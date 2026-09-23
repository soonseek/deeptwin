# Actual provider request integration

Controller contract, 2026-09-19. State: Task41 ACCEPTED after independent R1 spec/quality review.
Initial graph tests lacked pre-implementation RED; that disclosed procedural deviation is retained
in the ledger. Final R1 eight-family199pass/one inherited warning, exact719 preservation; earlier
failed32 and ordered421 runs remain separate evidence. No native/provider-readiness claim.
Original implementation prerequisites were accepted Tasks37–40 and explicit dispatch; user-approved autonomous continuation governs technical
recommendations without broadening operational authority. No native/network/user-data/key/commit/push
action is authorized. The checksum below was independently checked using text/AST only; no application
module import or SQLite execution at design time. Implementation evidence is in task-41-report.md
and task-41-r1-review.md under .superpowers/sdd/resumption-plan/.

Authority: ../spec.md FR-032 / ../decisions.md ADR-014; accepted deployment-receipt-journal-v3.md,
provider-source-context.md, provider-prepare-protocol.md and provider-publication.md.
Accepted Task40 slot-lifetime correction is a prerequisite. Tasks37–40 must be accepted before
implementation, not merely present. Task38's moving implementation was not inspected for this draft.

## 1. Outcome and fixed boundary

Implement one real vertical integration: v4 migration and historical verification, actual owner
prepare/cancel/read commands, scoped publication/reconciliation and reachable browser routes.
Do not deliver unused tables, a parallel registry, a context-register endpoint or a mock-success API.

New admission supports one original topology, one provider source context/epoch1, zero or one
already-staged legacy tool installation, and a never-reserved extension and physical slot. All other
requests must be terminal when a new provider prepare is admitted. Provider history is prepared1
→ cancelled2 or expired2 only. All original tool histories and old wire/replay bytes remain valid.

No native operator, receipt import/consumption for providers, provider installation/head update,
qualification, binding, connection/model choice, credential/billing/approval authority or live send.
No topology/context rotation, replacement/recycling, second slot registry, task scheduler or retry
route. Task30 stored_unbound credentials and Task32 generation denial remain; Claude API-only and
Codex subscription plus optional API scope remain. Private identity/catalog observations and schema
measurements do not establish semantic operation implementation or all-five-check qualification.
Controlled tests prove code behavior, never native provisioning/image provenance/packaging success.

## 2. Exact ownership:30 paths

Fifteen NEW paths:

| Path | Sole responsibility |
| --- | --- |
| app/deployment/provider_prepare_records.py | Actual CAS/context/inventory/history joins and core provider-v1 schema-byte projection. |
| app/deployment/provider_prepare_lifecycle.py | Provider transitions, frozen/read response construction and historical lifecycle verifier. |
| app/deployment/provider_prepare_service.py | Private orchestration delegated by the existing actual service; no parallel owner/domain/service. |
| app/deployment/provider_prepare_api_schema_exports.py | Three new closed API/response exports. |
| app/api/provider_deployment_prepare.py | Provider-only fixed router and preflight. |
| app/tests/provider_prepare_fixture.py | Real isolated DomainStore/owner/candidate/history plus accepted source fixture. |
| app/tests/test_provider_prepare_migration.py | Exact v4 migration, real historical preservation and rollback. |
| app/tests/test_provider_prepare_records.py | Actual CAS/graph/vault/context/inventory/event corruption checks. |
| app/tests/test_provider_prepare_service.py | Actual authenticated prepare/cancel/read, races, expiry and replay. |
| app/tests/test_provider_prepare_reconciliation.py | Actual39 publisher plus journal crash/time/source-currentness checks. |
| app/tests/test_provider_prepare_api.py | Actual startup/composition/web-boundary/routes and HTTP bytes. |
| app/tests/test_provider_prepare_api_schema_exports.py | Three exact exports, response closure/limits and four core schema-byte parity. |
| schemas/v2/deployment/provider-command-receipt-v1.schema.json | Closed prepared/cancelled command receipt. |
| schemas/v2/deployment/provider-request-read-v1.schema.json | Closed current historical read representation. |
| schemas/v2/deployment/provider-prepare-api-v1.schema.json | Closed input/receipt/read/error union. |

Fifteen MODIFIED paths:

| Path | Permitted scope |
| --- | --- |
| app/deployment/prepare_storage.py | Literal v4 layout/caps/hash/row validation and transaction-bound v3→v4 rebuild. |
| app/deployment/prepare_records.py | Install-chain extension, bounded provider discriminator dispatch and inventory verification after legacy installations load. |
| app/deployment/prepare_lifecycle.py | Exact provider dispatch in cancellation_payload and verify only; old branches unchanged. |
| app/deployment/prepare_service.py | Optional borrowed provider context, three methods/two replay operations, provider reconcile dispatch and wrong-family endpoint exclusion. Preserve40 lifetime corrections. |
| app/domain/deployment_request.py | Register exact provider anchor content discriminator; old anchor_content_schema/export unchanged. |
| app/api/deployment_prepare.py | Pass SAME startup-owned37 context to actual service; include provider router. Preserve old preflight/responses and resource ownership. |
| app/api/web_boundary.py | Separate provider path/preflight/body limits/state hook through existing auth/error boundary. |
| app/api/route_contributions/deployment-prepare-v1.json | Append exactly three routes; preserve five old entries/factory/contribution ID. |
| app/tests/test_deployment_receipt_migration.py | Only actual current-startup C1–C4/SHAPE_V4 expectations and directly dependent fixtures/comments; preserve legacy migration/business assertions. |
| app/tests/test_deployment_journal_v3_migration.py | Only actual current-startup C1–C4/SHAPE_V4/_V4 expectations and directly dependent fixtures/comments; preserve old migration/fault-injection/history assertions. |
| app/tests/test_first_party.py | Actual route count 29→32 and directly related comments only. |
| app/tests/test_provider_source_startup.py | Actual route count 28→31/comments; in test_frozen_pin_and_original_five_source_arguments only, extend the exact constructor-kwargs expectation with provider_source_context: source. Preserve all five original identities, frozen-pin/env assertions, owned_resources order and close assertions. |
| app/tests/test_deployment_prepare_integrity.py | Only test_install_routing_preserves_absent_schema_initialization: change its final current-shape expectation SHAPE_V3→SHAPE_V4 and adjacent current-version comment. Preserve both constructor/records_install arms, empty-schema and empty-data assertions, not_found, and every separate retained-anchor/authority/integrity assertion. |
| app/tests/test_deployment_receipt_api.py | Only test_actual_v1_cold_http_upgrade_preserves_historical_reply_bytes: append exact (4,C4) to the final current migration list, advance final SHAPE_V3→SHAPE_V4 and adjacent current-version comment. Preserve C1–C3 literals, actual v1 history snapshot equality, owner/login, old install refusal and all replayed HTTP bytes/assertions. |
| app/tests/test_provider_sources.py | Only test_import_performs_no_source_or_mount_io: move the import-I/O check into a fresh finite-time subprocess with successful exit/output checked. Retain all three forbidden operations (Directory.open, read_mountinfo, native_platform) while genuinely importing provider_sources; do not reload it in the parent. Local standard-library harness imports are permitted in that function only. Preserve all other source tests and the production exact ProviderSourceContext guard; no module/guard replacement to fake success. |

