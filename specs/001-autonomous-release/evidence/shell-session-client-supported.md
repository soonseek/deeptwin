# Evidence — the shell's session client for the supported factory (`session.mjs`)

- Date: 2026-09-18
- Task: T048 DOM-half prerequisite / T025 — the Continuation's "the run view wired against the
  supported routes (its CSRF source and base path)". The run GUI logic (`runtime.mjs`) talks to
  the server only through an injected request whose caller had to supply the supported
  boundary's CSRF token and the deployment base path; the intake shell's helper (`app.mjs`)
  still reads `/api/session/csrf` at the root, the preview's path. This slice supplies the
  supported-path client: the base path derived from the document location, the token from
  `GET {base}session` (api.md: the session read returns the token again after a refresh), and
  the request adapter the observer and the approvals module need.

## Frozen identities

```
82afa0cfac4f3240a53d50d3940cbd1c0f9c22da843463f94666c6420f2d27fa  app/static/session.mjs
ae9c094b5e4d96628e00ed389fd411b20bf3c72ab1afb52dc9c8a5f04bc0e2f2  app/api/assets.py
86d670f6c8059094c3db71e47ed9a1ed59736d5152662009398776bdd2e73bd0  app/tests/session.test.mjs
4c050c514176d2f4a33916d7fdd1a5301cc7cfc201c513822228acfa13443041  app/tests/test_session_gui_mirror.py
130e2947529a80d0a64d1da108cfff14edae9e305e051467c5ca88d761a11348  app/tests/test_web_shell_assets.py
```

(The `assets.py` and `test_web_shell_assets.py` identities frozen in
`shell-assets-supported-factory.md` are superseded: one catalogue entry.)

## What was built

- `app/static/session.mjs` (new, pure logic over an injected `fetch`): `basePathFrom(pathname)`
  derives `/` or `/<32 hex>/` from the document location and never guesses (a hex segment
  without its closing slash, uppercase hex or any other prefix is the portable `/`);
  `sessionRoutes(basePath)`; `SESSION_PATH`, `CSRF_HEADER`, `ERROR_CODES` (the run routes'
  partition plus the session boundary's own refusals). `createSupportedSession({fetch, basePath})`:
  `establish()` reads `GET {base}session` with same-origin credentials and keeps the token only in
  the closure (a snapshot says `established`, never the token; nothing thrown carries it);
  `request(path, {method, body})` is the observer's adapter — `GET` or `POST` only, a command
  requires an established session before any network call, `X-DeepTwin-CSRF` and a JSON body on
  every command, paths confined to plain `{prefix}/api/v1/…` segments (no query, fragment, dot
  or empty segments, scheme or foreign base), a refusal thrown with the envelope's `code` (an
  unknown code labelled by status, an unknown status `unavailable`) and the HTTP `status`, a
  success that is not a JSON object refused as `unavailable`. A 401 drops the session; a 403 on
  a command drops it too (the token no longer matches a rotated cookie; reads still pass, so only
  re-establishing repairs it), while a 403 on a read is an origin/host refusal and the session
  stands.
- `app/api/assets.py`: `session.mjs` joins the public asset catalogue (served by the supported
  factory beside the other modules; the exact-catalogue pin updated).
- `app/tests/test_session_gui_mirror.py`: the module is catalogued; the route and header names
  are the boundary's; the partition covers both server partitions; and the client's exact wire
  shape is exercised against the real supported factory (the session read returns the token; a
  command under the client's header name passes the session and reaches the run route; without
  it the boundary refuses with a code the client knows).

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (0 MUST, 2 SHOULD, 5 NIT). The reviewer probed the real factory
with the client's exact header set (admitted: 404 `not_found` on an unknown run, i.e. past the
session; `charset` accepted; no Origin → 403; 5000 B → 413) and the session read with and
without fetch metadata; 38 hostile path forms × 2 base paths (`..`, `%2e%2e`, `\`, `//`, `/./`,
trailing slash, uppercase, `?`, `#`, CR/LF, NUL, U+2028, U+200B, non-ASCII, absolute and
protocol-relative URLs, `/api/v2`, `/session*`, a root-absolute path under a hex base — all
refused; every `runRoutes`/`approvalRoutes` output admitted); token visibility through
`JSON.stringify`, `Object.keys`, `util.inspect(showHidden)` and thrown messages (never visible);
`basePathFrom` on every location form the factory can actually serve a document at. Closures,
RED-first:

1. SHOULD — after the owner logged in again elsewhere the cookie rotated: reads kept passing but
   every command with the retained token was 403 forever and `established` stayed true, so the
   shell had no signal that establishing again would repair it → a 403 on a command drops the
   session (a 403 on a read does not); the RED test pins both and that nothing thrown carries
   the token.
2. SHOULD — the mirror string-matched `session_routes.py` and `web_boundary.py` and would stay
   green on a router prefix, a renamed session field or a header parsed but no longer verified
   → the client's route and header are exercised against the real factory (a pin: it passed on
   first run by design, stated here).
3. NIT — the partition comment said "anything else is `unavailable`" while an unknown code is
   labelled by its status → the comment states the rule. 4. NIT — a 2xx with a non-object JSON
   body resolved as a payload → refused as `unavailable` (RED test). 5. NIT — the leak
   assertions on the frozen object were vacuous → the thrown refusal is asserted token-free.
   6. NIT (design, kept) — `request` refuses `{base}/session/logout`: the T025 shell will get a
   dedicated `logout(commandId)` on the session object rather than a wider prefix; the events
   stream goes through `EventSource`, not this adapter. 7. NIT (kept) — no length bound on
   paths: the shell composes paths only from `runRoutes`/`approvalRoutes`.

## Verification

- TDD: RED retained — `ERR_MODULE_NOT_FOUND` for `session.mjs`, `KeyError: 'session.mjs'` in the
  catalogue; GREEN after the module and the catalogue entry (two adjustments on the way: the
  path grammar refused `..` as a segment, the observer fixture used a completed receipt); the
  review's RED tests failed for their stated reasons (`established` true after the 403, `null`
  resolved as a payload).
- Tests: `node --test session.test.mjs` **9** (base path derivation; the session route; the
  token read and kept private; typed establishment failures; the refused command and the 403
  rule; non-object successes; the adapter's header, body and path confinement; refusals keep
  code and status, a 401 drops the session; the run observer over the adapter on a hex base);
  `runtime.test.mjs` 14 and `approvals.test.mjs` 7 unchanged (**30**); `test_session_gui_mirror.py`
  **4**; shell assets, server, web owner integration, run GUI mirror: **115 passed**. Ruff: clean on
  every changed Python file (one import-block sort applied).
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No DOM yet: `index.html`/`app.mjs` are unchanged and still the preview's callers; the run
  view's DOM half over this client is the next slice (T048), the browser E2E T049 (playwright
  not installed on this host). No bootstrap/login through this module (T025's shell), no
  logout, no events stream. No model, tool or paid call.
