# Evidence — T036 (remainder): critic-lens pipeline and input isolation

- Date: 2026-09-13
- Task: T036 [US2] remainder — the qualified lens routing/composition →
  LensPack → counterexample → independent validity/response pipeline with
  contribution/abstention recording and input isolation, in
  app/tests/test_critic_lens_pipeline.py (runtime.md §1 critic-* profile;
  FR-004/FR-006).

## Frozen identity

```
8cc72b27883c400d8a1ccf65d4fafec1451ef04a26be7d172393d96ce7997337  app/tests/test_critic_lens_pipeline.py
```

## Pipeline proven (4 tests over existing audited modules)

- **Qualified decisions → exact pack** — the registry's qualified lens
  decision becomes the proposal stage's LensPack rule with its honest
  academic status (`research_draft`), identified by the exact lens ref.
- **Contribution/abstention per rule** — a `used` lens contribution must
  name the counterexamples it produced; the lens_use set must match the
  pack exactly (an invented rule id refuses); both enforced by
  `parse_response` at the admission boundary.
- **Input isolation across stages** — the review input carries no lens
  identity at all (the string "lens" does not appear); validity sees the
  bound counterexample but never the lens pack, another critic's verdict
  or review findings — validity stays independent of the proposer's lens
  framing.
- **No generator identity leaks** — the candidate's `audit_lens_refs`
  exist on the record but none of them appears in the critic-facing
  candidate projection, and no self-score field exists.

## Verification

- Pure test slice; one probe run confirmed the isolation surfaces before
  authoring; two fixture fixes (LensDecision attribute shape).
- `ruff check` clean; full regression **3344 passed, 2 skipped**
  (was 3340).

## Notes

- T036's remaining scope is now the storage binding of pool/approval
  records into the runtime routes and the live provider binding — both
  outside the offline value layer (routes/UI/live gates).
