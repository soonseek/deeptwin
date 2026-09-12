# Codex 0.153.4 managed-runner closure proposal

Date: 2026-09-08  
Decision: **not release-qualified**  
Scope: credential-free supply-chain and runner-boundary evidence only

This document preserves a historical proposal beside, not a replacement for,
`deploy/manifests/codex-0.153.4.json`. At this audit point that manifest had not
yet changed; its exact input was 9,031 bytes with SHA-256
`f3465870a6c70ba2eb900e2822310f2a28639996e4edcbc359dfe1851084781c`.
The machine-readable candidate additions are in
`codex-0.153.4-sidecar-closure.proposal.json`, whose status is deliberately
`proposal_not_manifest_integrated` and whose release gate is deliberately
`not_satisfied`. ADR-013 and the current v3 child manifest have since integrated
the selected minimal-runner input boundary; this proposal file remains
non-authoritative historical evidence.

No ChatGPT account, API key, OS keychain entry, existing Codex home, device
login, or paid model call was used. Network was disabled for runtime probes.
Only public release assets were downloaded to private temporary directories;
no raw artifact or credential was copied into the repository.

## Result boundary

| Claim | Result | Exact boundary |
|---|---|---|
| Full Linux package archives | PASS | Both exact archives have the six declared regular files, five declared directories, safe exact modes, exact metadata, and no extra/symlink/special member. |
| Package archive signature | UNMET | The package tarballs themselves have no Sigstore bundle. An official checksum row is not a package signature. |
| `codex-code-mode-host` provenance | PASS, proposed | Both package members equal the independently signed standalone executable byte-for-byte; all four identity/issuer checks were run offline with pinned cosign. |
| `bubblewrap` provenance | PASS, proposed | Same limited executable-member scope as above. This does not close redistribution obligations. |
| ripgrep bytes and license inputs | PASS, provenance still open | Release archive, checksum sidecar, executable member, package member, `LICENSE-MIT`, and `UNLICENSE` match. The checksum asset was not shown to be cryptographically bound to the signed source tag. |
| zsh bytes and distribution lock | PASS, provenance still open | The release lock, archive, and package member match. The `codex-zsh-v0.1.0` tag/archive are unsigned and the build was not reproduced. |
| Redistribution notice bundle | UNMET | Codex `LICENSE`/`NOTICE`, bubblewrap `COPYING`, ripgrep licenses, zsh `LICENCE`, an SBOM, code-mode/Rust transitive inventory, and legal approval are not assembled into a shipping bundle. |
| `codex --version`, exec help, signed-out status | PASS in containers | Both Docker platform variants reported 0.153.4, identical help, required flags, and signed-out exit 1 without an auth file. This is not physical-host native evidence. |
| Bounded JSONL and cancellation | PASS | Synthetic failure cases and real accountless container runs prove bounded capture and that an incomplete prefix is never normalized as completion. |
| Auth lifecycle | FIXTURE PASS only | A hash-pinned offline fixture proves isolated state/status/reuse/logout mechanics without opening auth bytes. It does not prove device auth, OS keyring behavior, subscription entitlement, or a provider success path. |
| Tool/sandbox execution under a model | UNMET | It cannot be proven without an authenticated provider run. |

Nothing in the PASS rows changes the overall decision: the release remains
blocked.

## Primary behavior contract

