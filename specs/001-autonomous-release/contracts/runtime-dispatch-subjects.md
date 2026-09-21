# Runtime tagged subjects and explicit offline migration

Implementation contract for the existing pre-environment model-call prerequisite, not a new
dispatcher, provider authority, product UI or permission to migrate user storage.
Depends on independent acceptance of Task31; not implementation authorization before its
own bounded plan review. Source scope and tests will be in Task32 of resumption-plan.md.

## Outcome and versions

The same RuntimeLedger can represent an explicit dispatch subject without inventing a node
for work understanding. This slice installs/validates relational shape only. All public
attempt decoding/admission/permits/sends remain node_execution-only. Generation rows cannot
be made executable by a database flag or caller-created subject. Future canonical job/call/
consent integration requires a separate accepted contract.

Keep exact v1 DDL and original migration digest:
`b761957cfb9c21a63f928ba5c7d173ba7a4804d0dc72b240fdade0bc860ad118`.
Fresh empty runtime schemas initialize v2; existing exact v1 remains supported for node-only
operation, without automatic migration. Existing v2 is verified, not reinitialized.
Unknown/partial/unversioned schemas, unexpected runtime-prefixed objects or triggers fail
closed at ordinary startup before initialization changes, in the offline operation, and at
the existing real dispatch/permit/clock-recovery authority checks. Preserve budget and other
components' migration rows. Do not turn every descriptive read into a new authority boundary.
The three version-dependent live representation branches (node context, node creation, attempt
reservation) may use a private transaction-local discriminator that verifies the exact pinned
migration chain and exact version-specific attempt/subject shapes. It is not cached authority,
an existence-only guess or permission to dispatch. It preserves existing synthetic rollback
fault tests and readback while unrelated triggers remain categorically denied by full startup,
offline and actual dispatch checks. Unknown/partial/mismatched representations still deny.

The v2 target is the original18statement tuple with the subject table inserted immediately
before the attempts table and that table replaced below. Other statements/indexes unchanged.
Target tuple SHA256(join with newline, no final newline):
`3131be5d54e0ffdfcf980353d04b81428f27e64711f4762993e63915deeda255`.
Use this as the appended ledger version2 digest; retain the original version1 row. Freshv2
also records both exact rows. No historical v1 serialized object or content hash is rewritten.
Semicolons below are Markdown SQL presentation only, not bytes in the pinned tuple. Derive
expected sqlite_master shape by compiling the exact tuple in an owned in-memory SQLite
connection and reading its schema, then use the existing narrow whitespace/case normalization.
Do not compare a semicolon-bearing presentation string directly to SQLite's stored CREATE.
Both fresh-v2 and actual migrated-v2 must equal that same compiled target shape.

