"""The generic factory-issued owner (Task51 G2–G4; design §6 "Generic owner's actual guarantees").

Both generic factories retain one deadline bounded by the channel's operation
cap before acquisition; the issued owner keeps its generation, session, codec
and socket from acquisition to close; one reader latch covers `read` and
`read_duplex`; a writer latch never holds the codec lock over socket waits; an
idle poll returns None only before any prefix byte; close detaches its finite
resources first, shuts the socket down to wake readers, attempts every resource
and preserves an active primary; the owner is nonconstructible, uncopyable and
unserializable; an accepted owner outlives listener close. All over a real
temporary pair root and real handshakes through the platform seams.
"""

from __future__ import annotations

import copy
import pickle
import socket
import threading
import time
from uuid import uuid4

import pytest

from app.tests.support.provider_gateway_harness import (
    ACCEPT_MS,
    accept_in_thread,
    connect_owner,
    gateway_pair,
    owned_pair,
)
from app.workers import broker, ipc_root, listener


def deadline(ms=3_000):
    return broker.Deadline.after_ms(ms)


def send(owner, payload, *, message_type="credential_op", correlation_id=None, ms=3_000):
    message_id = str(uuid4())
    owner.write(message_id=message_id, correlation_id=correlation_id, message_type=message_type,
                payload=payload, deadline=deadline(ms))
    return message_id


def test_the_issued_owner_retains_its_original_deadline_bounded_by_the_operation_cap(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec, deadline_ms=2_000) as (client, owner, _worker):
        for connection in (client, owner):
            assert type(connection.deadline) is broker.Deadline
            # retained before acquisition: it ends no later than the caller's 2 s and no
            # later than the channel's operation cap (30 s), and it is read-only
            assert 0.0 < connection.deadline.remaining() <= 2.0
            with pytest.raises(AttributeError):
                connection.deadline = deadline()
        # a later read takes the minimum of the supplied and the retained end: a
        # supplied deadline far beyond the retained one cannot extend the wait
        started = time.monotonic()
        with pytest.raises((broker.DeadlineExceeded, broker.TransportUncertain)):
            # the broker's own categories are preserved: a socket wait that ends at the
            # retained end is its uncertain-transport outcome, never a longer wait
            owner.read_duplex(deadline=deadline(60_000))
        assert time.monotonic() - started < 3.0
        assert owner.closed


