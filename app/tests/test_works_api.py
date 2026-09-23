"""The intake's server surface on the supported factory (resumption-plan
Continuation "the intake screen on the supported factory", T023/T025 §5.1): the
`works-v1` route contribution. An owner session creates a work by explaining it
(`POST /api/v1/works`), reads its latest revision (`GET|HEAD /api/v1/works/{id}`)
and revises it under an expected revision (`POST …/{id}/revisions`). Every
revision is an immutable `work_revision` domain record — the very kind a run
names as its input (data-model.md `WorkRevision`; api.md Intake `/works`) — so
the run creation route can reference it. Command replay is idempotent, a reused
command with different content is a conflict, and a stale expected revision is a
conflict (concurrent edits, data-model.md). No model, tool or paid call; no
event, file or source yet.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.refs import EntityRef
from app.server import create_app
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers

CREATE = "work-create-command-v1"
REVISE = "work-revise-command-v1"


@contextmanager
def owner_app(tmp_path, *, executor=None):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments, run_executor=executor)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        yield SimpleNamespace(app=app, client=client, profile=profile, csrf=csrf,
                              domain=app.state.domain_store, path=profile.base_path + "api/v1/works")


def post(subject, body, path=None):
    return subject.client.post(path or subject.path, json=body, headers=headers(subject.profile, subject.csrf))


def create(subject, text="보고서를 요약해 주세요", command_id=None):
    return post(subject, {"schema_version": CREATE, "command_id": command_id or str(uuid4()), "text": text})


def test_an_owner_creates_a_work_and_reads_its_latest_revision(tmp_path):
    with owner_app(tmp_path) as subject:
        created = create(subject, command_id="11111111-1111-4111-8111-111111111111")
        assert created.status_code == 201, created.text
        work = created.json()
        assert set(work) == {"work_id", "revision", "text", "ref", "created_at_utc"}
        assert work["revision"] == 1 and work["text"] == "보고서를 요약해 주세요"
        # the revision is an immutable work_revision record of this vault — the kind a run names
        ref = EntityRef.from_dict(work["ref"])
        assert (ref.kind, ref.id, ref.version) == ("work_revision", work["work_id"], 1)
        record = subject.domain.get(ref)
        assert record.body["content"]["schema_version"] == "work-revision-v1"
        assert record.body["content"]["text"] == work["text"]
        assert record.body["content"]["input_origin"] == "owner_text"
        assert record.body["content"]["source_refs"] == []
        assert record.body["purpose"] == "operational"
        # the work id derives from the command: one work per command, findable from it
        assert work["work_id"] == created.json()["work_id"]
        read = subject.client.get(subject.path + "/" + work["work_id"], headers=headers(subject.profile))
        assert read.status_code == 200 and read.json() == work
        head = subject.client.head(subject.path + "/" + work["work_id"], headers=headers(subject.profile))
        assert head.status_code == 200 and head.content == b""
        assert head.headers.get("content-type") == read.headers.get("content-type")
        assert read.headers["cache-control"] == "no-store"


def test_a_replayed_command_is_idempotent_and_a_reused_one_is_a_conflict(tmp_path):
    with owner_app(tmp_path) as subject:
        command_id = str(uuid4())
        first = create(subject, command_id=command_id)
        again = create(subject, command_id=command_id)
        assert first.status_code == 201 and again.status_code == 201
        assert again.json() == first.json()
        reused = create(subject, text="다른 설명", command_id=command_id)
        assert reused.status_code == 409 and reused.json()["code"] == "conflict"
        # the stored revision is the first command's, untouched
        read = subject.client.get(subject.path + "/" + first.json()["work_id"], headers=headers(subject.profile))
        assert read.json()["text"] == "보고서를 요약해 주세요"


def test_a_revision_needs_the_expected_revision_and_keeps_every_earlier_one(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject).json()
        path = subject.path + "/" + work["work_id"] + "/revisions"
        command_id = str(uuid4())
        revised = post(subject, {"schema_version": REVISE, "command_id": command_id,
                                 "expected_revision": 1, "text": "보고서를 세 문단으로 요약해 주세요"}, path)
        assert revised.status_code == 201, revised.text
        second = revised.json()
        assert second["revision"] == 2 and second["work_id"] == work["work_id"]
        assert EntityRef.from_dict(second["ref"]).version == 2
        record = subject.domain.get(EntityRef.from_dict(second["ref"]))
        assert record.body["parent_refs"] == [work["ref"]]  # the earlier revision stays, linked
        assert subject.domain.get(EntityRef.from_dict(work["ref"])).body["content"]["text"] == work["text"]
        read = subject.client.get(subject.path + "/" + work["work_id"], headers=headers(subject.profile))
        assert read.json() == second
        # a stale expectation is a conflict (another screen revised it first)
        stale = post(subject, {"schema_version": REVISE, "command_id": str(uuid4()),
                               "expected_revision": 1, "text": "다시"}, path)
        assert stale.status_code == 409 and stale.json()["code"] == "conflict"
        # the same command replays; the same command with different content is a conflict
        replay = post(subject, {"schema_version": REVISE, "command_id": command_id,
                                "expected_revision": 1, "text": "보고서를 세 문단으로 요약해 주세요"}, path)
        assert replay.status_code == 201 and replay.json() == second
        reused = post(subject, {"schema_version": REVISE, "command_id": command_id,
                                "expected_revision": 1, "text": "또 다른"}, path)
        assert reused.status_code == 409
        # an unknown work
        missing = post(subject, {"schema_version": REVISE, "command_id": str(uuid4()),
                                 "expected_revision": 1, "text": "x"}, subject.path + "/" + str(uuid4()) + "/revisions")
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"


@pytest.mark.parametrize("body, status", [
    ({"schema_version": CREATE, "command_id": "not-a-uuid", "text": "x"}, 400),
    ({"schema_version": CREATE, "command_id": str(uuid4()), "text": ""}, 400),
    ({"schema_version": CREATE, "command_id": str(uuid4()), "text": 5}, 400),
    ({"schema_version": CREATE, "command_id": str(uuid4()), "text": "x", "extra": 1}, 400),
    ({"schema_version": "other", "command_id": str(uuid4()), "text": "x"}, 400),
    ({"schema_version": CREATE, "command_id": str(uuid4()), "text": "가" * 20_001}, 400),
])
def test_invalid_creations_are_refused_with_the_closed_partition(tmp_path, body, status):
    with owner_app(tmp_path) as subject:
        response = post(subject, body)
        assert response.status_code == status, response.text
        assert response.json()["code"] == "invalid_input"
        assert set(response.json()) == {"code", "message", "retryability", "affected_refs", "correlation_id"}


def test_the_text_bound_is_the_intake_stores_and_an_oversized_body_is_too_large(tmp_path):
    with owner_app(tmp_path) as subject:
        exact = create(subject, text="가" * 20_000)
        assert exact.status_code == 201, exact.text[:200]
        oversized = subject.client.post(subject.path, content=b'{"schema_version":"' + CREATE.encode()
                                        + b'","command_id":"' + str(uuid4()).encode() + b'","text":"'
                                        + b"a" * 90_000 + b'"}',
                                        headers={**headers(subject.profile, subject.csrf),
                                                 "content-type": "application/json"})
        assert oversized.status_code == 413 and oversized.json()["code"] == "too_large"


def test_the_routes_sit_behind_the_owner_boundary(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject).json()
        # a command without the CSRF token, a foreign origin, a query on the path, a wrong method
        no_csrf = subject.client.post(subject.path, json={"schema_version": CREATE, "command_id": str(uuid4()),
                                                          "text": "x"}, headers=headers(subject.profile))
        assert no_csrf.status_code in {401, 403}
        foreign = subject.client.post(subject.path, json={"schema_version": CREATE, "command_id": str(uuid4()),
                                                          "text": "x"},
                                      headers={**headers(subject.profile, subject.csrf), "Origin": "https://evil.test"})
        assert foreign.status_code == 403
        aimed = subject.client.get(subject.path + "/" + work["work_id"] + "?x=1", headers=headers(subject.profile))
        assert aimed.status_code == 400
        put = subject.client.put(subject.path + "/" + work["work_id"], json={}, headers=headers(subject.profile, subject.csrf))
        assert put.status_code == 400
        unknown = subject.client.get(subject.path + "/" + str(uuid4()), headers=headers(subject.profile))
        assert unknown.status_code == 404 and unknown.json()["code"] == "not_found"
        bad_id = subject.client.get(subject.path + "/not-a-uuid", headers=headers(subject.profile))
        assert bad_id.status_code == 400
        # without a session nothing is readable
        subject.client.cookies.clear()
        assert subject.client.get(subject.path + "/" + work["work_id"], headers=headers(subject.profile)).status_code == 401


def test_a_run_can_name_a_work_revision_the_route_sealed(tmp_path):
    # the point of sealing the intake as a work_revision record: the run creation route
    # (runs-v1) resolves it as the run's own input
    from app.tests.test_graph_execution import linear_graph
    from app.tests.test_runs_api import Executor, consent_for, graph_record, immutable
    from app.tests.test_runs_api import owner_app as run_app

    executor = Executor()
    with run_app(tmp_path, executor) as subject:
        created = subject.client.post(subject.profile.base_path + "api/v1/works", headers=headers(subject.profile, subject.csrf),
                                      json={"schema_version": CREATE, "command_id": str(uuid4()), "text": "요약"})
        assert created.status_code == 201, created.text
        work_ref = created.json()["ref"]
        graph_ref = graph_record(subject, linear_graph())
        executor.result = immutable(subject.domain, subject.domain.roots(), "artifact").ref
        started = subject.client.post(subject.path, headers=headers(subject.profile, subject.csrf), json={
            "command_id": str(uuid4()), "graph_ref": graph_ref.as_dict(), "work_revision_ref": work_ref,
            "environment_ref": subject.refs.environment.as_dict(),
            "consent_ref": consent_for(subject, graph_ref, work_ref=work_ref),
            "budget_policy_ref": subject.refs.budget.as_dict()})
        assert started.status_code == 201, started.text


def test_the_composition_carries_the_work_routes(tmp_path):
    with owner_app(tmp_path) as subject:
        composition = subject.app.state.route_composition
        assert "works-v1" in composition.contribution_ids
        for route_id in ("works.create", "works.read", "works.revise"):
            assert route_id in composition.route_ids
        assert composition.route_count == 43


def test_the_text_bound_is_the_records_own_64_kib_and_never_a_storage_outage(tmp_path):
    # review MUST: the domain record's canonical string cap is 65 536 UTF-8 bytes; a text under
    # the character bound but over it was refused as a 503 outage after the transaction rolled
    # back — the wire and the service refuse it as invalid input instead
    with owner_app(tmp_path) as subject:
        admitted = create(subject, text="\U0001F600" * 16_384)  # exactly 65 536 bytes
        assert admitted.status_code == 201, admitted.text[:200]
        refused = create(subject, text="\U0001F600" * 16_385)
        assert refused.status_code == 400 and refused.json()["code"] == "invalid_input", refused.text[:200]


def test_a_chunked_body_meets_the_same_closed_envelope(tmp_path):
    # review MUST: a body without Content-Length streams through the boundary's loop cap;
    # it must be the work envelope (too_large), not a bare code
    with owner_app(tmp_path) as subject:
        def chunks():
            yield b'{"schema_version":"' + CREATE.encode() + b'","command_id":"' + str(uuid4()).encode() + b'","text":"'
            for _ in range(9):
                yield b"a" * 10_000
            yield b'"}'
        oversized = subject.client.post(subject.path, content=chunks(),
                                        headers={**headers(subject.profile, subject.csrf),
                                                 "content-type": "application/json"})
        assert oversized.status_code == 413 and oversized.json()["code"] == "too_large", oversized.text
        assert set(oversized.json()) == {"code", "message", "retryability", "affected_refs", "correlation_id"}
        work = create(subject).json()
        with_body = subject.client.request("GET", subject.path + "/" + work["work_id"], content=iter([b"x"]),
                                           headers=headers(subject.profile))
        assert with_body.status_code == 400 and with_body.json()["code"] == "invalid_input"
        assert set(with_body.json()) == {"code", "message", "retryability", "affected_refs", "correlation_id"}


def test_a_command_names_exactly_one_revision_across_every_work(tmp_path):
    # review SHOULD (api.md: a command reused with a different payload is a conflict): the
    # command's identity is global, not per work and version
    with owner_app(tmp_path) as subject:
        command_id = str(uuid4())
        first = create(subject, command_id=command_id).json()
        other = create(subject).json()
        # the creating command reused to revise another work
        reused = post(subject, {"schema_version": REVISE, "command_id": command_id, "expected_revision": 1,
                                "text": "다른 설명"}, subject.path + "/" + other["work_id"] + "/revisions")
        assert reused.status_code == 409 and reused.json()["code"] == "conflict"
        # a revising command reused as a create, and to revise a third work
        revising = str(uuid4())
        revised = post(subject, {"schema_version": REVISE, "command_id": revising, "expected_revision": 1,
                                 "text": "수정"}, subject.path + "/" + first["work_id"] + "/revisions")
        assert revised.status_code == 201
        assert create(subject, text="수정", command_id=revising).status_code == 409
        third = create(subject).json()
        assert post(subject, {"schema_version": REVISE, "command_id": revising, "expected_revision": 1,
                              "text": "수정"}, subject.path + "/" + third["work_id"] + "/revisions").status_code == 409
        # the replays still hold
        assert post(subject, {"schema_version": REVISE, "command_id": revising, "expected_revision": 1,
                              "text": "수정"}, subject.path + "/" + first["work_id"] + "/revisions").json() == revised.json()
        assert subject.client.get(subject.path + "/" + other["work_id"], headers=headers(subject.profile)).json() == other


@pytest.mark.parametrize("expected", [True, 1.0, 0, -1, "1"])
def test_an_expected_revision_is_an_exact_positive_count(tmp_path, expected):
    with owner_app(tmp_path) as subject:
        work = create(subject).json()
        response = post(subject, {"schema_version": REVISE, "command_id": str(uuid4()), "expected_revision": expected,
                                  "text": "x"}, subject.path + "/" + work["work_id"] + "/revisions")
        assert response.status_code == 400 and response.json()["code"] == "invalid_input"


def test_concurrent_revisions_under_one_expectation_admit_exactly_one(tmp_path):
    import threading

    with owner_app(tmp_path) as subject:
        work = create(subject).json()
        path = subject.path + "/" + work["work_id"] + "/revisions"
        results = []
        barrier = threading.Barrier(8)

        def revise(index):
            barrier.wait()
            results.append(post(subject, {"schema_version": REVISE, "command_id": str(uuid4()),
                                          "expected_revision": 1, "text": f"수정 {index}"}, path).status_code)

        threads = [threading.Thread(target=revise, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert sorted(results) == [201] + [409] * 7
        assert subject.client.get(subject.path + "/" + work["work_id"], headers=headers(subject.profile)).json()["revision"] == 2


def test_a_text_quoting_another_command_never_masks_that_command(tmp_path):
    # the command scan reads canonical bodies, which escape every quote inside a string:
    # a text that spells another command's key is still only text
    with owner_app(tmp_path) as subject:
        other = str(uuid4())
        quoting = create(subject, text=f'{{"command_id":"{other}"}} 를 포함한 설명')
        assert quoting.status_code == 201, quoting.text
        real = create(subject, text="진짜", command_id=other)
        assert real.status_code == 201 and real.json()["text"] == "진짜"
        assert create(subject, text="진짜", command_id=other).json() == real.json()
        assert create(subject, text="가짜", command_id=other).status_code == 409
