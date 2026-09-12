# T013/T014 finite runtime budgets and atomic dispatch — offline evidence

Verified 2026-09-08 in the authoritative worktree
`/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure`. T013 and T014 are complete
for the bounded runtime budget/dispatch boundary. No provider, network, credential, Keychain,
paid API or user vault was used.

## Implemented boundary

`BudgetPolicy` has separate finite execution, design and growth profiles. Every profile bounds
model calls, tool calls, node visits, loop rounds, output bytes, concurrency, candidates and
wall time. API mode additionally requires an explicit ISO currency and positive caller-selected
microunit cap; subscription mode never invents a currency limit. There is no automatic paid
fallback or unlimited/zero-cost API default.

`BudgetBook` keeps canonical policy bytes, sessions, conservative reservations, actual/unknown
usage and a per-session hash-linked audit in the existing vault SQLite database. It validates
policy/schema/migration digests, exact accounting, lifecycle chronology, row bounds and a
nondecreasing persisted clock. A retry is a new charged reservation. Unknown provider acceptance
retains the conservative charge. Restart never resets the original wall deadline or counters.

The book now uses the same hardened `DomainStore` path connection rather than opening the stored
pathname directly. Directory/database ownership, modes, link count, inode stability and SQLite
sidecars are rechecked around each transaction. The exact budget schema is checked on every
public connection. Because all components share one app-owned database and no production trigger
is part of the migration contract, any trigger anywhere in that database fails closed before a
budget operation; case and attachment-table spelling cannot bypass this rule.

`RunSpec` freezes one `budget_session_id` plus one immutable `budget_policy_ref`. Creating another
session with the same policy cannot replenish a run. `BudgetDispatchRequest` must bind that frozen
session, policy and the attempt's reservation ID.

`RuntimeLedger.commit_budgeted_send_intent` performs all of the following in one `BEGIN IMMEDIATE`
transaction over the same database:

1. verify the startup session, owner, lease, deadline, run mode and immutable refs;
2. verify exact runtime and budget migration/schema state;
3. reserve finite budget and transition it to `dispatched` with its audit entries;
4. change the attempt to the may-have-sent barrier;
5. append the attempt journal, public dispatch event and idempotent command result;
6. after the final write, re-read the attempt, journal, event, command, reservation, session and
   immutable policy binding before allowing commit.

Only this path returns `DispatchPermit`, which includes the exact session/reservation/policy,
deadline, lease fence and originating `BudgetBook` identity. The production consumer accepts only
that exact one-shot process-local object and rechecks durable ledger and budget state immediately
before use. The isolated ledger lifecycle helper returns a different `LedgerOnlyPermit`, which the
production consumer rejects. Command replay and process restart never mint another permit.

## Failure-first and verification

The initial atomic suite failed because no shared budget/send-intent unit existed. Independent
review then reproduced and fixed: a trigger deleting the reservation after send intent, a public
unbudgeted permit path, substitution of another budget owner, session-based cap reset in one run,
database symlink/path replacement, and an uppercase table-name trigger extending a lease. Both
lowercase and uppercase/cross-table trigger forms now fail before mutation. Transaction rollback
tests inject failures after reservation without relying on a schema hook.

Final focused result at the hashes below:

```text
python -m pytest -q app/tests/test_runtime_budgets.py \
  app/tests/test_runtime_ledger.py app/tests/test_runtime_budget_dispatch.py
112 passed in 28.82s

app/tests/test_runtime_budget_dispatch.py
14 passed
```

The independent final reviewer reran the trigger, same-run new-session, path-swap, replay/restart
and unbudgeted-permit reproductions and returned `CLEAR` with no T014 P1/P2 blocker.

| File | SHA-256 |
|---|---|
| `app/runtime/budgets.py` | `bba11db58a474fd0b9e0ec8d92d24d9aeb1669a55e1d7879d46c83a5b33ee14f` |
| `app/runtime/ledger.py` | `5570f642b69ae3caeb1ed5fb47f5a0a3c1dd4a63894a78772e1d36713ee0cfea` |
| `app/tests/test_runtime_budget_dispatch.py` | `3c98ba0e8d09cad5a35e3c1d8c32a85324cf7138efd8c12fbf8eca556f987704` |
| `app/tests/test_runtime_ledger.py` | `5dcc36773af9afc5ae3ed6f10fe0d76a03860c4b66c3ea0565e5675c13947854` |
| `app/tests/test_runtime_budgets.py` | `e8835b1824a8ae9b3d8afd4939a45e09d358fe19e4df47ba7ad3fc90dee93bb8` |

## Honest limits

This closes reservation plus send-intent atomicity, not remote exactly-once delivery. A committed
intent still means the provider may have started, and uncertain usage remains charged. Terminal
result plus artifact sealing plus final budget reconciliation is a later shared transaction in
T016/runtime integration. HTTP authentication, permission grants, tool dispatch, process stopping
and provider price truth are also separate tasks.

The hash chain detects incoherent application-state corruption; it is not an external MAC and does
not defeat a same-account attacker who can coherently rewrite the whole database and code. The
implementation makes no stronger cryptographic or power-loss guarantee.
