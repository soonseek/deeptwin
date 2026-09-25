"""The provider-transport manifest and its qualification document (T087 → T090).

A provider-transport manifest (`provider-transport-manifest-v1`) is the closed, data-owned
request surface of one `provider-port-v1` provider's credentialed transport: the pinned
API origin (the port config's `api_origin`), the allowed methods and absolute path
prefixes, the projected request headers with their fixed values, the header the gateway
injects the credential into, the request/response byte bounds and the two endpoints the
send dialogue names (`messages`, `models`) with their method, path, fixed query, cursor
parameter and accepted response media type. The Claude API manifest ships as canonical
JSON beside this module (`transport_manifests/claude-api-v1.json`); its identity is the
SHA-256 of those exact bytes. Nothing here is a code constant of the transport: the
gateway's `ProviderBinding` is built only from a parsed manifest.

A manifest authorizes nothing by itself. It is *qualified* by the control plane's
qualification act (`app/extensions/provider_transport_qualification.py`): a matched
verified-installation conformance run of the provider port (the T087 installation and
conformance path) plus an offline transport conformance of this exact manifest against a
local mock provider. The result is a nonsecret qualification document
(`provider-transport-qualification-v1`) naming the manifest digest. The control plane
publishes it to the gateway (`bind_transport`), the gateway journals it, and the send
path delivers custody only while the adopted qualification names the digest of the
manifest the transport was built from: an unqualified manifest, or a manifest whose bytes
changed after qualification, refuses every send before any provider byte.

This module is pure (no vault, no network) and is imported by both sides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from ..domain.refs import (
    DomainContractError,
    EntityRef,
    canonical_json,
    parse_canonical,
)

MANIFEST_SCHEMA = "provider-transport-manifest-v1"
QUALIFICATION_SCHEMA = "provider-transport-qualification-v1"
CLAUDE_API_MANIFEST = Path(__file__).with_name("transport_manifests") / "claude-api-v1.json"
MAX_MANIFEST_BYTES = 8_192
ENDPOINTS = ("messages", "models")
VECTOR_COUNT = 4

_PROVIDER = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]{0,253}[a-z0-9])?\Z")
_HEADER_NAME = re.compile(r"[a-z0-9-]{1,64}\Z")
_HEADER_VALUE = re.compile(r"[\x21-\x7e]([\x20-\x7e]{0,254}[\x21-\x7e])?\Z")
_PATH = re.compile(r"/[A-Za-z0-9/_.-]{0,1023}\Z")
_QUERY_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_MEDIA = re.compile(r"[a-z]+/[a-z0-9.+-]{1,64}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
# Headers the transport frames itself or that must never be caller-projected.
FORBIDDEN_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie", "host",
    "transfer-encoding", "content-encoding", "content-length", "connection",
    "upgrade", "te", "trailer", "keep-alive", "forwarded", "x-forwarded-for",
    "x-forwarded-host", "x-forwarded-proto",
})


class TransportManifestError(ValueError):
    """A manifest or qualification document is not the closed shape."""


def _require(condition, message="provider transport manifest is invalid"):
    if not condition:
        raise TransportManifestError(message)


def _exact(value, keys):
    _require(type(value) is dict and set(value) == set(keys))
    return value


def _bounded_int(value, low, high):
    _require(type(value) is int and low <= value <= high)
    return value


def _under(path, prefixes):
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


@dataclass(frozen=True, slots=True)
class TransportEndpoint:
    name: str
    method: str
    path: str
    query: tuple[tuple[str, str], ...]
    cursor_parameter: str | None
    request_body: str
    response_media_type: str


@dataclass(frozen=True, slots=True, init=False)
class TransportManifest:
    """A parsed manifest; only :func:`parse_transport_manifest` constructs one."""

    content_bytes: bytes
    manifest_sha256: str
    provider: str
    provider_id: str
    api_origin: str
    scheme: str
    host: str
    port: int
    allowed_methods: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    request_headers: tuple[tuple[str, str], ...]
    auth_header: str
    max_request_bytes: int
    max_response_bytes: int
    timeout_seconds: int
    endpoints: tuple[TransportEndpoint, ...]

    def __new__(cls, *args, **kwargs):
        raise TypeError("a transport manifest requires the parser")

    def endpoint(self, name):
        for endpoint in self.endpoints:
            if endpoint.name == name:
                return endpoint
        raise TransportManifestError("provider endpoint is not in the manifest")


def parse_transport_manifest(raw: bytes) -> TransportManifest:
    """Parse the exact canonical manifest bytes into a closed value (fail closed)."""
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST_BYTES)
        value = parse_canonical(raw)
        _exact(value, ("schema_version", "port_contract_version", "provider", "provider_id",
                       "auth_mode", "api_origin", "allowed_methods", "allowed_path_prefixes",
                       "request_headers", "auth_header", "max_request_bytes",
                       "max_response_bytes", "timeout_seconds", "endpoints"))
        _require(value["schema_version"] == MANIFEST_SCHEMA
                 and value["port_contract_version"] == "provider-port-v1"
                 and value["auth_mode"] == "api")
        _require(type(value["provider"]) is str and _PROVIDER.fullmatch(value["provider"]) is not None)
        _require(type(value["provider_id"]) is str
                 and _IDENTIFIER.fullmatch(value["provider_id"]) is not None)
        origin = value["api_origin"]
        _require(type(origin) is str and len(origin) <= 255)
        split = urlsplit(origin)
        # the production origin is HTTPS with no path, query, fragment or credentials
        _require(split.scheme == "https" and split.path == "" and not split.query
                 and not split.fragment and split.username is None and split.password is None
                 and split.hostname is not None and _HOST.fullmatch(split.hostname) is not None
                 and origin == "https://" + split.netloc)
        port = split.port if split.port is not None else 443
        _bounded_int(port, 1, 65_535)
        methods = value["allowed_methods"]
        _require(type(methods) is list and methods and methods == sorted(set(methods))
                 and all(method in ("GET", "POST") for method in methods))
        prefixes = value["allowed_path_prefixes"]
        _require(type(prefixes) is list and prefixes and prefixes == sorted(set(prefixes))
                 and all(type(prefix) is str and _PATH.fullmatch(prefix) is not None
                         and ".." not in prefix and not prefix.startswith("//")
                         for prefix in prefixes))
        headers = value["request_headers"]
        _require(type(headers) is dict and len(headers) <= 16)
        for name, header_value in headers.items():
            _require(_HEADER_NAME.fullmatch(name) is not None and name not in FORBIDDEN_HEADERS
                     and type(header_value) is str
                     and _HEADER_VALUE.fullmatch(header_value) is not None)
        auth = value["auth_header"]
        _require(type(auth) is str and _HEADER_NAME.fullmatch(auth) is not None
                 and auth not in FORBIDDEN_HEADERS and auth not in headers)
        max_request = _bounded_int(value["max_request_bytes"], 1, 8 * 1024 * 1024)
        max_response = _bounded_int(value["max_response_bytes"], 1, 8 * 1024 * 1024)
        timeout = _bounded_int(value["timeout_seconds"], 1, 600)
        endpoints_value = value["endpoints"]
        _require(type(endpoints_value) is dict and sorted(endpoints_value) == list(ENDPOINTS))
        endpoints = []
        for name in ENDPOINTS:
            item = _exact(endpoints_value[name], ("method", "path", "query", "cursor_parameter",
                                                  "request_body", "response_media_type"))
            _require(item["method"] in methods)
            _require(type(item["path"]) is str and _PATH.fullmatch(item["path"]) is not None
                     and ".." not in item["path"] and _under(item["path"], prefixes))
            query = item["query"]
            _require(type(query) is list and len(query) <= 8)
            pairs = []
            for pair in query:
                _require(type(pair) is list and len(pair) == 2
                         and all(type(part) is str and _QUERY_TOKEN.fullmatch(part) is not None
                                 for part in pair))
                pairs.append((pair[0], pair[1]))
            cursor = item["cursor_parameter"]
            _require(cursor is None or (type(cursor) is str
                                        and _QUERY_TOKEN.fullmatch(cursor) is not None
                                        and cursor not in {key for key, _ in pairs}))
            _require(item["request_body"] in ("required", "empty"))
            _require(type(item["response_media_type"]) is str
                     and _MEDIA.fullmatch(item["response_media_type"]) is not None)
            endpoints.append(TransportEndpoint(name, item["method"], item["path"], tuple(pairs),
                                               cursor, item["request_body"],
                                               item["response_media_type"]))
        # the send dialogue's own shape: a message is a POST with a body, a model page a
        # GET with no body and an explicit cursor
        _require(endpoints[0].method == "POST" and endpoints[0].request_body == "required"
                 and endpoints[0].cursor_parameter is None)
        _require(endpoints[1].method == "GET" and endpoints[1].request_body == "empty"
                 and endpoints[1].cursor_parameter is not None)
    except TransportManifestError:
        raise
    except (DomainContractError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise TransportManifestError("provider transport manifest is invalid") from None
    result = object.__new__(TransportManifest)
    for name, field_value in {
        "content_bytes": raw, "manifest_sha256": sha256(raw).hexdigest(),
        "provider": value["provider"], "provider_id": value["provider_id"],
        "api_origin": origin, "scheme": "https", "host": split.hostname, "port": port,
        "allowed_methods": tuple(methods), "allowed_path_prefixes": tuple(prefixes),
        "request_headers": tuple(sorted(headers.items())), "auth_header": auth,
        "max_request_bytes": max_request, "max_response_bytes": max_response,
        "timeout_seconds": timeout, "endpoints": tuple(endpoints),
    }.items():
        object.__setattr__(result, name, field_value)
    return result


def endpoint_request(endpoints, request_headers, endpoint, after_id):
    """(method, request target, projected headers, accepted response media type) of one
    send-dialogue endpoint of a manifest's endpoint table; the one request builder the
    gateway's binding and the offline transport conformance share."""
    for spec in endpoints:
        if spec.name == endpoint:
            break
    else:
        raise TransportManifestError("provider endpoint is not in the manifest")
    query = list(spec.query)
    if spec.cursor_parameter is not None and after_id is not None:
        _require(type(after_id) is str and 0 < len(after_id) <= 256, "cursor is invalid")
        query.append((spec.cursor_parameter, after_id))
    elif after_id is not None:
        raise TransportManifestError("provider endpoint has no cursor")
    target = spec.path + ("?" + urlencode(query, safe="") if query else "")
    return spec.method, target, dict(request_headers), spec.response_media_type


