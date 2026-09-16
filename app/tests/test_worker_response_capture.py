"""Real authenticated socketpair capture; OS peer/endpoint checks alone are bypassed.

The host/worker handshake, MAC framing, correlation, stream and SQLite are real.
No live providers, microphone, credentials, or external network are used.
"""

import copy
import socket
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest

from app.domain.permissions import AccessDenied
from app.domain.refs import DomainContractError, EntityRef
from app.domain.schemas import ImmutableRecord
from app.domain.store import BlobRef, DomainStore, StorageError
from app.runtime.ledger import LedgerError, RuntimeLedger
from app.runtime.worker_coordinator import WorkerCoordinatorError
from app.runtime.worker_dispatch import DispatchOutcome, WorkerDispatchService
from app.runtime.worker_response_capture import (
    WorkerResponseCaptureGap,
    _load_response_bytes,
    _lookup_response_capture,
)
from app.tests.test_worker_coordinator import build_subject, immutable
from app.workers import broker
from app.workers.artifact_stream import (
    ArtifactDescriptor,
    BytesSource,
    OfferedBatchPolicy,
    StreamLimits,
    send_batch,
)
from app.workers.artifact_stream_transport import FrameCodecTransport

PAYLOAD = b' \n{"result": "e\xcc\x81", "n": 1}\t\x00\xff'


def wire(value, monkeypatch, *, payload=PAYLOAD, before_response=None, outputs=(), invalid_offer=None):
    client, server = socket.socketpair()
    failures = []

    def worker():
        try:
            deadline = broker.Deadline.after_ms(5000)
            session = broker.server_handshake(
                server, value.route.channel_spec, value.coordinator._secret,
                requester_boot_id="control-boot-1", responder_boot_id="document-boot-1",
                deadline=deadline,
            )
            codec = broker.FrameCodec(value.route.channel_spec, session,
                                     local_service="document")
            request = codec.read(server, deadline=deadline)
            assert request.payload == value.records.envelope.body_bytes
            if before_response is not None:
                before_response()
            if invalid_offer is not None:
                import json

                codec.write(server, message_id=str(uuid4()),
                            correlation_id=value.permit.command_id, message_type="artifact-stream",
                            payload=json.dumps(invalid_offer).encode("ascii"), deadline=deadline)
                codec.close()
                return
            if outputs:
                send_batch(FrameCodecTransport(codec, server, message_type="artifact-stream",
                                               correlation_id=value.permit.command_id,
                                               deadline=deadline),
                           [item[0] for item in outputs], [BytesSource(item[1]) for item in outputs],
                           limits=StreamLimits())
            codec.write(server, message_id=str(uuid4()),
                        correlation_id=value.permit.command_id,
                        message_type="completed", payload=payload, deadline=deadline)
            codec.close()
        except BaseException as exc:  # noqa: BLE001 - surface every owned worker failure in parent
            failures.append(exc)
        finally:
            server.close()

    monkeypatch.setattr(broker, "connect_verified", lambda *args, **kwargs: (client, None, None))
    monkeypatch.setattr(broker, "_verify_peer", lambda *args, **kwargs: None)
    thread = Thread(target=worker, daemon=True)
    thread.start()
    return thread, failures


def dispatch(value, *, policy=None):
    dispatcher = WorkerDispatchService(runtime_ledger=value.ledger,
                                       coordinators=(value.coordinator,))
    dispatcher.start()
    try:
        deadline = broker.Deadline.after_ms(5000)
        reservation = dispatcher.reserve(value.permit.command_id,
                                         value.route.profile_ref, deadline=deadline)
        outcome = DispatchOutcome({}, value.permit, False, value.capability)
        acceptance = dispatcher.accept(reservation, outcome, deadline=deadline,
                                       artifact_output_policy=policy)
        dispatcher.claim_acceptance(acceptance, reservation, outcome, deadline=deadline)
        dispatcher.wait_idle(deadline)
    finally:
        dispatcher.close()


