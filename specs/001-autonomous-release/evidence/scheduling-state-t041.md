# Evidence — T041 sealed activation, atomic join winner, visit identity

- Date: 2026-09-13
- Task: T041 [US3] sealed branch activation, atomic join winner,
  visit-vs-attempt IDs and dependency-scoped failure in
  app/runtime/scheduling_state.py (runtime.md §2/§4).

## Frozen identities

```
85cf087344806d83d2820b7710e7c970b8bc656da51e7ef0bb021532caeb9063  app/runtime/scheduling_state.py
da3ce9c3e26b4aa4e2cef949afdecd6433246c4dd3577b5a13b3bbe928b9591f  app/tests/test_scheduling_state.py
```

## What was built

- `seal_activation` — the router's activation set freezes for one exact
  run/loop visit BEFORE any branch dispatches: bounded, nonempty, no
  duplicate branches; the activation id derives from
  run/router/visit/branches. A result from outside the sealed set never
  enters a join.
- `open_join` / `apply_branch_result` — the three contract modes:
  - `any_success`: one compare-and-swap decision — the first observed
    success wins and schedules the successor exactly once; an earlier
    observation arriving late re-points the same single decision; an
    observation-index tie breaks by the frozen branch-id ordering; later
    successes and every other terminal result remain recorded evidence
    that can never replace the sealed winner or double-schedule.
  - `all_selected`: completes only when every sealed branch is terminal;
    `skipped` is terminal and contributes no input (never a phantom).
  - `collect`: explicit reachable minimum required at open; completes at
    the minimum or when all branches report; inputs in frozen order.
  - A branch can never report twice; unknown statuses refuse.
- `visit_identity` / `next_attempt` — a repeat visit (new loop index) is
  a NEW visit, never a retry; attempts index retries of one exact visit.
- `blocked_dependants` — a required producer failure blocks exactly its
  dependants; independent branches proceed.
- Issued-value pattern; join states evolve only through application.

## Verification

- TDD: module absent first (collection error); 8 tests green
  (seal freezing, CAS winner, tie-break, all_selected with skipped,
  dependency scoping, duplicate/late immunity, visit-vs-attempt, collect).
- `ruff check` clean; full regression **3237 passed, 2 skipped**
  (was 3229).

## Notes

- T040 (the LangGraph scheduling adapter with persistent cursors) sits on
  top of this state module; the langgraph dependency is not yet added —
  that adapter is the next US3 runtime slice, along with T039's broader
  execution-pattern test file.
