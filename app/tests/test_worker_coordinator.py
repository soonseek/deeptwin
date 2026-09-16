"""Offline failure-first tests for the isolated-worker dispatch coordinator."""

import inspect
import time
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.session import LocalSessionAuthority
from app.domain.permissions import create_persistent_policy
from app.domain.refs import EntityRef
from app.domain.schemas import Actor, ImmutableRecord
from app.domain.store import DomainStore
from app.runtime import worker_coordinator as worker_module
from app.runtime.budgets import BudgetBook, BudgetDispatchRequest, BudgetPolicy
from app.runtime.ledger import (
    AttemptSpec,
    ExecutionSpec,
    OwnerIdentity,
    RunSpec,
    RuntimeLedger,
)
from app.storage import Store
from app.workers import broker

STAMP = "2026-09-08T00:00:00.000000Z"
ORIGIN = "http://127.0.0.1:4197"


def identifier() -> str:
    return str(uuid4())


def immutable(
    domain: DomainStore,
    roots: object,
    kind: str,
    *,
    content: dict[str, object] | None = None,
    actor_ref: EntityRef | None = None,
) -> ImmutableRecord:
    record = ImmutableRecord.create(
        kind=kind,
        id=identifier(),
        version=1,
        created_at_utc=STAMP,
        actor_ref=roots.actor if actor_ref is None else actor_ref,
        parent_refs=(),
        purpose="operational",
        access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"fixture": kind} if content is None else content,
    )
    domain.put(record)
    return record


def channel_spec(pair_root) -> broker.ChannelSpec:
    return broker.ChannelSpec(
        channel_id="control-document",
        requester_service="control",
        responder_service="document",
        request_direction="control-to-document",
        protocol_id="document-command-v1",
        requester_uid=10_001,
        requester_gid=10_002,
        responder_uid=10_003,
        responder_gid=10_004,
        pair_gid=10_005,
        pair_root=pair_root,
        socket_name="document.sock",
        root_uid=10_003,
        root_gid=10_005,
        socket_uid=10_003,
        socket_gid=10_005,
        requester_message_types=("execute",),
        responder_message_types=("completed", "failed"),
        max_queue_depth=1,
    )


