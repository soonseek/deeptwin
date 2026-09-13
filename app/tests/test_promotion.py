"""US6 promotion: authenticated exact-hash approval, activation CAS, rollback.

A promotion decision is a human's authenticated explicit act — silence, UI
refresh or a developer default never create an approve, and reject/defer are
first-class outcomes that can never activate. Activation is compare-and-swap:
the approved bundle hash must equal the applied bundle hash and the expected
current environment must still be current; a tampered bundle or a moved
current environment fails the conditional apply and demands re-approval
(G-13). Full activation requires a passed sealed-offline validation report
bound to the exact same bundle — shadow or limited reports never back it
(G-11). Validation, deployment and lifecycle are separate axes (FR-026):
rollback restores the previous compatible bundle while both versions stay in
history, and it never claims external real-world effects were undone.
"""

import dataclasses

import pytest

from app.domain.refs import EntityRef
from app.services.promotion import (
    PromotionDecision,
    PromotionError,
    PromotionState,
    activate_candidate,
    open_promotion_state,
    record_promotion_decision,
    rollback_environment,
)
from app.services.validation import freeze_candidate, run_validation
from app.tests.test_alternatives import ref
from app.tests.test_validation import (
    candidate_value,
    ledger_with_sealed,
    report_value,
)

APPROVER = "00000000-0000-4000-8000-00000000a001"
CURRENT_ENV = ref("environment", 980)


def frozen_candidate(**overrides):
    return freeze_candidate(candidate_value(**overrides))


def passed_report(candidate, dataset_id="sealed-a", **overrides):
    report, _ledger = run_validation(
        candidate, ledger_with_sealed(dataset_id),
        report_value(datasets=[dataset_id], **overrides),
    )
    return report


def decision_value(candidate, report, **overrides):
    value = {
        "candidate": candidate,
        "validation_report": report,
        "scope": ref("decision_record", 981),
        "approver": {
            "actor_id": APPROVER,
            "authenticated": True,
            "evidence": ref("action_approval", 982),
        },
        "decision": "approve",
        "decision_at": "2026-09-13T03:14:15.926535Z",
        "expected_current_environment": CURRENT_ENV,
        "rollback_bundle": ref("backup_manifest", 983),
    }
    value.update(overrides)
    return value


def test_approval_is_an_authenticated_explicit_human_act():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    decision = record_promotion_decision(decision_value(candidate, report))
    assert type(decision) is PromotionDecision
    assert decision.decision == "approve"
    assert decision.candidate_environment == candidate.bundle_ref
    with pytest.raises(PromotionError):
        record_promotion_decision(decision_value(
            candidate, report,
            approver={"actor_id": APPROVER, "authenticated": False,
                      "evidence": ref("action_approval", 982)},
        ))
    with pytest.raises(PromotionError):
        # silence is never a decision
        record_promotion_decision(decision_value(candidate, report,
                                                 decision=None))
    with pytest.raises(PromotionError):
        record_promotion_decision(decision_value(candidate, report,
                                                 decision="auto_approve"))
    rejected = record_promotion_decision(decision_value(
        candidate, report, decision="reject",
    ))
    deferred = record_promotion_decision(decision_value(
        candidate, report, decision="defer",
    ))
    assert rejected.decision == "reject"
    assert deferred.decision == "defer"


def test_only_an_approve_decision_can_activate():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    state = open_promotion_state(CURRENT_ENV)
    for outcome in ("reject", "defer"):
        decision = record_promotion_decision(decision_value(
            candidate, report, decision=outcome,
        ))
        with pytest.raises(PromotionError):
            activate_candidate(state, decision, candidate)
    approved = record_promotion_decision(decision_value(candidate, report))
    activated = activate_candidate(state, approved, candidate)
    assert type(activated) is PromotionState
    assert activated.current_environment == candidate.bundle_ref
    # the previous version is kept, never erased
    assert activated.history[-1][0] == EntityRef.from_dict(CURRENT_ENV)


def test_activation_is_compare_and_swap_on_the_current_environment():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    approved = record_promotion_decision(decision_value(candidate, report))
    moved = open_promotion_state(ref("environment", 984))  # env changed since
    with pytest.raises(PromotionError):
        activate_candidate(moved, approved, candidate)  # re-approval required
    state = open_promotion_state(CURRENT_ENV)
    activated = activate_candidate(state, approved, candidate)
    with pytest.raises(PromotionError):
        # the same approval can never apply twice: current moved to the
        # candidate itself.
        activate_candidate(activated, approved, candidate)


def test_the_approved_hash_must_equal_the_applied_hash():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    approved = record_promotion_decision(decision_value(candidate, report))
    tampered = frozen_candidate(prompts=ref("artifact", 999))
    state = open_promotion_state(CURRENT_ENV)
    with pytest.raises(PromotionError):
        activate_candidate(state, approved, tampered)  # G-13: no other version


def test_full_activation_requires_a_passed_sealed_report_on_the_same_bundle():
    candidate = frozen_candidate()
    other = frozen_candidate(prompts=ref("artifact", 999))
    with pytest.raises(PromotionError):
        # a report for a different bundle backs nothing
        record_promotion_decision(decision_value(
            candidate, passed_report(other),
        ))
    gates = report_value()["gates"]
    gates["regression"] = {
        "status": "fail", "reasons": ["회귀 실패"],
        "evidence": [ref("comparison_result", 960)],
    }
    failed, _ = run_validation(
        candidate, ledger_with_sealed("sealed-f"),
        report_value(gates=gates, datasets=["sealed-f"]),
    )
    with pytest.raises(PromotionError):
        record_promotion_decision(decision_value(candidate, failed))
    shadow, _ = run_validation(
        candidate, ledger_with_sealed("sealed-s"),
        report_value(mode="shadow", datasets=[]),
    )
    with pytest.raises(PromotionError):
        # G-11: observation-only evidence never backs operational promotion
        record_promotion_decision(decision_value(candidate, shadow))


def test_rollback_restores_the_bundle_and_never_claims_effect_reversal():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    approved = record_promotion_decision(decision_value(candidate, report))
    state = activate_candidate(
        open_promotion_state(CURRENT_ENV), approved, candidate,
    )
    rolled = rollback_environment(state, "회귀 발견")
    assert rolled.current_environment == EntityRef.from_dict(CURRENT_ENV)
    assert rolled.external_effects_reverted is False  # never claimed
    # both versions preserved: the restored one is current again, the
    # rolled-back bundle stays in history and can never silently return.
    assert (candidate.bundle_ref, "rolled_back") in rolled.history
    with pytest.raises(PromotionError):
        rollback_environment(open_promotion_state(CURRENT_ENV), "없음")
    with pytest.raises(PromotionError):
        rollback_environment(state, "")  # a rollback states its reason


def test_values_are_issued_never_constructed():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    decision = record_promotion_decision(decision_value(candidate, report))
    with pytest.raises(TypeError):
        dataclasses.replace(decision, decision="approve")
    state = open_promotion_state(CURRENT_ENV)
    with pytest.raises(TypeError):
        dataclasses.replace(state, current_environment=candidate.bundle_ref)
    with pytest.raises(PromotionError):
        activate_candidate(object(), decision, candidate)
    with pytest.raises(PromotionError):
        activate_candidate(state, object(), candidate)
    with pytest.raises(PromotionError):
        record_promotion_decision(decision_value(candidate, object()))
    with pytest.raises(PromotionError):
        record_promotion_decision(decision_value(object(), report))
