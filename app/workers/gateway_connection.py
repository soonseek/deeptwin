"""Private frame adapters for the shared gateway engines (Task51; design §5).

The credential vault engine and the provider send engine execute over one
private connection surface — `read`, `read_duplex`, `write`, `close`,
`closed` — so the factory-issued owner (`listener.AuthenticatedConnection`)
and the historical raw `(socket, codec)` pair run the same application code.
Only the raw adapter holds raw resources; nothing here exposes an owner's
socket or codec, and no wire byte or MAC algorithm changes.
"""

from __future__ import annotations

import select
import socket
import threading

from . import broker
from .listener import AuthenticatedConnection

__all__: list[str] = []

_IDLE_SLICE_MAX_MS = 10


class _RawConnection:
    """A borrowing adapter over the historical raw `(sock, codec)` pair.

    The codec is the adapter's to close on failure (the raw callers' own
    convention); the socket is closed only when the caller handed ownership
    over (`owns_socket=True`, the client factories' case).
    """

    __slots__ = ("_codec", "_owns_socket", "_read_latch", "_socket")

    def __init__(self, sock: socket.socket, codec: broker.FrameCodec, *, owns_socket: bool = False) -> None:
        if type(codec) is not broker.FrameCodec:
            raise broker.ChannelConfigurationError()
        self._socket = sock
        self._codec = codec
        self._owns_socket = owns_socket
        self._read_latch = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._codec.closed

    def read(self, *, deadline: broker.Deadline) -> broker.ReceivedFrame:
        return self._codec.read(self._socket, deadline=deadline)

    def read_duplex(
        self,
        *,
        deadline: broker.Deadline,
        idle_timeout_ms: int | None = None,
    ) -> broker.ReceivedFrame | None:
        if idle_timeout_ms is not None and (
            type(idle_timeout_ms) is not int or not 1 <= idle_timeout_ms <= _IDLE_SLICE_MAX_MS
        ):
            raise broker.ChannelConfigurationError()
        if not self._read_latch.acquire(blocking=False):
            raise broker.TransportClosed(dispatch_effect="outcome_unknown")
        try:
            if idle_timeout_ms is not None:
                slice_s = min(idle_timeout_ms / 1000.0, deadline.require(dispatch_effect="outcome_unknown"))
                readable, _writable, _errors = select.select([self._socket], [], [], slice_s)
                if not readable:
                    return None
            return self._codec.read(self._socket, deadline=deadline)
        finally:
            self._read_latch.release()

    def write(
        self,
        *,
        message_id: str,
        correlation_id: str | None,
        message_type: str,
        payload: bytes,
        deadline: broker.Deadline,
    ) -> None:
        self._codec.write(
            self._socket,
            message_id=message_id,
            correlation_id=correlation_id,
            message_type=message_type,
            payload=payload,
            deadline=deadline,
        )

    def close(self) -> None:
        self._codec.close()
        if self._owns_socket:
            try:
                self._socket.close()
            except OSError:
                pass


def _require_connection(connection: object) -> object:
    """An engine accepts exactly the owner or the raw adapter — never a duck."""
    if type(connection) not in (AuthenticatedConnection, _RawConnection):
        raise broker.ChannelConfigurationError()
    return connection
