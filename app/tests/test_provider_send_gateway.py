import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.refs import canonical_json
from app.tests.support.provider_semantic_harness import (
    connection_values,
    controlled_upstream,
    encrypted_credential,
)
from app.workers import broker
from app.workers.credential_channel import encode_op
from app.workers.credential_contracts import CredentialVaultError
from app.workers.credential_files import CustodyBudget
from app.workers.provider_gateway import CredentialedProviderTransport, ProviderBinding
from app.workers.provider_send_client import ProviderSendClient
from app.workers.provider_send_messages import (
    ProviderSendError,
    prepare_from_header,
    prepare_header,
    prepare_message,
)
from app.workers.provider_send_service import ProviderSendService


def authenticated_spec(root: Path):
    uid, gid = os.getuid(), os.getgid()
    distinct = lambda *values: next(value for value in range(31_001, 31_100) if value not in values)
    responder_uid = uid or distinct(uid)
    requester_uid = distinct(uid, responder_uid)
    pair_gid = next((value for value in (gid, *os.getgroups()) if value > 0), distinct(gid))
    return broker.ChannelSpec(channel_id="task47-provider-send", requester_service="control",
        responder_service="credential-gateway", request_direction="control-to-credential-gateway",
        protocol_id="credential-gateway-v1", requester_uid=requester_uid,
        requester_gid=distinct(gid, pair_gid), responder_uid=responder_uid,
        responder_gid=distinct(gid, pair_gid, requester_uid), pair_gid=pair_gid,
        pair_root=root, socket_name="provider-send.sock", root_uid=responder_uid,
        root_gid=pair_gid, socket_uid=responder_uid, socket_gid=pair_gid,
        requester_message_types=("credential_op",), responder_message_types=("credential_result",),
        max_queue_depth=1)


def binding(port):
    return ProviderBinding(provider="claude", scheme="http", host="127.0.0.1", port=port,
                           allowed_methods=("GET", "POST"), allowed_path_prefixes=("/v1",),
                           allowed_request_headers=("anthropic-version", "content-type"),
                           auth_header="x-api-key", max_request_bytes=1_048_576,
                           max_response_bytes=1_048_576, timeout_seconds=2)


def future_deadline(seconds=3_600):
    """An absolute deadline still ahead when the test runs (the wire's exact format);
    a fixed date here became a time bomb once the calendar passed it."""
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def prepared(meta, record, handle, pin, *, body=b"{}", remaining_ms=2000, deadline_at=None):
    deadline_at = future_deadline() if deadline_at is None else deadline_at
    return prepare_message(operation_ref={"kind": "validation_report", "id": str(uuid4()),
                           "version": 1, "sha256": "c" * 64}, request_id=str(uuid4()),
                           request_sha256="d" * 64,
                           selected_handle_ref=handle, connection_pin=pin,
                           credential_metadata=meta, credential_record=record,
                           endpoint="messages", after_id=None, body=body,
                           remaining_ms=remaining_ms, deadline_at=deadline_at,
                           reservation_ref={"kind": "validation_report",
                           "id": str(uuid4()), "version": 1, "sha256": "e" * 64})


def prepared_catalog(meta, record, handle, pin, *, after_id=None):
    return prepare_message(operation_ref={"kind": "validation_report", "id": str(uuid4()),
        "version": 1, "sha256": "c" * 64}, request_id=str(uuid4()), request_sha256="d" * 64,
        selected_handle_ref=handle, connection_pin=pin, credential_metadata=meta,
        credential_record=record, endpoint="models", after_id=after_id, body=b"",
        remaining_ms=2_000, deadline_at=future_deadline(), reservation_ref=None)


def test_prepare_header_rejects_boolean_sequence_before_body_admission(tmp_path):
    with encrypted_credential(tmp_path) as (_vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        message = prepared(meta, record, handle, pin)
        header = prepare_header(message)
        header["seq"] = False
        with pytest.raises(ProviderSendError, match="prepare body"):
            prepare_from_header(header, message.body)


def test_gateway_prepare_commit_revoke_and_replay(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin))
        assert captures == []
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        observation = service.exchange(lease)
        assert observation.phase == "terminal_observed" and len(captures) == 1
        with pytest.raises(ProviderSendError):
            service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        assert len(captures) == 1


def test_real_encrypted_custody_delivery_only_for_issued_lease(tmp_path):
    secret = b"synthetic-task47-sentinel"
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path, secret) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        assert service.exchange(lease).status == 200
        assert captures[0][2]["x-api-key"].encode() == secret
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        with pytest.raises(Exception):
            vault.resolve_for_gateway(record["record_id"])


def test_catalog_gateway_get_captures_exact_cursor_and_empty_body(tmp_path):
    raw = b'{"data":[],"first_id":null,"last_id":null,"has_more":false}'
    with controlled_upstream(response=(200, "application/json", raw)) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        prepared_value = prepared_catalog(meta, record, handle, pin, after_id="model-0")
        ready = service.prepare(prepared_value)
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        observation = service.exchange(lease)
        assert observation.body == raw and captures[0][0:2] == (
            "GET", "/v1/models?limit=100&after_id=model-0")
        assert captures[0][3] == b""


def test_two_encrypted_credentials_cannot_swap_bound_handle(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path, b"credential-a") as (vault, meta_a, record_a):
        meta_b = meta_a | {"command_id": str(uuid4()), "record_id": str(uuid4())}
        receipt_b = vault.store_at(metadata=meta_b, secret=b"credential-b")
        record_b = {key: receipt_b[key] for key in ("record_id", "record_version", "ciphertext_sha256")}
        handle, pin, _, _ = connection_values(meta_a, record_a)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        for bad_meta, bad_record in ((meta_b, record_b), (meta_a, record_b)):
            with pytest.raises(ProviderSendError):
                service.prepare(prepared(bad_meta, bad_record, handle, pin))
        assert captures == []


