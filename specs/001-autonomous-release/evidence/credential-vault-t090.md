# T090 — credential-vault core (`credential-vault-port-v1`)

Date: 2026-09-13
Status: implemented and unit-verified vault core; **T090 remains open** (no gateway,
no CredentialedProviderTransport, no HTTP ingress, no UDS wiring, no independent audit)

## Exact scope

`app/workers/credential_vault.py` implements the gateway-side vault state machine of
runtime.md's `credential-vault-port-v1` row: operations `capabilities`, `store`,
`resolve_for_gateway`, `retire`, `erase`, `health`; the secret stays opaque behind a
framework-minted handle; a store/rotate intent id deduplicates; and responses never
contain the raw secret.

- Staged commits: the secret enters an owned 0600 staging file (O_EXCL/no-follow),
  is fsynced and atomically renamed into `secrets/<handle>`; the metadata index is
  rewritten atomically and carries only the provider, state, intent id and secret
  sha256 — never secret bytes.
- Idempotency: an identical intent replay returns the committed record; a replay
  whose provider/bytes/predecessor differ is a sanitized conflict.
- Rotation: `store(..., rotate_from=handle)` requires an active predecessor,
  supersedes it to `cleanup_pending` and immediately invalidates its resolution.
- Retirement gates resolution the same way; `erase` is legal only from
  `cleanup_pending`/`secret_input_lost` and reports `erasure_completed` only after
  the local copy is verifiably absent (post-unlink stat must fail).
- Startup reconciliation: orphaned `staging-*` files are removed; an active record
  whose secret bytes are missing becomes `secret_input_lost` (never re-invented).
- Bounds: canonical-UUID intent, `[a-z][a-z0-9_-]{0,31}` provider, 1..65,536-byte
  UTF-8 secret; resolution re-verifies length and sha256.

Tests: `app/tests/test_credential_vault.py` (9) — lifecycle/opacity, intent
idempotency and conflict, rotation supersession/invalidation, retire+verified
erasure with a whole-tree secret-byte sweep, rotated-predecessor cleanup, restart
reconciliation (orphan staging removed, lost secret marked), bounds/foreign-input
zero-effect, sanitized errors, secret-free on-disk metadata.

```text
python -m pytest -q app/tests/test_credential_vault.py
9 passed
ruff check app/workers/credential_vault.py app/tests/test_credential_vault.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,049 passed, 2 skipped, 369 subtests passed, 1 known warning
```

## Frozen content identities (SHA-256)

```text
30184e13e7be8292be1eefd0dc651ce3b3efb17f774e2f91a973afb524229ec8  app/workers/credential_vault.py
c288868060505ea538c54ab15eca291f9fe8a65ec1994c8e42befef1a4b79edc  app/tests/test_credential_vault.py
```

## Not claimed

No provider gateway or `CredentialedProviderTransport` exists yet (auth injection,
redirect/SSRF/header canaries, bounded redacted responses remain open), no HTTP
create/rotate ingress with the exact Content-Length/no-encoding wire checks, no UDS
service wiring, no T087 provider-transport manifest binding, and no independent
adversarial audit of this vault core has run.

## CredentialedProviderTransport (2026-09-13)

`app/workers/provider_gateway.py` adds the gateway's credentialed request path:

- `ProviderBinding`: the closed request surface — provider id, exact origin
  (scheme/host/port; plain HTTP is loopback-only, production is HTTPS), allowed
  methods, absolute path prefixes, a projected request-header whitelist that can
  never include auth/host/cookie/proxy/framing names, the injected auth header
  name, request/response byte ceilings and a bounded timeout — all validated
  fail-closed at construction.
- `CredentialedProviderTransport.send(handle, method, path, headers, body)`:
  validates the projection *before any network effect* (forbidden or unlisted
  headers, foreign paths/absolute URLs/traversal/CR-LF, unbound methods, oversized
  bodies all reject with the fake server observing zero requests), verifies the
  handle's provider binding, resolves the secret only at send time, injects the
  auth header itself, and connects only to the pinned origin — the caller never
  supplies a URL. Redirects are never followed (exactly one wire request observed;
  the Location target never appears in the error), non-2xx responses are redacted
  to a status class (provider error bytes never surface), and responses are read
  under the bound ceiling. Secrets never appear in reprs or errors.

Tests: `app/tests/test_provider_transport.py` (9) over a real loopback HTTP fake
server — auth injection round trip, seven zero-effect header canaries, six
destination canaries, redirect non-follow, provider-error redaction, request and
response size ceilings, cross-provider/retired handle enforcement, secret-leak
sweep, and fail-closed binding validation.

```text
python -m pytest -q app/tests/test_provider_transport.py
9 passed
ruff check app/workers/provider_gateway.py app/tests/test_provider_transport.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,058 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
78c184e6976bb24c8bd673072567857daf27ffed361ecdff7220e27f8c815064  app/workers/provider_gateway.py
dd1668deaeb74aa86143c4ad022d55ed754c2787fb691d5f29c37f6242fa09de  app/tests/test_provider_transport.py
```

Still not claimed: HTTPS/TLS qualification against a real provider origin, the
HTTP create/rotate ingress wire checks, UDS service wiring, budget binding into
the runtime ledger, the T087 provider-transport manifest, and any independent
adversarial audit of the vault/transport pair.

## Create/rotate ingress wire checks (2026-09-13)

`app/api/credential_ingress.py` implements the control-plane wire gate through
which a raw secret may cross exactly once on its way to the gateway:
`parse_credential_ingress(raw_headers, body)` requires exactly one decimal
`Content-Length` (strict `0|[1-9][0-9]*`, no signs/spaces/leading zeros) of at
most 96 KiB whose value equals the actual body length, rejects any
`Transfer-Encoding` or `Content-Encoding` occurrence, requires a single JSON
content type, and parses the strict intent object (exact keys
`intent_id`/`provider`/`secret` plus optional `rotate_from`) with a canonical
UUID intent, bounded provider identifier, 1..65,536-byte UTF-8 secret and a
well-formed rotation handle. Every violation fails before any intent or vault
effect; errors are sanitized and never carry secret bytes; the module retains no
copy beyond the returned value.

Tests: `app/tests/test_credential_ingress.py` (7) — create/rotate parse,
eight framing rejections (missing/duplicate/signed/hex/spaced/leading-zero/
mismatched/oversized Content-Length), four encoding-header rejections, ten
strict-body rejections, an over-secret-bound body within acceptable framing,
secret-free errors, and JSON content-type enforcement.

```text
python -m pytest -q app/tests/test_credential_ingress.py
7 passed
ruff check app/api/credential_ingress.py app/tests/test_credential_ingress.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,065 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
ceccf3f347cbb71aa11ebe0a0ac171d3c08de8c05456a6127f8698668432de7e  app/api/credential_ingress.py
b3c3697bbd218d05cbbf5560119a19bbecab61bfc94b1be1439ba9e61daf4e28  app/tests/test_credential_ingress.py
```

Still not claimed: the ingress is not yet mounted on an authenticated HTTP route
or forwarded over the gateway UDS, lost-response/race persistence cases remain,
and no independent adversarial audit of the T090 slices has run.

## Independent adversarial audit and remediation (2026-09-13)

An independent adversarial audit subagent attacked the vault/transport/ingress trio
at 957d8b9 (probe scripts preserved in the session scratchpad `t090-audit/`).
Verdict: **REJECT** — one P1 and three P2, all reproduced; all four are now fixed
with per-finding regression tests:

- **F1 (P1, fixed):** a secret containing CR/LF (realistic for PEM-format keys)
  leaked in cleartext through `http.client.putheader`'s `ValueError` message, which
  escaped the transport's `except OSError`. Fixed in three layers: the vault and
  the ingress now reject control characters in secrets before any effect; the
  transport validates header-safety of the resolved secret before injection and
  fails closed (`credential is not header-safe`); and the wire `except` now
  catches `ValueError` with a severed cause chain (`from None`) so a framing
  error can never carry the header value. Regression: a monkeypatched hostile
  resolution raises a sanitized `GatewayError` with zero network effect and no
  secret in the message or cause.
- **F2 (P2, fixed):** a lone-surrogate secret crashed the ingress with an uncaught
  `UnicodeEncodeError` carrying the offending character; the encode is now guarded
  and control characters are rejected with sanitized errors.
- **F3 (P2, fixed):** a crash between the secret commit and the index commit left
  an unreferenced, un-erasable secret file. Startup reconciliation now also
  garbage-collects committed secret files that no index record references, and the
  regression test walks the whole vault tree for secret bytes after a simulated
  crash.
- **F4 (P2, fixed):** the store path was a lock-free check-then-act: concurrent
  stores dropped committed records via stale index snapshots and one intent could
  alias up to eight handles. All vault operations now hold a process lock;
  regressions drive 40 parallel distinct intents (all survive reload) and 16
  parallel replays of one intent (exactly one handle and one secret file).

Invariants the audit could NOT break (its probes listed in the report):
destination/header pinning including unicode-lowercase collisions and prefix
confusion, handle opacity and rotation/retire/erase lifecycle including
resurrection attempts, and every ingress framing trick attempted
(trailing-space names, CR-tailed lengths, duplicate lengths/types, BOM bodies).

