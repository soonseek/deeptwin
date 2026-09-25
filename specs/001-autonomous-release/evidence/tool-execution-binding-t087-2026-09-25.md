# Evidence — T087: per-execution approval binding and the per-tool input declaration

- Date: 2026-09-25
- Status: **landed (two slices), T087 not closed.** Offline only; no model, tool or paid call; no
  live test run.
- Task: the two items the T087 entry listed as remaining and owned here: "per-execution approval
  binding" (`tool-call-approval-verification-t087.md` SHOULD 3: one decision admitted every
  execution of the node, loop iterations and retries included) and "the ports contract's per-tool
  input count/role binding" (extension-ports.md §3.9 `T-tool`: the core ToolDefinition's closed
  `ToolArtifactInputContractV1`; `worker-artifact-input-leg-t018-t087.md` SHOULD 5).

## Frozen identities

```
076277aedb67fccdb0e34a7fa034436527df62541f9b0f995543c056fda2dd5d  app/extensions/tool_input_contracts.py
fda22adc5dfba3697478160fd37e53b86aea8773cc976b5230f3452def1f5e92  app/runtime/extension_attempt_transport.py
f538907623f97ba00b993c49038d0ebf86851fdbf475505781e1da12da32fdbb  app/runtime/ledger.py
86c22f9c5851a023f37ea2c27fbf74239c0a9a3734484647346a261f299f1c53  app/services/run_approvals.py
02ac141ba0d7b27fd019d6c6d6efeaf86843d141a1c1558d30d5ee031f625ecb  app/workers/extension_probe.py
b4a9a91dd843970cf0f3b75679001d9b7df11e3b85fce6dc72030ab720e53194  app/tests/test_tool_execution_binding.py
5a47544de38a261ef88582c69d79ee296d9a0d015f30511041be69bb3e8c9b2b  app/tests/test_extension_attempt_transport.py
991b4d1c3a952e3f5d6920d12c23dd5958e27a83eed111f7370877690139ce06  specs/001-autonomous-release/contracts/extension-worker-probe.md
```

(These supersede the identities of the same files frozen in earlier T087 evidence.)

## What landed

### 1. Per-execution approval binding

