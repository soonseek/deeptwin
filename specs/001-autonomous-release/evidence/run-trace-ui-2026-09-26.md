# UI phase 3 — run trace and run detail screen (2026-09-26)

Status: **the read-only run trace route and the run detail screen are implemented and exercised
in real Chrome against the real supported server with synthetic test-actor data. The owner has not
reviewed the screenshots yet.** Automatic checks passing is not usability acceptance
(docs/ui/2026-09-26-product-ux-redesign.md §9). T048 and T078 stay unticked.

Design: docs/ui/2026-09-26-product-ux-redesign.md §5.3, §5.4, §7. What landed and what was deferred
is recorded in §12 of that document.

## What landed

### Server: `GET|HEAD /api/v1/runs/{run_id}/trace`

- Contribution `run-trace-v1`, route `runs.trace`, scope `work.read`, browser session only (a
  bearer gets `401`). No query and no body are accepted. The response carries
  `Cache-Control: no-store`.
- Code: `app/api/run_trace.py`, `app/services/run_traces.py`, and `app/runtime/budgets.py`
  (`reservation_record`, read only). The run read now shares its parts
  (`PersistentRuns.observe_parts`).
- The route is registered in `app/api/first_party_catalog.py`. The run preflight in
  `app/api/runs.py` admits only GET/HEAD with no body on the trace.
- Route inventory: 144 routes in 28 contributions (`route_inventory.py --write`). The pinned
  counts are updated in `test_first_party`, `test_web_owner_integration`, `test_runs_api`,
  `test_works_api` and `test_provider_source_startup`.
- Contract docs: `contracts/api.md` row "Runtime (implemented 2026-09-26, `run-trace-v1`)" and
  `docs/release/api-compatibility.md` §3b.
- **Response `run-trace-v1`.** Top-level fields:
  - Run identity: `run_id`, `phase`, `graph_ref`, `graph_digest`.
  - Work: `work {work_revision_ref, work_id, revision, title}`.
  - `budget_mode`, `started_at_utc`, `ended_at_utc`.
  - `stops[]`: the run's own `run.stopped` records, each with a reason, a time and a duration.
  - `totals`: model calls, tool calls, attempts, retries, input and output tokens,
    `tokens_complete`, and `cost {state, microunits, currency}`.
  - `exit {node_ids, basis}`, where the basis is the completion criteria or the graph's sinks.
  - `final_results[]` and `stopped_at[]`.
  - `nodes[]`: each node's visits. A visit carries its status, result, outputs and
    `produced_by_attempt_no`.
    - `inputs[]`: the upstream visit and its attempt, the result ref, and each artifact's exact
      version and SHA-256.
    - `attempts[]`: each attempt's times, outcome, error, own outputs, tool calls, budget
      reservation, cost with its basis, and journal.
    - `model_calls[]`: the Claude executor's recorded calls, with tokens, times and the output ref.
  - `handoffs[]`, each with `receipt: not_recorded`.
  - `approvals {gates, executions}`.
  - `timeline[]` and `links`.
  - `gaps[] {category, reason}`, one per category that is not recorded: `attempt_tokens`,
    `handoff_receipt`, `handler_attempts`, `handler_error`, `model_cost`, `reasoning`.
- **Honesty rules:**
  - Unrecorded values are the string `not_recorded`; nothing is computed to fill them.
  - A past attempt carries only its own outputs. The visit result is attributed only to the
    attempt the bound checkpoint row names.
  - Cost bases:
    - `budget_settlement` for settled actuals;
    - `reserved_ceiling` (an estimate) for a reservation made from ceiling rates before the send;
    - `subscription_mode` (no currency);
    - `not_recorded` otherwise.
  - No hidden reasoning, secrets, credentials or raw provider payloads are included.
- **`GET /api/v1/events`** (and `/stream`, `/{event_type}`) take at most one of `run_id` or
  `work_id` (canonical UUID).
  - They match only on what each event carries: `work_id` through work-revision refs, and
    `run_id` through the run's own start/stop correlation, a run ref, or refs to its attempts.
  - An approval decision names neither, so it is not matched by `run_id`.
  - The subject is part of the cursor's filter identity.

### Browser: the run detail screen (`observe.html`)

