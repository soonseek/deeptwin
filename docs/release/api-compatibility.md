# API surface and compatibility (draft)

Date: 2026-09-23 · Updated: 2026-09-26 · Status: **draft for T084**. Normative source: `contracts/api.md` (`api-v1`) and
`contracts/verification.md`. This page describes the routes the supported factory (`create_app` in
`app/server.py`) mounts today and the compatibility rules that apply to them.

The HTTP API serves the official browser UI. Since 2026-09-26 the owner can create scoped
service clients, and on the portable HTTPS profile a client's bearer can read the public snapshot
and event routes (§3a). Bearer commands, an OpenAPI document and the extension-specific client
surface are **not yet provided** (see §5).

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

Current inventory (146 routes in 29 contributions; auth policies: `browser_session`, `browser_session_or_service_bearer`):

| Contribution | Routes | Scopes |
| --- | --- | --- |
| `core-v1` | events.read, events.stream, events.type, snapshot.read, commands.read, commands.create (6) | `events.read`, `snapshot.read`, `work.command`, `work.read` |
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
| `runs-v1` | runs.create, runs.read, runs.resume, runs.cancel, runs.recover, runs.artifacts, runs.artifact, runs.artifact_content, runs.artifact_preview, runs.artifact_page, runs.artifact_page_image, runs.artifact_drafts, runs.artifact_draft_save, runs.artifact_draft, runs.artifact_draft_freeze, runs.artifact_alternative_file, runs.artifact_draft_differences, runs.alternative_difference, runs.alternative_difference_observe, runs.environments (20) | `work.command`, `work.read` |
| `artifact-index-v1` | artifacts.index (1) | `work.read` |
| `run-trace-v1` | runs.trace (1) | `work.read` |
| `run-feedback-v1` | runs.feedback, runs.feedback_record (2) | `work.command`, `work.read` |
| `graphs-v1` | graphs.read (1) | `work.read` |
| `design-workspace-v1` | design_requests.list, design_requests.create, design_requests.read, design_requests.derive, design_requests.review, design_requests.prepare, design_requests.generate, design_requests.cancel (8) | `work.command`, `work.read` |
| `hypotheses-v1` | hypotheses.read, hypotheses.propose (2) | `work.command`, `work.read` |
| `inquiries-v1` | inquiries.read, inquiries.open, inquiries.answer, inquiries.evidence, inquiries.judge, inquiries.audit (6) | `work.command`, `work.read` |
| `versions-v1` | versions.read, versions.adopt, versions.decide, versions.activate, versions.rollback, versions.tool_effect_boundaries.read, versions.tool_effect_boundaries.decide (7) | `work.command`, `work.read` |
| `deployment-prepare-v1` | deployment.requests.prepare, deployment.requests.cancel, deployment.requests.read, deployment.requests.receipts.import, deployment.requests.consume, deployment.provider-requests.prepare, deployment.provider-requests.cancel, deployment.provider-requests.read, deployment.provider-requests.receipts, deployment.provider-requests.consume (10) | `deployment.manage`, `deployment.read` |
| `provider-conformance-v1` | extensions.provider-conformance.execute, extensions.provider-conformance.read, extensions.provider-transport-qualification.read, extensions.provider-transport-qualification.execute (4) | `extension.manage`, `extension.read` |
| `provider-installation-v1` | extensions.provider-installation.execute, extensions.provider-installation.read (2) | `extension.manage`, `extension.read` |
| `extension-bindings-v1` | extensions.installations.list, extensions.bindings.list, extensions.bindings.read, extensions.bindings.slot_key, extensions.bindings.bind, extensions.bindings.disable, extensions.bindings.rollback, extensions.bindings.retention_release (8) | `extension.manage`, `extension.read` |
| `browser-grants-v1` | browser_grants.read, browser_grants.create, browser_grants.revoke (3) | `work.command`, `work.read` |
| `platform-update-v1` | platform.update.read (1) | `deployment.read` |
| `service-clients-v1` | service-clients.list, service-clients.create, service-clients.read, service-clients.rotate, service-clients.revoke (5) | `service_client.manage`, `service_client.read` |

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

## 3a. Service clients and bearer reads (T025, 2026-09-26)

The owner manages clients through `service-clients-v1`, a browser-session contribution (cookie and,
for every POST, CSRF):

| Route | Effect |
| --- | --- |
| `GET /api/v1/service-clients` | the owner's clients (no secret, no digest) |
| `POST /api/v1/service-clients` | create `{client_id, name, scopes, allowed_network_profile, expires_at}`; 201 returns the `dt_sc_` secret **once** |
| `GET /api/v1/service-clients/{client_id}` | one client (no secret) |
| `POST …/{client_id}/rotate` | `{expected_revision}`; new secret once, the old one stops at once |
| `POST …/{client_id}/revoke` | `{expected_revision}`; the next bearer request is refused |

