# T011/T012 — bounded durable runtime ledger evidence

Date: 2026-09-07  
Scope: `app/runtime/ledger.py` and isolated temporary-SQLite tests in
`app/tests/test_runtime_ledger.py`.

## Approved API

The API was reported before implementation and approved with the explicit constraint that
budget-row ownership remains in `BudgetBook`.

- Frozen inputs: `RunSpec`, `ExecutionSpec`, `OwnerIdentity`, `AttemptSpec`,
  `ResultObservation`, and `CancellationObservation`.
- Write commands: `create_run`, `create_execution`, `reserve_attempt`, `renew_lease`,
  `advance_attempt`, `commit_send_intent`, `request_cancel`, `finish_cancellation`,
  `accept_result`, `write_checkpoint`, and `reconcile_startup`.
- Dispatch boundary: `commit_send_intent` first commits the write-ahead state and returns one
  process-local `DispatchPermit`; `consume_dispatch_permit` consumes that exact object at most
  once. Replaying the durable send command deliberately returns no permit.
- Reads: `get_run`, `get_execution`, `get_attempt`, `read_checkpoint`,
  `checkpoint_for_replay`, `recovery_snapshot`, `lookup_committed_result`,
  `result_observations`, `events`, and the paged `attempt_journal`.

Every mutation takes a canonical UUID `command_id`. Revision-sensitive transitions also take
an exact expected revision. Lease operations bind the complete `OwnerIdentity`—owner UUID,
PID, process start time, and nonce—and not PID alone.

## Durable invariants exercised

- The runtime schema is additive to the initialized `intake.sqlite3`; legacy and immutable
  domain rows remain readable. Run, attempt, and terminal-result reference indexes are checked
  against canonical hashed bodies and exact domain-record keys before safety-sensitive reuse.
- Attempt reservation commits the attempt ID, immutable idempotency key, exact envelope,
  runtime-profile and budget-policy refs, exact budget-reservation UUID, full owner identity,
  lease, journal row, command receipt, and allowlisted event in one SQLite transaction.
- The send-intent CAS commits `may_have_started`, journal, `attempt.dispatched`, and command
  receipt before any permit exists. Failed storage commits return no permit. Concurrent issue
  and consume tests admit one permit only; lease/deadline expiry, cancellation, reconciliation,
  session fencing, or state corruption fail closed.
- `replay` and `snapshot` runs cannot issue external-dispatch permits. A retry must be the next
  attempt number and every predecessor must be either definitely unsent or a final, matching
  observed remote failure/timeout/cancellation with final usage. Active, successful, denied,
  late-timeout, `outcome_unknown`, or any sent predecessor with conflicting quarantined late
  evidence blocks retry.
- Terminal acceptance is a first-writer CAS. Exact command/observation replay is stable;
  semantic duplicates and nonmatching late observations are append-only. The accepted result
  pointer and exact sealed result ref are revalidated. Equal timestamps retain explicit
  insertion sequence. Typed observations contain only UUID/ref/enum fields—no raw provider
  body or free-form details.
- A result first observed at or after the frozen whole-attempt deadline is retained as late
  evidence while the attempt becomes `timed_out`; it cannot turn the attempt into success.
- Cancellation durably closes the gate first. Local transport closure, owned-process exit,
  remote terminal observation, and usage finality remain separate. A local close cannot prove
  remote cancellation, and a pre-send cancellation cannot claim a remote or unknown effect.
  A storage failure creates only process-local emergency inhibition and never fabricates a
  durable cancellation.
- Checkpoint cursors are bounded opaque bytes, hashed, revision-CAS written, and omitted from
  command payload/result receipts. Replay requires explicit startup reconciliation. Recovery
  validates latest checkpoints for active runs; historical completed-run checkpoints cannot
  exhaust the active recovery bound, while selecting a historical checkpoint still validates
  its digest and exact attempt/execution/envelope binding.
