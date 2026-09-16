"""Deterministic core-owned JSON Schemas for semantic extension ports.

The catalog in :mod:`app.extensions.port_contracts` owns the closed port/operation
partitions.  This module expands that catalog into Draft 2020-12 schemas and performs
the cross-field checks JSON Schema cannot express.  Generation and validation are pure;
``write_port_schemas`` is the sole filesystem boundary.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from ..domain.refs import canonical_json
from .port_contracts import (
    ALLOWED_EFFECT_TUPLES,
    ALLOWED_TERMINAL_CANDIDATES,
    EFFECT_FAMILIES,
    OPERATION_CONTRACTS,
    PORT_CONTRACTS,
    PORT_SCHEMA_IDS,
    PORT_SCHEMA_SHAPES,
    REQUEST_ARTIFACT_PROFILES,
    RESULT_ARTIFACT_METADATA,
    TERMINALS_BY_CLASS,
    BindingSlotKeyV1,
    PortContractError,
)

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_ENVELOPE_BYTES = 1_048_576
MAX_NESTING = 8
MAX_STRING = 4_096

IDENTIFIER_PATTERN = r"^[a-z][a-z0-9._:-]{0,127}$"
TEXT_PATTERN = r"^[^\u0000-\u001f\u007f-\u009f]+$"
MEDIA_TYPE_PATTERN = (
    r"^[a-z0-9][a-z0-9!#$&^_.+\-]{0,126}/"
    r"[a-z0-9][a-z0-9!#$&^_.+\-]{0,126}$"
)
DIGEST_PATTERN = r"^[0-9a-f]{64}$"
TIME_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
    r"[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class PortSchemaValidationError(ValueError):
    """A base payload or extension refinement violates the core contract."""


def _object(properties: Mapping[str, Any], *, required: tuple[str, ...] | None = None,
            max_properties: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties) if required is None else list(required),
        "additionalProperties": False,
    }
    if max_properties is not None:
        result["maxProperties"] = max_properties
    return result


def _string(*, minimum: int = 1, maximum: int = MAX_STRING,
            pattern: str | None = None, enum: tuple[str, ...] | None = None,
            const: str | None = None, fmt: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string", "minLength": minimum,
                              "maxLength": maximum}
    if pattern is not None:
        result["pattern"] = pattern
    if enum is not None:
        result["enum"] = list(enum)
    if const is not None:
        result["const"] = const
    if fmt is not None:
        result["format"] = fmt
    return result


def _identifier(*, const: str | None = None) -> dict[str, Any]:
    return _string(maximum=128, pattern=IDENTIFIER_PATTERN, const=const)


def _effort_value() -> dict[str, Any]:
    return _string(maximum=80)


def _short_text(*, maximum: int = 512) -> dict[str, Any]:
    return _string(maximum=maximum, pattern=TEXT_PATTERN)


def _version_text() -> dict[str, Any]:
    return _string(maximum=128, pattern=TEXT_PATTERN)


def _media_type(*, const: str | None = None) -> dict[str, Any]:
    return _string(maximum=255, pattern=MEDIA_TYPE_PATTERN, const=const)


def _https_uri() -> dict[str, Any]:
    return _string(maximum=2048, pattern=r"^https://[^/?#]+(?:/[^#]*)?$", fmt="uri")


def _integer(*, minimum: int = 0, maximum: int = MAX_SAFE_INTEGER) -> dict[str, Any]:
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def _positive(*, maximum: int = MAX_SAFE_INTEGER) -> dict[str, Any]:
    return _integer(minimum=1, maximum=maximum)


def _digest() -> dict[str, Any]:
    return _string(minimum=64, maximum=64, pattern=DIGEST_PATTERN)


def _time() -> dict[str, Any]:
    return _string(minimum=24, maximum=24, pattern=TIME_PATTERN)


def _uuid() -> dict[str, Any]:
    return _string(minimum=36, maximum=36, pattern=UUID_PATTERN)


def _enum(*values: str) -> dict[str, Any]:
    return _string(maximum=max(map(len, values)), enum=tuple(values))


def _nullable(schema: Mapping[str, Any]) -> dict[str, Any]:
    return {"oneOf": [deepcopy(dict(schema)), {"type": "null"}]}


def _array(items: Mapping[str, Any], *, minimum: int = 0, maximum: int = 256,
           unique: bool = False, sorted_unique: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "array", "minItems": minimum, "maxItems": maximum,
        "items": deepcopy(dict(items)),
    }
    if unique or sorted_unique:
        result["uniqueItems"] = True
    if sorted_unique:
        result["x-deeptwin-sorted"] = "canonical-json-byte-order"
    return result


def _empty_object() -> dict[str, Any]:
    return _object({})


def _empty_array() -> dict[str, Any]:
    return _array({}, maximum=0)


def _extension_object() -> dict[str, Any]:
    return {
        "type": "object",
        "maxProperties": 64,
        "propertyNames": _identifier(),
        "x-deeptwin-requires-closed-refinement": True,
    }


def _ref() -> dict[str, Any]:
    return _object({
        "kind": _identifier(),
        "id": _uuid(),
        "version": _positive(),
        "sha256": _digest(),
    })


def _ref_array(*, sorted_unique: bool = False) -> dict[str, Any]:
    return _array(_ref(), sorted_unique=sorted_unique)


def _identifier_array(*, sorted_unique: bool = False) -> dict[str, Any]:
    return _array(_identifier(), sorted_unique=sorted_unique)


def _effort_value_array(*, sorted_unique: bool = False) -> dict[str, Any]:
    return _array(_effort_value(), sorted_unique=sorted_unique)


def _media_array(*, sorted_unique: bool = False) -> dict[str, Any]:
    return _array(_media_type(), sorted_unique=sorted_unique)


def _binding_slot_key() -> dict[str, Any]:
    return _object({
        "port_contract_version": _identifier(),
        "target_scope_fingerprint": _digest(),
        "purpose": _identifier(),
        "binding_slot_id": _identifier(),
        "capability_selector_digest": _digest(),
    })


def _artifact_input_binding() -> dict[str, Any]:
    return _object({
        "artifact_ref": _ref(),
        "selector_ref": _nullable(_ref()),
        "declared_media_type": _media_type(),
        "role": _identifier(),
    })


def _artifact_result_binding(*, role: str | None = None,
                             omissions: str = "optional") -> dict[str, Any]:
    properties = {
        "artifact_ref": _ref(),
        "media_type": _media_type(),
        "role": _identifier(const=role) if role is not None else _identifier(),
        "content_digest": _digest(),
        "byte_count": _integer(),
        "omissions_ref": _nullable(_ref()),
    }
    if omissions == "forbidden":
        properties["omissions_ref"] = {"type": "null"}
    elif omissions == "required":
        properties["omissions_ref"] = _ref()
    return _object(properties)


def _resource_limits() -> dict[str, Any]:
    return _object({
        "deadline_ms": _positive(maximum=600_000),
        "max_input_bytes": _positive(maximum=1_048_576),
        "max_output_bytes": _positive(maximum=1_048_576),
        "max_artifacts": _integer(maximum=256),
        "max_artifact_bytes": _positive(maximum=67_108_864),
        "max_artifact_input_bytes": _positive(maximum=67_108_864),
    })


def _usage() -> dict[str, Any]:
    return _object({
        "input_units": _nullable(_integer()),
        "output_units": _nullable(_integer()),
        "billed_units": _nullable(_integer()),
        "unit_name": _nullable(_identifier()),
        "provider_report_ref": _nullable(_ref()),
    })


def _status_input() -> dict[str, Any]:
    return _object({"operation_ref": _ref()})


def _status_output() -> dict[str, Any]:
    return _object({
        "observed_state": _enum(
            "pending", "running", "succeeded", "failed", "cancelled", "unknown",
        ),
        "observed_at": _time(),
        "terminal_result_ref": _nullable(_ref()),
    })


def _cancel_input() -> dict[str, Any]:
    return _object({
        "operation_ref": _ref(),
        "reason_class": _enum(
            "user_requested", "deadline", "budget", "superseded", "shutdown",
            "policy_revoked",
        ),
    })


def _cancel_output() -> dict[str, Any]:
    return _object({
        "cancel_state": _enum("accepted", "already_terminal", "not_cancellable"),
        "observed_at": _time(),
    })


def _model_step_input() -> dict[str, Any]:
    return _object({
        "frozen_turn_ref": _ref(),
        "model_id": _identifier(),
        "effort": _nullable(_effort_value()),
        "requested_modalities": _identifier_array(sorted_unique=True),
        "tool_definition_refs": _ref_array(sorted_unique=True),
        "response_schema_ref": _nullable(_ref()),
    })


def _models_output() -> dict[str, Any]:
    model = _object({
        "model_id": _identifier(),
        "display_name": _short_text(),
        "modalities": _identifier_array(sorted_unique=True),
        "effort_values": _effort_value_array(sorted_unique=True),
        "capability_evidence_ref": _ref(),
    })
    return _array(model)


def _provider_step_output(response_field: str) -> dict[str, Any]:
    return _object({
        "provider_id" if response_field == "provider_response_ref" else "runtime_profile_ref": (
            _identifier() if response_field == "provider_response_ref" else _ref()
        ),
        "model_id": _identifier(),
        "content_block_refs": _ref_array(),
        "tool_proposal_refs": _ref_array(),
        "usage_report_ref": _nullable(_ref()),
        response_field: _ref(),
    })


def _port_configs() -> dict[str, dict[str, Any]]:
    app_points = _enum("initial_generation", "critic_inquiry", "post_alternative")
    return {
        "provider-port-v1": _object({
            "provider_id": _identifier(), "auth_mode": _identifier(const="api"),
            "api_origin": _https_uri(), "egress_policy_ref": _ref(),
            "catalog_ttl_seconds": _positive(maximum=86_400),
            "supported_modalities": _identifier_array(sorted_unique=True),
            "supported_input_media_types": _media_array(sorted_unique=True),
        }),
        "managed-provider-runner-port-v1": _object({
            "provider_id": _identifier(), "runner_profile_ref": _ref(),
            "binary_digest": _digest(), "tool_bridge_profile_ref": _ref(),
            "auth_volume_profile_ref": _ref(),
            "supported_event_types": _identifier_array(sorted_unique=True),
            "supported_input_media_types": _media_array(sorted_unique=True),
        }),
        "model-runtime-port-v1": _object({
            "runtime_profile_ref": _ref(), "model_catalog_ref": _ref(),
            "supported_modalities": _identifier_array(sorted_unique=True),
            "supported_efforts": _effort_value_array(sorted_unique=True),
            "supported_input_media_types": _media_array(sorted_unique=True),
        }),
        "tool-port-v1": _object({
            "tool_definition_refs": _ref_array(sorted_unique=True),
            "effect_policy_ref": _ref(), "artifact_policy_ref": _ref(),
            "network_policy_ref": _nullable(_ref()),
            "filesystem_policy_ref": _nullable(_ref()),
        }),
        "artifact-codec-port-v1": _object({
            "input_media_types": _media_array(sorted_unique=True),
            "output_media_types": _media_array(sorted_unique=True),
            "selector_kinds": _identifier_array(sorted_unique=True),
            "determinism": _enum("deterministic", "declared_nondeterministic"),
            "conversion_limits_ref": _ref(),
        }),
        "lens-definition-port-v1": _object({
            "definition_ref": _ref(), "composition_contract_ref": _ref(),
            "source_map_ref": _ref(),
            "allowed_application_points": _array(app_points, sorted_unique=True),
        }),
        "evaluator-definition-port-v1": _object({
            "rubric_ref": _ref(), "scoring_contract_ref": _ref(),
            "abstention_policy_ref": _ref(),
            "allowed_evidence_kinds": _identifier_array(sorted_unique=True),
        }),
        "evaluator-runtime-port-v1": _object({
            "rubric_ref": _ref(), "scoring_contract_ref": _ref(),
            "abstention_policy_ref": _ref(),
            "allowed_evidence_kinds": _identifier_array(sorted_unique=True),
            "runtime_profile_ref": _ref(), "model_choice_ref": _nullable(_ref()),
            "isolation_profile_ref": _ref(),
        }),
        "storage-port-v1": _object({
            "namespace_id": _identifier(), "schema_version": _version_text(),
            "transaction_profile_ref": _ref(), "migration_profile_ref": _ref(),
            "exclusive_owner_instance_id": _identifier(),
            "accepted_value_media_types": _media_array(sorted_unique=True),
        }),
        "credential-vault-port-v1": _object({
            "vault_id": _identifier(), "algorithm_profile_ref": _ref(),
            "trust_root_ref": _ref(),
            "supported_secret_types": _identifier_array(sorted_unique=True),
            "exclusive_owner_instance_id": _identifier(),
        }),
        "export-sink-port-v1": _object({
            "destination_kind": _identifier(), "network_policy_ref": _ref(),
            "delivery_policy_ref": _ref(),
            "supported_media_types": _media_array(sorted_unique=True),
        }),
    }


PORT_ERROR_CODES: dict[str, tuple[str, ...]] = {
    "provider-port-v1": (
        "auth_failed", "catalog_incomplete", "model_unavailable", "rate_limited",
        "billing_blocked", "provider_protocol_error",
    ),
    "managed-provider-runner-port-v1": (
        "auth_required", "device_flow_expired", "runner_version_mismatch",
        "tool_bridge_failed", "runner_protocol_error",
    ),
    "model-runtime-port-v1": (
        "model_not_loaded", "model_incompatible", "inference_failed",
        "runtime_protocol_error",
    ),
    "tool-port-v1": (
        "tool_not_found", "tool_version_mismatch", "arguments_invalid", "effect_denied",
        "execution_failed", "effect_outcome_unknown",
    ),
    "artifact-codec-port-v1": (
        "media_unsupported", "selector_unsupported", "decode_failed", "render_failed",
        "encode_failed", "content_rejected",
    ),
    "lens-definition-port-v1": (
        "definition_invalid", "composition_invalid", "source_missing",
        "application_point_unsupported",
    ),
    "evaluator-definition-port-v1": (
        "rubric_invalid", "evidence_insufficient", "evaluation_failed",
        "evaluation_invalid",
    ),
    "evaluator-runtime-port-v1": (
        "rubric_invalid", "evidence_insufficient", "evaluation_failed",
        "evaluation_invalid", "runtime_unavailable", "evaluator_protocol_error",
    ),
    "storage-port-v1": (
        "revision_conflict", "schema_mismatch", "migration_unsafe", "storage_corrupt",
        "storage_unavailable",
    ),
    "credential-vault-port-v1": (
        "secret_invalid", "key_unavailable", "record_conflict", "rotation_incomplete",
        "retirement_required", "erase_incomplete", "vault_unavailable",
    ),
    "export-sink-port-v1": (
        "destination_invalid", "consent_required", "content_unsupported",
        "transmit_failed", "delivery_unknown",
    ),
}


def _operation_shapes() -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    """Return every exact operation input/success-output pair."""
    operation_shapes: dict[
        tuple[str, str], tuple[dict[str, Any], dict[str, Any]]
    ] = {}

    def add(port: str, operation: str, input_schema: dict[str, Any],
            output_schema: dict[str, Any]) -> None:
        key = (port, operation)
        if key in operation_shapes:
            raise RuntimeError(f"duplicate operation shape: {key!r}")
        operation_shapes[key] = (input_schema, output_schema)

    # Provider and local model runtime.
    add("provider-port-v1", "capabilities", _empty_object(), _object({
        "modalities": _identifier_array(sorted_unique=True),
        "tool_calling": {"type": "boolean"},
        "usage_reporting": {"type": "boolean"},
        "cancellation": {"type": "boolean"},
    }))
    add("provider-port-v1", "catalog", _object({
        "catalog_epoch": _nullable(_ref()),
    }), _object({
        "catalog_ref": _ref(), "complete": {"type": "boolean"},
        "models": _models_output(),
    }))
    add("provider-port-v1", "model_step", _model_step_input(),
        _provider_step_output("provider_response_ref"))
    add("provider-port-v1", "status", _status_input(), _status_output())
    add("provider-port-v1", "cancel", _cancel_input(), _cancel_output())

    add("model-runtime-port-v1", "capabilities", _empty_object(), _object({
        "model_ids": _identifier_array(sorted_unique=True),
        "modalities": _identifier_array(sorted_unique=True),
        "effort_values": _effort_value_array(sorted_unique=True),
        "tool_calling": {"type": "boolean"},
    }))
    add("model-runtime-port-v1", "model_step", _model_step_input(),
        _provider_step_output("runtime_response_ref"))
    add("model-runtime-port-v1", "status", _status_input(), _status_output())
    add("model-runtime-port-v1", "cancel", _cancel_input(), _cancel_output())

    # Managed provider runner.
    add("managed-provider-runner-port-v1", "preflight", _object({
        "requested_model_id": _nullable(_identifier()),
        "requested_effort": _nullable(_effort_value()),
    }), _object({
        "observed_binary_digest": _digest(), "runner_version": _version_text(),
        "auth_state": _enum(
            "disconnected", "pending", "authenticated", "expired", "failed",
        ),
        "model_acceptance": _enum("accepted", "unsupported", "unknown"),
        "capability_evidence_ref": _ref(),
    }))
    add("managed-provider-runner-port-v1", "device_auth_start", _object({
        "login_intent_ref": _ref(),
    }), _object({
        "login_operation_ref": _ref(), "verification_url": _https_uri(),
        "user_code": _short_text(), "expires_at": _time(),
    }))
    add("managed-provider-runner-port-v1", "device_auth_status", _object({
        "login_operation_ref": _ref(),
    }), _object({
        "state": _enum("pending", "completed", "cancelled", "expired", "failed"),
    }))
    add("managed-provider-runner-port-v1", "device_auth_cancel", _object({
        "login_operation_ref": _ref(),
    }), _cancel_output())
    add("managed-provider-runner-port-v1", "run_start", _object({
        "frozen_run_projection_ref": _ref(), "model_id": _identifier(),
        "effort": _nullable(_effort_value()),
        "tool_definition_refs": _ref_array(sorted_unique=True),
    }), _object({"runner_run_ref": _ref(), "event_cursor": _ref()}))
    add("managed-provider-runner-port-v1", "run_status", _object({
        "runner_run_ref": _ref(), "event_cursor": _nullable(_ref()),
    }), _object({
        "state": _enum("pending", "running", "succeeded", "failed", "cancelled", "unknown"),
        "normalized_event_refs": _ref_array(),
        "usage_report_ref": _nullable(_ref()),
    }))
    add("managed-provider-runner-port-v1", "run_cancel", _object({
        "runner_run_ref": _ref(),
        "reason_class": _enum(
            "user_requested", "deadline", "budget", "superseded", "shutdown",
            "policy_revoked",
        ),
    }), _cancel_output())

    # Tool and artifact codecs.
    tool_description = _object({
        "tool_id": _identifier(), "version": _version_text(),
        "argument_schema_ref": _ref(), "result_schema_ref": _ref(),
        "effect_class": _enum(
            "none", "read", "write_reversible", "external_reversible",
            "external_irreversible", "instance_critical_secret",
            "instance_critical_storage",
        ),
        "artifact_roles": _identifier_array(sorted_unique=True),
    })
    add("tool-port-v1", "describe_tools", _object({
        "requested_tool_ids": _identifier_array(sorted_unique=True),
    }), _object({"tools": _array(tool_description)}))
    add("tool-port-v1", "invoke_tool", _object({
        "tool_id": _identifier(), "tool_version": _version_text(),
        "arguments_ref": _ref(), "grant_ref": _ref(),
        "expected_effect_class": _enum(
            "none", "read", "write_reversible", "external_reversible",
            "external_irreversible", "instance_critical_secret",
            "instance_critical_storage",
        ),
        "external_target_ref": _nullable(_ref()),
    }), _object({"tool_call_ref": _ref(), "result_ref": _ref()}))
    add("tool-port-v1", "status", _status_input(), _status_output())
    add("tool-port-v1", "cancel", _cancel_input(), _cancel_output())

    codec_operations = _array(
        _enum("decode_projection", "render_preview", "encode"),
        sorted_unique=True,
    )
    add("artifact-codec-port-v1", "probe", _empty_object(), _object({
        "media_type": _media_type(), "supported_operations": codec_operations,
        "limit_evidence_ref": _ref(),
    }))
    add("artifact-codec-port-v1", "decode_projection", _object({
        "target_projection_schema_ref": _ref(),
    }), _object({
        "projection_artifact_ref": _ref(), "omissions_ref": _ref(),
    }))
    add("artifact-codec-port-v1", "render_preview", _object({
        "target_media_type": _media_type(), "render_options_ref": _nullable(_ref()),
    }), _object({"preview_artifact_ref": _ref(), "omissions_ref": _ref()}))
    add("artifact-codec-port-v1", "encode", _object({
        "target_media_type": _media_type(), "encode_options_ref": _nullable(_ref()),
    }), _object({"encoded_artifact_ref": _ref(), "omissions_ref": _ref()}))
    add("artifact-codec-port-v1", "cancel", _cancel_input(), _cancel_output())

    # Lens and evaluator definitions/runtimes.
    app_point = _enum("initial_generation", "critic_inquiry", "post_alternative")
    add("lens-definition-port-v1", "validate_definition", _object({
        "definition_ref": _ref(), "source_map_ref": _ref(),
    }), _object({"valid": {"type": "boolean"}, "issue_refs": _ref_array()}))
    add("lens-definition-port-v1", "compose", _object({
        "atomic_lens_refs": _ref_array(), "composition_policy_ref": _ref(),
    }), _object({
        "composition_ref": _ref(), "conflict_refs": _ref_array(),
        "abstention_ref": _nullable(_ref()),
    }))
    add("lens-definition-port-v1", "apply_decision", _object({
        "work_model_ref": _ref(), "application_point": app_point,
        "composition_ref": _ref(), "evidence_refs": _ref_array(),
    }), _object({
        "question_refs": _ref_array(), "decision_contribution_refs": _ref_array(),
        "abstention_ref": _nullable(_ref()),
    }))

    rubric_input = _object({"rubric_ref": _ref()})
    rubric_output = _object({
        "criteria_refs": _ref_array(), "scoring_contract_ref": _ref(),
        "abstention_policy_ref": _ref(),
    })
    evaluate_input = _object({
        "candidate_ref": _ref(), "evidence_refs": _ref_array(),
        "evaluation_profile_ref": _ref(),
    })
    evaluate_output = _object({
        "evaluation_result_ref": _ref(), "score_ref": _nullable(_ref()),
        "decision": _enum("pass", "fail", "abstain", "invalid"),
        "unavailable_item_refs": _ref_array(),
    })
    abstain_input = _object({
        "candidate_ref": _ref(), "reason_code": _identifier(),
        "unavailable_item_refs": _ref_array(),
    })
    abstain_output = _object({
        "evaluation_result_ref": _ref(), "decision": _identifier(const="abstain"),
    })
    for port in ("evaluator-definition-port-v1", "evaluator-runtime-port-v1"):
        add(port, "describe_rubric", deepcopy(rubric_input), deepcopy(rubric_output))
        add(port, "evaluate", deepcopy(evaluate_input), deepcopy(evaluate_output))
        add(port, "abstain", deepcopy(abstain_input), deepcopy(abstain_output))
    add("evaluator-runtime-port-v1", "status", _status_input(), _status_output())
    add("evaluator-runtime-port-v1", "cancel", _cancel_input(), _cancel_output())

    # Storage and credential vault.
    add("storage-port-v1", "capabilities", _empty_object(), _object({
        "transaction_modes": _array(
            _enum("read_only", "write_cas", "migration"), sorted_unique=True,
        ),
        "max_object_bytes": _positive(maximum=67_108_864),
        "cas": {"type": "boolean"},
    }))
    add("storage-port-v1", "health", _empty_object(), _object({
        "state": _enum("healthy", "degraded", "unavailable"),
        "evidence_ref": _ref(),
    }))
    add("storage-port-v1", "migrate_plan", _object({
        "from_schema": _version_text(), "to_schema": _version_text(),
        "snapshot_ref": _ref(),
    }), _object({"migration_plan_ref": _ref(), "reversible": {"type": "boolean"}}))
    add("storage-port-v1", "read", _object({
        "object_ref": _ref(), "expected_revision": _nullable(_positive()),
        "purpose_ref": _ref(),
    }), _object({"object_artifact_ref": _ref(), "revision": _positive()}))
    add("storage-port-v1", "write_cas", _object({
        "object_ref": _ref(), "expected_revision": _nullable(_positive()),
        "next_revision": _positive(), "transaction_key": _digest(),
    }), _object({
        "transaction_ref": _ref(), "revision": _positive(), "commit_ref": _ref(),
    }))

    add("credential-vault-port-v1", "capabilities", _empty_object(), _object({
        "secret_types": _identifier_array(sorted_unique=True),
        "rotation": {"type": "boolean"}, "secure_erasure_profile_ref": _ref(),
    }))
    add("credential-vault-port-v1", "health", _empty_object(), _object({
        "state": _enum("healthy", "degraded", "unavailable"),
        "evidence_ref": _ref(),
    }))
    add("credential-vault-port-v1", "store", _object({
        "intent_ref": _ref(), "record_id": _identifier(),
        "expected_version": _nullable(_positive()), "next_version": _positive(),
        "secret_type": _identifier(), "secret_ingress_ref": _ref(),
    }), _object({
        "record_ref": _ref(), "opaque_handle_ref": _ref(), "version": _positive(),
    }))
    add("credential-vault-port-v1", "resolve_for_gateway", _object({
        "opaque_handle_ref": _ref(), "provider_request_intent_ref": _ref(),
    }), _object({"gateway_delivery_ref": _ref()}))
    add("credential-vault-port-v1", "retire", _object({
        "record_ref": _ref(), "expected_version": _positive(),
    }), _object({"retirement_receipt_ref": _ref()}))
    add("credential-vault-port-v1", "erase", _object({
        "record_ref": _ref(), "retirement_receipt_ref": _ref(),
    }), _object({"erasure_receipt_ref": _ref(), "complete": {"type": "boolean"}}))

    # Export sink.
    add("export-sink-port-v1", "capabilities", _empty_object(), _object({
        "destination_kind": _identifier(),
        "media_types": _media_array(sorted_unique=True),
        "cancellation": {"type": "boolean"}, "status_query": {"type": "boolean"},
    }))
    add("export-sink-port-v1", "prepare", _object({
        "snapshot_ref": _ref(), "target_ref": _ref(), "consent_challenge_ref": _ref(),
    }), _object({"prepared_delivery_ref": _ref(), "content_manifest_ref": _ref()}))
    add("export-sink-port-v1", "transmit", _object({
        "prepared_delivery_ref": _ref(), "target_ref": _ref(),
        "consent_decision_ref": _ref(),
    }), _object({"delivery_ref": _ref(), "delivery_receipt_ref": _nullable(_ref())}))
    add("export-sink-port-v1", "status", _status_input(), _status_output())
    add("export-sink-port-v1", "cancel", _cancel_input(), _cancel_output())

    expected = set(OPERATION_CONTRACTS)
    if set(operation_shapes) != expected:
        missing = sorted(expected - set(operation_shapes))
        extra = sorted(set(operation_shapes) - expected)
        raise RuntimeError(f"operation schema partition mismatch; missing={missing}, extra={extra}")
    return operation_shapes


CORE_ERROR_CODES = (
    "invalid_request", "unsupported_operation", "unsupported_capability",
    "permission_denied", "deadline_exceeded", "cancelled", "resource_exhausted",
    "dependency_unavailable", "integrity_failed", "external_effect_unknown",
    "port_specific_failure", "internal_failure",
)
MESSAGE_CLASSES = (
    "validation", "unsupported", "permission", "timeout", "cancelled", "capacity",
    "dependency", "integrity", "external_outcome", "port_failure", "internal",
)
RETRY_CLASSES = (
    "never", "after_backoff", "after_requalification", "human_action_required",
)


def _schema_header(port: str, shape: str) -> dict[str, Any]:
    return {
        "$schema": DRAFT_2020_12,
        "$id": PORT_SCHEMA_IDS[(port, shape)],
        "title": f"DeepTwin {port} {shape} v1",
        "$comment": (
            "Core-owned semantic schema. Validation grants no installation, binding, "
            "artifact, credential, network, deployment, or human authority."
        ),
        "type": "object",
        "additionalProperties": False,
    }


def _operation_defs() -> dict[str, Any]:
    return {
        "status-operation-input-v1": _status_input(),
        "status-operation-output-v1": _status_output(),
        "cancel-operation-input-v1": _cancel_input(),
        "cancel-operation-output-v1": _cancel_output(),
    }


def _config_schema(port: str, port_config: Mapping[str, Any]) -> dict[str, Any]:
    slot = _binding_slot_key()
    slot["properties"]["port_contract_version"] = _identifier(const=port)
    properties = {
        "schema_id": _string(
            maximum=2048, const=PORT_SCHEMA_IDS[(port, "config")], fmt="uri",
        ),
        "schema_version": {"type": "integer", "const": 1},
        "port_contract_version": _identifier(const=port),
        "extension_id": _identifier(),
        "installation_digest": _digest(),
        "qualification_ref": _ref(),
        "binding_revision_ref": _ref(),
        "binding_slot_key": slot,
        "binding_slot_key_digest": _digest(),
        "extension_config": _extension_object(),
        "grant_refs": _ref_array(sorted_unique=True),
        "credential_handle_refs": _ref_array(sorted_unique=True),
        "resource_limits": _resource_limits(),
        "port_config": deepcopy(dict(port_config)),
    }
    result = _schema_header(port, "config")
    result.update({"properties": properties, "required": list(properties)})
    return result


def _request_artifacts_schema(profile_name: str) -> dict[str, Any]:
    profile = REQUEST_ARTIFACT_PROFILES[profile_name]
    item = _artifact_input_binding()
    if profile.role is not None:
        item["properties"]["role"] = _identifier(const=profile.role)
    if profile.selector_policy == "forbidden":
        item["properties"]["selector_ref"] = {"type": "null"}
    result = _array(item, minimum=profile.min_items, maximum=profile.max_items)
    result["x-deeptwin-artifact-profile"] = profile.name
    result["x-deeptwin-exact-order"] = profile.exact_order
    result["x-deeptwin-list-source"] = profile.list_source
    result["x-deeptwin-bounded-stream-required"] = profile.requires_bounded_stream
    result["x-deeptwin-ref-only-allowed"] = profile.ref_only_allowed
    result["x-deeptwin-shared-store-allowed"] = profile.shared_store_allowed
    result["uniqueItems"] = True
    result["x-deeptwin-unique-binding-tuple"] = True
    if profile_name != "E":
        result["x-deeptwin-unique-by"] = "artifact_ref"
    return result


def _request_schema(port: str, operation_shapes: Mapping[
        tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    operations = PORT_CONTRACTS[port].operations
    properties = {
        "schema_id": _string(
            maximum=2048, const=PORT_SCHEMA_IDS[(port, "request")], fmt="uri",
        ),
        "schema_version": {"type": "integer", "const": 1},
        "port_contract_version": _identifier(const=port),
        "request_id": _uuid(),
        "operation": _enum(*operations),
        "installation_digest": _digest(),
        "qualification_ref": _ref(),
        "binding_revision_ref": _ref(),
        "purpose_ref": _ref(),
        "actor_ref": _ref(),
        "grant_refs": _ref_array(sorted_unique=True),
        "idempotency_key": _digest(),
        "deadline_at": _time(),
        "cancellation_ref": _nullable(_ref()),
        "artifact_inputs": _array(_artifact_input_binding()),
        "input": {"type": "object"},
        "extension_input": _extension_object(),
    }
    branches = []
    for operation in operations:
        contract = OPERATION_CONTRACTS[(port, operation)]
        input_schema, _ = operation_shapes[(port, operation)]
        branches.append({
            "title": f"{port}:{operation}",
            "properties": {
                "operation": {"const": operation},
                "artifact_inputs": _request_artifacts_schema(
                    contract.request_artifact_profile,
                ),
                "input": deepcopy(input_schema),
            },
            "required": ["operation", "artifact_inputs", "input"],
        })
    result = _schema_header(port, "request")
    result.update({
        "$defs": _operation_defs(),
        "properties": properties,
        "required": list(properties),
        "oneOf": branches,
    })
    return result


def _error_properties(port: str, operation_schema: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_id": _string(
            maximum=2048, const=PORT_SCHEMA_IDS[(port, "error")], fmt="uri",
        ),
        "schema_version": {"type": "integer", "const": 1},
        "port_contract_version": _identifier(const=port),
        "request_id": _uuid(),
        "operation": deepcopy(dict(operation_schema)),
        "code": _enum(*CORE_ERROR_CODES),
        "port_error_code": _nullable(_enum(*PORT_ERROR_CODES[port])),
        "extension_error_code": _nullable(_identifier()),
        "message_class": _enum(*MESSAGE_CLASSES),
        "retry_class": _enum(*RETRY_CLASSES),
        "affected_refs": _ref_array(sorted_unique=True),
        "evidence_ref": _nullable(_ref()),
    }


def _error_relations(*, terminal: str | None = None) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = [
        {
            "if": {"properties": {"code": {"const": "port_specific_failure"}},
                   "required": ["code"]},
            "then": {"properties": {"port_error_code": {"type": "string"}}},
            "else": {"properties": {
                "port_error_code": {"type": "null"},
                "extension_error_code": {"type": "null"},
            }},
        },
        {
            "if": {"properties": {"retry_class": {"const": "after_backoff"}},
                   "required": ["retry_class"]},
            "then": {"properties": {"code": {
                "not": {"enum": ["cancelled", "external_effect_unknown"]},
            }}},
        },
    ]
    if terminal == "failed":
        relations.append({
            "properties": {
                "code": {"enum": [
                    code for code in CORE_ERROR_CODES
                    if code not in {"cancelled", "external_effect_unknown"}
                ]},
            },
        })
    elif terminal == "cancelled":
        relations.append({
            "properties": {
                "code": {"const": "cancelled"},
                "retry_class": {"const": "never"},
            },
        })
    elif terminal == "unknown":
        relations.append({
            "properties": {
                "code": {"const": "external_effect_unknown"},
                "retry_class": {"const": "never"},
            },
        })
    else:
        relations.extend((
            {
                "if": {"properties": {"code": {"const": "cancelled"}},
                       "required": ["code"]},
                "then": {"properties": {"retry_class": {"const": "never"}}},
            },
            {
                "if": {"properties": {
                    "code": {"const": "external_effect_unknown"},
                }, "required": ["code"]},
                "then": {"properties": {"retry_class": {"const": "never"}}},
            },
        ))
    return relations


def _embedded_error(port: str, operation: str, terminal: str) -> dict[str, Any]:
    properties = _error_properties(port, {"const": operation})
    schema = _object(properties)
    schema["allOf"] = _error_relations(terminal=terminal)
    return schema


def _error_schema(port: str) -> dict[str, Any]:
    operations = PORT_CONTRACTS[port].operations
    properties = _error_properties(port, _enum(*operations))
    result = _schema_header(port, "error")
    result.update({
        "properties": properties,
        "required": list(properties),
        "allOf": _error_relations(),
        "oneOf": [
            {"properties": {"operation": {"const": operation}},
             "required": ["operation"]}
            for operation in operations
        ],
    })
    return result


def _effect_schema(port: str, operation: str, terminal: str) -> dict[str, Any]:
    allowed_classes = OPERATION_CONTRACTS[(port, operation)].allowed_effect_classes
    branches: list[dict[str, Any]] = []
    for effect_class in sorted(allowed_classes):
        family = EFFECT_FAMILIES[effect_class]
        for state, receipt_presence, remote in sorted(
                ALLOWED_EFFECT_TUPLES[(terminal, family)]):
            branches.append(_object({
                "effect_class": _identifier(const=effect_class),
                "effect_state": _enum(state),
                "effect_receipt_ref": (
                    {"type": "null"} if receipt_presence == "null" else _ref()
                ),
                "remote_outcome": _enum(remote),
            }))
    if not branches:
        return {"not": {}}
    return {"oneOf": branches}


def _result_artifacts_schema(port: str, operation: str, terminal: str) -> dict[str, Any]:
    if terminal != "succeeded":
        result = _empty_array()
        result["x-deeptwin-result-artifact-mode"] = "E"
        return result
    contract = OPERATION_CONTRACTS[(port, operation)]
    mode = contract.result_artifact_mode
    metadata = RESULT_ARTIFACT_METADATA[contract.result_artifact_metadata]
    if mode == "E":
        result = _empty_array()
    else:
        omissions = "forbidden" if metadata.omissions_source == "null" else "optional"
        item = _artifact_result_binding(role=metadata.role, omissions=omissions)
        if mode == "O":
            result = _array(item, minimum=1, maximum=1)
        else:
            result = _array(item, maximum=256)
        result["uniqueItems"] = True
        result["x-deeptwin-unique-by"] = "artifact_ref"
        result["x-deeptwin-binding-source"] = metadata.binding_source
        result["x-deeptwin-media-source"] = metadata.media_source
        result["x-deeptwin-omissions-source"] = metadata.omissions_source
    result["x-deeptwin-result-artifact-mode"] = mode
    return result


def _result_schema(port: str, operation_shapes: Mapping[
        tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    operations = PORT_CONTRACTS[port].operations
    properties = {
        "schema_id": _string(
            maximum=2048, const=PORT_SCHEMA_IDS[(port, "result")], fmt="uri",
        ),
        "schema_version": {"type": "integer", "const": 1},
        "port_contract_version": _identifier(const=port),
        "request_id": _uuid(),
        "operation": _enum(*operations),
        "terminal": _enum("succeeded", "failed", "cancelled", "unknown"),
        "started_at": _time(),
        "completed_at": _nullable(_time()),
        "output": {"type": "object"},
        "extension_output": _extension_object(),
        "artifacts": _array(_artifact_result_binding()),
        "usage": _usage(),
        "effect": {"type": "object"},
        "error": {"oneOf": [{"type": "object"}, {"type": "null"}]},
    }
    branches = []
    for operation in operations:
        contract = OPERATION_CONTRACTS[(port, operation)]
        _, success_output = operation_shapes[(port, operation)]
        for terminal in TERMINALS_BY_CLASS[contract.terminal_class]:
            success = terminal == "succeeded"
            branch_properties: dict[str, Any] = {
                "operation": {"const": operation},
                "terminal": {"const": terminal},
                "completed_at": _time() if terminal != "unknown" else {"type": "null"},
                "output": deepcopy(success_output) if success else _empty_object(),
                "extension_output": _extension_object() if success else _empty_object(),
                "artifacts": _result_artifacts_schema(port, operation, terminal),
                "effect": _effect_schema(port, operation, terminal),
                "error": {"type": "null"} if success else _embedded_error(
                    port, operation, terminal,
                ),
            }
            branches.append({
                "title": f"{port}:{operation}:{terminal}",
                "properties": branch_properties,
                "required": list(branch_properties),
            })
    expected = {
        candidate for candidate in ALLOWED_TERMINAL_CANDIDATES if candidate[0] == port
    }
    actual = {
        (port, branch["properties"]["operation"]["const"],
         branch["properties"]["terminal"]["const"])
        for branch in branches
    }
    if actual != expected or len(branches) != len(expected):
        raise RuntimeError(f"result terminal partition mismatch for {port}")
    result = _schema_header(port, "result")
    result.update({
        "$defs": _operation_defs(),
        "properties": properties,
        "required": list(properties),
        "oneOf": branches,
    })
    return result


@lru_cache(maxsize=1)
def _generated_templates() -> dict[tuple[str, str], dict[str, Any]]:
    port_configs = _port_configs()
    operation_shapes = _operation_shapes()
    if set(port_configs) != set(PORT_CONTRACTS):
        raise RuntimeError("port config schema partition does not match the catalog")
    generated: dict[tuple[str, str], dict[str, Any]] = {}
    for port in PORT_CONTRACTS:
        generated[(port, "config")] = _config_schema(port, port_configs[port])
        generated[(port, "request")] = _request_schema(port, operation_shapes)
        generated[(port, "result")] = _result_schema(port, operation_shapes)
        generated[(port, "error")] = _error_schema(port)
    if set(generated) != set(PORT_SCHEMA_IDS) or len(generated) != 44:
        raise RuntimeError("generated schema catalog must be the exact 44 schema IDs")
    observed_ids = {value["$id"] for value in generated.values()}
    if observed_ids != set(PORT_SCHEMA_IDS.values()):
        raise RuntimeError("generated schema identifiers diverge from PORT_SCHEMA_IDS")
    for schema in generated.values():
        Draft202012Validator.check_schema(schema)
    return generated


def generate_port_schemas() -> dict[tuple[str, str], dict[str, Any]]:
    """Generate a fresh deterministic mapping of all 44 core-owned schemas."""
    return deepcopy(_generated_templates())


def canonical_schema_bytes(schema: Mapping[str, Any]) -> bytes:
    """Return stable UTF-8 JSON bytes used for checked-in schema artifacts."""
    return (json.dumps(
        schema, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ) + "\n").encode("utf-8")


def validate_contract_source_structure(source: str) -> tuple[str, ...]:
    """Pure guard for the eleven normative Markdown port rows.

    A caller supplies already-read text, keeping source-file I/O out of generation.  Every pipe
    group must be a real table and every normative port row must live in a ``Port`` table.
    """
    if type(source) is not str:
        raise PortSchemaValidationError("contract source must be text")
    lines = source.splitlines()
    pipe_groups: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate([*lines, ""]):
        if line.lstrip().startswith("|"):
            start = index if start is None else start
        elif start is not None:
            pipe_groups.append((start, index))
            start = None
    separator = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")
    for group_start, group_end in pipe_groups:
        group = lines[group_start:group_end]
        if len(group) < 3 or separator.fullmatch(group[1]) is None:
            raise PortSchemaValidationError(
                f"isolated or malformed Markdown pipe row at line {group_start + 1}",
            )
    normative_header = (
        "| Port | Exact closed `port_config` | Exact operation: `input` → successful `output` "
        "| Closed port-error enum |"
    )
    normative_separator = "| --- | --- | --- | --- |"
    section_ports = {
        "3.1": {
            "provider-port-v1", "managed-provider-runner-port-v1", "model-runtime-port-v1",
        },
        "3.2": {"tool-port-v1", "artifact-codec-port-v1"},
        "3.3": {
            "lens-definition-port-v1", "evaluator-definition-port-v1",
            "evaluator-runtime-port-v1",
        },
        "3.4": {"storage-port-v1", "credential-vault-port-v1"},
        "3.5": {"export-sink-port-v1"},
    }
    section_at_line: dict[int, str] = {}
    current_section: str | None = None
    for index, line in enumerate(lines):
        section_match = re.match(r"^### (3\.[1-5])(?:\s|$)", line)
        if section_match is not None:
            current_section = section_match.group(1)
        elif line.startswith("### "):
            current_section = None
        if current_section is not None:
            section_at_line[index] = current_section

    normative_groups: dict[tuple[int, int], str] = {}
    for group_start, group_end in pipe_groups:
        group = lines[group_start:group_end]
        if group[0] != normative_header:
            continue
        if group[1] != normative_separator:
            raise PortSchemaValidationError("normative Port table separator is not exact")
        section = section_at_line.get(group_start)
        if section not in section_ports:
            raise PortSchemaValidationError("normative Port table is outside an exact section")
        if section in normative_groups.values():
            raise PortSchemaValidationError(f"duplicate normative Port table in section {section}")
        normative_groups[(group_start, group_end)] = section
    if set(normative_groups.values()) != set(section_ports):
        raise PortSchemaValidationError("every normative port section requires one exact Port table")

    found: list[str] = []
    found_by_section: dict[str, set[str]] = {section: set() for section in section_ports}
    row_pattern = re.compile(r"^\s*\|\s*`([^`]+-port-v1)`\s*\|")
    for index, line in enumerate(lines):
        match = row_pattern.match(line)
        if match is None:
            continue
        port = match.group(1)
        containing = next(
            ((left, right) for left, right in pipe_groups if left <= index < right),
            None,
        )
        if containing is None:
            raise PortSchemaValidationError(f"isolated normative port row: {port}")
        section = normative_groups.get(containing)
        if section is None:
            raise PortSchemaValidationError(
                f"normative port row is outside an exact normative Port table: {port}",
            )
        cells = re.split(r"(?<!\\)\|", line.strip())[1:-1]
        if len(cells) != 4:
            raise PortSchemaValidationError(f"normative port row is not four cells: {port}")
        found.append(port)
        found_by_section[section].add(port)
    expected = tuple(PORT_CONTRACTS)
    if len(found) != 11 or set(found) != set(expected) or len(set(found)) != 11:
        raise PortSchemaValidationError(
            f"contract must contain each of the eleven normative port rows once; found={found!r}",
        )
    for section, ports in section_ports.items():
        if found_by_section[section] != ports:
            raise PortSchemaValidationError(
                f"normative port rows are in the wrong section {section}: "
                f"found={sorted(found_by_section[section])!r}",
            )
    return tuple(found)


def write_port_schemas(destination: str | Path, *, contract_source: str | None = None) \
        -> dict[tuple[str, str], Path]:
    """Write all schema artifacts beneath an explicit destination.

    This is intentionally the module's only filesystem operation.  When supplied, the already-read
    contract source is structurally guarded before any directory or file is created.
    """
    if contract_source is not None:
        validate_contract_source_structure(contract_source)
    generated = generate_port_schemas()
    root = Path(destination)
    written: dict[tuple[str, str], Path] = {}
    for key in sorted(generated):
        port, shape = key
        path = root / port / f"{shape}.schema.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_schema_bytes(generated[key]))
        written[key] = path
    return written


def _canonical_key(value: Any) -> bytes:
    try:
        return canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise PortSchemaValidationError("value is not canonical JSON") from exc


def _check_global_bounds(value: Any, *, depth: int = 1, field: str | None = None) -> None:
    if depth > MAX_NESTING:
        raise PortSchemaValidationError("semantic envelope nesting exceeds 8")
    if isinstance(value, str):
        limit = 2_048 if field in {"api_origin", "verification_url", "schema_id"} else MAX_STRING
        if len(value) > limit:
            raise PortSchemaValidationError(f"string exceeds bound at {field or '<root>'}")
        if field in {
            "display_name", "user_code", "runner_version", "version", "tool_version",
            "schema_version", "from_schema", "to_schema",
        } and unicodedata.normalize("NFC", value) != value:
            raise PortSchemaValidationError(f"non-NFC text at {field}")
        if field in {"api_origin", "verification_url"}:
            _validate_https_uri(value)
        if field in {"deadline_at", "started_at", "completed_at", "observed_at", "expires_at"}:
            _validate_time(value)
        return
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise PortSchemaValidationError("JSON integer exceeds the exact safe bound")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PortSchemaValidationError("non-finite JSON number")
        raise PortSchemaValidationError("JSON floating-point numbers are outside the port vocabulary")
    if isinstance(value, list):
        if len(value) > 256:
            raise PortSchemaValidationError("array exceeds 256 items")
        for item in value:
            _check_global_bounds(item, depth=depth + 1, field=field)
        return
    if isinstance(value, dict):
        if len(value) > 64:
            raise PortSchemaValidationError("object exceeds 64 members")
        for key, item in value.items():
            if type(key) is not str:
                raise PortSchemaValidationError("object key is not text")
            _check_global_bounds(key, depth=depth + 1, field="object-key")
            _check_global_bounds(item, depth=depth + 1, field=key)
        return
    raise PortSchemaValidationError(f"unsupported JSON value type: {type(value).__name__}")


def _validate_https_uri(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PortSchemaValidationError("invalid HTTPS URI") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment or not parsed.hostname.isascii()
            or parsed.hostname != parsed.hostname.lower() or parsed.hostname.endswith(".")
            or port == 443 or "%" in parsed.netloc):
        raise PortSchemaValidationError("HTTPS URI is not canonical")
    if "\\" in parsed.path or "//" in parsed.path:
        raise PortSchemaValidationError("HTTPS URI path is not canonical")
    if any(segment in {".", ".."} for segment in parsed.path.split("/")):
        raise PortSchemaValidationError("HTTPS URI path is not canonical")
    unreserved = frozenset(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~",
    )
    for component in (parsed.path, parsed.query):
        index = 0
        while index < len(component):
            if component[index] != "%":
                index += 1
                continue
            escape = component[index + 1:index + 3]
            if (len(escape) != 2 or re.fullmatch(r"[0-9A-F]{2}", escape) is None
                    or chr(int(escape, 16)) in unreserved):
                raise PortSchemaValidationError("HTTPS URI percent escapes are not canonical")
            index += 3


def _validate_time(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise PortSchemaValidationError("invalid UTC calendar instant") from exc


def _walk_schema_annotations(value: Any, schema: Mapping[str, Any]) -> None:
    if schema.get("x-deeptwin-sorted") == "canonical-json-byte-order":
        encoded = [_canonical_key(item) for item in value]
        if encoded != sorted(encoded) or len(set(encoded)) != len(encoded):
            raise PortSchemaValidationError("array is not canonical sorted-unique")
    if schema.get("x-deeptwin-unique-by") == "artifact_ref":
        keys = [_canonical_key(item["artifact_ref"]) for item in value]
        if len(keys) != len(set(keys)):
            raise PortSchemaValidationError("duplicate artifact_ref")
    if schema.get("x-deeptwin-unique-binding-tuple") is True:
        keys = [
            _canonical_key({
                "artifact_ref": item["artifact_ref"],
                "selector_ref": item["selector_ref"],
                "role": item["role"],
            })
            for item in value
        ]
        if len(keys) != len(set(keys)):
            raise PortSchemaValidationError("duplicate artifact input binding tuple")
    if isinstance(value, dict):
        for name, subschema in schema.get("properties", {}).items():
            if name in value:
                _walk_schema_annotations(value[name], subschema)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for item in value:
            _walk_schema_annotations(item, schema["items"])
    for keyword in ("allOf", "oneOf"):
        for subschema in schema.get(keyword, []):
            if not list(Draft202012Validator(subschema).iter_errors(value)):
                _walk_schema_annotations(value, subschema)


def _resolve_local_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise PortSchemaValidationError("only local refinement refs are allowed")
    current: Any = root
    for encoded_part in ref[2:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if type(current) is not dict or part not in current:
            raise PortSchemaValidationError("local refinement ref does not resolve")
        current = current[part]
    if type(current) is not dict:
        raise PortSchemaValidationError("local refinement ref must resolve to a schema object")
    return current


def _check_refinement_document_bounds(schema: Mapping[str, Any]) -> None:
    stack: list[tuple[Any, int]] = [(schema, 1)]
    visited = 0
    while stack:
        value, depth = stack.pop()
        visited += 1
        if visited > 10_000 or depth > 64:
            raise PortSchemaValidationError("refinement schema document is too complex")
        if isinstance(value, float) or (type(value) is int and abs(value) > MAX_SAFE_INTEGER):
            raise PortSchemaValidationError("refinement numeric bounds are not canonical integers")
        if isinstance(value, str) and len(value) > MAX_STRING:
            raise PortSchemaValidationError("refinement schema string exceeds 4096")
        if isinstance(value, list):
            if len(value) > 256:
                raise PortSchemaValidationError("refinement schema array exceeds 256 items")
            stack.extend((item, depth + 1) for item in value)
        elif isinstance(value, dict):
            if len(value) > 256:
                raise PortSchemaValidationError("refinement schema object is too large")
            stack.extend((item, depth + 1) for item in value.values())


def validate_refinement_schema(schema: Mapping[str, Any]) -> None:
    """Reject refinement schemas that are open, executable, remote, or unbounded."""
    if type(schema) is not dict:
        raise PortSchemaValidationError("refinement schema must be an object")
    _check_refinement_document_bounds(schema)
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise PortSchemaValidationError("refinement root must be a closed object")

    forbidden = {
        "$anchor", "$dynamicAnchor", "$dynamicRef", "$id", "$recursiveAnchor",
        "$recursiveRef", "$vocabulary", "contentEncoding", "contentMediaType", "default",
        "dependentRequired", "dependentSchemas", "maxContains", "minContains",
        "patternProperties", "prefixItems", "propertyNames", "unevaluatedItems",
        "unevaluatedProperties",
    }
    schema_keywords = {
        "$comment", "$defs", "$ref", "$schema", "additionalProperties", "allOf", "anyOf",
        "const", "description", "else", "enum", "exclusiveMaximum", "exclusiveMinimum",
        "format", "if", "items", "maxItems", "maxLength", "maxProperties", "maximum",
        "minItems", "minLength", "minProperties", "minimum", "multipleOf", "not", "oneOf",
        "pattern", "properties", "required", "then", "title", "type", "uniqueItems",
    }
    active_refs: set[str] = set()
    validated_refs: set[str] = set()

    def walk(node: Any, *, root_node: bool = False) -> None:
        if type(node) is not dict:
            raise PortSchemaValidationError("every refinement schema node must be an object")
        unknown = set(node) - schema_keywords
        if unknown or set(node) & forbidden:
            raise PortSchemaValidationError("refinement uses a forbidden or unknown keyword")
        if root_node and node.get("$schema", DRAFT_2020_12) != DRAFT_2020_12:
            raise PortSchemaValidationError("refinement must use Draft 2020-12")
        ref = node.get("$ref")
        if ref is not None:
            if type(ref) is not str or set(node) - {"$ref", "$comment", "title", "description"}:
                raise PortSchemaValidationError("local refinement refs cannot have semantic siblings")
            if ref in active_refs:
                raise PortSchemaValidationError("cyclic local refinement ref")
            if ref not in validated_refs:
                active_refs.add(ref)
                walk(_resolve_local_ref(schema, ref))
                active_refs.remove(ref)
                validated_refs.add(ref)
            return

        node_type = node.get("type")
        if isinstance(node_type, list) or node_type == "number":
            raise PortSchemaValidationError("refinement uses a non-exact or floating-point type")
        combinators = [key for key in ("allOf", "anyOf", "oneOf") if key in node]
        if node_type is None and not combinators and not any(key in node for key in ("const", "enum", "not", "if")):
            raise PortSchemaValidationError("refinement schema node requires an exact type")

        object_keywords = {"properties", "required", "additionalProperties", "minProperties", "maxProperties"}
        if set(node) & object_keywords or node_type == "object":
            if node_type != "object" or node.get("additionalProperties") is not False:
                raise PortSchemaValidationError("every refinement object must be explicitly closed")
            properties = node.get("properties", {})
            if type(properties) is not dict or len(properties) > 64:
                raise PortSchemaValidationError("refinement object exceeds 64 fields")
            if any(re.fullmatch(IDENTIFIER_PATTERN, name) is None for name in properties):
                raise PortSchemaValidationError("refinement property name is not an identifier")
            maximum = node.get("maxProperties", len(properties))
            minimum = node.get("minProperties", 0)
            if (type(maximum) is not int or type(minimum) is not int
                    or not 0 <= minimum <= maximum <= min(64, len(properties))):
                raise PortSchemaValidationError("refinement object property bounds are invalid")
            required = node.get("required", [])
            if (type(required) is not list or any(type(name) is not str for name in required)
                    or len(required) != len(set(required)) or not set(required) <= set(properties)):
                raise PortSchemaValidationError("refinement required fields are invalid")
            for child in properties.values():
                walk(child)

        array_keywords = {"items", "minItems", "maxItems", "uniqueItems"}
        if set(node) & array_keywords or node_type == "array":
            if node_type != "array" or type(node.get("items")) is not dict:
                raise PortSchemaValidationError("refinement arrays require one exact item schema")
            maximum = node.get("maxItems")
            minimum = node.get("minItems", 0)
            if (type(maximum) is not int or type(minimum) is not int
                    or not 0 <= minimum <= maximum <= 256):
                raise PortSchemaValidationError("refinement arrays require maxItems<=256")
            walk(node["items"])

        if node_type == "string":
            maximum = node.get("maxLength")
            minimum = node.get("minLength", 0)
            if (type(maximum) is not int or type(minimum) is not int
                    or not 0 <= minimum <= maximum <= MAX_STRING):
                raise PortSchemaValidationError("refinement strings require maxLength<=4096")
        if node_type == "integer":
            minimum = node.get("minimum")
            maximum = node.get("maximum")
            if (type(minimum) is not int or type(maximum) is not int
                    or not -MAX_SAFE_INTEGER <= minimum <= maximum <= MAX_SAFE_INTEGER):
                raise PortSchemaValidationError("refinement integers require exact safe bounds")
        for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"):
            if keyword in node and (type(node[keyword]) is not int
                                    or abs(node[keyword]) > MAX_SAFE_INTEGER):
                raise PortSchemaValidationError("refinement numeric keyword is not a safe integer")
        for keyword in combinators:
            branches = node[keyword]
            if type(branches) is not list or not branches or len(branches) > 64:
                raise PortSchemaValidationError("refinement combinator is empty or over-bound")
            for child in branches:
                walk(child)
        for keyword in ("not", "if", "then", "else"):
            if keyword in node:
                walk(node[keyword])
        definitions = node.get("$defs", {})
        if type(definitions) is not dict or len(definitions) > 64:
            raise PortSchemaValidationError("refinement definitions are invalid")
        for child in definitions.values():
            walk(child)

    walk(schema, root_node=True)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # jsonschema raises several version-specific schema errors
        raise PortSchemaValidationError("invalid Draft 2020-12 refinement") from exc


def _format_errors(errors: list[Any]) -> str:
    ordered = sorted(
        errors,
        key=lambda error: (tuple(map(str, error.absolute_path)), error.message),
    )
    first = ordered[0]
    location = "/".join(str(part) for part in first.absolute_path) or "<root>"
    return f"base schema rejected {location}: {first.message}"


def validate_port_payload(port: str, shape: str, value: Any, *,
                          context: Mapping[str, Any] | None = None,
                          refinement_schema: Mapping[str, Any] | None = None) -> None:
    """Validate one semantic payload against the core base and optional narrower refinement."""
    if (port, shape) not in PORT_SCHEMA_IDS or shape not in PORT_SCHEMA_SHAPES:
        raise PortSchemaValidationError("unknown port/schema shape")
    _check_global_bounds(value)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PortSchemaValidationError("payload is not strict JSON") from exc
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise PortSchemaValidationError("semantic envelope exceeds 1,048,576 bytes")
    schema = generate_port_schemas()[(port, shape)]
    errors = list(Draft202012Validator(
        schema, format_checker=FormatChecker(),
    ).iter_errors(value))
    if errors:
        raise PortSchemaValidationError(_format_errors(errors))
    _walk_schema_annotations(value, schema)
    if not isinstance(context, Mapping):
        raise PortSchemaValidationError("trusted context is required for semantic validation")

    if shape == "config":
        _validate_config_semantics(port, value, context)
    elif shape == "request":
        _validate_request_semantics(port, value, context)
    elif shape == "result":
        _validate_result_semantics(port, value, context)
    else:
        _require_context_fields(context, "request", "extension_error_codes")
        _validate_error_lineage(value, context["request"])
        _validate_extension_error_code(value, context)

    refinement_field = {
        "config": "extension_config", "request": "extension_input",
        "result": "extension_output",
    }.get(shape)
    if refinement_field is not None and refinement_schema is None:
        if value[refinement_field] != {}:
            raise PortSchemaValidationError(
                f"{refinement_field} must be empty without a frozen refinement",
            )
    elif refinement_schema is not None:
        if shape == "error":
            raise PortSchemaValidationError("errors use frozen extension-error enums, not a schema")
        validate_refinement_schema(refinement_schema)
        try:
            refinement_errors = list(Draft202012Validator(
                refinement_schema, format_checker=FormatChecker(),
            ).iter_errors(value[refinement_field]))
        except (RecursionError, RuntimeError) as exc:
            raise PortSchemaValidationError("refinement validation did not terminate safely") from exc
        if refinement_errors:
            raise PortSchemaValidationError(
                "refinement rejected payload: " + _format_errors(refinement_errors),
            )


def _require_context_fields(context: Mapping[str, Any], *fields: str) -> None:
    missing = [field for field in fields if field not in context]
    if missing:
        raise PortSchemaValidationError(
            f"trusted context is missing required fields: {', '.join(missing)}",
        )


def _same_value(left: Any, right: Any) -> bool:
    try:
        return _canonical_key(left) == _canonical_key(right)
    except PortSchemaValidationError:
        return False


def _require_exact_record(record: Any, ref: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if not isinstance(record, Mapping) or not _same_ref(record.get("ref"), ref):
        raise PortSchemaValidationError(f"{label} does not carry the exact immutable ref")
    return record


def _validate_config_semantics(port: str, value: Mapping[str, Any],
                               context: Mapping[str, Any]) -> None:
    try:
        key = BindingSlotKeyV1.from_mapping(
            value["binding_slot_key"], expected_port_contract_version=port,
            expected_digest=value["binding_slot_key_digest"],
        )
    except PortContractError as exc:
        raise PortSchemaValidationError(str(exc)) from exc
    if key.port_contract_version != value["port_contract_version"]:
        raise PortSchemaValidationError("binding slot sibling port version mismatch")
    if (port in {"artifact-codec-port-v1", "storage-port-v1"}
            and value["resource_limits"]["max_artifacts"] < 1):
        raise PortSchemaValidationError("config cannot satisfy an exact-one result artifact row")
    _require_context_fields(
        context, "validated_at", "qualification_record", "binding_revision_record",
        "binding_head_record",
    )
    validated_at = _parse_time(context["validated_at"])
    qualification = _require_exact_record(
        context["qualification_record"], value["qualification_ref"], "qualification record",
    )
    if (qualification.get("status") != "qualified"
            or qualification.get("installation_digest") != value["installation_digest"]
            or qualification.get("port_contract_version") != port
            or not isinstance(qualification.get("expires_at"), str)
            or _parse_time(qualification["expires_at"]) <= validated_at):
        raise PortSchemaValidationError("qualification is not exact, passing, and unexpired")
    binding = _require_exact_record(
        context["binding_revision_record"], value["binding_revision_ref"],
        "binding revision record",
    )
    if (binding.get("state") != "active"
            or binding.get("extension_id") != value["extension_id"]
            or binding.get("installation_digest") != value["installation_digest"]
            or not _same_ref(binding.get("qualification_ref"), value["qualification_ref"])
            or binding.get("port_contract_version") != port
            or not _same_value(binding.get("binding_slot_key"), value["binding_slot_key"])
            or binding.get("binding_slot_key_digest") != value["binding_slot_key_digest"]
            or not _same_value(binding.get("grant_refs"), value["grant_refs"])
            or not _same_value(
                binding.get("credential_handle_refs"), value["credential_handle_refs"],
            )):
        raise PortSchemaValidationError("config differs from the active binding revision")
    head = context["binding_head_record"]
    if (not isinstance(head, Mapping) or head.get("state") != "active"
            or not _same_ref(head.get("current_binding_revision_ref"), value["binding_revision_ref"])
            or not _same_value(head.get("binding_slot_key"), value["binding_slot_key"])
            or head.get("binding_slot_key_digest") != value["binding_slot_key_digest"]):
        raise PortSchemaValidationError("config does not match the exact active binding head")


def _validate_error_lineage(error: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    if (error["request_id"] != request["request_id"]
            or error["operation"] != request["operation"]
            or error["port_contract_version"] != request["port_contract_version"]):
        raise PortSchemaValidationError("error does not match the exact request lineage")


def _validate_extension_error_code(error: Mapping[str, Any],
                                   context: Mapping[str, Any]) -> None:
    code = error["extension_error_code"]
    if code is None:
        return
    frozen = context.get("extension_error_codes")
    operation = error["operation"]
    allowed = frozen.get(operation) if isinstance(frozen, Mapping) else None
    if type(allowed) not in {list, tuple, set, frozenset} or code not in allowed:
        raise PortSchemaValidationError("extension error code is not manifest-frozen")


def _same_ref(left: Any, right: Any) -> bool:
    return type(left) is dict and type(right) is dict and _canonical_key(left) == _canonical_key(right)


def _refs_subset(values: list[Mapping[str, Any]], allowed: list[Mapping[str, Any]]) -> bool:
    allowed_keys = {_canonical_key(value) for value in allowed}
    return all(_canonical_key(value) in allowed_keys for value in values)


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise PortSchemaValidationError("invalid UTC calendar instant")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC,
        )
    except (TypeError, ValueError) as exc:
        raise PortSchemaValidationError("invalid UTC calendar instant") from exc


BUILTIN_TOOL_ARTIFACT_INPUT_CONTRACTS: dict[str, dict[str, Any]] = {
    name: {"mode": "none"}
    for name in (
        "public_fetch", "browser_navigate", "browser_observe", "browser_interact",
        "document_create_blank",
    )
}

_BROWSER_UPLOAD_MEDIA = (
    "application/json", "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "audio/mpeg", "audio/wav", "image/jpeg", "image/png", "image/webp", "text/csv",
    "text/markdown", "text/plain", "video/mp4",
)
_MULTIMODAL_MEDIA = (
    "application/pdf", "audio/mpeg", "audio/wav", "image/jpeg", "image/png", "image/webp",
    "video/mp4",
)
_DOCUMENT_MEDIA = (
    "application/json", "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg", "image/png", "image/webp", "text/csv", "text/markdown", "text/plain",
)


def _bounded_tool_contract(min_items: int, max_items: int, role: str,
                           media: tuple[str, ...], selector: str) -> dict[str, Any]:
    return {
        "mode": "bounded", "min_items": min_items, "max_items": max_items,
        "role": role, "allowed_media_types": list(media), "selector_policy": selector,
    }


BUILTIN_TOOL_ARTIFACT_INPUT_CONTRACTS.update({
    "browser_upload": _bounded_tool_contract(
        1, 16, "browser_upload", _BROWSER_UPLOAD_MEDIA, "forbidden",
    ),
    "multimodal_inspect": _bounded_tool_contract(
        1, 16, "multimodal_input", _MULTIMODAL_MEDIA, "optional",
    ),
    "document_compose": _bounded_tool_contract(
        0, 32, "document_source", _DOCUMENT_MEDIA, "optional",
    ),
    "document_transform": _bounded_tool_contract(
        1, 1, "document_source", _DOCUMENT_MEDIA, "optional",
    ),
    "document_extract": _bounded_tool_contract(
        1, 1, "document_source", _DOCUMENT_MEDIA, "optional",
    ),
    "pdf_render": _bounded_tool_contract(
        1, 1, "document_source", ("application/pdf",), "optional",
    ),
})


def _validate_tool_contract(tool_definition: Mapping[str, Any],
                            artifact_inputs: list[Mapping[str, Any]]) -> None:
    contract = tool_definition.get("artifact_input_contract")
    if type(contract) is not dict:
        raise PortSchemaValidationError("ToolDefinition lacks artifact_input_contract")
    tool_id = tool_definition.get("tool_id")
    if tool_id in BUILTIN_TOOL_ARTIFACT_INPUT_CONTRACTS:
        expected = BUILTIN_TOOL_ARTIFACT_INPUT_CONTRACTS[tool_id]
        if _canonical_key(contract) != _canonical_key(expected):
            raise PortSchemaValidationError("built-in ToolDefinition profile was widened or changed")
    if contract.get("mode") == "none":
        if set(contract) != {"mode"} or artifact_inputs:
            raise PortSchemaValidationError("tool forbids artifact inputs")
        return
    required = {
        "mode", "min_items", "max_items", "role", "allowed_media_types",
        "selector_policy",
    }
    if set(contract) != required or contract.get("mode") != "bounded":
        raise PortSchemaValidationError("ToolDefinition artifact contract is not closed")
    minimum = contract["min_items"]
    maximum = contract["max_items"]
    if (type(minimum) is not int or type(maximum) is not int
            or not 0 <= minimum <= maximum <= 32):
        raise PortSchemaValidationError("ToolDefinition artifact bounds are invalid")
    role = contract["role"]
    media = contract["allowed_media_types"]
    policy = contract["selector_policy"]
    if (type(role) is not str or re.fullmatch(IDENTIFIER_PATTERN, role) is None
            or type(media) is not list or not media
            or any(type(item) is not str
                   or re.fullmatch(MEDIA_TYPE_PATTERN, item) is None for item in media)
            or media != sorted(set(media)) or type(policy) is not str
            or policy not in {"forbidden", "optional", "required"}):
        raise PortSchemaValidationError("ToolDefinition artifact profile is malformed")
    if not minimum <= len(artifact_inputs) <= maximum:
        raise PortSchemaValidationError("tool artifact input cardinality mismatch")
    for binding in artifact_inputs:
        selector = binding["selector_ref"]
        if binding["role"] != role or binding["declared_media_type"] not in media:
            raise PortSchemaValidationError("tool artifact role/media mismatch")
        if ((policy == "forbidden" and selector is not None)
                or (policy == "required" and selector is None)):
            raise PortSchemaValidationError("tool artifact selector policy mismatch")


def _contains_artifact_ref(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_artifact_ref(item) for item in value)
    if not isinstance(value, dict):
        return False
    if set(value) >= {"kind", "id", "version", "sha256"}:
        kind = value.get("kind")
        if type(kind) is not str:
            raise PortSchemaValidationError("tool arguments contain a malformed ref marker")
        if kind in {"artifact", "artifact_input_selector", "selector"}:
            return True
    return any(_contains_artifact_ref(item) for item in value.values())


def _lookup_record(records: Mapping[str, Any], ref: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    record = records.get(ref["sha256"])
    if type(record) is not dict:
        raise PortSchemaValidationError(f"missing {label} record")
    stored_ref = record.get("ref")
    if not _same_ref(stored_ref, ref):
        raise PortSchemaValidationError(f"{label} record ref mismatch")
    return record


def _iter_named_refs(value: Any, field: str = "input"):
    if type(value) is dict:
        if set(value) == {"kind", "id", "version", "sha256"}:
            yield field, value
            return
        for name, child in value.items():
            yield from _iter_named_refs(child, name)
    elif type(value) is list:
        for child in value:
            yield from _iter_named_refs(child, field)


def _record_type_for_field(field: str) -> str:
    if field.endswith("_refs"):
        return field[:-5]
    if field.endswith("_ref"):
        return field[:-4]
    return field


def _validate_request_trusted_context(port: str, value: Mapping[str, Any],
                                      context: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_context_fields(
        context, "config", "accepted_at", "actor_record", "purpose_record",
        "grant_records", "artifact_records", "selector_records", "input_records",
    )
    config = context["config"]
    if not isinstance(config, Mapping):
        raise PortSchemaValidationError("trusted config is missing")
    if (config.get("port_contract_version") != port
            or config.get("installation_digest") != value["installation_digest"]
            or not _same_ref(config.get("qualification_ref"), value["qualification_ref"])
            or not _same_ref(config.get("binding_revision_ref"), value["binding_revision_ref"])
            or not _refs_subset(value["grant_refs"], config.get("grant_refs", []))):
        raise PortSchemaValidationError("request does not match validated config binding")
    actor = _require_exact_record(context["actor_record"], value["actor_ref"], "actor record")
    actor_type = actor.get("actor_type")
    if (actor.get("authenticated") is not True or type(actor_type) is not str
            or actor_type not in {"system", "worker"}):
        raise PortSchemaValidationError("request actor is not an authenticated system/worker")
    purpose = _require_exact_record(
        context["purpose_record"], value["purpose_ref"], "purpose record",
    )
    if (purpose.get("active") is not True
            or purpose.get("purpose") != config["binding_slot_key"]["purpose"]):
        raise PortSchemaValidationError("request purpose is not active for the binding slot")
    grant_records = context["grant_records"]
    if not isinstance(grant_records, Mapping):
        raise PortSchemaValidationError("trusted grant records are malformed")
    for grant_ref in value["grant_refs"]:
        grant = _lookup_record(grant_records, grant_ref, "grant")
        operations = grant.get("allowed_operations")
        if (grant.get("active") is not True
                or not _same_ref(grant.get("purpose_ref"), value["purpose_ref"])
                or type(operations) is not list or value["operation"] not in operations):
            raise PortSchemaValidationError("request grant is inactive or out of scope")
    input_records = context["input_records"]
    if not isinstance(input_records, Mapping):
        raise PortSchemaValidationError("trusted input records are malformed")
    for field, input_ref in _iter_named_refs(value["input"]):
        if input_ref.get("kind") in {"artifact", "artifact_input_selector", "selector"}:
            raise PortSchemaValidationError("operation input contains an artifact/selector ref")
        record = _lookup_record(input_records, input_ref, "operation input")
        expected_type = _record_type_for_field(field)
        if record.get("record_type") != expected_type:
            raise PortSchemaValidationError("operation input ref resolved to the wrong record type")
    return config


def _validate_request_semantics(port: str, value: Mapping[str, Any],
                                context: Mapping[str, Any]) -> None:
    operation = value["operation"]
    contract = OPERATION_CONTRACTS[(port, operation)]
    config = _validate_request_trusted_context(port, value, context)
    expected_key_body = {
        "port_contract_version": port,
        "installation_digest": value["installation_digest"],
        "binding_revision_ref": value["binding_revision_ref"],
        "purpose_ref": value["purpose_ref"],
        "operation": operation,
        "grant_refs": value["grant_refs"],
        "artifact_inputs": value["artifact_inputs"],
        "input": value["input"],
        "extension_input": value["extension_input"],
    }
    if sha256(canonical_json(expected_key_body)).hexdigest() != value["idempotency_key"]:
        raise PortSchemaValidationError("request idempotency key mismatch")
    accepted = _parse_time(context["accepted_at"])
    deadline = _parse_time(value["deadline_at"])
    if deadline <= accepted:
        raise PortSchemaValidationError("request deadline is not after acceptance")
    delta_ms = (deadline - accepted).total_seconds() * 1000
    if delta_ms > config["resource_limits"]["deadline_ms"]:
        raise PortSchemaValidationError("request deadline exceeds config limit")

    artifact_inputs = value["artifact_inputs"]
    source_field = {
        "F-model": ("frozen_record", "frozen_turn_ref"),
        "F-runner": ("frozen_record", "frozen_run_projection_ref"),
        "X-export-prepare": ("export_snapshot_record", "snapshot_ref"),
        "X-export-transmit": ("prepared_delivery_record", "prepared_delivery_ref"),
    }.get(contract.request_artifact_profile)
    if source_field is not None:
        context_field, request_field = source_field
        _require_context_fields(context, context_field)
        source = _require_exact_record(
            context[context_field], value["input"][request_field], context_field,
        )
        expected_inputs = source.get("artifact_input_bindings")
        if not _same_value(artifact_inputs, expected_inputs):
            raise PortSchemaValidationError("artifact inputs do not equal the frozen source list")
        if (not _same_ref(source.get("purpose_ref"), value["purpose_ref"])
                or not _same_value(source.get("grant_refs"), value["grant_refs"])):
            raise PortSchemaValidationError("frozen artifact source purpose/grants mismatch")
        if contract.request_artifact_profile.startswith("X-export") \
                and source.get("bounded_stream_authorized") is not True:
            raise PortSchemaValidationError("export artifact source lacks bounded-stream authority")
        if contract.request_artifact_profile == "X-export-transmit" and (
                not _same_ref(source.get("target_ref"), value["input"]["target_ref"])
                or not isinstance(source.get("expires_at"), str)
                or _parse_time(source["expires_at"]) <= accepted):
            raise PortSchemaValidationError("transmit differs from active prepared delivery")

    if contract.request_artifact_profile == "T-tool":
        _require_context_fields(context, "tool_definition", "resolved_arguments")
        tool_definition = context["tool_definition"]
        if (not isinstance(tool_definition, Mapping)
                or tool_definition.get("tool_id") != value["input"]["tool_id"]
                or tool_definition.get("version") != value["input"]["tool_version"]):
            raise PortSchemaValidationError("request tool does not match ToolDefinition")
        if not any(
            _same_ref(tool_definition.get("ref"), ref)
            for ref in config["port_config"]["tool_definition_refs"]
        ):
            raise PortSchemaValidationError("ToolDefinition is absent from config")
        if tool_definition.get("effect_class") != value["input"]["expected_effect_class"]:
            raise PortSchemaValidationError("ToolDefinition effect class differs from request")
        _validate_tool_contract(tool_definition, artifact_inputs)
        arguments = context["resolved_arguments"]
        if type(arguments) is not dict:
            raise PortSchemaValidationError("resolved tool arguments are not a closed object")
        argument_projection = json.loads(_canonical_key(arguments))
        if _contains_artifact_ref(argument_projection):
            raise PortSchemaValidationError("tool arguments contain a hidden artifact/selector ref")

    _validate_request_artifact_records(contract.request_artifact_profile, value, config, context)


def _validate_request_artifact_records(profile: str, request: Mapping[str, Any],
                                       config: Mapping[str, Any] | None,
                                       context: Mapping[str, Any]) -> None:
    records = context["artifact_records"]
    selectors = context["selector_records"]
    if not isinstance(records, Mapping) or not isinstance(selectors, Mapping):
        raise PortSchemaValidationError("trusted artifact/selector records are malformed")
    purpose_ref = request["purpose_ref"]
    total = 0
    allowed_media: set[str] | None = None
    if config is not None:
        port_config = config["port_config"]
        if profile in {"F-model", "F-runner"}:
            allowed_media = set(port_config["supported_input_media_types"])
        elif profile in {"C-one", "C-one-selected", "C-many"}:
            allowed_media = set(port_config["input_media_types"])
        elif profile == "S-one":
            allowed_media = set(port_config["accepted_value_media_types"])
        elif profile in {"X-export-prepare", "X-export-transmit"}:
            allowed_media = set(port_config["supported_media_types"])
    for binding in request["artifact_inputs"]:
        artifact = _lookup_record(records, binding["artifact_ref"], "artifact")
        if (artifact.get("readable") is not True
                or not _same_ref(artifact.get("purpose_ref"), purpose_ref)
                or not _same_value(artifact.get("grant_refs"), request["grant_refs"])):
            raise PortSchemaValidationError("artifact is not readable under exact purpose/grants")
        if artifact.get("media_type") != binding["declared_media_type"]:
            raise PortSchemaValidationError("declared artifact media differs from stored media")
        if allowed_media is not None and binding["declared_media_type"] not in allowed_media:
            raise PortSchemaValidationError("artifact media is not supported by config")
        byte_count = artifact.get("byte_count", artifact.get("size"))
        if type(byte_count) is not int or byte_count < 0:
            raise PortSchemaValidationError("artifact byte count is invalid")
        if config is not None and byte_count > config["resource_limits"]["max_artifact_bytes"]:
            raise PortSchemaValidationError("artifact exceeds config per-artifact bound")
        selector_ref = binding["selector_ref"]
        if selector_ref is None:
            total += byte_count
        else:
            selector = _lookup_record(selectors, selector_ref, "selector")
            if (not _same_ref(selector.get("source_artifact_ref"), binding["artifact_ref"])
                    or not _same_ref(selector.get("purpose_ref"), purpose_ref)
                    or selector.get("selector_digest") != selector_ref["sha256"]):
                raise PortSchemaValidationError("selector source/purpose mismatch")
            selected = selector.get("selected_byte_count")
            if type(selected) is not int or not 0 <= selected <= byte_count:
                raise PortSchemaValidationError("selector byte count is invalid")
            if (profile == "C-one-selected" and config is not None
                    and selector.get("selector_kind") not in config["port_config"]["selector_kinds"]):
                raise PortSchemaValidationError("selector kind is not qualified by codec config")
            total += selected
    if config is not None and total > config["resource_limits"]["max_artifact_input_bytes"]:
        raise PortSchemaValidationError("selected request bytes exceed aggregate config bound")


def _binding_projection(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_ref": binding["artifact_ref"],
        "role": binding["role"],
        "media_type": binding["media_type"],
        "omissions_ref": binding["omissions_ref"],
    }


def _result_projection(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_ref": artifact["artifact_ref"],
        "role": artifact["role"],
        "media_type": artifact["media_type"],
        "omissions_ref": artifact["omissions_ref"],
    }


def _validate_embedded_payload_shape(port: str, shape: str, value: Any) -> None:
    """Validate a previously refined payload's core shape without replaying its refinement."""
    if type(value) is not dict:
        raise PortSchemaValidationError(f"trusted {shape} is malformed")
    _check_global_bounds(value)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PortSchemaValidationError(f"trusted {shape} is not strict JSON") from exc
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise PortSchemaValidationError(
            f"trusted {shape} exceeds 1,048,576 bytes",
        )
    schema = generate_port_schemas()[(port, shape)]
    errors = list(Draft202012Validator(
        schema, format_checker=FormatChecker(),
    ).iter_errors(value))
    if errors:
        raise PortSchemaValidationError(f"trusted {shape} {_format_errors(errors)}")
    _walk_schema_annotations(value, schema)


