"""Connected offline proofs for the conditional, deliberately unregistered semantic path."""

import os
import socket
import struct
import subprocess
import sys
import threading
import time
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.domain.permissions import Grant, Principal
from app.domain.refs import EntityRef, canonical_json
from app.domain.schemas import Actor, ImmutableRecord
from app.domain.store import DomainStore
from app.extensions.port_schema_generator import generate_port_schemas
from app.extensions.provider_semantic_context import (
    ProviderSemanticAuthority,
    ProviderSemanticContextLoader,
)
from app.extensions.provider_semantic_contracts import (
    ProviderSemanticError,
    instruction_projection_digest,
)
from app.extensions.provider_semantic_records import (
    admit_operation,
    load_terminal,
    seal_catalog,
    seal_catalog_traversal,
    seal_frozen,
    seal_operation,
)
from app.runtime.budgets import BudgetBook, BudgetPolicy
from app.runtime.ledger import ExecutionSpec, OwnerIdentity, RunSpec, RuntimeLedger
from app.runtime.node_attempts import (
    AttemptBinding,
    AttemptDispatchRequest,
    NodeAttemptDispatcher,
    attempt_identity,
    reservation_identity,
)
from app.runtime.provider_attempt_transport import (
    ProviderAttemptTransport,
    ProviderSemanticOperationController,
)
from app.storage import Store
from app.tests.support.provider_semantic_harness import (
    canonical_provider_config,
    connection_values,
    controlled_upstream,
    encrypted_credential,
    immutable_ref,
)
from app.tests.test_provider_semantic_codec import page, valid_stream
from app.tests.test_provider_semantic_worker import request
from app.tests.test_provider_send_gateway import authenticated_spec, future_deadline
from app.tests.test_provider_send_gateway import binding as gateway_binding
from app.workers import broker
from app.workers.credential_contracts import fingerprint
from app.workers.provider_gateway import CredentialedProviderTransport
from app.workers.provider_port_client import ProviderPortClient
from app.workers.provider_port_service import ProviderPortService
from app.workers.provider_semantic_codec import (
    CatalogTraversal,
    advance_catalog,
    encode_text_body,
    parse_model_page,
)
from app.workers.provider_send_client import ProviderSendClient
from app.workers.provider_send_messages import ProviderSendError, prepare_message
from app.workers.provider_send_service import ProviderSendService


def worker_spec(root: Path):
    uid, gid = os.getuid(), os.getgid()
    distinct = lambda *values: next(value for value in range(32_001, 32_100) if value not in values)
    responder_uid = uid or distinct(uid)
    requester_uid = distinct(uid, responder_uid)
    pair_gid = next((value for value in (gid, *os.getgroups()) if value > 0), distinct(gid))
    return broker.ChannelSpec(channel_id="task47-semantic-worker", requester_service="control",
        responder_service="semantic-worker", request_direction="control-to-semantic-worker",
        protocol_id="deeptwin-extension-worker-v1", requester_uid=requester_uid,
        requester_gid=distinct(gid, pair_gid), responder_uid=responder_uid,
        responder_gid=distinct(gid, pair_gid, requester_uid), pair_gid=pair_gid,
        pair_root=root, socket_name="semantic-worker.sock", root_uid=responder_uid,
        root_gid=pair_gid, socket_uid=responder_uid, socket_gid=pair_gid,
        requester_message_types=("extension-artifact-v1", "extension-request-v1"),
        responder_message_types=("extension-artifact-v1", "extension-result-v1"),
        max_queue_depth=1)


