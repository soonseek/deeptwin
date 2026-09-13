# T062/T063 — growth loop state and exact plateau arithmetic (US6)

Date: 2026-09-13
Status: implemented and unit-verified contract slice; **T062/T063 remain open**
(no live paired execution feeds rounds, no persistence, no UI, no validation/
promotion consumption)

## Exact scope

`app/services/growth.py` implements growth.md §6.1-§6.4 as a PRODUCT-only
early-stop policy (nothing here describes or stops development work):

- `freeze_quality_profile`: profile id/version, exact-`Decimal` quality floor
  and `min_delta`, and a patience that can never change inside a lineage —
  issued, immutable.
- `start_growth_loop` / `apply_round` / `stop_growth_loop`: the loop state is
  an issued value evolving one round at a time; a round id can never apply
  twice, and there is no API that resets counters or budget on restart.
- **best/progress separation (§6.2):** `best_observed` keeps the genuinely
  best eligible candidate (ties keep the earlier one; a confirmed-defect round
  can never take it even with a higher raw number), while
  `progress_reference` tracks the last *meaningful* improvement. The first
  valid at-floor candidate sets the reference and does not count as a
  non-improvement; afterwards improvement means
  `current - reference >= min_delta` in exact `Decimal` arithmetic (floats
  are rejected).
- Invalid/unresolved/interrupted rounds keep score `null` and counters
  untouched while their consumed budget still accrues; confirmed-defect
  rounds count as valid non-improvement. `patience` consecutive valid
  non-improving rounds after the floor end the loop `plateau_reached` — an
  exploration stop, never an operational-fitness claim.
- External stop reasons are validated honestly: plateau is never declarable
  by fiat, `budget_exhausted` requires the floor, `below_floor_exhausted`
  requires never having reached it, and a lineage change ends the loop with
  nothing carried into a fresh lineage.

Tests: `app/tests/test_growth_loop.py` (9) — all six synthetic §6.4 sequences
reproduced exactly, the first-floor non-count rule, duplicate/terminal
rejection, and issuance/exactness guards.

```text
python -m pytest -q app/tests/test_growth_loop.py
9 passed
ruff check app/services/growth.py app/tests/test_growth_loop.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,139 passed, 2 skipped, 369 subtests passed, 1 known warning
```

## Frozen content identities (SHA-256)

```text
8c55ba847c5b80424b8c02021d4974a791b25e03cea836c2c3a7f977438dd5c7  app/services/growth.py
a203394c86cbe4f6ad7a88ffde3f07d0b5780c38648fa9ab44f3b5065978f54c  app/tests/test_growth_loop.py
```

## Not claimed

No real paired execution produces rounds, nothing persists, inflight tracking
and multi-metric/Pareto profiles are not implemented, and validation (T064)
and promotion (T065) do not yet consume loop outcomes. No independent audit of
this slice has run.
