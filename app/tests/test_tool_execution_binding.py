"""T087: a tool call's execution binding — the ports contract's per-tool input
declaration (count, role, media, selector) checked by the dispatcher before any
send and re-checked by the worker, and the per-execution approval binding (an
owner decision authorizes one attempt of one execution, never another visit or
a retry attempt; the same attempt replays idempotently).

Controlled mirror alteration (an external effect class for `text_profile`) is
rejection/admission evidence of the gate only, never real external tool support.
"""

import hashlib
import os
from contextlib import contextmanager
from dataclasses import replace
from types import MappingProxyType
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.extensions import port_schema_generator as psg
from app.extensions.tool_input_contracts import (
    MISMATCH_CODES,
    ToolArtifactInputContract,
    ToolInputMismatch,
    check_tool_inputs,
)
from app.runtime import extension_attempt_transport as xt
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.budgets import BudgetDispatchRequest
from app.runtime.ledger import (
    AttemptSpec,
    ExecutionSpec,
    LedgerError,
    ToolCallSpec,
    tool_call_identity,
)
from app.tests.test_extension_attempt_transport import (  # noqa: F401 - fixture re-exports
    INSTANCE,
    SLOT,
    TEXT_PROFILE,
    app_subject,
    channel,
    slot,
    staged,
    started,
    text_input,
    tool_transport,
    worker_tree,
)
from app.workers import extension_execute_messages as xm
from app.workers import extension_probe as ep
from app.workers import listener

TEXT_CONTRACT = {"mode": "bounded", "min_items": 1, "max_items": 1, "role": "document_source",
                 "allowed_media_types": ["text/plain"], "selector_policy": "forbidden"}


# --- the per-tool input declaration --------------------------------------------------------


def test_the_contract_value_is_the_ports_closed_object_and_refuses_anything_else():
    none = ToolArtifactInputContract("none")
    assert none.as_dict() == {"mode": "none"}
    bounded = ToolArtifactInputContract.bounded(min_items=0, max_items=32, role="document_source",
                                                allowed_media_types=("application/pdf", "text/plain"),
                                                selector_policy="optional")
    assert bounded.as_dict()["allowed_media_types"] == ["application/pdf", "text/plain"]
    valid = {"mode": "bounded", "min_items": 0, "max_items": 1, "role": "r",
             "allowed_media_types": ("text/plain",), "selector_policy": "forbidden"}
    ToolArtifactInputContract(**valid)
    for bad in [
        {"mode": "some"}, {"mode": "none", "min_items": 1}, {"mode": "none", "role": "x"},
        {**valid, "min_items": 2}, {**valid, "max_items": 33}, {**valid, "role": "Role"},
        {**valid, "allowed_media_types": ()},
        {**valid, "allowed_media_types": ("text/plain", "application/pdf")},
        {**valid, "selector_policy": "sometimes"}, {**valid, "min_items": True},
    ]:
        with pytest.raises(ValueError):
            ToolArtifactInputContract(**bad)


@pytest.mark.parametrize("inputs,code", [
    ((), "missing_input"),
    ((("document_source", "text/plain", None),) * 2, "extra_input"),
    ((("attachment", "text/plain", None),), "wrong_role"),
    ((("document_source", "application/octet-stream", None),), "wrong_media"),
    ((("document_source", "text/plain", "selector-ref"),), "selector_mismatch"),
    ((("document_source", "text/plain", None),), None),
])
def test_the_check_names_how_the_inputs_miss_and_agrees_with_the_ports_validator(inputs, code):
    contract = xt.TOOL_INPUT_CONTRACTS[("text_profile", "1.0.0")]
    assert contract.as_dict() == TEXT_CONTRACT
    ports_view = [{"role": role, "declared_media_type": media, "selector_ref": selector}
                  for role, media, selector in inputs]
    definition = {"tool_id": "text_profile", "artifact_input_contract": contract.as_dict()}
    if code is None:
        check_tool_inputs(contract, inputs)
        psg._validate_tool_contract(definition, ports_view)
        return
    with pytest.raises(ToolInputMismatch) as refused:
        check_tool_inputs(contract, inputs)
    assert refused.value.code == code and code in MISMATCH_CODES
    with pytest.raises(psg.PortSchemaValidationError):  # the ports contract refuses the same inputs
        psg._validate_tool_contract(definition, ports_view)
    with pytest.raises(ToolInputMismatch):  # mode:none takes nothing at all
        check_tool_inputs(ToolArtifactInputContract("none"), (("document_source", "text/plain", None),))


