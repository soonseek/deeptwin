# Evidence — T039: scheduling-pattern tests

- Date: 2026-09-13
- Task: T039 [US3] sequential/parallel/router/closed-join/loop/retry/
  restart scheduling tests in app/tests/test_graph_execution.py (R02;
  R07/R08's crash/cancel substrate is exercised by the pre-existing
  test_runtime_ledger suite — reserve/send-intent/observation/
  startup-reconciliation — and is not duplicated here).

## Frozen identity

```
80fc9d39278a9c6c9794579a8412d2452db0e7b13936a99edd730362a54cf04f  app/tests/test_graph_execution.py
```

## Patterns proven (7 tests over the audited scheduling primitives)

- **Sequential** — each stage's successor gate opens only when its
  producer's single-branch join is terminal; nothing runs ahead.
- **Parallel** — branches progress independently inside one seal; a
  required failure never hides (completed with `satisfied=False`) and
  never blocks the other branches' own completion.
- **Router/conditional** — the sealed subset IS the decision: a
  statically-possible but unactivated branch can never report, and a
  failed activated branch blocks exactly its dependants.
- **Closed join / collect** — collect gathers its explicit minimum in
  frozen order regardless of arrival order; the sealed decision never
  grows from late successes.
- **Bounded loop** — every iteration is a NEW visit with a NEW activation
  identity; the loop-index hard cap refuses runaway loops.
- **Retry vs repeat** — attempts index retries of ONE visit (0,1,2…)
  under a retry cap; a repeat visit is a different identity, never
  attempt N+1 (R02).
- **Restart** — replaying the recorded evidence in recorded order
  reconstructs the identical winner/inputs/completion (the frozen-order
  tie held through the replay), and late duplicates stay refused after
  the rebuild.

## Verification

- Pure test slice over existing audited primitives — no production code
  changed. `ruff check` clean; full regression
  **3314 passed, 2 skipped** (was 3307).
