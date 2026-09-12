"""Failure-first contract for the T016 root command transaction.

The tests use only temporary SQLite vaults and synthetic records.  A successful
transaction may expose one process-local dispatch permit, but no provider, tool,
network, credential store, or user database is touched here.
"""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import importlib
import sqlite3
from threading import Event, Thread, current_thread
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.commands import (
    ArgField,
    CommandConflict,
    CommandDefinition,
    CommandInvalid,
    CommandRegistry,
)
from app.api.session import LocalSessionAuthority
from app.domain.permissions import AccessDenied, create_persistent_policy
from app.domain.refs import EntityRef, canonical_json
from app.domain.schemas import Actor, ImmutableRecord
from app.domain.store import DomainStore, _writer
from app.runtime.budgets import BudgetBook, BudgetDispatchRequest, BudgetPolicy
from app.runtime.ledger import (
    AttemptSpec,
    DispatchBlocked,
    DispatchPermit,
    ExecutionSpec,
    OwnerIdentity,
    RunSpec,
    RuntimeLedger,
)
from app.storage import Store
from app.workers import broker


STAMP = "2026-09-08T00:00:00.000000Z"
ORIGIN = "http://127.0.0.1:4193"
TRANSACTION_STAGES = (
    "command_intent",
    "permission_verified",
    "budget_and_send_intent",
    "public_event",
    "command_receipt",
)


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
    return record


def registry():
    return CommandRegistry((
        CommandDefinition(
            "attempt.dispatch",
            target_kind="attempt",
            revision="required",
            target_hash="required",
            arguments=(
                ArgField("grant_id", "uuid"),
                ArgField("resource_sha256", "sha256"),
                ArgField("budget_request_sha256", "sha256"),
            ),
        ),
    ))


def authenticated_requests(clock):
    authority = LocalSessionAuthority(
        {"127.0.0.1:4193"}, clock=lambda: clock[0],
        session_ttl_seconds=900,
    )
    launch = authority.mint_bootstrap()
    exchange = authority.exchange_bootstrap(
        launch.capability,
        method="POST",
        host="127.0.0.1:4193",
        origin=ORIGIN,
        sec_fetch_site="same-origin",
    )
    post = authority.authenticate_request(
        method="POST",
        host="127.0.0.1:4193",
        origin=ORIGIN,
        sec_fetch_site="same-origin",
        cookie_header=exchange.cookie_pair,
        csrf_token=exchange.csrf_token,
    )
    read = authority.authenticate_request(
        method="GET",
        host="127.0.0.1:4193",
        origin=None,
        sec_fetch_site="same-origin",
        cookie_header=exchange.cookie_pair,
        csrf_token=None,
    )
    return authority, exchange, post, read


