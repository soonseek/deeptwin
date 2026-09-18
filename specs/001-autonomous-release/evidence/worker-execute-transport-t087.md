# Evidence — T087/T018 slice: the worker's first real operation and the real attempt transport

- Date: 2026-09-18
- Task: Continuation "the core semantic-port dependencies (T087 worker-side operation registry /
  T018 worker message) so a real transport can replace the injected one" — the item named in
  `resumption-plan.md` after the T040 dispatch slice (`scheduler-attempt-dispatch-t040.md`).
  Contract: `contracts/extension-worker-probe.md` amended (§1 decision, §2 registry, new §2b
  execute messages, §3 mode selection, §4 caps, §6 gates).

## Frozen identities

```
8fe6f935d26868e9c1fe2b7631e64bcd03a42fa0662998134d081ca86bd5d1fb  app/workers/extension_execute_messages.py
fcb0292149b8436a51063e17b1b15fb5f22e272996371eb7bed17fc35bb4eb40  app/workers/extension_probe.py
25aa46bba35fca3055e272ba068a13b4f8fd1eb35537d57af63772f46b1fd368  app/runtime/extension_attempt_transport.py
f3ce9979f989e332506a50607dc69be70505d3b77eb67bca3cf0f76ae38b32a3  app/runtime/node_attempts.py
643ad605bbe6fae332aedd417beec45e4b1172da460393f6235579d87b339820  app/tests/test_extension_execute_messages.py
b29be5e88164325d39bc16223afec8e670c4b5d9a8090b4da19b20a7b2ae3920  app/tests/test_extension_execute.py
551840516cc0449ca3020ca9bf075d81a314224ad4b8feb7762d485d34d3bb65  app/tests/test_extension_attempt_transport.py
7b4e3b31bfbfd81064ded77b13a929a497f5c33bd5237809027da42af3bca1ea  app/tests/test_scheduler_attempt_dispatch.py
bd5423eefb8547087fd4a4fb89d23950917e13b6673f07597b49ef009281189a  specs/001-autonomous-release/contracts/extension-worker-probe.md
```

## What was built

- `app/workers/extension_execute_messages.py` (new, pure): `extension-execute-v1` request
  (attempt, execution, operation ∈ tool-port-v1, envelope/profile `EntityRef`s, `remaining_ms`
  1..30000, a 32-byte nonce; ≤ 2048 B) and `extension-execute-result-v1` reply (the ledger's
  result vocabulary mirrored and pinned equal by test; the seven exact usage counters iff final;
  `output` iff succeeded, for `status` the probe reply's own shape; the ledger's invariant that an
  unknown outcome claims no known terminal; ≤ 4096 B, depth 5); `peek_schema` for mode selection.
  Rides on the channel's existing `extension-request-v1` / `extension-result-v1` types: the type
  tuples are part of the authenticated channel identity and stay unchanged.
- `app/workers/extension_probe.py`: the private router is now over the code-owned operation
  table `_OPERATIONS = {"status": …}` (no registration surface; `registered_operations` is its
  exact key set, `["status"]`); `status` answers from an actual `read_current` reading; an
  unregistered operation is the typed refusal `failed` / `validation_failed` with final zero
  usage. `_serve` selects the connection mode by the first frame's exact schema: execute mode
  answers exactly one request and closes; a probe connection refuses a later execute frame or any
  reply schema on a request frame.
- `app/runtime/extension_attempt_transport.py` (new): `ExtensionAttemptTransport.build(
  domain_store, instance_id, slot_number, operation, attempt_ms)`; one call `(permit, request,
  window)` binds the permit to the request and to its consumed window, bounds the exchange by the
  window and the attempt budget (an exhausted window never connects), connects through the
  authenticated extension client, writes one request (message id = the send-intent command id,
  fresh nonce, `remaining_ms` from the effective deadline), reads one reply, verifies type,
  correlation, schema, attempt, operation and nonce, rechecks the fences, and maps the reply.
  Control does not trust the worker's `status` usage (the one real counter is measured
  control-side; any other claim is a mismatch). A succeeded output is sealed control-side as an
  `artifact` record whose id derives from the send command (`sealed_artifact_identity`), parent =
  the envelope. Failures raise `ExtensionTransportError(code, dispatch_effect)` — `definitely_not_sent`
  before any write, the broker's own effect for an interrupted write, `outcome_unknown` otherwise.
- `app/runtime/node_attempts.py`: the transport now receives the consumed one-shot window
  (`consume_dispatch_permit_window` before the exchange), and the ledger observation is built
  inside the fault boundary so a result the ledger refuses is recorded as `outcome_unknown`,
  never stranded.
