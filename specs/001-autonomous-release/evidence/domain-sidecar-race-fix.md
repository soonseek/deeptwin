# DomainStore SQLite sidecar-check concurrency fix

Date: 2026-09-12

## Defect

`DomainStore._connection` rejected a connection with `UnsafePath("Unsafe SQLite sidecar")`
when its no-follow stat of `intake.sqlite3-wal/-shm/-journal` raced with another connection
unlinking that sidecar on close: the path still resolved but the inode showed `st_nlink == 0`
with otherwise healthy attributes (regular file, mode 0600, current user). Observed once as
`test_domain_permissions.py::test_concurrent_persistent_registration_preserves_both_descriptors`
failing under full-suite load on 2026-09-12; a raw two-thread churn reproduced the transient
`st_nlink == 0` observation within seconds.

## Fix

The sidecar predicate now fails on `st_nlink > 1` (a hardlinked inode reachable elsewhere)
instead of `st_nlink != 1`. A healthy sidecar observed at `st_nlink == 0` is a concurrent
close-time unlink — the inode is reachable by no other name — and is treated as already
absent. Symlinks, foreign owners, wrong modes and non-regular files still fail exactly as
before, so no security property is weakened: the previous check was equally point-in-time.

## Verification

```text
python -m pytest -q app/tests/test_domain_storage.py
87 passed  (includes the new nlink 0/1/2 parametrized regression:
            0 and 1 accepted, 2 rejected as a hardlink)

test_concurrent_persistent_registration_preserves_both_descriptors: 6/6 repeats pass

6-second two-writer/two-checker sidecar churn through DomainStore._connection:
zero UnsafePath (the same churn reproduced the transient before the fix)
```

The full shared regression count is recorded in the commit message.
