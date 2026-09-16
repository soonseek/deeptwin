# Deployment receipt journal v2 — actual owner import and one-use non-success

Normative implementation contract for the next stage after accepted prepare-journal v1 and receipt
wire/source/dependency prerequisites. This extends the same actual service, not the overall release
scope or user journey. No implemented migration, signing job, image qualification or installation
is claimed by writing this contract. The earlier scratch SQL/interface reports are superseded here.
Canonical source§7 governs K-gated positive projections and independent cancellation.

## 1. Scope and actual interfaces

Only first-installation stage requests. Succeeded → receipt_pending2; failed/unknown → rejected2
plus one-use consumption. No accepted state, installation, qualification, binding, worker effect,
reservation release, receipt replacement, runtime trust or slot-absence reacquisition.
Bind exact startup DomainStore and PersistentOwnerAuthority sharing `owner._domain is domain`;
reuse the exact prepared-journal service/registry binding and exact retained U/J/K classes.
Use `with _writer(), domain._connection(write=True) as db`, `_assert_write_transaction(db)`,
`owner.authenticate_bound(request.session,db=db)`, actual request method/host/origin/CSRF checks,
`_read_roots`, `_check_graph`, `_load`, `_blob_bytes`, and `_put_in_transaction`. Public `put_blob`
preseals outside the final writer. Do not introduce callbacks, nested public reads or a new store.
`AuthenticatedRequest`/`AuthenticatedSession` are the shared request_identity types; the real boundary
must have called owner.authenticate_request (including raw-token CSRF verification). A fabricated
csrf_verified flag, actor, copied session or parsed receipt is not independent admission evidence.
EntityRef remains `{kind,id,version,sha256}`; BlobRef remains `{vault_id,purpose,sha256,size}`.
Add only deployment_receipt and deployment_receipt_consumption kinds/content validators and exports.
Keep api.commands/RootCommandTransaction APIs unchanged: use the deployment private replay table,
not the standalone command journal's separately committed executing intent.

## 2. Literal changed/new v2 DDL

Keep deployment_prepare_control and deployment_prepare_requests DDL/columns byte-for-byte v1.
Replace the other five definitions with the following; add the four new tables. Checksum policy is
SHA256(canonical_json(full ordered v2 DDL list)), matching v1. Full order (deployment_prepare_ prefix):
migrations, control, requests, lifecycle, heads, commands, outbox, receipt_sources, receipts,
consumptions, consumed_outbox. Include unchanged v1 control/requests statements in that eleven-item
list; execute only the nine recreated/new statements below. Freeze exact strings/checksum, excluding
Markdown fences; never infer them from sqlite_schema. Preserve the original migration1 checksum.

