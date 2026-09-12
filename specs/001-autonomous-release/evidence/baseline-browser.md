# T002 — existing browser/Node baseline

Recorded: 2026-09-07 21:06 KST. Status: **baseline measured; not all green**.
This is evidence for the existing development application and synthetic control
prototype, not qualification of the newly designed release.

## Actual results

| Scope | Test files | Tests | Passed | Failed | Skipped/cancelled/todo |
| --- | ---: | ---: | ---: | ---: | ---: |
| `app/tests/*.test.mjs` | 6 | 62 | 62 | 0 | 0/0/0 |
| `control-prototype/tests/*.test.mjs` | 11 | 101 | 99 | 2 | 0/0/0 |
| Full baseline run | 17 | 163 | 161 | 2 | 0/0/0 |
| Isolated failing-case recheck | 2 | 2 | 0 | 2 | 0/0/0 |

The full run exited 1: Node duration **151,389.28725 ms**, `/usr/bin/time`
wall **151.43 s**, user 127.14 s, sys 46.78 s. The recheck exited 1:
Node duration **3,815.2325 ms**, wall **3.98 s**, user 2.22 s, sys 1.10 s.
The recheck is not two additional unique baseline tests. No application code or
test assertions were changed to obtain these results.

### Reproduced failures

1. `control-prototype/tests/browser-review.test.mjs:339`, assertion at line 357:
   `narrow graph selection, details state and dialog focus survive repaint`.
   At 390×900, after selecting the approval node and switching to conversation,
   reopening the graph does not satisfy preservation of the previous
   `scrollLeft` within one pixel. Earlier selected-node visibility assertions
   passed. Assertion result was `false`; the test does not report both numeric
   offsets, so this record does not invent them.
2. `control-prototype/tests/browser.test.mjs:189`, assertion at line 211:
   `graph scroll and expanded state survive repaint while the selected node stays visible`.
   At 720×820, reopening the conversation graph fails the `scrollLeft > 0`
   assertion, whose message is “opening the graph retains the same instance
   scroll position”. Earlier graph state and selected-node visibility checks
   passed.

Both failures recurred with `--test-concurrency=1` and only those test names
selected. This establishes repeatability in this local setup, not a root-cause
diagnosis or a guarantee that all environments behave identically. Preserve
these failures as pre-implementation baseline findings; do not silently mark
the old prototype suite green or attribute them to new runtime code.

## Environment and preflight

- Worktree: `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure`.
- Git HEAD: `f9ea189de00db436d41d01260401a86a951d8925`; dirty and untracked
  pre-existing changes were retained, including the current application,
  control prototype, tests and review output. No checkout/reset/cleanup was run.
- macOS 26.5.1, build 25F80, arm64.
- Node v24.19.0:
  `/Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`.
- Python 3.12.13, explicitly selected existing environment:
  `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python`.
- Existing Playwright 1.62.1:
  `/Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs`.
- Installed Google Chrome 152.0.7977.77, verified by an isolated headless
  `chromium.launch({ channel: 'chrome', headless: true })` and `browser.version()`.
  No package/browser installation was required.

Before running, the two READMEs, all test entry points/output paths and the four
Python fixtures were inspected. The READMEs describe historical implementation
limits; their stale dual-subscription/Claude-approval wording is **not** the
current product authority. The release spec's Claude API-only and Codex
subscription/explicit optional API decision remains authoritative.

## Exact execution and output isolation

The application tests hardcode `app/review-output`; the control review test
supports `CONTROL_REVIEW_OUTPUT_DIR`. To avoid replacing existing screenshots,
both source trees were copied, unchanged, to a new temporary root. This also
fixes the tested snapshot while other agents work in the shared worktree.

Executed from the worktree:

```sh
mktemp -d /tmp/deeptwin-t002-browser.XXXXXX
rsync -a --exclude=review-output/ --exclude=__pycache__/ --exclude='*.pyc' app control-prototype /tmp/deeptwin-t002-browser.djzgWy/
```

The first command returned `/tmp/deeptwin-t002-browser.djzgWy`. Executed from
that directory, using its unchanged test files:

```sh
env CONTROL_PYTHON=/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python CONTROL_PLAYWRIGHT_MODULE=/Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs CONTROL_REVIEW_OUTPUT_DIR=/tmp/deeptwin-t002-browser.djzgWy/control-prototype/review-output PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -p /Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test --test-concurrency=2 --test-reporter=spec --test-reporter-destination=stdout --test-reporter=tap --test-reporter-destination=/tmp/deeptwin-t002-browser.djzgWy/baseline.tap app/tests/*.test.mjs control-prototype/tests/*.test.mjs
```

The failing-case recheck, from the same snapshot:

```sh
env CONTROL_PYTHON=/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python CONTROL_PLAYWRIGHT_MODULE=/Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs CONTROL_REVIEW_OUTPUT_DIR=/tmp/deeptwin-t002-browser.djzgWy/control-prototype/recheck-output PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -p /Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test --test-concurrency=1 --test-name-pattern='narrow graph selection, details state and dialog focus survive repaint|graph scroll and expanded state survive repaint while the selected node stays visible' --test-reporter=spec --test-reporter-destination=stdout --test-reporter=tap --test-reporter-destination=/tmp/deeptwin-t002-browser.djzgWy/recheck.tap control-prototype/tests/browser-review.test.mjs control-prototype/tests/browser.test.mjs
```

### Preservation and evidence hashes

Aggregate tree hashes are SHA-256 of `JSON.stringify` of relative-path/file
SHA-256 pairs sorted by relative-path `localeCompare`, including regular files
and excluding `review-output`, `recheck-output`, `__pycache__` and `*.pyc` for
the source snapshot. Snapshot and original matched before execution:

- 195 files; `0e25025304659d6689470682736297bfb773f72840e2bd488001a7242abf96f5`.
- The same 195 snapshot files and hash remained unchanged after both runs.
- The original worktree gained `app/tests/test_domain_contracts.py` during
  parallel work. A path-by-path comparison found this as the sole difference;
  all 195 baseline files still matched. That new Python test was not part of
  this earlier browser/Node baseline and was not changed by this task.
- All 220 files already in the original two `review-output` directories were
  retained with the same before/after aggregate hash:
  `f8323d8fbfb2c966b51dd55096c51b010da6a237172adeb167bc88e8755746f8`.
- The test snapshot generated 99 new screenshots in its two `review-output`
  directories; aggregate hash:
  `a7b9d61a898c982c45a507e5304829538b1c9be304d79a0ebee0856fed8f6472`.

Raw TAP files remain at the local temporary paths below. They and the new
screenshots were not uploaded/published; `/tmp` is not durable archival storage.
This workspace Markdown record preserves totals, commands and failure details
even if OS temporary cleanup later removes the raw files.

- `/tmp/deeptwin-t002-browser.djzgWy/baseline.tap`:
  `2afd2875e24dc377b7c02bfd3596ee4cc68c72e1ad39af3f04972eae574d23d0`.
- `/tmp/deeptwin-t002-browser.djzgWy/recheck.tap`:
  `def232a3ce030fd53da3d3c8d28707fa7251c16833c833763e30fbe24d54c8a4`.

## Evidence limits

- The app's HTTP/store/session/RPC implementations ran against temporary
  stores. Account/model exchanges used `connection_server.py`,
  `understanding_server.py` and `fake_codex_rpc.py`; no real account login,
  subscription inference or paid API request was initiated by these tests.
  One real-server connection-controls case deliberately makes no account POST.
- Speech uses generated WAV fake media devices and a controlled transcription
  implementation. The real user's microphone was not opened; this is not
  local STT engine accuracy, real speech or Korean-noise qualification.
- Control artifacts, alternatives, hypotheses, graphs and evaluation rounds
  remain synthetic fixtures. Passing their UI checks does not establish real
  graph generation, lens inference, criticism independence, queue improvement
  or actual human version promotion.
- Passing DOM/layout/contrast assertions and producing screenshots is not a
  visual-design review, physical IME/accessibility certification or user UX
  acceptance. These new screenshots were not visually audited in this task.
- Page-level external-request checks passing is not host-wide network egress
  certification. Packaging, signing/notarization, sandbox workers, installer,
  new providers and final-release security were not tested here.
- This task only measured the browser/Node suites requested for T002. Python
  regression results belong to the parent task's separate baseline evidence.