No other files writable. In particular no source37/publisher39/IPC40 helper rewrite, new catalog
export/key/scope/contribution, domain refs/store/public-events change, old schema widening, unlisted old test
expectation edits, original images/Compose/initializer/operator edits or dependency addition.

## 3. Fixed interfaces and dependency consumption

PersistentDeploymentPrepare remains the exact existing owner/domain/registry/RLock service.
Append keyword provider_source_context=None; accept None or exact accepted ProviderSourceContext,
borrow it and never close it. Constructor historical migration/verification does not require a live
source check. Existing5 source arguments/defaults and actual same-owner/domain checks remain.

Add @closed service methods, delegated to same-named private module functions whose first argument
is service:

    prepare_provider(authenticated_request, payload) -> dict
    cancel_provider(authenticated_request, request_id, payload) -> dict
    read_provider(authenticated_request, request_id) -> dict

Private provider service also owns reconcile_item(service, request_id: str, role: str) -> None;
only request/cancel roles, only actual verified journal intents, never browser bytes/auth flags.

Existing migration APIs:

    prepare_storage._rebuild_v3_as_v4(db) -> None
    prepare_records.install(domain, db, profile, *, candidate_registry) -> dict

Private provider records APIs:

    _provider_schema_bytes() -> tuple[bytes, bytes, bytes, bytes]
    load_context(domain, db, roots, profile, control, rows) -> dict | None
    load(domain, db, roots, profile, control, row, *, context, provider_row) -> dict
    inventory(domain, db, roots, profile, journal, *,
              source_bundle_files, at_event_sequence: int) -> bytes
    verify_inventories(domain, db, roots, profile, journal) -> None

These dictionaries are private transaction-local projections of actual verified rows/CAS, not public
caller-dict admission APIs. Provider lifecycle APIs:

    transition(db, roots, profile, item, *, state, now, actor_ref, value=None) -> dict | None
    cancellation_payload(item, *, profile) -> bytes
    read_body(item) -> dict
    verify(db, roots, profile, item, commands) -> None

API module:

    PATH = "/api/v1/deployment/provider-requests"
    preflight(scope, body, content_type) -> dict | None
    create_router(*, service: PersistentDeploymentPrepare, base_path: str) -> APIRouter

Use37 read_current/recheck_current and39 open_provider_outbox_lease(context, *, profile,
expected_payloads), observe_existing(*,role,request_digest), stage(*,role,request_digest),
commit(attempt), close unchanged. Commit consumes its attempt on every exit. Source context remains
read-only/borrowed;39 internally uses its accepted combined same-guard publication observation,
not the superseded identity-only accessor.40 supplies actual original _acquire slot lease ownership.

Task38 parsers/constructors and exact wire remain unchanged. Prepare input required fields only:
{command_id:UUID,kind:"extension_stage",candidate_id:UUID,slot_id:int1..16,
 expires_in_seconds:int60..86400,source_context_sha256:H}.
Cancel POST body only {command_id:UUID,request_digest:B32,expected_revision:1}; path request_id
is bound by parse_provider_cancel and its normalized private input includes that selector.

H means lower-case hex64. UUID is canonical lower-case nonnil36. B32 is canonical unpadded base64url
of32 bytes (43 chars, final char in AEIMQUYcgkosw048). No bool-as-int, coercion, unknown/duplicate
fields, malformed UTF8/noncanonical retained JSON. Task38 request/inventory/cancel caps remain
65536/16384/8192; anchor content8192; input4096. Do not rewrite a provider discriminator to use v1.

## 4. Three exact closed response/API schemas

All objects below require EVERY listed field and additionalProperties=false, including links and
error objects. Enum/state relations use exact oneOf arms, not optional unions permitting mixed states.
Use Draft2020-12, $id urn:deeptwin:schemas:v2:deployment:{filename-stem}, detached factory dictionaries,
sorted UTF8 two-space JSON with final newline for schema files. Wire is domain canonical_json.
Byte caps are runtime UTF8/canonical-byte checks; JSON Schema character limits do not substitute.

Factories: provider_command_receipt_schema(), provider_request_read_schema(),
provider_prepare_api_schema(); exported_schemas() maps exactly the three filenames in§2.
Use38's exact already-owned request/input schema factories inline; no network $ref resolution,
new request schema, or change to its seven exports.

### A. provider-command-receipt-v1

Exact required fields/types:
command_id:UUID; request_id:UUID; request_digest:B32; kind constant extension_stage;
state:prepared|cancelled; revision integer1|2; publication_state:pending|published|suppressed;
cancellation_publication_state:null|pending; source_context_sha256:H;
preserved_inventory_sha256:H; event_cursor:string1..4096; links:closed object below.
Canonical response<=8192B. event_cursor must be the actual frozen event cursor, checked using the
existing cursor decoder/stream relation, not merely a syntactically permitted arbitrary string.

| state | revision | publication_state | cancellation_publication_state | HTTP |
| --- | --- | --- | --- | --- |
| prepared |1|pending|null|201|
| cancelled |2|published or suppressed|pending|200|