```sql
CREATE TABLE deployment_prepare_migrations (
 version INTEGER PRIMARY KEY CHECK(version IN (1,2)),
 checksum TEXT NOT NULL CHECK(length(checksum)=64)
);
CREATE TABLE deployment_prepare_lifecycle (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 3),
 previous_revision INTEGER, previous_hash TEXT,
 state TEXT NOT NULL CHECK(state IN ('prepared','cancelled','expired','receipt_pending','rejected')),
 transitioned_ms INTEGER NOT NULL CHECK(transitioned_ms BETWEEN 0 AND 253402300799999),
 actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 1024), command_id TEXT,
 event_id TEXT NOT NULL UNIQUE REFERENCES api_event_envelopes(event_id),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(request_id,revision), UNIQUE(request_id,revision,hash), UNIQUE(command_id),
 FOREIGN KEY(request_id,previous_revision,previous_hash)
  REFERENCES deployment_prepare_lifecycle(request_id,revision,hash),
 FOREIGN KEY(command_id) REFERENCES deployment_prepare_commands(command_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((revision=1 AND state='prepared' AND previous_revision IS NULL AND previous_hash IS NULL AND command_id IS NOT NULL)
  OR (revision=2 AND state IN ('cancelled','expired','receipt_pending','rejected') AND previous_revision IS NOT NULL AND previous_revision=1 AND previous_hash IS NOT NULL)
  OR (revision=3 AND state IN ('cancelled','expired') AND previous_revision IS NOT NULL AND previous_revision=2 AND previous_hash IS NOT NULL)),
 CHECK((state='expired' AND command_id IS NULL) OR (state<>'expired' AND command_id IS NOT NULL))
);
CREATE TABLE deployment_prepare_heads (
 request_id TEXT PRIMARY KEY REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 3),
 lifecycle_hash TEXT NOT NULL CHECK(length(lifecycle_hash)=64), hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(request_id,revision,lifecycle_hash) REFERENCES deployment_prepare_lifecycle(request_id,revision,hash)
);
CREATE TABLE deployment_prepare_commands (
 command_id TEXT PRIMARY KEY CHECK(length(command_id)=36),
 namespace TEXT NOT NULL CHECK(namespace IN ('deployment-prepare-v1','deployment-cancel-v1','deployment-cancel-v2','deployment-receipt-import-v1')),
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 1024),
 input_json TEXT NOT NULL CHECK(length(input_json) BETWEEN 2 AND 4096),
 input_digest TEXT NOT NULL CHECK(length(input_digest)=64),
 http_status INTEGER NOT NULL CHECK(http_status IN (200,201)),
 receipt_json TEXT NOT NULL CHECK(length(receipt_json) BETWEEN 2 AND 8192),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision BETWEEN 1 AND 3),
 hash TEXT NOT NULL CHECK(length(hash)=64), UNIQUE(namespace,request_id),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 CHECK((namespace='deployment-prepare-v1' AND http_status=201 AND lifecycle_revision=1)
  OR (namespace='deployment-cancel-v1' AND http_status=200 AND lifecycle_revision=2)
  OR (namespace='deployment-cancel-v2' AND http_status=200 AND lifecycle_revision=3)
  OR (namespace='deployment-receipt-import-v1' AND http_status=200 AND lifecycle_revision=2))
);
CREATE TABLE deployment_prepare_outbox (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 role TEXT NOT NULL CHECK(role IN ('request','cancel')),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision BETWEEN 1 AND 3),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 payload_size INTEGER NOT NULL CHECK(payload_size BETWEEN 1 AND 65536),
 state TEXT NOT NULL CHECK(state IN ('pending','published','suppressed')),
 published_ms INTEGER CHECK(published_ms BETWEEN 0 AND 253402300799999),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2), hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(request_id,role),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 CHECK((role='request' AND lifecycle_revision=1)
  OR (role='cancel' AND lifecycle_revision IN (2,3) AND state<>'suppressed')),
 CHECK((state='pending' AND revision=1 AND published_ms IS NULL)
  OR (state='published' AND revision=2 AND published_ms IS NOT NULL)
  OR (state='suppressed' AND revision=2 AND published_ms IS NULL))
);
CREATE TABLE deployment_prepare_receipt_sources (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1) REFERENCES deployment_prepare_control(singleton),
 vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id),
 purpose TEXT NOT NULL CHECK(purpose='operational'),
 trust_sha256 TEXT NOT NULL CHECK(length(trust_sha256)=64),
 trust_size INTEGER NOT NULL CHECK(trust_size BETWEEN 1 AND 16384),
 ingress_sha256 TEXT NOT NULL CHECK(length(ingress_sha256)=64),
 ingress_size INTEGER NOT NULL CHECK(ingress_size BETWEEN 1 AND 8192),
 consumption_exchange_sha256 TEXT NOT NULL CHECK(length(consumption_exchange_sha256)=64),
 consumption_exchange_size INTEGER NOT NULL CHECK(consumption_exchange_size BETWEEN 1 AND 8192),
 identity_json TEXT NOT NULL CHECK(length(identity_json) BETWEEN 2 AND 8192),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(vault_id,purpose,trust_sha256) REFERENCES domain_blobs(vault_id,purpose,sha256),
 FOREIGN KEY(vault_id,purpose,ingress_sha256) REFERENCES domain_blobs(vault_id,purpose,sha256),
 FOREIGN KEY(vault_id,purpose,consumption_exchange_sha256) REFERENCES domain_blobs(vault_id,purpose,sha256)
);
CREATE TABLE deployment_prepare_receipts (
 request_id TEXT PRIMARY KEY REFERENCES deployment_prepare_requests(request_id),
 vault_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind='deployment_receipt'),
 version INTEGER NOT NULL CHECK(version=1), anchor_digest TEXT NOT NULL CHECK(length(anchor_digest)=64),
 receipt_sha256 TEXT NOT NULL UNIQUE CHECK(length(receipt_sha256)=64),
 receipt_size INTEGER NOT NULL CHECK(receipt_size BETWEEN 1 AND 16384),
 outcome TEXT NOT NULL CHECK(outcome IN ('succeeded','failed','unknown')),
 source_singleton INTEGER NOT NULL CHECK(source_singleton=1) REFERENCES deployment_prepare_receipt_sources(singleton),
 import_command_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_commands(command_id),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision=2), hash TEXT NOT NULL CHECK(length(hash)=64),
 UNIQUE(request_id,receipt_sha256),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 FOREIGN KEY(vault_id,kind,request_id,version,anchor_digest) REFERENCES domain_records(vault_id,kind,id,version,sha256)
);
CREATE TABLE deployment_prepare_consumptions (
 request_id TEXT PRIMARY KEY, receipt_sha256 TEXT NOT NULL UNIQUE CHECK(length(receipt_sha256)=64),
 consumption_id TEXT NOT NULL UNIQUE CHECK(length(consumption_id)=36), vault_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='deployment_receipt_consumption'), version INTEGER NOT NULL CHECK(version=1),
 anchor_digest TEXT NOT NULL CHECK(length(anchor_digest)=64),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision=2),
 command_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_commands(command_id),
 event_id TEXT NOT NULL UNIQUE REFERENCES api_event_envelopes(event_id),
 consumed_ms INTEGER NOT NULL CHECK(consumed_ms BETWEEN 0 AND 253402300799999),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(request_id,receipt_sha256) REFERENCES deployment_prepare_receipts(request_id,receipt_sha256),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 FOREIGN KEY(vault_id,kind,consumption_id,version,anchor_digest) REFERENCES domain_records(vault_id,kind,id,version,sha256)
);
CREATE TABLE deployment_prepare_consumed_outbox (
 consumption_id TEXT PRIMARY KEY REFERENCES deployment_prepare_consumptions(consumption_id),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 payload_size INTEGER NOT NULL CHECK(payload_size BETWEEN 1 AND 4096),
 state TEXT NOT NULL CHECK(state IN ('pending','published')),
 published_ms INTEGER CHECK(published_ms BETWEEN 0 AND 253402300799999),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2), hash TEXT NOT NULL CHECK(length(hash)=64),
 CHECK((state='pending' AND revision=1 AND published_ms IS NULL)
  OR (state='published' AND revision=2 AND published_ms IS NOT NULL))
);
```

Existing six hashed tables retain `{namespace:"deployment-prepare-storage-v1",table:<suffix>,row}`
for ALL their rows, including new revisions; unchanged columns mean old hashes never change.
Four added tables use namespace deployment-prepare-storage-v2 and suffixes receipt_sources,
receipts, consumptions, consumed_outbox. Row excludes only hash; canonical JSON TEXT is hashed as
its exact string. Verify Python scalar types/byte limits/UUID/digest grammar beyond SQL CHECKs.
Only heads/control/old outbox/new consumed_outbox permit CAS updates, matching old revision AND hash;
all other rows are immutable. No extra indexes/triggers/views, cascade, replacement or pruning.

## 3. Migration algorithm and verified history

