"""Bounded no-follow retained file/directory observations; no root repair."""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .contracts import (
    DeploymentSourceError,
    DeploymentSourceUnavailable,
    digest,
    hex_digest,
    uuid,
)


def stat_fd(fd):
    return os.fstat(fd)


def stat_at(fd, name):
    return os.stat(name, dir_fd=fd, follow_symlinks=False)


def close_fd(fd):
    if fd >= 0:
        try:
            os.close(fd)
        except OSError:
            pass


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    uid: int
    gid: int
    mode: int


def identity(info):
    if not 0 <= info.st_dev <= 2**63 - 1 or not 1 <= info.st_ino <= 2**63 - 1:
        raise DeploymentSourceError()
    return FileIdentity(
        info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)
    )


def signature(info):
    return (
        identity(info),
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def open_directory(path, *, search=False):
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.anchor != "/"
        or ".." in path.parts
        or len(os.fsencode(path)) > 4096
    ):
        raise DeploymentSourceError()
    fd = -1
    try:
        flags = (
            (getattr(os, "O_PATH", os.O_RDONLY) if search else os.O_RDONLY)
            | os.O_CLOEXEC
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
        )
        fd = os.open("/", flags)
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            close_fd(fd)
            fd = child
        return fd
    except (OSError, AttributeError):
        close_fd(fd)
        raise DeploymentSourceUnavailable() from None


def members(fd, maximum):
    result = set()
    try:
        with os.scandir(fd) as entries:
            for entry in entries:
                result.add(entry.name)
                if len(result) > maximum:
                    raise DeploymentSourceError()
        return result
    except OSError:
        raise DeploymentSourceUnavailable() from None


def validate_directory(fd, *, uid=None, gid=None, mode=None):
    info = stat_fd(fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or uid is not None
        and info.st_uid != uid
        or gid is not None
        and info.st_gid != gid
        or mode is not None
        and stat.S_IMODE(info.st_mode) != mode
    ):
        raise DeploymentSourceError()
    return identity(info)


def open_regular(fd, name, *, uid, gid, mode, cap, empty=False):
    child = -1
    try:
        child = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd
        )
        info = stat_fd(child)
        validate_regular(info, uid=uid, gid=gid, mode=mode, cap=cap, empty=empty)
        return child
    except (OSError, DeploymentSourceError):
        close_fd(child)
        raise DeploymentSourceError() from None


def validate_regular(info, *, uid, gid, mode, cap, empty=False):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != uid
        or info.st_gid != gid
        or stat.S_IMODE(info.st_mode) != mode
        or not (0 if empty else 1) <= info.st_size <= cap
    ):
        raise DeploymentSourceError()


def read_exact(fd, cap):
    try:
        before = stat_fd(fd)
        if not 0 <= before.st_size <= cap:
            raise DeploymentSourceError()
        os.lseek(fd, 0, os.SEEK_SET)
        result = bytearray()
        while len(result) <= cap:
            part = os.read(fd, min(65536, cap + 1 - len(result)))
            if not part:
                break
            result.extend(part)
        if len(result) != before.st_size or signature(before) != signature(stat_fd(fd)):
            raise DeploymentSourceError()
        return bytes(result)
    except OSError:
        raise DeploymentSourceUnavailable() from None


class RetainedHandle:
    def __copy__(self):
        raise TypeError("retained source is not copyable")

    def __deepcopy__(self, _memo):
        raise TypeError("retained source is not copyable")

    def __reduce__(self):
        raise TypeError("retained source is not serializable")

    def __enter__(self):
        if self._closed:
            raise DeploymentSourceError()
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.close()


class Directory(RetainedHandle):
    @classmethod
    def open(cls, path, *, uid=None, gid=None, mode=None, search=False):
        fd = open_directory(path, search=search)
        try:
            observed = validate_directory(fd, uid=uid, gid=gid, mode=mode)
            result = cls()
            result.path, result.fd, result.identity = path, fd, observed
            result._uid, result._gid, result._mode, result._search = (
                uid,
                gid,
                mode,
                search,
            )
            result._closed = False
            result.recheck_current()
            return result
        except (OSError, DeploymentSourceError):
            close_fd(fd)
            raise DeploymentSourceError() from None

    def recheck_current(self):
        if self._closed:
            raise DeploymentSourceError()
        current = open_directory(self.path, search=self._search)
        try:
            for fd in (current, self.fd):
                if (
                    validate_directory(
                        fd, uid=self._uid, gid=self._gid, mode=self._mode
                    )
                    != self.identity
                ):
                    raise DeploymentSourceError()
            return self.identity
        except OSError:
            raise DeploymentSourceUnavailable() from None
        finally:
            close_fd(current)

    def close(self):
        if not self._closed:
            self._closed = True
            close_fd(self.fd)


class SourceFile(RetainedHandle):
    @classmethod
    def open(cls, path, name, *, uid, gid, cap, pin):
        hex_digest(pin)
        root = Directory.open(path, uid=uid, gid=gid, mode=0o750)
        fd = -1
        try:
            if members(root.fd, 1) != {name}:
                raise DeploymentSourceError()
            fd = open_regular(root.fd, name, uid=uid, gid=gid, mode=0o440, cap=cap)
            result = cls()
            result.root, result.fd, result.name = root, fd, name
            result.cap, result.pin = cap, pin
            result._signature, result._closed = signature(stat_fd(fd)), False
            result.read_current()
            return result
        except (OSError, DeploymentSourceError):
            root.close()
            close_fd(fd)
            raise DeploymentSourceError() from None

    def read_current(self):
        if self._closed:
            raise DeploymentSourceError()
        self.root.recheck_current()
        try:
            if members(self.root.fd, 1) != {self.name}:
                raise DeploymentSourceError()
            if (
                signature(stat_at(self.root.fd, self.name)) != self._signature
                or signature(stat_fd(self.fd)) != self._signature
            ):
                raise DeploymentSourceError()
            data = read_exact(self.fd, self.cap)
            if (
                digest(data) != self.pin
                or signature(stat_at(self.root.fd, self.name)) != self._signature
            ):
                raise DeploymentSourceError()
            return data
        except OSError:
            raise DeploymentSourceUnavailable() from None

    def close(self):
        if not self._closed:
            self._closed = True
            close_fd(self.fd)
            self.root.close()