@pytest.fixture
def subject(tmp_path):
    legacy = Store(tmp_path / "vault")
    domain = DomainStore(legacy)
    roots = domain.initialize_vault()

    session_clock = [1_000]
    authority, exchange, post_request, read_request = authenticated_requests(session_clock)
    permission_clock = [1_000]
    host, gate = create_persistent_policy(
        domain,
        authenticate_session=authority.authenticate_bound,
        verify_projection=lambda _value: False,
        clock=lambda: permission_clock[0],
    )
    human = host.bind_human(exchange.session, expires_at=1_500)
    runtime = host.bind_runtime(
        Actor(identifier(), "provider", "model_output"),
        purpose="operational",
        expires_at=1_400,
    )

    policy = BudgetPolicy.create(
        profile="execution",
        provider_mode="subscription",
        max_model_calls=3,
        max_tool_calls=5,
        max_node_visits=7,
        max_loop_rounds=2,
        max_output_bytes=1_000,
        max_concurrency=2,
        max_wall_seconds=60,
        max_candidates=1,
    )
    records = SimpleNamespace(
        work=immutable(domain, roots, "work_revision"),
        environment=immutable(domain, roots, "environment"),
        consent=immutable(domain, roots, "run_consent"),
        budget=immutable(domain, roots, "budget_policy", content=policy.domain_content()),
        manifest=immutable(domain, roots, "run_manifest"),
        envelope=immutable(domain, roots, "execution_envelope"),
        profile=immutable(domain, roots, "runtime_profile"),
    )
    for record in vars(records).values():
        host.register_record(record)
    grant = host.grant(
        human,
        runtime,
        records.envelope.ref,
        action="read",
        purpose="operational",
        expires_at=1_300,
    )

    budget_clock = [100]
    book = BudgetBook(legacy, clock=lambda: budget_clock[0])
    budget_session_id = identifier()
    book.start(budget_session_id, policy)

    ledger_clock = [1_000]
    ledger = RuntimeLedger(domain, clock_ms=lambda: ledger_clock[0])
    ledger.reconcile_startup(identifier(), observed_owners={})
    run = RunSpec(
        identifier(),
        records.work.ref,
        records.environment.ref,
        records.consent.ref,
        "live",
        records.budget.ref,
        budget_session_id,
        records.manifest.ref,
    )
    ledger.create_run(identifier(), run)
    execution = ExecutionSpec(identifier(), run.run_id, "writer", identifier(), (0,), ())
    ledger.create_execution(identifier(), execution)
    owner = OwnerIdentity(identifier(), 4_321, 900, identifier())
    attempt = AttemptSpec(
        identifier(),
        execution.execution_id,
        1,
        records.envelope.ref,
        records.profile.ref,
        records.budget.ref,
        identifier(),
        "effect:" + identifier(),
        owner,
        10_000,
    )
    before = ledger.reserve_attempt(identifier(), attempt, lease_duration_ms=1_000)
    budget_request = BudgetDispatchRequest.create(
        session_id=budget_session_id,
        request_id=attempt.reservation_id,
        policy_ref=records.budget.ref,
        model_calls=1,
        tool_calls=0,
        node_visits=1,
        loop_rounds=0,
        output_bytes=100,
        candidates=0,
        api_microunits=None,
    )
    return SimpleNamespace(
        legacy=legacy,
        domain=domain,
        roots=roots,
        authority=authority,
        post_request=post_request,
        read_request=read_request,
        permission_clock=permission_clock,
        host=host,
        gate=gate,
        human=human,
        runtime=runtime,
        grant=grant,
        records=records,
        policy=policy,
        book=book,
        budget_request=budget_request,
        ledger=ledger,
        ledger_clock=ledger_clock,
        owner=owner,
        attempt=attempt,
        before=before,
        command_clock=[1_000],
        event_clock=[1_800_000_000],
    )


def transaction_module():
    try:
        return importlib.import_module("app.api.transaction")
    except ModuleNotFoundError as exc:
        if exc.name != "app.api.transaction":
            raise
        pytest.fail(
            "T016 integration is missing: app.api.transaction.RootCommandCoordinator"
        )


def budget_request_hash(subject):
    return sha256(canonical_json(subject.budget_request.as_dict())).hexdigest()


def command_payload(subject, *, command_id=None, expected_revision=None,
                    target_hash=None, request_hash=None):
    return {
        "schema_version": "command-v1",
        "command_id": command_id or identifier(),
        "command_type": "attempt.dispatch",
        "target": {"kind": "attempt", "id": subject.attempt.attempt_id},
        "expected_revision": (
            subject.before["revision"] if expected_revision is None else expected_revision
        ),
        "target_hash": (
            subject.before["object_ref"]["content_hash"]
            if target_hash is None else target_hash
        ),
        "args": {
            "grant_id": subject.grant.id,
            "resource_sha256": subject.records.envelope.ref.sha256,
            "budget_request_sha256": request_hash or budget_request_hash(subject),
        },
    }


def coordinator(subject):
    module = transaction_module()
    authorization = module.DispatchAuthorization(
        principal=subject.runtime,
        grants=(subject.grant,),
        resource_ref=subject.records.envelope.ref,
        action="read",
        purpose="operational",
        episode_id=None,
    )
    value = module.RootCommandCoordinator(
        domain_store=subject.domain,
        permission_host=subject.host,
        permission_gate=subject.gate,
        budget_book=subject.book,
        runtime_ledger=subject.ledger,
        registry=registry(),
        authenticate_session=subject.authority.authenticate_bound,
        command_clock=lambda: subject.command_clock[0],
        event_clock=lambda: subject.event_clock[0],
    )
    assert value.path == subject.domain.path == subject.book.path
    return value, authorization


