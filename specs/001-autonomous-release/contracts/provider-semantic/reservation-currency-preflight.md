# Task47 reservation currency — independent interface preflight

Verdict: **READY for controller promotion of the currency-only correction.**

Findings: **0 Critical, 0 Important, 0 Minor.**

## Scope and authority

Read the entire proposed amendment
`.superpowers/sdd/resumption-plan/task-47-reservation-currency-amendment.md`, SHA-256
`abc13f808136b18b2c0d9eb4a81821861d04ecbb02410006e977f34f7de70632`.
Compared it with the retained complete literal appendix: §1 defines lowercase identifier I,
§2 assigns I to reservation.currency, and §6 requires equality with the frozen BudgetPolicy
currency. The controller supplied its direct unchanged-interface inspection of
`app/runtime/budgets.py:108`, requiring a string matching `[A-Z]{3}` for API currency.
No moving product code was inspected, tests run, helpers used or gateway amendment reopened.
Only this report was written. This is not the R1 implementation review.

## Assessment

The conflict is exact: lowercase-initial I and three ASCII uppercase letters have no common
value. The currency-only replacement permits the existing API policy representation while
preserving byte-exact equality to the actual frozen policy. It needs no budget implementation
change, conversion, normalization or default currency.

The specified validators are precise. Runtime full-string matching rejects trailing newlines;
the portable schema's string type, exact length three and anchored ASCII pattern jointly reject
them as well. Null, bool, mixed/lowercase, whitespace, digits, non-ASCII and wrong lengths are
excluded. The amendment correctly distinguishes this code representation from proof of ISO
registry membership or pricing authority.

The new C notation is explicitly limited to reservation.currency by the amendment's ONLY/only
scope statements; it does not redefine the appendix §7 control-observation C or other fields.
Model/account identifiers keep I. Reservation connection/model/body/window/amount/evidence
joins and all other admission checks remain required. A valid uppercase code different from
the frozen API policy must still refuse before send.

Compatibility and accounting boundaries are preserved: no canonical port/schema/hash change,
no alteration of existing API/subscription BudgetPolicy behavior, no migration of activated
records, and no new owned product path. Provisional/unknown API cost, usage=None and held
reservation remain unchanged. The amendment cannot confer reviewed-estimate authority or
justify settlement.

## Proof and promotion boundary

The named proof is sufficient for this narrow correction: an exact matching uppercase policy
code through composed admission and the actual dispatcher; a different valid code refused
before model send; malformed values refused by durable runtime and portable schema; unchanged
API/subscription policy, held reservation and lowercase model/account behavior. These are future
implementation requirements, not test results established by this preflight.

Controller may explicitly incorporate these exact amendment bytes while retaining original
snapshot hashes. This closes the identified type contradiction only; it does not waive any
I1–I15 finding, establish R1 correctness, or authorize production/live/native activation.
