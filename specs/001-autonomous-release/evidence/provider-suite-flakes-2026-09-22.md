# Evidence — the provider suites' order/timing failures chased at cause (2026-09-22)

- Date: 2026-09-22
- Task: not a product slice — the regression's trustworthiness. Since the merged-tree reconciliation
  every full run (`pytest app/tests deploy/tests`, ~9,350 tests, ~83 min) failed one to three
  cases in the parallel orchestration's provider/deployment suites, a different case each time,
  every one passing alone; the loop recorded them under "order/timing-dependent" three times.
  This iteration found the causes (an independent investigation agent with reproductions; the
  fixes applied here) instead of recording a fourth.

## Frozen identities

```
36092495d292b15c580fa6a203be69b0e8e43c1ebea74d8a3d17b5d27ee646ab  app/tests/provider_source_reader_fixture.py
51d020100f9ea4f55ef3ef7b4929c8a2d33f37309d697d82a2da0971d083cec8  app/tests/provider_receipt_fixture.py
93eb800141a11b969336f6bbbd5ef10a29ed2abe80616db09fedaeae46e66af9  app/tests/provider_conformance_fixture.py
11a11847ab7ff1e67a837dcb34a545335e1240500e4c3bcbc14ad2e222d294d3  app/tests/test_provider_conformance_lifecycle.py
f28fa0b7b7c0c8ec5876a4ec4052ee961cebb19cb9c57b11e5a28e0850088965  app/tests/test_provider_semantic_owned_connection.py
920f699eec5ad16aef86eba7aef3349bec20d33b0e5e0cad9d99bd188467ceeb  app/tests/test_provider_service.py
88cca8258bfd0cd1343ee62c2f6b3077002899f2fd871d7dddfac49aba287b33  app/tests/test_extension_handshake.py
```

## Causes and fixes

- **Cause A (cross-cutting, reproduced): a 3 GB heap left by one test, collected by a 13–30 s
  cyclic garbage-collection pause inside a later test's IPC.** `ReaderTree` recorded every
  `os.open` into an unbounded `opens` list read by two modules only; the 64-execute capacity
  test (`test_provider_conformance_lifecycle.py::…lifetime_capacity`) made ~17 M entries
  (51.8 M live objects, RSS 3.1 GB). The tree sits in a reference cycle (its observer closure
  over its own bound method in `publication_tree`), so it is freed only by a gen-2 pass — which
  landed in whichever later test crossed the threshold: measured 28.7 s inside the final-wall
  case and 30.4 s inside the late-finalization case, the latter failing with exactly the
  recorded `{'socket_peak': 3, 'error': ProviderServiceError}`. Fix at cause: recording is opt-in
  (`ReaderTree(record_opens=True)`, set by the `reader_tree` fixture whose two modules read
  `opens`), and the receipt-context fixture collects in its own teardown so any residue is
  never a pause inside a later test.
- **Cause B (cross-cutting, reproduced): the fixture worker's 5 s budget became a 5 s per-socket
  timeout.** `_provider_conformance_worker` served each connection under
  `Deadline.after_ms(5000)`; the final-wall and late-finalization cases freeze the clock, so
  `remaining()` is a constant 5.0 and every worker `recv`/`send` got `settimeout(5.0)` — while
  one vector already costs 2.0–2.6 s unloaded (4.4–6.3 s under load; the client's checkpoints
  re-verify the whole journal). The chain: worker recv timeout → `TransportUncertain` →
  `ProviderServiceError` → the client's credit send meets a closed peer → `ArtifactStreamError`
  → `_Stop("protocol_error")` — the recorded `('text-refusal-v1', 'protocol_error', 16)` with
  `completion_count == 2`. A 5.5 s stall injected between the projection-body offer and the
  client's credit reproduced it exactly; with the worker at the product's own connection window
  (30 s, the listener's) the same stall passes. Fix at cause: the fixture worker serves under
  `WORKER_BUDGET_MS = 30_000` (the join bounded accordingly), and the late-finalization case
  advances its clock only once the worker has finished (its last fence followed the capture by
  milliseconds).
- **The owned-connection prepublication cases** (`[deadline]` 2/10, `[payload]` 1/6 alone):
  after the cancel control-result the server also sends its `provider-semantic-final-v1`; the
  client tears down right after the control-result, so the server's send meets a closed peer
  (`TransportUncertain`) — a transport outcome by the test's own design, asserted absent. Fix:
  the server's box may hold a transport closure there, never anything else (24/24 after).
- **The whole-dialogue budget case**: reproduced deterministically with a 0.3 s delay — the
  server charges the projection acknowledgement under the lowered ceiling and closes; the
  client's write then fails uncertainly. Fix: the client's uncertain write is tolerated, the
  server's own `ProviderServiceError` and open listener remain the facts.
- **The handshake requester-id case**: `client.close()` from the main thread does not wake the
  client thread's `recv` on macOS, so it exits only at its own 5 s deadline while `join(5)`
  starts milliseconds later. Fix: both ends are shut down before the close.
- **The installation service's clock floor** (`_now`: `now >= clock_floor_ms`): only a backward
  wall-clock step fails it (reasoned, not reproduced; no fixture patches that clock). Left as
  the deliberate refusal it is; recorded.
- **The receipt-sources 240-entries case** (`deployment_source_invalid`): not reproduced — a
  prefix run of all 203 preceding files in suite order passed (gc 0.19 s, fds 25, threads 1).
  The failing site's `raise … from None` hides the cause and the test sits exactly at the 240
  cap; the instance-id/digest hypothesis is unsupported (the context and profile come from the
  same per-test app). Recorded open; this iteration's full run carried an observation-only
  plugin that logs the suppressed cause chain of any failure.

## Verification

- Reproductions: the stall probe (5.5 s) fails under the 5 s budget and passes under 30 s; the
  budget case reproduced with a 0.3 s delay and passes after; the prepublication variants
  24/24 and the budget case 3/3 after; the seven touched modules **328** together; the two
  conformance cases **6** (the parametrized late-finalization variants and the final-wall case).
  The capacity test still takes ~15.5 min alone: the heap is gone, the remaining cost is the
  product's own O(n²) journal re-verification (`prepare_service._journal` re-verifies the whole
  history on every call) — a product performance note, not changed here.
- Ruff: no finding introduced (the orchestration's files keep their own pre-existing findings).
- Full regression on the frozen identities above, with the observation-only monitor (per-test
  fds/threads/RSS, the longest garbage-collection pause, the suppressed cause chain of any
  failure): **9,350 passed, 0 failed, 2 skipped** (Linux-only), 369 subtests, 1h19m — the first
  wholly green full run since the merged tree; the longest collection pause of the whole run
  **0.25 s** (previously 13–30 s), no failure chain logged. The seven identities above were
  unchanged across the run.

## Boundaries kept

- No product change: every fix is in test fixtures and test expectations that were wrong about
  timing or transport outcomes; the product's behaviour under load was right each time.