```text
python -m pytest -q (three T090 suites, post-remediation)
30 passed
ruff check (six touched files)
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,070 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities after remediation (SHA-256):

```text
2f048fc0b6c9d9ed106e8cc8b58cb85bf4fe020b99521280a196263f58046018  app/workers/credential_vault.py
1a9a0c31c72cb9a9613a43cac95499584d3646a05482164c1a66c5ad9998ad96  app/workers/provider_gateway.py
c59ce54f35a3428da04c27047972f131a483a5016567eb5d93153a306cbda34b  app/api/credential_ingress.py
```

This remediation itself has not been independently re-audited.

## Authenticated ingress route (2026-09-13)

`app/api/credential_routes.py` mounts `POST /api/v1/credentials` on the existing
session/CSRF authority. The route applies the exact wire checks
(`parse_credential_ingress` over the raw ASGI header pairs) before any effect and
hands the validated intent to a host-wired `credential_gateway_submit` callable on
application state — the control plane never imports the vault implementation, and
`create_app` attaches no gateway by default, so the route is honestly
`dependency_unavailable` until the UDS-backed gateway client exists. The gateway's
receipt is validated to the exact redacted shape (`handle`/`provider`/`state`);
any other shape — including a hostile receipt echoing the secret — is rejected as
a sanitized 503 and never reaches the browser.

Tests: `app/tests/test_credential_routes.py` (5, over the real app and local
boundary) — CSRF-less write refused by the boundary; gateway-less unavailability;
a valid intent forwarded exactly once with a redacted 201 receipt; five wire
violations rejected 400 with zero gateway effect and no secret in any response;
and a misbehaving gateway receipt never echoed.

```text
python -m pytest -q app/tests/test_credential_routes.py
5 passed
ruff check app/api/credential_routes.py app/tests/test_credential_routes.py
All checks passed  (server.py carries 3 pre-existing whole-tree findings, unchanged)
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,075 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
cffd70c8e287f532b2543dee9a09c209cb4ddaafc7948243747c6fbc6d5da23c  app/api/credential_routes.py
f17a0293e54752ebd497b36ded840d2493177d31997009c047e42668119781e1  app/tests/test_credential_routes.py
```

Still not claimed: no UDS-backed gateway client exists (the state attachment point
is honestly empty in production), GET/status/catalog zero-effect routes, delete
retirement flow, and lost-response/race persistence cases remain open.

## Delete retirement and zero-effect status reads (2026-09-13)

Two more authenticated routes complete the control-plane surface:

- `DELETE /api/v1/credentials/{handle}`: CSRF-gated; the handle format is
  validated before any boundary call; the intent forwards to a host-wired
  `credential_gateway_retire` callable (honestly unavailable by default) and the
  receipt is validated to the exact `{handle, state}` shape with state in
  `cleanup_pending`/`erasure_completed` — the UI can therefore distinguish local
  erasure from remote provider revocation, and a hostile receipt is a sanitized
  503.
- `GET /api/v1/credentials`: a session-gated snapshot read of already-known
  redacted state via `credential_status_snapshot`. The regression proves the
  zero-effect rule: with submit/retire boundaries armed as spies, a status read
  touches neither — no vault, gateway, provider or network effect — and a
  snapshot carrying anything beyond `{handle, provider, state}` is rejected
  without echoing.

Tests: 6 more in `app/tests/test_credential_routes.py` (11 total).

```text
python -m pytest -q app/tests/test_credential_routes.py
11 passed
ruff check app/api/credential_routes.py app/tests/test_credential_routes.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,081 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
5fd725350be19b32edd252c6c4230c9da963a1b93339098e9930ee29ad4f2313  app/api/credential_routes.py
0a3ba176b053cafe5b95ac0586ecbc1659e981e5c1515fefe1b3c5f5e50fe129  app/tests/test_credential_routes.py
```

Still not claimed: no UDS-backed gateway client/service wiring, no
lost-response/race persistence cases, no T087 provider-transport manifest, and
the T090 route/wiring additions since the audit (routes, delete, status) have
not been independently audited.

## Gateway service and control-plane client over broker frames (2026-09-13)

`app/workers/credential_gateway_service.py` closes the channel between the two
sides. `CredentialGatewayService.serve_one` answers exactly one `credential_op`
frame per authenticated codec with a `credential_result` frame: the closed
operation set is store, delete (retire of an active record followed by verified
erase), snapshot (redacted, excluding erased records), health and capabilities —
`resolve_for_gateway` is deliberately not a channel operation; resolution stays
inside the gateway for the provider transport alone. Vault rejections become one
sanitized rejection code. `CredentialGatewayClient` (control plane) never
imports the vault: it speaks frames through an injected transport factory,
binds each response to its request's message id, and surfaces failures as
sanitized `GatewayServiceError`s.

Tests: `app/tests/test_credential_gateway_service.py` (5) over real socketpairs
with full broker handshakes and live codecs on a dedicated
`control-to-credential-gateway` channel — store round trip with a redacted
receipt and gateway-side resolution; a wire log proving no outbound service
payload ever carries secret bytes; delete performing retire+verified-erase;
redacted read-only snapshot; and sanitized conflict/forbidden-operation/unknown-
operation rejections with no secret in any error.

```text
python -m pytest -q app/tests/test_credential_gateway_service.py
5 passed
ruff check app/workers/credential_gateway_service.py app/tests/test_credential_gateway_service.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,086 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
5925a3224555c3ff131b0885a32e1696050b54428835bb81e2ff3acc1dff4d55  app/workers/credential_gateway_service.py
67a51d879fd94d9f8352b9b6b24cda17fab7297c7775d37ca7bdadc19e30c472  app/tests/test_credential_gateway_service.py
```

Still not claimed: production wiring of the client's transport factory to a real
UDS endpoint (connect_verified/client_handshake with SO_PEERCRED needs the Linux
canary, blocked on the host's Docker fault), attachment of the client to the
HTTP routes' state seams, the T087 provider-transport manifest, and an
independent audit of the post-audit T090 additions (routes + channel).

## Control-plane boundary split and end-to-end attachment (2026-09-13)

The channel client moved into `app/workers/credential_channel.py`, which imports
no vault code (verified by an import probe), so `attach_credential_gateway` in
`app/api/credential_routes.py` can bind a client to the route state seams
without the control plane ever transitively importing the vault implementation.
A full-stack regression now drives the entire T090 offline chain live: an
authenticated browser-style HTTP POST crosses the ingress wire checks, the
frame channel with a real broker handshake, and the gateway service into the
vault (resolution verified gateway-side); the snapshot GET lists it redacted;
and DELETE completes retire + verified erase — with no secret bytes in any HTTP
response.

```text
python -m pytest -q app/tests/test_credential_routes.py app/tests/test_credential_gateway_service.py
17 passed
ruff check (four touched files)
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,087 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
050b38b3af2640a7f1ce5e17297cf3a8fad9802e537c4125403f933bd212393b  app/workers/credential_channel.py
9d9f93bee372ade5b6a60a247c3d3391946d70b4b37211bb9e9c2af5943ca45c  app/workers/credential_gateway_service.py
b5de9ae5e9105e158e54e5c531ba79846ec89ccaa504d8f52139479e29803d96  app/api/credential_routes.py
```

Progress note: the weighted table's first-use/providers package moved 0.55 → 0.60
for this once-audited T090 control-plane arc (total 38.05, user-facing roughly
40%). Real UDS endpoint qualification, the T087 manifest, budget binding and a
re-audit of the post-audit additions remain open.

## 2026-09-25 — real-UDS kernel peer credentials, lost-response and race persistence

Scope note: since the sections above, the gateway moved to the encrypted `credential-op-v2`
custody (`store_at`/`query_record`/`retire`/`snapshot`/`health`/`capabilities`; the v1
`store`/`delete` are refused `unsupported_operation`) and the owned shared gateway profile
(`gateway_channel.py`, `CredentialGatewayClient.for_gateway`, `ProviderGatewayIngress`) landed.
This slice adds **tests only**; no production module changed.

### Real Unix-domain socket with SO_PEERCRED (`app/tests/test_credential_gateway_peercred.py`, 4)

The earlier "Still not claimed" item — the client's transport on a real UDS through
`connect_verified`/handshake with SO_PEERCRED, which needed the Linux canary blocked on
Docker — is verified here without Docker. The test (root on Linux only; skipped elsewhere) starts
the gateway and the control plane as **separate processes** through `subprocess` with
`user=`/`group=`/`extra_groups=` set to the fixed identities of the production `cp-provider`
profile (control 20102:20102, provider 20103:20103, pair group 21101). The child module
`app/tests/support/credential_peercred_child.py` patches nothing in the broker, handshake,
`connect_verified` or listener; the only change is the module-local profile resolution,
moved to an owned 0755 temporary pair root (the pair root is initialized by the real
`ipc_root.initialize_pair_root` as root). The socket is reached through `/proc/self/fd`, and every
peer check reads the kernel's SO_PEERCRED.

- The gateway child initializes an encrypted vault as the provider identity, binds the real
  `WorkerListener` and serves each accepted owner through `CredentialGatewayService.serve_connection`.
  The control child uses `CredentialGatewayClient.for_gateway` to run store_at → query_record → replay under the
  same command id with *different* bytes (the original receipt comes back) → snapshot, then
  retire(owner_delete) → query (`cleanup_pending`). The journal as oracle shows (1 command,
  1 nonce, 1 receipt, 1 retirement): the replayed secret was never ingested. A whole-tree sweep
  finds neither secret nor its sha256, and the listener unlinked its socket on close.
- A wrong requester UID (20104), or the right UID with a wrong primary GID, in both cases
  **holding the pair group** (the socket mode admits its connect), is refused by the gateway's
  accept with `PeerCredentialError`. The client sees only the sanitized
  `gateway channel failed` / `credential_operation_rejected`, the journal stays (0,0,0,0), and the
  same listener then serves the real control identity.
- An impostor responder: root listens on a socket file with the exact expected owner, group and
  mode 0660, so every path/inode/mode check passes. The control child's `broker.connect_verified`
  refuses it with `PeerCredentialError`, and the impostor's accepted connection reads EOF (zero
  bytes written).
- Mutation check (temporary, reverted, not committed): with `broker._verify_peer` short-circuited, all
  three refusal tests fail, and the wrong-UID requester actually **stored a credential**. Among the pair
  group's members, SO_PEERCRED is the only barrier: the boot secret is readable by the pair group, so the handshake
  MAC alone does not tell pair members apart. This is a property of the design as it stands, recorded here
  and not changed.

### Lost-response, races and lost ingress over the channel (`app/tests/test_credential_gateway_persistence.py`, 15)

These run over real authenticated broker frames on socket pairs (the in-process harness
shape). A lost response is injected at the only place it can occur after a commit: the service's reply
write closes the connection instead of answering. The vault is the oracle throughout.

- Lost create and lost rotate (`store_at` with a predecessor reference, version+1): the client
  gets the sanitized channel failure with no secret or hash in the message or cause. `query_record` returns
  the committed receipt. A replay under the same command id with other bytes returns that receipt, and
  the authenticated private open still yields the original secret. A changed intent under the lost
  command id is `conflict`. The rotation predecessor is unchanged, and the state survives reopen.
- Lost retire (`owner_delete` and `superseded`): the same command id replays the identical
  retirement body, a changed reason is `conflict`, and neither a replayed store nor a reopen reverses
  `cleanup_pending`.
- After a lost response, a wrong retry under a *new* command id for the same record/version is
  `conflict` (the target ingests once).
- Six concurrent `store_at` under one command id with six different secrets, for both create and
  rotate: every racer gets the one receipt and the journal grows by exactly one
  command/nonce/receipt. Four concurrent rotations of one predecessor under distinct command ids:
  exactly one successor, three `conflict`.
- Delete racing rotate (delete first, rotate first, and concurrent): the predecessor ends
  `cleanup_pending` under both retirement intents and the successor stays `stored_unbound`. Replays
  cannot resurrect the predecessor, and the result holds across reopen.
- Missing record: a create or rotate whose process crashed after journaling the pending command
  (before encryption) reopens as `secret_input_lost` over the channel. A replay with fresh bytes
  returns `secret_input_lost` and never ingests them (the bytes appear nowhere on disk), the snapshot lists
  the state, retirement of any reference to it is `conflict`, and a lost rotation leaves its predecessor exactly as it was.
- Zero-effect reads: query (known and unknown), snapshot, health and capabilities over frames
  leave the journal counts and every vault file byte-identical and never call seal/open.
- Zero provider effect: over the real listener and the shared `ProviderGatewayIngress` (credential
  and send services on one vault), a create, a rotate, a superseded retire and an owner delete never call
  `delivery_for_exchange`, `HTTP(S)Connection.connect`, `socket.create_connection`/`getaddrinfo`,
  or any send-engine entry (`_serve_dialogue`, `serve_*`, `prepare`).

```text
env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q -p no:cacheprovider \
  app/tests/test_credential_gateway_peercred.py app/tests/test_credential_gateway_persistence.py
