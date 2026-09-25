# Evidence — T087: the scheduler's gate passage consumes execution-bound (v2) decisions per attempt; atomic claim; expiry; browser E2E

- Date: 2026-09-25
- Branch: `t087-scheduler` (from `codex/ui-structure` at e5de425).
- Status: **landed (one slice), T087 not closed.** Offline only; no model, network, paid or live
  call; no Docker. The only external-effect tool anywhere is the TEST-ACTOR tool
  `test_actor_notify`, registered only in test fixtures; the production worker table is unchanged
  (it holds no external-effect tool).
- Task: the items `execution-approval-route-t087-2026-09-25.md` and
  `approval-screen-2026-09-25.md` left open: nothing in production created the ledger's
  execution-approval ask, the scheduler/gate passage read only v1, approval use / ToolCall /
  budget / send were not one transaction, no expiry, no v2 case in a real browser.

## What landed

### 1. Scheduler / gate passage (`app/runtime/scheduler.py`, `app/runtime/node_attempts.py`)

- `build_scheduler` reads the compiled `tool_effects`: a node bound to an external-family tool
  behind a gate is a **gated tool node** `(gate, tool_approval_scope(tool, version))`. That scope is
  no longer a v1 scope of the gate: a gate whose scopes are all tool scopes has no static interrupt
  and no v1 decision; passing it records only its durable gate request
  (`request_gate_approval`). A gate's other scopes stay v1 exactly as before.
- A gated tool node must be attempt-bound through `NodeAttemptDispatcher` with an
  `ExtensionAttemptTransport` in its per-attempt approval mode bound to that node; otherwise the
  build is refused (as is a gated tool node inside a bounded loop). `approvals` (the persistent
  service) is required whenever a v1 gate or a gated tool node exists.
