# US3 — T049: controlled producer→consumer E2E and the finite authorized model paths (2026-09-25)

Status: **controlled browser/PDF/table/image E2E observed in real Chromium over real worker
processes; ONE live Claude run completed through the product's Claude run executor with a model
role consuming a produced artifact; the Codex path is NOT available here.** T049 stays unchecked
because its Codex half cannot be exercised (see "Codex path"). Scripted test actor only:
synthetic evidence of the mechanism, never user evidence (SC-001/SC-004).

## 1. Controlled E2E (offline, real processes)

`app/tests/browser-runtime.test.mjs` (new) starts `app/tests/fixtures/runtime_e2e_server.py launch`
as root; it runs, each as its own process:

| process | identity | what it is |
|---|---|---|
| fixture HTTPS site | root, loopback only | local pages (`/report`, `/chart`, `/slow-once`, `/logo.png`), test CA from `openssl` |
| fetch service | 20104 (groups 21102/21110) | the unmodified `fetch_worker_main` (test-support resolver/CA/port substitutions only, as in T043) |
| browser worker | 20105 in `unshare --net` (groups 21104/21110) | the unmodified `browser_worker_main`: headless Chromium 141, JS off, seccomp+PID-ns sandbox probe |
| supported app server | 20102 (groups 21104/21102) | `create_app(..., browser_worker=BrowserControlConfiguration, document_worker=...)` over the real `cp-browser`/`cp-fetch` pair roots |
| document worker | 20102, child of the app | `document_worker_harness` (the isolated `DocumentCodecService` over the frame channel) |

The graph (`app/tests/support/runtime_e2e.py`, `e2e_graph`) — three entry producers, a join, the
owner's gate, one consumer:

- `page-reader` (agent, ToolDefinition `browser_read` 1.0.0) and `page-shooter` (agent,
  `browser_screenshot` 1.0.0): one real attempt each through `NodeAttemptDispatcher` and the
  product's `BrowserToolset` (`app.state.browser_tools`) → `BrowserAttemptTransport` →
  `BrowserClient` → browser worker → fetch service → fixture site, under one `BrowserGrant`
  (source `https://granted.test/`, recipient `granted.test`).
- `documents` (deterministic): the product's document adapter (`app/adapters/documents.py`:
  `render_pdf` reportlab + pdfium/pypdf inspection, `render_csv`, `render_png` Pillow; all already
  pinned, no new dependency) makes `paper` (PDF), `table` (CSV) and `figure` (PNG).
- `gather` (join `all_selected`, block) → `release-gate` (human gate `release-output`) →
  `consumer` (deterministic): reads the FULL bytes of every artifact of every selected producer —
  exactly the entries the run artifact routes list — re-hashes each against its registered blob,
  and reads it: the page text (UTF-8), both PNGs decoded (Pillow; size, centre pixel, pixel
  digest), the whole PDF sent to the isolated document worker's `extract_pdf_text`, every CSV row.
  Its `report` (JSON) names each input's producer, result record, ordinal, sha256 and size; the
  result record descends from the three producer results.

Observed (one run of the test, 2026-09-25, **1 passed**, ~35 s):

- Run A created through the owner's consent and run routes: producers + join complete, the run
  waits at `release-gate` (`awaiting_human`); the receipt lists exactly two attempts
  (`page-reader`, `page-shooter`), both `terminal` / remote `succeeded`.
- Observe page: graph `documents · 정해진 처리 · 완료`, `page-reader · 에이전트 · 완료`,
  `page-shooter · 에이전트 · 완료`, `gather · 합류 · 완료`, `release-gate · 사람 승인 · 승인 대기`,
  `consumer · 정해진 처리 · 미방문`; one panel row per attempt (`시도 1 호출 <attempt id>: 게이트
  닫힘, 원격 종료 확인됨 (succeeded)`); 5 artifacts listed with their producing node:
  - `paper` PDF 2964 B `3b7d226e…0971` — page 1 of 1 rendered to PNG by the document worker;
  - `table` CSV 73 B `de7223cb…f063` — shown as a 5×3 table, cell by cell;
  - `figure` PNG 461 B `94de1217…7faf` — 240×120 image decoded by the page;
  - `screenshot` PNG 661 B `93cd1ee9…ad91` — 320×200; pixels (80,100) = (220,30,30) and
    (240,100) = (30,30,220), i.e. the chart page really rendered;
  - `page_text` text 102 B `ef699b64…a17f0` — contains "Revenue grew 12 percent in the third quarter."
