"""The owner's inquiry over an observed difference over the supported app (US5, T060), against
a mock transport.

A real run (the Claude executor on a mock transport) writes a text; the owner freezes their
own version; the framework observes the difference; the owner asks for competing
explanations (one scripted model turn). Then only the owner's own requests open the inquiry,
answer or skip its questions, supply evidence and judge hypotheses; a confirmed hypothesis
yields a change candidate *proposal* that is never applied. Nothing is ever recorded as a
human answer without the owner's own input. Scripted test actor only.
"""

import json
from uuid import uuid4

import httpx2

from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
from app.tests.test_claude_api import Spy, complete_text_stream, model, model_page, response
from app.tests.test_claude_design_turn import EFFORTS
from app.tests.test_claude_live_path import messages
from app.tests.test_hypotheses import COMPETING, WRITER_TEXT, hypotheses_path, observed_difference, propose_body
from app.tests.test_runs_api import events, owner_app
from app.tests.test_web_owner_integration import headers

QUESTIONS = json.dumps({"questions": [
    {"text": "다른 보고서에서도 둘째 줄을 이렇게 고치십니까?", "hypothesis_ids": ["system-0", "expert_judgment-1"]},
]}, ensure_ascii=False)


def transport(diagnosis=COMPETING, questions=QUESTIONS):
    def responder(request, body):
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model(capabilities=EFFORTS)]))
        if b"diagnosis worker" in body:
            answer = diagnosis
        elif b"inquiry worker" in body:
            answer = questions
        else:
            answer = WRITER_TEXT
        return response(request, body=complete_text_stream(answer), headers={"content-type": "text/event-stream"})

    spy = Spy(responder)
    return spy, httpx2.MockTransport(spy)


def base(subject, difference_id, action=""):
    path = subject.profile.base_path + f"api/v1/inquiries/{difference_id}"
    return f"{path}/{action}" if action else path


def send(subject, path, body):
    return subject.client.post(path, json=body, headers=headers(subject.profile, subject.csrf))


def read(subject, path):
    return subject.client.get(path, headers=headers(subject.profile))


def opening(choice=None):
    return {"schema_version": "inquiry-open-command-v1", "command_id": str(uuid4()), "model_choice_ref": choice}


def answer(question_id, text):
    return {"schema_version": "inquiry-answer-command-v1", "command_id": str(uuid4()), "question_id": question_id,
            "action": "answer" if text is not None else "skip", "text": text}


def evidence(text, sources=()):
    return {"schema_version": "inquiry-evidence-command-v1", "command_id": str(uuid4()), "text": text,
            "sources": list(sources)}


def judgment(hypothesis_id, verdict, evidence_ids=(), note=None):
    return {"schema_version": "inquiry-judgment-command-v1", "command_id": str(uuid4()),
            "hypothesis_id": hypothesis_id, "judgment": verdict, "evidence_ids": list(evidence_ids), "note": note}


def with_hypotheses(subject):
    choice, difference = observed_difference(subject)
    difference_id = difference["difference_ref"]["id"]
    made = send(subject, hypotheses_path(subject, difference_id), propose_body(choice))
    assert made.status_code == 200, made.text
    return choice, difference_id