19 passed   (repeated 5x serially: 19 passed each time)
... plus test_credential_{custody,gateway_service,import_boundary,ingress,root,routes,vault}.py,
    test_provider_transport.py, test_provider_gateway_channel.py, test_provider_gateway_owned.py
234 passed, 1 known warning   (215 before this slice + 19)
ruff check (three new files)
All checks passed
```

The full shared regression was not re-run for this slice. No production file changed.

Frozen identities (SHA-256):

```text
6f16c36db92572672cc2d3fef34a6d21e470380d457a702781df8286db3663a0  app/tests/test_credential_gateway_peercred.py
c10fb712650e86c0c2b30d0106276b6896d26283f3e946cd6a5b6a92dfbbe7d5  app/tests/test_credential_gateway_persistence.py
bd58bfe3d2aec343940e82ab516bcc1459c89f07a02377c039423810235162d5  app/tests/support/credential_peercred_child.py
```

Still not claimed: the real-UDS qualification ran in this development container as root, with
synthetic numeric identities. It did not run in the candidate service image, and no production bootstrap yet
binds the listener, initializes the `cp-provider` generation or establishes the requester-boot trust.
The HTTP routes (`app/api/credential_routes.py`, `attach_credential_gateway`) still forward the v1
`store`/`delete` shapes, which the v2 gateway refuses, so there is no working v2 create/rotate/delete route or
control-side command-id allocation and query-after-ambiguity flow yet. Rotation does not yet invalidate
catalog/model authority (no binding CAS exists). Erasure/`vault-maintenance` and `erasure_completed` remain
unavailable by design. The T087 provider-transport manifest and budget binding are not implemented. No
independent audit of these additions has run.

## 2026-09-25 — HTTP create/rotate/delete routes over credential-v2, control-side command ids

This slice closes the gap recorded just above: the authenticated HTTP routes now speak the current
gateway protocol end to end, and the control plane allocates and recovers gateway commands itself.

### What works

- `app/api/credential_commands.py` (new, control plane; imports no vault code):
  - `CredentialCommandLedger` — a 0600 SQLite ledger of owner acts. Each act is keyed by the
    browser's `intent_id` (the act's idempotency key) and a fingerprint of its nonsecret request
    (kind, provider, rotation target). Before any gateway call, one transaction records the act's
    allocated gateway `command_id`, target `record_id`/`record_version`, `created_at` and predecessor
    reference, plus the retirement command id and reason for a rotation (`superseded`) or delete
    (`owner_delete`). The ledger stores no secret, secret hash or verifier. Receipted records
    (`stored_unbound`/`cleanup_pending`) are kept here too.
  - `CredentialActs` drives each act over the frame-only `CredentialGatewayClient`. `store_at` is
    sent at most once per command id, and a compare-and-set claim picks the one sender under
    concurrency. The command is released for the same act only on a pre-send failure (the new
    `GatewayServiceError.sent is False`: the connection or handshake failed before any request byte)
    or a definitive non-admission answer (`busy`, `capacity_exhausted`, `nonce_exhausted`,
    `invalid_*`). Any other failure is ambiguous. That request and every retry of the act then
    call `query_record` on the same command id and never re-send a secret. A retry adopts the
    committed receipt. `unknown`/`pending` return a retryable `503 command_pending` and never lead
    to a new id or a loss verdict. The gateway's `secret_input_lost` is terminal (`409
    secret_input_lost`, not retryable): the same act never ingests re-entered bytes, and only a new
    act with a fresh intent can try again. A changed request under a used intent is `409
    conflict`. Retirement carries no secret, so an ambiguous retire is recovered by replaying the
    same retire command. Only one unfinished rotate/delete act may target a handle at a time;
    others get a retryable `409 conflict`, which prevents a delete racing an in-flight rotation.
- `app/api/credential_routes.py`:
  - `POST /api/v1/credentials` creates, or rotates when `rotate_from` is set. It returns `201
    {handle, provider, state: "stored_unbound"}`. The handle is the record id in hex and is stable
    across rotations.
  - A rotation stores version+1 with the exact predecessor reference, then retires the predecessor
    (`superseded`).
  - `DELETE /api/v1/credentials/{handle}` takes the exact body `{"intent_id": uuid}` and returns
    `{handle, state: "cleanup_pending", provider_revocation: "not_performed"}`.
  - `GET /api/v1/credentials` now reads the ledger snapshot only. The earlier attachment read the
    gateway `snapshot`, which was a gateway dispatch on a GET. Each entry also carries
    `provider_revocation: "not_performed"`, which keeps local erasure distinct from provider-side
    revocation.
  - Blocking gateway calls run in the threadpool.
  - `attach_credential_gateway(app, client, ledger)` now takes the ledger.
  - A redacted-projection check still rejects any seam result with extra fields.
- `app/api/credential_ingress.py`:
  - Oversize framing or a secret over 65,536 bytes raises `CredentialIngressTooLarge`, which the
    route maps to 413 as the API contract requires. Other violations stay 400.
  - Duplicate JSON keys are now refused. Before this, a later `secret` silently won.
  - Decode errors are no longer chained. A `JSONDecodeError` holds the whole body, secret included.
- `app/workers/credential_channel.py`: `GatewayServiceError` gains `sent`, and `_call` marks
  connect/handshake failures `sent=False` with the same code and message. The legacy
  `submit`/`delete` stay only for the gateway's existing refusal pins, and no route calls them.
  The C408 lint findings in this file predate this slice.

### Tests

`app/tests/test_credential_routes_v2.py` (10, new) runs over the real development app (session,
CSRF, ingress checks), the ledger, the real client and real authenticated broker frames into
`CredentialGatewayService` and an encrypted vault (the persistence harness). The vault journal is
the oracle, and the teardown sweep finds no secret in logs, the ledger or any file.

- create → rotate (successor stored, predecessor `cleanup_pending` under `superseded`) → delete,
  journal (2, 2, 2, 2), then new acts on the retired handle are refused (`409`) with zero effect.
- A same-act replay with a different secret returns the original receipt without a gateway call.
  The same key with a changed provider or target is `409`.
- Lost store response (create and rotate): with both the store and the recovery-query replies
  lost, the request is `503 command_pending`. A retry with other bytes calls only `query_record`,
  adopts the receipt, then retires the predecessor for a rotation. The decrypted record is the
  original secret. With one lost reply, the same request recovers.
- A lost retire response is recovered by replaying the same retire command, still one retirement.
- `secret_input_lost`: the gateway journals the command, then its process crashes before
  encryption. The route returns `409 secret_input_lost`. The same act with re-entered bytes makes
  no gateway call, the snapshot lists the state, and a new act succeeds.
- Route-level refusals: an unsupported provider, unknown rotate/delete targets, oversize framing
  (413) and missing CSRF all have zero gateway or vault effect. A pre-send failure releases the
  command for the same act. An unfinished rotation blocks delete and other rotations until it
  settles.
- Status reads with every client operation patched to fail leave the vault tree byte-identical.

`app/tests/test_credential_routes.py` (11) was updated to the seam shapes: `stored_unbound`
receipts, delete with an intent body, duplicate-key/413/query refusals, and
`provider_revocation`. The v1-refusal full-stack test moved to the v2 file as working flows.

```text
env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q -p no:cacheprovider \
  app/tests/test_credential_{custody,gateway_peercred,gateway_persistence,gateway_service,import_boundary,ingress,root,routes,routes_v2,vault}.py \
  app/tests/test_provider_transport.py app/tests/test_provider_gateway_channel.py \
  app/tests/test_provider_gateway_owned.py app/tests/test_web_owner_integration.py app/tests/test_first_party.py
