# Evidence — T057 closed: mandatory leak check and the system-repair admission (2026-09-23)

- Task: T057 — typed restore/learn/protect compilation with per-field provenance and leak checks;
  the 2026-09-15 reconciliation kept it open: "Reconcile mandatory supported-inquiry admission with
  growth §4's system-repair path and make leak checking non-optional before completion."

## Frozen identities

```
1c77c7d4996c2b42a976812deb1c917397fa97a5b07d27af1119b23b7c59416e  app/runtime/compiler.py
5a7d130f53cf1d3c5138c07850a3ee7693fcc288d3952feda1fb966c68bfd5e9  app/tests/test_change_compiler.py
```

## What changed (`app/runtime/compiler.py`)

- **Leak checking is not optional.** `forbidden_spans` is a required keyword on every compilation
  and must be a non-empty list (at least the alternative's own wording); omitting it is a
  `TypeError`, an empty list, `None` or a bare string is refused. Every free-text field (the three
  clauses and both scopes) is checked, whitespace/NFKC/format-character normalized, as before.
- **Two admissions, recorded on the candidate** (`grounds`, also in `as_dict`):
  - `supported_inquiry` — unchanged: a concluded *supported* inquiry grounds any kind, each
    clause's provenance drawn from the inquiry's fresh post-freeze evidence;
  - `confirmed_system_hypothesis` — growth §4 ("if a system deficit is a sufficient cause, a
    restoration experiment may come first; SPLI is not forced on every deficit"):
    `compile_system_restore(hypotheses, hypothesis_id, value, *, forbidden_spans)` accepts only a
    framework-issued hypothesis set in which the named hypothesis is family `system` and status
    `confirmed` — which the set itself allows only after every competitor was examined and over
    evidence outside the alternative/difference — admits kind `restore` only (learn/protect need an
    expert-judgment difference, i.e. an inquiry), and draws every clause's provenance from that
    hypothesis's own confirmation basis (a refuted competitor's evidence is refused).
- The unpromoted-store ban (own_alternative/difference/hypothesis/selector refs never in
  provenance) and issuance discipline hold on both paths.

## Tests: `test_change_compiler.py` 10 passed

The seven original cases now hand the forbidden material explicitly; new: the leak check is never
optional (missing/empty/None/str refused, scope leak refused); a confirmed system hypothesis
grounds a restore without an inquiry and records its grounds; the system path refuses learn/
protect, a refuted competitor's evidence, a non-system or merely proposed hypothesis, a foreign
set, empty forbidden material and a copied span.

## Not claimed

- Extracting the forbidden material automatically from stored alternative/philosophy content
  needs those stores; the compiler requires it from its caller.
- `app/runtime/memory.py` `compile_knowledge` (T058, closed) still defaults its forbidden spans to
  empty — a follow-up for the same discipline, recorded here rather than changed inside T057.
- No live patch application, persistence or operational activation (promotion/validation tasks).
