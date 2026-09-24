"""The direct-adapter Claude path end to end over the supported app, against a mock
transport. No real network, key or paid call.

The owner stores a key (kept in server memory only), refreshes the catalog, and
chooses a catalog-listed model, which seals an owner `model_choice` record. A
real work, a graph whose agent node binds that choice, and the owner's consent
then start a run. The executor's agent node makes one Messages call and seals
its text as the node's artifact. The tests also check that a replay never calls
again, that the run and process budgets stop a call before it is sent, and that
without a key nothing is sent.
"""

import json
from uuid import uuid4

import httpx2

from app.domain.refs import EntityRef
from app.services.claude_run_executor import (
    OUTPUT_SCHEMA,
    ClaudeRunExecutor,
    LiveLimits,
)
from app.tests.test_claude_api import (
    MODEL_ID,
    SECRET,
    Spy,
    model,
    model_page,
    response,
    thinking_then_text_stream,
)
from app.tests.test_graph_execution import linear_graph
from app.tests.test_runs_api import events, graph_record, owner_app, post
from app.tests.test_server_api_v1 import immutable
from app.tests.test_web_owner_integration import headers

WORK_TEXT = "분기 보고서 초안을 세 문단으로 정리해 주세요."
EFFORT = {"effort": {"supported": True, "low": {"supported": True}}}


def mock_transport():
    def responder(request, body):
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model(capabilities=EFFORT)]))
        if request.url.path == "/v1/messages":
            # the provider's default thinking block comes first and is dropped
            return response(request, body=thinking_then_text_stream("합성 모델 출력"),
                            headers={"content-type": "text/event-stream"})
        raise AssertionError(request.url.path)

    spy = Spy(responder)
    return spy, httpx2.MockTransport(spy)


def claude(subject, name, body=None):
    base = subject.profile.base_path + "api/v1/connections/claude"
    if name is None:
        return subject.client.get(base, headers=headers(subject.profile))
    return subject.client.post(f"{base}/{name}", json=body or {}, headers=headers(subject.profile, subject.csrf))


def live_graph(subject, choice_ref):
    raw = linear_graph()
    raw["model_bindings"][0]["model_choice_ref"] = choice_ref
    raw["tool_bindings"] = []
    raw["grant_refs"] = []
    raw["memory_policies"][0]["read_grant_refs"] = []
    for node in raw["nodes"]:
        node["grant_refs"] = []
        if node["kind"] == "agent":
            node["config"]["tool_binding_ids"] = []
    roots = subject.domain.roots()
    raw["observation_contract_ref"] = immutable(subject.domain, roots, "observation_contract").ref.as_dict()
    raw["budget_policy_ref"] = subject.refs.budget.as_dict()
    return graph_record(subject, raw)


def real_work(subject, text=WORK_TEXT):
    created = post(subject, {"schema_version": "work-create-command-v1", "command_id": str(uuid4()),
                             "text": text}, subject.profile.base_path + "api/v1/works").json()
    with subject.domain._connection() as db:
        row = db.execute("SELECT sha256 FROM domain_records WHERE kind='work_revision' AND id=? AND version=1",
                         (created["work_id"],)).fetchone()
    return EntityRef("work_revision", created["work_id"], 1, row["sha256"])


def start(subject, graph_ref, work_ref):
    consent = post(subject, {
        "schema_version": "run-consent-command-v1", "command_id": str(uuid4()),
        "graph_ref": graph_ref.as_dict(), "work_revision_ref": work_ref.as_dict(),
        "environment_ref": subject.refs.environment.as_dict(), "budget_policy_ref": subject.refs.budget.as_dict(),
    }, subject.profile.base_path + "api/v1/run-consents").json()
    body = {"command_id": str(uuid4()), "graph_ref": graph_ref.as_dict(), "work_revision_ref": work_ref.as_dict(),
            "environment_ref": subject.refs.environment.as_dict(), "consent_ref": consent["ref"],
            "budget_policy_ref": subject.refs.budget.as_dict()}
    return body, post(subject, body)