def test_real_dispatch_persists_exact_payload_for_reopen(tmp_path, monkeypatch):
    value = build_subject(tmp_path)
    thread, failures = wire(value, monkeypatch)
    dispatch(value)
    thread.join(5)
    assert not thread.is_alive()
    assert failures == []
    reopened = RuntimeLedger(DomainStore(value.legacy), clock_ms=lambda: 1000)
    entries = reopened.attempt_journal(value.permit.attempt_id)
    captures = [entry for entry in entries if entry["transition"] == "response_captured"]
    assert len(captures) == 1, "authenticated response bytes have no durable capture reference"
    ref = EntityRef.from_dict(captures[0]["payload"]["capture_ref"])
    content = reopened._domain.get(ref).body["content"]
    assert reopened._domain.read_blob(BlobRef.from_dict(content["payload_blob"]),
                                      purpose="operational") == PAYLOAD
    assert captures[0]["payload"]["classification"] == "pending_validation"
    assert content["artifacts"] == []
    assert value.ledger.dispatch_status(value.permit.command_id)["state"] == "running"
    result = reopened.reconcile_startup(str(uuid4()), observed_owners={})
    assert result["unknown_count"] == 0
    assert result["recovery_pending_count"] == 1
    status = reopened.dispatch_status(value.permit.command_id)
    assert status["state"] == "outcome_unknown"
    assert status["attempt"]["phase"] == "running"
    assert status["attempt"]["recovery_state"] == "pending"
    assert status["attempt"]["dispatch_gate"] == "closed"
    assert status["attempt"]["accepted_observation_id"] is None
    assert status["attempt"]["usage_finality"] != "final"
    assert _lookup_response_capture(reopened, value.permit.command_id) == ref
    with pytest.raises(LedgerError):
        _lookup_response_capture(value.ledger, value.permit.command_id)


def exchange(value, monkeypatch, **kwargs):
    thread, failures = wire(value, monkeypatch, **kwargs)
    response = value.coordinator.exchange(value.permit, value.capability,
                                         deadline=broker.Deadline.after_ms(5000))
    thread.join(5)
    assert not thread.is_alive()
    assert failures == []
    return response


def grants_for(value, ref):
    return tuple(value.host.grant(value.human, value.runtime, resource,
                                  action="read", purpose="operational", expires_at=1300)
                 for resource in (ref, value.records.profile.ref)) + (value.grant,)


def test_exact_receipt_duplicate_and_authorized_replay(tmp_path, monkeypatch):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    ref = value.coordinator.capture_response(value.permit, response)
    before = value.ledger.attempt_journal(value.permit.attempt_id)
    assert value.coordinator.capture_response(value.permit, response) == ref
    assert value.ledger.attempt_journal(value.permit.attempt_id) == before
    assert value.coordinator._active_responses == {}
    with pytest.raises(AccessDenied):
        _load_response_bytes(value.ledger, value.gate, value.runtime, value.permit.command_id,
                             purpose="operational", grants=(value.grant,))
    grants = grants_for(value, ref)
    replay = _load_response_bytes(value.ledger, value.gate, value.runtime, value.permit.command_id,
                                  purpose="operational", grants=grants)
    assert replay.payload == PAYLOAD
    assert replay.artifacts == ()
    assert "result" not in repr(replay)
    with pytest.raises((AttributeError, TypeError)):
        replay.payload = b"changed"
    with pytest.raises(AccessDenied):
        _load_response_bytes(value.ledger, value.gate, value.runtime, value.permit.command_id,
                             purpose="diagnosis", grants=grants)


@pytest.mark.parametrize("mode", ("construct", "replace", "copy", "foreign", "mutate", "abort"))
def test_only_original_authenticated_response_can_attach(tmp_path, monkeypatch, mode):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    target = value.coordinator
    if mode == "construct":
        response = type(response)(response.attempt_id, response.connection_id, response.worker_boot_id,
                                  response.message_id, response.correlation_id,
                                  response.message_type, response.payload)
    elif mode == "replace":
        response = replace(response)
    elif mode == "copy":
        response = copy.copy(response)
    elif mode == "foreign":
        target = build_subject(tmp_path / "foreign").coordinator
    elif mode == "mutate":
        object.__setattr__(response, "payload", b"changed")
    else:
        target.abort_response(response)
    with pytest.raises((WorkerCoordinatorError, LedgerError)):
        target.capture_response(value.permit, response)
    assert not [entry for entry in value.ledger.attempt_journal(value.permit.attempt_id)
                if entry["transition"] == "response_captured"]


