"""T087: the owner's HTTP route for an execution-bound (v2) decision.

The dispatcher asks the ledger for one attempt's decision
(`request_execution_approval`: gate, execution, attempt number, the executing
node from the ledger's own execution row, and the digest of the attempt's exact
artifact inputs). `GET {run}/approvals/executions` lists those asks with their
state; `POST {run}/approvals/executions` (owner session, CSRF, same origin)
records the decision, checking every named field against the ledger's held ask.
The dispatcher refuses a decision for another attempt, another inputs digest,
one recorded beside the ask, or one an owner recovery superseded.

Controlled mirror alteration (an external effect class for `text_profile`) is
rejection/admission evidence of the gate only, never real external tool support.
"""

from contextlib import contextmanager
from types import MappingProxyType, SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.refs import EntityRef
from app.runtime import extension_attempt_transport as xt
from app.runtime import scheduler as sch
from app.runtime.ledger import (
    CommandConflict,
    ExecutionSpec,
    LedgerError,
    tool_inputs_digest,
)
from app.server import create_app
from app.services import run_approvals as ra
from app.tests.test_extension_attempt_transport import app_subject, text_input
from app.tests.test_tool_execution_binding import (  # noqa: F401 - fixture re-export
    SCOPE,
    committed_attempt,
    connects,
    dispatch_request,
    execution_of,
    gated_transport,
    unsent_attempt,
)
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers

GATE = "tool-gate"


def digest_of(*texts):
    inputs = [text_input(text) for text in texts]
    return tool_inputs_digest([item.declaration(index, len(inputs)).as_dict()
                               for index, item in enumerate(inputs)])


@contextmanager
def owner_run(tmp_path, monkeypatch):
    """A bootstrapped owner over HTTP, a run whose scheduler asked for the `tool-gate`,
    and a compiled graph whose writer binds `text_profile` as an external-family tool."""
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
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        subject, run = app_subject(app)
        subject.ledger.request_gate_approval(run.run_id, GATE, SCOPE)
        path = profile.base_path + f"api/v1/runs/{run.run_id}/approvals/executions"
        yield SimpleNamespace(app=app, client=client, csrf=csrf, profile=profile, subject=subject, run=run,
                              compiled=compiled, path=path,
                              approvals=app.state.first_party_exports["run-approvals.service"])


def ask(owner, execution_id, attempt_no=1, digest=None):
    return owner.subject.ledger.request_execution_approval(
        owner.run.run_id, GATE, SCOPE, execution_id, attempt_no,
        inputs_digest=digest_of(b"hello") if digest is None else digest)


def listed(owner):
    response = owner.client.get(owner.path, headers=headers(owner.profile))
    assert response.status_code == 200, response.text
    return response.json()["requests"]


def command_for(request, decision="approved", **changes):
    body = {"command_id": str(uuid4()), "decision": decision,
            **{name: request[name] for name in ("node_id", "approval_scope", "execution_id",
                                                "execution_node_id", "attempt_no", "inputs_digest")}}
    body.update(changes)
    return body


def post(owner, body, csrf=None, **extra_headers):
    return owner.client.post(owner.path, headers={**headers(owner.profile, csrf or owner.csrf), **extra_headers},
                             json=body)