def test_root_rejects_a_substituted_session_authenticator(subject):
    module = transaction_module()

    with pytest.raises(TypeError, match="same session authenticator"):
        module.RootCommandCoordinator(
            domain_store=subject.domain,
            permission_host=subject.host,
            permission_gate=subject.gate,
            budget_book=subject.book,
            runtime_ledger=subject.ledger,
            registry=registry(),
            authenticate_session=lambda session: session.actor,
            command_clock=lambda: subject.command_clock[0],
            event_clock=lambda: subject.event_clock[0],
        )

    root, _authorization = coordinator(subject)
    root._authenticate_session = lambda session: session.actor
    with pytest.raises(TypeError, match="Permission authority"):
        root.read_events(
            request=subject.read_request,
            after_cursor=None,
            event_types=(),
            limit=1,
        )


def dispatch(subject, coordinator_value, authorization, payload, *,
             route_profile_ref=None, deadline=None):
    return coordinator_value.execute_budgeted_dispatch(
        payload,
        request=subject.post_request,
        authorization=authorization,
        attempt_id=subject.attempt.attempt_id,
        owner=subject.owner,
        budget_request=subject.budget_request,
        route_profile_ref=(
            subject.records.profile.ref
            if route_profile_ref is None else route_profile_ref
        ),
        deadline=(broker.Deadline.after_ms(5_000) if deadline is None else deadline),
    )


def table_count(subject, table, where="", parameters=()):
    with sqlite3.connect(subject.legacy.path) as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists is None:
            return 0
        suffix = " WHERE " + where if where else ""
        return db.execute("SELECT count(*) FROM " + table + suffix, parameters).fetchone()[0]


def transaction_counts(subject, command_id):
    return {
        "api_commands": table_count(
            subject, "api_commands", "vault_id=? AND command_id=?",
            (subject.domain.vault_id, command_id),
        ),
        "api_events": table_count(
            subject, "api_event_envelopes", "vault_id=? AND event_type='attempt.dispatched'",
            (subject.domain.vault_id,),
        ),
        "runtime_commands": table_count(
            subject, "runtime_commands", "vault_id=? AND command_id=?",
            (subject.domain.vault_id, command_id),
        ),
        "runtime_events": table_count(
            subject,
            "runtime_public_events",
            "vault_id=? AND event_type='attempt.dispatched' AND object_id=?",
            (subject.domain.vault_id, subject.attempt.attempt_id),
        ),
        "budget": table_count(
            subject,
            "runtime_budget_reservations",
            "request_id=?",
            (subject.budget_request.request_id,),
        ),
    }


def assert_no_transaction_effect(subject, command_id):
    assert transaction_counts(subject, command_id) == {
        "api_commands": 0,
        "api_events": 0,
        "runtime_commands": 0,
        "runtime_events": 0,
        "budget": 0,
    }
    assert subject.ledger.get_attempt(subject.attempt.attempt_id) == subject.before
    assert subject.ledger.pending_permit_count == 0


@pytest.mark.parametrize("failure", ("profile", "deadline"))
def test_route_profile_and_absolute_deadline_fail_before_any_root_effect(
    subject,
    failure,
):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)
    wrong_profile = EntityRef(
        "runtime_profile",
        "10000000-0000-4000-8000-000000000011",
        1,
        "b" * 64,
    )
    if failure == "profile":
        expected = CommandInvalid
        kwargs = {"route_profile_ref": wrong_profile}
    else:
        expected = broker.DeadlineExceeded
        kwargs = {"deadline": broker.Deadline(0.1)}

    with pytest.raises(expected):
        dispatch(subject, root, authorization, payload, **kwargs)

    assert_no_transaction_effect(subject, payload["command_id"])


def test_fixture_components_share_one_vault_before_root_integration(subject):
    assert subject.domain.path == subject.book.path == subject.ledger._domain.path
    assert subject.domain.vault_id == subject.ledger.vault_id
    assert subject.gate.authorize(
        subject.runtime,
        subject.records.envelope.ref,
        action="read",
        purpose="operational",
        grants=(subject.grant,),
    ) is None
    assert_no_transaction_effect(subject, identifier())


