# API surface and compatibility (draft)

Date: 2026-09-23 · Status: **draft for T084**. Normative source: `contracts/api.md` (`api-v1`) and
`contracts/verification.md`. This page describes the routes the supported factory (`create_app` in
`app/server.py`) mounts today and the compatibility rules that apply to them.

The HTTP API currently serves the official browser UI. An installable HTTP/OpenAPI client and
service-client (bearer) automation are **not yet provided** (see §5).

## 1. Route families

| Family | Prefix | Versioned | Source of truth |
| --- | --- | --- | --- |
| Owner session and shell | `/`, `/health`, `/session`, `/session/bootstrap`, `/session/login`, `/session/logout`, static assets | no (fixed by design) | `app/api/session_routes.py`, `app/api/assets.py` |
| Domain API | `/api/v1/…` | yes, major `v1` | `app/api/route_contributions/*.json` |
| Development preview only | `/api/works…`, `/api/speech…` and others | no | `create_development_app` in `app/server.py`; **not** part of the supported surface |

All paths are relative to the deployment's validated base path (`OriginProfile.base_path`).

## 2. Route contributions

Every supported `/api/v1` route is declared in a build-installed JSON descriptor with schema
`deeptwin-first-party-route-contribution-v1`:

```json
{ "schema_version": "deeptwin-first-party-route-contribution-v1",
  "contribution_id": "works-v1",
  "factory": "app.api.works:create_router",
  "routes": [ { "route_id": "works.read", "methods": ["GET", "HEAD"],
                "path": "/api/v1/works/{work_id}",
                "auth_policy": "browser_session", "required_scope": "work.read" } ] }
```

`app/api/router_composition.py` refuses composition unless: the descriptor directory holds exactly
the expected file set (no extra, missing, symlinked or hardlinked file); each descriptor is within
64 KiB and parses as a closed object; the factory matches `app.api.<module>:create_router` and is in
the build allowlist (`app/api/first_party_catalog.py`); every path matches `^/api/v1/…` with no
dot segments; methods, auth policies and scopes come from closed sets; and route IDs are unique.
The composed set is mounted once. There is no runtime route registry and extensions cannot add
routes.

Current inventory (54 routes, all `auth_policy: browser_session`):

| Contribution | Routes | Scopes |
| --- | --- | --- |
| `core-v1` | events list/stream/by-type, snapshot, command read/create (6) | `work.read`, `work.command` |
| `works-v1` | work create/read/revise, revision read, source upload/read/content, command receipt, export preview/confirm/download (11) | `work.read`, `work.command` |
| `runs-v1` | run create/read/resume/cancel/recover, artifacts list/read/content/preview, drafts list/save/read/freeze/differences, alternative-file upload, alternative difference read/observe (17) | `work.read`, `work.command` |
| `run-consents-v1` | record, read (2) | `work.command`, `work.read` |
| `run-approvals-v1` | record, read (2) | `approval.manage`, `approval.read` |
| `deployment-prepare-v1` | deployment and provider-deployment requests: prepare, cancel, read, receipt import, consume (10) | `deployment.manage`, `deployment.read` |
| `extension-candidates-v1` | candidate create, read (2) | `extension.manage`, `extension.read` |
| `provider-conformance-v1` | execute, read (2) | `extension.manage`, `extension.read` |
| `provider-installation-v1` | execute, read (2) | `extension.manage`, `extension.read` |

The descriptor files are the authoritative list; regenerate this table from them rather than
editing it by hand.

## 3. Wire conventions

- **Closed input.** Request bodies are closed JSON objects; unknown keys, duplicate keys and
  out-of-bound values are rejected rather than ignored.
- **Body limits** are enforced at the web boundary before parsing: 4 KiB for ordinary run routes,
  600 KB for draft saves, 5.6 MB for alternative-file uploads (4 MiB decoded), and route-specific
  limits for work and source uploads.
- **Commands are idempotent per command ID.** Replaying a command with identical content returns
  the original result; the same command ID with different content is a `conflict`.
- **Revision-safe writes.** Writes name the revision they were based on; a stale base gets
  `conflict` and nothing is overwritten.
- **Error envelope** (`contracts/api.md` §1):
  `{code, message, field_errors?, retryability, affected_refs, correlation_id}`. Codes are a closed
  set including `invalid_input`, `credentials`, `unauthenticated`, `access_denied`, `not_found`,
  `conflict`, `too_large`, `capacity`, `unavailable`, `setup_incomplete`, `setup_unavailable`.
  Clients branch on `code`, never on `message`.
- **Mutations** from the browser need the session cookie and the `X-DeepTwin-CSRF` header
  ([security.md](security.md)).

## 4. Compatibility policy

From `contracts/api.md`:

- The major version is part of the path (`/api/v1`). An unsupported major contract is rejected.
  The composer's path rule currently admits only `v1`; introducing `v2` is a deliberate code and
  contract change, not a descriptor edit.
- Additive, supported versions are negotiated explicitly.
- *Proposed working rule (not yet in the contract):* within a major version, new routes and new
  optional response fields may be added; removing a route, changing a field's meaning, tightening an
  accepted value or changing the error code for an existing condition requires a new major version.
  Because request objects are closed, a new request field is a breaking change for older servers.
- No adapter may reinterpret an old approval, target, effect, port operation or artifact selector.
- The unversioned owner-session routes are fixed; they carry no domain command aliases.
- The development-preview `/api/works…` routes are compatibility adapters for the preview only and
  carry no release compatibility promise.
- Semantic extension port schemas are a separate core-owned artifact set with their own version
  (`extension-ports-v1`); OpenAPI may reference their IDs but cannot redefine them.

No formal deprecation window or support period has been decided; that is an open release decision.

## 5. Not yet provided

- **OpenAPI document.** The supported factory sets `openapi_url=None`, `docs_url=None`,
  `redoc_url=None`. The contract requires a versioned OpenAPI document generated from the same types
  as the UI; it does not exist yet.
- **Service clients / bearer automation.** `/api/v1/service-clients` is specified but not
  mounted. Under the contract, bearer calls are portable-HTTPS only; the HTTP loopback profile must
  not register or parse bearer credentials, with no cookie or plaintext fallback.
- **Installable HTTP/OpenAPI client** (`deeptwin_client`) with parity proof from a separate process
  that does not import `app` (T087/T083).
- Contract routes such as `/extensions`, `/service-clients`, backup, retention/deletion and
  settings routes listed in `contracts/api.md` §2 that have no descriptor yet.
