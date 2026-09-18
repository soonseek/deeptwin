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


def execute(client, *, operation="status", payload=None):
    fields = {
        "attempt_id": str(uuid4()),
        "execution_id": str(uuid4()),
        "operation": operation,
        "envelope_ref": ref("execution_envelope"),
        "profile_ref": ref("runtime_profile"),
        "remaining_ms": 1_500,
        "challenge": os.urandom(32),
    }
    message_id = str(uuid4())
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
