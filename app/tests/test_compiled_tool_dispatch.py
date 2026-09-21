"""Compiled coherence only: controlled authority, real ledger and temporary worker.

These fixtures are not durable qualification or registered input lineage.
"""

from dataclasses import replace
from uuid import uuid4

import pytest

from app.runtime import extension_attempt_transport as xt
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.ledger import RuntimeLedger
from app.tests.test_extension_attempt_transport import (  # noqa: F401 - worker fixture dependencies
    INSTANCE,
    SLOT,
    TEXT_PROFILE,
    bound,
    channel,
    handlers,
    permit_and_request,
    slot,
    staged,
    started,
    text_input,
    window,
    worker_tree,
    writer_attempt_id,
)
from app.tests.test_graph_contract import authority_with, compile_value, trusted_tool
from app.tests.test_graph_execution import linear_graph
from app.tests.test_scheduler_attempt_dispatch import restart
from app.workers import listener


def compilation(tool_id="text_profile"):
    return compile_value(linear_graph(), compilation_authority=authority_with([
        trusted_tool(tool_id=tool_id),
    ]))


def bound_transport(subject, compiled=None, **overrides):
    return xt.ExtensionAttemptTransport.build(**{
        "domain_store": subject.domain, "instance_id": INSTANCE, "slot_number": SLOT,
        "operation": "invoke_tool", "artifact_inputs": (text_input(b"a\r\nb\n"),),
        "compiled": compiled or compilation(), "node_id": "writer", "binding_id": "source-read",
        "ledger": subject.ledger, **overrides,
    })


def assert_unreserved(subject):
    with subject.domain._connection() as db:
        assert db.execute("SELECT count(*) FROM runtime_attempts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM runtime_budget_reservations").fetchone()[0] == 0


@pytest.fixture
def no_connect(monkeypatch):
    calls = []
    def unexpected(*args, **kwargs):
        calls.append(1)
        raise AssertionError("invocation reached connector")
    monkeypatch.setattr(listener, "_connect_extension_authenticated", unexpected)
    yield calls
    assert calls == []


def test_legacy_unbound_invocation_is_unavailable_even_with_a_ledger(tmp_path):
    subject, _ = started(tmp_path)
    with pytest.raises(ValueError, match="compiled"):
        xt.ExtensionAttemptTransport.build(
            domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
            operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
            tool=TEXT_PROFILE, ledger=subject.ledger)


