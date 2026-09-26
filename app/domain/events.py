"""Versioned metadata allowlists. Private evidence and authorization live elsewhere.

    Fields are optional observations unless a specific event requires its exact set.
    Absence is unknown, never zero. New event fields
    require an explicit code/schema change, not an untrusted arbitrary telemetry dictionary.
"""

from dataclasses import dataclass
from types import MappingProxyType

from .refs import DomainContractError, MAX_INTEGER, canonical_json


@dataclass(frozen=True, slots=True)
class Field:
    kind: str
    values: tuple = ()

    def validate(self, value):
        if self.kind == "integer":
            minimum, maximum = self.values or (0, MAX_INTEGER)
            valid = type(value) is int and minimum <= value <= maximum
        elif self.kind == "boolean":
            valid = type(value) is bool
        else:
            valid = type(value) is str and value in self.values
        if not valid:
            raise DomainContractError("Invalid event metadata field")
        return value

    def schema(self):
        if self.kind == "integer":
            minimum, maximum = self.values or (0, MAX_INTEGER)
            return {"type": "integer", "minimum": minimum, "maximum": maximum}
        if self.kind == "boolean":
            return {"type": "boolean"}
        return {"type": "string", "enum": list(self.values)}


COUNT = Field("integer")
FLAG = Field("boolean")
PROVIDER = Field("enum", ("codex", "claude"))
MODE = Field("enum", ("subscription", "api"))
VALIDITY = Field("enum", ("valid", "invalid", "not_checked"))
COMPARISON_VALIDITY = Field("enum", ("valid", "invalid", "pending"))
OUTCOME = Field("enum", ("succeeded", "failed", "denied", "timed_out", "cancelled", "outcome_unknown"))
END_REASON = Field("enum", ("completed", "plateau", "budget_exhausted", "below_quality_floor",
                            "cancelled", "safety_halt", "outcome_unknown", "infrastructure_failure"))
LOOP_REASON = Field("enum", ("plateau_reached", "budget_exhausted", "below_floor_exhausted",
                            "evidence_blocked", "safety_stop", "human_stop", "lineage_changed"))
GAP_REASON = Field("enum", ("missing", "deleted", "corrupt", "not_recorded", "access_denied",
                            "outcome_unknown", "storage_failed", "unsupported", "not_supplied"))
EXTENSION_KIND = Field("enum", ("provider", "model_runtime", "tool", "artifact_codec", "lens",
                                "evaluator", "storage", "credential_vault", "export_sink"))
TRUST_TIER = Field("enum", ("deployment_trusted", "runtime_worker", "definition_package",
                            "managed_provider_runner"))
EXTENSION_STATE = Field("enum", ("discovered", "staged", "verified", "qualified", "enabled",
                                  "failed", "suspended", "revoked", "removed"))
SERVICE_CLIENT_DENIAL = Field("enum", (
    "credential", "expired", "revoked", "network", "scope", "owner", "identifier",
    "conflict", "expiry", "name", "state", "internal",
))
CONFORMANCE_OUTCOME = Field("enum", ("matched", "mismatch", "incomplete"))
PORT_CONTRACT = Field("enum", ("provider-port-v1", "managed-provider-runner-port-v1",
    "model-runtime-port-v1", "tool-port-v1", "artifact-codec-port-v1", "evaluator-runtime-port-v1",
    "storage-port-v1", "credential-vault-port-v1", "export-sink-port-v1"))
BINDING_PURPOSE = Field("enum", ("operational", "diagnosis", "inquiry_audit", "evaluation_development",
                                 "evaluation_sealed", "release_evidence"))
RETENTION_STATE = Field("enum", ("absent", "retained", "released", "consumed"))
_registry = {}


def _register(names, **fields):
    for name in names.split():
        if name in _registry:
            raise RuntimeError("Duplicate event registration")
        _registry[name] = MappingProxyType(dict(fields))


_register("setup.started", component_count=COUNT)
_register("owner.created session.created session.revoked", session_count=COUNT)
_register("setup.component_progress", completed_count=COUNT, total_count=COUNT, byte_count=COUNT)
_register("setup.failed update.failed promotion.failed", reason_code=GAP_REASON)
_register("connection.checked connection.changed", provider=PROVIDER, auth_mode=MODE,
          key_present=FLAG, ready=FLAG)
