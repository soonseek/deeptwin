# Evidence — T087: the `output_bytes` reservation from the tool's stated output bound

- Date: 2026-09-18
- Task: the Continuation's "the `output_bytes` reservation from the tool's bound" (probe contract
  §6 open item: "an under-reserved attempt settles as an overrun that blocks the budget session
  — the caller, not the transport, sizes it today"). runtime.md: a spend cap is the owner's
  decision, never a stranded attempt; budgets: an accounting overrun blocks the whole session.

## Frozen identities

```
0a8089100d221745ead81f3d4c95fae1e16ed8fa9e2c0ef015394313b52e65e9  app/runtime/extension_attempt_transport.py
85b346690dc979e93468fdfe994f016396ee357cd1fd81656b71337d47ccb6f0  app/runtime/node_attempts.py
6891e373876ff984e1398ce2537f03c00b8bd45eda5eee8efb345f9c33cf3276  app/tests/test_extension_attempt_transport.py
6bd01b3de45af688b2f5b3ba2e7b42bcc4a455896b69f5e82f207c3a15ab78c2  app/tests/test_scheduler_attempt_dispatch.py
49777151b531f32f7f734c36e99941a9ff72e9d7fb51c08c81d9eb60666f85a7  app/tests/test_runtime_budget_dispatch.py
```

(The `extension_attempt_transport.py` and `test_extension_attempt_transport.py` identities frozen
in `tool-call-record-effect-gate-t087.md`, and the `node_attempts.py`,
`test_scheduler_attempt_dispatch.py` and `test_runtime_budget_dispatch.py` identities frozen in
earlier T040/T087 evidence, are superseded.)

## What was built

- `app/runtime/extension_attempt_transport.py`: `ExtensionAttemptTransport.output_bytes_bound`
  — the most output bytes control will measure for one attempt of the bound operation: the reply
  frame's ceiling (4 096 bytes; the grammar accepts a reply only when its raw bytes equal their
  canonical encoding within the ceiling, and the output is a closed sub-object of it, so the
  re-encoding control measures never grows past it) plus, for a tool call, the tool's stated
  growth over the declared inputs, never over the leg's ceiling (`TOOL_OUTPUT_BOUNDS`:
  `text_profile` none; `text_normalize` 3× under NFC — the widest UTF-8 growth of any code
  point is exactly 3.0, the U+1D15E–U+1D1C0 family, verified by brute force over the whole
  code space in review). The artifact part is enforced, not measured: `_result` refuses a
  received batch over it as `transport_mismatch`, so an inflating worker is an unknown outcome
  and never an accounting overrun.
- `app/runtime/node_attempts.py`: `NodeAttemptDispatcher.build` reads a transport's stated
  bound when the attribute is statically present (a present bound that fails to read
  propagates — it never turns the gate off); it must be an exact non-negative count, and every
  binding must reserve at least it, or the build is refused. A callable stating no bound is
  unchanged (the in-process fakes).
- Tests: the shared subject's policy takes `max_output_bytes` (default unchanged, 1 000); the
  transport tests run on a subject whose cap admits the bound, and their bindings reserve
  `transport.output_bytes_bound`.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (1 MUST, 3 SHOULD, 4 NIT); probes over the real socket and the
budget book. Verified clean: the bound's arithmetic for every operation; the under-reservation
pin (a bare callable reserving one byte settles `overage`, `blocked_reason = reservation_overrun`,
`usage_finality = known_overrun`, the next reservation refused); finalized rows charge the actual
usage, so reserving up to 1 MiB per attempt never exhausts a session; `text_profile`'s empty
output contract refuses any reverse-leg batch; no production caller and no mock passes a
transport with the attribute. Closures, RED-first:

1. MUST — the bound was measured, not enforced: a worker returning 10 000 bytes for a 5-byte
   input (under the 1 MiB leg ceiling) was admitted and settled as an overrun that blocked the
   session — exactly what the slice exists to prevent → `_result` refuses a received batch over
   the tool's artifact bound as a mismatch; pinned (the attempt is `outcome_unknown`, the
   reservation `unknown`, the session unblocked).
2. SHOULD — a policy cap under the bound was untested → pinned: the budget refuses before any
   attempt or reservation row exists and the session stays open (passed on first run: it pins
   existing behaviour the slice makes far more reachable).
3. SHOULD — the docstring gave an incidental reason for the reply-frame bound (the encoder's
   unescaped UTF-8) → the load-bearing fact is the grammar's canonical-equality check within the
   frame's ceiling; stated.
4. SHOULD — `getattr(..., None)` silently skipped the gate when a present property raised
   `AttributeError` (a future unset slot would turn the gate off without a trace) → static
   presence check, then a normal read that propagates; pinned.
5. NIT — a negative bound is a `ValueError` (was `TypeError`); bool and zero pinned (refused /
   admitted). 6. NIT — the 3× family named at the constant. 7. NIT — the test helper moved next
   to its peer. 8. NIT (recorded) — `test_runtime_budget_dispatch.py` carries a pre-existing
   import-order finding at HEAD, untouched.

## Verification

- TDD: RED retained — no `output_bytes_bound` on the transport; the dispatcher not refusing
  (four tests, each failing for its stated reason; one collection-time error was corrected to
  fail inside the tests before proceeding); GREEN after the property and the gate; the review's
  RED tests failed for their stated reasons (the inflated output admitted; the negative bound's
  error type). One expectation was corrected on the way: an under-reserved attempt itself
  succeeds — the overrun blocks the session for every later reservation, not that attempt.
- Tests: transport **+5**, dispatcher **+1** (extended); (transport, dispatcher, budget dispatch)
  **74**; (runs API, settlement, run cancel) **41**. Ruff: no new findings.
- Full regression: **6310 passed, 2 skipped** (Linux-only), 369 subtests, 15m58s.

## Boundaries kept

- The bound is the mirror's (`TOOL_OUTPUT_BOUNDS`), enforced against what control received;
  the ToolDefinition-backed table, the worker-owned scratch for larger outputs and every other
  probe-contract open item stay open. No model, tool or paid call.
