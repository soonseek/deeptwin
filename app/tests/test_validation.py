"""US6 sealed validation: candidate freeze, dataset exposure, honest gates.

A frozen candidate fixes the full compatibility bundle — environment graph,
model bindings, prompts, knowledge rules, archetype I/O, tools/permissions,
lens versions, scope, evaluation/approval policy, dependencies, rollback —
under one bundle hash; any modification is a new candidate, never a mutation.
The dataset ledger separates tuning, sealed-validation and prospective data
(FR-025): a sealed dataset exposed to tuning or candidate authoring is burned
to development permanently, a dataset consumed by a validation run is seen
forever, and NOTHING relabels seen data unseen (G-12) — an unseen pass claim
requires genuinely unexposed sealed data. The report keeps the §8 categories
distinct (reconstruction, heldout transfer, boundary exclusion, regression,
leakage, side effects), a judge failure is invalid and never erases a real
failure, failed gates must state reasons, and shadow/limited modes never
claim sealed-offline coverage — limited application requires an exact
user-approved scope.
"""

import dataclasses

import pytest

from app.services.validation import (
    FrozenCandidate,
    GrowthValidationError,
    ValidationReport,
    expose_dataset,
    freeze_candidate,
    open_dataset_ledger,
    register_dataset,
    run_validation,
    unseen_dataset_ids,
)
from app.tests.test_alternatives import ref

LINEAGE = "00000000-0000-4000-8000-00000000f201"

GATES = (
    "reconstruction", "heldout_transfer", "boundary_exclusion",
    "regression", "leakage", "side_effects",
)


def candidate_value(**overrides):
    value = {
        "candidate": ref("change_candidate", 930),
        "environment_graph": ref("environment", 931),
        "model_bindings": ref("model_choice", 932),
        "prompts": ref("artifact", 933),
        "knowledge_rules": ref("decision_record", 934),
        "archetype_io": ref("observation_contract", 935),
        "tool_permissions": ref("grant", 936),
        "lens_versions": ref("lens_composition", 937),
        "scope": ref("decision_record", 938),
        "evaluation_policy": ref("evaluation_profile", 939),
        "approval_policy": ref("decision_record", 940),
        "dependencies": ref("run_manifest", 941),
        "rollback_bundle": ref("backup_manifest", 942),
    }
    value.update(overrides)
    return value


def ledger_with_sealed(dataset_id="sealed-a"):
    ledger = open_dataset_ledger(LINEAGE)
    return register_dataset(ledger, {
        "dataset_id": dataset_id,
        "classification": "sealed_validation",
        "manifest": ref("run_manifest", 950),
    })


def recorded_round(suffix=960, *, validity="valid", candidate=None):
    """A comparison round recorded by the framework (the evaluator execution a
    gate rests on), run for the candidate_value() change candidate by default."""

    from app.services.comparisons import freeze_comparison_plan, record_comparison_round
    from app.tests.test_comparisons import plan_value

    plan = freeze_comparison_plan(plan_value())
    return record_comparison_round(plan, {
        "round_id": f"round-{suffix}", "round_index": 0,
        "candidate": candidate or ref("change_candidate", 930),
        "baseline_runs": [ref("run_manifest", suffix)],
        "candidate_runs": [ref("run_manifest", suffix + 1000)],
        "validity": validity,
        "validity_reasons": [] if validity != "invalid" else ["평가 불가"],
        "mandatory_checks": ref("validation_report", 925),
        "metric_vector": {"utility": "1"} if validity == "valid" else None,
        "utility": "1" if validity == "valid" else None,
        "evidence": [], "usage": ref("decision_record", 927),
    })


def gate(status="pass", *, reasons=(), evidence_suffix=960):
    if status == "invalid" and not reasons:
        reasons = ("판정자 실패",)  # an invalid gate states why too
    value = {
        "status": status,
        "evidence": [recorded_round(evidence_suffix)],
        "reasons": list(reasons),
    }
    return value


