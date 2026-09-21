from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef, canonical_json, parse_canonical
from app.domain.store import _writer
from app.extensions.provider_conformance_contracts import ConformanceError
from app.extensions import provider_conformance_service as service_module
from app.extensions.provider_conformance_service import PersistentProviderConformance
from app.extensions.provider_conformance_records import verify_history
from app.tests.provider_conformance_fixture import _provider_conformance_worker, staged_conformance_app
from app.workers import provider_client


def test_actual_stage_executes_seals_replays_and_rehydrates_without_second_dispatch(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            reply = service.execute(staged.actual.request, payload)
            if reply["result_ref"] is not None:
                with _writer(), staged.domain._connection(write=True) as db:
                    observed = service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
            assert reply["state"] == "matched", observed.comparison
            assert reply["completed_count"] == reply["matched_count"] == 4
        assert worker.completion_count == 6
        assert service.execute(staged.actual.request, payload) == reply
        assert service.read(staged.actual.read_request, payload["command_id"]) == reply
        with _writer(), staged.domain._connection(write=True) as db:
            retained = service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
        assert retained.report_ref.as_dict() == reply["result_ref"]
        assert retained.comparison.completion == "matched"
        assert retained.capture_bytes is not None
        def forbidden(*args, **kwargs):
            raise AssertionError("frozen replay consulted fresh execution state")
        monkeypatch.setattr(service_module, "run_fixed_suite", forbidden)
        monkeypatch.setattr(service_module, "resolve_subject", forbidden)
        monkeypatch.setattr(service, "_wall_now", forbidden)
        monkeypatch.setattr(service_module, "time", __import__("types").SimpleNamespace(
            time_ns=forbidden, monotonic=forbidden))
        monkeypatch.setattr(provider_client.listener, "_connect_extension_authenticated", forbidden)
        monkeypatch.setattr(provider_client.os, "urandom", forbidden)
        monkeypatch.setattr(provider_client, "uuid4", forbidden)
        assert service.execute(staged.actual.request, payload) == reply
        assert service.read(staged.actual.read_request, payload["command_id"]) == reply


def test_rehydrate_rejects_corrupt_frozen_reply_without_live_dispatch(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            reply = service.execute(staged.actual.request, payload)
        assert worker.completion_count == 6
        assert reply["state"] == "matched"
        with _writer(), staged.domain._connection(write=True) as db:
            retained = service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
        transcript_capture = parse_canonical(retained.capture_bytes)
        vector_frames = transcript_capture["attempts"][1]["frames"]
        removed = next(index for index, frame in enumerate(vector_frames)
                       if frame["direction"] == "sent")
        del vector_frames[removed]
        elapsed_capture = parse_canonical(retained.capture_bytes)
        elapsed_capture["elapsed_ms"] = 60001

        def wrong_ready_capture(*, trim_local):
            value = parse_canonical(retained.capture_bytes)
            frames = value["attempts"][1]["frames"]
            index = next(index for index, frame in enumerate(frames)
                if frame["direction"] == "received" and frame["message_type"] == provider_client.RESULT
                and provider_client.provider_messages.parse_control(
                    provider_client._frame_payload(frame)).get("schema") ==
                    "provider-transform-ready-v1")
            ready = provider_client.provider_messages.parse_control(
                provider_client._frame_payload(frames[index]))
            ready["phase"] = "inputs"
            frames[index]["payload_chunks"] = provider_client._payload_chunks(
                provider_client.provider_messages.encode_control(ready))
            if trim_local:
                value["attempts"][1]["frames"] = frames[:index + 1]
            return canonical_json(value)

        duplicate_capture = parse_canonical(retained.capture_bytes)
        duplicate_capture["attempts"] = duplicate_capture["attempts"][:2]
        duplicate_attempt = duplicate_capture["attempts"][-1]
        duplicate_attempt["failure"] = "protocol_error"
        frames = duplicate_attempt["frames"]
        plan_batch = provider_client.provider_messages.parse_control(
            provider_client._frame_payload(frames[0]))["plan"]["batch_id"]
        projection_frame = next(frame for frame in frames
            if frame["direction"] == "received" and frame["message_type"] == provider_client.RESULT
            and provider_client.provider_messages.parse_control(
                provider_client._frame_payload(frame))["schema"] == "provider-transform-projection-v1")
        projection = provider_client.provider_messages.parse_control(
            provider_client._frame_payload(projection_frame))
        old_batch = projection["body"]["batch_id"]
        projection["body"]["batch_id"] = plan_batch
        projection_frame["payload_chunks"] = provider_client._payload_chunks(
            provider_client.provider_messages.encode_control(projection))
        for frame in frames:
            if (frame["message_type"] == provider_client.ARTIFACT
                    and frame["correlation_id"] == projection_frame["message_id"]):
                message = parse_canonical(provider_client._frame_payload(frame))
                if message.get("batch_id") == old_batch:
                    message["batch_id"] = plan_batch
                    frame["payload_chunks"] = provider_client._payload_chunks(canonical_json(message))
        wrong_peer_capture = parse_canonical(retained.capture_bytes)
        wrong_peer = wrong_peer_capture["attempts"][-1]
        wrong_peer["failure"] = "identity_mismatch"
        wrong_peer["connection"]["peer_uid"] = (wrong_peer["connection"]["peer_uid"] + 1) % (2**32)

        forged_blobs = (
            ("duplicate_batch_local_suffix", staged.domain.put_blob(
                canonical_json(duplicate_capture), purpose="operational"), None, True),
            ("acquired_peer_local_suffix", staged.domain.put_blob(
                canonical_json(wrong_peer_capture), purpose="operational"), None, True),
            ("transcript", staged.domain.put_blob(canonical_json(transcript_capture),
                                                  purpose="operational"), None, False),
            ("elapsed", staged.domain.put_blob(canonical_json(elapsed_capture),
                                               purpose="operational"), 60001, False),
            ("continued_mismatch", staged.domain.put_blob(
                wrong_ready_capture(trim_local=False), purpose="operational"), None, True),
            ("later_attempts", staged.domain.put_blob(
                wrong_ready_capture(trim_local=True), purpose="operational"), None, True),
        )
        with _writer(), staged.domain._connection(write=True) as db:
            db.execute("SAVEPOINT corrupt_frozen_reply")
            try:
                db.execute("UPDATE provider_conformance_runs SET terminal_reply=? WHERE command_id=?",
                    (b"{}", payload["command_id"]))
                with pytest.raises(ConformanceError, match="^unavailable$"):
                    service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
            finally:
                db.execute("ROLLBACK TO corrupt_frozen_reply")
                db.execute("RELEASE corrupt_frozen_reply")
            db.execute("SAVEPOINT corrupt_frozen_cursor")
            try:
                corrupted = reply | {"event_cursor": "x" * 32}
                db.execute("UPDATE provider_conformance_runs SET terminal_reply=? WHERE command_id=?",
                    (canonical_json(corrupted), payload["command_id"]))
                with pytest.raises(ConformanceError, match="^unavailable$"):
                    service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
            finally:
                db.execute("ROLLBACK TO corrupt_frozen_cursor")
                db.execute("RELEASE corrupt_frozen_cursor")
            for name, statement, arguments in (
                ("counter", "UPDATE provider_conformance_control SET run_count=2", ()),
                ("intent", "UPDATE domain_records SET body=? WHERE kind=? AND id=? AND version=1",
                    (b"{}", "provider_conformance_run", payload["command_id"])),
                ("edge", "DELETE FROM domain_edges WHERE source_kind=? AND source_id=? "
                    "AND source_version=2",
                    ("provider_conformance_run", payload["command_id"])),
                ("event", "UPDATE api_event_envelopes SET envelope=(SELECT envelope FROM "
                    "api_event_envelopes WHERE sequence=(SELECT started_sequence FROM "
                    "provider_conformance_runs WHERE command_id=?)) WHERE sequence=(SELECT "
                    "finished_sequence FROM provider_conformance_runs WHERE command_id=?)",
                    (payload["command_id"], payload["command_id"])),
            ):
                savepoint = "corrupt_" + name
                db.execute("SAVEPOINT " + savepoint)
                try:
                    db.execute(statement, arguments)
                    with pytest.raises(ConformanceError, match="^unavailable$"):
                        service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
                finally:
                    db.execute("ROLLBACK TO " + savepoint)
                db.execute("RELEASE " + savepoint)
            db.execute("PRAGMA defer_foreign_keys=ON")
            for name, forged_blob, elapsed_ms, mismatch in forged_blobs:
                savepoint = "refreshed_" + name + "_forgery"
                db.execute("SAVEPOINT " + savepoint)
                row = db.execute("SELECT report_sha256,finished_sequence,terminal_reply,"
                    "retained_bytes FROM provider_conformance_runs WHERE command_id=?",
                    (payload["command_id"],)).fetchone()
                body = parse_canonical(db.execute("SELECT body FROM domain_records WHERE kind=? "
                    "AND id=? AND version=2", ("provider_conformance_run",
                    payload["command_id"])).fetchone()[0])
                body["content"]["observations_blob_ref"] = forged_blob.as_dict()
                if elapsed_ms is not None:
                    body["content"]["elapsed_ms"] = elapsed_ms
                if mismatch:
                    body["content"]["completion"] = "mismatch"
                    body["content"]["reason"] = "compared"
                    if name == "duplicate_batch_local_suffix":
                        # R3 accepts this impossible flow and incorrectly covers the first vector.
                        # Refresh all claimed results to that exact output, not a stale report.
                        for index, vector in enumerate(body["content"]["vectors"]):
                            vector["comparison"] = "matched" if index == 0 else "not_observed"
                        body["content"]["covered_subchecks"] = ["text-basic-v1"]
                    elif name == "acquired_peer_local_suffix":
                        body["content"]["reason"] = "identity_mismatch"
                    else:
                        body["content"]["vectors"][0]["comparison"] = "mismatch"
                        body["content"]["covered_subchecks"] = (
                            body["content"]["covered_subchecks"][1:])
                raw = canonical_json(body)
                refreshed = __import__("hashlib").sha256(raw).hexdigest()
                db.execute("UPDATE domain_records SET sha256=?,body=? WHERE kind=? AND id=? "
                    "AND version=2", (refreshed, raw, "provider_conformance_run",
                    payload["command_id"]))
                db.execute("UPDATE domain_record_blobs SET purpose=?,sha256=?,size=? WHERE "
                    "source_kind=? AND source_id=? AND source_version=2", (forged_blob.purpose,
                    forged_blob.sha256, forged_blob.size, "provider_conformance_run",
                    payload["command_id"]))
                terminal = parse_canonical(bytes(row["terminal_reply"]))
                terminal["result_ref"]["sha256"] = refreshed
                terminal["state"] = body["content"]["completion"]
                terminal["completed_count"] = sum(item["comparison"] != "not_observed"
                    for item in body["content"]["vectors"])
                terminal["matched_count"] = sum(item["comparison"] == "matched"
                    for item in body["content"]["vectors"])
                db.execute("UPDATE provider_conformance_runs SET state=?,report_sha256=?,"
                    "terminal_reply=?,retained_bytes=? WHERE command_id=?", (
                    body["content"]["completion"], refreshed, canonical_json(terminal),
                    forged_blob.size, payload["command_id"]))
                db.execute("UPDATE provider_conformance_control SET retained_bytes="
                    "retained_bytes+?", (forged_blob.size - row["retained_bytes"],))
                event = parse_canonical(db.execute("SELECT envelope FROM api_event_envelopes WHERE "
                    "sequence=?", (row["finished_sequence"],)).fetchone()[0])
                event["object_refs"][0]["content_hash"] = refreshed
                event["private_evidence_refs"][0]["sha256"] = refreshed
                event["status"] = ("succeeded" if body["content"]["completion"] == "matched"
                                   else "failed")
                event["public_metadata"] = {"completed_count": terminal["completed_count"],
                    "matched_count": terminal["matched_count"],
                    "outcome": body["content"]["completion"]}
                db.execute("UPDATE api_event_envelopes SET envelope=? WHERE sequence=?",
                           (canonical_json(event), row["finished_sequence"]))
                with pytest.raises(ConformanceError, match="^unavailable$"):
                    service.rehydrate(db, EntityRef("provider_conformance_run",
                        payload["command_id"], 2, refreshed))
                db.execute("ROLLBACK TO " + savepoint)
                db.execute("RELEASE " + savepoint)


def test_full_family_rejects_refreshed_hash_forgery_in_a_different_run(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payloads = tuple({"command_id": str(uuid4()),
            "installation_ref": staged.installation_ref.as_dict()} for _ in range(2))
        replies = []
        for payload in payloads:
            with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
                replies.append(service.execute(staged.actual.request, payload))
            assert worker.completion_count == 6
        with _writer(), staged.domain._connection(write=True) as db:
            captures = tuple(parse_canonical(service.rehydrate(
                db, EntityRef.from_dict(reply["result_ref"])).capture_bytes) for reply in replies)
        assert len({attempt["connection"]["requester_boot_id"] for capture in captures
            for attempt in capture["attempts"]}) == 1
        forged_id = payloads[1]["command_id"]
        with _writer(), staged.domain._connection(write=True) as db:
            db.execute("PRAGMA defer_foreign_keys=ON")
            roots = staged.domain._read_roots(db)

            def reject_different_run():
                with pytest.raises(ConformanceError, match="^unavailable$"):
                    service.rehydrate(db, EntityRef.from_dict(replies[0]["result_ref"]))

            row = db.execute("SELECT report_sha256,finished_sequence,terminal_reply,"
                "deadline_ms FROM provider_conformance_runs WHERE command_id=?",
                (forged_id,)).fetchone()
            db.execute("SAVEPOINT wrong_event_actor_kind")
            event = parse_canonical(db.execute("SELECT envelope FROM api_event_envelopes WHERE "
                "sequence=?", (row["finished_sequence"],)).fetchone()[0])
            event["actor_kind"] = "provider"
            db.execute("UPDATE api_event_envelopes SET envelope=? WHERE sequence=?",
                       (canonical_json(event), row["finished_sequence"]))
            reject_different_run()
            db.execute("ROLLBACK TO wrong_event_actor_kind")
            db.execute("RELEASE wrong_event_actor_kind")

            def rewrite_report(*, finished_ms=None, actor_ref=None):
                current = db.execute("SELECT report_sha256,finished_sequence,terminal_reply,"
                    "deadline_ms FROM provider_conformance_runs WHERE command_id=?",
                    (forged_id,)).fetchone()
                body = parse_canonical(db.execute("SELECT body FROM domain_records WHERE kind=? "
                    "AND id=? AND version=2", ("provider_conformance_run", forged_id)).fetchone()[0])
                old_actor = body["actor_ref"]
                if finished_ms is not None:
                    body["content"]["finished_ms"] = finished_ms
                    body["created_at_utc"] = service_module.instant(finished_ms)
                if actor_ref is not None:
                    body["actor_ref"] = actor_ref.as_dict()
                    db.execute("UPDATE domain_edges SET target_id=?,target_version=?,"
                        "target_sha256=? WHERE source_kind='provider_conformance_run' AND "
                        "source_id=? AND source_version=2 AND target_kind='actor' AND target_id=?",
                        (actor_ref.id, actor_ref.version, actor_ref.sha256, forged_id,
                         old_actor["id"]))
                raw = canonical_json(body)
                refreshed = __import__("hashlib").sha256(raw).hexdigest()
                db.execute("UPDATE domain_records SET sha256=?,body=? WHERE kind=? AND id=? "
                    "AND version=2", (refreshed, raw, "provider_conformance_run", forged_id))
                terminal = parse_canonical(bytes(current["terminal_reply"]))
                terminal["result_ref"]["sha256"] = refreshed
                updates = "report_sha256=?,terminal_reply=?"
                arguments = [refreshed, canonical_json(terminal)]
                if finished_ms is not None:
                    updates += ",finished_ms=?"
                    arguments.append(finished_ms)
                arguments.append(forged_id)
                db.execute("UPDATE provider_conformance_runs SET " + updates +
                           " WHERE command_id=?", arguments)
                event = parse_canonical(db.execute("SELECT envelope FROM api_event_envelopes "
                    "WHERE sequence=?", (current["finished_sequence"],)).fetchone()[0])
                event["object_refs"][0]["content_hash"] = refreshed
                event["private_evidence_refs"][0]["sha256"] = refreshed
                if finished_ms is not None:
                    event["recorded_at_utc"] = service_module.instant(finished_ms)
                    event["observed_at_utc"] = service_module.instant(finished_ms)
                    db.execute("UPDATE provider_conformance_control SET last_now_ms=?",
                               (finished_ms,))
                if actor_ref is not None:
                    event["actor_ref"] = actor_ref.as_dict()
                db.execute("UPDATE api_event_envelopes SET envelope=? WHERE sequence=?",
                    (canonical_json(event), current["finished_sequence"]))

            db.execute("SAVEPOINT matched_at_deadline")
            rewrite_report(finished_ms=row["deadline_ms"])
            reject_different_run()
            db.execute("ROLLBACK TO matched_at_deadline")
            db.execute("RELEASE matched_at_deadline")

            db.execute("SAVEPOINT report_system_actor")
            rewrite_report(actor_ref=roots.actor)
            reject_different_run()
            db.execute("ROLLBACK TO report_system_actor")
            db.execute("RELEASE report_system_actor")

            db.execute("SAVEPOINT intent_system_actor")
            current = db.execute("SELECT intent_sha256,report_sha256,started_sequence,"
                "finished_sequence,pending_reply,terminal_reply FROM provider_conformance_runs "
                "WHERE command_id=?", (forged_id,)).fetchone()
            intent_body = parse_canonical(db.execute("SELECT body FROM domain_records WHERE "
                "kind='provider_conformance_run' AND id=? AND version=1",
                (forged_id,)).fetchone()[0])
            old_actor = intent_body["actor_ref"]
            intent_body["actor_ref"] = roots.actor.as_dict()
            intent_raw = canonical_json(intent_body)
            intent_sha = __import__("hashlib").sha256(intent_raw).hexdigest()
            db.execute("UPDATE domain_records SET sha256=?,body=? WHERE kind=? AND id=? "
                "AND version=1", (intent_sha, intent_raw, "provider_conformance_run", forged_id))
            db.execute("UPDATE domain_edges SET target_id=?,target_version=?,target_sha256=? "
                "WHERE source_kind='provider_conformance_run' AND source_id=? AND "
                "source_version=1 AND target_kind='actor' AND target_id=?",
                (roots.actor.id, roots.actor.version, roots.actor.sha256, forged_id,
                 old_actor["id"]))
            report_body = parse_canonical(db.execute("SELECT body FROM domain_records WHERE "
                "kind='provider_conformance_run' AND id=? AND version=2",
                (forged_id,)).fetchone()[0])
            report_body["content"]["intent_ref"]["sha256"] = intent_sha
            report_raw = canonical_json(report_body)
            report_sha = __import__("hashlib").sha256(report_raw).hexdigest()
            db.execute("UPDATE domain_records SET sha256=?,body=? WHERE kind=? AND id=? "
                "AND version=2", (report_sha, report_raw, "provider_conformance_run", forged_id))
            db.execute("UPDATE domain_edges SET target_sha256=? WHERE source_kind="
                "'provider_conformance_run' AND source_id=? AND source_version=2 AND "
                "target_kind='provider_conformance_run' AND target_version=1",
                (intent_sha, forged_id))
            pending = parse_canonical(bytes(current["pending_reply"]))
            pending["intent_ref"]["sha256"] = intent_sha
            terminal = parse_canonical(bytes(current["terminal_reply"]))
            terminal["intent_ref"]["sha256"] = intent_sha
            terminal["result_ref"]["sha256"] = report_sha
            db.execute("UPDATE provider_conformance_runs SET intent_sha256=?,report_sha256=?,"
                "pending_reply=?,terminal_reply=? WHERE command_id=?", (intent_sha, report_sha,
                canonical_json(pending), canonical_json(terminal), forged_id))
            started = parse_canonical(db.execute("SELECT envelope FROM api_event_envelopes "
                "WHERE sequence=?", (current["started_sequence"],)).fetchone()[0])
            started["actor_ref"] = roots.actor.as_dict()
            started["object_refs"][0]["content_hash"] = intent_sha
            db.execute("UPDATE api_event_envelopes SET envelope=? WHERE sequence=?",
                (canonical_json(started), current["started_sequence"]))
            completed = parse_canonical(db.execute("SELECT envelope FROM api_event_envelopes "
                "WHERE sequence=?", (current["finished_sequence"],)).fetchone()[0])
            completed["object_refs"][0]["content_hash"] = report_sha
            completed["private_evidence_refs"][0]["sha256"] = report_sha
            db.execute("UPDATE api_event_envelopes SET envelope=? WHERE sequence=?",
                (canonical_json(completed), current["finished_sequence"]))
            reject_different_run()
            db.execute("ROLLBACK TO intent_system_actor")
            db.execute("RELEASE intent_system_actor")

            row = db.execute("SELECT report_sha256,finished_sequence,terminal_reply FROM "
                "provider_conformance_runs WHERE command_id=?", (forged_id,)).fetchone()
            body = parse_canonical(db.execute("SELECT body FROM domain_records WHERE kind=? "
                "AND id=? AND version=2", ("provider_conformance_run", forged_id)).fetchone()[0])
            body["content"]["suite_sha256"] = "f" * 64
            raw = canonical_json(body)
            refreshed = __import__("hashlib").sha256(raw).hexdigest()
            db.execute("UPDATE domain_records SET sha256=?,body=? WHERE kind=? AND id=? AND version=2",
                (refreshed, raw, "provider_conformance_run", forged_id))
            terminal = parse_canonical(bytes(row["terminal_reply"]))
            terminal["result_ref"]["sha256"] = refreshed
            db.execute("UPDATE provider_conformance_runs SET report_sha256=?,terminal_reply=? "
                "WHERE command_id=?", (refreshed, canonical_json(terminal), forged_id))
            event = parse_canonical(db.execute("SELECT envelope FROM api_event_envelopes WHERE "
                "sequence=?", (row["finished_sequence"],)).fetchone()[0])
            event["object_refs"][0]["content_hash"] = refreshed
            event["private_evidence_refs"][0]["sha256"] = refreshed
            db.execute("UPDATE api_event_envelopes SET envelope=? WHERE sequence=?",
                       (canonical_json(event), row["finished_sequence"]))
            with pytest.raises(ConformanceError, match="^unavailable$"):
                service.rehydrate(db, EntityRef.from_dict(replies[0]["result_ref"]))
        with pytest.raises(ConformanceError, match="^unavailable$"):
            PersistentProviderConformance(staged.domain, staged.actual.owner,
                prepare_service=staged.prepare, source_context=staged.actual.context)


def test_two_services_race_same_command_without_duplicate_dispatch(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        services = tuple(PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context) for _ in range(2))
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        barrier = Barrier(2)

        def execute(service):
            barrier.wait()
            return service.execute(staged.actual.request, payload)

        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = tuple(pool.map(execute, services))
        assert worker.completion_count == 6
        assert {reply["state"] for reply in replies} <= {"pending", "matched"}
        terminal = services[0].execute(staged.actual.request, payload)
        assert terminal["state"] == "matched"
        assert services[1].execute(staged.actual.request, payload) == terminal
        with _writer(), staged.domain._connection(write=True) as db:
            assert db.execute("SELECT count(*) FROM provider_conformance_runs WHERE command_id=?",
                (payload["command_id"],)).fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind=? AND id=?",
                ("provider_conformance_run", payload["command_id"])).fetchone()[0] == 2


def test_two_distinct_commands_race_for_one_installation_and_only_one_dispatches(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        services = tuple(PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context) for _ in range(2))
        payloads = tuple({"command_id": str(uuid4()),
            "installation_ref": staged.installation_ref.as_dict()} for _ in range(2))
        barrier = Barrier(2)

        def execute(pair):
            service, payload = pair
            barrier.wait()
            try:
                return "reply", service.execute(staged.actual.request, payload)
            except ConformanceError as error:
                return "error", error.code

        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = tuple(pool.map(execute, zip(services, payloads, strict=True)))
        assert worker.completion_count == 6
        assert sorted(kind for kind, _ in results) == ["error", "reply"]
        assert next(value for kind, value in results if kind == "error") == "conflict"
        assert next(value for kind, value in results if kind == "reply")["state"] == "matched"
        with _writer(), staged.domain._connection(write=True) as db:
            assert db.execute("SELECT count(*) FROM provider_conformance_runs WHERE command_id IN (?,?)",
                              tuple(payload["command_id"] for payload in payloads)).fetchone()[0] == 1


@pytest.mark.parametrize("fault", ["intent", "started-event", "index-insert", "control-counter"])
def test_admission_write_fault_rolls_back_entire_family(tmp_path, monkeypatch, fault):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        domain_type = type(staged.domain)
        actual_put = domain_type._put_in_transaction
        actual_append = service_module._append_event_in_transaction
        actual_execute = service_module._execute
        if fault == "intent":
            def put(_self, db, record):
                if record.ref.kind == "provider_conformance_run":
                    raise sqlite3.OperationalError("controlled intent write failure")
                return actual_put(_self, db, record)
            monkeypatch.setattr(domain_type, "_put_in_transaction", put)
        elif fault == "started-event":
            def append(db, **kwargs):
                if kwargs["event_type"] == "provider.conformance_started":
                    raise sqlite3.OperationalError("controlled started event failure")
                return actual_append(db, **kwargs)
            monkeypatch.setattr(service_module, "_append_event_in_transaction", append)
        else:
            target = ("INSERT INTO provider_conformance_runs" if fault == "index-insert"
                      else "UPDATE provider_conformance_control SET run_count")

            def execute(db, statement, arguments=()):
                if statement.startswith(target):
                    raise sqlite3.OperationalError("controlled admission index write")
                return actual_execute(db, statement, arguments)

            monkeypatch.setattr(service_module, "_execute", execute)
        with pytest.raises(ConformanceError, match="^unavailable$"):
            service.execute(staged.actual.request, payload)
        monkeypatch.setattr(domain_type, "_put_in_transaction", actual_put)
        monkeypatch.setattr(service_module, "_append_event_in_transaction", actual_append)
        monkeypatch.setattr(service_module, "_execute", actual_execute)
        with _writer(), staged.domain._connection(write=True) as db:
            assert db.execute("SELECT count(*) FROM provider_conformance_runs WHERE command_id=?",
                (payload["command_id"],)).fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind=? AND id=?",
                ("provider_conformance_run", payload["command_id"])).fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM api_event_envelopes WHERE event_type LIKE "
                "'provider.conformance_%'").fetchone()[0] == 0
            assert tuple(db.execute("SELECT run_count,retained_bytes FROM "
                "provider_conformance_control").fetchone()) == (0, 0)


