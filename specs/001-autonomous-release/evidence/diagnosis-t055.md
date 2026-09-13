# T055 — difference and hypothesis contracts (US5)

Date: 2026-09-13
Status: implemented and unit-verified contract slice; **T055 remains open**
(no trace slicing over real runs, no persistence, no inquiry/SPLI consumption)

## Exact scope

`app/services/diagnosis.py` implements the observation/interpretation split of
contracts/growth.md:

- `Observation.from_untrusted`: one format-aware observable difference
  (text/table/page-region/image-region/time-range/structure change) with a
  bounded locator — never an interpretation.
- `record_difference(alternative, observations, uncertainties)`: a `Difference`
  bound to the accepted alternative's exact original/alternative artifacts and
  selector alignment, inheriting its stated `evidence_scope`/`unreviewed_scope`;
  the payload structurally carries no cause or hypothesis field.
- `propose_hypotheses(difference, values)`: the five contract families
  (system / expert_judgment / exception / alternative_error /
  no_generalization) as competing `proposed` hypotheses. A lone causal family
  is rejected — only the explicit null conclusion may stand alone.
- `HypothesisSet.resolve`: immutable single-transition evolution.
  **Confirmation requires every competitor to be examined first** (the
  single-cause shortcut is a typed error) and a non-empty basis of real
  comparison/behavior evidence references (`comparison_result`/`artifact`/
  `handoff` kinds only) — the difference record itself (a string diff) is not
  an admissible basis, and non-referential grounds (model confidence,
  philosopher authority, human silence) cannot enter a basis because a basis
  is made of exact entity references. Refutation records counterevidence;
  resolved hypotheses never transition again.

Tests: `app/tests/test_diagnosis.py` (6) — observation-only difference with
scope inheritance; family competition incl. lone-null; examined-competitors
confirmation gate; evidence-kind basis enforcement incl. the string-diff
rejection; counterevidence on refutation; strict shapes and single-transition
discipline.

```text
python -m pytest -q app/tests/test_diagnosis.py app/tests/test_alternatives.py
14 passed
ruff check app/services/diagnosis.py app/tests/test_diagnosis.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,101 passed, 2 skipped, 369 subtests passed, 1 known warning
```

## Frozen content identities (SHA-256)

```text
eb59a326f18b213e0e055ce9c20b738692bf9f6346847641e04ef29e41ffe21a  app/services/diagnosis.py
45d47d8651f614d6676e0b13b6829da9fddf0335d78ad26aff8a75c728c9e297  app/tests/test_diagnosis.py
```

## Not claimed

No trace slicing over real preserved runs, no domain-store persistence, and the
inquiry stage (T056 SPLI routing, frozen predictions, fresh evidence) does not
yet consume these hypothesis sets. No independent audit of this slice has run.
