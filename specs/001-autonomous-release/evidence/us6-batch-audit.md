# Evidence — adversarial audit of the US6 batch (T057, T061–T065)

- Date: 2026-09-13
- Scope: independent adversarial audit of compiler.py, comparisons.py,
  growth.py, validation.py, promotion.py against growth.md §3–§8 and
  FR-022..026. Verdict: **REJECT** (1 critical, 8 major, 9 minor). Every
  code-level finding is closed with a regression test in
  `app/tests/test_us6_audit_findings.py` (15 tests, RED before the fixes).

## Frozen identities (post-fix)

```
48324cffab9876e5ee8ee4d14f360c12bd84b67ccdf88455a32146f604c18d08  app/services/promotion.py
d993602ca74e6cb84f1820a4e95c6f0adc7ed7f3e14e207b5553926fdbf6ff34  app/services/validation.py
eb1b144de4a7285246cca5eb19faa259644d72c0290db36012a400883e3b3e4b  app/services/growth.py
67df72b3fa0bac4a7232101e60849be4bfa7dd6a27a38ef6134db0396daf3775  app/services/comparisons.py
4f404d93080903c4770b54d36c606edc0f5231eedc6f3235ac3ffea464e5e5c3  app/services/inquiry.py
33168c72644d995bbc6b9ad50bf377cc641cf850e40a797accb319ce3caf16a1  app/runtime/compiler.py
61dbee35dded548778fa9b769b9d8968b7f3c034165570126e8fe90a0102e3ec  app/tests/test_us6_audit_findings.py
```

## Findings fixed (finding → fix → regression test)

- **F1 (critical)** Double rollback silently re-promoted the rolled-back
  bundle with no approval → rollback now restores only the latest `retired`
  entry; a `rolled_back` bundle is never restorable and history never holds
  two actives → `test_f1`.
- **F2 (major)** A consumed approval became valid again after rollback (and
  forked) → `PromotionState.consumed_decisions` records the content hash of
  every applied decision; re-activation refuses it → `test_f2`.
- **F3 (major)** Sealed-data laundering: a burned manifest re-registered
  under a fresh dataset id regained unseen status → registration now refuses
  any manifest already present in the ledger → `test_f3`.
- **F4 (major)** Immutable-ledger replay produced unlimited unseen passes
  undetectably → `DatasetLedger.revision` (monotone) + reports carry
  `ledger_revision`; two reports from one state are a visible conflict; the
  storage layer must CAS on the revision (documented) → `test_f4`.
- **F5 (major)** `min_delta<=0` / negative floor destroyed plateau semantics
  → profile freeze requires `min_delta > 0`, `quality_floor >= 0` →
  `test_f5`.
- **F8 (major)** compiler accepted a forged never-issued Inquiry (only
  consumer missing the token check) → `is_issued_inquiry` exported from
  inquiry.py and required → `test_f8`.
- **F9 (major)** Different contents shared `(kind, id, version)` with
  divergent hashes (bundle_ref, plan_ref, validation_report ref) → ids are
  now UUIDv5 of the content hash → `test_f9`.
- **F10 (minor)** A run paired with itself → baseline/candidate lists must
  be disjoint → `test_f10`.
- **F11 (minor)** Comparison rounds had no idempotency id → `round_id`
  required field, binding the seam growth already dedups on → `test_f11`.
- **F12 (minor)** `apply_round` accepted extra keys, unknown validity, and
  silently dropped scores on non-valid rounds → exact key set (+optional
  `invalid_reason`), validity enum, non-valid rounds must carry
  `utility=None` → `test_f12`.
- **F14 (minor)** Forbidden verbatim spans unscanned in
  `change_scope`/`predicted_impact_scope` → scanned like patch clauses →
  `test_f14`.
- **F15 (minor)** Provenance matching ignored `version` → observed-evidence
  key is the full 4-tuple → `test_f15`.
- **F16 (minor)** Lax promotion timestamps → canonical 6-digit-fraction UTC
  regex (same as inquiry) → `test_f16`.
- **F17 (minor)** Unhashable dataset items leaked a raw TypeError → typed
  check, domain error → `test_f17`.
- **F18 (minor)** A human could not record reject/defer of a
  failed-validation candidate → only `approve` requires the passed
  sealed-offline report; reject/defer are recordable on any bound report →
  `test_f18`.

## Findings acknowledged without code change (design/seam decisions)

- **F6** `start_growth_loop` re-opens a lineage with fresh counters: not
  preventable in a pure-value module. The overclaiming docstring was
  corrected; the storage layer owns single-live-loop-per-lineage and CAS on
  `revision` (growth.md §7). Same seam decision covers state-object forks.
- **F7** Post-issue `object.__setattr__` mutation and token exfiltration:
  the issued-value pattern is a discipline boundary against accidental
  misuse (public constructors, `dataclasses.replace`, duck-typed
  look-alikes), not a security boundary against hostile in-process code — an
  attacker who can call `object.__setattr__` can equally call the module's
  own private `_issue` or rebind `_ISSUE_TOKEN` on the module object, so no
  in-process registry closes that class of attack. Recorded as the pattern's
  documented threat model.
- **F13** A valid round with `utility=None` never counts toward plateau: per
  §6.2 a fully-observed capability failure counts only when the independent
  evaluation completed normally — which yields a score. `utility=None`
  means the evaluation did not complete; counters stay untouched. The seam
  obligation (evaluators must score completed evaluations) is documented in
  growth.py.
- Auditor's verified-negative list (subclass forgery, pickle round-trips,
  `dataclasses.replace`, decimal attacks, §6.4 sequences, stop-reason
  laundering, gate honesty, CAS basics, compiler leak checks) is retained in
  the audit transcript for future audits.

## Verification

- TDD: all 15 regression tests written first and observed failing (14
  RED + 1 spurious pass traced to a tuple-unpacking bug in the test itself,
  fixed, then RED).
- Existing suites updated for the strengthened contracts: comparison rounds
  now carry `round_id`; rollback history assertions follow the new
  restore-only-retired semantics.
- `ruff check` clean on all changed files.
- Full regression `python -m pytest app/tests deploy/tests -q` —
  **3168 passed, 2 skipped, 369 subtests passed** (was 3153).