@pytest.mark.parametrize("cause", ("cancel", "deadline", "lease", "fence", "recovery", "terminal"))
def test_late_response_is_quarantined_without_reopening(tmp_path, monkeypatch, cause):
    value = build_subject(tmp_path)

    def before_response():
        if cause == "cancel":
            value.ledger.request_cancel(str(uuid4()), value.permit.attempt_id, expected_revision=2)
        elif cause in {"deadline", "lease"}:
            value.ledger._clock = lambda: 10000 if cause == "deadline" else 3000
        elif cause == "fence":
            value.ledger.renew_lease(str(uuid4()), value.permit.attempt_id, value.permit.owner,
                                    expected_revision=2, lease_duration_ms=3000)
        elif cause == "recovery":
            with value.ledger._transaction(write=True) as db:
                db.execute("UPDATE runtime_attempts SET recovery_state='pending',dispatch_gate='closed',"
                           "dispatch_blocked_at_ms=1000 "
                           "WHERE id=?", (value.permit.attempt_id,))
        else:
            # Real startup makes the known ownerless sent attempt terminal unknown.
            value.ledger.reconcile_startup(str(uuid4()), observed_owners={})

    response = exchange(value, monkeypatch, before_response=before_response)
    before = value.ledger.get_attempt(value.permit.attempt_id)
    ref = value.coordinator.capture_response(value.permit, response)
    content = value.domain.get(ref).body["content"]
    assert value.domain.read_blob(BlobRef.from_dict(content["payload_blob"]),
                                  purpose="operational") == PAYLOAD
    entries = value.ledger.attempt_journal(value.permit.attempt_id)
    captured = [entry for entry in entries if entry["transition"] == "response_captured"]
    assert captured[0]["payload"]["classification"] == "quarantined"
    assert not [entry for entry in entries if entry["transition"] == "transport_observed"]
    after = value.ledger.get_attempt(value.permit.attempt_id)
    assert after["phase"] == before["phase"]
    assert after["terminal_outcome"] == before["terminal_outcome"]
    assert after["dispatch_gate"] == "closed"
    assert after["accepted_observation_id"] is None


@pytest.mark.parametrize("damage", ("blob_missing", "blob_corrupt", "record_missing", "journal_missing"))
def test_restart_capture_corruption_inhibits_with_sanitized_gap(tmp_path, monkeypatch, damage):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    ref = value.coordinator.capture_response(value.permit, response)
    blob = BlobRef.from_dict(value.domain.get(ref).body["content"]["payload_blob"])
    if damage.startswith("blob_"):
        with value.domain._blob_directory("operational") as directory:
            import os
            if damage == "blob_missing":
                os.unlink(blob.sha256, dir_fd=directory)
            else:
                descriptor = os.open(blob.sha256, os.O_WRONLY, dir_fd=directory)
                try:
                    os.write(descriptor, b"!")
                finally:
                    os.close(descriptor)
    else:
        # Deliberate offline corruption; production schema/trigger checks stay enabled.
        with value.ledger._transaction(write=True) as db:
            if damage == "record_missing":
                db.execute("DELETE FROM permission_descriptors WHERE kind='worker_response_capture'")
                db.execute("DELETE FROM domain_record_blobs WHERE source_kind='worker_response_capture'")
                db.execute("DELETE FROM domain_edges WHERE source_kind='worker_response_capture'")
                db.execute("DELETE FROM domain_records WHERE kind='worker_response_capture'")
            else:
                db.execute("DELETE FROM runtime_attempt_journal WHERE transition='response_captured'")
    reopened = RuntimeLedger(DomainStore(value.legacy), clock_ms=lambda: 1000)
    with pytest.raises(WorkerResponseCaptureGap, match="integrity gap"):
        reopened.reconcile_startup(str(uuid4()), observed_owners={})
    assert reopened.is_dispatch_emergency_inhibited
    with reopened._transaction() as db:
        event = db.execute("SELECT payload FROM runtime_public_events WHERE event_type='record.gap'").fetchone()
        assert event[0] == b'{"reason_code":"corrupt"}'


def test_ordered_distinct_descriptors_can_own_equal_exact_bytes(tmp_path, monkeypatch):
    value = build_subject(tmp_path)
    spec = replace(value.route.channel_spec, requester_message_types=("artifact-stream", "execute"),
                   responder_message_types=("artifact-stream", "completed", "failed"))
    value.route = replace(value.route, channel_spec=spec, artifact_stream_message_type="artifact-stream")
    value.coordinator._route = value.route
    data = b"same exact artifact bytes"
    batch = str(uuid4())
    outputs = tuple((ArtifactDescriptor(batch, value.permit.command_id, index, 2, media,
                                         len(data), sha256(data).hexdigest()), data)
                    for index, media in enumerate(("text/plain", "application/octet-stream")))
    policy = OfferedBatchPolicy(value.permit.command_id, ("text/plain", "application/octet-stream"))
    thread, failures = wire(value, monkeypatch, outputs=outputs)
    dispatch(value, policy=policy)
    thread.join(5)
    assert failures == []
    ref = _lookup_response_capture(value.ledger, value.permit.command_id)
    content = value.domain.get(ref).body["content"]
    assert [item["descriptor"]["ordinal"] for item in content["artifacts"]] == [0, 1]
    assert content["artifacts"][0]["blob"] == content["artifacts"][1]["blob"]
    replay = _load_response_bytes(value.ledger, value.gate, value.runtime, value.permit.command_id,
                                  purpose="operational", grants=grants_for(value, ref))
    assert [item.descriptor.media_type for item in replay.artifacts] == ["text/plain", "application/octet-stream"]
    assert [item.payload for item in replay.artifacts] == [data, data]
    changed = value.domain.get(ref).body
    changed["content"]["artifacts"].reverse()
    from app.domain.refs import canonical_json
    with pytest.raises(DomainContractError):
        ImmutableRecord.from_bytes(canonical_json(changed))


