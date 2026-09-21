# Private provider conformance protocol

2026-09-20. Normative scoped implementation contract for Task45. Controller promotion follows
full independent preflight and scoped R1 approval; this authorizes only reversible local product
implementation and synthetic tests. It does not authorize native operator work, real credentials,
paid/live model calls, qualification/binding or release/publication.

This is the reviewed provider-conformance B plan. Task43 provides accepted staged-provider history;
Task42 provides requester cleanup; Task44 provides finite shared-store cleanup. Their acceptance
is recorded in resumption-plan.md and progress.md. All seven product journeys remain required.

## 1. Deliverable and type decision

Deliver an authenticated browser-route command on the real owner/DomainStore, resolving the actual
Task43 staged provider, running only four code-owned public vectors through the actual private
worker client, retaining bounded raw observations, independently comparing them, atomically sealing
immutable history/events, and rehydrating that history after restart without probing again.
No UI admin screen, CLI prerequisite, native collector, network/provider call, credential/grant,
semantic provider-port operation, qualification/binding head or execution_ready toggle is added.
Task30 credentials remain stored_unbound; Task32 generation remains denied; Claude stays API-only
and Codex subscription plus optional API remain product scope, not permissions issued here.

Use ONE additive EntityKind `provider_conformance_run`, operational purpose only. Version1 is an
immutable intent; version2 is its sole terminal report, not a replacement of version1. This is a
command/evidence history in the SAME database, not a second installation registry. Reasons:

- data-model.md:135 defines ProposedCommand as a message-linked model proposal without human
  authority. Authenticated core execution intent is not that entity, even if its generic parser
  would accept an arbitrary dictionary.
- data-model.md:476 defines ValidationReport around growth candidate/evaluator/K0–K7 results.
  Reusing it would create a misleading path toward growth promotion. This new kind cannot satisfy
  validation_report, qualification or extension_qualification consumers.
- refs.py:14–29 owns EntityKind/ObjectRef kinds; schemas.py:103+ dispatches actual envelope checks;
  store.py:247+ discovers exact EntityRefs/BlobRefs and verifies the real graph. Do not bypass them.

## 2. Exact candidate ownership —34 paths:23 new,11 modified

All app paths below are relative to app/; schema paths are repository-relative.

| New path | Sole responsibility |
| --- | --- |
| workers/provider_client.py | Production fixed-vector requester, bounded transcript, real authenticated connection ownership; no arbitrary transform public API. |
| extensions/provider_conformance_contracts.py | Closed command, context, transcript, reply and comparison values; strict canonical byte limits/errors. |
| extensions/provider_conformance_vectors.py | Four literal vectors, suite manifest/digest and independent application-level oracle. No worker-transform import. |
| extensions/provider_conformance_resolver.py | Read-only actual43 journal/source/candidate resolution adapter; no cached caller dictionary authority. |
| extensions/provider_conformance_records.py | Intent/report construction, exact graph/index/event joins and actual retained-byte rehydration. |
| extensions/provider_conformance_storage.py | Three-table/one-index additive same-store version1 layout and bounded verification. |
| extensions/provider_conformance_service.py | Owner command/read, durable intent, guarded execution/finalization/recovery; no background runner. |
| extensions/provider_conformance_schema_exports.py | Three new detached structural schemas/exporter. |
| domain/provider_conformance.py | Pure new-kind header/content/parent/version validators and content schema. |
| api/provider_conformance.py | Closed two-route adapter, actual service factory, error/reply/base-path handling. |
| api/route_contributions/provider-conformance-v1.json | Fixed route declarations and browser_session scopes. |
| tests/provider_conformance_fixture.py | Actual owned temp store/source/stage/worker/app fixture; public synthetic evidence only. |
| tests/test_provider_client.py | Real framed/streamed requester and bounded protocol failures. |
| tests/test_provider_conformance_vectors.py | Independent literal expected bytes and suite identity. |
| tests/test_provider_conformance_contracts.py | Closed syntax/domain/export/event parity and old-record preservation. |
| tests/test_provider_conformance_records.py | Actual CAS/graph/history and rehydration corruption checks. |
| tests/test_provider_conformance_storage.py | Exact layout/additive install/history rollback/caps. |
| tests/test_provider_conformance_service.py | Actual stage→intent→six connections→report/event/replay. |
| tests/test_provider_conformance_api.py | Actual authenticated composition and two-route vertical. |
| tests/test_provider_conformance_lifecycle.py | Deterministic acquisition/interruption/race/crash cleanup and recovery. |
| schemas/v2/extensions/provider-conformance-input-v1.schema.json | Closed POST input. |
| schemas/v2/extensions/provider-conformance-reply-v1.schema.json | Closed pending/terminal reply. |
| schemas/v2/extensions/provider-conformance-record-v1.schema.json | New kind's version1/version2 complete envelope. |

| Modified path | Exact allowed delta |
| --- | --- |
| domain/refs.py | Add provider_conformance_run to ENTITY_KINDS; resulting LOCATOR_KINDS inclusion is navigation only. No new purpose. |
| domain/schemas.py | Invoke pure validator only for new kind; old dispatch/error/body rules unchanged. |
| domain/schema_exports.py | Add exact new-kind conditional branch; existing branch contents unchanged. |
| domain/events.py | Add exactly provider.conformance_started/completed and exact-required metadata for those two only. |
| schemas/v1/domain-envelopes.schema.json | Regenerate additive kind/locator/closed-body changes. |
| schemas/v1/event-metadata.schema.json | Regenerate exactly two added event payload definitions. |
| api/first_party_catalog.py | Append one fixed contribution after deployment with dependencies/exports below. |
| api/web_boundary.py | Narrow new family preflight/body-limit/state/error dispatch; preserve every old family. |
| deployment/prepare_service.py | One private read-only delegate `_provider_conformance_subject(db, installation_ref)`; no old lifecycle/replay/DDL behavior change. |
| tests/test_first_party.py | Existing total route declaration expectation34→36 only, after actual43 reconciliation; preserve every endpoint/auth assertion. |
| tests/test_provider_source_startup.py | Route count33→35; the bounded composition/dependency fixture amendment in§10 is also allowed. Preserve all four original source/cleanup cases and assertions. |

Do not change worker, broker, listener, IPC roots, streams, source18, original topology/recipe,
private-worker/schema identities, candidate registry, old deployment SQL/C1–C5, qualification/model
catalog, generic DomainStore or public-event storage. No dependency additions. Schema writer also
emits worker-response-capture and owner-auth-public: those two outputs must remain byte-identical.
Old DOMAIN RECORD/command/replay bytes stay unchanged; the two aggregate export FILES deliberately
change. Any future release/source-bundle digest containing changed core files must be recomputed in
its own release build; do not preserve a false old digest or edit historical build locks/images.
The worker's four provider-port schema bytes and its measured image identity do not change here.

