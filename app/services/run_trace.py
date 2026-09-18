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
class TraceAttempt:
    """One attempt (시도) of a visit as the ledger recorded it: its number, its
    terminal facts, and whether it is the attempt the bound checkpoint row names
    as the producer of the visit's durable result."""

    attempt_id: str
    attempt_no: int
    phase: str
    terminal_outcome: str | None
    remote_terminal_observed: str
    usage_finality: str
    cancel_state: str
    produced_result: bool
    bound_revision: int | None


@dataclass(frozen=True, slots=True, init=False)
class TraceExecution:
    """One recorded node visit (수행), its attempts, and its durable result
    reference, if any. Three honest states: no attempts (a handler-produced
    visit; nothing to attribute), a result attributed to the one attempt a
    bound checkpoint row names (`producing_attempt_id`, `produced_result`),
    or attempts with a result that no bound row names (a result produced
    outside the dispatcher, e.g. a resume with a plain handler after a failed
    attempt): then `producing_attempt_id` is None and no attempt claims it —
    a past attempt never carries a later result."""

    execution_id: str
    node_id: str
    loop_index: int
    parents: tuple[str, ...]
    result_ref: EntityRef | None
    created_at_ms: int
    attempts: tuple[TraceAttempt, ...]
    producing_attempt_id: str | None


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
    # one closed read boundary over the journal and the ledger: a trace is never
    # assembled against the wrong compilation, and no ledger or storage detail
    # (a session refusal, a missing row, a corrupt binding) leaks past it
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
        raise RunTraceError("checkpoint journal is not bound to this graph") from None
    try:
        try:
            revision = ledger.checkpoint_for_replay(run_id, NAMESPACE)["revision"]
        except KeyError:
            revision = 0
        # the bound rows name, per execution, the attempt that produced its
        # result; the ledger re-verified each row and that the execution is this
        # run's. One execution has at most one bound row (the registry binds one
        # attempt per execution); a later row for the same execution would win
        bound = {}
        for row_revision, execution_id, attempt_id in ledger.bound_checkpoints_for_run(
            run_id, NAMESPACE
        ):
            bound[execution_id] = (attempt_id, row_revision)
        attempts_by_execution = {}
        for item in ledger.attempts_for_run(run_id):
            attempts_by_execution.setdefault(item["spec"]["execution_id"], []).append(
                item
            )
        execution_rows = ledger.executions_for_run(run_id)
    except Exception:  # noqa: BLE001 - ledger and storage detail stays private
        raise RunTraceError("run journal is not readable") from None
    # the durable results: the head's merged channel, then the head's pending
    # writes — a result the journal preserved (a crash between the bound
    # pending-writes row and the merging checkpoint) is still the visit's result
    results = {}
    if head is not None:
        values = head.checkpoint["channel_values"].get("results", {})
        pending = [
            value
            for _, channel, value in head.pending_writes
            if channel == "results" and type(value) is dict
        ]
        for mapping in (values, *pending):
            for execution_id, ref in mapping.items():
                if type(ref) is EntityRef:
                    results[execution_id] = ref
    executions = []
    for row in execution_rows:
        spec = row["spec"]
        execution_id = spec["execution_id"]
        producing, bound_revision = bound.get(execution_id, (None, None))
        attempts = tuple(
            _issue(
                TraceAttempt,
                attempt_id=item["spec"]["attempt_id"],
                attempt_no=item["spec"]["attempt_no"],
                phase=item["phase"],
                terminal_outcome=item["terminal_outcome"],
                remote_terminal_observed=item["remote_terminal_observed"],
                usage_finality=item["usage_finality"],
                cancel_state=item["cancel_state"],
                produced_result=item["spec"]["attempt_id"] == producing,
                bound_revision=(
                    bound_revision if item["spec"]["attempt_id"] == producing else None
                ),
            )
            for item in attempts_by_execution.get(execution_id, ())
        )
        executions.append(
            _issue(
                TraceExecution,
                execution_id=execution_id,
                node_id=spec["node_id"],
                loop_index=spec["loop_indices"][0] if spec["loop_indices"] else 0,
                parents=tuple(spec["parent_execution_ids"]),
                result_ref=results.get(execution_id),
                created_at_ms=row["created_at_ms"],
                attempts=attempts,
                producing_attempt_id=producing,
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
