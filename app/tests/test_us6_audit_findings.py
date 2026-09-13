"""Regression tests for the US6 batch adversarial audit findings.

Each test reproduces one confirmed finding from the independent audit of
compiler/comparisons/growth/validation/promotion and pins its fix:
F1 double rollback must never re-promote without a fresh approval;
F2 a consumed approval is never valid again, rollback included;
F3 a burned manifest cannot be laundered under a new dataset id;
F4 replayed reports from one ledger state are detectably conflicting;
F5 a quality profile requires a strictly positive min_delta and a
non-negative floor; F8 a forged (never-issued) inquiry never compiles;
F9 content-addressed refs get content-derived ids — two different bundles
or plans never share (kind, id, version); F10 a run cannot be paired with
itself; F11 comparison rounds carry their idempotency id; F12 round
outcomes have exact shapes, a validity enum, and no scores on non-valid
rounds; F14 forbidden verbatim spans are also blocked in scope fields;
F15 candidate provenance must match observed evidence including version;
F16 decision timestamps are canonical (exactly six fractional digits);
F17 malformed dataset lists fail with the domain error; F18 a human can
record an explicit reject/defer of a candidate whose validation failed.
"""

import pytest

from app.runtime.compiler import ChangeCompilerError, compile_change_candidate
from app.services.comparisons import (
    ComparisonError,
    freeze_comparison_plan,
    record_comparison_round,
)
from app.services.growth import GrowthLoopError, freeze_quality_profile
from app.services.inquiry import Inquiry
from app.services.promotion import (
    PromotionError,
    activate_candidate,
    open_promotion_state,
    record_promotion_decision,
    rollback_environment,
)
from app.services.validation import (
    GrowthValidationError,
    expose_dataset,
    register_dataset,
    run_validation,
)
from app.tests.test_alternatives import ref
from app.tests.test_change_compiler import patch_value, supported_inquiry
from app.tests.test_comparisons import plan_value, round_value
from app.tests.test_promotion import (
    CURRENT_ENV,
    decision_value,
    frozen_candidate,
    passed_report,
)
from app.tests.test_validation import ledger_with_sealed, report_value


def test_f1_double_rollback_never_repromotes_without_a_fresh_approval():
    candidate = frozen_candidate()
    approved = record_promotion_decision(
        decision_value(candidate, passed_report(candidate)),
    )
    state = activate_candidate(
        open_promotion_state(CURRENT_ENV), approved, candidate,
    )
    rolled = rollback_environment(state, "회귀 발견")
    assert rolled.current_environment != candidate.bundle_ref
    with pytest.raises(PromotionError):
        rollback_environment(rolled, "한 번 더")  # nothing restorable
    lifecycles = [entry[1] for entry in rolled.history]
    assert lifecycles.count("active") == 0  # history never claims two actives
    assert (candidate.bundle_ref, "rolled_back") in rolled.history


def test_f2_a_consumed_approval_is_never_valid_again():
    candidate = frozen_candidate()
    approved = record_promotion_decision(
        decision_value(candidate, passed_report(candidate)),
    )
    state = activate_candidate(
        open_promotion_state(CURRENT_ENV), approved, candidate,
    )
    rolled = rollback_environment(state, "회귀 발견")
    assert rolled.current_environment.as_dict()["id"] == CURRENT_ENV["id"]
    with pytest.raises(PromotionError):
        # current == expected again, but the approval was consumed.
        activate_candidate(rolled, approved, candidate)


def test_f3_a_burned_manifest_cannot_return_under_a_new_name():
    ledger = ledger_with_sealed("sealed-a")
    burned = expose_dataset(ledger, "sealed-a", "tuning")
    with pytest.raises(GrowthValidationError):
        register_dataset(burned, {
            "dataset_id": "sealed-a-take2",
            "classification": "sealed_validation",
            "manifest": ref("run_manifest", 950),  # the same manifest
        })


def test_f4_replayed_reports_from_one_ledger_state_are_detectable():
    candidate = frozen_candidate()
    ledger = ledger_with_sealed("sealed-a")
    first, after = run_validation(candidate, ledger, report_value())
    second, _ = run_validation(candidate, ledger, report_value())
    # The immutable-value replay cannot be prevented here, but it must be
    # detectable: both reports name the identical pre-consumption revision.
    assert first.ledger_revision == second.ledger_revision
    assert first.as_dict()["ledger_revision"] == first.ledger_revision
    third_ledger = expose_dataset(
        register_dataset(after, {
            "dataset_id": "sealed-b",
            "classification": "sealed_validation",
            "manifest": ref("run_manifest", 951),
        }),
        "sealed-b", "validation",
    )
    assert third_ledger.revision > after.revision > ledger.revision


def test_f5_a_profile_requires_positive_min_delta_and_sane_floor():
    def profile(**overrides):
        value = {
            "profile_id": "p", "version": 1, "quality_floor": "0.80",
            "min_delta": "0.02", "patience": 3,
        }
        value.update(overrides)
        return value

    for bad_delta in ("0", "-0.50", "-0"):
        with pytest.raises(GrowthLoopError):
            freeze_quality_profile(profile(min_delta=bad_delta))
    with pytest.raises(GrowthLoopError):
        freeze_quality_profile(profile(quality_floor="-1"))
    assert freeze_quality_profile(profile()).min_delta > 0


