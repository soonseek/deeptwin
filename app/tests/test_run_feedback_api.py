"""The owner's process feedback on a run (`run-feedback-v1`, UI phase 4;
docs/ui/2026-09-26-product-ux-redesign.md §6; decisions.md 2026-09-26, the owner's decision on
process feedback).

`GET|HEAD /api/v1/runs/{run_id}/feedback` reads every target's latest revision and the whole
history; `POST` sets or clears one target's feedback — an optional mark (`ok` /
`needs_attention`) and an optional memo of at most 4,000 characters, at least one of them — as
a new immutable revision, through the owner-command path (CSRF-verified POST, one command id,
the record and its `feedback.recorded` event in one transaction). A target is the run as a
whole or one node's exact visit and attempt, and it must exist in the run's own trace. No
explanation is ever asked for, and feedback is never an alternative: nothing that counts
alternatives counts it. Synthetic test-actor data; the fake transport only.
"""

import io
import json
import zipfile
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.services.runs import run_identity
from app.tests.test_run_trace_api import artifact_record, node, recovered_run, trace
from app.tests.test_runs_api import (
    AttemptExecutor,
    Executor,
    FlakyTransport,
    command,
    consent_for,
    graph_record,
    owner_app,
    post,
)
from app.tests.test_graph_execution import linear_graph
from app.tests.test_web_owner_integration import headers

SCHEMA = "process-feedback-command-v1"


def feedback(subject, run_path, *, target, mark=None, memo=None, expected=0, action="set", command_id=None,
             csrf=True):
    body = {"schema_version": SCHEMA, "command_id": command_id or str(uuid4()), "action": action,
            "target": target, "expected_revision": expected, "mark": mark, "memo": memo}
    return subject.client.post(run_path + "/feedback", json=body,
                               headers=headers(subject.profile, subject.csrf if csrf else None))


def listing(subject, run_path):
    response = subject.client.get(run_path + "/feedback", headers=headers(subject.profile))
    assert response.status_code == 200, response.text
    return response.json()


RUN = {"scope": "run"}


def step(node_id, visit_no=1, attempt_no=None):
    return {"scope": "step", "node_id": node_id, "visit_no": visit_no, "attempt_no": attempt_no}


def events(subject, **query):
    response = subject.client.get(subject.profile.base_path + "api/v1/events", params={"limit": 100, **query},
                                  headers=headers(subject.profile))
    assert response.status_code == 200, response.text
    return [item for item in response.json()["events"] if item["event_type"] == "feedback.recorded"]


@pytest.fixture
def recovered(tmp_path):
    transport = FlakyTransport(failures=1)
    executor = AttemptExecutor(transport)
    with owner_app(tmp_path, executor) as subject:
        run_id, run_path = recovered_run(subject, executor, transport)
        yield subject, run_id, run_path


