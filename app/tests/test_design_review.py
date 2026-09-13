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
from app.services.design_criticism import (
    _review_criteria,
    fold_candidate_criticism,
)
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


_REQUESTS = {}


def verdict(item, status="passed", _reasons=()):
    """Earn a real fold verdict for one candidate with the wanted status."""

    request = _REQUESTS[item.candidate_id]
    ids = [entry["id"] for entry in _review_criteria(request)["items"]]
    statuses = ["pass"] * len(ids)
    if status == "rejected":
        statuses[0] = "fail"
    elif status == "insufficient_evidence":
        statuses[0] = "unresolved"
    review = {
        "candidate_id": item.candidate_id,
        "candidate_version": str(item.version),
        "findings": [
            {"criterion_id": cid, "status": st}
            for cid, st in zip(ids, statuses)
        ],
    }
    return fold_candidate_criticism(item, request, review, [])


def pool_inputs(request_id_suffix=230):
    target, _lens, decision, request, _graph = prepared()
    if request_id_suffix != 230:
        from app.services.design import create_generation_request
        from app.tests.test_design_generation import design_authority

        request = create_generation_request(
            target,
            [decision],
            request_id=f"00000000-0000-4000-8000-{request_id_suffix:012d}",
            requested_candidate_count=3,
            compilation_authority=design_authority(),
        )
    two = accepted(request, target, decision, suffix=request_id_suffix + 1)
    three = accepted(
        request, target, decision, suffix=request_id_suffix + 2, reshape=True,
    )
    duplicate = accepted(request, target, decision, suffix=request_id_suffix + 3)
    for item in (two, three, duplicate):
        _REQUESTS[item.candidate_id] = request
    return request, two, three, duplicate


def test_the_pool_presents_structurally_different_passed_candidates():
    request, two, three, duplicate = pool_inputs()
    pool = assemble_selection_pool(request, [
        (two, verdict(two)),
        (three, verdict(three)),
        (duplicate, verdict(duplicate)),  # same shape as `two`
    ])
    assert type(pool) is SelectionPool
    assert {item.candidate_id for item in pool.presented} == {
        two.candidate_id, three.candidate_id,
    }
    assert pool.passed_count == 3  # honesty: three passed, one pooled out
    assert (duplicate.candidate_id, "structural_duplicate") in pool.excluded


def test_mandatory_defects_and_insufficiency_never_enter_the_pool():
    request, two, three, _duplicate = pool_inputs()
    pool = assemble_selection_pool(request, [
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
    request, two, three, _duplicate = pool_inputs()
    with pytest.raises(DesignReviewError):
        assemble_selection_pool(request, [(two, verdict(three))])
    with pytest.raises(DesignReviewError):
        assemble_selection_pool(request, [(object(), verdict(two))])
    with pytest.raises(DesignReviewError):
        assemble_selection_pool(request, [(two, {"status": "passed"})])
    with pytest.raises(DesignReviewError):
        # the same candidate can never appear twice in one pool input
        assemble_selection_pool(
            request, [(two, verdict(two)), (two, verdict(two))],
        )


def test_derived_versions_require_re_review_and_inherit_nothing():
    request, two, three, _duplicate = pool_inputs()
    selected = derive_design_version(request, "select", [two])
    assert selected.action == "select"
    assert selected.parent_refs == (two.graph_ref,)
    assert selected.re_review_required is True
    assert selected.inherited_verdict is None
    merged = derive_design_version(request, "merge", [two, three])
    assert merged.parent_refs == (two.graph_ref, three.graph_ref)
    assert merged.re_review_required is True
    edited = derive_design_version(
        request, "edit", [two], instruction="research 역할의 출처 수집을 강화",
    )
    assert edited.instruction == "research 역할의 출처 수집을 강화"
    with pytest.raises(DesignReviewError):
        derive_design_version(request, "merge", [two])
    with pytest.raises(DesignReviewError):
        derive_design_version(request, "select", [two, three])
    with pytest.raises(DesignReviewError):
        derive_design_version(request, "regenerate", [two])
    with pytest.raises(DesignReviewError):
        derive_design_version(request, "edit", [two])
    with pytest.raises(DesignReviewError):
        derive_design_version(request, "select", [object()])
    with pytest.raises(TypeError):
        dataclasses.replace(selected, re_review_required=False)
