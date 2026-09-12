# Browser distribution evidence

> **읽는 순서:** 2026-09-07의 macOS/CfT 선택 논의는 ADR-009 이전 역사적 조사다. 현재 웹
> 릴리스 방향은 아래 `2026-09-08 ADR-010 Linux multi-architecture update`와 T089 manifest를
> 따르며, 어느 쪽도 아직 최종 배포 적격성을 뜻하지 않는다.

2026-09-07 · bounded T003/T018 research · release authorization **unresolved**

Recommendation: keep the presently installed Chrome for Testing (CfT) asset as a
development-canary candidate for controlled, trustworthy fixtures, outside the release
payload. For DeepTwin's independently installed browser worker, qualify a current,
revision-pinned **unbranded Chromium build without Widevine** and preserve the full browser
capability requirement. This is an engineering recommendation from the evidence below,
not legal clearance for a particular binary or a claim that a replacement works already.

## What the installed asset actually is

Read-only local inspection found Playwright **1.62.0**, browser revision **1234**, browser
version **151.0.7922.34**, and title **Chrome for Testing** in the installed wheel's
`playwright/driver/package/browsers.json`. Its SHA-256 is
`f306eed529599b1eaf2f8a85db9de2b23e1a3fe36c2b66434b7c9434fb627a99`, matching the earlier
[dependency-resolution record](dependency-resolution.md). This research did not download
or launch a browser.

The inspected installation root was
`/private/tmp/deeptwin-t003-build.EIO0ZY/browser-components/chromium-1234/chrome-mac-arm64/`.
Its `ABOUT` identifies Google Chrome, Google copyright and `chrome://terms`, separately
acknowledging Chromium and other open-source software. `ABOUT` SHA-256:
`34d078ce3003087a8374e7c6156fda374769b8047d6ddaf419d66414aa48edfb`.

Under `Google Chrome for Testing.app/Contents/Frameworks/Google Chrome for Testing
Framework.framework/Versions/151.0.7922.34/Libraries/WidevineCdm/`, `manifest.json` identifies
Widevine **4.10.3050.0**. Its `LICENSE` matches the material restrictions in the
[upstream Widevine license](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/third_party/widevine/LICENSE):
Google requires a separate license agreement for using, modifying, selling or distributing
the module, and identifies it as non-open-source. Local license SHA-256:
`20de375707692099b3132084695377ce5fec0aec05813dedcce094b8eda44386`.
No applicable separate agreement was supplied or inspected.

## Licenses and usage guidance are separate layers

