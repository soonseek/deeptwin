# Provider receipt / staged-installation consumption — Task43 implementation contract

ACTIVE IMPLEMENTATION CONTRACT, 2026-09-20. Full independent preflight READY; not implemented or accepted.
Post-freeze1 scope amendment§13 adds one test-only path (50 total); original49-path text below
records the reviewed initial scope. Wire/SQL/production ownership and authority remain unchanged.
Authority: ../spec.md FR-032, ADR-014, runtime.md, accepted original deployment receipt/source/
journal-v3 contracts and accepted provider source/context/protocol/publication/slot integration.
Tasks39–41 are accepted dependencies; Task41 accepted after scoped R1 with immutable719 snapshot
.superpowers/sdd/resumption-plan/task-41-r1-frozen.sha256, manifest SHA256
de8e69aefcd1f29792643c81ccbf3d959806104e4ddcaa4e9d96716f3370c509.
Task42 is accepted after independent review and fixture-only R1. Controller read its actual final
production diff, test correction and evidence against provider-stage-connection-lifetime.md.
Accepted720 snapshot is task-42-r1-frozen.sha256, copied to task-43-before.sha256; SHA256
6b3fa4a70cb6e8946c7540b6b4f347a68dc71d6b4aef7d7928c866786b5bd61d.
Full Task43 preflight is READY; controller authorized fresh sole-writer dispatch. No new human
technical-choice confirmation, native execution or release authority is implied.

This candidate preserves the R2 draft's49 paths, all wire fields, SQL/C5 and authority boundaries.
The source draft and beforecopies remain immutable advisory history. Accepted41 R1 changed only
one production finalizer and five fixture/test files, not DDL/API semantics; exact carry-through
and evidence limits appear in§12. No SQL/app imports/tests/native/network/key/user-data actions
were performed to prepare this candidate. Its companion task-43-brief.md is the implementation brief.

## 1. One complete delivery and limits

Implement actual provider receipt selector import, independent two-connection identity observation,
one-writer staged installation/head/consumption/events, historical rehydration, pending cancel/expiry,
physical non-success consumed projection and reachable authenticated HTTP. A pure parser, isolated
migration, mocked successful observer/service or disconnected route is not completion.

Exactly one original topology and provider context epoch1; at most one accepted provider alongside
zero or one legacy staged tool installation. Fresh provider preparation/publication is denied after
a provider installation exists. Previous cancelled/expired/rejected provider attempts remain history
and permanently reserve their distinct extension/slot; there is no retry/recycling. No parallel
installation/head registry, new topology/source context, rotation, replacement or uninstall.
The target head is absent and next installation revision1. Every frozen inventory reconstructs
legacy staged heads at its original event boundary, not today's inventory after provider acceptance.

No operator/signing implementation, new image/build packaging, qualification/binding/model choice,
credential/billing/approval/send authority or native execution. External producer native-API mapping
and immutable artifact intake remain unbuilt code interfaces, not permission blockers to isolated
consumer code. Synthetic crypto/IPC/source fixtures prove code behavior, never real provisioning,
packaging or all-five-check qualification. Task30 stays stored_unbound, Task32 generation denied;
Claude API-only and Codex subscription plus optional API scope unchanged.

## 2. Exact ownership:49 paths

29 NEW paths:

| Path | Responsibility |
| --- | --- |
| app/deployment/provider_receipt_contracts.py | Pure receipt verification/selected byte joins; import/consume/pending-cancel inputs and projection codecs. |
| app/deployment/provider_receipt_schema_exports.py | Exact twelve detached new exports listed below; no old schema edits. |
| app/deployment/provider_receipt_sources.py | Fixed incoming/consumed retained-channel lease, selected receipt lease and consumed publication. |
| app/deployment/provider_stage_observer.py | Actual two-connection identify observer and inert compact-evidence parser. |
| app/deployment/provider_receipt_records.py | Actual context/source/receipt/consumption/install graph joins, provider expected identity and atomic acceptance. |
| app/deployment/provider_receipt_lifecycle.py | New frozen responses/read-v2, pending transitions/history/events/commands; no general event framework. |
| app/deployment/provider_receipt_service.py | Existing service's delegated import/consume and consumed reconciliation orchestration. |
| app/tests/provider_receipt_fixture.py | Real isolated owner/DomainStore/candidate/source/IPC fixtures; synthetic signing material labeled. |
| app/tests/test_provider_receipt_contracts.py | Wire/crypto/source join and wrong-family negative matrices. |
| app/tests/test_provider_receipt_schema_exports.py | Twelve exact exports, closed-field/bound/response parity. |
| app/tests/test_provider_receipt_sources.py | Actual retained files/leases/selected bytes/identity/races/cleanup. |
| app/tests/test_provider_stage_observer.py | Actual authenticated two-connection worker path, evidence/time/freshness/negative matrices. |
| app/tests/test_provider_receipt_migration.py | Immediate-v4 real-history migration, preservation, inbound FK/rollback faults. |
| app/tests/test_provider_receipt_records.py | Same-vault graph/index/association caps and complete historical reconstruction. |
| app/tests/test_provider_receipt_service.py | Actual owner commands, races, expiry, no-source replay/read/cancel, atomic acceptance. |
| app/tests/test_provider_receipt_reconciliation.py | Real publisher/consumed projection, crash/ack/source/time and recovery. |
| app/tests/test_provider_receipt_api.py | Actual composition/router/web boundary and canonical HTTP bytes. |
| schemas/v2/deployment/provider-receipt-v1.schema.json | Signed receipt/result. |
| schemas/v2/deployment/provider-stage-postcondition-v1.schema.json | Compact core observation. |
| schemas/v2/deployment/provider-receipt-import-input-v1.schema.json | Prepared receipt selector. |
| schemas/v2/deployment/provider-consume-input-v1.schema.json | Pending consume selector. |
| schemas/v2/deployment/provider-cancel-input-v2.schema.json | Pending cancellation selector. |
| schemas/v2/deployment/provider-cancellation-v2.schema.json | Pending cancellation publication. |
| schemas/v2/deployment/provider-consumption-v1.schema.json | Failed/unknown physical marker. |
| schemas/v2/deployment/provider-receipt-anchor-v1.schema.json | Immutable provider receipt content. |
| schemas/v2/deployment/provider-installation-anchor-v1.schema.json | Immutable provider staged installation content. |
| schemas/v2/deployment/provider-command-receipt-v2.schema.json | New command replies only. |
| schemas/v2/deployment/provider-request-read-v2.schema.json | Receipt-bearing current read. |
| schemas/v2/deployment/provider-receipt-api-v1.schema.json | Exact old/new input/response/error union. |

20 MODIFIED paths:

| Path | Only permitted scope |
| --- | --- |
| app/deployment/provider_sources.py | Private combined receipt/consumed channel identity+snapshot accessor; public context remains read-only. |
| app/deployment/provider_publication.py | Add expected_receipts and pending-cancel-v2 codec/joins, preserve old default path and acquisition behavior. |
| app/deployment/prepare_storage.py | Exact v5 layout/scalar/hash dispatch and writer-bound v4→v5 rebuild only. |
| app/deployment/prepare_records.py | v5 migration chain and exact provider receipt/install family dispatch; old loaders/caps unchanged. |
| app/deployment/prepare_service.py | Two delegated methods/replay namespaces/provider consumed reconcile; startup borrowed ownership unchanged. |
| app/deployment/provider_prepare_records.py | Historical inventory projection by actual staged-event boundary after both installation families load; retained source/context/graph joins unchanged. |
| app/deployment/provider_prepare_lifecycle.py | Dispatch receipt-bearing history/read/pending cancel to new helper; original prepare/rev1-cancel branches unchanged. |
| app/deployment/provider_prepare_service.py | New pending-cancel selector/read dispatch; pending request suppression; v2 cancellation expected receipt tuple; explicit family-aware fresh prepare/publication denial after provider installation. |
| app/domain/deployment_receipt.py | New provider receipt body discriminator only; old receipt/consumption exports/validators unchanged in meaning. |
| app/domain/extension_installation.py | New provider installation body discriminator only; old tool branch/export unchanged. |
| app/api/provider_deployment_prepare.py | Two real routes, pending-cancel selector, new response projection. |
| app/api/route_contributions/deployment-prepare-v1.json | Append exactly two routes, preserve eight existing declarations. |
| app/tests/test_deployment_receipt_migration.py | Current startup C1–C5/SHAPE_V5 expectations and directly dependent fixtures/comments only. |
| app/tests/test_deployment_journal_v3_migration.py | Current-startup C1–C5/SHAPE_V5/_V5 expectations; receipts-only historical column projection plus separate new-NULL/source1 assertions in snapshot; exact scopes in§11. |
| app/tests/test_provider_prepare_migration.py | Current startup C1–C5/SHAPE_V5/_V5 expectations; receipts-only historical column projection/new-NULL assertions; exact empty historical-v4 fixture for named v4 corruption test; preserve v3→v4 checkpoints/baselines (§11). |
| app/tests/test_provider_prepare_api.py | Preserve malformed {}→400 at provider /receipts; clarify its malformed-selector meaning and add a genuinely unknown suffix case. Only the two named R1 endpoint selectors may change to unique exact path/method matches (§11.1). No business/replay/schema weakening; genuine new route checks live in new consumer API tests. |
| app/tests/test_first_party.py | Route count32→34 and directly related comments only. |
| app/tests/test_provider_source_startup.py | Route count31→33 and directly related comments only; preserve same-context constructor kwargs and ownership. |
| app/tests/test_deployment_prepare_integrity.py | Only test_install_routing_preserves_absent_schema_initialization: final SHAPE_V4→SHAPE_V5 and adjacent current-version comment; both entrypoints/guards/assertions unchanged. |
| app/tests/test_deployment_receipt_api.py | Only test_actual_v1_cold_http_upgrade_preserves_historical_reply_bytes: append literal (5,C5), final SHAPE_V4→SHAPE_V5/current-version comment; C1–C4 and all old HTTP replay assertions unchanged. |

No other writes. No worker/listener/broker/IPC changes (consume42), generic domain/store/ref/event
changes, old schema regeneration, initializer/geometry/trust changes, new catalog/startup key/service
owner, frontend, packaging or dependency changes. web_boundary.py remains UNCHANGED: its existing
provider descendant dispatch already forwards to the owned provider preflight with all required
limits/auth/error/state handling. Do not pad ownership with a no-op edit. The eight exact adapted
test files/interfaces are reconciled to accepted41 R1 (§12). Accepted42 actual-diff comparison and
full independent preflight remain mandatory before dispatch. Any additional edit requires a scoped
amendment; this candidate grants none outside the49 paths.

## 3. Fixed grammar, pure wire and signature boundary