- New modules: `run-trace.mjs` (pure logic) and `run-detail.mjs` (DOM). Both are catalogued in
  `app/api/assets.py`.
- Reworked modules: `observe.html`, `observe.mjs`, `artifacts.mjs` (a filter per selection and an
  editor slot), `alternatives.mjs` and `alternative-file.mjs` (title and close, in place),
  `graph.mjs` (selection callback, vertical layout, fitted labels, folded design details),
  `run-panel.mjs`, `approval-screen.mjs`, `records-page.mjs` (`#run=` filter), `ui-format.mjs`
  (trace terms) and `styles.css`.
- Header: work name, short run id, a status chip, start and end times with the duration, call
  counts (model, tool, attempts and retries), tokens, cost ("미확인" when unknown, "추정" when
  estimated), and the run commands. A pending approval shows a banner with "승인 화면 열기",
  and the graph node gets a dashed marker.
- "최종 결과" comes first. Each exit artifact has a preview, "원본 내려받기", "내 버전 만들기",
  "대안 파일 올리기" and "과정에서 보기". Without a final result the section says so and lists
  where the run stopped.
- "과정": graph | timeline tabs and the selection panel share one selection.
  - The panel has visit and attempt pickers, defaulting to the latest.
  - A past attempt shows a note and only its own error, inputs, calls and journal.
  - Tabs: 입력 / 산출물 / 전달 / 도구·모델 / 기록.
  - The 산출물 tab lists only the selected node's outputs. This fixes the earlier bug where the
    whole run was listed.
  - 기록 links to `records.html#run=<id>`, which filters the event log by `run_id`.
- 내 버전 opens in place, in the final-result card or the selected artifact row.
  - The title names the artifact, role and visit or attempt.
  - On wide screens the original and the owner's version sit side by side, with a 차이 view.
  - The status reads "자동 저장됨 (수정본 N)".
  - "분석용으로 고정" is renamed "차이 살펴보기" (UX-D07). Its behaviour and the no-reason rule
    are unchanged.
- The old 20-row text list is no longer a primary element. It remains, folded, as
  "노드별 상태를 글로 보기", beside the graph's node-list buttons.
- On a narrow screen a pick in the graph or timeline scrolls the selection panel into view.
- A change of `#run=` on the same page opens that run.

### Fixture

`app/tests/fixtures/trace_server.py` runs the real supported factory with the product's Claude run
executor over an in-process scripted transport. There is no network, and it refuses to start if
`DEEPTWIN_LIVE_ANTHROPIC_API_KEY` is set. It extends the executor with the tool-gate fixture's test
seams: the in-process extension worker, the TEST-ACTOR tool `test_actor_notify` (it claims an
external effect and performs none), the real attempt dispatcher and the extension attempt
transport. A scripted test actor then works through the owner's own routes:

- sets the owner up;
- chooses the scripted model;
- saves a work;
- runs `intake → writer (one model call, 812/164 tokens reported by the script) → tool-gate
  (gate approved) → publish (attempt 1 approved and failed; recovery; attempt 2 approved and
  succeeded) → report (final report artifact)`;
- starts a second run that waits at the gate.

Labels: `synthetic/test-actor`.

## Observed

Every run had `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` unset. Pytest ran one file per process.

### Server (pytest)

- **`test_run_trace_api.py`: 6 passed.**
  - Shape; attempt separation (attempt 1 keeps its failure and no outputs; attempt 2 its result).
  - `not_recorded` values and named gaps.
  - No secret, key or raw provider payload in the body.
  - Browser session only: bearer `401`, no cookie `401`, unknown run `404`, bad id, query or body
    `400`.
  - A handler run's final result.
  - API-priced cost bases: settled `9000` (`budget_settlement`), unknown attempt `25000`
    (`reserved_ceiling`, estimate), total estimate `34000` USD.
  - The events filter by `run_id` and `work_id`, with the subject bound to the cursor.
- **Route counts and composition, all passed:**

  | File | Passed |
  |---|---|
  | `test_first_party` | 17 |
  | `test_web_owner_integration` | 80 |
  | `test_runs_api` | 27 |
  | `test_works_api` | 23 |
  | `test_provider_source_startup` | 21 |
  | `test_router_composition` | 36 |
  | `test_server` | 22 |
  | `test_reuse_compliance` | 2 |
  | `test_implementation_matrix` | 2 |

