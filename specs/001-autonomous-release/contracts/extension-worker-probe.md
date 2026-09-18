# Worker-private stage probe messages

2026-09-18 · ordinary-tool fixed-image profile · observation-only application messages over the
slot's `broker_pair` socket, not admission, installation, qualification or readiness authority.
Authority: extension-worker-metadata.md (the worker's own `WorkerMetadataReading`, §3 FD budget,
§4 observations, §5 fresh reads), extension-lineage-values.md §3/§5 (`BuildIdentity.digest`,
`BuildIdentity.schema_set_digest`, the fixed argv command), extension-candidates.md (SocketMount
`broker_pair`, `deeptwin-extension-worker-v1` protocol identity vs `deeptwin-worker-ipc-v2`
framing), deployment-prepare-sources.md (control identity), ADR-008 (canonical JSON), ADR-010
(isolated transport, T018), ADR-014 (extension lifecycle, T087). This contract normalises the
2026-09-16 probe proposal §1–§5 for Task 25 slices 1b–3; it precedes their code and will be
referenced by the journal-v3 contract (Task 24 step (a)) for the evidence a stage postcondition
records. Independent specification review 2026-09-18: ACCEPT WITH CHANGES, folded in.

## 1. Channel profile (fixed values, slice 1a — committed)

`extension-channel-profile-v1` is an application profile over the existing framing
(`deeptwin-worker-ipc-v2` remains the frame version). Every slot and control identity value is
derived from `app/deployment/contracts.py::slot` and `::CONTROL` by
`app/workers/extension_channel.py::extension_channel(*, instance_id, slot_number) ->
(PairRootSpec, ChannelSpec)`; `parse_worker_argv(argv) -> (instance_id, slot_number)` parses the
fixed image argv; `ExtensionChannelError` is the single closed error. This contract fixes the
profile constants:

| Field | Value |
| --- | --- |
| requester / responder | `control` (uid/gid 20102) / `ext-<I>-<NN>` (uid/gid 22000+N, pair gid 23000+N) |
| channel / direction / protocol | `cp-ext-<I>-<NN>` / `control-to-ext-<I>-<NN>` / `deeptwin-extension-worker-v1` |
| pair root / socket | `/run/deeptwin/ipc/xs<NN>/endpoint` (never the outer root) / `worker.sock` |
| root, socket owner and modes | responder uid + pair gid; `0o2710` / `0o660` |
| requester message types | `extension-artifact-v1`, `extension-request-v1` |
| responder message types | `extension-artifact-v1`, `extension-result-v1` |
| frame / in-flight / queue / operation | 65536 B / 1 / 16 / 30000 ms |

`<I>` is lowercase hex32 (`contracts.identifier`), `<NN>` the two-digit slot 01..16. The
artifact type exists so a later semantic route can stream artifacts on the same channel
(`WorkerRouteBinding` needs a distinct bidirectional artifact type); the probe never sends it.
Decision (T087 execute slice, 2026-09-18): the execute request/reply of §2b rides on the same
`extension-request-v1` / `extension-result-v1` types — the type tuples are part of the
authenticated channel identity and stay unchanged — and the connection mode is selected by the
first frame's exact request schema (§3). Fixed image argv: a
`list` of exactly five `str` — `[executable, --instance-id, <hex32>, --slot-number, <1..16>]`,
no leading zero, no other flag; argv[0] is image packaging and is not compared.

## 2. Closed probe messages (slice 1b)

Payload bytes (pre-envelope) are canonical strict UTF-8 JSON in the ADR-008 canonical form:
request ≤ 1024 B, reply ≤ 4096 B, parsed with the existing `app.domain.wire.parse_json_object`
under `WireLimits(max_bytes=1024|4096, max_depth=4, max_items=128, max_members=16,
max_string_bytes=128, max_integer=2**32-1)` — root depth 1, item counts as the existing wire
walker defines them (total dict members plus list elements); `parse_json_object` closes only the
top level, so the codec closes every nested object; a payload is refused unless
`app.domain.refs.canonical_json(value) == raw`. No duplicate, unknown, null, float or
bool-as-integer values. `H` is lowercase hex64. `Nonce` is 32 random bytes rendered as unpadded
base64url (43 characters); canonical means `urlsafe_b64encode(raw).rstrip(b"=")` equals the field
after decoding (the last character therefore lies in `AEIMQUYcgkosw048`). `BrokerId` is the broker
identifier grammar (`[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*`, ≤ 64). `UInt32` is an integer in
`1..2^32-1` (uid/gid 0 is never a truthful worker value; metadata §4, candidates descriptor).

