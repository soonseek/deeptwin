# Evidence — T065 promotion (authenticated exact-hash approval, CAS, rollback)

- Date: 2026-09-13
- Task: T065 [US6] authenticated exact-hash approval / activation CAS /
  rollback compatibility in app/services/promotion.py; separate
  validation/deployment/lifecycle axes (FR-026; growth.md §7–§8, G-11, G-13).

## Frozen identities

```
8054e01f68f11cf92645b8b21930ec40854fd03ebf6691784e3540f3d1d82b33  app/services/promotion.py
6b043f778c29debccde46f86af5930c08cfc8ed8a8c84a6530f7946096b4af9f  app/tests/test_promotion.py
488f21693c3f6ba74370266365ad4ecbc02de99249a626d614fde8dbbabc2ab5  app/services/validation.py
```

## What was built

- `record_promotion_decision` — one human's authenticated explicit act.
  Requires the exact decision object; the approver must be authenticated
  (canonical actor UUID + `action_approval` evidence ref); the decision must
  be an explicit `approve`/`reject`/`defer` — `None`, silence or any other
  string is refused, so a UI refresh or developer default can never mint an
  approve (§7). An approve additionally requires a framework-issued
  ValidationReport that is `passed`, `sealed_offline`, and bound to the
  exact `FrozenCandidate.bundle_ref` — shadow/limited/failed/invalid
  evidence backs nothing (G-11). The decision freezes the approved bundle
  hash (`candidate_environment`) and the report's content hash.
- `activate_candidate` — compare-and-swap conditional apply: only an
  approve; the applied bundle must equal the approved bundle exactly (a
  tampered bundle is a different version, G-13); the state's current
  environment must equal the decision's `expected_current_environment` (a
  moved environment demands re-comparison and re-approval; a consumed
  approval cannot apply twice because activation moves the current
  environment). The previous version is appended to history as `retired`,
  never erased.
- `rollback_environment` — requires a stated reason; restores the previous
  compatible bundle from history; both versions remain in history (`active`
  + `rolled_back`); `external_effects_reverted` is always False — a rollback
  restores the bundle, never the world (§8).
- FR-026 axes stay separate: validation in the report record, deployment in
  the current-environment pointer, lifecycle in the version history.
- Issued-value pattern throughout; `is_frozen_candidate` predicate added to
  validation.py for cross-module bundle verification.

## Verification

- TDD: module absent first (collection error), then 14 tests green
  (`test_promotion.py` 7 + `test_validation.py` 7). One test-side fix:
  EntityRef vs raw-dict comparison in assertions.
- `ruff check` on all three files — clean.
- Full regression `python -m pytest app/tests deploy/tests -q` —
  **3153 passed, 2 skipped, 369 subtests passed** (was 3146).

## Notes

- The promotion-screen disclosure requirements (§8: showing diffs, queue
  results, budget changes before approval) are a UI concern (T023 browser
  UI); this slice implements the decision/activation records they feed.
- The US6 chain is now contract-complete offline:
  alternatives → diagnosis → inquiry → change compiler → comparisons →
  growth loop → validation → promotion. Next: adversarial audit of the
  post-audit US6 batch (compiler, comparisons, growth loop, validation,
  promotion).
