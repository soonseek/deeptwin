"""Pure provider-only image lineage value and exact descriptor/schema join."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from jsonschema import Draft202012Validator

from ..domain.refs import canonical_json, parse_canonical
from ..domain.wire import WireLimits, parse_json_object
from .candidate_contracts import ExtensionServiceDescriptor, metadata_ref
from .provider_identity import (
    parse_provider_build_identity,
    validate_provider_schema_bytes,
)
from .provider_lineage_schema_exports import provider_lineage_schema

_FIELDS = (
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
_LIMITS = WireLimits(
    max_bytes=65_536,
    max_depth=8,
    max_items=4_096,
    max_members=16,
    max_string_bytes=256,
    max_integer=2**40,
)


class ProviderLineageError(ValueError):
    """Uniform non-reflective rejection for provider lineage values."""

    def __init__(self) -> None:
        super().__init__("invalid provider lineage value")


def _invalid() -> ProviderLineageError:
    return ProviderLineageError()


def _valid_version(value: object) -> bool:
    return (
        type(value) is str
        and len(value.encode("utf-8")) <= 32
        and _VERSION.fullmatch(value) is not None
        and all(int(component) <= 2**31 - 1 for component in value.split("."))
    )


def _decode(raw: object) -> dict:
    value = parse_json_object(raw, required=_FIELDS, limits=_LIMITS)  # type: ignore[arg-type]
    if canonical_json(value) != raw or not Draft202012Validator(
        provider_lineage_schema()
    ).is_valid(value):
        raise _invalid()
    return value


def _validate_value(raw: object) -> dict:
    value = _decode(raw)
    if not _valid_version(value["extension_version"]):
        raise _invalid()
    for expected_platform, item in zip(_PLATFORMS, value["platforms"], strict=True):
        entry = item["measured_platform_entry"]
        identity = parse_provider_build_identity(
            canonical_json(item["build_identity"])
        ).as_dict()
        if (
            entry["platform"] != expected_platform
            or identity["platform"] != expected_platform
            or identity["extension_id"] != value["extension_id"]
            or identity["extension_version"] != value["extension_version"]
            or identity["port_contract_version"] != value["port_contract_version"]
            or identity["worker_profile"] != "claude-text-transform-v1"
            or [layer["position"] for layer in entry["layers"]]
            != list(range(1, len(entry["layers"]) + 1))
        ):
            raise _invalid()
    return value


def _stored_bytes(value: object, expected_type: type) -> bytes:
    if type(value) is not expected_type:
        raise _invalid()
    try:
        raw = object.__getattribute__(value, "content_bytes")
    except AttributeError:
        raise _invalid() from None
    if type(raw) is not bytes:
        raise _invalid()
    return raw


def _revalidated(value: object) -> tuple[bytes, dict]:
    raw = _stored_bytes(value, ProviderLineage)
    try:
        return raw, _validate_value(raw)
    except ProviderLineageError:
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


@dataclass(frozen=True, slots=True, init=False)
class ProviderLineage:
    """Canonical bytes are the sole stored truth for inert provider lineage."""

    content_bytes: bytes

    def __new__(cls):
        raise TypeError("Use parse_provider_lineage")

    @property
    def digest(self) -> str:
        raw, _ = _revalidated(self)
        return sha256(raw).hexdigest()

    def as_dict(self) -> dict:
        _, value = _revalidated(self)
        return value

    def selected_platform(self, platform: str) -> dict:
        if type(platform) is not str or platform not in _PLATFORMS:
            raise _invalid()
        _, value = _revalidated(self)
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

    def selected_platform_digest(self, platform: str) -> str:
        return sha256(canonical_json(self.selected_platform(platform))).hexdigest()


def parse_provider_lineage(raw: bytes) -> ProviderLineage:
    """Parse strict canonical provider lineage without granting runtime authority."""

    try:
        _validate_value(raw)
        result = object.__new__(ProviderLineage)
        object.__setattr__(result, "content_bytes", raw)
        return result
    except ProviderLineageError:
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


def validate_provider_descriptor_lineage(
    lineage: ProviderLineage,
    descriptor: ExtensionServiceDescriptor,
    *,
    instance_id: str,
    slot_number: int,
    schema_bytes: tuple[bytes, bytes, bytes, bytes],
) -> None:
    """Require the complete structural provider join; return no authority token."""

    try:
        if (
            type(lineage) is not ProviderLineage
            or type(descriptor) is not ExtensionServiceDescriptor
            or type(instance_id) is not str
            or _INSTANCE_ID.fullmatch(instance_id) is None
            or type(slot_number) is not int
            or not 1 <= slot_number <= 16
            or type(schema_bytes) is not tuple
            or len(schema_bytes) != 4
            or any(type(raw) is not bytes for raw in schema_bytes)
        ):
            raise _invalid()
        lineage_raw = _stored_bytes(lineage, ProviderLineage)
        lineage_value = parse_provider_lineage(lineage_raw).as_dict()
        descriptor_raw = _stored_bytes(descriptor, ExtensionServiceDescriptor)
        descriptor_value = ExtensionServiceDescriptor.from_mapping(
            parse_canonical(descriptor_raw)
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
            != metadata_ref("provenance", lineage_raw)
            or descriptor_value["command"] != expected_command
        ):
            raise _invalid()
        for item in lineage_value["platforms"]:
            identity = parse_provider_build_identity(
                canonical_json(item["build_identity"])
            )
            validate_provider_schema_bytes(identity, schema_bytes)
    except ProviderLineageError:
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
