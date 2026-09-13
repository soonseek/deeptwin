"""US6 comparison contracts: frozen plans, paired rounds, honest validity.

A comparison plan freezes every condition before observation; results bind the
exact plan, pair baseline and candidate runs, and keep validity, work failure
and semantic irresolution distinct — a missing measurement is never converted
into a zero or a no-improvement score, and utility is an exact decimal that
exists only for valid rounds. Values are issued, never constructed.
"""

import dataclasses

import pytest

from app.services.comparisons import (
    ComparisonError,
    ComparisonPlan,
    ComparisonResult,
    freeze_comparison_plan,
    record_comparison_round,
)
from app.tests.test_alternatives import ref

LINEAGE = "00000000-0000-4000-8000-00000000f001"


def plan_value(**overrides):
    value = {
        "lineage_id": LINEAGE,
        "baseline_environment": ref("environment", 901),
        "queue": ref("run_manifest", 905),
        "quality_profile": ref("evaluation_profile", 906),
        "evaluator_bundle": ref("rubric", 907),
        "reset_manifest": ref("run_manifest", 908),
        "allowed_changes": ref("decision_record", 909),
        "tool_effect_policy": ref("observation_contract", 910),
        "budget": ref("budget_policy", 911),
        "mode": "automatic",
    }
    value.update(overrides)
    return value


def round_value(**overrides):
    value = {
        "round_index": 0,
        "candidate": ref("change_candidate", 920),
        "baseline_runs": [ref("run_manifest", 921), ref("run_manifest", 922)],
        "candidate_runs": [ref("run_manifest", 923), ref("run_manifest", 924)],
        "validity": "valid",
        "validity_reasons": [],
        "mandatory_checks": ref("validation_report", 925),
        "metric_vector": {"정확도": "0.82", "반려율": "0.10"},
        "utility": "0.36",
        "evidence": [ref("comparison_result", 926)],
        "usage": ref("decision_record", 927),
    }
    value.update(overrides)
    return value


def test_a_plan_freezes_every_condition():
    plan = freeze_comparison_plan(plan_value())
    assert type(plan) is ComparisonPlan
    assert plan.lineage_id == LINEAGE
    assert plan.mode == "automatic"
    assert plan.plan_ref.kind == "comparison_plan"
    human = freeze_comparison_plan(plan_value(mode="human_assisted"))
    assert human.mode == "human_assisted"
    with pytest.raises(ComparisonError):
        freeze_comparison_plan(plan_value(mode="adaptive"))
    with pytest.raises(ComparisonError):
        freeze_comparison_plan(plan_value(queue=ref("artifact", 999)))
    with pytest.raises(ComparisonError):
        freeze_comparison_plan({"unexpected": True})


def test_rounds_bind_the_exact_plan_and_pair_their_runs():
    plan = freeze_comparison_plan(plan_value())
    result = record_comparison_round(plan, round_value())
    assert type(result) is ComparisonResult
    assert result.plan_ref == plan.plan_ref
    assert result.round_index == 0
    assert len(result.baseline_runs) == len(result.candidate_runs) == 2
    with pytest.raises(ComparisonError):
        record_comparison_round(object(), round_value())
    with pytest.raises(ComparisonError):
        record_comparison_round(plan, round_value(
            candidate_runs=[ref("run_manifest", 923)],  # unpaired counts
        ))
    with pytest.raises(ComparisonError):
        record_comparison_round(plan, round_value(baseline_runs=[]))


def test_validity_work_failure_and_irresolution_stay_distinct():
    plan = freeze_comparison_plan(plan_value())
    invalid = record_comparison_round(plan, round_value(
        validity="invalid",
        validity_reasons=["평가기 장애로 판정이 불가능했다."],
        metric_vector=None,
        utility=None,
    ))
    assert invalid.validity == "invalid"
    assert invalid.utility is None
    with pytest.raises(ComparisonError):
        record_comparison_round(plan, round_value(
            validity="invalid", validity_reasons=[],  # invalid needs reasons
            metric_vector=None, utility=None,
        ))
    pending = record_comparison_round(plan, round_value(
        validity="pending", metric_vector=None, utility=None,
    ))
    assert pending.utility is None
    with pytest.raises(ComparisonError):
        # A missing measurement is never converted into a score.
        record_comparison_round(plan, round_value(
            validity="invalid",
            validity_reasons=["장애"],
            metric_vector=None,
            utility="0",
        ))
    # A valid round may honestly lack a utility; absence stays absence.
    unmeasured = record_comparison_round(plan, round_value(utility=None))
    assert unmeasured.validity == "valid"
    assert unmeasured.utility is None


def test_utility_is_an_exact_decimal_never_a_float():
    plan = freeze_comparison_plan(plan_value())
    result = record_comparison_round(plan, round_value(utility="0.30"))
    assert str(result.utility) == "0.30"
    for bad in (0.3, float("nan"), "NaN", "Infinity", "1e999", "abc"):
        with pytest.raises(ComparisonError):
            record_comparison_round(plan, round_value(utility=bad))


def test_values_are_issued_never_constructed():
    plan = freeze_comparison_plan(plan_value())
    result = record_comparison_round(plan, round_value())
    with pytest.raises(TypeError):
        dataclasses.replace(plan, mode="human_assisted")
    with pytest.raises(TypeError):
        dataclasses.replace(result, validity="valid")
    with pytest.raises(TypeError):
        ComparisonPlan(
            LINEAGE, plan.baseline_environment, plan.queue, plan.quality_profile,
            plan.evaluator_bundle, plan.reset_manifest, plan.allowed_changes,
            plan.tool_effect_policy, plan.budget, "automatic",
        )

    class FakePlan:
        plan_ref = plan.plan_ref

    with pytest.raises(ComparisonError):
        record_comparison_round(FakePlan(), round_value())


def test_metric_vectors_are_bounded_exact_decimal_maps():
    plan = freeze_comparison_plan(plan_value())
    with pytest.raises(ComparisonError):
        record_comparison_round(plan, round_value(
            metric_vector={"정확도": 0.82},  # float measurements are inexact
        ))
    with pytest.raises(ComparisonError):
        record_comparison_round(plan, round_value(
            metric_vector={"": "0.1"},
        ))
