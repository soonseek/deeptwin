# Evidence — the shell mount on the supported factory (`observe.html` / `observe.mjs`, T048/T025)

- Date: 2026-09-18
- Task: the Continuation's "the shell mount of the run list + panel on the supported factory".
  The supported factory's `/` stays the honest setup/login stub (UX-AC01, T025); the mount is a
  public static page beside it (api.md: the static shell is public, everything else
  session-protected) whose module establishes the owner session the browser already holds and
  only then mounts the run source (`run-list-source-t048.md`) and the run panel
  (`run-panel-dom-t048.md`). No login UI (T025's), no run creation (blocked on the consent/design
  line), no browser case (T049; playwright not installed).

## Frozen identities

```
31b0bb240a26589ac5079b3cde16d3d1de5af3433a457014f7ada4327a74fecf  app/static/observe.mjs
b8d623eb4088b43d95d3d5ca77c99280f1999b407d06e55517cf4cdf62338dd0  app/static/observe.html
92c3e5c3b8fdbb48d54d7ce39cadb8a6343f1c294ac033a098553e601dabe5d9  app/api/assets.py
337493348bec767715819ed50f4a29d1c9ee64b97e108a858f415a9a0982e275  app/tests/observe.test.mjs
cf9e14597c4a3bc1371bc80465cf03d3339b37472338eb9a9cf3eeddb4ca7523  app/tests/test_web_shell_assets.py
```

(The `assets.py` and `test_web_shell_assets.py` identities frozen in `run-list-source-t048.md` are
superseded: two catalogue entries and two tests.)

## What was built

- `app/static/observe.html` (new, catalogued public asset, `text/html`): the observation page
  under the deployment base path with relative asset paths only (`./styles.css`, `./observe.mjs`),
  the three mounts (`#session-status`, `#run-source`, `#run-panel`), an honest banner (it observes
  recorded runs; the creation and login screens are still pending), no form, no secret.
- `app/static/observe.mjs` (new, catalogued): `MOUNT_IDS`; `boot({document, location, fetch,
  crypto})` derives the base path from the location, creates the supported session client and
  establishes it from the owner cookie; without a session it sets the status line (data-state =
  the code, text stating the fact: no owner session, the setup/login screen still pending; a
  host/origin refusal; a server answer outside the session grammar named by its status; a
  connection failure) and mounts nothing that could send a command; with a session it mounts the
  run panel (command ids from `crypto.randomUUID`) and the run list (a choice reads the run on the
  panel), reads the list once, and returns the frozen mount. `bootPage` is the page's entry: a
  boot that fails before or beside the session exchange still reaches the status line, so the
  HTML's initial text never stands for a failure; the module auto-boots only in a browser (the
  panel mount present), never under node.
- `app/api/assets.py`: `observe.mjs` and `observe.html` join the catalogue.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (0 MUST, 3 SHOULD, 7 NIT). Verified by the reviewer over the real
supported factory under the hex base path: the page and its whole module graph served with the
right types and `nosniff`; the exact CSP (`default-src 'none'; script-src 'self'; style-src
'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none';
object-src 'none'`) plus `X-Frame-Options: DENY` admit the relative module, the stylesheet and
same-origin fetches and forbid framing; nothing inline, no `data:`; the session cookie's path
covers the page; a navigation-shaped request and the page's own fetch shape are admitted; the
only 403 causes are host/origin/cross-site shaped; no instance id, base path or token in either
file; the module imported twice boots once; no test harness defines a global document. Closures,
RED-first:

1. SHOULD — the no-session text told the owner to log in somewhere that does not exist yet (a
   fresh instance without an owner answers the same 401) → the text states the fact and that the
   setup/login screen is still pending; the unreachable codes were dropped from the table.
2. SHOULD — a boot rejection outside the session exchange left the HTML's initial text standing →
   `bootPage` routes it to the status line as `unavailable`; the auto-boot uses it.
3. SHOULD — only the page's direct references were pinned as catalogued → the module import
   graph is walked transitively from `observe.mjs` and every module asserted catalogued (a pin).
4. NIT — an unknown code read as a connection failure even when the server answered → the status
   the page saw is named. 5. NIT — the copied `data-ready` attribute dropped. 6. NIT — the
   redundant `role`/`aria-live` re-set dropped. 7. NIT (stated) — `styles.css` defines no
   `.run-source`/`.run-panel`; the sections render with the base rules, acceptable for a mount
   slice. 8. NIT — the page test also sends a navigation's own request shape. 9. NIT (inherited,
   stated) — a navigation carrying a cross-site or same-site fetch metadata is refused, so the
   page is reached from the address bar, a bookmark or a same-origin link only. 10. NIT —
   `/favicon.ico` at the root answers 403 JSON: console noise only.

## Verification

- TDD: RED retained — `ERR_MODULE_NOT_FOUND` for `observe.mjs`, the catalogue pin, the page test;
  GREEN after the module, the page and the entries; the review's RED tests failed for their
  stated reasons (`bootPage` absent, the login copy, `data-ready` present).
- Tests: `node --test observe.test.mjs` **5** (mount ids and refusals; no session → honest text,
  nothing mounted, offline and a 404 answer distinguished; a session → the list read once, a
  choice reaches the panel on the hex base, portable base; a failed first list read keeps the
  session; a boot failing outside the exchange reaches the status line); run-list 8, run-panel 10,
  session 9 unchanged (**31**); `test_web_shell_assets.py` **7** (catalogue; the page served
  publicly with its type, CSP and mounts, relative catalogued references, no form or password, the
  API still protected, the navigation shape admitted; the module graph catalogued transitively);
  covering Python (shell assets, the three GUI mirrors, server, server API v1, web owner
  integration, first party, runs API): **190 passed**. Ruff: clean on the changed Python files.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- `/` stays the setup/login stub; no login UI, no bootstrap through this page, no run creation;
  the preview shell (`index.html`, `app.mjs`) is unchanged; no content-digested asset paths yet
  (T025); T049's browser case stays open. No model, tool or paid call.