def build_subject(tmp_path, *, envelope_content=None, profile_content=None, lease_duration_ms=2_000,
                  human_authored=False):
    legacy = Store(tmp_path / "vault")
    domain = DomainStore(legacy)
    roots = domain.initialize_vault()

    session_clock = [1_000]
    authority = LocalSessionAuthority(
        {"127.0.0.1:4197"},
        clock=lambda: session_clock[0],
        session_ttl_seconds=900,
    )
    bootstrap = authority.mint_bootstrap()
    session = authority.exchange_bootstrap(
        bootstrap.capability,
        method="POST",
        host="127.0.0.1:4197",
        origin=ORIGIN,
        sec_fetch_site="same-origin",
    )

    permission_clock = [1_000]
    host, gate = create_persistent_policy(
        domain,
        authenticate_session=authority.authenticate_bound,
        verify_projection=lambda _value: False,
        clock=lambda: permission_clock[0],
    )
    human = host.bind_human(session.session, expires_at=1_500)
    runtime = host.bind_runtime(
        Actor(identifier(), "provider", "model_output"),
        purpose="operational",
        expires_at=1_400,
    )

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
    author_ref = roots.actor
    if human_authored:
        author = ImmutableRecord.create(
            kind="actor", id=human.actor.id, version=1, created_at_utc=STAMP,
            actor_ref=roots.actor, parent_refs=(), purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
            content={"id": human.actor.id, "kind": "human", "origin": "local_session"},
        )
        domain.put(author)
        host.register_record(author)
        author_ref = author.ref
    records = SimpleNamespace(
        work=immutable(domain, roots, "work_revision"),
        environment=immutable(domain, roots, "environment"),
        consent=immutable(domain, roots, "run_consent"),
        budget=immutable(
            domain,
            roots,
            "budget_policy",
            content=policy.domain_content(),
        ),
        manifest=immutable(domain, roots, "run_manifest"),
        envelope=immutable(
            domain,
            roots,
            "execution_envelope",
            content=({"operation": "render", "artifact": "report.pdf"}
                     if envelope_content is None else envelope_content),
            actor_ref=author_ref,
        ),
        profile=immutable(domain, roots, "runtime_profile", content=profile_content),
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
    budget = BudgetBook(legacy, clock=lambda: budget_clock[0])
    budget_session_id = identifier()
    budget.start(budget_session_id, policy)

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
    execution = ExecutionSpec(
        identifier(),
        run.run_id,
        "document",
        identifier(),
        (0,),
        (),
    )
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
    ledger.reserve_attempt(identifier(), attempt, lease_duration_ms=lease_duration_ms)
    request = BudgetDispatchRequest.create(
        session_id=budget_session_id,
        request_id=attempt.reservation_id,
        policy_ref=records.budget.ref,
        model_calls=0,
        tool_calls=1,
        node_visits=1,
        loop_rounds=0,
        output_bytes=1_000,
        candidates=0,
        api_microunits=None,
    )
    command_id = identifier()
    permit = ledger.commit_budgeted_send_intent(
        command_id,
        attempt.attempt_id,
        owner,
        expected_revision=1,
        budget_book=budget,
        budget_request=request,
        principal=runtime,
        grant=grant,
    )
    capability = worker_module.SelectedDispatchReadCapability(
        permit_id=permit.permit_id,
        command_id=permit.command_id,
        principal=runtime,
        grant=grant,
        resource_ref=records.envelope.ref,
        purpose="operational",
        episode_id=None,
    )
    route = worker_module.WorkerRouteBinding(
        profile_ref=records.profile.ref,
        channel_spec=channel_spec(tmp_path / "worker-pair"),
        request_message_type="execute",
        response_message_types=("completed", "failed"),
    )
    coordinator = worker_module.WorkerCoordinator(
        domain_store=domain,
        permission_gate=gate,
        runtime_ledger=ledger,
        budget_book=budget,
        route=route,
        boot_secret=broker.BootSecret(b"k" * broker.AUTH_SECRET_BYTES),
        requester_boot_id="control-boot-1",
        worker_boot_id="document-boot-1",
    )
    return SimpleNamespace(
        legacy=legacy,
        domain=domain,
        host=host,
        gate=gate,
        human=human,
        runtime=runtime,
        grant=grant,
        records=records,
        budget=budget,
        ledger=ledger,
        permit=permit,
        capability=capability,
        route=route,
        coordinator=coordinator,
    )


@pytest.fixture
def subject(tmp_path):
    return build_subject(tmp_path)


class FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def response_frame(subject, *, correlation_id=None, message_type="completed"):
    payload = b'{"artifact_ref":"sha256:result"}'
    return broker.ReceivedFrame(
        envelope=broker.FrameEnvelope(
            schema_version="deeptwin-worker-envelope-v2",
            protocol_version=broker.PROTOCOL_VERSION,
            protocol_id=subject.route.channel_spec.protocol_id,
            channel_id=subject.route.channel_spec.channel_id,
            requester_boot_id="control-boot-1",
            responder_boot_id="document-boot-1",
            connection_id="c" * 64,
            sender="document",
            receiver="control",
            direction="document-to-control",
            sequence=1,
            message_id=identifier(),
            correlation_id=(
                subject.permit.command_id
                if correlation_id is None
                else correlation_id
            ),
            message_type=message_type,
            payload_bytes=len(payload),
            payload_sha256="a" * 64,
            payload_b64="e30=",
            mac="b" * 64,
        ),
        payload=payload,
    )


def install_transport(
    monkeypatch,
    subject,
    *,
    frame=None,
    write_error: broker.BrokerError | None = None,
    read_error: broker.BrokerError | None = None,
):
    events: list[object] = []
    sock = FakeSocket()
    codecs = []

    def connect(spec, *, local_service, deadline):
        events.append("connect")
        assert spec is subject.route.channel_spec
        assert local_service == spec.requester_service
        assert type(deadline) is broker.Deadline
        return sock, None, None

    def handshake(
        value,
        spec,
        secret,
        *,
        requester_boot_id,
        responder_boot_id,
        deadline,
    ):
        events.append("handshake")
        assert value is sock
        assert spec is subject.route.channel_spec
        assert secret is subject.coordinator._secret
        assert requester_boot_id == "control-boot-1"
        assert responder_boot_id == "document-boot-1"
        assert type(deadline) is broker.Deadline
        return SimpleNamespace(
            connection_id="c" * 64,
            requester_boot_id="control-boot-1",
            responder_boot_id="document-boot-1",
        )

    class FakeCodec:
        def __init__(self, spec, session, *, local_service):
            assert spec is subject.route.channel_spec
            assert session.connection_id == "c" * 64
            assert local_service == spec.requester_service
            self.closed = False
            self.writes = []
            codecs.append(self)
            events.append("codec")

        def write(self, value, **kwargs):
            events.append("write")
            assert value is sock
            self.writes.append(kwargs)
            if write_error is not None:
                raise write_error

        def read(self, value, *, deadline):
            events.append("read")
            assert value is sock
            assert type(deadline) is broker.Deadline
            if read_error is not None:
                raise read_error
            return response_frame(subject) if frame is None else frame

        def close(self):
            self.closed = True
            events.append("codec-close")

    monkeypatch.setattr(worker_module.broker, "connect_verified", connect)
    monkeypatch.setattr(worker_module.broker, "client_handshake", handshake)
    monkeypatch.setattr(worker_module.broker, "FrameCodec", FakeCodec)
    return SimpleNamespace(events=events, socket=sock, codecs=codecs)


def deadline() -> broker.Deadline:
    return broker.Deadline.after_ms(5_000)


def test_constructor_and_exchange_reject_cross_component_or_capability_binding(
    subject,
    tmp_path,
    monkeypatch,
):
    other_budget = BudgetBook(Store(tmp_path / "other-vault"), clock=lambda: 100)
    with pytest.raises(TypeError, match="components are not exactly bound"):
        worker_module.WorkerCoordinator(
            domain_store=subject.domain,
            permission_gate=subject.gate,
            runtime_ledger=subject.ledger,
            budget_book=other_budget,
            route=subject.route,
            boot_secret=broker.BootSecret(b"q" * broker.AUTH_SECRET_BYTES),
            requester_boot_id="control-boot-2",
            worker_boot_id="document-boot-2",
        )

    consumed = []

    def forbidden_consume(*_args, **_kwargs):
        consumed.append(True)
        raise AssertionError("a mismatched capability must not consume the permit")

    monkeypatch.setattr(
        subject.ledger,
        "consume_dispatch_permit_window",
        forbidden_consume,
    )
    mismatched = replace(subject.capability, command_id=identifier())
    with pytest.raises(worker_module.WorkerCoordinatorError):
        subject.coordinator.exchange(subject.permit, mismatched, deadline=deadline())
    assert consumed == []
    assert subject.ledger.pending_permit_count == 1


def test_cloned_permit_is_not_a_process_local_capability(subject):
    cloned = replace(subject.permit)
    assert cloned == subject.permit and cloned is not subject.permit

    with pytest.raises(worker_module.WorkerCoordinatorError):
        subject.coordinator.exchange(cloned, subject.capability, deadline=deadline())

    assert subject.ledger.pending_permit_count == 1


def test_command_selected_grant_cannot_be_replaced_before_consumption(
    subject,
    monkeypatch,
):
    subject.host.revoke(subject.grant)
    replacement = subject.host.grant(
        subject.human,
        subject.runtime,
        subject.records.envelope.ref,
        action="read",
        purpose="operational",
        expires_at=1_300,
    )
    forged = worker_module.SelectedDispatchReadCapability(
        permit_id=subject.permit.permit_id,
        command_id=subject.permit.command_id,
        principal=subject.runtime,
        grant=replacement,
        resource_ref=subject.records.envelope.ref,
        purpose="operational",
        episode_id=None,
    )
    connect_calls = []
    monkeypatch.setattr(
        worker_module.broker,
        "connect_verified",
        lambda *_args, **_kwargs: connect_calls.append(True),
    )

    with pytest.raises(worker_module.WorkerCoordinatorError):
        subject.coordinator.exchange(subject.permit, forged, deadline=deadline())

    assert subject.ledger.pending_permit_count == 1
    assert connect_calls == []


def test_no_payload_argument_and_exact_immutable_envelope_bytes_are_sent(
    subject,
    monkeypatch,
):
    parameters = inspect.signature(subject.coordinator.exchange).parameters
    assert tuple(parameters) == (
        "permit",
        "capability",
        "deadline",
        "artifact_inputs",
        "artifact_output_policy",
    )
    with pytest.raises(TypeError, match="unexpected keyword argument 'payload'"):
        subject.coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
            payload=b"caller-controlled",
        )
    assert subject.ledger.pending_permit_count == 1

    transport = install_transport(monkeypatch, subject)
    response = subject.coordinator.exchange(
        subject.permit,
        subject.capability,
        deadline=deadline(),
    )

    assert type(response) is worker_module.AuthenticatedWorkerResponse
    assert response.attempt_id == subject.permit.attempt_id
    assert response.connection_id == "c" * 64
    assert response.worker_boot_id == "document-boot-1"
    assert response.correlation_id == subject.permit.command_id
    assert response.message_type == "completed"
    assert len(transport.codecs) == 1
    assert transport.codecs[0].writes == [{
        "message_id": subject.permit.command_id,
        "correlation_id": subject.permit.attempt_id,
        "message_type": "execute",
        "payload": subject.records.envelope.body_bytes,
        "deadline": transport.codecs[0].writes[0]["deadline"],
    }]
    assert transport.socket.closed is True
    assert transport.codecs[0].closed is True


