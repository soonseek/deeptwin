# Evidence — the transport's vouched dispatch effect, journaled by the dispatcher (T040/T087)

- Date: 2026-09-19
- Task: the Continuation's "honouring a vouched non-send after the send intent in the
  dispatcher". Finding of the approval slice (`tool-call-approval-verification-t087.md`): the
  extension transport raises a refusal before any byte leaves as `definitely_not_sent`, but the
  dispatcher recorded every transport fault after the send intent as a bare unknown outcome —
  the journal and the dispatch status said nothing of what the transport vouched.
- The ledger's trust model, kept: a committed send intent is possibly sent (`reserve_attempt`
  admits a next attempt only when no intent was committed, or after an observed terminal in the
  owner's recovery); a transport's vouched non-send is evidence for recovery, never a retry
  proof (runtime.md is silent on a non-send after an intent; the worker dispatch records such
  observations the same way). Turning a vouched non-send into a free retry would be a canon
  change and stays open.

## Frozen identities

```
3563c160e9d854c6a67f62da0e8a5f5269873df959565fc4e5e74d4d239eabf2  app/runtime/node_attempts.py
be5a3ee64eefd7aeeebcc00af3c00c764e2741072c20ec0161373768cdcdab23  app/runtime/extension_attempt_transport.py
84fd2873cfe2a9e84ee308b4d817419467426f79d6e1a39839007d03edd2160c  app/tests/test_scheduler_attempt_dispatch.py
```

(The `node_attempts.py` and `test_scheduler_attempt_dispatch.py` identities frozen in
`output-bytes-reservation-t087.md` and the `extension_attempt_transport.py` identity frozen in
`tool-call-approval-verification-t087.md` are superseded.)

## What was built

- `app/runtime/node_attempts.py`: when the transport raises, the dispatcher reads the fault's
  `dispatch_effect` (the extension transport's own error shape; anything else is ignored) and,
  for `definitely_not_sent` or `may_have_started`, records the attempt's transport observation
  (the effect, no response fields — the worker dispatch's shape) before accepting the unknown
  outcome; a failure to record is suppressed (the entry is evidence, never the outcome). The
  ledger's acceptance admits the result through its recoverable branch, so the attempt ends as
  before — terminal `outcome_unknown`, `may_have_started`, the reservation retained unknown —
  and the dispatch status now reports the vouched effect.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (1 MUST, 2 SHOULD, NITs); probes over the ledger's crash and
replay paths. Verified clean: no path records the observation twice in-process (a replay
returns no permit before the transport runs); a transport that recorded `transport_accepted`
itself and then vouched is a suppressed conflict, still accepted unknown; the reservation
settles `unknown` through the recoverable branch; the pending permits stay clean; the journal
payload is identities, the effect and nulls (no message); a lying transport gains no retry
proof. Closures, RED-first:

1. MUST — the vouch was read outside the guard: an unhashable or raising `dispatch_effect`
   escaped the "a fault is an unknown outcome" contract and stranded the attempt in
   `send_intent` with the gate open → the read and the membership check sit inside the
   suppress, and only a string effect counts; pinned for both shapes.
2. SHOULD — the suppress path unpinned → pinned (a ledger fault while recording: the unknown
   outcome still accepted, the status reports only the unknown outcome). A `CorruptLedger`
   there is suppressed like any other fault — the worker dispatch inhibits dispatch on any
   failure of its own recording; parity on that point stays open (recorded).
3. SHOULD — the crash window unpinned → pinned: a crash between the journal write and the
   acceptance leaves the attempt `send_intent`, gate closed, recovery pending, the dispatch
   status `blocked` (the worker dispatch's own shape); the restart reconciles it as unknown.
4. NIT — the test's canary check aimed at the result observations; it reads the journal row.
5. NIT — the module docstring still said no worker-side transport existed; corrected, and the
   transport's docstring now says the vouched effect is journaled.

## Verification

- TDD: RED retained — the dispatch status reported only the unknown outcome; GREEN after the
  journaled observation; the review's RED tests failed for the stated reason (the stranded
  attempt) and the two pins passed on first run. Tests: dispatcher **+5** (both vouched
  effects, a plain fault, two unreadable vouches, the suppress path and the crash window);
  dispatcher **21**; (transport, ledger, worker dispatch, runs API) **157**. Ruff: clean on the
  changed files.
- Full regression: **6341 passed, 2 skipped** (Linux-only), 369 subtests, 16m18s.

## Boundaries kept

- No change to the ledger's trust model, the retry proofs or the budget settlement; no model,
  tool or paid call.
