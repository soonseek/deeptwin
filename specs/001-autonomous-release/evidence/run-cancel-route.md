# Evidence — run-level cancellation: the `runs.cancel` route

- Date: 2026-09-18
- Task: the Continuation's "cancel/recovery routes" (api.md Runtime row: "start scoped run,
  cancel, recover/retry after outcome check"; runtime.md: "Cancellation first durably closes the
  dispatch gate, then requests owned transports/workers to stop … never claim durable
  cancellation if commit failed"; api.md: "Cancellation closes future dispatch, not proof of
  remote termination"; experience.md §9 row 294: new-dispatch closure and each call's
  termination shown separately, never a claim that provider usage ended from the local cancel).

## Frozen identities

```
1988da3f7825261e68c24d772e5ab124efb13738c6a58caf3283344f50b63220  app/runtime/ledger.py
8a340bc9a3144a098161b2049cfe3a8d1e395a4295f8a9e8f6a78daf18b048e7  app/services/runs.py
79c3e882b50e2fdb90419965bba1782626d85522e5071e0cfceda156e264a7dc  app/api/runs.py
d97c55ac868ba023259324b8b137380904fbaec4d7c6ce981dafced3361d8f13  app/api/routes.py
4e4a9df54c589e3f0953928bc9c384c2f1d4a6890a739ff44e1181227a91cf7f  app/api/route_contributions/runs-v1.json
db942dede8817617b5023b272f0aca8686b762e17f34d2976e0a1acdda7522e4  app/static/runtime.mjs
dd36fa151e1185c04788aebd6ab31357b0b00dc336f83fc99222ebfd2249e75e  app/tests/test_runtime_run_cancel.py
ab4ffd80d7a0757b6f7c84a07efaa62d74a43f6d5d3decf8931b9aab5e3ada63  app/tests/test_runs_api.py
689560b929b5f26c03e710b615685ffd2241f38178dfece1f3b596e2a9ff2aaf  app/tests/runtime.test.mjs
```

(The `ledger.py`, `runs.py`, `api/runs.py`, `runtime.mjs` and test identities frozen in the
earlier run-route, dispatch and GUI-logic evidence files are superseded by these.)

## What was built

- `app/runtime/ledger.py`: `RUN_PHASES = {created, cancelled}` — the run row's durable phase
  (previously frozen at `created` by the snapshot reader); `cancel_run(command_id, run_id)` — a
  replayable command that CASes the run to `cancelled` (revision +1) and reports `applied`; a
  cancelled run admits no new execution (`create_execution`) and no new attempt
  (`reserve_attempt`), both `DispatchBlocked`; `attempts_for_run(run_id)` — the read-only
  enumerator of every attempt of the run's executions. The run command touches no attempt and
  proves nothing about remote work.
- `app/services/runs.py`: `PHASES` gains `cancelled`; every receipt carries `cancellation`
  (`requested`, and per attempt its `phase`, `cancel_state`, `dispatch_gate`,
  `remote_terminal_observed` — the two facts kept apart); `cancel`: authenticate in the writer →
  manifest → under the run lock when no execution is live (a durable `run.stopped(completed)`
  means nothing to cancel → conflict) → `ledger.cancel_run` → `request_cancel` on every live
  attempt with one deterministic command per (cancel command, attempt), re-reading and repeating
  (bounded) when an attempt moved between the snapshot and the request →
  `run.stopped(cancelled)` once → the receipt from a fresh scheduler. When an execution is live
  the closure is durable without the lock and that execution ends the run itself, once. A
  cancelled run's resume is a conflict; a create replay reports it; the durable closure never
  depends on the executor (the receipt may not be buildable, the closure stands).
- `app/api/runs.py` + `runs-v1.json`: `POST /api/v1/runs/{run_id}/cancel` (`runs.cancel`,
  browser session, `work.command`), the same bounded preflight as resume; pins 18 → 19 routes
  (19 → 20 with the example contribution). `app/api/routes.py`: the public snapshot accepts
  every durable run phase.
