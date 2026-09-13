# Evidence — T036 third slice: bounded supplementation orchestration

- Date: 2026-09-13
- Task: T036 [US2] partial — bounded supplementation over the offline
  design arc: generation → per-candidate driven criticism → honest pool →
  at most three rounds (experience.md: 적합 후보가 0–2개면 실제 수·이유와
  추가 탐색 가능 범위; 다시 생성해도 이전 후보·평가는 남는다).

## Frozen identities

```
df2c853cb9a56eae972cc8ab5ec8749eb8f4612f8031c06c28ed425346ec0ca7  app/services/design_orchestration.py
e602edfb442b9b4e07b83f72e5dd8f18256642a401681f0fd5e95c677860e826  app/tests/test_design_orchestration.py
```

## What was built

- `propose_environment(request, registry, *, generation_turn,
  criticism_turn, model_id, max_rounds)` — one bounded proposal run:
  - each round generates through the untrusted generation boundary and
    criticizes every accepted candidate through the live criticism driver
    (two separate callables keep the boundaries distinct);
  - the pool re-assembles over the CUMULATIVE entries — regeneration
    preserves every prior candidate, verdict, exclusion and call record;
  - a full pool (three structurally different passed) stops immediately —
    no supplementation call is spent on an already-full pool;
  - rounds are hard-bounded (1..3) and a shortfall ends as the real
    passed count with per-candidate reasons — never padding;
  - a criticism-contract violation refuses the whole proposal (typed),
    never a silently skipped candidate;
  - the `EnvironmentProposal` is an issued value carrying the pool,
    rounds, all candidates/verdicts, generation records and criticism
    runs — ready for persistence and the approval flow.

## Verification (5 tests, TDD — module absent first)

- A two-of-three first round supplements exactly once and preserves all
  three candidates/verdicts/runs (2 generation calls total).
- A full first round never spends a supplementation call.
- max_rounds=1 with two passed ends honestly (2 presented, shortfall
  flagged).
- A rejected candidate stays recorded with its `rejected:` reason while
  the pool refills from supplementation.
- max_rounds 0/4 and contract-violating critics are typed refusals; the
  proposal rejects `dataclasses.replace`.
- Test infra: a stage-aware `auto_critic` builds contract-valid review
  (all-pass or one-fail) and honest proposal abstentions dynamically from
  the actual prompt payload (candidate id/version, criteria, originals,
  lens pack) — no fixture is presented as a live score.
- `ruff check` clean; full regression **3226 passed, 2 skipped**
  (was 3221).

## Notes

- The offline design arc is now orchestrated end to end:
  propose (generate→criticize→pool, bounded supplementation) →
  approve (exact DesignApproval) → prepare (EnvironmentVersion CAS).
- T036 remaining: storage binding of proposals/approvals/versions and the
  critic-lens pipeline test file; live provider binding stays user-gated.
