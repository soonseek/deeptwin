# Evidence — T064 closed: validation gates rest on recorded evaluator executions (2026-09-23)

- Task: T064 — candidate freeze, dataset exposure and the §8 gates existed
  (evidence/validation-t064.md); the reconciliation kept it open: "Evidence-free caller-declared
  passes must not issue authoritative qualification; bind actual evaluator execution/results
  before closing."

## Frozen identities

```
b2d195c3896198067499ba3774e4a7210a68d2f90ad1817ed34f0e496d209b1c  app/services/validation.py
a933b5ebfe58e98574766bb0cea3d7ea64d01f6cfa4ea34a033a86e337c5a3a0  app/services/comparisons.py
2570409092eabb19fb784bd6ed6b38cf5720f43804521a8099f5991a007e6a3f  app/tests/test_validation.py
```

## What changed

- A gate's `evidence` is now the **framework-recorded comparison rounds themselves**
  (`record_comparison_round` values — e.g. the isolated paired execution of T061), not
  caller-supplied references. `_parse_gate` refuses anything else.
- A `pass` needs at least one round, every one `valid` and run for **this exact change
  candidate** (`round.candidate == frozen.candidate`); an invalid or pending round, a round for
  another candidate, a raw reference or no evidence at all cannot pass a gate.
- `fail` and `invalid` gates must state reasons (`invalid` newly: a judge failure is
  explained too); rounds they cite are held to the same candidate binding.
- The report records each backing round by its content-derived `comparison_result` reference
  (`comparisons.comparison_result_ref`; `is_recorded_round` is the predicate).

## Tests

`test_validation.py` 9 (2 new: the six refused shapes of a pass; the report names the exact
backing rounds and a failed gate may cite an invalid round). The shared `gate()` fixture now
builds real recorded rounds; growth store, promotion, growth firewall and US6 audit suites were
moved onto it — together with comparisons, change compiler and inquiry: **78 passed**.

## Not claimed

- Which evaluator bundle and dataset produced a round is bound by the round's plan (T061); a
  cross-check that a sealed-offline report's rounds consumed exactly its sealed datasets needs
  the dataset ledger and plan queue to share identities — recorded as a follow-up.
