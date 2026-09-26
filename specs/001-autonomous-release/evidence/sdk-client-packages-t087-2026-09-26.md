# T087 slice: separate SDK/client package roots and installed-client TLS reach (2026-09-26)

Status: **package roots, artifacts and fresh-environment installs landed; T087 stays open.**
This covers the first half of the T087 sentence "Produce separate PEP 517 package roots,
metadata and wheel/sdist artifacts … install each into a fresh environment rather than
importing the repository source tree". The alternate-client parity half cannot be met yet (see
"Still open").

## What landed

- **Two package roots** (the layout `plan.md` names):
  - `sdk/python/deeptwin_ext/`: distribution `deeptwin-ext` 0.1.0. The existing
    `deeptwin_ext` sources moved unchanged to `src/deeptwin_ext/`, and
    `test_extension_sdk.py`/`test_extension_spi.py` now point there.
  - `sdk/python/deeptwin_client/`: distribution `deeptwin-client` 0.1.0 (new). It is a
    stdlib-only HTTPS service client:
    - HTTPS only, with certificate and hostname verification and TLS 1.2 or newer
    - exactly one `Authorization: Bearer` credential, checked against the server's
      `dt_sc_` + 32-byte base64url form
    - no cookies, redirects or plaintext mode
    - plain `/api/v1` paths only (`.`/`..`/percent segments refused)
    - bounded JSON responses with duplicate keys refused
    - typed `ApiError`/`TransportError`, whose messages never carry the credential; the
      client refuses to pickle and its repr omits the credential
    - an optional `connect_address` (an IP literal to dial, like curl's `--resolve`) that
      leaves verification and Host on the origin name
    - methods: `snapshot`, `read_command`, `submit_command`, and the extension reads
      (`list_extension_candidates`, `read_extension_candidate`,
      `list_extension_installations`, `list_extension_bindings`, `read_extension_binding`)
- **Each root has:**
  - its own `pyproject.toml`: `[build-system] requires = []`, `backend-path = ["_build"]`,
    License-Expression `Apache-2.0`, no dependencies
  - `LICENSE`/`NOTICE` copies, pinned byte-equal to the repository's
  - the in-tree backend `_build/deeptwin_build_backend.py`
- **Why an in-tree backend:** the project environment has no setuptools, hatchling, flit, wheel
  or build (checked: none importable in `.venv`, and pip is absent there). A pinned new build
  dependency would need a lock change and network access. The backend is stdlib-only and
  byte-identical in both roots, because PEP 517 `backend-path` must lie inside the tree being
  built. It implements:
  - `get_requires_for_build_{wheel,sdist}` (returns `[]`), `prepare_metadata_for_build_wheel`,
    `build_wheel`, `build_sdist`
  - Metadata 2.4 (`License-Expression`, `License-File`, licenses under
    `.dist-info/licenses/`), a `py3-none-any` purelib wheel with a sha256 RECORD, and a
    self-contained sdist (`PKG-INFO`, `pyproject.toml`, licences, backend, sources)
  - reproducible bytes (sorted entries, fixed 1980 or `SOURCE_DATE_EPOCH` timestamps, uid/gid 0,
    fixed modes)
  - refusal of any pyproject field outside its supported subset (dependencies, readme, a
    non-`MAJOR.MINOR.PATCH` version, license files outside the root)
- **The real server over TLS:** test fixture `app/tests/fixtures/portable_https_server.py`
  runs `create_app` on the `portable_https` origin profile (`https://deeptwin.test:<port>`)
  under uvicorn with a throwaway `openssl` CA and leaf, bound to 127.0.0.1. Requests therefore
  reach the actually composed route surface with `scheme == "https"`.

## Tests (one file per concern)

- `app/tests/test_sdk_package_builds.py`, **15 passed**:
  - both roots are offline PEP 517 roots with distinct names; the backends are identical; the
    licences are byte-equal to the root's; the repository stays `package = false`
  - the sources import only the standard library and never `app`
  - the wheel's file set is exact, every RECORD hash and size is verified, and METADATA and
    WHEEL fields are pinned
  - the sdist's member set and bytes are exact and it has fixed ownership and mtime
  - wheel and sdist are byte-reproducible for both distributions, and a different
    `SOURCE_DATE_EPOCH` changes the bytes
  - unsupported pyproject fields are refused
- `app/tests/test_sdk_package_install.py`, **8 passed**:
  - for each distribution × {wheel, sdist}: a new `python -m venv`, then `pip install --isolated
    --no-index --no-deps --no-cache-dir`. The sdist path makes pip run the in-tree backend under
    build isolation.
  - probes run with `python -I` from a directory outside the repository and a scrubbed
    environment (no PYTHONPATH). In each one:
    - `import app` fails, and the other distribution is not importable
    - the module resolves from that venv's site-packages, with no `sys.path` entry inside the
      repository
    - `importlib.metadata` gives the pyproject version, `Apache-2.0`, no requirements and
      installer `pip`
  - the installed `deeptwin_ext` builds a manifest that the core `ExtensionManifest` parser
    accepts, with canonical bytes equal to `canonical_json`
  - the installed client refuses plaintext, userinfo, query and path origins, malformed
    bearers, non-IP connect addresses, dot and encoded path segments, and pickling, all before
    any I/O, and never echoes the credential
- `app/tests/test_extension_client_blackbox.py`, **2 passed**. The client wheel is installed
  in a fresh venv and run with `python -I` outside the repository, where `import app` fails.
  Against the running TLS server:
  - the owner path (bootstrap over TLS, a `Secure` cookie) gets 200 from `/api/v1/snapshot`,
    `/api/v1/extensions/candidates`, `/api/v1/extensions/installations` and
    `/api/v1/extensions/bindings`. The routes the client calls are mounted and served.
  - the installed client calls the same four routes over verified TLS (test CA, SNI and Host
    `deeptwin.test:<port>`, dialled at 127.0.0.1) with a well-formed, never-issued canary
    bearer. Each gets **401 `unauthenticated`**, the uniform pre-auth denial.
  - with system trust only, the same client fails with `TLS verification or handshake failed`
  - an `http://` origin is refused before I/O
  - the canary appears in no output
- Unchanged suites still pass: `test_extension_sdk` 61, `test_extension_spi` 46,
  `test_extension_architecture` 8, `test_first_party` 17, `test_reuse_compliance` 2,
  `test_router_composition` 36, `test_web_owner_integration` 80, `test_service_client_routes` 4.

## Still open (precisely)

1. **No bearer route exists to call.** Every route contribution under
   `app/api/route_contributions/*.json` is `auth_policy: browser_session` (138 of 138).
   `ServiceClientAuthenticator` and `HeadlessCommandSurface` have no production caller, and the
   `/api/v1/service-clients` lifecycle router is not composed into `create_app`. So "call
   T025's actually mounted TLS-bearer HTTPS server routes" cannot be met until T025 mounts the
   bearer path through the seam. The black-box test pins today's truth (401 for the bearer
   client, 200 for the owner on the same routes) and has to be turned into admitted calls when
   T025 lands.
2. **No parity yet.** Matching the browser path's durable receipt, revision, authority and
   event ordering across restart and concurrency needs (1), plus a service-client issuance path
   the test can drive (owner create → one-time secret → bearer).
3. **No OpenAPI yet.** The server sets `openapi_url=None`, and no versioned OpenAPI document is
   generated. The client is hand-written over the documented paths and does not come from an
   OpenAPI document.
4. **`deeptwin_ext` has only the historical helpers.** It does not yet ship read-only,
   hash-equal bindings to the core-owned `extension-ports-v1` schemas, or refinement authoring.
5. **Not in this slice:** `app/api/extension_routes.py` / `extensions-v1.json` /
   `test_extension_route_registration.py` (the extension route surface is still the separate
   `extension-candidates-v1`, `extension-bindings-v1` and provider contributions), and the
   out-of-tree OCI tool fixture.
