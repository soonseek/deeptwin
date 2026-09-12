"""Real SQLite budget tests; no provider calls, credentials or user database."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib
import sqlite3
import tracemalloc
from uuid import uuid4

import pytest

from app.storage import Store


def api():
    if importlib.util.find_spec("app.runtime.budgets") is None:
        pytest.fail("Missing durable runtime budget implementation")
    return importlib.import_module("app.runtime.budgets")


def policy(module, *, mode="subscription", **changes):
    values = dict(profile="execution", provider_mode=mode, max_model_calls=3,
                  max_tool_calls=5, max_node_visits=7, max_loop_rounds=2,
                  max_output_bytes=1000, max_concurrency=2, max_wall_seconds=60,
                  currency="USD" if mode == "api" else None,
                  max_api_microunits=500 if mode == "api" else None)
    values.update(changes)
    return module.BudgetPolicy.create(**values)


def opened(tmp_path, *, mode="subscription", **changes):
    module = api()
    now = [1000]
    legacy = Store(tmp_path / "vault")
    book = module.BudgetBook(legacy, clock=lambda: now[0])
    session = str(uuid4())
    book.start(session, policy(module, mode=mode, **changes))
    return module, legacy, book, session, now


def test_existing_book_rejects_database_symlink_swap_without_touching_target(tmp_path):
    module = api()
    primary = Store(tmp_path / "primary")
    victim = Store(tmp_path / "victim")
    book = module.BudgetBook(primary, clock=lambda: 1_000)
    module.BudgetBook(victim, clock=lambda: 1_000)
    saved_primary = primary.path.with_name("saved-intake.sqlite3")
    primary.path.rename(saved_primary)
    primary.path.symlink_to(victim.path)
    session = str(uuid4())

    with pytest.raises(module.CorruptBudget, match="unsafe"):
        book.start(session, policy(module))

    with sqlite3.connect(victim.path) as db:
        assert db.execute(
            "SELECT count(*) FROM runtime_budget_sessions WHERE id=?", (session,)
        ).fetchone() == (0,)
    assert saved_primary.is_file()


def test_uppercase_table_trigger_is_rejected_on_existing_budget_book(tmp_path):
    module, legacy, book, session, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute(
            """CREATE TRIGGER UPPERCASE_BUDGET_TRIGGER
            AFTER UPDATE ON RUNTIME_BUDGET_SESSIONS
            BEGIN SELECT 1; END"""
        )

    with pytest.raises(module.CorruptBudget, match="trigger"):
        book.status(session)


def reserve(book, session, *, request=None, **changes):
    values = dict(model_calls=1, tool_calls=0, node_visits=1, loop_rounds=0,
                  output_bytes=100, candidates=0, api_microunits=None)
    values.update(changes)
    return book.reserve(session, request or str(uuid4()), **values)


@pytest.mark.parametrize("field,value", [
    ("max_model_calls", True), ("max_model_calls", 0), ("max_tool_calls", -1),
    ("max_output_bytes", 2 ** 63), ("max_concurrency", 0), ("max_wall_seconds", 0),
])
def test_policy_rejects_unbounded_or_bool_limits(field, value):
    module = api()
    with pytest.raises(ValueError):
        policy(module, **{field: value})


def test_api_requires_explicit_positive_currency_cap_and_subscription_does_not_fake_one():
    module = api()
    with pytest.raises(ValueError):
        policy(module, mode="api", currency=None, max_api_microunits=None)
    with pytest.raises(ValueError):
        policy(module, mode="api", max_api_microunits=0)
    with pytest.raises(ValueError):
        policy(module, mode="subscription", currency="USD", max_api_microunits=500)
    assert policy(module).max_api_microunits is None


def test_recommended_profiles_are_finite_and_api_still_needs_a_cap():
    module = api()
    execution = module.BudgetPolicy.recommended("execution", provider_mode="subscription")
    design = module.BudgetPolicy.recommended("design", provider_mode="subscription")
    growth = module.BudgetPolicy.recommended("growth", provider_mode="subscription")
    assert (execution.max_model_calls, execution.max_tool_calls, execution.max_node_visits,
            execution.max_wall_seconds, execution.max_concurrency) == (100, 200, 200, 1800, 2)
    assert (design.max_model_calls, design.max_candidates, design.max_wall_seconds) == (64, 12, 1200)
    assert (growth.max_loop_rounds, growth.max_model_calls, growth.max_tool_calls,
            growth.max_wall_seconds) == (10, 500, 1000, 7200)
    with pytest.raises(ValueError):
        module.BudgetPolicy.recommended("execution", provider_mode="api")


def test_restart_preserves_consumed_budget_and_original_deadline(tmp_path):
    module, legacy, book, session, now = opened(tmp_path)
    item = reserve(book, session)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=40,
                candidates=0, api_microunits=None)
    now[0] = 1020
    reopened = module.BudgetBook(legacy, clock=lambda: now[0])
    status = reopened.status(session)
    assert status["deadline"] == 1060
    assert status["remaining"]["model_calls"] == 2
    with pytest.raises(module.SessionConflict):
        reopened.start(session, policy(module, max_model_calls=4))


def test_exact_duplicate_start_is_idempotent_and_forged_policy_is_rejected(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    now = [1000]
    book = module.BudgetBook(legacy, clock=lambda: now[0])
    session = str(uuid4())
    original = policy(module)
    first = book.start(session, original)
    assert book.start(session, original) == first
    with pytest.raises(ValueError):
        book.start(str(uuid4()), replace(original, id="0" * 64))


def test_expired_session_and_clock_rollback_never_reset_wall_budget(tmp_path):
    module, legacy, book, session, now = opened(tmp_path)
    now[0] = 1060
    with pytest.raises(module.BudgetExceeded):
        reserve(book, session)
    now[0] = 999
    reopened = module.BudgetBook(legacy, clock=lambda: now[0])
    with pytest.raises(module.ClockError):
        reopened.status(session)


def test_exact_duplicate_reservation_remains_readable_after_deadline_but_cannot_newly_dispatch(tmp_path):
    module, _, book, session, now = opened(tmp_path)
    request = str(uuid4())
    item = reserve(book, session, request=request)
    now[0] = 1060
    assert reserve(book, session, request=request) == item
    with pytest.raises(module.BudgetExceeded):
        book.mark_dispatched(request)
    with pytest.raises(module.BudgetExceeded):
        reserve(book, session)


@pytest.mark.parametrize("mutation", ["policy_hash", "negative_counter", "active_over_cap"])
def test_persisted_budget_tampering_fails_closed(tmp_path, mutation):
    module, legacy, book, session, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        if mutation == "policy_hash":
            db.execute("UPDATE runtime_budget_sessions SET policy_hash=? WHERE id=?",
                       ("0" * 64, session))
        elif mutation == "negative_counter":
            db.execute("UPDATE runtime_budget_sessions SET model_calls=-1 WHERE id=?", (session,))
        else:
            db.execute("UPDATE runtime_budget_sessions SET active=99 WHERE id=?", (session,))
    with pytest.raises(module.CorruptBudget):
        book.status(session)


def test_session_counters_must_equal_reservation_ledger_before_more_work(tmp_path):
    module, legacy, book, session, _ = opened(
        tmp_path, max_model_calls=1, max_node_visits=1,
        max_output_bytes=100, max_concurrency=1)
    reserve(book, session)
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE runtime_budget_sessions SET model_calls=0,node_visits=0,"
                   "output_bytes=0,active=0 WHERE id=?", (session,))
    with pytest.raises(module.CorruptBudget):
        reserve(book, session)


@pytest.mark.parametrize("mutation", ["negative", "hash", "state"])
def test_persisted_reservation_tampering_fails_closed(tmp_path, mutation):
    module, legacy, book, session, _ = opened(tmp_path)
    request = str(uuid4())
    reserve(book, session, request=request)
    with sqlite3.connect(legacy.path) as db:
        if mutation == "negative":
            db.execute("UPDATE runtime_budget_reservations SET model_calls=-1 "
                       "WHERE request_id=?", (request,))
        elif mutation == "hash":
            db.execute("UPDATE runtime_budget_reservations SET request_hash=? "
                       "WHERE request_id=?", ("0" * 64, request))
        else:
            db.execute("UPDATE runtime_budget_reservations SET state='forged' "
                       "WHERE request_id=?", (request,))
    with pytest.raises(module.CorruptBudget):
        reserve(book, session, request=request)


def test_observed_usage_above_reservation_is_recorded_and_blocks_new_dispatch(tmp_path):
    module, _, book, session, _ = opened(tmp_path, mode="api")
    item = reserve(book, session, api_microunits=100)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=100,
                candidates=0, api_microunits=200)
    status = book.status(session)
    assert status["blocked_reason"] == "reservation_overrun"
    assert status["remaining"]["api_microunits"] == 300
    assert status["overrun"]["api_microunits"] == 0
    assert status["usage_finality"] == "known_overrun"
    with pytest.raises(module.BudgetExceeded):
        reserve(book, session, api_microunits=1)


def test_observed_usage_above_session_cap_preserves_exact_overrun(tmp_path):
    _, _, book, session, _ = opened(tmp_path, mode="api")
    item = reserve(book, session, api_microunits=400)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=100,
                candidates=0, api_microunits=600)
    status = book.status(session)
    assert status["blocked_reason"] == "reservation_overrun"
    assert status["remaining"]["api_microunits"] == 0
    assert status["overrun"]["api_microunits"] == 100


def test_multiple_extreme_overages_preserve_overflow_fact_and_exact_decimal_total(tmp_path):
    module, _, book, session, _ = opened(
        tmp_path, max_model_calls=2, max_node_visits=2,
        max_output_bytes=200, max_concurrency=2)
    first = reserve(book, session)
    second = reserve(book, session)
    book.mark_dispatched(first.request_id)
    book.mark_dispatched(second.request_id)
    for item in (first, second):
        book.settle(item.request_id, usage_finality="known",
                    model_calls=module.MAX_INTEGER, tool_calls=0,
                    node_visits=1, loop_rounds=0, output_bytes=100,
                    candidates=0, api_microunits=None)
    status = book.status(session)
    assert status["accounting_overflow"] is True
    assert status["overflow_dimensions"] == ["model_calls"]
    assert status["overflow_exact_totals"]["model_calls"] == str(2 * module.MAX_INTEGER)
    assert status["overrun"]["model_calls"] == module.MAX_INTEGER
    assert status["blocked_reason"] == "reservation_overrun"


def test_cancelling_preexisting_reservation_recomputes_saturated_accounting(tmp_path):
    module, _, book, session, _ = opened(
        tmp_path, max_model_calls=2, max_node_visits=2,
        max_output_bytes=200, max_concurrency=2)
    first = reserve(book, session)
    second = reserve(book, session)
    book.mark_dispatched(first.request_id)
    book.settle(first.request_id, usage_finality="known",
                model_calls=module.MAX_INTEGER, tool_calls=0,
                node_visits=1, loop_rounds=0, output_bytes=100,
                candidates=0, api_microunits=None)
    assert book.status(session)["accounting_overflow"] is True
    book.cancel_before_dispatch(second.request_id)
    status = book.status(session)
    assert status["accounting_overflow"] is False
    assert status["overflow_dimensions"] == []
    assert status["remaining"]["model_calls"] == 0


def test_design_candidate_budget_is_reserved_and_cannot_be_bypassed(tmp_path):
    module, _, book, session, _ = opened(tmp_path, max_candidates=1)
    item = reserve(book, session, candidates=1)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=100,
                candidates=1, api_microunits=None)
    with pytest.raises(module.BudgetExceeded):
        reserve(book, session, candidates=1)
    assert book.status(session)["remaining"]["candidates"] == 0


def test_pending_reservation_is_not_reported_as_all_usage_known(tmp_path):
    _, _, book, session, _ = opened(tmp_path, max_concurrency=2)
    completed = reserve(book, session)
    book.mark_dispatched(completed.request_id)
    book.settle(completed.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=40,
                candidates=0, api_microunits=None)
    reserve(book, session)
    assert book.status(session)["usage_finality"] == "pending"


def test_parallel_reservations_share_one_atomic_call_and_concurrency_cap(tmp_path):
    module, _, book, session, _ = opened(tmp_path, max_model_calls=1, max_concurrency=1)
    def attempt(_):
        try:
            return reserve(book, session)
        except module.BudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(item is not None for item in results) == 1
    assert book.status(session)["remaining"]["model_calls"] == 0


@pytest.mark.parametrize("field,request_field", [
    ("max_model_calls", "model_calls"), ("max_tool_calls", "tool_calls"),
    ("max_node_visits", "node_visits"), ("max_loop_rounds", "loop_rounds"),
    ("max_output_bytes", "output_bytes"), ("max_candidates", "candidates"),
])
def test_each_dimension_is_checked_before_reservation(tmp_path, field, request_field):
    module, _, book, session, _ = opened(tmp_path, **{field: 1})
    changes = dict(model_calls=0, node_visits=0, output_bytes=0)
    changes[request_field] = 2
    with pytest.raises(module.BudgetExceeded):
        reserve(book, session, **changes)
    assert book.status(session)["reservation_count"] == 0


def test_api_reservation_is_required_and_unknown_usage_retains_maxima(tmp_path):
    module, _, book, session, _ = opened(tmp_path, mode="api")
    with pytest.raises(module.BudgetExceeded):
        reserve(book, session)
    item = reserve(book, session, api_microunits=200)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="unknown")
    status = book.status(session)
    assert status["remaining"]["api_microunits"] == 300
    assert status["remaining"]["model_calls"] == 2
    assert status["active_reservations"] == 1
    assert status["usage_finality"] == "unknown"


def test_unknown_usage_rejects_candidate_counts_instead_of_silently_ignoring_them(tmp_path):
    module, _, book, session, _ = opened(tmp_path, max_candidates=1)
    item = reserve(book, session, candidates=1)
    book.mark_dispatched(item.request_id)
    with pytest.raises(ValueError):
        book.settle(item.request_id, usage_finality="unknown", candidates=1)
    assert book.status(session)["usage_finality"] == "pending"


def test_known_usage_requires_explicit_candidate_count_and_cannot_refund_by_omission(tmp_path):
    module, _, book, session, _ = opened(tmp_path, max_candidates=1)
    item = reserve(book, session, candidates=1)
    book.mark_dispatched(item.request_id)
    with pytest.raises(ValueError):
        book.settle(item.request_id, usage_finality="known", model_calls=1,
                    tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=10,
                    api_microunits=None)
    assert book.status(session)["remaining"]["candidates"] == 0


def test_unknown_reconciliation_requires_explicit_candidate_count(tmp_path):
    module, _, book, session, _ = opened(tmp_path, max_candidates=1)
    item = reserve(book, session, candidates=1)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="unknown")
    with pytest.raises(TypeError):
        book.reconcile_unknown(item.request_id, model_calls=1, tool_calls=0,
                               node_visits=1, loop_rounds=0, output_bytes=10,
                               api_microunits=None)
    assert book.status(session)["remaining"]["candidates"] == 0


def test_subscription_budget_never_claims_currency_remaining(tmp_path):
    _, _, book, session, _ = opened(tmp_path)
    assert book.status(session)["remaining"]["api_microunits"] is None
    with pytest.raises(ValueError):
        reserve(book, session, api_microunits=1)


def test_duplicate_request_is_idempotent_but_payload_change_conflicts(tmp_path):
    module, _, book, session, _ = opened(tmp_path)
    request = str(uuid4())
    first = reserve(book, session, request=request)
    assert reserve(book, session, request=request) == first
    with pytest.raises(module.RequestConflict):
        reserve(book, session, request=request, output_bytes=101)
    assert book.status(session)["reservation_count"] == 1


def test_cancel_before_dispatch_releases_capacity_but_dispatched_work_does_not(tmp_path):
    module, _, book, session, _ = opened(tmp_path, max_model_calls=1, max_concurrency=1)
    first = reserve(book, session)
    book.cancel_before_dispatch(first.request_id)
    assert book.status(session)["remaining"]["model_calls"] == 1
    second = reserve(book, session)
    book.mark_dispatched(second.request_id)
    with pytest.raises(module.ReservationConflict):
        book.cancel_before_dispatch(second.request_id)
    assert book.status(session)["remaining"]["model_calls"] == 0


def test_known_usage_reconciles_conservative_bytes_and_currency(tmp_path):
    _, _, book, session, _ = opened(tmp_path, mode="api")
    item = reserve(book, session, output_bytes=400, api_microunits=300)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=120,
                candidates=0, api_microunits=100)
    status = book.status(session)
    assert status["remaining"]["output_bytes"] == 880
    assert status["remaining"]["api_microunits"] == 400
    assert status["active_reservations"] == 0
    assert status["usage_finality"] == "known"


def test_unknown_usage_can_only_be_reconciled_once_within_original_maxima(tmp_path):
    module, _, book, session, _ = opened(tmp_path, mode="api")
    item = reserve(book, session, output_bytes=400, api_microunits=300)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="unknown")
    book.reconcile_unknown(item.request_id, model_calls=1, tool_calls=0, node_visits=1,
                           loop_rounds=0, output_bytes=40, candidates=0,
                           api_microunits=150)
    with pytest.raises(module.ReservationConflict):
        book.reconcile_unknown(item.request_id, model_calls=1, tool_calls=0, node_visits=1,
                               loop_rounds=0, output_bytes=40, candidates=0,
                               api_microunits=150)
    assert book.status(session)["active_reservations"] == 0


def test_retry_is_a_new_audited_reservation_and_consumes_budget(tmp_path):
    _, _, book, session, _ = opened(tmp_path, max_model_calls=2)
    first = reserve(book, session)
    book.mark_dispatched(first.request_id)
    book.settle(first.request_id, usage_finality="unknown")
    second = reserve(book, session)
    assert second.request_id != first.request_id
    assert book.status(session)["remaining"]["model_calls"] == 0


def test_transaction_failure_rolls_back_reservation_and_counters(tmp_path, monkeypatch):
    _, _, book, session, _ = opened(tmp_path)

    def fail_accounting(*_args, **_kwargs):
        raise sqlite3.IntegrityError("synthetic accounting failure")

    monkeypatch.setattr(book, "_synchronize_accounting", fail_accounting)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic accounting failure"):
        reserve(book, session)
    status = book.status(session)
    assert status["reservation_count"] == 0
    assert status["remaining"]["model_calls"] == 3


def test_cancelled_reservations_still_have_a_finite_ledger_row_cap(tmp_path):
    module, _, book, session, _ = opened(
        tmp_path, max_model_calls=1, max_tool_calls=1, max_node_visits=1,
        max_loop_rounds=1, max_candidates=1)
    for _ in range(5):
        item = reserve(book, session)
        book.cancel_before_dispatch(item.request_id)
    with pytest.raises(module.BudgetExceeded):
        reserve(book, session)
    assert book.status(session)["reservation_slots_remaining"] == 0


def test_deleting_zero_charge_reservation_cannot_reopen_row_capacity(tmp_path):
    module, legacy, book, session, _ = opened(
        tmp_path, max_model_calls=1, max_tool_calls=1, max_node_visits=1,
        max_loop_rounds=1, max_candidates=1)
    item = reserve(book, session)
    book.cancel_before_dispatch(item.request_id)
    with sqlite3.connect(legacy.path) as db:
        db.execute("DELETE FROM runtime_budget_reservations WHERE request_id=?",
                   (item.request_id,))
    with pytest.raises(module.CorruptBudget):
        book.status(session)


def test_deleting_trailing_reservation_and_audit_events_conflicts_with_persisted_head(tmp_path):
    module, legacy, book, session, _ = opened(tmp_path)
    item = reserve(book, session)
    book.cancel_before_dispatch(item.request_id)
    with sqlite3.connect(legacy.path) as db:
        db.execute("DELETE FROM runtime_budget_audit WHERE request_id=?", (item.request_id,))
        db.execute("DELETE FROM runtime_budget_reservations WHERE request_id=?", (item.request_id,))
        db.execute("UPDATE runtime_budget_sessions SET reservation_rows=0 WHERE id=?", (session,))
    with pytest.raises(module.CorruptBudget):
        book.status(session)


def test_coherent_actual_and_session_rewrite_conflicts_with_append_only_audit(tmp_path):
    module, legacy, book, session, _ = opened(
        tmp_path, max_model_calls=1, max_node_visits=1, max_output_bytes=100)
    item = reserve(book, session)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=100,
                candidates=0, api_microunits=None)
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE runtime_budget_reservations SET actual_model_calls=0,"
                   "actual_node_visits=0,actual_output_bytes=0 WHERE request_id=?",
                   (item.request_id,))
        db.execute("UPDATE runtime_budget_sessions SET model_calls=0,node_visits=0,"
                   "output_bytes=0 WHERE id=?", (session,))
    with pytest.raises(module.CorruptBudget):
        book.status(session)


def test_unknown_cannot_be_rewritten_as_cancelled_with_counters_reset(tmp_path):
    module, legacy, book, session, _ = opened(tmp_path)
    item = reserve(book, session)
    book.mark_dispatched(item.request_id)
    book.settle(item.request_id, usage_finality="unknown")
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE runtime_budget_reservations SET state='cancelled',"
                   "dispatched_at=NULL,usage_finality='not_dispatched' WHERE request_id=?",
                   (item.request_id,))
        db.execute("UPDATE runtime_budget_sessions SET model_calls=0,node_visits=0,"
                   "output_bytes=0,active=0 WHERE id=?", (session,))
    with pytest.raises(module.CorruptBudget):
        book.status(session)


def test_pending_work_takes_status_precedence_over_prior_overage(tmp_path):
    _, _, book, session, _ = opened(tmp_path, mode="api", max_concurrency=2,
                                    max_model_calls=3, max_node_visits=3,
                                    max_output_bytes=300)
    first = reserve(book, session, api_microunits=100)
    reserve(book, session, api_microunits=100)
    book.mark_dispatched(first.request_id)
    book.settle(first.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=101,
                candidates=0, api_microunits=100)
    # Existing reserved work remains pending after an overrun, even though no
    # new reservation or dispatch can be authorized.
    assert book.status(session)["usage_finality"] == "pending"


def test_settlement_before_dispatch_timestamp_is_corrupt(tmp_path):
    module, legacy, book, session, now = opened(tmp_path)
    item = reserve(book, session)
    now[0] = 1002
    book.mark_dispatched(item.request_id)
    now[0] = 1003
    book.settle(item.request_id, usage_finality="known", model_calls=1,
                tool_calls=0, node_visits=1, loop_rounds=0, output_bytes=100,
                candidates=0, api_microunits=None)
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE runtime_budget_reservations SET settled_at=1001 WHERE request_id=?",
                   (item.request_id,))
    with pytest.raises(module.CorruptBudget):
        book.status(session)


def test_budget_connections_enable_required_sqlite_durability_settings(tmp_path):
    _, _, book, session, _ = opened(tmp_path)
    assert book.status(session)["session_id"] == session
    settings = book.sqlite_settings()
    assert settings["journal_mode"].casefold() == "wal"
    assert settings["synchronous"] == 2
    assert settings["fullfsync"] == 1
    assert settings["foreign_keys"] == 1
    assert settings["trusted_schema"] == 0


def test_budget_schema_is_installed_by_hashed_component_migration(tmp_path):
    module, legacy, _, _, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        row = db.execute("SELECT sha256 FROM runtime_migrations "
                         "WHERE component='budgets' AND version=1").fetchone()
    assert row == (module.RUNTIME_MIGRATION_SHA256,)


def test_runtime_migration_preserves_other_components_and_rejects_digest_tampering(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    with sqlite3.connect(legacy.path) as db:
        db.execute("CREATE TABLE runtime_migrations(component TEXT NOT NULL,"
                   "version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0),"
                   "sha256 TEXT NOT NULL,PRIMARY KEY(component,version))")
        db.execute("INSERT INTO runtime_migrations VALUES ('ledger',1,?)", ("1" * 64,))
    module.BudgetBook(legacy, clock=lambda: 1000)
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT sha256 FROM runtime_migrations WHERE component='ledger'").fetchone() == ("1" * 64,)
        db.execute("UPDATE runtime_migrations SET sha256=? WHERE component='budgets'", ("0" * 64,))
    with pytest.raises(module.CorruptBudget):
        module.BudgetBook(legacy, clock=lambda: 1000)


def test_migration_constraint_probe_never_deletes_another_component(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    foreign = "__budget_schema_constraint_probe__"
    with sqlite3.connect(legacy.path) as db:
        db.execute("CREATE TABLE runtime_migrations(component TEXT NOT NULL,"
                   "version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0),"
                   "sha256 TEXT NOT NULL,PRIMARY KEY(component,version))")
        db.execute("INSERT INTO runtime_migrations VALUES (?,?,?)",
                   (foreign, 2, "f" * 64))
    module.BudgetBook(legacy, clock=lambda: 1000)
    with sqlite3.connect(legacy.path) as db:
        assert db.execute(
            "SELECT version,sha256 FROM runtime_migrations WHERE component=?", (foreign,)
        ).fetchone() == (2, "f" * 64)


def test_unversioned_partial_budget_schema_fails_closed(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    with sqlite3.connect(legacy.path) as db:
        db.execute("CREATE TABLE runtime_budget_sessions(id TEXT PRIMARY KEY)")
    with pytest.raises(module.CorruptBudget):
        module.BudgetBook(legacy, clock=lambda: 1000)


def test_version_row_does_not_hide_budget_schema_rewrite(tmp_path):
    module, legacy, _, _, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute("ALTER TABLE runtime_budget_sessions ADD COLUMN forged TEXT")
    with pytest.raises(module.CorruptBudget):
        module.BudgetBook(legacy, clock=lambda: 1000)


def test_weakened_shared_migration_constraints_fail_closed(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    with sqlite3.connect(legacy.path) as db:
        db.execute("CREATE TABLE runtime_migrations(component TEXT NOT NULL,"
                   "version INTEGER NOT NULL,sha256 TEXT NOT NULL,"
                   "PRIMARY KEY(component,version))")
    with pytest.raises(module.CorruptBudget):
        module.BudgetBook(legacy, clock=lambda: 1000)


@pytest.mark.parametrize("object_kind", ["trigger", "index"])
def test_unregistered_objects_on_owned_runtime_tables_fail_closed(tmp_path, object_kind):
    module, legacy, _, _, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        if object_kind == "trigger":
            db.execute("CREATE TRIGGER injected_budget_trigger BEFORE INSERT ON "
                       "runtime_budget_reservations BEGIN SELECT RAISE(ABORT,'blocked'); END")
        else:
            db.execute("CREATE INDEX injected_budget_index ON runtime_budget_sessions(blocked_reason)")
    with pytest.raises(module.CorruptBudget):
        module.BudgetBook(legacy, clock=lambda: 1000)


def test_cancelled_only_session_has_known_zero_usage_not_pending_work(tmp_path):
    _, _, book, session, _ = opened(tmp_path)
    item = reserve(book, session)
    book.cancel_before_dispatch(item.request_id)
    status = book.status(session)
    assert status["active_reservations"] == 0
    assert status["reservation_count"] == 0
    assert status["usage_finality"] == "known"


def test_non_blob_persisted_policy_fails_before_size_based_bytes_allocation(tmp_path):
    module, legacy, book, session, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE runtime_budget_sessions SET policy=10000000 WHERE id=?", (session,))
    tracemalloc.start()
    try:
        with pytest.raises(module.CorruptBudget):
            book.status(session)
        _, peak = tracemalloc.get_traced_memory()
        assert peak < 1024 * 1024
    finally:
        tracemalloc.stop()
