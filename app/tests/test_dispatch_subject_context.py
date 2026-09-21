"""Legacy node-dispatch context characterization and resolver regressions."""

import sqlite3
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest

from app.domain.refs import canonical_json
from app.domain.store import BlobRef, DomainStore
from app.runtime.budgets import BudgetDispatchRequest, BudgetUsage
from app.runtime import ledger as ledger_module
from app.runtime.ledger import (
    AttemptSpec,
    CorruptLedger,
    DispatchBlocked,
    ExecutionSpec,
    LedgerError,
    OwnerIdentity,
    ResultObservation,
    RunSpec,
    RuntimeLedger,
)
from app.runtime.worker_response_capture import (
    _lookup_response_capture,
    _response_fingerprint,
)
from app.tests.test_runtime_budget_dispatch import identifier, immutable, opened
from app.tests.test_worker_response_capture import PAYLOAD, exchange
from app.tests.test_worker_coordinator import build_subject


def _budgeted_attempt(subject, *, mode="live", parent_execution_ids=()):
    run = RunSpec(
        identifier(),
        subject.refs.work,
        subject.refs.environment,
        subject.refs.consent,
        mode,
        subject.refs.budget,
        subject.budget_session_id,
        subject.refs.manifest,
    )
    subject.ledger.create_run(identifier(), run)
    execution = ExecutionSpec(
        identifier(),
        run.run_id,
        "writer",
        identifier(),
        (0,),
        parent_execution_ids,
    )
    subject.ledger.create_execution(identifier(), execution)
    owner = OwnerIdentity(identifier(), 4321, 900, identifier())
    attempt = AttemptSpec(
        identifier(),
        execution.execution_id,
        1,
        subject.refs.envelope,
        subject.refs.profile,
        subject.refs.budget,
        identifier(),
        "effect:" + identifier(),
        owner,
        10_000,
    )
    reserved = subject.ledger.reserve_attempt(
        identifier(), attempt, lease_duration_ms=1_000
    )
    request = BudgetDispatchRequest.create(
        session_id=subject.budget_session_id,
        request_id=attempt.reservation_id,
        policy_ref=subject.refs.budget,
        model_calls=1,
        tool_calls=0,
        node_visits=1,
        loop_rounds=0,
        output_bytes=100,
        candidates=0,
        api_microunits=None,
    )
    return run, execution, owner, attempt, reserved, request


def _row(path, sql, parameters=()):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        value = db.execute(sql, parameters).fetchone()
        assert value is not None
        return dict(value)


def _assert_canonical_blob(row, field, expected):
    encoded = canonical_json(expected)
    assert bytes(row[field]) == encoded
    assert row[f"{field}_digest"] == sha256(encoded).hexdigest()


