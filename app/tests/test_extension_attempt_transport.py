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
from dataclasses import replace
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from app.domain.refs import EntityRef, canonical_json
from app.runtime import extension_attempt_transport as xt
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.budgets import BudgetExceeded
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
from app.tests.test_runtime_budget_dispatch import budget_row, opened
from app.tests.test_runtime_result_settlement import dispatched
from app.tests.test_scheduler_attempt_dispatch import (
    build as _build,
)
from app.tests.test_scheduler_attempt_dispatch import (
    handlers,
    writer_attempt_id,
)
from app.tests.test_scheduler_attempt_dispatch import started as _started
from app.workers import extension_execute_messages as xm
from app.workers import extension_probe as ep
from app.workers import listener

# the transport states a bound of at least the reply frame's ceiling (4 KiB); the
# shared subject's 1 000-byte policy cap cannot admit an attempt reserved from it
OUTPUT_CAP = xm.MAX_REPLY_BYTES + xt.MAX_INPUT_BYTES


def compiled_context(subject, tool=None):
    """Controlled authority assembly, never a persisted qualification claim."""
    from app.tests.test_graph_contract import (
        authority_with,
        compile_value,
        trusted_tool,
    )
    from app.tests.test_graph_execution import linear_graph

    selected = TEXT_PROFILE if tool is None else tool
    subject.compiled = compile_value(linear_graph(), compilation_authority=authority_with([
        trusted_tool(tool_id=selected["tool_id"], version=selected["version"]),
    ]))
    return {"compiled": subject.compiled, "node_id": "writer", "binding_id": "source-read"}


def build(subject, run, attempts, registry):
    return _build(subject, run, attempts, registry, compiled=getattr(subject, "compiled", None))


def started(path):
    return _started(path, max_output_bytes=OUTPUT_CAP)


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


def bound(subject, transport, *, tool_calls=0):
    # an attempt reserves the output bytes the transport states it can produce (the
    # dispatcher refuses less); a tool call reserves its one call
    return na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": na.AttemptBinding.create(
            envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
            budget_policy_ref=subject.refs.budget, deadline_at_ms=10_000,
            lease_duration_ms=1_000, model_calls=1, tool_calls=tool_calls, node_visits=1,
            loop_rounds=0, output_bytes=transport.output_bytes_bound, candidates=0, api_microunits=None,
            principal=subject.principal, grant=subject.grant,
        )},
        transport=transport,
    )


def binding_with(subject, *, output_bytes):
    return na.AttemptBinding.create(
        envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
        budget_policy_ref=subject.refs.budget, deadline_at_ms=10_000,
        lease_duration_ms=1_000, model_calls=1, tool_calls=0, node_visits=1,
        loop_rounds=0, output_bytes=output_bytes, candidates=0, api_microunits=None,
        principal=subject.principal, grant=subject.grant,
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
    assert content["output"]["runtime"]["registered_operations"] == ["describe_tools", "invoke_tool", "status"]
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
    assert content["output"] == {"tools": ep.tool_descriptions()}
    attempt_id = writer_attempt_id(run)
    assert subject.ledger.get_attempt(attempt_id)["terminal_outcome"] == "succeeded"
    row = budget_row(subject, na.reservation_identity(attempt_id))
    assert row["state"] == "finalized"
    assert row["actual_output_bytes"] == len(canonical_json({"tools": ep.tool_descriptions()}))
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

    assert xt._CONTROL_MEASURED == OUTPUT_OPERATIONS == frozenset({"status", "describe_tools", "invoke_tool"})
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
                                               slot_number=SLOT, operation="invoke_tool", artifact_inputs=(item,),
                                               tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
    assert built.operation == "invoke_tool"
    # invoke_tool names its tool at build; a query never does
    with pytest.raises(ValueError):
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                                           operation="invoke_tool", artifact_inputs=(item,))
    with pytest.raises(ValueError):
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                                           operation="status", tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
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
        # a tool that ran and failed made its one call (control verifies exactly that)
        return {"outcome": "failed", "usage_finality": "final", "remote_terminal_observed": "failed",
                "reason_code": "provider_terminal", "usage": {**ep._ZERO_USAGE, "tool_calls": 1}, "output": None}

    monkeypatch.setattr(ep._Router, "execute", recording)
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    payload = b"y" * 20_000
    inputs = (xt.ExtensionArtifactInput(media_type="text/plain", declared_size=len(payload),
                                        sha256=sha256(payload).hexdigest(), role="document_source",
                                        payload=payload),)
    transport_ = xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                                    slot_number=SLOT, operation="invoke_tool",
                                                    artifact_inputs=inputs, tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
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
            lease_duration_ms=1_000, model_calls=1, tool_calls=1, node_visits=1,
            loop_rounds=0, output_bytes=transport_.output_bytes_bound, candidates=0, api_microunits=None,
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
                                                    artifact_inputs=(item,), tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
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
        build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    assert [type(item) for item in raised] == [xt.ExtensionTransportError]
    assert raised[0].code == "transport_stream" and raised[0].dispatch_effect == "outcome_unknown"
    assert subject.ledger.get_attempt(writer_attempt_id(run))["terminal_outcome"] == "outcome_unknown"
    assert called == []
    assert type(box.get("error")) is ep.ProbeServiceError


TEXT_PROFILE = {"tool_id": "text_profile", "version": "1.0.0"}


def test_the_real_tool_runs_end_to_end_and_its_result_is_the_sealed_node_result(tmp_path, staged):
    # T087 first real tool over the artifact leg: control declares and streams the text,
    # the worker runs `text_profile`, the reply's result is sealed as the attempt's artifact
    # and the node's result; the attempt settles with one tool call and measured bytes
    from hashlib import sha256

    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    text = b"one two\nthree\n"
    inputs = (xt.ExtensionArtifactInput(media_type="text/plain", declared_size=len(text),
                                        sha256=sha256(text).hexdigest(), role="document_source", payload=text),)
    transport_ = xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                                    slot_number=SLOT, operation="invoke_tool",
                                                    artifact_inputs=inputs, tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
    outcome = build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    content = subject.domain.get(dict(outcome.result_refs)[writer_execution]).body["content"]
    assert content["operation"] == "invoke_tool"
    assert content["output"] == {"tool_id": "text_profile", "version": "1.0.0", "result": {
        "byte_count": len(text), "char_count": len(text.decode()), "line_count": 2, "word_count": 3,
        "sha256": sha256(text).hexdigest(), "utf8": True}, "artifacts": []}
    assert content["artifacts"] == []
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "succeeded" and stored["usage_finality"] == "final"
    row = budget_row(subject, na.reservation_identity(attempt_id))
    assert row["state"] == "finalized"
    assert row["actual_tool_calls"] == 1 and row["actual_model_calls"] == 0
    assert row["actual_output_bytes"] == len(canonical_json(content["output"]))
    assert box.get("served") == 1, box