def test_the_owner_sees_the_ledgers_ask_and_records_exactly_that_attempts_decision(tmp_path, monkeypatch):
    with owner_run(tmp_path, monkeypatch) as owner:
        assert listed(owner) == []
        visit = execution_of(owner.subject, owner.run, 0)
        asked = ask(owner, visit)
        [request] = listed(owner)
        # the ask carries its server-set expiry (T087 2026-09-25 scheduler slice)
        assert request == {"run_id": owner.run.run_id, "node_id": GATE, "approval_scope": SCOPE,
                           "execution_id": visit, "execution_node_id": "writer", "attempt_no": 1,
                           "inputs_digest": digest_of(b"hello"), "expires_at_ms": asked["expires_at_ms"],
                           "state": "pending", "approval_ref": None}
        assert owner.client.head(owner.path, headers=headers(owner.profile)).content == b""
        body = command_for(request)
        response = post(owner, body)
        assert response.status_code == 201, response.text
        receipt = response.json()
        assert receipt["state"] == "recorded" and receipt["decision"] == "approved"
        ref = EntityRef.from_dict(receipt["approval_ref"])
        # the record is the v2 decision of that attempt, carrying the ledger's ask and digest
        content = owner.subject.domain.get(ref).body["content"]
        assert content["schema_version"] == "run-approval-v2"
        assert (content["execution_id"], content["execution_node_id"], content["attempt_no"]) == (visit, "writer", 1)
        assert content["inputs_digest"] == digest_of(b"hello")
        assert ref.id == ra.execution_approval_identity(owner.run.run_id, GATE, SCOPE, visit, "writer", 1)
        [after] = listed(owner)
        assert after["state"] == "approved" and after["approval_ref"] == receipt["approval_ref"]
        # replay by command id returns the same receipt; changed content conflicts
        assert post(owner, body).json() == receipt
        for change in ({"command_id": str(uuid4())}, {"decision": "rejected"}):
            conflict = post(owner, {**body, **change})
            assert conflict.status_code == 409 and conflict.json()["code"] == "conflict"
        events = owner.client.get(receipt["links"]["events"], headers=headers(owner.profile)).json()["events"]
        assert sum(event["event_type"] == "approval.decided" for event in events) == 1


@pytest.mark.parametrize("change", [
    {"execution_id": "00000000-0000-4000-8000-00000000beef"},   # an execution the ledger never asked for
    {"execution_node_id": "publish"},                          # another executing node
    {"attempt_no": 2},                                         # a retry attempt nobody asked for
    {"node_id": "other-gate"},                                 # another gate
    {"approval_scope": "tool-other"},                          # another scope
    {"inputs_digest": "0" * 64},                               # other inputs than the ledger's ask
    {"inputs_digest": None},                                   # hiding the digest the ask carries
])
def test_a_forged_execution_attempt_or_digest_is_refused_before_any_write(tmp_path, monkeypatch, change):
    with owner_run(tmp_path, monkeypatch) as owner:
        ask(owner, execution_of(owner.subject, owner.run, 0))
        [request] = listed(owner)
        response = post(owner, command_for(request, **change))
        assert response.status_code == 400 and response.json()["code"] == "invalid_input", response.text
        assert listed(owner)[0]["state"] == "pending"


@pytest.mark.parametrize("change", [
    {"attempt_no": "1"}, {"attempt_no": True}, {"attempt_no": 0}, {"execution_id": "not-a-uuid"},
    {"inputs_digest": "ABC"}, {"decision": "maybe"}, {"extra": 1},
])
def test_the_command_grammar_is_closed(tmp_path, monkeypatch, change):
    with owner_run(tmp_path, monkeypatch) as owner:
        ask(owner, execution_of(owner.subject, owner.run, 0))
        [request] = listed(owner)
        response = post(owner, command_for(request, **change))
        assert response.status_code == 400 and response.json()["code"] == "invalid_input"
        missing = command_for(request)
        del missing["inputs_digest"]
        assert post(owner, missing).status_code == 400
        assert listed(owner)[0]["state"] == "pending"


def test_a_non_owner_a_missing_csrf_or_a_foreign_origin_is_refused(tmp_path, monkeypatch):
    with owner_run(tmp_path, monkeypatch) as owner:
        ask(owner, execution_of(owner.subject, owner.run, 0))
        [request] = listed(owner)
        body = command_for(request)
        assert post(owner, body, csrf="wrong").status_code in {401, 403}
        assert owner.client.post(owner.path, headers=headers(owner.profile), json=body).status_code in {401, 403}
        assert post(owner, body, Origin="https://evil.example").status_code == 403
        # no owner session at all (the cookie withheld): both routes refuse
        saved = dict(owner.client.cookies)
        owner.client.cookies.clear()
        assert owner.client.get(owner.path, headers=headers(owner.profile)).status_code == 401
        assert post(owner, body).status_code == 401
        owner.client.cookies.update(saved)
        assert listed(owner)[0]["state"] == "pending"


