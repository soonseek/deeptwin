# Evidence — human-gate approval requests bound to real runs (scheduler review F6)

- Date: 2026-09-18
- Scope: T040 human gates (runtime.md §2 approval edges, §4 `awaiting_human`).
  Closes review finding F6 of 2026-09-17 ("approvals are not bound to a real
  run/target; nothing emits `approval.requested` when a gate starts waiting").
  T040 stays open (worker dispatch integration).
- Builds on: `run-approvals-human-gate.md`, `scheduler-t040-slice1.md`.

## Frozen identities

```
fabedf1e744e5c1924f3ebd7cc8c9fa1c397e9d09563e442ef8679e8210cd582  app/runtime/gates.py
6a65a4ec979ee1cd9647fa6d22929b711a74bd60c2324c71df4171b0b432b496  app/runtime/ledger.py
a68e3a3814bf1db8d947ad7fb61a00f2cf0370c108a0f25834df060bfd0273ce  app/runtime/scheduler.py
ca3be64c5e1900b9335069b3aea96b6339d1f933e6b843326a01808357e5f56f  app/services/run_approvals.py
587af96bcab8fa10ded56052ae8981be74441c3b873f5da610da4998867372ba  app/tests/test_run_approvals.py
d4668bdfb3b55a2a6601d27d4c8f8730514b5e9b0b4959af02977e644cf2a2d6  app/tests/test_run_approval_api.py
0c6305fa3c464759463ba9c3f8307e8db50c7ac7e6c41adfd660a3210d4ea904  app/tests/test_graph_execution.py
19e83ca4d0b80926b9826aa67b56e3fcabafe6bf6772bc156f64cd9e73c324d5  app/tests/test_runtime_ledger.py
```

## What was built

- `app/runtime/gates.py` — `gate_request_identity(run_id, node_id, scope)`
  (uuid5 over canonical JSON; delimiter-proof), the shared `LOCAL` grammar
  for node ids and scopes, and `gate_request_recorded(db, vault_id, …)`, the
  single reader of a request row used by the ledger and the approvals
  service alike.
- `RuntimeLedger.request_gate_approval(run_id, node_id, scope)` — one
  replayable command per (run, node, scope) whose command id IS the derived
  identity, so the same ask can never be recorded twice; requires the run
  to exist (`KeyError`); emits one public `approval.requested` event
  (object `run`, `{"approval_kind": "run"}`) on first recording; exact
  replay returns the stored result and emits nothing. `gate_approval_requested`
  reads it back. No schema change: the request lives in `runtime_commands`.
- `GraphScheduler._gate_status` — when a gate scope has no recorded
  approval, the scheduler records the request before reporting
  `awaiting_human`; waiting again, resuming, a second scheduler instance or
  a process restart replay the same command (request + event are one
  `BEGIN IMMEDIATE` transaction under the global writer lock).
- `PersistentRunApprovals.record` — after authentication, command
  validation and the existing-approval replay path, refuses
  `invalid gate: no pending approval request` unless the ledger holds the
  request for exactly (run, node, scope). The ledger's vault id is the
  domain genesis id, so the service reads the same SQLite database; a vault
  without a ledger fails closed as `unavailable`. The route maps the refusal
  to 400 `invalid_input`.

## Review (independent, adversarial) and closures

Verdict on the first cut: ACCEPT. Folded in RED-first / before commit:

1. SHOULD — the scheduler-level "keyed by run/node/scope" property lost its
   coverage (decoys were refused before existing) → decoy gates are now
   genuinely requested, their approvals recorded, and the scheduler still
   waits on this run's gate and scope; the refusal loop is kept.
2. SHOULD — the service duplicated the ledger's `runtime_commands` SQL while
   the ledger's reader was test-only → both use `gates.gate_request_recorded`.
3. NIT — duplicated local-identifier grammar → the service imports `LOCAL`.
4. SHOULD (documented, not changed) — `approval.requested` carries only
   `approval_kind` (closed catalog) and no read lists pending requests per
   run; the owner GUI still renders pending gates from the scheduler outcome
   (`approvals.mjs awaitingHumanView`). A `pending_gate_requests(run_id)`
   read is a follow-up.
5. SHOULD (documented) — gate requests never expire: runs have no retired
   phase in the ledger; a late approval only matters once a scheduler resumes
   and a second decision conflicts. The ledger does not check the compiled
   graph; only the scheduler, which knows it, records requests.

## Verification

- TDD: `ImportError` on `gate_request_identity` first; then GREEN; the
  derived-identity contract change (caller command id removed) RED on the
  ledger unit test, then GREEN.
- Covering command (run approvals + API, scheduler, runtime ledger, run
  trace, web owner integration): **181 passed, 1 inherited warning**;
  after review closures (approvals, API, scheduler, ledger, trace):
  **101 passed**. Ruff clean on new/changed files; `ledger.py` keeps its
  14 pre-existing ISC004 findings (other pre-existing findings reduced).
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No route/GUI change; no model/tool/paid call; no publication; no license
  decision. T040 worker dispatch integration and the semantic
  acceptance + budget settlement transaction remain open per Continuation.