def test_legacy_node_dispatch_bytes_snapshots_and_settlement_receipt_are_stable(tmp_path):
    subject = opened(tmp_path)
    run, execution, owner, attempt, reserved, request = _budgeted_attempt(subject)

    run_row = _row(subject.legacy.path, "SELECT * FROM runtime_runs WHERE id=?", (run.run_id,))
    execution_row = _row(
        subject.legacy.path,
        "SELECT * FROM runtime_node_executions WHERE id=?",
        (execution.execution_id,),
    )
    attempt_row = _row(
        subject.legacy.path,
        "SELECT * FROM runtime_attempts WHERE id=?",
        (attempt.attempt_id,),
    )
    _assert_canonical_blob(run_row, "spec", run.as_dict())
    _assert_canonical_blob(execution_row, "spec", execution.as_dict())
    _assert_canonical_blob(attempt_row, "spec", attempt.as_dict())
    assert set(subject.ledger.get_run(run.run_id)) == {
        "object_ref", "spec", "phase", "revision", "created_at_ms",
    }
    assert set(subject.ledger.get_execution(execution.execution_id)) == {
        "object_ref", "spec", "phase", "revision", "created_at_ms",
    }
    assert set(reserved) == {
        "object_ref", "spec", "phase", "dispatch_gate", "send_finality",
        "cancel_state", "recovery_state", "terminal_outcome", "revision",
        "lease_owner", "lease_fence", "lease_expires_at_ms", "reservation_ref",
        "dispatch_blocked_at_ms", "send_intent_at_ms", "local_transport_closed_at_ms",
        "owned_process_exit", "remote_terminal_observed", "usage_finality",
        "accepted_observation_id", "created_at_ms", "updated_at_ms",
    }

    send_command = identifier()
    permit = subject.ledger.commit_budgeted_send_intent(
        send_command,
        attempt.attempt_id,
        owner,
        expected_revision=1,
        budget_book=subject.book,
        budget_request=request,
        principal=subject.principal,
        grant=subject.grant,
    )
    command = _row(
        subject.legacy.path,
        "SELECT * FROM runtime_commands WHERE command_id=?",
        (send_command,),
    )
    _assert_canonical_blob(command, "payload", {
        "attempt_id": attempt.attempt_id,
        "owner": owner.as_dict(),
        "expected_revision": 1,
        "budget_request": request.as_dict(),
        "principal_id": subject.principal.id,
        "grant_id": subject.grant.id,
    })
    _assert_canonical_blob(command, "result", {
        "intent_committed": True,
        "attempt_id": attempt.attempt_id,
        "permit_id": permit.permit_id,
        "revision": 2,
    })
    assert subject.ledger.commit_budgeted_send_intent(
        send_command,
        attempt.attempt_id,
        owner,
        expected_revision=1,
        budget_book=subject.book,
        budget_request=request,
        principal=subject.principal,
        grant=subject.grant,
    ) is None
    assert subject.ledger.pending_permit_count == 1

    result_ref = immutable(subject.domain, subject.domain.roots(), "artifact")
    observation = ResultObservation(
        identifier(),
        attempt.attempt_id,
        "succeeded",
        result_ref,
        "final",
        "succeeded",
        "provider_terminal",
    )
    usage = BudgetUsage.create(
        model_calls=1,
        tool_calls=0,
        node_visits=1,
        loop_rounds=0,
        output_bytes=80,
        candidates=0,
        api_microunits=None,
    )
    settle_command = identifier()
    outcome = subject.ledger.accept_result_and_settle(
        settle_command, observation, budget_book=subject.book, usage=usage
    )
    terminal = subject.ledger.get_attempt(attempt.attempt_id)
    settle_row = _row(
        subject.legacy.path,
        "SELECT * FROM runtime_commands WHERE command_id=?",
        (settle_command,),
    )
    _assert_canonical_blob(settle_row, "payload", {
        "observation": observation.as_dict(),
        "usage": usage.as_dict(),
    })
    _assert_canonical_blob(settle_row, "result", {
        "classification": "accepted",
        "observation_id": observation.observation_id,
        "attempt": terminal,
        "settlement": {
            "request_id": request.request_id,
            "state": "finalized",
            "usage_finality": "known",
        },
    })
    assert outcome["attempt"] == terminal

    reopened = RuntimeLedger(
        DomainStore(subject.legacy), clock_ms=lambda: subject.ledger_clock[0]
    )
    assert reopened.get_run(run.run_id) == subject.ledger.get_run(run.run_id)
    assert reopened.get_execution(execution.execution_id) == subject.ledger.get_execution(
        execution.execution_id
    )
    assert reopened.get_attempt(attempt.attempt_id) == terminal


@pytest.mark.parametrize("mode", ("replay", "snapshot"))
def test_legacy_read_only_modes_and_exact_replay_never_issue_another_permit(tmp_path, mode):
    subject = opened(tmp_path)
    _run, _execution, owner, attempt, before, request = _budgeted_attempt(
        subject, mode=mode
    )
    command_id = identifier()
    with pytest.raises(DispatchBlocked, match=mode):
        subject.ledger.commit_budgeted_send_intent(
            command_id,
            attempt.attempt_id,
            owner,
            expected_revision=1,
            budget_book=subject.book,
            budget_request=request,
            principal=subject.principal,
            grant=subject.grant,
        )
    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert subject.ledger.pending_permit_count == 0