Run unconditionally at upgraded PersistentDeploymentPrepare construction, in its actual DomainStore
writer with foreign_keys=ON throughout, even when all live U/J/K are absent. No public schema-version
setting, sidecar importer, cached layout choice or old-binary coexistence. Exact v2 is forward-only;
old code must reject it. Migration itself never reconciles, expires or publishes. Before full row
materialization, inspect exact schema and per-column typeof/UTF8 length/caps including migration
checksums. Do not put Bfix1's scalar preflight behind a full SELECT. Verify the bound actual candidate
registry through its existing bounded candidate preflight before rebuilding populated history. Verify exact v1 schema,
migration1 checksum, every v1 row/hash/anchor/blob/event/replay/outbox relationship and global bounds
before any DDL. Reject any new-domain anchor or any partial/new private table in a purported v1 DB.
Wholly absent private schema may install v1 then migrate in that writer only after proving absence
of all three deployment domain kinds and orphan relevant deployment events; deleting receipt tables must never reenroll an occupied DB.
Already-v2 startup requires exact rows {(1,C1),(2,C2)}, eleven exact tables and whole-v2 integrity.
No source enrollment/import, clock advance, domain/event write or projection happens in migration.

Snapshot exact typed rows of migrations/lifecycle/heads/commands/outbox in bounded Python memory
(1/32/16/32/32 respectively), ordered by PK; no JSON normalization or TEMP/attached database.
Execute `PRAGMA defer_foreign_keys=ON` and verify it is 1; this defers enforcement, not disables FKs.
DELETE old outbox, heads, commands, lifecycle (per-row PK deletes, descending revision), migrations; all cyclic children
are now empty. DROP outbox, heads, commands, lifecycle, migrations in that order. No rename of a
referenced old table, no writable_schema, no foreign_keys OFF and no executescript implicit commit.
Execute the nine DDL statements above using individual db.execute calls. Restore migration1 exactly;
restore lifecycle ordered request_id/revision, commands, heads, outbox using explicit column lists
and original values/hashes. Deferred lifecycle→command FK permits restore; referenced events and
requests never moved. Insert (2,C2), prove exact snapshot equality and unchanged control/requests,
domain bytes/ref associations/event stream; run whole-v2 verification and PRAGMA foreign_key_check.
Commit with defer_foreign_keys still ON (SQLite resets it on transaction exit); any fault rolls back
the entire rebuild to exact v1. Do not turn deferral OFF to hide pending violations. Preflight must
prove delete/drop/restore deferral counters resolve on supported SQLite; no untested FK workaround.

## 4. Immutable domain records and integrity bijections

Both use ImmutableRecord.create, operational/version1, actual human actor and persisted policy roots,
created_at_utc=import now padded to six digits. Receipt ID=request_id, parents=[actual request_ref]:
`{schema_version:"deployment-receipt-anchor-v1",receipt_blob_ref,request_ref,trust_blob_ref,
ingress_blob_ref,consumption_exchange_blob_ref,import_command_id}` (exact keys).
Consumption ID=host-generated UUID, parents=[actual request_ref,actual receipt_ref], exact content:
`{schema_version:"deployment-receipt-consumption-anchor-v1",request_ref,receipt_ref,
winning_lifecycle_revision:2,consumed_at:Time,actor_ref,transaction_id:import_command_id,
public_event_id:actual appended event_id,outcome:"failed"|"unknown"}`.
transaction_id is deliberately the deployment command ID, not a fabricated SQLite transaction ID.
consumed_at retains the wire Time grammar: exactly24 characters with three fractional digits.
For example, consumed_at `2023-11-14T22:13:22.123Z` requires created_at_utc
`2023-11-14T22:13:22.123000Z`: zero-pad the validated fractional text, never round/truncate or
require literal equality between unlike representations. Six-digit consumed_at is invalid.
Receipt SHA is external SHA256 of complete signed bytes; BlobRef SHA is hex, API selector B32.
Domain envelope SHA is different. Keep opaque signed bytes in the blob; no nested *_ref rewriting.
Consumption has no lifecycle hash, future anchor ref or self/event hash; the event has no consumption
ref. All EntityRefs/BlobRefs resolve through unchanged DomainStore graph and reference association checks.

Sources singleton exists iff ≥1 admitted receipt. identity_json is exact canonical
`{trust:U.recheck_current().as_dict(),ingress:J.recheck_current().as_dict(),
consumption:K.recheck_current().as_dict()}` using the closed source-contract identities. U/J/K blobs must match pins, identity bytes,
actual historical control E and request T/instance/origin; source Q/V/R/I links are also checked.
Enrollment uses actual retained instances/currentness, never identities supplied by callers.

Whole verification: requests↔deployment_request anchors; receipts↔deployment_receipt anchors;
consumptions↔deployment_receipt_consumption anchors (every version, no extra legacy arms). ≤16 each;
≤48 lifecycle/commands; ≤32 old outbox and ≤16 consumed_outbox; read LIMIT cap+1, never truncate.
Every request has prepared1, exact predecessor hashes, last-row head, and only transitions in §5.
Every receipt matches one import command and revision2 receipt_pending/rejected; pending-success
may have cancelled3/expired3 but cannot consume. Rejected has exactly one failed/unknown receipt,
consumption and consumed outbox; all other states have zero consumption. Every command↔non-expired
history link is bijective with matching actor/route/input/status/receipt/cursor; expiry has no command.
Exactly one request outbox per request; one cancel outbox iff cancelled; one consumed outbox per
consumption. No receipt outbox. Recompute projection SHA/size from actual immutable records.
Historical verification uses committed U/signature/time-at-admission, never current source availability,
current deadline or a new key interpretation. Check event vault/object/actor/type/status/error/time/correlation/metadata/cursor.
SQL FKs are insufficient for predecessor-state, command kind, outcome, vault, event and blob-size checks.

## 5. Admission, lifecycle, clock and replay matrix

| Actual head and fresh matching command | now<expires | now≥expires |
| --- | --- | --- |
| prepared1 + valid succeeded import | receipt_pending2, evidence only | expired2;409, no receipt/consumption |
| prepared1 + valid failed/unknown import | rejected2+one-use+K intent | expired2;409, no receipt/consumption |
| prepared1 + cancel | cancelled2, v1 marker | expired2;409, no cancel command/marker |
| receipt_pending2 + cancel | cancelled3, v2 marker | expired3;409, no cancel command/marker |
| receipt_pending2 + another import |409; first evidence immutable|409; bounded expiry may later make expired3|
| rejected/cancelled/expired + new command |409|409|

