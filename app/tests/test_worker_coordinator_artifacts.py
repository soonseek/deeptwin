"""Coordinator wiring for the bounded artifact stream (T018-foundation byte route).

These tests drive the coordinator over a real socketpair with a real broker
handshake and two live frame codecs, so the streamed artifact frames are the
authenticated, replay-checked frames the contract requires — not scripted fakes.
"""

import hashlib
import socket
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.runtime import worker_coordinator as worker_module
from app.tests.test_worker_coordinator import build_subject, deadline, identifier
from app.workers import broker
from app.workers.artifact_stream import (
    ArtifactDescriptor,
    BytesSink,
    BytesSource,
    OfferedBatchPolicy,
    receive_batch,
    send_batch,
)
from app.workers.artifact_stream_transport import FrameCodecTransport

BATCH_ID = "123e4567-e89b-42d3-a456-426614174000"


@pytest.fixture
def subject(tmp_path):
    return build_subject(tmp_path)


def stream_channel_spec(pair_root) -> broker.ChannelSpec:
    return broker.ChannelSpec(
        channel_id="control-document",
        requester_service="control",
        responder_service="document",
        request_direction="control-to-document",
        protocol_id="document-command-v1",
        requester_uid=10_001,
        requester_gid=10_002,
        responder_uid=10_003,
        responder_gid=10_004,
        pair_gid=10_005,
        pair_root=pair_root,
        socket_name="document.sock",
        root_uid=10_003,
        root_gid=10_005,
        socket_uid=10_003,
        socket_gid=10_005,
        requester_message_types=("artifact_stream", "execute"),
        responder_message_types=("artifact_stream", "completed", "failed"),
        max_queue_depth=1,
    )


def stream_route(subject, pair_root) -> worker_module.WorkerRouteBinding:
    return worker_module.WorkerRouteBinding(
        profile_ref=subject.records.profile.ref,
        channel_spec=stream_channel_spec(pair_root),
        request_message_type="execute",
        response_message_types=("completed", "failed"),
        artifact_stream_message_type="artifact_stream",
    )


def stream_coordinator(subject, pair_root) -> worker_module.WorkerCoordinator:
    return worker_module.WorkerCoordinator(
        domain_store=subject.domain,
        permission_gate=subject.gate,
        runtime_ledger=subject.ledger,
        budget_book=subject.budget,
        route=stream_route(subject, pair_root),
        boot_secret=broker.BootSecret(b"k" * broker.AUTH_SECRET_BYTES),
        requester_boot_id="control-boot-1",
        worker_boot_id="document-boot-1",
    )