links fields: self:string1..256, cancel:string1..256, events:string1..128.
Exact unprefixed values: PATH+"/"+request_id, PATH+"/"+request_id+"/cancel", "/api/v1/events".
The wire projection prepends base_path.rstrip("/") to each value as the old adapter does.
Structural link patterns are anchored:
self = ^/(?:[0-9a-f]{32}/)?api/v1/deployment/provider-requests/[0-9a-f-]{36}$
cancel = same pattern with /cancel before $;
events = ^/(?:[0-9a-f]{32}/)?api/v1/events$.
Runtime checks bind the path UUID to the actual canonical request_id and base_path to OriginProfile;
pattern alone cannot grant either. UUID/H/B32 scalar schemas reuse existing exact constructors and
non-nil/canonical runtime validation. Both digest fields derive from retained parsed request bytes.

### B. provider-request-read-v1

Exact required fields/types:
request_id:UUID; request_digest:B32; kind constant extension_stage; state:prepared|cancelled|expired;
revision integer1|2; publication_state:pending|published|suppressed;
cancellation_publication_state:null|pending|published; source_context_sha256:H;
preserved_inventory_sha256:H; links:exact object above; request:complete exact38 provider-request-v2.
NO command_id or event_cursor. NO receipt/installation/credential/readiness placeholder.
Canonical response<=73728B; embedded request itself<=65536B.

| state | revision | publication_state | cancellation_publication_state |
| --- | --- | --- | --- |
| prepared |1|pending or published|null|
| cancelled |2|published or suppressed|pending or published|
| expired |2|published or suppressed|null|

GET200 returns canonical bytes; HEAD200 follows existing GET/HEAD header behavior with no wire body.
All summaries/digests/links must match embedded request and actual journal head/outbox, not cached
caller values. Historical reads never require current source availability.

### C. provider-prepare-api-v1

Exact oneOf:38 prepare input;38 cancel input; schema A; schema B; one closed error arm per following
code/message pair. Every error requires only {code,message,retryability:"not_retryable",
affected_refs:[],correlation_id:UUID}; no extra diagnostic/stack/path/value fields.

| code | HTTP | exact message |
| --- | --- | --- |
| invalid_input |400|Invalid deployment request.|
| unauthenticated |401|Authentication is required.|
| access_denied |403|This action is not allowed.|
| not_found |404|Deployment request, candidate or slot was not found.|
| conflict |409|Deployment request state conflicts with this command.|
| too_large |413|Deployment request is too large.|
| capacity |429|Deployment preparation capacity is exhausted.|
| dependency_unavailable |503|Deployment preparation is unavailable.|
| unavailable |503|Deployment state is unavailable.|

Frozen receipts store UNPREFIXED canonical links/input/receipt bytes. Exact replay returns original
command receipt/status even after publication, cancellation, expiry or source loss; API projects the
same OriginProfile base path, giving byte-identical wire replay. GET can show later state.

## 5. Exact literal v4 schema and checksums

DDL_V4 is precisely the following ordered17 strings: each starts at CREATE and ends at its semicolon,
excluding inter-statement blank lines, preserving every internal space/newline.16 are tables; one is
an explicit unique index. Relative to actual DDL_V3, only positions0(migrations) and5(commands) change;
append positions13..16. Old DDL/DDL_V2/DDL_V3 string lists remain byte-identical.

Checksum = SHA256(domain canonical_json(list(DDL_V4))). Text-only AST extraction of actual old
constants plus these literal replacement/addition statements was recomputed for this draft:

| Layout | Statements | Canonical bytes | SHA256 |
| --- | --- | --- | --- |
|v1|7|6930|68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec|
|v2|11|11362|d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f|
|v3|13|13535|ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457|
|v4|17|17696|f89a9a8ba7f98da44e4a48f63c0363d2bfa7fafe038bd19bfdc178396c4be7d2|

No SQL was executed. This checksum freezes proposed text, not accepted migration correctness.

