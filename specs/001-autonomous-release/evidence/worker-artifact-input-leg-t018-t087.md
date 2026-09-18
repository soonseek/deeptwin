# Evidence — T018/T087: the artifact input leg of the extension execute exchange

- Date: 2026-09-18
- Task: the Continuation's "artifact stream". T018's bounded digest/chunk/receiver-credit stream
  (`artifact-stream-t018f1.md`; wired into the generic `WorkerCoordinator` in
  `worker-coordinator-t018b.md`) now rides the extension worker channel's reserved
  `extension-artifact-v1` type as the only byte route into a semantic operation
  (runtime.md L350-355; ADR-014 rev.5; extension-ports.md: bytes only through the stream;
  `max_input_bytes ≤ 1 MiB`). Contract amended: `contracts/extension-worker-probe.md` §2b
  (request grammar, the leg, gates), §3 (the artifact type on an execute connection), §4
  (bytes), §6 (open items).

## Frozen identities

```
4da22aa23dc60519ebed47d60b4f012a2d1eae8f80059ef9a20ae689fe43a5ed  app/workers/extension_execute_messages.py
979ee8fde6e17226f452950a22cd717472304d2e63b0d31dcfb7176b2366a35c  app/workers/extension_probe.py
914d95a340d2cfc7cb3bc77d5ea73059c8ae123469abd6e4f12648013c40f180  app/workers/artifact_stream_transport.py
cdf776e472b91ab5c01a9733f86acb6b0ac65b83f8483c866f8ec400224335ad  app/runtime/extension_attempt_transport.py
d2973a4acda5165fd61d1a8ded214b77e0e784c62e4f5e409a665c177acafdaa  app/tests/test_extension_execute_messages.py
58782f0817c56c188650fd1711d43fc303f56c5a5aaf40e22e59734518c63d30  app/tests/test_extension_execute.py
7dd78f5daaff996446445b4504064d6838bdf0078346800c9afc37b4f0f4e9bd  app/tests/test_extension_attempt_transport.py
c08abf110eeb7bf9152c7e27b66998d26d3e75858ba56009ad1efa01a8dfeb63  specs/001-autonomous-release/contracts/extension-worker-probe.md
```

(The identities of these files frozen in `worker-describe-tools-t087.md` and
`artifact-stream-t018f1.md` are superseded.)

## What was built

- `app/workers/extension_execute_messages.py`: the request declares its artifact inputs —
  `artifact_batch_id` (uuid, null iff none) and `artifact_inputs` (≤ 8 `{ordinal, media_type,
  declared_size, sha256, role}` declarations: the exact ordered sequence, sizes and their sum
  ≤ `MAX_INPUT_BYTES` = 1 MiB, media type ≤ 128 bytes and digest through the stream's own
  descriptor grammar, role a §2 identifier); `ArtifactInputDeclaration`;
  `ExecuteRequest.artifact_descriptors(request_id)` builds the stream descriptors under the
  declared batch id and the request frame's message id; `MAX_REQUEST_BYTES` 2048 → 4096.
- `app/workers/artifact_stream_transport.py`: `ConnectionStreamTransport` — the stream over an
  owning `ExtensionConnection` at either end: every message one authenticated frame of the
  artifact type correlated to the request's message id; a frame of another type or
  correlation is a terminal stream error.
- `app/workers/extension_probe.py`: `_Router.admits_inputs(request)` — declared inputs are
  admissible only for a registered operation whose port contract's request artifact profile
  takes request artifacts (profile `E` — `status`, `describe_tools` — takes none); a request
  declaring inputs otherwise is the typed refusal `failed`/`validation_failed` before any
  artifact frame is read. When admitted, `_serve_execute` receives the declared batch into
  bounded in-memory sinks (`EXECUTE_STREAM_LIMITS`, 1 MiB; the worker's root is read-only, no
  scratch volume) before running the operation, which receives `(declaration, bytes)` pairs;
  a stream violation is terminal — the connection closes without a reply and the operation
  never runs; `ArtifactStreamError` is sanitized and the descriptor build stays inside the
  sanitizer (the domain admits any non-nil canonical UUID as a message id, the stream only a
  versioned one).