def report_value(**overrides):
    value = {
        "mode": "sealed_offline",
        "datasets": ["sealed-a"],
        "gates": {name: gate(evidence_suffix=960 + i)
                  for i, name in enumerate(GATES)},
        "approved_scope": None,
    }
    value.update(overrides)
    return value


def test_a_candidate_freezes_the_whole_bundle_under_one_hash():
    frozen = freeze_candidate(candidate_value())
    assert type(frozen) is FrozenCandidate
    assert frozen.bundle_ref.kind == "environment"
    again = freeze_candidate(candidate_value())
    assert again.bundle_ref == frozen.bundle_ref
    modified = freeze_candidate(candidate_value(
        prompts=ref("artifact", 999),
    ))
    assert modified.bundle_ref != frozen.bundle_ref  # modification = new candidate
    with pytest.raises(GrowthValidationError):
        freeze_candidate(candidate_value(rollback_bundle=ref("artifact", 942)))
    with pytest.raises(GrowthValidationError):
        freeze_candidate({"unexpected": True})


def test_sealed_data_exposed_to_tuning_is_burned_forever():
    ledger = ledger_with_sealed()
    assert unseen_dataset_ids(ledger) == ("sealed-a",)
    burned = expose_dataset(ledger, "sealed-a", "tuning")
    assert unseen_dataset_ids(burned) == ()
    with pytest.raises(GrowthValidationError):
        # nothing relabels seen data unseen — there is no such API and
        # re-registering the same id is refused.
        register_dataset(burned, {
            "dataset_id": "sealed-a",
            "classification": "sealed_validation",
            "manifest": ref("run_manifest", 950),
        })


def test_validation_consumes_unseen_data_exactly_once():
    frozen = freeze_candidate(candidate_value())
    ledger = ledger_with_sealed()
    report, seen = run_validation(frozen, ledger, report_value())
    assert type(report) is ValidationReport
    assert report.status == "passed"
    assert report.candidate_bundle == frozen.bundle_ref
    assert unseen_dataset_ids(seen) == ()
    with pytest.raises(GrowthValidationError):
        # the same sealed data can never back a second unseen claim, even
        # for a modified (= new) candidate.
        run_validation(
            freeze_candidate(candidate_value(prompts=ref("artifact", 999))),
            seen, report_value(),
        )


def test_failed_gates_state_reasons_and_invalid_never_erases_failure():
    frozen = freeze_candidate(candidate_value())
    gates = report_value()["gates"]
    gates["regression"] = gate("fail", reasons=["기존 역할 회귀 3건"])
    gates["leakage"] = gate("invalid")  # judge failure
    report, _seen = run_validation(
        frozen, ledger_with_sealed(), report_value(gates=gates),
    )
    assert report.status == "failed"  # invalid never erases a real failure
    assert ("regression", ("기존 역할 회귀 3건",)) in [
        (name, outcome.reasons) for name, outcome in report.gates
    ]
    invalid_only = report_value()["gates"]
    invalid_only["leakage"] = gate("invalid")
    report2, _ = run_validation(
        freeze_candidate(candidate_value()),
        ledger_with_sealed("sealed-b"),
        report_value(gates=invalid_only, datasets=["sealed-b"]),
    )
    assert report2.status == "invalid"  # never converted into a pass
    with pytest.raises(GrowthValidationError):
        bad = report_value()["gates"]
        bad["regression"] = gate("fail")  # a failure must state reasons
        run_validation(
            freeze_candidate(candidate_value()),
            ledger_with_sealed("sealed-c"),
            report_value(gates=bad, datasets=["sealed-c"]),
        )


def test_the_gate_set_is_exact_and_never_partial():
    frozen = freeze_candidate(candidate_value())
    missing = report_value()["gates"]
    del missing["side_effects"]
    with pytest.raises(GrowthValidationError):
        run_validation(frozen, ledger_with_sealed(), report_value(gates=missing))
    extra = report_value()["gates"]
    extra["vibes"] = gate()
    with pytest.raises(GrowthValidationError):
        run_validation(frozen, ledger_with_sealed(), report_value(gates=extra))


