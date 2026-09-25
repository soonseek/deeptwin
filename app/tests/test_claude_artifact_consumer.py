"""T049: the Claude run executor's model role consumes a PRODUCED artifact, offline.

The graph's entry node names the host-owned table producer (`documents-table-v1`,
passed to `ClaudeRunExecutor(producers=...)`): the document adapter renders a CSV table
and it is sealed as that node's artifact. The Claude role (the writer) receives the
table's whole text as its input, and its output descends from the table's result.
A mock transport stands in for the provider: no network, key or paid call. The one live
run of this path is `test_claude_live_artifact_consumer.py` (owner-gated).
"""

import json
from hashlib import sha256

import pytest

from app.domain.refs import EntityRef
from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
from app.tests.support.runtime_e2e import TABLE_HANDLER, table_consumer_graph, table_producer
from app.tests.test_claude_live_path import connected, messages, mock_transport, real_work, start
from app.tests.test_runs_api import graph_record, owner_app
from app.tests.test_server_api_v1 import immutable
from app.tests.test_web_owner_integration import headers


def consumer_graph(subject, choice_ref):
    raw = table_consumer_graph(choice_ref)
    raw["observation_contract_ref"] = immutable(subject.domain, subject.domain.roots(),
                                                "observation_contract").ref.as_dict()
    raw["budget_policy_ref"] = subject.refs.budget.as_dict()
    return graph_record(subject, raw)


def run_table_consumer(subject):
    """Start the run and return (receipt, the table artifact, the table bytes, the
    writer's output record)."""

    _body, started = start(subject, consumer_graph(subject, connected(subject)), real_work(subject))
    assert started.status_code == 201, started.text
    receipt = started.json()
    listed = subject.client.get(receipt["links"]["self"] + "/artifacts", headers=headers(subject.profile)).json()
    table = next(item for item in listed["artifacts"] if item["role"] == "table")
    data = subject.client.get(receipt["links"]["self"] + f"/artifacts/{table['artifact_id']}/content",
                              headers=headers(subject.profile)).content
    writer = dict(receipt["outcome"]["execution_ids"])["writer"]
    output = subject.domain.get(EntityRef.from_dict(dict(receipt["outcome"]["result_refs"])[writer]))
    return receipt, table, data, output


def test_the_model_role_receives_the_produced_table_whole(tmp_path):
    spy, transport = mock_transport()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=2, max_output_tokens=64), transport=transport,
                                 producers={TABLE_HANDLER: table_producer})
    with owner_app(tmp_path, executor) as subject:
        receipt, table, data, output = run_table_consumer(subject)
        assert receipt["phase"] == "completed", receipt
        assert table["node_id"] == "intake" and table["declared_media_type"] == "text/csv"
        assert sha256(data).hexdigest() == table["sha256"] and data.startswith(b"region,quarter,units")
        [(_request, raw)] = messages(spy)
        sent = json.loads(raw)
        # the model's input is the table's whole text, not a summary of it
        assert sent["messages"] == [{"role": "user", "content": data.decode("utf-8")}]
        # the output descends from exactly the produced table's result record
        assert table["result_ref"] in output.body["parent_refs"]
        assert "request_id" in output.body["content"]["output"]  # recorded (the mock sends none)


def test_producers_are_host_wiring_only(tmp_path):
    with pytest.raises(TypeError):
        ClaudeRunExecutor(producers={TABLE_HANDLER: "not callable"})
    with pytest.raises(TypeError):
        ClaudeRunExecutor(producers=[(TABLE_HANDLER, table_producer)])
