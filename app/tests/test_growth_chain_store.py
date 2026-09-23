"""The durable US6 chain (T066 prerequisite): comparison plan → recorded rounds →
frozen candidate bundle → validation report, each persisted once with its exact
issue input and re-issued on resume through the same framework function. A payload
that does not read back byte-for-byte is refused; a report restores only over its
stored candidate and the stored rounds its gates cite, and its status must follow
from those gates again. Nothing is re-exposed: resume never consumes a dataset.
"""

import pytest

from app.domain.refs import EntityRef
from app.domain.schemas import ImmutableRecord
from app.services.comparisons import comparison_result_ref, freeze_comparison_plan
from app.services.growth_store import (
    RECORD_KIND,
    GrowthStoreError,
    persist_comparison_plan,
    persist_comparison_round,
    persist_frozen_candidate,
    persist_validation_report,
    resume_comparison_plan,
    resume_comparison_round,
    resume_frozen_candidate,
    resume_validation_report,
)
from app.services.validation import freeze_candidate, is_validation_report, run_validation
from app.tests.test_alternatives import ref
from app.tests.test_comparisons import plan_value
from app.tests.test_growth_store import headers, vault  # noqa: F401 - fixture
from app.tests.test_promotion import promotion_owner  # noqa: F401 - autouse owner session
from app.tests.test_validation import GATES, LINEAGE, candidate_value, ledger_with_sealed


def round_input(suffix):
    return {
        "round_id": f"round-{suffix}", "round_index": 0, "candidate": ref("change_candidate", 930),
        "baseline_runs": [ref("run_manifest", suffix)], "candidate_runs": [ref("run_manifest", suffix + 1000)],
        "validity": "valid", "validity_reasons": [], "mandatory_checks": ref("validation_report", 925),
        "metric_vector": {"utility": "1"}, "utility": "1", "evidence": [],
        "usage": ref("decision_record", 927),
    }


def chain(domain, roots):
    plan = freeze_comparison_plan(plan_value())
    plan_ref = persist_comparison_plan(domain, plan, **headers(roots))
    rounds = []
    for index in range(len(GATES)):
        value = round_input(960 + index)
        persist_comparison_round(domain, plan, value, plan_record_ref=plan_ref, **headers(roots))
        rounds.append(resume_comparison_round(domain, _result_ref(plan, value)))
    candidate = freeze_candidate(candidate_value())
    persist_frozen_candidate(domain, candidate, **headers(roots))
    report, _ledger = run_validation(candidate, ledger_with_sealed(), {
        "mode": "sealed_offline", "datasets": ["sealed-a"], "approved_scope": None,
        "gates": {name: {"status": "pass", "evidence": [rounds[index]], "reasons": []}
                  for index, name in enumerate(GATES)}})
    report_ref = persist_validation_report(domain, report, lineage_id=LINEAGE, **headers(roots))
    return plan, plan_ref, rounds, candidate, report, report_ref


def _result_ref(plan, value):
    from app.services.comparisons import record_comparison_round

    return comparison_result_ref(record_comparison_round(plan, value))


def test_the_chain_persists_once_and_resumes_exactly(vault):  # noqa: F811
    domain, roots = vault
    plan, plan_ref, rounds, candidate, report, report_ref = chain(domain, roots)
    assert resume_comparison_plan(domain, plan_ref).as_dict() == plan.as_dict()
    again = persist_comparison_plan(domain, plan, **headers(roots))
    assert again == plan_ref  # the same value persisted again is idempotent
    assert resume_frozen_candidate(domain, candidate.bundle_ref).as_dict() == candidate.as_dict()
    resumed_candidate, resumed = resume_validation_report(domain, report_ref)
    assert is_validation_report(resumed)
    assert resumed.as_dict() == report.as_dict()
    assert resumed_candidate.bundle_ref == candidate.bundle_ref
    assert resumed.status == "passed" and resumed.mode == "sealed_offline"


def test_a_round_or_candidate_never_persisted_is_not_found(vault):  # noqa: F811
    domain, roots = vault
    plan = freeze_comparison_plan(plan_value())
    with pytest.raises(GrowthStoreError, match="never persisted"):
        resume_comparison_round(domain, _result_ref(plan, round_input(999)))
    with pytest.raises(GrowthStoreError, match="never persisted"):
        resume_frozen_candidate(domain, freeze_candidate(candidate_value()).bundle_ref)


def test_a_round_needs_its_stored_plan(vault):  # noqa: F811
    domain, roots = vault
    plan = freeze_comparison_plan(plan_value())
    plan_ref = persist_comparison_plan(domain, plan, **headers(roots))
    other = freeze_comparison_plan(plan_value(mode="human_assisted"))
    with pytest.raises(GrowthStoreError, match="stored plan"):
        persist_comparison_round(domain, other, round_input(960), plan_record_ref=plan_ref, **headers(roots))


def test_a_report_whose_cited_round_is_missing_does_not_restore(vault):  # noqa: F811
    domain, roots = vault
    plan = freeze_comparison_plan(plan_value())
    persist_comparison_plan(domain, plan, **headers(roots))
    from app.services.comparisons import record_comparison_round

    unpersisted = [record_comparison_round(plan, round_input(960 + index)) for index in range(len(GATES))]
    candidate = freeze_candidate(candidate_value())
    persist_frozen_candidate(domain, candidate, **headers(roots))
    report, _ = run_validation(candidate, ledger_with_sealed(), {
        "mode": "sealed_offline", "datasets": ["sealed-a"], "approved_scope": None,
        "gates": {name: {"status": "pass", "evidence": [unpersisted[index]], "reasons": []}
                  for index, name in enumerate(GATES)}})
    report_ref = persist_validation_report(domain, report, lineage_id=LINEAGE, **headers(roots))
    with pytest.raises(GrowthStoreError, match="never persisted"):
        resume_validation_report(domain, report_ref)


def test_a_tampered_stored_plan_is_refused(vault):  # noqa: F811
    domain, roots = vault
    from app.services.design_persistence import encode_design_refs

    forged = dict(freeze_comparison_plan(plan_value()).as_dict(), mode="human_assisted", lineage_id="nope")
    record = ImmutableRecord.create(
        kind=RECORD_KIND, id="11111111-1111-4111-8111-111111111111", version=1,
        created_at_utc="2026-09-13T06:00:00.000000Z", actor_ref=roots.actor, parent_refs=(),
        purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"growth_kind": "growth_comparison_plan", "plan": encode_design_refs(forged)})
    domain.put(record)
    with pytest.raises(GrowthStoreError):
        resume_comparison_plan(domain, record.ref)
    assert EntityRef.from_dict(record.ref.as_dict()) == record.ref
