# Third-party notices inventory (draft)

Date: 2026-09-23 · Status: **draft technical inventory for T084. This is not a NOTICE file, not
legal advice and not a distribution approval.** No `NOTICE` or `LICENSES/` directory has been
created; they must be assembled and reviewed before any publication, and only after the copyright
owner approves the repository license ([license-recommendation.md](license-recommendation.md)).

## How to read this page

- Every licence value below is copied from **lock or manifest metadata in this repository**. Nothing
  was looked up elsewhere and nothing is guessed. Where no value is recorded, the entry says
  **unknown**.
- A declared licence label is upstream metadata. It does not prove the licence of every file in a
  package (native wheels in particular may bundle further third-party code) and it is not a
  review result.
- "Embedded licence text" says whether the wheel itself contains a licence file according to
  `deploy/manifests/python-wheel-artifacts.json`. For the wheels marked **no**, the manifest's
  `legal_gate` locks upstream licence text under `deploy/locks/licenses/` instead.

## 1. Python release wheels

Source: `deploy/manifests/python-wheel-artifacts.json` (status `candidate_not_release_qualified`),
which maps the per-service Linux locks `deploy/locks/requirements-*-linux.lock`. 76 distinct
name/version pairs; `Services` names the isolated service profiles that consume each wheel.
Declaration source: `expr` = PEP 639 `License-Expression`, `field` = core-metadata `License`
field, `classifier` = trove classifier only.

