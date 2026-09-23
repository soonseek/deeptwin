"""Closed constants and pure validators for the conditional Claude semantic profile.

This module describes data.  It grants no qualification, binding, currentness,
credential, budget, or network authority.
"""

from __future__ import annotations

from hashlib import sha256
from functools import lru_cache
import re
import unicodedata
from uuid import NAMESPACE_URL, UUID, uuid5
from jsonschema import Draft202012Validator, FormatChecker
from datetime import datetime

from ..domain.refs import EntityRef, canonical_json

PROFILE = "claude-api-text-semantic-v1"
PORT = "provider-port-v1"
PROVIDER_ID = "claude_api"
API_VERSION = "2023-06-01"
MAX_INPUTS = 4
MAX_INPUT_BYTES = 262_144
MAX_OUTPUT_BLOCKS = 4
MAX_OUTPUT_BYTES = 524_288
MAX_OUTPUT_TOKENS = 8_192
MAX_OPERATION_MS = 30_000

_IDENTIFIER = re.compile(r"[a-z][a-z0-9._:-]{0,127}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_READS = frozenset({"capabilities", "catalog", "status"})
_OPERATIONS = frozenset(_READS | {"model_step", "cancel"})
_TERMINALS = {
    "capabilities": frozenset({"succeeded", "failed"}),
    "catalog": frozenset({"succeeded", "failed"}),
    "model_step": frozenset({"succeeded", "failed", "cancelled", "unknown"}),
    "status": frozenset({"succeeded", "failed"}),
    "cancel": frozenset({"succeeded", "failed"}),
}


class ProviderSemanticError(ValueError):
    """A value is outside the frozen profile; messages contain no upstream bytes."""


def _require(condition: bool, message: str = "invalid provider semantic value") -> None:
    if not condition:
        raise ProviderSemanticError(message)


def _uuid(value: object) -> str:
    _require(type(value) is str)
    try:
        parsed = UUID(value)
    except (ValueError, TypeError):
        raise ProviderSemanticError("invalid UUID") from None
    _require(str(parsed) == value and parsed.int != 0, "invalid UUID")
    return value


def digest(value: object) -> str:
    _require(type(value) is str and _HASH.fullmatch(value) is not None, "invalid digest")
    return value


def identifier(value: object) -> str:
    _require(type(value) is str and unicodedata.normalize("NFC", value) == value
             and _IDENTIFIER.fullmatch(value) is not None, "invalid identifier")
    return value


def exact_ref(value: object, kind: str | None = None) -> dict:
    try:
        parsed = EntityRef.from_dict(value)
    except (TypeError, ValueError):
        raise ProviderSemanticError("invalid immutable reference") from None
    _require(kind is None or parsed.kind == kind, "wrong reference kind")
    return parsed.as_dict()


def semantic_record_id(vault_uuid: str, tag: str, owner_uuid: str, ordinal: int = 0) -> str:
    _uuid(vault_uuid)
    _uuid(owner_uuid)
    _require(type(tag) is str and tag.startswith("provider-semantic-") and tag.endswith("-v1"))
    _require(type(ordinal) is int and 0 <= ordinal <= 255)
    return str(uuid5(NAMESPACE_URL,
                     f"deeptwin:provider-semantic:v1:{vault_uuid}:{tag}:{owner_uuid}:{ordinal}"))


def instruction_projection_digest(projection: dict) -> str:
    validate_instruction_projection(projection)
    return sha256(canonical_json(projection)).hexdigest()


def validate_instruction_projection(value: object) -> dict:
    _require(type(value) is dict and set(value) == {"profile_id", "system_artifact_ref"})
    _require(value["profile_id"] == "execution-model-step")
    if value["system_artifact_ref"] is not None:
        exact_ref(value["system_artifact_ref"], "artifact")
    return value


def _closed_ref_list(value: object, *, maximum: int = 32) -> list:
    _require(type(value) is list and len(value) <= maximum)
    for item in value:
        exact_ref(item)
    encoded = [canonical_json(item) for item in value]
    _require(encoded == sorted(encoded) and len(set(encoded)) == len(encoded))
    return value


def validate_frozen_content(value: object) -> dict:
    fields = {"schema_version", "turn", "execution_envelope_ref", "purpose_ref", "grant_refs",
              "artifact_input_bindings", "messages", "max_output_tokens", "instruction_projection"}
    _require(type(value) is dict and set(value) == fields)
    _require(value["schema_version"] == "provider-semantic-frozen-v1")
    exact_ref(value["execution_envelope_ref"], "execution_envelope")
    exact_ref(value["purpose_ref"])
    _closed_ref_list(value["grant_refs"])
    bindings = value["artifact_input_bindings"]
    _require(type(bindings) is list and 1 <= len(bindings) <= MAX_INPUTS)
    for binding in bindings:
        _require(type(binding) is dict and set(binding) == {
            "artifact_ref", "selector_ref", "declared_media_type", "role"})
        exact_ref(binding["artifact_ref"], "artifact")
        _require(binding["selector_ref"] is None and binding["declared_media_type"] == "text/plain"
                 and binding["role"] == "model_input")
    messages = value["messages"]
    _require(type(messages) is list and 1 <= len(messages) <= MAX_INPUTS)
    ordinals: list[int] = []
    system = None
    for index, message in enumerate(messages):
        _require(type(message) is dict and set(message) == {"role", "input_ordinals"})
        _require(message["role"] in {"system", "user", "assistant"})
        _require(message["role"] != "system" or index == 0)
        current = message["input_ordinals"]
        _require(type(current) is list and 1 <= len(current) <= MAX_INPUTS
                 and all(type(item) is int and item >= 0 for item in current))
        if message["role"] == "system":
            _require(len(current) == 1)
            system = bindings[current[0]]["artifact_ref"] if current[0] < len(bindings) else None
        ordinals.extend(current)
    _require(any(message["role"] == "user" for message in messages))
    _require(ordinals == list(range(len(bindings))))
    projection = validate_instruction_projection(value["instruction_projection"])
    _require(projection["system_artifact_ref"] == system)
    _require(type(value["max_output_tokens"]) is int
             and 1 <= value["max_output_tokens"] <= MAX_OUTPUT_TOKENS)
    turn = value["turn"]
    expected_turn = {"profile", "work_ref", "environment_ref", "node_id", "execution_id",
                     "attempt_index", "provider", "account_id", "catalog_ref", "model_id", "effort",
                     "instruction_profile_digest", "inputs", "granted_tools", "output_schema_id",
                     "runtime_profile_ref", "deadline_seconds", "budget_ref", "consent_ref"}
    _require(type(turn) is dict and set(turn) == expected_turn)
    _require(turn["profile"] == "execution-model-step" and turn["provider"] == PROVIDER_ID
             and turn["effort"] is None and turn["granted_tools"] == [])
    _require(turn["instruction_profile_digest"] == instruction_projection_digest(projection))
    _require(type(turn["attempt_index"]) is int and turn["attempt_index"] >= 0)
    _require(type(turn["deadline_seconds"]) is int and 1 <= turn["deadline_seconds"] <= 180)
    for name, kind in (("work_ref", "work_revision"), ("environment_ref", "environment"),
                       ("catalog_ref", "model_catalog"), ("runtime_profile_ref", "runtime_profile"),
                       ("budget_ref", "budget_policy"), ("consent_ref", "run_consent")):
        exact_ref(turn[name], kind)
    identifier(turn["node_id"])
    identifier(turn["account_id"])
    identifier(turn["model_id"])
    _uuid(turn["execution_id"])
    _require(turn["output_schema_id"] is None)
    inputs = turn["inputs"]
    _require(type(inputs) is list and len(inputs) == len(bindings))
    for index, item in enumerate(inputs):
        _require(type(item) is dict and set(item) == {"type", "ref", "marker", "omissions"})
        _require(item == {"type": "text", "ref": bindings[index]["artifact_ref"],
                          "marker": None, "omissions": []})
    return value


def permits_fresh_observation(port: str, profile: str, operation: str) -> bool:
    return port == PORT and profile == PROFILE and operation in _READS


def allowed_terminal(operation: str, terminal: str) -> bool:
    return operation in _TERMINALS and terminal in _TERMINALS[operation]


def validate_operation(operation: object) -> str:
    _require(type(operation) is str and operation in _OPERATIONS)
    return operation


@lru_cache(maxsize=3)
def _port_validator(shape: str):
    from .port_schema_generator import generate_port_schemas
    _require(shape in {"config", "request", "result"})
    return Draft202012Validator(
        generate_port_schemas()[(PORT, shape)],
        format_checker=FormatChecker())


def prewarm_port_validators() -> None:
    """Build the three canonical validators once, outside any request deadline.

    The first build generates and meta-validates all 44 port schemas, which takes
    seconds; paid inside a dialogue it consumes that dialogue's whole deadline."""
    for shape in ("config", "request", "result"):
        _port_validator(shape)


def validate_canonical_port_shape(shape: str, value: object) -> dict:
    _require(type(value) is dict)
    errors = list(_port_validator(shape).iter_errors(value))
    _require(not errors, f"invalid canonical provider {shape}")
    return value


def semantic_request_key(request: object) -> str:
    request = validate_canonical_port_shape("request", request)
    projection = {name: request[name] for name in (
        "port_contract_version", "installation_digest", "binding_revision_ref", "purpose_ref",
        "operation", "grant_refs", "artifact_inputs", "input", "extension_input")}
    expected = sha256(canonical_json(projection)).hexdigest()
    _require(request["idempotency_key"] == expected, "request semantic key mismatch")
    return expected


def _time(value):
    _require(type(value) is str and len(value) == 24)
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise ProviderSemanticError("invalid canonical port timestamp") from None
    return value


def _natural(value):
    _require(type(value) is int and 0 <= value <= 9_007_199_254_740_991)
    return value


def _positive(value):
    _natural(value); _require(value >= 1); return value


def _optional_value(value, validator):
    _require(type(value) is dict and set(value) == {"state", "value"}
             and value["state"] in {"absent", "null", "value"})
    if value["state"] == "value":
        _require(value["value"] is not None); validator(value["value"])
    else:
        _require(value["value"] is None)


def _blob(value, *, maximum=None):
    from ..domain.store import BlobRef
    try:
        parsed = BlobRef.from_dict(value)
    except (TypeError, ValueError):
        raise ProviderSemanticError("invalid operational blob ref") from None
    _require(parsed.purpose == "operational" and (maximum is None or parsed.size <= maximum))
    return parsed


def _validate_usage(content):
    for name in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                 "cache_read_input_tokens"):
        _optional_value(content[name], _natural)
    _optional_value(content["cache_creation"], lambda item: (
        _require(type(item) is dict and set(item) == {
            "ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"}),
        _natural(item["ephemeral_1h_input_tokens"]),
        _natural(item["ephemeral_5m_input_tokens"])))
    _optional_value(content["output_tokens_details"], lambda item: (
        _require(type(item) is dict and set(item) == {"thinking_tokens"}),
        _natural(item["thinking_tokens"])))
    _optional_value(content["server_tool_use"], lambda item: (
        _require(type(item) is dict and set(item) == {
            "web_fetch_requests", "web_search_requests"}),
        _natural(item["web_fetch_requests"]), _natural(item["web_search_requests"])))
    _optional_value(content["inference_geo"], lambda item: _require(
        type(item) is str and 1 <= len(item.encode("utf-8")) <= 128 and "\x00" not in item))
    _optional_value(content["service_tier"], lambda item: _require(
        item in {"standard", "priority", "batch"}))
    paths = content["unknown_categories"]
    _require(type(paths) is list and len(paths) <= 64 and paths == sorted(set(paths), key=str.encode)
             and all(type(path) is str and path.startswith("/")
                     and len(path.encode("utf-8")) <= 512 for path in paths))
    _require(content["cache_zero_basis"] == "request_omits_cache_and_tools"
             and content["currency_cost_known"] is False)