def test_invocation_without_toolcall_ledger_is_unavailable(tmp_path):
    subject, _ = started(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        xt.ExtensionAttemptTransport.build(
            domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
            operation="invoke_tool", artifact_inputs=(text_input(b"hello"),), tool=TEXT_PROFILE)


def test_another_graphs_read_tool_cannot_be_dispatched(tmp_path):
    subject, run = started(tmp_path)
    transport = bound_transport(subject)
    with pytest.raises((ValueError, sch.SchedulerError), match="compiled|binding"):
        sch.build_scheduler(compilation("text_normalize"), ledger=subject.ledger,
                            run_id=run.run_id, handlers=handlers(subject, []),
                            attempts=bound(subject, transport, tool_calls=1))
    assert_unreserved(subject)


@pytest.mark.parametrize("field,value", [
    ("graph_digest", "a" * 64), ("authority_digest", "b" * 64),
    ("node_id", "publish"), ("binding_id", "other"),
    ("definition_ref", "definition"), ("grant_ref", "grant"),
    ("tool_id", "text_normalize"), ("version", "2.0.0"),
    ("effect_class", "external_irreversible"), ("approval_gate_node_id", "manual"),
])
def test_scheduler_refuses_every_altered_projection_before_reservation(tmp_path, no_connect, field, value):
    from app.domain.refs import EntityRef

    subject, run = started(tmp_path)
    compiled = compilation()
    transport = bound_transport(subject, compiled)
    selected = compiled.tool_bindings[0]
    if field.endswith("_ref"):
        current = getattr(selected, field)
        value = EntityRef(current.kind, current.id, current.version + 1, current.sha256)
    changed = replace(compiled, tool_bindings=(replace(selected, **{field: value}),))
    with pytest.raises(ValueError):
        sch.build_scheduler(changed, ledger=subject.ledger, run_id=run.run_id,
                            handlers=handlers(subject, []), attempts=bound(subject, transport, tool_calls=1))
    assert_unreserved(subject)


def test_transport_cannot_be_reused_under_a_different_valid_graph_or_authority(tmp_path, no_connect):
    subject, run = started(tmp_path)
    compiled = compilation()
    transport = bound_transport(subject, compiled)
    attempts = bound(subject, transport, tool_calls=1)
    raw = linear_graph()
    raw["graph_id"] = str(uuid4())
    changed_authority = authority_with([trusted_tool()], approval_scopes=("another-scope",))
    for wrong in (compile_value(raw), compile_value(linear_graph(), compilation_authority=changed_authority)):
        with pytest.raises(ValueError):
            sch.build_scheduler(wrong, ledger=subject.ledger, run_id=run.run_id,
                                handlers=handlers(subject, []), attempts=attempts)
    # Failed reuse never rebinds the shared transport to the most recent scheduler.
    sch.build_scheduler(compiled, ledger=subject.ledger, run_id=run.run_id,
                        handlers=handlers(subject, []), attempts=attempts)
    assert transport.compiled_tool_binding == compiled.tool_bindings[0]
    assert_unreserved(subject)


@pytest.mark.parametrize("overrides", [
    {"tool": {"tool_id": "text_normalize", "version": "1.0.0"}},
    {"tool": {"tool_id": "text_profile", "version": "2.0.0"}},
    {"effect_class": "external_irreversible", "tool": TEXT_PROFILE},
    {"node_id": "publish"}, {"binding_id": "wrong"}, {"ledger": None},
])
def test_conflicting_legacy_or_absent_binding_fields_fail_before_connection(tmp_path, no_connect, overrides):
    subject, _ = started(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        bound_transport(subject, **overrides)
    assert_unreserved(subject)


def test_missing_tracking_and_wrong_exact_ledger_or_store_are_refused(tmp_path, no_connect):
    subject, _ = started(tmp_path / "one")
    other, _ = started(tmp_path / "two")
    with pytest.raises(TypeError):
        bound_transport(subject, ledger=other.ledger)
    # Even another RuntimeLedger object over the same DomainStore is not this dispatcher.
    another_ledger = RuntimeLedger(subject.domain)
    transport = bound_transport(subject, ledger=another_ledger)
    with pytest.raises(ValueError):
        bound(subject, transport, tool_calls=1)
    transport = bound_transport(subject)
    with pytest.raises(ValueError, match="tracked tool call"):
        bound(subject, transport, tool_calls=0)
    assert_unreserved(subject)


def test_direct_visit_requires_exact_compiled_context_even_after_scheduler_build(tmp_path, no_connect):
    subject, run = started(tmp_path)
    compiled = compilation()
    attempts = bound(subject, bound_transport(subject, compiled), tool_calls=1)
    sch.build_scheduler(compiled, ledger=subject.ledger, run_id=run.run_id,
                        handlers=handlers(subject, []), attempts=attempts)
    for wrong in (None, compilation("text_normalize")):
        with pytest.raises(ValueError):
            attempts.for_visit(run_id=run.run_id, node_id="writer", execution_id=str(uuid4()),
                               loop_index=0, compiled=wrong)
    with pytest.raises((ValueError, KeyError)):
        attempts.for_visit(run_id=run.run_id, node_id="publish", execution_id=str(uuid4()),
                           loop_index=0, compiled=compiled)
    assert_unreserved(subject)


def test_direct_visit_cannot_attach_the_binding_to_another_nodes_execution(tmp_path, no_connect):
    from app.runtime.ledger import ExecutionSpec

    subject, run = started(tmp_path)
    execution_id = str(uuid4())
    subject.ledger.create_execution(str(uuid4()), ExecutionSpec(
        execution_id, run.run_id, "publish", str(uuid4()), (0,), ()))
    compiled = compilation()
    attempts = bound(subject, bound_transport(subject, compiled), tool_calls=1)
    with pytest.raises(ValueError, match="execution"):
        attempts.for_visit(run_id=run.run_id, node_id="writer", execution_id=execution_id,
                           loop_index=0, compiled=compiled)
    assert_unreserved(subject)


@pytest.mark.parametrize("change", ["missing", "wrong-node", "wrong-binding", "wrong-graph"])
def test_direct_transport_cannot_bypass_request_binding(tmp_path, no_connect, change):
    subject, permit, request = permit_and_request(tmp_path)
    issued = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    compiled = compilation()
    transport = bound_transport(subject, compiled)
    selected = compiled.tool_bindings[0]
    if change == "wrong-node":
        request = replace(request, node_id="publish", tool_binding=selected)
    elif change == "wrong-binding":
        request = replace(request, tool_binding=replace(selected, binding_id="other"))
    elif change == "wrong-graph":
        request = replace(request, tool_binding=compilation("text_normalize").tool_bindings[0])
    with pytest.raises(xt.ExtensionTransportError) as error:
        transport(permit, request, issued)
    assert error.value.dispatch_effect == "definitely_not_sent"
    assert subject.ledger.tool_calls_for_attempt(request.attempt_id) == []


@pytest.mark.parametrize("tool_id", ["text_profile", "text_normalize"])
def test_matching_compiler_scheduler_and_worker_track_one_call_and_restart_never_resends(
        tmp_path, staged, monkeypatch, tool_id):  # noqa: F811 - imported fixture
    from app.domain.refs import canonical_json
    from app.domain.store import BlobRef
    from app.tests.test_runtime_budget_dispatch import budget_row
    from app.workers import extension_probe as ep

    subject, run = started(tmp_path / "ledger")
    compiled = compilation(tool_id)
    seen = []
    original = ep._Router.execute
    def observe(self, service, request, deadline, inputs=()):
        seen.append([(item.role, raw) for item, raw in inputs])
        assert [call["state"] for call in subject.ledger.tool_calls_for_attempt(request.attempt_id)] == ["intent"]
        return original(self, service, request, deadline, inputs)
    monkeypatch.setattr(ep._Router, "execute", observe)
    def scheduler():
        return sch.build_scheduler(compiled, ledger=subject.ledger, run_id=run.run_id,
                                   handlers=handlers(subject, []),
                                   attempts=bound(subject, bound_transport(subject, compiled), tool_calls=1))
    result = scheduler().run()
    execution = sch.execution_identity(run.run_id, "writer", 0)
    content = subject.domain.get(dict(result.result_refs)[execution]).body["content"]
    assert content["output"]["tool_id"] == tool_id
    artifact_bytes = 0
    if tool_id == "text_normalize":
        blob = BlobRef.from_dict(content["artifacts"][0]["blob"])
        assert subject.domain.read_blob(blob, purpose="operational") == b"a\nb\n"
        artifact_bytes = 4
    else:
        assert content["output"]["result"]["byte_count"] == 5
    attempt_id = writer_attempt_id(run)
    calls = subject.ledger.tool_calls_for_attempt(attempt_id)
    assert len(calls) == 1 and calls[0]["state"] == "succeeded"
    assert (calls[0]["tool_id"], calls[0]["version"], calls[0]["effect_class"]) == (tool_id, "1.0.0", "read")
    assert [(item["ordinal"], item["role"], item["declared_size"]) for item in calls[0]["artifact_inputs"]] == [(0, "document_source", 5)]
    row = budget_row(subject, na.reservation_identity(attempt_id))
    assert row["actual_tool_calls"] == 1 and row["state"] == "finalized"
    assert row["actual_output_bytes"] == len(canonical_json(content["output"])) + artifact_bytes
    assert scheduler().run().result_refs == result.result_refs
    restart(subject, tmp_path / "ledger")
    assert scheduler().run().result_refs == result.result_refs
    assert subject.ledger.tool_calls_for_attempt(attempt_id) == calls
    assert seen == [[("document_source", b"a\r\nb\n")]]
    assert staged[3].get("served") == 1


@pytest.mark.parametrize("wrong", ["ledger", "run", "execution"])
def test_direct_call_rechecks_ledger_execution_before_connection(tmp_path, monkeypatch, wrong):
    subject, permit, request = permit_and_request(tmp_path / "one")
    issued = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    compiled = compilation()
    transport = bound_transport(subject, compiled)
    request = replace(request, tool_binding=compiled.tool_bindings[0])
    if wrong == "ledger":
        other, _ = started(tmp_path / "two")
        transport = bound_transport(other, compiled)
    elif wrong == "run":
        request = replace(request, run_id=str(uuid4()))
    else:
        request = replace(request, node_id="publish")
    connects = []
    monkeypatch.setattr(xt, "extension_channel", lambda **kw: (None, None))
    def unexpected(*args, **kwargs):
        connects.append(1)
        raise OSError("no real connection")
    monkeypatch.setattr(listener, "_connect_extension_authenticated", unexpected)
    with pytest.raises(xt.ExtensionTransportError):
        transport(permit, request, issued)
    assert connects == []


def test_direct_call_rejects_another_ledger_issuer_over_the_same_store(tmp_path, monkeypatch):
    subject, permit, request = permit_and_request(tmp_path)
    issued = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    compiled = compilation()
    request = replace(request, tool_binding=compiled.tool_bindings[0])
    other = RuntimeLedger(subject.domain)
    transport = bound_transport(subject, compiled, ledger=other)
    connects = []
    monkeypatch.setattr(xt, "extension_channel", lambda **kw: (None, None))
    def unexpected(*args, **kwargs):
        connects.append(1)
        raise OSError("no actual connection")
    monkeypatch.setattr(listener, "_connect_extension_authenticated", unexpected)
    with pytest.raises(xt.ExtensionTransportError) as error:
        transport(permit, request, issued)
    assert error.value.dispatch_effect == "definitely_not_sent"
    assert connects == []
    assert subject.ledger.tool_calls_for_attempt(request.attempt_id) == []


def test_direct_call_with_the_actual_issuing_ledger_runs_the_real_worker(tmp_path, staged):  # noqa: F811
    subject, permit, request = permit_and_request(tmp_path)
    compiled = compilation()
    request = replace(request, tool_binding=compiled.tool_bindings[0])
    issued = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    result = bound_transport(subject, compiled)(permit, request, issued)
    assert result.outcome == "succeeded"
    content = subject.domain.get(result.result_ref).body["content"]
    assert content["output"]["tool_id"] == "text_profile"
    assert content["output"]["result"]["byte_count"] == 5
    calls = subject.ledger.tool_calls_for_attempt(request.attempt_id)
    assert len(calls) == 1 and calls[0]["state"] == "succeeded"
    assert staged[3].get("served") == 1


@pytest.mark.parametrize("invalid", ["fabricated", "copied", "replaced", "widened", "discarded", "inhibited"])
def test_invalid_window_authority_never_reaches_the_connector(tmp_path, no_connect, invalid):
    from copy import copy

    subject, permit, request = permit_and_request(tmp_path)
    compiled = compilation()
    request = replace(request, tool_binding=compiled.tool_bindings[0])
    issued = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    if invalid == "fabricated":
        issued = window(permit)
    elif invalid == "copied":
        issued = copy(issued)
    elif invalid == "replaced":
        issued = replace(issued)
    elif invalid == "widened":
        object.__setattr__(issued, "runtime_remaining_ms", issued.runtime_remaining_ms + 1)
    elif invalid == "discarded":
        subject.ledger.discard_dispatch_permit(permit)
    else:
        subject.ledger.emergency_inhibit_attempt(permit.attempt_id)
    with pytest.raises(xt.ExtensionTransportError) as error:
        bound_transport(subject, compiled)(permit, request, issued)
    assert error.value.dispatch_effect == "definitely_not_sent"
    assert subject.ledger.tool_calls_for_attempt(request.attempt_id) == []


def test_genuine_legacy_external_approval_cannot_enable_invocation(tmp_path, monkeypatch):
    from app.domain.refs import EntityRef
    from app.services.run_approvals import PersistentRunApprovals
    from app.tests.test_extension_attempt_transport import app_subject
    from app.tests.test_extension_candidates_persistent import owner

    # Controlled mirror alteration proves refusal only, never external tool support.
    monkeypatch.setattr(xt, "TOOL_EFFECTS", {("text_profile", "1.0.0"): "external_irreversible"})
    with owner(tmp_path) as (app, _, request, _, _):
        subject, run = app_subject(app)
        approvals = PersistentRunApprovals(subject.domain, app.state.owner_authority)
        scope = xt.tool_approval_scope("text_profile", "1.0.0")
        subject.ledger.request_gate_approval(run.run_id, "writer", scope)
        receipt = approvals.record(request, {
            "schema_version": "run-approval-command-v1", "command_id": str(uuid4()),
            "run_id": run.run_id, "node_id": "writer", "approval_scope": scope,
            "decision": "approved"})
        approved = EntityRef.from_dict(receipt["approval_ref"])
        assert approvals.lookup(run.run_id, "writer", scope).approval_ref == approved
        with pytest.raises(ValueError):
            xt.ExtensionAttemptTransport.build(
                domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT,
                operation="invoke_tool", artifact_inputs=(text_input(b"hello"),),
                tool=TEXT_PROFILE, ledger=subject.ledger, approvals=approvals,
                effect_approval_ref=approved, effect_class="external_irreversible")