def test_a_retry_attempt_needs_its_own_ask_and_decision(tmp_path, monkeypatch, connects):  # noqa: F811
    with owner_run(tmp_path, monkeypatch) as owner:
        subject, run, compiled = owner.subject, owner.run, owner.compiled
        visit = execution_of(subject, run, 0)
        ask(owner, visit)
        first = EntityRef.from_dict(post(owner, command_for(listed(owner)[0])).json()["approval_ref"])
        transport_ = gated_transport(subject, owner.approvals, compiled, first)
        # attempt 1 closes unsent; the retry (attempt 2) is refused under attempt 1's decision
        unsent_attempt(subject, visit, 1)
        retry, permit, window = committed_attempt(subject, visit, 2, transport_)
        with pytest.raises(xt.ExtensionTransportError) as error:
            transport_(permit, dispatch_request(subject, run, compiled, retry, visit), window)
        assert (error.value.code, error.value.dispatch_effect) == ("transport_invalid", "definitely_not_sent")
        assert connects == []
        # the ledger asks again for attempt 2; the owner sees exactly that attempt pending
        ask(owner, visit, attempt_no=2)
        states = {(item["attempt_no"], item["state"]) for item in listed(owner)}
        assert states == {(1, "approved"), (2, "pending")}
        pending = next(item for item in listed(owner) if item["state"] == "pending")
        second = EntityRef.from_dict(post(owner, command_for(pending)).json()["approval_ref"])
        assert second != first
        with pytest.raises(xt.ExtensionTransportError) as error:
            gated_transport(subject, owner.approvals, compiled, second)(
                permit, dispatch_request(subject, run, compiled, retry, visit), window)
        assert error.value.dispatch_effect == "definitely_not_sent"
        assert connects == [1]  # the verification passed and the connection was attempted


def test_the_decision_is_bound_to_the_inputs_digest_of_the_ask(tmp_path, monkeypatch, connects):  # noqa: F811
    with owner_run(tmp_path, monkeypatch) as owner:
        subject, run, compiled = owner.subject, owner.run, owner.compiled
        visit = execution_of(subject, run, 0)
        # the ledger asked for other inputs than the ones the transport would declare
        ask(owner, visit, digest=digest_of(b"something else"))
        approved = EntityRef.from_dict(post(owner, command_for(listed(owner)[0])).json()["approval_ref"])
        transport_ = gated_transport(subject, owner.approvals, compiled, approved)
        attempt, permit, window = committed_attempt(subject, visit, 1, transport_)
        with pytest.raises(xt.ExtensionTransportError) as error:
            transport_(permit, dispatch_request(subject, run, compiled, attempt, visit), window)
        assert (error.value.code, error.value.dispatch_effect) == ("transport_invalid", "definitely_not_sent")
        assert connects == [] and subject.ledger.tool_calls_for_attempt(attempt.attempt_id) == []
        assert transport_.artifact_inputs_digest == digest_of(b"hello")


def test_a_decision_recorded_beside_the_ledgers_ask_is_refused_at_dispatch(tmp_path, monkeypatch, connects):  # noqa: F811
    from app.tests.test_web_owner_integration import bound_request

    with owner_run(tmp_path, monkeypatch) as owner:
        subject, run, compiled = owner.subject, owner.run, owner.compiled
        visit = execution_of(subject, run, 0)
        ask(owner, visit)
        # the in-process v2 command names no ask and no digest
        receipt = owner.approvals.record(bound_request(owner.app, owner.client, owner.profile, owner.csrf), {
            "schema_version": "run-approval-command-v2", "command_id": str(uuid4()), "run_id": run.run_id,
            "node_id": GATE, "approval_scope": SCOPE, "decision": "approved", "execution_id": visit,
            "execution_node_id": "writer", "attempt_no": 1})
        beside = EntityRef.from_dict(receipt["approval_ref"])
        transport_ = gated_transport(subject, owner.approvals, compiled, beside)
        attempt, permit, window = committed_attempt(subject, visit, 1, transport_)
        with pytest.raises(xt.ExtensionTransportError) as error:
            transport_(permit, dispatch_request(subject, run, compiled, attempt, visit), window)
        assert error.value.code == "transport_invalid" and connects == []
        # the route then conflicts: the attempt already holds a decision (another command)
        assert post(owner, command_for(listed(owner)[0])).status_code == 409


