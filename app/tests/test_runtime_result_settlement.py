"""T040: semantic result acceptance and budget settlement in one shared
transaction (resumption-plan Continuation: the public `accept_result` and
`settle` each own a transaction; calling them in sequence is not the required
atomic integration).

`RuntimeLedger.accept_result_and_settle` records the terminal result and, for
an accepted classification, settles the attempt's budget reservation on the
same caller-owned SQLite transaction the ledger opened; a duplicate or late
classification settles nothing; a budget failure rolls the acceptance back;
exact replay returns the stored result without touching the reservation
again. No provider or worker is invoked.
"""

import sqlite3
from dataclasses import replace

import pytest

from app.runtime import budgets as budgets_module
from app.runtime import ledger as ledger_module
from app.runtime.budgets import (
    BudgetBook,
    BudgetError,
    BudgetUsage,
    CorruptBudget,
    ReservationConflict,
)
from app.runtime.ledger import (
    AttemptSpec,
    ExecutionSpec,
    LedgerError,
    OwnerIdentity,
    ResultObservation,
)
from app.storage import Store
from app.tests.test_runtime_budget_dispatch import (
    budget_row,
    commit,
    identifier,
    immutable,
    opened,
    prepare,
)


def dispatched(tmp_path):
    subject = opened(tmp_path)
    owner, attempt, request, _ = prepare(subject)
    permit = commit(subject, owner, attempt, request)
    subject.refs.result = immutable(subject.domain, subject.domain.roots(), "artifact")
    return subject, attempt, request, permit


def observation(subject, attempt_id, **changes):
    value = ResultObservation(
        observation_id=identifier(), attempt_id=attempt_id, outcome="succeeded",
        result_ref=subject.refs.result, usage_finality="final",
        remote_terminal_observed="succeeded", reason_code="provider_terminal",
    )
    return replace(value, **changes) if changes else value


def usage(**changes):
    values = {"model_calls": 1, "tool_calls": 0, "node_visits": 1, "loop_rounds": 0,
              "output_bytes": 80, "candidates": 0, "api_microunits": None}
    return BudgetUsage.create(**{**values, **changes})


def command_rows(subject, kind):
    with sqlite3.connect(subject.legacy.path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            "SELECT * FROM runtime_commands WHERE kind=?", (kind,))]


def test_accepted_result_and_settlement_commit_together(tmp_path):
    subject, attempt, request, _ = dispatched(tmp_path)
    accepted = observation(subject, attempt.attempt_id)
    command_id = identifier()
    outcome = subject.ledger.accept_result_and_settle(
        command_id, accepted, budget_book=subject.book, usage=usage()
    )
    assert outcome["classification"] == "accepted"
    assert outcome["attempt"]["terminal_outcome"] == "succeeded"
    assert outcome["settlement"] == {
        "request_id": request.request_id, "state": "finalized", "usage_finality": "known",
    }
    row = budget_row(subject, request.request_id)
    assert row["state"] == "finalized" and row["usage_finality"] == "known"
    assert row["actual_model_calls"] == 1 and row["actual_output_bytes"] == 80
    assert subject.ledger.get_attempt(attempt.attempt_id)["terminal_outcome"] == "succeeded"
    assert subject.book.status(subject.budget_session_id)["active_reservations"] == 0
    # one command, one observation, replay without a second settlement
    assert len(command_rows(subject, "accept_result_and_settle")) == 1
    audits_before = audit_count(subject, request.request_id)
    replay = subject.ledger.accept_result_and_settle(
        command_id, accepted, budget_book=subject.book, usage=usage()
    )
    assert replay == outcome
    assert audit_count(subject, request.request_id) == audits_before
    assert len(command_rows(subject, "accept_result_and_settle")) == 1


def audit_count(subject, request_id):
    with sqlite3.connect(subject.legacy.path) as db:
        return db.execute(
            "SELECT count(*) FROM runtime_budget_audit WHERE request_id=?", (request_id,)
        ).fetchone()[0]


