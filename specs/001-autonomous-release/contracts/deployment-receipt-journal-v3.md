# Deployment receipt journal v3 — accepted stage postcondition and absent-only installation head

Normative implementation contract for the stage after accepted receipt journal v2 (owner import,
one-use non-success consumption) and the worker-private probe channel (Task 25). It extends the
same actual `PersistentDeploymentPrepare` service, not the release scope. Writing this contract
implements no migration, observer, consumption, installation, qualification, binding or image
qualification. It is Task 24 step (a) of the redraft order recorded in `resumption-plan.md`
("### Task 24"); steps (c)–(f) implement it and each is reviewed before the next.

Authority: `deployment-receipt-journal.md` (v2 — every rule not changed below stays in force),
`deployment-receipts.md` §3/§6 (stage result arm, evidence never a request body, absent-only head,
"no accepted state until real postconditions exist"), `deployment-prepare-journal.md` §9 (the
stage request tuple and first-only managed-kind guard), `extension-worker-probe.md` §2–§6 (the only
control-side observation of a staged service), `extension-lineage-values.md` §3/§5
(`BuildIdentity.digest`, `schema_set_digest`, `validate_descriptor_lineage`), data-model §3
(`DeploymentRequestLifecycle.accepted`, `DeploymentReceiptConsumption` success rule,
`ExtensionInstallation`/`ExtensionInstallationHead`), runtime.md ("handshake and qualification
precede binding-head CAS"), ADR-008 canonical JSON.

## 1. Scope and boundary

Only the first-installation stage arm. A `receipt_pending2` request whose signed receipt says
`succeeded` may become `accepted3` exactly once, in one writer, when the core itself observes the
staged service over the slot's `broker_pair` socket and the observation equals the request tuple.
Acceptance creates, atomically: the immutable `extension_installation` record (revision 1, from an
absent head), the installation head keyed by `extension_id`, the success consumption anchor (v2),
the `deployment.request_accepted` lifecycle event and the `extension.staged` installation event,
the frozen `deployment-consume-v1` command receipt and the private index rows. Nothing else
changes: no qualification, verification, binding, enable, dispatch permit, semantic registry,
replace/uninstall/retire arm, reservation release or runtime trust. `staged ≠ verified`.

Boundary statements kept verbatim from the rejected draft's review: `staged ≠ verified`; no
qualification/binding/enable/dispatch; no replace/uninstall/retire arm; one-writer atomicity;
expiry precedence; the live end-to-end run (container, socket, worker) is Docker/colima host
authority reported as a gate, never claimed; no GUI (UX-AC11 remains open).

Evidence is never a request body (receipts §6): the consume route accepts digest selectors only;
the service performs the observation in its preseal phase exactly as it performs `J.open_receipt`,
and only the observer module (§5) can construct the evidence value. A parsed reply, a signature, a
readiness file or a browser-supplied tuple is not evidence.

## 2. Literal changed/new v3 DDL

Thirteen statements in this full order (`deployment_prepare_` prefix): migrations, control,
requests, lifecycle, heads, commands, outbox, receipt_sources, receipts, consumptions,
consumed_outbox, installations, installation_heads. Control, requests, heads, outbox,
receipt_sources, receipts and consumed_outbox stay byte-identical to their v1/v2 strings; the four
changed statements (migrations, lifecycle, commands, consumptions) and the two new ones are below.
Execute only those six. `CHECKSUM_V3 = SHA256(canonical_json(full ordered thirteen-item list))`,
excluding Markdown fences; never derived from `sqlite_schema`. C1 and C2 are preserved.

```sql
CREATE TABLE deployment_prepare_migrations (
 version INTEGER PRIMARY KEY CHECK(version IN (1,2,3)),
 checksum TEXT NOT NULL CHECK(length(checksum)=64)
);
CREATE TABLE deployment_prepare_lifecycle (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 3),
 previous_revision INTEGER, previous_hash TEXT,
 state TEXT NOT NULL CHECK(state IN ('prepared','cancelled','expired','receipt_pending','rejected','accepted')),
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
  OR (revision=3 AND state IN ('cancelled','expired','accepted') AND previous_revision IS NOT NULL AND previous_revision=2 AND previous_hash IS NOT NULL)),
 CHECK((state='expired' AND command_id IS NULL) OR (state<>'expired' AND command_id IS NOT NULL))
);
CREATE TABLE deployment_prepare_commands (
 command_id TEXT PRIMARY KEY CHECK(length(command_id)=36),
 namespace TEXT NOT NULL CHECK(namespace IN ('deployment-prepare-v1','deployment-cancel-v1','deployment-cancel-v2','deployment-receipt-import-v1','deployment-consume-v1')),
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
  OR (namespace='deployment-receipt-import-v1' AND http_status=200 AND lifecycle_revision=2)
  OR (namespace='deployment-consume-v1' AND http_status=200 AND lifecycle_revision=3))
);
CREATE TABLE deployment_prepare_consumptions (
 request_id TEXT PRIMARY KEY, receipt_sha256 TEXT NOT NULL UNIQUE CHECK(length(receipt_sha256)=64),
 consumption_id TEXT NOT NULL UNIQUE CHECK(length(consumption_id)=36), vault_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='deployment_receipt_consumption'), version INTEGER NOT NULL CHECK(version=1),
 anchor_digest TEXT NOT NULL CHECK(length(anchor_digest)=64),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision IN (2,3)),
 command_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_commands(command_id),
 event_id TEXT NOT NULL UNIQUE REFERENCES api_event_envelopes(event_id),
 consumed_ms INTEGER NOT NULL CHECK(consumed_ms BETWEEN 0 AND 253402300799999),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(request_id,receipt_sha256) REFERENCES deployment_prepare_receipts(request_id,receipt_sha256),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 FOREIGN KEY(vault_id,kind,consumption_id,version,anchor_digest) REFERENCES domain_records(vault_id,kind,id,version,sha256)
);
CREATE TABLE deployment_prepare_installations (
 request_id TEXT PRIMARY KEY REFERENCES deployment_prepare_requests(request_id),
 extension_id TEXT NOT NULL UNIQUE CHECK(length(extension_id) BETWEEN 1 AND 128),
 vault_id TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose='operational'),
 kind TEXT NOT NULL CHECK(kind='extension_installation'),
 installation_id TEXT NOT NULL UNIQUE CHECK(length(installation_id)=36),
 version INTEGER NOT NULL CHECK(version=1), anchor_digest TEXT NOT NULL CHECK(length(anchor_digest)=64),
 evidence_sha256 TEXT NOT NULL UNIQUE CHECK(length(evidence_sha256)=64),
 evidence_size INTEGER NOT NULL CHECK(evidence_size BETWEEN 1 AND 8192),
 consumption_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_consumptions(consumption_id),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision=3),
 command_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_commands(command_id),
 event_id TEXT NOT NULL UNIQUE REFERENCES api_event_envelopes(event_id),
 installed_ms INTEGER NOT NULL CHECK(installed_ms BETWEEN 0 AND 253402300799999),
 hash TEXT NOT NULL CHECK(length(hash)=64), UNIQUE(extension_id,request_id),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 FOREIGN KEY(vault_id,purpose,evidence_sha256) REFERENCES domain_blobs(vault_id,purpose,sha256),
 FOREIGN KEY(vault_id,kind,installation_id,version,anchor_digest) REFERENCES domain_records(vault_id,kind,id,version,sha256)
);
CREATE TABLE deployment_prepare_installation_heads (
 extension_id TEXT PRIMARY KEY REFERENCES deployment_prepare_installations(extension_id),
 request_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_installations(request_id),
 revision INTEGER NOT NULL CHECK(revision=1),
 installation_anchor_digest TEXT NOT NULL CHECK(length(installation_anchor_digest)=64),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(extension_id,request_id) REFERENCES deployment_prepare_installations(extension_id,request_id)
);
```

Row hashing: the six historical suffixes keep `deployment-prepare-storage-v1`; the four v2
suffixes keep `deployment-prepare-storage-v2`; `installations` and `installation_heads` use
namespace `deployment-prepare-storage-v3`. Row excludes only `hash`. `installations.event_id` is the
`extension.staged` event; the consumption row's `event_id` is the `deployment.request_accepted`
event. `UNIQUE(extension_id)` on installations and `revision=1` on the head are the absent-only
rule in SQL: there is no tombstone, replace or retire branch, and no CAS `advance` exists for
`installation_heads` in v3 (it arrives with uninstall-current). Capacities: installations 16,
installation_heads 16; migrations exactly three rows; lifecycle and commands stay 48. No indexes,
triggers, views, cascade, replacement or pruning.

## 3. Migration v2 → v3

Same algorithm and guarantees as v1 → v2 (journal v2 §3), applied to the exact v2 shape:
unconditional at upgraded construction, in the actual DomainStore writer, `foreign_keys=ON`
throughout, `PRAGMA defer_foreign_keys=ON` verified as 1, no rename/TEMP/attached DB/
`executescript`/`writable_schema`, one transaction, any fault rolls back to exact v2. Preflight the
exact v2 schema, rows `{(1,C1),(2,C2)}`, per-column typeof/UTF-8 length/caps and the whole v2
verifier before any DDL. Snapshot typed rows of migrations (2), lifecycle (48), commands (48),
consumptions (16) in bounded memory ordered by PK; DELETE consumptions, commands (descending
`lifecycle_revision`), lifecycle (descending revision), migrations; DROP consumptions, commands,
lifecycle, migrations; CREATE the four changed and two new statements with individual
`db.execute` calls; restore migrations `(1,C1),(2,C2)` exactly, then lifecycle, commands,
consumptions with explicit column lists and original values/hashes (deferred lifecycle→command FK
permits the order); insert `(3,C3)`; prove snapshot equality, unchanged control/requests/heads/
outbox/receipt_sources/receipts/consumed_outbox rows, unchanged domain bytes/associations/event
stream; run the whole v3 verifier and `PRAGMA foreign_key_check`; commit. Unlike v1 → v2, the
children of the recreated parents are **not** emptied: heads, outbox and receipts (→ lifecycle,
→ commands) and consumed_outbox (→ consumptions) stay populated throughout. This relies on the
stated SQLite semantics, which the migration tests must prove on the supported version: with
`defer_foreign_keys=ON` each parent-row DELETE raises the deferred violation counter, DROP/CREATE
leave it untouched (child constraints resolve the parent by name), the restores lower it to zero,
`foreign_key_check` is empty and COMMIT succeeds; a COMMIT attempted without the restores is
refused by SQLite ("FOREIGN KEY constraint failed") and rolls back to exact v2. Snapshotting or
deleting those child tables is neither required nor permitted. Already-v3 startup requires exact rows
`{(1,C1),(2,C2),(3,C3)}`, thirteen exact tables and whole-v3 integrity. v3 is forward-only; v1 and
v2 code must reject it (`storage.install`, `records.install_storage` and `_rebuild_v1_as_v2` stay
honest v1/v2-only helpers). A v1 database migrates v1 → v2 → v3 in the same writer by the two
existing algorithms in sequence, each verified before the next. Migration itself never observes,
consumes, expires or publishes.

## 4. Immutable records, evidence blob and bijections

**Evidence blob** (`extension-stage-postcondition-v1`, operational purpose, canonical JSON ≤ 8192
bytes, constructed only by the observer module §5, presealed with `put_blob` outside the final
writer like receipt bytes):

```text
{schema_version:"extension-stage-postcondition-v1",
 request_id:UUID, request_digest:B32, receipt_digest:B32,
 request_blob_sha256:H, receipt_blob_sha256:H,
 observed_at:Time, attempt_ms:1..2000,
 connection:{channel_id:BrokerId, connection_id:H, requester_boot_id:H, responder_boot_id:H,
             peer_uid:UInt32, peer_gid:UInt32},
 probes:[Probe, Probe],
 expected:{service_identity:BrokerId, build_identity_digest:H, port_schema_set_digest:H,
           port_contract_version:"tool-port-v1", platform:"linux/amd64"|"linux/arm64",
           uid:UInt32, gid:UInt32},
 comparison:"equal"}
Probe = {challenge:Nonce, request_message_id:UUID, reply_message_id:UUID,
         reply:{service_identity, component:{build_identity_digest,port_contract_version,
                port_schema_set_digest}, runtime:{platform,uid,gid,registered_operations}}}
```

Grammars are the probe contract's (§2): `H` hex64, `Nonce` 43-char base64url, `UInt32` 1..2^32-1,
`BrokerId` the broker identifier. `connection_id` is the session's SHA-256 hexdigest; the two boot
ids are pinned to `H` although the transport grammar (`_BOOT_ID`) admits more — both real
producers use `secrets.token_hex(32)`, and a session whose boot ids are outside hex64 is
`probe_invalid`. Exactly two probes with distinct challenges and four distinct message ids;
`request_blob_sha256`/`receipt_blob_sha256` are the SHA-256 of the retained request bytes
(`item["raw"]`) and receipt bytes, and every reply repeats them and its challenge verbatim.

`expected` (`ExpectedStageIdentity`, a frozen typed value) is derived by the service from retained
records only, in the first writer, through exactly this path: `service_identity` and `uid`/`gid`
from `deployment.contracts.slot(instance_id, row.slot_id)` of the request's admitted slot (equal to
`new_service_effect.service_identity` and the T tuple); `platform` from
`selected_platform_entry.platform`; the candidate bundle reconstructed by `records.candidate(...)`
(as the verifier already does), `lineage = parse_lineage(<the bundle's "provenance"
support-document bytes>)`, `validate_descriptor_lineage(lineage, bundle.descriptor,
instance_id=<control instance_id>, slot_number=row.slot_id)`, then
`build_identity_digest = parse_build_identity(canonical_json(lineage.selected_platform(platform)
["build_identity"])).digest` (SHA-256 of the canonical embedded identity, equal to the worker's
file digest because `parse_build_identity` refuses non-canonical bytes),
`port_schema_set_digest` = that identity's `schema_set_digest`, and `port_contract_version` = the
lineage's `port_contract_version`. A candidate whose provenance document is not a valid
`extension-build-lineage-v1`, or which fails the descriptor join, denies **409 conflict** in the
first writer with no observation, no transition and no blob. The whole-journal verifier re-derives
`expected` through the same path from the retained candidate, never from the blob alone.
`comparison:"equal"` is the only admissible value and is recomputed by the verifier from the two
replies, `expected` and `connection.peer_uid/peer_gid == expected.uid/gid`: every compared field of
both replies equals `expected`. `registered_operations` is recorded, not compared (a staged worker
reports `[]`; a value is not qualification). A blob with any other comparison, one probe, a repeated
challenge, an unequal field or a peer outside the slot never exists: the observer returns a closed
failure and nothing is presealed.

