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

## Live candidate-generation driver (2026-09-13)

Frozen identities (SHA-256):

```text
c82d834f35b355098d5a41042efffaf1700cad995ce53b732ad28fff09cf4251  app/services/design_live.py
3ec86c457f32cf2e437b58391a6c592f6a4c2be5bc9435cfac05d4c3ddfe7362  app/tests/test_design_live.py
```

`app/services/design_live.py` adds the first live-path slice for T027/T030: a bounded
generation driver in which the framework keeps every authority and the model boundary is
one caller-supplied `model_turn(system, user) -> str` callable (bindable to the Claude or
Codex adapters later, scriptable offline today):

- `render_candidate_prompt(request)` deterministically renders the exact (system, user)
  prompt pair: the DESIGN_CANDIDATE instruction profile (restrictions + reference
  boundary + responsibility) plus a closed output-schema clause, and a canonical-JSON
  user payload carrying the generation request, full work model, design decisions,
  disposition and requested count.
- `run_candidate_generation(request, model_turn=..., model_id=...)` validates the
  request/model identity/boundary, runs exactly one turn (a boundary exception is
  wrapped terminally — no retry), parses the response as the exact
  `{"candidates": [{"graph": ...}, ...]}` object (strict keys, bounded count/size), and
  mints the `GenerationCallRecord` itself (request ref, profile digest, model id, prompt
  and response sha256; content-ref'd as a `decision_record`). The model contributes
  nothing but graphs — candidate identities are framework-minted UUIDs, call refs are
  the framework's own record, and any extra key from the model is terminal. Admission
  runs only through `accept_design_candidates`, so the compiler authority, decision
  binding, effect realization and structural-diversity rejection all apply unchanged
  (a renamed-twin batch from the model is rejected by the existing authority).

Tests: `app/tests/test_design_live.py` (7) — exact prompt/payload/call-record binding
against a scripted model; deterministic rendering; forged call-ref/candidate-identity
rejection; renamed-duplicate rejection via the authority; ten malformed-output shapes
terminal; a raising model boundary wrapped; request/model-identity validation.

```text
python -m pytest -q app/tests/test_design_live.py app/tests/test_design_generation.py
29 passed
ruff check app/services/design_live.py app/tests/test_design_live.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,006 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Not claimed: no real provider adapter is bound to `model_turn` yet (no live API calls —
none are authorized), generation-call records and accepted candidates are not yet
persisted as domain records, and the criticism/selection/approval stages of the journey
remain open.

## Durable persistence of the generation chain (2026-09-13)

`app/services/design_persistence.py` persists the live chain as immutable domain
records with real lineage: request → generation call → graph → candidate, each a
`decision_record`/`graph`/`design_candidate` record whose `parent_refs` are the actual
stored record refs. Design-layer references are content hashes over design dictionaries
— a different hash space from the store's body-hash record refs — and the DomainStore
reserves `*_ref(s)` keys and ref-shaped dicts in content for verified record edges, so
the codec (`encode_design_refs`/`decode_design_refs`) stores design refs as tagged
`design-ref:` strings with suffixed key names and decodes them exactly; non-ref shapes
(effect targets, lens-ref strings) pass through untouched. Persistence is idempotent
(same stamp → same records), and cross-request/call binding is validated before any
write.

Tests: `app/tests/test_design_persistence.py` (5) — codec round-trip with foreign
shapes untouched; the full generated chain persisted with exact lineage and
content round-trip out of a real vault; idempotent re-persist; foreign request/result
binding rejection; type guards.

```text
python -m pytest -q app/tests/test_design_persistence.py app/tests/test_design_live.py
12 passed
ruff check app/services/design_persistence.py app/tests/test_design_persistence.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,011 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
2b5216baf4d5e3d0e30eff844c8eba74d5c5cf1b1029d854f64f3aabd5c18d22  app/services/design_persistence.py
b5cc7fc968775a59fb2b79fc8c8b2f0f3d50a333ee89a633a3c79026cb3a3a56  app/tests/test_design_persistence.py
```

Not claimed: candidates/calls are persisted but nothing consumes them yet (criticism,
selection and approval stages remain open), no provider adapter is bound to the model
boundary, and no policy-host registration/read-grant path covers these records.

## Critic-facing candidate projection (2026-09-13)

`app/services/design_criticism.py` bridges accepted live candidates to the
already-qualified critic pipeline: `critic_candidate_projection` renders the exact
candidate functional contract (roles/artifacts/handoffs/control) the critic contract
requires, validated against `critic_contract.Candidate` before return. It is
deterministic and faithful — real agent responsibilities and slot flows, exact
model/tool binding reference strings, artifact producer/consumer/access derived from
the real slot topology, artifact-edge handoffs with multiplicity/mandatory modes — and
every non-role mechanism (human gates, deterministic handlers, non-artifact edges,
completion criteria, observation/budget bindings, fact names, approval scopes) is
surfaced in the control notes so the critic cannot be shown less than the graph
commits to. The projection grants no authority.

Tests: `app/tests/test_design_criticism.py` (7) — contract validation over a
live-generated candidate; determinism; faithful roles/bindings/slots (Korean
responsibility text exact); artifact/handoff flow; control-note completeness;
single-agent shape; type guard.

```text
python -m pytest -q app/tests/test_design_criticism.py
7 passed
ruff check app/services/design_criticism.py app/tests/test_design_criticism.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,018 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
050cdb7547fe04ebeb32e722b7dba29b9ae32887523aff6b4cf72a9c61dd9e98  app/services/design_criticism.py
3ec89372af38b15c6f1f9ff0e1915c95bd2d177fe3c7af8636e4ed38db029e21  app/tests/test_design_criticism.py
```

Not claimed: no critic trial has yet run over a projected live candidate (the review/
counterexample/validity/response stages still consume their own prepared inputs), and
selection/approval over criticized candidates remains open.

## Review preparation and parsed round trip (2026-09-13)

`prepare_candidate_review(candidate, request)` completes the offline review loop over a
live candidate: it builds the exact bounded `ReviewInput` — the confirmed work model as
the original document (deterministic canonical-JSON sections per field:
goals/deliverables/completion_conditions/authorities/risks/unknowns/suitability),
criteria derived from the request itself (one per decision functional claim, one per
proposed effect with its declared graph target, the disposition-shape criterion, and
one per work-model completion condition), and the candidate projection — then hands it
to the already-qualified `prepare_input(REVIEW, ...)`, so the critic contract's own
visibility/citation registry and manifest hashing apply unchanged. Binding is validated
first: the candidate must belong to the exact request and work model.

A scripted review response covering every derived criterion round-trips through
`parse_response`, and a coverage-violating response is rejected by the existing
contract — demonstrating the full offline review path over a live-generated candidate.

Tests: 4 more in `app/tests/test_design_criticism.py` (11 total) — prepared-input
shape/criteria/manifest assertions, determinism, foreign-request rejection, and the
scripted parse round trip with coverage violation.

```text
python -m pytest -q app/tests/test_design_criticism.py
11 passed
ruff check app/services/design_criticism.py app/tests/test_design_criticism.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,022 passed, 2 skipped, 369 subtests passed, 1 known warning
```

Frozen identities (SHA-256):

```text
9c5896d99ec6b8eea05d61df7fcffcfeae3bfe50ac675c2fb384dadeb0d71bc1  app/services/design_criticism.py
bc6ffb3d348c606e63f754bcad691cf4cd32691e11458f0bb000b50a21d09057  app/tests/test_design_criticism.py
```

Not claimed: no model has produced a live review (the scripted response only proves the
contract path), counterexample/validity/response stages are not yet driven from design
context, and selection/approval over criticized candidates remains open.