def test_the_worker_cannot_inflate_the_usage_of_invoke_tool(tmp_path, staged, monkeypatch):
    # a tool call's usage is verified by control: one tool call, no model call, measured bytes
    from hashlib import sha256

    box = staged[3]
    original = ep._Router.execute

    def inflated(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        return {**result, "usage": {**result["usage"], "model_calls": 1}}

    monkeypatch.setattr(ep._Router, "execute", inflated)
    subject, run = started(tmp_path / "ledger")
    text = b"hello"
    inputs = (xt.ExtensionArtifactInput(media_type="text/plain", declared_size=5, sha256=sha256(text).hexdigest(),
                                        role="document_source", payload=text),)
    transport_ = xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                                    slot_number=SLOT, operation="invoke_tool",
                                                    artifact_inputs=inputs, tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    assert subject.ledger.get_attempt(writer_attempt_id(run))["terminal_outcome"] == "outcome_unknown"
    assert box.get("served") == 1, box


def observed_call(monkeypatch):
    raised = []
    original = xt.ExtensionAttemptTransport.__call__

    def observed(self, permit, request, window):
        try:
            return original(self, permit, request, window)
        except BaseException as failure:
            raised.append(failure)
            raise

    monkeypatch.setattr(xt.ExtensionAttemptTransport, "__call__", observed)
    return raised


def text_input(text, *, role="document_source", media_type="text/plain"):
    from hashlib import sha256

    return xt.ExtensionArtifactInput(media_type=media_type, declared_size=len(text),
                                     sha256=sha256(text).hexdigest(), role=role, payload=text)


def tool_transport(subject, inputs, tool=None):
    return xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE,
                                              slot_number=SLOT, operation="invoke_tool",
                                              artifact_inputs=inputs, tool=TEXT_PROFILE if tool is None else tool,
                                              ledger=subject.ledger, **compiled_context(subject, tool))


def test_build_mirrors_the_tools_input_contract_so_a_refusal_is_never_lost_as_unknown(tmp_path):
    # review MUST: the worker refuses a call declaring the wrong inputs before reading a
    # byte, but control streamed regardless and met the reply mid-stream — a definitive
    # validation_failed became outcome_unknown. Control mirrors the tool's input contract
    # at build (a static mirror pinned to the worker's entry until ToolDefinition records)
    subject, _run = started(tmp_path / "ledger")
    text = b"hello"
    assert xt.TOOL_INPUT_CONTRACTS[("text_profile", "1.0.0")] == (("document_source", "text/plain"),)
    assert xt.TOOL_INPUT_CONTRACTS[("text_normalize", "1.0.0")] == (("document_source", "text/plain"),)
    assert set(xt.TOOL_INPUT_CONTRACTS) == set(xt.TOOL_OUTPUT_CONTRACTS) == set(xt.TOOL_EFFECTS) == {
        (entry["tool_id"], entry["version"]) for entry in ep.tool_descriptions()}
    assert tuple(ep.TEXT_PROFILE_ENTRY["artifact_roles"]) == ("document_source",)
    assert dict(xt.TOOL_EFFECTS) == {(entry["tool_id"], entry["version"]): entry["effect_class"]
                                     for entry in ep.tool_descriptions()}
    tool_transport(subject, (text_input(text),))  # the exact contract builds
    for inputs in [
        (text_input(text), text_input(text)),
        (text_input(text, role="attachment"),),
        (text_input(text, media_type="application/octet-stream"),),
        (),
    ]:
        with pytest.raises(ValueError):
            tool_transport(subject, inputs)
    with pytest.raises(ValueError):
        tool_transport(subject, (text_input(text),), tool={"tool_id": "other_tool", "version": "1.0.0"})
    with pytest.raises(ValueError):
        tool_transport(subject, (text_input(text),), tool={"tool_id": "text_profile", "version": "2.0.0"})


def test_a_result_for_a_tool_control_did_not_name_is_never_sealed(tmp_path, staged, monkeypatch):
    # review MUST: the reply's tool id and version must be the ones control named
    box = staged[3]
    original = ep._Router.execute

    def swapped(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        return {**result, "output": {**result["output"], "tool_id": "other_tool", "version": "9.9.9"},
                "usage": {**result["usage"], "output_bytes": len(canonical_json(
                    {**result["output"], "tool_id": "other_tool", "version": "9.9.9"}))}}

    monkeypatch.setattr(ep._Router, "execute", swapped)
    raised = observed_call(monkeypatch)
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, tool_transport(subject, (text_input(b"hello"),)), tool_calls=1),
              handlers(subject, [])).run()
    assert raised[0].code == "transport_mismatch"
    assert subject.ledger.get_attempt(writer_attempt_id(run))["terminal_outcome"] == "outcome_unknown"
    assert box.get("served") == 1, box


def test_a_text_profile_result_that_contradicts_the_streamed_bytes_is_never_sealed(tmp_path, staged, monkeypatch):
    # review closure: the result is the worker's claim; the two facts control already holds
    # (the input's digest and size) are cross-checked before the claim is sealed
    box = staged[3]
    original = ep._Router.execute

    def forged(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        output = {**result["output"], "result": {**result["output"]["result"], "sha256": "f" * 64}}
        return {**result, "output": output, "usage": {**result["usage"], "output_bytes": len(canonical_json(output))}}

    monkeypatch.setattr(ep._Router, "execute", forged)
    raised = observed_call(monkeypatch)
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, tool_transport(subject, (text_input(b"hello"),)), tool_calls=1),
              handlers(subject, [])).run()
    assert raised[0].code == "transport_mismatch"
    assert box.get("served") == 1, box