All objects required/closed, canonical ADR008 JSON, no unknown/duplicate fields, coercion, floats,
bool integers, BOM/invalid UTF8/trailing bytes. UUID=canonical nonnil lower-case36. H=lowerhex64;
B32=canonical unpadded base64url32/43 chars; B64=unpadded64/86 chars with round-trip pad-bit check.
Time=calendar-valid ASCII UTC milliseconds through year9999; max epoch253402300799999. ID=existing
extension ID1..128; BrokerID=existing private-provider broker grammar1..64; instance=lowerhex32;
OciDigest=sha256:+H; platform=linux/amd64|linux/arm64. UInt32Positive=1..2**32-1.
Wire limits: receipt16384/depth12/items512/members32/string1024; evidence8192 with same depth/items/
members/string; anchor content/body8192; input4096/depth4/items32/members8/string256; cancellation/
consumed8192/depth4/items64/members16/string256. Composite bounds apply before full parsing.

### 3.1 Signed receipt

Exact23 fields:

    {schema:"deployment-provider-receipt-v1",domain:"deeptwin-deployment-provider-receipt-v1",
     request_id:UUID,request_digest:B32,request_nonce:B32,kind:"extension_stage",
     instance_id,origin_profile_digest:B32,deployment_profile_id:CurrentOriginalProfileId,
     operator_adapter:"deeptwin-provider-stage-operator-v1",operator_version:"1.0.0",
     effect_result:Result,started_at:Time,completed_at:Time,
     outcome:"succeeded"|"failed"|"unknown",failure_class:null|Failure,
     claimed_facts:[Fact],verified_facts:[Fact],unverified_facts:[Fact],key_id:UUID,
     trust_set_digest:B32,trust_class:"instance_operator",signature:B64}

Failure is operator_refused|precondition_failed|image_unavailable|effect_failed|
observation_unavailable|deadline_exceeded|operator_interrupted|internal_error. UnknownFailure is
the final four. Fact is request_binding|image_identity|mount_configuration|service_presence|
service_reachability|network_configuration|resource_configuration|operator_preconditions. Arrays
sorted unique0..8, pairwise disjoint and combined<=8. Unlisted is unspecified, not passed.

    Result={schema_id:"deeptwin.provider-stage-result.v1",extension_id:ID,
      expected_installation_head:{state:"absent"},expected_next_installation_revision:1,
      old_service:{presence:"absent"},new_service:Absent|Present|Unknown,
      stage_profile:"claude-text-transform-v1",
      source_context:{context_id:UUID,epoch:1,sha256:H,size_bytes:1..16384},
      geometry:{sha256:H,size_bytes:1..65536},preserved_inventory_sha256:H,
      preservation:NotAttempted|Preserved|Unconfirmed}
    Absent={presence:"absent"}
    Present={presence:"present",service_identity:BrokerID,manifest_digest:H,
      service_descriptor_digest:H,selected_platform_entry_digest:H,
      image_manifest_digest:OciDigest,reachable_after_effect:boolean,observed_at:Time}
    Unknown={presence:"unknown",expected_service_identity:BrokerID,expected_manifest_digest:H,
      expected_service_descriptor_digest:H,expected_selected_platform_entry_digest:H,
      expected_image_manifest_digest:OciDigest,failure_class:UnknownFailure,observed_at:Time}
    NotAttempted={state:"not_attempted"}
    Preserved={state:"preserved",observations:[Preservation0..1]}
    Unconfirmed={state:"unconfirmed",failure_class:UnknownFailure}
    Preservation={slot_id:1..16,service_identity:BrokerID,before:Snapshot,after:Snapshot}
    Snapshot={observed_at:Time,engine_id:NativeId,container_id:H,image_config_digest:OciDigest,
      started_at:NativeTime,restart_count:0..2**31-1,init_pid:1..2**31-1,
      configured_uid:UInt32Positive,configured_gid:UInt32Positive,
      socket_volume:OriginalVolumeName,socket_path:OriginalSlotPath,socket_read_only:false}

NativeId ASCII[A-Za-z0-9:._-]{1,128}; NativeTime calendar-valid UTC with exactly9 fractional digits.
Volume/path are exact slot-derived strings, additionally <=256 UTF8B each. Image_config_digest is
the operator's native image/config observation, not an OCI manifest digest proof. Snapshot equality
excludes only observed_at (NOT started_at). Require before.started_at <= before.observed_at when
compared losslessly at nanosecond precision. EVERY outcome unconditionally requires
request.created_at<=receipt.started_at<=receipt.completed_at<request.expires_at, including
failed/Absent/NotAttempted and empty-inventory failed/Absent/Preserved with zero observations.
Separately, every present native before/after.observed_at and every present target observed_at
must lie within [receipt.started_at,receipt.completed_at]. Preserve
before.observed_at<=after.observed_at; optional observations never replace the unconditional chain.

Preserved entries exactly match frozen inventory order and original slot/service/configured UID/GID/
socket volume/path; empty inventory requires empty observations. This is only a signed statement
of unchanged recorded socket-mount fields and no restart indicated by two native samples, not
continuous availability/all mounts/old artifact verification/core head proof/qualification.

| outcome | new_service | preservation | failure_class |
| --- | --- | --- | --- |
| succeeded | Present | Preserved | null |
| failed | Absent | NotAttempted,Preserved,Unconfirmed | Failure |
| failed | Unknown | Preserved,Unconfirmed | Failure |
| unknown | Unknown | Preserved,Unconfirmed | UnknownFailure |

For unknown outcome, new_service.failure_class equals common failure_class. Unconfirmed's failure
is its own closed UnknownFailure observation (need not equal a failed aggregate effect code).
NotAttempted means the producer knows no target effect began; consumer verifies the signed grammar,
not native truth. Target presence with unconfirmed preservation reports unknown/Unknown as aggregate
uncertainty, never fabricated absence or retry permission. Success need not assert reachability;
actual core identify remains mandatory.

Every request/result tuple is exact: UUID/digest/nonce/kind/instance/origin/profile; target ID, absent
head/next revision, service/manifest/descriptor; selected-platform-entry digest=H(SHA256(canonical
selected request entry)); image manifest retains OCI prefix; stage/context/geometry/inventory repeat
request bytes. Reparse actual18-file bundle and original profile, require its provider trust bytes
equal trust_bytes. Trust_set_digest is B32(SHA256(actual trust bytes)); key ID/public key/class/adapter/
version/current profile resolve together through accepted provider trust parser. Pure Ed25519 uses
existing receipt_crypto.verify_detached over exact canonical fields except signature, not a truthy
verifier result, custom crypto or old trust schema rewritten to provider. No sign function in core.

Pure times are request-relative only. Actual import enforces completed<=durable_now<expiry. Receipt
hash is SHA256(all signed bytes); request_digest excludes only request_digest as Task38 does.
Parsed/signed values remain inert; service owns admitted request/history/source/currentness/clock.

### 3.2 Command selectors and projections

Import input={command_id:UUID,request_digest:B32,receipt_digest:B32,expected_revision:1}.
Consume input={command_id:UUID,request_digest:B32,receipt_digest:B32,expected_revision:2}.
Pending-cancel input is exactly the consume shape, with its own endpoint/command namespace.
Each parser binds path request_id into the normalized private input, never into an extra wire field.
Prepared cancel input/Task38 marker stay byte-identical; dispatch strictly by exact closed shape and
expected revision, not caller schema text. New pending-cancel bytes:

    {schema:"deployment-provider-cancellation-v2",domain:"deeptwin-deployment-provider-cancellation-v2",
     request_id,request_digest,receipt_digest,instance_id,origin_profile_digest:B32,
     source_context_sha256:H,preserved_inventory_sha256:H,lifecycle_revision:3,cancelled_at:Time}

Derive from actual admitted succeeded receipt/request plus recorded cancelled time; import<=cancel<
expiry in service/history. Publisher pure check can prove only completed<=cancel<expiry, not import
time. Filename remains request digest hex64.json in cancelled; one winning marker, no overwrite.
Expiry emits no marker. Failed/unknown consumed bytes, derived after DB consumption exists:

    {schema:"deployment-provider-consumption-v1",domain:"deeptwin-deployment-provider-consumption-v1",
     consumption_id:UUID,request_id,request_digest,receipt_digest,instance_id,origin_profile_digest:B32,
     source_context_sha256:H,preserved_inventory_sha256:H,winning_lifecycle_revision:2,
     consumed_at:Time,outcome:"failed"|"unknown"}

Consumed filename is receipt digest hex64.json. No physical success marker; accepted3 uses actual
DB success consumption. Every UUID/B32/instance/type/derived field equality remains mandatory.

### 3.3 Core stage evidence, exact equations

    {schema_version:"provider-stage-postcondition-v1",request_id:UUID,request_digest:B32,
     receipt_digest:B32,request_blob_sha256:H,receipt_blob_sha256:H,source_context_sha256:H,
     preserved_inventory_sha256:H,observed_at:Time,attempt_ms:1..2000,
     expected:Expected,observations:[Observation1,Observation2],comparison:"equal"}
    Expected={service_identity:BrokerID,build_identity_digest:H,port_schema_set_digest:H,
     port_contract_version:"provider-port-v1",platform,uid:UInt32Positive,gid:UInt32Positive,
     worker_profile:"claude-text-transform-v1",implemented_transforms:["catalog","text"]}
    Observation={ordinal:1|2,observed_at:Time,connection_id:H,requester_boot_id:H,
     responder_boot_id:H,listener_record_sha256:H,peer_uid:UInt32Positive,peer_gid:UInt32Positive,
     nonce:H,challenge:H,request_message_id:UUID,reply_message_id:UUID,
     reply:{schema:"provider-worker-identity-v1",challenge:H,service_identity:BrokerID,
       build_identity_digest:H,port_schema_set_digest:H,platform,uid:UInt32Positive,gid:UInt32Positive,
       worker_profile:"claude-text-transform-v1",implemented_transforms:["catalog","text"]}}

Actual source: extension_channel(original instance,slot), _connect_extension_authenticated, unchanged
provider_messages codec. Two sequential fresh connections, one identify each; outbound
extension-request-v1 has correlation_id=None and body {schema:"provider-worker-identify-v1",challenge}.
Reply frame is extension-result-v1 with correlation_id equal its request ID. No tool probes or
semantic provider operations. Exact ordinals[1,2]; four pairwise-distinct message UUIDs, two distinct
connection IDs/nonces/challenges; nonce is fresh32 random bytes, collision refuses without retry loop.