def test_set_change_clear_and_the_history_is_kept(recovered):
    subject, run_id, run_path = recovered
    # the whole run marked 확인 필요 with no memo at all: no reason is asked for
    first = feedback(subject, run_path, target=RUN, mark="needs_attention")
    assert first.status_code == 201, first.text
    recorded = first.json()["recorded"]
    assert (recorded["revision"], recorded["state"], recorded["mark"], recorded["memo"]) == (
        1, "set", "needs_attention", None)
    assert first.headers["cache-control"] == "no-store"
    # attempt 1 of the writer (the failed one) with a mark and a memo; a memo alone is complete too
    memo = "시도 1은 입력을 제대로 받았습니다.\n두 번째 줄."
    attempt = feedback(subject, run_path, target=step("writer", 1, 1), mark="ok", memo=memo)
    assert attempt.status_code == 201, attempt.text
    alone = feedback(subject, run_path, target=step("intake", 1, None), memo="메모만 남깁니다")
    assert alone.status_code == 201 and alone.json()["recorded"]["mark"] is None
    # a change is a new revision over the one it was made from
    changed = feedback(subject, run_path, target=RUN, mark="ok", memo="다시 보니 괜찮습니다", expected=1)
    assert changed.status_code == 201 and changed.json()["recorded"]["revision"] == 2
    # a stale screen (still at revision 1) is refused, never silently wins
    stale = feedback(subject, run_path, target=RUN, mark="needs_attention", expected=1)
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"
    fresh = feedback(subject, run_path, target=step("publish", 1, None), mark="ok", expected=1)
    assert fresh.status_code == 409  # nothing to change yet: revision 0 is the start
    # a clear is a new revision, not a deletion
    cleared = feedback(subject, run_path, target=step("writer", 1, 1), action="clear", expected=1)
    assert cleared.status_code == 201, cleared.text
    assert (cleared.json()["recorded"]["revision"], cleared.json()["recorded"]["state"]) == (2, "cleared")
    again = feedback(subject, run_path, target=step("writer", 1, 1), action="clear", expected=2)
    assert again.status_code == 400  # nothing left to clear
    # after a clear the target can be set again from the cleared revision
    reset = feedback(subject, run_path, target=step("writer", 1, 1), mark="needs_attention", expected=2)
    assert reset.status_code == 201 and reset.json()["recorded"]["revision"] == 3

    value = listing(subject, run_path)
    assert value["schema_version"] == "process-feedback-list-v1" and value["run_id"] == run_id
    assert value["memo_max_chars"] == 4000 and value["marks"] == ["ok", "needs_attention"]
    current = value["current"]
    assert (current["run"]["revision"], current["run"]["mark"], current["run"]["memo"]) == (2, "ok", "다시 보니 괜찮습니다")
    assert [(item["target"]["node_id"], item["target"]["attempt_no"], item["revision"], item["state"], item["mark"])
            for item in current["steps"]] == [("intake", None, 1, "set", None),
                                              ("writer", 1, 3, "set", "needs_attention")]
    history = value["history"]
    assert len(history) == 6
    writer = [item for item in history if item["target"] == step("writer", 1, 1)]
    assert [(item["revision"], item["state"], item["memo"]) for item in writer] == [
        (1, "set", memo), (2, "cleared", None), (3, "set", None)]
    # every revision is its own immutable record: n links to n-1, the first to the run manifest
    records = [subject.domain.get(EntityRef.from_dict(item["ref"])) for item in writer]
    assert records[1].body["parent_refs"] == [records[0].ref.as_dict()]
    assert records[2].body["parent_refs"] == [records[1].ref.as_dict()]
    manifest = subject.domain.get(EntityRef.from_dict(records[0].body["parent_refs"][0]))
    assert manifest.ref.kind == "run_manifest" and manifest.body["content"]["run_id"] == run_id
    assert records[0].ref.kind == "process_feedback"

    head = subject.client.head(run_path + "/feedback", headers=headers(subject.profile))
    assert head.status_code == 200 and head.content == b""


def test_a_command_id_is_idempotent_and_never_reused_for_another_body(recovered):
    subject, _run_id, run_path = recovered
    command_id = str(uuid4())
    first = feedback(subject, run_path, target=RUN, mark="ok", command_id=command_id)
    replay = feedback(subject, run_path, target=RUN, mark="ok", command_id=command_id)
    assert first.status_code == replay.status_code == 201
    assert replay.json()["replayed"] is True and first.json()["replayed"] is False
    assert replay.json()["recorded"] == first.json()["recorded"]
    other = feedback(subject, run_path, target=RUN, mark="needs_attention", command_id=command_id)
    assert other.status_code == 409
    assert len(listing(subject, run_path)["history"]) == 1
    assert len(events(subject)) == 1  # a replay emits nothing


