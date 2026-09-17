# Evidence — restart-invariant scheduler projection (scheduler review F9)

- Date: 2026-09-18
- Scope: T040 scheduler outcome projection. Closes review finding F9 of
  2026-09-17 ("consumed approvals and sealed activations are process memory,
  lost on restart"). T040 stays open (worker dispatch integration).
- Builds on: `scheduler-t040-slice1.md`, `gate-approval-requests-f6.md`.

## Frozen identities

```
d156da83a1b061260cf928a75cd8c240f3dbfc5d70508ff1a731e93f4372b7be  app/runtime/scheduler.py
cf40aaa4db8795d6faa91e35ed2a36f35ec9952bab67390ae49620781c9bbfea  app/tests/test_graph_execution.py
```

## What was built

- `GraphScheduler._project` no longer reads the in-memory `_consumed` and
  `_activations` collections (both removed from the instance):
  - `_consumed_approvals(counters)` re-reads, for every human gate whose
    visit counter is positive, the owner's durable `action_approval` record
    per scope through `PersistentRunApprovals.lookup`; a gate that ran
    without an approved record projects `SchedulerError("approval_missing")`
    and an unreadable record projects `SchedulerError("approval_unreadable")`
    — the approvals service's own errors never cross the scheduler boundary.
    "Consumed" now means the gate actually ran (before, the refs were
    reported as soon as the gate check found them).
  - `_sealed_activations(raw_counters)` rebuilds `(router, activation_id,
    branches)` from the durable `<router>.activation.<target>` markers in
    the closed counters channel by re-running `seal_activation` over the
    same run, router, visit and branch inputs (its identity is a pure
    digest of those); a router counter above one is refused loudly
    (`router_revisited`) because last-writer-wins markers could not carry a
    second visit — today the compiler and builder already make that
    impossible.
- Router nodes still seal the activation before dispatch (validation); the
  router branch map is computed once per scheduler and reused.
- Module docstring updated: the projection is restart-invariant.

## Review (independent, adversarial) and closures

Verdict on the first cut: ACCEPT. Folded in RED-first / before commit:

1. SHOULD — `run()` could raise `RunApprovalError` from `_project`
   (outside the try block that normalises failures) → lookups are wrapped;
   test injects an unavailable approvals reader and expects `SchedulerError`.
2. SHOULD — stale "reported from memory" docstring → rewritten.
3. NIT — partial projection if routers were ever revisited → explicit
   `router_revisited` refusal.
4. NIT — restart tests did not prove nothing re-ran → both assert the second
   scheduler made zero handler calls (the router test also reopens the store).
5. NIT — `_router_branches` computed three times → once.

## Verification

- TDD: both recovery tests RED (`assert () == (...)`), then GREEN; the
  error-contract test RED (`RunApprovalError: unavailable` escaped), then GREEN.
- Covering command (scheduler, run trace, run approvals): **59 passed, 1
  inherited warning**; after the last refactor (scheduler, run trace):
  **38 passed**. Ruff clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No route/GUI change; no model/tool/paid call; no publication; no license
  decision. Retry-within-visit, attempt reservation, budget settlement and
  semantic admission remain open per Continuation.
