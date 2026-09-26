# T025 slice: service clients and bearer reads on the supported factory (2026-09-26)

Status: **mounted and tested; T025 and T087 stay open.** This slice mounts the common service-client
path the contracts assign to T025, and only as far as the contracts ground it. Where the contracts
leave a choice open, the slice stops at the smallest subset and records the choice as an open owner
decision (`decisions.md`, 2026-09-26 "Open owner decisions from the T025 bearer slice").

## Contract basis

- `contracts/api.md` §1:
  - `BrowserSession` and service-client credentials use distinct namespaces.
  - A service client exists only after the owner creates it from the authenticated web UI.
  - Its secret is shown once and only its digest is stored.
  - It is restricted to the declared HTTPS network profile, an expiry of at most 24 hours, and
    scopes.
  - Bearer calls "require TLS, reject browser-cookie fallback, and use exact Host, rate limits".
  - Service credentials cannot call bootstrap, manufacture an approval or broaden their own scope.
  - "every GET/HEAD/snapshot/SSE/download requires an owner session or scoped `ServiceClient`".
  - HTTP classes: "401 session; 403 scope/consent … 429 bounded capacity".
- `contracts/api.md` §1 (T025 ownership paragraph): T025 owns `service_clients.py`,
  `service_client_auth.py`, `app/api/service_clients.py` and the composition seam. Routes register
  through fixed descriptors with a required auth policy and scope. There is no unmounted adapter and
  no cookie fallback as proof.
- `contracts/api.md` §2, row "Service clients": "`/service-clients`, `/{id}` — T025 mounts/registers
  these routes; owner creates/rotates/revokes … secret is returned once and never by reads, bearer
  calls receive TLS/network/scope/rate-limit enforcement".
- `contracts/api.md` (§ on the HTTP client): "the HTTP-only loopback profile does not register or
  expose bearer automation: a fixed non-secret canary receives route-not-found or the specified
  pre-auth denial before bearer parsing".
- `data-model.md`, `ServiceClient` and `ServiceClientCredentialRevision`: durable principal and CAS
  head, immutable revisions, digest only, expiry ≤24h, rotate revokes the predecessor, recovery and
  revoke invalidate, last-used CAS, client and route buckets before dispatch.
- ADR-010 (two profiles) and ADR-014 (T025 owns the common authority and seam; loopback registers
  no bearer automation route).

## What landed

### Owner management (`service-clients-v1`)

`app/api/route_contributions/service-clients-v1.json` holds five `browser_session` routes. The
catalog entry is `app/api/first_party_catalog.py`, and the factory `service_client_services` is in
`app/api/service_clients.py`.

| Route id | Method and path | Effect |
| --- | --- | --- |
| `service-clients.list` | `GET /api/v1/service-clients` | owner's clients; no secret or digest |
| `service-clients.create` | `POST /api/v1/service-clients` | 201 with the `dt_sc_` secret once, `Cache-Control: no-store` |
| `service-clients.read` | `GET /api/v1/service-clients/{client_id}` | one client; no secret |
| `service-clients.rotate` | `POST …/{client_id}/rotate` | `{expected_revision}`; new secret once, predecessor dead |
| `service-clients.revoke` | `POST …/{client_id}/revoke` | `{expected_revision}` |

- The durable store is the existing `PersistentServiceClientRegistry` over the instance store, so a
  credential survives restart. Its secrets are 32 random bytes from `secrets.token_bytes`, and only
  their SHA-256 digests are stored.
- Owner verification requires an `AuthenticatedRequest` bound to the live session. A POST needs a
  CSRF-verified request, and the web boundary also enforces exact Origin and `Sec-Fetch-Site`.
- On the supported factory, creation is refused (`422 invalid_state`) unless all of these hold:
  - the instance runs `portable_https`
  - `allowed_network_profile` is exactly that profile (so `dedicated_https` is refused)
  - every scope is one a composed route declares for a bearer
  - the expiry is at most 24 hours ahead
- The registry itself still refuses the forbidden categories: bootstrap, auth, approval, promotion,
  deployment, recovery, service_client, credential and managed_login.
- A cheap wire preflight (`preflight`, wired into `preflight_api_v1`) admits the exact query and body
  shapes before any auth state, storage or entropy is touched.

### Bearer-admitting routes

- The new descriptor policy `browser_session_or_service_bearer` (`SERVICE_BEARER_POLICY` in
  `app/api/router_composition.py`) is the only way a route admits a bearer. Its `required_scope` is
  the scope the client must hold.