Cancel/import first compares actual request digest/expected revision and replay; stale/mismatched
commands do not themselves expire a different head. Matching expired eligible head materializes the
system expiry and commits before returning409. Background expiry only prepared1/receipt_pending2.
Retain the v1 durable checkpoint policy before presealing; final now=max(actual owner time, durable
floor, highest sampled in process). Failed checkpoint inhibits mutation/publication. Strict receipt
created≤started≤completed≤actual now<expires, observed times inside started..completed; no grace.
Pure verifier additionally checks completed<expires. Invalid evidence never creates an admission;
independent bounded expiry maintenance may still expire an eligible request. GET never expires.

For a fresh import: authenticate actual owner/request; verify full journal and replay; commit durable
clock checkpoint. In an actual writer check the matching request digest/head/revision and first-only
managed-kind absence before source access. If that matching prepared head is already due, commit
expiry only and return409 even if selected evidence/U/J/K is missing or invalid. A stale/wrong
head/digest command does not expire another head. For an eligible request, read actual U/J/K,
check K inventory, call J.open_receipt(B32), retain its FD, validate canonical
wire/signature against actual U and exact committed request; preseal receipt/U/J/K bytes. A parsed
or signature-checked value stays inert. In final writer repeat auth/replay/journal/head/digest/time;
recheck exact readers+lease named file/whole bytes/pins/identities and request graph. Reverify signature
from those actual bytes. Repeat first-only managed-domain absence query (any installation/qualification/
binding row denies); do not open/reacquire T-slot absence, use physical service claims as core proof,
or require live T/E when intact independent U/J/K and historical bindings suffice.
Enroll source row if first admission; put receipt anchor; append receipt event via shared helper;
construct/put consumption anchor only for non-success using returned event.event_id. Insert lifecycle2,
CAS prepared head, insert exact command receipt, receipt index, optional consumption index/outbox;
suppress pending request outbox (published unchanged); verify full journal and commit once. Deferred
lifecycle command FK resolves before commit. Anchor/event/command/index failure rolls back authority;
only unattached presealed blobs may remain. No filesystem publication before this commit.

Command IDs stay globally unique within deployment commands. Import digest input is canonical
`{namespace,instance_id,origin_digest,actor_ref,input}`; input includes route request_id plus exact body.
Live-owner exact replay returns frozen original200/status/body without U/J/K reread, expiry, verification,
outbox flush or new authority; changed route/body/actor/operation returns409. For cancel replay, inspect
stored cancel-v1/v2 namespace first; do not derive namespace from today's head. Fresh cancel from
prepared uses cancel-v1; from pending uses cancel-v2. Unsuccessful admission has no command receipt;
successful import of failed/unknown evidence DOES create a command receipt and rejected2 lifecycle.

## 6. API/event/publication matrices

Owner-session-only POST `/api/v1/deployment/requests/{request_id}/receipts`, exact body≤4096:
`{command_id:UUID,request_digest:B32,receipt_digest:B32,expected_revision:integer1..3}`.
Reuse v1 strict transport/depth4/items32/string256/no-query checks; no browser bytes/key/path/upload.
200 frozen body exactly `{command_id,request_id,receipt_digest,outcome,
disposition:"pending_postconditions"|"consumed_non_success",revision:2,event_cursor}`.
Cancel route body extends expected_revision to1..3; v1 response keys unchanged, revision may now3.
Existing v1 prepare/cancel stored receipts and rendered prefix/canonical bytes remain identical.
Current GET always uses the separately named prepare-api-v2 artifact, with both new fields even
for old requests; preserve prepare-api-v1 and cancellation-v1 artifact bytes unchanged. The new
cancellation-v2 artifact permits2|3 while its emitter uses3 only. This pre-release route evolution
is not backward-compatible validation by the old closed schema. Historical replies stay unchanged.
GET keeps v1 keys, extends states/revisions, adds `receipt:null|{receipt_digest,outcome,disposition,
import_revision:2}` and `consumption_publication_state:null|"pending"|"published"`; receipt is retained
after cancelled3/expired3, disposition remains historical pending_postconditions. HEAD runs same checks.
Local historical reads/cancel and exact replay survive source loss; fatal DB integrity always503.

| Transition | Event type | status / error_code | exact metadata |
| --- | --- | --- | --- |
| receipt_pending2 | deployment.receipt_committed | pending / null | {revision:2} |
| rejected2, signed failed | deployment.receipt_committed | failed / null | {revision:2} |
| rejected2, signed unknown | deployment.receipt_committed | unknown / outcome_unknown | {revision:2} |
| cancelled2 or3 | deployment.request_cancelled | cancelled / null | {revision:2 or3} |
| expired2 or3 | deployment.request_expired | blocked / stale_state | {revision:2 or3} |

Reuse registered receipt_committed (meaning evidence commit, not success); no new event ID injection
API. One event per transition, request ObjectRef only, private_evidence_refs=[], causation_id=null,
actual human/system actor and policy root, retention core, both event times=transition time at six
digits; correlation=command ID or host expiry UUID. No signer facts/hash/key in public metadata.
Errors retain v1 exact envelope/messages: malformed selector/body or invalid signed wire/signature400
invalid_input; missing selected final503 dependency_unavailable (request404 only after auth/integrity);
wrong request binding/lifecycle/late/conflicting replay409 conflict; missing/drifted/unsafe U/J/K503
dependency_unavailable; corrupt enrolled journal503 unavailable; auth401/403, body413, bounded capacity429.
Different current source pin is dependency_unavailable, not reenrollment. Post-commit filesystem failure
returns frozen200; publication recovery never creates a second consumption/event/command.

