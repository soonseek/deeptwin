# Web UI/API and command contract

The supported owner path now includes fixed `POST /api/v1/extensions/candidates` and
`GET|HEAD /api/v1/extensions/candidates/{candidate_id}`. Their exact 1MiB input, closed receipt,
errors, inert storage, local-prefix projection and current-owner admission are frozen in
[extension-candidates.md](extension-candidates.md). This is unqualified metadata registration;
there is no stage/install endpoint. Supported composition is exactly core-v1 plus
extension-candidates-v1; historical preview remains separate.

2026-09-08 · `api-v1` · Target contract, not currently implemented endpoint inventory.
Keep existing `/api/works`, revisions, file and Codex/STT endpoints compatible while adding
versioned services. Domain types are in data-model.md; execution/approval semantics are not
reimplemented in the frontend. No endpoint executes user-supplied Python/shell/SQL.

## 1. Session, envelopes and errors

The edge binds only interfaces explicitly selected by the instance operator; the control plane is
internal-only. `local-no-terminal-v1` publishes loopback on the exact generated
`<instance-id>.localhost:port/<instance-path>/` origin/base path. `portable-compose-v1` uses the
release-pinned edge's operator-supplied TLS secrets and exact HTTPS host/origin; the initial profile
has no implicit ACME or unqualified external reverse-proxy dependency. A deployment-created,
one-use, short-lived capability may claim the first owner. Never put it or a session in URL query/fragment/logs. Reject cross-site,
unexpected Host, null/untrusted origins and arbitrary CORS. Page scripts receive no filesystem or
command-execution bridge.

Browser authentication has two explicit cookie profiles. Loopback HTTP uses a host-only HttpOnly
`deeptwin_session` cookie scoped to the random instance base path, `SameSite=Strict`, no Domain; it
does not claim `Secure` or the `__Host-` prefix over HTTP. HTTPS uses a Secure HttpOnly
`__Host-deeptwin_session` cookie with Path `/`, no Domain and `SameSite=Strict`. Both require exact
Host/Origin plus CSRF for mutations. Each browser token is 32 random bytes; the server stores only
its SHA-256 digest and enforces a 12-hour idle plus seven-day absolute lifetime. The CSRF value is
base64url-no-padding HMAC-SHA-256 under a separate 32-byte read-only control-plane session root over
ADR-008 canonical JSON `{domain:"deeptwin-csrf-v1",origin_base,session_token_b64url,recovery_epoch}`.
`origin_base` is the deployment-validated external base URL including its normalized trailing-slash
path; token/HMAC comparisons are constant-time and T025 publishes cross-profile test vectors.
Browser mutations carry the derived value exactly once in `X-DeepTwin-CSRF`; field names follow
HTTP's case-insensitive rules, but duplicate/comma-folded fields and noncanonical base64url values
are rejected.
Authenticated `GET /session` can return it again with `Cache-Control: no-store` after refresh
without changing authority. Login/bootstrap/password/recovery rotates the session. Cookies are not
port-isolated; the random host/path and cross-port tests reduce accidental collision but do not
claim defense from a malicious host administrator. Neither browser profile puts raw session/CSRF
values in JavaScript storage, a service worker or a URL, and neither can fall back to the other.

A one-shot `session-root-init` job exclusive-creates the 32-byte root and immutable generation/
recovery-epoch manifest in a separate named volume; only the control plane mounts it read-only.
Normal serving requires equal root/config/database epochs. During explicit recovery,
`session-root-maintenance` runs with the control plane stopped and atomically advances the root
generation and configured epoch. The next container may start only in recovery-reconciliation mode:
a valid deployment recovery receipt plus a strictly greater root epoch permits one DB transaction
to advance `OwnerAccount.recovery_epoch` and revoke every prior authenticator/session/service
client/unconsumed human capability/pending challenge. Only after commit can bootstrap/login/general
API serving resume. Equal epoch is a normal start; rollback, skipped epoch, wrong generation,
missing/malformed root or mismatch without the receipt fails closed. Root bytes never enter env/DB/log.
All root/key init jobs are update-safe: absent storage permits one O_EXCL create plus fsync; exact
valid existing state is verify-only no-op success; malformed ownership/version/epoch fails closed and
is never replaced. Initial session genesis may match configured epoch without a prior receipt, while
every subsequent maintenance/recovery generation requires its exact request-bound receipt.

The only unauthenticated session-establishment requests are bounded `POST /session/bootstrap`
and `POST /session/login`; neither is a domain/work command. Bootstrap requires exact configured
Host/Origin, an 8 KiB JSON/1,024 UTF-8 password-byte cap, deployment-minted one-use capability and
a deployment-global ten-minute/five-attempt claim window. Cheap schema/Host/Origin/capability-
verifier checks run before any Argon2 allocation. Atomically consume the capability and only then
hash the chosen password and issue the selected browser cookie plus the derived CSRF value.
It cannot itself authorize model/tool calls, data export, billing or promotion. All other
mutations require an authenticated owner session using the exact profile; a setup failure is not permission
to expose an unauthenticated fallback. No capability is returned by a public GET endpoint.
Capability delivery is behind a `BootstrapDeliveryPort`, not improvised by the web server. Both
profiles use the checksummed offline `deploy/bootstrap/index.html`, which uses WebCrypto to generate
a 32-byte raw capability and SHA-256 verifier without network access. It also creates the nonsecret
`OriginProfile={deployment_profile_id,instance_id,mode,scheme,host,port,base_path,origin_base,digest}`:
both modes generate a lowercase 32-hex-character 128-bit instance ID; local mode also generates a
lowercase 32-hex-character 128-bit
random base path and validates a selected port; portable mode validates an
operator-supplied HTTPS URL on an instance-dedicated hostname and requires `base_path=/` for the
`__Host-` cookie. `port` is always the effective 1..65535 integer, including 80/443 when omitted;
`origin_base` omits a default port. Local base path is exactly `/<hex32>/`, portable exactly `/`.
`digest` is SHA-256 over ADR-008 canonical JSON of the preceding fields, excluding
itself. Canonicalization rejects userinfo/query/fragment, IP-literal ambiguity, dot segments,
encoded separators and duplicate slashes; lowercases/IDNA-normalizes the ASCII host, removes a
scheme-default port and emits one normalized trailing slash. The helper outputs a Portainer/Compose configuration
block containing only verifier, recovery epoch and origin profile; it displays the raw capability
separately for one-time entry in DeepTwin's same-origin browser setup form. Both
`raw_capability_b64u` and `verifier_b64u` are canonical base64url-no-padding strings decoding to
exactly 32 bytes; shared JS/Python vectors and strict parsers reject alternate encodings. Edge,
control plane, bootstrap/session/CSRF and receipt verification require the same origin-profile digest. The raw
value MUST NOT be printed to ordinary logs, returned by a product GET, embedded in a URL or retained
after successful claim. Recovery rotates a new verifier only through the deployment authority, is
audited, invalidates older epochs/sessions and cannot silently replace an existing owner. The helper
is an inspectable deployment artifact, not a native/product launcher or the ordinary work UI.