@pytest.mark.parametrize("reply", [
    {"outcome": "outcome_unknown", "usage_finality": "unknown", "remote_terminal_observed": "not_observed",
     "reason_code": "transport_unknown", "usage": None, "output": None},
    {"outcome": "cancelled", "usage_finality": "final", "remote_terminal_observed": "cancelled",
     "reason_code": "cancel_requested", "usage": {**ep._ZERO_USAGE, "tool_calls": 1}, "output": None},
    {"outcome": "failed", "usage_finality": "final", "remote_terminal_observed": "failed",
     "reason_code": "deadline", "usage": dict(ep._ZERO_USAGE), "output": None},  # a call that ran claims its call
])
def test_a_read_effect_tool_cannot_answer_unknown_cancelled_or_an_uncalled_failure(tmp_path, staged, monkeypatch, reply):
    # review closure: an in-process deterministic read-effect tool has no unknown or cancelled
    # terminal — such an answer dodges the usage verification; and a failure after the call
    # ran claims exactly one call (zero only for a refusal before it: validation_failed,
    # permission_denied)
    box = staged[3]
    monkeypatch.setattr(ep._Router, "execute", lambda *args, **kwargs: dict(reply))
    raised = observed_call(monkeypatch)
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, tool_transport(subject, (text_input(b"hello"),)), tool_calls=1),
              handlers(subject, [])).run()
    assert raised[0].code == "transport_mismatch"
    assert box.get("served") == 1, box


def test_a_refusal_before_the_call_and_a_failure_after_it_settle_with_their_own_usage(tmp_path, staged, monkeypatch):
    box = staged[3]
    monkeypatch.setattr(ep._Router, "execute", lambda *args, **kwargs: {
        "outcome": "failed", "usage_finality": "final", "remote_terminal_observed": "failed",
        "reason_code": "permission_denied", "usage": dict(ep._ZERO_USAGE), "output": None})
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, tool_transport(subject, (text_input(b"hello"),)), tool_calls=1),
              handlers(subject, [])).run()
    assert subject.ledger.get_attempt(writer_attempt_id(run))["terminal_outcome"] == "failed"
    assert box.get("served") == 1, box


TEXT_NORMALIZE = {"tool_id": "text_normalize", "version": "1.0.0"}


def test_a_tools_output_artifacts_are_admitted_imported_and_sealed_into_the_node_result(tmp_path, staged):
    # the reverse leg end to end: control admits the offered batch under the tool's mirrored
    # output contract, imports each artifact as registered content, checks the reply's
    # bindings against what it received, and seals the blob references into the attempt's
    # artifact; the budget row counts the reply and the artifact bytes
    from hashlib import sha256

    from app.domain.store import BlobRef

    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    raw = b"a\r\nb\n"
    expected = b"a\nb\n"
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(raw),), tool=TEXT_NORMALIZE, ledger=subject.ledger, **compiled_context(subject, TEXT_NORMALIZE))
    assert xt.TOOL_OUTPUT_CONTRACTS[("text_normalize", "1.0.0")] == (("normalized_text", "text/plain"),)
    assert xt.TOOL_OUTPUT_CONTRACTS[("text_profile", "1.0.0")] == ()
    outcome = build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    content = subject.domain.get(dict(outcome.result_refs)[writer_execution]).body["content"]
    assert content["output"]["tool_id"] == "text_normalize"
    assert content["output"]["result"]["changed"] is True
    assert [item["role"] for item in content["artifacts"]] == ["normalized_text"]
    blob = BlobRef.from_dict(content["artifacts"][0]["blob"])
    assert blob.sha256 == sha256(expected).hexdigest() and blob.size == len(expected)
    assert subject.domain.read_blob(blob, purpose="operational") == expected
    assert content["artifacts"][0]["media_type"] == "text/plain"
    row = budget_row(subject, na.reservation_identity(writer_attempt_id(run)))
    assert row["state"] == "finalized"
    assert row["actual_output_bytes"] == len(canonical_json(content["output"])) + len(expected)
    assert box.get("served") == 1, box


def test_an_offered_artifact_outside_the_tools_output_contract_is_never_admitted(tmp_path, staged, monkeypatch):
    # a worker offering an artifact for a tool whose contract yields none, or one more than
    # the contract, or a binding that does not match what was received, is refused
    from hashlib import sha256

    box = staged[3]
    original = ep._Router.execute

    def offering(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        return {**result, "artifacts": (({"role": "normalized_text", "media_type": "text/plain"}, b"smuggled"),)}

    monkeypatch.setattr(ep._Router, "execute", offering)
    raised = observed_call(monkeypatch)
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, tool_transport(subject, (text_input(b"hello"),)), tool_calls=1),
              handlers(subject, [])).run()
    assert raised[0].code in {"transport_invalid", "transport_mismatch"}
    assert subject.ledger.get_attempt(writer_attempt_id(run))["terminal_outcome"] == "outcome_unknown"
    assert sha256(b"smuggled").hexdigest() not in repr(subject.domain.roots())
    # control closed the stream on the worker: its send fails as a sanitized local error
    assert box.get("served") == 1 or type(box.get("error")) is ep.ProbeServiceError, box


def test_a_binding_that_contradicts_the_received_artifact_is_never_sealed(tmp_path, staged, monkeypatch):
    box = staged[3]
    original = ep._Router.execute

    def lying(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        output = {**result["output"], "artifacts": [{**result["output"]["artifacts"][0], "sha256": "f" * 64}]}
        return {**result, "output": output}

    monkeypatch.setattr(ep._Router, "execute", lying)
    raised = observed_call(monkeypatch)
    subject, run = started(tmp_path / "ledger")
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"a\r\n"),), tool=TEXT_NORMALIZE, ledger=subject.ledger, **compiled_context(subject, TEXT_NORMALIZE))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    assert raised[0].code == "transport_mismatch"
    assert box.get("served") == 1, box


