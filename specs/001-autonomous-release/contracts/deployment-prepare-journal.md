# Deployment stage prepare/cancel journal v1

Normative Task10 integration contract following the actual source-I/O boundary in
`deployment-prepare-sources.md`. No deployed effect, signed receipt, installation/qualification,
worker invocation or whole T025/T087 completion is implied. Existing request arms remain required;
this first-only stage/cancel slice does not silently implement release/update/recovery/replace.

## 1. Selected design and existing interfaces

Use seven private tables: migration; one topology/clock binding; immutable request/reservation;
immutable lifecycle history; lifecycle head; command receipts; outbox. The request row itself holds
the permanent slot/extension reservation. No separate vacant-slot table, provisional installation,
receipt-consumption table, or reservation-release facade is needed for this first-only slice.

Service construction binds exact DomainStore, PersistentOwnerAuthority and PersistentCandidateRegistry
from supported startup, and the concrete startup-owned topology/exchange readers. Reject subclasses,
different owner/domain instances and caller callbacks. Services import shared `app/domain/refs.py`,
`schemas.py`, `request_identity.py`, `wire.py`, `public_events.py`, never HTTP adapters. Actual
`AuthenticatedRequest` now lives in request_identity; `_owner.authenticate_bound(session,db=db)`
requires the exact active DomainStore writer and rejects copied/process-stale session objects
(`owner_auth.py:399–415`). The shared authenticate helper has historical fallback behavior
(`request_identity.py:17–33`); Task10 must not use that fallback to broaden its exact persistent owner.

Use the concrete registry's `_verify(db)` and `candidate_records.load_candidate(domain,db,row)`
on the same writer; no nested public registry.read connection and no `candidate_loader` callback.
Registry and domain verify the actual anchor/blobs/command/event relationships. Owner checks must
also retain exact method, origin/host and CSRF for mutations, not merely a plausible Actor value.

DomainStore owns canonical immutable bytes and reference associations. `put_blob` owns a writer;
preseal outside the final writer after actual early owner validation, then call `_put_in_transaction`
for anchors in the final writer. Presealed unattached blob rows/files may survive rejection.
The global reserved `*_ref(s)` scanner is unchanged. Events use shared
`_append_event_in_transaction` and `_event_cursor_in_transaction` (`public_events.py:497–535`).

## 2. Immutable request anchor and digest identities

Add the necessary actual domain kind **`deployment_request`** to ENTITY_KINDS; its normal locator
is consequently available. Add a narrow content validator for this kind and update domain/event
structural exports. Do not reuse extension_installation or extension_manifest for a request.
The port schema generator's generic ref grammar does not require changing the44 port schemas.

Domain envelope: kind deployment_request, ID=request_id, version1, purpose operational; actor is
the current persisted human owner, policies are real roots, created_at_utc uses the existing exact
six-digit microsecond format. parent_refs contains exactly the candidate anchor EntityRef. Content:

```text
{
 schema_version:"deployment-request-anchor-v1",
 request_id:UUID,
 request_blob_ref: actual operational BlobRef,
 candidate_ref: actual extension_manifest candidate-anchor EntityRef,
 topology_blob_ref: actual operational BlobRef,
 exchange_blob_ref: actual operational BlobRef,
 topology_id:UUID, topology_revision:1, slot_id:integer1..16,
 reservation_revision:1, prepare_command_id:UUID
}
```

The opaque request blob contains the exact common request envelope in §9 and canonical stage arm;
only managed never-installed `{state:"absent"}`/next revision1 is admitted. Preserve declared
network/resource MetaRefs inside that blob; they are neither EntityRefs nor runtime permissions.
Topology bytes are the independently pinned, actually admitted public source. Candidate descriptors
must match its exact slot; no override or extra topology precondition is inserted into the wire.

Keep three different hashes explicit:

- request_digest: b64u32 SHA256 of canonical request excluding only request_digest;
- request_blob_ref.sha256: hex64 SHA256 of the complete canonical request bytes;
- request anchor EntityRef.sha256: hex64 SHA256 of the whole domain envelope.

The topology blob SHA is the independent source pin. Recompute all hashes/relationships at final
admission and load. URI labels, physical volume names and source declarations never authenticate
themselves. All UUIDs are canonical nonnil; b64u32 is exact unpadded32bytes with roundtrip validation;
HexDigest is lowercasehex64. SQL length checks below are not replacements for those parsers.

## 3. Exact private SQL

Namespace is `deployment_prepare_*`. These are the literal v1 DDL statements for this slice; a contract is not a completed migration. Use canonical ordered DDL list SHA256 as migration checksum, matching existing private-schema
patterns. Every column's exact Python scalar type, named schema/checksum and table-associated row
hash is verified. No triggers/views/undeclared indexes, no ON DELETE CASCADE, no INSERT OR REPLACE.
The existing domain/event FK shapes are reused. Forward command/history FKs are deferred to permit
their single commit, not a content-hash cycle. Only IDs connect event/command/history.