```sql
CREATE TABLE deployment_prepare_migrations (
 version INTEGER PRIMARY KEY CHECK(version IN (1,2,3,4)),
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

CREATE TABLE deployment_prepare_heads (
 request_id TEXT PRIMARY KEY REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 3),
 lifecycle_hash TEXT NOT NULL CHECK(length(lifecycle_hash)=64), hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(request_id,revision,lifecycle_hash) REFERENCES deployment_prepare_lifecycle(request_id,revision,hash)
);

CREATE TABLE deployment_prepare_commands (
 command_id TEXT PRIMARY KEY CHECK(length(command_id)=36),
 namespace TEXT NOT NULL CHECK(namespace IN ('deployment-prepare-v1','deployment-cancel-v1','deployment-cancel-v2','deployment-receipt-import-v1','deployment-consume-v1','deployment-prepare-provider-v1','deployment-cancel-provider-v1')),
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
  OR (namespace='deployment-consume-v1' AND http_status=200 AND lifecycle_revision=3)
  OR (namespace='deployment-prepare-provider-v1' AND http_status=201 AND lifecycle_revision=1)
  OR (namespace='deployment-cancel-provider-v1' AND http_status=200 AND lifecycle_revision=2))
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
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision IN (2,3)),
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

CREATE UNIQUE INDEX deployment_prepare_requests_vault_request
 ON deployment_prepare_requests(vault_id,request_id);

CREATE TABLE deployment_prepare_provider_contexts (
 context_id TEXT PRIMARY KEY CHECK(length(context_id)=36),
 vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id),
 topology_id TEXT NOT NULL CHECK(length(topology_id)=36),
 epoch INTEGER NOT NULL CHECK(epoch=1),
 worker_profile TEXT NOT NULL CHECK(worker_profile='claude-text-transform-v1'),
 purpose TEXT NOT NULL CHECK(purpose='operational'),
 context_sha256 TEXT NOT NULL CHECK(length(context_sha256)=64),
 context_size INTEGER NOT NULL CHECK(context_size BETWEEN 1 AND 16384),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 UNIQUE(vault_id,context_id),
 UNIQUE(vault_id,context_sha256),
 UNIQUE(vault_id,worker_profile,epoch),
 FOREIGN KEY(vault_id,topology_id)
  REFERENCES deployment_prepare_control(vault_id,topology_id),
 FOREIGN KEY(vault_id,purpose,context_sha256)
  REFERENCES domain_blobs(vault_id,purpose,sha256)
);

CREATE TABLE deployment_prepare_provider_context_documents (
 context_id TEXT NOT NULL,
 vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id),
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 18),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 64),
 purpose TEXT NOT NULL CHECK(purpose='operational'),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 size INTEGER NOT NULL CHECK(size BETWEEN 1 AND 65536),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(context_id,ordinal),
 UNIQUE(context_id,name),
 FOREIGN KEY(vault_id,context_id)
  REFERENCES deployment_prepare_provider_contexts(vault_id,context_id),
 FOREIGN KEY(vault_id,purpose,sha256)
  REFERENCES domain_blobs(vault_id,purpose,sha256),
 CHECK((ordinal=1 AND name='original-prepare-recipe.json' AND size<=4096)
  OR (ordinal=2 AND name='original-prepare-instance.json' AND size<=4096)
  OR (ordinal=3 AND name='original-topology.json' AND size<=65536)
  OR (ordinal=4 AND name='original-outgoing-exchange.json' AND size<=8192)
  OR (ordinal=5 AND name='original-receipt-recipe.json' AND size<=4096)
  OR (ordinal=6 AND name='original-receipt-instance.json' AND size<=4096)
  OR (ordinal=7 AND name='original-trust-set.json' AND size<=16384)
  OR (ordinal=8 AND name='original-receipt-ingress.json' AND size<=8192)
  OR (ordinal=9 AND name='original-consumption-exchange.json' AND size<=8192)
  OR (ordinal=10 AND name='geometry.json' AND size<=65536)
  OR (ordinal=11 AND name='provider-recipe.json' AND size<=8192)
  OR (ordinal=12 AND name='provider-instance.json' AND size<=8192)
  OR (ordinal=13 AND name='provider-trust-set.json' AND size<=16384)
  OR (ordinal=14 AND name='outgoing-exchange.json' AND size<=8192)
  OR (ordinal=15 AND name='receipt-ingress.json' AND size<=8192)
  OR (ordinal=16 AND name='consumption-exchange.json' AND size<=8192)
  OR (ordinal=17 AND name='source-context.json' AND size<=16384)
  OR (ordinal=18 AND name='source-pins.json' AND size<=8192))
);

CREATE TABLE deployment_prepare_provider_requests (
 request_id TEXT PRIMARY KEY CHECK(length(request_id)=36),
 vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id),
 context_id TEXT NOT NULL CHECK(length(context_id)=36),
 purpose TEXT NOT NULL CHECK(purpose='operational'),
 inventory_sha256 TEXT NOT NULL CHECK(length(inventory_sha256)=64),
 inventory_size INTEGER NOT NULL CHECK(inventory_size BETWEEN 1 AND 16384),
 at_event_sequence INTEGER NOT NULL CHECK(at_event_sequence BETWEEN 0 AND 1099511627776),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(vault_id,request_id)
  REFERENCES deployment_prepare_requests(vault_id,request_id),
 FOREIGN KEY(vault_id,context_id)
  REFERENCES deployment_prepare_provider_contexts(vault_id,context_id),
 FOREIGN KEY(vault_id,purpose,inventory_sha256)
  REFERENCES domain_blobs(vault_id,purpose,sha256)
);
```

## 6. Scalar, hash, shape and retained-graph invariants

Exact16-table shape includes migrations plus15 private data tables. TABLES_V4 extends existing
TABLES_V3 only with provider_contexts,provider_context_documents,provider_requests in that order.
Migration rows exactly(1,C1),(2,C2),(3,C3),(4,C4). CAPS_V4 preserves all existing v3 caps:
control1,requests16,lifecycle48,heads16,commands48,outbox32,receipt_sources1,receipts16,
consumptions16,consumed_outbox16,installations16,installation_heads16; add1/18/16 respectively.
No new nullable columns. Existing nullable sets unchanged. Preflight SQL scalar types and byte
lengths/caps before full-row materialization; UUID/H/B32 grammars, bool exclusion and canonical
JSON are verified in Python as well as SQL CHECKs. New context_id is UUID; context/inventory/sha256
fields H; ordinal/name/size must equal the fixed18-row SQL table, not an arbitrary basename.

Row hash preimage remains {namespace,table,row:all columns except hash}, domain canonical_json.
Namespace remains deployment-prepare-storage-v1 for original TABLES, storage-v2 for old v2 additions,
storage-v3 for old v3 additions, and deployment-prepare-storage-v4 ONLY for the three new additions.
Old commands with new provider namespace text are still hashed under storage-v1. Never rehash old rows.
Extend _layout/_expected/_private_sizes/_row/insert verification with this exact v4 layout; keep old
validate_row v1 semantics and old layout decoding. No updates permitted for new immutable index rows.
Existing advance permits only its existing control/head/outbox/consumed-outbox mutations.

Vault and slot invariants exceed SQL length checks. Every new row uses actual roots.genesis.id;
context/doc/request/CAS composite FKs must agree with that root, including inventory. The explicit
requests(vault_id,request_id) unique index is a vault-qualified FK target, NOT a second reservation
registry. Existing request UNIQUE(vault_id,topology_id,slot_id) and UNIQUE(vault_id,extension_id) cover
all old/new terminal states forever. Original topology ID, profile, capacity and slot(instance,number)
geometry remain exact. No aliases through a new context/topology ID; cancellation/expiry never recycles.

Exactly one provider relation iff request anchor's content discriminator is
deployment-provider-request-anchor-v2; none for deployment-request-anchor-v1. Exactly one context
iff at least one provider request, exactly18 document rows, no orphan context/doc/relation. All
provider requests use that exact context/worker_profile/epoch and original control topology.

Provider domain envelope stays deployment_request/version1,id=request_id,parent_refs=[candidate_ref],
operational purpose and actual actor/access/retention roots. Content exact38 fields:
{schema_version,request_id,request_blob_ref,source_documents,preserved_inventory_blob_ref,
candidate_ref,topology_id,topology_revision:1,slot_id,reservation_revision:1,prepare_command_id}.
source_documents is exactly18 ordered {name,blob_ref}, using names/caps in SQL above.
All BlobRefs operational/same actual vault; candidate EntityRef has NO vault_id field.

Before _load, bound body<=8192 and actual edge/blob associations. Old anchors keep their original
edges4/blobs3 bound. For provider anchors, edges4 and at most20 distinct blob associations, precisely
actual request+inventory+18 source refs with exact deduplication through existing domain semantics.
Do not globally widen old limits. Enforce domain-record/private-row bijections, all actual CAS
size/digest/bytes, actor account/record, parent, policy and ownership graph through DomainStore._load,
_check_graph and bounded blob APIs. SQL references and nested hashes alone are not provenance.

