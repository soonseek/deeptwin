"""Deterministic provider-only image lineage schema export."""

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
    obj,
    text,
)
from .provider_identity_schema_exports import provider_build_identity_schema

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


def provider_lineage_schema() -> dict:
    """Return a fresh closed Draft 2020-12 provider lineage schema."""

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
            build_identity={
                "allOf": [
                    {"$ref": "#/$defs/provider_identity"},
                    {
                        "type": "object",
                        "properties": {"platform": const(platform)},
                        "required": ["platform"],
                    },
                ]
            },
            extraction_evidence_sha256=text(64, HEX),
        )
        for platform in _PLATFORMS
    )
    return {
        "$schema": DRAFT,
        "$id": "urn:deeptwin:schemas:v2:extensions:provider-build-lineage-v2",
        "$comment": _COMMENT,
        **obj(
            schema_version=const("extension-build-lineage-v2"),
            extension_id=text(128, ID),
            extension_version=text(32, VERSION),
            port_contract_version=const("provider-port-v1"),
            launch_profile=const("provider-private-transform-v1"),
            index=index,
            platforms=_ordered_array(platforms),
        ),
        "$defs": {"provider_identity": provider_build_identity_schema()},
    }


def exported_schemas() -> dict[str, dict]:
    """Return the sole provider lineage export in deterministic filename order."""

    return {"provider-build-lineage-v2.schema.json": provider_lineage_schema()}


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[2] / "schemas/v2/extensions"
    for name, schema in exported_schemas().items():
        content = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        (destination / name).write_text(content, encoding="utf-8")
