# Evidence — dependency truth unified in pyproject.toml

- Date: 2026-09-16
- Scope: engineering hygiene, not a canonical task. Three sources of
  dependency truth had drifted: the uv-managed `.venv` (packages installed
  by hand during the resumption session: argon2-cffi, PyNaCl, anthropic,
  LangGraph family), the worktree's `app/requirements.txt` (a partial
  development slice that only gained PyNaCl) and the repository
  `pyproject.toml` (scaffold-era `>=` ranges without argon2/PyNaCl/anthropic).
  The test suite therefore depended on packages no manifest declared.

## What changed

- `pyproject.toml` now lives on the code branch (`codex/ui-structure`) and
  identically on `main`. It is the single source: 13 runtime dependencies
  and 8 dev-group tools, **every one an exact `==` pin** matching the
  versions verified in the development environment (argon2-cffi 25.1.0
  and PyNaCl 1.6.2 as mandated by the resumption plan; anthropic 1.4.0;
  fastapi 0.141.1 / starlette 1.6.0 / uvicorn[standard] 0.52.4; httpx,
  idna, jsonschema, langgraph 1.2.11, langgraph-checkpoint-sqlite 3.1.1,
  pydantic 2.13.5, python-docx 1.2.0). `[tool.uv] package = false` because
  the repository runs as modules and is not built as a distribution.
- Declared entries with no import anywhere in `app/` or `deploy/` were
  dropped: rich, typer, pyyaml/types-pyyaml, pytest-asyncio; tools never
  installed (pip-audit, pre-commit) were dropped too. They can be restored
  in the dev group if a workflow needs them.
- `uv.lock` regenerated (111 packages resolved); `uv sync --frozen` made
  the shared `.venv` exact (134 → 108 distributions). Transitive bumps from
  resolution: pycparser 2.23 → 3.0, urllib3 2.7 → 2.8, tzdata, uuid-utils.
  `pip` itself is no longer in the venv — use `uv pip list`.
- `app/requirements.txt` is now a generated projection of the runtime
  pins with a do-not-edit header.
- New drift lock: `app/tests/test_dependency_manifest_parity.py` (RED first
  on the missing pyproject, then GREEN 4/4) asserts that every runtime pin
  is exact, that `app/requirements.txt` equals the pyproject projection,
  and that the interpreter running the suite has each runtime and dev pin
  installed at exactly that version.
- Untouched: the Linux release locks under `deploy/locks/` (pinned T089
  build inputs) and `deploy/manifests/`.

## Verification

- Parity test 4/4; `ruff check` clean on the new test.
- Full Python regression on the exactly synced environment
  (`LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false DD_TRACE_ENABLED=false
  python -B -m pytest app/tests deploy/tests -q -p no:cacheprovider -rs`):
  **5585 passed, 1 skipped (Linux SO_PEERCRED), 1 warning
  (Starlette/AnyIO deprecation), 369 subtests, 691.62s**, exit 0.
  Previous run before the sync: 5581 passed — the delta is the four new
  parity tests; nothing the sync removed was needed.

## Limits

- macOS development wheels are not Linux release qualification; the
  release image inputs remain governed by `deploy/locks/`.
- `pyproject.toml` on `main` keeps `src/deeptwin` untouched as scaffold;
  with `package = false` it is not installed anywhere.