**Installation anchor** (kind `extension_installation`, version 1, id = host-generated UUID,
parents `[request_ref, receipt_ref]`, blobs `[evidence_blob_ref]`, `ImmutableRecord.create`,
operational, actual human actor and persisted policy roots, `created_at_utc` = acceptance now):

```text
{schema_version:"extension-installation-anchor-v1",
 extension_id:Id, manifest_digest:H, service_descriptor_digest:H,
 selected_platform_entry_digest:H, image_manifest_digest:"sha256:"+H, platform:Platform,
 service_identity:BrokerId, staging_authority:"deployment-receipt-v1",
 request_ref:EntityRef, receipt_ref:EntityRef, postcondition_evidence_blob_ref:BlobRef,
 consume_command_id:UUID, state:"staged", revision:1, previous_record_digest:null,
 installed_at:Time, actor_ref}
```

Every tuple field equals the request's `effect_payload` and the receipt's `Present` result;
`selected_platform_entry_digest` is SHA-256 of the canonical `selected_platform_entry`. Ruling on
the existing `extension-installation-v1` (`app/extensions/contracts.py::ExtensionInstallation`,
with `verification_refs`/`scan_refs`): it **coexists** as the registry-owned in-memory shape of the
T087 framework and is never written as a domain anchor by this path; the durable anchor content of
kind `extension_installation` is `extension-installation-anchor-v1` above, validated by a new
`app/domain/extension_installation.py` (`installation_content_schema()`,
`validate_installation_body(body)`), registered in `schemas.py`/`schema_exports.py` for the one
kind with regenerated envelope exports (Task 10 precedent). T087's registry must adopt this anchor
as the durable head input when it lands; it may not introduce a second durable installation shape.

