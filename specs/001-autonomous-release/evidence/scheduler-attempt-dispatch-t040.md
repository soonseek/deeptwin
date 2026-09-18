# Evidence — T040 slice 4: attempt dispatch through the scheduler

- Date: 2026-09-18
- Task: T040 (Continuation) "worker/attempt dispatch through the scheduler" — the last open item
  of the T040 line in `tasks.md`; the Task 6 boundary (transport evidence is not semantic
  success; no unknown-use reservation is released) and the Task 5 note (no default effort, no
  invented provider binding) are preserved. Builds on the settlement slice
  (`runtime-result-settlement-t040.md`).

## Frozen identities

```
fabf81b6d2abb2a14a8a295f6c860d3cd74a1804f20dfe8cb80f3d3cac77aafe  app/runtime/node_attempts.py
6109ec0e6019d2e900bdf394e76a341e9973e69b3fc33fc155200f10db64508f  app/runtime/scheduler.py
80dc3a73e7572792c46fcbdb53a5dff43c53988f8e339b311d2844b8fe626daa  app/tests/test_scheduler_attempt_dispatch.py
```

## What was built

- `app/runtime/node_attempts.py` (new): `AttemptBinding` (exact envelope / runtime-profile /
  budget-policy references, deadline, lease, budget counters, principal and grant — caller-supplied
  context, not a production dispatcher), `AttemptDispatchRequest` (identities and references the
  transport learns; never bytes), `AttemptTransportResult` (the ledger's result vocabulary, usage
  iff final), `VisitAttempt` (a one-shot capability: one callable and its accepted result),
  `NodeAttemptDispatcher.build(ledger, budget_book, owner, bindings, transport)` and the
  identities `attempt_identity(run, node, loop_index, attempt_index)` / `reservation_identity`.
  One visit: `reserve_attempt` on a deterministic command id and idempotency key → the run's
  frozen budget session → `commit_budgeted_send_intent` bound to the reserve snapshot's revision
  → the code-owned transport under the one-shot permit → `accept_result_and_settle`. The node's
  result is the accepted `succeeded` reference and nothing else. Exact replay of the send (a
  may-have-started attempt) resolves only through `lookup_committed_result` and never re-sends;
  a transport fault, an inexact result or a claimed result that does not resolve in the domain
  is admitted as `outcome_unknown` (reservation retained as unknown usage); the unconsumed
  permit is discarded whenever the acceptance did not commit. The only continuation is the
  ledger's own proof that an earlier attempt of the visit was definitely never sent (a crash
  before the send-intent barrier, quarantined at startup): the next attempt number of the same
  execution is reserved, bounded to four.
- `app/runtime/scheduler.py`: `NodeContext.attempt` (None unless the node is bound);
  `build_scheduler(..., attempts=None)` admits only an exact dispatcher over the run's ledger
  binding agent nodes; a bound node's handler receives the capability and its returned
  reference must equal the committed result or the visit fails.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (no MUST). The reviewer verified with eleven scratch probes that no
path yields a node result except the accepted classification, that a crash after the acceptance
but before the superstep checkpoint replays reserve/send and resolves through the committed
result with the transport never asked again, that a crash before the send commits the send for
real once (definitely not sent), that a crash after the send fails closed, that loop iterations
reserve distinct attempts each with `attempt_no` 1 per execution, and that `NodeContext`'s new
default breaks no assertion. Closures, RED-first:

1. SHOULD — a crash between the reserve and the send followed by a restart left the run dead
   (startup recovery closed the gate; every later visit failed at the revision CAS although the
   ledger itself admits `attempt_no` 2 for a proven-unsent predecessor) → the dispatcher continues
   with the next attempt of the same execution when the ledger proves the earlier one definitely
   not sent (bounded to four); the restart test renamed to say recovery quarantines a sent
   attempt.
2. SHOULD — a well-typed `succeeded` result whose reference does not resolve raised before the
   acceptance transaction and left the attempt in `send_intent` with a live permit → the claimed
   reference is verified in the transport boundary and an unresolvable claim is `outcome_unknown`.
3. SHOULD — the permit was never discarded when the acceptance did not commit →
   `discard_dispatch_permit` in a `finally` (harmless after the accepted result's revocation).
4. SHOULD/NIT — `NodeContext` said "never clients" while the capability reached the dispatcher →
   the capability collapsed to one callable and the docstrings state the code-owned trust
   boundary.
5. NIT — the send-intent revision now comes from the reserve snapshot with the reason stated.
6. NIT — a `None` permit for deadline/lease refusals is now checked for the definitely-unsent
   proof before it is treated as a replay.
7. NIT — noted: `commit_budgeted_send_intent` does not check the grant's expiry (only the policy
   gate does at read time); an expired grant in a long-lived binding would surface as a transport
   fault → `outcome_unknown`, not a definite not-sent refusal.
8. NIT — the recovery assertion tightened to `outcome_unknown`. 9. NIT — the unreachable
   "succeeded without a reference" arm dropped.

## Verification

- TDD: RED retained — `ImportError: cannot import name 'node_attempts'`; GREEN after the module
  and the scheduler seam (one restart assertion aligned with startup recovery: the dead owner of a
  may-have-started send is quarantined as `outcome_unknown`); the review's three RED tests failed
  for their stated reasons (permit still pending, `node_failed` on the restart-before-send run,
  `None` terminal outcome for the phantom reference).
- Tests (9): the bound visit dispatches one attempt with visit-derived identities and admits the
  accepted result (permit and bounded request seen once; second run replays without a send);
  restart after the send never re-sends and recovery quarantines the attempt with the permit
  discarded; unknown outcome fails the visit and retains the reservation; a transport fault or a
  loose result is `outcome_unknown`; a failed result is admitted and fails the visit; only the
  accepted result can be the node result (skip / swap / dispatch twice); build refuses wrong
  dispatchers and bindings and the identities are deterministic; restart before the send reserves
  the next unsent attempt and dispatches once; a success with an unresolvable reference is an
  unknown outcome.
- Covering (dispatch, graph execution, checkpoints, settlement, budget dispatch): **69 passed**
  before the review, **117 passed** after the closures. Ruff clean on the three files.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No worker message, provider, model, effort or paid call: the transport is an injected callable
  and the only transports today are the tests' in-process fakes (the worker-side operation
  registry is T087/T018; frozen turns and adapters are T042). No raw graph state in the outcome
  (field set unchanged). Retry after a sent attempt stays unimplemented. Checkpoints were unbound to attempts at this slice; the binding landed later the same day
  (`checkpoint-attempt-binding-t040.md`). The live container/socket/worker run remains the host gate.