def host_header(scheme, host, port):
    return host if port == {"http": 80, "https": 443}[scheme] else f"{host}:{port}"


def claude_api_manifest_bytes() -> bytes:
    """The exact shipped bytes of the Claude API provider-transport manifest."""
    with open(CLAUDE_API_MANIFEST, "rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    _require(len(raw) <= MAX_MANIFEST_BYTES)
    return raw


def claude_api_manifest() -> TransportManifest:
    return parse_transport_manifest(claude_api_manifest_bytes())


def _ref(value, kind, version=None):
    try:
        ref = EntityRef.from_dict(value)
    except (DomainContractError, TypeError, ValueError):
        raise TransportManifestError("qualification reference is invalid") from None
    _require(ref.kind == kind and (version is None or ref.version == version))
    return ref


def parse_qualification(value) -> dict:
    """Validate a `provider-transport-qualification-v1` document (a detached copy).

    It is nonsecret and names: the manifest digest; the control plane's sealed
    qualification record; the matched verified-installation conformance run of the
    provider port; and the matched offline transport conformance of this manifest."""
    try:
        _exact(value, ("schema_version", "provider", "revision", "manifest_sha256",
                       "qualification_ref", "installation_conformance", "transport_conformance"))
        _require(value["schema_version"] == QUALIFICATION_SCHEMA)
        _require(type(value["provider"]) is str and _PROVIDER.fullmatch(value["provider"]) is not None)
        _bounded_int(value["revision"], 1, 253402300799999)
        _require(type(value["manifest_sha256"]) is str
                 and _HEX.fullmatch(value["manifest_sha256"]) is not None)
        _ref(value["qualification_ref"], "validation_report", 1)
        installation = _exact(value["installation_conformance"], (
            "command_id", "staged_installation_ref", "verified_installation_ref", "result_ref",
            "suite_sha256", "completed_count", "matched_count"))
        staged = _ref(installation["staged_installation_ref"], "extension_installation", 1)
        verified = _ref(installation["verified_installation_ref"], "extension_installation", 2)
        _require(staged.id == verified.id)
        result = _ref(installation["result_ref"], "provider_conformance_run", 2)
        _require(result.id == installation["command_id"])
        transport = _exact(value["transport_conformance"], (
            "suite_sha256", "result_sha256", "completed_count", "matched_count"))
        for section in (installation, transport):
            _require(type(section["suite_sha256"]) is str
                     and _HEX.fullmatch(section["suite_sha256"]) is not None)
            # qualification is all-or-nothing: every fixed vector completed and matched
            _require(section["completed_count"] == VECTOR_COUNT
                     and section["matched_count"] == VECTOR_COUNT)
        _require(type(transport["result_sha256"]) is str
                 and _HEX.fullmatch(transport["result_sha256"]) is not None)
        detached = parse_canonical(canonical_json(value))
        _require(len(canonical_json(detached)) <= 4_096)
        return detached
    except TransportManifestError:
        raise
    except (DomainContractError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise TransportManifestError("provider transport qualification is invalid") from None


__all__ = [
    "CLAUDE_API_MANIFEST", "ENDPOINTS", "FORBIDDEN_HEADERS", "MANIFEST_SCHEMA",
    "QUALIFICATION_SCHEMA", "TransportEndpoint", "TransportManifest", "TransportManifestError",
    "claude_api_manifest", "claude_api_manifest_bytes", "parse_qualification",
    "parse_transport_manifest",
]