```sql
CREATE TABLE deployment_prepare_migrations (
 version INTEGER PRIMARY KEY CHECK(version=1),
 checksum TEXT NOT NULL CHECK(length(checksum)=64)
);

CREATE TABLE deployment_prepare_control (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id),
 instance_id TEXT NOT NULL CHECK(length(instance_id)=32),
 origin_digest TEXT NOT NULL CHECK(length(origin_digest)=64),
 topology_id TEXT NOT NULL UNIQUE CHECK(length(topology_id)=36),
 topology_revision INTEGER NOT NULL CHECK(topology_revision=1),
 topology_purpose TEXT NOT NULL CHECK(topology_purpose='operational'),
 topology_sha256 TEXT NOT NULL CHECK(length(topology_sha256)=64),
 topology_size INTEGER NOT NULL CHECK(topology_size BETWEEN 1 AND 65536),
 exchange_id TEXT NOT NULL UNIQUE CHECK(length(exchange_id)=36),
 exchange_revision INTEGER NOT NULL CHECK(exchange_revision=1),
 exchange_purpose TEXT NOT NULL CHECK(exchange_purpose='operational'),
 exchange_sha256 TEXT NOT NULL CHECK(length(exchange_sha256)=64),
 exchange_size INTEGER NOT NULL CHECK(exchange_size BETWEEN 1 AND 8192),
 exchange_identity_json TEXT NOT NULL CHECK(length(exchange_identity_json) BETWEEN 2 AND 4096),
 slot_capacity INTEGER NOT NULL CHECK(slot_capacity BETWEEN 1 AND 16),
 clock_floor_ms INTEGER NOT NULL CHECK(clock_floor_ms BETWEEN 0 AND 253402300799999),
 revision INTEGER NOT NULL CHECK(revision>=1),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 UNIQUE(vault_id,topology_id),
 FOREIGN KEY(vault_id,topology_purpose,topology_sha256)
  REFERENCES domain_blobs(vault_id,purpose,sha256),
 FOREIGN KEY(vault_id,exchange_purpose,exchange_sha256)
  REFERENCES domain_blobs(vault_id,purpose,sha256)
);

CREATE TABLE deployment_prepare_requests (
 request_id TEXT PRIMARY KEY CHECK(length(request_id)=36),
 vault_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='deployment_request'),
 version INTEGER NOT NULL CHECK(version=1),
 anchor_digest TEXT NOT NULL CHECK(length(anchor_digest)=64),
 request_digest TEXT NOT NULL UNIQUE CHECK(length(request_digest)=43),
 nonce_hex TEXT NOT NULL UNIQUE CHECK(length(nonce_hex)=64),
 topology_id TEXT NOT NULL,
 slot_id INTEGER NOT NULL CHECK(slot_id BETWEEN 1 AND 16),
 reservation_revision INTEGER NOT NULL CHECK(reservation_revision=1),
 extension_id TEXT NOT NULL CHECK(length(extension_id) BETWEEN 1 AND 128),
 created_ms INTEGER NOT NULL CHECK(created_ms BETWEEN 0 AND 253402300799999),
 expires_ms INTEGER NOT NULL CHECK(expires_ms<=253402300799999),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 CHECK(expires_ms-created_ms BETWEEN 60000 AND 86400000),
 UNIQUE(vault_id,topology_id,slot_id),
 UNIQUE(vault_id,extension_id),
 FOREIGN KEY(vault_id,topology_id)
  REFERENCES deployment_prepare_control(vault_id,topology_id),
 FOREIGN KEY(vault_id,kind,request_id,version,anchor_digest)
  REFERENCES domain_records(vault_id,kind,id,version,sha256)
);

CREATE TABLE deployment_prepare_lifecycle (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2),
 previous_revision INTEGER,
 previous_hash TEXT,
 state TEXT NOT NULL CHECK(state IN ('prepared','cancelled','expired')),
 transitioned_ms INTEGER NOT NULL CHECK(transitioned_ms BETWEEN 0 AND 253402300799999),
 actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 1024),
 command_id TEXT,
 event_id TEXT NOT NULL UNIQUE REFERENCES api_event_envelopes(event_id),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(request_id,revision),
 UNIQUE(request_id,revision,hash),
 UNIQUE(command_id),
 FOREIGN KEY(request_id,previous_revision,previous_hash)
  REFERENCES deployment_prepare_lifecycle(request_id,revision,hash),
 FOREIGN KEY(command_id) REFERENCES deployment_prepare_commands(command_id)
  DEFERRABLE INITIALLY DEFERRED,
 CHECK((revision=1 AND state='prepared' AND previous_revision IS NULL
        AND previous_hash IS NULL AND command_id IS NOT NULL)
    OR (revision=2 AND state IN ('cancelled','expired') AND previous_revision IS NOT NULL AND previous_revision=1
        AND previous_hash IS NOT NULL)),
 CHECK((state='expired' AND command_id IS NULL)
    OR (state IN ('prepared','cancelled') AND command_id IS NOT NULL))
);

CREATE TABLE deployment_prepare_heads (
 request_id TEXT PRIMARY KEY REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2),
 lifecycle_hash TEXT NOT NULL CHECK(length(lifecycle_hash)=64),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(request_id,revision,lifecycle_hash)
  REFERENCES deployment_prepare_lifecycle(request_id,revision,hash)
);

CREATE TABLE deployment_prepare_commands (
 command_id TEXT PRIMARY KEY CHECK(length(command_id)=36),
 namespace TEXT NOT NULL CHECK(namespace IN ('deployment-prepare-v1','deployment-cancel-v1')),
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 1024),
 input_json TEXT NOT NULL CHECK(length(input_json) BETWEEN 2 AND 4096),
 input_digest TEXT NOT NULL CHECK(length(input_digest)=64),
 http_status INTEGER NOT NULL CHECK(http_status IN (200,201)),
 receipt_json TEXT NOT NULL CHECK(length(receipt_json) BETWEEN 2 AND 8192),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision BETWEEN 1 AND 2),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 UNIQUE(namespace,request_id),
 FOREIGN KEY(request_id,lifecycle_revision)
  REFERENCES deployment_prepare_lifecycle(request_id,revision),
 CHECK((namespace='deployment-prepare-v1' AND http_status=201 AND lifecycle_revision=1)
    OR (namespace='deployment-cancel-v1' AND http_status=200 AND lifecycle_revision=2))
);

CREATE TABLE deployment_prepare_outbox (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 role TEXT NOT NULL CHECK(role IN ('request','cancel')),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision BETWEEN 1 AND 2),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 payload_size INTEGER NOT NULL CHECK(payload_size BETWEEN 1 AND 65536),
 state TEXT NOT NULL CHECK(state IN ('pending','published','suppressed')),
 published_ms INTEGER CHECK(published_ms BETWEEN 0 AND 253402300799999),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(request_id,role),
 FOREIGN KEY(request_id,lifecycle_revision)
  REFERENCES deployment_prepare_lifecycle(request_id,revision),
 CHECK((role='request' AND lifecycle_revision=1)
    OR (role='cancel' AND lifecycle_revision=2 AND state<>'suppressed')),
 CHECK((state='pending' AND revision=1 AND published_ms IS NULL)
    OR (state='published' AND revision=2 AND published_ms IS NOT NULL)
    OR (state='suppressed' AND revision=2 AND published_ms IS NULL))
);
```

