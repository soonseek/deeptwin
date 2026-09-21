# Task47 reservation currency type — proposed bounded correction

DRAFT pending independent preflight and explicit controller promotion.

## Conflict and exact correction

Literal appendix§2 declares reservation.currency:I. I is the canonical lowercase
identifier (`^[a-z][a-z0-9._:-]{0,127}$`), while appendix§6 requires byte-exact
equality to frozen BudgetPolicy.currency. Existing API BudgetPolicy.create in
app/runtime/budgets.py:108 requires type str and fullmatch `[A-Z]{3}`; subscription
policy has no currency. No string satisfies both grammars, so the positive API
reservation is impossible under the literal type declaration.

Replace ONLY reservation.currency:I with reservation.currency:C, where C is an
exact string of three ASCII uppercase letters, matching the existing BudgetPolicy
API currency grammar. Runtime must use full-string validation; portable JSON schema
uses type string, minLength=maxLength=3 and pattern `^[A-Z]{3}$`. This is the existing
ISO-shaped code representation, NOT evidence of ISO registry membership or pricing.

At admission require exact equality to the actual frozen API BudgetPolicy.currency
and preserve all reservation/model/connection/body/validity/amount/evidence joins.
No case folding, whitespace trimming, lowercase compatibility, currency conversion,
default USD, subscription currency or alternative API-budget branch is introduced.
Only the reservation currency field changes type; model/account identifiers retain I.

API accounting remains provisional/unknown, usage=None and reservation held. This
correction cannot establish exact cost, convert uncertainty to zero, settle a budget
or mint review authority. Existing runtime BudgetPolicy and published canonical port
schemas/hash bytes remain unchanged; all implementation fits Task47's existing26paths.
Original snapshots remain byte-identical; a promoted master addendum explicitly
adopts this corrected field type. No production/live/native activation follows.

## Required proof

- Exact uppercase code equal to real API BudgetPolicy currency passes the composed
  reservation/model admission and existing actual dispatcher path.
- Another syntactically valid uppercase code mismatching that policy refuses before
  model send; no automatic conversion or policy rewrite.
- Lowercase/mixed case, null, bool, digit, whitespace/newline, non-ASCII and wrong
  length values fail both durable runtime validation and the exported portable schema.
- Existing API/subscription BudgetPolicy behavior, provisional reservation retention
  and lowercase model/account identifier grammar remain unchanged.

Recommendation: correct this one type, not runtime currency or equality. Cost is
one narrow validator/schema change and focused fixtures; if wrong, that unregistered
record contract requires revision rather than any external financial side effect.
