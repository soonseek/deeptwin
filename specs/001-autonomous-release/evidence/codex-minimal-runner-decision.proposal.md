# Codex 0.153.4 minimal managed-runner decision proposal

**Date:** 2026-09-08

**Scope:** T089 build-input choice and T088 downstream qualification requirements

**Status:** `accepted_by_ADR-013_manifest_v3_locked_input_candidate_not_release_qualified`; this file
does not qualify a release

## Decision

DeepTwin should not make the six-member official full Codex package a mandatory
managed-runner input. The smallest upstream Codex set that supports the required
current-model path is the separately released and separately Sigstore-signed pair:

1. `codex`
2. `codex-code-mode-host`, installed as its sibling

This is a **pair**, not a `codex`-only decision. Codex 0.153.4 declares
`gpt-6-astra` as `code_mode_only`; removing the host makes a requested code-mode
tool call fail rather than fall back to direct tools.

The final Linux runner must also provide a trusted shell and Codex's compatible
`bubblewrap` for the `read-only` and `workspace-write` internal sandboxes. ADR-013
selects OpenAI's separately released and separately signed standalone `bwrap`
asset for both architectures. V1 omits `rg`, the patched zsh fork and
`codex-package.json`; none may be recovered from ambient PATH or package metadata.

Consequently, the production profiles are:

| Profile | Codex inputs | Framework/runtime inputs | Decision |
|---|---|---|---|
| T088 defense-in-depth profile | signed `codex` + signed sibling `codex-code-mode-host` | signed standalone OpenAI `bubblewrap`, pinned Debian Bookworm `/bin/bash`, fixed PATH | **V1 decision** |
| Externally sandboxed exception | signed pair | independently proven destroy-on-exit worker sandbox and trusted shell | Future profile only after a separate decision and T018/T079 proof |
| Official full package | all six members | package layout | Compatible, but not mandatory and currently expands unsigned/unbound provenance work |
| `codex` alone | signed `codex` | any | Reject for Astra/current `code_mode_only` support |

No live ChatGPT subscription, device login, credential, API key, provider model
execution, or paid call was used in this audit. A loopback mock Responses server
tested local protocol and process behavior only.

## Why the full package is not a runtime dependency

