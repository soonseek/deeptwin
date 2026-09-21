"""Single serving owner, bounded FIFO native work, and independent rate buckets."""
import fcntl
import os
import stat
import time
from collections import deque
from threading import Condition, RLock


class AdmissionRejected(RuntimeError):
    pass


class ServingLock:
    """OS released exclusivity; the file holds no key or credential."""
    def __init__(self, directory, *, expected_uid, expected_gid, create=True):
        self._fd = None
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            metadata = os.fstat(parent)
            if (metadata.st_uid != expected_uid or metadata.st_gid != expected_gid
                    or stat.S_IMODE(metadata.st_mode) != 0o700):
                raise AdmissionRejected("Serving ownership unavailable")
            try:
                if not create:
                    raise FileExistsError
                fd = os.open("owner-auth.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
                os.fsync(fd)
                os.fsync(parent)
            except FileExistsError:
                fd = os.open("owner-auth.lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=parent)
            self._fd = fd
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or metadata.st_uid != expected_uid or metadata.st_gid != expected_gid
                    or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_size != 0):
                raise AdmissionRejected("Serving ownership unavailable")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            visible = os.stat("owner-auth.lock", dir_fd=parent, follow_symlinks=False)
            if (metadata.st_dev, metadata.st_ino) != (visible.st_dev, visible.st_ino):
                raise AdmissionRejected("Serving ownership unavailable")
        except BaseException as exc:
            self.close()
            if isinstance(exc, (OSError, AdmissionRejected)):
                raise AdmissionRejected("Serving ownership unavailable") from None
            raise
        finally:
            os.close(parent)

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


class PasswordLane:
    def __init__(self, *, timeout=10.0):
        self._condition = Condition()
        self._queue = deque()
        self._timeout = timeout
        self._closed = False

    def reserve(self):
        with self._condition:
            if self._closed or len(self._queue) >= 4:
                raise AdmissionRejected("Password capacity unavailable")
            reservation = _Reservation(self, time.monotonic() + self._timeout)
            self._queue.append(reservation)
            return reservation

    def close(self):
        with self._condition:
            self._closed = True
            for reservation in tuple(self._queue):
                reservation.close()
            while self._queue:
                self._condition.wait()


class _Reservation:
    def __init__(self, lane, deadline):
        self._lane, self._deadline = lane, deadline
        self._running = self._closed = False

    def run(self, operation):
        lane = self._lane
        with lane._condition:
            while not self._closed and lane._queue[0] is not self:
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    self.close()
                    raise AdmissionRejected("Password capacity unavailable")
                lane._condition.wait(remaining)
            if self._closed or time.monotonic() > self._deadline:
                self.close()
                raise AdmissionRejected("Password capacity unavailable")
            self._running = True
        try:
            return operation()
        finally:
            with lane._condition:
                self._running = False
                self.close()

    def close(self):
        with self._lane._condition:
            # Cancellation cannot release a still-running native operation.
            if not self._running and not self._closed:
                self._closed = True
                self._lane._queue.remove(self)
                self._lane._condition.notify_all()


class PasswordBuckets:
    def __init__(self):
        self._lock = RLock()
        self._sources, self._accounts = {}, {}

    def admit(self, source, account):
        now = time.monotonic()
        with self._lock:
            candidates = []
            for mapping, key in ((self._sources, source), (self._accounts, account)):
                for stale in [key for key, (_, used) in mapping.items() if now - used >= 60]:
                    del mapping[stale]
                if key not in mapping and len(mapping) >= 1024:
                    raise AdmissionRejected("Password rate unavailable")
                tokens, last = mapping.get(key, (5.0, now))
                tokens = min(5.0, tokens + (now - last) / 6)
                if tokens < 1:
                    raise AdmissionRejected("Password rate unavailable")
                candidates.append((mapping, key, tokens - 1))
            for mapping, key, tokens in candidates:
                mapping[key] = (tokens, now)
