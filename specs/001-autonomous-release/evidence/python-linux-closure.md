# T089 Python Linux service-closure evidence

Date: 2026-09-08. Scope: CPython 3.12 service dependency inputs for the self-hostable
open-source web framework. This is build-input evidence, not a final service-image, application
integration, model-inference or release-qualification claim.

## Locked result

The exact base is `python@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254`
(`3.12.14-slim-bookworm`). Direct inspection of that multi-architecture index produced CPython
3.12.14 and glibc 2.36 on both `linux/amd64` and `linux/arm64`. The declared artifact floor is
glibc 2.28 because `huggingface-hub==1.0.1` selects `hf-xet==1.6.0`, whose arm64 wheel is
`manylinux_2_28`; Bookworm satisfies that narrower floor.

| Lock profile | Packages per architecture | amd64 install/import | arm64 install/import | Lock SHA-256 |
|---|---:|---|---|---|
| control-plane | 17 | pass | pass | `66ced7fca949d303db10df2802f7b3a8b533d1dc7175d1edf30fe7f2a36fcb47` |
| runtime | 41 | pass | pass | `1a2ca2d5c83695ce7dc245474dfd807c67b55f29a51bb6a2056e08add88969e6` |
| provider | 21 | pass | pass | `f742c7dc48a8a15acefcfd8ce2076023dd6483f9f99d20f70be476b271d70233` |
| document | 8 | pass | pass | `9efbdb655e9635047e83771abf5e9d84b7ed9935e10c693814d12d7abaebf8f6` |
| speech | 26 | pass | pass | `f62de3f0caf0be99c7efa615e72d08ee0c283eab5c0a2551fd9f33a3611dfd2f` |

The runtime profile is a dependency closure reused in separate evaluation-worker and
runtime-extension-worker images; it does not authorize process or permission co-location. The
other profiles map to their same-purpose isolated service. Final image indexes remain T081 outputs.

Across both architectures and all profiles, 226 selected wheel occurrences reduce to 97 unique
artifacts and 167,132,970 unique bytes. `python-wheel-artifacts.json` SHA-256 is
`8d14cbc3b0acd9bc35773b3658c620409ef5e2ad3f9101b35395a740d4a85029`. It records every exact
filename, size, digest, wheel tag, profile/platform use, official PyPI artifact URL, `Requires-Python`,
declared license metadata and embedded legal-resource hashes. The locally derived
`deeptwin-faster-whisper==1.2.1+deeptwin.1` remains separately identified and has SHA-256
`145997e6be94b4f95d8792ec6675889d7fd39589f8f8fff710d8e13bd47cd956`.

## Native container verification

For each of the ten profile/platform pairs, a fresh disposable container was created from the
exact base descriptor with `--network none`. Only the matching wheelhouse and profile lock were
copied in. Installation used:

```text
python -m pip install --no-index --only-binary=:all: \
  --find-links /wheelhouse --require-hashes -r /requirements.lock
python -m pip check
```

All ten installs and `pip check` calls passed. Imports then passed for:

- control-plane: FastAPI, Uvicorn, Pydantic and Argon2;
- runtime: LangGraph, SQLite checkpointer, LangChain Core and sqlite-vec;
- provider: Anthropic, httpx2, httpx and PyNaCl;
- document: python-docx, pypdf, pypdfium2, Pillow and ReportLab;
- speech: the patched faster-whisper, CTranslate2, tokenizers, Hugging Face Hub, tqdm, NumPy and
  PyYAML.

The speech checks also proved `av` and `onnxruntime` are not importable in either container. The
first amd64 control-plane and arm64 document import probes had a test-command quoting error after
successful installation; corrected fresh-container reruns passed. One first amd64 speech runner
result was not retained after a 30-second harness yield; an independently repeated fresh-container
run completed with exit 0. These are harness retries, not hidden dependency passes.

The repository verifier now passes nine positive/adversarial tests covering the current candidate,
release-blocker enforcement, unused hashes, cross-architecture use, derived-wheel binding, browser
seccomp/capability tampering, missing external-license coverage and changed external-license bytes.
`verify_build_inputs.py` SHA-256 at this evidence point is
`aefae07bb4c86074b8cf5d7c19af8abc7efb3dbd3fd4eed888200850942becdd`; the test file SHA-256 is
`51bd71e54623985205ea9ccbb730cc055df5d861a0d17a56c94ab77ccc72cbd9`.

## Source-license byte capture for wheels without embedded notices

The seven wheel files that omit an embedded license resource map to four exact package versions.
For each package, the manifest now locks the upstream GitHub repository, release tag, 40-character
commit, raw source URL, local byte size and SHA-256. The captured resources are:

| Package | Upstream identity | Locked source-license resource(s) |
|---|---|---|
| CTranslate2 4.8.2 | `v4.8.2` / `d44d2d069eb88c7b7804da864c10c201501cb4a9` | MIT, `54aa79d9fe3c09e67a16dcd95b9e88676405a6ec174efda31036983cf7672ecb` |
| LangSmith 0.12.2 | `v0.12.2` / `aadfe00ed2cf31808d14a32646e73030a9eeb0b5` | MIT, `34e0b9842c7a31d34e53bc7eb224e81e07a34996106e029bbc72dea2d449f496` |
| sqlite-vec 0.1.9 | `v0.1.9` / `e9f598abfa0c06b328d8fe5da9c3760cce74be10` | MIT, `6ce72bbe12d975bd5286e5ab0a064c069693300c47bccbc57bec18485f1621ea`; Apache-2.0, `a38070a94d4afd9cd710e3ce67bd1de78097cfe1784c1f0109ac95d3c196bfdc` |
| tokenizers 0.22.1 | `v0.22.1` / `afaae088837b277c19f90604a1111a272838857b` | Apache-2.0, `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |

The verifier requires exact coverage of every package/version whose selected wheel lacks an
embedded license resource and fails if any captured byte, size, digest or commit-bound URL changes.
This closes the reproducibility gap in the legal-review input; it is not legal approval.

## Open gates

This run did not mount the speech model or perform transcription, PDF visual QA, framework request
handling, non-root final-image execution, seccomp/UDS isolation or application end-to-end work.
Seven wheel artifacts still lack an embedded license resource: the two CTranslate2 wheels,
LangSmith, the two sqlite-vec wheels and the two tokenizers wheels. Their exact upstream project
license bytes are now locked, but bundled native third-party obligations, missing license texts,
release notices/source offers and the distribution/legal/publication disposition remain a T084
gate. Final-image `ldd`, per-image SBOM, source-to-binary provenance and hermetic native-Linux
repetition remain T082 work. These downstream qualifications do not reopen the T089 input lock.
