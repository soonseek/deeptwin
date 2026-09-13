# T061 — comparison plan and paired-round contracts (US6)

Date: 2026-09-13
Status: implemented and unit-verified contract slice; **T061 remains open**
(no isolated paired execution over real runs, no persistence, no growth-loop
consumption)

## Exact scope

`app/services/comparisons.py` implements the frozen-comparison discipline of
contracts/growth.md:

- `freeze_comparison_plan`: every condition — baseline environment, prior
  queue, quality profile, evaluator bundle, reset manifest, allowed changes,
  tool effect policy, budget — is bound by exact reference kind and frozen with
  the lineage id and mode (`automatic`/`human_assisted`) before any
  observation; the plan is content-addressed (`comparison_plan` ref). Changing
  a condition can only produce a new plan (a new lineage), never a mutation:
  plans are issued `init=False` values.
- `record_comparison_round`: binds the exact frozen plan (a look-alike object
  is rejected), requires **paired** baseline/candidate run lists of equal
  bounded size with no duplicates, and keeps validity honest:
  - `invalid` requires stated reasons;
  - only a `valid` round may carry a metric vector or a utility — a missing or
    failed measurement is never converted into a zero or a "no improvement"
    score, and a valid round may honestly carry no utility at all;
  - utility and every metric are **exact decimal strings** (floats, NaN,
    Infinity and scientific notation are rejected), parsed to `Decimal` for
    the growth loop's exact plateau arithmetic.

Tests: `app/tests/test_comparisons.py` (6) — full freeze with kind/mode
enforcement; exact plan binding and pairing; the validity/absence discipline
incl. the never-zero rule; exact-decimal utility; issuance/anti-forgery; and
bounded exact-decimal metric maps.

```text
python -m pytest -q app/tests/test_comparisons.py
6 passed
ruff check app/services/comparisons.py app/tests/test_comparisons.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,130 passed, 2 skipped, 369 subtests passed, 1 known warning
```

## Frozen content identities (SHA-256)

```text
7e238d1d41946f747c83d71c38bf09858b67c87af6482ce5371c96327c825d4e  app/services/comparisons.py
3c0f6c2584acb0439837ed5f09c5c2f0286da8274079a64d7ec1c8a38da99e60  app/tests/test_comparisons.py
```

## Not claimed

No isolated paired execution runs real workloads, nothing persists to the
domain store, downstream partial-scope effect tracing is not implemented, and
the growth loop (T062/T063 plateau/state) does not yet consume rounds. No
independent audit of this slice has run.
