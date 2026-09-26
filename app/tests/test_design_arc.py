"""The design arc through the owner's design workspace routes (T038; SC-003/SC-005).

Generation → criticism → the honest pool runs through the product's own drivers and
persistence, with scripted TEST-ACTOR model turns (`design_arc_fixture`), over a real
saved work: 0 / 1 / 2 / 3 presented candidates, a refused model call recorded as a
refusal (never a candidate), an owner's edit realized by a revision generation call and
re-reviewed from scratch, and the owner's cancel stopping the arc before its next model
call. The critic qualification is SIMULATED (test-actor); nothing here is live.
"""

import time
from uuid import uuid4

from app.tests.design_arc_fixture import (
    CRITIC_ID,
    GENERATOR_ID,
    open_scenarios,
    run_in_thread,
)
from app.tests.test_claude_live_path import real_work
from app.tests.test_runs_api import Executor, owner_app
from app.tests.test_web_owner_integration import headers

ROOT = "api/v1/design-requests"


def url(subject, *parts):
    return subject.profile.base_path + "/".join((ROOT, *parts))


def post(subject, request_id, kind, body):
    return subject.client.post(url(subject, request_id, kind), headers=headers(subject.profile, subject.csrf),
                               json={"command_id": str(uuid4()), **body})


def generate(subject, request_id, rounds=3):
    return post(subject, request_id, "generations", {"schema_version": "design-generation-command-v1",
                                                     "max_rounds": rounds})


def read(subject, request_id):
    response = subject.client.get(url(subject, request_id), headers=headers(subject.profile))
    assert response.status_code == 200, response.text
    return response.json()


def work_with_source(subject):
    """A real saved work with one stored original (the work model's source)."""
    from types import SimpleNamespace

    from app.domain.refs import EntityRef
    from app.tests.test_owner_material_intake import metadata, upload

    revision = real_work(subject, "설계 흐름을 시험할 업무입니다.")
    data = "시험용 원본 자료\n".encode()
    target = SimpleNamespace(client=subject.client, profile=subject.profile, csrf=subject.csrf,
                             path=subject.profile.base_path + "api/v1/works")
    response = upload(target, {"work_id": revision.id}, data,
                      metadata(data, name="자료.txt", declared_media_type="text/plain", expected_revision=1))
    assert response.status_code == 201, response.text
    value = response.json()
    return EntityRef.from_dict(value["ref"]), [EntityRef.from_dict(item) for item in value["source_refs"]]


def opened(subject, scenarios, **options):
    revision, sources = work_with_source(subject)
    return open_scenarios(subject.app, revision, sources, scenarios=scenarios, **options)