Admission suppresses pending request projection in every outcome. Cancellation revision2 emits exact
unchanged v1 marker; revision3 emits same fields with schema deployment-cancellation-v2, domain
deeptwin-deployment-cancellation-v2 and lifecycle_revision3 (v2 codec permits2|3, emitter uses3 only).
Filename remains cancelled/<request-digest-hex>.json; E bytes/membership/ownership never change.
Consumed marker is exact source-contract §5 bytes, from immutable consumption/request/receipt, named
consumed/<receipt-digest-hex>.json. Only rejected2 can have pending→published; never suppressed.
After commit hold same DomainStore writer through full journal/consumption/retained U/J/K rechecks,
K.publish_consumed(receipt_digest,payload), returned role/digest/SHA/size/file checks and outbox ackCAS;
resample durable monotonic time for published_ms≥consumed_ms. Deadline no longer blocks committed
consumption projection. Check existing K finals correspond to actual consumption/outbox, including
pending rows after crash; alien/differing files inhibit. The precise source-contract§7 K gate is
normative: after durable receipt_sources enrollment every positive request projection requires
fresh actual K inventory before publication and before ackCAS, across restart and even when K is
unavailable. Before enrollment request publication remains T/E-only; new import and consumed
publication always require actual U/J/K. E-only cancellation is exempt from the K gate, never
from E's own currentness/protected-root/alias checks. Local read/replay/cancel/expiry stay independent.
Check TTL again after potentially slow K inspection and before E I/O; if due, expire instead.
A valid prepare may commit201pending under existing T/E admission before post-commit K failure.
Missing acknowledged final never regresses ack, recreates that final, reenrolls K or frees a slot.
No durable loss latch is added: enrollment causes mandatory rechecking on every future attempt.
Expected per-item dependency failure leaves pending work and must not trigger B's corruption latch.
Cancellation cannot win after rejection. Exact existing-file recovery fsyncs before ack; no deletion
or reconsumption. Failure after file visibility leaves pending recovery, not cross-filesystem atomicity.
Use one combined ≤16-item/one-second-soft reconciliation budget: cancel, consumed, request priority;
one writer per item, stop on integrity failure, no new item after budget. No perpetual scheduler,
automatic inbox import or hard fsync latency promise. Published is historical durable acknowledgement,
not proof the file still exists; never regress a published row or silently republish missing finals.


## 7. Exact storage compatibility APIs

Keep storage mechanics in `app/deployment/prepare_storage.py`. Keep the existing exported
`DDL`, `CHECKSUM`, `SHAPE`, `COLUMNS`, `TABLES`, `CAPS`, `NULLABLE` meanings fixed to v1;
their old definitions/checksum are historical inputs, not aliases to “current.” Add separately
named `DDL_V2`, `CHECKSUM_V2`, `SHAPE_V2`, `COLUMNS_V2`, `TABLES_V2`, `CAPS_V2`, `NULLABLE_V2`.
Two private frozen build-owned layouts reuse common scalar/hash/SQL-check mechanics. Do not
copy the complete storage module or expose a configurable schema backend.

Exact signatures:

```python
# prepare_storage.py
def _layout(db) -> _Layout: ...       # exact observed shape + migration rows, never a caller version
def _private_sizes(db, layout) -> None: ...
def _validate_row(layout, table, row) -> None: ...
def validate_row(table, row) -> None: ...              # retained v1-only compatibility API
def validate_current_row(db, table, row) -> None: ...  # observes exact DB layout itself
def digest(table, values) -> str: ...                 # six old suffixes remain storage-v1
def insert(db, table, values) -> dict: ...             # _layout(db), private v1/v2 validation
def advance(db, table, old, changes) -> dict: ...      # same dispatch for both old and new row
def verify(db) -> dict[str, list[dict]]: ...           # exact supported stored shape only
def install(db) -> None: ...                          # historical v1-only installer, never migrates
def _rebuild_v1_as_v2(db) -> None: ...                 # mechanical internal primitive only

# prepare_records.py
def private_sizes(db) -> None: ...                    # observes exact supported shape
def install_storage(db) -> None: ...                  # retained v1-only foundation helper
def install(domain, db, profile, *, candidate_registry) -> dict: ...
def verify(domain, db, profile) -> dict: ...
```

`install(domain,...,candidate_registry=...)` is the sole production install/upgrade entry.
It checks the exact persistent registry and its bound domain/profile, calls the existing
`bounded_candidates` before the actual registry `_verify(db)`, then the full old or new
journal verifier. This required concrete dependency replaces the current direct-install
test calls; it is not a verification callback. Constructor calls it with its already
validated `_registry`, then `_journal(db)`. Do not first call legacy `install_storage`:
that path intentionally rejects v2 and cannot verify enough before a populated migration.

Historical helpers remain honest after upgrade: `storage.install(db)` and
`records.install_storage(db)` reject exact v2; they neither downgrade nor silently treat it
as v1. `validate_row(table,row)` always means v1 and rejects new-only rows. Production writes
never call this v1 wrapper for a migrated row: `insert/advance` use `_validate_row(_layout(db),...)`.
`verify`, `validate_current_row`, `records.verify/private_sizes` admit either exact stored shape.
No decision is made from a revision integer or the presence of just the migration2 row.
`_layout` itself must inspect migration typeof/length and cap before reading checksum values;
it must not move Bfix1's bounded preflight behind its own full migration-row materialization.

`digest` may accept the four new fixed suffixes and choose their storage-v2 namespace;
all six historical suffixes use storage-v1 even on new revision3 rows. Its return is only a
hash, never schema admission. Validate exact columns, strict types, UTF8 caps, canonical JSON,
UUID/B32/lowerhex grammar and literal SQL constraints independently. SQL foreign keys remain
checked against the actual DB, not the isolated CHECK-validation DB.

### 7.1 Eleven-table layout

Use the exact §2 nine changed/new DDL statements, with full order:
`migrations, control, requests, lifecycle, heads, commands, outbox, receipt_sources, receipts,
consumptions, consumed_outbox`. Reuse exact old control/request statements. C2 is the SHA256
of canonical JSON of these eleven exact strings, not a pretty-printed schema or SQL introspection.
Migration1 retains accepted production C1, not the SQL diagnostic's independently extracted C1.

Hashed-row bounds are respectively `1,16,48,16,48,32,1,16,16,16`; migrations has exactly two
rows. Every read uses cap+1 and rejects overflow. Old snapshot capacities before rebuild are
1 migration, 32 lifecycle, 16 heads, 32 commands, 32 outbox. All growth remains bounded by
16 permanent request reservations. Four new tables do not create another capacity counter.