@pytest.mark.parametrize("lie", [{"sha256_out": "f" * 64}, {"byte_count_out": 999}, {"changed": False}])
def test_a_text_normalize_result_that_contradicts_the_received_output_is_never_sealed(tmp_path, staged, monkeypatch, lie):
    # review MUST: control received and digest-verified the output bytes; the result's
    # output digest, size and `changed` are facts control holds, not the worker's to claim
    box = staged[3]
    original = ep._Router.execute

    def lying(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        output = {**result["output"], "result": {**result["output"]["result"], **lie}}
        return {**result, "output": output, "usage": {**result["usage"], "output_bytes":
                len(canonical_json(output)) + sum(len(raw) for _, raw in result["artifacts"])}}

    monkeypatch.setattr(ep._Router, "execute", lying)
    raised = observed_call(monkeypatch)
    subject, run = started(tmp_path / "ledger")
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"a\r\n"),), tool=TEXT_NORMALIZE, ledger=subject.ledger, **compiled_context(subject, TEXT_NORMALIZE))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    assert raised[0].code == "transport_mismatch"
    assert box.get("served") == 1, box


def test_the_output_contracts_have_unique_roles_and_a_stated_output_bound():
    for key, contract in xt.TOOL_OUTPUT_CONTRACTS.items():
        roles = [role for role, _media in contract]
        assert len(roles) == len(set(roles)), key
    # the derived text is at most three times the input (NFC growth) and never over the ceiling
    assert xt.TOOL_OUTPUT_BOUNDS[("text_normalize", "1.0.0")] == (3, xt.MAX_INPUT_BYTES)
    assert xt.TOOL_OUTPUT_BOUNDS[("text_profile", "1.0.0")] == (0, 0)


def test_a_tool_call_intent_is_recorded_before_the_send_and_settled_after_the_reply(tmp_path, staged, monkeypatch):
    # T087 ToolCall: control records the write-ahead intent in the ledger before the request
    # frame leaves (the worker sees it already recorded), and settles it with the sealed
    # result after the reply; the effect class comes from the compiled definition
    seen = {}
    original = ep._Router.execute

    def observing(self, service, request, deadline, inputs=()):
        seen["intents"] = [(call["state"], call["tool_id"], call["effect_class"])
                           for call in subject.ledger.tool_calls_for_attempt(request.attempt_id)]
        return original(self, service, request, deadline, inputs)

    monkeypatch.setattr(ep._Router, "execute", observing)
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
    outcome = build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    assert seen["intents"] == [("intent", "text_profile", "read")]
    attempt_id = writer_attempt_id(run)
    calls = subject.ledger.tool_calls_for_attempt(attempt_id)
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    assert len(calls) == 1 and calls[0]["state"] == "succeeded"
    assert calls[0]["result_ref"] == dict(outcome.result_refs)[writer_execution].as_dict()
    assert calls[0]["artifact_inputs"] == [text_input(b"hello").declaration(0, 1).as_dict()]
    assert calls[0]["version"] == "1.0.0"
    assert box.get("served") == 1, box


def test_a_tool_call_settles_failed_or_unknown_by_what_control_observed(tmp_path, staged, monkeypatch):
    box = staged[3]
    original = ep._Router.execute

    def lying(self, service, request, deadline, inputs=()):
        result = original(self, service, request, deadline, inputs)
        return {**result, "output": {**result["output"], "tool_id": "other_tool", "version": "9.9.9"}}

    monkeypatch.setattr(ep._Router, "execute", lying)
    subject, run = started(tmp_path / "ledger")
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    calls = subject.ledger.tool_calls_for_attempt(writer_attempt_id(run))
    assert [call["state"] for call in calls] == ["unknown"]  # a refused reply: the effect is unknown
    assert box.get("served") == 1, box
    # a worker's typed failure settles the call as failed
    again = box["serve_again"]()
    subject2, run2 = started(tmp_path / "ledger2")
    monkeypatch.setattr(ep._Router, "execute", lambda *args, **kwargs: {
        "outcome": "failed", "usage_finality": "final", "remote_terminal_observed": "failed",
        "reason_code": "provider_terminal", "usage": {**ep._ZERO_USAGE, "tool_calls": 1}, "output": None})
    transport2 = xt.ExtensionAttemptTransport.build(
        domain_store=subject2.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, ledger=subject2.ledger, **compiled_context(subject2))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject2, run2, bound(subject2, transport2, tool_calls=1), handlers(subject2, [])).run()
    assert [call["state"] for call in subject2.ledger.tool_calls_for_attempt(writer_attempt_id(run2))] == ["failed"]
    assert again.get("served") == 1, again


def test_a_tool_call_never_stays_intent_on_a_terminal_attempt_in_process(tmp_path, staged, monkeypatch):
    # review closures: any exception out of the exchange settles the call unknown before it
    # propagates (not only the typed transport error); a vouched non-send settles it failed
    # — the call definitely never ran
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    monkeypatch.setattr(xt.ExtensionAttemptTransport, "_result", lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("PRIVATE")))
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    assert [call["state"] for call in subject.ledger.tool_calls_for_attempt(writer_attempt_id(run))] == ["unknown"]
    assert box.get("served") == 1, box
    # the intent is recorded once the connection stands; a vouched non-send from the exchange
    # then settles it failed (the worker sees a connection that sends nothing and closes)
    box["serve_again"]()
    subject2, run2 = started(tmp_path / "ledger2")
    monkeypatch.setattr(xt.ExtensionAttemptTransport, "_exchange", lambda *args, **kwargs: (_ for _ in ()).throw(
        xt.ExtensionTransportError("transport_unavailable", dispatch_effect="definitely_not_sent")))
    transport2 = xt.ExtensionAttemptTransport.build(
        domain_store=subject2.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, ledger=subject2.ledger, **compiled_context(subject2))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject2, run2, bound(subject2, transport2, tool_calls=1), handlers(subject2, [])).run()
    assert [call["state"] for call in subject2.ledger.tool_calls_for_attempt(writer_attempt_id(run2))] == ["failed"]