**Consumption anchor v2** (kind `deployment_receipt_consumption`, version 1, id = host UUID,
parents `[request_ref, receipt_ref, installation_ref]`, no blobs):

```text
{schema_version:"deployment-receipt-consumption-anchor-v2",
 request_ref, receipt_ref, winning_lifecycle_revision:3, consumed_at:Time, actor_ref,
 transaction_id:consume_command_id, public_event_id:<deployment.request_accepted event_id>,
 outcome:"succeeded", effect_ref:<installation EntityRef>}
```

`validate_consumption_body` dispatches on `schema_version`: v1 keeps its exact v2-journal rules
(`winning_lifecycle_revision:2`, `outcome ∈ {failed,unknown}`, no `effect_ref`); v2 requires
revision 3, `outcome:"succeeded"` and an `effect_ref` of kind `extension_installation`. The
installation anchor is put before the consumption anchor (its digest is `effect_ref`); the
installation content carries `consume_command_id`, never the consumption ref, so no digest cycle
exists. Time relations, six-digit padding and Time grammar are as in v2 §4.

**Bijections** (whole verification, each ≤ 16): installations ↔ `extension_installation` anchors;
installation_heads ↔ installations (head iff installation; `installation_anchor_digest` equals the
row's `anchor_digest`; revision 1); accepted3 ↔ exactly one consumption with `lifecycle_revision=3`,
a v2 anchor whose `effect_ref` is that installation, and **no** consumed outbox row; installation
`consumption_id`/`command_id` equal that consumption's; `evidence_sha256`/`evidence_size` match the
actual blob bytes and the anchor's `postcondition_evidence_blob_ref`; the blob recomputes
`comparison:"equal"` against `expected`, which the verifier re-derives from the retained request
and lineage records (never from the blob alone). Rejected2 keeps exactly one v1 consumption with a
consumed outbox; receipt_pending2, cancelled3 and expired3 keep zero consumptions. No installation
row without accepted3; no accepted3 without receipt_pending2 and a `succeeded` receipt. The
`extension.staged` event is verified through `installations.event_id` (object, actor, times,
correlation, causation = the accepted event id, metadata) and is excluded from the v2 "deployment
event universe ≤ 48 compared to lifecycle ids" count, which gains only `deployment.request_accepted`.

## 5. Observer and one-writer transaction (steps (d) and (e))

`app/deployment/stage_observer.py` is the only constructor of the evidence value:

```python
class StagePostconditionError(Exception): code: str   # closed: probe_unavailable, probe_mismatch,
                                                      # probe_deadline, probe_invalid
class ExpectedStageIdentity:                          # frozen typed value (§4), built only by the
                                                      # service from retained records
class StagePostconditionEvidence:                     # frozen, nonconstructible; .content_bytes,
                                                      # .digest, .size; no live socket retained
def observe_stage_postcondition(*, request_id, request_digest, receipt_digest, request_bytes,
        receipt_bytes, slot_number, instance_id, expected: ExpectedStageIdentity,
        deadline) -> StagePostconditionEvidence
```

It derives the pair root and `ChannelSpec` through `extension_channel`, connects with
`_connect_extension_authenticated` (readiness, populated fence, mount fence read-only, exact socket
inode, peer retained) under the module's own process boot ID (`secrets.token_hex(32)` generated
once per process inside the observer; it is not a parameter and never an owner account), sends
exactly two probes (`encode_probe_request` with fresh `os.urandom(32)` challenges and fresh non-nil
UUIDs), reads each reply under the remaining attempt budget (whole attempt ≤ 2000 ms measured from
before connect; the final probe ≤ 500 ms), `recheck()`s the connection after each reply, parses
with `parse_probe_reply`, verifies correlation (`message_type` `extension-result-v1`, the reply's
`correlation_id` equal to the probe request frame's `message_id`, a fresh non-nil reply id), the
verbatim digests/challenge, `service_identity == spec.responder_service`, `peer.uid/gid ==
expected.uid/gid`, and equality of every compared field of both replies to `expected`. Any
deviation is a closed error; a mismatch is `probe_mismatch` and creates no admission (journal v2
§5 "invalid evidence never creates an admission"). The observer imports nothing from
`app.api`/`app.static`/`app.server`. The in-process test
responder is the actual `WorkerProbeService` over the macOS seams; positive Linux authentication,
the real worker image and the container/socket runtime remain host gates.

Consume transaction (`PersistentDeploymentPrepare.consume_receipt(authenticated_request,
request_id, payload) -> dict`, same `@closed` lock, no callback, nested public read or new store):
authenticate the actual owner/request; verify the full journal and replay; commit the durable clock
checkpoint. In an actual writer, check the matching request digest, head `receipt_pending2`,
`expected_revision:2` and a `succeeded` receipt, then the first-only managed-kind absence exactly
as journal v2 §5 and `prepare_service.py` define it: a **global** `SELECT 1 FROM domain_records
WHERE kind IN ('extension_installation','extension_qualification','extension_binding')` with no
extension filter. Consequently, while this guard stands, a v3 journal holds at most one accepted3
and one installation; after the first acceptance every later prepare, import and consume — for
any request and any extension — is 409 (the v2 rule, unchanged), a second consume of the same
request is a replay or 409, and the caps of 16 on installations/installation_heads are structural
row bounds, not admissible cardinality. Relaxing the guard to per-extension is a later contract
change that arrives with the replace/uninstall arms, not this one. If that matching head is
already due, commit `expired3` only and return 409 without touching the socket (expiry
precedence). Otherwise re-read the retained request/receipt bytes and the candidate bundle in that
writer, derive `expected` (§4; a lineage/descriptor-join failure is 409 here), leave the writer,
run the observer
(preseal phase), preseal the evidence blob with `put_blob`. In the final writer repeat auth, replay,
journal, head, digest, receipt outcome, time (now < expires, observation completed before now) and
the managed-kind absence; put the installation anchor; append the `deployment.request_accepted`
transition through `commit_receipt_transition`'s sibling (`_append_transition` with
`state="accepted"`, `previous.state == "receipt_pending"`); append the `extension.staged` event with
the installation ObjectRef; put the consumption anchor v2 with the returned lifecycle event id;
insert the consume command receipt, the consumption row (`lifecycle_revision=3`), the installation
row and the installation head; verify the full v3 journal; commit once. Any failure after the
preseal rolls back all authority; only the unattached presealed blob may remain (it is never
admitted later without a fresh observation). No filesystem publication and no K marker exist for
success; the request outbox was already suppressed at revision 2.