def _contained_refs(value):
    found = set()
    def walk(item):
        if type(item) is dict:
            if set(item) == {"kind", "id", "version", "sha256"}:
                found.add(EntityRef.from_dict(item)); return
            if set(item) == {"vault_id", "purpose", "sha256", "size"}:
                return
            for child in item.values(): walk(child)
        elif type(item) is list:
            for child in item: walk(child)
    walk(value)
    return tuple(sorted(found, key=lambda ref: canonical_json(ref.as_dict())))


def canonical_provider_result(request: dict, *, terminal: str, started_at: str,
                              completed_at: str | None, output=None, artifacts=None,
                              usage=None, effect=None, error=None) -> dict:
    """Construct and structurally validate one complete provider result envelope."""
    from .port_contracts import PORT_SCHEMA_IDS
    semantic_request_key(request)
    operation = request["operation"]
    if effect is None:
        effect_class = "none" if operation == "cancel" else "read"
        effect = {"effect_class": effect_class, "effect_state": "none",
                  "effect_receipt_ref": None, "remote_outcome": "not_applicable"}
    if usage is None:
        usage = {"input_units": None, "output_units": None, "billed_units": None,
                 "unit_name": None, "provider_report_ref": None}
    value = {"schema_id": PORT_SCHEMA_IDS[(PORT, "result")], "schema_version": 1,
             "port_contract_version": PORT, "request_id": request["request_id"],
             "operation": operation, "terminal": terminal, "started_at": started_at,
             "completed_at": completed_at, "output": {} if output is None else output,
             "extension_output": {}, "artifacts": [] if artifacts is None else artifacts,
             "usage": usage, "effect": effect, "error": error}
    return validate_canonical_port_shape("result", value)


