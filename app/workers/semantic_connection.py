"""Private raw/owned frame adapters for the semantic worker dialogue.

This module adds no public transport or authority surface.  The owned adapter
accepts only the exact listener owner, retains it through every frame, and
fences publication through explicit checkpoints.  The raw adapter preserves
the established direct test seam while sharing the semantic dialogue engine.
"""

from __future__ import annotations

import select
import socket
import struct

from ..extensions.provider_semantic_contracts import ProviderSemanticError
from . import broker, listener

_OWNED_CODES = frozenset(
    {
        "owned_connection_unavailable",
        "owned_connection_cleanup_failed",
        "owned_connection_cleanup_failed_after_control_observation",
    }
)


class _OwnedConnectionError(ProviderSemanticError):
    """Sanitized local owned-connection failure; never a wire value."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if code not in _OWNED_CODES:
            raise ValueError("invalid owned connection error code")
        self.code = code
        super().__init__(code)

    @property
    def cleanup_failure(self) -> bool:
        return self.code != "owned_connection_unavailable"


def _effective_deadline(
    requested: broker.Deadline, retained: broker.Deadline
) -> broker.Deadline:
    if type(requested) is not broker.Deadline or type(retained) is not broker.Deadline:
        raise ProviderSemanticError("owned connection deadline is invalid")
    return broker.Deadline(
        min(requested.end_monotonic, retained.end_monotonic)
    )


class _RawSemanticConnection:
    """Compatibility adapter for the existing socket/codec entry signatures."""

    __slots__ = ("_closed", "_codec", "_owns", "_socket", "deadline", "session")

    def __init__(
        self,
        sock: socket.socket,
        codec: broker.FrameCodec,
        deadline: broker.Deadline,
        *,
        owns: bool,
    ) -> None:
        if type(codec) is not broker.FrameCodec or type(deadline) is not broker.Deadline:
            raise ProviderSemanticError("authenticated worker transport required")
        broker._validate_socket(sock)
        self._socket = sock
        self._codec = codec
        self.deadline = deadline
        self.session = codec._session
        self._owns = owns
        self._closed = False

    @property
    def raw_socket(self) -> socket.socket:
        return self._socket

    @property
    def raw_codec(self) -> broker.FrameCodec:
        return self._codec

    def checkpoint(self) -> None:
        self.deadline.require(dispatch_effect="outcome_unknown")

    def write(self, **values) -> None:
        supplied = values.pop("deadline", None)
        if supplied is not None and type(supplied) is not broker.Deadline:
            raise ProviderSemanticError("semantic frame deadline is invalid")
        self.checkpoint()
        self._codec.write(self._socket, deadline=self.deadline, **values)
        self.checkpoint()

    def read(self, *, deadline: broker.Deadline | None = None):
        del deadline
        self.checkpoint()
        frame = self._codec.read(self._socket, deadline=self.deadline)
        self.checkpoint()
        return frame

    def read_duplex(self):
        """Bounded raw read that leaves the codec lock free during socket waits."""

        self.checkpoint()

        def read_exact(size: int) -> bytes:
            value = bytearray()
            while len(value) < size:
                remaining = self.deadline.require(
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
            prefix = read_exact(4)
            (size,) = struct.unpack(">I", prefix)
            if not 1 <= size <= self._codec._spec.max_frame_bytes:
                raise broker.ProtocolViolation(dispatch_effect="outcome_unknown")
            frame = self._codec.decode(read_exact(size))
            self.checkpoint()
            return frame
        except BaseException:
            self._codec.close()
            raise

    def close(self, *, after_control_observation: bool = False) -> None:
        del after_control_observation
        if self._closed or not self._owns:
            return
        self._closed = True
        first_error = None
        try:
            self._codec.close()
        except BaseException as error:
            first_error = error
        try:
            self._socket.close()
        except BaseException as error:
            if first_error is None:
                first_error = error
        if first_error is not None:
            raise first_error


class _OwnedSemanticConnection:
    """Strongly retain and fence one exact ExtensionConnection owner."""

    __slots__ = ("_closed", "_owner", "deadline", "session")

    def __init__(
        self, owner: listener.ExtensionConnection, deadline: broker.Deadline
    ) -> None:
        if type(owner) is not listener.ExtensionConnection:
            raise ProviderSemanticError("exact owned extension connection required")
        self._owner = owner
        self.deadline = _effective_deadline(deadline, owner.deadline)
        self.session = owner.session
        self._closed = False

    @property
    def owner(self) -> listener.ExtensionConnection:
        return self._owner

    def checkpoint(self) -> None:
        try:
            self.deadline.require(dispatch_effect="outcome_unknown")
            self._owner.recheck()
            self.deadline.require(dispatch_effect="outcome_unknown")
        except listener.ListenerError:
            raise _OwnedConnectionError("owned_connection_unavailable") from None

    def write(self, **values) -> None:
        supplied = values.pop("deadline", None)
        if supplied is not None and type(supplied) is not broker.Deadline:
            raise ProviderSemanticError("semantic frame deadline is invalid")
        self.checkpoint()
        try:
            self._owner.write(deadline=self.deadline, **values)
        except listener.ListenerError:
            raise _OwnedConnectionError("owned_connection_unavailable") from None
        self.checkpoint()

    def read(self, *, deadline: broker.Deadline | None = None):
        del deadline
        self.checkpoint()
        try:
            frame = self._owner.read_duplex(deadline=self.deadline)
        except listener.ListenerError:
            raise _OwnedConnectionError("owned_connection_unavailable") from None
        self.checkpoint()
        return frame

    def read_duplex(self):
        return self.read()

    def close(self, *, after_control_observation: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._owner.close()
        except BaseException:
            code = (
                "owned_connection_cleanup_failed_after_control_observation"
                if after_control_observation
                else "owned_connection_cleanup_failed"
            )
            raise _OwnedConnectionError(code) from None


def _raw_connection(
    sock: socket.socket,
    codec: broker.FrameCodec,
    deadline: broker.Deadline,
    *,
    owns: bool,
) -> _RawSemanticConnection:
    return _RawSemanticConnection(sock, codec, deadline, owns=owns)


def _owned_connection(
    owner: listener.ExtensionConnection, deadline: broker.Deadline
) -> _OwnedSemanticConnection:
    return _OwnedSemanticConnection(owner, deadline)


__all__: list[str] = []
