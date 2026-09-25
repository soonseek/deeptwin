"""T087 (2026-09-25, scheduler slice): the scheduler's gate passage for a gated
external-effect tool call consumes execution-bound (v2) decisions per attempt.

A compiled graph whose `writer` binds an external-family tool behind the human gate
`tool-gate` runs up to the gate; the gate's tool scope is not a v1 scope, so passing
the gate only records its durable request. Before the writer's handler, the
scheduler asks the ledger for exactly the attempt the dispatcher would send next
(with the digest of the transport's exact inputs) and pauses the node until the
owner's v2 decision for that attempt exists. An approval dispatches, and the
dispatcher claims the approval use, the ToolCall intent, the budget reservation and
the send intent in one ledger transaction; a rejection, an expiry or a recovery
supersession stops the visit with its recorded reason; a retry attempt is a new ask
needing its own decision; a crash between the claim and the send is recovered
without any send.

Every tool here is the TEST-ACTOR tool `test_actor_notify` registered only for these
tests (app/tests/support/tool_gate.py); it performs no external effect. The worker is
the real in-process extension worker over the real socket (the `staged` seams).
"""

import time
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.runtime import extension_attempt_transport as xt
from app.runtime import ledger as ledger_module
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.budgets import BudgetDispatchRequest
from app.runtime.ledger import (
    ApprovalRefused,
    AttemptSpec,
    RuntimeLedger,
    ToolCallSpec,
    ToolDispatchClaim,
    tool_call_identity,
)
from app.services import run_approvals as ra
from app.tests.support.tool_gate import (
    GATE,
    SCOPE,
    TEST_ACTOR_TOOL,
    compiled_tool_gated,
    register_test_actor_tool,
)
from app.tests.test_extension_attempt_transport import (  # noqa: F401 - fixture re-exports
    INSTANCE,
    SLOT,
    app_subject,
    channel,
    slot,
    staged,
    text_input,
    worker_tree,
)
from app.tests.test_runtime_ledger import identifier
from app.tests.test_scheduler_attempt_dispatch import handlers as base_handlers
from app.tests.test_tool_execution_binding import execution_of, unsent_attempt
from app.workers import listener


@pytest.fixture
def actor_tool(monkeypatch):
    """The test-actor tool, registered before the worker service opens its router."""
    return register_test_actor_tool(monkeypatch)


@pytest.fixture
def worker(actor_tool, staged):  # noqa: F811 - the imported fixture
    return SimpleNamespace(tool=actor_tool, box=staged[3])


@contextmanager
def gated(tmp_path):
    from app.tests.test_extension_candidates_persistent import owner

    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = ra.PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        subject, run = app_subject(app)
        subject.approvals, subject.request, subject.run, subject.app = approvals, request, run, app
        subject.compiled = compiled_tool_gated()
        yield subject


def transport_of(subject, ledger=None, payload=b"hello"):
    return xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(payload),), compiled=subject.compiled, node_id="writer",
        binding_id="source-read", ledger=ledger or subject.ledger, approvals=subject.approvals)


def dispatcher_of(subject, transport, *, retry=False, ledger=None):
    return na.NodeAttemptDispatcher.build(
        ledger=ledger or subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": na.AttemptBinding.create(
            envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
            budget_policy_ref=subject.refs.budget, deadline_at_ms=subject.deadline,
            lease_duration_ms=60_000, model_calls=0, tool_calls=1, node_visits=1, loop_rounds=0,
            output_bytes=transport.output_bytes_bound, candidates=0, api_microunits=None,
            principal=subject.principal, grant=subject.grant,
        )},
        transport=transport, retry_after_terminal=retry,
    )


def scheduler_of(subject, *, retry=False, ledger=None):
    calls = []
    registry = base_handlers(subject, calls)
    registry["core.human_gate"] = registry["core.deterministic"]
    transport = transport_of(subject, ledger)
    return sch.build_scheduler(
        subject.compiled, ledger=ledger or subject.ledger, run_id=subject.run.run_id, handlers=registry,
        approvals=subject.approvals, attempts=dispatcher_of(subject, transport, retry=retry, ledger=ledger))


