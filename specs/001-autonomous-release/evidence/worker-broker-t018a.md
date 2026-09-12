# T018-A — authenticated isolated-worker broker checkpoint

Date: 2026-09-08  
Status: independently reviewed low-level checkpoint; **T018 remains open**

## Exact scope

This checkpoint implements the bounded Unix-domain-socket transport that runs **after** a trusted
caller has already validated authority, reserved budget and committed send intent. It does not
make those decisions itself. The implemented files are:

- `app/workers/broker.py`
- `app/workers/__init__.py`
- `deploy/tests/test_worker_boundary.py`

The broker contains no application store, permission, budget, container-lifecycle, subprocess,
external-network, logging or file-descriptor-passing dependency. It neither retries an uncertain
send nor turns transport state into application authority.

The target DeepTwin release is a self-hostable, web-based, open-source multi-agent framework whose
supported user surface is its bundled browser UI; the current repository has no approved project
license. This broker is an internal server-side worker boundary, not a
native/product launcher, an end-user CLI, or a Claude/Codex application shell.

## Closed boundary properties

- `ChannelSpec` is frozen, exact-type checked and binds both services/directions, distinct nonzero
  primary UID/GID expectations, a separate pair-specific supplemental GID, a responder-owned
  setgid `02710` directory, one responder-owned `0660` socket, per-side sorted message-type
  allowlists, frame/queue/in-flight limits and an operation limit. The pair GID is only a kernel
  filesystem reachability gate; `SO_PEERCRED` must match the peer's distinct primary UID/GID and
  cannot substitute the supplemental group for service identity.
- Every absolute pair-root component is opened relative to a held directory descriptor with
  `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`. Linux connect uses the verified
  `/proc/self/fd/<root-fd>/<socket>` path and rechecks the exact socket device/inode after connect.
  The release path fails closed outside Linux and authenticates the peer with `SO_PEERCRED`.
- Protocol v2's four-flight HMAC handshake binds the complete channel-spec digest, protocol,
  channel, roles, direction, **distinct requester and responder boot IDs**, and two fresh 256-bit
  challenges. Both boot IDs are also bound into the derived connection/session key. The requester
  does not succeed without the responder's final proof. Public handshake APIs expose neither
  peer-verification bypass nor an injectable challenge source, close their socket on every escaping
  failure and classify a failed handshake as `definitely_not_sent` at the application-dispatch layer.
- Authenticated sessions can be created only by the handshake path, are role/spec bound, redacted,
  immutable, non-copyable and non-serializable. One session can claim one `FrameCodec`; the codec
  is also non-copyable/non-serializable and prevents public reassignment of its direction or
  counters, so constructing or copying a second sequence-1 receiver cannot reset replay state.
- Canonical big-endian framed JSON rejects duplicate keys, floats/non-finite values, booleans used
  as integers, non-canonical encoding, unknown/missing fields, oversized/deep inputs and invalid
  UTF-8. Application envelopes bind exact bytes, byte count, digest, direction, message type,
  connection, both boot IDs and monotonically increasing per-direction sequence under HMAC. A
  decode violation latches the codec closed.
- FIFO admission permits one in-flight request, bounds queued callers, rechecks the absolute
  deadline immediately before admission and removes/notifies an interrupted waiter in `finally`.
- `max_operation_ms` creates one absolute monotonic bound at each connect or handshake operation;
  individual packets do not reset it. Sanitized `BrokerError` objects retain neither an external
  cause nor context containing input JSON or filesystem paths.

## Verification

Final focused result:

```text
python -m pytest -q deploy/tests/test_worker_boundary.py
29 passed, 1 skipped, 21 subtests passed
```

The one skip is deliberate: this macOS development host cannot execute the Linux
`SO_PEERCRED` plus `/proc/self/fd` wrong-primary-identity integration path. The true distinct-UID
positive path remains a later Linux/container qualification item and is not claimed here.

Final regressions:

```text
python -m pytest -q deploy/tests
298 passed, 1 skipped, 369 subtests passed in 38.08s

python -m pytest -q app/tests
2255 passed, 1 skipped, 1 dependency deprecation warning in 73.54s

python -m ruff check app/workers/__init__.py app/workers/broker.py \
  deploy/tests/test_worker_boundary.py
All checks passed

git diff --check
PASS
```

An independent security/correctness audit reproduced and drove fixes for public peer bypass,
missing final acknowledgement, caller-resettable replay state, copied codec replay, full-path
symlink traversal, post-wakeup deadline admission, interrupted queue leakage, retained exception
payload/path context, ineffective entropy-failure testing, boolean/integer confusion, incomplete
spec authentication and unenforced operation bounds. Its final P1/P2 result is **PASS**.

A later topology review found that the original `0700`/`0600` same-owner layout could not serve
two containers with distinct service UIDs. The revised responder-owned `02710`/`0660` plus
pair-GID contract was independently re-audited. It rejects equal/root identities, primary/pair GID
confusion, ownership drift and broader directory/socket modes; the repeated P1/P2 result is
**PASS**.

Final SHA-256:

```text
4110914d9fe20497f1fb1d2752d62da0128ef18c98e6d70c17630c1a0fe2858c  app/workers/__init__.py
e92ac4354d038bc22e163be23e92b446e34df33c5348bd72a971998f592f6be0  app/workers/broker.py
1714e539da90baff78916132963788df45cea0d9c3cdd0e50c470b9865ad24d7  deploy/tests/test_worker_boundary.py
```

## Explicitly open T018 work

This is not an isolated-worker deployment qualification. T018 stays unchecked until all of its
remaining requirements are implemented and measured, including:

- an HTTP/root-command-to-coordinator handoff, durable transport observations, restart-status
  queries and worker-restart reconciliation; T018-B closes only the process-local exact-capability
  transport coordinator checkpoint;
- pair-root/socket creation, deployment `group_add`/mount enforcement, per-boot secret
  distribution/rotation and actual Linux distinct-UID positive, wrong-peer, replacement and
  backpressure qualification;
- runtime qualification of the static edge/control/provider/fetch/Codex/browser/document/speech/
  evaluation/runtime-extension isolation skeleton and its separate egress/no-egress networks;
- data-mount denial, bounded artifact streaming, fixed users, root filesystem/tmpfs/resource
  limits, Docker-socket/dynamic-mount/capability denial and pinned Chromium seccomp/userns sandbox;
- Compose and no-terminal deployment integration plus the later T079/T081/T083 clean-environment
  and release evidence.

These limits are why neither T018 nor the full web-based open-source framework release is marked
complete by this checkpoint.
