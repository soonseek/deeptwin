"""Root-owned generation boundary for one isolated-worker IPC pair.

The mounted pair root contains only root-owned generation metadata and one
responder-owned endpoint directory.  Requesters and responders hold a shared
lock while using a boot secret; the one-shot initializer takes the exclusive
lock before rotating it.  No container, process, or Compose lifecycle is
managed here.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
import re
import secrets
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from . import broker

PAIR_ROOT_MODE = 0o710
PAIR_METADATA_MODE = 0o640
ENDPOINT_MODE = 0o2710
BOOT_SECRET_NAME = "boot-secret"
GENERATION_LOCK_NAME = "generation.lock"
ENDPOINT_NAME = "endpoint"
LISTENER_NAME = "listener.json"
LISTENER_LOCK_NAME = "listener.lock"
METADATA_UID = 0
_MAX_PATH_BYTES = 4_096
_GENERATION_DOMAIN = b"deeptwin-worker-generation-v1\x00"
_SECRET_STAGE = re.compile(r"\.boot-secret\.[0-9a-f]{32}\.tmp\Z")


class IpcRootError(RuntimeError):
    """Sanitized IPC-root failure without a filesystem path or secret."""

    code = "ipc_root_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class IpcRootIntegrityError(IpcRootError):
    code = "ipc_root_integrity_invalid"


class IpcRootBusy(IpcRootError):
    code = "ipc_generation_busy"


@dataclass(frozen=True, slots=True)
class PairRootSpec:
    pair_root: Path
    responder_uid: int
    responder_gid: int
    pair_gid: int

    def __post_init__(self) -> None:
        root_bytes: bytes | None = None
        try:
            root_bytes = os.fsencode(self.pair_root)
        except (TypeError, UnicodeError):
            pass
        if (
            not isinstance(self.pair_root, Path)
            or root_bytes is None
            or not self.pair_root.is_absolute()
            or self.pair_root == Path(os.sep)
            or self.pair_root.anchor != os.sep
            or ".." in self.pair_root.parts
            or not 1 <= len(root_bytes) <= _MAX_PATH_BYTES
        ):
            raise IpcRootIntegrityError()
        values = (self.responder_uid, self.responder_gid, self.pair_gid)
        if (
            any(
                type(value) is not int or not 1 <= value < (1 << 32) for value in values
            )
            or self.responder_gid == self.pair_gid
        ):
            raise IpcRootIntegrityError()

    @property
    def boot_secret_path(self) -> Path:
        return self.pair_root / BOOT_SECRET_NAME

    @property
    def generation_lock_path(self) -> Path:
        return self.pair_root / GENERATION_LOCK_NAME

    @property
    def endpoint_path(self) -> Path:
        return self.pair_root / ENDPOINT_NAME

    @property
    def listener_path(self) -> Path:
        return self.endpoint_path / LISTENER_NAME

    @property
    def listener_lock_path(self) -> Path:
        return self.endpoint_path / LISTENER_LOCK_NAME

    def socket_path(self, socket_name: str) -> Path:
        if (
            type(socket_name) is not str
            or not socket_name
            or Path(socket_name).name != socket_name
            or "/" in socket_name
        ):
            raise IpcRootIntegrityError()
        return self.endpoint_path / socket_name


@dataclass(frozen=True, slots=True)
class InitializedGeneration:
    generation_id: str
    pair_identity: broker.EndpointIdentity
    endpoint_identity: broker.EndpointIdentity


class GenerationLease:
    """A held shared generation lock and its exact verified boot secret."""

    __slots__ = (
        "_closed",
        "_endpoint_fd",
        "_lock_fd",
        "_pair_fd",
        "endpoint_identity",
        "generation_id",
        "pair_identity",
        "secret",
    )

    def __init__(
        self,
        *,
        generation_id: str,
        secret: broker.BootSecret,
        pair_identity: broker.EndpointIdentity,
        endpoint_identity: broker.EndpointIdentity,
        pair_fd: int,
        endpoint_fd: int,
        lock_fd: int,
    ) -> None:
        self.generation_id = generation_id
        self.secret = secret
        self.pair_identity = pair_identity
        self.endpoint_identity = endpoint_identity
        self._pair_fd = pair_fd
        self._endpoint_fd = endpoint_fd
        self._lock_fd = lock_fd
        self._closed = False

    @property
    def pair_fd(self) -> int:
        if self._closed:
            raise IpcRootIntegrityError()
        return self._pair_fd

    @property
    def endpoint_fd(self) -> int:
        if self._closed:
            raise IpcRootIntegrityError()
        return self._endpoint_fd

    @property
    def lock_fd(self) -> int:
        if self._closed:
            raise IpcRootIntegrityError()
        return self._lock_fd

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        endpoint_fd, lock_fd, pair_fd = self._endpoint_fd, self._lock_fd, self._pair_fd
        self._endpoint_fd = self._lock_fd = self._pair_fd = -1
        first_error = None
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        except BaseException as error:
            first_error = error
        for descriptor in (endpoint_fd, lock_fd, pair_fd):
            try:
                _close_fd(descriptor)
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def __enter__(self) -> Self:
        if self._closed:
            raise IpcRootIntegrityError()
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<GenerationLease generation_id={self.generation_id!r} secret=redacted>"

    def __copy__(self) -> object:
        raise TypeError("GenerationLease is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("GenerationLease is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("GenerationLease is not serializable")


def _close_fd(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _identity(info: os.stat_result) -> broker.EndpointIdentity:
    return broker.EndpointIdentity(
        device=info.st_dev,
        inode=info.st_ino,
        uid=info.st_uid,
        gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode),
    )


def _directory_flags(*, searchable_only: bool) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise IpcRootIntegrityError()
    access = getattr(os, "O_PATH", os.O_RDONLY) if searchable_only else os.O_RDONLY
    return access | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_absolute_directory(path: Path, *, searchable_only: bool) -> int:
    flags = _directory_flags(searchable_only=searchable_only)
    descriptor = -1
    try:
        descriptor = os.open(os.sep, flags)
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            previous = descriptor
            descriptor = child
            _close_fd(previous)
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise IpcRootIntegrityError()
        return descriptor
    except BaseException as error:
        owned, descriptor = descriptor, -1
        try:
            _close_fd(owned)
        except BaseException:  # noqa: BLE001, S110 - preserve the acquisition primary
            pass
        if isinstance(error, OSError):
            raise IpcRootIntegrityError() from None
        raise


def _validate_directory(
    descriptor: int,
    *,
    uid: int,
    gid: int,
    mode: int,
) -> broker.EndpointIdentity:
    try:
        info = os.fstat(descriptor)
    except OSError:
        raise IpcRootIntegrityError() from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != uid
        or info.st_gid != gid
        or stat.S_IMODE(info.st_mode) != mode
    ):
        raise IpcRootIntegrityError()
    return _identity(info)


def _open_regular_at(
    directory_fd: int,
    name: str,
    *,
    uid: int,
    gid: int,
    mode: int,
    writable: bool,
    exact_size: int | None,
) -> int:
    flags = (os.O_RDWR if writable else os.O_RDONLY) | os.O_CLOEXEC | os.O_NONBLOCK
    if not hasattr(os, "O_NOFOLLOW"):
        raise IpcRootIntegrityError()
    flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != uid
            or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != mode
            or (exact_size is not None and info.st_size != exact_size)
        ):
            raise IpcRootIntegrityError()
        return descriptor
    except BaseException as error:
        owned, descriptor = descriptor, -1
        try:
            _close_fd(owned)
        except BaseException:  # noqa: BLE001, S110 - preserve the acquisition primary
            pass
        if isinstance(error, OSError):
            raise IpcRootIntegrityError() from None
        raise


def _read_exact_secret(descriptor: int) -> bytes:
    try:
        before = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        value = os.read(descriptor, broker.AUTH_SECRET_BYTES + 1)
        after = os.fstat(descriptor)
    except OSError:
        raise IpcRootIntegrityError() from None
    if len(value) != broker.AUTH_SECRET_BYTES or (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        # the partial or drifted bytes must not stay reachable through the
        # traceback frame of the sanitized error
        value = None
        raise IpcRootIntegrityError()
    return value


def _generation_id(secret: bytes) -> str:
    return hmac.new(secret, _GENERATION_DOMAIN, hashlib.sha256).hexdigest()


def _create_regular(
    directory_fd: int,
    name: str,
    *,
    uid: int,
    gid: int,
    mode: int,
) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if not hasattr(os, "O_NOFOLLOW"):
        raise IpcRootIntegrityError()
    flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        return descriptor
    except OSError:
        _close_fd(descriptor)
        raise IpcRootIntegrityError() from None


def _write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    try:
        while offset < len(value):
            written = os.write(descriptor, value[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
    except OSError:
        raise IpcRootIntegrityError() from None


def _classify_entries(entries: set[str]) -> tuple[bool, str | None]:
    base = {GENERATION_LOCK_NAME, ENDPOINT_NAME}
    if not base <= entries:
        raise IpcRootIntegrityError()
    has_secret = BOOT_SECRET_NAME in entries
    extras = entries - base - ({BOOT_SECRET_NAME} if has_secret else set())
    if len(extras) > 1:
        raise IpcRootIntegrityError()
    stage_name = next(iter(extras), None)
    if stage_name is not None and _SECRET_STAGE.fullmatch(stage_name) is None:
        raise IpcRootIntegrityError()
    return has_secret, stage_name


def _remove_exact_secret_stage(
    pair_fd: int,
    spec: PairRootSpec,
    name: str,
    *,
    expected: broker.EndpointIdentity | None = None,
) -> None:
    if _SECRET_STAGE.fullmatch(name) is None:
        raise IpcRootIntegrityError()
    descriptor = _open_regular_at(
        pair_fd,
        name,
        uid=METADATA_UID,
        gid=spec.pair_gid,
        mode=PAIR_METADATA_MODE,
        writable=False,
        exact_size=None,
    )
    try:
        before = os.fstat(descriptor)
        identity = _identity(before)
        if before.st_size > broker.AUTH_SECRET_BYTES or (
            expected is not None and identity != expected
        ):
            raise IpcRootIntegrityError()
        named = os.stat(name, dir_fd=pair_fd, follow_symlinks=False)
        if (
            _identity(named) != identity
            or named.st_nlink != 1
            or named.st_size != before.st_size
        ):
            raise IpcRootIntegrityError()
        os.unlink(name, dir_fd=pair_fd)
        after = os.fstat(descriptor)
        if _identity(after) != identity or after.st_nlink != 0:
            raise IpcRootIntegrityError()
        os.fsync(pair_fd)
    except IpcRootError:
        raise
    except OSError:
        raise IpcRootIntegrityError() from None
    finally:
        _close_fd(descriptor)


def _establish_empty_root(spec: PairRootSpec, pair_fd: int) -> None:
    try:
        if os.listdir(pair_fd):
            raise IpcRootIntegrityError()
        os.fchown(pair_fd, METADATA_UID, spec.pair_gid)
        os.fchmod(pair_fd, PAIR_ROOT_MODE)
        lock_fd = _create_regular(
            pair_fd,
            GENERATION_LOCK_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
        )
        _close_fd(lock_fd)
        os.mkdir(ENDPOINT_NAME, 0o700, dir_fd=pair_fd)
        endpoint_fd = os.open(
            ENDPOINT_NAME,
            _directory_flags(searchable_only=False),
            dir_fd=pair_fd,
        )
        try:
            os.fchown(endpoint_fd, spec.responder_uid, spec.pair_gid)
            os.fchmod(endpoint_fd, ENDPOINT_MODE)
            os.fsync(endpoint_fd)
        finally:
            _close_fd(endpoint_fd)
        os.fsync(pair_fd)
    except IpcRootError:
        raise
    except OSError:
        raise IpcRootIntegrityError() from None


def _validate_layout(
    spec: PairRootSpec,
    pair_fd: int,
    *,
    secret_required: bool,
) -> tuple[broker.EndpointIdentity, broker.EndpointIdentity]:
    pair_identity = _validate_directory(
        pair_fd,
        uid=METADATA_UID,
        gid=spec.pair_gid,
        mode=PAIR_ROOT_MODE,
    )
    try:
        endpoint_fd = os.open(
            ENDPOINT_NAME,
            _directory_flags(searchable_only=True),
            dir_fd=pair_fd,
        )
    except OSError:
        raise IpcRootIntegrityError() from None
    try:
        endpoint_identity = _validate_directory(
            endpoint_fd,
            uid=spec.responder_uid,
            gid=spec.pair_gid,
            mode=ENDPOINT_MODE,
        )
    except BaseException:
        try:
            _close_fd(endpoint_fd)
        except BaseException:  # noqa: BLE001, S110 - preserve endpoint validation
            pass
        raise
    else:
        _close_fd(endpoint_fd)
    lock_fd = _open_regular_at(
        pair_fd,
        GENERATION_LOCK_NAME,
        uid=METADATA_UID,
        gid=spec.pair_gid,
        mode=PAIR_METADATA_MODE,
        writable=False,
        exact_size=0,
    )
    _close_fd(lock_fd)
    if secret_required:
        secret_fd = _open_regular_at(
            pair_fd,
            BOOT_SECRET_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
            writable=False,
            exact_size=broker.AUTH_SECRET_BYTES,
        )
        _close_fd(secret_fd)
    return pair_identity, endpoint_identity


def initialize_pair_root(
    spec: PairRootSpec,
    *,
    entropy: Callable[[int], bytes] = secrets.token_bytes,
) -> InitializedGeneration:
    """Initialize an empty mounted pair root or rotate one valid idle generation."""

    if type(spec) is not PairRootSpec or not callable(entropy):
        raise IpcRootIntegrityError()
    if os.geteuid() != METADATA_UID:
        raise IpcRootIntegrityError()
    pair_fd = _open_absolute_directory(spec.pair_root, searchable_only=False)
    lock_fd = -1
    stage_name: str | None = None
    stage_identity: broker.EndpointIdentity | None = None
    try:
        try:
            entries = set(os.listdir(pair_fd))
        except OSError:
            raise IpcRootIntegrityError() from None
        empty = not entries
        if empty:
            _establish_empty_root(spec, pair_fd)
            entries = {GENERATION_LOCK_NAME, ENDPOINT_NAME}
        has_secret, _unverified_stage = _classify_entries(entries)
        _validate_layout(spec, pair_fd, secret_required=has_secret)
        lock_fd = _open_regular_at(
            pair_fd,
            GENERATION_LOCK_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
            writable=True,
            exact_size=0,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IpcRootBusy() from None
        except OSError:
            raise IpcRootIntegrityError() from None
        try:
            locked_entries = set(os.listdir(pair_fd))
        except OSError:
            raise IpcRootIntegrityError() from None
        has_secret, abandoned_stage = _classify_entries(locked_entries)
        _validate_layout(spec, pair_fd, secret_required=has_secret)
        if abandoned_stage is not None:
            _remove_exact_secret_stage(pair_fd, spec, abandoned_stage)
        bootstrap = not has_secret
        _validate_layout(spec, pair_fd, secret_required=has_secret)
        previous: bytes | None = None
        if not bootstrap:
            previous_fd = _open_regular_at(
                pair_fd,
                BOOT_SECRET_NAME,
                uid=METADATA_UID,
                gid=spec.pair_gid,
                mode=PAIR_METADATA_MODE,
                writable=False,
                exact_size=broker.AUTH_SECRET_BYTES,
            )
            try:
                previous = _read_exact_secret(previous_fd)
            finally:
                _close_fd(previous_fd)
        candidate: bytes | None = None
        try:
            candidate = entropy(broker.AUTH_SECRET_BYTES)
        except Exception:  # noqa: BLE001 - sanitize an injected RNG failure.
            previous = None
            candidate = None
            raise IpcRootIntegrityError() from None
        candidate_rejected = (
            type(candidate) is not bytes
            or len(candidate) != broker.AUTH_SECRET_BYTES
            or (previous is not None and hmac.compare_digest(candidate, previous))
        )
        if candidate_rejected:
            previous = None
            candidate = None
            raise IpcRootIntegrityError()
        candidate_stage = f".boot-secret.{secrets.token_hex(16)}.tmp"
        stage_fd = _create_regular(
            pair_fd,
            candidate_stage,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
        )
        stage_name = candidate_stage
        try:
            _write_all(stage_fd, candidate)
            os.fsync(stage_fd)
            info = os.fstat(stage_fd)
            if info.st_size != broker.AUTH_SECRET_BYTES:
                raise IpcRootIntegrityError()
            stage_identity = _identity(info)
        finally:
            _close_fd(stage_fd)
        os.replace(
            stage_name,
            BOOT_SECRET_NAME,
            src_dir_fd=pair_fd,
            dst_dir_fd=pair_fd,
        )
        stage_name = None
        os.fsync(pair_fd)
        pair_identity, endpoint_identity = _validate_layout(
            spec,
            pair_fd,
            secret_required=True,
        )
        installed_fd = _open_regular_at(
            pair_fd,
            BOOT_SECRET_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
            writable=False,
            exact_size=broker.AUTH_SECRET_BYTES,
        )
        try:
            if not hmac.compare_digest(_read_exact_secret(installed_fd), candidate):
                raise IpcRootIntegrityError()
        finally:
            _close_fd(installed_fd)
        return InitializedGeneration(
            generation_id=_generation_id(candidate),
            pair_identity=pair_identity,
            endpoint_identity=endpoint_identity,
        )
    except IpcRootError:
        raise
    except OSError:
        raise IpcRootIntegrityError() from None
    finally:
        if stage_name is not None:
            try:
                _remove_exact_secret_stage(
                    pair_fd,
                    spec,
                    stage_name,
                    expected=stage_identity,
                )
            except IpcRootError:
                pass
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        _close_fd(lock_fd)
        _close_fd(pair_fd)


def acquire_generation(spec: PairRootSpec) -> GenerationLease:
    """Hold a shared lock over one fully verified secret/endpoint generation."""

    if type(spec) is not PairRootSpec:
        raise IpcRootIntegrityError()
    pair_fd = _open_absolute_directory(spec.pair_root, searchable_only=True)
    lock_fd = -1
    endpoint_fd = -1
    secret_fd = -1
    try:
        pair_identity, endpoint_identity = _validate_layout(
            spec,
            pair_fd,
            secret_required=True,
        )
        lock_fd = _open_regular_at(
            pair_fd,
            GENERATION_LOCK_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
            writable=False,
            exact_size=0,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IpcRootBusy() from None
        except OSError:
            raise IpcRootIntegrityError() from None
        current_pair, current_endpoint = _validate_layout(
            spec,
            pair_fd,
            secret_required=True,
        )
        if current_pair != pair_identity or current_endpoint != endpoint_identity:
            raise IpcRootIntegrityError()
        secret_fd = _open_regular_at(
            pair_fd,
            BOOT_SECRET_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
            writable=False,
            exact_size=broker.AUTH_SECRET_BYTES,
        )
        secret_bytes = _read_exact_secret(secret_fd)
        owned, secret_fd = secret_fd, -1
        _close_fd(owned)
        endpoint_fd = os.open(
            ENDPOINT_NAME,
            _directory_flags(searchable_only=True),
            dir_fd=pair_fd,
        )
        if (
            _validate_directory(
                endpoint_fd,
                uid=spec.responder_uid,
                gid=spec.pair_gid,
                mode=ENDPOINT_MODE,
            )
            != endpoint_identity
        ):
            raise IpcRootIntegrityError()
        lease = GenerationLease(
            generation_id=_generation_id(secret_bytes),
            secret=broker.BootSecret(secret_bytes),
            pair_identity=pair_identity,
            endpoint_identity=endpoint_identity,
            pair_fd=pair_fd,
            endpoint_fd=endpoint_fd,
            lock_fd=lock_fd,
        )
        pair_fd = lock_fd = endpoint_fd = -1
        return lease
    except BaseException as error:
        owned = (secret_fd, endpoint_fd, lock_fd, pair_fd)
        secret_fd = endpoint_fd = lock_fd = pair_fd = -1
        for descriptor in owned:
            try:
                _close_fd(descriptor)
            except BaseException:  # noqa: BLE001, S110 - attempt all; preserve primary
                pass
        if isinstance(error, OSError):
            raise IpcRootIntegrityError() from None
        raise


def _metadata_stat(info: os.stat_result) -> tuple:
    return (
        _identity(info),
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


class MetadataGenerationLease:
    """Shared rotation exclusion and current metadata; never boot-secret contents."""

    __slots__ = (
        "_closed",
        "_endpoint_fd",
        "_lock_fd",
        "_lock_stat",
        "_pair_fd",
        "_secret_fd",
        "_secret_stat",
        "_spec",
        "endpoint_identity",
        "pair_identity",
    )

    def __init__(self):
        raise TypeError("metadata lease construction requires a held generation lock")

    def recheck_current(self) -> None:
        if self._closed:
            raise IpcRootIntegrityError()
        current_fd = -1
        try:
            current_fd = _open_absolute_directory(
                self._spec.pair_root, searchable_only=True
            )
            for descriptor in (current_fd, self._pair_fd):
                if (
                    _validate_directory(
                        descriptor,
                        uid=METADATA_UID,
                        gid=self._spec.pair_gid,
                        mode=PAIR_ROOT_MODE,
                    )
                    != self.pair_identity
                ):
                    raise IpcRootIntegrityError()
            endpoint = os.stat(ENDPOINT_NAME, dir_fd=current_fd, follow_symlinks=False)
            if (
                _identity(endpoint) != self.endpoint_identity
                or not stat.S_ISDIR(endpoint.st_mode)
                or _validate_directory(
                    self._endpoint_fd,
                    uid=self._spec.responder_uid,
                    gid=self._spec.pair_gid,
                    mode=ENDPOINT_MODE,
                )
                != self.endpoint_identity
            ):
                raise IpcRootIntegrityError()
            for name, descriptor, expected in (
                (GENERATION_LOCK_NAME, self._lock_fd, self._lock_stat),
                (BOOT_SECRET_NAME, self._secret_fd, self._secret_stat),
            ):
                named = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
                held = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(named.st_mode)
                    or _metadata_stat(named) != expected
                    or _metadata_stat(held) != expected
                ):
                    raise IpcRootIntegrityError()
            for name in ("worker.sock", LISTENER_NAME):
                try:
                    os.stat(name, dir_fd=self._endpoint_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise IpcRootIntegrityError()
        except BaseException as error:
            owned, current_fd = current_fd, -1
            try:
                _close_fd(owned)
            except BaseException:  # noqa: BLE001, S110 - preserve recheck primary
                pass
            if isinstance(error, OSError):
                raise IpcRootIntegrityError() from None
            raise
        else:
            _close_fd(current_fd)

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error = None
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        except BaseException as error:  # noqa: BLE001 - defer until all closes attempted
            first_error = error
        for name in ("_secret_fd", "_endpoint_fd", "_lock_fd", "_pair_fd"):
            descriptor = getattr(self, name)
            setattr(self, name, -1)
            try:
                _close_fd(descriptor)
            except BaseException as error:  # noqa: BLE001 - attempt remaining closes
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def __enter__(self) -> Self:
        try:
            self.recheck_current()
        except IpcRootError:
            self.close()
            raise
        return self

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.close()

    def __copy__(self):
        raise TypeError("MetadataGenerationLease is not copyable")

    def __deepcopy__(self, _memo):
        raise TypeError("MetadataGenerationLease is not copyable")

    def __reduce__(self):
        raise TypeError("MetadataGenerationLease is not serializable")


def acquire_generation_metadata(spec: PairRootSpec) -> MetadataGenerationLease:
    """Retain actual generation metadata under a nonblocking shared lock."""
    if type(spec) is not PairRootSpec:
        raise IpcRootIntegrityError()
    pair_fd = endpoint_fd = lock_fd = secret_fd = -1
    lease = None
    transferred = False
    try:
        pair_fd = _open_absolute_directory(spec.pair_root, searchable_only=True)
        pair_identity, endpoint_identity = _validate_layout(
            spec, pair_fd, secret_required=True
        )
        lock_fd = _open_regular_at(
            pair_fd,
            GENERATION_LOCK_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
            writable=False,
            exact_size=0,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IpcRootBusy() from None
        secret_fd = _open_regular_at(
            pair_fd,
            BOOT_SECRET_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
            writable=False,
            exact_size=broker.AUTH_SECRET_BYTES,
        )
        endpoint_fd = os.open(
            ENDPOINT_NAME, _directory_flags(searchable_only=True), dir_fd=pair_fd
        )
        lock_stat = _metadata_stat(os.fstat(lock_fd))
        secret_stat = _metadata_stat(os.fstat(secret_fd))
        lease = object.__new__(MetadataGenerationLease)
        lease._spec = spec
        lease.pair_identity, lease.endpoint_identity = pair_identity, endpoint_identity
        lease._pair_fd, lease._endpoint_fd = pair_fd, endpoint_fd
        lease._lock_fd, lease._secret_fd = lock_fd, secret_fd
        lease._lock_stat = lock_stat
        lease._secret_stat = secret_stat
        lease._closed = False
        pair_fd = endpoint_fd = lock_fd = secret_fd = -1
        transferred = True
        lease.recheck_current()
        return lease
    except BaseException as error:
        if transferred:
            try:
                lease.close()
            except BaseException:  # noqa: BLE001, S110 - preserve initial recheck primary
                pass
        else:
            owned = (secret_fd, endpoint_fd, lock_fd, pair_fd)
            secret_fd = endpoint_fd = lock_fd = pair_fd = -1
            for descriptor in owned:
                try:
                    _close_fd(descriptor)
                except BaseException:  # noqa: BLE001, S110 - attempt all; preserve primary
                    pass
        if isinstance(error, OSError):
            raise IpcRootIntegrityError() from None
        raise


class PopulatedGenerationFence:
    """A borrowed held generation plus one owned boot-secret descriptor and
    the leaf root and metadata observations, rechecked against the named
    files on every fence (extension-worker-probe.md §6; proposal §3). Every
    path component is opened no-follow, so an ancestor swapped for a symlink
    is refused; a rename or bind that resolves to the same device and inode
    is harmless by construction.

    Unlike the absence-only `MetadataGenerationLease`, this fence permits a
    populated endpoint (`worker.sock`, `listener.json` present): it exists for
    the probe that runs while the worker listener is live. It never exposes
    secret bytes; the reread is compared in constant time to the generation's
    own secret and discarded. Closing the fence releases only what it owns.
    """

    __slots__ = (
        "_closed",
        "_generation",
        "_lock_stat",
        "_secret_fd",
        "_secret_stat",
        "_spec",
    )

    def __init__(self):
        raise TypeError("a populated fence is retained from a held generation")

    def recheck_current(self) -> None:
        if self._closed or self._generation.closed:
            raise IpcRootIntegrityError()
        spec, generation = self._spec, self._generation
        current_fd = -1
        try:
            current_fd = _open_absolute_directory(spec.pair_root, searchable_only=True)
            for descriptor in (current_fd, generation.pair_fd):
                if (
                    _validate_directory(
                        descriptor,
                        uid=METADATA_UID,
                        gid=spec.pair_gid,
                        mode=PAIR_ROOT_MODE,
                    )
                    != generation.pair_identity
                ):
                    raise IpcRootIntegrityError()
            endpoint = os.stat(ENDPOINT_NAME, dir_fd=current_fd, follow_symlinks=False)
            if (
                _identity(endpoint) != generation.endpoint_identity
                or not stat.S_ISDIR(endpoint.st_mode)
                or _validate_directory(
                    generation.endpoint_fd,
                    uid=spec.responder_uid,
                    gid=spec.pair_gid,
                    mode=ENDPOINT_MODE,
                )
                != generation.endpoint_identity
            ):
                raise IpcRootIntegrityError()
            for name, descriptor, expected in (
                (GENERATION_LOCK_NAME, generation.lock_fd, self._lock_stat),
                (BOOT_SECRET_NAME, self._secret_fd, self._secret_stat),
            ):
                named = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
                held = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(named.st_mode)
                    or _metadata_stat(named) != expected
                    or _metadata_stat(held) != expected
                ):
                    raise IpcRootIntegrityError()
            reread = _read_exact_secret(self._secret_fd)
            same = hmac.compare_digest(reread, generation.secret._material())
            del reread
            if not same:
                raise IpcRootIntegrityError()
        except BaseException as error:
            owned, current_fd = current_fd, -1
            try:
                _close_fd(owned)
            except BaseException:  # noqa: BLE001, S110 - preserve recheck primary
                pass
            if isinstance(error, OSError):
                raise IpcRootIntegrityError() from None
            raise
        owned, current_fd = current_fd, -1
        _close_fd(owned)

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_fd(self._secret_fd)

    def __enter__(self) -> Self:
        try:
            self.recheck_current()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"PopulatedGenerationFence(closed={self._closed!r})"

    def __copy__(self):
        raise TypeError("a populated fence cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("a populated fence cannot be copied")

    def __reduce__(self):
        raise TypeError("a populated fence cannot be serialized")


def _retain_populated_generation(
    spec: PairRootSpec, generation: GenerationLease
) -> PopulatedGenerationFence:
    """Borrow a held generation and own one more no-follow boot-secret
    descriptor plus the leaf root and metadata observations; the original
    shared lock stays held by the generation (borrowers close nothing)."""

    if type(spec) is not PairRootSpec or type(generation) is not GenerationLease:
        raise IpcRootIntegrityError()
    if generation.closed:
        raise IpcRootIntegrityError()
    secret_fd = -1
    fence = None
    try:
        secret_fd = _open_regular_at(
            generation.pair_fd,
            BOOT_SECRET_NAME,
            uid=METADATA_UID,
            gid=spec.pair_gid,
            mode=PAIR_METADATA_MODE,
            writable=False,
            exact_size=broker.AUTH_SECRET_BYTES,
        )
        # every observation that can fail happens before the fence exists, so
        # a half-built fence never reaches close()
        secret_stat = _metadata_stat(os.fstat(secret_fd))
        lock_stat = _metadata_stat(os.fstat(generation.lock_fd))
        fence = object.__new__(PopulatedGenerationFence)
        # ownership of the descriptor moves in one step: close() is valid
        # from here on, and the local no longer refers to the descriptor
        fence._closed, fence._secret_fd, secret_fd = False, secret_fd, -1
        fence._spec = spec
        fence._generation = generation
        fence._secret_stat = secret_stat
        fence._lock_stat = lock_stat
        fence.recheck_current()
        return fence
    except BaseException as error:
        # every acquisition path unwinds, whatever interrupted it
        owned_fence, fence = fence, None
        owned_fd, secret_fd = secret_fd, -1
        try:
            if owned_fence is not None:
                owned_fence.close()
            else:
                _close_fd(owned_fd)
        except BaseException:  # noqa: BLE001, S110 - preserve acquisition primary
            pass
        if isinstance(error, IpcRootError) or not isinstance(error, OSError):
            raise
        raise IpcRootIntegrityError() from None
