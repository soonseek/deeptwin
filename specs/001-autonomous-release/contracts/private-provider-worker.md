# Private provider worker: text and catalog transformations

Controller design decisions recorded 2026-09-19. Independent plan review remains required before
implementation dispatch. This contract supersedes the advisory worker/dialogue drafts only for
this bounded worker tranche; it is not provider execution or deployment authorization.
Sources: current worker/listener/stream code; `specs/001-autonomous-release/evidence/claude-provider-protocol-check-2026-09-19.md`.

## 1. Outcome and non-authority boundary

Deliver an actual fixed-entrypoint no-network worker that authenticates the control peer, measures
its own provider-profile files, transforms bounded text into a Claude request body, consumes supplied
Claude SSE/catalog bytes, and returns bounded normalized observations through real framed streams.
The controlled client supplies upstream bytes; this worker NEVER obtains them from a provider.
No UI/status milestone, runtime route registration, canonical admission record, gateway protocol,
credential change, v4 staging, provider connection/catalog authority or WorkModel is created.
Production create_app/gateway admission remains unchanged/denied. No fixture transport in composition.

Call this private mode `claude-text-transform-v1`, not an admitted `provider-port-v1` execution.
The transformation result is inert data parsed from supplied bytes, not proof the provider was called,
charged, chose a model, supplied a current account catalog or completed work. Its DTO has no pass flag,
qualification/binding ref, fake environment/node/run consent, worker-issued ArtifactRef or admission_ref.
Future core maps an actually admitted canonical F-model projection to this DTO and seals outputs only
under the existing capture/ledger contract. The DTO cannot replace that projection or authorize input.
Text/no-tools/no-workspace/no-explicit-effort/30s are initial limits, not removals from product scope.

## 2. Smallest ownership set and concrete interfaces

Production ownership for the bounded implementation:

- `app/adapters/claude_protocol.py`: pure `decode_json`, incremental `SSEDecoder.feed/finish`,
  safe-ID/integer validators and small normalized value types; stdlib only, no I/O/callback authority.
- `app/workers/provider_transform.py`: pure `prepare_text(plan, input_bytes) -> bytes`,
  `parse_text_response(requested_model, chunks) -> TextObservation`,
  `CatalogAccumulator.accept_page(raw) -> next_cursor|None` and `finish() -> CatalogObservation`.
- `app/workers/provider_messages.py`: strict metadata/value codecs, fixed bounds and streamed
  context/result schemas below. Parsers return inert values; no source/authority constructors.
- `app/workers/provider_service.py`: `open_provider_worker_service(*,instance_id,slot_number)`;
  nonconstructible owned service `serve_one(deadline)/close/closed`, serial connections, fixed router.
- `app/workers/provider_worker.py`: `main(argv=None)` fixed entrypoint; no network/client callback flags.
- `app/extensions/provider_identity.py` and `provider_identity_schema_exports.py`: new provider-only
  BuildIdentity v2 parser/export; `schemas/v2/extensions/provider-build-identity-v2.schema.json`.
- `app/workers/provider_metadata.py`: no-argument `open_provider_metadata_source()` with
  `read_current(deadline)/close/closed`; real fixed-file measurements, never installation authority.

Narrow shared edits: `adapters/claude_api.py` delegates small pure helpers to claude_protocol while
keeping its existing transport/state semantics; `workers/extension_metadata.py` may delegate low-level
fixed-image measurement to NEW `workers/_fixed_image_metadata.py` as detailed below. Do not alter
old v1 schemas/exports/port tables or listener/broker behavior for convenience. No runtime imports.
No production control-side client is required for this tranche: a test-owned scripted requester uses
the real broker connection API. A later control adapter needs a separate reviewed admission scope.
Existing service/stream integration references are extension_probe.py, artifact_stream.py and
artifact_stream_transport.py; there is no extension_service.py or streams.py to create or replace.

