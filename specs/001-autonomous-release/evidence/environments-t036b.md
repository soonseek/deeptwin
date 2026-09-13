# Evidence — T036 second slice: exact DesignApproval + preparation CAS

- Date: 2026-09-13
- Task: T036 [US2] partial — exact `DesignApproval` and preparation of the
  same `EnvironmentVersion` by CAS in app/services/environments.py with
  stale/hash/run-binding tests; preparation is not operational promotion
  (experience.md §6.3 `이 설계로 준비`; FR-004/007/008).

## Frozen identities

```
b7626bc76cb687145c9316bcac89cab306f7af3ce01e6ca158698b333db107fa  app/services/environments.py
5e9e770a04203efc8615beb48e2e60ad6888e90c0410948675f5b870a022c3dd  app/tests/test_environments.py
```

## What was built

- `record_design_approval` — a human's authenticated explicit act on one
  EXACT design version: requires an acceptance-issued candidate, a
  criticism verdict bound to that exact candidate (id + version) with
  status `passed` (a rejected/insufficient design is never approvable — a
  derived select/edit/merge version must complete its own re-review into a
  passed candidate first), an authenticated approver with `action_approval`
  evidence, a canonical timestamp, and the concrete configuration refs
  (model bindings, tool grants, observation contract). The approval binds
  `candidate.graph_ref` (the exact graph hash) and content-hashes itself
  (`approval_sha`).
- `prepare_environment_version(state, approval, expected_head=)` — CAS on
  the environment head: a stale expected head refuses (the environment
  moved; re-compare and re-approve); each approval prepares at most once
  (`consumed_approvals` by content hash); the prepared
  `EnvironmentVersion` carries the exact `design_ref`, the `approval_sha`,
  and status `"prepared"` — this module exposes NO activation function, so
  preparation can never masquerade as work start or operational promotion.
- Issued-value pattern throughout; `dataclasses.replace` fails on
  approvals, versions and states.

## Verification (5 tests, TDD — module absent first)

- Approval requires passed+bound verdict, authenticated approver, accepted
  candidate; cross-bound verdicts refuse.
- Preparation CAS: stale head refuses; consumed approval refuses; a second
  approval advances the head to version 2.
- Approval tampering is structurally impossible (`replace` → TypeError);
  foreign objects refuse.
- Prepared versions/states are issued; the module has no
  `activate_environment_version`.
- `ruff check` clean (3 autofixes); full regression
  **3215 passed, 2 skipped** (was 3210).

## Notes

- T036 remaining: independent-review orchestration over the live criticism
  driver for multiple candidates (bounded supplementation loop), the
  critic-lens pipeline test file (test_critic_lens_pipeline.py), and the
  storage binding of approvals/versions.

## Addendum — storage binding (design_store.py, same date)

The documented EnvironmentState storage-CAS seam is discharged:
`persist_design_approval` stores each human approval content-addressed
(UUIDv5 of approval_sha — an identical re-persist is idempotent, never a
second act); `persist_environment_head` stores one record per head value
(record version IS the head, chained to its exact predecessor, the
consumed approval as an additional parent), so two writers preparing from
the same head collide at the store; `resume_environment_state` rebuilds
the issued state through the strict `restore_environment_state` path, and
a resumed state still refuses every consumed approval. Cross-checks:
version/state must describe the same preparation (environment id, head,
approval_sha membership). 3 new tests; regression 3229 passed, 2 skipped.

```
71590ad21ef25db67a4387649589e96fedb6e092f26c1888729b92ead9f64800  app/services/design_store.py
5d2fa4c312ef3858d0096a69473ed61e74a3da1bf46c26ca5ff9ce3a5a12a044  app/services/environments.py
52fc5e44a3648a2463dbe9106f00fe8e7faa80e48cdac486ae4953fa6017fddb  app/tests/test_design_store.py
```
