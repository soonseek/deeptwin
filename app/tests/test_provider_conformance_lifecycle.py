from uuid import uuid4
from contextlib import contextmanager

import pytest

from app.domain.refs import EntityRef, canonical_json, parse_canonical
from app.domain.store import StorageError, _writer
from app.extensions.provider_conformance_contracts import ConformanceError
from app.extensions import provider_conformance_service as service_module
from app.extensions.provider_conformance_service import PersistentProviderConformance
from app.workers import provider_client
from app.workers.broker import Deadline, DeadlineExceeded
from app.tests.provider_conformance_fixture import staged_conformance_app
from app.tests.provider_conformance_fixture import _provider_conformance_worker


def test_read_and_fresh_execute_preserve_closed_owner_authentication(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        with pytest.raises(ConformanceError) as caught:
            service.read(staged.actual.read_request, str(uuid4()))
        assert caught.value.code == "not_found"
        with pytest.raises(ConformanceError) as caught:
            service.execute(staged.actual.read_request, {"command_id": str(uuid4()),
                "installation_ref": staged.installation_ref.as_dict()})
        assert caught.value.code == "access_denied"


def test_process_control_stays_primary_and_exact_replay_is_frozen_pending(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        calls = []

        def interrupted(*args, **kwargs):
            calls.append((args, kwargs))
            raise KeyboardInterrupt("primary")

        monkeypatch.setattr(provider_client.listener, "_connect_extension_authenticated", interrupted)
        with pytest.raises(KeyboardInterrupt, match="primary") as caught:
            service.execute(staged.actual.request, payload)
        assert type(caught.value) is KeyboardInterrupt
        assert len(calls) == 1
        replay = service.execute(staged.actual.request, payload)
        assert replay["state"] == "pending" and replay["result_ref"] is None
        assert replay["completed_count"] == replay["matched_count"] == 0
        assert len(calls) == 1


@pytest.mark.parametrize("primary_type,cleanup_type", [
    (KeyboardInterrupt, SystemExit), (SystemExit, KeyboardInterrupt)])
def test_process_control_primary_survives_owned_connection_close_failure(
        tmp_path, monkeypatch, primary_type, cleanup_type):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        actual_connect = provider_client.listener._connect_extension_authenticated

        class CloseFails:
            def __init__(self, connection):
                self._connection = connection

            def __getattr__(self, name):
                return getattr(self._connection, name)

            def close(self):
                self._connection.close()
                raise cleanup_type("cleanup")

        def connect(*args, **kwargs):
            return CloseFails(actual_connect(*args, **kwargs))

        checks = []

        def guard():
            checks.append(None)
            if len(checks) == 3:
                raise primary_type("primary")

        monkeypatch.setattr(provider_client.listener, "_connect_extension_authenticated", connect)
        with _provider_conformance_worker(staged.actual, monkeypatch, serve_count=1) as (_, worker):
            with pytest.raises(primary_type, match="primary") as caught:
                provider_client.run_fixed_suite(subject, deadline=Deadline.after_ms(60000),
                                                guard=guard)
            assert type(caught.value) is primary_type
        assert worker.completion_count == 1


def test_ordinary_guard_failure_retains_incomplete_prefix_and_closes_connection(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        checks = []

        def guard():
            checks.append(None)
            if len(checks) == 3:
                raise RuntimeError("controlled ordinary failure")

        with _provider_conformance_worker(staged.actual, monkeypatch, serve_count=1) as (_, worker):
            capture = provider_client.run_fixed_suite(
                subject, deadline=Deadline.after_ms(60000), guard=guard)
        assert worker.completion_count == 1
        comparison = provider_client.compare_capture(subject, capture)
        assert comparison.completion == "incomplete"
        assert comparison.reason == "connection_unavailable"


def test_ordinary_owned_connection_cleanup_failure_is_propagated_after_close(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        actual_connect = provider_client.listener._connect_extension_authenticated
        closed = []

        class CloseFails:
            def __init__(self, connection):
                self._connection = connection

            def __getattr__(self, name):
                return getattr(self._connection, name)

            def close(self):
                self._connection.close()
                closed.append(self)
                raise RuntimeError("controlled ordinary cleanup failure")

        monkeypatch.setattr(provider_client.listener, "_connect_extension_authenticated",
            lambda *args, **kwargs: CloseFails(actual_connect(*args, **kwargs)))
        with _provider_conformance_worker(staged.actual, monkeypatch, serve_count=1) as (_, worker):
            with pytest.raises(RuntimeError, match="controlled ordinary cleanup failure"):
                provider_client.run_fixed_suite(subject, deadline=Deadline.after_ms(60000),
                                                guard=lambda: None)
        assert worker.completion_count == 1
        assert len(closed) == 1


@pytest.mark.parametrize("owner", ["live", "replay"])
@pytest.mark.parametrize("stage", ["acquire", "receive", "finalize"])
@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, RuntimeError])
def test_b_owned_stream_sinks_preserve_primary_and_abort_every_reached(
        monkeypatch, stage, owner, primary_type):
    primary = primary_type("primary")
    reached = []
    aborted = []

    class Sink:
        def __init__(self):
            if stage == "acquire" and reached:
                raise primary
            reached.append(self)

        def abort(self):
            aborted.append(self)
            raise SystemExit("cleanup")

        def finalize(self):
            if stage == "finalize":
                raise primary

        @property
        def value(self):
            return b""

    def receive(transport, descriptors, sinks, *, limits):
        if stage == "receive":
            raise primary
        for sink in sinks:
            sink.finalize()

    monkeypatch.setattr(provider_client, "BytesSink", Sink)
    monkeypatch.setattr(provider_client, "receive_batch", receive)
    descriptions = tuple({"batch_id": str(uuid4()), "size": 0,
        "sha256": __import__("hashlib").sha256(b"").hexdigest(),
        "media_type": "application/json"} for _ in range(2))
    connection = type("Connection", (), {"write": lambda self, **kwargs: None,
                                          "read": lambda self, **kwargs: None})()
    with pytest.raises(primary_type) as caught:
        if owner == "live":
            provider_client._stream(connection, str(uuid4()), descriptions,
                                    Deadline.after_ms(1000))
        else:
            provider_client._replay_stream(
                provider_client._TranscriptCursor([]), str(uuid4()), descriptions)
    assert caught.value is primary
    assert aborted == reached


def test_owner_revocation_after_acquisition_is_retained_and_stops_continuation(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        actual_authenticate = service._authenticate
        calls = []

        def authenticate(request, db, *, read=False):
            calls.append(read)
            if len(calls) == 4:
                raise ConformanceError("access_denied")
            return actual_authenticate(request, db, read=read)

        monkeypatch.setattr(service, "_authenticate", authenticate)
        with _provider_conformance_worker(staged.actual, monkeypatch, serve_count=1,
                                          allow_error=True) as (_, worker):
            reply = service.execute(staged.actual.request, payload)
        assert worker.completion_count == 0
        assert reply["state"] == "incomplete"
        with _writer(), staged.domain._connection(write=True) as db:
            retained = service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
        assert retained.comparison.reason == "owner_revoked"
        capture = __import__("json").loads(retained.capture_bytes)
        assert len(capture["attempts"]) == 1
        assert capture["attempts"][0]["connection"] is not None
        assert capture["attempts"][0]["frames"] == []


def test_durable_clock_floor_regression_refuses_without_admission_or_floor_rewrite(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        now = service_module.time.time_ns() // 1_000_000
        floor = now + 1000
        with _writer(), staged.domain._connection(write=True) as db:
            db.execute("UPDATE provider_conformance_control SET last_now_ms=?", (floor,))
        monkeypatch.setattr(service_module.time, "time_ns", lambda: now * 1_000_000)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        with pytest.raises(ConformanceError, match="^unavailable$"):
            service.execute(staged.actual.request, payload)
        with _writer(), staged.domain._connection(write=True) as db:
            assert db.execute("SELECT last_now_ms FROM provider_conformance_control").fetchone()[0] == floor
            assert db.execute("SELECT count(*) FROM provider_conformance_runs").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind=?",
                              ("provider_conformance_run",)).fetchone()[0] == 0


def test_durable_clock_floor_rollback_is_rejected_by_full_history_verification(
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
            admitted = db.execute("SELECT admitted_ms FROM provider_conformance_runs WHERE "
                                  "command_id=?", (payload["command_id"],)).fetchone()[0]
            assert admitted > 0
            db.execute("UPDATE provider_conformance_control SET last_now_ms=0")
        with pytest.raises(ConformanceError, match="^unavailable$"):
            service.read(staged.actual.read_request, payload["command_id"])


def test_preseal_blob_failure_leaves_one_verified_pending_intent_and_replays_it(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        domain_type = type(staged.domain)
        actual_put_blob = domain_type.put_blob

        def fail_preseal(self, raw, *, purpose):
            raise StorageError("controlled preseal failure")

        monkeypatch.setattr(domain_type, "put_blob", fail_preseal)
        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            with pytest.raises(ConformanceError, match="^unavailable$"):
                service.execute(staged.actual.request, payload)
        assert worker.completion_count == 6
        monkeypatch.setattr(domain_type, "put_blob", actual_put_blob)
        replay = service.execute(staged.actual.request, payload)
        assert replay["state"] == "pending" and replay["result_ref"] is None
        with _writer(), staged.domain._connection(write=True) as db:
            assert db.execute("SELECT count(*) FROM provider_conformance_runs WHERE command_id=?",
                              (payload["command_id"],)).fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind=? AND id=?",
                ("provider_conformance_run", payload["command_id"])).fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM api_event_envelopes WHERE event_type LIKE "
                              "'provider.conformance_%'").fetchone()[0] == 1
            assert tuple(db.execute("SELECT run_count,retained_bytes FROM "
                "provider_conformance_control").fetchone()) == (1, 0)


def test_distinct_expired_attempt_recovers_interrupted_before_honest_source_failure(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        old = {"command_id": str(uuid4()),
               "installation_ref": staged.installation_ref.as_dict()}
        now = [service_module.time.time_ns() // 1_000_000]
        monkeypatch.setattr(service_module.time, "time_ns", lambda: now[0] * 1_000_000)
        monkeypatch.setattr(provider_client.listener, "_connect_extension_authenticated",
            lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit("lost")))
        with pytest.raises(SystemExit, match="lost"):
            service.execute(staged.actual.request, old)

        now[0] += 60_000
        fresh = {"command_id": str(uuid4()),
                 "installation_ref": staged.installation_ref.as_dict()}
        monkeypatch.setattr(service_module, "resolve_subject",
            lambda *args, **kwargs: (_ for _ in ()).throw(ConformanceError("unavailable")))
        with pytest.raises(ConformanceError) as caught:
            service.execute(staged.actual.request, fresh)
        assert caught.value.code == "unavailable"
        recovered = service.read(staged.actual.read_request, old["command_id"])
        assert recovered["state"] == "incomplete"
        with _writer(), staged.domain._connection(write=True) as db:
            retained = service.rehydrate(db, EntityRef.from_dict(recovered["result_ref"]))
            assert db.execute("SELECT 1 FROM provider_conformance_runs WHERE command_id=?",
                              (fresh["command_id"],)).fetchone() is None
        wrong_installation = {**fresh, "installation_ref": {
            **fresh["installation_ref"], "id": str(uuid4())}}
        with pytest.raises(ConformanceError, match="^conflict$"):
            service.execute(staged.actual.request, wrong_installation)
        fake_actor = EntityRef("actor", str(uuid4()), 1, "f" * 64)
        monkeypatch.setattr(service, "_authenticate",
                            lambda request, db, read=False: (object(), fake_actor))
        with pytest.raises(ConformanceError, match="^conflict$"):
            service.execute(staged.actual.request, fresh)
        assert retained.comparison.completion == "incomplete"
        assert retained.comparison.reason == "interrupted"
        assert retained.capture_bytes is None


def test_expired_pending_recovery_remains_possible_at_lifetime_capacity(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        now = [service_module.time.time_ns() // 1_000_000]
        monkeypatch.setattr(service_module.time, "time_ns", lambda: now[0] * 1_000_000)
        monkeypatch.setattr(provider_client.listener, "_connect_extension_authenticated",
            lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit("lost")))
        commands = []
        for index in range(64):
            if index:
                now[0] += 60_000
            payload = {"command_id": str(uuid4()),
                       "installation_ref": staged.installation_ref.as_dict()}
            with pytest.raises(SystemExit, match="lost"):
                service.execute(staged.actual.request, payload)
            commands.append(payload)
        now[0] += 60_000
        rejected = {"command_id": str(uuid4()),
                    "installation_ref": staged.installation_ref.as_dict()}
        with pytest.raises(ConformanceError) as caught:
            service.execute(staged.actual.request, rejected)
        assert caught.value.code == "capacity"
        recovered = service.read(staged.actual.read_request, commands[-1]["command_id"])
        assert recovered["state"] == "incomplete"
        with _writer(), staged.domain._connection(write=True) as db:
            assert tuple(db.execute("SELECT run_count,retained_bytes FROM "
                "provider_conformance_control").fetchone()) == (64, 0)
            assert db.execute("SELECT count(*) FROM provider_conformance_runs WHERE state='pending'").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind=? AND id=?",
                ("provider_conformance_run", rejected["command_id"])).fetchone()[0] == 0


def test_final_wall_deadline_downgrades_complete_observations_without_losing_them(
        tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.tests.provider_conformance_fixture import (
        _retained_provider_conformance_worker, restart_without_provider,
    )

    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        now = [service_module.time.time_ns() // 1_000_000]
        # This test advances the final wall clock, not an earlier IPC deadline.
        # Isolate these clocks from owner authentication and real thread/socket waits.
        clock = SimpleNamespace(time_ns=lambda: now[0] * 1_000_000,
                                monotonic=lambda: 1000.0)
        for module in (service_module, provider_client, provider_client.broker):
            monkeypatch.setattr(module, "time", clock)
        actual_run = service_module.run_fixed_suite
        captures = []

        def expires_after_capture(*args, **kwargs):
            capture = actual_run(*args, **kwargs)
            observations = parse_canonical(capture.content_bytes)
            # Bounded diagnostic metadata only; never expose raw frames/payloads.
            summary = tuple((attempt['role'], attempt['failure'], len(attempt['frames']))
                            for attempt in observations['attempts'])
            assert worker.finished.wait(6), ("worker did not finish before final-wall jump", summary)
            assert worker.completion_count == 6, summary
            assert tuple(attempt["role"] for attempt in observations["attempts"]) == (
                "identify-before", "text-basic-v1", "text-refusal-v1",
                "catalog-two-pages-v1", "catalog-negative-capability-v1", "identify-after")
            assert all(attempt["failure"] is None for attempt in observations["attempts"])
            comparison = provider_client.compare_capture(args[0], capture)
            assert comparison.completion == "matched" and comparison.reason == "compared"
            assert comparison.vectors == (
                ("text-basic-v1", "matched"), ("text-refusal-v1", "matched"),
                ("catalog-two-pages-v1", "matched"),
                ("catalog-negative-capability-v1", "matched"))
            captures.append(capture.content_bytes)
            now[0] += 60_000
            return capture

        monkeypatch.setattr(service_module, "run_fixed_suite", expires_after_capture)
        with _retained_provider_conformance_worker(staged, monkeypatch) as (_, worker):
            reply = service.execute(staged.actual.request, payload)
            assert reply["state"] == "incomplete"
            assert reply["completed_count"] == reply["matched_count"] == 4
            with restart_without_provider(staged, monkeypatch) as reopened:
                assert reopened.actual.context is None
                assert reopened.stopped_worker_completion_count == 6
                with _writer(), reopened.domain._connection(write=True) as db:
                    retained = reopened.service.rehydrate(
                        db, EntityRef.from_dict(reply["result_ref"]))
        assert worker.completion_count == 6
        assert captures == [retained.capture_bytes]
        assert retained.comparison.completion == "incomplete"
        assert retained.comparison.reason == "deadline"
        assert retained.comparison.covered_subchecks == (
            "text-basic-v1", "text-refusal-v1", "catalog-two-pages-v1",
            "catalog-negative-capability-v1")


@pytest.mark.parametrize("final_reason", ["deadline", "source_changed"])
def test_late_finalization_downgrades_actual_mismatch_without_losing_vector_evidence(
        tmp_path, monkeypatch, final_reason):
    from app.workers import provider_service

    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        now = [service_module.time.time_ns() // 1_000_000]
        monkeypatch.setattr(service_module.time, "time_ns", lambda: now[0] * 1_000_000)
        actual_write = provider_service._Dialogue.write

        def wrong_projection(dialogue, value, *, correlation=None):
            if value.get("schema") == "provider-transform-projection-v1":
                value = {**value, "endpoint": "models", "body": None}
            return actual_write(dialogue, value, correlation=correlation)

        monkeypatch.setattr(provider_service._Dialogue, "write", wrong_projection)
        actual_run = service_module.run_fixed_suite
        actual_require = service_module.require_current_subject
        after_capture = [False]

        def expires_after_mismatch(*args, **kwargs):
            capture = actual_run(*args, **kwargs)
            after_capture[0] = True
            if final_reason == "deadline":
                now[0] += 60_000
            return capture

        monkeypatch.setattr(service_module, "run_fixed_suite", expires_after_mismatch)
        if final_reason == "source_changed":
            def source_changes_after_mismatch(*args, **kwargs):
                if after_capture[0]:
                    raise ConformanceError("source_changed")
                return actual_require(*args, **kwargs)

            monkeypatch.setattr(service_module, "require_current_subject",
                                source_changes_after_mismatch)
        with _provider_conformance_worker(staged.actual, monkeypatch, serve_count=2,
                                          allow_error=True) as (_, worker):
            reply = service.execute(staged.actual.request, payload)
        assert worker.completion_count == 1
        assert reply["state"] == "incomplete"
        assert reply["completed_count"] == 1 and reply["matched_count"] == 0
        with _writer(), staged.domain._connection(write=True) as db:
            retained = service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
        assert retained.comparison.completion == "incomplete"
        assert retained.comparison.reason == final_reason
        assert retained.comparison.vectors[0] == ("text-basic-v1", "mismatch")
        assert retained.comparison.covered_subchecks == ()
        if final_reason != "deadline":
            return
        with _writer(), staged.domain._connection(write=True) as db:
            db.execute("PRAGMA defer_foreign_keys=ON")
            db.execute("SAVEPOINT forged_late_mismatch")
            row = db.execute("SELECT report_sha256,finished_sequence,terminal_reply FROM "
                "provider_conformance_runs WHERE command_id=?", (payload["command_id"],)).fetchone()
            body = parse_canonical(db.execute("SELECT body FROM domain_records WHERE kind=? "
                "AND id=? AND version=2", ("provider_conformance_run",
                payload["command_id"])).fetchone()[0])
            body["content"]["completion"] = "mismatch"
            body["content"]["reason"] = "compared"
            raw = canonical_json(body)
            refreshed = __import__("hashlib").sha256(raw).hexdigest()
            db.execute("UPDATE domain_records SET sha256=?,body=? WHERE kind=? AND id=? "
                "AND version=2", (refreshed, raw, "provider_conformance_run",
                payload["command_id"]))
            terminal = parse_canonical(bytes(row["terminal_reply"]))
            terminal["state"] = "mismatch"
            terminal["result_ref"]["sha256"] = refreshed
            db.execute("UPDATE provider_conformance_runs SET state='mismatch',report_sha256=?,"
                "terminal_reply=? WHERE command_id=?", (refreshed, canonical_json(terminal),
                payload["command_id"]))
            event = parse_canonical(db.execute("SELECT envelope FROM api_event_envelopes WHERE "
                "sequence=?", (row["finished_sequence"],)).fetchone()[0])
            event["status"] = "failed"
            event["public_metadata"]["outcome"] = "mismatch"
            event["object_refs"][0]["content_hash"] = refreshed
            event["private_evidence_refs"][0]["sha256"] = refreshed
            db.execute("UPDATE api_event_envelopes SET envelope=? WHERE sequence=?",
                       (canonical_json(event), row["finished_sequence"]))
            with pytest.raises(ConformanceError, match="^unavailable$"):
                service.rehydrate(db, EntityRef("provider_conformance_run",
                    payload["command_id"], 2, refreshed))
            db.execute("ROLLBACK TO forged_late_mismatch")
            db.execute("RELEASE forged_late_mismatch")


def test_final_source_drift_downgrades_complete_observations_without_rebinding_subject(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        actual_run = service_module.run_fixed_suite
        actual_require = service_module.require_current_subject
        after_capture = [False]

        def drift_after_capture(*args, **kwargs):
            capture = actual_run(*args, **kwargs)
            after_capture[0] = True
            return capture

        def require_current(*args, **kwargs):
            if after_capture[0]:
                raise ConformanceError("source_changed")
            return actual_require(*args, **kwargs)

        monkeypatch.setattr(service_module, "run_fixed_suite", drift_after_capture)
        monkeypatch.setattr(service_module, "require_current_subject", require_current)
        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            reply = service.execute(staged.actual.request, payload)
        assert worker.completion_count == 6
        assert reply["state"] == "incomplete"
        assert reply["completed_count"] == reply["matched_count"] == 4
        with _writer(), staged.domain._connection(write=True) as db:
            retained = service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
        assert retained.comparison.completion == "incomplete"
        assert retained.comparison.reason == "source_changed"
        assert retained.subject.installation_ref == staged.installation_ref


@pytest.mark.parametrize("reason", ["deadline", "source_changed"])
def test_requester_stopped_prefix_remains_readable_replayable_and_reopenable(
        tmp_path, monkeypatch, reason):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        actual_run = service_module.run_fixed_suite

        def stopped_run(subject, *, deadline, guard):
            calls = [0]

            def stopped_guard():
                calls[0] += 1
                if calls[0] == 9:
                    if reason == "deadline":
                        raise DeadlineExceeded()
                    raise ConformanceError("source_changed")
                return guard()

            return actual_run(subject, deadline=deadline, guard=stopped_guard)

        monkeypatch.setattr(service_module, "run_fixed_suite", stopped_run)
        with _provider_conformance_worker(staged.actual, monkeypatch, serve_count=2,
                                          allow_error=True) as (_, worker):
            reply = service.execute(staged.actual.request, payload)
        assert worker.completion_count == 1
        assert reply["state"] == "incomplete"
        assert service.read(staged.actual.read_request, payload["command_id"]) == reply
        assert service.execute(staged.actual.request, payload) == reply
        with _writer(), staged.domain._connection(write=True) as db:
            retained = service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
        assert retained.comparison.completion == "incomplete"
        assert retained.comparison.reason == reason
        reopened = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        assert reopened.read(staged.actual.read_request, payload["command_id"]) == reply


@pytest.mark.parametrize("delay_at", ["preseal", "writer-wait", "final-source"])
def test_original_monotonic_deadline_is_rechecked_after_late_finalization_delays(
        tmp_path, monkeypatch, delay_at):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        service = PersistentProviderConformance(staged.domain, staged.actual.owner,
            prepare_service=staged.prepare, source_context=staged.actual.context)
        payload = {"command_id": str(uuid4()),
                   "installation_ref": staged.installation_ref.as_dict()}
        monotonic = [1000.0]
        monkeypatch.setattr(service_module.time, "monotonic", lambda: monotonic[0])
        after_capture = [False]
        delayed = [False]
        actual_run = service_module.run_fixed_suite

        def run(*args, **kwargs):
            capture = actual_run(*args, **kwargs)
            after_capture[0] = True
            return capture

        monkeypatch.setattr(service_module, "run_fixed_suite", run)
        if delay_at == "preseal":
            domain_type = type(staged.domain)
            actual_put_blob = domain_type.put_blob

            def put_blob(self, *args, **kwargs):
                monotonic[0] += 61
                return actual_put_blob(self, *args, **kwargs)

            monkeypatch.setattr(domain_type, "put_blob", put_blob)
        elif delay_at == "writer-wait":
            actual_writer = service_module._writer

            @contextmanager
            def writer():
                if after_capture[0] and not delayed[0]:
                    delayed[0] = True
                    monotonic[0] += 61
                with actual_writer():
                    yield

            monkeypatch.setattr(service_module, "_writer", writer)
        else:
            actual_require = service_module.require_current_subject

            def require(*args, **kwargs):
                if after_capture[0] and not delayed[0]:
                    delayed[0] = True
                    monotonic[0] += 61
                return actual_require(*args, **kwargs)

            monkeypatch.setattr(service_module, "require_current_subject", require)
        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            reply = service.execute(staged.actual.request, payload)
        assert worker.completion_count == 6
        assert reply["state"] == "incomplete"
        assert reply["completed_count"] == reply["matched_count"] == 4
        with _writer(), staged.domain._connection(write=True) as db:
            retained = service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))
            row = db.execute("SELECT admitted_ms,finished_ms FROM provider_conformance_runs "
                             "WHERE command_id=?", (payload["command_id"],)).fetchone()
        capture = __import__("json").loads(retained.capture_bytes)
        assert retained.comparison.reason == "deadline"
        assert capture["started_ms"] == row["admitted_ms"]
        assert row["finished_ms"] >= capture["finished_ms"]
        assert capture["elapsed_ms"] == 0