`DeploymentControlPort` is outside ordinary product authority. The product can read a versioned
platform/health receipt, prepare an exact digest-bound update/recovery request and verify a returned
receipt. It has no method to create/stop containers, replace images, mutate volumes/TLS or access a
Docker socket. The initial Portainer/operator surfaces perform those privileged effects; no owner
or `ServiceClient` API scope implies host-administrator authority.

Each prepared `DeploymentRequest` is a closed tagged union. Its common envelope contains exact
`schema=deployment-request-v1`, `domain=deeptwin-deployment-request-v1`, request ID, closed `kind`,
a canonical-base64url 32-byte random request nonce, instance and origin-profile digests, exact
kind-specific `effect_payload`, a closed `preconditions` object, creator, creation/expiry and a SHA-256 request digest
over ADR-008 canonical JSON excluding only that digest. Release/update/recovery uses its separately
defined exact precondition object. The four extension kinds require common `preconditions={}` and
make the closed arm payload the only precondition authority; a mirrored or overriding head, revision,
target, dependency or other member under `preconditions` is rejected:

| `kind` / `effect_payload.schema_id` | Required fields after `schema_id,extension_id` | Fields that MUST be absent |
| --- | --- | --- |
| `extension_stage` / `deeptwin.extension-stage-request.v1` | manifest/descriptor/platform/new-service fields, exact `expected_installation_head`=`{state:"absent"}` or committed `{state:"uninstalled",revision,installation_record_digest}`, and next installation revision 1 or tombstone+1 respectively | every reachable-current/superseded installation or retirement field and every dependency/lineage/uninstall/retirement field |
| `extension_replace` / `deeptwin.extension-replace-request.v1` | new manifest/descriptor/platform/service-effect fields, `expected_current_head:{extension_id,revision,installation_record_digest}`, `expected_next_installation_revision=current+1`, `old_service_identity_must_remain_reachable:true` | absent-head marker, every superseded-installation/retirement/dependency/uninstall field and every future record/head ref |
| `extension_uninstall_current` / `deeptwin.extension-uninstall-current-request.v1` | `expected_current_head`, `expected_next_installation_revision=current+1`, exact five-field `service_to_uninstall`, `zero_dependency_snapshot_ref`, its canonical digest, `uninstall_reason` | manifest/descriptor/platform/new-service, superseded-installation/descendant-proof/retirement and every future record/head field |
| `extension_retire_superseded` / `deeptwin.extension-retire-superseded-request.v1` | `expected_current_head`, exact strict-ancestor `superseded_installation_ref`, exact five-field `service_to_retire`, descendant-proof ref/digest, zero-dependency snapshot ref/digest, `expected_retirement_head_state:"absent"`, `expected_next_retirement_revision:1`, `retirement_reason` | every next-installation/new-artifact/current-uninstall and every future record/head field |

All nested shapes are exact in data-model §3.2. Stage has no reachable current service; it starts from
never-installed absence or an exact uninstall tombstone so reinstall remains monotonic. Uninstall-current removes
the exact current service and advances to a tombstone; retire-superseded names an existing strict-
ancestor installation and leaves its descendant current head unchanged. The retirement dependency
snapshot contains empty active-binding, retained-rollback and active-environment sets, while the core
rechecks all three, backward ancestry and current-head CAS at receipt consumption. A request never
names a future installation/retirement record. Mixed payloads, non-empty extension `preconditions`,
missing required members and unknown kinds fail closed. Request bytes are immutable; prepared/
cancelled/receipt_pending/accepted/rejected/expired lives in a separate revisioned CAS lifecycle.

A separate one-shot deployment-receipt-root init writes physically separate
`deployment-signing-private` and `deployment-verify-public` volumes. The receipt job mounts only
private read-only and signs the exact receipt; the control plane mounts only the public trust set
read-only. Sealed requests and signed receipts use separate fixed exchange volumes with opposite
read/write mounts, content-digest filenames and staging+fsync+atomic rename; neither carries a Docker
socket/Portainer credential and a browser upload cannot enter this recovery channel.

`deployment-receipt-v1` carries `domain=deeptwin-deployment-receipt-v1`; Ed25519 signs ADR-008
canonical JSON of every exact field except `signature`. Public keys (32 bytes), request nonces/
digests and signatures (64 bytes) use canonical base64url without padding. Strict parsing rejects
duplicate/unknown fields/algorithms, and a deployment-pinned versioned public trust-set digest selects
the key ID. A receipt repeats request ID/digest/nonce/kind, instance/origin and carries the exact
matching result arm. Release results bind old/new release/schema/image-lock/epoch state. Extension
results use the four exact result schema IDs in data-model §3.2. Stage, replace and uninstall-current
bind old/new tagged service observations; retire-superseded binds preserved-current plus target-before/
target-after observations. Any repeated existing head, target, revision, dependency/lineage digest or
service tuple equals the request byte-for-byte, while every future installation/retirement record or
head is forbidden.

Observation arms are exactly `absent`, fully identified `present`, or bounded diagnostic `unknown`.
Successful stage is absent→present; successful replace is distinct present→present with old reachable;
successful uninstall-current is current-present→absent. Successful retire-superseded keeps the
descendant current service present/reachable while the exact ancestor target goes present→absent.
Every present/unknown new observation equals the requested five-field new tuple. Every current or
target present/unknown observation equals, or repeats as `expected_*`, the five-field tuple resolved
from its exact request-bound committed installation. Uninstall-current never permits old absent and
never substitutes another service. Retirement never permits target-after absent on failed/unknown and
cannot target current, a sibling or a non-ancestor. Missing or mismatched equality is receipt rejection,
not diagnostic latitude.

