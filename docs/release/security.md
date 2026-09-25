# Security model (draft)

Date: 2026-09-23 · Updated: 2026-09-25 · Status: **draft for T084. No security qualification has been performed**; T079
(security qualification against the frozen release candidate) and T083 (two fresh hosts) are open.
Normative sources: `contracts/api.md` §1 and §5, `contracts/operations.md` §2.2, §3, §5, §8,
`contracts/runtime.md` §5–6, `contracts/encrypted-credential-custody.md`.

## 1. Reporting a vulnerability

A private vulnerability-reporting channel has **not yet been set up**. Until one exists, do not
file security problems in a public tracker; contact the copyright owner privately. This section must
be completed before any publication.

## 2. Web boundary

`app/api/web_boundary.py` runs before any authentication work:

- **Exact origin.** Scheme, `Host`, `Origin` and base path must equal the deployment's
  `OriginProfile`. `Sec-Fetch-Site` must be absent, `none` or `same-origin`. There is no CORS.
- **No proxy trust.** Requests with `Forwarded`, any `X-Forwarded-*`, `X-Original-URL` or
  `X-Rewrite-URL` are denied; Uvicorn runs with `proxy_headers=False`.
- **Path hygiene.** Raw paths containing `%`, `\`, `//`, `.` or `..` segments, or non-ASCII bytes
  are denied. Static files come from a closed catalogue (`app/api/assets.py`); no path is composed
  from the request.
- **Header and body bounds.** At most 256 headers / 64 KiB of header bytes, singleton parsing of
  the headers it reads, and per-route body limits enforced before parsing.
