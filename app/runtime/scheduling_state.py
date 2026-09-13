"""Sealed activation, atomic join winner, visit-vs-attempt identity (T041).

The router seals its activation set for one run/loop visit before any branch
dispatches; a join can never finish against an open set, and a result from
outside the sealed set never enters it. Winner selection for ``any_success``
is one compare-and-swap decision on the unique join activation: the first
APPLIED success wins and nothing re-points it afterwards — simultaneous
observations are ingested through ``apply_simultaneous_results``, which
realizes the frozen branch-order tie-break BEFORE the decision, and every
later result is recorded evidence that can never replace the sealed winner
or the successor's already-consumed inputs.
``all_selected`` waits for every sealed branch; ``collect`` completes at its
explicit minimum. Skipped branches are terminal ``skipped`` and contribute
no input. A required producer failure blocks exactly its dependants. A
repeat visit is a new visit, never a retry; attempts retry one visit
(runtime.md §2/§4). Values are issued, never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef, canonical_json

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
    _issuer_token: object = field(repr=False, compare=False)


def _require_visit(visit) -> None:
    if (
        type(visit) is not NodeVisit
        or getattr(visit, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise SchedulingError("a framework-issued node visit is required")


def visit_identity(node_id, *, loop_index) -> NodeVisit:
    _identifier(node_id, "node id")
    if type(loop_index) is not int or not 0 <= loop_index <= 1_000_000:
        raise SchedulingError("loop index is out of bounds")
    return _issue(
        NodeVisit, node_id=node_id, loop_index=loop_index,
        _issuer_token=_ISSUE_TOKEN,
    )


@dataclass(frozen=True, slots=True, init=False)
class Attempt:
    """One retry of one exact visit."""

    visit: NodeVisit
    attempt_index: int
    _issuer_token: object = field(repr=False, compare=False)


def next_attempt(visit, *, previous_index) -> Attempt:
    _require_visit(visit)
    if previous_index is None:
        index = 0
    elif type(previous_index) is int and 0 <= previous_index <= 1_000:
        index = previous_index + 1
    else:
        raise SchedulingError("the previous attempt index is out of bounds")
    return _issue(
        Attempt, visit=visit, attempt_index=index,
        _issuer_token=_ISSUE_TOKEN,
    )


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
    _require_visit(visit)
    if type(branch_ids) is not list or not 1 <= len(branch_ids) <= 64:
        raise SchedulingError("an activation seals a bounded nonempty set")
    branches = tuple(_identifier(item, "branch id") for item in branch_ids)
    if len(set(branches)) != len(branches):
        raise SchedulingError("a branch can never activate twice in one seal")
    # Delimiter-proof identity: the components are canonically encoded
    # before hashing, so no id text can smear one seal into another.
    digest = sha256(canonical_json({
        "run_id": run_id,
        "router_node_id": router_node_id,
        "node_id": visit.node_id,
        "loop_index": visit.loop_index,
        "branch_ids": list(branches),
    })).hexdigest()
    activation_id = str(uuid5(
        NAMESPACE_URL, f"deeptwin:activation:{digest}",
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
    # True only when the mode's own success condition was actually met at
    # completion; a collect below its minimum completes unsatisfied.
    satisfied: bool
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
        satisfied=False,
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
    artifact = value["artifact_ref"]
    if artifact is not None:
        try:
            artifact = EntityRef.from_dict(artifact).as_dict()
        except (DomainContractError, TypeError) as exc:
            raise SchedulingError(
                "a branch result artifact must be an exact ref or None"
            ) from exc

    reported = (*join.reported, branch_id)
    # Recorded evidence is detached from the caller's object entirely.
    evidence = (*join.evidence, {
        "branch_id": branch_id,
        "status": status,
        "observation_index": observation,
        "artifact_ref": artifact,
    })
    winner = join.winner
    winner_observation = join.winner_observation
    successor_scheduled = join.successor_scheduled
    completed = join.completed
    satisfied = join.satisfied
    inputs = join.inputs

    if completed:
        # The decision is sealed: everything after completion is recorded
        # evidence only — the winner and the successor's inputs never move.
        pass
    elif join.mode == "any_success":
        if status == "succeeded":
            # The single CAS decision: the first APPLIED success wins and
            # nothing — not an earlier observation index, not a tie —
            # re-points it afterwards. Simultaneous observations must be
            # ingested through apply_simultaneous_results, which realizes
            # the frozen-order tie-break BEFORE this decision.
            winner = branch_id
            winner_observation = observation
            successor_scheduled = True
            completed = True
            satisfied = True
            inputs = (branch_id,)
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
                satisfied = all(
                    item["status"] in ("succeeded", "skipped")
                    for item in evidence
                )
        else:  # collect
            if len(ordered) >= join.min_success:
                completed = True
                satisfied = True
                inputs = ordered
            elif len(reported) == len(join.activation.branch_ids):
                # Exhausted below the minimum: completed but explicitly
                # UNSATISFIED, never silently short.
                completed = True
                satisfied = False
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
        satisfied=satisfied,
        inputs=inputs,
        _issuer_token=_ISSUE_TOKEN,
    )


def apply_simultaneous_results(join, values) -> JoinState:
    """Ingest one batch of simultaneous observations; ties break by the
    frozen branch order BEFORE the single decision is taken."""

    if (
        type(join) is not JoinState
        or getattr(join, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise SchedulingError("a framework-issued join state is required")
    if type(values) is not list or not 1 <= len(values) <= 64:
        raise SchedulingError("expected a bounded batch of branch results")
    def order(value):
        if type(value) is not dict or "branch_id" not in value:
            raise SchedulingError("expected the exact branch result object")
        branch = value.get("branch_id")
        if branch not in join.activation.branch_ids:
            raise SchedulingError("the branch is outside the sealed activation")
        observation = value.get("observation_index")
        if type(observation) is not int:
            raise SchedulingError("the observation index is out of bounds")
        return (observation, _frozen_index(join.activation, branch))

    for value in sorted(values, key=order):
        join = apply_branch_result(join, value)
    return join


def blocked_dependants(activation, failed_branch, dependants_map) -> tuple[str, ...]:
    """A required failure blocks exactly its dependants, nothing else.

    The dependants map is graph-derived data owned by the compiler/ledger
    seam: this function scopes the blockage; the caller is responsible for
    passing the compiled graph's real dependency edges, not an ad-hoc map.
    """

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
    "apply_simultaneous_results",
    "blocked_dependants",
    "next_attempt",
    "open_join",
    "seal_activation",
    "visit_identity",
]
