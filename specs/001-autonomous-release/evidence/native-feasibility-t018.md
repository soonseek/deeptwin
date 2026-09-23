# T018 — fail-closed launcher and brokered browser feasibility

> **2026-09-08 superseded by ADR-009.** 이 문서는 현재 T018이 아니라, 같은 번호를 사용했던
> 이전 macOS 런처 실험의 역사적 증거다. 현재 T018은 자체 호스팅 웹 worker/broker 경계를
> 구현·검증하며 이 결과를 릴리스 합격으로 승계하지 않는다.

2026-09-08 · macOS 26.5.1 (25F80) arm64 · development evidence only.

This slice implements a production-shaped closed message schema and standalone launcher,
and exercises a real local Chromium-family browser capture. It does **not** accept the
product native/browser boundary. T017's real App Sandbox XPC worker and inheriting native
probe remain the only OS-enforced file/network-denial evidence; their feasibility sources
were not changed by T018.

## Implemented boundary

- `app/native/worker_bridge/protocol.py` accepts exactly one `capture` action using a
  64 KiB length-prefixed JSON frame. It requires request and generation IDs, a closed
  synthetic HTTPS origin, status 200, two explicitly allowed response-header names and
  at most 32 KiB of canonical base64 body bytes. Python rejects duplicate JSON object keys
  at every nesting level. Unknown fields/actions, duplicate/case-variant headers,
  stale-shaped IDs, host paths, commands, credentials and generic URLs are outside the schema.
- `app/native/worker_bridge/browser_capture.mjs` launches the caller-selected local browser
  with Chromium's internal sandbox enabled, registers interception before navigation,
  blocks service workers/download acceptance, fulfills only the exact synthetic fixture
  request, and aborts every other routed request. It has no `route.continue`, `route.fetch`,
  proxy, remote-debugging port, `--no-sandbox` or generic child-process action. Its raw JSON
  scanner rejects duplicate keys before importing Playwright or launching a browser; its
  schema/header/base64/field bounds match the Python decoder. Both sides loop until every
  IPC byte is read or written. The PNG is returned over the bounded pipe; the browser child
  receives no output filesystem path.
- `packaging/macos/launcher.py` requires caller-authorized SHA-256 values for Node, helper,
  Playwright entry module and browser executable before spawn, rejects symlink components,
  keeps their regular-file descriptors open and verifies pathname identity/hash before and
  after the run. It performs
  one exact-ID host fetch from a temporary loopback fixture with environment proxies disabled,
  passes only fetched bytes to the helper, and requires generation/request/reply schema,
  `unexpected_request_count=0`, the exact fresh launcher-generated DOM marker,
  `javascript=executed` and the PNG digest. It writes the PNG to a private 0600 stage opened
  relative to a retained output-directory descriptor. Only after the exact shutdown reply,
  zero helper exit, bounded stderr drain, owned-process termination and component-path
  recheck does it atomically hard-link the complete inode to a previously absent final name.
  Failures remove the private stage and never unlink an unrelated final file. Node starts in
  a fresh process group with `close_fds=True`; only that recorded group is terminated.
- Ordinary/product invocation reads the N0 result and fails before component validation or
  browser spawn when worker-to-host authentication, browser child App Sandbox inheritance
  or the complete browser boundary is absent. Even a caller-supplied report setting every
  field true cannot mint native attestation: this T018 launcher unconditionally keeps product
  browser launch disabled until a later signed integration replaces that canary gate. Current
  N0 has `peer_auth_complete=false`, so the standalone CLI exits 78 with `state=blocked`.
  `--development-canary` runs the bounded functional experiment but always returns
  `production_boundary_accepted=false`; this flag cannot mint qualifying evidence.

## Failure-first and regression results

The T018 tests were written before the launcher/helper. Initial command and result:

```text
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -m pytest packaging/macos/tests/test_native_boundary_t018.py -q
4 failed in 0.17s
```

All four failures were the expected missing `packaging/macos/launcher.py` boundary. After
implementation and adding standalone/static-policy regressions, the pre-audit focused result was:

```text
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -m pytest packaging/macos/tests/test_native_boundary_t018.py -q
7 passed in 2.60s
```

The fresh independent-audit requirements were then encoded before remediation. The expected
failure-first run was:

```text
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -m pytest packaging/macos/tests/test_native_boundary_t018.py -q
15 failed, 2 passed in 0.77s
```

Those failures covered missing explicit identities, duplicate-key acceptance, incomplete
writes/stderr draining, unvalidated receipts, symlink/TOCTOU canaries and early PNG publication.
After the audit patch, the focused result was:

```text
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -m pytest packaging/macos/tests/test_native_boundary_t018.py -q
32 passed in 28.29s
```

Final combined T017/T018 regression, run with `-s` to retain the N0 build-root observation:

```text
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python -m pytest packaging/macos/tests/test_native_boundary.py packaging/macos/tests/test_native_boundary_t018.py -q -s
40 passed in 31.79s
```

This reran the real ad-hoc-signed N0 XPC/App Sandbox bundle. Its generated build root was
`/var/folders/1t/dt7vw7rj5_361vj2g76qthtw0000gn/T/deeptwin-n0-yb0ld7yy`. As recorded in T017, the native worker and
native child were sandboxed, denied the controlled network/file operations, and terminated;
the reverse peer-auth boundary remained false.

