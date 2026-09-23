# Evidence — T055 closed: format-aware differences observed over sliced traces (2026-09-23)

- Task: T055 — "format-aware differences/trace slicing and system/expert/exception/error/
  no-generalization hypotheses …; no unsupported single-cause claim (FR-018)". The observation and
  hypothesis contracts (evidence/diagnosis-t055.md) and trace slicing over real scheduler runs
  (evidence/run-trace-t055.md) existed; observations were caller-supplied, and "format-aware
  artifact differences over sliced traces" was recorded open.

## Frozen identities

```
eddd07456cd100de01e397550daec63952730027635ffb176df5a91aa540626e  app/services/difference_observer.py
558ce9ed2bbe4fb34ecdf352f0e9fe19fdbc8e336bc96d0c012e79c386e5dbe0  app/tests/test_difference_observer.py
```

## What landed (`app/services/difference_observer.py`)

- `observe_differences(original, alternative, *, media_type)` — the framework, not a model,
  observes where two exact artifacts differ, in the format's own units, as `Observation` values
  `record_difference` accepts unchanged:
  - text (`text/plain`, `text/markdown`, other `text/*` with a disclosed uncertainty): line spans
    per replace/delete/insert (1-based, `alignment: proposed`); equal lines with different line
    endings are still a difference;
  - CSV: rows paired one to one yield cell-level changes (added/removed/changed, row and column),
    other row blocks are row-span changes; formula-looking cells are compared as text;
  - JSON: exact RFC 6901 paths added/removed/changed (`alignment: confirmed`, since a path is
    exact); equal values with different serialization are observed as such;
  - anything this process does not parse (PDF, images, office containers, binary) — one
    whole-artifact observation (`alignment: unresolved`) with the reason as an uncertainty, so
    different files never read as the same and no page or region difference is invented;
  - identical bytes observe nothing. Bounds: 1 MiB per input, 20 000 lines, 10 000 rows, JSON depth
    32, paths 1 KiB; beyond 256 observations the rest are counted in one observation and an
    uncertainty, never dropped silently.
- `observe_boundary_output(domain_store, trace_slice, *, ordinal, alternative)` — the original is
  the exact artifact a framework-issued trace slice's boundary execution durably produced (read
  through the store, which verifies its bytes), with the media type the transport sealed; a
  boundary without a result, without that artifact, or a slice the framework did not issue is
  refused.

## Tests (`app/tests/test_difference_observer.py`): 10 passed

Text replace/insert spans; line endings only; CSV cell and row changes, formulas as text; JSON
paths incl. escaped `/`, serialization-only; opaque PDF and binary text; identical; > 256 changes
counted; bounds (size, type, depth); observations feed `record_difference`; and over a real
scheduler run the writer's sealed output read back through `slice_trace` is the compared
original, with the intake boundary (no artifact list), a missing ordinal and a foreign slice refused.

## Not claimed

- Page, image-region and time-range differences need the isolated artifact codec worker; until it
  is connected those formats are observed only as whole-artifact differences with the reason.
- Persisting differences and hypothesis sets in the growth chain and feeding them to inquiry are
  T056/T057's consumers.
