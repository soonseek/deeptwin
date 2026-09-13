# Evidence — T036 first slice: selection pool and derived design versions

- Date: 2026-09-13
- Task: T036 [US2] partial — hard gates / structural diversity / honest
  shortfall in the selection pool, and select/edit/merge as new immutable
  design versions with mandatory re-review (experience.md §후보 제시/선택,
  FR-004/007/008). DesignApproval + EnvironmentVersion CAS remain the next
  T036 slice.

## Frozen identities

```
eb06eb7215db01d87894f77170edc672e5a76c6a7f86e6bd8e4b516f3ec5f387  app/services/design_review.py
2c5129b46c143ee3e452db7b71477a9760445f4a40335d16c33364f04d392210  app/tests/test_design_review.py
```

## What was built

- `assemble_selection_pool([(candidate, verdict), ...])` — at most three
  structurally different passed candidates are presented:
  - a `rejected` verdict (mandatory defect) never enters the pool
    regardless of anything else, and `insufficient_evidence` is not a pass
    — both are excluded with their stated reasons;
  - structural duplicates are detected by the SHA-256 of the existing
    `structural_diversity_projection` (the same shape under a different
    name is excluded as `structural_duplicate`, keeping the earlier one);
  - `passed_count` reports the real number of passed candidates even when
    fewer are pooled, and `supplementation_available` is true whenever
    fewer than three present — the pool states reality instead of padding;
  - verdicts must bind their exact candidate (id + version), candidates
    must be acceptance-issued, statuses must be known, and one candidate
    can never appear twice.
- `derive_design_version(action, parents, instruction=)` — `select` (one
  parent), `edit` (one parent + mandatory instruction), `merge` (two or
  more parents): each returns an issued `DerivedDesignVersion` bound to
  its parents' graph refs with `re_review_required=True` and
  `inherited_verdict=None` — scores and approvals never inherit (FR-008);
  unknown actions (e.g. "regenerate" — regeneration is generation, not
  derivation) are refused; issued values reject `dataclasses.replace`.

## Verification (4 tests, TDD — module absent first)

- Pool presents the two structurally different passed candidates and
  excludes the same-shape third as `structural_duplicate` while honestly
  counting all three as passed.
- Rejected/insufficient candidates produce an empty pool with per-candidate
  reasons and supplementation availability.
- Cross-bound verdicts, foreign candidates, malformed verdicts, unknown
  statuses and duplicated candidates are refused.
- Derivations enforce parent arity, edit instructions and no inheritance.
- One test-infra correction: a "3-agent" graph variant does not exist in
  the fixture; a real structural change (narrowing the final artifact
  contract) is used instead — confirming the projection keys on shape,
  not names.
- `ruff check` clean; full regression **3210 passed, 2 skipped**
  (was 3206).

## Notes

- Next T036 slice: exact `DesignApproval` (human act on one exact design
  version) and `EnvironmentVersion` preparation by CAS in
  app/services/environments.py — preparation is not operational promotion.
