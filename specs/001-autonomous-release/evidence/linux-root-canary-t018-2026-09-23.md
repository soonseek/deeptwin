# Evidence — T018-foundation's Linux/root canary executed; two Linux-only defects found and fixed (2026-09-23)

- Date: 2026-09-23
- Task: T018 (`T018-foundation`: "actual Linux initializers/listeners/peer handshake"). The
  canary `deploy/tests/t018_foundation_linux_canary.py` had never run: every earlier session was
  on macOS (evidence/worker-ipc-foundation-t018f1.md "Not claimed"), and the 2026-09-12 Docker
  attempt was blocked by a host content-store fault.
- Host: Linux 6.18 (x86_64) container, **root**, ext4 root filesystem, Python 3.12.3. Native
  `SO_PEERCRED` and `/proc/self/fd`. This is a development container, not the candidate service
  image: the pair roots were provisioned as the empty directories the Compose volumes provide
  (`/run/deeptwin/ipc/<pair>`), nothing else.

## Frozen identities

```
aeefcf5d1a5eb8571de8a71133d96677e407dd0afe80d6242e13f34bbf908cfd  app/workers/listener.py
3385a1f7f7bd3772647d6b2c3b91d741acf597459ff88cf8b3cd5307e08fd2a4  deploy/tests/test_worker_listener.py
0f434f06841027d306fb9e959f826fdeb616070b0dc99869dec42aa33b770588  deploy/tests/t018_foundation_linux_canary.py
```

The canary's own hash is the one frozen in worker-ipc-foundation-t018f1.md — unchanged.

## Canary result

```
$ python deploy/tests/t018_foundation_linux_canary.py      # root, Linux
{"generation_rotations":10,"old_generation_application_frames":0,"pairs":10,
 "peer_credential_path":"SO_PEERCRED","socket_anchor":"/proc/self/fd","status":"PASS",
 "wrong_primary_peer_application_frames":0}
exit 0
```

All ten pairs qualified with their fixed numeric UID/GIDs over the real `SO_PEERCRED` path and
`/proc/self/fd` socket anchoring, one generation rotation each, zero application frames from an
old generation, and the wrong-primary-peer probe refused before any application frame. Run twice
(before and after the fix below), PASS both times. The first attempt, before the pair roots
existed, refused honestly (`ipc_root_integrity_invalid` on the absent mount) — no synthetic PASS.

## Defect 1 (product, security-relevant): inode reuse defeated the listener's replacement check

- `deploy/tests` on Linux as root: **2–3 failures** that macOS never showed, varying per run.
- `test_readiness_inode_swap_is_preserved_by_close`: an attacker-model unlink-and-recreate of
  the readiness file with the same owner and mode — `close()` did **not** refuse and unlinked the
  **replacement**. Cause: `_unlink_exact` identifies the file by (device, inode, uid, gid, mode);
  ext4 hands a freed inode number straight to the next file, so the replacement compared equal.
  The same holds for the socket pathname (the socket-swap case passed only when the kernel
  happened to pick another number).
- Fix: `bind_worker_listener` now holds an `O_PATH | O_NOFOLLOW` descriptor on each published name
  (readiness record, socket path), verified to be the published (device, inode), for the
  listener's lifetime (`_pin_inodes`, `WorkerListener._pins`), closed in `close()` after the
  exact-unlink checks and on every bind failure path. A held descriptor keeps the inode allocated,
  so no replacement can take its number while the listener lives. Without `O_PATH` (not Linux)
  nothing is pinned and the identity check stands alone, as before.
- RED: the swap case failed on this host before the fix; GREEN after, three consecutive runs.

## Defect 2 (test assumptions): inode inequality after a crash

- `test_restart_rotates_generation_and_listener_reclaims_only_stale_pair` and
  `test_restart_reconciles_exact_socket_only_crash_residue_under_listener_lock` asserted the new
  socket's inode differs from the crashed one's. After a real crash every descriptor — now
  including the pins — is released and ext4 may reuse the number, so the assertion was false on
  Linux, not a product defect. The crash models now also release the pins (faithful), and the
  inequality is replaced by what actually proves the reclaim: the new generation's (or the
  restarted boot's) authenticated record, still verified by `verify_listener`.

## Defect 3 (test portability): a hard-coded macOS path

- `test_deployment_consume.py` created its short socket alias under `/private/tmp`
  unconditionally (`FileNotFoundError` on Linux). Now `/private/tmp` only on Darwin, the default
  temporary directory elsewhere, like the other fixtures already did. 19/19 on Linux.

## Verification

- `deploy/tests`: **449 passed, 369 subtests**, three consecutive runs on Linux/root (the earlier
  macOS runs reported 150 focused / 298 deploy with one Linux-only skip; that skip now runs).
- Canary PASS as above. App-side listener consumers: see the progress entry.

## Not claimed

- Not the candidate service image or Compose topology: no container isolation, seccomp,
  non-root Chromium sandbox, image initializers or two clean deployment profiles (T081/T083).
- T018 stays open for those, actual worker implementations and the semantic integrations
  (T087/T090/T024/T043/T044/T070); this closes only the foundation's "actual Linux initializers/
  listeners/peer handshake" canary run that was recorded open.
