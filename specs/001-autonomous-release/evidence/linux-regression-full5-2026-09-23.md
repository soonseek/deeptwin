# Linux full regression (full5) and the fixes it led to (2026-09-23)

## full5

Run on a fresh worktree at `13233c6`, Linux x86_64, running as root, with
`DEEPTWIN_AGE_RUNTIME_ROOT` set:

```
6 failed, 9489 passed, 4 skipped, 369 subtests passed in 5637.14s
```

All six failures were in the provider worker-transport family. On a quiet machine four
reproduced every time. Two of those four, the owned-control lock contention case and the
cancel-in-settlement case, also failed at `91341e8^` and at `6b6fbb9`. They predate this day's
slices.

## Root causes and fixes

1. **The first dialogue paid a multi-second schema build inside its deadline.** A worker's
   first request built the canonical provider validators (`_port_validator`). That build
   generates all 44 port schemas and meta-validates them with `check_schema`: **5.0 s cold** on
   this host, against a 3 s dialogue deadline. Both sides then waited on each other until the
   deadline: the server was still building, and the client waited for artifact credit.
   Whether a test hit this depended on whether an earlier test had already warmed the
   `lru_cache`.
   - Fix: `prewarm_port_validators()` runs in `ProviderPortService.__init__`, so the validators
     are built at worker start and never inside a dialogue.
   - The test harnesses now construct the service before accepting a connection, as a worker
     does.
   - The meta-validation itself is kept.
2. **A peer reset on Linux read as "uncertain" instead of "closed".** On AF_UNIX, a peer that
   closes with our bytes unread yields `ECONNRESET` on Linux and EOF on macOS. The three frame
   readers now map `ConnectionResetError` to `TransportClosed`, still `outcome_unknown`:
   `broker._read_exact`, `ExtensionConnection.read_duplex` and the semantic connection's
   reader. Other `OSError`s stay `TransportUncertain`. This gives both platforms the same
   behaviour.
3. **`ExtensionConnection.recheck()` raced `close()`.** A concurrent close cleared `_generation`
   and `_fence` between the closed check and their use, raising `AttributeError`. The method
   now snapshots both and answers the closed-set `ListenerIntegrityError`.
4. **The metadata drift test assumed a non-root runner.** Its "owner" drift faked the expected
   owner as `(0, 0)`, which equals the real owner when running as root. The fake owner now
   always differs from the tree's actual owner.

## Observed after the fixes

- Worker, transport and provider suites (listener, IPC fences, gateways, semantic
  codec/contracts/records/vertical/worker, send gateway, artifact stream, coordinator,
  dispatch, response capture, worker boundary): **579 passed, 2 skipped**.
- `test_provider_metadata.py`: 19 passed, 1 skipped.
- `test_provider_semantic_owned_connection.py`, run eight times in a row: 44/44 in four runs,
  and one or two failures in the others. Before the fixes it failed four cases every run.

## Still open

The remaining owned-connection failures are narrow concurrency-window cases whose outcome
depends on thread scheduling. Typical assertions:
- a drift sample count `>= 1`
- `StreamCancelled` observed, where an `owned_connection_unavailable` sometimes wins the race

They are recorded here as open, not as flakes to ignore. Also open: the Linux Chromium
download-name case recorded earlier.

## full6 (after the fixes)

Run on a fresh worktree at `3f8b32e`:

```
1 failed, 9495 passed, 4 skipped, 369 subtests passed in 5554.61s
```

The owned-connection cases did not fail in full6. One case failed:
`test_provider_semantic_vertical.py::…retains_api_reservation[USD-valid-None]`.

- **Cause:** a test-owned barrier gave a whole semantic dialogue 2 s to reach ledger
  acceptance. Repeated isolated runs of that test before the fix showed one failure in three.
- **Fix:** the barriers (`accept_entered`, `accept_release`, the dispatch join) are now 10 s.
  They are test synchronisation, not product deadlines. A dispatch that fails before acceptance
  is now reported with its own error rather than as a timeout.
- **Observed:** `test_provider_semantic_vertical.py` **83 passed**.

## Browser suite: the Linux download-name case closed

- **Cause.** The download-name failure (`suggestedFilename() === 'download'`) was the runner's
  locale. With no `LANG`, the process runs under POSIX/C, and Linux Chromium cannot name a
  download with a non-ASCII original name, so it falls back to the generic "download". The
  server's `Content-Disposition` (`filename*=UTF-8''…`) was correct throughout.
- **Fix 1.** The test launches Chromium with a UTF-8 locale.
- **Fix 2.** The work screen's download link now carries the original's name as its `download`
  attribute. It used to be empty. Path separators and control characters are replaced.
- **Observed.**
  - `browser-owner-material-intake.test.mjs`: 3/3 passed in five consecutive runs.
  - All browser tests (`app/tests/browser-*.test.mjs`): **89 passed, 0 failed**.
  - All non-browser node tests: 164 passed.