Tests: new `test_provider_{identity,metadata,messages,transform,service,worker}.py` plus test-owned
framed requester helpers; narrow existing Claude/parser and tool-metadata regression selections.
If pure-helper extraction changes the old parser's outputs/errors, fix the extraction or separately
review the behavior change; this task does not silently repair all legacy adapter semantics.
Controller-reviewed exception (2026-09-19): the old JSON helper rejects NaN/Infinity tokens but
finite-spelled exponents such as 1e999 can overflow Python float to infinity. The shared decoder
must reject such nonfinite decoded values recursively for all consumers, including the old
adapter, while preserving valid finite floats, event/error ordering and exact detail codes.
Add explicit RED/GREEN positive/negative/nested overflow tests and finite-value controls.
Do not add a legacy bypass flag or silently preserve this demonstrated nonfinite loophole.

## 3. Provider metadata must be real, versioned and independently opened

Old `lineage_schema_exports.py:45–71` fixes BuildIdentity v1 to tool-port-v1; old
`extension_metadata.py:130–175,304–377` opens tool paths and calls that parser. It cannot attest provider bytes.
New provider BuildIdentity v2 has the SAME bounded identity fields/input hashes/entrypoint/schema-role
order as v1, except schema_version=`extension-build-identity-v2`, port_contract_version=`provider-port-v1`,
plus worker_profile=`claude-text-transform-v1`. Two platform values remain linux/amd64 and linux/arm64;
identity cap8192B, entrypoint16MiB, each schema262144B, four-schema sum1MiB. Inputs remain declarations.
Define a separate exact ProviderBuildIdentity type and parser; old parse_build_identity remains v1-only.
This slice does NOT introduce provider LineageEvidence, a descriptor join or stage acceptance.
The new identity module also owns validate_provider_schema_bytes(identity, schema_bytes)->None:
require the exact ProviderBuildIdentity class, revalidate its canonical bytes and compare the exact
config/request/result/error tuple's role order, sizes and hashes, using the closed provider error.
Keep the old tool validator exact-type/v1-only. The private measurement profile selects BOTH its
code-owned parser and schema-byte validator, preserving the old tool error/poison distinctions.
The measured four files are the unchanged semantic provider-port-v1 schema bytes already under
schemas/v1/extensions/ports/provider-port-v1/, not newly invented private-dialogue schemas. Their
identity is a byte measurement, not a claim that the private router implements model_step/cancel
or other semantic provider operations. Private codecs belong to the measured executable closure.

Fixed paths under `/opt/deeptwin-extension`: bin/worker, identity/build-identity-v2.json,
ports/provider-port-v1/{config,request,result,error}.schema.json. Root-owned exact0555/0444 leaves,
0755 ancestors, regular/single-link/no symlink or inode aliases; root read-only, no prefix overlays,
nonroot real=effective IDs, actual Linux platform. Rehash executable and all schema files on each
read; compare declared hashes/sizes, actual platform, retained names/FDs/mounts before and after.
Retain existing 13 steady FD/≤32 transient FD,64KiB read chunk,1s acquire/500ms read budgets and
17,833,984B aggregate file cap. Busy/close/lifetime/poison behavior matches existing metadata contract.

Preferred helper extraction: private `_fixed_image_metadata.py` owns shared descriptor traversal,
signature/mount/currentness/cleanup machinery. Only two code-owned internal profiles select fixed
tool-v1/provider-v2 paths and parser functions; public factories take no paths/pins/expected facts.
Keep separate public source/reading types and old tool error/API behavior. Reuse deployment.files/
mounts; do not copy a second600-line observer or expose a general caller-selected measurement factory.
Before extracting, add characterization tests for old FD cleanup, poisoning and byte-identical exports.