challenge=H(SHA256(canonical_json({domain:"deeptwin-provider-stage-identify-challenge-v1",
request_blob_sha256,receipt_blob_sha256,source_context_sha256,preserved_inventory_sha256,ordinal,nonce}))).
Each reply echoes its own challenge. Both identity projections (all reply fields except schema and
challenge) equal Expected without port_contract_version, which is separately derived from lineage.
Both peer tuples equal expected UID/GID. Live requester IDs equal one current observer-process boot;
historical verifier compares them only to each other, never its new process boot. Responder boot IDs
equal each other and actual live records. Recheck after each validated reply; compare both live
record.unsigned() contents and persist H(SHA256(canonical unsigned record)) for each. Historical
parser checks equal well-formed digests only: no preimage is retained, no readiness-file inode claim.

Sample wall times after successful reply validation/recheck. Require actual imported/history times:
import_ms<=sample1_ms<=sample2_ms==evidence_ms<=acceptance_ms<expires_ms. Non-strict millis preserve
same-tick samples. Monotonic total starts before first acquisition and ends after second recheck;
ceil(elapsed_seconds*1000), minimum1, <=2000 and actual deadline still holds. Each connection is
bounded by remaining total and1000ms; first teardown is inside total, final teardown outside sampled
window. Wall subtraction is not a budget. Close every owned connection using accepted42 guarantees.
Challenges bind core-local inputs but do not attest that the worker understood/verified those bytes.

## 4. Fixed interfaces and actual retained source ownership

New pure APIs (ordinary failures use existing ReceiptWireError fixed codes or DeploymentPrepareError
invalid_input; pure request/result equality mismatch maps to service conflict, not signature success):

    parse_provider_receipt(raw:bytes)->dict
    verify_provider_receipt(raw:bytes,*,request_bytes:bytes,trust_bytes:bytes,
        source_bundle_files:tuple[tuple[str,bytes],...],profile:OriginProfile)->dict
    parse_provider_receipt_import(request_id:str,value:dict)->dict
    parse_provider_consume(request_id:str,value:dict)->dict
    parse_provider_pending_cancel(request_id:str,value:dict)->dict
    make_provider_pending_cancellation(*,request_bytes:bytes,receipt_bytes:bytes,
        profile:OriginProfile,cancelled_ms:int)->bytes
    parse_provider_pending_cancellation(raw:bytes,*,profile:OriginProfile)->dict
    parse_provider_consumed(raw:bytes,*,profile:OriginProfile)->dict
    validate_provider_channel_identity(value:dict)->None

Define frozen ProviderReceiptChannelIdentity in this pure module, with exactly the§4.1 fields and
validated as_dict(), not in the filesystem module. Both provider_sources and provider_receipt_sources
import that inert value/validator without importing each other during module initialization. It
contains no handle/FD/authority token. Explicit caller construction never establishes currentness.

Use a private ReceiptRequestMismatch subtype/code path to distinguish well-formed request-binding
conflict from malformed/bad-signature invalid_input; no raw detail in API. Pure functions accept
inert bytes, never authorized/already_validated flags. Snapshot parsing does not call native engine.

Observer APIs:

    ExpectedProviderStageIdentity (frozen slots; exact fields Expected; validated construction)
    ProviderStageEvidence (nonconstructible immutable content_bytes,digest,size_bytes)
    observe_provider_stage_postcondition(*,request_id,request_digest,receipt_digest,
        request_bytes,receipt_bytes,source_context_sha256,preserved_inventory_sha256,
        instance_id,slot_number,expected,deadline)->ProviderStageEvidence
    parse_provider_stage_evidence(raw:bytes)->dict

Observer validates input bounds/exact types before sockets, binds local hashes, but service alone
proves candidate/source provenance. Closed observer error codes probe_invalid/probe_mismatch/
probe_deadline/probe_unavailable; mismatch→conflict, other ordinary observation failures→
dependency_unavailable. Preserve process-control primary objects. No diagnostic bytes/paths.

### 4.1 Channel currentness and selected receipt

ProviderSourceContext private accessor:

    _provider_receipt_observation()->tuple[ProviderReceiptChannelIdentity,
        tuple[tuple[str,_ProviderNamespaceSnapshot],...]]

One complete before/after guard captures incoming root/receipts, consumed root/consumed identities,
their actual mount backing-root digests and all four namespace snapshots in requests,cancelled,
receipts,consumed order. It returns equal before/after observations only. Reuse shared scanners/
policies, no FD exports or unguarded late snapshot. Identity is a frozen inert value with as_dict():

    {schema_version:"deployment-provider-receipt-channel-identity-v1",source_context_sha256:H,
     incoming:{root:{device,inode},namespace:{device,inode},backing_root_digest:H},
     consumed:{root:{device,inode},namespace:{device,inode},backing_root_digest:H}}

Device=integer0..2**63-1, inode=1..2**63-1; exact object fields; canonical<=2048. Backing hash is H of
actual decoded mountinfo backing-root UTF8 text, no transient mount ID or caller path. Same actual
identity is persisted on first provider import and compared for every new import/consume/consumed
publication. Static context content pins/18 bytes supply source graph; this identity pins mutable
channel continuity. A restart cannot reenroll replaced roots under unchanged document hashes.

    open_provider_receipt_channels(context:ProviderSourceContext,*,profile:OriginProfile)
        ->ProviderReceiptChannels
    ProviderReceiptChannels.recheck_current()->ProviderReceiptChannelIdentity
    ProviderReceiptChannels.open_receipt(receipt_digest:B32)->ProviderReceiptFileLease
    ProviderReceiptChannels.publish_consumed(*,receipt_digest:B32,
        expected_payloads:tuple[bytes,...])->ConsumedPublicationObservation
    ProviderReceiptChannels.close()->None
    ProviderReceiptFileLease.receipt_bytes:bytes  # guarded read, not unchecked cache
    ProviderReceiptFileLease.recheck_current()->None
    ProviderReceiptFileLease.close()->None

Factory borrows SAME startup-owned exact context/profile; no path, native override, caller identity
or public constructors. Opens only four own directories at /run/deeptwin/provider-deployment-receipts
and /receipts child, and /run/deeptwin/provider-deployment-consumed and /consumed child. Incoming
20113:21201/0750, control RO; consumed20102:21201/0750, control RW; leaf finals0440/single-link.
Compare fresh own identities with context's combined guard on acquisition and each operation.
Own independent FDs, never borrowed context FDs; close only owned handles/selected leaves. Exact
type/hollow/subclass/closed refusal; context close invalidates operations without retarget/reopen.
Use accepted files helpers and provider namespace policies, no new duplicate scanner/framework.

Selected digest B32 converts to lowercasehex64.json; recheck full context, metadata membership,
selected final signature, open no-follow, read<=16384, hash matches selector, parse provider receipt,
repeat context/selected-file guard and bytes equality. Hold selected FD across preseal/final import
writer. Missing selector/source/ordinary OS failure→dependency_unavailable; malformed selected bytes/
hash/schema→invalid_input; source continuity mismatch→dependency_unavailable. Foreign incoming
finals remain metadata-only and do not count as admitted or get deleted; interrupted stages untouched.
Incoming64+32stage, consumed16+32stage; pernamespace96/aggregate240. No incoming writes.

Consumed expected_payloads: canonical tuple<=16/131072 aggregate bytes, ordered decoded receipt
digest hex, unique receipt and consumption IDs. Parse/derive context/profile joins for every payload;
actual service supplies complete committed intent set, including published markers. Recheck all
consumed final entries and exact bytes against that set; unknown/wrong final refuses without repair.
Target must be in set. Stage once using accepted publication._stage_payload/_commit_stage/
_existing_for_policy and fixed8192 policy, recheck before commit and after fsync/exact final read.
Existing exact final is fsynced/verified, no new rename. Return inert observation(role="consumed",
receipt_digest,payload_sha256,size_bytes,file_identity), never DB admission. Process-control cleanup
preserves primary and attempts all owned handles; normal context/source errors preserve fixed codes.

Factory/operation additions:4 retained directories+at most1 selected receipt FD or consumed staged
FD+1 final-read transient; only one active selected lease/publication per channel owner. Explicit
busy refusal, not concurrent mutation. Close is idempotent/exhaustive. Unsupported native platform
refuses before acquisition through accepted context/mount primitives; tests use controlled seams,
no positive production bypass. Combined startup context/new channels/publisher/IPC transient peak
must remain<=256 task-owned FDs, measured deterministically, not via process-wide scan.

### 4.2 Existing request/cancel publisher extension

Extend the actual39 factory with only the defaulted final keyword:

    open_provider_outbox_lease(context,*,profile,
        expected_payloads:tuple[tuple[str,bytes],...],
        expected_receipts:tuple[bytes,...]=())->ProviderOutboxLease

expected_payloads is role+bytes, NOT the consumed publisher's separate tuple[bytes,...] input.
Existing observe_existing/stage take keyword role/request_digest; commit consumes/closes its attempt.
Private context observation reuses the existing combined _read_observed guard, not detached or late
unguarded snapshots. Old empty behavior unchanged. Expected payloads retain
request16*65536+cancel16*8192=1179648B,
request-rank0/cancel-rank1 then decoded digest hex ordering. New receipts<=16*16384=262144B;
combined ceiling1441792B. Receipts ordered decoded request digest hex. Validate BEFORE directory
acquisition an exact bijection: one succeeded signed receipt for each v2 cancel, none for v1 or
unrelated request; unique request IDs/digests and signed receipt hashes, no extras/missing entries.
Verify every receipt against actual context trust and corresponding request; reconstruct exact v2
marker from request/receipt/cancelled_at. Compare request ID/digest, receipt full digest, context/
inventory/instance/origin/time, not just a supplied digest tuple. No receipt is published or imported.
No fresh wall-clock deadline in factory: a committed pre-expiry cancellation may publish after
expiry. Service/history owns import<=cancel<expiry; pure signature/marker does not prove attachment.
One winning cancel per filename, no v1→v2 replacement, same39 stage/commit ownership and no retry loop.

## 5. Domain graph, exact anchors and bounded historical ownership

Every new domain record is version1, operational, actual owner actor/access/retention roots and
actual vault through DomainStore. EntityRef has only kind/id/version/sha256, never vault_id. Use
existing domain nested reference walker/_put_in_transaction/_check_graph/bounded actual CAS; no
new record gateway or inferred authority from a parsed ref. Old schema export functions stay old.

Provider receipt content exactly:

    {schema_version:"deployment-provider-receipt-anchor-v1",request_ref:EntityRef(deployment_request,1),
     receipt_blob_ref:BlobRef(operational,<=16384),source_context_sha256:H,
     channel_identity:exact4.1 identity,import_command_id:UUID}

Receipt record ID=request ID, parent_refs=[request_ref], created at import_ms; actual receipt blob
same vault, complete hash/size; request's retained context owns all18 original/provider documents.
No duplicated18-blob receipt copy or old trust singleton substitution. Provider source index row
identity_json must equal actual admitted receipt channel_identity for EVERY receipt using it, and
source_context_sha256 equals indexed context/actual ordinal17 bytes. Source row exists iff at least
one provider receipt, exactly one row for that context, never standalone registration/migration data.