def test_success_commits_one_receipt_event_then_exposes_one_budget_permit(subject, monkeypatch):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)
    observed = []

    def observe(stage, db):
        database_path = db.execute("PRAGMA database_list").fetchone()[2]
        observed.append((stage, database_path, subject.ledger.pending_permit_count))

    monkeypatch.setattr(root, "_after_stage", observe)
    outcome = dispatch(subject, root, authorization, payload)

    assert [item[0] for item in observed] == list(TRANSACTION_STAGES)
    assert all(item[1] == str(subject.domain.path) and item[2] == 0 for item in observed)
    assert outcome.replayed is False
    assert type(outcome.permit) is DispatchPermit
    assert outcome.permit.command_id == payload["command_id"]
    assert outcome.permit.budget_deadline_epoch_seconds == 160
    assert outcome.read_capability.permit_id == outcome.permit.permit_id
    assert outcome.read_capability.command_id == outcome.permit.command_id
    assert outcome.read_capability.resource_ref == outcome.permit.envelope_ref
    assert outcome.read_capability.grant.id == payload["args"]["grant_id"]
    assert outcome.permit.principal is subject.runtime
    assert outcome.permit.grant is subject.grant
    assert outcome.permit.principal_id == subject.runtime.id
    assert outcome.permit.grant_id == payload["args"]["grant_id"]
    assert outcome.read_capability.principal is outcome.permit.principal
    assert outcome.read_capability.grant is outcome.permit.grant
    assert subject.ledger.pending_permit_count == 1
    assert transaction_counts(subject, payload["command_id"]) == {
        "api_commands": 1,
        "api_events": 1,
        "runtime_commands": 1,
        "runtime_events": 1,
        "budget": 1,
    }
    assert outcome.receipt["state"] == "pending"
    page = root.read_events(
        request=subject.read_request,
        after_cursor=None,
        event_types=("attempt.dispatched",),
        limit=10,
    )
    assert len(page.events) == 1
    assert page.events[0].event_type == "attempt.dispatched"
    assert page.event_cursors == (outcome.receipt["event_cursor"],)
    assert "private_evidence_refs" not in str(page.events[0].as_dict())
    assert subject.ledger.consume_dispatch_permit(
        outcome.permit, budget_book=subject.book
    ) is outcome.permit


@pytest.mark.parametrize("stage", TRANSACTION_STAGES)
def test_failure_after_each_stage_rolls_back_every_component_and_no_permit(
        subject, monkeypatch, stage):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)

    def fail_after(current, _db):
        if current == stage:
            raise sqlite3.IntegrityError("synthetic root transaction failure: " + stage)

    monkeypatch.setattr(root, "_after_stage", fail_after)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic root transaction failure"):
        dispatch(subject, root, authorization, payload)

    assert_no_transaction_effect(subject, payload["command_id"])


def test_base_exception_after_permission_preserves_clock_floor_and_rolls_back(
        subject, monkeypatch):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)
    subject.permission_clock[0] = 1_100

    def interrupt_after_permission(stage, _db):
        if stage == "permission_verified":
            raise KeyboardInterrupt("PRIVATE_INTERRUPT_CANARY")

    monkeypatch.setattr(root, "_after_stage", interrupt_after_permission)
    with pytest.raises(KeyboardInterrupt, match="PRIVATE_INTERRUPT_CANARY"):
        dispatch(subject, root, authorization, payload)

    assert_no_transaction_effect(subject, payload["command_id"])
    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute(
            "SELECT last_observed FROM permission_control WHERE singleton=1"
        ).fetchone()[0] == 1_100