Entrypoint packaging must include every executed parser/helper in the measured image/executable
closure; hashing a tiny launcher does not prove imported modules. The chosen future packaging
profile is standard locked CPython in an exact OCI image, not a new freezer dependency. Local
six-file entrypoint/schema observations remain narrow: they do not measure imported modules,
authenticate an OCI image or qualify its execution. The executed-image claim requires qualified
final-filesystem inspection plus an authenticated allowed-image authority, independent exact OCI
platform graph verification and external stage enforcement of fixed isolated Python, read-only
root, closed argv/env/cwd and no import-path overlays. A caller-supplied digest or matching local
identity is not that chain. These requirements belong to later builder/stage/native gates;
this task creates none of their evidence. Existing six-file/FD/deadline limits stay unchanged.
Missing provider image files must prevent listener publication, never fall back to tool metadata.

## 4. Listener, modes, deadline and ownership

Reuse `extension_channel(instance_id,slot_number)` and exact IPC-v2/type tuples unchanged:
control sends extension-request-v1, worker replies extension-result-v1; artifact type is bidirectional
extension-artifact-v1. Frame65536B, in-flight1, queue16, operation30000ms. No changed global broker cap.
Open provider metadata BEFORE bind_worker_listener; fresh boot ID; use actual authenticated accept,
peer identity, populated generation/mount/readiness fences and owning ExtensionConnection.
`listener._accept_extension_authenticated(...,connection_ms=30000)` is reusable; it bounds the passed
Deadline (`listener.py:1381–1431`), not a new independent runtime authorization. Recheck before first
frame and after each phase/reply; own the connection through all stream and final-reply completion.

First schema selects identify OR transform, one mode/connection, no second conversation. Tool
extension-stage-probe-v1 and extension-execute-v1 are refused by this provider service, not reinterpreted.
One nonblocking service lock; malformed peer closes only its connection. Metadata poisoning or
listener identity drift closes service; no restart-with-weaker-checks or spin loop. BaseException cleanup
releases sockets/generation/streams/source, preserving the active exception. Main exit0 requested stop,
1 unavailable/poisoned,2 invalid argv; argv reuses fixed instance-id/slot-number shape only.

Control/test requester starts one Deadline before connect; worker further bounds accepted deadline
by first-message remaining_ms. All phases/pages share it; never restart30s per phase or compare remote
monotonic timestamps. Read parser chunks/events under deadline checks. No hot loops without finite caps.
SIGTERM/SIGINT unwind owned resources like existing extension_worker; tests don't signal user processes.
Responder connections authenticate control through the existing listener handshake; their peer
property is deliberately None. Do not synthesize a peer object or bypass that authentication.
Transform performs fresh read_current after complete validated plan/inputs before first projection,
then after every complete supplied response is validated/parsed before next projection or final.
Unavailable/truncated and semantic-failure finals require that same fresh final read. Bound every
read by the original dialogue deadline and existing 500ms metadata budget. Metadata unavailable/
invalid/poisoned closes the service; read deadline closes this connection without false poisoning.
Connection recheck alone is not image remeasurement. Recheck IPC around each phase and after final
result batch acknowledgement. Identify performs one fresh metadata read and uses the accepted
connection deadline; remaining_ms applies only to transform, whose start actually contains it.

## 5. Exact private wire and stream choices

U=canonical nonnil UUID accepted by broker AND ArtifactDescriptor; H=lowercase hex64.
Metadata canonical ADR008 JSON≤16384B/depth8/items2048/members32/string512, integer≤2^63−1;
closed nested fields, no duplicate/unknown/null except explicitly stated, no floats/bool-as-int.
These metadata rules apply only to provider CONTROL payloads. Plans and body/results use their
separate codecs below; artifact frames retain unchanged stream grammar and broker frame limits.
No inline base64 means no blob embedded in provider control payloads, not removal of artifact
stream internals' base64 chunks. This tranche makes no stronger duplicate/extra-field promise for
unchanged stream messages. Control frames/announced batch IDs must be fresh within the dialogue;
maintain one bounded seen-ID set (at most256) for those IDs. Stream frame IDs retain existing broker
sequence/replay behavior, not a new global UUID-uniqueness guarantee. Dialogue ID remains constant.
D={batch_id:U,size:0..1048576,sha256:H,media_type:application/json|text/plain|text/event-stream}.
A D announces ONE stream object, ordinal0/count1; artifact request_id and every stream correlation
equal its announcing frame ID. Each new hop/phase gets fresh IDs. Stream bytes, not inline base64.
Use existing send_batch/receive_batch, BytesSink/BytesSource and ConnectionStreamTransport,
16384B chunks/credit/end-digest/accept/no resume. Validate whole input before using it.
Canonical model input artifacts (future F-model) are different from these private transport blobs.