Provider installation content exactly:

    {schema_version:"extension-provider-installation-anchor-v1",extension_id:ID,
     manifest_digest:H,service_descriptor_digest:H,selected_platform_entry_digest:H,
     image_manifest_digest:OciDigest,platform,service_identity:BrokerID,
     staging_authority:"deployment-provider-receipt-v1",request_ref,receipt_ref,
     postcondition_evidence_blob_ref:BlobRef(operational,<=8192),consume_command_id:UUID,
     state:"staged",revision:1,previous_record_digest:null,installed_at:Time,actor_ref,
     stage_profile:"claude-text-transform-v1",source_context_sha256:H,preserved_inventory_sha256:H}

New installation ID is core UUID4; parents exactly[request_ref,receipt_ref]. Every tuple equals
admitted request/Present receipt; evidence equals actual observer bytes; created_at_utc=installed_at
converted to existing microsecond domain timestamp, actor_ref same actual requester. No new generic
staging authority in candidate manifest: its required deployment_operator tuple remains unchanged;
this anchor's literal names its specific verified receipt wire family only.

Reuse consumption anchor v1 exactly for failed/unknown (request/receipt parents, winning2) and v2
exactly for success (request/receipt/installation parents, winning3, succeeded,effect_ref). Each has
schema_version,request_ref,receipt_ref,winning_lifecycle_revision,consumed_at,actor_ref,transaction_id,
public_event_id,outcome; v2 adds effect_ref. Actual domain consumption UUID4, no new consumption
format/validator weakening; consumer verifies provider request/receipt/installation family joins.

Exact pre-materialization budgets, then exact graph set comparison/deduplication:

| Body | Max canonical body | Max edges / blobs |
| --- | --- | --- |
| old tool request/receipt/installation |8192 each|4/3;4/4;5/1 unchanged|
| provider request |8192|4/20 (request+inventory+18 documents, exact dedup)|
| provider receipt |8192|4/1|
| provider installation |8192|5/1|
| failed/unknown consumption |8192|5/0 unchanged|
| succeeded consumption |8192|6/0 unchanged|

Private scalar caps precede row loads; _anchor_dimensions must dispatch by bounded discriminator
without broadening old caps. Receipt/install/source/index/domain rows form exact bijections and
match actual root policies/actor/account/parents/blob lengths/hashes. Provider state may not be
injected as a tool shape or satisfy a provider relation with a missing source/receipt/install row.
Source identity is not authority when caller-created: only actual retained lease observations enter
first import, and actual domain anchor/CAS/history retains it afterward.

New private record interfaces (transaction-local dictionaries are projections, not public authority):

    load_sources(domain,db,roots,profile,journal,rows)->dict|None
    load_receipt(domain,db,roots,profile,item,source_binding,row)->dict
    load_installation(domain,db,roots,profile,item,consumption,row,head_rows)->dict
    expected_stage_identity(domain,db,profile,item)->ExpectedProviderStageIdentity
    accept_stage(domain,db,roots,profile,item,*,now,actor_ref,value,evidence,evidence_bytes)->dict

Expected identity comes from actual registered candidate CAS/provider lineage/selected platform
and actual original geometry; use code-owned four semantic schema bytes as41. Never from receipt's
asserted build, HTTP, source flags or an injected evidence_verifier. Load legacy installations with
old checks first, then provider receipt/consumption/install branch, then reconstruct each request's
frozen legacy inventory at its own event boundary. Provider head never enters that old snapshot.

## 6. Literal proposed v5 SQL

The following block contains ALL19 ordered statements (17 tables,2 explicit indexes), each CREATE
through semicolon is one string; preserve internal whitespace, exclude blank separators. Derivation
from normative41 v4 changes positions0 migrations,5 commands,8 receipts,10 consumed_outbox and adds
positions17 index,18 provider_receipt_sources. Everything else and C1–C4 remain literal-identical.
The added index is a composite FK target, not a second reservation/installation registry.

DDL_V5 canonical list length=19244 bytes; CHECKSUM_V5=9f3b9426d465524036c8c3ca48db3ba3360e284149b5cee8611aba0d6b4907d2.
C1=68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec
C2=d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f
C3=ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457
C4=f89a9a8ba7f98da44e4a48f63c0363d2bfa7fafe038bd19bfdc178396c4be7d2

Recomputed by text extraction plus standard JSON serialization (ensure_ascii=False, sort_keys=True,
separators=(',',':')) and SHA256 only, after asserting normative41's C4. No SQLite execution or
application import. This freezes candidate text, not tested migration correctness. The R2 constant/name/subscript-only
AST comparison established all17 actual41 DDL_V4 strings equal normative41,17696 canonical bytes/C4.
Accepted41 R1 leaves prepare_storage bytes unchanged, confirmed against accepted719. Candidate v5
remains19244/C5 unchanged. No application import, _expected invocation or SQL occurred.

```sql
CREATE TABLE deployment_prepare_migrations (
 version INTEGER PRIMARY KEY CHECK(version IN (1,2,3,4,5)),
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
 namespace TEXT NOT NULL CHECK(namespace IN ('deployment-prepare-v1','deployment-cancel-v1','deployment-cancel-v2','deployment-receipt-import-v1','deployment-consume-v1','deployment-prepare-provider-v1','deployment-cancel-provider-v1','deployment-receipt-import-provider-v1','deployment-consume-provider-v1','deployment-cancel-provider-v2')),
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
  OR (namespace='deployment-cancel-provider-v1' AND http_status=200 AND lifecycle_revision=2)
  OR (namespace='deployment-receipt-import-provider-v1' AND http_status=200 AND lifecycle_revision=2)
  OR (namespace='deployment-consume-provider-v1' AND http_status=200 AND lifecycle_revision=3)
  OR (namespace='deployment-cancel-provider-v2' AND http_status=200 AND lifecycle_revision=3))
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
 source_singleton INTEGER CHECK(source_singleton IS NULL OR source_singleton=1) REFERENCES deployment_prepare_receipt_sources(singleton),
 import_command_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_commands(command_id),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision=2), hash TEXT NOT NULL CHECK(length(hash)=64),
 provider_context_id TEXT CHECK(provider_context_id IS NULL OR length(provider_context_id)=36),
 UNIQUE(request_id,receipt_sha256),
 CHECK((source_singleton IS NOT NULL AND source_singleton=1 AND provider_context_id IS NULL)
  OR (source_singleton IS NULL AND provider_context_id IS NOT NULL)),
 FOREIGN KEY(vault_id,request_id,provider_context_id)
  REFERENCES deployment_prepare_provider_requests(vault_id,request_id,context_id),
 FOREIGN KEY(vault_id,provider_context_id)
  REFERENCES deployment_prepare_provider_receipt_sources(vault_id,context_id),
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
 payload_size INTEGER NOT NULL CHECK(payload_size BETWEEN 1 AND 8192),
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

CREATE UNIQUE INDEX deployment_prepare_provider_requests_vault_request_context
 ON deployment_prepare_provider_requests(vault_id,request_id,context_id);

CREATE TABLE deployment_prepare_provider_receipt_sources (
 context_id TEXT PRIMARY KEY CHECK(length(context_id)=36),
 vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id),
 identity_json TEXT NOT NULL CHECK(length(identity_json) BETWEEN 2 AND 2048),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 UNIQUE(vault_id,context_id),
 FOREIGN KEY(vault_id,context_id)
  REFERENCES deployment_prepare_provider_contexts(vault_id,context_id)
);
```

## 7. v5 bounded hashing, migration and historical verification

TABLES_V5=TABLES_V4 plus provider_receipt_sources. CAPS unchanged: control1,requests16,lifecycle48,
heads16,commands48,outbox32,receipt_sources1,receipts16,consumptions16,consumed_outbox16,
installations16,installation_heads16,provider_contexts1,provider_context_documents18,
provider_requests16; add provider_receipt_sources1. Migrations exactly(1,C1)..(5,C5). Index set is
exactly the two explicit indexes above plus SQLite autoindexes belonging to these constraints.
No views/triggers/cascade, undocumented columns/indexes or foreign attachments.

Scalars inspected by typeof/byte length before full materialization. New identity_json<=2048 canonical
UTF8 TEXT; provider_context_id nullable UUID with exact XOR source rule. In actual storage, add
_V5 through _freeze and its exact DDL-derived SHAPE_V5/COLUMNS_V5/TABLES_V5/CAPS_V5/NULLABLE_V5;
preserve all older layout objects. _private_sizes must choose2048 specifically for
(provider_receipt_sources,identity_json) before row materialization; old receipt_sources remains8192.
Add provider_context_id to _row's UUID handling and both new nullable receipt fields to v5 only.
Do not hand-write a competing column map or invoke application imports to derive it during design. Old rows: source_singleton=1,
provider_context_id=NULL. Provider rows: source_singleton=NULL, provider_context_id equals actual
provider_requests.context_id and source row's same-vault context. New composite index supplies the
SQL parent key for(vault_id,request_id,context_id); actual graph/membership still verified in Python.
SQL NULL checks are explicit; both-null/both-present cannot pass three-valued CHECK semantics.

Hash preimage remains {namespace,table,row}; `row` excludes only hash except the following explicit
legacy projection. For v5 receipts with provider_context_id NULL, omit that ONE added column and
hash all original v4 receipt columns under deployment-prepare-storage-v2, preserving old hashes.
For nonnull provider receipts hash ALL v5 columns except hash (including source_singleton:null)
under deployment-prepare-storage-v5. provider_receipt_sources uses storage-v5. All other tables keep
their old hash domains, even new command namespace texts and provider installation/head rows:
original tables storage-v1, receipt_sources/consumptions/consumed_outbox storage-v2, installation/
heads storage-v3, provider_context/documents/requests storage-v4. No old row is rehashed.
Consumed_outbox SQL permits8192 only so the provider arm can exist; old family Python cap stays4096,
provider cap8192 after joining its actual consumption/request. No global old-marker widening.

Actual existing storage.insert requires an exact column set. Preserve legacy receipt callers with
ONE explicit v5 compatibility projection there: only table=receipts, layout=_V5, exact original
v4 receipt input keys (excluding hash) and source_singleton=1 may synthesize provider_context_id=None
before strict row validation/hash/INSERT. Reject all other missing/extra-key cases; new provider
callers supply both explicit nullable fields. This does not default authority or widen other tables.
For layouts1..4 use their original key checks. On v5 reads _row still requires every actual column.
Keep validate_row v1-only and validate_current_row layout-dependent. The v4 receipt column order is
request_id,vault_id,kind,version,anchor_digest,receipt_sha256,receipt_size,outcome,source_singleton,
import_command_id,lifecycle_revision,hash; v5 appends provider_context_id AFTER hash. Old-layout
receipts without that key retain their original hash, just as projected v5 receipts with its NULL.
No generic missing-key default; the new source table order is context_id,vault_id,identity_json,hash.
Similarly identity_json dispatch is table-specific: old receipt_sources keeps its old validator;
provider_receipt_sources uses validate_provider_channel_identity with2048 cap. Do not send new JSON
through the old identity parser or globally loosen it. These are required actual storage-API joins,
not optional conveniences left to the implementer.