def _require_result_bindings(context: Mapping[str, Any], field: str,
                             label: str) -> list[Mapping[str, Any]]:
    _require_context_fields(context, field)
    bindings = context[field]
    if type(bindings) is not list:
        raise PortSchemaValidationError(f"{label} are malformed")
    required = {"artifact_ref", "role", "media_type", "omissions_ref"}
    for binding in bindings:
        if not isinstance(binding, Mapping) or set(binding) != required:
            raise PortSchemaValidationError(f"{label} are malformed")
        artifact_ref = binding["artifact_ref"]
        omissions_ref = binding["omissions_ref"]
        if (list(Draft202012Validator(_ref()).iter_errors(artifact_ref))
                or (omissions_ref is not None
                    and list(Draft202012Validator(_ref()).iter_errors(omissions_ref)))
                or type(binding["role"]) is not str
                or re.fullmatch(IDENTIFIER_PATTERN, binding["role"]) is None
                or type(binding["media_type"]) is not str
                or re.fullmatch(MEDIA_TYPE_PATTERN, binding["media_type"]) is None):
            raise PortSchemaValidationError(f"{label} are malformed")
    return bindings


def _validate_result_semantics(port: str, value: Mapping[str, Any],
                               context: Mapping[str, Any]) -> None:
    _require_context_fields(context, "config", "request", "artifact_records")
    config = context["config"]
    request = context["request"]
    records = context["artifact_records"]
    _validate_embedded_payload_shape(port, "config", config)
    _validate_config_semantics(port, config, context)
    _validate_embedded_payload_shape(port, "request", request)
    _validate_request_semantics(port, request, context)
    if not isinstance(records, Mapping):
        raise PortSchemaValidationError("trusted artifact records are malformed")
    operation = value["operation"]
    terminal = value["terminal"]
    if (value["request_id"] != request["request_id"]
            or operation != request["operation"]
            or port != request["port_contract_version"]):
        raise PortSchemaValidationError("result does not match the exact request")
    if value["error"] is not None:
        _validate_error_lineage(value["error"], request)
    if (port == "tool-port-v1" and operation == "invoke_tool"
            and value["effect"]["effect_class"] != request["input"]["expected_effect_class"]):
        raise PortSchemaValidationError("tool result effect differs from expected class")
    if port == "export-sink-port-v1" and operation == "transmit":
        _require_context_fields(context, "transmit_effect_class")
        if value["effect"]["effect_class"] != context["transmit_effect_class"]:
            raise PortSchemaValidationError(
                "export result effect differs from frozen target effect class",
            )
    if value["error"] is not None:
        _require_context_fields(context, "extension_error_codes")
        if not isinstance(context["extension_error_codes"], Mapping):
            raise PortSchemaValidationError("extension error context is malformed")
        _validate_extension_error_code(value["error"], context)
    if (terminal != "unknown" and value["completed_at"] is not None
            and _parse_time(value["completed_at"]) < _parse_time(value["started_at"])):
        raise PortSchemaValidationError("completion precedes start")

    artifacts = value["artifacts"]
    if terminal == "succeeded":
        _validate_result_artifact_lineage(port, operation, value, context)
    elif artifacts:
        raise PortSchemaValidationError("non-success result cannot authorize artifacts")

    limits = config["resource_limits"]
    if len(artifacts) > limits["max_artifacts"]:
        raise PortSchemaValidationError("result artifacts exceed config count limit")
    for artifact in artifacts:
        stored = _lookup_record(records, artifact["artifact_ref"], "artifact")
        size = stored["byte_count"] if "byte_count" in stored else stored.get("size")
        digest = stored.get("content_digest", stored.get("digest"))
        if (type(size) is not int or size < 0
                or stored.get("media_type") != artifact["media_type"]
                or size != artifact["byte_count"]
                or digest != artifact["content_digest"]):
            raise PortSchemaValidationError("result artifact metadata differs from durable Artifact")
        if artifact["byte_count"] > limits["max_artifact_bytes"]:
            raise PortSchemaValidationError("result artifacts exceed config limits")


