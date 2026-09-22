# Evidence — the `environment` entity a run names (T048)

- Date: 2026-09-22
- Task: the Continuation's "the design line records a run consent and an environment" — the
  environment half, and the last of the five records `POST /api/v1/runs` names without a
  producer. The design arc persisted only its chained `decision_record` head
  (`design_store.persist_environment_head`, whose record version IS the head), so every test
  fabricated `{"fixture": "environment"}`. data-model.md §3 (`EnvironmentVersion` carries its
  design; prepared is never active; the `Run` row's `environment_ref`), experience.md §6.3
  (`업무 시작` fixes the input and environment version).

## Frozen identities

```
5d23192af3085924116a1eab0189339992345172990c92f3bed6f5ed0a0fa6ab  app/services/design_store.py
d7096005bf12908c1720a3073ac0d52c71e6af00f09d9840038ab4bdbccecdcb  app/services/run_consents.py
a3936ea00f4fc47562f19355c1940df524e58969b995d81bd2fbba31c0572642  app/tests/test_environment_records.py
```

(The `run_consents.py` identity frozen in the consent slices is superseded.)

## What was built

- `app/services/design_store.py`: `persist_environment_record(domain_store, version, *,
  head_ref, **headers)` seals one immutable record of kind `environment` per prepared version —
  the id is the environment's (the head chain's own uuid5), the record version is the prepared
  version, the parent is the exact head record, and the content (`environment-record-v1`) names
  the environment, the version, the approved design, the approval digest and the status, with
  the refs encoded by the arc's own encoder (the approved design may not live in this vault).
  Only a `prepared` version is ever sealed, and the head record must itself hold exactly this
  preparation — two writers preparing different designs from one head cannot seal a record
  claiming the design the head does not hold, and a second writer's different content at the
  same identity loses the compare-and-swap. `_put` gained a `kind=` parameter (the module's
  three writers are its only callers; only this one writes a kind other than
  `decision_record`), and its `StorageError` mapping now distinguishes the CAS refusal from an
  unresolvable or altered parent.
- `app/services/run_consents.py`: the deferred-coherence note rewritten — the environment
  record now has its producer, but its stored design is a design-space content hash rather
  than a store reference, so nothing yet binds it to a run's `graph_ref`.

## Review (independent, adversarial) and closures

- **ACCEPT WITH CHANGES** (3 MUST, 6 SHOULD, 3 NIT), folded in RED-first. MUST — the head
  reference was checked only by kind, id and version, so a record could be sealed claiming a
  design its own parent head never prepared (the reviewer's probe sealed exactly that) → the
  head is read and must hold this exact preparation (pinned RED first with two version-1
  preparations of different designs from one head); the consent module's deferred note claimed
  no environment writer exists → rewritten to the real remaining gap; no activation or currency
  exists, and the reviewer showed the tests enshrine every version staying nameable →
  recorded open in the producer's own docstring. SHOULD — the module docstring names the third
  writer and the one non-`decision_record` kind; the kind is a named constant beside the
  others; only a `prepared` version is sealed (the callee's grace made local now); the CAS
  message no longer covers an unresolvable parent; the idempotency claim says "under the same
  headers"; the test gaps closed — the compare-and-swap race, a head reference whose digest is
  not the stored one, and the route path the module's own docstring claimed but never tried
  (the run route starts a run under a persisted record; the chained head offered in that slot
  is refused at the consent wire). NIT — a dead parameter dropped, the decoding made consistent.
- Verified OK by the review: the shared uuid5 identity is safe (the store's primary key
  includes the kind and every query in non-test code names it; a mixed-kind reference does not
  resolve); the record is decorative to today's consumers (none read its content), so no
  consumer can read `prepared` as active; the head still resumes its own state and refuses this
  record.

## Verification

- TDD: RED retained (the producer absent; then the head-content claim), GREEN after each.
- Tests: `test_environment_records.py` **6**; the design arc, consent and run neighbours **69**
  together. Ruff: clean on the changed files.
- Full regression on the frozen identities above, with the observation-only monitor:
  **9,356 passed, 0 failed, 2 skipped** (Linux-only), 369 subtests, 1h25m; the longest
  garbage-collection pause 0.95 s, no failure chain logged. The three identities above were
  unchanged across the run.
- An earlier run of the same bytes failed two cases in `test_provider_prepare_reconciliation.py`
  (a deadline checkpoint reporting `prepared` instead of `expired`, and a missing outbox request
  file). Both are load-sensitive, not of this unit: the module passes 18/18 alone, imports
  nothing this slice touched, and under ten busy processes five of its six deadline cases fail.
  Probing showed the publication never reaches the checkpoint the test wraps, so the test
  exercises nothing and its assertion fails; the mechanism behind that is not yet established
  (a one-minute fixture deadline was the obvious candidate and did **not** fix it, so that
  change was reverted rather than kept on a guess). Recorded for a dedicated slice, with the
  reproduction recipe above; this slice's own run is green.

## Boundaries kept

- No route for the design arc (the approval still needs an accepted candidate and a fold-issued
  passed verdict, and that line has no production path yet); no activation, currency or
  environment ⇄ graph binding; the run and consent routes unchanged; no model, tool or paid call.