Row hash: hex SHA256 of canonical `{namespace:"deployment-prepare-storage-v1",table:<exact suffix>,
row:<all columns except hash>}`. TEXT JSON fields must themselves be exact canonical text; runtime
enforces UTF8 byte caps, not merely SQL character lengths. Lifecycle previous_hash binds the exact
preceding row. On updates compare both old revision and old hash; require rowcount1. Request rows,
lifecycle history and command receipts are insert-only. Heads/control/outbox alone change under CAS.
Rows/hashes protect integrity consistency, not malicious administrators who can rewrite the DB.

No redundant full request/topology/exchange copy is stored in SQL. Requests are lookup/reservation indexes;
control is the host pin/clock binding; lifecycle/command/outbox are the actual private control journal.
Marker bytes are deterministically reconstructed from request+lifecycle, not an arbitrary stored
payload. Verify every indexed scalar against its authoritative blob/anchor or transition before use.

The shared event table currently has globally UNIQUE event_id; validate the referenced event's
vault_id, request object ref, actor, event type, timestamp, correlation and metadata as well as FK.
actor_ref TEXT is a canonical actual actor EntityRef: resolve its full domain graph and actor descriptor,
not just its JSON syntax. Human prepared/cancelled actors must match current owner on command admission;
expired actor must equal the real system root. Verify command↔history links in both directions and
derive the stored cursor from the actual referenced event's sequence. No event/hash cycle is created.

## 4. Enrollment, whole-journal validation and actual absence

Private schema can exist empty without topology configured; control row is absent until the first
successful prepare. Install only a wholly absent schema after proving no committed deployment_request
domain anchor exists. Partial/private schema or checksum mismatch fails closed. On the first prepare,
insert control plus first request and all related records atomically. Thus a bound topology always
has an independently stored domain request anchor; deleting every private table cannot masquerade
as an initial empty enrollment. A control row with no requests is invalid under this v1 contract.
Orphan topology/request blobs are not enrollment evidence.

On startup, read and before mutation: exact schema/checksum/columns/global no-trigger validation;
foreign_key_check; canonical row/hash/ref validation; bounded complete request index↔domain-request
anchor bijection; exactly one prepared revision per request, at most one valid terminal successor,
head equals last history revision/hash; exact command/transition and outbox matrix. Reject extra
domain request anchors, missing heads/commands/outboxes, unsupported domain request content and
wrong-vault references. A domain record is not absent because its index disappeared.

For **new** prepare only, inside the same writer query committed domain kinds
extension_installation/extension_qualification/extension_binding. Any such row, including ambiguous
historical values or a tombstone, denies this intentionally first-only slice globally. Do not try
to infer a successful absence from parsing unknown legacy content. Candidate manifests are allowed.
Also verify the whole new request/reservation journal and query its UNIQUE extension/slot barriers.
Slot ID must exist within the verified contiguous source capacity and match all candidate declarations.
No target or slot reuse is allowed even after cancellation or expiry. UNIQUE insertion of the
request/reservation row is the initial absent→held CAS under BEGIN IMMEDIATE. There is no missing
row lookup exposed as a generic installation-head authority. Managed absence still says nothing
about unobserved host containers; the operator checks its actual precondition before effects.

Reads/cancellation do not require present physical topology or fresh managed-installation absence.
They verify the historical source blob/DB binding and request journal, retain real owner auth, and
can operate when the new-prepare source is unavailable. Malformed/corrupt journal remains unavailable,
never not_found. A different source pin/instance/topology UUID cannot reset a reservation or enrollment.

## 5. Time, prepare, replay and terminal transitions

Timestamps in wire use exact UTCmilliseconds, SQL integer milliseconds. Domain/event timestamps use
the same instant padded to six fractional digits; do not pass milliseconds to `_at_epoch`, whose
input is seconds. Check representable time/TTL addition before serialization. TTL is explicit60..86400
seconds in input; no service default, renewal, skew grace or nonce reuse.

Use the exact owner authority's current time machinery, not a user clock callback. For an enrolled
journal, bounded authenticated mutation admission first commits a clock checkpoint in its own short
DomainStore writer: `now=max(owner._now(db,write=True),control.clock_floor_ms)` and advance the
deployment clock floor monotonically. This writer has no request/slot/event/command effects. It
precedes presealing and the final business writer; a later business rejection cannot undo the
checkpoint. Final writer time is at least that checkpoint and the in-process highest sampled value.
Retain the latter until checkpointed; if checkpoint durability fails, inhibit mutations/publication,
not perform work using a lower time. Do not rewrite owner-auth time policy or promise protection
against administrator clock/DB rollback. Before first enrollment there are no request deadlines to
revive; source binding/initial floor commits with the first successful request. GET has no deployment checkpoint or expiry mutation. The existing authentication middleware's
owner-session clock/idle maintenance remains unchanged; do not claim GET causes no authentication
bookkeeping anywhere in the stack.

