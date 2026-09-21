"""T090 credential gateway service over authenticated broker frames.

The control plane's client speaks `credential_op` frames over one authenticated
channel; the gateway service dispatches to the vault and answers with redacted
results only. The secret crosses exactly once (store direction); no response —
success or error — ever carries secret bytes, and `resolve_for_gateway` is not
an operation the channel exposes at all.
"""

import json
import socket
import threading
from pathlib import Path

import pytest

from app.workers import broker
from app.workers.credential_gateway_service import (
    CredentialGatewayClient,
    CredentialGatewayService,
    GatewayServiceError,
)
from app.workers.credential_vault import CredentialVault
from app.tests.test_credential_root import initialized
from app.tests.test_credential_custody import metadata
from uuid import uuid4

INTENT = "00000000-0000-4000-8000-00000000ee01"
SECRET = "sk-uds-gateway-secret-000"
REQUESTER_BOOT = "control-boot-test"
RESPONDER_BOOT = "gateway-boot-test"


def channel_spec(root: Path) -> broker.ChannelSpec:
    def distinct(*excluded):
        for candidate in range(20_001, 20_040):
            if candidate not in excluded:
                return candidate
        raise RuntimeError("identity range exhausted")

    import os
    current_uid, current_gid = os.getuid(), os.getgid()
    responder_uid = current_uid or distinct(current_uid)
    requester_uid = distinct(current_uid, responder_uid)
    pair_gid = next(
        (g for g in (current_gid, *os.getgroups()) if g > 0), distinct(current_gid)
    )
    return broker.ChannelSpec(
        channel_id="control-credential-gateway",
        requester_service="control",
        responder_service="credential-gateway",
        request_direction="control-to-credential-gateway",
        protocol_id="credential-gateway-v1",
        requester_uid=requester_uid,
        requester_gid=distinct(current_gid, pair_gid),
        responder_uid=responder_uid,
        responder_gid=distinct(current_gid, pair_gid, requester_uid),
        pair_gid=pair_gid,
        pair_root=root,
        socket_name="credential-gateway.sock",
        root_uid=responder_uid,
        root_gid=pair_gid,
        socket_uid=responder_uid,
        socket_gid=pair_gid,
        requester_message_types=("credential_op",),
        responder_message_types=("credential_result",),
        max_queue_depth=2,
    )


@pytest.fixture
def subject(tmp_path):
    vault = CredentialVault(**initialized(tmp_path))
    spec = channel_spec(tmp_path / "pair")
    secret = broker.BootSecret(b"k" * broker.AUTH_SECRET_BYTES)
    service = CredentialGatewayService(vault, spec, secret)
    wire_log: list[bytes] = []

    def transport_factory():
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        errors: list = []

        def serve():
            try:
                session = broker._server_handshake_impl(
                    right, spec, secret,
                    requester_boot_id=REQUESTER_BOOT,
                    responder_boot_id=RESPONDER_BOOT,
                    deadline=broker.Deadline.after_ms(5_000),
                    verify_peer=False,
                )
                codec = broker.FrameCodec(
                    spec, session, local_service=spec.responder_service
                )
                try:
                    service.serve_one(
                        right, codec,
                        deadline=broker.Deadline.after_ms(5_000),
                        wire_log=wire_log,
                    )
                finally:
                    codec.close()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                try:
                    right.close()
                except OSError:
                    pass

        thread = threading.Thread(target=serve)
        thread.start()
        session = broker._client_handshake_impl(
            left, spec, secret,
            requester_boot_id=REQUESTER_BOOT,
            responder_boot_id=RESPONDER_BOOT,
            deadline=broker.Deadline.after_ms(5_000),
            verify_peer=False,
        )
        codec = broker.FrameCodec(
            spec, session, local_service=spec.requester_service
        )
        threads.append((thread, errors))
        return left, codec

    threads: list = []
    client = CredentialGatewayClient(
        transport_factory, deadline_ms=5_000,
    )

    yield vault, client, threads, wire_log
    for thread, errors in threads:
        thread.join(5)
        assert not thread.is_alive()
        assert errors == []
    vault.close()


def test_store_round_trips_with_a_redacted_receipt(subject):
    vault, client, _threads, _wire = subject
    meta = metadata()
    receipt = client.store_at(metadata=meta, secret=SECRET.encode())
    assert client.query_record(metadata=meta) == receipt
    assert receipt["provider"] == "claude"
    assert receipt["state"] == "stored_unbound"
    assert SECRET not in json.dumps(receipt)
    assert vault.query_record(metadata=meta) == receipt


