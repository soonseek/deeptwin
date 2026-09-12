"""Carry the bounded artifact stream over one authenticated broker frame channel.

The artifact stream (`artifact_stream`) is deliberately transport-agnostic.  This adapter
binds it to a live :class:`broker.FrameCodec`, so every offer/credit/chunk/end/accept/cancel
message travels as one authenticated, replay-checked, size-bounded frame stamped with the
request's correlation id.  All broker transport failures surface as terminal
:class:`ArtifactStreamError`s, matching the stream's no-resume, no-retry contract.
"""

from __future__ import annotations

import socket
from uuid import uuid4

from . import broker
from .artifact_stream import ArtifactStreamError


class FrameCodecTransport:
    """A ``StreamTransport`` backed by one authenticated frame codec on one socket."""

    __slots__ = ("_codec", "_correlation_id", "_deadline", "_message_type", "_sock")

    def __init__(
        self,
        codec: broker.FrameCodec,
        sock: socket.socket,
        *,
        message_type: str,
        correlation_id: str,
        deadline: broker.Deadline,
    ) -> None:
        if type(codec) is not broker.FrameCodec:
            raise ArtifactStreamError("artifact stream requires an authenticated frame codec")
        if type(deadline) is not broker.Deadline:
            raise ArtifactStreamError("artifact stream requires a bounded deadline")
        self._codec = codec
        self._sock = sock
        self._message_type = message_type
        self._correlation_id = correlation_id
        self._deadline = deadline

    def send(self, payload: bytes) -> None:
        try:
            self._codec.write(
                self._sock,
                message_id=str(uuid4()),
                correlation_id=self._correlation_id,
                message_type=self._message_type,
                payload=payload,
                deadline=self._deadline,
            )
        except broker.BrokerError as exc:
            raise ArtifactStreamError("artifact stream frame could not be sent") from exc

    def receive(self) -> bytes:
        try:
            frame = self._codec.read(self._sock, deadline=self._deadline)
        except broker.BrokerError as exc:
            raise ArtifactStreamError("artifact stream frame could not be read") from exc
        envelope = frame.envelope
        if (envelope.message_type != self._message_type
                or envelope.correlation_id != self._correlation_id):
            raise ArtifactStreamError("unexpected frame on the artifact stream")
        return frame.payload


__all__ = ["FrameCodecTransport"]
