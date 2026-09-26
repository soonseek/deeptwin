# UI phase 6 — accessibility, narrow screens and dark mode (2026-09-26)

Status: **audited and fixed on every shell page with synthetic test-actor data in real Chrome against the
real supported server.** These are automated checks and keyboard-only journeys. They are **not** a test by
a real screen-reader user (NVDA, VoiceOver, TalkBack), and they are **not** the owner's acceptance. The
owner has not reviewed the screenshots yet. T078 stays unticked: its text requires the frozen T081
candidate, the T087 extension UI checks, IME and three-mode usability checks, and a real screen-reader
pass.

Design and contract: docs/ui/2026-09-26-product-ux-redesign.md §15 (what landed and what was deferred);
experience.md §12 (keyboard reach, the graph's accessible list, state never by colour alone, no
repeated announcements, focus kept and returned, 360px and wide screens, zoom and both themes, graph and
table navigation inside their own box).

## Method

- **Pages.** 업무 (`work.html`), 실행 목록 (`observe.html`), 실행 상세 of a completed run and of a run
  waiting at its gate (`observe.html#run=…`), 버전·실험 (`versions.html`), 기록 (`records.html`), every
  설정 panel (계정과 세션, 모델 연결, 실행 한도, 백업·보존, 업데이트·복구, 확장, 서비스 클라이언트,
  브라우저 권한) and the signed-out 시작 screen (`start.html`).
- **Fixtures.** `app/tests/fixtures/trace_server.py` (a scripted test-actor owner; run A completed with a
  failed and a retried attempt, run B waiting at its gate; no provider call, no key read). The service
  client success path uses `app/tests/fixtures/portable_https_server.py` over real TLS with a throwaway
  test CA.
- **Automated (in-house).** axe-core was not available offline here (not under
  `/opt/node22/lib/node_modules`, not in the npm cache, not installed for pip), so nothing was vendored.
  `app/tests/helpers/a11y-audit.mjs` (a test helper; never a served asset) runs in the page. Accessible
  names and roles are Chrome's own computation (`Element.computedName` / `computedRole`, the test browser
  launched with `--enable-blink-features=ComputedAccessibilityInfo`).
- **Computed.** Contrast of the design tokens pair by pair as the stylesheet uses them, resolved in each
  theme: text 4.5:1 (large text 3:1), focus ring, field edge and glyph 3:1. Rendered text contrast is
  measured against the first opaque background behind each text, with ancestor opacity applied.
- **Keyboard journey.** Playwright, keyboard only (Tab, Shift+Tab, Enter, Space, arrows, Home, End,
  Escape, typing); no mouse, no `fill`.
- **200% zoom.** Emulated as a 640 CSS px viewport at 2 device pixels (1280 at 200%), not the browser's
  own zoom control.
- **Cross-check (not in the suite).** A copy of axe-core 4.12.1 fetched through pip into the scratch space
  was run once over 52 page and state combinations (both themes at 1280px, the light theme at 390px, the
  editor and difference view open, the drawer open, the service-client refusal): 0 violations after the
  fixes. Before the fixes it reported the settings entry's contrast (4.16:1), duplicate landmark names on
  two settings panels and the context bar outside any landmark. It was not vendored.

## Checklist

Result: **pass** (nothing to fix), **fixed** (found and fixed in this phase; the check now passes), **open**
(not done or not checkable here).

