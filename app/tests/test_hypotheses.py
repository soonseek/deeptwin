"""Competing explanations of an observed difference over the supported app (US5, FR-018),
against a mock transport.

A real run (the Claude executor on a mock transport) produces the writer's text; the owner
freezes their own version; the framework observes the difference; then — only when the
owner asks — one model turn proposes competing hypotheses, which the framework admits only
through `propose_hypotheses` and seals once per difference, all `proposed`.
"""

import json
from uuid import uuid4

import httpx2

from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
from app.services.run_artifacts import artifact_identity
from app.tests.test_alternative_drafts_api import freeze, save
from app.tests.test_claude_api import Spy, complete_text_stream, model, model_page, response
from app.tests.test_claude_design_turn import EFFORTS
from app.tests.test_claude_live_path import connected, live_graph, messages, real_work, start
from app.tests.test_runs_api import events, owner_app, post
from app.tests.test_web_owner_integration import headers

WRITER_TEXT = "첫 줄\n둘째 줄\n셋째 줄\n"
COMPETING = json.dumps({"hypotheses": [
    {"family": "system", "claim": "작성 노드가 원자료의 표현 규칙을 받지 못했다.",
     "conditions": ["인계가 요약뿐일 때"], "predictions": ["규칙을 인계하면 차이가 사라진다"]},
    {"family": "expert_judgment", "claim": "소유자는 둘째 줄을 더 구체적으로 쓴다.",
     "conditions": [], "predictions": ["다른 문서에서도 같은 수정이 나타난다"]},
]}, ensure_ascii=False)


def transport(diagnosis_answer):
    def responder(request, body):
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model(capabilities=EFFORTS)]))
        answer = diagnosis_answer if b"diagnosis worker" in body else WRITER_TEXT
        return response(request, body=complete_text_stream(answer), headers={"content-type": "text/event-stream"})

    spy = Spy(responder)
    return spy, httpx2.MockTransport(spy)


def observed_difference(subject):
    choice = connected(subject)
    _body, started = start(subject, live_graph(subject, choice), real_work(subject))
    receipt = started.json()
    run_id = receipt["run_id"]
    writer = dict(receipt["outcome"]["execution_ids"])["writer"]
    from app.domain.refs import EntityRef
    artifact_id = artifact_identity(EntityRef.from_dict(dict(receipt["outcome"]["result_refs"])[writer]), 0)
    subject.path = subject.profile.base_path + "api/v1/runs"
    draft = save(subject, run_id, artifact_id, format="text", text="첫 줄\n고친 둘째 줄\n셋째 줄\n")
    assert draft.status_code in (200, 201), draft.text
    frozen = freeze(subject, run_id, artifact_id, draft.json()["draft_id"], 1)
    assert frozen.status_code in (200, 201), frozen.text
    alternative_id = frozen.json()["alternative_ref"]["id"]
    path = f"{subject.path}/{run_id}/artifacts/{artifact_id}/alternatives/{alternative_id}/difference"
    observed = post(subject, {}, path)
    assert observed.status_code == 201, observed.text
    return choice, observed.json()


def hypotheses_path(subject, difference_id):
    return subject.profile.base_path + f"api/v1/differences/{difference_id}/hypotheses"


def propose_body(choice):
    return {"schema_version": "hypotheses-propose-command-v1", "command_id": str(uuid4()),
            "model_choice_ref": choice}


def test_competing_explanations_are_made_on_request_admitted_and_sealed_once(tmp_path):
    spy, mock = transport(COMPETING)
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=5), transport=mock)
    with owner_app(tmp_path, executor) as subject:
        choice, difference = observed_difference(subject)
        path = hypotheses_path(subject, difference["difference_ref"]["id"])
        before = subject.client.get(path, headers=headers(subject.profile))
        assert before.status_code == 200 and before.json()["state"] == "not_generated"
        assert len(messages(spy)) == 1  # only the run's writer call so far
        made = subject.client.post(path, json=propose_body(choice), headers=headers(subject.profile, subject.csrf))
        assert made.status_code == 200, made.text
        value = made.json()
        assert value["state"] == "proposed" and [item["family"] for item in value["hypotheses"]] == [
            "system", "expert_judgment"]
        assert all(item["status"] == "proposed" for item in value["hypotheses"])
        # the prompt carried the observations and both text versions, nothing else
        _request, raw = messages(spy)[-1]
        sent = json.dumps(json.loads(raw), ensure_ascii=False)
        assert "고친 둘째 줄" in sent and "text_change" in sent
        assert [item["public_metadata"] for item in events(subject, "hypothesis.updated")] == [{"revision": 1}]
        # one set per difference: asking again never calls again
        again = subject.client.post(path, json=propose_body(choice), headers=headers(subject.profile, subject.csrf))
        assert again.json() == value and len(messages(spy)) == 2
        assert subject.client.get(path, headers=headers(subject.profile)).json() == value


def test_a_lone_causal_family_is_refused_and_nothing_is_sealed(tmp_path):
    lone = json.dumps({"hypotheses": [
        {"family": "system", "claim": "a", "conditions": [], "predictions": []},
        {"family": "system", "claim": "b", "conditions": [], "predictions": []}]})
    _spy, mock = transport(lone)
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=5), transport=mock)
    with owner_app(tmp_path, executor) as subject:
        choice, difference = observed_difference(subject)
        path = hypotheses_path(subject, difference["difference_ref"]["id"])
        refused = subject.client.post(path, json=propose_body(choice), headers=headers(subject.profile, subject.csrf))
        assert refused.status_code == 422 and refused.json()["code"] == "model_output_invalid"
        assert subject.client.get(path, headers=headers(subject.profile)).json()["state"] == "not_generated"
        extra = {**propose_body(choice), "family": "system"}
        assert subject.client.post(path, json=extra, headers=headers(subject.profile, subject.csrf)).status_code == 400
        absent = hypotheses_path(subject, str(uuid4()))
        assert subject.client.get(absent, headers=headers(subject.profile)).status_code == 404
