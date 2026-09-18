# Evidence — T025 / UX-AC01: the instance's first screen (first-owner setup and login)

- Date: 2026-09-18
- Task: the Continuation's "the owner setup/login UI (T025) so the observation page is reachable
  without a bootstrap client". experience.md §5.1.3: an ownerless instance's first browser
  screen is the same-origin first-owner setup form — the one-time capability is typed in (never
  part of a URL) and the owner password created; the server consumes the capability and creates
  the owner atomically before issuing a session; an existing owner re-authenticates on the
  product's login screen; only an authenticated session leads on. T025: the raw capability is
  one-time form input, never GET/log/query.

## Frozen identities

```
bba87596f0e372347301169dc976a2962a88b3310ead497d23047561c46d8028  app/static/start.mjs
e1f43fb4e81f152bf6765be98551e42e030dd8e5cc96dc81ed7a402761eb6565  app/static/start.html
62e5c6dca3d9f010cfef73bab230137d7bb5cc7ddca04d8e5951084c4a397e24  app/static/observe.mjs
e53e638a70b555afc2fdaecf6a74a7f241c32c001bb3143ff7e1e41a392fb6f0  app/static/observe.html
fcfdc22ef7dcd374bb4602f6ea8d88f53bca9c9623be19f7fbb6e5b5400cc88d  app/api/assets.py
c3717851becfeb806cc79cba61a8307206f37b4a29e77533db47019ddb21ff0d  app/api/session_routes.py
e8595c99eab496c12409498108ffddee0c456b7af19b15d6eefbc40c7a794f2a  app/services/owner_auth.py
efa849d8c723fdfee415322472408c4070c2c9f2f52b73c397241d0ca87ae224  app/tests/start.test.mjs
37f9e0ce0630d918bbb493e8a1425ca9efb2ef09d30e00a55b2709a3924dbf9d  app/tests/observe.test.mjs
c93cc8b1303e104e46f1545a5c4618cdf7b6cc7aff43d43738e32d354822f468  app/tests/test_web_shell_assets.py
```

(The `observe.mjs`, `observe.html`, `assets.py`, `session_routes.py`, `observe.test.mjs` and
`test_web_shell_assets.py` identities frozen in `observe-page-mount-t048.md` and
`shell-assets-supported-factory.md` are superseded.)

## What was built

- `app/static/start.html` (new, catalogued `text/html`): the supported factory's `/` serves it
  (the inline "pending" stub is gone) and `/start.html` too; three mounts, two `method="post"`
  forms (hidden until the state is known; the setup form `autocomplete="off"`), relative
  assets only, an honest banner (the intake screen and run creation still pending; after login
  the observation page).
