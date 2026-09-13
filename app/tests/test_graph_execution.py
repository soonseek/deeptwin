"""US3 scheduling patterns: sequential, parallel, router, join, loop,
retry, restart (T039; R02, with R07/R08's crash/cancel substrate already
covered by test_runtime_ledger).

These patterns compose the sealed-activation/join/visit primitives the way
a driver would: a successor runs only after its producer is terminal; a
router's unsealed branch can never report; a bounded loop makes NEW visits
(never retries); a retry stays inside one visit; and a restart that
replays the recorded evidence reconstructs the identical join decision —
late duplicates stay refused after the replay too.
"""

import pytest

from app.runtime.scheduling_state import (
    SchedulingError,
    apply_branch_result,
    apply_simultaneous_results,
    blocked_dependants,
    next_attempt,
    open_join,
    seal_activation,
    visit_identity,
)

RUN_ID = "00000000-0000-4000-8000-00000000d101"


def sealed(branches, *, mode="all_selected", min_success=None, loop_index=0):
    activation = seal_activation(
        run_id=RUN_ID,
        router_node_id="router-main",
        visit=visit_identity("router-main", loop_index=loop_index),
        branch_ids=list(branches),
    )
    return activation, open_join(
        activation, mode=mode, min_success=min_success,
    )


def result(branch, status, index, artifact=None):
    return {
        "branch_id": branch,
        "status": status,
        "observation_index": index,
        "artifact_ref": artifact,
    }


def test_sequential_chain_gates_each_successor_on_terminal_producers():
    # a sequential chain is a chain of single-branch all_selected joins:
    # the next stage's activation is sealed only after the previous stage
    # completed
    stages = ["research", "write", "review"]
    completed = []
    for stage in stages:
        _activation, join = sealed([f"{stage}-branch"])
        assert join.completed is False  # nothing runs ahead of its producer
        join = apply_branch_result(
            join, result(f"{stage}-branch", "succeeded", 1),
        )
        assert join.completed is True and join.satisfied is True
        completed.append(stage)
    assert completed == stages


def test_parallel_branches_progress_independently_within_the_seal():
    _activation, join = sealed(["b1", "b2", "b3"])
    join = apply_branch_result(join, result("b2", "succeeded", 1))
    assert join.completed is False  # others still in flight, none blocked
    join = apply_branch_result(join, result("b3", "failed", 2))
    join = apply_branch_result(join, result("b1", "succeeded", 3))
    assert join.completed is True
    assert join.satisfied is False  # a required failure is never hidden
    assert join.inputs == ("b1", "b2")


def test_a_router_activates_a_subset_and_outsiders_never_report():
    # the router chose 2 of 4 statically-possible branches; the sealed set
    # IS the decision
    activation, join = sealed(["path-a", "path-c"], mode="any_success")
    assert activation.branch_ids == ("path-a", "path-c")
    with pytest.raises(SchedulingError):
        apply_branch_result(join, result("path-b", "succeeded", 1))
    join = apply_branch_result(join, result("path-c", "succeeded", 1))
    assert join.winner == "path-c"
    blocked = blocked_dependants(
        activation, "path-a", {"path-a": ["delivery"], "path-c": []},
    )
    assert blocked == ("delivery",)


def test_a_bounded_loop_makes_new_visits_never_retries():
    seen_activations = set()
    for iteration in range(3):
        activation, join = sealed(
            ["loop-body"], loop_index=iteration,
        )
        assert activation.activation_id not in seen_activations
        seen_activations.add(activation.activation_id)
        join = apply_branch_result(join, result("loop-body", "succeeded", 1))
        assert join.completed is True
    # the loop's visits are three DIFFERENT identities
    visits = {
        visit_identity("loop-body", loop_index=i) for i in range(3)
    }
    assert len(visits) == 3
    with pytest.raises(SchedulingError):
        visit_identity("loop-body", loop_index=1_000_001)  # hard cap


def test_a_retry_stays_inside_one_visit():
    visit = visit_identity("write", loop_index=0)
    first = next_attempt(visit, previous_index=None)
    second = next_attempt(visit, previous_index=first.attempt_index)
    third = next_attempt(visit, previous_index=second.attempt_index)
    assert first.visit == second.visit == third.visit == visit
    assert (first.attempt_index, second.attempt_index,
            third.attempt_index) == (0, 1, 2)
    repeat_visit = visit_identity("write", loop_index=1)
    assert repeat_visit != visit  # a repeat visit is NOT attempt 3
    with pytest.raises(SchedulingError):
        next_attempt(visit, previous_index=1_001)  # retry budget cap


def test_a_restart_replays_evidence_to_the_identical_decision():
    _activation, join = sealed(
        ["b1", "b2", "b3"], mode="any_success",
    )
    join = apply_simultaneous_results(join, [
        result("b2", "succeeded", 4),
        result("b3", "succeeded", 4),
    ])
    join = apply_branch_result(join, result("b1", "failed", 5))
    # crash: rebuild from the recorded evidence in recorded order
    _activation2, rebuilt = sealed(
        ["b1", "b2", "b3"], mode="any_success",
    )
    for item in join.evidence:
        rebuilt = apply_branch_result(rebuilt, dict(item))
    assert rebuilt.winner == join.winner == "b2"  # frozen-order tie held
    assert rebuilt.inputs == join.inputs
    assert rebuilt.completed is True
    with pytest.raises(SchedulingError):
        # a late duplicate stays refused after the replay too
        apply_branch_result(rebuilt, result("b1", "succeeded", 9))


def test_collect_pattern_gathers_the_minimum_across_parallel_workers():
    _activation, join = sealed(
        ["w1", "w2", "w3", "w4"], mode="collect", min_success=2,
    )
    join = apply_branch_result(join, result("w4", "succeeded", 1))
    join = apply_branch_result(join, result("w2", "failed", 2))
    assert join.completed is False
    join = apply_branch_result(join, result("w1", "succeeded", 3))
    assert join.completed is True and join.satisfied is True
    assert join.inputs == ("w1", "w4")  # frozen order, not arrival order
    late = apply_branch_result(join, result("w3", "succeeded", 4))
    assert late.inputs == ("w1", "w4")  # sealed decision, evidence only
