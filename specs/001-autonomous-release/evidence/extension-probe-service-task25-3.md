# Evidence — Task 25 slice 3: worker probe service and fixed entrypoint

- Date: 2026-09-18
- Task: Task 25 (worker-private probe channel; prerequisite for Task 24), slice 3 — T087
  worker startup over the T018-foundation transport. Plan entry: `resumption-plan.md`
  "### Task 25", bullet 3 and "Acceptance and non-claims". Contract:
  `contracts/extension-worker-probe.md` §3 (envelope use and per-connection rules), §4
  (budgets), §5 (service ownership), §6 (what a reply is not).
- Builds on: slices 1a (channel values, 26e9df3), 1b (codecs, 7ac470e), 2a (handshake,
  9b87945), 2b (populated fence, dcd0851), 2c (listener accept/connect and fences, b6492da).

## Frozen identities

```
a80aa477880be3135eabb9eaf9701227159e8a4f87015aabd46474facca8b710  app/workers/extension_probe.py
3e98267d520fa89acaffb42891a1e03dbde7188e1c860d0ddb1a4c4473c81aac  app/workers/extension_worker.py
a2b1c513a7c78f917f010fda74993b7cfe59f3bf024153679159e636e7d30abc  app/workers/listener.py
80cf0b2a90a0ad0e206da12bd6cab3cba22c6960cb19cbab3c753adfb839641d  app/tests/test_extension_probe.py
```

## What was built

- `app/workers/extension_probe.py` (new):
  - `open_worker_probe_service(*, instance_id, slot_number)`: derives the slot's pair root and
    channel through `extension_channel`, opens the Task 23 metadata source **before** binding
    or advertising the listener (a worker whose fixed files cannot be measured never publishes
    readiness), then binds one listener under a fresh `secrets.token_hex(32)` boot ID; every
    failure after the source was opened releases the source and, once bound, the listener.
    The existing listener identity check (`_validate_local_identity`) supplies uid/gid and
    pair-gid membership; nothing is re-derived.
  - `WorkerProbeService` (nonconstructible, uncopyable, unserializable; repr shows only
    `closed`): one boot ID, one source, one listener, one private `_Router`. A nonblocking
    lock rejects overlapping `serve_one`/`close` as `ProbeServiceBusy`; a closed service
    answers `ProbeServiceClosed`; close order is listener then source, idempotent.
  - `serve_one(deadline) -> int`: accepts one connection through
    `_accept_extension_authenticated` (the caller's deadline bounds the accept), then serves it
    under `deadline.bounded(2000)` taken after the accept: `recheck()` before the first read,
    then per probe — request type `extension-request-v1` with `correlation_id` null, a non-nil
    canonical message id distinct from every id seen on the connection, a request within the
    codec grammar, an identical request/receipt digest pair across the two probes, a fresh
    nonce — an actual `read_current(deadline.bounded(500))`, the reply built from that
    reading (`build_identity.digest`, `schema_set_digest`, the identity's own
    `port_contract_version`, `platform`/`uid`/`gid`), the owned `ChannelSpec`'s
    `responder_service` and the router's exact (empty) key set, written as
    `extension-result-v1` with a fresh id correlated to the request, then `recheck()` again.
    The service closes the connection after the second reply and returns 2; a requester that
    ends the connection after its first reply yields 1 (a truncated later request is
    indistinguishable and equally the requester's end); every rule violation raises the
    closed `ProbeServiceError` after closing the connection. A poisoned source (integrity or
    unavailability during a read) closes the whole service; a bad requester never does.
  - `_Router`: the private router created in this slice. Its semantic registry is an
    immutable empty mapping; `operations()` returns `()`; there is no `register`, no
    placeholder handler, and it is not the T087 semantic registry.
  - Errors: `ProbeServiceError` / `ProbeServiceBusy` / `ProbeServiceClosed` with fixed
    messages; digests, nonces and message ids stay in locals and never reach an exception.
- `app/workers/extension_worker.py` (new): `main(argv=None) -> int` parses only the fixed
  argv through `parse_worker_argv` (exit 2 otherwise, before anything opens), opens one
  service (exit 1 if it cannot), installs SIGTERM/SIGINT stop handlers when on the main
  thread and restores them on exit, and loops `serve_one` with a 30 s accept deadline: a
  per-connection error continues, a closed (poisoned) service exits 1, a requested stop
  exits 0 after closing the service.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (22 tests green, Ruff clean at review time; every §3 rule traced
to its raise site with scratch probes; no case erroring earlier in the framing). All closed
RED-first:

1. MUST — `main()` hot-spins when the listener's own fences fail permanently (readiness
   record unlinked or pair root re-initialized: `serve_one` failed in ~0.2 ms with the
   service still open; a `WorkerListener` cannot be re-bound) → on a `ListenerError` the
   service re-runs the accept's own comparison (`_verify_record` against its record and the
   readiness/socket identities it published) and closes itself when it no longer verifies, so
   the entrypoint exits 1; test unlinks `listener.json` and asserts closure within 1 s with
   every descriptor released.