## 3. Values, context and actual interfaces

Notation: H=lowercase64hex, U=existing canonical nonnil UUID; all generated IDs are UUID4. N is an
exact non-boolean integer0..2^63−1. Time is epoch milliseconds0..253402300799999. Domain timestamps
are the existing six-digit UTC form; milliseconds convert by appending000 microseconds. EntityRef
is existing exact kind/id/version/sha256, never vault_id. BlobRef is the actual same-vault operational
ref; no hash-only substitute. Every object below is CLOSED; unknown/missing/null fields fail unless
explicitly allowed. Canonical JSON is refs.canonical_json/parse_canonical, not a second canonicalizer.

POST input `{command_id:U, installation_ref:EntityRef(extension_installation,version1)}` <=4096B;
no body schema selector, vector, model, text, worker path, test callback, clock, capability or pass map.
Command identity is H(canonical input). The new command namespace is this family only; never claim
global uniqueness against unrelated legacy command tables. Same ID/different actor/input conflicts.

Required new Python interfaces (to be implemented):

    PersistentProviderConformance(domain_store, owner_authority, *, prepare_service, source_context)
      .execute(authenticated_request, payload) -> dict
      .read(authenticated_request, command_id) -> dict
      .rehydrate(db, run_ref) -> RehydratedConformance
    resolve_subject(prepare_service, db, installation_ref) -> ConformanceSubject
    require_current_subject(prepare_service, db, subject, source_context) -> None
    run_fixed_suite(subject, *, deadline, guard) -> ConformanceCapture
    compare_capture(subject, capture) -> ConformanceComparison
    rehydrate_conformance(prepare_service, db, run_ref) -> RehydratedConformance
    install(db) -> None; verify_layout(db) -> None
    verify_history(prepare_service, db) -> tuple[RunHistory,...]

contracts exports `ConformanceError(code="invalid_input")` with only§8 error codes, `parse_command(value)
->dict`, `parse_capture(raw:bytes)->ConformanceCapture`, `parse_reply(raw:bytes)->dict`.
It also defines/exports the internal ConformanceSubject value with the exact rules below.
domain validator exports `validate_body(body)->None`, `content_schema()->dict`; it handles only the
new kind. Schema module exports `input_schema`, `reply_schema`, `record_schema`, `exported_schemas`
(three filename→fresh dict entries) and `write_schemas(destination)` (writes exactly those three).

Vectors module exposes `fixed_vectors()->tuple[FixedVector,...]` and `vector_manifest()->bytes`.
FixedVector is frozen: vector_id, operation, plan_bytes, input_bytes:tuple[bytes,...],
supplied_bodies:tuple[bytes,...], expected_projections:tuple[bytes,...], expected_result_bytes.
Expected projections are the canonical digest projections defined§4, not random live controls.
ConformanceCapture exposes content_bytes only; ConformanceComparison is frozen with completion,
reason,vectors:tuple[(vector_id,comparison),...],covered_subchecks:tuple[str,...].
RehydratedConformance is frozen with intent_ref,report_ref,subject,comparison,capture_bytes:bytes|None.
History verification calls a private one-run loader and then checks global bijections; rehydrator
selects from that verified result, never recursively calls itself or accepts cached passed results.

The private prepare delegate is `_provider_conformance_subject(db, installation_ref)`. It first calls
this exact prepare service's `self._domain._assert_write_transaction(db)`, then invokes the internal
resolver with this service, the already-active writer and the closed installation EntityRef. The B
constructor requires `domain_store is prepare_service._domain`, `source_context is
prepare_service._provider_context` and the existing owner/registry/profile associations; it accepts
no second store or source authority. The resolver calls
`prepare_service._journal(db)` once and consumes its verified provider item. It does not hand-call
Task43 loaders as a public API, accept a caller journal/subject, acquire `prepare_service._lock`, or
call `_admit`, `_managed`, `read_provider` or any other @closed prepare method. The delegate itself is
not @closed. Existing Task43 public operations remain prepare-RLock→global-writer; the B sequence is
global-writer→assertion→journal with no prepare-RLock edge, so it cannot reverse that order.
ConformanceSubject is a NEW value defined only in the already-scoped
`extensions/provider_conformance_contracts.py` and exported there for internal Python consumers;
it is not an existing application class or an HTTP input. It is a frozen, slotted dataclass with
`init=False` and a `__new__` that refuses ordinary construction with TypeError. Only the resolver's
private `_subject_from_verified_item(prepare_service, db, item)` allocates it via `object.__new__`
and fills slots with `object.__setattr__`, after the required exact active-writer/journal/identity
validation. The helper is not a public factory or dependency-injection argument. Historical loading
uses that same helper on the historically verified journal item, without demanding live sources or
the current head. Fresh resolution additionally performs the existing current-head/source guards.

The complete runtime field set is the21 exact durable projection keys listed below plus `uid` and
`gid`. Each string/int uses the specified exact type; the four `*_ref` values are frozen EntityRef
instances, `implemented_transforms` is the immutable tuple `("catalog", "text")`, and uid/gid are
exact non-boolean uint32 values from `provider_receipt_records.expected_stage_identity`, never the
worker. No mutable projection dictionary is stored. `as_dict()` returns a fresh exact durable
projection, converting refs with as_dict and that tuple to a fresh list, EXCLUDING uid/gid.
Context digest is H(canonical as_dict()) only. Dataclass equality and hashing cover ALL23 immutable
runtime fields including uid/gid; a source-less rehydrated subject must equal the original when
all retained inputs are identical. All internal subject consumers require `type(subject) is
ConformanceSubject`; no subclasses/duck types. Pure parsing of a persisted projection never
constructs an admitted subject. This construction discipline is not a Python security sandbox or
authority by type alone: actual same-store history and fresh guards remain mandatory.

The service does not accept a subject from callers. run_fixed_suite is an INTERNAL function: its guard is the
service's closed no-argument current-pending/source check, never supplied to constructor/API by caller.
All public constructors reject fake/mismatched DomainStore, PersistentOwnerAuthority, prepare owner/
domain/source associations. No production client/observer/replayer/evidence-verifier injection.

Subject's durable projection is exactly:

    {vault_id:U, instance_id:hex32, origin_digest:H, topology_id:U,
     source_context_sha256:H, provider_geometry_sha256:H,
     installation_ref, candidate_ref:EntityRef(extension_manifest,1),
     request_ref:EntityRef(deployment_request,1), receipt_ref:EntityRef(deployment_receipt,1),
     platform:"linux/amd64"|"linux/arm64", selected_platform_entry_digest:H,
     image_manifest_digest:"sha256:"+H, service_descriptor_digest:H,
     service_identity:existing BrokerID, slot_id:integer1..16,
     build_identity_digest:H, port_schema_set_digest:H, port_contract_version:"provider-port-v1",
     worker_profile:"claude-text-transform-v1", implemented_transforms:["catalog","text"]}

