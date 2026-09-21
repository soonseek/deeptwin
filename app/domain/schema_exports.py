"""Portable structural schemas; runtime remains authoritative for bytes and trust."""

import json
from pathlib import Path

from .events import EVENT_TYPES, event_schema
from .refs import ENTITY_KINDS, LOCATOR_KINDS, MAX_INTEGER, MAX_ITEMS, MAX_STRING_BYTES
from .schemas import (
    BOOTSTRAP_VERSION,
    GENESIS_VERSION,
    PURPOSES,
    ROOT_KINDS,
    SCHEMA_VERSION,
)

DRAFT = "https://json-schema.org/draft/2020-12/schema"
DOMAIN_ID = "urn:deeptwin:schemas:v1:domain-envelopes"
EVENTS_ID = "urn:deeptwin:schemas:v1:event-metadata"


def _object(properties, *, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def _constant(value):
    kind = "integer" if type(value) is int else "string"
    return {"type": kind, "const": value}


def _enum(values):
    return {"type": "string", "enum": sorted(values)}


def _uuid():
    return {"type": "string", "minLength": 36, "maxLength": 36,
            "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            "not": {"const": "00000000-0000-0000-0000-000000000000"}}


def _hash():
    return {"type": "string", "minLength": 64, "maxLength": 64,
            "pattern": "^[0-9a-f]{64}$"}


def _positive():
    return {"type": "integer", "minimum": 1, "maximum": MAX_INTEGER}


def _timestamp():
    return {"type": "string", "minLength": 27, "maxLength": 27,
            "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$",
            "format": "date-time",
            "$comment": "Runtime also validates the calendar date; format assertion support varies."}


def _ref(kind=None):
    reference = {"$ref": "#/$defs/EntityRef"}
    if kind is None:
        return reference
    return {"allOf": [reference, {"properties": {"kind": _constant(kind)}}]}


def _identity(schema_version, kind, *, bootstrap=False):
    return {"schema_version": _constant(schema_version), "kind": kind, "id": _uuid(),
            "version": _constant(1) if bootstrap else _positive(),
            "created_at_utc": _timestamp()}


def _provider_semantic_content_schemas():
    """Closed structural projections for the Task 47 durable semantic records.

    The Python validators still enforce the cross-record joins, exact port request/result
    branches and blob integrity.  Keeping the exported projections here avoids treating the
    portable schema as an authority oracle while ensuring a tagged record cannot fall back to
    the otherwise deliberately generic canonical-object branch.
    """
    ref = {"$ref": "#/$defs/EntityRef"}
    nullable_ref = {"anyOf": [ref, {"type": "null"}]}
    blob = _object({"vault_id": _uuid(), "purpose": _constant("operational"),
                    "sha256": _hash(), "size": {"type": "integer", "minimum": 0,
                                                   "maximum": MAX_INTEGER}})
    nullable_hash = {"anyOf": [_hash(), {"type": "null"}]}
    nullable_identifier = {"anyOf": [
        {"type": "string", "minLength": 1, "maxLength": 128,
         "pattern": "^[a-z][a-z0-9._:-]{0,127}$"},
        {"type": "null"},
    ]}
    canonical = {"$ref": "#/$defs/CanonicalObject"}
    from ..extensions.port_schema_generator import generate_port_schemas
    port_schemas = generate_port_schemas()
    canonical_config = port_schemas[("provider-port-v1", "config")]
    canonical_request = port_schemas[("provider-port-v1", "request")]
    canonical_result = port_schemas[("provider-port-v1", "result")]
    identifier = {"type": "string", "minLength": 1, "maxLength": 128,
                  "pattern": "^[a-z][a-z0-9._:-]{0,127}$"}
    port_time = {"type": "string", "minLength": 24, "maxLength": 24,
                 "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
                 "format": "date-time"}
    natural = {"type": "integer", "minimum": 0, "maximum": 9_007_199_254_740_991}
    positive = {"type": "integer", "minimum": 1, "maximum": 9_007_199_254_740_991}
    def optional_field(schema):
        return {"oneOf": [
            _object({"state": _constant("absent"), "value": {"type": "null"}}),
            _object({"state": _constant("null"), "value": {"type": "null"}}),
            _object({"state": _constant("value"), "value": schema}),
        ]}
    support = _object({"supported": {"type": "boolean"}})
    context = _object({"supported": {"type": "boolean"},
        "clear_thinking_20251015": optional_field(support),
        "clear_tool_uses_20250919": optional_field(support),
        "compact_20260112": optional_field(support)})
    effort = _object({"supported": {"type": "boolean"}, "high": support, "low": support,
                      "max": support, "medium": support, "xhigh": optional_field(support)})
    thinking = _object({"supported": {"type": "boolean"},
                        "types": _object({"adaptive": support, "enabled": support})})
    capabilities = _object({"batch": support, "citations": support,
        "code_execution": support, "context_management": context, "effort": effort,
        "image_input": support, "pdf_input": support, "structured_outputs": support,
        "thinking": thinking})
    model_projection = _object({"id": identifier,
        "display_name": {"type": "string", "minLength": 1, "maxLength": 512},
        "created_at": {"type": "string", "minLength": 20, "maxLength": 64},
        "capabilities": optional_field(capabilities),
        "max_input_tokens": optional_field(positive), "max_tokens": optional_field(positive)})
    credential_record = _object({"record_id": _uuid(), "record_version": positive,
                                 "ciphertext_sha256": _hash()})
    credential_metadata = _object({"command_id": _uuid(), "record_id": _uuid(),
        "record_version": positive, "provider": _constant("claude"),
        "auth_mode": _constant("api"), "created_at": _timestamp(),
        "predecessor": {"anyOf": [credential_record, {"type": "null"}]}})
    input_binding = _object({"artifact_ref": ref, "selector_ref": {"type": "null"},
        "declared_media_type": _constant("text/plain"), "role": _constant("model_input")})
    message = _object({"role": _enum({"system", "user", "assistant"}),
        "input_ordinals": {"type": "array", "minItems": 1, "maxItems": 4,
                           "items": {"type": "integer", "minimum": 0, "maximum": 3}}})
    instruction = _object({"profile_id": _constant("execution-model-step"),
                           "system_artifact_ref": nullable_ref})
    frozen_input = _object({"type": _constant("text"), "ref": ref,
                            "marker": {"type": "null"},
                            "omissions": {"type": "array", "maxItems": 0}})
    frozen_turn = _object({
        "profile": _constant("execution-model-step"), "work_ref": ref,
        "environment_ref": ref, "node_id": identifier, "execution_id": _uuid(),
        "attempt_index": natural, "provider": _constant("claude_api"),
        "account_id": identifier, "catalog_ref": ref, "model_id": identifier,
        "effort": {"type": "null"}, "instruction_profile_digest": _hash(),
        "inputs": {"type": "array", "minItems": 1, "maxItems": 4,
                   "items": frozen_input},
        "granted_tools": {"type": "array", "maxItems": 0},
        "output_schema_id": {"type": "null"}, "runtime_profile_ref": ref,
        "deadline_seconds": {"type": "integer", "minimum": 1, "maximum": 180},
        "budget_ref": ref, "consent_ref": ref,
    })
    cache_creation = _object({"ephemeral_1h_input_tokens": natural,
                              "ephemeral_5m_input_tokens": natural})
    output_details = _object({"thinking_tokens": natural})
    tool_usage = _object({"web_fetch_requests": natural, "web_search_requests": natural})
    schemas = {
        "provider-semantic-frozen-v1": _object({
            "schema_version": _constant("provider-semantic-frozen-v1"),
            "turn": frozen_turn,
            "execution_envelope_ref": ref,
            "purpose_ref": ref,
            "grant_refs": {"type": "array", "maxItems": 32, "uniqueItems": True,
                           "items": ref},
            "artifact_input_bindings": {"type": "array", "minItems": 1, "maxItems": 4,
                                        "items": input_binding},
            "messages": {"type": "array", "minItems": 1, "maxItems": 4,
                         "items": message},
            "max_output_tokens": {"type": "integer", "minimum": 1, "maximum": 8192},
            "instruction_projection": instruction,
        }),
        "provider-semantic-operation-v1": _object({
            "schema_version": _constant("provider-semantic-operation-v1"),
            "request": canonical_request,
            "config_ref": ref,
            "request_sha256": _hash(),
            "core_boot_id": _uuid(),
            "frozen_ref": nullable_ref,
            "envelope_ref": nullable_ref,
            "reservation_ref": nullable_ref,
        }),
        "provider-semantic-response-v1": _object({
            "schema_version": _constant("provider-semantic-response-v1"),
            "operation_ref": ref,
            "exchange_id": _uuid(),
            "proposal_sha256": _hash(),
            "status": {"anyOf": [{"type": "integer", "minimum": 100, "maximum": 599},
                                  {"type": "null"}]},
            "raw_blob": {"anyOf": [blob, {"type": "null"}]},
            "raw_sha256": nullable_hash,
            "raw_size": natural,
            "phase": _enum({"not_sent", "may_have_sent", "terminal_observed"}),
            "observed_model": nullable_identifier,
            "stop_reason": nullable_identifier,
            "cancel_observed": {"type": "boolean"},
            "failure_class": {"anyOf": [
                _enum({"permission_denied", "deadline_exceeded", "resource_exhausted",
                       "unsupported_capability", "integrity_failed",
                       "dependency_unavailable", "cancelled", "internal_failure"}),
                {"type": "null"},
            ]},
        }),
        "provider-semantic-usage-v1": _object({
            "schema_version": _constant("provider-semantic-usage-v1"),
            "operation_ref": ref,
            "response_ref": ref,
            "input_tokens": optional_field(natural),
            "output_tokens": optional_field(natural),
            "cache_creation_input_tokens": optional_field(natural),
            "cache_read_input_tokens": optional_field(natural),
            "cache_creation": optional_field(cache_creation),
            "output_tokens_details": optional_field(output_details),
            "server_tool_use": optional_field(tool_usage),
            "inference_geo": optional_field({"type": "string", "minLength": 1,
                                              "maxLength": 128}),
            "service_tier": optional_field(_enum({"standard", "priority", "batch"})),
            "unknown_categories": {"type": "array", "maxItems": 64,
                                   "uniqueItems": True,
                                   "items": {"type": "string", "minLength": 1,
                                             "maxLength": 512}},
            "cache_zero_basis": _constant("request_omits_cache_and_tools"),
            "currency_cost_known": {"type": "boolean", "const": False},
        }),
        "provider-semantic-effect-v1": _object({
            "schema_version": _constant("provider-semantic-effect-v1"),
            "operation_ref": ref,
            "response_ref": ref,
            "request_sha256": _hash(),
            "effect_state": _enum({"none", "not_committed", "committed", "unknown"}),
            "remote_outcome": _enum({"not_applicable", "confirmed", "unconfirmed", "unknown"}),
            "source": _constant("gateway_observation"),
        }),
        "provider-semantic-output-v1": _object({
            "schema_version": _constant("provider-semantic-output-v1"),
            "operation_ref": ref,
            "ordinal": {"type": "integer", "minimum": 0, "maximum": 3},
            "blob_ref": blob,
            "media_type": _constant("text/plain"),
            "content_digest": _hash(),
            "byte_count": {"type": "integer", "minimum": 0, "maximum": 524288},
        }),
        "provider-semantic-terminal-v1": _object({
            "schema_version": _constant("provider-semantic-terminal-v1"),
            "operation_ref": ref,
            "result": canonical_result,
            "response_ref": nullable_ref,
        }),
    }
    schemas.update({
        "provider-semantic-connection-v1": _object({
            "schema_version": _constant("provider-semantic-connection-v1"),
            "locator": _object({"kind": _constant("connection"), "id": _uuid()}),
            "revision_digest": _hash(), "provider_id": _constant("claude_api"),
            "account_id": identifier, "credential_metadata": credential_metadata,
            "credential_metadata_sha256": _hash(), "credential_record": credential_record}),
        "provider-semantic-config-v1": _object({
            "schema_version": _constant("provider-semantic-config-v1"), "config": canonical_config,
            "connection_ref": ref, "text_policy_ref": ref, "compatibility_set_ref": ref}),
        "provider-semantic-text-policy-v1": _object({
            "schema_version": _constant("provider-semantic-text-policy-v1"),
            "source_url": _constant("https://platform.claude.com/docs/en/models/overview"),
            "source_blob": blob, "source_sha256": _hash(), "retrieved_at": port_time,
            "reviewed_at": port_time, "valid_until": port_time,
            "scope_model_ids": {"type": "array", "minItems": 1, "maxItems": 256,
                                "uniqueItems": True, "items": identifier},
            "claim": _constant("current-models-text-input-output"), "reviewer_ref": ref}),
        "provider-semantic-reservation-v1": _object({
            "schema_version": _constant("provider-semantic-reservation-v1"),
            "connection_ref": ref, "model_id": identifier, "proposal_sha256": _hash(),
            "input_upper_bound": positive, "max_output_tokens": positive,
            "currency": {"type": "string", "minLength": 3, "maxLength": 3,
                         "pattern": "^[A-Z]{3}$"}, "reserved_microunits": positive,
            "effective_at": port_time, "expires_at": port_time, "method_blob": blob,
            "reviewer_ref": ref, "basis": _constant("reviewed-conservative-estimate")}),
        "provider-semantic-compatibility-set-v1": _object({
            "schema_version": _constant("provider-semantic-compatibility-set-v1"),
            "profile_id": _constant("claude-api-text-semantic-v1"), "connection_ref": ref,
            "observation_refs": {"type": "array", "maxItems": 256,
                                 "uniqueItems": True, "items": ref}}),
        "provider-semantic-compatibility-v1": _object({
            "schema_version": _constant("provider-semantic-compatibility-v1"),
            "profile_id": _constant("claude-api-text-semantic-v1"), "connection_ref": ref,
            "model_id": identifier, "request_policy_sha256": _hash(),
            "observed_at": port_time, "expires_at": port_time,
            "observation_ref": ref, "outcome": _constant("complete_text")}),
        "provider-semantic-page-v1": _object({
            "schema_version": _constant("provider-semantic-page-v1"), "operation_ref": ref,
            "index": {"type": "integer", "minimum": 0, "maximum": 19},
            "after_id": {"anyOf": [identifier, {"type": "null"}]}, "raw_blob": blob,
            "raw_sha256": _hash(), "raw_size": positive,
            "first_id": {"anyOf": [identifier, {"type": "null"}]},
            "last_id": {"anyOf": [identifier, {"type": "null"}]},
            "has_more": {"type": "boolean"},
            "model_ids": {"type": "array", "maxItems": 100, "uniqueItems": True,
                          "items": identifier}}),
        "provider-semantic-capability-v1": _object({
            "schema_version": _constant("provider-semantic-capability-v1"),
            "operation_ref": ref, "page_ref": ref,
            "model_index": {"type": "integer", "minimum": 0, "maximum": 99},
            "model_id": identifier, "text_policy_ref": ref, "compatibility_ref": nullable_ref,
            "observed_at": port_time, "valid_until": port_time, "projection": model_projection}),
        "provider-semantic-catalog-v1": _object({
            "schema_version": _constant("provider-semantic-catalog-v1"),
            "operation_ref": ref, "connection_ref": ref, "fetched_at": port_time,
            "expires_at": port_time,
            "page_refs": {"type": "array", "minItems": 1, "maxItems": 20, "items": ref},
            "complete": {"type": "boolean", "const": True},
            "models": {"type": "array", "maxItems": 256, "items": _object({
                "model_id": identifier, "display_name": {"type": "string", "minLength": 1,
                "maxLength": 512}, "modalities": {"type": "array", "maxItems": 1,
                "items": _constant("text")}, "effort_values": {"type": "array", "maxItems": 5,
                "uniqueItems": True, "items": _enum({"high", "low", "max", "medium", "xhigh"})},
                "capability_evidence_ref": ref})},
            "eligible_model_ids": {"type": "array", "maxItems": 256, "uniqueItems": True,
                                   "items": identifier},
            "excluded": {"type": "array", "maxItems": 256, "items": _object({
                "model_id": identifier, "reason": _enum({"capability_unknown", "limits_unknown",
                "text_scope_unproved", "profile_unproved"})})}}),
        "provider-semantic-idempotency-v1": _object({
            "schema_version": _constant("provider-semantic-idempotency-v1"),
            "request_id": _uuid(), "request_sha256": _hash(), "operation_ref": ref}),
        "provider-semantic-cancel-intent-v1": _object({
            "schema_version": _constant("provider-semantic-cancel-intent-v1"),
            "target_operation_ref": ref, "first_cancel_operation_ref": ref,
            "first_request_sha256": _hash(),
            "reason_class": _enum({"user_requested", "deadline", "budget", "superseded",
                                   "shutdown", "policy_revoked"}), "core_boot_id": _uuid()}),
    })
    return schemas


def domain_schema():
    """Export base envelopes, including narrow acyclic bootstrap variants.

    No returned object shares mutable state with the runtime registries or another call.
    Feature-specific content schemas must further constrain DomainBody.content.
    """
    entity = _object({"kind": _enum(ENTITY_KINDS), "id": _uuid(),
                      "version": _positive(), "sha256": _hash()})
    locator = _object({"kind": _enum(LOCATOR_KINDS), "id": _uuid(),
                       "version": _positive(), "content_hash": _hash()}, required=["kind", "id"])
    locator["$comment"] = "Navigation only; an ObjectRef never substitutes for an EntityRef."
    ordinary = _identity(SCHEMA_VERSION, _enum(ENTITY_KINDS - {"vault_genesis"}))
    ordinary.update({"actor_ref": _ref("actor"),
                     "parent_refs": {"type": "array", "maxItems": 256, "uniqueItems": True,
                                     "items": _ref()},
                     "purpose": _enum(PURPOSES), "access_policy_ref": _ref("access_policy"),
                     "retention_policy_ref": _ref("retention_policy"),
                     "content": {"$ref": "#/$defs/CanonicalObject"}})
    genesis = _identity(GENESIS_VERSION, _constant("vault_genesis"), bootstrap=True)
    genesis.update({"vault_id": _uuid(), "profile": _constant("local-deny-by-default-v1")})
    genesis = _object(genesis)
    genesis["$comment"] = "Runtime requires id == vault_id. Parsing grants no installation authority."
    bootstrap = _identity(BOOTSTRAP_VERSION, _enum(ROOT_KINDS), bootstrap=True)
    bootstrap.update({"genesis_ref": _ref("vault_genesis"), "content": {"type": "object"}})
    bootstrap = _object(bootstrap)
    root_payloads = {
        "actor": _object({"id": _uuid(), "kind": _constant("system"),
                           "origin": _constant("host_service")}),
        "access_policy": _object({"profile": _constant("deny-by-default-v1")}),
        "retention_policy": _object({"core_mode": _constant("manual_only"),
                                      "cache_max_age_days": _constant(14),
                                      "cache_max_bytes": _constant(1_073_741_824),
                                      "diagnostics_max_age_days": _constant(30),
                                      "diagnostics_max_bytes": _constant(104_857_600)}),
    }
    bootstrap["oneOf"] = [{"properties": {"kind": _constant(kind), "content": payload}}
                          for kind, payload in root_payloads.items()]
    bootstrap["$comment"] = ("Runtime requires actor content.id == header id. Only authenticated "
                             "atomic first store initialization may install the three roots.")
    string = {"type": "string", "maxLength": MAX_STRING_BYTES,
              "pattern": "^[^\\uD800-\\uDFFF]*$",
              "$comment": "Runtime additionally limits UTF-8 byte length, not only character count."}
    canonical_object = {"type": "object", "maxProperties": MAX_ITEMS,
                        "propertyNames": {"$ref": "#/$defs/CanonicalString"},
                        "additionalProperties": {"$ref": "#/$defs/CanonicalValue"}}
    canonical_value = {"anyOf": [{"type": "null"}, {"type": "boolean"},
                                  {"type": "integer", "minimum": -MAX_INTEGER, "maximum": MAX_INTEGER},
                                  {"$ref": "#/$defs/CanonicalString"},
                                  {"type": "array", "maxItems": MAX_ITEMS,
                                   "items": {"$ref": "#/$defs/CanonicalValue"}},
                                  {"$ref": "#/$defs/CanonicalObject"}]}
    body_variants = {"oneOf": [{"$ref": "#/$defs/" + name}
                               for name in ("DomainBody", "GenesisBody", "BootstrapBody")]}
    record = _object({"ref": _ref(), "body": body_variants})
    record["$comment"] = ("Runtime verifies ref identity/version and SHA-256 against the exact "
                          "canonical body bytes. Mutable observation metadata is separate.")
    from .worker_response import capture_content_schema

    capture_content = capture_content_schema()
    for name in ("execution_envelope_ref", "runtime_profile_ref"):
        capture_content["properties"][name]["allOf"][0]["$ref"] = "#/$defs/EntityRef"
    ordinary_body = _object(ordinary)
    ordinary_body["allOf"] = [{
        "if": {"properties": {"kind": _constant("worker_response_capture")}},
        "then": {"properties": {"version": _constant(1), "content": capture_content}},
    }]
    from .deployment_request import anchor_content_schema

    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("deployment_request")}},
        "then": {"properties": {"version": _constant(1), "purpose": _constant("operational"),
                                "content": anchor_content_schema(),
                                "parent_refs": {"type": "array", "minItems": 1, "maxItems": 1,
                                                "items": {"allOf": [_ref("extension_manifest"),
                                                                     {"properties": {"version": _constant(1)}}]}}}},
        "$comment": "Runtime also requires header id == content.request_id and the parent == content.candidate_ref.",
    })
    from ..extensions.provider_conformance_schema_exports import record_body_condition

    conformance = record_body_condition()
    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("provider_conformance_run")}},
        "then": conformance,
        "$comment": ("Runtime additionally verifies command/header identity, context digest, "
                     "deadline arithmetic, result relations, exact ordered parents and byte caps."),
    })
    from .deployment_receipt import consumption_content_variants, receipt_content_schema

    receipt_request = _ref("deployment_request")
    receipt_request["allOf"].append({"properties": {"version": _constant(1)}})
    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("deployment_receipt")}},
        "then": {"properties": {"version": _constant(1), "purpose": _constant("operational"),
                                "content": receipt_content_schema(),
                                "parent_refs": {"type": "array", "minItems": 1, "maxItems": 1,
                                                "items": receipt_request}}},
        "$comment": ("Runtime also requires header id and sole parent to match request_ref, "
                     "all four blobs to share one vault and the complete body to fit 8192 bytes. "
                     "Structure grants no import authority."),
    })
    consumption_request = _ref("deployment_request")
    consumption_request["allOf"].append({"properties": {"version": _constant(1)}})
    consumption_receipt = _ref("deployment_receipt")
    consumption_receipt["allOf"].append({"properties": {"version": _constant(1)}})
    consumption_installation = _ref("extension_installation")
    consumption_installation["allOf"].append({"properties": {"version": _constant(1)}})
    consumption_parents = [consumption_request, consumption_receipt, consumption_installation]
    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("deployment_receipt_consumption")}},
        # each content variant is paired with its exact parent arity: the v1
        # non-success shape has the request and receipt parents, the v2 success
        # shape adds the installation it created
        "then": {"oneOf": [
            {"properties": {"version": _constant(1), "purpose": _constant("operational"),
                            "content": content,
                            "parent_refs": {"type": "array", "minItems": arity,
                                            "maxItems": arity,
                                            "prefixItems": consumption_parents[:arity],
                                            "items": False}}}
            for content, arity in consumption_content_variants()]},
        "$comment": ("Runtime also requires exact ordered duplicated parents, matching request/"
                     "receipt ids (and the v2 effect as the third parent), actor and six-digit "
                     "consumption time, and caps the complete body at 8192 bytes. Event syntax "
                     "proves no event exists."),
    })
    from .extension_installation import installation_content_schema

    installation_request = _ref("deployment_request")
    installation_request["allOf"].append({"properties": {"version": _constant(1)}})
    installation_receipt = _ref("deployment_receipt")
    installation_receipt["allOf"].append({"properties": {"version": _constant(1)}})
    from ..extensions.provider_installation_schema_exports import record_body_condition as verified_installation_body
    ordinary_body["allOf"].append({
        "if": {"properties": {"kind": _constant("extension_installation")}},
        "then": {"oneOf": [{"properties": {"version": _constant(1), "purpose": _constant("operational"),
                                "content": installation_content_schema(),
                                "parent_refs": {"type": "array", "minItems": 2, "maxItems": 2,
                                                "prefixItems": [installation_request,
                                                                installation_receipt],
                                                "items": False}}}, verified_installation_body()]},
        "$comment": ("Runtime also requires the ordered duplicated request/receipt parents with "
                     "matching ids, the actor, the six-digit installation time, an operational "
                     "evidence blob and the 8192-byte cap. Structure grants no installation, "
                     "acceptance or head authority."),
    })
    from .owner_material import content_schemas

    for profile, (kind, content) in content_schemas().items():
        ordinary_body["allOf"].append({
            "if": {"properties": {"content": {"properties": {"schema_version": _constant(profile)},
                                               "required": ["schema_version"]}}},
            "then": {"properties": {"kind": _constant(kind), "purpose": _constant("operational"),
                                    "content": content,
                                    **({"version": _constant(1)} if kind in {"source", "artifact"} else {})}},
            "$comment": "Runtime also verifies exact ancestry, actor, blob size/digest and bounded indication consistency.",
        })
    for profile, content in _provider_semantic_content_schemas().items():
        kind = ("frozen_turn" if profile == "provider-semantic-frozen-v1" else
                "artifact" if profile == "provider-semantic-output-v1" else
                "model_catalog" if profile == "provider-semantic-catalog-v1" else
                "validation_report")
        ordinary_body["allOf"].append({
            "if": {"properties": {"content": {"properties": {
                "schema_version": _constant(profile)}, "required": ["schema_version"]}}},
            "then": {"properties": {"kind": _constant(kind), "version": _constant(1),
                                    "purpose": _constant("operational"), "content": content}},
            "$comment": ("Runtime additionally validates exact semantic joins, ancestry, "
                         "request/result branches and referenced blob bytes."),
        })
    return {"$schema": DRAFT, "$id": DOMAIN_ID,
            "title": "DeepTwin version 1 immutable record envelopes", "$ref": "#/$defs/Record",
            "$comment": ("Structural envelope contract only. Runtime also checks canonical compact "
                         "sorted UTF-8 bytes, integer lexical representation, Unicode scalars, "
                         "64 KiB strings, 1 MiB total bytes, depth 32 and 10000 total items, "
                         "reference/body equality, non-self/future parents, hash integrity, "
                         "same-vault resolution, lineage, trusted provenance and authorization. "
                         "Feature schemas further constrain domain content. Schema validity "
                         "never grants root installation, human approval or dispatch authority."),
            "$defs": {"EntityRef": entity, "ObjectRef": locator,
                      "DomainBody": ordinary_body, "GenesisBody": genesis,
                      "BootstrapBody": bootstrap, "Record": record,
                      "CanonicalString": string, "CanonicalObject": canonical_object,
                      "CanonicalValue": canonical_value}}


def events_schema():
    """Export exact registered metadata payloads, selected through their $defs fragment."""
    return {"$schema": DRAFT, "$id": EVENTS_ID,
            "title": "DeepTwin version 1 public event metadata payloads",
            "$comment": ("Select the exact event type through #/$defs/<category.action>. "
                         "This document is a payload schema registry, not the EventEnvelope "
                         "or a substitute for authenticated emission or private-detail access. "
                         "Metadata observations are optional unless the selected event schema "
                         "requires its exact field set; absence means unknown."),
            "$defs": {name: event_schema(name) for name in sorted(EVENT_TYPES)}}


def write_domain_schemas(destination):
    """Deterministically export domain registries and the closed capture content."""
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    from ..services.owner_auth_schema import owner_auth_schema
    from .worker_response import capture_schema

    for name, schema in (
        ("domain-envelopes.schema.json", domain_schema()),
        ("event-metadata.schema.json", events_schema()),
        ("worker-response-capture.schema.json", capture_schema()),
        ("owner-auth-public.schema.json", owner_auth_schema()),
    ):
        (root / name).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
