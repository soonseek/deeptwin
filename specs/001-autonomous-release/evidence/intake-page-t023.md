# Evidence — the intake page on the supported factory (T023/T025, §5.1 items 4–6)

- Date: 2026-09-19
- Task: the Continuation's "the intake page on the supported factory over `works-v1`" — the
  browser half of the intake screen. experience.md §5.1 item 4 (after the authenticated session
  the first work screen states the local retention scope, when an external model transmission
  happens and that nothing is sent to the maker, with a detail), item 5 (`어떤 일을 맡기고
  싶으세요?`, the description, `자료 추가`, the microphone, the saved state), item 6 (drafts kept
  without a connection); §5.2 (the user's sentence is never overwritten); T023 (exact
  instance-scoped storage wording; never imply the browser device is the host).

## Frozen identities

```
0c05297463105ef787b1bc820adb891c2334af3af95ca130f13a6d04b136bab7  app/static/work.mjs
04b8063b1cb2ab1b27731b10cd66d03cd1086c98a724bd3c33919db14232155d  app/static/work.html
bb4b681266db126499547b856fa2ae5956a2f95836edace66b8b0b958bcab643  app/static/start.mjs
ffb18cdd7853dc2836a4766ce6e95ccbe9e86e8c17bd385154acee9297322218  app/static/start.html
e177150c89285642630f32252b9c340eb201b357ac2ec941123045b043081ff4  app/static/observe.html
5539a491ab7d63b9b4d4192bd0b2475a2e9c49c6490853151c7654c48f461730  app/api/assets.py
e33a653b13a39f665d919f2d39d7d112c5eec8c663bb7f89dee0d8c6c8da57a3  app/tests/work.test.mjs
2737bfa9d9165e42b979e794fb71daaa69c04241b5edce1c0b88ea5389ea8bfd  app/tests/start.test.mjs
09ce39f4019fed2f9c95561f20741e70aabc7dc2f596c861520befb7c8010fe7  app/tests/test_web_shell_assets.py
```

(The `start.mjs`, `start.html`, `observe.html`, `assets.py`, `start.test.mjs` and
`test_web_shell_assets.py` identities frozen in `first-screen-setup-login-t025.md` are
superseded.)

## What was built

- `app/static/work.html` (new, catalogued `text/html`): the first work screen after login, a
  public static page under the deployment base path with relative assets only; the six mounts
  (session status, the notices, the `method="post"` form, the save status, the materials, the
  link to the observation page); an honest banner; no secret.
