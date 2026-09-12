# T089 supply-chain verification evidence

Date: 2026-09-08

Scope: independent verification of the Codex 0.153.4 Linux executable signatures, the `playwright-core@1.63.0` npm registry signatures and attestations, and the age 1.3.2 Linux Sigsum proofs. This evidence does not qualify runtime behavior, redistribution, native dual-architecture execution, or source reproducibility unless explicitly stated.

## Codex 0.153.4

The first audit verified both unpacked `codex` executables with Cosign 3.1.2 and the following exact
policy. ADR-013's follow-on minimal-runner audit then verified the separately released
`codex-code-mode-host` and `bubblewrap` executables for both architectures with the same required
certificate identity and issuer; their exact archive, executable and bundle hashes are recorded in
`codex-minimal-runner-decision.proposal.md` and the v3 child manifest.

```text
certificate identity: https://github.com/openai/codex/.github/workflows/rust-release.yml@refs/tags/rust-v0.153.4
OIDC issuer: https://token.actions.githubusercontent.com
workflow name: rust-release
workflow ref: refs/tags/rust-v0.153.4
repository: openai/codex
workflow commit: 3d2ee51ca2d5db578f328aa75e20aa22c0197c9a
trigger: push
runner: github-hosted
run: 33926543788/attempts/1
```

The verification command included `--certificate-identity`, `--certificate-oidc-issuer`, and every `--certificate-github-workflow-*` constraint above. Both commands exited `0` with `Verified OK`. A deliberately incorrect identity exited `1`.

| Platform | Standalone archive SHA-256 | Signed executable SHA-256 | Bundle SHA-256 |
|---|---|---|---|
| linux/amd64 | `f479424eca092484dc40d87ae28c44f4cc40234a60045d6131e493800d814a30` | `56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da` | `0dc1cab06eade46e05659b84289751a9425f7bb7886c5a10ddc3d6f5735cfaa2` |
| linux/arm64 | `5cda6182bd94c3a30f2eb63a495489ebf7f691fddb14d70f48c6c1a5071b6cde` | `4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6` | `847b47e73068f86635c23ab5501647a93fab9ad0c450d6661a88481dfcd6d759` |

Verifier: Cosign 3.1.2, commit `193d2153431f8bb0d945a4c1ee721872f73add67`, darwin/arm64 binary SHA-256 `dec1c3f802320b19c2fbcf2dc7bcfb3f258e1c181a046c23a1a074bdf932f10a`, 139,584,002 bytes. Its official checksum matched, and its own bundle SHA-256 `ffbec621bbef3c1e02f05633e74892bd874f2b1157ea57bcb0c7449113966500` verified with identity `keyless@projectsigstore.iam.gserviceaccount.com` and issuer `https://accounts.google.com`.

Boundary: each OpenAI Sigstore bundle is scoped to its corresponding unpacked executable, not its
compressed archive or an assembled package. ADR-013 therefore locks each standalone archive,
executable and executable-scoped bundle separately. The earlier full-package, imported `rg`, zsh
and sidecar-parent-digest path is historical and is not an authoritative V1 dependency.

### Debian Bookworm runtime input

The ADR-013 child manifest now pins Docker Official Debian
`bookworm-20260824-slim` by OCI index plus architecture-specific manifest,
config and layer descriptors. It also pins Debian `bash` `5.2.15-2+b13` for
amd64 and arm64 by Snapshot Debian `.deb`, the exact `bin/bash` member and mode,
the shared copyright member, and all three declared `bash` `5.2.15-2` source
inputs. The common OCI index digest is
`sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171`;
the complete per-platform values remain machine-readable in
`deploy/manifests/codex-0.153.4.json` rather than being partially duplicated here.

The official OCI layer and Snapshot Debian inputs were inspected read-only and
the Bash executable/copyright member hashes were derived from each `.deb` data
archive. The source hashes matched the `.dsc` declarations. This closes the
exact input-coordinate gap, but does not prove reproducibility from source,
final image assembly, native behavior, or legal approval.

### Artifact-backed receipt capture