def test_responses_never_carry_secret_bytes_on_the_wire(subject):
    _vault, client, _threads, wire_log = subject
    client.store_at(metadata=metadata(), secret=SECRET.encode())
    responses = [payload for direction, payload in wire_log if direction == "out"]
    assert responses  # the service logged its outbound payloads
    for payload in responses:
        assert SECRET.encode("utf-8") not in payload


def test_retirement_is_persistent_denial_without_erasure(subject):
    vault, client, _threads, _wire = subject
    meta = metadata()
    receipt = client.store_at(metadata=meta, secret=SECRET.encode())
    reference = {k: receipt[k] for k in ("record_id", "record_version", "ciphertext_sha256")}
    command = str(uuid4())
    outcome = client.retire(command_id=command, record=reference, reason="owner_delete")
    assert outcome["state"] == "cleanup_pending"
    assert client.retire(command_id=command, record=reference, reason="owner_delete") == outcome
    assert client.query_record(metadata=meta)["state"] == "cleanup_pending"
    assert vault.health()["cleanup_pending"] == 1


def test_snapshot_is_redacted_and_read_only(subject):
    vault, client, _threads, _wire = subject
    receipt = client.store_at(metadata=metadata(), secret=SECRET.encode())
    snapshot = client.snapshot()
    assert snapshot == [receipt]
    assert vault.health()["stored_unbound"] == 1


def test_conflicts_and_unknown_operations_are_sanitized(subject):
    _vault, client, _threads, _wire = subject
    meta = metadata()
    client.store_at(metadata=meta, secret=SECRET.encode())
    with pytest.raises(GatewayServiceError) as failure:
        client.store_at(metadata=meta | {"provider": "codex"}, secret=b"sk-different-secret")
    assert "sk-different" not in str(failure.value)
    assert SECRET not in str(failure.value)

    with pytest.raises(GatewayServiceError):
        client._call({"op": "resolve_for_gateway", "handle": "0" * 32})
    with pytest.raises(GatewayServiceError):
        client._call({"op": "unknown_operation"})


def test_v1_writes_and_delete_are_explicitly_unsupported(subject):
    vault, client, _, _ = subject
    for request in ({"op": "store", "intent_id": INTENT, "provider": "claude", "secret_b64": "eA==", "rotate_from": None},
                    {"op": "delete", "handle": "0" * 32}):
        with pytest.raises(GatewayServiceError) as failure:
            client._call(request)
        assert failure.value.code == "unsupported_operation"
    assert vault.health()["stored_unbound"] == 0


def test_v2_closed_keys_and_base64_are_strict_and_replay_ignores_new_ingress(subject):
    _, client, _, _ = subject
    from app.workers.credential_contracts import b64u
    meta = metadata()
    request = dict(schema="credential-op-v2", op="store_at", metadata=meta, secret_b64u=b64u(SECRET.encode()))
    with pytest.raises(GatewayServiceError):
        client._call(request | {"extra": True})
    with pytest.raises(GatewayServiceError):
        client._call(request | {"secret_b64u": "eA=="})
    receipt = client._call(request)
    assert client._call(request | {"secret_b64u": "not valid replacement"}) == receipt


def test_maximum_secret_traverses_actual_authenticated_v2_frames(subject):
    vault, client, _, wire = subject
    meta, secret = metadata(), b"x" * 65536
    receipt = client.store_at(metadata=meta, secret=secret)
    assert client.query_record(metadata=meta) == receipt
    assert receipt["state"] == "stored_unbound"
    assert vault._root.open(vault._published(meta), meta) == secret
    assert all(secret not in payload for direction, payload in wire if direction == "out")
    assert client.store_at(metadata=meta, secret=b"changed-replay") == receipt
    from hashlib import sha256
    for path in Path(vault._root._records.path).rglob("*"):
        if path.is_file():
            assert secret not in path.read_bytes()
            assert sha256(secret).hexdigest().encode() not in path.read_bytes()


from contextlib import contextmanager


@contextmanager
def authenticated_pair(tmp_path):
    spec = channel_spec(tmp_path / "fragment-pair")
    secret = broker.BootSecret(b"f" * broker.AUTH_SECRET_BYTES)
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    server_sessions, errors = [], []
    def server_handshake():
        try:
            server_sessions.append(broker._server_handshake_impl(right, spec, secret,
                requester_boot_id=REQUESTER_BOOT, responder_boot_id=RESPONDER_BOOT,
                deadline=broker.Deadline.after_ms(2000), verify_peer=False))
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=server_handshake)
    thread.start()
    client_session = broker._client_handshake_impl(left, spec, secret,
        requester_boot_id=REQUESTER_BOOT, responder_boot_id=RESPONDER_BOOT,
        deadline=broker.Deadline.after_ms(2000), verify_peer=False)
    thread.join(3)
    assert not thread.is_alive() and not errors
    client_codec = broker.FrameCodec(spec, client_session, local_service=spec.requester_service)
    server_codec = broker.FrameCodec(spec, server_sessions[0], local_service=spec.responder_service)
    try:
        yield left, client_codec, right, server_codec, spec, secret
    finally:
        client_codec.close()
        server_codec.close()
        left.close()
        right.close()


