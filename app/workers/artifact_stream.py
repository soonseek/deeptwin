"""Bounded digest/chunk/receiver-credit artifact stream for the T018 worker boundary.

The control plane never mounts the artifact store into a worker and never shares a
whole volume.  It opens one exact immutable object, states its digest, media type and
declared size up front, and transfers the bytes over the pair-specific socket using
bounded frames, an absolute receiver-credit watermark, an end digest and cancellation.
The worker returns output artifacts through the identical protocol with the sender and
receiver roles swapped.

This module is transport-agnostic: it drives a ``StreamTransport`` that moves one bounded
frame payload at a time.  The production integration wraps a :class:`broker.FrameCodec`
so each message is one authenticated, replay-checked, size-bounded frame; tests use an
in-memory paired transport.  A short read, a changed digest, an over-limit stream, a
stalled consumer, a cancellation or a peer restart fails the attempt without silently
substituting a path or sharing the whole volume.  There is no offset resume and no
automatic retry.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Bounded so one chunk message, base64-encoded once here and again by the broker frame,
# stays well under broker.MAX_FRAME_BYTES (65,536) with envelope overhead to spare.
MAX_CHUNK_BYTES = 16_384
MAX_ARTIFACTS_PER_BATCH = 256
MAX_TOTAL_STREAM_BYTES = 64 * 1024 * 1024
_DEFAULT_CREDIT_WINDOW_CHUNKS = 4

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&\-^_.+]{0,126}/[a-z0-9][a-z0-9!#$&\-^_.+]{0,126}\Z")

_OFFER = "artifact-offer"
_CREDIT = "artifact-credit"
_CHUNK = "artifact-chunk"
_END = "artifact-end"
_ACCEPTED = "artifact-accepted"
_CANCEL = "artifact-cancel"
_MESSAGE_TYPES = frozenset({_OFFER, _CREDIT, _CHUNK, _END, _ACCEPTED, _CANCEL})


class ArtifactStreamError(RuntimeError):
    """Terminal artifact-stream failure.  The attempt cannot resume."""


class StreamCancelled(ArtifactStreamError):
    """The peer sent an explicit cancellation."""


@runtime_checkable
class StreamTransport(Protocol):
    """Moves one bounded frame payload at a time in each direction."""

    def send(self, payload: bytes) -> None:  # pragma: no cover - protocol
        ...

    def receive(self) -> bytes:  # pragma: no cover - protocol
        ...


class ArtifactSink(Protocol):
    """Owned scratch destination.  Bytes arrive strictly in order from offset 0."""

    def write(self, offset: int, data: bytes) -> None:  # pragma: no cover - protocol
        ...

    def finalize(self) -> None:  # pragma: no cover - protocol
        ...

    def abort(self) -> None:  # pragma: no cover - protocol
        ...


class ArtifactSource(Protocol):
    """The exact immutable object being transferred; read strictly forward."""

    def read(self, size: int) -> bytes:  # pragma: no cover - protocol
        ...


def _reject_float(_name: str) -> None:
    raise ArtifactStreamError("stream message contains a non-integer number")


def _encode(message: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            message,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ArtifactStreamError("stream message is not encodable") from exc


def _decode(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_TOTAL_STREAM_BYTES:
        raise ArtifactStreamError("stream frame payload is invalid")
    try:
        value = json.loads(payload.decode("ascii"), parse_float=_reject_float)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactStreamError("stream frame payload is not strict JSON") from exc
    if type(value) is not dict:
        raise ArtifactStreamError("stream frame payload is not an object")
    message_type = value.get("type")
    if message_type not in _MESSAGE_TYPES:
        raise ArtifactStreamError("unknown stream message type")
    return value


def _int(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ArtifactStreamError("stream integer is out of bounds")
    return value


def _b64_bytes(value: object, *, limit: int) -> bytes:
    import base64

    if type(value) is not str:
        raise ArtifactStreamError("chunk data is not text")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise ArtifactStreamError("chunk data is not valid base64") from exc
    if base64.b64encode(raw).decode("ascii") != value:
        raise ArtifactStreamError("chunk data base64 is not canonical")
    if not 1 <= len(raw) <= limit:
        raise ArtifactStreamError("chunk length is out of bounds")
    return raw


def _b64_text(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode("ascii")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """The frozen, exact identity of one artifact in an ordered batch."""

    batch_id: str
    request_id: str
    ordinal: int
    count: int
    media_type: str
    declared_size: int
    sha256: str

    def __post_init__(self) -> None:
        if _UUID.fullmatch(self.batch_id) is None or _UUID.fullmatch(self.request_id) is None:
            raise ArtifactStreamError("descriptor id is not a canonical UUID")
        if type(self.count) is not int or isinstance(self.count, bool) or not 1 <= self.count <= MAX_ARTIFACTS_PER_BATCH:
            raise ArtifactStreamError("descriptor count is out of bounds")
        if type(self.ordinal) is not int or isinstance(self.ordinal, bool) or not 0 <= self.ordinal < self.count:
            raise ArtifactStreamError("descriptor ordinal is out of bounds")
        if type(self.media_type) is not str or _MEDIA_TYPE.fullmatch(self.media_type) is None:
            raise ArtifactStreamError("descriptor media type is invalid")
        if type(self.declared_size) is not int or isinstance(self.declared_size, bool) or not 0 <= self.declared_size <= MAX_TOTAL_STREAM_BYTES:
            raise ArtifactStreamError("descriptor declared size is out of bounds")
        if type(self.sha256) is not str or _SHA256.fullmatch(self.sha256) is None:
            raise ArtifactStreamError("descriptor digest is not lowercase sha256 hex")

    def as_offer_fields(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "request_id": self.request_id,
            "ordinal": self.ordinal,
            "count": self.count,
            "media_type": self.media_type,
            "declared_size": self.declared_size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class StreamLimits:
    """Caller-supplied ceilings; never above the module hard maxima."""

    max_artifact_bytes: int = MAX_TOTAL_STREAM_BYTES
    max_total_bytes: int = MAX_TOTAL_STREAM_BYTES
    max_chunk_bytes: int = MAX_CHUNK_BYTES
    credit_window_chunks: int = _DEFAULT_CREDIT_WINDOW_CHUNKS

    def __post_init__(self) -> None:
        if not 1 <= self.max_chunk_bytes <= MAX_CHUNK_BYTES:
            raise ArtifactStreamError("max_chunk_bytes is out of bounds")
        if not 1 <= self.max_artifact_bytes <= MAX_TOTAL_STREAM_BYTES:
            raise ArtifactStreamError("max_artifact_bytes is out of bounds")
        if not 1 <= self.max_total_bytes <= MAX_TOTAL_STREAM_BYTES:
            raise ArtifactStreamError("max_total_bytes is out of bounds")
        if not 1 <= self.credit_window_chunks <= 4_096:
            raise ArtifactStreamError("credit_window_chunks is out of bounds")

    @property
    def credit_window_bytes(self) -> int:
        return self.max_chunk_bytes * self.credit_window_chunks


class BytesSource:
    """An in-memory forward-only reader over one immutable byte object."""

    __slots__ = ("_data", "_offset")

    def __init__(self, data: bytes) -> None:
        if type(data) is not bytes:
            raise ArtifactStreamError("source data must be bytes")
        self._data = data
        self._offset = 0

    def read(self, size: int) -> bytes:
        if type(size) is not int or size < 0:
            raise ArtifactStreamError("source read size is invalid")
        chunk = self._data[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


class BytesSink:
    """Collect ordered bytes in memory; expose them only after finalize."""

    __slots__ = ("_buffer", "_final", "_received")

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._final: bytes | None = None
        self._received = 0

    def write(self, offset: int, data: bytes) -> None:
        if offset != self._received:
            raise ArtifactStreamError("sink received an out-of-order write")
        self._buffer.extend(data)
        self._received += len(data)

    def finalize(self) -> None:
        self._final = bytes(self._buffer)

    def abort(self) -> None:
        self._buffer = bytearray()
        self._final = None
        self._received = 0

    @property
    def value(self) -> bytes:
        if self._final is None:
            raise ArtifactStreamError("sink was not finalized")
        return self._final


class ScratchFileSink:
    """Write into a single owned scratch file created no-follow under a directory fd."""

    __slots__ = ("_dir_fd", "_fd", "_finalized", "_name", "_received")

    def __init__(self, scratch_dir: str, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name or ""):
            raise ArtifactStreamError("scratch name is invalid")
        dir_fd = os.open(scratch_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        info = os.fstat(dir_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            os.close(dir_fd)
            raise ArtifactStreamError("scratch directory is not owned by this user")
        self._dir_fd = dir_fd
        self._name = name
        self._received = 0
        self._finalized = False
        try:
            self._fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=dir_fd,
            )
        except OSError as exc:
            os.close(dir_fd)
            raise ArtifactStreamError("scratch file could not be created") from exc

    def write(self, offset: int, data: bytes) -> None:
        if offset != self._received:
            raise ArtifactStreamError("sink received an out-of-order write")
        written = 0
        while written < len(data):
            written += os.pwrite(self._fd, data[written:], offset + written)
        self._received += len(data)

    def finalize(self) -> None:
        os.fsync(self._fd)
        os.close(self._fd)
        self._finalized = True
        os.close(self._dir_fd)

    def abort(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass
        try:
            os.unlink(self._name, dir_fd=self._dir_fd)
        except OSError:
            pass
        finally:
            os.close(self._dir_fd)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactStreamError(message)


def send_artifact(
    transport: StreamTransport,
    descriptor: ArtifactDescriptor,
    source: ArtifactSource,
    *,
    limits: StreamLimits | None = None,
) -> None:
    """Offer, then push bytes only up to the receiver's absolute credit, then end."""

    limits = limits or StreamLimits()
    _require(descriptor.declared_size <= limits.max_artifact_bytes, "artifact exceeds limit")
    transport.send(_encode({"type": _OFFER, **descriptor.as_offer_fields()}))

    rolling = hashlib.sha256()
    sent = 0
    credit_through = 0
    try:
        while sent < descriptor.declared_size:
            if sent >= credit_through:
                credit_through = _await_credit(
                    transport, descriptor, previous=credit_through, sent=sent,
                )
            take = min(limits.max_chunk_bytes, credit_through - sent, descriptor.declared_size - sent)
            data = source.read(take)
            _require(len(data) == take and take > 0, "source produced a short read")
            rolling.update(data)
            transport.send(_encode({
                "type": _CHUNK,
                "batch_id": descriptor.batch_id,
                "ordinal": descriptor.ordinal,
                "offset": sent,
                "data": _b64_text(data),
            }))
            sent += take
        digest = rolling.hexdigest()
        _require(digest == descriptor.sha256, "source bytes do not match the declared digest")
    except StreamCancelled:
        raise
    except ArtifactStreamError:
        _send_cancel(transport, descriptor, "sender_fault")
        raise

    transport.send(_encode({
        "type": _END,
        "batch_id": descriptor.batch_id,
        "ordinal": descriptor.ordinal,
        "size": sent,
        "sha256": digest,
    }))
    accepted = _decode(transport.receive())
    _require(accepted["type"] == _ACCEPTED, "expected an acceptance")
    _match_ref(accepted, descriptor)
    _require(accepted.get("sha256") == descriptor.sha256, "acceptance digest mismatch")