```text
Request = {schema_version:"extension-stage-probe-v1",
           request_blob_sha256:H, receipt_blob_sha256:H, challenge:Nonce}
Reply   = {schema_version:"extension-stage-probe-result-v1",
           request_blob_sha256:H, receipt_blob_sha256:H, challenge:Nonce,
           service_identity:BrokerId,
           component:{build_identity_digest:H, port_contract_version:"tool-port-v1",
                      port_schema_set_digest:H},
           runtime:{platform:"linux/amd64"|"linux/arm64", uid:UInt32, gid:UInt32,
                    registered_operations:[Op...]}}
Op      = an element of PORT_CONTRACTS["tool-port-v1"].operations
          (codepoint-sorted, unique, may be empty)
```

Every field is required exactly once. `request_blob_sha256`/`receipt_blob_sha256` are the
control side's digests of the retained prepare request and receipt bytes and `challenge` is fresh
per probe; the reply repeats all three verbatim as correlation only — the worker checks their
grammar and, across the two probes of one connection, that the digest pair is identical (§3),
but verifies nothing about what the digests denote, and no expected platform, identity, schema
or image tuple is ever sent to it. `component.build_identity_digest =
reading.build_identity.digest` (SHA-256 of the exact identity file bytes, lineage §3),
`component.port_schema_set_digest = reading.build_identity.schema_set_digest`, and
`component.port_contract_version` is the reading's identity `port_contract_version` (already
constrained to `tool-port-v1` by `parse_build_identity`), never a literal restated by the
worker; `runtime.platform`/`uid`/`gid` are the reading's own fresh observations
(`WorkerMetadataReading.platform/uid/gid`); `service_identity` is the `responder_service` of the
worker's owned `ChannelSpec`, not an argv re-derivation. `registered_operations` is the exact
key set of the worker's actual immutable semantic registry — the code-owned operation table
of `app/workers/extension_probe.py` (`_OPERATIONS`), fixed at import and keyed by
`tool-port-v1` operation names; since the T087 `describe_tools` slice it is
`["describe_tools", "invoke_tool", "status"]` (the execute slice shipped `["status"]`, the tool-table slice
`["describe_tools", "status"]`, slice 3 `[]`); a placeholder
handler or a copy of the port catalog is forbidden. `describe_tools` answers from the worker's
code-owned tool table (`_TOOLS`, fixed at import; `text_profile` since the first-tool slice,
`text_normalize` since the reverse-leg slice), never
from the port catalog; the execute grammar carries no selection yet, so the whole
table is described. Control does not trust the worker's counters for either read-class query.

### 2b. Closed execute messages (T087 execute slice)