- **`test_web_shell_assets`: 22 passed** (catalogue with `run-trace.mjs` and `run-detail.mjs`).
- **`test_ui_format_mirror`: 5 passed** (every trace term has a label).
- **Neighbours, all passed:**

  | File | Passed |
  |---|---|
  | `test_run_trace` | 10 |
  | `test_public_events` | 15 |
  | `test_service_client_bearer` | 9 |
  | `test_api_command_transaction` | 26 |
  | `test_server_api_v1` | 26 |
  | `test_run_approval_api` | 8 |
  | `test_runtime_budget_dispatch` | 35 |
  | `test_budget_policies` | 3 |
  | `test_run_artifact_previews` | 8 |
  | `test_tool_gate_scheduler` | 14 |
  | `test_runtime_result_settlement` | 12 |

### Node unit tests

All non-browser files ran in one `node --test` call (44 files): **354 passed, 0 failed**. The new
or extended files:

- **`run-trace.test.mjs`** (9): the route; contract refusal; the header facts with an unknown cost;
  final results or stop points; the default latest attempt and a past attempt's own facts; the
  timeline; pending approvals.
- **`run-detail.test.mjs`** (11):
  - the final result first, with an in-place edit whose title names the artifact and step;
  - node selection filters the outputs to that node;
  - graph and timeline share one selection without echo;
  - on attempt 1 of the store step: its error, its inputs, its tool call only and its journal, with
    none of attempt 2's outputs;
  - the model call with its tokens, the unknown cost and no reasoning;
  - the approval banner;
  - no final result: where the run stopped;
  - contract refusal;
  - a pick made while loading;
  - the panel scrolls into view only when it is stacked.
- **`observe.test.mjs`** (`#run=` parsing).
- **`records-page.test.mjs`** (the `run_id` filter, its links and its empty text).
- **`alternatives.test.mjs`** (the label "차이 살펴보기").

### Browser suite

Real Chrome, one file per process, `CONTROL_PYTHON` and `CONTROL_PLAYWRIGHT_MODULE` set. The final
full run covered all 35 files with the final page code:

- 34 files passed.
- `browser-runtime` failed on its newly added assertion. It counted the listed artifacts before
  the selection's filter had applied. The test now waits for the filtered status, and it passed
  twice alone after that change.
- Total: **126 tests passed, 0 failing.**
- `browser-backup` and `browser-retention` (2 each) skipped themselves: their backup worker
  fixture needs `DEEPTWIN_AGE_RUNTIME_ROOT`, which this container does not have.

**`browser-run-detail.test.mjs` (new, 2 passed):**

- the run opens on its header (work, status, `모델 호출 1회 · 도구 호출 2회 · 시도 2회(재시도 1회)`,
  `입력 812 · 출력 164`) and its `최종 결과` (`report` with its preview);
- the store step defaults to attempt 2. On attempt 1 it shows `시도 1 오류`, the past-attempt note,
  `시도 1의 산출물이 없습니다.`, its exact input (`draft` from `tool-gate`, and the tool's declared
  input) and exactly one tool call (`publish · 시도 1`, failed). The 기록 tab links to
  `records.html#run=`;
- the writer's model call shows its tokens, "미확인" and the no-reasoning note;
- another node lists its own artifacts (`draft · writer`, then `source · intake`, one each);
- a timeline entry selects attempt 1, and the entry is marked;
- 내 버전 opens inside the final-result card, titled
  `내 버전 — report (최종 안내문을 보고서로 묶는다 · 수행 1)`, autosaves (`자동 저장됨 (수정본 1)`)
  and offers `차이 살펴보기`. No `분석용으로 고정` remains;
- a waiting run, opened by a hash change on the same page, shows the banner, the `승인 대기` node
  marker, no final result, and the approval screen.

**Existing files changed for layout or label only:**

- `browser-alternatives`, `browser-inquiry`, `browser-records`: the button label.
- `browser-performance`: waits for the run header and the graph's node list instead of the folded
  text rows.
- `browser-runtime`: a selected node now lists only its output (`page_text · page-reader`); the
  test asserts that, then returns to "실행 전체 보기" before the run-wide checks.
- `browser-shell`: returns to the whole run before the artifact-row check; opens the node's design
  disclosure; counts the cancel button while its disabled row is hidden.