def _await_credit(
    transport: StreamTransport,
    descriptor: ArtifactDescriptor,
    *,
    previous: int,
    sent: int,
) -> int:
    message = _decode(transport.receive())
    if message["type"] == _CANCEL:
        _match_ref(message, descriptor, batch_only=True)
        raise StreamCancelled("receiver cancelled the stream")
    _require(message["type"] == _CREDIT, "expected a credit watermark")
    _match_ref(message, descriptor)
    consumed = _int(message.get("consumed_through"), minimum=0, maximum=descriptor.declared_size)
    credit_through = _int(message.get("credit_through"), minimum=0, maximum=descriptor.declared_size)
    _require(consumed <= credit_through, "credit watermark is inverted")
    _require(consumed <= sent, "receiver consumed more than was sent")
    # Absolute watermark: it may never move backward, and while the sender still holds
    # unsent bytes a fresh credit must strictly advance or the consumer has stalled.
    _require(credit_through >= previous, "credit watermark moved backward")
    _require(credit_through > sent, "credit did not advance a stalled sender")
    return credit_through


def receive_artifact(
    transport: StreamTransport,
    expected: ArtifactDescriptor,
    sink: ArtifactSink,
    *,
    limits: StreamLimits | None = None,
) -> None:
    """Validate the offer against the exact expected descriptor, then admit bytes."""

    limits = limits or StreamLimits()
    _require(expected.declared_size <= limits.max_artifact_bytes, "artifact exceeds limit")
    try:
        offer = _decode(transport.receive())
        _require(offer["type"] == _OFFER, "expected an offer")
        _require(
            {key: offer.get(key) for key in expected.as_offer_fields()} == expected.as_offer_fields(),
            "offer does not match the expected descriptor",
        )

        rolling = hashlib.sha256()
        received = 0
        credit_through = min(limits.credit_window_bytes, expected.declared_size)
        if expected.declared_size > 0:
            _send_credit(transport, expected, consumed=0, credit_through=credit_through)

        while received < expected.declared_size:
            message = _decode(transport.receive())
            if message["type"] == _CANCEL:
                _match_ref(message, expected, batch_only=True)
                raise StreamCancelled("sender cancelled the stream")
            _require(message["type"] == _CHUNK, "expected a chunk")
            _match_ref(message, expected)
            offset = _int(message.get("offset"), minimum=0, maximum=expected.declared_size)
            _require(offset == received, "chunk offset is not the next expected byte")
            data = _b64_bytes(message.get("data"), limit=limits.max_chunk_bytes)
            _require(offset + len(data) <= credit_through, "chunk exceeds granted credit")
            _require(offset + len(data) <= expected.declared_size, "chunk exceeds declared size")
            sink.write(offset, data)
            rolling.update(data)
            received += len(data)
            new_credit = min(received + limits.credit_window_bytes, expected.declared_size)
            if new_credit != credit_through:
                credit_through = new_credit
                _send_credit(transport, expected, consumed=received, credit_through=credit_through)

        end = _decode(transport.receive())
        if end["type"] == _CANCEL:
            _match_ref(end, expected, batch_only=True)
            raise StreamCancelled("sender cancelled the stream")
        _require(end["type"] == _END, "expected an end marker")
        _match_ref(end, expected)
        _require(_int(end.get("size"), minimum=0, maximum=expected.declared_size) == received, "end size disagrees")
        _require(received == expected.declared_size, "stream ended before the declared size")
        digest = rolling.hexdigest()
        _require(end.get("sha256") == expected.sha256 == digest, "end digest disagrees")
        sink.finalize()
    except ArtifactStreamError:
        sink.abort()
        raise
    transport.send(_encode({
        "type": _ACCEPTED,
        "batch_id": expected.batch_id,
        "ordinal": expected.ordinal,
        "sha256": expected.sha256,
    }))


