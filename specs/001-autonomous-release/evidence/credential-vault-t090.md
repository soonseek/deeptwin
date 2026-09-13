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
