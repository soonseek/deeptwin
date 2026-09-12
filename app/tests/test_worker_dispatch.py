"""Bounded handoff tests; no live worker, provider, network, or credential use."""

# The imported fixture is intentionally re-exported for this test module.
# ruff: noqa: F401, F811

import asyncio
import copy
import pickle
from dataclasses import replace
from threading import Event, Thread, Timer
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api import routes as api_routes
from app.api.transaction import DispatchOutcome
from app.domain import store as domain_store_module
from app.domain.refs import EntityRef
from app.runtime import worker_coordinator as worker_module
from app.runtime import worker_dispatch as dispatch_module
from app.runtime.budgets import BudgetDispatchRequest, BudgetPolicy
from app.runtime.ledger import (
    AttemptSpec,
    DispatchBlocked,
    ExecutionSpec,
    RunSpec,
    RuntimeLedger,
)
from app.tests.test_worker_coordinator import (
    immutable,
    install_transport,
    subject,
)
from app.workers import broker


def outcome(value):
    return DispatchOutcome({}, value.permit, False, value.capability)


def accept_dispatch(dispatcher, reservation, dispatch_outcome, route_deadline):
    acceptance = dispatcher.accept(
        reservation,
        dispatch_outcome,
        deadline=route_deadline,
    )
    claimed = dispatcher.claim_acceptance(
        acceptance,
        reservation,
        dispatch_outcome,
        deadline=route_deadline,
    )
    assert claimed is acceptance
    assert reservation._slot_token not in dispatcher._issued_acceptances
    return acceptance


def deadline(milliseconds=5_000):
    return broker.Deadline.after_ms(milliseconds)


def service(value):
    return dispatch_module.WorkerDispatchService(
        runtime_ledger=value.ledger,
        coordinators=(value.coordinator,),
    )


@pytest.fixture
def started_dispatcher():
    dispatchers = []

    def start(value):
        dispatcher = service(value)
        dispatcher.start()
        dispatchers.append(dispatcher)
        return dispatcher

    yield start

    first_error = None
    for dispatcher in reversed(dispatchers):
        try:
            dispatcher.close()
        except Exception as exc:  # noqa: BLE001 - teardown must try every owned thread
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def alternate_coordinator(value, tmp_path, *, duplicate):
    pair_root = tmp_path / "alternate-pair"
    socket_name = "alternate.sock"
    if duplicate == "pair_root":
        pair_root = value.route.channel_spec.pair_root
    elif duplicate in {"resolved_pair_root", "resolved_endpoint"}:
        original_root = value.route.channel_spec.pair_root
        original_root.mkdir(exist_ok=True)
        pair_root = tmp_path / "pair-root-alias"
        pair_root.symlink_to(original_root, target_is_directory=True)
        if duplicate == "resolved_endpoint":
            socket_name = value.route.channel_spec.socket_name
    channel = replace(
        value.route.channel_spec,
        channel_id=(
            value.route.channel_spec.channel_id
            if duplicate == "channel_id" else "alternate-channel"
        ),
        requester_service=(
            value.route.channel_spec.requester_service
            if duplicate == "service_pair" else "alternate-control"
        ),
        responder_service=(
            value.route.channel_spec.responder_service
            if duplicate == "service_pair" else "alternate-document"
        ),
        request_direction=(
            value.route.channel_spec.request_direction
            if duplicate == "service_pair"
            else "alternate-control-to-alternate-document"
        ),
        protocol_id="alternate-command-v1",
        pair_root=pair_root,
        socket_name=socket_name,
    )
    profile = EntityRef(
        "runtime_profile",
        "10000000-0000-4000-8000-000000000010",
        1,
        "a" * 64,
    )
    if duplicate == "profile":
        profile = value.records.profile.ref
    route = replace(value.route, profile_ref=profile, channel_spec=channel)
    secret = broker.BootSecret(b"q" * broker.AUTH_SECRET_BYTES)
    if duplicate == "secret":
        secret = broker.BootSecret(value.coordinator._secret._material())
    return worker_module.WorkerCoordinator(
        domain_store=value.domain,
        permission_gate=value.gate,
        runtime_ledger=value.ledger,
        budget_book=value.budget,
        route=route,
        boot_secret=secret,
        requester_boot_id=(
            value.coordinator._requester_boot_id
            if duplicate == "requester_boot_id" else "alternate-control-boot"
        ),
        worker_boot_id=(
            value.coordinator._worker_boot_id
            if duplicate == "worker_boot_id" else "alternate-document-boot"
        ),
    )


def identifier():
    return str(uuid4())