```sql
CREATE TABLE runtime_dispatch_subjects (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL, node_execution_id TEXT, generation_kind TEXT, generation_version INTEGER, generation_sha256 TEXT, PRIMARY KEY(vault_id,subject_kind,subject_id), FOREIGN KEY(vault_id,node_execution_id) REFERENCES runtime_node_executions(vault_id,id), FOREIGN KEY(vault_id,generation_kind,subject_id,generation_version,generation_sha256) REFERENCES domain_records(vault_id,kind,id,version,sha256), CHECK((subject_kind='node_execution' AND node_execution_id IS NOT NULL AND node_execution_id=subject_id AND generation_kind IS NULL AND generation_version IS NULL AND generation_sha256 IS NULL) OR (subject_kind='generation_call' AND node_execution_id IS NULL AND generation_kind IS NOT NULL AND generation_kind='generation_call' AND generation_version IS NOT NULL AND typeof(generation_version)='integer' AND generation_version>0 AND generation_sha256 IS NOT NULL AND length(generation_sha256)=64 AND generation_sha256 NOT GLOB '*[^0-9a-f]*')));
CREATE TABLE runtime_attempts (vault_id TEXT NOT NULL, id TEXT NOT NULL, execution_id TEXT, subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, idempotency_key TEXT NOT NULL, reservation_id TEXT NOT NULL, spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, dispatch_gate TEXT NOT NULL, send_finality TEXT NOT NULL, cancel_state TEXT NOT NULL, recovery_state TEXT NOT NULL, terminal_outcome TEXT, revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), lease_owner BLOB NOT NULL, lease_owner_digest TEXT NOT NULL, lease_fence INTEGER NOT NULL, lease_expires_at_ms INTEGER NOT NULL, dispatch_blocked_at_ms INTEGER, send_intent_at_ms INTEGER, local_transport_closed_at_ms INTEGER, owned_process_exit INTEGER, remote_terminal_observed TEXT NOT NULL, usage_finality TEXT NOT NULL, accepted_observation_id TEXT, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id), UNIQUE(vault_id,execution_id,attempt_no), UNIQUE(vault_id,subject_kind,subject_id,attempt_no), UNIQUE(vault_id,idempotency_key), FOREIGN KEY(vault_id,execution_id) REFERENCES runtime_node_executions(vault_id,id), FOREIGN KEY(vault_id,subject_kind,subject_id) REFERENCES runtime_dispatch_subjects(vault_id,subject_kind,subject_id), CHECK((subject_kind='node_execution' AND execution_id IS NOT NULL AND execution_id=subject_id) OR (subject_kind='generation_call' AND execution_id IS NULL)));
```

Preserve old execution-attempt uniqueness and index as well as new subject uniqueness.
The generation arm's explicit IS NOT NULL constraints are required: SQL CHECK NULL is not
acceptance. FK references complete vault/kind/id/version/hash; an ID alone is insufficient.
Backfill one node subject per execution, even with zero attempts. Every migrated attempt's
subject_kind=node_execution and subject_id=execution_id; generation count remains zero.
V2 node creation and subject creation share the original transaction. Reservation adds
relational columns only; public command/spec/snapshot/receipt/capture bytes remain v1.
Validate v2 relationship at each existing dispatch context boundary before authority use.

## Code boundaries and shared validation

Keep versioned DDL/shape verification in one focused runtime module, reusable by ordinary
ledger startup and the offline operation. Preserve existing compatibility exports, notably
RUNTIME_MIGRATION_SHA256 as the v1 digest and existing private test references where practical.
No second dispatcher, budget ledger or authority registry. BudgetBook transaction assertions
remain FK-on and unchanged. The offline operation never calls Store/DomainStore/RuntimeLedger
constructors because those perform ordinary startup writes.

Reuse current pure snapshot/ref/parent validation for exact existing run/execution/attempt
bindings through a private read-only verifier. It receives the checked transaction and
expected vault only; it must not expose permit issuance, reconciliation, caller-supplied
authority context, callbacks or public activation. Share actual validation logic rather than
copying a weaker subset. Semantic accepted-observation links and checkpoint bound-attempt/
execution refs must remain coherent, including links not declared as SQL FKs.
This offline verifier covers canonical record bodies/digests, SQL reference/blob metadata,
original-send/capture bindings and checkpoint/accepted-result relationships. Extract and share
those pure checks. Physical blob verification and permission-service reconstruction remain in
ordinary startup, not this transaction-only verifier. Migration does not certify physical
capture-byte availability; no invocation of DomainStore._check_graph may silently add unbounded
filesystem reads or require a fabricated live repository/permission service.

## Offline boundary and paths

Deployment-only internal function, not an HTTP route or end-user CLI requirement:

```python
migrate_runtime_ledger_v1_to_v2(
    data_directory, *, expected_uid, expected_gid,
    expected_vault_id, expected_v1_digest
) -> dict
```

The expected digest must equal the pinned constant, not caller-selected acceptance. Validate
canonical nonnil vault UUID and exact nonnegative integer UID/GID. No provider/user credentials
or root secrets are parameters. No host/process stopping, deployment modification, secret
maintenance or actual user-store execution is authorized in development.
The operation process effective UID/GID must equal the configured expected UID/GID, preventing
privileged invocation from creating SQLite sidecars under a different owner. This is not an
instruction to change host identity or permissions during development.