def writer_execution(subject):
    return sch.execution_identity(subject.run.run_id, "writer", 0)


def listing(subject):
    return subject.approvals.execution_requests(subject.run.run_id)


def decide(subject, entry, decision="approved"):
    body = {"schema_version": "run-approval-command-v2", "command_id": str(uuid4()),
            "run_id": subject.run.run_id, "decision": decision,
            **{name: entry[name] for name in ("node_id", "approval_scope", "execution_id",
                                              "execution_node_id", "attempt_no", "inputs_digest")}}
    return EntityRef.from_dict(subject.approvals.record_execution(subject.request, body)["approval_ref"])


def pending_entry(subject, attempt_no):
    [entry] = [item for item in listing(subject) if item["attempt_no"] == attempt_no]
    assert entry["state"] == "pending"
    return entry


def attempts_of(subject):
    return subject.ledger.attempts_for_run(subject.run.run_id)


def attempt_id(subject, index=0):
    return na.attempt_identity(subject.run.run_id, "writer", 0, index)


def active_reservations(subject):
    return subject.book.status(subject.budget_session_id)["active_reservations"]


def test_the_scheduler_asks_for_the_exact_attempt_and_pauses_until_the_owner_approves_it(tmp_path, worker):
    with gated(tmp_path) as subject:
        visit = writer_execution(subject)
        outcome = scheduler_of(subject).run()
        # the run reached the tool node and waits on exactly its first attempt's decision
        assert outcome.awaiting_execution == ((GATE, SCOPE, visit, "writer", 1),)
        assert outcome.awaiting_human == () and outcome.rejected_execution == ()
        assert set(outcome.completed_node_ids) == {"intake", GATE} and outcome.pending_node_ids == ("writer",)
        # the ledger holds the gate request and the ask for that attempt, with the digest
        # of the exact inputs the transport will declare and a bounded server-set expiry
        assert subject.ledger.gate_approval_requested(subject.run.run_id, GATE, SCOPE)
        ask = subject.ledger.execution_approval_requested(subject.run.run_id, GATE, SCOPE, visit, 1)
        assert ask["execution_node_id"] == "writer"
        assert ask["inputs_digest"] == transport_of(subject).artifact_inputs_digest
        now = time.time_ns() // 1_000_000
        assert now < ask["expires_at_ms"] <= now + ledger_module.EXECUTION_APPROVAL_TTL_MS
        # nothing was reserved, claimed or sent while waiting
        assert attempts_of(subject) == [] and active_reservations(subject) == 0
        assert worker.tool["calls"] == 0 and "served" not in worker.box
        # reading and running again ask nothing new and still wait
        assert scheduler_of(subject).observe().awaiting_execution == outcome.awaiting_execution
        assert scheduler_of(subject).run().awaiting_execution == outcome.awaiting_execution
        assert [item["attempt_no"] for item in listing(subject)] == [1]
        # a run-wide v1 decision for the gate's tool scope authorizes no attempt
        subject.approvals.record(subject.request, {
            "schema_version": "run-approval-command-v1", "command_id": str(uuid4()),
            "run_id": subject.run.run_id, "node_id": GATE, "approval_scope": SCOPE, "decision": "approved"})
        assert scheduler_of(subject).run().awaiting_execution == outcome.awaiting_execution
        assert attempts_of(subject) == []

        approved = decide(subject, pending_entry(subject, 1))
        assert scheduler_of(subject).observe().awaiting_execution == ()
        done = scheduler_of(subject).run()
        assert set(done.completed_node_ids) == {"intake", GATE, "writer", "publish"}
        assert done.pending_node_ids == () and done.awaiting_execution == ()
        # the approved attempt ran once, its ToolCall carries exactly that approval, and
        # the claim (approval use, ToolCall intent, budget, send intent) was one transaction
        [attempt] = attempts_of(subject)
        assert attempt["spec"]["attempt_no"] == 1 and attempt["terminal_outcome"] == "succeeded"
        [call] = subject.ledger.tool_calls_for_attempt(attempt_id(subject))
        assert call["state"] == "succeeded" and call["approval_ref"] == approved.as_dict()
        assert (call["tool_id"], call["version"], call["effect_class"]) == (
            TEST_ACTOR_TOOL["tool_id"], TEST_ACTOR_TOOL["version"], "external_irreversible")
        assert call["created_at_ms"] == attempt["send_intent_at_ms"]
        assert worker.tool["calls"] == 1 and worker.box.get("served") == 1
        assert listing(subject)[0]["state"] == "approved"


