"""T040 slice 4: attempt dispatch through the scheduler (resumption-plan
Continuation "worker/attempt dispatch through the scheduler").

A bound `agent` node visit reserves exactly one ledger attempt with identities
derived from the visit, commits the budgeted send intent, hands the one-shot
permit to a code-owned transport and admits the result only through
`accept_result_and_settle`; the node's `EntityRef` is the accepted result and
nothing else. Restart reconciles by command replay and never re-sends. The
transport here is an in-process fake: no worker, provider or paid call exists
in this slice (the worker-side operation registry is T087/T018).
"""

import pytest

from app.domain.refs import EntityRef
from app.domain.store import DomainStore
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.budgets import BudgetBook, BudgetUsage
from app.runtime.ledger import DispatchPermit, OwnerIdentity, RunSpec, RuntimeLedger
from app.storage import Store
from app.tests.test_graph_contract import compile_value
from app.tests.test_graph_execution import linear_graph
from app.tests.test_runtime_budget_dispatch import (
    budget_row,
    identifier,
    immutable,
    opened,
)


def started(tmp_path):
    subject = opened(tmp_path)
    run = RunSpec(
        identifier(), subject.refs.work, subject.refs.environment, subject.refs.consent,
        "live", subject.refs.budget, subject.budget_session_id, subject.refs.manifest,
    )
    subject.ledger.create_run(identifier(), run)
    subject.refs.result = immutable(subject.domain, subject.domain.roots(), "artifact")
    subject.refs.produced = immutable(subject.domain, subject.domain.roots(), "artifact")
    subject.owner = OwnerIdentity(identifier(), 4321, 900, identifier())
    return subject, run


def restart(subject, tmp_path):
    # Store/DomainStore/RuntimeLedger/BudgetBook keep no connection between operations:
    # a fresh process sees only the durable state
    subject.legacy = Store(tmp_path / "vault")
    subject.domain = DomainStore(subject.legacy)
    subject.book = BudgetBook(subject.legacy, clock=lambda: subject.budget_clock[0])
    subject.ledger = RuntimeLedger(subject.domain, clock_ms=lambda: subject.ledger_clock[0])
    subject.ledger.reconcile_startup(identifier(), observed_owners={})


def binding(subject):
    return na.AttemptBinding.create(
        envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
        budget_policy_ref=subject.refs.budget, deadline_at_ms=10_000,
        lease_duration_ms=1_000, model_calls=1, tool_calls=0, node_visits=1,
        loop_rounds=0, output_bytes=100, candidates=0, api_microunits=None,
        principal=subject.principal, grant=subject.grant,
    )


def succeeded(subject):
    return na.AttemptTransportResult(
        outcome="succeeded", result_ref=subject.refs.produced, usage_finality="final",
        remote_terminal_observed="succeeded", reason_code="provider_terminal",
        usage=BudgetUsage.create(model_calls=1, tool_calls=0, node_visits=1, loop_rounds=0,
                                 output_bytes=80, candidates=0, api_microunits=None),
    )


class Transport:
    def __init__(self, result=None, *, fault=None):
        self.calls = []
        self.result = result
        self.fault = fault

    def __call__(self, permit, request, window):
        # the consumed one-shot window travels with the permit (T087 slice)
        assert type(window).__name__ == "ConsumedDispatchWindow"
        assert window.permit is permit
        self.calls.append((permit, request))
        if self.fault is not None:
            raise self.fault
        return self.result


def dispatcher(subject, transport, *, nodes=("writer",)):
    return na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={node: binding(subject) for node in nodes}, transport=transport,
    )


def handlers(subject, calls, *, agent=None):
    def produce(context, view):
        calls.append(context.node_id)
        assert context.attempt is None
        return subject.refs.result

    def dispatch(context, view):
        calls.append(context.node_id)
        return context.attempt.dispatch()

    return {"core.deterministic": produce, "core.agent": agent or dispatch,
            "core.join": produce, "core.router": produce}


def build(subject, run, attempts, registry):
    return sch.build_scheduler(compile_value(linear_graph()), ledger=subject.ledger,
                               run_id=run.run_id, handlers=registry, attempts=attempts)


