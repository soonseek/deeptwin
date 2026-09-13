"""Per-finding regression tests for the 2026-09-13 growth-contracts audit.

Each test reproduces one audited defect (F1-F10) and pins its fix. The common
remedy is the lenses.py defense the codebase already owned: init-disabled
issuance, provenance carried in the value, and evidence bound by content.
"""

import dataclasses

import pytest

from app.services.alternatives import (
    AlternativeContractError,
    OriginalExecution,
    OwnAlternative,
    SyntheticAlternative,
    accept_own_alternative,
    is_accepted_alternative,
)
from app.services.diagnosis import (
    DiagnosisError,
    Difference,
    Hypothesis,
    HypothesisSet,
    propose_hypotheses,
    record_difference,
)
from app.services.inquiry import (
    Inquiry,
    InquiryError,
    observe_evidence,
    open_inquiry,
)
from app.tests.test_alternatives import (
    original_value,
    ref,
    submission,
)
from app.tests.test_diagnosis import hypothesis, observation
from app.tests.test_inquiry import (
    AFTER,
    FROZEN_AT,
    investigation,
    opened,
    spli_decision,
)

# ------------------------------------------------------------------ F1


def test_synthetic_material_cannot_launder_into_diagnosis():
    original = OriginalExecution.from_untrusted(original_value())
    synthetic = accept_own_alternative(original, submission(synthetic=True))
    assert type(synthetic) is SyntheticAlternative
    assert synthetic.is_user_learning_evidence is False
    with pytest.raises(DiagnosisError):
        record_difference(
            synthetic.inner, [observation()], uncertainties=[],
        )


# ------------------------------------------------------------------ F2


def test_growth_value_types_are_not_forgeable():
    original = OriginalExecution.from_untrusted(original_value())
    accepted = accept_own_alternative(original, submission())
    assert is_accepted_alternative(accepted)

    with pytest.raises(TypeError):
        dataclasses.replace(accepted, alternative_artifact=accepted.original_artifact)
    with pytest.raises(TypeError):
        OwnAlternative(
            "00000000-0000-4000-8000-000000000901",
            "2026-09-13T10:00:00.000000Z",
            original, accepted.original_artifact, accepted.alternative_artifact,
            "whole", (), None,
        )
    with pytest.raises(TypeError):
        SyntheticAlternative(inner=accepted)

    difference = record_difference(accepted, [observation()], uncertainties=[])
    with pytest.raises(TypeError):
        dataclasses.replace(difference, unreviewed_scope="none")
    with pytest.raises(TypeError):
        Difference(
            accepted.original_artifact, accepted.alternative_artifact,
            (), (), ("whole",), "none", (),
        )
    proposed = propose_hypotheses(difference, [
        hypothesis("system"), hypothesis("expert_judgment"),
    ])
    with pytest.raises(TypeError):
        HypothesisSet(difference.difference_ref, proposed.hypotheses)
    with pytest.raises(TypeError):
        Hypothesis(
            "h-forged", "expert_judgment", "주장", (), (),
            "confirmed", (), (), (),
        )

    _accepted, inquiry = opened()
    with pytest.raises(TypeError):
        dataclasses.replace(inquiry, outcome=None)
    with pytest.raises(TypeError):
        Inquiry(
            inquiry.difference_ref, inquiry.confirmed_h_exp, inquiry.lens_refs,
            inquiry.questions, inquiry.opposing_predictions, inquiry.frozen_at,
            (),
        )

    class FakeSet:
        difference_ref = difference.difference_ref
        hypotheses = proposed.hypotheses

    with pytest.raises(InquiryError):
        open_inquiry(
            difference, FakeSet(), registry=object(), lens_decisions=[],
            questions=["질문"], opposing_predictions=[], frozen_at=FROZEN_AT,
        )


# ------------------------------------------------------------------ F3


def test_pre_freeze_records_and_renamed_versions_are_not_fresh_evidence():
    accepted, inquiry = opened()
    renamed = accepted.alternative_artifact.as_dict()
    renamed["version"] = 2  # same bytes, same id: the same content renamed
    with pytest.raises(InquiryError):
        observe_evidence(inquiry, [renamed], observed_at=AFTER)
    with pytest.raises(InquiryError):
        # The confirmation basis of the confirmed H_exp predates the freeze.
        observe_evidence(
            inquiry, [ref("comparison_result", 701)], observed_at=AFTER,
        )
    with pytest.raises(InquiryError):
        # The boundary's own outputs are pre-freeze records too.
        observe_evidence(inquiry, [ref("artifact", 305)], observed_at=AFTER)


# ------------------------------------------------------------------ F4


def test_excluded_or_abstained_lens_decisions_cannot_open_inquiries():
    from app.services.lenses import ApplicabilityAssessment

    accepted, difference, confirmed = investigation()
    registry, _good = spli_decision(accepted, difference)
    item = registry.get("L-P032-01")
    excluded_assessment = ApplicabilityAssessment.create(
        lens_ref=item.ref, status="not_applicable", evidence_hashes=("e" * 64,),
    )
    import app.tests.test_inquiry as inquiry_tests

    route = inquiry_tests.RouteEvidence.create(
        path="post_alternative_spli",
        scope_hash="5" * 64,
        authorized_source_hashes=("7" * 64,),
        original_hash=accepted.original_artifact.sha256,
        alternative_hash=accepted.alternative_artifact.sha256,
        alternative_scope="partial",
        observed_difference_hash=difference.difference_ref.sha256,
        h_exp_hash="b" * 64,
    )
    qualification = inquiry_tests.LensQualification.create(
        lens_ref=item.ref, path="post_alternative_spli", scope_hash="5" * 64,
        status="qualified", qualification_record_hash="d" * 64,
    )
    excluded = registry.decide(item.ref, route, excluded_assessment, qualification)
    assert excluded.state != "proposed"
    with pytest.raises(InquiryError):
        open_inquiry(
            difference, confirmed, registry=registry,
            lens_decisions=[excluded],
            questions=["질문"],
            opposing_predictions=[{
                "question_index": 0,
                "if_supported": "지지", "if_refuted": "반박",
            }],
            frozen_at=FROZEN_AT,
        )