_register("catalog.refreshed catalog.invalidated", model_count=COUNT, complete=FLAG)
_register("model.selected model.mismatch", provider=PROVIDER, auth_mode=MODE, revision=COUNT)
_register("work.created work.revised", revision=COUNT, source_count=COUNT)
_register("source.stored", byte_count=COUNT)
_register("ingestion.completed", supplied_count=COUNT, omitted_count=COUNT, complete=FLAG)
_register("ingestion.failed", reason_code=GAP_REASON)
_register("speech.started", local=FLAG)
_register("speech.segment", segment_index=COUNT, final=FLAG, duration_ms=COUNT)
_register("speech.stopped", segment_count=COUNT, duration_ms=COUNT)
_register("understanding.requested understanding.completed", revision=COUNT, duration_ms=COUNT)
_register("design.proposed design.repaired", candidate_count=COUNT, revision=COUNT)
_register("design.selected", revision=COUNT)
_register("review.completed review.invalid", validity=VALIDITY, gate_count=COUNT,
          failed_count=COUNT, unknown_count=COUNT)
_register("run.started", node_count=COUNT, edge_count=COUNT)
_register("run.stopped", reason_code=END_REASON, duration_ms=COUNT)
_register("attempt.reserved attempt.dispatched", attempt_no=COUNT)
_register("attempt.response_captured", artifact_count=COUNT,
          classification=Field("enum", ("pending_validation", "quarantined")))
_register("attempt.terminal tool.terminal", outcome=OUTCOME, duration_ms=COUNT)
# the ports contract's closed effect vocabulary (extension-ports.md `effect-class`), the one set the
# tool boundary, the ledger's ToolCall and the extension transport share; pinned equal to
# app.extensions.port_contracts.EFFECT_CLASSES by the domain events tests (no import cycle here)
TOOL_EFFECT_CLASSES = (
    "external_irreversible", "external_reversible", "instance_critical_secret",
    "instance_critical_storage", "none", "read", "write_reversible",
)
_register("tool.requested", effect_class=Field("enum", TOOL_EFFECT_CLASSES))
_register("artifact.sealed", byte_count=COUNT)
_register("artifact.missing", reason_code=GAP_REASON)
_register("handoff.delivered handoff.acknowledged", artifact_count=COUNT, supplied_count=COUNT,
          omitted_count=COUNT)
_register("memory.read", considered_count=COUNT, selected_count=COUNT, supplied_count=COUNT)
_register("memory.written", item_count=COUNT)
_register("alternative.saved", partial=FLAG, revision=COUNT)
# the owner's process feedback (services/run_feedback.py): never an alternative, never the memo
# text — only which target kind, which mark, whether a memo exists, whether it was a clear
_register("feedback.recorded", scope=Field("enum", ("run", "step")),
          mark=Field("enum", ("ok", "needs_attention", "none")), memo=FLAG, cleared=FLAG, revision=COUNT)
_register("difference.observed", difference_count=COUNT)
_register("hypothesis.updated", revision=COUNT)
_register("inquiry.frozen", question_count=COUNT, prediction_count=COUNT)
_register("inquiry.evidence", evidence_count=COUNT)
_register("inquiry.declined", deferred=FLAG)
_register("lens.selected lens.composed", component_count=COUNT)
_register("lens.abstained", reason_code=Field("enum", ("out_of_scope", "insufficient_evidence",
                                                       "conflict", "unqualified", "not_applicable")))
_register("candidate.created candidate.frozen", revision=COUNT)
_register("evaluation.started", case_count=COUNT, round_index=COUNT)
_register("evaluation.result", validity=COMPARISON_VALIDITY, completed_count=COUNT, failed_count=COUNT)
_register("loop.updated", round_count=COUNT, patience_count=COUNT, best_changed=FLAG)
_register("loop.stopped", reason_code=LOOP_REASON, round_count=COUNT, patience_count=COUNT)
_register("validation.completed", passed_count=COUNT, failed_count=COUNT, unknown_count=COUNT)
_register("approval.requested", approval_kind=Field("enum", ("design", "run", "action", "promotion", "rollback")))
_register("approval.decided", decision=Field("enum", ("approved", "rejected", "expired", "revoked")))
_register("promotion.applied rollback.applied", revision=COUNT)
_register("retention.changed", revision=COUNT)
_register("retention.pruned retention.deleted", object_count=COUNT, byte_count=COUNT)
_register("export.previewed export.created", object_count=COUNT, gap_count=COUNT,
          redacted_count=COUNT, byte_count=COUNT)
_register("backup.created backup.verified", object_count=COUNT, byte_count=COUNT, verified=FLAG)
_register("update.started", component_count=COUNT)
_register("recovery.reconciled", recovered_count=COUNT, unknown_count=COUNT)
_register("security.denied record.gap", reason_code=GAP_REASON)
_register("extension.discovered extension.staged extension.verified extension.qualified "
          "extension.enabled extension.failed extension.suspended extension.revoked extension.removed",
          extension_kind=EXTENSION_KIND, trust_tier=TRUST_TIER, revision=COUNT)
_register("extension.binding_changed", extension_kind=EXTENSION_KIND,
          trust_tier=TRUST_TIER, revision=COUNT)