Identify request (correlation=null): {schema:"provider-worker-identify-v1",challenge:H}.
Reply correlated to request frame: {schema:"provider-worker-identity-v1",challenge:H,
service_identity:broker-id,build_identity_digest:H,port_schema_set_digest:H,platform:linux/amd64|linux/arm64,
uid:uint32>0,gid:uint32>0,worker_profile:"claude-text-transform-v1",
implemented_transforms:["catalog","text"]}. Build/IDs come from fresh actual metadata/listener,
not request expectations. One reply then close; this is NOT the stage probe/receipt postcondition.

Transform start frame S (correlation=null): {schema:"provider-transform-start-v1",dialogue_id:U,
operation:"text"|"catalog",remaining_ms:1..30000,plan:D}. Reply correlated S:
{schema:"provider-transform-ready-v1",dialogue_id,phase:"plan"}; receive plan batch correlated S.
Plan canonical JSON≤262144B, exact union selected by operation:
text={profile:"claude-text-transform-v1",model_id:SafeId,max_output_tokens:1..8192,
messages:[{role:"system"|"user"|"assistant",input_ordinals:[0..31]}],inputs:[{size:0..1048576,sha256:H}]}.
catalog={profile:"claude-text-transform-v1",limit:1000}. No refs, workspace, effort, headers, URLs,
keys, binding or consent fields. Reject extras rather than claim to have honored them.
Text ≤32 messages/inputs; each message nonempty, inputs used exactly once in overall ordinal order;
optional single system message first, at least one user. UTF8 input total≤1MiB; no normalization.

Worker ready phase="inputs", correlated S. Requester sends frame I correlated S:
{schema:"provider-transform-inputs-v1",dialogue_id,batch_id:U|null}; catalog requires null/no bytes;
text requires fresh batch ID, descriptors derived exactly from plan.inputs, text/plain, order0..N−1,
count=N, request_id=I. Receive batch correlated I. A mismatch ends connection before transformation.

Worker frame P correlated S: {schema:"provider-transform-projection-v1",dialogue_id,step:1..20,
endpoint:"messages"|"models",after_id:SafeId|null,body:D|null} followed by body batch correlated P.
Text exactly messages/step1/after_id=null/bodyJSON; catalog models/body=null, initial cursor=null.
This is a request PROPOSAL, not network I/O or a send request. Worker has no gateway client.

Requester frame Q correlated S: {schema:"provider-transform-response-v1",dialogue_id,step,
status:"supplied"|"unavailable"|"truncated",body:D|null}. Supplied iff body present; text MIME is SSE,
catalog MIME JSON. Stream correlated Q. No field claims HTTP send/credential/usage authority; received
bytes have only authenticated control-peer provenance. Only expected step accepted; no interleaving.
Worker parses complete bounded bytes, then emits next catalog projection or final frame F correlated S:
{schema:"provider-transform-final-v1",dialogue_id,result:D}; result batch correlated F, then close.
No gateway leg, authority placeholder or API invocation is introduced. Errors before complete metadata
close; semantic/unsupported response yields closed final result when remaining time allows.

## 6. Text transformation and safe parser extraction

