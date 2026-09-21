"""Persistent owner command service for fixed provider conformance."""

import sqlite3
import time
from hashlib import sha256
from uuid import uuid4

from ..deployment.prepare_contracts import DeploymentPrepareError
from ..deployment.prepare_lifecycle import instant
from ..deployment.prepare_service import PersistentDeploymentPrepare
from ..domain.public_events import (
    _append_event_in_transaction,
    _event_cursor_in_transaction,
)
from ..domain.refs import (
    EntityRef,
    ObjectRef,
    canonical_json,
    parse_canonical,
    uuid_string,
)
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, StorageError, _writer
from ..services.owner_auth import OwnerAuthError, PersistentOwnerAuthority
from ..workers.broker import Deadline, DeadlineExceeded
from ..workers.provider_client import _service_timing, compare_capture, run_fixed_suite
from .provider_conformance_contracts import (
    ConformanceComparison,
    ConformanceError,
    ConformanceSubject,
    parse_command,
    parse_reply,
)
from .provider_conformance_records import rehydrate_conformance, verify_history
from .provider_conformance_resolver import (
    require_current_subject,
    require_current_verified_admission,
    resolve_subject,
    resolve_verified_admission,
)
from .provider_conformance_storage import install, verify_layout
from .provider_conformance_vectors import SUITE_SHA256, SUITE_VERSION, fixed_vectors

EVENT_TYPES = ("provider.conformance_completed", "provider.conformance_started")


def _execute(db, statement, arguments=()):
    return db.execute(statement, arguments)


def _map_error(error):
    code = getattr(error, "code", "unavailable")
    if code == "capacity":
        code = "capacity"
    elif code not in {"invalid_input", "unauthenticated", "access_denied", "not_found",
                      "conflict", "too_large", "capacity", "unavailable"}:
        code = "unavailable"
    return ConformanceError(code)