| # | Check | Page | Result | Method |
| --- | --- | --- | --- | --- |
| 1 | Every interactive control has an accessible name | all pages, both themes, 320px and 1280@200% | pass | automated |
| 2 | Images and SVGs have a role and name, or are hidden (shell icons `aria-hidden`; the graph `role=img` "노드 N개, 연결 M개") | all pages | pass | automated |
| 3 | Form fields have a real label (a placeholder alone fails) | all pages | pass | automated |
| 4 | Heading levels never skip | waiting run: "이 실행 전체" feedback was h2 → h4 | fixed | automated |
| 5 | Landmarks: one main; a role used twice has distinct names | 설정 계정과 세션 and 실행 한도: inner region repeated the panel's name | fixed | automated (+ axe cross-check) |
| 6 | No content outside a landmark | the context bar (was `role=group`, now a named region "현재 맥락") | fixed | automated (axe cross-check) |
| 7 | Every `aria-*` IDREF and `label[for]` resolves | 실행 상세: the header region pointed at a title absent while loading (now `aria-label="선택한 실행"`) | fixed | automated |
| 8 | No duplicate ids | all pages | pass | automated |
| 9 | No name on a role that prohibits it (a `div` with `aria-label`) | 업무 바꾸기, 실행 명령, the editor's 원본 side (now `role=group`); the start screen's logo (label removed) | fixed | automated |
| 10 | Live regions do not nest | all pages | pass | automated |
| 11 | `aria-pressed` / `aria-selected` only on roles that support them | 실행 상세: `aria-pressed` on the graph's SVG groups (now `data-selected`) | fixed | automated, keyboard journey |
| 12 | No positive `tabindex` | all pages | pass | automated |
| 13 | A visible focus indicator on every tab stop (`:focus-visible`, outline ≥ 2px or a shadow, ring ≥ 3:1 against its surface) | all pages (light theme, every stop until the tab order ends) | pass | automated (keyboard Tab) |
| 14 | Token contrast, light theme | accent `#087f83` was 4.42 on the surface, 4.29 on the muted panel, 4.16 on the accent tint, 4.21 on the navigation; now `#07777b` (≥ 4.55) | fixed | computed |
| 15 | Token contrast, dark theme | all pairs | pass | computed |
| 16 | Field edges 3:1 (WCAG 1.4.11) | inputs and selects were 1.77:1 (`--color-line-strong`); now `--color-field-line` (≥ 3.03 light, ≥ 3.32 dark) | fixed | computed |
| 17 | Rendered text contrast (AA) | all pages, both themes, 320px and 1280@200% (the current settings entry was 4.16:1) | fixed | automated |
| 18 | Status never by colour alone: chips carry words, graph list buttons name the state, feedback marks carry a glyph and words | all pages; 실행 상세 | pass | automated, keyboard journey |
| 19 | Reflow at 320px: no sideways page scroll; only graph, table and code boxes scroll | all pages | pass | automated |
| 20 | Reflow at 320px: every detail tab on screen | 실행 상세: 기록 was behind a sideways-scrolling tab strip (now wraps) | fixed | automated |
| 21 | Reflow at 1280px under 200% zoom | all pages | pass | automated |
| 22 | `prefers-reduced-motion: reduce` removes transitions and animations | 기록 (every element and pseudo-element) | pass | automated |
| 23 | Status changes are polite and not repeated | 업무: "저장되지 않은 변경 …" rewritten on every keystroke; 실행 상세: "산출물 3개" and "아직 남긴 피드백이 없습니다." rewritten on every selection | fixed | keyboard journey (live-region recorder) |
| 24 | No assertive announcement in a normal journey (errors keep `role=alert`) | 업무, 실행 상세 | pass | keyboard journey |
| 25 | Journey (a): write a new work and save it | 업무 | pass | keyboard journey |
| 26 | Journey (b): open a run from the list; the two runs of one work are told apart | 실행 목록 (link described by its own run line) | fixed | keyboard journey |
| 27 | Journey (b): move through the graph's nodes (arrows, Home, End; Enter or Space selects) | 실행 상세 (arrow keys added; each node stays a tab stop) | fixed | keyboard journey |
| 28 | Journey (b): switch the attempt and keep the keyboard on the picker | 실행 상세 (the redrawn picker dropped focus to the page body) | fixed | keyboard journey |
| 29 | Journey (b): switch the detail tabs with the arrow keys (one tab stop, wrap, Home/End, Tab into the panel) | 실행 상세 | pass | keyboard journey |
| 30 | Journey (b): "실행 전체 보기" keeps the keyboard (it removes itself) | 실행 상세 (focus fell to the page body; now the new heading) | fixed | keyboard journey |
| 31 | Journey (c): 내 버전 opens in place and takes the keyboard to its heading; type; 차이 살펴보기 opens in place with focus on its heading | 실행 상세 | fixed | keyboard journey |
| 32 | Journey (c): closing the difference view returns focus to 차이 살펴보기; closing the editor returns it to 내 버전 만들기 | 실행 상세 | fixed | keyboard journey |
| 33 | Journey (d): mark 확인 필요 and save; the keyboard stays on the control | 실행 상세 (the disabled 저장 dropped focus to the body; now the pressed mark) | fixed | keyboard journey |
| 34 | Journey (e): the 390px drawer takes focus, traps Tab and Shift+Tab, and returns focus on Escape and on 메뉴 닫기 | every page (the skip link stayed reachable and Tab could leave the drawer) | fixed | keyboard journey, automated |
| 35 | Journey (e): the menu's DeepTwin link is read as one word | every page ("Deep Twin" before) | fixed | keyboard journey |
| 36 | Journey (f): every settings panel by keyboard; the panel takes the keyboard; Tab never reaches a hidden panel | 설정 (8 panels) | pass | keyboard journey |
| 37 | Journey (f): a service client refused on this deployment is said in words, the server's answer under 기술 정보 | 설정 > 서비스 클라이언트 (loopback) | pass | keyboard journey |
| 38 | The graph has an equivalent list (one button per drawn node, its state in words) | 실행 상세 | pass | keyboard journey |
| 39 | The service client's one-time secret: read-only field, copy, warning, focus on its heading, never in storage, an attribute, the address or the title | 설정 > 서비스 클라이언트 (portable HTTPS) | pass | automated (browser and node tests) |
| 40 | Test by a real screen-reader user | all pages | open | — |
| 41 | Owner acceptance of the screens | all pages | open | — |
| 42 | Focus ring traversal in the dark theme (only its token contrast is computed) | all pages | open | computed only |
| 43 | Text over gradients or images, text inside the SVG graph (graph colours computed as token pairs) | 실행 상세 | open | computed only |
| 44 | Forced colours (Windows high contrast), the browser's own zoom control, IME, three-mode usability, the T087 extension UI checks | — | open | — |

