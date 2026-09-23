# T087 slice — core boundary test (2026-09-23)

Status: **the named boundary test landed; T087 stays open.** Still open:
- the extension routes (`app/api/extension_routes.py`, `extensions-v1.json`)
- client black-box parity
- the OCI tool fixture through the broker
- the binding, rollback and environment reconciliation cases

## What landed

`app/tests/test_extension_architecture.py` walks the transitive import graph statically from
every module under `app/domain`, `app/services`, `app/runtime`, `app/operations` and
`app/extensions`. The walk:

- follows `import` and `from … import`, including relative imports and those under
  `TYPE_CHECKING` or inside functions
- follows literal `importlib.import_module` / `__import__` targets
- passes through any other `app` module it reaches

No path may reach `app.api`, `app.static`, `app.server`, FastAPI, Starlette, Jinja or Uvicorn. A
dynamic import whose target is not a string literal is itself a violation, since it could
bypass the check.

## Observed

**8 passed**:

- the real tree has **no violation**
- the walk covers more than 100 core modules
- a synthetic tree proves the walker catches each form: a direct relative import, an indirect
  import through a non-core `app` module, a function-local import, a literal dynamic import, a
  `TYPE_CHECKING` import, and an unresolvable dynamic import