@pytest.mark.parametrize("fault", ["report", "completed-event", "index-update", "control-retained"])
def test_final_write_fault_leaves_only_verified_pending_family(tmp_path, monkeypatch, fault):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        domain_type = type(staged.domain)
        actual_put = domain_type._put_in_transaction
        actual_append = service_module._append_event_in_transaction
        actual_execute = service_module._execute
        if fault == "report":
            def put(_self, db, record):
                if record.ref.kind == "provider_conformance_run" and record.ref.version == 2:
                    raise sqlite3.OperationalError("controlled report write failure")
                return actual_put(_self, db, record)
            monkeypatch.setattr(domain_type, "_put_in_transaction", put)
        elif fault == "completed-event":
            def append(db, **kwargs):
                if kwargs["event_type"] == "provider.conformance_completed":
                    raise sqlite3.OperationalError("controlled completed event failure")
                return actual_append(db, **kwargs)
            monkeypatch.setattr(service_module, "_append_event_in_transaction", append)
        else:
            target = ("UPDATE provider_conformance_runs SET report_version"
                      if fault == "index-update" else
                      "UPDATE provider_conformance_control SET retained_bytes")

            def execute(db, statement, arguments=()):
                if statement.startswith(target):
                    raise sqlite3.OperationalError("controlled final index write")
                return actual_execute(db, statement, arguments)

            monkeypatch.setattr(service_module, "_execute", execute)
        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            with pytest.raises(ConformanceError, match="^unavailable$"):
                service.execute(staged.actual.request, payload)
        assert worker.completion_count == 6
        monkeypatch.setattr(domain_type, "_put_in_transaction", actual_put)
        monkeypatch.setattr(service_module, "_append_event_in_transaction", actual_append)
        monkeypatch.setattr(service_module, "_execute", actual_execute)
        pending = service.execute(staged.actual.request, payload)
        assert pending["state"] == "pending" and pending["result_ref"] is None
        with _writer(), staged.domain._connection(write=True) as db:
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind=? AND id=?",
                ("provider_conformance_run", payload["command_id"])).fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM api_event_envelopes WHERE event_type LIKE "
                "'provider.conformance_%'").fetchone()[0] == 1
            assert tuple(db.execute("SELECT run_count,retained_bytes FROM "
                "provider_conformance_control").fetchone()) == (1, 0)