def test_the_owner_opens_answers_some_skips_one_supplies_evidence_and_confirms_one(tmp_path):
    spy, mock = transport()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=6), transport=mock)
    with owner_app(tmp_path, executor) as subject:
        _choice, difference_id = with_hypotheses(subject)
        calls = len(messages(spy))
        before = read(subject, base(subject, difference_id)).json()
        assert before["state"] == "not_opened" and before["can_open"] is True and before["answers"] == []
        opened = send(subject, base(subject, difference_id), opening())
        assert opened.status_code == 200, opened.text
        value = opened.json()
        assert len(messages(spy)) == calls  # no model turn without a model choice
        origins = [item["origin"] for item in value["questions"]]
        # questions come from each hypothesis' predictions and from the unknowns, nothing else
        assert origins[:2] == ["hypothesis_prediction", "hypothesis_prediction"]
        assert set(origins) <= {"hypothesis_prediction", "missing_evidence", "hypothesis_without_prediction"}
        assert "규칙을 인계하면 차이가 사라진다" in value["questions"][0]["text"]
        assert value["answers"] == [] and value["unanswered_count"] == len(value["questions"])
        assert all(item["status"] == "proposed" for item in value["hypotheses"])
        assert value["change_candidates"] == [] and value["spli"]["state"] == "not_opened"
        frozen = value["frozen_at"]
        # a repeat never re-freezes
        assert send(subject, base(subject, difference_id), opening()).json()["frozen_at"] == frozen

        answered = send(subject, base(subject, difference_id, "answers"), answer("q1", "네, 인계를 바꾸면 사라졌습니다."))
        assert answered.status_code == 200, answered.text
        skip = answer("q2", None)
        skipped = send(subject, base(subject, difference_id, "answers"), skip)
        assert [(item["question_id"], item["state"]) for item in skipped.json()["answers"]] == [
            ("q1", "answered"), ("q2", "skipped")]
        assert skipped.json()["answers"][1]["text"] is None
        # a replayed command changes nothing
        assert send(subject, base(subject, difference_id, "answers"), skip).json()["revision"] == skipped.json()["revision"]

        supplied = send(subject, base(subject, difference_id, "evidence"),
                        evidence("지난 세 보고서에서 둘째 줄을 모두 같은 방식으로 고쳤다.", ["보고서 2026-07, 2026-08"]))
        assert supplied.status_code == 200, supplied.text
        [item] = supplied.json()["evidence"]
        assert item["evidence_ref"]["kind"] == "artifact" and item["at"] > frozen and item["origin"] == "owner_input"
        evidence_id = item["evidence_id"]

        # confirmation needs cited evidence and every competitor examined first
        bare = send(subject, base(subject, difference_id, "judgments"), judgment("expert_judgment-1", "confirmed"))
        assert bare.status_code == 422 and bare.json()["code"] == "evidence_required"
        early = send(subject, base(subject, difference_id, "judgments"),
                     judgment("expert_judgment-1", "confirmed", [evidence_id]))
        assert early.status_code == 409 and early.json()["code"] == "competitors_unexamined"
        refuted = send(subject, base(subject, difference_id, "judgments"),
                       judgment("system-0", "refuted", [evidence_id], "인계에는 규칙이 있었다."))
        assert refuted.status_code == 200, refuted.text
        assert refuted.json()["change_candidates"] == []
        confirmed = send(subject, base(subject, difference_id, "judgments"),
                         judgment("expert_judgment-1", "confirmed", [evidence_id]))
        assert confirmed.status_code == 200, confirmed.text
        view = confirmed.json()
        assert {item["hypothesis_id"]: item["status"] for item in view["hypotheses"]} == {
            "system-0": "refuted", "expert_judgment-1": "confirmed"}
        [candidate] = view["change_candidates"]
        assert candidate["kind"] == "learn" and candidate["state"] == "proposed"
        assert candidate["applied"] is False and candidate["compiled"] is False
        assert candidate["leak_check"] == "passed"
        assert candidate["evidence_refs"] == [item["evidence_ref"]]
        again = send(subject, base(subject, difference_id, "judgments"),
                     judgment("expert_judgment-1", "refuted", [evidence_id]))
        assert again.status_code == 409 and again.json()["code"] == "already_judged"

        audit = read(subject, base(subject, difference_id, "audit"))
        assert audit.status_code == 200, audit.text
        detail = audit.json()
        assert detail["owner_inputs"] == {"answers": 1, "skips": 1, "evidence": 1, "judgments": 2}
        assert detail["inputs_not_from_owner"] == 0
        [turn] = detail["model_turns"]
        assert turn["purpose"] == "diagnosis_hypotheses" and turn["intent_ref"] is not None
        assert turn["outcome"]["state"] == "completed"
        kinds = [item["kind"] for item in detail["timeline"]]
        assert kinds == ["difference_observed", "hypotheses_proposed", "opened", "answer", "skip", "evidence",
                         "judgment", "judgment"]
        assert all(item["actor"] == "owner" for item in detail["timeline"][2:])
        assert detail["timeline"][1]["actor"] == "model" and detail["timeline"][1]["requested_by"] == "owner"
        assert [item["public_metadata"] for item in events(subject, "inquiry.frozen")] == [
            {"question_count": len(value["questions"]),
             "prediction_count": len(value["questions"])}]
        assert [item["public_metadata"] for item in events(subject, "inquiry.declined")] == [{"deferred": True}]
        assert len(messages(spy)) == calls  # no step after the hypotheses called the model


def test_an_answer_shaped_model_output_is_refused_and_nothing_opens(tmp_path):
    answered_by_model = json.dumps({"questions": [
        {"text": "둘째 줄을 왜 고쳤습니까?", "hypothesis_ids": ["system-0"], "answer": "더 구체적이어서"}]},
        ensure_ascii=False)
    _spy, mock = transport(questions=answered_by_model)
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=6), transport=mock)
    with owner_app(tmp_path, executor) as subject:
        choice, difference_id = with_hypotheses(subject)
        refused = send(subject, base(subject, difference_id), opening(choice))
        assert refused.status_code == 422 and refused.json()["code"] == "model_output_invalid"
        assert read(subject, base(subject, difference_id)).json()["state"] == "not_opened"