def writer_attempt_id(run):
    return na.attempt_identity(run.run_id, "writer", 0, 0)


def test_a_bound_agent_visit_dispatches_one_attempt_and_admits_the_accepted_result(tmp_path):
    subject, run = started(tmp_path)
    transport = Transport(succeeded(subject))
    calls = []
    outcome = build(subject, run, dispatcher(subject, transport), handlers(subject, calls)).run()
    assert calls == ["intake", "writer", "publish"]
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    assert dict(outcome.result_refs)[writer_execution] == subject.refs.produced
    assert set(outcome.__dataclass_fields__) == {
        "run_id", "graph_digest", "completed_node_ids", "execution_ids",
        "result_refs", "counters", "activations", "awaiting_human", "approvals",
        "pending_node_ids", "rejected_human",  # the runs route slice's identities
    }
    # exactly one attempt with visit-derived identities, terminal and accepted
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["spec"]["execution_id"] == writer_execution
    assert stored["spec"]["attempt_no"] == 1
    assert stored["terminal_outcome"] == "succeeded" and stored["phase"] == "terminal"
    assert stored["spec"]["reservation_id"] == na.reservation_identity(attempt_id)
    committed = subject.ledger.lookup_committed_result(
        attempt_id, writer_execution, subject.refs.envelope
    )
    assert EntityRef.from_dict(committed["result_ref"]) == subject.refs.produced
    row = budget_row(subject, na.reservation_identity(attempt_id))
    assert row["state"] == "finalized" and row["actual_output_bytes"] == 80
    assert subject.book.status(subject.budget_session_id)["active_reservations"] == 0
    # the transport saw the one-shot permit and a bounded request: refs, never bytes
    assert len(transport.calls) == 1
    permit, request = transport.calls[0]
    assert type(permit) is DispatchPermit and permit.attempt_id == attempt_id
    assert request == na.AttemptDispatchRequest(
        run_id=run.run_id, node_id="writer", execution_id=writer_execution,
        attempt_id=attempt_id, envelope_ref=subject.refs.envelope,
        profile_ref=subject.refs.profile, deadline_at_ms=10_000,
    )
    # a second run over the same durable head replays: no second attempt or send
    again = build(subject, run, dispatcher(subject, transport), handlers(subject, [])).run()
    assert again.result_refs == outcome.result_refs
    assert len(transport.calls) == 1
    assert subject.ledger.get_attempt(attempt_id)["revision"] == stored["revision"]


def test_restart_after_the_send_never_resends_and_recovery_quarantines_the_attempt(
    tmp_path, monkeypatch
):
    subject, run = started(tmp_path)
    transport = Transport(succeeded(subject))
    calls = []

    def crash(*args, **kwargs):
        raise RuntimeError("PRIVATE_CRASH_CANARY")

    monkeypatch.setattr(subject.ledger, "accept_result_and_settle", crash)
    with pytest.raises(sch.SchedulerError, match="node_failed:writer") as failure:
        build(subject, run, dispatcher(subject, transport), handlers(subject, calls)).run()
    assert "CANARY" not in str(failure.value)
    monkeypatch.undo()
    attempt_id = writer_attempt_id(run)
    sent = subject.ledger.get_attempt(attempt_id)
    assert sent["phase"] == "send_intent" and sent["terminal_outcome"] is None
    # the unconsumed permit is discarded when the acceptance did not commit
    assert not any(
        entry[0].attempt_id == attempt_id for entry in subject.ledger._pending_permits.values()
    )
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "dispatched"
    # the process restarts: the send is may-have-started, so the visit is refused
    # closed and the transport is never asked again
    restart(subject, tmp_path)
    later = Transport(succeeded(subject))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, later), handlers(subject, [])).run()
    assert later.calls == []
    # startup reconciliation sees the dead owner of a may-have-started send and
    # quarantines the attempt as outcome_unknown; no result was ever accepted,
    # no observation exists and the reservation is still dispatched
    after = subject.ledger.get_attempt(attempt_id)
    assert after["terminal_outcome"] == "outcome_unknown"
    assert after["accepted_observation_id"] is None
    assert subject.ledger.result_observations(attempt_id) == []
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "dispatched"
    assert "publish" not in calls