Security, honesty and behaviour assertions are unchanged. In an earlier full run,
`browser-owner-material-intake` (file chooser) and `browser-work-conversation-t023` (reading count
after reload) failed once each, while running beside other work. Neither touches the observe page,
and both passed on rerun and in the final full run.

## Screenshots

Saved outside the repository in the session scratchpad (`…/scratchpad/phase3/`). Each state is
captured full page at 1280×900, 390×844 and dark 1280×900:

- (a) `a-run-opened-*`: the run opened;
- (b) `b-attempt-1-*`: the two-attempt node on attempt 1;
- (c) `c-tools-models-publish-*` and `c-tools-models-writer-*`: the 도구·모델 tab (tool call;
  model call with tokens);
- (d) `d-my-version-*`: 내 버전 in place;
- (e) `e-records-run-*`: the records page filtered to the run;
- (w) `w-waiting-run-*`: a run waiting at the gate.

## Open

- Owner review of the screenshots (phase 3 deliverable).
- ~~The Claude executor path records no per-call cost.~~ Superseded the same day: see
  "Recorded usage" below (a cost basis per call; a settled cost on that path stays open).
- ~~Ledger attempts record no token counts (`attempt_tokens`).~~ Superseded the same day: an
  attempt whose transport reports provider usage now has it journaled; the gap stays for an
  attempt whose transport reports none.
- Hand-off receipts are not recorded.
- Approval decisions are not matched by the events `run_id` filter.
- Deferred to phase 4:
  - process marks and memos;
  - the difference screen; the "차이와 설명" card still sits in its old place.
- Deferred to phase 5:
  - the run list table;
  - records filters beyond the run.
- Deferred to phase 6 and T078: accessibility checks.

## Recorded usage (2026-09-26, later the same day)

Status: **the product now records what the provider reports for each model call and each model
attempt, and each executor call's cost with its basis; the trace reads those records.** No live
provider call was made: every run below used a scripted transport with
`DEEPTWIN_LIVE_ANTHROPIC_API_KEY` unset. T048 stays unticked.

### Where production model calls happen, and what was already recorded

- **The Claude run executor** (`app/services/claude_run_executor.py`) is what the supported factory
  installs (`app/server.py` `main()`). Each run model call seals an intent before the send
  (`claude-call-intent-v1`) and, after it, the output artifact (`claude-model-output-v1`, a
  completed call) or the outcome record (`claude-call-outcome-v1`, anything else). Both already
  carried what the adapter observed: the provider's message id, request id and reported model, and
  its reported usage (input, output, cache creation and cache read tokens). Tokens per executor call
  were therefore already durable; the cost basis was missing.
- **Ledger attempts** go `NodeAttemptDispatcher` → transport → `accept_result_and_settle`. The
  ledger and the budget book kept the reservation and the settled counters only. The semantic
  provider transport (`app/runtime/provider_attempt_transport.py`, not wired into the supported
  factory) already parsed the provider's usage in core and sealed it as `provider-semantic-usage-v1`,
  but it gave the dispatcher no counts.
- **The provider-send gateway** (the credential gateway) sends the bytes once and keeps its
  receipts. It parses no usage. It is unchanged.
- **Ceiling rates.** No product configuration held any. A budget policy holds a currency and a cap
  (`max_api_microunits`), and an attempt's reservation holds a reserved amount. Per-token ceiling
  rates existed only as constants in the owner-gated live tests' spend guards and in evidence
  (`us2.md`). Nothing in the product reads those.

### What is recorded now, and where

1. **Per attempt** (`app/runtime/ledger.py`, `app/runtime/node_attempts.py`):
   - A transport may return `AttemptTransportResult.provider_usage`, a `ProviderUsageReport`: the
     input, output, cache creation and cache read counts (each an integer, or None when the provider
     did not report it), and the observed model, provider message id and provider request id when
     the transport holds them.
   - `accept_result_and_settle(..., provider_usage=...)` journals it once, as the attempt journal
     transition `provider_usage`, in the same transaction and only with an accepted classification.
     A duplicate or late observation adds none. It never changes the classification, the settlement
     or the send accounting. It enters the command payload only when present, so a command recorded
     earlier replays unchanged.
   - `RuntimeLedger.attempt_provider_usage(attempt_id)` reads it back.
   - The semantic provider transport now reports the normalized usage and the observed model
     (`_provider_usage`, which never raises). It does not hold the provider's message or request id,
     so those stay unreported.
   - No schema change: the journal's closed transition vocabulary grew by one entry. A historical v1
     ledger holding such an entry migrates to v2 through the offline operation with the entry kept,
     and the v2 history verification accepts it on repeat (tested).
