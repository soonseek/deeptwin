# Evidence — Task 24 step (c2): v3 storage constants, consume codec and prepare-api-v3

- Date: 2026-09-18
- Task: Task 24 redraft step (c), second half (c2): the pure v3 values —
  `contracts/deployment-receipt-journal-v3.md` §2 (literal DDL), §6 (consume input, frozen 200
  reply, prepare-api-v3), §7 (constants and `parse_consume`), §8 (frozen checksums). Precedent:
  `prepare_v2_schema_exports.py`, `prepare_v2_contracts.py`, journal v2 §6/§9.

## Frozen identities

```
33cc6379d5e7f309ad732d99983c2446c6a68e1135c16bdfddb741b2be7dd1e9  app/deployment/prepare_storage.py
3849f818f64c4818df25b0debb8a5cf56e5a6b5e2d7529885eccb70130b62dec  app/deployment/prepare_v3_schema_exports.py
7cdcc55f7cab4290ad0c8d3df7e91b1e397c848de5c511e253cb4519e2de5619  app/deployment/prepare_v3_contracts.py
b45315c53737d8f6861a9d05f967d149a0db7c148babb045cdb5fd0ee6c690d8  schemas/v1/deployment/prepare-api-v3.schema.json
ba1cd46e555e56368ca3f7de2cb9745eea77967e9117d484c817baa7396dabca  app/tests/test_deployment_prepare_v3_contracts.py
```

## What was built

- `app/deployment/prepare_storage.py`: appended `DDL_V3` (thirteen statements — seven imported
  byte-identical from `DDL`/`DDL_V2`, four changed, two new, exactly the contract's fenced text),
  `CHECKSUM_V3` (computed from the literal list, equal to the frozen
  `ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457`), `TABLES_V3`, `CAPS_V3`
  (installations 16, installation_heads 16) and `NULLABLE_V3`. Constants only: `_layout`,
  `digest`, `insert`, `advance`, `verify` and `install` are untouched (they arrive with the
  coordinated storage step).
- `app/deployment/prepare_v3_schema_exports.py` (new): `consume_input_schema()`
  (`expected_revision` exactly 2), `installation_schema()` (`installation_id`, `extension_id`,
  hex64 `installation_digest`, `revision:1`), `consume_receipt_schema()` (the frozen 200 body),
  `read_schema()` (every v2 arm with `installation:null` plus the accepted3 arm: receipt
  `consumed_success`, installation present, no consumption publication state, no cancellation
  state), `api_schema()`, `exported_schemas()` (`prepare-api-v3` only, separately named URN) and
  `write_schemas()`; the artifact `schemas/v1/deployment/prepare-api-v3.schema.json` is
  generated. The consume input has the import input's wire shape (its route pins the revision),
  so the artifact's input alternative for both routes is the import-shaped input — listing both
  would make every consume body match two `oneOf` alternatives.
- `app/deployment/prepare_v3_contracts.py` (new): `parse_consume(request_id, value)` over the
  shared route-input helper and the closed `DeploymentPrepareError` family.
- v1/v2 artifacts and the v2 modules are unchanged.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (no MUST). The reviewer re-extracted the six fenced statements and
confirmed them byte-identical to the code, recomputed C3, checked the new foreign keys against
the real `domain_blobs`/`domain_records` keys, confirmed `prepare_storage` behaviour is unchanged
(`digest` still refuses the new suffixes, nothing enumerates the constants), confirmed the eight
pre-existing deployment artifacts unchanged and the v3 artifact byte-identical to its writer, and
traced every `parse_consume` refusal to its layer. Closures:

1. SHOULD — the error arms hand-rolled `affected_refs` and so differed textually from the v2
   envelope → the shared `array({}, 0, 0)` helper; artifact regenerated (the v2 `uniqueItems`
   form is back in all arms).
2. SHOULD — the artifact did not state why the consume input is not a separate alternative →
   the `$comment` now says the consume route's body has the receipt-import input shape with
   `expected_revision` fixed to 2 at the route (the code comment stays as well).
3. SHOULD — the CHECK-matrix refusals could also be key collisions, so the test would survive a
   deleted CHECK arm → `match="CHECK constraint failed"` on every refused row.
4. NIT — `NULLABLE_V3 == NULLABLE_V2` was tautological → the two new tables are now read back
   through `PRAGMA table_info` and every column is notnull or a primary-key column.
5. NIT — `ruff format` differences (cosmetic; `ruff check` is the gate), `SHAPE_V3`/`COLUMNS_V3`
   deferred to the coordinated storage step (noted there), v1 artifact bytes covered by the v1
   suite (and verified unchanged by the reviewer).

## Verification

- TDD: RED retained — `AttributeError: module 'app.deployment.prepare_storage' has no attribute
  'DDL_V3'` and `ModuleNotFoundError: No module named 'app.deployment.prepare_v3_contracts'`;
  GREEN after one design correction found by the artifact test (the consume input matched two
  `oneOf` alternatives) and one test correction (the CHECK-matrix cases could also fail on foreign
  keys, so the matrix is exercised with foreign keys off and the admitted rows inserted).
- Covering: **274 passed** — v3 contracts 15, v2 schema exports, v2 contracts, prepare storage,
  receipt schema exports, prepare contracts, lineage contracts (the 68-artifact byte-pin still
  holds: the v3 artifact is a new file). Ruff clean on every new/changed file
  (`prepare_storage.py` had no findings before or after).
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- Pure values only: no layout dispatch, migration, insertion, service, observer, consume
  transaction, route, event registration or lifecycle change ((d)–(f) and the coordinated
  storage step remain); schema validity grants no acceptance, installation or head authority;
  no GUI.