`prepare_storage._rebuild_v4_as_v5(db)->None` is invoked only through actual same-owner
PersistentDeploymentPrepare constructor/records.install under existing writer+DomainStore write
transaction. Preserve accepted v1→v2→v3→v4 paths, then v4→v5; already-v5 verifies only. Source-less
startup is allowed. No clock/RNG/event/CAS/domain write/source opening/publication during migration.
Absent schema follows existing orphan guards/chain. Old binary rejects new shape. No offline DB path.
Actual entry is prepare_records.install(domain,db,profile,*,candidate_registry), after its writer/
registry checks and full semantic verify. Append the v4→v5 step there and verify before/after;
do not redirect prepare_records.install_storage or storage.install, which remain v1-only helpers.
Preserve _rebuild_v3_as_v4 itself, including its four incoming command edges, immediate-v3 rowid
snapshot, two-parent rebuild and original checkpoint ordering. New v5 migration validates grouped
composite receipt FKs separately; the old single-column fk[1]==0 check cannot admit that composite.

Before mutation, exact v4 shape/hash/domain/history/FK verification; capture bounded typed rows,
old-column projection bytes, canonical TEXT/BLOBs/hashes and explicit rowids of rebuilt tables.
Only migrations,commands,receipts,consumed_outbox are rebuilt. Enumerate incoming FK metadata across
actual tables and reject every unexpected edge/action before deletion. Allowed incoming edges:

- commands: lifecycle.command_id; receipts.import_command_id; consumptions.command_id;
  installations.command_id, exactly their v4 definitions/actions.
- receipts: consumptions.(request_id,receipt_sha256)→receipts.(request_id,receipt_sha256), exactly v4.
- migrations and consumed_outbox: none. Unrelated application schema stays untouched.

Require foreign_keys=ON throughout, defer_foreign_keys=ON verified1 within writer. Snapshot before
mutation. Delete consumed_outbox, receipts, commands(descending lifecycle_revision), migrations;
drop only these four; recreate their new literals; create new composite index and source table;
restore old rows with explicit rowids and every old column verbatim, adding NULL only for receipt
provider_context_id. Restore all parents before final verification (deferred children stay in place),
append5/C5, compare snapshots and all untouched rows, then complete semantic verify and FK check
before commit. No rename/TEMP/ATTACH/executescript/FK-OFF/writable_schema/prune/repair.

Preservation means all existing cells/typed old-column projections/rowids, immutable domain/CAS/
event/counter/replay bytes identical. Receipts have one deliberately added NULL cell; do not falsely
claim their full new-column tuples equal old tuples. No SQLite page/WAL identity claim. Immediate-v4
rowids are preserved; earlier accepted v1–v3 rebuild limitations remain, not retroactively rewritten.
Every failure at delete/drop/create/restore/verification rolls back exact old logical schema/rows.

Source row index exists iff provider receipt(s); identity equals each provider receipt anchor,
context is actual same request's retained context and source docs. No provider source-only positive
migration fixture. Receipt row provider_context_id iff actual provider request/receipt anchor family;
legacy source row must not accept provider receipt. Old singleton source may coexist unchanged.
Receipt complete bytes/outcome/import command/time/domain ownership/signature/request/source joins
rechecked on every historical load using retained CAS, not current filesystem or current clock.

Actual prepare_records.verify already bounds request anchors, loads provider context, compares request
discriminator with provider_requests row presence and dispatches request load. Its subsequent old
receipt/consumption/installation calls must branch BEFORE parsing provider bytes. Add family marker
reconstruction before the existing consumed-outbox validation; preserve global anchors/events/
head/source iff checks and final verify_inventories. Reuse unchanged consumption semantics/shapes
only where applicable. No old loader may first parse and then discard a provider record.

Keep actual provider_prepare_records signatures:
load_context(domain,db,roots,profile,control,rows) returns None or
{row,files,refs,value,topology,exchange}, with files the exact18 CAS bytes and refs ordered
{name,blob_ref} wrappers. Context presence remains iff provider request presence, not receipt presence.
load(domain,db,roots,profile,control,row,*,context,provider_row) returns
{ref,row,anchor,actor,request,raw,control,context,provider_row,inventory_raw,topology,exchange,
topology_raw,exchange_raw}; prepare_records adds history/head/outbox/receipt/consumption/
consumed_outbox/installation. These actual transaction-local joins feed the new receipt helper;
no public caller dict or new domain/store wrapper authority.

Retain provider request edges4/blobs20, raw request65536/inventory16384; old request edges4/blobs3,
old receipt edges4/blobs4, old consumption accepted6/rejected5 edges and0 blobs, old installation
edges5/blobs1. New family caps in§5 apply only to new branches. No global association/blob cap widening.

Installation/head bijection allows0..1 legacy +0..1 provider only; no extra qualified/bound states,
disconnected heads or mixed family anchors. Legacy staged event uses tool metadata; provider event
uses provider metadata below. Load both installation families/events before final inventory checks.
inventory(domain,db,roots,profile,journal,*,source_bundle_files,at_event_sequence) must validate actual
installation/staged-event association, then skip entries staged AFTER that historical boundary,
THEN require included entries to be legacy with exact accepted/staged/head joins. Provider installation
at/before the boundary refuses, not silently omitted. verify_inventories(domain,db,roots,profile,journal)
still requires each frozen sequence precede its prepared event and byte-exact reconstructed inventory.
Head_digest remains actual storage-v3 installation_heads hash, not a new digest definition.

Fresh prepare/request publication must explicitly refuse ANY verified provider installation in actual
provider_prepare_service._business, not only in inventory serialization: the accepted41 total-installation
count<=1 alone does not exclude a sole provider. Existing terminal reservations still count and
replayed old commands bypass new admission only after complete historical verification.

## 8. Exact lifecycle, public events, command history and responses

Legal provider history paths (no other edge):

    prepared1 -> cancelled2 | expired2 | receipt_pending2 | rejected2
    receipt_pending2 -> cancelled3 | expired3 | accepted3

prepared/cancelled2 behavior and frozen replies remain41/38 byte-identical. Receipt_pending requires
one succeeded receipt, no consumption/install/cancel/consumed intent. Rejected requires one failed/
unknown receipt plus one consumption-v1 and one consumed intent. Cancelled3/expired3 retain their
succeeded receipt, no consumption/install; cancelled3 has one v2 cancel intent, expired3 has none.
Accepted3 requires succeeded receipt, exactly one installation/head and consumption-v2; no cancel
or consumed intent. All branches preserve reservation. No first receipt overwrite or receipt retry.

Every transition advances head/hash and appends exactly one lifecycle event through existing
prepare_lifecycle._append_transition/event_fields. Pending request intent is suppressed on ANY
transition out of prepared1; published intent remains published. Thus receipt-bearing request
publication_state is published|suppressed, never pending. Non-success/acceptance domain/index writes
and frozen command are in that same writer. No consumed effect is inferred from a signed statement.

Command namespaces/status/revision:

| Operation | Namespace | HTTP | Revision |
| --- | --- | --- | --- |
| existing prepare | deployment-prepare-provider-v1 |201|1|
| existing prepared cancel | deployment-cancel-provider-v1 |200|2|
| import any outcome | deployment-receipt-import-provider-v1 |200|2|
| consume success | deployment-consume-provider-v1 |200|3|
| pending cancel | deployment-cancel-provider-v2 |200|3|

Global command ID uniqueness crosses all old/new namespaces. Normalized input includes bound path
request_id for cancel/import/consume. input_digest=H(SHA256(canonical_json({namespace,instance_id,
origin_digest,actor_ref,input}))), preserving actual existing helper conventions. Every non-expiry
actor is original request's actual owner actor; expiry uses actual roots.actor/system, has no command
and existing generated event correlation UUID. Exact namespace/actor/input replay returns original
stored status/receipt bytes before fresh source/time/RNG/probe checks, even after later state/source
loss/restart. Changed namespace/actor/input or second distinct command for a won transition conflicts.
Whole historical verification precedes replay; corrupt DB does not get a replay bypass.

Actual prepare_lifecycle.verify already delegates provider items; leave that shared file unchanged.
provider_prepare_lifecycle.verify must delegate receipt-bearing history BEFORE its accepted41
prepared/cancelled/expired-only and no-receipt-object checks. Preserve original branches.
Its private _body(item,*,command_id=None,cursor=None) constructs old self/cancel/events links;
read_body(item) wraps it. Do not add receipt/consume fields or links to _body globally.
Historical command verification reconstructs prefix history, pending request for prepared and pending
cancel for cancel, then compares the exact old _body. Continue reconstructing those snapshots after
receipt-bearing successors. Preserve cursor generation compatibility, not a demand for today's
generation in frozen replies. Only new commands/receipt-bearing reads use the new helper's family.

Use existing public event vocabulary/envelope helper, no new event schema:
receipt_pending/rejected emit deployment.receipt_committed with status pending/failed/unknown from
outcome, error outcome_unknown only for unknown, metadata{revision:2}. accepted emits
deployment.request_accepted/status succeeded/metadata{revision:3}. cancelled/expired existing events
use revision2|3, status cancelled/blocked; expired error stale_state. Lifecycle object_ref is actual
request ref, actor kind human except system expiry, causation null, actual timestamps/policy/retention.
Acceptance then appends immediately next event extension.staged, actual installation ObjectRef,
human same actor, status succeeded/error null, metadata{extension_kind:"provider",
trust_tier:"runtime_worker",revision:1}; correlation=consume command ID, causation=accepted event ID.
Both have empty private_evidence_refs and retention_class core, policy actual access root. Do not
call old tool-only staged_event_fields with a provider; new helper supplies this exact metadata via
unchanged _append_event_in_transaction. Staged sequence=accepted sequence+1 in same transaction.
consumption.event_id is acceptance for success, receipt_committed for non-success; installation row
event_id is staged. Commands' frozen cursor is the transition event cursor (accepted, not staged).

### 8.1 New closed command receipt-v2 and read-v2

