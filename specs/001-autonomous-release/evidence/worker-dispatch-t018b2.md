# T018-B2 — bounded HTTP-to-worker dispatch handoff checkpoint

Date: 2026-09-08  
Status: independently adversarially accepted checkpoint; **T018 remains open**

## Product and scope boundary

DeepTwin targets a self-hostable, web-based, open-source multi-agent framework whose bundled
browser UI is the supported end-user product and control plane. The current repository has no
approved project license and is not yet a legal open-source release. This checkpoint is an
internal server-side handoff from an authenticated HTTP command through the root transaction to
one already qualified worker coordinator. It is not a native launcher, an end-user CLI, a full
graph runtime, a worker implementation, or deployment qualification.

The checkpoint covers:

- a fresh lifespan-owned `WorkerDispatchService` with one bounded FIFO and one serial worker
  thread per exact runtime profile;
- one absolute deadline across route resolution, capacity reservation, root commit, queue handoff,
  worker exchange and observation;
- exact profile, capability, principal, grant, worker generation, service pair and channel binding;
- durable, redacted transport observation plus same-actor and same-session `GET`/`HEAD` status;
- no replay resend, semantic-success inference, result acceptance, retry or budget settlement;
- a process-wide fail-closed latch when post-commit handoff or observation truth cannot be proved.

The implementation surface recorded here is:

- `app/runtime/ledger.py`
- `app/runtime/worker_dispatch.py`
- `app/api/transaction.py`
- `app/api/routes.py`
- `app/server.py`
- `app/tests/test_runtime_ledger.py`
- `app/tests/test_worker_dispatch.py`
- `app/tests/test_api_command_transaction.py`
- `app/tests/test_server_api_v1.py`
- `app/tests/test_server.py`

## Closed invariants

- Capacity reservation, root transaction and accept-or-release are owned by one synchronous
  helper invoked through one thread-pool boundary. Async request cancellation cannot strand a
  pre-commit reservation between checkpoints.
- Queue ownership transfer and registration of an exact `DispatchAcceptance` are atomic under the
  dispatch service condition. The worker does not wait for a second confirmation gate.
- The acceptance proof is bound to the exact service, slot, command, permit, profile and deadline.
  The route succeeds only after consuming the same object from the service-owned issuance registry
  once and checking the registry postcondition. Direct proof minting, copying, forging, mutation,
  reuse and silent accept/claim implementations cannot create a false HTTP `202`.
- A transition that may have queued or started work but cannot be proved is quarantined where still
  locally owned and otherwise recorded conservatively through process-wide inhibition and
  `outcome_unknown`; it is never rolled back as definitely not sent.
- The emergency latch sets its in-memory barrier and purges every pending permit under the permit
  lock without waiting on the SQLite writer. Writer contention therefore cannot leave dispatch
  authority open. Every worker emergency path has a non-I/O fail-closed fallback.
- Successful and failed transport observations use the exact ledger implementation, validate the
  returned observation identity and re-read the durable dispatch projection. Silent/no-op writes
  become process-wide unknown rather than leaving a may-have-happened effect as `pending`.
- Shutdown invalidates unclaimed proofs, drains or records queued work conservatively, releases
  capacity exactly once and joins all owned profile threads.

## Independent adversarial history

Independent review deliberately rejected earlier revisions until the following reproduced defects
were closed:

1. the global emergency latch waited for the SQLite writer and failed open on writer timeout;
2. async cancellation between reservation and the thread-pool helper leaked bounded capacity;
3. a silent `accept` could release a slot without queueing yet still return HTTP `202`;
4. silent transport-observation persistence left an external effect in `pending`;
5. a two-step confirmation gate could silently fail and strand a worker forever;
6. an internally minted but service-unregistered acceptance proof could falsely attest queue
   transfer.

The final read-only re-audit reproduced the proof-forgery case against the fixed bytes and observed:

```text
result=committed_unknown
held_reservations=0
queue_depth=0
owned_slots=0
issued_acceptances=0
occupied=[0]
pending_permits=0
status=outcome_unknown
latch=True
```

It found no remaining P1, P2 or P3 in this bounded checkpoint. Cross-role reuse of a boot-ID string
between different channels is not a defect under the current contract: requester and responder IDs
must differ within each authenticated channel, and the MAC transcript also binds channel, role,
direction and secret.

## Verification

Final implementation-focused results:

```text
app/tests/test_worker_dispatch.py
40 passed

app/tests/test_server_api_v1.py
26 passed

final independent adversarial focused set
127 passed, 1 existing Starlette/AnyIO deprecation warning

full application suite after the accepted bytes
2298 passed, 1 skipped, 1 existing Starlette/AnyIO deprecation warning
```

No live provider, paid API, external network, Docker daemon, user credential or destructive user
data operation was used.

## Explicitly open work

T018 remains unchecked. This checkpoint does not qualify:

- actual Linux UID/peer-credential paths, container networks, mounts, resources or initializers;
- browser, document/PDF, speech, evaluation, runtime-extension, provider/fetch, Codex or backup
  worker implementations;
- non-root Chromium user namespace/sandbox/seccomp operation and controlled egress;
- bounded artifact chunk/credit streaming or semantic graph execution;
- either clean self-hosted deployment profile or the final service images;
- release licensing, distribution, real-provider behavior or the complete US1–US7 journey.

## SHA-256

```text
fca496649d1a9404903a3951d78d2c2f9dc7d52fa83ebebaa0e28607f7d778c7  app/runtime/ledger.py
aa14d4b4e43e00e4077d236a57c29f1751686220dbc06a041ea9ce1f6f6c36c9  app/runtime/worker_dispatch.py
46746b3cc27e50663196b7374149961287765a7aa8e0aaf922931079ce4c117c  app/api/transaction.py
028cc4484293369a111dd669bc829de01958d636524478db827cbb2c1566bb6b  app/api/routes.py
fd3f6bd76bb288829691469020fdabef541d1e8e3d6706146355f2efbde63f4c  app/server.py
5dcc36773af9afc5ae3ed6f10fe0d76a03860c4b66c3ea0565e5675c13947854  app/tests/test_runtime_ledger.py
3a373d377417f4b1d62ea62c886f9d33c6ec0edc1369d65a5204231bfd2f1391  app/tests/test_worker_dispatch.py
7109d8a539f5c1c1a26f4f193419ee15bb4402383d56a89b62ad1e44bc1fb8d1  app/tests/test_api_command_transaction.py
03bc279970f67966ed0014d9acb2970b7f23584e3f1dc4a651d90d51a27823bf  app/tests/test_server_api_v1.py
37398bdf3d744e40662fded5d614ec61020d72c0a0753bcd756ffb641cc35d53  app/tests/test_server.py
```