def test_a_decision_superseded_by_an_owner_recovery_is_refused_at_dispatch(tmp_path, monkeypatch, connects):  # noqa: F811
    with owner_run(tmp_path, monkeypatch) as owner:
        subject, run, compiled = owner.subject, owner.run, owner.compiled
        visit = execution_of(subject, run, 0)
        ask(owner, visit)
        approved = EntityRef.from_dict(post(owner, command_for(listed(owner)[0])).json()["approval_ref"])
        transport_ = gated_transport(subject, owner.approvals, compiled, approved)
        attempt, permit, window = committed_attempt(subject, visit, 1, transport_)
        # a later owner recovery (its barrier after the decision's event; the real
        # reconciliation is exercised in test_owner_sessions) supersedes the decision
        sequence = subject.domain.get(approved).body["content"]["event_sequence"]
        monkeypatch.setattr(ra, "_recovery_barrier", lambda db, vault_id: sequence + 1)
        assert listed(owner)[0]["state"] == "superseded"
        with pytest.raises(xt.ExtensionTransportError) as error:
            transport_(permit, dispatch_request(subject, run, compiled, attempt, visit), window)
        assert (error.value.code, error.value.dispatch_effect) == ("transport_invalid", "definitely_not_sent")
        assert connects == [] and subject.ledger.tool_calls_for_attempt(attempt.attempt_id) == []


def test_the_ledgers_ask_is_bound_to_its_gate_execution_and_attempt(tmp_path, monkeypatch):
    with owner_run(tmp_path, monkeypatch) as owner:
        ledger, run = owner.subject.ledger, owner.run
        visit = execution_of(owner.subject, run, 0)
        with pytest.raises(LedgerError, match="gate request"):
            ledger.request_execution_approval(run.run_id, "other-gate", SCOPE, visit, 1)
        with pytest.raises(LedgerError, match="execution"):
            ledger.request_execution_approval(run.run_id, GATE, SCOPE, str(uuid4()), 1)
        with pytest.raises(LedgerError, match="attempt number"):
            ledger.request_execution_approval(run.run_id, GATE, SCOPE, visit, 2)
        for bad in ({"attempt_no": 0}, {"attempt_no": True}, {"inputs_digest": "x"}):
            arguments = {"attempt_no": 1, "inputs_digest": None, **bad}
            with pytest.raises(ValueError):
                ledger.request_execution_approval(run.run_id, GATE, SCOPE, visit, arguments["attempt_no"],
                                                  inputs_digest=arguments["inputs_digest"])
        # an execution of another run of the same vault
        other = sch.execution_identity(str(uuid4()), "writer", 0)
        with pytest.raises(LedgerError):
            ledger.request_execution_approval(run.run_id, GATE, SCOPE, other, 1)
        first = ask(owner, visit)
        assert first["execution_node_id"] == "writer" and first["requested"] is True
        assert ask(owner, visit) == first  # the same ask replays
        with pytest.raises(CommandConflict):  # one attempt, one digest
            ask(owner, visit, digest=digest_of(b"else"))
        assert ledger.execution_approval_requested(run.run_id, GATE, SCOPE, visit, 1)["inputs_digest"] \
            == digest_of(b"hello")
        assert ledger.execution_approval_requested(run.run_id, GATE, SCOPE, visit, 2) is None
        # the executing node comes from the ledger's execution row, never the caller
        publish = sch.execution_identity(run.run_id, "publish", 0)
        ledger.create_execution(str(uuid4()), ExecutionSpec(publish, run.run_id, "publish", str(uuid4()), (0,), ()))
        assert ledger.request_execution_approval(run.run_id, GATE, SCOPE, publish, 1)["execution_node_id"] \
            == "publish"