def test_unknown_usage_settles_unknown_and_retains_the_reservation(tmp_path):
    subject, attempt, request, _ = dispatched(tmp_path)
    unknown = observation(
        subject, attempt.attempt_id, outcome="outcome_unknown", result_ref=None,
        usage_finality="unknown", remote_terminal_observed="not_observed",
        reason_code="transport_unknown",
    )
    outcome = subject.ledger.accept_result_and_settle(
        identifier(), unknown, budget_book=subject.book, usage=None
    )
    assert outcome["classification"] == "accepted"
    assert outcome["settlement"]["state"] == "unknown"
    assert budget_row(subject, request.request_id)["state"] == "unknown"
    # a provisional usage finality also retains the full reservation
    subject2, attempt2, _request2, _ = dispatched(tmp_path / "second")
    provisional = observation(subject2, attempt2.attempt_id, usage_finality="provisional")
    outcome2 = subject2.ledger.accept_result_and_settle(
        identifier(), provisional, budget_book=subject2.book, usage=None
    )
    assert outcome2["settlement"]["state"] == "unknown"


def test_usage_must_match_the_finality_and_the_book_must_share_the_vault(tmp_path):
    subject, attempt, request, _ = dispatched(tmp_path)
    accepted = observation(subject, attempt.attempt_id)
    with pytest.raises(ValueError):
        subject.ledger.accept_result_and_settle(
            identifier(), accepted, budget_book=subject.book, usage=None
        )  # final usage needs the counters
    unknown = observation(
        subject, attempt.attempt_id, usage_finality="unknown", outcome="failed",
        result_ref=None, remote_terminal_observed="failed", reason_code="provider_terminal",
    )
    with pytest.raises(ValueError):
        subject.ledger.accept_result_and_settle(
            identifier(), unknown, budget_book=subject.book, usage=usage()
        )  # unknown usage retains the reservation: no counters
    with pytest.raises(TypeError):
        subject.ledger.accept_result_and_settle(
            identifier(), accepted, budget_book=subject.book, usage={"model_calls": 1}
        )
    other = BudgetBook(Store(tmp_path / "other-vault"), clock=lambda: 100)
    with pytest.raises(LedgerError):
        subject.ledger.accept_result_and_settle(
            identifier(), accepted, budget_book=other, usage=usage()
        )
    with pytest.raises(TypeError):
        subject.ledger.accept_result_and_settle(
            identifier(), accepted, budget_book=object(), usage=usage()
        )
    assert subject.ledger.get_attempt(attempt.attempt_id)["terminal_outcome"] is None
    assert budget_row(subject, request.request_id)["state"] == "dispatched"
    assert command_rows(subject, "accept_result_and_settle") == []


def test_duplicate_and_late_results_settle_nothing(tmp_path):
    subject, attempt, request, _ = dispatched(tmp_path)
    accepted = observation(subject, attempt.attempt_id)
    subject.ledger.accept_result_and_settle(
        identifier(), accepted, budget_book=subject.book, usage=usage()
    )
    audits = audit_count(subject, request.request_id)
    duplicate = subject.ledger.accept_result_and_settle(
        identifier(), replace(accepted, observation_id=identifier()),
        budget_book=subject.book, usage=usage(model_calls=3),
    )
    assert duplicate["classification"] == "duplicate" and duplicate["settlement"] is None
    late = subject.ledger.accept_result_and_settle(
        identifier(),
        observation(subject, attempt.attempt_id, outcome="failed", result_ref=None,
                    usage_finality="unknown", remote_terminal_observed="failed",
                    reason_code="provider_terminal"),
        budget_book=subject.book, usage=None,
    )
    assert late["classification"] == "late" and late["settlement"] is None
    row = budget_row(subject, request.request_id)
    assert row["state"] == "finalized" and row["actual_model_calls"] == 1
    assert audit_count(subject, request.request_id) == audits


