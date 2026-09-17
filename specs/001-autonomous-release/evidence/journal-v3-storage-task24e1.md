# Evidence — Task 24 step (e1): v3 storage layout and the v2 → v3 migration

- Date: 2026-09-18
- Task: Task 24 redraft step (e), first half (e1): the coordinated storage step —
  `contracts/deployment-receipt-journal-v3.md` §2 (row hashing, capacities), §3 (migration
  algorithm, deferred-FK reliance and its proofs), §4 (installations/heads bijections), §7
  (storage/records API additions), §8 (frozen checksums). Precedent: `_rebuild_v1_as_v2`,
  journal v2 §3, `test_deployment_receipt_migration.py`.

## Frozen identities

```
3586c73a4ae9cf320f9f8424c1e0a35c5ab75ade8f9be8703972691d103772c7  app/deployment/prepare_storage.py
2829876e34f67e3edd47cb523df015de1ff4b4ee722b92b0e106bc0ea5b3ec26  app/deployment/prepare_records.py
26153653ae73d4b6e3d09213690733869d8e9c20abcb3fe3ab00c2846447e1fa  app/tests/test_deployment_journal_v3_migration.py
2c23afe8d9e3fd9beffe8c7ddb29fe9abac581df220937f27f68f3f4baf856eb  app/tests/test_deployment_receipt_migration.py
e3528e4362fa89d41f8f99cb5432b58f254364573d4e6a40d20f87282f4194d4  app/tests/test_deployment_receipt_import.py
ee1172a0ad6fad9f2229a05fc89adf5a9e47376edfd1c2c476837d6646e3dfe3  app/tests/test_deployment_prepare.py
```

## What was built

- `app/deployment/prepare_storage.py`: `SHAPE_V3`/`COLUMNS_V3` observed from `DDL_V3`; the
  frozen `_V3` layout (migrations `(1,C1),(2,C2),(3,C3)`); `_layout` dispatches the three exact
  stored shapes; `digest` accepts the two v3 suffixes under `deployment-prepare-storage-v3` (the
  six v1 and four v2 suffixes keep their namespaces, so no existing row hash changes); `_row`
  validates `installation_id` as a UUID and `evidence_sha256`/`installation_anchor_digest` as
  hex64 (`extension_id` grammar already applied by name); `_rebuild_v2_as_v3(db)` — the
  mechanical rebuild: exact v2 and FK-on precondition, bounded snapshots of migrations (2),
  lifecycle (48), commands (48) and consumptions (16) ordered by primary key, unchanged
  snapshots of the seven untouched tables, `defer_foreign_keys=ON` verified, per-row deletes
  (consumptions, commands, lifecycle, migrations, each in reverse snapshot order), drops in that
  order, the six changed/new statements created by individual `execute` calls, restores with
  explicit column lists, `(3,C3)`, restored-equality and unchanged-equality proofs. The populated
  children (heads, outbox, receipts, consumed_outbox) stay in place and re-resolve their parents
  by name; the deferred counter is settled only by the restores.
- `app/deployment/prepare_records.py`: `install` runs v1 → v2 → v3 in the same writer with the
  whole verifier between steps (forward-only; a v3 startup is write-free); the absent-schema
  guard also refuses a pre-existing `extension_installation` anchor; `verify` adds the anchor
  dimension preflight for that kind, the "no installation anchor before v3" guard, the
  heads ↔ installations equality (revision 1, same anchor digest, same count) and the
  anchors ↔ installations bijection keyed by `installation_id`. Per-item installation loading and
  the accepted3 lifecycle rules arrive with the consume transaction (e2); no v3 writer can yet
  produce an installation row.
- `advance` is unchanged: `installation_heads` has no CAS in v3 (absent-only head).

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES. The reviewer reproduced the deferred-FK reliance on SQLite 3.53.1
(child rows survive the parent delete/drop/create with `foreign_key_check` non-empty; the
restores settle the counter; a commit without them is refused and the store's `finally`
rolls back without a leaked writer), confirmed the six created statements, the delete/drop/
restore orders, the untouched-table proof's total order and caps, the fail-closed heads ↔
installations logic, the unchanged v1/v2 row hashes, the exactness of the fault-injection
count (`2·old_rows + 11`) and that already-v3 startup is write-free. Closures:

