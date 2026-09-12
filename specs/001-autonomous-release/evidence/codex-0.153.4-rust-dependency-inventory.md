# Codex 0.153.4 Rust dependency input inventory

Date: 2026-09-08  
Scope: T089 technical build and license-input inventory for the three Rust
executables selected by ADR-013's pinned minimal standalone Codex runner.  This
evidence leaf closes the Rust exact-input enumeration used by T089.  It does
not mutate task state and does not qualify a release.

## Result

The exact Cargo `normal` + `build` closure was resolved offline with Cargo and
rustc 1.95.0 for both supported musl targets.  Development dependencies were
excluded.  The roots are the actual package members:

| Root | `linux/amd64` | `linux/arm64` |
|---|---:|---:|
| `bin/codex` (`codex-cli`) | 1,016 packages | 1,014 packages |
| `bin/codex-code-mode-host` | 537 packages | 537 packages |
| `codex-resources/bwrap` (`codex-bwrap`) | 6 packages | 6 packages |

ADR-013 retains these as three separately signed runner components for each
Linux platform.  The fixed Debian Bookworm Bash runtime is a separate
non-Cargo input verified by the runner/build-input lock and is not part of this
Rust dependency union.

The union contains **1,047 packages**:

- 908 crates.io packages, represented by 908 exact `.crate` archives;
- 134 packages from the pinned OpenAI Codex source archive; and
- 5 packages from 4 precise Git revisions, represented by 4 exact codeload
  commit archives.

The 908 crates.io archives total **184,071,517 bytes**.  Every observed archive
SHA-256 equals its Cargo.lock checksum.  The inventory records archive URL,
size, digest, declared license, target/root membership, custom build-script
presence, native `links` metadata, and candidate license/notice file members.

All 1,047 packages have non-empty Cargo license metadata.  This is not the same
as possessing every required notice text: 1,465 `LICENSE`, `COPYING`, `NOTICE`,
`UNLICENSE`, or `COPYRIGHT` candidate files were byte-hashed inside registry
archives, while **73 registry packages contain no matching in-archive file**.
There are 14 reachable `links` packages and 98 packages with a custom build
target.  Those counts are preserved so a later notice/SBOM process cannot infer
that one top-level SPDX expression is the whole distributed-code license
surface.

The machine-readable result is
`deploy/manifests/codex-0.153.4-rust-dependencies.json`:

- file bytes: `857379`
- file SHA-256: `9d67a5dda134bcdaab8bc62cc2b0fdbb7d2adb3c94062b0a12ea14d09b71b644`
- ADR-008-style canonical semantic digest:
  `a09a94f6099c7f003555d4a1b43da996098c11d2c26a7cefb75062c2799b0d47`

## Source and lock derivation

The source input is the codeload archive for commit
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`:

- URL:
  `https://codeload.github.com/openai/codex/tar.gz/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`
- bytes: `13330433`
- SHA-256:
  `bbbf66ffa30846f1e9bc3ae8a87a5aa0bb768efee8dbb94759dc9eb64bb4aa3a`
- GitHub commit verification observed: unsigned.

The archive's `codex-rs/Cargo.lock` is 378,387 bytes with SHA-256
`3494b8a78d0f643556a83a9cc184e912bcab9f4c5640288952f4223452ba5dc8`.
Its workspace packages still have version `0.0.0`, while the source manifests
declare `0.153.4`.  Cargo 1.95.0 therefore refused the original lock under
`--locked`.  A metadata pass without `--locked` produced a 378,685-byte derived
lock with SHA-256
`a2cb91dfb2e8112bc81d05158fa00b9698e2df8cc1ae0547b5dc5606a44904d3`.

A semantic comparison of all 1,381 lock records found exactly 149 changes.  In
every case, the package was a source-less workspace package and the sole change
was `version = "0.0.0"` to `version = "0.153.4"`.  No name, dependency, source,
or checksum changed.  Both the source lock and derived lock are retained under
`deploy/locks/codex-0.153.4/`; the verifier checks both exact hashes and repeats
the 149-record semantic comparison.  This establishes the candidate resolver
input; it does not prove which transient lock bytes were used by GitHub's
official release job.