## Test runs

All runs on 2026-09-26 with `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` unset.

- **Node, non-browser** (`node --test` over the 49 non-browser files): 397 passed, 0 failed. New or
  extended here: `service-clients.test.mjs` (6), `ui-shell.test.mjs` (the drawer's Tab wrap and inert
  skip link), `graph.test.mjs` (data-selected and arrow keys), `run-trace.test.mjs` (the mode badge),
  `run-feedback.test.mjs` (no rewritten status, focus after save, heading level), `records-page.test.mjs`
  (a hash-only change re-reads the log), `settings.test.mjs` (the short state lines, the new entry),
  `account-transport-qualification.test.mjs` (the short digest and its fold).
- **Browser, the full suite, one file per process**
  (`CONTROL_PYTHON=$PWD/.venv/bin/python CONTROL_PLAYWRIGHT_MODULE=/opt/node22/lib/node_modules/playwright/index.mjs env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY node --test <file>`):
  39 files, every one exit 0; 143 passed, 5 skipped. The skips are the existing environment skips (the
  real backup worker fixture needs Linux, root and `DEEPTWIN_AGE_RUNTIME_ROOT`): `browser-backup` 2,
  `browser-retention` 2, `browser-records` 1. New: `browser-a11y.test.mjs` (10: the audit, reflow,
  reduced motion and the six journeys) and `browser-service-clients.test.mjs` (1, over the portable
  HTTPS fixture). Both were run again after the last change to `service-clients.mjs`: 10 and 1 passed.
- **pytest, one file per process:** test_web_shell_assets 22, test_server 22, test_first_party 17,
  test_web_owner_integration 80, test_service_client_bearer 10 (one new: the panel's scopes mirror the
  composed bearer scopes), test_ui_format_mirror 6, test_reuse_compliance 2, test_implementation_matrix 2,
  test_run_trace_api 7 (the key set gains `run_mode`), test_claude_run_executor 7,
  test_records_contract_mirror 6, test_run_feedback_api 7, test_session_gui_mirror 4 — all passed.

## Screenshots

Saved outside the repository for the owner's review (synthetic test-actor data; the service-client
secret shown there belongs to a throwaway test server that no longer exists):

- every page at 320px and at 1280px under 200% zoom (`p6-320-*.png`, `p6-zoom-*.png`);
- the dark theme of the run detail and of every settings panel (`p6-1280-dark-*.png`);
- the service clients panel: the secret shown once (light and dark), a rotation's confirmation, the list
  after a revocation at 320px, the loopback refusal (`p6-*-service-clients-*.png`);
- focus-visible examples: a graph node and a detail tab reached by keyboard (`p6-1280-focus-*.png`);
- the work page's run-start step with "실행 준비 다시 읽기" aligned (`p6-*-run-start.png`).