def test_an_unknown_transport_outcome_fails_the_visit_and_retains_the_reservation(tmp_path):
    subject, run = started(tmp_path)
    unknown = na.AttemptTransportResult(
        outcome="outcome_unknown", result_ref=None, usage_finality="unknown",
        remote_terminal_observed="not_observed", reason_code="transport_unknown", usage=None,
    )
    transport = Transport(unknown)
    calls = []
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport), handlers(subject, calls)).run()
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "outcome_unknown"
    assert stored["usage_finality"] == "unknown"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "unknown"
    assert calls == ["intake", "writer"]  # the successor never ran
    assert subject.ledger.lookup_committed_result(
        attempt_id, sch.execution_identity(run.run_id, "writer", 0), subject.refs.envelope
    )["outcome"] == "outcome_unknown"


def test_a_transport_fault_is_recorded_as_outcome_unknown_not_as_success(tmp_path):
    subject, run = started(tmp_path)
    transport = Transport(fault=ConnectionError("PRIVATE_TRANSPORT_CANARY"))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer") as failure:
        build(subject, run, dispatcher(subject, transport), handlers(subject, [])).run()
    assert "CANARY" not in str(failure.value)
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "outcome_unknown"
    assert stored["remote_terminal_observed"] == "not_observed"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "unknown"
    # a transport that returns something other than the typed result is the same
    subject2, run2 = started(tmp_path / "second")
    loose = Transport({"outcome": "succeeded"})
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject2, run2, dispatcher(subject2, loose), handlers(subject2, [])).run()
    stored2 = subject2.ledger.get_attempt(writer_attempt_id(run2))
    assert stored2["terminal_outcome"] == "outcome_unknown"


def test_a_failed_result_is_admitted_and_fails_the_visit(tmp_path):
    subject, run = started(tmp_path)
    failed = na.AttemptTransportResult(
        outcome="failed", result_ref=None, usage_finality="final",
        remote_terminal_observed="failed", reason_code="provider_terminal",
        usage=BudgetUsage.create(model_calls=1, tool_calls=0, node_visits=1, loop_rounds=0,
                                 output_bytes=0, candidates=0, api_microunits=None),
    )
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, Transport(failed)), handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    assert subject.ledger.get_attempt(attempt_id)["terminal_outcome"] == "failed"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "finalized"


def test_only_the_accepted_result_can_be_the_node_result(tmp_path):
    subject, run = started(tmp_path)
    transport = Transport(succeeded(subject))
    calls = []

    def skip(context, view):  # a handler that never dispatches
        calls.append(context.node_id)
        return subject.refs.result

    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport), handlers(subject, calls, agent=skip)).run()
    assert transport.calls == []
    with pytest.raises(KeyError):
        subject.ledger.get_attempt(writer_attempt_id(run))  # nothing was reserved

    def swap(context, view):  # dispatches, then returns another ref
        context.attempt.dispatch()
        return subject.refs.result

    subject2, run2 = started(tmp_path / "second")
    transport2 = Transport(succeeded(subject2))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject2, run2, dispatcher(subject2, transport2), handlers(subject2, [], agent=swap)).run()
    assert len(transport2.calls) == 1
    assert subject2.ledger.get_attempt(writer_attempt_id(run2))["terminal_outcome"] == "succeeded"

    def twice(context, view):  # a visit capability is one-shot
        first = context.attempt.dispatch()
        context.attempt.dispatch()
        return first

    subject3, run3 = started(tmp_path / "third")
    transport3 = Transport(succeeded(subject3))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject3, run3, dispatcher(subject3, transport3), handlers(subject3, [], agent=twice)).run()
    assert len(transport3.calls) == 1