def test_original_send_capture_fingerprint_survives_lease_fence_change_and_reopen(
    tmp_path, monkeypatch
):
    value = build_subject(tmp_path)

    def change_lease_after_original_send():
        value.ledger.renew_lease(
            identifier(),
            value.permit.attempt_id,
            value.permit.owner,
            expected_revision=2,
            lease_duration_ms=3_000,
        )

    response = exchange(value, monkeypatch, before_response=change_lease_after_original_send)
    receipt = response._capture_receipt
    fingerprint = _response_fingerprint(value.coordinator, value.permit, response)
    assert receipt.fingerprint == fingerprint
    capture_ref = value.coordinator.capture_response(value.permit, response)
    capture = value.domain.get(capture_ref)
    assert capture.body["content"]["command_id"] == value.permit.command_id
    assert capture.body["content"]["lease_fence"] == value.permit.lease_fence
    captured = [
        entry for entry in value.ledger.attempt_journal(value.permit.attempt_id)
        if entry["transition"] == "response_captured"
    ]
    assert [entry["payload"]["classification"] for entry in captured] == ["quarantined"]

    reopened = RuntimeLedger(DomainStore(value.legacy), clock_ms=lambda: 1_000)
    reopened.reconcile_startup(identifier(), observed_owners={})
    assert _lookup_response_capture(reopened, value.permit.command_id) == capture_ref
    assert value.domain.read_blob(
        BlobRef.from_dict(capture.body["content"]["payload_blob"]),
        purpose="operational",
    ) == PAYLOAD


def test_resolver_returns_a_frozen_exact_node_context_inside_the_owned_transaction(tmp_path):
    subject = opened(tmp_path)
    run, execution, _owner, attempt, _reserved, _request = _budgeted_attempt(subject)

    with subject.ledger._transaction() as db:
        context = subject.ledger._resolve_node_dispatch_context(db, attempt)
        compatible = subject.ledger._run_spec_for_attempt(db, attempt)

    assert type(context) is ledger_module._NodeDispatchContext
    assert context.execution_spec == execution
    assert context.run_spec == run
    assert context.run_phase == "created"
    assert compatible == context.run_spec
    with pytest.raises(FrozenInstanceError):
        context.run_phase = "cancelled"
    subject.ledger.cancel_run(identifier(), run.run_id)
    with subject.ledger._transaction() as db:
        cancelled = subject.ledger._resolve_node_dispatch_context(db, attempt)
        with pytest.raises(TypeError, match="exact AttemptSpec"):
            subject.ledger._resolve_node_dispatch_context(db, attempt.as_dict())
    assert cancelled.run_phase == "cancelled"
    assert cancelled.run_spec == run

    raw = sqlite3.connect(subject.legacy.path)
    try:
        raw.row_factory = sqlite3.Row
        with pytest.raises(LedgerError, match="active transaction"):
            subject.ledger._resolve_node_dispatch_context(raw, attempt)
    finally:
        raw.close()


