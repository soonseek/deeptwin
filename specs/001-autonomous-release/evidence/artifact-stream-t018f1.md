# T018-F1 (bounded artifact stream) — digest/chunk/receiver-credit transfer

Date: 2026-09-12
Status: implemented and unit-verified transport-agnostic slice; **T018-foundation and T018
remain open** (no Linux/root canary run, no coordinator wiring yet)

## Exact scope

This adds the bounded artifact byte route the contract requires as the *only* way a worker
receives or returns artifact bytes (runtime.md L350-355; decisions.md ADR-014 rev.5,
"digest/chunk/receiver-credit stream is the only byte route; typed refs and shared-store
mounts are not substitutes").

- `app/workers/artifact_stream.py`: a transport-agnostic state machine driving a
  `StreamTransport` that moves one bounded frame payload at a time.
  - `ArtifactDescriptor`: frozen exact identity (batch/request UUIDs, ordinal/count with
    1..256 bound, media type, declared size ≤ 64 MiB, lowercase sha256).
  - `send_artifact`/`receive_artifact`: offer → absolute receiver-credit watermark →
    ordered chunks (≤ 16,384 raw bytes each) → end digest → acceptance. Cancellation and
    every violation are terminal with no offset resume and no retry.
  - `send_batch`/`receive_batch`: a frozen ordered 1..256 batch with a shared batch/request
    id, exact ordinal sequence and an aggregate byte ceiling.
  - `BytesSource`/`BytesSink` (in-memory) and `ScratchFileSink` (owned scratch file created
    `O_CREAT|O_EXCL|O_NOFOLLOW` under a user-owned directory fd; `abort` unlinks it).
- `app/tests/test_worker_artifact_stream.py`: 26 acceptance tests over a threaded paired
  transport and a scripted-attacker transport.

The chunk bound is chosen so one chunk message, base64-encoded here and again inside the
broker's JSON frame envelope, stays well under `broker.MAX_FRAME_BYTES` (65,536); a test
asserts the double-encoded worst case with envelope headroom.

## Enforced invariants (each has a reproducing test)

- Bytes and digest round-trip for single-chunk, multi-chunk (several credit rounds) and
  zero-length artifacts, and for an ordered multi-artifact batch.
- Absolute credit watermark: the sender never sends past `credit_through`; a watermark that
  moves backward, exceeds the declared size, or fails to advance a sender that still holds
  unsent bytes (a stalled consumer) is terminal — a replayed credit cannot amplify capacity.
- Receiver defenses: offer that does not exactly match the expected descriptor; chunk beyond
  granted credit; out-of-order chunk offset; over-limit chunk length; end size/digest
  disagreement; sender cancellation. Each is terminal and the sink is aborted (never
  finalized), so no partial artifact is admitted.
- Sender integrity: a source whose bytes do not match the declared digest, or a declared
  size larger than the source (short read), fails and cancels the stream.
- Strict framing: non-canonical base64 and non-integer JSON numbers are rejected.
- Descriptor and batch validation: bad UUID/ordinal/media-type/digest/size, wrong ordinal
  sequence, and aggregate over the total byte limit are all rejected.
- Owned scratch: `ScratchFileSink` persists the exact bytes on success and unlinks the file
  on a failed stream.

## Verification

```text
python -m pytest -q app/tests/test_worker_artifact_stream.py
26 passed

ruff check app/workers/artifact_stream.py app/tests/test_worker_artifact_stream.py
All checks passed

python -m pytest -q app/tests deploy/tests   (full shared regression, 2026-09-12)
2,960 passed, 2 skipped, 369 subtests passed, 1 known Starlette/AnyIO deprecation warning
```

## Frozen content identities (SHA-256)

```text
6b9e3448128897973397d33bcff8f3c3d92e4ff8f6a78371ceb6bffb1d0b417e  app/workers/artifact_stream.py
1dfd909f8e19acb8a8b980d447aed05ba387e96dfd6b1a09d01352c79e3aa77b  app/tests/test_worker_artifact_stream.py
```

## FrameCodec adapter (2026-09-12)

`app/workers/artifact_stream_transport.py` adds `FrameCodecTransport`, a `StreamTransport`
that carries each stream message as one authenticated `broker.FrameCodec` frame stamped with
the request's correlation id; every broker transport failure surfaces as a terminal
`ArtifactStreamError`. `app/tests/test_artifact_stream_transport.py` runs the stream over a
real socketpair with a full broker handshake and two codecs in two threads:

```text
python -m pytest -q app/tests/test_artifact_stream_transport.py
4 passed
```

covering a single-frame round trip, a multi-chunk transfer that exchanges real credit frames,
a correlation-id mismatch (terminal), and adapter construction guards. This closes the
"FrameCodec adapter not written" gap; the stream now demonstrably works over authenticated,
replay-checked, size-bounded frames, not only the in-memory paired transport.

Frozen identities (SHA-256):

```text
76acece677d402bb54b154550b634d07b1d3845a56274bc204a6f8fc3020a08c  app/workers/artifact_stream_transport.py
7e71d08c28fc7fc37c421451ab7c15a27b091e26aaf845f6dcda8ab626229287  app/tests/test_artifact_stream_transport.py
```

## Coordinator wiring — input direction (2026-09-12)

`WorkerCoordinator.exchange` now carries declared artifact inputs to the worker over the same
authenticated session as the dispatch itself:

- `WorkerRouteBinding.artifact_stream_message_type` (default `None`) declares the duplex
  stream type; it must appear in *both* the requester and responder message-type sets and be
  distinct from the request and response types, else the binding is rejected at construction.
- `DispatchArtifactInput` pairs one exact `ArtifactDescriptor` with one byte source. `exchange`
  gained a keyword-only `artifact_inputs: tuple[...] = ()`; the signature guard test now pins
  the four-parameter shape and still rejects any caller-controlled `payload`.
- Fail-closed ordering: inputs are validated *before* permit consumption — a tuple of exact
  `DispatchArtifactInput`s, every `descriptor.request_id` equal to the permit's `command_id`,
  and the whole batch passing `validate_batch` (now a public `artifact_stream` API) — so a
  streamless route, a foreign stream identity, or a malformed batch leaves the permit intact
  (`WorkerArtifactRejected`, `definitely_not_sent`).
- After the request frame is written, the batch streams through a `FrameCodecTransport` bound
  to the live codec/socket with `correlation_id = command_id` (the worker learns it from the
  request frame's `message_id`). Any stream failure past that point raises
  `WorkerArtifactStreamFailed` with `dispatch_effect="outcome_unknown"`, closing the codec,
  socket and admission slot through the existing `finally`.

`app/tests/test_worker_coordinator_artifacts.py` (7 tests) drives the coordinator over a real
socketpair with a real broker handshake and two live frame codecs — the worker side runs
`receive_batch` in a thread — covering: duplex/distinct route validation; pre-consumption
rejection on a streamless route, a foreign request id and malformed input shapes; a two-artifact
(multi-chunk + small) round trip whose request frame carries the exact immutable envelope bytes
and whose worker sinks reproduce the exact bytes; a streamless exchange on a stream-capable
route; a worker that abandons the stream after the request frame (`outcome_unknown`, permit
consumed); and a lying source whose digest mismatch cancels the stream on both ends.

```text
python -m pytest -q app/tests/test_worker_coordinator_artifacts.py \
    app/tests/test_worker_coordinator.py app/tests/test_worker_dispatch.py
62 passed

ruff check app/runtime/worker_coordinator.py app/workers/artifact_stream.py \
    app/tests/test_worker_coordinator_artifacts.py app/tests/test_worker_coordinator.py
All checks passed

python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-12)
2,971 passed, 2 skipped, 369 subtests passed, 1 known Starlette/AnyIO deprecation warning
```

Frozen identities (SHA-256):

```text
ff6ef00592120ae2cdc370224e0a27413cc800f78f96b6c5cba417cd91f46cf2  app/runtime/worker_coordinator.py
e5cd2588aafb1599d1d6b22ec1e21cb994569b630a7f4b493c1b895656be6d43  app/workers/artifact_stream.py
c053f9b6caecc5369c1b25581905a732c209862291f5c77fc9090a3cbbcbc865  app/tests/test_worker_coordinator_artifacts.py
```

## Coordinator wiring — output direction (2026-09-12)

Workers now return artifact bytes through the same digest-first protocol with the roles
swapped, driven by an offer-driven receive because the control plane cannot know output
descriptors in advance:

- `artifact_stream.OfferedBatchPolicy` is the receiver's bound for a sender-declared batch:
  exact `request_id`, a closed non-empty `allowed_media_types` tuple and `max_artifacts`
  (validated at construction). `receive_offered_batch(transport, policy, sink_factory,
  limits)` admits an ordered batch whose descriptors arrive in the offers, enforcing per
  offer: policy request id, allowed media type, first-offer count ≤ policy and ordinal 0,
  frozen batch identity (batch_id/count) and exact ordinal sequence mid-stream, per-artifact
  and running-aggregate byte ceilings. A violating offer is cancelled toward the sender and
  terminal; the admitted body reuses the same `_admit_body` credit/chunk/end/digest path as
  `receive_artifact` (refactored out, behavior unchanged). `PushbackTransport` replays one
  already-received payload so a peeked frame can start the stream.
- `WorkerCoordinator.exchange` gained keyword-only `artifact_output_policy: OfferedBatchPolicy
  | None = None`, validated before permit consumption (exact policy type, stream-capable
  route, `policy.request_id == permit.command_id`); the signature guard now pins the
  five-parameter shape. After the request (and any input batch), if the next authenticated
  frame carries the route's stream type and the exact command correlation, the coordinator
  receives the offered batch into `BytesSink`s and then reads the terminal response frame;
  the verified artifacts return as `AuthenticatedWorkerResponse.artifacts`, a tuple of
  `ReceivedWorkerArtifact` whose constructor independently recomputes length and sha256
  against the descriptor. Stream failures raise `WorkerArtifactStreamFailed`
  (`outcome_unknown`); a worker streaming without a declared policy still dies as a
  `ProtocolViolation` (`outcome_unknown`) through the existing response-type check.

New tests: 8 stream-level (`test_worker_artifact_stream.py`: offered-batch round trip without
prior descriptors, foreign request id, disallowed media, count over policy, aggregate over
total bytes, changed batch identity mid-stream via scripted frames, policy field validation,
pushback replay) and 6 coordinator-level over real socketpair codecs
(`test_worker_coordinator_artifacts.py`: pre-consumption policy rejection; a two-artifact
multi-chunk output return; one exchange carrying inputs *and* outputs on one authenticated
session; an undeclared worker stream as protocol violation; a policy-violating output media
cancelled on both ends; `ReceivedWorkerArtifact` digest recomputation).

```text
python -m pytest -q app/tests/test_worker_coordinator_artifacts.py \
    app/tests/test_worker_coordinator.py app/tests/test_worker_artifact_stream.py \
    app/tests/test_artifact_stream_transport.py app/tests/test_worker_dispatch.py
106 passed

ruff check (all five touched files)
All checks passed

python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-12)
2,985 passed, 2 skipped, 369 subtests passed, 1 known Starlette/AnyIO deprecation warning
```

Frozen identities (SHA-256):

```text
6bb87dc2f77a56d21ff2820c8012c1f35c990a5007fac6cc86301f30cebc786e  app/runtime/worker_coordinator.py
568db1ebc28c9c7b26139272567ed70368722c3e790486ab5c1849108ff5e093  app/workers/artifact_stream.py
1a49c0848b3bfd26d2ef61459bd7b31e6b8d6f187b4a8a50fe3d8ae7c873aa79  app/tests/test_worker_coordinator_artifacts.py
53b6b6e9c14ac6309526f13670ae155674d2fbd1fe4bfa7bf037ee026225bd75  app/tests/test_worker_artifact_stream.py
```

## Not claimed

`worker_dispatch.py` does not yet plumb `artifact_inputs`/`artifact_output_policy` from any
semantic caller, sources and sinks are in-memory rather than CAS-backed store reads/writes,
and no Linux/root canary has exercised the stream over a real UDS with SO_PEERCRED — the
2026-09-12 attempt remains blocked by the host's Docker content-store I/O fault, not by the
code. No independent adversarial re-audit of the artifact stream or its coordinator wiring
has run yet.
