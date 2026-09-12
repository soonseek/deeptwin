"""The artifact stream carried over a real authenticated broker frame codec."""

from __future__ import annotations

import hashlib
import os
import socket
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from app.workers import broker
from app.workers.artifact_stream import (
    ArtifactDescriptor,
    ArtifactStreamError,
    BytesSink,
    BytesSource,
    StreamLimits,
    receive_artifact,
    send_artifact,
)
from app.workers.artifact_stream_transport import FrameCodecTransport

REQUESTER_BOOT_ID = "control-boot-test"
RESPONDER_BOOT_ID = "worker-boot-test"
CORRELATION = "123e4567-e89b-42d3-a456-426614174222"


def _distinct(*excluded: int) -> int:
    for candidate in range(20_001, 20_040):
        if candidate not in excluded:
            return candidate
    raise RuntimeError("identity range exhausted")


def artifact_channel(root: Path) -> broker.ChannelSpec:
    """A pair whose single message type flows in both directions for a duplex stream."""
    current_uid, current_gid = os.getuid(), os.getgid()
    responder_uid = current_uid or _distinct(current_uid)
    requester_uid = _distinct(current_uid, responder_uid)
    pair_gid = next((g for g in (current_gid, *os.getgroups()) if g > 0), _distinct(current_gid))
    requester_gid = _distinct(current_gid, pair_gid)
    responder_gid = _distinct(current_gid, pair_gid, requester_gid)
    return broker.ChannelSpec(
        channel_id="control-document",
        requester_service="control",
        responder_service="document",
        request_direction="control-to-document",
        protocol_id="artifact-stream-v1",
        requester_uid=requester_uid,
        requester_gid=requester_gid,
        responder_uid=responder_uid,
        responder_gid=responder_gid,
        pair_gid=pair_gid,
        pair_root=root,
        socket_name="document.sock",
        root_uid=responder_uid,
        root_gid=pair_gid,
        socket_uid=responder_uid,
        socket_gid=pair_gid,
        requester_message_types=("artifact_stream",),
        responder_message_types=("artifact_stream",),
        max_queue_depth=2,
    )



def codec_pair(spec):
    """Two authenticated codecs over one socketpair, handshaken without peer creds."""
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    secret = broker.BootSecret(b"k" * 32)
    server_out: list[broker.AuthenticatedSession] = []
    server_err: list[BaseException] = []

    def serve():
        try:
            server_out.append(broker._server_handshake_impl(
                right, spec, secret,
                requester_boot_id=REQUESTER_BOOT_ID, responder_boot_id=RESPONDER_BOOT_ID,
                deadline=broker.Deadline.after_ms(2_000), verify_peer=False,
            ))
        except BaseException as exc:  # noqa: BLE001
            server_err.append(exc)

    thread = threading.Thread(target=serve)
    thread.start()
    client = broker._client_handshake_impl(
        left, spec, secret,
        requester_boot_id=REQUESTER_BOOT_ID, responder_boot_id=RESPONDER_BOOT_ID,
        deadline=broker.Deadline.after_ms(2_000), verify_peer=False,
    )
    thread.join(3)
    if server_err:
        raise server_err[0]
    client_codec = broker.FrameCodec(spec, client, local_service=spec.requester_service)
    server_codec = broker.FrameCodec(spec, server_out[0], local_service=spec.responder_service)
    return left, right, client_codec, server_codec


def descriptor(data: bytes) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        batch_id="123e4567-e89b-42d3-a456-426614174000",
        request_id="123e4567-e89b-42d3-a456-426614174111",
        ordinal=0, count=1, media_type="application/pdf",
        declared_size=len(data), sha256=hashlib.sha256(data).hexdigest(),
    )


def _run(data: bytes, *, limits=None):
    spec = artifact_channel(Path("/tmp/deeptwin-artifact-stream-test"))
    left, right, client_codec, server_codec = codec_pair(spec)
    sender = FrameCodecTransport(
        client_codec, left, message_type="artifact_stream",
        correlation_id=CORRELATION, deadline=broker.Deadline.after_ms(5_000))
    receiver = FrameCodecTransport(
        server_codec, right, message_type="artifact_stream",
        correlation_id=CORRELATION, deadline=broker.Deadline.after_ms(5_000))
    desc = descriptor(data)
    sink = BytesSink()
    errors: dict[str, BaseException] = {}

    def do_send():
        try:
            send_artifact(sender, desc, BytesSource(data), limits=limits)
        except BaseException as exc:  # noqa: BLE001
            errors["send"] = exc

    def do_recv():
        try:
            receive_artifact(receiver, desc, sink, limits=limits)
        except BaseException as exc:  # noqa: BLE001
            errors["recv"] = exc

    ts = threading.Thread(target=do_send)
    tr = threading.Thread(target=do_recv)
    tr.start(); ts.start(); ts.join(8); tr.join(8)
    try:
        left.close(); right.close()
    except OSError:
        pass
    assert not ts.is_alive() and not tr.is_alive(), "stream deadlocked over the frame codec"
    return errors, sink


def test_single_frame_artifact_round_trips_over_authenticated_frames():
    data = b"a real authenticated artifact payload"
    errors, sink = _run(data)
    assert errors == {}
    assert sink.value == data


def test_multi_chunk_artifact_round_trips_with_real_credit_frames():
    data = bytes((i * 91) % 256 for i in range(40_000))
    errors, sink = _run(data, limits=StreamLimits(max_chunk_bytes=4_096, credit_window_chunks=2))
    assert errors == {}
    assert sink.value == data


def test_correlation_mismatch_is_terminal():
    spec = artifact_channel(Path("/tmp/deeptwin-artifact-stream-test"))
    left, right, client_codec, server_codec = codec_pair(spec)
    # The receiver expects a different correlation id than the sender stamps.
    sender = FrameCodecTransport(
        client_codec, left, message_type="artifact_stream",
        correlation_id=CORRELATION, deadline=broker.Deadline.after_ms(2_000))
    receiver = FrameCodecTransport(
        server_codec, right, message_type="artifact_stream",
        correlation_id=str(uuid4()), deadline=broker.Deadline.after_ms(2_000))
    desc = descriptor(b"payload")
    result: dict[str, BaseException] = {}

    def do_send():
        try:
            send_artifact(sender, desc, BytesSource(b"payload"))
        except BaseException as exc:  # noqa: BLE001
            result["send"] = exc

    def do_recv():
        try:
            receive_artifact(receiver, desc, BytesSink())
        except BaseException as exc:  # noqa: BLE001
            result["recv"] = exc

    tr = threading.Thread(target=do_recv); ts = threading.Thread(target=do_send)
    tr.start(); ts.start(); ts.join(5); tr.join(5)
    left.close(); right.close()
    assert isinstance(result.get("recv"), ArtifactStreamError)


def test_transport_rejects_a_non_codec_or_unbounded_deadline():
    spec = artifact_channel(Path("/tmp/deeptwin-artifact-stream-test"))
    left, right, client_codec, _ = codec_pair(spec)
    with pytest.raises(ArtifactStreamError):
        FrameCodecTransport(object(), left, message_type="artifact_stream",
                            correlation_id=CORRELATION, deadline=broker.Deadline.after_ms(1_000))
    with pytest.raises(ArtifactStreamError):
        FrameCodecTransport(client_codec, left, message_type="artifact_stream",
                            correlation_id=CORRELATION, deadline=object())
    left.close(); right.close()
