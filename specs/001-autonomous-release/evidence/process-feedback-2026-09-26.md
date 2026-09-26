# UI phase 4 — process feedback and 차이 살펴보기 (2026-09-26)

Status: **the owner's process feedback (a mark and a memo) and the in-place difference view are
implemented and exercised in real Chrome against the real supported server with synthetic
test-actor data. The owner has not reviewed the screenshots yet.** Automatic checks passing is not
usability acceptance (docs/ui/2026-09-26-product-ux-redesign.md §9). T048 and T078 stay unticked.

Design: docs/ui/2026-09-26-product-ux-redesign.md §5.3–§5.5 and §6; the owner decision "2026-09-26 —
Owner decisions on the product UI after a usability review" (decisions.md); experience.md §7, §8,
§12. What landed and what was deferred is recorded in §13 of the redesign document.

## What landed

### Server: `run-feedback-v1` and the `process_feedback` record

- **Record** (`app/services/run_feedback.py`, kind `process_feedback`, `process-feedback-v1`):
  - The target is the run (`{scope: run}`) or one node's exact visit and attempt (`{scope: step,
    node_id, visit_no, attempt_no}`). A visit the executor ran without ledger attempts takes
    `attempt_no: null`. The target must exist in the run's own trace (`404` otherwise).
  - `mark` ∈ `ok` / `needs_attention` / null. `memo` is null or plain text of 1–4,000 characters with
    a visible character; tabs and line breaks are kept and other control characters are refused.
    A set needs a mark or a memo; either alone is complete. No explanation is ever asked for (FR-016).
  - One identity per run and target: revision n is record version n. Revision 1's parent is the run
    manifest and revision n's is n-1. A change is a new revision; a clear is a new `cleared`
    revision; nothing is overwritten or deleted. A change names the revision it was made from
    (`expected_revision`); a stale one is `409`.
- **Write path:** the owner-command path the other owner writes use.
  - A CSRF-verified same-origin POST of the live owner session (`_authenticate_owner`).
  - One command id: an exact replay returns the same revision (`replayed: true`) and emits nothing;
    the same id with another body is `409`.
  - The record and its public event `feedback.recorded` go in one writer transaction.
- **Event** `feedback.recorded` (exact payload, registered and exported):
  - `scope` (run/step), `mark` (ok/needs_attention/none), `memo` (present), `cleared`, `revision`.
  - Never the memo text.
  - Object refs: the record and the run, so `GET /api/v1/events?run_id=` lists it.
  - `ui-format.mjs` words it ("과정 피드백을 남겼습니다 (단계 · 괜찮음 · 메모)"); the mirror test pins it.
- **Routes:** `GET|HEAD /api/v1/runs/{run_id}/feedback` (`runs.feedback`, `work.read`) and
  `POST /api/v1/runs/{run_id}/feedback` (`runs.feedback_record`, `work.command`).
  - Browser session only; a bearer gets `401`.
  - The run preflight admits the path and bounds a POST body to 64 KiB (`runs.FEEDBACK_BODY_BYTES`).
    A memo over 4,000 characters is `413`.
  - GET answers `process-feedback-list-v1`: `current {run, steps}` (the latest revision of every
    target, cleared ones with their state) and `history` (every revision).
  - POST answers `201` with `recorded`, `replayed` and the new `current`.
  - Contribution `run-feedback-v1` requires `run-trace.service`, which `run-trace-v1` now provides.
    Route inventory: 146 routes in 29 contributions.
- **Trace** (`run-trace-v1`, additive): `feedback {run, steps}` at the top, `feedback` on every
  attempt and visit (the current set feedback of that exact target, or null), `links.feedback`.
- **Export:** the export contract has a natural place. The `events` category already carries the
  runs' owner decisions (approvals) as metadata. When a run of the work has feedback,
  `events/run-feedback.json` lists every revision as metadata: target, mark, state and memo length,
  never the memo text. Nothing goes under `alternatives`.
- **Never an alternative (UX-AC05):**
  - Feedback is a separate kind that no alternative, draft, difference, hypothesis, inquiry or
    export-alternatives path reads.
  - Memory compilation, the change compiler and the knowledge registry now refuse a
    `process_feedback` reference, so exploration can use feedback only as an owner-supplied
    observation, never as ground truth.
  - No gateway profile carries the kind.
- **Contracts and records:**
  - `contracts/api.md`: row "Process feedback (implemented 2026-09-26, `run-feedback-v1`)".
  - `data-model.md`: record `ProcessFeedback` and the event list.
  - `docs/release/api-compatibility.md` §3c and the regenerated inventory.
  - `schemas/v1/domain-envelopes.schema.json` and `event-metadata.schema.json`, regenerated.
  - The pinned route counts: `test_first_party`, `test_web_owner_integration` (count, contribution
    ids, route ids), `test_runs_api`, `test_works_api`, `test_provider_source_startup`.

### Browser

- **Process feedback** (`run-feedback.mjs`, `run-detail.mjs`):
  - "이 결과 전체" sits at the end of the final result block ("이 실행 전체" when there is no final
    result).
  - The selection panel has the same control for the selected node's exact attempt, titled
    "이 단계: 승인된 안내문을 저장 도구로 기록한다 · 시도 1". It is absent for the whole-run selection.
  - The control:
    - 괜찮음 / 확인 필요 toggles with `aria-pressed`; pressing the pressed one takes it back.
    - [메모 쓰기] opens an optional memo with a character count.
    - An explicit [저장] with "저장됨 · 3분 전" (the absolute time as the title). There is no
      autosave.
    - [지우기], shown only when feedback exists; it says the earlier records stay.
    - The helper text: "이유를 적지 않아도 됩니다. 표시만, 메모만, 또는 둘 다 남길 수 있습니다."
    - A save in one place keeps an unsaved edit in the other. A stale revision loads the server's
      latest and says why.
  - **Markers:**
    - The graph node gets a small badge (! 확인 필요, ✓ 괜찮음, ✎ 메모만) with its words in an SVG
      `<title>`, and " · 피드백: 괜찮음" beside the node's list button. Colour is never the only cue.
    - The timeline marks the exact attempt row, or the visit row of a visit without attempts.
    - The header gets "내 피드백" with one chip per kind, each in its own tone, e.g.
      [결과 전체: 확인 필요] [괜찮음 1개 단계].
- **차이 살펴보기** (`difference-view.mjs`; `inquiry.mjs` embedded mode; `observe.mjs`):
  - It opens in place, under the editor in the same artifact slot, and replaces the detached
    "차이와 설명" card. The placement is justified in redesign §13.3.
  - The first screen:
    - the observed differences;
    - the evidence scope with the unreviewed area ("내가 바꾼 1곳이 근거입니다. 바꾸지 않은 부분은
      검토하지 않은 영역으로 남고, 영향 범위는 따로 조사합니다.");
    - the related run segment from the trace (`run-trace.mjs` `differenceSegment`): the step, its
      visit and attempt, its inputs (the previous step and attempt, the artifact roles) and its
      tool and model calls, with [과정에서 이 단계 보기].
  - Picking a difference shows the original part and the owner's part, with line numbers, and three
    lines around (−/+ and screen-reader words). These are the two exact contents the editor froze.
    When they are not known (the owner kept typing, or an uploaded file), the view says so and shows
    the observation only.
  - The inquiry sits inside the view:
    - competing explanations only on explicit request, and they stay `proposed`;
    - optional questions, evidence, judgments and change-candidate proposals that are not applied.
  - Opening the view reads the difference, or observes it once. It calls no model.
- **Phase 3 clean-ups:**
  - The vault-wide artifact index moved to `records.html#artifacts` ("모든 산출물"). Each row has
    [실행 화면에서 열기] → `observe.html#run=…&artifact=…`, which opens the run and previews the
    artifact. The run page says it shows only this run and links there.
  - The approvals card folds to "이 실행의 승인 기록 N건 · 보기" when nothing is pending, and
    stays open after a decision.
  - Approval deadlines are shown in this device's local time (`ui-format.mjs` `absoluteTime`), not
    UTC.
  - Records page: a `run.stopped` chip is the run outcome ("실패로 멈춤" in the error tone, "완료",
    "취소·거절로 멈춤", …; all eight closed reasons are mirrored). The record's own status moves to
    "사건 기록 상태" in the technical fold.
  - "다음 기록 보기": a short page is followed until the page fills or the server's cursor stops
    moving (at most 40 reads), and the button hides at the log's end.