def test_a_rejected_attempt_stops_the_visit_with_its_recorded_reason(tmp_path, worker):
    with gated(tmp_path) as subject:
        visit = writer_execution(subject)
        scheduler_of(subject).run()
        decide(subject, pending_entry(subject, 1), "rejected")
        observed = scheduler_of(subject).observe()
        assert observed.awaiting_execution == ()
        assert observed.rejected_execution == ((GATE, SCOPE, visit, "writer", 1, "rejected"),)
        with pytest.raises(sch.SchedulerError, match="approval_refused:writer"):
            scheduler_of(subject).run()
        assert subject.ledger.execution_approval_refused(subject.run.run_id, GATE, SCOPE, visit, 1) == "rejected"
        with pytest.raises(sch.SchedulerError, match="approval_refused:writer"):  # the stop stands
            scheduler_of(subject).run()
        assert attempts_of(subject) == [] and active_reservations(subject) == 0
        assert worker.tool["calls"] == 0 and "served" not in worker.box


def test_a_retry_attempt_is_a_new_ask_and_needs_its_own_decision(tmp_path, worker):
    with gated(tmp_path) as subject:
        worker.tool["fail_next"] = 1
        scheduler_of(subject).run()
        first = decide(subject, pending_entry(subject, 1))
        # attempt 1 runs and the test-actor tool fails terminally (final usage observed)
        with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
            scheduler_of(subject).run()
        assert worker.tool["calls"] == 1 and worker.box.get("served") == 1
        # without the owner's recovery nothing is asked again
        with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
            scheduler_of(subject).run()
        assert [item["attempt_no"] for item in listing(subject)] == [1]
        # the owner's recovery: attempt 2 is its own ask, attempt 1's decision does not cover it
        outcome = scheduler_of(subject, retry=True).run()
        assert outcome.awaiting_execution == ((GATE, SCOPE, writer_execution(subject), "writer", 2),)
        assert {item["attempt_no"]: item["state"] for item in listing(subject)} == {1: "approved", 2: "pending"}
        assert scheduler_of(subject, retry=True).run().awaiting_execution == outcome.awaiting_execution
        assert len(attempts_of(subject)) == 1
        second = decide(subject, pending_entry(subject, 2))
        assert second != first
        again = worker.box["serve_again"]()
        done = scheduler_of(subject, retry=True).run()
        assert "publish" in done.completed_node_ids and done.awaiting_execution == ()
        [call] = subject.ledger.tool_calls_for_attempt(attempt_id(subject, 1))
        assert call["state"] == "succeeded" and call["approval_ref"] == second.as_dict()
        [old] = subject.ledger.tool_calls_for_attempt(attempt_id(subject, 0))
        assert old["state"] == "failed" and old["approval_ref"] == first.as_dict()
        assert worker.tool["calls"] == 2 and again.get("served") == 1


