# US4 evidence — the owner's own version (T054, SC-006) — 2026-09-23

## Kind of evidence

**Synthetic, test-actor evidence of the mechanism only.** The scripted Playwright actor does all
the "owner" editing below, against a fixture run whose artifacts are fixed bytes. None of it is
evidence that a real user made an alternative, reviewed a work, or that the product helped anyone.
**Actual-user alternatives: none recorded (not available in this environment).** SC-006's
real-user part remains open.

## Environment

- Linux x86_64 container, Chromium 1194 (Playwright's build, run as the `chrome` channel), Node 22,
  Python 3.12.
- The real supported server (`create_app` with a deployment config and session root) serves
  `app/tests/fixtures/alternatives_server.py`.
- The run is started through the owner's own `run-consents` and `runs` routes. The code-owned test
  executor returns one sealed result: a `text/plain` report and a `text/csv` table.
- No model, tool or paid call.

## Cases (`app/tests/browser-alternatives.test.mjs`, 3 passed, repeated twice)

1. **Three views, autosave, refresh and freeze.**
   - The observe page lists the run's artifacts. "내 버전 편집" opens a copy of the original.
   - Typing autosaves revision 1.
   - "원본" shows the recorded bytes read-only, with no textarea.
   - "차이" shows what the framework observed on the saved revision (the T055 observer):
     "원본 2–2행이 대안 2–2행으로 바뀌었다".
   - Switching back to "내 버전" keeps the owner's text.
   - A page reload resumes revision 1 from the server.
   - The explicit freeze records only the changed line: "바꾼 부분 1곳".
   - No page errors.
2. **A stale tab never overwrites.**
   - Two tabs edit from revision 1, and tab A saves revision 2.
   - Tab B's save is refused as a conflict, and B's text stays on screen.
   - B keeps its text as a new draft (revision 1 of its own). The first draft still holds A's
     revision 2: the server lists revisions [1, 2].
   - A third stale tab chooses "최신 수정본 불러오기" instead, and receives the newer revision's text.
3. **A table is edited cell by cell with the keyboard**: focus, select all, type. Autosave runs,
   and the differences view names the changed cell: "원본 2행 2열과 대안 2행 2열의 값이 다르다".

"Stale-range recovery" in this build means the conflict recovery above. Selectors are computed at
freeze time from one exact saved revision, so a range can never be computed against text the
server did not save.

## What this does not show

- No real user made or judged an alternative.
- Neither PDF/image region selection nor the alternative-file upload was exercised in a browser
  here. Both are covered by API tests and node DOM tests only (T053).
- The comparison between the alternative and the original goes no further than formal
  differences: impact stays `pending_investigation`.