def test_caller_transaction_rollback_never_publishes_record_or_descriptor(tmp_path):
    value = build_subject(tmp_path)
    roots = value.domain.roots()
    record = ImmutableRecord.create(
        kind="source", id=str(uuid4()), version=1, created_at_utc="2026-09-15T00:00:00.000000Z",
        actor_ref=roots.actor, parent_refs=(), purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content={"sensitive": "declared by host"},
    )
    with pytest.raises(RuntimeError, match="rollback"), value.ledger._transaction(write=True) as db:
        value.domain._put_in_transaction(db, record)
        value.host._register_record_in_transaction(db, record, secret=True)
        assert record.ref not in value.host._resources
        raise RuntimeError("rollback")
    value.host._sync_persistent()
    assert record.ref not in value.host._resources
    with pytest.raises(StorageError):
        value.domain.get(record.ref)


def test_caller_transaction_rejects_foreign_and_inactive_connections(tmp_path):
    value = build_subject(tmp_path)
    other = build_subject(tmp_path / "other")
    with other.ledger._transaction(write=True) as db, pytest.raises(StorageError):
        value.domain._put_in_transaction(db, value.records.envelope)
    db = sqlite3.connect(value.domain.path)
    try:
        with pytest.raises(StorageError):
            value.domain._put_in_transaction(db, value.records.envelope)
    finally:
        db.close()


@pytest.mark.parametrize("table,operation", (
    ("domain_records", sqlite3.SQLITE_INSERT),
    ("permission_descriptors", sqlite3.SQLITE_INSERT),
    ("runtime_attempt_journal", sqlite3.SQLITE_INSERT),
    ("runtime_public_events", sqlite3.SQLITE_INSERT),
    ("runtime_attempts", sqlite3.SQLITE_UPDATE),
))
def test_real_sqlite_failure_rolls_back_entire_capture(tmp_path, monkeypatch, table, operation):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    before = value.ledger.get_attempt(value.permit.attempt_id)
    original = value.domain._put_in_transaction
    denials = []

    def put(db, record):
        # Install a real SQLite authorizer on the already admitted capture writer.
        # No schema/trigger admission checks are disabled.
        def authorizer(action, first, second, database, source):
            if action == operation and first == table:
                denials.append((first, action))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorizer)
        return original(db, record)

    monkeypatch.setattr(value.domain, "_put_in_transaction", put)
    with pytest.raises(WorkerCoordinatorError):
        value.coordinator.capture_response(value.permit, response)
    assert denials
    assert value.ledger.is_dispatch_emergency_inhibited
    assert value.ledger.get_attempt(value.permit.attempt_id) == before
    with value.ledger._transaction() as db:
        for query in (
            "SELECT count(*) FROM domain_records WHERE kind='worker_response_capture'",
            "SELECT count(*) FROM permission_descriptors WHERE kind='worker_response_capture'",
            "SELECT count(*) FROM runtime_attempt_journal WHERE transition='response_captured'",
            "SELECT count(*) FROM runtime_public_events WHERE event_type='attempt.response_captured'",
            "SELECT count(*) FROM runtime_attempt_journal WHERE transition='transport_observed'",
        ):
            assert db.execute(query).fetchone()[0] == 0
        assert db.execute("SELECT state FROM runtime_budget_reservations").fetchone()[0] == "dispatched"
    value.host._sync_persistent()
    assert all(ref.kind != "worker_response_capture" for ref in value.host._resources)
    assert value.coordinator._active_responses == {}
    reopened = RuntimeLedger(DomainStore(value.legacy), clock_ms=lambda: 1000)
    result = reopened.reconcile_startup(str(uuid4()), observed_owners={})
    assert result["unknown_count"] == 1


@pytest.mark.parametrize("noop", ("observation", "event", "state"))
def test_silent_capture_stage_loss_is_detected_before_commit(tmp_path, monkeypatch, noop):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    if noop == "observation":
        monkeypatch.setattr(value.ledger, "_record_transport_observation_in_transaction",
                            lambda *args, **kwargs: None)
    elif noop == "event":
        monkeypatch.setattr(value.ledger, "_event", lambda *args, **kwargs: None)
    else:
        original = value.ledger._record_transport_observation_in_transaction

        def missing_state(db, permit, observation):
            original(db, permit, observation)
            db.execute("UPDATE runtime_attempts SET phase='send_intent',send_finality='may_have_started' "
                       "WHERE id=?", (permit.attempt_id,))
        monkeypatch.setattr(value.ledger, "_record_transport_observation_in_transaction", missing_state)
    with pytest.raises(WorkerCoordinatorError):
        value.coordinator.capture_response(value.permit, response)
    assert _lookup_response_capture(value.ledger, value.permit.command_id) is None


