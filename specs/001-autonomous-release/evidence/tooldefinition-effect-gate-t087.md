# Evidence — T087: the ToolDefinition-backed effect gate

- Date: 2026-09-19 (built), 2026-09-22 (review closures)
- Task: the Continuation's "the ToolDefinition-backed gate (T087: the compilation authority's
  trusted tool definition carries the effect class, a binding to an approval-requiring tool
  must name its approval scope, the transport takes the class from the binding and refuses a
  disagreeing mirror)". runtime.md §6: the ToolDefinition's effect class is authoritative;
  extension-ports.md: the external family requires an explicit approval; runtime.md §4: approval
  edges from human gates; the approvals service records one decision per (run, gate node, scope).

## Frozen identities

```
c3bff8684dd6ee55c8f7ca5e2a7579723bcf3a971c2823c455e74913eeb682f4  app/runtime/gates.py
59d9c3a6f3739a011baff45bf8ee928de3ed6e5d43082578b1f95848f6bdca4c  app/runtime/graph.py
304b7986c5405461730ecef452ecea8edb906c53c0ff2360bcc9c121a878d3c1  app/runtime/extension_attempt_transport.py
d5ce32c462d9edb4d95bf817a85b905a51c73d61dd9574436693ff205ca9122f  app/tests/test_graph_contract.py
37abef812afa1456f118976ffbcd7d18cde79be5ef255371319b83e47cf49216  app/tests/test_extension_attempt_transport.py
648427c0bd03af38009eb42285c48cac59a00de278922615ef7986b2b98522d4  app/tests/test_design_generation.py
```

(The `graph.py`, `extension_attempt_transport.py` and the two test identities were also
carried, between the build and the closures, by the parallel orchestration's tasks 27–51
manifests under `.superpowers/sdd/resumption-plan/`; the identities above supersede those and
the ones frozen in `vouched-transport-effect-journal.md`.)

## What was built

- `app/runtime/gates.py`: `tool_approval_scope(tool_id, version)` — `tool-` and the uuid5 of
  the canonical (tool id, version) pair: delimiter-proof, fixed-length and lowercase, so every
  id and version fits the gate grammar, the graph schema's local identifiers and the
  authority's scope grammar. One home, shared by the compiled graph and the transport.
- `app/runtime/graph.py`: `TrustedToolDefinition` carries the tool's identity (id in the
  worker's execute identifier grammar, version in the execute version grammar) and its effect
  class in the ports contract's vocabulary; two trusted definitions of one tool may not
  disagree on the class; an external-family definition's approval scope is trusted by
  derivation, never listed by hand; a node bound to such a tool must require the tool's scope
  (the structure already binds every required scope to an approval edge from a human gate);
  `CompiledGraph.tool_effects` states, per binding on a node, the tool, its class and the gate
  supplying its scope.
- `app/runtime/extension_attempt_transport.py`: `build(..., effect_class=, approval_gate_node_id=)`
  — the compiled binding's class is authoritative and a disagreeing worker mirror is refused;
  the gate id is validated as a node id at build; the decision is looked up under the named
  gate (the graph's) when given, else under the calling node.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (0 MUST, 5 SHOULD, 6 NIT); probes over the compile gate, the loop
structure, the scheduler and the transport. Verified sound: `tool_binding_ids` exist only on
agent config and are unique; a required scope with no gate path is refused by structure so
`tool_effects` cannot miss its gate; a tool-bound node inside a loop with a gate outside is
unreachable by structure (an approval edge is triggering); the scheduler asks the ledger for
the tool scope under the gate node and the tool node cannot run before the decision; the
transport's disagreement check precedes the approval rule; `CompiledGraph` equality and the
digests are unaffected. Closures, RED-first:

1. SHOULD — the authority's tool-id grammar was wider than the worker's execute identifier (a
   graph could vouch for a tool the transport cannot name) → the execute grammar; pinned.
2. SHOULD — the approval gate id was validated by length only → the gates module's local
   identifier, checked before the approvals authority; pinned (refused shapes; a well-formed
   gate then meets the missing authority).
3. SHOULD — two trusted definitions of one tool with different classes were admitted → refused;
   pinned (the same class twice stays admitted).
4. SHOULD — no scheduler test ran the gated graph → recorded as open (the reviewer's probe over
   `gated_tool_graph` showed awaiting the gate, the decision recorded under the gate, then the
   writer running); the transport test asks the ledger for the gate by hand.
5. SHOULD — stale text: the ledger's `ToolCallSpec` docstring still calls the class the mirror's
   claim (true only when no definition is bound); the request-node fallback is a dead path in
   production (the scheduler asks under gates only) — both recorded here.
6. NIT (recorded) — the authority digest changes for every authority carrying tools, so a run
   sealed before this change is unresumable (pre-release); the composer binding a transport per
   `tool_effects` fact is trusted to pass the right gate — the scheduler's activation ordering
   is the backstop; the positional 6-tuple authority is easy to misorder (a swapped id/version
   fails the id grammar now that it is the execute identifier); the loop refusal is a side
   effect of triggering approval edges, not a stated rule (open pin); the transport still
   re-exports the scope helper.

## Verification

- TDD: RED retained — no scope helper in gates, the authority refusing a 6-tuple, no
  `effect_class` at build; GREEN after the definition, the compile gate, `tool_effects` and the
  transport's build rules (one grammar collision on the way: the `tool:` scope failed the graph
  schema's lowercase local identifier — the `tool-` shape); the review's RED tests failed for
  their stated reasons (the wide grammar admitted; the length-only gate; the disagreeing
  definitions admitted; one first draft of the gate test passed for the wrong reason and was
  rewritten to reach the check).
- Tests: graph contract **+3**, transport **+3**; (graph contract, transport, design
  generation) **134** before the last closure, transport **48** after it; (design generation,
  transport, graph contract, graph execution, runs API, scheduler dispatch) **207** at build.
  Ruff: clean on the changed files.
- Full regression: the merged tree's third full run, **9,280 passed, 3 failed (timing/order-dependent, each
  passing alone), 0 errors** (`merged-tree-reconciliation-2026-09-22.md`).

## Boundaries kept

- No production node asks for a tool gate yet (a graph must bind it); one decision admits every
  execution of the node; no expiry; no model, tool or paid call.