| Layer | Primary evidence | Consequence for DeepTwin |
| --- | --- | --- |
| Playwright Python and bundled Playwright driver | Installed wheel metadata says `License-Expression: Apache-2.0`; its driver package LICENSE and [Python upstream LICENSE](https://github.com/microsoft/playwright-python/blob/main/LICENSE) agree. | Correct the premise: **Playwright is Apache-2.0, not MIT**. Its license does not grant rights to every separately downloaded browser/plugin. Preserve its own notices. |
| CfT availability repository | [Repository LICENSE](https://github.com/GoogleChromeLabs/chrome-for-testing/blob/main/LICENSE) is Apache-2.0; [README](https://github.com/GoogleChromeLabs/chrome-for-testing#support) distinguishes its dashboard/API code from browser binaries. | The repository license is not sufficient evidence that the entire downloaded Chrome application is Apache-2.0. |
| Downloaded Chrome executable | [Chrome additional terms](https://www.google.com/chrome/terms/) explicitly apply to executable code and distinguish open-source components. They incorporate [Google terms, software section](https://policies.google.com/terms#toc-software), which restrict distribution while recognizing applicable open-source terms. | Reviewed sources do not establish a CfT-specific grant for repackaging this whole bundle in an independent product. Applicable jurisdiction/agreement scope remains a review item; the web response showed the US English terms. |
| Widevine binary | Local license above; [Chromium build rules](https://github.com/chromium/chromium/blob/main/third_party/widevine/cdm/widevine.gni) explicitly bundle Widevine in branded Chrome/CfT. | A permissive framework license and public download URL do not resolve this separate proprietary component. Merely not calling DRM functions is not evidence of redistribution permission. |
| Chromium open-source code | [Chromium LICENSE](https://github.com/chromium/chromium/blob/main/LICENSE) permits source/binary redistribution subject to notice and non-endorsement conditions. | Provides an explicit basis for an open-source build, subject to **all included third-party components**, branding and build-specific notices. It does not relicense the inspected Chrome/Widevine bundle. |

Google's [CfT guidance](https://developer.chrome.com/docs/automation-and-testing/chrome-for-testing)
describes automation/testing, no automatic updates, and use with trustworthy content.
That is operational guidance, not by itself a conclusion that every non-test use violates a
license. It does mean that arbitrary third-party web content in DeepTwin's real worker is
outside the suitability established by this source. A successful local canary does not
establish safe runtime use or distribution rights. Testing DeepTwin's own controlled fixture
pages fits the documented scenario more closely; that does not create a standalone Widevine
license or permission to redistribute the bundle.

## Options that retain the browser worker

| Option | Assessment and next evidence |
| --- | --- |
| Current CfT 151 bundle | Development-canary candidate only for now. Keep release eligibility false. Obtain an applicable binary/component redistribution basis and resolve untrusted-content suitability before reconsidering it. Removing Widevine alone does not resolve Chrome's remaining terms or its usage guidance. |
| Current pinned upstream Chromium binary | Reasonable first qualification candidate if a macOS arm64 artifact with adequate provenance and notice closure exists. [Official download guidance](https://www.chromium.org/getting-involved/download-chromium/#chromium) says snapshots are best-effort, arbitrary revisions and do not auto-update. Record exact source revision, asset hash, third-party contents and security-update ownership; do not assume the label Chromium proves a particular archive contains no restricted components. No alternative archive was downloaded or qualified here. |
| Current pinned Chromium source build | Preferred fallback when binary provenance/contents cannot be established. [Official macOS build instructions](https://github.com/chromium/chromium/blob/main/docs/mac_build_instructions.md) support building Chromium; [branding defaults](https://github.com/chromium/chromium/blob/main/build/config/chrome_build.gni) and [Widevine configuration](https://github.com/chromium/chromium/blob/main/third_party/widevine/cdm/widevine.gni) allow an unbranded build without Widevine. Pin source/dependencies/toolchain, explicitly exclude proprietary components and generate notices for the actual output. Build resources, signing and compatibility remain work, not a tested result. |
| Older pre-CfT Playwright browser | Useful only as a bounded diagnostic comparison, not the recommended release escape. Official [v1.57 release notes](https://playwright.dev/docs/release-notes#version-157) identify the CfT switch; [v1.56.1 manifest](https://github.com/microsoft/playwright/blob/v1.56.1/packages/playwright-core/browsers.json) pins Chromium **141.0.7390.37 / revision 1194**. Its actual binary/notices still need review. An older browser lacks later fixes; version age cannot be exchanged for presumed license certainty. |

All alternative executables need a version-paired functional canary: Playwright's
[launch contract](https://playwright.dev/docs/api/class-browsertype#browser-type-launch)
warns that arbitrary alternative browser versions are not guaranteed compatible. Preserve
the existing worker's explicit profile, isolated writable directory, controlled egress,
artifact capture, cancellation and child ownership requirements. Prove these on the selected
binary and signed app; neither license review nor successful page rendering substitutes for
the native isolation checks. Those requirements remain in [native feasibility](native-feasibility.md).

Downloading Chrome directly on the end user's machine may change who distributes the bytes,
but does not establish appropriate runtime usage, component rights or a managed update policy.
It therefore is not a completed workaround for the product requirement.

## Concrete disposition

1. Mark the installed CfT asset as an observed development candidate with unresolved release
   redistribution/suitability, retaining its actual hashes and notices. Do not silently
   relabel it as permissively licensed Chromium or infer readiness from a Playwright test.
2. Investigate a current macOS arm64 unbranded Chromium artifact first; use a pinned source
   build when its contents/provenance cannot be established. Treat DRM as unsupported unless
   separately licensed; ordinary navigation, interaction and artifact work remain required.
3. Before shipping, close browser and third-party notices, security update ownership,
   version-paired Playwright behavior and native worker containment. Leave this gate open
   until evidence exists for the exact distributed payload.

Method: applied the research skill's primary-source and repository-evidence workflow.
Its requested background-research spawn hit the agent thread limit, so the assigned agent
performed the research directly. Only this note was written; no installs, large downloads,
provider calls, browser launches, account/credential reads or license acceptance occurred.

## 2026-09-08 ADR-010 Linux multi-architecture update

The earlier macOS evidence remains historical. A fresh exact Linux audit rejects the Playwright
1.62.0/revision-1234 browser payload for the web release: amd64 resolves to Chrome for Testing while
arm64 resolves to a Playwright-built non-CfT Chromium archive with no ABOUT/LICENSE/NOTICE members.
The amd64 full-browser archive also contains Widevine. A shared version number therefore does not
make this a symmetric or notice-complete multi-architecture distribution.

The release candidate moves the isolated browser worker to the official Node
`playwright-core@1.63.0` driver and Chromium **headless-shell only**, pending the exact Node/npm lock.
Playwright Python 1.63.0 is not published on PyPI, so pretending it is a Python dependency is
forbidden. Playwright v1.63.0 tag commit is
`1b025d7e20a026371cd5f98ba0cdce48892737c8`; its browser revision 1243 is Chromium
`153.0.8010.12`. The exact audited browser inputs are:

| Platform | Official archive | Bytes | SHA-256 | Executable member SHA-256 |
| --- | --- | ---: | --- | --- |
| linux/amd64 | `https://cdn.playwright.dev/builds/cft/153.0.8010.12/linux64/chrome-headless-shell-linux64.zip` | 119,809,080 | `a9da028861a0cf789ff25c2fed45f5f1aaf969ed9247835b6a7821a4f7af9d1d` | `ded93a9c9a53a1ae040f08124badcca95c938e9d5015ff340c3b5538c41bf39e` (`chrome-headless-shell-linux64/chrome-headless-shell`, 197,422,408 bytes) |
| linux/arm64 | `https://cdn.playwright.dev/builds/cft/153.0.8010.12/linux-arm64/chrome-headless-shell-linux-arm64.zip` | 120,278,638 | `d433c45172c7836e38124fe545f767b02210bfb43a6262f08a297473a8e91c99` | `f5d89353cc9ef8dc1541268bbee1f05ee40a31ce3d9799b3a274e5147f6a8cdb` (`chrome-headless-shell-linux-arm64/chrome-headless-shell`, 189,402,512 bytes) |

Both archives contain 287 members, the same `ABOUT`
(`sha256:34d078ce3003087a8374e7c6156fda374769b8047d6ddaf419d66414aa48edfb`)
and the same 2,257,005-byte `LICENSE.headless_shell`
(`sha256:b92247f7a44c14627ef5cbbe0aa6dcca4e4422b7c05e6f2c660054061a5e3da7`),
and neither contains Widevine. DeepTwin will not mirror these browser archives in the source
release. The user's deployment build fetches the official URL and verifies the exact hash, while
the applicable Chrome for Testing terms and complete notice disposition remain an explicit T084
release gate rather than being inferred from downloadability.

The runtime requires a non-root ephemeral worker, version-pinned seccomp policy, no Docker socket
or host/work mounts, read-only root, bounded scratch and destination-mediated egress. Launch must set
`chromiumSandbox: true`; `--no-sandbox` is rejected. The former Playwright MCR image remains a
development canary only because the official container guidance is for test/development and its
default root execution disables Chromium sandboxing. [Playwright Docker guidance](https://playwright.dev/docs/docker),
[Chrome for Testing](https://developer.chrome.com/docs/chromium/chrome-for-testing)