- **Assets:** `run-feedback.mjs` and `difference-view.mjs` are added to the flat catalogue
  (`app/api/assets.py`).
- **Guide:** `docs/release/browser-user-guide.md` §1, §4.1, §4.2, §4.5, §4.8 and §6.1 are updated.

### Merge

`origin/codex/ui-structure` (provider-reported usage and cost bases in the trace, the fixture's
API-priced run B) was merged, not rebased. The conflicts in `contracts/api.md` and
`data-model.md` kept both sides. The screenshots and the listed tests below ran after the merge.

## Observed

Every run had `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` unset. Pytest ran one file per process.

### Server (pytest, after the merge)

- **`test_run_feedback_api.py` (new): 7 passed.**
  - Set, change, clear and set again: revisions 1→2→3, the history of every revision, the record
    chain (revision 1's parent is the run manifest), a stale `expected_revision` `409`, and a clear
    of nothing `400`.
  - A replayed command id returns the same revision and emits nothing; the same id with another
    body is `409`.
  - Validation: `400` for neither mark nor memo, a blank memo, a control character, an unknown mark
    or action, a run target naming a node, a bad node id, visit 0, or an extra field. 4,000
    characters are accepted and 4,001 are `413`; a 70 KB body is `413`.
  - Unknown targets: a run, a node, a visit or an attempt; a null attempt where the visit has
    attempts; an attempt where it has none. All are `404`.
  - Access: no CSRF token `401`/`403`, a foreign origin `403`, a bearer `401` on GET and POST, no
    cookie `401`.
  - The event: one `feedback.recorded` per revision with the exact payload, the run in its refs,
    no memo text, and found by `?run_id=`.
  - The trace: the run's feedback, the exact attempt's (attempt 2 of the same visit stays null),
    a cleared visit null in place and `cleared` in `steps`.
  - **Never an alternative:**
    - no `own_alternative`, `difference`, `hypothesis`, `inquiry`, `selector` or
      `change_candidate` record and no alternative, difference, hypothesis or inquiry event exists;
    - the final artifact has no draft;
    - the export's `alternatives` category is `not_recorded` and holds no item;
    - `events/run-feedback.json` holds both revisions without the memo text;
    - memory compilation, the change compiler and the knowledge registry refuse the record's ref.
- **Route counts, composition and neighbours, all passed:**

  | File | Passed |
  |---|---|
  | `test_run_trace_api` | 7 |
  | `test_run_trace` | 10 |
  | `test_first_party` | 17 |
  | `test_web_owner_integration` | 80 |
  | `test_runs_api` | 27 |
  | `test_works_api` | 23 |
  | `test_provider_source_startup` | 21 |
  | `test_router_composition` | 36 |
  | `test_web_shell_assets` | 22 |
  | `test_server` | 22 |
  | `test_public_events` | 15 |
  | `test_ui_format_mirror` | 6 |
  | `test_reuse_compliance` | 2 |
  | `test_implementation_matrix` | 2 |
  | `test_work_exports_api` | 17 |
  | `test_memory_compilation` | 5 |
  | `test_change_compiler` | 10 |
  | `test_knowledge` | 7 |
  | `test_domain_schema_exports` | 3 |
  | `test_domain_events` | 711 |
  | `test_event_coverage` | 6 |
  | `test_alternative_drafts_api` | 8 |
  | `test_extension_lineage_contracts` | 102 |
  | `test_extension_installation_domain` | 30 |
  | `test_deployment_acceptance` | 36 |
  | `test_provider_semantic_contracts` | 17 |
  | `test_claude_run_executor` | 7 |
  | `test_runtime_result_settlement` | 16 |
  | `test_provider_semantic_vertical` | 87 |
  | `test_api_command_transaction` | 26 |
  | `test_server_api_v1` | 26 |
  | `test_run_approval_api` | 8 |
  | `test_domain_permissions` | 69 |

  `test_web_shell_assets` first failed on the run page's new link `./records.html#artifacts`: the
  page may reference only catalogued assets, and a fragment is not one. The link is now
  `./records.html`, and the file passes. The assertion is unchanged.

### Node unit tests

All non-browser files ran in one `node --test` call (46 files): **372 passed, 0 failed.**

- New: `run-feedback.test.mjs` (5), for the command, lookup, markers, summary, control and the
  detail's two feedback places. `difference-view.test.mjs` (3), for the parts, the segment and the
  view without a model call.
- Extended: `ui-format` (stop outcomes, the feedback sentence), `graph` (markers), `observe`
  (`#run=…&artifact=…`), `approval-screen` (the fold, local deadlines) and `records-page` (paging
  to the end, the short filtered log, the honest stop chip).

### Browser suite

Real Chrome, one file per process, after the merge. All 35 files passed: **127 tests, 0 failed.**
Five tests skipped themselves, as before: `browser-backup` (2), `browser-retention` (2) and one in
`browser-records`. They need the backup worker's `DEEPTWIN_AGE_RUNTIME_ROOT`, which this container
does not have.

`browser-run-detail`, `browser-shell` and `browser-artifact-previews` ran again after the link fix
and passed.

- **`browser-run-detail.test.mjs` (3 passed; the new journey):**
  - The whole result is marked 확인 필요 with no memo and saved. The exact command body is checked,
    and it carries the CSRF header.
  - The store step's attempt 1 is marked 괜찮음 with a memo and saved.
  - After a reload:
    - both are pressed and saved;
    - the header reads [결과 전체: 확인 필요] [괜찮음 1개 단계];
    - the graph badge and the list words mark `publish`;
    - the timeline marks attempt 1 and not attempt 2;
    - the memo is back.
  - Clearing leaves no marker, and the server shows `cleared` with 3 revisions. No body carries a
    reason.
  - 내 버전 of the final result gets one changed line, then 차이 살펴보기 opens inside `#run-final`.
    The detached card is gone. The view shows:
    - the changed line on both sides;
    - the step "최종 안내문을 보고서로 묶는다" (report) and its input from `publish` attempt 2;
    - the unreviewed-area statement and the explanations not made.
  - The only commands are the freeze and one observation. No request went to hypotheses,
    model-choice, inquiries or connections. The only refused response was the difference read
    before its observation (`404`).
- **Changed for location only:**
  - `browser-inquiry`: the panel is `#run-difference`.
  - `browser-artifact-previews`: the index is on `records.html` and its rows are links.
  - `browser-tool-gate`: the deadline regex is without "UTC", the local time.

## Screenshots

Real Chrome, 1280×900, 390×844 and 1280 dark, full page, on a fresh trace fixture (synthetic
test actor). Scratchpad folder `phase4/` (not committed):

| State | Files |
|---|---|
| (a) the whole result marked 확인 필요, no memo, saved | `a-final-needs-attention-{1280,390,1280-dark}.png` |
| (b) the store step's attempt 1 marked 괜찮음 with a memo; the graph badge and list words | `b-attempt-ok-memo-{1280,390,1280-dark}.png` |
| (c) after a reload: the header line [결과 전체: 확인 필요] [괜찮음 1개 단계] and the folded approvals | `c-header-summary-{1280,390,1280-dark}.png` |
| (d) 차이 살펴보기 in place under the final result's editor | `d-difference-view-{1280,390,1280-dark}.png` |
| (e) the records page filtered to the run: "실패로 멈춤", "완료", the feedback events, no "다음 기록 보기", the moved index | `e-records-run-stops-{1280,390,1280-dark}.png` |

Fixes made from the screenshot review:
- The pressed mark's glyph turned into an empty disc; it now keeps its tone colour.
- The header line was one warning-coloured chip, so "괜찮음 1개 단계" read as a warning. It is now
  one chip per kind.
- The embedded inquiry used larger text than the view, and its status repeated the view's; both are
  fixed.
- The two first-screen cards align to their tops.
- On a phone, the nested card and the view give their padding back to the content.

## Not done / open

- The owner's screenshot review; T048 and T078 stay open.
- The UI shows only the current feedback. The history is in the GET route and the export.
- No target for a hand-off itself (sender → receiver); targets are the run and a visit/attempt.
- No exploration path reads feedback yet. It is only fenced to observation use.
- The difference view closes on a reload. Reopening it freezes the same revision again as a new
  alternative (the existing editor behaviour).
- The related run segment is the producing step only, not the upstream chain.
