"""US2 selection pool and derived design versions (T036 first slice).

The selection pool presents at most three structurally different passed
candidates: a rejected verdict (a mandatory defect) never enters the pool
regardless of anything else, insufficient evidence is not a pass, an
unreviewed candidate is never selectable, and a structural duplicate of an
already-pooled candidate is excluded by its shape, not its name. When fewer
than three candidates qualify, the pool states the real count and every
exclusion's reason instead of padding (experience.md: 통과한 구조적으로 다른
기본 3안 / 0–2개면 실제 수·이유). Selecting, editing or merging creates a
NEW immutable design version bound to its parents with mandatory re-review —
scores and verdicts never inherit (FR-008).
"""

import dataclasses

import pytest

from app.services.design import accept_design_candidates
from app.services.design_criticism import CandidateVerdict
from app.services.design_review import (
    DesignReviewError,
    SelectionPool,
    assemble_selection_pool,
    derive_design_version,
)
from app.tests.test_design_generation import (
    candidate,
    graph_value,
    prepared,
)


def accepted(request, target, decision, *, suffix, reshape=False):
    graph = graph_value(
        target, decision.decision_ref.as_dict(), graph_suffix=200 + suffix,
    )
    if reshape:
        # a real structural change: the final artifact contract narrows,
        # which alters the projected shape (not merely a name)
        for contract in graph["artifact_contracts"]:
            if contract["artifact_contract_id"] == "final-script":
                contract["max_items"] = 1
                contract["media_types"] = ["text/markdown"]
    return accept_design_candidates(
        request, [candidate(request, graph, suffix=suffix)],
    )[0]


def verdict(item, status="passed", reasons=()):
    return CandidateVerdict(
        candidate_id=item.candidate_id,
        candidate_version=str(item.version),
        status=status,
        reasons=tuple(reasons),
    )


def pool_inputs():
    target, _lens, decision, request, _graph = prepared()
    two = accepted(request, target, decision, suffix=231)
    three = accepted(request, target, decision, suffix=232, reshape=True)
    duplicate = accepted(request, target, decision, suffix=233)
    return request, two, three, duplicate


def test_the_pool_presents_structurally_different_passed_candidates():
    _request, two, three, duplicate = pool_inputs()
    pool = assemble_selection_pool([
        (two, verdict(two)),
        (three, verdict(three)),
        (duplicate, verdict(duplicate)),  # same shape as `two`
    ])
    assert type(pool) is SelectionPool
    assert [item.candidate_id for item in pool.presented] == [
        two.candidate_id, three.candidate_id,
    ]
    assert pool.passed_count == 3  # honesty: three passed, one pooled out
    assert (duplicate.candidate_id, "structural_duplicate") in pool.excluded


def test_mandatory_defects_and_insufficiency_never_enter_the_pool():
    _request, two, three, _duplicate = pool_inputs()
    pool = assemble_selection_pool([
        (two, verdict(two, "rejected", ["review_fail:c1"])),
        (three, verdict(three, "insufficient_evidence",
                        ["validity_unresolved:x"])),
    ])
    assert pool.presented == ()
    assert pool.passed_count == 0
    reasons = dict(pool.excluded)
    assert reasons[two.candidate_id].startswith("rejected:")
    assert reasons[three.candidate_id].startswith("insufficient_evidence:")
    assert pool.supplementation_available is True  # fewer than three


def test_verdicts_must_bind_their_exact_candidate():
    _request, two, three, _duplicate = pool_inputs()
    with pytest.raises(DesignReviewError):
        assemble_selection_pool([(two, verdict(three))])  # cross-bound
    with pytest.raises(DesignReviewError):
        assemble_selection_pool([(object(), verdict(two))])
    with pytest.raises(DesignReviewError):
        assemble_selection_pool([(two, {"status": "passed"})])
    with pytest.raises(DesignReviewError):
        assemble_selection_pool([
            (two, verdict(two, "vibes_based")),  # unknown status
        ])
    with pytest.raises(DesignReviewError):
        # the same candidate can never appear twice in one pool input
        assemble_selection_pool([(two, verdict(two)), (two, verdict(two))])


def test_derived_versions_require_re_review_and_inherit_nothing():
    _request, two, three, _duplicate = pool_inputs()
    selected = derive_design_version("select", [two])
    assert selected.action == "select"
    assert selected.parent_refs == (two.graph_ref,)
    assert selected.re_review_required is True
    assert selected.inherited_verdict is None
    merged = derive_design_version("merge", [two, three])
    assert merged.parent_refs == (two.graph_ref, three.graph_ref)
    assert merged.re_review_required is True
    edited = derive_design_version(
        "edit", [two], instruction="research 역할의 출처 수집을 강화",
    )
    assert edited.instruction == "research 역할의 출처 수집을 강화"
    with pytest.raises(DesignReviewError):
        derive_design_version("merge", [two])  # a merge needs two parents
    with pytest.raises(DesignReviewError):
        derive_design_version("select", [two, three])  # a select takes one
    with pytest.raises(DesignReviewError):
        derive_design_version("regenerate", [two])  # not a derivation action
    with pytest.raises(DesignReviewError):
        derive_design_version("edit", [two])  # an edit states its instruction
    with pytest.raises(DesignReviewError):
        derive_design_version("select", [object()])
    with pytest.raises(TypeError):
        dataclasses.replace(selected, re_review_required=False)