Every listed field required; nullable means literal null only in matrix below. Command receipt-v2
fields (<=8192 canonical bytes):

    {command_id:UUID,request_id:UUID,request_digest:B32,kind:"extension_stage",
     state:"receipt_pending"|"rejected"|"accepted"|"cancelled",revision:2|3,
     publication_state:"published"|"suppressed",
     cancellation_publication_state:null|"pending",consumption_publication_state:null|"pending",
     source_context_sha256:H,preserved_inventory_sha256:H,receipt:ReceiptSummary,
     consumption_ref:null|EntityRef(deployment_receipt_consumption,1),
     installation_ref:null|EntityRef(extension_installation,1),event_cursor:string1..4096,links:Links}
    ReceiptSummary={receipt_ref:EntityRef(deployment_receipt,1),receipt_digest:B32,
      outcome:"succeeded"|"failed"|"unknown",import_revision:2}
    Links={self:string1..256,cancel:string1..256,receipts:string1..256,
      consume:string1..256,events:string1..128}

| command state/rev | receipt outcome | cancel pub | consumed pub | consumption/install refs |
| --- | --- | --- | --- | --- |
| receipt_pending2 |succeeded|null|null|null/null|
| rejected2 |failed or unknown|null|pending|actual/null|
| accepted3 |succeeded|null|null|actual/actual|
| cancelled3 |succeeded|pending|null|null/null|

New read-v2 fields are precisely command receipt fields minus command_id/event_cursor, plus request
complete exact Task38 provider request bytes parsed as object. Add expired3 state; allow pending|
published for nonnull cancellation/consumption publication. Expired3 is succeeded receipt with
both pub markers null and both refs null. Other row relations exactly above. Cap73728 canonical
bytes, embedded request<=65536. All summaries/refs/digests match actual admitted journal, not caller.
No raw signed receipt/native snapshot/secret/qualification placeholder in public response.

Only receipt-bearing reads use v2. Prepared1/cancelled2/expired2 with no receipt keep exact Task41
read-v1/links/body. Existing prepare and prepared cancel always replay old command-v1. New frozen
replies never change after marker publication; GET can report later published marker state.

Links unprefixed exact PATH=/api/v1/deployment/provider-requests:
self=PATH+"/"+request_id; cancel=self+"/cancel"; receipts=self+"/receipts";
consume=self+"/consume"; events=/api/v1/events. Stored frozen bytes unprefixed. HTTP projection adds
actual OriginProfile base path exactly as old router; exact request ID/path/profile checked at
runtime. Patterns anchored with optional /[0-9a-f]{32} prefix and canonical36 UUID path; never allow
external URLs or alternate route IDs. event_cursor actual decoder/stream event relation, not arbitrary
string; permit existing cursor-generation advancement without rewriting frozen cursor bytes.

New API schema is oneOf: unchanged38 prepare/prepared-cancel inputs, new import input, pending
selector (structurally shared by consume/pending cancel), unchanged41 command-v1/read-v1, new command
v2/read-v2 and exact errors below. Do NOT put identical consume/pending-cancel shapes twice in oneOf;
both standalone exports have their own URNs but the aggregate references their common shape once.

All twelve schema filenames in§2 use Draft2020-12 and
urn:deeptwin:schemas:v2:deployment:{filename-stem}; sorted UTF8 JSON two-space indent/final newline.
Factory names are filename stems with hyphens→underscores plus _schema, except provider_receipt_api_schema
for provider-receipt-api-v1; exported_schemas maps exactly these twelve files, fresh detached values.
Inline/reuse accepted exact scalar/provider identity/38/41 schema factories; no network $ref retrieval,
second canonicalizer or old export widening. Runtime byte bounds supplement structural schema limits.

## 9. Actual service operations, source/time/error/replay order

Add @closed methods on SAME PersistentDeploymentPrepare (same actual owner/domain/registry/RLock):

    import_provider_receipt(authenticated_request,request_id,payload)->dict
    consume_provider_receipt(authenticated_request,request_id,payload)->dict

Delegate to same-named functions(service,...) in provider_receipt_service. Keep existing cancel_provider/
read_provider; delegate pending selector and receipt-bearing read only. New lifecycle helper APIs:
`transition(db,roots,profile,item,*,state,now,actor_ref,value=None,receipt_outcome=None)->dict|None`,
`read_body(item)->dict`, `verify(db,roots,profile,item,commands)->None`,
`staged_event_fields(roots,installation_ref,now,actor_ref,*,correlation_id,causation_id)->dict`.
These receive actual transaction-local item projections, not browser authority.
Actual @closed holds the existing RLock and error partition; _journal performs complete verification.
Extend _replay's explicit operation namespace map for import/consume and pending-cancel-v2 without
widening any old family. Existing read_provider uses the actual writer/auth(read=True)/full journal
then lifecycle.read_body; retain it. Existing cancel_provider replays before head/time and commits
expiry before conflict outside the writer; add pending-selector dispatch without replacing that arm.

Import steps:

1. Closed selector parse/authentication/full journal/replay under existing first admission boundary.
   Wrong-family ID not_found; request digest/revision/state mismatch conflict. Require prepared1,
   no receipt, exact current managed legacy inventory, target absent, no provider install or
   qualification/binding. Sample actual owner/_now/control floor; at/after expiry atomically expire2
   and suppress pending request, exit writer, then conflict (do not roll expiry back by raising inside).
2. Under first writer open actual context-backed channels, compare actual18 source bytes to retained
   request/index graph and current identity to source row if enrolled. Select actual incoming receipt;
   verify signature/request/source/time. Keep selected lease/channel owner live through preseal.
3. Outside writer preseal exact selected receipt bytes via DomainStore.put_blob(operational). No raw
   browser receipt input, detached channel identity or source path. A losing race may leave an
   unreferenced blob, never an admitted anchor/index/receipt/event.
4. Final writer reauth/full journal/replay race/head/deadline/managed inventory/candidate/request
   reconstruction; recheck live context/channel identity/selected file currentness and byte equality,
   repeat signature joins, sample last durable now/floor and require completed<=now<expiry. If expired,
   commit expired2 then conflict outside writer. Before first receipt create source row from ACTUAL
   observed identity; otherwise require exact existing identity. Put receipt anchor/index, transition,
   frozen command; for failed/unknown also actual consumption-v1 and consumed intent, all one writer.
   Whole journal reverify before commit. No installation, active provider or binding from import.
5. Close selected lease then channel owner with primary-preserving exhaustive cleanup. Best-effort
   bounded reconciliation after success; return frozen200 bytes, never publication-dependent success.

Consume steps:

1. Authenticate/replay/full journal; require receipt_pending2, exact request/receipt selectors and
   succeeded receipt. First writer expires before opening socket. Reconstruct expected identity from
   actual candidate/lineage/source graph, current preserved inventory/target absence; open actual
   channels, compare enrolled physical identity/context bytes. Never acquire absent-slot metadata
   lease after an operator may legitimately populate it. Slot routing derives original geometry.
2. Outside writer actual observer obtains two fresh authenticated connections, no injected success
   callback. Preseal actual evidence bytes. Keep channel owner for final source-currentness check;
   IPC connections are separately owned/closed by observer using42. No selected incoming FD required
   for consume: immutable admitted receipt is read from actual CAS, not reimported/reselected.
3. Final writer repeats auth/replay/head/actual clock/expiry/candidate/context/channel identity/current
   managed inventory and expected identity. Reparse evidence and complete timing/hash/identity joins.
   Expiry wins at/after deadline; commit expired3 before conflict. No qualification/binding managed
   state or pre-existing target/provider install may appear between observation and writer.
4. Core allocates installation and success-consumption UUIDs. Put installation+head, accepted3,
   consumption-v2, accepted then contiguous staged events, frozen command and all indexes atomically;
   actual source/receipt/request/evidence refs and same-vault graph checked. Journal reverify before
   commit. Any failure leaves no acceptance authority; old heads/records/events remain unchanged.
5. Close owned channels without closing startup context. Return frozen200; no success marker/send.

Ordinary observer error maps as§4 and leaves pending unless a subsequent actual writer checkpoint
observes expiry. No invented timer transition or terminal failed installation on a probe refusal.
Every new operation uses existing monotonic wall-clock floor/overflow checks; source timestamps do
not advance authority. Exact replay/GET requires no fresh clock/source/RNG/signature under a new key.

Pending cancellation needs exact input2, attached succeeded receipt, original actor, receipt_pending2;
no live source/slot/managed inventory required to RECORD it. Before expiry commit cancelled3+v2 intent+
new frozen command; at/after expiry commit expired3/no marker then conflict. Reconcile may remain pending
on unavailable source; cancellation remains durable. Both expiry forms reserve forever. New family
IDs never enter old routes, and legacy IDs never enter provider receipt/consume routes after auth.

Errors use existing DeploymentPrepareError envelope, no raw path/crypto/native diagnostics:

| code | HTTP | message |
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

Each requires exactly{code,message,retryability:"not_retryable",affected_refs:[],correlation_id:UUID}.
Selected malformed/bad-signature receipt invalid_input; well-formed wrong request binding, future
completion, expected revision/inventory/identity mismatch conflict; source/currentness/ordinary OS/
unavailable probe dependency_unavailable; actual graph/journal/SQLite corruption unavailable.
Preserve process-control exceptions; no broad exception-to-success or parser dict authority.

## 10. Reconciliation, projections and actual API wiring

`provider_receipt_service.reconcile_consumed(service,request_id)->None` runs only from actual verified
journal under existing service RLock/writer with owner check. Load all committed provider consumption
intents, construct exact expected marker tuple and actual context/channel identity. Require every
journal-published consumed final exists with exact bytes; unknown/conflicting final denies this item,
not deletion. Publish/verify once, repeat source currentness, then ackCAS pending1→published2 with
actual durable published_ms>=consumption_ms and<=clock floor. No expiry condition for this already
committed consequence. If native commit exposes bytes then DB rollback/source postcheck failure,
intent remains pending; next bounded run observes exact final/fsyncs/acks, not duplicate consumption.
No file/DB atomicity claim, no marker deletion or native effect retry.

Provider cancel reconciliation builds actual complete request/cancel payload tuple plus succeeded
receipt tuple for v2 cancels only, from verified CAS/history. It does not require current slot absence
or current managed inventory. It verifies admitted import/cancel times, calls extended39 publisher,
and permits publication after expiry. All expected old/v1 payloads and frozen reply bytes unchanged.
Build request-rank0 then cancel-rank1 role+bytes pairs in decoded request-digest order as actual41
does; pass succeeded receipts only for v2 markers. Existing rev1 orchestration acknowledges using
the owner clock and may expire afterward; do not falsely claim it has no clock. Implement the
new post-expiry v2-cancel branch explicitly while preserving _highest/floor and durable history.
The pure publisher/codec uses admitted import/cancel times, never a fresh wall-clock eligibility test.
Preserve accepted41 R1 finalizer guard: when an exception is active, no finalizer SELECT, floor or
journal verification can replace it; normal/early returns retain all three. New family finalizers
must preserve primary process-control objects while attempting all owned cleanup (§12).
Provider request publication remains41's actual gate only for prepared1; no later request re-exposure
after import/cancel/expiry. At first import a pending intent is suppressed, not falsely acknowledged.