def descriptors_for(command_id: str, *payloads: bytes) -> tuple[ArtifactDescriptor, ...]:
    return tuple(
        ArtifactDescriptor(
            batch_id=BATCH_ID,
            request_id=command_id,
            ordinal=index,
            count=len(payloads),
            media_type="application/pdf",
            declared_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        for index, data in enumerate(payloads)
    )


def inputs_for(command_id: str, *payloads: bytes):
    return tuple(
        worker_module.DispatchArtifactInput(descriptor=descriptor, source=BytesSource(data))
        for descriptor, data in zip(
            descriptors_for(command_id, *payloads), payloads, strict=True
        )
    )


def install_real_transport(monkeypatch, worker_behavior):
    """Route the coordinator through a real socketpair with a real worker thread."""

    state: dict[str, socket.socket] = {}
    harness = SimpleNamespace(threads=[], worker_errors=[])

    def connect(spec, *, local_service, deadline):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        state["right"] = right
        return left, None, None

    def handshake(sock, spec, secret, *, requester_boot_id, responder_boot_id, deadline):
        right = state.pop("right")

        def serve():
            codec = None
            try:
                session = broker._server_handshake_impl(
                    right,
                    spec,
                    secret,
                    requester_boot_id=requester_boot_id,
                    responder_boot_id=responder_boot_id,
                    deadline=broker.Deadline.after_ms(5_000),
                    verify_peer=False,
                )
                codec = broker.FrameCodec(
                    spec, session, local_service=spec.responder_service
                )
                worker_behavior(right, codec)
            except BaseException as exc:  # noqa: BLE001
                harness.worker_errors.append(exc)
            finally:
                if codec is not None:
                    codec.close()
                try:
                    right.close()
                except OSError:
                    pass

        thread = threading.Thread(target=serve)
        thread.start()
        harness.threads.append(thread)
        return broker._client_handshake_impl(
            sock,
            spec,
            secret,
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            deadline=deadline,
            verify_peer=False,
        )

    monkeypatch.setattr(worker_module.broker, "connect_verified", connect)
    monkeypatch.setattr(worker_module.broker, "client_handshake", handshake)
    return harness


def join_worker(harness) -> None:
    for thread in harness.threads:
        thread.join(8)
        assert not thread.is_alive(), "worker thread deadlocked"


def test_route_binding_requires_a_duplex_distinct_stream_message_type(subject, tmp_path):
    spec = stream_channel_spec(tmp_path / "pair")
    valid = worker_module.WorkerRouteBinding(
        profile_ref=subject.records.profile.ref,
        channel_spec=spec,
        request_message_type="execute",
        response_message_types=("completed", "failed"),
        artifact_stream_message_type="artifact_stream",
    )
    assert valid.artifact_stream_message_type == "artifact_stream"

    for stream_type in (
        "execute",  # collides with the request type
        "completed",  # collides with a response type
        "missing",  # declared in neither direction
        b"artifact_stream",  # not a string
        "Artifact_Stream",  # not a valid message-type token
    ):
        with pytest.raises(TypeError, match="route binding is invalid"):
            worker_module.WorkerRouteBinding(
                profile_ref=subject.records.profile.ref,
                channel_spec=spec,
                request_message_type="execute",
                response_message_types=("completed", "failed"),
                artifact_stream_message_type=stream_type,
            )

    one_way = broker.ChannelSpec(
        channel_id="control-document",
        requester_service="control",
        responder_service="document",
        request_direction="control-to-document",
        protocol_id="document-command-v1",
        requester_uid=10_001,
        requester_gid=10_002,
        responder_uid=10_003,
        responder_gid=10_004,
        pair_gid=10_005,
        pair_root=tmp_path / "one-way",
        socket_name="document.sock",
        root_uid=10_003,
        root_gid=10_005,
        socket_uid=10_003,
        socket_gid=10_005,
        requester_message_types=("artifact_stream", "execute"),
        responder_message_types=("completed", "failed"),
        max_queue_depth=1,
    )
    with pytest.raises(TypeError, match="route binding is invalid"):
        worker_module.WorkerRouteBinding(
            profile_ref=subject.records.profile.ref,
            channel_spec=one_way,
            request_message_type="execute",
            response_message_types=("completed", "failed"),
            artifact_stream_message_type="artifact_stream",
        )


def test_inputs_on_a_streamless_route_are_rejected_before_consumption(
    subject, monkeypatch
):
    def forbidden_consume(*_args, **_kwargs):
        raise AssertionError("a streamless route must reject inputs before consumption")

    monkeypatch.setattr(
        subject.ledger, "consume_dispatch_permit_window", forbidden_consume
    )
    with pytest.raises(worker_module.WorkerCoordinatorError):
        subject.coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
            artifact_inputs=inputs_for(subject.permit.command_id, b"payload"),
        )
    assert subject.ledger.pending_permit_count == 1


def test_input_identity_must_bind_the_exact_dispatch_command(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")

    def forbidden_consume(*_args, **_kwargs):
        raise AssertionError("a foreign stream identity must not consume the permit")

    monkeypatch.setattr(
        subject.ledger, "consume_dispatch_permit_window", forbidden_consume
    )
    foreign = inputs_for(identifier(), b"payload")
    with pytest.raises(worker_module.WorkerCoordinatorError):
        coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
            artifact_inputs=foreign,
        )
    assert subject.ledger.pending_permit_count == 1

    for bad_inputs in (
        [*inputs_for(subject.permit.command_id, b"payload")],  # not a tuple
        (object(),),  # not a DispatchArtifactInput
        # wrong ordinal sequence for the declared count
        tuple(
            worker_module.DispatchArtifactInput(
                descriptor=descriptors_for(
                    subject.permit.command_id, b"a", b"b"
                )[1],
                source=BytesSource(b"b"),
            )
            for _ in range(1)
        ),
    ):
        with pytest.raises(worker_module.WorkerCoordinatorError):
            coordinator.exchange(
                subject.permit,
                subject.capability,
                deadline=deadline(),
                artifact_inputs=bad_inputs,
            )
    assert subject.ledger.pending_permit_count == 1