The exact audited source is OpenAI Codex commit
[`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`](https://github.com/openai/codex/tree/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a).
The [source archive](https://github.com/openai/codex/archive/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a.tar.gz)
used here was 13,330,433 bytes with SHA-256
`bbbf66ffa30846f1e9bc3ae8a87a5aa0bb768efee8dbb94759dc9eb64bb4aa3a`.

The relevant call graph is:

```text
codex exec
  -> model metadata chooses ToolMode
     -> gpt-6-astra: CodeModeOnly
        -> ProcessOwnedCodeModeSessionProvider (feature on by default)
           -> InstallContext::code_mode_host_program()
              -> packaged resource, otherwise sibling codex-code-mode-host
  -> nested shell execution
     -> Linux sandbox launcher
        -> compatible system bwrap from PATH, otherwise bundled bwrap, otherwise fail closed
  -> search helper
     -> packaged/standalone resource rg, otherwise rg from PATH
  -> session shell
     -> packaged zsh only when ShellZshFork is enabled; otherwise default user shell
```

Permanent source evidence:

- [`install-context/src/lib.rs` lines 152–205](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/install-context/src/lib.rs#L152-L205)
  returns plain `rg` when no resource exists and locates
  `codex-code-mode-host` beside the current standalone executable. The sibling
  path does not require `codex-package.json`.
- [`models-manager/models.json` lines 4–20](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/models-manager/models.json#L4-L20)
  declares `gpt-6-astra` as `code_mode_only`.
- [`core/src/tools/mod.rs` lines 68–89](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/tools/mod.rs#L68-L89)
  gives model metadata priority. Only ordinary `CodeMode`, not
  `CodeModeOnly`, may downgrade to direct tools when the host is unavailable.
- [`core/src/tools/code_mode/mod.rs` lines 98–115](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/tools/code_mode/mod.rs#L98-L115)
  explicitly reports fail-closed behavior and directs the installer to provide
  `codex-code-mode-host`.
- [`core/src/thread_manager.rs` lines 463–470](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/thread_manager.rs#L463-L470)
  selects the process-owned host provider when `CodeModeHost` is enabled.
- [`features/src/lib.rs` lines 923–932](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/features/src/lib.rs#L923-L932)
  and [lines 1000–1004](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/features/src/lib.rs#L1000-L1004)
  makes unified exec and the host stable/default-on, while zsh fork is under
  development/default-off.
- [`core/src/session/session.rs` lines 1160–1186](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/session/session.rs#L1160-L1186)
  requests packaged zsh only for the zsh-fork feature and otherwise uses the
  default shell.
- [`linux-sandbox/src/launcher.rs` lines 38–55](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/linux-sandbox/src/launcher.rs#L38-L55)
  and [lines 126–204](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/linux-sandbox/src/launcher.rs#L126-L204)
  prefers a capability-checked system `bwrap`, falls back to the bundled
  resource, and panics if neither exists. Required capabilities include
  `--as-pid-1` and `--perms`; the source has compatibility paths for optional
  `--argv0` and `--ro-bind-fd`.

OpenAI's own package smoke test deliberately checks every assembled resource,
including its bundled `rg`. That proves completeness of the upstream package,
not that every member is required by an embedding framework. See
[`scripts/codex_package/smoke_tests/test_codex_package.py` lines 39–142](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/scripts/codex_package/smoke_tests/test_codex_package.py#L39-L142).

## Component disposition

| Full-package member | Runtime role in this source | T088 disposition |
|---|---|---|
| `bin/codex` | CLI/`exec --json` entrypoint and auth state consumer | Mandatory, use separately signed standalone asset |
| `bin/codex-code-mode-host` | Out-of-process JavaScript/code-mode engine; required for Astra tool calls | Mandatory, use separately signed standalone asset adjacent to `codex` |
| `codex-resources/bwrap` | Fallback Linux sandbox launcher | Mandatory V1 standalone signed OpenAI asset, installed at the manifest-fixed path |
| `codex-path/rg` | Search command/resource | Omit in V1; neither a built-in tool nor search-acceleration property is promised by this boundary |
| `codex-resources/zsh/bin/zsh` | Experimental zsh-fork shell | Omit in V1 while `shell_zsh_fork=false` |
| `codex-package.json` | Full-package layout metadata | Omit; sibling host discovery was exercised without it |

The runner image uses a fixed, minimal PATH so `bwrap`, the sibling host and the
shell cannot be replaced through ambient host PATH. The Debian Bookworm image
and Bash package/source/member coordinates are now locked below. Their inclusion
does not qualify either final architecture image or its runtime sandbox canaries.

## Locked Bookworm and Bash input closure

The runner base is the dated Docker Official Image
`docker.io/library/debian:bookworm-20260824-slim`, pinned through OCI index
`sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171`.
The two platform manifests, configs and single layers are separately recorded in
`deploy/manifests/codex-0.153.4.json`; a tag or shared index alone is not treated
as a platform lock. The image metadata records the exact architecture-specific
`debuerreotype/docker-debian-artifacts` source revisions.

Both platform images contain Debian Bookworm `bash` `5.2.15-2+b13`, sourced from
`bash` `5.2.15-2`. The child manifest locks each architecture's Snapshot Debian
`.deb`, its `bin/bash` member and mode, the common copyright member, and the
`.dsc`, upstream tarball and Debian patch tarball. The `.dsc` source hashes were
also compared with the declared source files. This establishes exact inputs and
source coordinates; it is not a reproducible source-to-binary proof.

The official-registry and Snapshot Debian bytes were inspected read-only because
the local Docker content store reported an unrelated metadata I/O error. No daemon
restart or unrelated container mutation was used to manufacture runtime evidence.
The authoritative verifier must still reject a substituted `.deb`, archive
member, OCI descriptor or source file before the final runner can be assembled.

## Signed standalone artifact evidence

All six extracted executables were verified with cosign 3.1.2 using the exact
release workflow identity and OIDC issuer. Each returned `Verified OK` offline:

```text
cosign verify-blob --offline \
  --bundle <asset.sigstore> \
  --certificate-identity \
    https://github.com/openai/codex/.github/workflows/rust-release.yml@refs/tags/rust-v0.153.4 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  <extracted-executable>
```

The first audit used cosign 3.1.2 Darwin arm64, 139,584,002 bytes, SHA-256
`dec1c3f802320b19c2fbcf2dc7bcfb3f258e1c181a046c23a1a074bdf932f10a`.
That host-specific observation is not the only reproducible build verifier.

The follow-up verifier-bootstrap audit pinned the [official cosign 3.1.2 release](https://github.com/sigstore/cosign/releases/tag/v3.1.2)
checksum file
(3,906 bytes, SHA-256
`3ef5d389c3f508b96025fd1b92744a305c46e95951c91242b57467567d5622db`)
and its Sigstore bundle (6,578 bytes, SHA-256
`be73ee422be126a70190ee24bf88a1b078cde1f954f076ddf9c0901de4136362`).
The checksum bundle and each executable bundle below returned `Verified OK`
with certificate identity `keyless@projectsigstore.iam.gserviceaccount.com`
and issuer `https://accounts.google.com`:

| Verifier host | Executable bytes / SHA-256 | Bundle bytes / SHA-256 |
|---|---|---|
| linux/amd64 | 141,150,460 / `f7622ed3cf22e55e1ae6377c080979ff77a22da9981c11df222a2e444991e7cf` | 6,433 / `fdaa1c168d67041cd0d8f5782f8136ac5d148827b6911ba8bb577cbc7e13de2c` |
| linux/arm64 | 132,737,437 / `90e7ae0b5dfd60f20816b52c012addf7fc055ebcc7bea4ce81c428ca8518c302` | 6,543 / `e5cb6bc66d703b69c3dc629e77a600cbb67ca6e4bd81e7d690f2c52a73247d10` |
| darwin/arm64 audit bootstrap | 139,584,002 / `dec1c3f802320b19c2fbcf2dc7bcfb3f258e1c181a046c23a1a074bdf932f10a` | 6,574 / `ffbec621bbef3c1e02f05633e74892bd874f2b1157ea57bcb0c7449113966500` |

All three executable hashes also matched the signed checksum file. The Linux
artifacts now provide exact clean-build-host inputs. A separate receipt-capture
command subsequently consumed all 17 exact declared inputs and ran the locked
verifier with the pinned Darwin arm64 Cosign audit artifact. It verified all
six OpenAI executable bundles plus both Debian packages and the three shared
Bash source files, then wrote the checked-in, one-way provenance receipt. The
receipt records `native_linux_verifier_executed=false`; hermetic CI and native
execution of each Linux verifier remain T082 qualification evidence and are not
overstated by the T089 input lock. The aggregate generator can consume and hash
this content-bound receipt but cannot create or replace it. The repository JSON
is not a signed/authenticated attestation and cannot prove who created it.

| Platform / executable | Standalone archive SHA-256 | Sigstore bundle SHA-256 | Extracted executable SHA-256 |
|---|---|---|---|
| linux/amd64 `codex` | `f479424eca092484dc40d87ae28c44f4cc40234a60045d6131e493800d814a30` | `0dc1cab06eade46e05659b84289751a9425f7bb7886c5a10ddc3d6f5735cfaa2` | `56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da` |
| linux/amd64 host | `f95830a869590957664bbfc67bccb08773806b693670baf15908176f89b4cd31` | `a31c6bc2aa530b98986207d67e61061096ba384f623b49ed9992bb628145900f` | `3e85d67471825f73d02ff5f7e047ca1f6ca8caa3f59e4c6e8d9ca6ca7302cb45` |
| linux/amd64 `bubblewrap` | `e7d65c75e05637e42b93f6abf9222fa0d26b537648a7a34c122b75021d41756d` | `4e0e55799310ed3655041bc06246b3ab4b7917a04fc821b8b010d73c23fd53f0` | `77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c` |
| linux/arm64 `codex` | `5cda6182bd94c3a30f2eb63a495489ebf7f691fddb14d70f48c6c1a5071b6cde` | `847b47e73068f86635c23ab5501647a93fab9ad0c450d6661a88481dfcd6d759` | `4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6` |
| linux/arm64 host | `d8047b8d33370d6090e729d27eb76de60a2686baa1c143c138c9b05dc70d813b` | `def3aaaf54077d58f2aa41667d374c4b9c0695ef4d6fb0b7645fdbf0badbe408` | `d677dedf8179ca28ceb869a2e0b60d3ffad3d26f6e7738f7617d34500128a369` |
| linux/arm64 `bubblewrap` | `2c6ea97dfb0a936b695ece6df058b89d4dfd53774a9ad852b3e4c98e6bbdfd20` | `de750905a97468d3fca09304dddf26fefe4427692a316a1486b7eb6f74273f6e` | `c547cbdc762a70ed216789ffaa4c6c0e7d2beabe32245a498f8e365a9fc8dab4` |

These extracted hashes also equal the corresponding members already recorded
in `deploy/manifests/codex-0.153.4.json`. The conclusion does not transfer an
executable signature to either compressed archive; T089 must retain archive
hashes and executable-scoped signature wording.

## Credential-free runtime evidence

Both pairs were staged in isolated directories without `rg`, `bwrap`, zsh, or
`codex-package.json` in an Ubuntu 24.04 Colima VM. The arm64 pair ran natively in that arm64 VM. The
amd64 pair ran through the VM's registered qemu/binfmt path; this is cross-arch
execution evidence, not physical amd64 native qualification.

| Probe | linux/arm64 | linux/amd64 | Meaning |
|---|---|---|---|
| `codex --version` | `codex-cli 0.153.4` | `codex-cli 0.153.4` | Pair starts without full layout |
| `codex exec --help` | exit 0 | exit 0 | Both help bodies had SHA-256 `e504bac5a6364566fbe408132dec7993639def9258ece34e8352f51f8d43687c` |
| isolated `codex login status` | exit 1, `Not logged in` | exit 1, `Not logged in` | No ambient auth used; no `auth.json` appeared |
| isolated, outbound-disabled cancellation | `thread.started`, `turn.started`, then SIGINT/exit 1 | same after emulation startup allowance | JSONL prefix and cancellation work without full layout; no completion claim |
| loopback mock Astra code-mode `text("minimal-host-ok")` | exit 0, two local requests, host output returned | exit 0, two local requests, host output returned | Sibling host works without package metadata/resources; no provider/model claim |
| mock nested shell, `danger-full-access` | tool exit 0, `minimal-shell-ok` | not repeated | Host can delegate to system shell without rg/zsh/bwrap when internal sandbox is deliberately bypassed |
| mock nested shell, `read-only`, no bwrap | tool exit 101 with explicit unavailable message | not repeated | Internal Linux sandbox fails closed without system or bundled bwrap |
| mock code-mode call after removing sibling host | request carried spawn failure for expected sibling path | not repeated | `codex` alone does not satisfy Astra tools |

The mock server and CLI ran together inside a fresh `unshare -n` network
namespace, so only loopback was available. The mock model record explicitly set
`requires_openai_auth=false` and returned deterministic Responses SSE events.
Successful code-mode stdout hashes were
`073a942860947034d68087bd36198b713aa7d197db68752bd98cf333ce2d7f02`
(arm64) and
`85ecdafc9d86f902fbc91c5bd5dffe7262332fc63cb869db7e0d818199048a27`
(amd64). The missing-host second request hash was
`52660f96f8c259531d342b054cfa9811ebf7f55987ad4075ab56d538ada6db9e`.
The recorded read-only missing-bwrap tool-output digest began `c10106e7`; the
full transcript was not retained, so this prefix is diagnostic context rather
than durable release evidence.

The amd64 mock run printed a host `SIGKILL` shutdown message after the terminal
result. Because that run used qemu/binfmt and the result had already completed,
it is recorded as an emulation/shutdown limitation and still requires native
amd64 repetition in T088.

Representative public-artifact and local-runtime commands were:

```text
curl -fL <exact rust-v0.153.4 asset URL> -o <private staging file>
shasum -a 256 <archive-or-bundle>
tar -xzf <archive> -C <private architecture directory>
cosign verify-blob --offline --bundle ... <extracted executable>

colima ssh -- <pair>/codex --version
colima ssh -- env CODEX_HOME=<empty-private-dir> <pair>/codex login status
colima ssh -- sudo unshare -n -- <isolated mock harness and codex exec --json>
```

The runtime harness was intentionally ad hoc because this assignment permitted
only this proposal file. No reusable test program or raw credential/provider
transcript was added. T088 must turn these cases into checked-in, bounded,
adversarial runner tests rather than treating the narrative hashes as release
qualification.

## T089 implications

ADR-013 accepts this direction. T089 replaces the phrase “official full
Codex CLI distribution” with a precise minimal-runner contract:

- lock both standalone Codex archives, executable members, Sigstore bundles,
  certificate policy, source commit/archive, licenses and the exact Rust
  dependency/license-input inventory for linux/amd64 and linux/arm64;
- install `codex-code-mode-host` beside `codex` and record the layout invariant;
- lock the separately signed OpenAI `bubblewrap` archive, executable and Sigstore
  bundle for both architectures and install it at the fixed runner path;
- lock the trusted Debian Bookworm image and `/bin/bash` package/source/member
  closure. Omit `rg` from V1;
- remove the full-package tarballs, imported upstream ripgrep archive, patched
  zsh archive, and `codex-package.json` from mandatory runner inputs after the
  manifest/schema/verifier tests are deliberately updated;
- regenerate the aggregate build-input lock only after the authoritative Codex
  manifest, verifier categories, license references, and tests agree with this
  choice.

This removes the earlier unsigned full-package-archive and unsigned zsh release
paths from the required release boundary. It also removes the need to treat the
upstream ripgrep asset as a Codex package member. T089's exact Rust and
license-input enumeration is closed. Per-final-image SBOM and source-to-binary
provenance remain T082 work, native runner qualification remains T088 work, and
missing license texts/notices/source offers plus redistribution/legal/
publication decisions remain T084 work.

The authoritative child manifest and focused verifier now encode ADR-013's v3
locked input candidate, including the Bookworm/Bash closure and exact
artifact-backed verifier replay receipt. The receipt is not a signed or
otherwise authenticated attestation of its creator. The aggregate lock is
regenerated only by consuming those leaves. Component and aggregate suites pass without converting
the downstream-blocked candidate into a release-qualified one.

## T088 implications

T088 should qualify the final image, not loose staging binaries. Required tests:

1. assert both signed pair hashes and sibling layout before execution;
2. run an isolated `CODEX_HOME`, fixed PATH, explicit model, explicit
   sandbox/approval, ignored ambient config/rules/skills/hooks/MCP, bounded stdin
   and bounded JSONL parser;
3. preflight that the selected current model is known and that
   `code_mode_only` has a healthy host; fail before a user run if the host is
   absent or wrong-version;
4. prove the chosen `bubblewrap` is selected in both target images, then run
   read-only/workspace-write allow/deny, symlink, process escape, cancellation,
   descendant teardown and missing-bwrap fail-closed canaries;
5. prove the runner works without `rg`; keep zsh-fork disabled and test that
   ambient rg/zsh/package metadata cannot change behavior;
6. only in a separately authorized qualification, exercise real
   `codex login --device-auth`, expiry/cancel/reconnect, saved subscription-auth
   reuse/logout, successful terminal `codex exec --json`, live model/tool use,
   and unknown/mismatched-model denial on native linux/amd64 and linux/arm64;
7. keep DeepTwin's authenticated web UI as the only product control surface.
   The CLI and device-code flow remain an internal server-owned bridge.

OpenAI's current documentation supports `codex exec` as the non-interactive
entrypoint, `--json` as JSONL, reuse of saved CLI authentication, and ChatGPT
subscription sign-in: [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode.md),
[Authentication](https://learn.chatgpt.com/docs/auth.md), and
[Codex CLI](https://learn.chatgpt.com/docs/codex/cli.md). Those documents define
the intended adapter contract; they do not substitute for T088's real
subscription qualification.

## Limits and open gates

- No live subscription success, device login, keychain behavior, model output,
  entitlement, rate limit, or paid tool call was tested.
- Arm64 was VM-native; amd64 was qemu/binfmt. Physical/native amd64 remains open.
- The signed standalone `bubblewrap` assets are pinned in the v3 manifest, but
  final-image internal-sandbox success and native dual-platform canaries remain open.
- The dated Bookworm OCI descriptors, Bash binary/source/member inputs and Rust
  dependency/license-input inventory are pinned. Per-final-image SBOM and
  reproducible source-to-binary evidence remain T082 work; exact inputs are not
  equivalent to a reproducible build.
- The mock confirmed the local executable/host protocol, not OpenAI service
  compatibility beyond the exact source's Responses shape.
- The minimal pair reduces the redistribution surface but does not waive
  Apache-2.0 notices, Rust transitive notices/SBOM, system-package licenses,
  source-offer obligations where applicable, or legal approval.
- Temporary Docker staging encountered a containerd metadata I/O error after
  host disk pressure. Tests were therefore run directly in the existing Colima
  VM. No Docker-daemon restart or unrelated-container mutation was attempted.

The decision is therefore **accept the minimal three-artifact signed
architecture and the separately locked shell/runtime closure as the T089 input
set**. The locked input does not qualify a release: T082 packaged provenance,
T084 publication/legal work, and T088 native/live runner qualification remain
open under their own owners.