## Resolver reproduction

The source was mounted read-only in the pinned local Rust image
`rust@sha256:d81582a30689ffafaa04e2a9e117d39cc5032cb12eee8d6a5f26b1f215c1e3e8`.
The Cargo home was populated once from public upstream sources, then both
platform resolutions were performed with container networking disabled.

For each target:

```text
cargo metadata --locked --offline --format-version 1 \
  --filter-platform <target> \
  --manifest-path /src/codex-rs/cli/Cargo.toml
```

For each of `codex-cli`, `codex-code-mode-host`, and `codex-bwrap`:

```text
cargo tree --locked --offline --target <target> \
  --manifest-path /src/codex-rs/<root>/Cargo.toml \
  -p <package> -e normal,build --prefix none --format '{p}'
```

The root/platform package-set digests are:

| Root | Platform | Package-set SHA-256 |
|---|---|---|
| bwrap | linux/amd64 | `aa178f15381552e99dcf62edbee42eee2ab1846d53e01f06cd6f12015765e87c` |
| bwrap | linux/arm64 | `aa178f15381552e99dcf62edbee42eee2ab1846d53e01f06cd6f12015765e87c` |
| code-mode-host | linux/amd64 | `fc23b7bf9b47fb570a2b55a5607ae6e5e00b596dddb3e8b49e6a7b8dabfe520b` |
| code-mode-host | linux/arm64 | `fc23b7bf9b47fb570a2b55a5607ae6e5e00b596dddb3e8b49e6a7b8dabfe520b` |
| codex | linux/amd64 | `e8223b94a3b2d51f1c7673f9ffcde10d7229880e21da983669c67d92906a1598` |
| codex | linux/arm64 | `e437ec088247a90dfe7f44ba1160704d269a17e8ddba64db2e5a12d92dd4c503` |

The two target closures differ only by two x86_64-only registry packages:
`cpufeatures@0.3.0` and `curve25519-dalek-derive@0.1.1`.

## Git dependency inputs

The Cargo graph contains five packages from four precise Git commits.  Exact
codeload archives were downloaded and hashed as independent source inputs:

| Repository/commit | Packages | Bytes | SHA-256 |
|---|---|---:|---|
| `openai-oss-forks/crossterm@45fecb9508105988f42fe6ff0441783ed3717f92` | crossterm | 144,786 | `408decc2710285f01e6a154e2605891e1af297961fd4e6517dcbfb9491eb6c6f` |
| `helix-editor/nucleo@4253de9faabb4e5c6d81d946a5e35a90f87347ee` | nucleo, nucleo-matcher | 86,782 | `d1676ac33a82c5903ffede68ce73c9d924666aa8a102bb649a8fb926a7a61ce1` |
| `openai-oss-forks/tokio-tungstenite@0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186` | tokio-tungstenite | 33,055 | `a1d8bfedf41ea59d5ed375ebc280dad7099d0c3398e91406c51d485270196a3d` |
| `openai-oss-forks/tungstenite-rs@4fffad30fe373adbdcffab9545e9e9bf4f2fc19f` | tungstenite | 293,806 | `d85393467dd5843688059bb204a61b7450dce1166a2c8aab3c87478955ffce48` |

These hashes make the candidate input exact.  They do not add a signature to
the Git commits or codeload archives.

## Non-Cargo code-mode build input

`codex-code-mode-host` reaches the `v8@150.4.0` crate.  The official Codex
release workflow does not let that crate fetch its ordinary upstream binary;
it downloads the Codex `rusty-v8-v150.4.0` ptr-compression+sandbox build pair
and supplies `RUSTY_V8_ARCHIVE` and `RUSTY_V8_SRC_BINDING_PATH`.

The exact dual-platform inputs were downloaded and checked against both their
two-line checksum files and GitHub's reported asset digests:

