"""The design arc's model boundary over the owner's Claude connection (mock transport).

`ClaudeRunExecutor.model_turn` is the `model_turn(system, user) -> str` the design
drivers call. Each call seals an intent before sending and an outcome after, spends the
process cap shared with run nodes, asks for the design effort the catalog supports, and
returns text only for a completed call.
"""

import json

import httpx2
import pytest

from app.services.claude_run_executor import (
    DESIGN_INTENT_SCHEMA,
    OUTCOME_SCHEMA,
    ClaudeRunExecutor,
    LiveLimits,
)
from app.tests.test_claude_api import MODEL_ID, SECRET, Spy, complete_text_stream, model, model_page, response
from app.tests.test_claude_live_path import EFFORT, connected, messages
from app.tests.test_runs_api import owner_app

EFFORTS = {"effort": {**EFFORT["effort"], "medium": {"supported": True}}}


def transport(stream):
    def responder(request, body):
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model(capabilities=EFFORTS)]))
        return response(request, body=stream, headers={"content-type": "text/event-stream"})

    spy = Spy(responder)
    return spy, httpx2.MockTransport(spy)


def records(subject, schema):
    with subject.domain._connection() as db:
        rows = db.execute("SELECT body FROM domain_records WHERE kind='decision_record'").fetchall()
    found = [json.loads(bytes(row["body"])) for row in rows]
    return [item["content"] for item in found if item["content"].get("schema_version") == schema]


def test_a_design_turn_returns_the_text_and_records_intent_and_outcome(tmp_path):
    spy, mock = transport(complete_text_stream('{"candidates": []}'))
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=3, max_design_output_tokens=4000),
                                 transport=mock)
    with owner_app(tmp_path, executor) as subject:
        connected(subject)
        turn = executor.model_turn(MODEL_ID, purpose="design_candidate")
        assert turn("system text", "user payload") == '{"candidates": []}'
        [(request, raw)] = messages(spy)
        sent = json.loads(raw)
        assert sent["max_tokens"] == 4000 and sent["output_config"] == {"effort": "medium"}
        assert sent["system"] == "system text" or "system text" in json.dumps(sent["system"])
        [intent] = records(subject, DESIGN_INTENT_SCHEMA)
        assert intent["purpose"] == "design_candidate" and intent["model_id"] == MODEL_ID
        assert intent["max_output_tokens"] == 4000 and len(intent["prompt_sha256"]) == 64
        [outcome] = records(subject, OUTCOME_SCHEMA)
        assert outcome["state"] == "completed" and outcome["stop_reason"] == "end_turn"
        with subject.domain._connection() as db:
            stored = b"".join(bytes(row[0]) for row in db.execute("SELECT body FROM domain_records"))
        assert SECRET.encode() not in stored and b"user payload" not in stored


def test_a_truncated_design_turn_raises_and_the_process_cap_is_shared(tmp_path):
    _spy, mock = transport(complete_text_stream("partial", reason="max_tokens"))
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=1), transport=mock)
    with owner_app(tmp_path, executor) as subject:
        connected(subject)
        turn = executor.model_turn(MODEL_ID, purpose="design_candidate")
        with pytest.raises(RuntimeError):
            turn("s", "u")
        assert records(subject, OUTCOME_SCHEMA)[0]["state"] == "incomplete"
        # the single process call is spent: the next turn is refused before sending
        with pytest.raises(RuntimeError):
            turn("s", "u")
        assert len(records(subject, DESIGN_INTENT_SCHEMA)) == 1