The independently run receipt-capture path consumed a read-only staging
directory containing the 17 exact declared runner/source inputs: six OpenAI
standalone archives, their six Sigstore bundles, both architecture-specific
Bash `.deb` files, and the three shared Bash source files. It selected the
manifest-pinned Cosign 3.1.2 Darwin arm64 audit artifact and ran the locked
offline verifier against the v3 child manifest. The verifier re-hashed every
input, inspected the exact Bash members and source declarations, and returned
successful Sigstore verification for all six Linux executable members.

Only after that verifier returned a complete report did
`capture_codex_provenance_receipt.py` create
`codex-0.153.4-provenance-receipt.json`. The receipt truthfully records
`execution_platform=darwin/arm64`, `result=pass`, and
`native_linux_verifier_executed=false`. It is a required content-bound evidence
leaf: the aggregate lock generator requires, verifies and hashes it, but cannot
create or replace it. The checked-in JSON is not a signed or otherwise
authenticated attestation, so its exact schema and hashes do not prove which
tool, process or person created it. Native Linux verifier execution, hermetic
release-CI repetition and packaged output provenance remain T082 work rather
than implied T089 evidence.

## playwright-core 1.63.0

Attestation endpoint:

```text
https://registry.npmjs.org/-/npm/v1/attestations/playwright-core@1.63.0
```

The endpoint response was 15,084 bytes with SHA-256 `cd87562d3380bb32463ba4f8e3bf52b039f37eda3fc4e556783da01296581ff1`. The package archive was 3,123,044 bytes with SHA-256 `208593d4e1bcd8f8fe5f869cad1cc332dc7f1d70dc1d58c102dc3ac36e30f26c`; its registry SRI and both attestation subjects matched SHA-512 `ad80ac045fcce478d4721e766dbb5538d1058efe97bbcb26f21ef674d951e5bcc81357ef0bf6f182ca7392349f53e3307843263ccf0a25e6c6ea79f2c68e660a`.

In an isolated, lifecycle-script-disabled temp project:

```sh
npm audit signatures --json --include-attestations
```

Official npm CLI 12.0.2 exited `0`, returned `invalid: []` and `missing: []`, and verified the npm publish and SLSA provenance bundles for `playwright-core@1.63.0`.

The verified SLSA payload was then compared with this allowlist:

```text
identity: https://github.com/microsoft/playwright/.github/workflows/publish_release.yml@refs/tags/v1.63.0
issuer: https://token.actions.githubusercontent.com
repository: https://github.com/microsoft/playwright
workflow: .github/workflows/publish_release.yml
ref: refs/tags/v1.63.0
commit: 1b025d7e20a026371cd5f98ba0cdce48892737c8
event: release
repository id: 221981891
owner id: 6154722
builder: https://github.com/actions/runner/github-hosted
invocation: https://github.com/microsoft/playwright/actions/runs/33926504498/attempts/1
```

All observed fields matched. Release code must implement this exact postcheck because npm's successful exit alone does not enforce an application-specific repository, workflow, ref, or commit allowlist.

Verifier: npm 12.0.2 archive SHA-256 `5dbb86c71d07a1957f2e90734092dd6a58bdcd9ebc2d8d41ca1c6e6a21d364e1`, 3,045,132 bytes, official registry SRI matched, source tag commit `b888cc9a9ff34a8b023ff47b784692396635397b`, Artistic-2.0. The verification used host Node 22.23.1; that Node runtime was not independently provenance-verified in this check and remains a release-verifier pinning requirement.

## age 1.3.2

The age project's two published submitter keys and the verifier's built-in `sigsum-generic-2025-1` policy were used exactly as documented:

```sh
sigsum-verify -k age-sigsum-key.pub -P sigsum-generic-2025-1 AGE_ARCHIVE.proof < AGE_ARCHIVE
```

| Platform | Archive SHA-256 | Proof SHA-256 | Result |
|---|---|---|---|
| linux/amd64 | `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` | `98402fa59b4e433426156b4a7e74a32e44902e0434c61158f7de18ffc84f1f97` | exit 0 |
| linux/arm64 | `6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4` | `a174de2bf22a72efedd1a779cbee8b7d5605b41a25fae085807003b4abf5688e` | exit 0 |

