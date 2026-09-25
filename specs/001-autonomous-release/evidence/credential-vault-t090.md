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