Replay key is command_id within this deployment command namespace, across prepare and cancel.
input_digest is SHA256 canonical `{namespace,instance_id,origin_digest,actor_ref,input}`; input for
cancel includes the exact route request_id. Store input_json as that route's canonical input object,
not the entire candidate bundle or request blob. Compare actor, namespace, canonical input and digest;
changed body, route target, or command kind gives409. Revalidate current actual session before replay;
original session token/ID is not persisted in this table and a fresh valid owner session may replay.
Successful command replay returns its exact original status/body, even if lifecycle/publication has
since changed. It neither recreates a nonce nor flushes an outbox. Read gives present journal state.

New prepare: early owner/replay/capacity/source/candidate checks; generate one proposed request ID,
nonce and explicit time interval; preseal request/topology/exchange bytes; enter writer; verify owner,
registry/journal, replay again, time validity, exact source/currentness, managed absence and barriers;
insert actual request anchor; insert control if first enrollment, reservation/request index,
prepared event/history/head, prepare command receipt and request outbox pending. Commit once.
Events can be inserted before history because the outer transaction is all-or-none. Unused proposals
and presealed blobs have no authority. Never call public put_blob or a public registry read here.

Initial lifecycle is revision1 prepared. Only terminal transitions are revision2 cancelled or
expired, each with previous_revision1/exact previous_hash. No third revision or state reopening.
These narrow SQL checks must be migrated explicitly when real receipt consumers are introduced;
do not preauthorize future accepted/rejected/receipt_pending mutations now.

Cancel: exact live owner+CSRF; replay first; verify request_digest and expected_revision against the
real head. Wrong/stale input returns409. Prepared and now<expires_ms → one cancelled transition,
cancel event/head CAS, command receipt, cancel outbox pending; request outbox pending→suppressed,
or leave already-published untouched. Retain the immutable reservation. A different command against
an already cancelled/expired request returns409, not another successful mutation. Same-command
cancel replay remains200. No claim that host effects were undone.

If a matching fresh cancel finds prepared but now>=expires_ms, materialize expiry instead: system
expired event/history/head and suppress pending request publication, no cancel command/marker;
commit that expiry, then return409. Do not raise an exception inside the writer and accidentally
roll it back. A failed/stale cancel may otherwise return409 without a transition. Expiry maintenance
uses the same writer/CAS and system root, creates no command row and never frees reservation.
Startup and bounded mutation completion/publication check deadlines; there is no implied perpetual
scheduler. GET reports the stored lifecycle, so an unswept prepared state after expires_at is not a
claim of continuing eligibility. Every actual prepare/publication/operator admission checks time.

## 6. Outbox, exact marker and cancel/publication serialization

The request filename is `requests/<hex(request_digest decoded bytes)>.json`, not the complete
request-blob hash. Payload is the already committed complete request blob. Cancel filename is
`cancelled/<same request digest hex>.json`. No expiry file or consumed marker is produced in Task10.
The operator already checks expires_at; receipt consumption namespaces remain unused.

Exact cancellation marker bytes, at most4096bytes:

```text
{
 schema:"deployment-cancellation-v1",
 domain:"deeptwin-deployment-cancellation-v1",
 request_id:UUID, request_digest:b64u32,
 instance_id:hex32, origin_profile_digest:b64u32,
 lifecycle_revision:2, cancelled_at:UTCmilliseconds
}
```

This is an unsigned control-written projection of committed cancellation, not an operator receipt
or cryptographic proof. Exact file-channel ownership supplies provenance. Derive every field from
the immutable request and cancelled history. Outbox payload_sha256 hashes these whole marker bytes;
for request it equals request_blob_ref.sha256. Validate these equalities on every load/retry.

After the business commit, a bounded publisher opens **the same DomainStore SQLite writer**, verifies
the full journal and exact pending row, and keeps that writer through lifecycle/source/exchange/time
rechecks, no-follow publication and delivered-row CAS. Cancellation/expiry cannot commit between
those checks and request-file publication. Request publication requires prepared, live TTL and the
current pinned source; cancel marker publication requires committed cancelled state and the exact
outgoing exchange source, **not** currently valid physical topology. Source drift blocks new request
publication but must not block an intact cancellation marker or read/cancel API.

Publish only already committed bytes. Choose Linux `renameat2(...,RENAME_NOREPLACE)` through a narrow
libc binding (flag1), with retained source/destination directory FDs and an exclusive-create random
staging basename. Write exact bytes, set final declared permissions, fsync the staging file, perform
no-replace rename, then fsync the destination directory before delivery bookkeeping. EEXIST means
verify the existing file, never replace it. ENOSYS/EINVAL/EOPNOTSUPP means publication unavailable;
no ordinary-rename or check-then-rename fallback. No process or Docker API is needed. Existing final
file is acceptable only if exact canonical
bytes/digest/size/type/permissions match; differing content or unsafe path inhibits publication.
Do not check-then-overwrite rename, delete a previous file, create runtime mounts or write the RO
receipt inbox. Unsupported platform semantics deny publication, not fall back to overwrite. This report does
not change the existing exchange namespace or introduce an alternative receipt transport.

Race/crash rules:

- Cancel writer wins first: pending request row becomes suppressed; publisher never creates its
  request projection afterwards. Cancel marker remains retryable pending if exchange is unavailable.
- Publisher wins first: file may become visible before its bookkeeping commit, while cancel waits.
  After publisher transaction exits, cancel may commit but cannot claim the prior file was unread.
- Crash after final file publication but before bookkeeping commit: row remains pending; the next
  eligible publisher validates the exact existing file, then marks published once. It never emits
  different bytes or regenerates nonce. If cancellation won meanwhile, suppress pending work and
  never republish; existing bytes may already have escaped.