- `CompositionReceipt` now carries every declared route.
- `bearer_route(method, path)` admits only when every declared route matching the pair is
  bearer-admitting under a single scope. An overlapping template cannot expose a browser-only route.

| Route id | Path | Scope |
| --- | --- | --- |
| `events.read` | `GET\|HEAD /api/v1/events` | `events.read` |
| `events.stream` | `GET\|HEAD /api/v1/events/stream` | `events.read` |
| `events.type` | `GET\|HEAD /api/v1/events/{event_type}` | `events.read` |
| `snapshot.read` | `GET\|HEAD /api/v1/snapshot` | `snapshot.read` |

Every other route stays `browser_session`, including `commands.read`, `commands.create`, the
artifact routes, the extension reads and the service-client routes themselves.

### Web boundary (`app/api/web_boundary.py`)

- `Authorization` is now a singleton header, so a duplicate gets `400 invalid_input`.
- Any `Authorization` header gets the uniform `401 unauthenticated` **before the value is parsed**
  unless all of these hold:
  - the profile is `portable_https`
  - the connection scheme is `https`
  - no cookie is present
  - the route is a declared bearer route
- Plain HTTP to the portable profile is refused earlier, by the exact-scheme check (`403`).
- A declared bearer request skips session auth and CSRF. It is authorized by
  `ServiceClientAuthenticator`, which runs these checks in order:
  1. one exact `Bearer dt_sc_…` header and no cookie
  2. source and route buckets reserved
  3. durable lookup in one transaction: active head, same credential revision, not expired, same
     recovery epoch, network profile. The last-used CAS is also updated.
  4. client bucket
  5. declared scope
- Errors map to `401 unauthenticated`, `403 access_denied` for scope
  (`ServiceClientScopeDenied`) and `429 capacity` (`ServiceClientRateLimited`).
- The handlers receive a read-only `ServiceClientRead` (`app/domain/request_identity.py`). It holds
  no credential. `_public_reader` in `app/api/routes.py` accepts it only for the matching scope.
  `_authorized_reader` in `app/api/transaction.py` re-checks the grant after the read through
  `PersistentServiceClientRegistry.verify_current`, so a revoke, rotation or expiry committed while
  the read ran withholds the response.
- No mutation path accepts `ServiceClientRead`, and it never becomes an owner session.
- Rate buckets (provisional; open owner decision): burst 60, one token per second, 1,024 keys per
  dimension, 10-minute idle expiry.

### Recovery and backup

Unchanged and now live: owner recovery already revokes every service client in the reconciliation
transaction (`deployment_control.reconcile_recovery_in_transaction`). Backups exclude
`service_client_*` tables.

## Tests (one process per file, `env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q`)

### New: `app/tests/test_service_client_bearer.py` (9 passed)

This file runs on the composed supported factory:

- The descriptors declare exactly the four bearer routes and scopes. Commands are never bearer
  routes.
- The owner issues a client once. List and read never carry the secret. No table row in the instance
  database contains the secret, and captured logs never do.
- **Read parity:** the bearer snapshot and event page equal the browser's at the same point.
- Denials:
  - wrong scope gets 403
  - a browser-only route gets 401, including `commands/{id}`, extension reads, `service-clients`
    and a bearer-driven revoke
  - an unknown canary, a non-Bearer scheme and a bearer with a cookie get 401
  - a duplicate header gets 400
  - revocation gives 401 on the next request, and the other client is unaffected
- Owner commands need CSRF (403 without it). Command scopes, `artifact.read`, `dedicated_https` and a
  25-hour expiry get 422, and an extra field gets 400. Rotation kills the old secret.
- The credential survives a cold restart. Rate buckets give `[200, 200, 429]` at capacity 2.
- A revoke committed during a read withholds it (`verify` and `read_events` raise).
- On the loopback profile, creation gets 422 and a canary gets 401 even beside a live cookie. Plain
  HTTP to the portable profile gets 403.

### Rewritten: `app/tests/test_extension_client_blackbox.py` (2 passed)

- The installed `deeptwin-client` wheel runs in a fresh venv with `python -I` outside the
  repository, where `import app` fails.
- The server is the real `create_app` portable-HTTPS server under uvicorn over TLS.
- The owner bootstraps over TLS and gets a `Secure` cookie. Creation without CSRF gets 403. The owner
  then creates two clients: one with `snapshot.read`+`events.read`, one with `events.read` only.
- The client gets 200 from `/api/v1/snapshot` and `/api/v1/events`. Its bodies are **equal to the
  browser's** (same projection and `event_cursor`).
- The events-only client gets **403 `access_denied`** on the snapshot and 200 on events.
- `extensions/candidates`, `extensions/installations`, `extensions/bindings`, `commands/{id}` and
  `service-clients` each give **401**.
