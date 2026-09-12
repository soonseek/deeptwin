# T027/T028/T030 — graph-compiler adversarial re-audit and remediation

Date: 2026-09-12
Verdict of the fresh audit: **REJECT** (2×P1, 3×P2, 1×P3). All five actionable findings
are now fixed and reproduced-closed; **T027/T028/T030 stay open** for the live pipeline.

## Method

An independent adversarial auditor (separate agent, no write access) reviewed
`app/runtime/graph.py`, `app/domain/graph_schema.py`, `app/services/design.py` and
`app/generation_profiles.py` against the runtime contract and the four defect classes the
2026-09-08 in-session audit had claimed closed. It wrote executable probes and reproduced
five defects plus one nonblocking tension. This session re-ran every probe, confirmed each,
fixed the code, added a committed regression test per finding, and re-ran the probes to
confirm closure (probe4b 4/4, probe5 10/10, probe6 1/1).

## Findings and fixes

| ID | Sev | Defect | Fix |
|----|-----|--------|-----|
| F1 | P1 | `structural_diversity_projection` leaked the raw, un-aliased router `decision_fact` into `evaluation_placement`, so a candidate that was byte-for-byte another with the sole router fact renamed projected as "different" — a regression of the renamed-graph duplicate class. | `evaluation_placement` now emits the fact-aliased router config (aliased `decision_fact`, `allowed_values`); join/human_gate/handler configs carry no fact/id per schema and stay as-is. |
| F2 | P1 | Fact aliases were assigned by lexical order of arbitrary fact names, so a consistent bijective rename that inverted sort order changed condition signatures — false diversity with no router needed. | Fact aliases are now ordered by each fact's structural usage (fact-agnostic base node signatures plus self-marked expression position), never by name. A name tiebreak applies only between facts with identical usage, which are interchangeable and leave the projection invariant. |
| F3 | P2 | `dependency_shape` was a flat edge multiset that could not distinguish non-isomorphic topologies over identically-signatured nodes (a 3-deep chain vs a 1→2 fan), so genuinely different candidates were rejected as duplicates. | Dependency endpoints now use a one-round neighbourhood refinement (each node's aliased signature plus the sorted multiset of its incident edges' kind/direction/neighbour-base-signature/semantics), so chain and fan differ. |
| F4 | P2 | Loop-exit validation compared the frozen edge condition (tuples) to the thawed controller termination (lists), so any bounded loop whose termination used a list-bearing expression (`in`/`and`/`or`) was rejected even with a byte-identical exit. | The comparison is now `canonical_json(exit_condition) != canonical_json(termination)` over both thawed forms. |
| F5 | P2 | `accept_design_decision` checked `type(item) is LensDecision` but never verified the registry issuer token, so a reconstructed decision with a fabricated token, bundle id and content hash flowed through to an accepted candidate. | `LensRegistry.vouches_for(decision)` exposes the per-instance issuer-token check; `accept_design_decision` now requires a vouching `registry` and rejects any decision it did not issue. |
| F6 | P3 | `any_success` join tie-break (`branch_id_lexical`) is semantically meaningful but references node IDs that the projection correctly erases, so an ID swap changes runtime tie order while projecting identically. | Not changed. Documented design tension; capturing branch-order rename-invariantly needs a separate signature axis. Not release-blocking. |

The fact-ordering and refinement changes preserve the existing invariants: ID renames still
project identically, condition-format and real-axis changes still differ, and identical
graphs still collapse to one shape (no new false diversity introduced — the refinement only
adds discriminating power).

## Regression tests (committed)

`app/tests/test_design_generation.py`:
`test_projection_is_invariant_under_router_decision_fact_rename` (F1),
`test_projection_is_invariant_under_order_inverting_fact_rename` (F2),
`test_projection_distinguishes_chain_from_fan_topology` (F3),
`test_bounded_loop_accepts_every_closed_termination_expression` (F4, parametrized over
eq/in/and/not), `test_accept_design_decision_rejects_a_forged_lens_decision` (F5).

## Verification

```text
python -m pytest -q app/tests/test_graph_contract.py app/tests/test_design_generation.py \
    app/tests/test_work_model_confirmation.py app/tests/test_lens_registry.py
122 passed

auditor probes re-run after the fix: probe4b 4/4, probe5 10/10, probe6 1/1 (F1-F5 closed)

python -m pytest -q app/tests deploy/tests   (full shared regression, 2026-09-12)
2,956 passed, 2 skipped, 369 subtests passed, 1 known Starlette/AnyIO deprecation warning

ruff check (changed files) and git diff --check: PASS
```

## Frozen content identities (SHA-256)

```text
21f7893126ced3964006d2d99b17cfcbc9fc1cdc0023c082ef075ed29134c5f2  app/runtime/graph.py
5c40b90e85560f0c592b1ac51ef8eca421055ce8cbecdb4ee74c6cb4eed68a11  app/services/design.py
a70917d3545eaf1d9081dbb4cd4f183f322e3fccc0213d94be0d8dd89b4a81db  app/services/lenses.py
9b995a22fd9cff13439c9993fd5eab91128ddaa6a20f61f19a20b443a96d4657  app/tests/test_design_generation.py
```

## Still open

The audit covered the structural projection, compiler and decision boundary only. T030's
live confirmation → lens → generation pipeline against a real provider, and F6's tie-break
axis, remain open. No release credit is claimed beyond the recorded suites.
