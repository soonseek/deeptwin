# Evidence — T031: B4 provider lifecycle deadline/cancel

- Date: 2026-09-13
- Task: T031 [US2] complete the B4 lifecycle deadline/cancel from
  preflight through actual owned process termination in
  app/codex_understanding.py and app/codex_rpc.py; retain the B1
  prepared-input contract (verification §5).

## Frozen identities

```
de80592bd4b9497a0df41c689c6c57f6e0309dcaa94e59d2fb149d29079ca105  app/codex_rpc.py
b66e5181c8593b0ee0b7770a0e7492779cb391f92d90e8edaa86a9e968effe0f  app/codex_understanding.py
60de7904f992b44b53263e5dff7372ba7ccf6d32e4e7b11008aa98724ec88468  app/tests/test_provider_lifecycle.py
```

## What was built

- **One lifecycle deadline** — `generate()` fixes `overall_deadline` at
  entry; a `_gate()` (cancel → `_CancelledBeforeTransfer`, deadline →
  `ModelError('timeout')`) runs after `start()` and after EVERY
  preflight call (account/read, config/read, skills/list, and the whole
  override-restart branch) and before `thread/start`. The turn-polling
  loop now spends the SAME deadline — slow preflight no longer grants
  the turn a fresh full budget, and the prepared input is never
  transferred once the budget is gone.
- **Cancel spends nothing** — a cancel that is already set returns
  `cancelled-before-transfer` before `find_codex`/factory: no transport
  object, no process, no call. A mid-preflight cancel stops at that
  exact call boundary (not one call further) and still closes the
  transport; the post-thread cancel/interrupt semantics are unchanged.
- **Owned termination confirmed** — new
  `codex_rpc.terminate_owned_process(process, grace)`: SIGTERM, bounded
  wait, SIGKILL escalation, bounded wait, and returns True only when
  the exit is CONFIRMED (`poll() is not None`). `CodexRPC.close()` uses
  it and records the honest outcome in `termination_confirmed`
  (None = no lifecycle claim yet; True/False after close).

## Verification (5 tests, TDD — import failed first)

- Cancel-already-set: `created == []`, result
  `cancelled-before-transfer`.
- Mid-preflight cancel: calls end exactly at
  `['account/read', 'config/read']`; `PRIVATE INPUT` never appears in
  any call (B1); transport closed.
- Deadline spans preflight: a 0.1s `skills/list` against a 0.05s budget
  refuses with `timeout`; `thread/start`/`turn/start` never called;
  input never transferred.
- Real processes: a polite child confirms via SIGTERM; a
  SIGTERM-ignoring child (verified armed via stdout) is SIGKILLed and
  confirms with `returncode == -SIGKILL`.
- End-to-end: `CodexRPC.start()` against a silent long-running child
  times out on initialize, and `termination_confirmed is True` after
  the failure path's cleanup.
- `ruff check` clean on the test; codex_rpc/codex_understanding keep
  only their pre-existing HEAD findings (2×I001, 2×BLE001 — verified
  via `git show HEAD:` copies). Codex suite 130 passed; full regression
  **3375 passed, 2 skipped** (was 3370).

## Notes

- The live provider path itself (real Codex account, paid runs) remains
  user-authorization-gated; everything here is scripted/offline plus
  real local child processes owned by the test.