- Request projection state **suppressed** means “do not perform future publication,” not “this
  file never existed.” Thus suppression is honest even if a crash left an unacknowledged file.
  Published means bookkeeping confirmed an exact durable publication at published_ms, not that
  the file remains available forever or the operator acted. Do not regress published→pending.
- A filesystem error after request commit leaves its exact stored201 prepared/pending receipt;
  return that receipt instead of500. Fatal bookkeeping corruption still inhibits subsequent work.
  There is no DB/filesystem atomicity claim; external observation can precede a rollback of delivery
  bookkeeping. SQLite writer serialization protects logical order, not external-reader revocation.

Each reconciliation invocation visits at most16pending items, prioritizing cancellation markers,
using one transaction per item; stop at the first integrity failure. No retry-count/audit table is
needed. Do not block an HTTP turn indefinitely on a failing filesystem: begin no new item after a
one-second soft invocation budget, and cap each payload at64KiB. fsync itself has no hard portable
latency guarantee; record that limitation rather than claim the budget interrupts a kernel call.

## 7. Exact HTTP inputs, replies and errors

Fixed browser-session-only contribution; mutations require deployment.manage, reads deployment.read
as composer labels, **plus actual live owner checks**. Labels are not grants. No service-client route.
Bodies bounded4096bytes before buffering, depth4/items32/members8/string256; UUID, numeric slot and
TTL parsers reject bools. No query fields; GET/HEAD body absent. Use shared strict wire decoding before
auth work for malformed inputs, preserve all supported boundary headers/method/media/Origin/CSRF rules.

POST `/api/v1/deployment/requests` exact input:
`{command_id:UUID,kind:"extension_stage",candidate_id:UUID,slot_id:integer1..16,expires_in_seconds:60..86400}`.
The slot ID is the topology slot_number rendered as an integer, not a candidate name/UID/channel.
Kind is a closed constant; unsupported arms are not guessed partial schemas.

POST `/api/v1/deployment/requests/{request_id}/cancel` exact input:
`{command_id:UUID,request_digest:b64u32,expected_revision:integer1..2}`.
Its canonical stored command input also contains request_id from the validated path; the body cannot
override it. A2 is syntactically valid but cannot cause another transition in this slice.

Prepare201 and cancel200 command receipts have the same exact keys:

```text
{command_id,request_id,request_digest,kind:"extension_stage",
 state:"prepared"|"cancelled",revision:1|2,
 publication_state:"pending"|"published"|"suppressed",
 cancellation_publication_state:null|"pending"|"published",
 event_cursor,links:{self,cancel,events}}
```

Prepare receipt is frozen with prepared/1/pending/null. Cancel receipt is frozen with cancelled/2,
the resulting request publication state and cancellation_publication_state=pending. These are the
committed command snapshot; do not mutate them after immediate publisher success. This makes replay
byte-identical. Current publication facts are obtained through GET. No succeeded installation state,
operator completion, qualification, fake result ref or runtime permit is returned.

GET200 `/api/v1/deployment/requests/{request_id}` exact body:

```text
{request_id,request_digest,kind:"extension_stage",
 state:"prepared"|"cancelled"|"expired",revision:1|2,
 publication_state:"pending"|"published"|"suppressed",
 cancellation_publication_state:null|"pending"|"published",
 request:<complete exact immutable request>,links:{self,cancel,events}}
```

Cancel publication is null unless state cancelled, when its pending/published outbox must exist.
Prepared request projection is pending/published; a terminal projection is published/suppressed.
Unknown ID404 only after authentication and journal integrity checks. HEAD executes the same read
checks/status and headers but no body. No flush, event, expiry transition or candidate initialization.
Links are stored/rendered only from fixed paths: self `/api/v1/deployment/requests/{request_id}`,
cancel self+`/cancel`, events `/api/v1/events`; the HTTP adapter prefixes actual local origin base
exactly once, while portable uses root paths. No caller URL or internal file path is returned.

Serialize command-success and read bodies deterministically as ADR008 canonical JSON after the
fixed link prefix projection, so initial/replayed HTTP body bytes are identical, not merely equal
JSON objects. HEAD calculates the same content-type/content-length/status/security headers as GET
but sends no body; the existing common HEAD suppression remains authoritative. Errors containing
fresh correlation IDs are not replay receipts. Never mutate stored unprefixed canonical receipts.

All deployment application errors use exactly `{code,message,retryability:"not_retryable",
affected_refs:[],correlation_id:UUID}` with a fresh safe host correlation ID and fixed messages:

| code | HTTP | fixed message |
| --- | --- | --- |
| invalid_input |400| Invalid deployment request. |
| unauthenticated |401| Authentication is required. |
| access_denied |403| This action is not allowed. |
| not_found |404| Deployment request, candidate or slot was not found. |
| conflict |409| Deployment request state conflicts with this command. |
| too_large |413| Deployment request is too large. |
| capacity |429| Deployment preparation capacity is exhausted. |
| dependency_unavailable |503| Deployment preparation is unavailable. |
| unavailable |503| Deployment state is unavailable. |

Missing/drifted/unmatched topology or exchange is dependency_unavailable; exhausted/held matching slot
is capacity; same-extension prior reservation is conflict; corrupt journal/history ambiguity is
unavailable. Unknown candidate/slot is not_found only after actual auth (slot outside configured
capacity is a missing slot; source absent is dependency_unavailable). These errors promise neither
automatic retry nor clearing a barrier. Existing boundary transport/session errors retain their
own already-closed schemas. No raw exceptions, keys, cookies, root paths or source text in messages.
The table maps expected DeploymentPrepareError. Unexpected sanitized programmer failures retain
the generic non-debug host500, rather than being mislabeled as an expected503 or a command receipt.
Production debug stays disabled and internal diagnostic text is never returned in the body.