@pytest.mark.parametrize("boundary", [
    "rotate_before_prepare", "rotate_after_prepare", "rotate_after_commit",
    "retire_before_prepare", "retire_after_prepare", "retire_after_commit",
])
def test_rotation_and_revocation_boundaries_preserve_exact_lease_custody(tmp_path, boundary):
    secret_a, secret_b = b"credential-a", b"credential-b"
    with controlled_upstream(response=(200, "text/event-stream",
            b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path, secret_a) as (vault, meta_a, record_a):
        handle, pin, _, _ = connection_values(meta_a, record_a)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))

        def rotate():
            meta_b = meta_a | {"command_id": str(uuid4()), "record_id": str(uuid4()),
                               "predecessor": record_a}
            return vault.store_at(metadata=meta_b, secret=secret_b)

        def retire():
            return vault.retire(command_id=str(uuid4()), record=record_a,
                                reason="superseded")

        if boundary.endswith("before_prepare"):
            rotate() if boundary.startswith("rotate") else retire()
        ready = service.prepare(prepared(meta_a, record_a, handle, pin))
        if boundary.endswith("after_prepare"):
            rotate() if boundary.startswith("rotate") else retire()
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        if boundary.endswith("after_commit"):
            rotate() if boundary.startswith("rotate") else retire()

        if boundary.startswith("rotate"):
            assert service.exchange(lease).status == 200
            assert len(captures) == 1
            assert captures[0][2]["x-api-key"].encode() == secret_a
            assert secret_b not in repr(captures).encode()
        else:
            with pytest.raises(ProviderSendError):
                service.exchange(lease)
            assert captures == [] and not lease.write_event.is_set()


def test_actual_after_first_write_crash_is_may_have_sent_and_never_resends(
        tmp_path, monkeypatch):
    import http.client

    with controlled_upstream(response=(200, "application/json", b'{"data":[]}')) as (
            port, captures, _entered, _release), encrypted_credential(tmp_path) as (
            vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared_catalog(meta, record, handle, pin))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        original_endheaders = http.client.HTTPConnection.endheaders

        def crash_after_write(connection, *args, **kwargs):
            original_endheaders(connection, *args, **kwargs)
            raise OSError("test-owned crash after actual header write")

        monkeypatch.setattr(http.client.HTTPConnection, "endheaders", crash_after_write)
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        assert lease.write_event.is_set()
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        deadline = time.monotonic() + 1
        while not captures and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(captures) == 1