def test_one_reader_latch_covers_read_and_duplex_and_never_consumes_the_legitimate_readers_bytes(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        received = {}

        def reader():
            received["frame"] = owner.read_duplex(deadline=deadline())

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        time.sleep(0.15)  # the reader is waiting on the wire
        with pytest.raises(listener.ListenerBusy):
            owner.read(deadline=deadline(200))
        with pytest.raises(listener.ListenerBusy):
            owner.read_duplex(deadline=deadline(200), idle_timeout_ms=10)
        assert not owner.closed  # a refused competitor never closes the legitimate reader
        message_id = send(client, b'{"schema":"credential-op-v2"}')
        thread.join(3)
        assert not thread.is_alive()
        frame = received["frame"]
        assert frame.payload == b'{"schema":"credential-op-v2"}'
        assert frame.envelope.message_id == message_id
        # the reply crosses the other direction under the same owners
        reply = send(owner, b"{}", message_type="credential_result", correlation_id=message_id)
        assert client.read(deadline=deadline()).envelope.message_id == reply


def test_read_duplex_idles_only_before_any_prefix_byte_and_finishes_a_started_frame(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        started = time.monotonic()
        assert owner.read_duplex(deadline=deadline(), idle_timeout_ms=10) is None
        assert time.monotonic() - started < 0.5
        assert not owner.closed
        for bad in (0, 11, True, "10", 1.5):
            with pytest.raises(broker.ChannelConfigurationError):
                owner.read_duplex(deadline=deadline(), idle_timeout_ms=bad)
        # a frame written in two halves with a pause between them: the poll returns the
        # whole frame (never a half-consumed one) because the prefix started
        raw_socket = client._socket  # the test's own client side, split at the wire
        codec = client._codec
        encoded = codec.encode(message_id=str(uuid4()), correlation_id=None,
                               message_type="credential_op", payload=b'{"a":1}')
        import struct
        wire = struct.pack(">I", len(encoded)) + encoded
        results = {}

        def poll():
            results["frame"] = owner.read_duplex(deadline=deadline(), idle_timeout_ms=10)

        raw_socket.sendall(wire[:3])  # the prefix has begun before the poll
        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
        time.sleep(0.2)  # far longer than the idle slice: the poll must not return None
        assert thread.is_alive()
        raw_socket.sendall(wire[3:])
        thread.join(3)
        assert not thread.is_alive()
        assert results["frame"].payload == b'{"a":1}'
        # EOF is never idle: a closed peer is a transport failure, not None
        client.close()
        with pytest.raises(broker.TransportClosed):
            owner.read_duplex(deadline=deadline(), idle_timeout_ms=10)
        assert owner.closed


def test_a_partial_prefix_or_body_is_bounded_by_the_original_deadline(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec, deadline_ms=1_500) as (client, owner, _worker):
        client._socket.sendall(b"\x00\x00")  # two prefix bytes, then silence
        started = time.monotonic()
        with pytest.raises((broker.DeadlineExceeded, broker.TransportUncertain)):
            owner.read_duplex(deadline=deadline(60_000), idle_timeout_ms=10)
        assert time.monotonic() - started < 3.0  # the retained 1.5 s end, not the supplied 60 s
        assert owner.closed


def test_a_failed_encoded_write_closes_the_owner_and_the_advanced_sequence_is_never_reused(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        sent = broker._send_exact

        def failing(sock, raw, deadline_):
            raise broker.TransportUncertain(dispatch_effect="may_have_started")

        monkeypatch.setattr(broker, "_send_exact", failing)
        with pytest.raises(broker.TransportUncertain):
            send(client, b"{}")
        monkeypatch.setattr(broker, "_send_exact", sent)
        assert client.closed and client.codec_closed
        with pytest.raises(broker.TransportClosed):
            send(client, b"{}")
        with pytest.raises(broker.TransportClosed):
            client.read(deadline=deadline())
        # the peer sees EOF, never a frame with a skipped sequence
        with pytest.raises(broker.TransportClosed):
            owner.read(deadline=deadline())


def test_close_detaches_first_shuts_the_socket_down_and_attempts_every_resource(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        owned_socket, codec, generation = owner._socket, owner._codec, owner._generation
        blocked = {}

        def blocked_reader():
            try:
                owner.read(deadline=deadline(5_000))
            except BaseException as error:  # noqa: BLE001 - the wake is the fact
                blocked["error"] = error

        thread = threading.Thread(target=blocked_reader, daemon=True)
        thread.start()
        time.sleep(0.15)
        original_close = broker.FrameCodec.close

        def failing_close(self):
            original_close(self)
            if self is codec:
                raise RuntimeError("CODEC CLOSE")

        monkeypatch.setattr(broker.FrameCodec, "close", failing_close)
        with pytest.raises(RuntimeError, match="CODEC CLOSE"):
            owner.close()
        monkeypatch.setattr(broker.FrameCodec, "close", original_close)
        thread.join(3)
        assert not thread.is_alive() and "error" in blocked  # the shutdown woke the reader
        assert owner.closed and owner.codec_closed  # readable after the detach
        assert owned_socket.fileno() == -1 and generation.closed  # every resource attempted
        assert owner._socket is None and owner._codec is None and owner._generation is None
        owner.close()  # repeated close is harmless
        with pytest.raises(broker.TransportClosed):
            owner.read(deadline=deadline())
        with pytest.raises(listener.ListenerIntegrityError), owner:
            pass
        client.close()


def test_the_owner_is_factory_issued_uncopyable_and_unserializable(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        with pytest.raises(TypeError):
            listener.AuthenticatedConnection(connection=client._socket, session=client.session,
                                             codec=client._codec, generation=client._generation)
        with pytest.raises(TypeError):
            listener.AuthenticatedConnection()
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                operation(owner)
        assert type(owner) is listener.AuthenticatedConnection
        assert "socket" not in repr(owner) and "codec" not in repr(owner).lower()


def test_acquisition_failures_unwind_every_resource_and_preserve_the_primary(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec):
        worker = listener.bind_worker_listener(root, spec, responder_boot_id="provider-boot-a")
        try:
            # the client: the handshake succeeds, then owner construction's last step fails —
            # the socket and the generation must be closed, the primary preserved
            opened = []
            original_codec = broker.FrameCodec

            def exploding_codec(*args, **kwargs):
                codec = original_codec(*args, **kwargs)
                opened.append(codec)
                raise RuntimeError("PRIVATE CODEC CANARY")

            box = {}
            thread = accept_in_thread(worker, box)
            monkeypatch.setattr(listener.broker, "FrameCodec", exploding_codec)
            with pytest.raises(RuntimeError, match="PRIVATE CODEC CANARY"):
                connect_owner(root, spec)
            monkeypatch.setattr(listener.broker, "FrameCodec", original_codec)
            thread.join(ACCEPT_MS / 1000 + 1)
            assert not thread.is_alive()
            if "owner" in box:
                box["owner"].close()
            # the generation lease is released: a fresh acquisition succeeds at once and the
            # client's socket to the endpoint is gone (a new connect is a new socket)
            with ipc_root.acquire_generation(root) as lease:
                assert lease.generation_id
            # the worker: the handshake fails after accept — the accepted socket is closed
            # and the listening socket's timeout is restored to blocking
            def failing_handshake(*args, **kwargs):
                raise broker.ProtocolViolation()

            monkeypatch.setattr(listener.broker, "server_handshake", failing_handshake)
            box2 = {}
            thread2 = accept_in_thread(worker, box2, deadline_ms=1_500)
            raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            raw.connect(listener._anchored_socket_path(-1, root, spec.socket_name))
            thread2.join(3)
            assert not thread2.is_alive()
            assert type(box2.get("error")) is broker.ProtocolViolation
            assert worker._socket.gettimeout() is None
            raw.close()
        finally:
            worker.close()


def test_an_accepted_owner_outlives_listener_close_and_is_not_an_extension_connection(tmp_path, monkeypatch):
    with gateway_pair(tmp_path, monkeypatch) as (root, spec):
        worker = listener.bind_worker_listener(root, spec, responder_boot_id="provider-boot-a")
        box = {}
        thread = accept_in_thread(worker, box)
        client = connect_owner(root, spec)
        thread.join(ACCEPT_MS / 1000 + 1)
        owner = box["owner"]
        try:
            message_id = send(client, b'{"before":"close"}')
            worker.close()
            with pytest.raises(ipc_root.IpcRootBusy):
                ipc_root.initialize_pair_root(root, entropy=lambda size: b"b" * size)
            frame = owner.read_duplex(deadline=deadline(), idle_timeout_ms=10)
            assert frame.envelope.message_id == message_id
            assert type(owner) is listener.AuthenticatedConnection
            assert not hasattr(owner, "recheck")  # no extension fences on the generic owner
        finally:
            client.close()
            owner.close()
        ipc_root.initialize_pair_root(root, entropy=lambda size: b"b" * size)


def test_a_failure_after_the_codec_is_owned_unwinds_the_codec_and_the_socket(tmp_path, monkeypatch):
    # review closure (G2): the failure lands after every resource is owned — the codec is
    # closed, the client's socket is gone and the generation released, the primary preserved
    with gateway_pair(tmp_path, monkeypatch) as (root, spec):
        worker = listener.bind_worker_listener(root, spec, responder_boot_id="provider-boot-a")
        codecs = []
        original_codec = broker.FrameCodec

        def recording_codec(*args, **kwargs):
            codec = original_codec(*args, **kwargs)
            codecs.append(codec)
            return codec

        original_init = listener.AuthenticatedConnection.__init__

        def exploding_init(self, *args, **kwargs):
            if kwargs.get("codec") is not None and kwargs["codec"].local_service == "control":
                raise RuntimeError("PRIVATE OWNER CANARY")
            original_init(self, *args, **kwargs)

        try:
            box = {}
            thread = accept_in_thread(worker, box)
            monkeypatch.setattr(listener.broker, "FrameCodec", recording_codec)
            monkeypatch.setattr(listener.AuthenticatedConnection, "__init__", exploding_init)
            with pytest.raises(RuntimeError, match="PRIVATE OWNER CANARY"):
                connect_owner(root, spec)
            monkeypatch.setattr(listener.AuthenticatedConnection, "__init__", original_init)
            thread.join(ACCEPT_MS / 1000 + 1)
            assert not thread.is_alive()
            client_codecs = [codec for codec in codecs if codec.local_service == "control"]
            assert len(client_codecs) == 1 and client_codecs[0].closed
            if "owner" in box:
                box["owner"].close()
        finally:
            worker.close()
        # the generation is released: the pair root rotates
        ipc_root.initialize_pair_root(root, entropy=lambda size: b"c" * size)


def test_a_silent_reader_never_blocks_a_writer_and_every_close_failure_is_attempted(tmp_path, monkeypatch):
    # review closure (G3/G4): the owner writes while its own reader waits on the wire; a
    # generation close failure still leaves the codec and the socket closed and is raised
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        received = {}
        thread = threading.Thread(target=lambda: received.update(frame=owner.read_duplex(deadline=deadline())), daemon=True)
        thread.start()
        time.sleep(0.1)
        reply = send(owner, b"{}", message_type="credential_result")  # the writer is not behind the reader
        assert client.read(deadline=deadline()).envelope.message_id == reply
        message_id = send(client, b'{"x":1}')
        thread.join(3)
        assert not thread.is_alive() and received["frame"].envelope.message_id == message_id
        owned_socket, codec, generation = owner._socket, owner._codec, owner._generation
        original_close = type(generation).close

        def failing_generation_close(self):
            original_close(self)
            if self is generation:
                raise OSError("GENERATION CLOSE")

        monkeypatch.setattr(type(generation), "close", failing_generation_close)
        with pytest.raises(OSError, match="GENERATION CLOSE"):
            owner.close()
        monkeypatch.setattr(type(generation), "close", original_close)
        assert owner.closed and codec.closed and owned_socket.fileno() == -1 and generation.closed
        client.close()


def test_a_competitor_refused_mid_prefix_leaves_the_whole_frame_to_the_legitimate_reader(tmp_path, monkeypatch):
    # review closure (G3): the legitimate reader is blocked mid-prefix; the competitor is
    # refused without consuming a byte; the rest arrives and the reader gets the whole frame
    import struct

    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        encoded = client._codec.encode(message_id=str(uuid4()), correlation_id=None,
                                       message_type="credential_op", payload=b'{"whole":true}')
        wire = struct.pack(">I", len(encoded)) + encoded
        received = {}
        thread = threading.Thread(target=lambda: received.update(frame=owner.read(deadline=deadline())), daemon=True)
        thread.start()
        time.sleep(0.1)
        client._socket.sendall(wire[:2])  # the legitimate reader now waits mid-prefix
        time.sleep(0.1)
        with pytest.raises(listener.ListenerBusy):
            owner.read_duplex(deadline=deadline(200), idle_timeout_ms=10)
        client._socket.sendall(wire[2:])
        thread.join(3)
        assert not thread.is_alive()
        assert received["frame"].payload == b'{"whole":true}'
        assert not owner.closed


@pytest.mark.parametrize("size", [0, 65_537, 2**31])
def test_an_oversized_or_empty_prefix_is_a_protocol_violation_that_closes_the_owner(tmp_path, monkeypatch, size):
    import struct

    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        client._socket.sendall(struct.pack(">I", size))
        with pytest.raises(broker.ProtocolViolation):
            owner.read_duplex(deadline=deadline(), idle_timeout_ms=10)
        assert owner.closed


def test_a_close_during_an_idle_poll_is_a_transport_close_never_a_bare_error(tmp_path, monkeypatch):
    # review MUST: a concurrent close mid-poll emptied the descriptor and `select` raised a
    # bare ValueError past every product handler
    with gateway_pair(tmp_path, monkeypatch) as (root, spec), owned_pair(root, spec) as (client, owner, _worker):
        outcome = {}

        def poll_until_closed():
            try:
                for _ in range(2_000):
                    if owner.read_duplex(deadline=deadline(5_000), idle_timeout_ms=10) is not None:
                        break
            except BaseException as error:  # noqa: BLE001 - the category is the fact
                outcome["error"] = error

        thread = threading.Thread(target=poll_until_closed, daemon=True)
        thread.start()
        time.sleep(0.05)
        owner.close()
        thread.join(3)
        assert not thread.is_alive()
        assert type(outcome["error"]) is broker.TransportClosed, outcome
        client.close()
