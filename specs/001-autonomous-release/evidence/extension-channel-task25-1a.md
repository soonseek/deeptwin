# Evidence — Task 25 slice 1a: fixed extension worker channel values and argv parser

- Date: 2026-09-18
- Task: Task 25 (worker-private probe channel; prerequisite for Task 24), slice 1a only —
  T018-foundation transport values. Plan entry: `resumption-plan.md` "### Task 25", accepted
  for 1a by independent specification review on 2026-09-18 (ACCEPT WITH CHANGES, folded in).
- Authority: `contracts/extension-candidates.md` (SocketMount `broker_pair`,
  `deeptwin-extension-worker-v1`), `contracts/deployment-prepare-sources.md` (control identity,
  packaging gate), `contracts/extension-lineage-values.md` §5 (argv structure),
  `app/deployment/contracts.py::slot`/`::CONTROL`, `broker.ChannelSpec`, `ipc_root.PairRootSpec`,
  `listener._validate_pair_channel`.

## Frozen identities

```
12162a60a2281cd240a0ffd61d03308b461ee0d25b84f0bc1512bbead4b778b9  app/workers/extension_channel.py
c3a6795cf941b07f13918536c7de8f0b1d998f4e810741d26f9c0b276cdfe6c0  app/tests/test_extension_channel.py
```

## What was built

- `app/workers/extension_channel.py` (new; no existing production file changed):
  - `extension_channel(*, instance_id, slot_number) -> (PairRootSpec, ChannelSpec)` derives
    every slot and control identity value from `deployment.contracts.slot` (service `ext-I-NN`,
    channel `cp-ext-I-NN`, responder uid/gid 22000+N, pair gid 23000+N, socket mount
    `/run/deeptwin/ipc/xsNN`, `worker.sock`, protocol `deeptwin-extension-worker-v1`) and
    `deployment.contracts.CONTROL` (requester `control`, uid/gid 20102); the channel's pair root
    is the slot root's `endpoint` (never the outer root); root/socket owner responder + pair gid,
    modes 0o2710/0o660; the explicit `extension-channel-profile-v1` constants (requester types
    `extension-artifact-v1`/`extension-request-v1`, responder types
    `extension-artifact-v1`/`extension-result-v1`, frame 65536, in-flight 1, queue 16,
    operation 30000 ms) are an application profile over the existing framing.
  - `parse_worker_argv(argv) -> (instance_id, slot_number)`: exactly five string elements,
    elements 1..4 exactly `--instance-id`, hex32 (the slot grammar; no third regex),
    `--slot-number`, `1..16` with no leading zero, bounded to two ASCII digits before any
    integer conversion; argv[0] is not compared (the executable's packaging is an image gate).
  - `ExtensionChannelError` is the single closed error.
- Inert values: no I/O, authority or live channel; the worker probe service (slice 3) is their
  first importer (Task 22 precedent for pure precursors).

## Review (independent, adversarial) and closures

Verdict: ACCEPT, conditional on two items, both closed before commit:

1. SHOULD — an oversized digit string reached `int()` first and leaked Python's
   4300-digit `ValueError` → length bound before conversion; `"9" * 5000` is a refusal case.
2. SHOULD — retained RED output (below).
3. SHOULD — listener/route-binding compatibility restated field by field → a test now runs
   `listener._validate_pair_channel` for all 16 slots and constructs a `WorkerRouteBinding`
   from the spec; modes pinned to `ipc_root.ENDPOINT_MODE`.
4. NIT — subprocess import-boundary probe now passes `cwd` and `stdin=DEVNULL`.
5. NIT — extra negative argv shapes (tuple, bytes, Arabic-Indic and fullwidth digits, `00`,
   `1_0`, trailing newline, surrogate-escaped instance id).
6. NIT — channel spec digest pinned stable per slot (`broker._spec_digest`).
7. NIT — docstring: only slot/control identity values are "never restated"; the profile
   constants and argv shape are defined here.

## Verification

- TDD: RED retained — `pytest app/tests/test_extension_channel.py` →
  `E   ModuleNotFoundError: No module named 'app.workers.extension_channel'` / `1 error in 0.13s`;
  review closures RED first (`ValueError: Exceeds the limit (4300 digits)…`,
  `WorkerRouteBinding.__init__() missing … 'channel_spec'`), then GREEN.
- Covering: **45 passed** (`test_extension_channel.py`); mixed run with the web owner suite
  that loads `app.api`: **113 passed** (the import-boundary check runs in a fresh interpreter).
  Ruff check/format clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No Linux/OCI image, initializer, mount, argv metadata or packaging claim; no worker semantic
  registry; no control observer or admission; no handshake, listener, fence or probe message
  (slices 1b–3 remain, 1b gated on `contracts/extension-worker-probe.md`); no GUI; the actual
  worker image and container/socket runtime are Docker/colima host authority.
