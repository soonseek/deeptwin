"""Deployment-only offline migration. External process isolation remains required.

The cooperative lock does not fence standalone legacy writers. Stdlib SQLite's
pathname/VFS race against hostile same-UID processes is not native qualification.
"""
import os
from pathlib import Path
import sqlite3
import stat
import time

from ..domain.refs import uuid_string
from ..services.owner_admission import AdmissionRejected, ServingLock
from ..runtime.ledger_schema import LEDGER_V1_SHA256, LEDGER_V2_SHA256, _schema_version
from ..runtime.ledger_migrations import (LedgerMigrationError, _remaining, _preflight, _rebuild,
                                       _verify_history, _compare, _verify_metadata,
                                       _inbound_attempt_foreign_keys, _size, _plans)


def _metadata(fd, uid, gid, *, directory=False):
    row = os.fstat(fd)
    valid_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (not valid_type(row.st_mode) or row.st_uid != uid or row.st_gid != gid
            or stat.S_IMODE(row.st_mode) != (0o700 if directory else 0o600)
            or (not directory and row.st_nlink != 1)):
        raise LedgerMigrationError("unavailable")
    return row.st_dev, row.st_ino


def _directory(path):
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


class _Handles:
    def __init__(self, path, uid, gid):
        self.path, self.uid, self.gid = path, uid, gid
        self.directory = self.database = None
        self.lock = None
        try:
            self.directory = _directory(path)
            _metadata(self.directory, uid, gid, directory=True)
            self.database = os.open("intake.sqlite3", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory)
            self.check()
            try:
                self.lock = ServingLock(path, expected_uid=uid, expected_gid=gid, create=False)
            except AdmissionRejected:
                # Missing/unsafe lock is unavailable; valid contended lock is busy.
                fd = os.open("owner-auth.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory)
                try:
                    _metadata(fd, uid, gid)
                    if os.fstat(fd).st_size != 0:
                        raise LedgerMigrationError("unavailable")
                finally:
                    os.close(fd)
                raise LedgerMigrationError("busy") from None
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        visible = _directory(self.path)
        try:
            if _metadata(visible, self.uid, self.gid, directory=True) != _metadata(
                    self.directory, self.uid, self.gid, directory=True):
                raise LedgerMigrationError("unavailable")
        finally:
            os.close(visible)
        for name, held in (("intake.sqlite3", self.database),
                           ("owner-auth.lock", None if self.lock is None else self.lock._fd)):
            if held is None:
                continue
            actual = os.stat(name, dir_fd=self.directory, follow_symlinks=False)
            if _metadata(held, self.uid, self.gid) != (actual.st_dev, actual.st_ino):
                raise LedgerMigrationError("unavailable")
            if name == "owner-auth.lock" and os.fstat(held).st_size != 0:
                raise LedgerMigrationError("unavailable")
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                fd = os.open("intake.sqlite3" + suffix, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory)
            except FileNotFoundError:
                continue
            try:
                _metadata(fd, self.uid, self.gid)
                visible = os.stat("intake.sqlite3" + suffix, dir_fd=self.directory, follow_symlinks=False)
                held = os.fstat(fd)
                if (held.st_dev, held.st_ino) != (visible.st_dev, visible.st_ino):
                    raise LedgerMigrationError("unavailable")
            finally:
                os.close(fd)

    def close(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None
        for name in ("database", "directory"):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)


def _open(handles, deadline):
    handles.check()
    path = handles.path / "intake.sqlite3"
    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None,
                         timeout=min(5, _remaining(deadline)))
    try:
        db.row_factory = sqlite3.Row
        if [tuple(row) for row in db.execute("PRAGMA database_list")] != [(0, "main", str(path))]:
            raise LedgerMigrationError("unavailable")
        handles.check()
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA fullfsync=ON")
        for pragma, expected in (("foreign_keys", 1), ("trusted_schema", 0),
                                 ("synchronous", 2), ("fullfsync", 1),
                                 ("journal_mode", "wal"), ("encoding", "UTF-8")):
            if db.execute("PRAGMA " + pragma).fetchone()[0] != expected:
                raise LedgerMigrationError("maintenance_required")
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1)
        return db
    except BaseException:
        db.close()
        raise