Verifier: `sigsum-verify` 0.13.1, module sum `h1:q3LCLow8dWmy2hivXhEwu2uNeCwigIbLMwS1+CD35Lo=`, source commit `c537b12e18bdc787b5ed300eea630f3cb4e988bf`, locally built binary SHA-256 `a887cabb731f786f028a98eb2f11969d0944ebc51e2bda8b8a5fc5ad831ed51d`, 3,834,114 bytes, BSD-2-Clause. Bootstrap Go 1.27.1 darwin/arm64 archive was 68,100,347 bytes with SHA-256 `ee215d57e0ec269c60cc9ceca68e6bda321ba9ee5afe24f4b0988703c2d87d12`, matching official go.dev release metadata.

Boundary: Sigsum proves that the exact release archives were authorized by an age project submitter key and satisfied the named transparency-log/witness policy. It does not prove reproducibility from source commit `b74dce4cdbe35b5e5f66c06d9612b72f89028758`.

The later runtime-qualification pass also matched the embedded Go module sets in
`age` and `age-keygen` to an eight-component/three-license-file technical bundle,
then passed restricted native X25519 positive and negative canaries on both Linux
architectures. Those results are recorded in
`age-1.3.2-runtime-qualification.md`. They close the technical module/license-input
and loose-artifact native-canary gaps, not production integration, final-image
qualification or legal approval.

## Remaining release blockers

- Codex per-final-image SBOMs, source-to-binary provenance, hermetic/native-Linux
  verifier repetition and any authorized signing remain T082 work. Native
  dual-architecture execution/sandbox/JSONL/cancel tests and dedicated
  `CODEX_HOME` authentication lifecycle qualification remain T088 work. Missing
  license texts, notices/source offers, publishable LICENSE selection and
  redistribution/legal/publication approval remain T084 work. The exact Rust,
  Debian Bookworm and Bash input coordinates are locked; that is not runtime or
  release qualification.
- Browser worker Debian snapshot closure, automatic SLSA allowlist enforcement with a provenance-pinned Node verifier runtime, Chromium redistribution disposition, and native sandbox/PDF/screenshot/trace/cancel/egress tests.
- age production restricted-bridge integration, hermetic release-CI verifier
  bootstrap, final-image/PATH/plugin-denial tests and legal approval. The exact
  embedded-module license inputs and loose-artifact dual-architecture X25519/
rejection canaries now pass.

## Final T089 verification checkpoint

The final aggregate is `locked` with semantic digest
`2fb6fd8b108ce31f1cc49a9d9ffd3a335584cde677b63de6dceb683731708b24`
and file SHA-256
`212eb478026a2e38b40d882c2525fcee6a3945ed258dbb0d89b615489e62e0bd`.
The content-bound receipt SHA-256 is
`ce9a740da70ae0117265d195105376114ffac3be0aea43d20e6d2d5377f9cd1a`.

On the final files, the root reran all 223 Python deploy tests and all 19 Node
provenance tests; the aggregate, component and 1,047-package Rust inventory
verifier CLIs passed. Same-timestamp aggregate construction matched the checked-in
bytes twice and did not change the receipt. A separate read-only auditor first
demonstrated that the earlier summary-only check accepted an incomplete report.
After correction, an independent re-audit passed: the expected report binds all
17 input filenames, sizes and SHA-256 values plus all six platform/component
Sigstore outcomes, uses canonical exact equality, and rejects 257 recursive key
deletion, unknown-key insertion and list deletion/insertion mutations.

This closes only T089's build-input enumeration and integrity gate. The receipt's
local JSON bytes do not authenticate their creator. Native-Linux/hermetic packaged
provenance, final image SBOMs and signing remain T082; notices, source offers,
license selection and legal/publication approval remain T084; native runner and
authorized subscription behavior remain T088.

Official references: [Codex release](https://github.com/openai/codex/releases/tag/rust-v0.153.4), [Sigstore Cosign verification](https://docs.sigstore.dev/cosign/system_config/installation/), [npm provenance](https://docs.npmjs.com/generating-provenance-statements/), [npm audit signatures](https://docs.npmjs.com/cli/commands/npm-audit), [age Sigsum instructions](https://github.com/FiloSottile/age/blob/v1.3.2/SIGSUM.md), [age 1.3.2 release](https://github.com/FiloSottile/age/releases/tag/v1.3.2), and [Go downloads](https://go.dev/dl/).
