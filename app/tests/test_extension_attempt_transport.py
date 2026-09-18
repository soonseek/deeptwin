"""T087/T018 slice: the real attempt transport replaces the injected fake.

`ExtensionAttemptTransport` performs one authenticated AF_UNIX exchange with
the in-process worker service under the one-shot permit: it writes the
execute request for the bound operation, reads the one reply, verifies the
correlation, attempt, operation and nonce, rechecks the fences, and maps the
reply to the ledger's result vocabulary. A succeeded read-class reply
(`status`, `describe_tools`) is sealed control-side as an immutable `artifact` record (the worker never
touches the store); admission still happens only through
`accept_result_and_settle` inside `NodeAttemptDispatcher`. Same macOS seams
as the probe tests: service, operation and transport logic, never positive
Linux authentication, a real image or a container.
"""

import time
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.domain.refs import canonical_json
from app.runtime import extension_attempt_transport as xt
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.ledger import ConsumedDispatchWindow
from app.tests.test_extension_listener import INSTANCE
from app.tests.test_extension_probe import (  # noqa: F401 - fixture re-exports
    SLOT,
    channel,
    open_service,
    serve_in_thread,
    slot,
    worker_tree,
)
from app.tests.test_runtime_budget_dispatch import budget_row
from app.tests.test_runtime_result_settlement import dispatched
from app.tests.test_scheduler_attempt_dispatch import (
    build,
    dispatcher,
    handlers,
    started,
    writer_attempt_id,
)
from app.workers import extension_probe as ep
from app.workers import listener


@pytest.fixture
def staged(slot, monkeypatch):  # noqa: F811 - the imported fixture
    root, spec, side, tree = slot

    def derived(*, instance_id, slot_number):
        assert (instance_id, slot_number) == (INSTANCE, SLOT)
        return root, spec

    monkeypatch.setattr(xt, "extension_channel", derived)
    service = open_service()
    box = {}
    thread = serve_in_thread(service, box, side, deadline_ms=20_000)
    threads = [thread]

    def serve_again():
        # one accepted connection per serve: a test that exchanges twice serves twice
        again = {}
        threads.append(serve_in_thread(service, again, side, deadline_ms=20_000))
        return again

    box["serve_again"] = serve_again
    try:
        yield root, spec, tree, box
    finally:
        for pending in threads:
            pending.join(25)
        try:
            service.close()
        except ep.ProbeServiceError:
            pass


def bound(subject, transport):
    # the status output is a few hundred bytes: reserve within the policy cap
    return na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": na.AttemptBinding.create(
            envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
            budget_policy_ref=subject.refs.budget, deadline_at_ms=10_000,
            lease_duration_ms=1_000, model_calls=1, tool_calls=0, node_visits=1,
            loop_rounds=0, output_bytes=1_000, candidates=0, api_microunits=None,
            principal=subject.principal, grant=subject.grant,
        )},
        transport=transport,
    )


def transport(subject, *, operation="status"):
    return xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
        operation=operation,
    )


def test_status_executes_over_the_socket_and_the_sealed_output_is_the_node_result(
    tmp_path, staged
):
    _root, spec, tree, box = staged
    subject, run = started(tmp_path / "ledger")
    calls = []
    outcome = build(subject, run, bound(subject, transport(subject)),
                    handlers(subject, calls)).run()
    assert calls == ["intake", "writer", "publish"]
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    result_ref = dict(outcome.result_refs)[writer_execution]
    record = subject.domain.get(result_ref)
    assert record.body["kind"] == "artifact" and record.body["purpose"] == "operational"
    content = record.body["content"]
    assert content["schema_version"] == "extension-execute-output-v1"
    assert content["operation"] == "status"
    assert content["attempt_id"] == writer_attempt_id(run)
    assert content["execution_id"] == writer_execution
    assert content["output"]["service_identity"] == spec.responder_service
    assert content["output"]["component"]["build_identity_digest"] == tree["identity_digest"]
    assert content["output"]["runtime"]["registered_operations"] == ["describe_tools", "status"]
    assert record.body["parent_refs"] == [subject.refs.envelope.as_dict()]
    # the sealed artifact is addressable from the send command: one id per attempt
    assert content["send_command_id"] == na._command_identity(writer_attempt_id(run), "send")
    assert result_ref.id == xt.sealed_artifact_identity(content["send_command_id"])
    assert result_ref.id == str(uuid5(NAMESPACE_URL,
                                      "deeptwin:artifact:execute:" + content["send_command_id"]))
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "succeeded" and stored["usage_finality"] == "final"
    row = budget_row(subject, na.reservation_identity(attempt_id))
    assert row["state"] == "finalized" and row["usage_finality"] == "known"
    assert row["actual_output_bytes"] == len(canonical_json(content["output"]))
    assert 0 < row["actual_output_bytes"] <= 1_000
    assert row["actual_model_calls"] == 0 and row["actual_node_visits"] == 1
    assert subject.ledger._pending_permits == {}
    assert box.get("served") == 1, box


