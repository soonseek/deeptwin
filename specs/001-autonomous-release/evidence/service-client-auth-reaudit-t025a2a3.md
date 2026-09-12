# T025-A2/A3 — independent re-audit of the six rejected service-client findings

Date: 2026-09-12
Verdict: **ACCEPT — all six 2026-09-09 REJECT findings no longer reproduce**; T025 remains open

## Scope and method

The 2026-09-09 independent audit of the service-client credential registry, bearer
boundary and first-party route composition rejected the slice with two P1, three P2 and
one P3 finding. The fixes landed in the same Codex sessions but ended without a recorded
re-audit. This session re-ran each original reproduction as an executable probe against
the snapshot state (commit `e2723b2`, files unchanged since), authored independently of
the fix author. Probes construct the real `PersistentServiceClientRegistry`,
`ServiceClientAuthenticator`/`IndependentTokenBuckets` and `FirstPartyRouteComposer`
against temporary stores; only `os.read` is wrapped in the RC-01 probe to make the
original race deterministic.

## Per-finding result

| ID | Original defect | Re-audit observation |
|---|---|---|
| SC-01 (P1) | Recovery advanced only active heads, so a manually revoked client made the post-recovery cold-restart startup audit raise `CorruptServiceClient` | `revoke_all_for_recovery` now advances revoked heads with `service_client.recovery_advanced` and counts only active heads in `revoked_count`. Probes: one pre-revoked head → receipt `revoked_count=1`, cold reopen succeeds, revoked credential still denied; all heads pre-revoked → `revoked_count=0`, cold reopen succeeds |
| SC-02 (P1) | Original Bearer visible in denial tracebacks (`raw_headers`, `parsed`, `_decode_bearer` locals) | Probe walks every frame of the raised denial including `__cause__`/`__context__` chains and scans `f_locals` of all product (`app/`) frames for the exact bearer. No hit for registry-failure, malformed-bearer or rate-limited denials with a fake registry, nor end-to-end against the real persistent registry for wrong-profile, scope-denied and unknown-client denials. The committed regression test walks the primary traceback; the probe additionally confirms suppressed context chains are clean |
| RC-01 (P2) | Same-inode, same-length descriptor content swap between pre-read stat and read was undetected | `_descriptor_bytes` now re-fstats after the exact-size read and compares dev/ino/size/mtime_ns/ctime_ns. Probe swaps equal-length content mid-read via a wrapped `os.read`; compose fails closed with `RouteCompositionError` |
| AUTH-01 (P2) | Rate precheck reserved nothing, so with capacity 1, 20 concurrent requests all reached `registry.authenticate()` | `reserve()` atomically holds source and route capacity before credential verification, with finalize/refund. Probe: capacity 1, 20 concurrent authorizations against a blocking registry → exactly 1 `authenticate` entry, 19 denied as rate-limited |
| RC-02 (P2) | Freeze was not atomic; two concurrent `compose()` calls could both succeed | `compose` runs under the composer lock. Probe: two barrier-synchronized threads → exactly one success, one `RouteCompositionError` |
| SCHEMA-01 (P3) | Exported schema accepted `["POST","GET"]` while the runtime enforced sorted order | The exported `methods` enum now enumerates only canonical sorted-unique lists; every enum entry verifies as sorted-unique, `["DELETE","GET"]` validates and `["GET","DELETE"]` is rejected by the schema itself |

All seven probes pass (SC-01 has two variants). Each closed defect also has a committed
regression test in the shared suites: recovery-epoch cold restart, traceback-locals
scrubbing, reserve-before-authenticate, rewrite-during-read, exactly-once freeze, and
exact schema/runtime method order.

## Verification

```text
python -m pytest -q app/tests/test_service_clients.py \
    app/tests/test_service_clients_persistent.py app/tests/test_service_client_auth.py \
    app/tests/test_service_client_routes.py app/tests/test_router_composition.py
93 passed

independent probe run: 7/7 PASS, plus the real-registry SC-02 end-to-end scan (3 denial
paths, zero product-frame leaks)

python -m pytest -q app/tests deploy/tests   (full shared regression, 2026-09-12)
2,922 passed, 2 skipped, 369 subtests passed
```

## Frozen content identities (SHA-256)

```text
8ba9394ee18464e9a1cd4c432381bf3b0e4850bc0f327fd1f7325d4bfe167866  app/services/service_clients.py
76545de05072d120096d052d82e84de469ffd4358f0873b4bd0d37868cd3a424  app/services/service_client_auth.py
97dd53c136d7bd4ebf290a0254bf79c4a09780fc06b180dacd126166c5e9d4f5  app/api/router_composition.py
b5ab4a5dec0e3224e48263d1f8566f907f0e3474d8dd0f804f65c4e7ccc25ee7  schemas/v1/first-party-route-contribution.schema.json
```

## Observations outside the six findings

A callee that legitimately receives the secret (the registry's own `authenticate` frame)
remains reachable through a denial's suppressed `__context__` if that callee raises
without clearing its locals; the persistent registry's denial paths showed no such
retention in the probes above, but any future alternate registry implementation must
preserve that property. This is an implementation obligation note, not a reopened
finding.

## Not claimed

This closes only the six rejected findings for the audited slice. T025's remaining arms
— first-owner bootstrap admission, sessions/CSRF wiring, route mounting into the live
server, deployment-authority integration and the gateway/vault work under T090 — stay
open, and no live-network or deployment-profile behavior was exercised.
