# Evidence — the supported factory serves the browser modules; the shell speaks the supported CSRF header

- Date: 2026-09-18
- Task: T048 DOM-half prerequisite (with the T025 header name): the run GUI logic
  (`runtime.mjs`, `approvals.mjs`) and the intake shell's modules become reachable from the
  supported deployment authority, and the shell's request helper carries the one CSRF header
  the supported boundary admits (`X-DeepTwin-CSRF`, tasks.md T025). `api.md`: the static shell
  is public, everything else session-protected; `/` stays the honest setup/login stub (UX-AC01,
  experience.md §5.1, T025).

## Frozen identities

```
b4ecc1f2e65fa49f5f5d4af8494dfff0e1d60ecbb0e5814a7e662a7f6f94c08d  app/api/assets.py
96d19d4c1611ca9a51a11ceb38f0cea8e5d8d49c1b1ed3fa1709b974be8a63cb  app/api/session_routes.py
415de507083436d6e91118a23cbd56542b1a349e7d2f9976b5b585639b387dfd  app/api/web_boundary.py
794c5831e0dd3a2a30f3806885a0ec7bd692ebe414a6e104c8f8d0bedbd44a30  app/api/session.py
b3e4f77c16cf2ec0848925daa6b81a88a5989347216daf4a3ac6601d1ae22d47  app/server.py
42d8600549f449cde920819c54af7696807b42e9d7fe8db047e7a54b63d94201  app/static/app.mjs
5ae6dc1b559d85f47a6d804c41ec859bdb22eba15c4c5eb7d4efd310c69b7d89  app/static/runtime.mjs
69924336586f445ee741c97d25558d934f70fbd79df431be913700776a8c6f9c  app/tests/test_web_shell_assets.py
9b28803d85ce9da48b44915d258033d77a6ce5ae8a29375cc0871226adb757c9  app/tests/test_server.py
```

(The `runtime.mjs` identity in `runtime-gui-logic-t048.md` is superseded: one comment changed.)

## What was built

- `app/api/assets.py` (new): the closed module catalogue `MODULES` (nine flat names with exact
  media types), `PUBLIC_ASSET_PATHS`, `asset_response(name)` — the exact catalogued file served
  whole as one response (no byte ranges, no validators) or the closed `unavailable` envelope —
  and `asset_endpoint(name)`, a parameterless route endpoint so nothing about a request (query,
  body, headers) can re-aim a catalogued path at another file.
- `app/api/session_routes.py`: `GET|HEAD /<module>` for every catalogued module on the supported
  factory beside `/` (still the setup/login stub) and `/health`; `app/api/web_boundary.py`: the
  public GET/HEAD set includes the asset paths and refuses any query on them; HEAD bodies are
  blanked and the security headers (`no-store`, CSP `script-src 'self'`, `nosniff`) apply.
- `app/server.py` (development preview): the per-file asset routes replaced by the shared
  catalogue (`/` = `index.html`; the dead `STATIC` constant removed); `app/api/session.py`: the
  preview boundary admits `x-deeptwin-csrf` beside its historical `x-csrf-token` (two lines are
  not one exact singleton).
- `app/static/app.mjs`: the request helper sends `X-DeepTwin-CSRF`. Its CSRF source
  (`/api/session/csrf`) and root-absolute paths are still the preview's, so it is not yet a
  caller of the supported routes (stated in `runtime.mjs`).

## Review (independent, adversarial) and closures

Verdict: REJECT on one MUST, then ACCEPT WITH CHANGES; every closure RED-first:

1. MUST — the closure-default trick (`def module(name=name)`) was introspected by FastAPI as a
   `name` query parameter: `GET <base>/app.mjs?name=index.html` served the preview's intake shell
   publicly from the supported factory → parameterless endpoints (`asset_endpoint`) on both
   factories, and the boundary refuses any query on an asset path (`invalid_input`).
2. SHOULD — `Range` on a public asset produced Starlette's text/plain range errors, and a missing
   catalogued file FastAPI's `{"detail": …}` shape → whole-file responses without validators;
   the closed `unavailable` envelope (503) for a missing catalogued file.
3. SHOULD — arbitrary query strings rode on public asset GETs → refused (bodies on GET remain
   the boundary's pre-existing behaviour for `/` and `/health`).
4. SHOULD — the caching deviation was silent → stated here and in the module: assets are served
   under undigested names with `no-store`; content-digested immutable asset paths (api.md) are
   deferred to the T025 shell work; no `etag`/`last-modified` is emitted.
5. NIT — base path: assets are served only under the deployment base path; `index.html` and
   `app.mjs` still reference root-absolute preview paths (stated, T023/T025). 6. NIT — the dead
   `STATIC` constant and the redundant media-type argument removed. 7. NIT — the test pins the
   catalogue from the module itself, exactly.

Verified clean by the reviewer: path hygiene before routing (`..%2f`, `%00`, `//`, `\`, `.`
segments → 403); non-catalogued names are protected, not public; cross-site fetch metadata on
GET → 403; the preview accepts both header names and refuses both together; no preview test or
browser fixture asserts the old name; HEAD on the preview unchanged (405).

## Verification

- TDD: RED retained — the supported factory answered 401 for every module and `app.mjs` still
  sent `X-CSRF-Token`; the preview refused the supported name; GREEN after the catalogue, the
  routes, the public set and the header changes; the review's RED tests (query bypass, any
  query, Range, missing file) failed before the closures.
- Tests: `test_web_shell_assets.py` **5** (exact catalogue; every module served publicly with
  exact type, body, headers and HEAD equivalence while `/` stays the stub; unknown and hostile
  paths never served, query bypass refused, Range ignored; a missing catalogued file is the
  closed envelope; the shell's header name accepted and the historical one refused);
  `test_server.py` **+1** (the preview accepts both names, refuses both together, serves every
  module). Covering (shell assets, server, server API v1, server session integration, web owner
  integration, runs API, first party, run approvals, consume API, import boundary): **229 passed**
  before the review, **138 passed** on the re-run after the closures; `node --test
  runtime.test.mjs` 13. Ruff: no new findings (server.py 3/3 pre-existing), the new module clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- `/` on the supported factory is still the setup/login stub (UX-AC01 open, T025); the shell's
  CSRF source and root-absolute paths are the preview's; no DOM wiring of the run view (T048),
  no Playwright case (T049, playwright not installed on this host); no content-digested asset
  paths; no model, tool or paid call.