- **Security headers** on every response: `Cache-Control: no-store`, `X-Content-Type-Options:
  nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and
  `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; connect-src
  'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src
  'none'`.
- The browser modules write server text through `textContent` or attributes only.

## 3. Owner authentication, session and CSRF

- **First owner** is claimed with a deployment-created, one-use, short-lived capability (32 bytes,
  typed by the owner, never in a URL or log). Attempts and the claim window are bounded and
  persisted. Passwords are at least 15 characters and hashed with Argon2id (`argon2-cffi`, profile `argon2id-v19-m65536-t3-p4-s16-h32` in
  `app/services/owner_auth.py`).
- **Session cookie**: HttpOnly, `SameSite=Strict`, scoped to the instance base path; `Secure`
  under HTTPS. The contract names `deeptwin_session` (loopback HTTP) and
  `__Host-deeptwin_session` (HTTPS). The server stores only a digest of the 32-byte token and
  enforces idle and absolute lifetimes (12 hours / 7 days per contract).
- **CSRF**: mutations carry `X-DeepTwin-CSRF` exactly once. The value is an HMAC-SHA-256 under a
  separate read-only **session root** (`app/operations/session_root.py`) over the origin, session
  token and recovery epoch, compared in constant time.
- A second serving process is refused by an exclusive `owner-auth.lock`; this is a
  single-process constraint, not a general rate-limit guarantee. The operator tools take the
  data directory's serving lock too, so they refuse (`busy`) while a control plane runs.
- **Password change and session revocation**: changing the password ends every other session;
  the owner can also end all other sessions explicitly.
- **Owner recovery** (operator only, control plane stopped): a signed recovery receipt verified
  against a `deployment-public-trust-set-v2` advances the recovery epoch by exactly one. The next
  start reconciles in one transaction before any route is composed: every authenticator, browser
  session and service client is revoked, unconsumed challenges and undecided gate requests expire,
  open run consents are revoked, and execution-bound approvals decided before the recovery are
  superseded. Rollbacks, skipped epochs and foreign trust sets fail closed. No real signing adapter
  exists yet.

## 4. No host paths

Host filesystem paths never become authority. Tool arguments and model-originated values are
checked by `carries_host_path` (`app/runtime/gateway.py`), which also looks through percent-encoding
and backslash disguises. File names on upload are refused if they contain path or control
characters. Export bundles use restricted relative paths only. Deployment roots are
deployment-supplied, never browser-configurable.

## 5. Tool dispatch and side channels (`app/runtime/tools.py`)

- A **closed registry**: only `register_tool` adds a tool; unknown IDs or versions are
  unsupported, never inferred from model or extension output.
- Arguments follow the tool's declared profile and carry **no artifact refs, selectors or host
  paths**; ordered artifact-input bindings are the only byte-input authority.
- The required grant must match exactly. External and instance-critical effects need an explicit
  effect approval. An execution-bound approval (`run-approval-v2`) authorizes exactly one attempt
  of one execution, is bound to the ledger's ask and the attempt's inputs digest, is claimed
  atomically and expires; a retry needs a new decision. The declared replay policy is
  authoritative; an unknown external outcome holds the request until a real reconciliation.
- Growth comparisons never re-send a past external effect: a tool with a recorded effect is answered
  only by an owner-approved boundary (recorded replay or an isolated sink), otherwise the item is not
  compared.
- An admitted dispatch envelope is the **only key to side channels**:
  - `open_in_scope` opens files under a declared scope one component at a time with `O_NOFOLLOW`
    (no absolute, empty, `.` or `..` component, no symlink at any depth, no hardlinked or
    non-regular target); writes create exclusively and require a writing effect class.
  - `admit_network` allows only an exact host the tool declared, then routes the fetch through the
    egress broker.
  - `admit_tool_result` enforces the tool's byte cap, refuses active renderable content (HTML, SVG,
    script) and sniffs declared document formats, so a tool cannot hand a renderer something it did
    not declare.

## 6. Egress broker (`app/runtime/egress.py`)

HTTPS on port 443 only, `GET`/`HEAD` only, hostnames from an explicit grant set, the product's own
origin never reachable, no inherited credentials (URL userinfo, `Authorization`, `Cookie` refused),
bounded response size. Every resolved address must be public; private, loopback, link-local
(including cloud metadata), multicast, reserved and unspecified ranges refuse, and one bad address
poisons the set. The transport connects only to the pinned addresses (DNS-rebinding defense), and
every redirect is revalidated with a fresh resolution under a hop limit. The module itself performs
no live network activity; resolver and transport are injected. OS-level egress denial is claimed
only for `network_mode: none` workers.

In the worker topology the broker runs only in the fetch service (`app/workers/fetch_service.py`).
The browser worker refuses to start if its network namespace has any interface but loopback, runs
Chromium with its own sandbox and JavaScript disabled, and reaches the web only through the
`browser-fetch` pair under an owner-created browser grant. A grant binds exact https navigation
URLs, recipient hosts, byte/request/redirect budgets, an expiry, and the only query parameters that
may carry values, each bound to an owner-declared value set stored as SHA-256 digests; work
content, diagnosis, alternatives and secrets are not declarable sources. Derived requests are
checked for the carried values; an encoding a hostile page invents beyond the checked forms toward
another granted recipient is not detected (the recipient list stays the outer bound). No
production run registers the browser tools yet.

## 7. Credential custody

There are two separate key paths today. Owners see them as separate panels.

- **Direct-adapter Claude connection (used by runs today).** The owner-entered Claude API key is
  held in the control-plane process memory only (`InMemoryCredentialVault`), never written to
  disk, the database, a log, an event or a response, and forgotten on restart. The provider call is
  made from the same process through the official-SDK adapter, bounded by the operator's
  `DEEPTWIN_LIVE_MAX_MODEL_CALLS`/`DEEPTWIN_LIVE_MAX_OUTPUT_TOKENS`. This profile was chosen by the
  owner for development and is **not** the release isolation boundary
  (`evidence/claude-direct-live-path-2026-09-24.md`).
- **Credential gateway (release path).** Provider credentials live in an **encrypted vault** split
  across two deployment-supplied directories (root key volume and records volume), never
  browser-configurable, opened only by the separate `provider` process
  (`app/workers/credential_gateway_main.py`). Records are `credential-record-v1` envelopes encrypted
  with XChaCha20-Poly1305 (PyNaCl `nacl.secret.Aead`) with fresh 24-byte nonces; the root manifest is
  HMAC-bound. There is **no plaintext fallback**; unknown or legacy raw layouts fail with
  `maintenance_required` before any mutation. A create/rotate secret crosses the control plane once,
  in bounded no-store request memory, to the gateway over the authenticated `cp-provider` pair; the
  control plane never imports the vault implementation. The gateway sends nothing with a stored key
  until it has adopted a provider-transport qualification for its shipped manifest, and each send is
  bound to a budget reservation. Deleting a key erases the local copy only; it does not revoke the
  key at the provider. Runs do not yet use this path (T090/T087 open).
- Secrets are entered through masked input and never returned by reads, logged, exported or backed
  up as restorable authority. Export previews scan raw originals for secret-shaped values and
  exclude those originals unless the owner explicitly acknowledges the shown findings.
- Backups exclude credentials, keys, sessions, challenges, unconsumed capabilities and deployment
  private state; a restored instance opens in `restored_review` with dispatch blocked
  ([operator guide](operator-deployment-backup-guide.md) §5). The backup identity stays in the
  networkless backup-crypto worker; the control plane never reads the backup-key volume.

## 8. Isolation and container posture (target)

Per `operations.md` §2.2 and the Compose skeleton: non-root fixed UIDs, read-only root filesystems,
`cap_drop: ALL`, no-new-privileges, bounded tmpfs, per-pair Unix sockets with owner/mode checks,
`SO_PEERCRED` and per-boot nonces, no Docker socket in any DeepTwin container. The Chromium worker
must run with its own sandbox active (no `--no-sandbox`, no privileged mode). These are **design
targets** partially exercised by canaries (`deploy/tests/`); they are not yet qualified on final
images.

## 9. Known gaps

- No final images, so no image-level security evidence; no worker is wired into Compose yet.
- The direct-adapter Claude key and provider call share the control-plane process (§7).
- Operator-side signing adapters for owner recovery and update receipts do not exist; only
  test-owned signers were used.
- Speech, evaluation and runtime-extension workers are not connected in the supported server.
- The control-plane process still imports `python-docx` at start through the legacy owner-upload
  extractor; the preview path never calls it, but the parser boundary is enforced at process level
  only for the PDF stack (`evidence/artifact-previews-t045-2026-09-25.md`).
- Browser JavaScript-enabled pages and interaction tools are not qualified; Chromium's sandbox was
  probed locally, not in the final container.
- The development preview (`create_development_app`) is not a security boundary.
- No private disclosure channel; no third-party audit.