def test_cancel_while_upstream_blocks(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n"), blocked=True) as (port, captures, entered, release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=1000))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        result, failures = [], []
        def exchange():
            try:
                result.append(service.exchange(lease))
            except BaseException as exc:
                failures.append(exc)
        thread = threading.Thread(target=exchange)
        thread.start()
        assert entered.wait(1)
        assert service.status(lease.exchange_id) == "running"
        assert service.cancel(lease.exchange_id, "user_requested").accepted
        thread.join(2)
        release.set()
        assert not thread.is_alive() and result == [] and len(failures) == 1
        assert type(failures[0]) is ProviderSendError
        assert len(captures) == 1


def test_prepare_commit_and_bodies_cross_authenticated_frames_and_streams(tmp_path):
    response = b"event: ping\ndata: {}\n\n" + b" " * 70_000
    request = b'{"prompt":"' + b"x" * 70_000 + b'"}'
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(200, "text/event-stream", response)) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"k" * 32)
        threads, failures = [], []

        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            def serve():
                try:
                    session = broker._server_handshake_impl(right, spec, secret,
                        requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                        deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    try:
                        service.serve_authenticated(right, codec,
                            deadline=broker.Deadline.after_ms(5_000))
                    finally:
                        codec.close()
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    right.close()
            thread = threading.Thread(target=serve)
            thread.start(); threads.append(thread)
            session = broker._client_handshake_impl(left, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
            return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

        client = ProviderSendClient(transport_factory=factory, deadline_ms=5_000)
        message = prepared(meta, record, handle, pin, body=request, remaining_ms=5_000)
        header = prepare_header(message)
        assert header["body_descriptor"]["request_id"] == message.request_id
        assert len({message.request_id, message.operation_ref["id"], message.dialogue_id,
                    header["body_descriptor"]["batch_id"]}) == 4
        assert message.prepare_sha256 == sha256(canonical_json(header)).hexdigest()
        try:
            ready = client.prepare(message)
        except BaseException as failure:
            for thread in threads:
                thread.join(5)
            raise AssertionError(f"server failures: {failures!r}") from failure
        lease = client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        observation = client.exchange(lease)
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
        assert failures == []
        assert observation.body == response and observation.phase == "terminal_observed"
        assert captures[0][3] == request


def test_authenticated_bodyless_models_pages_pin_one_semantic_request_uuid(tmp_path):
    responses = [(200, "application/json", page)
                 for page in (__import__("app.tests.test_provider_semantic_codec",
                    fromlist=["page"]).page(["model-1"], more=True),
                    __import__("app.tests.test_provider_semantic_codec",
                    fromlist=["page"]).page(["model-2"]))]
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=responses) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"m" * 32)
        threads, failures = [], []
        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            def serve():
                try:
                    session = broker._server_handshake_impl(right, spec, secret,
                        requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                        deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    try: service.serve_authenticated(right, codec, deadline=broker.Deadline.after_ms(5_000))
                    finally: codec.close()
                except BaseException as exc: failures.append(exc)
                finally: right.close()
            thread = threading.Thread(target=serve); thread.start(); threads.append(thread)
            session = broker._client_handshake_impl(left, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
            return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)
        semantic_request_id = str(uuid4())
        operation_ref = {"kind": "validation_report", "id": str(uuid4()), "version": 1,
                         "sha256": "c" * 64}
        for after_id in (None, "model-1"):
            message = prepare_message(operation_ref=operation_ref, request_id=semantic_request_id,
                request_sha256="d" * 64, selected_handle_ref=handle, connection_pin=pin,
                credential_metadata=meta, credential_record=record, endpoint="models",
                after_id=after_id, body=b"", remaining_ms=5_000,
                deadline_at=future_deadline(), reservation_ref=None)
            assert prepare_header(message)["body_descriptor"] is None
            client = ProviderSendClient(transport_factory=factory, deadline_ms=5_000)
            try:
                ready = client.prepare(message)
            except BaseException as failure:
                for thread in threads: thread.join(5)
                raise AssertionError(f"server failures: {failures!r}") from failure
            lease = client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            assert client.exchange(lease).status == 200
        for thread in threads:
            thread.join(5); assert not thread.is_alive()
        assert failures == []
        assert [capture[1] for capture in captures] == [
            "/v1/models?limit=100", "/v1/models?limit=100&after_id=model-1"]


@pytest.mark.parametrize("mutation", ["descriptor", "missing_failure", "extra_failure",
    "unknown_failure", "boolean_failure", "complete_failure", "refused_after_send",
    "cancelled_without_latch", "boolean_status", "boolean_http", "unknown_phase",
    "boolean_cancel", "not_sent_with_response"])
def test_authenticated_result_failure_class_and_descriptor_are_closed(
        tmp_path, monkeypatch, mutation):
    import app.workers.provider_send_service as service_module

    response = b"event: ping\ndata: {}\n\n"
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(200, "text/event-stream", response)) as (
            port, captures, _entered, _release), encrypted_credential(
            tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"r" * 32)
        threads, failures, result_fields = [], [], []
        original_encode = service_module.encode_op

        def substituted_descriptor(value):
            if type(value) is dict and value.get("schema") == "provider-send-result-v1":
                value = dict(value)
                result_fields.append(set(value))
                if mutation == "descriptor":
                    value["response_descriptor"] = dict(value["response_descriptor"])
                    value["response_descriptor"]["request_id"] = str(uuid4())
                elif mutation == "missing_failure":
                    value.pop("failure_class")
                elif mutation == "extra_failure":
                    value["failure_detail"] = "forbidden"
                elif mutation == "unknown_failure":
                    value["failure_class"] = "unknown_category"
                elif mutation == "boolean_failure":
                    value["failure_class"] = False
                elif mutation == "complete_failure":
                    value["failure_class"] = "internal_failure"
                elif mutation == "refused_after_send":
                    value["status"] = "refused"
                elif mutation == "cancelled_without_latch":
                    value["status"] = "unknown"
                    value["failure_class"] = "cancelled"
                    value["cancel_observed"] = False
                elif mutation == "boolean_status":
                    value["status"] = True
                elif mutation == "boolean_http":
                    value["status"] = "unknown"
                    value["http_status"] = True
                elif mutation == "unknown_phase":
                    value["phase"] = "later"
                elif mutation == "boolean_cancel":
                    value["cancel_observed"] = 0
                else:
                    value["status"] = "refused"
                    value["phase"] = "not_sent"
            return original_encode(value)

        monkeypatch.setattr(service_module, "encode_op", substituted_descriptor)

        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            def serve():
                try:
                    session = broker._server_handshake_impl(right, spec, secret,
                        requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                        deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    try:
                        service.serve_authenticated(right, codec,
                            deadline=broker.Deadline.after_ms(5_000))
                    finally:
                        codec.close()
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    right.close()
            thread = threading.Thread(target=serve)
            thread.start(); threads.append(thread)
            session = broker._client_handshake_impl(left, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
            return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

        client = ProviderSendClient(transport_factory=factory, deadline_ms=5_000)
        message = prepared(meta, record, handle, pin, remaining_ms=5_000)
        ready = client.prepare(message)
        with pytest.raises(ProviderSendError):
            client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()
        assert len(captures) == 1 and client._channel is None
        assert all(type(failure) is ProviderSendError for failure in failures)
        assert len(result_fields) == 1
        assert "response_descriptor" in result_fields[0]
        assert "body_descriptor" not in result_fields[0] and "failure_class" in result_fields[0]


@pytest.mark.parametrize("case", ["unknown_http_200", "complete_http_503"])
def test_authenticated_result_accepts_incomplete_or_non2xx_without_local_cause(
        tmp_path, monkeypatch, case):
    import app.workers.provider_send_service as service_module

    status = 200 if case == "unknown_http_200" else 503
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(status, "text/event-stream", b"bounded-response")) as (
            port, captures, _entered, _release), encrypted_credential(
            tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"u" * 32)
        threads, failures = [], []
        original_encode = service_module.encode_op

        def preserve_wire_evidence(value):
            if type(value) is dict and value.get("schema") == "provider-send-result-v1":
                value = {**value, "status": ("unknown" if status == 200 else "complete"),
                         "failure_class": None}
            return original_encode(value)

        monkeypatch.setattr(service_module, "encode_op", preserve_wire_evidence)

        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            def serve():
                try:
                    session = broker._server_handshake_impl(right, spec, secret,
                        requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                        deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    try:
                        service.serve_authenticated(right, codec,
                            deadline=broker.Deadline.after_ms(5_000))
                    finally:
                        codec.close()
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    right.close()
            thread = threading.Thread(target=serve)
            thread.start(); threads.append(thread)
            session = broker._client_handshake_impl(left, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
            return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

        client = ProviderSendClient(transport_factory=factory, deadline_ms=5_000)
        message = prepared(meta, record, handle, pin, remaining_ms=5_000)
        ready = client.prepare(message)
        lease = client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        observed = client.exchange(lease)
        assert observed.status == status and observed.failure_class is None
        assert observed.body == b"bounded-response"
        for thread in threads:
            thread.join(2); assert not thread.is_alive()
        assert failures == [] and len(captures) == 1


@pytest.mark.parametrize("case", ["permission", "capacity", "media", "dependency", "non2xx"])
def test_authenticated_gateway_failure_class_reaches_core_without_diagnostics(
        tmp_path, monkeypatch, case):
    import http.client

    response = ((503, "application/json", b'{"error":"unavailable"}') if case == "non2xx"
        else (200, "application/octet-stream", b"media-bytes") if case == "media"
        else (200, "text/event-stream", b"x" * 128))
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=response) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        provider_binding = binding(port)
        if case == "capacity":
            provider_binding = replace(provider_binding, max_response_bytes=32)
        service = ProviderSendService(CredentialedProviderTransport(vault, provider_binding))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"v" * 32)
        threads, failures = [], []
        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            def serve():
                try:
                    session = broker._server_handshake_impl(right, spec, secret,
                        requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                        deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    try:
                        service.serve_authenticated(right, codec,
                            deadline=broker.Deadline.after_ms(5_000))
                    finally:
                        codec.close()
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    right.close()
            thread = threading.Thread(target=serve); thread.start(); threads.append(thread)
            session = broker._client_handshake_impl(left, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
            return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

        client = ProviderSendClient(transport_factory=factory, deadline_ms=5_000)
        ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
        if case == "permission":
            vault.retire(command_id=str(uuid4()), record=record, reason="superseded")
        elif case == "dependency":
            monkeypatch.setattr(http.client.HTTPConnection, "endheaders",
                                lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
        lease = client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        observed = client.exchange(lease)
        expected = {"permission": "permission_denied", "capacity": "resource_exhausted",
                    "media": "unsupported_capability", "dependency": "dependency_unavailable",
                    "non2xx": None}[case]
        assert observed.failure_class == expected
        assert "dispatcher-secret" not in repr(observed)
        if case == "permission":
            assert observed.phase == "not_sent" and observed.status is None and observed.body == b""
        elif case == "capacity":
            assert observed.status == 200 and observed.body == b"x" * 32
        elif case == "media":
            assert observed.status == 200 and observed.body == b"media-bytes"
        elif case == "dependency":
            assert observed.phase == "may_have_sent" and observed.status is None
        else:
            assert observed.status == 503 and observed.body == b'{"error":"unavailable"}'
        for thread in threads:
            thread.join(2); assert not thread.is_alive()
        assert failures == [] and len(captures) == (0 if case in {"permission", "dependency"} else 1)


def test_prepare_semantic_request_identity_is_closed_and_digest_bound(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"")) as (
            port, captures, _entered, _release), encrypted_credential(tmp_path) as (
            vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        message = prepared(meta, record, handle, pin)
        header = prepare_header(message)
        changed = dict(header); changed["request_id"] = str(uuid4())
        with pytest.raises(ProviderSendError):
            prepare_from_header(changed, message.body)
        coherent = dict(header); coherent["request_id"] = str(uuid4())
        coherent["body_descriptor"] = {**header["body_descriptor"],
                                       "request_id": coherent["request_id"]}
        changed_message = prepare_from_header(coherent, message.body)
        assert changed_message.prepare_sha256 != message.prepare_sha256
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(changed_message)
        with pytest.raises(ProviderSendError):
            service.commit(ready["exchange_id"], message.prepare_sha256, str(uuid4()))
        assert captures == []
        with pytest.raises(ProviderSendError):
            prepare_message(operation_ref=message.operation_ref, request_id="not-a-uuid",
                request_sha256=message.request_sha256, selected_handle_ref=handle,
                connection_pin=pin, credential_metadata=meta, credential_record=record,
                endpoint="messages", after_id=None, body=b"{}", remaining_ms=1000,
                deadline_at=message.deadline_at, reservation_ref=message.reservation_ref)


@pytest.mark.parametrize("mutation", [
    "dialogue", "sequence", "boolean_sequence", "exchange", "prepare_fence", "correlation",
])
def test_authenticated_commit_envelope_session_sequence_and_fence_refuse(tmp_path, mutation):
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(200, "text/event-stream",
            b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"f" * 32)
        threads, failures = [], []

        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            def serve():
                try:
                    session = broker._server_handshake_impl(right, spec, secret,
                        requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                        deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    try:
                        service.serve_authenticated(right, codec,
                            deadline=broker.Deadline.after_ms(5_000))
                    finally:
                        codec.close()
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    right.close()
            thread = threading.Thread(target=serve)
            thread.start(); threads.append(thread)
            session = broker._client_handshake_impl(left, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
            return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

        client = ProviderSendClient(transport_factory=factory, deadline_ms=5_000)
        message = prepared(meta, record, handle, pin, remaining_ms=5_000)
        ready = client.prepare(message)
        channel = client._channel
        commit = {"schema": "provider-send-commit-v1",
            "dialogue_id": channel["dialogue_id"], "seq": 1,
            "exchange_id": ready["exchange_id"], "prepare_sha256": ready["prepare_sha256"],
            "commit_id": str(uuid4()), "remaining_ms": 1_000}
        correlation_id = channel["start_id"]
        if mutation == "dialogue": commit["dialogue_id"] = str(uuid4())
        elif mutation == "sequence": commit["seq"] = 2
        elif mutation == "boolean_sequence": commit["seq"] = True
        elif mutation == "exchange": commit["exchange_id"] = str(uuid4())
        elif mutation == "prepare_fence": commit["prepare_sha256"] = "0" * 64
        elif mutation == "correlation": correlation_id = str(uuid4())
        channel["codec"].write(channel["sock"], message_id=str(uuid4()),
            correlation_id=correlation_id, message_type="credential_op",
            payload=encode_op(commit), deadline=channel["deadline"])
        threads[0].join(2)
        client._close()
        assert not threads[0].is_alive()
        assert len(failures) == 1 and type(failures[0]) is ProviderSendError
        assert captures == [] and service._pending == {} and service._states == {}


def test_one_deadline_bounds_real_vault_rlock_contention_before_any_write(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=100))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        held, release = threading.Event(), threading.Event()
        def block():
            with vault._lifetime:
                held.set(); release.wait(2)
        thread = threading.Thread(target=block)
        thread.start(); assert held.wait(1)
        started = time.monotonic()
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        elapsed = time.monotonic() - started
        release.set(); thread.join(1)
        assert not thread.is_alive() and elapsed < 0.75 and captures == []


def test_one_deadline_bounds_real_flock_contention_before_any_write(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=100))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        lock_path = Path(vault._root._records.path) / "mutation.lock"
        holder = subprocess.Popen([sys.executable, "-c", """
import fcntl, sys
with open(sys.argv[1], 'r+b', buffering=0) as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    print('ready', flush=True)
    sys.stdin.read(1)
""", str(lock_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert holder.stdout.readline().strip() == "ready"
        started = time.monotonic()
        try:
            with pytest.raises(ProviderSendError):
                service.exchange(lease)
        finally:
            holder.stdin.write("x"); holder.stdin.flush(); holder.wait(2)
        assert holder.returncode == 0 and time.monotonic() - started < 0.75 and captures == []


def test_budgeted_delivery_refuses_real_sqlite_contention_without_retry_or_write(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=500))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        database = Path(vault._root._records.path) / "journal.sqlite"
        blocker = sqlite3.connect(database, timeout=0, isolation_level=None)
        blocker.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        try:
            with pytest.raises(ProviderSendError):
                service.exchange(lease)
        finally:
            blocker.execute("ROLLBACK"); blocker.close()
        assert time.monotonic() - started < 0.75 and captures == []


def test_delivery_validates_the_full_journal_and_rejects_a_malformed_sibling(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path, b"credential-a") as (vault, meta, record):
        sibling = meta | {"command_id": str(uuid4()), "record_id": str(uuid4())}
        vault.store_at(metadata=sibling, secret=b"credential-b")
        database = Path(vault._root._records.path) / "journal.sqlite"
        with sqlite3.connect(database) as db:
            db.execute("UPDATE commands SET metadata=? WHERE command_id=?", (b"{}", sibling["command_id"]))
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=500))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        assert captures == []


def test_post_acquire_cancel_checkpoint_releases_vault_lifetime(tmp_path, monkeypatch):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=500))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        original = CustodyBudget.checkpoint
        calls = 0
        def cancel_at_post_acquire(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                lease.cancel_event.set()
            return original(value)
        monkeypatch.setattr(CustodyBudget, "checkpoint", cancel_at_post_acquire)
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        acquired = []
        def probe():
            with vault._lifetime:
                acquired.append(True)
        thread = threading.Thread(target=probe)
        thread.start(); thread.join(1)
        assert acquired == [True] and not thread.is_alive() and captures == []


def test_cancellation_during_full_metadata_scan_aborts_before_secret_or_write(tmp_path,
                                                                              monkeypatch):
    import app.workers.credential_journal as journal_module

    with controlled_upstream(response=(200, "text/event-stream",
            b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path, b"credential-a") as (vault, meta, record):
        for _ in range(4):
            sibling = meta | {"command_id": str(uuid4()), "record_id": str(uuid4()),
                              "predecessor": None}
            vault.store_at(metadata=sibling, secret=b"credential-sibling")
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        original = journal_module.metadata_value
        calls = []

        def cancel_inside_command_scan(value):
            checked = original(value)
            calls.append(checked["command_id"])
            if len(calls) == 2:
                lease.cancel_event.set()
            return checked

        monkeypatch.setattr(journal_module, "metadata_value", cancel_inside_command_scan)
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        assert len(calls) == 2 and captures == [] and service._states == {}


def test_sqlite_progress_handler_interrupts_active_validation_query(tmp_path, monkeypatch):
    from app.workers.credential_journal import Journal

    query_entered, interrupted = threading.Event(), []
    with controlled_upstream(response=(200, "text/event-stream",
            b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path, b"credential-a") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))

        def long_validation_query(self, layout, *, custody_budget=None):
            assert custody_budget is not None
            query_entered.set()
            try:
                self.connection.execute("WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL "
                    "SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n").fetchone()
            except sqlite3.OperationalError as exc:
                interrupted.append(getattr(exc, "sqlite_errorcode", None))
                raise
            raise AssertionError("test-owned validation query was not interrupted")

        monkeypatch.setattr(Journal, "_validate_metadata", long_validation_query)
        canceller = threading.Thread(target=lambda: (
            query_entered.wait(1) and lease.cancel_event.set()))
        canceller.start()
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        canceller.join(1)
        assert not canceller.is_alive()
        assert interrupted == [sqlite3.SQLITE_INTERRUPT]
        assert captures == [] and service._states == {}


def test_ready_cancel_revokes_commit_and_never_writes(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin))
        cancelled = service.cancel(ready["exchange_id"], "user_requested")
        assert cancelled.accepted and cancelled.phase == "not_sent"
        with pytest.raises(ProviderSendError):
            service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        assert captures == []


def test_prepare_deadline_is_not_refreshed_by_delayed_commit(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=50))
        time.sleep(0.075)
        with pytest.raises(ProviderSendError):
            service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        assert captures == []


def test_shorter_absolute_deadline_is_consumed_by_setup_and_cannot_be_lengthened(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream",
            b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        absolute = (datetime.now(timezone.utc) + timedelta(milliseconds=80)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        message = prepared(meta, record, handle, pin, remaining_ms=2_000,
                           deadline_at=absolute)
        time.sleep(0.100)
        with pytest.raises(ProviderSendError, match="deadline elapsed"):
            service.prepare(message)

        absolute = (datetime.now(timezone.utc) + timedelta(milliseconds=160)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        ready = service.prepare(prepared(meta, record, handle, pin,
            remaining_ms=2_000, deadline_at=absolute))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"],
                               str(uuid4()), ready["remaining_ms"])
        assert lease.deadline_monotonic - time.monotonic() < 0.160
        time.sleep(0.180)
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        assert captures == []


def test_authenticated_gateway_body_receipt_uses_prepare_deadline_before_ready(tmp_path):
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(200, "text/event-stream", b"unused")) as (
            port, captures, _entered, _release), encrypted_credential(
            tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"y" * 32)
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        failures = []

        def serve():
            try:
                session = broker._server_handshake_impl(right, spec, secret,
                    requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                    deadline=broker.Deadline.after_ms(2_000), verify_peer=False)
                codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                try:
                    service.serve_authenticated(right, codec,
                        deadline=broker.Deadline.after_ms(2_000))
                finally:
                    codec.close()
            except BaseException as exc:
                failures.append(exc)
            finally:
                right.close()

        thread = threading.Thread(target=serve)
        thread.start()
        session = broker._client_handshake_impl(left, spec, secret,
            requester_boot_id="task47-control", responder_boot_id="task47-gateway",
            deadline=broker.Deadline.after_ms(2_000), verify_peer=False)
        codec = broker.FrameCodec(spec, session, local_service=spec.requester_service)
        message = prepared(meta, record, handle, pin, body=b"withheld-body", remaining_ms=120)
        codec.write(left, message_id=str(uuid4()), correlation_id=None,
            message_type="credential_op", payload=encode_op(prepare_header(message)),
            deadline=broker.Deadline.after_ms(2_000))
        try:
            thread.join(0.6)
            assert not thread.is_alive(), "gateway retained the outer broker body deadline"
        finally:
            try:
                left.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            left.close(); thread.join(2)
        assert len(failures) == 1 and type(failures[0]) is ProviderSendError
        assert service._pending == {} and service._states == {} and captures == []


def test_post_custody_lazy_connect_and_response_socket_use_short_remaining_timeout(
        tmp_path, monkeypatch):
    import http.client

    with controlled_upstream(response=(200, "text/event-stream",
            b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=600))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        original_delivery = type(vault).delivery_for_exchange
        original_endheaders = http.client.HTTPConnection.endheaders
        observed = []

        @contextmanager
        def delayed_custody(subject, exact_lease):
            with original_delivery(subject, exact_lease) as secret:
                time.sleep(0.150)
                yield secret

        def observe_lazy_timeout(connection, *args, **kwargs):
            observed.append((connection.timeout,
                             lease.deadline_monotonic - time.monotonic()))
            return original_endheaders(connection, *args, **kwargs)

        monkeypatch.setattr(type(vault), "delivery_for_exchange", delayed_custody)
        monkeypatch.setattr(http.client.HTTPConnection, "endheaders", observe_lazy_timeout)
        observation = service.exchange(lease)
        assert observation.status == 200
        configured, remaining = observed[0]
        assert 0 < configured <= remaining + 0.030
        assert len(captures) == 1


@contextmanager
def authenticated_service_pair(tmp_path, service):
    """Keep the peer open until assertions finish; never let peer closure enforce a deadline."""
    spec, secret = authenticated_spec(tmp_path / "r4-pair"), broker.BootSecret(b"4" * 32)
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    failures = []
    def serve():
        try:
            session = broker._server_handshake_impl(right, spec, secret,
                requester_boot_id="r4-core", responder_boot_id="r4-gateway",
                deadline=broker.Deadline.after_ms(2_000), verify_peer=False)
            codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
            try:
                service.serve_authenticated(right, codec, deadline=broker.Deadline.after_ms(2_000))
            finally:
                codec.close()
        except BaseException as exc:
            failures.append(exc)
        finally:
            right.close()
    server = threading.Thread(target=serve)
    server.start()
    session = broker._client_handshake_impl(left, spec, secret,
        requester_boot_id="r4-core", responder_boot_id="r4-gateway",
        deadline=broker.Deadline.after_ms(2_000), verify_peer=False)
    codec = broker.FrameCodec(spec, session, local_service=spec.requester_service)
    try:
        yield left, codec, server, failures
    finally:
        codec.close()
        left.close()
        server.join(2)
        assert not server.is_alive()


def test_authenticated_ready_budget_includes_time_spent_receiving_body(tmp_path, monkeypatch):
    import app.workers.provider_send_service as service_module
    with encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(1)))
        original_receive = service_module.receive_batch
        def delayed_body_receipt(*args, **kwargs):
            # Core is blocked waiting for stream credit during this actual body transfer.
            time.sleep(0.350)
            return original_receive(*args, **kwargs)
        monkeypatch.setattr(service_module, "receive_batch", delayed_body_receipt)
        with authenticated_service_pair(tmp_path, service) as (sock, codec, _server, _failures):
            client = ProviderSendClient(transport_factory=lambda: (sock, codec), deadline_ms=600)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=600))
            assert 0 < ready["remaining_ms"] <= 250, "READY refreshed the body-consumed budget"
            assert service._pending[ready["exchange_id"]][1] - time.monotonic() <= 0.250
            client._close()


