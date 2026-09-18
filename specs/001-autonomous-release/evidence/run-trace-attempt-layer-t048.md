# Evidence — the run trace's attempt layer (T048/T055)

- Date: 2026-09-18
- Task: T048 [US3] "keep past attempts distinct (UX-AC04/10)" on the read side — the run trace
  (T055 reopened scope, `run_trace.py`) now carries each visit's attempts as the ledger recorded
  them and attributes the durable result to the one attempt the bound checkpoint row names
  (`checkpoint-attempt-binding-t040.md`: "the run trace's attempt layer is T048's"). experience.md
  §7: a past attempt never carries a later result.

## Frozen identities

```
c8487f8f613c5e460e4d9a19a6c65e144009a180fe22945f7584249401f9682d  app/services/run_trace.py
a3a2b11a4bb7108db6e08027ea488bd4359892526975f6013aa151f49b6552bd  app/runtime/ledger.py
f1139417acb6aae39e863c46362f74b56de13fbceb29d1fbcb0cd24ddfce29cc  app/tests/test_run_trace.py
bc59774d430a24c720f33ba644d214fa83f70ab1707e862366f93e7d13abd25a  app/tests/test_runtime_ledger.py
```

(The `ledger.py` and `test_runtime_ledger.py` identities frozen in `checkpoint-attempt-binding-t040.md`
are superseded; `run_trace.py` had no earlier frozen identity in this line.)

## What was built

- `app/services/run_trace.py`: `TraceAttempt` (attempt id and number, phase, terminal outcome,
  remote terminal observation, usage finality, cancel state, `produced_result`,
  `bound_revision`) and, on `TraceExecution`, `attempts` and `producing_attempt_id`. Three honest
  states: no attempts (a handler-produced visit), a result attributed to exactly the attempt the
  bound row names, or attempts beside a result that no bound row names (a result produced
  outside the dispatcher, e.g. a plain-handler resume after a failed attempt) — then no attempt
  claims it. The read is one closed boundary: the journal head, the head revision, the bound rows,
  the attempts and the executions are read inside one `try`, and every ledger or storage failure
  (a session refusal, a missing row, a corrupt binding, a raw storage error) is `RunTraceError`
  without its detail. Results come from the head's merged `results` channel **and** the head's
  pending writes on that channel, so a result the journal preserved in a bound pending-writes
  row whose merging checkpoint never committed (a crash between `put_writes` and `put`) is the
  visit's result — attributed, and not an observation gap.
- `app/runtime/ledger.py`: `bound_checkpoints_for_run(run_id, namespace)` — the read-only
  enumerator of the run's bound rows as `(revision, bound_execution_id, bound_attempt_id)`, read
  and re-verified in one transaction through the same `_checkpoint` check every other read uses
  (the binding still matches the attempt's exact state and the execution is this run's);
  bounded by `MAX_CHECKPOINTS_PER_NAMESPACE`; unknown run → `KeyError`; no session gate (a
  read grants nothing).

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (1 MUST, 3 SHOULD, 3 NIT). Verified by the reviewer: the dispatch
happy path, the unsent continuation and the recovery retry each attribute the result to the
attempt that actually produced it; a handler-produced visit has no attempts and attributes
nothing; a restart reproduces the attribution; the outcome field set is unchanged. Closures,
RED-first:

1. MUST — the new per-revision loop called `checkpoint_for_replay` outside the `try/except
   CheckpointError`, so a session refusal, a corrupt bound row or a missing revision leaked the
   ledger's own exception (and its message) from a read-only trace → one closed read boundary;
   the RED test monkeypatches three ledger readers to raise `DispatchBlocked`, `KeyError` and a
   raw `RuntimeError` and asserts `RunTraceError` without the private text.
2. SHOULD — the loop read every revision of the journal one transaction each (N reads, N
   validations, no isolation between them) → the ledger's `bound_checkpoints_for_run` returns
   the bound rows in one transaction; the trace performs one head read for the revision.
3. SHOULD — a crash between the bound pending-writes row and the merging checkpoint left the
   result attributed (`produced_result` True) but `result_ref` None and the execution listed as
   an observation gap → results are taken from the head's pending writes as well; the RED test
   crashes the saver's append on the checkpoint that follows the writer's bound row and asserts
   the reference, the attribution and no gap.
4. SHOULD — the three states were implicit → documented on `TraceExecution` and pinned by a
   test whose writer's sent attempt failed under the dispatcher and whose resume ran a plain
   handler: the result exists, the failed attempt stays `produced_result` False,
   `producing_attempt_id` is None.
5. NIT — ruff format drift (a ternary) → formatted. 6. NIT — the loop variable renamed
   (`row_revision`). 7. NIT — the map semantics stated in a comment (one bound row per execution
   by the registry; a later row would win; the ledger guarantees the execution is this run's).

## Verification

- TDD: RED retained — `attempts`/`producing_attempt_id` absent from the field pin,
  `AttributeError` for `TraceAttempt`; GREEN after the dataclass, the bound-row map and the
  attempt grouping; the review's RED tests failed for their stated reasons
  (`AttributeError: 'RuntimeLedger' object has no attribute 'bound_checkpoints_for_run'` on the
  leak test, `result_ref` None beside `produced_result` True on the crash test); the mixed-state
  test pins existing behaviour by design (a documentation pin, stated).
- Tests: run trace **+4** (the attempt layer attributes the result to the producing attempt,
  survives a restart and the field pin; ledger failures are trace errors; a result preserved
  only as a pending write is attributed and not a gap; an unattributed result is not
  misattributed); ledger **+1** (`bound_checkpoints_for_run`: unknown run, empty, revision
  order with unbound rows skipped, namespace scoping, argument bound, a tampered row refused
  without mutation). Covering (run trace, ledger, dispatch, checkpoints, graph execution, runs
  API, web owner integration): **252 passed**. Ruff: clean on the trace and both test files;
  `ledger.py` 18/18 pre-existing (no new finding); `ruff format --check` clean on the trace.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- Read-only: no dispatch, result, recovery or replay authority; no raw channel state or cursor
  bytes leave the trace (only `EntityRef` results); the outcome field set is unchanged. No model,
  tool or paid call. The DOM half of T048 (the run view wired against the supported routes) and
  the browser E2E (T049; playwright not installed on this host) stay open; the trace's attempt
  layer is not yet presented by a route (T055's slice routes stay as they were).
