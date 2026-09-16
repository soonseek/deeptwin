# Evidence — T055 (reopened scope): trace slicing over real preserved runs

- Date: 2026-09-17
- Scope: `app/services/run_trace.py` (new) + read-only
  `RuntimeLedger.executions_for_run` — the "actual trace slicing over
  real runs" that evidence/diagnosis-t055.md left open. The traces come
  from runs the actual scheduler executed over a real SQLite ledger and
  checkpoint journal; no fixture-declared observations.

## What was built

- **`read_run_trace(ledger, run_id, compiled)`** — exact
  `RuntimeLedger`/`CompiledGraph` only; the run must exist; the checkpoint
  journal must be bound to this exact graph/authority (a journal written
  under another compilation refuses — a trace is never assembled against
  the wrong graph). Executions are read in recorded insertion order with
  their node, loop index, recorded parent executions and creation time;
  the only thing taken from the checkpoint journal is the durable result
  reference per execution (channel `results`), never cursor bytes or raw
  channel state. `observation_gaps` lists recorded visits without a
  durable result (a failed or interrupted visit); `checkpoint_revision`
  pins the journal head; `node_ids` carries the static node set.
- **`slice_trace(trace, *, boundary_node_id, loop_index=None)`** — one
  boundary execution (a loop node needs its loop index; an unexecuted
  node cannot be sliced), its transitive ancestors by recorded parents,
  its direct dependants, and `excluded_node_ids` — statically possible
  nodes that never ran (e.g. the router branch that was not activated).
- Issued, immutable values (`is_issued_trace`); read-only; no model,
  tool or replay call.

## Verification (6 tests, RED first on the missing module)

- Linear run reads back as an ordered trace with parents and results;
  pinned field sets exclude raw state and cursor bytes; a failed run
  (handler failure) shows the gap and survives ledger reopen; loop
  iterations are distinct ordered executions with loop-visit parents;
  slicing a router run keeps `choose` as ancestor, `join` as dependant
  and `revise` as excluded, and refuses an unexecuted boundary or a
  wrong loop index; exact ledger/run/graph binding is required.
- Ruff lint/format clean on the new module and test; the ledger keeps
  its pre-existing lint state (verified against HEAD).

## Frozen identities

```
3b3bdf353ca767fe02bc17427e7541ba40865a8cc3346a041c9af61cb0a9b145  app/services/run_trace.py
70e6a8040b43aabd30036b0b75229e06b4a0d3af9167c02b617ff35c77da471c  app/tests/test_run_trace.py
d36e605f341d5b49bd96abd0b3df28108980a5ef076b7da1b96472042d52e34c  app/runtime/ledger.py
```

## Limits

- Not whole T055: format-aware artifact differences and hypothesis
  proposal still consume caller-recorded observations; attempts/tool
  child executions do not exist yet in scheduler runs, so the trace has
  no attempt layer; handoff/artifact bytes are not read.

Full regression (same command): **5710 passed, 1 skipped, 1 warning, 369 subtests passed in 672.80s (0:11:12)**, exit 0.
