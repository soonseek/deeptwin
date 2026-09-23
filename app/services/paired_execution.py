"""Isolated paired execution of a frozen comparison (US6, T061; FR-022/023/025).

One paired round runs the baseline and the candidate environment over the same
frozen queue items. Each (side, item) run executes on the real scheduler in its
own fresh vault and runtime ledger under the plan's reset root — nothing one run
wrote is visible to another, so a candidate can never read the baseline's output
(or its own earlier item's) and the pairing is the only link between them. The
evaluator is code-owned: it scores what each run durably produced, per item, as
exact decimal strings, and may declare an item invalid with reasons. The round is
recorded through `record_comparison_round` against the exact frozen plan: a round
with any invalid item is `invalid` with every reason, and only a fully valid
round carries metrics — the per-metric mean over items, exact decimals, never a
zero standing in for a failed measurement.

Partial-scope downstream effects are traced from the runs themselves: for each
item, the nodes whose durable results differ between the sides, and — given the
changed nodes the candidate declared — the nodes whose difference lies outside
the declared nodes' downstream closure, which a partial change must explain
before it is trusted.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from ..domain.refs import EntityRef, canonical_json
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore
from ..runtime.graph import CompiledGraph
from ..runtime.ledger import RunSpec, RuntimeLedger
from ..runtime.scheduler import build_scheduler
from ..storage import Store
from .comparisons import ComparisonResult, is_frozen_plan, record_comparison_round
from .run_trace import RunTrace, read_run_trace

MAX_ITEMS = 64
_DECIMAL = re.compile(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?\Z")
_QUANTUM = Decimal("0.000000000000000001")
_STAMP = "1970-01-01T00:00:00.000000Z"


class PairedExecutionError(ValueError):
    """A paired round cannot be executed or recorded as presented."""


@dataclass(frozen=True, slots=True)
class PairedSide:
    """One side's code-owned wiring: its compiled graph and handler registry.

    `handlers(item, domain)` returns the closed handler registry for one queue
    item; it receives the item's own content and the fresh isolated store of
    this one run (where its results are sealed), never the other side's.
    """

    label: str
    compiled: CompiledGraph
    handlers: object


@dataclass(frozen=True, slots=True)
class SideRun:
    """What one isolated run left behind, read back from its own vault."""

    side: str
    item_index: int
    manifest_ref: EntityRef
    trace: RunTrace
    results: tuple[tuple[str, dict], ...]  # (node id, the node's durable result content)


@dataclass(frozen=True, slots=True)
class PairedRound:
    result: ComparisonResult
    runs: tuple[tuple[SideRun, SideRun], ...]
    changed_nodes: tuple[tuple[str, ...], ...]      # per item: nodes whose results differ
    unexplained_nodes: tuple[tuple[str, ...], ...]  # per item: differences outside the scope


def _record(domain, roots, kind, content, parents=()):
    record = ImmutableRecord.create(
        kind=kind, id=str(uuid4()), version=1, created_at_utc=_STAMP, actor_ref=roots.actor,
        parent_refs=tuple(parents), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content=content,
    )
    domain.put(record)
    return record.ref


def _run_isolated(root: Path, side: PairedSide, item_index: int, item: dict, plan) -> SideRun:
    """One run in a fresh vault and ledger nobody else opens."""

    directory = root / side.label / str(item_index)
    if directory.exists():
        raise PairedExecutionError("an isolated run directory must be fresh")
    directory.mkdir(parents=True)
    domain = DomainStore(Store(directory / "vault"))
    roots = domain.initialize_vault()
    # the plan lives in the caller's vault: bound here by its id and digest as plain
    # text (a ref-shaped value would have to resolve inside this isolated vault)
    plan_binding = {"plan_id": plan.plan_ref.id, "plan_sha256": plan.plan_ref.sha256}
    work = _record(domain, roots, "work_revision", {"paired_item": item, "item_index": item_index})
    environment = _record(domain, roots, "environment", {
        "paired_side": side.label, "graph_digest": side.compiled.graph_digest, "plan_binding": plan_binding})
    consent = _record(domain, roots, "run_consent", {"isolated_comparison_plan": plan_binding})
    budget = _record(domain, roots, "budget_policy", {"plan_budget_id": plan.budget.id,
                                                      "plan_budget_sha256": plan.budget.sha256})
    manifest = _record(domain, roots, "run_manifest", {
        "paired_side": side.label, "item_index": item_index, "plan_binding": plan_binding,
        "graph_digest": side.compiled.graph_digest}, parents=(work, environment))
    ledger = RuntimeLedger(domain, clock_ms=lambda: 1_000)
    ledger.reconcile_startup(str(uuid4()), observed_owners={})
    run = RunSpec(str(uuid4()), work, environment, consent, "isolated-comparison", budget,
                  str(uuid4()), manifest)
    ledger.create_run(str(uuid4()), run)
    handlers = side.handlers(dict(item), domain)
    build_scheduler(side.compiled, ledger=ledger, run_id=run.run_id, handlers=handlers).run()
    trace = read_run_trace(ledger, run.run_id, side.compiled)
    results = []
    for execution in trace.executions:
        if execution.result_ref is not None:
            results.append((execution.node_id,
                            domain.get(execution.result_ref).body["content"]))
    return SideRun(side.label, item_index, manifest, trace, tuple(results))


def _mean(values: list[Decimal]) -> str:
    mean = (sum(values, Decimal(0)) / Decimal(len(values))).quantize(_QUANTUM)
    text = format(mean.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _downstream(compiled: CompiledGraph, nodes: set[str]) -> set[str]:
    successors: dict[str, set[str]] = {}
    for target, sources in compiled.activation_predecessors:
        for source in sources:
            successors.setdefault(source, set()).add(target)
    closure, frontier = set(nodes), list(nodes)
    while frontier:
        for successor in successors.get(frontier.pop(), ()):
            if successor not in closure:
                closure.add(successor)
                frontier.append(successor)
    return closure


def execute_paired_round(plan, *, items, baseline, candidate, evaluator, reset_root,
                         declared_changes, round_value) -> PairedRound:
    """Run both sides over the same frozen items in isolation and record the round.

    `round_value` carries the round's identity fields for the comparison record
    (`round_id`, `round_index`, `candidate`, `mandatory_checks`, `evidence`,
    `usage`); runs, validity and measurements come only from this execution.
    """

    if not is_frozen_plan(plan):
        raise PairedExecutionError("a frozen comparison plan is required")
    if type(items) is not list or not 1 <= len(items) <= MAX_ITEMS or any(
            type(item) is not dict for item in items):
        raise PairedExecutionError("the frozen queue items are out of bounds")
    canonical_json(items)  # the items are data, bounded and canonical
    for side in (baseline, candidate):
        if (type(side) is not PairedSide or type(side.compiled) is not CompiledGraph
                or not callable(side.handlers)):
            raise PairedExecutionError("each side needs its compiled graph and handlers")
    if baseline.label == candidate.label or not all(
            re.fullmatch(r"[a-z][a-z0-9-]{0,31}", side.label) for side in (baseline, candidate)):
        raise PairedExecutionError("the sides need two distinct plain labels")
    if not callable(evaluator):
        raise PairedExecutionError("a code-owned evaluator is required")
    declared = set(declared_changes)
    known = {node.node_id for node in candidate.compiled.nodes}
    if not declared or not declared <= known:
        raise PairedExecutionError("the candidate must declare the nodes it changed")
    root = Path(reset_root)
    if root.exists() and any(root.iterdir()):
        raise PairedExecutionError("the reset root must start empty")
    runs, changed, unexplained, reasons, metrics = [], [], [], [], {}
    scope = _downstream(candidate.compiled, declared)
    try:
        for index, item in enumerate(items):
            left = _run_isolated(root, baseline, index, item, plan)
            right = _run_isolated(root, candidate, index, item, plan)
            runs.append((left, right))
            before, after = dict(left.results), dict(right.results)
            differing = tuple(sorted(node for node in set(before) | set(after)
                                     if before.get(node) != after.get(node)))
            changed.append(differing)
            unexplained.append(tuple(node for node in differing if node not in scope))
            verdict = evaluator(item, left, right)
            if type(verdict) is not dict or set(verdict) != {"valid", "reasons", "metrics"}:
                raise PairedExecutionError("the evaluator answered outside its contract")
            if verdict["valid"] is not True:
                item_reasons = verdict["reasons"]
                if type(item_reasons) is not list or not item_reasons:
                    raise PairedExecutionError("an invalid item must state its reasons")
                reasons.extend(f"item {index}: {reason}" for reason in item_reasons)
                continue
            for name, value in verdict["metrics"].items():
                if type(value) is not str or _DECIMAL.fullmatch(value) is None:
                    raise PairedExecutionError("metrics must be exact decimal strings")
                metrics.setdefault(name, []).append(Decimal(value))
    except PairedExecutionError:
        raise
    except Exception as error:  # noqa: BLE001 - a run that failed is an invalid round, stated
        reasons.append(f"item {len(runs)}: run failed ({type(error).__name__})")
    complete = len(runs) == len(items)
    valid = complete and not reasons and all(len(values) == len(items) for values in metrics.values())
    if not complete and not reasons:
        reasons.append("not every item ran on both sides")
    vector = {name: _mean(values) for name, values in metrics.items()} if valid and metrics else None
    utility = vector.get("utility") if vector else None
    if not runs:
        raise PairedExecutionError("no item ran on both sides: " + "; ".join(reasons))
    value = {
        **round_value,
        "baseline_runs": [left.manifest_ref.as_dict() for left, _right in runs],
        "candidate_runs": [right.manifest_ref.as_dict() for _left, right in runs],
        "validity": "valid" if valid else "invalid",
        "validity_reasons": [] if valid else reasons,
        "metric_vector": vector,
        "utility": utility,
    }
    result = record_comparison_round(plan, value)
    return PairedRound(result, tuple(runs), tuple(changed), tuple(unexplained))


def remove_isolated_runs(reset_root) -> None:
    """Discard every isolated vault of a recorded round (their refs stay in the round)."""

    shutil.rmtree(Path(reset_root), ignore_errors=False)


__all__ = [
    "PairedExecutionError",
    "PairedRound",
    "PairedSide",
    "SideRun",
    "execute_paired_round",
    "remove_isolated_runs",
]
