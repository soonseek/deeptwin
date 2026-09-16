"""Private durable transport evidence. No semantic success, model input, or settlement.

Physical blob registration precedes the attachment transaction. Without a worker
ACK/redelivery protocol a receive-before-commit crash remains outcome unknown.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256

from ..domain.permissions import AccessDenied, PolicyGate, _PermissionStore
from ..domain.refs import EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef
from ..domain.worker_response import CAPTURE_VERSION, validate_capture_content
from .ledger import (
    AttemptSpec,
    CommandConflict,
    CorruptLedger,
    OwnerIdentity,
    RevisionConflict,
    TransportObservation,
    _decode_canonical,
)

JOURNAL_VERSION = "worker-response-capture-journal-v1"
MAX_RECOVERY_CAPTURES = 100_000


class WorkerResponseCaptureGap(CorruptLedger):
    """Sanitized durable-capture integrity gap; dispatch must remain inhibited."""


def _response_content(coordinator, permit, response):
    spec = coordinator._route.channel_spec
    purpose = "operational"  # Verified operational envelope is required below.

    def blob(data):
        return BlobRef(coordinator._ledger.vault_id, purpose,
                       sha256(data).hexdigest(), len(data)).as_dict()

    return {
        "capture_schema_version": CAPTURE_VERSION,
        "command_id": permit.command_id, "attempt_id": permit.attempt_id,
        "permit_id": permit.permit_id, "execution_envelope_ref": permit.envelope_ref.as_dict(),
        "runtime_profile_ref": permit.profile_ref.as_dict(), "lease_fence": permit.lease_fence,
        "connection_id": response.connection_id,
        "requester_boot_id": coordinator._requester_boot_id,
        "worker_boot_id": response.worker_boot_id, "channel_id": spec.channel_id,
        "requester_service": spec.requester_service, "responder_service": spec.responder_service,
        "message_id": response.message_id, "correlation_id": response.correlation_id,
        "message_type": response.message_type, "payload_blob": blob(response.payload),
        "artifacts": [{"descriptor": item.descriptor.as_offer_fields(), "blob": blob(item.payload)}
                      for item in response.artifacts],
    }


def _response_fingerprint(coordinator, permit, response):
    content = _response_content(coordinator, permit, response)
    validate_capture_content(content)
    if (response.attempt_id != permit.attempt_id
            or response.worker_boot_id != coordinator._worker_boot_id
            or response.message_type not in coordinator._route.response_message_types):
        raise CorruptLedger("Worker response binding changed")
    return sha256(canonical_json({
        "content": content, "owner": permit.owner.as_dict(),
        "execution_id": permit.execution_id, "reservation_id": permit.reservation_id,
        "budget_policy_ref": permit.budget_policy_ref.as_dict(),
        "budget_session_id": permit.budget_session_id, "principal_id": permit.principal_id,
        "grant_id": permit.grant_id, "idempotency_key": permit.idempotency_key,
        "deadline": permit.deadline_at_ms, "lease_expiry": permit.lease_expires_at_ms,
        "issued_at": permit.issued_at_ms, "budget_deadline": permit.budget_deadline_epoch_seconds,
    })).hexdigest()


def _original_binding(ledger, db, content):
    """Validate the original durable intent, not a subsequently changed live lease."""
    command = db.execute("SELECT * FROM runtime_commands WHERE vault_id=? AND command_id=?",
                         (ledger.vault_id, content["command_id"])).fetchone()
    if command is None or command["kind"] != "commit_budgeted_send_intent":
        raise CorruptLedger("Worker response capture command is absent")
    payload = _decode_canonical(command["payload"], command["payload_digest"], "capture command")
    result = _decode_canonical(command["result"], command["result_digest"], "capture command result")
    fields = {"attempt_id", "owner", "expected_revision", "budget_request", "principal_id", "grant_id"}
    if (type(payload) is not dict or set(payload) != fields or type(result) is not dict
            or set(result) != {"intent_committed", "attempt_id", "permit_id", "revision"}
            or result["intent_committed"] is not True
            or payload["attempt_id"] != content["attempt_id"]
            or result["attempt_id"] != content["attempt_id"]
            or result["permit_id"] != content["permit_id"]):
        raise CorruptLedger("Worker response capture command binding changed")
    row = ledger._load_attempt(db, content["attempt_id"])
    spec = AttemptSpec.from_dict(_decode_canonical(row["spec"], row["spec_digest"], "capture attempt"))
    request = payload["budget_request"]
    run = ledger._run_spec_for_attempt(db, spec)
    if (content["execution_envelope_ref"] != spec.envelope_ref.as_dict()
            or content["runtime_profile_ref"] != spec.profile_ref.as_dict()
            or OwnerIdentity.from_dict(payload["owner"]) != spec.owner
            or type(request) is not dict or request.get("request_id") != spec.reservation_id
            or request.get("policy_ref") != spec.budget_policy_ref.as_dict()
            or request.get("session_id") != run.budget_session_id):
        raise CorruptLedger("Worker response capture attempt binding changed")
    entries = list(db.execute("SELECT * FROM runtime_attempt_journal WHERE vault_id=? "
                              "AND attempt_id=? AND transition='send_intent'",
                              (ledger.vault_id, spec.attempt_id)))
    if len(entries) != 1:
        raise CorruptLedger("Worker response original intent is unavailable")
    intent = _decode_canonical(entries[0]["payload"], entries[0]["payload_digest"], "capture intent")
    if (intent != {"lease_fence": content["lease_fence"], "revision": result["revision"]}
            or type(result["revision"]) is not int
            or result["revision"] != payload["expected_revision"] + 1
            or entries[0]["at_ms"] != command["created_at_ms"]
            or row["send_intent_at_ms"] != command["created_at_ms"]):
        raise CorruptLedger("Worker response original fence is inconsistent")
    return row, spec


def _resources(ledger, db):
    storage = _PermissionStore(ledger._domain, _db=db)
    roots = ledger._domain._read_roots(db)

    def resolve(ref):
        ledger._domain._check_graph(db, [ref], roots)
        return ledger._domain._load(db, ref, roots)[0]

    return storage.load(db, resolve)[1]


def _source(ledger, db, content, resources):
    roots = ledger._domain._read_roots(db)
    ref = EntityRef.from_dict(content["execution_envelope_ref"])
    ledger._domain._check_graph(db, [ref], roots)
    envelope = ledger._domain._load(db, ref, roots)[0]
    descriptor = resources.get(ref)
    if (descriptor is None or descriptor.record != envelope
            or envelope.body["purpose"] != "operational"
            or descriptor.purpose != envelope.body["purpose"]):
        raise CorruptLedger("Worker response source policy is unavailable")
    return roots, envelope, descriptor


def _validate_entry(ledger, db, entry, resources):
    value = _decode_canonical(entry["payload"], entry["payload_digest"], "response capture journal")
    if (type(value) is not dict
            or set(value) != {"schema_version", "command_id", "capture_ref", "classification"}
            or value["schema_version"] != JOURNAL_VERSION
            or value["classification"] not in {"pending_validation", "quarantined"}):
        raise CorruptLedger("Worker response capture journal is invalid")
    ref = EntityRef.from_dict(value["capture_ref"])
    if ref.kind != "worker_response_capture":
        raise CorruptLedger("Worker response capture reference kind changed")
    roots = ledger._domain._read_roots(db)
    ledger._domain._check_graph(db, [ref], roots)
    record = ledger._domain._load(db, ref, roots)[0]
    content = record.body["content"]
    _original_binding(ledger, db, content)
    _, envelope, source = _source(ledger, db, content, resources)
    descriptor = resources.get(ref)
    body = record.body
    if (content["command_id"] != value["command_id"]
            or content["attempt_id"] != entry["attempt_id"]
            or ref.id != content["command_id"] or ref.version != 1
            or body["actor_ref"] != roots.actor.as_dict()
            or body["parent_refs"] != [envelope.ref.as_dict()]
            or any(body[key] != envelope.body[key] for key in
                   ("purpose", "access_policy_ref", "retention_policy_ref"))
            or descriptor is None or descriptor.record != record
            or descriptor.episode_id != source.episode_id
            or content["payload_blob"]["purpose"] != body["purpose"]
            or (source.tainted and not descriptor.tainted)):
        raise CorruptLedger("Worker response capture policy binding changed")
    if value["classification"] == "pending_validation":
        observations = list(db.execute("SELECT * FROM runtime_attempt_journal WHERE vault_id=? "
            "AND attempt_id=? AND transition='transport_observed'", (ledger.vault_id, entry["attempt_id"])))
        if len(observations) != 1 or _decode_canonical(
                observations[0]["payload"], observations[0]["payload_digest"], "capture transport"
                ) != _transport_for_content(content).as_dict():
            raise CorruptLedger("Worker response capture transport gap")
    return record, value["classification"]


def _transport_for_content(content):
    blob = content["payload_blob"]
    return TransportObservation(
        content["permit_id"], content["command_id"], content["attempt_id"], "transport_accepted",
        content["connection_id"], content["worker_boot_id"], content["message_id"],
        content["message_type"], blob["size"], blob["sha256"])


def _entries(ledger, db, attempt_id):
    rows = list(db.execute("SELECT * FROM runtime_attempt_journal WHERE vault_id=? "
                           "AND attempt_id=? AND transition='response_captured'",
                           (ledger.vault_id, attempt_id)))
    if len(rows) > 1:
        raise CorruptLedger("Worker response capture is duplicated")
    return rows


def _validated_captures(ledger, db):
    """Validate all persisted capture attachments before startup opens dispatch."""
    try:
        return _validate_all_captures(ledger, db)
    except Exception:  # noqa: BLE001 - corrupt capture data must produce one sanitized gap
        raise WorkerResponseCaptureGap("Worker response capture integrity gap") from None


def _validate_all_captures(ledger, db):
    rows = db.execute("SELECT * FROM runtime_attempt_journal WHERE vault_id=? "
                      "AND transition='response_captured' ORDER BY sequence LIMIT ?",
                      (ledger.vault_id, MAX_RECOVERY_CAPTURES + 1)).fetchall()
    if len(rows) > MAX_RECOVERY_CAPTURES:
        raise CorruptLedger("Worker response capture recovery bound exceeded")
    count = db.execute("SELECT count(*) FROM domain_records WHERE vault_id=? "
                       "AND kind='worker_response_capture'", (ledger.vault_id,)).fetchone()[0]
    if count != len(rows):
        raise CorruptLedger("Worker response capture attachment gap")
    if not rows:
        return {}
    resources = _resources(ledger, db)
    result, commands = {}, set()
    for row in rows:
        record, classification = _validate_entry(ledger, db, row, resources)
        command = record.body["content"]["command_id"]
        if row["attempt_id"] in result or command in commands:
            raise CorruptLedger("Worker response capture is duplicated")
        commands.add(command)
        result[row["attempt_id"]] = classification
    return result


def _capture_authenticated(coordinator, permit, response, receipt):
    ledger, domain = coordinator._ledger, coordinator._domain
    if coordinator._checked_response_receipt(permit, response) is not receipt:
        raise CorruptLedger("Worker response receipt changed")
    content = _response_content(coordinator, permit, response)
    # Reject absent/foreign identities before any attachment or blob registration.
    with ledger._transaction(write=True) as db:
        ledger._require_session(db)
        ledger._transport_command_binding(db, permit)
        _original_binding(ledger, db, content)
        resources = _resources(ledger, db)
        _, envelope, source = _source(ledger, db, content, resources)
        existing = _entries(ledger, db, permit.attempt_id)
        if existing:
            record, _ = _validate_entry(ledger, db, existing[0], resources)
            if record.body["content"] != content:
                raise CommandConflict("Worker response capture changed after commit")
            return record.ref
        if receipt.captured_ref is not None:
            raise CorruptLedger("Committed worker response capture is missing")
    purpose = envelope.body["purpose"]
    domain.put_blob(response.payload, purpose=purpose)
    for artifact in response.artifacts:
        domain.put_blob(artifact.payload, purpose=purpose)
    with ledger._transaction(write=True) as db:
        ledger._require_session(db)
        ledger._transport_command_binding(db, permit)
        row, spec = _original_binding(ledger, db, content)
        resources = _resources(ledger, db)
        roots, envelope, source = _source(ledger, db, content, resources)
        existing = _entries(ledger, db, permit.attempt_id)
        if existing:
            record, _ = _validate_entry(ledger, db, existing[0], resources)
            if record.body["content"] != content:
                raise CommandConflict("Worker response capture changed after commit")
            return record.ref
        coordinator._checked_response_receipt(permit, response)
        now = ledger._now(db)
        record = ImmutableRecord.create(
            kind="worker_response_capture", id=permit.command_id, version=1,
            created_at_utc=datetime.fromtimestamp(now / 1000, UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"),
            actor_ref=roots.actor, parent_refs=(envelope.ref,), purpose=purpose,
            access_policy_ref=EntityRef.from_dict(envelope.body["access_policy_ref"]),
            retention_policy_ref=EntityRef.from_dict(envelope.body["retention_policy_ref"]),
            content=content,
        )
        domain._put_in_transaction(db, record)
        coordinator._permission_gate._host._register_record_in_transaction(
            db, record, episode_id=source.episode_id)
        # Reobserve clocks after content/graph/policy verification while this writer
        # excludes concurrent durable cancellation or lease updates.
        now = ledger._now(db)
        eligible = (
            row["phase"] == "send_intent" and row["send_finality"] == "may_have_started"
            and row["cancel_state"] == "none" and row["recovery_state"] == "clean"
            and row["dispatch_gate"] == "open" and row["lease_fence"] == permit.lease_fence
            and _decode_canonical(row["lease_owner"], row["lease_owner_digest"], "capture owner")
            == permit.owner.as_dict() and now < row["lease_expires_at_ms"]
            and now < spec.deadline_at_ms and receipt.deadline.remaining() > 0
            and not ledger.is_dispatch_emergency_inhibited
        )
        classification = "pending_validation" if eligible else "quarantined"
        ledger._journal(db, permit.attempt_id, "response_captured", {
            "schema_version": JOURNAL_VERSION, "command_id": permit.command_id,
            "capture_ref": record.ref.as_dict(), "classification": classification,
        }, now)
        ledger._event(db, "attempt.response_captured", "attempt", permit.attempt_id,
                      {"classification": classification, "artifact_count": len(response.artifacts)}, now)
        if eligible:
            observation = _transport_for_content(content)
            ledger._record_transport_observation_in_transaction(db, permit, observation)
        elif row["phase"] != "terminal" and row["dispatch_gate"] == "open":
            changed = db.execute("UPDATE runtime_attempts SET dispatch_gate='closed',"
                "recovery_state='pending',dispatch_blocked_at_ms=?,revision=revision+1,updated_at_ms=? "
                "WHERE vault_id=? AND id=? AND revision=?", (now, now, ledger.vault_id,
                                                            permit.attempt_id, row["revision"])).rowcount
            if changed != 1:
                raise RevisionConflict("Capture quarantine lost its state CAS")
        entries = _entries(ledger, db, permit.attempt_id)
        resources = _resources(ledger, db)
        if len(entries) != 1 or _validate_entry(ledger, db, entries[0], resources)[0] != record:
            raise CorruptLedger("Worker response capture commit invariant failed")
        events = list(db.execute("SELECT * FROM runtime_public_events WHERE vault_id=? "
            "AND object_kind='attempt' AND object_id=? AND event_type='attempt.response_captured'",
            (ledger.vault_id, permit.attempt_id)))
        if (len(events) != 1 or _decode_canonical(events[0]["payload"], events[0]["payload_digest"],
                "capture event") != {"classification": classification,
                                     "artifact_count": len(response.artifacts)}):
            raise CorruptLedger("Worker response capture event gap")
        final = ledger._load_attempt(db, permit.attempt_id)
        if eligible and (final["phase"] != "running" or final["dispatch_gate"] != "open"
                         or final["send_finality"] != "transport_accepted"
                         or final["recovery_state"] != "clean" or final["cancel_state"] != "none"):
            raise CorruptLedger("Worker response capture state gap")
        if not eligible and final["dispatch_gate"] != "closed":
            raise CorruptLedger("Worker response quarantine state gap")
    return record.ref


def _lookup_response_capture(ledger, command_id):
    """Private session-bound metadata only; it issues no read authority."""
    uuid_string(command_id)
    with ledger._transaction(write=True) as db:
        ledger._require_session(db)
        command = db.execute("SELECT * FROM runtime_commands WHERE vault_id=? AND command_id=?",
                             (ledger.vault_id, command_id)).fetchone()
        if command is None or command["kind"] != "commit_budgeted_send_intent":
            raise CorruptLedger("Worker response capture command is absent")
        result = _decode_canonical(command["result"], command["result_digest"], "capture lookup")
        entries = _entries(ledger, db, result["attempt_id"])
        if not entries:
            return None
        record, _ = _validate_entry(ledger, db, entries[0], _resources(ledger, db))
        if record.body["content"]["command_id"] != command_id:
            raise CorruptLedger("Worker response lookup binding changed")
        return record.ref


@dataclass(frozen=True, slots=True)
class CapturedWorkerBytes:
    payload: bytes = field(repr=False)
    artifacts: tuple = field(repr=False)


def _load_response_bytes(ledger, gate, principal, command_id, *, purpose, grants, episode_id=None):
    """Load exact bytes only through capture AND transitive dependency read grants."""
    from ..workers.artifact_stream import ArtifactDescriptor
    from .worker_coordinator import ReceivedWorkerArtifact

    if (type(gate) is not PolicyGate or gate._host._storage is None
            or gate._host._storage.domain_store is not ledger._domain):
        raise AccessDenied("Exact capture read authority required")
    ref = _lookup_response_capture(ledger, command_id)
    if ref is None:
        raise AccessDenied("Worker response capture is unavailable")

    def loader(exact_ref):
        if _lookup_response_capture(ledger, command_id) != exact_ref:
            raise AccessDenied("Worker response capture changed")
        content = ledger._domain.get(exact_ref).body["content"]
        payload = ledger._domain.read_blob(BlobRef.from_dict(content["payload_blob"]), purpose=purpose)
        artifacts = tuple(ReceivedWorkerArtifact(
            ArtifactDescriptor(**item["descriptor"]),
            ledger._domain.read_blob(BlobRef.from_dict(item["blob"]), purpose=purpose),
        ) for item in content["artifacts"])
        return CapturedWorkerBytes(payload, artifacts)

    result = gate.read(principal, ref, purpose=purpose, grants=grants,
                       episode_id=episode_id, loader=loader)
    # Gate revalidates grants/session after bytes. Ledger generation is independent.
    if _lookup_response_capture(ledger, command_id) != ref:
        raise AccessDenied("Worker response capture changed")
    return result