def test_late_rollback_atomically_preserves_all_observed_clock_floors(
        subject, monkeypatch):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)
    subject.permission_clock[0] = 1_100
    subject.ledger_clock[0] = 1_200
    subject.book.clock = lambda: 150

    def fail_after_runtime_and_budget(stage, _db):
        if stage == "public_event":
            raise sqlite3.IntegrityError("synthetic late rollback")

    monkeypatch.setattr(root, "_after_stage", fail_after_runtime_and_budget)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic late rollback"):
        dispatch(subject, root, authorization, payload)

    assert_no_transaction_effect(subject, payload["command_id"])
    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute(
            "SELECT last_observed FROM permission_control WHERE singleton=1"
        ).fetchone()[0] == 1_100
        assert db.execute(
            "SELECT last_clock_ms FROM runtime_control WHERE singleton=1"
        ).fetchone()[0] == 1_200
        assert db.execute(
            "SELECT last_observed FROM runtime_budget_sessions WHERE id=?",
            (subject.budget_request.session_id,),
        ).fetchone()[0] == 150


def test_clock_recovery_accepts_already_higher_durable_floors(subject):
    root, _authorization = coordinator(subject)

    root._persist_observed_clock_watermarks(
        permission_floor=1_100,
        runtime_floor=1_200,
        budget_session_id=subject.budget_request.session_id,
        budget_floor=150,
    )
    root._persist_observed_clock_watermarks(
        permission_floor=1_050,
        runtime_floor=1_150,
        budget_session_id=subject.budget_request.session_id,
        budget_floor=125,
    )

    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute(
            "SELECT last_observed FROM permission_control WHERE singleton=1"
        ).fetchone()[0] == 1_100
        assert db.execute(
            "SELECT last_clock_ms FROM runtime_control WHERE singleton=1"
        ).fetchone()[0] == 1_200
        assert db.execute(
            "SELECT last_observed FROM runtime_budget_sessions WHERE id=?",
            (subject.budget_request.session_id,),
        ).fetchone()[0] == 150


def test_writer_lock_covers_rollback_recovery_before_next_command(
        subject, monkeypatch):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)
    recovery_entered = Event()
    release_recovery = Event()
    second_finished = Event()
    failures = []
    outcomes = []
    original_recovery = root._persist_observed_clock_watermarks

    def fail_first_command(stage, _db):
        if stage == "public_event" and current_thread().name == "failing-command":
            raise sqlite3.IntegrityError("synthetic rollback before recovery")

    def delayed_recovery(**values):
        recovery_entered.set()
        if not release_recovery.wait(timeout=5):
            raise AssertionError("test did not release clock recovery")
        return original_recovery(**values)

    def run_failure():
        try:
            dispatch(subject, root, authorization, payload)
        except BaseException as exc:
            failures.append(exc)

    def run_second():
        try:
            outcomes.append(dispatch(subject, root, authorization, payload))
        finally:
            second_finished.set()

    monkeypatch.setattr(root, "_after_stage", fail_first_command)
    monkeypatch.setattr(root, "_persist_observed_clock_watermarks", delayed_recovery)
    first = Thread(target=run_failure, name="failing-command")
    second = Thread(target=run_second, name="following-command")
    first.start()
    assert recovery_entered.wait(timeout=5)
    second.start()
    assert second_finished.wait(timeout=0.2) is False
    release_recovery.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert len(failures) == 1
    assert type(failures[0]) is sqlite3.IntegrityError
    assert len(outcomes) == 1 and outcomes[0].replayed is False
    assert type(outcomes[0].permit) is DispatchPermit
    assert subject.ledger.pending_permit_count == 1
    assert root._fatal_inhibited is False


def test_clock_capture_failure_cannot_commit_or_expose_a_permit(subject, monkeypatch):
    module = transaction_module()
    root, authorization = coordinator(subject)
    payload = command_payload(subject)

    def fail_capture():
        raise KeyboardInterrupt("PRIVATE_CAPTURE_CANARY")

    monkeypatch.setattr(subject.host, "_observed_clock_floor", fail_capture)
    with pytest.raises(module.RootTransactionFatal) as caught:
        dispatch(subject, root, authorization, payload)

    assert caught.value.error_code == "root_clock_watermark_failed"
    assert "PRIVATE_CAPTURE_CANARY" not in (repr(caught.value) + str(caught.value))
    assert_no_transaction_effect(subject, payload["command_id"])
    with pytest.raises(module.RootTransactionFatal):
        dispatch(subject, root, authorization, payload)