340 passed, 1 known warning   (331 on the base commit; -1 legacy full-stack test, +10 new)
app/tests/test_server_api_v1.py app/tests/test_first_party_dependencies.py: 60 passed
ruff check (credential_commands, credential_routes, credential_ingress, both route tests): All checks passed
```

Mutation check (temporary, reverted): treating every store failure as "not admitted", which would
re-send the secret under the consumed command, fails 4 of the 10 new tests: both lost-response
cases, `secret_input_lost` and the unfinished-rotation guard.

Route counts: no route was added (the same three paths), and these routes are not in the
first-party route contributions, so `test_first_party` route counts are unchanged.

Frozen identities (SHA-256; this block supersedes the earlier blocks above for these paths):

```text
8e4b4011037f0916978e192dd96e4224262110b3690d7615ff5f48f6eace0aed  app/api/credential_commands.py
d416c31132a7dc581c69a80095b8711da0ff5315e426c28f2b0a6554985c1121  app/api/credential_routes.py
202cf1b870f7dfa3ad39f29b1f2984bdf763a7d23c925341be24ea0ac877982c  app/api/credential_ingress.py
6719f948e5a14c26894b6da613ee01552fe185a2072b94b3247deee01ca474bd  app/workers/credential_channel.py
4edd09cd8a9baf1b800f184057099c4c50ec4e1c11d8c6cec0c6e160c178da7c  app/tests/test_credential_routes.py
f3f14f96f9a61ae280ae727c08341cf09bca5eff5b50e662b4929ea738bce1ff  app/tests/test_credential_routes_v2.py
```

### Remaining

- No production bootstrap creates the ledger, binds the listener or calls
  `attach_credential_gateway`, so the routes stay honestly `503` in a deployed app.
- The ledger is a separate SQLite file, not part of the main DB's command transaction. There is no
  provider-binding CAS, so a stored credential is `stored_unbound`, never an active binding. Rotation
  does not yet invalidate catalog/model authority.
- An act whose command stays `unknown` (the request may or may not have reached the gateway)
  blocks further rotate/delete on that handle. Resolving it needs the separate cancel/fence
  protocol the custody contract defers, and create orphans are not yet retired as
  `unbound_orphan`.
- The browser-facing handle is the record id. The API contract's "no handles in creation
  responses" wording is still to be reconciled with the addressable rotate/delete routes.
- Erasure (`vault-maintenance`, `erasure_completed`), the T087 manifest/budget binding, a UI page
  and an independent audit of this slice remain open. The full shared regression was not re-run.

## 2026-09-25 — supported-factory wiring and the owner credential UI

This slice addresses the first item under "Remaining" above: the routes now exist in the supported
factory and are wired whenever the deployment names the gateway. The gateway-side bootstrap is
still not built.

### Production wiring

- `app/api/credential_wiring.py` (new, control plane; imports no vault code):
  - `CredentialGatewayConfiguration` is the deployment's optional, nonsecret naming of the gateway
    endpoint. It is the exact object `{"schema": "deeptwin-credential-gateway-attachment-v1",
    "pair_root", "requester_boot_id"}` (absolute pair root, broker boot-id grammar).
  - `open_credential_attachment` checks the named pair root against the fixed profile
    (`gateway_channel.gateway_channel()`, i.e. `/run/deeptwin/ipc/cp-provider`). Any other path
    fails the start with `ValueError`. There is no fallback.
  - It then opens the `CredentialCommandLedger` at `<instance state dir>/credential-commands.sqlite3`
    (0600) and builds `CredentialGatewayClient.for_gateway`. Each call of that client runs
    `listener.connect_authenticated`, which covers readiness-record verification, the socket
    inode/owner/mode check, `broker.connect_verified` with SO_PEERCRED, and the boot-secret
    handshake.
  - The `credentials-v1` first-party contribution (`route_contributions/credentials-v1.json`) adds
    three routes: `credentials.read` (GET), `credentials.store` (POST) and `credentials.delete`
    (DELETE `/api/v1/credentials/{handle}`). They use `browser_session` and work.read/work.command
    and are installed after `claude-connection-v1`.
- `app/api/credential_routes.py`: `install_credential_ingress(target, *, seams=None)` now also
  mounts on an `APIRouter` with fixed `CredentialSeams`. Without seams, the development host still
  reads `app.state`. `credential_seams(client, ledger)` binds `CredentialActs`, and
  `attach_credential_gateway` uses it. Route behaviour and projections are unchanged.
- `app/api/first_party.py`: `ApplicationContext.credential_gateway` must be `None` or an exact
  `CredentialAttachment`.
- `app/server.py`:
  - `create_app(..., credential_gateway=None)` opens the attachment once the serving lock, the
    Store and the API components exist, hands it to the composition and exposes it as
    `app.state.credential_attachment`.
  - `main()` accepts `--credential-gateway-config <json>`.
  - Without it, the routes are composed unbound and answer `503 dependency_unavailable`. No ledger
    file is created and no connect is attempted.
- Route count: 73 → 76 installed. The pinned counts and id lists in `test_first_party`,
  `test_web_owner_integration`, `test_works_api`, `test_runs_api` and `test_provider_source_startup`
  were updated.

### Owner UI

`app/static/account.mjs` gains `createCredentialsPanel`. It is mounted on the records page next to
"계정과 세션" (`records-credentials` in `records.html` and `records-page.mjs`). No new static module
was added.

- The list shows only the redacted projection: provider · handle · state label.
- The panel states that deleting locally does not revoke the key at the provider. The delete
  confirmation says `provider_revocation: not_performed`.
- Add and rotate use a masked field. It is read once and cleared synchronously before the request
  leaves, and a rotate carries `rotate_from`. The secret goes into no attribute, dataset, status
  text or storage.
- Delete asks for explicit confirmation and sends only `{intent_id}`.
- `command_pending` keeps the act's intent in memory, and the next submit ("결과 다시 확인") reuses
  it. The server then only queries the earlier command and never ingests the re-entered value.
- `secret_input_lost` is terminal: the next submit gets a new intent.
- `dependency_unavailable` (gateway not attached or not answering) is shown as unavailable, with no
  list.

### Tests

`app/tests/test_credential_gateway_startup.py` (6, new):

- **Real UDS through the real factory** (root on Linux; skipped elsewhere).
  - The parent initializes the relocated `cp-provider` pair root and starts the existing gateway
    child (`credential_peercred_child`, role `serve`, provider identity 20103 with pair group
    21101).
  - The new `app/tests/support/credential_app_child.py` runs the actual `create_app` as control
    identity 20102:20102 plus the pair group, with a configuration naming that pair root. The only
    substitution is the module-local profile relocation.
  - The child bootstraps an owner session over HTTP, then runs:
    - create: 201 `stored_unbound`;
    - GET;
    - rotate: 201, same handle;
    - GET;
    - delete: 200 `cleanup_pending`, `provider_revocation: not_performed`;
    - GET: `cleanup_pending`.
  - What the parent checks:
    - the gateway served exactly 4 sessions (the GETs make no gateway call);
    - the vault journal counts are (2, 2, 2, 2) and health reports `cleanup_pending` = 2;
    - the ledger is 0600 and owned by the control UID;
    - no vault module was loaded in the control process;
    - a sweep finds neither secret nor its sha256 anywhere in the tree.
- **Unnamed gateway.** The routes are composed and sit behind the owner session (401 without one).
  GET, POST and DELETE answer 503 `dependency_unavailable` with no secret echoed. No ledger file
  exists, and `listener.connect_authenticated`/`broker.connect_verified` are patched to fail if
  called.
- **Wrong or invalid naming.** A wrongly named pair root, or a non-configuration object, fails
  `create_app`, and no ledger is created.
- **Fixed pair root without a gateway.** The fixed pair root binds a 0600 ledger and the fixed
  client without connecting.
- **Configuration exactness.**
- **`main()`.** It passes `None` without the flag and the parsed configuration with it.

Other test changes:

- `app/tests/test_credential_import_boundary.py` also imports `app.api.credential_wiring` and
  `app.api.first_party_catalog` in the fresh control interpreter. It still finds no vault or crypto
  module.
- `app/tests/account-credentials.test.mjs` (9, new, `node --test`):
  - the redacted list and the revocation text, with no actions on retired rows;
  - add: the field is cleared synchronously and exactly one request carries the secret. Afterwards
    the secret is in no text, attribute, dataset or value, and `localStorage`/`sessionStorage` are
    never touched;
  - an empty secret sends nothing;
  - rotate carries `rotate_from`;
  - delete asks first, then sends only the intent;
  - `command_pending` for create and for delete: the retry reuses the same intent;
  - `secret_input_lost`: the next act gets a new intent;
  - unavailable and offline.
- Mutation check (temporary, reverted): composing `credentials-v1` unbound even when a gateway is
  named fails the real-UDS test.

```text
env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q -p no:cacheprovider \
  app/tests/test_credential_{custody,gateway_peercred,gateway_persistence,gateway_service,gateway_startup,import_boundary,ingress,root,routes,routes_v2,vault}.py \
  app/tests/test_first_party.py app/tests/test_first_party_dependencies.py \
  app/tests/test_provider_gateway_channel.py app/tests/test_provider_gateway_owned.py app/tests/test_provider_transport.py \
  app/tests/test_server.py app/tests/test_server_api_v1.py app/tests/test_server_session_integration.py \
  app/tests/test_web_owner_integration.py
433 passed, 2 warnings (the known starlette deprecation; one transient unraisable socket warning
  that did not reproduce in any subset run)
app/tests/test_{works_api,runs_api,provider_source_startup,web_shell_assets,router_composition,claude_live_path}.py
125 passed
node --test app/tests/{account,account-credentials,records-page,claude-connection,session,settings}.test.mjs
all pass. app/tests/browser-records.test.mjs fails 3/3 here with "Controlled installed runtimes
  required; never skip" (no controlled browser runtime in this container)