@dataclass(frozen=True, slots=True)
class _NamespacePolicy:
    writer_uid: int
    primary_gid: int
    pair_gid: int
    final_limit: int
    stage_limit: int
    payload_cap: int


@dataclass(frozen=True, slots=True)
class _FinalEntry:
    name: str
    signature: tuple


@dataclass(frozen=True, slots=True)
class _NamespaceScan:
    finals: tuple[_FinalEntry, ...]
    stages: int


_REQUEST_NAMESPACE = _NamespacePolicy(20102, 20102, 21201, 16, 32, 65536)
_CANCEL_NAMESPACE = _NamespacePolicy(20102, 20102, 21201, 16, 32, 4096)
_INCOMING_NAMESPACE = _NamespacePolicy(20113, 20113, 21201, 64, 32, 16384)
_CONSUMED_NAMESPACE = _NamespacePolicy(20102, 20102, 21201, 16, 32, 4096)


def _scan_namespace(directory, *, policy):
    if type(directory) is not Directory or type(policy) is not _NamespacePolicy:
        raise DeploymentSourceError()
    finals = []
    stages = 0
    try:
        directory.recheck_current()
        directory_signature = signature(stat_fd(directory.fd))
        names = sorted(members(directory.fd, policy.final_limit + policy.stage_limit))
        observations = []
        for name in names:
            info = stat_at(directory.fd, name)
            if re.fullmatch(r"[0-9a-f]{64}\.json", name):
                validate_regular(
                    info,
                    uid=policy.writer_uid,
                    gid=policy.pair_gid,
                    mode=0o440,
                    cap=policy.payload_cap,
                )
                finals.append(_FinalEntry(name, signature(info)))
            elif name.startswith(".stage-") and name.endswith(".tmp"):
                uuid(name[7:-4])
                mode = stat.S_IMODE(info.st_mode)
                if (info.st_gid, mode) not in {
                    (policy.primary_gid, 0o600),
                    (policy.pair_gid, 0o600),
                    (policy.pair_gid, 0o440),
                }:
                    raise DeploymentSourceError()
                validate_regular(
                    info,
                    uid=policy.writer_uid,
                    gid=info.st_gid,
                    mode=mode,
                    cap=policy.payload_cap,
                    empty=True,
                )
                stages += 1
            else:
                raise DeploymentSourceError()
            observations.append((name, signature(info)))
        if len(finals) > policy.final_limit or stages > policy.stage_limit:
            raise DeploymentSourceError()
        if names != sorted(
            members(directory.fd, policy.final_limit + policy.stage_limit)
        ) or any(
            signature(stat_at(directory.fd, name)) != observed
            for name, observed in observations
        ):
            raise DeploymentSourceError()
        directory.recheck_current()
        if signature(stat_fd(directory.fd)) != directory_signature:
            raise DeploymentSourceError()
        return _NamespaceScan(tuple(finals), stages)
    except OSError:
        raise DeploymentSourceUnavailable() from None


class _FinalFile(RetainedHandle):
    def __init__(self):
        raise TypeError("final file construction requires a namespace scan")

    def read_current(self):
        if self._closed:
            raise DeploymentSourceError()
        self._directory.recheck_current()
        try:
            if (
                signature(stat_fd(self.fd)) != self._signature
                or signature(stat_at(self._directory.fd, self.name)) != self._signature
            ):
                raise DeploymentSourceError()
            raw = read_exact(self.fd, self._cap)
            if (
                signature(stat_fd(self.fd)) != self._signature
                or signature(stat_at(self._directory.fd, self.name)) != self._signature
            ):
                raise DeploymentSourceError()
            return raw
        except OSError:
            raise DeploymentSourceUnavailable() from None

    def close(self):
        if not self._closed:
            self._closed = True
            close_fd(self.fd)


def _open_final(directory, entry, *, policy):
    if (
        type(directory) is not Directory
        or type(entry) is not _FinalEntry
        or type(policy) is not _NamespacePolicy
    ):
        raise DeploymentSourceError()
    fd = -1
    try:
        fd = open_regular(
            directory.fd,
            entry.name,
            uid=policy.writer_uid,
            gid=policy.pair_gid,
            mode=0o440,
            cap=policy.payload_cap,
        )
        if (
            signature(stat_fd(fd)) != entry.signature
            or signature(stat_at(directory.fd, entry.name)) != entry.signature
        ):
            raise DeploymentSourceError()
        result = object.__new__(_FinalFile)
        result._directory = directory
        result.fd, result.name = fd, entry.name
        result._signature, result._cap, result._closed = (
            entry.signature,
            policy.payload_cap,
            False,
        )
        return result
    except (OSError, DeploymentSourceError):
        close_fd(fd)
        raise DeploymentSourceError() from None


def inspect_namespace(directory, cap):
    """Bounded final files and narrow legitimate stage states; never clean stages."""
    policy = _NamespacePolicy(20102, 20102, 21201, 16, 32, cap)
    scan = _scan_namespace(directory, policy=policy)
    finals = []
    for entry in scan.finals:
        opened = _open_final(directory, entry, policy=policy)
        try:
            finals.append((entry.name, opened.read_current()))
        finally:
            opened.close()
    return tuple(finals), scan.stages
