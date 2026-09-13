# Evidence — durable persistence of driven criticism runs (design pillar)

- Date: 2026-09-13
- Scope: wire `CriticismRunResult` into the design persistence chain —
  every actual model call and the recomputed-fold verdict become immutable
  records parented under the candidate record.

## Frozen identities

```
b77103c16cd99a5db5be4e03f8cffa8a6eeee14a392c16ed09230415fd68d5c3  app/services/design_persistence.py
6a2f56509ea06c096d98a6b12b1b42b351f8c7d04eb2b64e261ccea87a06fea0  app/tests/test_criticism_run_persistence.py
```

## What was built

- `persist_criticism_run(domain, candidate_record_ref, candidate, request,
  registry, run, ...)` — the run is never trusted as presented:
  - every stage's prompt hash is **recomputed** from the candidate,
    request, registry and the run's own chains (review, proposal, one
    validity per chain, one response per non-None chain response) and must
    equal the presented call records in exact sequence;
  - all call records must share one model identity and the exact request
    binding;
  - each `CriticismCallRecord` persists as its own `decision_record`
    (design_kind `criticism_call`, id = call_id) parented to the candidate
    record;
  - the verdict record persists through the existing
    `persist_candidate_criticism` (which recomputes the fold), now
    extended to carry the call-record dicts in content and the call-record
    refs as additional parents.
- Response hashes remain the boundary's recorded fact (raw responses are
  not retained beyond their hash); prompt hashes are provable and proven.

## Verification (4 tests, TDD — import failure first)

- A driven 4-stage run persists: 4 call records + 1 criticism record;
  content round-trips (verdict, ordered call ids); every call record is
  parented under the candidate record.
- A forged prompt hash never persists.
- A dropped call and a reordered call sequence never persist.
- A forged `passed` verdict and a non-run object never persist.
- `ruff check` clean (2 autofixes); full regression
  **3206 passed, 2 skipped** (was 3202).

## Notes

- The design pillar's offline arc is now: generation (driven + persisted)
  → criticism (driven + persisted with call provenance). Next: T036
  selection/approval (independent reviews, hard gates, DesignApproval,
  EnvironmentVersion CAS), then live provider binding (user-gated).
