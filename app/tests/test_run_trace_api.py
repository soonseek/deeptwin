"""The owner's read-only run trace (`GET|HEAD /api/v1/runs/{run_id}/trace`, run-trace-v1;
docs/ui/2026-09-26-product-ux-redesign.md §7).

A run whose writer's first attempt failed and whose second (the owner's recovery)
succeeded: the trace shows each attempt with its own times, outcome, reason and outputs —
the past attempt never carries the later result — the visits' recorded parents as inputs
and hand-offs, the budget reservation of each attempt, the final result of the graph's
declared exit, and every value the runtime did not record as `not_recorded`. Owner browser
session only: no session → 401, a bearer → 401 before any parsing, an unknown run → 404.
No model, tool or paid call; the fake transport only. Synthetic test-actor data.
"""

import json
from uuid import uuid4

from app.domain.schemas import ImmutableRecord
from app.services.runs import run_identity
from app.tests.test_runs_api import (
    AttemptExecutor,
    Executor,
    FlakyTransport,
    bind_attempts,
    command,
    graph_record,
    owner_app,
    post,
)
from app.tests.test_graph_execution import linear_graph
from app.tests.test_web_owner_integration import headers

STAMP = "2026-09-26T00:00:00.000000Z"
SECRET_CANARY = "sk-ant-api03-synthetic-trace-canary"


def artifact_record(domain, text, role="draft"):
    """A result record declaring one text artifact (the shape transports seal)."""

    roots = domain.roots()
    blob = domain.put_blob(text.encode(), purpose="operational")
    record = ImmutableRecord.create(
        kind="artifact", id=str(uuid4()), version=1, created_at_utc=STAMP, actor_ref=roots.actor,
        parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"schema_version": "fixture-output-v1", "output": {},
                 "artifacts": [{"ordinal": 0, "role": role, "media_type": "text/plain", "blob": blob.as_dict()}]})
    domain.put(record)
    return record.ref


def recovered_run(subject, executor, transport):
    bind_attempts(subject, executor)
    executor.result = artifact_record(subject.domain, "합성 원자료\n", role="source")
    transport.produced = artifact_record(subject.domain, "합성 초안\n", role="draft")
    body = command(subject, graph_record(subject, linear_graph()))
    assert post(subject, body).status_code == 503  # attempt 1 fails: the run stops
    run_id = run_identity(body["command_id"])
    run_path = subject.path + "/" + run_id
    recovered = post(subject, {"command_id": str(uuid4())}, run_path + "/recover")
    assert recovered.status_code == 200 and recovered.json()["phase"] == "completed", recovered.text
    return run_id, run_path


def trace(subject, run_path, **options):
    return subject.client.get(run_path + "/trace", headers=headers(subject.profile), **options)


def node(value, node_id):
    return next(item for item in value["nodes"] if item["node_id"] == node_id)


