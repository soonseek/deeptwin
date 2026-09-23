# T060 slice — observed difference after a freeze, every unknown stated (2026-09-23)

Status: **slice landed; T060 stays open.** Showing real hypotheses, inquiries and change candidates
needs a connected explanation generator. That generator comes from qualified model authority
(T035/T077) and is absent here.

## What landed

- **Server** (`PersistentAlternativeDrafts.observe_difference` and `read_difference`; two routes
  in `runs-v1`, route count now 54). They sit at
  `…/runs/{run}/artifacts/{aid}/alternatives/{alt}/difference`: POST observes, GET reads.
  - The accepted alternative is re-issued from the stored `own_alternative` record through
    `accept_own_alternative` against the stored boundary, and has to read back exactly. Nothing
    from the wire is trusted.
  - The bytes come from the original artifact and from the alternative's own draft or file blob,
    which is sha-checked.
  - `observe_differences` (T055) produces the observation, and `diagnosis.record_difference`
    records it. The record is a `difference` record: one per alternative, idempotent, parented on
    the alternative, with positions and operations only.
  - The response states `hypotheses: not_generated` (all five families listed, none examined),
    `inquiry: not_opened` (no confirmed judgment hypothesis, so nothing is asked),
    `change_candidates: none`, and `impact_scope: pending_investigation`.
- **GUI** (`app/static/inquiry.mjs`, `#run-inquiry` on the observe page) opens automatically
  after a freeze from the editor or the alternative-file form. It shows:
  - the observations
  - the evidence scope next to the unreviewed area
  - each competing explanation as "검토되지 않음", with the generator's absence
  - the reason no question is asked, and that answering is never required
  - the reason no change candidate exists

  The panel has **no input control**, so nothing asks the owner for an answer.

## Observed

- `test_alternative_drafts_api.py` **8 passed**, 1 of them new: a difference exists only after
  observation, is idempotent and sealed, and an unknown alternative gets 404.
- `inquiry.test.mjs` **2 passed**.
- `browser-inquiry.test.mjs` **1 passed**, in real Chromium against the supported server: freeze,
  the sealed difference, the stated unknowns, zero input controls, no page errors.
  `browser-alternatives.test.mjs` still passes 3 of 3.
- The affected Python suites: 191 passed.

This is synthetic evidence from a scripted test actor. No real user alternative, hypothesis or
answer exists.
