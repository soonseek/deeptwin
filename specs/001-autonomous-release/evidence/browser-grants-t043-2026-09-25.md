# T043 slice — projection grants and the owner's persisted browser grants (2026-09-25)

Status: **projection enforcement and persisted grant authority landed; T043 stays open**
(see "Open"). Closes the first two open items of evidence/browser-worker-t043-2026-09-25.md.

## The contract, and the rule chosen

runtime.md §6: "Network GET is also outbound transmission: a grant binds both permitted
recipient and allowed source/projection categories. Browser URL/query/path/body generation
must not receive private diagnosis, alternatives, secrets or undeclared work content.
Derived URLs inherit source tags; only an explicitly permitted outbound projection can cross
the broker. The broker inspects the actual normalized request and source binding, including
referer/cookies, not only domains." and "Grants bind … tool/version, source/target, action,
… expiry/use count, byte limits and human/policy authority. Revalidate at every dispatch,
including redirects and resource subrequests."

A browser GET carries data only in its URL: the fetch service never forwards the browser's
request headers (no Cookie/Referer — the broker sends a fixed `Accept`; already pinned by the
worker tests) and there is no body. The projection is therefore a rule over the normalized
URL (`app/workers/fetch_channel.py`):

- `GrantProjection.entries`: each `ProjectionEntry` is one exact https URL without a query,
  plus the query parameters (in order) that may carry values, each bound to a declared
  `DataSource`. No parameters = **pure navigation, no source data**.
- `DataSource`: an owner-declared source; the grant holds only the SHA-256 digests of its
  values (`value_digest`, UTF-8). There is no other kind of source: work content, diagnosis,
  alternatives and secrets are never declarable.
- A **navigation** URL is admitted only if it is exactly an entry — for a parameterized entry,
  exactly `projected_url(entry, values)` (canonical `quote` encoding: no `+`, no needless
  percent-encoding, no extra/repeated/renamed parameter, no fragment) with each value's
  digest declared for the parameter's source (`projection_values`).
- **Derived requests** (subresources and every redirect hop the broker follows) inherit the
  navigation's source tags: a request toward any host other than the navigation's entry host
  must not carry any value an admitted navigation carried — raw, percent-decoded or
  form-decoded, case-insensitively (`carries_source_values`).
- A violation is the closed code `projection_denied` (added to the fetch, grant, browser
  worker, adapter and client code sets; a `denied`/`permission_denied` attempt).

Where it is enforced: control pre-checks the request URL before registering
(`BrowserClient.run`, `sent=false`); the fetch service checks the registration's
`navigation_url` (a new required field of `fetch-grant-request-v1` register) and seeds the
grant's tags from it, checks every `navigation` fetch against the entries (extending the
tags), and checks every request and each redirect hop in a transport wrapper *before* the
hop's connection is opened. The source-prefix and recipient checks keep their order and
codes (`grant_denied` first).

## Persisted grants

`app/services/browser_grants.py` — `PersistentBrowserGrants` over the bound store and owner
authority (the run-consent discipline):

- `create` (`browser-grant-command-v1`): one immutable `grant` record per command
  (`uuid5(command)`; replay returns the same view; any other body conflicts), authored by the
  owner's human actor with `approval.decided(approved)` in the same transaction. Content
  `browser-grant-v1`: label, tools (subset of `browser_navigate|read|screenshot` 1.0.0), the
  `BrowserGrant` mapping (sources, recipients, projection with digests, byte/request/
  redirect/ttl limits), `expires_at_utc` (≤ 90 days), `decided_at_utc`, event sequence. The
  typed values are hashed and never stored or shown back (the record bytes are checked).
- `revoke` (`browser-grant-revocation-command-v1`): one sealed `decision_record` per grant
  with `approval.decided(revoked)`; not undone, a second different revoke conflicts.
- `list`: every grant record with the writer's whole discipline (owner actor, identity from
  the command, grammar, decided event); other `grant` records are not browser grants and are
  skipped. State `active | revoked | expired`.
- `for_dispatch(ref, tool_id, version)`: the `BrowserGrant` built from the record only;
  `revoked`, `expired`, `tool_not_granted`, `unavailable`/`not_found`; the session TTL is
  clipped to the grant's remaining lifetime.
- `approved_tool_permissions(domain, environment_ref)`: environment record → its prepared
  head record → the design approval that head consumed (record id and canonical digest =
  the approval's `approval_sha`, environment id equal) → its `tool_permissions_ref` (kind
  `grant`). Anything without that chain has no approved tool permissions.

Routes: `browser-grants-v1` contribution (`app/api/browser_grants.py`): `browser_grants.read`
GET|HEAD `/api/v1/browser-grants` (work.read), `browser_grants.create` POST (work.command),
`browser_grants.revoke` POST `/{grant_id}/revoke` (work.command); shared `/api/v1`
preflight admits bodies exactly before auth; `no-store`. Installed routes 100 → **103**
(pinned counts/lists updated in test_web_owner_integration, test_first_party (104 with the
example), test_runs_api, test_works_api, test_provider_source_startup).

Screen: `settings.html#settings-grants` (`app/static/browser-grants.mjs`, served asset):
each grant's recipients, sources, projection (pure navigation, or `param ← 선언한 값 n개` —
never a value or digest), tools, expiry, state; a revoke control on active grants; a create
form (one exact address, optional one parameter with its values one per line, extra
recipient hosts, tools, 1–90 days). Server text via textContent only. The settings hub's
entry list is unchanged.

