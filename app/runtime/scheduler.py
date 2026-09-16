"""LangGraph scheduling adapter with ledger-reconciled idempotent node visits
(T040 first slice; runtime.md §2 compilation mapping, §4 visits/attempts,
FR-013/FR-030).

A `CompiledGraph` is mapped onto a real `StateGraph` whose nodes keep the
approved node IDs and run only code-owned handlers from a closed registry
keyed by the compiled handler keys — model output can never add, rename or
widen a handler. State is the checkpoint saver's closed profile (result
refs by execution ID and visit counters); every node visit derives a
deterministic execution identity, records it in the runtime ledger through
the ledger's own command replay (so a re-run or restart reconciles instead
of duplicating), and a visit whose result is already durable is never
re-executed. Routers return one declared enum value; the adapter seals the
activation set through `scheduling_state.seal_activation` before the branch
runs and routes with a LangGraph `Command`, never with an ad-hoc edge.
Persistence goes through `LedgerCheckpointSaver`: the ledger holds opaque
cursor bytes, and this module never parses, exposes or streams them. The
only public result is a bounded projection; handler exceptions become the
fixed `node_failed` fact with the node ID and nothing else.

Explicit limits of this slice: `human_gate` and `bounded_loop` nodes refuse
at build time; `all_selected` joins rely on activated branches completing
in the same superstep; sealed activations are reported from memory, not
recovered from the journal; no attempt reservation, budget settlement or
semantic result admission happens here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ..domain.refs import EntityRef
from .checkpoints import NAMESPACE, CheckpointError, LedgerCheckpointSaver
from .graph import HANDLER_KEYS, CompiledGraph
from .ledger import ExecutionSpec, RuntimeLedger
from .scheduling_state import seal_activation, visit_identity

__all__ = [
    "NAMESPACE",
    "GraphScheduler",
    "NodeContext",
    "SchedulerError",
    "SchedulerOutcome",
    "build_scheduler",
    "execution_identity",
]

_SUPPORTED_KINDS = frozenset({"deterministic", "agent", "join", "router"})
_MAX_NODES = 256


class SchedulerError(ValueError):
    """A build, registry, routing or run failure, sanitized of private detail."""


class _NodeFailure(Exception):
    """Internal: a node visit failed; carries only the node ID."""

    def __init__(self, node_id: str) -> None:
        super().__init__("node_failed")
        self.node_id = node_id


def execution_identity(run_id: str, node_id: str, loop_index: int) -> str:
    """The deterministic execution ID of one logical node visit."""

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"deeptwin:execution:{run_id}:{node_id}:{loop_index}"
        )
    )


def _visit_id(run_id: str, node_id: str, loop_index: int) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"deeptwin:visit:{run_id}:{node_id}:{loop_index}"
        )
    )


def _command_id(execution_id: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"deeptwin:command:execution:{execution_id}")
    )


def _merge_results(left: dict, right: dict) -> dict:
    merged = dict(left)
    for key, value in right.items():
        if key in merged and merged[key] != value:
            # two writers for one execution ID with different content is a
            # conflict, never a last-writer-wins overwrite
            raise SchedulerError("conflicting result write")
        merged[key] = value
    return merged


def _merge_counters(left: dict, right: dict) -> dict:
    return {**left, **right}


class _State(TypedDict):
    results: Annotated[dict, _merge_results]
    counters: Annotated[dict, _merge_counters]


@dataclass(frozen=True, slots=True)
class NodeContext:
    """What a handler learns about its visit: identity only, never clients."""

    run_id: str
    node_id: str
    execution_id: str
    visit_id: str
    loop_index: int


@dataclass(frozen=True, slots=True)
class SchedulerOutcome:
    """The bounded public projection of a run; never the raw channel state."""

    run_id: str
    graph_digest: str
    completed_node_ids: tuple[str, ...]
    execution_ids: tuple[tuple[str, str], ...]
    result_refs: tuple[tuple[str, EntityRef], ...]
    counters: dict
    activations: tuple[tuple[str, str, tuple[str, ...]], ...]


def _detached_view(state: dict) -> dict:
    return {
        "results": dict(state.get("results", {})),
        "counters": dict(state.get("counters", {})),
    }


class GraphScheduler:
    """One compiled graph bound to one run; built only by `build_scheduler`."""

    __slots__ = (
        "_activations",
        "_compiled",
        "_graph",
        "_handlers",
        "_ledger",
        "_recursion_limit",
        "_run_id",
        "_saver",
    )

    def __init__(self) -> None:
        raise TypeError("Use build_scheduler")

    def run(self) -> SchedulerOutcome:
        """Run to completion (or resume from the durable head); no streaming."""

        config = {
            "configurable": {"thread_id": self._run_id, "checkpoint_ns": ""},
            "recursion_limit": self._recursion_limit,
        }
        try:
            head = self._saver.get_tuple(config)
            initial = None if head is not None else {"results": {}, "counters": {}}
            final = self._graph.invoke(initial, config, durability="sync")
        except _NodeFailure as failure:
            raise SchedulerError(f"node_failed:{failure.node_id}") from None
        except SchedulerError:
            raise
        except CheckpointError:
            raise SchedulerError("checkpoint journal halted") from None
        except Exception:  # noqa: BLE001 - never surface private graph or provider detail
            raise SchedulerError("scheduler_failed") from None
        return self._project(final)

    def _project(self, state: dict) -> SchedulerOutcome:
        counters = dict(state.get("counters", {}))
        results = dict(state.get("results", {}))
        executions = []
        for node_id, count in sorted(counters.items()):
            for loop_index in range(count):
                execution_id = execution_identity(self._run_id, node_id, loop_index)
                if execution_id in results:
                    executions.append((node_id, execution_id))
        refs = tuple(sorted((key, results[key]) for key in results))
        return SchedulerOutcome(
            run_id=self._run_id,
            graph_digest=self._compiled.graph_digest,
            completed_node_ids=tuple(
                sorted(node for node, count in counters.items() if count)
            ),
            execution_ids=tuple(executions),
            result_refs=refs,
            counters=counters,
            activations=tuple(self._activations),
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchedulerError(message)


def _router_branches(compiled: CompiledGraph, node_id: str) -> dict[str, str]:
    graph = compiled.execution_graph
    node = next(item for item in graph.nodes if item.node_id == node_id)
    branches = {}
    for edge in graph.edges:
        if edge.source_node_id != node_id or edge.kind != "control":
            continue
        condition = edge.data.get("condition")
        if condition is None:
            continue
        branches[condition["value"]] = edge.target_node_id
    _require(
        set(branches) == set(node.config["allowed_values"]),
        "router branches incomplete",
    )
    return branches


def build_scheduler(
    compiled: CompiledGraph,
    *,
    ledger: RuntimeLedger,
    run_id: str,
    handlers,
) -> GraphScheduler:
    _require(type(compiled) is CompiledGraph, "an exact CompiledGraph is required")
    _require(type(ledger) is RuntimeLedger, "an exact RuntimeLedger is required")
    _require(type(run_id) is str, "run id must be a string")
    _require(1 <= len(compiled.nodes) <= _MAX_NODES, "node count out of bounds")
    kinds = {node.node_id: node.kind for node in compiled.nodes}
    for node_id, kind in kinds.items():
        _require(kind in _SUPPORTED_KINDS, f"unsupported node kind: {kind} ({node_id})")
    required_keys = {key for _, key in compiled.handler_keys}
    _require(type(handlers) is dict, "handlers must be a closed mapping")
    # the registry namespace is the closed core key set: every compiled key
    # must be present and no key outside the namespace may exist at all
    _require(
        required_keys <= set(handlers), "handler registry is missing a compiled key"
    )
    _require(
        set(handlers) <= set(HANDLER_KEYS.values()),
        "handler registry carries an unknown key",
    )
    for key, handler in handlers.items():
        _require(
            callable(handler) and not isinstance(handler, str),
            f"handler {key} is not callable",
        )
    handler_by_node = {node_id: handlers[key] for node_id, key in compiled.handler_keys}
    predecessors = {
        node_id: sources for node_id, sources in compiled.activation_predecessors
    }

    scheduler = object.__new__(GraphScheduler)
    scheduler._compiled = compiled
    scheduler._ledger = ledger
    scheduler._run_id = run_id
    scheduler._handlers = dict(handlers)
    scheduler._activations = []
    scheduler._recursion_limit = min(4 * len(compiled.nodes) + 8, 4096)

    try:
        saver = LedgerCheckpointSaver(
            ledger,
            run_id,
            graph_digest=compiled.graph_digest,
            authority_digest=compiled.authority_digest,
            node_ids=tuple(kinds),
        )
    except CheckpointError:
        raise SchedulerError("checkpoint journal binding failed") from None
    scheduler._saver = saver

    def record_execution(node_id: str, state: dict) -> tuple[str, int, NodeContext]:
        counters = state.get("counters", {})
        loop_index = counters.get(node_id, 0)
        execution_id = execution_identity(run_id, node_id, loop_index)
        parents = tuple(
            execution_identity(run_id, source, counters[source] - 1)
            for source in predecessors.get(node_id, ())
            if counters.get(source, 0) > 0
        )
        spec = ExecutionSpec(
            execution_id,
            run_id,
            node_id,
            _visit_id(run_id, node_id, loop_index),
            (loop_index,),
            parents,
        )
        try:
            ledger.create_execution(_command_id(execution_id), spec)
        except Exception:  # noqa: BLE001 - ledger detail stays private
            raise _NodeFailure(node_id) from None
        context = NodeContext(run_id, node_id, execution_id, spec.visit_id, loop_index)
        return execution_id, loop_index, context

    def producing_node(node_id: str):
        handler = handler_by_node[node_id]

        def node_fn(state: dict):
            loop_index = state.get("counters", {}).get(node_id, 0)
            if execution_identity(run_id, node_id, loop_index) in state.get(
                "results", {}
            ):
                return {}  # this visit is already durable: never re-run it
            execution_id, loop_index, context = record_execution(node_id, state)
            try:
                result = handler(context, _detached_view(state))
            except Exception:  # noqa: BLE001 - handler detail is private
                raise _NodeFailure(node_id) from None
            if type(result) is not EntityRef:
                raise _NodeFailure(node_id)
            return {
                "results": {execution_id: result},
                "counters": {node_id: loop_index + 1},
            }

        return node_fn

    def router_node(node_id: str, branches: dict[str, str]):
        handler = handler_by_node[node_id]

        def node_fn(state: dict):
            _execution_id, loop_index, context = record_execution(node_id, state)
            try:
                decision = handler(context, _detached_view(state))
            except Exception:  # noqa: BLE001
                raise _NodeFailure(node_id) from None
            if type(decision) is not str or decision not in branches:
                raise _NodeFailure(node_id)  # an undeclared decision activates nothing
            target = branches[decision]
            try:
                activation = seal_activation(
                    run_id=run_id,
                    router_node_id=node_id,
                    visit=visit_identity(node_id, loop_index=loop_index),
                    branch_ids=[target],
                )
            except Exception:  # noqa: BLE001
                raise _NodeFailure(node_id) from None
            scheduler._activations.append(
                (node_id, activation.activation_id, (target,))
            )
            return Command(goto=target, update={"counters": {node_id: loop_index + 1}})

        return node_fn

    builder = StateGraph(_State)
    router_targets: dict[str, tuple[str, ...]] = {}
    for node_id, kind in kinds.items():
        if kind == "router":
            branches = _router_branches(compiled, node_id)
            router_targets[node_id] = tuple(sorted(set(branches.values())))
            builder.add_node(
                node_id,
                router_node(node_id, branches),
                destinations=router_targets[node_id],
            )
        else:
            builder.add_node(node_id, producing_node(node_id))
    has_successor = set(router_targets)
    for node_id, sources in predecessors.items():
        for source in sources:
            has_successor.add(source)
            if kinds[source] != "router":
                # routers dispatch through their sealed Command, never an edge
                builder.add_edge(source, node_id)
    for node_id in compiled.entry_node_ids:
        builder.add_edge(START, node_id)
    for node_id in kinds:
        if node_id not in has_successor:
            builder.add_edge(node_id, END)
    try:
        scheduler._graph = builder.compile(checkpointer=saver)
    except Exception:  # noqa: BLE001
        raise SchedulerError("graph compilation failed") from None
    return scheduler
