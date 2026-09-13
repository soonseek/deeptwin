# Evidence — T045 (value slice): purpose-scoped artifacts

- Date: 2026-09-13
- Task: T045 [US3] partial — purpose-scoped artifact storage contract,
  preview derivation and range reads in app/services/artifacts.py;
  originals preserved and derived/unsupported coverage disclosed
  (runtime.md §5, FR-015). The multi-format browser viewers
  (app/static/artifacts.mjs) stay the separate UI half.

## Frozen identities

```
030d18f59519f52772949ad9bd3a7ce29cdee279067e432d7ba3443d8d888ea0  app/services/artifacts.py
a4774b8ccb9daa2ab300bc9f254ac49b19000015006f42aa014cd3846ef3468d  app/tests/test_artifacts_service.py
```

## What was built

- `register_artifact` — MIME, digest, size, provenance
  (original_execution), access purposes (closed set) and availability:
  `available` or `missing` only — a hash whose bytes are gone is missing
  and never counts as a reproducible original; ids register exactly once.
- `derive_preview` — a preview is a DERIVED artifact with its own digest,
  a mandatory fidelity note and disclosed coverage (covered spans and
  omissions); deriving never touches the original entry; a missing
  original derives nothing; `is_original=False` forever — a derived id
  can never be re-registered as an original, and `derived_coverage`
  refuses originals (an original IS its own coverage).
- `read_range` — purpose-scoped: only purposes granted at registration
  read; missing bytes refuse; every range is bounded by the real byte
  length; the admitted descriptor binds the exact digest and offsets.
- Issued values throughout; the catalog is an immutable value (storage
  owns transactions).

## Verification

- TDD: module absent first (collection error); 5 tests green.
- `ruff check` clean; full regression **3283 passed, 2 skipped**
  (was 3278).
