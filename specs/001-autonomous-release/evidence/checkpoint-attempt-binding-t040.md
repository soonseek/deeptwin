# Evidence — T040: checkpoint↔attempt binding (the task's last open item)

- Date: 2026-09-18
- Task: T040 [US3] — "checkpoint↔attempt binding before T040 can be marked complete"
  (`tasks.md`; `scheduler-attempt-dispatch-t040.md` "Checkpoints stay unbound to attempts (a
  separate decision)"). runtime.md: startup reconciles recorded attempts and checkpoint cursors
  before new dispatch (R07: a crash after reserve/send/result/checkpoint loses no committed
  result and duplicates no effect); `NodeExecution` is one logical visit, `Attempt` a retry of it.

## Frozen identities

```
a65fd7b5b1d0d8b46c533b669cee3cb9338cc3e831290737dc861a877d268578  app/runtime/checkpoints.py
5d7cb09b88a95f790365ce29524e8743a430593198492a9cf94939b3645c0591  app/runtime/node_attempts.py
6183c70c445dccf9bf693a27de9909a81ad0c914eb14691e7b811cb245134b2b  app/runtime/scheduler.py
8e23db3b3bcdb5336c2904bba0fb77ecbf7d76d65bdb737178d5f85ec0402a10  app/runtime/ledger.py
25122329397bfb8dc6352ac7a9328b0b7d3de46750bc7720637d67f31ff8f8a9  app/tests/test_langgraph_checkpoints.py
3c76122c9e784fe22258ee22a9c4f417a19e31163a32dda785f33c9cb53fbdf2  app/tests/test_scheduler_attempt_dispatch.py
039f5ddacac29dc6c5fab2e1e5ac5d67c9761f867f92b1e14ee00b56803dfc26  app/tests/test_runtime_ledger.py
```

(The `ledger.py`, `scheduler.py`, `node_attempts.py`, `checkpoints.py` and test identities frozen in
the earlier T040, cancel, recovery and projection-recovery evidence files are superseded.)

## What was built

- `app/runtime/checkpoints.py`: `AttemptBindings` — the per-run, in-memory registry of which
  accepted attempt produced which execution's result (one attempt per execution; bounded by the
  journal's record limit). `LedgerCheckpointSaver(..., attempt_bindings=)` binds each
  pending-writes row that carries exactly one `results` write naming exactly one registered
  execution to that attempt through `write_checkpoint(attempt_id=)`; every other row (the merging
  checkpoint, counters-only writes, unregistered executions) stays unbound — a guessed or partial
  binding would be a permanent integrity failure.
- `app/runtime/node_attempts.py`: the dispatch returns the accepted attempt with the result;
  `VisitAttempt.accepted_attempt` names it once `dispatch()` committed.
- `app/runtime/scheduler.py`: `build_scheduler` creates the registry when a dispatcher is bound
  and hands it to the saver; after the visit's `committed == result` gate the execution is
  registered with its accepted attempt. `SchedulerOutcome` is unchanged.
- `app/runtime/ledger.py`: the ledger already derived the four bound columns from the attempt
  (its revision at write, its execution, its envelope digest) and re-verified them on every read;
  it now re-verifies **every bound row** of the run — not only the journal head — on the next
  `reserve_attempt` of the run and at startup for runs with a live attempt
  (`_validated_bound_checkpoints`, bounded).

What the binding guarantees: each journal row that first carries a bound node's accepted result
names the attempt id, that attempt's revision at write, its execution id and its envelope digest;
the ledger refuses any read, the run's next attempt and startup when a binding no longer matches
the attempt's exact state; the scheduler cannot be rebuilt over a tampered bound row. Nothing
presents the binding yet (no consumer in `app/services` or `app/api`): the run trace's attempt
layer is T048's.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (0 MUST, 3 SHOULD, 3 NIT), 29 scratch probes. Verified: langgraph
commits a task's pending writes only after the node returned and the registry was set (20/20
deterministic, no window for an unbound-but-registered row); a crash between the acceptance and
the row commit replays the send as `None`, resolves the committed result without any transport
call and writes the row bound at the attempt's current revision; two bound visits in one
superstep and a loop's two visits bind their own attempts; the unsent continuation and the
recovery retry bind the attempt that actually produced the result. Closures, RED-first:

1. SHOULD — the ledger's reserve/startup check covered only the journal head, and a bound row is
   never the head after a completed superstep, so a tampered non-head binding passed both → every
   bound row of the run is re-verified (`_validated_bound_checkpoints`) on the next reserve and at
   startup.
2. SHOULD — the tamper refusals had no tests anywhere → the ledger suite pins, for a revision
   ahead, another execution, another envelope digest and a partial binding: refused on read, on
   the next reserve and at startup; the dispatch suite pins that a tampered bound row refuses the
   next scheduler build.
3. SHOULD — the docs did not close the item → `tasks.md` marks T040 complete with this evidence;
   the dispatch evidence's "unbound" sentence is superseded here.
4. NIT — the registry docstring overstated "first carries" → "each row that carries exactly that
   execution's result". 5. NIT — the registry is bounded by the journal's record limit. 6. NIT —
   the row's result and the bound attempt's accepted result agree by the scheduler's gate
   (`committed == result` before registration); a ref-level assertion in the saver stays optional.

## Verification

- TDD: RED retained — `AttemptBindings` absent, the happy path's bound rows empty, the
  capability without `accepted_attempt`; GREEN after the registry, the saver binding, the
  dispatcher's accepted attempt and the scheduler wiring; the review's RED tamper tests failed
  (accepted on reserve and startup) before the ledger's bound-row validation.
- Tests: checkpoints **+1** (a registered execution's pending-writes row bound with the four
  columns; unregistered, counters-only and merging rows unbound; the bound row replays on reopen;
  a foreign-run attempt halts the saver without committing; a wrong registry refused); dispatch
  (the happy path binds attempt index 0 and the capability names it; the unsent continuation
  binds index 1; a tampered bound row refuses the next build); ledger **+4** (tamper refusals
  everywhere). Covering (ledger, checkpoints, dispatch, graph execution, budget dispatch, run
  trace, runs API): **185 passed**; web owner integration and cancel **145**. Ruff: no new
  findings (ledger 18/18), the rest clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No raw state: the binding adds identities and a digest to a row; cursor bytes stay out of
  command payloads; `SchedulerOutcome` gains nothing; nothing reaches the API or the trace yet.
- The saver's command id stays random: replay safety is the revision CAS and the prefix digest.
- T040's listed items are all closed (scheduler, gates, gate requests, settlement, dispatch,
  retry after a sent attempt, checkpoint↔attempt binding); the real worker operations beyond
  `status`, the run trace's attempt layer and the browser E2E stay with T087 / T048 / T049.