class PersistentProviderConformance:
    def __init__(self, domain_store, owner_authority, *, prepare_service, source_context):
        if (type(domain_store) is not DomainStore or type(owner_authority) is not PersistentOwnerAuthority
                or type(prepare_service) is not PersistentDeploymentPrepare
                or prepare_service._domain is not domain_store
                or prepare_service._owner is not owner_authority
                or source_context is not prepare_service._provider_context):
            raise ConformanceError("unavailable")
        self._domain = domain_store
        self._owner = owner_authority
        self._prepare = prepare_service
        self._source = source_context
        self._requester_boot_id = "provider-conformance-" + uuid4().hex
        with _writer(), self._domain._connection(write=True) as db:
            journal = self._prepare._journal(db)
            verified_empty = journal.get("control") is None and not journal.get("requests")
            install(db, verified_empty=verified_empty)
            verify_history(self._prepare, db)

    def _authenticate(self, request, db, *, read=False):
        if read and getattr(request, "method", None) not in {"GET", "HEAD"}:
            raise ConformanceError("access_denied")
        if not read and getattr(request, "method", None) != "POST":
            raise ConformanceError("access_denied")
        try:
            actor = self._prepare._authenticate(request, db, read=read)
            return actor, self._prepare._actor_ref(db, actor)
        except (OwnerAuthError, DeploymentPrepareError) as exc:
            raise _map_error(exc) from None

    @staticmethod
    def _wall_now(db):
        raw = time.time_ns() // 1_000_000
        control = db.execute("SELECT last_now_ms FROM provider_conformance_control").fetchone()
        if (type(raw) is not int or not 0 <= raw <= 253402300799999
                or control is None or type(control[0]) is not int or raw < control[0]):
            raise ConformanceError("unavailable")
        return raw

    @staticmethod
    def _reply(command_id, installation_ref, intent_ref, result_ref, state, context_sha,
               completed, matched, cursor,admission=None):
        result = {"schema_version": "provider-conformance-reply-v1", "command_id": command_id,
            "installation_ref": installation_ref.as_dict(), "intent_ref": intent_ref.as_dict(),
            "result_ref": None if result_ref is None else result_ref.as_dict(), "state": state,
            "suite_version": SUITE_VERSION, "suite_sha256": SUITE_SHA256,
            "context_sha256": context_sha, "completed_count": completed,
            "matched_count": matched, "event_cursor": cursor,
            "links": {"self": "/api/v1/extensions/provider-conformance/" + command_id,
                      "events": "/api/v1/events"}}
        if admission is not None:
            del result['installation_ref'],result['context_sha256']
            result.update(schema_version='provider-conformance-reply-v2',
                staged_installation_ref=admission.staged_installation_ref.as_dict(),
                verified_installation_ref=admission.verified_installation_ref.as_dict(),
                stage_context_sha256=admission.stage_context_sha256,
                admission_sha256=sha256(canonical_json(admission.as_dict())).hexdigest())
        return result

    def _row_reply(self, row):
        raw = row["terminal_reply"] if row["terminal_reply"] is not None else row["pending_reply"]
        return parse_reply(bytes(raw))

    @staticmethod
    def _verify_recovery_cause(histories, command_id, installation_ref, actor_ref, request_sha,command):
        causes = [item for item in histories if item.report is not None
            and item.report.body["content"]["recovery_command_id"] == command_id]
        expected = sha256(canonical_json(command)).hexdigest()
        if (len(causes) > 1 or expected != request_sha or any(
                item.intent.body["content"].get('staged_installation_ref',item.intent.body['content'].get('installation_ref')) != installation_ref.as_dict()
                or item.report.body["actor_ref"] != actor_ref.as_dict()
                for item in causes)):
            raise ConformanceError("conflict")

    def _recover_pending(self, db, row, actor_ref, recovery_command_id, now):
        roots = self._domain._read_roots(db)
        intent_ref = EntityRef("provider_conformance_run", row["command_id"], 1,
                               row["intent_sha256"])
        installation_ref = EntityRef(row["installation_kind"], row["installation_id"],
                                     row["installation_version"], row["installation_sha256"])
        intent = self._domain._load(db, intent_ref, roots)[0]
        content = intent.body["content"]
        admission = None
        if content['schema_version'] == 'provider-conformance-intent-v2':
            from .provider_conformance_resolver import historical_verified_admission
            admission = historical_verified_admission(self._prepare,db,canonical_json(content['admission']))
        context_sha = admission.stage_context_sha256 if admission is not None else content['context_sha256']
        report_content = {"schema_version": "provider-conformance-report-v1",
            "command_id": row["command_id"], "intent_ref": intent_ref.as_dict(),
            "installation_ref": installation_ref.as_dict(),
            "context_sha256": context_sha, "suite_sha256": SUITE_SHA256,
            "finished_ms": now, "elapsed_ms": None, "observations_blob_ref": None,
            "completion": "incomplete", "reason": "interrupted",
            "vectors": [{"vector_id": vector.vector_id, "comparison": "not_observed"}
                        for vector in fixed_vectors()],
            "covered_subchecks": [], "recovery_command_id": recovery_command_id}
        if admission is not None: self._verified_report(report_content,admission)
        report = ImmutableRecord.create(kind="provider_conformance_run", id=row["command_id"],
            version=2, created_at_utc=instant(now), actor_ref=actor_ref,
            parent_refs=(intent_ref, installation_ref)+(() if admission is None else (admission.verified_installation_ref,)), purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
            content=report_content)
        self._domain._put_in_transaction(db, report)
        event = _append_event_in_transaction(db, vault_id=roots.genesis.id,
            recorded_at_utc=instant(now), observed_at_utc=instant(now), actor_kind="human",
            actor_ref=actor_ref, event_type="provider.conformance_completed",
            object_refs=(ObjectRef(report.ref.kind, report.ref.id, report.ref.version,
                                   report.ref.sha256),), correlation_id=row["command_id"],
            causation_id=db.execute("SELECT event_id FROM api_event_envelopes WHERE vault_id=? "
                "AND sequence=?", (roots.genesis.id, row["started_sequence"])).fetchone()[0],
            status="unknown", error_code=None,
            public_metadata={"completed_count": 0, "matched_count": 0,
                             "outcome": "incomplete"},
            private_evidence_refs=(report.ref,), retention_class="core",
            policy_ref=roots.access_policy)
        cursor = _event_cursor_in_transaction(db, vault_id=roots.genesis.id,
            sequence=event.sequence, event_types=EVENT_TYPES)
        terminal = self._reply(row["command_id"], installation_ref, intent_ref, report.ref,
            "incomplete", context_sha, 0, 0, cursor,admission)
        terminal_raw = canonical_json(terminal)
        changed = _execute(db, "UPDATE provider_conformance_runs SET report_version=2,"
            "report_sha256=?,state='incomplete',finished_ms=?,finished_sequence=?,"
            "terminal_reply=? WHERE command_id=? AND state='pending'",
            (report.ref.sha256, now, event.sequence, terminal_raw, row["command_id"])).rowcount
        if changed != 1:
            raise ConformanceError("conflict")
        _execute(db, "UPDATE provider_conformance_control SET last_now_ms=?", (now,))

    def execute(self, authenticated_request, payload):
        value = parse_command(payload)
        command_id = value["command_id"]
        verified_variant = value.get('schema_version') == 'provider-conformance-command-v2'
        installation_ref = EntityRef.from_dict(value['staged_installation_ref'] if verified_variant else value['installation_ref'])
        request_sha = sha256(canonical_json(value)).hexdigest()
        try:
            # Recovery is one complete writer before the new command seeks admission.  It is
            # authorized only by this explicit, already parsed and authenticated attempt.
            with _writer(), self._domain._connection(write=True) as recovery_db:
                _, recovery_actor_ref = self._authenticate(authenticated_request, recovery_db)
                histories = verify_history(self._prepare, recovery_db)
                existing = recovery_db.execute(
                    "SELECT * FROM provider_conformance_runs WHERE command_id=?",
                    (command_id,)).fetchone()
                if existing is not None:
                    history = next((item for item in histories
                                    if item.command_id == command_id), None)
                    if (existing["request_sha256"] != request_sha
                            or existing["installation_id"] != installation_ref.id
                            or existing["installation_sha256"] != installation_ref.sha256
                            or history is None
                            or history.intent.body["actor_ref"] != recovery_actor_ref.as_dict()):
                        raise ConformanceError("conflict")
                    return self._row_reply(existing)
                self._verify_recovery_cause(histories, command_id, installation_ref,
                                            recovery_actor_ref, request_sha,value)
                pending = recovery_db.execute(
                    "SELECT * FROM provider_conformance_runs WHERE vault_id=? "
                    "AND installation_id=? AND state='pending'",
                    (self._domain._read_roots(recovery_db).genesis.id,
                     installation_ref.id)).fetchone()
                if pending is not None:
                    recovery_now = self._wall_now(recovery_db)
                    if recovery_now < pending["deadline_ms"]:
                        raise ConformanceError("conflict")
                    self._recover_pending(recovery_db, pending, recovery_actor_ref,
                                          command_id, recovery_now)
            admitted_monotonic = time.monotonic()
            with _writer(), self._domain._connection(write=True) as db:
                actor, actor_ref = self._authenticate(authenticated_request, db)
                histories = verify_history(self._prepare, db)
                self._verify_recovery_cause(histories, command_id, installation_ref,
                                            actor_ref, request_sha,value)
                existing = db.execute("SELECT * FROM provider_conformance_runs WHERE command_id=?",
                                      (command_id,)).fetchone()
                if existing is not None:
                    history = next((item for item in histories
                                    if item.command_id == command_id), None)
                    if (existing["request_sha256"] != request_sha
                            or existing["installation_id"] != installation_ref.id
                            or existing["installation_sha256"] != installation_ref.sha256
                            or history is None
                            or history.intent.body["actor_ref"] != actor_ref.as_dict()):
                        raise ConformanceError("conflict")
                    return self._row_reply(existing)
                pending = db.execute("SELECT 1 FROM provider_conformance_runs WHERE vault_id=? "
                    "AND installation_id=? AND state='pending'", (self._domain._read_roots(db).genesis.id,
                                                                  installation_ref.id)).fetchone()
                if pending is not None:
                    raise ConformanceError("conflict")
                admission = (resolve_verified_admission(self._prepare,db,installation_ref,
                    EntityRef.from_dict(value['expected_verified_installation_ref'])) if verified_variant else None)
                subject = admission.stage_subject if admission is not None else resolve_subject(self._prepare, db, installation_ref)
                control = db.execute("SELECT * FROM provider_conformance_control").fetchone()
                now = self._wall_now(db)
                if now > 253402300739999:
                    raise ConformanceError("unavailable")
                if admission is not None:
                    verification = db.execute(
                        'SELECT verified_ms FROM deployment_prepare_installation_verifications '
                        'WHERE installation_id=? AND anchor_digest=?',
                        (admission.verified_installation_ref.id,
                         admission.verified_installation_ref.sha256)).fetchone()
                    if verification is None or now < verification['verified_ms']:
                        raise ConformanceError('unavailable')
                if control["run_count"] >= 64:
                    raise ConformanceError("capacity")
                roots = self._domain._read_roots(db)
                context_sha = sha256(canonical_json(subject.as_dict())).hexdigest()
                content = {"schema_version": "provider-conformance-intent-v1",
                    "command_id": command_id, "request_sha256": request_sha,
                    "installation_ref": installation_ref.as_dict(), "subject": subject.as_dict(),
                    "context_sha256": context_sha, "suite_version": SUITE_VERSION,
                    "suite_sha256": SUITE_SHA256, "requester_version": "private-provider-requester-v1",
                    "comparator_version": "private-provider-literal-oracle-v1",
                    "admitted_ms": now, "deadline_ms": now + 60000}
                if admission is not None:
                    del content['installation_ref'],content['subject'],content['context_sha256']
                    content.update(schema_version='provider-conformance-intent-v2',
                        staged_installation_ref=installation_ref.as_dict(),verified_installation_ref=admission.verified_installation_ref.as_dict(),
                        admission=admission.as_dict(),admission_sha256=sha256(canonical_json(admission.as_dict())).hexdigest())
                intent = ImmutableRecord.create(kind="provider_conformance_run", id=command_id, version=1,
                    created_at_utc=instant(now), actor_ref=actor_ref, parent_refs=(installation_ref,)+(() if admission is None else (admission.verified_installation_ref,)),
                    purpose="operational", access_policy_ref=roots.access_policy,
                    retention_policy_ref=roots.retention_policy, content=content)
                self._domain._put_in_transaction(db, intent)
                event = _append_event_in_transaction(db, vault_id=roots.genesis.id,
                    recorded_at_utc=instant(now), observed_at_utc=instant(now), actor_kind="human",
                    actor_ref=actor_ref, event_type="provider.conformance_started",
                    object_refs=(ObjectRef(intent.ref.kind, intent.ref.id, intent.ref.version,
                                           intent.ref.sha256),), correlation_id=command_id,
                    causation_id=None, status="started", error_code=None,
                    public_metadata={"vector_count": 4}, private_evidence_refs=(),
                    retention_class="core", policy_ref=roots.access_policy)
                cursor = _event_cursor_in_transaction(db, vault_id=roots.genesis.id,
                    sequence=event.sequence, event_types=EVENT_TYPES)
                pending_reply = canonical_json(self._reply(command_id, installation_ref, intent.ref,
                    None, "pending", context_sha, 0, 0, cursor,admission))
                _execute(db, "INSERT INTO provider_conformance_runs VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (command_id, roots.genesis.id, request_sha, installation_ref.kind,
                     installation_ref.id, installation_ref.version, installation_ref.sha256,
                     "provider_conformance_run", 1, intent.ref.sha256, None, None, "pending", now,
                     now + 60000, None, event.sequence, None, pending_reply, None, 0))
                _execute(db, "UPDATE provider_conformance_control SET run_count=run_count+1,last_now_ms=?",
                           (now,))

            deadline = Deadline(admitted_monotonic + 60.0)

            def guard():
                with _writer(), self._domain._connection(write=True) as guard_db:
                    self._authenticate(authenticated_request, guard_db)
                    row = guard_db.execute("SELECT state,intent_sha256,deadline_ms "
                                           "FROM provider_conformance_runs "
                                           "WHERE command_id=?", (command_id,)).fetchone()
                    if row is None or row["state"] != "pending" or row["intent_sha256"] != intent.ref.sha256:
                        raise ConformanceError("conflict")
                    guard_now = self._wall_now(guard_db)
                    if guard_now >= row["deadline_ms"] or deadline.remaining() <= 0:
                        raise DeadlineExceeded()
                    self._require_current(guard_db,subject,admission)
                    _execute(guard_db, "UPDATE provider_conformance_control SET last_now_ms=?",
                                     (guard_now,))

            with _service_timing(boot_id=self._requester_boot_id, admitted_ms=now,
                                 admitted_monotonic=admitted_monotonic):
                capture = run_fixed_suite(subject, deadline=deadline, guard=guard)
            comparison = compare_capture(subject, capture)
            blob = self._domain.put_blob(capture.content_bytes, purpose="operational")
            with _writer(), self._domain._connection(write=True) as db:
                actor, final_actor_ref = self._authenticate(authenticated_request, db)
                verify_history(self._prepare, db)
                row = db.execute("SELECT * FROM provider_conformance_runs WHERE command_id=?",
                                 (command_id,)).fetchone()
                if (row is not None and row["state"] != "pending"
                        and row["request_sha256"] == request_sha
                        and row["intent_sha256"] == intent.ref.sha256):
                    return self._row_reply(row)
                if row is None or row["state"] != "pending" or row["intent_sha256"] != intent.ref.sha256:
                    raise ConformanceError("conflict")
                try:
                    self._require_current(db,subject,admission)
                except ConformanceError:
                    comparison = ConformanceComparison("incomplete", "source_changed",
                        comparison.vectors, comparison.covered_subchecks)
                final_now = self._wall_now(db)
                if (final_now >= row["deadline_ms"] or deadline.remaining() <= 0
                        ) and comparison.completion != "incomplete":
                    comparison = ConformanceComparison("incomplete", "deadline",
                        comparison.vectors, comparison.covered_subchecks)
                capture_value = parse_canonical(capture.content_bytes)
                if capture_value["elapsed_ms"] > 60000 and comparison.completion != "incomplete":
                    comparison = ConformanceComparison("incomplete", "deadline",
                        comparison.vectors, comparison.covered_subchecks)
                roots = self._domain._read_roots(db)
                vectors = [{"vector_id": vector_id, "comparison": result}
                           for vector_id, result in comparison.vectors]
                content = {"schema_version": "provider-conformance-report-v1",
                    "command_id": command_id, "intent_ref": intent.ref.as_dict(),
                    "installation_ref": installation_ref.as_dict(), "context_sha256": context_sha,
                    "suite_sha256": SUITE_SHA256, "finished_ms": final_now,
                    "elapsed_ms": capture_value["elapsed_ms"],
                    "observations_blob_ref": blob.as_dict(), "completion": comparison.completion,
                    "reason": comparison.reason, "vectors": vectors,
                    "covered_subchecks": list(comparison.covered_subchecks),
                    "recovery_command_id": None}
                if admission is not None: self._verified_report(content,admission)
                report = ImmutableRecord.create(kind="provider_conformance_run", id=command_id, version=2,
                    created_at_utc=instant(final_now), actor_ref=final_actor_ref,
                    parent_refs=(intent.ref, installation_ref)+(() if admission is None else (admission.verified_installation_ref,)), purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                    content=content)
                self._domain._put_in_transaction(db, report)
                completed = sum(result != "not_observed" for _, result in comparison.vectors)
                matched = sum(result == "matched" for _, result in comparison.vectors)
                status = "succeeded" if comparison.completion == "matched" else (
                    "failed" if comparison.completion == "mismatch" else "unknown")
                event = _append_event_in_transaction(db, vault_id=roots.genesis.id,
                    recorded_at_utc=instant(final_now), observed_at_utc=instant(final_now),
                    actor_kind="human", actor_ref=final_actor_ref,
                    event_type="provider.conformance_completed",
                    object_refs=(ObjectRef(report.ref.kind, report.ref.id, report.ref.version,
                                           report.ref.sha256),), correlation_id=command_id,
                    causation_id=db.execute("SELECT event_id FROM api_event_envelopes WHERE vault_id=? "
                        "AND sequence=?", (roots.genesis.id, row["started_sequence"])).fetchone()[0],
                    status=status, error_code=None,
                    public_metadata={"completed_count": completed, "matched_count": matched,
                                     "outcome": comparison.completion},
                    private_evidence_refs=(report.ref,), retention_class="core",
                    policy_ref=roots.access_policy)
                cursor = _event_cursor_in_transaction(db, vault_id=roots.genesis.id,
                    sequence=event.sequence, event_types=EVENT_TYPES)
                terminal = self._reply(command_id, installation_ref, intent.ref, report.ref,
                    comparison.completion, context_sha, completed, matched, cursor,admission)
                terminal_raw = canonical_json(terminal)
                changed = _execute(db, "UPDATE provider_conformance_runs SET report_version=2,report_sha256=?,"
                    "state=?,finished_ms=?,finished_sequence=?,terminal_reply=?,retained_bytes=? "
                    "WHERE command_id=? AND state='pending'", (report.ref.sha256, comparison.completion,
                    final_now, event.sequence, terminal_raw, len(capture.content_bytes), command_id)).rowcount
                if changed != 1:
                    raise ConformanceError("conflict")
                _execute(db, "UPDATE provider_conformance_control SET retained_bytes=retained_bytes+?,last_now_ms=?",
                           (len(capture.content_bytes), final_now))
                return terminal
        except ConformanceError:
            raise
        except (OwnerAuthError, DeploymentPrepareError) as exc:
            raise _map_error(exc) from None
        except (sqlite3.Error, StorageError, ValueError, TypeError, KeyError):
            raise ConformanceError("unavailable") from None

    def _require_current(self,db,subject,admission):
        if admission is None: require_current_subject(self._prepare,db,subject,self._source)
        else: require_current_verified_admission(self._prepare,db,admission,self._source)

    @staticmethod
    def _verified_report(content,admission):
        del content['installation_ref'],content['context_sha256']
        content.update(schema_version='provider-conformance-report-v2',
            staged_installation_ref=admission.staged_installation_ref.as_dict(),
            verified_installation_ref=admission.verified_installation_ref.as_dict(),
            admission_sha256=sha256(canonical_json(admission.as_dict())).hexdigest(),
            stage_context_sha256=admission.stage_context_sha256)

    def read(self, authenticated_request, command_id):
        try:
            uuid_string(command_id)
        except Exception:
            raise ConformanceError("invalid_input") from None
        try:
            with _writer(), self._domain._connection(write=True) as db:
                self._authenticate(authenticated_request, db, read=True)
                verify_history(self._prepare, db)
                row = db.execute("SELECT * FROM provider_conformance_runs WHERE command_id=?",
                                 (command_id,)).fetchone()
                if row is None:
                    raise ConformanceError("not_found")
                return self._row_reply(row)
        except ConformanceError:
            raise
        except Exception:
            raise ConformanceError("unavailable") from None

    def rehydrate(self, db, run_ref):
        return rehydrate_conformance(self._prepare, db, run_ref)