def test_a_decision_superseded_by_an_owner_recovery_never_lets_the_visit_proceed(tmp_path, worker, monkeypatch):
    with gated(tmp_path) as subject:
        scheduler_of(subject).run()
        approved = decide(subject, pending_entry(subject, 1))
        # an owner recovery after the decision (its barrier after the decision's event;
        # the real reconciliation is exercised in test_owner_sessions) supersedes it
        sequence = subject.domain.get(approved).body["content"]["event_sequence"]
        monkeypatch.setattr(ra, "_recovery_barrier", lambda db, vault_id: sequence + 1)
        assert listing(subject)[0]["state"] == "superseded"
        assert scheduler_of(subject).observe().rejected_execution[0][-1] == "superseded"
        with pytest.raises(sch.SchedulerError, match="approval_refused:writer"):
            scheduler_of(subject).run()
        assert subject.ledger.execution_approval_refused(
            subject.run.run_id, GATE, SCOPE, writer_execution(subject), 1) == "superseded"
        assert attempts_of(subject) == [] and worker.tool["calls"] == 0 and "served" not in worker.box


def test_a_pending_ask_expires_and_can_no_longer_be_decided(tmp_path, worker):
    with gated(tmp_path) as subject:
        scheduler_of(subject).run()
        entry = pending_entry(subject, 1)
        later = entry["expires_at_ms"]
        subject.approvals._clock = lambda: later  # the ask's instant has come
        assert listing(subject)[0]["state"] == "expired"
        with pytest.raises(ra.RunApprovalError, match="conflict"):
            decide(subject, entry)
        with pytest.raises(sch.SchedulerError, match="approval_refused:writer"):
            scheduler_of(subject).run()
        assert subject.ledger.execution_approval_refused(
            subject.run.run_id, GATE, SCOPE, writer_execution(subject), 1) == "expired"
        assert attempts_of(subject) == [] and worker.tool["calls"] == 0


def test_an_approval_that_expired_before_the_dispatch_is_refused_inside_the_claim(tmp_path, worker):
    with gated(tmp_path) as subject:
        scheduler_of(subject).run()
        entry = pending_entry(subject, 1)
        decide(subject, entry)
        # the service still reads the decision as approved; the ledger's own clock (the
        # dispatch's) has passed the ask's instant, so the claim refuses it
        offset = entry["expires_at_ms"] - time.time_ns() // 1_000_000 + 1_000
        real = subject.ledger._clock
        subject.ledger._clock = lambda: real() + offset
        with pytest.raises(sch.SchedulerError, match="approval_refused:writer"):
            scheduler_of(subject).run()
        assert subject.ledger.execution_approval_refused(
            subject.run.run_id, GATE, SCOPE, writer_execution(subject), 1) == "expired"
        # nothing of the claim was written: the attempt is reserved and unsent, no ToolCall,
        # no budget reservation, no send
        [attempt] = attempts_of(subject)
        assert attempt["phase"] == "reserved" and attempt["send_intent_at_ms"] is None
        assert subject.ledger.tool_calls_for_attempt(attempt_id(subject)) == []
        assert active_reservations(subject) == 0
        assert worker.tool["calls"] == 0 and "served" not in worker.box


class _Crash(BaseException):
    """The process dies between the committed claim and the send."""


