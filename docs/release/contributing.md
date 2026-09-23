# Contributing to DeepTwin (draft)

Date: 2026-09-23 · Status: **draft for T084**. This page will not be published until the copyright
owner approves a repository license ([license-recommendation.md](license-recommendation.md)).

## 0. Licensing status: read this first

The repository has **no license file**. Until the copyright owner explicitly approves one:

- the terms under which outside contributions would be accepted are **undecided**;
- no inbound-contribution mechanism (for example a Developer Certificate of Origin sign-off or a
  contributor license agreement) has been chosen;
- nothing in this repository should be treated as available for reuse or redistribution.

Outside contributions should therefore wait until the license and the inbound terms are decided.
The rest of this page describes the engineering workflow those contributions will follow.

## 1. Governing documents

Work follows the project constitution (`.specify/memory/constitution.md`) and the single feature
package `specs/001-autonomous-release/`:

- `spec.md` requirements, `decisions.md` ADRs, `plan.md`, `tasks.md` (the one task index);
- `contracts/*.md` normative contracts (API, operations, runtime, extension ports, …);
- `evidence/*.md` dated records of what was actually built and observed.

A change that alters behavior should reference the task it advances (for example `T052`) and, when
it closes or narrows a claim, add or update an evidence file that states what was observed and what
was **not** shown.

## 2. Honest evidence rules

These come from constitution principle IX and apply to code, tests, docs and evidence:

- Report design review, unit tests, synthetic integration, live provider behavior, real-user
  usability and measured effect **separately**. A passing unit test is not a live or user result.
- Label synthetic, scripted-test-actor evidence as such.
- Never weaken a test to fit a failing implementation.
- Do not claim a feature, platform or qualification that the code and evidence do not show; say
  "not yet provided" or "unverified" instead.
- Preserve existing unrelated changes and user data.

## 3. Development environment

Python 3.12 or newer; dependencies are exact pins in `pyproject.toml` and resolved in `uv.lock`.
The project is run as modules, not installed as a package (`[tool.uv] package = false`).

```sh
uv sync                      # installs runtime + dev groups from uv.lock
uv run pytest app/tests -q   # Python test suite
uv run ruff check            # lint
node --test app/tests/work-export.test.mjs   # an example DOM-level module test
```

Notes:

- `app/requirements.txt` is a **generated projection** of `pyproject.toml`;
  `app/tests/test_dependency_manifest_parity.py` fails on drift. Edit `pyproject.toml`, not the
  projection.
- The Linux release locks under `deploy/locks/` are separate pinned build inputs; changing them is a
  build-input change with its own verifiers (`deploy/locks/verify_*.py`) and tests
  (`deploy/tests/`).
- `app/tests/browser-*.test.mjs` need a real Chromium/Playwright environment supplied through
  environment variables (see `app/README.md`). Without it they fail; that is an environment gap, not
  a pass.
- `app/tests/test_backup.py` needs a verified age 1.3.2 directory in `DEEPTWIN_AGE_RUNTIME_ROOT`;
  without it the binary-dependent cases skip with a stated reason.
- Tests must use only temporary directories they create and must never use real accounts, paid
  calls or real credentials. Live provider runs require a separately recorded, bounded
  authorization.

## 4. Code boundaries contributors must keep

- **Browser is the only product surface.** Do not add an end-user CLI, native wrapper or launcher
  journey. Shell commands in the repository are for development and verification only.
- **No container authority in the product.** Never mount a Docker socket, download code/images at
  runtime, or start/stop containers from the control plane.
- **Closed catalogues.** New routes are added through a JSON descriptor in
  `app/api/route_contributions/` plus an allowlisted factory; new static files through the closed
  catalogue in `app/api/assets.py`; new tools through `register_tool` in `app/runtime/tools.py`.
  See [api-compatibility.md](api-compatibility.md).
- **Server text reaches the DOM through `textContent` or attributes only** (no `innerHTML` with
  server data), matching the existing modules in `app/static/`.
- **No host paths** in wire values, tool arguments or event records; use repository-relative or
  opaque identifiers.
- **Secrets** never appear in logs, errors, events, exports or test snapshots.

## 5. Publishable-content hygiene

Before anything is proposed for publication (T084 scope):

- no developer usernames, workstation or temporary absolute paths, or private source locations in
  source, docs or evidence;
- no user private documents, data, keys or history;
- no automatic public push. Publishing, signing and registry actions require explicit authority
  that ordinary development automation does not have.

A repository-wide scrub has **not** been verified as complete by this draft.

## 6. Commits and review

Keep changes scoped to one task where practical. Shared server and schema files should not be edited
by two parallel efforts at once (`tasks.md`, "Dependencies and parallel work"). Each implementation
change is expected to have tests, a separate specification/quality review and, for UI changes, an
actual browser check.