## 8. Caps, events and minimum verification cases

Source capacity gives a hard maximum16permanent request reservations,32lifecycle rows,32success
commands and32outbox rows. Check bounds before materializing rows (LIMIT maximum+1) and validate
global shape; never silently truncate. Request blob64KiB, topology64KiB, anchor8KiB, command input4KiB,
receipt8KiB, cancel marker4KiB; canonical depth/items limits also apply. Journal immutable-content
growth is consequently bounded without a second mutable byte counter. This is not a disk quota for
presealed orphans or all candidate content. No automatic pruning/release/cleanup is part of Task10.

Public events: existing deployment.request_prepared (status pending) and deployment.request_cancelled
(status cancelled), metadata exactly `{revision:1}` or `{revision:2}`; add deployment.request_expired
(status blocked, error_code stale_state, metadata exactly `{revision:2}`). Actual service enforces
these exact metadata objects even though the general registry permits absent optional observations.
Use request ObjectRef, actual actor/system root, prepared/cancel correlation=command ID, expiry
correlation=host UUID, retention core and actual access-policy root; no source/nonce/request hashes in
public metadata. Event IDs link history; cursors derive from that same event transaction. Publication
bookkeeping emits no extra public event or success claim. Register/export/test the new expired type.

Minimum regression cases: real owner prepare/read/replay/cancel with one exact matching synthetic
source; stale/copied/revoked session; different command bytes/route/actor; same-slot and same-extension
two-connection races; private/domain anchor/index bijection corruption; real historical installation
row prevents managed absence; fault after anchor/reservation/event/head/outbox before commit leaves
none; clock rollback after checkpoint cannot revive expired request; cancellation after deadline
commits expiry once while returning409; cancel before publisher creates no later request file;
publisher-before-cancel and crash-after-file-before-ack preserve exact bytes and barrier; source drift
denies new prepare/publication but allows read/cancel+cancel-marker projection; publication failure
still returns the frozen201; cold reopen preserves all heads/receipts/reservations. Tests use real
temporary SQLite/files and actual owner sessions, with isolated low-level Linux observation fixtures,
not a fake source-authority constructor. The implementation must supply exact RED/GREEN and real transaction/source evidence; this contract
itself is not a test result.

## 9. Exact request construction and pure export contract

Common envelope has exactly the fields specified by deployment-prepare-sources§9:
schema,domain,request_id,kind,request_nonce,request_digest,instance_id,origin_profile_digest,
effect_payload,preconditions,created_by,created_at,expires_at. Schema/domain are the fixed
deployment-request-v1/deeptwin-deployment-request-v1 and kind is extension_stage. Use the Task9
pure validate_projection(*,role,request_digest,payload,profile) in app/deployment/publication.py
retains one shape/hash codec. Its Projection reports role/request_digest/payload_sha256/size_bytes,
not effect authority. Parse those same canonical bytes and supplement with the closed exact stage
arm below and full current source/journal admission. A pure parsed request is never authority.

Use actual persisted owner actor EntityRef (kind actor, matching account, human/local_session
content) for created_by; all source and request times are host-generated. Request nonce is exactly
32cryptographic random bytes encoded canonical unpaddedbase64url; requestID is nonnilUUID.
created_at/expires_at are exact ASCII UTCmilliseconds, calendar-validated through year9999.
Explicit expires_in_seconds60..86400 defines the exact integral-second interval; no implicitdefault,
extension, clockgrace or replay regeneration. request_digest excludes only itself; origin digest
converts only the actual OriginProfile hex32bytes to b64u32. Other nested hashes retain their types.

effect_payload is exactly:
```text
{schema_id:"deeptwin.extension-stage-request.v1",
 extension_id:CandidateId,
 manifest_digest:HexDigest,
 service_descriptor_digest:HexDigest,
 selected_platform_entry:{platform:"linux/amd64"|"linux/arm64",
   index_digest:OciDigest,manifest_digest:OciDigest,config_digest:OciDigest,
   ordered_layer_digests:[OciDigest,...]},
 new_service_effect:{service_identity:BrokerId,socket_mounts:[SocketMount],
   named_volume_mounts:[],network_policy_ref:MetaRef(network_declaration),
   resource_profile_ref:MetaRef(resource_declaration)},
 expected_installation_head:{state:"absent"},expected_next_installation_revision:1}
```
CandidateId here is the stable manifest extension_id (existing1..128 Id grammar), NOT the candidate
anchor UUID. OciDigest has the exact sha256:hex64 grammar. Layer order including repetitions comes
from the selected actual descriptor entry; one OCI index digest comes from descriptor.index.
The descriptor must contain both supported platforms; selected platform must equal the actual
admitted topology platform. No tag resolution, OCI image fetch or content verification is implied.

Use actual candidate_records.load_candidate output/associated blobs to reconstruct the matching
CandidateBundle, preserving exact MetaRefs and support-document order/identity. The actual core
catalog tuple must be ordinary tool-port-v1/oci_extension_service/runtime-worker class; source.kind
does not promote trust. Require network none, empty grant_ids/secret_needs, filesystem_needs exactly
["owned_scratch"], the fixed baseline isolation document and one exact slot socket/no data mounts.
Compare requester control20102:20102, service/UID/GID/channel/pairGID/protocol/socket name and mount
tuple exactly with T. All four requested resource dimensions must fit the immutable slot allowance.
No capability flag, caller-held descriptor hash or unverified image metadata replaces these checks.
Unknown/mixed/extra fields, alternate stage/tombstone heads, future installation references or
nonempty preconditions are invalid, not another partially implemented branch.

