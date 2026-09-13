# Evidence — durable growth-chain persistence with store-enforced CAS

- Date: 2026-09-13
- Scope: discharge the storage-seam obligations recorded by the US6 batch
  audit (F4 ledger replay, F6 lineage restart/fork; growth.md §7 G-09) on
  the DomainStore. New module app/services/growth_store.py plus strict
  restore paths in growth.py and validation.py.

## Frozen identities

```
d5e445687565a9877cc4ad44f51756f6e4c858d7a6e65ab3fe6011948e3a47ad  app/services/growth_store.py
34b08672b64c14b16bb349ebc9c36cdea1b77e52250f0aa1991ed9cb7d697ccf  app/services/growth.py
568e9be0bd510ac1f2a1ac691cc860b43e7b4cf82d6a71cabc72f1a57fac640e  app/services/validation.py
4e4c6e11222cf2b7cdd3dfac6a3ae7e2cbef2c637177a886494f6ae94db298c5  app/tests/test_growth_store.py
```

## What was built

- **CAS on the DomainStore's immutable identity** — every loop revision and
  ledger revision is one `decision_record` whose record version IS the
  revision, hash-chained through `parent_refs` to its exact predecessor.
  Two writers advancing from the same revision produce the same
  (kind, id, version) with different content: the second `put` fails with
  ImmutableConflict, surfaced as GrowthStoreError (G-09 — no silent fork).
- **Lineage single-liveness (F6)** — a loop's revision-1 record is the
  lineage's opening: re-opening the same lineage with a different profile
  collides; an identical re-open is idempotent (same ref, no fork). A loop
  revision > 1 must carry its exact predecessor as parent; a parentless
  later revision is the restart-laundering path and is refused before the
  store is touched.
- **Unseen-claim durability (F4)** — `persist_validation_report` stores a
  run at an identity derived from (lineage, consumed ledger revision):
  a *different* run replaying the same pre-consumption revision collides;
  a byte-identical replay is idempotent (same record, never a second
  claim). Consumed-ledger writes themselves are idempotent when identical.
- **Strict restores** — `growth.restore_growth_loop(profile, dict)` and
  `validation.restore_dataset_ledger(dict)` revalidate everything a
  payload could lie about (status/stop-reason coherence, counter bounds vs
  patience, floor/reference consistency, plateau consistency, round-id
  membership of best/reference, revision vs entry counts, classification
  and manifest uniqueness); trust comes from the store's hash chain, and a
  tampered payload is refused. `is_issued_loop` / `is_issued_ledger`
  predicates exported.
- Content uses the design-persistence ref codec (EntityRef-shaped dicts
  encoded as tagged strings) so synthetic manifests never break the
  store's real-edge check; ledger record ids are UUIDv5 of the lineage.

## Verification

- TDD: module absent first, 3 intermediate failures fixed (ledger
  first-revision > 1 parent rule; the correct realization that identical
  replayed ledgers must be idempotent while the *report* identity is what
  collides; one wrong counter expectation in the test itself).
- 7 new tests; `ruff check` clean.
- Full regression `python -m pytest app/tests deploy/tests -q` —
  **3195 passed, 2 skipped, 369 subtests passed** (was 3188).

## Notes

- PromotionState persistence rides the same pattern when needed (its
  consumed-decision replay is already refused in-value; its durable CAS
  can bind current-environment revisions the same way).
- The evidence files us6-batch-audit.md (F4/F6) now have their seam
  obligations discharged at the store layer for loop and ledger.

## Addendum — promotion-state durable CAS (same date, second slice)

PromotionState now carries a monotone `revision` (open=1; each
activation/rollback +1) and persists through
`persist_promotion_state(domain, state, scope_id=...)` /
`resume_promotion_state` at record id UUIDv5("deeptwin:promotion:{scope}"),
version == revision, parent-chained. Verified: (a) a resumed state keeps its
`consumed_decisions`, so an approval consumed before persistence can never
re-activate after a resume+rollback; (b) two writers from one revision — a
rollback vs a different candidate's activation — collide at the store while
a byte-identical write stays idempotent; (c) `restore_promotion_state`
refuses tampered payloads (revision bounds, `external_effects_reverted`
must be False — a permanent honesty invariant, never a stored truth —
malformed decision hashes, non-{retired,rolled_back} history lifecycles).
Note: the rollback *reason* is not part of the state value (two rollbacks
of the same revision are byte-identical); reasons belong to the audit event
stream, not the CAS identity.

Post-fix hashes:

```
6fb8a55f69126266d958ac54831d43fe24e9e8eb00408fc2b7baf88406734483  app/services/growth_store.py
7291041ee5a208568c6c43cd8b89da2329c2189e9099716611f717724d506d53  app/services/promotion.py
f968029b1a77185ce0581eff81ff08172b9fcf26b402735826543ba92faa4a31  app/tests/test_growth_store.py
```

3 new tests; full regression **3198 passed, 2 skipped** (was 3195).