## 6. Admission, API, events and replay

| Actual head and fresh matching command | now < expires | now ≥ expires |
| --- | --- | --- |
| receipt_pending2 (succeeded) + consume, observation equal | accepted3: installation record/head, consumption v2, two events, command 200 | expired3; 409, no observation |
| receipt_pending2 + consume, observation unavailable/deadline/invalid | 503 dependency_unavailable, no transition, no blob | expired3; 409 |
| receipt_pending2 + consume, observation mismatch | 409 conflict (`probe_mismatch`), no transition, no blob | expired3; 409 |
| receipt_pending2 + cancel | cancelled3 (unchanged v2 rule) | expired3; 409 |
| accepted3 + any command (consume, cancel, import) | 409 | 409 (accepted never expires) |
| rejected2/cancelled/expired + consume | 409 | 409 |

Background expiry stays limited to prepared1/receipt_pending2; accepted3 is terminal for this
contract. Cancel that wins first still rejects a later consume. A replayed consume with the exact
same command/body/actor returns the frozen 200 body without a new observation.

Owner-session-only POST `/api/v1/deployment/requests/{request_id}/consume`, route identity
`deployment.requests.consume`, `deployment.manage`, browser_session only, same transport limits
(4096 B, depth 4, items 32, members 8, string 256, no query). Body exactly
`{command_id:UUID, request_digest:B32, receipt_digest:B32, expected_revision:2}`. Frozen 200 body:

```text
{command_id, request_id, receipt_digest, outcome:"succeeded", disposition:"consumed_success",
 revision:3, installation:{installation_id:UUID, extension_id:Id, installation_digest:HexDigest,
 revision:1}, event_cursor}
```

`installation_digest` is the installation anchor's envelope `sha256` (= `installations.anchor_digest`
= `installation_heads.installation_anchor_digest`); with `installation_id` it lets a client build
the exact EntityRef the staged event carries.

`prepare-api-v3` (separately named artifact and export in `prepare_v3_schema_exports.py`; v1/v2
artifact bytes unchanged): GET/HEAD add state `accepted`, `receipt.disposition` gains
`consumed_success` (paired with `outcome:"succeeded"` and `revision:3`), and a new field
`installation: null | {installation_id, extension_id, installation_digest, revision:1}`;
`consumption_publication_state` is `null` for a success consumption. `lifecycle.disposition()` is
outcome-only: v3 `read_body` derives `consumed_success` from the accepted3 head, while the stored
revision-2 import command `receipt_json` keeps its frozen `pending_postconditions` unchanged.
`cancellation-v2` and the v1/v2 command reply schemas are unchanged; the consume reply schema is
new. Import command `expected_revision` stays 1; consume is 2; cancel-v2 is 2. `_admit`/`_replay`
gain the fixed operation string `consume` whose only namespace is `deployment-consume-v1` (command
lookup before head interpretation, journal v2 §10).