def test_the_trace_separates_attempts_and_names_what_was_not_recorded(tmp_path):
    transport = FlakyTransport(failures=1)
    executor = AttemptExecutor(transport)
    with owner_app(tmp_path, executor) as subject:
        run_id, run_path = recovered_run(subject, executor, transport)
        response = trace(subject, run_path)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        value = response.json()
        assert value["schema_version"] == "run-trace-v1" and value["run_id"] == run_id
        assert value["phase"] == "completed"
        assert set(value) == {"schema_version", "run_id", "phase", "graph_ref", "graph_digest", "work",
                              "budget_mode", "started_at_utc", "ended_at_utc", "stops", "totals", "exit",
                              "final_results", "stopped_at", "nodes", "handoffs", "approvals", "timeline",
                              "gaps", "links"}
        assert sorted(item["node_id"] for item in value["nodes"]) == ["intake", "publish", "writer"]
        # the run's own stop events: the failed execution, then completion; the end is the completion
        assert [stop["reason"] for stop in value["stops"]] == ["infrastructure_failure", "completed"]
        assert value["ended_at_utc"] == value["stops"][-1]["at_utc"]
        assert value["started_at_utc"] < value["ended_at_utc"]

        writer = node(value, "writer")
        [visit] = writer["visits"]
        assert visit["status"] == "completed" and visit["produced_by_attempt_no"] == 2
        first, second = visit["attempts"]
        assert [first["attempt_no"], second["attempt_no"]] == [1, 2]
        # attempt 1 keeps its own failure and never the later result
        assert first["terminal_outcome"] == "failed" and first["produced_visit_result"] is False
        assert first["error"] == {"outcome": "failed", "reason_code": "provider_terminal",
                                  "remote_terminal_observed": "failed"}
        assert first["result_ref"] == "not_recorded" and first["outputs"] == []
        assert second["terminal_outcome"] == "succeeded" and second["produced_visit_result"] is True
        assert second["error"] is None
        assert second["result_ref"] == transport.produced.as_dict()
        assert [item["role"] for item in second["outputs"]] == ["draft"]
        assert visit["outputs"] == second["outputs"]
        for attempt in (first, second):
            assert attempt["sent_at_utc"] != "not_recorded"
            assert attempt["ended_at_utc"] != "not_recorded"
            assert [entry["transition"] for entry in attempt["journal"]][:2] == ["reserved", "send_intent"]
            # the budget reservation recorded before the send; subscription mode states no currency
            assert attempt["budget_reservation"]["reserved"]["model_calls"] == 1
            assert attempt["budget_reservation"]["reserved"]["api_microunits"] == "not_recorded"
            assert attempt["cost"] == {"state": "unknown", "basis": "subscription_mode"}
            assert attempt["tool_calls"] == []
        assert first["sent_at_utc"] < second["sent_at_utc"]
        # the writer's input is the intake visit's exact result, from the recorded parent
        [source] = visit["inputs"]
        assert source["from_node_id"] == "intake" and source["from_attempt_no"] == "not_recorded"
        assert source["result_ref"] == executor.result.as_dict()
        assert [item["role"] for item in source["artifacts"]] == ["source"]

        # a handler visit has no ledger attempt; that is said, not filled
        intake = node(value, "intake")
        assert intake["visits"][0]["attempts"] == [] and intake["visits"][0]["model_calls"] == []
        categories = {item["category"] for item in value["gaps"]}
        assert {"handler_attempts", "handoff_receipt"} <= categories

        # hand-offs: sent result, receiving visit and its attempts; receipt is not recorded
        handoffs = {(item["from_node_id"], item["to_node_id"]): item for item in value["handoffs"]}
        assert set(handoffs) == {("intake", "writer"), ("writer", "publish")}
        to_writer = handoffs[("intake", "writer")]
        assert to_writer["to_attempt_nos"] == [1, 2] and to_writer["receipt"] == "not_recorded"
        assert to_writer["designed_edge_ids"] == ["e1"]
        from_writer = handoffs[("writer", "publish")]
        assert from_writer["from_attempt_no"] == 2 and from_writer["result_ref"] == transport.produced.as_dict()

        # the final result is what the graph's declared exit recorded (this test executor's
        # handler seals its fixed result there), never a guess
        assert value["exit"] == {"node_ids": ["publish"], "basis": "completion_criteria"}
        assert [item["node_id"] for item in value["final_results"]] == ["publish"]
        assert value["final_results"][0]["result_ref"] == node(value, "publish")["visits"][0]["result_ref"]
        assert value["stopped_at"] == []

        totals = value["totals"]
        assert totals["attempts"] == 2 and totals["retries"] == 1 and totals["model_calls"] == 2
        assert totals["tool_calls"] == 0
        # ledger model attempts record budget facts, not token counts: said, not zeroed
        assert totals["tokens_complete"] is False and "attempt_tokens" in categories
        assert totals["cost"] == {"state": "unknown", "microunits": "not_recorded", "currency": None}
        # the timeline is in time order and names each attempt
        stamps = [item["at_utc"] for item in value["timeline"]]
        assert stamps == sorted(stamps)
        assert [item["attempt_no"] for item in value["timeline"] if item["kind"] == "attempt"] == [1, 2]
        assert value["links"]["events"].endswith(f"/api/v1/events?run_id={run_id}")

        # HEAD carries the headers and no body; nothing was executed by reading
        head = subject.client.head(run_path + "/trace", headers=headers(subject.profile))
        assert head.status_code == 200 and head.content == b""
        assert transport.calls and len(transport.calls) == 2


def test_the_trace_carries_no_secret_or_raw_provider_payload(tmp_path):
    transport = FlakyTransport(failures=1)
    executor = AttemptExecutor(transport)
    with owner_app(tmp_path, executor) as subject:
        # a key stored for the owner never reaches the trace
        stored = subject.client.post(subject.profile.base_path + "api/v1/connections/claude/key",
                                     headers=headers(subject.profile, subject.csrf),
                                     json={"secret": SECRET_CANARY})
        assert stored.status_code in {200, 503}
        _run_id, run_path = recovered_run(subject, executor, transport)
        text = trace(subject, run_path).text
        assert SECRET_CANARY not in text
        for forbidden in ("lease_owner", "idempotency_key", "cursor", "permit_id", "principal_id", "owner\""):
            assert forbidden not in text
        value = json.loads(text)
        assert all(not call.get("request_body") for item in value["nodes"] for visit in item["visits"]
                   for call in visit["model_calls"])