slot_id and geometry are EXACT original provider request/source projection, not assigned by B;
internal slot_number=slot_id, no alias field or second number. Context digest = H(canonical this
projection). Use the exact accepted producer chain
`PersistentDeploymentPrepare._journal(db) -> prepare_records.verify(...)`; its internal loaders
materialize retained context/source18, request/candidate, provider receipt, shared consumption and
provider installation. Select exactly one accepted provider item whose installation ref equals the
closed input, including SHA. Require head revision1 and installation-anchor digest equal the input
ref SHA; successful receipt; accepted history; consumption effect_ref equal installation_ref;
provider staged authority/state/revision; and exact record parents receipt=[request],
installation=[request,receipt], consumption=[request,receipt,installation]. Derive identity only with
`provider_receipt_records.expected_stage_identity(domain,db,profile,item)`, not the same-named legacy
prepare helper. UID/GID are INTERNAL subject scalars from that identity, never worker assertions.

Map durable fields only into the EXISTING exact Subject projection above. In particular,
`provider_geometry_sha256` is produced by
`item["request"]["effect_payload"]["geometry"]["sha256"]`; its paired size is checked against
retained `geometry.json`. Context id/epoch/size, geometry size, installation manifest digest and head
revision/digest remain validation predicates or transitively bound by exact refs; they are not new
Subject fields. Old tool installs, orphan/generic forged anchors, other vaults, superseded heads and
missing candidate/support byte joins fail.

At every already-scheduled fresh current-subject/source guard, require
`prepare_service._provider_context.read_current() == item["context"]["files"]`, comparing all18
ordered names and bytes. `recheck_current()` alone cannot replace an equality sample. This adds no
guard/background loop and changes no deadline or cap. Absent/closed context on fresh pre-intent
admission is unavailable/503; an exact historical ref that is no longer current is conflict/409.
After intent admission, source/head drift follows the existing source_changed/incomplete finalization
only while owner/store authority remains valid; otherwise pending remains. Replay is checked before
live source. Historical replay/rehydration remains source-less and does not rerequire current head.
Original topology ID and physical slot identities remain unchanged; no second slot registry.

On replay/history reads do not require current source/worker or reread current installation authority:
rehydrate the exact historical graph. A new run needs current exact stage/source. Future C requires
current verified-installation descendant plus its own expanded qualification context, not this
staged-only historical loader. RehydratedConformance carries immutable intent/report refs, historical
subject, raw capture bytes and independently recomputed comparisons; no qualified/valid-until token.

## 4. Fixed suite and independent literal oracle

Suite version `private-provider-conformance-v1`; requester/comparator IDs are respectively
`private-provider-requester-v1` / `private-provider-literal-oracle-v1`. These are code-owned versions,
NOT measured/authenticated runtime release provenance. No invented framework/runtime digest.
Freeze ordered four vectors below. B must not import provider_transform or call Claude parser code
to produce EXPECTED results. Using provider_messages parsers for actual syntax is permitted.

Let J be existing canonical_json, h=SHA256 hex, model=`claude-conformance-fixture`, input bytes
`b"hello conformance\n"`. Text plan P is J of:

    {"profile":"claude-text-transform-v1","model_id":"claude-conformance-fixture",
     "max_output_tokens":32,"messages":[{"role":"user","input_ordinals":[0]}],
     "inputs":[{"size":18,"sha256":h(b"hello conformance\n")} ]}

NOTE size is len literal=18, with exactly one LF. Expected text projection bytes are J of:

    {"model":"claude-conformance-fixture","max_tokens":32,"stream":true,
     "messages":[{"role":"user","content":[{"type":"text","text":"hello conformance\n"}]}]}

SSE encoding E(t,fields)=b"event: "+ASCII(t)+b"\ndata: "+J({"type":t,**fields})+b"\n\n".
Supply ONE text/event-stream body formed by concatenating these six events, in order:

    message_start: {message:{type:"message",role:"assistant",model,content:[],
                            usage:{input_tokens:3,output_tokens:0}}}
    content_block_start: {index:0,content_block:{type:"text",text:""}}
    content_block_delta: {index:0,delta:{type:"text_delta",text:"answer"}}
    content_block_stop: {index:0}
    message_delta: {delta:{stop_reason:STOP},usage:{output_tokens:4}}
    message_stop: {}

Expected result base `{schema:"provider-transform-result-v1",operation:"text",input_digest:h(P)}`.
Expected observation `{requested_model:model,observed_model:model,text_blocks:BLOCKS,stop_reason:STOP,
usage_observed:{input_tokens:3,output_tokens:4,cache_read_input_tokens:null,
cache_creation_input_tokens:null},usage_complete:null}`.

| vector_id | STOP / BLOCKS / expected state / reason |
| --- | --- |
| text-basic-v1 | end_turn / ["answer"] / parsed_complete / complete |
| text-refusal-v1 | refusal / [] / non_success / refusal |

Both must first project endpoint=messages, step1, after_id=null and exact body above. Supply bytes
only after that independent comparison; an alien projection gets no supplied body and is mismatch.
Catalog plan Q=J({profile:"claude-text-transform-v1",limit:1000}), no input batch. Define M(id) as
{type:"model",id,display_name:"Fixture",created_at:"2026-01-01T00:00:00Z"}; page(id,more,extra) is
J({data:[{**M(id),**extra}],has_more:more,first_id:id,last_id:id}). All responses status=supplied.

| vector_id | Supplied pages / required projections / expected result |
| --- | --- | --- |
| catalog-two-pages-v1 | page("one",true,{}) then page("two",false,{}); models step1/after_id=null then step2/after_id="one", both body=null | operation=catalog,input_digest=h(Q),state=parsed_complete,reason=complete; observation page_digests=[h(page1),h(page2)],complete=true,models=[N("one"),N("two")] |
| catalog-negative-capability-v1 | page("one",false,{capabilities:{unexpected:-1}}); models step1/after_id=null/body=null | operation=catalog,input_digest=h(Q),state=invalid_response,reason=catalog_incomplete; observation page_digests=[h(page1)],complete=false,models=[] |

Catalog results also contain schema=provider-transform-result-v1. N(id) is EXACTLY
{id,display_name:"Fixture",created_at:"2026-01-01T00:00:00Z",max_input_tokens:null,max_tokens:null,
capabilities:null}; no sorting/normalization beyond these literal values. Negative capability checks
a precise existing parser rule, not a general safety/secret/egress test.

