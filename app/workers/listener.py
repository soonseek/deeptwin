"""Authenticated Unix listener lifecycle for one verified worker channel.

The listener owns only its responder-writable endpoint directory.  Root-owned
boot material remains in the parent pair root, protected by a generation lock.
Readiness is an exact HMAC-authenticated manifest; it is never authority to
skip the broker's Linux peer-credential and mutual-handshake checks.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import select
import socket
import stat
import struct
import sys
import threading
from dataclasses import dataclass
from typing import Self

from ..deployment import mounts as m
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


_ISSUE = object()  # the factories' private issuance token
_IDLE_SLICE_MAX_MS = 10


class AuthenticatedConnection:
    """One factory-issued generic owner: the accepted or connected socket, its
    authenticated session and codec, and the generation lease it was
    acquired under, retained from acquisition to close (Task51, design §6).

    The owner keeps one deadline, bounded by the channel's operation cap and
    retained before acquisition; every later read, write or poll takes the
    minimum of the supplied and the retained end. One nonblocking reader latch
    covers `read` and `read_duplex` (a competing read fails before consuming a
    byte and never closes the legitimate reader); a bounded writer latch
    encodes through the codec and writes the encoded bytes without holding the
    codec's lock over socket waits (a failed encoded write closes the owner:
    the advanced sequence is never reused). Close detaches its finite
    resources first, shuts the socket down to wake readers and writers,
    attempts codec, socket and generation independently, and raises the first
    cleanup failure. Nonconstructible, uncopyable, unserializable. The generic
    owner gains no extension fences (no recheck, mount or readiness claims);
    an accepted owner outlives listener close.
    """

    __slots__ = ("_closed", "_codec", "_codec_was_closed", "_deadline", "_generation",
                 "_read_latch", "_socket", "_write_latch", "session")

    def __init__(
        self,
        *,
        connection: socket.socket,
        session: broker.AuthenticatedSession,
        codec: broker.FrameCodec,
        generation: ipc_root.GenerationLease,
        deadline: broker.Deadline,
        _issued: object = None,
    ) -> None:
        if _issued is not _ISSUE:
            raise TypeError("AuthenticatedConnection is issued by the listener factories only")
        if type(deadline) is not broker.Deadline:
            raise ListenerIntegrityError()
        self._socket = connection
        self.session = session
        self._codec = codec
        self._generation = generation
        self._deadline = deadline
        self._closed = False
        self._codec_was_closed = False
        self._read_latch = threading.Lock()
        self._write_latch = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def codec_closed(self) -> bool:
        codec = self._codec
        if codec is None:
            return self._codec_was_closed
        return codec.closed

    @property
    def deadline(self) -> broker.Deadline:
        """The retained end: the caller's deadline at acquisition, bounded by
        the channel's operation cap."""
        return self._deadline

    def _effective(self, deadline: broker.Deadline) -> broker.Deadline:
        if type(deadline) is not broker.Deadline:
            raise ListenerIntegrityError()
        return broker.Deadline(min(deadline.end_monotonic, self._deadline.end_monotonic))

    def write(
        self,
        *,
        message_id: str,
        correlation_id: str | None,
        message_type: str,
        payload: bytes,
        deadline: broker.Deadline,
    ) -> None:
        effective = self._effective(deadline)
        if self._closed:
            raise broker.TransportClosed()
        if not self._write_latch.acquire(timeout=effective.require()):
            raise broker.DeadlineExceeded()
        try:
            codec, sock = self._codec, self._socket
            if self._closed or codec is None or sock is None:
                raise broker.TransportClosed()
            try:
                # the codec's own lock is held for the encode only; the socket wait
                # happens outside it so a reader or a close is never blocked behind it
                raw = codec.encode(
                    message_id=message_id,
                    correlation_id=correlation_id,
                    message_type=message_type,
                    payload=payload,
                )
                try:
                    broker._validate_socket(sock)
                except broker.EndpointViolation:
                    if self._closed:  # a concurrent close, not an endpoint fault
                        raise broker.TransportClosed() from None
                    raise
                broker._send_exact(sock, struct.pack(">I", len(raw)) + raw, effective)
            except BaseException:
                self._close_after_failure()
                raise
        finally:
            self._write_latch.release()

    def read(self, *, deadline: broker.Deadline) -> broker.ReceivedFrame:
        frame = self.read_duplex(deadline=deadline)
        if frame is None:  # closed by construction: no idle slice was asked for
            raise broker.TransportClosed(dispatch_effect="outcome_unknown")
        return frame

    def read_duplex(
        self,
        *,
        deadline: broker.Deadline,
        idle_timeout_ms: int | None = None,
    ) -> broker.ReceivedFrame | None:
        """Receive one authenticated frame, or None when `idle_timeout_ms` (an
        exact int 1..10) elapsed before any prefix byte became readable. Once a
        prefix begins the whole frame is finished under the effective deadline
        or the owner closes: a short poll never consumes half a frame. EOF,
        errors and a partial prefix or body are never idle."""

        if idle_timeout_ms is not None and (
            type(idle_timeout_ms) is not int or not 1 <= idle_timeout_ms <= _IDLE_SLICE_MAX_MS
        ):
            raise broker.ChannelConfigurationError()
        effective = self._effective(deadline)
        if self._closed:
            raise broker.TransportClosed(dispatch_effect="outcome_unknown")
        if not self._read_latch.acquire(blocking=False):
            raise ListenerBusy()
        try:
            codec, sock = self._codec, self._socket
            if self._closed or codec is None or sock is None:
                raise broker.TransportClosed(dispatch_effect="outcome_unknown")
            try:
                effective.require(dispatch_effect="outcome_unknown")
                if idle_timeout_ms is not None:
                    slice_s = min(idle_timeout_ms / 1000.0, effective.remaining())
                    try:
                        readable, _writable, _errors = select.select([sock], [], [], slice_s)
                    except (OSError, ValueError):
                        # a concurrent close emptied the descriptor mid-poll
                        raise broker.TransportClosed(dispatch_effect="outcome_unknown") from None
                    if not readable:
                        return None
                try:
                    broker._validate_socket(sock)
                except broker.EndpointViolation:
                    if self._closed:  # a concurrent close, not an endpoint fault
                        raise broker.TransportClosed(dispatch_effect="outcome_unknown") from None
                    raise
                header = broker._read_exact(sock, 4, effective)
                (size,) = struct.unpack(">I", header)
                if not 1 <= size <= codec._spec.max_frame_bytes:
                    raise broker.ProtocolViolation(dispatch_effect="outcome_unknown")
                raw = broker._read_exact(sock, size, effective)
                frame = codec.decode(raw)  # the codec's lock for the MAC/sequence check only
                if self._closed:
                    raise broker.TransportClosed(dispatch_effect="outcome_unknown")
                return frame
            except BaseException:
                self._close_after_failure()
                raise
        finally:
            self._read_latch.release()

    def _close_after_failure(self) -> None:
        with contextlib.suppress(Exception):  # the operation failure is the primary
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # the closed latch detaches the finite set before any fallible close
        codec, connection, generation = self._codec, self._socket, self._generation
        self._codec = self._socket = self._generation = None
        first_error = None
        try:
            connection.shutdown(socket.SHUT_RDWR)  # wakes a blocked reader or writer
        except OSError as error:
            if error.errno not in {errno.ENOTCONN, errno.EBADF}:
                first_error = error
        except BaseException as error:  # noqa: BLE001 - recorded, every resource still attempted
            first_error = error
        for owned in (codec, connection, generation):
            try:
                owned.close()
            except BaseException as error:  # noqa: BLE001 - recorded, every resource still attempted
                if first_error is None:
                    first_error = error
        self._codec_was_closed = codec.closed  # honest even when the codec's own close failed
        if first_error is not None:
            raise first_error

    def __enter__(self) -> Self:
        if self._closed:
            raise ListenerIntegrityError()
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()

    def __copy__(self) -> object:
        raise TypeError("AuthenticatedConnection is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("AuthenticatedConnection is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("AuthenticatedConnection is not serializable")

    def __repr__(self) -> str:
        return f"AuthenticatedConnection(closed={self._closed})"


class WorkerListener:
    __slots__ = (
        "_closed",
        "_endpoint_fd",
        "_generation",
        "_listener_lock_fd",
        "_pins",
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
        pins: tuple[int, ...] = (),
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
        self._pins = pins
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def _accept_transport(self, deadline: broker.Deadline) -> socket.socket:
        if self._closed or type(deadline) is not broker.Deadline:
            raise ListenerIntegrityError()
        operation_deadline = deadline.bounded(self.spec.max_operation_ms)
        connection: socket.socket | None = None
        try:
            self._socket.settimeout(operation_deadline.require())
            connection, _address = self._socket.accept()
            broker._validate_socket(connection)
            result, connection = connection, None
            return result
        except broker.BrokerError:
            raise
        except TimeoutError:
            raise broker.DeadlineExceeded() from None
        except OSError:
            raise broker.TransportClosed() from None
        finally:
            # an accepted socket that failed validation is unwound here, and the
            # listening socket's timeout is restored on every exit without replacing
            # the primary exception
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            try:
                self._socket.settimeout(None)
            except OSError:
                pass

    def accept_authenticated(
        self,
        *,
        requester_boot_id: str,
        deadline: broker.Deadline,
    ) -> AuthenticatedConnection:
        if type(deadline) is not broker.Deadline:
            raise ListenerIntegrityError()
        # the owner's one deadline is retained before acquisition, bounded by the
        # channel's operation cap; every later stage takes the minimum of it
        retained = deadline.bounded(self.spec.max_operation_ms)
        generation = ipc_root.acquire_generation(self.root_spec)
        connection: socket.socket | None = None
        codec: broker.FrameCodec | None = None
        try:
            if (
                generation.generation_id != self.record.generation_id
                or generation.endpoint_identity != self._generation.endpoint_identity
            ):
                raise ListenerIntegrityError()
            connection = self._accept_transport(retained)
            session = broker.server_handshake(
                connection,
                self.spec,
                generation.secret,
                requester_boot_id=requester_boot_id,
                responder_boot_id=self.record.responder_boot_id,
                deadline=retained,
            )
            codec = broker.FrameCodec(
                self.spec,
                session,
                local_service=self.spec.responder_service,
            )
            retained.require()
            result = AuthenticatedConnection(
                connection=connection,
                session=session,
                codec=codec,
                generation=generation,
                deadline=retained,
                _issued=_ISSUE,
            )
            connection = None
            codec = None
            generation = None  # type: ignore[assignment]
            return result
        except BaseException:
            if codec is not None:
                codec.close()
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
            for pin in self._pins:
                _close_fd(pin)
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
    except BaseException as error:
        owned, descriptor = descriptor, -1
        try:
            _close_fd(owned)
        except BaseException:  # noqa: BLE001, S110 - preserve readiness primary
            pass
        if isinstance(error, OSError):
            raise ListenerIntegrityError() from None
        raise
    owned, descriptor = descriptor, -1
    _close_fd(owned)
    return raw


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
    except BaseException:
        owned, generation = generation, None
        if owned is not None:
            try:
                owned.close()
            except BaseException:  # noqa: BLE001, S110 - preserve verification primary
                pass
        raise


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


def _pin_inodes(endpoint_fd: int, named: tuple) -> tuple[int, ...]:
    """Hold each published name's inode for the listener's lifetime.

    A (device, inode, uid, gid, mode) identity alone cannot tell a replacement
    from the original once the original is freed: ext4 hands a freed inode
    number straight to the next file, so an unlink-and-recreate with the same
    owner and mode compared equal and `close` removed the replacement. A held
    O_PATH descriptor keeps each inode allocated, so no replacement can reuse
    its number while the listener lives. Without O_PATH (not Linux) nothing is
    pinned and the identity check stands alone, as before.
    """

    flag = getattr(os, "O_PATH", None)
    if flag is None:
        return ()
    pins: list[int] = []
    try:
        for name, identity in named:
            pin = os.open(name, flag | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=endpoint_fd)
            pins.append(pin)
            info = os.fstat(pin)
            if (info.st_dev, info.st_ino) != (identity.device, identity.inode):
                raise ListenerIntegrityError()
        result, pins = tuple(pins), []
        return result
    finally:
        for pin in pins:
            _close_fd(pin)


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
    pins: tuple[int, ...] = ()
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
        pins = _pin_inodes(
            endpoint_fd,
            ((ipc_root.LISTENER_NAME, readiness_identity), (spec.socket_name, socket_identity)),
        )
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
            pins=pins,
        )
        pins = ()
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
        for pin in pins:
            _close_fd(pin)
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
    if type(deadline) is not broker.Deadline:
        raise ListenerIntegrityError()
    # the owner's one deadline is retained before readiness, connect and handshake,
    # bounded by the channel's operation cap
    retained = deadline.bounded(spec.max_operation_ms)
    retained.require()
    verified = verify_listener(root, spec)
    connection: socket.socket | None = None
    codec: broker.FrameCodec | None = None
    try:
        retained.require()
        connection, endpoint_identity, _peer = broker.connect_verified(
            spec,
            local_service=spec.requester_service,
            deadline=retained,
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
            deadline=retained,
        )
        codec = broker.FrameCodec(
            spec,
            session,
            local_service=spec.requester_service,
        )
        retained.require()
        result = AuthenticatedConnection(
            connection=connection,
            session=session,
            codec=codec,
            generation=verified.generation,
            deadline=retained,
            _issued=_ISSUE,
        )
        connection = None
        codec = None
        verified._closed = True
        return result
    finally:
        # every acquired resource is unwound on failure; the original exception is
        # preserved (the generation is released by the verifier's own close)
        if codec is not None:
            codec.close()
        if connection is not None:
            connection.close()
        verified.close()


# --- worker-private probe channel: extension accept/connect and fences ---------
# (Task 25 slice 2c; contracts/extension-worker-probe.md §3/§6, proposal §3)

_read_mountinfo = m.read_mountinfo


def _extension_mount_fence(root: ipc_root.PairRootSpec, *, read_only: bool) -> None:
    """The slot's pair root must be exactly one mountpoint with the side's
    mapping (read-only for control, read-write for the worker), with no
    mount nested below it and no visible same-device alias of its backing
    path; an unreadable mount table fails closed. Named volumes on the host
    state device (the compose shape) pass; a bare host that bind-mounts the
    slot out of its root filesystem is refused as a same-device alias, by
    the same rule the worker metadata source applies."""

    try:
        mounts = _read_mountinfo()
        mount = m.containing(mounts, root.pair_root)
    except m.DeploymentSourceError:
        raise ListenerIntegrityError() from None
    if mount.mountpoint != root.pair_root or mount.read_only is not read_only:
        raise ListenerIntegrityError()
    backing = m.backing(mount, root.pair_root)
    for other in mounts:
        if other is mount:
            continue
        if other.mountpoint.is_relative_to(root.pair_root):
            raise ListenerIntegrityError()
        if other.device == mount.device and (
            other.root.is_relative_to(backing) or backing.is_relative_to(other.root)
        ):
            raise ListenerIntegrityError()


class ExtensionConnection:
    """One owning, authenticated probe connection with its fences.

    Owns the socket, the codec and (after a successful handshake) the
    generation, the populated-generation fence and the listener record it
    was verified against. `recheck()` re-runs the populated fence, the
    listener record fence (readiness bytes, HMAC, socket inode) and the
    mount fence; any failure closes the connection. Ownership order on
    close: fence, codec and socket, then the generation. Nonconstructible,
    uncopyable, unserializable: no observation recreates it.
    """

    __slots__ = (
        "_closed",
        "_codec",
        "_fence",
        "_generation",
        "_read_only",
        "_reader_lock",
        "_root",
        "_socket",
        "_spec",
        "deadline",
        "peer",
        "record",
        "session",
    )

    def __init__(self) -> None:
        raise TypeError("an extension connection is accepted or connected, never built")

    @property
    def closed(self) -> bool:
        return self._closed

    def recheck(self) -> None:
        # snapshot: a concurrent close() clears the lease, which must read as closed
        # (a closed-set integrity error), never as an attribute fault
        generation, fence = self._generation, self._fence
        if self._closed or generation is None or fence is None:
            raise ListenerIntegrityError()
        try:
            fence.recheck_current()
            record, _readiness, _socket = _verify_record(generation, self._root, self._spec)
            if record != self.record:
                raise ListenerIntegrityError()
            _extension_mount_fence(self._root, read_only=self._read_only)
        except BaseException as error:
            try:
                self.close()
            except BaseException:  # noqa: BLE001, S110 - preserve operation primary
                pass
            if isinstance(error, ListenerError):
                raise
            if isinstance(error, (ipc_root.IpcRootError, OSError)):
                raise ListenerIntegrityError() from None
            raise

    def write(self, *, message_id: str, correlation_id: str | None, message_type: str,
              payload: bytes, deadline: broker.Deadline) -> None:
        if self._closed:
            raise broker.TransportClosed()
        operation_deadline = self._bounded_deadline(deadline)
        try:
            self._codec.write(
                self._socket,
                message_id=message_id,
                correlation_id=correlation_id,
                message_type=message_type,
                payload=payload,
                deadline=operation_deadline,
            )
        except BaseException:
            try:
                self.close()
            except BaseException:  # noqa: BLE001, S110 - preserve operation primary
                pass
            raise

    def read(self, *, deadline: broker.Deadline) -> broker.ReceivedFrame:
        if self._closed:
            raise broker.TransportClosed(dispatch_effect="outcome_unknown")
        operation_deadline = self._bounded_deadline(deadline)
        if not self._reader_lock.acquire(blocking=False):
            raise broker.ProtocolViolation(dispatch_effect="outcome_unknown")
        try:
            return self._codec.read(self._socket, deadline=operation_deadline)
        except BaseException:
            try:
                self.close()
            except BaseException:  # noqa: BLE001, S110 - preserve operation primary
                pass
            raise
        finally:
            self._reader_lock.release()

    def _bounded_deadline(self, deadline: broker.Deadline) -> broker.Deadline:
        if type(deadline) is not broker.Deadline:
            raise broker.ChannelConfigurationError()
        return broker.Deadline(
            min(deadline.end_monotonic, self.deadline.end_monotonic)
        )

    def read_duplex(self, *, deadline: broker.Deadline) -> broker.ReceivedFrame:
        """Read one authenticated frame without holding the codec across I/O.

        The owner-local reader latch is shared with ``read``.  Refusing a
        competing reader does not consume bytes and does not close the valid
        reader's owner.  Prefix/body acquisition remains under the retained
        owner deadline and authentication/sequence advancement stays in the
        existing ``FrameCodec.decode`` implementation.
        """

        if self._closed:
            raise broker.TransportClosed(dispatch_effect="outcome_unknown")
        operation_deadline = self._bounded_deadline(deadline)
        if not self._reader_lock.acquire(blocking=False):
            raise broker.ProtocolViolation(dispatch_effect="outcome_unknown")

        def read_exact(size: int) -> bytes:
            value = bytearray()
            while len(value) < size:
                remaining = operation_deadline.require(
                    dispatch_effect="outcome_unknown"
                )
                try:
                    readable, _, _ = select.select(
                        [self._socket], [], [], remaining
                    )
                except (OSError, ValueError):
                    raise broker.TransportUncertain(
                        dispatch_effect="outcome_unknown"
                    ) from None
                if not readable:
                    raise broker.DeadlineExceeded(
                        dispatch_effect="outcome_unknown"
                    )
                try:
                    block = self._socket.recv(size - len(value))
                except ConnectionResetError:
                    block = b""  # the peer's close (ECONNRESET on Linux, EOF on macOS)
                except (OSError, TimeoutError):
                    raise broker.TransportUncertain(
                        dispatch_effect="outcome_unknown"
                    ) from None
                if not block:
                    raise broker.TransportClosed(
                        dispatch_effect="outcome_unknown"
                    )
                value.extend(block)
            return bytes(value)

        try:
            self.recheck()
            prefix = read_exact(4)
            (size,) = struct.unpack(">I", prefix)
            if not 1 <= size <= self._spec.max_frame_bytes:
                raise broker.ProtocolViolation(dispatch_effect="outcome_unknown")
            frame = self._codec.decode(read_exact(size))
            self.recheck()
            operation_deadline.require(dispatch_effect="outcome_unknown")
            return frame
        except BaseException:
            try:
                self.close()
            except BaseException:  # noqa: BLE001, S110 - preserve operation primary
                pass
            raise
        finally:
            self._reader_lock.release()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # The closed latch detaches the finite set before any fallible close.
        fence, codec, connection, generation = (
            self._fence,
            self._codec,
            self._socket,
            self._generation,
        )
        self._fence = self._codec = self._socket = self._generation = None
        first_error = None
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError as error:
            if error.errno not in {errno.ENOTCONN, errno.EBADF}:
                first_error = error
        except BaseException as error:
            first_error = error
        for owned in (fence, codec, connection, generation):
            try:
                owned.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def __enter__(self) -> Self:
        if self._closed:
            raise ListenerIntegrityError()
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ExtensionConnection(closed={self._closed!r})"

    def __copy__(self) -> object:
        raise TypeError("an extension connection cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("an extension connection cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("an extension connection cannot be serialized")


def _extension_connection(
    *,
    connection: socket.socket,
    session: broker.AuthenticatedSession,
    codec: broker.FrameCodec,
    generation: ipc_root.GenerationLease,
    fence: ipc_root.PopulatedGenerationFence,
    record: ListenerRecord,
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    read_only: bool,
    peer: broker.PeerCredentials | None,
    deadline: broker.Deadline,
) -> ExtensionConnection:
    result = object.__new__(ExtensionConnection)
    result._closed = False
    # the connection's own window: on the responder side it starts at the
    # transport accept and already bounded the handshake; on the requester
    # side it is the attempt's deadline
    result.deadline = deadline
    # the kernel peer credentials observed at connect, fixed per connection
    # (control keeps them for its comparison; the responder wrapper verifies
    # them before the hello but returns only the session, so the accept side
    # records none — a deferred retention, not a check skipped)
    result.peer = peer
    result._socket = connection
    result.session = session
    result._codec = codec
    result._generation = generation
    result._fence = fence
    result.record = record
    result._root = root
    result._spec = spec
    result._read_only = read_only
    result._reader_lock = threading.Lock()
    return result


def _accept_extension_authenticated(
    worker: WorkerListener,
    *,
    deadline: broker.Deadline,
    connection_ms: int | None = None,
) -> ExtensionConnection:
    """Responder side: accept one probe connection under every fence.

    The generation is re-acquired and fenced, the worker's own readiness
    record and file identities re-verified and the slot mount checked
    read-write before the transport accept (which may block until the
    deadline); the requester's boot ID is learned from its proven hello, and
    the mount fence runs once more after the handshake. These are
    pre-connection observations: the probe service rechecks before the first
    read and after each reply (`ExtensionConnection.recheck`). Every failure
    after the generation was acquired unwinds socket, fence and generation.
    With `connection_ms`, the accepted connection's window starts at the
    transport accept, bounds the handshake and is carried as
    `ExtensionConnection.deadline`; without it the caller's deadline is the
    window.
    """

    if type(worker) is not WorkerListener or worker.closed:
        raise ListenerIntegrityError()
    if connection_ms is not None and not broker._exact_int(
        connection_ms, minimum=1, maximum=86_400_000
    ):
        raise ListenerIntegrityError()
    broker._require_extension_profile(worker.spec)
    root, spec = worker.root_spec, worker.spec
    generation = ipc_root.acquire_generation(root)
    fence = None
    codec = None
    connection: socket.socket | None = None
    try:
        if (
            generation.generation_id != worker.record.generation_id
            or generation.endpoint_identity != worker._generation.endpoint_identity
        ):
            raise ListenerIntegrityError()
        fence = ipc_root._retain_populated_generation(root, generation)
        record, readiness, socket_identity = _verify_record(generation, root, spec)
        if (
            record != worker.record
            or readiness != worker._readiness_identity
            or socket_identity != worker._socket_identity
        ):
            # a re-created readiness file with identical bytes is another inode
            raise ListenerIntegrityError()
        _extension_mount_fence(root, read_only=False)
        connection = worker._accept_transport(deadline)
        window = deadline if connection_ms is None else deadline.bounded(connection_ms)
        session = broker._extension_server_handshake(
            connection,
            spec,
            generation.secret,
            responder_boot_id=worker.record.responder_boot_id,
            deadline=window,
        )
        _extension_mount_fence(root, read_only=False)
        codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
        result = _extension_connection(
            connection=connection, session=session, codec=codec, generation=generation,
            fence=fence, record=record, root=root, spec=spec, read_only=False, peer=None,
            deadline=window,
        )
        connection = generation = fence = codec = None  # type: ignore[assignment]
        return result
    except BaseException as error:
        owned = (connection, codec, fence, generation)
        connection = codec = fence = generation = None
        for resource in owned:
            if resource is not None:
                try:
                    resource.close()
                except BaseException:  # noqa: BLE001, S110 - preserve primary
                    pass
        if isinstance(error, ipc_root.IpcRootError):
            raise ListenerIntegrityError() from None
        raise


def _connect_extension_authenticated(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    *,
    requester_boot_id: str,
    deadline: broker.Deadline,
) -> ExtensionConnection:
    """Requester side: verify readiness, fence the generation and the slot
    mount (read-only for control), connect to the exact socket inode with
    the kernel peer credentials retained, and complete the extension
    handshake. Every failure after readiness was verified unwinds; an
    `IpcRootError` from the readiness verification itself propagates as
    raised, as `connect_authenticated` does."""

    broker._require_extension_profile(spec)
    _validate_pair_channel(root, spec)
    verified = verify_listener(root, spec)
    fence = None
    codec = None
    connection: socket.socket | None = None
    try:
        fence = ipc_root._retain_populated_generation(root, verified.generation)
        _extension_mount_fence(root, read_only=True)
        connection, endpoint_identity, peer = broker.connect_verified(
            spec, local_service=spec.requester_service, deadline=deadline
        )
        if (
            endpoint_identity.device != verified.record.socket.device
            or endpoint_identity.inode != verified.record.socket.inode
            or endpoint_identity.uid != verified.record.socket.uid
            or endpoint_identity.gid != verified.record.socket.gid
            or endpoint_identity.mode != verified.record.socket.mode
        ):
            raise ListenerIntegrityError()
        session = broker._extension_client_handshake(
            connection,
            spec,
            verified.generation.secret,
            requester_boot_id=requester_boot_id,
            responder_boot_id=verified.record.responder_boot_id,
            deadline=deadline,
        )
        codec = broker.FrameCodec(spec, session, local_service=spec.requester_service)
        result = _extension_connection(
            connection=connection, session=session, codec=codec,
            generation=verified.generation, fence=fence, record=verified.record,
            root=root, spec=spec, read_only=True, peer=peer, deadline=deadline,
        )
        connection = fence = codec = None  # type: ignore[assignment]
        verified._closed = True  # the generation now belongs to the connection
        return result
    except BaseException as error:
        owned = (connection, fence, codec, verified)
        connection = fence = codec = verified = None
        for resource in owned:
            if resource is not None:
                try:
                    resource.close()
                except BaseException:  # noqa: BLE001, S110 - attempt all; preserve primary
                    pass
        if isinstance(error, ipc_root.IpcRootError):
            raise ListenerIntegrityError() from None
        raise
