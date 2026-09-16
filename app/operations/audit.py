"""Aggregate event-coverage audit and secret-free public projections
(US7, T068; operations.md §4.2, FR-027).

`REQUIRED_COVERAGE` maps every OPS §4.2 required record group — including
the lifecycles T068 names explicitly — to the concrete event types that
satisfy it; `audit_event_coverage` returns the missing requirements
instead of passing silently. The event registry is an allowlist of counts,
flags and closed enums only, so no record handle, secret or provider raw
body can enter an event; `public_projection` validates a payload against
that allowlist and refuses any unknown field or value outright.
"""

from __future__ import annotations

from ..domain.events import EVENT_REGISTRY
from ..domain.refs import DomainContractError

REQUIRED_COVERAGE: dict[str, tuple[str, ...]] = {
    "deployment_request_lifecycle": (
        "deployment.request_prepared", "deployment.request_cancelled", "deployment.request_expired",
        "deployment.receipt_committed",
    ),
    "setup": ("setup.started", "setup.component_progress", "setup.failed"),
    "auth_recovery": (
        "auth.recovery_started", "auth.recovery_completed",
        "auth.recovery_failed",
    ),
    "service_client": (
        "service_client.created", "service_client.rotated",
        "service_client.revoked", "service_client.denied",
    ),
    "connection": ("connection.checked", "connection.changed"),
    "credential_erasure": (
        "credential.retired", "credential.cleanup_completed",
        "credential.erasure_confirmed", "credential.erasure_failed",
    ),
    "managed_login_lifecycle": (
        "managed_login.started", "managed_login.completed",
        "managed_login.cancelled", "managed_login.failed",
    ),
    "catalog": ("catalog.refreshed", "catalog.invalidated"),
    "model_selection": ("model.selected", "model.mismatch"),
    "extension_lifecycle": (
        "extension.discovered", "extension.staged", "extension.verified",
        "extension.qualified", "extension.enabled", "extension.failed",
        "extension.suspended", "extension.revoked", "extension.removed",
    ),
    "extension_binding": (
        "extension.binding_changed", "extension.compatibility_failed",
    ),
    "work_source_ingestion": (
        "work.created", "work.revised", "source.stored",
        "ingestion.completed", "ingestion.failed",
    ),
    "stt": (
        "speech.started", "speech.segment", "speech.stopped",
        "speech.interrupted", "speech.raw_unavailable",
    ),
    "understanding_design_review_selection": (
        "understanding.requested", "understanding.completed",
        "design.proposed", "design.repaired", "design.selected",
        "review.completed", "review.invalid",
    ),
    "run_attempt_tool_handoff_artifact": (
        "run.started", "run.stopped", "attempt.reserved",
        "attempt.dispatched", "attempt.terminal", "tool.requested",
        "tool.terminal", "handoff.delivered", "handoff.acknowledged",
        "artifact.sealed", "artifact.missing",
    ),
    "alternative_difference_hypothesis_inquiry_lens": (
        "alternative.saved", "difference.observed", "hypothesis.updated",
        "inquiry.frozen", "inquiry.evidence", "inquiry.declined",
        "lens.selected", "lens.composed", "lens.abstained",
    ),
    "candidate_evaluation_loop_stop": (
        "candidate.created", "candidate.frozen", "evaluation.started",
        "evaluation.result", "loop.updated", "loop.stopped",
    ),
    "validation_approval_promotion_rollback": (
        "validation.completed", "approval.requested", "approval.decided",
        "promotion.applied", "promotion.failed", "rollback.applied",
    ),
    "retention_export_backup_update_recovery_security": (
        "retention.changed", "retention.pruned", "retention.deleted",
        "export.previewed", "export.created", "backup.created",
        "backup.verified", "update.started", "update.failed",
        "recovery.reconciled", "security.denied", "record.gap",
    ),
}


class EventAuditError(ValueError):
    """A projection request or coverage check input is invalid."""


def audit_event_coverage(event_types) -> tuple[str, ...]:
    """Return every §4.2 requirement whose events are not all registered."""

    if not isinstance(event_types, (set, frozenset)):
        raise EventAuditError("expected the registered event type set")
    missing = []
    for requirement, satisfiers in sorted(REQUIRED_COVERAGE.items()):
        absent = [item for item in satisfiers if item not in event_types]
        if absent:
            missing.append(f"{requirement}: {', '.join(absent)}")
    return tuple(missing)


def public_projection(event_type, payload) -> dict:
    """Validate one payload against the allowlist; unknown fields refuse.

    The registry carries only counts, flags and closed enums — there is no
    free-text field anywhere, so no record handle, secret or provider raw
    body can pass this projection.
    """

    if type(event_type) is not str or event_type not in EVENT_REGISTRY:
        raise EventAuditError("unknown event type")
    fields = EVENT_REGISTRY[event_type]
    if type(payload) is not dict:
        raise EventAuditError("expected the event payload object")
    unknown = set(payload) - set(fields)
    if unknown:
        raise EventAuditError(
            "the payload carries fields outside the allowlist"
        )
    projected = {}
    for name, value in payload.items():
        try:
            projected[name] = fields[name].validate(value)
        except DomainContractError as exc:
            raise EventAuditError(
                f"the {name} field violates its allowlist"
            ) from exc
    return projected


__all__ = [
    "REQUIRED_COVERAGE",
    "EventAuditError",
    "audit_event_coverage",
    "public_projection",
]