def additional_outcome(value, *, profile_ref=None):
    policy = BudgetPolicy.create(
        profile="execution",
        provider_mode="subscription",
        max_model_calls=2,
        max_tool_calls=2,
        max_node_visits=4,
        max_loop_rounds=1,
        max_output_bytes=10_000,
        max_concurrency=1,
        max_wall_seconds=60,
        max_candidates=1,
    )
    roots = value.domain.roots()
    budget_record = immutable(
        value.domain,
        roots,
        "budget_policy",
        content=policy.domain_content(),
    )
    value.host.register_record(budget_record)
    budget_session_id = identifier()
    value.budget.start(budget_session_id, policy)
    run = RunSpec(
        identifier(),
        value.records.work.ref,
        value.records.environment.ref,
        value.records.consent.ref,
        "live",
        budget_record.ref,
        budget_session_id,
        value.records.manifest.ref,
    )
    value.ledger.create_run(identifier(), run)
    execution = ExecutionSpec(
        identifier(),
        run.run_id,
        "document-second",
        identifier(),
        (0,),
        (),
    )
    value.ledger.create_execution(identifier(), execution)
    attempt = AttemptSpec(
        identifier(),
        execution.execution_id,
        1,
        value.records.envelope.ref,
        value.records.profile.ref if profile_ref is None else profile_ref,
        budget_record.ref,
        identifier(),
        "effect:" + identifier(),
        value.permit.owner,
        10_000,
    )
    value.ledger.reserve_attempt(identifier(), attempt, lease_duration_ms=2_000)
    request = BudgetDispatchRequest.create(
        session_id=budget_session_id,
        request_id=attempt.reservation_id,
        policy_ref=budget_record.ref,
        model_calls=0,
        tool_calls=1,
        node_visits=1,
        loop_rounds=0,
        output_bytes=1_000,
        candidates=0,
        api_microunits=None,
    )
    permit = value.ledger.commit_budgeted_send_intent(
        identifier(),
        attempt.attempt_id,
        value.permit.owner,
        expected_revision=1,
        budget_book=value.budget,
        budget_request=request,
        principal=value.runtime,
        grant=value.grant,
    )
    capability = worker_module.SelectedDispatchReadCapability(
        permit_id=permit.permit_id,
        command_id=permit.command_id,
        principal=value.runtime,
        grant=value.grant,
        resource_ref=value.records.envelope.ref,
        purpose="operational",
        episode_id=None,
    )
    return DispatchOutcome({}, permit, False, capability)


def test_process_wide_inhibition_never_waits_for_writer_and_purges_all_profiles(
    subject,
):
    alternate_profile = immutable(
        subject.domain,
        subject.domain.roots(),
        "runtime_profile",
    )
    subject.host.register_record(alternate_profile)
    second = additional_outcome(subject, profile_ref=alternate_profile.ref)
    assert second.permit.profile_ref != subject.permit.profile_ref
    assert subject.ledger.pending_permit_count == 2

    writer_held = Event()
    release_writer = Event()

    def hold_writer():
        with domain_store_module._writer():
            writer_held.set()
            assert release_writer.wait(5)

    holder = Thread(target=hold_writer)
    holder.start()
    assert writer_held.wait(1)
    inhibited = Event()

    def inhibit():
        subject.ledger.emergency_inhibit_all_dispatch()
        inhibited.set()

    inhibiter = Thread(target=inhibit)
    inhibiter.start()
    try:
        assert inhibited.wait(0.5)
        inhibiter.join(1)
        assert not inhibiter.is_alive()
        assert subject.ledger.is_dispatch_emergency_inhibited is True
        assert subject.ledger.pending_permit_count == 0
        for permit in (subject.permit, second.permit):
            assert subject.ledger.dispatch_status(permit.command_id)["state"] == (
                "outcome_unknown"
            )
        with pytest.raises(DispatchBlocked):
            subject.ledger._activate_dispatch_permit(
                second.permit,
                budget_book=subject.budget,
            )
    finally:
        release_writer.set()
        holder.join(5)
        inhibiter.join(5)
    assert not holder.is_alive()


@pytest.mark.parametrize(
    "duplicate",
    (
        "profile",
        "channel_id",
        "pair_root",
        "resolved_pair_root",
        "resolved_endpoint",
        "service_pair",
        "secret",
        "requester_boot_id",
        "worker_boot_id",
    ),
)
def test_dispatcher_rejects_each_cross_route_identity_reuse(
    subject,
    tmp_path,
    duplicate,
):
    alternate = alternate_coordinator(subject, tmp_path, duplicate=duplicate)

    with pytest.raises(TypeError, match="duplicated or foreign"):
        dispatch_module.WorkerDispatchService(
            runtime_ledger=subject.ledger,
            coordinators=(subject.coordinator, alternate),
        )


def test_dispatcher_rejects_unresolvable_pair_root_without_path_disclosure(
    subject,
    tmp_path,
):
    pair_root = tmp_path / "loop"
    pair_root.symlink_to(pair_root, target_is_directory=True)
    channel = replace(subject.route.channel_spec, pair_root=pair_root)
    route = replace(subject.route, channel_spec=channel)
    coordinator = worker_module.WorkerCoordinator(
        domain_store=subject.domain,
        permission_gate=subject.gate,
        runtime_ledger=subject.ledger,
        budget_book=subject.budget,
        route=route,
        boot_secret=broker.BootSecret(b"s" * broker.AUTH_SECRET_BYTES),
        requester_boot_id="control-boot-loop",
        worker_boot_id="document-boot-loop",
    )

    with pytest.raises(TypeError) as captured:
        dispatch_module.WorkerDispatchService(
            runtime_ledger=subject.ledger,
            coordinators=(coordinator,),
        )

    assert str(pair_root) not in str(captured.value)


