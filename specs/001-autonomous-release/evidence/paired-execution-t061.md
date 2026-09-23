# Evidence — T061 closed: isolated paired execution and partial-scope effect tracing (2026-09-23)

- Task: T061 — "frozen related-queue/baseline/candidate/reset/evaluator/budget plans and isolated
  paired execution …; trace partial-scope downstream effects (FR-022/023/025)". The frozen plan
  and round-recording contracts existed (evidence/comparisons-t061.md); "real paired queue
  execution" was recorded open.

## Frozen identities

```
9ac9fb2b38aeeef695bbf599da1123bba508c204f28793cd3fc3bf2a42ed13a8  app/services/paired_execution.py
e8d866424cc3073290aa7d6af8dddb7c14ffb97284fa616d435c1a12bb0a12f2  app/tests/test_paired_execution.py
```

## What landed (`app/services/paired_execution.py`)

- `execute_paired_round(plan, *, items, baseline, candidate, evaluator, reset_root,
  declared_changes, round_value)`: both sides run every frozen queue item on the **real
  scheduler**, each (side, item) run in its **own fresh vault and runtime ledger** under the
  plan's reset root (run mode `isolated-comparison`; a work revision, environment, consent,
  budget policy and run manifest sealed in that vault, bound to the plan by id and digest). No
  run can read another's output; the pairing is the only link. The reset root must start empty.
- The **evaluator is code-owned** and scores what each run durably produced, per item, as exact
  decimal strings (floats refused), or declares the item invalid with reasons. The round is
  recorded through `record_comparison_round` against the exact frozen plan: any invalid item or
  failed run makes it `invalid` with every reason (a run failure is named by exception type,
  never its message), and only a fully valid round carries metrics — the exact per-metric mean,
  `utility` included — never a zero for a failed measurement.
- **Partial-scope downstream effects**: per item, the nodes whose durable result content differs
  between the sides, and the ones outside the downstream closure of the nodes the candidate
  declared it changed (`unexplained_nodes`), which a partial change must explain.
- `remove_isolated_runs` discards the isolated vaults once the round is recorded.

## Tests (`app/tests/test_paired_execution.py`): 6 passed (+ 6 comparison contract tests)

Valid round over two items: four distinct vaults, disjoint run manifests, exact utility and a
15.5 mean, writer/publish changed and nothing unexplained; a difference at `intake` outside the
declared writer change is unexplained; an invalid item invalidates the round with no
measurement; a crashing candidate run yields an invalid round with the completed pair, without
leaking the exception text; bad inputs refused before anything runs (empty/non-dict items, one
side twice, undeclared or unknown changes, no evaluator, a foreign plan, a non-empty reset root);
an evaluator outside its contract or with a float metric stops the round.

## Not claimed

- The sides here are code-owned handler registries; paired rounds over model-dispatching graphs
  need the provider attempt transport wired into the runtime (T090/T049) and would spend budget
  per run under the plan's policy.
- Persisting rounds in the growth chain and the experiments UI (T066) are separate tasks.
