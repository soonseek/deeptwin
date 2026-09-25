# Source license inventory (draft)

Date: 2026-09-23 · Updated: 2026-09-25 · Status: **draft for T084; technical inventory, not legal
review.** Scope: files tracked in this repository. Third-party packages resolved at build time are
inventoried separately in [third-party-notices.md](third-party-notices.md).

## 1. Repository-level status

| Item | Present? |
| --- | --- |
| `LICENSE` / `LICENSES/` / `NOTICE` | **yes** — Apache-2.0, approved by the owner on 2026-09-24 ([license-recommendation.md](license-recommendation.md)); `LICENSES/Apache-2.0.txt` is the same canonical text; `LICENSES/LicenseRef-Upstream-Terms.txt` explains the upstream-terms annotation (§3) |
| `license` field in `pyproject.toml` | `license = "Apache-2.0"`, `license-files = ["LICENSE", "NOTICE"]` |
| Per-file licence and copyright information | **yes, through `REUSE.toml`** (REUSE 3.3): every tracked file defaults to `SPDX-License-Identifier = "Apache-2.0"` and `SPDX-FileCopyrightText = "2026 The DeepTwin Authors"`; the upstream files in §3 override this with `LicenseRef-Upstream-Terms` and `NOASSERTION`. `reuse lint` is compliant and guarded by `app/tests/test_reuse_compliance.py` |
| SPDX headers inside individual source files | none; coverage comes from `REUSE.toml` annotations, not in-file headers |

The copyright line is the owner's chosen collective attribution; who actually owns each first-party
area (§2) has not been separately confirmed ([license-recommendation.md](license-recommendation.md)
§4.1).

## 2. First-party source areas

Counts are tracked files on 2026-09-25 (`git ls-files`, 1,914 files in total).

| Area | Files | Content | Licence (via `REUSE.toml`) | Notes |
| --- | --- | --- | --- | --- |
| `app/` | 918 | control plane, workers, operator tools, browser shell, tests, fixtures | Apache-2.0 | includes test fixtures; confirm none contain real user data |
| `schemas/` | 119 | generated JSON Schemas | Apache-2.0 | generated from `app/` code |
| `deploy/` (scripts, Compose, bootstrap, tests, recipes, locks, manifests) | 76 | operator and build-input tooling | Apache-2.0 except §3 | see §3 for third-party files inside `deploy/` |
| `sdk/python/` | 4 | historical extension-kit checkpoint | Apache-2.0 | not the installable SDK |
| `examples/extensions/` | 7 | inert examples | Apache-2.0 for the repository; the manifests also declare `Apache-2.0` and `CC0-1.0` for themselves | the example declarations are unreviewed |
| `control-prototype/` | 318 | synthetic control prototype, generated PDFs/SVGs, review screenshots | Apache-2.0 | generated PDFs may embed font subsets whose licences are unverified |
| `prototype/`, `evals/`, `.agents/` | 96 | earlier prototype, eval harness/verifiers/qualification designs, agent skill | Apache-2.0 | not reviewed in detail |
| `packaging/macos/` | 9 | pre-ADR-009 native experiment | Apache-2.0 | historical; publication optional |
| `specs/`, `docs/`, `.specify/`, `README.md` | 358 | specification, contracts, evidence, design notes, release docs | Apache-2.0 (no separate documentation licence was chosen) | `docs/lenses/` cites external philosophical sources; rights to any text quoted there are unverified |
| Root files (`LICENSE`, `LICENSES/`, `NOTICE`, `REUSE.toml`, `pyproject.toml`, `uv.lock`, `.gitignore`, `.dockerignore`) | 9 | licence, packaging and lock metadata | as declared by `REUSE.toml` | `uv.lock` is data about third-party packages |

## 3. Third-party files stored in the repository

These are upstream files kept for verification or notices. They keep their upstream terms and must
not be relicensed with the repository. `REUSE.toml` annotates them `LicenseRef-Upstream-Terms`.

| Path | What it is | Upstream license (as recorded) |
| --- | --- | --- |
| `deploy/locks/licenses/**` | upstream license texts (CTranslate2, LangSmith, Node.js, OpenAI Whisper, Silero, sqlite-vec, tokenizers; age, edwards25519 and Go under `age-1.3.2/`) | the licenses they contain |
| `deploy/locks/codex-*/Cargo.lock.*` | upstream Codex lockfiles | not recorded for the files themselves (Codex crates declare Apache-2.0) |
| `deploy/locks/nodejs/**` | Node.js release signature and release-key keyring | not recorded |
| `deploy/locks/moby-default-seccomp-*.json` | upstream Moby default seccomp profile (reference) | not recorded |
| `deploy/locks/requirements-*.lock`, `uv.lock`, `deploy/manifests/*.json` | lock and manifest data describing third-party artifacts | data about third-party packages; annotated Apache-2.0 as DeepTwin-authored data, which does not relicense the packages they describe |

## 4. Scrub status (publishable content)

T084 also requires removing developer usernames, absolute workstation/temp paths and private source
locations from publishable source, docs and evidence. A scrub of 40 tracked documents was done on
2026-09-23 (`evidence/publishable-scrub-t084-2026-09-23.md`); test-owned canary paths are kept on
purpose. Still open: `docs/lenses/source-map.md` names a workstation path but its bytes are pinned by
the reviewed lens bundle, so changing it needs a lens-bundle re-review; and files added since the
scrub have not been re-checked. The files under `docs/release/` use repository-relative paths only.

## 5. Next steps

1. Done 2026-09-24: the owner approved Apache-2.0 for the repository (no separate documentation
   licence).
2. Confirm ownership of all first-party areas above and decide which historical areas to publish.
3. Done 2026-09-25: `REUSE.toml` licence coverage for every tracked file, upstream files annotated
   `LicenseRef-Upstream-Terms`; `reuse lint` passes, guarded by `app/tests/test_reuse_compliance.py`.
4. Verify rights to text quoted in `docs/lenses/`.
5. Re-run the scrub over content added since 2026-09-23 and re-review the pinned lens source file;
   verify that fixtures and evidence contain no user private data or keys.
6. Per-image third-party notices and source offers with the T081 images.