def test_one_sync_helper_owns_reservation_from_root_commit_through_accept(
    subject,
    monkeypatch,
    started_dispatcher,
):
    install_transport(monkeypatch, subject)
    entered_root = Event()
    finish_root = Event()
    results = []

    class BlockingRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **kwargs):
            entered_root.set()
            assert finish_root.wait(kwargs["deadline"].require())
            return outcome(subject)

    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    envelope = SimpleNamespace(command_id=subject.permit.command_id)
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    def execute_helper():
        results.append(api_routes._reserve_execute_and_handoff(
            BlockingRoot(),
            dispatcher,
            envelope,
            object(),
            resolved,
            route_deadline,
        ))

    helper = Thread(target=execute_helper)
    helper.start()
    assert entered_root.wait(1)
    # The route has transferred ownership to this one synchronous helper; no
    # cancellation/finally boundary exists from reserve through root and accept.
    with dispatcher._condition:
        reservations = tuple(dispatcher._reservations.values())
        assert len(reservations) == 1
        assert dispatcher._held(reservations[0]) is True
    finish_root.set()
    helper.join(5)
    assert not helper.is_alive()
    assert results == [outcome(subject)]
    dispatcher.wait_idle(deadline())
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == "running"
    dispatcher.close()


def test_async_cancellation_at_root_boundary_cannot_strand_capacity_or_permit(
    subject,
    monkeypatch,
    started_dispatcher,
):
    install_transport(monkeypatch, subject)
    entered_root = Event()
    finish_root = Event()
    completed = []

    class BlockingCommittedRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **kwargs):
            entered_root.set()
            assert finish_root.wait(kwargs["deadline"].require())
            return outcome(subject)

    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    envelope = SimpleNamespace(command_id=subject.permit.command_id)
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    def run_boundary():
        result = api_routes._reserve_execute_and_handoff(
            BlockingCommittedRoot(),
            dispatcher,
            envelope,
            object(),
            resolved,
            route_deadline,
        )
        completed.append(result)
        return result

    async def cancel_caller():
        task = asyncio.create_task(api_routes.run_in_threadpool(run_boundary))
        while not entered_root.is_set():
            await asyncio.sleep(0)
        task.cancel()
        finish_root.set()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(cancel_caller())
    dispatcher.wait_idle(deadline())

    assert completed == [outcome(subject)]
    assert all(value == 0 for value in dispatcher._occupied.values())
    assert subject.ledger.pending_permit_count == 0
    assert subject.ledger.is_dispatch_emergency_inhibited is False
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == "running"
    dispatcher.close()


def test_precommit_cancellation_releases_helper_owned_reservation_without_503(
    subject,
    monkeypatch,
    started_dispatcher,
):
    class InjectedCancellation(BaseException):
        pass

    class CancelledRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **_kwargs):
            raise InjectedCancellation()

    monkeypatch.setattr(
        api_routes,
        "_stored_command_receipt",
        lambda *_args, **_kwargs: None,
    )
    assert subject.ledger.discard_dispatch_permit(subject.permit) is True
    dispatcher = started_dispatcher(subject)
    envelope = SimpleNamespace(command_id=subject.permit.command_id)
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    with pytest.raises(InjectedCancellation):
        api_routes._reserve_execute_and_handoff(
            CancelledRoot(),
            dispatcher,
            envelope,
            object(),
            resolved,
            deadline(),
        )

    assert all(value == 0 for value in dispatcher._occupied.values())
    assert subject.ledger.pending_permit_count == 0
    assert subject.ledger.is_dispatch_emergency_inhibited is False
    assert all(thread.is_alive() for thread in dispatcher._threads)
    dispatcher.close()


def test_unreadable_root_commit_recheck_releases_slot_and_returns_unknown(
    subject,
    monkeypatch,
    started_dispatcher,
):
    class FailedRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **_kwargs):
            raise OSError("PRIVATE_ROOT_FAILURE")

    monkeypatch.setattr(
        api_routes,
        "_stored_command_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("PRIVATE_RECEIPT_FAILURE")
        ),
    )
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    envelope = SimpleNamespace(command_id=subject.permit.command_id)
    monkeypatch.setattr(
        dispatcher,
        "release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("PRIVATE_RELEASE_FAILURE")
        ),
    )
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    with pytest.raises(api_routes.ApiCommittedDispatchUnknown):
        api_routes._reserve_execute_and_handoff(
            FailedRoot(), dispatcher, envelope, object(), resolved,
            route_deadline,
        )

    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    assert all(value == 0 for value in dispatcher._occupied.values())
    dispatcher.close()