Structural artifacts are generated from the same schema helpers, with Draft202012 schema checks,
runtime/JSONSchema valid-negative parity and exact byte regeneration:
- schemas/v1/deployment/request-stage-v1.schema.json
- schemas/v1/deployment/request-anchor-v1.schema.json
- schemas/v1/deployment/prepare-api-v1.schema.json
- schemas/v1/deployment/cancellation-v1.schema.json.
Their exact $id values are urn:deeptwin:schemas:v1:deployment:request-stage-v1,
urn:deeptwin:schemas:v1:deployment:request-anchor-v1,
urn:deeptwin:schemas:v1:deployment:prepare-api-v1 and
urn:deeptwin:schemas:v1:deployment:cancellation-v1. This follows the existing schema URN style.
Artifacts are structural definitions, not ADR008 request
bytes or proofs. Keep generator hashing/newline policy explicit; never rewrite44semanticport or
historical build-input artifacts for the new request kind.

## 10. Immutable exchange binding and clock/publication limits

Control E columns in §3 are required from migrationv1, not a later optional patch. exchange_blob_ref
is mandatory in the exact anchor. Preseal actual independently verified E; verify its canonical bytes,
hash/size/OriginProfile/instance/R/I against T and the immutable control binding in the same writer.
A complete source parser applies even to retained blobs; arbitrary BlobRef syntax is insufficient.

exchange_identity_json is exact canonical private observed continuity:
```text
{schema_version:"deployment-outbox-identity-v1",
 root:{device, inode}, requests:{device,inode}, cancelled:{device,inode},
 backing_root_digest:HexDigest}
```
Device exact nonnegative signed64integer; inode positive signed64integer. The source reader obtains
this tuple from actual freshly checked FDs/mount map. No HTTP or caller-provided proof value.
The digest covers decoded UTF8 mountinfo backing-root text; do not persist transient mount IDs.
Its exact immutable tuple, E UUID/revision/pin, T UUID/revision/pin, vault and instance persist across
normal restart. Any replacement/continuity loss denies projection pending explicit future
maintenance, never reenrolls, creates a new outbox, overwrites a pin or frees reservations.
Only control clock/revision/hash may change under its specified CAS.

Source failure/currentness is distinct from retained-journal integrity. New/current T mismatch denies
new prepare/request publication but local read/cancel continues against retained valid records.
E may independently reopen and publish cancellation even after T loss. E mismatch prevents all
projections without preventing valid local cancellation; a new correct-looking source is not a
migration of old pending work. Complete startup pin absence never creates positive source state.

The pre-I/O clock check is an admission observation, not a hard upper bound on fsync/rename latency.
published_ms records actual monotonic acknowledgement observation, not a fictional precise first
visibility instant. Recheck host time before initiating publication, checkpoint highest observation
as prescribed, and require the external operator to recheck TTL/cancel immediately before effects.
Never claim syscall interruption or a copied request's revocation. If I/O succeeded before a failed
DBacknowledgement, retain honest pending/suppressed recovery semantics.

## 11. Common fixed composition, dependencies and resource ownership

This is a narrow T025 common-seam amendment for a real dependent contribution; it is not an
arbitrary plugin container. Leave app/api/router_composition.py's existing descriptor validation,
passive-router/no-hook policy and atomic route staging unchanged. Server contains no deployment/
candidate imports, names, pin keys or service-specific branch. Only fixed installed code chooses
the catalog; there is no public late registration, configuration-selected module or locator.

Extend InstalledContribution with frozen requires, provides and startup_keys tuples (default empty).
All names are exact nonempty bounded strings (maximum128UTF8bytes, ASCII identifier grammar
[a-z][a-z0-9._-]* except environment keys use [A-Z][A-Z0-9_]*). At most64unique entries each and
64totalstartupkeys. Validate complete catalog before anyfactory: unique provides, required keys
provided by earlier entries, no forward refs/cycles/repeated keys. Preserve fixed ordering rather
than dynamically sorting factories. Returned export keys must exactly equal declaredprovides.
Existing candidate entry declares provides=("extension-candidates.registry",); core declaresempty.
Deployment declares only that key in requires and its own one service export.

No-dependency call remains factory(context). A dependent factory is called once as
factory(context, dependencies=MappingProxyType(exact_declared_subset)), never signature inspection
or TypeError retry. Every factory sees the same actual frozen ApplicationContext identity. The
private subset comes only from successful earlier build-owned factories, not app.state or runtime
lookup. Actual deployment factory verifies registry type/domain/owner identity; no duplicate registry
construction, fake loader, mutableglobal locator or arbitrary caller evidence callback.

ContributionServices adds owned_resources:tuple=(). Successful return transfers exact closeable
objects to common ownership before subsequent export/router validation. Reject duplicate resource
identities within/across contributions. A private resource owner backs FirstPartyPublication.close();
close in reverse construction order, idempotently, attempting later cleanup even if one raises.
Cleanup errors are sanitized; preserve an already active original failure. Borrowed domain/owner/
store/registry objects are not transferred as new owned source resources. Do not grant close hooks
through descriptors or route lifecycle events.

Factory uses a local ExitStack as soon as each concrete source opens. Try T/E independently;
catch only expected closed source availability failures. Unexpected service/construction failure
closes all untransferred resources; successful ContributionServices creation transfers them once.
No resource object is published merely so a route/app.state can obtain cleanup. Invalid later
contribution/route inclusion closes already adopted resources before propagating sanitized failure.

At supported shutdown/worker-startupfailure: stop/clear worker, close common publication, close
authority, close store, with nested finally so everyowner is attempted. If composition or session/
middleware registration fails before return, close publication ifcreated, then existing owners.
These are fixed common teardown mechanics, not plugin startup hooks or external effects.