@pytest.mark.parametrize("boundary", ["expired_custody", "cleanup", "result_stream"])
def test_authenticated_short_commit_bounds_wire_and_cleanup(tmp_path, monkeypatch, boundary):
    from app.workers.credential_channel import decode_op
    response = b"event: ping\ndata: {}\n\n"
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(200, "text/event-stream", response)) as (
            port, captures, _entered, _release), encrypted_credential(tmp_path / "custody") as (
            vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        entered, release = threading.Event(), threading.Event()
        original_delivery = type(vault).delivery_for_exchange
        @contextmanager
        def bounded_custody(subject, lease):
            with original_delivery(subject, lease) as secret:
                entered.set()
                if boundary == "cleanup":
                    assert release.wait(2), "test-owned custody barrier was not released"
                else:
                    time.sleep(max(0, lease.deadline_monotonic - time.monotonic()) + 0.040)
                yield secret
        if boundary != "result_stream":
            monkeypatch.setattr(type(vault), "delivery_for_exchange", bounded_custody)
        with authenticated_service_pair(tmp_path, service) as (sock, codec, server, failures):
            client = ProviderSendClient(transport_factory=lambda: (sock, codec), deadline_ms=2_000)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=2_000))
            channel = client._channel
            codec.write(sock, message_id=str(uuid4()), correlation_id=channel["start_id"],
                message_type="credential_op", payload=encode_op({
                    "schema": "provider-send-commit-v1", "dialogue_id": channel["dialogue_id"],
                    "seq": 1, "exchange_id": ready["exchange_id"],
                    "prepare_sha256": ready["prepare_sha256"], "commit_id": str(uuid4()),
                    "remaining_ms": 400 if boundary == "result_stream" else 80}),
                deadline=broker.Deadline.after_ms(1_000))
            try:
                if boundary == "result_stream":
                    frame = codec.read(sock, deadline=broker.Deadline.after_ms(400))
                    assert decode_op(frame.payload)["schema"] == "provider-send-result-v1"
                    # Withhold artifact credit while the peer remains open.
                    server.join(0.600)
                    assert not server.is_alive(), "result transfer kept the pre-commit budget"
                    assert len(captures) == 1
                else:
                    assert entered.wait(0.500)
                    server.join(0.300)
                    assert not server.is_alive(), "cleanup retained the pre-commit budget"
                    sock.settimeout(0.200)
                    assert sock.recv(1) == b"", "expired commit emitted an extra error frame"
                    assert captures == []
                    if boundary == "cleanup":
                        assert service._usable is False
                        with pytest.raises(ProviderSendError, match="unavailable after unsafe cleanup"):
                            service.prepare(prepared(meta, record, handle, pin))
                assert len(failures) == 1 and type(failures[0]) is ProviderSendError
            finally:
                release.set()
                for thread in threading.enumerate():
                    if thread.name == "provider-send-exchange":
                        thread.join(1)
                        assert not thread.is_alive()