def test_validation_refuses_empty_oversize_and_unknown_targets(recovered):
    subject, _run_id, run_path = recovered
    codes = {}
    for name, kwargs in {
        "neither": {"target": RUN},
        "blank memo": {"target": RUN, "memo": "  \n\t "},
        "control": {"target": RUN, "memo": "a\x00b"},
        "unknown mark": {"target": RUN, "mark": "great"},
        "clear with a mark": {"target": RUN, "mark": "ok", "action": "clear"},
        "unknown action": {"target": RUN, "mark": "ok", "action": "delete"},
        "run target with a node": {"target": {"scope": "run", "node_id": "writer"}, "mark": "ok"},
        "bad node id": {"target": step("Writer!"), "mark": "ok"},
        "visit zero": {"target": step("writer", 0, 1), "mark": "ok"},
    }.items():
        response = feedback(subject, run_path, **kwargs)
        codes[name] = (response.status_code, response.json()["code"])
    assert set(codes.values()) == {(400, "invalid_input")}, codes
    # the memo is bounded: 4,000 characters are accepted, one more is too large
    assert feedback(subject, run_path, target=RUN, memo="가" * 4000).status_code == 201
    over = feedback(subject, run_path, target=step("intake"), memo="가" * 4001)
    assert over.status_code == 413 and over.json()["code"] == "too_large"
    huge = subject.client.post(run_path + "/feedback", content=b'{"memo":"' + b"a" * 70_000 + b'"}',
                               headers={**headers(subject.profile, subject.csrf), "content-type": "application/json"})
    assert huge.status_code == 413
    extra = subject.client.post(run_path + "/feedback", json={
        "schema_version": SCHEMA, "command_id": str(uuid4()), "action": "set", "target": RUN,
        "expected_revision": 0, "mark": "ok", "memo": None, "reason": "why"},
        headers=headers(subject.profile, subject.csrf))
    assert extra.status_code == 400
    # an unknown run, node, visit or attempt is refused; a visit's attempts are exact
    unknown_run = subject.path + "/" + str(uuid4())
    assert feedback(subject, unknown_run, target=RUN, mark="ok").status_code == 404
    for target in (step("nowhere"), step("writer", 2, 1), step("writer", 1, 3),
                   step("writer", 1, None),   # the writer has ledger attempts: one must be named
                   step("intake", 1, 1)):     # the intake ran in-process: it has none
        response = feedback(subject, run_path, target=target, mark="ok")
        assert response.status_code == 404, (target, response.text)
    assert subject.client.get(unknown_run + "/feedback", headers=headers(subject.profile)).status_code == 404
    assert subject.client.get(subject.path + "/not-a-uuid/feedback", headers=headers(subject.profile)).status_code == 400
    assert subject.client.get(run_path + "/feedback?x=1", headers=headers(subject.profile)).status_code == 400
    assert len(listing(subject, run_path)["history"]) == 1  # only the accepted 4,000-character memo


def test_the_routes_are_owner_commands_behind_csrf_and_the_browser_session(recovered):
    subject, _run_id, run_path = recovered
    no_csrf = feedback(subject, run_path, target=RUN, mark="ok", csrf=False)
    assert no_csrf.status_code in {401, 403}
    foreign = subject.client.post(run_path + "/feedback", json={
        "schema_version": SCHEMA, "command_id": str(uuid4()), "action": "set", "target": RUN,
        "expected_revision": 0, "mark": "ok", "memo": None},
        headers={**headers(subject.profile, subject.csrf), "Origin": "https://evil.test"})
    assert foreign.status_code == 403
    bearer = {**headers(subject.profile, subject.csrf), "Authorization": "Bearer " + "A" * 43}
    assert subject.client.get(run_path + "/feedback", headers=bearer).status_code == 401
    assert subject.client.post(run_path + "/feedback", headers=bearer, json={
        "schema_version": SCHEMA, "command_id": str(uuid4()), "action": "set", "target": RUN,
        "expected_revision": 0, "mark": "ok", "memo": None}).status_code == 401
    put = subject.client.put(run_path + "/feedback", json={}, headers=headers(subject.profile, subject.csrf))
    assert put.status_code in {400, 405}
    assert listing(subject, run_path)["history"] == []
    subject.client.cookies.clear()
    assert subject.client.get(run_path + "/feedback", headers=headers(subject.profile)).status_code == 401


