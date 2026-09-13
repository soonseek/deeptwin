"""US7 aggregate event coverage and secret-free public projections (T068).

Every OPS §4.2 required category — including the lifecycles T068 names
explicitly (deployment request/cancel/receipt, auth recovery,
credential retirement/cleanup/erasure/failure, managed-login lifecycle,
speech interrupted/raw-unavailable, extension qualification/binding) — has
registered event types, and the audit reports any missing requirement
instead of passing silently. The registry is an allowlist of counts, flags
and closed enums ONLY: no free-text field exists, so no record handle,
secret or provider raw body can ever enter an event; the public projection
validates against the allowlist and refuses unknown fields (FR-027).
"""

import pytest

from app.domain.events import EVENT_REGISTRY, EVENT_TYPES
from app.operations.audit import (
    REQUIRED_COVERAGE,
    EventAuditError,
    audit_event_coverage,
    public_projection,
)


def test_every_required_category_is_covered():
    missing = audit_event_coverage(EVENT_TYPES)
    assert missing == ()  # the audit closes, not merely reports


def test_the_audit_reports_missing_requirements_instead_of_passing():
    gutted = frozenset(
        item for item in EVENT_TYPES if not item.startswith("deployment.")
    )
    missing = audit_event_coverage(gutted)
    assert any("deployment" in requirement for requirement in missing)


def test_t068_named_lifecycles_exist():
    for event_type in (
        "deployment.request_prepared",
        "deployment.request_cancelled",
        "deployment.receipt_committed",
        "auth.recovery_started",
        "auth.recovery_completed",
        "auth.recovery_failed",
        "credential.retired",
        "credential.cleanup_completed",
        "credential.erasure_confirmed",
        "credential.erasure_failed",
        "managed_login.started",
        "managed_login.completed",
        "managed_login.cancelled",
        "managed_login.failed",
        "speech.interrupted",
        "speech.raw_unavailable",
        "extension.qualified",
        "extension.binding_changed",
    ):
        assert event_type in EVENT_TYPES, event_type


def test_the_registry_has_no_free_text_fields_at_all():
    for event_type, fields in EVENT_REGISTRY.items():
        for name, field in fields.items():
            assert field.kind in ("integer", "boolean", "enum"), (
                event_type, name,
            )
            if field.kind == "boolean":
                # a presence flag (e.g. key_present) can carry no content
                continue
            for banned in ("secret", "token", "handle", "raw_body", "path",
                           "url", "key"):
                assert banned not in name, (event_type, name)
            if field.kind == "enum":
                for value in field.values:
                    assert "/" not in value and ":" not in value, (
                        event_type, name, value,
                    )


def test_public_projections_validate_and_refuse_unknown_fields():
    projected = public_projection("deployment.request_cancelled",
                                  {"revision": 3})
    assert projected == {"revision": 3}
    with pytest.raises(EventAuditError):
        public_projection("deployment.request_cancelled", {
            "revision": 3, "record_handle": "vault://secret",
        })
    with pytest.raises(EventAuditError):
        public_projection("not.an_event", {})
    with pytest.raises(EventAuditError):
        public_projection("speech.raw_unavailable", {"reason_code": "banana"})


def test_required_coverage_is_itself_exact():
    # every requirement maps to event types that actually exist
    for requirement, satisfiers in REQUIRED_COVERAGE.items():
        assert satisfiers, requirement
        for event_type in satisfiers:
            assert event_type in EVENT_TYPES, (requirement, event_type)
