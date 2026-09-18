# Evidence — the connected browser path: the `runs-v1` route contribution

- Date: 2026-09-18
- Task: resumption-plan Continuation "the connected browser path under the unchanged canonical
  plan" — the route layer of US3/T048 (`app/api/routes.py` side; `app/static/runtime.mjs` and the
  Playwright case T049 stay open). Precedent: the approvals route slice
  (`run-approvals-human-gate.md`, "the browser path to approvals") shipped the route before any
  DOM wiring; this slice does the same for runs. No DOM change.

## Frozen identities

```
495427c55fb0da57d8eb67586cd62f169223001a177ca93ef79c7a58c2faaf6a  app/services/runs.py
377ca86468430e26959e49fc6f075f089c1c5cc9cd00778f816a301ddebbce0b  app/api/runs.py
756d445bae3e67546fac5192668d623404752131088ea98346667b37400e32fb  app/api/route_contributions/runs-v1.json
f9fc6d16390dfc90c2bd52126250837d928ce1dc8197a5f2b11562ca49c71e23  app/api/first_party_catalog.py
5d8f176c803c39df2de73adb88b71157c2f6028de1a4a4955f43fa91a408b4a1  app/api/first_party.py
24af0f66a0e8e772ed323b2cadd85520df4d3ba63bc5d4c9e17a832f14983521  app/api/web_boundary.py
359e53f4547c4d8bc3020d3579b2be6b07b658c2738fdc46d1762213193116f4  app/server.py
e745fb3830f4c5f1db90e4e44be4a75ba96717e64f21a2bc5d6a8ddd855aad16  app/runtime/scheduler.py
f899887db6e1942c101ca6bdccbd5623e1613e448a6b505290a1b402ea54e330  app/tests/test_runs_api.py
```

(The `scheduler.py` identity frozen in `scheduler-projection-recovery-f9.md` and
`scheduler-attempt-dispatch-t040.md` is superseded by this one: `observe()` and the two outcome
identities below were added.)

## What was built

- `app/services/runs.py` (new): `PersistentRuns(domain_store, owner_authority, *, ledger,
  budget_book, approvals, executor)`. `create` authenticates the owner (POST + CSRF, re-checked
  inside the writer), validates the command (a stored `graph` reference and the run's
  `work_revision` / `environment` / `run_consent` / `budget_policy` references), and in one store
  writer transaction resolves the records, decodes the stored functional graph, compiles it
  through the injected executor, rebuilds the `BudgetPolicy` from the policy record's own content
  (hash verified), seals the `run_manifest` record keyed by the command (inputs, digests, budget
  session, start time, event sequence) and appends `run.started`; outside the writer (the ledger
  and the store share one database) it starts the budget session, creates the ledger run by the
  same command id and executes. A replay reuses the sealed manifest whatever happened after it; a
  command reused with any different input is a conflict. `resume` runs the head again; `read` is
  a no-execution projection. Execution is exclusive per run in this process. `run.stopped` is
  emitted once per ended execution (completion once, `cancelled` once for a rejected gate,
  `infrastructure_failure` per failed execution), its duration measured from the run's start; the
  once-ness is checked against the durable event stream, never memory. The phase is derived from
  the head: `awaiting_human`, `rejected`, `completed` (nothing pending), `created`, `running`.
- `app/api/runs.py` (new): the preflight (`/api/v1/runs` POST, `/{run_id}` GET/HEAD,
  `/{run_id}/resume` POST; the approvals paths keep their adapter; 4096 B, depth 3, items 32,
  members 8, strings 256; typed reference shapes; no query), the closed error partition, the
  router (201 create, 200 resume, GET/HEAD read with equal headers), and `run_services` requiring
  the approvals export. Descriptor `runs-v1.json` (`runs.create` / `runs.read` / `runs.resume`,
  `browser_session`, `work.command` / `work.read`), catalog entry before `deployment-prepare-v1`.
- `app/api/first_party.py` / `app/server.py`: `ApplicationContext.run_executor` and
  `create_app(run_executor=)` — the code-owned compilation authority and handler registry are
  trusted host wiring, never page input; without one the routes are honestly unavailable (503).
  The ledger's startup reconciliation runs at lifespan whenever a run executor is configured.
- `app/api/web_boundary.py`: the run route classification, body caps (4096 / 0 for reads), the
  preflight into `state["run_payload"]`, the error handler and the replay condition.
