"""US5 diagnosis contracts: observations vs interpretation, competing hypotheses.

A Difference carries format-aware observations only — interpretation lives in
Hypothesis objects of the five contract families, which must compete: a batch
cannot be a lone causal family, and confirming one hypothesis while its
competitors are unexamined is the forbidden single-cause shortcut. Confirmation
needs real comparison/behavior evidence refs; a string diff alone (the
difference record itself) can never be the confirmation basis. Model confidence,
philosopher authority and human silence are not reference-shaped and therefore
can never enter a confirmation basis.
"""

import pytest

from app.services.alternatives import OriginalExecution, accept_own_alternative
from app.services.diagnosis import (
    DiagnosisError,
    Difference,
    HypothesisSet,
    propose_hypotheses,
    record_difference,
)
from app.tests.test_alternatives import original_value, ref, submission

STAMP = "2026-09-13T11:00:00.000000Z"


def alternative():
    original = OriginalExecution.from_untrusted(original_value())
    return accept_own_alternative(original, submission())


def observation(index=0, *, kind="text_change"):
    return {
        "observation_id": f"obs-{index}",
        "kind": kind,
        "locator": {"start": 120 + index, "end": 480},
        "description": "원본은 근거 링크가 없고 대안은 문단마다 출처를 단다.",
    }


def hypothesis(family, *, claim="검색 결과가 대본 작성 입력으로 전달되지 않았다."):
    return {
        "family": family,
        "claim": claim,
        "conditions": ["research 산출물이 비어 있던 실행"],
        "predictions": ["전달 경로를 복원하면 출처 표기가 재현된다."],
    }


def proposed_set(*families):
    accepted = alternative()
    difference = record_difference(
        accepted,
        [observation(index) for index in range(2)],
        uncertainties=["수신 확인 여부는 관측되지 않았다."],
    )
    return propose_hypotheses(
        difference, [hypothesis(family) for family in families],
    )


def test_difference_carries_observations_and_scopes_only():
    accepted = alternative()
    difference = record_difference(
        accepted, [observation()], uncertainties=["표기 규칙 합의는 미확인."],
    )
    assert type(difference) is Difference
    assert difference.original_artifact == accepted.original_artifact
    assert difference.alternative_artifact == accepted.alternative_artifact
    assert difference.evidence_scope == accepted.evidence_scope
    assert difference.unreviewed_scope == accepted.unreviewed_scope
    assert difference.observations[0].kind == "text_change"
    payload = difference.as_dict()
    # Observations are observable facts; no interpretation fields exist here.
    assert "hypotheses" not in payload
    assert "cause" not in payload


def test_hypotheses_must_compete_across_families():
    result = proposed_set("system", "expert_judgment")
    assert type(result) is HypothesisSet
    assert {item.family for item in result.hypotheses} == {
        "system", "expert_judgment",
    }
    assert all(item.status == "proposed" for item in result.hypotheses)

    with pytest.raises(DiagnosisError):
        proposed_set("system")  # a lone causal family is a single-cause shortcut
    with pytest.raises(DiagnosisError):
        proposed_set("unknown_family", "system")
    # The explicit null conclusion may stand alone.
    lone_null = proposed_set("no_generalization")
    assert len(lone_null.hypotheses) == 1


def test_confirmation_requires_examined_competitors():
    result = proposed_set("system", "exception")
    target = result.hypotheses[0].hypothesis_id
    with pytest.raises(DiagnosisError):
        result.resolve(
            target, "confirmed",
            basis_refs=[ref("comparison_result", 601)],
        )
    examined = result.resolve(
        result.hypotheses[1].hypothesis_id, "unresolved", basis_refs=[],
    )
    confirmed = examined.resolve(
        target, "confirmed", basis_refs=[ref("comparison_result", 601)],
    )
    states = {item.hypothesis_id: item.status for item in confirmed.hypotheses}
    assert states[target] == "confirmed"


def test_confirmation_needs_real_comparison_or_behavior_evidence():
    result = proposed_set("system", "alternative_error")
    examined = result.resolve(
        result.hypotheses[1].hypothesis_id, "refuted",
        basis_refs=[ref("comparison_result", 602)],
    )
    target = examined.hypotheses[0].hypothesis_id
    with pytest.raises(DiagnosisError):
        examined.resolve(target, "confirmed", basis_refs=[])  # no basis
    with pytest.raises(DiagnosisError):
        examined.resolve(
            target, "confirmed",
            basis_refs=[examined.difference_ref.as_dict()],  # string diff alone
        )
    confirmed = examined.resolve(
        target, "confirmed",
        basis_refs=[ref("comparison_result", 603), ref("artifact", 604)],
    )
    assert confirmed.hypotheses[0].status == "confirmed"
    assert len(confirmed.hypotheses[0].confirmation_basis) == 2


def test_refutation_records_counterevidence():
    result = proposed_set("system", "expert_judgment")
    target = result.hypotheses[0].hypothesis_id
    with pytest.raises(DiagnosisError):
        result.resolve(target, "refuted", basis_refs=[])
    refuted = result.resolve(
        target, "refuted", basis_refs=[ref("comparison_result", 605)],
    )
    assert refuted.hypotheses[0].status == "refuted"
    assert len(refuted.hypotheses[0].counterevidence) == 1


def test_shapes_and_transitions_are_strict():
    accepted = alternative()
    with pytest.raises(DiagnosisError):
        record_difference(accepted, [], uncertainties=[])  # no observations
    with pytest.raises(DiagnosisError):
        record_difference(object(), [observation()], uncertainties=[])
    result = proposed_set("system", "exception")
    with pytest.raises(DiagnosisError):
        result.resolve("missing-id", "unresolved", basis_refs=[])
    with pytest.raises(DiagnosisError):
        result.resolve(
            result.hypotheses[0].hypothesis_id, "nonsense", basis_refs=[],
        )
    resolved = result.resolve(
        result.hypotheses[0].hypothesis_id, "unresolved", basis_refs=[],
    )
    with pytest.raises(DiagnosisError):
        # A terminal-state hypothesis cannot silently flip back to proposed.
        resolved.resolve(
            resolved.hypotheses[0].hypothesis_id, "proposed", basis_refs=[],
        )