ruff check (credential_wiring, credential_routes, startup test, app child): All checks passed
```

Frozen identities (SHA-256; this block supersedes earlier blocks for these paths):

```text
9c727910adf9882ef617eebd7809aaf63ebfa5ec3d9dbd303aabe15108b19ef2  app/api/credential_wiring.py
2c005a15b6e66a270651f75d432a44968aff92f55b109d0f57968f3aba3204e2  app/api/credential_routes.py
e00bcd293514e6e096e6b47d9be82a49ed7f8bea5cda1fb68cef75d4430c070c  app/api/route_contributions/credentials-v1.json
70a7305572da66761515894d1a6a4ccc8f8912e8716f74cf112b37faaaa43af9  app/api/first_party.py
666ca8ccb95cbd22e79de9bb4992eae40838431231dd4f4063ca38d9a7179d46  app/api/first_party_catalog.py
79a6a9cfb4ad3a6a356fa117fcf1305fcddeedd7b866e49419411bf00e5d857b  app/server.py
db0eca79cf3fedae898c011a17c77563c23bb00af03195d37d1078c29c532948  app/static/account.mjs
3e5f3db33a0dffbcb011e66cd7659a31b0401b14d99257e619f3bd5415d8b20f  app/static/records-page.mjs
51a9a41e6ffd7c29cc26b7e0ac5562c31862db9db2eefea2766b38c68f0fe651  app/static/records.html
3f97cffd326ecd5bc941187a4a226e1f6f824771e5f3c6dcadb3f12332007f9e  app/tests/test_credential_gateway_startup.py
29b5ca153b4fb3a8ed4a16fed8d1f9df88ecedd8c46ac2ba5e38b05d49cc05aa  app/tests/support/credential_app_child.py
4253aa791aafd50d5cb3054a6a2a33e7336d5ce3391e064562c0600a93e38cf6  app/tests/account-credentials.test.mjs
e3353626f4e528bfcbe8e72feda0d673aad1f76aa94ccee6ec909ef29b98a139  app/tests/test_credential_import_boundary.py
d5c4470465cef47cc4b1d05c746a444c7f67251e17b7d03adf911b7e1e08dc03  app/tests/test_first_party.py
2af3aff8b8bcd219798e4879753840eaef9bfc5d435e0dc50d9cbd5347cbafa2  app/tests/test_web_owner_integration.py
d8cc8dcc5acbb27432f6575b815d7bf8dcfffcaac6fcc3b2a56ee142fbd121b4  app/tests/test_works_api.py
b101c97be6a2d705cc347a1893e15f8e07d12d3ecdebce212ca1e488237caeb4  app/tests/test_runs_api.py
aa5db484bb6568041179639e39bab6c06c2bfaab760a2786e83ef233faa00b62  app/tests/test_provider_source_startup.py
```

### Still not claimed

- **Gateway-side bootstrap.** No production process yet binds the gateway listener, initializes
  the `cp-provider` generation or serves `CredentialGatewayService`. Nothing establishes the
  requester-boot trust either: the attachment names the requester boot id, and the gateway must be
  configured to expect that same id. Until a gateway serves the pair root, a configured deployment
  answers a retryable `503 dependency_unavailable` (a pre-send connect failure).
- **Qualification environment.** The real-UDS run used synthetic numeric identities as root in
  this development container, not in the candidate service image.
- **Ledger coverage.** The ledger is a separate SQLite file next to `intake.sqlite3`. It is not
  covered by the backup, export or retention flows.
- **Items carried over from the section above.**
  - binding CAS;
  - catalog invalidation on rotate;
  - the unknown-command fence;
  - `unbound_orphan` cleanup;
  - reconciling the API contract's handle wording;
  - erasure;
  - the T087 manifest/budget binding.
- **Audit and regression.** No independent audit of this slice has run, and the full shared
  regression was not re-run.

## 2026-09-25 — production gateway entrypoint, shared boot-label trust, ledger inventory

This slice addresses "Gateway-side bootstrap" and "Ledger coverage" under "Still not claimed"
just above.

### Gateway service entrypoint

`app/workers/credential_gateway_main.py` (new) is the provider service's process on the
`cp-provider` pair: `python -m app.workers.credential_gateway_main
--service-config=<abs> --attachment-config=<abs>`. It follows the `provider_worker` pattern
(fixed argv, exit 0 on a requested stop, 1 when unavailable or poisoned, 2 for argv or
configuration outside the exact shapes).

- **Configuration.** The service configuration is the exact nonsecret object
  `{"schema": "deeptwin-credential-gateway-service-v1", "vault_id", "root_directory",
  "records_directory"}`. The attachment configuration is the very object the control plane
  reads through `--credential-gateway-config`. Both are read as one regular non-symlink file
  of at most 4,096 bytes and parsed by the strict `domain.wire.parse_json_object`, which
  refuses duplicate keys. The attachment's pair root must equal the fixed profile's
  (`gateway_channel.gateway_channel()`); anything else exits 2 before any open.
- **Vault.** `CredentialVault` is opened under the profile's fixed provider UID/GID. The
  entrypoint never initializes, repairs or replaces a pair: genesis stays the
  deployment-only `initialize_credential_root`. An unopenable pair exits 1 without binding.
- **Pair-root generation.** The generation is created and rotated only by the root-owned
  initializer (`ipc_root.initialize_pair_root`; a responder cannot). The entrypoint
  validates it through the existing `listener.bind_worker_listener`. That call requires the
  process to be the responder UID/GID with the pair group. It acquires the generation under
  its shared lock, checking the owners and modes of the pair root, `generation.lock`,
  `boot-secret` and the 02710 endpoint. It removes only a stale listener pair of its own,
  binds the 0660 socket and publishes the HMAC readiness record under a fresh
  `secrets.token_hex(32)` responder boot id.
- **Serving.** The channel's in-flight bound is 1, so one owner is served at a time. The loop
  waits for a queued connection in 0.25 s `select` slices, then calls `accept_authenticated`
  under a fresh 30 s operation deadline. An idle wait therefore never shortens a client's
  handshake window. It then runs `CredentialGatewayService.serve_connection` on the owner.
  - A refused peer (SO_PEERCRED, wrong boot label, bad handshake) or a failed dialogue closes
    only that connection.
  - Listener or generation integrity loss, such as a pair re-initialized for a new boot,
    exits 1 so the supervisor restarts the gateway against the new generation. It never
    retries with weaker checks.
  - The service's boot-secret constructor argument is only type-checked; frames are
    authenticated by the generation secret through the listener. It receives a fresh random
    value, which keeps the generation secret out of the service object.
- **SIGTERM/SIGINT.** The handler only sets a flag, so a vault mutation in progress is
  never interrupted. The current dialogue completes, then the listener unlinks its socket
  and `listener.json`, the vault closes, and the process exits 0 after `gateway_stopped`.
- **Logging.** Each stderr line is one JSON object from a closed vocabulary
  (`gateway_ready`, `session_accepted`, `session_served`, `session_refused`,
  `session_failed`, `gateway_unavailable`, `configuration_invalid`, `gateway_stopped`). An
  entry carries at most an exception class name: never a message, path, metadata, secret,
  hash or boot id. Nothing is ever written to stdout.
- **Scope.** It serves the credential-v2 operations only. It does not compose the provider
  send engine (`ProviderGatewayIngress`), which still needs the T087 transport manifest and
  budget binding.

### Requester boot-id trust (no new trust root)

`app/workers/credential_attachment.py` (new) now holds `CredentialGatewayConfiguration`
and `SCHEMA`, moved unchanged out of `credential_wiring.py`, which re-exports them. It also
holds a bounded file reader. The gateway imports this module with no web or control-plane
code.

- The trust mechanism is the existing deployment attachment object. The operator names
  `requester_boot_id` once, and both processes read that same object. The control plane
  connects under the label. The gateway passes it as `accept_authenticated`'s expected
  requester boot, so the broker's handshake proof, which covers both boot ids, fails closed
  on any other label. Neither side generates or overrides it.
- The existing extension probe profile learns the requester boot from the proven hello. The
  shared gateway instead expects the configured label, as the attachment configuration
  already required.
- The label is not a secret and not a trust root on its own. The per-boot pair secret
  written by the root-only IPC initializer authenticates the handshake, and SO_PEERCRED
  tells the pair group's members apart (see the peercred section). The label binds each
  session transcript to the configured pairing.
- The label is static per deployment, not regenerated per control-plane boot. Rotating it
  means rewriting the one attachment object and restarting both services.

### Deployment topology (`deploy/compose.yaml`): unchanged, and why

The compose `provider` service is the gateway's intended home: it mounts `cp-provider`
read-write with pair group 21101. However, the bytes of `deploy/compose.yaml` and
`deploy/security/service-ids.json` are pinned by `BASE_COMPOSE_SHA256`/`RECIPE` in
`app/deployment/contracts.py` and by `deploy/security/deployment-prepare-recipe-v1.json` and
its sibling recipes. Those pins feed the deployment prepare, receipt and provider-source
chains.

Adding the gateway command, two vault volumes (key/data separation), their state-root-init
entries and a shared attachment config would move all of those pins. It would also reopen
the pinned `test_compose_topology` contract. That is a deployment-release change, so this
slice does not make it. The service delta a later T081 change must apply:

- `provider`:
  - `command`: `--service-config=/etc/deeptwin/credential-gateway/service.json`,
    `--attachment-config=/etc/deeptwin/credential-gateway/attachment.json`;
  - the image entrypoint must be `python -m app.workers.credential_gateway_main`;
  - separate `credential-root` and `credential-records` volumes (0700, 20103:20103, created
    by state-root-init), so `depends_on` also names state-root-init;
  - the two configs.
- `control`: the same external attachment config at the path given to
  `--credential-gateway-config`.
- A one-shot vault genesis step (`initialize_credential_root` as 20103) that the compose
  file does not have yet.

`deploy/tests` pass unchanged: 449 passed, 369 subtests.

### Command-ledger inventory

- **Backup** (`app/operations/backup.py`). `credential_command_ledger` joins
  `OUT_OF_SCOPE_CATEGORIES`, so every backup manifest's `excluded_categories` now states it.
  - The ledger (`credential-commands.sqlite3`, 0600, beside `intake.sqlite3`) holds no secret,
    hash or verifier. But every row names a record and command of one specific gateway
    vault, and that vault's root is itself never backed up (`provider_credential_root`).
  - A restored ledger would present handles and pending commands that nothing can resolve.
    A restored instance already requires the owner to re-create credentials
    (`restored_review`).
  - The archive carries only the database and the registered originals, so the ledger was
    never an archive member; the category makes the exclusion explicit.
  - If its tables (`acts`, `records`) were ever moved into the vault database,
    `classify_table` would refuse the backup as unclassified. No secret-exclusion rule
    changed.
- **Export** (`app/operations/export.py`). Unchanged. Its categories are a closed set with
  credentials deliberately not selectable, and the ledger is credential custody
  bookkeeping, not work data.
- **Retention** (`app/operations/retention.py`). Unchanged. It is a value layer over
  registered items (`core`/`cache`/`diagnostics`) with no file inventory. Ledger rows record
  owner acts; `cleanup_pending` rows are released only by the still-unavailable erasure flow
  (`erasure_completed`), not by retention pruning.

### Tests

`app/tests/test_credential_gateway_main.py` (21, new):

- **17 unprivileged tests, which run anywhere.**
  - Six argv shapes exit 2.
  - An attachment naming another pair root exits 2 before any vault or listener call.
  - Eight configuration mutations exit 2: service schema, extra key, nil vault id, relative
    path, attachment schema, bad boot label, duplicate key, invalid JSON.
  - An unopenable vault exits 1 without binding and logs only a class name.
  - A fresh interpreter importing the entrypoint loads no `fastapi`/`starlette`/`uvicorn`,
    `app.api`, `app.server` or `app.services` module.
- **4 real-UDS tests (root on Linux; skipped elsewhere).**
  - Setup: `ipc_root.initialize_pair_root` runs as root, and `initialize_credential_root` runs
    as 20103 (the genesis step). The production entrypoint then starts as 20103:20103 with
    pair group 21101. It goes through `app/tests/support/credential_gateway_launcher.py`,
    whose only change is the module-local profile relocation used by every real-UDS child;
    everything after that is `credential_gateway_main.main`.
  - The real `create_app` runs in `credential_app_child` as 20102:20102 plus the pair group.
    Both read the same attachment file.
  - The four tests:
    1. HTTP create → GET → rotate → GET → delete → GET. The gateway's event log is exactly
       `ready, (accepted, served)×4, stopped`. The journal is (2,2,2,2), the control process
       loaded no vault module, and SIGTERM exits 0 with the socket and `listener.json`
       unlinked while the generation remains.
    2. A control plane whose attachment names another boot label gets `503
       dependency_unavailable`. The gateway logs `session_refused` (class
       `AuthenticationError`) and no `session_accepted`, the journal stays (0,0,0,0), and the
       gateway keeps running and then stops cleanly.
    3. SIGTERM during a dialogue. The dialogue is held at the vault's own mutation lock.
       After SIGTERM the process is still alive; once the lock is released the store
       commits, the HTTP answer is 201, and the process exits 0.
    4. Restart with a pending command:
       - The first gateway is SIGSTOPped while its store waits at the mutation lock. The
         control plane's store and recovery query both time out, and the POST answers
         `503 command_pending`. The journal is still (0,0,0,0).
       - After SIGCONT the gateway commits and fails only to answer (`session_failed`,
         `TransportUncertain`); the journal is (1,1,1,0).
       - SIGTERM exits 0. A new gateway process opens the same vault and pair root.
       - Retrying the same act with *different* bytes queries only. The new gateway logs one
         served session, the committed receipt is adopted (201), GET lists `stored_unbound`,
         and the journal stays (1,1,1,0): the re-entered bytes were never ingested.
  - After each real-UDS test, a sweep of the whole tree, including gateway stderr, finds
    neither secret nor its sha256.
- **Mutation checks** (temporary, reverted):
  - Raising from the signal handler, the old worker pattern, fails all four real-UDS tests.
  - Removing the pair-root check fails the wrong-endpoint test.

`app/tests/support/credential_app_child.py` gains two things. With an `attachment` path it
reads the attachment from that file instead of building one. The `mark`/`wait_for` steps
let the parent act between two requests of one control-plane process. Nothing else changed.

`app/tests/test_backup.py` gains two tests:

- `test_the_credential_command_ledger_is_stated_and_never_carried` (runs without age). It
  creates a real ledger beside the vault and checks that the category is present, that the
  snapshot has none of the ledger tables, and that each ledger table name is refused by
  `classify_table`.
- `test_a_backup_beside_a_credential_command_ledger_restores_without_it` needs
  `DEEPTWIN_AGE_RUNTIME_ROOT`, the locked age 1.3.2 build. It **skipped here**: the
  container's `/usr/bin/age` does not match the locked digests.

```text
env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q -p no:cacheprovider \
  app/tests/test_credential_{custody,gateway_main,gateway_peercred,gateway_persistence,gateway_service,gateway_startup,import_boundary,ingress,root,routes,routes_v2,vault}.py \
  app/tests/test_provider_gateway_channel.py app/tests/test_provider_gateway_owned.py \
  app/tests/test_server.py app/tests/test_server_api_v1.py app/tests/test_server_session_integration.py \
  app/tests/test_provider_transport.py app/tests/test_web_owner_integration.py \
  app/tests/test_first_party.py app/tests/test_first_party_dependencies.py app/tests/test_backup.py
