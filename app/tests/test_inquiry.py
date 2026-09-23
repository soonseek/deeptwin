"""US5 inquiry contracts: frozen opposing predictions before fresh evidence.

An inquiry opens only over a recorded difference whose hypothesis set holds at
least one confirmed expert-judgment hypothesis, routed through registry-vouched
SPLI lens decisions. Questions and opposing predictions freeze first; evidence
observed at or before the freeze is rejected, the existing alternative can never
be renamed into new evidence, supported/refuted conclusions require actual fresh
evidence, and declining is a legitimate outcome without any.
"""

import pytest

from app.services.diagnosis import propose_hypotheses, record_difference
from app.services.inquiry import (
    Inquiry,
    InquiryError,
    conclude_inquiry,
    observe_evidence,
    open_inquiry,
)
from app.services.lenses import (
    ApplicabilityAssessment,
    LensQualification,
    RouteEvidence,
)
from app.tests.test_alternatives import ref
from app.tests.test_design_generation import proposed_lens
from app.tests.test_diagnosis import alternative, hypothesis, observation

FROZEN_AT = "2026-09-13T11:30:00.000000Z"
AFTER = "2026-09-13T11:45:00.000000Z"
BEFORE = "2026-09-13T11:15:00.000000Z"


def investigation():
    accepted = alternative()
    difference = record_difference(
        accepted, [observation()], uncertainties=["수신 확인 미관측."],
    )
    proposed = propose_hypotheses(difference, [
        hypothesis("expert_judgment"), hypothesis("system"),
    ])
    examined = proposed.resolve(
        proposed.hypotheses[1].hypothesis_id, "unresolved", basis_refs=[],
    )
    confirmed = examined.resolve(
        examined.hypotheses[0].hypothesis_id, "confirmed",
        basis_refs=[ref("comparison_result", 701)],
    )
    return accepted, difference, confirmed


def spli_decision(accepted, difference):
    registry, _initial = proposed_lens(_target(accepted))
    item = registry.get("L-P032-01")
    route = RouteEvidence.create(
        path="post_alternative_spli",
        scope_hash="5" * 64,
        authorized_source_hashes=("7" * 64,),
        original_hash=accepted.original_artifact.sha256,
        alternative_hash=accepted.alternative_artifact.sha256,
        alternative_scope="partial",
        observed_difference_hash=difference.difference_ref.sha256,
        h_exp_hash="b" * 64,
    )
    assessment = ApplicabilityAssessment.create(
        lens_ref=item.ref, status="supported", evidence_hashes=("e" * 64,),
    )
    qualification = LensQualification.create(
        lens_ref=item.ref,
        path="post_alternative_spli",
        scope_hash="5" * 64,
        status="qualified",
        qualification_record_hash="d" * 64,
    )
    return registry, registry.decide(item.ref, route, assessment, qualification)


def _target(accepted):
    # proposed_lens only reads work-model bindings from the confirmed target;
    # rebuild one from the shared design fixtures.
    from app.tests.test_design_generation import confirmed

    return confirmed()


def opened(**overrides):
    accepted, difference, confirmed = investigation()
    registry, decision = spli_decision(accepted, difference)
    arguments = {
        "registry": registry,
        "lens_decisions": [decision],
        "questions": ["출처 표기가 실제 수신자 신뢰에 영향을 주는가?"],
        "opposing_predictions": [{
            "question_index": 0,
            "if_supported": "출처가 있는 대본이 검수 반려율을 낮춘다.",
            "if_refuted": "반려율이 출처 유무와 무관하게 같다.",
        }],
        "frozen_at": FROZEN_AT,
    }
    arguments.update(overrides)
    return accepted, open_inquiry(difference, confirmed, **arguments)


def test_inquiry_opens_with_frozen_questions_and_predictions():
    _accepted, inquiry = opened()
    assert type(inquiry) is Inquiry
    assert inquiry.frozen_at == FROZEN_AT
    assert inquiry.outcome is None
    assert inquiry.new_evidence == ()
    assert len(inquiry.confirmed_h_exp) == 1
    payload = inquiry.as_dict()
    assert payload["questions"] == [
        "출처 표기가 실제 수신자 신뢰에 영향을 주는가?",
    ]


def test_opening_requires_confirmed_expert_judgment_and_vouched_spli():
    accepted, difference, _confirmed = investigation()
    unexamined = propose_hypotheses(difference, [
        hypothesis("expert_judgment"), hypothesis("system"),
    ])
    registry, decision = spli_decision(accepted, difference)
    base = {
        "registry": registry,
        "lens_decisions": [decision],
        "questions": ["질문"],
        "opposing_predictions": [{
            "question_index": 0,
            "if_supported": "지지 예측", "if_refuted": "반박 예측",
        }],
        "frozen_at": FROZEN_AT,
    }
    with pytest.raises(InquiryError):
        open_inquiry(difference, unexamined, **base)  # no confirmed H_exp
    with pytest.raises(InquiryError):
        opened(lens_decisions=[object()])
    other_registry, _other = spli_decision(accepted, difference)
    with pytest.raises(InquiryError):
        # A decision vouched by a different registry instance is foreign.
        opened(registry=other_registry)


def test_predictions_must_oppose():
    with pytest.raises(InquiryError):
        opened(opposing_predictions=[{
            "question_index": 0,
            "if_supported": "같은 문장", "if_refuted": "같은 문장",
        }])
    with pytest.raises(InquiryError):
        opened(opposing_predictions=[])
    with pytest.raises(InquiryError):
        opened(opposing_predictions=[{
            "question_index": 5,
            "if_supported": "지지", "if_refuted": "반박",
        }])


