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
    vault = CredentialVault(str(tmp_path / "vault"))
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


def test_store_round_trips_with_a_redacted_receipt(subject):
    vault, client, _threads, _wire = subject
    receipt = client.submit(
        intent_id=INTENT, provider="claude",
        secret=SECRET.encode("utf-8"), rotate_from=None,
    )
    assert set(receipt) == {"handle", "provider", "state"}
    assert receipt["provider"] == "claude"
    assert receipt["state"] == "active"
    assert SECRET not in json.dumps(receipt)
    assert vault.resolve_for_gateway(receipt["handle"]) == SECRET.encode("utf-8")


def test_responses_never_carry_secret_bytes_on_the_wire(subject):
    _vault, client, _threads, wire_log = subject
    client.submit(
        intent_id=INTENT, provider="claude",
        secret=SECRET.encode("utf-8"), rotate_from=None,
    )
    responses = [payload for direction, payload in wire_log if direction == "out"]
    assert responses  # the service logged its outbound payloads
    for payload in responses:
        assert SECRET.encode("utf-8") not in payload


def test_delete_performs_retire_and_erase(subject):
    vault, client, _threads, _wire = subject
    receipt = client.submit(
        intent_id=INTENT, provider="claude",
        secret=SECRET.encode("utf-8"), rotate_from=None,
    )
    outcome = client.delete(receipt["handle"])
    assert outcome == {"handle": receipt["handle"], "state": "erasure_completed"}
    assert vault.health() == {
        "active": 0, "cleanup_pending": 0, "secret_input_lost": 0,
    }


def test_snapshot_is_redacted_and_read_only(subject):
    vault, client, _threads, _wire = subject
    receipt = client.submit(
        intent_id=INTENT, provider="claude",
        secret=SECRET.encode("utf-8"), rotate_from=None,
    )
    snapshot = client.snapshot()
    assert snapshot == [{
        "handle": receipt["handle"], "provider": "claude", "state": "active",
    }]
    assert vault.health()["active"] == 1


def test_conflicts_and_unknown_operations_are_sanitized(subject):
    _vault, client, _threads, _wire = subject
    client.submit(
        intent_id=INTENT, provider="claude",
        secret=SECRET.encode("utf-8"), rotate_from=None,
    )
    with pytest.raises(GatewayServiceError) as failure:
        client.submit(
            intent_id=INTENT, provider="claude",
            secret=b"sk-different-secret", rotate_from=None,
        )
    assert "sk-different" not in str(failure.value)
    assert SECRET not in str(failure.value)

    with pytest.raises(GatewayServiceError):
        client._call({"op": "resolve_for_gateway", "handle": "0" * 32})
    with pytest.raises(GatewayServiceError):
        client._call({"op": "unknown_operation"})