@pytest.mark.parametrize("size", [16383, 16384, 16385, 102400])
@pytest.mark.parametrize("response", [False, True])
def test_logical_codec_thresholds_and_fragmented_response(tmp_path, size, response):
    from app.workers.credential_channel import _read_logical, _write_logical
    payload = b'{"value":"' + b"x" * (size - 12) + b'"}'
    assert len(payload) == size
    with authenticated_pair(tmp_path) as (left, cc, right, sc, _, _):
        sender, writer, receiver, reader = (right, sc, left, cc) if response else (left, cc, right, sc)
        message_type = "credential_result" if response else "credential_op"
        correlation = str(uuid4()) if response else None
        identity = str(uuid4())
        results, errors = [], []
        def read():
            try:
                results.append(_read_logical(receiver, reader, message_type=message_type,
                    correlation_id=correlation, deadline=broker.Deadline.after_ms(3000)))
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=read)
        thread.start()
        try:
            _write_logical(sender, writer, payload=payload, message_id=identity,
                message_type=message_type, correlation_id=correlation, deadline=broker.Deadline.after_ms(3000))
        finally:
            thread.join(4)
        assert not thread.is_alive() and not errors
        assert results == [(identity, payload)]
        assert writer.next_send_sequence == 1 + (1 if size <= 16384 else (size + 16383) // 16384)


def test_logical_codec_overflow_sends_no_frames(tmp_path):
    from app.workers.credential_channel import _write_logical
    with authenticated_pair(tmp_path) as (left, cc, _, _, _, _):
        with pytest.raises(GatewayServiceError):
            _write_logical(left, cc, payload=b"x" * 102401, message_id=str(uuid4()),
                message_type="credential_op", correlation_id=None, deadline=broker.Deadline.after_ms(1000))
        assert cc.next_send_sequence == 1


def fragment_frames(payload, identity):
    from app.workers.credential_contracts import b64u
    count = (len(payload) + 16383) // 16384
    return [(identity if index == 0 else str(uuid4()), None if index == 0 else identity,
        {"schema": "credential-fragment-v1", "transfer_id": identity, "total_bytes": len(payload),
         "index": index, "count": count, "chunk_b64u": b64u(payload[index*16384:(index+1)*16384])})
        for index in range(count)]


@pytest.mark.parametrize("damage", ["reorder", "duplicate_index", "wrong_transfer", "wrong_count", "wrong_total", "bool", "short_chunk", "padded", "extra", "duplicate_key", "wrong_correlation", "first_correlation", "reused_message_id", "first_identity", "noncanonical", "single_oversize", "incomplete", "bad_mac"])
def test_malformed_actual_frames_do_not_mutate_vault(tmp_path, damage):
    import struct
    from app.workers.credential_channel import encode_op
    from app.workers.credential_contracts import b64u
    args = initialized(tmp_path)
    with CredentialVault(**args) as vault, authenticated_pair(tmp_path) as (left, cc, right, sc, spec, boot):
        meta = metadata()
        payload = encode_op(dict(schema="credential-op-v2", op="store_at", metadata=meta, secret_b64u=b64u(b"x" * 20000)))
        identity = str(uuid4())
        frames = fragment_frames(payload, identity)
        index = 1
        msg, corr, body = frames[index]
        if damage == "reorder":
            frames.reverse()
        elif damage == "duplicate_index":
            body["index"] = 0
        elif damage == "wrong_transfer":
            body["transfer_id"] = str(uuid4())
        elif damage == "wrong_count":
            body["count"] = 3
        elif damage == "wrong_total":
            body["total_bytes"] += 1
        elif damage == "bool":
            body["index"] = True
        elif damage == "short_chunk":
            body["chunk_b64u"] = "eA"
        elif damage == "padded":
            body["chunk_b64u"] += "="
        elif damage == "extra":
            body["extra"] = 1
        elif damage == "wrong_correlation":
            frames[index] = (msg, str(uuid4()), body)
        elif damage == "first_correlation":
            frames[0] = (identity, str(uuid4()), frames[0][2])
        elif damage == "reused_message_id":
            frames[index] = (identity, corr, body)
        elif damage == "first_identity":
            frames[0] = (str(uuid4()), None, frames[0][2])
        elif damage == "incomplete":
            frames = frames[:1]
        errors = []
        service = CredentialGatewayService(vault, spec, boot)
        def serve():
            try:
                service.serve_one(right, sc, deadline=broker.Deadline.after_ms(100))
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=serve)
        thread.start()
        try:
            for number, (msg, corr, value) in enumerate(frames):
                raw = encode_op(value)
                if damage == "duplicate_key" and number == 1:
                    raw = raw[:-1] + b',"index":1}'
                elif damage == "noncanonical" and number == 1:
                    raw = b" " + raw
                elif damage == "single_oversize":
                    raw, corr = payload, None
                if damage == "bad_mac":
                    encoded = json.loads(cc.encode(message_id=msg, correlation_id=corr, message_type="credential_op", payload=raw))
                    mac = encoded["mac"]
                    encoded["mac"] = ("A" if mac[0] != "A" else "B") + mac[1:]
                    packet = encode_op(encoded)
                    left.sendall(struct.pack(">I", len(packet)) + packet)
                else:
                    cc.write(left, message_id=msg, correlation_id=corr, message_type="credential_op", payload=raw, deadline=broker.Deadline.after_ms(1000))
                if damage in ("single_oversize", "bad_mac", "reorder", "first_correlation", "first_identity"):
                    break
            if damage == "incomplete":
                left.shutdown(socket.SHUT_WR)
        finally:
            thread.join(2)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], (GatewayServiceError, broker.BrokerError)), errors
        assert vault.snapshot() == []
        from app.tests.test_credential_custody import counts
        assert counts(args) == (0, 0, 0)