def test_unexpected_post_commit_accept_failure_cannot_remain_pending(
    subject,
    monkeypatch,
    started_dispatcher,
):
    class CommittedRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **_kwargs):
            return outcome(subject)

    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    envelope = SimpleNamespace(command_id=subject.permit.command_id)
    monkeypatch.setattr(
        dispatcher,
        "accept",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("PRIVATE_ACCEPT_FAILURE")
        ),
    )
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    with pytest.raises(api_routes.ApiCommittedDispatchUnknown):
        api_routes._reserve_execute_and_handoff(
            CommittedRoot(), dispatcher, envelope, object(), resolved,
            route_deadline,
        )

    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    assert all(value == 0 for value in dispatcher._occupied.values())
    dispatcher.close()


@pytest.mark.parametrize(
    "silent_mode",
    ("instance_shadow", "class_noop", "class_forged_proof"),
)
def test_silent_accept_shadow_is_committed_unknown_and_purges_permit(
    subject,
    monkeypatch,
    started_dispatcher,
    silent_mode,
):
    class CommittedRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **_kwargs):
            return outcome(subject)

    dispatcher = started_dispatcher(subject)
    if silent_mode == "instance_shadow":
        monkeypatch.setattr(dispatcher, "accept", lambda *_args, **_kwargs: None)
    elif silent_mode == "class_noop":
        monkeypatch.setattr(
            dispatch_module.WorkerDispatchService,
            "accept",
            lambda _self, *_args, **_kwargs: None,
        )
    else:
        def forged_accept(service, reservation, dispatch_outcome, *, deadline):
            return dispatch_module.DispatchAcceptance._issue(
                command_id=dispatch_outcome.permit.command_id,
                permit=dispatch_outcome.permit,
                profile_ref=reservation.profile_ref,
                deadline=deadline,
                service_token=service._service_token,
                slot_token=reservation._slot_token,
            )

        monkeypatch.setattr(
            dispatch_module.WorkerDispatchService,
            "accept",
            forged_accept,
        )
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    with pytest.raises(api_routes.ApiCommittedDispatchUnknown):
        api_routes._reserve_execute_and_handoff(
            CommittedRoot(),
            dispatcher,
            SimpleNamespace(command_id=subject.permit.command_id),
            object(),
            resolved,
            deadline(),
        )

    assert all(value == 0 for value in dispatcher._occupied.values())
    assert all(not queue for queue in dispatcher._queues.values())
    assert not dispatcher._issued_acceptances
    assert subject.ledger.pending_permit_count == 0
    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    dispatcher.close()


@pytest.mark.parametrize(
    "claim_mode",
    ("instance_shadow", "class_noop", "class_forged_return", "postcondition"),
)
def test_unverifiable_acceptance_claim_is_unknown_and_quarantined(
    subject,
    monkeypatch,
    started_dispatcher,
    claim_mode,
):
    class CommittedRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **_kwargs):
            return outcome(subject)

    dispatcher = started_dispatcher(subject)
    real_notify = dispatcher._condition.notify_all
    monkeypatch.setattr(dispatcher._condition, "notify_all", lambda: None)
    if claim_mode == "instance_shadow":
        monkeypatch.setattr(
            dispatcher,
            "claim_acceptance",
            lambda *_args, **_kwargs: None,
        )
    elif claim_mode == "class_noop":
        monkeypatch.setattr(
            dispatch_module.WorkerDispatchService,
            "claim_acceptance",
            lambda _self, *_args, **_kwargs: None,
        )
    elif claim_mode == "class_forged_return":
        def forged_claim(
            service,
            _acceptance,
            reservation,
            dispatch_outcome,
            *,
            deadline,
        ):
            return dispatch_module.DispatchAcceptance._issue(
                command_id=dispatch_outcome.permit.command_id,
                permit=dispatch_outcome.permit,
                profile_ref=reservation.profile_ref,
                deadline=deadline,
                service_token=service._service_token,
                slot_token=reservation._slot_token,
            )

        monkeypatch.setattr(
            dispatch_module.WorkerDispatchService,
            "claim_acceptance",
            forged_claim,
        )
    else:
        monkeypatch.setattr(
            dispatch_module.WorkerDispatchService,
            "claim_acceptance",
            lambda _self, acceptance, *_args, **_kwargs: acceptance,
        )
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    with pytest.raises(api_routes.ApiCommittedDispatchUnknown):
        api_routes._reserve_execute_and_handoff(
            CommittedRoot(),
            dispatcher,
            SimpleNamespace(command_id=subject.permit.command_id),
            object(),
            resolved,
            deadline(),
        )

    assert all(value == 0 for value in dispatcher._occupied.values())
    assert all(not queue for queue in dispatcher._queues.values())
    assert not dispatcher._issued_acceptances
    assert subject.ledger.pending_permit_count == 0
    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    monkeypatch.setattr(dispatcher._condition, "notify_all", real_notify)
    dispatcher.close()
    assert all(not thread.is_alive() for thread in dispatcher._threads)