def test_final_compare_and_set_loser_cannot_publish_or_increment_control(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        actual_execute = service_module._execute

        def lose(db, statement, arguments=()):
            if statement.startswith("UPDATE provider_conformance_runs SET report_version"):
                return db.execute("UPDATE provider_conformance_runs SET state=state WHERE 0")
            return actual_execute(db, statement, arguments)

        monkeypatch.setattr(service_module, "_execute", lose)
        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            with pytest.raises(ConformanceError, match="^conflict$"):
                service.execute(staged.actual.request, payload)
        assert worker.completion_count == 6
        with _writer(), staged.domain._connection(write=True) as db:
            row = db.execute("SELECT state,report_sha256,retained_bytes FROM "
                "provider_conformance_runs WHERE command_id=?", (payload["command_id"],)).fetchone()
            assert tuple(row) == ("pending", None, 0)
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind=? AND id=?",
                ("provider_conformance_run", payload["command_id"])).fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM api_event_envelopes WHERE event_type LIKE "
                "'provider.conformance_%'").fetchone()[0] == 1
            assert tuple(db.execute("SELECT run_count,retained_bytes FROM "
                "provider_conformance_control").fetchone()) == (1, 0)


def test_run_scalar_ranges_are_rejected_before_domain_record_materialization(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        monkeypatch.setattr(provider_client.listener, "_connect_extension_authenticated",
            lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit("controlled pending")))
        with pytest.raises(SystemExit, match="controlled pending"):
            service.execute(staged.actual.request, payload)
        with _writer(), staged.domain._connection(write=True) as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute("UPDATE provider_conformance_runs SET deadline_ms=admitted_ms+60001 "
                       "WHERE command_id=?", (payload["command_id"],))
            domain_type = type(staged.domain)
            actual_load = domain_type._load
            loaded = []

            def forbidden_load(*args, **kwargs):
                loaded.append(None)
                raise AssertionError("materialized before scalar refusal")

            monkeypatch.setattr(domain_type, "_load", forbidden_load)
            with pytest.raises(ConformanceError, match="^unavailable$"):
                verify_history(staged.prepare, db)
            assert loaded == []
            monkeypatch.setattr(domain_type, "_load", actual_load)
