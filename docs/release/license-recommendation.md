# Repository license recommendation (for owner decision)

Date: 2026-09-23 · Status: **recommendation only. No license has been approved, and no license
file has been added.**

## Decision status

- The copyright owner has **not** approved a repository license.
- Accordingly, this change adds **no** `LICENSE`, `LICENSES/`, `NOTICE`, SPDX headers or license
  metadata to source files or `pyproject.toml`.
- No license file will be added, and nothing will be published, pushed publicly, tagged as a release
  or uploaded to a registry, until the copyright owner gives **explicit approval** of a specific
  license (T084, FR-001/032, constitution "Execution Boundaries").
- Until then the repository remains "all rights reserved" by default and is **not** an open-source
  release, whatever the README's goal statement says.

This document is engineering input to that decision. It is not legal advice; the owner may want
counsel to review it, particularly §4.

## 1. What the license must support

From the specification and ADR-014:

1. A self-hostable web framework that third parties can deploy, modify and run.
2. A reusable core with separately installable distributions (extension-author SDK, HTTP/OpenAPI
   client) that third parties embed in their own code.
3. Third-party extensions with **their own** licenses, running as separate OCI services connected
   over a broker protocol.
4. Redistribution of container images that bundle many third-party components (Python wheels, Go
   binaries, Node.js, Chromium, Debian packages, a speech model, the Codex runner).
5. Compatibility with the licenses already in the dependency inventory
   ([third-party-notices.md](third-party-notices.md)), which as recorded are predominantly
   permissive (MIT, BSD, Apache-2.0, ISC, PSF-2.0) with some MPL-2.0 file-level copyleft.

## 2. Options considered

| Option | Fit | Main trade-off |
| --- | --- | --- |
| **Apache-2.0** | Permissive; explicit patent grant and patent-retaliation clause; NOTICE convention matches the NOTICE work T084 already requires; compatible with the recorded dependency licenses | Allows proprietary hosted forks without sharing changes |
| MIT | Simplest permissive option; widest compatibility | No explicit patent grant; no NOTICE convention |
| MPL-2.0 | File-level copyleft: modified DeepTwin files stay open, larger works may be proprietary | More obligations for integrators of the SDK/client |
| AGPL-3.0-only | Network copyleft: hosted modified versions must offer source | Strongly discourages embedding the SDK/client and some extension ecosystems; heavier compliance for self-hosters |
| Dual core/SDK licensing (e.g. AGPL core + Apache SDK/client) | Keeps hosted forks open while letting integrators embed the SDK/client | Two licenses to maintain and explain; contribution terms must cover both |

## 3. Recommendation

**Recommended default: Apache License 2.0 for the whole repository**, including the core, the
future `deeptwin_ext` SDK and `deeptwin_client` distributions, operator artifacts and documentation,
with a REUSE-style layout (`LICENSES/Apache-2.0.txt`, SPDX headers, a
`NOTICE` file for DeepTwin and bundled third-party notices).

Reasons:

- It matches requirement 2 and 3 best: integrators and extension authors can use the SDK and client
  under any license of their own.
- The explicit patent grant is useful for a framework intended for reuse.
- Its NOTICE mechanism fits the per-image NOTICE/source-offer closure T084 already requires.
- The development toolchain already pins `reuse==6.2.0`, which can check a REUSE-style layout.

**If the owner's priority is that hosted modified versions must stay open**, the recommended
alternative is AGPL-3.0-only for the core with Apache-2.0 for `deeptwin_ext` and
`deeptwin_client`. This needs a clear written boundary for what counts as the SDK/client.

The choice is the owner's. Either path is reversible only before first publication in practice, so
it should be settled first.

## 4. Points the owner (or counsel) should confirm

1. **Copyright ownership.** Confirm who owns the existing code, documentation and evidence, and
   whether any part was contributed by others or generated with tools whose terms matter.
2. **Inbound contribution terms.** Choose a mechanism (e.g. DCO sign-off, or a CLA if relicensing
   flexibility is wanted). Dual licensing generally needs a CLA.
3. **Trademark.** Apache-2.0 grants no trademark rights; decide how the "DeepTwin" name may be used.
4. **Bundled components.** Review MPL-2.0 files (e.g. `certifi`, parts of `orjson` and `tqdm`),
   the Chromium and Debian notices, the Codex closure and the speech model before shipping images.
5. **Example files.** `examples/extensions/*/manifest.json` declare `Apache-2.0` and `CC0-1.0` for
   themselves; confirm or change these once the repository license is chosen.
6. **Historical material.** Decide whether `packaging/macos/`, `prototype/`, `control-prototype/`
   and large evidence files are published at all.

## 5. What happens after approval (not done now)

Only after the owner's explicit approval of a named license:

1. Add `LICENSE` / `LICENSES/<id>.txt` and SPDX headers; add `license` metadata to
   `pyproject.toml` and to the future SDK/client packages.
2. Assemble `NOTICE` and third-party license texts and source offers per final image
   (after T081/T082).
3. Finish the publishable-content scrub (usernames, absolute paths, private locations, user data).
4. Record the approval (who, when, which license) in `specs/001-autonomous-release/evidence/`.
5. Publish only with the separately required publication authority; no automatic public push.

See also [source-license-inventory.md](source-license-inventory.md).