def test_claim_failure_after_worker_becomes_active_is_unknown_without_leak(
    subject,
    monkeypatch,
    started_dispatcher,
):
    began = Event()
    finish = Event()

    def exchange(permit, _capability, *, deadline):
        began.set()
        assert finish.wait(deadline.require())
        return worker_module.AuthenticatedWorkerResponse(
            attempt_id=permit.attempt_id,
            connection_id="c" * 64,
            worker_boot_id="document-boot-1",
            message_id=identifier(),
            correlation_id=permit.command_id,
            message_type="completed",
            payload=b"{}",
        )

    class CommittedRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **_kwargs):
            return outcome(subject)

    dispatcher = started_dispatcher(subject)
    monkeypatch.setattr(subject.coordinator, "exchange", exchange)

    def fail_after_active(_service, *_args, **_kwargs):
        assert began.wait(1)
        raise RuntimeError("PRIVATE_CLAIM_FAILURE_AFTER_WORKER_ACTIVE")

    monkeypatch.setattr(
        dispatch_module.WorkerDispatchService,
        "claim_acceptance",
        fail_after_active,
    )
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    try:
        with pytest.raises(api_routes.ApiCommittedDispatchUnknown):
            api_routes._reserve_execute_and_handoff(
                CommittedRoot(),
                dispatcher,
                SimpleNamespace(command_id=subject.permit.command_id),
                object(),
                resolved,
                deadline(),
            )
        assert not dispatcher._issued_acceptances
        assert subject.ledger.pending_permit_count == 0
        assert subject.ledger.is_dispatch_emergency_inhibited is True
    finally:
        finish.set()
        dispatcher.wait_idle(deadline())

    assert all(value == 0 for value in dispatcher._occupied.values())
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    dispatcher.close()
    assert all(not thread.is_alive() for thread in dispatcher._threads)


def test_accept_transition_then_exception_quarantines_queue_before_unknown(
    subject,
    monkeypatch,
    started_dispatcher,
):
    class CommittedRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **_kwargs):
            return outcome(subject)

    dispatcher = started_dispatcher(subject)
    real_accept = dispatch_module.WorkerDispatchService.accept
    real_notify = dispatcher._condition.notify_all

    def transition_then_raise(service, *args, **kwargs):
        real_accept(service, *args, **kwargs)
        raise RuntimeError("PRIVATE_AFTER_TRANSFER_FAILURE")

    # Keep the queue item pending long enough to prove exact quarantine removes it.
    monkeypatch.setattr(dispatcher._condition, "notify_all", lambda: None)
    monkeypatch.setattr(
        dispatch_module.WorkerDispatchService,
        "accept",
        transition_then_raise,
    )
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    with pytest.raises(api_routes.ApiCommittedDispatchUnknown):
        api_routes._reserve_execute_and_handoff(
            CommittedRoot(),
            dispatcher,
            SimpleNamespace(command_id=subject.permit.command_id),
            object(),
            resolved,
            deadline(),
        )

    assert all(value == 0 for value in dispatcher._occupied.values())
    assert not dispatcher._issued_acceptances
    assert all(not queue for queue in dispatcher._queues.values())
    assert subject.ledger.pending_permit_count == 0
    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    monkeypatch.setattr(dispatcher._condition, "notify_all", real_notify)
    dispatcher.close()
    assert all(not thread.is_alive() for thread in dispatcher._threads)


def test_close_race_during_root_commit_cannot_leave_capacity_or_permit(
    subject,
    started_dispatcher,
):
    entered_root = Event()
    finish_root = Event()
    failures = []

    class BlockingCommittedRoot:
        _ledger = subject.ledger

        def execute_budgeted_dispatch(self, *_args, **kwargs):
            entered_root.set()
            assert finish_root.wait(kwargs["deadline"].require())
            return outcome(subject)

    dispatcher = started_dispatcher(subject)
    resolved = SimpleNamespace(
        authorization=object(),
        attempt_id=subject.permit.attempt_id,
        owner=subject.permit.owner,
        budget_request=object(),
        route_profile_ref=subject.records.profile.ref,
    )

    def handoff():
        try:
            api_routes._reserve_execute_and_handoff(
                BlockingCommittedRoot(),
                dispatcher,
                SimpleNamespace(command_id=subject.permit.command_id),
                object(),
                resolved,
                deadline(),
            )
        except BaseException as exc:  # noqa: BLE001 - assert exact boundary result
            failures.append(exc)

    helper = Thread(target=handoff)
    helper.start()
    assert entered_root.wait(1)
    dispatcher.close()
    finish_root.set()
    helper.join(5)

    assert len(failures) == 1
    assert type(failures[0]) is api_routes.ApiCommittedDispatchUnknown
    assert all(value == 0 for value in dispatcher._occupied.values())
    assert not dispatcher._issued_acceptances
    assert subject.ledger.pending_permit_count == 0
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    assert all(not thread.is_alive() for thread in dispatcher._threads)