- `app/runtime/scheduler.py`: `GraphScheduler.observe()` — the bounded projection of the durable
  head with no execution, no resume and no approval request; `SchedulerOutcome.pending_node_ids`
  (node ids the head still has to visit) and `rejected_human` ((gate, scope) pairs the owner
  rejected) — allowlisted identities, never raw channel state.
- Pins: `test_web_owner_integration` 15 → 18 routes with the ids and contribution order,
  `test_first_party` 16 → 19, the outcome field pins in the graph-execution and dispatch suites.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (3 MUST, 4 SHOULD, 6 NIT). Verified clean by the reviewer: no
`database is locked` under fifteen concurrent creates against two hot readers (the ledger reuses
the store's writer lock and connection; the scheduler never runs inside a store writer); the
path partition (approvals paths, `/resume` reads, non-uuid ids, trailing slashes, extra or
nested members, oversize, unknown runs) refuses before any write; the event metadata validates;
responses carry a constant message, no exception text, and exactly the outcome's fields.
Closures, all RED-first:

1. MUST — a crash between the manifest transaction and the ledger run made the command
   unreplayable (a second seal with a fresh stamp conflicted forever) → the manifest is looked up
   by its deterministic id first and reused; the ledger run is created only when absent.
2. MUST — a graph with an untaken router branch never reported `completed` and never emitted
   `run.stopped` → `pending_node_ids` from the head's next nodes; `completed` iff nothing is
   pending.
3. MUST — two concurrent resumes executed the same node twice with contradictory stop events → a
   per-run non-blocking lock; a concurrent execution is `409 conflict`, never a second execution.
4. SHOULD — a command reused with a different consent or budget reference was accepted as a
   replay → every input is compared; any difference is a conflict.
5. SHOULD — `run.stopped` semantics were mis-stated → decided and documented: once per ended
   execution, completion once per run (a completed head is never re-run), `cancelled` once for a
   rejected gate, `infrastructure_failure` per failed execution; a resume after a failure is a new
   execution of the same run.
6. SHOULD — a rejected gate was reported as still awaiting and its resume as an infrastructure
   failure → `rejected_human` in the outcome, phase `rejected`, `run.stopped(cancelled)` once, 200.
7. SHOULD — a replay after the ledger run but before any execution only observed an empty head
   → the replay executes (the same path as resume, under the lock).
8. NIT — the resume command id is a receipt label (documented). 9. NIT — the stop duration is
   measured from the run's start recorded in the manifest. 10. NIT — the adapter catches only the
   service error family. 11. NIT — the graph is compiled on every request (noted, acceptable).
   12. NIT — the budget session is started but nothing reserves or settles here; the POST blocks
   its worker thread (both stated as non-claims). 13. NIT — this evidence file; the superseded
   scheduler identities named above.

## Verification

- TDD: RED retained — `create_app() got an unexpected keyword argument 'run_executor'` (the
  first HTTP case), then 400 / 503 at each missing layer until GREEN; the review's seven RED
  tests failed for their stated reasons before the closures.
- Tests (19): a browser-started run executes and is readable without execution (receipt shape,
  projection field set, events, exact replay, HEAD = GET headers, a second run, conflicts on any
  differing input); a gated run waits, records the approval through the existing route and
  resumes to completion; nine closed shapes refused before any write; unauthenticated 401, no
  executor 503, unknown run 404; the composition carries the routes; a router run with an untaken
  branch completes and is never re-run; a crash between the manifest and the ledger run is
  replayable; a replay before any execution executes; concurrent resumes execute once; a rejected
  gate is reported and stops the run once; a failed execution is stopped and a resume is a new
  execution.
- Covering (runs API, web owner integration, first party and dependencies, run approvals,
  deployment receipt API, graph execution, scheduler dispatch, import boundary, router
  composition, checkpoints, run trace): **365 passed** plus the adapted dispatch pin (10). Ruff:
  no new findings on the modified modules (server.py 3/3 pre-existing), the new modules clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No DOM, `app/static/runtime.mjs` or Playwright case (T048/T049); no model, tool or paid call
  (the tests' executor uses fixture handlers; the real attempt transport is exercised elsewhere);
  no cancel or recover route; no attempt layer in the run trace; no `pending_gate_requests`
  read; the projection never carries raw graph state; the budget session is started, not
  consumed; the run's inputs are owner-named references that must already exist (no producer of
  `environment`/`run_consent` records is claimed); UX-AC11 (T087) and the live worker run stay
  open or host gates.