def test_build_refuses_wrong_dispatchers_and_bindings(tmp_path):
    subject, run = started(tmp_path)
    registry = handlers(subject, [])
    with pytest.raises(sch.SchedulerError):
        build(subject, run, object(), registry)
    with pytest.raises(sch.SchedulerError):  # bound to a node that is not an agent node
        build(subject, run, dispatcher(subject, Transport(), nodes=("intake",)), registry)
    with pytest.raises(sch.SchedulerError):  # bound to an unknown node
        build(subject, run, dispatcher(subject, Transport(), nodes=("ghost",)), registry)
    other, _ = started(tmp_path / "other")
    with pytest.raises(sch.SchedulerError):  # a dispatcher over another ledger
        build(subject, run, dispatcher(other, Transport()), registry)
    with pytest.raises(TypeError):
        na.NodeAttemptDispatcher.build(
            ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
            bindings={"writer": binding(subject)}, transport="not-callable",
        )
    with pytest.raises(TypeError):
        na.NodeAttemptDispatcher.build(
            ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
            bindings={"writer": {"envelope_ref": subject.refs.envelope}}, transport=Transport(),
        )
    with pytest.raises(TypeError):
        na.NodeAttemptDispatcher()
    with pytest.raises(ValueError):  # bindings are keyed by node id and non-empty
        na.NodeAttemptDispatcher.build(
            ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
            bindings={}, transport=Transport(),
        )
    with pytest.raises((TypeError, ValueError)):  # ref kinds are exact
        na.AttemptBinding.create(
            envelope_ref=subject.refs.profile, profile_ref=subject.refs.profile,
            budget_policy_ref=subject.refs.budget, deadline_at_ms=10_000,
            lease_duration_ms=1_000, model_calls=1, tool_calls=0, node_visits=1,
            loop_rounds=0, output_bytes=100, candidates=0, api_microunits=None,
            principal=subject.principal, grant=subject.grant,
        )
    # the attempt identities are deterministic in the visit and distinct per index
    first = na.attempt_identity(run.run_id, "writer", 0, 0)
    assert first == na.attempt_identity(run.run_id, "writer", 0, 0)
    assert first != na.attempt_identity(run.run_id, "writer", 1, 0)
    assert first != na.attempt_identity(run.run_id, "writer", 0, 1)
    assert na.reservation_identity(first) != first


def test_restart_before_the_send_reserves_the_next_unsent_attempt_and_dispatches_once(
    tmp_path, monkeypatch
):
    subject, run = started(tmp_path)
    first = Transport(succeeded(subject))

    def crash(*args, **kwargs):
        raise RuntimeError("PRIVATE_CRASH_CANARY")

    monkeypatch.setattr(subject.ledger, "commit_budgeted_send_intent", crash)
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, first), handlers(subject, [])).run()
    monkeypatch.undo()
    assert first.calls == []
    unsent = na.attempt_identity(run.run_id, "writer", 0, 0)
    assert subject.ledger.get_attempt(unsent)["send_finality"] == "not_started"
    # the process restarts: recovery proves the first attempt definitely not sent
    # and the visit continues with the next attempt of the same execution
    restart(subject, tmp_path)
    later = Transport(succeeded(subject))
    calls = []
    outcome = build(subject, run, dispatcher(subject, later), handlers(subject, calls)).run()
    assert calls == ["writer", "publish"] or calls == ["intake", "writer", "publish"]
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    assert dict(outcome.result_refs)[writer_execution] == subject.refs.produced
    assert len(later.calls) == 1
    second = na.attempt_identity(run.run_id, "writer", 0, 1)
    assert later.calls[0][1].attempt_id == second
    before = subject.ledger.get_attempt(unsent)
    assert before["send_finality"] == "definitely_not_sent" and before["dispatch_gate"] == "closed"
    assert subject.ledger.result_observations(unsent) == []
    accepted = subject.ledger.get_attempt(second)
    assert accepted["spec"]["attempt_no"] == 2 and accepted["terminal_outcome"] == "succeeded"
    assert budget_row(subject, na.reservation_identity(second))["state"] == "finalized"
    # the ledger-only reservation of the unsent attempt never reached the book
    assert budget_row(subject, na.reservation_identity(unsent)) is None


def test_a_success_with_an_unresolvable_result_is_an_unknown_outcome(tmp_path):
    subject, run = started(tmp_path)
    phantom = EntityRef.from_dict({**subject.refs.produced.as_dict(), "id": identifier()})
    transport = Transport(na.AttemptTransportResult(
        outcome="succeeded", result_ref=phantom, usage_finality="final",
        remote_terminal_observed="succeeded", reason_code="provider_terminal",
        usage=BudgetUsage.create(model_calls=1, tool_calls=0, node_visits=1, loop_rounds=0,
                                 output_bytes=1, candidates=0, api_microunits=None),
    ))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport), handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "outcome_unknown" and stored["phase"] == "terminal"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "unknown"
    assert not any(
        entry[0].attempt_id == attempt_id for entry in subject.ledger._pending_permits.values()
    )


