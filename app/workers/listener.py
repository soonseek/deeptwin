"""Authenticated Unix listener lifecycle for one verified worker channel.

The listener owns only its responder-writable endpoint directory.  Root-owned
boot material remains in the parent pair root, protected by a generation lock.
Readiness is an exact HMAC-authenticated manifest; it is never authority to
skip the broker's Linux peer-credential and mutual-handshake checks.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import stat
import sys
from dataclasses import dataclass
from typing import Self

from . import broker, ipc_root

LISTENER_SCHEMA_VERSION = "deeptwin-worker-listener-v1"
LISTENER_FILE_MODE = 0o640
LISTENER_LOCK_MODE = 0o600
MAX_LISTENER_BYTES = 8_192
_LISTENER_MAC_DOMAIN = b"deeptwin-worker-listener-v1\x00"
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class ListenerError(RuntimeError):
    """Sanitized listener failure without paths, secret bytes, or manifest data."""

    code = "worker_listener_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class ListenerIntegrityError(ListenerError):
    code = "worker_listener_integrity_invalid"


class ListenerIdentityError(ListenerError):
    code = "worker_listener_identity_invalid"


class ListenerBusy(ListenerError):
    code = "worker_listener_busy"


class ListenerPlatformError(ListenerError):
    code = "worker_listener_platform_unsupported"


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    uid: int
    gid: int
    mode: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.device,
                self.inode,
                self.uid,
                self.gid,
                self.mode,
            )
        ):
            raise ListenerIntegrityError()

    @classmethod
    def from_stat(cls, info: os.stat_result) -> FileIdentity:
        return cls(
            device=info.st_dev,
            inode=info.st_ino,
            uid=info.st_uid,
            gid=info.st_gid,
            mode=stat.S_IMODE(info.st_mode),
        )

    @classmethod
    def from_mapping(cls, value: object) -> FileIdentity:
        if type(value) is not dict or set(value) != {
            "device",
            "inode",
            "uid",
            "gid",
            "mode",
        }:
            raise ListenerIntegrityError()
        try:
            return cls(**value)
        except TypeError:
            raise ListenerIntegrityError() from None

    def as_dict(self) -> dict[str, int]:
        return {
            "device": self.device,
            "inode": self.inode,
            "uid": self.uid,
            "gid": self.gid,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class SocketIdentity:
    name: str
    device: int
    inode: int
    uid: int
    gid: int
    mode: int

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or not self.name
            or os.path.basename(self.name) != self.name
            or "/" in self.name
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.device,
                    self.inode,
                    self.uid,
                    self.gid,
                    self.mode,
                )
            )
        ):
            raise ListenerIntegrityError()

    @classmethod
    def from_stat(cls, name: str, info: os.stat_result) -> SocketIdentity:
        return cls(
            name=name,
            device=info.st_dev,
            inode=info.st_ino,
            uid=info.st_uid,
            gid=info.st_gid,
            mode=stat.S_IMODE(info.st_mode),
        )

    @classmethod
    def from_mapping(cls, value: object) -> SocketIdentity:
        if type(value) is not dict or set(value) != {
            "name",
            "device",
            "inode",
            "uid",
            "gid",
            "mode",
        }:
            raise ListenerIntegrityError()
        try:
            return cls(**value)
        except TypeError:
            raise ListenerIntegrityError() from None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "device": self.device,
            "inode": self.inode,
            "uid": self.uid,
            "gid": self.gid,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class ListenerRecord:
    schema_version: str
    protocol_version: str
    channel_spec_sha256: str
    generation_id: str
    responder_boot_id: str
    endpoint: FileIdentity
    socket: SocketIdentity
    hmac_sha256: str

    def unsigned(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "channel_spec_sha256": self.channel_spec_sha256,
            "generation_id": self.generation_id,
            "responder_boot_id": self.responder_boot_id,
            "endpoint": self.endpoint.as_dict(),
            "socket": self.socket.as_dict(),
        }

    def as_dict(self) -> dict[str, object]:
        return {**self.unsigned(), "hmac_sha256": self.hmac_sha256}


class VerifiedListener:
    __slots__ = ("_closed", "generation", "record")

    def __init__(
        self,
        *,
        generation: ipc_root.GenerationLease,
        record: ListenerRecord,
    ) -> None:
        self.generation = generation
        self.record = record
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.generation.close()

    def __enter__(self) -> Self:
        if self._closed:
            raise ListenerIntegrityError()
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()


class AuthenticatedConnection:
    __slots__ = ("_closed", "_codec", "_generation", "_socket", "session")

    def __init__(
        self,
        *,
        connection: socket.socket,
        session: broker.AuthenticatedSession,
        codec: broker.FrameCodec,
        generation: ipc_root.GenerationLease,
    ) -> None:
        self._socket = connection
        self.session = session
        self._codec = codec
        self._generation = generation
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def codec_closed(self) -> bool:
        return self._codec.closed

    def write(
        self,
        *,
        message_id: str,
        correlation_id: str | None,
        message_type: str,
        payload: bytes,
        deadline: broker.Deadline,
    ) -> None:
        if self._closed:
            raise broker.TransportClosed()
        try:
            self._codec.write(
                self._socket,
                message_id=message_id,
                correlation_id=correlation_id,
                message_type=message_type,
                payload=payload,
                deadline=deadline,
            )
        except BaseException:
            self.close()
            raise

    def read(self, *, deadline: broker.Deadline) -> broker.ReceivedFrame:
        if self._closed:
            raise broker.TransportClosed(dispatch_effect="outcome_unknown")
        try:
            return self._codec.read(self._socket, deadline=deadline)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._codec.close()
            self._socket.close()
        finally:
            self._generation.close()

    def __enter__(self) -> Self:
        if self._closed:
            raise ListenerIntegrityError()
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()


class WorkerListener:
    __slots__ = (
        "_closed",
        "_endpoint_fd",
        "_generation",
        "_listener_lock_fd",
        "_readiness_identity",
        "_socket",
        "_socket_identity",
        "record",
        "root_spec",
        "spec",
    )

    def __init__(
        self,
        *,
        root_spec: ipc_root.PairRootSpec,
        spec: broker.ChannelSpec,
        listening_socket: socket.socket,
        record: ListenerRecord,
        generation: ipc_root.GenerationLease,
        endpoint_fd: int,
        listener_lock_fd: int,
        readiness_identity: FileIdentity,
        socket_identity: SocketIdentity,
    ) -> None:
        self.root_spec = root_spec
        self.spec = spec
        self._socket = listening_socket
        self.record = record
        self._generation = generation
        self._endpoint_fd = endpoint_fd
        self._listener_lock_fd = listener_lock_fd
        self._readiness_identity = readiness_identity
        self._socket_identity = socket_identity
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def _accept_transport(self, deadline: broker.Deadline) -> socket.socket:
        if self._closed or type(deadline) is not broker.Deadline:
            raise ListenerIntegrityError()
        operation_deadline = deadline.bounded(self.spec.max_operation_ms)
        try:
            self._socket.settimeout(operation_deadline.require())
            connection, _address = self._socket.accept()
            broker._validate_socket(connection)
            self._socket.settimeout(None)
            return connection
        except broker.BrokerError:
            raise
        except TimeoutError:
            raise broker.DeadlineExceeded() from None
        except OSError:
            raise broker.TransportClosed() from None

    def accept_authenticated(
        self,
        *,
        requester_boot_id: str,
        deadline: broker.Deadline,
    ) -> AuthenticatedConnection:
        generation = ipc_root.acquire_generation(self.root_spec)
        connection: socket.socket | None = None
        try:
            if (
                generation.generation_id != self.record.generation_id
                or generation.endpoint_identity != self._generation.endpoint_identity
            ):
                raise ListenerIntegrityError()
            connection = self._accept_transport(deadline)
            session = broker.server_handshake(
                connection,
                self.spec,
                generation.secret,
                requester_boot_id=requester_boot_id,
                responder_boot_id=self.record.responder_boot_id,
                deadline=deadline,
            )
            codec = broker.FrameCodec(
                self.spec,
                session,
                local_service=self.spec.responder_service,
            )
            result = AuthenticatedConnection(
                connection=connection,
                session=session,
                codec=codec,
                generation=generation,
            )
            connection = None
            generation = None  # type: ignore[assignment]
            return result
        except BaseException:
            if connection is not None:
                connection.close()
            raise
        finally:
            if generation is not None:
                generation.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        violation = False
        try:
            self._socket.close()
            if not _unlink_exact(
                self._endpoint_fd,
                ipc_root.LISTENER_NAME,
                self._readiness_identity,
                require_socket=False,
            ):
                violation = True
            if not _unlink_exact(
                self._endpoint_fd,
                self.spec.socket_name,
                self._socket_identity,
                require_socket=True,
            ):
                violation = True
            try:
                os.fsync(self._endpoint_fd)
            except OSError:
                violation = True
        finally:
            try:
                fcntl.flock(self._listener_lock_fd, fcntl.LOCK_UN)
            except OSError:
                violation = True
            _close_fd(self._listener_lock_fd)
            _close_fd(self._endpoint_fd)
            self._generation.close()
        if violation:
            raise ListenerIntegrityError()

    def __enter__(self) -> Self:
        if self._closed:
            raise ListenerIntegrityError()
        return self

    def __exit__(self, kind: object, _value: object, _traceback: object) -> None:
        try:
            self.close()
        except ListenerError:
            if kind is None:
                raise


def _close_fd(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _process_identity() -> tuple[int, int, frozenset[int]]:
    return os.geteuid(), os.getegid(), frozenset(os.getgroups())


def _validate_local_identity(root: ipc_root.PairRootSpec) -> None:
    uid, gid, groups = _process_identity()
    if (
        uid != root.responder_uid
        or gid != root.responder_gid
        or root.pair_gid not in groups | {gid}
    ):
        raise ListenerIdentityError()


def _validate_pair_channel(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
) -> None:
    if (
        type(root) is not ipc_root.PairRootSpec
        or type(spec) is not broker.ChannelSpec
        or spec.pair_root != root.endpoint_path
        or spec.responder_uid != root.responder_uid
        or spec.responder_gid != root.responder_gid
        or spec.pair_gid != root.pair_gid
        or spec.root_uid != root.responder_uid
        or spec.root_gid != root.pair_gid
        or spec.root_mode != ipc_root.ENDPOINT_MODE
        or spec.socket_uid != root.responder_uid
        or spec.socket_gid != root.pair_gid
        or spec.socket_mode != 0o660
    ):
        raise ListenerIntegrityError()


def _canonical_json(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeError):
        raise ListenerIntegrityError() from None
    if len(encoded) > MAX_LISTENER_BYTES:
        raise ListenerIntegrityError()
    return encoded


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ListenerIntegrityError()
        result[key] = value
    return result


def _decode_record(raw: bytes) -> ListenerRecord:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_LISTENER_BYTES:
        raise ListenerIntegrityError()
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_float=lambda _value: (_ for _ in ()).throw(ListenerIntegrityError()),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ListenerIntegrityError()
            ),
        )
    except ListenerError:
        raise
    except (RecursionError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ListenerIntegrityError() from None
    if (
        type(value) is not dict
        or _canonical_json(value) != raw
        or set(value)
        != {
            "schema_version",
            "protocol_version",
            "channel_spec_sha256",
            "generation_id",
            "responder_boot_id",
            "endpoint",
            "socket",
            "hmac_sha256",
        }
    ):
        raise ListenerIntegrityError()
    if (
        value["schema_version"] != LISTENER_SCHEMA_VERSION
        or value["protocol_version"] != broker.PROTOCOL_VERSION
        or type(value["channel_spec_sha256"]) is not str
        or _HEX_DIGEST.fullmatch(value["channel_spec_sha256"]) is None
        or type(value["generation_id"]) is not str
        or _HEX_DIGEST.fullmatch(value["generation_id"]) is None
        or type(value["responder_boot_id"]) is not str
        or _BOOT_ID.fullmatch(value["responder_boot_id"]) is None
        or type(value["hmac_sha256"]) is not str
        or _HEX_DIGEST.fullmatch(value["hmac_sha256"]) is None
    ):
        raise ListenerIntegrityError()
    return ListenerRecord(
        schema_version=value["schema_version"],
        protocol_version=value["protocol_version"],
        channel_spec_sha256=value["channel_spec_sha256"],
        generation_id=value["generation_id"],
        responder_boot_id=value["responder_boot_id"],
        endpoint=FileIdentity.from_mapping(value["endpoint"]),
        socket=SocketIdentity.from_mapping(value["socket"]),
        hmac_sha256=value["hmac_sha256"],
    )


def _record_mac(secret: broker.BootSecret, unsigned: dict[str, object]) -> str:
    return hmac.new(
        secret._material(),
        _LISTENER_MAC_DOMAIN + _canonical_json(unsigned),
        hashlib.sha256,
    ).hexdigest()


def _stat_at(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        raise ListenerIntegrityError() from None


def _validate_readiness_info(
    info: os.stat_result,
    root: ipc_root.PairRootSpec,
) -> FileIdentity:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != root.responder_uid
        or info.st_gid != root.pair_gid
        or stat.S_IMODE(info.st_mode) != LISTENER_FILE_MODE
        or not 1 <= info.st_size <= MAX_LISTENER_BYTES
    ):
        raise ListenerIntegrityError()
    return FileIdentity.from_stat(info)


def _validate_socket_info(
    info: os.stat_result,
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
) -> SocketIdentity:
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != root.responder_uid
        or info.st_gid != root.pair_gid
        or stat.S_IMODE(info.st_mode) != spec.socket_mode
    ):
        raise ListenerIntegrityError()
    return SocketIdentity.from_stat(spec.socket_name, info)


def _read_file_at(directory_fd: int, name: str, expected: FileIdentity) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if not hasattr(os, "O_NOFOLLOW"):
        raise ListenerIntegrityError()
    flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        before = os.fstat(descriptor)
        if FileIdentity.from_stat(before) != expected or before.st_nlink != 1:
            raise ListenerIntegrityError()
        raw = os.read(descriptor, MAX_LISTENER_BYTES + 1)
        after = os.fstat(descriptor)
        if FileIdentity.from_stat(after) != expected or before.st_size != after.st_size:
            raise ListenerIntegrityError()
        return raw
    except ListenerError:
        raise
    except OSError:
        raise ListenerIntegrityError() from None
    finally:
        _close_fd(descriptor)


def _current_endpoint_identity(
    generation: ipc_root.GenerationLease,
) -> FileIdentity:
    try:
        info = os.fstat(generation.endpoint_fd)
    except OSError:
        raise ListenerIntegrityError() from None
    identity = FileIdentity.from_stat(info)
    if not stat.S_ISDIR(info.st_mode) or identity != FileIdentity(
        device=generation.endpoint_identity.device,
        inode=generation.endpoint_identity.inode,
        uid=generation.endpoint_identity.uid,
        gid=generation.endpoint_identity.gid,
        mode=generation.endpoint_identity.mode,
    ):
        raise ListenerIntegrityError()
    return identity


def _verify_record(
    generation: ipc_root.GenerationLease,
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
) -> tuple[ListenerRecord, FileIdentity, SocketIdentity]:
    endpoint = _current_endpoint_identity(generation)
    readiness_info = _stat_at(generation.endpoint_fd, ipc_root.LISTENER_NAME)
    socket_info = _stat_at(generation.endpoint_fd, spec.socket_name)
    if readiness_info is None or socket_info is None:
        raise ListenerIntegrityError()
    readiness_identity = _validate_readiness_info(readiness_info, root)
    socket_identity = _validate_socket_info(socket_info, root, spec)
    record = _decode_record(
        _read_file_at(
            generation.endpoint_fd,
            ipc_root.LISTENER_NAME,
            readiness_identity,
        )
    )
    if (
        record.channel_spec_sha256 != broker._spec_digest(spec)
        or record.generation_id != generation.generation_id
        or record.endpoint != endpoint
        or record.socket != socket_identity
        or not hmac.compare_digest(
            record.hmac_sha256,
            _record_mac(generation.secret, record.unsigned()),
        )
    ):
        raise ListenerIntegrityError()
    return record, readiness_identity, socket_identity


def verify_listener(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
) -> VerifiedListener:
    """Verify current readiness while retaining a shared generation lock."""

    _validate_pair_channel(root, spec)
    generation = ipc_root.acquire_generation(root)
    try:
        record, _readiness, _socket = _verify_record(generation, root, spec)
        result = VerifiedListener(generation=generation, record=record)
        generation = None  # type: ignore[assignment]
        return result
    finally:
        if generation is not None:
            generation.close()


def _open_endpoint_for_owner(
    generation: ipc_root.GenerationLease,
    root: ipc_root.PairRootSpec,
) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    if not hasattr(os, "O_NOFOLLOW"):
        raise ListenerIntegrityError()
    flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(".", flags, dir_fd=generation.endpoint_fd)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or FileIdentity.from_stat(info) != _current_endpoint_identity(generation)
            or info.st_uid != root.responder_uid
            or info.st_gid != root.pair_gid
            or stat.S_IMODE(info.st_mode) != ipc_root.ENDPOINT_MODE
        ):
            raise ListenerIntegrityError()
        return descriptor
    except ListenerError:
        _close_fd(descriptor)
        raise
    except OSError:
        _close_fd(descriptor)
        raise ListenerIntegrityError() from None


def _open_listener_lock(endpoint_fd: int, root: ipc_root.PairRootSpec) -> int:
    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK
    if not hasattr(os, "O_NOFOLLOW"):
        raise ListenerIntegrityError()
    flags |= os.O_NOFOLLOW
    descriptor = -1
    created = False
    try:
        try:
            descriptor = os.open(ipc_root.LISTENER_LOCK_NAME, flags, dir_fd=endpoint_fd)
        except FileNotFoundError:
            descriptor = os.open(
                ipc_root.LISTENER_LOCK_NAME,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=endpoint_fd,
            )
            created = True
            os.fchown(descriptor, root.responder_uid, root.pair_gid)
            os.fchmod(descriptor, LISTENER_LOCK_MODE)
            os.fsync(descriptor)
            os.fsync(endpoint_fd)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != root.responder_uid
            or info.st_gid != root.pair_gid
            or stat.S_IMODE(info.st_mode) != LISTENER_LOCK_MODE
            or info.st_size != 0
        ):
            raise ListenerIntegrityError()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ListenerBusy() from None
        return descriptor
    except ListenerError:
        _close_fd(descriptor)
        if created:
            try:
                os.unlink(ipc_root.LISTENER_LOCK_NAME, dir_fd=endpoint_fd)
            except OSError:
                pass
        raise
    except OSError:
        _close_fd(descriptor)
        raise ListenerIntegrityError() from None


def _anchored_socket_path(
    endpoint_fd: int, root: ipc_root.PairRootSpec, name: str
) -> str:
    if sys.platform != "linux" or not hasattr(os, "O_PATH"):
        raise ListenerPlatformError()
    proc_root = f"/proc/self/fd/{endpoint_fd}"
    try:
        proc_info = os.stat(proc_root, follow_symlinks=True)
        endpoint_info = os.fstat(endpoint_fd)
    except OSError:
        raise ListenerIntegrityError() from None
    if (proc_info.st_dev, proc_info.st_ino) != (
        endpoint_info.st_dev,
        endpoint_info.st_ino,
    ):
        raise ListenerIntegrityError()
    del root
    return f"{proc_root}/{name}"


def _write_all(descriptor: int, raw: bytes) -> None:
    offset = 0
    try:
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
    except OSError:
        raise ListenerIntegrityError() from None


def _publish_record(
    endpoint_fd: int,
    root: ipc_root.PairRootSpec,
    record: ListenerRecord,
) -> FileIdentity:
    stage_name = f".listener.{secrets.token_hex(16)}.tmp"
    stage_fd = -1
    stage_identity: FileIdentity | None = None
    published = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if not hasattr(os, "O_NOFOLLOW"):
            raise ListenerIntegrityError()
        flags |= os.O_NOFOLLOW
        stage_fd = os.open(stage_name, flags, 0o600, dir_fd=endpoint_fd)
        os.fchown(stage_fd, root.responder_uid, root.pair_gid)
        os.fchmod(stage_fd, LISTENER_FILE_MODE)
        stage_info = os.fstat(stage_fd)
        if (
            not stat.S_ISREG(stage_info.st_mode)
            or stage_info.st_nlink != 1
            or stage_info.st_uid != root.responder_uid
            or stage_info.st_gid != root.pair_gid
            or stat.S_IMODE(stage_info.st_mode) != LISTENER_FILE_MODE
            or stage_info.st_size != 0
        ):
            raise ListenerIntegrityError()
        stage_identity = FileIdentity.from_stat(stage_info)
        raw = _canonical_json(record.as_dict())
        _write_all(stage_fd, raw)
        os.fsync(stage_fd)
        os.link(
            stage_name,
            ipc_root.LISTENER_NAME,
            src_dir_fd=endpoint_fd,
            dst_dir_fd=endpoint_fd,
            follow_symlinks=False,
        )
        os.unlink(stage_name, dir_fd=endpoint_fd)
        stage_name = ""
        os.fsync(endpoint_fd)
        info = _stat_at(endpoint_fd, ipc_root.LISTENER_NAME)
        if info is None:
            raise ListenerIntegrityError()
        identity = _validate_readiness_info(info, root)
        if (
            identity != stage_identity
            or _read_file_at(
                endpoint_fd,
                ipc_root.LISTENER_NAME,
                identity,
            )
            != raw
        ):
            raise ListenerIntegrityError()
        published = True
        return identity
    except ListenerError:
        raise
    except OSError:
        raise ListenerIntegrityError() from None
    finally:
        rollback_identity = stage_identity
        if not published and stage_fd >= 0:
            try:
                rollback_identity = FileIdentity.from_stat(os.fstat(stage_fd))
            except (OSError, ListenerError):
                rollback_identity = None
        _close_fd(stage_fd)
        if not published and rollback_identity is not None:
            if stage_name:
                _unlink_exact(
                    endpoint_fd,
                    stage_name,
                    rollback_identity,
                    require_socket=False,
                    allowed_links=(1, 2),
                )
            _unlink_exact(
                endpoint_fd,
                ipc_root.LISTENER_NAME,
                rollback_identity,
                require_socket=False,
            )
            try:
                os.fsync(endpoint_fd)
            except OSError:
                pass


def _unlink_exact(
    endpoint_fd: int,
    name: str,
    identity: FileIdentity | SocketIdentity,
    *,
    require_socket: bool,
    allowed_links: tuple[int, ...] = (1,),
) -> bool:
    info = _stat_at(endpoint_fd, name)
    if info is None:
        return False
    current = FileIdentity.from_stat(info)
    expected = FileIdentity(
        device=identity.device,
        inode=identity.inode,
        uid=identity.uid,
        gid=identity.gid,
        mode=identity.mode,
    )
    if current != expected or info.st_nlink not in allowed_links:
        return False
    if require_socket != stat.S_ISSOCK(info.st_mode):
        return False
    try:
        os.unlink(name, dir_fd=endpoint_fd)
    except OSError:
        return False
    return True


def _remove_stale_pair(
    endpoint_fd: int,
    generation: ipc_root.GenerationLease,
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
) -> None:
    readiness_info = _stat_at(endpoint_fd, ipc_root.LISTENER_NAME)
    socket_info = _stat_at(endpoint_fd, spec.socket_name)
    if readiness_info is None and socket_info is None:
        return
    if readiness_info is None and socket_info is not None:
        socket_identity = _validate_socket_info(socket_info, root, spec)
        if not _unlink_exact(
            endpoint_fd,
            spec.socket_name,
            socket_identity,
            require_socket=True,
        ):
            raise ListenerIntegrityError()
        try:
            os.fsync(endpoint_fd)
        except OSError:
            raise ListenerIntegrityError() from None
        return
    if readiness_info is None or socket_info is None:
        raise ListenerIntegrityError()
    readiness_identity = _validate_readiness_info(readiness_info, root)
    socket_identity = _validate_socket_info(socket_info, root, spec)
    record = _decode_record(
        _read_file_at(
            endpoint_fd,
            ipc_root.LISTENER_NAME,
            readiness_identity,
        )
    )
    if (
        record.channel_spec_sha256 != broker._spec_digest(spec)
        or record.endpoint != _current_endpoint_identity(generation)
        or record.socket != socket_identity
    ):
        raise ListenerIntegrityError()
    if record.generation_id == generation.generation_id and not hmac.compare_digest(
        record.hmac_sha256,
        _record_mac(generation.secret, record.unsigned()),
    ):
        raise ListenerIntegrityError()
    if not _unlink_exact(
        endpoint_fd,
        ipc_root.LISTENER_NAME,
        readiness_identity,
        require_socket=False,
    ) or not _unlink_exact(
        endpoint_fd,
        spec.socket_name,
        socket_identity,
        require_socket=True,
    ):
        raise ListenerIntegrityError()
    try:
        os.fsync(endpoint_fd)
    except OSError:
        raise ListenerIntegrityError() from None


def bind_worker_listener(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    *,
    responder_boot_id: str,
) -> WorkerListener:
    """Bind and publish one responder listener under the current generation."""

    _validate_pair_channel(root, spec)
    _validate_local_identity(root)
    if (
        type(responder_boot_id) is not str
        or _BOOT_ID.fullmatch(responder_boot_id) is None
    ):
        raise ListenerIntegrityError()
    generation = ipc_root.acquire_generation(root)
    endpoint_fd = listener_lock_fd = -1
    listening: socket.socket | None = None
    socket_identity: SocketIdentity | None = None
    readiness_identity: FileIdentity | None = None
    try:
        endpoint_fd = _open_endpoint_for_owner(generation, root)
        listener_lock_fd = _open_listener_lock(endpoint_fd, root)
        _remove_stale_pair(endpoint_fd, generation, root, spec)
        listening = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        broker._validate_socket(listening)
        listening.bind(_anchored_socket_path(endpoint_fd, root, spec.socket_name))
        os.chown(
            spec.socket_name,
            root.responder_uid,
            root.pair_gid,
            dir_fd=endpoint_fd,
            follow_symlinks=False,
        )
        os.chmod(
            spec.socket_name,
            spec.socket_mode,
            dir_fd=endpoint_fd,
            follow_symlinks=False,
        )
        socket_info = _stat_at(endpoint_fd, spec.socket_name)
        if socket_info is None:
            raise ListenerIntegrityError()
        socket_identity = _validate_socket_info(socket_info, root, spec)
        listening.listen(max(1, min(spec.max_queue_depth, 128)))
        unsigned = {
            "schema_version": LISTENER_SCHEMA_VERSION,
            "protocol_version": broker.PROTOCOL_VERSION,
            "channel_spec_sha256": broker._spec_digest(spec),
            "generation_id": generation.generation_id,
            "responder_boot_id": responder_boot_id,
            "endpoint": _current_endpoint_identity(generation).as_dict(),
            "socket": socket_identity.as_dict(),
        }
        record = ListenerRecord(
            schema_version=LISTENER_SCHEMA_VERSION,
            protocol_version=broker.PROTOCOL_VERSION,
            channel_spec_sha256=broker._spec_digest(spec),
            generation_id=generation.generation_id,
            responder_boot_id=responder_boot_id,
            endpoint=FileIdentity.from_mapping(unsigned["endpoint"]),
            socket=socket_identity,
            hmac_sha256=_record_mac(generation.secret, unsigned),
        )
        readiness_identity = _publish_record(endpoint_fd, root, record)
        result = WorkerListener(
            root_spec=root,
            spec=spec,
            listening_socket=listening,
            record=record,
            generation=generation,
            endpoint_fd=endpoint_fd,
            listener_lock_fd=listener_lock_fd,
            readiness_identity=readiness_identity,
            socket_identity=socket_identity,
        )
        listening = None
        generation = None  # type: ignore[assignment]
        readiness_identity = None
        socket_identity = None
        endpoint_fd = listener_lock_fd = -1
        return result
    except ListenerError:
        raise
    except (OSError, broker.BrokerError):
        raise ListenerIntegrityError() from None
    finally:
        if listening is not None:
            listening.close()
        if readiness_identity is not None:
            _unlink_exact(
                endpoint_fd,
                ipc_root.LISTENER_NAME,
                readiness_identity,
                require_socket=False,
            )
        if socket_identity is not None:
            _unlink_exact(
                endpoint_fd,
                spec.socket_name,
                socket_identity,
                require_socket=True,
            )
        if listener_lock_fd >= 0:
            try:
                fcntl.flock(listener_lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        _close_fd(listener_lock_fd)
        _close_fd(endpoint_fd)
        if generation is not None:
            generation.close()


def connect_authenticated(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    *,
    requester_boot_id: str,
    deadline: broker.Deadline,
) -> AuthenticatedConnection:
    """Verify readiness, connect to its inode, then complete the public handshake."""

    _validate_pair_channel(root, spec)
    verified = verify_listener(root, spec)
    connection: socket.socket | None = None
    try:
        connection, endpoint_identity, _peer = broker.connect_verified(
            spec,
            local_service=spec.requester_service,
            deadline=deadline,
        )
        if (
            endpoint_identity.device != verified.record.socket.device
            or endpoint_identity.inode != verified.record.socket.inode
            or endpoint_identity.uid != verified.record.socket.uid
            or endpoint_identity.gid != verified.record.socket.gid
            or endpoint_identity.mode != verified.record.socket.mode
        ):
            raise ListenerIntegrityError()
        session = broker.client_handshake(
            connection,
            spec,
            verified.generation.secret,
            requester_boot_id=requester_boot_id,
            responder_boot_id=verified.record.responder_boot_id,
            deadline=deadline,
        )
        codec = broker.FrameCodec(
            spec,
            session,
            local_service=spec.requester_service,
        )
        result = AuthenticatedConnection(
            connection=connection,
            session=session,
            codec=codec,
            generation=verified.generation,
        )
        connection = None
        verified._closed = True
        return result
    finally:
        if connection is not None:
            connection.close()
        verified.close()
