"""Retained fixed-input and no-replace installation mechanics for root initializers."""

import os
import stat
from pathlib import Path
from uuid import uuid4

from . import contracts as c
from . import files as f
from . import publication as p


class _PublicInputFile(f.RetainedHandle):
    """A regular fixed input retained by descriptor and its original directory entry."""

    @classmethod
    def open(cls, directory, name, *, cap, modes):
        if type(directory) is not f.Directory or type(name) is not str:
            raise c.DeploymentSourceError()
        info = f.stat_at(directory.fd, name)
        mode = stat.S_IMODE(info.st_mode)
        if mode not in modes:
            raise c.DeploymentSourceError()
        fd = f.open_regular(
            directory.fd,
            name,
            uid=0,
            gid=0,
            mode=mode,
            cap=cap,
        )
        try:
            result = cls()
            result._directory = directory
            result.name, result.fd, result.cap = name, fd, cap
            result._signature = f.signature(f.stat_fd(fd))
            result._closed = False
            result._bytes = result._read_current()
            return result
        except BaseException as error:
            try:
                f.close_fd(fd)
            except BaseException:  # noqa: BLE001, S110 - preserve the active primary
                pass
            if isinstance(error, (OSError, c.DeploymentSourceError)):
                raise c.DeploymentSourceError() from None
            raise

    def _read_current(self):
        self._directory.recheck_current()
        try:
            if (
                f.signature(f.stat_fd(self.fd)) != self._signature
                or f.signature(f.stat_at(self._directory.fd, self.name))
                != self._signature
            ):
                raise c.DeploymentSourceError()
            raw = f.read_exact(self.fd, self.cap)
            if (
                f.signature(f.stat_fd(self.fd)) != self._signature
                or f.signature(f.stat_at(self._directory.fd, self.name))
                != self._signature
            ):
                raise c.DeploymentSourceError()
            self._directory.recheck_current()
            return raw
        except OSError:
            raise c.DeploymentSourceUnavailable() from None

    def read_current(self):
        if self._closed:
            raise c.DeploymentSourceError()
        raw = self._read_current()
        if raw != self._bytes:
            raise c.DeploymentSourceError()
        return raw

    @property
    def identity(self):
        if self._closed:
            raise c.DeploymentSourceError()
        return self._signature[0]

    def close(self):
        if not self._closed:
            self._closed = True
            f.close_fd(self.fd)


class _ReleaseInput(f.RetainedHandle):
    """A fixed release file retained together with every validated ancestor."""

    @classmethod
    def open(cls, relative, cap):
        if type(relative) is not str:
            raise c.DeploymentSourceError()
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or relative_path.anchor
            or ".." in relative_path.parts
            or str(relative_path) != relative
        ):
            raise c.DeploymentSourceError()
        path = c.RELEASE_ROOT / relative_path
        handles = []
        source = None
        try:
            for parent in reversed(path.parent.parents):
                directory = f.Directory.open(parent, uid=0, gid=0)
                handles.append(directory)
                if directory.identity.mode not in (0o750, 0o755):
                    raise c.DeploymentSourceError()
            directory = f.Directory.open(path.parent, uid=0, gid=0)
            handles.append(directory)
            if directory.identity.mode not in (0o750, 0o755):
                raise c.DeploymentSourceError()
            source = _PublicInputFile.open(
                directory,
                path.name,
                cap=cap,
                modes=(0o444, 0o644),
            )
            result = cls()
            result.path, result._ancestors, result._source = path, handles, source
            result._closed = False
            result._bytes = result.read_current()
            return result
        except BaseException as error:
            for handle in ([source] if source is not None else []) + handles:
                try:
                    handle.close()
                except BaseException:  # noqa: BLE001, S110 - attempt remaining closes
                    pass
            if isinstance(error, (OSError, c.DeploymentSourceError)):
                raise c.DeploymentSourceError() from None
            raise

    @property
    def identity(self):
        if self._closed:
            raise c.DeploymentSourceError()
        return self._source.identity

    def read_current(self):
        if self._closed:
            raise c.DeploymentSourceError()
        raw = self._source.read_current()
        for handle in self._ancestors:
            handle.recheck_current()
        if raw != self._bytes if hasattr(self, "_bytes") else False:
            raise c.DeploymentSourceError()
        return raw

    def close(self):
        if not self._closed:
            self._closed = True
            failure = None
            for handle in (self._source, *self._ancestors):
                try:
                    handle.close()
                except BaseException as error:  # noqa: BLE001 - rethrow after all closes
                    if failure is None:
                        failure = error
            if failure is not None:
                raise failure


