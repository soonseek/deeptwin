# Evidence — the run view's DOM half (`run-panel.mjs`, T048)

- Date: 2026-09-18
- Task: T048 [US3] "Connect live graph/role visits/attempts/inputs/outputs/tools/cancel/recovery
  to common UI … keep past attempts distinct (UX-AC04/10)" — the DOM half over the run GUI
  logic (`runtime-gui-logic-t048.md`) and the supported session client
  (`shell-session-client-supported.md`). experience.md §9/§12: the state in text, never colour
  alone; §7: visits and attempts distinct. api.md runtime rows: start, cancel, recover/retry.

## Frozen identities

```
d0e9912543fb3a001fc121f9befb1cff06c5ec18c7d4f640a14fc26104192546  app/static/run-panel.mjs
91d5b854a68e10d51dfd4c2efc146d7c6b7cbe0be6dc92e1bec3caa22da6c799  app/static/runtime.mjs
6fedb5f5815321e612ba37089d9961034f6d170f7db513518b4d9fe885d37a42  app/api/assets.py
b8016d3fafbed2e73884c7d7d16539fb591489d5602eea2544f943f865a9e665  app/tests/run-panel.test.mjs
bb2914fadb23cc9d502c1a1331c98d21fb82c3e607e544456c60666196f1e0f6  app/tests/runtime.test.mjs
54dc8da9e0e6014abe67997b1451d2146b13496f7a14761cef75600922c62f8e  app/tests/test_web_shell_assets.py
```

(The `runtime.mjs`, `runtime.test.mjs`, `assets.py` and `test_web_shell_assets.py` identities frozen
in the GUI-logic, recover-route and session-client evidence files are superseded.)

## What was built

- `app/static/run-panel.mjs` (new, catalogued public asset): `createRunPanel({root, document,
  request, basePath, commandId})` renders the run observer's state into a DOM the caller owns —
  a status line (`role=status`, polite; a `running` head reads **미완료**, never "실행 중": the
  receipt carries no liveness and a failed execution leaves a `running` head with nothing
  live), one accessible text row per node and per past attempt (`accessibleRows`), the closed
  error text keyed by the server's code (`role=alert`, `data-code`; `ERROR_MESSAGES` cover
  `ERROR_CODES` and never claim what the view cannot know), and three commands (`CONTROL_LABELS`:
  이어서 진행 / 새 dispatch 중단 / 복구 시도) gated by `controlsFor(state)` from the server's own
  admission (`app/services/runs.py`): resume on `created`/`running` (the head runs again; on a
  waiting gate resume is a server no-op, so it is not offered), cancel on any run not complete
  or cancelled (a rejected run included), recover — one more billed attempt — only on `running`
  and only by the owner's click; nothing while an exchange is in flight. Each click sends one
  fresh command id from the injected source (a non-UUID is a recorded `invalid_input`, never a
  send). A refused command of the shown run is kept on screen beside the run read again at once
  (a 503 may have run a node and recorded a stop) until the owner's next command or read; the
  screen and `snapshot()` always agree. `panel.observer` is the real observer; `read`/`start`
  delegate.
- `app/static/runtime.mjs`: `accessibleRows` lists every past attempt as its own row whether or
  not a cancel was requested (the 취소 요청됨 row only when it was); `createRunObserver` keeps
  the last view on a refused cancel/recover of the shown run (previously read/resume only), a
  superseded exchange never touches the newer view or error when it fails late, and the busy
  publish moved inside the fault boundary so a throwing renderer cannot leave the observer busy
  forever.
- `app/api/assets.py`: `run-panel.mjs` joins the catalogue.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 5 SHOULD, 6 NIT). The reviewer probed the real server's
admission per phase (`resume` on `awaiting_human` → 200 no-op; after the approval the read is
`running` and resume completes; a 503 leaves a completed node and a stop event) and the panel
with eight node probes. Closures, RED-first:

1. MUST — resume was offered exactly where the server no-ops (waiting gate) and hidden where
   the owner needs it (`running` after an approval or a failed execution), leaving 복구 시도 —
   an extra billed attempt — as the only continuation → resume on `created`/`running`; the
   gating table test corrected.
2. MUST — the `unavailable` text claimed the run state did not change, which a 503 with a sent
   attempt contradicts → the text says the run was read again; the panel re-reads the run after
   any refused command of the shown run.
3. SHOULD — a `running` head read 실행 중 with nothing live → 미완료. 4. SHOULD — attempt rows
   rendered only under a cancel request (UX-AC04) → every attempt is a row. 5. SHOULD — a conflict
   left a stale view with live controls and no way to refresh → automatic re-read with the
   refusal retained. 6. SHOULD — a superseded exchange's late failure wiped the newer run →
   generation check in the observer's fault branch. 7. SHOULD — the non-UUID command id path
   was only a comment → tested; the retained refusal keeps screen and snapshot equal.
8. NIT — the rows list is labelled for nodes and attempts. 9. NIT — the `invalid_input` text no
   longer says the request was not sent (a 400 was). 10. NIT — a throwing renderer no longer
   leaves the observer busy. 11. NIT — `unauthenticated` asks for the session to be re-established,
   not a login. 12. NIT (stated) — the fake `click()` awaits async listeners; a real one does not,
   so T049 must poll; no assertion rests on fake-only behaviour. 13. NIT (kept) — no dispose is
   needed (listeners live on panel-owned children); `nodeIds` (미수행 rows) is not reachable through
   the observer and not required by this slice.

Verified clean by the reviewer: double click sends once (busy is published before the first
await); render is synchronous inside `publish`; cancel gating matches the server on every phase;
recover hidden on awaiting/rejected where the server no-ops; the §9 cancellation rows render
without a termination claim; unknown codes → `unavailable` text; the session wiring on a hex base
path sends the CSRF header on commands only.

## Verification

- TDD: RED retained — `ERR_MODULE_NOT_FOUND` for `run-panel.mjs`, the catalogue pin; GREEN after
  the module and the entry (one observer gap found by the panel test and pinned in the runtime
  suite before the fix); the review's nine RED tests failed for their stated reasons before the
  closures.
- Tests: `node --test` run-panel **10**, runtime **18** (+4: attempts distinct without a cancel,
  refused cancel/recover keeps the view, a superseded late failure, a throwing renderer), session
  9, approvals 7 (**43**); shell assets, run GUI mirror, session mirror **13**; wider Python covering
  (shell assets, session mirror, server, web owner integration, run GUI mirror, runs API):
  **142 passed** before the closures. Ruff: clean on the changed Python files.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- The panel is not yet mounted in `index.html`/`app.mjs`: the shell has no run source yet (no
  graph/run creation surface — T023/T025/T046 line), so a mount would be dead code; the module
  is reachable from the supported factory and proven wired to the supported routes through the
  session client. The approvals surface (`approvals.mjs`) is not rendered by this panel. T049's
  browser case stays open (playwright not installed on this host). No model, tool or paid call.
