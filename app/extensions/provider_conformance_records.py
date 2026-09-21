"""Immutable provider conformance history construction and rehydration."""

from dataclasses import dataclass
from hashlib import sha256

from ..deployment.prepare_lifecycle import instant
from ..domain.public_events import EventEnvelope, _decode_cursor, _event_cursor_in_transaction
from ..domain.refs import EntityRef, canonical_json, parse_canonical
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef
from .provider_conformance_contracts import (
    ConformanceError,
    RehydratedConformance,
    RehydratedVerifiedConformance,
    parse_capture,
    parse_reply,
)
from .provider_conformance_resolver import historical_subject,historical_verified_admission
from .provider_conformance_storage import verify_layout
from .provider_conformance_vectors import SUITE_SHA256, SUITE_VERSION
from ..workers.provider_client import compare_capture


@dataclass(frozen=True, slots=True)
class RunHistory:
    command_id: str
    row: dict
    intent: ImmutableRecord
    report: ImmutableRecord | None
    subject: object
    comparison: object | None
    capture_bytes: bytes | None
    admission: object | None = None


_EVENT_TYPES = ("provider.conformance_completed", "provider.conformance_started")


def _verify_frozen_cursor(db, vault_id, sequence, value):
    current = _decode_cursor(_event_cursor_in_transaction(
        db, vault_id=vault_id, sequence=sequence, event_types=_EVENT_TYPES))
    frozen = _decode_cursor(value)
    if (frozen["generation"] > current["generation"]
            or {**frozen, "generation": current["generation"]} != current):
        raise ConformanceError("unavailable")


def _bounded_record(domain, db, roots, ref, *, edges, blobs, byte_limit):
    scalar = db.execute("SELECT typeof(body),length(body) FROM domain_records WHERE "
        "vault_id=? AND kind=? AND id=? AND version=? AND sha256=?", (
        roots.genesis.id, ref.kind, ref.id, ref.version, ref.sha256)).fetchone()
    edge_count = db.execute("SELECT count(*) FROM domain_edges WHERE vault_id=? AND source_kind=? "
        "AND source_id=? AND source_version=?", (roots.genesis.id, ref.kind, ref.id,
        ref.version)).fetchone()[0]
    blob_count = db.execute("SELECT count(*) FROM domain_record_blobs WHERE vault_id=? "
        "AND source_kind=? AND source_id=? AND source_version=?", (roots.genesis.id, ref.kind,
        ref.id, ref.version)).fetchone()[0]
    if (scalar is None or tuple(scalar)[0] != "blob" or type(scalar[1]) is not int
            or not 1 <= scalar[1] <= byte_limit or edge_count != edges or blob_count != blobs):
        raise ConformanceError("unavailable")
    domain._check_graph(db, [ref], roots)
    return domain._load(db, ref, roots)[0]


def _event(db, roots, sequence):
    scalar = db.execute("SELECT typeof(sequence),typeof(event_id),typeof(event_type),"
        "typeof(envelope),length(envelope) FROM api_event_envelopes WHERE vault_id=? "
        "AND sequence=?", (roots.genesis.id, sequence)).fetchone()
    if scalar is None or tuple(scalar)[:4] != ("integer", "text", "text", "blob") \
            or type(scalar[4]) is not int or not 1 <= scalar[4] <= 65536:
        raise ConformanceError("unavailable")
    row = db.execute("SELECT sequence,event_id,event_type,envelope FROM api_event_envelopes "
        "WHERE vault_id=? AND sequence=?", (roots.genesis.id, sequence)).fetchone()
    envelope = EventEnvelope.from_bytes(bytes(row["envelope"]))
    if (row["sequence"] != envelope.sequence or row["event_id"] != envelope.event_id
            or row["event_type"] != envelope.event_type or envelope.vault_id != roots.genesis.id):
        raise ConformanceError("unavailable")
    return envelope