def test_describe_tools_executes_over_the_socket_and_seals_the_empty_catalogue(tmp_path, staged):
    _root, _spec, _tree, box = staged
    subject, run = started(tmp_path / "ledger")
    outcome = build(subject, run, bound(subject, transport(subject, operation="describe_tools")),
                    handlers(subject, [])).run()
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    content = subject.domain.get(dict(outcome.result_refs)[writer_execution]).body["content"]
    assert content["operation"] == "describe_tools"
    assert content["output"] == {"tools": []}
    attempt_id = writer_attempt_id(run)
    assert subject.ledger.get_attempt(attempt_id)["terminal_outcome"] == "succeeded"
    row = budget_row(subject, na.reservation_identity(attempt_id))
    assert row["state"] == "finalized"
    assert row["actual_output_bytes"] == len(canonical_json({"tools": []}))
    assert row["actual_model_calls"] == 0 and row["actual_tool_calls"] == 0
    assert box.get("served") == 1, box


def test_the_worker_cannot_inflate_the_usage_of_describe_tools(tmp_path, staged, monkeypatch):
    # a read-class query makes no model or tool call and control measures its bytes
    box = staged[3]
    original = ep._Router.execute

    def inflated(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        result["usage"] = {**result["usage"], "tool_calls": 1}
        return result

    monkeypatch.setattr(ep._Router, "execute", inflated)
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport(subject, operation="describe_tools")),
              handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    assert subject.ledger.get_attempt(attempt_id)["terminal_outcome"] == "outcome_unknown"
    assert box.get("served") == 1, box


def test_a_read_class_query_cannot_dodge_the_measured_usage_by_claiming_it_unknown(tmp_path, staged, monkeypatch):
    # review closure: a succeeded `describe_tools` with usage_finality "unknown" and no
    # counters completed the run with an unknown budget row; a completed read-class query
    # has no unknown usage — control measures it, so the claim is a mismatch
    box = staged[3]
    original = ep._Router.execute

    def dodging(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        return {**result, "usage_finality": "unknown", "usage": None}

    monkeypatch.setattr(ep._Router, "execute", dodging)
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport(subject, operation="describe_tools")),
              handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    assert subject.ledger.get_attempt(attempt_id)["terminal_outcome"] == "outcome_unknown"
    assert box.get("served") == 1, box


def test_the_control_measured_queries_are_exactly_the_operations_with_an_output_grammar():
    from app.workers.extension_execute_messages import OPERATIONS, OUTPUT_OPERATIONS

    assert xt._CONTROL_MEASURED == OUTPUT_OPERATIONS == frozenset({"status", "describe_tools"})
    assert OUTPUT_OPERATIONS <= OPERATIONS


def test_build_refuses_artifact_inputs_for_operations_that_take_none(tmp_path):
    from hashlib import sha256

    from app.workers.artifact_stream import BytesSource

    subject, _run = started(tmp_path / "ledger")
    item = xt.ExtensionArtifactInput(media_type="text/plain", declared_size=5,
                                     sha256=sha256(b"hello").hexdigest(), role="document_source",
                                     payload=b"hello")
    for operation in ("status", "describe_tools"):
        with pytest.raises(ValueError):
            xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                               slot_number=SLOT, operation=operation, artifact_inputs=(item,))
    built = xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                               slot_number=SLOT, operation="invoke_tool", artifact_inputs=(item,))
    assert built.operation == "invoke_tool"
    with pytest.raises(TypeError):
        xt.ExtensionArtifactInput(media_type="text/plain", declared_size=5, sha256="d" * 64, role="document_source",
                                  payload=BytesSource(b"hello"))  # bytes, not a source
    with pytest.raises(TypeError):
        xt.ExtensionArtifactInput(media_type="text/plain", declared_size=4, sha256=sha256(b"hello").hexdigest(),
                                  role="document_source", payload=b"hello")  # the declaration must be the bytes' own


