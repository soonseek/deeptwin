# T087-A1 — executable port schema generation and trusted-context semantic validation

Date: 2026-09-12
Status: implemented checkpoint with focused and full regression evidence; **T087 remains open**

## Exact scope

This checkpoint closes the executable slice of ADR-014's core-owned port schemas: deterministic
generation of the 44 `schemas/v1/extensions/ports/<port>/{config,request,result,error}.schema.json`
artifacts from `contracts/extension-ports.md`, and a fail-closed semantic validator that refuses to
validate config/request/result/error payloads without trusted durable-store context. It does not
implement durable extension state, routes, staging, dispatch, the SDK/client packages, or any other
open T087 arm.

The work was started in the Codex sessions ending 2026-09-09 01:54 KST and finished in this
session. The Codex side landed the validator's trusted-context requirement, the
`uniqueItems`/`x-deeptwin-unique-binding-tuple`/`x-deeptwin-unique-by` artifact-input guards and the
fail-closed/duplicate/refinement/URI/decoy-table tests, but stopped before (a) regenerating the
checked-in schema files from the changed generator and (b) giving the five pre-existing semantic
tests the trusted context the validator now requires. This session completed both.

## Changes in this session

- Regenerated all 44 checked-in port schema files with `write_port_schemas`, restoring byte
  determinism between generator output and `schemas/v1/extensions/ports/` (the 11 request schemas
  gained the artifact-input uniqueness annotations).
- Added `_config_context` and `_request_context` fixture helpers to
  `app/tests/test_extension_port_schema_generation.py`. `_config_context` supplies the exact
  qualification/binding-revision/binding-head records for one validated config.
  `_request_context` builds the full trusted request context (validated config with generous
  resource limits, accepted-at instant, authenticated actor, active purpose, grant/artifact/
  selector/input records, and the profile source record: frozen turn/run projection, export
  snapshot, prepared delivery, or ToolDefinition with the built-in artifact-input contract). It
  also gives every named operation-input ref a distinct digest so each ref resolves to its own
  record, resealing the idempotency key afterwards.
- Updated the five semantic tests to validate the happy path under the full trusted context first
  and then re-assert each targeted rejection: refinement ordering, manifest-frozen extension error
  codes with exact request lineage, binding-slot digest/nesting, frozen-source-list mismatch,
  hidden artifact refs in tool arguments, built-in tool profile widening, and export exact-list
  mismatch.
- Collapsed one nested `if` in the generator's transmit check (ruff SIM102); no behavior change.

The happy-path assertions are load-bearing: they prove the negative cases fail on the targeted
check rather than on an incomplete context.

## Verification

```text
python -m pytest -q app/tests/test_extension_port_schema_generation.py
28 passed

python -m pytest -q app/tests deploy/tests   (full shared regression, run twice)
run 1: 2,921 passed, 1 failed, 2 skipped, 369 subtests passed
run 2: 2,922 passed, 0 failed, 2 skipped, 369 subtests passed
Both runs carry the 1 known Starlette/AnyIO deprecation warning. Run 1's single failure is an
unrelated pre-existing flake: test_domain_permissions.py::
test_concurrent_persistent_registration_preserves_both_descriptors raised
UnsafePath("Unsafe SQLite sidecar") from app/domain/store.py:403 when two writers raced over a
freshly created -wal/-shm sidecar. It passes 5/5 in isolation and 2/2 whole-file; recorded as a
pre-existing DomainStore concurrency defect, not caused or fixed by this checkpoint.

ruff check app/extensions/port_schema_generator.py app/tests/test_extension_port_schema_generation.py
PASS

git diff --check
PASS
```

The shared totals include concurrent T018/T025/T087 work present in the worktree; they are
regression evidence, not completion evidence for those tasks.

## Frozen content identities (SHA-256)

```text
15a2330554950f36b96af1a207b36f238119cd78bff9bd4f1260e2eaf589a0e7  app/extensions/port_schema_generator.py
e0174a09936e78e304757b3eb180875007a810a5259364bfba6df3eff5d824b2  app/extensions/port_contracts.py
24cba747f173de57859c59d54c92b99adf7701dbe570b16b4d6dcbd2251d2aba  app/tests/test_extension_port_schema_generation.py
1654f85585d86c69a9a939dced54d758e3b6399a7c637668c741ed9feb16ce74  concatenated 44 schemas/v1/extensions/ports/**/*.schema.json (sorted paths)
```

## Not claimed

No durable installation/qualification/binding persistence, no extension routes or settings UI, no
operator staging, no runtime dispatch, no SDK/HTTP-client packages, and no independent adversarial
re-audit of this checkpoint yet. The trusted-context record shapes used by the fixtures encode the
validator's current expectations; the durable-store implementation must supply the same shapes or
this suite must be revised with it.