`extension-execute-v1` (request, ≤ 4096 B pre-envelope since the artifact leg — up to eight declared
inputs; wire depth ≤ 6 — a tool result's own objects
reach three levels under the output, root being 1 — otherwise §2's limits):
`schema_version`, `attempt_id` (uuid), `execution_id` (uuid), `operation` (a member of the
port's closed operation set), `envelope_ref` and `profile_ref` (four-field `EntityRef` shapes of
kinds `execution_envelope` / `runtime_profile`), `remaining_ms` (1..30000, the requester's
effective remaining window after permit consumption — the worker may bound its work by it; it
is not an absolute clock value), `challenge` (32-byte nonce, base64url), and — the T018/T087
artifact leg — `artifact_batch_id` (uuid, `null` iff no inputs) with `artifact_inputs`
(≤ 8 declarations `{ordinal, media_type, declared_size, sha256, role}`: the exact ordered
sequence, sizes and their sum ≤ 1 MiB per extension-ports.md `max_input_bytes`, media type and
digest per the stream's descriptor grammar, role a §2 identifier). Identities, references and
descriptors only; never bytes, never model input. The declared bytes follow the request frame
on the channel's `extension-artifact-v1` type, correlated to the request's message id, through
T018's digest/chunk/receiver-credit stream (`ConnectionStreamTransport` on both ends, batch and
request ids = the declared batch id and the request message id). The worker admits them into
bounded owned in-memory sinks (its root is read-only; no scratch volume) only when the
operation is registered and its port contract's request artifact profile takes request
artifacts: profile `E` (`status`, `describe_tools`) takes none, so a request declaring inputs
for them is the typed refusal `failed` / `validation_failed` before any artifact frame is read
(the requester never has to send one). A stream violation (digest, size, order, credit, an
unexpected frame) is terminal: the connection closes without a reply and the operation never
runs; control records `outcome_unknown` (`transport_stream`) — honest because the worker runs
the operation only after it accepted the last artifact, so a failure while control reads that
final acceptance leaves the run possible. Control applies the same profile gate at build
(`ExtensionAttemptTransport.build(artifact_inputs=)`), so a query operation can never be built
with inputs; an input carries its bytes (bounded by the ceiling) so every attempt of the visit,
the owner's recovery retry included, streams them again from a fresh source. Stream frames carry
fresh message ids; their integrity is the channel's sequence and HMAC, and their binding to the
request is the correlation id and the offers' batch/request ids matched field for field. Control
mirrors the tool table statically (`TOOL_INPUT_CONTRACTS`, `TOOL_OUTPUT_CONTRACTS`, `TOOL_EFFECTS`,
pinned equal to the worker's entries by test until ToolDefinition records exist), so a tool call
declaring other inputs is refused at build — never streamed into a worker that would refuse it before
reading a byte, which control could only see mid-stream as an unknown outcome. The registered
consumer of the leg is `invoke_tool`; the multi-input route is still exercised in tests through a
test-only handler.

`extension-execute-result-v1` (reply, ≤ 4096 B): `schema_version`, `attempt_id`, `operation`,
`challenge` (echoed), `outcome` / `usage_finality` / `remote_terminal_observed` / `reason_code`
(the runtime ledger's closed result vocabulary, mirrored in the worker package and pinned equal
by test), `usage` (the seven exact counters iff `usage_finality == "final"`, else `null`),
`output` (present iff `outcome == "succeeded"`; its grammar is selected by the reply's
`operation`: for `status` exactly the probe reply's `service_identity` / `component` / `runtime`
shape; for `describe_tools` exactly `{tools: [{tool_id, version, argument_schema_sha256,
result_schema_sha256, effect_class, artifact_roles}]}` after extension-ports.md §3.2 with the wire's
narrower grammars: `tool_id` and roles are §2 identifiers (no `:`, no `--`, ≤ 64), `version` is
`[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}` (no spaces or parentheses), the schemas are named by their
sha256 digests — a worker cannot reference control-side schema records; control resolves and seals
them later (T087) —, `effect_class` a member of the closed effect classes,
roles sorted unique (≤ 256), one entry per tool in identifier order, at most 8 entries and — the
binding bound — at most 3072 canonical bytes for the table so the reply can always carry it; for
`invoke_tool` exactly `{tool_id, version, result, artifacts}` — the tool's own bounded JSON object,
closed over the wire limits where it is built so a reply the parser would refuse is never sent, and
the bindings of its output artifacts (≤ 8: ordinal, role, media type, exact size, digest; the same
grammar as the declared inputs). The output artifacts travel as an offered batch on the artifact
type, correlated to the request, **before** the reply frame — the reverse leg: `send_batch` on the
worker, `receive_offered_batch` on control under a policy from the named tool's mirrored output
contract (media types, count, the 1 MiB ceiling); an offered batch for a tool whose contract yields
none, or bindings that are not exactly what was admitted, is refused as a transport mismatch and
recorded `outcome_unknown` — honest, because control observed no reply it could call a terminal (the
worker's send fails once control stops reading), and a worker outside the protocol in one place is
not trusted elsewhere; a worker that streams artifacts and then answers a non-succeeded terminal is
refused the same way (ports contract: artifacts are `[]` for every non-succeeded terminal). Control imports each admitted
artifact as registered content and seals its blob reference into the attempt's artifact beside the
output (`artifacts: [{ordinal, role, media_type, blob}]`), counting the artifact bytes with the reply
as the measured output; the sealed artifact is the result (the ports contract's `{tool_call_ref,
result_ref}` are control-side records; the `ToolCall` record stays open); a success under `cancel`
is outside the grammar until its output is defined). The request carries `tool` (`{tool_id,
version}`, required iff the operation is `invoke_tool`; arguments have no wire grammar yet — the
tools take none). The worker's table holds `text_profile` 1.0.0 (effect `read`, exactly one
`document_source` `text/plain` input, strict UTF-8): byte/character/line/word counts and the digest,
with stated definitions a non-Python worker can repeat under the same result schema digest — bytes;
code points (a BOM kept and counted); `\n`-terminated segments plus one final unterminated segment;
runs between ASCII whitespace; the bytes' sha256 — and `text_normalize` 1.0.0 (effect `read`, the
same input; NFC, CRLF and a lone CR to LF, one leading BOM removed, nothing else changed; the derived
text is its one output artifact `normalized_text` text/plain over the reverse leg; the result names
the input and output digests and sizes and whether anything changed; NFC can triple UTF-8 bytes, so
the derived text is at most three times the input and, over the 1 MiB ceiling, the tool's own terminal
failure). A call naming another tool or
version, or declaring other inputs, is the typed refusal `validation_failed` before any byte is read;
bytes that are not a text are the tool's own terminal failure (`provider_terminal`, one tool call).
Control verifies a tool call: the reply's tool id and version are the ones it named; the result's
input digest and byte count agree with the streamed input it holds, and its output digest, size and
`changed` with the output it admitted (the rest of the result is the
worker's claim, sealed as such); usage is exactly one tool call (none when refused before it ran:
`validation_failed`, `permission_denied`), no model call, the reply and artifact bytes measured; an
in-process read-effect tool has no `outcome_unknown` or `cancelled` terminal (class C's terminals
pass through only for an external-effect tool, and none is in the table). Invariants: an unknown outcome cannot claim
a known remote terminal; a succeeded outcome observes `succeeded`; a terminal outcome other than
`succeeded` cannot observe `succeeded`. An unregistered operation is the typed refusal
`failed` / `validation_failed` with final zero usage and no output. Control does not trust the
worker's counters for the read-class queries `status` and `describe_tools`: the only real
counter (`output_bytes`) is measured control-side; a completed query claiming its usage unknown,
or any final claim other than the measured one, is a mismatch (`outcome_unknown`). A succeeded output is sealed control-side as an `artifact`
record whose id derives from the send-intent command; the worker never touches the store.

### 2a. Pure interfaces (slice 1b)

New module `app/workers/extension_probe_messages.py` (pure; no I/O, authority or service; the
slice-3 service and the Task 24 observer are its importers) exports:

```python
class ProbeMessageError(ValueError)            # fixed message "invalid probe message", never input
class ProbeRequest    # frozen: request_blob_sha256: str, receipt_blob_sha256: str, challenge: bytes (32)
class ProbeComponent  # frozen: build_identity_digest: str, port_contract_version: str, port_schema_set_digest: str
class ProbeRuntime    # frozen: platform: str, uid: int, gid: int, registered_operations: tuple[str, ...]
class ProbeReply      # frozen: request_blob_sha256, receipt_blob_sha256, challenge: bytes, service_identity: str,
                      #         component: ProbeComponent, runtime: ProbeRuntime
encode_probe_request(*, request_blob_sha256, receipt_blob_sha256, challenge: bytes) -> bytes
parse_probe_request(raw: bytes) -> ProbeRequest
encode_probe_reply(*, request_blob_sha256, receipt_blob_sha256, challenge: bytes, service_identity,
                   build_identity_digest, port_contract_version, port_schema_set_digest,
                   platform, uid, gid, registered_operations) -> bytes
parse_probe_reply(raw: bytes) -> ProbeReply
```

Values are frozen dataclasses of validated scalars; the nonce travels as 32 `bytes` and is
rendered/decoded by the codec. Encoders take plain validated scalars only — never a
`WorkerMetadataReading`, a `ChannelSpec` or a registry object (the service, not the codec, is
the response builder that reads them) — and refuse every value outside the grammar before
encoding; `encode` then `parse` round-trips byte-for-byte. Parsers refuse noncanonical bytes,
caps, unknown/duplicate/missing fields and wrong types with the single closed error. A parsed
message is an inert value, never an observation or a readiness claim.

## 3. Envelope use and per-connection rules (slices 2c–3)

Probe frames use the existing `FrameEnvelope`: request `message_type="extension-request-v1"`,
fresh canonical lowercase UUID `message_id`, `correlation_id=null`; reply
`message_type="extension-result-v1"`, a new UUID `message_id`, `correlation_id` equal to the
request's `message_id`. The framing accepts the nil UUID; the probe service and observer refuse
it (`refs.uuid_string` semantics). All four message ids of a connection (two requests, two
replies) are distinct. The first authenticated application frame selects the connection mode
by the exact request schema: `extension-stage-probe-v1` (observation-only, at most two probes)
or `extension-execute-v1` (one execute request, one reply, then the worker closes; a second
request of either schema, or a reply schema on a request frame, closes the connection).
Observation-only connections: at most two probes, distinct message ids and
nonces, identical `request_blob_sha256`/`receipt_blob_sha256`; the worker remembers only those
bounded values locally and closes after the second reply. A repeated challenge, a third probe, a
different digest pair, any other message type (the framing permits `extension-artifact-v1`; the
probe rejects it — only an execute connection whose request declared inputs reads it, §2b), an artifact or semantic payload, a malformed correlation (request
`correlation_id != null`, reply `correlation_id != request.message_id`) or an unexpected frame
closes the connection with a sanitized local error. No retry, no failure-success envelope, no
artifact stream; semantic dispatch is admitted only through the execute schema selected by the
first frame (§2b) — a semantic payload on a probe connection still closes it. Each probe reply
is built from an actual
`read_current(deadline=...)` of the worker's metadata source per probe; readiness never
substitutes for that read. Control rejects a reply whose `service_identity` differs from the
`responder_service` of the authenticated session's `ChannelSpec`.

## 4. Budgets and bounds

Control attempt ≤ 2000 ms measured from before connect; final probe ≤ 500 ms and within the
remaining attempt budget. Worker accepted connection ≤ 2000 ms; metadata reads ≤ 500 ms as
contracted. Handshake packets ≤ 4096 B in the private extension wrappers (the existing frame
decoder may buffer ≤ 65536 B before the tighter payload rejection). At most four handshake packets
and two request/reply pairs per probe connection (one per execute connection); payload caps are
§2's pre-envelope byte sizes (probe: 1024 B / 4096 B, depth 4) and §2b's (execute: 4096 B /
4096 B, depth 6; declared input bytes ≤ 1 MiB per batch over the artifact stream). Worker
service total owned FDs ≤ 64 including the metadata source's 13 retained + ≤ 32 transient (45 at
peak), leaving ≤ 19 for generation, listener, connection and fence descriptors. Digests, nonces
and bytes never appear in logs. Metadata syscall stalls cannot be preempted; control enforces its
network deadline independently.

## 5. Service ownership (slice 3)

The worker service opens its metadata source before binding or advertising its listener and
relies on the existing listener identity check (`_validate_local_identity`: uid/gid equal the
slot, pair-gid membership). One service owns one boot ID, one metadata source and one listener;
`serve_one(deadline)` accepts and handles one connection without new threads or processes; a
nonblocking guard rejects overlapping `serve_one`/`close` as busy. Control owns one process boot
ID. A future control observer derives the slot and the request/receipt blob digests from the
actual retained prepare/receipt records, never from a browser-supplied tuple; this contract adds
no such observer and exposes no low-level connection as a reusable admission proof.

## 6. What a probe reply is not

A reply received over a completed mutually authenticated connection (slices 2a–2c) is a
self-reported component observation at one moment over one connection: the probe compares
nothing to an expected tuple — that comparison (`validate_descriptor_lineage`, the request tuple)
belongs to the Task 24 observer. It is not qualification, a usable-tool claim, installation,
readiness, a permit, a grant, or evidence of life after the response; there is no DB atomicity.
Control separately compares the kernel peer uid/gid, rechecks its retained sources and endpoints
after each reply, and a later stage postcondition consumes the observation only inside its own
same-writer authority/currentness transaction. Gates reported, never claimed: both native
architectures; the actual initializer/image/mount/UID/argv packaging of the fixed image (`main()`,
`bin/worker`); allowed-manifest and OCI identity trust; the worker semantic registry beyond the
three code-owned operations — `status`, `describe_tools` over the two-tool table, and
`invoke_tool` running `text_profile` and `text_normalize` over both artifact legs (T087: `cancel`,
tool arguments in the execute grammar, the `ToolCall` record and `{tool_call_ref, result_ref}`
control-side, schema records resolved from the entries' digests and the result validated against
them, the effect gate and grant check for a tool call (`effect_class` is the entry's claim, mirrored
on control, enforced by nothing yet), class-C terminals for external-effect tools, the tool table
learned from `describe_tools` instead of the static mirror, a worker-owned scratch for larger
outputs (in-memory sinks bound both legs to 1 MiB; the transport states `output_bytes_bound` — the reply
frame's ceiling plus the tool's stated growth over its inputs from `TOOL_OUTPUT_BOUNDS` — enforces the artifact
part against what it received, and the dispatcher refuses a binding reserving less), optional outputs (an omissions
policy; the wire binds exactly the contract's count), the data-model `Artifact` entity for the sealed
output (an inline blob reference today; a seal failure after the import leaves a registered,
unreferenced content-addressed blob),
the ports contract's per-tool input count (up to 32 for T-tool; the wire carries 8), role and
selector binding to the ToolDefinition, every model-bearing port); the control observer and admission; positive Linux authentication (non-Linux hosts fail closed at
peer credentials). No human/key authority, metadata mount, allowlist or core fixture lock is
introduced; boot IDs are per-process `secrets.token_hex(32)` labels, never owner accounts;
`app/workers` imports nothing from `app.api`, `app.static` or `app.server`; no GUI.