def test_declared_inputs_stream_after_the_request_and_a_typed_result_settles(tmp_path, staged, monkeypatch):
    # end to end over the real socket: control declares and streams the inputs, the worker
    # (a test-only handler under invoke_tool) receives them and answers a typed failure,
    # the attempt settles as failed with final zero usage
    from hashlib import sha256

    seen = {}

    def recording(self, service, request, deadline, inputs):
        seen["inputs"] = [(item.role, raw) for item, raw in inputs]
        return {"outcome": "failed", "usage_finality": "final", "remote_terminal_observed": "failed",
                "reason_code": "provider_terminal", "usage": dict(ep._ZERO_USAGE), "output": None}

    monkeypatch.setattr(ep._Router, "execute", recording)
    # the test seam: `invoke_tool` is unregistered today, so the router would refuse the
    # inputs before reading a byte; admit them to exercise the byte route itself
    monkeypatch.setattr(ep._Router, "admits_inputs", lambda self, request: True)
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    payload = b"y" * 20_000
    inputs = (xt.ExtensionArtifactInput(media_type="application/octet-stream", declared_size=len(payload),
                                        sha256=sha256(payload).hexdigest(), role="document_source",
                                        payload=payload),)
    transport_ = xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                                    slot_number=SLOT, operation="invoke_tool",
                                                    artifact_inputs=inputs)
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_), handlers(subject, [])).run()
    assert seen["inputs"] == [("document_source", payload)]
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "failed" and stored["usage_finality"] == "final"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "finalized"
    assert box.get("served") == 1, box
    # review closure: the same built transport serves the owner's recovery retry — the
    # inputs stream again from their bytes, never from a consumed one-shot source
    seen.clear()
    again = box["serve_again"]()
    retrying = na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": na.AttemptBinding.create(
            envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
            budget_policy_ref=subject.refs.budget, deadline_at_ms=10_000,
            lease_duration_ms=1_000, model_calls=1, tool_calls=0, node_visits=1,
            loop_rounds=0, output_bytes=1_000, candidates=0, api_microunits=None,
            principal=subject.principal, grant=subject.grant,
        )},
        transport=transport_, retry_after_terminal=True,
    )
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, retrying, handlers(subject, [])).run()
    assert seen["inputs"] == [("document_source", payload)]
    assert again.get("served") == 1, again


def test_a_stream_failure_on_control_is_a_typed_unknown_outcome(tmp_path, staged, monkeypatch):
    # review MUST: control's stream-failure path must raise the typed transport error
    # (code `transport_stream`, effect outcome_unknown) — not a bare ValueError that only
    # the dispatcher's last-resort barrier turns into an unknown outcome
    from hashlib import sha256

    called = []
    monkeypatch.setattr(ep._Router, "execute", lambda *args, **kwargs: called.append(args) or {})
    monkeypatch.setattr(ep._Router, "admits_inputs", lambda self, request: True)
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    error = xt.ExtensionTransportError("transport_stream")
    assert error.code == "transport_stream" and error.dispatch_effect == "outcome_unknown"
    # a declaration that lies about its bytes cannot be built; force the mismatch past the
    # build check to make the stream itself fail at the end digest
    item = xt.ExtensionArtifactInput(media_type="text/plain", declared_size=5,
                                     sha256=sha256(b"hello").hexdigest(), role="document_source", payload=b"hello")
    object.__setattr__(item, "payload", b"HELLO")
    transport_ = xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                                    slot_number=SLOT, operation="invoke_tool",
                                                    artifact_inputs=(item,))
    raised = []
    original = xt.ExtensionAttemptTransport.__call__

    def observed(self, permit, request, window):
        try:
            return original(self, permit, request, window)
        except BaseException as failure:
            raised.append(failure)
            raise

    monkeypatch.setattr(xt.ExtensionAttemptTransport, "__call__", observed)
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_), handlers(subject, [])).run()
    assert [type(item) for item in raised] == [xt.ExtensionTransportError]
    assert raised[0].code == "transport_stream" and raised[0].dispatch_effect == "outcome_unknown"
    assert subject.ledger.get_attempt(writer_attempt_id(run))["terminal_outcome"] == "outcome_unknown"
    assert called == []
    assert type(box.get("error")) is ep.ProbeServiceError