def test_external_effects_are_unavailable_and_a_read_refuses_an_effect_approval(tmp_path, monkeypatch):
    # V1 approvals and the historical ledger grammar remain, but cannot enable
    # an external invocation at this transport.
    subject, _run = started(tmp_path / "ledger")
    approval = EntityRef("action_approval", str(uuid4()), 1, "a" * 64)
    with pytest.raises(ValueError):  # a read effect carries no approval requirement
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                                           operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
                                           tool=TEXT_PROFILE, effect_approval_ref=approval)
    from types import MappingProxyType

    monkeypatch.setattr(xt, "TOOL_EFFECTS", MappingProxyType({**xt.TOOL_EFFECTS, ("text_profile", "1.0.0"): "external_irreversible"}))
    with pytest.raises(ValueError):  # a disagreeing mirror cannot change the compiled effect
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                                           operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
                                           tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))
    with pytest.raises(TypeError):  # of the exact kind
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                                           operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
                                           tool=TEXT_PROFILE, effect_approval_ref=EntityRef("artifact", str(uuid4()), 1, "a" * 64))
    with pytest.raises(ValueError):  # and the authority that recorded it, to verify it before the send
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                                           operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
                                           tool=TEXT_PROFILE, effect_approval_ref=approval, ledger=subject.ledger)
    # Historical ledger records still require their approval reference. This is
    # a record constraint, not permission to invoke an external tool.
    from app.runtime.ledger import ToolCallSpec, tool_call_identity

    attempt_id = str(uuid4())
    with pytest.raises(ValueError):
        ToolCallSpec(tool_call_id=tool_call_identity(attempt_id), attempt_id=attempt_id, tool_id="text_profile",
                     version="1.0.0", effect_class="external_irreversible", artifact_inputs=(), approval_ref=None)
    from app.runtime import ledger as ledger_module

    assert xt.APPROVAL_EFFECTS == ledger_module.TOOL_APPROVAL_EFFECTS
    assert xt.APPROVAL_EFFECTS == frozenset({"external_reversible", "external_irreversible",
                                             "instance_critical_secret", "instance_critical_storage"})
    with pytest.raises(TypeError):
        xt.ExtensionAttemptTransport.build(domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                                           operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
                                           tool=TEXT_PROFILE, ledger="nope")


def test_the_input_ceilings_agree_across_the_grammar_the_worker_and_control():
    from app.workers import extension_execute_messages as xm

    assert ep.EXECUTE_STREAM_LIMITS == xt._STREAM_LIMITS
    assert ep.EXECUTE_STREAM_LIMITS.max_total_bytes == xm.MAX_INPUT_BYTES
    assert ep.ARTIFACT_TYPE == xt.ARTIFACT_TYPE == "extension-artifact-v1"


def test_an_unregistered_operation_is_admitted_as_a_failed_attempt(tmp_path, staged):
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport(subject, operation="cancel")),
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
        build(subject, run, bound(subject, transport(subject)), handlers(subject, [])).run()
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


class _TrackedConnection:
    """Observe lifetime and request writes while retaining the real connection."""

    def __init__(self, connection, *, close_error=None, write_error=None):
        self.connection = connection
        # the real connection detaches its socket on close; keep the object it owned so
        # its own closed state (fileno -1) stays observable afterwards
        self.socket = connection._socket
        self.close_error = close_error
        self.write_error = write_error
        self.close_calls = 0
        self.execute_frames = 0

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def write(self, **kwargs):
        if self.write_error is not None:
            raise self.write_error
        result = self.connection.write(**kwargs)
        if kwargs["message_type"] == xt.REQUEST_TYPE:
            self.execute_frames += 1
        return result

    def close(self):
        self.close_calls += 1
        self.connection.close()
        if self.close_error is not None:
            raise self.close_error


def capture_real_connections(monkeypatch, **tracking_options):
    captured = []
    connect = listener._connect_extension_authenticated

    def tracked(*args, **kwargs):
        connection = _TrackedConnection(connect(*args, **kwargs), **tracking_options)
        captured.append(connection)
        return connection

    monkeypatch.setattr(listener, "_connect_extension_authenticated", tracked)
    return captured


def close_leaked_connections(captured):
    """Keep a deliberately RED lifetime regression from holding its worker thread."""

    for tracked in captured:
        if not tracked.connection.closed:
            tracked.connection.close()


def test_an_intent_exception_closes_the_actual_connection_without_sending(tmp_path, staged, monkeypatch):
    captured = capture_real_connections(monkeypatch)
    subject, permit, request = permit_and_request(tmp_path)
    issued = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
        operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
        tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))

    request = replace(request, tool_binding=transport_.compiled_tool_binding)

    def fail_intent(_ledger, _command_id, _spec):
        raise OSError("PRIVATE INTENT FAILURE")

    monkeypatch.setattr(type(subject.ledger), "record_tool_call", fail_intent)
    try:
        with pytest.raises(xt.ExtensionTransportError) as failure:
            transport_(permit, request, issued)
        assert failure.value.code == "transport_invalid"
        assert failure.value.dispatch_effect == "definitely_not_sent"
        assert str(failure.value) == "transport_invalid"
        assert len(captured) == 1
        assert captured[0].close_calls == 1
        assert captured[0].connection.closed
        assert captured[0].socket.fileno() == -1
        assert captured[0].execute_frames == 0
        assert subject.ledger.tool_calls_for_attempt(request.attempt_id) == []
    finally:
        close_leaked_connections(captured)


def test_an_intent_base_exception_survives_a_cleanup_oserror_and_closes_the_actual_connection(
        tmp_path, staged, monkeypatch):
    class IntentBoundaryAbort(BaseException):
        pass

    captured = capture_real_connections(monkeypatch, close_error=OSError("CLOSE FAILURE"))
    subject, permit, request = permit_and_request(tmp_path)
    issued = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
        operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
        tool=TEXT_PROFILE, ledger=subject.ledger, **compiled_context(subject))

    request = replace(request, tool_binding=transport_.compiled_tool_binding)

    def abort_intent(_ledger, _command_id, _spec):
        raise IntentBoundaryAbort("ORIGINAL INTENT ABORT")

    monkeypatch.setattr(type(subject.ledger), "record_tool_call", abort_intent)
    try:
        with pytest.raises(IntentBoundaryAbort, match="ORIGINAL INTENT ABORT"):
            transport_(permit, request, issued)
        assert len(captured) == 1
        assert captured[0].close_calls == 1
        assert captured[0].connection.closed
        assert captured[0].socket.fileno() == -1
        assert captured[0].execute_frames == 0
        assert subject.ledger.tool_calls_for_attempt(request.attempt_id) == []
    finally:
        close_leaked_connections(captured)


