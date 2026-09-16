"""Fixed extension worker metadata source: local measurement, never authority
(Task 23; contracts/extension-worker-metadata.md, lineage values from Task 22).

The source retains the exact fixed hierarchy under the extension prefix —
seven directory descriptors and six leaf descriptors — and, on every read,
reopens the chain from the root, compares every named directory and leaf
against the retained identities/signatures, rereads all six files
completely, rehashes the worker executable against the declared
entrypoint, revalidates the identity and the four role-ordered schema
bytes, and rechecks the sampled process credentials, platform and mount
namespace before and after the reads. Any drift is an integrity failure
that poisons the source.

The result is an observation of actual local bytes and facts. It is not a
trusted capability, a successful installation, a qualification or proof of
a rebuild; identity input hashes remain declarations and the kernel
architecture does not prove unemulated execution.
"""

from __future__ import annotations

import os
import platform as _platform
import stat
import threading
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ..deployment import files as f
from ..deployment import mounts as m
from ..deployment.contracts import DeploymentSourceError, DeploymentSourceUnavailable
from ..extensions.lineage_contracts import (
    BuildIdentity,
    LineageContractError,
    parse_build_identity,
    validate_schema_bytes,
)
from ..extensions.port_contracts import PORT_SCHEMA_SHAPES
from .broker import ChannelConfigurationError, Deadline, DeadlineExceeded

EXTENSION_ROOT = Path("/")
EXTENSION_PREFIX = Path("/opt/deeptwin-extension")

_DIRECTORY_MODE = 0o755
_WORKER_MODE = 0o555
_LEAF_MODE = 0o444
_WORKER_CAP = 16_777_216
_IDENTITY_CAP = 8_192
_SCHEMA_CAP = 262_144
_TOTAL_CAP = 17_833_984
_CHUNK = 65_536
_ACQUIRE_MS = 1_000
_READ_BOUND_MS = 500
_MAX_ID = 4_294_967_295
_PLATFORMS = {"x86_64": "linux/amd64", "aarch64": "linux/arm64", "arm64": "linux/arm64"}
_LEAF_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class WorkerMetadataError(Exception):
    """Closed error family; every subclass carries one fixed code string."""

    code = "worker_metadata_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class WorkerMetadataUnavailable(WorkerMetadataError):
    code = "worker_metadata_unavailable"


class WorkerMetadataInvalid(WorkerMetadataError):
    code = "worker_metadata_invalid"


class WorkerMetadataUnsupportedPlatform(WorkerMetadataError):
    code = "worker_metadata_unsupported_platform"


class WorkerMetadataClosed(WorkerMetadataError):
    code = "worker_metadata_closed"


class WorkerMetadataBusy(WorkerMetadataError):
    code = "worker_metadata_busy"


class WorkerMetadataDeadline(WorkerMetadataError):
    code = "worker_metadata_deadline"


@dataclass(frozen=True, slots=True)
class WorkerMetadataReading:
    """Actual locally sampled values; not a capability or installation proof."""

    build_identity: BuildIdentity
    platform: str
    uid: int
    gid: int


# --- sampled facts (test-only monkeypatch points; no production test mode) ---


def _expected_owner() -> tuple[int, int]:
    return (0, 0)


def _native_platform() -> str:
    if _platform.system() != "Linux":
        raise WorkerMetadataUnsupportedPlatform()
    result = _PLATFORMS.get(_platform.machine())
    if result is None:
        raise WorkerMetadataUnsupportedPlatform()
    return result


def _credentials() -> tuple[int, int, int, int]:
    return (os.getuid(), os.geteuid(), os.getgid(), os.getegid())


def _read_mountinfo():
    return m.read_mountinfo()


# --- fixed layout ---


def _directories() -> tuple[Path, ...]:
    prefix = EXTENSION_PREFIX
    if prefix.parent.parent != EXTENSION_ROOT:
        raise WorkerMetadataInvalid()
    return (
        EXTENSION_ROOT,
        prefix.parent,
        prefix,
        prefix / "bin",
        prefix / "identity",
        prefix / "ports",
        prefix / "ports" / "tool-port-v1",
    )