def frame_factory(spec, secret, serve, threads, failures):
    def factory():
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        def run():
            try:
                session = broker._server_handshake_impl(right, spec, secret,
                    requester_boot_id="task47-control", responder_boot_id="task47-service",
                    deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
                codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                try:
                    serve(right, codec, broker.Deadline.after_ms(5_000))
                finally:
                    codec.close()
            except BaseException as exc:
                failures.append(exc)
            finally:
                right.close()
        thread = threading.Thread(target=run)
        thread.start(); threads.append(thread)
        session = broker._client_handshake_impl(left, spec, secret,
            requester_boot_id="task47-control", responder_boot_id="task47-service",
            deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
        return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)
    return factory


def _worker_authority():
    identity = {"qualification_ref": immutable_ref(digest="2"),
        "binding_revision_ref": immutable_ref(digest="3"),
        "egress_policy_ref": immutable_ref(digest="8")}
    return immutable_ref(digest="9"), canonical_provider_config(
        immutable_ref(digest="a"), identity=identity)


def test_all_five_operations_cross_authenticated_worker_frames_and_streams(tmp_path):
    service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "pair"), broker.BootSecret(b"w" * 32)
    threads, failures = [], []

    def factory():
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        def serve():
            try:
                session = broker._server_handshake_impl(right, spec, secret,
                    requester_boot_id="task47-control", responder_boot_id="task47-worker",
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
            requester_boot_id="task47-control", responder_boot_id="task47-worker",
            deadline=broker.Deadline.after_ms(5_000), verify_peer=False)
        return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

    client = ProviderPortClient(transport_factory=factory, deadline_ms=5_000)
    operation_ref, config = _worker_authority()
    assert client.execute(request("capabilities", {}), operation_ref=operation_ref,
                          config=config)["terminal"] == "succeeded"
    catalog_proposal = client.begin(request("catalog", {"catalog_epoch": None}),
                                    operation_ref=operation_ref, config=config)
    next_catalog = client.observe(catalog_proposal, status=200,
        raw=page(["model-1"], more=True), exchange_id=str(uuid4()))
    assert next_catalog.endpoint == "models" and next_catalog.after_id == "model-1"
    catalog = client.observe(next_catalog, status=200, raw=page(["model-2"]),
                             exchange_id=str(uuid4()))
    assert catalog.complete and catalog.model_ids == ("model-1", "model-2")

    frozen = {"turn": {"model_id": "model-1"}, "max_output_tokens": 8,
              "messages": [{"role": "user", "input_ordinals": [0]}]}
    model_request = request("model_step", {"frozen_turn_ref": {"kind": "frozen_turn",
        "id": str(uuid4()), "version": 1, "sha256": "a" * 64}, "model_id": "model-1",
        "effort": None, "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None})
    proposal = client.begin(model_request, frozen_content=frozen,
                            input_bytes=(b"authenticated input",), operation_ref=operation_ref,
                            config=config)
    target = {"kind": "validation_report", "id": str(uuid4()), "version": 1,
              "sha256": "b" * 64}
    state = {"operation_ref": target, "observed_state": "running",
             "observed_at": "2026-09-20T00:00:00.000Z", "terminal_result_ref": None}
    routed_status = client.control(request("status", {"operation_ref": target}),
                                   query_state=state)
    assert routed_status["output"]["observed_state"] == "running"
    model = client.observe(proposal, status=200, raw=valid_stream("authenticated output"),
                           exchange_id=str(uuid4()))
    assert model.text_blocks == (b"authenticated output",)

    assert client.execute(request("status", {"operation_ref": target}),
                          query_state=state, operation_ref=operation_ref,
                          config=config)["output"]["observed_state"] == "running"
    assert client.execute(request("cancel", {"operation_ref": target,
                          "reason_class": "user_requested"}),
                          query_state=state, operation_ref=operation_ref,
                          config=config)["output"]["cancel_state"] == "accepted"

    cancel_proposal = client.begin(model_request, frozen_content=frozen,
                                   input_bytes=(b"authenticated input",),
                                   operation_ref=operation_ref, config=config)
    routed_cancel = client.control(request("cancel", {"operation_ref": target,
        "reason_class": "user_requested"}), query_state=state)
    assert cancel_proposal.endpoint == "messages"
    assert routed_cancel["output"]["cancel_state"] == "accepted"

    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert failures == []


def test_worker_factory_setup_consumes_the_original_deadline_anchor(tmp_path):
    service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "deadline-pair"), broker.BootSecret(b"d" * 32)
    threads, failures = [], []
    actual_factory = frame_factory(spec, secret,
        lambda sock, codec, deadline: service.serve_authenticated(
            sock, codec, deadline=deadline), threads, failures)

    def delayed_factory():
        channel = actual_factory()
        time.sleep(0.080)
        return channel

    client = ProviderPortClient(transport_factory=delayed_factory, deadline_ms=5_000)
    operation_ref, config = _worker_authority()
    end = time.monotonic() + 0.050
    result = client.execute(request("capabilities", {}), operation_ref=operation_ref,
                            config=config, deadline_end_monotonic=end)
    assert result["terminal"] == "failed" and time.monotonic() >= end
    for thread in threads:
        thread.join(1); assert not thread.is_alive()
    assert failures == []


@pytest.mark.parametrize("boundary", ["frozen", "input", "raw", "final", "text"])
def test_status_cancel_route_at_each_worker_stream_boundary(tmp_path, monkeypatch, boundary):
    import app.workers.provider_port_client as client_module
    import app.workers.provider_port_service as service_module

    service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "pair"), broker.BootSecret(b"j" * 32)
    threads, failures = [], []
    client = ProviderPortClient(transport_factory=frame_factory(spec, secret,
        lambda sock, codec, deadline: service.serve_authenticated(
            sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000)
    operation_ref, config = _worker_authority()
    target = {"kind": "validation_report", "id": str(uuid4()), "version": 1,
              "sha256": "b" * 64}
    state = {"operation_ref": target, "observed_state": "running",
             "observed_at": "2026-09-20T00:00:00.000Z", "terminal_result_ref": None}
    frozen = {"turn": {"model_id": "model-1"}, "max_output_tokens": 8,
              "messages": [{"role": "user", "input_ordinals": [0]}]}
    model_request = request("model_step", {"frozen_turn_ref": {"kind": "frozen_turn",
        "id": str(uuid4()), "version": 1, "sha256": "a" * 64}, "model_id": "model-1",
        "effort": None, "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None})
    reached, release = threading.Event(), threading.Event()
    offer_count = []

    if boundary in {"frozen", "input"}:
        original = client_module._WorkerClientStreamTransport.send
        target_offer = {"frozen": 1, "input": 2}[boundary]
        def hold_client_offer(transport, payload):
            if b'"type":"artifact-offer"' in payload:
                offer_count.append(True)
                if len(offer_count) == target_offer:
                    reached.set(); assert release.wait(1)
            return original(transport, payload)
        monkeypatch.setattr(client_module._WorkerClientStreamTransport, "send",
                            hold_client_offer)
    proposal_box, model_box, work_failures = [], [], []
    if boundary in {"frozen", "input"}:
        def begin():
            try:
                proposal_box.append(client.begin(model_request, frozen_content=frozen,
                    input_bytes=(b"authenticated input",), operation_ref=operation_ref,
                    config=config))
            except BaseException as exc:
                work_failures.append(exc)
        work = threading.Thread(target=begin)
    else:
        proposal = client.begin(model_request, frozen_content=frozen,
            input_bytes=(b"authenticated input",), operation_ref=operation_ref, config=config)
        if boundary == "raw":
            original = client_module._WorkerClientStreamTransport.send
            def hold_client_offer(transport, payload):
                if b'"type":"artifact-offer"' in payload and not offer_count:
                    offer_count.append(True); reached.set(); assert release.wait(1)
                return original(transport, payload)
            monkeypatch.setattr(client_module._WorkerClientStreamTransport, "send",
                                hold_client_offer)
        else:
            original = service_module._WorkerServiceStreamTransport.send
            target_offer = 1 if boundary == "final" else 2
            def hold_service_offer(transport, payload):
                if b'"type":"artifact-offer"' in payload:
                    offer_count.append(True)
                    if len(offer_count) == target_offer:
                        reached.set(); assert release.wait(1)
                return original(transport, payload)
            monkeypatch.setattr(service_module._WorkerServiceStreamTransport, "send",
                                hold_service_offer)
        def observe():
            try:
                model_box.append(client.observe(proposal, status=200,
                    raw=valid_stream("stream-routed"), exchange_id=str(uuid4())))
            except BaseException as exc:
                work_failures.append(exc)
        work = threading.Thread(target=observe)
    work.start(); assert reached.wait(2)
    control_result, control_failures = [], []
    operation = "cancel" if boundary == "text" else "status"
    control_request = request(operation, {"operation_ref": target,
        **({"reason_class": "user_requested"} if operation == "cancel" else {})})
    control_written = threading.Event()
    original_codec_write = broker.FrameCodec.write
    def observe_control_write(codec, *args, **kwargs):
        result = original_codec_write(codec, *args, **kwargs)
        if b'"schema":"provider-semantic-control-v1"' in kwargs.get("payload", b""):
            control_written.set()
        return result
    monkeypatch.setattr(broker.FrameCodec, "write", observe_control_write)
    def control():
        try:
            control_result.append(client.control(control_request, query_state=state))
        except BaseException as exc:
            control_failures.append(exc)
    controller = threading.Thread(target=control)
    controller.start(); assert control_written.wait(1); release.set()
    work.join(3); controller.join(3)
    assert not work.is_alive() and not controller.is_alive() and control_failures == [], (
        [(type(exc).__name__, str(exc)) for exc in work_failures],
        [(type(exc).__name__, str(exc)) for exc in control_failures],
        [(type(exc).__name__, str(exc)) for exc in failures])
    if operation == "status":
        assert control_result[0]["output"]["observed_state"] == "running"
        if boundary in {"frozen", "input"}:
            assert len(proposal_box) == 1 and work_failures == []
            model_box.append(client.observe(proposal_box[0], status=200,
                raw=valid_stream("stream-routed"), exchange_id=str(uuid4())))
        assert len(model_box) == 1 and model_box[0].text_blocks == (b"stream-routed",)
    else:
        assert control_result[0]["output"]["cancel_state"] == "accepted"
        assert len(work_failures) == 1 and client._channel is None
    for thread in threads:
        thread.join(2); assert not thread.is_alive()
    assert failures == []


def test_status_completes_while_worker_stream_offer_is_withheld(tmp_path, monkeypatch):
    import app.workers.provider_port_service as service_module

    service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "pair"), broker.BootSecret(b"k" * 32)
    threads, failures = [], []
    client = ProviderPortClient(transport_factory=frame_factory(spec, secret,
        lambda sock, codec, deadline: service.serve_authenticated(
            sock, codec, deadline=deadline), threads, failures), deadline_ms=2_000)
    operation_ref, config = _worker_authority()
    frozen = {"turn": {"model_id": "model-1"}, "max_output_tokens": 8,
              "messages": [{"role": "user", "input_ordinals": [0]}]}
    model_request = request("model_step", {"frozen_turn_ref": {"kind": "frozen_turn",
        "id": str(uuid4()), "version": 1, "sha256": "a" * 64}, "model_id": "model-1",
        "effort": None, "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None})
    target = {"kind": "validation_report", "id": str(uuid4()), "version": 1,
              "sha256": "b" * 64}
    state = {"operation_ref": target, "observed_state": "running",
             "observed_at": "2026-09-20T00:00:00.000Z", "terminal_result_ref": None}
    offer_withheld, release_offer = threading.Event(), threading.Event()
    original_send = service_module._WorkerServiceStreamTransport.send
    held = []

    def withhold_offer_while_routing_control(transport, payload):
        if b'"type":"artifact-offer"' in payload and not held:
            held.append(True)
            offer_withheld.set()
            frame = transport._router._codec.read(
                transport._router._sock, deadline=transport._router._deadline)
            assert transport._router._route(frame, allow_observation=False) is False
            assert release_offer.wait(1)
        return original_send(transport, payload)

    monkeypatch.setattr(service_module._WorkerServiceStreamTransport, "send",
                        withhold_offer_while_routing_control)
    proposals, begin_failures = [], []

    def begin():
        try:
            proposals.append(client.begin(model_request, frozen_content=frozen,
                input_bytes=(b"authenticated input",), operation_ref=operation_ref,
                config=config))
        except BaseException as exc:
            begin_failures.append(exc)

    work = threading.Thread(target=begin)
    work.start()
    reached_offer = offer_withheld.wait(2)
    if not reached_offer:
        if client._channel is not None:
            try:
                client._channel["sock"].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        work.join(3)
        for thread in threads:
            thread.join(2)
        pytest.fail(f"worker stream offer was not reached: {begin_failures!r}")
    control_results, control_failures, control_done = [], [], threading.Event()

    def control():
        try:
            control_results.append(client.control(
                request("status", {"operation_ref": target}), query_state=state))
        except BaseException as exc:
            control_failures.append(exc)
        finally:
            control_done.set()

    controller = threading.Thread(target=control)
    controller.start()
    try:
        assert control_done.wait(0.5), "status starved behind a withheld worker stream frame"
    finally:
        release_offer.set()
        if not control_done.is_set() and client._channel is not None:
            try:
                client._channel["sock"].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    work.join(3); controller.join(3)
    assert not work.is_alive() and not controller.is_alive()
    assert begin_failures == [] and control_failures == []
    assert control_results[0]["output"]["observed_state"] == "running"
    assert len(proposals) == 1
    client.abandon()
    for thread in threads:
        thread.join(2); assert not thread.is_alive()
    assert failures == []


def test_control_during_proposal_body_preserves_application_sequence(tmp_path, monkeypatch):
    import app.workers.provider_port_client as client_module

    service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "pair"), broker.BootSecret(b"l" * 32)
    threads, failures = [], []
    client = ProviderPortClient(transport_factory=frame_factory(spec, secret,
        lambda sock, codec, deadline: service.serve_authenticated(
            sock, codec, deadline=deadline), threads, failures), deadline_ms=2_000)
    operation_ref, config = _worker_authority()
    frozen = {"turn": {"model_id": "model-1"}, "max_output_tokens": 8,
              "messages": [{"role": "user", "input_ordinals": [0]}]}
    model_request = request("model_step", {"frozen_turn_ref": {"kind": "frozen_turn",
        "id": str(uuid4()), "version": 1, "sha256": "a" * 64}, "model_id": "model-1",
        "effort": None, "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None})
    target = {"kind": "validation_report", "id": str(uuid4()), "version": 1,
              "sha256": "b" * 64}
    state = {"operation_ref": target, "observed_state": "running",
             "observed_at": "2026-09-20T00:00:00.000Z", "terminal_result_ref": None}
    credit_reached, control_written = threading.Event(), threading.Event()
    original_stream_send = client_module._WorkerClientStreamTransport.send
    original_codec_write = broker.FrameCodec.write
    first_credit = []

    def observe_control_write(codec, sock, **kwargs):
        result = original_codec_write(codec, sock, **kwargs)
        if b'"schema":"provider-semantic-control-v1"' in kwargs["payload"]:
            control_written.set()
        return result

    def order_credit_after_control(transport, payload):
        if b'"type":"artifact-credit"' in payload and not first_credit:
            first_credit.append(True)
            credit_reached.set()
            assert control_written.wait(1)
        return original_stream_send(transport, payload)

    monkeypatch.setattr(broker.FrameCodec, "write", observe_control_write)
    monkeypatch.setattr(client_module._WorkerClientStreamTransport, "send",
                        order_credit_after_control)
    proposals, begin_failures = [], []

    def begin():
        try:
            proposals.append(client.begin(model_request, frozen_content=frozen,
                input_bytes=(b"authenticated input",), operation_ref=operation_ref,
                config=config))
        except BaseException as exc:
            begin_failures.append(exc)

    work = threading.Thread(target=begin)
    work.start(); assert credit_reached.wait(1)
    control_results, control_failures = [], []

    def control():
        try:
            control_results.append(client.control(
                request("status", {"operation_ref": target}), query_state=state))
        except BaseException as exc:
            control_failures.append(exc)

    controller = threading.Thread(target=control)
    controller.start()
    work.join(3); controller.join(3)
    assert not work.is_alive() and not controller.is_alive()
    assert begin_failures == [] and control_failures == []
    assert len(proposals) == 1
    assert control_results[0]["output"]["observed_state"] == "running"
    client.abandon()
    for thread in threads:
        thread.join(2); assert not thread.is_alive()
    assert failures == []


@pytest.mark.parametrize(("wire_case", "failure_type"), [
    ("oversize", broker.ProtocolViolation),
    ("partial_prefix", broker.DeadlineExceeded),
    ("partial_body", broker.DeadlineExceeded),
])
def test_authenticated_raw_frame_owner_fails_closed_on_malformed_or_partial_wire(
        tmp_path, wire_case, failure_type):
    spec, secret = worker_spec(tmp_path / "pair"), broker.BootSecret(b"m" * 32)
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    server_failures = []

    def peer():
        try:
            broker._server_handshake_impl(right, spec, secret,
                requester_boot_id="task47-control", responder_boot_id="task47-worker",
                deadline=broker.Deadline.after_ms(1_000), verify_peer=False)
            if wire_case == "oversize":
                right.sendall(struct.pack(">I", spec.max_frame_bytes + 1))
            elif wire_case == "partial_prefix":
                right.sendall(b"\x00\x00")
            else:
                right.sendall(struct.pack(">I", 16) + b"x")
            time.sleep(0.180)
        except BaseException as exc:
            server_failures.append(exc)
        finally:
            right.close()

    server = threading.Thread(target=peer)
    server.start()
    session = broker._client_handshake_impl(left, spec, secret,
        requester_boot_id="task47-control", responder_boot_id="task47-worker",
        deadline=broker.Deadline.after_ms(1_000), verify_peer=False)
    codec = broker.FrameCodec(spec, session, local_service=spec.requester_service)
    started = time.monotonic()
    with pytest.raises(failure_type):
        ProviderPortClient._read_authenticated_frame({
            "sock": left, "codec": codec, "deadline": broker.Deadline.after_ms(100)})
    elapsed = time.monotonic() - started
    assert elapsed < 0.300 and codec.closed
    left.close(); server.join(1)
    assert not server.is_alive() and server_failures == []


@pytest.mark.parametrize("mutation", ["boolean_sequence", "operation_ref", "config",
                                      "resource_limits", "port_config", "qualification_ref"])
def test_worker_begin_authority_and_sequence_are_closed(tmp_path, monkeypatch, mutation):
    import app.workers.provider_port_client as client_module

    service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "pair"), broker.BootSecret(b"q" * 32)
    threads, failures = [], []
    client = ProviderPortClient(transport_factory=frame_factory(spec, secret,
        lambda sock, codec, deadline: service.serve_authenticated(
            sock, codec, deadline=deadline), threads, failures), deadline_ms=2_000)
    operation_ref, config = _worker_authority()
    original_encode = client_module.encode_op

    def mutate_begin(value):
        if type(value) is dict and value.get("schema") == "provider-semantic-begin-v1":
            value = {**value}
            if mutation == "boolean_sequence":
                value["seq"] = False
            elif mutation == "operation_ref":
                value["operation_ref"] = {**value["operation_ref"], "extra": True}
            elif mutation == "config":
                value["config"] = {**value["config"], "extra": True}
            elif mutation == "resource_limits":
                value["config"] = deepcopy(value["config"])
                value["config"]["resource_limits"]["max_output_bytes"] = False
            elif mutation == "port_config":
                value["config"] = deepcopy(value["config"])
                value["config"]["port_config"]["profile_id"] = "unreviewed-profile"
            else:
                value["config"] = deepcopy(value["config"])
                value["config"]["qualification_ref"]["sha256"] = "not-a-digest"
        return original_encode(value)

    monkeypatch.setattr(client_module, "encode_op", mutate_begin)
    result = client.execute(request("capabilities", {}), operation_ref=operation_ref,
                            config=config)
    assert result["terminal"] == "failed"
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert len(failures) == 1 and type(failures[0]) is ProviderSemanticError


def test_worker_final_observation_declared_over_64k_is_refused_by_client(
        tmp_path, monkeypatch):
    import app.workers.provider_port_service as service_module

    service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "pair"), broker.BootSecret(b"v" * 32)
    threads, failures = [], []
    client = ProviderPortClient(transport_factory=frame_factory(spec, secret,
        lambda sock, codec, deadline: service.serve_authenticated(
            sock, codec, deadline=deadline), threads, failures), deadline_ms=2_000)
    operation_ref, config = _worker_authority()
    original_encode = service_module.encode_op

    def oversize_final(value):
        if type(value) is dict and value.get("schema") == "provider-semantic-final-v1":
            value = {**value, "observation_descriptor": {
                **value["observation_descriptor"], "declared_size": 65_537}}
        return original_encode(value)

    monkeypatch.setattr(service_module, "encode_op", oversize_final)
    result = client.execute(request("capabilities", {}), operation_ref=operation_ref,
                            config=config)
    assert result["terminal"] == "failed"
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert failures


def test_worker_receiver_refuses_application_control_over_16k(tmp_path):
    service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "pair"), broker.BootSecret(b"x" * 32)
    threads, failures = [], []
    left, codec = frame_factory(spec, secret,
        lambda sock, server_codec, deadline: service.serve_authenticated(
            sock, server_codec, deadline=deadline), threads, failures)()
    operation_ref, config = _worker_authority()
    payload = __import__("app.workers.credential_channel",
        fromlist=["encode_op"]).encode_op({"schema": "provider-semantic-begin-v1",
        "dialogue_id": str(uuid4()), "seq": 0, "operation_ref": operation_ref,
        "config": config, "request": request("capabilities", {}),
        "frozen_descriptor": None, "input_descriptors": [], "query_state": None,
        "oversized": "x" * 16_384})
    assert len(payload) > 16_384
    codec.write(left, message_id=str(uuid4()), correlation_id=None,
        message_type="extension-request-v1", payload=payload,
        deadline=broker.Deadline.after_ms(2_000))
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    codec.close(); left.close()
    assert len(failures) == 1 and type(failures[0]) is ProviderSemanticError


@pytest.mark.parametrize("block_phase", ["headers", "body"])
def test_same_authenticated_worker_dialogue_routes_status_and_cancel_while_http_blocks(
        tmp_path, block_phase):
    worker_service = ProviderPortService()
    spec, secret = worker_spec(tmp_path / "worker-pair"), broker.BootSecret(b"r" * 32)
    threads, failures = [], []
    worker_client = ProviderPortClient(transport_factory=frame_factory(
        spec, secret, lambda sock, codec, deadline: worker_service.serve_authenticated(
            sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000)
    frozen = {"turn": {"model_id": "model-1"}, "max_output_tokens": 8,
              "messages": [{"role": "user", "input_ordinals": [0]}]}
    model_request = request("model_step", {"frozen_turn_ref": {"kind": "frozen_turn",
        "id": str(uuid4()), "version": 1, "sha256": "a" * 64}, "model_id": "model-1",
        "effort": None, "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None})
    operation_ref, config = _worker_authority()
    worker_client.begin(model_request, frozen_content=frozen, input_bytes=(b"blocked",),
                        operation_ref=operation_ref, config=config)

    (tmp_path / "custody").mkdir()
    with controlled_upstream(response=(200, "text/event-stream", valid_stream()), blocked=True,
                             block_phase=block_phase) as (
            port, captures, entered, release), encrypted_credential(tmp_path / "custody") as (
            vault, meta, credential_record):
        handle, pin, _, _ = connection_values(meta, credential_record)
        send_service = ProviderSendService(CredentialedProviderTransport(vault, gateway_binding(port)))
        prepared = prepare_message(operation_ref={"kind": "validation_report", "id": str(uuid4()),
            "version": 1, "sha256": "c" * 64}, request_id=str(uuid4()),
            request_sha256="d" * 64,
            selected_handle_ref=handle, connection_pin=pin, credential_metadata=meta,
            credential_record=credential_record, endpoint="messages", after_id=None,
            body=b"{}", remaining_ms=2_000, deadline_at=future_deadline(),
            reservation_ref={"kind": "validation_report",
                "id": str(uuid4()), "version": 1, "sha256": "e" * 64})
        ready = send_service.prepare(prepared)
        lease = send_service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
        exchange_failures = []
        def exchange():
            try: send_service.exchange(lease)
            except BaseException as exc: exchange_failures.append(exc)
        exchange_thread = threading.Thread(target=exchange)
        exchange_thread.start()
        assert entered.wait(1)
        target = prepared.operation_ref
        query_state = {"operation_ref": target, "observed_state": "running",
            "observed_at": "2026-09-20T00:00:00.000Z", "terminal_result_ref": None}
        status_result = worker_client.control(
            request("status", {"operation_ref": target}), query_state=query_state)
        assert status_result["output"]["observed_state"] == "running"
        cancel_result = worker_client.control(request("cancel", {
            "operation_ref": target, "reason_class": "user_requested"}),
            query_state=query_state)
        assert cancel_result["output"]["cancel_state"] == "accepted"
        assert send_service.cancel(lease.exchange_id, "user_requested").accepted
        exchange_thread.join(2); release.set()
        assert not exchange_thread.is_alive() and len(exchange_failures) == 1
        assert type(exchange_failures[0]) is ProviderSendError and len(captures) == 1
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert failures == []


def test_default_server_import_does_not_register_semantic_services_or_test_authority():
    script = """
import sys
import app.server
for name in sys.modules:
    assert name != 'app.tests.support.provider_semantic_harness', name
    assert name not in {'app.workers.provider_port_service',
                        'app.workers.provider_send_service',
                        'app.runtime.provider_attempt_transport'}, name
"""
    completed = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True,
        text=True, timeout=15, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert completed.returncode == 0, completed.stderr


def _record(domain, kind, content, *, parents=()):
    roots = domain.roots()
    return domain.put(ImmutableRecord.create(kind=kind, id=str(uuid4()), version=1,
        created_at_utc="2026-09-20T00:00:00.000000Z", actor_ref=roots.actor,
        parent_refs=parents, purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content=content))


def _api_runtime(path):
    legacy = Store(path / "vault")
    domain = DomainStore(legacy)
    roots = domain.initialize_vault()
    policy = BudgetPolicy.create(profile="execution", provider_mode="api", max_model_calls=2,
        max_tool_calls=1, max_node_visits=2, max_loop_rounds=1, max_output_bytes=1_048_576,
        max_concurrency=1, max_wall_seconds=60, max_candidates=1,
        currency="USD", max_api_microunits=1_000_000)
    budget = _record(domain, "budget_policy", policy.domain_content())
    refs = SimpleNamespace(
        work=_record(domain, "work_revision", {"fixture": "work"}),
        environment=_record(domain, "environment", {"fixture": "environment"}),
        consent=_record(domain, "run_consent", {"fixture": "consent"}), budget=budget,
        manifest=_record(domain, "run_manifest", {"fixture": "manifest"}),
        envelope=_record(domain, "execution_envelope", {"fixture": "envelope"}),
        profile=_record(domain, "runtime_profile", {"fixture": "profile"}))
    book = BudgetBook(legacy, clock=lambda: 100)
    session_id = str(uuid4()); book.start(session_id, policy)
    ledger = RuntimeLedger(domain, clock_ms=lambda: 1_000)
    ledger.reconcile_startup(str(uuid4()), observed_owners={})
    principal = Principal(str(uuid4()), Actor(str(uuid4()), "test_actor", "test_fixture"),
                          "runtime", "operational", 10_000)
    grant = Grant(str(uuid4()), str(uuid4()), principal.id, refs.envelope, "read",
                  "operational", None, 10_000, 1)
    return SimpleNamespace(legacy=legacy, domain=domain, roots=roots, refs=refs, policy=policy,
        book=book, session_id=session_id, ledger=ledger, principal=principal, grant=grant)


def _assert_subset_replay_is_immutable(domain, config, operation, request_value,
        boot_id, reservation, stamp, config_grants):
    """A wider binding must not let an existing request adopt different grants/config."""
    from app.tests.support.provider_semantic_harness import canonical_provider_request

    anchor_bytes = canonical_json(domain.get(operation).body)
    terminal = load_terminal(domain, operation)
    terminal_bytes = canonical_json(terminal.body)
    assert admit_operation(domain, config_ref=config, request=request_value,
        core_boot_id=boot_id, reservation_ref=reservation,
        semantic_key=request_value["idempotency_key"], created_at_utc=stamp) == (operation, True)
    changed = canonical_provider_request(request_value["operation"], request_value["input"],
        request_id=request_value["request_id"], artifact_inputs=request_value["artifact_inputs"],
        identity={**request_value, "grant_refs": config_grants},
        deadline_at=request_value["deadline_at"])
    with pytest.raises(ProviderSemanticError, match="changed immutable input"):
        admit_operation(domain, config_ref=config, request=changed, core_boot_id=boot_id,
            reservation_ref=reservation, semantic_key=changed["idempotency_key"],
            created_at_utc=stamp)
    config_record = domain.get(config)
    other_config = _record(domain, "validation_report", config_record.body["content"],
        parents=tuple(EntityRef.from_dict(item) for item in config_record.body["parent_refs"]))
    with pytest.raises(ProviderSemanticError, match="changed immutable input"):
        admit_operation(domain, config_ref=other_config, request=request_value,
            core_boot_id=boot_id, reservation_ref=reservation,
            semantic_key=request_value["idempotency_key"], created_at_utc=stamp)
    assert canonical_json(domain.get(operation).body) == anchor_bytes
    assert canonical_json(load_terminal(domain, operation).body) == terminal_bytes


@pytest.mark.parametrize(("reservation_currency", "response_mode", "fault_phase"), [
    ("USD", "valid", None), ("EUR", "valid", None), ("USD", "malformed", None),
    ("USD", "valid", "gateway_commit"),
    ("USD", "valid", "gateway_untrusted_result"),
    ("USD", "valid", "write_boundary"),
    ("USD", "valid", "response_observed"),
    ("USD", "valid", "terminal_store_failure"),
    ("USD", "valid", "terminal_sealed"),
    ("USD", "valid", "ledger_accepted"),
    ("USD", "valid", "cancel_during_body"),
    ("USD", "valid", "success_cancel_latch"),
    ("USD", "valid", "worker_body_substitution"),
    ("USD", "valid", "worker_observation_substitution"),
    ("USD", "valid", "worker_prepare_exception"),
    ("USD", "valid", "worker_begin_deadline"),
    ("USD", "valid", "gateway_prepare_exception"),
    ("USD", "valid", "final_reload_exception"),
    ("USD", "valid", "initial_permission"),
    ("USD", "valid", "initial_grant_permission"),
    ("USD", "valid", "deadline_after_worker"),
    ("USD", "valid", "deadline_after_reload"),
    ("USD", "valid", "gateway_session_mismatch"),
    ("USD", "valid", "cleanup_cancel_exception"),
    ("USD", "valid", "worker_observation_exception"),
    ("USD", "valid", "reservation_amount"),
    ("USD", "valid", "output_limit"),
    ("USD", "valid", "unsupported_model"),
    ("USD", "valid", "model_deadline"),
    ("USD", "valid", "account_mismatch"),
    ("USD", "valid", "model_owner_missing"),
    ("USD", "valid", "model_owner_missing_expired"),
    ("USD", "valid", "model_owner_missing_revoked"),
    ("USD", "valid", "model_owner_consumed_expired"),
    ("USD", "valid", "model_owner_consumed_revoked"),
    ("USD", "valid", "model_owner_missing_unauthenticated"),
    ("USD", "valid", "model_subject_mismatch"),
    ("USD", "valid", "model_grant_subset"),
    ("USD", "valid", "model_grant_non_subset"),
    ("USD", "valid", "catalog_grant_subset"),
    ("USD", "valid", "catalog_grant_non_subset"),
    ("USD", "valid", "stale_catalog"),
    ("USD", "valid", "catalog_provenance"),
    ("USD", "valid", "session_mismatch"),
    ("USD", "valid", "catalog_malformed"),
    ("USD", "valid", "catalog_non2xx"),
    ("USD", "valid", "catalog_continuation"),
    ("USD", "valid", "catalog_revoked"),
    ("USD", "valid", "catalog_initial_permission"),
    ("USD", "valid", "catalog_initial_deadline"),
    ("USD", "valid", "catalog_broker_deadline"),
    ("USD", "valid", "catalog_worker_local_failure"),
    ("USD", "valid", "catalog_worker_protocol_failure"),
    ("USD", "valid", "catalog_owner_crash"),
    ("USD", "valid", "catalog_owner_crash_expired"),
    ("USD", "valid", "catalog_media"),
    ("USD", "valid", "catalog_deadline"),
    ("USD", "valid", "gateway_permission"),
    ("USD", "valid", "gateway_capacity"),
    ("USD", "valid", "gateway_media"),
])
def test_authenticated_semantic_path_is_accepted_by_actual_dispatcher_and_retains_api_reservation(
        tmp_path, monkeypatch, reservation_currency, response_mode, fault_phase):
    runtime = _api_runtime(tmp_path / "runtime")
    run = RunSpec(str(uuid4()), runtime.refs.work, runtime.refs.environment,
        runtime.refs.consent, "live", runtime.refs.budget, runtime.session_id,
        runtime.refs.manifest)
    runtime.ledger.create_run(str(uuid4()), run)
    execution = ExecutionSpec(str(uuid4()), run.run_id, "writer", str(uuid4()), (0,), ())
    runtime.ledger.create_execution(str(uuid4()), execution)
    (tmp_path / "custody").mkdir()
    response = (valid_stream("dispatcher output") if response_mode == "valid"
                else valid_stream("dispatcher output").rstrip())
    actual_catalog = (reservation_currency == "USD" and response_mode == "valid"
                      and (fault_phase is None or (type(fault_phase) is str
                                                   and fault_phase.startswith("catalog_")
                                                   and fault_phase != "catalog_provenance")))
    if fault_phase in {"catalog_malformed", "catalog_owner_crash", "catalog_owner_crash_expired"}:
        upstream_response = (200, "application/json", b"{")
    elif fault_phase == "catalog_non2xx":
        upstream_response = (503, "application/json", b'{"error":"unavailable"}')
    elif fault_phase in {"catalog_continuation", "catalog_revoked", "catalog_deadline"}:
        upstream_response = [(200, "application/json", page(["model-1"], more=True)),
                             (200, "application/json", page(["model-2"]))]
    elif fault_phase == "catalog_media":
        upstream_response = (200, "text/event-stream", page(["model-1"]))
    elif fault_phase == "gateway_media":
        upstream_response = (200, "application/json", response)
    elif fault_phase == "gateway_capacity":
        upstream_response = (200, "text/event-stream", response + b"x" * 128)
    else:
        upstream_response = ([(200, "application/json", page(["model-1"], more=True)),
                          (200, "application/json", page(["model-2"])),
                          (200, "application/json", page(["model-1"], more=True)),
                          (200, "application/json", page(["model-2"])),
                          (200, "text/event-stream", response)]
                         if actual_catalog else (200, "text/event-stream", response))
    threads, failures = [], []
    with controlled_upstream(response=upstream_response,
            blocked=fault_phase == "cancel_during_body", block_phase="body") as (
            port, captures, _entered, _release), \
            encrypted_credential(tmp_path / "custody", b"dispatcher-secret") as (vault, meta, credential_record):
        locator = {"kind": "connection", "id": str(uuid4())}
        pin = {"locator": locator, "revision_digest": "b" * 64,
               "provider_id": "claude_api", "account_id": "account",
               "credential_metadata_sha256": fingerprint(meta)}
        connection = _record(runtime.domain, "validation_report", {
            "schema_version": "provider-semantic-connection-v1", **pin,
            "credential_metadata": meta, "credential_record": credential_record})
        now = datetime.now(timezone.utc).replace(microsecond=(datetime.now(timezone.utc).microsecond // 1000) * 1000)
        port_time = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        domain_time = lambda value: value.isoformat(timespec="microseconds").replace("+00:00", "Z")
        source = runtime.domain.put_blob(b"synthetic reviewed model scope", purpose="operational")
        text_policy = _record(runtime.domain, "validation_report", {
            "schema_version": "provider-semantic-text-policy-v1",
            "source_url": "https://platform.claude.com/docs/en/models/overview",
            "source_blob": source.as_dict(), "source_sha256": source.sha256,
            "retrieved_at": port_time(now - timedelta(minutes=2)),
            "reviewed_at": port_time(now - timedelta(minutes=1)),
            "valid_until": port_time(now + timedelta(hours=2)),
            "scope_model_ids": ["model-1"], "claim": "current-models-text-input-output",
            "reviewer_ref": runtime.roots.actor.as_dict()}, parents=(runtime.roots.actor,))
        qualification = _record(runtime.domain, "validation_report", {"fixture": "qualification"})
        binding_revision = _record(runtime.domain, "validation_report", {"fixture": "binding"})
        compatibility_observation = _record(runtime.domain, "validation_report",
                                             {"fixture": "compatibility-observation"})
        request_policy_sha256 = sha256(canonical_json({
            "profile_id": "claude-api-text-semantic-v1", "api_version": "2023-06-01",
            "auth": "api-key", "effort": None, "tools": False, "cache": False,
            "thinking_override": None, "success_stop": "end_turn",
            "input_media_types": ["text/plain"], "max_inputs": 4, "max_output_blocks": 4,
            "max_output_tokens": 8192, "deadline_ms": 30000})).hexdigest()
        compatibility = _record(runtime.domain, "validation_report", {
            "schema_version": "provider-semantic-compatibility-v1",
            "profile_id": "claude-api-text-semantic-v1", "connection_ref": connection.as_dict(),
            "model_id": "model-1", "request_policy_sha256": request_policy_sha256,
            "observed_at": port_time(now - timedelta(minutes=1)),
            "expires_at": port_time(now + timedelta(hours=1)),
            "observation_ref": compatibility_observation.as_dict(), "outcome": "complete_text"},
            parents=tuple(sorted((connection, compatibility_observation),
                                 key=lambda item: canonical_json(item.as_dict()))))
        compatibility_set = _record(runtime.domain, "validation_report", {
            "schema_version": "provider-semantic-compatibility-set-v1",
            "profile_id": "claude-api-text-semantic-v1", "connection_ref": connection.as_dict(),
            "observation_refs": [compatibility.as_dict()]}, parents=(connection,))
        purpose = _record(runtime.domain, "validation_report", {"fixture": "purpose"})
        grant_case = fault_phase in {"model_grant_subset", "model_grant_non_subset",
                                     "catalog_grant_subset", "catalog_grant_non_subset"}
        grant_ref = (_record(runtime.domain, "validation_report", {"fixture": "grant"})
                     if fault_phase == "initial_grant_permission" or grant_case else None)
        grant_refs = [] if grant_ref is None else [grant_ref.as_dict()]
        extra_grant = (_record(runtime.domain, "validation_report", {"fixture": "unused grant"})
                       if grant_case else None)
        config_grants = grant_refs
        if grant_case:
            config_grants = sorted([extra_grant.as_dict(), *(
                [] if fault_phase.endswith("non_subset") else grant_refs)], key=canonical_json)
        selected_grant_records = ({} if grant_ref is None else {grant_ref.sha256: {
            "ref": grant_ref.as_dict(), "active": grant_case,
            "purpose_ref": purpose.as_dict(),
            "allowed_operations": ["catalog", "model_step"] if grant_case else ["model_step"]}})
        request_identity = {"installation_digest": "1" * 64,
            "qualification_ref": qualification.as_dict(),
            "binding_revision_ref": binding_revision.as_dict(), "purpose_ref": purpose.as_dict(),
            "actor_ref": runtime.roots.actor.as_dict(), "grant_refs": grant_refs}
        config_value = canonical_provider_config(connection.as_dict(), identity={
            **request_identity, "grant_refs": config_grants,
            "egress_policy_ref": runtime.roots.access_policy.as_dict()},
            catalog_ttl_seconds=1 if fault_phase == "stale_catalog" else 3600)
        config_parents = tuple(sorted({connection, text_policy, compatibility_set,
            qualification, binding_revision, runtime.roots.access_policy,
            *(EntityRef.from_dict(item) for item in config_grants)},
            key=lambda item: canonical_json(item.as_dict())))
        config = _record(runtime.domain, "validation_report", {
            "schema_version": "provider-semantic-config-v1", "config": config_value,
            "connection_ref": connection.as_dict(), "text_policy_ref": text_policy.as_dict(),
            "compatibility_set_ref": compatibility_set.as_dict()}, parents=config_parents)
        catalog_request = __import__("app.tests.support.provider_semantic_harness",
            fromlist=["canonical_provider_request"]).canonical_provider_request(
            "catalog", {"catalog_epoch": None}, identity=request_identity,
            deadline_at=port_time(now + (timedelta(seconds=1.5)
                if fault_phase in {"catalog_deadline", "catalog_initial_deadline", "catalog_owner_crash_expired"}
                else timedelta(seconds=30))))
        catalog_boot_id = str(uuid4())
        catalog_operation, catalog_replay = admit_operation(runtime.domain, config_ref=config,
            request=catalog_request, core_boot_id=catalog_boot_id, reservation_ref=None,
            semantic_key=catalog_request["idempotency_key"], created_at_utc=domain_time(now))
        assert not catalog_replay
        if actual_catalog:
            slot = config_value["binding_slot_key"]
            catalog_binding = {"ref": binding_revision.as_dict(), "state": "active",
                "extension_id": config_value["extension_id"],
                "installation_digest": config_value["installation_digest"],
                "qualification_ref": qualification.as_dict(),
                "port_contract_version": "provider-port-v1", "binding_slot_key": slot,
                "binding_slot_key_digest": config_value["binding_slot_key_digest"],
                "grant_refs": config_grants, "credential_handle_refs": [connection.as_dict()]}
            catalog_authority = ProviderSemanticAuthority(binding_record=catalog_binding,
                current_connection=pin,
                qualification_record={"ref": qualification.as_dict(), "status": "qualified",
                    "installation_digest": config_value["installation_digest"],
                    "port_contract_version": "provider-port-v1",
                    "expires_at": port_time(now + timedelta(hours=2))},
                binding_head_record={"state": "active",
                    "current_binding_revision_ref": binding_revision.as_dict(),
                    "binding_slot_key": slot,
                    "binding_slot_key_digest": config_value["binding_slot_key_digest"]},
                actor_record={"ref": runtime.roots.actor.as_dict(), "authenticated": True,
                              "actor_type": "system"},
                purpose_record={"ref": purpose.as_dict(), "active": True,
                                "purpose": "operational"},
                grant_records=deepcopy(selected_grant_records), artifact_records={},
                selector_records={}, input_records={}, core_boot_id=catalog_boot_id)
            catalog_worker_service = ProviderPortService()
            catalog_worker_client = ProviderPortClient(transport_factory=frame_factory(
                worker_spec(tmp_path / "catalog-worker-pair"), broker.BootSecret(b"c" * 32),
                lambda sock, codec, deadline: catalog_worker_service.serve_authenticated(
                    sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000)
            catalog_send_service = ProviderSendService(CredentialedProviderTransport(
                vault, gateway_binding(port)))
            catalog_send_client = ProviderSendClient(transport_factory=frame_factory(
                authenticated_spec(tmp_path / "catalog-send-pair"), broker.BootSecret(b"g" * 32),
                lambda sock, codec, deadline: catalog_send_service.serve_authenticated(
                    sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000)
            catalog_loader = ProviderSemanticContextLoader(runtime.domain, config_ref=config,
                operation_ref=catalog_operation, authority=catalog_authority)
            catalog_transport = ProviderAttemptTransport(domain_store=runtime.domain,
                ledger=runtime.ledger, budget_book=runtime.book, context_loader=catalog_loader,
                worker_client=catalog_worker_client, send_client=catalog_send_client)
            if fault_phase == "catalog_grant_non_subset":
                retained_bytes = canonical_json(runtime.domain.get(catalog_operation).body)
                with pytest.raises(ProviderSemanticError, match="identity differs from config"):
                    catalog_transport.execute_catalog()
                assert catalog_loader.consume_owner_capability(), "non-subset consumed the owner"
                assert load_terminal(runtime.domain, catalog_operation) is None
                assert canonical_json(runtime.domain.get(catalog_operation).body) == retained_bytes
                assert captures == [] and threads == [] and failures == []
                return
            if fault_phase == "catalog_initial_permission":
                catalog_authority.qualification_record["status"] = "revoked"
            elif fault_phase == "catalog_initial_deadline":
                deadline = datetime.fromisoformat(
                    catalog_request["deadline_at"].replace("Z", "+00:00"))
                time.sleep(max(0.0, (deadline - datetime.now(
                    timezone.utc)).total_seconds()) + 0.050)
            elif fault_phase == "catalog_broker_deadline":
                monkeypatch.setattr(catalog_send_client, "prepare", lambda *args, **kwargs: (
                    _ for _ in ()).throw(broker.DeadlineExceeded()))
                broker_errors = []
                original_catalog_failure = catalog_transport._seal_catalog_failure
                def capture_catalog_failure(*args, **kwargs):
                    broker_errors.append(args[-1])
                    return original_catalog_failure(*args, **kwargs)
                monkeypatch.setattr(catalog_transport, "_seal_catalog_failure",
                                    capture_catalog_failure)
            if fault_phase in {"catalog_continuation", "catalog_revoked", "catalog_deadline"}:
                original_observe = catalog_worker_client.observe
                def perturb_catalog_observation(proposal, **kwargs):
                    value = original_observe(proposal, **kwargs)
                    if type(value) is __import__("app.workers.provider_port_messages",
                            fromlist=["ProviderProposal"]).ProviderProposal:
                        if fault_phase == "catalog_continuation":
                            return replace(value, after_id="wrong-cursor")
                        if fault_phase == "catalog_revoked":
                            catalog_authority.current_connection["revision_digest"] = "f" * 64
                        else:
                            deadline = datetime.fromisoformat(
                                catalog_request["deadline_at"].replace("Z", "+00:00"))
                            time.sleep(max(0.0, (deadline - datetime.now(
                                timezone.utc)).total_seconds()) + 0.050)
                    return value
                monkeypatch.setattr(catalog_worker_client, "observe",
                                    perturb_catalog_observation)
            if fault_phase == "catalog_worker_local_failure":
                original_catalog_observe = catalog_worker_client.observe
                def fail_after_valid_catalog_page(*args, **kwargs):
                    original_catalog_observe(*args, **kwargs)
                    raise RuntimeError("test-owned local catalog failure after valid page")
                monkeypatch.setattr(catalog_worker_client, "observe", fail_after_valid_catalog_page)
            if fault_phase == "catalog_worker_protocol_failure":
                from app.workers.credential_channel import decode_op
                original_write = broker.FrameCodec.write
                original_failure = catalog_transport._seal_catalog_failure
                protocol_errors = []
                def skip_authenticated_sequence(codec, *args, **kwargs):
                    if codec.local_service == "semantic-worker":
                        value = decode_op(kwargs["payload"])
                        if (value.get("schema") == "provider-semantic-proposal-v1"
                                and value.get("after_id") is not None):
                            object.__setattr__(codec, "_next_send", codec._next_send + 1)
                    return original_write(codec, *args, **kwargs)
                def trace_protocol_failure(*args, **kwargs):
                    protocol_errors.append(args[-1])
                    return original_failure(*args, **kwargs)
                monkeypatch.setattr(broker.FrameCodec, "write", skip_authenticated_sequence)
                monkeypatch.setattr(catalog_transport, "_seal_catalog_failure", trace_protocol_failure)
            if fault_phase in {"catalog_owner_crash", "catalog_owner_crash_expired"}:
                monkeypatch.setattr(catalog_transport, "_seal_catalog_failure",
                    lambda *args, **kwargs: (_ for _ in ()).throw(
                        RuntimeError("test-owned catalog terminal crash")))
            if fault_phase in {"catalog_malformed", "catalog_non2xx", "catalog_media",
                               "catalog_continuation", "catalog_revoked", "catalog_deadline",
                               "catalog_initial_permission", "catalog_initial_deadline",
                               "catalog_broker_deadline", "catalog_owner_crash", "catalog_owner_crash_expired",
                               "catalog_worker_local_failure", "catalog_worker_protocol_failure"}:
                if fault_phase in {"catalog_owner_crash", "catalog_owner_crash_expired"}:
                    with pytest.raises(RuntimeError, match="catalog terminal crash"):
                        catalog_transport.execute_catalog()
                    captured = len(captures)
                    retained_bytes = canonical_json(runtime.domain.get(catalog_operation).body)
                    if fault_phase == "catalog_owner_crash_expired":
                        expires = datetime.fromisoformat(catalog_request["deadline_at"].replace("Z", "+00:00"))
                        time.sleep(max(0.0, (expires - datetime.now(timezone.utc)).total_seconds()) + 0.020)
                    second_transport = ProviderAttemptTransport(domain_store=runtime.domain,
                        ledger=runtime.ledger, budget_book=runtime.book,
                        context_loader=ProviderSemanticContextLoader(runtime.domain,
                            config_ref=config, operation_ref=catalog_operation,
                            authority=catalog_authority),
                        worker_client=ProviderPortClient(transport_factory=frame_factory(
                            worker_spec(tmp_path / "catalog-worker-second"),
                            broker.BootSecret(b"d" * 32),
                            lambda sock, codec, deadline: ProviderPortService().serve_authenticated(
                                sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000),
                        send_client=ProviderSendClient(transport_factory=frame_factory(
                            authenticated_spec(tmp_path / "catalog-send-second"),
                            broker.BootSecret(b"h" * 32),
                            lambda sock, codec, deadline: ProviderSendService(
                                CredentialedProviderTransport(vault, gateway_binding(port))).serve_authenticated(
                                    sock, codec, deadline=deadline), threads, failures),
                            deadline_ms=5_000))
                    with pytest.raises(ValueError, match="owned or unavailable"):
                        second_transport.execute_catalog()
                    assert len(captures) == captured == 1
                    assert load_terminal(runtime.domain, catalog_operation) is None
                    assert canonical_json(runtime.domain.get(catalog_operation).body) == retained_bytes
                else:
                    failed_ref = catalog_transport.execute_catalog()
                    failed = runtime.domain.get(failed_ref).body["content"]["result"]
                    assert failed["terminal"] == "failed" and failed["output"] == {}, (failed, captures)
                    expected = ({"catalog_non2xx": "dependency_unavailable",
                                 "catalog_media": "unsupported_capability",
                                 "catalog_deadline": "deadline_exceeded",
                                 "catalog_initial_permission": "permission_denied",
                                 "catalog_initial_deadline": "deadline_exceeded",
                                 "catalog_broker_deadline": "deadline_exceeded",
                                 "catalog_worker_local_failure": "internal_failure",
                                 "catalog_worker_protocol_failure": "integrity_failed",
                                 "catalog_revoked": "permission_denied"}.get(
                                     fault_phase, "port_specific_failure"))
                    if fault_phase == "catalog_broker_deadline":
                        assert len(broker_errors) == 1
                        assert type(broker_errors[0]) is broker.DeadlineExceeded
                    assert failed["error"]["code"] == expected
                    if fault_phase == "catalog_worker_protocol_failure":
                        assert len(protocol_errors) == 1 and type(protocol_errors[0]) is broker.ProtocolViolation
                    if fault_phase in {"catalog_worker_local_failure", "catalog_worker_protocol_failure"}:
                        from app.domain.store import BlobRef
                        from app.extensions.provider_semantic_records import (
                            _load_by_owner,
                        )
                        retained_page = _load_by_owner(runtime.domain, kind="validation_report",
                            tag="provider-semantic-page-v1", owner_uuid=catalog_request["request_id"])
                        assert retained_page is not None
                        assert runtime.domain.read_blob(BlobRef.from_dict(
                            retained_page.body["content"]["raw_blob"]), purpose="operational") == page(["model-1"], more=True)
                        assert _load_by_owner(runtime.domain,
                            tag="provider-semantic-catalog-v1", owner_uuid=catalog_request["request_id"],
                            kind="model_catalog") is None
                        assert len(captures) == 1
                    if fault_phase == "catalog_media":
                        response_record = runtime.domain.get(EntityRef.from_dict(
                            runtime.domain.get(failed_ref).body["content"][
                                "response_ref"])).body["content"]
                        assert response_record["failure_class"] == "unsupported_capability"
                        assert response_record["raw_blob"] is not None
                    captured = len(captures)
                    if fault_phase == "catalog_deadline":
                        assert captured == 1
                    assert catalog_transport.execute_catalog() == failed_ref
                    assert len(captures) == captured
                for thread in threads:
                    thread.join(2)
                    assert not thread.is_alive()
                assert failures == []
                return
            first_catalog_terminal = catalog_transport.execute_catalog()
            captured_after_first = len(captures)
            assert captured_after_first == 2
            assert catalog_transport.execute_catalog() == first_catalog_terminal
            assert len(captures) == captured_after_first
            first_catalog = EntityRef.from_dict(runtime.domain.get(first_catalog_terminal).body[
                "content"]["result"]["output"]["catalog_ref"])
            first_catalog_content = runtime.domain.get(first_catalog).body["content"]
            if fault_phase == "catalog_grant_subset":
                assert first_catalog_content["complete"] is True
                assert catalog_request["grant_refs"] == [grant_ref.as_dict()]
                assert len(config_grants) == 2 and extra_grant.sha256 not in catalog_authority.grant_records
                _assert_subset_replay_is_immutable(runtime.domain, config, catalog_operation,
                    catalog_request, catalog_boot_id, None, domain_time(now), config_grants)
                for projection, field, denied in (
                        (catalog_authority.actor_record, "authenticated", False),
                        (catalog_authority.purpose_record, "active", False),
                        (catalog_authority.grant_records[grant_ref.sha256], "active", False)):
                    original = projection[field]
                    projection[field] = denied
                    with pytest.raises(ProviderSemanticError, match="unauthorized"):
                        catalog_transport.execute_catalog()
                    projection[field] = original
                assert catalog_transport.execute_catalog() == first_catalog_terminal
                assert len(captures) == 2
                for thread in threads:
                    thread.join(2)
                    assert not thread.is_alive()
                assert failures == []
                return

            def load_catalog_epoch(epoch_ref):
                epoch_request = __import__("app.tests.support.provider_semantic_harness",
                    fromlist=["canonical_provider_request"]).canonical_provider_request(
                        "catalog", {"catalog_epoch": epoch_ref.as_dict()},
                        identity=request_identity,
                        deadline_at=port_time(now + timedelta(seconds=30)))
                epoch_operation, epoch_replay = admit_operation(runtime.domain,
                    config_ref=config, request=epoch_request, core_boot_id=catalog_boot_id,
                    reservation_ref=None, semantic_key=epoch_request["idempotency_key"],
                    created_at_utc=domain_time(now))
                assert not epoch_replay
                epoch_authority = replace(catalog_authority, input_records={
                    epoch_ref.sha256: {"ref": epoch_ref.as_dict(),
                                       "record_type": "catalog_epoch"}})
                return ProviderSemanticContextLoader(runtime.domain, config_ref=config,
                    operation_ref=epoch_operation, authority=epoch_authority).load(
                        now_utc=domain_time(now))

            assert load_catalog_epoch(first_catalog).catalog_ref == first_catalog
            wrong_connection_content = deepcopy(runtime.domain.get(connection).body["content"])
            wrong_connection_content["locator"] = {"kind": "connection", "id": str(uuid4())}
            wrong_connection = _record(runtime.domain, "validation_report",
                                       wrong_connection_content)
            wrong_catalog_content = deepcopy(first_catalog_content)
            wrong_catalog_content["connection_ref"] = wrong_connection.as_dict()
            wrong_catalog = _record(runtime.domain, "model_catalog", wrong_catalog_content,
                parents=tuple(sorted({EntityRef.from_dict(first_catalog_content["operation_ref"]),
                    wrong_connection, *[EntityRef.from_dict(item) for item in
                    first_catalog_content["page_refs"]]},
                    key=lambda item: canonical_json(item.as_dict()))))
            for invalid_epoch in (wrong_catalog, config):
                with pytest.raises(ProviderSemanticError):
                    load_catalog_epoch(invalid_epoch)
            missing_epoch = EntityRef("model_catalog", str(uuid4()), 1, "0" * 64)
            malformed_epoch_request = __import__(
                "app.tests.support.provider_semantic_harness",
                fromlist=["canonical_provider_request"]).canonical_provider_request(
                    "catalog", {"catalog_epoch": missing_epoch.as_dict()},
                    identity=request_identity,
                    deadline_at=port_time(now + timedelta(seconds=30)))
            with pytest.raises(ValueError, match="not registered"):
                admit_operation(runtime.domain, config_ref=config,
                    request=malformed_epoch_request, core_boot_id=catalog_boot_id,
                    reservation_ref=None,
                    semantic_key=malformed_epoch_request["idempotency_key"],
                    created_at_utc=domain_time(now))
            revoked_catalog_authority = replace(catalog_authority,
                current_connection={**catalog_authority.current_connection,
                                    "revision_digest": "f" * 64},
                core_boot_id=str(uuid4()))
            historical_catalog_transport = ProviderAttemptTransport(
                domain_store=runtime.domain, ledger=runtime.ledger, budget_book=runtime.book,
                context_loader=ProviderSemanticContextLoader(runtime.domain, config_ref=config,
                    operation_ref=catalog_operation, authority=revoked_catalog_authority),
                worker_client=catalog_worker_client, send_client=catalog_send_client)
            assert historical_catalog_transport.execute_catalog() == first_catalog_terminal
            assert len(captures) == captured_after_first
            refreshed_request = __import__("app.tests.support.provider_semantic_harness",
                fromlist=["canonical_provider_request"]).canonical_provider_request(
                    "catalog", {"catalog_epoch": None}, identity=request_identity,
                    deadline_at=port_time(now + timedelta(seconds=30)))
            refreshed_operation, refreshed_replay = admit_operation(runtime.domain,
                config_ref=config, request=refreshed_request, core_boot_id=catalog_boot_id,
                reservation_ref=None, semantic_key=refreshed_request["idempotency_key"],
                created_at_utc=domain_time(now))
            assert not refreshed_replay and refreshed_operation != catalog_operation
            refreshed_loader = ProviderSemanticContextLoader(runtime.domain, config_ref=config,
                operation_ref=refreshed_operation, authority=catalog_authority)
            refreshed_transport = ProviderAttemptTransport(domain_store=runtime.domain,
                ledger=runtime.ledger, budget_book=runtime.book, context_loader=refreshed_loader,
                worker_client=catalog_worker_client, send_client=catalog_send_client)
            refreshed_terminal = refreshed_transport.execute_catalog()
            refreshed_result = runtime.domain.get(refreshed_terminal).body[
                "content"]["result"]
            refreshed_error = refreshed_result.get("error")
            diagnostic = {
                "terminal": refreshed_result.get("terminal"),
                "error": (None if type(refreshed_error) is not dict else {
                    name: refreshed_error[name]
                    for name in ("code", "classification", "category")
                    if name in refreshed_error
                }),
                "peer_failures": [{
                    "type": type(error).__name__,
                    "code": getattr(error, "code", None),
                    "dispatch_effect": getattr(error, "dispatch_effect", None),
                } for error in failures],
            }
            assert (refreshed_terminal != first_catalog_terminal
                    and len(captures) == 4), diagnostic
            catalog = EntityRef.from_dict(runtime.domain.get(refreshed_terminal).body[
                "content"]["result"]["output"]["catalog_ref"])
            catalog_content = runtime.domain.get(catalog).body["content"]
            assert catalog_content["complete"] is True
            assert [row["model_id"] for row in catalog_content["models"]] == ["model-1", "model-2"]
            assert catalog_content["eligible_model_ids"] == ["model-1"]
        else:
            catalog_raw = page(["model-1"])
            if fault_phase == "output_limit":
                catalog_raw = catalog_raw.replace(b'"max_tokens":8192', b'"max_tokens":1')
            traversal = advance_catalog(CatalogTraversal(), parse_model_page(catalog_raw))
            catalog = seal_catalog_traversal(runtime.domain, operation_ref=catalog_operation,
                connection_ref=connection, text_policy_ref=text_policy,
                compatibility_by_model=({} if fault_phase == "unsupported_model"
                                        else {"model-1": compatibility}), traversal=traversal,
                raw_pages=(catalog_raw,), fetched_at=port_time(now),
                expires_at=port_time(now + (timedelta(seconds=1)
                    if fault_phase == "stale_catalog" else timedelta(hours=1))),
                created_at_utc=domain_time(now))
            if fault_phase == "catalog_provenance":
                retained_catalog = runtime.domain.get(catalog).body["content"]
                alternate_request = __import__("app.tests.support.provider_semantic_harness",
                    fromlist=["canonical_provider_request"]).canonical_provider_request(
                        "catalog", {"catalog_epoch": None}, identity=request_identity,
                        deadline_at=port_time(now + timedelta(seconds=30)))
                alternate_operation = seal_operation(runtime.domain, config_ref=config,
                    request=alternate_request, core_boot_id=str(uuid4()), reservation_ref=None,
                    created_at_utc=domain_time(now))
                catalog = seal_catalog(runtime.domain, operation_ref=alternate_operation,
                    connection_ref=connection, fetched_at=retained_catalog["fetched_at"],
                    expires_at=retained_catalog["expires_at"],
                    page_refs=[EntityRef.from_dict(item) for item in retained_catalog["page_refs"]],
                    complete=True, models=retained_catalog["models"],
                    eligible_model_ids=retained_catalog["eligible_model_ids"],
                    excluded=retained_catalog["excluded"], created_at_utc=domain_time(now))
        input_blob = runtime.domain.put_blob(b"dispatcher input", purpose="operational")
        input_artifact = _record(runtime.domain, "artifact", {"blob_ref": input_blob.as_dict()})
        projection = {"profile_id": "execution-model-step", "system_artifact_ref": None}
        frozen_value = {
            "schema_version": "provider-semantic-frozen-v1",
            "turn": {"profile": "execution-model-step", "work_ref": runtime.refs.work.as_dict(),
                "environment_ref": runtime.refs.environment.as_dict(), "node_id": "writer",
                "execution_id": execution.execution_id, "attempt_index": 0, "provider": "claude_api",
                "account_id": ("other" if fault_phase == "account_mismatch" else "account"),
                "catalog_ref": catalog.as_dict(), "model_id": "model-1",
                "effort": None, "instruction_profile_digest": instruction_projection_digest(projection),
                "inputs": [{"type": "text", "ref": input_artifact.as_dict(), "marker": None,
                            "omissions": []}], "granted_tools": [], "output_schema_id": None,
                "runtime_profile_ref": runtime.refs.profile.as_dict(), "deadline_seconds": 30,
                "budget_ref": runtime.refs.budget.as_dict(), "consent_ref": runtime.refs.consent.as_dict()},
            "execution_envelope_ref": runtime.refs.envelope.as_dict(),
            "purpose_ref": purpose.as_dict(), "grant_refs": grant_refs,
            "artifact_input_bindings": [{"artifact_ref": input_artifact.as_dict(),
                "selector_ref": None, "declared_media_type": "text/plain", "role": "model_input"}],
            "messages": [{"role": "user", "input_ordinals": [0]}], "max_output_tokens": 32,
            "instruction_projection": projection}
        frozen_ref = seal_frozen(runtime.domain, command_id=str(uuid4()), content=frozen_value,
                                 created_at_utc=domain_time(now))
        proposal_body = encode_text_body(frozen_value, (b"dispatcher input",))
        method_blob = runtime.domain.put_blob(b"synthetic controlled-upstream tariff",
                                              purpose="operational")
        reservation = _record(runtime.domain, "validation_report", {
            "schema_version": "provider-semantic-reservation-v1",
            "connection_ref": connection.as_dict(), "model_id": "model-1",
            "proposal_sha256": sha256(proposal_body).hexdigest(), "input_upper_bound": 64,
            "max_output_tokens": 32, "currency": reservation_currency,
            "reserved_microunits": 50_000,
            "effective_at": port_time(now - timedelta(minutes=1)),
            "expires_at": port_time(now + timedelta(hours=1)), "method_blob": method_blob.as_dict(),
            "reviewer_ref": runtime.roots.actor.as_dict(), "basis": "reviewed-conservative-estimate"},
            parents=tuple(sorted((connection, runtime.roots.actor),
                                 key=lambda item: canonical_json(item.as_dict()))))
        semantic_request = __import__("app.tests.support.provider_semantic_harness",
            fromlist=["canonical_provider_request"]).canonical_provider_request(
            "model_step", {"frozen_turn_ref": frozen_ref.as_dict(),
            "model_id": "model-1", "effort": None, "requested_modalities": ["text"],
            "tool_definition_refs": [], "response_schema_ref": None}, identity=request_identity,
            artifact_inputs=frozen_value["artifact_input_bindings"],
            deadline_at=port_time(now + (timedelta(seconds=1.5)
                if fault_phase in {"model_deadline", "model_owner_missing_expired",
                                   "model_owner_consumed_expired"} else timedelta(seconds=30))))
        model_boot_id = str(uuid4())
        operation, replay = admit_operation(runtime.domain, config_ref=config, request=semantic_request,
            core_boot_id=model_boot_id, reservation_ref=reservation,
            semantic_key=semantic_request["idempotency_key"], created_at_utc=domain_time(now))
        assert not replay
        slot = config_value["binding_slot_key"]
        binding_record = {"ref": binding_revision.as_dict(), "state": "active",
            "extension_id": config_value["extension_id"],
            "installation_digest": config_value["installation_digest"],
            "qualification_ref": qualification.as_dict(), "port_contract_version": "provider-port-v1",
            "binding_slot_key": slot, "binding_slot_key_digest": config_value["binding_slot_key_digest"],
            "grant_refs": config_grants, "credential_handle_refs": [connection.as_dict()]}
        authority = ProviderSemanticAuthority(
            binding_record=binding_record, current_connection=pin,
            qualification_record={
                "ref": qualification.as_dict(), "status": "qualified",
                "installation_digest": config_value["installation_digest"],
                "port_contract_version": "provider-port-v1",
                "expires_at": port_time(now + timedelta(hours=2))},
            binding_head_record={"state": "active",
                "current_binding_revision_ref": binding_revision.as_dict(),
                "binding_slot_key": slot,
                "binding_slot_key_digest": config_value["binding_slot_key_digest"]},
            actor_record={"ref": runtime.roots.actor.as_dict(), "authenticated": True,
                          "actor_type": "system"},
            purpose_record={"ref": purpose.as_dict(), "active": True, "purpose": "operational"},
            grant_records=deepcopy(selected_grant_records),
            artifact_records={input_artifact.sha256: {
                "ref": input_artifact.as_dict(), "readable": True, "purpose_ref": purpose.as_dict(),
                "grant_refs": grant_refs, "media_type": "text/plain", "byte_count": input_blob.size}},
            selector_records={}, input_records={frozen_ref.sha256: {
                "ref": frozen_ref.as_dict(), "record_type": "frozen_turn"}},
            core_boot_id=model_boot_id)
        loader = ProviderSemanticContextLoader(runtime.domain, config_ref=config,
                                               operation_ref=operation, authority=authority)

        worker_service = ProviderPortService()
        worker_specification = worker_spec(tmp_path / "worker-pair")
        worker_client = ProviderPortClient(transport_factory=frame_factory(
            worker_specification, broker.BootSecret(b"w" * 32),
            lambda sock, codec, deadline: worker_service.serve_authenticated(
                sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000)
        model_gateway_binding = gateway_binding(port)
        if fault_phase == "gateway_capacity":
            model_gateway_binding = replace(model_gateway_binding, max_response_bytes=64)
        send_service = ProviderSendService(CredentialedProviderTransport(
            vault, model_gateway_binding))
        send_specification = authenticated_spec(tmp_path / "send-pair")
        send_client = ProviderSendClient(transport_factory=frame_factory(
            send_specification, broker.BootSecret(b"s" * 32),
            lambda sock, codec, deadline: send_service.serve_authenticated(
                sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000)
        controller = ProviderSemanticOperationController(runtime.domain, ledger=runtime.ledger,
            config_ref=config, core_boot_id=str(uuid4()), authority=authority)
        transport = ProviderAttemptTransport(domain_store=runtime.domain, ledger=runtime.ledger,
            budget_book=runtime.book, context_loader=loader, worker_client=worker_client,
            send_client=send_client, operation_controller=controller)
        if fault_phase == "initial_permission":
            authority.qualification_record["status"] = "revoked"
        if fault_phase == "session_mismatch":
            original_begin = worker_client.begin
            def corrupt_authenticated_session(*args, **kwargs):
                value = original_begin(*args, **kwargs)
                observed = worker_client._authenticated_session
                worker_client._authenticated_session = (observed[0], "wrong-channel",
                    *observed[2:])
                return value
            monkeypatch.setattr(worker_client, "begin", corrupt_authenticated_session)

        owner = OwnerIdentity(str(uuid4()), 4321, 900, str(uuid4()))
        # a generous dispatch window (the lease bounds it): the path before the send
        # (worker proposal, gateway prepare, authority reload) outlasted a one-second
        # lease on a slower host; the deadline faults below move the clock explicitly
        binding = AttemptBinding.create(envelope_ref=runtime.refs.envelope,
            profile_ref=runtime.refs.profile, budget_policy_ref=runtime.refs.budget,
            deadline_at_ms=60_000,
            lease_duration_ms=1_000 if fault_phase in {"deadline_after_worker", "deadline_after_reload"}
            else 30_000, model_calls=1, tool_calls=0,
            node_visits=1, loop_rounds=0, output_bytes=524_288, candidates=0,
            api_microunits=50_000, principal=runtime.principal, grant=runtime.grant)
        dispatcher = NodeAttemptDispatcher.build(ledger=runtime.ledger, budget_book=runtime.book,
            owner=owner, bindings={"writer": binding}, transport=transport)
        if fault_phase == "model_grant_subset":
            identity_failures = []
            original_identity = loader._operation_identity
            def trace_model_identity():
                try:
                    return original_identity()
                except ProviderSemanticError as exc:
                    identity_failures.append(str(exc))
                    raise
            monkeypatch.setattr(loader, "_operation_identity", trace_model_identity)
            try:
                result_ref = dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
                terminal = load_terminal(runtime.domain, operation)
                assert terminal.ref == result_ref
                assert terminal.body["content"]["result"]["terminal"] == "succeeded"
                assert semantic_request["grant_refs"] == frozen_value["grant_refs"] == [grant_ref.as_dict()]
                assert authority.artifact_records[input_artifact.sha256]["grant_refs"] == grant_refs
                assert len(config_grants) == 2 and extra_grant.sha256 not in authority.grant_records
                _assert_subset_replay_is_immutable(runtime.domain, config, operation,
                    semantic_request, model_boot_id, reservation, domain_time(now), config_grants)
                historical_request = AttemptDispatchRequest(run.run_id, "writer",
                    execution.execution_id, attempt_identity(run.run_id, "writer", 0, 0),
                    runtime.refs.envelope, runtime.refs.profile, 10_000)
                assert transport._historical_model_replay(historical_request).result_ref == result_ref
                for projection, field, denied in (
                        (authority.actor_record, "authenticated", False),
                        (authority.purpose_record, "active", False),
                        (authority.grant_records[grant_ref.sha256], "active", False)):
                    original = projection[field]
                    projection[field] = denied
                    with pytest.raises(ProviderSemanticError, match="unauthorized"):
                        transport._historical_model_replay(historical_request)
                    projection[field] = original
                assert dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch() == result_ref
                assert len(captures) == 1 and captures[0][0] == "POST"
                assert captures[0][3] == proposal_body
                assert runtime.ledger.get_attempt(historical_request.attempt_id)["usage_finality"] == "provisional"
                assert runtime.book.status(runtime.session_id)["active_reservations"] == 1
            finally:
                worker_client.abandon()
                for thread in threads:
                    thread.join(2)
                    assert not thread.is_alive()
                assert identity_failures == [], f"actual identity rejection: {identity_failures}"
            assert failures == []
            return
        if fault_phase == "success_cancel_latch":
            import http.client

            import app.runtime.provider_attempt_transport as transport_module
            original_seal = transport_module.seal_terminal
            seal_failures = []
            def trace_success_seal(*args, **kwargs):
                try:
                    return original_seal(*args, **kwargs)
                except Exception as exc:
                    response_content = runtime.domain.get(kwargs["response_ref"]).body["content"]
                    seal_failures.append((type(exc).__name__, str(exc),
                        kwargs["result"]["terminal"], response_content["cancel_observed"]))
                    raise
            monkeypatch.setattr(transport_module, "seal_terminal", trace_success_seal)
            original_exchange = CredentialedProviderTransport.exchange
            original_close = http.client.HTTPConnection.close
            original_read = http.client.HTTPResponse.read1
            active_lease = []
            body_complete = threading.Event()
            def observe_body_eof(response, *args, **kwargs):
                block = original_read(response, *args, **kwargs)
                if not block:
                    body_complete.set()
                return block
            def retain_exchange_lease(subject, *, lease):
                active_lease.append(lease)
                return original_exchange(subject, lease=lease)
            def latch_after_complete_body(connection):
                original_close(connection)
                if (body_complete.is_set() and active_lease
                        and connection.host == "127.0.0.1" and connection.port == port):
                    # Gateway finally closes HTTP after its last body-cancel checkpoint,
                    # then samples this same Event into the completed observation.
                    active_lease[-1].cancel_event.set()
            monkeypatch.setattr(CredentialedProviderTransport, "exchange", retain_exchange_lease)
            monkeypatch.setattr(http.client.HTTPConnection, "close", latch_after_complete_body)
            monkeypatch.setattr(http.client.HTTPResponse, "read1", observe_body_eof)
            try:
                result_ref = dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
                terminal = load_terminal(runtime.domain, operation)
                assert terminal.ref == result_ref
                result = terminal.body["content"]["result"]
                observed = runtime.domain.get(EntityRef.from_dict(
                    terminal.body["content"]["response_ref"])).body["content"]
                assert result["terminal"] == "succeeded" and result["error"] is None
                assert result["effect"]["effect_state"] == "committed"
                assert result["effect"]["remote_outcome"] == "confirmed"
                assert result["usage"]["provider_report_ref"] == result["output"]["usage_report_ref"]
                assert observed["cancel_observed"] is True
                assert observed["failure_class"] is None and observed["status"] == 200
                assert observed["phase"] == "terminal_observed"
                dialogue_count = len(threads)
                assert dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch() == result_ref
                assert len(threads) == dialogue_count and len(captures) == 1
            finally:
                worker_client.abandon()
                for thread in threads:
                    thread.join(2)
                    assert not thread.is_alive()
                assert seal_failures == [], f"actual seal rejection: {seal_failures}"
            assert failures == []
            return
        if fault_phase in {"model_owner_missing", "model_owner_missing_expired",
                           "model_owner_missing_revoked", "model_owner_consumed_expired",
                           "model_owner_consumed_revoked", "model_owner_missing_unauthenticated",
                           "model_subject_mismatch", "model_grant_non_subset"}:
            retained_bytes = canonical_json(runtime.domain.get(operation).body)
            if "consumed" in fault_phase or fault_phase == "model_owner_missing":
                assert loader.consume_owner_capability()
            elif fault_phase not in {"model_subject_mismatch", "model_grant_non_subset"}:
                # The original loader holds the only capability; a reconstructed one has none.
                transport._context_loader = ProviderSemanticContextLoader(runtime.domain,
                    config_ref=config, operation_ref=operation, authority=authority)
            if fault_phase.endswith("expired"):
                expires = datetime.fromisoformat(semantic_request["deadline_at"].replace("Z", "+00:00"))
                time.sleep(max(0.0, (expires - datetime.now(timezone.utc)).total_seconds()) + 0.020)
            if fault_phase.endswith("revoked"):
                authority.qualification_record["status"] = "revoked"
            if fault_phase == "model_owner_missing_unauthenticated":
                authority.actor_record["authenticated"] = False
            if fault_phase == "model_subject_mismatch":
                original_dispatch = transport._dispatch_model
                def wrong_subject(permit, request, window):
                    return original_dispatch(permit, replace(request, node_id="wrong-node"), window)
                monkeypatch.setattr(transport, "_dispatch_model", wrong_subject)
            with pytest.raises(Exception, match="attempt_outcome_unknown"):
                dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
            retained_attempt = runtime.ledger.lookup_committed_result(
                attempt_identity(run.run_id, "writer", 0, 0),
                execution.execution_id, runtime.refs.envelope)
            assert retained_attempt["outcome"] == "outcome_unknown"
            assert retained_attempt["result_ref"] is None
            assert load_terminal(runtime.domain, operation) is None
            assert canonical_json(runtime.domain.get(operation).body) == retained_bytes
            if fault_phase in {"model_subject_mismatch", "model_grant_non_subset"}:
                assert loader.consume_owner_capability(), "invalid identity consumed the owner"
            with pytest.raises(Exception, match="attempt_outcome_unknown"):
                dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
            assert captures == [] and threads == [] and failures == []
            return
        if fault_phase == "gateway_permission":
            original_permission_commit = ProviderSendService.commit
            retired = []
            def retire_before_delivery(self, *args, **kwargs):
                value = original_permission_commit(self, *args, **kwargs)
                if self is send_service and not retired:
                    retired.append(vault.retire(command_id=str(uuid4()),
                                                record=credential_record,
                                                reason="superseded"))
                return value
            monkeypatch.setattr(ProviderSendService, "commit", retire_before_delivery)
        if fault_phase == "stale_catalog":
            with pytest.raises(Exception, match="catalog is not current"):
                loader.load(now_utc=port_time(now + timedelta(seconds=2)))
            assert captures == [] and threads == [] and failures == []
            return
        if fault_phase in {"reservation_amount", "output_limit", "unsupported_model",
                           "model_deadline", "account_mismatch",
                           "catalog_provenance", "session_mismatch"}:
            if fault_phase == "catalog_provenance":
                catalog_value = runtime.domain.get(catalog).body["content"]
                page_value = runtime.domain.get(EntityRef.from_dict(
                    catalog_value["page_refs"][0])).body["content"]
                assert page_value["operation_ref"] != catalog_value["operation_ref"]
                with pytest.raises(Exception, match="retained catalog page projection is invalid"):
                    loader.load(now_utc=port_time(datetime.now(timezone.utc)))
            if fault_phase == "reservation_amount":
                mismatched_binding = replace(binding, api_microunits=49_999)
                dispatcher = NodeAttemptDispatcher.build(ledger=runtime.ledger,
                    budget_book=runtime.book, owner=owner, bindings={"writer": mismatched_binding},
                    transport=transport)
            if fault_phase == "model_deadline":
                request_deadline = datetime.fromisoformat(
                    semantic_request["deadline_at"].replace("Z", "+00:00"))
                time.sleep(max(0.0, (request_deadline - datetime.now(
                    timezone.utc)).total_seconds()) + 0.050)
            with pytest.raises(Exception, match="attempt_failed"):
                dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
            if fault_phase == "session_mismatch":
                for thread in threads:
                    thread.join(2)
                    assert not thread.is_alive()
                assert len(threads) == 1
            else:
                assert threads == []
            assert captures == [] and failures == []
            failed_attempt = attempt_identity(run.run_id, "writer", 0, 0)
            committed = runtime.ledger.lookup_committed_result(
                failed_attempt, execution.execution_id, runtime.refs.envelope)
            result = runtime.domain.get(EntityRef.from_dict(
                committed["result_ref"])).body["content"]["result"]
            expected_code = {"output_limit": "resource_exhausted",
                             "unsupported_model": "unsupported_capability",
                             "model_deadline": "deadline_exceeded"}.get(
                                 fault_phase, "integrity_failed")
            assert result["terminal"] == "failed" and result["error"]["code"] == expected_code
            return
        if reservation_currency != runtime.policy.currency:
            with pytest.raises(Exception, match="attempt_failed"):
                dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
            assert captures == [] and threads == [] and failures == []
            refused_attempt = attempt_identity(run.run_id, "writer", 0, 0)
            committed = runtime.ledger.lookup_committed_result(
                refused_attempt, execution.execution_id, runtime.refs.envelope)
            refused = runtime.domain.get(EntityRef.from_dict(committed["result_ref"])).body[
                "content"]["result"]
            assert refused["terminal"] == "failed"
            assert refused["error"]["code"] == "integrity_failed"
            return
        if fault_phase in {"gateway_permission", "gateway_capacity", "gateway_media"}:
            with pytest.raises(Exception):
                dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
            failed_attempt = attempt_identity(run.run_id, "writer", 0, 0)
            committed = runtime.ledger.lookup_committed_result(
                failed_attempt, execution.execution_id, runtime.refs.envelope)
            terminal_ref = EntityRef.from_dict(committed["result_ref"])
            terminal = runtime.domain.get(terminal_ref).body["content"]
            result = terminal["result"]
            response_record = runtime.domain.get(EntityRef.from_dict(
                terminal["response_ref"])).body["content"]
            expected_category = {"gateway_permission": "permission_denied",
                "gateway_capacity": "resource_exhausted",
                "gateway_media": "unsupported_capability"}[fault_phase]
            assert response_record["failure_class"] == expected_category
            if fault_phase == "gateway_permission":
                assert result["terminal"] == "failed"
                assert result["error"]["code"] == "permission_denied"
                assert response_record["phase"] == "not_sent"
                assert response_record["raw_blob"] is None and captures == []
            else:
                assert result["terminal"] == "unknown"
                assert result["error"]["code"] == "external_effect_unknown"
                assert response_record["raw_blob"] is not None and len(captures) == 1
            dialogue_count, capture_count = len(threads), len(captures)
            with pytest.raises(Exception):
                dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
            assert len(threads) == dialogue_count and len(captures) == capture_count
            for thread in threads:
                thread.join(2); assert not thread.is_alive()
            assert failures == []
            return
        if fault_phase in {"worker_prepare_exception", "worker_begin_deadline", "gateway_prepare_exception",
                           "final_reload_exception", "initial_permission",
                           "initial_grant_permission",
                           "deadline_after_worker", "deadline_after_reload",
                           "gateway_session_mismatch", "cleanup_cancel_exception",
                           "worker_observation_exception"}:
            if fault_phase == "worker_prepare_exception":
                monkeypatch.setattr(worker_client, "begin", lambda *args, **kwargs: (
                    _ for _ in ()).throw(RuntimeError("test-owned worker prepare failure")))
            elif fault_phase == "worker_begin_deadline":
                original_begin = worker_client.begin
                begin_errors = []
                def begin_with_expired_wire_budget(*args, **kwargs):
                    # Real begin reaches its broker deadline check before opening a channel.
                    try:
                        return original_begin(*args, **{**kwargs,
                            "deadline_end_monotonic": time.monotonic() - 0.001})
                    except broker.DeadlineExceeded as exc:
                        begin_errors.append(exc)
                        raise
                monkeypatch.setattr(worker_client, "begin", begin_with_expired_wire_budget)
            elif fault_phase == "gateway_prepare_exception":
                monkeypatch.setattr(send_client, "prepare", lambda *args, **kwargs: (
                    _ for _ in ()).throw(RuntimeError("test-owned gateway prepare failure")))
            elif fault_phase == "final_reload_exception":
                original_load = loader.load
                load_count = []
                def fail_final_reload(*args, **kwargs):
                    load_count.append(True)
                    if len(load_count) == 2:
                        raise RuntimeError("test-owned final authority reload failure")
                    return original_load(*args, **kwargs)
                monkeypatch.setattr(loader, "load", fail_final_reload)
            elif fault_phase == "deadline_after_worker":
                original_begin = worker_client.begin
                def expire_after_worker(*args, **kwargs):
                    value = original_begin(*args, **kwargs)
                    time.sleep(max(0.0, kwargs["deadline_end_monotonic"]
                                       - time.monotonic()) + 0.020)
                    return value
                monkeypatch.setattr(worker_client, "begin", expire_after_worker)
            elif fault_phase == "deadline_after_reload":
                original_load = loader.load
                load_count = []
                def expire_final_reload(*args, **kwargs):
                    value = original_load(*args, **kwargs)
                    load_count.append(True)
                    if len(load_count) == 2:
                        request_deadline = datetime.fromisoformat(
                            semantic_request["deadline_at"].replace("Z", "+00:00"))
                        time.sleep(max(0.0, (request_deadline - datetime.now(
                            timezone.utc)).total_seconds()) + 0.020)
                    return value
                monkeypatch.setattr(loader, "load", expire_final_reload)
            elif fault_phase in {"gateway_session_mismatch", "cleanup_cancel_exception"}:
                original_prepare = send_client.prepare
                def corrupt_gateway_session(*args, **kwargs):
                    value = original_prepare(*args, **kwargs)
                    observed = send_client._authenticated_session
                    send_client._authenticated_session = (observed[0], "wrong-channel",
                        *observed[2:])
                    return value
                monkeypatch.setattr(send_client, "prepare", corrupt_gateway_session)
                if fault_phase == "cleanup_cancel_exception":
                    original_cancel = ProviderSendService.cancel
                    def fail_cleanup(subject, *args, **kwargs):
                        if subject is send_service:
                            raise RuntimeError("test-owned cleanup failure")
                        return original_cancel(subject, *args, **kwargs)
                    monkeypatch.setattr(ProviderSendService, "cancel", fail_cleanup)
            else:
                monkeypatch.setattr(worker_client, "observe", lambda *args, **kwargs: (
                    _ for _ in ()).throw(RuntimeError("test-owned worker observation failure")))
            with pytest.raises(Exception):
                dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
            failed_attempt = attempt_identity(run.run_id, "writer", 0, 0)
            committed = runtime.ledger.lookup_committed_result(
                failed_attempt, execution.execution_id, runtime.refs.envelope)
            terminal = runtime.domain.get(EntityRef.from_dict(
                committed["result_ref"])).body["content"]
            result = terminal["result"]
            expected_code = ({"worker_prepare_exception": "internal_failure",
                              "worker_begin_deadline": "deadline_exceeded",
                              "gateway_prepare_exception": "internal_failure",
                              "final_reload_exception": "internal_failure",
                              "initial_permission": "permission_denied",
                              "initial_grant_permission": "permission_denied",
                              "deadline_after_worker": "deadline_exceeded",
                              "deadline_after_reload": "deadline_exceeded",
                              "gateway_session_mismatch": "integrity_failed",
                              "cleanup_cancel_exception": "integrity_failed",
                              "worker_observation_exception": "external_effect_unknown"}[
                                  fault_phase])
            assert result["error"]["code"] == expected_code
            if fault_phase == "worker_begin_deadline":
                assert len(begin_errors) == 1 and type(begin_errors[0]) is broker.DeadlineExceeded
            if fault_phase == "worker_observation_exception":
                assert result["terminal"] == "unknown"
                assert terminal["response_ref"] is not None and len(captures) == 1
            else:
                assert result["terminal"] == "failed"
                assert terminal["response_ref"] is None and captures == []
            for thread in threads:
                thread.join(2); assert not thread.is_alive()
            if fault_phase == "deadline_after_reload":
                assert [type(item) for item in failures] == [
                    ProviderSendError, broker.TransportUncertain]
                assert str(failures[1]) == "transport_uncertain"
            elif fault_phase == "cleanup_cancel_exception":
                assert len(failures) == 1 and type(failures[0]) is RuntimeError
                assert str(failures[0]) == "test-owned cleanup failure"
            else:
                assert failures == []
            return
        if fault_phase is not None:
            if fault_phase == "cancel_during_body":
                dispatched, dispatch_failures = [], []
                def dispatch_cancelled():
                    try:
                        dispatched.append(dispatcher.for_visit(run_id=run.run_id,
                            node_id="writer", execution_id=execution.execution_id,
                            loop_index=0).dispatch())
                    except BaseException as exc:
                        dispatch_failures.append(exc)
                dispatch_thread = threading.Thread(target=dispatch_cancelled)
                dispatch_thread.start()
                assert _entered.wait(2)
                query_identity = {name: semantic_request[name] for name in (
                    "installation_digest", "qualification_ref", "binding_revision_ref",
                    "purpose_ref", "actor_ref", "grant_refs")}
                cancel_request = __import__("app.tests.support.provider_semantic_harness",
                    fromlist=["canonical_provider_request"]).canonical_provider_request(
                    "cancel", {"operation_ref": operation.as_dict(),
                    "reason_class": "user_requested"}, identity=query_identity,
                    deadline_at=port_time(now + timedelta(seconds=30)))
                acknowledgement = controller.cancel(cancel_request,
                    semantic_key=cancel_request["idempotency_key"], observed_at=port_time(now),
                    created_at_utc=domain_time(now))
                assert acknowledgement["output"]["cancel_state"] == "accepted"
                dispatch_thread.join(2)
                assert not dispatch_thread.is_alive() and dispatched == []
                assert len(dispatch_failures) == 1
                assert "attempt_cancelled" in str(dispatch_failures[0])
                cancelled_attempt = attempt_identity(run.run_id, "writer", 0, 0)
                committed = runtime.ledger.lookup_committed_result(cancelled_attempt,
                    execution.execution_id, runtime.refs.envelope)
                cancelled = runtime.domain.get(EntityRef.from_dict(committed["result_ref"])).body[
                    "content"]["result"]
                assert cancelled["terminal"] == "cancelled"
                assert cancelled["effect"] == {"effect_class": "external_irreversible",
                    "effect_state": "unknown", "effect_receipt_ref": None,
                    "remote_outcome": "unconfirmed"}
                dialogue_count, capture_count = len(threads), len(captures)
                with pytest.raises(Exception, match="attempt_cancelled"):
                    dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                        execution_id=execution.execution_id, loop_index=0).dispatch()
                assert len(threads) == dialogue_count and len(captures) == capture_count == 1
                for thread in threads:
                    thread.join(2)
                    assert not thread.is_alive()
                assert failures == []
                return
            if fault_phase == "worker_body_substitution":
                original_begin = ProviderPortService.begin
                def substitute_body(self, *args, **kwargs):
                    proposal = original_begin(self, *args, **kwargs)
                    return (replace(proposal, body=proposal.body + b" ")
                            if self is worker_service else proposal)
                monkeypatch.setattr(ProviderPortService, "begin", substitute_body)
                with pytest.raises(Exception, match="attempt_failed"):
                    dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                        execution_id=execution.execution_id, loop_index=0).dispatch()
                failed_attempt = attempt_identity(run.run_id, "writer", 0, 0)
                committed = runtime.ledger.lookup_committed_result(failed_attempt,
                    execution.execution_id, runtime.refs.envelope)
                failed = runtime.domain.get(EntityRef.from_dict(committed["result_ref"])).body[
                    "content"]["result"]
                assert failed["terminal"] == "failed"
                assert failed["error"]["code"] == "integrity_failed"
                assert captures == []
                for thread in threads:
                    thread.join(2)
                    assert not thread.is_alive()
                assert failures == []
                return
            if fault_phase == "worker_observation_substitution":
                original_observe = worker_client.observe
                def substitute_observation(*args, **kwargs):
                    return replace(original_observe(*args, **kwargs),
                                   observed_model="substituted-model")
                monkeypatch.setattr(worker_client, "observe", substitute_observation)
                with pytest.raises(Exception, match="attempt_outcome_unknown"):
                    dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                        execution_id=execution.execution_id, loop_index=0).dispatch()
                failed_attempt = attempt_identity(run.run_id, "writer", 0, 0)
                committed = runtime.ledger.lookup_committed_result(failed_attempt,
                    execution.execution_id, runtime.refs.envelope)
                terminal = runtime.domain.get(EntityRef.from_dict(
                    committed["result_ref"])).body["content"]
                assert load_terminal(runtime.domain, operation).ref == EntityRef.from_dict(
                    committed["result_ref"])
                failed = terminal["result"]
                assert failed["terminal"] == "unknown"
                assert failed["error"]["code"] == "external_effect_unknown"
                assert terminal["response_ref"] is not None
                response_record = runtime.domain.get(EntityRef.from_dict(
                    terminal["response_ref"])).body["content"]
                assert runtime.domain.read_blob(__import__("app.domain.store",
                    fromlist=["BlobRef"]).BlobRef.from_dict(response_record["raw_blob"]),
                    purpose="operational") == response
                assert len(captures) == 1
                for thread in threads:
                    thread.join(2)
                    assert not thread.is_alive()
                assert failures == []
                return
            import app.runtime.provider_attempt_transport as attempt_transport_module
            import app.workers.provider_send_service as send_service_module
            original_commit = ProviderSendService.commit
            original_exchange = ProviderSendService.exchange
            original_seal = attempt_transport_module.seal_terminal
            original_accept = RuntimeLedger.accept_result_and_settle

            if fault_phase == "gateway_commit":
                def crash_after_commit(self, *args, **kwargs):
                    value = original_commit(self, *args, **kwargs)
                    if self is send_service:
                        raise ValueError("test-owned crash after gateway commit")
                    return value
                monkeypatch.setattr(ProviderSendService, "commit", crash_after_commit)
            elif fault_phase == "gateway_untrusted_result":
                original_encode = send_service_module.encode_op
                def corrupt_authenticated_result(value):
                    if (type(value) is dict
                            and value.get("schema") == "provider-send-result-v1"):
                        value = {**value, "failure_class": "untrusted-category"}
                    return original_encode(value)
                monkeypatch.setattr(send_service_module, "encode_op",
                                    corrupt_authenticated_result)
            elif fault_phase == "write_boundary":
                import http.client
                original_endheaders = http.client.HTTPConnection.endheaders
                def crash_after_actual_write(connection, *args, **kwargs):
                    original_endheaders(connection, *args, **kwargs)
                    raise OSError("test-owned crash after actual header write")
                monkeypatch.setattr(http.client.HTTPConnection, "endheaders",
                                    crash_after_actual_write)
            elif fault_phase == "response_observed":
                def crash_after_response(self, lease):
                    value = original_exchange(self, lease)
                    if self is send_service:
                        raise RuntimeError("test-owned crash after response")
                    return value
                monkeypatch.setattr(ProviderSendService, "exchange", crash_after_response)
            elif fault_phase == "terminal_store_failure":
                def fail_terminal_store(*args, **kwargs):
                    raise RuntimeError("test-owned terminal storage failure")
                monkeypatch.setattr(attempt_transport_module, "seal_terminal", fail_terminal_store)
            elif fault_phase == "terminal_sealed":
                def crash_after_terminal(*args, **kwargs):
                    value = original_seal(*args, **kwargs)
                    raise RuntimeError("test-owned crash after terminal seal")
                monkeypatch.setattr(attempt_transport_module, "seal_terminal", crash_after_terminal)
            elif fault_phase == "ledger_accepted":
                def crash_after_accept(self, *args, **kwargs):
                    value = original_accept(self, *args, **kwargs)
                    if self is runtime.ledger:
                        raise RuntimeError("test-owned crash after ledger acceptance")
                    return value
                monkeypatch.setattr(RuntimeLedger, "accept_result_and_settle", crash_after_accept)
            else:  # pragma: no cover - the closed parameter table makes this unreachable
                raise AssertionError(fault_phase)

            first_error = "test-owned crash after ledger acceptance" \
                if fault_phase == "ledger_accepted" else "attempt_outcome_unknown"
            with pytest.raises(Exception, match=first_error):
                dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch()
            for thread in threads:
                thread.join(2)
                assert not thread.is_alive()
            if fault_phase in {"gateway_commit", "gateway_untrusted_result"}:
                assert len(failures) == 1 and type(failures[0]) is ProviderSendError
            else:
                assert failures == []
            capture_count = len(captures)
            assert capture_count == (0 if fault_phase == "gateway_commit" else 1)
            if fault_phase == "gateway_untrusted_result":
                committed = runtime.ledger.lookup_committed_result(
                    attempt_identity(run.run_id, "writer", 0, 0),
                    execution.execution_id, runtime.refs.envelope)
                terminal = runtime.domain.get(EntityRef.from_dict(
                    committed["result_ref"])).body["content"]
                assert terminal["response_ref"] is None
                assert terminal["result"]["terminal"] == "unknown"
                assert terminal["result"]["error"]["code"] == "external_effect_unknown"

            # Reconstruct every new transport/controller/gateway object. The existing ledger's
            # committed send fence resolves the command before any of them can open a dialogue.
            restart_worker = ProviderPortClient(transport_factory=frame_factory(
                worker_specification, broker.BootSecret(b"w" * 32),
                lambda sock, codec, deadline: ProviderPortService().serve_authenticated(
                    sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000)
            restart_send = ProviderSendClient(transport_factory=frame_factory(
                send_specification, broker.BootSecret(b"s" * 32),
                lambda sock, codec, deadline: ProviderSendService(
                    CredentialedProviderTransport(vault, gateway_binding(port))).serve_authenticated(
                    sock, codec, deadline=deadline), threads, failures), deadline_ms=5_000)
            restart_transport = ProviderAttemptTransport(domain_store=runtime.domain,
                ledger=runtime.ledger, budget_book=runtime.book, context_loader=loader,
                worker_client=restart_worker, send_client=restart_send,
                operation_controller=ProviderSemanticOperationController(runtime.domain,
                    ledger=runtime.ledger, config_ref=config, core_boot_id=str(uuid4()),
                    authority=authority))
            restart_dispatcher = NodeAttemptDispatcher.build(ledger=runtime.ledger,
                budget_book=runtime.book, owner=owner, bindings={"writer": binding},
                transport=restart_transport)
            dialogue_count = len(threads)
            if fault_phase == "ledger_accepted":
                assert restart_dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch() is not None
            else:
                with pytest.raises(Exception, match="attempt_outcome_unknown"):
                    restart_dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                        execution_id=execution.execution_id, loop_index=0).dispatch()
            assert len(threads) == dialogue_count and len(captures) == capture_count
            return
        accept_entered, accept_release = threading.Event(), threading.Event()
        original_accept = RuntimeLedger.accept_result_and_settle
        def gated_accept(self, *args, **kwargs):
            if self is runtime.ledger:
                accept_entered.set()
                if not accept_release.wait(2):
                    raise TimeoutError("test-owned acceptance barrier elapsed")
            return original_accept(self, *args, **kwargs)
        monkeypatch.setattr(RuntimeLedger, "accept_result_and_settle", gated_accept)
        dispatched, dispatch_failures = [], []
        def dispatch():
            try:
                dispatched.append(dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                    execution_id=execution.execution_id, loop_index=0).dispatch())
            except BaseException as exc:
                dispatch_failures.append(exc)
        dispatch_thread = threading.Thread(target=dispatch)
        dispatch_thread.start()
        assert accept_entered.wait(2)
        query_identity = {name: semantic_request[name] for name in ("installation_digest",
            "qualification_ref", "binding_revision_ref", "purpose_ref", "actor_ref", "grant_refs")}
        status_before = __import__("app.tests.support.provider_semantic_harness",
            fromlist=["canonical_provider_request"]).canonical_provider_request(
            "status", {"operation_ref": operation.as_dict()}, identity=query_identity,
            deadline_at=port_time(now + timedelta(seconds=30)))
        preaccepted = controller.observe_status(status_before,
            semantic_key=status_before["idempotency_key"], observed_at=port_time(now),
            created_at_utc=domain_time(now))
        assert preaccepted["output"] == {"observed_state": "running",
            "observed_at": port_time(now), "terminal_result_ref": None}
        accept_release.set(); dispatch_thread.join(2)
        assert not dispatch_thread.is_alive()
        if response_mode == "malformed":
            assert dispatched == [] and len(dispatch_failures) == 1
            assert "attempt_outcome_unknown" in str(dispatch_failures[0])
            failed_attempt = attempt_identity(run.run_id, "writer", 0, 0)
            committed = runtime.ledger.lookup_committed_result(
                failed_attempt, execution.execution_id, runtime.refs.envelope)
            terminal = runtime.domain.get(EntityRef.from_dict(committed["result_ref"]))
            result = terminal.body["content"]["result"]
            assert result["terminal"] == "unknown"
            assert result["error"]["code"] == "external_effect_unknown"
            assert result["effect"]["remote_outcome"] == "unknown"
            assert len(captures) == 1
            return
        assert dispatch_failures == [] and len(dispatched) == 1
        result_ref = dispatched[0]
        status_after = {**status_before, "request_id": str(uuid4())}
        accepted = controller.observe_status(status_after,
            semantic_key=status_after["idempotency_key"], observed_at=port_time(now),
            created_at_utc=domain_time(now))
        assert accepted["output"]["observed_state"] == "succeeded"
        assert accepted["output"]["terminal_result_ref"] == result_ref.as_dict()
        assert controller.observe_status(status_before,
            semantic_key=status_before["idempotency_key"], observed_at=port_time(now),
            created_at_utc=domain_time(now)) == preaccepted
        cancel_after = __import__("app.tests.support.provider_semantic_harness",
            fromlist=["canonical_provider_request"]).canonical_provider_request(
            "cancel", {"operation_ref": operation.as_dict(), "reason_class": "user_requested"},
            identity=query_identity, deadline_at=port_time(now + timedelta(seconds=30)))
        cancel_result = controller.cancel(cancel_after,
            semantic_key=cancel_after["idempotency_key"],
            observed_at=port_time(now), created_at_utc=domain_time(now))[
                "output"]
        assert cancel_result["cancel_state"] == "already_terminal"
        expired_observation = port_time(now + timedelta(seconds=31))
        assert controller.observe_status(status_before,
            semantic_key=status_before["idempotency_key"], observed_at=expired_observation,
            created_at_utc=domain_time(now + timedelta(seconds=31))) == preaccepted
        assert controller.cancel(cancel_after,
            semantic_key=cancel_after["idempotency_key"], observed_at=expired_observation,
            created_at_utc=domain_time(now + timedelta(seconds=31)))["output"] == cancel_result
        dialogue_count = len(threads)
        expected_captures = 5 if actual_catalog else 1
        assert dispatcher.for_visit(run_id=run.run_id, node_id="writer",
            execution_id=execution.execution_id, loop_index=0).dispatch() == result_ref
        assert len(threads) == dialogue_count and len(captures) == expected_captures
        historical_authority = replace(authority,
            current_connection={**authority.current_connection,
                                "revision_digest": "f" * 64},
            qualification_record={**authority.qualification_record,
                                  "status": "revoked"},
            core_boot_id=str(uuid4()))
        historical_transport = ProviderAttemptTransport(domain_store=runtime.domain,
            ledger=runtime.ledger, budget_book=runtime.book,
            context_loader=ProviderSemanticContextLoader(runtime.domain, config_ref=config,
                operation_ref=operation, authority=historical_authority),
            worker_client=worker_client, send_client=send_client)
        historical_request = AttemptDispatchRequest(run.run_id, "writer",
            execution.execution_id, attempt_identity(run.run_id, "writer", 0, 0),
            runtime.refs.envelope,
            runtime.refs.profile, 10_000)
        historical = historical_transport._historical_model_replay(historical_request)
        assert historical.result_ref == result_ref and len(threads) == dialogue_count
        assert len(captures) == expected_captures
        with pytest.raises(Exception, match="attempt_outcome_unknown|next logical retry"):
            dispatcher.for_visit(run_id=run.run_id, node_id="writer",
                execution_id=execution.execution_id, loop_index=1).dispatch()
        assert len(threads) == dialogue_count and len(captures) == expected_captures

        terminal = runtime.domain.get(result_ref).body["content"]
        assert terminal["schema_version"] == "provider-semantic-terminal-v1"
        assert list(Draft202012Validator(
            generate_port_schemas()[("provider-port-v1", "result")],
            format_checker=FormatChecker()).iter_errors(terminal["result"])) == []
        derived_attempt = attempt_identity(run.run_id, "writer", 0, 0)
        assert runtime.ledger.get_attempt(derived_attempt)["usage_finality"] == "provisional"
        import sqlite3
        with sqlite3.connect(runtime.legacy.path) as db:
            row = db.execute("SELECT state,usage_finality,api_microunits FROM runtime_budget_reservations "
                "WHERE request_id=?", (reservation_identity(derived_attempt),)).fetchone()
        assert row == ("unknown", "unknown", 50_000)
        assert runtime.book.status(runtime.session_id)["active_reservations"] == 1
        assert len(captures) == expected_captures
        assert all(capture[2]["x-api-key"] == "dispatcher-secret" for capture in captures)
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert failures == []