def test_control_and_worker_declare_the_same_contract_for_every_tool_of_the_table():
    assert dict(xt.TOOL_INPUT_CONTRACTS) == dict(ep.TOOL_INPUT_CONTRACTS)
    assert set(xt.TOOL_INPUT_CONTRACTS) == {(entry["tool_id"], entry["version"]) for entry in ep.tool_descriptions()}
    for (tool_id, version), contract in ep.TOOL_INPUT_CONTRACTS.items():
        entry = next(item for item in ep.tool_descriptions() if (item["tool_id"], item["version"]) == (tool_id, version))
        # the contract's role is one of the roles the tool describes; its bound fits the wire
        assert contract.role in entry["artifact_roles"]
        assert contract.max_items <= xm.MAX_ARTIFACT_INPUTS
        assert contract.as_dict() == TEXT_CONTRACT


@pytest.mark.parametrize("tool", ["text_profile", "text_normalize"])
@pytest.mark.parametrize("inputs,code", [
    ((), "missing_input"),
    ((b"a", b"b"), "extra_input"),
    (((b"a", "attachment", "text/plain"),), "wrong_role"),
    (((b"a", "document_source", "text/markdown"),), "wrong_media"),
])
def test_the_dispatcher_refuses_mismatching_inputs_before_any_row_or_send(tmp_path, tool, inputs, code):
    subject, run = started(tmp_path / "ledger")
    supplied = tuple(text_input(item) if type(item) is bytes else
                     text_input(item[0], role=item[1], media_type=item[2]) for item in inputs)
    with pytest.raises(ValueError, match=code):
        tool_transport(subject, supplied, tool={"tool_id": tool, "version": "1.0.0"})
    assert subject.ledger.attempts_for_run(run.run_id) == []


def test_the_dispatcher_rechecks_the_declaration_at_the_call_before_the_connection(tmp_path, monkeypatch):
    from app.tests.test_compiled_tool_dispatch import bound_transport, compilation
    from app.tests.test_extension_attempt_transport import permit_and_request

    subject, permit, request = permit_and_request(tmp_path)
    compiled = compilation()
    transport_ = bound_transport(subject, compiled)
    request = replace(request, tool_binding=compiled.tool_bindings[0])
    issued = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    # the declaration changes under a built transport (a table swapped in-process)
    narrowed = ToolArtifactInputContract.bounded(min_items=1, max_items=1, role="document_source",
                                                 allowed_media_types=("text/markdown",), selector_policy="forbidden")
    monkeypatch.setattr(xt, "TOOL_INPUT_CONTRACTS", MappingProxyType({**xt.TOOL_INPUT_CONTRACTS,
                                                                      ("text_profile", "1.0.0"): narrowed}))
    connects = []
    monkeypatch.setattr(listener, "_connect_extension_authenticated", lambda *a, **kw: connects.append(1))
    with pytest.raises(xt.ExtensionTransportError) as error:
        transport_(permit, request, issued)
    assert error.value.code == "transport_mismatch" and error.value.dispatch_effect == "definitely_not_sent"
    assert connects == [] and subject.ledger.tool_calls_for_attempt(request.attempt_id) == []


def _request(tool_id, declared):
    return xm.parse_execute_request(xm.encode_execute_request(
        attempt_id=str(uuid4()), execution_id=str(uuid4()), operation="invoke_tool",
        envelope_ref=EntityRef("execution_envelope", str(uuid4()), 1, "0" * 64),
        profile_ref=EntityRef("runtime_profile", str(uuid4()), 1, "0" * 64),
        remaining_ms=1_000, challenge=os.urandom(32),
        artifact_batch_id=str(uuid4()) if declared else None,
        artifact_inputs=[{"ordinal": index, "media_type": media, "declared_size": 1,
                          "sha256": hashlib.sha256(b"a").hexdigest(), "role": role}
                         for index, (role, media) in enumerate(declared)],
        tool={"tool_id": tool_id, "version": "1.0.0"}))