def test_a_result_the_ledger_cannot_observe_is_an_unknown_outcome(tmp_path):
    # the transport vocabulary admits a pair the ledger refuses (an unknown outcome
    # claiming a known remote terminal): recorded as unknown, never stranded
    subject, run = started(tmp_path)
    claimed = na.AttemptTransportResult(
        outcome="outcome_unknown", result_ref=None, usage_finality="unknown",
        remote_terminal_observed="failed", reason_code="transport_unknown", usage=None,
    )
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, Transport(claimed)), handlers(subject, [])).run()
    attempt_id = writer_attempt_id(run)
    stored = subject.ledger.get_attempt(attempt_id)
    assert stored["terminal_outcome"] == "outcome_unknown" and stored["phase"] == "terminal"
    assert stored["remote_terminal_observed"] == "not_observed"
    assert budget_row(subject, na.reservation_identity(attempt_id))["state"] == "unknown"


def failed_result(subject):
    return na.AttemptTransportResult(
        outcome="failed", result_ref=None, usage_finality="final",
        remote_terminal_observed="failed", reason_code="provider_terminal",
        usage=BudgetUsage.create(model_calls=1, tool_calls=0, node_visits=1, loop_rounds=0,
                                 output_bytes=0, candidates=0, api_microunits=None),
    )


class FailingOnce:
    """A transport whose first call ends in an observed terminal failure."""

    def __init__(self, subject):
        self.subject = subject
        self.calls = []

    def __call__(self, permit, request, window):
        self.calls.append(request.attempt_id)
        if len(self.calls) == 1:
            return failed_result(self.subject)
        return succeeded(self.subject)


def test_a_sent_attempt_is_retried_only_on_the_owners_recovery_and_only_after_an_observed_terminal(tmp_path):
    subject, run = started(tmp_path)
    transport = FailingOnce(subject)
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport), handlers(subject, [])).run()
    first = na.attempt_identity(run.run_id, "writer", 0, 0)
    assert subject.ledger.get_attempt(first)["terminal_outcome"] == "failed"
    assert transport.calls == [first]
    # a plain resume never re-sends a sent attempt: the failure stands
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport), handlers(subject, [])).run()
    assert transport.calls == [first]
    # the owner's recovery admits the next attempt of the same execution, because the
    # ledger proved the first one terminal, observed and finally accounted
    retrying = na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": binding(subject)}, transport=transport, retry_after_terminal=True,
    )
    calls = []
    outcome = build(subject, run, retrying, handlers(subject, calls)).run()
    second = na.attempt_identity(run.run_id, "writer", 0, 1)
    assert transport.calls == [first, second]
    assert calls == ["writer", "publish"]
    assert dict(outcome.result_refs)[sch.execution_identity(run.run_id, "writer", 0)] == subject.refs.produced
    stored = subject.ledger.get_attempt(second)
    assert stored["spec"]["attempt_no"] == 2 and stored["terminal_outcome"] == "succeeded"
    assert subject.ledger.get_attempt(first)["terminal_outcome"] == "failed"  # the past stays
    assert budget_row(subject, na.reservation_identity(first))["state"] == "finalized"
    assert budget_row(subject, na.reservation_identity(second))["state"] == "finalized"
    # a recovery over an unknown outcome is never a retry: nothing was observed terminal
    subject2, run2 = started(tmp_path / "second")
    unknown = Transport(na.AttemptTransportResult(
        outcome="outcome_unknown", result_ref=None, usage_finality="unknown",
        remote_terminal_observed="not_observed", reason_code="transport_unknown", usage=None,
    ))
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject2, run2, dispatcher(subject2, unknown), handlers(subject2, [])).run()
    retrying2 = na.NodeAttemptDispatcher.build(
        ledger=subject2.ledger, budget_book=subject2.book, owner=subject2.owner,
        bindings={"writer": binding(subject2)}, transport=unknown, retry_after_terminal=True,
    )
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject2, run2, retrying2, handlers(subject2, [])).run()
    assert len(unknown.calls) == 1
    with pytest.raises(TypeError):
        na.NodeAttemptDispatcher.build(
            ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
            bindings={"writer": binding(subject)}, transport=transport, retry_after_terminal="yes",
        )