def test_deadline_expiry_during_accept_releases_capacity_and_records_unknown(
    subject,
    started_dispatcher,
):
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline(20)
    reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    Event().wait(route_deadline.remaining() + 0.01)

    with pytest.raises(dispatch_module.WorkerDispatchUnavailable):
        dispatcher.accept(
            reservation,
            outcome(subject),
            deadline=route_deadline,
        )

    assert all(value == 0 for value in dispatcher._occupied.values())
    assert not dispatcher._issued_acceptances
    assert subject.ledger.pending_permit_count == 0
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    dispatcher.close()


def test_close_invalidates_unclaimed_issuance_without_capacity_or_thread_leak(
    subject,
    started_dispatcher,
):
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline(2_000)
    reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    dispatch_outcome = outcome(subject)
    acceptance = dispatcher.accept(
        reservation,
        dispatch_outcome,
        deadline=route_deadline,
    )
    assert dispatcher._issued_acceptances[reservation._slot_token] is acceptance

    dispatcher.close()

    assert not dispatcher._issued_acceptances
    assert not dispatcher._owned_slots
    assert all(value == 0 for value in dispatcher._occupied.values())
    assert all(not queue for queue in dispatcher._queues.values())
    assert subject.ledger.pending_permit_count == 0
    assert all(not thread.is_alive() for thread in dispatcher._threads)
    with pytest.raises(dispatch_module.WorkerDispatchUnavailable):
        dispatcher.claim_acceptance(
            acceptance,
            reservation,
            dispatch_outcome,
            deadline=route_deadline,
        )


def test_exact_post_commit_handoff_records_only_redacted_transport_fact(
    subject,
    monkeypatch,
    started_dispatcher,
):
    transport = install_transport(monkeypatch, subject)
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    dispatch_outcome = outcome(subject)
    acceptance = dispatcher.accept(
        reservation,
        dispatch_outcome,
        deadline=route_deadline,
    )
    with pytest.raises(TypeError):
        copy.copy(acceptance)
    with pytest.raises(TypeError):
        copy.deepcopy(acceptance)
    with pytest.raises(TypeError):
        pickle.dumps(acceptance)
    with pytest.raises(TypeError):
        dispatch_module.DispatchAcceptance(
            dispatch_outcome.permit.command_id,
            dispatch_outcome.permit,
            dispatch_outcome.permit.profile_ref,
            route_deadline,
            object(),
            object(),
        )
    # The worker is not gated by receipt validation and may finish first.
    dispatcher.wait_idle(deadline())
    assert dispatcher._issued_acceptances[reservation._slot_token] is acceptance
    assert not dispatch_module.DispatchAcceptance._claim(
        acceptance,
        service_token=dispatcher._service_token,
        slot_token=object(),
        permit=dispatch_outcome.permit,
        command_id=reservation.command_id,
        profile_ref=reservation.profile_ref,
        deadline=route_deadline,
    )
    claimed = dispatcher.claim_acceptance(
        acceptance,
        reservation,
        dispatch_outcome,
        deadline=route_deadline,
    )
    assert claimed is acceptance
    assert reservation._slot_token not in dispatcher._issued_acceptances
    with pytest.raises(dispatch_module.WorkerDispatchUnavailable):
        dispatcher.claim_acceptance(
            acceptance,
            reservation,
            dispatch_outcome,
            deadline=route_deadline,
        )

    status = subject.ledger.dispatch_status(subject.permit.command_id)
    assert status["state"] == "running"
    assert status["dispatch"] == {
        "state": "transport_accepted",
        "effect": "transport_accepted",
    }
    assert status["attempt"]["phase"] == "running"
    assert status["attempt"]["send_finality"] == "transport_accepted"
    entries = [
        item for item in subject.ledger.attempt_journal(subject.permit.attempt_id)
        if item["transition"] == "transport_observed"
    ]
    assert len(entries) == 1
    serialized = repr(entries[0])
    assert "artifact_ref" not in serialized
    assert str(subject.route.channel_spec.pair_root) not in serialized
    assert "payload_sha256" in serialized and "payload_bytes" in serialized
    assert transport.socket.closed is True
    dispatcher.close()


@pytest.mark.parametrize("silent_mode", ("instance_shadow", "class_noop"))
def test_silent_success_observation_noop_inhibits_and_projects_unknown(
    subject,
    monkeypatch,
    started_dispatcher,
    silent_mode,
):
    install_transport(monkeypatch, subject)
    target = subject.ledger if silent_mode == "instance_shadow" else RuntimeLedger
    monkeypatch.setattr(target, "record_transport_observation", lambda *_args, **_kwargs: None)
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    accept_dispatch(dispatcher, reservation, outcome(subject), route_deadline)
    dispatcher.wait_idle(deadline())

    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.pending_permit_count == 0
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == (
        "outcome_unknown"
    )
    assert not [
        item for item in subject.ledger.attempt_journal(subject.permit.attempt_id)
        if item["transition"] == "transport_observed"
    ]
    assert all(thread.is_alive() for thread in dispatcher._threads)
    dispatcher.close()