def test_a_crash_between_the_claim_and_the_send_is_recovered_without_a_send(tmp_path, worker, monkeypatch):
    connects = []
    real_connect = listener._connect_extension_authenticated
    monkeypatch.setattr(listener, "_connect_extension_authenticated",
                        lambda *a, **kw: connects.append(1) or real_connect(*a, **kw))
    with gated(tmp_path) as subject:
        scheduler_of(subject).run()
        approved = decide(subject, pending_entry(subject, 1))

        def crash(*_args, **_kwargs):
            raise _Crash()

        monkeypatch.setattr(subject.ledger, "consume_dispatch_permit_window", crash)
        with pytest.raises(_Crash):
            scheduler_of(subject).run()
        # the claim committed as one: send intent, budget reservation, ToolCall intent with
        # its approval — and nothing was sent
        [attempt] = attempts_of(subject)
        assert attempt["phase"] == "send_intent"
        [call] = subject.ledger.tool_calls_for_attempt(attempt_id(subject))
        assert call["state"] == "intent" and call["approval_ref"] == approved.as_dict()
        assert call["created_at_ms"] == attempt["send_intent_at_ms"]
        assert active_reservations(subject) == 1
        assert connects == [] and worker.tool["calls"] == 0
        # a restarted process: a fresh ledger reconciles the attempt as an unknown outcome
        restarted = RuntimeLedger(subject.domain)
        restarted.reconcile_startup(identifier(), observed_owners={})
        [attempt] = restarted.attempts_for_run(subject.run.run_id)
        assert attempt["terminal_outcome"] == "outcome_unknown"
        assert restarted.tool_calls_for_attempt(attempt_id(subject))[0]["state"] == "unknown"
        # the run resumes: no new ask, no second claim, no send — the unknown outcome
        # fails the visit, and even the owner's recovery never retries it
        for retry in (False, True):
            observed = scheduler_of(subject, retry=retry, ledger=restarted).observe()
            assert observed.awaiting_execution == () and observed.rejected_execution == ()
            with pytest.raises(sch.SchedulerError, match="node_failed:writer"):
                scheduler_of(subject, retry=retry, ledger=restarted).run()
        assert [item["attempt_no"] for item in listing(subject)] == [1]
        assert len(restarted.attempts_for_run(subject.run.run_id)) == 1
        assert connects == [] and worker.tool["calls"] == 0 and "served" not in worker.box


def test_a_gated_tool_node_needs_its_per_attempt_dispatcher(tmp_path, actor_tool):
    with gated(tmp_path) as subject:
        registry = base_handlers(subject, [])
        registry["core.human_gate"] = registry["core.deterministic"]
        with pytest.raises(sch.SchedulerError, match="per-attempt approval transport"):
            sch.build_scheduler(subject.compiled, ledger=subject.ledger, run_id=subject.run.run_id,
                                handlers=registry, approvals=subject.approvals)
        with pytest.raises(sch.SchedulerError, match="persistent run approval service"):
            sch.build_scheduler(subject.compiled, ledger=subject.ledger, run_id=subject.run.run_id,
                                handlers=registry, attempts=dispatcher_of(subject, transport_of(subject)))


# --- the atomic claim at the ledger ---------------------------------------------------------


def reserved_attempt(subject, execution_id, attempt_no=1):
    spec = AttemptSpec(identifier(), execution_id, attempt_no, subject.refs.envelope, subject.refs.profile,
                       subject.refs.budget, identifier(), "effect:" + identifier(), subject.owner,
                       subject.deadline)
    reserved = subject.ledger.reserve_attempt(identifier(), spec, lease_duration_ms=60_000)
    return spec, reserved


def budget_for(subject, spec):
    return BudgetDispatchRequest.create(
        session_id=subject.budget_session_id, request_id=spec.reservation_id, policy_ref=subject.refs.budget,
        model_calls=0, tool_calls=1, node_visits=1, loop_rounds=0, output_bytes=10, candidates=0,
        api_microunits=None)


def claim_for(spec, approval, verify):
    return ToolDispatchClaim(command_id=identifier(), spec=ToolCallSpec(
        tool_call_id=tool_call_identity(spec.attempt_id), attempt_id=spec.attempt_id,
        tool_id=TEST_ACTOR_TOOL["tool_id"], version=TEST_ACTOR_TOOL["version"],
        effect_class="external_irreversible", artifact_inputs=(), approval_ref=approval), verify=verify)


def commit(subject, spec, reserved, claim):
    return subject.ledger.commit_budgeted_send_intent(
        identifier(), spec.attempt_id, subject.owner, expected_revision=reserved["revision"],
        budget_book=subject.book, budget_request=budget_for(subject, spec), principal=subject.principal,
        grant=subject.grant, tool_call=claim)


