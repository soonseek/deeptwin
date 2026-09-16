"""Pure immutable extension image identity and lineage structural values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from jsonschema import Draft202012Validator

from ..domain.refs import canonical_json, parse_canonical
from ..domain.wire import WireLimits, parse_json_object
from .candidate_contracts import ExtensionServiceDescriptor, metadata_ref
from .lineage_schema_exports import build_identity_schema, lineage_schema
from .port_contracts import PORT_SCHEMA_SHAPES

_IDENTITY_FIELDS = (
    "schema_version",
    "extension_id",
    "extension_version",
    "platform",
    "port_contract_version",
    "inputs",
    "entrypoint",
    "port_schemas",
)
_LINEAGE_FIELDS = (
    "schema_version",
    "extension_id",
    "extension_version",
    "port_contract_version",
    "launch_profile",
    "index",
    "platforms",
)
_PLATFORMS = ("linux/amd64", "linux/arm64")
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_INSTANCE_ID = re.compile(r"[0-9a-f]{32}")
_IDENTITY_LIMITS = WireLimits(
    max_bytes=8_192,
    max_depth=4,
    max_items=128,
    max_members=16,
    max_string_bytes=256,
    max_integer=2**40,
)
_LINEAGE_LIMITS = WireLimits(
    max_bytes=65_536,
    max_depth=8,
    max_items=4_096,
    max_members=16,
    max_string_bytes=256,
    max_integer=2**40,
)


class LineageContractError(ValueError):
    """One uniform non-reflective rejection for untrusted lineage values."""

    def __init__(self) -> None:
        super().__init__("invalid lineage value")


def _invalid() -> LineageContractError:
    return LineageContractError()


def _valid_version(value: object) -> bool:
    if (
        type(value) is not str
        or len(value.encode("utf-8")) > 32
        or _VERSION.fullmatch(value) is None
    ):
        return False
    return all(int(component) <= 2**31 - 1 for component in value.split("."))


def _decode(
    raw: object, *, fields: tuple[str, ...], limits: WireLimits, schema: dict
) -> dict:
    try:
        value = parse_json_object(raw, required=fields, limits=limits)  # type: ignore[arg-type]
        if canonical_json(value) != raw or not Draft202012Validator(schema).is_valid(
            value
        ):
            raise _invalid()
        return value
    except LineageContractError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, MemoryError):
        raise _invalid() from None


def _validate_identity_value(value: dict) -> None:
    if not _valid_version(value["extension_version"]):
        raise _invalid()
    roles = tuple(item["role"] for item in value["port_schemas"])
    if roles != PORT_SCHEMA_SHAPES:
        raise _invalid()
    if sum(item["size_bytes"] for item in value["port_schemas"]) > 1_048_576:
        raise _invalid()


def _stored_bytes(value: object) -> bytes:
    """Return the exact-class instance's canonical bytes or refuse.

    Class membership alone proves nothing: a hollow or corrupted instance
    (absent or non-bytes state) must surface as the sanitized contract
    error, never as AttributeError from a slot lookup.
    """

    try:
        stored = object.__getattribute__(value, "content_bytes")
    except AttributeError:
        raise _invalid() from None
    if type(stored) is not bytes:
        raise _invalid()
    return stored


def _parse_identity(raw: object) -> dict:
    value = _decode(
        raw,
        fields=_IDENTITY_FIELDS,
        limits=_IDENTITY_LIMITS,
        schema=build_identity_schema(),
    )
    _validate_identity_value(value)
    return value


@dataclass(frozen=True, slots=True, init=False)
class BuildIdentity:
    """Canonical bytes are the sole stored truth for one inert build declaration."""

    content_bytes: bytes

    def __new__(cls):
        raise TypeError("Use parse_build_identity")

    @property
    def digest(self) -> str:
        return sha256(self.content_bytes).hexdigest()

    @property
    def input_digest(self) -> str:
        return sha256(canonical_json(self.as_dict()["inputs"])).hexdigest()

    @property
    def schema_set_digest(self) -> str:
        return sha256(canonical_json(self.as_dict()["port_schemas"])).hexdigest()

    def as_dict(self) -> dict:
        return parse_canonical(self.content_bytes)


@dataclass(frozen=True, slots=True, init=False)
class LineageEvidence:
    """Canonical bytes are the sole stored truth for full two-platform lineage."""

    content_bytes: bytes

    def __new__(cls):
        raise TypeError("Use parse_lineage")

    @property
    def digest(self) -> str:
        return sha256(self.content_bytes).hexdigest()

    def as_dict(self) -> dict:
        return parse_canonical(self.content_bytes)

    def selected_platform(self, platform: str) -> dict:
        if type(platform) is not str or platform not in _PLATFORMS:
            raise _invalid()
        try:
            value = parse_canonical(_stored_bytes(self))
            entry = value["platforms"][_PLATFORMS.index(platform)][
                "measured_platform_entry"
            ]
            return {
                "platform": platform,
                "index_digest": value["index"]["digest"],
                "manifest_digest": entry["manifest"]["digest"],
                "config_digest": entry["config"]["digest"],
                "ordered_layer_digests": [layer["digest"] for layer in entry["layers"]],
            }
        except LineageContractError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            AttributeError,
            UnicodeError,
            RecursionError,
            MemoryError,
        ):
            raise _invalid() from None

    def selected_platform_digest(self, platform: str) -> str:
        return sha256(canonical_json(self.selected_platform(platform))).hexdigest()


def parse_build_identity(raw: bytes) -> BuildIdentity:
    """Parse strict canonical bytes without granting build or runtime authority."""

    _parse_identity(raw)
    result = object.__new__(BuildIdentity)
    object.__setattr__(result, "content_bytes", raw)
    return result


def parse_lineage(raw: bytes) -> LineageEvidence:
    """Parse complete two-platform structural evidence as an inert value."""

    try:
        value = _decode(
            raw, fields=_LINEAGE_FIELDS, limits=_LINEAGE_LIMITS, schema=lineage_schema()
        )
        if not _valid_version(value["extension_version"]):
            raise _invalid()
        for expected_platform, item in zip(_PLATFORMS, value["platforms"], strict=True):
            entry = item["measured_platform_entry"]
            identity = _parse_identity(canonical_json(item["build_identity"]))
            if (
                entry["platform"] != expected_platform
                or identity["platform"] != expected_platform
                or identity["extension_id"] != value["extension_id"]
                or identity["extension_version"] != value["extension_version"]
                or identity["port_contract_version"] != value["port_contract_version"]
                or [layer["position"] for layer in entry["layers"]]
                != list(range(1, len(entry["layers"]) + 1))
            ):
                raise _invalid()
        result = object.__new__(LineageEvidence)
        object.__setattr__(result, "content_bytes", raw)
        return result
    except LineageContractError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, MemoryError):
        raise _invalid() from None


def validate_schema_bytes(
    identity: BuildIdentity,
    schema_bytes: tuple[bytes, bytes, bytes, bytes],
) -> None:
    """Match caller-supplied schema bytes to all four declared role records."""

    try:
        if (
            type(identity) is not BuildIdentity
            or type(schema_bytes) is not tuple
            or len(schema_bytes) != 4
        ):
            raise _invalid()
        if any(type(raw) is not bytes for raw in schema_bytes):
            raise _invalid()
        declarations = parse_build_identity(_stored_bytes(identity)).as_dict()[
            "port_schemas"
        ]
        for role, declaration, raw in zip(
            PORT_SCHEMA_SHAPES, declarations, schema_bytes, strict=True
        ):
            if (
                declaration["role"] != role
                or len(raw) != declaration["size_bytes"]
                or sha256(raw).hexdigest() != declaration["sha256"]
            ):
                raise _invalid()
    except LineageContractError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, MemoryError):
        raise _invalid() from None


def validate_descriptor_lineage(
    lineage: LineageEvidence,
    descriptor: ExtensionServiceDescriptor,
    *,
    instance_id: str,
    slot_number: int,
) -> None:
    """Require an exact structural descriptor join; return no capability token."""

    try:
        if (
            type(lineage) is not LineageEvidence
            or type(descriptor) is not ExtensionServiceDescriptor
            or type(instance_id) is not str
            or _INSTANCE_ID.fullmatch(instance_id) is None
            or type(slot_number) is not int
            or not 1 <= slot_number <= 16
        ):
            raise _invalid()
        lineage_bytes = _stored_bytes(lineage)
        lineage_value = parse_lineage(lineage_bytes).as_dict()
        descriptor_value = ExtensionServiceDescriptor.from_mapping(
            parse_canonical(_stored_bytes(descriptor))
        ).as_dict()
        expected_command = {
            "protocol_id": "deeptwin-extension-worker-v1",
            "argv": [
                "/opt/deeptwin-extension/bin/worker",
                "--instance-id",
                instance_id,
                "--slot-number",
                str(slot_number),
            ],
        }
        measured_entries = [
            item["measured_platform_entry"] for item in lineage_value["platforms"]
        ]
        if (
            descriptor_value["extension_id"] != lineage_value["extension_id"]
            or descriptor_value["extension_version"]
            != lineage_value["extension_version"]
            or descriptor_value["port_contract_version"]
            != lineage_value["port_contract_version"]
            or descriptor_value["index"] != lineage_value["index"]
            or descriptor_value["platforms"] != measured_entries
            or descriptor_value["evidence"]["provenance_ref"]
            != metadata_ref("provenance", lineage_bytes)
            or descriptor_value["command"] != expected_command
        ):
            raise _invalid()
    except LineageContractError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
        MemoryError,
    ):
        raise _invalid() from None
