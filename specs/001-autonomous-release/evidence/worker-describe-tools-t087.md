# Evidence — T087: the worker's second operation, `describe_tools`

- Date: 2026-09-18
- Task: T087 (Continuation: "worker operations beyond `status`"). `describe_tools` is tool-port-v1's
  query of the tools a worker offers (extension-ports.md §3.2; terminal class Q, effect `read`,
  result artifact mode `("E","none")`; runtime.md tool-port row). The worker answers from its
  code-owned tool table — empty today — never from the port catalogue; control seals the
  answer as evidence and measures its usage itself. Contract amended:
  `contracts/extension-worker-probe.md` §2 (registry), §2b (grammar), §4 (depth), §6 (gates).

## Frozen identities

```
b1e430f24cacf0fdd6a22fca2de0f013d95a900b989a1eb796907bf980af8ad9  app/workers/extension_execute_messages.py
dee98a3ed8b08dc38582fcad387c3906814c6b2944c16656275c38626dbeab0e  app/workers/extension_probe.py
28604abde915ec3cd44a859fb5b967ac667a5fa81b3934ff11cc946624c25e2d  app/runtime/extension_attempt_transport.py
55e7d75f7510f73c51f13a22f703f7d4581375941c47b840e5cb52dc9a01caf6  app/tests/test_extension_execute_messages.py
414af4f6f945d34ad6188852dd64187ae6a8cd83065cdbab3170649a1e1d5d4f  app/tests/test_extension_execute.py
19bdf3515dfcd5284e20c10a4f6b7ed60d023ab793520c6590138ccd063912a6  app/tests/test_extension_attempt_transport.py
80fae5f83e9406a3698648655372e80fb05da642d3dc6b433e463a8bd54339ab  app/tests/test_extension_probe.py
f3dd0c75097a11ffd3a1d199fd420c2fb074e54592870f4ba90cefb82a599923  app/tests/test_stage_observer.py
f1d20f3ce450c8f9e18e26fef5db9d50856604c049e4e8508c3184bbe42b8595  app/tests/test_deployment_consume.py
c7b24094184aca29b393f3f959879b95478fca0268725caa1db7c7488cdc0d3c  specs/001-autonomous-release/contracts/extension-worker-probe.md
```

(The identities of these files frozen in `worker-execute-transport-t087.md` and the earlier probe
evidence are superseded.)

## What was built

- `app/workers/extension_execute_messages.py`: the reply's `output` grammar is selected by the
  reply's `operation` (`OUTPUT_OPERATIONS = {status, describe_tools}`): `status` keeps the probe
  shape; `describe_tools` is exactly `{tools: [{tool_id, version, argument_schema_ref,
  result_schema_ref, effect_class, artifact_roles}]}` after extension-ports.md §3.2 with the
  wire's narrower grammars stated in §2b (identifiers per §2, version text
  `[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}`, references four-field `EntityRef` shapes of any registered
  kind, effect class a member of the closed set, roles sorted unique ≤ 256, one entry per tool in
  identifier order, ≤ 8 entries and — the binding bound — ≤ 3072 canonical bytes so the 4096 B
  reply can always carry the table, checked where the table is validated). A success under
  `invoke_tool` or `cancel` is outside the grammar until its output is defined. Wire depth 5 → 6
  (a tool entry's reference objects at depth 5, their scalars at 6).
- `app/workers/extension_probe.py`: `_TOOLS` — the worker's code-owned tool table (fixed at
  import, empty until a real tool is implemented in the worker); `_describe_tools_operation`
  answers the whole table (the execute grammar carries no selection yet) with zero counters and
  control-measurable `output_bytes`; `_OPERATIONS` is `{status, describe_tools}`, so
  `registered_operations` is `["describe_tools", "status"]` everywhere.
- `app/runtime/extension_attempt_transport.py`: the read-class queries `_CONTROL_MEASURED =
  {status, describe_tools}` never have their usage trusted — any final claim other than the
  measured seven-tuple, and now a completed query claiming its usage unknown, is
  `transport_mismatch` → `outcome_unknown`.
