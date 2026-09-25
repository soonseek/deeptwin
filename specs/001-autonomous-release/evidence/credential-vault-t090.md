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