| Package | Version | Declared licence (as recorded) | Source | Services | Embedded licence text |
| --- | --- | --- | --- | --- | --- |
| aiosqlite | 0.22.1 | MIT License | classifier | runtime | yes |
| annotated-doc | 0.0.5 | MIT | expr | control-plane, speech | yes |
| annotated-types | 0.8.0 | MIT | expr | control-plane, provider, runtime | yes |
| anthropic | 1.4.0 | MIT | field | provider | yes |
| anyio | 4.15.1 | MIT | expr | control-plane, provider, runtime, speech | yes |
| argon2-cffi | 25.1.0 | MIT | expr | control-plane | yes |
| argon2-cffi-bindings | 25.1.0 | MIT | expr | control-plane | yes |
| certifi | 2026.7.22 | MPL-2.0 | field | provider, runtime, speech | yes |
| cffi | 2.0.0 | MIT | expr | control-plane, provider | yes |
| charset-normalizer | 3.5.1 | MIT | field | document, runtime | yes |
| click | 8.5.0 | BSD-3-Clause | expr | control-plane | yes |
| ctranslate2 | 4.8.2 | MIT | field | speech | **no** |
| deeptwin-faster-whisper | 1.2.1+deeptwin.1 | MIT | field | speech | yes |
| distro | 1.9.0 | Apache License, Version 2.0 | field | runtime | yes |
| docstring-parser | 0.18.0 | MIT | field | provider | yes |
| fastapi | 0.141.1 | MIT | expr | control-plane | yes |
| filelock | 3.32.5 | MIT | expr | speech | yes |
| fsspec | 2026.7.0 | BSD-3-Clause | expr | speech | yes |
| h11 | 0.16.0 | MIT | field | control-plane, provider, runtime, speech | yes |
| hf-xet | 1.6.0 | Apache-2.0 | expr | speech | yes |
| httpcore | 1.0.9 | BSD-3-Clause | expr | provider, runtime, speech | yes |
| httpcore2 | 2.12.0 | BSD-3-Clause | expr | provider, runtime | yes |
| httpx | 0.28.1 | BSD-3-Clause | field | provider, runtime, speech | yes |
| httpx2 | 2.12.0 | BSD-3-Clause | expr | provider, runtime | yes |
| huggingface-hub | 1.0.1 | Apache | field | speech | yes |
| idna | 3.19 | BSD-3-Clause | expr | control-plane, provider, runtime, speech | yes |
| jiter | 0.16.0 | MIT | expr | provider | yes |
| jsonpatch | 1.33 | Modified BSD License | field | runtime | yes |
| jsonpointer | 3.1.1 | Modified BSD License | field | runtime | yes |
| langchain-core | 1.6.2 | MIT | field | runtime | yes |
| langchain-protocol | 0.0.19 | MIT | field | runtime | yes |
| langgraph | 1.2.11 | MIT | expr | runtime | yes |
| langgraph-checkpoint | 4.2.0 | MIT | expr | runtime | yes |
| langgraph-checkpoint-sqlite | 3.1.1 | MIT | expr | runtime | yes |
| langgraph-prebuilt | 1.1.0 | MIT | expr | runtime | yes |
| langgraph-sdk | 0.4.4 | MIT | expr | runtime | yes |
| langsmith | 0.12.2 | MIT | field | runtime | **no** |
| lxml | 6.1.3 | BSD-3-Clause | field | document | yes |
| markdown-it-py | 4.2.0 | MIT License | classifier | speech | yes |
| mdurl | 0.1.2 | MIT License | classifier | speech | yes |
| numpy | 2.3.4 | BSD License | classifier | speech | yes |
| orjson | 3.12.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | expr | runtime | yes |
| ormsgpack | 1.12.2 | Apache-2.0 OR MIT | expr | runtime | yes |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | expr | runtime, speech | yes |
| pillow | 12.3.0 | MIT-CMU | expr | document | yes |
| pycparser | 2.23 | BSD-3-Clause | field | control-plane, provider | yes |
| pydantic | 2.13.5 | MIT | expr | control-plane, provider, runtime | yes |
| pydantic-core | 2.46.5 | MIT | expr | control-plane, provider, runtime | yes |
| pygments | 2.21.0 | BSD-2-Clause | expr | speech | yes |
| pynacl | 1.6.2 | Apache-2.0 | field | provider | yes |
| pypdf | 6.17.0 | BSD-3-Clause | expr | document | yes |
| pypdfium2 | 5.13.0 | BSD-3-Clause, Apache-2.0, dependency licenses | field | document | yes |
| python-docx | 1.2.0 | MIT | field | document | yes |
| pyyaml | 6.0.3 | MIT | field | runtime, speech | yes |
| reportlab | 5.0.1 | BSD license (see license.txt …) | field | document | yes |
| requests | 2.34.2 | Apache-2.0 | field | runtime | yes |
| requests-toolbelt | 1.0.0 | Apache 2.0 | field | runtime | yes |
| rich | 15.0.0 | MIT | field | speech | yes |
| shellingham | 1.5.4 | ISC License | field | speech | yes |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | field | provider, runtime | yes |
| sqlite-vec | 0.1.9 | MIT License, Apache License, Version 2.0 | field | runtime | **no** |
| starlette | 1.6.0 | BSD-3-Clause | expr | control-plane | yes |
| tenacity | 9.1.4 | Apache 2.0 | field | runtime | yes |
| tokenizers | 0.22.1 | Apache Software License | classifier | speech | **no** |
| tqdm | 4.67.1 | MPL-2.0 AND MIT | field | speech | yes |
| truststore | 0.10.4 | MIT | expr | provider, runtime | yes |
| typer | 0.27.2 | MIT | expr | speech | yes |
| typer-slim | 0.24.0 | MIT | expr | speech | yes |
| typing-extensions | 4.16.0 | PSF-2.0 | expr | control-plane, document, provider, runtime, speech | yes |
| typing-inspection | 0.4.4 | MIT | expr | control-plane, provider, runtime | yes |
| urllib3 | 2.7.0 | MIT | expr | runtime | yes |
| uuid-utils | 0.17.0 | BSD-3-Clause | expr | runtime | yes |
| uvicorn | 0.52.4 | BSD-3-Clause | expr | control-plane | yes |
| websockets | 16.1.1 | BSD-3-Clause | expr | runtime | yes |
| xxhash | 4.0.1 | BSD-2-Clause | field | runtime | yes |
| zstandard | 0.25.0 | BSD-3-Clause | expr | runtime | yes |

Notes on specific entries:

- `deeptwin-faster-whisper 1.2.1+deeptwin.1` is a DeepTwin-built PCM-only variant of the upstream
  faster-whisper wheel (`deploy/locks/build_downstream_faster_whisper.py`). Its notice obligations
  as a modified work have not been reviewed.
- `certifi`, `orjson` (in part) and `tqdm` (in part) declare MPL-2.0; MPL file-level obligations
  need review before distribution.
- `numpy` records only a generic "BSD License" classifier (its `License` field holds full text
  without a short value); the exact variant and any bundled components are unverified here.
- `pypdfium2` declares "BSD-3-Clause, Apache-2.0, dependency licenses"; it bundles the PDFium
  binary, whose own notices are not inventoried here.
- The manifest's `legal_gate` records that `ctranslate2`, `langsmith`, `sqlite-vec` and
  `tokenizers` wheels lack embedded licence resources and that upstream licence texts are locked
  under `deploy/locks/licenses/`.

## 2. Development-only Python packages

