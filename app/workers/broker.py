"""Bounded authenticated IPC primitives for isolated DeepTwin workers.

This module transports an already-authorized, already-budgeted request.  It does
not decide authority, consume a dispatch permit, launch workers, manage
containers, access the work store, or retry an uncertain operation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import stat
import struct
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from uuid import UUID

PROTOCOL_VERSION = "deeptwin-worker-ipc-v2"
MAX_FRAME_BYTES = 65_536
# extension-channel-profile-v1 (contracts/extension-worker-probe.md §1): the
# single source for the worker-private probe channel's protocol identity,
# message types and handshake packet cap; app/workers/extension_channel.py
# derives the rest from the deployment slot
EXTENSION_PROTOCOL_ID = "deeptwin-extension-worker-v1"
EXTENSION_REQUESTER_MESSAGE_TYPES = ("extension-artifact-v1", "extension-request-v1")
EXTENSION_RESPONDER_MESSAGE_TYPES = ("extension-artifact-v1", "extension-result-v1")
EXTENSION_HANDSHAKE_PACKET_BYTES = 4_096
AUTH_SECRET_BYTES = 32
AUTH_CHALLENGE_BYTES = 32
_PREFIX_BYTES = 4
_MAC_BYTES = 32
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*\Z")
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ENVELOPE_SCHEMA = "deeptwin-worker-envelope-v2"
_HANDSHAKE_SCHEMA = "deeptwin-worker-handshake-v2"
_DISPATCH_EFFECTS = frozenset(
    {"definitely_not_sent", "may_have_started", "outcome_unknown"}
)
_MAX_JSON_DEPTH = 32
_MAX_JSON_ITEMS = 10_000
_MAX_JSON_INTEGER = (1 << 63) - 1
_MAX_IDENTIFIER_CHARS = 64
_MAX_PAIR_ROOT_BYTES = 4_096


class BrokerError(RuntimeError):
    """Sanitized broker failure; details never include payloads, paths or secrets."""

    code = "broker_error"

    def __init__(self, *, dispatch_effect: str = "definitely_not_sent") -> None:
        if dispatch_effect not in _DISPATCH_EFFECTS:
            dispatch_effect = "outcome_unknown"
        self.dispatch_effect = dispatch_effect
        super().__init__(self.code)


class ChannelConfigurationError(BrokerError):
    code = "channel_configuration_invalid"


class EndpointViolation(BrokerError):
    code = "endpoint_boundary_violation"


class PeerCredentialError(BrokerError):
    code = "peer_credential_invalid"


class AuthenticationError(BrokerError):
    code = "mutual_authentication_failed"


class ProtocolViolation(BrokerError):
    code = "protocol_violation"


class BrokerBusy(BrokerError):
    code = "broker_busy"


class DeadlineExceeded(BrokerError):
    code = "deadline_exceeded"


class TransportClosed(BrokerError):
    code = "transport_closed"


class TransportUncertain(BrokerError):
    code = "transport_uncertain"


def _exact_int(value: object, *, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _identifier(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= _MAX_IDENTIFIER_CHARS
        and _IDENTIFIER.fullmatch(value) is not None
    )


def _validate_json_tree(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    items = 0
    while pending:
        item, depth = pending.pop()
        items += 1
        if items > _MAX_JSON_ITEMS or depth > _MAX_JSON_DEPTH:
            raise ProtocolViolation()
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if not -_MAX_JSON_INTEGER <= item <= _MAX_JSON_INTEGER:
                raise ProtocolViolation()
            continue
        if type(item) is str:
            encoded_item: bytes | None = None
            try:
                encoded_item = item.encode("utf-8")
            except UnicodeError:
                pass
            if encoded_item is None:
                raise ProtocolViolation()
            if len(encoded_item) > MAX_FRAME_BYTES:
                raise ProtocolViolation()
            continue
        if type(item) is list:
            pending.extend((child, depth + 1) for child in item)
            continue
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ProtocolViolation()
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
            continue
        raise ProtocolViolation()


def _canonical_json(value: object) -> bytes:
    _validate_json_tree(value)
    encoded: bytes | None = None
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeError):
        pass
    if encoded is None:
        raise ProtocolViolation()
    return encoded


def _reject_float(_: str) -> None:
    raise ProtocolViolation()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolViolation()
        result[key] = value
    return result


def _decode_canonical_json(raw: bytes) -> dict[str, object]:
    decoded = False
    value: object = None
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
        decoded = True
    except BrokerError:
        raise
    except (RecursionError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    if not decoded:
        raise ProtocolViolation()
    _validate_json_tree(value)
    if type(value) is not dict or _canonical_json(value) != raw:
        raise ProtocolViolation()
    return value


def _canonical_b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode_b64(value: object, *, exact_bytes: int | None = None) -> bytes:
    if type(value) is not str or len(value) > 4 * MAX_FRAME_BYTES:
        raise ProtocolViolation()
    decoded: bytes | None = None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        pass
    if decoded is None:
        raise ProtocolViolation()
    if _canonical_b64(decoded) != value or (
        exact_bytes is not None and len(decoded) != exact_bytes
    ):
        raise ProtocolViolation()
    return decoded


@dataclass(frozen=True, slots=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        if not _exact_int(self.pid, minimum=1, maximum=(1 << 31) - 1):
            raise ChannelConfigurationError()
        for value in (self.uid, self.gid):
            if not _exact_int(value, minimum=0, maximum=(1 << 32) - 1):
                raise ChannelConfigurationError()


@dataclass(frozen=True, slots=True)
class EndpointIdentity:
    device: int
    inode: int
    uid: int
    gid: int
    mode: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in (
            self.device, self.inode, self.uid, self.gid, self.mode
        )):
            raise ChannelConfigurationError()


@dataclass(frozen=True, slots=True)
class Deadline:
    end_monotonic: float

    def __post_init__(self) -> None:
        if type(self.end_monotonic) is not float or not (
            0.0 < self.end_monotonic < float("inf")
        ):
            raise ChannelConfigurationError()

    @classmethod
    def after_ms(cls, milliseconds: int) -> Deadline:
        if not _exact_int(milliseconds, minimum=1, maximum=86_400_000):
            raise ChannelConfigurationError()
        return cls(time.monotonic() + milliseconds / 1000.0)

    def remaining(self) -> float:
        return max(0.0, self.end_monotonic - time.monotonic())

    def require(self, *, dispatch_effect: str = "definitely_not_sent") -> float:
        remaining = self.remaining()
        if remaining <= 0.0:
            raise DeadlineExceeded(dispatch_effect=dispatch_effect)
        return remaining

    def bounded(self, milliseconds: int) -> Deadline:
        if not _exact_int(milliseconds, minimum=1, maximum=86_400_000):
            raise ChannelConfigurationError()
        return Deadline(min(self.end_monotonic, time.monotonic() + milliseconds / 1000.0))


def _validated_types(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise ChannelConfigurationError()
    if any(not _identifier(item) for item in value):
        raise ChannelConfigurationError()
    if tuple(sorted(set(value))) != value:
        raise ChannelConfigurationError()
    return value


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    channel_id: str
    requester_service: str
    responder_service: str
    request_direction: str
    protocol_id: str
    requester_uid: int
    requester_gid: int
    responder_uid: int
    responder_gid: int
    pair_gid: int
    pair_root: Path
    socket_name: str
    root_uid: int
    root_gid: int
    socket_uid: int
    socket_gid: int
    requester_message_types: tuple[str, ...]
    responder_message_types: tuple[str, ...]
    root_mode: int = 0o2710
    socket_mode: int = 0o660
    max_frame_bytes: int = MAX_FRAME_BYTES
    max_in_flight: int = 1
    max_queue_depth: int = 16
    max_operation_ms: int = 30_000

    def __post_init__(self) -> None:
        for value in (
            self.channel_id,
            self.requester_service,
            self.responder_service,
            self.request_direction,
            self.protocol_id,
        ):
            if not _identifier(value):
                raise ChannelConfigurationError()
        if self.requester_service == self.responder_service:
            raise ChannelConfigurationError()
        expected_direction = f"{self.requester_service}-to-{self.responder_service}"
        if self.request_direction != expected_direction:
            raise ChannelConfigurationError()
        for value in (
            self.requester_uid,
            self.requester_gid,
            self.responder_uid,
            self.responder_gid,
            self.pair_gid,
            self.root_uid,
            self.root_gid,
            self.socket_uid,
            self.socket_gid,
        ):
            if not _exact_int(value, minimum=0, maximum=(1 << 32) - 1):
                raise ChannelConfigurationError()
        if (
            self.requester_uid == 0
            or self.responder_uid == 0
            or self.requester_gid == 0
            or self.responder_gid == 0
            or self.pair_gid == 0
            or self.requester_uid == self.responder_uid
            or self.requester_gid == self.responder_gid
            or self.pair_gid in {self.requester_gid, self.responder_gid}
            or self.root_uid != self.responder_uid
            or self.socket_uid != self.responder_uid
            or self.root_gid != self.pair_gid
            or self.socket_gid != self.pair_gid
        ):
            raise ChannelConfigurationError()
        root = self.pair_root
        root_bytes: bytes | None = None
        try:
            root_bytes = os.fsencode(root)
        except (TypeError, UnicodeError):
            pass
        if root_bytes is None:
            raise ChannelConfigurationError()
        if (
            not isinstance(root, Path)
            or not root.is_absolute()
            or root.anchor != os.sep
            or ".." in root.parts
            or not 1 <= len(root_bytes) <= _MAX_PAIR_ROOT_BYTES
        ):
            raise ChannelConfigurationError()
        if (
            not _identifier(self.socket_name)
            or Path(self.socket_name).name != self.socket_name
            or "/" in self.socket_name
        ):
            raise ChannelConfigurationError()
        if self.root_mode != 0o2710 or self.socket_mode != 0o660:
            raise ChannelConfigurationError()
        if not _exact_int(self.max_frame_bytes, minimum=256, maximum=MAX_FRAME_BYTES):
            raise ChannelConfigurationError()
        if not _exact_int(self.max_in_flight, minimum=1, maximum=1):
            raise ChannelConfigurationError()
        if not _exact_int(self.max_queue_depth, minimum=0, maximum=1024):
            raise ChannelConfigurationError()
        if not _exact_int(self.max_operation_ms, minimum=1, maximum=86_400_000):
            raise ChannelConfigurationError()
        _validated_types(self.requester_message_types)
        _validated_types(self.responder_message_types)

    def allowed_types(self, sender_service: str) -> tuple[str, ...]:
        if sender_service == self.requester_service:
            return self.requester_message_types
        if sender_service == self.responder_service:
            return self.responder_message_types
        raise ProtocolViolation()


def _spec_binding(spec: ChannelSpec) -> dict[str, object]:
    """Return every immutable channel field covered by mutual authentication."""

    return {
        "schema_version": "deeptwin-worker-channel-spec-v1",
        "channel_id": spec.channel_id,
        "requester_service": spec.requester_service,
        "responder_service": spec.responder_service,
        "request_direction": spec.request_direction,
        "protocol_id": spec.protocol_id,
        "requester_uid": spec.requester_uid,
        "requester_gid": spec.requester_gid,
        "responder_uid": spec.responder_uid,
        "responder_gid": spec.responder_gid,
        "pair_gid": spec.pair_gid,
        "pair_root": str(spec.pair_root),
        "socket_name": spec.socket_name,
        "root_uid": spec.root_uid,
        "root_gid": spec.root_gid,
        "socket_uid": spec.socket_uid,
        "socket_gid": spec.socket_gid,
        "requester_message_types": list(spec.requester_message_types),
        "responder_message_types": list(spec.responder_message_types),
        "root_mode": spec.root_mode,
        "socket_mode": spec.socket_mode,
        "max_frame_bytes": spec.max_frame_bytes,
        "max_in_flight": spec.max_in_flight,
        "max_queue_depth": spec.max_queue_depth,
        "max_operation_ms": spec.max_operation_ms,
    }


def _spec_digest(spec: ChannelSpec) -> str:
    return hashlib.sha256(_canonical_json(_spec_binding(spec))).hexdigest()


_SESSION_CONSTRUCTION_TOKEN = object()


class BootSecret:
    __slots__ = ("__value",)

    def __init__(self, value: bytes) -> None:
        if type(value) is not bytes or len(value) != AUTH_SECRET_BYTES:
            raise ChannelConfigurationError()
        object.__setattr__(self, "_BootSecret__value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("BootSecret is immutable")

    @classmethod
    def generate(cls) -> BootSecret:
        return cls(secrets.token_bytes(AUTH_SECRET_BYTES))

    def __repr__(self) -> str:
        return "<BootSecret redacted>"

    def _material(self) -> bytes:
        return self.__value

    def __reduce__(self) -> object:
        raise TypeError("BootSecret is not serializable")

    def __copy__(self) -> object:
        raise TypeError("BootSecret is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("BootSecret is not copyable")


class AuthenticatedSession:
    __slots__ = (
        "__codec_claimed",
        "__codec_lock",
        "__session_key",
        "channel_spec_sha256",
        "connection_id",
        "local_service",
        "requester_boot_id",
        "responder_boot_id",
    )

    def __init__(
        self,
        connection_id: str,
        requester_boot_id: str,
        responder_boot_id: str,
        session_key: bytes,
        *,
        channel_spec_sha256: str,
        local_service: str,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _SESSION_CONSTRUCTION_TOKEN:
            raise AuthenticationError()
        if type(connection_id) is not str or not _SHA256.fullmatch(connection_id):
            raise AuthenticationError()
        if (
            type(requester_boot_id) is not str
            or _BOOT_ID.fullmatch(requester_boot_id) is None
            or type(responder_boot_id) is not str
            or _BOOT_ID.fullmatch(responder_boot_id) is None
            or requester_boot_id == responder_boot_id
        ):
            raise AuthenticationError()
        if type(session_key) is not bytes or len(session_key) != _MAC_BYTES:
            raise AuthenticationError()
        if (
            type(channel_spec_sha256) is not str
            or _SHA256.fullmatch(channel_spec_sha256) is None
            or not _identifier(local_service)
        ):
            raise AuthenticationError()
        object.__setattr__(self, "connection_id", connection_id)
        object.__setattr__(self, "requester_boot_id", requester_boot_id)
        object.__setattr__(self, "responder_boot_id", responder_boot_id)
        object.__setattr__(self, "channel_spec_sha256", channel_spec_sha256)
        object.__setattr__(self, "local_service", local_service)
        object.__setattr__(self, "_AuthenticatedSession__session_key", session_key)
        object.__setattr__(self, "_AuthenticatedSession__codec_claimed", False)
        object.__setattr__(self, "_AuthenticatedSession__codec_lock", threading.Lock())

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("AuthenticatedSession is immutable")

    def __repr__(self) -> str:
        return (
            f"<AuthenticatedSession connection_id={self.connection_id!r} "
            "session_key=redacted>"
        )

    def _material(self) -> bytes:
        return self.__session_key

    def _claim_codec(self, spec: ChannelSpec, local_service: str) -> None:
        if (
            local_service != self.local_service
            or not hmac.compare_digest(self.channel_spec_sha256, _spec_digest(spec))
        ):
            raise AuthenticationError()
        with self.__codec_lock:
            if self.__codec_claimed:
                raise ProtocolViolation()
            object.__setattr__(self, "_AuthenticatedSession__codec_claimed", True)

    def __reduce__(self) -> object:
        raise TypeError("AuthenticatedSession is not serializable")

    def __copy__(self) -> object:
        raise TypeError("AuthenticatedSession is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("AuthenticatedSession is not copyable")


@dataclass(frozen=True, slots=True)
class FrameEnvelope:
    schema_version: str
    protocol_version: str
    protocol_id: str
    channel_id: str
    requester_boot_id: str
    responder_boot_id: str
    connection_id: str
    sender: str
    receiver: str
    direction: str
    sequence: int
    message_id: str
    correlation_id: str | None
    message_type: str
    payload_bytes: int
    payload_sha256: str
    payload_b64: str
    mac: str


@dataclass(frozen=True, slots=True)
class ReceivedFrame:
    envelope: FrameEnvelope
    payload: bytes


def _endpoint_identity(info: os.stat_result) -> EndpointIdentity:
    return EndpointIdentity(
        device=info.st_dev,
        inode=info.st_ino,
        uid=info.st_uid,
        gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode),
    )


def _close_fd(fd: int) -> None:
    if fd < 0:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _open_root(spec: ChannelSpec) -> int:
    """Open every absolute path component without following a symlink."""

    # Pair members deliberately receive execute, not directory-listing, access.
    # Linux O_PATH retains an anchored inode without requiring read permission.
    flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_CLOEXEC | os.O_DIRECTORY
    if not hasattr(os, "O_NOFOLLOW"):
        raise EndpointViolation()
    flags |= os.O_NOFOLLOW
    current_fd = -1
    try:
        current_fd = os.open(os.sep, flags)
        for component in spec.pair_root.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=current_fd)
            previous = current_fd
            current_fd = next_fd
            _close_fd(previous)
        info = os.fstat(current_fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != spec.root_uid
            or info.st_gid != spec.root_gid
            or stat.S_IMODE(info.st_mode) != spec.root_mode
        ):
            raise EndpointViolation()
        result, current_fd = current_fd, -1
        return result
    except BaseException as error:
        owned, current_fd = current_fd, -1
        try:
            _close_fd(owned)
        except BaseException:  # noqa: BLE001, S110 - preserve root acquisition primary
            pass
        if not isinstance(error, OSError):
            raise
    # Keep private OS details out of both exception cause and context.
    raise EndpointViolation()


def _validate_endpoint_at(root_fd: int, spec: ChannelSpec) -> EndpointIdentity:
    info: os.stat_result | None = None
    try:
        info = os.stat(spec.socket_name, dir_fd=root_fd, follow_symlinks=False)
    except OSError:
        pass
    if info is None:
        raise EndpointViolation()
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != spec.socket_uid
        or info.st_gid != spec.socket_gid
        or stat.S_IMODE(info.st_mode) != spec.socket_mode
    ):
        raise EndpointViolation()
    return _endpoint_identity(info)


def validate_endpoint(spec: ChannelSpec) -> EndpointIdentity:
    """Validate an exact socket inode without following any symlink."""

    root_fd = _open_root(spec)
    try:
        return _validate_endpoint_at(root_fd, spec)
    finally:
        _close_fd(root_fd)


def _validate_socket(sock: socket.socket) -> None:
    if type(sock) is not socket.socket or sock.family != socket.AF_UNIX:
        raise EndpointViolation()
    socket_failed = False
    try:
        if sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
            raise EndpointViolation()
        sock.set_inheritable(False)
        if sock.get_inheritable():
            raise EndpointViolation()
    except OSError:
        socket_failed = True
    if socket_failed:
        raise EndpointViolation()


def _close_socket(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass


def peer_credentials(sock: socket.socket) -> PeerCredentials:
    """Read release-qualifying Linux credentials; no silent OS fallback exists."""

    _validate_socket(sock)
    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
        raise PeerCredentialError()
    size = struct.calcsize("3i")
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
        if type(raw) is not bytes or len(raw) != size:
            raise PeerCredentialError()
        pid, uid, gid = struct.unpack("3i", raw)
        return PeerCredentials(pid=pid, uid=uid, gid=gid)
    except BrokerError:
        raise
    except (OSError, struct.error, ValueError):
        pass
    raise PeerCredentialError()


def _expected_peer(spec: ChannelSpec, local_service: str) -> tuple[int, int]:
    if local_service == spec.requester_service:
        return spec.responder_uid, spec.responder_gid
    if local_service == spec.responder_service:
        return spec.requester_uid, spec.requester_gid
    raise PeerCredentialError()


def _verify_peer(sock: socket.socket, spec: ChannelSpec, local_service: str) -> PeerCredentials:
    credentials = peer_credentials(sock)
    expected_uid, expected_gid = _expected_peer(spec, local_service)
    if credentials.uid != expected_uid or credentials.gid != expected_gid:
        raise PeerCredentialError()
    return credentials


def connect_verified(
    spec: ChannelSpec,
    *,
    local_service: str,
    deadline: Deadline,
) -> tuple[socket.socket, EndpointIdentity, PeerCredentials]:
    """Connect through an anchored directory FD and bind Linux peer identity."""

    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
        raise PeerCredentialError()
    deadline = deadline.bounded(spec.max_operation_ms)
    root_fd = _open_root(spec)
    sock: socket.socket | None = None
    try:
        before = _validate_endpoint_at(root_fd, spec)
        proc_root = f"/proc/self/fd/{root_fd}"
        proc_info: os.stat_result | None = None
        root_info: os.stat_result | None = None
        try:
            proc_info = os.stat(proc_root, follow_symlinks=True)
            root_info = os.fstat(root_fd)
        except OSError:
            pass
        if proc_info is None or root_info is None:
            raise EndpointViolation()
        if (proc_info.st_dev, proc_info.st_ino) != (root_info.st_dev, root_info.st_ino):
            raise EndpointViolation()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        _validate_socket(sock)
        sock.settimeout(deadline.require())
        sock.connect(f"{proc_root}/{spec.socket_name}")
        after = _validate_endpoint_at(root_fd, spec)
        if before != after:
            raise EndpointViolation()
        credentials = _verify_peer(sock, spec, local_service)
        sock.settimeout(None)
        # Keep the socket locally owned until transient-root cleanup succeeds.
        owned_root, root_fd = root_fd, -1
        _close_fd(owned_root)
        result, sock = (sock, after, credentials), None
        return result
    except BaseException as error:
        owned_socket, sock = sock, None
        owned_root, root_fd = root_fd, -1
        try:
            _close_socket(owned_socket)
        except BaseException:  # noqa: BLE001, S110 - preserve connect primary
            pass
        try:
            _close_fd(owned_root)
        except BaseException:  # noqa: BLE001, S110 - attempt both; preserve primary
            pass
        if not isinstance(error, (OSError, TimeoutError)):
            raise
    raise TransportClosed()


def _send_exact(sock: socket.socket, raw: bytes, deadline: Deadline) -> None:
    offset = 0
    view = memoryview(raw)
    while offset < len(raw):
        effect = "definitely_not_sent" if offset == 0 else "may_have_started"
        remaining = deadline.require(dispatch_effect=effect)
        timeout_failed = False
        try:
            sock.settimeout(remaining)
        except OSError:
            timeout_failed = True
        if timeout_failed:
            if offset:
                raise TransportUncertain(dispatch_effect="may_have_started")
            raise TransportClosed(dispatch_effect="definitely_not_sent")
        send_failed = False
        sent = 0
        try:
            sent = sock.send(view[offset:])
        except (OSError, TimeoutError):
            send_failed = True
        if send_failed:
            raise TransportUncertain(dispatch_effect="may_have_started")
        if sent <= 0:
            raise TransportUncertain(dispatch_effect="may_have_started")
        offset += sent


def _read_exact(sock: socket.socket, size: int, deadline: Deadline) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        read_failed = False
        block = b""
        try:
            sock.settimeout(deadline.require(dispatch_effect="outcome_unknown"))
            block = sock.recv(size - len(chunks))
        except DeadlineExceeded:
            raise
        except ConnectionResetError:
            # the peer closed with our bytes unread: Linux reports ECONNRESET where
            # macOS reports EOF; both are the peer's close, the outcome still unknown
            block = b""
        except (OSError, TimeoutError):
            read_failed = True
        if read_failed:
            raise TransportUncertain(dispatch_effect="outcome_unknown")
        if not block:
            raise TransportClosed(dispatch_effect="outcome_unknown")
        chunks.extend(block)
    return bytes(chunks)


def write_packet(
    sock: socket.socket,
    value: Mapping[str, object],
    deadline: Deadline,
    *,
    max_frame_bytes: int = MAX_FRAME_BYTES,
) -> None:
    _validate_socket(sock)
    if not _exact_int(max_frame_bytes, minimum=1, maximum=MAX_FRAME_BYTES):
        raise ProtocolViolation()
    body = _canonical_json(dict(value))
    if not (1 <= len(body) <= max_frame_bytes <= MAX_FRAME_BYTES):
        raise ProtocolViolation()
    _send_exact(sock, struct.pack(">I", len(body)) + body, deadline)


def read_packet(
    sock: socket.socket,
    deadline: Deadline,
    *,
    max_frame_bytes: int = MAX_FRAME_BYTES,
) -> dict[str, object]:
    _validate_socket(sock)
    if not _exact_int(max_frame_bytes, minimum=1, maximum=MAX_FRAME_BYTES):
        raise ProtocolViolation(dispatch_effect="outcome_unknown")
    header = _read_exact(sock, _PREFIX_BYTES, deadline)
    (size,) = struct.unpack(">I", header)
    if not (1 <= size <= max_frame_bytes <= MAX_FRAME_BYTES):
        raise ProtocolViolation(dispatch_effect="outcome_unknown")
    return _decode_canonical_json(_read_exact(sock, size, deadline))


def _auth_context(
    spec: ChannelSpec,
    *,
    phase: str,
    requester_boot_id: str,
    responder_boot_id: str,
    requester_challenge: bytes,
    responder_challenge: bytes | None,
    role: str,
) -> bytes:
    value = {
        "domain": "deeptwin-worker-mutual-auth-v2",
        "phase": phase,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_id": spec.protocol_id,
        "channel_id": spec.channel_id,
        "requester": spec.requester_service,
        "responder": spec.responder_service,
        "direction": spec.request_direction,
        "channel_spec_sha256": _spec_digest(spec),
        "requester_boot_id": requester_boot_id,
        "responder_boot_id": responder_boot_id,
        "requester_challenge": _canonical_b64(requester_challenge),
        "responder_challenge": (
            None if responder_challenge is None else _canonical_b64(responder_challenge)
        ),
        "role": role,
    }
    return _canonical_json(value)


def _proof(secret: BootSecret, context: bytes) -> str:
    return hmac.new(secret._material(), context, hashlib.sha256).hexdigest()


def _session(
    secret: BootSecret,
    spec: ChannelSpec,
    requester_boot_id: str,
    responder_boot_id: str,
    requester_challenge: bytes,
    responder_challenge: bytes,
    *,
    local_service: str,
) -> AuthenticatedSession:
    context = _auth_context(
        spec,
        phase="session",
        requester_boot_id=requester_boot_id,
        responder_boot_id=responder_boot_id,
        requester_challenge=requester_challenge,
        responder_challenge=responder_challenge,
        role="shared",
    )
    connection_id = hashlib.sha256(context).hexdigest()
    key = hmac.new(secret._material(), b"session-key\x00" + context, hashlib.sha256).digest()
    return AuthenticatedSession(
        connection_id,
        requester_boot_id,
        responder_boot_id,
        key,
        channel_spec_sha256=_spec_digest(spec),
        local_service=local_service,
        _construction_token=_SESSION_CONSTRUCTION_TOKEN,
    )


def _hello_base(
    spec: ChannelSpec,
    phase: str,
    requester_boot_id: str,
    responder_boot_id: str,
) -> dict[str, object]:
    return {
        "schema_version": _HANDSHAKE_SCHEMA,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_id": spec.protocol_id,
        "channel_id": spec.channel_id,
        "requester": spec.requester_service,
        "responder": spec.responder_service,
        "direction": spec.request_direction,
        "requester_boot_id": requester_boot_id,
        "responder_boot_id": responder_boot_id,
        "phase": phase,
    }


def _require_boot_id(boot_id: object) -> str:
    if type(boot_id) is not str or _BOOT_ID.fullmatch(boot_id) is None:
        raise AuthenticationError()
    return boot_id


def _exact_handshake(value: object, expected: Mapping[str, object]) -> None:
    if type(value) is not dict or set(value) != set(expected):
        raise AuthenticationError(dispatch_effect="outcome_unknown")
    actual_proof = value.get("proof")
    expected_proof = expected.get("proof")
    if (
        type(actual_proof) is not str
        or type(expected_proof) is not str
        or not hmac.compare_digest(actual_proof, expected_proof)
    ):
        raise AuthenticationError(dispatch_effect="outcome_unknown")
    if any(value[key] != item for key, item in expected.items() if key != "proof"):
        raise AuthenticationError(dispatch_effect="outcome_unknown")


def _client_handshake_impl(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    *,
    requester_boot_id: str,
    responder_boot_id: str,
    deadline: Deadline,
    challenge_factory: Callable[[int], bytes] | None = None,
    verify_peer: bool = True,
    max_packet_bytes: int | None = None,
) -> AuthenticatedSession:
    deadline = deadline.bounded(spec.max_operation_ms)
    packet_bytes = spec.max_frame_bytes if max_packet_bytes is None else max_packet_bytes
    _validate_socket(sock)
    requester_boot_id = _require_boot_id(requester_boot_id)
    responder_boot_id = _require_boot_id(responder_boot_id)
    if requester_boot_id == responder_boot_id:
        raise AuthenticationError()
    if verify_peer:
        _verify_peer(sock, spec, spec.requester_service)
    if challenge_factory is None:
        challenge_factory = secrets.token_bytes
    requester = challenge_factory(AUTH_CHALLENGE_BYTES)
    if type(requester) is not bytes or len(requester) != AUTH_CHALLENGE_BYTES:
        raise AuthenticationError()
    hello = _hello_base(
        spec, "requester-hello", requester_boot_id, responder_boot_id
    )
    hello["requester_challenge"] = _canonical_b64(requester)
    hello["proof"] = _proof(secret, _auth_context(
        spec,
        phase="requester-hello",
        requester_boot_id=requester_boot_id,
        responder_boot_id=responder_boot_id,
        requester_challenge=requester,
        responder_challenge=None,
        role="requester",
    ))
    write_packet(sock, hello, deadline, max_frame_bytes=packet_bytes)
    response = read_packet(sock, deadline, max_frame_bytes=packet_bytes)
    responder = _decode_b64(response.get("responder_challenge"), exact_bytes=AUTH_CHALLENGE_BYTES)
    expected = _hello_base(
        spec, "responder-hello", requester_boot_id, responder_boot_id
    )
    expected.update({
        "requester_challenge": _canonical_b64(requester),
        "responder_challenge": _canonical_b64(responder),
        "proof": _proof(secret, _auth_context(
            spec,
            phase="responder-hello",
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            requester_challenge=requester,
            responder_challenge=responder,
            role="responder",
        )),
    })
    _exact_handshake(response, expected)
    finish = _hello_base(
        spec, "requester-finish", requester_boot_id, responder_boot_id
    )
    finish.update({
        "requester_challenge": _canonical_b64(requester),
        "responder_challenge": _canonical_b64(responder),
        "proof": _proof(secret, _auth_context(
            spec,
            phase="requester-finish",
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            requester_challenge=requester,
            responder_challenge=responder,
            role="requester",
        )),
    })
    write_packet(sock, finish, deadline, max_frame_bytes=packet_bytes)
    acknowledgement = read_packet(sock, deadline, max_frame_bytes=packet_bytes)
    expected_acknowledgement = _hello_base(
        spec, "responder-finish", requester_boot_id, responder_boot_id
    )
    expected_acknowledgement.update({
        "requester_challenge": _canonical_b64(requester),
        "responder_challenge": _canonical_b64(responder),
        "proof": _proof(secret, _auth_context(
            spec,
            phase="responder-finish",
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            requester_challenge=requester,
            responder_challenge=responder,
            role="responder",
        )),
    })
    _exact_handshake(acknowledgement, expected_acknowledgement)
    return _session(
        secret,
        spec,
        requester_boot_id,
        responder_boot_id,
        requester,
        responder,
        local_service=spec.requester_service,
    )


def _server_handshake_impl(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    *,
    requester_boot_id: str,
    responder_boot_id: str,
    deadline: Deadline,
    challenge_factory: Callable[[int], bytes] | None = None,
    verify_peer: bool = True,
) -> AuthenticatedSession:
    deadline = deadline.bounded(spec.max_operation_ms)
    _validate_socket(sock)
    requester_boot_id = _require_boot_id(requester_boot_id)
    responder_boot_id = _require_boot_id(responder_boot_id)
    if requester_boot_id == responder_boot_id:
        raise AuthenticationError()
    if verify_peer:
        _verify_peer(sock, spec, spec.responder_service)
    if challenge_factory is None:
        challenge_factory = secrets.token_bytes
    hello = read_packet(sock, deadline, max_frame_bytes=spec.max_frame_bytes)
    return _server_continue(
        sock,
        spec,
        secret,
        hello,
        requester_boot_id=requester_boot_id,
        responder_boot_id=responder_boot_id,
        deadline=deadline,
        challenge_factory=challenge_factory,
        packet_bytes=spec.max_frame_bytes,
    )


def _server_continue(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    hello: object,
    *,
    requester_boot_id: str,
    responder_boot_id: str,
    deadline: Deadline,
    challenge_factory: Callable[[int], bytes],
    packet_bytes: int,
) -> AuthenticatedSession:
    """The one responder continuation after a hello was read: verify the
    complete expected hello (proof over both boot IDs and the fresh requester
    challenge), issue a fresh responder challenge, verify the finish and
    mint the session. Shared by the exact-expected-requester wrapper and the
    extension wrapper that learned the requester ID from the hello itself."""

    if type(hello) is not dict:
        raise AuthenticationError(dispatch_effect="outcome_unknown")
    requester = _decode_b64(hello.get("requester_challenge"), exact_bytes=AUTH_CHALLENGE_BYTES)
    expected = _hello_base(
        spec, "requester-hello", requester_boot_id, responder_boot_id
    )
    expected.update({
        "requester_challenge": _canonical_b64(requester),
        "proof": _proof(secret, _auth_context(
            spec,
            phase="requester-hello",
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            requester_challenge=requester,
            responder_challenge=None,
            role="requester",
        )),
    })
    _exact_handshake(hello, expected)
    responder = challenge_factory(AUTH_CHALLENGE_BYTES)
    if type(responder) is not bytes or len(responder) != AUTH_CHALLENGE_BYTES:
        raise AuthenticationError()
    response = _hello_base(
        spec, "responder-hello", requester_boot_id, responder_boot_id
    )
    response.update({
        "requester_challenge": _canonical_b64(requester),
        "responder_challenge": _canonical_b64(responder),
        "proof": _proof(secret, _auth_context(
            spec,
            phase="responder-hello",
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            requester_challenge=requester,
            responder_challenge=responder,
            role="responder",
        )),
    })
    write_packet(sock, response, deadline, max_frame_bytes=packet_bytes)
    finish = read_packet(sock, deadline, max_frame_bytes=packet_bytes)
    expected_finish = _hello_base(
        spec, "requester-finish", requester_boot_id, responder_boot_id
    )
    expected_finish.update({
        "requester_challenge": _canonical_b64(requester),
        "responder_challenge": _canonical_b64(responder),
        "proof": _proof(secret, _auth_context(
            spec,
            phase="requester-finish",
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            requester_challenge=requester,
            responder_challenge=responder,
            role="requester",
        )),
    })
    _exact_handshake(finish, expected_finish)
    acknowledgement = _hello_base(
        spec, "responder-finish", requester_boot_id, responder_boot_id
    )
    acknowledgement.update({
        "requester_challenge": _canonical_b64(requester),
        "responder_challenge": _canonical_b64(responder),
        "proof": _proof(secret, _auth_context(
            spec,
            phase="responder-finish",
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            requester_challenge=requester,
            responder_challenge=responder,
            role="responder",
        )),
    })
    write_packet(sock, acknowledgement, deadline, max_frame_bytes=packet_bytes)
    return _session(
        secret,
        spec,
        requester_boot_id,
        responder_boot_id,
        requester,
        responder,
        local_service=spec.responder_service,
    )


def client_handshake(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    *,
    requester_boot_id: str,
    responder_boot_id: str,
    deadline: Deadline,
) -> AuthenticatedSession:
    failure: type[BrokerError] | None = None
    try:
        return _client_handshake_impl(
            sock,
            spec,
            secret,
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            deadline=deadline,
            verify_peer=True,
        )
    except BrokerError as error:
        failure = type(error)
    except BaseException:
        _close_socket(sock)
        raise
    _close_socket(sock)
    if failure is None:
        raise AuthenticationError()
    raise failure(dispatch_effect="definitely_not_sent")


def server_handshake(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    *,
    requester_boot_id: str,
    responder_boot_id: str,
    deadline: Deadline,
) -> AuthenticatedSession:
    failure: type[BrokerError] | None = None
    try:
        return _server_handshake_impl(
            sock,
            spec,
            secret,
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            deadline=deadline,
            verify_peer=True,
        )
    except BrokerError as error:
        failure = type(error)
    except BaseException:
        _close_socket(sock)
        raise
    _close_socket(sock)
    if failure is None:
        raise AuthenticationError()
    raise failure(dispatch_effect="definitely_not_sent")


def _uuid(value: object, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if type(value) is not str:
        raise ProtocolViolation()
    parsed: UUID | None = None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        pass
    if parsed is None:
        raise ProtocolViolation()
    if str(parsed) != value:
        raise ProtocolViolation()
    return value


def _frame_unsigned(
    spec: ChannelSpec,
    session: AuthenticatedSession,
    *,
    sender: str,
    receiver: str,
    sequence: int,
    message_id: str,
    correlation_id: str | None,
    message_type: str,
    payload: bytes,
) -> dict[str, object]:
    if (
        sender not in {spec.requester_service, spec.responder_service}
        or receiver not in {spec.requester_service, spec.responder_service}
        or sender == receiver
        or {sender, receiver} != {spec.requester_service, spec.responder_service}
        or message_type not in spec.allowed_types(sender)
        or not _exact_int(sequence, minimum=1, maximum=(1 << 63) - 1)
        or type(payload) is not bytes
    ):
        raise ProtocolViolation()
    _uuid(message_id)
    _uuid(correlation_id, optional=True)
    encoded = _canonical_b64(payload)
    value: dict[str, object] = {
        "schema_version": _ENVELOPE_SCHEMA,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_id": spec.protocol_id,
        "channel_id": spec.channel_id,
        "requester_boot_id": session.requester_boot_id,
        "responder_boot_id": session.responder_boot_id,
        "connection_id": session.connection_id,
        "sender": sender,
        "receiver": receiver,
        "direction": f"{sender}-to-{receiver}",
        "sequence": sequence,
        "message_id": message_id,
        "correlation_id": correlation_id,
        "message_type": message_type,
        "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_b64": encoded,
    }
    return value


def _encode_application_frame(
    spec: ChannelSpec,
    session: AuthenticatedSession,
    *,
    sender: str,
    receiver: str,
    sequence: int,
    message_id: str,
    correlation_id: str | None,
    message_type: str,
    payload: bytes,
) -> bytes:
    unsigned = _frame_unsigned(
        spec,
        session,
        sender=sender,
        receiver=receiver,
        sequence=sequence,
        message_id=message_id,
        correlation_id=correlation_id,
        message_type=message_type,
        payload=payload,
    )
    mac = hmac.new(
        session._material(), b"frame\x00" + _canonical_json(unsigned), hashlib.sha256
    ).hexdigest()
    encoded = _canonical_json({**unsigned, "mac": mac})
    if not (1 <= len(encoded) <= spec.max_frame_bytes):
        raise ProtocolViolation()
    return encoded


def _decode_application_frame(
    spec: ChannelSpec,
    session: AuthenticatedSession,
    raw: bytes,
    *,
    expected_sender: str,
    expected_sequence: int,
) -> ReceivedFrame:
    try:
        if type(raw) is not bytes or not (1 <= len(raw) <= spec.max_frame_bytes):
            raise ProtocolViolation(dispatch_effect="outcome_unknown")
        value = _decode_canonical_json(raw)
        expected_keys = {
            "schema_version", "protocol_version", "protocol_id", "channel_id",
            "requester_boot_id", "responder_boot_id", "connection_id", "sender",
            "receiver", "direction",
            "sequence", "message_id", "correlation_id", "message_type",
            "payload_bytes", "payload_sha256", "payload_b64", "mac",
        }
        if set(value) != expected_keys:
            raise ProtocolViolation(dispatch_effect="outcome_unknown")
        mac = value.pop("mac")
        if type(mac) is not str or _SHA256.fullmatch(mac) is None:
            raise ProtocolViolation(dispatch_effect="outcome_unknown")
        expected_mac = hmac.new(
            session._material(), b"frame\x00" + _canonical_json(value), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(mac, expected_mac):
            raise ProtocolViolation(dispatch_effect="outcome_unknown")
        sender = value["sender"]
        receiver = value["receiver"]
        if sender != expected_sender or (
            expected_sender == spec.requester_service
            and receiver != spec.responder_service
        ) or (
            expected_sender == spec.responder_service
            and receiver != spec.requester_service
        ):
            raise ProtocolViolation(dispatch_effect="outcome_unknown")
        payload = _decode_b64(value["payload_b64"])
        if (
            value["schema_version"] != _ENVELOPE_SCHEMA
            or value["protocol_version"] != PROTOCOL_VERSION
            or value["protocol_id"] != spec.protocol_id
            or value["channel_id"] != spec.channel_id
            or value["requester_boot_id"] != session.requester_boot_id
            or value["responder_boot_id"] != session.responder_boot_id
            or value["connection_id"] != session.connection_id
            or value["direction"] != f"{sender}-to-{receiver}"
            or not _exact_int(
                value["sequence"], minimum=1, maximum=(1 << 63) - 1
            )
            or value["sequence"] != expected_sequence
            or value["message_type"] not in spec.allowed_types(str(sender))
            or type(value["payload_bytes"]) is not int
            or value["payload_bytes"] != len(payload)
            or type(value["payload_sha256"]) is not str
            or not hmac.compare_digest(
                value["payload_sha256"], hashlib.sha256(payload).hexdigest()
            )
        ):
            raise ProtocolViolation(dispatch_effect="outcome_unknown")
        _uuid(value["message_id"])
        _uuid(value["correlation_id"], optional=True)
        envelope = FrameEnvelope(mac=mac, **value)  # type: ignore[arg-type]
        return ReceivedFrame(envelope=envelope, payload=payload)
    except BrokerError:
        raise
    except (KeyError, TypeError, ValueError):
        pass
    raise ProtocolViolation(dispatch_effect="outcome_unknown")


class FrameCodec:
    """Own both sequence counters so callers cannot opt out of replay rejection."""

    __slots__ = (
        "_closed",
        "_lock",
        "_next_receive",
        "_next_send",
        "_session",
        "_spec",
        "local_service",
    )

    def __init__(
        self,
        spec: ChannelSpec,
        session: AuthenticatedSession,
        *,
        local_service: str,
    ) -> None:
        if local_service not in {spec.requester_service, spec.responder_service}:
            raise ChannelConfigurationError()
        session._claim_codec(spec, local_service)
        object.__setattr__(self, "_spec", spec)
        object.__setattr__(self, "_session", session)
        object.__setattr__(self, "local_service", local_service)
        object.__setattr__(self, "_next_send", 1)
        object.__setattr__(self, "_next_receive", 1)
        object.__setattr__(self, "_closed", False)
        object.__setattr__(self, "_lock", threading.RLock())

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("FrameCodec state is internally managed")

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def next_send_sequence(self) -> int:
        with self._lock:
            return self._next_send

    @property
    def next_receive_sequence(self) -> int:
        with self._lock:
            return self._next_receive

    def close(self) -> None:
        with self._lock:
            object.__setattr__(self, "_closed", True)

    def __copy__(self) -> object:
        raise TypeError("FrameCodec is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("FrameCodec is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("FrameCodec is not serializable")

    def encode(
        self,
        *,
        message_id: str,
        correlation_id: str | None,
        message_type: str,
        payload: bytes,
    ) -> bytes:
        with self._lock:
            if self._closed:
                raise TransportClosed()
            receiver = (
                self._spec.responder_service
                if self.local_service == self._spec.requester_service
                else self._spec.requester_service
            )
            raw = _encode_application_frame(
                self._spec,
                self._session,
                sender=self.local_service,
                receiver=receiver,
                sequence=self._next_send,
                message_id=message_id,
                correlation_id=correlation_id,
                message_type=message_type,
                payload=payload,
            )
            object.__setattr__(self, "_next_send", self._next_send + 1)
            return raw

    def write(
        self,
        sock: socket.socket,
        *,
        message_id: str,
        correlation_id: str | None,
        message_type: str,
        payload: bytes,
        deadline: Deadline,
    ) -> None:
        """Encode and wire one frame without exposing private serialization hooks."""

        with self._lock:
            if self._closed:
                raise TransportClosed()
            try:
                raw = _encode_application_frame(
                    self._spec,
                    self._session,
                    sender=self.local_service,
                    receiver=(
                        self._spec.responder_service
                        if self.local_service == self._spec.requester_service
                        else self._spec.requester_service
                    ),
                    sequence=self._next_send,
                    message_id=message_id,
                    correlation_id=correlation_id,
                    message_type=message_type,
                    payload=payload,
                )
                _validate_socket(sock)
                _send_exact(sock, struct.pack(">I", len(raw)) + raw, deadline)
            except BaseException:
                object.__setattr__(self, "_closed", True)
                raise
            object.__setattr__(self, "_next_send", self._next_send + 1)

    def read(self, sock: socket.socket, *, deadline: Deadline) -> ReceivedFrame:
        """Read and authenticate one wire frame, latching closed on any failure."""

        with self._lock:
            if self._closed:
                raise TransportClosed(dispatch_effect="outcome_unknown")
            try:
                _validate_socket(sock)
                header = _read_exact(sock, _PREFIX_BYTES, deadline)
                (size,) = struct.unpack(">I", header)
                if not 1 <= size <= self._spec.max_frame_bytes:
                    raise ProtocolViolation(dispatch_effect="outcome_unknown")
                raw = _read_exact(sock, size, deadline)
                frame = _decode_application_frame(
                    self._spec,
                    self._session,
                    raw,
                    expected_sender=(
                        self._spec.responder_service
                        if self.local_service == self._spec.requester_service
                        else self._spec.requester_service
                    ),
                    expected_sequence=self._next_receive,
                )
            except BaseException:
                object.__setattr__(self, "_closed", True)
                raise
            object.__setattr__(self, "_next_receive", self._next_receive + 1)
            return frame

    def decode(self, raw: bytes) -> ReceivedFrame:
        with self._lock:
            if self._closed:
                raise TransportClosed(dispatch_effect="outcome_unknown")
            sender = (
                self._spec.responder_service
                if self.local_service == self._spec.requester_service
                else self._spec.requester_service
            )
            try:
                frame = _decode_application_frame(
                    self._spec,
                    self._session,
                    raw,
                    expected_sender=sender,
                    expected_sequence=self._next_receive,
                )
            except BrokerError:
                object.__setattr__(self, "_closed", True)
                raise
            object.__setattr__(self, "_next_receive", self._next_receive + 1)
            return frame


class AdmissionLease:
    __slots__ = ("_active", "_gate", "_token")

    def __init__(self, gate: AdmissionGate, token: object) -> None:
        self._gate = gate
        self._token = token
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def release(self) -> None:
        if not self._active:
            raise ProtocolViolation()
        self._gate._release(self._token)
        self._active = False

    def __enter__(self) -> Self:
        if not self._active:
            raise ProtocolViolation()
        return self

    def __exit__(self, *_: object) -> None:
        if self._active:
            self.release()


class AdmissionGate:
    """FIFO, bounded, process-local admission before any transport bytes exist."""

    __slots__ = ("_active", "_condition", "_max_queue_depth", "_queue")

    def __init__(self, *, max_queue_depth: int) -> None:
        if not _exact_int(max_queue_depth, minimum=0, maximum=1024):
            raise ChannelConfigurationError()
        self._condition = threading.Condition()
        self._active: object | None = None
        self._queue: deque[object] = deque()
        self._max_queue_depth = max_queue_depth

    @property
    def queued(self) -> int:
        with self._condition:
            return len(self._queue)

    @property
    def in_flight(self) -> int:
        with self._condition:
            return int(self._active is not None)

    def acquire(self, deadline: Deadline) -> AdmissionLease:
        token = object()
        lease = AdmissionLease(self, token)
        with self._condition:
            deadline.require()
            if self._active is None and not self._queue:
                self._active = token
                return lease
            if len(self._queue) >= self._max_queue_depth:
                raise BrokerBusy()
            self._queue.append(token)
            admitted = False
            try:
                while True:
                    remaining = deadline.remaining()
                    if remaining <= 0.0:
                        raise DeadlineExceeded()
                    self._condition.wait(remaining)
                    if (
                        self._active is None
                        and self._queue
                        and self._queue[0] is token
                    ):
                        if deadline.remaining() <= 0.0:
                            raise DeadlineExceeded()
                        self._queue.popleft()
                        self._active = token
                        admitted = True
                        return lease
            finally:
                if not admitted:
                    try:
                        self._queue.remove(token)
                    except ValueError:
                        pass
                    self._condition.notify_all()

    def _release(self, token: object) -> None:
        with self._condition:
            if self._active is not token:
                raise ProtocolViolation()
            self._active = None
            self._condition.notify_all()


def _require_extension_profile(spec: ChannelSpec) -> None:
    """The whole extension-channel-profile-v1: protocol identity, message
    types and every bound the contract fixes (§1), not only the frame cap."""

    if (
        type(spec) is not ChannelSpec
        or spec.protocol_id != EXTENSION_PROTOCOL_ID
        or spec.requester_message_types != EXTENSION_REQUESTER_MESSAGE_TYPES
        or spec.responder_message_types != EXTENSION_RESPONDER_MESSAGE_TYPES
        or spec.max_frame_bytes != MAX_FRAME_BYTES
        or spec.max_in_flight != 1
        or spec.max_queue_depth != 16
        or spec.max_operation_ms != 30_000
    ):
        raise ChannelConfigurationError()


def _extension_server_handshake_impl(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    *,
    responder_boot_id: str,
    deadline: Deadline,
    challenge_factory: Callable[[int], bytes] | None = None,
    verify_peer: bool = True,
) -> AuthenticatedSession:
    """Responder side of the worker-private probe handshake: the requester's
    boot ID is read from the actual bounded hello, never known a priori, and
    proven by the same HMAC continuation; packets are capped at 4096 B."""

    _require_extension_profile(spec)
    deadline = deadline.bounded(spec.max_operation_ms)
    _validate_socket(sock)
    responder_boot_id = _require_boot_id(responder_boot_id)
    if verify_peer:
        _verify_peer(sock, spec, spec.responder_service)
    if challenge_factory is None:
        challenge_factory = secrets.token_bytes
    hello = read_packet(sock, deadline, max_frame_bytes=EXTENSION_HANDSHAKE_PACKET_BYTES)
    # once the hello was read every rejection is an unknown-outcome effect,
    # exactly as the exact-expected-requester path classifies the same failures
    try:
        requester_boot_id = _require_boot_id(hello.get("requester_boot_id"))
    except AuthenticationError:
        raise AuthenticationError(dispatch_effect="outcome_unknown") from None
    if requester_boot_id == responder_boot_id:
        raise AuthenticationError(dispatch_effect="outcome_unknown")
    return _server_continue(
        sock,
        spec,
        secret,
        hello,
        requester_boot_id=requester_boot_id,
        responder_boot_id=responder_boot_id,
        deadline=deadline,
        challenge_factory=challenge_factory,
        packet_bytes=EXTENSION_HANDSHAKE_PACKET_BYTES,
    )


def _extension_server_handshake(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    *,
    responder_boot_id: str,
    deadline: Deadline,
) -> AuthenticatedSession:
    """Seamless responder wrapper. Unlike the public `server_handshake`, it
    does not close the socket or normalise dispatch effects on failure: the
    private extension listener (slice 2c) owns the accepted socket and its
    cleanup on every failure, and reads the effect class as raised."""

    return _extension_server_handshake_impl(
        sock, spec, secret, responder_boot_id=responder_boot_id, deadline=deadline
    )


def _extension_client_handshake_impl(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    *,
    requester_boot_id: str,
    responder_boot_id: str,
    deadline: Deadline,
    challenge_factory: Callable[[int], bytes] | None = None,
    verify_peer: bool = True,
) -> AuthenticatedSession:
    _require_extension_profile(spec)
    return _client_handshake_impl(
        sock,
        spec,
        secret,
        requester_boot_id=requester_boot_id,
        responder_boot_id=responder_boot_id,
        deadline=deadline,
        challenge_factory=challenge_factory,
        verify_peer=verify_peer,
        max_packet_bytes=EXTENSION_HANDSHAKE_PACKET_BYTES,
    )


def _extension_client_handshake(
    sock: socket.socket,
    spec: ChannelSpec,
    secret: BootSecret,
    *,
    requester_boot_id: str,
    responder_boot_id: str,
    deadline: Deadline,
) -> AuthenticatedSession:
    """Seamless requester wrapper; as with the responder wrapper, the private
    extension connector (slice 2c) owns the socket and its cleanup on every
    failure and reads the effect class as raised."""

    return _extension_client_handshake_impl(
        sock,
        spec,
        secret,
        requester_boot_id=requester_boot_id,
        responder_boot_id=responder_boot_id,
        deadline=deadline,
    )
