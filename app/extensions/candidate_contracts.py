"""Pure, frozen executable metadata. No stage, loader, channel or runtime authority."""

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import unquote_to_bytes

from jsonschema import Draft202012Validator

from ..domain.refs import canonical_json, parse_canonical, uuid_string
from .candidate_schema_exports import descriptor_schema, input_schema, manifest_schema
from .port_contracts import PORT_CONTRACTS, validate_port_tuple
from .port_schema_generator import validate_refinement_schema


class CandidateError(ValueError):
    def __init__(self, code="invalid_input"):
        self.code = code
        super().__init__("Candidate request could not be admitted")


def require(condition):
    if not condition:
        raise CandidateError()


def bounded(value, maximum):
    raw = canonical_json(value)
    if len(raw) > maximum:
        raise CandidateError("too_large")
    return raw


def plain(value, maximum):
    require(
        type(value) is str
        and 0 < len(value.encode()) <= maximum
        and not any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)
    )


def version(value):
    parts = tuple(int(p) for p in value.split("."))
    require(len(parts) == 3 and all(p <= 2**31 - 1 for p in parts))
    return parts


def ordered(values, key=lambda v: v):
    keys = [key(value) for value in values]
    require(keys == sorted(keys) and len(keys) == len(set(keys)))


def canonical_host(value):
    require(type(value) is str and value.isascii() and value == value.lower())
    port = None
    if value.startswith("["):
        match = re.fullmatch(r"\[([0-9a-f:]+)\](?::([0-9]+))?", value)
        require(match is not None)
        host, port = match.groups()
        address = ipaddress.IPv6Address(host)
        require(address.compressed == host and address.ipv4_mapped is None)
    else:
        pieces = value.split(":")
        require(len(pieces) in (1, 2))
        host = pieces[0]
        port = pieces[1] if len(pieces) == 2 else None
        require(
            len(host) <= 253 and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p) for p in host.split("."))
        )
        if re.fullmatch(r"[0-9.]+", host):
            require(str(ipaddress.IPv4Address(host)) == host)
    if port is not None:
        require(re.fullmatch(r"[1-9][0-9]{0,4}", port) is not None and int(port) <= 65535)


def source_uri(value):
    require(value.isascii() and len(value) <= 2048 and value.startswith("https://"))
    authority, sep, path = value[8:].partition("/")
    canonical_host(authority)
    if sep:
        require(re.fullmatch(r"(?:[A-Za-z0-9._~!$&'()*+,;=:@/-]|%[0-9A-F]{2})*", path) is not None)
        for segment in path.split("/"):
            raw = unquote_to_bytes(segment)
            require(raw not in (b".", b"..") and not any(b < 32 or b == 127 or b in (47, 92) for b in raw))