Receipt verification checks that branch plus adapter/version, timestamp/expiry, outcome, claimed/
verified/unverified fields, key ID and signature; mixed-kind results fail closed. Release/update/
recovery acceptance atomically inserts a unique `DeploymentReceiptConsumption` with the winning
lifecycle and transition without modifying the signed receipt. For an extension, verified receipt
state remains non-authoritative until independent postconditions succeed. Stage/replace/uninstall-
current success atomically creates the installation record or tombstone, advances its head, consumes
the receipt, advances lifecycle and publishes the event. Retire-superseded success creates only the
target-keyed retirement record/head and event while CAS-checking the unchanged current installation
head, strict ancestry and repeated zero-dependency query. Failed/unknown receipts create no success
head and persist their lifecycle/event; unknown target state blocks rollback/rebinding until explicit
observed-state reconciliation. A committed cancel wins. Stale, replayed, already-
consumed, cross-instance, cross-origin and malformed receipts fail closed.

Signature authenticates the deployment-authority statement, not the host administrator's honesty;
component handshakes and migration/backup/dependency checks independently verify every state product
logic depends on. Installation-arm causality is existing inputs→request→receipt→postcondition→
installation record/head→consumption/event. Superseded retirement is existing target/current/proofs→
request→receipt→postcondition→retirement record/head→consumption/event with the installation head
unchanged. Earlier objects cannot content-reference later ones; event and consumption share a
transaction/non-content event ID rather than mutually hashing each other.

`BrowserSession` credentials are for the browser control plane and use a distinct token namespace
from service clients. Optional headless/integration clients are
disabled until the owner creates a scoped `ServiceClient` from the authenticated web UI. Its
durable principal and immutable credential revisions survive restart. A short-lived/rotatable bearer
secret is shown once, only its digest is stored, and the client is
restricted to the declared HTTPS network profile, an expiry no later than 24 hours after issuance,
and command scopes. Service credentials
cannot call bootstrap, manufacture a human approval, broaden their own scope or bypass a pending
target-bound challenge. Both browser-cookie profiles require Origin+CSRF; service-client bearer calls
require TLS, reject browser-cookie fallback, and use exact Host, rate limits and the same `command_id`,
revision, permission, budget, event and audit semantics. No broad browser CORS is enabled merely
to support service clients.

T025 owns the complete common service-client route/authentication path:
`app/services/service_clients.py`, `app/services/service_client_auth.py`,
`app/api/service_clients.py`, durable migrations/schema, plus the one core-owned composition seam in
`app/api/router_composition.py` and its single invocation from `app/server.py`. The seam accepts only
build-installed first-party route contributions declared by fixed descriptors under
`app/api/route_contributions/*.json`; it validates unique contribution/route IDs, an exact `/api/v1`
prefix, required auth policy/scope, an `app.api.*` factory allowlist and duplicate/late-registration
failure, then freezes at app creation. It is not an extension SPI and never loads operator/user code.
T025 implements create/rotate/revoke, expiry and last-used CAS, TLS-only single-bearer parsing, exact
trusted-network profile, scope authorization, independent client/source/route token buckets and
restart/recovery/rotation races. T087 owns `app/api/extension_routes.py` and the fixed
`app/api/route_contributions/extensions-v1.json` contribution; it registers through that frozen seam
without editing `app/server.py` or `router_composition.py`, and owns extension-specific client methods
plus their actual-server black-box parity. Neither task may use an unmounted adapter, arbitrary
dynamic route import or browser cookie fallback as proof.

Bootstrap atomically creates the single initial `OwnerAccount`, an Argon2id-v19 local-password
authenticator and the first `BrowserSession`; the password is chosen in that same browser form and
is never returned or logged. The initial owner-authentication profile uses argon2-cffi 25.1.0 with a 16-byte random salt,
32-byte tag, 65,536 KiB memory, time cost 3 and parallelism 4; the encoded hash retains its
parameters. Only an allowlisted successor whose memory/time/tag requirements are no weaker may be
used for a successful-login rehash; `check_needs_rehash` alone does not authorize a new profile.
Unauthenticated password work uses one deployment-global Argon2 operation at a time and a FIFO queue
of at most three with a ten-second admission deadline. Independent trusted-source and account token
buckets must both pass; each has burst five and refills one attempt per six seconds. The source comes
only from the socket peer or an allowlisted proxy, nonexistent login names share one sentinel account
bucket, and both maps have bounded cardinality and expiry. Excess work returns the same bounded
429 class without allocating another hash. Valid-size bad credentials use one uniform 401 response
and timing padding measured in T025 rather than claiming perfect constant time.
`POST /session/login`, `/session/logout` and `/session/revoke-others`
provide ordinary re-entry and revocation. Login has per-origin/account rate limits and uniform
failure responses; session records store token digests, absolute+idle expiry and revocation, and
rotate after login, password change, recovery and authority change. The initial release does not
claim WebAuthn or deployment SSO; those are versioned Authenticator adapters. Deployment-authority
recovery requires an explicit no-owner-access flow and invalidates all sessions/authenticators,
service-client credentials, unconsumed human capabilities and pending approval/consent challenges;
historical approval records remain evidence but cannot authorize a new effect. Recovery
never silently replaces the owner while an authenticated recovery decision is still possible.
Deployment recovery is not a public unauthenticated product route: the trusted operator adapter
rotates the session-root generation plus verifier/recovery epoch, after which the restricted startup
reconciliation above completes and the same bounded bootstrap exchange re-establishes the owner.
Login verifies an existing authenticator, returns uniform failures and cannot perform
any other mutation in the same request.

Except for a minimal health response and static bootstrap/login shell, every GET/HEAD/snapshot/
SSE/download requires an owner session or scoped `ServiceClient` plus object/purpose authorization.
GET/HEAD/snapshot/SSE never creates model calls, logins, permission prompts, runs, approvals
or exports. `GET /session` may derive and return the selected browser-profile CSRF value; other GET side effects
are limited to access audit. Mutations require an authenticated actor, strict typed request schemas
and `command_id`; browser-cookie mutations require CSRF and exact origin, while service-client bearer
mutations require the scoped non-browser envelope.
Revision-sensitive commands also require
`expected_revision`/exact target hash. An identical duplicate command returns the original
result, while reuse with different payload returns conflict. Never return a generic success
for a blocked permission or missing evidence.

All JSON mutation endpoints share one strict wire parser before domain validation: exact UTF-8,
top-level object, one occurrence of every allowed field, no duplicate or unknown member, BOM,
non-finite number, bool-as-number, trailing token or schema-specific size/depth/count violation.
Query parsers use an explicit name allowlist and exactly one occurrence per scalar; enums and IDs
are exact and headers with singleton semantics reject duplicate/comma-folded ambiguity. Rejected
wire input performs no domain mutation, vault access, gateway dispatch, provider/network call or
Argon2 work unless that endpoint's documented cheap preflight has already admitted it.