def canonical_provider_error(request: dict, *, code: str, message_class: str,
                             retry_class: str, port_error_code=None,
                             affected_refs=None, evidence_ref=None) -> dict:
    from .port_contracts import PORT_SCHEMA_IDS
    return {"schema_id": PORT_SCHEMA_IDS[(PORT, "error")], "schema_version": 1,
            "port_contract_version": PORT, "request_id": request["request_id"],
            "operation": request["operation"], "code": code,
            "port_error_code": port_error_code, "extension_error_code": None,
            "message_class": message_class, "retry_class": retry_class,
            "affected_refs": [] if affected_refs is None else affected_refs,
            "evidence_ref": evidence_ref}


_CONTENT_FIELDS = {
    "provider-semantic-connection-v1": {"locator", "revision_digest", "provider_id", "account_id",
        "credential_metadata", "credential_metadata_sha256", "credential_record"},
    "provider-semantic-config-v1": {"config", "connection_ref", "text_policy_ref",
                                     "compatibility_set_ref"},
    "provider-semantic-text-policy-v1": {"source_url", "source_blob", "source_sha256",
        "retrieved_at", "reviewed_at", "valid_until", "scope_model_ids", "claim", "reviewer_ref"},
    "provider-semantic-reservation-v1": {"connection_ref", "model_id", "proposal_sha256",
        "input_upper_bound", "max_output_tokens", "currency", "reserved_microunits",
        "effective_at", "expires_at", "method_blob", "reviewer_ref", "basis"},
    "provider-semantic-compatibility-set-v1": {"profile_id", "connection_ref", "observation_refs"},
    "provider-semantic-compatibility-v1": {"profile_id", "connection_ref", "model_id",
        "request_policy_sha256", "observed_at", "expires_at", "observation_ref", "outcome"},
    "provider-semantic-operation-v1": {"request", "config_ref", "request_sha256", "core_boot_id",
                                       "frozen_ref", "envelope_ref", "reservation_ref"},
    "provider-semantic-response-v1": {"operation_ref", "exchange_id", "proposal_sha256", "status",
                                      "raw_blob", "raw_sha256", "raw_size", "phase", "observed_model",
                                      "stop_reason", "cancel_observed", "failure_class"},
    "provider-semantic-usage-v1": {"operation_ref", "response_ref", "input_tokens", "output_tokens",
                                   "cache_creation_input_tokens", "cache_read_input_tokens",
                                   "cache_creation", "output_tokens_details", "server_tool_use",
                                   "inference_geo", "service_tier", "unknown_categories",
                                   "cache_zero_basis", "currency_cost_known"},
    "provider-semantic-effect-v1": {"operation_ref", "response_ref", "request_sha256", "effect_state",
                                    "remote_outcome", "source"},
    "provider-semantic-output-v1": {"operation_ref", "ordinal", "blob_ref", "media_type",
                                    "content_digest", "byte_count"},
    "provider-semantic-terminal-v1": {"operation_ref", "result", "response_ref"},
    "provider-semantic-page-v1": {"operation_ref", "index", "after_id", "raw_blob", "raw_sha256",
        "raw_size", "first_id", "last_id", "has_more", "model_ids"},
    "provider-semantic-capability-v1": {"operation_ref", "page_ref", "model_index", "model_id",
        "text_policy_ref", "compatibility_ref", "observed_at", "valid_until", "projection"},
    "provider-semantic-catalog-v1": {"operation_ref", "connection_ref", "fetched_at", "expires_at",
        "page_refs", "complete", "models", "eligible_model_ids", "excluded"},
    "provider-semantic-idempotency-v1": {"request_id", "request_sha256", "operation_ref"},
    "provider-semantic-cancel-intent-v1": {"target_operation_ref", "first_cancel_operation_ref",
        "first_request_sha256", "reason_class", "core_boot_id"},
}