def test_original_deadline_is_rechecked_after_custody_before_first_write(tmp_path,
                                                                         monkeypatch):
    with controlled_upstream(response=(200, "text/event-stream",
            b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin, remaining_ms=120))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        original_delivery = type(vault).delivery_for_exchange

        @contextmanager
        def delayed_custody(subject, exact_lease):
            with original_delivery(subject, exact_lease) as secret:
                time.sleep(max(0.0, exact_lease.deadline_monotonic - time.monotonic()) + 0.020)
                yield secret

        monkeypatch.setattr(type(vault), "delivery_for_exchange", delayed_custody)
        with pytest.raises(ProviderSendError) as caught:
            service.exchange(lease)
        assert caught.value.failure_class == "deadline_exceeded"
        assert caught.value.phase == "not_sent"
        assert captures == [] and not lease.write_event.is_set()


@pytest.mark.parametrize(("custody_code", "failure_class"), [
    ("cancelled", "cancelled"),
    ("deadline_exceeded", "deadline_exceeded"),
    ("provider_binding_unavailable", "permission_denied"),
    ("maintenance_required", "integrity_failed"),
    ("busy", "dependency_unavailable"),
    ("closed", "dependency_unavailable"),
    ("storage_failure", "dependency_unavailable"),
    ("unclassified_local_cause", "internal_failure"),
    ("invalid_metadata", "integrity_failed"),
    ("record_identity_mismatch", "integrity_failed"),
    ("authentication_failed", "integrity_failed"),
    ("invalid_envelope", "integrity_failed"),
    ("invalid_encoding", "integrity_failed"),
    ("invalid_secret", "integrity_failed"),
])
def test_custody_rejections_retain_typed_gateway_failure_class(
        tmp_path, monkeypatch, custody_code, failure_class):
    with encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(1)))
        ready = service.prepare(prepared(meta, record, handle, pin))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))

        @contextmanager
        def reject_custody(_subject, _lease):
            raise CredentialVaultError(custody_code)
            yield  # pragma: no cover - contextmanager shape only

        monkeypatch.setattr(type(vault), "delivery_for_exchange", reject_custody)
        with pytest.raises(ProviderSendError) as caught:
            service.exchange(lease)
        assert caught.value.failure_class == failure_class
        assert caught.value.phase == "not_sent"
        assert not lease.write_event.is_set()