`uv.lock` (115 packages) also resolves packages used only for development, testing and supply-chain
tooling (the `dev` dependency group) or only by the development slice. `uv.lock` records **no licence
metadata**, so their licences are **unknown** in this inventory. They are not part of the release
wheel manifest. Examples: `pytest 9.1.1`, `pytest-cov 7.1.0`, `hypothesis 6.167.1`,
`mypy 2.3.1`, `ruff 0.16.6`, `cyclonedx-bom 7.3.1`, `detect-secrets 1.5.0`, `reuse 6.2.0`,
`coverage 7.16.1`, `uvloop 0.22.1`, `httptools 0.8.0`, `watchfiles 1.2.0`, `jinja2 3.1.6`.
`jsonschema 4.26.0` is a runtime pin in `pyproject.toml` but does not appear in the release wheel
manifest; whether any release service needs it is unverified.

## 3. age backup encryption (Go binaries)

Source: `deploy/manifests/age-1.3.2.json` and `deploy/manifests/age-1.3.2-runtime-licenses.json`
(status `candidate_technical_inventory_not_legal_approval`, `legal_approval: false`). Licence
texts: `deploy/locks/licenses/age-1.3.2/`.

| Component | Version | Declared SPDX (manifest) |
| --- | --- | --- |
| filippo.io/age (`age`, `age-keygen`) | v1.3.2 | BSD-3-Clause |
| Go runtime and standard library | go1.27.0 | BSD-3-Clause |
| filippo.io/edwards25519 | v1.2.0 | BSD-3-Clause |
| filippo.io/hpke | v0.4.0 | BSD-3-Clause |
| filippo.io/nistec | v0.0.4 | BSD-3-Clause |
| golang.org/x/crypto | v0.55.0 | BSD-3-Clause |
| golang.org/x/sys | v0.47.0 | BSD-3-Clause |
| golang.org/x/term | v0.45.0 | BSD-3-Clause |

Build-time verification tool, not shipped: `sigsum-verify` v0.13.1 (policy
`sigsum-generic-2025-1`) verifies the age release archives. Its licence is **unknown** (not
recorded in the manifests).

## 4. Other locked components

| Component | Version | Declared licence (as recorded) | Source |
| --- | --- | --- | --- |
| Node.js runtime | 24.20.0 | licence text locked (`deploy/locks/licenses/Node-24.20.0-LICENSE.txt`); SPDX label not recorded | `deploy/manifests/browser-worker.json` |
| playwright-core | 1.63.0 | Apache-2.0 | `browser-worker.json` |
| Chromium headless shell | 153.0.8010.12 | licence bundle recorded by size/digest only; label not recorded | `browser-worker.json` |
| Debian bookworm browser runtime closure | 105 binaries / 85 source packages | per-package copyright payloads recorded | `browser-debian-bookworm.json`, `browser-debian-bookworm.sources.json` |
| npm (verification tool only) | 12.0.2 | Artistic-2.0 (verifier runtime record) | `browser-worker.json` |
| Speech model `Systran/faster-whisper-small` | rev `2ec96c54…` | MIT (declared by model card); OpenAI Whisper MIT text locked | `deploy/manifests/speech-model.json` |
| Codex managed runner | 0.153.4 | Apache-2.0 (workspace crates) | `deploy/manifests/codex-0.153.4-rust-dependencies.json` |
| Codex Rust dependency closure | 1,047 packages | every package declares an expression (mostly MIT/Apache-2.0 variants; also MPL-2.0, Unicode-3.0, ISC, BSD, Zlib, CC0-1.0, CDLA-Permissive-2.0 and others); 73 registry archives have no licence file | same |
| Upstream base images | python 3.12.14-slim-bookworm, node 24.20.0-bookworm-slim, caddy 2.11.4-alpine | image contents not licence-inventoried | `deploy/manifests/upstream-images.json` |
| Silero (licence text only) | unknown | MIT text locked (`deploy/locks/licenses/Silero-MIT.txt`) | `deploy/locks/licenses/` |

## 5. Browser shell and prototypes

`app/static/` loads no third-party JavaScript or fonts from the network (CSP `script-src 'self'`);
no bundled third-party front-end library was found there. `control-prototype/` and `prototype/`
were not inventoried by this draft.

## 6. Open items before a NOTICE file can exist

1. Owner approval of the repository licence.
2. Review of bundled native code in wheels, the Chromium bundle, Debian packages, base images and
   the Codex closure, including MPL-2.0 and other file-level or source-offer obligations.
3. Assembly of `LICENSES/` texts and a `NOTICE` file, plus any source offers, per final image
   (after T081/T082 produce the images and SBOMs).
4. Legal/redistribution approval; the manifests explicitly state that metadata capture is not
   approval.
