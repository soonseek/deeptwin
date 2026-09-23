# Evidence — T039 closed: retry inside one visit over the real scheduler (2026-09-23)

- Task: T039 — "sequential/parallel/router/closed-join/loop/retry/restart scheduling tests in
  app/tests/test_graph_execution.py". Real StateGraph + SQLite coverage for sequential,
  parallel, router, closed join, bounded loop and restart landed with the 2026-09-16 scheduler
  slices (evidence/scheduler-t040-slice1.md); the value-level `test_a_retry_stays_inside_one_visit`
  covered retry identities only. The recorded gap was retry within a visit on the real scheduler.
- Added: `test_a_retry_inside_a_loop_visit_is_the_next_attempt_of_that_visit` in
  `app/tests/test_graph_execution.py`, over the real `build_scheduler`, `NodeAttemptDispatcher`,
  `RuntimeLedger`, `BudgetBook` and the compiled `loop_graph()` (seed → loop ⇄ revise → done, cap 5),
  with an in-process transport (no worker, provider or paid call).

## What it proves

1. The loop's second `revise` visit (loop index 1) fails its first attempt with an observed
   terminal failure: the run fails `node_failed:revise`; the sends are exactly
   `[revise/0 attempt 0, revise/1 attempt 0]`.
2. A fresh process (every store reopened, `reconcile_startup`) and a plain resume re-send
   nothing.
3. The owner's recovery (`retry_after_terminal=True`) sends `revise/1 attempt 1` — the next
   attempt of the **same** execution identity — and nothing else; iteration 0 is never re-run;
   the loop proceeds to its third controller visit and `done`.
4. The visit's result is the retried attempt's accepted result; the failed attempt stays
   `failed` and `attempt_no` 2 names the same `execution_id`; iteration 0's attempt stays
   `succeeded`. Counters are `{seed: 1, loop: 3, revise: 2, done: 1}` — a retry is not a visit.

## Verification

- `pytest app/tests/test_graph_execution.py -k retry_inside_a_loop`: 1 passed (Linux, Python 3.12.3).
- The test composes existing behavior (the recovery retry landed 2026-09-18,
  evidence/run-recover-route.md); it adds no product code, so it has no RED phase of its own.