@pytest.mark.parametrize("tool", ["text_profile", "text_normalize"])
def test_the_worker_rechecks_the_declaration_before_reading_a_byte(tool):
    router = ep._Router()
    assert router.admits_inputs(_request(tool, [("document_source", "text/plain")]))
    for declared in ([], [("document_source", "text/plain")] * 2, [("attachment", "text/plain")],
                     [("document_source", "text/markdown")]):
        request = _request(tool, declared)
        assert not ep._tool_contract_admits(request)
        if declared:
            assert not router.admits_inputs(request)  # refused before any artifact frame
        refused = ep._invoke_tool_operation(None, request, None, ())
        assert (refused["outcome"], refused["reason_code"], refused["usage"]["tool_calls"]) == (
            "failed", "validation_failed", 0)


# --- the per-execution approval binding ------------------------------------------------------


SCOPE = xt.tool_approval_scope("text_profile", "1.0.0")


@contextmanager
def gated(tmp_path, monkeypatch):
    """An owner app, a run, a compiled graph whose writer binds `text_profile` as an
    external-family tool behind the `tool-gate` human gate (the mirror altered to agree)."""
    from app.services.run_approvals import PersistentRunApprovals
    from app.tests.test_extension_candidates_persistent import owner
    from app.tests.test_graph_contract import (
        authority_with,
        compile_value,
        gated_tool_graph,
        trusted_tool,
    )

    compiled = compile_value(gated_tool_graph(SCOPE), compilation_authority=authority_with([
        trusted_tool("external_irreversible")]))
    monkeypatch.setattr(xt, "TOOL_EFFECTS", MappingProxyType({**xt.TOOL_EFFECTS,
                                                             ("text_profile", "1.0.0"): "external_irreversible"}))
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        subject, run = app_subject(app)
        subject.ledger.request_gate_approval(run.run_id, "tool-gate", SCOPE)
        yield subject, run, approvals, request, compiled


def decide(approvals, owner_request, run_id, *, execution_id, attempt_no=1, node="writer",
           decision="approved", gate="tool-gate", schema="run-approval-command-v2", command_id=None):
    payload = {"schema_version": schema, "command_id": command_id or str(uuid4()), "run_id": run_id,
               "node_id": gate, "approval_scope": SCOPE, "decision": decision}
    if schema.endswith("v2"):
        payload.update(execution_id=execution_id, execution_node_id=node, attempt_no=attempt_no)
    return EntityRef.from_dict(approvals.record(owner_request, payload)["approval_ref"]), payload


def execution_of(subject, run, loop_index=0, node="writer"):
    execution_id = sch.execution_identity(run.run_id, node, loop_index)
    subject.ledger.create_execution(str(uuid4()), ExecutionSpec(
        execution_id, run.run_id, node, str(uuid4()), (loop_index,), ()))
    return execution_id


def committed_attempt(subject, execution_id, attempt_no, transport_):
    """A reserved attempt with a committed budgeted send intent and its consumed window."""
    attempt = AttemptSpec(str(uuid4()), execution_id, attempt_no, subject.refs.envelope, subject.refs.profile,
                          subject.refs.budget, str(uuid4()), "effect:" + str(uuid4()), subject.owner,
                          subject.deadline)
    subject.ledger.reserve_attempt(str(uuid4()), attempt, lease_duration_ms=60_000)
    budget = BudgetDispatchRequest.create(
        session_id=subject.budget_session_id, request_id=attempt.reservation_id, policy_ref=subject.refs.budget,
        model_calls=0, tool_calls=1, node_visits=1, loop_rounds=0,
        output_bytes=transport_.output_bytes_bound, candidates=0, api_microunits=None)
    permit = subject.ledger.commit_budgeted_send_intent(
        str(uuid4()), attempt.attempt_id, subject.owner, expected_revision=1, budget_book=subject.book,
        budget_request=budget, principal=subject.principal, grant=subject.grant)
    window = subject.ledger.consume_dispatch_permit_window(permit, budget_book=subject.book)
    return attempt, permit, window


def unsent_attempt(subject, execution_id, attempt_no):
    """A reserved attempt closed before any send (cancelled, definitely not sent): the
    ledger then admits the visit's next attempt as a retry."""
    from app.runtime.ledger import CancellationObservation

    attempt = AttemptSpec(str(uuid4()), execution_id, attempt_no, subject.refs.envelope, subject.refs.profile,
                          subject.refs.budget, str(uuid4()), "effect:" + str(uuid4()), subject.owner,
                          getattr(subject, "deadline", 10_000))
    subject.ledger.reserve_attempt(str(uuid4()), attempt, lease_duration_ms=1_000)
    subject.ledger.request_cancel(str(uuid4()), attempt.attempt_id, expected_revision=1)
    subject.ledger.finish_cancellation(str(uuid4()), attempt.attempt_id, subject.owner, CancellationObservation(
        outcome="cancelled", local_transport_closed=False, owned_process_exit=None,
        remote_terminal_observed="not_observed", usage_finality="final"), expected_revision=2)
    return attempt