Suite manifest is closed `{schema_version:"provider-conformance-vectors-v1",vectors:[...]}` with
four ordered entries `{vector_id,operation,plan_sha256,input_sha256s,supplied_body_sha256s,
projection_sha256s,expected_result_sha256}`. Hash canonical bytes; projection hashes are canonical
{step,endpoint,after_id,body_sha256:null|H} with streamed body digest, excluding random dialogue IDs.
Every SHA derives from the literal bytes above; report the computed constant during implementation
and test independent construction. No release/image digest default is generated by this process.

## 5. Real requester, raw observations and finite resources

Sequential six NEW authenticated connections: identify-before, the four vectors in manifest order,
identify-after. No connection reuse/retry, general generate/text input/cancel/status/catalog-refresh
API, tool stage-probe/execute, provider HTTP, SDK, engine socket or database/CAS mount in worker.
Use extension_channel(instance_id,slot_number), actual listener._connect_extension_authenticated,
provider_messages, ArtifactDescriptor/BytesSource/BytesSink/send_batch/receive_batch and
ConnectionStreamTransport. No test fixture requester in production. A new internal recording proxy
may forward read/write to its actual owned ExtensionConnection: transport supports those methods;
it holds NO FD and cannot manufacture an authenticated connection. No source-object adapter.

Use exact private worker contract start/ready/inputs/projection/response/final order and every
correlation/descriptor/dialogue/step/media/hash/size check. Outbound first request correlation=None;
reply correlation equals ACTUAL request message ID, not challenge/dialogue ID. Fresh UUID4 dialogue,
batch and message IDs; all control/frame IDs unique per connection, max256 per entire suite.
Identify challenge is os.urandom(32).hex; requester process boot is independently generated once per
service construction using an allowed BrokerID, never owner input. Six connection IDs and the two
challenges differ; worker boot may legitimately differ from HISTORICAL Task43 evidence, but not
within this run. Two identify replies must equal journal-derived identity and echoed challenge.
For ALL six connections require same actual peer PID/UID/GID, responder boot, generation ID and
listener unsigned-content hash. Expected UID/GID come from the provider expected identity. There is
no separate peer_role field: call `extension_channel(instance_id=subject.instance_id,
slot_number=subject.slot_id)`, require its fixed `spec.responder_service == subject.service_identity`,
and pass that exact root/spec to `_connect_extension_authenticated`. The broker handshake binds the
code-owned requester/responder roles and services from ChannelSpec; no caller/geometry role DTO is
accepted or persisted.
Never claim readiness inode continuity or reconstruct an old historical listener preimage.
Each connection recheck occurs after connection, before/after each protocol phase and before close;
source/pending guard before each connection and each application phase, and before final commit.

Run deadline Deadline.after_ms(60000), never extended; each transform bounded(min(30000,remaining)),
identify bounded1000ms. Compute remaining_ms=floor(Deadline.remaining()*1000); refuse0, do not invent
remaining_ms() API. No writer held across IPC; writer wait counts against whole deadline. Wire≤12MiB
per transform and≤48MiB total including identifies, counting each authenticated payload once in both
directions (stream base64 overhead included, decoded bodies not counted twice). Each body≤1MiB,
stream chunk≤16384B, application control≤8192B, all retained canonical transcript≤1048576B,
report domain body≤65536B, at most256 frames total. Retention cap intentionally may stop before
worker protocol maxima: `observation_limit`, never silently truncate into a match. Fixed suite uses
far less; no claim all worker-size limits were positively exercised. One owned connection at once;
memory sinks only, no scratchfile; task-owned open FD delta≤256 and returns to baseline after every
terminal/failure checkpoint. Borrowed source/context/domain ownership is never closed by B.

The already-new `tests/provider_conformance_fixture.py` owns the test composition. Its context manager
is `staged_conformance_app(tmp_path, monkeypatch, *, portable=False, slot_id=1)` and composes the
accepted `provider_receipt_context`, exact prepare/read/sign/install/import/two-connection-stage/
consume flow, then exposes the already-proposed fixture fields. Accepted43 fresh-success consume
performs exactly one real bounded reconciliation before return; exact replay performs no additional
reconciliation, and neither is counted among B's later six connections. A private test-only
`_provider_conformance_worker(actual, monkeypatch, *, serve_count=6)` in that SAME new file owns one
real worker service/thread and six successful `serve_one` calls, providing the connection counter;
it is not a production injection and adds no modified path. Parameterize `portable=False/True` for
the actual local non-root / portable root OriginProfiles; there is no `origin_mode` abstraction.

The same NEW fixture module defines one exact context-manager transition
`restart_without_provider(subject, monkeypatch)`, test-only. The initial subject privately retains
the actual accepted fixture's data path, application arguments and original client/application,
plus its owned B-worker cleanup stack. No new production restart/injection API or accepted fixture
edit is added. This transition saves a detached copy of owner cookies and the completion count;
stops/closes the B worker and joins its thread under the bounded cleanup contract; then exits the
original TestClient/application BEFORE a second create_app, releasing ServingLock. The original
application's startup owner closes its borrowed sources; the helper does not separately double-close
them. Repeated fixture teardown must not repeat owned-close attempts.

Copy application arguments and separately copy `first_party_startup_values`; remove ONLY
`DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256` from that copied values dict. Preserve the original
arguments, data path, deployment/session configuration and all other source pins. Open
`create_app(same_data, **copied_arguments)`, enter a new TestClient at the same profile.http_origin,
and restore the saved cookies. Yield a fresh subject with the SAME declared public fixture fields,
but the new domain/service/prepare/client from actual composed exports. Assert new domain is not
old domain, the `deployment-provider.source-context` export is None, and no worker remains.
The helper closes the new client/application once on exit, including failed setup. It does not
re-bootstrap/re-stage/reconcile B/run a new vector suite or synthesize history.

Under that reopened subject, GET/HEAD and exact POST replay must reproduce retained byte/status
semantics, without increased worker completions. Make B-specific live-source/client, wall/monotonic
clock and RNG entry points fail if invoked by those paths. Do not disable the existing owner's
session-authentication clock; replay-before-clock refers to B's execution clock, not auth expiry.
Also test a distinct fresh command fails unavailable/503 with no new intent. All this remains in
the already-new fixture/API tests and uses real startup/source-absence behavior, not fake responses.