@pytest.mark.parametrize("silent_mode", ("instance_shadow", "class_noop"))
def test_silent_failure_observation_noop_inhibits_and_projects_unknown(
    subject,
    monkeypatch,
    started_dispatcher,
    silent_mode,
):
    install_transport(
        monkeypatch,
        subject,
        write_error=broker.TransportClosed(dispatch_effect="definitely_not_sent"),
    )
    target = subject.ledger if silent_mode == "instance_shadow" else RuntimeLedger
    monkeypatch.setattr(target, "record_transport_observation", lambda *_args, **_kwargs: None)
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    accept_dispatch(dispatcher, reservation, outcome(subject), route_deadline)
    dispatcher.wait_idle(deadline())

    status = subject.ledger.dispatch_status(subject.permit.command_id)
    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.pending_permit_count == 0
    assert status["state"] == "outcome_unknown"
    assert status["dispatch"] == {
        "state": "recovery_pending",
        "effect": "outcome_unknown",
    }
    assert not [
        item for item in subject.ledger.attempt_journal(subject.permit.attempt_id)
        if item["transition"] == "transport_observed"
    ]
    assert all(thread.is_alive() for thread in dispatcher._threads)
    dispatcher.close()


def test_definite_transport_failure_closes_gate_without_settling_budget(
    subject,
    monkeypatch,
    started_dispatcher,
):
    install_transport(
        monkeypatch,
        subject,
        write_error=broker.TransportClosed(dispatch_effect="definitely_not_sent"),
    )
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    accept_dispatch(dispatcher, reservation, outcome(subject), route_deadline)
    dispatcher.wait_idle(deadline())

    status = subject.ledger.dispatch_status(subject.permit.command_id)
    assert status["state"] == "blocked"
    assert status["dispatch"] == {
        "state": "recovery_pending",
        "effect": "definitely_not_sent",
    }
    attempt = status["attempt"]
    assert attempt["phase"] == "send_intent"
    assert attempt["dispatch_gate"] == "closed"
    assert attempt["recovery_state"] == "pending"
    # The durable send-intent barrier stays conservative despite a local definite
    # failure, and this transport slice never settles usage.
    assert attempt["send_finality"] == "may_have_started"
    budget_state = subject.budget.status(subject.permit.budget_session_id)
    assert budget_state["usage_finality"] == "pending"
    assert budget_state["active_reservations"] == 1
    dispatcher.close()


def test_capacity_is_one_active_plus_the_declared_bounded_queue(
    subject,
    monkeypatch,
    started_dispatcher,
):
    started = Event()
    finish = Event()

    def exchange(permit, capability, *, deadline):
        del capability
        started.set()
        assert finish.wait(deadline.require())
        return worker_module.AuthenticatedWorkerResponse(
            attempt_id=permit.attempt_id,
            connection_id="c" * 64,
            worker_boot_id="document-boot-1",
            message_id=subject.permit.command_id,
            correlation_id=permit.command_id,
            message_type="completed",
            payload=b"{}",
        )

    monkeypatch.setattr(subject.coordinator, "exchange", exchange)
    dispatcher = started_dispatcher(subject)
    first_deadline = deadline()
    first = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=first_deadline,
    )
    accept_dispatch(dispatcher, first, outcome(subject), first_deadline)
    assert started.wait(1)

    queued = dispatcher.reserve(
        "10000000-0000-4000-8000-000000000001",
        subject.records.profile.ref,
        deadline=deadline(),
    )
    with pytest.raises(dispatch_module.WorkerDispatchBusy):
        dispatcher.reserve(
            "10000000-0000-4000-8000-000000000002",
            subject.records.profile.ref,
            deadline=deadline(),
        )
    dispatcher.release(queued)
    finish.set()
    dispatcher.wait_idle(deadline())
    dispatcher.close()


@pytest.mark.parametrize("mutation", ("reservation", "deadline"))
def test_every_post_commit_accept_mismatch_is_quarantined_and_consumes_capacity(
    subject,
    mutation,
    started_dispatcher,
):
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline()
    reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    supplied_reservation = reservation
    supplied_deadline = route_deadline
    if mutation == "reservation":
        supplied_reservation = replace(reservation, command_id=(
            "10000000-0000-4000-8000-000000000003"
        ))
    else:
        supplied_deadline = deadline()

    with pytest.raises(dispatch_module.WorkerDispatchUnavailable):
        dispatcher.accept(
            supplied_reservation,
            outcome(subject),
            deadline=supplied_deadline,
        )

    assert subject.ledger.pending_permit_count == 0
    status = subject.ledger.dispatch_status(subject.permit.command_id)
    assert status["state"] == "outcome_unknown"
    assert status["dispatch"] == {
        "state": "recovery_pending",
        "effect": "outcome_unknown",
    }
    # The mismatched handoff released its original reserved capacity.
    next_reservation = dispatcher.reserve(
        "10000000-0000-4000-8000-000000000004",
        subject.records.profile.ref,
        deadline=deadline(),
    )
    dispatcher.release(next_reservation)
    dispatcher.close()