- `app/static/start.mjs` (new, catalogued): `boot({document, location, fetch})` — an
  established session (`GET {base}session`) goes straight to `observe.html`; otherwise the
  public setup state from `GET {base}health` decides: an owner → the login form (name,
  current-password) posting to `session/login`; no owner and the claim `available` → the
  setup form (the capability as a password-type input with autocomplete off, name,
  new-password of 15+ characters) posting to `session/bootstrap`; `consumed` / `expired` /
  `exhausted` → text and no form. Client-side validation mirrors the server's bounds and names
  the field and limit (the capability's 43-character base64url shape; name ≤ 128 UTF-8 bytes,
  trimmed; password ≤ 1 024 UTF-8 bytes, 15+ code points for setup); inputs are cleared before
  the exchange resolves; establishment posts carry same-origin credentials and JSON, no CSRF
  (the boundary's public establishment); refusals become typed text by envelope code or status,
  never claiming more than the code (a consumed claim: only the deployment operator's recovery
  can finish it; too many attempts: wait); the native submit is always prevented, and the
  `method="post"` guards a blocked script from ever putting a secret in a URL. The capability
  never reaches the location, the console, a dataset or the status text.
- `app/api/session_routes.py`: `/health` returns `{state, owner, setup}` — the public setup
  state the first screen needs and nothing else (no name, digest or session fact); a fault is
  the closed envelope behind the boundary's headers. `app/services/owner_auth.py`:
  `setup_state()` (read-only, closed errors) reports an available claim past its deadline as
  `expired` without an attempt (the row itself is written lazily by a bootstrap).
- `observe.mjs`/`observe.html`: the no-session text now names the start screen (it exists).

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (1 MUST, 7 SHOULD, 8 NIT). Verified clean by the reviewer over the
real factory on both profiles: the page and its HEAD; the session/health/bootstrap/cookie/
observe/session/login flow with the page's exact body and fetch shapes; the cookie path covers
`observe.html` and `session` (local `deeptwin_session; Path=/<hex>/; HttpOnly; SameSite=strict`,
portable `__Host-…; Path=/; Secure`); the capability absent from location, console, dataset and
status text and present only in the POST body; both secrets cleared before the fetch resolves;
the CSP admits the module, stylesheet and fetches; the preview's `/` untouched; the 250 ms login
floor and the buckets as documented. Closures, RED-first:

1. MUST — `setup_state()` was the one public authority entry without the closed error boundary:
   a storage fault on `/health` escaped as a bare 500 without CSP or `no-store` → `@_closed_errors`
   and the route's mapping to the 503 envelope; the RED test breaks the storage verifier and
   asserts the envelope with the headers and no private text.
2. SHOULD — `/health` said `available` after the 10-minute deadline (the row is written lazily),
   so the page offered the setup form and the owner learned of the expiry from a 409 → the read
   reports the deadline itself; pinned with a shifted clock.
3. SHOULD — the `consumed` copy promised a retry that can never succeed (api.md: no automatic
   restoration, only operator recovery) → the text says so.
4. SHOULD — the forms had no `method`, so a blocked script would have submitted the capability
   in a GET URL → `method="post"` (pinned).
5. SHOULD — copy the slice made false (the observation page still said the login screen was
   pending; docstrings) → corrected.
6. SHOULD — client bounds diverged from the server (no password cap; name length in UTF-16
   units) and every refusal read "입력 형식" → UTF-8 byte bounds mirrored, each message names the
   field and limit; pinned.
7. SHOULD — the node tests never asserted `preventDefault` → asserted on every submit.
8. SHOULD — no Python end to end → the page's flow on the real factory, both profiles.
9. NIT — the `capacity` text names attempts, not load. 10. NIT — the exhausted-claim test is
   exact and the vestigial assertion dropped. 11. NIT (stated) — after a raced 409 the text asks
   to reopen the screen. 12. NIT (recorded) — `/health` runs the authority's full check per call;
   cheap now, linear in instance history. 13. NIT (stated) — exposing `owner`/`setup` is within
   api.md's minimal health response; both facts were already derivable from the establishment
   codes. 14. NIT (T049 item) — a browser password manager may offer to save the capability.
   15. NIT — the client's capability shape is the server's first stage; a non-canonical last
   character is refused before any attempt is counted. 16. NIT — the name input declares no
   autocapitalize and no spellcheck.

## Verification

- TDD: RED retained — `ERR_MODULE_NOT_FOUND` for `start.mjs`, the catalogue pin, `/health`
  without the state; GREEN after the module, the page, the routes and the authority read; the
  review's RED tests failed for their stated reasons (the bare 500; `available` past the
  deadline; the old copy; the missing `method`; the missing byte bounds).
- Tests: `node --test start.test.mjs` **6** (state parsing; established → observe; ownerless →
  setup form only with validation, the exact body, cleared inputs; owner → login form only and a
  typed refusal; unavailable states; the establishment codes' text), observe 5, run-list 8
  (**19**); `test_web_shell_assets.py` **13** (the catalogue; `/` serves the page; the page's
  references and mounts; the health state before and after bootstrap; the module's texts; the
  claim after five wrong capabilities; the expired window; the storage fault's envelope; the
  end-to-end flow on both profiles); shell assets, server, web owner integration **115**. Ruff:
  clean on the changed Python files.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration (the wider
  covering suites ran inside it; a separately attempted subset run had an empty file list).

## Boundaries kept

- Setup and login only: no password change, no logout control on the page (the session route
  exists), no intake screen (§5.1.4's first-work-screen guidance stays open — the page lands on
  the observation page and states it), no run creation; T049's browser case stays open. No
  model, tool or paid call.