Creation is refused (`422 invalid_state`) unless the instance runs the portable HTTPS profile,
`allowed_network_profile` is exactly that profile, the expiry is at most 24 hours ahead, and every
scope is one some composed route declares for a bearer.

A route admits a bearer only when its descriptor declares `auth_policy`
`browser_session_or_service_bearer`; `required_scope` is then the scope the client must hold:

| Route | Bearer scope |
| --- | --- |
| `GET\|HEAD /api/v1/snapshot` | `snapshot.read` |
| `GET\|HEAD /api/v1/events`, `/api/v1/events/stream`, `/api/v1/events/{event_type}` | `events.read` |

A bearer request sends exactly one `Authorization: Bearer dt_sc_…` header over TLS, no cookie and
no CSRF. Responses: `401 unauthenticated` for a missing, malformed, unknown, expired, rotated or
revoked credential, for any bearer on a browser-session-only route, and for any bearer on the loopback
profile; `403 access_denied` for a valid credential without the route's scope; `429 capacity` when
the client, source or route bucket is empty; `400 invalid_input` for a duplicated header. Every other
route stays browser-session only. Which further routes and scope names a bearer may reach is an open
owner decision (`evidence/bearer-service-clients-2026-09-26.md`).

## 3b. Run trace and event subject filters (2026-09-26, UI phase 3)

`GET|HEAD /api/v1/runs/{run_id}/trace` (`run-trace-v1`, route `runs.trace`, scope `work.read`) is a
browser-session read of what one run already recorded; a bearer gets `401` like on every other
browser-session route. No query and no body are accepted. The response is `run-trace-v1`
(`contracts/api.md` §2, row "Runtime (implemented 2026-09-26, `run-trace-v1`)"): visits and
attempts with their times and outcomes, each attempt's own inputs, outputs, tool calls, budget
reservation and error, the Claude executor's model calls with the provider's token usage, the
hand-offs the run recorded, the approvals, a time-ordered timeline, the graph's final results and
where the run stopped. A value the runtime did not record is the string `not_recorded`, and each
category not recorded is named with its reason in `gaps`. Errors: `400` malformed id, query or body,
`401` no session, `404` unknown run, `503` executor or ledger unavailable.

Additive fields (2026-09-26, recorded usage): each attempt carries `tokens`, `observed_model`,
`provider_message_id` and `request_id` (what the provider reported to its transport, or
`not_recorded`); a `reserved_ceiling` estimate carries `method` (`reservation`, or
`recorded_tokens_at_ceiling_rates` with the `rates` used); a model call's `cost` is recorded with
the call (`subscription_mode`, a ceiling-rate estimate, or `not_recorded`). No field was removed or
renamed; a reader that ignores unknown keys is unaffected.

`GET|HEAD /api/v1/events`, `/api/v1/events/stream` and `/api/v1/events/{event_type}` accept at most
one of `run_id` or `work_id` (canonical UUID, once). The filter keeps only events whose own record
names the subject: `work_id` — an object reference to that work's `work_revision`; `run_id` — the
run's own `run.started`/`run.stopped` (their correlation is the command that created the run, from
which the run id is derived) or an object reference to the run or one of its ledger attempts. An
approval decision carries neither, so it is not matched by `run_id` (the trace lists approvals from
their records). The subject is part of the cursor's filter identity: a cursor read under one
subject is refused (`400`) under another or none. Existing cursors are unchanged.

## 3c. Process feedback on a run (2026-09-26, UI phase 4)

`run-feedback-v1` adds two browser-session routes on one path (a bearer gets `401` before any
parsing, like on every other browser-session route):

- `GET|HEAD /api/v1/runs/{run_id}/feedback` (`runs.feedback`, scope `work.read`): no query, no body.
  Response `process-feedback-list-v1`: `run_id`, `memo_max_chars` (4000), `marks`
  (`ok`, `needs_attention`), `current {run, steps[]}` (the latest revision of every target, a
  cleared one included with `state: cleared`) and `history[]` (every revision in recorded order).
  An item is `feedback_id`, `revision`, `target`, `state` (`set`/`cleared`), `mark` (or null),
  `memo` (or null), `recorded_at_utc`, `ref`. `Cache-Control: no-store`.
- `POST /api/v1/runs/{run_id}/feedback` (`runs.feedback_record`, scope `work.command`): one
  `process-feedback-command-v1` command, exactly `schema_version`, `command_id`, `action`
  (`set`/`clear`), `target` (`{scope: run}` or `{scope: step, node_id, visit_no, attempt_no}`, where
  `attempt_no` is null only for a visit the executor ran without ledger attempts),
  `expected_revision` (0 for a target without feedback), `mark` (`ok`/`needs_attention`/null) and
  `memo` (null, or 1–4,000 characters with a visible character; tabs and line breaks kept, other
  control characters refused). A set needs a mark or a memo (either alone is complete; no
  explanation is ever required); a clear carries neither. Answer `201` with the recorded revision,
  `replayed` and the new `current`.