def test_revocation_during_blob_read_does_not_release_bytes(tmp_path, monkeypatch):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    ref = value.coordinator.capture_response(value.permit, response)
    grants = grants_for(value, ref)
    original = value.domain.read_blob

    def revoke_after_read(*args, **kwargs):
        data = original(*args, **kwargs)
        value.host.revoke(grants[0])
        return data

    monkeypatch.setattr(value.domain, "read_blob", revoke_after_read)
    with pytest.raises(AccessDenied):
        _load_response_bytes(value.ledger, value.gate, value.runtime, value.permit.command_id,
                             purpose="operational", grants=grants)


def crash_child(directory, stage):
    """Owned subprocess fixture: terminate only ourselves at a real DB boundary."""
    import os

    from pytest import MonkeyPatch

    with MonkeyPatch.context() as patch:
        value = build_subject(Path(directory))
        response = exchange(value, patch)
        original = value.ledger._transaction

        @contextmanager
        def transaction(*, write=False):
            captured = False
            with original(write=write) as db:
                yield db
                captured = bool(db.execute("SELECT count(*) FROM runtime_attempt_journal "
                                           "WHERE transition='response_captured'").fetchone()[0])
                if write and captured and stage == "precommit":
                    os._exit(71)
            if write and captured and stage == "postcommit":
                os._exit(72)

        value.ledger._transaction = transaction
        value.coordinator.capture_response(value.permit, response)
    raise AssertionError("crash boundary was not reached")


@pytest.mark.parametrize("stage,code,captures,unknown", (("precommit", 71, 0, 1),
                                                        ("postcommit", 72, 1, 0)))
def test_owned_process_exit_and_reopen(tmp_path, stage, code, captures, unknown):
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         ("from app.tests.test_worker_response_capture import crash_child; "
          "import sys; crash_child(sys.argv[1], sys.argv[2])"), str(tmp_path), stage],
        capture_output=True, timeout=20, check=False,
    )
    assert result.returncode == code, result.stderr.decode()
    from app.storage import Store
    domain = DomainStore(Store(tmp_path / "vault"))
    ledger = RuntimeLedger(domain, clock_ms=lambda: 1000)
    with ledger._transaction() as db:
        attempt = db.execute("SELECT id,phase FROM runtime_attempts").fetchone()
        for query in (
            "SELECT count(*) FROM domain_records WHERE kind='worker_response_capture'",
            "SELECT count(*) FROM permission_descriptors WHERE kind='worker_response_capture'",
            "SELECT count(*) FROM runtime_attempt_journal WHERE transition='response_captured'",
            "SELECT count(*) FROM runtime_public_events WHERE event_type='attempt.response_captured'",
        ):
            assert db.execute(query).fetchone()[0] == captures
        assert attempt["phase"] == ("running" if captures else "send_intent")
        assert db.execute("SELECT state FROM runtime_budget_reservations").fetchone()[0] == "dispatched"
    reopened = ledger.reconcile_startup(str(uuid4()), observed_owners={})
    assert reopened["unknown_count"] == unknown
    assert reopened["redispatched_count"] == 0
    assert ledger.get_attempt(attempt["id"])["dispatch_gate"] == "closed"


def test_opaque_response_capture_inherits_source_taint(tmp_path, monkeypatch):
    value = build_subject(tmp_path, profile_content={"secret": "private-source"})
    response = exchange(value, monkeypatch)
    ref = value.coordinator.capture_response(value.permit, response)
    value.host._sync_persistent()
    assert value.host._resources[ref].tainted
    with pytest.raises(AccessDenied):
        grants_for(value, ref)


def test_caller_registration_inherits_taint_and_does_not_grant(tmp_path):
    value = build_subject(tmp_path)
    source = immutable(value.domain, value.domain.roots(), "source", content={"secret": "private"})
    value.host.register_record(source)
    roots = value.domain.roots()
    record = ImmutableRecord.create(
        kind="source", id=str(uuid4()), version=1, created_at_utc="2026-09-15T00:00:00.000000Z",
        actor_ref=roots.actor, parent_refs=(source.ref,), purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy, content={},
    )
    with value.ledger._transaction(write=True) as db:
        value.domain._put_in_transaction(db, record)
        descriptor = value.host._register_record_in_transaction(db, record)
        assert descriptor.tainted
        assert record.ref not in value.host._resources
    value.host._sync_persistent()
    assert value.host._resources[record.ref].tainted
    with pytest.raises(AccessDenied):
        value.gate.read(value.runtime, record.ref, purpose="operational", grants=(value.grant,),
                        loader=lambda ref: value.domain.get(ref))