Success: `{command_id?, object_ref?, state, revision?, event_cursor, links}`. Background work
returns 202 with persisted request ref and status link, not a fake completed result.
Errors: `{code, message, field_errors?, retryability, affected_refs, correlation_id}`.
HTTP classes: 400/422 invalid schema; 401 session; 403 scope/consent; 404 absent/unauthorized
opaque object; 409 stale/conflicting state; 413 size; 429 bounded capacity; 503 unavailable
dependency/storage. Error bodies never contain raw credential/provider bodies or host paths.

Streaming uses authenticated same-origin SSE with a sequence cursor/Last-Event-ID, bounded
pages/buffers and `PublicEventView` only. Resume after gaps fetches a snapshot. Rate-limit UI
updates without dropping durable events. Show actual progress counts plus estimates, not
time-driven completion. Cancellation closes future dispatch, not proof of remote termination.

Dynamic/auth/bootstrap/secret/artifact responses use `Cache-Control: no-store` unless a separately
versioned immutable public asset policy applies. The web profile sets a nonce/hash-based CSP with
`default-src 'self'`, no arbitrary script/connect/frame/object, `frame-ancestors 'none'`,
`X-Content-Type-Options: nosniff`, strict `Referrer-Policy`, and a compatible frame fallback.
HSTS is emitted only by the qualified HTTPS origin. Uploaded/derived HTML/SVG/PDF never relaxes the
privileged UI CSP. Static assets are content-digested and immutable; the HTML shell is revalidated.
The initial profiles derive their origin only from the validated `OriginProfile`; direct
`Forwarded` or `X-Forwarded-*` is rejected/ignored and can never alter canonical external origin,
secure-cookie or redirect decisions. A future qualified upstream-proxy profile must declare exact
trusted peer addresses plus forwarding, SSE buffering/timeout and reconnect canaries before those
headers are accepted. No WebSocket requirement is implied by speech chunks.

### 1.1 Implemented first-owner backend slice (Task 7, T025 partial)

The supported `create_app` takes the exact three-field nonsecret bootstrap configuration,
an independently initialized session-root directory and explicit expected UID/GID. It invokes the
fixed first-party composer once for the existing six `/api/v1` route declarations. Nonversioned
session routes are a separate fixed router. Historical `create_development_app` and its
`/api/session`, `deeptwin_local_session`, fragment delivery and `X-CSRF-Token` fixtures do not
qualify this web authority.

| External path relative to configured base | Exact input | Result |
| --- | --- | --- |
| `POST session/bootstrap` | `login_name`, `password`, `raw_capability_b64u` | 201; cookie and derived `csrf_token` |
| `POST session/login` | `login_name`, `password` | 200; cookie and derived `csrf_token` |
| `GET` / `HEAD session` | no query fields; current cookie | authenticated state and CSRF on GET; empty HEAD |
| `POST session/logout` | `command_id`; current cookie and singleton `X-DeepTwin-CSRF` | committed revocation, then cookie clearing; exact private replay only |

`login_name` is an exact nonempty Unicode-scalar string, at most128 UTF-8 bytes, without control
characters or leading/trailing whitespace. The chosen password has at least15 Unicode scalars
and at most1024 UTF-8 bytes, without normalization, trimming or composition rules. Login accepts
any bounded nonempty candidate; shorter incorrect passwords and unknown accounts both return the
same401 class. Password work uses the exact ADR012 profile and one process-owned FIFO lane, a250ms
monotonic response floor, independent source/account burst5/refill1-per6s buckets,1024-key maps
and60s idle expiry. Unknown names share one sentinel. Ordinary rate buckets are process-local;
the OS serving lock prevents concurrent control-plane instances but does not make restart abuse
accounting durable. Bootstrap opening/deadline/attempts are durable.

Bootstrap has two commits: consume the exact claim before native hashing, then atomically create
human actor/descriptor, owner, authenticator, session and sanitized public event. A failed second
commit or crash leaves `setup_incomplete`, with no automatic verifier restoration or hash retry.
A lost response after success permits password login. Replay never revokes the successful session.
Login preserves other sessions, rotating only the exact presented prior same-owner cookie.

The authority validates persisted session/account/authenticator state in the exact root-command
writer before replay/intent and checks human permission consumers with that same writer. A revoked
cookie plus the same logout command/profile/epoch can retrieve only its previous logout result.
Root generation, exact canonical manifest digest and epoch are pinned privately in the shared DB.
Private auth state is absent from ordinary snapshots/exports and public events carry counts only.

The local prefix is checked in raw ASGI paths and removed once by code-owned routing. Scheme,
Host, Origin, fetch metadata, singleton security headers and bounded raw wire bodies are admitted
before auth state. Forwarding headers cannot establish HTTPS, host, prefix or rate identity.
Proxied internal HTTP remains unqualified for the portable HTTPS profile until a pinned-edge
transport adapter exists. Static shell/minimal health are public; work/download/event paths are
session-protected. The shell deliberately reports that final setup/login UI is pending.

Backend ASGI tests are not browser-story, TLS-edge, container, deployment recovery, service-client,
password-change/revoke-others, provider, semantic-runtime or whole T025/T026 qualification.

## 2. Service routes and authority

Paths below are relative to `/api/v1`; existing routes may delegate through compatibility
adapters. Commands accept only the exact IDs/versions they need, never a whole mutable state.

