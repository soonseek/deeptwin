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
from uuid import uuid4

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
from app.services.promotion_approvals import (
    PersistentPromotionApprovals,
    PromotionApproval,
)
from app.services.validation import (
    freeze_candidate,
    is_frozen_candidate,
    is_validation_report,
    run_validation,
    validation_report_ref,
)
from app.tests.test_alternatives import ref
from app.tests.test_validation import (
    candidate_value,
    ledger_with_sealed,
    report_value,
)

CURRENT_ENV = ref("environment", 980)

# One real owner session per test module backs every promotion approval in
# these value-level suites: approvals are only ever issued by the persistent
# owner writer, never assembled by a test. Modules that use decision_value /
# record_approval import `promotion_owner` so the autouse fixture opens the
# session before their first test and closes it right after their last.
_approvals = None


@pytest.fixture(scope="module", autouse=True)
def promotion_owner(tmp_path_factory):
    global _approvals
    from app.tests.test_extension_candidates_persistent import owner

    with owner(tmp_path_factory.mktemp("promotion-owner")) as (
        app,
        _client,
        request,
        _p,
        _a,
    ):
        _approvals = (
            PersistentPromotionApprovals(
                app.state.domain_store, app.state.owner_authority
            ),
            request,
        )
        yield
    _approvals = None


def record_approval(
    candidate, decision="approve", expected_current_environment=CURRENT_ENV, report=None
):
    if _approvals is None:
        raise RuntimeError(
            "import promotion_owner from app.tests.test_promotion into this module"
        )
    service, request = _approvals
    if not is_validation_report(report):
        report = passed_report(candidate)
    return service.record(
        request,
        {
            "schema_version": "promotion-approval-command-v1",
            "command_id": str(uuid4()),
            "candidate_bundle": candidate.bundle_ref.as_dict(),
            "validation_report": validation_report_ref(report).as_dict(),
            "expected_current_environment": expected_current_environment,
            "decision": decision,
        },
    )


def frozen_candidate(**overrides):
    return freeze_candidate(candidate_value(**overrides))


def passed_report(candidate, dataset_id="sealed-a", **overrides):
    report, _ledger = run_validation(
        candidate,
        ledger_with_sealed(dataset_id),
        report_value(datasets=[dataset_id], **overrides),
    )
    return report


def decision_value(candidate, report, **overrides):
    expected = overrides.pop("expected_current_environment", CURRENT_ENV)
    decision = overrides.pop("decision", "approve")
    if "approval" not in overrides:
        subject = candidate if is_frozen_candidate(candidate) else frozen_candidate()
        overrides["approval"] = record_approval(subject, decision, expected, report)
    value = {
        "candidate": candidate,
        "validation_report": report,
        "scope": ref("decision_record", 981),
        "expected_current_environment": expected,
        "rollback_bundle": ref("backup_manifest", 983),
    }
    value.update(overrides)
    return value


def test_approval_is_an_authenticated_explicit_human_act():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    approval = record_approval(candidate)
    decision = record_promotion_decision(
        decision_value(candidate, report, approval=approval)
    )
    assert type(decision) is PromotionDecision
    assert decision.decision == "approve"
    assert decision.candidate_environment == candidate.bundle_ref
    # the decision carries the owner's recorded act, nothing caller-declared
    assert decision.approver_id == approval.actor_ref.id
    assert decision.approver_evidence == approval.approval_ref
    assert decision.decision_at == approval.decided_at_utc
    with pytest.raises(PromotionError):
        # a caller-declared approver is not evidence
        record_promotion_decision(
            decision_value(
                candidate,
                report,
                approval={
                    "actor_id": approval.actor_ref.id,
                    "authenticated": True,
                    "evidence": approval.approval_ref,
                },
            )
        )
    with pytest.raises(PromotionError):
        # silence is never a decision
        record_promotion_decision(decision_value(candidate, report, approval=None))
    forged = object.__new__(PromotionApproval)
    for name in PromotionApproval.__slots__:
        object.__setattr__(forged, name, getattr(approval, name))
    object.__setattr__(forged, "_issuer_token", object())
    with pytest.raises(PromotionError):
        record_promotion_decision(decision_value(candidate, report, approval=forged))
    with pytest.raises(PromotionError):
        # the decision object keeps no caller-declared decision or stamp
        record_promotion_decision(
            decision_value(candidate, report) | {"decision": "approve"}
        )
    with pytest.raises(PromotionError):
        record_promotion_decision(
            decision_value(candidate, report)
            | {"decision_at": "2026-09-13T03:14:15.926535Z"}
        )
    rejected = record_promotion_decision(
        decision_value(
            candidate,
            report,
            decision="reject",
        )
    )
    deferred = record_promotion_decision(
        decision_value(
            candidate,
            report,
            decision="defer",
        )
    )
    assert rejected.decision == "reject"
    assert deferred.decision == "defer"


def test_the_approval_must_be_bound_to_this_bundle_and_expected_environment():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    other = frozen_candidate(prompts=ref("artifact", 999))
    with pytest.raises(PromotionError):
        # an approval of another bundle never backs this one (exact hash)
        record_promotion_decision(
            decision_value(
                candidate,
                report,
                approval=record_approval(other),
            )
        )
    with pytest.raises(PromotionError):
        # an approval given against another current environment demands
        # re-approval, not reuse (G-13)
        record_promotion_decision(
            decision_value(
                candidate,
                report,
                approval=record_approval(candidate, "approve", ref("environment", 984)),
            )
        )
    with pytest.raises(PromotionError):
        # the human approved over the evidence they saw: an approval bound to
        # another validation report of the same bundle backs nothing
        record_promotion_decision(
            decision_value(
                candidate,
                report,
                approval=record_approval(
                    candidate, report=passed_report(candidate, "sealed-b")
                ),
            )
        )
    assert validation_report_ref(report) != validation_report_ref(
        passed_report(candidate, "sealed-b")
    )
    decision = record_promotion_decision(decision_value(candidate, report))
    assert decision.validation_report == validation_report_ref(report)


def test_only_an_approve_decision_can_activate():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    state = open_promotion_state(CURRENT_ENV)
    for outcome in ("reject", "defer"):
        decision = record_promotion_decision(
            decision_value(
                candidate,
                report,
                decision=outcome,
            )
        )
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
        record_promotion_decision(
            decision_value(
                candidate,
                passed_report(other),
            )
        )
    gates = report_value()["gates"]
    gates["regression"] = {
        "status": "fail",
        "reasons": ["회귀 실패"],
        "evidence": [ref("comparison_result", 960)],
    }
    failed, _ = run_validation(
        candidate,
        ledger_with_sealed("sealed-f"),
        report_value(gates=gates, datasets=["sealed-f"]),
    )
    with pytest.raises(PromotionError):
        record_promotion_decision(decision_value(candidate, failed))
    shadow, _ = run_validation(
        candidate,
        ledger_with_sealed("sealed-s"),
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
        open_promotion_state(CURRENT_ENV),
        approved,
        candidate,
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