def test_declared_inputs_stream_to_the_worker_after_the_request_frame(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")
    first = bytes((i * 7) % 256 for i in range(20_000))
    second = b"second artifact"
    expected = descriptors_for(subject.permit.command_id, first, second)
    seen = SimpleNamespace(request=None, sinks=[BytesSink(), BytesSink()])

    def worker(sock, codec):
        frame = codec.read(sock, deadline=broker.Deadline.after_ms(5_000))
        seen.request = frame
        transport = FrameCodecTransport(
            codec,
            sock,
            message_type="artifact_stream",
            correlation_id=frame.envelope.message_id,
            deadline=broker.Deadline.after_ms(5_000),
        )
        receive_batch(transport, list(expected), list(seen.sinks))
        codec.write(
            sock,
            message_id=str(uuid4()),
            correlation_id=frame.envelope.message_id,
            message_type="completed",
            payload=b"{}",
            deadline=broker.Deadline.after_ms(5_000),
        )

    harness = install_real_transport(monkeypatch, worker)
    response = coordinator.exchange(
        subject.permit,
        subject.capability,
        deadline=deadline(),
        artifact_inputs=inputs_for(subject.permit.command_id, first, second),
    )
    join_worker(harness)

    assert harness.worker_errors == []
    assert type(response) is worker_module.AuthenticatedWorkerResponse
    assert response.message_type == "completed"
    assert response.correlation_id == subject.permit.command_id
    assert seen.request.envelope.message_type == "execute"
    assert seen.request.envelope.message_id == subject.permit.command_id
    assert seen.request.payload == subject.records.envelope.body_bytes
    assert seen.sinks[0].value == first
    assert seen.sinks[1].value == second


def test_streamless_exchange_still_works_on_a_stream_capable_route(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")

    def worker(sock, codec):
        frame = codec.read(sock, deadline=broker.Deadline.after_ms(5_000))
        codec.write(
            sock,
            message_id=str(uuid4()),
            correlation_id=frame.envelope.message_id,
            message_type="completed",
            payload=b"{}",
            deadline=broker.Deadline.after_ms(5_000),
        )

    harness = install_real_transport(monkeypatch, worker)
    response = coordinator.exchange(
        subject.permit, subject.capability, deadline=deadline()
    )
    join_worker(harness)

    assert harness.worker_errors == []
    assert response.message_type == "completed"


def test_stream_failure_after_the_request_frame_is_outcome_unknown(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")

    def worker(sock, codec):
        codec.read(sock, deadline=broker.Deadline.after_ms(5_000))
        # Abandon the exchange after the request frame: never grant credit.
        sock.close()

    harness = install_real_transport(monkeypatch, worker)
    with pytest.raises(broker.BrokerError) as failure:
        coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
            artifact_inputs=inputs_for(subject.permit.command_id, b"payload"),
        )
    join_worker(harness)

    assert failure.value.dispatch_effect == "outcome_unknown"
    assert subject.ledger.pending_permit_count == 0


def test_source_digest_mismatch_cancels_the_stream_and_fails_closed(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")
    declared = b"declared bytes"
    lying = inputs_for(subject.permit.command_id, declared)
    lying = (
        worker_module.DispatchArtifactInput(
            descriptor=lying[0].descriptor,
            source=BytesSource(b"different bytes"),
        ),
    )
    expected = descriptors_for(subject.permit.command_id, declared)
    worker_result: dict[str, BaseException] = {}

    def worker(sock, codec):
        frame = codec.read(sock, deadline=broker.Deadline.after_ms(5_000))
        transport = FrameCodecTransport(
            codec,
            sock,
            message_type="artifact_stream",
            correlation_id=frame.envelope.message_id,
            deadline=broker.Deadline.after_ms(5_000),
        )
        try:
            receive_batch(transport, list(expected), [BytesSink()])
        except BaseException as exc:  # noqa: BLE001
            worker_result["receive"] = exc

    harness = install_real_transport(monkeypatch, worker)
    with pytest.raises(broker.BrokerError) as failure:
        coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
            artifact_inputs=lying,
        )
    join_worker(harness)

    assert harness.worker_errors == []
    assert failure.value.dispatch_effect == "outcome_unknown"
    assert "receive" in worker_result


def output_policy(command_id, **overrides):
    fields = {
        "request_id": command_id,
        "allowed_media_types": ("application/pdf", "text/plain"),
        "max_artifacts": 4,
    }
    fields.update(overrides)
    return OfferedBatchPolicy(**fields)


def output_batch(command_id, *payloads, media_type="application/pdf"):
    return [
        ArtifactDescriptor(
            batch_id=str(uuid4()),
            request_id=command_id,
            ordinal=index,
            count=len(payloads),
            media_type=media_type,
            declared_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        for index, data in enumerate(payloads)
    ]


def test_output_policy_must_bind_the_exact_dispatch_command(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")

    def forbidden_consume(*_args, **_kwargs):
        raise AssertionError("an invalid output policy must not consume the permit")

    monkeypatch.setattr(
        subject.ledger, "consume_dispatch_permit_window", forbidden_consume
    )
    for bad_policy in (
        output_policy(identifier()),  # foreign request id
        object(),  # not a policy
    ):
        with pytest.raises(worker_module.WorkerCoordinatorError):
            coordinator.exchange(
                subject.permit,
                subject.capability,
                deadline=deadline(),
                artifact_output_policy=bad_policy,
            )
    with pytest.raises(worker_module.WorkerCoordinatorError):
        subject.coordinator.exchange(  # streamless route cannot accept outputs
            subject.permit,
            subject.capability,
            deadline=deadline(),
            artifact_output_policy=output_policy(subject.permit.command_id),
        )
    assert subject.ledger.pending_permit_count == 1


def test_worker_outputs_return_through_the_digest_first_protocol(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")
    report = bytes((i * 31) % 256 for i in range(30_000))
    summary = b"a short text summary"

    def worker(sock, codec):
        frame = codec.read(sock, deadline=broker.Deadline.after_ms(5_000))
        command_id = frame.envelope.message_id
        transport = FrameCodecTransport(
            codec,
            sock,
            message_type="artifact_stream",
            correlation_id=command_id,
            deadline=broker.Deadline.after_ms(5_000),
        )
        descriptors = output_batch(command_id, report, summary)
        descriptors[1] = ArtifactDescriptor(
            batch_id=descriptors[0].batch_id,
            request_id=command_id,
            ordinal=1,
            count=2,
            media_type="text/plain",
            declared_size=len(summary),
            sha256=hashlib.sha256(summary).hexdigest(),
        )
        descriptors[0] = ArtifactDescriptor(
            batch_id=descriptors[0].batch_id,
            request_id=command_id,
            ordinal=0,
            count=2,
            media_type="application/pdf",
            declared_size=len(report),
            sha256=hashlib.sha256(report).hexdigest(),
        )
        send_batch(
            transport,
            descriptors,
            [BytesSource(report), BytesSource(summary)],
        )
        codec.write(
            sock,
            message_id=str(uuid4()),
            correlation_id=command_id,
            message_type="completed",
            payload=b"{}",
            deadline=broker.Deadline.after_ms(5_000),
        )

    harness = install_real_transport(monkeypatch, worker)
    response = coordinator.exchange(
        subject.permit,
        subject.capability,
        deadline=deadline(),
        artifact_output_policy=output_policy(subject.permit.command_id),
    )
    join_worker(harness)

    assert harness.worker_errors == []
    assert response.message_type == "completed"
    assert len(response.artifacts) == 2
    assert response.artifacts[0].descriptor.media_type == "application/pdf"
    assert response.artifacts[0].payload == report
    assert response.artifacts[1].descriptor.media_type == "text/plain"
    assert response.artifacts[1].payload == summary


def test_inputs_and_outputs_share_one_authenticated_session(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")
    inbound = b"input bytes for the worker"
    expected_inputs = descriptors_for(subject.permit.command_id, inbound)

    def worker(sock, codec):
        frame = codec.read(sock, deadline=broker.Deadline.after_ms(5_000))
        command_id = frame.envelope.message_id
        transport = FrameCodecTransport(
            codec,
            sock,
            message_type="artifact_stream",
            correlation_id=command_id,
            deadline=broker.Deadline.after_ms(5_000),
        )
        sink = BytesSink()
        receive_batch(transport, list(expected_inputs), [sink])
        echoed = sink.value + b" processed"
        send_batch(
            transport,
            output_batch(command_id, echoed, media_type="text/plain"),
            [BytesSource(echoed)],
        )
        codec.write(
            sock,
            message_id=str(uuid4()),
            correlation_id=command_id,
            message_type="completed",
            payload=b"{}",
            deadline=broker.Deadline.after_ms(5_000),
        )

    harness = install_real_transport(monkeypatch, worker)
    response = coordinator.exchange(
        subject.permit,
        subject.capability,
        deadline=deadline(),
        artifact_inputs=inputs_for(subject.permit.command_id, inbound),
        artifact_output_policy=output_policy(subject.permit.command_id),
    )
    join_worker(harness)

    assert harness.worker_errors == []
    assert response.message_type == "completed"
    assert len(response.artifacts) == 1
    assert response.artifacts[0].payload == inbound + b" processed"


def test_an_undeclared_worker_stream_is_a_protocol_violation(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")
    worker_result: dict[str, BaseException] = {}

    def worker(sock, codec):
        frame = codec.read(sock, deadline=broker.Deadline.after_ms(5_000))
        command_id = frame.envelope.message_id
        transport = FrameCodecTransport(
            codec,
            sock,
            message_type="artifact_stream",
            correlation_id=command_id,
            deadline=broker.Deadline.after_ms(5_000),
        )
        data = b"unrequested bytes"
        try:
            send_batch(
                transport,
                output_batch(command_id, data, media_type="text/plain"),
                [BytesSource(data)],
            )
        except BaseException as exc:  # noqa: BLE001 - coordinator kills the channel
            worker_result["send"] = exc

    harness = install_real_transport(monkeypatch, worker)
    with pytest.raises(broker.ProtocolViolation) as failure:
        coordinator.exchange(
            subject.permit, subject.capability, deadline=deadline()
        )
    join_worker(harness)
    assert failure.value.dispatch_effect == "outcome_unknown"


def test_an_output_policy_violation_cancels_and_fails_closed(
    subject, tmp_path, monkeypatch
):
    coordinator = stream_coordinator(subject, tmp_path / "pair")
    worker_result: dict[str, BaseException] = {}

    def worker(sock, codec):
        frame = codec.read(sock, deadline=broker.Deadline.after_ms(5_000))
        command_id = frame.envelope.message_id
        transport = FrameCodecTransport(
            codec,
            sock,
            message_type="artifact_stream",
            correlation_id=command_id,
            deadline=broker.Deadline.after_ms(5_000),
        )
        data = b"forbidden media"
        try:
            send_batch(
                transport,
                output_batch(command_id, data, media_type="application/x-msdownload"),
                [BytesSource(data)],
            )
        except BaseException as exc:  # noqa: BLE001
            worker_result["send"] = exc

    harness = install_real_transport(monkeypatch, worker)
    with pytest.raises(broker.BrokerError) as failure:
        coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
            artifact_output_policy=output_policy(subject.permit.command_id),
        )
    join_worker(harness)

    assert failure.value.dispatch_effect == "outcome_unknown"
    assert "send" in worker_result


def test_received_worker_artifact_recomputes_its_own_digest():
    data = b"exact artifact bytes"
    good = ArtifactDescriptor(
        batch_id=BATCH_ID,
        request_id="123e4567-e89b-42d3-a456-426614174111",
        ordinal=0,
        count=1,
        media_type="text/plain",
        declared_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    artifact = worker_module.ReceivedWorkerArtifact(descriptor=good, payload=data)
    assert artifact.payload == data
    with pytest.raises(TypeError):
        worker_module.ReceivedWorkerArtifact(descriptor=good, payload=b"tampered")
    with pytest.raises(TypeError):
        worker_module.ReceivedWorkerArtifact(descriptor=good, payload=data + b"x")
