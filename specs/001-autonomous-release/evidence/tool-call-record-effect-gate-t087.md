# Evidence — T087: the `ToolCall` record and the effect gate for a tool call

- Date: 2026-09-18
- Task: the Continuation's "the `ToolCall` record and effect gate for a tool call". data-model.md
  §4 `ToolCall`: attempt ref, tool/version, ordered artifact inputs, grant/approval, effect class,
  idempotency, state/result — a write-ahead intent whose side-effect uncertainty is retained;
  runtime.md tool-port row: the declared effect class is authoritative, an unknown external
  outcome is held; extension-ports.md: external and instance-critical effects require an explicit
  approval. `tool_call` is a locator kind (a ledger row keyed by its attempt), not a domain record.

## Frozen identities

```
8b1be2bfc58dfdf68d5d0e8a3759048036732538886234125f91e964b2a612d3  app/runtime/ledger.py
30c8f8ac916a322b77681b706513682cdb543573a99d45cc5dd462180c779ee3  app/runtime/extension_attempt_transport.py
aede2925dd96978d4573f64930ad4db24a4f5c00c35611dedfc6696cabf83491  app/tests/test_runtime_ledger.py
28abf141234a29c9aefad8a88aa9ca28a1ddc649d3c0cf2ea30faeafa771a80a  app/tests/test_extension_attempt_transport.py
```

(The `ledger.py` and `test_runtime_ledger.py` identities frozen in `run-trace-attempt-layer-t048.md`
and the `extension_attempt_transport.py` / `test_extension_attempt_transport.py` identities in
`worker-output-artifacts-t018-t087.md` are superseded.)

## What was built

- `app/runtime/ledger.py`: the table `runtime_tool_calls` — one row per attempt (`UNIQUE
  (vault_id, attempt_id)`, one per command, a foreign key to the attempt): tool id and version,
  the effect class, the ordered artifact inputs (canonical bytes with their digest), the state
  (`intent`, `succeeded`, `failed`, `unknown`), the sealed result reference, the approval
  reference, the command and the times; the DDL digest therefore changes (the ledger's
  single-version policy refuses a vault of the previous schema as a partial schema, as for every
  earlier DDL addition — recorded, not changed here). `ToolCallSpec` (its id is the attempt's
  deterministic tool-call identity; tool id and version grammars; the ports contract's effect
  classes, pinned equal to `port_contracts.EFFECT_CLASSES`; inputs bounded to the execute
  grammar's eight, pinned; an approval — an exact `action_approval` reference — required for an
  external or instance-critical effect and refused for any other). `record_tool_call` is
  replayable by command and idempotent for the same intent under any command; a different intent
  for the attempt is refused; an unknown attempt is a `KeyError`. `settle_tool_call`: `succeeded`
  carries its result and nothing else does; from `intent` or `unknown` only (a final outcome
  never changes; `unknown` may still settle); replayable. `tool_calls_for_attempt` reads. At
  startup, an orphaned `intent` of a terminal attempt settles from the attempt's own terminal
  outcome: `succeeded` with the accepted result, `failed` for a failed, denied or timed-out
  attempt, `unknown` only for an unknown or cancelled one.
- `app/runtime/extension_attempt_transport.py`: `build(..., ledger=, effect_approval_ref=)`;
  the effect gate from the mirror's effect class — an external or instance-critical effect
  requires an `action_approval` reference and a read carries none (a query never carries one);
  `APPROVAL_EFFECTS` is the ledger's set. With a ledger bound, a tool call's intent (the named
  tool, the mirror's effect class, the declared inputs, the approval) is recorded after the
  connection stands and before the request frame leaves (a recording fault is a vouched
  non-send); after the reply it settles `succeeded` with the sealed result or `failed`; a vouched
  non-send from the exchange settles `failed` (the call never ran); any other fault — a typed
  transport error or anything else out of the exchange — settles `unknown` before it propagates,
  so a call never stays an intent on a terminal attempt in-process; a settlement fault raises
  `transport_invalid` (control must not claim a result whose call it cannot account for; the
  sealed result is then not re-linked — open).

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (0 MUST, 6 SHOULD, 5 NIT); nine probes over the real socket and the
ledger's recovery paths. Verified clean: the ordering (intent after connect, before the frame;
a recording failure inserts no row and is `definitely_not_sent`); `succeeded iff result_ref`;
final never changes; `unknown` re-settleable; the intent visible to the worker before the send
over the real socket; the table surviving a real reopen; the two effect vocabularies equal to
the ports contract's by value; `LOCATOR_KINDS` already carrying `tool_call`. Closures, RED-first:

1. SHOULD — a non-transport exception out of the exchange left the call `intent` on a terminal
   attempt until the next startup → every exception settles `unknown` before propagating; pinned.
2. SHOULD — startup settled every orphaned intent of a terminal attempt as `unknown`, even for
   an attempt that terminated succeeded with a sealed result → settled from the attempt's own
   terminal outcome; pinned for succeeded (with the result) and failed.
3. SHOULD — a vouched non-send settled `unknown` although the call definitely never ran →
   `failed`; pinned.
4. SHOULD — the gate persisted nothing it gated on → the approval reference is a column of the
   row, required by the spec for an approval effect and refused otherwise; its existence, scope,
   expiry and binding to this call are not verified (open); the gate is reachable today only
   through a mirror override (both tools are read-effect) — a correct shape, stated.
5. SHOULD — two effect vocabularies unpinned (the T047 in-memory tool boundary keeps
   `read/write/external/irreversible`) → the ledger's sets pinned to the ports contract; the row's
   effect class stated as the mirror's claim until ToolDefinition records exist; consulting the
   in-memory boundary instead of the mirror stays open.
6. SHOULD — docs → tasks.md and this evidence.
7. NIT — an identical intent under a new command is idempotent, not refused (the message was
   wrong). 8. NIT — the unreachable settlement arms removed and the closure stated. 9. NIT — the
   settlement-fault case documented as open. 10. NIT — a no-op line dropped; docstrings added;
   the input bound pinned to the grammar's. 11. NIT (recorded) — the ledger's single-version
   digest policy refuses a vault of an earlier schema as partial; no migration path exists.

## Verification

- TDD: RED retained — no `tool_call_identity`, no `ledger=` at build; GREEN after the table, the
  spec, the commands, the read, the startup settlement and the transport's intent/settlement/gate
  (three adjustments on the way: a missing `uuid` import, the test's reopen rebuilding the ledger
  over the same files, a second served connection for the non-send case); the review's RED tests
  failed for their stated reasons (`intent` after a `TypeError`; `unknown` for a succeeded
  attempt at startup; the identical intent refused; no `approval_ref`).
- Tests: ledger **+5**, transport **+4**; covering (ledger, transport) **81**; (messages, execute,
  checkpoints, run trace, budgets) **178**; (probe, probe messages) **97**; (dispatch, runs API,
  settlement, budget dispatch, run cancel, worker dispatch, response capture) **208 passed, 1
  failed** in one process — `test_runs_api.py::test_a_gated_run_waits_for_the_owner…` answered
  503 on run creation in that combination and passes alone and paired with each candidate
  predecessor; the full regression below is the authority. Ruff: no new findings (the ledger's
  18 pre-existing).
- Full regression: **6304 passed, 2 skipped** (Linux-only), 369 subtests, 16m10s; the gated-run test
  passed in the standard order, so the covering failure is an order-dependent interaction of that
  combination (not reproduced in any pair), recorded here and not chased in this slice.

## Boundaries kept

- The effect class is the mirror's claim; the approval is recorded, not verified; no tool
  arguments; no external tool exists, so the gate is a shape; the T047 in-memory tool boundary
  is not consulted (open); no model, tool or paid call beyond the in-process readings.
