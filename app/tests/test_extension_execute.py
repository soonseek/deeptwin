"""T087/T018 slice: the worker's first real operation. The private router's
semantic registry is no longer empty: `status` is a code-owned operation
that answers from an actual metadata reading (the same reading the probe
reports), so the probe's `registered_operations` now says `["status"]`.

The mode of an accepted connection is selected by its first authenticated
application frame's exact request schema (probe contract §3): an execute
request is answered exactly once and the worker closes; a probe connection
still answers at most two probes. An unregistered operation is a typed
refusal (`failed` / `validation_failed`, final zero usage), never a
placeholder result. Same macOS seams as the probe tests: service and
operation logic, never positive Linux authentication or a real image.
"""

import os
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef, canonical_json
from app.tests.test_extension_probe import (  # noqa: F401 - fixture re-exports
    channel,
    connect,
    deadline,
    open_service,
    probe,
    serve_in_thread,
    slot,
    worker_tree,
)
from app.workers import broker, listener
from app.workers import extension_execute_messages as xm
from app.workers import extension_probe as ep
from app.workers.extension_probe_messages import parse_probe_reply


def ref(kind):
    return EntityRef(kind, str(uuid4()), 1, "c" * 64)


def execute(client, *, operation="status", payload=None, message_id=None, **declared_inputs):
    fields = {
        "attempt_id": str(uuid4()),
        "execution_id": str(uuid4()),
        "operation": operation,
        "envelope_ref": ref("execution_envelope"),
        "profile_ref": ref("runtime_profile"),
        "remaining_ms": 1_500,
        "challenge": os.urandom(32),
        **declared_inputs,
    }
    message_id = str(uuid4()) if message_id is None else message_id
    client.write(
        message_id=message_id,
        correlation_id=None,
        message_type="extension-request-v1",
        payload=xm.encode_execute_request(**fields) if payload is None else payload,
        deadline=deadline(),
    )
    return message_id, fields


def served(service, side):
    box = {}
    thread = serve_in_thread(service, box, side)
    return box, thread


def closed_after(client):
    with pytest.raises((broker.BrokerError, listener.ListenerError, OSError)):
        execute(client)
        client.read(deadline=deadline())


def test_execute_status_answers_once_from_an_actual_reading_and_closes(slot):  # noqa: F811 - the imported fixture
    root, spec, side, tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            message_id, fields = execute(client)
            frame = client.read(deadline=deadline())
            assert frame.envelope.message_type == "extension-result-v1"
            assert frame.envelope.correlation_id == message_id
            reply = xm.parse_execute_reply(frame.payload)
            assert reply.attempt_id == fields["attempt_id"]
            assert reply.operation == "status" and reply.challenge == fields["challenge"]
            assert reply.outcome == "succeeded" and reply.usage_finality == "final"
            assert reply.remote_terminal_observed == "succeeded"
            assert reply.reason_code == "provider_terminal"
            assert reply.output["service_identity"] == spec.responder_service
            assert reply.output["component"]["build_identity_digest"] == tree["identity_digest"]
            assert reply.output["component"]["port_contract_version"] == "tool-port-v1"
            assert reply.output["runtime"]["registered_operations"] == ["describe_tools", "status"]
            assert reply.output["runtime"]["platform"] == "linux/amd64"
            assert reply.usage == {
                "model_calls": 0, "tool_calls": 0, "node_visits": 1, "loop_rounds": 0,
                "output_bytes": len(canonical_json(reply.output)), "candidates": 0,
                "api_microunits": None,
            }
            # exactly one execute per connection: the worker closed after the reply
            closed_after(client)
        finally:
            client.close()
        thread.join(5)
        assert box.get("served") == 1, box
    finally:
        service.close()


