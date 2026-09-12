# T018-B — exact-capability isolated-worker coordinator checkpoint

Date: 2026-09-08  
Status: independently re-audited transport checkpoint; **T018 remains open**

## Product and scope boundary

The target DeepTwin release is a **self-hostable, web-based, open-source multi-agent framework**;
the current repository has no approved project license. This checkpoint is
an internal server-side control-plane-to-worker boundary used by that framework. It is not a
native launcher, end-user CLI, Claude/Codex application shell, complete graph runtime, or supported
deployment.

The checkpoint adds one authenticated, budget- and permission-bound exchange from a committed
runtime attempt to a trusted worker route. Its implementation surface is:

- `app/runtime/worker_coordinator.py`
- `app/runtime/ledger.py`
- `app/runtime/budgets.py`
- `app/api/transaction.py`
- `app/workers/broker.py`
- `app/tests/test_worker_coordinator.py`
- `app/tests/test_runtime_budget_dispatch.py`
- `app/tests/test_api_command_transaction.py`
- `deploy/tests/test_worker_boundary.py`

The HTTP route still does not hand the post-commit permit to this coordinator. T018-B2 must add a
bounded internal handoff and durable transport observation before an HTTP `202` can mean that a
worker accepted the command.

## Closed properties

- The root transaction binds the command-selected exact runtime `Principal` and exact `Grant`
  objects and IDs into the process-local `DispatchPermit`. The permit registry snapshots those
  identities, a copied permit is rejected, replay never mints a second permit, and a newly issued
  replacement grant for the same immutable record cannot replace the user's selected grant.
- The permit preserves the runtime deadline/lease in epoch milliseconds and the budget deadline in
  epoch seconds without comparing unlike units. Consumption samples each trusted clock, removes one
  source-clock tick conservatively, and anchors the resulting durations to monotonic time **before**
  locks, graph validation and SQLite/fsync work. Validation latency therefore shortens the window;
  it cannot be added back as fresh execution time.
- The channel operation deadline is created before FIFO admission. Queue wait, permit validation,
  immutable loading, connect, handshake, write and read share one non-extending absolute deadline.
- The coordinator accepts no request payload or caller-selected connector. It reads the permit's
  exact immutable `execution_envelope`, reconstructs and verifies the record/ref/hash, enforces a
  32 KiB envelope ceiling, and sends the original canonical `body_bytes`. `PolicyGate.read` checks
  the exact selected grant both before and after loading, so revocation during the read fails before
  transport.
- Worker IPC protocol v2 authenticates distinct requester and responder boot/generation IDs in every
  handshake proof, derived session key and application frame MAC. A stale or replaced worker boot ID
  fails before application bytes are written.
- One authenticated response must use an allowlisted route type and correlate to the exact command.
  The result is only a transport observation; this layer does not advance/settle/accept the attempt,
  retry an uncertain effect, or infer semantic success.
- Codec, socket and admission state are closed on success and failure. Failure classes retain the
  conservative `definitely_not_sent`, `may_have_started`, or `outcome_unknown` effect.

## Independent adversarial review

The first review rejected the checkpoint for four P1/P2 defects: replaceable selected grants, one
ambiguous shared boot ID mislabeled as a worker generation, an operation limit started after queue
admission, and wall-to-monotonic conversion that could add database-validation time back. All four
were reproduced, fixed, and re-audited. The final re-audit found **no remaining P1/P2 blocker** and
its focused suite passed `183` tests plus `21` subtests (`1` deliberate non-Linux skip). The exact
replacement-grant reproduction now fails closed while leaving the unconsumed permit pending.

Local focused results after the final changes:

```text
python -m pytest -q app/tests/test_worker_coordinator.py
15 passed

python -m pytest -q deploy/tests/test_worker_boundary.py
29 passed, 1 skipped, 21 subtests passed

python -m pytest -q app/tests
2255 passed, 1 skipped, 1 dependency deprecation warning
```

The one worker-boundary skip is the real Linux distinct-UID `SO_PEERCRED` path; macOS cannot qualify
it. No live provider, paid model, Docker daemon, external network or user credential was used.

## Explicitly open work

T018 remains unchecked. This checkpoint does not provide:

- HTTP/root-command-to-coordinator handoff or durable transport observations;
- restart status queries, live cancellation, safe retry after an uncertain send, or process-wide
  route uniqueness;
- bounded digest/chunk/credit artifact streaming or semantic execution-envelope field validation;
- worker implementations for browser, document/PDF, speech, evaluation, runtime extensions,
  provider/fetch, Codex or backup;
- actual Linux container identities, pair-root/secret creation, networks/mounts/resources, Chromium
  sandbox operation, final service images, either deployment profile, or clean-host evidence.

These omissions are release gates, not optional polish.

## SHA-256

```text
4110914d9fe20497f1fb1d2752d62da0128ef18c98e6d70c17630c1a0fe2858c  app/workers/__init__.py
e92ac4354d038bc22e163be23e92b446e34df33c5348bd72a971998f592f6be0  app/workers/broker.py
1714e539da90baff78916132963788df45cea0d9c3cdd0e50c470b9865ad24d7  deploy/tests/test_worker_boundary.py
a48ddea93f4cdf8544fa6c5be8c36807eb2466c39e2c8e60661587d5108f3af2  app/runtime/worker_coordinator.py
9d22d4bf4cc95020fee95d58e95156c8490b7a75bd68d304928cab0f281764ca  app/tests/test_worker_coordinator.py
6d4a87059fd8911bec646e373eac40b73b9fd31b43bd3a793da2f9759764b5ca  app/runtime/budgets.py
9d2f74fb69970069f426a4bcd23664ca2e389c781a05bb4d8aa9b4e38ef9709c  app/runtime/ledger.py
a78c3573920e72af7bd6427ff7212ba1c6294de227211c37f7084a74ad6b256b  app/api/transaction.py
04d0f1f4abdc3883835d6dad7475bc51f6aa6f5b4d3edc0b3c6afe57acf7918b  app/tests/test_runtime_budget_dispatch.py
3a7100bd36e55a391738ad90c81da47ddf923620164282d76147643b924ce93a  app/tests/test_api_command_transaction.py
```