Raw capture codec is CLOSED:

    {schema_version:"provider-conformance-observations-v1",context_sha256:H,suite_sha256:H,
     started_ms:Time,finished_ms:Time,elapsed_ms:N,
     attempts:[{role:"identify-before"|vector_id|"identify-after",
       connection:null|{connection_id:H,requester_boot_id:BrokerID,responder_boot_id:BrokerID,
         generation_id:H,listener_sha256:H,peer_pid:1..2^31-1,peer_uid:0..2^32-1,peer_gid:0..2^32-1},
       frames:[{direction:"sent"|"received",message_id:U,correlation_id:null|U,
         message_type:"extension-request-v1"|"extension-result-v1"|"extension-artifact-v1",
         payload_chunks:[base64]}],
       failure:null|FailureCode}]}

Attempts are prefix of the exact6 roles, length1..6; connection=null only on failed open and no
frames. Base64 is canonical padded encoding of consecutive raw chunks≤24576B, encoded≤32768chars;
all but last chunk full-size, one empty string for empty payload; no empty chunk array. Frames are
successful authenticated reads / completed writes only; an interrupted write is NOT asserted sent.
An incoming authenticated but wrong-protocol frame is retained before parsing when within caps.
At cap retain only complete prefix, fail observation_limit; no passing unrecorded suffix. FailureCode
= connection_unavailable|identity_mismatch|source_changed|protocol_error|deadline|observation_limit|
interrupted|owner_revoked|storage_unavailable. Never persist freeform exceptions, paths, HMAC keys,
session/CSRF secrets, full readiness signatures or native/caller pass assertions.

Replay decoding verifies the finite transcript's control flow and stream descriptor/hash/correlation
semantics using the existing stream codec with a new PRIVATE in-memory transcript transport; it has
no live constructor/authority or network. Random outgoing IDs come from the retained frames, not
fresh RNG. It reconstructs actual projection/result bytes and compares them to the literal oracle.
This authenticates nothing independently: capture provenance comes from core command/history and
live authenticated client at production time. C must trust that producer plus its own current trust
chain; stored payloads cannot re-prove kernel credentials/HMAC after the fact. Failure prefixes are
checked up to their recorded stopping boundary and can never cover an unobserved vector.

## 6. Immutable records, bounded tables and history

Intent content (body≤8192B) exactly:

    {schema_version:"provider-conformance-intent-v1",command_id:U,request_sha256:H,
     installation_ref,subject:SubjectProjection,context_sha256:H,
     suite_version:"private-provider-conformance-v1",suite_sha256:H,
     requester_version:"private-provider-requester-v1",comparator_version:"private-provider-literal-oracle-v1",
     admitted_ms:Time,deadline_ms:Time}

Header kind=provider_conformance_run,id=command_id,version1,actor_ref=actual authenticated owner
actor record, parents EXACT [installation_ref], current root policies, purpose operational,
created_at=admitted_ms; deadline_ms=admitted_ms+60000 within Time bound. Subject duplicates actual
candidate/request/receipt refs; exact outgoing graph edges (deduplicated header/content refs) are
actor/access/retention/installation/candidate/request/receipt, ≤7; no direct blobs. Before load enforce
row/body/edge/blob caps, then verify exact equality, not only counts. Current stage resolver creates
intent; pure envelope constructor alone grants no permission.

Terminal report content exactly:

    {schema_version:"provider-conformance-report-v1",command_id:U,intent_ref:EntityRef(newkind,1),
     installation_ref,context_sha256:H,suite_sha256:H,finished_ms:Time,
     elapsed_ms:null|N,observations_blob_ref:null|BlobRef,
     completion:"matched"|"mismatch"|"incomplete",reason:"compared"|FailureCode,
     vectors:[{vector_id:fixedID,comparison:"matched"|"mismatch"|"not_observed"}],
     covered_subchecks:[fixedID],recovery_command_id:null|U}

Observed elapsed is the actual nonnegative monotonic difference in milliseconds, never clamped to
make a timeout fit. Matched alone requires elapsed<=60000 and final commit wall time<deadline.
Capture started_ms=intent.admitted_ms, capture finished_ms>=started_ms, report finished_ms>=capture
finished_ms; post-deadline/scheduling overrun can only be incomplete. No renewed measurement budget.
Header same ID/version2; parents EXACT [intent_ref,installation_ref]; actual finalizing actor,
root policies unchanged. Vectors always four ordered IDs. `covered_subchecks` is exactly ordered
IDs whose independently reconstructed comparison is matched, NOT all compatibility. Matched requires
both valid identifies, all six samples continuous and four matched vectors, reason=compared;
mismatch requires an observed independent comparison failure, reason=compared or identity_mismatch;
incomplete covers missing capture/guards/budget, never claiming unrecorded match. Stop after first
mismatch or ordinary failure; later vectors not_observed. Live report elapsed_ms and blob nonnull;
recovered report reason=interrupted, elapsed/blob=null, all not_observed, covered=[], recovery command
nonnull. No fabricated zero-duration/zero-IPC evidence. Header created_at=finished_ms. Same7? Actual
report edges are actor/access/retention/intent/installation (≤5), direct blobs0..1. Reject every
extra/missing edge/blob/version3 or half report, including an orphan domain record not indexed below.
Rehydration recomputes vector comparisons from raw bytes; a captured matching prefix can be retained
inside an incomplete report. Core-owned final guard failures may downgrade, never upgrade, raw
comparison completion. Future C refuses incomplete/mismatch for positive coverage admission even
if some individual vector IDs matched. It does not turn asserted failure causes into positive proof.

Storage is a NEW bounded family in the same database; **no deployment v6 or C5 edit**. Freeze exact
column order/types/constraints below; implementation emits literal CREATE statements and checks its
own sqlite_master/layout/foreign_key_list before any row materialization. No CREATE IF NOT EXISTS
acceptance of a partial/alien family. Checksum=SHA256(canonical_json(ordered CREATE statement strings));
independently recompute during full preflight. These are required exact bytes, not a claim that migration has been executed. Three tables plus one explicit index:

```sql
CREATE TABLE provider_conformance_migrations (
 version INTEGER PRIMARY KEY CHECK(version=1),
 checksum TEXT NOT NULL CHECK(length(checksum)=64)
);

CREATE TABLE provider_conformance_control (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id),
 instance_id TEXT NOT NULL CHECK(length(instance_id)=32),
 origin_digest TEXT NOT NULL CHECK(length(origin_digest)=64),
 run_count INTEGER NOT NULL CHECK(run_count BETWEEN 0 AND 64),
 retained_bytes INTEGER NOT NULL CHECK(retained_bytes BETWEEN 0 AND 67108864),
 last_now_ms INTEGER NOT NULL CHECK(last_now_ms BETWEEN 0 AND 253402300799999)
);

CREATE TABLE provider_conformance_runs (
 command_id TEXT PRIMARY KEY CHECK(length(command_id)=36),
 vault_id TEXT NOT NULL REFERENCES provider_conformance_control(vault_id),
 request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
 installation_kind TEXT NOT NULL CHECK(installation_kind='extension_installation'),
 installation_id TEXT NOT NULL CHECK(length(installation_id)=36),
 installation_version INTEGER NOT NULL CHECK(installation_version=1),
 installation_sha256 TEXT NOT NULL CHECK(length(installation_sha256)=64),
 run_kind TEXT NOT NULL CHECK(run_kind='provider_conformance_run'),
 intent_version INTEGER NOT NULL CHECK(intent_version=1),
 intent_sha256 TEXT NOT NULL CHECK(length(intent_sha256)=64),
 report_version INTEGER CHECK(report_version=2),
 report_sha256 TEXT CHECK(length(report_sha256)=64),
 state TEXT NOT NULL CHECK(state IN ('pending','matched','mismatch','incomplete')),
 admitted_ms INTEGER NOT NULL CHECK(admitted_ms BETWEEN 0 AND 253402300739999),
 deadline_ms INTEGER NOT NULL CHECK(deadline_ms=admitted_ms+60000),
 finished_ms INTEGER CHECK(finished_ms BETWEEN admitted_ms AND 253402300799999),
 started_sequence INTEGER NOT NULL CHECK(started_sequence>0),
 finished_sequence INTEGER CHECK(finished_sequence>started_sequence),
 pending_reply BLOB NOT NULL CHECK(length(pending_reply) BETWEEN 1 AND 8192),
 terminal_reply BLOB CHECK(length(terminal_reply) BETWEEN 1 AND 8192),
 retained_bytes INTEGER NOT NULL CHECK(retained_bytes BETWEEN 0 AND 1048576),
 FOREIGN KEY(vault_id,installation_kind,installation_id,installation_version,installation_sha256)
 REFERENCES domain_records(vault_id,kind,id,version,sha256),
 FOREIGN KEY(vault_id,run_kind,command_id,intent_version,intent_sha256)
 REFERENCES domain_records(vault_id,kind,id,version,sha256),
 FOREIGN KEY(vault_id,run_kind,command_id,report_version,report_sha256)
 REFERENCES domain_records(vault_id,kind,id,version,sha256),
 FOREIGN KEY(vault_id,started_sequence) REFERENCES api_event_envelopes(vault_id,sequence),
 FOREIGN KEY(vault_id,finished_sequence) REFERENCES api_event_envelopes(vault_id,sequence),
 CHECK((state='pending' AND report_version IS NULL AND report_sha256 IS NULL
 AND finished_ms IS NULL AND finished_sequence IS NULL AND terminal_reply IS NULL AND retained_bytes=0)
 OR (state!='pending' AND report_version IS NOT NULL AND report_sha256 IS NOT NULL
 AND finished_ms IS NOT NULL AND finished_sequence IS NOT NULL AND terminal_reply IS NOT NULL))
);

CREATE UNIQUE INDEX provider_conformance_one_pending
 ON provider_conformance_runs(vault_id,installation_id) WHERE state='pending';
```

Each CREATE through semicolon is one ordered string, preserve internal whitespace and exclude
separating blank lines. Four-string canonical list is3306B, CHECKSUM_V1=
`c8557c5bd0ce04379531434e7edba156662011f6a12321a9e28ded8f646d40f5`.
The explicit index is only concurrent-run exclusion, not slot/installation authority. Migration row
is exactly1/checksum; loader enforces exact SQL storage classes and canonical UUID/hash/range values
before parsing bounded bytes, since SQLite affinity/CHECK alone is insufficient. No SQL was run here.

Same-store writer creates complete family and owner-bound control atomically only when all absent;
it must first verify existing domain/event/owner and accepted43 histories. No initialization of domain,
owner or deployment state by B. Partial schema, malformed rows/checksum/layout, unknown version,
trigger/extra index/unexpected inbound FK to owned family or orphan new-kind records is unavailable,
never repaired/rebuilt. Max64 lifetime intents and64MiB attached transcript bytes; no deletion,
retirement/recycling/retention override. Count/sum recomputed from records, not trusted counters.
No table of observations separate from actual CAS; presealed unreferenced blobs are ordinary CAS
orphans after failed commit, not accepted evidence. Legacy C1–C5 rows, rowids, schema hashes, bytes,
typed NULLs, event sequences/cursors and all old frozen replies are preserved.

History verifier first performs bounded scalar queries (at most65 run rows,129 new-kind records,
129 new event rows to detect overflow), all local byte/edge/blob caps and exact storage classes;
only then materializes rows/CAS. Control starts run_count=retained_bytes=last_now_ms=0, no wall clock
at source-less initialization. Its actual origin digest must equal accepted deployment/owner binding,
not a freshly caller-supplied profile dictionary. Retained bytes=sum per-run attached transcript sizes
(conservative even if CAS deduplicates), not report-body bytes. History verifier rechecks all≤64
intents/results and their actual graph/CAS bytes, exact input SHA,
time/state/owner/policy/subject joins, unique corresponding events and frozen reply reconstruction.
Historical subject verifies retained candidate/source/request/receipt/installation bytes using
accepted43's historical journal checks; it does NOT demand current live source or old worker boot.
Complete graph≤4096nodes/depth256/64MiB as actual DomainStore, plus new tighter local caps. Reject
extra new-kind records, extra new event objects, refreshed hashes with altered vectors/source,
cross-vault blob/ref substitution, result without intent or duplicate completion. Read-only rehydrator
derives actual domain/owner/profile from its real bound prepare service, requires its active same-store
writer via _assert_write_transaction plus exact version2 ref; verifies FULL family, exact index,
events and bytes and recomputes all comparisons. `domain.get(ref)` or a caller-created dataclass is
insufficient. Rehydrate mismatch/incomplete too, preserving limitations; no current-authority boolean.

## 7. Command, time, crash and replay semantics

Constructor owns no source/connection/thread; borrows the exact startup provider source context and
prepare service,
installs/verifies additive family under actual writer, never probes/retires pending runs at startup.
Execute parses/authenticates first; writer reauth uses existing persistent owner/session/CSRF/
Host/Origin rules and actual account actor ref. Full family + accepted43 history verification and
exact replay precede fresh wall clock/source/RNG/IPC. Terminal replay returns frozen terminal bytes;
pending replay returns frozen pending bytes, never waits/runs/recovers. GET/HEAD are owner-authenticated
read operations and neither clock nor reconcile nor probe. Return copies, not mutable stored state.