def test_f8_a_forged_inquiry_never_compiles_a_candidate():
    _accepted, real = supported_inquiry()
    forged = object.__new__(Inquiry)
    for name in Inquiry.__slots__:
        object.__setattr__(forged, name, getattr(real, name))
    object.__setattr__(forged, "_issuer_token", None)
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(forged, patch_value())


def test_f9_different_contents_never_share_kind_id_version():
    one = frozen_candidate()
    two = frozen_candidate(prompts=ref("artifact", 999))
    assert (one.bundle_ref.id, one.bundle_ref.version) != (
        two.bundle_ref.id, two.bundle_ref.version,
    ) or one.bundle_ref.sha256 == two.bundle_ref.sha256
    assert one.bundle_ref.id != two.bundle_ref.id
    auto = freeze_comparison_plan(plan_value())
    human = freeze_comparison_plan(plan_value(mode="human_assisted"))
    assert auto.plan_ref.id != human.plan_ref.id


def test_f10_a_run_is_never_paired_with_itself():
    plan = freeze_comparison_plan(plan_value())
    shared = ref("run_manifest", 921)
    with pytest.raises(ComparisonError):
        record_comparison_round(plan, round_value(
            baseline_runs=[shared], candidate_runs=[shared],
        ))


def test_f11_comparison_rounds_carry_their_idempotency_id():
    plan = freeze_comparison_plan(plan_value())
    result = record_comparison_round(plan, round_value())
    assert result.round_id == "round-0"
    assert result.as_dict()["round_id"] == "round-0"
    with pytest.raises(ComparisonError):
        record_comparison_round(plan, round_value(round_id=""))
    value = round_value()
    del value["round_id"]
    with pytest.raises(ComparisonError):
        record_comparison_round(plan, value)


def test_f12_round_outcomes_have_exact_shapes_and_honest_validity():
    from app.services.growth import apply_round, start_growth_loop
    from app.tests.test_growth_loop import LINEAGE, profile, valid

    state = start_growth_loop(LINEAGE, profile())
    with pytest.raises(GrowthLoopError):
        apply_round(state, {**valid(0, "0.80"), "surprise": True})
    with pytest.raises(GrowthLoopError):
        apply_round(state, {**valid(0, "0.80"), "validity": "banana"})
    with pytest.raises(GrowthLoopError):
        # a non-valid round never carries a score that is silently dropped
        apply_round(state, {
            **valid(0, "0.99"), "validity": "invalid",
        })


def test_f14_forbidden_spans_are_blocked_in_scope_fields_too():
    _accepted, inquiry = supported_inquiry()
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(
            inquiry,
            patch_value(change_scope="사용자 대안 원문 그대로"),
            forbidden_spans=["사용자 대안 원문 그대로"],
        )
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(
            inquiry,
            patch_value(predicted_impact_scope="대안  원문"),
            forbidden_spans=["대안 원문"],  # whitespace-normalized
        )


def test_f15_provenance_must_match_observed_evidence_including_version():
    _accepted, inquiry = supported_inquiry()
    _stamp, observed = inquiry.new_evidence[0]
    wrong_version = {
        "kind": observed.kind,
        "id": observed.id,
        "version": observed.version + 76,
        "sha256": observed.sha256,
    }
    value = patch_value()
    value["condition"] = {
        "text": value["condition"]["text"],
        "evidence_refs": [wrong_version],
    }
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, value)


def test_f16_decision_stamps_are_canonical_six_digit_utc():
    candidate = frozen_candidate()
    report = passed_report(candidate)
    for bad in (
        "2026-09-13T03:14:15.9Z",       # 1-digit fraction
        "2026-09-13T03:14:15Z",         # no fraction
        "2026-09-13 03:14:15.926535Z",  # no T
    ):
        with pytest.raises(PromotionError):
            record_promotion_decision(
                decision_value(candidate, report, decision_at=bad),
            )


def test_f17_malformed_dataset_lists_fail_with_the_domain_error():
    candidate = frozen_candidate()
    with pytest.raises(GrowthValidationError):
        run_validation(
            candidate, ledger_with_sealed(),
            report_value(datasets=[["boom"]]),
        )


def test_f18_a_human_reject_of_a_failed_candidate_is_recordable():
    candidate = frozen_candidate()
    gates = report_value()["gates"]
    gates["regression"] = {
        "status": "fail", "reasons": ["회귀 실패"],
        "evidence": [ref("comparison_result", 960)],
    }
    failed, _ = run_validation(
        candidate, ledger_with_sealed("sealed-x"),
        report_value(gates=gates, datasets=["sealed-x"]),
    )
    rejected = record_promotion_decision(
        decision_value(candidate, failed, decision="reject"),
    )
    assert rejected.decision == "reject"
    deferred = record_promotion_decision(
        decision_value(candidate, failed, decision="defer"),
    )
    assert deferred.decision == "defer"
    with pytest.raises(PromotionError):
        # an approve still requires the passed sealed-offline report
        record_promotion_decision(decision_value(candidate, failed))