def test_an_exchange_failure_closes_the_actual_connection_once(tmp_path, staged, monkeypatch):
    captured = capture_real_connections(
        monkeypatch, write_error=OSError("WRITE FAILURE"), close_error=OSError("CLOSE FAILURE"))
    subject, permit, request = permit_and_request(tmp_path)
    with pytest.raises(xt.ExtensionTransportError) as failure:
        transport(subject)(permit, request, window(permit))
    assert failure.value.dispatch_effect == "may_have_started"
    assert len(captured) == 1
    assert captured[0].close_calls == 1
    assert captured[0].connection.closed
    assert captured[0].socket.fileno() == -1


def test_a_success_closes_the_actual_connection_once(tmp_path, staged, monkeypatch):
    captured = capture_real_connections(monkeypatch, close_error=OSError("CLOSE FAILURE"))
    subject, permit, request = permit_and_request(tmp_path)
    result = transport(subject)(permit, request, window(permit))
    assert result.outcome == "succeeded"
    assert len(captured) == 1
    assert captured[0].close_calls == 1
    assert captured[0].connection.closed
    assert captured[0].socket.fileno() == -1
    assert captured[0].execute_frames == 1


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


def test_the_transport_states_the_output_bytes_an_attempt_can_produce(tmp_path):
    # the reservation of `output_bytes` from the tool's stated bound: control measures
    # the reply's canonical output (inside the reply frame's ceiling) plus the output
    # artifacts it admits (the tool's growth factor over its inputs, never over the
    # leg's ceiling); a caller reserves exactly this and never overruns
    subject = opened(tmp_path)
    assert transport(subject).output_bytes_bound == xm.MAX_REPLY_BYTES
    assert transport(subject, operation="describe_tools").output_bytes_bound == xm.MAX_REPLY_BYTES
    assert tool_transport(subject, (text_input(b"hello"),)).output_bytes_bound == xm.MAX_REPLY_BYTES
    normalize = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"a\r\nb"),), tool=TEXT_NORMALIZE, ledger=subject.ledger, **compiled_context(subject, TEXT_NORMALIZE))
    assert normalize.output_bytes_bound == xm.MAX_REPLY_BYTES + 3 * 4
    at_ceiling = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"x" * xt.MAX_INPUT_BYTES),), tool=TEXT_NORMALIZE, ledger=subject.ledger, **compiled_context(subject, TEXT_NORMALIZE))
    assert at_ceiling.output_bytes_bound == xm.MAX_REPLY_BYTES + xt.MAX_INPUT_BYTES
    assert xm.MAX_REPLY_BYTES == 4_096  # the reply frame's ceiling (extension_execute_messages)


def test_an_attempt_reserved_from_the_bound_never_overruns_even_when_the_text_grows(tmp_path, staged):
    # an NFC expansion: U+0344 (2 bytes) derives U+0308 U+0301 (4 bytes) — the derived text
    # is larger than the input, within the stated growth; reserved from the bound, the
    # attempt finalizes with its measured usage under the reservation
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    raw = "\u0344" * 3
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(raw.encode()),), tool=TEXT_NORMALIZE, ledger=subject.ledger, **compiled_context(subject, TEXT_NORMALIZE))
    outcome = build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    content = subject.domain.get(dict(outcome.result_refs)[writer_execution]).body["content"]
    expected = "\u0308\u0301" * 3
    assert content["artifacts"][0]["blob"]["size"] == len(expected.encode()) > len(raw.encode())
    row = budget_row(subject, na.reservation_identity(writer_attempt_id(run)))
    assert row["state"] == "finalized" and row["output_bytes"] == transport_.output_bytes_bound
    assert row["actual_output_bytes"] == len(canonical_json(content["output"])) + len(expected.encode())
    assert row["actual_output_bytes"] <= row["output_bytes"]
    assert subject.book.status(subject.budget_session_id)["blocked_reason"] is None
    assert box.get("served") == 1, box


def test_an_attempt_reserved_under_the_bound_is_refused_at_build_not_settled_as_an_overrun(tmp_path, staged):
    # the transport's bound is authoritative: the dispatcher refuses a binding under it at
    # build (the ledger would otherwise settle the attempt as an accounting overrun that
    # blocks the whole budget session — pinned below through a transport that states no bound)
    box = staged[3]
    subject, run = started(tmp_path / "ledger")
    transport_ = transport(subject)
    with pytest.raises(ValueError, match="output bound"):
        na.NodeAttemptDispatcher.build(
            ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
            bindings={"writer": binding_with(subject, output_bytes=transport_.output_bytes_bound - 1)},
            transport=transport_)
    # the same exchange under-reserved through a bare callable stating no bound: the
    # attempt itself still succeeds, but the ledger settles its reservation as an
    # accounting overrun that blocks the whole budget session for every later
    # reservation — the reason the bound exists
    def bare(permit, request, window):
        return transport_(permit, request, window)

    dispatcher = na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": binding_with(subject, output_bytes=1)}, transport=bare)
    build(subject, run, dispatcher, handlers(subject, [])).run()
    row = budget_row(subject, na.reservation_identity(writer_attempt_id(run)))
    assert row["state"] == "overage" and row["actual_output_bytes"] > 1
    status = subject.book.status(subject.budget_session_id)
    assert status["blocked_reason"] == "reservation_overrun" and status["usage_finality"] == "known_overrun"
    with pytest.raises(BudgetExceeded):
        subject.book.reserve(subject.budget_session_id, str(uuid4()), model_calls=0, tool_calls=0,
                             node_visits=1, loop_rounds=0, output_bytes=1, api_microunits=None)
    assert box.get("served") == 1, box