Keep bounded cooperative1-second/at-most16 intents per reconcile call, no scheduler/public retry/
loops. Mixed order: provider cancellations, then existing old cancellations/consumed in old ordering,
then provider consumed, then request intents; request_id order within new classes. Failure consumes
one attempt and may permit next item while budget remains. Startup and successful commands reconcile;
GET/exact replay do not. Old item branches remain unchanged; corruption still poisons normally.
The actual provider reconcile_item currently accepts only request/cancel. Dispatch provider consumed
to the new helper BEFORE that guard. Keep the shared deadline/16-item budget and old-only ordering.
Shared work already considers receipt_pending expiry; add exact family expiry handling there.
No new startup source opener or persistent channel export: each new command/reconcile owns its short
channel owner and borrows SAME37 context; startup owner alone closes context once.

Append exactly two route declarations to existing deployment-prepare-v1 contribution/factory:

| route_id | methods | path | scope |
| --- | --- | --- | --- |
| deployment.provider-requests.receipts |POST|/api/v1/deployment/provider-requests/{request_id}/receipts|deployment.manage|
| deployment.provider-requests.consume |POST|/api/v1/deployment/provider-requests/{request_id}/consume|deployment.manage|

Existing provider cancel path admits the new pending selector; provider GET/HEAD chooses exact v1/v2
body by actual receipt presence. Actual catalog/router composition uses same service and startup
context. Existing eight routes unchanged; total ten in contribution. No new catalog export, route
owner, role/scope or frontend. UNCHANGED web_boundary already dispatches every provider descendant
to provider_deployment_prepare.preflight and stores provider_deployment_payload, with closed4096B
POST JSON, empty query, raw path/UUID/base-path/Host/Origin/session/CSRF/scope checks. Add suffix
parsing only inside owned provider preflight with its existing depth4/items32/members8/string256
limits; no new state key/auth/route-family matcher. Preserve GET/HEAD zero body and existing headers.
Router calls actual service via run_in_threadpool and returns canonical bytes; POST replies200 for
new methods, original prepare201. Existing response wrapper projects only links and checks service
base_path; old caps8192 command/73728 read remain. Shared deployment_error/ERRORS already match§9
and remain unchanged. Base-path projection preserves frozen replay. No bytes/path/key upload
endpoint, list/status/retry route or caller proof fields.
Preserve old routes' relative declaration order and append the two new contribution declarations.
New router registrations may naturally append; do not freeze first/last positional endpoint indexes.
The two accepted41 R1 tests named in§11.1 must select exactly one actual route by PATH and exact
methods instead. Preserve their actual response closure/endpoint and every byte/base-path assertion;
do not change response constructors to accommodate the tests.

## 11. Exact tests and preservation gate

Write independent tests before shared-file edits. Controlled tests use real isolated DomainStore,
owner/session/candidate service, actual38/41 requests, actual37 guarded trees, actual files and accepted
IPC framing/worker identify. Tests may replace explicit native mount/metadata observations in the
same manner as accepted upstream fixtures; do not mock source recheck, journal verify, owner authority,
signature verifier, publisher success or observer evidence to manufacture the vertical happy path.
Public synthetic signing seed used only in fixture code; no production signing code or real secrets.

| Test file | Meaningful acceptance vectors |
| --- | --- |
| test_provider_receipt_contracts.py | Independent signed preimage/vector; every signed field tamper; bad signature/key/adapter/profile; old/provider cross-family; refreshed wrong source/context/geometry/inventory/request hashes; all outcome/preservation/time arms, including a correctly re-signed reversed-start/completion failure with zero observations (Absent/NotAttempted and empty-inventory Absent/Preserved);0/1 old snapshots and unsupported2; named socket fields/config IDs/nanosecond parse; canonical encoding/duplicate/missing/extra/caps; cancellation/consumed reconstruction and pure after-expiry use without clock. |
| test_provider_receipt_schema_exports.py | Exact twelve fresh exports/URNs/bytes; runtime/schema valid-negative parity; each closed field and state matrix; shared consume/cancel selector included once in aggregate oneOf; exact old41/38/tool artifact bytes unchanged. |
| test_provider_receipt_sources.py | Real four directories/selected leaf and full context; same-guard identities/backing hashes; selected swap/rename/link/mode/size/hash; unselected invalid-but-metadata-safe receipts remain opaque; interrupted stages survive; bounds96/240; acquired cleanup/lease-close/context-close; source root replacement cannot reenroll after import; single active operation and no borrowed close. |
| test_provider_stage_observer.py | Actual worker serve_one twice/real authenticated connections and framing; correct outbound None/reply correlation; exact two samples/identity projection; new process boot on historical replay accepted; wrong peer/build/schema/profile/transform; repeated IDs/nonces/challenges/boot drift/listener content; hash grammar/equality without fake preimage reconstruction; first sample before import/reversed times; total/perconnection monotonic budget; no readiness-inode/semantic-operation claim; no fallback probe. |
| test_provider_receipt_migration.py | Genuine accepted owner/candidate commands create immediate-v4 old prepared/published/cancelled/expired/rejected/accepted histories and provider prepared/cancelled/expired (separate fixtures where old first-only rules require).19-string checksum/exact tables/indexes/C1–C5; rowids/old-column typed bytes/hash/null projection and unrelated domain/CAS/event/counter/replay preserved; unexpected inbound edges, missing composite index/source rows; every delete/drop/create/restore/check failure rollback; source-less no clock/RNG/event write. Earlier starts retain accepted chain then immediate-v4 guarantee. |
| test_provider_receipt_records.py | Actual domain put/load/check_graph; wrong vault/composite source/request/context FKs; source identity index vs anchor; capped legacy/provider blob/edge sets; receipt/source iff discriminator; orphan/half rows; signature/time/actor/event/command refresh attacks; one actual provider + one old tool history; exact preserved inventory at boundary after new head exists; no second provider install/fresh prepare; no fake qualification/binding. |
| test_provider_receipt_service.py | True request→selected signed receipt→pending→actual two-connection observe→atomic staged/consumed success; failed/unknown import→consumption/marker intent; no installation on signature alone; cancel prepared/pending and expiry boundaries; actor/global command collisions/replay before source/time/probe; two real service races; context/file/inventory/candidate drift between phases; same writer rollback at every authority write; fresh prepare after acceptance denied; source-less historical reads/replay/cancel recording. |
| test_provider_receipt_reconciliation.py | Actual accepted39 default behavior; exact request/cancel/expected_receipts bijection/order/1441792 cap before FDs; valid committed v2 cancel after expiry publishes with no fresh publisher clock; missing/wrong receipts; consumed131072 bound; exact-existing/fsync/NOREPLACE and stage/rename/fsync/postcheck/DB ack crash windows; pending recovery no second event/consumption; source continuity replacement; published missing/alien final refusal; malformed incoming remains opaque; bounded mixed old/new continuation. |
| test_provider_receipt_api.py | Actual server/session/catalog/web-boundary/service/source composition; POST41 prepare→actual temp receipt ingress→POST receipts200 pending→POST consume200 staged→GET200/HEAD→restart/replay canonical bytes; both origin modes/base paths; old route/family separation; new cancel rev2 selector; schema matrices; auth/CSRF/Host/Origin/query/media/body/UUID errors; no extra routes or hidden raw bytes; SAME startup context closes once. |

Fixture/service fault tests may inject a refusal or failure checkpoint, but the positive acceptance
must use the real observer/crypto/journal/channel path. Two-sample physical operator facts in synthetic
receipts remain labeled unverified native design assumptions, not real engine proof.

### 11.1 Exact eight existing-test adaptations against accepted41 R1

All paths here are app/tests/; coordinates identify accepted41 R1, except unchanged sites retain
their earlier coordinates. Semantic function names govern. Full preflight and accepted42 remain
required before implementation; R1's added assertions remain unchanged, with only the two endpoint
selectors explicitly adapted below (§12).
Append literal C5 where a current migration list is asserted; retain every C1–C4 literal. Historical
layout/checkpoint tests keep their exact old shape; no global v4→v5 find-and-replace.

| Existing file/site | Only permitted adaptation |
| --- | --- |
| test_deployment_receipt_migration.py:38–45 | Current constructor list adds C5; SHAPE_V5/current-version comment. Preserve snapshot_v1 external fixture (only original v1 tables), old-installer refusal/write-free startup (:177), concurrent snapshots (:200), all replay assertions. |
| test_deployment_journal_v3_migration.py:24–27, :117–119, :397 | Add literal C5; current shape/layout/list advance to v5. In snapshot (:36), use receipts-only explicit original COLUMNS_V2/V3 column-order projection instead of SELECT *; when v5 is present separately assert added provider_context_id NULL and old source_singleton=1. Keep all other fields/caps/order and populated rejected receipt comparison (:391–407). Historical to_v2 (:79), rollback SHAPE_V2 (:204) and intermediate fault semantics unchanged. |
| test_provider_prepare_migration.py:21, :125–130, :173, :319 | In legacy_projection, use receipts-only rowid plus exact COLUMNS_V3[receipts] order, separately asserting new NULL/source1 on v5; all other old columns/hash/domain/CAS/event/rowid snapshots unchanged. Constructor endpoints add C5/_V5. Preserve V3 fixtures/assertions (:60/:150/:301), intermediate _V4 verification fault (:218), and all19 original v4 destructive checkpoints (:244–281); new v5 faults belong in new consumer migration tests. |
| test_provider_prepare_migration.py:177 (same file) | For test_corrupt_v4_shape_or_migration_never_rebuilds, add a narrowly scoped sibling to install_empty_v3: FIRST obtain a genuine already-initialized owner/service/candidate registry, THEN convert only its verified EMPTY deployment journal to exact v4 and use that SAME existing service for real old commands before mutating the SAME old index/C4 sites. A newly constructed current service after conversion would immediately migrate to v5; construct it only for the intended reopen/migration assertion. No populated-v5 downgrade or production stop-migration hook. |
| test_provider_prepare_api.py:224/:260 | Preserve POST random UUID/receipts with {}→400: malformed closed selector, not proof of route absence. Clarify that meaning and add a truly unknown suffix case. Existing positive prepare/read/head/cancel/replay and old41 schema assertions unchanged. Exact ten-declaration/new-route checks belong in new test_provider_receipt_api.py. |
| test_provider_prepare_api.py::test_actual_response_formatters_enforce_canonical_byte_boundaries | Replace only router.routes[0] selection with the unique route whose path==PATH and methods=={"POST"}; assert exactly one match, then retain getclosurevars(selected.endpoint).nonlocals["response"]. Import PATH alongside create_router. Keep every formatter/body/UTF8/cap/base-path assertion unchanged. |
| test_provider_prepare_api.py::test_real_read_projection_refuses_base_path_different_from_actual_profile | Replace only router.routes[-1] selection with the unique route whose path==PATH+"/{request_id}" and methods=={"GET","HEAD"}; assert exactly one match, then invoke that actual endpoint unchanged. Import PATH alongside create_router. Preserve wrong-base-path setup,503 and successful direct-read assertions. |
| test_first_party.py:93 | Count32→34 and comment31 installed→33 installed; example contribution semantics unchanged. |
| test_provider_source_startup.py:299 | Count31→33 only; preserve exact context constructor kwargs/frozen pins/original source identities and ownership/close assertions (:128). |
| test_deployment_prepare_integrity.py:342 | Only test_install_routing_preserves_absent_schema_initialization final :377 SHAPE_V5/comment. Preserve constructor/records_install arms, empty-schema/empty-data, not_found and all separate integrity tests. |
| test_deployment_receipt_api.py:1088 | Only test_actual_v1_cold_http_upgrade_preserves_historical_reply_bytes :1120 list append (5,C5), :1123 comment/:1127 SHAPE_V5. Preserve owner/login, C1–C4, actual history equality, old install refusal and all replayed HTTP bytes. |