def dispatch_request(subject, run, compiled, attempt, execution_id, node="writer"):
    return na.AttemptDispatchRequest(
        run_id=run.run_id, node_id=node, execution_id=execution_id, attempt_id=attempt.attempt_id,
        envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
        deadline_at_ms=subject.deadline, tool_binding=compiled.tool_bindings[0])


def gated_transport(subject, approvals, compiled, approval_ref):
    return xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(b"hello"),), compiled=compiled, node_id="writer",
        binding_id="source-read", ledger=subject.ledger, approvals=approvals, effect_approval_ref=approval_ref)


@pytest.fixture
def connects(monkeypatch):
    calls = []

    def observed(*args, **kwargs):
        calls.append(1)
        raise OSError("observed: the verification passed and the connection was attempted")

    monkeypatch.setattr(xt, "extension_channel", lambda **kw: (None, None))
    monkeypatch.setattr(listener, "_connect_extension_authenticated", observed)
    return calls


def test_an_execution_bound_decision_is_its_own_version_beside_the_readable_v1(tmp_path, monkeypatch):
    from app.services.run_approvals import (
        RunApprovalError,
        approval_identity,
        execution_approval_identity,
    )

    with gated(tmp_path, monkeypatch) as (subject, run, approvals, owner_request, _compiled):
        execution_id = sch.execution_identity(run.run_id, "writer", 0)
        v1, _ = decide(approvals, owner_request, run.run_id, execution_id=None, schema="run-approval-command-v1")
        v2, payload = decide(approvals, owner_request, run.run_id, execution_id=execution_id)
        assert v1.id == approval_identity(run.run_id, "tool-gate", SCOPE)
        assert v2.id == execution_approval_identity(run.run_id, "tool-gate", SCOPE, execution_id, "writer", 1)
        assert v1.id != v2.id
        record = subject.domain.get(v2).body["content"]
        assert record["schema_version"] == "run-approval-v2"
        assert (record["execution_id"], record["execution_node_id"], record["attempt_no"]) == (execution_id, "writer", 1)
        assert "execution_id" not in subject.domain.get(v1).body["content"]
        # the v1 lookup reads only v1; the execution lookup reads only v2
        assert approvals.lookup(run.run_id, "tool-gate", SCOPE).approval_ref == v1
        found = approvals.lookup_execution(run.run_id, "tool-gate", SCOPE, execution_id=execution_id,
                                           execution_node_id="writer", attempt_no=1)
        assert found.approval_ref == v2 and found.execution_bound and not approvals.lookup(
            run.run_id, "tool-gate", SCOPE).execution_bound
        assert approvals.lookup_execution(run.run_id, "tool-gate", SCOPE, execution_id=execution_id,
                                          execution_node_id="writer", attempt_no=2) is None
        assert approvals.resolve(v2) == found and approvals.resolve(v1).approval_ref == v1
        assert approvals.resolve(EntityRef("action_approval", v2.id, 1, "b" * 64)) is None
        # an exact replay returns the same receipt; the same identity with another decision conflicts
        assert EntityRef.from_dict(approvals.record(owner_request, payload)["approval_ref"]) == v2
        with pytest.raises(RunApprovalError, match="conflict"):
            approvals.record(owner_request, {**payload, "command_id": str(uuid4())})
        with pytest.raises(RunApprovalError, match="conflict"):
            approvals.record(owner_request, {**payload, "decision": "rejected"})
        # no binding without a gate request, and the binding's grammar is closed
        with pytest.raises(RunApprovalError, match="gate"):
            decide(approvals, owner_request, run.run_id, execution_id=execution_id, gate="other-gate")
        for bad in ({"attempt_no": 0}, {"attempt_no": 1_001}, {"attempt_no": "1"}, {"attempt_no": True},
                    {"execution_id": "not-a-uuid"}, {"execution_node_id": "a b"}):
            with pytest.raises(RunApprovalError, match="invalid"):
                approvals.record(owner_request, {**payload, "command_id": str(uuid4()), **bad})
        for missing in ("execution_id", "execution_node_id", "attempt_no"):
            with pytest.raises(RunApprovalError, match="invalid command"):
                approvals.record(owner_request, {key: value for key, value in payload.items() if key != missing})
        with pytest.raises(RunApprovalError, match="invalid command"):  # a v1 command carries no binding
            approvals.record(owner_request, {**payload, "schema_version": "run-approval-command-v1"})