Operator must externally stop serving, workers and direct database users before invoking the
offline deployment operation. There is no quiesced=True parameter or browser assertion that
proves this. Reuse existing owner-auth.lock inode exclusively, existing-lock-only: no creation,
replacement, unlink or permission repair. Participating supported server takes that same lock
before Store/domain/runtime construction. Hold it until every migration/verification connection
is closed. Direct old Store users and hostile sameUID processes do not honor it; neither this
lock nor WAL BEGIN EXCLUSIVE proves they cannot return. Actual deployment isolation/offline
qualification remains separate. Do not claim arbitrary legacy writers are fenced.

Require an existing configured-user-owned mode0700 directory and existing intake.sqlite3
single-link regular0600 file; traverse paths component-wise no-follow. Retain directory/database/
lock descriptors and recheck inode/path/modes/owners before opening, before transaction and
before commit/reopen. Existing -wal/-shm/-journal must be same-owner nonlinked regular0600.
No create/chmod/reset/repair/checkpoint deletion or setting WAL mode as migration side effect.
Open mode=rw only, verify exactly main database pathname and held/visible identity. Stdlib
SQLite pathname/VFS sameUID race remains explicitly unqualified; no native nofollow claim.

Use FK ON, trusted_schema OFF, synchronous FULL, fullfsync ON, and verify existing WAL mode.
Never disable foreign_keys, attach another database, or weaken normal storage connections.
One monotonic30second operation deadline starts before lock acquisition and covers scans,
SQL and postcommit verification. Serving lock acquisition is nonblocking; SQLite busy waits
are capped at min(5seconds, remaining deadline). Progress handler interrupts SQL at deadline;
Python loops check it too. No per-stage deadline reset or automatic retry-to-success.

## Bounded snapshot and exact transaction

Maximum100000 total rows and64MiB of scalar payload across retained in-memory migration
snapshots. Count bytes as actual bytes length; strings UTF8 byte length; NULL0; int/float8.
Also bound each attempt spec/owner and history JSON with existing validators. Exceeding caps
or deadline refuses before parent deletion. These are offline-operation limits, not new
normal-runtime retention/pruning limits. Never spill snapshot payload to SQLTEMP/disk/logs.
Enforce counts and cumulative scalar-byte limits in bounded SQL sizing scans before fetching
large TEXT/BLOB values into Python; do not call unbounded fetchall then check size. All retained
referenced metadata consumes the same aggregate allowance. Compare restored rows by streaming
against the one retained snapshot, not an uncharged second full copy. SQL sizing and row loops
remain under the original deadline; database text encoding must be the existing UTF-8 profile.

Snapshot all runtime ledger tables in deterministic primary-key/sequence order and the
domain record/ref/blob metadata needed by referenced captures/semantics; do not snapshot
unrelated owner/password/credential stores. Retain original SQLite values, including BLOBs;
no JSON reserialization or content regeneration. Preserve untouched child rows, sqlite_sequence
entries, immutable domain capture records and referenced blob identities. No event, lease,
clock, session, cancel, budget, receipt, capture or checkpoint normalization/reconciliation.
Preserve original runtime_attempts hidden SQLite rowids explicitly through rebuild: existing
public reads may use rowid-derived ordering for tied timestamps. Retain and compare each rowid
inside the single bounded snapshot, charging its eight scalar bytes to the shared allowance.
Do not change public ordering queries or re-sort old histories to hide migration differences.
Acceptance includes interleaved runs with reversed attempt IDs and equal timestamps, checking
identical public readback before and after committed migration.

After serving exclusion and hardened connection:
1. BEGIN EXCLUSIVE; validate exact v1/v2 runtime DDL/migration chain, vault binding, required
   domain shape, FK integrity and relevant history before mutation. Exactv2 is verify-only.
