# T048 slice — run consent revocation, and the current consent before further dispatch (2026-09-23)

Status: **revocation landed; T048 stays open**. Still open: consent expiry, the design
arc's own production path, run creation from the intake page, and T049's browser case.

## What landed

- **`POST /api/v1/run-consents/{consent_id}/revoke`** (`run_consents.revoke`, work.command).
  - The body is exactly `{schema_version: "run-consent-revocation-command-v1", command_id}`.
  - The owner seals one `decision_record` per consent (`run-consent-revocation-v1`: the
    consent ref, the command, the time, the event sequence). The record is authored by the
    owner's human actor, with `approval.decided` carrying `decision: "revoked"` in the same
    transaction.
  - An exact replay returns the same revocation; another command over a revoked consent is a
    conflict.
  - A revocation is never undone.
  - The `approval.decided` decision enum gained `revoked`, and the event-metadata schema
    export was updated. The SQL event schema is unchanged.
- **Reading a revocation.** It is re-checked with the writer's whole discipline: the owner
  actor, the exact content grammar, the exact consent ref, and the decided event the record
  names with `revoked`. A malformed row at the revocation identity makes the consent unusable
  (`unavailable`); it is never ignored.
- **Consent reads** (`GET …/{consent_id}` and the record replay) now carry `revocation`,
  either `null` or `{command_id, revoked_at_utc}`.
- **The current consent** (runtime.md: verify the current consent before dispatch):
  - A revoked consent starts no run (`403 access_denied`).
  - `resume` and `recover` of a run started under it refuse (`403`).
  - A replay of the sealed create command also refuses unless the run already completed,
    because a replay dispatches too.
  - `cancel` stays available.

## Observed

- `test_run_consents.py`: **11 passed**, 3 of them new:
  - revocation is its own public fact
  - replay and conflict
  - the read shows it
  - no run starts under it; 404 for an unknown consent
  - a gated run under a revoked consent is not resumed, recovered or replayed (the executor
    is never called again) but can be cancelled
  - the revocation wire is exact, and it refuses without a session
- The affected suites passed: runs, consents and approvals, the route-count tests (installed
  routes 59 → 60), server, domain events and schema exports, event coverage, alternatives
  and versions. **1273 passed.**

## Still open

- **Expiry.** The consent command carries no expiry field yet. A time-bounded consent needs a
  new command version.
- **UI.** No screen offers revocation yet: the consent itself is not yet created from a screen
  (run creation from the intake page is still open).

## Expiry (same day)

- **`run-consent-command-v2`** adds `expires_at_utc` (the stamp format), which the owner
  chooses. It must lie ahead of the server's clock and within 366 days. That ceiling is a wire
  bound, not a product policy.
- The record is `run-consent-v2` and carries the expiry. v1 commands and records are unchanged
  and never expire. The projection states `expires_at_utc` (`null` for v1). A replay under the
  same command with another expiry conflicts.
- **`consent_current`** is the single check behind run start, `resume`, `recover` and the
  create replay. It refuses when the consent is revoked or its expiry has passed
  (`403 access_denied`), and it re-verifies the whole record discipline. Cancel stays
  available. An expired consent still reads back with its expiry.
- **Observed:** `test_run_consents.py` **12 passed**, with `test_runs_api.py` 39 in total. The
  expiry test covers:
  - refusal of a past expiry, an expiry beyond the bound, a malformed expiry, and an expiry on a
    v1 command
  - replay conflict on a changed expiry
  - a run started within the window
  - once the clock is advanced past the expiry: resume, recover and replay refuse without any
    new dispatch, the consent still reads, and cancel works

The "Still open: expiry" item above is closed by this section.