`advance` preserves exact old allowed-column sets and adds only
`consumed_outbox: {state,published_ms}` keyed by consumption_id, pending→published, revision1→2.
It checks both old/new row against the actual layout and compares old revision AND hash.
Heads may advance2→3 under v2; lifecycle semantic admission alone authorizes that predecessor.
Never add arbitrary updates to receipt_sources/receipts/consumptions or replace rows.


## 8. Shared whole-history verifier and domain boundary

`prepare_records.py` continues to own bounded loading and cross-record integrity. Its existing
`load` and `retained_sources` remain the shared historical request/candidate/T/E checks; do not
implement a second request loader. Refactor the outer verifier to exact layout dispatch plus
shared request loading, with private v1/v2 lifecycle paths. Avoid copying its complete v1 walker.

Add bounded private helpers in that module:

```python
def _load_receipt_sources(domain, db, roots, profile, control, rows) -> dict | None: ...
def _load_receipt(domain, db, roots, profile, item, source_binding, row) -> dict: ...
def _load_consumption(domain, db, roots, item, receipt, row) -> dict: ...
```

Return existing journal keys `control, requests, rows`, plus `receipt_sources` (None or loaded
historical binding). Each loaded request item gains `receipt`, `consumption`, `consumed_outbox`
(None or verified data). Existing item keys retain meanings. These dicts are transaction-local
inert load results, not authority wrappers accepted from callers.

New `app/domain/deployment_receipt.py` owns two closed content schemas/body validators;
modify `domain/refs.py`, `schemas.py`, `schema_exports.py` only for the two new kinds and exports.
Exact names are `receipt_content_schema()`, `consumption_content_schema()`,
`validate_receipt_body(body)->None`, `validate_consumption_body(body)->None`. Both complete
canonical anchor bodies have the8192byte cap. Body validators check all duplicated header/parent/
actor/time relations from§4; content schemas alone cannot establish those envelope relationships.
Use ImmutableRecord, normal `_load/_check_graph/_blob_bytes/_put_in_transaction` and unchanged
reserved-reference scanning. Receipt id=request_id, parent=[request_ref], four operational blobs
(receipt/U/J/K), version1. Consumption id=host UUID, parents=[request_ref,receipt_ref], no blobs,
version1. Consumption public_event_id is the actual transition append's returned ID. Domain
envelope digests, complete signed receipt digest and marker payload digest remain distinct.

Before loading new bodies/graph associations, inspect SQL typeof/length, cap anchors at8KiB,
blob sizes at receipt/U16KiB and J/K8KiB, and association counts. With current root/actor policy
edges, receipt has at most4 distinct EntityRef edges and4 blobs; consumption at most5 edges
and0 blobs (duplicate content refs do not add distinct targets). Confirm exact associations
through DomainStore, not merely those upper bounds. Preserve candidate/root preflights from Bfix1.

Full v2 checks include:

- Three index↔anchor bijections across every stored version/vault, each≤16; no orphan new
  anchors in v1. Source singleton iff at least one receipt; control iff requests; no data
  outside these relationships. Receipt/source blob hashes and sizes must match actual bytes.
- Retained U/J/K parsers validate all fixed structure/profile/recipe fields and cross-links:
  J historical R/I/E against retained E/request T; K same Q/V/U/J/E; distinct source IDs and
  correct historical instance/origin. The stored source identities have exact closed types
  and canonical bytes. Historical integrity does not reopen sources or adopt current pins.
- Reverify each committed signature against its committed U and exact request. Compare receipt
  times to original transition/admission time and immutable request deadline, never current now.
  Missing crypto dependency must fail rather than accept a historical receipt unchecked.
- Only prepared1→cancelled2/expired2/receipt_pending2/rejected2 and
  receipt_pending2→cancelled3/expired3. Strict nondecreasing transition times, exact predecessor
  revision/hash, exact head, correct human/system actor and event payload. Receipt_pending means
  succeeded; rejected means failed/unknown. Rejected has exactly one consumption; pending success
  and later cancellation/expiry have none. No import row without revision2 receipt transition.
- Complete non-expired lifecycle↔command bijection, global command IDs, exact namespace/input/
  actor/status/reply/cursor. Receipt import command expected_revision is1; cancel-v1 is1;
  cancel-v2 is2. Parsing may permit1..3, but a retained successful command must fit its transition.
- One request outbox per request, cancel iff cancelled, consumed iff non-success consumption.
  Recompute payload bytes using exact historical marker version and indices/anchors. Request
  pending is possible only while prepared. Published ack times lie between originating lifecycle
  time and durable floor; request ack cannot follow the first transition away from prepared
  (history[1], not merely the final revision3). Consumed ack never predates consumed_ms.
- Exact deployment event universe now includes receipt_committed and has≤48 entries, compared
  to lifecycle IDs. No generic event enum check replaces exact request ObjectRef, actor, times,
  correlation, status/error, private_evidence_refs=[], metadata revision and stored cursor.


## 9. Shared lifecycle and E compatibility

`prepare_lifecycle.py` owns transitions, event append/cursor and command snapshots. Retain
`body(item,command_id=None,cursor=None)` as the v1-shaped projection helper used by old stored
command validation; add `read_body(item)` for current v2 GET. Every upgraded current GET has the
two new fields (null before import); it does not choose response schema by the request's age.
Prepare command responses remain v1 bytes; cancel-v1 remains v1 bytes; cancel-v2 has the same
command keys with revision3, never retroactively adds receipt fields to old command receipts.

Concrete internal split, used by existing transition and import:

```python
def _append_transition(db, roots, profile, item, *, state, now, actor_ref,
                       command_id=None, receipt_outcome=None) -> tuple[dict, EventEnvelope]: ...
def _store_command(db, profile, item, *, actor_ref, namespace, value,
                   http_status, receipt, lifecycle_revision) -> None: ...
def transition(db, roots, profile, item, *, state, now, actor_ref, value=None) -> dict | None: ...
def commit_receipt_transition(db, roots, profile, item, *, now, actor_ref, value,
                              receipt_outcome) -> tuple[dict, EventEnvelope]: ...
def cancellation_payload(item, *, profile) -> bytes: ...
def consumed_payload(item) -> bytes: ...
def read_body(item) -> dict: ...
```