def test_a_worker_returning_more_than_the_tools_stated_bound_is_never_admitted(tmp_path, staged, monkeypatch):
    # review MUST: the bound is a fact control enforces, not a claim it measures — a worker
    # returning more bytes than the tool's stated growth over its inputs (still under the
    # leg's ceiling) is refused as a mismatch, so the attempt never settles as an
    # accounting overrun that blocks the session
    box = staged[3]
    monkeypatch.setattr(ep, "_text_normalize", lambda raw: (b"x" * 10_000, True))
    raised = observed_call(monkeypatch)
    subject, run = started(tmp_path / "ledger")
    transport_ = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"hello"),), tool=TEXT_NORMALIZE, ledger=subject.ledger, **compiled_context(subject, TEXT_NORMALIZE))
    assert transport_.output_bytes_bound == xm.MAX_REPLY_BYTES + 15
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_, tool_calls=1), handlers(subject, [])).run()
    assert raised[0].code == "transport_mismatch"
    attempt_id = writer_attempt_id(run)
    assert subject.ledger.get_attempt(attempt_id)["terminal_outcome"] == "outcome_unknown"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "unknown"
    assert subject.book.status(subject.budget_session_id)["blocked_reason"] is None
    assert box.get("served") == 1 or type(box.get("error")) is ep.ProbeServiceError, box


def test_a_policy_cap_under_the_bound_refuses_the_attempt_before_any_row(tmp_path, staged):
    # review SHOULD: the shared subject's 1 000-byte cap cannot admit the reply frame's
    # ceiling — the budget refuses before any attempt or reservation row exists and the
    # session stays open (runtime.md: a spend cap is the owner's decision, never a
    # stranded open attempt)
    box = staged[3]
    subject, run = _started(tmp_path / "ledger")  # the 1 000-byte cap
    transport_ = transport(subject)
    assert transport_.output_bytes_bound > 1_000
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, bound(subject, transport_), handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    with pytest.raises(KeyError):
        subject.ledger.get_attempt(attempt_id)
    assert budget_row(subject, na.reservation_identity(attempt_id)) is None
    assert subject.book.status(subject.budget_session_id)["blocked_reason"] is None
    assert box.get("served") is None, box



def app_subject(app):
    """The transport test's subject over a real factory's components (the owner
    authority records approvals): refs, a budget session, a run, real-clock deadlines."""
    import time

    from app.domain.permissions import Grant, Principal
    from app.domain.schemas import Actor
    from app.runtime.budgets import BudgetPolicy
    from app.runtime.ledger import OwnerIdentity, RunSpec
    from app.tests.test_runtime_ledger import identifier, immutable

    domain, ledger, book = app.state.domain_store, app.state.runtime_ledger, app.state.budget_book
    roots = domain.roots()
    ledger.reconcile_startup(identifier(), observed_owners={})
    policy = BudgetPolicy.create(
        profile="execution", provider_mode="subscription", max_model_calls=3, max_tool_calls=5,
        max_node_visits=7, max_loop_rounds=2, max_output_bytes=OUTPUT_CAP, max_concurrency=2,
        max_wall_seconds=60, max_candidates=1)
    refs = SimpleNamespace(
        work=immutable(domain, roots, "work_revision"), environment=immutable(domain, roots, "environment"),
        consent=immutable(domain, roots, "run_consent"),
        budget=immutable(domain, roots, "budget_policy", content=policy.domain_content()),
        manifest=immutable(domain, roots, "run_manifest"), envelope=immutable(domain, roots, "execution_envelope"),
        profile=immutable(domain, roots, "runtime_profile"), result=immutable(domain, roots, "artifact"),
        produced=immutable(domain, roots, "artifact"))
    session = identifier()
    book.start(session, policy)
    later = int(time.time() * 1000) + 3_600_000
    principal = Principal(identifier(), Actor(identifier(), "test_actor", "test_fixture"), "runtime", "operational", later)
    grant = Grant(identifier(), identifier(), principal.id, refs.envelope, "read", "operational", None, later, 1)
    run = RunSpec(identifier(), refs.work, refs.environment, refs.consent, "live", refs.budget, session, refs.manifest)
    ledger.create_run(identifier(), run)
    subject = SimpleNamespace(domain=domain, ledger=ledger, book=book, refs=refs, principal=principal, grant=grant,
                              budget_session_id=session, owner=OwnerIdentity(identifier(), 4321, 900, identifier()),
                              deadline=later)
    return subject, run


def real_clock_dispatcher(subject, transport_):
    return na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": na.AttemptBinding.create(
            envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
            budget_policy_ref=subject.refs.budget, deadline_at_ms=subject.deadline,
            lease_duration_ms=1_000, model_calls=1, tool_calls=1, node_visits=1,
            loop_rounds=0, output_bytes=transport_.output_bytes_bound, candidates=0, api_microunits=None,
            principal=subject.principal, grant=subject.grant,
        )},
        transport=transport_,
    )


