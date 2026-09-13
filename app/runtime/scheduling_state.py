"""Sealed activation, atomic join winner, visit-vs-attempt identity (T041).

The router seals its activation set for one run/loop visit before any branch
dispatches; a join can never finish against an open set, and a result from
outside the sealed set never enters it. Winner selection for ``any_success``
is one compare-and-swap decision on the unique join activation: the first
observed success wins, an earlier observation arriving late re-points the
same single decision, an observation-order tie breaks by the frozen
branch-id ordering, and the successor is scheduled exactly once — losing
results remain recorded evidence that can never replace the sealed winner.
``all_selected`` waits for every sealed branch; ``collect`` completes at its
explicit minimum. Skipped branches are terminal ``skipped`` and contribute
no input. A required producer failure blocks exactly its dependants. A
repeat visit is a new visit, never a retry; attempts retry one visit
(runtime.md §2/§4). Values are issued, never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

TERMINAL_STATUSES = frozenset({
    "succeeded", "failed", "cancelled", "skipped", "timed_out",
})
JOIN_MODES = frozenset({"any_success", "all_selected", "collect"})
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_ISSUE_TOKEN = object()


class SchedulingError(ValueError):
    """A sealing, join application or identity request is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _identifier(value, label, maximum=128):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise SchedulingError(f"{label} is out of bounds")
    return value


@dataclass(frozen=True, slots=True, init=False)
class NodeVisit:
    """One logical visit of one node; a repeat visit is a new visit."""

    node_id: str
    loop_index: int


def visit_identity(node_id, *, loop_index) -> NodeVisit:
    _identifier(node_id, "node id")
    if type(loop_index) is not int or not 0 <= loop_index <= 1_000_000:
        raise SchedulingError("loop index is out of bounds")
    return _issue(NodeVisit, node_id=node_id, loop_index=loop_index)


@dataclass(frozen=True, slots=True, init=False)
class Attempt:
    """One retry of one exact visit."""

    visit: NodeVisit
    attempt_index: int


def next_attempt(visit, *, previous_index) -> Attempt:
    if type(visit) is not NodeVisit:
        raise SchedulingError("an exact node visit is required")
    if previous_index is None:
        index = 0
    elif type(previous_index) is int and 0 <= previous_index <= 1_000:
        index = previous_index + 1
    else:
        raise SchedulingError("the previous attempt index is out of bounds")
    return _issue(Attempt, visit=visit, attempt_index=index)


@dataclass(frozen=True, slots=True, init=False)
class SealedActivation:
    """One router decision's frozen branch set for one exact visit."""

    activation_id: str
    run_id: str
    router_node_id: str
    visit: NodeVisit
    branch_ids: tuple[str, ...]
    _issuer_token: object = field(repr=False, compare=False)


def seal_activation(*, run_id, router_node_id, visit, branch_ids) -> SealedActivation:
    """Freeze the activation set before any branch dispatches."""

    if type(run_id) is not str or _UUID.fullmatch(run_id) is None:
        raise SchedulingError("run id is not a canonical UUID")
    _identifier(router_node_id, "router node id")
    if type(visit) is not NodeVisit:
        raise SchedulingError("an exact node visit is required")
    if type(branch_ids) is not list or not 1 <= len(branch_ids) <= 64:
        raise SchedulingError("an activation seals a bounded nonempty set")
    branches = tuple(_identifier(item, "branch id") for item in branch_ids)
    if len(set(branches)) != len(branches):
        raise SchedulingError("a branch can never activate twice in one seal")
    activation_id = str(uuid5(
        NAMESPACE_URL,
        "deeptwin:activation:"
        f"{run_id}:{router_node_id}:{visit.node_id}:{visit.loop_index}:"
        + ",".join(branches),
    ))
    return _issue(
        SealedActivation,
        activation_id=activation_id,
        run_id=run_id,
        router_node_id=router_node_id,
        visit=visit,
        branch_ids=branches,
        _issuer_token=_ISSUE_TOKEN,
    )


@dataclass(frozen=True, slots=True, init=False)
class JoinState:
    """One join over one sealed activation; evolution only by application."""

    activation: SealedActivation
    mode: str
    min_success: int | None
    reported: tuple[str, ...]
    evidence: tuple[dict, ...]
    winner: str | None
    winner_observation: int | None
    successor_scheduled: bool
    completed: bool
    inputs: tuple[str, ...]
    _issuer_token: object = field(repr=False, compare=False)