@pytest.mark.parametrize("reason", ["expired", "rejected", "superseded", "missing"])
def test_a_refused_claim_writes_no_budget_toolcall_or_send(tmp_path, reason):
    with gated(tmp_path) as subject:
        visit = execution_of(subject, subject.run, 0)
        spec, reserved = reserved_attempt(subject, visit)
        seen = []

        def refuse(db, now):
            seen.append(now)
            raise ApprovalRefused(reason)

        with pytest.raises(ApprovalRefused) as refused:
            commit(subject, spec, reserved, claim_for(spec, EntityRef("action_approval", identifier(), 1, "a" * 64),
                                                      refuse))
        assert refused.value.reason == reason and len(seen) == 1
        stored = subject.ledger.get_attempt(spec.attempt_id)
        assert stored["phase"] == "reserved" and stored["revision"] == reserved["revision"]
        assert subject.ledger.tool_calls_for_attempt(spec.attempt_id) == []
        assert active_reservations(subject) == 0


def test_an_approval_already_used_by_another_attempt_rolls_the_whole_claim_back(tmp_path):
    with gated(tmp_path) as subject:
        visit = execution_of(subject, subject.run, 0)
        approval = EntityRef("action_approval", identifier(), 1, "b" * 64)
        first = unsent_attempt(subject, visit, 1)
        subject.ledger.record_tool_call(identifier(), claim_for(first, approval, lambda db, now: None).spec)
        spec, reserved = reserved_attempt(subject, visit, 2)
        with pytest.raises(ApprovalRefused) as refused:
            commit(subject, spec, reserved, claim_for(spec, approval, lambda db, now: None))
        assert refused.value.reason == "used"
        stored = subject.ledger.get_attempt(spec.attempt_id)
        assert stored["phase"] == "reserved" and stored["send_intent_at_ms"] is None
        assert subject.ledger.tool_calls_for_attempt(spec.attempt_id) == []
        assert active_reservations(subject) == 0
        # the same claim with an unused approval commits the send, budget and ToolCall at once
        fresh = EntityRef("action_approval", identifier(), 1, "c" * 64)
        permit = commit(subject, spec, reserved, claim_for(spec, fresh, lambda db, now: None))
        assert permit is not None
        stored = subject.ledger.get_attempt(spec.attempt_id)
        [call] = subject.ledger.tool_calls_for_attempt(spec.attempt_id)
        assert stored["phase"] == "send_intent" and call["created_at_ms"] == stored["send_intent_at_ms"]
        assert call["approval_ref"] == fresh.as_dict() and active_reservations(subject) == 1
        subject.ledger.discard_dispatch_permit(permit)


def test_the_ask_expiry_is_server_set_and_bounded(tmp_path, monkeypatch):
    with gated(tmp_path) as subject:
        subject.ledger.request_gate_approval(subject.run.run_id, GATE, SCOPE)
        visit = execution_of(subject, subject.run, 0)
        other = execution_of(subject, subject.run, 1)
        first = subject.ledger.request_execution_approval(subject.run.run_id, GATE, SCOPE, visit, 1)
        # a replay returns the same instant, never a renewed one
        assert subject.ledger.request_execution_approval(subject.run.run_id, GATE, SCOPE, visit, 1) == first
        monkeypatch.setattr(ledger_module, "EXECUTION_APPROVAL_TTL_MS", ledger_module.MAX_EXECUTION_APPROVAL_TTL_MS + 1)
        with pytest.raises(ledger_module.LedgerError, match="time to live"):
            subject.ledger.request_execution_approval(subject.run.run_id, GATE, SCOPE, other, 1)
        monkeypatch.setattr(ledger_module, "EXECUTION_APPROVAL_TTL_MS", ledger_module.MIN_EXECUTION_APPROVAL_TTL_MS - 1)
        with pytest.raises(ledger_module.LedgerError, match="time to live"):
            subject.ledger.request_execution_approval(subject.run.run_id, GATE, SCOPE, other, 1)