| Area | Read surfaces | Explicit mutations and effects |
| --- | --- | --- |
| Auth/session | `/session`, `/session/sessions` | bootstrap once; login/logout, password change, revoke others, deployment-authority recovery |
| Setup/deployment evidence | `/setup`, `/components`, `/platform`, `/deployment/requests/{id}` | inspect current manifests; prepare/cancel an unexecuted digest-bound deployment request; accept/verify a deployment receipt. Product routes never download/install images/models, control containers/volumes/TLS or expose a Docker socket |
| Service clients | `/service-clients`, `/{id}` | T025 mounts/registers these routes; owner creates/rotates/revokes exact scoped durable client credential revisions; secret is returned once and never by reads, bearer calls receive TLS/network/scope/rate-limit enforcement |
| Connections | `/connections`, `/{id}/status`, `/{id}/catalog` | create/rotate/revoke+erase secret, start/cancel managed login, explicitly `refresh_catalog`; no inference implied |
| Model control | `/model-choices?scope=...` | set default or node/purpose override with catalog binding; create new config version |
| Intake | `/works`, `/{id}`, `/revisions/{revision}`, `/sources/{id}` | create/edit/upload, extraction retry, explicit understanding request/cancel |
| Intake (implemented 2026-09-18, `works-v1`) | `GET\|HEAD /api/v1/works/{id}` — the latest revision's projection (`work_id`, `revision`, `text`, `ref`, `created_at_utc`) | `POST /api/v1/works` (`work-create-command-v1`: `command_id`, `text` ≤ 20 000 chars and ≤ 65 536 UTF-8 bytes) seals revision 1 as a `work_revision` record whose id derives from the command; `POST /api/v1/works/{id}/revisions` (`work-revise-command-v1`: `command_id`, `expected_revision`, `text`) seals the next revision only when the latest is the expected one; a command names exactly one revision across every work (replay idempotent, different content or target → `conflict`); owner session + CSRF; sources, files, understanding requests open |
| Speech | `/speech/sessions/{id}`, `/{id}/segments` | create bounded capture session, append an idempotent ordered audio chunk, finalize/cancel; no implicit model run |
| Design | `/works/{id}/designs`, `/designs/{id}`, `/reviews/{id}` | generate, repair/merge/edit new version, select, prepare exact design |
| Runtime | `/runs`, `/{id}/graph`, `/executions/{id}`, `/attempts/{id}` | start scoped run, cancel, recover/retry after outcome check; replay route stays read-only |
| Artifacts | `/artifacts/{id}/metadata`, `/content`, `/preview`, `/lineage` | generate safe preview, declare validated output; never arbitrary path reads |
| Handoffs | `/handoffs/{id}`, `/executions/{id}/inputs` | internal acknowledged delivery; cannot fake acknowledgment via free user text |
| Own versions | `/alternatives/{id}`, `/drafts?original=...` | save whole/partial user draft, link original/selector, freeze for explicit analysis |
| DeepTwin | `/episodes/{id}`, `/differences`, `/hypotheses`, `/inquiries` | analyze, freeze questions/predictions, supply actual new evidence, decline/defer |
| Experiments | `/series/{id}`, `/rounds/{id}`, `/comparison-plans` | create/freeze plan+budget, start/cancel, fork changed conditions, freeze best candidate |
| Validation | `/validations/{id}`, `/knowledge/{id}` | isolated validation request, explicit source correction/withdrawal, compatibility recheck |
| Approvals | `/approvals/{id}`, `/environments/{id}/versions` | resolve typed challenge, activate exact approved version, explicit rollback |
| Operations | `/events`, `/gaps`, `/retention`, `/backups`, `/exports` | preview then confirm deletion/export/restore/update; no automatic creator transmission |
| Operations (implemented 2026-09-23, `works-v1` export routes) | `GET\|HEAD /api/v1/works/{id}/exports/{bundle_id}` — the owner's sealed bundle (`application/zip`, `X-DeepTwin-Bundle-SHA256`) | `POST /api/v1/works/{id}/exports/preview` (`work-export-preview-v1`: `request_id`, `categories` ⊆ closed export set, `include_raw` only with `originals`, optional `acknowledged_findings_sha` only with `include_raw`, optional `include_source_originals: true` only with `include_raw` (T074: attached originals — a PDF is scanned by the isolated document worker and, on an unconfirmed finding, exported only as the worker-made, re-verified image-only `redacted` copy or left out with its reason; an unscannable format is left out as `unavailable`)) returns the actual items, every omission with its closed reason, the raw originals' `secret_scan` (findings by kind/path/line/column only, never the value; an original with a finding is metadata-only unless `acknowledged_findings_sha` equals the current `findings_sha`, else `conflict`) and `preview_sha` over all of it, storing nothing (T074: `evaluation_evidence` carries the work's design requests/candidates/recorded verdicts/derivations/design approvals, the referenced lens definitions and the growth rounds whose plan baseline is an environment this work's runs used, metadata only); `POST /api/v1/works/{id}/exports` (`work-export-confirm-v1`: the same selection, the same optional `acknowledged_findings_sha` and `include_source_originals`, + `preview_sha` + `confirmed: true`) recomputes the preview, refuses a changed work (`conflict`), seals consent/raw-inclusion/`export_manifest` records and returns the external receipt; one bundle per request id; nothing is transmitted |
| Operations (T074, `backups-v1` restore upload) | `POST /api/v1/backups/restores/{id}/bundle` and `…/portable-bundle` cut before the declared body is complete | the web boundary drops the partial body; for an authenticated owner request (cookie + CSRF) it marks that `awaiting_bundle` restore `failed` (`restore_failed`, `interrupted_after_bytes`), nothing staged, cleanable at once; the restore cannot be resumed, a fresh restore starts over; the active vault is never touched |
| Extensions | `/extensions`, `/{id}`, `/{id}/installations`, `/{id}/retirements`, `/{id}/qualifications`, `/{id}/bindings`, `/{id}/bindings/{slot_key_digest}/rollback-retentions/{target_binding_record_digest}/release`, `/extension-deployment/requests/{id}` | bounded import of code-free definition; prepare/cancel exact stage/replace/current-uninstall/superseded-retirement request; verify one-use signed receipt and arm-specific postcondition; bind/disable/rollback already qualified revision; explicitly release a superseded target's rollback retention without deleting history. The extension-deployment path is a scoped projection/action over the same canonical `DeploymentRequest`/lifecycle/receipt-consumption records as `/deployment/requests/{id}`, never a second authority or store. Product API never downloads code/images, controls containers, accepts arbitrary Compose, installs executable or instance-critical storage/vault ports, or treats receipt as qualification |

Extension reads expose safe source/version/digest/license/kind/port/trust/platform, installation,
qualification/failure/expiry, binding/scope/grant and affected-environment projections. Definition
import accepts one bounded schema-validated code-free lens/evaluator bundle and creates inert bytes;
it cannot select a runtime entrypoint. Executable deployment requests bind the exact service
descriptor where applicable and the exact arm-specific precondition. Stage has no current head.
Current uninstall names the current head/tuple and advances to a tombstone. Superseded retirement
names an existing strict ancestor, preserves a descendant current head and advances only the target-
keyed retirement head after repeated binding/rollback/environment dependency checks. No arm carries
a future record ref. Only the external deployment authority performs the host effect. A replacement
stages the new digest under a distinct service identity while the old service remains reachable;
handshake and qualification precede binding-head CAS supersession, and exact ancestor retirement is
the later checked arm. In-place destructive
replace is unsupported and is surfaced as `rollback_unavailable`/outage if observed. Receipt
acceptance uses the common signed deployment receipt lifecycle and is followed by an independent
component handshake and semantic-port qualification before binding becomes possible. Every
mutating extension command uses the expected keyed head/revision: installation by extension
identity, qualification by installation+context fingerprint, and binding by the closed
`BindingSlotKeyV1={port_contract_version,target_scope_fingerprint,purpose,binding_slot_id,
capability_selector_digest}` plus its ADR-008 canonical digest. Bind/disable/rollback requests MUST
carry that exact object, digest and `expected_binding_head_revision`; the config, resolved binding,
result and event repeat them byte-for-byte. Different port versions/slots/selectors
coexist even for the same port/scope/purpose, while an exact same-slot stale head fails without
changing either candidate. It commits its immutable record, that head and public event atomically. A
supersession or disable also atomically creates the exact old binding's target-keyed rollback-
retention head in state `retained`; immutable backward binding refs alone never authorize rollback.
Rollback requires and atomically consumes that retained head while creating a new binding revision.