@pytest.mark.parametrize("producer", ["busy", "closed", "storage_failure"])
def test_actual_custody_producers_cross_authenticated_gateway_as_dependency(
        tmp_path, monkeypatch, producer):
    (tmp_path / "custody").mkdir()
    with controlled_upstream() as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        blocker = None
        if producer == "busy":
            blocker = sqlite3.connect(Path(vault._root._records.path) / "journal.sqlite",
                                      timeout=0, isolation_level=None)
            blocker.execute("BEGIN EXCLUSIVE")
        elif producer == "closed":
            vault.close()
        else:
            def failed_file_read(_subject, _metadata):
                raise OSError("test-owned published-file read failure")
            monkeypatch.setattr(type(vault), "_published", failed_file_read)
        produced = []
        original_delivery = type(vault).delivery_for_exchange
        @contextmanager
        def capture_actual_custody_error(subject, lease):
            try:
                with original_delivery(subject, lease) as secret:
                    yield secret
            except CredentialVaultError as exc:
                produced.append(exc.code)
                raise
        monkeypatch.setattr(type(vault), "delivery_for_exchange", capture_actual_custody_error)
        try:
            with authenticated_service_pair(tmp_path, service) as (sock, codec, server, failures):
                client = ProviderSendClient(transport_factory=lambda: (sock, codec), deadline_ms=1_000)
                ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=1_000))
                lease = client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
                observed = client.exchange(lease)
                assert observed.failure_class == "dependency_unavailable"
                assert observed.phase == "not_sent" and observed.status is None
                assert observed.body == b"" and not observed.cancel_observed
                server.join(1)
                assert not server.is_alive() and failures == []
            assert produced == [producer] and captures == []
            assert service._states == {} and service._pending == {}
        finally:
            if blocker is not None:
                blocker.execute("ROLLBACK")
                blocker.close()


