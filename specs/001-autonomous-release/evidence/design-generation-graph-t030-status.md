# T027/T028/T030 — design-generation and graph-contract slice status

Date: 2026-09-12
Status: implemented with passing focused suites; **T027/T028/T030 stay open pending a
recorded independent re-audit of the graph-compiler fixes**

## What exists

The Codex sessions ending 2026-09-09 01:54 KST implemented, in the shared worktree
(snapshot commit `e2723b2`):

- `app/domain/graph_schema.py` + `app/runtime/graph.py`: closed graph schema, structural
  validation (producers, artifact-slot matching, approval gates, routers with exact enum
  arm coverage, joins, single bounded loops, observation edges without execution
  reachability), `CompilationAuthority` external-authority binding, deterministic
  compiled plans, and public functional / structural-diversity projections.
- `app/services/design.py` + `app/generation_profiles.py`: work-model confirmation →
  lens decisions → functional candidate generation boundary with immutable confirmed
  targets and decision/graph job separation.
- Focused suites `test_graph_contract.py`, `test_design_generation.py`,
  `test_work_model_confirmation.py`: 88 tests, all passing on 2026-09-12.

## Audit context

During implementation an in-session independent audit reported four graph-compiler
defect classes: graph self-asserted authority, execution-contract loss in compiled
output, router bypass, and false diversity (renamed-identifier duplicates). The session
ended immediately after fixing the last of these (structural duplicate detection via the
ID-invariant projection in `app/services/design.py`). The audit's full report was not
preserved as an evidence file.

Each named defect class maps to at least one committed passing test:

| Defect class | Regression tests |
|---|---|
| Self-asserted authority | `compiler_requires_external_authority_and_rejects_graph_self_claims` |
| Execution-contract loss | `compiled_graph_preserves_typed_execution_contract_not_only_an_opaque_digest`, `multiformat_and_schema_bound_artifacts_survive_compile` |
| Router bypass | `router_cannot_activate_a_target_outside_its_exact_enum_control_arms`, `router_requires_exact_enum_branch_coverage_with_typed_conditions` |
| False diversity | `structural_projection_is_semantic_id_invariant_and_condition_format_sensitive`, `structural_projection_changes_on_real_axes_not_graph_names_or_decision_refs`, `fixed_three_template_substitution_and_duplicate_functional_graphs_are_rejected`, `candidate_projection_exposes_real_structural_axes_not_names_or_coordinates` |

## Verification

```text
python -m pytest -q app/tests/test_graph_contract.py app/tests/test_design_generation.py \
    app/tests/test_work_model_confirmation.py
88 passed

python -m pytest -q app/tests deploy/tests   (full shared regression, 2026-09-12)
2,922 passed, 2 skipped, 369 subtests passed
```

## Frozen content identities (SHA-256)

```text
ebc7caa7e8c8665ac442d3b408d90d2bb4fd505b7b41d59eec65f693ec6eab11  app/runtime/graph.py
0e037ed5f95b4791cc7c57baad699bb707ffeb5dbb522fcb60aef00515808fd5  app/domain/graph_schema.py
61548fe166473a9003a258c8f838a1630ae3ac842cc7345320f719089c02cdcb  app/services/design.py
76d132c71d64e03c723a914e6f66e027e9fb02c79aced8bbe9eee9f10368b6f2  app/generation_profiles.py
e1260ea09c169d4c34d309bd118a5feb6d2d58a7522e7fcde21553230c23a205  app/tests/test_graph_contract.py
ed6998ff8e33fbcd86d7ac8c18bb5fd6c189b8933b8d68b43a12050b2ba7bc22  app/tests/test_design_generation.py
3a37df0de87af83cb0eb44f235d2cbfa723b526ab238c3dd596898db88d57c5e  app/tests/test_work_model_confirmation.py
```

## Open

Because the original audit report was not preserved, passing tests demonstrate the four
named classes are covered but cannot prove every individual finding was addressed. A
fresh independent adversarial re-audit of `app/runtime/graph.py` and
`app/services/design.py` should run before T027/T028 close. T030 additionally still
requires the live confirmation→lens→generation pipeline against a real provider path,
which does not exist yet. No release credit is claimed beyond the recorded suites.
