# T018-F1 — root-owned IPC pair initializer and authenticated listener lifecycle

Date: 2026-09-12
Status: implemented checkpoint verified on macOS development hardware; **T018 and
T018-foundation remain open**

## Exact scope

This checkpoint implements the first T018-foundation arm: the two-level filesystem and
listener lifecycle for one isolated-worker IPC pair, on top of the already reviewed
T018-A/B/B2 broker/coordinator scope.

- `app/workers/ipc_root.py`: root-owned generation boundary for a mounted pair root —
  root-owned generation metadata (0640) and boot secret under an exclusive generation
  lock, one responder-owned setgid endpoint directory (02710), staged secret rotation,
  and no container/process/Compose lifecycle management.
- `app/workers/listener.py`: responder-side authenticated Unix listener lifecycle — the
  listener owns only its endpoint directory, publishes an exact HMAC-authenticated
  readiness manifest (8,192-byte bound, versioned schema), and readiness is explicitly
  not authority to skip the broker's Linux peer-credential and mutual-handshake checks.
- `deploy/compose.yaml` / `deploy/security/service-ids.json`: the ten expected pair
  mounts and the fixed numeric service UID / pair GID assignments the static topology
  tests enforce.
- `deploy/tests/t018_foundation_linux_canary.py`: a root-only Linux canary (not pytest-
  collected) that qualifies all ten pairs with real SO_PEERCRED, `/proc/self/fd` socket
  anchoring, generation rotation, and wrong-primary-peer rejection.

The work was implemented in the Codex sessions ending 2026-09-09 01:54 KST; that session
recorded the focused suites passing and left three closing checks open: honest non-Linux
canary failure, final content hashes, and a change-scope check. This session performed
those three checks and recorded this evidence; no implementation change was needed beyond
what the snapshot commit `e2723b2` already contains.

## Verification (macOS arm64 development host, Python 3.12.13)

```text
python -m pytest -q deploy/tests/test_ipc_root_initializer.py \
    deploy/tests/test_worker_listener.py deploy/tests/test_worker_boundary.py \
    deploy/tests/test_compose_topology.py
150 passed, 1 skipped, 21 subtests passed
(the single skip is deploy/tests/test_worker_boundary.py:313 —
 "Linux SO_PEERCRED is the only release qualification path")

python deploy/tests/t018_foundation_linux_canary.py   (macOS, non-root)
FAIL: native Linux SO_PEERCRED is required
exit status 1  — the canary refuses honestly on a non-Linux host; no synthetic PASS path

python -m pytest -q app/tests deploy/tests   (full shared regression, 2026-09-12)
2,922 passed, 2 skipped, 369 subtests passed, 1 known Starlette/AnyIO deprecation warning

ruff check app/workers/{ipc_root,listener,broker}.py deploy/tests/{test_ipc_root_initializer,
    test_worker_listener,t018_foundation_linux_canary,test_compose_topology}.py
PASS

git status --short   (after commit eb4f182)
clean — the slice touches only the files hashed below
```

## Frozen content identities (SHA-256)

```text
3b062f298202087c9baeef3d8a0d36caebf404c0bcbe6ac7acf9685f39cf04b0  app/workers/ipc_root.py
d03692e1c9d0f538c5adb8c465c326b5766372a581cd88cc472e9c59cd682f14  app/workers/listener.py
39139e14a613e90fb08268042c917304a93c9b91e763602346de90be4bee8278  app/workers/broker.py
d7f396a65b590ac7ede1e0e5c9f8980482f71a53e39b1e9362b844a7379da580  deploy/tests/test_ipc_root_initializer.py
62fb0890e06fafe09b8d0a1cb7a54278e266b276f62c1ae03020be328d5ce385  deploy/tests/test_worker_listener.py
b49036c783c2b5a851fcf2bb0db3292eba321e62e8d08603836db57d36533460  deploy/tests/test_compose_topology.py
1714e539da90baff78916132963788df45cea0d9c3cdd0e50c470b9865ad24d7  deploy/tests/test_worker_boundary.py
0f434f06841027d306fb9e959f826fdeb616070b0dc99869dec42aa33b770588  deploy/tests/t018_foundation_linux_canary.py
6a18faa38379724a18466f39b42f66c4405fe11eb790b8e9c21addd39cbd152e  deploy/compose.yaml
4330b2080d5579847909fb086ebde6144b1fc54fdee6251a97383acd1e5565f4  deploy/security/service-ids.json
```

## Not claimed

The Linux/root canary has not been executed: this host is macOS and no candidate Linux
service environment was provisioned in this session, so real SO_PEERCRED, fixed-UID/GID
and `/proc/self/fd` behavior remain unqualified. Bounded digest/chunk/receiver-credit
artifact streaming does not exist yet (no `app/workers/artifact_stream.py`), and staged
sandbox/channel enforcement, service images/initializers wiring, actual worker
implementations and both clean deployment profiles remain open. T018-foundation therefore
stays open; this checkpoint contributes only the initializer/listener lifecycle and its
macOS-executable regression surface. No independent adversarial re-audit of this specific
slice has run yet.
