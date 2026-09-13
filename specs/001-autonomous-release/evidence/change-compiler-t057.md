# T057 — typed change-candidate compilation (US5)

Date: 2026-09-13
Status: implemented and unit-verified contract slice; **T057 remains open**
(no live patch application, no per-field trace slicing over real runs, no
persistence, no operational activation path)

## Exact scope

`app/runtime/compiler.py` compiles `ChangeCandidate`s per contracts/growth.md:

- Compilation is possible only from a concluded **supported** inquiry — a
  declined, unresolved or unconcluded inquiry grounds no change (justified
  no-change stays a legitimate end).
- Typed kinds: `restore` / `learn` / `protect`.
- **Per-field behavior provenance:** each clause (condition/action/exception)
  carries its own evidence refs, and every one must be evidence the inquiry
  actually observed after its freeze (matched by kind/id/sha) — real change
  grounds connected to the exact modification.
- **Copy-absorption guard:** clause text may not contain any forbidden span
  (the alternative's wording, philosophy material) under whitespace-normalized
  matching, and no reference of the unpromoted store kinds
  (own_alternative/difference/hypothesis/selector) may appear in provenance.
- Exact env/compatibility/rollback bindings (`environment` /
  `validation_report` / `backup_manifest` kinds); scopes are separate declared
  texts; candidates are issued (`init=False` + issuer token, the audit lesson
  applied from the start) — `replace()` and direct construction fail, and
  `is_compiled_candidate` is the downstream predicate.

Tests: `app/tests/test_change_compiler.py` (7) — three-kind compilation with
per-field provenance; unsupported-outcome rejection; foreign/empty provenance
rejection; verbatim and whitespace-normalized copy rejection with a clean
control; unpromoted-store smuggling rejection; issuance/anti-forgery; strict
shapes.

```text
python -m pytest -q app/tests/test_change_compiler.py
7 passed
ruff check app/runtime/compiler.py app/tests/test_change_compiler.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,124 passed, 2 skipped, 369 subtests passed, 1 known warning
```

## Frozen content identities (SHA-256)

```text
0d8c66207fb3a87824307fd3587888c5bb60de50f954f18f0521822588fdb538  app/runtime/compiler.py
7f8707dfea239d84f60627b1026f132c9f9ed8fdd00f67fd7bcb9280d2b20e1f  app/tests/test_change_compiler.py
```

## Not claimed

No patch is applied to a live environment, forbidden spans are caller-supplied
(automatic extraction from stored alternative/philosophy content needs the
persistence layer), H_phi source detection beyond supplied spans, and the
knowledge registry (T058) and comparison/growth loop (T061+) do not yet consume
candidates. No independent audit of this slice has run.