def image_repository(value):
    require(value.isascii() and len(value) <= 512)
    host, sep, path = value.partition("/")
    require(bool(sep))
    canonical_host(host)
    require(all(re.fullmatch(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*", part) for part in path.split("/")))


def _manifest(value):
    require(Draft202012Validator(manifest_schema()).is_valid(value))
    version(value["extension_version"])
    port = PORT_CONTRACTS[value["port_contract_version"]]
    require(port.artifact_form != "code_free_definition")
    validate_port_tuple(
        extension_kind=value["extension_kind"],
        artifact_form=value["artifact"]["artifact_form"],
        port_contract_version=value["port_contract_version"],
        trust_tier=port.trust_tier,
        staging_authority=min(port.staging_authorities),
    )
    source_uri(value["source"]["locator"])
    plain(value["license"]["expression"], 256)
    compatibility = value["compatibility"]
    for namespace in ("framework", "extension_api"):
        require(version(compatibility[namespace + "_min"]) <= version(compatibility[namespace + "_max"]))
    ordered(compatibility["schema_versions"])
    refinements = value["refinements"]
    ordered(refinements["operations"], lambda v: v["operation"])
    schemas = [refinements["config"]]
    for operation in refinements["operations"]:
        require(operation["operation"] in port.operations)
        ordered(operation["extension_error_codes"])
        schemas.extend((operation["request"], operation["result"]))
    for schema in schemas:
        bounded(schema, 65536)
        validate_refinement_schema(schema)
    for name in ("grant_ids", "filesystem_needs", "secret_needs"):
        ordered(value["requirements"][name])


def _descriptor(value):
    require(Draft202012Validator(descriptor_schema()).is_valid(value))
    version(value["extension_version"])
    require(PORT_CONTRACTS[value["port_contract_version"]].artifact_form != "code_free_definition")
    image_repository(value["image_repository"])
    ordered(value["platforms"], lambda v: v["platform"])
    for platform in value["platforms"]:
        require([layer["position"] for layer in platform["layers"]] == list(range(1, len(platform["layers"]) + 1)))
    for arg in value["command"]["argv"]:
        plain(arg, 256)
    first = value["command"]["argv"][0]
    require(
        first.startswith("/")
        and "\\" not in first
        and "%" not in first
        and all(part not in ("", ".", "..") for part in first[1:].split("/"))
    )
    ordered(value["secret_needs"])
    mounts = value["socket_mounts"] + value["named_volume_mounts"]
    for key in ("mount_id", "volume_name", "container_path"):
        require(len({m[key] for m in mounts}) == len(mounts))
    for name, prefix in (
        ("socket_mounts", "/run/deeptwin/ipc/"),
        ("named_volume_mounts", "/var/lib/deeptwin-extension/"),
    ):
        ordered(value[name], lambda m: m["mount_id"])
        for mount in value[name]:
            require(mount["container_path"] == prefix + mount["mount_id"])
    endpoint = value["broker_endpoint"]
    require(
        endpoint["responder_service"] == value["service_identity"]
        and endpoint["protocol_id"] == value["command"]["protocol_id"]
        and endpoint["requester_service"] != endpoint["responder_service"]
        and endpoint["requester_uid"] != value["uid"]
        and endpoint["requester_gid"] != value["gid"]
        and endpoint["pair_gid"] not in (value["gid"], endpoint["requester_gid"])
        and endpoint["socket_mount_id"] in {m["mount_id"] for m in value["socket_mounts"]}
    )


@dataclass(frozen=True, slots=True, init=False)
class _Document:
    content_bytes: bytes

    def __new__(cls):
        raise TypeError("Use from_mapping")

    @classmethod
    def from_mapping(cls, value):
        try:
            raw = bounded(value, 262144)
            detached = parse_canonical(raw)
            (_manifest if cls is ExecutableExtensionManifest else _descriptor)(detached)
            result = object.__new__(cls)
            object.__setattr__(result, "content_bytes", raw)
            return result
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise CandidateError() from None

    @property
    def digest(self):
        return sha256(self.content_bytes).hexdigest()

    def as_dict(self):
        return parse_canonical(self.content_bytes)


class ExecutableExtensionManifest(_Document):
    __slots__ = ()


class ExtensionServiceDescriptor(_Document):
    __slots__ = ()


@dataclass(frozen=True, slots=True)
class CandidateBundle:
    content_bytes: bytes
    manifest: ExecutableExtensionManifest
    descriptor: ExtensionServiceDescriptor
    # (kind, exact bytes), sorted by kind and digest, detached and immutable.
    documents: tuple[tuple[str, bytes], ...]

    @property
    def digest(self):
        return sha256(self.content_bytes).hexdigest()

    def as_dict(self):
        return parse_canonical(self.content_bytes)


def metadata_ref(kind, raw):
    return {"document_kind": kind, "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}


def parse_bundle(value):
    try:
        raw = bounded(value, 1048576)
        value = parse_canonical(raw)
        require(Draft202012Validator(input_schema()).is_valid(value))
        uuid_string(value["command_id"])
        manifest = ExecutableExtensionManifest.from_mapping(value["manifest"])
        descriptor = ExtensionServiceDescriptor.from_mapping(value["service_descriptor"])
        m, d = manifest.as_dict(), descriptor.as_dict()
        require(m["artifact"]["service_descriptor_ref"] == metadata_ref("service_descriptor", descriptor.content_bytes))
        for field in ("extension_id", "extension_version", "port_contract_version"):
            require(m[field] == d[field])
        for field in ("network_policy_ref", "resource_profile_ref", "isolation_profile_ref", "secret_needs"):
            require(m["requirements"][field] == d[field])
        require(
            m["source"]["provenance_ref"] == d["evidence"]["provenance_ref"]
            and m["license"]["text_ref"] == d["evidence"]["license_ref"]
        )
        leaves = []
        for entry in value["documents"]:
            content = entry["content"]
            leaf = content.encode() if entry["document_kind"] == "license" else bounded(content, 65536)
            require(0 < len(leaf) <= 65536)
            if entry["document_kind"] == "resource_declaration":
                require(content["tmpfs_bytes"] <= content["memory_bytes"])
            leaves.append((entry["document_kind"], leaf))
        actual = [metadata_ref(kind, raw) for kind, raw in leaves]
        required = [
            d[field] for field in ("network_policy_ref", "resource_profile_ref", "isolation_profile_ref")
        ] + list(d["evidence"].values())
        keys = lambda refs: {canonical_json(ref) for ref in refs}
        require(len(keys(actual)) == len(actual) and keys(actual) == keys(required))
        return CandidateBundle(
            raw, manifest, descriptor, tuple(sorted(leaves, key=lambda p: (p[0], sha256(p[1]).hexdigest())))
        )
    except CandidateError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise CandidateError() from None