Dispatch (`app/runtime/browser_attempt_transport.py`): `build(..., grants=PersistentBrowserGrants)`
— no grant object is accepted any more; the grant is `for_dispatch(binding.grant_ref)` and the
request URL must pass sources and projection. Per attempt, before anything is sent, the run's
`environment_ref` must resolve (`approved_tool_permissions`) to exactly `binding.grant_ref` and
the record must still be current; otherwise the ToolCall is settled `failed` and the attempt is
`denied` / `permission_denied` / `not_observed` with final zero-tool usage. The sealed output
record names the grant record as a parent. `BrowserToolset(client, grants=…)`; the server
builds it with `PersistentBrowserGrants(domain_store, owner_authority)`.

## Observed

- `app/tests/test_browser_grants.py`: **13 passed** — grammar (exact entries, canonical
  spelling, digest-declared values), closed projection objects, fetch-service enforcement
  over the real frame codec (registration/navigation/subresource/redirect hop, tags extended
  by a later navigation, network never reached), control-side refusal (`sent=false`), owner
  records (replay, conflict, 9 invalid shapes, digests only in the record bytes, revoke,
  conflict on a second revoke), expiry/tool/foreign-record refusals with an injected clock,
  routes (no CSRF 403, foreign Origin 403, 201, list without values, query 400, extra field
  400, revoke 403 without CSRF, 200, unknown 404, `approval.decided` approved→revoked, no
  session 401), dispatch refusals through the real dispatcher/ledger with the real design
  approval chain (revoked after build, expired after build, run approved for another grant —
  each `denied`/final with nothing reaching the fetch service), the approval chain resolver,
  and a projection refusal at dispatch.
- `app/tests/test_browser_worker.py`: **33 passed** (two consecutive full runs), root, Linux,
  local headless Chromium 141. Existing cases now use exact pure-navigation projections; the
  in-thread dispatch cases run under an owner vault with a persisted grant and a real design
  approval chain. New real-process cases (unmodified fetch entrypoint as 20104, browser in its
  own netns as 20105, requester 20102):
  - `declared`: `read https://granted.test/search?q=deeptwin` rendered ("found it");
  - `undeclared_local`: `projection_denied`, `sent=false`; `undeclared_register` (control's
    pre-check bypassed): the fetch worker refuses the registration, `projection_denied`;
    `undeclared_navigation` (registered for `/`, browser asked for `/search?q=private-diagnosis`)
    and `respelled` (`?q=deeptwin&x=1`): the fetch worker refuses the navigation;
    `unlisted_path` (`/private-notes`, under the source, not an entry): `projection_denied`;
  - `derived_image`: `/leak?q=deeptwin` renders; its `<img>` to `other.test/collect?v=deeptwin`
    is refused while its value-free `other.test/tracker.png` is fetched (other.test *is* a
    recipient: only the projection stops it); `derived_redirect`: a 302 to
    `other.test/collect?v=DeepTwin` is refused before connecting;
  - the fixture site saw the declared request and the tracker, never `/collect…`, never
    `private-diagnosis`/`private-notes`; logs carry only `event`/`class`/`outcome`/`pair`;
  - dispatch: the graph node reads `/search?q=deeptwin` through the real worker under the
    owner's persisted grant (sealed result names the grant record); with the grant revoked
    after the transport is built the attempt is `denied`/final, ToolCall `failed`, and the
    site received nothing.
- `app/tests/settings-grants.test.mjs` (node): **5 passed** — form → exact command (and 14
  local refusals), view → lines (pure navigation, value counts, tools, expiry, state),
  text-only rendering with revoke on active grants only, unauthenticated state, the page
  mounts the section and module.
- `app/tests/browser-grants.test.mjs` (real Chromium against the real server,
  `fixtures/grants_server.py`): **1 passed** — invalid address refused on the page without a
  POST; create through the form; the row shows recipients, sources, projection, tools, expiry,
  `유효`; no typed value anywhere on the page; the server list holds exactly the two values'
  SHA-256 digests and a 7-day expiry; revoke → `철회됨`, no revoke control; no page errors.
- Kept passing (one serial run): test_browser_worker, test_browser_grants, test_egress*,
  test_extension_*, test_server*, test_web_owner_integration, test_first_party,
  test_web_shell_assets, test_runs_api, test_works_api, test_provider_source_startup —
  **1268 passed, 3 skipped**; test_first_party_dependencies, test_credential_import_boundary,
  test_deployment_receipt_api, test_provider_receipt_api, test_document_codec,
  test_core_import_boundary, test_client_conformance, test_tool_boundary,
  test_run_artifact_previews, test_scheduler_attempt_dispatch, test_environment_records,
  test_design_store, test_run_consents, test_router_composition, deploy/tests
  test_compose_topology / test_worker_boundary / test_worker_listener — **349 passed**;
  node settings/session tests pass.

## Open (why T043 stays unchecked)

- **Production authority.** No production graph authority registers the browser
  ToolDefinitions (`ClaudeRunExecutor` still compiles with `tool_definitions=[]`), so no
  product run can bind a browser tool yet; the design workspace still derives
  `tool_permissions` from the graph's first tool binding. Everything below that seam — record,
  approval chain, dispatch re-check — is real and tested.
- **Projection scope.** Values may appear only in declared query parameters; path-segment
  projections are not offered (an entry's path is fixed). Derived-request tagging is exact
  matching of the carried values (raw/percent/form-decoded, case-insensitive); an encoding a
  hostile page invents beyond those (e.g. base64 of a value) toward another *granted*
  recipient is not detected — the grant's recipient list remains the outer bound. Only
  owner-declared value sets exist as sources; no work-content source category is declarable.
- **PK-06 with scripts on**, **packaging (T081/T089)** and **container qualification
  (T081/T079)**: unchanged from evidence/browser-worker-t043-2026-09-25.md.
