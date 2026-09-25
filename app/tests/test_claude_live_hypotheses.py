"""One owner-authorized LIVE hypothesis proposal over a real observed difference.

Runs only with `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` and `DEEPTWIN_LIVE_HYPOTHESES=1`. A real
run (one Messages call) writes a short text; the owner rewrites its first line and freezes
that version; the framework observes the difference; one more model turn proposes
competing explanations, admitted through `propose_hypotheses`. Evidence (non-secret) goes
to `DEEPTWIN_LIVE_EVIDENCE_PATH`.
"""

import json
import os

import pytest

from app.domain.refs import EntityRef
from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
from app.services.run_artifacts import artifact_identity
from app.tests.test_alternative_drafts_api import freeze, save
from app.tests.test_claude_live_path import claude, live_graph, real_work, start
from app.tests.test_hypotheses import hypotheses_path, propose_body
from app.tests.test_runs_api import owner_app, post
from app.tests.test_web_owner_integration import headers

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
MODEL = os.environ.get("DEEPTWIN_LIVE_MODEL", "claude-opus-5")
EVIDENCE = os.environ.get("DEEPTWIN_LIVE_EVIDENCE_PATH")

pytestmark = pytest.mark.skipif(not KEY or os.environ.get("DEEPTWIN_LIVE_HYPOTHESES") != "1",
                                reason="live hypotheses need the key and DEEPTWIN_LIVE_HYPOTHESES=1")


def test_one_live_hypothesis_set_over_a_real_difference(tmp_path):
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=2, max_output_tokens=512))
    with owner_app(tmp_path, executor) as subject:
        assert claude(subject, "key", {"secret": KEY}).status_code == 200
        assert claude(subject, "catalog").status_code == 200
        choice = claude(subject, "model-choice", {"model_id": MODEL}).json()["model_choice_ref"]
        work = real_work(subject, "다음 회의 공지를 두세 줄로 써 주세요: 내일 오전 열 시, 3층 회의실, 분기 실적 검토.")
        _body, started = start(subject, live_graph(subject, choice), work)
        receipt = started.json()
        assert receipt.get("phase") == "completed", receipt
        writer = dict(receipt["outcome"]["execution_ids"])["writer"]
        ref = EntityRef.from_dict(dict(receipt["outcome"]["result_refs"])[writer])
        artifact_id = artifact_identity(ref, 0)
        base = subject.profile.base_path + "api/v1/runs"
        original = subject.client.get(f"{base}/{receipt['run_id']}/artifacts/{artifact_id}/content",
                                      headers=headers(subject.profile)).content.decode("utf-8")
        lines = original.split("\n")
        lines[0] = "[참석 필수] " + lines[0]  # the owner's own version: a stricter first line
        subject.path = base
        draft = save(subject, receipt["run_id"], artifact_id, format="text", text="\n".join(lines))
        frozen = freeze(subject, receipt["run_id"], artifact_id, draft.json()["draft_id"], 1)
        alternative_id = frozen.json()["alternative_ref"]["id"]
        observed = post(subject, {}, f"{base}/{receipt['run_id']}/artifacts/{artifact_id}/alternatives/"
                                      f"{alternative_id}/difference").json()
        path = hypotheses_path(subject, observed["difference_ref"]["id"])
        made = subject.client.post(path, json=propose_body(choice), headers=headers(subject.profile, subject.csrf))
        result = {"model": MODEL, "status": made.status_code, "hypotheses": made.json().get("hypotheses"),
                  "code": made.json().get("code"), "observations": observed["observations"]}
        with subject.domain._connection() as db:
            rows = [json.loads(bytes(row[0]))["content"] for row in
                    db.execute("SELECT body FROM domain_records WHERE kind='decision_record'")]
        result["calls"] = [{key: item.get(key) for key in ("provider_message_id", "state", "stop_reason", "usage")}
                           for item in rows if item.get("schema_version") == "claude-call-outcome-v1"]
        if EVIDENCE:
            with open(EVIDENCE, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        assert KEY not in json.dumps(result)
        assert made.status_code == 200, result
