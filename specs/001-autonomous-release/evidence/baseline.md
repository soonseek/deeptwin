# T002 baseline before autonomous implementation

2026-09-07. Actual worktree `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure`,
branch `codex/ui-structure`, HEAD `f9ea189de00db436d41d01260401a86a951d8925`.
`git rev-parse --git-dir --git-common-dir --show-superproject-working-tree` confirmed this
existing linked worktree, common repository `/Users/soonseekyang/Documents/Deeptwin/.git`,
and no superproject. No checkout, staging, commit, push or user-source reset occurred.

`baseline-source-manifest.json` fingerprints 108 pre-existing modified/untracked source,
test/eval and documentation files. These files remain user/prior-work owned. Generated
review-output and unrelated temporary fixture paths are excluded. Browser baseline used a
separate byte-identical source snapshot so existing screenshots could not be overwritten.

## Actual commands/results

- Initial attempted command: `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m
  pytest app/tests evals/deeptwin/tests -q`. Exit4, no tests ran: the second directory does
  not yet exist. This was a mistaken command path, not a tested harness or code failure.
- Corrected: `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests -q`.
  Exit0, **729 passed, 1 existing Starlette/AnyIO deprecation warning in 10.28s**. This run
  predates the new `test_domain_contracts.py`/domain code and is an actual rerun, not the
  historical count. Real filesystem/SQLite/local process behavior is tested with controlled
  provider boundaries; no live inference or account login.
- Node/browser: **163 tests, 161 pass, 2 fail, no skips**, wall151.43s. App tests62/62;
  prototype99/101. Exact commands/environment and preservation hashes are in
  [baseline-browser.md](baseline-browser.md). Both failures reproduced independently with
  concurrency1; not dismissed as parallel test noise.
- `git diff --check` and Spec Kit prerequisite checks passed after V0 status reconciliation.

## Known baseline defects, not waived

`control-prototype/tests/browser-review.test.mjs:357` and `browser.test.mjs:211` expose graph
horizontal scroll restoration failure after repaint/mode reopen. Preserve this evidence and
cover it in product graph/UI integration (T037/T048/T078); do not weaken assertions or claim
all baseline suites green. T002 is complete because baseline measurement/preservation was its
scope, not because every existing test passed.

Current domain implementation runs are separate from these baseline measurements. This
evidence is not full-product functionality, real provider, native package or DeepTwin effect
qualification. Source snapshots and generated fixture records are not real user alternatives.