def migrate_runtime_ledger_v1_to_v2(data_directory, *, expected_uid, expected_gid,
                                    expected_vault_id, expected_v1_digest):
    """No startup call site; success certifies SQL metadata, not physical blob bytes."""
    deadline = time.monotonic() + 30
    try:
        if (type(expected_uid) is not int or type(expected_gid) is not int
                or min(expected_uid, expected_gid) < 0 or expected_v1_digest != LEDGER_V1_SHA256):
            raise ValueError
        uuid_string(expected_vault_id)
        path = Path(os.path.abspath(os.fspath(data_directory)))
    except (ValueError, TypeError):
        raise LedgerMigrationError("invalid_request") from None
    if os.geteuid() != expected_uid or os.getegid() != expected_gid:
        raise LedgerMigrationError("unavailable")
    handles = db = None
    commit_attempted = False
    try:
        _remaining(deadline)
        handles = _Handles(path, expected_uid, expected_gid)
        db = _open(handles, deadline)
        handles.check()
        db.execute("PRAGMA busy_timeout=%d" % int(min(5, _remaining(deadline)) * 1000))
        db.execute("BEGIN EXCLUSIVE")
        version, snapshots = _preflight(db, expected_vault_id, deadline)
        attempts = len(snapshots["runtime_attempts"][4])
        executions = len(snapshots["runtime_node_executions"][4])
        if version == 1:
            _rebuild(db, snapshots, deadline)
        roots = _verify_history(db, expected_vault_id)
        _verify_metadata(db, snapshots, roots, deadline)
        handles.check()
        _remaining(deadline)
        db.execute("PRAGMA busy_timeout=%d" % int(min(5, _remaining(deadline)) * 1000))
        commit_attempted = True
        db.execute("COMMIT")
        db.close()
        db = None
        handles.check()
        db = _open(handles, deadline)
        db.execute("BEGIN")
        if _schema_version(db) != 2:
            raise LedgerMigrationError("outcome_unknown")
        _inbound_attempt_foreign_keys(db)
        _size(db, _plans(db), deadline)
        _compare(db, snapshots, deadline, migrated=version == 1)
        roots = _verify_history(db, expected_vault_id)
        _verify_metadata(db, snapshots, roots, deadline)
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise LedgerMigrationError("outcome_unknown")
        handles.check()
        _remaining(deadline)
        db.execute("ROLLBACK")
        db.close()
        db = None
        return dict(schema_version="runtime-ledger-migration-v1", vault_id=expected_vault_id,
                    from_version=version, to_version=2, state="migrated" if version == 1 else "already_current",
                    v1_sha256=LEDGER_V1_SHA256, v2_sha256=LEDGER_V2_SHA256,
                    attempts=attempts, executions=executions)
    except BaseException as exc:
        unknown = commit_attempted
        if db is not None and db.in_transaction:
            try:
                db.set_progress_handler(None, 0)
                db.execute("ROLLBACK")
            except BaseException:
                unknown = True
        if unknown:
            raise LedgerMigrationError("outcome_unknown") from None
        if not isinstance(exc, Exception):
            raise
        if isinstance(exc, LedgerMigrationError):
            raise exc from None
        if time.monotonic() >= deadline:
            code = "deadline_exceeded"
        elif isinstance(exc, sqlite3.OperationalError) and getattr(exc, "sqlite_errorcode", None) in (5, 6):
            code = "busy"
        elif isinstance(exc, OSError):
            code = "unavailable"
        else:
            code = "maintenance_required"
        raise LedgerMigrationError(code) from None
    finally:
        try:
            try:
                if db is not None:
                    db.close()
            finally:
                if handles is not None:
                    handles.close()
        except BaseException:
            raise LedgerMigrationError("outcome_unknown") from None