- Startup construction and reads do not reconcile or enable dispatch. Explicit reconciliation
  fences the active process session, compares exact owner nonce/start identity, marks unsent
  work definitely unsent, preserves live sent work as recovery-pending, and converts an
  unobserved sent effect to terminal `outcome_unknown`. It reports zero redispatches and never
  recreates an old permit.
- Clock values reject booleans, rollback, negative/out-of-range values, future owner starts,
  and lease-expiry overflow. Public/journal/result reads are explicitly bounded or paged.

## Shared runtime migration ledger

The shared registry contract is:

```sql
CREATE TABLE runtime_migrations (
  component TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0),
  sha256 TEXT NOT NULL,
  PRIMARY KEY(component,version)
)
```

Ledger migration identity is
`('ledger', 1, 'f4979b5e263a04b54081e29fb17be1b12143bf2535faef4525f50b50b324251c')`.
The digest is SHA-256 over the 17 ordered ledger DDL strings joined by a single `\n`, including
the shared-table statement. Installation verifies the table shape and required integer/positive
version semantics, the exact ledger digest, and all-or-none ledger-owned tables. Rows owned by
other components are preserved. A pre-existing `('budgets', 1, ...)` row and a subsequent
ledger row coexist under the composite primary key; the focused test proves this initialization
order without importing or changing `BudgetBook`.

## TDD and test results

The authoritative RED used the project environment:

```text
/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests/test_runtime_ledger.py -q
23 failed during import because app.runtime.ledger did not exist
```

The final focused GREEN after implementation and adversarial review fixes is:

```text
/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests/test_runtime_ledger.py -q
35 passed in 11.84s
```

The final shared-migration/component regression is:

```text
/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests/test_runtime_ledger.py app/tests/test_runtime_budgets.py -q
91 passed in 12.66s
```

The latest application regression excluding the independently in-flight Claude adapter test is:

```text
/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests -q --ignore=app/tests/test_claude_api.py
1740 passed, 1 warning in 25.39s
```

An unfiltered run did not execute tests because collection encountered the unrelated
`app/adapters/claude_api.py` top-level `import anthropic` while that parallel slice was still in
flight (`ModuleNotFoundError: No module named 'anthropic'`). No dependency was installed or
changed for this ledger task; an unfiltered regression must be rerun after that owner makes the
adapter import-safe.

The tests use new temporary vaults and synthetic SQLite transaction/trigger/tamper/concurrency
faults only. They perform no live provider calls, credential access, user-database access,
network calls, package installation, or external process termination.

## Explicit integration limits

This is a persistence/integrity slice, not an authority boundary or an exactly-once claim.

- `reservation_id` is exact and durable, but this module does not prove that a
  `runtime_budget_reservations` row exists. There is not yet a public cross-module unit of work
  that atomically reserves `BudgetBook` capacity with the attempt/send intent or settles budget
  with terminal acceptance. That integration remains required; this evidence does not claim
  data-model §2 transaction (a) or (b) in full.
- Consent/grant/purpose checks and current authorization remain caller responsibilities.
  `DomainStore`'s permission layer is process-local and is not converted into authority by a
  ledger row, lease, immutable ref, or dispatch permit. The caller must revalidate permission
  immediately at the actual provider/tool boundary.
- The ledger does not perform provider/tool I/O, process killing, budget release, scheduler
  replay, artifact creation, or semantic handoff validation. `attempt.dispatched` means that
  send intent is durably committed and the effect may have started—not remote acceptance.
- Runtime events are atomically sequenced within this ledger table, but are not yet integrated
  with the single application/API EventEnvelope/SSE sequence. Checkpoint bytes are opaque, so
  the scheduler must enforce the no-credentials/no-canonical-approvals content rule.
- The additive transaction currently uses `DomainStore`'s private connection/writer hooks
  because no public shared unit-of-work API exists. Replacing that coupling is integration debt.
- Reopen/trigger tests exercise transactional and logical crash boundaries, not a real process
  kill, filesystem power loss, provider idempotency implementation, or hardware durability
  qualification. Unknown remote effects therefore remain explicitly unknown and are never
  automatically redispatched.
