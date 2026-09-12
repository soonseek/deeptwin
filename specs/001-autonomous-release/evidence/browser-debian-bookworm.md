# Debian 12 browser-worker build-input closure evidence

Status: **candidate, blocked from release qualification**. This evidence closes package resolution,
records successful Debian metadata/signature verification and an arm64 sandbox/render canary for
the pinned browser worker. The amd64 package transaction passed under emulation, but the Chromium
sandbox did not; this document therefore does not claim native dual-architecture qualification or
legal disposition.

## Inputs and fixed snapshot

- Base: `docker.io/library/node:24.20.0-bookworm-slim`, OCI index `sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e`.
- Browser driver: `playwright-core@1.63.0`, npm tarball SHA-256 `208593d4e1bcd8f8fe5f869cad1cc332dc7f1d70dc1d58c102dc3ac36e30f26c`.
- Debian snapshot path: `20260907T000000Z` for `debian` bookworm/bookworm-updates and `debian-security` bookworm-security. The release dates returned by that single path are respectively 2026-07-11, 2026-09-06, and 2026-09-06 UTC. Exact Release/InRelease/index bytes and hashes are locked in the manifest because Debian Snapshot documents that a requested time can resolve to the latest import before it.
- Playwright's tagged Debian 12 table supplies 21 Chromium roots and 10 font roots. `xvfb` is intentionally excluded for headless-shell. The extracted Debian native-dependency subsection SHA-256 is `3c0e9c1046fc2c061d9f943a938328441838c4a60003bd4246f7435987764da0`.

