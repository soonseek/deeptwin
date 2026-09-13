# Evidence — backup-key-init job semantics (T023 tail, OPS-AC07)

- Date: 2026-09-13
- Task: T023 tail slice — the `backup-key-init` job in
  app/operations/backup_key.py under the `*-root-init` contract
  (operations.md §2: absent → O_EXCL create + file/directory fsync;
  exact valid existing → verify-only no-op; malformed → fail without
  replace; §5: fixed age-x25519-v1 identity in the separate backup-key
  volume, secret never logged).

## Frozen identities

```
0ad7c900c315dc99b9b15017299f18740ba84c97f58b8763f1fddd88e8f4a6f7  app/operations/backup_key.py
7f3660944b212d9e7b23e27d4c555b162b1da05bd29128ca195fb9cac5639c3f  app/tests/test_backup_key_init.py
```

## What was built

- `initialize_backup_key(volume_root, *, keygen, clock)`:
  - **absent** → validates the injected generator output (single-line
    `AGE-SECRET-KEY-1…` identity, `age1…` recipient — validated BEFORE
    any write), creates `identity.age` (0600) and `manifest.json`
    (schema_version/job/key_mode `instance_backup_key`/
    `encryption_profile_ref` `age-x25519-v1`/recipient/identity_sha256/
    created_at) with O_EXCL + per-file fsync + directory fsync →
    `BackupKeyState(status="created")`;
  - **exact valid existing** → verifies symlink-freedom, 0600 mode,
    manifest shape (every job-identifying field must match), the
    identity's SHA-256 against the recorded hash and the single-line
    age form → `status="verified"` with ZERO writes — the generator is
    never invoked on a rerun;
  - **anything else** → `BackupKeyInitError` without touching a byte:
    partial pairs, corrupt/foreign manifests (wrong profile, key_mode
    `portable_recovery`, wrong schema/job), tampered identities, loose
    permissions, symlinked volume/files, unmounted volume (the job
    never creates storage locations).
- The secret identity never appears in the result value or any error
  message — only the public recipient and hash.
- The real `age-keygen` stays inside the networkless
  backup-crypto-worker (T070, dep/Docker-gated); this module never
  spawns anything.

## Verification (20 tests, TDD — module absent first)

- Stack-update rerun: byte-for-byte and mtime_ns-identical volume,
  poisoned generator proves no regeneration.
- Every malformed state fails with the volume snapshot unchanged.
- Generator garbage (bad prefix, multiline, empty, missing keys,
  non-dict) refuses before any write — the volume stays empty.
- OS-level O_EXCL semantics confirmed against the created identity.
- `ruff check` clean; full regression **3417 passed, 2 skipped**
  (was 3397).

## Notes

- T023 remains `[ ]`: the GUI halves (settings/app .mjs, routes
  wiring), the provider-command receipt UI arc and the manifest-mode
  enforcement in the backup GUI are the remaining scope.