Fresh command: resolve current staged subject and actual18 bytes, sample wall time and compare durable
floor, reserve intent+started event+pending reply+counter under one writer. First sample uses actual
time.time_ns()//1000000, strict range/overflow. A regression below last_now_ms refuses unavailable;
update floor only with committed writes. Start monotonic deadline before admission work; actual
wall deadline is admitted_ms+60000; every further sample must be>=durable floor and<deadline for
positive match. Close deadline race in final writer. Never backdate an observation or extend budget.

IPC runs outside writer. Guard briefly reacquires actual writer, reauthenticates live owner, verifies
pending identity/current stage/source and wall+monotonic deadlines. No user-supplied callbacks.
After capture, independently compare; preseal bounded raw bytes through DomainStore.put_blob outside
writer. Final writer reauthenticates, repeats full history/current head/source/context joins and
compares pending intent; atomically adds report2, terminal event, indexed state/reply and counters.
Positive match requires all current joins. Head/source/deadline drift converts an otherwise matching
capture to incomplete with source_changed/deadline, still retaining historical observations when
owner/store authority remains valid. It never rewrites the subject to match the new head/source.
All full history revalidation occurs before commit; no partial installation/qualification changes.
Mismatch is evidence, not HTTP transport failure. Ordinary protocol/source/time failure retains an
incomplete report if final owner/store admission is still possible; revoked owner/corrupt store/floor
regression may leave pending instead of writing with nonexistent authority. No unsafe error masks it.

Crash/interruption: propagate SAME primary BaseException after attempting every task-owned close;
do not run a DB finalizer on that primary path. Intent may remain pending; no assertion that IPC
did not occur. Exact command replay never repeats it. A DISTINCT fresh owner command for SAME
installation may, once actual now>=old deadline_ms, retire that one expired pending run as
interrupted under a first writer (using current owner actor, recovery_command_id=new command_id),
commit old report/event/reply, then seek its own admission under a second writer. Old terminal is
unchanged thereafter. Recovery is authorized by the explicit new attempt; no timer/background/GET
write. A live resumed old task fails its pending/deadline guard and cannot overwrite recovery.
Recovery requires historical verification and owner but not a live worker/source; new admission
separately requires current stage/source. If new admission then fails (capacity/source/currentness),
return its honest error while old interruption stays committed. No new intent exists for that ID;
its ID is a recorded recovery cause, not a promised admitted run. Once successfully used as a
recovery cause, reuse with another installation/input conflicts (verify across≤64 reports).
The recovery cause input digest reconstructs exactly from recovery_command_id and that interrupted
intent's installation_ref; cause actor is the recovery report's actual actor. Check both on reuse,
including when the new run never admitted. Do not create an unused recovery command table.
Before expiry new command conflicts; same ID always replays. Capacity64 is intentional lifetime cap;
recovery remains possible at capacity, but new admission fails429 after recovery. No auto-reexecution.

Bounded connection cleanup consumes accepted42 lifetime guarantees: own the returned connection
immediately, cleanup all sinks/connection on every path, preserve active primary over close failures;
without primary propagate first cleanup failure after attempting all. No broker/slot/root fixes are
reopened here. No promise of arbitrary interpreter/kernel-kill atomic cleanup. Deterministic tests
cover acquisition return, frame/control/stream phases, source guards, preseal/final writer and close.
The accepted43 baseline's separate shared-transaction cleanup masking seam is corrected by accepted
Task44 (recorded in `../resumption-plan.md`). This34-path task consumes, but does not modify, that finite prerequisite.
Its same-primary tests exercise B-owned connection/sink/guard cleanup; Task44 separately tests the
three reached shared-store cleanup surfaces. Neither establishes every Store owner or arbitrary
termination/VFS atomicity, physical release after a refused close, or safe ambiguous-commit replay.
Ordinary same-store rollback/commit atomicity, process interruption leaving a recoverable intent,
and B's own primary preservation remain required, not deferred under a broad cleanup exception.
Actual Task44 is ACCEPTED in `../resumption-plan.md`; it owns exactly three surfaces:
DomainStore connection unwind, domain path-directory acquisition/unwind, and verified Store borrowed-
handle duplication/unwind, with its new lifecycle test. Its prerequisite/preflight docs above define
that work. B consumes its exact accepted result without adding those paths to this34-path candidate
or gaining ownership there. Accepted44 exact source/report reconciliation is retained in the
implementation evidence and canonical progress; it does not change this protocol.
No HMAC/native/socket fallback on unsupported platform or missing peer credentials/mount support:
actual accepted connector refusal becomes connection_unavailable/incomplete, never a fake match.

## 8. Events, routes, exports and future consumer

Add exactly two exact-required event payloads:

- provider.conformance_started `{vector_count:4}`; status started, object_refs=[ObjectRef(intent_ref)], private
  evidence empty, correlation_id=command_id, causation_id=null, actor human/current owner.
- provider.conformance_completed `{completed_count:0..4,matched_count:0..4,
  outcome:"matched"|"mismatch"|"incomplete"}`; completed_count counts compared vectors (not_observed
  excluded), matched_count<=completed_count; status succeeded for matched, failed for mismatch,
  unknown for incomplete; object_refs=[ObjectRef(report_ref)], private_evidence_refs=[report_ref]; correlation
  command_id, causation started event ID; actual finalizing actor. error_code=null (details closed in
  retained report); observed_at/recorded_at actual final wall value; policy actual access root and
  retention_class=core. ObjectRef(ref) means existing ObjectRef(ref.kind,ref.id,ref.version,ref.sha256),
  with content_hash, never an EntityRef dictionary passed to the ObjectRef parser. Event timestamps
  use public_events' existing UTC timestamp grammar, with equivalent exact wall time.

Use actual _append_event_in_transaction / _event_cursor_in_transaction. Event indexing/public
metadata is not provenance alone. Never emit extension.verified/qualified/enabled, catalog/model
selection or validation.completed. Old event schemas/optional-key semantics are unchanged.

PATH `/api/v1/extensions/provider-conformance`. Contribution ID provider-conformance-v1.json,
factory `app.api.provider_conformance:create_router`; required_auth=[browser_session], POST scope
extension.manage, GET|HEAD scope extension.read. Route IDs `extensions.provider-conformance.execute`
and `extensions.provider-conformance.read`. Requires exact exports deployment-prepare.service and
deployment-provider.source-context; provides only provider-conformance.service. Absent context does
not prevent historical reads/replay; fresh attempt503. Same startup owner closes context once.
No new startup key/service admission, frontend, route discovery or general extension registration.