2. **Per executor call** (`app/services/claude_run_executor.py`):
   - The intent now carries `ceiling_rates`: the configured rates that apply to this run, or null.
   - The output artifact or outcome record now carries `cost` {`state`, `basis`[, `method`,
     `microunits`, `currency`, `rates`]}, beside the usage and ids it already had.
3. **Operator configuration** (`CeilingRates`, `ceiling_rates_from_environment`, `app/server.py`):
   - Optional, non-secret settings: `DEEPTWIN_LIVE_CEILING_CURRENCY`,
     `DEEPTWIN_LIVE_CEILING_INPUT_MICROUNITS_PER_MTOK`,
     `DEEPTWIN_LIVE_CEILING_OUTPUT_MICROUNITS_PER_MTOK`, and optionally
     `…_CACHE_CREATION_MICROUNITS_PER_MTOK` and `…_CACHE_READ_MICROUNITS_PER_MTOK`.
   - None set means no rates. A partial or malformed setting stops the server at startup.
   - Documented in `docs/release/operator-deployment-backup-guide.md` §2.

### Cost-basis rules

- `budget_settlement` (`state: settled`): only a ledger attempt whose reservation was finalized
  with the `actual_api_microunits` its transport reported. The executor never settles against the
  budget book, so its calls never have this basis.
- `reserved_ceiling` (`state: estimate`, always labelled an estimate), by `method`:
  - `reservation`: a ledger attempt that was not settled, with a positive reserved amount. The
    amount is the whole reservation made before the send.
  - `recorded_tokens_at_ceiling_rates`: an executor call under an API-priced budget whose currency
    equals the configured rates' currency. The amount is the sum of each recorded token count times
    its rate, divided by one million and rounded up. The rates used are part of the cost. A reported
    cache count whose class has no configured rate is never priced as input: the call's cost is then
    `not_recorded`.
- `subscription_mode` (`state: unknown`, no money value): the run's budget is a subscription.
- `not_recorded`: everything else. That covers an API-priced budget without rates in its currency
  (never a conversion), no reported input or output count, and a call recorded before this change
  under an API-priced budget.
- The trace never prices anything at read time. A call recorded before this change reads
  `subscription_mode` or `not_recorded` from the run's budget, even when rates are configured now.

### Trace (`run-trace-v1`, additive)

- Each attempt carries `tokens` {`input`, `output`, `cache_creation_input`, `cache_read_input`},
  `observed_model`, `provider_message_id` and `request_id` (`not_recorded` when not reported).
- A `reserved_ceiling` estimate carries its `method`. A model call's `cost` is the recorded one.
- Totals add the attempts' recorded tokens and the executor calls' estimates.
- Gaps:
  - `attempt_tokens` only for a sent model attempt without reported counts;
  - `model_cost` only for a model call whose cost basis is `not_recorded`;
  - `reasoning` for any model call or sent model attempt;
  - `handoff_receipt`, `handler_attempts` and `handler_error` are unchanged.

### Browser

- `ui-format.mjs`:
  - an estimate names its method ("예약 상한 기준 추정", "기록된 토큰 × 설정된 상한 단가 추정"),
    and a run total says "상한 기준 추정";
  - `ratesText` words the rates;
  - the journal label `provider_usage` is "제공자 사용량 기록";
  - the two gap texts are reworded to what is still missing.
- `run-detail.mjs`:
  - a model call shows the gap reason only when its cost is not recorded, and shows the rates in
    "기술 정보";
  - a model attempt's cost section shows its tokens (or why there are none) and the observed model
    and ids.
- `run-trace.mjs`: a model attempt's timeline entry names its reported tokens.

### Fixture

`app/tests/fixtures/trace_server.py` configures the executor with the fixture's own synthetic
ceiling rates (USD, 4 000 000 / 20 000 000 micro-units per million input / output tokens; a test
configuration, never a real price). Labels stay `synthetic/test-actor`.

