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

Bounded loops (slice 2): the loop controller's handler returns a closed
facts mapping over the graph's declared fact names; the compiled
termination expression decides exit versus another iteration, each
iteration is a NEW visit with its own execution identity, and reaching
the hard iteration cap unterminated fails the run as `loop_cap:<loop_id>`
— the recursion limit is only an emergency cap above that product limit.

Human gates (slice 3): the graph always stops before a `human_gate` node
(static interrupt); `run()` resumes it only when the persistent run
approval service holds an owner-recorded, approved decision for every
declared scope — a recorded rejection fails the gate as
`approval_rejected:<node>`, absence returns the honest `awaiting_human`
projection, and the gate body itself re-verifies the records. No handler
return value, boolean or caller-supplied reference can pass a gate.

Fan-ins (review closure): a node with several producers runs once, only
after EVERY activated producer completed — a producer behind a router
counts only when that router sealed it (the sealed activation is kept as
a closed `<router>.activation.<target>` counter, durable in the journal),
and an open activated producer defers the trigger instead of running the
fan-in against an open set. Routers, joins and human gates inside a
bounded loop are refused at build time rather than given visit-blind
activations or approvals.

Explicit limits of this slice: retries within a visit are not
implemented (a failed visit fails the run and is resumed on restart); no
attempt reservation, budget settlement or semantic result admission
happens here. The outcome projection is restart-invariant: sealed
activations are rebuilt from the durable activation markers and consumed
approvals are re-read from the owner's records, never kept in memory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ..domain.refs import EntityRef, canonical_json
from ..services.run_approvals import PersistentRunApprovals
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

_SUPPORTED_KINDS = frozenset(
    {"deterministic", "agent", "join", "router", "bounded_loop", "human_gate"}
)
_DISPATCHING_KINDS = frozenset({"router", "bounded_loop"})  # route by sealed Command
_MAX_NODES = 256
_SCALARS = (str, int, bool)


class SchedulerError(ValueError):
    """A build, registry, routing or run failure, sanitized of private detail."""


class _NodeFailure(Exception):
    """Internal: a node visit failed; carries only the node ID."""

    def __init__(self, node_id: str) -> None:
        super().__init__("node_failed")
        self.node_id = node_id


class _LoopCap(Exception):
    """Internal: a bounded loop reached its hard iteration cap unterminated."""

    def __init__(self, loop_id: str) -> None:
        super().__init__("loop_cap")
        self.loop_id = loop_id


class _GateRejected(Exception):
    """Internal: an owner recorded a rejection for a human gate scope."""

    def __init__(self, node_id: str) -> None:
        super().__init__("approval_rejected")
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
    # (gate node, scope) pairs the run is honestly waiting on; empty when done
    awaiting_human: tuple[tuple[str, str], ...]
    # (gate node, approval refs) actually consumed to pass each gate
    approvals: tuple[tuple[str, tuple[EntityRef, ...]], ...]


def _detached_view(state: dict) -> dict:
    return {
        "results": dict(state.get("results", {})),
        "counters": dict(state.get("counters", {})),
    }


