# T025-A1 — offline bootstrap and OriginProfile checkpoint

Date: 2026-09-09  
Status: implemented and adversarially reviewed checkpoint; **T025 remains open**

## Exact scope

This checkpoint implements the common offline deployment helper and the transport-neutral
`OriginProfile`/capability-verifier boundary used before first-owner setup. It is an inspectable
`file://` deployment artifact, not a native launcher, an end-user CLI, a product work screen, or a
container-control surface. It performs no deployment effect and stores or transmits no user data.

The frozen scope is:

- `app/operations/setup.py`
- `deploy/bootstrap/index.html`
- `schemas/v1/origin-profile.schema.json`
- `schemas/v1/test-vectors/bootstrap-origin-profile-v1.json`
- `app/tests/test_bootstrap_delivery.py`
- `deploy/tests/bootstrap-helper.test.mjs`

## Closed properties

- Both local and portable profiles use lowercase 128-bit instance IDs. Local additionally uses a
  lowercase 128-bit random base path; portable is HTTPS on a dedicated hostname with `/` as its
  exact base path. Effective default ports are explicit in the profile while the normalized origin
  omits scheme-default ports.
- Canonicalization rejects userinfo, query, fragment, percent escapes, backslashes, duplicate/dot
  path segments, ambiguous ports, IP literals, noncanonical A-labels and hexadecimal-looking TLDs.
  Python and JavaScript share a pinned IDNA2008 PVALID-only table, an RFC 3492 encoder and RFC 5893
  bidirectional-label checks instead of delegating authority to runtime-specific URL/IDNA behavior.
- The profile digest is SHA-256 over the exact ADR-008 canonical JSON fields excluding the digest.
  Capability and verifier are canonical base64url without padding and decode to exactly 32 bytes;
  verifier comparison is constant-time at the Python boundary.
- The raw capability is displayed once and remains separate from the generated nonsecret
  Portainer/Compose configuration. It is not placed in a URL, config, storage, log or request.
  Editing any deployment input immediately clears both a completed result and an in-flight secret
  generation result.
- The helper has a restrictive offline CSP, imports no remote asset, performs no HTTP(S) request and
  remains keyboard-readable. It does not claim to create containers, TLS, volumes or an owner.

## Failure-first and independent review

The first Python and Node runs failed because the implementation/helper did not exist. Later RED
cases reproduced a Python/JavaScript split for crafted IDNA labels, Python acceptance of a hex-like
TLD and stale async secret output after form mutation. The implementation moved both runtimes to the
same pinned policy and generation-revision invalidation.

An independent adversarial pass then compared 847,292 raw U-labels, 301,684 malformed/canonical
A-labels and 960,545 RFC 3492 encodings. The final differential count was zero and no reproducible
P1 remained. A real `file://` Chrome 152.0.7977.77 smoke observed working CSP/WebCrypto, zero
HTTP(S) requests, zero runtime errors, stale-result removal and the expected
`BÜCHER.Example` canonical A-label. This development-browser result does not replace final
qualification on the T081-pinned Node/Playwright/Chromium image.

## Verification

```text
python -m pytest -q app/tests/test_bootstrap_delivery.py
14 passed

node --test deploy/tests/bootstrap-helper.test.mjs
8 passed

python -m pytest -q app/tests
2425 passed, 1 skipped, 1 dependency deprecation warning

python -m pytest -q deploy/tests
325 passed, 1 skipped, 369 subtests passed

ruff and git diff --check
PASS
```

The application and deploy totals include concurrent T018/T025/T087 work present in the shared
worktree on the recorded date; they are regression evidence, not completion evidence for those
tasks.

## Frozen content identities

```text
5483f8ecba8bc89d7e04712e8c49da9c753818027b95dd5c0a596b7bc47a5aed  app/operations/setup.py
64b36d5c642db0b57bde44351cd8d82306dc6b0d02c9c19291cc321e1d01d017  deploy/bootstrap/index.html
a9527db19a25c6b8c2fe6970f70c17b37ddf43add94d016f4ac0dd6f3a28965b  schemas/v1/origin-profile.schema.json
3ee3a2a0d186e515ec6d6c77fa2a518d7f854f2487b10c27668a13b01a3b80b0  schemas/v1/test-vectors/bootstrap-origin-profile-v1.json
1a8e9026d71665f97c5b924a06ab600aa980a98e952099ae161463a28c66ba25  app/tests/test_bootstrap_delivery.py
21cf4d4f23c960593d9ce7285b6b92e7895d12155023388e34478378767f45d4  deploy/tests/bootstrap-helper.test.mjs
```

## Explicitly open T025 work

T025 remains unchecked. This checkpoint does not implement or qualify OwnerAccount/Argon2,
bootstrap consumption, browser sessions, root generation/recovery, Host/Origin/CSRF enforcement,
service-client server composition, deployment requests/receipts, or the credential vault. The final
two deployment profiles, clean-host delivery and pinned-browser repetition also remain open.