| Transition | Event type | status / error_code | object | exact metadata |
| --- | --- | --- | --- | --- |
| accepted3 | deployment.request_accepted (new registration, `revision=COUNT`, next to the existing deployment events) | succeeded / null | request ObjectRef (as v2) | {revision:3} |
| installation revision 1 | extension.staged (existing registration) | succeeded / null | `ObjectRef(kind="extension_installation", id=installation_id, version=1, content_hash=anchor_digest)` | {extension_kind, trust_tier, revision:1} |

Registering `deployment.request_accepted` changes `EVENT_TYPES`, so the byte-pinned
`schemas/v1/event-metadata.schema.json` export is regenerated together with the
`extension_installation` domain-envelope export.

Both events are appended in the one writer with `private_evidence_refs=[]`, `causation_id` of the
staged event = the accepted event id, `correlation` = the consume command id, actor = the actual
human owner, policy root, retention core, both times = the transition time. `extension_kind` and
`trust_tier` come from the candidate manifest's admitted tuple. No signer facts, digests, nonces or
boot ids appear in public metadata.

Errors keep the v2 envelope: malformed selector/body 400 invalid_input; request 404 only after
auth/integrity; wrong binding/lifecycle/late/replay conflict 409; observer unavailable/deadline 503
dependency_unavailable; mismatch 409 conflict; corrupt journal 503 unavailable; auth 401/403; body
413; capacity 429. Command input digest is canonical `{namespace,instance_id,origin_digest,
actor_ref,input}` with namespace `deployment-consume-v1`.