def test_shadow_and_limited_modes_never_claim_sealed_coverage():
    frozen = freeze_candidate(candidate_value())
    ledger = open_dataset_ledger(LINEAGE)
    shadow, ledger = run_validation(frozen, ledger, report_value(
        mode="shadow", datasets=[],
    ))
    assert shadow.status == "passed"
    assert shadow.mode == "shadow"
    with pytest.raises(GrowthValidationError):
        # shadow observation never consumes sealed data as an unseen pass.
        run_validation(frozen, ledger_with_sealed(), report_value(mode="shadow"))
    with pytest.raises(GrowthValidationError):
        # limited application requires the exact user-approved scope.
        run_validation(frozen, ledger, report_value(
            mode="limited_application", datasets=[], approved_scope=None,
        ))
    limited, _ = run_validation(frozen, ledger, report_value(
        mode="limited_application", datasets=[],
        approved_scope=ref("decision_record", 970),
    ))
    assert limited.mode == "limited_application"


def test_values_are_issued_never_constructed():
    frozen = freeze_candidate(candidate_value())
    with pytest.raises(TypeError):
        dataclasses.replace(frozen, scope=ref("decision_record", 999))
    ledger = ledger_with_sealed()
    with pytest.raises(TypeError):
        dataclasses.replace(ledger, entries=())
    with pytest.raises(GrowthValidationError):
        run_validation(object(), ledger, report_value())
    with pytest.raises(GrowthValidationError):
        run_validation(frozen, object(), report_value())
    report, _ = run_validation(frozen, ledger, report_value())
    with pytest.raises(TypeError):
        dataclasses.replace(report, status="passed")


# --- T064: a gate rests on recorded evaluator executions, never a declaration ------


def test_a_pass_needs_the_recorded_evaluator_execution_behind_it():
    frozen = freeze_candidate(candidate_value())
    cases = {
        "evidence-free pass": {"status": "pass", "evidence": [], "reasons": []},
        "caller-declared ref": {"status": "pass", "evidence": [ref("comparison_result", 961)],
                                "reasons": []},
        "invalid round": {"status": "pass", "evidence": [recorded_round(962, validity="invalid")],
                          "reasons": []},
        "pending round": {"status": "pass", "evidence": [recorded_round(963, validity="pending")],
                          "reasons": []},
        "another candidate's round": {"status": "pass", "reasons": [], "evidence": [
            recorded_round(964, candidate=ref("change_candidate", 999))]},
        "unexplained invalid": {"status": "invalid", "evidence": [], "reasons": []},
    }
    for label, bad in cases.items():
        gates = report_value()["gates"]
        gates["heldout_transfer"] = bad
        with pytest.raises(GrowthValidationError):
            run_validation(frozen, ledger_with_sealed(), report_value(gates=gates))
        assert label  # every case above is refused


def test_the_report_names_the_exact_rounds_it_rests_on():
    from app.services.comparisons import comparison_result_ref

    frozen = freeze_candidate(candidate_value())
    gates = report_value()["gates"]
    backing = recorded_round(965)
    gates["regression"] = {"status": "pass", "evidence": [backing], "reasons": []}
    report, _seen = run_validation(frozen, ledger_with_sealed(), report_value(gates=gates))
    regression = dict(report.gates)["regression"]
    assert regression.evidence == (comparison_result_ref(backing),)
    # a failed gate may cite an invalid round, bound to the same candidate
    gates["regression"] = {"status": "fail", "reasons": ["회귀 2건"],
                           "evidence": [recorded_round(966, validity="invalid")]}
    failed, _ = run_validation(frozen, ledger_with_sealed(), report_value(gates=gates))
    assert failed.status == "failed"
