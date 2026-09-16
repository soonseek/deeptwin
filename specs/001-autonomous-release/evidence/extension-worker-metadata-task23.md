# Evidence — Task 23: fixed-file extension worker metadata source

- Date: 2026-09-16
- Task: resumption-plan.md Task 23 (T087 partial) — the actual local reader
  prerequisite for an authenticated live observation, per
  `contracts/extension-worker-metadata.md` §1–6 and the Task 22 lineage
  values. Not admission, installation, qualification or readiness.

## What was built (`app/workers/extension_metadata.py`)

- **Closed API**: `open_worker_metadata_source()`,
  `WorkerMetadataSource.read_current(*, deadline)`, `.close()`, `.closed`;
  frozen `WorkerMetadataReading(build_identity, platform, uid, gid)`.
  Direct construction, copy, deepcopy and pickle refuse; the source is a
  context manager with idempotent close; one nonblocking lock serializes
  reads and close (overlap is `busy`, never a close).
- **Closed errors** (§2): six subclasses with fixed code strings and no
  dynamic arguments or chained cause. OSError → unavailable; bytes/
  metadata/mount/process invariants → invalid; foreign host → unsupported
  platform (checked before any path access); wrong deadline type →
  invalid; deadline → deadline. Integrity/unavailable failures and any
  unexpected BaseException close/poison the source; busy, deadline and
  invalid-deadline do not.
- **Fixed hierarchy** (§3): seven directory descriptors (`/`, `/opt`,
  prefix, `bin`, `identity`, `ports`, `ports/tool-port-v1`; root-owned
  0755, opened componentwise DIRECTORY/CLOEXEC/NOFOLLOW) and six leaf
  descriptors (worker 0555 ≤16 MiB, identity 0444 ≤8 KiB, four schemas
  0444 ≤256 KiB each) — 13 retained, transient ≤32. Names are stat'ed
  without following links before open and compared again after; leaves
  must be regular single-link; device+inode pairs must be distinct across
  all thirteen; symlinks, hardlinks, FIFOs and directories in a leaf
  position refuse before any blocking open.
- **Measurement** (§5): every read reopens the chain from the root,
  compares directory identities and leaf signatures (device/inode/uid/gid/
  mode/nlink/size/mtime/ctime) against both the retained descriptors and
  the fresh names, rereads identity and schema bytes completely, streams
  and hashes the worker in ≤64 KiB chunks with deadline checks around each
  chunk (bytes discarded, never returned), parses the identity with
  `parse_build_identity`, requires its platform to equal the sampled one
  and its entrypoint sha256/size to equal the measured worker, and runs
  `validate_schema_bytes` over the four role-ordered schema bytes. A
  final fence rechecks names, sampled platform/credentials and returns
  only when everything equals the acquisition baseline.
- **Process/mount observations** (§4): real == effective UID/GID, nonzero,
  ≤4294967295; Linux-only platform mapping; `/proc/self/mountinfo` via the
  existing bounded parser — the root mount must be `/` and read-only,
  all thirteen paths must resolve to that mount (a mount at/below the
  prefix or an intervening `/opt` mount refuses), every retained identity
  must match its device, and a visible same-device mount whose backing
  root overlaps the prefix's backing path in either direction is an alias
  and refuses; unrelated mounts and their order are immaterial.

## Verification (53 tests, TDD)

- RED: ImportError on the absent module, then GREEN; two fixture
  corrections during authoring (the project's mountinfo parser requires
  positive parent ids; per-block restoration of patched facts).
- Covered: brief-mandated lifecycle; frozen reading without worker bytes;
  construction/copy/pickle refusal; fixed error codes; unpatched
  non-Linux factory fails before path access (host-conditional, skipped
  only on Linux with the reason stated); exact 13 retained FDs, all
  released, transient bound, no leak on partial acquisition; wrong/
  expired deadline without poison; concurrent busy for read and close;
  ten post-open mutations (identical replace, unlink, truncate, growth,
  in-place edit, leaf/dir chmod, ancestor replacement, schema/worker
  edits) each invalid-or-unavailable AND poisoning; symlink/hardlink/
  FIFO/directory leaves and a symlinked directory; identity/schema/worker
  mismatches incl. platform; exact caps incl. a sparse 16 MiB+1 worker and
  an empty worker; six mount rejections plus unrelated-mount/order
  acceptance; mount, credential and platform drift after open; six bad
  credential shapes; OSError → sanitized unavailable + poison;
  KeyboardInterrupt → closed then propagated; close continues past one
  failing descriptor; the real shipped result schema (>64 KiB) is read.
- Simulated Linux evidence: fixed root constants, ownership, platform,
  credentials and mountinfo are sampled through monkeypatched module
  functions; file types, names, inodes, sizes, modes and bytes are real.
  No real `/opt`, mount, user file or worker process is touched.
- Ruff lint, `ruff format --check` and `git diff --check` clean.
- Covering command (plan §Task 23) and full regression: recorded in the
  iteration report below the frozen hashes.

## Limits

- Not Linux kernel/OCI proof, not an image authentication, readiness
  signal, HTTP route, control observer, startup/handler composition or
  installation authority. Real Linux nonroot access, both native
  architectures, freshness latency and populated endpoint fences remain
  separate gates (T025/T087).

## Independent review and fix round 1 (2026-09-16)

Verdict before the fix: spec FAIL / quality PASS. Important: (I1) a mount whose mountpoint lay
below the prefix at a non-chain name (e.g. `<prefix>/extra`, `<prefix>/bin/extra`) was accepted
because only the 13 named paths were checked; (I2) a BaseException raised in the factory tail
after the descriptors were transferred leaked all 13. Minor: leaf-open OSError classified as
invalid (M3); identity/schema reads had no per-chunk deadline check (M4); mount state sampled
only after the reads and retained descriptors not re-fstat'ed at the final fence (M5);
`__exit__` could replace a propagating exception with busy (M6); broad Invalid mapping (M7,
accepted as fail-closed). Closures: any mount at/below the prefix refuses on or off the chain;
the factory tail unwinds on every BaseException; leaves are opened directly so OSError stays
unavailable; `_read_bounded` checks the deadline around every chunk; the mount key is sampled
before and after the reads and must match, and retained descriptors are re-fstat'ed at the
fence; `__exit__` re-raises busy only when nothing is propagating. RED 6 failed → GREEN;
suite **60 passed**; Ruff lint/format and diffcheck clean.

## Frozen identities (post-fix)

```
6b328b820f47a700361a638967488fda013dd495995751f8dbc587dc87aa358b  app/workers/extension_metadata.py
969a22c70bdbebe4524ff368e606097589ccf7c3ed4c0bb35bb2e8c8be630e25  app/tests/test_extension_worker_metadata.py
```

## Iteration record

- Pre-fix covering command: 264 passed, 1 skipped (Linux SO_PEERCRED), 21 subtests, 9.30s.
- Pre-fix full regression (module + 53 tests, before the review closures):
  see the resumption evidence log for the exact count.
- Post-fix covering command and the final full regression are recorded below.
- Final full regression on the committed tree (Task 23 post-fix + T040 slice 1; same tracing-disabled command): **5668 passed, 1 skipped (Linux SO_PEERCRED), 1 inherited warning, 369 subtests, 649.70s**, exit 0.