2. SHOULD — the handshake phase ran under the caller's accept deadline (a transport-only
   peer held the single-threaded worker for the whole accept deadline, 30 s in the image)
   → `_accept_extension_authenticated(..., connection_ms=)` starts the connection's window
   at the transport accept, bounds the handshake with it and carries it as
   `ExtensionConnection.deadline`; the service serves under that same window (one 2000 ms
   window, handshake included); tests with a 10 s accept deadline assert 1.5–3.0 s for both
   a transport-only peer and a post-handshake silent peer.
3. SHOULD — SIGTERM/SIGINT honoured only when the accept deadline expired (the accept
   retries after EINTR; Docker's default stop grace is shorter than 30 s) → the handler
   raises a private `BaseException` on the first signal, which unwinds the service's
   BaseException-safe paths and is caught only by `main()` (exit 0); a second signal during
   the close only re-sets the flag; handlers restored after the close. Test: a real SIGTERM
   to the process while the fake service blocks 5 s → exit 0 in < 2 s, handler restored.
4. SHOULD — "the worker closed the connection" asserted with `BrokerError`, which a hung
   worker's deadline also satisfies → `TransportClosed` at every site (the third-probe write
   may itself see the closed peer and is tolerated; the read must be the closed transport).
5. SHOULD — `_CONNECTION_MS` not exercised (the caller deadline was shorter) → see 2.
6. NIT — `__exit__` could replace a propagating exception with `ProbeServiceBusy` → guarded
   as the metadata source does; tested with a held lock and a body exception.
7. NIT — `listener` was a writable slot that sources `service_identity` → private slot with a
   read-only property; assignment raises.
8. NIT — `_SANITIZED` omitted `LineageContractError` (unreachable by construction, still an
   unsanitized path) → added.
9. NIT — coverage: a request reusing the worker's own reply id (refused) and an fd baseline
   around the poison test (released) added.
- Reviewer-verified: `TransportClosed` after ≥1 reply arises only from EOF at a frame
  boundary (rules are evaluated on complete decoded frames, so a truncation cannot mask a
  violation); reply sourcing (per-probe reading, owned spec, empty router); `_close_locked`
  from within `serve_one` runs with the lock held after the connection's `finally`;
  `open_worker_probe_service` unwinds on `BaseException`; descriptor enumeration matches the
  code; every raise site is fixed text; boot id grammar; the subprocess import test resolves
  `app` only from this worktree.

## Verification

- TDD: RED retained — `ImportError: cannot import name 'extension_probe' from 'app.workers'`
  (collection error, the whole module absent); GREEN 21/22 on the first run, the one failure
  being the descriptor enumeration (process-wide sample also counts the same-process
  requester's 5 descriptors — enumerated as such, equality asserted: 42). One test-side
  correction: a third probe is never read because the worker closes after its second reply,
  so that case asserts the closure (served = 2, the requester's next read fails) rather than a
  service error.
- Covering after the closures: **275 passed, 1 skipped (endpoint owner drift needs root)** —
  probe service 26, extension listener, handshake, worker metadata, channel, probe messages,
  populated fence, worker listener. Ruff clean (`listener.py` included).
- `app/workers/listener.py` changed for closure 2 only: the optional `connection_ms` window
  and the `deadline` attribute; the slice 2c tests are unchanged and green.
- Descriptor budget on this host (enumerated in the test): 13 source + 3 generation lease +
  3 listener = 19 retained; a served connection peaks at +5 (socket, re-acquired generation,
  fence secret) +13 transient = 37 worker-owned; contract worst case 19 + 5 + 32 = 56 ≤ 64.
- Import boundary: a fresh interpreter importing the two modules loads nothing from
  `app.api`, `app.static` or `app.server` (subprocess test).
- Test honesty on this macOS host: the same seams as slices 2c and Task 23 (no peer
  credentials, no `/proc`, synthetic mountinfo, a temporary fixed-file tree, the test's pair
  root and pair group in place of the fixed mount); the service's channel derivation is
  redirected to that root by monkeypatching the imported name. Service and probe logic only —
  never positive Linux authentication, a real mount, a real worker image or a container.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No semantic handler, artifact stream, retry, failure-success envelope or control-side
  observer/admission (Task 24); the reply compares nothing to an expected tuple and is not
  qualification, installation, readiness or a permit; no guarantee of life after the response;
  whether this module is the packaged `bin/worker` of a qualified image, both native
  architectures, allowed-manifest/OCI trust and the container/socket runtime are image and
  Docker/colima host gates — reported, never claimed; no GUI.