def test_the_attempt_bound_matches_the_ledgers():
    from app.runtime import ledger
    from app.services import run_approvals

    assert run_approvals.MAX_ATTEMPTS_PER_EXECUTION == ledger.MAX_ATTEMPTS_PER_EXECUTION


def test_build_admits_only_an_approved_v2_decision_of_the_compiled_gate(tmp_path, monkeypatch, connects):
    with gated(tmp_path, monkeypatch) as (subject, run, approvals, owner_request, compiled):
        execution_id = sch.execution_identity(run.run_id, "writer", 0)
        v1, _ = decide(approvals, owner_request, run.run_id, execution_id=None, schema="run-approval-command-v1")
        rejected, _ = decide(approvals, owner_request, run.run_id, execution_id=execution_id, attempt_no=2,
                             decision="rejected")
        approved, _ = decide(approvals, owner_request, run.run_id, execution_id=execution_id)
        for refused in (v1, rejected, EntityRef("action_approval", approved.id, 1, "c" * 64),
                        EntityRef("action_approval", str(uuid4()), 1, "d" * 64)):
            with pytest.raises(ValueError, match="external effects unavailable"):
                gated_transport(subject, approvals, compiled, refused)
        with pytest.raises(ValueError):  # no approval at all
            xt.ExtensionAttemptTransport.build(
                domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
                artifact_inputs=(text_input(b"hello"),), compiled=compiled, node_id="writer",
                binding_id="source-read", ledger=subject.ledger)
        built = gated_transport(subject, approvals, compiled, approved)
        assert built.effect_class == "external_irreversible"
        assert connects == []


def test_an_approval_authorizes_only_its_own_attempt_of_its_own_visit(tmp_path, monkeypatch, connects):
    with gated(tmp_path, monkeypatch) as (subject, run, approvals, owner_request, compiled):
        first_visit = execution_of(subject, run, 0)
        second_visit = execution_of(subject, run, 1)
        approved, _ = decide(approvals, owner_request, run.run_id, execution_id=first_visit, attempt_no=1)
        transport_ = gated_transport(subject, approvals, compiled, approved)

        # another visit of the same node (a later loop round): refused before the channel
        other, other_permit, other_window = committed_attempt(subject, second_visit, 1, transport_)
        other_call = (other_permit, dispatch_request(subject, run, compiled, other, second_visit), other_window)
        with pytest.raises(xt.ExtensionTransportError) as error:
            transport_(*other_call)
        assert (error.value.code, error.value.dispatch_effect) == ("transport_invalid", "definitely_not_sent")
        assert connects == [] and subject.ledger.tool_calls_for_attempt(other.attempt_id) == []

        # a retry attempt of the approved visit (attempt 1 closed unsent, so the ledger admits
        # the retry): its own attempt number, not the approved one
        unsent_attempt(subject, first_visit, 1)
        retry, permit, window = committed_attempt(subject, first_visit, 2, transport_)
        with pytest.raises(xt.ExtensionTransportError) as error:
            transport_(permit, dispatch_request(subject, run, compiled, retry, first_visit), window)
        assert (error.value.code, error.value.dispatch_effect) == ("transport_invalid", "definitely_not_sent")
        assert connects == [] and subject.ledger.tool_calls_for_attempt(retry.attempt_id) == []

        # an approval of that retry attempt is its own decision, and authorizes it alone
        retry_approval, _ = decide(approvals, owner_request, run.run_id, execution_id=first_visit, attempt_no=2)
        assert retry_approval != approved
        with pytest.raises(xt.ExtensionTransportError):  # never the other visit's attempt
            gated_transport(subject, approvals, compiled, retry_approval)(*other_call)
        assert connects == []
        # the approved attempt of the approved visit passes the verification (and reaches the
        # connection, which this test observes and refuses: nothing was sent)
        with pytest.raises(xt.ExtensionTransportError) as error:
            gated_transport(subject, approvals, compiled, retry_approval)(
                permit, dispatch_request(subject, run, compiled, retry, first_visit), window)
        assert error.value.dispatch_effect == "definitely_not_sent"
        assert connects == [1]