@pytest.mark.parametrize(("component", "method"), (
    ("host", "_persist_clock_watermark_in_transaction"),
    ("ledger", "_persist_clock_watermark_in_transaction"),
    ("book", "_persist_clock_watermark_in_transaction"),
))
def test_watermark_failure_is_atomic_redacted_and_inhibits_later_dispatch(
        subject, monkeypatch, component, method):
    module = transaction_module()
    root, authorization = coordinator(subject)
    payload = command_payload(subject)
    subject.permission_clock[0] = 1_100
    subject.ledger_clock[0] = 1_200
    subject.book.clock = lambda: 150

    def fail_after_permission(stage, _db):
        if stage == "public_event":
            raise sqlite3.IntegrityError("PRIVATE_COMMAND_FAILURE_CANARY")

    def fail_watermark(*_args, **_kwargs):
        raise OSError("PRIVATE_WATERMARK_PATH_CANARY")

    monkeypatch.setattr(root, "_after_stage", fail_after_permission)
    monkeypatch.setattr(getattr(subject, component), method, fail_watermark)
    with pytest.raises(module.RootTransactionFatal) as caught:
        dispatch(subject, root, authorization, payload)

    public = repr(caught.value) + str(caught.value)
    assert "PRIVATE_COMMAND_FAILURE_CANARY" not in public
    assert "PRIVATE_WATERMARK_PATH_CANARY" not in public
    assert caught.value.error_code == "root_clock_watermark_failed"
    assert_no_transaction_effect(subject, payload["command_id"])
    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute(
            "SELECT last_observed FROM permission_control WHERE singleton=1"
        ).fetchone()[0] == 1_000
        assert db.execute(
            "SELECT last_clock_ms FROM runtime_control WHERE singleton=1"
        ).fetchone()[0] == 1_000
        assert db.execute(
            "SELECT last_observed FROM runtime_budget_sessions WHERE id=?",
            (subject.budget_request.session_id,),
        ).fetchone()[0] == 100

    with pytest.raises(module.RootTransactionFatal):
        dispatch(subject, root, authorization, payload)
    assert_no_transaction_effect(subject, payload["command_id"])


def test_fatal_clock_recovery_revokes_every_preexisting_dispatch_permit(
        subject, monkeypatch):
    module = transaction_module()
    root, authorization = coordinator(subject)
    first = dispatch(subject, root, authorization, command_payload(subject))
    current = subject.ledger.get_attempt(subject.attempt.attempt_id)
    second_payload = command_payload(
        subject,
        expected_revision=current["revision"],
        target_hash=current["object_ref"]["content_hash"],
    )

    def fail_recovery(**_values):
        raise OSError("PRIVATE_GLOBAL_INHIBIT_CANARY")

    monkeypatch.setattr(root, "_persist_observed_clock_watermarks", fail_recovery)
    with pytest.raises(module.RootTransactionFatal) as caught:
        dispatch(subject, root, authorization, second_payload)

    assert "PRIVATE_GLOBAL_INHIBIT_CANARY" not in (repr(caught.value) + str(caught.value))
    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.pending_permit_count == 0
    with pytest.raises(DispatchBlocked, match="emergency inhibition"):
        subject.ledger.consume_dispatch_permit(
            first.permit, budget_book=subject.book
        )


def test_fatal_inhibition_cannot_overtake_a_permit_before_writer_ownership(
        subject, monkeypatch):
    root, authorization = coordinator(subject)
    outcome = dispatch(subject, root, authorization, command_payload(subject))
    consume_entered = Event()
    consumed = []
    failures = []
    original_consume = subject.ledger._consume_pending_permit

    def observe_consume(*args, **kwargs):
        consume_entered.set()
        return original_consume(*args, **kwargs)

    def consume():
        try:
            consumed.append(subject.ledger.consume_dispatch_permit(
                outcome.permit, budget_book=subject.book
            ))
        except BaseException as exc:
            failures.append(exc)

    monkeypatch.setattr(subject.ledger, "_consume_pending_permit", observe_consume)
    worker = Thread(target=consume, name="permit-consumer")
    with _writer():
        worker.start()
        assert consume_entered.wait(timeout=0.2) is False
        subject.ledger._inhibit_all_dispatch()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert consumed == []
    assert len(failures) == 1
    assert type(failures[0]) is DispatchBlocked
    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.pending_permit_count == 0


