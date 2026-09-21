"""Checked descriptor-relative credential filesystem operations; no domain store."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import time

from .credential_contracts import CredentialVaultError

BUSY_SECONDS = 5.0


class CustodyBudget:
    """One absolute cancellation/deadline budget for controllable custody waits."""
    __slots__ = ("deadline_monotonic", "cancel_event")

    def __init__(self, deadline_monotonic, cancel_event):
        if (type(deadline_monotonic) not in (int, float) or not deadline_monotonic > time.monotonic()
                or not hasattr(cancel_event, "is_set") or not hasattr(cancel_event, "wait")):
            raise CredentialVaultError("invalid_metadata")
        self.deadline_monotonic = float(deadline_monotonic)
        self.cancel_event = cancel_event

    def checkpoint(self):
        if self.cancel_event.is_set():
            raise CredentialVaultError("cancelled")
        if time.monotonic() >= self.deadline_monotonic:
            raise CredentialVaultError("deadline_exceeded")

    def wait_slice(self):
        self.checkpoint()
        return min(0.010, max(0.0, self.deadline_monotonic - time.monotonic()))


def checked(info, uid, gid, mode, directory=False):
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not correct_type or info.st_uid != uid or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != mode or (not directory and info.st_nlink != 1)):
        raise CredentialVaultError("maintenance_required")


def open_directory(path):
    """Reject links in every supplied component, including unmanaged parents."""
    path = os.path.abspath(os.fspath(path))
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in Path(path).parts[1:]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except OSError:
        os.close(fd)
        raise CredentialVaultError("maintenance_required") from None


class Directory:
    def __init__(self, path, uid, gid):
        self.path = os.path.abspath(os.fspath(path))
        self.uid, self.gid = uid, gid
        self.fd = open_directory(path)
        try:
            checked(os.fstat(self.fd), uid, gid, 0o700, True)
            self.identity = (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def verify(self):
        if self.fd is None:
            raise CredentialVaultError("closed")
        fd = open_directory(self.path)
        try:
            info = os.fstat(fd)
            checked(info, self.uid, self.gid, 0o700, True)
            if (info.st_dev, info.st_ino) != self.identity:
                raise CredentialVaultError("maintenance_required")
        finally:
            os.close(fd)

    def names(self):
        return set(os.listdir(self.fd))

    def file(self, name, mode=0o600, *, create=False, writable=False):
        if "/" in name or name in ("", ".", ".."):
            raise CredentialVaultError("maintenance_required")
        flags = os.O_RDWR if writable else os.O_RDONLY
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(name, flags | os.O_NOFOLLOW, mode, dir_fd=self.fd)
            try:
                checked(os.fstat(fd), self.uid, self.gid, mode)
                return fd
            except BaseException:
                os.close(fd)
                raise
        except OSError:
            raise CredentialVaultError("maintenance_required") from None

    def read(self, name, limit, mode=0o600):
        fd = self.file(name, mode)
        try:
            if os.fstat(fd).st_size > limit:
                raise CredentialVaultError("maintenance_required")
            data = bytearray()
            while len(data) <= limit:
                part = os.read(fd, min(65536, limit + 1 - len(data)))
                if not part:
                    break
                data.extend(part)
            if len(data) > limit:
                raise CredentialVaultError("maintenance_required")
            return bytes(data)
        finally:
            os.close(fd)

    def write(self, name, payload, mode=0o600):
        fd = self.file(name, mode, create=True, writable=True)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise CredentialVaultError("storage_failure")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.fd)

    def child(self, name, *, create=False):
        if "/" in name or name in ("", ".", ".."):
            raise CredentialVaultError("maintenance_required")
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=self.fd)
                os.fsync(self.fd)
            except FileExistsError:
                pass
        return Directory(os.path.join(self.path, name), self.uid, self.gid)


def separate(root, records):
    a, b = os.path.abspath(os.fspath(root)), os.path.abspath(os.fspath(records))
    if os.path.commonpath((a, b)) in (a, b):
        raise CredentialVaultError("maintenance_required")
    if os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b):
        raise CredentialVaultError("maintenance_required")


def approved_directory(path, uid, gid):
    path = os.path.abspath(os.fspath(path))
    parent_fd = open_directory(os.path.dirname(path))
    try:
        try:
            os.mkdir(os.path.basename(path), 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
    finally:
        os.close(parent_fd)
    return Directory(path, uid, gid)


def lock_fd(directory, name, *, create=False):
    if create and name not in directory.names():
        try:
            directory.write(name, b"")
        except CredentialVaultError:
            if name not in directory.names():
                raise
    fd = directory.file(name, writable=True)
    if os.fstat(fd).st_size:
        os.close(fd)
        raise CredentialVaultError("maintenance_required")
    return fd


def acquire(fd, exclusive=True, *, custody_budget=None):
    expires = time.monotonic() + BUSY_SECONDS
    while True:
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if custody_budget is not None:
                custody_budget.cancel_event.wait(custody_budget.wait_slice())
                continue
            if time.monotonic() >= expires:
                raise CredentialVaultError("busy") from None
            time.sleep(min(0.01, max(0, expires - time.monotonic())))


@contextmanager
def exclusion(directory, name, *, exclusive=True, create=False, custody_budget=None):
    if custody_budget is not None:
        custody_budget.checkpoint()
    fd = lock_fd(directory, name, create=create)
    try:
        acquire(fd, exclusive, custody_budget=custody_budget)
        if custody_budget is not None:
            custody_budget.checkpoint()
        directory.verify()
        # A replaced lock must never provide a second exclusion domain.
        current = directory.file(name, writable=True)
        try:
            if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (os.fstat(current).st_dev, os.fstat(current).st_ino):
                raise CredentialVaultError("maintenance_required")
        finally:
            os.close(current)
        yield
    finally:
        os.close(fd)