- **Crash/restart:** the app server was SIGKILLed while run A waited and restarted on the same
  data, port and workers. The owner's cookie session survived (`kept`); the attempt rows and the
  artifact listing were byte-for-byte identical after the restart; run B's attempt list likewise.
- The gate was approved on the approval screen, `이어서 진행` resumed, the run completed; the
  graph shows all six nodes `완료`; 6 artifacts (`report` from `consumer`, `73122eda…`). Run A's
  attempts are still exactly the two producer attempts (nothing re-sent).
- **Consumer inputs = producer digests:** the report's `inputs` (role, sha256, size, result
  record, ordinal) equal the five listed producer artifacts exactly; the report text shows every
  full digest; the PDF read `by` = "isolated document worker (extract_pdf_text)", 1 page, title and
  every region present; CSV 5 rows, units total 300; screenshot 320×200, figure 240×120.
- **Recovery and cancel (run B, graph variant):** the reader's first read of `/slow-once` outlasts
  its 3 s deadline → attempt 1 `timed_out` (final usage), the node fails, the run route answers 503
  and the run stays unfinished (`running`). After the restart, `복구 시도` makes the reader's
  attempt 2 (`succeeded`); the run proceeds to the gate; `새 dispatch 중단` cancels it. Final
  trace: three distinct attempt ids (reader 1 `timed_out`, reader 2 `succeeded`, shooter 1
  `succeeded`), every one its own row, plus `취소 요청됨: 새 dispatch 중단`; phase `cancelled`.

### Product changes this needed

- `app/runtime/node_attempts.py`: `NodeAttemptDispatcher.build(transports={node: transport})` —
  one code-owned transport per bound node (a graph whose roles call different tools; before, a
  dispatcher had one transport and a compiled tool transport bound exactly one node, so two
  browser roles could not share a run). `transport_for(node_id)`; `.transport` still answers the
  shared one. Every per-transport check (compiled binding = its node, one tracked tool call, the
  output bound reserved by each of its nodes) is kept per transport. `app/runtime/scheduler.py`
  reads the gated node's own transport.
- **Bug found and fixed (restart + recovery):** after a process restart the owner's recovery
  replayed attempt 1's `reserve_attempt` command, whose payload binds the lease owner of the dead
  process, so the ledger refused it (`CommandConflict`) and no attempt 2 was ever made. The
  dispatcher now walks past an attempt the ledger already proves behind the visit (definitely
  unsent, or — under recovery — observed terminal with final usage) without replaying its reserve:
  the same walk `next_attempt_no` takes. Regression:
  `test_the_owners_recovery_in_a_restarted_process_continues_past_the_terminal_attempt` (RED
  before the fix, then green; also proves a plain resume in the new process still never re-sends).
- `app/services/run_artifacts.py`: a browser tool's sealed observation (`browser-tool-output-v1`)
  lists its one imported output as an artifact (`page_text` / `screenshot`, declared type without
  parameters); before, browser outputs were invisible to the artifact routes and previews.

### 2026-09-25 (after the T043 grants merge): the E2E runs under a persisted owner grant

After T043's grants landed, `BrowserAttemptTransport` builds the grant only from the persisted
record the compiled binding's `grant_ref` names and re-checks it against the run's approved
`tool_permissions` on every dispatch; the E2E's code-supplied `BrowserGrant` was refused (503).
Now `runtime_e2e_server.py` sets up the owner in-process, creates the owner's browser grant
through the `browser_grants.create` route (tools `browser_read`/`browser_screenshot`; source
`https://granted.test/`, recipient `granted.test`; projection = the exact pages `/report`,
`/chart`, `/slow-once`, pure navigation, no data sources), approves a design whose
`tool_permissions` is that record through the real producers
(`browser_grant_chain.approved_environment`), and starts both runs on that approval's
environment record; both graphs and the compilation authority bind the grant record. The
browser test logs in as that owner and checks that the grant is listed `active` with exactly
those entries. No grant is supplied in code. No live API call was made for this change.
Re-run serially: `browser-runtime` and `browser-grants` **2 passed**; `test_browser_worker.py`,
`test_browser_grants.py`, `test_claude_artifact_consumer.py` (offline),
`test_scheduler_attempt_dispatch.py` **70 passed**.

## 2. The finite authorized Claude path (ONE live run)

