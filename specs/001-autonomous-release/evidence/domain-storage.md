# T007/T008 additive storage and legacy-CAS migration evidence

2026-09-08 · authoritative worktree:
`<repo>`.

Status: the bounded storage scope named by T008 is implemented. The existing SQLite store
remains the sole logical-state owner; legacy identifiers, revisions, events, metadata text and
file BLOB bytes are preserved. A file read changes from the legacy BLOB to verified CAS only
after a validated stable-ID mapping row commits. This does **not** claim completion of authorization,
cross-module command transactions, backup/restore, native sandboxing, or installed-device
power-loss qualification. Those remain T010, T014/T016, T018, T070–T072 and T083.

The design authority is [data-model §2](../data-model.md#2-storage-ownership-and-atomicity).
No real user vault was opened or migrated.

## Changed scope

- [app/domain/store.py](../../../app/domain/store.py): versioned domain schema, immutable
  record/ref indexes, purpose-partitioned CAS, bounded legacy migration and link verification.
- [app/storage.py](../../../app/storage.py): stable legacy `read_file` switches to CAS when,
  and only when, a validated v2 mapping exists; mapped corruption never falls back to BLOB.
- [app/tests/test_domain_storage.py](../../../app/tests/test_domain_storage.py): real temporary
  SQLite/filesystem and fault-injection coverage.
- This evidence and [the review record](domain-storage-review.md).

No dependency, provider/model call, network access, credential/account access, commit, or user
database access occurred. Existing unrelated dirty work was not rewritten.

## Additive schema and ownership

`domain_migrations` records two exact DDL digests:

1. v1: `domain_vault`, immutable `domain_records`, exact `domain_edges`, registered
   `domain_blobs`, and `domain_record_blobs`.
2. v2: an exact `(files.id, files.work_id)` identity index plus `domain_legacy_files`, whose
   foreign keys bind stable legacy identity and the registered `(vault, purpose, SHA-256)` CAS
   object. Its only accepted active source is `read_source='cas'`.

A fresh store creates v1+v2 and both ledger rows in one SQLite transaction. An exact v1 store
is checked before it upgrades to v2; injected v2 DDL failure rolls back the entire upgrade and
leaves the v1 ledger/schema and legacy rows intact. Rewritten/missing indexes, wrong/missing or
unknown ledger rows, partial schemas, and additional `domain_*` tables/indexes/views/triggers
fail closed. The migration is additive: no code path deletes or rewrites `works`, `files`,
`revisions`, or `events`.

SQLite is the only writable logical truth. CAS files are immutable byte objects registered by
digest. The old file BLOB intentionally remains a compatibility/recovery copy after a mapping
switch, but normal `Store.read_file(work_id, file_id)` no longer reads or returns it for that
mapped identity. There is no editable YAML/Markdown/JSON authority added here.

## Internal interfaces and invariants

| Interface | Bounded integrity behavior |
|---|---|
| `DomainStore(existing_store, max_blob_bytes=...)` | Uses the existing store's exact `intake.sqlite3`; applies/verifies additive migrations, but neither initializes authority nor enables dispatch. |
| `initialize_vault()` | Host-only one-time local root creation. Four roots and their exact indexes commit together; ordinary/imported records cannot mint or replace bootstrap roots. |
| `put/get` | Canonical immutable record bytes, exact identity/version/hash, indexed refs/blobs, same-vault resolution, cycle and transitive integrity verification. |
| `put_blob/read_blob` | Purpose-bound, content-addressed exact bytes; staging, descriptor fsync, bounded hash verification, rename, parent-directory fsync, re-verification, then DB registration. |
| `migrate_legacy_file(work_id, file_id)` | Snapshot exact metadata and BLOB, verify size/hash, seal/register CAS, recheck the legacy snapshot, then commit one mapping. Exact repeat is idempotent; wrong work identity is not. |
| `migrate_legacy_files(max_items=20)` | Resumable page with item and aggregate-byte limits. Every file switches in its own completed transaction; a later page resumes remaining stable IDs. |
| `legacy_file_links()` | Bounded mapping projection that revalidates metadata digest, identity, timestamp, CAS binding and exact bytes. |
| `Store.read_file(work_id, file_id)` | One DB snapshot selects either unmigrated BLOB or mapping. Any present/declared v2 schema is fully revalidated. A mapped read validates identity, metadata digest, timestamp and CAS bytes; no corruption fallback exists. |

Repository methods enforce integrity, not actor permission. T009/T010 and the authenticated
command layer must authorize purpose and caller before using them. A hash, root or actor-shaped
record is not permission.

## Seal, switch, crash and retry ordering

For each legacy file:

1. Read legacy identity/metadata and `length(data)` in a SQLite snapshot; refuse a missing,
   oversized or metadata/hash-mismatching object before a switch.
2. Write a unique 0600 `.stage-*` file under the fixed-purpose 0700 CAS hierarchy.
3. `fsync` the descriptor, reread under a byte ceiling, verify exact size and SHA-256, rename to
   the digest name, `fsync` the parent directory, and reverify the sealed object.
4. Register the exact CAS digest/size in SQLite only after sealing. A complete object left by a
   prior failed registration may be explicitly reverified and registered; corrupt content is
   never overwritten as “repair.”
5. In a later write transaction, reread the unchanged legacy snapshot, verify the registered
   CAS object, and insert the stable-ID mapping. Only that commit changes subsequent reads.

An injected seal failure leaves the old BLOB readable and no mapping. An injected mapping
commit failure may leave a complete registered CAS orphan, but no mapping and therefore no
read switch. A mapped CAS object that is missing or corrupt produces `StorageIntegrityError`;
the preserved legacy BLOB is not used as a silent fallback. No old, corrupt, staged, orphaned,
or temporarily unreferenced byte is automatically deleted.

This ordering prevents a DB mapping from naming an unsealed object in the tested cooperative
writer/crash boundaries. It is not an exactly-once remote protocol or a universal disk-power
loss guarantee.

## Relationship, tamper, path and resource review

- Bodies, nested `EntityRef`/`BlobRef` envelopes, and their edge/blob indexes must agree
  exactly. Missing, foreign, cyclic, hash-mismatched or index-mismatched content is rejected.
- The ledger does not excuse the applied schema: exact `sqlite_master` definitions and the
  complete reserved `domain_*` object set are checked. A partial v2 store cannot make a legacy
  reader silently accept bytes.
- Missing root rows with residual records, edges, blobs, record-blob indexes **or v2 legacy
  mappings** are corruption, never an empty vault eligible for a new genesis.
- Existing CAS content is opened no-follow/nonblocking and checked as a 0600 regular file with
  one link beneath current-user-owned directories. Directory components are no-follow 0700 directories;
  database and SQLite sidecars are checked as private regular single-link files.
- Default per-object CAS verification is 16 MiB, configurable only within 1 byte–64 MiB.
  Legacy upload remains separately capped at 10 MiB. Graph traversal is capped at 4,096 nodes,
  depth 256 and 64 MiB of distinct transitive blob bytes. Migration pages cap 1,000 items and
  64 MiB; link projection caps 4,096 links and 64 MiB of verified blobs. Limits refuse work;
  they do not truncate bytes or relabel a valid larger object as corrupt.
- Cooperating writers are serialized by a bounded process lock and SQLite `BEGIN IMMEDIATE`;
  SQLite busy waits are five seconds. This is not a total filesystem-I/O deadline.

The path checks are defense in depth for this internal repository, not an OS sandbox against a
hostile same-UID process racing SQLite pathname open or directly rewriting both database and
files. The legacy `Store` constructor's existing chmod behavior is not represented as hostile
same-user isolation. Native worker qualification remains T018/T083.

## Failure-first development and self-review dispositions

The inherited T007 baseline had 57 focused passes after its independent review found and fixed
four defects: new-record graph-bound asymmetry, FIFO blocking, residual v1 data being mistaken
for a fresh vault, and reader ceilings being labelled corruption.

T008 began with ten migration/read-switch tests failing because v2 and migration interfaces did
not exist. The first implementation reached 67 passes. A deliberate second self-review added
failing reproductions and fixed:

- wrong-work mapping tamper/fallback and wrong-work idempotent lookup;
- migration-ledger and exact applied-schema tamper, including case/name-independent triggers
  and indexes attached to governed tables;
- invalid mapping timestamps and partial-v2 legacy reads;
- total-byte bounds for migration pages, transitive graph blobs and mapping projection;
- residual v2 mapping rows being mistaken for a fresh vault;
- vault-directory replacement both during SQLite open and after `BEGIN`/before commit;
- non-BLOB SQLite values reaching `bytes(integer)` before a size/type refusal;
- reclassification of legacy mappings away from their fixed `operational` purpose;
- exception scoping so verification-limit failures remain distinct from corruption.

The final focused observation is **84/84 passed**. The final related observation is
**898/898 passed** across domain storage, legacy storage/ingestion, domain contracts, schema
exports and domain events.

A first whole-`app` attempt stopped during collection because a concurrent adapter file had not
yet landed, and a later run exposed one pre-v2 runtime-ledger test expectation. After those
separately owned files converged, the final whole-`app` observation was **1,882/1,882 passed**
with the existing Starlette/AnyIO deprecation warning.

A separate final read-only audit reproduced four additional closure defects (schema-name
bypass, two vault-path swap windows, unbounded non-BLOB materialization and purpose
reclassification), reviewed their failure-first fixes, and independently observed **84 focused
passes** plus **9/9 targeted audit regressions**. It reported no remaining T008 blocker. See
[domain-storage-review.md](domain-storage-review.md).

Commands used with the unchanged temporary locked interpreter:

```sh
PYTHONDONTWRITEBYTECODE=1 /private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q app/tests/test_domain_storage.py
PYTHONDONTWRITEBYTECODE=1 /private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q app/tests/test_domain_storage.py app/tests/test_storage.py app/tests/test_ingestion.py app/tests/test_domain_contracts.py app/tests/test_domain_schema_exports.py app/tests/test_domain_events.py
PYTHONDONTWRITEBYTECODE=1 /private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q app
PYTHONDONTWRITEBYTECODE=1 /private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q app --ignore=app/tests/test_codex_api_mode.py
PYTHONDONTWRITEBYTECODE=1 /private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m py_compile app/storage.py app/domain/store.py app/tests/test_domain_storage.py
git diff --check
```

Final source identities:

| File | SHA-256 |
|---|---|
| `app/domain/store.py` | `33a0469b36b72eae9f7b916b7831588d2579e378526448e1c97ea6636a38aa87` |
| `app/storage.py` | `c5321f9009dcb74ac3fb75bdaeaaf18a07e672e46e778215aff2136b2397cf4f` |
| `app/tests/test_domain_storage.py` | `912ccf619744350a5034dbd6e01fade2fbaf0388aab6e6e55b21bf24cf7b1b22` |

## Explicitly remaining outside T008

- Persistent grant/descriptor authorization and compiler projections: T010.
- One shared authenticated command transaction spanning permission/domain, budget reservation,
  dispatch intent/result reconciliation and events: T014/T016. T008 supplies the same SQLite
  storage substrate but does not claim this cross-module unit of work.
- Import/export reconciliation, backup-before-migration, restore to a disabled staging vault,
  rollback/recovery UI and later release migrations: T070–T072.
- Native helper isolation and real packaged crash/power-loss/filesystem qualification: T018,
  T079 and T083.
