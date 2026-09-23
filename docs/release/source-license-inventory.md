# Source license inventory (draft)

Date: 2026-09-23 · Status: **draft for T084; technical inventory, not legal review.** Scope: files
tracked in this repository. Third-party packages resolved at build time are inventoried separately
in [third-party-notices.md](third-party-notices.md).

## 1. Repository-level status

| Item | Present? |
| --- | --- |
| `LICENSE` / `LICENSES/` / `NOTICE` | **no** — intentionally not added; awaiting owner approval ([license-recommendation.md](license-recommendation.md)) |
| `license` field in `pyproject.toml` | no |
| SPDX-License-Identifier headers in tracked source | none found (checked with `git grep`, excluding lock/manifest data) |
| Copyright notices in first-party source | none found in `app/`, `sdk/`, `examples/`, `schemas/`, `deploy/` scripts, prototypes, `evals/`, `docs/` |

Until a license is approved, every first-party file below is unlicensed (all rights reserved).

## 2. First-party source areas

Counts are tracked files at the time of writing (`git ls-files`).

| Area | Files | Content | Intended license | Notes |
| --- | --- | --- | --- | --- |
| `app/` | 686 | control plane, workers, browser shell, tests, fixtures | undecided | includes test fixtures; confirm none contain real user data |
| `schemas/` | 115 | generated JSON Schemas | undecided | generated from `app/` code |
| `deploy/` (scripts, Compose, bootstrap, tests, recipes) | part of 76 | operator and build-input tooling | undecided | see §3 for third-party files inside `deploy/` |
| `sdk/python/` | 4 | historical extension-kit checkpoint | undecided | not the installable SDK |
| `examples/extensions/` | 7 | inert examples | as declared per example? | manifests declare `Apache-2.0` and `CC0-1.0`; unreviewed |
| `control-prototype/` | 318 | synthetic control prototype, generated PDFs/SVGs, review screenshots | undecided | generated PDFs may embed font subsets whose licenses are unverified |
| `prototype/`, `evals/`, `.agents/` | 14 | earlier prototype, eval material, agent skill | undecided | not reviewed in detail |
| `packaging/macos/` | 9 | pre-ADR-009 native experiment | undecided | historical; publication optional |
| `specs/`, `docs/`, `.specify/`, `README.md` | ~306 | specification, contracts, evidence, design notes | undecided (a documentation license could differ) | `docs/lenses/` cites external philosophical sources; rights to any quoted text unverified |

## 3. Third-party files stored in the repository

These are upstream files kept for verification or notices. They keep their upstream terms and must
not be relicensed with the repository.

| Path | What it is | Upstream license (as recorded) |
| --- | --- | --- |
| `deploy/locks/licenses/*.txt` | upstream license texts (CTranslate2, LangSmith, Node.js, OpenAI Whisper, Silero, sqlite-vec, tokenizers) | the licenses they contain |
| `deploy/locks/licenses/age-1.3.2/` | age, edwards25519 and Go license texts | BSD-3-Clause |
| `deploy/locks/codex-0.153.4/Cargo.lock.*` | upstream Codex lockfiles | not recorded for the files themselves (Codex crates declare Apache-2.0) |
| `deploy/locks/nodejs/` | Node.js release signature and release-key keyring | not recorded |
| `deploy/locks/moby-default-seccomp-61eaf326.json` | upstream Moby default seccomp profile (reference) | not recorded |
| `deploy/locks/requirements-*.lock`, `uv.lock`, `deploy/manifests/*.json` | lock and manifest data describing third-party artifacts | data about third-party packages; no license statement |

## 4. Scrub status (publishable content)

T084 also requires removing developer usernames, absolute workstation/temp paths and private source
locations from publishable source, docs and evidence. This draft did **not** perform or verify that
scrub. The files under `docs/release/` were written with repository-relative paths only.

## 5. Next steps

1. Owner approves a license (and a documentation license if different).
2. Confirm ownership of all first-party areas above and decide which historical areas to publish.
3. Add license files and SPDX headers; run `reuse lint` (pinned in the dev group) to check coverage.
4. Verify the scrub and that fixtures and evidence contain no user private data or keys.
