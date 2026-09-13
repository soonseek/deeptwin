# T050/T051 — own-alternative entry contracts (US4)

Date: 2026-09-13
Status: implemented and unit-verified contract slice; **T050/T051 remain open**
(no domain persistence, no editors/UI, no diagnosis/inquiry consumption)

## Exact scope

`app/services/alternatives.py` implements the growth journey's entry gate per
contracts/growth.md:

- `OriginalExecution.from_untrusted`: the preserved node/task execution boundary
  (work revision, environment, boundary id, exact input/output artifact refs,
  handoffs, tools, model bindings, explicit observation gaps) — never a post-hoc
  reconstruction.
- `Selector.from_untrusted`: the seven contract kinds
  (whole/text_span/table_range/page_region/image_region/time_range/
  structured_path), a bounded locator, the exact original version digest as
  `source_hash`, and preserved `confirmed|proposed|unresolved` alignment.
- `accept_own_alternative(original, submission)`:
  - **G-01:** work descriptions, revision instructions, review approvals and
    comments raise `NonAlternativeSubmission` carrying their own kind — never
    promoted; an empty draft (no alternative artifact) is likewise a
    `NonAlternativeSubmission("empty_draft")`.
  - Derived/mock material (`synthetic: true`) returns a distinct
    `SyntheticAlternative` whose `is_user_learning_evidence` is False.
  - Exact binding: the original artifact must be an output of the boundary; the
    alternative must be a distinct artifact; whole coverage carries no
    selectors; partial coverage requires 1..64 non-whole selectors whose
    `source_hash` equals the exact original artifact digest.
  - **G-02 scopes:** `evidence_scope` is exactly the selectors (or `whole`),
    `unreviewed_scope` is stated (`outside_selectors:<digest>` / `none`), and
    `impact_scope` is always `pending_investigation` — partial evidence never
    narrows semantic impact, and unreviewed area is never claimed as confirmed
    intent. Unconfirmed alignment is preserved, not upgraded
    (`fully_aligned`).
  - Deterministic `as_dict` and a content-addressed `own_alternative` ref.

Tests: `app/tests/test_alternatives.py` (8) — partial/whole acceptance with exact
binding and scope separation; four preserved non-alternative kinds; empty-draft
rejection; the synthetic separate type; six exact-binding violations; alignment
preservation; strict shapes and determinism.

```text
python -m pytest -q app/tests/test_alternatives.py
8 passed
ruff check app/services/alternatives.py app/tests/test_alternatives.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,095 passed, 2 skipped, 369 subtests passed, 1 known warning
```

## Frozen content identities (SHA-256)

```text
b9a9d34fa766e3ca5eb062b0d83faa18a15cacecf3714182475c752a0006012d  app/services/alternatives.py
56a2db08b49fe4d6716c322b2127a1de480e85db3d7bc979a88b17944bdb84a1  app/tests/test_alternatives.py
```

## Not claimed

No domain-store persistence of alternatives, no in-place editors or selector UI
(T052/T053), no browser flows (T054), and the diagnosis/inquiry stages (T055+)
do not yet consume these objects. No independent audit of this slice has run.