def test_permit_is_consumed_before_load_and_connect(subject, monkeypatch):
    events = []
    original_consume = subject.ledger.consume_dispatch_permit_window
    original_get = subject.domain.get

    def consume(*args, **kwargs):
        events.append("consume")
        return original_consume(*args, **kwargs)

    def load(ref):
        events.append(("load", ref.kind))
        return original_get(ref)

    monkeypatch.setattr(subject.ledger, "consume_dispatch_permit_window", consume)
    monkeypatch.setattr(subject.domain, "get", load)
    transport = install_transport(monkeypatch, subject)
    original_connect = worker_module.broker.connect_verified

    def connect(*args, **kwargs):
        events.append("connect")
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(worker_module.broker, "connect_verified", connect)

    subject.coordinator.exchange(
        subject.permit,
        subject.capability,
        deadline=deadline(),
    )

    assert events[0] == "consume"
    assert ("load", "execution_envelope") in events
    assert events.index(("load", "execution_envelope")) < events.index("connect")
    assert subject.ledger.pending_permit_count == 0
    assert transport.socket.closed is True


def test_channel_operation_deadline_is_fixed_before_queue_admission(
    subject,
):
    short_spec = replace(subject.route.channel_spec, max_operation_ms=20)
    route = replace(subject.route, channel_spec=short_spec)
    coordinator = worker_module.WorkerCoordinator(
        domain_store=subject.domain,
        permission_gate=subject.gate,
        runtime_ledger=subject.ledger,
        budget_book=subject.budget,
        route=route,
        boot_secret=broker.BootSecret(b"z" * broker.AUTH_SECRET_BYTES),
        requester_boot_id="control-boot-short",
        worker_boot_id="document-boot-short",
    )
    captured = []

    class RejectAdmission:
        def acquire(self, value):
            captured.append(value)
            raise broker.DeadlineExceeded()

    coordinator._admission = RejectAdmission()
    started = time.monotonic()

    with pytest.raises(broker.DeadlineExceeded):
        coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=broker.Deadline.after_ms(5_000),
        )

    assert len(captured) == 1
    assert captured[0].end_monotonic <= started + 0.05
    assert subject.ledger.pending_permit_count == 1


