"""Portable JSON Schemas for extension packages and lifecycle records."""

from copy import deepcopy
import json
from pathlib import Path

from .contracts import (
    EXTENSION_KINDS,
    INSTALLATION_STATES,
    INSTALL_AUTHORITIES,
    MANDATORY_QUALIFICATION_CHECKS,
    QUALIFICATION_RESULTS,
    QUALIFICATION_RECHECK_TRIGGERS,
    TRUST_TIERS,
)


DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _object(properties, *, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else list(required),
        "additionalProperties": False,
    }


def _string(maximum=256, *, enum=None, pattern=None, const=None):
    result = {"type": "string", "minLength": 1, "maxLength": maximum}
    if enum is not None:
        result["enum"] = sorted(enum)
    if pattern is not None:
        result["pattern"] = pattern
    if const is not None:
        result["const"] = const
    return result


def _hash():
    return _string(64, pattern="^[0-9a-f]{64}$")


def _uuid():
    return _string(36, pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _version():
    return _string(32, pattern="^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")


def _strings(*, digest=False, maximum=64):
    return {"type": "array", "maxItems": maximum, "uniqueItems": True,
            "items": _hash() if digest else _string()}


def _scope():
    nullable_uuid = {"anyOf": [_uuid(), {"type": "null"}]}
    result = _object({
        "instance_id": _uuid(),
        "environment_id": deepcopy(nullable_uuid),
        "work_id": deepcopy(nullable_uuid),
        "node_id": deepcopy(nullable_uuid),
        "purpose": {"anyOf": [
            _string(enum={"operational", "diagnosis", "inquiry_audit",
                          "evaluation_development", "evaluation_sealed", "release_evidence"}),
            {"type": "null"},
        ]},
    })
    has_string = lambda name: {
        "properties": {name: {"type": "string"}}, "required": [name],
    }
    requires_strings = lambda names: {
        "properties": {name: {"type": "string"} for name in names},
        "required": list(names),
    }
    result["allOf"] = [
        {"if": has_string("work_id"),
         "then": requires_strings(("environment_id",))},
        {"if": has_string("node_id"),
         "then": requires_strings(("environment_id", "work_id"))},
    ]
    return result


def _base(identifier, title, properties):
    return {
        "$schema": DRAFT,
        "$id": f"urn:deeptwin:schemas:v1:extensions:{identifier}",
        "title": title,
        "$comment": ("Structural data only. Schema validity, discovery, import, or a source label "
                     "never grants installation, execution, secret, network, human, or deployment authority."),
        **_object(properties),
    }


def _manifest_schema():
    schema_value = {
        "type": "object",
        "required": ["type"],
        "properties": {
            "type": {"enum": ["object", "array", "string", "integer", "boolean", "null"]},
        },
    }
    result = _base("manifest", "DeepTwin extension manifest v1", {
        "schema_version": _string(const="extension-manifest-v1"),
        "extension_id": _string(128, pattern="^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$"),
        "extension_version": _version(),
        "extension_kind": _string(enum=EXTENSION_KINDS),
        "artifact": _object({
            "type": _string(enum={"package", "image", "definition"}),
            "sha256": _hash(),
        }),
        "source": _object({
            "kind": _string(enum={"built_in", "third_party", "operator_deployment"}),
            "locator": _string(2048),
            "provenance_sha256": _hash(),
        }),
        "license_expression": _string(),
        "compatibility": _object({
            "extension_api": _version(),
            "framework_min": _version(),
            "framework_max": _version(),
            "schema_versions": {**_strings(), "minItems": 1},
        }),
        "entrypoint": _object({
            "protocol": _string(enum={"definition-v1", "worker-json-v1",
                                       "managed-provider-rpc-v1", "deployment-port-v1"}),
            "name": _string(128, pattern="^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$"),
        }),
        "config_schema": deepcopy(schema_value),
        "input_schema": deepcopy(schema_value),
        "output_schema": deepcopy(schema_value),
        "declared_grants": _strings(),
        "declared_resources": _strings(),
        "network_needs": _strings(),
        "filesystem_needs": _strings(),
        "secret_needs": _strings(),
        "isolation_profile": _string(
            128, pattern="^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$",
        ),
        "migration_policy": _string(enum={"none", "compatible", "required"}),
        "uninstall_policy": _string(enum={"retain_records", "block_if_bound"}),
    })
    protocol_is = lambda value: {
        "properties": {"entrypoint": {
            "properties": {"protocol": {"const": value}}, "required": ["protocol"],
        }},
        "required": ["entrypoint"],
    }
    artifact_is = lambda value: {
        "properties": {"artifact": {
            "properties": {"type": {"const": value}}, "required": ["type"],
        }},
        "required": ["artifact"],
    }
    kind_is = lambda values: {
        "properties": {"extension_kind": {"enum": list(values)}},
        "required": ["extension_kind"],
    }
    result["allOf"] = [
        {"if": protocol_is("definition-v1"),
         "then": {"allOf": [artifact_is("definition"), kind_is(("lens", "evaluator"))]}},
        {"if": artifact_is("definition"), "then": protocol_is("definition-v1")},
        {"if": kind_is(("lens",)), "then": protocol_is("definition-v1")},
        {"if": kind_is(("storage", "credential_vault")),
         "then": protocol_is("deployment-port-v1")},
        {"if": protocol_is("managed-provider-rpc-v1"), "then": kind_is(("provider",))},
    ]
    return result


def _installation_schema():
    return _base("installation", "DeepTwin extension installation v1", {
        "schema_version": _string(const="extension-installation-v1"),
        "installation_id": _uuid(),
        "manifest_digest": _hash(),
        "installed_artifact": _object({
            "type": _string(enum={"package", "image", "definition"}),
            "sha256": _hash(),
        }),
        "extension_kind": _string(enum=EXTENSION_KINDS),
        "trust_tier": _string(enum=TRUST_TIERS),
        "install_authority": _string(enum=INSTALL_AUTHORITIES),
        "actor_id": _uuid(),
        "installed_at_utc": _string(27),
        "state": _string(enum=INSTALLATION_STATES),
        "revision": {"type": "integer", "minimum": 1, "maximum": 9223372036854775807},
        "previous_state": {"anyOf": [_string(enum=INSTALLATION_STATES), {"type": "null"}]},
        "previous_record_digest": {"anyOf": [_hash(), {"type": "null"}]},
        "verification_refs": _strings(digest=True, maximum=256),
        "scan_refs": _strings(digest=True, maximum=256),
    })


def _qualification_schema():
    return _base("qualification", "DeepTwin extension qualification v1", {
        "schema_version": _string(const="extension-qualification-v1"),
        "qualification_id": _uuid(),
        "installation_id": _uuid(),
        "installation_revision": {"type": "integer", "minimum": 1,
                                  "maximum": 9223372036854775807},
        "installation_record_digest": _hash(),
        "manifest_digest": _hash(),
        "artifact_digest": _hash(),
        "platform_digest": _hash(),
        "runtime_digest": _hash(),
        "framework_version": _version(),
        "extension_api_version": _version(),
        "schema_version_bound": _string(128),
        "conformance_suite": _string(
            128, pattern="^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$",
        ),
        "conformance_version": _version(),
        "declared_capabilities_digest": _hash(),
        "observed_capabilities_digest": _hash(),
        "results": _object({name: _string(enum=QUALIFICATION_RESULTS)
                            for name in MANDATORY_QUALIFICATION_CHECKS}),
        "failure_details": _object(
            {name: _string(128, pattern="^[a-z][a-z0-9_.-]{0,127}$")
             for name in MANDATORY_QUALIFICATION_CHECKS},
            required=[],
        ),
        "evidence_refs": {**_strings(digest=True, maximum=256), "minItems": 1},
        "qualified_scope": _scope(),
        "evidence_verified": {"type": "boolean"},
        "qualified_at": {"type": "integer", "minimum": 0,
                         "maximum": 9223372036854775807},
        "expires_at": {"type": "integer", "minimum": 1,
                       "maximum": 9223372036854775807},
        "recheck_triggers": {
            "type": "array", "minItems": len(QUALIFICATION_RECHECK_TRIGGERS),
            "maxItems": len(QUALIFICATION_RECHECK_TRIGGERS), "uniqueItems": True,
            "prefixItems": [
                _string(const=value) for value in QUALIFICATION_RECHECK_TRIGGERS
            ],
            "items": False,
        },
        "status": _string(enum={"qualified", "failed"}),
    })


def _binding_schema():
    return _base("binding", "DeepTwin extension binding v1", {
        "schema_version": _string(const="extension-binding-v1"),
        "binding_id": _uuid(),
        "installation_id": _uuid(),
        "qualification_id": _uuid(),
        "manifest_digest": _hash(),
        "extension_kind": _string(enum=EXTENSION_KINDS),
        "trust_tier": _string(enum=TRUST_TIERS),
        "scope": _scope(),
        "config_ref": _hash(),
        "credential_handle_refs": _strings(digest=True, maximum=256),
        "grant_refs": _strings(digest=True, maximum=256),
        "enabled_revision": {"type": "integer", "minimum": 1,
                             "maximum": 9223372036854775807},
        "transmit_authorized": {"type": "boolean", "const": False},
    })


def extension_schemas():
    return {
        "manifest.schema.json": _manifest_schema(),
        "installation.schema.json": _installation_schema(),
        "qualification.schema.json": _qualification_schema(),
        "binding.schema.json": _binding_schema(),
    }


def write_extension_schemas(destination):
    """Deterministically export reviewed runtime schemas for packaging and SDKs."""
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    for name, schema in extension_schemas().items():
        target = root / name
        target.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    write_extension_schemas(Path(__file__).resolve().parents[2] / "schemas" / "v1" / "extensions")