def test_evidence_must_be_fresh_and_after_the_freeze():
    accepted, inquiry = opened()
    with pytest.raises(InquiryError):
        observe_evidence(
            inquiry, [ref("artifact", 801)], observed_at=BEFORE,
        )
    with pytest.raises(InquiryError):
        observe_evidence(
            inquiry, [ref("artifact", 801)], observed_at=FROZEN_AT,
        )
    with pytest.raises(InquiryError):
        # The existing alternative can never be renamed into new evidence.
        observe_evidence(
            inquiry,
            [accepted.alternative_artifact.as_dict()],
            observed_at=AFTER,
        )
    observed = observe_evidence(
        inquiry, [ref("artifact", 801)], observed_at=AFTER,
    )
    assert len(observed.new_evidence) == 1


def test_conclusions_require_evidence_except_decline_and_unresolved():
    _accepted, inquiry = opened()
    with pytest.raises(InquiryError):
        conclude_inquiry(inquiry, "supported")
    with pytest.raises(InquiryError):
        conclude_inquiry(inquiry, "refuted")
    declined = conclude_inquiry(inquiry, "declined")
    assert declined.outcome == "declined"
    with pytest.raises(InquiryError):
        observe_evidence(
            declined, [ref("artifact", 802)], observed_at=AFTER,
        )
    with pytest.raises(InquiryError):
        conclude_inquiry(declined, "supported")

    _accepted, fresh = opened()
    observed = observe_evidence(
        fresh, [ref("comparison_result", 803)], observed_at=AFTER,
    )
    supported = conclude_inquiry(observed, "supported")
    assert supported.outcome == "supported"


def test_shapes_are_strict():
    accepted, difference, confirmed = investigation()
    registry, decision = spli_decision(accepted, difference)
    with pytest.raises(InquiryError):
        open_inquiry(object(), confirmed, registry=registry,
                     lens_decisions=[decision], questions=["질문"],
                     opposing_predictions=[{
                         "question_index": 0,
                         "if_supported": "지지", "if_refuted": "반박",
                     }],
                     frozen_at=FROZEN_AT)
    with pytest.raises(InquiryError):
        opened(frozen_at="not-a-stamp")
    with pytest.raises(InquiryError):
        opened(questions=[])


# --- SPLI routing from the qualified lens cards and the H_exp revision (T056) -------


def test_routed_questions_are_the_qualified_cards_own_words():
    from app.services.inquiry import open_routed_inquiry, spli_questions

    accepted, difference, confirmed = investigation()
    registry, decision = spli_decision(accepted, difference)
    card = registry.get("L-P032-01")
    questions, predictions = spli_questions(registry, [decision, decision])
    assert questions == [card.distinguishing_question]  # one card, one question
    assert predictions == [{"question_index": 0, "if_supported": card.expected_contrast,
                            "if_refuted": card.disconfirmation}]
    inquiry = open_routed_inquiry(difference, confirmed, registry=registry,
                                  lens_decisions=[decision], frozen_at=FROZEN_AT)
    assert inquiry.questions == (card.distinguishing_question,)
    assert inquiry.opposing_predictions[0].if_refuted == card.disconfirmation
    assert inquiry.lens_refs == (str(card.ref),)


def test_routing_refuses_what_the_registry_does_not_vouch_for():
    from app.services.inquiry import spli_questions

    accepted, difference, _confirmed = investigation()
    registry, decision = spli_decision(accepted, difference)
    other, _ = spli_decision(accepted, difference)
    for bad in ([object()], [], "x"):
        with pytest.raises(InquiryError):
            spli_questions(registry, bad)
    with pytest.raises(InquiryError):
        spli_questions(other, [decision])  # vouched by another registry instance
    with pytest.raises(InquiryError):
        spli_questions(object(), [decision])


@pytest.mark.parametrize(("outcome", "status", "keeps_evidence"), [
    ("supported", "supported_by_fresh_evidence", True),
    ("refuted", "refuted_by_fresh_evidence", True),
    ("unresolved", "unchanged", False),
    ("declined", "unchanged", False),
])
def test_a_concluded_inquiry_revises_the_expert_judgment(outcome, status, keeps_evidence):
    from app.services.inquiry import is_issued_revision, revise_expert_judgment

    accepted, difference, confirmed = investigation()
    registry, decision = spli_decision(accepted, difference)
    inquiry = open_inquiry(difference, confirmed, registry=registry, lens_decisions=[decision],
                           questions=["질문"], opposing_predictions=[{
                               "question_index": 0, "if_supported": "가", "if_refuted": "나"}],
                           frozen_at=FROZEN_AT)
    observed = observe_evidence(inquiry, [ref("comparison_result", 702)], observed_at=AFTER)
    concluded = conclude_inquiry(observed, outcome)
    revision = revise_expert_judgment(confirmed, concluded)
    assert is_issued_revision(revision)
    assert revision.status == status and revision.h_exp_ids == concluded.confirmed_h_exp
    assert bool(revision.evidence) is keeps_evidence
    assert revision.as_dict()["frozen_at"] == FROZEN_AT


def test_only_a_concluded_inquiry_over_its_own_set_revises():
    from app.services.inquiry import revise_expert_judgment

    accepted, _difference, confirmed = investigation()
    _accepted, open_one = opened()
    with pytest.raises(InquiryError, match="concluded"):
        revise_expert_judgment(confirmed, open_one)
    concluded = conclude_inquiry(open_one, "declined")
    # a set over another difference (other observations) is not this inquiry's
    other_difference = record_difference(accepted, [observation(7)], uncertainties=[])
    other_set = propose_hypotheses(other_difference, [hypothesis("expert_judgment"),
                                                      hypothesis("system")])
    with pytest.raises(InquiryError, match="belong"):
        revise_expert_judgment(other_set, concluded)
    with pytest.raises(InquiryError):
        revise_expert_judgment(confirmed, object())