## 7. Storage and records APIs

`prepare_storage.py` adds `DDL_V3`, `CHECKSUM_V3`, `SHAPE_V3`, `COLUMNS_V3`, `TABLES_V3`
(`TABLES_V2 + ("installations","installation_heads")`), `CAPS_V3`, `NULLABLE_V3` next to the v1/v2
constants (whose meanings stay fixed); `_layout` observes the exact stored shape and dispatches
three private layouts; `digest` accepts the two new suffixes under storage-v3; `insert` validates
v3 rows; `advance` gains no new allowed-column set (installation heads are insert-only in v3);
`verify`, `validate_current_row`, `records.verify/private_sizes` admit any exact stored shape;
`records.install(domain, db, profile, *, candidate_registry)` remains the sole install/upgrade
entry and runs v1→v2→v3 as needed. `prepare_records.py` adds
`_load_installation(domain, db, roots, item, consumption, row) -> dict` and
`_load_installation_head(...)`; each loaded item gains `installation` (None or verified data).
`prepare_lifecycle.py` extends `_append_transition`'s finite matrix with
`receipt_pending → accepted`, adds `commit_acceptance_transition(...)` (sibling of
`commit_receipt_transition`, returns the actual event and frozen consume reply), and `read_body`
emits the v3 fields. Pure `prepare_v3_contracts.py`: `parse_consume(request_id, value) -> dict`.
No sidecar service, router or runtime schema knob.

## 8. Frozen checksums and acceptance

```
CHECKSUM     68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec  (C1, seven statements)
CHECKSUM_V2  d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f  (C2, eleven statements)
CHECKSUM_V3  ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457  (C3, thirteen statements)
```

C3 is SHA-256 of the canonical JSON list of the thirteen exact strings (the seven unchanged
statements imported byte-identical from `DDL`/`DDL_V2`, plus the six above); it was computed from
those literals, never from an introspected schema. Assert all three from literal constants.

Minimum connected verification before any step claims acceptance: v2 → v3 migration of empty and
mixed sixteen-request histories (including rejected2 with consumed outbox and receipt_pending2
with cancelled3/expired3; after acceptance, at most one accepted3 per journal under the global
guard), fault injection after every delete/drop/create/restore/insert/commit with exact v2
rollback, the commit-without-restores case refused by SQLite with exact v2 rollback, old helpers
rejecting v3; observer against the actual in-process
`WorkerProbeService` (macOS seams) for the equal case and every closed failure (transport, deadline,
mismatch per field, repeated challenge, peer mismatch, wrong service identity), with no blob for
any failure; consume transaction with fault injection at every stage (after preseal, after
installation anchor, after each event, after each index row, before commit) rolling back all
authority; competing consume/consume, cancel/consume and expiry/consume serialization; exact
replay; a second stage of the same extension denied by the managed-kind guard; GET v3 versus frozen
v1/v2 replies; whole-v3 verifier recomputing the evidence comparison; the import-boundary check.
Reported gates, never claimed: the live container/socket/worker run, positive Linux authentication,
both native architectures, image and OCI identity trust, qualification/binding, UX-AC11 GUI.