- **Run A** (the completed, tool-gated run) stays under a subscription budget. Its writer call shows
  `입력 812 · 출력 164` and "미확인 (구독 방식: 호출별 금액 없음)".
- **Run B** (waiting at the gate) now runs under an API-priced USD budget. Its writer call shows the
  same tokens and "약 $0.0065 (기록된 토큰 × 설정된 상한 단가 추정)", which is 812 × 4 + 164 × 20
  = 6 528 micro-units, with the rates in "기술 정보". Its header shows "약 $0.0065 (상한 기준 추정)".
- No new screenshots were taken for this change; the phase 3 set above predates it.

### Guarantees kept

- **Exactly-once send accounting:** reserve, send intent, permits and settlement are untouched. The
  usage entry is written only inside the accept transaction of an accepted result. Replay returns
  the stored outcome and adds nothing. The same command id with other counts is refused
  (`CommandConflict`).
- **Reconcile paths, no retries, no fallback:** unchanged. A transport's outcome cannot change
  because of usage evidence.
- **Redaction:** only bounded integer counts and bounded provider labels are stored. No payload,
  text or credential. The trace tests' secret canary still never appears.
- **Frozen files:** no file pinned by `evals/deeptwin/qualification/*/FROZEN.json` was edited. The
  adapter `app/adapters/claude_api.py` is pinned and unchanged.

### Observed

Every run had `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` unset. Pytest ran one file per process.

| File | Passed |
|---|---|
| `test_provider_send_gateway` | 85 |
| `test_runtime_budget_dispatch` | 35 |
| `test_budget_policies` | 3 |
| `test_runtime_result_settlement` (4 new) | 16 |
| `test_run_trace` | 10 |
| `test_run_trace_api` (1 new, 1 extended) | 7 |
| `test_runs_api` | 27 |
| `test_claude_run_executor` (new) | 7 |
| `test_ipc_populated_fence` | 22 |
| `test_first_party` | 17 |
| `test_reuse_compliance` | 2 |
| `test_provider_semantic_vertical` (extended) | 87 |
| `test_ui_format_mirror` | 5 |
| `test_runtime_ledger` | 46 |
| `test_runtime_ledger_migration` | 89 |
| `test_provider_attempt_transport` | 9 |
| `test_scheduler_attempt_dispatch` | 22 |
| `test_graph_execution` | 44 |
| `test_extension_attempt_transport` | 48 |
| `test_worker_response_capture` | 92 |
| `test_dispatch_subject_context` | 12 |
| `test_runtime_budgets` | 63 |
| `test_gateway_send_budget` | 12 |
| `test_tool_gate_scheduler` | 14 |
| `test_web_shell_assets` | 22 |
| `test_claude_artifact_consumer` | 2 |
| `test_claude_design_turn` | 2 |
| `test_design_requests`, `test_hypotheses`, `test_difference_inquiries`, `test_work_models` | 3, 2, 5, 3 |
| `test_server` | 22 |

- Node, all 44 non-browser files in one call: **358 passed, 0 failed**. `run-trace.test.mjs` and
  `run-detail.test.mjs`: 24 passed (4 new).
- `browser-run-detail.test.mjs` in real Chrome (`CONTROL_PYTHON`, `CONTROL_PLAYWRIGHT_MODULE`):
  **2 passed**, including run B's estimate and run A's subscription basis.

### Found, not changed

- An extension tool attempt cannot settle under an API-priced budget. Its measured usage names
  `api_microunits: None`, and the API-mode settlement refuses that (`BudgetBook.settle` raises
  `ValueError`; checked directly on a scratch vault). That is why the fixture's tool-gated run A
  stays under a subscription budget. Fixing it changes budget accounting and is out of this scope.

### Still `not_recorded`

- A settled cost on the executor path: it never settles against the budget book.
- Any cost for an API-priced run while the operator has configured no ceiling rates (the default).
- Tokens of a ledger attempt whose transport reports none: the extension tool transport, an unknown
  outcome, and a deadline-quarantined attempt's late result.
- The provider message id and request id on the semantic path, which does not hold them.
- Hand-off receipts, handler attempts and handler errors.
- Hidden reasoning, which is never stored.