`POST /extensions/{id}/bindings/{slot_key_digest}/rollback-retentions/
{target_binding_record_digest}/release` is owner-only and accepts exactly
`{command_id,extension_id,binding_slot_key,binding_slot_key_digest,expected_current_binding_head,
target_binding_revision_ref,target_installation_ref,target_service_tuple,expected_retention_head:{revision,
retention_record_digest,state:"retained"},reason}`. `binding_slot_key` is exact
`BindingSlotKeyV1` and `binding_slot_key_digest` equals its recomputed canonical digest;
`expected_current_binding_head` is exactly
`{revision,binding_record_digest,state}` with state `active|disabled`, and target binding ref is
exactly `{revision,binding_record_digest}`. The path `target_binding_record_digest` must equal
`target_binding_revision_ref.binding_record_digest`; all path and body identifiers must match. The target
must be a strict backward ancestor of the exact current binding head in that same five-field slot, and
its installation/service tuple must match the retained revision. Success returns every request
identifier/head/ref byte-for-byte in exactly
`{command_id,extension_id,binding_slot_key,binding_slot_key_digest,expected_current_binding_head,
target_binding_revision_ref,target_installation_ref,target_service_tuple,expected_retention_head,
new_retention_revision,new_retention_record_digest,state:"released"}` and atomically commits the
immutable retention revision/head/event without changing the binding or installation head. A
released/consumed target cannot roll back and does not populate `retained_rollback_refs`; its binding
history remains readable. Unknown fields, current/cross-slot targets, stale heads, repeated release
and tuple mismatch fail without mutation. Reads and dispatch
reconcile expiry, runtime/platform/framework/port change, revoked grants and incomplete receipt/
handshake after restart rather than reviving an old binding.

The versioned OpenAPI document and exported JSON schemas are generated from the same command/event
types used by the bundled UI. Compatibility is explicit: an unsupported major contract is rejected,
additive supported versions are negotiated, and no adapter may reinterpret an old approval, target,
effect, port operation or artifact selector. The extension-author distribution and HTTP/OpenAPI
client are separate installable packages with independent versions. The engineering black-box
process installs the HTTP client, imports no `app` module, talks to the actual T025 production HTTPS
route surface mounted through the frozen composition seam and proves that identical browser/client
commands produce the same durable object revisions, authority decisions, receipts and event order
across restart/concurrency.
T083 repeats the client parity on the final portable HTTPS distribution and verifies that the
HTTP-only loopback profile does not register or expose bearer automation: a fixed non-secret canary
receives route-not-found or the specified pre-auth denial before bearer parsing, and no real bearer is
sent. The out-of-tree extension itself is still exercised on both clean hosts. A future loopback
client profile requires a separately qualified transport rather than a cookie/plaintext-bearer
fallback. This supported automation
surface does not make a CLI part of the ordinary user's workflow.

The semantic port schemas are a separate core-owned API artifact set defined by
`contracts/extension-ports.md`. OpenAPI references their canonical IDs; the extension-author SDK
ships read-only schema bindings and authors only manifests/permitted refinements. An extension cannot
publish a replacement base port schema or expand operation, terminal, error, authority or effect
semantics through OpenAPI.

Secrets use dedicated masked input and backend `CredentialVault`. Creation responses return
key_present and connection state only, not key bytes, hashes, handles or raw auth errors.
Handle wording (decided 2026-09-25, T090): "handles" above means the gateway's opaque resolution
handle and any secret-derived value. The credential-v2 routes (`/api/v1/credentials`) do return a
browser-facing `handle`: the record id in 32-hex form, a stable nonsecret address that stays the
same across rotations and is what rotate (`rotate_from`) and `DELETE /api/v1/credentials/{handle}`
name. It is derived from no key byte, is not a gateway resolution handle, never resolves or opens a
secret and confers no dispatch, send or binding authority; binding authority is only the
control-plane connection binding head described below.
Codex managed device authorization returns only the official verification URL, user code and expiry
through a narrowly scoped authenticated login action, not logs/events/export. Unknown/malicious
verification destinations are rejected. Authenticated DeepTwin start/cancel/status commands control
the isolated official CLI managed-runner profile (`codex login --device-auth`, version-qualified
`codex exec --json`); the runner owns device code/token state in its
dedicated auth volume and subscription tokens never cross into the DeepTwin web session or general
worker. The first release exposes no provider callback route and does not assume a container
loopback callback reaches the host. Callback/PKCE is a future separately qualified runner profile.
The experimental App Server is not a production execution dependency; a separately qualified
preview may enrich catalog/event UI but cannot silently change the execution or authentication path.

