"""Trace slicing over real preserved runs (T055 reopened scope; growth.md
`OriginalExecution` boundary; runtime.md §9 read-only replay).

A run trace is read back from what the scheduler actually left behind: the
runtime ledger's execution records (one per logical node visit, with the
parent executions recorded at dispatch) and the durable checkpoint journal
for that run, from which only the result references are taken — never raw
channel state, cursor bytes or handler detail. Slicing picks one boundary
execution and returns its ancestors (transitively, by recorded parents),
its direct dependants and the statically possible nodes that never ran,
so a diagnosis starts from a sealed, evidence-backed boundary instead of
a caller-described one. Values are issued and immutable; reading is
read-only and performs no model, tool or replay call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef, uuid_string
from ..runtime.checkpoints import NAMESPACE, CheckpointError, LedgerCheckpointSaver
from ..runtime.graph import CompiledGraph
from ..runtime.ledger import RuntimeLedger

_ISSUE_TOKEN = object()


class RunTraceError(ValueError):
    """The run, graph binding or boundary is not readable as a sealed trace."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


@dataclass(frozen=True, slots=True, init=False)
class TraceExecution:
    """One recorded node visit and its durable result reference, if any."""

    execution_id: str
    node_id: str
    loop_index: int
    parents: tuple[str, ...]
    result_ref: EntityRef | None
    created_at_ms: int


@dataclass(frozen=True, slots=True, init=False)
class RunTrace:
    """The sealed read-back of one run: executions in recorded order."""

    run_id: str
    graph_digest: str
    node_ids: tuple[str, ...]
    executions: tuple[TraceExecution, ...]
    checkpoint_revision: int
    observation_gaps: tuple[str, ...]
    _issuer_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, init=False)
class TraceSlice:
    """One boundary execution with its recorded context."""

    trace_run_id: str
    boundary: TraceExecution
    ancestors: tuple[TraceExecution, ...]
    dependants: tuple[TraceExecution, ...]
    excluded_node_ids: tuple[str, ...]
    _issuer_token: object = field(repr=False, compare=False)


def is_issued_trace(value) -> bool:
    return (
        type(value) in (RunTrace, TraceSlice)
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def _require_trace(value) -> None:
    if (
        type(value) is not RunTrace
        or getattr(value, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise RunTraceError("a framework-issued run trace is required")


def read_run_trace(ledger, run_id, compiled) -> RunTrace:
    if type(ledger) is not RuntimeLedger:
        raise RunTraceError("an exact RuntimeLedger is required")
    if type(compiled) is not CompiledGraph:
        raise RunTraceError("an exact CompiledGraph is required")
    try:
        uuid_string(run_id)
    except (DomainContractError, TypeError, ValueError):
        raise RunTraceError("run id is not a canonical UUID") from None
    try:
        ledger.get_run(run_id)
    except KeyError:
        raise RunTraceError("unknown run") from None
    node_ids = tuple(node.node_id for node in compiled.nodes)
    try:
        saver = LedgerCheckpointSaver(
            ledger,
            run_id,
            graph_digest=compiled.graph_digest,
            authority_digest=compiled.authority_digest,
            node_ids=node_ids,
        )
        head = saver.get_tuple(
            {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}}
        )
    except CheckpointError:
        # the journal is bound to another graph/authority or is unreadable:
        # a trace must never be assembled against the wrong compilation
        raise RunTraceError("checkpoint journal is not bound to this graph") from None
    results = {}
    if head is not None:
        for execution_id, ref in (
            head.checkpoint["channel_values"].get("results", {}).items()
        ):
            if type(ref) is EntityRef:
                results[execution_id] = ref
    try:
        revision = ledger.checkpoint_for_replay(run_id, NAMESPACE)["revision"]
    except KeyError:
        revision = 0
    executions = []
    for row in ledger.executions_for_run(run_id):
        spec = row["spec"]
        executions.append(
            _issue(
                TraceExecution,
                execution_id=spec["execution_id"],
                node_id=spec["node_id"],
                loop_index=spec["loop_indices"][0] if spec["loop_indices"] else 0,
                parents=tuple(spec["parent_execution_ids"]),
                result_ref=results.get(spec["execution_id"]),
                created_at_ms=row["created_at_ms"],
            )
        )
    gaps = tuple(item.execution_id for item in executions if item.result_ref is None)
    return _issue(
        RunTrace,
        run_id=run_id,
        graph_digest=compiled.graph_digest,
        node_ids=node_ids,
        executions=tuple(executions),
        checkpoint_revision=revision,
        observation_gaps=gaps,
        _issuer_token=_ISSUE_TOKEN,
    )


def slice_trace(trace, *, boundary_node_id, loop_index=None) -> TraceSlice:
    _require_trace(trace)
    if type(boundary_node_id) is not str:
        raise RunTraceError("boundary node id must be a string")
    candidates = [
        item
        for item in trace.executions
        if item.node_id == boundary_node_id
        and (loop_index is None or item.loop_index == loop_index)
    ]
    if not candidates:
        raise RunTraceError("the boundary never executed in this run")
    if len(candidates) > 1:
        raise RunTraceError("the boundary has several visits; name the loop index")
    boundary = candidates[0]
    by_id = {item.execution_id: item for item in trace.executions}
    ancestors: list[str] = []
    frontier = list(boundary.parents)
    while frontier:
        parent_id = frontier.pop(0)
        if parent_id in ancestors or parent_id not in by_id:
            continue
        ancestors.append(parent_id)
        frontier.extend(by_id[parent_id].parents)
    ordered_ancestors = tuple(
        item for item in trace.executions if item.execution_id in ancestors
    )
    dependants = tuple(
        item for item in trace.executions if boundary.execution_id in item.parents
    )
    executed = {item.node_id for item in trace.executions}
    excluded = tuple(sorted(node for node in trace.node_ids if node not in executed))
    return _issue(
        TraceSlice,
        trace_run_id=trace.run_id,
        boundary=boundary,
        ancestors=ordered_ancestors,
        dependants=dependants,
        excluded_node_ids=excluded,
        _issuer_token=_ISSUE_TOKEN,
    )