- Errors: `400` malformed id, shape, value or an empty set, a clear of nothing; `401` no session or a
  bearer; `403` no CSRF token or a foreign origin; `404` unknown run, node, visit or attempt;
  `409` a stale `expected_revision` or a reused command id with another body; `413` a memo over
  4,000 characters or a body over 64 KiB; `503` storage or the run executor unavailable.
- A write is the owner-command path: CSRF-verified same-origin POST, one command id (an exact
  replay returns the same revision), the immutable `process_feedback` record and its public
  `feedback.recorded` event in one transaction. The event carries `scope`, `mark` (`none` when
  absent), `memo` (whether one exists), `cleared` and `revision` — never the memo text — and names
  the run, so `GET /api/v1/events?run_id=` lists it.
- `run-trace-v1` gains, additively, `feedback {run, steps}` at the top level, `feedback` on every
  attempt and visit (the current set feedback of that exact target, or null) and `links.feedback`.
- The work export's `events` category gains, when a run of the work has feedback,
  `events/run-feedback.json`: every revision as metadata (target, mark, state, memo length), never
  the memo text. It is never under `alternatives`.
- Process feedback is not an alternative and is never counted as one (UX-AC05).

## 3d. Additive fields for the work steps and the reload of 차이 살펴보기 (2026-09-26, UI phase 5)

No route was added (146 routes in 29 contributions stay). Two existing responses gain fields; no
field was removed or renamed, and a reader that ignores unknown keys is unaffected.

- `GET /api/v1/design-requests` (`design-workspace-v1`): each `requests[]` item gains `work_id` and
  `work_revision` — the work revision the request's confirmed work model was made from. `GET
  /api/v1/design-requests/{id}` gains `request.work_revision_ref` (the full reference). The work
  page uses them to show a work's own design requests.
- `GET /api/v1/runs/{run_id}/artifacts/{artifact_id}/drafts` and `…/drafts/{draft_id}`
  (`runs-v1`): each draft gains `frozen_alternatives[]` (`alternative_id`, `revision`, `coverage`,
  `frozen_at_utc`), oldest revision first, beside the unchanged `frozen_revisions`. A freeze is still
  one alternative per command (freezing the same revision again seals another one); the run screen
  uses the list to reopen an existing difference after a reload instead of freezing again.

## 3e. The run's recorded mode on the run trace (2026-09-26, UI phase 6)

No route was added (146 routes in 29 contributions stay). One response gains one field; nothing was
removed or renamed, and a reader that ignores unknown keys is unaffected.

- `GET /api/v1/runs/{run_id}/trace` (`run-trace-v1`) gains `run_mode`: the `mode` the runtime ledger
  froze in the run's spec (`live`, `replay`, `snapshot` or `isolated-comparison`), or `not_recorded`
  when the ledger holds no run row for it. It is read, never inferred. The run screen shows the mode
  badge from it: `live` is 운영 and `isolated-comparison` is 격리 실험; any other value shows no badge.
  Every run the runs service starts is `live`; paired comparison rounds run in their own ledger and
  are not listed by the runs routes.
- The settings page's 서비스 클라이언트 panel uses the existing `service-clients-v1` routes (§3a)
  unchanged.

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
- **Bearer commands and further bearer routes.** Only the snapshot and event reads admit a bearer
  (§3a). No command, artifact or extension route does: the contracts name no service-client scope for
  them (open owner decision).
- **Client parity for commands.** The installed `deeptwin_client` (separate package, T087) reads
  the bearer routes over TLS from a process that cannot import `app`, and gets the browser's
  projection and cursor. Command receipt and event-order parity across restart and concurrency
  waits on a bearer command route (T087/T083).
- Contract routes listed in `contracts/api.md` §2 that have no descriptor yet, among them
  the code-free definition import and retirement/uninstall arms of
  `/extensions`, `/extension-deployment/requests`, the managed-login connection routes (T088) and
  `/speech/sessions` (T024).
- **Documented deviations.** The artifact routes are served run-scoped
  (`/api/v1/runs/{run_id}/artifacts/{artifact_id}/…`, with `artifacts.index` returning the run id)
  rather than as `/artifacts/{id}/…`; extension bindings are served at `/api/v1/extensions/bindings…`
  with the extension id in each body, because an `/extensions/{id}/…` segment would collide with the
  fixed `candidates`, `provider-installation`, `provider-conformance` and
  `provider-transport-qualification` segments (`evidence/extensions-ui-2026-09-25.md`).