class GraphScheduler:
    """One compiled graph bound to one run; built only by `build_scheduler`."""

    __slots__ = (
        "_approvals",
        "_compiled",
        "_gates",
        "_graph",
        "_handlers",
        "_ledger",
        "_recursion_limit",
        "_routers",
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
        awaiting: tuple[tuple[str, str], ...] = ()
        try:
            head = self._saver.get_tuple(config)
            initial = None if head is not None else {"results": {}, "counters": {}}
            # the graph always stops before a human gate; it is resumed only
            # once the owner's recorded approvals cover every scope of every
            # pending gate — checked BEFORE any resume, never after
            final = None
            for _ in range(len(self._gates) + 2):
                if initial is None:
                    pending = self._pending_gates(config)
                    if pending:
                        awaiting = self._gate_status(pending)
                        if awaiting:
                            final = self._graph.get_state(config).values
                            break
                final = self._graph.invoke(initial, config, durability="sync")
                initial = None
                if not self._pending_gates(config):
                    break
            else:
                raise SchedulerError("human gate resume bound exceeded")
        except _NodeFailure as failure:
            raise SchedulerError(f"node_failed:{failure.node_id}") from None
        except _LoopCap as cap:
            raise SchedulerError(f"loop_cap:{cap.loop_id}") from None
        except _GateRejected as rejected:
            raise SchedulerError(f"approval_rejected:{rejected.node_id}") from None
        except SchedulerError:
            raise
        except CheckpointError:
            raise SchedulerError("checkpoint journal halted") from None
        except Exception:  # noqa: BLE001 - never surface private graph or provider detail
            raise SchedulerError("scheduler_failed") from None
        return self._project(final, awaiting)

    def _pending_gates(self, config: dict) -> tuple[str, ...]:
        return tuple(
            node for node in self._graph.get_state(config).next if node in self._gates
        )

    def _gate_status(self, pending: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
        """Consult the recorded approvals; a rejection fails, absence waits."""

        awaiting = []
        for node_id in pending:
            for scope in self._gates[node_id]:
                found = self._approvals.lookup(self._run_id, node_id, scope)
                if found is None:
                    # the ask is durable and replayable: the owner can only
                    # approve a gate this run actually reached
                    self._ledger.request_gate_approval(self._run_id, node_id, scope)
                    awaiting.append((node_id, scope))
                elif found.decision != "approved":
                    raise _GateRejected(node_id)
        return tuple(awaiting)

    def _consumed_approvals(self, counters: dict) -> tuple:
        """The approval refs each completed gate actually passed on — read
        from the owner's durable records, so a restarted scheduler projects
        exactly what the first one did."""

        consumed = []
        for node_id, scopes in sorted(self._gates.items()):
            if not counters.get(node_id):
                continue  # the gate never ran: nothing was consumed
            refs = []
            for scope in scopes:
                try:
                    found = self._approvals.lookup(self._run_id, node_id, scope)
                except Exception:  # noqa: BLE001 - the service's detail stays behind this boundary
                    raise SchedulerError(f"approval_unreadable:{node_id}") from None
                if found is None or found.decision != "approved":
                    raise SchedulerError(f"approval_missing:{node_id}")
                refs.append(found.approval_ref)
            consumed.append((node_id, tuple(refs)))
        return tuple(consumed)

    def _sealed_activations(self, raw_counters: dict) -> tuple:
        """Router activations rebuilt from the durable activation markers;
        the sealed identity is a pure function of run, router, visit and
        branches, so it is the same after any restart."""

        activations = []
        for node_id, branches in sorted(self._routers.items()):
            if raw_counters.get(node_id, 0) > 1:
                # a router visits once (no router inside a loop, one trigger);
                # last-writer-wins markers could not carry a second visit, so a
                # revisit is refused loudly rather than projected partially
                raise SchedulerError(f"router_revisited:{node_id}")
            for loop_index in range(raw_counters.get(node_id, 0)):
                targets = sorted(
                    target
                    for target in set(branches.values())
                    if raw_counters.get(f"{node_id}.activation.{target}") == loop_index + 1
                )
                if not targets:
                    continue
                sealed = seal_activation(
                    run_id=self._run_id,
                    router_node_id=node_id,
                    visit=visit_identity(node_id, loop_index=loop_index),
                    branch_ids=targets,
                )
                activations.append((node_id, sealed.activation_id, tuple(targets)))
        return tuple(activations)

    def _project(
        self, state: dict, awaiting: tuple[tuple[str, str], ...] = ()
    ) -> SchedulerOutcome:
        node_ids = {node.node_id for node in self._compiled.nodes}
        raw_counters = state.get("counters", {})
        counters = {
            key: value
            for key, value in raw_counters.items()
            if key in node_ids  # activation markers are routing facts, not visits
        }
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
            activations=self._sealed_activations(raw_counters),
            awaiting_human=awaiting,
            approvals=self._consumed_approvals(counters),
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


@dataclass(frozen=True, slots=True)
class _LoopPlan:
    loop_id: str
    cap: int
    termination: dict
    internal_targets: tuple[str, ...]
    exit_target: str
    fact_names: frozenset


def _loop_plan(compiled: CompiledGraph, node_id: str) -> _LoopPlan:
    graph = compiled.execution_graph
    node = next(item for item in graph.nodes if item.node_id == node_id).as_dict()
    loop_id = node["config"]["loop_id"]
    region = next((r for r in compiled.loop_regions if r[0] == loop_id), None)
    _require(
        region is not None and node_id in region[1], "loop controller has no region"
    )
    # thawed plain dicts: the frozen edge/node views are not canonical inputs
    termination = node["config"]["termination"]
    internal, exit_target = [], None
    for item in graph.edges:
        edge = item.as_dict()
        if edge["source_node_id"] != node_id or edge["kind"] != "control":
            continue
        condition = edge.get("condition")
        if edge["loop_id"] == loop_id and condition is None:
            internal.append(edge["target_node_id"])
        elif condition is not None and canonical_json(condition) == canonical_json(
            termination
        ):
            exit_target = edge["target_node_id"]
    _require(bool(internal) and exit_target is not None, "loop edges incomplete")
    return _LoopPlan(
        loop_id=loop_id,
        cap=region[2],
        termination=dict(termination),
        internal_targets=tuple(sorted(set(internal))),
        exit_target=exit_target,
        fact_names=frozenset(graph.fact_names),
    )


def _facts(value, plan: _LoopPlan) -> dict:
    """Handler-returned facts: a closed mapping over the graph's declared facts."""

    if type(value) is not dict or not value or not set(value) <= plan.fact_names:
        raise ValueError("facts outside the graph")
    for item in value.values():
        if type(item) not in _SCALARS:
            raise ValueError("fact values must be scalars")
    return dict(value)


def _terminated(plan: _LoopPlan, facts: dict) -> bool:
    expression = plan.termination
    if expression["fact"] not in facts:
        raise ValueError("termination fact absent")
    observed = facts[expression["fact"]]
    expected = expression["value"]
    if type(observed) is not type(expected):
        raise ValueError("termination fact type mismatch")
    equal = observed == expected
    return equal if expression["op"] == "eq" else not equal


def build_scheduler(
    compiled: CompiledGraph,
    *,
    ledger: RuntimeLedger,
    run_id: str,
    handlers,
    approvals=None,
) -> GraphScheduler:
    _require(type(compiled) is CompiledGraph, "an exact CompiledGraph is required")
    _require(type(ledger) is RuntimeLedger, "an exact RuntimeLedger is required")
    _require(type(run_id) is str, "run id must be a string")
    _require(1 <= len(compiled.nodes) <= _MAX_NODES, "node count out of bounds")
    kinds = {node.node_id: node.kind for node in compiled.nodes}
    for node_id, kind in kinds.items():
        _require(kind in _SUPPORTED_KINDS, f"unsupported node kind: {kind} ({node_id})")
    loop_members = {
        member for _, members, _ in compiled.loop_regions for member in members
    }
    for node_id in sorted(loop_members):
        # a router, join or human gate inside a loop would need visit-scoped
        # activations and approvals; this slice refuses instead of guessing
        _require(
            kinds[node_id] not in {"router", "join", "human_gate"},
            f"{kinds[node_id]} node {node_id} inside a bounded loop is unsupported",
        )
    gates = {
        node.node_id: tuple(node.as_dict()["config"]["approval_scopes"])
        for node in compiled.execution_graph.nodes
        if node.kind == "human_gate"
    }
    if gates:
        # a human gate can only be passed by the owner's recorded decision:
        # the persistent approval service is the sole reader of that record
        _require(
            type(approvals) is PersistentRunApprovals,
            "human_gate nodes require the persistent run approval service",
        )
    else:
        _require(
            approvals is None, "approvals are only meaningful with human_gate nodes"
        )
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
    scheduler._approvals = approvals
    scheduler._gates = gates
    scheduler._routers = {
        node_id: _router_branches(compiled, node_id)
        for node_id, kind in kinds.items()
        if kind == "router"
    }
    loop_steps = sum(
        cap * (len(members) + 1) for _, members, cap in compiled.loop_regions
    )
    # an emergency cap in addition to the domain loop budgets (runtime.md §2)
    scheduler._recursion_limit = min(4 * len(compiled.nodes) + 8 + 2 * loop_steps, 4096)

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

    branch_router = {}
    for node_id, branches in scheduler._routers.items():
        for target in set(branches.values()):
            branch_router[target] = node_id

    def producing_node(node_id: str):
        handler = handler_by_node[node_id]
        sources = predecessors.get(node_id, ())

        def node_fn(state: dict):
            counters = state.get("counters", {})
            if len(sources) > 1:
                # a fan-in runs once, after EVERY activated producer completed:
                # a producer behind a router counts only when that router
                # sealed it; an open activated producer defers this trigger
                for source in sources:
                    router = branch_router.get(source)
                    if router is not None and not counters.get(
                        f"{router}.activation.{source}"
                    ):
                        continue
                    if counters.get(source, 0) == 0:
                        return {}
            loop_index = counters.get(node_id, 0)
            if execution_identity(run_id, node_id, loop_index) in state.get(
                "results", {}
            ):
                return {}  # this visit is already durable: never re-run it
            if node_id in gates:
                # defense in depth: the gate body runs only against recorded
                # approvals for every scope, whatever resumed the graph
                for scope in gates[node_id]:
                    found = approvals.lookup(run_id, node_id, scope)
                    if found is None or found.decision != "approved":
                        raise _NodeFailure(node_id)
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
                # sealed before dispatch; the identity is re-derived from the
                # durable markers at projection, never kept in process memory
                seal_activation(
                    run_id=run_id,
                    router_node_id=node_id,
                    visit=visit_identity(node_id, loop_index=loop_index),
                    branch_ids=[target],
                )
            except Exception:  # noqa: BLE001
                raise _NodeFailure(node_id) from None
            return Command(
                goto=target,
                update={
                    "counters": {
                        node_id: loop_index + 1,
                        # the sealed activation, durable in the closed counters
                        # channel so fan-ins can tell "not activated" from "open"
                        f"{node_id}.activation.{target}": loop_index + 1,
                    }
                },
            )

        return node_fn

    def loop_node(node_id: str, plan: _LoopPlan):
        handler = handler_by_node[node_id]

        def node_fn(state: dict):
            _execution_id, loop_index, context = record_execution(node_id, state)
            try:
                facts = _facts(handler(context, _detached_view(state)), plan)
                done = _terminated(plan, facts)
            except Exception:  # noqa: BLE001 - handler/fact detail is private
                raise _NodeFailure(node_id) from None
            update = {"counters": {node_id: loop_index + 1}}
            if done:
                return Command(goto=plan.exit_target, update=update)
            if loop_index + 1 >= plan.cap:
                # the hard cap is a product limit: another iteration would
                # exceed it, so the run fails loudly instead of looping on
                raise _LoopCap(plan.loop_id)
            return Command(goto=list(plan.internal_targets), update=update)

        return node_fn

    builder = StateGraph(_State)
    dispatch_targets: dict[str, tuple[str, ...]] = {}
    for node_id, kind in kinds.items():
        if kind == "router":
            branches = scheduler._routers[node_id]
            dispatch_targets[node_id] = tuple(sorted(set(branches.values())))
            builder.add_node(
                node_id,
                router_node(node_id, branches),
                destinations=dispatch_targets[node_id],
            )
        elif kind == "bounded_loop":
            plan = _loop_plan(compiled, node_id)
            dispatch_targets[node_id] = tuple(
                sorted({*plan.internal_targets, plan.exit_target})
            )
            builder.add_node(
                node_id,
                loop_node(node_id, plan),
                destinations=dispatch_targets[node_id],
            )
        else:
            builder.add_node(node_id, producing_node(node_id))
    has_successor = set(dispatch_targets)
    for node_id, sources in predecessors.items():
        for source in sources:
            has_successor.add(source)
            if kinds[source] not in _DISPATCHING_KINDS:
                # routers and loop controllers dispatch through their sealed
                # Command, never through an unconditional edge
                builder.add_edge(source, node_id)
    for node_id in compiled.entry_node_ids:
        builder.add_edge(START, node_id)
    for node_id in kinds:
        if node_id not in has_successor:
            builder.add_edge(node_id, END)
    try:
        # static interrupts: the run always stops before a human gate, and
        # only `run()`'s approval check resumes it
        scheduler._graph = builder.compile(
            checkpointer=saver, interrupt_before=sorted(gates) or None
        )
    except Exception:  # noqa: BLE001
        raise SchedulerError("graph compilation failed") from None
    return scheduler