def test_capture_schema_and_runtime_reject_new_fields_and_wrong_version(tmp_path, monkeypatch):
    import json

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from app.domain.refs import canonical_json
    from app.domain.schema_exports import domain_schema
    from app.domain.worker_response import capture_schema

    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    ref = value.coordinator.capture_response(value.permit, response)
    record = value.domain.get(ref)
    domain = domain_schema()
    schema = capture_schema()
    registry = Registry().with_resource(domain["$id"], Resource.from_contents(domain))
    content_validator = Draft202012Validator(schema, registry=registry)
    content_validator.validate(record.body["content"])
    root = Path(__file__).resolve().parents[2] / "schemas" / "v1"
    assert schema == json.loads((root / "worker-response-capture.schema.json").read_text())
    validator = Draft202012Validator(domain, registry=registry)
    for change in ("extra", "bool_fence", "long_service", "version"):
        body = record.body
        if change == "extra":
            body["content"]["raw_payload"] = "private"
        elif change == "bool_fence":
            body["content"]["lease_fence"] = True
        elif change == "long_service":
            body["content"]["responder_service"] = "a" * 65
        else:
            body["version"] = 2
        with pytest.raises(DomainContractError):
            ImmutableRecord.from_bytes(canonical_json(body))
        candidate = {"ref": ref.as_dict(), "body": body}
        assert list(validator.iter_errors(candidate)), change


def test_authentic_stream_above_default_blob_cap_cannot_attach(tmp_path, monkeypatch):
    value = build_subject(tmp_path, lease_duration_ms=9000)
    spec = replace(value.route.channel_spec, requester_message_types=("artifact-stream", "execute"),
                   responder_message_types=("artifact-stream", "completed", "failed"))
    value.route = replace(value.route, channel_spec=spec, artifact_stream_message_type="artifact-stream")
    value.coordinator._route = value.route
    data = b"x" * (16 * 1024 * 1024 + 1)
    descriptor = ArtifactDescriptor(str(uuid4()), value.permit.command_id, 0, 1,
                                    "application/octet-stream", len(data), sha256(data).hexdigest())
    policy = OfferedBatchPolicy(value.permit.command_id, ("application/octet-stream",))
    thread, failures = wire(value, monkeypatch, outputs=((descriptor, data),))
    response = value.coordinator.exchange(value.permit, value.capability,
                                         deadline=broker.Deadline.after_ms(5000),
                                         artifact_output_policy=policy)
    thread.join(5)
    assert failures == []
    with pytest.raises(WorkerCoordinatorError):
        value.coordinator.capture_response(value.permit, response)
    assert _lookup_response_capture(value.ledger, value.permit.command_id) is None
    assert value.ledger.is_dispatch_emergency_inhibited


def test_changed_duplicate_rejected_without_events_or_replacement(tmp_path, monkeypatch):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    ref = value.coordinator.capture_response(value.permit, response)
    before = value.ledger.attempt_journal(value.permit.attempt_id)
    object.__setattr__(response, "payload", b"changed duplicate")
    with pytest.raises(WorkerCoordinatorError):
        value.coordinator.capture_response(value.permit, response)
    assert value.ledger.attempt_journal(value.permit.attempt_id) == before
    assert _lookup_response_capture(value.ledger, value.permit.command_id) == ref


def test_deadline_expiring_during_registration_quarantines(tmp_path, monkeypatch):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    original = value.host._register_record_in_transaction

    def register(*args, **kwargs):
        result = original(*args, **kwargs)
        value.ledger._clock = lambda: 10000
        return result

    monkeypatch.setattr(value.host, "_register_record_in_transaction", register)
    value.coordinator.capture_response(value.permit, response)
    entries = value.ledger.attempt_journal(value.permit.attempt_id)
    assert [entry["payload"]["classification"] for entry in entries
            if entry["transition"] == "response_captured"] == ["quarantined"]
    assert value.ledger.get_attempt(value.permit.attempt_id)["dispatch_gate"] == "closed"


