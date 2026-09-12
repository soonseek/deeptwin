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

## Not claimed

The stream is not yet wired into `worker_coordinator.py`/`worker_dispatch.py` (the coordinator
still performs a single request/response exchange), and no Linux/root canary has exercised it
over a real UDS with SO_PEERCRED — an attempt on 2026-09-12 was blocked by a Docker
content-store I/O fault on this host, not by the code. Real CAS-backed sources/sinks,
coordinator integration and the Linux qualification remain open T018-foundation work, and no
independent adversarial re-audit of this slice has run yet.