- `app/static/runtime.mjs`: `PHASES` + `cancelled` (`취소됨`); receipts must carry
  `cancellation`; a cancelled run waits on nobody (an earlier rejection stays a past fact);
  `runView.cancellation`; `accessibleRows` spells `취소 요청됨: 새 dispatch 중단` and, per call,
  `게이트 닫힘|열림` and `원격 종료 미확인|확인됨` from the remote observation only.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 3 SHOULD, 2 NIT). Verified by the reviewer: the run phase
closes before any gate; the once-guard is atomic under the store writer; `create_execution`
replay precedes the cancelled refusal and `observe()` never creates executions; the
`reserve_attempt` refusal writes nothing first; an unknown run is 404 before the ledger command;
every other run-snapshot reader accepts `cancelled`; the GUI mirror pin holds. Closures,
RED-first:

1. MUST — the public snapshot route still required `created` and answered `storage_failed`
   for the whole vault after the first cancel → it accepts every durable run phase; the cancel
   test asserts the snapshot still serves.
2. MUST — a cancel racing a live execution produced two stop events, and a completion slipping
   between the completed-check and the closure returned 503 after durably applying → the check
   and the closure run under the run lock when no execution is live; a live execution ends the
   run itself with the single `cancelled` stop; the receipt comes from a fresh scheduler.
3. SHOULD — a mid-loop `request_cancel` failure (an attempt moved between the snapshot and the
   request) reported `not_retryable` although the run was closed and a retry completed → the
   attempt pass re-reads and repeats, bounded.
4. SHOULD — cancel was impossible exactly when the executor could not compile → the durable
   closure never touches the executor; only the receipt does.
5. SHOULD — the accessible rows stated neither cancellation fact → both rows added.
6. NIT — `rejected_human` was wiped on a cancelled run → kept (a past fact). 7. NIT — per-request
   cost (the run snapshot fetched several times, every attempt decoded per read) noted, bounded
   by executions × attempts per execution; the reason code stays `cancelled` (the event enum is
   closed; the cause is distinguishable through `cancellation.requested` and the approvals
   route).

## Verification

- TDD: RED retained — no `cancel_run` / `attempts_for_run`, 404 on the cancel path, the GUI
  phase mirror; GREEN after the ledger, service, adapter, descriptor, pins and module; the
  review's five RED tests (snapshot after cancel, cancel during a live execution, the revision
  race, closure without an executor, the a11y rows) failed before the closures.
- Tests: ledger **2** (replayable `cancel_run`, refusals, startup reconciliation and readers
  over the cancelled row; `attempts_for_run` per run); runs API **+6** (a waiting run cancelled and
  nothing resumes it, an approval included, one stop event, replay and re-cancel honest, the
  snapshot still serves; a completed run cannot be cancelled and the closed shapes; the gate of
  a live attempt closed with the cancel state reported and no terminal claim; cancel during a
  live execution ends the run once; a lost attempt revision race retried; closure without an
  executor); `node --test runtime.test.mjs` **14** (the cancelled receipt and rows); mirror 4.
  Covering (ledger, graph execution, dispatch, run trace, web owner integration, first party and
  dependencies, approvals, budget dispatch, checkpoints, settlement): **312 passed**; after the
  closures runs API / cancel / mirror / server API v1 / web owner integration **137 passed**.
  Ruff: no new findings (ledger 18/18, routes 0/0), the rest clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- Cancellation closes future dispatch and each live attempt's gate; it never claims remote
  termination (`remote_terminal_observed` is the ledger's own observation; `finish_cancellation`
  with transport evidence remains the worker path's). The scheduler stays uninterruptible: a
  live execution finishes its current step and then ends the run. No recovery/retry route yet;
  no DOM wiring; no model, tool or paid call.
