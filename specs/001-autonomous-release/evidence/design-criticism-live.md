# Evidence — live-driven candidate criticism (design pillar, toward T030/T036)

- Date: 2026-09-13
- Scope: drive the four criticism stages (review, counterexample proposal,
  validity, candidate response) over the same untrusted
  `model_turn(system, user)` boundary the generation path uses, minting one
  framework-owned call record per actual model call, and folding through
  `fold_candidate_criticism`. Offline: the boundary is a scripted callable;
  no provider transport is bound and no live/paid call occurs (user gate).

## Frozen identities

```
3fa53902b82646efcb9faec36302e7f6f6aa64a8e08568cff9e34f75340f6449  app/services/design_criticism_live.py
55afdf0add7c37bc00ee2065ea13eb60bd5ee0fd49b15b70be5326c86d0fd124  app/tests/test_design_criticism_live.py
```

## What was built

- `render_criticism_prompt(prepared)` — the system prompt is exactly the
  code-owned instruction profile for the stage's purpose plus the stage's
  output schema; the user payload is the prepared contract input byte for
  byte (nothing else reaches the model).
- `run_candidate_criticism(candidate, request, registry, *, model_turn,
  model_id)` — review → proposal → per-counterexample validity → response
  only when validity is `valid` (rejected/unresolved validities spend no
  response call; an abstaining proposal ends the chain after two calls).
  Raw responses are admitted only through the pure critic contract's
  `parse_response`; a malformed, oversized or wrongly-bound response, a
  raising boundary, a non-callable, or a bad model id is a typed
  DesignCriticismError — never a verdict.
- `CriticismCallRecord` — purpose (one of the four critic purposes),
  instruction-profile digest, model id, prompt/response SHA-256, request
  binding, content-hashed `call_ref`; one per actual call, in call order.
- `CriticismRunResult` — folded CandidateVerdict + review + chains + call
  records, ready for persistence next to the generation chain.

## Verification (4 tests, TDD — module absent first)

- Full 4-stage scripted chain folds to a `passed` verdict with exactly 4
  call records in stage order, each carrying the stage's profile identity
  inside the actual system prompt sent to the boundary.
- A rejected validity produces exactly 3 calls and a `response: None`
  chain that folds out.
- An abstaining proposal (contract-valid: empty counterexamples,
  uncertainties stated, lens abstention) produces exactly 2 calls.
- Malformed JSON, cross-candidate binding, a raising boundary, a
  non-callable boundary and an invalid model id are all typed refusals.
- One fixture fix during RED→GREEN: lens_use status enum is
  `used|excluded|abstain` (not `no_contribution`).
- `ruff check` clean; full regression **3202 passed, 2 skipped**
  (was 3198).

## Notes

- Remaining for the design pillar's live path: persistence of criticism
  results next to the generation chain (design_persistence has
  `persist_candidate_criticism` — wire the driven result into it),
  selection/approval flow (T036), and the actual provider transport
  binding + live qualification (user-gated: paid API authorization).