def validate_semantic_domain_body(body: dict) -> None:
    content = body["content"]
    schema = content.get("schema_version")
    if schema == "provider-semantic-frozen-v1":
        _require(body["kind"] == "frozen_turn" and body["version"] == 1
                 and body["purpose"] == "operational")
        validate_frozen_content(content)
        expected_parents = _contained_refs(content)
        actual_parents = tuple(EntityRef.from_dict(item) for item in body["parent_refs"])
        _require(actual_parents == expected_parents, "semantic parent projection mismatch")
        return
    if schema not in _CONTENT_FIELDS:
        return
    expected_kind = ("artifact" if schema == "provider-semantic-output-v1" else
                     "model_catalog" if schema == "provider-semantic-catalog-v1" else
                     "validation_report")
    _require(body["kind"] == expected_kind and body["version"] == 1
             and body["purpose"] == "operational")
    _require(set(content) == _CONTENT_FIELDS[schema] | {"schema_version"})
    if schema == "provider-semantic-connection-v1":
        from ..workers.credential_contracts import fingerprint, metadata_value, reference
        _require(type(content["locator"]) is dict
                 and set(content["locator"]) == {"kind", "id"}
                 and content["locator"]["kind"] == "connection")
        _uuid(content["locator"]["id"]); digest(content["revision_digest"])
        _require(content["provider_id"] == PROVIDER_ID); identifier(content["account_id"])
        metadata, record = metadata_value(content["credential_metadata"]), reference(
            content["credential_record"])
        _require(content["credential_metadata_sha256"] == fingerprint(metadata)
                 and metadata["provider"] == "claude" and metadata["auth_mode"] == "api"
                 and metadata["record_id"] == record["record_id"]
                 and metadata["record_version"] == record["record_version"])
    elif schema == "provider-semantic-config-v1":
        validate_canonical_port_shape("config", content["config"])
        exact_ref(content["connection_ref"], "validation_report")
        exact_ref(content["text_policy_ref"], "validation_report")
        exact_ref(content["compatibility_set_ref"], "validation_report")
        _require(content["config"]["credential_handle_refs"] == [content["connection_ref"]])
    elif schema == "provider-semantic-operation-v1":
        semantic_request_key(content["request"])
        exact_ref(content["config_ref"])
        digest(content["request_sha256"])
        _require(content["request_sha256"] == sha256(
            canonical_json(content["request"])).hexdigest(), "operation request digest mismatch")
        _uuid(content["core_boot_id"])
        for name in ("frozen_ref", "envelope_ref", "reservation_ref"):
            if content[name] is not None:
                exact_ref(content[name])
        model = content["request"]["operation"] == "model_step"
        _require(model == (content["frozen_ref"] is not None)
                 and model == (content["envelope_ref"] is not None)
                 and (not model or content["request"]["input"]["frozen_turn_ref"]
                      == content["frozen_ref"]))
    elif schema == "provider-semantic-response-v1":
        exact_ref(content["operation_ref"], "validation_report")
        _uuid(content["exchange_id"]); digest(content["proposal_sha256"])
        _require(content["status"] is None or type(content["status"]) is int and 100 <= content["status"] <= 599)
        _require(content["phase"] in {"not_sent", "may_have_sent", "terminal_observed"}
                 and type(content["cancel_observed"]) is bool)
        failure_classes = {"permission_denied", "deadline_exceeded", "resource_exhausted",
            "unsupported_capability", "integrity_failed", "dependency_unavailable",
            "cancelled", "internal_failure"}
        _require(content["failure_class"] is None or type(content["failure_class"]) is str
                 and content["failure_class"] in failure_classes)
        _require((content["raw_blob"] is None and content["raw_sha256"] is None and content["raw_size"] == 0)
                 or (type(content["raw_blob"]) is dict and content["raw_blob"].get("sha256") == content["raw_sha256"]
                     and content["raw_blob"].get("size") == content["raw_size"]))
        if content["raw_blob"] is not None:
            blob = _blob(content["raw_blob"], maximum=1_048_576)
            _require(blob.sha256 == content["raw_sha256"] and blob.size == content["raw_size"])
        _require(content["phase"] != "not_sent" or (content["status"] is None
                 and content["raw_blob"] is None and content["raw_size"] == 0))
        _require(content["failure_class"] != "cancelled" or content["cancel_observed"])
        if content["observed_model"] is not None: identifier(content["observed_model"])
        if content["stop_reason"] is not None: identifier(content["stop_reason"])
    elif schema == "provider-semantic-text-policy-v1":
        _require(content["source_url"] == "https://platform.claude.com/docs/en/models/overview"
                 and content["claim"] == "current-models-text-input-output")
        blob = _blob(content["source_blob"], maximum=1_048_576)
        _require(blob.sha256 == content["source_sha256"])
        for name in ("retrieved_at", "reviewed_at", "valid_until"): _time(content[name])
        scope = content["scope_model_ids"]
        _require(type(scope) is list and 1 <= len(scope) <= 256
                 and scope == sorted(set(scope), key=str.encode))
        for item in scope: identifier(item)
        exact_ref(content["reviewer_ref"], "actor")
    elif schema == "provider-semantic-reservation-v1":
        exact_ref(content["connection_ref"], "validation_report"); identifier(content["model_id"])
        digest(content["proposal_sha256"]); _positive(content["input_upper_bound"])
        _positive(content["max_output_tokens"])
        _require(type(content["currency"]) is str
                 and re.fullmatch(r"[A-Z]{3}", content["currency"]) is not None)
        _positive(content["reserved_microunits"]); _time(content["effective_at"]); _time(content["expires_at"])
        _blob(content["method_blob"], maximum=65_536); exact_ref(content["reviewer_ref"], "actor")
        _require(content["basis"] == "reviewed-conservative-estimate")
    elif schema == "provider-semantic-compatibility-set-v1":
        _require(content["profile_id"] == PROFILE)
        exact_ref(content["connection_ref"], "validation_report")
        refs = content["observation_refs"]
        _require(type(refs) is list and len(refs) <= 256
                 and refs == sorted(refs, key=canonical_json)
                 and len({canonical_json(ref) for ref in refs}) == len(refs))
        for ref in refs: exact_ref(ref, "validation_report")
    elif schema == "provider-semantic-compatibility-v1":
        _require(content["profile_id"] == PROFILE and content["outcome"] == "complete_text")
        exact_ref(content["connection_ref"], "validation_report"); identifier(content["model_id"])
        digest(content["request_policy_sha256"]); _time(content["observed_at"]); _time(content["expires_at"])
        exact_ref(content["observation_ref"])
    elif schema == "provider-semantic-page-v1":
        exact_ref(content["operation_ref"], "validation_report"); _natural(content["index"])
        _require(content["index"] < 20 and type(content["has_more"]) is bool)
        blob = _blob(content["raw_blob"], maximum=1_048_576)
        _require(blob.sha256 == content["raw_sha256"] and blob.size == content["raw_size"] and blob.size > 0)
        ids = content["model_ids"]
        _require(type(ids) is list and len(ids) <= 100 and len(set(ids)) == len(ids))
        for item in ids: identifier(item)
        for name in ("after_id", "first_id", "last_id"):
            if content[name] is not None: identifier(content[name])
        _require((not ids and content["first_id"] is None and content["last_id"] is None
                  and not content["has_more"])
                 or (bool(ids) and content["first_id"] == ids[0] and content["last_id"] == ids[-1]))
    elif schema == "provider-semantic-capability-v1":
        from ..workers.provider_semantic_codec import validate_model_projection
        exact_ref(content["operation_ref"], "validation_report"); exact_ref(content["page_ref"], "validation_report")
        _natural(content["model_index"]); _require(content["model_index"] < 100)
        identifier(content["model_id"]); exact_ref(content["text_policy_ref"], "validation_report")
        if content["compatibility_ref"] is not None: exact_ref(content["compatibility_ref"], "validation_report")
        _time(content["observed_at"]); _time(content["valid_until"])
        validate_model_projection(content["projection"])
        _require(content["projection"]["id"] == content["model_id"])
    elif schema == "provider-semantic-catalog-v1":
        exact_ref(content["operation_ref"], "validation_report"); exact_ref(content["connection_ref"], "validation_report")
        _time(content["fetched_at"]); _time(content["expires_at"])
        _require(type(content["complete"]) is bool and content["complete"])
        pages, models, eligible, excluded = (content[name] for name in
            ("page_refs", "models", "eligible_model_ids", "excluded"))
        _require(type(pages) is list and 1 <= len(pages) <= 20)
        for ref in pages: exact_ref(ref, "validation_report")
        _require(type(models) is list and len(models) <= 256 and type(eligible) is list
                 and type(excluded) is list and len(eligible) + len(excluded) == len(models))
        model_ids = []
        for row in models:
            _require(type(row) is dict and set(row) == {"model_id", "display_name", "modalities",
                "effort_values", "capability_evidence_ref"})
            identifier(row["model_id"]); model_ids.append(row["model_id"])
            _require(type(row["display_name"]) is str and 1 <= len(row["display_name"].encode()) <= 512
                     and row["modalities"] in ([], ["text"]))
            efforts = row["effort_values"]
            _require(type(efforts) is list
                     and efforts == sorted(set(efforts), key=str.encode)
                     and all(item in {"high", "low", "max", "medium", "xhigh"}
                             for item in efforts), "invalid catalog effort values")
            exact_ref(row["capability_evidence_ref"], "validation_report")
        _require(len(model_ids) == len(set(model_ids)))
        for item in eligible: identifier(item)
        for item in excluded:
            _require(type(item) is dict and set(item) == {"model_id", "reason"}
                     and item["reason"] in {"capability_unknown", "limits_unknown",
                                            "text_scope_unproved", "profile_unproved"})
            identifier(item["model_id"])
        excluded_ids = [item["model_id"] for item in excluded]
        eligible_set, excluded_set = set(eligible), set(excluded_ids)
        _require(len(eligible) == len(eligible_set)
                 and len(excluded_ids) == len(excluded_set)
                 and not eligible_set & excluded_set
                 and set(model_ids) == eligible_set | excluded_set
                 and eligible == [item for item in model_ids if item in eligible_set]
                 and excluded_ids == [item for item in model_ids if item in excluded_set],
                 "catalog eligibility does not retain API order")
    elif schema == "provider-semantic-usage-v1":
        exact_ref(content["operation_ref"], "validation_report"); exact_ref(content["response_ref"], "validation_report")
        _validate_usage(content)
    elif schema == "provider-semantic-effect-v1":
        exact_ref(content["operation_ref"], "validation_report"); exact_ref(content["response_ref"], "validation_report")
        digest(content["request_sha256"])
        _require(content["effect_state"] in {"none", "not_committed", "committed", "unknown"}
                 and content["remote_outcome"] in {"not_applicable", "confirmed", "unconfirmed", "unknown"}
                 and content["source"] == "gateway_observation")
    elif schema == "provider-semantic-output-v1":
        exact_ref(content["operation_ref"], "validation_report")
        _require(type(content["ordinal"]) is int and 0 <= content["ordinal"] < 4
                 and content["media_type"] == "text/plain"
                 and content["blob_ref"].get("sha256") == content["content_digest"]
                 and content["blob_ref"].get("size") == content["byte_count"])
    elif schema == "provider-semantic-terminal-v1":
        exact_ref(content["operation_ref"], "validation_report")
        if content["response_ref"] is not None:
            exact_ref(content["response_ref"], "validation_report")
        result = validate_canonical_port_shape("result", content["result"])
        _require(allowed_terminal(result.get("operation"), result.get("terminal")))
        if result["terminal"] != "succeeded":
            _require(result.get("artifacts", []) == [])
    elif schema == "provider-semantic-idempotency-v1":
        _uuid(content["request_id"]); digest(content["request_sha256"])
        exact_ref(content["operation_ref"], "validation_report")
    elif schema == "provider-semantic-cancel-intent-v1":
        exact_ref(content["target_operation_ref"], "validation_report")
        exact_ref(content["first_cancel_operation_ref"], "validation_report")
        digest(content["first_request_sha256"]); _uuid(content["core_boot_id"])
        _require(content["reason_class"] in {"user_requested", "deadline", "budget",
            "superseded", "shutdown", "policy_revoked"})

    expected_parents = _contained_refs(content)
    if schema == "provider-semantic-compatibility-set-v1":
        expected_parents = (EntityRef.from_dict(content["connection_ref"]),)
    elif schema == "provider-semantic-catalog-v1":
        expected_parents = tuple(sorted({EntityRef.from_dict(content["operation_ref"]),
            EntityRef.from_dict(content["connection_ref"]),
            *(EntityRef.from_dict(item) for item in content["page_refs"])},
            key=lambda ref: canonical_json(ref.as_dict())))
    actual_parents = tuple(EntityRef.from_dict(item) for item in body["parent_refs"])
    _require(actual_parents == expected_parents, "semantic parent projection mismatch")


__all__ = [name for name in globals() if not name.startswith("_")]
