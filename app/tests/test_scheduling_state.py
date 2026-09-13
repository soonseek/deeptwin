"""US3 sealed activation, atomic join winner and visit-vs-attempt identity.

The router seals its activation set for one run/loop visit BEFORE branches
dispatch; a join can never finish against an open set. Winner selection is
one compare-and-swap on a unique join-activation id: simultaneous successes
cannot schedule the successor twice, an observation-order tie breaks by the
frozen branch-id ordering, and losing results remain recorded evidence that
can never replace the sealed winner. Skipped branches are terminal skipped,
never phantom inputs. A required producer failure blocks exactly its
dependants — independent branches proceed. A repeat visit is a new visit,
not a retry; attempts retry one visit (runtime.md §2/§4; T041).
"""

import dataclasses

import pytest

from app.runtime.scheduling_state import (
    SchedulingError,
    apply_branch_result,
    blocked_dependants,
    next_attempt,
    open_join,
    seal_activation,
    visit_identity,
)

RUN_ID = "00000000-0000-4000-8000-00000000d001"


def sealed(branches=("b-alpha", "b-beta", "b-gamma"), mode="any_success"):
    activation = seal_activation(
        run_id=RUN_ID,
        router_node_id="router-1",
        visit=visit_identity("router-1", loop_index=0),
        branch_ids=list(branches),
    )
    return activation, open_join(activation, mode=mode)


def result(branch, status, *, observation_index, artifact=None):
    return {
        "branch_id": branch,
        "status": status,
        "observation_index": observation_index,
        "artifact_ref": artifact,
    }


def test_sealing_freezes_the_branch_set_before_dispatch():
    activation, join = sealed()
    assert activation.branch_ids == ("b-alpha", "b-beta", "b-gamma")
    with pytest.raises(SchedulingError):
        seal_activation(
            run_id=RUN_ID, router_node_id="router-1",
            visit=visit_identity("router-1", loop_index=0),
            branch_ids=[],  # an empty activation set is not a decision
        )
    with pytest.raises(SchedulingError):
        seal_activation(
            run_id=RUN_ID, router_node_id="router-1",
            visit=visit_identity("router-1", loop_index=0),
            branch_ids=["b-alpha", "b-alpha"],
        )
    with pytest.raises(SchedulingError):
        # a result from outside the sealed set never enters the join
        apply_branch_result(join, result("b-omega", "succeeded",
                                         observation_index=1))


def test_any_success_selects_exactly_one_winner_by_cas():
    _activation, join = sealed()
    join = apply_branch_result(join, result("b-beta", "succeeded",
                                            observation_index=1))
    assert join.winner == "b-beta"
    assert join.successor_scheduled is True
    # a later success is recorded evidence, never a second scheduling
    join = apply_branch_result(join, result("b-alpha", "succeeded",
                                            observation_index=2))
    assert join.winner == "b-beta"
    assert ("b-alpha", "succeeded") in [
        (item["branch_id"], item["status"]) for item in join.evidence
    ]


def test_an_observation_tie_breaks_by_frozen_branch_order():
    from app.runtime.scheduling_state import apply_simultaneous_results

    _activation, join = sealed()
    # simultaneous observations enter as ONE batch: the frozen branch
    # ordering decides before the single decision, and the successor is
    # scheduled exactly once
    join = apply_simultaneous_results(join, [
        result("b-gamma", "succeeded", observation_index=1),
        result("b-alpha", "succeeded", observation_index=1),
    ])
    assert join.winner == "b-alpha"
    assert join.successor_scheduled is True
    assert len([item for item in join.evidence
                if item["status"] == "succeeded"]) == 2


def test_all_selected_waits_for_every_sealed_branch():
    _activation, join = sealed(mode="all_selected")
    join = apply_branch_result(join, result("b-alpha", "succeeded",
                                            observation_index=1))
    assert join.completed is False
    join = apply_branch_result(join, result("b-beta", "succeeded",
                                            observation_index=2))
    assert join.completed is False
    join = apply_branch_result(join, result("b-gamma", "skipped",
                                            observation_index=3))
    # skipped is terminal, not a phantom input: the join completes but a
    # skipped branch contributes no input
    assert join.completed is True
    assert join.satisfied is True  # nothing failed
    assert join.inputs == ("b-alpha", "b-beta")


def test_a_required_failure_blocks_exactly_its_dependants():
    activation, join = sealed(mode="all_selected")
    join = apply_branch_result(join, result("b-alpha", "failed",
                                            observation_index=1))
    blocked = blocked_dependants(
        activation, "b-alpha",
        {"b-alpha": ["writer-node", "delivery-node"],
         "b-beta": ["review-node"]},
    )
    assert blocked == ("delivery-node", "writer-node")
    del join


def test_duplicate_and_late_results_never_mutate_a_terminal_join():
    _activation, join = sealed()
    join = apply_branch_result(join, result("b-alpha", "succeeded",
                                            observation_index=1))
    with pytest.raises(SchedulingError):
        # the same branch can never report twice
        apply_branch_result(join, result("b-alpha", "failed",
                                         observation_index=2))
    late = apply_branch_result(join, result("b-beta", "succeeded",
                                            observation_index=9))
    assert late.winner == "b-alpha"  # evidence only, winner sealed


def test_visits_and_attempts_are_distinct_identities():
    first = visit_identity("writer-node", loop_index=0)
    repeat = visit_identity("writer-node", loop_index=1)
    assert first != repeat  # a repeat visit is a new visit, not a retry
    attempt1 = next_attempt(first, previous_index=None)
    attempt2 = next_attempt(first, previous_index=attempt1.attempt_index)
    assert attempt1.visit == attempt2.visit == first
    assert attempt2.attempt_index == attempt1.attempt_index + 1
    with pytest.raises(SchedulingError):
        visit_identity("", loop_index=0)
    with pytest.raises(SchedulingError):
        next_attempt(first, previous_index=-2)
    with pytest.raises(TypeError):
        dataclasses.replace(attempt1, attempt_index=99)


def test_collect_completes_at_its_explicit_minimum():
    activation, join = sealed(mode="any_success")
    del activation
    from app.runtime.scheduling_state import open_join as _open

    _activation2, _ = sealed()
    collect = _open(_activation2, mode="collect", min_success=2)
    collect = apply_branch_result(collect, result("b-alpha", "succeeded",
                                                  observation_index=1))
    assert collect.completed is False
    collect = apply_branch_result(collect, result("b-gamma", "succeeded",
                                                  observation_index=2))
    assert collect.completed is True
    assert collect.inputs == ("b-alpha", "b-gamma")  # frozen order
    with pytest.raises(SchedulingError):
        _open(_activation2, mode="collect", min_success=0)
    with pytest.raises(SchedulingError):
        _open(_activation2, mode="all_selected", min_success=1)
    del join