- After the owner revokes the first client, its snapshot and events give **401**. The other client
  still reads.
- An untrusted chain fails with `TLS verification or handshake failed`. An `http://` origin is
  refused before I/O. A plaintext request (canary only) to the TLS listener is not served.
- Neither secret nor the canary appears in the client's stdout or stderr, or in the server's stderr.
  The secrets travel only on stdin.

### Updated pins and other suites

Route counts went from 138 to 143: `test_first_party` (144 with its example), `test_web_owner_integration`
(ids and contributions), `test_runs_api`, `test_works_api`, `test_provider_source_startup`.
`specs/001-autonomous-release/tools/route_inventory.py --write` regenerated the table in
`docs/release/api-compatibility.md`.

Results are listed under "Run results" below.

## Run results (2026-09-26, one process per file, all exit 0)

| Group | Results |
| --- | --- |
| Route counts | test_first_party 17, test_web_owner_integration 80, test_runs_api 27, test_works_api 23, test_provider_source_startup 21 |
| Composition and reuse | test_router_composition 36, test_reuse_compliance 2, test_first_party_dependencies 34, test_extension_architecture 8 |
| Service clients | test_service_client_bearer 9, test_service_client_auth 18, test_service_client_routes 4, test_service_clients 16, test_service_clients_persistent 19, test_client_conformance 15 |
| SDK and black box | test_sdk_package_builds 15, test_sdk_package_install 8, test_extension_client_blackbox 2, test_extension_sdk 61, test_extension_spi 46 |
| Auth, session, CSRF, recovery | test_owner_sessions 5, test_session_security 8, test_local_session 32, test_server_session_integration 5, test_owner_password_change 4, test_owner_admission 13, test_session_root 14, test_bootstrap_delivery 14, test_session_gui_mirror 4, test_deployment_control 30, test_deployment_control_tool 11 |
| Other factory and storage suites | test_deployment_prepare_api 25, test_deployment_receipt_api 38 (both send a bearer on loopback and still get 401), test_deployment_consume_api 9, test_credential_gateway_startup 6, test_extension_bindings 7, test_run_approval_api 8 |
| Remaining `create_app`, `sqlite_master` and service-client users (40 files) | all passed. The only skips are the existing environment skips: DEEPTWIN_AGE_RUNTIME_ROOT or the backup worker not present (test_backup, test_backup_crypto_worker, test_backups_api, test_update_recovery) |

Browser tests were run with `CONTROL_PYTHON=$PWD/.venv/bin/python
CONTROL_PLAYWRIGHT_MODULE=/opt/node22/lib/node_modules/playwright/index.mjs node --test`, one file per
process:

| File | Passed |
| --- | --- |
| settings.test.mjs | 7 |
| settings-grants.test.mjs | 5 |
| records.test.mjs | 8 |
| records-page.test.mjs | 3 |
| records-backup.test.mjs | 10 |
| records-retention.test.mjs | 5 |
| records-update.test.mjs | 3 |
| browser-records.test.mjs | 5 (1 skipped: the existing backup-worker-unavailable skip) |
| browser-extensions.test.mjs | 2 |
| browser-owner-lifecycle-t025.test.mjs | 1 |
| browser-grants.test.mjs | 1 |
| browser-credentials.test.mjs | 1 |

## Open owner decisions (recorded in decisions.md, not decided)

1. **Routes a bearer may reach.** Only the public snapshot and event reads are admitted. Commands,
   command status, artifacts and extension reads await the owner's decision. No contract lists them.
2. **Scope names.** Only `snapshot.read` and `events.read` are grantable. They come from the existing
   T025 registry grammar, because the contracts name no scopes. `command:<category>.<action>`,
   `artifact.read` and extension-read scopes are not grantable.
3. **Rate-bucket numbers.** The values are provisional; see above.

## Still open

- **T025:**
  - bearer commands with the same `command_id`/revision/permission/budget/event/audit semantics
    (`HeadlessCommandSurface` still has no production caller)
  - a Settings UI for service clients (the routes exist; no screen yet)
  - the recovery items already listed in tasks.md
  - `CredentialVault`/`credential_client`
- **T087:**
  - command receipt, revision, authority and event-order parity across restart and concurrency.
    This needs a bearer command route. Read parity is shown, but that is not the T087 sentence.
  - extension-read scopes with its own `extensions-v1.json`
  - OpenAPI
  - `deeptwin_ext` port-schema bindings
  - the OCI tool fixture
- **T083:** repeating the client parity on the final distribution.