class _RetainedTargetFile(f.RetainedHandle):
    """A just-published file retaining the descriptor used for its commit."""

    @classmethod
    def _take(cls, directory, name, fd, raw, gid):
        if f.members(directory.fd, 1) != {name}:
            raise c.DeploymentSourceError()
        info = f.stat_fd(fd)
        f.validate_regular(info, uid=0, gid=gid, mode=0o440, cap=len(raw))
        signature = f.signature(info)
        if (
            f.signature(f.stat_at(directory.fd, name)) != signature
            or f.signature(f.stat_fd(fd)) != signature
        ):
            raise c.DeploymentSourceError()
        if f.members(directory.fd, 1) != {name}:
            raise c.DeploymentSourceError()
        result = cls()
        result._directory = directory
        result._root_object = (directory.identity.device, directory.identity.inode)
        result.name, result.fd, result._bytes, result._gid = name, fd, raw, gid
        result._signature = signature
        result._closed = False
        return result

    def _validated_signature(self):
        info = f.stat_fd(self.fd)
        f.validate_regular(
            info,
            uid=0,
            gid=self._gid,
            mode=0o440,
            cap=len(self._bytes),
        )
        return f.signature(info)

    @property
    def identity(self):
        if self._closed:
            raise c.DeploymentSourceError()
        return self._signature[0]

    def rebind_directory(self, directory):
        if self._closed or type(directory) is not f.Directory:
            raise c.DeploymentSourceError()
        if (directory.identity.device, directory.identity.inode) != self._root_object:
            raise c.DeploymentSourceError()
        self._directory = directory

    def read_current(self):
        if self._closed:
            raise c.DeploymentSourceError()
        self._directory.recheck_current()
        try:
            if (
                f.members(self._directory.fd, 1) != {self.name}
                or self._validated_signature() != self._signature
                or f.signature(f.stat_at(self._directory.fd, self.name))
                != self._signature
            ):
                raise c.DeploymentSourceError()
            raw = f.read_exact(self.fd, len(self._bytes))
            if (
                raw != self._bytes
                or self._validated_signature() != self._signature
                or f.signature(f.stat_at(self._directory.fd, self.name))
                != self._signature
                or f.members(self._directory.fd, 1) != {self.name}
            ):
                raise c.DeploymentSourceError()
            self._directory.recheck_current()
            return raw
        except OSError:
            raise c.DeploymentSourceUnavailable() from None

    def close(self):
        if not self._closed:
            self._closed = True
            f.close_fd(self.fd)


def _take_directory(parent, name, fd, uid, gid):
    """Transfer a newly created directory FD into the authoritative handle type."""
    result = object.__new__(f.Directory)
    result.path, result.fd = parent.path / name, fd
    result.identity = f.validate_directory(fd, uid=uid, gid=gid, mode=0o750)
    result._uid, result._gid, result._mode, result._search = uid, gid, 0o750, False
    result._closed = False
    return result


def _read_at(directory, name, *, cap, modes):
    source = _PublicInputFile.open(directory, name, cap=cap, modes=modes)
    try:
        return source.read_current()
    finally:
        source.close()


def _release(relative, cap):
    source = _ReleaseInput.open(relative, cap)
    try:
        return source.read_current()
    finally:
        source.close()


def _empty(directory):
    if f.members(directory.fd, 64):
        return False
    if (directory.identity.uid, directory.identity.gid, directory.identity.mode) != (
        0,
        0,
        0o755,
    ):
        raise c.DeploymentSourceError()
    return True


def _install_source_impl(directory, name, raw, gid, *, retain):
    directory.recheck_current()
    if not _empty(directory):
        raise c.DeploymentSourceError()
    os.fchown(directory.fd, 0, gid)
    os.fchmod(directory.fd, 0o750)
    stage = f".stage-{uuid4()}.tmp"
    fd = -1
    retained = None
    try:
        fd = os.open(
            stage,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory.fd,
        )
        p._write_all(fd, raw)
        os.fchown(fd, 0, gid)
        os.fchmod(fd, 0o440)
        os.fsync(fd)
        before = f.signature(f.stat_fd(fd))
        f.validate_regular(f.stat_fd(fd), uid=0, gid=gid, mode=0o440, cap=len(raw))
        if f.signature(f.stat_at(directory.fd, stage)) != before:
            raise c.DeploymentSourceError()
        p._rename_noreplace(directory.fd, stage, name)
        os.fsync(directory.fd)
        if f.signature(f.stat_at(directory.fd, name)) != f.signature(f.stat_fd(fd)):
            raise c.DeploymentSourceError()
        if retain:
            retained = _RetainedTargetFile._take(directory, name, fd, raw, gid)
            fd = -1
        return retained
    finally:
        f.close_fd(fd)


def _install_source(directory, name, raw, gid):
    _install_source_impl(directory, name, raw, gid, retain=False)


def _install_source_retained(directory, name, raw, gid):
    return _install_source_impl(directory, name, raw, gid, retain=True)


def _install_namespaces_impl(directory, *, names, uid, gid, retain):
    directory.recheck_current()
    if not _empty(directory):
        raise c.DeploymentSourceError()
    retained = []
    try:
        for name in names:
            os.mkdir(name, 0o700, dir_fd=directory.fd)
            fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory.fd,
            )
            try:
                os.fchown(fd, uid, gid)
                os.fchmod(fd, 0o750)
                os.fsync(fd)
                if retain:
                    retained.append(_take_directory(directory, name, fd, uid, gid))
                    fd = -1
            except BaseException:
                try:
                    f.close_fd(fd)
                except BaseException:  # noqa: BLE001, S110 - preserve the active primary
                    pass
                raise
            else:
                f.close_fd(fd)
            os.fsync(directory.fd)
        # Child metadata is durable before the writer/control owns the volume root.
        os.fchown(directory.fd, uid, gid)
        os.fchmod(directory.fd, 0o750)
        os.fsync(directory.fd)
        return tuple(retained)
    except BaseException:
        for handle in retained:
            try:
                handle.close()
            except BaseException:  # noqa: BLE001, S110 - attempt remaining closes
                pass
        raise


def _install_namespaces(directory, *, names, uid, gid):
    _install_namespaces_impl(
        directory,
        names=names,
        uid=uid,
        gid=gid,
        retain=False,
    )


def _install_namespaces_retained(directory, *, names, uid, gid):
    return _install_namespaces_impl(
        directory,
        names=names,
        uid=uid,
        gid=gid,
        retain=True,
    )