def retrying(subject, transport):
    return na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": binding(subject)}, transport=transport, retry_after_terminal=True,
    )


def test_late_evidence_on_the_failed_attempt_forbids_the_recovery_retry(tmp_path):
    from app.runtime.ledger import ResultObservation

    subject, run = started(tmp_path)
    transport = FailingOnce(subject)
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport), handlers(subject, [])).run()
    first = na.attempt_identity(run.run_id, "writer", 0, 0)
    # a different observation arriving after the terminal is late evidence: the
    # ledger's retry-safety proof no longer holds and the dispatcher must not
    # even reserve the next attempt
    late = subject.ledger.accept_result(identifier(), ResultObservation(
        observation_id=identifier(), attempt_id=first, outcome="failed", result_ref=None,
        usage_finality="final", remote_terminal_observed="failed", reason_code="validation_failed",
    ))
    assert late["classification"] == "late"
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, retrying(subject, transport), handlers(subject, [])).run()
    assert transport.calls == [first]
    with pytest.raises(KeyError):
        subject.ledger.get_attempt(na.attempt_identity(run.run_id, "writer", 0, 1))


def test_recovery_stops_at_the_budget_without_stranding_a_reserved_attempt(tmp_path):
    subject, run = started(tmp_path)  # the fixture policy admits three model calls

    class AlwaysFailing(FailingOnce):
        def __call__(self, permit, request, window):
            self.calls.append(request.attempt_id)
            return failed_result(self.subject)

    transport = AlwaysFailing(subject)
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, dispatcher(subject, transport), handlers(subject, [])).run()
    for _ in range(2):
        with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
            build(subject, run, retrying(subject, transport), handlers(subject, [])).run()
    assert len(transport.calls) == 3
    assert subject.book.status(subject.budget_session_id)["remaining"]["model_calls"] == 0
    # the budget is spent: the next recovery is refused before any reserve, so no
    # attempt row is stranded open and the book keeps no pending reservation
    with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
        build(subject, run, retrying(subject, transport), handlers(subject, [])).run()
    assert len(transport.calls) == 3
    with pytest.raises(KeyError):
        subject.ledger.get_attempt(na.attempt_identity(run.run_id, "writer", 0, 3))
    status = subject.book.status(subject.budget_session_id)
    assert status["active_reservations"] == 0
    assert na.MAX_ATTEMPTS_PER_VISIT == 4


def test_the_retry_proof_never_admits_a_cancelled_or_unsettled_attempt(tmp_path, monkeypatch):
    subject, _run = started(tmp_path)
    attempts = retrying(subject, Transport())
    rows = {
        "failed": {"phase": "terminal", "terminal_outcome": "failed", "remote_terminal_observed": "failed",
                   "usage_finality": "final"},
        "cancelled": {"phase": "terminal", "terminal_outcome": "cancelled",
                      "remote_terminal_observed": "cancelled", "usage_finality": "final"},
        "timed_out": {"phase": "terminal", "terminal_outcome": "timed_out",
                      "remote_terminal_observed": "not_observed", "usage_finality": "unknown"},
        "unknown": {"phase": "terminal", "terminal_outcome": "outcome_unknown",
                    "remote_terminal_observed": "not_observed", "usage_finality": "unknown"},
    }
    monkeypatch.setattr(subject.ledger, "get_attempt", lambda attempt_id: rows[attempt_id])
    monkeypatch.setattr(subject.ledger, "result_observations", lambda attempt_id: [])
    assert attempts._observed_terminal("failed") is True
    # a cancelled attempt's usage finality is the ledger's, not the book's: no
    # in-tree producer settles it, so it is never a retry proof here
    assert attempts._observed_terminal("cancelled") is False
    assert attempts._observed_terminal("timed_out") is False
    assert attempts._observed_terminal("unknown") is False