OpenAI documents `codex exec` as the non-interactive entry point and `--json`
as JSON Lines on stdout, including thread, turn, item, and error events in
[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).
OpenAI also documents CLI sign-in, device authentication, reuse of saved auth,
`CODEX_HOME`, `codex login status`, and logout in
[Authentication](https://learn.chatgpt.com/docs/auth).

Those pages justify the shape of the adapter, not a claim that an unauthenticated
test exercised the service. The production browser remains DeepTwin's control
surface; this CLI is an internal managed provider bridge.

The constructed 0.153.4 command is:

```text
codex exec
  --ignore-user-config
  --ignore-rules
  --strict-config
  -c approval_policy="never"
  --ephemeral
  --model <explicit bounded id>
  --sandbox <read-only|workspace-write>
  --color never
  --json
  --skip-git-repo-check
  --cd <explicit workspace>
  -
```

The prompt is delivered on stdin, not argv. The child starts in a new process
session. Stdout and stderr are drained independently and hashed while retained
bytes are capped. Default limits are 4 MiB total JSONL, 512 KiB per line, 4,096
events, JSON depth 32, stderr 512 KiB, and prompt 64 KiB. Cancellation and
deadline escalation are SIGINT, SIGTERM, then SIGKILL. Output overflow follows
the same path. An escaped `setsid` descendant can retain inherited pipes, so the
observer has a hard drain cutoff; a production container/PID namespace/cgroup
that is destroyed at job end is therefore a mandatory runtime prerequisite.

The JSONL verifier is intentionally a bounded lifecycle/framing validator. It
checks strict UTF-8 LF records, final newline, duplicate keys, finite and bounded
numbers, known 0.153.4 event/item kinds, one initial thread, turn ordering,
stable item id/type, terminal placement, token usage, and no active item at a
terminal event. It is not a complete validator for every domain-specific item
payload. A downstream consumer must validate the payload schema it uses.

## Exact full-package evidence

Source release: [OpenAI Codex `rust-v0.153.4`](https://github.com/openai/codex/releases/tag/rust-v0.153.4)  
Source commit: `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`  
Pinned official checksum file: 1,392 bytes,
`645fb8d4a1f821357a7160f04a6d15bf54ff97ab6946a79239c551ebed734d23`

| Platform | Archive bytes | Archive SHA-256 | Members / dirs |
|---|---:|---|---:|
| linux/amd64 | 126,196,303 | `a822187e1a2420c61c5926721bfbd878701ed95547c9bb0d4de4498a16ba1821` | 6 / 5 |
| linux/arm64 | 117,238,842 | `fc395cb043a1093ab0db34f44aba3199bfaa9ce640cd9be7fd588f44b0da64a4` | 6 / 5 |

| Member | linux/amd64 SHA-256 | linux/arm64 SHA-256 |
|---|---|---|
| `bin/codex` | `56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da` | `4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6` |
| `bin/codex-code-mode-host` | `3e85d67471825f73d02ff5f7e047ca1f6ca8caa3f59e4c6e8d9ca6ca7302cb45` | `d677dedf8179ca28ceb869a2e0b60d3ffad3d26f6e7738f7617d34500128a369` |
| `codex-path/rg` | `e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849` | `e36d0eb52e70696bdf1781392722e05a21bb91d3b7b762ef5ec20e5df2ec687b` |
| `codex-resources/bwrap` | `77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c` | `c547cbdc762a70ed216789ffaa4c6c0e7d2beabe32245a498f8e365a9fc8dab4` |
| `codex-resources/zsh/bin/zsh` | `67faaaa89242c4a332e16e508a1977cffc24bf7fca31d4411cdfd101f3831ef3` | `7feeacd883e1dc749847936948c378653c80a69ec4a9542f0f126b411882c179` |
| `codex-package.json` | `43f8735a93a7947c6dc082c550d2ff2d795fccfd1c7eb27c93aa91cbead1e3f4` | `a3c985c334a13f6168900d9aa900d875797e4c7a8a6432768bd1d64740f53f54` |

The exact member set also proves that no license, notice, or SBOM file is in
either full package.

## Signed sidecar proposal

Pinned verifier: cosign 3.1.2, 139,584,002 bytes,
`dec1c3f802320b19c2fbcf2dc7bcfb3f258e1c181a046c23a1a074bdf932f10a`.
Each verification used `verify-blob --offline` and the exact policy:

- certificate identity:
  `https://github.com/openai/codex/.github/workflows/rust-release.yml@refs/tags/rust-v0.153.4`
- OIDC issuer: `https://token.actions.githubusercontent.com`

| Platform / component | Standalone archive SHA-256 | Bundle SHA-256 | Bound package member SHA-256 |
|---|---|---|---|
| amd64 / code-mode host | `f95830a869590957664bbfc67bccb08773806b693670baf15908176f89b4cd31` | `a31c6bc2aa530b98986207d67e61061096ba384f623b49ed9992bb628145900f` | `3e85d67471825f73d02ff5f7e047ca1f6ca8caa3f59e4c6e8d9ca6ca7302cb45` |
| arm64 / code-mode host | `d8047b8d33370d6090e729d27eb76de60a2686baa1c143c138c9b05dc70d813b` | `def3aaaf54077d58f2aa41667d374c4b9c0695ef4d6fb0b7645fdbf0badbe408` | `d677dedf8179ca28ceb869a2e0b60d3ffad3d26f6e7738f7617d34500128a369` |
| amd64 / bubblewrap | `e7d65c75e05637e42b93f6abf9222fa0d26b537648a7a34c122b75021d41756d` | `4e0e55799310ed3655041bc06246b3ab4b7917a04fc821b8b010d73c23fd53f0` | `77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c` |
| arm64 / bubblewrap | `2c6ea97dfb0a936b695ece6df058b89d4dfd53774a9ad852b3e4c98e6bbdfd20` | `de750905a97468d3fca09304dddf26fefe4427692a316a1486b7eb6f74273f6e` | `c547cbdc762a70ed216789ffaa4c6c0e7d2beabe32245a498f8e365a9fc8dab4` |

All four returned exit 0. A deliberately wrong identity returned exit 1.
Unit tests also reject a component/member relabel, a different signed member,
a changed policy, and a nonzero verifier. These signatures cover the unpacked
standalone executables only; they do not sign either full package archive.

## Imported sidecars and redistribution inputs

The OpenAI release workflow at the pinned commit has SHA-256
`8c617e18825d43d29d59af75419d9e7b40594256d3225c0cf39b7abde745a6c9`.
Its pinned ripgrep DotSlash input has SHA-256
`41a10ca63365560d899a82b6f825fd7b420a18b34f660a98bffeece77eeae1f1`.

For ripgrep 15.2.0:

| Platform | Release archive | Checksum sidecar | Package/member match | License members |
|---|---|---|---|---|
| amd64 | `33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c` | `650080eb90718156132c821d150d8b74818f66de47969e38eef5a2dce3e2a5e6` | PASS | PASS |
| arm64 | `a740b91c82eaf9914cfedd353572f2791cbe0162c84101ee0951058f4dcbc90d` | `7b3f20fe255204e11cdb79fbca5ef7ccff1a10cb4bef53b3a5add996e1792105` | PASS | PASS |

`LICENSE-MIT` is 1,081 bytes,
`0f96a83840e146e43c0ec96a22ec1f392e0680e6c1226e6f3ba87e0740af850f`;
`UNLICENSE` is 1,211 bytes,
`7e12e5df4bae12cb21581ba157ced20e1986a0508dd10d0e8a4ab9a4cf94e85c`.
GitHub reported the annotated 15.2.0 source tag as PGP-verified at commit
`e89fff89ac9af12e8d4ce9d5fd07beb408ca730f`, but this audit did not establish
a cryptographic connection from that tag to the downloadable checksum asset.

For zsh, the `rust-v0.153.4` workflow pins a separately downloaded DotSlash
lock to 2,486 bytes and
`c534eab89dcea7e3d8a5e5b3f49c025c7c64cd4e4d9814ee24871de58a9359a1`.
The verifier proved the lock binds both release archives and that their sole
executables equal the package members:

| Platform | Archive SHA-256 | Member/package match |
|---|---|---|
| amd64 | `cb6ea328232cabd80f59141471a1362eb39b146a4d5e8a654d9b80cf9b7ec83c` | PASS |
| arm64 | `2968a278581e4e7937212c9b14d634e318c7bd13d17c20c549a1ecbae673a121` | PASS |

The `codex-zsh-v0.1.0` tag resolves to
`891f1f4c8584a082fc4658cabd48f1a8b01354e0` and is annotated but unsigned.
The build workflow names upstream Zsh commit
`77045ef899e53b9598bebc5a41db93a548a40ca6`; the patch hash is
`696b7d923b8071554d00e811afb9a08fcad4baada796f7314d12ecd72d06152c`.
Upstream `LICENCE` is 1,963 bytes,
`d06fdf3ef9b1ec69d6b9e170b0a9516fbad3523261ff1668bde3bfea6e0ef5f5`,
but it is absent from both the zsh archive and the full Codex package.

Other redistribution inputs found but absent from the package are:

| Input | Bytes | SHA-256 |
|---|---:|---|
| Codex `LICENSE` | 10,926 | `d17f227e4df5da1600391338865ce0f3055211760a36688f816941d58232d8dc` |
| Codex `NOTICE` | 242 | `9d71575ecfd9a843fc1677b0efb08053c6ba9fd686a0de1a6f5382fd3c220915` |
| vendored bubblewrap `COPYING` | 25,383 | `b7993225104d90ddd8024fd838faf300bea5e83d91203eab98e29512acebd69c` |

This is an inventory for legal review, not legal advice or approval. The
bubblewrap terms and source-offer/redistribution obligations must be reviewed
before shipping.

## Runtime probes

Both platform variants used the exact multi-platform base index
`python@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254`.
The probes ran as UID/GID 65534, read-only rootfs, `--network none`, all
capabilities dropped, `no-new-privileges`, 64-process limit, 256 MiB memory,
and dedicated tmpfs state. Temporary staged images and containers were removed.

Both variants returned:

- version: `codex-cli 0.153.4`
- exec-help SHA-256:
  `e504bac5a6364566fbe408132dec7993639def9258ece34e8352f51f8d43687c`
- all required command flags present
- `codex login status`: exit 1, no `auth.json`

The accountless real-CLI cancellation runs were supervised by the new bounded
runner. Both emitted exactly `thread.started`, `turn.started`, no terminal
event, no unfinished item, and no stderr before SIGINT. Results:

| Platform | Elapsed | Exit | Signals | JSONL bytes | JSONL SHA-256 | Normalized outcome |
|---|---:|---:|---|---:|---|---|
| linux/amd64 container | 3.280014 s | 1 | SIGINT | 101 | `be7fabfda2b370576f0263ae137ddbccb1fc7fbcd1024f3570817b5b6cc3acfe` | `cancelled` |
| linux/arm64 container | 3.337453 s | 1 | SIGINT | 101 | `89a866b4c57b9eca5f06504d06a0176599b8be2e0999fa118a6393c0c17f71eb` | `cancelled` |

Different stream hashes are expected because `thread_id` is unique. No output
content is retained in the report, only bounded metadata and hashes. These are
Docker platform probes on an arm64 development host; amd64 may be emulated and
neither row is physical native-Linux qualification.

The offline auth fixture separately proves the following local state machine:

```text
absent -> status(exit 1) -> device-auth fixture -> auth.json(0600, one link)
       -> status(exit 0) -> bounded JSONL fixture -> logout -> absent
```

The verifier inspects only `lstat` metadata for the synthetic auth handle; it
never opens or hashes its bytes. This fixture has no authority to claim that
real Codex uses `auth.json` rather than an OS keyring on a particular machine.

## Reproduction summary

The added verifier provides four subcommands:

```text
verify_codex_runner.py package
verify_codex_runner.py signed-sidecar
verify_codex_runner.py imported-sidecar
verify_codex_runner.py jsonl
```

Credential-free verification performed in this audit:

- two real full-package verifications: PASS
- four real signed-sidecar/package bindings: PASS
- four real imported-sidecar/package/license-or-lock bindings: PASS while
  reporting `cryptographic_provenance_closed: false`
- two real version/help/signed-out container probes: PASS
- two real accountless cancellation container probes: PASS
- 34 synthetic verifier/runner/auth failure-path tests: PASS

Proposed repository artifacts before any authoritative integration:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `deploy/locks/verify_codex_runner.py` | 67,073 | `397ca9068d59ef6fb1b47ef391d2adac54ff60b001969e1b4085a362b26a6f1f` |
| `deploy/tests/test_codex_runner_verifier.py` | 36,636 | `f2de1eae873b10e7000856856a156f2526d8a823370caa85cffff5777a914347` |
| `codex-0.153.4-sidecar-closure.proposal.json` | 12,577 | `c87ea6a38801c8cd444dc0942ca7cee2245801d9a2fc18b55f29d7684c358874` |

The tests cover extra/symlink/duplicate archive members, signature-scope
overstatement, mismatched or relabeled sidecars, nonzero Sigstore verification,
unbound checksums, provenance overstatement, duplicate JSON keys, NaN/Infinity,
huge integers, CRLF/missing newline, invalid event order/type transitions,
unfinished terminal items, output floods, non-reading stdin, timeout/cancel,
detached inherited pipes, ambient secret rejection, CODEX_HOME symlinks, auth
symlinks/hardlinks, and fixture hash/marker gates.

## Residual verifier assumptions

The verifier rejects symlink inputs and unsafe modes, but its large assets are
hashed and later reopened by path. Until fd-based verify/use or immutable-copy
staging is added, CI must download all inputs into a private mode-0700 staging
directory that no concurrent same-UID process can mutate. This is a stated
trust assumption, not a closed adversarial TOCTOU guarantee.

The synthetic auth fixture hash is supplied by its test caller. It detects
mutation of the intended fixture; it is not an external code-signing trust
anchor.

## Historical input gaps and current downstream work

The first two gaps identified at this evidence point were dispositioned by
ADR-013: the signed host/bubblewrap inputs are integrated in the current v3
child, while ripgrep and zsh are excluded from the required V1 runner boundary.
The remaining work below qualifies packaged output or runtime behavior and does
not reopen the T089 input lock:

1. T082 produces per-final-image SBOM and source-to-binary provenance, repeats
   verification hermetically on native Linux, and applies authorized signing.
2. T084 resolves the 73 Codex/Rust missing license-text cases, supplies notices
   and source offers, makes the repository-license selection, and obtains
   redistribution/legal/publication approval.
3. T018 puts every job in a destroy-on-exit container/PID namespace/cgroup; the
   bounded observer is never run directly on an unconstrained host.
4. T088 runs the native linux/amd64 and linux/arm64 runner canaries and, in an
   explicitly authorized later qualification, tests real subscription
   device auth, the configured credential store/keyring, login reuse, logout,
   successful terminal JSONL, cancellation, and tool/sandbox enforcement. That
   later test may not copy or print authentication bytes.

Until these downstream gates are satisfied, retain
`candidate_not_release_qualified` / `not_satisfied`; that release status is not
a T089 build-input blocker.

## Task ownership boundary

The remaining items do not all belong to T089:

- **T089 input record:** the current v3 child integrates the selected
  code-mode-host/bubblewrap inputs, excludes the unsigned full-package, ripgrep
  and zsh paths, locks the Codex/code-mode/Rust license inputs, and is referenced
  by the regenerated content-derived aggregate digest.
- **T018 downstream isolation:** implement the real provider/Codex worker,
  dedicated egress, PID namespace/cgroup teardown, authenticated bounded IPC,
  non-root filesystem/mount policy, and resource limits. The detached-child
  assumption belongs here.
- **T025 downstream authority/storage:** implement the production credential
  vault/root, owner/deployment authority, rotation/recovery, and secret-safe
  browser command path. The synthetic auth file is not a substitute.
- **T088 downstream runner behavior:** implement device-login state, dedicated
  Codex auth volume, normalized full payload consumers, reconnect/cancel, and
  authorized subscription success qualification.
- **T079 downstream integrated security:** rerun secret, direct-egress,
  wrong-peer, sandbox, dependency, and license canaries against the integrated
  staged/final topology.
- **T081 downstream distribution:** build the actual DeepTwin service images
  from the T089 digest and publish their per-platform index/manifest/config/
  layer locks. T089 must not invent those future image digests.
- **T082 downstream packaged provenance:** produce each final image's SBOM and
  source-to-binary provenance, repeat verification hermetically on native Linux,
  and apply authorized signing.
- **T084 downstream publication/legal gate:** assemble publishable
  `LICENSES/`, `NOTICE`, source offers and third-party/source-license
  documentation, resolve the 73 Codex/Rust missing license-text cases, scrub
  private paths, and obtain the copyright owner's required license and
  redistribution/legal/publication decisions. The current T089 manifest
  supplies the exact input identities that T084 consumes.