def test_each_revision_emits_one_public_event_without_the_memo(recovered):
    subject, run_id, run_path = recovered
    memo = "공개 사건에는 들어가지 않는 메모"
    assert feedback(subject, run_path, target=step("writer", 1, 2), mark="needs_attention", memo=memo).status_code == 201
    assert feedback(subject, run_path, target=step("writer", 1, 2), action="clear", expected=1).status_code == 201
    assert feedback(subject, run_path, target=RUN, memo=memo).status_code == 201
    found = events(subject)
    assert [item["public_metadata"] for item in found] == [
        {"scope": "step", "mark": "needs_attention", "memo": True, "cleared": False, "revision": 1},
        {"scope": "step", "mark": "none", "memo": False, "cleared": True, "revision": 2},
        {"scope": "run", "mark": "none", "memo": True, "cleared": False, "revision": 1}]
    assert all(item["status"] == "succeeded" for item in found)
    assert all({"kind": "run", "id": run_id} in item["object_refs"] for item in found)
    assert memo not in json.dumps(found, ensure_ascii=False)
    # the run's own filtered log carries them (they name the run)
    assert len(events(subject, run_id=run_id)) == 3


def test_the_trace_carries_the_feedback_beside_the_attempt_it_is_about(recovered):
    subject, run_id, run_path = recovered
    assert feedback(subject, run_path, target=RUN, mark="needs_attention").status_code == 201
    assert feedback(subject, run_path, target=step("writer", 1, 1), mark="ok", memo="시도 1 메모").status_code == 201
    assert feedback(subject, run_path, target=step("publish", 1, None), mark="needs_attention").status_code == 201
    assert feedback(subject, run_path, target=step("publish", 1, None), action="clear", expected=1).status_code == 201
    value = trace(subject, run_path).json()
    assert value["feedback"]["run"]["mark"] == "needs_attention"
    assert value["links"]["feedback"].endswith(f"/api/v1/runs/{run_id}/feedback")
    writer = node(value, "writer")["visits"][0]
    first, second = writer["attempts"]
    assert (first["feedback"]["mark"], first["feedback"]["memo"]) == ("ok", "시도 1 메모")
    assert second["feedback"] is None and writer["feedback"] is None
    # a cleared target keeps its revision in `steps` and shows null in place
    publish = node(value, "publish")["visits"][0]
    assert publish["feedback"] is None
    assert [(item["target"]["node_id"], item["state"]) for item in value["feedback"]["steps"]] == [
        ("publish", "cleared"), ("writer", "set")]