create_router(*,service,base_path), conformance_services(context,*,dependencies),
preflight(scope,body,content_type), conformance_error(error) follow actual candidate route seams.
POST runs service.execute in threadpool; reply200 terminal or202 pending, exact replay same status.
GET200 current pending/terminal; HEAD200 empty with same representation headers. Empty query, exact
UUID path, POST application/json4096B/depth4/items32/members8/string256; GET/HEAD zero body. New
web boundary state key provider_conformance_payload. Keep raw path/base path/Host/Origin/CSRF/session
and route auth before service. Error codes map invalid_input400,unauthenticated401,access_denied403,
not_found404,conflict409,too_large413,capacity429,unavailable503; exact candidate-shaped five fields,
message constant `Provider conformance request could not be admitted`, retryability=not_retryable,
affected_refs=[],correlation_id=freshU. No stack/path/raw observations in responses.

Reply≤8192B exactly `{schema_version:"provider-conformance-reply-v1",command_id:U,installation_ref,
intent_ref,result_ref:null|EntityRef(newkind,2),state:"pending"|"matched"|"mismatch"|"incomplete",
suite_version:"private-provider-conformance-v1",suite_sha256:H,context_sha256:H,
completed_count:0..4,matched_count:0..4,event_cursor:string,links:{self,events}}`.
Pending result=null/counts0/cursor=start; terminal result nonnull/counts recomputed/cursor=completion.
The pending and terminal replies are separate immutable snapshots: never overwrite pending_reply.
Replay chooses the terminal snapshot once it exists, otherwise pending. Verify frozen cursor's
actual stream/vault/filter/sequence/event relation while permitting the existing historical cursor
generation semantics; do not reconstruct/replace it with today's generation. Cursor filter is the
ordered pair provider.conformance_started,provider.conformance_completed as canonically sorted by
the existing helper, not an arbitrary caller filter.
Unprefixed self=PATH+"/"+command_id,events=/api/v1/events. Store frozen unprefixed canonical bytes;
HTTP validates closed reply then prefixes actual base path only. No raw transcript/candidate/source
document exposure; core C calls rehydrator directly in its own same-store transaction.
Three new schema URNs `urn:deeptwin:schemas:v2:extensions:{filename-stem}`; Draft2020-12, closed,
fresh detached, sorted UTF8/two spaces/final LF. Runtime and schema parity for every discriminator;
new record export includes exact envelope version1/version2 variants, not just content.

Future C MUST verify rehydrated producer/history/context/raw comparisons, freshness under C's own
qualification intent/suite policy, exact verified-installation ancestry and current source/runtime/
platform/schema/purpose/grants. B has no evidence expiry policy that can stand in for C's maximum
seven-day qualification expiry. Historical evidence remains readable after source change/restart;
it is not reusable as fresh qualification without all C joins. Installation, runtime/schema/suite,
native enrollment/trust/policy or target-context change requires C's invalidation/requalification.
No qualification signer delegation derives from receipt keys, HMAC peer or authenticated owner.

## 9. Acceptance / preflight gates

| Gate | Required proof before candidate is READY |
| --- | --- |
| Actual43 boundary | Accepted R1 manifest and exact resolver/history/fixture mapping reconciled at mapping SHA `9643c039880ca6fbd3a27f927bb1e544fcda08366fdb2da23181924da49feaad`; any later hash change reopens only affected rows. This satisfies the dependency gate, not B promotion. |
| Type/export parity | New kind admitted only with closed operational profiles; wrong kind/purpose/version/parents fail; old records/replay unchanged; exact two aggregate file deltas, other exports stable. |
| Exact storage | Literal3-table/index DDL/textual checksum above, FK/layout/type checks; independent review before promotion. No SQL execution claimed. |
| Literal vectors | Independent expected plan/projection/SSE/catalog/result bytes; negative refusal/capability cases count only expected private semantics. |
| Actual vertical | Real source18 + actual43 staging + actual worker framed streams + same DomainStore records/events + authenticated route + reopen/rehydrate, not pass-map/mocked success. |
| Lifecycle | Pending/replay/recovery two-writer semantics, wall-floor/deadline races, owned FD closure/primary preservation and lost finalization deterministic tests. |
| Shared store lifetime | Accepted Task44 exact source/report reconciliation closes this dependency only; no scope expansion or whole-store claim. |
| C consumer meaning | Real rehydrator recomputes historical subset; native trust/runtime/mount/release/permission/full semantic coverage remains explicitly unbuilt and cannot be bypassed. |

Tests must cover wrong field/type/bool/int/null/extra/duplicate/canonical/size/depth; mixed tool/provider
heads; all projection/result/correlation/stream ordering and duplicate ID attacks; six-connection
boot/peer/listener drift; raw blob/index/edge/event/counter forgery; unauthorized actor/vault; replay
with clock/RNG/source/client made to fail; raced requests, expired pending recovery and fresh command
failure after committed recovery; every intent/report/event/index write rollback; close failure
under ordinary/KeyboardInterrupt/SystemExit primary; actual unsupported-platform refusal.
Positive fixture labels synthetic worker image/mount/receipt observations, never native packaging,
all-five-check qualification or end-to-end paid provider use. Seven journeys advance provider setup/
verification infrastructure and eventual model choice/run, not a claim any complete journey now works.

## 10. Implementation-era fixture amendment — dependency preflight versus cleanup

2026-09-20. A focused legacy test observed1failed/4passed after the required new contribution
declared both deployment exports as dependencies. The old `composition` fault removed the provider
source declaration, so the unchanged catalog now correctly rejects before any factory executes.
It no longer reaches the source-owner cleanup checkpoint that the old test intends to exercise.

Allow only this additional test delta in the already-owned `test_provider_source_startup.py`:

- Preserve all four original parametrized cases and their source-count/read-after-close/no-live-FD
  assertions. For `composition`, retain every real deployment `provides` entry and append the unique
  valid test-only name `deployment-test.missing-export`. The unchanged catalog then admits the
  dependency graph; the real factory opens its source, the owner adopts it, and exact export-set
  checking fails because the test-only declared export is absent. Require exactly one source,
  its read-after-close refusal, and no live owned handles as before.
- Add one `dependency` case retaining the previous mutation
  `provides=("deployment-prepare.service",)`. Require `RouteCompositionError`, zero provider-source
  acquisitions and no live owned handles. Do not index a nonexistent source in this early-refusal
  case. This separately proves the new dependency fails before factory work.
- No production catalog timing, dependency, source ownership or cleanup behavior changes; no skips,
  xfails, exception suppression or reduced assertions for the four original cases. No other test
  adaptation is authorized. The other old test still allows its route-count change only.

The34-path ownership and72-module final cover remain unchanged. Run the five-case function plus
the changed first-party count case as the focused cover; retain the original failure chronology.
The final independent task review must inspect this fixture amendment and unchanged production
dependency/owner checks. This is not permission to repair an implementation by weakening tests.
