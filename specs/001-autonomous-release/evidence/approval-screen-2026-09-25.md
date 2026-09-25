# Approval screen on the observe page (T048/T087/UX-AC06), 2026-09-25

Status: **landed for gate (v1) decisions end to end in a real browser; execution-bound (v2)
asks are rendered and decided by the same screen but exercised by unit tests only.** No task
is ticked by this slice.

Found by the T074 records audit (evidence/us7.md): `approvals.mjs` was logic only and no page
mounted an approval screen; the browser recorded approvals through the owner route directly.

## What landed

- `app/static/approval-screen.mjs` (`createApprovalScreen`), mounted by `observe.mjs` at
  `#run-approvals` in `observe.html` and catalogued in `app/api/assets.py`. Choosing a run on
  the observe page shows its approvals beside the run panel, the graph and the artifacts.
- **Gates (v1).** The run's own read (`GET /api/v1/runs/{run}`, parsed by `runtime.mjs
  runView`) gives the pending `awaiting_human` pairs, narrowed by `approvals.mjs
  awaitingHumanView`. Each is shown as `실행 {run} · 노드 {node} · 범위 {scope}` with
  `승인: …` / `거절: …`. A click builds the closed body with `approvalCommand` (one fresh
  command id from `crypto.randomUUID`) and posts it to `POST /api/v1/runs/{run}/approvals`
  through the supported session client, which adds `X-DeepTwin-CSRF`. The receipt counts only
  through `receiptSummary` and only for that exact run/node/scope/decision.
- **Execution-bound asks (v2).** `GET /api/v1/runs/{run}/approvals/executions`, narrowed by
  `executionRequestsView`. Every ask is listed with `executionApprovalPrompt` (run, gate node,
  scope, execution id, executing node, attempt number, inputs sha256 or `입력 digest 없음`)
  and its state. A pending ask has approve/reject, posted as `executionApprovalCommand` to
  `POST …/approvals/executions`. A pending ask whose execution has an earlier decided or
  superseded attempt says `재시도 시도 — … 새 결정이 필요합니다`. A superseded one says it
  authorizes nothing and offers no buttons. A decided one states whether that exact attempt is
  authorized (`attemptAuthorized`).
- **The server has the last word.** After every decision the screen reads both lists again
  and calls back the run panel to re-read the run. A refusal is shown by its closed code
  (`role=alert`) beside the state read again. The two reads are independent: a refused v2
  listing never hides a gate that can still be decided. All server text goes through
  `textContent`.

## Evidence

| Case | Surface | Result | Label |
|---|---|---|---|
| Gate approved through the screen | `app/tests/browser-approvals.test.mjs` (real Chromium, `chrome` channel, `create_app` via `app/tests/fixtures/records_server.py`) | **Pass.** Two runs of the fixture's gated graph are started through the owner's consent and run routes. On `observe.html` the screen shows `실행 {run} · 노드 owner-gate · 범위 release-output`, no v2 asks, the panel `awaiting_human`, and the gate's read route answers 404. Clicking `승인: owner-gate/release-output` sends exactly one POST to `…/runs/{run}/approvals` whose `x-deeptwin-csrf` equals the session's CSRF value and whose body is exactly `{command_id, node_id: owner-gate, approval_scope: release-output, decision: approved}`. The read route then answers `approved` with that command id; the gate disappears; the panel re-reads to `running`; `이어서 진행` completes the run | synthetic, test actor |
| Gate rejected through the screen | same test, second run | **Pass.** `거절: …` records `rejected` (read route) and the panel re-reads to `rejected`; no page errors | synthetic, test actor |
| Exact identities, retry, superseded | `app/tests/approval-screen.test.mjs` (8) | **Pass.** Gate text; four v2 asks rendered with their exact prompt, state and buttons; retry attempts (after an approved and after a superseded attempt) need their own decision; superseded has no buttons; the approved attempt says authorized | synthetic |
| Closed commands | same | **Pass.** The v1 POST body is `approvalCommand`'s; the v2 body echoes the listed attempt verbatim (`execution_id`, `execution_node_id`, `attempt_no`, `inputs_digest`); both lists are re-read and the panel callback runs once | synthetic |
| Refusals | same | **Pass.** A 409 is shown as `conflict` beside the state read again, no panel callback; a refused listing leaves the gate decidable; both refused leaves nothing to decide | synthetic |
| Mounted by the page | `app/tests/observe.test.mjs` (+1), `test_web_shell_assets.py` | **Pass.** With the mount present a run choice reads `…/approvals/executions`; the module is catalogued and in the page's transitive import graph | synthetic |

## Not exercised / open

- **v2 in a real browser.** No supported path produces a v2 ask: the ledger's
  `request_execution_approval` has no production caller (T087 open item), and the records
  fixture's gated graph has only a human gate. The browser case therefore sees an empty v2
  list, and the screen says there is nothing to decide instead of inventing an ask.
- Resuming after an approval stays a separate command on the run panel (the screen says so).
- Version approval/rollback (T066) is a different decision (US6) and is not this screen.

## Observed (2026-09-25, Linux x86_64)

- `node --test app/tests/browser-approvals.test.mjs` (with `CONTROL_PYTHON` and
  `CONTROL_PLAYWRIGHT_MODULE`): 1 passed; with `browser-records` and `browser-graph`: 6 passed.
- `node --test app/tests/approval-screen.test.mjs app/tests/observe.test.mjs`: 14 passed.
- `pytest app/tests/test_execution_approval_route.py app/tests/test_run_approvals.py
  app/tests/test_run_approval_api.py app/tests/test_web_shell_assets.py` (inside the 212-test
  run recorded in evidence/us7.md): passed.
