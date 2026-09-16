# Evidence — T040 first slice: LangGraph scheduling adapter with ledger-reconciled visits

- Date: 2026-09-16
- Task: T040 [US3] first slice (resumption-plan.md Continuation: "T040's
  scheduler/ledger/worker integration") — `app/runtime/scheduler.py` maps a
  `CompiledGraph` onto a real LangGraph `StateGraph` with code-owned
  handlers, deterministic ledger-reconciled node visits, sealed router
  activations and opaque checkpoint cursors (runtime.md §2 compilation
  mapping, §4 visits/attempts; FR-013/FR-030). Tests live in
  `app/tests/test_graph_execution.py` (T039's file) as the actual scheduler
  execution and durable restart coverage that T039's reopening asked for.

## What was built

- **Closed handler registry** — `build_scheduler(compiled, *, ledger,
  run_id, handlers)` requires an exact `CompiledGraph`, an exact
  `RuntimeLedger`, and a handler dict whose keys cover every compiled
  handler key and stay inside the closed core namespace
  (`HANDLER_KEYS`); an unknown key (`core.shell`), a missing key or a
  non-callable refuses at build. Node kinds `human_gate` and
  `bounded_loop` refuse loudly as unsupported in this slice.
- **Compilation mapping** — nodes keep the approved node IDs; edges come
  from the compiled activation predecessors (`add_edge` per source, so
  the join fires once when its activated producers complete in the same
  superstep); entry nodes hang off `START`; terminal nodes go to `END`.
- **Ledger-reconciled idempotent visits** — each visit derives
  `execution_identity(run_id, node_id, loop_index)` (UUIDv5), records an
  `ExecutionSpec` through `ledger.create_execution` under a deterministic
  command ID (the ledger's own command replay makes re-runs and restarts
  reconcile instead of duplicating), passes handlers only a frozen
  `NodeContext` plus a detached results/counters view, requires an exact
  `EntityRef` result, and never re-executes a visit whose result is
  already durable in state.
- **Routers** — the handler returns one declared enum value; the
  matching control-edge target is sealed with
  `scheduling_state.seal_activation` before the branch runs and routed
  with a LangGraph `Command(goto=…)` (no ad-hoc edge); an undeclared
  decision activates nothing and fails the visit.
- **Opaque cursors, no streaming** — persistence is the existing
  `LedgerCheckpointSaver`; the scheduler never parses or exposes cursor
  bytes and offers no `stream` API. `run()` invokes with
  `durability="sync"`, resumes from the durable head when one exists, and
  returns only a bounded `SchedulerOutcome` (run/graph digest, completed
  node IDs, execution IDs, result refs, counters, activations).
- **Sanitized failures** — a handler exception becomes
  `SchedulerError("node_failed:<node>")`; the private error text never
  reaches the outcome, the exception or the checkpoint journal bytes.
- Reducers: result writes for one execution ID with different content
  conflict instead of last-writer-wins.

## Verification (8 tests, TDD — module absent first)

- Sequential chain: handlers run in order; every visit has a ledger
  execution whose spec node matches; execution IDs equal the
  deterministic identity; the outcome's field set is closed.
- Parallel entries fan in to one join visit.
- Router seals exactly the decided branch (activation ID is a UUID);
  an undeclared decision runs nothing after the router.
- Restart after a failure: the failed run leaks no canary; reopening the
  ledger and rebuilding the scheduler resumes without re-running the
  durable `intake` visit; the intake execution record is reused; no
  checkpoint cursor byte contains the canary.
- A completed run is idempotent on re-invocation (no handler calls, equal
  outcome).
- Registry closure and explicit unsupported kinds.
- Non-`EntityRef` handler results fail sanitized; no `stream` attribute.
- Handlers receive identity-only context (frozen) and a detached view
  whose mutation never reaches state.
- Ruff lint clean on both files; `ruff format` applied to the new module
  (the pre-existing test file keeps its original formatting).

## Limits (honest)

- Not whole T040/T039: no `bounded_loop`/`human_gate`, no retry within a
  visit, no attempt reservation/budget settlement/semantic admission, no
  worker dispatch; joins assume same-superstep completion of activated
  branches; sealed activations are reported from memory, not recovered
  from the journal. Real provider/worker execution and the browser
  journey remain open.

## Frozen identities

```
19ce7561cbd7eb7ca0419b749fdd72e2927e868a2a256c5889dcdc7e3ee982d0  app/runtime/scheduler.py
d1212a154432d1c4ca4a014824a66fb2d4b1dbcd9b7406aef6313e4f650b59c0  app/tests/test_graph_execution.py
```

## Iteration record

- Focused: scheduler + Task 23 + checkpoint suites **121 passed, 17.00s**.
- Final full regression is recorded below once run.