load_context obtains the18 ordered bytes from actual indexed CAS, validates the complete35 bundle
and old/provider graph, compares context row to ACTUAL source-context.json (ordinal17), and closes
original profile/topology/exchange/control/recipe/instance/trust/channel joins. No source handle is
required to read historical CAS. All source refs in each anchor equal these indexed BlobRefs.

Schema bytes are fixed code-owned projections: _provider_schema_bytes uses existing
generate_port_schemas()/canonical_schema_bytes() for (provider-port-v1,config/request/result/error)
in that order. New tests prove exact byte equality with unchanged checked-in v1 leaves. Do not accept
caller bytes/path/URL or pretend these are measured live-worker schemas. Future incompatible schema
generation must retain the old v1 projection for historical verification, not silently reinterpret it.

Load candidate through actual registry/CAS and reconstruct every provider request using full38
validate_provider_request_sources with actual candidate, bundle, schema bytes and inventory. This
closes lineage, full selected descriptor/UID/GID/broker/argv/network/resources/isolation and original
slot joins that39's filesystem publisher cannot establish. Reconstructed request must equal exact
retained bytes/digest/nonce/time/actor/slot/extension/private row, not merely an outer hash.

## 7. Migration: actual writer, complete history, no disconnected delivery

Use existing PersistentDeploymentPrepare constructor→_writer()/DomainStore._connection(write=True)
→records.install. Verify actual owner/domain/registry and whole legacy layout/history before each
step. Keep accepted v1→v2→v3 chain unchanged, then _rebuild_v3_as_v4; verify final v4 and FK check in
the same writer. Already-v4 verifies only. Old binaries reject the new exact shape.

No source requirement, RNG/clock/event/request/context/domain write or publication during migration.
No offline arbitrary DB-path tool. Wholly absent schema retains existing orphan anchor/event guard
and install chain. Adding empty v4 tables at a real application startup is permitted only as part
of this COMPLETE implemented vertical delivery; no table-only task/release.

Before mutation, snapshot bounded old typed rows, keys, original canonical TEXT/BLOB bytes/hashes and
observable rowids; capture relevant domain/CAS/event/counter/replay baseline in tests. Check exact
owned shape and inbound foreign-key metadata to the two rebuilt tables. Allowed inbound edges to
commands are ONLY:
lifecycle.command_id→commands.command_id,
receipts.import_command_id→commands.command_id,
consumptions.command_id→commands.command_id,
installations.command_id→commands.command_id;
their exact actions/definitions must match the unchanged v3 shape. No inbound edge to migrations.
Reject undeclared inbound references/actions before deleting anything. Inspect sqlite_schema and
foreign_key_list metadata of actual tables; existing shape() alone is insufficient. Do not modify
unrelated schema objects or introduce a generic database-repair subsystem.

Require FK ON and set defer_foreign_keys ON inside the transaction. Delete commands in descending
lifecycle_revision and migrations, drop ONLY those two, create their changed literals and the
new index/three tables, restore all old columns AND explicit rowids, append migration4. Populated
children stay in place. Compare old snapshots exactly, whole semantic verification and FK check
before commit. No FK OFF/cascade/rename/executescript/writable_schema/pruning.

Every injected failure after delete/drop/create/restore/check rolls back to exact old logical
schema/typed rows/rowids/bytes. No claim about physical SQLite page/WAL identity. Rowid preservation
is explicit for THIS v3→v4 step: old accepted v1→v2→v3 rebuilds did not explicitly snapshot rowids.
For v1/v2 starts preserve their accepted chain behavior/typed record/replay bytes, then preserve
immediate-v3 rowids; do not broaden scope to rewrite old migrations or claim a retroactive guarantee.

Real migration fixtures use accepted owner/candidate/service commands in isolated databases, covering
valid prepared/published/cancelled/expired/rejected/accepted histories and pending/suppressed marker
states. Use separate histories when first-only admission forbids coexistence; no fabricated positive
installation to shortcut verification. Reopen source-less and prove old HTTP replay and old terminal
slot conflicts unchanged. Negative corruption fixtures are not claims of genuine provenance.

Historical fixture construction clarification: in an isolated temporary store only, first use the
actual current constructor and assert normal v4 startup. With all deployment PRIVATE DATA tables
empty (migration rows are the exact known C1–C4 set) and no deployment anchors/events, a test-only
writer may replace those empty owned tables/index with exact retained DDL_V3 and C1–C3, keeping FK
ON. The already-bound actual service then creates legacy histories through genuine old commands;
actual current constructor reopen is the migration subject. This is explicit historical-layout
fixture setup, not a production downgrade or execution of an old binary. No production monkeypatch,
ignored-beforecopy module import or fake successful owner/source/journal/publisher is permitted.
Snapshot real records/events/CAS/rows only after genuine history construction; preserve them through
the migration under test. Existing explicit v1/v2 fixture/chain evidence boundaries remain unchanged.

## 8. Inventory, lifecycle and historical command verification

New prepare admits0..1 legacy staged installation, no qualification/binding records, all other
requests terminal (cancelled/expired/rejected/accepted). Never-used target extension AND slot across
ALL request rows, not just inventory. The original first-only tool business rules remain unchanged;
this is not general multi-install/head lifecycle or replacement support.

Freeze inventory using actual verified journal/installation/head and accepted/staged events at
at_event_sequence = validated api_event_streams.next_sequence -1 before prepared event, int0..2**40.
Inventory exact38 fields:
{schema_version:"deployment-provider-preserved-inventory-v1",vault_id,instance_id,
origin_profile_digest:H,topology_id,topology_sha256:H,at_event_sequence,installations}.
Entry exact:
{installation_ref,extension_id,request_ref,head_revision:1,head_digest:H,slot_id,service_identity,
accepted_event_id,staged_event_id}. Canonical order extension_id then installation_ref.id.
Head digest equals actual stored storage-v3 installation_heads.hash with exact preimage:
{namespace:"deployment-prepare-storage-v3",table:"installation_heads",
 row:{extension_id,request_id:request_ref.id,revision:1,
      installation_anchor_digest:installation_ref.sha256}}.
Never substitute installation anchor SHA. All EntityRefs are same actual vault via DomainStore,
not by changing their closed shape.