`_append_transition` has the finite transition matrix, derives revision from actual predecessor,
appends actual event/history/head and suppresses a pending request. It returns the actual event;
there is no public append-event callback or event-ID injection parameter. `transition` handles
prepare/cancel/expiry and its historical command projections. `commit_receipt_transition` handles
only receipt_pending/rejected, derives event status from exact outcome, writes frozen import
command and returns actual event plus response. The service then builds optional consumption
using that event ID before final full verification/commit. Incomplete intermediate relationships
are private inside this one writer, never exposed as an authoritative finished journal.

Add pure `app/deployment/prepare_v2_contracts.py`:
`parse_cancel_v2(request_id,value)->dict`, `parse_receipt_import(request_id,value)->dict`,
`cancellation_v2(request,transitioned_ms,*,profile)->bytes` (emits revision3 only).
Also `parse_cancellation_v2(*,request_digest,payload,profile)->dict` owns the one pure canonical
marker grammar (exact §6 fields, strict2|3 revision, cap4096, actual OriginProfile equality,
calendar/time/B32/UUID checks). It raises the same closed DeploymentPrepareError family as the
other pure prepare codecs. The emitter validates the accepted request, builds revision3 bytes,
then calls this parser. Later publication.validate_cancellation_v2 calls it via a local import
to avoid the existing prepare_contracts→publication module cycle, normalizes its closed errors to
DeploymentSourceError and creates only an inert Projection. No duplicate marker grammar or
unimplemented future publisher dependency is required to test this pure step independently.
Use existing input limits/time/B32/helpers, unchanged `parse_cancel` for retained v1 commands.
Add `prepare_v2_schema_exports.py` with explicit `prepare-api-v2` and `cancellation-v2` exports
under `schemas/v1/deployment/`, distinct URNs following the established naming scheme.
The v2 cancellation structural parser permits2|3 as §6 specifies; v2 emitter uses3; the
existing v1 emitter/parser/schema still permits exactly2 and reproduces exact bytes.

Publication needs a deliberate E compatibility seam after source Tasks14–16 stop editing it:

```python
# publication.py (or its dedicated v2 codec wrapper reusing shared mechanics)
def validate_cancellation_v2(*, request_digest, payload, profile) -> Projection: ...
def _validate_retained_projection(*, role, request_digest, payload, profile) -> Projection: ...
def publish_cancellation_v2(source, *, request_digest, payload) -> PublicationObservation: ...
# sources.ExchangeSource
def publish_cancellation_v2(self, *, request_digest, payload): ...
```

Keep existing public `validate_projection` and `publish(...role='request'|'cancel')` v1 behavior.
The new publisher checks exact ExchangeSource and currentness and uses the same private stage/
existing-file/no-clobber primitives from Task16. `ExchangeSource._recheck_outbox` uses a bounded
`_validate_retained_projection` schema discriminator: request always v1; cancellation exactly v1 or v2 delegates
to its fixed codec. Unknown/mixed schema fails. This is required for E cold reopen and for a
later v1 request/cancel publication when another request already has a v2 final. No new E role,
namespace, manifest byte or arbitrary schema override is added.


## 10. Same-service API and replay admission

Constructor becomes:

```python
PersistentDeploymentPrepare(domain_store, owner_authority, candidate_registry, *,
    topology_source, exchange_source, public_trust_source=None,
    receipt_ingress_source=None, consumption_exchange_source=None)
```

Each non-None source must be the exact accepted class; service borrows them. New public method
`import_receipt(authenticated_request,request_id,payload)->dict` uses the existing `@closed`
lock. Pure helpers cannot import/own this service. Any extracted import helper remains a private
function called with this exact service and no independent lock/clock/transaction owner.

Refactor `_admit(request,value,operation)` and `_replay(journal,actor_ref,operation,value)` to
fixed logical operation strings prepare/cancel/receipt_import. Existing command lookup happens
before current-head interpretation. For a found command, require its namespace belongs to that
one operation, then recompute input_digest using its stored namespace and exact actor/input.
No found command can become a fresh command because today's state changed. Fresh namespace is
prepare-v1/import-v1 or, for cancel, derived only after valid matching head prepared1/pending2.


## 11. Existing HTTP contribution and resource extension

After C acceptance, its writer extends `app/api/deployment_prepare.py` rather than installing a
second contribution. `prepare_services(context,*,dependencies)` still consumes only
`extension-candidates.registry`, exports only `deployment-prepare.service`, and constructs once.
Keep existing `reconcile_prepare_startup(own_exports)` unchanged in meaning.

Append five fixed startup keys to the existing four: DEEPTWIN_RECEIPT_RECIPE_SHA256,
DEEPTWIN_RECEIPT_INSTANCE_SHA256, DEEPTWIN_DEPLOYMENT_TRUST_SHA256,
DEEPTWIN_RECEIPT_INGRESS_SHA256, DEEPTWIN_CONSUMPTION_EXCHANGE_SHA256. Read the same frozen
StartupInputs; open U/J/K independently with their exact existing factories/profile/protected roots.
Malformed U pin does not skip opening J/K; common Q/V invalidity denies J/K but not U or independent
T/E. No live T/E requirement is introduced for U/J/K opening or import. Exact cross-binding occurs
inside the service against historical committed bytes, not through mere factory success.

Factory-local ExitStack owns each opened source immediately; successful ContributionServices
transfers exact objects once to common owned_resources. Service borrows all five; no duplicate
transfer of domain/owner/registry and no service.close that closes them again. Failed construction,
later contribution/route failure and host shutdown use C's common reverse-order ownership. Leases
are method-local and close before control returns. Source closure invalidates outstanding leases.
No changes to generic server composition/dependency mechanics are needed for receipt support.

Extend the same contribution descriptor with browser-only POST
`/api/v1/deployment/requests/{request_id}/receipts` with route identity
`deployment.requests.receipts.import`, browser_session-only with deployment.manage and actual auth.
Add WebBoundary parsing using the same4096/depth4/items32/members8/string256 limits and no query.
Dispatch cancel through the new parser; GET through current v2 structural output. Preserve actual
local prefix projection, deterministic JSON, frozen unprefixed DB replies and HEAD equivalence.
Import reply has no links and uses exact §6 fields. No discovery/list/import-all route is added.