def test_consumption_validation_latency_cannot_restart_transport_deadline(
    subject,
    monkeypatch,
):
    original = subject.ledger.consume_dispatch_permit_window
    loads = []

    def expired_window(*args, **kwargs):
        return replace(original(*args, **kwargs), anchor_monotonic=1.0)

    def forbidden_load(*args, **kwargs):
        loads.append((args, kwargs))
        raise AssertionError("expired absolute window must fail before payload load")

    monkeypatch.setattr(
        subject.ledger,
        "consume_dispatch_permit_window",
        expired_window,
    )
    monkeypatch.setattr(subject.coordinator, "_load_payload", forbidden_load)

    with pytest.raises(broker.DeadlineExceeded):
        subject.coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
        )

    assert loads == []
    assert subject.ledger.pending_permit_count == 0
    assert subject.coordinator._admission.in_flight == 0


def test_permission_revocation_during_load_fails_closed_before_transport(
    subject,
    monkeypatch,
):
    original_get = subject.domain.get
    connect_calls = []

    def load_then_revoke(ref):
        record = original_get(ref)
        subject.host.revoke(subject.grant)
        return record

    def forbidden_connect(*_args, **_kwargs):
        connect_calls.append(True)
        raise AssertionError("revoked immutable bytes must not reach transport")

    monkeypatch.setattr(subject.domain, "get", load_then_revoke)
    monkeypatch.setattr(worker_module.broker, "connect_verified", forbidden_connect)

    with pytest.raises(worker_module.WorkerPayloadRejected) as captured:
        subject.coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
        )

    assert captured.value.dispatch_effect == "definitely_not_sent"
    assert connect_calls == []
    assert subject.ledger.pending_permit_count == 0