459 passed, 12 skipped (the age-gated backup tests), 1 known starlette warning
  (437 passed / 11 skipped on the base commit; +21 gateway-entrypoint tests, +1 backup
  ledger test, +1 age-gated backup test skipped here)
app/tests/test_{works_api,runs_api,provider_source_startup,router_composition}.py
107 passed
deploy/tests (no Docker)
449 passed, 369 subtests passed
ruff check (new/changed files other than test_backup.py): All checks passed
(test_backup.py keeps one pre-existing I001 at its deleted-original test)
```

Frozen identities (SHA-256; this block supersedes earlier blocks for these paths):

```text
5e0567d63cf5ae078a5ba2957ad434b8112b91dd320ab2ab343e556be3c14214  app/workers/credential_attachment.py
29e3e5c0f63f10d2bdda069435249aaea3b115a4aaad02d38bb8d51f501c4c9f  app/workers/credential_gateway_main.py
226d5958ac94ddd4fb88b31194cf2892d6bdf220c8139444fd2b175079531760  app/api/credential_wiring.py
dce0feb8fa5ae985df7749777c31439a47f29a2b7909c53b5b04d46916b3756b  app/operations/backup.py
ec75d43a10d3b1b351b67eb693c5b3493b16e7e3f3997225ddd5cea8a7b6abdf  app/tests/test_credential_gateway_main.py
77f7def9f1398c884d9c1abfda546bc5fb05e88de1de426e68af36114d07c4fe  app/tests/support/credential_gateway_launcher.py
5262d00f088e312177ce2c76b2c17c95fc51e068b64e81056ea0022be10675cc  app/tests/support/credential_app_child.py
e9b68b5948400132a2a5f4d5feaed709251ba7055c20e7aaa1cbc220a36af8dc  app/tests/test_backup.py
6a18faa38379724a18466f39b42f66c4405fe11eb790b8e9c21addd39cbd152e  deploy/compose.yaml (unchanged)
```

### Still not claimed

- **Compose and image.** Nothing in `deploy/compose.yaml` runs the entrypoint yet (see
  above). No image packages it, and no deployment step performs vault genesis or delivers
  the shared attachment object to both services. The real-UDS runs used synthetic numeric
  identities as root in this development container, not the candidate service images.
- **Control-plane restart.** The restart test restarts the gateway only. The pending act
  lives in one control-plane process; recovery after a control-plane restart relies on the
  ledger's persisted pending state, which the routes tests cover in-process, not with a
  second `create_app` process.
- **Age-gated backup test.** It did not run here.
- **Items carried over.**
  - binding CAS;
  - catalog invalidation on rotate;
  - the unknown-command fence;
  - `unbound_orphan` cleanup;
  - the API contract's handle wording;
  - erasure/`erasure_completed`;
  - the T087 manifest/budget binding and send-engine composition in the gateway process.
- **Audit and regression.** No independent audit of this slice has run, and the full shared
  regression was not re-run.

## 2026-09-25 — binding CAS, catalog/model invalidation, `unbound_orphan`, the unknown-command fence, handle wording

This slice takes the control-plane items carried over above: binding CAS, catalog/model
invalidation on rotate, `unbound_orphan` cleanup, the unknown-command fence and the API
contract's handle wording. The gateway, vault, journal schema and channel are unchanged; every
change is in the control plane (`app/api/credential_commands.py`, `app/api/credential_routes.py`,
`credentials-v1.json`) and `contracts/api.md`.

### Provider connection binding by compare-and-swap

- The command ledger gains a `connections` table: one binding head per provider
  `{revision, state: bound|revoked_pending_erasure, record: {record_id, record_version,
  ciphertext_sha256}, command_id}`. The custody receipt is still never binding authority
  (custody contract): the store receipt is persisted first (`adopt_store_receipt`), and a
  **second ledger transaction** (`bind`) applies the binding by CAS, as api.md orders.
- Allocation records the connection's binding revision (`binding_expected`) with the act.
  - A create is refused `409 connection_bound` before any gateway call when the provider is
    already bound (replacing a key is a rotation). Its CAS succeeds only if the revision is
    unchanged and the head is not `bound`.
  - A rotation may target only the provider's currently bound record. Its CAS requires the
    recorded revision **and** the exact predecessor reference in the head. A new rotation's
    version is one past every version ever allocated to the record (receipted or not), so a
    fenced version is never reused.
  - A delete, in its allocation transaction, first CAS-revokes a head bound to that record to
    `revoked_pending_erasure` (revision + 1) and only then retires the record `owner_delete`. A
    lost retire reply therefore leaves the binding already revoked. A new create may bind the
    provider again afterwards.
- `bind` is idempotent per act. A crash after the receipt but before the binding transaction
  is completed by retrying the same act, locally, with no gateway call.
- A lost CAS makes the stored record a valid orphan: the act ends `orphaned`
  (`409 connection_conflict`, not retryable), the record is marked orphan (never bound, never
  the handle's current version), and an `unbound_orphan` retirement is allocated durably and sent
  (same-command replay on ambiguity). A rotation that loses its CAS leaves the predecessor bound
  and unretired (its `superseded` retirement is cancelled).

### Catalog and model authority keyed by binding revision

- `catalogs` and `model_choices` are keyed by `(provider, binding_revision)`. The rotation CAS and
  the delete revoke set every current row of that provider to `invalidated` **in the same
  transaction** as the head change.
- `record_catalog_refresh(provider, refresh_command, expected_binding_revision, models)` is the
  only writer of a catalog snapshot. It requires the head to be `bound` at exactly that revision,
  so a refresh answered for a predecessor cannot land after a rotation. It is idempotent per
  refresh command. `choose_model` accepts only a model the current revision's catalog lists.
- No create/rotate/delete/fence path calls either, and `CredentialActs` has no provider seam at
  all: its client exposes only `store_at`/`query_record`/`retire`.

### Unknown-command fence

The custody contract defines no gateway cancel/fence operation ("a future cancel/fence protocol
is a separate operation"), so this is the bounded, owner-visible control-plane resolution:

- The status read lists each unfinished act with `fence_available_at` (the send time plus
  `fence_after_seconds`, default 300 s).
- `POST /api/v1/credentials/fences {"intent_id"}` (the stuck act's intent; route
  `credentials.fence`, `work.command`, CSRF) is refused before that time
  (`409 fence_not_due`, retryable, no gateway call). After it, one fresh `query_record`:
  - `unknown` → the act becomes terminal `fenced`, `{"state": "fenced", "uncertain_record":
    "unknown", "provider_revocation": "not_performed"}`;
  - `pending` → refused `503 command_pending` (the gateway journaled it; its recovery settles
    it);
  - `secret_input_lost` → terminal as before;
  - committed → the record is adopted only as an orphan and retired `unbound_orphan`
    (`uncertain_record: "cleanup_pending"`); the owner's abandoned act never binds it;
  - gateway unreachable → `503 dependency_unavailable`, the act stays `sent`.
- A fenced act never re-sends its secret (`409 fenced` for any replay), never binds, releases
  the handle for new rotate/delete acts, and a rotation's predecessor stays bound.
- A delayed accepted store can still commit after the fence (custody contract: `unknown` is
  nonterminal). Every later owner act first reconciles open fences (bounded to 16, query only)
  and retires such a late record `unbound_orphan`. The fence neutralizes a late commit; it does
  not prevent it at the gateway. A delete act is not fenceable (it carries no secret; its
  recovery is same-command replay).

### Status read and handle wording

- `GET /api/v1/credentials` now returns `{credentials, connections, pending_acts}`, all from the
  committed ledger (zero gateway/vault/provider effect, re-pinned). Credential entries are
  unchanged. A seam that returns a bare list still yields `{credentials}` only.
- `contracts/api.md` now states the handle decision: "handles" in "creation responses return …
  not … handles" means the gateway's opaque resolution handle and anything secret-derived. The
  browser-facing `handle` of the credential-v2 routes is the record id in 32-hex form: a stable
  nonsecret address across rotations, used by `rotate_from` and `DELETE …/{handle}`, derived from
  no key byte, never resolving a secret and conferring no dispatch or binding authority. api.md
  also records the binding CAS, the revision-keyed catalog/model authority, the fence route and
  its limit, and the new GET shape.
- Ledger migration: an existing ledger gains the new tables and columns on open
  (`sent_at`, `binding_expected`, `bind_state`, `records.orphan`). Acts that were settled before
  this slice have no binding head; no deployed ledger exists.

### Tests

`app/tests/test_credential_binding.py` (13, new) runs on the `test_credential_routes_v2` harness:
the real development app → ledger → frame-only client → real authenticated broker frames on
socket pairs → `CredentialGatewayService` → encrypted vault, with a fake ledger clock for the
fence delay. The teardown sweep finds no secret in logs, the ledger or any file.

- **CAS lifecycle.** create binds revision 1; a second create is `409 connection_bound` with zero
  gateway calls; another provider has its own head. Rotate moves the head to revision 2 on
  version 2. A delete whose retire reply is lost is `503 command_pending`, but the head is
  already `revoked_pending_erasure` (revision 3) and listed in `pending_acts`. The same act then
  settles, and a new create binds revision 4.
- **Create race.** A second create is allocated and completed while the first create's store is
  in flight. The second wins the CAS. The first gets `409 connection_conflict`, and its stored
  record is retired `unbound_orphan` (vault retirements `[(1, "unbound_orphan")]`). A replay of
  the losing act sends nothing and retires nothing twice.
- **Rotation race.** The binding revision advances between the successor's store and its CAS.
  The successor becomes the orphan, and the predecessor stays bound and unretired. The next
  rotation allocates version 3 (past the orphan) and binds.
- **Crash between receipt and binding.** A retry of the same act completes the binding with no
  gateway call.
- **Catalog/model authority.** A refresh result + model choice at revision 1 is `current`. The
  rotation voids both (rows `invalidated`, GET `absent`). A refresh for revision 1 is refused;
  an explicit refresh for revision 2 creates the catalog (idempotent replay); an unlisted model
  is refused; delete voids the authority again.
- **No implicit effect.** With `record_catalog_refresh`, `choose_model`,
  `HTTP(S)Connection.connect`, `socket.create_connection` and `getaddrinfo` patched to fail,
  create → rotate → unknown rotate → fence → delete all succeed. Only
  `store_at`/`query_record`/`retire` cross the channel, and the catalog and model tables stay
  empty.
- **Fence of an unknown rotation.** The store fails ambiguously before reaching the gateway, so
  the command stays `unknown`. It blocks delete. A same-act retry only queries. An early fence is
  `409 fence_not_due` with no gateway call. After the delay: one query, then `fenced`
  (idempotent). A replay with a new secret is `409 fenced` (only the reconciliation query crosses
  the channel). The delayed store is then delivered and commits at the gateway. The next owner
  act reconciles it as `unbound_orphan`, rotates to version 3 and binds it. Version 2 was never
  bound.
- **Fence finding a commit.** The store and query replies are both lost. The fence's query finds
  the command committed, the fence retires it `unbound_orphan`, and the predecessor stays bound.
- **Fenced create.** The pending entry leaves `credentials`, appears as `fenced` in
  `pending_acts`, and a new create binds the provider.
- **Refusals.** Unknown intent 404; a settled act 409; `pending` → 503 `command_pending`;
  unreachable gateway → 503 with the act still `sent`; delete acts not fenceable; malformed body
  400; missing CSRF 403.
- **Zero-effect status read** with binding state: with every client operation patched to fail,
  the vault tree stays byte-identical.
- **Migration.** A first-layout ledger gains the new columns on open.

Changed existing tests:

- The real-UDS `test_credential_gateway_startup`/`test_credential_gateway_main` pin the new GET
  body (binding head revisions 1 → 2 → `revoked_pending_erasure` 3). They ran here as root.
- `test_credential_routes_v2`'s immediate-recovery create now uses `codex`, because `claude` is
  bound at that point.
- Route counts: 104 → 105 installed (`credentials.fence`) in `test_first_party`,
  `test_web_owner_integration`, `test_works_api`, `test_runs_api` and
  `test_provider_source_startup`.

Mutation checks (temporary, reverted):

- Forcing every CAS to win fails the create-race and rotation-race tests.
- Fencing without the fresh query, together with dropping the invalidation, fails the
  catalog test and three fence tests.

```text
env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q -p no:cacheprovider \
  app/tests/test_credential_binding.py app/tests/test_credential_routes_v2.py app/tests/test_credential_routes.py