1. MUST — the v1 → v2 migration test still asserted a v2 landing (the reviewer saw the state
   before the adaptation) → it asserts the forward-only v3 landing (three rows, `SHAPE_V3`).
2. SHOULD — the new test file was unformatted → `ruff format` applied.
3. SHOULD — deferring `_load_installation` to (e2) left a window where crafted installation
   rows with a foreign consumption and a bypassed anchor would pass the bijections unread
   (not producible by any current writer) → explicit closure: a v3 verify refuses any
   installation or head row until (e2) replaces the line with the loader. No isolating test:
   the crafted journal needs a rejected2 and a cancelled3 history and is exactly what (e2)'s
   loader tests will construct.
4. NIT — commands were deleted in reversed primary-key order while §3 says descending
   `lifecycle_revision` → aligned (immaterial under deferred keys).
5. NIT — the consumed-journal migration proved `records.install` only → the ordinary
   constructor's acceptance of the migrated journal is asserted as well; the orphan-anchor
   negative keeps its validator bypass (the bijection compares envelope tuples only).

## Verification

- TDD: RED retained — the ordinary constructor left a v2 journal at `{(1,C1),(2,C2)}` with the
  v2 shape (`assert migrations == [(1,C1),(2,C2),(3,C3)]` failed); GREEN with no test-side
  correction beyond ruff's `with`-statement merges.
- Tests (7): the ordinary constructor upgrades empty and mixed sixteen-request v2 histories
  without sources (exact rows/records/events preserved, installations empty, prepare/cancel/read
  served, a second construction write-free); a fault after every rebuild write (deletes,
  drops, creates, restores, the `(3,C3)` insert) and a refused commit roll back to exact v2 with
  `foreign_key_check` empty; a commit without the restores is refused by SQLite ("FOREIGN KEY
  constraint failed") while heads/outbox survive the drop/recreate; already-v3 startup requires
  exact `(3,C3)` and the v1 installer, the v1-only foundation helper and the v1 row wrapper
  reject v3; the v3 suffixes hash under their own namespace; an installation anchor outside the
  index denies verification; a v2 journal held at v2 with an imported failed receipt (consumption
  + pending consumed outbox) migrates through `records.install` with its children in place and
  the journal loaded (the contract's deferred-FK reliance, proved on the real store).
- Covering (receipt migration, prepare storage, receipt import, prepare, receipt journal
  integrity and reconciliation, v3 contracts): **161 passed, 4 failed** on the first run; the
  four were pre-existing tests that the accepted contract necessarily changes, adapted as
  tests and re-run green (12 passed on the affected cases; the whole covering set is re-run in
  the full regression):
  1. the v1 → v2 migration test asserted the final shape is v2 → the constructor now
     continues forward-only to v3 in the same writer (three migration rows, `SHAPE_V3`).
  2. the receipt import "managed_kind" final-writer recheck fabricated an
     `extension_installation` row → under v3 that is an integrity failure of this journal, so
     the guard is proved with an `extension_qualification` row (a managed kind the journal does
     not own).
  3. the prepare guard test's `extension_installation` case → the closed denial is now the
     journal integrity failure (`unavailable`) before the guard; the guard itself remains proved
     by the qualification and binding kinds.
  Ruff clean on every changed file.
- After the closures: migration (v3 and v2 suites) and storage **46 passed**; Ruff check and format clean on the new test.
- Full regression (`app/tests deploy/tests`, watchdog 1500 s): **6047 passed, 3 failed, 2 skipped**;
  the three were two more pre-existing v2-landing assertions, adapted as tests (the absent-schema
  install routing lands on `SHAPE_V3`; the cold HTTP upgrade shows three migration rows) and
  re-run green with their whole modules (`test_deployment_prepare_integrity.py`,
  `test_deployment_receipt_api.py`); no `app/` code changed after the full run. Their hashes:

  ```
  425133a473a6e247a0ababd36378c91355c90aa7b0cea282ba332a217a1e1a5b  app/tests/test_deployment_prepare_integrity.py
  08a01cdc2c42c1f59fb7b5a8a59d6e4b68c5f7da8b276c4a007f153ad338edb0  app/tests/test_deployment_receipt_api.py
  ```
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- Storage and verifier only: no consume transaction, lifecycle transition, installation writer,
  route, event registration or GUI; `installation_heads` gets no CAS; nothing observes a worker;
  the live container/socket/worker run stays a Docker/colima host gate.
