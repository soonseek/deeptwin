# Evidence — T058 active knowledge registry and policy compilation

- Date: 2026-09-13
- Task: T058 [US5] active conditional knowledge registry
  (authority/scope/time/conflict/revalidation) and prompt-derived policy
  compilation (FR-021/032; runtime.md §8; G-05).

## Frozen identities

```
4bc3d7428c6e871d56d017cc719d2364ba39909e3f66fe54342f6ace18eeae67  app/services/knowledge.py
661d64dfca3334513f59299fd4d38536ba999b842aae6d005af387ecb249e010  app/runtime/memory.py
0c38176f9d975e5bd42a8206a94a5517c3be3be964bf6d72758a336c7ccbc1aa  app/tests/test_knowledge.py
2431d7a643337efd0478d8a3834b1f0f7875abd5eb65113121ef32526bdd3dea  app/tests/test_memory_compilation.py
```

## What was built

- `app/services/knowledge.py` — ActiveKnowledge (canonical
  condition/action/exception + scope/purposes/effective time + the promoted
  lineage: `change_candidate` + `action_approval` + `validation_report` +
  behavior provenance). Registration refuses draft-store kinds
  (own_alternative/difference/hypothesis/inquiry/selector) in every ref
  field — draft stores are never operating memory. Retrieval filters scope,
  purpose, effective time and lifecycle, and reports each excluded
  scope-matching entry as an explicit (id, reason) gap. Conflicting
  authority in one scope must supersede explicitly (superseded entries are
  preserved); `declare_condition_change` suspends a scope into
  `revalidation_required` (excluded from retrieval) and
  `revalidate_knowledge` requires fresh validation/comparison evidence —
  past qualification is never permanent. Retirement is explicit, reasoned,
  and preserved. Registry is an issued immutable value with a monotone
  revision (storage owns single-writer transactions).
- `app/runtime/memory.py` — `compile_knowledge` compiles one *active*
  issued entry into exactly one of the five allowlisted targets
  (node_instructions, retrieval_rules, tool_restrictions, handoff_schemas,
  graph_gate_config); unknown targets refuse. Protected requirement classes
  (constitutional/safety/authority/final_human_approval/current_test) are
  never relaxed; ordinary removals (e.g. redundant_review) stay valid but
  require before/after criteria. H_phi/S_phi and current-alternative
  leakage are blocked as refs and as whitespace-normalized verbatim spans
  (G-05). Every compiled field carries its own behavior provenance.

## Verification

- TDD: both modules absent first (collection errors), then 12 tests green
  (7 registry + 5 compilation).
- `ruff check` clean (one RUF015 in a test fixed).
- Full regression `python -m pytest app/tests deploy/tests -q` —
  **3180 passed, 2 skipped, 369 subtests passed** (was 3168).

## Notes

- Remaining for US5: T059 growth firewall adversarial tests
  (cross-purpose retrieval/prompt/derived-input, hidden heldout, sensitive
  personal-profile rejection), T060 inquiry UI.
- The compiled-policy → graph/gate/tool activation path is the runtime
  integration seam (compatibility/conflict evaluation before activation is
  registry-side here; activation itself belongs to the environment version
  flow of T036/T065).