34 passed   (3 serial repeats)
... app/tests/test_credential_*.py test_first_party.py test_web_owner_integration.py test_server*.py
    test_works_api.py test_runs_api.py test_provider_source_startup.py test_backup.py
    test_first_party_dependencies.py test_router_composition.py
524 passed, 12 skipped (the age-gated backup tests; the real-UDS tests ran as root)
... app/tests/test_provider_*.py
2394 passed, 1 skipped, 2 failed: test_provider_gateway_owned::test_the_state_claim_order_is_the_wire_order
  (also fails 3/3 on the unmodified base tree here, timing-dependent) and
  test_provider_service::test_changed_generation_during_dialogue_closes_owned_service (passed on
  an immediate rerun). Neither module imports the changed code.
node --test app/tests/account-credentials.test.mjs: 9 pass (account.mjs unchanged)
ruff check (changed Python files): All checks passed
```

No `test_claude_connection*.py` file exists in this tree.

Frozen identities (SHA-256; this block supersedes earlier blocks for these paths):

```text
67f8eced99b8961d908f8ad7a2c8e530f3f1d6922a6d47a179dfee199fc3c597  app/api/credential_commands.py
336e6b2630f19333be88e243a1141618a06e94a6c483799d8e542474a7e4e483  app/api/credential_routes.py
db50118d6c75c18f3c693eb999da24f41e74f9bc105236feba72c74c204d5872  app/api/route_contributions/credentials-v1.json
1fe674fd42ab59c7c295884c8ab2155ea85e849ec6648c7a74f5d45f7b8d7383  app/tests/test_credential_binding.py
5a464125ed2a0fc9d606247034f50d832741729fdc2fa18ed4fbc88ae1b5ee80  app/tests/test_credential_routes_v2.py
0f586805b0bd2679fa6710f715b7c7bc8a15c49358a8f3d7285e5fe1ec17fae6  app/tests/test_credential_gateway_startup.py
93a2526d8ae0e79c1cbc95a290a2504637bfa29d2acee8c49a5f482168a6ad6c  app/tests/test_credential_gateway_main.py
d311225230c70a746ca3b898de6742c597d2ab490a4a811c353b9990f5363ecb  app/tests/test_first_party.py
3ae7e86abf470cf3901bb7d25f58cccd60026625c722b7129bd68406f474f9cf  app/tests/test_web_owner_integration.py
a2d1cbbddf806ccbbf6d397b52a37bab527d971c68fdf7080d3ecdab61a438c9  app/tests/test_works_api.py
88f3dd147a01ead471de21d433f25ce6820a0844d1b0718d659417285902273f  app/tests/test_runs_api.py
82df699fc9c7aaf8156af4e09caae8188a690af144cba455ca18c1c6640b7cbc  app/tests/test_provider_source_startup.py
```

### Still not claimed

- **Binding consumers.** The binding head is control-plane authority only. The gateway's send
  path (`delivery_for_exchange` under a lease) does not yet read it, and no `refresh_catalog`
  route or provider list-models call through the gateway exists. Only the ledger API writes a
  catalog. The direct-adapter `ClaudeConnection`/`model_selection` catalog is a separate,
  unchanged authority.
- **Gateway-side fence.** No gateway operation refuses a fenced command, so a late commit is
  neutralized (never bound, retired `unbound_orphan` on a later owner act), not prevented.
  Reconciliation runs only on owner acts; a gateway that never answers leaves the fence at
  `unknown`.
- **Owner UI.** `account.mjs` is unchanged: it neither shows `connections`/`pending_acts` nor
  offers the fence button, and its `stored_unbound` label ("not yet used for model connection")
  predates binding. The UI work belongs with the T023 screens.
- **T087.** The provider-transport manifest and budget binding of the send, plus send-engine
  composition in the gateway process, were not attempted in this slice.
- **Other carried items.** Compose/image wiring, vault genesis in deployment,
  erasure/`erasure_completed`, and a second-`create_app` control-plane restart test.
- **Audit and regression.** No independent audit of this slice, and the full shared regression
  was not re-run (only the families listed above).

## 2026-09-25 — credentials panel: binding heads, pending acts and the owner fence

This slice takes the "Owner UI" item carried over above. Only the browser side changed:
`createCredentialsPanel` in `app/static/account.mjs`, which is mounted on the records page. The
routes, ledger, gateway and vault are unchanged, and the production fence delay is still
`FENCE_AFTER_SECONDS` (300 s).

### Panel

- **Credentials.** The list still shows only provider · handle · custody state. The old
  `stored_unbound` label "아직 모델 연결에 쓰이지 않음" predated binding and is gone. The label
  is now "보관됨 (게이트웨이에 암호화 저장)". A row whose handle is its provider's bound record
  also says "이 제공자 연결에 쓰이는 키 (바인딩 수정본 N)".
- **Provider connections (read-only).** Each binding head shows its provider, its state
  (`bound` 연결됨 / `revoked_pending_erasure` 연결 해제됨), its handle and its binding revision.
  For a bound head it also says whether a catalog snapshot and a model choice are `current` for
  that revision ("있음/없음"). The panel states that a rotation or delete voids the previous
  revision's catalog/model choice, that a new catalog exists only after an explicit refresh, and
  that this screen neither refreshes a catalog nor calls a model. No button is offered on a head.
- **Pending acts.** Each act shows its kind, provider, handle and intent. A `command_pending` act
  reads "결과 미확인 (… pending/unknown)", because the ledger does not tell `pending` from `unknown`
  and the page does not guess. A store act also shows "차단 가능 시각: <UTC>" from
  `fence_available_at`. A delete or retirement act (`fence_available_at: null`) is labelled "not a
  fence target" and gets no button. A `fenced` act shows what is known of its record:
  - `unknown`: a late commit would be retired `unbound_orphan`;
  - `secret_input_lost`;
  - `retirement_pending` or `cleanup_pending`: the late commit is retired `unbound_orphan`.
- **Fence.** The "이 요청 차단" button appears only once the page clock has reached
  `fence_available_at`. A timer re-renders the rows the page already holds at that moment, with
  no request. The server still decides, and an early POST is refused `409 fence_not_due`. The
  button POSTs `/api/v1/credentials/fences` with exactly `{"intent_id"}` and the CSRF header,
  then re-reads the ledger. Each result has its own status line and `data-state`:
  - `fenced`: the record is still unknown;
  - `orphan_retired` (`cleanup_pending`) or `orphan_retiring` (`retirement_pending`); both say
    the provider key is not revoked;
  - `secret_input_lost`, whether it arrives as a 200 receipt or a 409;
  - `still_pending` (`503 command_pending`: the gateway journaled the command);
  - `fence_not_due`.

  A fence that ends the page's own unconfirmed store also ends its "결과 다시 확인" retry mode, so
  the next submit is a new intent. A replay of a fenced act (`409 fenced`) does the same.
- **Refusals.** `connection_bound` shows "이 제공자에는 이미 연결된 키가 있습니다. 새 키로 바꾸려면
  교체를 사용하세요." `connection_conflict` shows "저장하는 동안 제공자 연결이 바뀌었습니다. 이번
  키는 연결하지 않고 정리합니다." These are the routes' own texts. Both start the next submit
  over.
- **Status read validation.** A malformed binding head or pending act (unknown state, revision
  < 1, a stamp that is not the ledger's microsecond UTC form, an unknown `uncertain_record`) is
  refused as unavailable, and nothing is listed. A bare-list status (no `connections` /
  `pending_acts`) still renders.
- **Unchanged.** The secret field is cleared synchronously before the request leaves and is never
  written to the DOM or storage. Delete confirms first and says `provider_revocation:
  not_performed`. A "상태 다시 읽기" button re-reads the ledger-only GET.

### Tests

`app/tests/account-credentials.test.mjs` grows from 9 to 20 tests. The new tests cover:

- binding heads, read-only, with revision and catalog/model presence, the voiding notice and the
  gone stale label;
- the fence button only once due, via an injected clock and timer, with zero requests from the
  re-render, and none for a delete act;
- all six fence outcomes, with the exact POST (path, CSRF, `{"intent_id"}` body) followed by one
  GET;
- a fence of the page's own unconfirmed store ending its retry mode;
- the exact `connection_bound` and `connection_conflict` messages, with the secret cleared and
  absent;
- malformed heads and acts refused.

`app/tests/browser-credentials.test.mjs` (1, new) runs a real Chrome against the real supported
`create_app` served by `app/tests/fixtures/credentials_server.py`. The stack is the
`credentials-v1` routes, the real ledger, the real frame-only client, authenticated broker
frames on socket pairs, `CredentialGatewayService` and an encrypted `CredentialVault`.

Test-only substitutions in the fixture:

- `open_credential_attachment` returns that in-process gateway instead of the verified
  `cp-provider` pair root;
- the ledger's fence delay is `--fence-delay-seconds 3`;
- two synthetic secret prefixes script the gateway:
  - `sk-fixture-noreply-…` is committed, but the store reply and the recovery query reply are
    dropped (a gateway that commits without replying);
  - `sk-fixture-unadmitted-…` fails ambiguously before admission, so every query answers
    `unknown`;
- `POST /__test__/catalog`, a wrapper route in front of the app and not a product route, records
  a catalog refresh result and a model choice through the ledger's own API. It stands in for the
  `refresh_catalog` act, which does not exist yet.

The browser case, as the owner through the records page:

1. **Create.** The key is bound at revision 1 with no catalog. After the test route, the catalog
   and model choice read `current`.
2. **Second create.** It is refused with the exact `connection_bound` text.
3. **No-reply rotation.** The panel shows `command_pending`, the act with its fence time and no
   button, and revision 1 with its catalog intact. A direct early POST is `409 fence_not_due`.
   The button then appears by itself. The fence finds the commit and retires it `unbound_orphan`
   (`orphan_retired`/`orphan_retiring`; the test accepts either, because the orphan's retirement
   may finish inside the fence or on a later act). The retry mode ends, and the binding stays at
   revision 1 with its catalog.
4. **Unadmitted rotation.** After the delay the fence answers `fenced` with the record `unknown`,
   and the act is listed as fenced.
5. **Real rotation.** The binding moves to revision 2, and the catalog and model choice read
   `absent`.
6. **Delete.** The confirmation says the provider key is not revoked. The binding reads
   `revoked_pending_erasure` at revision 3.
7. **Sweep.** No synthetic secret appears in the DOM, in any input value, in local or session
   storage, in any response body the page received, in the fixture's output, or in any file the
   fixture owned (checked after shutdown).

Mutation check (temporary, reverted): offering the fence button regardless of
`fence_available_at` fails the node due-time test and the browser case.

```text
node --test app/tests/account-credentials.test.mjs                        20 pass
CONTROL_PYTHON=… CONTROL_PLAYWRIGHT_MODULE=… node --test app/tests/browser-credentials.test.mjs
                                                                           1 pass (3 serial runs)