- Adapted pins: the probe/stage-observer/consume suites now expect `["status"]`.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 5 SHOULD, 4 NIT), thirteen scratch probes. Verified clean:
the only production consumer of `registered_operations` (the stage observer's reply validation)
admits `["status"]`; the worker package touches nothing outside its allowed imports; the execute
reply leaks nothing the probe reply does not; every failure class of the transport is mapped;
the grammar refuses nonce, correlation, id, sortedness and overflow faults; sizes are comfortable
(actual status reply 832 B of 4096). Closures, RED-first:

1. MUST — a reply passing the execute grammar (`outcome_unknown` claiming a known remote
   terminal) was refused by the ledger's observation rule outside the fault boundary and stranded
   the attempt in `send_intent` with the reservation dispatched → the grammar mirrors the ledger's
   invariant (plus: a non-succeeded outcome cannot observe `succeeded`) and the dispatcher builds
   the observation inside the boundary (recorded as unknown).
2. MUST — the slice contradicted the probe contract as written → `contracts/extension-worker-probe.md`
   amended: §1 records the decision to multiplex on the existing types; §2 describes the code-owned
   registry; new §2b closes the execute grammar and its invariants; §3 states mode selection by the
   first frame; §4 adds the execute caps; §6 narrows the unclaimed gate to the registry beyond
   `status`; the worker module docstring corrected.
3. SHOULD — the consumed window was discarded and the transport ran on its own 2000 ms clock → the
   window travels with the permit; the exchange deadline is the minimum of the window and the
   attempt budget; an exhausted window never connects (`transport_deadline`, definitely not sent).
4. SHOULD — the worker's self-reported usage finalized the budget verbatim (an inflated claim
   produced an overage) → for `status` control computes the exact expected counters; any other
   claim is `transport_mismatch` (recorded as unknown; the reservation retained).
5. SHOULD — the sealed artifact used a random id (an orphan after a crash between seal and accept
   was unfindable) → the id derives from the send-intent command (`sealed_artifact_identity`).
6. SHOULD — a connect refusal after permit consumption is recorded as `outcome_unknown` although
   nothing was sent → kept (no ledger path reopens a post-intent attempt; the retry rule requires
   `send_intent_at_ms IS NULL`), and the error now carries the `dispatch_effect` control can vouch
   for, so a later slice can record the transport observation.
7. SHOULD — `deadline_at_ms` was an absolute ledger-clock value the worker cannot interpret →
   replaced by `remaining_ms` (1..30000) from the effective deadline; §2b says so.
8. NIT — a close fault after a reply in hand no longer masks the reply. 9. NIT — reply schemas on
   a request frame are pinned as refusals. 10–11. NIT — sizes and message-id reuse verified, no change.

## Verification

- TDD: RED retained — `ImportError` for both new modules (three suites erroring); GREEN after the
  codec, the worker execute mode, the transport and the dispatcher change; three test-side
  adaptations (the `channel` fixture re-export, a probe-mode execute is a rule violation that
  closes with the closed error, the status output needs a reservation above 100 B); the review's
  RED tests (23 failing) failed for their stated reasons before the closures.
- Tests: execute messages 20 (vocabulary pin, request/reply round trips, refusals, canonicality,
  peek); worker execute 7 (status from an actual reading and close, typed refusal, probe reports
  the registry, malformed and reply-schema frames close, closed registry); transport 8 (status over
  the real socket with the sealed output as the node result and the reservation finalized from the
  measured bytes, unregistered operation admitted as failed, no reachable worker → unknown, build
  refusals, exhausted window never connects, connect refusal is definitely not sent, inflated usage
  refused); scheduler dispatch +1 (a result the ledger cannot observe is unknown).
- Covering (the above plus probe, stage observer, probe messages, consume, consume API, graph
  execution, settlement, budget dispatch): **266 passed**. Ruff: no new findings (the worker and
  dispatcher modules 0/0), the new modules and tests clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No provider, model, effort or paid call; `status` is the only registered operation (a real
  metadata reading, not a placeholder); `invoke_tool`, `describe_tools`, `cancel` and every
  model-bearing port remain T087; the artifact stream, positive Linux peer authentication, the
  real image and the container/socket runtime remain host gates. The worker never touches the
  store. Transport evidence is still not semantic success: admission happens only through
  `accept_result_and_settle`. Not wired: recording the transport observation for a definitely
  unsent failure (the effect is carried, not yet journaled); the attempt result still lands as an
  `artifact` of the `status` output, not a graph-typed artifact (T042/T087).
