"""Offline runtime-ledger fault tests against a real temporary additive SQLite store."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.refs import DomainContractError, EntityRef, MAX_INTEGER
from app.domain.schemas import ImmutableRecord
from app.domain.store import DomainStore, MissingRecord
from app.storage import Store


STAMP = "2026-09-07T00:00:00.000000Z"


def api():
    from app.runtime import ledger
    return ledger


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


def opened(tmp_path, *, now=1_000, reconcile=True):
    module = api()
    clock = [now]
    legacy = Store(tmp_path / "vault")
    domain = DomainStore(legacy)
    roots = domain.initialize_vault()
    refs = SimpleNamespace(
        work=immutable(domain, roots, "work_revision"),
        environment=immutable(domain, roots, "environment"),
        consent=immutable(domain, roots, "run_consent"),
        budget=immutable(domain, roots, "budget_policy"),
        manifest=immutable(domain, roots, "run_manifest"),
        envelope=immutable(domain, roots, "execution_envelope"),
        profile=immutable(domain, roots, "runtime_profile"),
        result=immutable(domain, roots, "run_manifest", content={"fixture": "terminal"}),
    )
    ledger = module.RuntimeLedger(domain, clock_ms=lambda: clock[0])
    if reconcile:
        ledger.reconcile_startup(identifier(), observed_owners={})
    return SimpleNamespace(module=module, clock=clock, legacy=legacy, domain=domain,
                           roots=roots, refs=refs, ledger=ledger)


def run_spec(subject, **changes):
    module, refs = subject.module, subject.refs
    value = module.RunSpec(
        run_id=identifier(),
        work_revision_ref=refs.work,
        environment_ref=refs.environment,
        consent_ref=refs.consent,
        mode="live",
        budget_policy_ref=refs.budget,
        budget_session_id=identifier(),
        manifest_ref=refs.manifest,
    )
    return replace(value, **changes) if changes else value


def execution_spec(subject, run_id, **changes):
    value = subject.module.ExecutionSpec(
        execution_id=identifier(), run_id=run_id, node_id="writer",
        visit_id=identifier(), loop_indices=(0,), parent_execution_ids=(),
    )
    return replace(value, **changes) if changes else value


def owner(subject, **changes):
    value = subject.module.OwnerIdentity(
        owner_id=identifier(), pid=4321, process_started_at_ms=900, nonce=identifier())
    return replace(value, **changes) if changes else value


def attempt_spec(subject, execution_id, lease_owner, *, attempt_no=1, **changes):
    refs = subject.refs
    value = subject.module.AttemptSpec(
        attempt_id=identifier(), execution_id=execution_id, attempt_no=attempt_no,
        envelope_ref=refs.envelope, profile_ref=refs.profile,
        budget_policy_ref=refs.budget, reservation_id=identifier(),
        idempotency_key="effect:" + identifier(), owner=lease_owner,
        deadline_at_ms=10_000,
    )
    return replace(value, **changes) if changes else value


def result(subject, attempt_id, **changes):
    value = subject.module.ResultObservation(
        observation_id=identifier(), attempt_id=attempt_id, outcome="succeeded",
        result_ref=subject.refs.result, usage_finality="final",
        remote_terminal_observed="succeeded", reason_code="provider_terminal",
    )
    return replace(value, **changes) if changes else value


def prepared(subject, *, execution=None, lease_owner=None, spec=None):
    run = run_spec(subject)
    subject.ledger.create_run(identifier(), run)
    execution = execution or execution_spec(subject, run.run_id)
    subject.ledger.create_execution(identifier(), execution)
    lease_owner = lease_owner or owner(subject)
    spec = spec or attempt_spec(subject, execution.execution_id, lease_owner)
    snapshot = subject.ledger.reserve_attempt(identifier(), spec, lease_duration_ms=1_000)
    return run, execution, lease_owner, spec, snapshot


def send(subject, attempt, lease_owner, revision=1, *, command_id=None):
    return subject.ledger._commit_unbudgeted_send_intent_for_test(
        command_id or identifier(), attempt.attempt_id, lease_owner,
        expected_revision=revision,
    )


def test_runtime_schema_is_additive_and_preserves_domain_and_legacy_rows(tmp_path):
    subject = opened(tmp_path)
    work = subject.legacy.create_work("preserve me")
    before = subject.legacy.get_work(work["id"])
    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute(
            "SELECT version FROM domain_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,)]
        runtime = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'runtime_%'")}
    assert {"runtime_migrations", "runtime_runs", "runtime_node_executions",
            "runtime_attempts", "runtime_commands", "runtime_checkpoints"} <= runtime
    assert subject.legacy.get_work(work["id"]) == before
    assert subject.domain.get(subject.refs.environment).ref == subject.refs.environment


def test_shared_runtime_migrations_preserve_an_independent_budget_component(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    domain = DomainStore(legacy)
    domain.initialize_vault()
    with sqlite3.connect(legacy.path) as db:
        db.execute(
            "CREATE TABLE runtime_migrations (component TEXT NOT NULL, "
            "version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0), "
            "sha256 TEXT NOT NULL, PRIMARY KEY(component,version))"
        )
        db.execute("INSERT INTO runtime_migrations VALUES ('budgets',1,?)", ("a" * 64,))

    module.RuntimeLedger(domain, clock_ms=lambda: 1_000)
    with sqlite3.connect(legacy.path) as db:
        assert db.execute(
            "SELECT component,version,sha256 FROM runtime_migrations ORDER BY component"
        ).fetchall() == [
            ("budgets", 1, "a" * 64),
            ("ledger", 1, module.RUNTIME_MIGRATION_SHA256),
        ]


def test_shared_runtime_migration_table_requires_the_exact_version_check(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    domain = DomainStore(legacy)
    domain.initialize_vault()
    with sqlite3.connect(legacy.path) as db:
        db.execute(
            "CREATE TABLE runtime_migrations (component TEXT NOT NULL, "
            "version INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(component,version))"
        )
    with pytest.raises(module.CorruptLedger, match="version constraint"):
        module.RuntimeLedger(domain, clock_ms=lambda: 1_000)


def test_runtime_migration_digest_and_all_or_none_schema_are_fail_closed(tmp_path):
    subject = opened(tmp_path / "digest")
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("UPDATE runtime_migrations SET sha256=? WHERE component='ledger'", ("0" * 64,))
    with pytest.raises(subject.module.CorruptLedger, match="migration"):
        subject.module.RuntimeLedger(DomainStore(subject.legacy), clock_ms=lambda: 1_000)

    partial = opened(tmp_path / "partial")
    with sqlite3.connect(partial.legacy.path) as db:
        db.execute("DROP TABLE runtime_result_refs")
    with pytest.raises(partial.module.CorruptLedger, match="Partial"):
        partial.module.RuntimeLedger(DomainStore(partial.legacy), clock_ms=lambda: 1_000)


def test_run_execution_and_attempt_preserve_exact_refs_visits_and_reservation(tmp_path):
    subject = opened(tmp_path)
    run, execution, lease_owner, attempt, reserved = prepared(subject)
    assert reserved["spec"] == attempt.as_dict()
    assert reserved["object_ref"]["kind"] == "attempt"
    assert reserved["phase"] == "reserved"
    assert reserved["dispatch_gate"] == "open"
    assert reserved["send_finality"] == "not_started"
    assert reserved["lease_owner"] == lease_owner.as_dict()
    assert reserved["reservation_ref"] == {
        "kind": "budget_reservation", "id": attempt.reservation_id,
    }
    reopened = subject.module.RuntimeLedger(DomainStore(subject.legacy), clock_ms=lambda: subject.clock[0])
    assert reopened.get_run(run.run_id)["spec"] == run.as_dict()
    assert reopened.get_execution(execution.execution_id)["spec"] == execution.as_dict()
    assert reopened.get_attempt(attempt.attempt_id) == reserved

    repeat = execution_spec(subject, run.run_id, node_id=execution.node_id,
                            visit_id=identifier(), loop_indices=(1,))
    subject.ledger.create_execution(identifier(), repeat)
    subject.ledger.request_cancel(identifier(), attempt.attempt_id, expected_revision=1)
    subject.ledger.finish_cancellation(
        identifier(), attempt.attempt_id, lease_owner,
        subject.module.CancellationObservation(
            outcome="cancelled", local_transport_closed=True, owned_process_exit=None,
            remote_terminal_observed="not_observed", usage_finality="final"),
        expected_revision=2)
    retry = attempt_spec(subject, execution.execution_id, lease_owner, attempt_no=2)
    subject.ledger.reserve_attempt(identifier(), retry, lease_duration_ms=1_000)
    assert repeat.visit_id != execution.visit_id
    assert retry.attempt_no == 2 and retry.execution_id == execution.execution_id


def test_exact_refs_are_kind_checked_and_resolved_in_the_same_vault(tmp_path):
    subject = opened(tmp_path)
    with pytest.raises(DomainContractError):
        run_spec(subject, environment_ref=subject.refs.profile)

    other = Store(tmp_path / "other")
    foreign_domain = DomainStore(other)
    foreign_roots = foreign_domain.initialize_vault()
    foreign_environment = immutable(foreign_domain, foreign_roots, "environment")
    spec = run_spec(subject, environment_ref=foreign_environment)
    with pytest.raises(MissingRecord):
        subject.ledger.create_run(identifier(), spec)


def test_deleted_reference_indexes_fail_closed_before_dispatch_or_result_reuse(tmp_path):
    subject = opened(tmp_path / "attempt")
    _, _, lease_owner, attempt, _ = prepared(subject)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("DELETE FROM runtime_attempt_refs WHERE attempt_id=? AND role='envelope'",
                   (attempt.attempt_id,))
    with pytest.raises(subject.module.CorruptLedger, match="reference index"):
        send(subject, attempt, lease_owner)

    result_subject = opened(tmp_path / "result")
    _, _, result_owner, result_attempt, _ = prepared(result_subject)
    send(result_subject, result_attempt, result_owner)
    accepted = result(result_subject, result_attempt.attempt_id)
    result_subject.ledger.accept_result(identifier(), accepted)
    with sqlite3.connect(result_subject.legacy.path) as db:
        db.execute("DELETE FROM runtime_result_refs WHERE observation_id=?",
                   (accepted.observation_id,))
    with pytest.raises(result_subject.module.CorruptLedger, match="Result reference index"):
        result_subject.ledger.lookup_committed_result(
            result_attempt.attempt_id, result_attempt.execution_id,
            result_attempt.envelope_ref)


def test_command_replay_is_exact_and_payload_mismatch_conflicts_without_mutation(tmp_path):
    subject = opened(tmp_path)
    command_id = identifier()
    spec = run_spec(subject)
    first = subject.ledger.create_run(command_id, spec)
    assert subject.ledger.create_run(command_id, spec) == first
    with pytest.raises(subject.module.CommandConflict):
        subject.ledger.create_run(command_id, replace(spec, run_id=identifier()))
    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute("SELECT count(*) FROM runtime_runs").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM runtime_commands WHERE command_id=?",
                          (command_id,)).fetchone() == (1,)


def test_reservation_attempt_owner_idempotency_and_event_commit_atomically(tmp_path):
    subject = opened(tmp_path)
    run = run_spec(subject)
    subject.ledger.create_run(identifier(), run)
    execution = execution_spec(subject, run.run_id)
    subject.ledger.create_execution(identifier(), execution)
    lease_owner = owner(subject)
    spec = attempt_spec(subject, execution.execution_id, lease_owner)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("""CREATE TRIGGER fail_reserved_event BEFORE INSERT ON runtime_public_events
            WHEN NEW.event_type='attempt.reserved'
            BEGIN SELECT RAISE(ABORT,'synthetic reserved event failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic reserved event failure"):
        subject.ledger.reserve_attempt(identifier(), spec, lease_duration_ms=500)
    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute("SELECT count(*) FROM runtime_attempts").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM runtime_attempt_journal").fetchone() == (0,)
        db.execute("DROP TRIGGER fail_reserved_event")
    subject.ledger.reserve_attempt(identifier(), spec, lease_duration_ms=500)
    subject.clock[0] = spec.deadline_at_ms
    replayed = subject.ledger.reserve_attempt(identifier(), spec, lease_duration_ms=500)
    assert replayed["spec"] == spec.as_dict()
    conflicting = replace(spec, attempt_id=identifier())
    with pytest.raises(subject.module.IdempotencyConflict):
        subject.ledger.reserve_attempt(identifier(), conflicting, lease_duration_ms=500)
    events = subject.ledger.events(after_sequence=0, limit=100)
    reserved = [event for event in events if event["event_type"] == "attempt.reserved"]
    assert len(reserved) == 1 and reserved[0]["payload"] == {"attempt_no": 1}


def test_send_intent_commit_is_a_one_way_barrier_and_permit_is_process_one_shot(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    command_id = identifier()
    permit = send(subject, attempt, lease_owner, command_id=command_id)
    assert type(permit) is subject.module.LedgerOnlyPermit
    persisted = subject.ledger.get_attempt(attempt.attempt_id)
    assert persisted["phase"] == "send_intent"
    assert persisted["send_finality"] == "may_have_started"
    assert persisted["send_intent_at_ms"] == subject.clock[0]
    assert persisted["spec"]["envelope_ref"] == permit.envelope_ref.as_dict()
    assert subject.ledger._commit_unbudgeted_send_intent_for_test(
        command_id, attempt.attempt_id, lease_owner, expected_revision=1) is None
    assert subject.ledger._consume_unbudgeted_permit_for_test(permit) is permit
    with pytest.raises(subject.module.DispatchBlocked):
        subject.ledger._consume_unbudgeted_permit_for_test(permit)
    with sqlite3.connect(subject.legacy.path) as db:
        assert db.execute("SELECT count(*) FROM runtime_public_events WHERE event_type='attempt.dispatched'").fetchone() == (1,)


def test_failed_send_intent_commit_never_returns_or_invokes_a_permit(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, before = prepared(subject)
    sent = []
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("""CREATE TRIGGER fail_send_journal BEFORE INSERT ON runtime_attempt_journal
            WHEN NEW.transition='send_intent'
            BEGIN SELECT RAISE(ABORT,'synthetic send failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic send failure"):
        permit = send(subject, attempt, lease_owner)
        sent.append(subject.ledger._consume_unbudgeted_permit_for_test(permit))
    assert sent == []
    assert subject.ledger.get_attempt(attempt.attempt_id) == before


@pytest.mark.parametrize("mode", ["replay", "snapshot"])
def test_read_only_run_modes_never_issue_a_dispatch_permit(tmp_path, mode):
    subject = opened(tmp_path)
    run = run_spec(subject, mode=mode)
    subject.ledger.create_run(identifier(), run)
    execution = execution_spec(subject, run.run_id)
    subject.ledger.create_execution(identifier(), execution)
    lease_owner = owner(subject)
    attempt = attempt_spec(subject, execution.execution_id, lease_owner)
    before = subject.ledger.reserve_attempt(identifier(), attempt, lease_duration_ms=500)
    with pytest.raises(subject.module.DispatchBlocked, match=mode):
        send(subject, attempt, lease_owner)
    assert subject.ledger.get_attempt(attempt.attempt_id) == before
    assert subject.ledger.pending_permit_count == 0


def test_concurrent_send_barrier_issues_exactly_one_permit(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    barrier = Barrier(2)

    def issue(_):
        barrier.wait(timeout=5)
        try:
            return send(subject, attempt, lease_owner)
        except subject.module.RevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        permits = list(pool.map(issue, range(2)))
    assert sum(type(value) is subject.module.LedgerOnlyPermit for value in permits) == 1
    assert subject.ledger.get_attempt(attempt.attempt_id)["revision"] == 2


def test_dispatch_permit_is_concurrency_safe_and_expires_with_its_lease(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    permit = send(subject, attempt, lease_owner)
    barrier = Barrier(2)

    def consume(_):
        barrier.wait(timeout=5)
        try:
            subject.ledger._consume_unbudgeted_permit_for_test(permit)
            return "consumed"
        except subject.module.DispatchBlocked:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(consume, range(2)))
    assert sorted(outcomes) == ["blocked", "consumed"]

    retry_execution = execution_spec(subject, subject.ledger.get_execution(
        attempt.execution_id)["spec"]["run_id"], node_id="second")
    subject.ledger.create_execution(identifier(), retry_execution)
    retry = attempt_spec(subject, retry_execution.execution_id, lease_owner)
    subject.ledger.reserve_attempt(identifier(), retry, lease_duration_ms=500)
    expiring = send(subject, retry, lease_owner)
    subject.clock[0] = expiring.lease_expires_at_ms
    with pytest.raises(subject.module.DispatchBlocked):
        subject.ledger._consume_unbudgeted_permit_for_test(expiring)


def test_lease_renewal_requires_full_identity_live_lease_and_revision_cas(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    for impostor in (replace(lease_owner, nonce=identifier()),
                     replace(lease_owner, process_started_at_ms=899),
                     replace(lease_owner, owner_id=identifier())):
        with pytest.raises(subject.module.LeaseOwnershipError):
            subject.ledger.renew_lease(identifier(), attempt.attempt_id, impostor,
                                       expected_revision=1, lease_duration_ms=500)
    renewed = subject.ledger.renew_lease(
        identifier(), attempt.attempt_id, lease_owner,
        expected_revision=1, lease_duration_ms=2_000)
    assert renewed["revision"] == 2 and renewed["lease_fence"] == 2
    with pytest.raises(subject.module.RevisionConflict):
        subject.ledger.renew_lease(identifier(), attempt.attempt_id, lease_owner,
                                   expected_revision=1, lease_duration_ms=500)
    subject.clock[0] = renewed["lease_expires_at_ms"]
    with pytest.raises(subject.module.LeaseExpired):
        subject.ledger.renew_lease(identifier(), attempt.attempt_id, lease_owner,
                                   expected_revision=2, lease_duration_ms=500)


def test_clock_rejects_bool_rollback_and_lease_overflow_without_mutation(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, before = prepared(subject)
    subject.clock[0] = 999
    with pytest.raises(subject.module.ClockError):
        send(subject, attempt, lease_owner)
    assert subject.ledger.get_attempt(attempt.attempt_id) == before

    subject.clock[0] = True
    with pytest.raises(subject.module.ClockError):
        send(subject, attempt, lease_owner)

    overflow = opened(tmp_path / "overflow", now=MAX_INTEGER - 5)
    run = run_spec(overflow)
    overflow.ledger.create_run(identifier(), run)
    execution = execution_spec(overflow, run.run_id)
    overflow.ledger.create_execution(identifier(), execution)
    process = owner(overflow, process_started_at_ms=MAX_INTEGER - 10)
    spec = attempt_spec(overflow, execution.execution_id, process,
                        deadline_at_ms=MAX_INTEGER)
    with pytest.raises(ValueError, match="overflow"):
        overflow.ledger.reserve_attempt(identifier(), spec, lease_duration_ms=10)


def test_typed_terminal_result_first_wins_exact_duplicates_and_late_are_retained(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    send(subject, attempt, lease_owner)
    accepted = result(subject, attempt.attempt_id)
    outcome = subject.ledger.accept_result(identifier(), accepted)
    assert outcome["classification"] == "accepted"
    assert outcome["attempt"]["terminal_outcome"] == "succeeded"

    duplicate = replace(accepted, observation_id=identifier())
    assert subject.ledger.accept_result(identifier(), duplicate)["classification"] == "duplicate"
    late = result(subject, attempt.attempt_id, outcome="failed", result_ref=None,
                  usage_finality="unknown", remote_terminal_observed="failed",
                  reason_code="provider_terminal")
    assert subject.ledger.accept_result(identifier(), late)["classification"] == "late"
    stored = subject.ledger.get_attempt(attempt.attempt_id)
    assert stored["terminal_outcome"] == "succeeded"
    assert stored["accepted_observation_id"] == accepted.observation_id
    assert [item["classification"] for item in
            subject.ledger.result_observations(attempt.attempt_id)] == [
                "accepted", "duplicate", "late"]


def test_result_id_conflict_and_typed_reason_boundary_do_not_mutate(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    send(subject, attempt, lease_owner)
    observation = result(subject, attempt.attempt_id)
    subject.ledger.accept_result(identifier(), observation)
    before = subject.ledger.get_attempt(attempt.attempt_id)
    with pytest.raises(subject.module.ResultConflict):
        subject.ledger.accept_result(identifier(), replace(
            observation, outcome="failed", result_ref=None, usage_finality="unknown",
            remote_terminal_observed="failed"))
    with pytest.raises(ValueError):
        result(subject, attempt.attempt_id, reason_code="raw provider said /Users/secret")
    with pytest.raises(TypeError):
        subject.module.ResultObservation(**{**observation.as_dict(),
                                            "details": {"raw": "provider body"}})
    assert subject.ledger.get_attempt(attempt.attempt_id) == before


def test_concurrent_terminal_results_have_one_accepted_cas_winner(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    send(subject, attempt, lease_owner)
    barrier = Barrier(2)
    observations = [
        result(subject, attempt.attempt_id),
        result(subject, attempt.attempt_id, outcome="failed", result_ref=None,
               usage_finality="unknown", remote_terminal_observed="failed"),
    ]

    def finish(observation):
        barrier.wait(timeout=5)
        return subject.ledger.accept_result(identifier(), observation)["classification"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        classifications = list(pool.map(finish, observations))
    assert classifications.count("accepted") == 1
    assert classifications.count("late") == 1
    terminal_events = [event for event in subject.ledger.events(after_sequence=0, limit=100)
                       if event["event_type"] == "attempt.terminal"]
    assert len(terminal_events) == 1


def test_unknown_outcome_is_terminal_and_never_releases_exact_reservation_identity(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    send(subject, attempt, lease_owner)
    unknown = result(subject, attempt.attempt_id, outcome="outcome_unknown",
                     result_ref=None, usage_finality="unknown",
                     remote_terminal_observed="not_observed",
                     reason_code="transport_unknown")
    accepted = subject.ledger.accept_result(identifier(), unknown)
    assert accepted["classification"] == "accepted"
    snapshot = accepted["attempt"]
    assert snapshot["terminal_outcome"] == "outcome_unknown"
    assert snapshot["usage_finality"] == "unknown"
    assert snapshot["spec"]["reservation_id"] == attempt.reservation_id
    assert subject.ledger.lookup_committed_result(
        attempt.attempt_id, attempt.execution_id, attempt.envelope_ref)["observation_id"] == unknown.observation_id
    assert subject.ledger.lookup_committed_result(
        attempt.attempt_id, identifier(), attempt.envelope_ref) is None
    wrong_envelope = EntityRef("execution_envelope", identifier(), 1, "0" * 64)
    assert subject.ledger.lookup_committed_result(
        attempt.attempt_id, attempt.execution_id, wrong_envelope) is None
    retry = attempt_spec(subject, attempt.execution_id, lease_owner, attempt_no=2)
    with pytest.raises(subject.module.DispatchBlocked, match="retry-safe"):
        subject.ledger.reserve_attempt(identifier(), retry, lease_duration_ms=500)


def test_terminal_result_observed_after_deadline_is_quarantined_as_late(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    send(subject, attempt, lease_owner)
    subject.clock[0] = attempt.deadline_at_ms
    observation = result(subject, attempt.attempt_id)
    recorded = subject.ledger.accept_result(identifier(), observation)
    assert recorded["classification"] == "late"
    assert recorded["attempt"]["terminal_outcome"] == "timed_out"
    assert recorded["attempt"]["accepted_observation_id"] is None
    assert subject.ledger.result_observations(attempt.attempt_id)[0]["classification"] == "late"
    retry = attempt_spec(subject, attempt.execution_id, lease_owner, attempt_no=2,
                         deadline_at_ms=20_000)
    with pytest.raises(subject.module.DispatchBlocked, match="retry-safe"):
        subject.ledger.reserve_attempt(identifier(), retry, lease_duration_ms=500)


def test_incoherent_send_and_recovery_state_fails_closed_before_dispatch(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("UPDATE runtime_attempts SET phase='running' WHERE id=?",
                   (attempt.attempt_id,))
    with pytest.raises(subject.module.CorruptLedger, match="phase"):
        send(subject, attempt, lease_owner)

    second = opened(tmp_path / "pending")
    _, _, second_owner, second_attempt, _ = prepared(second)
    with sqlite3.connect(second.legacy.path) as db:
        db.execute("UPDATE runtime_attempts SET recovery_state='pending' WHERE id=?",
                   (second_attempt.attempt_id,))
    with pytest.raises(second.module.CorruptLedger, match="Recovery-pending"):
        send(second, second_attempt, second_owner)


def test_cancel_closes_gate_before_stop_and_late_success_is_quarantined(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    permit = send(subject, attempt, lease_owner)
    cancelled = subject.ledger.request_cancel(
        identifier(), attempt.attempt_id, expected_revision=2)
    assert cancelled["applied"] is True
    assert cancelled["attempt"]["dispatch_gate"] == "closed"
    assert cancelled["attempt"]["cancel_state"] == "requested"
    assert cancelled["attempt"]["dispatch_blocked_at_ms"] == subject.clock[0]
    with pytest.raises(subject.module.DispatchBlocked):
        subject.ledger._consume_unbudgeted_permit_for_test(permit)

    observation = subject.module.CancellationObservation(
        outcome="outcome_unknown", local_transport_closed=True, owned_process_exit=0,
        remote_terminal_observed="not_observed", usage_finality="unknown")
    terminal = subject.ledger.finish_cancellation(
        identifier(), attempt.attempt_id, lease_owner, observation,
        expected_revision=3)
    assert terminal["terminal_outcome"] == "outcome_unknown"
    assert terminal["local_transport_closed_at_ms"] == subject.clock[0]
    assert terminal["owned_process_exit"] == 0
    late = result(subject, attempt.attempt_id)
    assert subject.ledger.accept_result(identifier(), late)["classification"] == "late"
    assert subject.ledger.get_attempt(attempt.attempt_id)["terminal_outcome"] == "outcome_unknown"


def test_cancel_cannot_claim_remote_stop_from_a_dead_local_transport(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    send(subject, attempt, lease_owner)
    subject.ledger.request_cancel(identifier(), attempt.attempt_id, expected_revision=2)
    false_claim = subject.module.CancellationObservation(
        outcome="cancelled", local_transport_closed=True, owned_process_exit=0,
        remote_terminal_observed="not_observed", usage_finality="unknown")
    with pytest.raises(subject.module.InvalidTransition):
        subject.ledger.finish_cancellation(
            identifier(), attempt.attempt_id, lease_owner, false_claim,
            expected_revision=3)
    assert subject.ledger.get_attempt(attempt.attempt_id)["terminal_outcome"] is None


def test_late_conflicting_evidence_blocks_retry_after_remote_cancellation(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    send(subject, attempt, lease_owner)
    subject.ledger.request_cancel(identifier(), attempt.attempt_id, expected_revision=2)
    subject.ledger.finish_cancellation(
        identifier(), attempt.attempt_id, lease_owner,
        subject.module.CancellationObservation(
            outcome="cancelled", local_transport_closed=True, owned_process_exit=0,
            remote_terminal_observed="cancelled", usage_finality="final"),
        expected_revision=3)
    assert subject.ledger.accept_result(
        identifier(), result(subject, attempt.attempt_id))["classification"] == "late"
    retry = attempt_spec(subject, attempt.execution_id, lease_owner, attempt_no=2,
                         deadline_at_ms=20_000)
    with pytest.raises(subject.module.DispatchBlocked, match="retry-safe"):
        subject.ledger.reserve_attempt(identifier(), retry, lease_duration_ms=500)


def test_pre_send_cancel_is_definitely_unsent_and_can_finish_cancelled(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    subject.ledger.request_cancel(identifier(), attempt.attempt_id, expected_revision=1)
    observation = subject.module.CancellationObservation(
        outcome="cancelled", local_transport_closed=True, owned_process_exit=None,
        remote_terminal_observed="not_observed", usage_finality="final")
    snapshot = subject.ledger.finish_cancellation(
        identifier(), attempt.attempt_id, lease_owner, observation,
        expected_revision=2)
    assert snapshot["send_finality"] == "definitely_not_sent"
    assert snapshot["terminal_outcome"] == "cancelled"


def test_pre_send_cancel_rejects_remote_or_unknown_outcome_claims(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    subject.ledger.request_cancel(identifier(), attempt.attempt_id, expected_revision=1)
    for observation in (
        subject.module.CancellationObservation(
            outcome="cancelled", local_transport_closed=True, owned_process_exit=None,
            remote_terminal_observed="succeeded", usage_finality="final"),
        subject.module.CancellationObservation(
            outcome="outcome_unknown", local_transport_closed=True, owned_process_exit=None,
            remote_terminal_observed="not_observed", usage_finality="unknown"),
    ):
        with pytest.raises(subject.module.InvalidTransition):
            subject.ledger.finish_cancellation(
                identifier(), attempt.attempt_id, lease_owner, observation,
                expected_revision=2)


def test_cancel_storage_failure_sets_only_process_local_emergency_inhibition(tmp_path):
    subject = opened(tmp_path)
    _, _, lease_owner, attempt, _ = prepared(subject)
    permit = send(subject, attempt, lease_owner)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("""CREATE TRIGGER fail_cancel_journal BEFORE INSERT ON runtime_attempt_journal
            WHEN NEW.transition='cancel_requested'
            BEGIN SELECT RAISE(ABORT,'synthetic cancel failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic cancel failure"):
        subject.ledger.request_cancel(identifier(), attempt.attempt_id, expected_revision=2)
    persisted = subject.ledger.get_attempt(attempt.attempt_id)
    assert persisted["dispatch_gate"] == "open"
    assert persisted["cancel_state"] == "none"
    assert subject.ledger.is_emergency_inhibited(attempt.attempt_id) is True
    with pytest.raises(subject.module.DispatchBlocked):
        subject.ledger._consume_unbudgeted_permit_for_test(permit)


def test_checkpoint_cursor_is_opaque_bounded_versioned_and_not_a_command_payload(tmp_path):
    subject = opened(tmp_path)
    run, _, _, attempt, _ = prepared(subject)
    cursor = b"\x00not-json\xffscheduler-private\x00"
    first = subject.ledger.write_checkpoint(
        identifier(), run.run_id, "main", cursor, expected_revision=0,
        attempt_id=attempt.attempt_id)
    assert first["revision"] == 1 and first["cursor"] == cursor
    assert subject.ledger.read_checkpoint(run.run_id, "main") == first
    second = subject.ledger.write_checkpoint(
        identifier(), run.run_id, "main", b"next", expected_revision=1,
        attempt_id=attempt.attempt_id)
    assert second["revision"] == 2
    with pytest.raises(subject.module.RevisionConflict):
        subject.ledger.write_checkpoint(
            identifier(), run.run_id, "main", b"stale", expected_revision=1,
            attempt_id=attempt.attempt_id)
    with sqlite3.connect(subject.legacy.path) as db:
        command_bytes = b"".join(bytes(row[0]) for row in db.execute(
            "SELECT payload FROM runtime_commands"))
    assert cursor not in command_bytes

    reopened = subject.module.RuntimeLedger(DomainStore(subject.legacy), clock_ms=lambda: subject.clock[0])
    assert reopened.read_checkpoint(run.run_id, "main")["cursor"] == b"next"
    with pytest.raises(subject.module.StartupReconciliationRequired):
        reopened.checkpoint_for_replay(run.run_id, "main")
    reopened.reconcile_startup(identifier(), observed_owners={})
    assert reopened.checkpoint_for_replay(run.run_id, "main")["cursor"] == b"next"


def test_corrupt_checkpoint_blocks_reconciliation_and_replay(tmp_path):
    subject = opened(tmp_path)
    run, _, lease_owner, attempt, _ = prepared(subject)
    send(subject, attempt, lease_owner)
    subject.ledger.write_checkpoint(
        identifier(), run.run_id, "main", b"cursor", expected_revision=0,
        attempt_id=attempt.attempt_id)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("UPDATE runtime_checkpoints SET cursor=?", (b"tampered",))
    reopened = subject.module.RuntimeLedger(DomainStore(subject.legacy), clock_ms=lambda: subject.clock[0])
    with pytest.raises(subject.module.CorruptLedger):
        reopened.reconcile_startup(identifier(), observed_owners={attempt.attempt_id: lease_owner})
    with pytest.raises(subject.module.StartupReconciliationRequired):
        reopened.checkpoint_for_replay(run.run_id, "main")


def test_historical_checkpoints_do_not_exhaust_active_recovery_bound(tmp_path, monkeypatch):
    subject = opened(tmp_path)
    for _ in range(2):
        run, _, lease_owner, attempt, _ = prepared(subject)
        subject.ledger.write_checkpoint(
            identifier(), run.run_id, "main", b"historical", expected_revision=0,
            attempt_id=attempt.attempt_id)
        send(subject, attempt, lease_owner)
        subject.ledger.accept_result(identifier(), result(subject, attempt.attempt_id))
    _, _, _, active, _ = prepared(subject)
    monkeypatch.setattr(subject.module, "MAX_ACTIVE_ATTEMPTS", 1)
    reopened = subject.module.RuntimeLedger(
        DomainStore(subject.legacy), clock_ms=lambda: subject.clock[0])
    report = reopened.reconcile_startup(identifier(), observed_owners={})
    assert report["checkpoint_count"] == 0
    assert reopened.get_attempt(active.attempt_id)["send_finality"] == "definitely_not_sent"


def test_restart_reconciliation_never_reissues_or_automatically_redispatches(tmp_path):
    subject = opened(tmp_path)
    run = run_spec(subject)
    subject.ledger.create_run(identifier(), run)
    process = owner(subject)
    attempts = []
    send_commands = []
    for index in range(3):
        execution = execution_spec(subject, run.run_id, node_id=f"node-{index}")
        subject.ledger.create_execution(identifier(), execution)
        attempt = attempt_spec(subject, execution.execution_id, process)
        subject.ledger.reserve_attempt(identifier(), attempt, lease_duration_ms=2_000)
        attempts.append(attempt)
        if index < 2:
            command = identifier()
            assert send(subject, attempt, process, command_id=command) is not None
            send_commands.append(command)

    reopened = subject.module.RuntimeLedger(DomainStore(subject.legacy), clock_ms=lambda: subject.clock[0])
    with pytest.raises(subject.module.StartupReconciliationRequired):
        send(reopened_fixture(subject, reopened), attempts[2], process)
    before = reopened.recovery_snapshot()
    assert {item["spec"]["attempt_id"] for item in before["attempts"]} == {
        item.attempt_id for item in attempts}
    report = reopened.reconcile_startup(
        identifier(), observed_owners={attempts[0].attempt_id: process})
    assert report["recovery_pending_count"] == 2
    assert report["unknown_count"] == 1
    assert reopened.get_attempt(attempts[0].attempt_id)["recovery_state"] == "pending"
    assert reopened.get_attempt(attempts[1].attempt_id)["terminal_outcome"] == "outcome_unknown"
    unsent = reopened.get_attempt(attempts[2].attempt_id)
    assert unsent["send_finality"] == "definitely_not_sent"
    assert unsent["dispatch_gate"] == "closed"
    assert reopened._commit_unbudgeted_send_intent_for_test(
        send_commands[0], attempts[0].attempt_id, process, expected_revision=1) is None
    assert reopened.pending_permit_count == 0

    retry = attempt_spec(subject, attempts[2].execution_id, process, attempt_no=2)
    reopened.reserve_attempt(identifier(), retry, lease_duration_ms=1_000)
    assert reopened._commit_unbudgeted_send_intent_for_test(
        identifier(), retry.attempt_id, process, expected_revision=1) is not None


def reopened_fixture(subject, ledger):
    return SimpleNamespace(**{**subject.__dict__, "ledger": ledger})


def test_constructor_and_reads_never_reconcile_mutate_or_enable_dispatch(tmp_path):
    subject = opened(tmp_path)
    _, _, process, attempt, reserved = prepared(subject)
    reopened = subject.module.RuntimeLedger(DomainStore(subject.legacy), clock_ms=lambda: subject.clock[0])
    assert reopened.get_attempt(attempt.attempt_id) == reserved
    assert reopened.get_attempt(attempt.attempt_id) == reserved
    with pytest.raises(subject.module.StartupReconciliationRequired):
        reopened._commit_unbudgeted_send_intent_for_test(
            identifier(), attempt.attempt_id, process, expected_revision=1)
    assert reopened.get_attempt(attempt.attempt_id) == reserved


def test_unknown_ids_and_bounded_arguments_fail_explicitly(tmp_path):
    subject = opened(tmp_path)
    missing = identifier()
    for call in (
        lambda: subject.ledger.get_run(missing),
        lambda: subject.ledger.get_execution(missing),
        lambda: subject.ledger.get_attempt(missing),
        lambda: subject.ledger.read_checkpoint(missing, "main"),
    ):
        with pytest.raises(KeyError):
            call()
    with pytest.raises(ValueError):
        subject.ledger.events(after_sequence=True, limit=1)
    with pytest.raises(ValueError):
        subject.ledger.events(after_sequence=0, limit=0)
    with pytest.raises(ValueError):
        subject.ledger.attempt_journal(missing, after_sequence=True)
    with pytest.raises(DomainContractError):
        subject.ledger.checkpoint_for_replay(missing, "main", revision=True)
    with pytest.raises(ValueError):
        subject.module.OwnerIdentity(identifier(), True, 0, identifier())