## Standalone real-capture observation

The standalone CLI was invoked with explicit existing local paths (line wrapping added only
for readability):

```text
PYTHONDONTWRITEBYTECODE=1 <workspace>/.venv/bin/python \
  packaging/macos/launcher.py browser-canary \
  --node <node-runtime>/dependencies/node/bin/node \
  --node-sha256 27db838bb204ef7c21df2931f5656e4c8fb32e6e947f363a402b49714d32b5b1 \
  --playwright-module <node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
  --playwright-module-sha256 a0f5715ea22354f922791a9c53dc012d5d5c067ff9cc4cd35ffb7cd272071a9f \
  --browser '<playwright-browser-cache>/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing' \
  --browser-sha256 b1b9e2dd063115031f08eadc10ed381ca0fa05b2284baff8f721d87f5f0f61b7 \
  --helper-sha256 876bbfbdaf688895d183892c7f031b44defdfa48d020829a04dc30521167a197 \
  --n0-report /private/tmp/deeptwin-t018-audit.kddcxr/n0-open-report.json \
  --output /private/tmp/deeptwin-t018-audit.kddcxr/capture.png \
  --development-canary
```

Observed result was `passed_development_canary`, browser `149.0.7827.55`, exact DOM marker
and `data-js=executed`, one host-broker GET from `127.0.0.1`, one route fulfillment,
`unexpected_request_count=0`, and a real PNG SHA-256 of
`896f4f1867f2b3d86469868498d0bc9ef23b7c3af0706ecefdcee167fb755cce`.
The owned driver PID was 10263; descendants 10264, 10272, 10273, 10274, 10276 and 10277 were
observed while Chromium was alive, then all were absent after acknowledged shutdown.
The launcher recorded `component_identity_verified_after_run=true`,
`published_after_clean_shutdown=true`, and a fully drained empty stderr stream with the
SHA-256 of empty bytes.
The temporary directory contains only synthetic report/PNG data and is not a product install.

Exact inputs and final source hashes:

| Object | SHA-256 |
| --- | --- |
| local environment Node 24.19.0 | `27db838bb204ef7c21df2931f5656e4c8fb32e6e947f363a402b49714d32b5b1` |
| local Playwright `index.mjs` | `a0f5715ea22354f922791a9c53dc012d5d5c067ff9cc4cd35ffb7cd272071a9f` |
| local Chrome for Testing 149 executable | `b1b9e2dd063115031f08eadc10ed381ca0fa05b2284baff8f721d87f5f0f61b7` |
| `protocol.py` | `f1b7eb2e4076d5625326e2e9ed88f97860bdf412c581ac52cba3bd226fb9dda6` |
| `browser_capture.mjs` | `876bbfbdaf688895d183892c7f031b44defdfa48d020829a04dc30521167a197` |
| `launcher.py` | `a7595fe79ba8aec7daf19a2d7d0f25185a68da05e011b8ac78de9275b20c82b8` |
| `test_native_boundary_t018.py` | `b0b0301801cb2d5d3683e42db36ceed6d07bcf2e77c5ffd621e7f613fa401a81` |

## Unclosed gates and non-claims

- The browser used here is an existing local environment Chrome for Testing 149, not the
  selected unbranded Chromium snapshot 155/revision 1693281 in the component manifest.
  No download, copy into a product bundle, redistribution determination or manifest change
  was made. The local Node/Playwright/browser byte combination is evidence input, not a new
  release lock or supported-version matrix.
- The four expected hashes are supplied by the development-canary caller. They explicitly
  authorize the bytes observed at those paths for this run, but do not establish manifest,
  publisher or signature trust. Retained descriptors plus pre/post pathname identity/hash
  checks detect deterministic replacement and ordinary changes; because Node/import/Chromium
  still consume pathnames, they do not prove which bytes executed against an attacker able to
  swap and restore a path between checks. The result field therefore means only that authorized
  path identity was unchanged before/after, not executed-component attestation. Production
  remains unconditionally blocked rather than relying on this development-only mitigation.
- The real browser in this slice is launched by the host-side development canary, not by the
  signed App Sandbox XPC service. Route interception and defensive Chromium flags are not OS
  network enforcement. Therefore N1-01, N1-03 and SB-04 remain unqualified, even though the
  N0 native worker/probe network and host-file denials remain green.
- The worker still cannot authenticate the host with a stable supported code requirement
  under current ad-hoc signing. Closing that direction and signing the selected nested browser
  require appropriate stable signing authority and a new empirical run. No PID, bundle ID or
  observed CDHash has been promoted to authority.
- HTTP redirect/CORS/cookie/compression fidelity, DNS/Mach/Unix mediation, browser subprocess
  sandbox inheritance/signatures, Keychain separation, broker crash/restart, clean non-admin
  installation and other OS/browser revisions remain outside this slice.
- No Developer ID signature, notarization, publication, provider request, credential lookup,
  user secret, microphone/camera access, OS policy change or production peer authentication
  is claimed. T018 remains subject to independent audit and is not marked complete here.