def test_slow_partial_transfer_uses_one_absolute_deadline(tmp_path):
    import time
    from app.workers.credential_channel import encode_op
    with authenticated_pair(tmp_path) as (left, cc, right, sc, spec, boot):
        with CredentialVault(**initialized(tmp_path)) as vault:
            service = CredentialGatewayService(vault, spec, boot)
            frames = fragment_frames(b"x" * 40000, str(uuid4()))
            errors = []
            deadline = broker.Deadline.after_ms(100)
            start = time.monotonic()
            def serve():
                try:
                    service.serve_one(right, sc, deadline=deadline)
                except BaseException as exc:
                    errors.append(exc)
            thread = threading.Thread(target=serve)
            thread.start()
            for index in range(2):
                time.sleep(0.035)
                msg, corr, value = frames[index]
                cc.write(left, message_id=msg, correlation_id=corr, message_type="credential_op", payload=encode_op(value), deadline=broker.Deadline.after_ms(1000))
            thread.join(1)
            assert not thread.is_alive()
            # Existing broker maps a socket read timeout to uncertain transport.
            assert isinstance(errors[0], (broker.DeadlineExceeded, broker.TransportUncertain))
            assert time.monotonic() - start < 0.16
            assert vault.snapshot() == []


def test_deadline_is_checked_after_strict_decode_before_dispatch(tmp_path, monkeypatch):
    import time
    from app.workers import credential_gateway_service as service_module
    from app.workers.credential_channel import encode_op
    from app.workers.credential_contracts import b64u
    args = initialized(tmp_path)
    original = service_module.decode_op
    def slow(payload):
        value = original(payload)
        time.sleep(0.08)
        return value
    monkeypatch.setattr(service_module, "decode_op", slow)
    with CredentialVault(**args) as vault, authenticated_pair(tmp_path) as (left, cc, right, sc, spec, boot):
        request = dict(schema="credential-op-v2", op="store_at", metadata=metadata(), secret_b64u=b64u(b"synthetic"))
        cc.write(left, message_id=str(uuid4()), correlation_id=None, message_type="credential_op", payload=encode_op(request), deadline=broker.Deadline.after_ms(1000))
        with pytest.raises(broker.DeadlineExceeded):
            CredentialGatewayService(vault, spec, boot).serve_one(right, sc, deadline=broker.Deadline.after_ms(30))
        assert vault.snapshot() == []


def test_actual_snapshot_response_fragments_and_overflow_refuses(subject):
    vault, client, _, _ = subject
    for _ in range(64):
        vault.store_at(metadata=metadata(), secret=b"synthetic-snapshot")
    expected = vault.snapshot()
    assert len(json.dumps(expected)) > 16384
    assert client.snapshot() == expected
    for _ in range(336):
        vault.store_at(metadata=metadata(), secret=b"synthetic-snapshot")
    assert len(json.dumps(vault.snapshot(), separators=(",", ":"))) > 102400
    with pytest.raises(GatewayServiceError):
        client.snapshot()
    assert vault.health()["stored_unbound"] == 400
