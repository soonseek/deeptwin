# T017 — native feasibility plan and read-only preflight

> **2026-09-08 superseded by ADR-009.** 보존된 macOS `.app`/XPC/App Sandbox 실험 계획이며
> 현재 자체 호스팅 웹 릴리스의 구현 지침·의존성·격리 또는 합격 증거가 아니다.

2026-09-07 · macOS Apple Silicon · **PLAN ONLY: native experiments not run**.
This document defines the next small empirical gate before full GUI integration.
Only tool/SDK discovery and existing documentation/header inspection were performed.
No compiler build, signing, identity/account lookup, download, app launch, microphone,
camera, Keychain prompt, entitlement installation or macOS setting change occurred.

Authority: [sandbox research](../sandbox-research.md),
[packaging research](../packaging-research.md),
[runtime tool boundary](../contracts/runtime.md#6-framework-tool-suite-and-permission-model).
These recommended canary decisions are delegated engineering choices, not user
approval of an operating environment. They do not relax the selected product boundary.

## 1. Observed preflight

| Read-only command/check | Actual result | Limit of evidence |
| --- | --- | --- |
| `xcode-select -p` | `/Library/Developer/CommandLineTools` | Full Xcode GUI is not required by this proposed native Objective-C canary |
| `xcrun --find clang` | `/Library/Developer/CommandLineTools/usr/bin/clang` | No source compiled |
| `xcrun clang --version` | Apple clang 21.0.0, `clang-2100.1.1.101`, target `arm64-apple-darwin25.5.0` | Tool present, not a successful bundle build |
| `xcrun --find swift` / `xcrun swift --version` | CLT Swift; driver 1.148.6, Apple Swift 6.3.3, `swiftlang-6.3.3.1.3`; target `arm64-apple-macosx26.0` | Swift is available but not needed for the smallest canary |
| `xcrun --show-sdk-path` | `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk` | SDK path exists |
| `xcrun --show-sdk-version` / `--show-sdk-build-version` | 26.5 / 25F70 | SDK version is not the tested OS version |
| `sw_vers` / `uname -m` | macOS 26.5.1, build 25F80, arm64 | No older OS or clean second machine qualified |
| Foundation, AppKit, Security frameworks; `xpc/xpc.h` | Present in that SDK | No runtime XPC launch proved |
| SDK `NSXPCConnection.h` | `setCodeSigningRequirement:` and listener `setConnectionCodeSigningRequirement:` available from macOS 13 | Use supported peer requirements, not PID-only or caller-supplied identity checks |
| `/usr/bin/codesign --version` | Unsupported option; printed usage, no target was supplied | Executable exists; no version/identity/signing success claimed |
| `/usr/bin/plutil -help` | Tool help available | No plist or system setting changed |

There is **no missing compiler/SDK blocker** in this preflight. Pinned Chromium
has not yet been downloaded/bundled for this release, and the native harness below
does not exist yet. Existing pywebview/PyObjC/py2app availability does not prove
the XPC/Chromium boundary or standalone dependency closure.

## 2. Smallest experiment and deliverables

Two increasing slices avoid making full py2app/WKWebView integration the first
test of OS enforcement:

1. **N0: native host + sandboxed XPC + inheriting native probe.** Build three
   small Objective-C executables using the installed SDK. The unsandboxed host
   owns controlled network sinks and dummy files. A real embedded XPC service,
   launched through `NSXPCConnection`, starts an inheriting child probe. Both
   service and child attempt explicitly named negative operations. This tests
   native launch, OS denial, actual child inheritance, typed replies and cleanup.
2. **N1: add pinned driver/Chromium within the same XPC boundary.** The worker
   runs the owned driver and Chromium with inherited restrictions and pipe-only
   control. Real HTTP(S) bytes fetched by the host feed `route.fulfill`; browser
   DOM/JavaScript/artifact evidence must match a fresh server-generated marker.
   A synthetic `page.set_content` screenshot is not this proof.

Proposed source files to implement next under `native/feasibility/`:
`Host.m`, `Worker.m`, `Probe.m`, `Protocol.h`, `Host-Info.plist`,
`Worker-Info.plist`, `Worker.entitlements.plist`, `Inherit.entitlements.plist`.
These paths are a plan, not existing files or commands already executed.
Tests/build tooling must be created through the normal reviewed editing workflow.

Proposed bundle:

```text
DeepTwinCanary.app/Contents/
  Info.plist
  MacOS/DeepTwinCanary
  XPCServices/DeepTwinWorker.xpc/Contents/
    Info.plist
    MacOS/DeepTwinWorker
    Helpers/DeepTwinProbe
    Resources/                    # N1 only: owned, pinned driver/browser closure
```

Use distinct canary-only bundle identifiers for host and worker, not production
IDs or an existing user's container. Host shows a minimal local progress/result
window and exits after its bounded suite; it is not a product UI prototype.
The worker is an application-scoped XPC service (`CFBundlePackageType=XPC!`,
matching executable/service identifier), not a LaunchAgent, daemon or privileged
helper. Do not install anything in `/Library` or register a global Mach service.

### Entitlements and trust contract

- Worker: `com.apple.security.app-sandbox=true`, with **no** network client/server,
  user-selected-file, Downloads, App Group, host Keychain group, camera or microphone
  entitlement. No temporary-exception blanket allowances.
- Inheriting probe/driver/browser: the documented App Sandbox `app-sandbox=true`
  and `inherit=true` combination. Inspect every actual nested Mach-O object;
  additional hardened-runtime/JIT requirements must be minimally justified and
  tested, never replaced by `--no-sandbox` or a broad exception set.
- Host: owns sinks, broker and test results; it must not send its general process
  environment, credentials, open database handles, connected sockets, directory
  handles or filesystem capabilities to the worker. Only named typed messages and
  deliberately owned anonymous control/log pipes cross the intended boundary.
- Apply supported connection/listener code-signing requirements before activation,
  in both directions. Bundle name, PID, UID and a nonce alone are not code identity.
  For the local ad-hoc experiment, derive the expected counterpart requirement
  from the inspected signed object at its fixed enclosing-bundle location; never
  accept a peer-supplied path, hash or requirement. Record the actual CDHashes and
  a rejected different-code peer test. Do not create a self-referential pair of
  embedded peer CDHashes. Production publisher/Team-ID trust remains a separate
  signed-build qualification, not established by this local fixture.
- A local ad-hoc signature may be used for the **later** N0 feasibility build and
  does not require looking up a user's signing identity. Whether this exact ad-hoc
  embedded service launches and enforces sandboxing is itself an open test.
  Failure does not authorize entitlement relaxation, security bypass or an
  unrequested Developer ID signing/credential operation.

## 3. Harness protocol, controls and evidence

Expose only fixed operations such as `hello`, `runNativeCase`,
`requestFixtureResource`, `publishArtifact` and `cancel`. Use a closed case enum,
NSSecureCoding class allowlists/NSData payloads and bounded validated structures.
Reject unknown keys, arbitrary path/command strings, arbitrary URL fetches and file
handles. N0's closed negative-test vectors may identify only host-created dummy
targets bound to that exact canary run/root and owned ephemeral listener ports;
this test-only input is not a product tool or a model-accessible filesystem API.
Proposed bounds: 64 KiB control message, 64 KiB artifact chunks, 8 MiB assembled
canary artifact, 32 requests/case, two in flight, five seconds/native operation,
30 seconds/browser case, 180 seconds/suite. These are test bounds, not product defaults.

Each request pins suite/run generation, unique request ID, exact case, payload
size/hash and expected peer. Replies bind the same IDs. Duplicates, wrong generation,
oversize data and late replies after cancel are not accepted as new successes.
Connection allocation is not `ready`: require an authenticated round-trip reply.
The host confirms result persistence before displaying the suite as finished.

For N0 the host creates live TCP/UDP sinks bound only to ephemeral loopback
addresses (`127.0.0.1`, `::1`) and a unique per-case marker. A trusted host positive
control must reach each sink before **and after** its worker negative attempt.
Observe native syscall results **and** sink receipt counts; an error string or
zero traffic without a working positive control is not evidence of denial.
An unavailable IPv6 fixture yields `invalid/not_tested`, not a pass.

Create dummy protected files under a unique host-owned Application Support test
directory, outside the worker container and outside TCC-protected user folders.
Use generated names and random fixture bytes, not an actual DB, API key, OAuth
file, Keychain item or user document. Worker receives permitted fixture **bytes**
and writes them within its own disposable staging; no arbitrary host directory is
granted. Record a protected canary's hash/expected denial, not its raw bytes in the
general evidence stream. Do not assume `/tmp` alone provides a privacy boundary.

### Required actual case matrix

| Case | Procedure | Passing observation; otherwise fail/unknown |
| --- | --- | --- |
| N0-01 launch/peer | Start embedded service through the native host; handshake with signed-object metadata; try a different-code fixture peer | Expected worker replies; wrong peer rejected; no privileged install or broad fallback |
| N0-02 TCP/UDP client | Service and inheriting child directly connect/send to controlled IPv4 and IPv6 sinks; route/driver interception is not involved | Worker marker receipts 0 with bracketing host positives; report errno/return/elapsed separately; timeout alone is inconclusive |
| N0-03 network server | Service and child try bind/listen/receive on ephemeral loopback ports; host attempts controlled connection/message where a port was acquired | No usable worker inbound service; preserve per-syscall results rather than assuming socket creation itself must fail |
| N0-04 scoped files | Positive own-staging read/write; outside-container dummy reads/writes, traversal, symlink and file-replacement races | Permitted bytes match hash; outside content acquisition/mutation 0; actual before/after host hashes unchanged |
| N0-05 capability inheritance | Probe enumerates inherited descriptors; try an unexpected NSFileHandle/descriptor message; inspect owned child process tree | Decoder rejects unexpected capability; only documented owned control/runtime descriptors; no host secret/DB/socket capability inherited |
| N0-06 lifecycle | Drop broker connection, kill only the recorded owned worker, malformed reply, stale generation, cancel then late result | No replacement unsandboxed process, no direct-network retry, no false completion; owned children terminate within the bounded deadline |
| N1-01 browser pipe | Start the pinned owned driver and Chromium from worker, internal sandbox enabled; inspect argv/process tree and listeners | Actual browser connects by pipes; no CDP/proxy TCP listener; every relevant child has recorded restriction/signature evidence |
| N1-02 real render | Host fetches a live fixture document and subresources; fulfill intercepted requests; execute page JS and return DOM/table/image plus PNG | Fresh server marker and expected DOM values visible; true browser PNG bytes/hash; fixture origin and exact broker request ledger agree |
| N1-03 browser direct bypass | Controlled pages attempt fetch/popup/iframe/worker/WS/WebRTC-like UDP paths; native probe remains a parallel escape canary | Unsupported paths are aborted/marked unsupported; forbidden sink receipts 0; no automatic fallback to worker network |
| N1-04 HTTP fidelity | Real same/cross-origin redirects, CORS allow/deny, two Set-Cookie headers, cookie scoping, compressed response and relative resources | Correct final page URL/origin/security behavior and body; every actual hop broker-validated; no silent metadata/body transformations |
| N1-05 restart/failure | Browser crash, malformed broker body, request overflow, interrupted artifact chunks, broker shutdown | Explicit terminal/missing state, incomplete PNG/file never sealed, no orphan browser or completed claim before valid artifact receipt |

N0 is an early native gate, **not all SB-01–07 complete**. DNS service/Mach/Unix
proxy mediation, externally routed destinations, DoH/QUIC/STUN and data-protection
versus legacy Keychain behavior need later controlled tests. Do not infer their
denial from loopback TCP/UDP failures. No actual metadata service, user's LAN or
public third-party system is a negative probing target. Required external sinks
must be separately owned/authorized; lack of one stays `not_tested`.

### N1 transport fixture versus production egress policy

Start with an explicitly named, **canary-only** adapter that maps a closed fixture
ID to the exact host-owned ephemeral listener. It must not turn production's
loopback/private-address denial into a configurable bypass. Record this adapter
as the evidence source; it cannot qualify general public HTTPS egress by itself.

Use real served bytes and a broker-only TLS trust context for a dedicated test
certificate if testing local HTTPS. No OS trust-store edits, TLS-error ignoring or
blanket browser certificate exceptions. Public HTTPS/TLS/connect-time DNS policy
remains an additional gate using approved controlled origins. A route fulfillment
success does not itself prove browser-side certificate/origin semantics.

Register interception before the first page, block service workers, keep
`chromium_sandbox=True`, avoid a user profile, and do not invoke `route.continue`,
worker-side `route.fetch`, direct APIRequestContext or remote-debugging HTTP.
For redirects, blindly following in the host and fulfilling final bytes at the
initial URL changes the browser's origin/URL: this is not a valid shortcut.
Test explicit hop-by-hop redirect behavior and whether the pinned Playwright
interception path re-enters for each required hop. If it cannot, report that
supported path as unqualified; do not allow direct sockets to make it work.
Likewise preserve duplicate cookies and compressed-body/header consistency.

## 4. Precise next commands — NOT EXECUTED

Developer/agent commands only; final users must never perform these steps.
They become runnable **after** the planned reviewed sources/plists exist. Do not
substitute generated unreviewed code or claim the following is an existing script.
Use a new temporary build root; do not write into an installed app or user container.

```sh
native_canary_root="$(mktemp -d /tmp/deeptwin-native-feasibility.XXXXXX)"
native_canary_sdk="$(xcrun --show-sdk-path)"
native_canary_app="$native_canary_root/DeepTwinCanary.app"
native_canary_xpc="$native_canary_app/Contents/XPCServices/DeepTwinWorker.xpc"
mkdir -p "$native_canary_app/Contents/MacOS" "$native_canary_xpc/Contents/MacOS" "$native_canary_xpc/Contents/Helpers" "$native_canary_root/results"
cp native/feasibility/Host-Info.plist "$native_canary_app/Contents/Info.plist"
cp native/feasibility/Worker-Info.plist "$native_canary_xpc/Contents/Info.plist"
plutil -lint "$native_canary_app/Contents/Info.plist" "$native_canary_xpc/Contents/Info.plist" native/feasibility/Worker.entitlements.plist native/feasibility/Inherit.entitlements.plist
xcrun clang -target arm64-apple-macos26.5.1 -isysroot "$native_canary_sdk" -fobjc-arc -fblocks -Wall -Wextra -Werror -framework Foundation -framework AppKit -framework Security native/feasibility/Host.m -o "$native_canary_app/Contents/MacOS/DeepTwinCanary"
xcrun clang -target arm64-apple-macos26.5.1 -isysroot "$native_canary_sdk" -fobjc-arc -fblocks -Wall -Wextra -Werror -framework Foundation -framework Security native/feasibility/Worker.m -o "$native_canary_xpc/Contents/MacOS/DeepTwinWorker"
xcrun clang -target arm64-apple-macos26.5.1 -isysroot "$native_canary_sdk" -fobjc-arc -fblocks -Wall -Wextra -Werror -framework Foundation -framework Security native/feasibility/Probe.m -o "$native_canary_xpc/Contents/Helpers/DeepTwinProbe"
codesign --force --sign - --options runtime --entitlements native/feasibility/Inherit.entitlements.plist "$native_canary_xpc/Contents/Helpers/DeepTwinProbe"
codesign --force --sign - --options runtime --entitlements native/feasibility/Worker.entitlements.plist "$native_canary_xpc"
codesign --force --sign - --options runtime "$native_canary_app"
codesign --verify --strict --verbose=2 "$native_canary_xpc/Contents/Helpers/DeepTwinProbe"
codesign --verify --strict --verbose=2 "$native_canary_xpc"
codesign --verify --strict --verbose=2 "$native_canary_app"
codesign -d --entitlements :- "$native_canary_xpc"
codesign -d --entitlements :- "$native_canary_xpc/Contents/Helpers/DeepTwinProbe"
open -W -n "$native_canary_app" --args --suite native --result-dir "$native_canary_root/results"
plutil -p "$native_canary_root/results/native-results.json"
```

These signing commands target only newly built local canary files and use `-`
for ad-hoc identity, not a user's certificate. They do not notarize or establish
Developer ID trust. Run each step with checked exit status; compilation, signature,
launch or handshake failure stops dependent steps. Never use `--deep` re-signing,
`sandbox-exec`, `--no-sandbox`, entitlement expansion, `spctl --master-disable`,
quarantine removal, TCC reset or arbitrary privileged shell as recovery.
An unexpected permission prompt stops the experiment for review.

N1 adds reviewed bundle inputs from the dependency manifest and an explicit
`--suite browser` selector, then repeats inside-out signing and N0 first. There
is intentionally no guessed browser executable path/download command here:
the pinned matching driver/browser receipt and all nested objects must be
resolved before producing that command. Do not use the user's installed Chrome
to stand in for the owned, inheriting release Chromium.

## 5. Report format, stopping conditions and remaining gates

The host must persist `native-results.json` with schema/version, suite ID, timestamps,
actual OS/SDK/arch, source and signed-object hashes, execution profile, peer requirements,
owned PID/generation tree, descriptor findings, case status, syscall result/errno,
positive-control and forbidden-sink counts, artifact hashes, cleanup confirmation and
explicit missing evidence. Detailed ledgers may be linked by hash. All data is synthetic.
Status is one of `passed|failed|invalid|not_tested|unsupported`; absence is never pass.
The `open -W` command's return code alone is not the application test verdict.

| Gate | Status at this planning step | What closes it |
| --- | --- | --- |
| Toolchain/SDK discovery | observed present | No native execution claimed |
| N0 real XPC/native enforcement | not_tested | Actual bundle launch and all valid N0 cases with positive controls |
| N1 owned Chromium/HTTP fidelity | not_tested; pinned browser input pending | Exact bundled revision/child signatures, real broker/DOM/artifact cases |
| DNS/Mach/Unix mediation and all relevant network escape routes | not_tested | Extended controlled SB-02/03 matrix, not inference from N0 |
| Host API secrets / legacy and data-protection Keychain | not_tested | Separate synthetic non-user-secret test procedure; no unrequested prompts or credential inspection |
| Standalone py2app/WKWebView dependency closure and actual microphone | not_tested | PK-01/02/04/05/11; native canary success does not replace them |
| Developer ID, notarization, clean non-admin install | not_tested; authority not inspected | Real authorized signing/publication inputs and PK-03/SB-06 results |
| Other OS/build/browser revisions | not_tested | SB-07 requalification; do not generalize current-host results |

Proceed to implement N0 once this test contract is accepted by the development
workflow. If an early invariant fails, keep the affected browser capability
disabled and record the failure while other independent work continues. If the
chosen boundary cannot support required browsing without relaxing its guarantees,
that is an architecture decision to revisit in whole-product context, not a reason
to label an unsandboxed browser successful. No current native pass or RC readiness
is asserted by this document.