def open_join(activation, *, mode, min_success=None) -> JoinState:
    if (
        type(activation) is not SealedActivation
        or getattr(activation, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise SchedulingError("a sealed activation is required")
    if mode not in JOIN_MODES:
        raise SchedulingError("unknown join mode")
    if mode == "collect":
        if (
            type(min_success) is not int
            or not 1 <= min_success <= len(activation.branch_ids)
        ):
            raise SchedulingError(
                "collect requires an explicit reachable minimum"
            )
    elif min_success is not None:
        raise SchedulingError("only collect carries a minimum")
    return _issue(
        JoinState,
        activation=activation,
        mode=mode,
        min_success=min_success,
        reported=(),
        evidence=(),
        winner=None,
        winner_observation=None,
        successor_scheduled=False,
        completed=False,
        inputs=(),
        _issuer_token=_ISSUE_TOKEN,
    )


def _frozen_index(activation: SealedActivation, branch_id: str) -> int:
    return activation.branch_ids.index(branch_id)


def apply_branch_result(join, value) -> JoinState:
    """Apply one terminal branch result; the sealed decision never doubles."""

    if (
        type(join) is not JoinState
        or getattr(join, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise SchedulingError("a framework-issued join state is required")
    if type(value) is not dict or set(value) != {
        "branch_id", "status", "observation_index", "artifact_ref",
    }:
        raise SchedulingError("expected the exact branch result object")
    branch_id = value["branch_id"]
    if branch_id not in join.activation.branch_ids:
        # The set was sealed before dispatch; outsiders never enter.
        raise SchedulingError("the branch is outside the sealed activation")
    if branch_id in join.reported:
        raise SchedulingError("a branch can never report twice")
    status = value["status"]
    if status not in TERMINAL_STATUSES:
        raise SchedulingError("unknown terminal branch status")
    observation = value["observation_index"]
    if type(observation) is not int or not 0 <= observation <= 1_000_000:
        raise SchedulingError("the observation index is out of bounds")

    reported = (*join.reported, branch_id)
    evidence = (*join.evidence, dict(value))
    winner = join.winner
    winner_observation = join.winner_observation
    successor_scheduled = join.successor_scheduled
    completed = join.completed
    inputs = join.inputs

    if join.mode == "any_success":
        if status == "succeeded":
            if winner is None:
                winner = branch_id
                winner_observation = observation
                successor_scheduled = True  # the single CAS decision
                completed = True
                inputs = (branch_id,)
            elif observation < winner_observation or (
                observation == winner_observation
                and _frozen_index(join.activation, branch_id)
                < _frozen_index(join.activation, winner)
            ):
                # The same single decision re-points: observation order (or
                # the frozen tie-break) says this branch was first. The
                # successor was scheduled exactly once either way.
                winner = branch_id
                winner_observation = observation
                inputs = (branch_id,)
            # a later success is recorded evidence only
    else:
        successes = [
            item["branch_id"] for item in evidence
            if item["status"] == "succeeded"
        ]
        ordered = tuple(sorted(
            successes, key=lambda item: _frozen_index(join.activation, item),
        ))
        if join.mode == "all_selected":
            if len(reported) == len(join.activation.branch_ids):
                completed = True
                inputs = ordered
        else:  # collect
            if (
                len(ordered) >= join.min_success
                or len(reported) == len(join.activation.branch_ids)
            ):
                completed = True
                inputs = ordered

    return _issue(
        JoinState,
        activation=join.activation,
        mode=join.mode,
        min_success=join.min_success,
        reported=reported,
        evidence=evidence,
        winner=winner,
        winner_observation=winner_observation,
        successor_scheduled=successor_scheduled,
        completed=completed,
        inputs=inputs,
        _issuer_token=_ISSUE_TOKEN,
    )


def blocked_dependants(activation, failed_branch, dependants_map) -> tuple[str, ...]:
    """A required failure blocks exactly its dependants, nothing else."""

    if (
        type(activation) is not SealedActivation
        or getattr(activation, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise SchedulingError("a sealed activation is required")
    if failed_branch not in activation.branch_ids:
        raise SchedulingError("the branch is outside the sealed activation")
    if type(dependants_map) is not dict:
        raise SchedulingError("expected the dependants map")
    dependants = dependants_map.get(failed_branch, [])
    if type(dependants) is not list or any(
        type(item) is not str for item in dependants
    ):
        raise SchedulingError("dependants are malformed")
    return tuple(sorted(set(dependants)))


__all__ = [
    "JOIN_MODES",
    "TERMINAL_STATUSES",
    "Attempt",
    "JoinState",
    "NodeVisit",
    "SchedulingError",
    "SealedActivation",
    "apply_branch_result",
    "blocked_dependants",
    "next_attempt",
    "open_join",
    "seal_activation",
    "visit_identity",
]