`app/tests/test_claude_live_artifact_consumer.py` (skipped without
`DEEPTWIN_LIVE_ANTHROPIC_API_KEY`; excluded from regressions by its `_live_` name). The product's
`ClaudeRunExecutor` gained a host-wiring seam `producers={handler_id: callable}` (a graph cannot add
one): the graph's entry node `documents-table-v1` renders the same CSV table with the document
adapter and seals it; the executor's model role (writer) receives the table's whole text as its
input; the output record descends from the table's result. The executor now also records the
provider's `request_id`. Offline twin with a mock transport: `test_claude_artifact_consumer.py`
(2 passed: the sent message is exactly the table text; the output's parents include the table).

Limits: `LiveLimits(max_model_calls=1, max_output_tokens=200)`, low effort, no retry (SDK retries 0;
a sent call is never repeated), no fallback (the owner's one catalog choice); the test refuses to
send if a pre-send bound (prompt chars as tokens at $30/MTok in, 200 tokens at $150/MTok out)
exceeds the $2.00 cap — bound $0.0502. Model: the first model the live catalog listed (no model id
in code). Run once; one catalog read (free) + one Messages call:

| field | observed |
|---|---|
| result | HTTP 201, run `completed`, output `claude-model-output-v1` state `completed`, stop `end_turn` |
| model (provider-reported) | `claude-opus-5-5` (requested = observed) |
| message id | `msg_011CfQ6HUYCbZV8x4e3AJQ27` |
| request id | `req_011CfQ6HTjKv7Baj37X3bmT3` |
| usage | 125 input / 18 output tokens, no cache |
| consumed artifact | `table` CSV `de7223cb6ce1edf086d1c77f2807b1df910091abce949121631d3d70c66ef063` (same bytes as the E2E's table); output descends from it: yes |
| output | "North has the most units (120); the units column totals 300." (60 chars; correct) |
| spend | ≈ $0.0011 at $5/$25 per MTok (the rate recorded for the prior Opus-class live call); at most $0.0065 at the ceiling rates above; well under the $2.00 cap |

The key was never printed, logged or stored; the evidence JSON was checked not to contain it.

## 3. Codex path — not available

There is no Codex subscription or Codex credential in this environment, so no Codex run was made
and nothing was simulated. The Codex environmentless tool-step bridge (T042) and a live Codex path
remain unexercised; this is why T049 stays open.

## Kept passing (2026-09-25)

Python, offline (key unset), serially: **472 passed, 0 skipped** — `test_browser_worker.py` (the
root-only real-process cases ran), `test_document_codec/tools/worker_main.py`,
`test_run_artifact_previews.py`, `test_run_artifacts_api.py`, `test_runs_api.py`,
`test_graph_execution.py`, `test_scheduler_attempt_dispatch.py` (22, incl. the new restart
regression), `test_tool_gate_scheduler.py`, `test_compiled_tool_dispatch.py`,
`test_claude_artifact_consumer.py`, `test_claude_live_path.py`, `test_claude_design_turn.py`,
`test_extension_attempt_transport.py`, `test_paired_tool_effects.py`,
`test_provider_semantic_vertical.py`, `test_alternative_drafts_api.py`,
`test_artifacts_gui_mirror.py`, `test_hypotheses.py`, `test_work_models.py`,
`test_core_import_boundary.py`, `test_tool_execution_binding.py`, `test_runtime_run_cancel.py`.
Browser (real Chromium): `browser-graph`, `browser-artifact-previews`, `browser-tool-gate`,
`browser-runtime` — **4 passed**.

## Open

- Codex path (above). T042 (provider-neutral multimodal frozen turns) is still open: the Claude
  role consumed the table as text; PDF pages/images were not sent to a model.
- The E2E executor is a code-owned TEST executor (`RuntimeE2EExecutor`); no production graph
  authority registers the browser ToolDefinitions and `BrowserGrant`s are still supplied code-side
  (T043's open items). The run-creation surface is still the owner's routes, not a page.
- Container qualification (compose seccomp, read-only roots, `network_mode: none`) is still T081;
  the netns came from `unshare --net`. The E2E is root/Linux only (it skips elsewhere).
- The screenshot pixel checks used exact colours at two sampled points; they are a rendering
  proof, not a visual-regression baseline.

## 2026-09-25: Codex path delegated to the owner

The owner said, on 2026-09-25, that the Codex-side tests will be done separately with Codex. So T049 closes on the controlled E2E and the authorized Claude path recorded above. The Codex path has **not** been executed or simulated here. It is owner-delegated, not a passed result. T088 (the Codex runner) and T042 (the Codex bridge) stay open.