def test_the_input_ceilings_agree_across_the_grammar_the_worker_and_control():
    from app.workers import extension_execute_messages as xm

    assert ep.EXECUTE_STREAM_LIMITS == xt._STREAM_LIMITS
    assert ep.EXECUTE_STREAM_LIMITS.max_total_bytes == xm.MAX_INPUT_BYTES
    assert ep.ARTIFACT_TYPE == xt.ARTIFACT_TYPE == "extension-artifact-v1"


def test_an_unregistered_operation_is_admitted_as_a_failed_attempt(tmp_path, staged):
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport(subject, operation="invoke_tool")),
              handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "failed" and stored["usage_finality"] == "final"
    observations = subject.ledger.result_observations(attempt_id)
    assert len(observations) == 1
    assert observations[0]["reason_code"] == "validation_failed"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "finalized"
    assert box.get("served") == 1, box


def test_no_reachable_worker_is_an_unknown_outcome(tmp_path, slot, monkeypatch):  # noqa: F811
    root, spec, _side, _tree = slot
    monkeypatch.setattr(xt, "extension_channel",
                        lambda *, instance_id, slot_number: (root, spec))
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport(subject)), handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "outcome_unknown"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "unknown"
    assert subject.ledger._pending_permits == {}


def test_build_refuses_wrong_stores_operations_and_slots(tmp_path):
    subject, _ = started(tmp_path / "ledger")
    with pytest.raises(TypeError):
        xt.ExtensionAttemptTransport.build(domain_store=object(), instance_id=INSTANCE,
                                           slot_number=SLOT, operation="status")
    with pytest.raises(ValueError):
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                           slot_number=SLOT, operation="model_step")
    with pytest.raises((TypeError, ValueError)):
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                           slot_number=0, operation="status")
    with pytest.raises(TypeError):
        xt.ExtensionAttemptTransport()


def permit_and_request(tmp_path):
    subject, attempt, _request, permit = dispatched(tmp_path / "ledger")
    run_id = subject.ledger.get_execution(attempt.execution_id)["spec"]["run_id"]
    request = na.AttemptDispatchRequest(
        run_id=run_id, node_id="writer", execution_id=attempt.execution_id,
        attempt_id=attempt.attempt_id, envelope_ref=subject.refs.envelope,
        profile_ref=subject.refs.profile, deadline_at_ms=10_000,
    )
    return subject, permit, request


def window(permit, *, runtime_ms=5_000, budget_ms=5_000):
    return ConsumedDispatchWindow(permit=permit, runtime_remaining_ms=runtime_ms,
                                  budget_remaining_ms=budget_ms,
                                  anchor_monotonic=time.monotonic())


def test_an_exhausted_window_never_connects(tmp_path, slot, monkeypatch):  # noqa: F811
    root, spec, _side, _tree = slot
    monkeypatch.setattr(xt, "extension_channel", lambda *, instance_id, slot_number: (root, spec))
    subject, permit, request = permit_and_request(tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("connected with no window")

    monkeypatch.setattr(listener, "_connect_extension_authenticated", boom)
    with pytest.raises(xt.ExtensionTransportError) as failure:
        transport(subject)(permit, request, window(permit, runtime_ms=0))
    assert failure.value.code == "transport_deadline"
    assert failure.value.dispatch_effect == "definitely_not_sent"


def test_a_connect_refusal_is_definitely_not_sent(tmp_path, slot, monkeypatch):  # noqa: F811
    root, spec, _side, _tree = slot  # nothing listens on the slot
    monkeypatch.setattr(xt, "extension_channel", lambda *, instance_id, slot_number: (root, spec))
    subject, permit, request = permit_and_request(tmp_path)
    with pytest.raises(xt.ExtensionTransportError) as failure:
        transport(subject)(permit, request, window(permit))
    assert failure.value.code in {"transport_unavailable", "transport_deadline"}
    assert failure.value.dispatch_effect == "definitely_not_sent"
    assert xt.ExtensionTransportError("transport_invalid").dispatch_effect == "outcome_unknown"


def test_the_worker_cannot_inflate_the_usage_of_status(tmp_path, staged, monkeypatch):
    box = staged[3]
    original = ep._Router.execute

    def inflated(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        result["usage"] = {**result["usage"], "model_calls": 7}
        return result

    monkeypatch.setattr(ep._Router, "execute", inflated)
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport(subject)), handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    assert subject.ledger.get_attempt(attempt_id)["terminal_outcome"] == "outcome_unknown"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "unknown"
    assert box.get("served") == 1, box
