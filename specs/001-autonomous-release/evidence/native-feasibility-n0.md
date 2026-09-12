# Native isolation N0 — actual canary evidence

> **2026-09-08 superseded by ADR-009.** 아래 측정값은 보존된 macOS XPC/App Sandbox
> 개발 실험이다. 현재 웹 worker 경계나 공식 브라우저 제품 여정의 합격 증거가 아니다.

2026-09-07 · macOS26.5.1 arm64 · development canary, not a production boundary.

An Objective-C host application, embedded App Sandbox XPC service and inherited-sandbox
child probe were compiled with the installed Apple SDK, ad-hoc signed as newly generated
temporary artifacts, verified, launched and terminated. No existing application, signing
identity, Keychain item or OS security setting was changed. The probe used only synthetic
data and loopback sinks; it made no provider/browser/microphone call.

Observed command result: `packaging/macos/tests/test_native_boundary.py` **8 passed in
3.77s**. The generated report recorded distinct host/worker/child PIDs, both worker and child
reporting App Sandbox entitlement, and clean child/worker termination. Worker and child were
denied TCP/UDP client and server operations for IPv4 and IPv6 with errno1. The unsandboxed
host reached all four loopback sinks both before and after those probes; sink receipts contained
no worker/child marker. Both sandboxed generations could read/write their own temporary
container file but could neither read nor append the exact synthetic fixture under the host's
Application Support path; original bytes were unchanged.

Malformed, over-64KiB, stale-generation and unknown-action messages were rejected. The host
bound its positive XPC connection to the exact generated worker CDHash. A second canary with
an impossible service-side peer requirement rejected its host with XPC transport error4097.
These controls demonstrate actual tested OS denials and one direction of peer binding rather
than inferring isolation from plist text.

## Deliberately open boundary

`peer_auth_complete=false` is a required result. Inside the sandbox, the worker could not
derive a trusted host CDHash from the enclosing application, and PID-derived dynamic signing
lookup returned status100001. The worker therefore records that observation as unauthenticated;
the positive canary does not enforce worker-to-host identity. The impossible-requirement case
proves the connection API can reject, but does not establish a production trust bootstrap.
Stable Developer ID/designated requirements or another supported non-circular peer binding
must be qualified under real signing authority. PID, bundle identifier or an observational
CDHash must not be promoted to authority.

This is N0 only. It did not launch Chromium, broker HTTP responses, prove redirect/CORS/cookie/
compression fidelity, exercise renderer/network subprocesses, package the Python application,
or test signing/notarization/clean-user installation. Its XPC code is not connected to the
product dispatcher. Consequently T018 and the product browser boundary remain open even
though this bounded canary passed.

The retained temporary evidence directory was
`/var/folders/1t/dt7vw7rj5_361vj2g76qthtw0000gn/T/deeptwin-n0-w9qzvxpt`; it contains only
generated apps, request/results, sink receipts and the source manifest. The separate synthetic
Application Support fixture was removed after byte-preservation checks. Generated host/worker
PIDs no longer existed at test completion.
