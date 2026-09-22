"""Real authenticated framed dialogues over test-owned sockets and image files."""

import contextlib
import json
import pytest
from app.tests.test_extension_listener import channel, seams, INSTANCE
from app.tests._provider_worker_fixture import (
    provider_tree,
    Requester,
    serving,
    text_events,
    page,
    model_record,
    MODEL,
)
from app.tests._provider_worker_fixture import blob, encoded
from uuid import uuid4
import threading


@pytest.fixture
def slot(channel, provider_tree, monkeypatch):
    from app.workers import provider_service as ps

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(ps, "extension_channel", lambda **kw: (root, spec))
    return root, spec, side, provider_tree


def opened():
    from app.workers.provider_service import open_provider_worker_service

    return open_provider_worker_service(instance_id=INSTANCE, slot_number=4)


def join(thread, box):
    thread.join(5)
    assert not thread.is_alive()
    assert box == {"served": 1}


def test_service_entrypoint_is_owned():
    from app.workers.provider_service import ProviderWorkerService
    import pytest

    with pytest.raises(TypeError):
        ProviderWorkerService()


def test_identify_is_actual_metadata_and_one_connection(slot):
    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            request = client.write(
                {"schema": "provider-worker-identify-v1", "challenge": "a" * 64}
            )
            _, reply = client.read(request)
            assert reply["challenge"] == "a" * 64
            assert reply["service_identity"] == spec.responder_service
            assert reply["implemented_transforms"] == ["catalog", "text"]
            assert reply["uid"] == 22001
            join(thread, box)
        finally:
            client.close()


def test_real_text_dialogue_body_response_result_and_checkpoints(slot, monkeypatch):
    from app.workers import provider_metadata as pm

    root, spec, side, _ = slot
    reads = []
    original = pm.ProviderMetadataSource.read_current

    def read(source, *, deadline):
        reads.append(deadline.end_monotonic)
        return original(source, deadline=deadline)

    monkeypatch.setattr(pm.ProviderMetadataSource, "read_current", read)
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start(raw="내 업무 자료".encode())
            proposal, raw = client.projection()
            assert proposal["endpoint"] == "messages" and proposal["step"] == 1
            assert json.loads(raw) == {
                "model": MODEL,
                "max_tokens": 32,
                "stream": True,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "내 업무 자료"}],
                    }
                ],
            }
            client.response(b"".join(text_events()))
            result = client.final()
            assert result["state"] == "parsed_complete"
            assert result["observation"]["text_blocks"] == ["answer"]
            assert result["observation"]["usage_complete"] is None
            join(thread, box)
            assert len(reads) == 2 and reads[0] == reads[1]
        finally:
            client.close()


def test_real_two_page_catalog_and_null_input_batch(slot):
    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start("catalog")
            first, raw = client.projection()
            assert first["after_id"] is None and raw is None
            client.response(page([model_record("one")], True))
            second, raw = client.projection()
            assert second["after_id"] == "one" and second["step"] == 2 and raw is None
            client.response(page([model_record("two")]), step=2)
            result = client.final()
            assert result["observation"]["complete"] is True
            assert [m["id"] for m in result["observation"]["models"]] == ["one", "two"]
            join(thread, box)
        finally:
            client.close()


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("unavailable", "upstream_unavailable"),
        ("truncated", "truncated"),
        ("supplied", "protocol_error"),
    ],
)
def test_unsuccessful_final_also_remeasures(slot, monkeypatch, status, reason):
    from app.workers import provider_metadata as pm

    root, spec, side, _ = slot
    reads = []
    original = pm.ProviderMetadataSource.read_current

    def read(source, *, deadline):
        reads.append(deadline)
        return original(source, deadline=deadline)

    monkeypatch.setattr(pm.ProviderMetadataSource, "read_current", read)
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            client.projection()
            client.response(b"bad SSE" if status == "supplied" else None, status=status)
            result = client.final()
            assert result["reason"] == reason
            join(thread, box)
            assert len(reads) == 2 and reads[0] is reads[1]
        finally:
            client.close()


