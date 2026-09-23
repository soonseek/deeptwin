# T084 slice — publishable-tree path scrub (2026-09-23)

Status: **workstation paths scrubbed from 40 tracked documents; T084 stays open.** Still
open: license approval by the copyright owner, the Compose gaps, and the one pinned lens file
described below.

## What changed

A developer's absolute workstation paths were replaced with neutral placeholders, longest
prefix first:

| Workstation path | Placeholder |
| --- | --- |
| the repository worktree | `<repo>` |
| other worktrees | `<worktrees>/` |
| the workspace | `<workspace>` |
| the local Node runtime | `<node-runtime>` |
| the reference paper in Downloads | `<owner-provided reference PDF, not in the repository>` |
| the visualization cache | `<local-visualization-cache>` |
| the Playwright cache | `<playwright-browser-cache>` |
| Application Support | `<local-application-support>` |
| the remaining home paths | `<home>` |

The files are plans, specs, UI reviews, the two prototype READMEs, provider contracts and
research, the resumption plan, and 17 evidence files.

After the scrub, `git grep` finds no developer username and no `/Users/…`, `/home/<user>/`,
`/tmp/claude…` or `/private/var/folders` path outside tests. The test-owned synthetic canaries
(`/Users/secret`, `/Users/private/…` in `test_runtime_ledger.py` and
`test_server_api_v1.py`) are kept on purpose: they exist to prove such paths are redacted. The
remaining e-mail addresses are third-party license texts, a Sigstore signer identity and
`example.invalid` fixtures.

## Not changed, and why

- **`docs/lenses/source-map.md` still names the reference PDF by its workstation path.** The
  reviewed lens bundle pins this file's exact bytes (`test_lens_registry.py`: "bytes do not
  match the reviewed bundle"). Rewriting it would silently change a reviewed input. It needs a
  lens-bundle re-review that adopts the scrubbed bytes, so it stays open.
- **Historical review-input manifests keep the pre-scrub hashes:**
  - `baseline-source-manifest.json` (four plan and UI files)
  - `adr014-review-input-manifest*.md` (`provider-research.md` and
    `extension-spi-pure-contracts.md`)

  They record what was reviewed at the time, and those exact bytes remain recoverable from git
  history. No test verifies them. A T075 refresh of source hashes must use the current bytes
  and cite this scrub as the supersession.

## Observed

The tests that read docs and specs pass after the scrub: `test_design_generation.py`,
`test_extension_port_schema_generation.py`, `test_lens_registry.py` and
`test_build_input_lock_verifier.py`, **184 passed**.
