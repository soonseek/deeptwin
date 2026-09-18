# Evidence — the owner's recovery: `runs.recover` and the retry after a sent attempt

- Date: 2026-09-18
- Task: the Continuation's "recovery/retry route after an outcome check" (api.md Runtime row:
  "recover/retry after outcome check") and T040's open item "retry after a sent attempt". The
  retry is admitted only by the ledger's own retry-safety proof and only on the owner's explicit
  recovery command — never by default, never after an unknown outcome — and it is evidenced by
  the next attempt of the same execution in the ledger (experience.md §7: past attempts stay
  distinct).

## Frozen identities

```
0bbadc61c462bb196d22cfb92702d6a42a75db272653f6ba7dc71bc6b21302b9  app/runtime/node_attempts.py
c7bb9e307d682deddd728f6c87f846b12af7cdc69b8545a92c6c299ed1efaa30  app/services/runs.py
96f6d36e6071e9fb0bb4c9bb6238bf6f53ca492ad3e847a7580f2f6308031a9b  app/api/runs.py
2d9e737620854886e7016c7701dd50973b1a9f2ae0d47bc78b5364a1be258592  app/api/route_contributions/runs-v1.json
df9cd8c21a05f0a4c9b96b445a76e783dbe49906ee863122e8d2e60edc1f7135  app/static/runtime.mjs
034038a77dc818382b5feda283452061d8979c3f65f7b2aadfcb7d8193c74b08  app/tests/test_scheduler_attempt_dispatch.py
847a8a1bc50a7fd0171fd5f9d884c12bf6511e62ed39e191e988549fc7b0d88b  app/tests/test_runs_api.py
2f29a9997963cf22d0a45d120a21081c94d6e9485f66121b0d0642b8d6a7f8d8  app/tests/runtime.test.mjs
```

(The `node_attempts.py`, `runs.py`, `api/runs.py`, descriptor, `runtime.mjs` and test identities
frozen in the dispatch, run-route, cancel and GUI-logic evidence files are superseded.)

## What was built

- `app/runtime/node_attempts.py`: `NodeAttemptDispatcher.build(..., retry_after_terminal=False)`.
  In the send-replay branch, a dispatcher built for the owner's recovery continues to the next
  attempt number of the same execution when the ledger row proves the earlier attempt terminal
  (`failed` or `timed_out`), the remote terminal observed, the usage final and no late evidence
  recorded (`_observed_terminal`, mirroring the reserve's own proof; a `cancelled` attempt is
  excluded — nothing in tree settles its budget). `MAX_ATTEMPTS_PER_VISIT` (4) bounds unsent
  continuations and recovery retries together (`attempt_bound`). A spent budget is refused
  before any reserve (`attempt_budget_exceeded`, from the book's remaining counters and again
  around the send), so no open attempt row is ever stranded by a spend cap.
- `app/services/runs.py`: `recover(request, run_id, payload)` — authenticate in the writer,
  manifest, a completed run is a conflict, then the head runs again under the run lock with a
  scheduler built by the executor for recovery (`retry=True`, passed only then); a cancelled run
  is a conflict; the recover command id is a receipt label. Every receipt's `cancellation`
  attempt rows carry `attempt_no`, so past attempts stay distinct.
- `app/api/runs.py` + `runs-v1.json`: `POST /api/v1/runs/{run_id}/recover` (`runs.recover`,
  browser session, `work.command`); pins 19 → 20 (20 → 21 with the example contribution).
- `app/static/runtime.mjs`: `runRoutes().cancel/recover`, observer `cancel`/`recover` over the
  shared closed `{command_id}` body (`commandBody`; `resumeCommand` kept), attempt rows carry
  `attemptNo` and the accessible call rows read `시도 N 호출 …`.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (0 MUST, 4 SHOULD, 5 NIT). Verified by the reviewer's probes: each
recovery takes exactly one more attempt and the fifth is refused without a send; every
attempt's reservation finalizes and the book returns to zero active reservations; a deadline
quarantine (`timed_out`, remote not observed) is never retried; a crash after a retried attempt's
send is quarantined at startup as unknown and never re-sent; completed / awaiting / cancelled /
unknown runs answer 409 / 200 (observe) / 409 / 404; recovery shares the resume's per-run lock.
Closures, RED-first:

1. SHOULD — the dispatcher's proof omitted the late-evidence clause the reserve applies (a late
   observation made the reserve refuse with the ledger's error, not this module's typed reason)
   → the clause added; the late test pins no second attempt.
2. SHOULD — a spent budget surfaced as a stranded open attempt row and an infrastructure
   failure → refused before any reserve, typed `attempt_budget_exceeded`; the service can only
   surface it as `unavailable` (closed enums), stated here.
3. SHOULD — the `cancelled` arm admitted a retry whose reservation stayed dispatched (the
   ledger's finality is not the book's) → dropped from the dispatcher's proof.
4. SHOULD — the bound was named for the unsent case only → `MAX_ATTEMPTS_PER_VISIT` /
   `attempt_bound`, documented.
5. NIT — the completed check in `recover` runs outside the lock (a completion racing it returns
   the completed receipt; the next recover is a conflict). 6. NIT — a cancelled run whose executor
   cannot compile answers 503 before the cancelled conflict (as resume). 7. NIT — the executor
   protocol gains an optional `retry` keyword passed only on recovery (an executor without it
   fails only there, as 503). 8. NIT — `attempt_no` on the receipt's attempt rows and the
   `시도 N` prefix. 9. NIT — the shared command body renamed.

## Verification

- TDD: RED retained — no `retry_after_terminal`, 404 on the recover path, the browser routes;
  GREEN after the dispatcher, service, adapter, descriptor and module; the review's RED tests
  (late evidence, budget exhaustion, the retry proof, attempt numbers) recorded before the
  closures; one adapted expectation (a cancel attempt row now carries its number).
- Tests: dispatch **+4** (retry only on recovery and only after an observed terminal, an unknown
  outcome never retried; late evidence forbids the retry; the budget stops recovery without a
  stranded row; the proof never admits cancelled or unsettled attempts); runs API **+2** (the
  owner recovers a run whose sent attempt failed by one more attempt through a real dispatcher
  and a flaky fake transport — resume never re-sends, the second attempt completes the run, the
  receipt lists both attempts with their numbers, later recoveries are conflicts; recovery of
  waiting / cancelled / unknown runs); `node --test runtime.test.mjs` 14 (routes, observer,
  attempt numbers, rows). Covering (dispatch, runs API, extension transport, mirror, web owner
  integration, first party and dependencies, checkpoints, run trace, cancel, approvals): **249**
  then **140** after the closures. Ruff: clean on every changed Python file.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No retry without the owner's command, without the ledger's proof, after an unknown outcome
  or after late evidence; at most four attempts per visit; each attempt reserves and finalizes
  its own budget; no attempt is ever re-sent. No worker message beyond `status`, no model, tool
  or paid call; the injected fake transport only in tests. The DOM half stays open.