Whole verifier loads legacy requests/installations/heads/events first with unchanged old checks.
Then verify_inventories reconstructs each frozen inventory at its boundary: include exactly the
validated legacy installations whose staged event sequence<=boundary, accepted event earlier, actual
causation/request/head/service tuple. Require boundary<new prepared event sequence and actual stream
bounds, no missing/future/swapped events. Stored inventory bytes and row hash/size/sequence must agree.
Reject unsupported provider installation/head/receipt/consumption rows; no fake historical heads.
No new provider-specific restrictions apply to an old-only journal with no provider relations.

Later unrelated global events or legitimate later old history do not rewrite frozen inventory.
Historical reconstruction must not require TODAY's inventory equal the request's snapshot.
Fresh prepare/publication separately compares current managed inventory contents; only global
at_event_sequence may differ. Unsupported qualified/bound managed state prevents new admission/
publication; this task does not add a decoder for future qualification/binding lifecycles.

Provider lifecycle only prepared1→cancelled2/expired2. Request row always retained. Prepared creates
request pending intent; terminal transition suppresses only a still-pending request, leaves published
request acknowledgment intact; cancelled creates pending8192-max cancellation, expired creates none.
No provider receipt/consumption/consumed marker/installation/head can join its ID.

Reuse existing lifecycle._append_transition/outbox/_store_command/event_fields/input_digest, with
exact provider cancellation dispatch; do not reimplement general public events. Provider transition
uses only deployment-prepare-provider-v1(201,rev1) and deployment-cancel-provider-v1(200,rev2).
Old lifecycle.verify delegates only on exact retained provider discriminator; old body unchanged.
Provider verifier reconstructs row chain/head/hash, monotonic clock, actor, actual event/cursor,
outbox payload/state/hash and complete command set. Prepared/cancelled actor must be the original
request's actual owner actor; expired uses roots.actor/system. Cancellation time is
created<=cancel<expires; expiry time>=expires. Existing event names/status/private evidence and
object_ref shapes remain the same request lifecycle vocabulary; no staged/qualified event emitted.

Each command input is exact parsed38 input (cancel normalized with bound path request_id);
input_digest = SHA256(canonical_json({namespace,instance_id,origin_digest,actor_ref,input})).
Global command ID uniqueness crosses old/new namespaces. Verify status/lifecycle/request/actor/input,
original frozen receipt shape/links/digests/cursor and actual event-sequence relation. Permit existing
cursor-generation advancement exactly as old verifier does, without rewriting saved cursor bytes.
No command for system expiry. Frozen prepare receipt always pending; frozen cancel receipt records
published|suppressed request and pending cancel, even after later cancel publication.

## 9. Real prepare/cancel/read and source ownership

Authenticate using existing exact AuthenticatedRequest and bound owner authority. POST requires
correct host/origin, actual same-origin CSRF; read accepts existing GET/HEAD rules. Resolve actor
from actual owner account/domain graph. Same-command replay follows full journal verification and
namespace/actor/exact-input/digest match, then returns BEFORE new RNG/source/inventory/time checks.
Conflicting namespace/actor/input is conflict. Read authenticates/reconstructs journal without source.

For a genuinely new prepare:

1. Parse38 input, authenticate, full journal/registry/replay gate under actual writer; _now/floor
   using existing owner clock/highest/control floor. No invented source timestamp. Check overflow
   with expires_in_seconds and existing MAX_MS253402300799999.
2. Load actual candidate/managed state; refuse reused extension(conflict), reused slot(capacity),
   nonexistent slot(not_found), unsupported managed/nonterminal state(conflict). Read actual37
   ordered18 bytes and compare expected source_context_sha256 to actual pinned bytes. Missing/stale/
   wrong-profile context or failed structural candidate/source compatibility is dependency_unavailable.
3. Acquire original TopologySource slot metadata lease through accepted40 _acquire; current original
   ExchangeSource supplies original exchange bytes/identity. Exact original topology/profile/instance/
   capacity/slot and current control agree. Provider context cannot manufacture an OutboxIdentity.
4. Freeze actual inventory/event boundary and actor; generate UUID4+32-byte nonce in core. Call38
   make_provider_request using actual candidate/source/schema/inventory; request bytes are canonical.
   Preseal request,inventory,18 source blobs through actual DomainStore.put_blob(operational).
5. Final actual writer: reauthenticate, full journal/registry, replay race before new writes, fresh
   _now<deadline, exact candidate/source/original exchange/slot lease/currentness, permanent unused
   reservation and managed inventory checks. Reconstruct inventory at frozen boundary AND compare
   current managed inventory excluding only at_event_sequence; unrelated global events may advance.
   Full38 byte reconstruction again; no browser dictionary can assert these checks passed.
6. Atomically create domain anchor with actual parent/actor/policies, original control IF absent
   (original topology/exchange CAS and actual old exchange identity, never provider exchange),
   first context+18 doc rows, old requests reservation row, provider relation, lifecycle/head/outbox/
   event/frozen command and clock floor. Existing context must match every byte/ref/field. Reverify
   complete journal before transaction commit. No separate context registration write.
7. Close slot lease preserving primary; best-effort actual reconcile; return frozen201 receipt.
   Presealed orphan CAS after a lost race is not admission; no anchor/context/request/event/command
   partial success survives a transaction failure.

Cancel: parse path-bound38 selectors, authenticate/replay, require provider ID/digest/rev1 and actual
original actor, sample clock/floor. Before expiry commit cancelled2+exact38 cancellation intent+
frozen200 receipt atomically; no current source/slot/inventory needed to RECORD cancellation.
At/after expiry commit expired2/suppression, exit writer, then raise conflict without a losing cancel
command. Raising inside transaction would wrongly roll back expiry. Expiry emits no marker.
Source absence may leave cancellation pending; it must not prevent historical read/replay.

Wrong-family IDs return not_found after authentication: old read/cancel/receipts/consume never admit
provider anchors, new read/cancel never select old anchors. All previously valid old calls retain
their input/result bytes and business rules. New source failure is dependency_unavailable, not a
reason to mark an otherwise valid old journal globally unavailable. Actual journal corruption remains
unavailable; raw private diagnostics never escape. Preserve process-control exceptions.

Startup uses37's SAME local context already registered immediately with _own_source/ExitStack;
pass it to the actual service, keep both accepted exports/resource order and include provider router.
No second opener, late env lookup, browser context object, catalog/key addition or context refresh.
Application resource owner closes sources; new service never closes borrowed context. Missing pin/
context permits old service, migration and historical provider read/replay/cancel/expiry.

