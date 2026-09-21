# Evidence — Task51: the owned shared gateway prerequisite (G1–G10)

- Date: 2026-09-22
- Task: the plan's Task 51 (`.superpowers/sdd/resumption-plan/task-51-plan.md`, adopted contract
  `contracts/provider-owned-shared-gateway.md`, normative snapshot
  `contracts/provider-semantic/shared-gateway-owned-design-r1.md`): execute real owned gateway
  dialogues through a fixed shared vault/send ingress without losing original deadlines,
  cancellation observations or cleanup. Delivered by this loop in three reviewed stages (A: the
  inert profile and the generic owner, G1–G4; B: the shared frame/fragment engines and the
  ingress, G5–G6; C: the owned send dialogue and linearized control, G7–G10), each RED→GREEN
  with an independent adversarial review folded in, then one full regression and one commit —
  the plan's "one review unit" was kept as one commit, not as one review. The 12 owned paths
  are exactly the plan's; the one extra edit outside them is one test seam moved in
  `app/tests/test_credential_gateway_service.py` (the strict-decode seam now patches the one
  grammar's decoder). No broker, schema, wire/record identity, deployment topology, DB, app
  composition or HTTP/UI route changed.

## Frozen identities

```
d16759b473eba3526e1b923c236179f44288e6c13212cf7dcaa7eed7b2b02caf  app/workers/listener.py
196b40e870a8cd5784d508e9fe5cc2adc4ff7454c046269dc97472a06f03174f  app/workers/gateway_channel.py
71422fd4f7f1f7decacb0c7b02aab02374428d90fefb75220c365bb31d10b29a  app/workers/gateway_connection.py
d52395179e11eedc85c7d9ecf3b1cf8acc3eae843c8674f1bb02329715f1935a  app/workers/credential_channel.py
94f9977950d4c6f3fe7af5f11be6135ef10fa1e0de80bde014a4d31b05dafd35  app/workers/credential_gateway_service.py
00bfd49e84dca9cdcd2ff89c995810764d90660ecd6494cc8f7e2ba79ecb62ae  app/workers/provider_send_client.py
6dd7c51f07c108054c3cd6e97d23a656b680882239444d9179d954baf4da71f0  app/workers/provider_send_service.py
9ba6ab49fb8530714956100531a4132e3be330b8b9fdf583e7cf2aa9f4ec1d93  app/workers/provider_gateway_ingress.py
8cd18790637c8437fe1cd8da486ef271f3ddd4bf927fc0f4cd44b1dfde1f6b3e  app/tests/test_authenticated_gateway_connection.py
32b6bea80cdbdb269be466c7d3e62b62c1713cf26927ee3b8553cf4e346ff275  app/tests/test_provider_gateway_channel.py
ac04a6b7ed5e74dce629d62ceb68694cdf27ddb25d5c91558b896554bd101bf9  app/tests/test_provider_gateway_owned.py
3fc84e9cd8a465837d0765763c0d21c30cb3f043d78b151da25a07fd99ea9b86  app/tests/support/provider_gateway_harness.py
5d13c3e30747d2d003b243dac72a13226d748fccc45eeaf8e7a26d548f0534dd  app/tests/test_credential_gateway_service.py
```

## What was built

- `app/workers/gateway_channel.py` (new, G1): `PROFILE_ID = "provider-gateway-channel-v1"`; the
  pure `gateway_channel()` declaring the `cp-provider` pair root (responder 20103/20103, pair
  group 21101) and the `credential-gateway-v1` channel (control → provider, `worker.sock`,
  `credential_op`/`credential_result`, 65 536 / 1 / 16 / 30 000, endpoint 02710, socket 0660)
  from `CONTROL` and `IPC_ROOT`; no I/O, no override; pinned against the static service ids
  without production ever loading them.
- `app/workers/listener.py` (G2–G4): `AuthenticatedConnection` is factory-issued (constructor,
  copy and pickle refused), retains one `deadline` bounded by the operation cap before
  acquisition in both factories, takes the minimum of the supplied and retained ends on every
  read, write and poll; one nonblocking reader latch (`ListenerBusy` for a competitor, no byte
  consumed); `read_duplex(deadline, idle_timeout_ms)` polls only before a prefix byte and then
  finishes the frame under the deadline; the writer encodes under the codec's lock and writes
  the encoded bytes outside it, a failed write closing permanently; `close` detaches the finite
  set, shuts the socket down, attempts codec, socket and generation, raises the first cleanup
  failure; `_accept_transport` unwinds an unvalidated socket and restores the listening timeout;
  both factories unwind every acquired resource preserving the primary. A concurrent close
  mid-poll or mid-validation is a transport close, never a bare error.
- `app/workers/gateway_connection.py` (new, G5): the private `_RawConnection` adapter so the raw
  `(sock, codec)` pair and the issued owner run one engine.
- `app/workers/credential_channel.py` (G5): `_write_logical_connection` and
  `_read_logical_connection(..., first_frame, first_value)` — the one fragmentation grammar,
  the router's already-read pair reused, one decode per frame; the raw entries delegate;
  `CredentialGatewayClient.for_gateway(*, requester_boot_id, deadline_ms)` resolves the profile
  at call time and adapts listener faults at the engine boundary.
- `app/workers/credential_gateway_service.py` (G5): `serve_connection(owner)` (the owner's
  session digest and responder side checked), the already-read `_serve_logical` handoff, the raw
  `serve_one` through the adapter (one behaviour moved with the shared grammar and pinned: a
  non-strict reconstruction is refused before any reply).
- `app/workers/provider_gateway_ingress.py` (new, G6): the exact composition (one vault, the
  credential spec equal to the fixed spec), `serve_one` over the exact gateway listener,
  `serve_connection`, a serial nonblocking latch (a competing owner closed on rejection), the
  pinned guard order — 24 576 before the one decode, fragments to the credential grammar
  (credential-v2 or the closed legacy shapes; a fragmented prepare refused after assembly),
  16 384 before every plain arm, prepare to the send engine's already-read handoff — and the
  send service's unusable state mirrored.
- `app/workers/provider_send_service.py` (G6–G10): `_serve_dialogue(connection, start_frame,
  header)` over the connection surface, polling the owner in 10 ms idle slices beside the
  completion queue; `serve_connection(owner)`; `vault`; listener faults adapted.
- `app/workers/provider_send_client.py` (G7–G10): `for_gateway`, `abandon`; explicit serialized
  state (ready → committing | cancelling → closed) claimed under one bounded state lock; one
  writer lock; the commit thread the one reader (`read_duplex` polling); a one-shot cancellation
  slot the reader commits and a terminal close never replaces; concurrent cancels serialized by
  a bounded control lock, each with its own acknowledgement or the fixed terminal state; the
  ready-cancel arm reads its one acknowledgement and owns the final close, a cleanup failure
  surfacing as `ProviderSendCleanupAfterCancellation` with the exact observation retained; a
  cleanup-only failure after a validated observation reported with the observation's fields
  and `internal_failure`; the owned client's local failure mapping (deadline → `deadline_exceeded`,
  malformed → `integrity_failed`, unavailable → `dependency_unavailable`); the raw pair keeps
  its historical exceptions and private seams.

