# API surface and compatibility (draft)

Date: 2026-09-23 · Updated: 2026-09-25 · Status: **draft for T084**. Normative source: `contracts/api.md` (`api-v1`) and
`contracts/verification.md`. This page describes the routes the supported factory (`create_app` in
`app/server.py`) mounts today and the compatibility rules that apply to them.

The HTTP API currently serves the official browser UI. An installable HTTP/OpenAPI client and
service-client (bearer) automation are **not yet provided** (see §5).

## 1. Route families

| Family | Prefix | Versioned | Source of truth |
| --- | --- | --- | --- |
| Owner session and shell | `/`, `/health`, `/session`, `/session/bootstrap`, `/session/login`, `/session/password`, `/session/revoke-others`, `/session/logout`, static assets | no (fixed by design) | `app/api/session_routes.py`, `app/api/assets.py` |
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

Current inventory (128 routes in 25 contributions; auth policies: `browser_session`):

| Contribution | Routes | Scopes |
| --- | --- | --- |
| `core-v1` | events.read, events.stream, events.type, snapshot.read, commands.read, commands.create (6) | `work.command`, `work.read` |
| `extension-candidates-v1` | extensions.candidates.create, extensions.candidates.list, extensions.candidates.read (3) | `extension.manage`, `extension.read` |
| `run-approvals-v1` | runs.approvals.record, runs.approvals.read, runs.execution_approvals.record, runs.execution_approvals.read (4) | `approval.manage`, `approval.read` |
| `works-v1` | works.receipt, works.source_upload, works.revision, works.source, works.source_content, works.export_preview, works.export_confirm, works.export_download, works.deletion_preview, works.deletion_confirm, works.create, works.read, works.revise (13) | `work.command`, `work.read` |
| `run-consents-v1` | run_consents.record, run_consents.read, run_consents.revoke (3) | `work.command`, `work.read` |
| `claude-connection-v1` | connections.claude.read, connections.claude.key, connections.claude.forget, connections.claude.catalog, connections.claude.model_choice (5) | `work.command`, `work.read` |
| `backups-v1` | backups.read, backups.preview, backups.create, backups.ciphertext, backups.receipt, backups.restore_begin, backups.restore_read, backups.restore_upload, backups.restore_upload_portable (9) | `work.command`, `work.read` |
| `retention-v1` | retention.read, retention.cleanup_preview, retention.cleanup (3) | `work.command`, `work.read` |
| `credentials-v1` | credentials.read, credentials.store, credentials.delete, credentials.fence, credentials.catalog_refresh, credentials.model_choice (6) | `work.command`, `work.read` |
| `work-models-v1` | work_models.draft, work_models.read, work_models.confirm (3) | `work.command`, `work.read` |
| `source-readings-v1` | source_readings.list, source_readings.read, source_readings.latest (3) | `work.command`, `work.read` |
| `conversations-v1` | conversations.read, conversations.message, conversations.propose, conversations.challenge, conversations.approve (5) | `work.command`, `work.read` |
| `budget-policies-v1` | budget_policies.list, budget_policies.create (2) | `work.command`, `work.read` |
| `runs-v1` | runs.create, runs.read, runs.resume, runs.cancel, runs.recover, runs.artifacts, runs.artifact, runs.artifact_content, runs.artifact_preview, runs.artifact_page, runs.artifact_page_image, runs.artifact_drafts, runs.artifact_draft_save, runs.artifact_draft, runs.artifact_draft_freeze, runs.artifact_alternative_file, runs.artifact_draft_differences, runs.alternative_difference, runs.alternative_difference_observe (19) | `work.command`, `work.read` |
| `artifact-index-v1` | artifacts.index (1) | `work.read` |
| `graphs-v1` | graphs.read (1) | `work.read` |
| `design-workspace-v1` | design_requests.list, design_requests.read, design_requests.derive, design_requests.review, design_requests.prepare (5) | `work.command`, `work.read` |
| `hypotheses-v1` | hypotheses.read, hypotheses.propose (2) | `work.command`, `work.read` |
| `versions-v1` | versions.read, versions.adopt, versions.decide, versions.activate, versions.rollback, versions.tool_effect_boundaries.read, versions.tool_effect_boundaries.decide (7) | `work.command`, `work.read` |
| `deployment-prepare-v1` | deployment.requests.prepare, deployment.requests.cancel, deployment.requests.read, deployment.requests.receipts.import, deployment.requests.consume, deployment.provider-requests.prepare, deployment.provider-requests.cancel, deployment.provider-requests.read, deployment.provider-requests.receipts, deployment.provider-requests.consume (10) | `deployment.manage`, `deployment.read` |
| `provider-conformance-v1` | extensions.provider-conformance.execute, extensions.provider-conformance.read, extensions.provider-transport-qualification.read, extensions.provider-transport-qualification.execute (4) | `extension.manage`, `extension.read` |
| `provider-installation-v1` | extensions.provider-installation.execute, extensions.provider-installation.read (2) | `extension.manage`, `extension.read` |
| `extension-bindings-v1` | extensions.installations.list, extensions.bindings.list, extensions.bindings.read, extensions.bindings.slot_key, extensions.bindings.bind, extensions.bindings.disable, extensions.bindings.rollback, extensions.bindings.retention_release (8) | `extension.manage`, `extension.read` |
| `browser-grants-v1` | browser_grants.read, browser_grants.create, browser_grants.revoke (3) | `work.command`, `work.read` |
| `platform-update-v1` | platform.update.read (1) | `deployment.read` |

The descriptor files are the authoritative list; regenerate this table from them rather than
editing it by hand.

## 3. Wire conventions

- **Closed input.** Request bodies are closed JSON objects; unknown keys, duplicate keys and
  out-of-bound values are rejected rather than ignored.
- **Body limits** are enforced at the web boundary before parsing: 4 KiB for run, consent,
  approval, deployment and conformance routes, 600 KB for draft saves, 5.6 MB for alternative-file
  uploads (4 MiB decoded), 1 MiB for an extension-candidate registration, 64 MiB for a backup
  restore upload, and route-specific limits for work and source uploads.
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
- Contract routes listed in `contracts/api.md` §2 that have no descriptor yet, among them
  `/service-clients`, the code-free definition import and retirement/uninstall arms of
  `/extensions`, `/extension-deployment/requests`, the managed-login connection routes (T088) and
  `/speech/sessions` (T024).
- **Documented deviations.** The artifact routes are served run-scoped
  (`/api/v1/runs/{run_id}/artifacts/{artifact_id}/…`, with `artifacts.index` returning the run id)
  rather than as `/artifacts/{id}/…`; extension bindings are served at `/api/v1/extensions/bindings…`
  with the extension id in each body, because an `/extensions/{id}/…` segment would collide with the
  fixed `candidates`, `provider-installation`, `provider-conformance` and
  `provider-transport-qualification` segments (`evidence/extensions-ui-2026-09-25.md`).