Text body exact {model,max_tokens,stream:true,messages,system?}; system is ordered concatenation
without inserted separators; ordinary messages are user/assistant with ordered {type:"text",text}
blocks. No tools/built-ins, images, thinking, cache directives, output_config, metadata or fallback.
Use separate strict sorted-compact UTF8 codec for body/result (≤1MiB, depth16/items16384,
individual string≤1MiB, aggregate text bound). Domain canonical_json has a64KiB string cap and MUST
NOT be applied to long-text body/result. Re-encoded escaping overhead exceeding1MiB refuses, not truncates.
Control must eventually independently compare this body with the admitted frozen disclosure.

Shared-helper extraction is small: move duplicate-key/nonfinite JSON handling and bounded SSE token
framing (claude_api.py:331–355,1973–2060) into pure claude_protocol. Adapter wrappers retain their
error mapping/cancel/deadline handling. No import of ClaudeAPIAdapter, Keychain, SDK/httpx, secret
canaries, `_client`, `_issued_catalogs` or `_authorized_message_response` by worker/helper graph.
New transformer implements only the text state machine; don't copy the adapter's≈2100-line class.
Keep legacy tool parsing/catalog authority untouched. Source import-graph tests cover transitive imports.
The extracted decoder must preserve pull/lazy event/error order: a malformed later event in one
chunk cannot suppress an earlier yielded event. Expose bounded line/event steps so the old adapter
retains its before/after-read and between-step cancellation/deadline checks. No clock or arbitrary
cancellation callback belongs inside the pure helper. The new TextResponseAccumulator consumes
bounded decoded events; the service drives it with deadline checks between chunks/parse steps.
parse_text_response may be a pure convenience wrapper only, not a clock-free service loop.
Shared strict JSON retains duplicate/nonfinite rejection AND legacy finite-float acceptance;
integer-only private DTO checks are layered above it. Preserve exact legacy error mapping.
Legacy comment-only groups remain errors through its wrapper; new provider policy may ignore them.
Do not silently change old adapter post-stop ping, second-delta or cache-zero semantics here.
Characterize malformed-later-event ordering, between-event cancellation/deadline, split UTF8/CRLF,
comment-only groups, duplicate fields, finite-float JSON and old error codes before extraction.

Per text reply: ≤1MiB SSE, each event≤262144B, ≤10000 events, ≤32 text blocks/524288B text.
Incremental UTF8/SSE decoder handles split multibyte/CRLF, multiple data lines, comments; rejects
duplicate event fields, malformed JSON, incomplete terminal event and unsupported SSE fields.
Valid ping may occur between phases (including before start/after stop); ignore content-free or
{type:"ping"} pings without resetting counters/deadline. Error event => non-success, never fallback
or retry, no provider error message reflected. Unknown event => typed protocol error (local strict
profile, explicitly narrower than Anthropic forward-compatibility advice).
Require one assistant/message start, requested_model EXACTLY observed model, sequential block
start/delta/stop, one or more message_delta, one message_stop. Successful content is text only.
Model drift/alias/fallback mismatch => model_mismatch, never accept “equivalent” model.
Structurally drain only the closed rejected-block grammar below to reach later observed usage;
this is not full upstream non-text schema validation or permission to execute a tool. Keep one
active block, strictly sequential exact-integer indexes, matching start/delta/stop and no overlap,
delta outside its block, or content after message_delta. All blocks count toward the32block cap.
On rejected start, latch its reason, erase text and retain only kind/index; other start payload
fields are bounded inert JSON and discarded. Validate delta's kind/required exact string field,
then immediately discard rejected string content. Never join/parse tool JSON, consult a tool
catalog, verify thinking signatures or expose rejected content. Unknown/incompatible delta kinds,
missing fields and malformed index/order/envelopes are protocol_error.