# ------------------------------------------------------------------ F5


def test_the_boundarys_own_records_are_not_a_user_alternative():
    original = OriginalExecution.from_untrusted(original_value())
    for suffix in (305, 303):  # the second output and an input of the boundary
        with pytest.raises(AlternativeContractError):
            accept_own_alternative(
                original, submission(alternative_artifact=ref("artifact", suffix)),
            )


# ------------------------------------------------------------------ F6


def test_the_compared_artifacts_cannot_confirm_their_own_hypotheses():
    original = OriginalExecution.from_untrusted(original_value())
    accepted = accept_own_alternative(original, submission())
    difference = record_difference(accepted, [observation()], uncertainties=[])
    proposed = propose_hypotheses(difference, [
        hypothesis("expert_judgment"), hypothesis("system"),
    ])
    examined = proposed.resolve(
        proposed.hypotheses[1].hypothesis_id, "unresolved", basis_refs=[],
    )
    target = examined.hypotheses[0].hypothesis_id
    with pytest.raises(DiagnosisError):
        examined.resolve(
            target, "confirmed",
            basis_refs=[accepted.alternative_artifact.as_dict()],
        )
    with pytest.raises(DiagnosisError):
        examined.resolve(
            target, "confirmed",
            basis_refs=[accepted.original_artifact.as_dict()],
        )
    duplicated = ref("comparison_result", 611)
    with pytest.raises(DiagnosisError):
        examined.resolve(
            target, "confirmed", basis_refs=[duplicated, duplicated],
        )


# ------------------------------------------------------------------ F7


def test_lens_route_evidence_must_bind_the_actual_difference():
    accepted, difference, confirmed = investigation()
    registry, _good = spli_decision(accepted, difference)
    import app.tests.test_inquiry as inquiry_tests

    item = registry.get("L-P032-01")
    unbound_route = inquiry_tests.RouteEvidence.create(
        path="post_alternative_spli",
        scope_hash="5" * 64,
        authorized_source_hashes=("7" * 64,),
        original_hash="1" * 64,
        alternative_hash="2" * 64,
        alternative_scope="whole",
        observed_difference_hash="3" * 64,
        h_exp_hash="4" * 64,
    )
    assessment = inquiry_tests.ApplicabilityAssessment.create(
        lens_ref=item.ref, status="supported", evidence_hashes=("e" * 64,),
    )
    qualification = inquiry_tests.LensQualification.create(
        lens_ref=item.ref, path="post_alternative_spli", scope_hash="5" * 64,
        status="qualified", qualification_record_hash="d" * 64,
    )
    unbound = registry.decide(item.ref, unbound_route, assessment, qualification)
    with pytest.raises(InquiryError):
        open_inquiry(
            difference, confirmed, registry=registry,
            lens_decisions=[unbound],
            questions=["질문"],
            opposing_predictions=[{
                "question_index": 0,
                "if_supported": "지지", "if_refuted": "반박",
            }],
            frozen_at=FROZEN_AT,
        )


# ------------------------------------------------------------------ F8


def test_stamps_must_be_real_datetimes():
    with pytest.raises(InquiryError):
        opened(frozen_at="2026-13-99T99:99:99.999999Z")
    _accepted, inquiry = opened()
    with pytest.raises(InquiryError):
        observe_evidence(
            inquiry, [ref("artifact", 801)],
            observed_at="2026-09-13T25:00:00.000000Z",
        )
    original = OriginalExecution.from_untrusted(original_value())
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(
            original, submission(created_at="2026-13-99T10:00:00.000000Z"),
        )


# ------------------------------------------------------------------ F9


def test_locator_type_failures_are_module_typed():
    from app.services.alternatives import Selector
    from app.services.diagnosis import Observation

    with pytest.raises(AlternativeContractError):
        Selector.from_untrusted({
            "kind": "text_span", "locator": {"start": 1.5},
            "source_hash": "a" * 64, "alignment": "confirmed",
        })
    with pytest.raises(DiagnosisError):
        Observation.from_untrusted({
            "observation_id": "obs-x", "kind": "text_change",
            "locator": {"start": 1.5}, "description": "설명",
        })


# ------------------------------------------------------------------ F10


def test_a_single_causal_family_cannot_hide_behind_the_null():
    original = OriginalExecution.from_untrusted(original_value())
    accepted = accept_own_alternative(original, submission())
    difference = record_difference(accepted, [observation()], uncertainties=[])
    with pytest.raises(DiagnosisError):
        propose_hypotheses(difference, [
            hypothesis("no_generalization"), hypothesis("system"),
        ])
    # Two causal families plus the null remain legitimate.
    result = propose_hypotheses(difference, [
        hypothesis("system"), hypothesis("expert_judgment"),
        hypothesis("no_generalization"),
    ])
    assert len(result.hypotheses) == 3
