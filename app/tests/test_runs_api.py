"""The connected browser path (resumption-plan Continuation, US3/T048 route
layer): an owner session starts a run of a stored graph and observes it
through the supported server, with no DOM change yet (the precedent is the
approvals route slice, "the browser path to approvals").

`POST /api/v1/runs` names the run's inputs by reference (a stored `graph`
record and the run's work revision, environment, consent and budget policy
records); the server seals the run manifest, creates the ledger run, emits
`run.started`, executes the scheduler to completion or to a human gate and
returns the bounded projection. `GET|HEAD /api/v1/runs/{run_id}` is a
no-execution read of the same projection. `POST …/{run_id}/resume` runs the
durable head again (after a recorded approval). The compilation authority
and the handler registry are code-owned host wiring injected as the run
executor, never page input; without one the route is honestly unavailable.
No model, tool or paid call; the fake transport only.
"""

import threading
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.runtime import scheduler as sch
from app.runtime.budgets import BudgetPolicy
from app.runtime.graph import compile_graph
from app.server import create_app
from app.services.design_persistence import encode_design_refs
from app.tests.test_graph_contract import authority, graph_value, parse, router_graph
from app.tests.test_graph_execution import linear_graph
from app.tests.test_server_api_v1 import immutable
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers


class Executor:
    """Code-owned run executor: the compilation authority and the handler
    registry are trusted host wiring, never page or model input."""

    def __init__(self):
        self.calls = []
        self.result = None

    def compile(self, graph):
        return compile_graph(graph, authority())

    def scheduler(self, compiled, *, ledger, run_id, approvals):
        def produce(context, view):
            self.calls.append(context.node_id)
            return self.result

        def route(context, view):
            self.calls.append(context.node_id)
            return "accept"

        handlers = {key: produce for key in (
            "core.deterministic", "core.agent", "core.join", "core.human_gate",
        )}
        handlers["core.router"] = route
        gated = any(node.kind == "human_gate" for node in compiled.nodes)
        return sch.build_scheduler(compiled, ledger=ledger, run_id=run_id, handlers=handlers,
                                   approvals=approvals if gated else None)


@contextmanager
def owner_app(tmp_path, executor):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments, run_executor=executor)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        domain = app.state.domain_store
        roots = domain.roots()
        policy = BudgetPolicy.create(
            profile="execution", provider_mode="subscription", max_model_calls=3,
            max_tool_calls=5, max_node_visits=7, max_loop_rounds=2, max_output_bytes=1_000,
            max_concurrency=2, max_wall_seconds=60, max_candidates=1,
        )
        refs = SimpleNamespace(
            work=immutable(domain, roots, "work_revision").ref,
            environment=immutable(domain, roots, "environment").ref,
            consent=immutable(domain, roots, "run_consent").ref,
            budget=immutable(domain, roots, "budget_policy", content=policy.domain_content()).ref,
        )
        if executor is not None:
            executor.result = immutable(domain, roots, "artifact").ref
        yield SimpleNamespace(app=app, client=client, profile=profile, csrf=csrf, refs=refs,
                              domain=domain, path=profile.base_path + "api/v1/runs")


def graph_record(subject, raw):
    graph = parse(raw)
    return immutable(subject.domain, subject.domain.roots(), "graph", content={
        "design_kind": "functional_graph", "design": encode_design_refs(graph.as_dict()),
    }).ref


def command(subject, graph_ref, **changes):
    body = {
        "command_id": str(uuid4()),
        "graph_ref": graph_ref.as_dict(),
        "work_revision_ref": subject.refs.work.as_dict(),
        "environment_ref": subject.refs.environment.as_dict(),
        "consent_ref": subject.refs.consent.as_dict(),
        "budget_policy_ref": subject.refs.budget.as_dict(),
    }
    return {**body, **changes}


def post(subject, body, path=None):
    return subject.client.post(path or subject.path, json=body,
                               headers=headers(subject.profile, subject.csrf))


def events(subject, event_type):
    listing = subject.client.get(subject.profile.base_path + "api/v1/events",
                                 headers=headers(subject.profile))
    assert listing.status_code == 200, listing.text
    return [item for item in listing.json()["events"] if item["event_type"] == event_type]