def connected(subject):
    assert claude(subject, None).json()["key_present"] is False
    stored = claude(subject, "key", {"secret": SECRET})
    assert stored.status_code == 200, stored.text
    assert stored.json()["key_present"] is True and stored.json()["key_storage"] == "server_memory_only"
    assert SECRET not in stored.text
    catalog = claude(subject, "catalog")
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["catalog"]["model_ids"] == [MODEL_ID]
    assert claude(subject, "model-choice", {"model_id": "not-listed"}).status_code == 404
    chosen = claude(subject, "model-choice", {"model_id": MODEL_ID})
    assert chosen.status_code == 200, chosen.text
    return chosen.json()["model_choice_ref"]


def messages(spy):
    return [(request, body) for request, body in spy.requests if request.url.path == "/v1/messages"]


def test_an_owner_connected_run_makes_one_model_call_and_records_its_output(tmp_path):
    spy, transport = mock_transport()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=5, max_output_tokens=64), transport=transport)
    with owner_app(tmp_path, executor) as subject:
        choice = connected(subject)
        assert [event["public_metadata"] for event in events(subject, "model.selected")] == [
            {"provider": "claude", "auth_mode": "api", "revision": 1}]
        body, started = start(subject, live_graph(subject, choice), real_work(subject))
        assert started.status_code == 201, started.text
        receipt = started.json()
        assert receipt["phase"] == "completed", receipt
        [(request, raw)] = messages(spy)
        sent = json.loads(raw)
        assert request.headers["x-api-key"] == SECRET  # injected at send time only
        assert sent["model"] == MODEL_ID and sent["max_tokens"] == 64
        assert sent["output_config"] == {"effort": "low"} and "thinking" not in sent
        assert "Your output limit is 64 tokens" in json.dumps(sent["system"])
        assert WORK_TEXT in json.dumps(sent, ensure_ascii=False)
        results = dict(receipt["outcome"]["result_refs"])
        writer = dict(receipt["outcome"]["execution_ids"])["writer"]
        output = subject.domain.get(EntityRef.from_dict(results[writer]))
        content = output.body["content"]
        assert content["schema_version"] == OUTPUT_SCHEMA and content["model_id"] == MODEL_ID
        assert content["output"]["usage"]["output_tokens"] == 5 and content["output"]["stop_reason"] == "end_turn"
        # the owner reads the model's text through the run's artifact routes
        listed = subject.client.get(receipt["links"]["self"] + "/artifacts", headers=headers(subject.profile)).json()
        texts = [item for item in listed["artifacts"] if item["role"] == "draft"]
        assert texts, listed
        body_text = subject.client.get(receipt["links"]["self"] + f"/artifacts/{texts[0]['artifact_id']}/content",
                                       headers=headers(subject.profile)).content.decode("utf-8")
        assert body_text == "합성 모델 출력"
        # a replay of the same command never calls again
        assert post(subject, body).json()["run_id"] == receipt["run_id"]
        assert len(messages(spy)) == 1
        # the key never appears in any stored record or event
        with subject.domain._connection() as db:
            stored = b"".join(bytes(row[0]) for row in db.execute("SELECT body FROM domain_records"))
            logged = b"".join(bytes(row[0]) for row in db.execute("SELECT envelope FROM api_event_envelopes"))
        assert SECRET.encode() not in stored and SECRET.encode() not in logged


def test_the_budget_stops_a_call_before_it_is_sent(tmp_path):
    spy, transport = mock_transport()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=1, max_output_tokens=64), transport=transport)
    with owner_app(tmp_path, executor) as subject:
        choice = connected(subject)
        graph = live_graph(subject, choice)
        work = real_work(subject)
        assert start(subject, graph, work)[1].json()["phase"] == "completed"
        assert len(messages(spy)) == 1
        # the process cap is spent: the next run's agent node fails without sending
        # (a failed node stops the run; the run route reports it as unavailable)
        second = start(subject, graph, work)[1]
        assert second.status_code == 503
        assert len(messages(spy)) == 1
        assert [item["public_metadata"] for item in events(subject, "run.stopped")][-1]["reason_code"] == "infrastructure_failure"


def test_without_a_key_nothing_is_sent(tmp_path):
    spy, transport = mock_transport()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=5, max_output_tokens=64), transport=transport)
    with owner_app(tmp_path, executor) as subject:
        choice = connected(subject)
        assert claude(subject, "forget").json()["key_present"] is False
        failed = start(subject, live_graph(subject, choice), real_work(subject))[1]
        assert failed.status_code == 503
        assert messages(spy) == []