| Target | Asset | Bytes | SHA-256 |
|---|---|---:|---|
| x86_64-musl | static archive | 29,557,041 | `d06e08bcbf45a90cfeac8a4d322c7288775cb5e3609ca703ea312b155174e46a` |
| x86_64-musl | Rust binding | 39,884 | `7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506` |
| x86_64-musl | checksum file | 264 | `9bd5beb3a7bfa4f95bc887476ec3e4d564254c1815efe63296740e09bcc8665b` |
| aarch64-musl | static archive | 28,897,449 | `d258efd9c17b67077013f110302ff148fd11428cc4804fcb5c9ad05e3e634cb4` |
| aarch64-musl | Rust binding | 39,884 | `7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506` |
| aarch64-musl | checksum file | 266 | `9c40a51e4d5fcedaec527757b8660115b2a10ca3e2ddacadc3075924ad005b66` |

The tag points to unsigned commit
`12b3e88028b983051913fb6bb95d7a11218bdceb`.  No signature, SBOM, or provenance
attestation asset was observed, and the GitHub release API reports
`immutable: false`.  A checksum distributed beside a mutable artifact is an
exact byte binding, not independent provenance.  This remains an explicit
T079 integrated-security and T082 packaged-provenance risk; it does not reopen
the T089 input inventory.

## Verification

The local verifier checks the pinned semantic digest, exact non-release status,
source and lock hashes, 149 lock rewrites, all 1,047 packages against the
effective Cargo.lock, the six immutable root/platform set digests, all derived
counts, and the exact downstream-boundary language.  With optional
paths, it also hashes all 908 registry archives, four Git archives, six
rusty_v8 assets, and selected members of the 13.3 MB Codex source archive.

```text
PYTHONDONTWRITEBYTECODE=1 python3 deploy/locks/verify_codex_rust_inventory.py
PASS: Codex Rust candidate inventory is exact and remains non-release: 1047 packages, 184071517 registry bytes, digest a09a94f6099c7f003555d4a1b43da996098c11d2c26a7cefb75062c2799b0d47
```

The original full byte-level invocation over the retained audit cache produced
the same package and artifact closure.  Those cache inputs are not committed,
so the ADR-013 wording-only regeneration was not rerun from the audit cache.
The focused test instead asserts that the generator, verifier, and checked-in
manifest carry the same exact qualification limits; all 1,047 package records
and six root/platform package-set digests remain unchanged.

Adversarial tests cover package deletion, target-membership drift,
self-consistent digest rewrites, registry checksum substitution, license-file
removal, boolean/integer confusion, false V8 attestation claims, removal of open
gaps, Git commit substitution, duplicate JSON keys, symlinked inputs, lock
mutation, and missing optional source/artifact bytes:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  deploy.tests.test_codex_rust_inventory_verifier -v

Ran 17 tests in 0.945s
OK
```

## Exact remaining boundaries

This work closes the **enumeration and exact byte-input record** for the Cargo
portion of the three Rust roots retained by ADR-013.  The remaining items are
downstream release qualifications and do not reopen that T089 input lock:

1. The Codex source commit and rusty_v8 tag commit are unsigned, so their
   source provenance is not cryptographically authenticated. T079 retains this
   integrated-security risk.
2. The exact rusty_v8 assets are checksum-bound but have no observed artifact
   signature or attestation and are published on a mutable GitHub release.
   T079 retains the risk and T082 must bind packaged output provenance.
3. The inventory records all declared license expressions and observed text
   candidates, but 73 registry archives have no matching license file.  Text
   selection, complete transitive notices/source offers, publishable LICENSES,
   redistribution/legal review and publication approval remain T084 work;
   technical inventory is not legal clearance.
4. No bit-for-bit build has reproduced the separately signed Codex,
   code-mode-host, or bwrap executables from these inputs.  Per-final-image
   SBOMs, source-to-binary provenance and any authorized signing are T082
   outputs and remain outside this claim.

Accordingly the machine inventory remains
`candidate_exact_input_inventory_not_release_qualified` and its release gate is
`not_satisfied`.