@pytest.mark.parametrize(
    ("correlation_id", "message_type"),
    (
        (identifier(), "completed"),
        (None, "failed-extra"),
    ),
)
def test_response_requires_exact_command_correlation_and_declared_type(
    subject,
    monkeypatch,
    correlation_id,
    message_type,
):
    frame = response_frame(
        subject,
        correlation_id=correlation_id,
        message_type=message_type,
    )
    transport = install_transport(monkeypatch, subject, frame=frame)

    with pytest.raises(broker.ProtocolViolation) as captured:
        subject.coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
        )

    assert captured.value.dispatch_effect == "outcome_unknown"
    assert transport.socket.closed is True
    assert transport.codecs[0].closed is True


def test_authenticated_worker_generation_must_match_before_application_send(
    subject,
    monkeypatch,
):
    transport = install_transport(monkeypatch, subject)

    def stale_worker(value, spec, secret, **kwargs):
        del value, spec, secret, kwargs
        return SimpleNamespace(
            connection_id="c" * 64,
            requester_boot_id="control-boot-1",
            responder_boot_id="stale-document-boot",
        )

    monkeypatch.setattr(worker_module.broker, "client_handshake", stale_worker)

    with pytest.raises(broker.AuthenticationError) as captured:
        subject.coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
        )

    assert captured.value.dispatch_effect == "definitely_not_sent"
    assert transport.events == ["connect"]
    assert transport.socket.closed is True


@pytest.mark.parametrize(
    ("phase", "error_type", "effect"),
    (
        ("write", broker.TransportUncertain, "may_have_started"),
        ("read", broker.TransportUncertain, "outcome_unknown"),
    ),
)
def test_transport_failures_preserve_effect_and_release_every_local_resource(
    subject,
    monkeypatch,
    phase,
    error_type,
    effect,
):
    error = error_type(dispatch_effect=effect)
    transport = install_transport(
        monkeypatch,
        subject,
        write_error=error if phase == "write" else None,
        read_error=error if phase == "read" else None,
    )

    with pytest.raises(error_type) as captured:
        subject.coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
        )

    assert captured.value is error
    assert captured.value.dispatch_effect == effect
    assert transport.socket.closed is True
    assert transport.codecs[0].closed is True
    assert subject.coordinator._admission.queued == 0


def test_consumed_permit_cannot_dispatch_twice(subject, monkeypatch):
    transport = install_transport(monkeypatch, subject)
    first = subject.coordinator.exchange(
        subject.permit,
        subject.capability,
        deadline=deadline(),
    )
    assert first.message_type == "completed"

    with pytest.raises(worker_module.WorkerCoordinatorError) as captured:
        subject.coordinator.exchange(
            subject.permit,
            subject.capability,
            deadline=deadline(),
        )

    assert captured.value.dispatch_effect == "definitely_not_sent"
    assert transport.events.count("connect") == 1
    assert transport.events.count("write") == 1
    assert subject.ledger.pending_permit_count == 0
    assert subject.coordinator._admission.queued == 0


def test_route_profile_is_bound_before_permit_consumption(subject, monkeypatch):
    wrong_profile = EntityRef(
        "runtime_profile",
        identifier(),
        1,
        "0" * 64,
    )
    route = replace(subject.route, profile_ref=wrong_profile)
    coordinator = worker_module.WorkerCoordinator(
        domain_store=subject.domain,
        permission_gate=subject.gate,
        runtime_ledger=subject.ledger,
        budget_book=subject.budget,
        route=route,
        boot_secret=broker.BootSecret(b"r" * broker.AUTH_SECRET_BYTES),
        requester_boot_id="control-boot-wrong-profile",
        worker_boot_id="document-boot-wrong-profile",
    )
    connect_calls = []
    monkeypatch.setattr(
        worker_module.broker,
        "connect_verified",
        lambda *_args, **_kwargs: connect_calls.append(True),
    )

    with pytest.raises(worker_module.WorkerCoordinatorError):
        coordinator.exchange(subject.permit, subject.capability, deadline=deadline())

    assert subject.ledger.pending_permit_count == 1
    assert connect_calls == []
