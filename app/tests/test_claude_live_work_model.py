"""One owner-authorized LIVE work-model draft through the product route.

Runs only with `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` and `DEEPTWIN_LIVE_WORK_MODEL=1`; never
in the ordinary suite. A work with text and one retained original is drafted by one
model turn through `POST /api/v1/work-models`, admitted strictly and confirmed by the
owner. Non-secret evidence goes to `DEEPTWIN_LIVE_EVIDENCE_PATH`.
"""

import json
import os

import pytest

from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
from app.tests.test_claude_live_path import claude
from app.tests.test_runs_api import owner_app
from app.tests.test_work_models import confirm_body, draft_body, get, post, sourced_work

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
MODEL = os.environ.get("DEEPTWIN_LIVE_MODEL", "claude-opus-5")
EVIDENCE = os.environ.get("DEEPTWIN_LIVE_EVIDENCE_PATH")

pytestmark = pytest.mark.skipif(not KEY or os.environ.get("DEEPTWIN_LIVE_WORK_MODEL") != "1",
                                reason="live work model needs the key and DEEPTWIN_LIVE_WORK_MODEL=1")


def test_one_live_work_model_draft_is_admitted_and_confirmed(tmp_path):
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=1))
    with owner_app(tmp_path, executor) as subject:
        assert claude(subject, "key", {"secret": KEY}).status_code == 200
        assert claude(subject, "catalog").status_code == 200
        choice = claude(subject, "model-choice", {"model_id": MODEL}).json()["model_choice_ref"]
        work, sources = sourced_work(subject)
        drafted = post(subject, "api/v1/work-models", draft_body(work, choice))
        observed = {"model": MODEL, "status": drafted.status_code, "body": drafted.json()}
        if drafted.status_code == 200:
            view = drafted.json()
            confirmed = post(subject, f"api/v1/work-models/{view['work_model_id']}/confirm",
                             confirm_body(view["work_model_ref"]))
            observed["confirmed_state"] = confirmed.json().get("state")
        with subject.domain._connection() as db:
            rows = [json.loads(bytes(row[0]))["content"] for row in
                    db.execute("SELECT body FROM domain_records WHERE kind='decision_record'")]
        observed["calls"] = [{key: item.get(key) for key in ("provider_message_id", "state", "stop_reason", "usage")}
                             for item in rows if item.get("schema_version") == "claude-call-outcome-v1"]
        if EVIDENCE:
            with open(EVIDENCE, "w", encoding="utf-8") as handle:
                json.dump(observed, handle, ensure_ascii=False, indent=2)
        assert KEY not in json.dumps(observed)
        assert drafted.status_code == 200, observed
        assert observed["confirmed_state"] == "confirmed"