def _leaves() -> tuple[tuple[Path, str, int, int], ...]:
    prefix = EXTENSION_PREFIX
    schemas = tuple(
        (
            prefix / "ports" / "tool-port-v1",
            f"{role}.schema.json",
            _LEAF_MODE,
            _SCHEMA_CAP,
        )
        for role in PORT_SCHEMA_SHAPES
    )
    return (
        (prefix / "bin", "worker", _WORKER_MODE, _WORKER_CAP),
        (prefix / "identity", "build-identity-v1.json", _LEAF_MODE, _IDENTITY_CAP),
        *schemas,
    )


@dataclass(frozen=True, slots=True)
class _Observation:
    platform: str
    uid: int
    gid: int
    directories: tuple[f.FileIdentity, ...]
    leaves: tuple[tuple, ...]
    identity_bytes: bytes
    schema_bytes: tuple[bytes, bytes, bytes, bytes]
    worker_digest: str
    worker_size: int
    mount_key: tuple


def _check(deadline: Deadline) -> None:
    deadline.require()


def _process() -> tuple[int, int]:
    values = _credentials()
    if type(values) is not tuple or len(values) != 4:
        raise WorkerMetadataInvalid()
    ruid, euid, rgid, egid = values
    for item in values:
        if type(item) is not int or not 1 <= item <= _MAX_ID:
            raise WorkerMetadataInvalid()
    if ruid != euid or rgid != egid:
        raise WorkerMetadataInvalid()
    return ruid, rgid


def _open_directory(
    path: Path, owner: tuple[int, int], transient: list[int]
) -> f.FileIdentity:
    before = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise WorkerMetadataInvalid()
    fd = f.open_directory(path)
    transient.append(fd)
    observed = f.validate_directory(
        fd, uid=owner[0], gid=owner[1], mode=_DIRECTORY_MODE
    )
    if (observed.device, observed.inode) != (before.st_dev, before.st_ino):
        raise WorkerMetadataInvalid()
    return observed


def _open_leaf(
    dir_fd: int,
    name: str,
    mode: int,
    cap: int,
    owner: tuple[int, int],
    transient: list[int],
) -> tuple:
    before = f.stat_at(dir_fd, name)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise WorkerMetadataInvalid()
    # opened directly so that an OSError here stays "unavailable" (contract §2)
    fd = os.open(name, _LEAF_FLAGS, dir_fd=dir_fd)
    transient.append(fd)
    info = f.stat_fd(fd)
    f.validate_regular(info, uid=owner[0], gid=owner[1], mode=mode, cap=cap)
    signature = f.signature(info)
    if signature != f.signature(f.stat_at(dir_fd, name)) or signature != f.signature(
        before
    ):
        raise WorkerMetadataInvalid()
    return signature


def _read_bounded(fd: int, cap: int, deadline: Deadline) -> bytes:
    """Read one complete bounded file with deadline checks around every chunk."""

    before = f.stat_fd(fd)
    if not 1 <= before.st_size <= cap:
        raise WorkerMetadataInvalid()
    os.lseek(fd, 0, os.SEEK_SET)
    result = bytearray()
    while len(result) <= cap:
        _check(deadline)
        part = os.read(fd, min(_CHUNK, cap + 1 - len(result)))
        _check(deadline)
        if not part:
            break
        result.extend(part)
    if len(result) != before.st_size or f.signature(before) != f.signature(
        f.stat_fd(fd)
    ):
        raise WorkerMetadataInvalid()
    return bytes(result)


def _hash_worker(fd: int, expected_size: int, deadline: Deadline) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = sha256()
    total = 0
    while total <= expected_size:
        _check(deadline)
        chunk = os.read(fd, min(_CHUNK, expected_size + 1 - total))
        _check(deadline)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    if total != expected_size:
        raise WorkerMetadataInvalid()
    return digest.hexdigest()