def test_issued_lease_rejects_mutated_frozen_projection_and_registry_is_bounded(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        lease.connection_pin["account_id"] = "mutated"
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        assert captures == [] and service._states == {}

        for _ in range(2):
            ready = service.prepare(prepared(meta, record, handle, pin))
            lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            assert service.exchange(lease).status == 200
            assert service._states == {}


def test_lease_is_one_shot_value_and_session_bound_across_instances(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream",
            b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        foreign = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared(meta, record, handle, pin))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        with pytest.raises(ProviderSendError):
            foreign.exchange(lease)
        copied = replace(lease)
        with pytest.raises(ProviderSendError):
            service.exchange(copied)
        cross_issued = replace(lease, _issuer=foreign)
        with pytest.raises(ProviderSendError):
            service.exchange(cross_issued)
        assert captures == []
        assert service.exchange(lease).status == 200 and len(captures) == 1
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
        assert len(captures) == 1 and service._states == {} and foreign._states == {}


def test_http_profile_omits_accept_encoding_and_requires_exact_media(tmp_path):
    (tmp_path / "exact").mkdir()
    with controlled_upstream(response=(200, "application/json", b'{"data":[],"first_id":null,"last_id":null,"has_more":false}')) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path / "exact") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        ready = service.prepare(prepared_catalog(meta, record, handle, pin))
        assert service.exchange(service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))).status == 200
        request_headers = {name.lower(): value for name, value in captures[0][2].items()}
        assert "accept-encoding" not in request_headers
        assert request_headers["anthropic-version"] == "2023-06-01"
        assert request_headers["content-type"] == "application/json"

    for response in ((200, None, b"{}"),
                     (200, "application/json", b"{}", {"content-encoding": "gzip"})):
        path = tmp_path / str(uuid4()); path.mkdir()
        with controlled_upstream(response=response) as (port, _captures, _entered, _release), \
                encrypted_credential(path) as (vault, meta, record):
            handle, pin, _, _ = connection_values(meta, record)
            service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
            ready = service.prepare(prepared_catalog(meta, record, handle, pin))
            lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            observed = service.exchange(lease)
            assert observed.failure_class == "unsupported_capability"
            assert observed.status == 200 and observed.body == b"{}"


def test_core_send_client_import_does_not_load_gateway_or_vault():
    script = """
import sys
import app.workers.provider_send_client
assert 'app.workers.provider_send_service' not in sys.modules
assert 'app.workers.provider_gateway' not in sys.modules
assert 'app.workers.credential_vault' not in sys.modules
"""
    completed = subprocess.run([sys.executable, "-B", "-c", script], cwd=Path(__file__).parents[2],
                               text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr


def test_registry_lock_is_not_taken_while_vault_exclusion_is_held(tmp_path, monkeypatch):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, _captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        observed = []
        original_lock = service._lock
        class InspectedLock:
            def __enter__(self):
                observed.append(vault._lifetime._is_owned())
                return original_lock.__enter__()
            def __exit__(self, *args):
                return original_lock.__exit__(*args)
        service._lock = InspectedLock()
        ready = service.prepare(prepared(meta, record, handle, pin))
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        assert service.exchange(lease).status == 200
        assert observed and not any(observed)


def test_authenticated_cancel_owns_blocked_http_and_cleans_dialogue(tmp_path):
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n"),
                             blocked=True) as (port, captures, entered, release), \
            encrypted_credential(tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"z" * 32)
        server_threads, server_failures = [], []
        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            def serve():
                try:
                    session = broker._server_handshake_impl(right, spec, secret,
                        requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                        deadline=broker.Deadline.after_ms(2_000), verify_peer=False)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    try:
                        service.serve_authenticated(right, codec,
                            deadline=broker.Deadline.after_ms(2_000))
                    finally:
                        codec.close()
                except BaseException as exc:
                    server_failures.append(exc)
                finally:
                    right.close()
            thread = threading.Thread(target=serve)
            thread.start(); server_threads.append(thread)
            session = broker._client_handshake_impl(left, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                deadline=broker.Deadline.after_ms(2_000), verify_peer=False)
            return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

        client = ProviderSendClient(transport_factory=factory, deadline_ms=2_000)
        ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=2_000))
        completed, failed = [], []
        def commit():
            try:
                completed.append(client.commit(ready["exchange_id"], ready["prepare_sha256"],
                                               str(uuid4())))
            except BaseException as exc:
                failed.append(exc)
        thread = threading.Thread(target=commit)
        thread.start(); assert entered.wait(1)
        started = time.monotonic()
        cancellation = client.cancel(ready["exchange_id"], "user_requested")
        elapsed = time.monotonic() - started
        thread.join(1); release.set()
        for server_thread in server_threads:
            server_thread.join(1)
        assert cancellation.accepted and cancellation.phase == "may_have_sent"
        assert elapsed < 0.5 and not thread.is_alive() and len(completed) == 1 and failed == []
        observation = client.exchange(completed[0])
        assert observation.cancel_observed and observation.phase == "may_have_sent"
        assert service._pending == {} and service._states == {}
        assert all(not item.is_alive() for item in server_threads) and server_failures == []
        assert len(captures) == 1