def _load_one_unchecked(prepare_service, db, row, owner_ref):
    domain = prepare_service._domain
    roots = domain._read_roots(db)
    row = dict(row)
    intent_ref = EntityRef("provider_conformance_run", row["command_id"], 1, row["intent_sha256"])
    scalar = db.execute('SELECT typeof(body),length(body) FROM domain_records WHERE vault_id=? AND kind=? AND id=? AND version=1 AND sha256=?',
        (roots.genesis.id,intent_ref.kind,intent_ref.id,intent_ref.sha256)).fetchone()
    source = (roots.genesis.id,intent_ref.kind,intent_ref.id,intent_ref.version)
    edge_count = db.execute('SELECT count(*) FROM domain_edges WHERE vault_id=? AND source_kind=? '
        'AND source_id=? AND source_version=?',source).fetchone()[0]
    blob_count = db.execute('SELECT count(*) FROM domain_record_blobs WHERE vault_id=? AND source_kind=? '
        'AND source_id=? AND source_version=?',source).fetchone()[0]
    if (scalar is None or scalar[0] != 'blob' or type(scalar[1]) is not int
            or not 1 <= scalar[1] <= 16384 or edge_count not in (7,8) or blob_count != 0):
        raise ConformanceError('unavailable')
    probe = domain._load(db,intent_ref,roots)[0]
    verified_variant = probe.body['content']['schema_version'] == 'provider-conformance-intent-v2'
    intent = _bounded_record(domain, db, roots, intent_ref, edges=8 if verified_variant else 7, blobs=0,
        byte_limit=16384 if verified_variant else 8192)
    content = intent.body["content"]
    pending = parse_reply(bytes(row["pending_reply"]))
    admission = None
    if verified_variant:
        admission = historical_verified_admission(prepare_service,db,canonical_json(content['admission']))
        subject = admission.stage_subject
        admission_sha = sha256(canonical_json(admission.as_dict())).hexdigest()
        if (content['staged_installation_ref'] != admission.staged_installation_ref.as_dict()
                or content['verified_installation_ref'] != admission.verified_installation_ref.as_dict()
                or content['admission_sha256'] != admission_sha): raise ConformanceError('unavailable')
        pending = _verified_projection(pending,admission,reply=True)
        command = {'schema_version':'provider-conformance-command-v2','command_id':row['command_id'],
            'staged_installation_ref':admission.staged_installation_ref.as_dict(),
            'expected_verified_installation_ref':admission.verified_installation_ref.as_dict()}
        content = {**content,'installation_ref':admission.staged_installation_ref.as_dict(),
            'context_sha256':admission.stage_context_sha256,'subject':subject.as_dict()}
    else:
        command = {'command_id':row['command_id'],'installation_ref':content['installation_ref']}
        if pending['schema_version'] != 'provider-conformance-reply-v1': raise ConformanceError('unavailable')
    _verify_frozen_cursor(db, roots.genesis.id, row["started_sequence"], pending["event_cursor"])
    if (row["vault_id"] != roots.genesis.id or row["request_sha256"] != content["request_sha256"]
            or row["installation_kind"] != "extension_installation"
            or {"kind": row["installation_kind"], "id": row["installation_id"],
                "version": row["installation_version"], "sha256": row["installation_sha256"]}
                != content["installation_ref"]
            or row["run_kind"] != "provider_conformance_run" or row["intent_version"] != 1
            or row["admitted_ms"] != content["admitted_ms"]
            or row["deadline_ms"] != content["deadline_ms"]
            or pending["command_id"] != row["command_id"]
            or pending["installation_ref"] != content["installation_ref"]
            or pending["intent_ref"] != intent_ref.as_dict() or pending["state"] != "pending"
            or pending["context_sha256"] != content["context_sha256"]
            or pending["suite_version"] != SUITE_VERSION
            or pending["suite_sha256"] != SUITE_SHA256
            or content["suite_sha256"] != SUITE_SHA256
            or intent.body["actor_ref"] != owner_ref.as_dict()
            or row["request_sha256"] != sha256(canonical_json(command)).hexdigest()
            or intent.body["access_policy_ref"] != roots.access_policy.as_dict()
            or intent.body["retention_policy_ref"] != roots.retention_policy.as_dict()
            or intent.body["created_at_utc"] != instant(content["admitted_ms"])):
        raise ConformanceError("unavailable")
    subject = admission.stage_subject if admission is not None else historical_subject(prepare_service, db, EntityRef.from_dict(content["installation_ref"]))
    if subject.as_dict() != content["subject"]:
        raise ConformanceError("unavailable")
    started = _event(db, roots, row["started_sequence"])
    if admission is not None:
        verification = db.execute('SELECT verified_ms,event_id FROM deployment_prepare_installation_verifications WHERE installation_id=? AND anchor_digest=?',
            (admission.verified_installation_ref.id,admission.verified_installation_ref.sha256)).fetchone()
        if (verification is None or content['admitted_ms'] < verification['verified_ms']
                or db.execute('SELECT sequence FROM api_event_envelopes WHERE event_id=?',(verification['event_id'],)).fetchone()[0] >= row['started_sequence']):
            raise ConformanceError('unavailable')
    if (started.event_type != "provider.conformance_started"
            or started.actor_kind != "human"
            or started.correlation_id != row["command_id"] or started.causation_id is not None
            or started.status != "started" or started.error_code is not None
            or started.public_metadata != {"vector_count": 4}
            or started.actor_ref.as_dict() != intent.body["actor_ref"]
            or started.recorded_at_utc != intent.body["created_at_utc"]
            or started.observed_at_utc != intent.body["created_at_utc"]
            or started.retention_class != "core"
            or started.policy_ref != roots.access_policy
            or tuple(item.as_dict() for item in started.object_refs) != ({"kind": intent_ref.kind,
                "id": intent_ref.id, "version": intent_ref.version,
                "content_hash": intent_ref.sha256},)
            or started.private_evidence_refs):
        raise ConformanceError("unavailable")
    report = comparison = capture_bytes = None
    if row["state"] != "pending":
        report_ref = EntityRef("provider_conformance_run", row["command_id"], 2, row["report_sha256"])
        report = _bounded_record(domain, db, roots, report_ref, edges=6 if verified_variant else 5,
                                 blobs=1 if row["retained_bytes"] else 0,
                                 byte_limit=65536)
        terminal = parse_reply(bytes(row["terminal_reply"]))
        _verify_frozen_cursor(db, roots.genesis.id, row["finished_sequence"],
                              terminal["event_cursor"])
        result = report.body["content"]
        if admission is not None:
            result = _verified_projection(result,admission,reply=False)
            terminal = _verified_projection(terminal,admission,reply=True)
        elif result['schema_version'] != 'provider-conformance-report-v1' or terminal['schema_version'] != 'provider-conformance-reply-v1':
            raise ConformanceError('unavailable')
        completed = sum(item["comparison"] != "not_observed" for item in result["vectors"])
        matched = sum(item["comparison"] == "matched" for item in result["vectors"])
        blob_size = 0 if result["observations_blob_ref"] is None else result["observations_blob_ref"]["size"]
        if (result["intent_ref"] != intent_ref.as_dict()
                or result["installation_ref"] != content["installation_ref"]
                or result["context_sha256"] != content["context_sha256"]
                or result["suite_sha256"] != content["suite_sha256"]
                or report.body["actor_ref"] != owner_ref.as_dict()
                or row["report_version"] != 2 or row["state"] != result["completion"]
                or row["finished_ms"] != result["finished_ms"] or row["retained_bytes"] != blob_size
                or terminal["command_id"] != row["command_id"]
                or terminal["installation_ref"] != content["installation_ref"]
                or terminal["intent_ref"] != intent_ref.as_dict()
                or terminal["result_ref"] != report_ref.as_dict()
                or terminal["state"] != result["completion"]
                or terminal["context_sha256"] != content["context_sha256"]
                or terminal["suite_version"] != SUITE_VERSION
                or terminal["suite_sha256"] != SUITE_SHA256
                or terminal["completed_count"] != completed or terminal["matched_count"] != matched):
            raise ConformanceError("unavailable")
        if (report.body["access_policy_ref"] != roots.access_policy.as_dict()
                or report.body["retention_policy_ref"] != roots.retention_policy.as_dict()
                or report.body["created_at_utc"] != instant(result["finished_ms"])
                or result["completion"] != "incomplete"
                and result["finished_ms"] >= content["deadline_ms"]):
            raise ConformanceError("unavailable")
        completed_event = _event(db, roots, row["finished_sequence"])
        status = "succeeded" if result["completion"] == "matched" else (
            "failed" if result["completion"] == "mismatch" else "unknown")
        if (completed_event.event_type != "provider.conformance_completed"
                or completed_event.actor_kind != "human"
                or completed_event.correlation_id != row["command_id"]
                or completed_event.causation_id != started.event_id
                or completed_event.status != status or completed_event.error_code is not None
                or completed_event.public_metadata != {"completed_count": completed,
                    "matched_count": matched, "outcome": result["completion"]}
                or completed_event.actor_ref.as_dict() != report.body["actor_ref"]
                or completed_event.recorded_at_utc != report.body["created_at_utc"]
                or completed_event.observed_at_utc != report.body["created_at_utc"]
                or completed_event.retention_class != "core"
                or completed_event.policy_ref != roots.access_policy
                or tuple(item.as_dict() for item in completed_event.object_refs) != ({
                    "kind": report_ref.kind, "id": report_ref.id, "version": report_ref.version,
                    "content_hash": report_ref.sha256},)
                or tuple(item.as_dict() for item in completed_event.private_evidence_refs)
                    != (report_ref.as_dict(),)):
            raise ConformanceError("unavailable")
        if result["observations_blob_ref"] is not None:
            blob = BlobRef.from_dict(result["observations_blob_ref"])
            capture_bytes = domain._blob_bytes(db, blob, roots, purpose="operational")
            capture = parse_capture(capture_bytes)
            capture_value = parse_canonical(capture.content_bytes)
            observed = compare_capture(subject, capture)
            recorded = tuple((entry["vector_id"], entry["comparison"])
                             for entry in result["vectors"])
            exact_comparison = (observed.completion == result["completion"]
                                and observed.reason == result["reason"])
            final_source_downgrade = (result["completion"] == "incomplete"
                                      and result["reason"] == "source_changed")
            final_deadline_downgrade = (result["completion"] == "incomplete"
                and result["reason"] == "deadline" and observed.completion != "incomplete")
            if (capture_value["started_ms"] != content["admitted_ms"]
                    or capture_value["finished_ms"] > result["finished_ms"]
                    or capture_value["elapsed_ms"] != result["elapsed_ms"]
                    or result["completion"] != "incomplete" and result["elapsed_ms"] > 60000
                    or observed.vectors != recorded
                    or observed.covered_subchecks != tuple(result["covered_subchecks"])
                    or not (exact_comparison or final_source_downgrade
                            or final_deadline_downgrade)):
                raise ConformanceError("unavailable")
            from .provider_conformance_contracts import ConformanceComparison
            comparison = ConformanceComparison(result["completion"], result["reason"], recorded,
                                                tuple(result["covered_subchecks"]))
        else:
            from .provider_conformance_contracts import ConformanceComparison
            comparison = ConformanceComparison("incomplete", result["reason"],
                tuple((entry["vector_id"], entry["comparison"]) for entry in result["vectors"]),
                tuple(result["covered_subchecks"]))
    elif any(row[name] is not None for name in ("report_version", "report_sha256", "finished_ms",
                                                  "finished_sequence", "terminal_reply")) \
            or row["retained_bytes"] != 0:
        raise ConformanceError("unavailable")
    return RunHistory(row["command_id"], row, intent, report, subject, comparison, capture_bytes,admission)