def test_oversized_sse_integer_returns_final_with_prior_usage_and_fresh_metadata(
    slot, monkeypatch
):
    from app.workers import provider_metadata as pm

    root, spec, side, _ = slot
    reads = []
    original = pm.ProviderMetadataSource.read_current

    def read(source, *, deadline):
        reading = original(source, deadline=deadline)
        reads.append(deadline)
        return reading

    monkeypatch.setattr(pm.ProviderMetadataSource, "read_current", read)
    raw = (
        b"".join(text_events()[:1])
        + b'event: message_delta\ndata: {"type":"message_delta",'
        b'"delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":'
        + b"1" * 5000
        + b"}}\n\n"
    )
    assert len(raw) == 5298  # bounded response, not a stream-integrity overflow
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            client.projection()
            client.response(raw)
            result = client.final()
            assert (result["state"], result["reason"]) == (
                "invalid_response",
                "protocol_error",
            )
            assert result["observation"]["text_blocks"] == []
            assert result["observation"]["usage_observed"] == {
                "input_tokens": 3,
                "output_tokens": 0,
                "cache_read_input_tokens": None,
                "cache_creation_input_tokens": None,
            }
            assert result["observation"]["usage_complete"] is None
            join(thread, box)
            assert len(reads) == 2 and reads[0] is reads[1]
            assert not service.closed
        finally:
            client.close()


def test_private_text_parser_does_not_turn_deadline_failure_into_protocol_result():
    from app.workers import broker
    from app.workers.provider_service import ProviderWorkerService

    with pytest.raises(broker.DeadlineExceeded):
        ProviderWorkerService._parse_text(
            MODEL, b"".join(text_events()), broker.Deadline(0.0001)
        )


@pytest.mark.parametrize("status", ["supplied", "unavailable", "truncated"])
def test_image_drift_between_phases_closes_service_without_final(slot, status):
    from app.workers import provider_service as ps, broker

    root, spec, side, tree = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            client.projection()
            tree["worker"].chmod(0o755)
            client.response(
                b"".join(text_events()) if status == "supplied" else None, status=status
            )
            thread.join(5)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert service.closed
            with pytest.raises(broker.TransportClosed):
                client.read(client.start_id)
        finally:
            client.close()


@pytest.mark.parametrize(
    "case",
    [
        "step",
        "dialogue",
        "correlation",
        "replay_control",
        "replay_batch",
        "wrong_media",
        "extra",
        "nil_id",
    ],
)
def test_bad_response_control_closes_only_connection(slot, case):
    from app.workers import provider_service as ps

    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            proposal, _ = client.projection()
            value = {
                "schema": "provider-transform-response-v1",
                "dialogue_id": client.dialogue,
                "step": 1,
                "status": "supplied",
                "body": blob(b"upstream", "text/event-stream"),
            }
            correlation = client.start_id
            mid = None
            if case == "step":
                value["step"] = 2
            if case == "dialogue":
                value["dialogue_id"] = str(uuid4())
            if case == "correlation":
                correlation = str(uuid4())
            if case == "replay_control":
                mid = client.start_id
            if case == "replay_batch":
                value["body"]["batch_id"] = proposal["body"]["batch_id"]
            if case == "wrong_media":
                value["body"]["media_type"] = "application/json"
            if case == "extra":
                value["key"] = "forbidden"
            if case == "nil_id":
                mid = "00000000-0000-0000-0000-000000000000"
            client.write(value, correlation, message_id=mid)
            thread.join(5)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert not service.closed
        finally:
            client.close()


def test_payload_accounting_counts_both_directions_and_every_stream_frame_once(
    slot, monkeypatch
):
    from app.workers import provider_service as ps, listener

    root, spec, side, _ = slot
    captured = []
    original_init = ps._BudgetConnection.__init__

    def init(value, connection):
        original_init(value, connection)
        captured.append(value)

    monkeypatch.setattr(ps._BudgetConnection, "__init__", init)
    original_read, original_write = (
        listener.ExtensionConnection.read,
        listener.ExtensionConnection.write,
    )
    measured = {"in": 0, "out": 0}
    deadlines = []

    def read(connection, **kwargs):
        result = original_read(connection, **kwargs)
        if threading.get_ident() == side.get("worker_ident"):
            measured["in"] += len(result.payload)
            deadlines.append(kwargs["deadline"])
        return result

    def write(connection, **kwargs):
        if threading.get_ident() == side.get("worker_ident"):
            measured["out"] += len(kwargs["payload"])
            deadlines.append(kwargs["deadline"])
        return original_write(connection, **kwargs)

    monkeypatch.setattr(listener.ExtensionConnection, "read", read)
    monkeypatch.setattr(listener.ExtensionConnection, "write", write)
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start(raw=b"x" * 70000)
            client.projection()
            client.response(b"".join(text_events()))
            assert client.final()["state"] == "parsed_complete"
            join(thread, box)
            assert captured[0].total == measured["in"] + measured["out"]
            assert measured["in"] > 70000 and measured["out"] > 70000
            assert all(d is deadlines[1] for d in deadlines[1:])
        finally:
            client.close()