def test_an_approval_of_another_node_or_run_never_authorizes(tmp_path, monkeypatch, connects):
    with gated(tmp_path, monkeypatch) as (subject, run, approvals, owner_request, compiled):
        visit = execution_of(subject, run, 0)
        # bound to the right execution id but naming another executing node
        wrong_node, _ = decide(approvals, owner_request, run.run_id, execution_id=visit, node="publish")
        transport_ = gated_transport(subject, approvals, compiled, wrong_node)
        attempt, permit, window = committed_attempt(subject, visit, 1, transport_)
        with pytest.raises(xt.ExtensionTransportError) as error:
            transport_(permit, dispatch_request(subject, run, compiled, attempt, visit), window)
        assert error.value.dispatch_effect == "definitely_not_sent"
        # another run's decision for the same deterministic node visit
        other_subject, other_run = app_subject_again(subject)
        other_subject.ledger.request_gate_approval(other_run.run_id, "tool-gate", SCOPE)
        elsewhere, _ = decide(approvals, owner_request, other_run.run_id,
                              execution_id=sch.execution_identity(other_run.run_id, "writer", 0))
        transport_ = gated_transport(subject, approvals, compiled, elsewhere)
        with pytest.raises(xt.ExtensionTransportError):
            transport_(permit, dispatch_request(subject, run, compiled, attempt, visit), window)
        assert connects == []


def app_subject_again(subject):
    from app.runtime.ledger import RunSpec
    from app.tests.test_runtime_ledger import identifier

    refs = subject.refs
    run = RunSpec(identifier(), refs.work, refs.environment, refs.consent, "live", refs.budget,
                  subject.budget_session_id, refs.manifest)
    subject.ledger.create_run(identifier(), run)
    return subject, run


def test_the_ledger_admits_one_approval_for_one_attempts_call_and_replays_the_same(tmp_path):
    from app.tests.test_runtime_ledger import identifier

    subject, run = started(tmp_path / "ledger")
    execution_id = execution_of(subject, run, 0)
    retry = AttemptSpec(identifier(), execution_id, 2, subject.refs.envelope, subject.refs.profile,
                        subject.refs.budget, identifier(), "effect:" + identifier(), subject.owner, 10_000)
    attempts = [unsent_attempt(subject, execution_id, 1), retry]
    subject.ledger.reserve_attempt(identifier(), retry, lease_duration_ms=1_000)
    approval = EntityRef("action_approval", str(uuid4()), 1, "a" * 64)

    def spec(attempt):
        return ToolCallSpec(tool_call_id=tool_call_identity(attempt.attempt_id), attempt_id=attempt.attempt_id,
                            tool_id="text_profile", version="1.0.0", effect_class="external_irreversible",
                            artifact_inputs=(), approval_ref=approval)

    first = subject.ledger.record_tool_call(identifier(), spec(attempts[0]))
    assert first["approval_ref"] == approval.as_dict()
    # the same attempt's intent again, under any command, is the same intent
    assert subject.ledger.record_tool_call(identifier(), spec(attempts[0])) == first
    with pytest.raises(LedgerError, match="another attempt"):
        subject.ledger.record_tool_call(identifier(), spec(attempts[1]))
    assert subject.ledger.tool_calls_for_attempt(attempts[1].attempt_id) == []


def test_the_approved_attempt_runs_end_to_end_and_its_call_carries_the_bound_approval(
        tmp_path, monkeypatch, staged):  # noqa: F811 - imported fixture
    with gated(tmp_path, monkeypatch) as (subject, run, approvals, owner_request, compiled):
        visit = execution_of(subject, run, 0)
        approved, _ = decide(approvals, owner_request, run.run_id, execution_id=visit)
        transport_ = gated_transport(subject, approvals, compiled, approved)
        attempt, permit, window = committed_attempt(subject, visit, 1, transport_)
        result = transport_(permit, dispatch_request(subject, run, compiled, attempt, visit), window)
        assert result.outcome == "succeeded"
        calls = subject.ledger.tool_calls_for_attempt(attempt.attempt_id)
        assert len(calls) == 1 and calls[0]["state"] == "succeeded"
        assert calls[0]["effect_class"] == "external_irreversible"
        assert calls[0]["approval_ref"] == approved.as_dict()
        assert staged[3].get("served") == 1