def test_execute_describe_tools_answers_the_workers_actual_tool_table(slot):  # noqa: F811 - the imported fixture
    # T087 second operation: the worker describes the tools it actually offers — the
    # code-owned tool table, empty today — never a copy of the port catalogue
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            message_id, fields = execute(client, operation="describe_tools")
            frame = client.read(deadline=deadline())
            assert frame.envelope.correlation_id == message_id
            reply = xm.parse_execute_reply(frame.payload)
            assert reply.attempt_id == fields["attempt_id"]
            assert reply.operation == "describe_tools" and reply.challenge == fields["challenge"]
            assert reply.outcome == "succeeded" and reply.usage_finality == "final"
            assert reply.remote_terminal_observed == "succeeded"
            assert reply.reason_code == "provider_terminal"
            assert reply.output == {"tools": []}
            assert reply.usage == {
                "model_calls": 0, "tool_calls": 0, "node_visits": 1, "loop_rounds": 0,
                "output_bytes": len(canonical_json(reply.output)), "candidates": 0,
                "api_microunits": None,
            }
            closed_after(client)
        finally:
            client.close()
        thread.join(5)
        assert box.get("served") == 1, box
    finally:
        service.close()
    # the tool table is code-owned and immutable, like the operation table
    assert ep._TOOLS == ()
    with pytest.raises(AttributeError):
        ep._TOOLS.append  # noqa: B018


def stream_inputs(client, message_id, fields, payloads):
    from app.workers.artifact_stream import BytesSource, send_batch
    from app.workers.artifact_stream_transport import ConnectionStreamTransport

    request = xm.parse_execute_request(xm.encode_execute_request(**fields))
    transport = ConnectionStreamTransport(client, message_type="extension-artifact-v1",
                                          correlation_id=message_id, deadline=deadline())
    send_batch(transport, request.artifact_descriptors(message_id), [BytesSource(raw) for raw in payloads],
               limits=ep.EXECUTE_STREAM_LIMITS)


def declared(payloads, roles):
    import hashlib

    return {
        "artifact_batch_id": str(uuid4()),
        "artifact_inputs": [
            {"ordinal": index, "media_type": "text/plain", "declared_size": len(raw),
             "sha256": hashlib.sha256(raw).hexdigest(), "role": role}
            for index, (raw, role) in enumerate(zip(payloads, roles, strict=True))
        ],
    }


def test_declared_inputs_for_a_query_operation_are_refused_before_any_byte_is_read(slot):  # noqa: F811
    # T018/T087 artifact leg: `status` and `describe_tools` take no request artifacts
    # (port contract profile E); a request declaring inputs for them is the typed refusal
    # and the worker reads no artifact frame — the client never has to send one
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            message_id, _fields = execute(client, operation="status", **declared([b"hello"], ["source"]))
            frame = client.read(deadline=deadline())
            assert frame.envelope.correlation_id == message_id
            reply = xm.parse_execute_reply(frame.payload)
            assert reply.outcome == "failed" and reply.reason_code == "validation_failed"
            assert reply.output is None and reply.usage["output_bytes"] == 0
        finally:
            client.close()
        thread.join(5)
        assert box.get("served") == 1, box
    finally:
        service.close()


def test_declared_inputs_reach_the_operation_over_the_bounded_stream(slot, monkeypatch):  # noqa: F811
    # the byte route: after the request frame the requester streams the declared batch on
    # the channel's artifact type; the worker admits it into bounded owned sinks, verifies
    # every digest, and only then runs the operation with the received inputs. No
    # registered operation takes inputs today (profile E), so the receiving path is
    # exercised through a test-only handler under `invoke_tool` (profile T-tool)
    seen = {}

    def recording(self, service, request, deadline, inputs):
        seen["inputs"] = [(item.role, item.sha256, raw) for item, raw in inputs]
        seen["operation"] = request.operation
        return {
            "outcome": "failed", "usage_finality": "final",
            "remote_terminal_observed": "failed", "reason_code": "provider_terminal",
            "usage": dict(ep._ZERO_USAGE), "output": None,
        }

    monkeypatch.setattr(ep._Router, "execute", recording)
    # the test seam: `invoke_tool` is unregistered today, so the router would refuse the
    # inputs before reading a byte; admit them to exercise the byte route itself
    monkeypatch.setattr(ep._Router, "admits_inputs", lambda self, request: True)
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            payloads = [b"hello", b"x" * 40_000, b""]
            message_id, fields = execute(client, operation="invoke_tool",
                                         **declared(payloads, ["document_source", "attachment", "empty"]))
            stream_inputs(client, message_id, fields, payloads)
            frame = client.read(deadline=deadline())
            assert frame.envelope.correlation_id == message_id
            reply = xm.parse_execute_reply(frame.payload)
            assert reply.outcome == "failed" and reply.reason_code == "provider_terminal"
            assert seen["operation"] == "invoke_tool"
            assert [role for role, _, _ in seen["inputs"]] == ["document_source", "attachment", "empty"]
            assert [raw for _, _, raw in seen["inputs"]] == payloads
            assert [digest for _, digest, _ in seen["inputs"]] == [
                item["sha256"] for item in fields["artifact_inputs"]]
            closed_after(client)
        finally:
            client.close()
        thread.join(5)
        assert box.get("served") == 1, box
    finally:
        service.close()


