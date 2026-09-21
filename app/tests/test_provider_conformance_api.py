from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.domain.store import _writer
from app.extensions import provider_conformance_service as service_module
from app.tests.provider_conformance_fixture import (
    _retained_provider_conformance_worker,
    restart_without_provider,
    staged_conformance_app,
)
from app.tests.test_web_owner_integration import headers
from app.workers.broker import DeadlineExceeded


@pytest.mark.parametrize("portable", [False, True])
def test_owner_runs_fixed_suite_and_reads_actual_record(tmp_path, monkeypatch, portable):
    with staged_conformance_app(tmp_path, monkeypatch, portable=portable) as subject:
        body = {"command_id": str(uuid4()),
                "installation_ref": subject.installation_ref.as_dict()}
        with _retained_provider_conformance_worker(subject, monkeypatch) as (_, worker):
            response = subject.client.post(subject.path, json=body,
                headers=headers(subject.profile, subject.csrf))
            assert response.status_code == 200, response.text
            reply = response.json()
            assert reply["state"] == "matched"
            assert reply["completed_count"] == reply["matched_count"] == 4
            assert worker.completion_count == 6
            read = subject.client.get(reply["links"]["self"], headers=headers(subject.profile))
            assert read.status_code == 200 and read.content == response.content
            head = subject.client.head(reply["links"]["self"], headers=headers(subject.profile))
            assert head.status_code == 200 and head.content == b""
            assert head.headers["content-length"] == read.headers["content-length"]
            replay = subject.client.post(subject.path, json=body,
                headers=headers(subject.profile, subject.csrf))
            assert replay.status_code == 200 and replay.content == response.content
            assert worker.completion_count == 6
            with _writer(), subject.domain._connection(write=True) as db:
                original = subject.service.rehydrate(db, EntityRef.from_dict(reply["result_ref"]))

            with restart_without_provider(subject, monkeypatch) as reopened:
                assert reopened.stopped_worker_completion_count == 6
                with monkeypatch.context() as replay_patch:
                    replay_patch.setattr(service_module.Deadline, "after_ms",
                        classmethod(lambda cls, milliseconds: (_ for _ in ()).throw(
                            AssertionError("replay touched execution deadline"))))
                    read = reopened.client.get(reply["links"]["self"],
                        headers=headers(reopened.profile))
                    assert read.status_code == 200 and read.content == response.content
                    head = reopened.client.head(reply["links"]["self"],
                        headers=headers(reopened.profile))
                    assert head.status_code == 200 and head.content == b""
                    replay = reopened.client.post(reopened.path, json=body,
                        headers=headers(reopened.profile, reopened.csrf))
                    assert replay.status_code == 200 and replay.content == response.content
                assert worker.completion_count == 6
                with _writer(), reopened.domain._connection(write=True) as db:
                    retained = reopened.service.rehydrate(
                        db, EntityRef.from_dict(reply["result_ref"]))
                    before = db.execute("SELECT count(*) FROM provider_conformance_runs").fetchone()[0]
                assert retained.subject == original.subject
                assert retained.comparison == original.comparison
                assert retained.capture_bytes == original.capture_bytes
                fresh = {"command_id": str(uuid4()),
                         "installation_ref": reopened.installation_ref.as_dict()}
                unavailable = reopened.client.post(reopened.path, json=fresh,
                    headers=headers(reopened.profile, reopened.csrf))
                assert unavailable.status_code == 503
                with _writer(), reopened.domain._connection(write=True) as db:
                    after = db.execute("SELECT count(*) FROM provider_conformance_runs").fetchone()[0]
                assert after == before


def test_wire_auth_and_suffix_failures_use_closed_candidate_error(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as subject:
        body = {"command_id": str(uuid4()),
                "installation_ref": subject.installation_ref.as_dict()}
        cases = (
            subject.client.post(subject.path, json={**body, "extra": True},
                headers=headers(subject.profile, subject.csrf)),
            subject.client.post(subject.path, content=b"{}",
                headers={**headers(subject.profile, subject.csrf),
                         "Content-Type": "text/plain"}),
            subject.client.post(subject.path, json=body, headers=headers(subject.profile)),
            subject.client.get(subject.path + "/not-a-uuid", headers=headers(subject.profile)),
            subject.client.get(subject.path + "/" + str(uuid4()), headers=headers(subject.profile)),
        )
        assert [response.status_code for response in cases] == [400, 400, 403, 400, 404]
        for response in cases:
            value = response.json()
            assert set(value) == {"code", "message", "retryability", "affected_refs",
                                  "correlation_id"}
            assert value["message"] == "Provider conformance request could not be admitted"
            assert value["retryability"] == "not_retryable" and value["affected_refs"] == []


@pytest.mark.parametrize("reason", ["deadline", "source_changed"])
def test_stopped_prefix_survives_source_less_http_restart(tmp_path, monkeypatch, reason):
    with staged_conformance_app(tmp_path, monkeypatch) as subject:
        body = {"command_id": str(uuid4()),
                "installation_ref": subject.installation_ref.as_dict()}
        actual_run = service_module.run_fixed_suite

        def stopped_run(conformance_subject, *, deadline, guard):
            calls = [0]

            def stopped_guard():
                calls[0] += 1
                if calls[0] == 9:
                    if reason == "deadline":
                        raise DeadlineExceeded()
                    from app.extensions.provider_conformance_contracts import ConformanceError
                    raise ConformanceError("source_changed")
                return guard()

            return actual_run(conformance_subject, deadline=deadline, guard=stopped_guard)

        monkeypatch.setattr(service_module, "run_fixed_suite", stopped_run)
        with _retained_provider_conformance_worker(
                subject, monkeypatch, serve_count=2, allow_error=True) as (_, worker):
            response = subject.client.post(subject.path, json=body,
                headers=headers(subject.profile, subject.csrf))
            assert response.status_code == 200, response.text
            reply = response.json()
            assert reply["state"] == "incomplete"
            assert worker.completion_count == 1
            with restart_without_provider(subject, monkeypatch) as reopened:
                assert reopened.stopped_worker_completion_count == 1
                path = reply["links"]["self"]
                read = reopened.client.get(path, headers=headers(reopened.profile))
                replay = reopened.client.post(reopened.path, json=body,
                    headers=headers(reopened.profile, reopened.csrf))
                assert read.status_code == replay.status_code == 200
                assert read.content == replay.content == response.content
                assert worker.completion_count == 1
                with _writer(), reopened.domain._connection(write=True) as db:
                    retained = reopened.service.rehydrate(
                        db, EntityRef.from_dict(reply["result_ref"]))
                assert retained.comparison.completion == "incomplete"
                assert retained.comparison.reason == reason


def test_pending_read_and_head_are_successful_reads_not_post_admission_status(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as subject:
        command_id = str(uuid4())
        intent = EntityRef("provider_conformance_run", command_id, 1, "a" * 64)
        pending = subject.service._reply(command_id, subject.installation_ref, intent, None,
            "pending", "b" * 64, 0, 0, "cursor")
        with monkeypatch.context() as route_patch:
            route_patch.setattr(service_module.PersistentProviderConformance, "read",
                                lambda self, request, value: pending)
            path = subject.path + "/" + command_id
            response = subject.client.get(path, headers=headers(subject.profile))
            head = subject.client.head(path, headers=headers(subject.profile))
        assert response.status_code == 200 and response.json()["state"] == "pending"
        assert head.status_code == 200 and head.content == b""
        assert head.headers["content-length"] == response.headers["content-length"]