def _validate_result_artifact_lineage(port: str, operation: str,
                                      value: Mapping[str, Any],
                                      context: Mapping[str, Any]) -> None:
    contract = OPERATION_CONTRACTS[(port, operation)]
    artifacts = value["artifacts"]
    if contract.result_artifact_mode == "E":
        return
    output = value["output"]
    request = context.get("request")
    expected: list[dict[str, Any]] | None = None
    if port in {"provider-port-v1", "model-runtime-port-v1"} and operation == "model_step":
        expected_refs = output["content_block_refs"]
        if len(expected_refs) != len(artifacts) or any(
            not _same_ref(ref, artifact["artifact_ref"])
            for ref, artifact in zip(expected_refs, artifacts, strict=True)
        ):
            raise PortSchemaValidationError("model artifacts do not equal ordered content refs")
    elif port == "managed-provider-runner-port-v1" and operation == "run_status":
        expected = _require_result_bindings(
            context, "normalized_event_artifact_bindings",
            "normalized event artifact bindings",
        )
    elif port == "tool-port-v1" and operation == "invoke_tool":
        expected = _require_result_bindings(
            context, "tool_result_artifact_bindings", "sealed artifact bindings",
        )
        tool_definition = context["tool_definition"]
        _validate_tool_output_contract(tool_definition, expected)
    elif port == "artifact-codec-port-v1":
        field = {
            "decode_projection": "projection_artifact_ref",
            "render_preview": "preview_artifact_ref",
            "encode": "encoded_artifact_ref",
        }[operation]
        if not _same_ref(artifacts[0]["artifact_ref"], output[field]):
            raise PortSchemaValidationError("codec result artifact ref mismatch")
        if not _same_ref(artifacts[0]["omissions_ref"], output["omissions_ref"]):
            raise PortSchemaValidationError("codec omissions ref mismatch")
        if (operation in {"render_preview", "encode"}
                and artifacts[0]["media_type"] != request["input"]["target_media_type"]):
            raise PortSchemaValidationError("codec target/result media mismatch")
        if operation == "decode_projection":
            _require_context_fields(context, "target_projection_media_type")
            if artifacts[0]["media_type"] != context["target_projection_media_type"]:
                raise PortSchemaValidationError("decoded projection media mismatch")
    elif port == "storage-port-v1" and operation == "read":
        if not _same_ref(artifacts[0]["artifact_ref"], output["object_artifact_ref"]):
            raise PortSchemaValidationError("storage read artifact ref mismatch")
    if (expected is not None
            and [_result_projection(item) for item in artifacts] != [
                _binding_projection(item) for item in expected
            ]):
        raise PortSchemaValidationError("result artifacts differ from sealed artifact bindings")