def test_a_stream_violation_closes_the_connection_before_the_operation_runs(slot, monkeypatch):  # noqa: F811
    from app.workers.artifact_stream import ArtifactStreamError

    called = []
    monkeypatch.setattr(ep._Router, "execute", lambda *args, **kwargs: called.append(args) or {
        "outcome": "failed", "usage_finality": "final", "remote_terminal_observed": "failed",
        "reason_code": "provider_terminal", "usage": dict(ep._ZERO_USAGE), "output": None})
    monkeypatch.setattr(ep._Router, "admits_inputs", lambda self, request: True)
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            # the bytes sent do not match the declared digest: terminal, no reply, no operation
            fields = declared([b"hello"], ["document_source"])
            message_id, fields = execute(client, operation="invoke_tool", **fields)
            with pytest.raises(ArtifactStreamError):
                stream_inputs(client, message_id, fields, [b"HELLO"])
            with pytest.raises((broker.BrokerError, listener.ListenerError, OSError)):
                client.read(deadline=deadline())
            assert called == []
        finally:
            client.close()
        thread.join(5)
        # the sanitized local error, exactly; the service is not poisoned by a bad stream
        assert type(box.get("error")) is ep.ProbeServiceError and "served" not in box
        assert service.closed is False
        # the next connection serves normally
        box2, thread2 = served(service, side)
        client = connect(root, spec)
        try:
            _message_id, _fields = execute(client, operation="status")
            reply = xm.parse_execute_reply(client.read(deadline=deadline()).payload)
            assert reply.reason_code == "provider_terminal"  # the test router's own answer
        finally:
            client.close()
        thread2.join(5)
        assert box2.get("served") == 1, box2
    finally:
        service.close()


def test_a_request_id_outside_the_stream_grammar_is_a_sanitized_refusal(slot, monkeypatch):  # noqa: F811
    # review MUST: the domain admits any non-nil canonical UUID as a message id while the
    # stream's descriptor grammar demands a versioned one; the descriptor build must stay
    # inside the sanitizer or the raw stream error would escape the worker entrypoint
    monkeypatch.setattr(ep._Router, "admits_inputs", lambda self, request: True)
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            execute(client, operation="invoke_tool", message_id="00000000-0000-0000-8000-000000000000",
                    **declared([b"hello"], ["document_source"]))
            with pytest.raises((broker.BrokerError, listener.ListenerError, OSError)):
                client.read(deadline=deadline())
        finally:
            client.close()
        thread.join(5)
        assert type(box.get("error")) is ep.ProbeServiceError, box
        assert service.closed is False
    finally:
        service.close()


def test_declared_inputs_for_an_unregistered_operation_are_refused_before_any_byte_is_read(slot):  # noqa: F811
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            _message_id, _fields = execute(client, operation="cancel", **declared([b"hello"], ["document_source"]))
            reply = xm.parse_execute_reply(client.read(deadline=deadline()).payload)
            assert reply.outcome == "failed" and reply.reason_code == "validation_failed"
        finally:
            client.close()
        thread.join(5)
        assert box.get("served") == 1, box
    finally:
        service.close()