- `app/runtime/extension_attempt_transport.py`: `ExtensionArtifactInput(media_type,
  declared_size, sha256, role, payload)` — validated through the wire grammar and against its
  own bytes at construction; `build(..., artifact_inputs=)` applies the same profile gate as the
  worker and the byte ceiling; the request carries a fresh batch id per attempt and the
  declarations; after the request frame control streams the batch from fresh sources (so the
  owner's recovery retry streams again); any failure past the request is
  `ExtensionTransportError("transport_stream")` with effect `outcome_unknown` — honest because
  the worker runs the operation only after accepting the last artifact, so a failure while
  reading that final acceptance leaves the run possible.

No registered operation takes inputs today: the byte route is exercised end to end over the
real authenticated socket pair through a test-only handler under `invoke_tool` (profile
`T-tool`) with the router's admission seam monkeypatched; production code has no placeholder.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 4 SHOULD, 3 NIT); probes over the real socket pair.
Verified clean: an E-profile refusal while a foreign client streams anyway ends in a stream
error on the client, no deadlock, no stale-frame bleed into the next connection; a maximal
8-declaration request encodes in 3347 B; `peek_schema` unchanged; a forged over-ceiling sum
refused at parse; an artifact frame as the first frame refused; both ends check the frame's
type and correlation and match offers field for field; memory bounded (≤ 1 MiB of sinks plus
one frame, one connection under the service lock). Closures, RED-first:

1. MUST — `transport_stream` was not a registered transport error code: control's stream
   failure raised a bare `ValueError` that only the dispatcher's last-resort barrier turned into
   an unknown outcome → registered; the RED test forces an end-digest mismatch over the socket
   and asserts the typed error, its effect and the ledger's `outcome_unknown`.
2. MUST — the descriptor build sat outside the sanitizer: a request frame id that is a canonical
   but unversioned UUID raised a raw `ArtifactStreamError` that would have escaped the worker
   entrypoint → the build moved inside the boundary and the stream error sanitized; the RED test
   sends such an id and asserts the sanitized error with the service still serving.
3. SHOULD — the effect comment gave the wrong reason → reworded to the acceptance race (code
   and contract).
4. SHOULD — a consumed one-shot source would have made every retried attempt with inputs an
   unknown outcome → inputs carry their bytes and stream from a fresh source per attempt; the
   RED test runs the owner's recovery retry over a second served connection.
5. SHOULD — ports-contract parity stated as open (§6): the wire carries 8 inputs where T-tool
   tools declare up to 32; roles are identifiers not yet bound to a ToolDefinition; the test
   roles renamed off `arguments` (the ports contract forbids bytes there).
6. SHOULD — weak/missing tests → the violation test asserts the exact sanitized error, the
   service not poisoned and the next connection serving; new tests for an unregistered
   operation with inputs (refused before any byte), a foreign correlation on the stream, and the
   ceilings pinned equal across grammar, worker and control.
7. NIT — media types bounded at 128 bytes on encode as on parse. 8. NIT — descriptors built
   once before the request write. 9. NIT — §2b states the frames' message-id rule.

## Verification

- TDD: RED retained — `encode_execute_request() got an unexpected keyword argument
  'artifact_batch_id'`, no `ExtensionArtifactInput`, the worker refusing nothing; GREEN after the
  grammar, the adapter, the worker leg and the control leg (three adjustments on the way: the
  test-only handler's reason code from the ledger's closed set, the router's admission seam in
  the tests, declaration objects accepted by the encoder); the review's RED tests failed for
  their stated reasons (`ValueError: unknown transport error code`; the raw stream error in the
  worker box; no `payload` field).
- Tests: messages **+1**, execute **+6**, transport **+4**; covering (messages, execute,
  transport) **58**; (probe, probe messages, stream transport, stream) **139**; (stage observer,
  deployment consume, coordinator artifacts) **63**; (dispatch, runs API) **42** — in separate
  processes (the descriptor checks are order-sensitive across suites, pre-existing). Ruff:
  clean on every changed Python file.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- Inputs only: no worker-returned output artifacts over the channel, no operation input in
  the grammar beyond the declarations, no registered consumer, no real tool, no `invoke_tool`
  or `cancel`; the worker's tool table stays empty; no scratch volume (bounded memory); no
  model, tool or paid call. The live container/socket/worker run stays the host gate.