PROJECTION_FIELDS = {
    "run_id", "graph_digest", "completed_node_ids", "execution_ids", "result_refs",
    "counters", "activations", "awaiting_human", "approvals", "pending_node_ids",
    "rejected_human",
}


def test_a_browser_started_run_executes_and_is_readable_without_execution(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        graph_ref = graph_record(subject, linear_graph())
        body = command(subject, graph_ref)
        created = post(subject, body)
        assert created.status_code == 201, created.text
        receipt = created.json()
        assert executor.calls == ["intake", "writer", "publish"]
        assert receipt["command_id"] == body["command_id"]
        assert receipt["phase"] == "completed"
        assert receipt["graph_ref"] == graph_ref.as_dict()
        outcome = receipt["outcome"]
        assert set(outcome) == PROJECTION_FIELDS
        assert outcome["run_id"] == receipt["run_id"]
        assert outcome["completed_node_ids"] == ["intake", "publish", "writer"]
        assert outcome["awaiting_human"] == [] and outcome["approvals"] == []
        assert outcome["pending_node_ids"] == [] and outcome["rejected_human"] == []
        assert outcome["counters"] == {"intake": 1, "writer": 1, "publish": 1}
        executions = dict(outcome["execution_ids"])
        assert executions["writer"] == sch.execution_identity(receipt["run_id"], "writer", 0)
        assert dict(outcome["result_refs"])[executions["writer"]] == executor.result.as_dict()
        assert receipt["links"]["self"] == subject.profile.base_path + "api/v1/runs/" + receipt["run_id"]
        assert receipt["links"]["events"] == subject.profile.base_path + "api/v1/events"
        assert receipt["event_cursor"]
        # the run is visible to the browser's event stream
        started = events(subject, "run.started")
        assert len(started) == 1 and started[0]["public_metadata"] == {"node_count": 3, "edge_count": 2}
        assert started[0]["status"] == "succeeded"
        stopped = events(subject, "run.stopped")
        assert len(stopped) == 1 and stopped[0]["public_metadata"]["reason_code"] == "completed"
        # exact replay: the same receipt, no second run, no second event
        replay = post(subject, body)
        assert replay.status_code == 201 and replay.json() == receipt
        assert executor.calls == ["intake", "writer", "publish"]
        assert len(events(subject, "run.started")) == 1
        # a no-execution read of the same projection, HEAD equal to GET
        current = subject.client.get(receipt["links"]["self"], headers=headers(subject.profile))
        head = subject.client.head(receipt["links"]["self"], headers=headers(subject.profile))
        assert current.status_code == head.status_code == 200 and head.content == b""
        for name in ("content-type", "cache-control", "content-security-policy",
                     "x-content-type-options", "referrer-policy", "x-frame-options"):
            assert head.headers[name] == current.headers[name]
        state = current.json()
        assert state["outcome"] == outcome and state["phase"] == "completed"
        assert state["graph_ref"] == graph_ref.as_dict() and state["run_id"] == receipt["run_id"]
        assert executor.calls == ["intake", "writer", "publish"]
        # a different command for the same graph is a second run
        second = post(subject, command(subject, graph_ref))
        assert second.status_code == 201 and second.json()["run_id"] != receipt["run_id"]
        # a conflicting reuse of the command id is refused, whichever input differs
        conflict = post(subject, {**body, "graph_ref": graph_record(subject, linear_graph()).as_dict()})
        assert conflict.status_code == 409 and conflict.json()["code"] == "conflict"
        other_consent = immutable(subject.domain, subject.domain.roots(), "run_consent").ref
        conflict = post(subject, {**body, "consent_ref": other_consent.as_dict()})
        assert conflict.status_code == 409 and conflict.json()["code"] == "conflict"
        assert len(events(subject, "run.started")) == 2  # only the two genuine runs


def test_a_gated_run_waits_for_the_owner_and_resumes_after_the_recorded_approval(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        graph_ref = graph_record(subject, graph_value())
        created = post(subject, command(subject, graph_ref))
        assert created.status_code == 201, created.text
        receipt = created.json()
        assert receipt["phase"] == "awaiting_human"
        assert receipt["outcome"]["awaiting_human"] == [["owner-gate", "release-output"]]
        assert executor.calls == ["intake", "writer"]
        assert len(events(subject, "run.stopped")) == 0
        run_path = receipt["links"]["self"]
        # reading never resumes; resuming without an approval keeps waiting
        assert subject.client.get(run_path, headers=headers(subject.profile)).json()["phase"] == "awaiting_human"
        waiting = post(subject, {"command_id": str(uuid4())}, run_path + "/resume")
        assert waiting.status_code == 200 and waiting.json()["phase"] == "awaiting_human"
        assert executor.calls == ["intake", "writer"]
        # the owner records the approval through the existing route
        approved = post(subject, {
            "command_id": str(uuid4()), "node_id": "owner-gate",
            "approval_scope": "release-output", "decision": "approved",
        }, run_path + "/approvals")
        assert approved.status_code == 201, approved.text
        resume = {"command_id": str(uuid4())}
        resumed = post(subject, resume, run_path + "/resume")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["phase"] == "completed"
        assert resumed.json()["command_id"] == resume["command_id"]
        assert executor.calls == ["intake", "writer", "owner-gate", "publish"]
        assert resumed.json()["outcome"]["approvals"] == [["owner-gate", [
            subject.app.state.first_party_exports["run-approvals.service"]
            .lookup(receipt["run_id"], "owner-gate", "release-output").approval_ref.as_dict(),
        ]]]
        assert len(events(subject, "run.stopped")) == 1
        again = post(subject, resume, run_path + "/resume")
        assert again.status_code == 200 and again.json() == resumed.json()
        assert executor.calls == ["intake", "writer", "owner-gate", "publish"]
        read = subject.client.get(run_path, headers=headers(subject.profile)).json()
        assert read["phase"] == "completed" and read["outcome"] == resumed.json()["outcome"]


@pytest.mark.parametrize("shape", [
    "missing_field", "extra_member", "unknown_graph", "wrong_kind", "not_json", "oversize",
    "get_with_body", "query", "put",
])
def test_closed_shapes_are_refused_before_any_write(tmp_path, shape):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        graph_ref = graph_record(subject, linear_graph())
        body = command(subject, graph_ref)
        common = {"headers": headers(subject.profile, subject.csrf)}
        if shape == "missing_field":
            response = subject.client.post(subject.path, json={k: v for k, v in body.items() if k != "consent_ref"}, **common)
        elif shape == "extra_member":
            response = subject.client.post(subject.path, json={**body, "mode": "replay"}, **common)
        elif shape == "unknown_graph":
            response = subject.client.post(subject.path, json={**body, "graph_ref": {**graph_ref.as_dict(), "id": str(uuid4())}}, **common)
        elif shape == "wrong_kind":
            response = subject.client.post(subject.path, json={**body, "graph_ref": subject.refs.work.as_dict()}, **common)
        elif shape == "not_json":
            response = subject.client.post(subject.path, content=b"not json",
                                           headers={**common["headers"], "content-type": "application/json"})
        elif shape == "oversize":
            response = subject.client.post(subject.path, json={**body, "command_id": "x" * 5000}, **common)
        elif shape == "get_with_body":
            response = subject.client.request("GET", subject.path + "/" + str(uuid4()), content=b"{}",
                                              headers={**headers(subject.profile), "content-type": "application/json"})
        elif shape == "query":
            response = subject.client.post(subject.path + "?x=1", json=body, **common)
        else:
            response = subject.client.put(subject.path, json=body, **common)
        expected = {"oversize": {413}, "unknown_graph": {404}}.get(shape, {400})
        assert response.status_code in expected, (shape, response.status_code, response.text)
        assert response.json()["code"] in {"invalid_input", "too_large", "not_found"}
        assert executor.calls == []
        assert events(subject, "run.started") == []


def test_unauthenticated_and_unavailable_executor_are_honest(tmp_path):
    with owner_app(tmp_path, None) as subject:
        graph_ref = graph_record(subject, linear_graph())
        body = command(subject, graph_ref)
        cookies = dict(subject.client.cookies)
        subject.client.cookies.clear()
        unauthenticated = post(subject, body)
        assert unauthenticated.status_code == 401 and unauthenticated.json()["code"] == "unauthenticated"
        for name, value in cookies.items():
            subject.client.cookies.set(name, value)
        # no code-owned executor is installed: the run is not started
        unavailable = post(subject, body)
        assert unavailable.status_code == 503, unavailable.text
        assert unavailable.json()["code"] == "unavailable"
        assert events(subject, "run.started") == []
        missing = subject.client.get(subject.path + "/" + str(uuid4()), headers=headers(subject.profile))
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"


def test_the_composition_carries_the_run_routes(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        composition = subject.app.state.route_composition
        assert "runs-v1" in composition.contribution_ids
        for route_id in ("runs.create", "runs.read", "runs.resume"):
            assert route_id in composition.route_ids
        assert composition.route_count == 18


def test_a_router_run_with_an_untaken_branch_completes(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        created = post(subject, command(subject, graph_record(subject, router_graph())))
        assert created.status_code == 201, created.text
        receipt = created.json()
        assert receipt["phase"] == "completed", receipt
        assert receipt["outcome"]["pending_node_ids"] == []
        assert "choose" in receipt["outcome"]["completed_node_ids"]
        assert len(events(subject, "run.stopped")) == 1
        calls = list(executor.calls)
        resumed = post(subject, {"command_id": str(uuid4())}, receipt["links"]["self"] + "/resume")
        assert resumed.status_code == 200 and resumed.json()["phase"] == "completed"
        assert executor.calls == calls  # a completed head is never re-run
        assert len(events(subject, "run.stopped")) == 1


def test_a_crash_between_the_manifest_and_the_ledger_run_is_replayable(tmp_path, monkeypatch):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        ledger = subject.app.state.runtime_ledger
        original = ledger.create_run
        state = {"failed": False}

        def crash_once(command_id, spec):
            if not state["failed"]:
                state["failed"] = True
                raise RuntimeError("PRIVATE_CRASH_CANARY")
            return original(command_id, spec)

        monkeypatch.setattr(ledger, "create_run", crash_once)
        body = command(subject, graph_record(subject, linear_graph()))
        first = post(subject, body)
        assert first.status_code == 503 and "CANARY" not in first.text
        assert len(events(subject, "run.started")) == 1
        assert executor.calls == []
        # the same command replays: the sealed manifest is reused, the run is created
        # and executed exactly once
        replay = post(subject, body)
        assert replay.status_code == 201, replay.text
        assert replay.json()["phase"] == "completed"
        assert executor.calls == ["intake", "writer", "publish"]
        assert len(events(subject, "run.started")) == 1
        again = post(subject, body)
        assert again.status_code == 201 and again.json() == replay.json()
        assert executor.calls == ["intake", "writer", "publish"]


def test_a_replay_after_the_ledger_run_but_before_execution_executes(tmp_path, monkeypatch):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        original = executor.scheduler
        state = {"failed": False}

        def crash_once(*args, **kwargs):
            if not state["failed"]:
                state["failed"] = True
                raise RuntimeError("PRIVATE_CRASH_CANARY")
            return original(*args, **kwargs)

        monkeypatch.setattr(executor, "scheduler", crash_once)
        body = command(subject, graph_record(subject, linear_graph()))
        assert post(subject, body).status_code == 503
        replay = post(subject, body)
        assert replay.status_code == 201 and replay.json()["phase"] == "completed"
        assert executor.calls == ["intake", "writer", "publish"]


def test_concurrent_resumes_execute_a_run_once(tmp_path):
    executor = Executor()
    gate_reached = threading.Event()
    release = threading.Event()

    class BlockingExecutor(Executor):
        def scheduler(self, compiled, *, ledger, run_id, approvals):
            def slow(context, view):
                self.calls.append(context.node_id)
                if context.node_id == "owner-gate":
                    gate_reached.set()
                    assert release.wait(10)
                return self.result

            handlers = {key: slow for key in (
                "core.deterministic", "core.agent", "core.join", "core.router", "core.human_gate",
            )}
            return sch.build_scheduler(compiled, ledger=ledger, run_id=run_id, handlers=handlers,
                                       approvals=approvals)

    executor = BlockingExecutor()
    with owner_app(tmp_path, executor) as subject:
        created = post(subject, command(subject, graph_record(subject, graph_value())))
        assert created.json()["phase"] == "awaiting_human"
        run_path = created.json()["links"]["self"]
        approved = post(subject, {
            "command_id": str(uuid4()), "node_id": "owner-gate",
            "approval_scope": "release-output", "decision": "approved",
        }, run_path + "/approvals")
        assert approved.status_code == 201
        results = {}

        def resume(name):
            results[name] = post(subject, {"command_id": str(uuid4())}, run_path + "/resume")

        first = threading.Thread(target=resume, args=("first",))
        first.start()
        assert gate_reached.wait(10)
        # a second resume while the first executes is refused, never a second execution
        resume("second")
        assert results["second"].status_code == 409, results["second"].text
        assert results["second"].json()["code"] == "conflict"
        release.set()
        first.join(10)
        assert results["first"].status_code == 200 and results["first"].json()["phase"] == "completed"
        assert executor.calls.count("owner-gate") == 1 and executor.calls.count("publish") == 1
        assert len(events(subject, "run.stopped")) == 1


def test_a_rejected_gate_is_reported_and_never_an_infrastructure_failure(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        created = post(subject, command(subject, graph_record(subject, graph_value())))
        run_path = created.json()["links"]["self"]
        rejected = post(subject, {
            "command_id": str(uuid4()), "node_id": "owner-gate",
            "approval_scope": "release-output", "decision": "rejected",
        }, run_path + "/approvals")
        assert rejected.status_code == 201, rejected.text
        read = subject.client.get(run_path, headers=headers(subject.profile)).json()
        assert read["phase"] == "rejected"
        assert read["outcome"]["awaiting_human"] == []
        assert read["outcome"]["rejected_human"] == [["owner-gate", "release-output"]]
        resumed = post(subject, {"command_id": str(uuid4())}, run_path + "/resume")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["phase"] == "rejected"
        assert executor.calls == ["intake", "writer"]
        stopped = events(subject, "run.stopped")
        assert len(stopped) == 1 and stopped[0]["public_metadata"]["reason_code"] == "cancelled"
        again = post(subject, {"command_id": str(uuid4())}, run_path + "/resume")
        assert again.status_code == 200 and again.json()["phase"] == "rejected"
        assert len(events(subject, "run.stopped")) == 1


def test_a_failed_execution_is_stopped_and_a_resume_is_a_new_execution(tmp_path):
    executor = Executor()
    failing = {"writer"}

    class FailingExecutor(Executor):
        def scheduler(self, compiled, *, ledger, run_id, approvals):
            def produce(context, view):
                self.calls.append(context.node_id)
                if context.node_id in failing:
                    raise RuntimeError("PRIVATE_HANDLER_CANARY")
                return self.result

            handlers = {key: produce for key in (
                "core.deterministic", "core.agent", "core.join", "core.router", "core.human_gate",
            )}
            return sch.build_scheduler(compiled, ledger=ledger, run_id=run_id, handlers=handlers)

    executor = FailingExecutor()
    with owner_app(tmp_path, executor) as subject:
        body = command(subject, graph_record(subject, linear_graph()))
        failed = post(subject, body)
        assert failed.status_code == 503 and "CANARY" not in failed.text
        stopped = events(subject, "run.stopped")
        assert len(stopped) == 1 and stopped[0]["public_metadata"]["reason_code"] == "infrastructure_failure"
        # a replay of the command executes the head again and fails again
        replay = post(subject, body)
        assert replay.status_code == 503  # the replay executes again and fails again
        assert len(events(subject, "run.stopped")) == 2
        failing.clear()
        recovered = post(subject, body)
        assert recovered.status_code == 201 and recovered.json()["phase"] == "completed"
        stopped = events(subject, "run.stopped")
        assert len(stopped) == 3 and stopped[-1]["public_metadata"]["reason_code"] == "completed"