def _mount_key(
    directories: tuple[f.FileIdentity, ...],
    leaves: tuple[tuple, ...],
    paths: tuple[Path, ...],
) -> tuple:
    mounts = _read_mountinfo()
    root_mount = m.containing(mounts, EXTENSION_ROOT)
    if root_mount.mountpoint != EXTENSION_ROOT or not root_mount.read_only:
        raise WorkerMetadataInvalid()
    for path in paths:
        if m.containing(mounts, path) is not root_mount:
            # an intervening mount on the chain (e.g. at /opt)
            raise WorkerMetadataInvalid()
    for identity in (*directories, *(leaf[0] for leaf in leaves)):
        m.verify_device(root_mount, identity)
    prefix_backing = m.backing(root_mount, EXTENSION_PREFIX)
    for mount in mounts:
        if mount is root_mount:
            continue
        if mount.mountpoint.is_relative_to(EXTENSION_PREFIX):
            # NO mount at or below the prefix, on the named chain or off it
            raise WorkerMetadataInvalid()
        if mount.device == root_mount.device and (
            mount.root.is_relative_to(prefix_backing)
            or prefix_backing.is_relative_to(mount.root)
        ):
            # a visible same-device alias of the prefix's backing path
            raise WorkerMetadataInvalid()
    return (root_mount.device, str(root_mount.root), root_mount.read_only)


def _observe(
    deadline: Deadline,
    *,
    retained: WorkerMetadataSource | None,
    keep: list[int] | None,
) -> _Observation:
    transient: list[int] = []
    try:
        _check(deadline)
        platform_name = _native_platform()
        uid, gid = _process()
        owner = _expected_owner()
        directory_paths = _directories()
        leaf_specs = _leaves()
        directories = tuple(
            _open_directory(path, owner, transient) for path in directory_paths
        )
        directory_fds = tuple(transient)
        by_path = dict(zip(directory_paths, directory_fds, strict=True))
        leaves = []
        for directory, name, mode, cap in leaf_specs:
            leaves.append(
                _open_leaf(by_path[directory], name, mode, cap, owner, transient)
            )
        leaves = tuple(leaves)
        leaf_fds = tuple(transient[len(directory_fds) :])
        keys = {(d.device, d.inode) for d in directories} | {
            (leaf[0].device, leaf[0].inode) for leaf in leaves
        }
        if len(keys) != len(directories) + len(leaves):
            raise WorkerMetadataInvalid()
        leaf_paths = tuple(directory / name for directory, name, _, _ in leaf_specs)
        all_paths = (*directory_paths, *leaf_paths)
        mount_key = _mount_key(directories, leaves, all_paths)
        if retained is not None:
            _compare_retained(retained, owner)
        _check(deadline)
        worker_size = leaves[0][2]
        identity_bytes = _read_bounded(leaf_fds[1], _IDENTITY_CAP, deadline)
        schema_bytes = tuple(
            _read_bounded(fd, _SCHEMA_CAP, deadline) for fd in leaf_fds[2:]
        )
        if (
            worker_size + len(identity_bytes) + sum(len(raw) for raw in schema_bytes)
            > _TOTAL_CAP
        ):
            raise WorkerMetadataInvalid()
        identity = parse_build_identity(identity_bytes)
        declared = identity.as_dict()
        if declared["platform"] != platform_name:
            raise WorkerMetadataInvalid()
        entrypoint = declared["entrypoint"]
        if entrypoint["size_bytes"] != worker_size:
            raise WorkerMetadataInvalid()
        validate_schema_bytes(identity, schema_bytes)  # type: ignore[arg-type]
        worker_digest = _hash_worker(leaf_fds[0], worker_size, deadline)
        if worker_digest != entrypoint["sha256"]:
            raise WorkerMetadataInvalid()
        # final fence: names, held descriptors, mounts and sampled facts must
        # still agree with what was measured
        for path, baseline in zip(directory_paths, directories, strict=True):
            after = os.stat(path, follow_symlinks=False)
            if (after.st_dev, after.st_ino) != (baseline.device, baseline.inode):
                raise WorkerMetadataInvalid()
        for (directory, name, _, _), baseline, fd in zip(
            leaf_specs, leaves, leaf_fds, strict=True
        ):
            if f.signature(f.stat_at(by_path[directory], name)) != baseline:
                raise WorkerMetadataInvalid()
            if f.signature(f.stat_fd(fd)) != baseline:
                raise WorkerMetadataInvalid()
        if retained is not None:
            _compare_retained(retained, owner)
        if _mount_key(directories, leaves, all_paths) != mount_key:
            raise WorkerMetadataInvalid()
        if _native_platform() != platform_name or _process() != (uid, gid):
            raise WorkerMetadataInvalid()
        _check(deadline)
        observation = _Observation(
            platform=platform_name,
            uid=uid,
            gid=gid,
            directories=directories,
            leaves=leaves,
            identity_bytes=identity_bytes,
            schema_bytes=schema_bytes,  # type: ignore[arg-type]
            worker_digest=worker_digest,
            worker_size=worker_size,
            mount_key=mount_key,
        )
        if keep is not None:
            keep.extend(transient)
            transient.clear()
        return observation
    except WorkerMetadataError:
        raise
    except DeadlineExceeded:
        raise WorkerMetadataDeadline() from None
    except ChannelConfigurationError:
        raise WorkerMetadataInvalid() from None
    except DeploymentSourceUnavailable:
        raise WorkerMetadataUnavailable() from None
    except (
        DeploymentSourceError,
        LineageContractError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        UnicodeError,
        RecursionError,
        MemoryError,
    ):
        raise WorkerMetadataInvalid() from None
    except OSError:
        raise WorkerMetadataUnavailable() from None
    finally:
        for fd in transient:
            f.close_fd(fd)


