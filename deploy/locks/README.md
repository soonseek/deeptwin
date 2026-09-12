# DeepTwin release build-input locks

This directory contains immutable **inputs** for the self-hostable open-source web framework.
It does not contain or claim final DeepTwin service-image digests. T081 creates those images only
after the required services exist and records them in the final `PlatformSupportManifest`.

Current state: the aggregate T089 build-input lock is `locked`; the release is
still `candidate_not_release_qualified` while downstream owner gates remain.

- `service-roots.json` records direct Python roots by isolated service boundary.
- `requirements-{control-plane,runtime,provider,document,speech}-linux.lock` are the exact
  CPython 3.12/glibc 2.28 closure profiles. They stay separate so isolated services do not force
  unrelated transitive packages into one environment. The runtime profile is consumed separately
  by the evaluation and runtime-extension workers; every other profile maps to its same-purpose
  service. The speech profile replaces pristine faster-whisper with the DeepTwin PCM-only wheel.
  Per-platform artifact, upstream URL, license-resource and service-profile mappings live in
  `../manifests/python-wheel-artifacts.json`.
- model, browser, upstream image, Codex runner, age and license/provenance records belong in
  `../manifests/` and are folded into one content-derived `BuildInputLockManifest`.
- installation uses a separately verified per-platform wheelhouse, `--require-hashes` and
  `--no-index`; an application container never resolves or downloads packages or model files.

The input lock cannot be promoted while a required architecture, binary
dependency, technical license/provenance input, offline install/import check or
upstream-image digest is unresolved. Missing license texts, final notices/source
offers, LICENSE selection and redistribution/legal/publication decisions are
T084 release work. Per-final-image SBOMs, source-to-binary provenance, hermetic
native-Linux verification and authorized signing are T082 release work. Those
downstream gaps keep the release unqualified but do not reopen a complete T089
input enumeration.

## Codex provenance receipt boundary

`generate_build_input_lock.py` is an aggregate generator, not an evidence
producer. It requires an exact artifact-backed verifier replay receipt at
`specs/001-autonomous-release/evidence/codex-0.153.4-provenance-receipt.json`,
verifies its subject, verifier, complete runner report, all 17 file bindings,
all six signature outcomes and result rows, then hashes
the unchanged receipt into the aggregate. A missing or non-passing receipt makes
locked generation fail. The generator cannot mint or overwrite a PASS receipt.

`capture_codex_provenance_receipt.py` is the supported receipt-capture tool. It
requires the exact child manifest, all exact offline artifacts and a
manifest-pinned Cosign executable; it runs `verify_codex_runner.py` before using
an atomic create-without-replacement operation. Native Linux is the release
verification path. The explicitly selected locked Darwin arm64 verifier may
capture a cross-platform audit receipt, but that receipt records
`native_linux_verifier_executed=false` and does not substitute for T082's
hermetic/native-Linux packaged provenance. The checked-in JSON is content-bound
but is not a signed or otherwise authenticated attestation, so repository
verification cannot prove which tool, process or person created it.
