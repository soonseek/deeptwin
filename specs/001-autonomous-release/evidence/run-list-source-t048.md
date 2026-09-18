# Evidence — the run panel's run source over the public snapshot (`run-list.mjs`, T048)

- Date: 2026-09-18
- Task: the Continuation's "the shell's run source before the run panel's mount" (T048). The
  shell cannot compose a run creation yet: no production path records a `run_consent`, an
  `environment` or a `work_revision` record (the design/consent line; verified by the reviewer —
  every production reference to those kinds is a consumer, the only writer is a test fixture).
  The honest source of runs to observe is therefore the public snapshot
  (`GET {base}api/v1/snapshot`, session-protected; api.md: resume after gaps fetches the
  snapshot, so it is the canonical public state — the Runtime row mandates no list route).

## Frozen identities

```
fc431247cdf5d561e8f86af228c3160d4d64f5d8dfde023663b539b61684650b  app/static/run-list.mjs
a65893f48440d9ebbaf5b5fd2e14e08df34f5a1b0decedeb1d93a4ec3fffc320  app/api/assets.py
ce9352446baa3a094c7df596c797cd1eed32029257cb155aa5830cea6a47e5a9  app/tests/run-list.test.mjs
db485c28585ec072d0009a0889585d26956818437fae043c5ea28252f3442148  app/tests/test_run_list_gui_mirror.py
1a099b267efe1a39ed8743eb2a1eab070f97582ee85e8c44d02937f9394ffe53  app/tests/test_web_shell_assets.py
```

(The `assets.py` and `test_web_shell_assets.py` identities frozen in `run-panel-dom-t048.md` are
superseded: one catalogue entry.)

## What was built

- `app/static/run-list.mjs` (new, catalogued public asset): `SNAPSHOT_VERSION`, the runtime
  ledger's durable run phases `RUN_PHASES` with labels (기록됨 / 취소됨 — a row's own phase, never
  progress; the receipt's derived phase is the panel's), `MAX_RUNS` = the server's snapshot item
  bound, `snapshotRoute(basePath)`, `runList(snapshot)` (the public snapshot's `state.runs`
  rows validated exactly — distinct canonical ids incl. the server's v5 ids, durable phases,
  positive revisions — as a frozen list in recorded order; a foreign shape is `unavailable`),
  and `createRunList({root, document, request, basePath, onSelect})`: a status line, a
  `<select>` whose first option is the empty choice (nothing is auto-selected; a value the list
  never offered is not a choice), one option per run, a refresh button; refreshes go through
  the injected request (the session client's adapter), are generation-ordered (a superseded
  refresh resolves with the list that stands), and a failed re-read keeps the last honest list
  and the choice beside the error (run rows are never deleted, so this was the only path by
  which a chosen run could vanish from the list while the panel still showed it);
  `onSelect(runId)` once per real choice.
- `app/api/assets.py`: `run-list.mjs` joins the catalogue.
- `app/tests/test_run_list_gui_mirror.py`: catalogued; `SNAPSHOT_VERSION` is the route's literal;
  `RUN_PHASES` equals the ledger's; `MAX_RUNS` equals `MAX_SNAPSHOT_ITEMS`.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (1 MUST, 3 SHOULD, 5 NIT). The reviewer verified the rationale
(no producer of the three input kinds), fed a real supported factory's snapshot with two created
runs (v5 ids) to `runList` (accepted), and probed the fake DOM's fidelity (nothing asserted rests on
fake-only behaviour). Closures, RED-first:

1. MUST — the list's bound (4 096) sat below the server's `MAX_SNAPSHOT_ITEMS` (10 000): the
   4 097th run would have made the source permanently unusable with a false "server" error →
   mirrored and pinned by the mirror test; the node test admits 10 000 rows and refuses 10 001.
2. SHOULD — the error partition used `in` on a plain object, so a code naming a prototype
   member became the label text → own keys only; pinned.
3. SHOULD — a failed refresh wiped the list and the selection while the panel kept the run →
   the last honest list and the choice stay, the status names the error and the kept count.
4. SHOULD — fixtures misstated the served shape (root-absolute `links.events` under a base
   path; v4 ids only) → the fixture prefixes the base and carries a v5 id.
5. NIT — a superseded refresh resolved with the stale reply → resolves with the standing list.
6. NIT (kept) — the labels claim no progress; 7. NIT (open, the mount) — a real `<select>` fires
   no change for an unchanged value, so re-reading the shown run needs a control on the panel;
   8. NIT — the mirror's literal match catches a version bump; 9. NIT — the module is not mounted
   (`index.html` → `app.mjs` only), as T048's mount waits on the shell.

## Verification

- TDD: RED retained — `ERR_MODULE_NOT_FOUND` for `run-list.mjs`, the catalogue pin; GREEN after
  the module and the entry; the review's RED tests failed for their stated reasons (`MAX_RUNS`
  not exported, the mirror's bound, the wipe, the prototype key, the stale resolution).
- Tests: `node --test run-list.test.mjs` **8** (route and version; the frozen list, the v5 id,
  the bound and 11 refusals; the read and its options; empty vault, refused read, foreign shape
  and prototype-key code; a failed refresh keeps the list; choosing and clearing; overlapping
  refreshes; the source wired to the run panel through the session client on a hex base);
  run-panel 10, session 9, runtime 18 unchanged (**44**); `test_run_list_gui_mirror.py` **4**;
  covering Python (shell assets, the three GUI mirrors, server, server API v1, web owner
  integration): **144 passed**. Ruff: clean on the changed Python files.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No run creation (blocked on the consent/design line), no new server route, no mount in the
  shell yet (`index.html`/`app.mjs` unchanged), no claim of progress from the durable row; T049's
  browser case stays open (playwright not installed). No model, tool or paid call.