def test_zero_one_two_three_presented_with_the_real_count_and_every_reason(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        arcs = opened(subject, ("zero", "one", "two", "three"))
        expected = {"zero": (0, 3, "shortfall"), "one": (1, 3, "shortfall"), "two": (2, 3, "shortfall"),
                    "three": (3, 1, "filled")}
        for name, (presented, rounds, outcome) in expected.items():
            request_id = arcs[name]["request"].request_id
            before = read(subject, request_id)
            assert before["generation"]["available"] is True and before["pool"]["candidate_count"] == 0
            response = generate(subject, request_id)
            assert response.status_code == 201, response.text
            run = response.json()
            assert (run["presented_count"], run["rounds"], run["outcome"]) == (presented, rounds, outcome), name
            assert run["generator_model_id"] == GENERATOR_ID and run["critic_model_id"] == CRITIC_ID
            view = read(subject, request_id)
            assert view["pool"]["presented_count"] == presented
            assert view["generation"]["runs"][0]["run_id"] == run["run_id"]
            reasons = [item["reason"] for item in view["pool"]["excluded"]]
            if name == "zero":
                # a malformed answer is a refused call, never a candidate; both graphs rejected
                assert [item["stage"] for item in run["refusals"]] == ["generation"], run["refusals"]
                assert view["pool"]["candidate_count"] == 2 and all(r.startswith("rejected:") for r in reasons)
            if name in ("one", "two"):
                assert reasons and all(r == "structural_duplicate" for r in reasons)
            # every presented candidate's verdict is the recorded one of the scripted critic
            for item in view["candidates"]:
                if item["presented"]:
                    assert item["verdict"]["status"] == "passed" and item["verdict"]["model_ids"] == [CRITIC_ID]
            # model calls: generation rounds plus two per criticized candidate (review, proposal)
            assert run["model_calls"] == rounds + 2 * (view["pool"]["candidate_count"])
        # a replay of the same command returns the same run and calls nothing
        request_id = arcs["three"]["request"].request_id
        body = {"schema_version": "design-generation-command-v1", "command_id": str(uuid4()), "max_rounds": 1}
        first = subject.client.post(url(subject, request_id, "generations"), json=body,
                                    headers=headers(subject.profile, subject.csrf))
        calls = arcs["three"]["generator"].calls
        again = subject.client.post(url(subject, request_id, "generations"), json=body,
                                    headers=headers(subject.profile, subject.csrf))
        assert again.json() == first.json() and arcs["three"]["generator"].calls == calls


def test_an_edit_is_realized_by_a_revision_call_and_re_reviewed_from_scratch(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        arcs = opened(subject, ("three",))
        request_id = arcs["three"]["request"].request_id
        assert generate(subject, request_id).status_code == 201
        view = read(subject, request_id)
        assert view["review"]["realizes"] == ["select", "edit"]
        parent = view["pool"]["presented_candidate_ids"][0]
        edit = post(subject, request_id, "derivations", {"schema_version": "design-derivation-command-v1",
                                                         "action": "edit", "parent_candidate_ids": [parent],
                                                         "instruction": "최종 대본 크기 한도를 절반으로 줄인다"})
        assert edit.status_code == 201 and edit.json()["re_review_required"] is True
        reviewed = post(subject, request_id, "reviews", {"schema_version": "design-review-command-v1",
                                                         "derivation_id": edit.json()["derivation_id"]})
        assert reviewed.status_code == 201, reviewed.text
        value = reviewed.json()
        assert value["re_review_required"] is False and value["inherited_verdict"] is None
        candidate = value["reviewed_candidate"]
        assert candidate["parent_candidate_ids"] == [parent] and candidate["verdict"]["status"] == "passed"
        parent_graph = next(item for item in view["candidates"] if item["candidate_id"] == parent)["graph"]
        assert candidate["graph"]["graph_id"] != parent_graph["graph_id"]
        sizes = {g["artifact_contract_id"]: g["max_total_bytes"] for g in candidate["graph"]["artifact_contracts"]}
        before = {g["artifact_contract_id"]: g["max_total_bytes"] for g in parent_graph["artifact_contracts"]}
        assert sizes["final-script"] == before["final-script"] // 2
        # the revision is the derivation's own: the pool's count is unchanged
        assert read(subject, request_id)["pool"]["candidate_count"] == view["pool"]["candidate_count"]
        merge = post(subject, request_id, "derivations", {"schema_version": "design-derivation-command-v1",
                                                          "action": "merge",
                                                          "parent_candidate_ids": view["pool"]["presented_candidate_ids"][:2],
                                                          "instruction": None}).json()
        refused = post(subject, request_id, "reviews", {"schema_version": "design-review-command-v1",
                                                        "derivation_id": merge["derivation_id"]})
        assert refused.status_code == 503 and refused.json()["reason"] == "derived_graph_not_generated"


def test_the_owner_cancels_before_the_next_model_call(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        arcs = opened(subject, ("cancel",))
        request_id = arcs["cancel"]["request"].request_id
        thread, box = run_in_thread(generate, subject, request_id)
        deadline = time.monotonic() + 30
        while arcs["cancel"]["critic"].reviews < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert read(subject, request_id)["generation"]["running"] is True
        cancelled = post(subject, request_id, "cancellations", {"schema_version": "design-generation-cancel-command-v1"})
        assert cancelled.status_code == 201 and cancelled.json()["state"] == "cancel_requested"
        thread.join(30)
        run = box["value"].json()
        assert run["outcome"] == "cancelled"
        assert len(run["candidate_ids"]) == 3 and len(run["unreviewed_candidate_ids"]) == 2
        # 1 generation + 2 calls for the first candidate + the review of the second
        assert run["model_calls"] == 4 and arcs["cancel"]["critic"].calls == 3
        view = read(subject, request_id)
        assert view["pool"]["presented_count"] == 1
        assert sorted(item["reason"] for item in view["pool"]["excluded"]) == ["unreviewed", "unreviewed"]
        assert view["generation"]["running"] is False
        idle = post(subject, request_id, "cancellations", {"schema_version": "design-generation-cancel-command-v1"})
        assert idle.json()["state"] == "not_running"


def test_generation_is_unavailable_without_registered_turns(tmp_path):
    from app.tests.design_workspace_fixture import open_seeded

    with owner_app(tmp_path, Executor()) as subject:
        request, _roles = open_seeded(subject.app)
        view = read(subject, request.request_id)
        assert view["generation"] | {"runs": None} == {
            "available": False, "reason": "generator_model_not_configured", "generator_model_id": None,
            "critic_model_id": None, "max_rounds": 3, "running": False, "cancel_requested": False, "runs": None}
        refused = generate(subject, request.request_id)
        assert refused.status_code == 503 and refused.json()["reason"] == "generator_model_not_configured"
        bad = generate(subject, request.request_id, rounds=4)
        assert bad.status_code == 400


def test_a_refused_review_answer_is_persisted_with_its_exact_violation(tmp_path):
    """T038 diagnosis: a critic answer the contract refuses is recorded as a refusal of that
    round (the candidate stays unreviewed), and its raw text and the exact rule it broke are
    persisted on the candidate, so the cause is readable after the run."""
    import json

    from app.tests.design_arc_fixture import ScriptedCritic

    class Uncited(ScriptedCritic):
        def __call__(self, system, user):
            answer = super().__call__(system, user)
            if "lens_pack" in json.loads(user)["input"]:
                return answer
            value = json.loads(answer)
            value["findings"][0]["evidence"][0]["location"] = "research 노드의 책임 문장"
            return json.dumps(value, ensure_ascii=False)

    with owner_app(tmp_path, Executor()) as subject:
        arcs = opened(subject, ("one",))
        request = arcs["one"]["request"]
        workspace = subject.app.state.first_party_exports["design-workspace.service"]
        registration = workspace._requests[request.request_id]
        workspace.open_request(request, registry=registration.registry, criticism_turn=Uncited(),
                               critic_model_id=CRITIC_ID, generation_turn=arcs["one"]["generator"],
                               generator_model_id=GENERATOR_ID)
        run = generate(subject, request.request_id, rounds=1).json()
        assert run["presented_count"] == 0 and run["unreviewed_candidate_ids"] == run["candidate_ids"]
        refusal = run["refusals"][0]
        assert refusal["stage"] == "criticism" and refusal["purpose"] == "review"
        assert refusal["reason"] == "the review response violates the contract"
        assert refusal["violation"].startswith("citation is not visible: /findings/0/evidence/0")
        stored = workspace.criticism_refusals(request.request_id)
        assert [item["record_id"] for item in stored] == [refusal["refusal_record_id"]]
        assert stored[0]["violation"] == refusal["violation"]
        assert "research 노드의 책임 문장" in stored[0]["response_text"]
        assert stored[0]["candidate_id"] == run["candidate_ids"][0] and stored[0]["response_truncated"] is False
        view = read(subject, request.request_id)
        assert view["pool"]["excluded"] == [{"candidate_id": run["candidate_ids"][0], "reason": "unreviewed"}]