## Reviews (independent, adversarial) and closures

- Stage A: ACCEPT WITH CHANGES (1 MUST, 6 SHOULD). MUST — a concurrent close mid-poll leaked a
  bare `ValueError` from `select` → a transport close; pinned. SHOULD — a close racing the
  socket validation reported an endpoint violation → a transport close when closed; the
  generation-lease oracle was vacuous → the pair root's rotation; the codec unwind was never
  exercised → a failure injected after the codec is owned; a silent reader beside a writer and
  every close failure → pinned; `ListenerBusy` without consuming bytes → a competitor refused
  mid-prefix, the whole frame to the legitimate reader; the owner's own oversize/empty prefix
  branch → pinned. NIT — `codec_closed` honest when the codec's close failed.
- Stage B: ACCEPT WITH CHANGES (1 MUST, 7 SHOULD). MUST — a listener fault escaped
  `for_gateway` as a listener error → adapted to the gateway error at the engine boundary.
  SHOULD — the raw entry's moved behaviour documented and pinned; exact decode counts pinned
  (six for a four-fragment store, plus two for the snapshot); a canonical 24 576-byte request
  reaching the grammar and refused as ordinary (whitespace padding dropped); the legacy arms at
  16 384/16 385 and a plain prepare at 16 384/16 385 pinned; an oversized continuation refused
  before its decode; the second-dialogue race waits for the latch; the decoder seam dropped;
  the dead vault-error arm dropped; a `vault` property on the credential service.