## 12. Frozen checksums, errors and acceptance

The exact canonical full eleven-statement DDL list has CHECKSUM_V2
`d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f`; original seven-statement
CHECKSUM remains `68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec`.
Assert these from actual literal constants; never join SQL lines or derive expected strings from
sqlite_schema. The previously recorded five in-memory synthetic-parent SQL checks prove only DDL
mechanics, not actual DomainStore/owner/journal migration. Real disk-backed tests remain required.

Wire§8 private _ReceiptRequestMismatch maps to409 only after actual signature success. Other
ReceiptWireError maps to400; source§7 DeploymentReceiptInvalid also maps to400 only after its safe
selected-read boundary. Other source errors map to503 dependency_unavailable; no text matching or
second relational validator. A failed live J instance/profile/U binding may deny503 before pure
request verification. Matching-head due expiry precedes live source/evidence access as§5 specifies.

Minimum connected verification on actual owner/domain/registry/source fixtures:

- Empty and sixteen-request mixed v1 histories migrate atomically, preserve every typed old row,
  bytes/hash/anchor/event/cursor and unchanged control/requests, reopen exact v2, idempotently verify.
  Inject faults after every delete/drop/create/restore/migration insert/commit; rollback exact v1.
  Assert FKON throughout, no rename/TEMP/attached DB/executescript, no partial-schema repair.
- Scalar/UTF8/row/association preflight denies oversized/malformed migration/anchor/private values
  before full materialization. Dirty v1/new-kind orphan, wrong checksum/extra schema/FK or altered
  history denies before DDL. Old low-level v1 helpers reject v2, real insert/CAS validate v2 CHECKs.
- Actual signed pending success creates zero consumption/install; failed/unknown exactly one
  consumption and K intent in the same writer/event/command. Competing connections import/import,
  cancel/import and expiry serialize; every authority-write failure rolls back all authoritative
  changes. Presealed orphan blobs are allowed but never admitted as receipts.
- Current GETv2 versus frozen prepare/cancel/import replies, actual-auth replay with absent sources,
  source drift and all exact error partitions; pending-success cancel/expiry revision3 and v2 E
  cold reopen, existing mixed v1/v2 files and unchanged v1 bytes. No T/slot reacquisition on import.
- Post-rename/pre-ack crash recovery only acknowledges exact existing file after required fsync;
  missing published/alien/differing K finals never repair/reenroll/free. Enroll through success with
  zero consumptions, restart without K: a new admitted prepare stays201pending; E-only cancel still
  publishes with intact E. Before enrollment missing K never adds a request dependency.
- K failure before E call creates no file; after visibility/before ack leaves pending; an inspection
  crossing TTL creates expiry instead of new publication. Fresh writer sees enrollment committed
  by another connection. Expected source loss never latches journal corruption or blocks cancels.
- One shared≤16-item/one-second-soft budget; pending-success expiry remains eligible; cancellation
  priority, then consumed, then request/expiry. No hidden second scheduler or filesystem hard bound.
- Real supported local-prefix and portable HTTP owner/candidate/prepare/import/read/head/cancel/
  restart chain with same concrete service/export. Source factory/activation/teardown tests extend
  C's established ownership. No positive verifier/service callback, raw uploaded evidence, dynamic
  composition lookup or pretend external key/job/image qualification.

Implementation order after source Task17: pure v2/domain codecs; E mixed-version publication;
coordinated storage/records/lifecycle/service migration/import; then extension of the existing C
HTTP contribution. Each gets its own scoped brief/tests/review before a successor. No sidecar
receipt_journal_schema/import_service/router architecture, runtime schema knob or shared-core copy.

## 13. Actual historical fixture boundary

The test-only `app/tests/deployment_v1_history_fixture.py` may build a real valid v1 history before
constructing the upgraded service: `v1_history(tmp_path,monkeypatch,*,states=(...))` yields actual
domain/owner/registry/profile/authenticated request and original public command cases;
`snapshot_v1(domain)` returns bounded in-memory typed rows and reached public bytes/relationships.
states is a closed0..16 test tuple of prepared/cancelled/expired, not a runtime schema selector.

Enter actual owner/candidate under existing pre_deployment_catalog only for owner startup, then
restore the catalog before normal upgraded construction. Install exact v1 with storage.install
in an actual FK-on DomainStore writer BEFORE any deployment request anchor exists. Do not call
records.install (the upgrade API) or use retained_anchor as a complete history: it deliberately
creates an orphan for negative tests and must continue to fail the absence guard.

Register real candidate variants; use normal make_request/ImmutableRecord/put_blob and actual E
currentness for retained source identity. Attach each request anchor/index/control and complete
its history in one real writer using existing lifecycle.transition for prepared/cancelled/expired.
That helper must retain valid v1 support and creates actual events/cursors/commands/outbox; never
seed fabricated event IDs/hashes/cursors or duplicate live prepare/replay/reconciliation logic.
Check bounded candidates, actual registry integrity, complete records.verify and foreign_key_check
before commit and after independent read reopen. Explicitly assert C1/oldschema/three state matrices
and namespace/revision/status rather than accepting a generator's boolean assurance.

Use an actual sampled owner time with a wide valid request interval for live fixture rows and
well-past deadlines for expiry rows. Keep positive fixture outboxes pending/suppressed; separate
actual file-publication tests cover published histories. Do not label synthetic history times or
manually assembled DB state as proof of old service/live-source/clock admission.

Construct ordinary upgraded PersistentDeploymentPrepare with these actual owners and sourcesNone;
its unconditional migration runs untouched. Compare exact in-memory before/after public schema/
typedrows/reached record/blob/edge/event/cursor snapshot BEFORE startup reconciliation can legitimately
expire/publish. Never snapshot/export auth/session tables, verifier/root capability files or cookies;
no committed owner DB/golden whole-journal dump is needed. Current full supported HTTP tests remain
separate actual admission evidence. A neutral test-only request-material extraction may be shared
with retained_anchor, but never a positive verifier or a service migration bypass.