def test_whole_dialogue_budget_exhaustion_closes_without_false_final(slot, monkeypatch):
    from app.workers import broker, provider_messages as wire, provider_service as ps

    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            client.projection()
            # Lower the ceiling only as a test seam; the next payload must still
            # include earlier traffic, rather than reset at the response phase.
            monkeypatch.setattr(wire, "MAX_DIALOGUE", 1)
            # the server may charge the projection acknowledgement under the lowered
            # ceiling and close before this response leaves: the client's write then
            # fails uncertainly — the fact under test is the server's own closure
            with contextlib.suppress(broker.TransportUncertain, broker.TransportClosed):
                client.response(status="unavailable")
            thread.join(5)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert not service.closed
        finally:
            client.close()


@pytest.mark.parametrize("kind", ["bad_credit", "cancel"])
def test_projection_stream_credit_and_local_cancel_are_terminal(slot, kind):
    from app.workers import provider_service as ps

    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            pid, projection = client.read(client.start_id)
            client.connection.read(deadline=client.deadline)  # actual artifact offer
            value = (
                {
                    "type": "artifact-cancel",
                    "batch_id": projection["body"]["batch_id"],
                    "reason": "fixture",
                }
                if kind == "cancel"
                else {
                    "type": "artifact-credit",
                    "batch_id": projection["body"]["batch_id"],
                    "ordinal": 0,
                    "consumed_through": 1,
                    "credit_through": 1,
                }
            )
            client.connection.write(
                message_id=str(uuid4()),
                correlation_id=pid,
                message_type="extension-artifact-v1",
                payload=encoded(value),
                deadline=client.deadline,
            )
            thread.join(5)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert not service.closed
        finally:
            client.close()


def test_bad_response_hash_and_eof_cleanup(slot):
    from app.workers import provider_service as ps
    from app.workers.artifact_stream import ArtifactStreamError

    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            client.projection()
            desc = blob(b"expected", "text/event-stream")
            mid = client.write(
                {
                    "schema": "provider-transform-response-v1",
                    "dialogue_id": client.dialogue,
                    "step": 1,
                    "status": "supplied",
                    "body": desc,
                },
                client.start_id,
            )
            with pytest.raises(ArtifactStreamError):
                client.stream(mid, [desc], [b"changed!"])
            thread.join(5)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert not service.closed
        finally:
            client.close()
        thread, box = serving(service, side)
        client = Requester(root, spec)
        client.close()
        thread.join(5)
        assert not thread.is_alive() and isinstance(
            box.get("error"), ps.ProviderServiceError
        )
        assert not service.closed


def test_final_stream_ack_is_required_before_service_returns(slot):
    from app.workers.artifact_stream_transport import ConnectionStreamTransport
    from app.workers.artifact_stream import ArtifactDescriptor, BytesSink, receive_batch

    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            client.projection()
            client.response(b"".join(text_events()))
            final_id, final = client.read(client.start_id)
            desc = final["result"]
            transport = ConnectionStreamTransport(
                client.connection,
                message_type="extension-artifact-v1",
                correlation_id=final_id,
                deadline=client.deadline,
            )
            held = []

            class HoldAck:
                def receive(self):
                    return transport.receive()

                def send(self, payload):
                    if json.loads(payload)["type"] == "artifact-accepted":
                        held.append(payload)
                    else:
                        transport.send(payload)

            sink = BytesSink()
            receive_batch(
                HoldAck(),
                [
                    ArtifactDescriptor(
                        batch_id=desc["batch_id"],
                        request_id=final_id,
                        ordinal=0,
                        count=1,
                        media_type=desc["media_type"],
                        declared_size=desc["size"],
                        sha256=desc["sha256"],
                    )
                ],
                [sink],
            )
            assert held and thread.is_alive() and box == {}
            transport.send(held[0])
            join(thread, box)
        finally:
            client.close()


def test_missing_provider_files_prevent_listener_publication(slot):
    from app.workers import provider_service as ps

    root, _, _, tree = slot
    tree["identity"].unlink()
    with pytest.raises(ps.ProviderServiceError):
        opened()
    assert not (root.endpoint_path / "listener.json").exists()


def test_generation_or_listener_drift_closes_service(slot):
    from app.workers import provider_service as ps, broker

    root, _, side, _ = slot
    service = opened()
    try:
        (root.endpoint_path / "listener.json").unlink()
        side["worker_ident"] = threading.get_ident()
        with pytest.raises(ps.ProviderServiceError):
            service.serve_one(broker.Deadline.after_ms(1000))
        assert service.closed
    finally:
        service.close()


def test_metadata_deadline_closes_only_connection(slot, monkeypatch):
    from app.workers import provider_service as ps, provider_metadata as pm, broker

    root, spec, side, _ = slot
    original = pm.ProviderMetadataSource.read_current
    calls = [0]

    def expired(source, *, deadline):
        calls[0] += 1
        return original(
            source, deadline=broker.Deadline(0.0001) if calls[0] == 2 else deadline
        )

    monkeypatch.setattr(pm.ProviderMetadataSource, "read_current", expired)
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            client.projection()
            client.response(status="unavailable")
            thread.join(5)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert not service.closed and not service._source.closed
        finally:
            client.close()


