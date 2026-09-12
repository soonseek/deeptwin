"""Event payloads are bounded allowlists, never arbitrary telemetry dictionaries."""

import pytest

from app.domain.events import EVENT_TYPES, event_metadata, event_schema
from app.domain.refs import DomainContractError


REQUIRED_TYPES = """
setup.started setup.component_progress setup.failed connection.checked connection.changed
catalog.refreshed catalog.invalidated model.selected model.mismatch work.created work.revised
source.stored ingestion.completed ingestion.failed speech.started speech.segment speech.stopped
understanding.requested understanding.completed design.proposed design.repaired design.selected
review.completed review.invalid run.started run.stopped attempt.reserved attempt.dispatched
attempt.terminal tool.requested tool.terminal artifact.sealed artifact.missing handoff.delivered
handoff.acknowledged memory.read memory.written alternative.saved difference.observed
hypothesis.updated inquiry.frozen inquiry.evidence inquiry.declined lens.selected lens.composed
lens.abstained candidate.created candidate.frozen evaluation.started evaluation.result
loop.updated loop.stopped validation.completed approval.requested approval.decided
promotion.applied promotion.failed rollback.applied retention.changed retention.pruned
retention.deleted export.previewed export.created backup.created backup.verified
update.started update.failed recovery.reconciled security.denied record.gap
""".split()


def test_all_documented_event_types_are_registered_explicitly():
    assert set(REQUIRED_TYPES) <= EVENT_TYPES
    assert len(EVENT_TYPES) == len(set(EVENT_TYPES))
    for name in REQUIRED_TYPES:
        assert event_schema(name)["additionalProperties"] is False


@pytest.mark.parametrize("name", REQUIRED_TYPES)
@pytest.mark.parametrize("field", ["api_key", "filename", "url", "prompt", "reasoning", "raw_error",
                                     "private_evidence_ref", "label", "metadata", "reason"])
def test_every_event_rejects_freeform_or_private_metadata(name, field):
    with pytest.raises(DomainContractError):
        event_metadata(name, {field: "secret-canary-do-not-export"})


def test_wrong_event_or_extra_field_is_not_silently_dropped():
    with pytest.raises(DomainContractError):
        event_metadata("run.unknown", {})
    with pytest.raises(DomainContractError):
        event_metadata("work.created", {"token_count": 4})


@pytest.mark.parametrize("value", [True, -1, 1.5, "2", 2 ** 63])
def test_event_counts_are_strict_bounded_nonnegative_integers(value):
    with pytest.raises(DomainContractError):
        event_metadata("artifact.sealed", {"byte_count": value})


def test_per_event_schema_validates_enum_and_numeric_values():
    assert event_metadata("artifact.sealed", {"byte_count": 0}) == {"byte_count": 0}
    assert event_metadata("loop.stopped", {"reason_code": "plateau_reached", "round_count": 4}) == {
        "reason_code": "plateau_reached", "round_count": 4}
    with pytest.raises(DomainContractError):
        event_metadata("loop.stopped", {"reason_code": "model wrote a secret here"})
    with pytest.raises(DomainContractError):
        event_metadata("loop.stopped", {"reason_code": "passed"})


def test_loop_reason_and_evaluation_validity_use_growth_contract_terms():
    reasons = {"plateau_reached", "budget_exhausted", "below_floor_exhausted", "evidence_blocked",
               "safety_stop", "human_stop", "lineage_changed"}
    assert set(event_schema("loop.stopped")["properties"]["reason_code"]["enum"]) == reasons
    assert event_metadata("evaluation.result", {"validity": "pending"}) == {"validity": "pending"}
    with pytest.raises(DomainContractError):
        event_metadata("evaluation.result", {"validity": "not_checked"})


def test_schema_and_metadata_views_cannot_mutate_global_rules():
    schema = event_schema("loop.stopped")
    schema["properties"]["reason_code"]["enum"].append("injected")
    with pytest.raises(DomainContractError):
        event_metadata("loop.stopped", {"reason_code": "injected"})
    payload = {"byte_count": 2}
    view = event_metadata("artifact.sealed", payload)
    payload["byte_count"] = -1
    assert view == {"byte_count": 2}