def test_dispatcher_requires_reconciled_ledger_and_closed_generation_is_not_reused(
    subject,
    started_dispatcher,
):
    dispatcher = started_dispatcher(subject)
    dispatcher.close()
    subject.ledger.reconcile_startup(
        "10000000-0000-4000-8000-000000000005",
        observed_owners={},
    )
    with pytest.raises(dispatch_module.WorkerDispatchUnavailable):
        dispatcher.start()
    fresh = started_dispatcher(subject)
    fresh.close()

    reopened = type(subject.ledger)(subject.domain, clock_ms=lambda: 1_000)
    coordinator = worker_module.WorkerCoordinator(
        domain_store=subject.domain,
        permission_gate=subject.gate,
        runtime_ledger=reopened,
        budget_book=subject.budget,
        route=subject.route,
        boot_secret=broker.BootSecret(b"r" * broker.AUTH_SECRET_BYTES),
        requester_boot_id="control-boot-unreconciled",
        worker_boot_id="document-boot-unreconciled",
    )
    unreconciled = dispatch_module.WorkerDispatchService(
        runtime_ledger=reopened,
        coordinators=(coordinator,),
    )
    with pytest.raises(dispatch_module.WorkerDispatchUnavailable):
        unreconciled.start()


def test_unrecordable_post_commit_observation_inhibits_process_wide(
    subject,
    monkeypatch,
    started_dispatcher,
):
    install_transport(monkeypatch, subject)
    dispatcher = started_dispatcher(subject)
    monkeypatch.setattr(
        subject.ledger,
        "record_transport_observation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("SECRET")),
    )
    monkeypatch.setattr(
        subject.ledger,
        "emergency_inhibit_all_dispatch",
        lambda: (_ for _ in ()).throw(RuntimeError("PUBLIC_LATCH_FAILURE")),
    )
    route_deadline = deadline()
    reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    accept_dispatch(dispatcher, reservation, outcome(subject), route_deadline)
    dispatcher.wait_idle(deadline())

    assert subject.ledger.is_dispatch_emergency_inhibited is True
    assert subject.ledger.pending_permit_count == 0
    status = subject.ledger.dispatch_status(subject.permit.command_id)
    assert status["state"] == "outcome_unknown"
    assert status["dispatch"] == {
        "state": "recovery_pending",
        "effect": "outcome_unknown",
    }
    occupied = dispatcher._occupied.copy()
    with pytest.raises(dispatch_module.WorkerDispatchUnavailable):
        dispatcher.reserve(
            identifier(),
            subject.records.profile.ref,
            deadline=deadline(),
        )
    assert dispatcher._occupied == occupied
    assert all(thread.is_alive() for thread in dispatcher._threads)
    dispatcher.close()
    assert all(not thread.is_alive() for thread in dispatcher._threads)
    with pytest.raises(dispatch_module.WorkerDispatchUnavailable):
        service(subject).start()


def test_close_drains_accepted_queue_without_new_deadline_or_send(
    subject,
    monkeypatch,
    started_dispatcher,
):
    second = additional_outcome(subject)
    began = Event()
    release = Event()
    calls = []

    def exchange(permit, capability, *, deadline):
        del capability
        calls.append(permit.command_id)
        began.set()
        assert release.wait(deadline.require())
        return worker_module.AuthenticatedWorkerResponse(
            attempt_id=permit.attempt_id,
            connection_id="c" * 64,
            worker_boot_id="document-boot-1",
            message_id=identifier(),
            correlation_id=permit.command_id,
            message_type="completed",
            payload=b"{}",
        )

    monkeypatch.setattr(subject.coordinator, "exchange", exchange)
    dispatcher = started_dispatcher(subject)
    route_deadline = deadline(2_000)
    first_reservation = dispatcher.reserve(
        subject.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    accept_dispatch(
        dispatcher,
        first_reservation,
        outcome(subject),
        route_deadline,
    )
    assert began.wait(1)
    second_reservation = dispatcher.reserve(
        second.permit.command_id,
        subject.records.profile.ref,
        deadline=route_deadline,
    )
    accept_dispatch(dispatcher, second_reservation, second, route_deadline)

    timer = Timer(0.05, release.set)
    timer.start()
    dispatcher.close()
    timer.join()

    assert calls == [subject.permit.command_id]
    assert subject.ledger.dispatch_status(subject.permit.command_id)["state"] == "running"
    queued_status = subject.ledger.dispatch_status(second.permit.command_id)
    assert queued_status["state"] == "outcome_unknown"
    assert queued_status["dispatch"]["effect"] == "outcome_unknown"
    assert all(not thread.is_alive() for thread in dispatcher._threads)