@pytest.mark.parametrize("cleanup_failure", [False, True])
@pytest.mark.parametrize("interruption", ["keyboard", "stop"])
def test_base_exception_preserves_exception_and_releases_owned_resources(
    slot, monkeypatch, cleanup_failure, interruption
):
    from app.workers import provider_service as ps, provider_worker as pw, listener
    from app.tests.test_extension_listener import open_fds

    root, spec, side, _ = slot
    before = open_fds()
    service = opened()
    primary = KeyboardInterrupt() if interruption == "keyboard" else pw._StopRequested()
    real_close = listener.ExtensionConnection.close
    closed_connections = []

    def close(connection):
        real_close(connection)
        if threading.get_ident() == side.get("worker_ident"):
            closed_connections.append(connection)
            if cleanup_failure:
                raise OSError("synthetic connection cleanup failure")

    monkeypatch.setattr(listener.ExtensionConnection, "close", close)

    def interrupted(*args):
        raise primary

    monkeypatch.setattr(
        ps.ProviderWorkerService, "_parse_text", staticmethod(interrupted)
    )
    thread, box = serving(service, side)
    client = Requester(root, spec)
    try:
        client.start()
        client.projection()
        client.response(b"".join(text_events()))
        thread.join(5)
        assert not thread.is_alive() and box.get("error") is primary
        assert service.closed
        assert len(closed_connections) == 1 and closed_connections[0].closed
    finally:
        client.close()
        service.close()
    assert open_fds() == before


def test_connection_close_failure_without_primary_keeps_normal_error_handling(
    slot, monkeypatch
):
    from app.workers import provider_service as ps, listener
    from app.tests.test_extension_listener import open_fds

    root, spec, side, _ = slot
    before = open_fds()
    real_close = listener.ExtensionConnection.close
    closed_connections = []

    def close(connection):
        real_close(connection)
        if threading.get_ident() == side.get("worker_ident"):
            closed_connections.append(connection)
            raise OSError("synthetic connection cleanup failure")

    monkeypatch.setattr(listener.ExtensionConnection, "close", close)
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            request = client.write(
                {"schema": "provider-worker-identify-v1", "challenge": "a" * 64}
            )
            assert client.read(request)[1]["schema"] == "provider-worker-identity-v1"
            thread.join(5)
            assert not thread.is_alive()
            assert type(box.get("error")) is ps.ProviderServiceError
            assert not service.closed
            assert len(closed_connections) == 1 and closed_connections[0].closed
        finally:
            client.close()
    assert open_fds() == before


def test_changed_generation_during_dialogue_closes_owned_service(slot):
    from app.workers import provider_service as ps

    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start()
            client.projection()
            root.boot_secret_path.chmod(
                0o600
            )  # synthetic pair metadata, not a user credential
            client.response(status="unavailable")
            thread.join(5)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert service.closed
        finally:
            client.close()


def test_remaining_time_timeout_closes_only_connection(slot):
    from app.workers import provider_service as ps

    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.write(
                {
                    "schema": "provider-transform-start-v1",
                    "dialogue_id": str(uuid4()),
                    "operation": "catalog",
                    "remaining_ms": 1,
                    "plan": blob(
                        encoded({"profile": "claude-text-transform-v1", "limit": 1000})
                    ),
                }
            )
            # Deliberately provide no plan bytes; the worker must use the 1ms
            # original dialogue deadline, not restart a fresh 30s stream timer.
            thread.join(2)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert not service.closed
        finally:
            client.close()


def test_escaped_request_overflow_returns_no_projection(slot):
    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.start(raw=b"\x00" * 180000)
            result = client.final()  # next control frame must be final, not a proposal
            assert (result["state"], result["reason"]) == (
                "unsupported_profile",
                "unsupported",
            )
            assert result["observation"]["observed_model"] is None
            join(thread, box)
        finally:
            client.close()


@pytest.mark.parametrize("schema", ["extension-stage-probe-v1", "extension-execute-v1"])
def test_tool_modes_are_not_reinterpreted(slot, schema):
    from app.workers import provider_service as ps

    root, spec, side, _ = slot
    with opened() as service:
        thread, box = serving(service, side)
        client = Requester(root, spec)
        try:
            client.write({"schema": schema})
            thread.join(5)
            assert not thread.is_alive() and isinstance(
                box.get("error"), ps.ProviderServiceError
            )
            assert not service.closed
        finally:
            client.close()
