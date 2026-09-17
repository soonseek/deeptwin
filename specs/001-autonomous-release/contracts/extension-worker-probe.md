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
artifact type exists so a later semantic route can bind the same channel (`WorkerRouteBinding`
needs a distinct bidirectional artifact type); the probe never sends it. Fixed image argv: a
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
key set of the worker's actual immutable semantic registry — for slice 3 that registry is empty
and the reply says `[]`; a placeholder handler or a copy of the port catalog is forbidden.

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
replies) are distinct. The first authenticated application frame selects observation-only mode
by the exact request schema. Per connection: at most two probes, distinct message ids and
nonces, identical `request_blob_sha256`/`receipt_blob_sha256`; the worker remembers only those
bounded values locally and closes after the second reply. A repeated challenge, a third probe, a
different digest pair, any other message type (the framing permits `extension-artifact-v1`; the
probe rejects it here), an artifact or semantic payload, a malformed correlation (request
`correlation_id != null`, reply `correlation_id != request.message_id`) or an unexpected frame
closes the connection with a sanitized local error. No retry, no failure-success envelope, no
artifact stream, no semantic dispatch. Each reply is built from an actual
`read_current(deadline=...)` of the worker's metadata source per probe; readiness never
substitutes for that read. Control rejects a reply whose `service_identity` differs from the
`responder_service` of the authenticated session's `ChannelSpec`.

## 4. Budgets and bounds

Control attempt ≤ 2000 ms measured from before connect; final probe ≤ 500 ms and within the
remaining attempt budget. Worker accepted connection ≤ 2000 ms; metadata reads ≤ 500 ms as
contracted. Handshake packets ≤ 4096 B in the private extension wrappers (the existing frame
decoder may buffer ≤ 65536 B before the tighter payload rejection). At most four handshake packets
and two request/reply pairs per connection; payload caps are §2's pre-envelope byte sizes. Worker
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
`bin/worker`); allowed-manifest and OCI identity trust; the worker semantic registry (T087); the
control observer and admission; positive Linux authentication (non-Linux hosts fail closed at
peer credentials). No human/key authority, metadata mount, allowlist or core fixture lock is
introduced; boot IDs are per-process `secrets.token_hex(32)` labels, never owner accounts;
`app/workers` imports nothing from `app.api`, `app.static` or `app.server`; no GUI.
