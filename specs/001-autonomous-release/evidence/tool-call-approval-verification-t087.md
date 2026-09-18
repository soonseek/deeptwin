# Evidence — T087: the approval's verification for a tool call

- Date: 2026-09-19
- Task: the Continuation's "the approval's verification" (T087). The effect gate
  (`tool-call-record-effect-gate-t087.md`) required an `action_approval` reference for an
  external or instance-critical effect and recorded it, verifying nothing about it. ports
  contract: external and instance-critical effects require an explicit approval; data-model.md
  `ActionApproval` authorises a material external action; the approvals service
  (`app/services/run_approvals.py`) is the only producer of decisions and records one per
  (run, gate node, scope) against a gate request the ledger holds.

## Frozen identities

```
31207edd9700730a619121161cc5aea359f15c2f1ffd937e3becbda7f9559a49  app/runtime/extension_attempt_transport.py
1e23839c832a9c1795fe72ca7314f8a6146d4c7c1ba47b00adaafc561f423e83  app/runtime/ledger.py
17630396da00dd313073f11869aaabfb35cf7c138cc219d0be93f6505e893705  app/tests/test_extension_attempt_transport.py
```

(The `extension_attempt_transport.py` and `test_extension_attempt_transport.py` identities frozen
in `output-bytes-reservation-t087.md` and the `ledger.py` identity frozen in
`tool-call-record-effect-gate-t087.md` are superseded.)

## What was built

- `app/runtime/extension_attempt_transport.py`: `tool_approval_scope(tool_id, version)` — the
  gate scope an approval of one tool call names: `tool:` and the uuid5 of the canonical (tool
  id, version) pair, delimiter-proof and fixed-length, so every id and version the execute
  grammar admits fits the gate scope grammar (pinned: a build-metadata version, a 64-character
  id, `a:b`/`1` against `a`/`b:1`). `build(..., approvals=)` takes the exact
  `PersistentRunApprovals` over the same domain store, required together with an approval
  reference and refused without one. `_verify_effect_approval` runs in the call after the
  fence and deadline checks and before the channel is resolved, the connection opens or the
  ToolCall intent is recorded: the approvals service's `lookup` for (run, node, scope) —
  which verifies the owner's authorship, version 1 only and the run/node/scope binding — must
  return a decision that is `approved` and whose reference equals the one named (kind, id,
  version, digest); anything else is refused as `transport_invalid`, a service fault as
  `transport_unavailable`, both `definitely_not_sent`.
- `app/runtime/ledger.py`: the `ToolCallSpec` docstring says what is verified where, and that
  no expiry exists on a decision.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (0 MUST, 5 SHOULD, NITs); probes over the real socket and the
real approvals service. Verified clean: the ordering (refused before the channel, the
connection and the intent row; no served connection, no ToolCall row); `EntityRef` equality
over all four fields; nothing escapes the verification as an unknown outcome (the service's
closed errors only). Closures, RED-first:

1. SHOULD — the docstrings called the refusal a "vouched non-send", but the dispatcher records
   every transport failure after the send intent as an unknown outcome (`may_have_started`,
   one attempt, the budget spent) — pre-existing, admitted in the module → stated in the
   docstring; the recorded state pinned (`outcome_unknown`, `may_have_started`); honouring
   `definitely_not_sent` after the intent is a separate slice (open).
2. SHOULD — the docstring claimed "the run's node asks for it", but no production path asks the
   ledger for this gate under the tool-calling node (the scheduler asks only under
   `human_gate` nodes, under their own ids); the test asks explicitly → stated as open wiring.
3. SHOULD — one decision admits every execution of the node, loop iterations included, for an
   irreversible effect (the scheduler refuses a `human_gate` inside a loop for this reason; a
   tool node inside a loop is admitted) → stated as open (refuse at compile, or bind the
   execution).
4. SHOULD — the scope `tool:{id}:{version}` failed the gate grammar for a version with build
   metadata or a long id, refusing the transport at build → the uuid5 scope; pinned.
5. SHOULD — "a decision never expires" was the slice's own claim; no expiry is recorded, so
   none is checked → stated in both docstrings; runtime.md's stale approvals stay open.
6. NIT — a later version of the genuine id and an approval of the same node in another run
   pinned as refused; `_subject` naming.
7. NIT (recorded) — `app_subject` reconciles the ledger the lifespan already reconciled
   (harmless, all zeros); the private `_domain` identity check mirrors the service's own.

## Verification

- TDD: RED retained — no `tool_approval_scope`, no `approvals=` at build; GREEN after the scope,
  the build rule and the verification (three fixture adjustments on the way: the owner's
  session root must live outside the slot's pair root, whose group children inherit on macOS;
  the initializer creates only its last path segment; a missing import); the review's RED test
  (the scope's shape) failed for its stated reason.
- Tests: transport **+1** (the verification over the real factory and the real socket: two
  build refusals, a rejected decision, another node's approval, a forged digest, another run's
  approval, a later version, then the approved call whose intent carries the verified
  reference) and the gate test adjusted; transport **41**; (transport, ledger, approvals,
  dispatcher) **124**. Ruff: no new findings (the ledger's 18 pre-existing).
- Full regression: **6336 passed, 2 skipped** (Linux-only), 369 subtests, 16m01s.

## Boundaries kept

- The effect class is still the mirror's claim (the ToolDefinition-backed gate stays open; the
  in-memory tool boundary keeps a four-class vocabulary against the ports' seven); no gate
  request is made by any production node; no expiry; no model, tool or paid call.