def _validate_tool_output_contract(tool_definition: Mapping[str, Any],
                                   bindings: list[Mapping[str, Any]]) -> None:
    contract = tool_definition.get("artifact_output_contract")
    if type(contract) is not dict or set(contract) != {"min_items", "max_items", "roles"}:
        raise PortSchemaValidationError("ToolDefinition lacks a closed output artifact contract")
    minimum = contract["min_items"]
    maximum = contract["max_items"]
    roles = contract["roles"]
    if (type(minimum) is not int or type(maximum) is not int
            or not 0 <= minimum <= maximum <= 256 or type(roles) is not list or not roles):
        raise PortSchemaValidationError("tool output artifact contract is malformed")
    if not minimum <= len(bindings) <= maximum:
        raise PortSchemaValidationError("tool output artifact count mismatch")
    role_map: dict[str, Mapping[str, Any]] = {}
    for role in roles:
        if type(role) is not dict or set(role) != {
            "role", "allowed_media_types", "omissions_policy",
        }:
            raise PortSchemaValidationError("tool output role contract is not closed")
        name = role["role"]
        media = role["allowed_media_types"]
        policy = role["omissions_policy"]
        if (type(name) is not str or re.fullmatch(IDENTIFIER_PATTERN, name) is None
                or type(media) is not list or not media
                or any(type(item) is not str
                       or re.fullmatch(MEDIA_TYPE_PATTERN, item) is None for item in media)
                or media != sorted(set(media))
                or type(policy) is not str
                or policy not in {"forbidden", "optional", "required"}):
            raise PortSchemaValidationError("tool output role/media/omissions contract is invalid")
        if name in role_map:
            raise PortSchemaValidationError("tool output roles are not unique")
        role_map[name] = role
    for binding in bindings:
        role = role_map.get(binding["role"])
        if role is None or binding["media_type"] not in role["allowed_media_types"]:
            raise PortSchemaValidationError("tool result role/media is outside ToolDefinition")
        policy = role["omissions_policy"]
        omissions = binding["omissions_ref"]
        if ((policy == "forbidden" and omissions is not None)
                or (policy == "required" and omissions is None)):
            raise PortSchemaValidationError("tool result omissions policy mismatch")