def test_model_questions_are_admitted_as_proposals_with_nothing_answered(tmp_path):
    spy, mock = transport()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=6), transport=mock)
    with owner_app(tmp_path, executor) as subject:
        choice, difference_id = with_hypotheses(subject)
        opened = send(subject, base(subject, difference_id), opening(choice))
        assert opened.status_code == 200, opened.text
        value = opened.json()
        proposed = [item for item in value["questions"] if item["origin"] == "model_proposal"]
        assert [item["text"] for item in proposed] == ["다른 보고서에서도 둘째 줄을 이렇게 고치십니까?"]
        assert proposed[0]["if_yes"] is None  # no prediction is invented for a model question
        # the model turn saw the hypotheses, not the owner's answers (there are none)
        _request, raw = messages(spy)[-1]
        assert "expert_judgment-1" in json.loads(raw)["messages"][0]["content"]
        assert value["answers"] == [] and value["evidence"] == [] and value["judgments"] == []
        detail = read(subject, base(subject, difference_id, "audit")).json()
        assert detail["owner_inputs"] == {"answers": 0, "skips": 0, "evidence": 0, "judgments": 0}
        assert [turn["purpose"] for turn in detail["model_turns"]] == ["diagnosis_hypotheses", "inquiry_questions"]
        assert all(turn["intent_ref"] is not None for turn in detail["model_turns"])
        assert detail["questions"][-1] == {"question_id": proposed[0]["question_id"], "origin": "model_proposal"}


def test_opening_needs_hypotheses_and_every_body_is_exact(tmp_path):
    _spy, mock = transport()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=6), transport=mock)
    with owner_app(tmp_path, executor) as subject:
        choice, difference = observed_difference(subject)
        difference_id = difference["difference_ref"]["id"]
        early = send(subject, base(subject, difference_id), opening())
        assert early.status_code == 409 and early.json()["code"] == "hypotheses_required"
        assert read(subject, base(subject, difference_id)).json()["can_open"] is False
        not_open = send(subject, base(subject, difference_id, "answers"), answer("q1", "x"))
        assert not_open.status_code == 409 and not_open.json()["code"] == "not_opened"
        assert send(subject, hypotheses_path(subject, difference_id), propose_body(choice)).status_code == 200
        assert send(subject, base(subject, difference_id), opening()).status_code == 200
        path = base(subject, difference_id, "answers")
        assert send(subject, path, {**answer("q1", "x"), "extra": 1}).status_code == 400
        assert send(subject, path, {**answer("q1", None), "text": "a skip carries no text"}).status_code == 400
        assert send(subject, path, answer("q1", "   ")).status_code == 400
        assert send(subject, path, answer("q99", "x")).status_code == 404
        unknown = send(subject, base(subject, difference_id, "judgments"),
                       judgment("system-0", "refuted", [str(uuid4())]))
        assert unknown.status_code == 404
        assert send(subject, base(subject, difference_id, "judgments"),
                    judgment("system-0", "maybe")).status_code == 400
        assert read(subject, base(subject, str(uuid4()))).status_code == 404
        assert read(subject, base(subject, difference_id, "answers")).status_code in (400, 404, 405)
        # an unanswered, never-skipped question stays simply unanswered: nothing fills it
        view = read(subject, base(subject, difference_id)).json()
        assert view["answers"] == [] and view["unanswered_count"] == len(view["questions"])


def test_a_candidate_that_copies_the_owners_wording_is_flagged(tmp_path):
    quoting = json.dumps({"hypotheses": [
        {"family": "exception", "claim": "이번 보고서만 ‘첫 줄 고친 둘째 줄’처럼 쓴다.",
         "conditions": ["고친 둘째 줄 이라는 문구가 필요한 경우"], "predictions": []},
        {"family": "alternative_error", "claim": "고친 문장이 오히려 틀렸다.", "conditions": [], "predictions": []},
    ]}, ensure_ascii=False)
    _spy, mock = transport(diagnosis=quoting)
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=6), transport=mock)
    with owner_app(tmp_path, executor) as subject:
        _choice, difference_id = with_hypotheses(subject)
        value = send(subject, base(subject, difference_id), opening()).json()
        assert value["questions"][0]["origin"] == "hypothesis_without_prediction"
        supplied = send(subject, base(subject, difference_id, "evidence"), evidence("이번 분기만 해당한다.")).json()
        evidence_id = supplied["evidence"][0]["evidence_id"]
        unresolved = send(subject, base(subject, difference_id, "judgments"), judgment("alternative_error-1", "unresolved"))
        assert unresolved.status_code == 200, unresolved.text
        confirmed = send(subject, base(subject, difference_id, "judgments"),
                         judgment("exception-0", "confirmed", [evidence_id])).json()
        [candidate] = confirmed["change_candidates"]
        assert candidate["kind"] == "protect" and candidate["leak_check"] == "copies_owner_wording"