StartupInputs is frozen: values immutable Mapping[str,str], invalid_keys immutable tuple[str,...],
protected_roots tuple[Path,...]. Fixedcatalog startup_keys defines the entireallowedkeyunion.
Snapshot only those ambientenv/config entries once, never whole environment or ambient reads
inside factories. Valid rawvalues must be strings≤256UTF8bytes; invaliddeclaredvalues are omitted
and their names recorded in invalid_keys without rawtext, making that feature unavailable rather
than killing owner/candidate startup. No truncation/coercion/default. Unknown programmatickeys/
invalid overall mapping type are startupconfigurationerrors. No credential/session/verifier/root
handle enters this map; all four deployment keys are nonsecret SHA256pins and parsed exactly by
its own factory.

Generic supported create_app accepts first_party_startup_values=None and additional_protected_roots=().
Actual validated data/sessionrootpaths are always appended; caller cannotremove them. Main adds
actual bootstrapconfigparent and any real configured publictrust/otherexchange roots. Paths must
be absolute bounded/no dot/no symlink normalization; do not resolve() to forgive unsafealiases.
No directory/key contents are read by this genericcontextbuilder. Sources add their canonical
fixed built-in protectedmounts and do real checks. Programmaticcallers must declare any additional
configured protectedroots; no discovery of unrelated/privatehostfiles.

The final unique lexical protected-root tuple is bounded to64entries including mandatoryroots,
each1..4096UTF8bytes. Accept absolute Path values without retained '..' components; a Path has
already eliminated '.' components, so do not claim to recover the caller's original spelling.
Deduplicate exact lexical paths only, not resolved/inode aliases. Main anchors a relative configured
bootstrapfile to cwd without resolve(), rejects retained '..' before reading, and passes its actual
parent through additional_protected_roots. The parsed deploymentconfiguration dict contains no
sourcepath and create_app must not invent one. This common bound does not replace retained source
FD/nofollow/mount alias checks or inspect private contents.

The fixed deployment entry declares four exact canonical envpin names from the sourcecontract.
Missing/malformed T pin cannot shortcircuit independent E; sharedR/I failure deniesboth, no false
positive. Expected sourceunavailability leaves the actual journal/read/cancel routes usable.
No pin, protectedpath, reader, callback or catalog can be submitted by HTTP.
The four pins are the exact operator-owned P tuple emitted into the same rendered X; individually
well-formed strings do not establish their common derivation. The fixed initializer recomputes
T/E from I and verifies both against P before handing sources to control. T contains no I hash,
so the control reader must not claim it independently proves T-to-I preimage lineage. It validates
the trusted tuple's actual T/E bytes and source bindings, and the journal retains that tuple
unchanged; coherent operator configuration/initializer-image qualification remains an external
gate. Config edits never migrate an existing journal binding.

WebBoundary may add an explicit bounded deployment preflight branch: exact4096POST and absent
GET/HEADbody before auth, including chunked/no-length, closedquery/method/path/media parsing.
Preserve commonorigin/FetchMetadata, actualowner/session/CSRF, safetyheaders and existingcandidate/
corecaps. Parser emits only inert typed requeststate and never changes policy. No generic plugin
preflight/authhook is introduced; feature-specific HTTP parsing is not servercompositioncoupling.

### One-shot host activation after complete composition

Factories may open readers/install or verify private schema, but do not expire requests or publish
outbox files. Complete route/session/middleware construction must succeed before such effects.
InstalledContribution has optional startup_reconcile direct build-owned function (defaultNone),
called with immutable exact own_exports only. The fixed deployment catalog entry alone declares
the adapter that invokes its actual service.reconcile_startup(). No descriptor/config/HTTP supplies
or selects this function; it returns no authorization/proof. No route lifecycle hook, scheduler,
background task, retry policy, priority or dynamic activation module is added.
The supported activation function is synchronous and returns exactly None. Reject asynchronous
functions/awaitable or other returned values rather than treating unexecuted work or a truthy
return as successful activation. One-shot state is set before calling any function, including
failure, so the same publication never retries or re-enters implicitly.

FirstPartyPublication.activate_startup() holds the constructed resource owner and fixed functions
privately; it is one-shot, rejects closed/repeated/reentrant use before anyfunction call, and runs
fixedcatalog order. Common host lifespan calls it through the existing threadpool after complete
composition and before worker startup or yielding HTTP admission. Server knows no feature key/type.
Lower routercomposer continues to reject route lifespan/startuphooks. This explicitly scoped host
activation is the sole common addition, not an extension-defined effect hook.

Reconciliation visits at most16total items, cancellation projections first, then dueexpiry or
eligible request projections, one transaction peritem, no newitem beyond one-second softbudget.
Every item rechecks actual journal/time/source; a request is never published because an expired
row was not visited earlier. Expiry is systemevent/history/head/suppression only. Source-blocked
unvisited items remain pending. Exact commandreplay/GET/HEAD do not trigger this activation or
another reconciliation. New successful mutation completion can invoke the same bounded reconciler.
There is no eventual-drain promise without another mutation/restart, and no receipt or slotrelease.

Expected sourceunavailability or journalcorruption stops the concrete reconciler safely and makes
that service unavailable without hiding ordinary owner/candidate routes. Unexpected activation
exceptions fail hoststartup and close every owned resource/authority/store. A later workerstartup
failure cannot roll back projections already authorized by prior durable intent; treat it as the
same crash-recovery case and verify exactbytes/journal onrestart. Guarantee no files before complete
composition, not filesystemrollback across any later startupfailure. No new request/nonce or
installation is created by activation.

## 12. Scope of this version

The seven-table journal, source reader instances, command authority, event/blob relationships and
file publisher form one actual integration. No receipt import, signing key, successful installation,
qualification head, safe reservationrelease, scheduler, graph execution or final Settings UI is
fabricated to close this slice. Future receipt consumers explicitly migrate two-revision lifecycle
checks and use independent postconditions; no timeout/cancel manufactures absence.