- `app/services/run_approvals.py`: a second, versioned decision record. `run-approval-command-v2` /
  `run-approval-v2` carry the gate's `(run_id, node_id, approval_scope, decision)` **plus** the
  execution they authorize as the ledger names it: `execution_id` (the node visit; the
  scheduler's deterministic `execution_identity(run, node, loop_index)`), `execution_node_id` and
  `attempt_no` (1..`MAX_ATTEMPTS_PER_EXECUTION`, pinned equal to the ledger's). Identity:
  `execution_approval_identity(...)`, uuid5 of canonical JSON under its own domain
  (`deeptwin-run-approval-v2`), so it never collides with a v1 identity. It is recordable only
  against a gate request the ledger holds (same rule as v1). An exact replay returns the same
  receipt; the same identity with another command or decision conflicts. `lookup` (v1) returns only
  v1 records; `lookup_execution(...)` returns only v2 records; `resolve(ref)` returns the decision an
  exact reference names (either version), checking that its identity matches its own content.
  **v1 stays readable** (the human gate's passage and the scheduler still consult it) **and is
  refused for dispatch**, because it names no execution.
- `app/runtime/extension_attempt_transport.py`: an external-family tool binding (the ports' X
  family, from the compiled ToolDefinition) is admitted again, but only under a v2 decision:
  - at build: the named reference must resolve to an **approved v2** decision under the compiled
    gate and the tool's derived scope; otherwise it is refused with
    `external effects unavailable: an execution-bound approval is required` (the v1, rejected,
    forged-digest and unknown references all get this refusal);
  - at the call, after the window/compiled-context checks and **before the channel, the
    connection and the ToolCall intent**: `lookup_execution` for the request's run, the compiled
    gate and scope, **the ledger's execution id and node for this request, and the ledger's
    attempt number for this attempt** must return that exact approved reference. Anything else is
    `transport_invalid` / `definitely_not_sent` (a service fault `transport_unavailable`). So an
    approval of attempt 1 of visit A never authorizes visit B (another loop round), another node's
    execution, another run's execution, or a retry attempt 2 of visit A; a retry needs its own
    decision, which authorizes that attempt alone.
  - the verified reference is written into the ToolCall intent (`approval_ref`).
- `app/runtime/ledger.py` (`record_tool_call`): one approval is used by one attempt's call. The
  same attempt replaying the same intent (under any command) stays idempotent; the same approval
  on another attempt's call is refused (`LedgerError`). No DDL change (query over the existing
  `approval_kind/approval_id` columns), so the ledger schema digest is unchanged.

### 2. Per-tool input count/role binding

- `app/extensions/tool_input_contracts.py` (pure, no I/O): `ToolArtifactInputContract`, the ports'
  closed `ToolArtifactInputContractV1` (`{mode:none}` or `{mode:bounded, min_items, max_items ≤ 32,
  role, allowed_media_types (sorted unique non-empty), selector_policy}`) with `as_dict()` giving
  the ports object; `check_tool_inputs(contract, [(role, media, selector)…])` raises
  `ToolInputMismatch` with one closed code: `missing_input`, `extra_input`, `wrong_role`,
  `wrong_media`, `selector_mismatch`.
- Control (`TOOL_INPUT_CONTRACTS` in the transport) and the worker (`TOOL_INPUT_CONTRACTS` in
  `extension_probe.py`) each declare the table; for `text_profile` 1.0.0 and `text_normalize` 1.0.0
  it is `{bounded, 1..1, document_source, [text/plain], forbidden}`. The two tables are pinned equal,
  and equal in keys to the worker's `describe_tools` entries.
- The dispatcher (the transport) refuses a mismatching call at build (the code in the message; no
  attempt, reservation or row) and re-checks before the connection (`transport_mismatch`,
  `definitely_not_sent`). The worker re-checks in `_tool_contract_admits` before reading a byte and
  in the operation (`failed`/`validation_failed`, zero tool calls).
- Agreement with the ports schema validator: for every case the check and
  `port_schema_generator._validate_tool_contract` accept or refuse the same inputs.

## Observed counts

- New: `app/tests/test_tool_execution_binding.py` **26 passed** (13.8 s).
- Focused: `test_extension_attempt_transport.py test_compiled_tool_dispatch.py test_run_approvals.py
  test_run_approval_api.py test_extension_execute.py test_tool_execution_binding.py` **170 passed**.
- Covering set (58 files: `test_*extension*`, `test_tool*`, `test_worker*`, `test_*gate*`,
  `test_runtime*`, `test_graph*`, `test_run*`, `test_scheduler*`, `test_domain_events`,
  `test_compiled_tool_dispatch`, `test_deployment_consume`, `test_owner_decisions`,
  `test_promotion_approvals`, `test_stage_observer`), `-k "not live"`:
  baseline before the change **2688 passed, 3 skipped, 18 deselected**; after, with the new file,
  **2714 passed, 3 skipped, 18 deselected** (2688 + 26).
- Ruff: clean on every changed Python file except the ledger's 4 pre-existing findings (none new).
- One existing pin changed: `test_extension_attempt_transport.py` asserted the old tuple shape
  of `TOOL_INPUT_CONTRACTS`; it now asserts the declared contract and control/worker equality.
- TDD note: the new tests were written before the implementation ran, but a failing (RED) run was
  not retained; each approval-binding test asserts both the refusal code and that no connection
  was attempted, and the positive case asserts the connection is reached, so a missing check
  would fail it.

## Still open

- A production graph that binds a tool gate (no production node asks for a tool gate).
- The scheduler/gate passage consuming v2 decisions (it still reads v1 per run/gate/scope); no
  HTTP route or UI records a v2 decision (the approvals API still builds v1 commands).
- The atomic approval-use / ToolCall / budget / send claim in one transaction (the approval is
  verified before the intent and single-use is enforced at the intent, not in the send-intent
  commit); binding the approval to the exact inputs/arguments; approval expiry.
- The compiled ToolDefinition record (`TrustedToolDefinition`) carrying the input declaration (the
  tables are code-owned mirrors); selectors on the execute wire (it names none, so every selector
  is null); the wire's 8-input bound against the ports' 32; duplicate-ref checks (the wire carries
  digests, not refs).
- No external-effect tool exists in the worker table; the approval gate is reached only by a test
  mirror override. Every other port remains open.