| Active block | Flag at start | Permitted delta kind / required string |
| --- | --- | --- |
| text | none unless already latched | text_delta / text; count text bytes even when discarded |
| tool_use, server_tool_use | unsupported | input_json_delta / partial_json |
| thinking | unsupported | thinking_delta / thinking OR signature_delta / signature |
| redacted_thinking | unsupported | none; matching stop only |
| refusal | refusal | none; matching stop only |
| fallback | model_mismatch | none; matching stop only |

Unknown block kinds are protocol_error in this local strict profile. Preserve refusal metadata
flags independently of active block type. Test split rejected tool deltas followed by usage,
thinking/signature drain, zero-delta refusal/fallback, incompatible deltas, wrong indexes, and
later corruption clearing usage_complete. No rejected-block type adds model/tool authority.
Multiple message_delta accepted after blocks finish; repeated nonnull stop_reason must agree.
Only end_turn can be parsed_complete. Refusal stop_reason, any refusal-typed content or nonnull refusal
metadata, or nonnull stop_details => non-success even with end_turn. Treat unrecognized stop_details
as unsupported evidence, not successful completion; don't classify ordinary prose via keyword matching.
Other known stop reasons remain non-success/truncated; unknown reasons protocol error. Missing stop,
unavailable/truncated supplied response or parser failure never yields a successful prefix.

Usage state has FOUR independently nullable counters (input,output,cache_read_input,cache_creation_input).
Initialize null; merge valid nonnegative integers from message_start.message.usage and EVERY cumulative
message_delta.usage; null/absent means no newer observation, not zero or erase. Reject decreases or
bool/negative/overflow. Deltas require numeric output_tokens under the pinned upstream profile.
Latest nonnull cumulative value wins, never SUM deltas. usage_complete exists only when message_stop
and all four counters nonnull; otherwise null. Always preserve partial nullable observations in result,
including refusal/error/drift paths when structurally valid. No api_microunits/model_calls/settlement claim.
Merge each whole usage update atomically after every counter validates; a bad/decreasing member
must leave all prior counters intact. Latch semantic refusal/model mismatch/unsupported content,
discard text and continue bounded structural parsing of already supplied SSE to observe later valid
usage. Structural corruption stops further observation. usage_complete requires the entire supplied
SSE to be structurally valid, message_stop present and all four counters observed; it can accompany
a semantic non-success, but is null after any later protocol error even following message_stop.
A structurally valid provider error terminates without requiring the normal message_stop sequence;
it preserves only earlier validated usage and has usage_complete=null.

## 7. Catalog and exact final observation

Catalog one page≤1MiB, aggregate≤4MiB,20 pages/1000 distinct models; SafeId is local
`[A-Za-z0-9][A-Za-z0-9._:-]{0,199}` (not an upstream guarantee). First/last IDs match entries;
has_more exact boolean; more requires nonempty data/new last_id; reject duplicate models/cursor loops.
Next proposal carries only previous page's validated last_id. No URL/before_id/workspace/header fields;
later gateway derives fixed GET /v1/models?limit=1000 and safely encoded after_id, not worker URL text.
Cap/unsupported ID/malformed/incomplete page yields catalog_incomplete, not a complete prefix.
Require upstream type=model; normalize bounded id/display_name/created_at, nullable max_input_tokens
and max_tokens, and nullable capabilities. Missing nullable fields become null (unknown), never zero
or inferred model-name support. Present token limits must be exact integers 0..2^63−1 or null; this
is a local strict profile, narrower than the upstream numeric type. Capability/effort subobjects
remain raw bounded inert JSON, not typed affirmative support or generation settings. display_name is nonempty UTF8≤512B;
created_at≤64B parses as timezone-bearing ISO8601; id uses SafeId. A result exceeding1MiB is
catalog_incomplete, never a successful partial result. Preserve supported structured metadata as
bounded JSON evidence, not permission. No raw capability fields become typed authorization in this tranche. Preserve the complete bounded
capabilities object without selecting familiar keys; do not synthesize effort values or strip unknown
support evidence. Unknown ordinary ModelInfo fields are ignored only after whole-page bounds/strict
JSON validation; they never create behavior. Any unsupported capability value rejects the page.