def test_legacy_external_decisions_remain_evidence_but_cannot_enable_a_send(tmp_path, monkeypatch):
    from app.runtime.gates import LOCAL
    from app.services.run_approvals import PersistentRunApprovals
    from app.tests.test_extension_candidates_persistent import owner
    from app.tests.test_graph_contract import (
        authority_with,
        compile_value,
        gated_tool_graph,
        trusted_tool,
    )

    scope = xt.tool_approval_scope("text_profile", "1.0.0")
    assert scope.startswith("tool-") and len(scope) == 5 + 36 and scope == scope.lower()
    assert xt.tool_approval_scope("x", "1.0.0+build.5") != xt.tool_approval_scope("x", "1.0.0")
    assert xt.tool_approval_scope("a:b", "1") != xt.tool_approval_scope("a", "b:1")
    assert LOCAL.fullmatch(xt.tool_approval_scope("t" * 64, "v" * 64)) is not None
    compiled = compile_value(gated_tool_graph(scope), compilation_authority=authority_with([
        trusted_tool("external_irreversible")]))
    # Controlled mirror alteration is rejection evidence, never real external support.
    monkeypatch.setattr(xt, "TOOL_EFFECTS", {**xt.TOOL_EFFECTS,
                                           ("text_profile", "1.0.0"): "external_irreversible"})
    connects = []
    monkeypatch.setattr(listener, "_connect_extension_authenticated", lambda *a, **kw: connects.append(1))
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        subject, run = app_subject(app)

        def decide(run_id, node_id, decision):
            subject.ledger.request_gate_approval(run_id, node_id, scope)
            receipt = approvals.record(request, {
                "schema_version": "run-approval-command-v1", "command_id": str(uuid4()), "run_id": run_id,
                "node_id": node_id, "approval_scope": scope, "decision": decision})
            return EntityRef.from_dict(receipt["approval_ref"])

        rejected = decide(run.run_id, "writer", "rejected")
        elsewhere = decide(run.run_id, "publish", "approved")
        genuine = decide(run.run_id, "tool-gate", "approved")
        _other_subject, other_run = app_subject(app)
        other = decide(other_run.run_id, "tool-gate", "approved")
        assert approvals.lookup(run.run_id, "writer", scope).decision == "rejected"
        assert approvals.lookup(run.run_id, "tool-gate", scope).approval_ref == genuine
        assert approvals.lookup(other_run.run_id, "tool-gate", scope).approval_ref == other
        for approved in (rejected, elsewhere, genuine, other,
                         EntityRef("action_approval", genuine.id, 2, genuine.sha256),
                         EntityRef("action_approval", genuine.id, 1, "b" * 64)):
            with pytest.raises(ValueError, match="external effects unavailable"):
                xt.ExtensionAttemptTransport.build(
                    domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                    operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
                    compiled=compiled, node_id="writer", binding_id="source-read", ledger=subject.ledger,
                    approvals=approvals, effect_approval_ref=approved, approval_gate_node_id="tool-gate")
        assert subject.ledger.tool_calls_for_attempt(writer_attempt_id(run)) == []
        assert subject.book.status(subject.budget_session_id)["active_reservations"] == 0
        assert connects == []


def test_the_effect_class_comes_from_the_definition_and_a_disagreeing_mirror_is_refused(tmp_path, monkeypatch):
    # T087 ToolDefinition-backed gate: the compiled binding's effect class (the compilation
    # authority's definition) is authoritative at build; the worker's mirrored claim must agree
    from types import MappingProxyType

    subject, _run = started(tmp_path / "ledger")
    built = xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, effect_class="read", ledger=subject.ledger, **compiled_context(subject))
    assert built.effect_class == "read"
    with pytest.raises(ValueError, match="disagrees"):
        xt.ExtensionAttemptTransport.build(
            domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
            artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, effect_class="external_irreversible", ledger=subject.ledger, **compiled_context(subject))
    with pytest.raises(ValueError):
        xt.ExtensionAttemptTransport.build(
            domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
            artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, effect_class="irreversible")
    with pytest.raises(ValueError):  # a query names no effect class
        xt.ExtensionAttemptTransport.build(
            domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="status", effect_class="read")
    monkeypatch.setattr(xt, "TOOL_EFFECTS", MappingProxyType({**xt.TOOL_EFFECTS, ("text_profile", "1.0.0"): "external_irreversible"}))
    with pytest.raises(ValueError, match="disagrees"):
        xt.ExtensionAttemptTransport.build(
            domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
            artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, effect_class="read", ledger=subject.ledger, **compiled_context(subject))


def test_a_manual_or_matching_legacy_gate_cannot_enable_external_invocation(tmp_path, monkeypatch):
    from app.services.run_approvals import PersistentRunApprovals
    from app.tests.test_extension_candidates_persistent import owner
    from app.tests.test_graph_contract import (
        authority_with,
        compile_value,
        gated_tool_graph,
        trusted_tool,
    )

    scope = xt.tool_approval_scope("text_profile", "1.0.0")
    compiled = compile_value(gated_tool_graph(scope), compilation_authority=authority_with([
        trusted_tool("external_irreversible")]))
    monkeypatch.setattr(xt, "TOOL_EFFECTS", {**xt.TOOL_EFFECTS,
                                           ("text_profile", "1.0.0"): "external_irreversible"})
    connects = []
    monkeypatch.setattr(listener, "_connect_extension_authenticated", lambda *a, **kw: connects.append(1))
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        subject, run = app_subject(app)
        for gate in ("manual-gate", "tool-gate"):
            subject.ledger.request_gate_approval(run.run_id, gate, scope)
            receipt = approvals.record(request, {
                "schema_version": "run-approval-command-v1", "command_id": str(uuid4()), "run_id": run.run_id,
                "node_id": gate, "approval_scope": scope, "decision": "approved"})
            approved = EntityRef.from_dict(receipt["approval_ref"])
            assert approvals.lookup(run.run_id, gate, scope).approval_ref == approved
            for named_gate in (None, gate, "disconnected", 7):
                with pytest.raises((ValueError, TypeError)):
                    xt.ExtensionAttemptTransport.build(
                        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                        operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
                        compiled=compiled, node_id="writer", binding_id="source-read", ledger=subject.ledger,
                        approvals=approvals, effect_approval_ref=approved, approval_gate_node_id=named_gate)
        assert subject.ledger.tool_calls_for_attempt(writer_attempt_id(run)) == []
        assert subject.book.status(subject.budget_session_id)["active_reservations"] == 0
        assert connects == []


def test_the_approval_gate_is_a_node_id_at_build(tmp_path):
    subject, _run = started(tmp_path / "ledger")
    approval = EntityRef("action_approval", str(uuid4()), 1, "a" * 64)
    # the gate id's shape is checked before the approvals authority: a bad id is a
    # TypeError even where the (absent) authority would be refused next
    for bad in ("A B", "g" * 65, "", "gate/x", 7):
        with pytest.raises(TypeError):
            xt.ExtensionAttemptTransport.build(
                domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
                artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, effect_approval_ref=approval,
                approvals=None, approval_gate_node_id=bad)
    with pytest.raises(ValueError):  # a well-formed gate, then the missing authority is the refusal
        xt.ExtensionAttemptTransport.build(
            domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
            artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE, effect_approval_ref=approval,
            approvals=None, approval_gate_node_id="tool-gate")
