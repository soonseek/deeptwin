# Evidence — Task 25 slice 2c: extension listener accept/connect and fences

- Date: 2026-09-18
- Task: Task 25 (worker-private probe channel; prerequisite for Task 24), slice 2c —
  T018-foundation transport. Plan entry: `resumption-plan.md` "### Task 25", bullet 2c and
  the macOS test-honesty paragraph. Contract: `contracts/extension-worker-probe.md` §3
  (per-connection rules stay with slice 3), §4, §6. Intent: the 2026-09-16 proposal §3.
- Builds on: slice 2a (`broker._extension_*_handshake`, 9b87945) and 2b
  (`ipc_root._retain_populated_generation`, dcd0851).

## Frozen identities

```
b3ab1cf789bf6863f9be5472e5c1773de3760c58b481b366857575d90a333da7  app/workers/listener.py
e5841fea9756119ee60e0903b1c5c74477b51a6d631f9bc558be482de291da7e  app/tests/test_extension_listener.py
```

## What was built

- `app/workers/listener.py` (appended; existing `WorkerListener`, `accept_authenticated`,
  `connect_authenticated`, `verify_listener` untouched):
  - `_extension_mount_fence(root, *, read_only)` over the bounded `deployment.mounts`
    helpers (`_read_mountinfo` seam): the slot's pair root must be exactly one mountpoint
    with the side's mapping (read-only for control, read-write for the worker), no mount
    nested below it, no visible same-device alias of its backing path; an unreadable table
    fails closed. The compose deployment shape (overlay root, kernel pseudo filesystems,
    docker-managed `/etc` files, every slot volume on the host state device) passes; a bare
    host that bind-mounts the slot out of its root filesystem is refused as an alias — the
    same rule the worker metadata source applies.
  - `ExtensionConnection` (nonconstructible, uncopyable, unserializable): owns the socket,
    codec, generation, populated-generation fence, the listener record it was verified
    against, its side, and the kernel peer credentials retained at connect (control side;
    the responder wrapper verifies them before the hello but returns only the session, so
    the accept side records none — a deferred retention, stated, not a check skipped).
    `recheck()` re-runs the populated fence, the listener record fence (`_verify_record`
    equality) and the mount fence; any failure closes. `read`/`write` mirror
    `AuthenticatedConnection`; close order fence → codec and socket → generation.
  - `_accept_extension_authenticated(worker, *, deadline)`: profile check, re-acquired and
    fenced generation (generation id and endpoint identity equal to the listener's), the
    worker's readiness record AND readiness/socket file identities re-verified (a
    re-created `listener.json` with identical bytes is another inode and is refused), mount
    fence read-write, then the transport accept, the extension server handshake (peer
    verified before the hello; requester boot ID learned from it), the mount fence once more
    after the handshake; every failure after the generation was acquired unwinds socket,
    fence and generation; `IpcRootError` maps to `ListenerIntegrityError`.
  - `_connect_extension_authenticated(root, spec, *, requester_boot_id, deadline)`: profile
    check, pair-channel validation, `verify_listener`, populated fence, mount fence
    read-only, `connect_verified` (socket identity compared with the record, peer retained),
    the extension client handshake; generation ownership transfers from the verified
    listener; every failure after readiness verification unwinds.

## Review (independent, adversarial) and closures

Verdict: ACCEPT, conditional on one test correction; SHOULDs folded in RED-first:

1. SHOULD (blocking) — the server-side recheck assertion in the socket-swap test passed
   because the main thread lacked the worker mount view, not because of the swap → the test
   claims the worker view first, so only the swap can be what the worker side refuses.
2. SHOULD — no positive case with a realistic mount table; the parent's suspicion that the
   same-device alias clause would refuse every host was disproved by the reviewer against a
   full compose container table → that table is now the positive fixture (worker slot
   read-write passes, control's view of another slot passes, the wrong mapping fails).
3. SHOULD — pre-accept fences documented as if covering the accepted connection → the
   mount fence re-runs after the handshake; the docstring states the observations are
   pre-connection and that the probe service rechecks before the first read and after each
   reply.
4. SHOULD — accept-side record fence discarded the readiness identity → readiness and
   socket identities compared with the listener's own; test re-creates `listener.json`
   byte-for-byte and the accept refuses (the listener's own close then reports its
   violation, as the existing listener tests expect).
5. NIT — `acquire_generation`/`verify_listener` outside the unwind (mirrors
   `connect_authenticated`) → stated in the docstrings.
6. NIT — peer credentials verified but not retained → retained on the connect side as
   `ExtensionConnection.peer`; the accept-side retention is recorded as deferred.
7. NIT — only the server seamless path asserted fail-closed → the requester path with the
   real `connect_verified` is asserted to refuse before any socket, while the listener is
   live.
8. NIT — async-exception window at the ownership handoff, precedent-consistent with
   `connect_authenticated`; noted.
- Reviewer-verified: no double close on connect failure after the fence exists; every
  accept thread joined; error classes mirror `AuthenticatedConnection`;
  `DeploymentSourceUnavailable` is a `DeploymentSourceError` so the unreadable-table branch
  is real; the thread-keyed mountinfo seam is an honest stand-in for "which container".

## Verification

- TDD: RED retained — `AttributeError: module 'app.workers.listener' has no attribute
  '_read_mountinfo'` ×11 / `'_accept_extension_authenticated'`; closures RED first
  (`'ExtensionConnection' object has no attribute 'peer'`, `TransportUncertain` where the
  readiness-identity refusal was expected), then GREEN. Three test-side errors were the
  tests' own (a descriptor baseline taken with the listener open; a seam "restored" to
  itself because `listener.broker` is the `broker` module; a compose table with parent id 0)
  and corrected as such.
- Covering: **165 passed, 1 skipped (endpoint owner drift needs root)** — extension listener
  13, extension handshake, populated fence, worker listener, worker response capture. Ruff
  clean; `listener.py` has no findings.
- Test honesty on this macOS host: the seamless wrappers are asserted to fail closed with
  `PeerCredentialError` on both sides; flows run through the existing implementation seams
  (`verify_peer=False`, a symlinked socket alias, `connect_verified` returning the connected
  socket, synthetic mountinfo keyed by thread) — handshake and fence logic, never positive
  Linux authentication or a real mount observation.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No probe messages over the connection, no per-connection probe rules, no worker service,
  no observer or admission (slice 3 and Task 24 remain); no positive Linux authentication or
  real mount table claim; the actual worker image and container/socket runtime are
  Docker/colima host authority; no GUI.