def test_the_trace_is_owner_session_only(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        body = command(subject, graph_record(subject, linear_graph()))
        assert post(subject, body).status_code == 201
        run_path = subject.path + "/" + run_identity(body["command_id"])
        assert trace(subject, run_path).status_code == 200
        # a bearer is refused before its header is parsed (loopback profile: no bearer route)
        bearer = subject.client.get(run_path + "/trace", headers={**headers(subject.profile),
                                                                  "Authorization": "Bearer " + "A" * 43})
        assert bearer.status_code == 401
        # an unknown run, a malformed id, a query or a body
        assert trace(subject, subject.path + "/" + str(uuid4())).status_code == 404
        assert subject.client.get(subject.path + "/not-a-uuid/trace",
                                  headers=headers(subject.profile)).status_code == 400
        assert subject.client.get(run_path + "/trace?limit=1", headers=headers(subject.profile)).status_code == 400
        assert subject.client.post(run_path + "/trace", headers=headers(subject.profile, subject.csrf),
                                   json={}).status_code in {400, 405}
        subject.client.cookies.clear()
        assert trace(subject, run_path).status_code == 401


def test_a_handler_run_trace_reports_its_final_result_and_unrecorded_attempts(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        executor.result = artifact_record(subject.domain, "합성 보고서\n", role="report")
        body = command(subject, graph_record(subject, linear_graph()))
        assert post(subject, body).status_code == 201
        value = trace(subject, subject.path + "/" + run_identity(body["command_id"])).json()
        assert value["totals"]["attempts"] == 0 and value["totals"]["model_calls"] == 0
        assert [item["role"] for item in value["final_results"]] == ["report"]
        # one result named by every visit: each visit lists it as its own output
        assert all(visit["outputs"] and visit["attempts"] == [] for item in value["nodes"]
                   for visit in item["visits"])
        assert value["work"]["title"] == "not_recorded"  # a fixture revision carries no text


def test_events_filter_by_run_and_work_from_what_each_event_carries(tmp_path):
    from app.domain.public_events import _append_event_in_transaction
    from app.domain.refs import ObjectRef
    from app.domain.store import _writer

    with owner_app(tmp_path, Executor()) as subject:
        first = command(subject, graph_record(subject, linear_graph()))
        second = command(subject, graph_record(subject, linear_graph()))
        assert post(subject, first).status_code == 201 and post(subject, second).status_code == 201
        run_id = run_identity(first["command_id"])
        # a work revision event names its work's revision record; another work's does not
        domain = subject.domain
        roots = domain.roots()
        work = subject.refs.work
        other = ImmutableRecord.create(
            kind="work_revision", id=str(uuid4()), version=1, created_at_utc=STAMP, actor_ref=roots.actor,
            parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy, content={"fixture": "other"})
        domain.put(other)
        with _writer(), domain._connection(write=True) as db:
            for ref in (work, other.ref):
                _append_event_in_transaction(
                    db, vault_id=roots.genesis.id, recorded_at_utc=STAMP, observed_at_utc=STAMP,
                    actor_kind="human", actor_ref=roots.actor, event_type="work.revised",
                    object_refs=(ObjectRef(ref.kind, ref.id, ref.version, ref.sha256),),
                    correlation_id=str(uuid4()), causation_id=None, status="succeeded", error_code=None,
                    public_metadata={"revision": 1, "source_count": 0}, private_evidence_refs=(),
                    retention_class="core", policy_ref=roots.access_policy)
        events_path = subject.profile.base_path + "api/v1/events"

        def read(query):
            response = subject.client.get(events_path, params=query, headers=headers(subject.profile))
            assert response.status_code == 200, response.text
            return response.json()

        everything = [item["event_type"] for item in read({})["events"]]
        assert everything.count("run.started") == 2 and everything.count("run.stopped") == 2
        own = read({"run_id": run_id})
        # exactly this run's own start and stop (its creating command is their correlation)
        assert [item["event_type"] for item in own["events"]] == ["run.started", "run.stopped"]
        assert read({"run_id": str(uuid4())})["events"] == []
        by_work = read({"work_id": work.id})["events"]
        # the run consents name the work's revision too; the other work's revision event does not match
        assert [item["event_type"] for item in by_work] == ["approval.decided", "approval.decided", "work.revised"]
        assert all(any(ref["kind"] == "work_revision" and ref["id"] == work.id for ref in item["object_refs"])
                   for item in by_work)
        # a cursor belongs to its subject filter: it never pages another subject
        cursor = own["next_cursor"]
        assert subject.client.get(events_path, params={"cursor": cursor},
                                  headers=headers(subject.profile)).status_code == 400
        assert read({"run_id": run_id, "cursor": cursor})["events"] == []
        for query in ({"run_id": "not-a-uuid"}, {"run_id": run_id, "work_id": work.id},
                      [("run_id", run_id), ("run_id", run_id)], {"subject": run_id}):
            refused = subject.client.get(events_path, params=query, headers=headers(subject.profile))
            assert refused.status_code == 400, (query, refused.text)