def _verified_projection(value,admission,*,reply):
    if (value['schema_version'] != ('provider-conformance-reply-v2' if reply else 'provider-conformance-report-v2')
            or value['staged_installation_ref'] != admission.staged_installation_ref.as_dict()
            or value['verified_installation_ref'] != admission.verified_installation_ref.as_dict()
            or value['stage_context_sha256'] != admission.stage_context_sha256
            or value['admission_sha256'] != sha256(canonical_json(admission.as_dict())).hexdigest()):
        raise ConformanceError('unavailable')
    return {**value,'installation_ref':admission.staged_installation_ref.as_dict(),'context_sha256':admission.stage_context_sha256}


def _load_one(prepare_service, db, row, owner_ref):
    try:
        return _load_one_unchecked(prepare_service, db, row, owner_ref)
    except ConformanceError as exc:
        if str(exc) == "unavailable":
            raise
        raise ConformanceError("unavailable") from None
    except Exception:
        raise ConformanceError("unavailable") from None


def verify_history(prepare_service, db):
    prepare_service._domain._assert_write_transaction(db)
    verify_layout(db)
    scalar_rows = list(db.execute("SELECT "
        "typeof(command_id),length(command_id),typeof(vault_id),length(vault_id),"
        "typeof(request_sha256),length(request_sha256),typeof(installation_kind),"
        "typeof(installation_id),length(installation_id),typeof(installation_version),"
        "typeof(installation_sha256),length(installation_sha256),typeof(run_kind),"
        "typeof(intent_version),typeof(intent_sha256),length(intent_sha256),"
        "typeof(report_version),typeof(report_sha256),coalesce(length(report_sha256),0),"
        "typeof(state),typeof(admitted_ms),typeof(deadline_ms),typeof(finished_ms),"
        "typeof(started_sequence),typeof(finished_sequence),typeof(pending_reply),"
        "length(pending_reply),typeof(terminal_reply),coalesce(length(terminal_reply),0),"
        "typeof(retained_bytes),installation_version,intent_version,report_version,state,"
        "admitted_ms,deadline_ms,finished_ms,started_sequence,finished_sequence,retained_bytes "
        "FROM provider_conformance_runs LIMIT 65"))
    for values in scalar_rows:
        values = tuple(values)
        if (values[0:6] != ("text", 36, "text", 36, "text", 64)
                or values[6:10] != ("text", "text", 36, "integer")
                or values[10:16] != ("text", 64, "text", "integer", "text", 64)
                or values[19:22] != ("text", "integer", "integer")
                or values[23] != "integer" or values[25] != "blob"
                or not 1 <= values[26] <= 8192 or values[29] != "integer"
                or values[16] not in {"null", "integer"}
                or values[17] not in {"null", "text"}
                or values[18] not in {0, 64}
                or values[22] not in {"null", "integer"}
                or values[24] not in {"null", "integer"}
                or values[27] not in {"null", "blob"}
                or not 0 <= values[28] <= 8192
                or values[30] != 1 or values[31] != 1
                or values[32] not in {None, 2}
                or values[33] not in {"pending", "matched", "mismatch", "incomplete"}
                or not 0 <= values[34] <= 253402300739999
                or values[35] != values[34] + 60000
                or (values[36] is not None
                    and not values[34] <= values[36] <= 253402300799999)
                or values[37] <= 0
                or (values[38] is not None and values[38] <= values[37])
                or not 0 <= values[39] <= 1048576):
            raise ConformanceError("unavailable")
    rows = list(db.execute("SELECT * FROM provider_conformance_runs ORDER BY admitted_ms,command_id LIMIT 65"))
    if len(rows) > 64 or len(rows) != len(scalar_rows):
        raise ConformanceError("unavailable")
    owner_ref = None
    if rows:
        try:
            _control, _claim, account = prepare_service._owner._check(db)
            if account is None:
                raise ConformanceError("unavailable")
            owner_ref = EntityRef.from_dict(parse_canonical(
                account["actor_ref"].encode("utf-8")))
        except ConformanceError:
            raise
        except Exception:
            raise ConformanceError("unavailable") from None
    histories = tuple(_load_one(prepare_service, db, row, owner_ref) for row in rows)
    floor = db.execute("SELECT last_now_ms FROM provider_conformance_control").fetchone()[0]
    if any(item.row["admitted_ms"] > floor
            or item.row["finished_ms"] is not None and item.row["finished_ms"] > floor
            for item in histories):
        raise ConformanceError("unavailable")
    indexed = {(item.command_id, item.intent.ref.version) for item in histories}
    indexed |= {(item.command_id, item.report.ref.version) for item in histories if item.report is not None}
    roots = prepare_service._domain._read_roots(db)
    records = {(row[0], row[1]) for row in db.execute(
        "SELECT id,version FROM domain_records WHERE vault_id=? AND "
        "kind='provider_conformance_run' LIMIT 130", (roots.genesis.id,))}
    if records != indexed:
        raise ConformanceError("unavailable")
    event_rows = list(db.execute("SELECT sequence FROM api_event_envelopes WHERE vault_id=? AND "
        "event_type IN ('provider.conformance_started','provider.conformance_completed') LIMIT 129",
        (roots.genesis.id,)))
    expected_sequences = {item.row["started_sequence"] for item in histories}
    expected_sequences |= {item.row["finished_sequence"] for item in histories
                           if item.row["finished_sequence"] is not None}
    if len(event_rows) > 128 or {row[0] for row in event_rows} != expected_sequences:
        raise ConformanceError("unavailable")
    return histories


def rehydrate_conformance(prepare_service, db, run_ref):
    prepare_service._domain._assert_write_transaction(db)
    if type(run_ref) is not EntityRef or run_ref.kind != "provider_conformance_run" or run_ref.version != 2:
        raise ConformanceError("invalid_input")
    matches = [item for item in verify_history(prepare_service, db)
               if item.command_id == run_ref.id and item.report is not None]
    if len(matches) != 1 or matches[0].report.ref != run_ref:
        raise ConformanceError("not_found")
    item = matches[0]
    if item.admission is not None:
        return RehydratedVerifiedConformance(item.intent.ref,item.report.ref,item.admission,item.comparison,item.capture_bytes)
    return RehydratedConformance(item.intent.ref, item.report.ref, item.subject,
                                 item.comparison, item.capture_bytes)