def _send_credit(
    transport: StreamTransport,
    descriptor: ArtifactDescriptor,
    *,
    consumed: int,
    credit_through: int,
) -> None:
    transport.send(_encode({
        "type": _CREDIT,
        "batch_id": descriptor.batch_id,
        "ordinal": descriptor.ordinal,
        "consumed_through": consumed,
        "credit_through": credit_through,
    }))


def _send_cancel(transport: StreamTransport, descriptor: ArtifactDescriptor, reason: str) -> None:
    try:
        transport.send(_encode({
            "type": _CANCEL,
            "batch_id": descriptor.batch_id,
            "reason": reason,
        }))
    except ArtifactStreamError:
        pass


def _match_ref(message: Mapping[str, object], descriptor: ArtifactDescriptor, *, batch_only: bool = False) -> None:
    _require(message.get("batch_id") == descriptor.batch_id, "message batch id mismatch")
    if not batch_only:
        _require(message.get("ordinal") == descriptor.ordinal, "message ordinal mismatch")


def validate_batch(descriptors: list[ArtifactDescriptor], limits: StreamLimits) -> None:
    if not 1 <= len(descriptors) <= MAX_ARTIFACTS_PER_BATCH:
        raise ArtifactStreamError("batch size is out of bounds")
    first = descriptors[0]
    total = 0
    for index, descriptor in enumerate(descriptors):
        if descriptor.batch_id != first.batch_id or descriptor.request_id != first.request_id:
            raise ArtifactStreamError("batch descriptors disagree on batch/request id")
        if descriptor.count != len(descriptors) or descriptor.ordinal != index:
            raise ArtifactStreamError("batch ordinal/count is not the exact ordered sequence")
        total += descriptor.declared_size
    if total > limits.max_total_bytes:
        raise ArtifactStreamError("batch aggregate exceeds the total byte limit")


