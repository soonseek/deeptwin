"""Separate provider v2 structural export; the tool v1 export stays unchanged."""

from .lineage_schema_exports import build_identity_schema


def provider_build_identity_schema():
    value = build_identity_schema()
    value["$id"] = "urn:deeptwin:schemas:v2:extensions:provider-build-identity-v2"
    value["properties"]["schema_version"] = {"const": "extension-build-identity-v2"}
    value["properties"]["port_contract_version"] = {"const": "provider-port-v1"}
    value["properties"]["worker_profile"] = {"const": "claude-text-transform-v1"}
    value["required"].append("worker_profile")
    return value


def exported_schemas():
    return {"provider-build-identity-v2.schema.json": provider_build_identity_schema()}