Final result exact common fields: {schema:"provider-transform-result-v1",operation:"text"|"catalog",
state:"parsed_complete"|"non_success"|"invalid_response"|"unsupported_profile",
reason:"complete"|"upstream_unavailable"|"truncated"|"refusal"|"model_mismatch"|"provider_error"|
"protocol_error"|"catalog_incomplete"|"unsupported",input_digest:H,observation:{...}}.
input_digest=SHA256(canonical plan bytes), including its exact input descriptors, not a permission claim.
parsed_complete requires reason=complete; every other state requires a non-complete reason. Text observation exact
{requested_model,observed_model:SafeId|null,text_blocks:[string],stop_reason:known_stop_enum|null,
usage_observed:{input_tokens:int|null,output_tokens:int|null,cache_read_input_tokens:int|null,
cache_creation_input_tokens:int|null},usage_complete:the_four_integer_object|null}; no provider IDs/log text.
Non-success text_blocks=[]; preserve raw input evidence only at future control capture, not worker storage.
Catalog observation exact {page_digests:[H],complete:bool,models:[{id,display_name,created_at,
max_input_tokens:int|null,max_tokens:int|null,capabilities:boundedJSON|null}]}; non-success complete=false/models=[] (no selectable partial catalog).
Known stop enum is end_turn/max_tokens/stop_sequence/tool_use/pause_turn/refusal/model_context_window_exceeded.
Bounded capability JSON: object≤65536 encoded bytes, depth8/items2048, strict duplicate-free JSON;
preserve only as inert evidence, never as capability approval. Reject unsupported value types explicitly.
Profile metadata never claims provider invocation or native qualification; parsed_complete means only parsing.
Whole catalog pages are strict duplicate-free finite JSON before field selection: depth≤16,
items≤16384, members per object≤256, UTF8 strings≤65536B and keys≤128B, besides the1MiB page cap.
Capability objects additionally allow only null, boolean, nonnegative exact integer≤2^63−1, UTF8
string≤8192B, arrays and objects; depth≤8/items≤2048/members per object≤128/keys≤128B/encoded≤65536B.
Finite floats remain accepted by the SHARED JSON decoder but are unsupported capability values:
reject the page, never strip/coerce them. Empty terminal pages require first_id=last_id=null and
has_more=false; nonempty pages' IDs must match first/last entries exactly.

Exact final state/reason mapping and precedence:
1. Malformed supplied TEXT bytes/event order/usage/unknown event or stop reason → invalid_response /
   protocol_error, overriding semantic flags. Connection-integrity/order/hash/credit/time faults
   close the connection instead and do not manufacture an ordinary final result.
2. A valid provider error event → non_success/provider_error; unavailable/truncated supplied status
   → non_success/upstream_unavailable or non_success/truncated respectively (no response bytes).
3. Structurally valid semantic flags use refusal before model_mismatch before unsupported before
   truncation: refusal→non_success/refusal; model drift→non_success/model_mismatch; unsupported
   block or nonnull unknown stop_details→unsupported_profile/unsupported; max_tokens or
   model_context_window_exceeded→non_success/truncated. stop_sequence/tool_use/pause_turn are
   unsupported_profile/unsupported in this no-tools initial profile. Valid end_turn without flags
   → parsed_complete/complete. Ordinary prose is never a refusal classifier.
4. Catalog malformed/unsupported/incomplete/cap overflow → invalid_response/catalog_incomplete,
   complete=false/models=[]; a fully validated terminal catalog → parsed_complete/complete.
5. Well-shaped text inputs whose escaped request body exceeds its1MiB cap →
   unsupported_profile/unsupported before any projection. Malformed private plan/control input
   closes the connection. No body truncation, silent normalization or paid retry is introduced.
   If escaped final text-result encoding exceeds1MiB despite decoded text staying under its cap,
   emit the bounded unsupported_profile/unsupported result with text_blocks=[] and otherwise valid
   observations retained; never publish a partial successful result. Test escaping expansion in
   both request and result directions. Catalog result overflow keeps catalog_incomplete as above.

