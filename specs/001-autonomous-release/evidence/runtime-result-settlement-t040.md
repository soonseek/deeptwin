# Evidence — T040 slice: atomic semantic acceptance and budget settlement

- Date: 2026-09-18
- Task: T040 (Continuation) "the atomic semantic acceptance + budget settlement" — the open item
  named in `tasks.md` T040 and in `resumption-plan.md` Task 6 ("transport evidence … does not
  release unknown-use reservations"; preserve that boundary in the runtime integration slices).
  The public `RuntimeLedger.accept_result` and `BudgetBook.settle` each own a transaction, so
  calling them in sequence can be torn between the accepted result and the reservation.

## Frozen identities

```
c994aab957b6ad2333cd32567785ad1ad3e965111f4ef5eb12272f3d5fe539f6  app/runtime/budgets.py
b5c0d2c5a4195e8bb0e034134b27e63699ac8785a7a7110611d93a429e3285dd  app/runtime/ledger.py
ee81a2f03358b44673a6d38066a4bc4a60ce3000cf3c8eb4b94b8268b1a060fd  app/tests/test_runtime_result_settlement.py
```

## What was built

- `app/runtime/budgets.py`: `BudgetUsage` — a frozen typed value of the known usage counters
  (`create(...)` validates every dimension as a bounded nonnegative integer, `candidates`
  explicit, `api_microunits` optional; `as_dict()`); `BudgetBook._settle_in_transaction(db,
  request_id, *, usage_finality, usage, session_id=None)` settles one dispatched reservation on a
  caller-owned transaction over this exact DB (an exact-transaction/`sqlite3.Row` guard as the
  clock-watermark precedent, the transaction schema assertion, an optional session binding,
  `dispatched` only, unknown usage retained with an audit row, known usage finalized or recorded
  as an overage) and returns `{"request_id", "state", "usage_finality"}` re-read from the row;
  the public `settle` builds the `BudgetUsage` up front and delegates to it (now returning the
  same dict); `_reservation_state_in_transaction` is a side-effect-free read.
- `app/runtime/ledger.py`: `accept_result` wraps the shared `_accept_result`;
  `accept_result_and_settle(command_id, observation, *, budget_book, usage)` refuses before any
  write an inexact `BudgetBook`, a book on another vault, an inexact `BudgetUsage`, a usage that
  does not match the observation's finality (`final` needs the counters; `provisional`/`unknown`
  take none and retain the reservation as unknown usage) and forged counters (rebuilt through
  `BudgetUsage.create`); inside the ledger's single `BEGIN IMMEDIATE` transaction it asserts the
  budget schema, replays by the command kind `accept_result_and_settle` with the usage in the
  payload, refuses a reservation shared by another attempt and binds the settlement to the run's
  frozen budget session, classifies the result exactly as before and, for `accepted`, settles
  the attempt's reservation on the same connection; a result arriving at or after the deadline
  quarantines the attempt as timed out and retains a dispatched reservation as unknown in the
  same transaction; duplicate, late and reused-observation outcomes carry `settlement` None;
  permits are revoked after the commit as before.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (no MUST). The reviewer verified with scratch probes that the
settlement path never opens its own connection or re-enters the budget lock, that the session
clock watermark written on the shared connection rolls back with a forced `_finalize` fault, that
a six-thread race settles exactly once, that replay with a different usage, a different
observation or the plain command kind is a `CommandConflict` with no budget change, that late and
duplicate results write nothing to the budget tables, that overage records the actual counters,
and that `provisional → unknown` agrees with the plan's Task 6 boundary and `contracts/runtime.md`.
Closures, all RED-first in the settlement suite:

1. SHOULD — `_settle_in_transaction` had no exact-transaction/Row guard (a raw autocommit handle
   could settle without its audit row) → the clock-watermark guard added (`CorruptBudget`).
2. SHOULD — the settlement trusted `spec.reservation_id` without binding; an attempt in another
   execution carrying the same reservation id (reachable only through the test-only unbudgeted
   send-intent hook today) finalized the first attempt's reservation → a reservation shared by
   another attempt is refused (`LedgerError`) and the settlement is bound to the run's budget
   session (`ReservationConflict`), both before any write.
3. SHOULD — a hand-built `BudgetUsage` with negative or non-integer counters failed only inside
   the transaction → rebuilt through `BudgetUsage.create` before the transaction opens.
4. SHOULD — a result at or after the deadline quarantined the attempt as timed out with unknown
   usage but left the dispatched reservation stranded → retained as unknown in the same
   transaction and surfaced in `settlement`.
5. SHOULD — test lint (unused import, `dict()` call, unused unpack) and a vacuous final
   assertion → cleaned; the sequential-methods test now shows the stranded reservation released
   only by the public `settle`.
6. NIT — return-value docstring corrected. 7. NIT — public `settle` now validates the counters
   before the row lookup (unknown request id with bad counters raises `ValueError` first);
   all callers are tests. 8. NIT — the reused-observation outcome documented. 9. NIT — a
   duplicated vault path check dropped. 10. NIT — public `settle` returns the settlement dict.

## Verification

- TDD: RED retained — `ImportError: cannot import name 'BudgetUsage'` (7 cases erroring) before
  any production change; GREEN after the two modules; two test-side slips corrected (the
  commands table column is `kind`; the typed reason is `transport_unknown`); the review's five
  RED tests failed for their stated reasons (missing guard, no `LedgerError`, two transactions
  opened, `settlement` None, `settle` returning None) before the closures.
- Tests (12): accepted result and settlement commit together with exact replay and one audit
  row; unknown and provisional finality retain the reservation; finality/usage mismatch, inexact
  types and a foreign vault refused before any write; duplicate and late settle nothing; a forced
  `_finalize` fault rolls the acceptance, the observation and the command back and the reservation
  stays dispatched; overage; the sequential public methods are not the integration; the exact
  transaction guard; a shared reservation and a foreign session refused; counters validated
  before the transaction; the deadline quarantine retains the reservation as unknown.
- Covering (settlement, ledger, budgets, budget dispatch): **124 passed** before the review,
  **129 passed** after the closures; `test_known_usage_requires_explicit_candidate_count…` caught
  a first draft that defaulted `candidates` to 0 (made explicit). Ruff: no new findings on the
  two runtime modules (18/18 and 11→10 pre-existing), the test module clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No provider, worker or paid call; no scheduler dispatch yet (the next T040 slice: worker/attempt
  dispatch through the scheduler); no change to the public `accept_result` classification, the
  permit revocation or the budget accounting; T039/T040/T041 remain open.