@pytest.mark.parametrize(
    "damage, message",
    (
        ("execution_missing", "Attempt execution is missing"),
        ("execution_snapshot", "Execution row does not match"),
        ("run_missing", "Attempt run is missing"),
        ("run_snapshot", "Runtime run row does not match"),
        ("run_ref", "reference index"),
    ),
)
def test_resolver_denies_missing_or_corrupt_execution_run_and_reference_rows(
    tmp_path, damage, message
):
    subject = opened(tmp_path)
    run, execution, _owner, attempt, _reserved, _request = _budgeted_attempt(subject)
    with sqlite3.connect(subject.legacy.path) as db:
        if damage == "execution_missing":
            db.execute(
                "DELETE FROM runtime_node_executions WHERE id=?",
                (execution.execution_id,),
            )
        elif damage == "execution_snapshot":
            db.execute(
                "UPDATE runtime_node_executions SET node_id='changed' WHERE id=?",
                (execution.execution_id,),
            )
        elif damage == "run_missing":
            db.execute("DELETE FROM runtime_runs WHERE id=?", (run.run_id,))
        elif damage == "run_snapshot":
            changed = replace(run, run_id=identifier())
            encoded = canonical_json(changed.as_dict())
            db.execute(
                "UPDATE runtime_runs SET spec=?,spec_digest=? WHERE id=?",
                (encoded, sha256(encoded).hexdigest(), run.run_id),
            )
        else:
            db.execute(
                "DELETE FROM runtime_run_refs WHERE run_id=? AND role='manifest'",
                (run.run_id,),
            )

    with subject.ledger._transaction() as db:
        with pytest.raises(CorruptLedger, match=message):
            subject.ledger._resolve_node_dispatch_context(db, attempt)


def test_resolver_validates_same_run_parent_targets_in_the_same_vault(tmp_path):
    subject = opened(tmp_path)
    run = RunSpec(
        identifier(), subject.refs.work, subject.refs.environment, subject.refs.consent,
        "live", subject.refs.budget, subject.budget_session_id, subject.refs.manifest,
    )
    subject.ledger.create_run(identifier(), run)
    parent = ExecutionSpec(identifier(), run.run_id, "parent", identifier(), (), ())
    subject.ledger.create_execution(identifier(), parent)
    child = ExecutionSpec(
        identifier(), run.run_id, "child", identifier(), (), (parent.execution_id,)
    )
    subject.ledger.create_execution(identifier(), child)
    owner = OwnerIdentity(identifier(), 4321, 900, identifier())
    attempt = AttemptSpec(
        identifier(), child.execution_id, 1, subject.refs.envelope, subject.refs.profile,
        subject.refs.budget, identifier(), "effect:" + identifier(), owner, 10_000,
    )
    subject.ledger.reserve_attempt(identifier(), attempt, lease_duration_ms=1_000)

    with subject.ledger._transaction() as db:
        assert subject.ledger._resolve_node_dispatch_context(db, attempt).execution_spec == child

    other_run = replace(run, run_id=identifier())
    subject.ledger.create_run(identifier(), other_run)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute(
            "UPDATE runtime_node_executions SET run_id=? WHERE id=?",
            (other_run.run_id, parent.execution_id),
        )
    with subject.ledger._transaction() as db:
        with pytest.raises(CorruptLedger, match="cross-run"):
            subject.ledger._resolve_node_dispatch_context(db, attempt)


def test_resolver_and_send_deny_wrong_budget_policy_or_session_without_mutation(tmp_path):
    subject = opened(tmp_path)
    _run, _execution, owner, attempt, before, request = _budgeted_attempt(subject)
    other_policy_ref = immutable(
        subject.domain,
        subject.domain.roots(),
        "budget_policy",
        content=subject.policy.domain_content(),
    )
    with subject.ledger._transaction() as db:
        with pytest.raises(CorruptLedger, match="budget policy"):
            subject.ledger._resolve_node_dispatch_context(
                db, replace(attempt, budget_policy_ref=other_policy_ref)
            )

    wrong_session = BudgetDispatchRequest.create(
        session_id=identifier(),
        request_id=request.request_id,
        policy_ref=request.policy_ref,
        model_calls=1,
        tool_calls=0,
        node_visits=1,
        loop_rounds=0,
        output_bytes=100,
        candidates=0,
        api_microunits=None,
    )
    with pytest.raises(LedgerError, match="frozen run budget session"):
        subject.ledger.commit_budgeted_send_intent(
            identifier(),
            attempt.attempt_id,
            owner,
            expected_revision=1,
            budget_book=subject.book,
            budget_request=wrong_session,
            principal=subject.principal,
            grant=subject.grant,
        )
    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert subject.ledger.pending_permit_count == 0
