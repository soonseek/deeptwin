"""One owner-authorized LIVE question-proposal turn for an inquiry over a real observed difference.

Runs only with `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` and `DEEPTWIN_LIVE_INQUIRY=1`. A real run (one
Messages call) writes a short notice; the test actor rewrites its first line and freezes that
version; the framework observes the difference; one live turn proposes competing explanations;
the test actor opens the inquiry with the same model, so one more live turn may add proposed
questions. Nothing is answered: the test asserts the model's output was admitted as questions
only and that no answer, evidence or judgment exists. Output caps keep the three calls within a
$0.50 budget. The model is `DEEPTWIN_LIVE_MODEL` or the first model the live catalog lists.
Evidence (non-secret) goes to `DEEPTWIN_LIVE_EVIDENCE_PATH`.
"""

import json
import os

import pytest

from app.domain.refs import EntityRef
from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
from app.services.run_artifacts import artifact_identity
from app.tests.test_alternative_drafts_api import freeze, save
from app.tests.test_claude_live_path import claude, live_graph, real_work, start
from app.tests.test_difference_inquiries import base, opening, read, send
from app.tests.test_hypotheses import hypotheses_path, propose_body
from app.tests.test_runs_api import owner_app, post
from app.tests.test_web_owner_integration import headers

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
EVIDENCE = os.environ.get("DEEPTWIN_LIVE_EVIDENCE_PATH")

pytestmark = pytest.mark.skipif(not KEY or os.environ.get("DEEPTWIN_LIVE_INQUIRY") != "1",
                                reason="the live inquiry turn needs the key and DEEPTWIN_LIVE_INQUIRY=1")


def test_one_live_question_proposal_is_admitted_as_questions_only(tmp_path):
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=3, max_output_tokens=256,
                                                   max_design_output_tokens=2_500))
    with owner_app(tmp_path, executor) as subject:
        assert claude(subject, "key", {"secret": KEY}).status_code == 200
        catalog = claude(subject, "catalog")
        assert catalog.status_code == 200
        model = os.environ.get("DEEPTWIN_LIVE_MODEL") or catalog.json()["catalog"]["model_ids"][0]
        choice = claude(subject, "model-choice", {"model_id": model}).json()["model_choice_ref"]
        work = real_work(subject, "다음 회의 공지를 두세 줄로 써 주세요: 내일 오전 열 시, 3층 회의실, 분기 실적 검토.")
        _body, started = start(subject, live_graph(subject, choice), work)
        receipt = started.json()
        assert receipt.get("phase") == "completed", receipt
        writer = dict(receipt["outcome"]["execution_ids"])["writer"]
        artifact_id = artifact_identity(EntityRef.from_dict(dict(receipt["outcome"]["result_refs"])[writer]), 0)
        runs = subject.profile.base_path + "api/v1/runs"
        original = subject.client.get(f"{runs}/{receipt['run_id']}/artifacts/{artifact_id}/content",
                                      headers=headers(subject.profile)).content.decode("utf-8")
        lines = original.split("\n")
        lines[0] = "[참석 필수] " + lines[0]  # the test actor's own version: a stricter first line
        subject.path = runs
        draft = save(subject, receipt["run_id"], artifact_id, format="text", text="\n".join(lines))
        frozen = freeze(subject, receipt["run_id"], artifact_id, draft.json()["draft_id"], 1)
        alternative_id = frozen.json()["alternative_ref"]["id"]
        observed = post(subject, {}, f"{runs}/{receipt['run_id']}/artifacts/{artifact_id}/alternatives/"
                                     f"{alternative_id}/difference").json()
        difference_id = observed["difference_ref"]["id"]
        made = send(subject, hypotheses_path(subject, difference_id), propose_body(choice))
        assert made.status_code == 200, made.text
        opened = send(subject, base(subject, difference_id), opening(choice))
        value = opened.json()
        audit = read(subject, base(subject, difference_id, "audit")).json()
        result = {"model": model, "status": opened.status_code, "code": value.get("code"),
                  "hypotheses": made.json()["hypotheses"], "questions": value.get("questions"),
                  "answers": value.get("answers"), "model_turns": audit.get("model_turns"),
                  "owner_inputs": audit.get("owner_inputs")}
        if EVIDENCE:
            with open(EVIDENCE, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        assert KEY not in json.dumps(result)
        assert opened.status_code == 200, result
        proposed = [item for item in value["questions"] if item["origin"] == "model_proposal"]
        assert 1 <= len(proposed) <= 4
        assert value["answers"] == [] and value["evidence"] == [] and value["judgments"] == []
        assert audit["owner_inputs"] == {"answers": 0, "skips": 0, "evidence": 0, "judgments": 0}
        assert [turn["purpose"] for turn in audit["model_turns"]] == ["diagnosis_hypotheses", "inquiry_questions"]