Secret-bearing create/rotate commands require exactly one decimal `Content-Length` ≤96 KiB, no
`Transfer-Encoding`/`Content-Encoding`, and a decoded UTF-8 `secret` value ≤65,536 bytes; missing,
duplicate, malformed or oversize framing is rejected before an intent, vault access or gateway call
(413 for size). Only that explicit path may
hold the raw secret once in bounded no-store edge/control-plane memory and pass it through the
authenticated gateway IPC; normal dispatch and storage use opaque handles. Secret-bearing connection commands first persist a pending intent containing `command_id`, a
fingerprint of the non-secret envelope, target record/connection and expected versions in one DB
transaction. The control plane then sends the in-memory secret once to the gateway's idempotent
`store_at(record_id, record_version)`, persists its non-secret encrypted-record receipt, applies the
provider binding by compare-and-swap in a second DB transaction, and only then stores the terminal
command receipt. They never claim a cross-process DB+file transaction and never persist or compare
key bytes, a key-derived verifier, prefix/suffix or generic journal payload. Restart reconciliation
queries the exact record ID/version before deciding: it returns an already bound result, completes
an exact stored-record binding, or quarantines a valid unbound record. If the pending intent exists
but the gateway has not durably admitted that command, an exact query returns nonterminal
`unknown`: a delayed accepted call may still commit. Absence alone never authorizes a new
command ID, replacement secret, automatic retry or a terminal loss receipt. Only the gateway's
durably journaled pending, never-receipted command with demonstrably irrecoverable ingress can
return terminal `secret_input_lost`; after that terminal proof, a fresh command ID plus explicit
secret re-entry may retry. Missing ciphertext of a previously receipted record is recovery or
maintenance, not ingress loss. It never applies a newly supplied secret under a consumed command ID. Changed
non-secret fields conflict and an intentional key change always uses a fresh command ID. Lost-response
and concurrent duplicates follow this protocol rather than risking a second credential mutation.
Create/rotate/revoke themselves perform zero provider check, catalog refresh, model call or runtime
dispatch. A successful rotate atomically invalidates every catalog/model choice bound to its
predecessor; only a later explicit `refresh_catalog` mutation can establish a new catalog.
Credential-v2 binding (T090, 2026-09-25): each provider has one connection binding head
`{revision, state: bound|revoked_pending_erasure, record}` in the control-plane credential ledger.
A create binds only a connection that is not `bound` (otherwise `409 connection_bound` before any
gateway call; replacing a bound key is a rotation); a rotation's CAS requires the revision recorded
at allocation and the exact predecessor record. Catalog snapshots and model choices are keyed by
binding revision, so the rotation's CAS and a delete's revoke void them in the same transaction. A
stored record that loses its CAS is a valid create/rotation orphan: `409 connection_conflict`, an
immutable `unbound_orphan` retirement, and a rotation's predecessor stays bound and unretired.
Unknown-command fence: the custody contract defines no gateway cancel/fence operation, so an act
whose store command stays `unknown` is resolved by an explicit owner act,
`POST /api/v1/credentials/fences {"intent_id"}` (the unresolved act's intent), available only after
a fixed delay since the command was sent (`fence_available_at` in the status read, 300 s by default).
The fence makes one more `query_record`: `pending` refuses the fence (`503 command_pending`, the
gateway's own recovery settles it), `secret_input_lost` is terminal, a committed record is adopted
only as an unbound orphan and retired `unbound_orphan`, and a still-`unknown` command makes the act
terminal `fenced` (`409 fenced` for any replay; its secret is never re-sent and its record is never
bound). A later rotation skips the fenced version. A delayed accepted store may still commit after
the fence: later owner acts query open fences and retire such a late record as `unbound_orphan`.
The fence therefore neutralizes a late commit; it does not prevent it at the gateway.

`GET /api/v1/credentials` returns `{credentials, connections, pending_acts}` from the committed
ledger: redacted credential entries, each provider's binding head (`binding_revision`, and whether a
catalog snapshot/model choice is `current` for that revision) and the unfinished or fenced acts.
Connection/status/catalog GETs return only persisted redacted snapshots and perform zero vault open,
gateway dispatch, provider request, network call or catalog refresh. Only an authenticated mutation
with a fresh `command_id` can request `refresh_catalog` or a managed login/check action. Connection
deletion first CAS-revokes the binding to `revoked_pending_erasure`, atomically invalidates every
catalog/selection authority for it and blocks all future send/refresh. Valid create orphans, each
successfully rotated predecessor and deleted records receive immutable retirement intents and stay
`cleanup_pending`. With the gateway stopped, `vault-maintenance` promotes a verified generation
excluding every retired record, removes superseded/staging locally managed generations and verifies
their absence. Only then may it return `erasure_completed`; crash, partial removal or rollback keeps
cleanup pending, never restores provider authority and resumes cleanup without opening the old
record for dispatch. Physical copies controlled by host snapshots, administrators, swap or prior
backups are outside the erasure claim and reported as limitations. Reads never advance this lifecycle.
`erasure_completed` means DeepTwin's locally managed encrypted copies were removed; it does not
revoke or invalidate the API credential at Anthropic/OpenAI. The UI directs the owner to the
provider's separate revocation control when remote invalidation is desired and never marks that
step complete without provider evidence.

Browser speech profile `stt-local-ko-v1` uses explicit `getUserMedia` plus an `AudioWorklet` to
produce 16 kHz mono signed 16-bit little-endian PCM. It uses JSON `POST /speech/sessions`, raw-body
`PUT /speech/sessions/{id}/chunks/{sequence}`, JSON
`POST /speech/sessions/{id}/utterances/{utterance_id}/finalize`, and JSON
`POST /speech/sessions/{id}/{finalize|cancel}`. A session freezes work/revision, declared media
type, sample metadata, `retention_mode=ephemeral_only` and finite byte/time limits; every other raw-
audio retention mode is rejected until a separate profile is implemented and qualified. The only v1 media
type is `application/vnd.deeptwin.pcm;version=1;encoding=s16le;rate=16000;channels=1`. New-client
chunks are consecutive, non-overlapping ranges: ordinary chunks are exactly 16,000 samples/32,000
bytes. `X-DeepTwin-Chunk-Kind: tail` may carry 1..16,000 real samples with no zero padding and then
that utterance accepts only finalize/cancel; an empty tail is not sent. The worker derives overlapping decode windows and the
client never resends a cumulative window as a new chunk. Each chunk binds the path sequence plus
`X-DeepTwin-Utterance-Id`, `X-DeepTwin-Sample-Start`, `X-DeepTwin-Sample-End-Exclusive`, exact chunk
kind and `X-DeepTwin-Command-Id`. The raw-body exception requires that exact Content-Type,
bounded Content-Length and RFC 9530
`Content-Digest: sha-256=:base64:` plus exact browser-session authentication and that selected
profile's single `X-DeepTwin-CSRF` header. Exactly one non-trailer `Content-Digest` field is parsed as a Structured
Fields Dictionary containing only one unparameterized `sha-256` member whose Byte Sequence decodes
to 32 bytes; duplicate field/member, extra algorithm, malformed base64/SF, Content-Encoding and
31/33-byte values are rejected. Host/Origin/session/CSRF/header/Content-Length/sample-range checks run before
the body; bytes stream into uncommitted bounded tmpfs while SHA-256 is computed. Only a constant-time
RFC 9530 digest match accepts/commits the chunk metadata and queues decode; mismatch erases staging.
It never parses multipart filenames/paths. An identical replay is harmless and a changed duplicate,
gap or overlapping actual sample range conflicts. Utterance finalize binds `command_id`, exact
`end_sample_exclusive` and one of `browser_silence|manual_stop|track_ended|max_duration`; it is
idempotent and runs the final pass over that exact tmpfs range. A silence-finalized utterance may be
followed by a new utterance in the same session. Session finalize requires no open utterance; manual
stop/track end first finalize the last utterance, while the server enforces the 60-second boundary.
Interim/final segments are versioned reads/events and remain editable user input, never automatic
permission to design or run. Raw audio is always ephemeral in this v1 profile and the UI states that
it is not retained. Same-origin authenticated SSE carries recognition events, while
microphone bytes go only to the framework speech endpoint/worker granted for that session.
The first isolated worker profile uses `deeptwin-faster-whisper 1.2.1+deeptwin.1`, CPU int8 and the
pinned multilingual `Systran/faster-whisper-small` revision from ADR-011. For each exact chunk
range the worker requires even bytes and the declared sample count, converts
`np.frombuffer(raw,dtype="<i2")` to contiguous one-dimensional float32 with multiplication by
`1/32768.0`, and rejects raw bytes/int16 arrays, path/BinaryIO decode, VAD and remote
model/tokenizer fallback. Provisional rolling-window output and the
separate final utterance pass have distinct segment revisions; a user-edited span is detached from
automatic replacement. Missing/failed local STT never triggers an external transcription fallback.
Raw PCM has no application-level durable storage: it is browser-memory/container-tmpfs state and is
lost on worker restart. Host-admin access, VM/host swap and crash-dump capture are outside this
claim; the UI does not promise raw bytes can never reach physical media. A worker/server restart makes
unfinalized audio `interrupted/raw_unavailable`; final transcript revisions and user edits remain,
and no automatic re-decode is claimed. The existing cumulative-window
`POST /api/speech/sessions/{id}/chunks?...` is a one-major-version compatibility adapter only. It
must pass the same session/origin/CSRF/size/digest/idempotency service, verify each cumulative body
has the previous tmpfs body as an exact prefix and stays within a separate 1,920,000-byte/60-second
utterance cap. It appends only the suffix into a per-utterance accumulator, emitting 16,000-sample
internal chunks only when complete; `final=true` emits any remaining 1..16,000-sample tail and the
typed finalize, while zero remainder emits no tail. An identical cumulative non-final body is a
harmless replay, and an identical final body may finalize with zero suffix; changed prefix conflicts.
The adapter maps the legacy sequence/utterance/final query exactly, fails interrupted after restart,
and the bundled UI migrates to PUT and cannot rely on it for release qualification.

## 3. File and artifact delivery

The planned first connected originals-only slice is specified in
[`owner-material-intake.md`](owner-material-intake.md). Its design review is complete; its
implementation/acceptance is not. It preserves originals without claiming extraction or the
complete delivery contract below. File-first input requires no invented explanation.

Upload streams into bounded staging with per-file limits; current 10 MiB input ceiling is a
visible initial limit, not a silent truncation. Support larger artifacts via configurable
validated limits, distinct from bounded model input/preview sizes. Sniff actual media type,
check archive/decompression limits and preserve source bytes. Return explicit stored/extraction
states. Downloads are authorized attachment responses with safe display names/nosniff and no
inline executable HTML/SVG. PDF previews are page images; original PDF remains downloadable.

Partial requests bind original hash, selector kind, coordinates/ranges and alignment status.
Stale selectors fail rather than pointing at a new version. Image/PDF dimensions and table
keys/ranges are server-validated. Text partial drafts store user content separately from a
composed full-preview artifact so unedited regions are not attributed to the user.

## 4. Commands from chat and three-view state

Store chat messages with explicit referenced objects and semantic origin (`work_request`,
`clarification`, `own_artifact`, `analysis_evidence`, `command_request`). A language model can
propose `ProposedCommand` but the command service verifies target, authority and evidence.
Ordinary chat praise/criticism/“yes” does not create a user alternative or approve a new
unidentified environment. Material actions require an unambiguous current challenge; a UI
button and an explicit target-bound chat response invoke the same validated command.

`ViewContext` stores mode, work/revision, candidate/environment/run, execution/attempt,
artifact/selector, alternative/episode/series/round plus local zoom/focus. Switching views or
expanding detail performs only reads. Per-work drafts are revisioned, recovery-safe, and not
mixed with provider transcripts. Long internal IDs/hashes remain expandable details.

## 5. Security/behavior tests

A01 local and HTTPS-deployment Origin/Host/session/CSRF plus one-use first-owner bootstrap,
non-CLI delivery and audited recovery; A02 GET has zero external dispatch;
A03 idempotency mismatch/revision conflict; A04 public SSE and error canaries; A05 stale/
cross-vault/cross-purpose artifact requests; A06 upload bombs/unsafe previews/ranges;
A07 all three modes issue identical target-bound commands; A08 partial draft != whole user
work; A09 model-proposed approval or unknown chat target rejected; A10 reconnect/late events
preserve selected old attempt and current drafts; A11 permission/credential-vault/budget failures
show recoverable facts without a fake success or automatic paid fallback; A12 ordered/replayed/
changed speech chunks, permission denial, raw-audio expiry and cancel/finalize races are bounded;
A13 wrong extension kind/artifact/port/trust/staging tuple, wrong base schema/operation/terminal/error/
refinement/artifact cardinality, four-field/sibling-version/digest-mismatched binding key, mixed or arm-forbidden deployment payload, non-empty common extension
preconditions, future record precondition, request↔service/head/target/dependency-digest mismatch,
current-uninstall versus superseded-retirement mode confusion, non-ancestor retirement, changed
preserved head, retained binding/rollback/environment dependency, missing/stale/cross-slot rollback-
retention release, released-target rollback, digest cycle, untrusted receipt/
postcondition, restart/requalification and slot-key stale-head race are rejected. The full 52-operation
×four-terminal result matrix includes cancelled codec with `artifacts=[]`; the separate 52-operation
request matrix rejects every extra/missing/wrong-role/media/selector/hidden competing artifact ref,
requires exact frozen-list equality and enforces the core ToolDefinition profile plus exact export
snapshot/prepared byte lists (11 non-empty-capable, 41 exact-empty). Result artifacts reject wrong
role/media/omissions or codec target/output mismatch. The result `effect` object is the sole effect
truth; embedded errors carry no effect state, and every unlisted terminal×effect-family/retry tuple is
invalid, including succeeded-external-unknown and failed-unknown-retryable. Tool `invoke_tool`
success output is exactly `{tool_call_ref,result_ref}`; any output-level `effect_receipt_ref` or
alias is rejected even when equal, while `result.effect.effect_receipt_ref` remains authoritative.
The recursive reusable-core
scan includes `app/extensions/**`; a separately installed client process reaches the composed TLS
bearer route, while the HTTP loopback non-secret canary proves route non-exposure before bearer parsing.
