# Evidence — T087: the owner route for execution-bound (v2) approvals

- Date: 2026-09-25
- Status: **landed (one slice), T087 not closed.** Offline only; no model, tool, network or paid
  call; no live test run.
- Task: items left open by `tool-execution-binding-t087-2026-09-25.md` "Still open": no HTTP route or
  UI recorded a `run-approval-v2` decision, and no decision was bound to the attempt's exact inputs.

## What landed

### 1. The ledger's own ask for one attempt's decision

- `app/runtime/gates.py`: `EXECUTION_APPROVAL_REQUEST_COMMAND` (`request_execution_approval`),
  `execution_approval_request_identity(run, gate node, scope, execution id, attempt no)` (uuid5 of
  canonical JSON under `deeptwin-execution-approval-request-v1`), and the single readers
  `execution_approval_request(...)` / `execution_approval_requests(db, vault, run)`, which re-derive
  each row's identity and grammar from its own payload and refuse a row that does not reproduce it.
- `app/runtime/ledger.py`: `RuntimeLedger.request_execution_approval(run, gate node, scope,
  execution id, attempt no, *, inputs_digest=None)` records one replayable `runtime_commands` row per
  attempt, only when the ledger holds the gate request for (run, gate, scope) and the execution row
  belongs to the run; the **executing node is read from the ledger's execution row**, never taken
  from the caller; the attempt number must be one the execution holds or its next; the optional
  `inputs_digest` is `tool_inputs_digest(...)` (new: sha256 of the canonical ordered input
  declarations — the same computation the ledger uses for a ToolCall's `inputs_digest`). The same
  identity with another digest is a `CommandConflict` (one attempt, one ask, one digest).
  `execution_approval_requested(...)` reads it back. No DDL change (a new command kind in the
  existing table), so the ledger schema digest is unchanged; no event is emitted (the gate's
  `approval.requested` stands).
- `ExtensionAttemptTransport.artifact_inputs_digest`: the digest of the exact declarations the
  transport will send — what a dispatcher names in its ask.

### 2. The owner route

- `app/services/run_approvals.py`:
  - `record_execution(request, payload)`: owner-only (the same `_authenticate_owner`: POST, verified
    CSRF, exact host and origin, live session re-checked inside the writer). The payload is a v2
    command plus the `inputs_digest` the listing reported. Inside the one writer transaction every
    named field must equal the ledger's held ask for that attempt (gate node, scope, execution id,
    attempt number, **executing node**, **inputs digest**) and the ledger's execution row (run and
    node); otherwise `invalid` and nothing is written. The v2 record additionally carries
    `execution_request_id` (the ask's identity) and the ask's `inputs_digest`, copied from the
    ledger, not the client. Replay by the same command id returns the same receipt; the same
    attempt under another command or decision conflicts.
  - `execution_requests(run)`: every ask of the run with its state — `pending`, `approved`,
    `rejected` (a current decision, with its reference) or `superseded` (decided before the latest
    owner recovery).
  - `record` (the in-process v1/v2 command) is unchanged in behaviour; `_load` reads the two new
    optional v2 fields and refuses a malformed or partial pair, and a v1 record carrying them.
- `app/api/run_approvals.py` + `route_contributions/run-approvals-v1.json` (same contribution,
  same preflight seam in `web_boundary`): `POST /api/v1/runs/{run}/approvals/executions`
  (`runs.execution_approvals.record`, `approval.manage`, closed 8-field JSON body, 4 KiB) and
  `GET|HEAD /api/v1/runs/{run}/approvals/executions` (`runs.execution_approvals.read`,
  `approval.read`, no body). Installed route count 73 → 75 (`test_first_party.py`,
  `test_web_owner_integration.py` updated).

### 3. Dispatch: the decision must answer this attempt's ask and inputs

`ExtensionAttemptTransport._verify_execution_approval`, after the existing v2 lookup and before the
channel, the connection and the ToolCall intent: when the ledger holds an ask for this attempt, the
decision must name that ask (`execution_request_id`), carry the ask's digest, and the ask's
executing node must be the execution's; when the decision carries a digest it must equal
`artifact_inputs_digest`. Otherwise `transport_invalid` / `definitely_not_sent` (a ledger fault:
`transport_unavailable`). A v2 decision recorded without an ask (the in-process `record`) still
dispatches where the ledger holds no ask — the pre-existing behaviour — but is refused where it does.

### 4. UI logic

`app/static/approvals.mjs` (logic only, like the rest of the module): `executionApprovalRoutes`,
`executionRequestsView` (closed projection of the listing: one entry per attempt), 
`executionApprovalPrompt` (text naming the gate, execution id, executing node, attempt number and
digest), `executionApprovalCommand` (the POST body built only from a pending listed entry, fields
echoed verbatim), `attemptAuthorized` (true only for an approved entry of that exact attempt).

## Tests (observed)

- New `app/tests/test_execution_approval_route.py` — **21 passed**: listing → owner POST → v2 record
  with the ask and digest → listing `approved`; replay returns the same receipt; another command or
  decision 409; forged execution id / executing node / attempt number / gate / scope / digest /
  hidden digest each 400 with nothing written (7 cases); closed grammar (7 cases + missing field);
  wrong CSRF, missing CSRF, foreign origin, no session (GET and POST) refused; a retry attempt is
  refused under attempt 1's decision and passes the verification only under its own ask and
  decision (the connection is reached); a decision whose ask carried other inputs is refused at
  dispatch; a decision recorded beside the ask is refused at dispatch; a decision superseded by a
  recovery is listed `superseded` and refused at dispatch; the ledger's ask refuses no gate, a
  foreign/missing execution, a skipped attempt number, a bad digest, and conflicts on a changed
  digest.
- Mutation check (manual, reverted): disabling the service's ask comparison fails the 7 forged-field
  cases; disabling the transport's ask/digest checks fails the digest and beside-the-ask cases.
- New `app/tests/approvals-execution.test.mjs` — **4 passed** (`node --test`); with
  `approvals.test.mjs` and `runtime.test.mjs`: **29 passed**.
- Required set (`test_run_approvals.py test_run_approval_api.py test_tool_execution_binding.py
  test_extension_attempt_transport.py test_owner_sessions.py test_web_owner_integration.py
  test_first_party.py`): baseline **205 passed**; after, with the new file, **226 passed**
  (205 + 21).
- Adjacent set (`test_compiled_tool_dispatch test_domain_events test_graph_contract
  test_implementation_matrix test_owner_decisions test_promotion_approvals test_run_consents
  test_runs_api test_runtime_ledger test_runtime_ledger_migration test_scheduler_attempt_dispatch
  test_server test_web_shell_assets` + the new file, `-k "not live"`): **1107 passed, 1 failed,
  13 deselected** — the failure was one more installed-route-count pin (`test_runs_api.py`, 73);
  it and the same pin in `test_provider_source_startup.py` and `test_works_api.py` now say 75, and
  those three files with the new file and `test_router_composition.py` give **128 passed**.
- All `app/tests/*.test.mjs`: the approvals/runtime files pass; 15 `browser-*.test.mjs` files fail
  here with `Controlled installed runtimes required; never skip` (no controlled browser runtime in
  this container) — none imports `approvals.mjs`'s changed surface, and they were not run to green.
- Ruff: clean on the changed files except the ledger's 4 pre-existing findings (none new).

## Honest limits

- The recovery-superseded dispatch test forces the recovery barrier (monkeypatched
  `_recovery_barrier`) rather than running a real recovery; the real reconciliation superseding a v2
  decision is exercised in `test_owner_sessions.py` (lookup/resolve). The listing's `superseded`
  state and the transport refusal are what this file adds.
- After a recovery a superseded attempt cannot be decided again (same identity → conflict); only a
  new attempt with its own ask can be authorized.

## Still open

- **No production caller asks.** No production graph binds a tool gate, so nothing in production
  calls `request_execution_approval`; tests call it as the dispatcher would. The scheduler/gate
  passage still reads v1 only.
- The in-process `record` still accepts a v2 command without a ledger ask (kept for existing
  callers/tests); only the HTTP route requires the ask. Such a decision is refused at dispatch only
  when the ledger holds an ask for that attempt.
- The inputs binding covers the artifact input declarations (ordinal, media type, size, sha256,
  role), not tool arguments (the execute wire carries none) nor selectors.
- The atomic approval-use / ToolCall / budget / send claim in one transaction; approval and ask
  expiry; an event for the ask; a DOM rendering of the execution prompts (the module is logic only,
  like the existing approvals GUI half).
