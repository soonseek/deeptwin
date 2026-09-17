# Evidence — Task 24 step (d): control-side stage postcondition observer

- Date: 2026-09-18
- Task: Task 24 redraft step (d) "evidence value inside the observer module with an in-process
  socket responder test". Contract: `contracts/deployment-receipt-journal-v3.md` §4 (evidence
  blob) and §5 (observer); `contracts/extension-worker-probe.md` §3/§4/§6. Building blocks:
  Task 25 (`_connect_extension_authenticated`, `ExtensionConnection`, probe codecs,
  `WorkerProbeService`).

## Frozen identities

```
3b9612d7cc7fa9a2033149e95d063ec7644934a6dd4e71d9fb114b5532438efc  app/deployment/stage_observer.py
d371170589334cf9165c57abb05876bb098560f42401bf4df1033a22632d2b35  app/tests/test_stage_observer.py
```

## What was built

- `app/deployment/stage_observer.py` (new):
  - `StagePostconditionError(code)` — the closed family `probe_unavailable` / `probe_mismatch` /
    `probe_deadline` / `probe_invalid`; the code is the whole message.
  - `ExpectedStageIdentity` — the frozen typed expectation (service identity by the broker
    grammar, hex64 digests, `tool-port-v1`, platform enum, uid/gid 1..2^32-1); built by the
    service from retained records (step (e)), never from a reply.
  - `StagePostconditionEvidence` — the canonical `extension-stage-postcondition-v1` bytes with
    digest and size: nonconstructible, immutable, uncopyable, unserializable, repr shows the size
    only; no live socket retained.
  - `_process_boot_id()` — one `secrets.token_hex(32)` per process, lazily, under a lock.
  - `observe_stage_postcondition(*, request_id, request_digest, receipt_digest, request_bytes,
    receipt_bytes, slot_number, instance_id, expected, deadline)` — validates every input before
    any socket; derives the channel through `extension_channel`; bounds the whole attempt to
    2000 ms from before connect; connects with `_connect_extension_authenticated` under the
    process boot ID; requires hex64 boot ids and connection id, a `PeerCredentials` peer equal
    to the slot uid/gid; sends exactly two probes (fresh `os.urandom(32)` challenges, fresh
    non-nil UUIDs, the final probe ≤ 500 ms within the remaining budget); verifies each reply
    (`extension-result-v1`, correlation to the probe's message id, a fresh reply id, verbatim
    digests and challenge, `service_identity` equal to the channel's responder) and compares
    every field of `component`/`runtime` with `expected` (`registered_operations` recorded, not
    compared); `recheck()`s after each reply; closes the connection; emits the blob with
    `observed_at`, `attempt_ms`, the connection facts, both probes, `expected` and
    `comparison:"equal"`. A socket timeout with the attempt exhausted is `probe_deadline`;
    transport/listener failures are `probe_unavailable`; malformed or miscorrelated replies,
    non-hex64 session ids, an absent peer and invalid inputs are `probe_invalid`; any compared
    inequality or a peer outside the slot is `probe_mismatch`. No failure produces evidence.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (no MUST; twenty scratch probes against the code — peer, reply,
framing, session, input and budget deviations — all failed closed with no evidence and no
leaked descriptor). Closures, all RED-first:

1. SHOULD — a handshake that stalled until the attempt was exhausted was `probe_unavailable`
   while the same stall one packet later was `probe_deadline` → the connect clause applies the
   same "attempt exhausted → deadline" rule; test: a responder that accepts the transport and
   never answers the hello, 10 s caller deadline, `probe_deadline` within 1.5–3.0 s.
2. SHOULD — a framing-level violation from the authenticated worker (a garbage frame) was
   `probe_unavailable` → `ProtocolViolation`/`AuthenticationError` map to `probe_invalid`
   (the worker was reached and answered wrongly); test: a garbage frame after the handshake.
3. SHOULD — the reply-side uid/gid comparison was never reached (the peer check fired first)
   → a test where the seam peer and the expectation agree on a uid/gid the worker does not
   report: `probe_mismatch` after exactly one served reply.
4. SHOULD — only a wrong challenge exercised the reply checks → parametrized wrong
   correlation, reply id equal to the request id and the artifact message type, each
   `probe_invalid`.
5. NIT — the hex64 boot-id pin was untested → a listener with a legal non-hex boot id is
   `probe_invalid` after a completed handshake.
6. NIT — `attempt_ms` included the teardown → measured after the exchange, before close.
7. NIT — failure paths had no descriptor baselines → mismatch, peer, silent, transport-only
   and malformed cases assert the baseline.
- Reviewer-verified: exact §4 blob conformance (worst case 2588 B, so the 8192 cap is defensive
  only); the attempt window starts before connect and the final probe is bounded to 500 ms; the
  timeout→deadline mapping is sound (CPython rounds the poll timeout up, so a timeout return
  implies `remaining() == 0`); check ordering; immutability/copy/pickle refusals; closed error
  messages with every mapping `from None`; input validation before any socket with caps
  matching `parse_request`/receipts §2; honest tests (real missing readiness, seam re-runs the
  real channel validation, subprocess boundary); a fresh import loads nothing from `app.api`,
  `app.static`, `app.server`, `app.services` or the prepare service.

## Verification

- TDD: RED retained — `ModuleNotFoundError: No module named 'app.deployment.stage_observer'`
  (2 failed, 20 errors); GREEN after one implementation finding surfaced by the silent-responder
  test (the framing reports a socket timeout as an uncertain transport, mapped to
  `probe_deadline` when the attempt budget is exhausted) and two test-side corrections (the
  channel seam now delegates identity validation to the real derivation; a helper argument name).
- Covering after the closures: **68 passed** (stage observer 29, extension probe, extension
  listener); before them **237 passed, 1 skipped** — stage observer 22,
  extension probe, listener, handshake, probe messages, channel, populated fence, worker
  listener. Ruff clean.
- Test honesty on this macOS host: the responder is the actual in-process `WorkerProbeService`
  over the listener seams (no peer credentials, no `/proc`, synthetic mountinfo, temporary
  fixed-file tree); the connect seam supplies the slot's `PeerCredentials` so the observer's peer
  comparison is load-bearing (mismatch and absent cases included). Positive Linux
  authentication, the real worker image and the container are host gates, never claimed.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No consume transaction, storage layout, migration, route, event, installation or head (steps
  (e)–(f)); the evidence is an inert value that the service preseals and re-verifies in its own
  writer; a reply proves nothing beyond one connection at one moment (`staged ≠ verified`); the
  boot ID is a process label; nothing imports `app.api`/`app.static`/`app.server`; no GUI.