def _compare_retained(retained: WorkerMetadataSource, owner: tuple[int, int]) -> None:
    """The retained descriptors must still show the acquisition baseline."""

    for fd, baseline in zip(
        retained._directory_fds, retained._baseline.directories, strict=True
    ):
        if (
            f.validate_directory(fd, uid=owner[0], gid=owner[1], mode=_DIRECTORY_MODE)
            != baseline
        ):
            raise WorkerMetadataInvalid()
    for fd, baseline in zip(retained._leaf_fds, retained._baseline.leaves, strict=True):
        if f.signature(f.stat_fd(fd)) != baseline:
            raise WorkerMetadataInvalid()


class WorkerMetadataSource(f.RetainedHandle):
    """Retains the fixed hierarchy; every read is a fresh complete measurement."""

    __slots__ = ("_baseline", "_closed", "_directory_fds", "_leaf_fds", "_lock")

    def __init__(self) -> None:
        raise TypeError("source construction requires open_worker_metadata_source")

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self):
        if self._closed:
            raise WorkerMetadataClosed()
        return self

    def __exit__(self, _kind, value, _traceback):
        try:
            self.close()
        except WorkerMetadataBusy:
            # never replace an exception that is already propagating
            if value is None:
                raise
        return False

    def read_current(self, *, deadline: Deadline) -> WorkerMetadataReading:
        if type(deadline) is not Deadline:
            raise WorkerMetadataInvalid()
        if not self._lock.acquire(blocking=False):
            raise WorkerMetadataBusy()
        try:
            if self._closed:
                raise WorkerMetadataClosed()
            try:
                observation = _observe(
                    deadline.bounded(_READ_BOUND_MS), retained=self, keep=None
                )
                if observation != self._baseline:
                    raise WorkerMetadataInvalid()
            except (WorkerMetadataDeadline, WorkerMetadataBusy):
                raise
            except BaseException:
                # integrity/unavailable failures and unexpected exceptions
                # both poison the source; the caller must restart it
                self._close_locked()
                raise
            return WorkerMetadataReading(
                build_identity=parse_build_identity(observation.identity_bytes),
                platform=observation.platform,
                uid=observation.uid,
                gid=observation.gid,
            )
        finally:
            self._lock.release()

    def close(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise WorkerMetadataBusy()
        try:
            self._close_locked()
        finally:
            self._lock.release()

    def _close_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fd in (*self._directory_fds, *self._leaf_fds):
            f.close_fd(
                fd
            )  # attempts every descriptor; one failure never stops the rest


def open_worker_metadata_source() -> WorkerMetadataSource:
    """Acquire the fixed hierarchy with a private one-second deadline."""

    _native_platform()  # unsupported hosts fail before any path access
    kept: list[int] = []
    observation = _observe(Deadline.after_ms(_ACQUIRE_MS), retained=None, keep=kept)
    try:
        source = object.__new__(WorkerMetadataSource)
        source._lock = threading.Lock()
        source._closed = False
        source._directory_fds = tuple(kept[:7])
        source._leaf_fds = tuple(kept[7:])
        source._baseline = observation
    except BaseException:
        # acquisition unwinds on every BaseException, including this tail
        for fd in kept:
            f.close_fd(fd)
        raise
    return source
