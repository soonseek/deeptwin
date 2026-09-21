"""A separate process-shared, no-follow upload lease; never the serving-owner lock."""
import asyncio
import fcntl
import os
import stat

from .works import WorkServiceError


class UploadLock:
    def __init__(self, directory):
        self._fd = None
        self._operation = None
        parent = None
        try:
            parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or info.st_gid != os.getgid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise WorkServiceError("unavailable")
            try:
                self._fd = os.open("owner-material-upload.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                                   0o600, dir_fd=parent)
                os.fsync(self._fd)
                os.fsync(parent)
            except FileExistsError:
                self._fd = os.open("owner-material-upload.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            info = os.fstat(self._fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_gid != os.getgid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size != 0):
                raise WorkServiceError("unavailable")
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkServiceError("capacity") from None
        except BaseException as error:
            self.close()
            if isinstance(error, OSError):
                raise WorkServiceError("unavailable") from None
            raise
        finally:
            if parent is not None:
                os.close(parent)

    async def publish(self, operation, *args):
        # The child task owns the FD through the actual thread completion. Cancelling
        # the HTTP awaiter cannot cancel the child or release its publication lease.
        # the services layer stays free of the presentation stack: the loop's own thread pool
        self._operation = asyncio.create_task(asyncio.to_thread(operation, *args))

        def finished(task):
            if not task.cancelled():
                task.exception()  # consume an error even if its HTTP awaiter has gone
            self.close()

        self._operation.add_done_callback(finished)
        return await asyncio.shield(self._operation)

    def close(self):
        if self._operation is not None and not self._operation.done():
            return
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
