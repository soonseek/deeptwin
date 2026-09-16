# Evidence — owner-recorded run approvals and scheduler human gates (T040 slice 3)

- Date: 2026-09-16
- Scope: `app/services/run_approvals.py` (new) — the first real producer
  of `action_approval` records — and `human_gate` support in
  `app/runtime/scheduler.py` (runtime.md §2 approval edges / §4
  `awaiting_human`; FR-026 authenticated human approval; the
  resumption ruling that a caller-declared boolean is never approval
  evidence).

## Why this slice

Every earlier consumer of `action_approval` (promotion, environments,
retention, knowledge, tools) referenced the record by fixture ref;
nothing in the codebase ever produced one. A human gate implemented on a
handler-returned reference would therefore have repeated the pattern the
2026-09-15 reconciliation reopened T064/T065 for. The persistent owner
session from Task 7 is the only authenticated human authority available,
so the approval writer is built on it.

## What was built

- **`PersistentRunApprovals(domain_store, owner_authority)`** — binds the
  exact `DomainStore` and `PersistentOwnerAuthority` (identity-checked,
  as the candidate registry does).
  - `record(request, payload)`: closed command
    `{schema_version: run-approval-command-v1, command_id, run_id,
    node_id, approval_scope, decision: approved|rejected}` validated
    before any work; a POST with verified CSRF, exact host and origin;
    `authenticate_bound` re-run inside the final writer (`_writer()` +
    the store's write connection). One immutable `action_approval`
    record per (run, node, scope) — identity
    `uuid5("deeptwin:run-approval:<run>:<node>:<scope>")` — with content
    `{schema_version: run-approval-v1, run_id, node_id, approval_scope,
    decision, command_id, decided_at_utc, event_sequence}`, authored by
    the owner's human actor ref (never the system root), plus the
    `approval.decided` public event (`decision` only) in the same
    transaction. Exact replay of the same command returns the same
    receipt; a different command or decision for the same key conflicts
    and never overwrites.
  - `lookup(run_id, node_id, scope)`: resolves the record through
    `domain_records` (kind, id) → exact `EntityRef` → store load, and
    returns the frozen `RunApproval` or `None`; a record whose content
    disagrees with its key is `unavailable`.
- **Scheduler `human_gate`** — gate nodes compile with a static
  `interrupt_before`; `run()` checks pending gates BEFORE every resume:
  all scopes approved → resume (the consumed refs appear in
  `outcome.approvals`); any rejection → `SchedulerError
  ("approval_rejected:<node>")` with the gate never executed; any
  absence → `outcome.awaiting_human == ((node, scope), …)` and no
  invoke. The gate body re-verifies every scope as defense in depth. A
  gated graph refuses to build without the exact
  `PersistentRunApprovals`; an ungated graph refuses one.

## Verification (TDD)

- RED: both test modules failed on the absent service, then GREEN.
- `app/tests/test_run_approvals.py` (17): durable record + event +
  human actor ref + lookup keying; exact replay vs. conflicting
  decision/command; GET/CSRF/origin/host refusals before any write;
  closed payload validation (9 shapes) before any write; a failing
  event write rolls the record back with no canary leak; exact
  store/authority binding.
- `app/tests/test_graph_execution.py` (+4, 26 total): a gate waits for
  the owner (twice) and runs after the recorded approval with the
  consumed ref reported; a rejection fails the gate without running it;
  approvals are keyed by run/node/scope (other run, other scope, other
  node do not unlock); a gated graph requires the real service.
- Focused suites (graph execution, approvals, checkpoints, web owner
  integration, candidate persistence, graph contract): **265 passed**.
- Ruff lint/format clean on the new/changed modules; diffcheck clean.
  Authoring fixes: event timestamps need the 6-digit UTC form; the
  supported server reconciles its ledger only when worker dispatch is
  configured, so the gate fixture performs that startup step itself;
  `run()` must consult approvals before resuming past a static
  interrupt.

## Frozen identities

```
52452d778f07ac9f5ed73e2edc8414456809c4bf34f83a6e068d5c8c2333cf3f  app/runtime/scheduler.py
a791de23af489cd0fa269011b9129fab8110bedd189d43f0b4fb8063e7f52084  app/services/run_approvals.py
4f6e630abfacca86d478d858a814605ab1cbb28bb6f077d582623253b95e3391  app/tests/test_run_approvals.py
1a92f3d5ba92a43e4861ee38ecc23185d3f545b68639c53a31980638745f689b  app/tests/test_graph_execution.py
```

## Limits

- No HTTP route exposes `record` yet (the API/UI wiring is a later
  slice); no `approval.requested` event is emitted when a gate starts
  waiting; consumed approvals are reported from memory, not the journal;
  promotion/environment approvals (T065) still validate their own
  `action_approval` refs and are not yet routed through this producer.
