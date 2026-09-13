# Evidence — T043 (broker half): controlled egress fetch policy engine

- Date: 2026-09-13
- Task: T043 [US3] broker half — the controlled egress broker in
  app/runtime/egress.py with injected resolver/transport, enforcing
  destination grants, forbidden networks, DNS pinning, redirect
  revalidation and byte limits (runtime.md §5-6, R09, FR-014).

## Frozen identities

```
a182282424129cf1c02140df348f655143924e813b294cda22cb5f3ab4636580  app/runtime/egress.py
eae4c68a2722f89fcc3cae78063134e0b952852bd414959f2f31ebd131fd3ec8  app/tests/test_egress_broker.py
```

## What was built

- **Frozen policy** — `freeze_egress_policy(granted_hosts,
  product_origins, max_redirects, max_response_bytes)` issues an
  `EgressPolicy` (issued-value pattern; `dataclasses.replace` fails);
  hostnames are validated label-by-label, grants must be non-empty and
  unique, bounds 1..10 redirects and 1..64MiB body.
- **Typed brokered fetch** — `broker_fetch(policy, method, url, *,
  resolver, transport, headers)`:
  - HTTPS only; every other scheme (http/ws/wss/file/data/ftp/…) fails
    visibly as an unsupported route; port 443 only; GET/HEAD only;
  - no inherited credentials: URL userinfo refuses, and
    authorization/proxy-authorization/cookie headers refuse
    case-insensitively;
  - the hostname must be in the grant set, and the product's own origin
    is never reachable even when (mis)granted;
  - every resolution must be globally routable — `not is_global` refuses
    (private, loopback, link-local incl. cloud metadata
    169.254.169.254, multicast, reserved, unspecified, CGNAT and
    documentation ranges); one bad address poisons the whole set; empty
    or non-address resolutions refuse;
  - **DNS pinning**: the transport receives exactly the addresses the
    policy check resolved — the connection can never re-resolve;
  - **redirect revalidation**: every 301/302/303/307/308 hop re-runs the
    FULL policy with a fresh pinned resolution under the bounded hop
    count; a rebinding redirect (target resolving privately), an
    ungranted target and a missing Location all refuse;
  - the final body is byte-bounded; the result is an issued
    `FetchResult` (final_url, status, body, redirect_chain) with
    `is_issued_fetch_result`.
- Resolver and transport are injected; the module performs no live
  network activity (NO live/paid calls constraint holds).

## Verification (26 tests, TDD)

- RED: module absent (ModuleNotFoundError), then GREEN.
- Two authoring fixes: `dataclasses.replace` on an `init=False` issued
  value raises TypeError (not FrozenInstanceError), and the
  documentation/TEST-NET fixture addresses (203.0.113.7, 2001:db8::7)
  are themselves non-global — which validated the `is_global` check and
  moved the fixtures to genuinely public addresses.
- `ruff check` clean; the new tests pass under `-W error`; the suite's
  single warning is third-party (starlette DeprecationWarning).
- Full regression **3370 passed, 2 skipped** (was 3344).

## Notes

- T043 stays `[ ]`: the remaining scope is the sandboxed Chromium
  navigation/read/screenshot worker (app/adapters/browser.py) and the
  typed IPC — gated on the browser container/deps (Docker broken on this
  host) — plus wiring the broker into the runtime tool dispatch.