def test_exact_replay_returns_original_receipt_without_a_second_permit(subject):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)

    first = dispatch(subject, root, authorization, payload)
    replay = dispatch(subject, root, authorization, payload)

    assert first.replayed is False and type(first.permit) is DispatchPermit
    assert replay.replayed is True and replay.permit is None
    assert replay.read_capability is None
    assert replay.receipt == first.receipt
    assert subject.ledger.pending_permit_count == 1
    assert transaction_counts(subject, payload["command_id"]) == {
        "api_commands": 1,
        "api_events": 1,
        "runtime_commands": 1,
        "runtime_events": 1,
        "budget": 1,
    }


def test_same_command_id_payload_mismatch_adds_no_reservation_event_or_permit(subject):
    root, authorization = coordinator(subject)
    command_id = identifier()
    accepted = command_payload(subject, command_id=command_id)
    first = dispatch(subject, root, authorization, accepted)
    before = transaction_counts(subject, command_id)
    changed = command_payload(
        subject,
        command_id=command_id,
        request_hash="0" * 64,
    )

    with pytest.raises(CommandConflict):
        dispatch(subject, root, authorization, changed)

    assert transaction_counts(subject, command_id) == before
    assert subject.ledger.pending_permit_count == 1
    assert type(first.permit) is DispatchPermit


def test_revoked_grant_fails_before_reservation_event_or_permit(subject):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)
    subject.host.revoke(subject.grant)

    with pytest.raises(AccessDenied):
        dispatch(subject, root, authorization, payload)

    assert_no_transaction_effect(subject, payload["command_id"])


def test_revoked_selected_grant_cannot_be_replaced_for_committed_permit(subject):
    module = transaction_module()
    root, authorization = coordinator(subject)
    payload = command_payload(subject)
    outcome = dispatch(subject, root, authorization, payload)
    subject.host.revoke(subject.grant)
    replacement = subject.host.grant(
        subject.human,
        subject.runtime,
        subject.records.envelope.ref,
        action="read",
        purpose="operational",
        expires_at=1_300,
    )
    forged = module.SelectedDispatchReadCapability(
        permit_id=outcome.permit.permit_id,
        command_id=outcome.permit.command_id,
        principal=subject.runtime,
        grant=replacement,
        resource_ref=subject.records.envelope.ref,
        purpose="operational",
        episode_id=None,
    )

    with pytest.raises(TypeError, match="capability binding"):
        module.DispatchOutcome(outcome.receipt, outcome.permit, False, forged)

    object.__setattr__(outcome.permit, "grant", replacement)
    with pytest.raises(DispatchBlocked, match="authorization binding changed"):
        subject.ledger.consume_dispatch_permit(
            outcome.permit, budget_book=subject.book
        )


def test_stale_revision_fails_before_reservation_event_or_permit(subject):
    root, authorization = coordinator(subject)
    payload = command_payload(
        subject,
        expected_revision=subject.before["revision"] + 1,
    )

    with pytest.raises(CommandConflict):
        dispatch(subject, root, authorization, payload)

    assert_no_transaction_effect(subject, payload["command_id"])


def test_parallel_duplicate_has_one_result_and_one_post_commit_permit(subject):
    root, authorization = coordinator(subject)
    payload = command_payload(subject)

    def worker(_index):
        return dispatch(subject, root, authorization, payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, range(2)))

    assert outcomes[0].receipt == outcomes[1].receipt
    assert sum(outcome.replayed is False for outcome in outcomes) == 1
    assert sum(type(outcome.permit) is DispatchPermit for outcome in outcomes) == 1
    assert sum(outcome.permit is None for outcome in outcomes) == 1
    assert subject.ledger.pending_permit_count == 1
    assert transaction_counts(subject, payload["command_id"]) == {
        "api_commands": 1,
        "api_events": 1,
        "runtime_commands": 1,
        "runtime_events": 1,
        "budget": 1,
    }
