"""Atomic budget plus runtime send-intent tests; no provider is invoked."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.permissions import Grant, Principal
from app.domain.schemas import Actor, ImmutableRecord
from app.domain.store import DomainStore
from app.runtime import ledger as ledger_module
from app.runtime.budgets import (
    BudgetBook,
    BudgetDispatchRequest,
    BudgetExceeded,
    BudgetPolicy,
    ReservationConflict,
)
from app.runtime.ledger import (
    AttemptSpec,
    ConsumedDispatchWindow,
    CorruptLedger,
    DispatchBlocked,
    ExecutionSpec,
    LedgerError,
    OwnerIdentity,
    RevisionConflict,
    RunSpec,
    RuntimeLedger,
)
from app.storage import Store


STAMP = "2026-09-07T00:00:00.000000Z"


def identifier():
    return str(uuid4())


def immutable(domain, roots, kind, *, content=None):
    record = ImmutableRecord.create(
        kind=kind,
        id=identifier(),
        version=1,
        created_at_utc=STAMP,
        actor_ref=roots.actor,
        parent_refs=(),
        purpose="operational",
        access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"fixture": kind} if content is None else content,
    )
    domain.put(record)
    return record.ref


def opened(tmp_path, *, policy_content=True, max_model_calls=3):
    legacy = Store(tmp_path / "vault")
    domain = DomainStore(legacy)
    roots = domain.initialize_vault()
    policy = BudgetPolicy.create(
        profile="execution",
        provider_mode="subscription",
        max_model_calls=max_model_calls,
        max_tool_calls=5,
        max_node_visits=7,
        max_loop_rounds=2,
        max_output_bytes=1_000,
        max_concurrency=2,
        max_wall_seconds=60,
        max_candidates=1,
    )
    budget_ref = immutable(
        domain,
        roots,
        "budget_policy",
        content=policy.domain_content() if policy_content else {"fixture": "wrong-policy"},
    )
    refs = SimpleNamespace(
        work=immutable(domain, roots, "work_revision"),
        environment=immutable(domain, roots, "environment"),
        consent=immutable(domain, roots, "run_consent"),
        budget=budget_ref,
        manifest=immutable(domain, roots, "run_manifest"),
        envelope=immutable(domain, roots, "execution_envelope"),
        profile=immutable(domain, roots, "runtime_profile"),
    )
    budget_clock = [100]
    book = BudgetBook(legacy, clock=lambda: budget_clock[0])
    budget_session_id = identifier()
    book.start(budget_session_id, policy)
    ledger_clock = [1_000]
    ledger = RuntimeLedger(domain, clock_ms=lambda: ledger_clock[0])
    ledger.reconcile_startup(identifier(), observed_owners={})
    principal = Principal(
        identifier(),
        Actor(identifier(), "test_actor", "test_fixture"),
        "runtime",
        "operational",
        10_000,
    )
    grant = Grant(
        identifier(),
        identifier(),
        principal.id,
        refs.envelope,
        "read",
        "operational",
        None,
        10_000,
        1,
    )
    return SimpleNamespace(
        legacy=legacy,
        domain=domain,
        refs=refs,
        policy=policy,
        book=book,
        budget_session_id=budget_session_id,
        budget_clock=budget_clock,
        ledger=ledger,
        ledger_clock=ledger_clock,
        principal=principal,
        grant=grant,
    )


def prepare(subject, *, reservation_id=None, execution_id=None):
    run = RunSpec(
        identifier(), subject.refs.work, subject.refs.environment, subject.refs.consent,
        "live", subject.refs.budget, subject.budget_session_id, subject.refs.manifest,
    )
    subject.ledger.create_run(identifier(), run)
    execution = ExecutionSpec(
        execution_id or identifier(), run.run_id, "writer", identifier(), (0,), (),
    )
    subject.ledger.create_execution(identifier(), execution)
    owner = OwnerIdentity(identifier(), 4321, 900, identifier())
    attempt = AttemptSpec(
        identifier(), execution.execution_id, 1, subject.refs.envelope,
        subject.refs.profile, subject.refs.budget, reservation_id or identifier(),
        "effect:" + identifier(), owner, 10_000,
    )
    before = subject.ledger.reserve_attempt(identifier(), attempt, lease_duration_ms=1_000)
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
    return owner, attempt, request, before


def commit(subject, owner, attempt, request, *, command_id=None):
    return subject.ledger.commit_budgeted_send_intent(
        command_id or identifier(),
        attempt.attempt_id,
        owner,
        expected_revision=1,
        budget_book=subject.book,
        budget_request=request,
        principal=subject.principal,
        grant=subject.grant,
    )


def budget_row(subject, request_id):
    with sqlite3.connect(subject.legacy.path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM runtime_budget_reservations WHERE request_id=?", (request_id,)
        ).fetchone()
        return None if row is None else dict(row)


def test_atomic_commit_reserves_budget_and_dispatch_intent_together(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)

    permit = commit(subject, owner, attempt, request)

    assert permit.reservation_id == request.request_id
    assert budget_row(subject, request.request_id)["state"] == "dispatched"
    assert subject.ledger.get_attempt(attempt.attempt_id)["phase"] == "send_intent"
    assert subject.book.status(subject.budget_session_id)["active_reservations"] == 1


def test_budget_rejection_leaves_attempt_and_command_unmodified(tmp_path):
    subject = opened(tmp_path, max_model_calls=1)
    owner, attempt, request, before = prepare(subject)
    oversized = BudgetDispatchRequest.create(
        session_id=request.session_id,
        request_id=request.request_id,
        policy_ref=request.policy_ref,
        model_calls=2,
        tool_calls=0,
        node_visits=1,
        loop_rounds=0,
        output_bytes=100,
        candidates=0,
        api_microunits=None,
    )

    with pytest.raises(BudgetExceeded):
        commit(subject, owner, attempt, oversized)

    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert budget_row(subject, request.request_id) is None


def test_ledger_event_failure_rolls_back_fresh_budget_reservation(tmp_path, monkeypatch):
    subject = opened(tmp_path)
    owner, attempt, request, before = prepare(subject)

    def fail_event(*_args, **_kwargs):
        raise sqlite3.IntegrityError("synthetic atomic dispatch failure")

    monkeypatch.setattr(subject.ledger, "_event", fail_event)

    with pytest.raises(sqlite3.IntegrityError, match="synthetic atomic dispatch failure"):
        commit(subject, owner, attempt, request)

    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert budget_row(subject, request.request_id) is None
    assert subject.ledger.pending_permit_count == 0


def test_unexpected_trigger_cannot_delete_budget_and_still_issue_permit(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, before = prepare(subject)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute(
            """CREATE TRIGGER delete_dispatch_budget
            AFTER UPDATE OF phase ON runtime_attempts
            WHEN NEW.phase='send_intent'
            BEGIN
                DELETE FROM runtime_budget_reservations
                WHERE request_id=NEW.reservation_id;
            END"""
        )

    with pytest.raises(CorruptLedger, match="trigger"):
        commit(subject, owner, attempt, request)

    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert budget_row(subject, request.request_id) is None
    assert subject.ledger.pending_permit_count == 0


def test_uppercase_table_trigger_cannot_extend_dispatch_lease(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, before = prepare(subject)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute(
            """CREATE TRIGGER UPPERCASE_LEASE_EXTENDER
            AFTER UPDATE OF phase ON RUNTIME_ATTEMPTS
            WHEN NEW.phase='send_intent'
            BEGIN
                UPDATE runtime_attempts SET lease_expires_at_ms=9000
                WHERE id=NEW.id;
            END"""
        )

    with pytest.raises(CorruptLedger, match="trigger"):
        commit(subject, owner, attempt, request)

    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert budget_row(subject, request.request_id) is None
    assert subject.ledger.pending_permit_count == 0


def test_replay_never_reissues_permit_or_budget_transition(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    command_id = identifier()
    first = commit(subject, owner, attempt, request, command_id=command_id)

    assert commit(subject, owner, attempt, request, command_id=command_id) is None
    with sqlite3.connect(subject.legacy.path) as db:
        budget_events = db.execute(
            "SELECT kind FROM runtime_budget_audit WHERE request_id=? ORDER BY sequence",
            (request.request_id,),
        ).fetchall()
        dispatch_events = db.execute(
            "SELECT count(*) FROM runtime_public_events WHERE event_type='attempt.dispatched'"
        ).fetchone()[0]
    assert budget_events == [("reserved",), ("dispatched",)]
    assert dispatch_events == 1
    assert subject.ledger.consume_dispatch_permit(
        first, budget_book=subject.book
    ) is first


def test_permit_rejects_replacement_grant_for_same_envelope(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    permit = commit(subject, owner, attempt, request)
    replacement = Grant(
        identifier(),
        permit.grant.issuer_id,
        permit.principal.id,
        permit.envelope_ref,
        "read",
        "operational",
        None,
        permit.grant.expires_at,
        permit.grant.policy_revision,
    )

    object.__setattr__(permit, "grant", replacement)

    with pytest.raises(DispatchBlocked, match="authorization binding changed"):
        subject.ledger.consume_dispatch_permit(permit, budget_book=subject.book)
    assert subject.ledger.pending_permit_count == 1


def test_consumed_window_preserves_clock_domains_and_never_extends(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    permit = commit(subject, owner, attempt, request)
    assert permit.budget_deadline_epoch_seconds == 160

    subject.ledger_clock[0] = 1_200
    subject.budget_clock[0] = 110
    window = subject.ledger.consume_dispatch_permit_window(
        permit, budget_book=subject.book
    )

    assert type(window) is ConsumedDispatchWindow
    assert window.permit is permit
    assert window.runtime_remaining_ms == 799
    assert window.budget_remaining_ms == 49_000
    assert window.effective_remaining_ms == 799
    assert type(window.anchor_monotonic) is float
    assert window.deadline_end_monotonic == pytest.approx(
        window.anchor_monotonic + 0.799
    )
    with pytest.raises(DispatchBlocked, match="absent or changed"):
        subject.ledger.consume_dispatch_permit_window(
            permit, budget_book=subject.book
        )


def test_consumed_window_does_not_add_validation_latency_back(
    tmp_path,
    monkeypatch,
):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    permit = commit(subject, owner, attempt, request)
    subject.ledger_clock[0] = 1_200
    subject.budget_clock[0] = 110
    monotonic = [50.0]
    monkeypatch.setattr(ledger_module.time, "monotonic", lambda: monotonic[0])
    original = subject.ledger._assert_permit_attempt_state

    def validate_after_delay(db, value):
        result = original(db, value)
        monotonic[0] = 55.0
        return result

    monkeypatch.setattr(
        subject.ledger,
        "_assert_permit_attempt_state",
        validate_after_delay,
    )

    window = subject.ledger.consume_dispatch_permit_window(
        permit, budget_book=subject.book
    )

    assert window.anchor_monotonic == 50.0
    assert window.deadline_end_monotonic == pytest.approx(50.799)
    assert window.deadline_end_monotonic < monotonic[0]


def test_permit_budget_deadline_drift_is_rejected_after_consumption(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    permit = commit(subject, owner, attempt, request)
    object.__setattr__(
        permit,
        "budget_deadline_epoch_seconds",
        permit.budget_deadline_epoch_seconds + 1,
    )

    with pytest.raises(DispatchBlocked, match="budget binding"):
        subject.ledger.consume_dispatch_permit_window(
            permit, budget_book=subject.book
        )
    assert subject.ledger.pending_permit_count == 0


def test_exact_budget_policy_record_is_required_before_any_reservation(tmp_path):
    subject = opened(tmp_path, policy_content=False)
    owner, attempt, request, before = prepare(subject)

    with pytest.raises(CorruptLedger, match="budget policy"):
        commit(subject, owner, attempt, request)

    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert budget_row(subject, request.request_id) is None


def test_request_must_bind_attempt_reservation_and_policy(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, before = prepare(subject)
    wrong_id = BudgetDispatchRequest.create(
        session_id=request.session_id,
        request_id=identifier(),
        policy_ref=request.policy_ref,
        model_calls=1,
        tool_calls=0,
        node_visits=1,
        loop_rounds=0,
        output_bytes=100,
        candidates=0,
        api_microunits=None,
    )

    with pytest.raises(LedgerError, match="reservation"):
        commit(subject, owner, attempt, wrong_id)

    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert budget_row(subject, wrong_id.request_id) is None


def test_dispatched_reservation_cannot_authorize_a_second_attempt(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    commit(subject, owner, attempt, request)
    second_owner, second_attempt, second_request, before = prepare(
        subject, reservation_id=request.request_id
    )

    with pytest.raises(ReservationConflict):
        commit(subject, second_owner, second_attempt, second_request)

    assert subject.ledger.get_attempt(second_attempt.attempt_id) == before


def test_same_run_cannot_reset_its_budget_by_selecting_a_new_session(tmp_path):
    subject = opened(tmp_path, max_model_calls=1)
    owner, attempt, request, _ = prepare(subject)
    commit(subject, owner, attempt, request)
    run_id = subject.ledger.get_execution(attempt.execution_id)["spec"]["run_id"]
    replacement_session = identifier()
    subject.book.start(replacement_session, subject.policy)
    execution = ExecutionSpec(
        identifier(), run_id, "second", identifier(), (0,), (),
    )
    subject.ledger.create_execution(identifier(), execution)
    second_owner = OwnerIdentity(identifier(), 4322, 900, identifier())
    second_attempt = AttemptSpec(
        identifier(), execution.execution_id, 1, subject.refs.envelope,
        subject.refs.profile, subject.refs.budget, identifier(),
        "effect:" + identifier(), second_owner, 10_000,
    )
    before = subject.ledger.reserve_attempt(
        identifier(), second_attempt, lease_duration_ms=1_000
    )
    second_request = BudgetDispatchRequest.create(
        session_id=replacement_session,
        request_id=second_attempt.reservation_id,
        policy_ref=second_attempt.budget_policy_ref,
        model_calls=1,
        tool_calls=0,
        node_visits=1,
        loop_rounds=0,
        output_bytes=100,
        candidates=0,
        api_microunits=None,
    )

    with pytest.raises(LedgerError, match="frozen run budget session"):
        commit(subject, second_owner, second_attempt, second_request)

    assert subject.ledger.get_attempt(second_attempt.attempt_id) == before
    assert budget_row(subject, second_request.request_id) is None


def test_concurrent_atomic_commit_has_one_permit_and_one_budget_dispatch(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)

    def worker(_):
        try:
            return commit(subject, owner, attempt, request)
        except RevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))

    assert len([value for value in results if value is not None]) == 1
    assert budget_row(subject, request.request_id)["state"] == "dispatched"
    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute(
            "SELECT count(*) FROM runtime_budget_audit WHERE request_id=? AND kind='dispatched'",
            (request.request_id,),
        ).fetchone()[0] == 1


def test_budget_book_from_another_vault_is_rejected(tmp_path):
    subject = opened(tmp_path / "primary")
    owner, attempt, request, before = prepare(subject)
    other_legacy = Store(tmp_path / "other" / "vault")
    other_book = BudgetBook(other_legacy, clock=lambda: 100)

    with pytest.raises(LedgerError, match="same vault"):
        subject.ledger.commit_budgeted_send_intent(
            identifier(), attempt.attempt_id, owner, expected_revision=1,
            budget_book=other_book, budget_request=request,
        )

    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert budget_row(subject, request.request_id) is None


def test_budgeted_permit_requires_its_book_and_rechecks_wall_deadline(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    permit = commit(subject, owner, attempt, request)

    with pytest.raises(DispatchBlocked, match="BudgetBook"):
        subject.ledger.consume_dispatch_permit(permit)

    subject.budget_clock[0] = 160
    with pytest.raises(BudgetExceeded, match="wall-time"):
        subject.ledger.consume_dispatch_permit(permit, budget_book=subject.book)


def test_budgeted_permit_rejects_a_substitute_book_for_the_same_path(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    permit = commit(subject, owner, attempt, request)
    substitute = BudgetBook(subject.legacy, clock=lambda: subject.budget_clock[0])

    with pytest.raises(DispatchBlocked, match="budget owner"):
        subject.ledger.consume_dispatch_permit(permit, budget_book=substitute)

    assert subject.ledger.consume_dispatch_permit(
        permit, budget_book=subject.book
    ) is permit
