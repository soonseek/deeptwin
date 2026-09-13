"""US4 own-alternative contracts: exact original binding, G-01/G-02 guards.

An own alternative is a user-made artifact bound to one preserved original
execution boundary. Initial work descriptions, revision instructions, review
approvals, comments and empty drafts are never promoted into alternatives
(G-01); partial selectors bind the exact original artifact version and keep
formal selection separate from semantic impact (G-02): partial evidence never
shrinks the impact scope, and unreviewed area is stated, never claimed.
"""

import pytest

from app.domain.refs import EntityRef
from app.services.alternatives import (
    AlternativeContractError,
    NonAlternativeSubmission,
    OriginalExecution,
    OwnAlternative,
    SyntheticAlternative,
    accept_own_alternative,
)

STAMP = "2026-09-13T10:00:00.000000Z"


def ref(kind, suffix, *, sha=None):
    return {
        "kind": kind,
        "id": f"00000000-0000-4000-8000-{suffix:012d}",
        "version": 1,
        "sha256": sha or format(suffix, "x").rjust(64, "0"),
    }


def original_value():
    return {
        "boundary_id": "writer-final-script",
        "work_revision_ref": ref("work_revision", 301),
        "environment_ref": ref("environment", 302),
        "input_refs": [ref("artifact", 303)],
        "output_refs": [ref("artifact", 304), ref("artifact", 305)],
        "handoff_refs": [ref("handoff", 306)],
        "tool_refs": [ref("tool_definition", 307)],
        "model_binding_refs": [ref("model_choice", 308)],
        "observation_gaps": ["수신자 열람 여부는 관측되지 않았다."],
    }


def selector(*, kind="text_span", alignment="confirmed", source=304):
    return {
        "kind": kind,
        "locator": {"start": 120, "end": 480},
        "source_hash": ref("artifact", source)["sha256"],
        "alignment": alignment,
    }


def submission(**overrides):
    value = {
        "author_id": "00000000-0000-4000-8000-000000000901",
        "created_at": STAMP,
        "submission_kind": "user_artifact",
        "original_artifact": ref("artifact", 304),
        "alternative_artifact": ref("artifact", 401),
        "coverage": "partial",
        "selectors": [selector()],
        "optional_explanation": None,
        "synthetic": False,
    }
    value.update(overrides)
    return value


@pytest.fixture
def original():
    return OriginalExecution.from_untrusted(original_value())


def test_partial_alternative_binds_the_exact_original_version(original):
    accepted = accept_own_alternative(original, submission())
    assert type(accepted) is OwnAlternative
    assert accepted.coverage == "partial"
    assert accepted.original_artifact == EntityRef.from_dict(ref("artifact", 304))
    assert accepted.selectors[0].source_hash == ref("artifact", 304)["sha256"]
    assert accepted.evidence_scope == ("selector:text_span:0",)
    assert accepted.unreviewed_scope.startswith("outside_selectors:")
    # G-02: partial evidence never narrows the semantic impact scope.
    assert accepted.impact_scope == "pending_investigation"
    assert accepted.as_dict()["coverage"] == "partial"
    assert accepted.alternative_ref.kind == "own_alternative"


def test_whole_alternative_needs_no_selectors_and_states_no_unreviewed_area(original):
    accepted = accept_own_alternative(
        original, submission(coverage="whole", selectors=[]),
    )
    assert accepted.coverage == "whole"
    assert accepted.evidence_scope == ("whole",)
    assert accepted.unreviewed_scope == "none"
    assert accepted.impact_scope == "pending_investigation"


def test_non_alternative_submissions_keep_their_kind(original):
    for kind in (
        "work_description", "revision_instruction", "review_approval", "comment",
    ):
        with pytest.raises(NonAlternativeSubmission) as failure:
            accept_own_alternative(original, submission(submission_kind=kind))
        assert failure.value.submission_kind == kind


def test_an_empty_draft_is_not_an_alternative(original):
    with pytest.raises(NonAlternativeSubmission) as failure:
        accept_own_alternative(
            original, submission(alternative_artifact=None),
        )
    assert failure.value.submission_kind == "empty_draft"


def test_synthetic_material_is_a_separate_type_never_learning_evidence(original):
    result = accept_own_alternative(original, submission(synthetic=True))
    assert type(result) is SyntheticAlternative
    assert type(result) is not OwnAlternative
    assert result.is_user_learning_evidence is False


def test_selector_and_original_bindings_are_exact(original):
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(
            original,
            submission(original_artifact=ref("artifact", 999)),  # not an output
        )
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(
            original,
            submission(selectors=[selector(source=305)]),  # wrong original version
        )
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(
            original, submission(coverage="whole"),  # whole cannot carry selectors
        )
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(
            original, submission(selectors=[]),  # partial requires selectors
        )
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(
            original, submission(selectors=[selector(kind="whole")]),
        )
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(
            original,
            submission(
                alternative_artifact=ref("artifact", 304),  # same as original
            ),
        )


def test_unconfirmed_alignment_is_preserved_not_upgraded(original):
    accepted = accept_own_alternative(
        original, submission(selectors=[selector(alignment="proposed")]),
    )
    assert accepted.selectors[0].alignment == "proposed"
    assert accepted.fully_aligned is False
    confirmed = accept_own_alternative(original, submission())
    assert confirmed.fully_aligned is True


def test_shapes_are_strict_and_deterministic(original):
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(original, {"unexpected": True})
    with pytest.raises(AlternativeContractError):
        accept_own_alternative(object(), submission())
    with pytest.raises(AlternativeContractError):
        OriginalExecution.from_untrusted({"missing": "fields"})
    first = accept_own_alternative(original, submission())
    second = accept_own_alternative(original, submission())
    assert first.as_dict() == second.as_dict()
    assert first.alternative_ref == second.alternative_ref
