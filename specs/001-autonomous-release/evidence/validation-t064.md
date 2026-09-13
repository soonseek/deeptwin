# Evidence — T064 sealed validation (candidate freeze, dataset exposure, gates)

- Date: 2026-09-13
- Task: T064 [US6] candidate freeze, dataset exposure tracking and
  heldout/boundary/regression/shadow/limited gates (FR-025; growth.md §7–§8,
  G-12; seen data never relabeled unseen).

## Frozen identities

```
4f7e3f60438710bd46c9d62317082a274fbdc4f56e2f5764a3c645c2ad2534a6  app/services/validation.py
edcd1a52a305960273b74bdf3d51e9fe0b8bbbe232f07e31755e94a0678ec0bf  app/tests/test_validation.py
```

## What was built

- `freeze_candidate` — the full §8 compatibility bundle (environment graph,
  model bindings, prompts, knowledge rules, archetype I/O, tool permissions,
  lens versions, scope, evaluation/approval policy, dependencies, rollback
  bundle) fixed under one content hash (`bundle_ref`, canonical JSON,
  SHA-256). Identical inputs reproduce the identical ref; changing any
  component yields a different ref — modification is a new candidate, never a
  mutation. All bindings use registered entity kinds (precedents:
  `model_choice` from alternatives, `backup_manifest` from the change
  compiler).
- Dataset ledger (FR-025) — `open_dataset_ledger` / `register_dataset` /
  `expose_dataset` / `unseen_dataset_ids`. Classifications are exactly
  {tuning, sealed_validation, prospective}. A sealed or prospective dataset
  exposed to tuning, candidate authoring or report review is reclassified to
  tuning permanently; a dataset consumed by a validation run is seen forever.
  There is no relabeling API and a dataset id can never be re-registered —
  the relabeling attack (G-12) has no path.
- `run_validation` — binds the exact frozen bundle ref; requires the exact §8
  gate set {reconstruction, heldout_transfer, boundary_exclusion, regression,
  leakage, side_effects}; every failed gate must state reasons (§7
  validation_failed keeps its causes); judge failure is `invalid` and never
  erases a real failure (`failed` dominates `invalid` dominates `passed`);
  sealed_offline mode consumes only genuinely unseen sealed datasets and
  marks them seen in the returned ledger; shadow and limited_application
  modes never consume sealed datasets (no sealed-coverage claims), and
  limited application requires the exact user-approved scope ref.
- Issued-value pattern throughout: `dataclasses.replace` and public
  constructors fail with TypeError; foreign objects are rejected.

## Verification

- `python -m pytest app/tests/test_validation.py -q` — 7 passed (TDD: module
  absent first, all behaviors written as failing tests before implementation).
- `python -m ruff check` on both files — clean.
- Full regression `python -m pytest app/tests deploy/tests -q` —
  **3146 passed, 2 skipped, 369 subtests passed** (was 3139).

## Notes

- `bundle_ref` uses entity kind `environment` (the frozen candidate is a
  candidate environment bundle version, per PromotionDecision's
  `candidate_environment: Ref`); a dedicated kind was deliberately not added
  to the domain registry.
- T065 promotion (authenticated exact-hash approval, activation CAS,
  rollback compatibility) builds directly on `ValidationReport` and
  `FrozenCandidate.bundle_ref`.