def test_cancel_routes_during_gateway_result_stream(tmp_path, monkeypatch):
    import app.workers.provider_send_client as client_module

    response = b"event: ping\ndata: {}\n\n" + b"x" * 70_000
    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(200, "text/event-stream", response)) as (
            port, captures, _entered, _release), encrypted_credential(
            tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"s" * 32)
        servers, failures = [], []

        def factory():
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            def serve():
                try:
                    session = broker._server_handshake_impl(right, spec, secret,
                        requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                        deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    try:
                        service.serve_authenticated(right, codec,
                            deadline=broker.Deadline.after_ms(5_000))
                    finally:
                        codec.close()
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    right.close()
            thread = threading.Thread(target=serve)
            thread.start(); servers.append(thread)
            session = broker._client_handshake_impl(left, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
            return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

        credit_ready, release_credit, cancel_written = (threading.Event() for _ in range(3))
        original_send = client_module._CoreStreamTransport.send
        held = []
        def hold_first_result_credit(transport, payload):
            if (transport.channel is not None and not held
                    and b'"type":"artifact-credit"' in payload):
                held.append(True); credit_ready.set()
                assert release_credit.wait(1)
            return original_send(transport, payload)
        monkeypatch.setattr(client_module._CoreStreamTransport, "send", hold_first_result_credit)
        original_write = broker.FrameCodec.write
        def observe_cancel_write(codec, sock, **kwargs):
            result = original_write(codec, sock, **kwargs)
            if b'"schema":"provider-send-cancel-v1"' in kwargs["payload"]:
                cancel_written.set()
            return result
        monkeypatch.setattr(broker.FrameCodec, "write", observe_cancel_write)

        client = ProviderSendClient(transport_factory=factory, deadline_ms=5_000)
        ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
        committed, commit_failures = [], []
        def commit():
            try:
                committed.append(client.commit(ready["exchange_id"], ready["prepare_sha256"],
                                               str(uuid4())))
            except BaseException as exc:
                commit_failures.append(exc)
        commit_thread = threading.Thread(target=commit)
        commit_thread.start(); assert credit_ready.wait(2)
        cancelled, cancel_failures = [], []
        def cancel():
            try:
                cancelled.append(client.cancel(ready["exchange_id"], "user_requested"))
            except BaseException as exc:
                cancel_failures.append(exc)
        cancel_thread = threading.Thread(target=cancel)
        cancel_thread.start(); assert cancel_written.wait(1)
        release_credit.set()
        commit_thread.join(3); cancel_thread.join(3)
        assert not commit_thread.is_alive() and not cancel_thread.is_alive()
        assert commit_failures == [] and cancel_failures == [] and len(committed) == 1
        assert len(cancelled) == 1 and not cancelled[0].accepted
        assert cancelled[0].phase == "terminal_observed"
        assert client.exchange(committed[0]).body == response
        for server in servers:
            server.join(2); assert not server.is_alive()
        assert failures == [] and len(captures) == 1


def test_exhausted_deadline_cleanup_makes_gateway_unusable(tmp_path, monkeypatch):
    (tmp_path / "custody").mkdir()
    with encrypted_credential(tmp_path / "custody") as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(1)))
        spec, secret = authenticated_spec(tmp_path / "pair"), broker.BootSecret(b"u" * 32)
        entered, release = threading.Event(), threading.Event()
        def surviving_exchange(self, lease):
            entered.set(); release.wait(2)
            raise ProviderSendError("test-owned surviving exchange")
        monkeypatch.setattr(ProviderSendService, "exchange", surviving_exchange)
        failures = []
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        def serve():
            try:
                session = broker._server_handshake_impl(right, spec, secret,
                    requester_boot_id="task47-control", responder_boot_id="task47-gateway",
                    deadline=broker.Deadline.after_ms(2_000), verify_peer=False)
                codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                try:
                    service.serve_authenticated(right, codec,
                        deadline=broker.Deadline.after_ms(150))
                finally:
                    codec.close()
            except BaseException as exc:
                failures.append(exc)
            finally:
                right.close()
        server = threading.Thread(target=serve); server.start()
        session = broker._client_handshake_impl(left, spec, secret,
            requester_boot_id="task47-control", responder_boot_id="task47-gateway",
            deadline=broker.Deadline.after_ms(2_000), verify_peer=False)
        client = ProviderSendClient(transport_factory=lambda: (left,
            broker.FrameCodec(spec, session, local_service=spec.requester_service)),
            deadline_ms=500)
        ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=500))
        client_remaining_at_ready = client._channel["deadline"].remaining()
        with pytest.raises((ProviderSendError, broker.BrokerError)):
            client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        server.join(1)
        survivors = [thread for thread in threading.enumerate()
                     if thread.name == "provider-send-exchange" and thread.is_alive()]
        try:
            assert client_remaining_at_ready <= ready["remaining_ms"] / 1000
            assert entered.is_set() and not server.is_alive() and survivors
            assert service._usable is False and len(failures) == 1
            with pytest.raises(ProviderSendError, match="unavailable after unsafe cleanup"):
                service.prepare(prepared(meta, record, handle, pin))
        finally:
            release.set()
            for survivor in survivors:
                survivor.join(1)
        assert all(not survivor.is_alive() for survivor in survivors)


def test_a_commit_budget_measured_before_transit_shortens_but_never_extends_the_deadline(tmp_path):
    # the requester measures its remaining budget before its commit frame crosses the channel,
    # so a claim a few milliseconds above what is left here must commit (clamped), while a claim
    # beyond the ready grant is still refused
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (port, captures, _entered, _release), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, binding(port)))
        message = prepared(meta, record, handle, pin)
        ready = service.prepare(message)
        time.sleep(0.05)  # the frame's transit: the claim below now exceeds the local remainder
        lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()),
                               remaining_ms=ready["remaining_ms"])
        assert service.exchange(lease).phase == "terminal_observed" and len(captures) == 1
        second = service.prepare(prepared(meta, record, handle, pin))
        with pytest.raises(ProviderSendError, match="commit remaining deadline is invalid"):
            service.commit(second["exchange_id"], second["prepare_sha256"], str(uuid4()),
                           remaining_ms=message.remaining_ms + 1)
        assert len(captures) == 1