- Pins updated in the probe, stage-observer and deployment-consume suites.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (0 MUST, 6 SHOULD, 4 NIT). The reviewer probed the grammar (status
shape under `describe_tools`, `tools` under `status`, a success under `invoke_tool`, duplicate or
unsorted ids and roles, uppercase ids, locator kinds, ref version 0, tuples, a forged parse — all
refused at encode and parse), the socket (a status-shape reply under a `describe_tools` transport
→ `transport_invalid` → `outcome_unknown`; a failed reply with non-zero bytes → mismatch), the
request-side depth (nothing new reaches the field validators; bounded by 2048 B) and the probe
consumers (the stage observer checks sorted/unique/subset and records; no golden bytes drift).
Closures, RED-first:

1. SHOULD — `MAX_TOOLS = 8` was not the real bound: four grammar-maximal entries (~1.2 KB each)
   validated but could not be encoded under the 4096 B cap, so over the socket the worker failed
   to answer (`outcome_unknown`) instead of refusing → the table is bounded by canonical bytes
   (`MAX_TOOLS_BYTES = 3072`) where it is validated; the RED test pins one maximal entry admitted,
   four refused at validation, and the roles' own bound (`MAX_ROLES`).
2. SHOULD — the wire's version text and identifier are narrower than the ports contract's
   `version-text`/`identifier` and §2b said "per §3.2" without saying so → §2b states both
   narrowings and the code comments name them.
3. SHOULD — "control measures the only real counter" was dodgeable: a succeeded `describe_tools`
   claiming `usage_finality: "unknown"` with no counters completed the run with an unknown budget
   row (pre-existing from the status slice, restated as a guarantee) → a completed read-class query
   claiming unknown usage is a mismatch (`outcome_unknown`); the RED socket test pins it; §2b says
   so.
4. SHOULD — §4 still said depth 5 and §2b's depth sentence was off by one → both corrected (root
   is 1; reference objects at 5, scalars at 6).
5. SHOULD — the trust boundary of the sealed table is stated here: the table is the worker's own
   claim, sealed verbatim as control's evidence record (an `artifact` descending from the
   envelope, as for `status`); a dangling reference fails the seal closed (`outcome_unknown`);
   `("E","none")` describes the port result's byte artifacts, not control's evidence record; no
   production consumer of the sealed content exists today, so the table authorises nothing.
6. SHOULD — `OUTPUT_OPERATIONS` and `_CONTROL_MEASURED` had to agree but were unpinned → pinned
   equal and ⊆ `OPERATIONS`.
7. NIT — stale docstrings (transport, grammar, worker, test) updated. 8. NIT — `tools` removed from
   `peek_schema`'s top-level set (it is nested). 9. NIT — the roles list has its own constant.
   10. NIT — table entries are deep-copied into the output.

Order-sensitive descriptor checks (`test_extension_probe.py`, `test_stage_observer.py`) fail when
the transport suite runs first in the same process and pass alone or reversed; the reviewer
reproduced the same on a scratch extraction of HEAD — pre-existing, not this slice; the covering
runs below use separate processes and the full regression runs the suites in their own order.

## Verification

- TDD: RED retained — `failed`/`validation_failed` for `describe_tools` over the socket, the
  grammar refusing `{tools: []}`, the pins at `["status"]`; GREEN after the grammar, the table,
  the router entry and the transport set (two adjustments on the way: the reference kind in the
  test fixture, the wire depth); the review's RED tests failed for their stated reasons
  (`MAX_TOOLS_BYTES` absent; the dodge completed the run).
- Tests: execute messages **+2**, execute **+1**, transport **+4**; covering (messages, execute,
  transport) **47**; (probe, probe messages) **97**; (stage observer, deployment consume) **48**.
  Ruff: clean on every changed Python file (two auto-fixed sorts).
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- The tool table is empty: no tool, no `invoke_tool`, no `cancel`, no operation input in the
  execute grammar (`requested_tool_ids` is not carried; the whole table is described, stated in
  §2), no model-bearing port; the worker never touches the store; no model, tool or paid call. The
  live container/socket/worker run stays the host gate.