- Stage C: **REJECT** (3 MUST, 5 SHOULD, 6 NIT), every finding folded RED first and the closure
  set re-reviewed. MUST — a losing `commit` (a duplicate, or one entering while a ready-cancel
  was blocked in its acknowledgement read — the runtime's dispatch/controller shape) tore down
  the in-flight winner because the state refusal sat inside commit's closing guard → the claim
  is a distinct branch: the loser is refused locally and touches nothing of the claimant, the
  claimant's exact acknowledgement and the gateway's removal of the pending exchange retained
  (pinned for both shapes); a failed cancel-frame write left a dead `cancelling` dialogue on the
  runtime's process-lifetime client ("already active" for ever) → any failure after the claim
  closes the dialogue and maps, the reused client starts its next dialogue (pinned); the
  blocked-exchange gate test was flaky (~1/10: a second cancel framed during the empty-body
  result stream is acknowledged after the client's deterministic terminal closure, a gateway
  post-delivery failure the design tolerates) → the assertion tolerates one post-delivery
  gateway failure and one-or-two exact acknowledgements, looped 20× green. SHOULD — `cancel`
  and `prepare`'s first deadline check now map every transport fault (an expired deadline is
  `deadline_exceeded` on every owned entry, never the broker's raw class; pinned); the cleanup
  catches accept any local exception kind so a `RuntimeError` from a close never erases a
  validated cancellation or observation (pinned for OSError and RuntimeError on the ready-cancel
  arm, the exchange path and abandon); the peer's malformed authenticated grammar is
  `integrity_failed` (pinned with a corrupted acknowledgement), as is a failed authentication;
  the plan's gaps pinned — the exchange-path cleanup failure retains status/body/phase/media,
  a body-phase blocked exchange is acknowledged `may_have_sent`, a cancel during the owned
  result stream is the terminal acknowledgement with the stream delivered whole, a real peer
  EOF (the gateway's cancel raising, closing with no acknowledgement) is never a claimed
  cancellation; the unjoinable-thread test joins the retained HTTP thread. NIT — the unread
  terminal flag dropped; `status()` reads the channel once; a `usable` property on the send
  service read by the ingress; the stale test comment and module docstring corrected.
- Stage C re-review of the closure set: **ACCEPT WITH CHANGES** (1 MUST, 3 SHOULD, 2 NIT), every
  closure re-probed and holding (M1 under four concurrent commits, M2 under a shut socket, M3
  30/30). MUST — the stream engine's wrapper (`ArtifactStreamError`, a bare RuntimeError)
  escaped the owned client unmapped: a chunk write's deadline during the body, a malformed
  result-stream frame → unwrapped to the broker's own category when the cause is a transport
  fault (`deadline_exceeded`), `integrity_failed` otherwise (both pinned RED first). SHOULD —
  the close was identity-blind: a stale caller's cleanup (a cancel whose frame failed after
  another thread abandoned its dialogue and the next send prepared a successor) detached the
  successor → the detach is bound to the caller's own channel (pinned RED first with the
  interleaving injected between the fault and the cleanup); the claim order was not the wire
  order: a cancel losing the state claim could still precede the commit frame, the gateway
  then answered the ready-cancel and the claim winner reported `dependency_unavailable` for a
  user-cancelled, never-sent request → both frames are written under their claim (lock order
  control → state → write; pinned RED first: the winner's frame leads and observes its own
  exchange); the raw pair's re-raise restored to the bare `raise` so its historical exception
  chaining is untouched. NIT (recorded, not changed) — three local refusals carry no closed
  failure class; at the deadline instant a pre-claim expiry closes under a live claimant whose
  read then reports `dependency_unavailable` rather than `deadline_exceeded`.

## Verification

- TDD: every stage RED first (the profile module absent; no `deadline`/`read_duplex`/issuance on
  the owner; the ingress module absent; the client's channel keyed on raw resources), GREEN
  after each implementation; two owner tests and one ingress test passed on the existing code
  and are reported as added coverage, not RED.
- Tests: `test_provider_gateway_channel.py` **3**, `test_authenticated_gateway_connection.py`
  **16**, `test_provider_gateway_owned.py` **40** (the stage C closures: fourteen RED first — the
  losing commit, the duplicate commit, the failed cancel write, the expired deadline, the
  RuntimeError cleanups, abandon, the malformed acknowledgement, the peer EOF, the usability
  fact, the body-stream deadline, the malformed result-stream frame, the stale caller, the
  claim/wire order — and the body-phase, owned result-stream and OSError-cleanup cases as added
  coverage; the module looped 12× and the concurrency cases 20–40× green, with one unexplained
  single failure of the claim/wire-order case observed while a killed earlier run was still
  exiting, not reproduced in 100+ runs since — recorded, not claimed fixed); the plan's final13 command on the held bytes:
  **437 passed, 1 failed** — `test_provider_semantic_owned_connection.py::…prepublication_failure…[deadline]`,
  the parallel orchestration's own intermittent case (it failed in the merged tree's third full
  run before this unit existed and passes alone; it does not touch the generic owner). The
  refactored engines' consumers: credential gateway service, send gateway, semantic vertical,
  owned connection, provider service **250** together. Ruff: clean on the new modules; the
  pre-existing findings of the modified modules untouched.
- Full regression on the frozen identities above: **9,341 passed, 1 failed, 2 skipped** (Linux-only),
  369 subtests, 1h22m. The one failure — `test_design_store.py::…resolves_its_owner_evidence…` —
  is a pre-existing hidden flake of that pin, not of this unit: one of its four tampered copies
  replaced the approver id's last hex digit with `"0"`, a no-op for one id in sixteen, so the
  refusal it pins could not be raised; reproduced alone (2 of 5 runs), fixed at cause (the digit
  replaced by one it is not; `71b440efd60018d7ea885f90a18b582b0a2517860da2b076f6a12aef02e4e527`),
  looped 12× green. The thirteen identities above were unchanged across the run.

## Boundaries kept

- No launcher, `create_app` registration, HTTP/browser route, environment test mode, root
  initializer or Compose mutation; no actual provisioning, bootstrap, semantic artifact
  admission, current binding, managed Codex, live provider or browser journey; the fixed
  factories expose no override (tests substitute only the module-local profile resolution
  into an owned temporary root). No model, tool or paid call.
