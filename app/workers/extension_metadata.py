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


# Code-owned private error adapter for the shared observer.
_MetadataError = WorkerMetadataError
_MetadataInvalid = WorkerMetadataInvalid
_MetadataUnavailable = WorkerMetadataUnavailable
_MetadataDeadline = WorkerMetadataDeadline

# Low-level traversal is shared; public source/error and sampling APIs stay local.
from ._fixed_image_metadata import _observe_tool as _observe


def _read_bounded(fd, cap, deadline):
    # Preserve the existing tool observer's finite-read sampling seam.
    import sys
    from ._fixed_image_metadata import _read_bounded as read
    return read(sys.modules[__name__], fd, cap, deadline)


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
