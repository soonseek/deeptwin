# Evidence — Task 25 slice 2a: extension handshake continuation

- Date: 2026-09-18
- Task: Task 25 (worker-private probe channel; prerequisite for Task 24), slice 2a —
  T018-foundation transport. Plan entry: `resumption-plan.md` "### Task 25", bullet 2a and
  the macOS test-honesty paragraph. Contract: `contracts/extension-worker-probe.md` §1/§4/§6.
  Intent: the 2026-09-16 proposal §2 (fresh requester boot authentication).

## Frozen identities

```
be809c61fa8219320f893c4bd9c5359612b98d14e8501afddcd063cd059dc48c  app/workers/broker.py
b85bdfd4d8826b4eeb7de27ff5e40574e8b9df2befa89341c68a67d097702f9a  app/workers/extension_channel.py
60a1557948566a44d479311c69262a8307a1ccba277cf4a56f68577357240c28  app/tests/test_extension_handshake.py
609ccf2a9facfd71b404546c5670a84b482831b588697324708f67807502fa19  app/tests/test_extension_channel.py
```

## What was built

- `app/workers/broker.py`:
  - Profile constants `EXTENSION_PROTOCOL_ID`, `EXTENSION_REQUESTER_MESSAGE_TYPES`,
    `EXTENSION_RESPONDER_MESSAGE_TYPES`, `EXTENSION_HANDSHAKE_PACKET_BYTES = 4096` — the
    single source `extension_channel.py` now imports (the slot's protocol identity is
    cross-asserted equal).
  - `_server_continue(...)`: the one responder continuation after a hello was read
    (complete expected-hello reconstruction and HMAC proof over both boot IDs, spec digest,
    phase and the requester challenge; fresh responder challenge; finish verification;
    acknowledgement; session). `_server_handshake_impl` now reads the hello and delegates to
    it — its body is line-for-line the previous one; public `server_handshake` /
    `client_handshake` keep byte-identical semantics (caps, error classes, `challenge_factory`,
    single `deadline.bounded`). `_client_handshake_impl` gained a keyword-only private
    `max_packet_bytes` (default unchanged).
  - `_extension_server_handshake_impl(sock, spec, secret, *, responder_boot_id, deadline,
    challenge_factory=None, verify_peer=True)`: full-profile check
    (`_require_extension_profile`: protocol id, both message-type tuples, frame 65536,
    in-flight 1, queue 16, operation 30000 ms), socket validation, peer verification for the
    responder BEFORE any read, hello read under the 4096 B cap, requester boot ID taken from
    the hello and validated (grammar, ≠ responder), then the shared continuation with the
    4096 B cap; every rejection after the hello was read is `outcome_unknown`, as on the
    public path. `_extension_client_handshake_impl` = profile check + client continuation
    under the cap.
  - Seamless wrappers `_extension_server_handshake` / `_extension_client_handshake`: no
    `verify_peer`/`challenge_factory`; documented as leaving socket cleanup and effect
    classification to the private extension listener/connector (slice 2c), unlike the
    public wrappers.

## Review (independent, adversarial) and closures

Verdict: ACCEPT; folded in RED-first before commit:

1. SHOULD — the defining vector (a genuine proof for boot A relabelled as boot B) was not
   tested → added to the mutation list; refused by the proof compare.
2. SHOULD — the replay test passed for a weaker reason (stale finish with a zero proof;
   an in-thread assert pytest downgrades to a warning) → the stale finish now carries a
   genuine proof over a different responder challenge, the observed responder phase is
   boxed and asserted from the main thread, and the thread is asserted finished.
3. SHOULD — post-read rejections (bad boot id grammar, equal boots) raised
   `definitely_not_sent` where the public path reports `outcome_unknown` → normalised; every
   mutated-hello case asserts `outcome_unknown`.
4. SHOULD — seamless wrappers not parallel to the public ones (no socket close / effect
   normalisation) → intentional per the proposal (2c owns cleanup), now stated in their
   docstrings.
5. NIT — dead `type(hello) is not dict` guard removed (`read_packet` returns dicts).
6. NIT — partial profile check → the whole profile.
7. NIT — fail-closed test needlessly skipped on Linux (a socketpair peer is never the slot
   uid there either) → runs everywhere.
8. NIT — thread hygiene → every started thread is joined and asserted finished.
- Reviewer-verified: the label is bound by the HMAC, not by self-comparison; peer
  verification precedes the hello read; the fresh responder challenge is minted only after
  the hello proof passes and the finish proof covers it; cross-wrapper use has no downgrade
  (same proof context); `read_packet` refuses an announced size over the cap before reading
  the body (header-only probe, 0 ms); maximal-grammar hello 809 B / finish 879 B under the
  4096 B cap; `max_packet_bytes` is keyword-only after `*` and every caller passes keywords.

## Verification

- TDD: RED retained — `AttributeError: module 'app.workers.broker' has no attribute
  '_extension_server_handshake_impl'`; review closures RED first
  (`assert 'definitely_not_sent' == 'outcome_unknown'` ×5), then GREEN.
- Covering: **234 passed** (handshake 17, channel 46, and every existing handshake consumer
  suite: worker response capture, credential routes, artifact stream transport, worker
  listener, worker coordinator, server API v1). Ruff clean; `broker.py` has no findings.
- Test honesty on this macOS host: the seamless wrappers are asserted to fail closed with
  `PeerCredentialError` before any read/write; the continuation is exercised over real
  socketpairs through the existing `verify_peer=False` implementation seam — handshake logic,
  never positive Linux authentication, which stays a qualified-Linux gate.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No listener, fence, mount check, probe service, observer or admission (slices 2b–3
  remain); no positive Linux authentication claim; the actual worker image and
  container/socket runtime are Docker/colima host authority; no GUI.