def test_a_budget_failure_rolls_the_acceptance_back(tmp_path, monkeypatch):
    subject, attempt, request, _ = dispatched(tmp_path)
    accepted = observation(subject, attempt.attempt_id)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("controlled settlement fault")

    monkeypatch.setattr(budgets_module.BudgetBook, "_finalize", fail)
    with pytest.raises(sqlite3.OperationalError):
        subject.ledger.accept_result_and_settle(
            identifier(), accepted, budget_book=subject.book, usage=usage()
        )
    monkeypatch.undo()
    stored = subject.ledger.get_attempt(attempt.attempt_id)
    assert stored["terminal_outcome"] is None and stored["accepted_observation_id"] is None
    assert subject.ledger.result_observations(attempt.attempt_id) == []
    assert budget_row(subject, request.request_id)["state"] == "dispatched"
    assert command_rows(subject, "accept_result_and_settle") == []
    # and a settled reservation cannot be settled again by a later acceptance
    outcome = subject.ledger.accept_result_and_settle(
        identifier(), accepted, budget_book=subject.book, usage=usage()
    )
    assert outcome["classification"] == "accepted"
    with pytest.raises(BudgetError):
        subject.book.settle(request.request_id, usage_finality="known", model_calls=1,
                            tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=1,
                            candidates=0)


def test_overage_settles_as_overage_in_the_same_transaction(tmp_path):
    subject, attempt, request, _ = dispatched(tmp_path)
    accepted = observation(subject, attempt.attempt_id)
    outcome = subject.ledger.accept_result_and_settle(
        identifier(), accepted, budget_book=subject.book, usage=usage(output_bytes=5_000)
    )
    assert outcome["classification"] == "accepted"
    assert outcome["settlement"]["state"] == "overage"
    assert budget_row(subject, request.request_id)["state"] == "overage"
    assert subject.ledger.get_attempt(attempt.attempt_id)["terminal_outcome"] == "succeeded"


def test_sequential_public_methods_are_not_the_integration(tmp_path):
    # documented boundary: two transactions can be torn between them; the plain
    # acceptance strands the reservation, which only the public settle releases
    subject, attempt, request, _ = dispatched(tmp_path)
    accepted = observation(subject, attempt.attempt_id)
    assert subject.ledger.accept_result(identifier(), accepted)["classification"] == "accepted"
    assert budget_row(subject, request.request_id)["state"] == "dispatched"  # not settled
    # the atomic boundary afterwards reuses the accepted observation and settles nothing
    again = subject.ledger.accept_result_and_settle(
        identifier(), accepted, budget_book=subject.book, usage=usage()
    )
    assert again["classification"] == "accepted" and again["settlement"] is None
    assert budget_row(subject, request.request_id)["state"] == "dispatched"
    assert subject.book.settle(request.request_id, usage_finality="unknown") == {
        "request_id": request.request_id, "state": "unknown", "usage_finality": "unknown",
    }
    assert isinstance(ledger_module.RuntimeLedger.accept_result_and_settle, object)


def test_settlement_requires_an_exact_row_transaction(tmp_path):
    subject, _attempt, request, _ = dispatched(tmp_path)
    raw = sqlite3.connect(subject.legacy.path, isolation_level=None)
    try:
        with pytest.raises(CorruptBudget):
            subject.book._settle_in_transaction(
                raw, request.request_id, usage_finality="unknown", usage=None
            )
        raw.row_factory = sqlite3.Row
        with pytest.raises(CorruptBudget):  # rows but no open transaction
            subject.book._settle_in_transaction(
                raw, request.request_id, usage_finality="unknown", usage=None
            )
        raw.execute("BEGIN IMMEDIATE")
        raw.row_factory = None
        with pytest.raises(CorruptBudget):  # a transaction without rows
            subject.book._settle_in_transaction(
                raw, request.request_id, usage_finality="unknown", usage=None
            )
        raw.execute("ROLLBACK")
    finally:
        raw.close()
    assert budget_row(subject, request.request_id)["state"] == "dispatched"