def send_batch(
    transport: StreamTransport,
    descriptors: list[ArtifactDescriptor],
    sources: list[ArtifactSource],
    *,
    limits: StreamLimits | None = None,
) -> None:
    """Stream a frozen ordered batch of 1..256 artifacts one after another."""

    limits = limits or StreamLimits()
    validate_batch(descriptors, limits)
    if len(sources) != len(descriptors):
        raise ArtifactStreamError("each descriptor needs exactly one source")
    for descriptor, source in zip(descriptors, sources, strict=True):
        send_artifact(transport, descriptor, source, limits=limits)


def receive_batch(
    transport: StreamTransport,
    expected: list[ArtifactDescriptor],
    sinks: list[ArtifactSink],
    *,
    limits: StreamLimits | None = None,
) -> None:
    """Admit a frozen ordered batch, one artifact at a time, into owned sinks."""

    limits = limits or StreamLimits()
    validate_batch(expected, limits)
    if len(sinks) != len(expected):
        raise ArtifactStreamError("each descriptor needs exactly one sink")
    for descriptor, sink in zip(expected, sinks, strict=True):
        receive_artifact(transport, descriptor, sink, limits=limits)


__all__ = [
    "MAX_ARTIFACTS_PER_BATCH",
    "MAX_CHUNK_BYTES",
    "MAX_TOTAL_STREAM_BYTES",
    "ArtifactDescriptor",
    "ArtifactSink",
    "ArtifactSource",
    "ArtifactStreamError",
    "BytesSink",
    "BytesSource",
    "ScratchFileSink",
    "StreamCancelled",
    "StreamLimits",
    "StreamTransport",
    "receive_artifact",
    "receive_batch",
    "send_artifact",
    "send_batch",
    "validate_batch",
]
