# Evidence — Task 25 slice 2b: populated-generation fence

- Date: 2026-09-18
- Task: Task 25 (worker-private probe channel; prerequisite for Task 24), slice 2b —
  T018-foundation transport. Plan entry: `resumption-plan.md` "### Task 25", bullet 2b.
  Contract: `contracts/extension-worker-probe.md` §6. Intent: the 2026-09-16 proposal §3
  (populated endpoint currentness and retained resources).

## Frozen identities

```
fff137dcd22558e2e81446a7d210f85f867c1a0589c316e906a7a08ccaa76c50  app/workers/ipc_root.py
f837bd9bd174e37bedb7b88c33e9817952aa4220143ab6506f812b7077bb2702  app/tests/test_ipc_populated_fence.py
```

## What was built

- `app/workers/ipc_root.py` (appended; `GenerationLease`, `acquire_generation`,
  `MetadataGenerationLease` and `acquire_generation_metadata` untouched; one pre-existing
  helper hardened):
  - `PopulatedGenerationFence` (nonconstructible, uncopyable, unpicklable, repr shows only
    `closed`): borrows a held `GenerationLease` and owns exactly one additional no-follow
    boot-secret descriptor plus the leaf root and metadata observations. `recheck_current()`
    requires the borrowed generation to be open, opens the absolute pair root search-only,
    compares the current and held root identities (uid `METADATA_UID`, pair gid, 0o710), the
    named and held endpoint identities (responder uid, pair gid, 0o2710), the named and held
    `generation.lock` / `boot-secret` metadata stats, then rereads the exact 32 secret bytes
    through its own descriptor and compares them in constant time to the generation's
    secret; the bytes are dropped immediately. It permits populated endpoint files
    (`worker.sock`, `listener.json`) — the absence-only lease is unchanged. `close()`
    releases only the owned descriptor; the generation's shared lock and descriptors stay
    held ("borrowers close nothing").
  - `_retain_populated_generation(spec, generation)`: exact types, open generation, every
    fallible observation taken before the fence object exists, initial recheck, and an
    unwind on any `BaseException` (IpcRootError and non-OS errors re-raised as they are,
    OS errors mapped to the sanitized integrity error).
  - `_read_exact_secret` now clears the partial or drifted bytes before raising, so a failed
    reread leaves no secret reachable through the error's traceback frames (this also
    hardens `acquire_generation`, whose behaviour is otherwise unchanged).

## Review (independent, adversarial) and closures

Verdict on the first cut: REJECT (small fixes). All closed RED-first:

1. REJECT — reread bytes reachable in `_read_exact_secret`'s traceback frame → cleared before
   raising; tests walk the traceback locals after a forced short reread.
2. SHOULD — a half-built fence could surface a raw `AttributeError` → observations precede
   construction; an OS error from `fstat` while retaining is the closed integrity error.
3. SHOULD — owned descriptor leaked on a non-IpcRootError during the initial recheck or
   `__enter__` → `BaseException` unwind on both; tests count descriptors.
4. SHOULD — the tamper test passed through the stat compare → replaced by the load-bearing
   cases: an `os.replace` of a correct-shape secret between acquiring the generation and
   retaining the fence (only the byte compare can tell), and a per-inode frozen-stat case
   (a naive frozen stat had made the lock compare fail first — corrected).
5. SHOULD — missing negatives → truncated / hardlinked / symlinked secret, deleted lock,
   root replaced by a symlink, endpoint owner drift (root-only, honest skip), `__enter__`
   failure closes the descriptor, rotation still excluded after the fence closes while the
   generation lives.
6–7. NITs — docstrings say "leaf root and metadata observations" (every path component is
   opened no-follow); the descriptor-count comment is accurate.
- Confirmatory re-review: ACCEPT — every finding CLOSED with probe evidence (a restored
  pre-fix `_read_exact_secret` fails the traceback assertion; `compare_digest → True` fails both
  reread tests; failing the 2nd/3rd `fstat` raises the closed error with no descriptor change).
  Its three NITs were folded in afterwards: descriptor ownership moves to the fence in one
  step (`_closed`, `_secret_fd`, local zeroed together) so no asynchronous-exception window
  can double-close or reach `close()` on a half-built fence; the unwind test fails the 2nd and
  3rd `fstat` call (the retain function's own observations) with a call counter; the
  truncated-shape case's traceback assertion is annotated as the stat-compare path.

## Verification

- TDD: RED retained — `AssertionError: populated fence missing` ×12; closures RED first
  (traceback-leak assertion and descriptor-count assertion failed), then GREEN.
- Covering: **110 passed, 1 skipped (endpoint owner drift needs root)** — fence 20,
  metadata lease, ipc_root initializer, worker listener. Ruff clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No listener fence, mount check, probe service, observer or admission (slices 2c–3
  remain); the fence holds no lock of its own (the borrowed generation's shared lock
  excludes rotation; the caller's ordering closes the fence before the generation); no
  positive Linux authentication claim; the actual worker image and container/socket
  runtime are Docker/colima host authority; no GUI.