def test_capture_reachable_blob_limit_is_enforced_transactionally(tmp_path, monkeypatch):
    from app.domain import store as store_module

    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    # Scaled limit exercises the same aggregate traversal; production 64 MiB
    # ceiling is untouched. The real 16 MiB per-blob boundary is tested above.
    monkeypatch.setattr(store_module, "MAX_GRAPH_BLOB_BYTES", len(PAYLOAD) - 1)
    with pytest.raises(WorkerCoordinatorError):
        value.coordinator.capture_response(value.permit, response)
    with value.ledger._transaction() as db:
        assert db.execute("SELECT count(*) FROM domain_records "
                          "WHERE kind='worker_response_capture'").fetchone()[0] == 0


def test_read_rejects_revoked_human_session(tmp_path, monkeypatch):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    ref = value.coordinator.capture_response(value.permit, response)
    human_grants = tuple(value.host.grant(value.human, value.human, resource,
                                          action="read", purpose="operational", expires_at=1300)
                         for resource in (ref, value.records.envelope.ref, value.records.profile.ref))
    monkeypatch.setattr(value.host, "_authenticate_session", lambda session: None)
    with pytest.raises(AccessDenied):
        _load_response_bytes(value.ledger, value.gate, value.human, value.permit.command_id,
                             purpose="operational", grants=human_grants)


def test_public_events_status_and_response_repr_have_no_raw_bytes(tmp_path, monkeypatch):
    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    value.coordinator.capture_response(value.permit, response)
    with value.ledger._transaction() as db:
        events = list(db.execute("SELECT event_type,payload FROM runtime_public_events"))
    for item in (repr(response), repr(value.ledger.dispatch_status(value.permit.command_id)),
                 repr([tuple(row) for row in events])):
        assert "result" not in item
        assert "payload_blob" not in item
        assert str(value.route.channel_spec.pair_root) not in item
    capture = [row[1] for row in events if row[0] == "attempt.response_captured"]
    assert capture == [b'{"artifact_count":0,"classification":"pending_validation"}']


def test_failed_postcommit_return_reconciles_exact_ref_without_resend(tmp_path, monkeypatch):
    from app.runtime import worker_response_capture as capture_module

    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    original = capture_module._capture_authenticated

    def lost_return(*args):
        original(*args)
        raise OSError("untrusted-private-payload")

    monkeypatch.setattr(capture_module, "_capture_authenticated", lost_return)
    with pytest.raises(WorkerCoordinatorError) as error:
        value.coordinator.capture_response(value.permit, response)
    assert str(error.value) == "worker_dispatch_rejected"
    assert value.ledger.is_dispatch_emergency_inhibited
    assert value.coordinator._active_responses == {}
    monkeypatch.setattr(capture_module, "_capture_authenticated", original)
    ref = value.coordinator.capture_response(value.permit, response)
    assert _lookup_response_capture(value.ledger, value.permit.command_id) == ref
    assert len([entry for entry in value.ledger.attempt_journal(value.permit.attempt_id)
                if entry["transition"] == "response_captured"]) == 1


def test_prior_transport_fact_survives_quarantined_late_capture(tmp_path, monkeypatch):
    from app.runtime.ledger import TransportObservation

    value = build_subject(tmp_path)
    response = exchange(value, monkeypatch)
    earlier = TransportObservation(value.permit.permit_id, value.permit.command_id,
        value.permit.attempt_id, "transport_accepted", response.connection_id,
        response.worker_boot_id, response.message_id, response.message_type,
        len(response.payload), sha256(response.payload).hexdigest())
    value.ledger.record_transport_observation(value.permit, earlier)
    value.ledger.request_cancel(str(uuid4()), value.permit.attempt_id, expected_revision=3)
    value.coordinator.capture_response(value.permit, response)
    entries = value.ledger.attempt_journal(value.permit.attempt_id)
    assert [entry["payload"] for entry in entries if entry["transition"] == "transport_observed"] == [earlier.as_dict()]
    assert [entry["payload"]["classification"] for entry in entries
            if entry["transition"] == "response_captured"] == ["quarantined"]
    status = value.ledger.dispatch_status(value.permit.command_id)
    assert status["state"] == "outcome_unknown"
    assert status["attempt"]["cancel_state"] == "requested"
    assert status["attempt"]["dispatch_gate"] == "closed"


