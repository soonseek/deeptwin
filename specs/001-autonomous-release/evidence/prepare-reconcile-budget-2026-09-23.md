# Evidence — the prepare reconciliation's load-sensitive cases chased at cause (2026-09-23)

- Date: 2026-09-23
- Task: not a product slice — the regression's trustworthiness, the slice
  `environment-record-t048.md` recorded open: two cases in
  `test_provider_prepare_reconciliation.py` failing under load (a deadline checkpoint reporting
  `prepared` instead of `expired`; a missing outbox request file), mechanism not yet established.
- Host: Linux container, 4 vCPU, Python 3.12.3. On this host the module failed **alone**
  (9 of its first 10 cases), so the failure reproduced deterministically here.

## Frozen identities

```
df835689d70290866e3a39a6d15453b44af9310cf53ed88d79670485dfdb9ecd  app/deployment/mounts.py
502c308bb23414b1011e55549b8eb53d6fa754a92b8a0b7900902734db9bc0de  app/deployment/source_common.py
deee584e4615176f8d2a8f30c04de6693ed2d437fe3cac429814fbd7fb3a2e06  app/deployment/provider_prepare_records.py
a6ef47b4958637012fb5900545af3ca5edb264fe88425b9ef8ae1a47d601bb34  app/tests/test_mount_containment.py
4decc4adf72a811d1a88e0a472560e44fe137af6a8c2adf5149e4c24e9741f08  app/tests/test_provider_prepare_reconciliation.py
```

## Mechanism (established by measurement)

- `PersistentDeploymentPrepare._reconcile` sets a **cooperative one-second wall-clock budget**
  (`_provider_reconcile_deadline = started + 1`, contracts: deployment-prepare-journal §6,
  provider-request-integration). `reconcile_item` checks it (`before_deadline()`) before the
  lease work, before the stage and at the last pre-commit checkpoint; a spent budget returns
  with the intent still `pending` — honest, by design.
- A timing probe on the failing case: the journal pass left **0.66 s** of budget when the item
  began, and the item's own work took **0.97 s**, so the pre-commit checkpoint found the budget
  spent and the file was never renamed — exactly the recorded "missing outbox request file".
  The "`prepared` instead of `expired`" arm is the same budget exhausted before the checkpoint
  that samples the moved clock.
- A profile of that pass: ~2 s (profiled) of which the mount-boundary checks were the largest
  single cost — `PurePath.is_relative_to` called **28,527** times per pass (it walks `parents`,
  building a path per ancestor), inside `mounts.containing`/`verify_boundaries` and
  `source_common._source_mount_observations`, run on every source guard; and three deep copies
  of the 44 generated port schemas per pass (`provider_prepare_records._provider_schema_bytes`).
- Why the previous host passed alone: it was faster; the same work fits inside the second there.

## Fixes

1. **Product, behavior-preserving:** `mounts.within(path, root)` — `is_relative_to` by cached
   `parts` prefix — replaces every `is_relative_to` in the boundary checks. Pinned by
   `test_mount_containment.py`: a 2,000-example Hypothesis equivalence against
   `Path.is_relative_to` over absolute/relative/root/empty/`.`-bearing paths, plus the named edges
   (`/run-x` is not under `/run`; `/` contains everything absolute; `.` contains only relative).
2. **Product, behavior-preserving:** `_provider_schema_bytes` is `functools.cache`d — it returns
   an immutable tuple of bytes from the code-owned generator, so one deep copy per process.
3. Result: the item's work fell from 0.97 s to ~0.85 s (unprofiled) and the whole module passes
   **alone** on this host again (19/19 before the test change below).
4. **Test, isolation:** under four busy processes the real budget is still exhausted (4 of 18
   failed) — inherent to a wall-clock budget, not a defect. The module now applies the
   accepted amendment's pattern (provider-receipt-consumption.md: "one sampled fixed monotonic
   value and unchanged real time.time_ns … isolates history semantics from machine throughput")
   to every case through an autouse `cooperative_clock` fixture over `prepare_service`,
   `provider_prepare_service` and `provider_receipt_service` — `time_ns` and every other
   attribute stay real, so the deadline cases that move `time.time_ns` still move it. Cases that
   set their own clock (the capacity-16 arm, the budget-exhausted-after-stage case) still do.
   **One case stays on the real clock** (`…_cancel_publishes_marker[2]`), named in the module
   as a host observation that an unloaded host publishes within the budget — not a portable
   throughput proof.

## Considered and not kept

- Dropping the budget check from the last pre-commit checkpoint (the contract text names only
  currentness and expiry there). A RED-first test was written and went GREEN, but it
  contradicted the accepted `test_cooperative_budget_exhausted_after_stage_leaves_pending_without_rename`,
  which the provider-receipt amendment explicitly keeps unchanged. That is an accepted design
  decision, so the change and its test were reverted, not overridden.

## Verification

- RED: the module alone on this host, 9 of the first 10 failed; timing probe as above.
- GREEN: `test_mount_containment.py` 2; `test_provider_prepare_reconciliation.py` 18 unloaded;
  under four busy processes 17 passed / 1 failed — the one named real-clock case, by design.
- Neighbours: see the progress entry for the deployment/provider family run and the full
  regression on these bytes.

## Open, recorded

- **Starvation on a slow host (product risk, not fixed here).** Every `_reconcile` pass restarts
  the one-second budget from zero and each item re-verifies the whole journal and source graph.
  On a host where one item's pre-stage work alone exceeds the second, a pending publication is
  never staged by any pass — no retry loop or cross-run fairness exists (the contract says so
  explicitly). This host was ~0.2 s from that edge before the fixes. A real remedy (carrying
  budget across passes, or a smaller verification unit) is a contract change, recorded here for
  the deployment line rather than made unilaterally.