- Before the gated node's handler runs, the scheduler takes
  `NodeAttemptDispatcher.next_attempt_no(...)` (a write-free mirror of the dispatcher's own walk:
  unsent → next; observed terminal under the owner's recovery → next; reserved-unsent → itself;
  already sent → `None`, the replay resolves it and nothing is sent again) and then:
  - records `request_gate_approval` (idempotent) and `request_execution_approval(run, gate, scope,
    execution, attempt_no, inputs_digest=transport.artifact_inputs_digest)` — **the first
    production caller of the ask**;
  - reads `PersistentRunApprovals.execution_state(...)` for exactly that attempt: `pending` → the
    visit pauses (`_ExecutionAwaiting`; the node did not run, the durable head still names it;
    `SchedulerOutcome.awaiting_execution = ((gate, scope, execution, node, attempt_no),)`);
    `approved` → the handler dispatches; `rejected` / `expired` / `superseded` → the reason is
    recorded once for that attempt (`RuntimeLedger.refuse_execution_approval`, new command kind
    `refuse_execution_approval`, identity derived from the ask's) and the run fails
    `approval_refused:<node>`; a recorded refusal stands on every later run.
- `observe()` and every `run()` projection report `awaiting_execution` / `rejected_execution`
  (reason) from the ledger's asks and the owner's decisions without writing. The projection names
  the attempt an owner's recovery would send next, reported only once its ask exists.
- A retry (the owner's recovery after an observed terminal attempt) is a new attempt number and
  so a new ask; attempt N's decision never covers attempt N+1.
- `app/services/runs.py`: the projection carries both new fields; `awaiting_execution` → phase
  `awaiting_human`, `rejected_execution` → `rejected`; `approval_refused:` stops the run like a v1
  rejection (`run.stopped(cancelled)`); a cancelled run waits on nobody.

### 2. Atomic claim (`app/runtime/ledger.py`, `node_attempts.py`, `extension_attempt_transport.py`)

- `ToolDispatchClaim(command_id, spec: ToolCallSpec, verify)`;
  `commit_budgeted_send_intent(..., tool_call=claim)` runs, **inside the one send-intent
  transaction**: `verify(db, now)` (the approval check on the ledger's own view and clock) before
  any budget row, then the budget reservation, the send-intent CAS, and the ToolCall's write-ahead
  intent with its approval reference (`_record_tool_call_in_transaction`; one approval admits one
  attempt's call — reuse raises `ApprovalRefused("used")`). Any refusal (`ApprovalRefused`, reasons
  `missing|rejected|expired|superseded|used|mismatch`) rolls back all of them. The claim is not in
  the replayed payload, so an exact replay (no permit) is recognised whether or not the caller
  re-derived its claim.
- `ExtensionAttemptTransport.dispatch_claim(request, send_command_id)` builds the claim (the same
  ToolCall command id `__call__` records under, so the transport's record replays it); for an
  external effect the check is `PersistentRunApprovals.verify_dispatch_claim`: the exact v2 record
  for this attempt, the claimed reference, approved, current (not superseded), answering the
  ledger's ask (required in the per-attempt mode), carrying the inputs digest about to be declared,
  unexpired on the ledger's clock.
- The dispatcher claims only for an attempt read fresh as reserved, open and unsent; a replayed,
  already-committed attempt claims nothing (never a second send). An approval refusal becomes
  `AttemptDispatchError(approval_refusal=reason)`; the scheduler records it (for the three stop
  reasons) and stops the visit.
- Transport per-attempt mode (`approvals` without a reference named at build): before the channel
  the decision must be this attempt's, answer the ledger's ask, and already be claimed (the
  attempt's ToolCall intent carries exactly it); the fixed-reference mode is unchanged and now also
  claims through the dispatcher.
- Crash between claim and send: the claim is committed (send intent, budget, ToolCall intent with
  the approval); the existing startup reconciliation settles the attempt `outcome_unknown` and the
  ToolCall `unknown`; the resumed run asks nothing, claims nothing and sends nothing; the owner's
  recovery never retries an unknown outcome.

### 3. Expiry (`gates.py`, `ledger.py`, `run_approvals.py`)

- The ask's result carries `expires_at_ms` = ledger clock at first recording +
  `EXECUTION_APPROVAL_TTL_MS` (30 min; refused outside [60 s, 24 h]); a replay returns the same
  instant. Kept in the result, not the payload, so the ask's identity and payload are unchanged.
- `record_execution` refuses (`conflict`, HTTP 409) a new decision at or after the instant (an
  exact replay of one recorded in time still answers); the v2 record carries the ask's
  `expires_at_ms` (now one of the ask fields).
- At dispatch the claim refuses an approval on or after the instant on the ledger's clock.
- Listing states: `pending`, `approved`, `rejected`, `superseded`, **`expired`** (instant passed
  with no decision, or with an approval no ToolCall used), each with `expires_at_ms`.
- UI: `approvals.mjs` `EXECUTION_STATES` + `expiresAtMs`; `approval-screen.mjs` shows
  `만료됨 — …` (no buttons, not authorized) and each ask's `시한 … UTC`; `runtime.mjs` parses
  `awaiting_execution`/`rejected_execution` (phase agreement, node state); `graph.mjs` marks the
  waiting tool node.

### 4. Real-browser E2E (`app/tests/browser-tool-gate.test.mjs`)

Fixture `app/tests/fixtures/tool_gate_server.py`: `create_app` with a code-owned test executor
binding `writer` to the real `NodeAttemptDispatcher` and the real `ExtensionAttemptTransport`
(per-attempt mode) over the real in-process extension worker on its socket (the same test seams as
the pytest `staged` fixture); the test-actor tool is registered only in that process
(`app/tests/support/tool_gate.py`). Real Chromium (`chrome` channel):

| Case | Result | Label |
|---|---|---|
| Approve | Run started through consent/run routes pauses at `awaiting_execution` attempt 1; the screen shows `실행 {run} · tool-gate/{scope}: 실행 {execution} (노드 writer) 시도 1 — 입력 sha256 {digest}` where the digest is computed independently in the test from the exact bytes the fixture sends, plus the time limit; `승인: 시도 1` posts exactly the 8-field v2 body with the session CSRF; resume completes the run and the writer's result is the tool's sealed artifact | synthetic, test actor |
| Reject | `거절: 시도 1` → panel `rejected`; the run's read reports `rejected_execution … 'rejected'`; no attempt was reserved | synthetic, test actor |
| Retry | Attempt 1 approved, the tool fails terminally; resume shows the refusal and a re-read (`running`); `복구 시도` → attempt 2 is a new pending ask marked `재시도 시도 — … 새 결정이 필요합니다`, attempt 1 listed `approved`; approving attempt 2 and recovering completes the run with attempts [1, 2] | synthetic, test actor |

## Tests (observed, Linux x86_64)

- New `app/tests/test_tool_gate_scheduler.py`: **14 passed** (pause/ask/approve with the claim in
  one transaction; v1 decision authorizes nothing; reject; retry needs its own decision;
  superseded; pending ask expiry + record refused; approval expired at the claim (nothing written);
  crash between claim and send recovered without a send; build refusals; ledger-level refused
  claim ×4 and used-approval rollback; TTL bound).
- New `app/tests/browser-tool-gate.test.mjs`: **1 passed** (15.4 s).
- Required set (`test_tool_execution_binding test_execution_approval_route
  test_extension_attempt_transport test_run_approvals test_graph_execution
  test_scheduler_attempt_dispatch test_runs_api test_web_owner_integration test_first_party`):
  baseline before the change **305 passed**; after, with the new file: **319 passed** (305 + 14).
- Browser (`CONTROL_PYTHON`/`CONTROL_PLAYWRIGHT_MODULE`): `browser-approvals browser-tool-gate browser-records browser-graph` **7 passed**.
- Node unit (`approval-screen approvals-execution approvals runtime observe run-panel graph`):
  **58 passed** (+2 new cases).
- Full Python regression (`app/tests`, the five `*_live_*` files ignored, `-k "not live"`):
  **9186 passed, 1 failed, 15 skipped, 76 deselected** (1:20:08, a loaded container). The one
  failure, `test_credential_root.py::test_independent_process_genesis_exclusion[same_pair]`, touches
  nothing this slice changed (another agent's credential area); rerun alone it passes (3 passed):
  a timing-dependent test under load, recorded, not fixed here. (The full run preceded two
  docstring edits and a ruff import-order fix; the required set, the new file and the browser
  cases were run again after them.)
- Pins changed (additive fields only): the `SchedulerOutcome` field set in
  `test_graph_execution.py` / `test_scheduler_attempt_dispatch.py`, `PROJECTION_FIELDS` in
  `test_runs_api.py`, the listing entry in `test_execution_approval_route.py` (`expires_at_ms`),
  `EXECUTION_STATES` in `approvals-execution.test.mjs` (`expired`).
- Ruff: clean on changed files except the ledger's 4 pre-existing findings.
- Mutation checks (manual, reverted): skipping the claim's `verify` call fails 5 of the claim
  tests (claim expiry + the four refused-claim cases); skipping the scheduler's `execution_gate`
  fails the pause, reject and retry tests.

## Honest limits / still open

- **No production graph binds a tool gate**: the production worker table has no external-effect
  tool and the production run executor (`claude_run_executor`) compiles no tools. The production
  *code path* (scheduler → ask → pause → decision → claim → send) is what the fixture drives, with
  a test-registered tool.
- A stop (rejected / expired / superseded) ends the run; re-asking after an expiry would need a
  new attempt number (closing the reserved-unsent one) and is not implemented. A claim refusal for
  `used`/`mismatch`/`missing` fails the node (`node_failed`) instead of a recorded stop.
- The pre-dispatch state check reads the service clock; the authoritative expiry check is the
  claim's, on the ledger's clock (both wall clock in production).
- A run rejected on the screen records its scheduler-side refusal only when the run is executed
  again (the runs service stops a `rejected` head before running it); the owner's decision itself
  is durable.
- After the recovery that created attempt N+1's ask, sending it needs the owner's recovery again
  (a plain resume uses the non-retry dispatcher and fails the visit without sending).
- The in-process `record` can still write a v2 decision without the ask's fields; in the
  scheduler's mode such a decision is refused at the claim (`mismatch`).
- Consumed v2 approvals are not projected in `SchedulerOutcome.approvals`; tool arguments and
  selectors remain unbound (the execute wire carries none); every other T087 port stays open.