def test_a_foreign_correlation_on_the_stream_closes_before_the_operation_runs(slot, monkeypatch):  # noqa: F811
    from app.workers.artifact_stream import ArtifactStreamError

    called = []
    monkeypatch.setattr(ep._Router, "execute", lambda *args, **kwargs: called.append(args) or {})
    monkeypatch.setattr(ep._Router, "admits_inputs", lambda self, request: True)
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            _message_id, fields = execute(client, operation="invoke_tool", **declared([b"hello"], ["document_source"]))
            with pytest.raises((ArtifactStreamError, broker.BrokerError, listener.ListenerError, OSError)):
                stream_inputs(client, str(uuid4()), fields, [b"hello"])  # frames correlated to another request
                client.read(deadline=deadline())
            assert called == []
        finally:
            client.close()
        thread.join(5)
        assert type(box.get("error")) is ep.ProbeServiceError
    finally:
        service.close()


def test_an_unregistered_operation_is_a_typed_refusal(slot):  # noqa: F811 - the imported fixture
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            message_id, fields = execute(client, operation="invoke_tool")
            frame = client.read(deadline=deadline())
            assert frame.envelope.correlation_id == message_id
            reply = xm.parse_execute_reply(frame.payload)
            assert reply.operation == "invoke_tool" and reply.challenge == fields["challenge"]
            assert reply.outcome == "failed" and reply.reason_code == "validation_failed"
            assert reply.remote_terminal_observed == "failed"
            assert reply.usage_finality == "final" and reply.output is None
            assert reply.usage == {
                "model_calls": 0, "tool_calls": 0, "node_visits": 1, "loop_rounds": 0,
                "output_bytes": 0, "candidates": 0, "api_microunits": None,
            }
        finally:
            client.close()
        thread.join(5)
        assert box.get("served") == 1, box
    finally:
        service.close()


def test_the_probe_reports_the_registered_operations(slot):  # noqa: F811 - the imported fixture
    root, spec, side, _tree = slot
    service = open_service()
    try:
        assert service._router.operations() == ("describe_tools", "status")
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            message_id, _ = probe(client)
            frame = client.read(deadline=deadline())
            assert frame.envelope.correlation_id == message_id
            reply = parse_probe_reply(frame.payload)
            assert reply.runtime.registered_operations == ("describe_tools", "status")
            # the mode was selected by the first frame: an execute on a probe
            # connection is a rule violation that closes it with the closed error
            closed_after(client)
        finally:
            client.close()
        thread.join(5)
        assert "served" not in box and isinstance(box.get("error"), ep.ProbeServiceError)
    finally:
        service.close()


def test_an_execute_request_outside_the_grammar_closes_the_connection(slot):  # noqa: F811 - the imported fixture
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            with pytest.raises((broker.BrokerError, listener.ListenerError, OSError)):
                execute(client, payload=canonical_json({
                    "schema_version": xm.REQUEST_SCHEMA, "attempt_id": "nope",
                }))
                client.read(deadline=deadline())
        finally:
            client.close()
        thread.join(5)
        assert "served" not in box and isinstance(box.get("error"), ep.ProbeServiceError)
    finally:
        service.close()


@pytest.mark.parametrize("schema", [xm.REPLY_SCHEMA, "extension-stage-probe-result-v1"])
def test_a_reply_schema_on_a_request_frame_closes_the_connection(slot, schema):  # noqa: F811
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box, thread = served(service, side)
        client = connect(root, spec)
        try:
            with pytest.raises((broker.BrokerError, listener.ListenerError, OSError)):
                execute(client, payload=canonical_json({"schema_version": schema}))
                client.read(deadline=deadline())
        finally:
            client.close()
        thread.join(5)
        assert "served" not in box and isinstance(box.get("error"), ep.ProbeServiceError)
    finally:
        service.close()


def test_the_router_is_a_closed_code_owned_registry():
    router = ep._Router()
    assert router.operations() == ("describe_tools", "status")
    assert set(router.operations()) <= xm.OPERATIONS
    with pytest.raises(AttributeError):
        router.register  # noqa: B018 - there is no registration surface
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(router)