… --test-concurrency=1 browser-credentials browser-records browser-retention browser-backup
    6 pass, 0 fail, 5 skipped (the backup/retention cases need Linux+root+DEEPTWIN_AGE_RUNTIME_ROOT,
    not set here; unchanged skips)
node --test app/tests/[!b]*.test.mjs app/tests/b[!r]*.test.mjs (every non-browser node test)
    269 pass, 0 fail
env -u DEEPTWIN_LIVE_ANTHROPIC_API_KEY .venv/bin/python -m pytest -q -p no:cacheprovider \
  app/tests/test_credential_*.py test_web_shell_assets.py test_extension_architecture.py test_browser_worker.py
    284 passed (includes test_credential_binding 13 and test_credential_routes_v2)
ruff check app/tests/fixtures/credentials_server.py: All checks passed
```

Frozen identities (SHA-256; this block supersedes earlier blocks for these paths):

```text
229f4712f545a900ba3bfc9c228423fdc8b7f5c286e466ed095f73f87e6e6bd0  app/static/account.mjs
3942723f8620ec7836afd6d071885a827e3c0c7c715e388a7a0ddc900a2d76fe  app/tests/account-credentials.test.mjs
64151c3450bf7089655793387067e0a94f15dc55e47f44b34eca227f09e486a4  app/tests/browser-credentials.test.mjs
1c343a27e3dc116abedcf8d1f83981c0f4627339245bfe230f6bde16416bac15  app/tests/fixtures/credentials_server.py
```

### Still not claimed

- **Catalog refresh.** There is still no `refresh_catalog` route or provider list-models call
  through the gateway. The browser case's catalog comes from a test-owned route over the ledger
  API, and the panel only reports presence.
- **`pending` versus `unknown`.** The status read reports `command_pending` for both, so the panel
  cannot distinguish them. Only the fence's own query does: `503 command_pending` means the
  gateway journaled the command.
- **Clock skew.** The fence button follows the browser clock. If that clock runs ahead of the
  server, the owner can see the button early and receive `fence_not_due`. The server stays
  authoritative.
- **Browser `connection_conflict`.** It is not produced in the browser case, because a CAS race
  needs two concurrent acts. It is covered by the node test (message) and by
  test_credential_binding (route).
- **Gateway transport.** The browser fixture's gateway is in-process over socket pairs, not the
  real UDS/SO_PEERCRED endpoint (that path stays covered by the root-only
  test_credential_gateway_startup/main).
- **Carried items.** Everything else carried above (gateway-side fence, binding consumers, T087,
  compose, erasure, audit and full regression) is unchanged.
