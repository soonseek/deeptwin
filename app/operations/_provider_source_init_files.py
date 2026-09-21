"""Private fixed 18-file no-replace publication; never observes channel payloads."""

import os
from uuid import uuid4

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import publication as p
from app.deployment._provider_source_files import _FILES, _ROOT
from app.deployment.provider_source_contracts import validate_provider_source_bundle


class _BundlePublication(f.RetainedHandle):
    def __init__(self):
        raise TypeError("bundle publication requires staging")

    def recheck_current(self):
        if self._closed:
            raise c.DeploymentSourceError()
        root = f.identity(f.stat_fd(self._root.fd))
        expected = self._root.identity
        if (root.device, root.inode) != (expected.device, expected.inode):
            raise c.DeploymentSourceError()
        if not self._committed:
            self._root.recheck_current()
            if f.signature(f.stat_fd(self._root.fd)) != self._root_signature:
                raise c.DeploymentSourceError()
        elif (root.uid, root.gid, root.mode) != (0, 21201, 0o750):
            raise c.DeploymentSourceError()
        if f.members(self._root.fd, 1) != {self._name}:
            raise c.DeploymentSourceError()
        if (
            f.identity(f.stat_at(self._root.fd, self._name)) != self._directory_identity
            or f.identity(f.stat_fd(self._fd)) != self._directory_identity
        ):
            raise c.DeploymentSourceError()
        if (
            not self._committed
            and f.signature(f.stat_fd(self._fd)) != self._directory_signature
        ):
            raise c.DeploymentSourceError()
        if f.members(self._fd, 18) != {name for name, _ in self._files}:
            raise c.DeploymentSourceError()
        for (name, raw), (fd, signature) in zip(self._files, self._leaves, strict=True):
            if (
                f.signature(f.stat_fd(fd)) != signature
                or f.signature(f.stat_at(self._fd, name)) != signature
                or f.read_exact(fd, len(raw)) != raw
            ):
                raise c.DeploymentSourceError()

    def _object_identities(self):
        self.recheck_current()
        return f.identity(f.stat_fd(self._fd)), tuple(
            (name, f.identity(f.stat_fd(fd)))
            for (name, _), (fd, _) in zip(self._files, self._leaves, strict=True)
        )

    def close(self):
        if not self._closed:
            self._closed = True
            failure = None
            for fd in (*self._owned_fds, self._fd):
                try:
                    f.close_fd(fd)
                except BaseException as error:  # noqa: BLE001 - rethrow after all closes
                    if failure is None:
                        failure = error
            if failure is not None:
                raise failure


def _stage_bundle(root: f.Directory, expected_files: tuple):
    if type(root) is not f.Directory or root.path != _ROOT:
        raise c.DeploymentSourceError()
    root.recheck_current()
    if (root.identity.uid, root.identity.gid, root.identity.mode) != (
        0,
        0,
        0o755,
    ) or f.members(root.fd, 1):
        raise c.DeploymentSourceError()
    validate_provider_source_bundle(expected_files)
    if tuple(name for name, _ in expected_files) != tuple(name for name, _ in _FILES):
        raise c.DeploymentSourceError()
    result = object.__new__(_BundlePublication)
    result._root, result._files = root, expected_files
    result._fd, result._closed, result._committed = -1, False, False
    result._owned_fds, result._leaves = [], []
    result._name = f".stage-{uuid4()}.tmp"
    try:
        os.mkdir(result._name, 0o700, dir_fd=root.fd)
        result._fd = os.open(
            result._name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=root.fd,
        )
        initial = f.identity(f.stat_fd(result._fd))
        if (
            initial != f.identity(f.stat_at(root.fd, result._name))
            or initial.device != root.identity.device
        ):
            raise c.DeploymentSourceError()
        for name, raw in expected_files:
            fd = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=result._fd,
            )
            result._owned_fds.append(fd)
            p._write_all(fd, raw)
            os.fchown(fd, 0, 21201)
            os.fchmod(fd, 0o440)
            os.fsync(fd)
            info = f.stat_fd(fd)
            f.validate_regular(info, uid=0, gid=21201, mode=0o440, cap=len(raw))
            signature = f.signature(info)
            if (
                info.st_dev != initial.device
                or signature != f.signature(f.stat_at(result._fd, name))
                or f.read_exact(fd, len(raw)) != raw
            ):
                raise c.DeploymentSourceError()
            result._leaves.append((fd, signature))
        os.fchown(result._fd, 0, 21201)
        os.fchmod(result._fd, 0o750)
        os.fsync(result._fd)
        result._directory_identity = f.validate_directory(
            result._fd, uid=0, gid=21201, mode=0o750
        )
        if (result._directory_identity.device, result._directory_identity.inode) != (
            initial.device,
            initial.inode,
        ):
            raise c.DeploymentSourceError()
        result._directory_signature = f.signature(f.stat_fd(result._fd))
        result._root_signature = f.signature(f.stat_fd(root.fd))
        result.recheck_current()
        return result
    except BaseException:
        try:
            result.close()
        except BaseException:  # noqa: BLE001, S110 - preserve the active primary
            pass
        raise


def _commit_bundle(publication: _BundlePublication):
    if type(publication) is not _BundlePublication or publication._committed:
        raise c.DeploymentSourceError()
    publication.recheck_current()
    root = publication._root
    p._rename_noreplace(root.fd, publication._name, "documents")
    publication._name = "documents"
    os.fsync(root.fd)
    os.fchown(root.fd, 0, 21201)
    os.fchmod(root.fd, 0o750)
    publication._committed = True
    publication.recheck_current()