@pytest.mark.parametrize("damage", ("ordinal", "count_type", "foreign_request"))
def test_real_authenticated_malformed_offer_never_mints_capture(tmp_path, monkeypatch, damage):
    value = build_subject(tmp_path)
    spec = replace(value.route.channel_spec, requester_message_types=("artifact-stream", "execute"),
                   responder_message_types=("artifact-stream", "completed", "failed"))
    value.route = replace(value.route, channel_spec=spec, artifact_stream_message_type="artifact-stream")
    value.coordinator._route = value.route
    descriptor = ArtifactDescriptor(str(uuid4()), value.permit.command_id, 0, 2,
                                    "text/plain", 0, sha256(b"").hexdigest())
    offer = {"type": "artifact-offer", **descriptor.as_offer_fields()}
    if damage == "ordinal":
        offer["ordinal"] = 1
    elif damage == "count_type":
        offer["count"] = True
    else:
        offer["request_id"] = str(uuid4())
    policy = OfferedBatchPolicy(value.permit.command_id, ("text/plain",))
    thread, failures = wire(value, monkeypatch, invalid_offer=offer)
    dispatch(value, policy=policy)
    thread.join(5)
    assert failures == []
    assert _lookup_response_capture(value.ledger, value.permit.command_id) is None
    assert value.coordinator._active_responses == {}
    assert value.ledger.dispatch_status(value.permit.command_id)["state"] == "outcome_unknown"


def test_capture_uses_host_root_actor_for_human_authored_envelope(tmp_path, monkeypatch):
    value = build_subject(tmp_path, human_authored=True)
    response = exchange(value, monkeypatch)
    ref = value.coordinator.capture_response(value.permit, response)
    body = value.domain.get(ref).body
    source = value.records.envelope.body
    assert body["actor_ref"] == value.domain.roots().actor.as_dict()
    assert body["actor_ref"] != source["actor_ref"]
    assert body["parent_refs"] == [value.records.envelope.ref.as_dict()]
    for name in ("purpose", "access_policy_ref", "retention_policy_ref"):
        assert body[name] == source[name]


@pytest.mark.parametrize("suffix", ("\n", "\r", "\r\n", "\u2028", "\u2029"))
@pytest.mark.parametrize("field", (
    "channel_id", "message_type", "requester_boot_id", "worker_boot_id",
    "requester_service", "responder_service", "batch_id", "request_id", "media_type",
))
def test_capture_schema_runtime_reject_terminal_line_separators(field, suffix):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from app.domain.schema_exports import domain_schema
    from app.domain.worker_response import capture_schema, validate_capture_content

    identity = "10000000-0000-4000-8000-000000000001"
    other_identity = "10000000-0000-4000-8000-000000000002"
    blob = {"vault_id": identity, "purpose": "operational", "sha256": "a" * 64, "size": 0}
    content = {
        "capture_schema_version": "worker-response-capture-v1",
        "command_id": identity, "attempt_id": other_identity, "permit_id": identity,
        "execution_envelope_ref": {"kind": "execution_envelope", "id": identity,
                                   "version": 1, "sha256": "b" * 64},
        "runtime_profile_ref": {"kind": "runtime_profile", "id": identity,
                                "version": 1, "sha256": "c" * 64},
        "lease_fence": 1, "connection_id": "d" * 64,
        "requester_boot_id": "control-1", "worker_boot_id": "document-1",
        "channel_id": "control-document", "requester_service": "control",
        "responder_service": "document", "message_id": other_identity,
        "correlation_id": identity, "message_type": "completed", "payload_blob": blob,
        "artifacts": [{"descriptor": {"batch_id": other_identity, "request_id": identity,
                                       "ordinal": 0, "count": 1, "media_type": "text/plain",
                                       "declared_size": 0, "sha256": "a" * 64}, "blob": blob}],
    }
    domain = domain_schema()
    registry = Registry().with_resource(domain["$id"], Resource.from_contents(domain))
    validator = Draft202012Validator(capture_schema(), registry=registry)
    body_validator = Draft202012Validator(
        {"$ref": domain["$id"] + "#/$defs/DomainBody"}, registry=registry)
    validate_capture_content(content)
    validator.validate(content)
    record_body = {
        "schema_version": "domain-v1", "kind": "worker_response_capture", "id": identity,
        "version": 1, "created_at_utc": "2026-09-15T00:00:00.000000Z",
        "actor_ref": {"kind": "actor", "id": identity, "version": 1, "sha256": "a" * 64},
        "parent_refs": [], "purpose": "operational",
        "access_policy_ref": {"kind": "access_policy", "id": identity,
                              "version": 1, "sha256": "a" * 64},
        "retention_policy_ref": {"kind": "retention_policy", "id": identity,
                                 "version": 1, "sha256": "a" * 64},
        "content": content,
    }
    body_validator.validate(record_body)
    target = content["artifacts"][0]["descriptor"] if field in {
        "batch_id", "request_id", "media_type"} else content
    target[field] += suffix
    with pytest.raises(DomainContractError):
        validate_capture_content(content)
    assert list(validator.iter_errors(content)), "capture schema accepted a terminal separator"
    assert list(body_validator.iter_errors(record_body)), "domain schema accepted a terminal separator"