## 8. Failure/replay, acceptance and prerequisite rulings

Whole-dialogue payload budget12MiB; all streamed bytes/control metadata count, no per-page reset.
Its accounting unit is authenticated application frame PAYLOAD bytes in both directions, including
artifact manifests/credit/ack/base64 data once, excluding broker envelope/MAC/length prefix. Do not
also charge decoded blob bytes to this total; their individual/batch/SSE/catalog caps still apply.
A service-local owning-connection wrapper counts writes before forwarding and reads immediately
after bounded receive, delegates to the existing connection and is used by ConnectionStreamTransport.
Exhaustion closes; max_total_bytes on one stream batch is not a whole-dialogue budget.
Cancellation is local connection/stream cancellation only; no remote cancellation success. Timeout,
EOF, bad correlation/order/hash/credit closes; no offset resume/reconnect/automatic resend. Worker
has no durable request ledger; a later runtime MUST resolve unknown send/capture state before retry,
not treat this transform's local idempotence as paid-call retry permission. No output usage settlement.

Acceptance must connect real requester FrameCodec/ExtensionConnection to actual provider service,
send text, receive exact proposed body, supply scripted SSE, receive normalized result; repeat catalog
two-page dialogue and identify mode. Test fixture only supplies peer/source bytes, NOT fake admitted refs.
Use real temporary files/FDs; test-only ownership/mount/Linux sampling seams are labeled simulated;
actual provider metadata factory on unsupported host fails closed. No live provider or Docker proof.
Test byte limits/escaping/string64KiB boundary, split UTF8/SSE, ping/error/unknown events, plural deltas,
nullable counter merge/decrease, refusal under end_turn, model fallback/drift, tool injection, stale
phase/batch/correlation/peer generation, metadata replacement, poison/close/partial acquire/stop,
unavailable/truncated response, cursor loops/caps, zero synthesized cache counters and no auto retries.
Characterize old tool source/probe/execute/schema bytes unchanged and no worker import of secrets/HTTP clients.

Controller rulings: the separate long-text codec and bounded initial profile above are approved
for this private worker, not product-wide limits. Pin refusal fixtures for message_start.message
and message_delta.delta stop_details={type:"refusal",category:"cyber",explanation:"fixture"}, including
end_turn coexistence; retain only the fixed refusal reason, never the explanation. Nonnull unknown
stop_details is unsupported/non-success, never parsed_complete. Also cover stop_reason=refusal and
refusal content block, plus unrelated ordinary text containing "refusal" that is not classified by
keyword. Upstream metadata is strictly decoded and bounded; known nested fields retain their meaning.
Catalog fixtures cover nullable/missing capabilities and limits, nested effort.supported/levels,
unknown bounded capability keys, zero limits, wrong numeric types, and timezone-bearing created_at.
Official references rechecked by controller:
- https://platform.claude.com/docs/en/api/messages/create (refusal stop_details with end_turn)
- https://platform.claude.com/docs/en/api/models/list (ModelInfo nullable capabilities/token limits)
These are minimal synthetic protocol fixtures, not recorded live responses or proof of provider use.
Gateway activation later must separately freeze API-version/auth/workspace policy. No credential
eligibility assertion belongs in this worker: it has no keys, HTTP headers or workspace selection.
Bearer default and supported legacy x-api-key fallback, multi-workspace selection and response
identity must be resolved against actual canonical connection authority before any future send.
Provider BuildIdentity v2/metadata is prerequisite IN this tranche, but image packaging/native inclusion,
lineage-v2 + globally unique physical-slot staging continuation, durable five-check qualification,
canonical connection/catalog/model choice and actual gateway send issuer remain separate milestones.