def test_a_reservation_shared_by_another_attempt_is_refused_before_settlement(tmp_path):
    subject, attempt_a, request, _ = dispatched(tmp_path)
    with sqlite3.connect(subject.legacy.path) as db:
        run_id = db.execute(
            "SELECT run_id FROM runtime_node_executions WHERE id=?", (attempt_a.execution_id,)
        ).fetchone()[0]
    execution_b = ExecutionSpec(identifier(), run_id, "writer", identifier(), (1,), ())
    subject.ledger.create_execution(identifier(), execution_b)
    owner_b = OwnerIdentity(identifier(), 4321, 900, identifier())
    attempt_b = AttemptSpec(
        identifier(), execution_b.execution_id, 1, subject.refs.envelope,
        subject.refs.profile, subject.refs.budget, attempt_a.reservation_id,
        "effect:" + identifier(), owner_b, 10_000,
    )
    subject.ledger.reserve_attempt(identifier(), attempt_b, lease_duration_ms=1_000)
    subject.ledger._commit_unbudgeted_send_intent_for_test(
        identifier(), attempt_b.attempt_id, owner_b, expected_revision=1
    )
    with pytest.raises(LedgerError):
        subject.ledger.accept_result_and_settle(
            identifier(), observation(subject, attempt_b.attempt_id),
            budget_book=subject.book, usage=usage(),
        )
    assert budget_row(subject, request.request_id)["state"] == "dispatched"
    assert subject.ledger.get_attempt(attempt_b.attempt_id)["terminal_outcome"] is None
    assert subject.ledger.result_observations(attempt_b.attempt_id) == []
    assert command_rows(subject, "accept_result_and_settle") == []


def test_a_reservation_of_another_budget_session_is_refused(tmp_path):
    subject, attempt, request, _ = dispatched(tmp_path)
    foreign = opened(tmp_path / "foreign")
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("UPDATE runtime_budget_reservations SET session_id=? WHERE request_id=?",
                   (foreign.budget_session_id, request.request_id))
    with pytest.raises(BudgetError):
        subject.ledger.accept_result_and_settle(
            identifier(), observation(subject, attempt.attempt_id),
            budget_book=subject.book, usage=usage(),
        )
    assert subject.ledger.get_attempt(attempt.attempt_id)["terminal_outcome"] is None
    assert command_rows(subject, "accept_result_and_settle") == []


def test_usage_counters_are_validated_before_the_transaction(tmp_path, monkeypatch):
    subject, attempt, request, _ = dispatched(tmp_path)
    opened_transactions = []
    original = subject.ledger._transaction

    def spy(*args, **kwargs):
        opened_transactions.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(subject.ledger, "_transaction", spy)
    forged = BudgetUsage(model_calls=-1, tool_calls=0, node_visits=1, loop_rounds=0,
                         output_bytes=1, candidates=0, api_microunits=None)
    with pytest.raises(ValueError):
        subject.ledger.accept_result_and_settle(
            identifier(), observation(subject, attempt.attempt_id),
            budget_book=subject.book, usage=forged,
        )
    typed = BudgetUsage(model_calls="1", tool_calls=0, node_visits=1, loop_rounds=0,
                        output_bytes=1, candidates=0, api_microunits=None)
    with pytest.raises(ValueError):
        subject.ledger.accept_result_and_settle(
            identifier(), observation(subject, attempt.attempt_id),
            budget_book=subject.book, usage=typed,
        )
    assert opened_transactions == []
    assert budget_row(subject, request.request_id)["state"] == "dispatched"


def test_deadline_quarantine_settles_the_dispatched_reservation_unknown(tmp_path):
    subject, attempt, request, _ = dispatched(tmp_path)
    accepted = observation(subject, attempt.attempt_id)
    subject.ledger_clock[0] = 10_001  # past spec.deadline_at_ms = 10_000
    outcome = subject.ledger.accept_result_and_settle(
        identifier(), accepted, budget_book=subject.book, usage=usage()
    )
    stored = subject.ledger.get_attempt(attempt.attempt_id)
    assert stored["terminal_outcome"] == "timed_out" and stored["usage_finality"] == "unknown"
    assert outcome["classification"] == "late"
    assert outcome["settlement"] == {
        "request_id": request.request_id, "state": "unknown", "usage_finality": "unknown",
    }
    assert budget_row(subject, request.request_id)["state"] == "unknown"
    # a later late result against the quarantined attempt settles nothing more
    audits = audit_count(subject, request.request_id)
    later = subject.ledger.accept_result_and_settle(
        identifier(), replace(accepted, observation_id=identifier()),
        budget_book=subject.book, usage=usage(),
    )
    assert later["classification"] == "late" and later["settlement"] is None
    assert audit_count(subject, request.request_id) == audits
    with pytest.raises(ReservationConflict):
        subject.book.settle(request.request_id, usage_finality="unknown")