def test_feedback_is_never_counted_as_an_alternative(tmp_path):
    from app.runtime.compiler import ChangeCompilerError
    from app.services.knowledge import KnowledgeError, _ref
    from app.tests.test_works_api import CREATE

    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        works = subject.profile.base_path + "api/v1/works"
        work = post(subject, {"schema_version": CREATE, "command_id": str(uuid4()), "text": "피드백을 남길 업무"},
                    works).json()
        executor.result = artifact_record(subject.domain, "합성 보고서\n첫 줄\n", role="report")
        graph_ref = graph_record(subject, linear_graph())
        body = command(subject, graph_ref, work_revision_ref=work["ref"],
                       consent_ref=consent_for(subject, graph_ref, work_ref=work["ref"]))
        assert post(subject, body).status_code == 201
        run_id = run_identity(body["command_id"])
        run_path = subject.path + "/" + run_id
        assert feedback(subject, run_path, target=RUN, mark="needs_attention", memo="결과 전체가 이상합니다").status_code == 201
        assert feedback(subject, run_path, target=step("publish"), mark="ok", memo="이 단계는 괜찮습니다").status_code == 201

        # no alternative, draft, difference, hypothesis or inquiry record exists, and no such event
        with subject.domain._connection() as db:
            kinds = {row[0] for row in db.execute("SELECT DISTINCT kind FROM domain_records").fetchall()}
            types = {row[0] for row in db.execute("SELECT DISTINCT event_type FROM api_event_envelopes").fetchall()}
        assert "process_feedback" in kinds
        assert not kinds & {"own_alternative", "difference", "hypothesis", "inquiry", "selector", "change_candidate"}
        assert not types & {"alternative.saved", "difference.observed", "hypothesis.updated", "inquiry.frozen"}
        # the final artifact has no draft of the owner's version
        [final] = trace(subject, run_path).json()["final_results"]
        drafts = subject.client.get(f"{run_path}/artifacts/{final['artifact_id']}/drafts",
                                    headers=headers(subject.profile))
        assert drafts.status_code == 200 and drafts.json()["drafts"] == []

        # the work export: "alternatives" states none; the feedback is a run event, memo excluded
        preview = post(subject, {"schema_version": "work-export-preview-v1", "request_id": str(uuid4()),
                                 "categories": ["alternatives", "events"], "include_raw": False},
                       f"{works}/{work['work_id']}/exports/preview")
        assert preview.status_code == 200, preview.text
        shown = preview.json()
        reasons = {entry["category"]: entry["reason"] for entry in shown["missing"]}
        assert reasons["alternatives"] == "not_recorded"
        assert not [item for item in shown["items"] if item["category"] == "alternatives"]
        [item] = [item for item in shown["items"] if item["relative_path"] == "events/run-feedback.json"]
        assert item["content_mode"] == "metadata_only" and item["label"].startswith("실행 과정 피드백 기록 2건")
        receipt = post(subject, {"schema_version": "work-export-confirm-v1", "request_id": shown["request_id"],
                                 "categories": shown["categories"], "include_raw": False,
                                 "preview_sha": shown["preview_sha"], "confirmed": True},
                       f"{works}/{work['work_id']}/exports")
        assert receipt.status_code == 201, receipt.text
        bundle = subject.client.get(f"{works}/{work['work_id']}/exports/{receipt.json()['bundle_id']}",
                                    headers=headers(subject.profile))
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            names = archive.namelist()
            exported = json.loads(archive.read("events/run-feedback.json"))
        assert not [name for name in names if name.startswith("alternatives/")]
        assert [(entry["target"]["scope"], entry["mark"], entry["memo_characters"]) for entry in exported["revisions"]] == [
            ("run", "needs_attention", len("결과 전체가 이상합니다")), ("step", "ok", len("이 단계는 괜찮습니다"))]
        assert "결과 전체가 이상합니다" not in bundle.content.decode("utf-8", "replace")

        # a feedback record is an observation, never ground truth: it is refused as memory
        # provenance, as a change candidate's evidence and as knowledge
        listed = subject.client.get(run_path + "/feedback", headers=headers(subject.profile)).json()
        ref = listed["current"]["run"]["ref"]
    from app.runtime.compiler import compile_change_candidate
    from app.runtime.memory import MemoryCompilationError, compile_knowledge
    from app.tests.test_change_compiler import EVIDENCE, LEAK, patch_value, supported_inquiry
    from app.tests.test_memory_compilation import compilation_value, entry

    value = compilation_value()
    value["fields"]["instruction"]["provenance"] = [ref]
    with pytest.raises(MemoryCompilationError, match="never enter a policy"):
        compile_knowledge(entry(), value)
    _accepted, inquiry = supported_inquiry()
    smuggled = patch_value()
    smuggled["condition"]["evidence_refs"] = [EVIDENCE, ref]
    with pytest.raises(ChangeCompilerError, match="never enters a candidate"):
        compile_change_candidate(inquiry, smuggled, forbidden_spans=LEAK)
    with pytest.raises(KnowledgeError, match="draft-store"):
        _ref(ref, frozenset({"process_feedback"}), "evidence")