## 10. Publication and reconciliation crash/time contract

Use39 real fixed-root publisher unchanged, not a fake ExchangeSource or second file writer.
Under service RLock and actual DomainStore writer per intent: owner check, full journal, time/floor,
winning state/outbox, retained context equality. Build expected_payloads from ALL provider request
bytes including suppressed ones plus committed cancellations; request rank0/cancel rank1, decoded
digest hex order, <=16+16, per65536/8192 and aggregate<=1,179,648. No caller auth flags.
39 validates all outgoing final metadata/bytes; service additionally requires each journal-published
final exists. Incoming/consumed payloads and metadata-safe interrupted stages stay opaque/unmodified.

Request publication requires prepared1, current original slot lease, exact candidate/source graph,
current managed inventory equal frozen content and no other nonterminal request. Cancellation
requires cancelled2 but no execution-condition slot/inventory gate. Its already-committed timestamp
was pre-expiry; cancellation may publish after that deadline.

Observe exact target BEFORE stage. Existing matching final can be acknowledged without another
rename, including after expiry, because it records past exposure. Missing request target with
now>=expiry suppresses/ expires without stage. Otherwise recheck source/slot/inventory, clock and
cooperative budget, stage once, then repeat currentness and fresh authoritative now<expiry at last
pre-commit checkpoint. On expiry close attempt (honest stage may remain), expire/suppress; NO rename.
Task39 stage requires absence; a target race refuses or is handled by its one-shot NOREPLACE commit,
never an automatic retry loop.

After commit NOREPLACE/fsync/exact postread/currentness, sample acknowledgment _now and advance
pending→published once; if request expired during commit, acknowledge observed publication then
append expired2 in the SAME writer. published_ms is durable observation/ack time, not invented rename
time: require lifecycle transition<=ack<=floor and, once terminal, ack<=terminal transition.
Do not require ack<deadline, which would reject an honest crash/slow-fsync observation.
Reverify whole journal and commit. Cancel/expire races serialize through actual writer/owner checks.

Filesystem publication and SQLite are NOT one atomic transaction. File visible/fsynced then DB
rollback/crash leaves pending+exact final; retry observes/fsyncs existing bytes, never creates another
request/event/effect. Source postcheck failure after visibility leaves honest disk state and pending
DB intent. If source unavailable at expiry, commit expired/suppressed without claiming absence of
a prior final. Suppressed means no remaining intent, NOT proof of non-exposure. Never repend a
suppressed terminal row, delete final, fabricate cancellation for expiry or claim kernel-atomic
deadline enforcement. Future operator must independently enforce deadline/current inventory/authority;
no such operator is implemented here.

Every new provider operation explicitly closes its owned attempt/publisher/slot resources with
primary-preserving exhaustive cleanup. commit already closes/relinquishes genuine attempt on all
exits; repeated close is inert, foreign attempts are not closed. Borrowed context stays with startup
owner (its own process-control guard may self-close). Exact post-effect source/capacity refusals
remain bounded, not loops or rollback/unlink. Map provider source/publication/ordinary FS failures
inside new orchestration before old broad _reconcile error handler; keep intent pending or expired/
suppressed and permit subsequent old items. Journal/SQLite corruption still poisons service normally.

Keep old _reconcile_item branch unchanged for old discriminator. At most16 intents and existing
cooperative1-second monotonic budget per _reconcile invocation; no hard syscall deadline or cross-run
fairness promise. Preserve old-only ordering; mixed order: provider cancellations, old cancellation/
consumed work, requests, request_id ordering within each class. One refused item consumes one attempt;
continue while budget remains, no retry. Startup and successful new command reconcile; GET/exact
replay do not. No background scheduler, public retry route, or rebind of stale context.

Account owned FD additions: provider publisher3 dirs+at most1 stage+1 read, original slot lease5
retained FDs, accepted context and bounded acquisition/currentness transients. Test the combined
context+publisher+slot resource set stays<=256 including transient peaks, with preexisting other
startup resources reported separately as caller baseline. No process-wide FD scan/global manager.
Primary preservation is at deterministic acquisition/next-call/transfer/cleanup checkpoints, not an
impossible SIGKILL/arbitrary-VM-interval guarantee.

## 11. Actual HTTP boundary

Append these EXACT three browser_session route declarations under existing contribution/factory:

| route_id | methods | path | required_scope |
| --- | --- | --- | --- |
| deployment.provider-requests.prepare |POST|/api/v1/deployment/provider-requests|deployment.manage|
| deployment.provider-requests.cancel |POST|/api/v1/deployment/provider-requests/{request_id}/cancel|deployment.manage|
| deployment.provider-requests.read |GET,HEAD|/api/v1/deployment/provider-requests/{request_id}|deployment.read|

No receipt/consume/list/status/retry endpoint for providers. Preserve five legacy declarations.
web_boundary classifies provider path separately, parses empty query only, POST application/json
and4096-byte wire limits; GET/HEAD zero bytes/content-length. Same raw-path normalization/OriginProfile
base path, host/origin/CSRF/session/scope enforcement and existing error envelope. Set only
provider_deployment_payload after successful new preflight; old deployment_payload path untouched.
Router uses run_in_threadpool on actual methods and canonical response bytes/base-path projection.
HEAD has no body. Unsupported method/suffix/malformed UUID follow fixed deployment error behavior.
No provider method is declared reachable until this real composition path and source ownership pass.

## 12. Concrete TDD, preservation and review acceptance

Write NEW independent characterization tests before old-file edits. Only the seven listed existing
tests may adapt the precise current-startup/version, route-count, one same-context constructor
argument expectation or the single import-test process isolation above. The constructor check retains full kwargs equality over exactly six values,
not a subset/any-value check or a disabled startup test. Preserve
legacy v1/v2/v3 mechanical migration, literal checksums, rollback, rows/records/events/CAS/replay,
owner/lifecycle and business assertions; no skipping, lazy migration or production monkeypatch.
The new records suite must exercise real DomainStore put/load/check_graph and deduplicated blob
associations for source_documents wrappers, including wrong vault and malformed nested references.
The generic domain/store.py walker stays byte-unchanged.
The import test must prove an actual fresh-process import with source/mount/native acquisition
forbidden, not merely run an empty child. Keep an actual ordered regression: warm the real publisher,
execute that import test, then exercise both unchanged publisher families; parent class identity and
the exact-type refusal semantics must remain intact. This repairs test-process contamination only.
Synthetic hashes/UID/mount/native observations must be labeled. Do not mock successful source guards,
owner authentication, actual journal integrity or publisher result to manufacture a happy path.
Use accepted37 controlled trees and39 real FD/name/bytes/fsync/no-replace paths in isolated test state.

