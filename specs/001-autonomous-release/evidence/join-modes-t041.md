# Evidence — T041: join modes, the ledger-recorded join selection and dependency-scoped failure; LangGraph late pending writes (2026-09-23)

- Task: T041 — "sealed branch activation, atomic join winner, visit-vs-attempt IDs and
  dependency-scoped failure … durable ledger CAS, concurrent-writer single-successor and restart
  recovery are not implemented by those pure functions".
- Host: Linux container, Python 3.12.3, langgraph 1.2.11.

## Frozen identities

```
ad2e123a489100765adf6c4cd991e877ee8698279fe6a6d26eb6b3e97fff9dc9  app/runtime/scheduler.py
82c95adaee1edafb21e2afeb6334ec8914e1247f9579effaf5decc45065170f2  app/runtime/checkpoints.py
eae8c2736aa5caa62170db775d5d7f0a8e3b3780c06244f3b574c56b419e5f6c  app/tests/test_graph_execution.py
b0ebf88519a715376430dabd4f563d70af76c8b44351f61c807729edd9d25d42  app/tests/test_langgraph_checkpoints.py
```

## Defect found first: the scheduler ignored every join mode

The graph schema accepts `all_selected`, `any_success` (with `tie_break: branch_id_lexical`) and
`collect` (`min_selected`/`max_selected`), each with `failure_handling: block | collect_failures`,
and the compiler projects them — but the scheduler ran **every** join as `all_selected` and ended
the run on **any** producer failure. A graph approved with `any_success` silently waited for all
branches and failed on the first failing one.

## What landed (app/runtime/scheduler.py)

- `all_selected`: runs once every activated producer is terminal (unchanged under `block`);
  under `collect_failures` it joins the successes after every branch finished.
- `any_success`: the first valid success wins; successes observed in the same step tie-break on
  the frozen branch-ID order; a later branch still runs and its result stays as evidence; every
  activated branch failing fails the join as itself (`node_failed:join`).
- `collect`: the maximum as soon as it is reached, else between minimum and maximum once every
  branch is terminal; below the minimum the join fails as itself.
- **The single compare-and-swap is the join's ledger execution record** (its selected parent
  executions): every evaluation first reads an existing record and adopts it — a restart after a
  crash between the record and the checkpoint, a late trigger, or a concurrent writer whose create
  conflicts with the other writer's record — so the successor runs once, from one selection.
- **Dependency-scoped failure:** a producer whose every consumer is a failure-tolerant join, and
  which is not attempt-bound, fails as durable terminal evidence (`<node>.failed`) instead of
  ending the run; a re-run replays nothing. Any other failure ends the run as before and a resume
  re-runs that visit. An attempt-bound visit keeps ending the run because its failure may be an
  unknown remote outcome only the owner's recovery can settle.
- Two scheduling guards the join work exposed: outside a bounded loop a node has exactly one
  visit, and every node defers until its activated producers completed — LangGraph triggers the
  successors of a deferring (empty) write too, so without the guard a successor ran before its
  join (caught by the new tests, not by the old ones, whose joins had no successor).
- Projection: `SchedulerOutcome.join_selections` and `.failed_node_ids`, rebuilt from durable
  markers (restart-invariant); `NodeContext.inputs` hands a join handler its selected producers.
  The runs route's public projection is unchanged.

## Defect found on the way: LangGraph late pending writes halted runs at random on Linux

- `test_graph_execution.py` failed 2–3 of every 5 runs on this host **before any change here**
  (a different case each time: `checkpoint journal halted` or `node_failed`), measured on the
  unmodified tree.
- Probe inside the saver's validation: the rejected rows were the input task's pending writes
  (`task_path "~__pregel_pull, __start__"`, channels `results/counters/branch:to:*`) arriving for
  the checkpoint **two back** from the head. LangGraph 1.2.11 (`pregel/_loop.py`) drains only
  delta-channel `put_writes` futures before putting the next checkpoint; ordinary pending writes
  are submitted to its executor and may land after the checkpoint that superseded theirs. The
  saver's rule "pending writes must target the current checkpoint" then halted the saver.
- Fix (`checkpoints.py`): pending writes still require a committed checkpoint, but a late row for a
  superseded one is journaled as that checkpoint's history only — never the head's state or its
  pending writes; `put` still refuses any parent but the head, so no fork is possible. The accepted
  test `test_unchanged_version_cannot_replace_state_and_old_writes_cannot_fork` encoded the wrong
  model of LangGraph's ordering; it now asserts the real invariants (head state and pending writes
  unchanged, a put from the old parent refused, the same after a journal replay).
- Result: `test_graph_execution.py` 5/5 green after the fix (was 2–3/5 failing).

## Tests (app/tests/test_graph_execution.py)

`test_any_success_takes_the_first_success_and_schedules_the_successor_once`,
`test_any_success_absorbs_failed_branches_as_evidence`,
`test_any_success_with_every_branch_failed_fails_the_join`,
`test_a_blocking_all_selected_join_still_fails_the_run_on_a_branch_failure`,
`test_all_selected_collecting_failures_joins_the_successes_after_every_branch`,
`test_collect_takes_between_min_and_max_successes` (3 cases),
`test_collect_below_its_minimum_fails_the_join`,
`test_the_ledger_record_fixes_the_winner_across_a_restart` (crash after the record, resume sees
another observation order and adopts the recorded winner),
`test_a_concurrent_writer_adopts_the_recorded_selection` (the loser's create conflicts; it adopts
the record — this one caught a real bug: the handler first received the stale local selection).

## Verification

- `test_graph_execution.py` 44 passed ×5 consecutive; `test_langgraph_checkpoints.py` 63 passed.
- Runtime neighbours (graph contract/execution, run approvals, runs API, result settlement,
  scheduler attempt dispatch, checkpoints, compiled tool dispatch, run trace): **303 passed**.

## Not claimed

- A fatal failure still stops the whole run at its step; independent branches continue on the
  resume, not concurrently (runtime.md says they *may* proceed).
- Routers, joins and human gates inside a bounded loop remain refused at build.
- The attempt-bound exclusion from absorption is by code, without its own test.