- `app/static/work.mjs` (new, catalogued): `boot({document, location, fetch, crypto, storage})`
  establishes the supported session; without one it names the start screen and mounts nothing
  that could send a command. With one: the three notices and a detail (what stays on this
  instance; an external transmission only when a provider is connected and a run is started
  explicitly — this screen connects to none and sends nothing; nothing sent to the maker); the
  prompt `어떤 일을 맡기고 싶으세요?` over a textarea; `자료 추가` disabled and the microphone
  absent, each said plainly to be not on this factory yet; the link to the observation page.
  The browser store (a per-deployment key; every read and write guarded; every field validated —
  a UUID shape, a positive count, a string — and the rest dropped) holds the work id and its
  revision, the draft, the draft's base revision and the pending command with the text it was
  minted for; an unsaved draft is described as kept in this browser only, never as instance
  storage. A save is one command id persisted with its text before the send: a retry replays
  it; an edit made after a lost send is saved as the next revision only after that send is
  settled with its own text (a sentence the instance may already hold is never orphaned); a
  send the reload observes as sealed is settled there. `expected_revision` is the draft's base:
  a revision saved from another screen is a conflict with two actions — reopen the saved
  revision (replaces the draft on the owner's click only) or keep the draft on top of the
  latest (rebases it). A work the instance no longer has is forgotten, never the draft. Offline
  is named as such; a rotated token is repaired once by re-establishing; a save in flight
  ignores a second submit and text typed meanwhile stays a draft; an unchanged text is not
  sealed again. Client bounds mirror the route's (20 000 characters, 65 536 UTF-8 bytes) and
  name the limit. Refusals are typed by the envelope's code, never claiming more.
- `app/static/start.mjs`: setup, login and an established session land on the work screen;
  `start.html` and `observe.html` say so, and the observation page links to the work screen.

## Review (independent, adversarial) and closures

First verdict: REJECT (2 MUST, 7 SHOULD); after the rewrite a second independent review:
ACCEPT WITH CHANGES (1 MUST, 2 SHOULD, NITs). Verified clean across both: no `innerHTML`, no
user text in an attribute or a URL, nothing user-derived in the page address; `method="post"`
and the native submit always prevented; CSRF on every command; the page public with a
navigation-shaped request while the API stays protected; HEAD equals GET; the CSP admits the
module; the module graph catalogued transitively; both origin profiles end to end; `busy`
released on every path. Closures, RED-first:

1. MUST — a stored work the instance no longer had wiped the unsaved draft (the only copy) →
   only the work is forgotten; the draft stays and is shown as a browser draft; pinned.
2. MUST — a create-mode conflict offered a reopen of `/works/undefined`, blamed another screen
   and orphaned the sentence a lost send had sealed → the pending command is bound to its text
   and settled first; the reopen renders only with a work; create-mode conflict has its own
   text; pinned (a lost create then an edit → revision 1 = the lost text, revision 2 = the edit).
3. MUST (second review) — a pending revision the reload observed as sealed stayed pending, so
   the next save met a conflict blamed on another screen → settled at boot when the saved text
   is the pending text; a draft edited since is an edit on that revision; pinned.
4. SHOULD — `expected_revision` went stale silently across a reload → the draft's base
   revision is recorded on the first edit, carried across reloads and sent; a differing latest
   at boot is shown as the conflict; pinned.
5. SHOULD — tampered storage steered requests and left the page stuck → every field validated,
   the rest dropped; pinned over seven corruptions.
6. SHOULD — a revise-mode 404 was a dead end → the work is forgotten, the draft kept, the next
   save creates; pinned.
7. SHOULD — offline was reported as a server failure → named; pinned.
8. SHOULD — a 403 on a command (the token rotated after a login elsewhere) blamed the address →
   re-established once and retried, a second refusal says to reopen; pinned.
9. SHOULD — the first notice claimed "설명과 자료" on the instance while the draft sat in the
   browser, and the second claimed instance state (no provider connected) the page cannot read
   → reworded to what this screen holds; pinned.
10. SHOULD — tests: the scenarios above; the Python end-to-end parametrised on both origin
    profiles, the schema names read from the module; the stale copy corrected.
11. SHOULD (second review) — text typed during a save in flight was reported saved and dropped
    → stays a draft on the revision just saved; pinned.
12. SHOULD (second review) — a conflict's only exit discarded the draft → a second action
    rebases the draft on the latest revision; pinned.
13. NIT — reopen and rebase guarded by `busy`; an unchanged text on a saved work is not sealed
    again (pinned); the Python test uses the client's `with` block.
14. NIT (recorded, open) — the conflict actions live inside the live status region; two tabs
    share one key and can clobber each other's draft in the browser store (nothing on the
    instance is lost); a pending send without its text is dropped by validation.

## Verification

- TDD: RED retained — the module absent, the start page landing on the observation page, the
  catalogue without the entries; GREEN after the page, the module, the catalogue and the
  landing; the first review's nine RED tests and the second review's four failed for their
  stated reasons before the closures.
- Tests: `node --test work.test.mjs` **21**; start 6, observe 5, run-list 8, run-panel 9,
  session 9 (**58**); `test_web_shell_assets.py` **15** (the catalogue, the module graph from
  every page, the work screen on both profiles with the page's exact exchanges); (shell assets,
  owner integration, server, works API) **140**. Ruff: clean on the changed Python files.
- Full regression: **6335 passed, 2 skipped** (Linux-only), 369 subtests, 16m08s.

## Boundaries kept

- No source, file or microphone input; no understanding request; no run creation from the
  intake; no provider connection (the notices say so); no browser case (T049). No model, tool
  or paid call.