2. Enumerate actual inbound foreign_key_list across database tables. Expected inbound attempt
   FKs are runtime_attempt_refs, runtime_result_observations, runtime_tool_calls and
   runtime_attempt_journal, all(vault_id,attempt_id)→(vault_id,id), NO ACTION update/delete.
   Reject additional/self/cascade/set-null/restrict actions and all triggers before deletion.
   Constraints cannot merely be inferred from Python declarations.
3. Finish bounded snapshots/semantic checks; create/backfill subject table from every valid
   execution. Set defer_foreign_keys=ON and verify it; foreign_keys remains1.
4. Explicit DELETE FROM runtime_attempts; verify zero rows. DROP TABLE runtime_attempts,
   then execute the frozen v2 CREATE TABLE runtime_attempts directly under its original name.
   No replacement-table rename. Insert every original column plus the derived node-subject
   values with explicit column order. Recreate the original runtime_attempts_execution index.
5. Compare all original columns/rows in both directions; compare preserved child/history/
   sequences and semantic references, check exact v2DDL and every new subject relation.
   All generation rows remain absent. Whole-database foreign_key_check must be empty.
6. Append(ledger,2,target_digest) in the same transaction. COMMIT while FK enforcement and
   deferred checks remain ON. Do not disable deferred checks to force commit.
7. Close connection, reopen a fresh hardened FK-on mode=rw connection under the same serving
   lock, verify exactv2/schema/history/bindings, close, then release exclusion and return.

The runtime DDL itself is exact; unrelated registered domain/budget/deployment objects are not
prohibited merely because they coexist. Unexpected runtime objects or inbound actions do deny.

## Outcomes and failure

Successful result exact fields:
schema_version='runtime-ledger-migration-v1', vault_id, from_version(1or2), to_version=2,
state='migrated' or'already_current', v1_sha256, v2_sha256, attempts, executions.
Counts are nonnegative integers; no payload/SQL/path/credentials in results/errors.

Typed fixed errors: invalid_request, unavailable, busy, maintenance_required, capacity_exceeded,
deadline_exceeded, outcome_unknown. No user-controlled error reflection.
Beforecommit failure rolls back; do not repair or fall back. Once COMMIT is attempted, a commit
exception or failed postcommit verification is outcome_unknown, not assumed rollback. Preserve
files. Reinvoke offline verification to distinguish exactv1/v2; never blindly rebuild. An exactv2
repeat is verify-only with already_current. A rollback error also becomes outcome_unknown.

## Acceptance before implementation acceptance

- Empty and populated actual v1→v2 **COMMIT** with real attempt children, authenticated response
  capture, checkpoint, receipts, revisions and snapshots; exact old bytes and later normal
  v2 node execution/send/replay/capture/settlement preserved.
- Fail after each create/backfill/delete/drop/create/insert/index/registry stage: exact v1
  logical recovery and children unchanged. Deliberately omit one restoration with actual
  child reference: COMMIT must fail. Keep rename-based failing control in a bounded test.
- Wrong/unknown versions/digests, partial schemas, changedconstraints, inboundCASCADE/triggers,
  corrupt refs/digests/semanticpointers, foreignvault and new generation rows failclosed.
- Real owned-process ServingLock exclusion and directSQLitewriter contention; unsafe/missing/
  replacedlock/DB/sidecars; close/timeout cleanup; no new file or permission repair on refusal.
- Fixed row/byte/deadline bounds, no secret/source payload in diagnostics, outcome_unknown after
  committed-but-unverified simulation, exactv2repeat, freshFKON and subsequentconstraintfailure.
- Old v1-only ledger schema verifier refusesv2; distinguish this from native oldbinary or
  arbitrary standaloneStore fencing. No liveprovider/callercontext/generationadmission.
- Existing v1 regressions and representative freshv2 node paths; source/schema digest fixture
  matches exact19statements. Final scoped cover, independent spec/quality review. No realDBuse.

This is structure and safe offline migration code, not qualified deployment or a complete
understanding/graph journey. T023/T042 and full semantic/provider/user stories remain open.
