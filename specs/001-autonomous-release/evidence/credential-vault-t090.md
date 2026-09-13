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