This table contains eight files; provider_prepare_migration has two scoped rows. Receipt projection
is necessary because v5 adds one NULL column: do not claim whole SELECT * tuples unchanged or hide
arbitrary fields. Assert every old typed cell/rowid/hash and the new NULL separately. No shared
historical fixture file is writable. The new consumer fixture must create genuine immediate-v4
provider history through actual41 commands, then exercise v5 reopening, not prefilled receipt tables.

test_provider_sources.py remains unchanged covering scope. Its accepted :574 import-isolation test
uses a fresh bounded subprocess with Directory.open/read_mountinfo/native_platform all forbidden;
preserve it and the exact ProviderSourceContext class identity. No parent-module reload or guard
replacement. The unchanged web_boundary is exercised through the actual new API happy/refusal paths.

Narrow covering tests (no tests run for this candidate): all new test_*.py above plus unchanged
test_deployment_prepare.py, test_deployment_prepare_storage.py,
test_deployment_prepare_publication.py, test_deployment_prepare_api.py,
test_deployment_prepare_contracts.py, test_deployment_prepare_v2_contracts.py,
test_deployment_prepare_v3_contracts.py, test_deployment_prepare_v2_schema_exports.py,
test_deployment_receipt_journal_integrity.py, test_deployment_receipt_journal_reconciliation.py,
test_deployment_receipt_import.py, test_deployment_consume.py,
test_deployment_consume_api.py, test_deployment_acceptance.py, test_first_party_dependencies.py,
test_provider_sources.py, test_provider_prepare_contracts.py, test_provider_prepare_records.py,
test_provider_prepare_service.py, test_provider_prepare_reconciliation.py,
test_provider_prepare_api_schema_exports.py, test_provider_publication.py,
test_provider_publication_lifecycle.py, test_provider_slot_lifecycle.py,
test_provider_stage_connection_lifecycle.py and the eight narrowly adapted test files in§2/11.1.
All test basenames in this paragraph are under app/tests/. The new observer additionally covers
unchanged test_extension_listener.py, test_stage_observer.py, test_provider_worker.py there.

Review one complete delivery in order: old characterization→codecs/guarded source→v5 full history→
actual import/pending cancel/expiry→real observer/one-writer acceptance→outbox crash recovery→actual
HTTP/restart. No table-only or protocol-only completion. Report exact49-path hashes/diff, independent
RED/GREEN results, measured task-owned FD peak and untouched old schema/byte assertions. No source
or test outside the frozen table becomes writable without controller amendment.

## 12. Accepted dependencies, evidence carry-through and dispatch gate

Tasks39/40 factory/attempt/role+bytes and source observation interfaces are confirmed in
task-43-acceptance-reconciliation.md, now updated by the controller to accepted41 R1 status.
task-43-frozen41-reconciliation.md and R2 diff remain historical pre-R1 evidence, not a competing
current contract. Task41 R1 is ACCEPTED by the controller after task-41-r1-review.md (I1/I2 addressed,
no new Critical/Important findings). Its frozen719 manifest identifies the accepted source snapshot.
A text-only manifest comparison shows exactly six changed paths from pre-R1; current hashes of those
six and storage/API/provider-record/provider-lifecycle dependencies match accepted719. No moving42
source was read; a whole current-worktree hash claim is intentionally NOT made during its active work.

| Accepted41 R1 delta | Required Task43 preservation; no ownership expansion |
| --- | --- |
| provider_prepare_service.py:619 | Only production edit: active-exception guard now precedes finalizer SELECT/floor/journal. Keep it; new family paths cannot regress primary exception handling. Already Task43-owned. |
| tests/provider_prepare_fixture.py | Adds defer_legacy_stage=False and actual.stage_legacy(), factoring real old registration→prepare→signed import→consume while retaining immediate default/single outer yield. Reuse unchanged; NOT Task43-owned. |
| tests/test_provider_prepare_reconciliation.py:356 | Actual publisher stage plus primary SystemExit/KeyboardInterrupt and secondary floor/SELECT failure; checks primary identity, pending intent, handles and retained context. Unchanged covering family; add new-family counterparts in new receipt tests. |
| tests/test_provider_prepare_records.py:20 | Actual consumer rejects CAS-sealed forged inventory with real DB events/head refs. Consumer-level negative proof, NOT a fully rewritten persisted graph forgery. Keep unchanged; new receipt historical reconstruction gets its own actual tests. |
| tests/test_provider_prepare_service.py:59/:146/:203 | Real candidate-CAS/managed-history drift, permanent terminal slot/extension reservations and valid alternate-context refusal. Preserve unchanged; no new registry/rotation permission. |
| tests/test_provider_prepare_api.py:19/:96/:139 | Actual formatter8192/73728 multibyte boundaries, rehashed frozen-link rejection, real wrong-base-path read projection. Internal boundary inputs, NOT legal public padding. Only two positional endpoint selectors change as precisely authorized in§11.1; all other added-test behavior remains unchanged. No new path ownership. |

No DDL/C4/column/hash/insert/migration or public API/wire change occurred in R1; C5 remains
9f3b9426d465524036c8c3ca48db3ba3360e284149b5cee8611aba0d6b4907d2 (19 strings/19244 bytes).
The accepted eight-family R1 run reports199passed/1 inherited warning in362.95s, separate from the
prior ordered421 run and initial failed32-family run; this candidate reran none. M1 Starlette/AnyIO
deprecation remains visible; M2 missing historical graph-RED chronology remains disclosed. Neither
fixture failures, internal padded responses nor targeted negative consumer inputs repair that history
or become persisted-forgery/native evidence. Preserve these ledger carry-throughs in Task43's report.

Before dispatch: full independent Task43 contract/brief preflight must be READY; Task42 must finish,
receive independent acceptance, and have its actual final diff/interfaces/correlation/cleanup
guarantees compared by the controller to provider-stage-connection-lifetime.md. Any difference
requires bounded reconciliation before writing Task43 code. Do not read or patch its active source
to guess its eventual guarantee. The42 contract preserves protocol/peer/HMAC/deadline/error semantics
and promises primary-preserving exhaustive cleanup on the finite reached requester chain, NOT
responder-wide safety, arbitrary kernel interruption atomicity or provider admission.
Only after those gates may a fresh sole writer execute this49-path delivery. No implementation
authorization is implied by this contract's canonical-directory location. Text checks cannot prove
v5 FK/rollback/history/HTTP/FD behavior; required RED/GREEN and final frozen coverage remain work.

The external producer separately must freeze native API/version/finite bounds and actual immutable
candidate/descriptor/policy/selected OCI artifact acquisition. Current request hashes/MetaRefs do
not supply artifact access or a registry URL. This contract candidate contains no operator effect/signing/repair
callback and cannot claim whole-provider deployment. Neither these signatures nor identify schemas
satisfy permission/isolation/egress/secret/compatibility, durable qualification/binding or live-send
issuance. No source-context rotation/new topology is required by the payload families above.

## 13. Post-freeze1 fixture-only timing reconciliation

The frozen45-family run reported1487passed/2failed/one inherited warning. Its manifest/package
remain immutable. Shortest unchanged two-node replay passed, while a read-only instrumented legacy
node reproduced pending publication: real final before_deadline sampled11.127ms beyond its1s budget,
with no source failure. This is lawful cooperative refusal, not grounds to widen production time.
The diagnostic overlapped another focused test; no standalone performance-regression cause is claimed.

Controller amendment adds ONLY app/tests/test_provider_prepare_service.py to original ownership:
within test_real_staged_legacy_installation_is_frozen_at_provider_boundary, after real fixture setup,
replace module-local time references in prepare_service and provider_prepare_service with a
SimpleNamespace containing one sampled fixed monotonic value and unchanged real time.time_ns.
Use scoped monkeypatch restoration, never modify the shared time module. All existing inventory,
exact row digest, event order and published assertions stay byte-for-byte. This isolates history
semantics from machine throughput; it does not prove publication completes within a real second.
Beforecopy SHA256:54b74254069629ccd2d88af83ee2cc377d255ba1ac223ce6b35d52ec43c65a75,
captured against accepted720 baseline before amendment. Total50=29new+21modified;
final749=699unchanged+21modified+29new. No old test beyond this function may change.

In already-owned test_provider_receipt_reconciliation.py, control_cleanup must start an actual
service.reconcile_startup() pass rather than inherit a stale private-pass deadline. In that fault
scope only, use the same deterministic monotonic/time_ns value pattern for prepare_service and
provider_receipt_service so the intended committed-primary/secondary-close checkpoint is reached.
Keep identical primary, all cleanup/state/journal/FD assertions. The separate deadline arm keeps
its explicit expired budget and no-publication assertions; do not globally freeze time or alter
production checks. Existing cooperative-budget-exhausted-after-stage test remains unchanged.

Focused GREEN: both new deadline/cleanup arms, amended legacy-history node and the unchanged
cooperative-budget-exhausted-after-stage node. Then freeze2 and run exactly these three whole
families in order once: test_provider_receipt_reconciliation.py, test_provider_prepare_service.py,
test_provider_prepare_reconciliation.py. Normal tracing-off Python-B/pytest-q/no-cache flags apply.
Verify747freeze1 source paths unchanged and exactly these two test files changed; preserve all
production/schema bytes. Review receives original full49-path package PLUS exact two-file freeze2
overlay and this amendment. No fresh all-green45-family or whole-product test claim is permitted.
Independent review may judge this ruling and any remaining limitations; it is not self-acceptance.