# data-model.md "Extension lifecycle": one exact event per durable binding-head move and per rollback-
# retention revision, committed in the binding transaction. The public payload is the allowlist below
# (kinds, enums, revisions, counts); the exact slot, revision and retention records travel as the event's
# `object_refs` (`extension_binding` records whose ids derive from the recomputed slot-key digest), so a
# stale event names its own slot and cannot be applied to a sibling same-port slot.
_register("extension.binding_activated extension.binding_superseded extension.binding_disabled "
          "extension.binding_rolled_back", extension_kind=EXTENSION_KIND, trust_tier=TRUST_TIER,
          port_contract_version=PORT_CONTRACT, purpose=BINDING_PURPOSE, revision=COUNT,
          previous_revision=COUNT, affected_environment_count=COUNT)
_register("extension.rollback_retention_created extension.rollback_retention_released "
          "extension.rollback_retention_consumed", extension_kind=EXTENSION_KIND, trust_tier=TRUST_TIER,
          port_contract_version=PORT_CONTRACT, purpose=BINDING_PURPOSE, retention_revision=COUNT,
          target_revision=COUNT, binding_revision=COUNT, previous_state=RETENTION_STATE,
          state=RETENTION_STATE)
_register("extension.candidate_registered", extension_kind=EXTENSION_KIND,
          port_contract_version=PORT_CONTRACT,
          candidate_count=Field("integer", (1, 1)), byte_count=Field("integer", (1, 1114112)))
_register("extension.compatibility_failed", extension_kind=EXTENSION_KIND,
          trust_tier=TRUST_TIER, revision=COUNT,
          reason_code=Field("enum", ("framework", "extension_api", "schema", "runtime",
                                     "platform", "permission", "expired", "bytes")))
_register("service_client.created service_client.rotated service_client.revoked",
          scope_count=COUNT, revision=COUNT)
_register("service_client.denied", reason_code=SERVICE_CLIENT_DENIAL)
_register("deployment.request_prepared deployment.request_cancelled deployment.request_expired "
          "deployment.receipt_committed deployment.request_accepted", revision=COUNT)
_register("auth.recovery_started auth.recovery_completed", revision=COUNT)
_register("auth.recovery_failed", reason_code=GAP_REASON)
_register("credential.retired credential.cleanup_completed "
          "credential.erasure_confirmed", revision=COUNT)
_register("credential.erasure_failed", reason_code=GAP_REASON)
_register("managed_login.started managed_login.completed managed_login.cancelled",
          provider=PROVIDER)
_register("managed_login.failed", provider=PROVIDER, reason_code=GAP_REASON)
_register("speech.interrupted", segment_count=COUNT)
_register("speech.raw_unavailable", reason_code=GAP_REASON)
_register("provider.conformance_started", vector_count=Field("integer", (4, 4)))
_register("provider.conformance_completed", completed_count=Field("integer", (0, 4)),
          matched_count=Field("integer", (0, 4)), outcome=CONFORMANCE_OUTCOME)
EVENT_TYPES = frozenset(_registry)
EVENT_REGISTRY = MappingProxyType(_registry)
# Do not retain a separately mutable reference to the registry.
del _registry


_EXACT = frozenset({
    "extension.candidate_registered", "provider.conformance_started", "provider.conformance_completed",
    "extension.binding_activated", "extension.binding_superseded", "extension.binding_disabled",
    "extension.binding_rolled_back", "extension.rollback_retention_created",
    "extension.rollback_retention_released", "extension.rollback_retention_consumed",
    "feedback.recorded",
})


def event_schema(event_type):
    if type(event_type) is not str or event_type not in EVENT_REGISTRY:
        raise DomainContractError("Unregistered event type")
    result = {"type": "object", "properties": {name: field.schema()
            for name, field in EVENT_REGISTRY[event_type].items()}, "additionalProperties": False}
    if event_type in _EXACT:
        result["required"] = list(EVENT_REGISTRY[event_type])
    return result


def event_metadata(event_type, payload):
    if type(event_type) is not str or event_type not in EVENT_REGISTRY:
        raise DomainContractError("Unregistered event type")
    if type(payload) is not dict:
        raise DomainContractError("Event metadata must be an object")
    fields = EVENT_REGISTRY[event_type]
    if set(payload) - fields.keys():
        raise DomainContractError("Unregistered event metadata field")
    if event_type in _EXACT and set(payload) != fields.keys():
        raise DomainContractError("Event requires exact observations")
    result = {name: fields[name].validate(value) for name, value in payload.items()}
    if event_type == "provider.conformance_completed" and result["matched_count"] > result["completed_count"]:
        raise DomainContractError("Invalid conformance event counts")
    canonical_json(result)
    return result