Official references: [Debian Snapshot usage](https://snapshot.debian.org/), [Playwright v1.63.0 native dependency source](https://github.com/microsoft/playwright/blob/v1.63.0/packages/playwright-core/src/server/registry/nativeDeps.ts), [Playwright Docker sandbox guidance](https://playwright.dev/docs/docker), [Chromium Linux sandbox design](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/sandboxing.md), [Debian copyright policy](https://www.debian.org/doc/debian-policy/ch-docs.html#copyright-information).

## Playwright npm provenance policy

The release postcheck is now implemented and pinned. It consumes the exact byte/hash-bound JSON
emitted after npm's cryptographic signature/attestation verification, requires exactly one publish
and one SLSA bundle, hashes both statements, and applies an exact allowlist to the subject, package
SHA-512, repository, workflow, tag ref, source commit, event, repository/owner IDs, builder and
invocation. It also parses the SLSA bundle's Fulcio X.509 DER and independently checks the SAN,
OIDC issuer and duplicate GitHub claims against the same allowlist. Nineteen synthetic adversarial
tests pass, including re-hashed statement changes, certificate identity/issuer changes and duplicate
bundle/claim cases.

The initial policy-only run used an unqualified host Node and correctly returned exit `3`. The same
postcheck was then run with network disabled, a read-only root, uid 1000, all capabilities dropped
and no-new-privileges under the exact pinned Node 24.20.0 OCI platforms. Both linux/arm64 and the
emulated linux/amd64 run returned exit `0`: the running executable hashes exactly matched the
separately authenticated Node release bytes and the policy had no remaining runtime blocker. This
qualifies the provenance postcheck runtime; it does not qualify native amd64 Chromium behavior and
does not replace npm's cryptographic verification.

## Node 24.20.0 release-byte authentication

The official clear-signed `SHASUMS256.txt.asc` verifies against the commit-pinned Node release
keyring with signer fingerprint `5BE8A3F6C8A5C01D106C0AD820B1A390B168D356` and signature time
2026-08-26T14:25:36Z. A networkless offline verifier checked the complete 5,888-member structure of
each official linux-x64 and linux-arm64 archive, rejected unsafe tar forms, and matched the exact
`bin/node` and `LICENSE` bytes. Those executable hashes also match `/usr/local/bin/node` in the
corresponding platform selected from the pinned Node OCI index. Twenty adversarial verifier tests
pass. This authenticates the selected release bytes, not a reproducible source build, the whole OCI
filesystem, or upstream provenance of the verifier image and `gpgv` binary.

## Resolution result

The amd64 and arm64 package names and versions are identical:

- 104 packages are reachable from the 31 declared roots.
- Actual ELF `DT_NEEDED` inspection of both headless-shell archives adds one explicit base assertion, `libudev1=252.39-1~deb12u2`, for a 105-package final runtime set.
- Each platform graph has 219 versioned dependency edges and zero unresolved groups.
- The only alternative choices are `debconf` for `debconf | debconf-2.0` and `fonts-dejavu-core` for fontconfig's default-font alternative group.
- The pinned Node OCI layers were read directly. Each architecture has 88 installed dpkg records. Thirty-one closure packages plus `libudev1` are already exact in the base; 72 packages are additions and `libpcre2-8-0` is upgraded from `10.42-1` to `10.42-1+deb12u1`.
- Install delta: 73 `.deb` files, 45,435,472 bytes on amd64 and 44,543,182 bytes on arm64.
- The audit downloaded and SHA-256-verified all 210 full-closure `.deb` artifacts (105 per architecture), not only the 146 delta artifacts.

The complete raw resolution audit is preserved only by content descriptor: 516,378 bytes, SHA-256 `c1757a2b08e699b3be4e37134f4dec37985953b79d68f7f242188354af7090b8`. Its machine-local path is intentionally absent from publishable artifacts.

## Source and copyright evidence

The compact sidecar maps the 105 binaries to 85 exact Debian source packages and records every `.dsc`/source-tar URL, byte count, and SHA-256 from the pinned Sources indexes. It also records the extracted binary copyright evidence:

- 103 packages contain a direct `/usr/share/doc/<package>/copyright` payload.
- `libgcc-s1` uses the Debian-policy-permitted package-directory link to `gcc-12-base`; the target copyright evidence is resolved explicitly.
- There are 85 unique copyright payload hashes on each platform.
- Extracted `License:` fields are evidence only. Forty legacy copyright documents do not use structured DEP-5 fields, so no automatic SPDX/legal conclusion is made.

## Observed OpenPGP and byte verification

After the read-only resolution audit, all pinned metadata files were fetched again and their bytes
matched the manifest. The repository verifier and exact 73-file delta for both architectures were
copied into fresh `--network none` containers based on
`python@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254`.
Both `linux/amd64` and `linux/arm64` runs passed:

- every `InRelease` and detached `Release.gpg` signature verified with `gpgv`;
- each signed `Release` SHA-256/size entry matched its Packages and Sources index;
- both delta directories contained exactly the 73 expected `.deb` files and every byte/hash matched;
- the keyring was `debian-archive-keyring 2023.3+deb12u2`, 55,918 bytes, SHA-256
  `506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017`;
- `gpgv 2.2.40-1.1+deb12u2` binary SHA-256 was
  `e82416f3ae002b63c0731f311519c55fc9e7d3c8bdadbd64239833298f09a2cf` on amd64 and
  `26999f2766739b3df31c6c355856440bbd7377a5a19ebcf3f6cfe4cfb3c42f69` on arm64.

This verifies the selected repository bytes and authority chain. The immutable release build must
repeat it; a local pass does not replace build provenance or native browser execution.

## Observed offline package transaction

The exact Node OCI index
`sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e`
was run for both Docker target platforms on the arm64 development host. The arm64 target was native
to the Docker VM; amd64 used platform emulation and is not native-amd64 release evidence. Both runs:

- matched the pinned pre-transaction dpkg-status hash and exactly 88 base packages;
- used Docker `--network none` and one local APT transaction over only `/debs/*.deb`;
- reported `Need to get 0 B`, added 72 packages, upgraded only `libpcre2-8-0`, and ended with
  exactly 160 installed packages;
- matched all 105 closure package versions, produced an empty `dpkg --audit`, rebuilt fontconfig,
  found five Korean-capable font-family rows, and had no unresolved `ldd` dependency;
- matched `Google Chrome for Testing 153.0.8010.12` and the locked ELF member hashes.

An earlier attempt to combine APT absolute local paths with `--no-download` failed inside APT before
installing anything. A second cache/name experiment also failed before installation because no
candidate package indexes were present. The accepted method relies on a network-disabled container,
an exact local file allowlist and the observed `0 B` fetch requirement; it does not falsely claim
that APT's `--no-download` flag worked for this transaction.

## Observed non-root sandbox and artifact canary

Playwright's tagged guidance established the required `clone`, `setns` and `unshare` user-namespace
exception. The candidate does not copy Playwright's older full default profile. It starts from the
current pinned Moby default at commit `61eaf32614c7c71b60bd8927d3e6a4ffc8ff1f31` (13,470 bytes,
SHA-256 `536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74`) and prepends one exact
`clone`/`setns`/`unshare`/`chroot` allow rule. The rule's canonical SHA-256 is
`ed7d3a2f86df38ed26fc39bdfc56741570507cd643fb0a41481726233d9a02bb`; the derived profile is
17,006 bytes, SHA-256 `8878c8683ef98daaaf9f296767581084d87969111e36d18a61bb70a8e3eff22a`.
It preserves Moby's `clone3=ENOSYS` rule rather than granting an uninspectable blanket `clone3`.

The final passing arm64 configuration used a non-root `node` identity, read-only root filesystem,
tmpfs-only working space, `--network none`, all Linux capabilities dropped with none added, the
derived seccomp profile, and `no-new-privileges`. The outer process therefore has no `SYS_CHROOT`;
the kernel permits chroot only after Chromium creates its user namespace and gains the namespace-
local capability. `SYS_ADMIN`, `SYS_PTRACE` and every Chromium sandbox-disable flag remained forbidden.

The default Docker seccomp profile correctly failed closed with `No usable sandbox`. Playwright's
older profile progressed further but its capability-gated chroot rule failed when all outer
capabilities were dropped. A diagnostic configuration adding only `SYS_CHROOT` passed, after which
the derived namespace-local profile removed that outer capability and passed again. The canary proved:

- exact Playwright 1.63.0 and browser executable bytes/hash;
- a CDP renderer mapped to its `/proc` `NSpid` chain, uid 1000, `NoNewPrivs=1` and `Seccomp=2`;
- no non-loopback interface/route or proxy variable, plus blocked HTTP and WebSocket probes;
- Korean DOM and canvas rendering with 4,251 non-background pixels;
- a validated 1280×960 PNG (78,716 bytes), PDF 1.4 (139,457 bytes), and Playwright trace
  (175,973 bytes, 41 trace events, eight completed actions).

The headless-shell binary does not expose `chrome://sandbox` and returns the exact
`net::ERR_INVALID_URL`; the canary records that limitation and uses the renderer process signals
above rather than inventing a status page. On emulated amd64, the same strict canary failed closed
at launch with `No usable sandbox`. No `--no-sandbox` fallback was attempted or accepted. A native
linux/amd64 host is therefore still required. The network-none probes establish denial, not the
future authenticated destination-broker allow path, and this run did not exercise cancellation.

## Reproducible installation sequence

1. Verify the Node OCI index, target platform manifest/config/layers, then extract and compare the exact dpkg-status SHA-256 from the pinned layers.
2. Repeat the now-observed locked `InRelease`, `Release`, `Release.gpg`, Packages and Sources verification with the pinned `gpgv` and Debian archive keyring bytes, including Release-to-index SHA-256 linkage.
3. Fetch only the 73 platform delta artifacts from the manifest and verify filename, size, SHA-256, snapshot timestamp and absence of extra `.deb` files.
4. Disable container networking, expose only the verified local `.deb` allowlist and perform one `apt-get install --no-install-recommends /debs/*.deb` transaction. Require APT to report `0 B` fetched; do not run an unpinned `apt-get update`, upgrade, install-latest operation or rely on the incompatible absolute-path `--no-download` invocation.
5. Re-assert the 105-package closure versions and 160-package total, clear APT cache/index material, build the fontconfig cache, and record the final image filesystem/SBOM/provenance.
6. On native amd64 and arm64, apply the pinned seccomp profile and capability allowlist, then require no missing `ldd`/ELF dependencies, the non-root sandbox canary, Korean DOM/canvas/screenshot/PDF/trace fixtures, and the authenticated egress/cancellation matrix.

## Remaining release blockers

- Repeat metadata and offline package verification in the immutable image build; the local runs do not provide release provenance.
- Run the strict sandbox/render canary on a native linux/amd64 host. The emulated amd64 failure is not waived and no sandbox bypass is allowed.
- Qualify cancellation and authenticated destination-broker egress on both native architectures; network-none denial alone is insufficient.
- Reproduce the passing Node archive/OpenPGP and Playwright allowlist checks inside the immutable
  release build and bind their results to T082 provenance.
- Chromium/Chrome-for-Testing and Debian notice/source disposition still requires the release legal gate.
- These remaining items are T018/T079/T081/T082/T084 release and runtime gates, not missing browser
  build-input identities. The browser portion of T089 is locked; none of these observations claims
  that a final browser-worker image or the full DeepTwin web framework is release-qualified.

## Locked candidate artifacts

| Intended path | Bytes | SHA-256 |
| --- | ---: | --- |
| `deploy/manifests/browser-worker.json` | 20054 | `584035ab08b1cee72fa745dfc5f7ff8d9be1a8a23206ce7e4a460fde56f7c704` |
| `deploy/manifests/browser-debian-bookworm.json` | 162033 | `191f88c1ab982b67dff13f62f96910355271133f69a6e9bd8a50714a2fc286cf` |
| `deploy/manifests/browser-debian-bookworm.sources.json` | 155081 | `ba3120935f5ddf1e8d9942892b53c119a6adbcaebd06e54f4846e43af8bf2692` |
| `deploy/locks/verify_browser_debian_bookworm.py` | 14258 | `79bffd5c97e8f89a3ba9165e9bb7f062b4213dc329a124a7cf6a4032d1a78c59` |
| `deploy/locks/verify_browser_runtime.mjs` | 6071 | `2509398b6bbdd33a4df989a543f01b5b83c0e11f4e05db46d9270c9b2e94e973` |
| `deploy/locks/moby-default-seccomp-61eaf326.json` | 13470 | `536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74` |
| `deploy/locks/browser-worker-seccomp.json` | 17006 | `8878c8683ef98daaaf9f296767581084d87969111e36d18a61bb70a8e3eff22a` |
| `deploy/tests/browser_worker_canary.mjs` | 28919 | `704f3e435790ae9af1e0d78047179c34ffc85cecee5d7b322c996a094402bee2` |
| `deploy/locks/verify_playwright_provenance.mjs` | 29871 | `cb122e241441f8b063ae747957031b38aab85cbd5aaa952fd39b203a6ee29e31` |
| `deploy/tests/test_playwright_provenance_verifier.mjs` | 14306 | `16aa4fedd68b6239c76cb62aaa312ddfcdfb1525ff95fec3f334641fae387ac4` |
| `deploy/locks/verify_node_release.py` | 36317 | `490da6edc3563ac6e5510f350f5e32911fc273b2ff37c174749a481da1f222b2` |
| `deploy/tests/test_node_release_verifier.py` | 19762 | `24aedf4ac573dffd09f0fabd3d3be55e5ca3c7e1d8ef2c1c63cf72cacdb8f1fd` |
| `specs/001-autonomous-release/evidence/node-24.20.0-release-results.json` | 2996 | `b6115fe3a4f3b45e756ce78060f747cf233aef8d9e8056919b3491e7c83f5403` |
| `specs/001-autonomous-release/evidence/playwright-1.63.0-provenance-results.json` | 1920 | `386c95c9dedac0e582226bcd97dd3a46bd8b50223b3b8ef3d0f7ebfd0ce2d7ee` |

The verifiers check manifest/sidecar hashes, official timestamped URL boundaries, package/source
coverage, graph reachability, base/delta partitioning, exact local artifacts, the Moby-base-to-
DeepTwin-seccomp one-rule derivation, canary/provenance-postcheck binding and optionally the signed Release/index chain.
A pass deliberately reports that native release gates remain.
