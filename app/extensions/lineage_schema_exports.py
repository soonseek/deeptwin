"""Deterministic structural schemas for inert extension image lineage values."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .candidate_schema_exports import (
    DRAFT,
    HEX,
    ID,
    VERSION,
    const,
    descriptor_schema,
    enum,
    integer,
    obj,
    text,
)
from .port_contracts import PORT_SCHEMA_SHAPES

_COMMENT = (
    "Structural only; these values grant no authentication, qualification, "
    "installation, binding, measurement, trust, or execution authority."
)
_PLATFORMS = ("linux/amd64", "linux/arm64")


def _ordered_array(values: tuple[dict, ...]) -> dict:
    return {
        "type": "array",
        "prefixItems": list(values),
        "items": False,
        "minItems": len(values),
        "maxItems": len(values),
    }


def _identity_value_schema(platform: str | None = None) -> dict:
    sized_bytes = obj(sha256=text(64, HEX), size_bytes=integer(1, 1_073_741_824))
    schema_files = tuple(
        obj(role=const(role), sha256=text(64, HEX), size_bytes=integer(1, 262_144))
        for role in PORT_SCHEMA_SHAPES
    )
    return obj(
        schema_version=const("extension-build-identity-v1"),
        extension_id=text(128, ID),
        extension_version=text(32, VERSION),
        platform=const(platform) if platform is not None else enum(*_PLATFORMS),
        port_contract_version=const("tool-port-v1"),
        inputs=obj(
            schema_version=const("extension-build-inputs-v1"),
            source_bundle=deepcopy(sized_bytes),
            build_recipe=deepcopy(sized_bytes),
            dependency_input_set=deepcopy(sized_bytes),
        ),
        entrypoint=obj(sha256=text(64, HEX), size_bytes=integer(1, 16_777_216)),
        port_schemas=_ordered_array(schema_files),
    )


def _document(name: str, value: dict) -> dict:
    return {
        "$schema": DRAFT,
        "$id": "urn:deeptwin:schemas:v1:extensions:" + name,
        "$comment": _COMMENT,
        **value,
    }


def build_identity_schema() -> dict:
    """Return a fresh Draft 2020-12 schema for a per-platform identity."""

    return _document("build-identity-v1", _identity_value_schema())


def lineage_schema() -> dict:
    """Return a fresh schema containing the complete existing OCI entry shapes."""

    descriptor = descriptor_schema()
    index = deepcopy(descriptor["properties"]["index"])
    platform_entry = descriptor["properties"]["platforms"]["items"]
    platforms = tuple(
        obj(
            measured_platform_entry={
                **deepcopy(platform_entry),
                "properties": {
                    **deepcopy(platform_entry["properties"]),
                    "platform": const(platform),
                },
            },
            build_identity=_identity_value_schema(platform),
            extraction_evidence_sha256=text(64, HEX),
        )
        for platform in _PLATFORMS
    )
    return _document(
        "build-lineage-v1",
        obj(
            schema_version=const("extension-build-lineage-v1"),
            extension_id=text(128, ID),
            extension_version=text(32, VERSION),
            port_contract_version=const("tool-port-v1"),
            launch_profile=const("extension-fixed-slot-argv-v1"),
            index=index,
            platforms=_ordered_array(platforms),
        ),
    )


def exported_schemas() -> dict[str, dict]:
    """Return new lineage exports in deterministic filename order."""

    return {
        "build-identity-v1.schema.json": build_identity_schema(),
        "build-lineage-v1.schema.json": lineage_schema(),
    }


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[2] / "schemas/v1/extensions"
    for name, schema in exported_schemas().items():
        content = (
            json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
        (destination / name).write_text(content, encoding="utf-8")