| NEW test file | Required proof |
| --- | --- |
| test_provider_prepare_migration.py | Real old histories; all v1/v2/v3 starts; immediate-v3 typed rows/rowids/hash/text/blob/event/counter/replay preservation; exact17-statement shape/C1–C4; missing/forged index/migration; inbound commands FKs including receipts/consumptions/installations; unknown inbound edge refuses; injected failure at every destructive/restore/verification step rolls back; source-less constructor has no clock/event/domain write. |
| test_provider_prepare_records.py | Wrong-vault composite FKs plus real DomainStore graph mismatch; half/orphan18-doc graph and alias topology; CAS bytes/size/hash with refreshed index hashes; provider relation iff discriminator; old3-blob cap unchanged; context17 exact; actual frozen inventory/event boundary, independent head-hash vector, extension+slot exclusion, future/swapped events; provider receipt/consumption/install rows denied. |
| test_provider_prepare_service.py | Actual bound owner/candidate; zero/one legacy staged installation; every terminal reservation counted; no reuse/context rotation; auth/CSRF/actor/namespace conflicts; exact replay before source/clock/RNG; two real services competing; candidate/source/slot/inventory drift before final writer; atomic rows/event/receipt; cancel before/at expiry committed correctly; source-less read/replay/cancel. |
| test_provider_prepare_reconciliation.py | Verified journal intents→actual39 bytes; all published finals observed; missing/unknown/wrong final; exact-existing restart; stage/rename/fsync then DB failure; clock before stage/before rename/during ack; source failure after exposure; unavailable-at-expiry suppression not proof of absence; no cancelled re-publication; cancellation after deadline; incoming remains opaque; old item still processed after provider refusal within budget; combined FD/cleanup bounds. |
| test_provider_prepare_api.py | Actual server/catalog/contribution/web-boundary/session/candidate/service;8 route declarations; POST201 real CAS/rows/event/final file→GET200; cancel200; HEAD empty; frozen byte replay after source loss/state change; base-path modes; all input/media/query/body/scope/origin failures; wrong-family not_found and no provider receipts route; SAME startup-owned context passed/closed once and no second opener. |
| test_provider_prepare_api_schema_exports.py | Exact3 fresh exports/URNs/bytes; no extra/missing fields and invalid state combinations; links bound to actual ID/base path; receipt8192/read73728; exact error messages; generated4 provider-v1 schema bytes equal checked-in leaves; old/38 exports unchanged. |

Every phase has meaningful RED then minimal implementation then focused GREEN; missing prerequisite
module is a dependency failure, not a protocol RED. No isolated migration/route scaffold acceptance:
final acceptance includes real POST→CAS/journal→actual publisher→GET→replay/cancel/restart.

Focused future runner (one frozen run, not executed for this draft):
<workspace>/.venv/bin/python -B -m pytest with -q -p no:cacheprovider,
all six new test modules above. Narrow existing coverage:19 byte-unchanged plus the seven narrowly
adapted tests enumerated in section2, exact26 paths:

    app/tests/test_deployment_prepare.py
    app/tests/test_deployment_prepare_integrity.py
    app/tests/test_deployment_prepare_storage.py
    app/tests/test_deployment_prepare_publication.py
    app/tests/test_deployment_prepare_api.py
    app/tests/test_deployment_prepare_contracts.py
    app/tests/test_deployment_prepare_v2_contracts.py
    app/tests/test_deployment_prepare_v3_contracts.py
    app/tests/test_deployment_prepare_v2_schema_exports.py
    app/tests/test_deployment_receipt_migration.py
    app/tests/test_deployment_journal_v3_migration.py
    app/tests/test_deployment_receipt_journal_integrity.py
    app/tests/test_deployment_receipt_journal_reconciliation.py
    app/tests/test_deployment_receipt_import.py
    app/tests/test_deployment_receipt_api.py
    app/tests/test_deployment_consume.py
    app/tests/test_deployment_consume_api.py
    app/tests/test_deployment_acceptance.py
    app/tests/test_first_party.py
    app/tests/test_first_party_dependencies.py
    app/tests/test_provider_sources.py
    app/tests/test_provider_source_startup.py
    app/tests/test_provider_prepare_contracts.py
    app/tests/test_provider_publication.py
    app/tests/test_provider_publication_lifecycle.py
    app/tests/test_provider_slot_lifecycle.py

Verification refinement after the initial frozen run: that exact32-family run produced
63 failed/1040 passed; the failures were reproduced as three stale current-version assertions
and60 consequences of parent-module reload. If the only post-run changes are the three newly
authorized existing test functions above, preserve that complete initial result and require one
fresh ordered cover of the affected integrity and receipt-API families, a genuine publisher warmup,
the entire provider_sources family, then both unchanged provider_publication families. All initial
27 owned files and every other baseline byte must still match the initial freeze. Do not repeat the
unaffected passing families merely to replace the historical failure report. State these as two
distinct evidence runs, never as one fresh all-green32-family run. Any production/new-test/schema
change instead requires a fresh covering selection for its actual impact before acceptance.

Review internally in order: old characterization→literal storage/migration/history→owner commands/
lifecycle→actual publisher/crash/time→actual HTTP/source ownership. Ship/accept ONE complete task.
Freeze all30 owned path hashes/full diff; prove old literals/schema bytes, unlisted test bytes and
all assertions outside the seven precise test adaptations preserved; report RED/GREEN/failures and actual FD measurements. Independent spec/quality preflight
and final whole-slice review are required. No native provisioning/live model evidence claim.

This contract supplies concrete SQL/fields/APIs; independent preflight and prerequisite acceptance
still gate implementation. Full report belongs to .superpowers/sdd/resumption-plan/task-41-report.md;
no subagents or unlisted source/test edits. Preserve dirty work and all accepted lower-level contracts.
No unbuilt image or real credential is an external blocker to isolated code/test implementation.
Actual publication on a user instance requires genuinely configured sources and authenticated owner
command, not promotion of synthetic fixture evidence.
