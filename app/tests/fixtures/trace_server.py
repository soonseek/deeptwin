"""Finite test-owned supported app whose seeded run has content in every trace section
(UI phase 3, 2026-09-26: the run detail screen, its browser journey and its screenshots).

The real supported factory over a fresh owned directory. Its run executor is the product's
Claude run executor over an in-process scripted transport (httpx2.MockTransport: no
network, no key, no paid call), extended by this fixture — test-owned host wiring — with
the tool-gate fixture's test seams: the in-process extension worker on its real socket
with the TEST-ACTOR tool `test_actor_notify` (it claims an external effect and performs
none), the real attempt dispatcher and the real extension attempt transport.

At startup the fixture acts as a scripted test actor through the owner's own routes
(in-process, before the socket opens): it sets the owner up (the browser later logs in with
the same synthetic passphrase), stores a test-only key in server memory, reads the scripted
catalog and chooses its model, saves a work, and runs the graph

    intake (정해진 처리) → writer (에이전트: one scripted model call with recorded tokens)
      → tool-gate (사람 승인: a gate decision, then one decision per tool attempt)
      → publish (정해진 처리 + 도구: attempt 1 fails, the owner's recovery makes attempt 2)
      → report (정해진 처리: the final report artifact)

approving the gate and each tool attempt and recovering once, so run A completes under a
subscription budget (its model call's cost basis is `subscription_mode`, no money). A second
run B, under an API-priced budget in the currency of the fixture's configured ceiling rates,
stops at the gate (awaiting the owner); its model call's cost is an estimate from the
recorded tokens at those rates. It announces TRACE_SEED= (both run ids) and TRACE_URL=.
Every value is synthetic test-actor data — the scripted usage and the ceiling rates are this
fixture's own configuration, never a real price — nothing here stands in for a person, and
DEEPTWIN_LIVE_ANTHROPIC_API_KEY is never read.
"""
import argparse
import base64
import copy
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx2
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from _pytest.monkeypatch import MonkeyPatch  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.domain.permissions import Grant, Principal  # noqa: E402
from app.domain.refs import EntityRef  # noqa: E402
from app.domain.schemas import Actor  # noqa: E402
from app.operations.session_root import initialize_session_root  # noqa: E402
from app.operations.setup import (  # noqa: E402
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.runtime import extension_attempt_transport as xt  # noqa: E402
from app.runtime import node_attempts as na  # noqa: E402
from app.runtime import scheduler as sch  # noqa: E402
from app.runtime.budgets import BudgetPolicy  # noqa: E402
from app.runtime.graph import CompilationAuthority, compile_graph  # noqa: E402
from app.runtime.ledger import OwnerIdentity  # noqa: E402
from app.server import create_app  # noqa: E402
from app.services.claude_connection import CHOICE_SCHEMA  # noqa: E402
from app.services.claude_run_executor import CeilingRates, ClaudeRunExecutor, LiveLimits  # noqa: E402
from app.services.design_persistence import encode_design_refs  # noqa: E402
from app.tests.fixtures import tool_gate_server as gate_fixture  # noqa: E402
from app.tests.support.tool_gate import (  # noqa: E402
    EFFECT,
    GATE,
    KEY,
    SCOPE,
    STORE,
    deterministic_tool_gated_graph,
)
from app.tests.test_claude_api import (  # noqa: E402
    MODEL_ID,
    SECRET,
    Spy,
    model,
    model_page,
    response,
    sse_event,
)
from app.tests.test_extension_attempt_transport import text_input  # noqa: E402
from app.tests.test_graph_contract import artifact_edge, input_slot, node, output_slot, parse, ref, trusted_tool  # noqa: E402
from app.tests.test_server_api_v1 import immutable  # noqa: E402
from app.tests.test_web_owner_integration import headers  # noqa: E402
from app.workers.extension_execute_messages import MAX_INPUT_BYTES, MAX_REPLY_BYTES  # noqa: E402

LABEL = "synthetic/test-actor"
PASSWORD = "synthetic owner passphrase"
REPORT = "report"
REPORT_HANDLER = "fixture-final-report-v1"
EFFORT = {"effort": {"supported": True, "low": {"supported": True}}}
WORK_TEXT = ("화요일 공간 안내\n"
             "다음 주 화요일 오후 모임의 장소·시간·준비물을 안내문으로 정리해 주세요. (합성 시험 데이터)\n")
DRAFT = ("# 화요일 공간 안내\n\n"
         "- 장소: 3층 세미나실\n"
         "- 시간: 화요일 14:00–16:00\n"
         "- 준비물: 노트북, 발표 자료\n\n"
         "늦게 오시는 분은 뒷문으로 들어와 주세요.\n"
         "문의는 운영팀에 해 주세요.\n")
# the scripted provider's reported usage (what the executor records, never a real count)
INPUT_TOKENS, OUTPUT_TOKENS = 812, 164
# this fixture's own host configuration of ceiling rates (synthetic, never a real price):
# micro-units per million tokens; run B's call is estimated at 812 x 4 + 164 x 20 micro-units
CEILING_RATES = CeilingRates(currency="USD", input_microunits_per_mtok=4_000_000,
                             output_microunits_per_mtok=20_000_000)


def scripted_stream(text):
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_synthetic_trace_1", "type": "message", "role": "assistant", "model": MODEL_ID,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": INPUT_TOKENS, "output_tokens": 1,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": OUTPUT_TOKENS}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return b"".join(sse_event(name, payload) for name, payload in events)


def responder(request, body):
    if request.url.path == "/v1/models":
        return response(request, payload=model_page([model(capabilities=EFFORT)]))
    if request.url.path == "/v1/messages":
        return response(request, body=scripted_stream(DRAFT), headers={"content-type": "text/event-stream"})
    raise AssertionError(request.url.path)


def trace_graph(choice_ref, observation_ref, budget_ref):
    """The deterministic tool-gated graph (intake → writer → tool-gate → publish) with the
    owner-chosen model on the writer, a v1 gate scope beside the tool scope, and a final
    report step after the store."""

    raw = copy.deepcopy(deterministic_tool_gated_graph())
    words = {"intake": "업무 설명을 원자료로 정리한다", "writer": "안내문 초안을 쓴다",
             GATE: "사람이 초안과 저장 도구 호출을 승인한다", STORE: "승인된 안내문을 저장 도구로 기록한다"}
    for item in raw["nodes"]:
        item["responsibility"] = words[item["node_id"]]
        if item["node_id"] == GATE:
            item["config"]["approval_scopes"] = sorted([SCOPE, "release-output"])
    raw["nodes"].append(node(REPORT, "deterministic", "최종 안내문을 보고서로 묶는다",
                             inputs=[input_slot("stored", "text-document")],
                             outputs=[output_slot("report", "text-document")],
                             config={"handler_id": REPORT_HANDLER}))
    raw["edges"].append(artifact_edge("e3", STORE, "result", REPORT, "stored", "text-document"))
    raw["completion_criteria"] = [{"criterion_id": "final", "node_id": REPORT, "output_slot": "report",
                                   "artifact_contract_id": "text-document", "min_items": 1}]
    raw["model_bindings"][0]["model_choice_ref"] = choice_ref.as_dict()
    raw["observation_contract_ref"] = observation_ref.as_dict()
    raw["budget_policy_ref"] = budget_ref.as_dict()
    return raw


class TraceExecutor:
    """Test-owned host wiring around the product's Claude run executor (installed as
    that exact executor, so the Claude connection uses its scripted transport): the
    compilation authority adds the test-actor tool definition to the owner's model
    choices, `publish` dispatches through the real attempt dispatcher and extension
    transport, the writer's model call is the executor's own, and the report step seals
    the final report from the approved draft."""

    def __init__(self, claude, refs):
        self.claude = claude
        self.refs = refs
        self.owner = OwnerIdentity(str(uuid4()), 4321, 900, str(uuid4()))
        self.contexts = {}
        self.drafts = {}
        self.book = None

    def authority(self):
        choices = [(record.ref, tuple(record.body["content"]["capabilities"]))
                   for record in self.claude._records("model_choice", owner_only=True, schema=CHOICE_SCHEMA)]
        return CompilationAuthority.from_trusted(
            model_choices=choices, tool_definitions=[trusted_tool(EFFECT, tool_id=KEY[0], version=KEY[1])],
            grant_refs=[EntityRef.from_dict(ref("grant", 6))], approval_scopes=["release-output"],
            observation_contract_refs=[self.refs["observation"]], budget_policy_refs=[self.refs["budget"]],
            artifact_schema_refs=[])

    def compile(self, graph):
        self.claude._bound()
        return compile_graph(graph, self.authority())

    def _context(self, ledger, run_id):
        if run_id not in self.contexts:
            later = int(time.time() * 1000) + 3_600_000
            principal = Principal(str(uuid4()), Actor(str(uuid4()), "test_actor", "test_fixture"), "runtime",
                                  "operational", later)
            grant = Grant(str(uuid4()), str(uuid4()), principal.id, self.refs["envelope"], "read", "operational",
                          None, later, 1)
            self.contexts[run_id] = {"principal": principal, "grant": grant, "deadline": later,
                                     "policy": ledger.get_run(run_id)["spec"]["budget_policy_ref"]}
        return self.contexts[run_id]

    def scheduler(self, compiled, *, ledger, run_id, approvals, retry=False):
        claude = self.claude
        context = self._context(ledger, run_id)
        graph = compiled.execution_graph.as_dict()
        nodes = {item["node_id"]: item for item in graph["nodes"]}
        bindings = {item["binding_id"]: item for item in graph["model_bindings"]}
        predecessors = dict(compiled.activation_predecessors)
        spec = ledger.get_run(run_id)["spec"]
        # the store's exact input: the approved draft's bytes once the writer made them
        payload = self.drafts.get(run_id, {}).get("bytes", b"synthetic draft not yet written\n")
        transport = xt.ExtensionAttemptTransport.build(
            domain_store=claude._domain, instance_id=gate_fixture.INSTANCE, slot_number=gate_fixture.SLOT,
            operation="invoke_tool", artifact_inputs=(text_input(payload),), compiled=compiled, node_id=STORE,
            binding_id="source-read", ledger=ledger, approvals=approvals)
        dispatcher = na.NodeAttemptDispatcher.build(
            ledger=ledger, budget_book=self.book, owner=self.owner,
            bindings={STORE: na.AttemptBinding.create(
                envelope_ref=self.refs["envelope"], profile_ref=self.refs["profile"],
                budget_policy_ref=EntityRef.from_dict(context["policy"]), deadline_at_ms=context["deadline"],
                lease_duration_ms=60_000, model_calls=0, tool_calls=1, node_visits=1, loop_rounds=0,
                output_bytes=transport.output_bytes_bound, candidates=0, api_microunits=None,
                principal=context["principal"], grant=context["grant"])},
            transport=transport, retry_after_terminal=retry)

        def upstream(context, view):
            refs = []
            for source in predecessors.get(context.node_id, ()):
                count = view["counters"].get(source, 0)
                found = view["results"].get(sch.execution_identity(run_id, source, count - 1)) if count else None
                if found is not None:
                    refs.append(found)
            return refs

        def deterministic(context, view):
            if context.attempt is not None:
                return context.attempt.dispatch()  # the store step's tool call
            if context.node_id == REPORT:
                draft = self.drafts[run_id]
                text = (draft["bytes"].decode("utf-8").rstrip("\n")
                        + "\n\n---\n저장 도구 기록을 확인한 최종본입니다. (합성 시험 데이터, 테스트 행위자)\n")
                return claude._seal_artifact(
                    record_id=str(uuid5(NAMESPACE_URL, f"deeptwin:fixture-report:{run_id}:{context.execution_id}")),
                    text=text, role="report", parents=(draft["ref"], *upstream(context, view)),
                    content={"schema_version": REPORT_HANDLER, "run_id": run_id, "node_id": REPORT, "label": LABEL})
            return claude._source_artifact(spec, run_id, context)

        def forward(context, view):
            found = upstream(context, view)
            return found[0]

        def agent(context, view):
            result = claude._model_call(context, view, nodes[context.node_id], bindings, spec, run_id,
                                        upstream(context, view))
            record = claude._domain.get(result)
            item = record.body["content"]["artifacts"][0]
            from app.domain.store import BlobRef

            data = claude._domain.read_blob(BlobRef(**item["blob"]), purpose="operational")
            self.drafts[run_id] = {"ref": result, "bytes": data}
            return result

        handlers = {"core.deterministic": deterministic, "core.human_gate": forward, "core.agent": agent}
        return sch.build_scheduler(compiled, ledger=ledger, run_id=run_id,
                                   handlers={key: handlers[key] for _, key in compiled.handler_keys},
                                   approvals=approvals, attempts=dispatcher)


def seed(app, profile, capability, executor, tool_state):
    """The scripted test actor's journey through the owner's own routes (in-process)."""

    client = TestClient(app, base_url=profile.http_origin)  # no lifespan, no socket
    base = profile.base_path
    created = client.post(base + "session/bootstrap", headers=headers(profile), json={
        "login_name": "owner", "password": PASSWORD, "raw_capability_b64u": capability})
    assert created.status_code == 201, created.text
    csrf = created.json()["csrf_token"]

    def post(path, body):
        answer = client.post(base + path, json=body, headers=headers(profile, csrf))
        return answer.status_code, answer.json()

    def get(path):
        answer = client.get(base + path, headers=headers(profile))
        assert answer.status_code == 200, (path, answer.text)
        return answer.json()

    for name, body in (("key", {"secret": SECRET}), ("catalog", {}), ("model-choice", {"model_id": MODEL_ID})):
        status, value = post(f"api/v1/connections/claude/{name}", body)
        assert status == 200, (name, value)
    choice = EntityRef.from_dict(value["model_choice_ref"])
    status, work = post("api/v1/works", {"schema_version": "work-create-command-v1", "command_id": str(uuid4()),
                                         "text": WORK_TEXT})
    assert status == 201, work
    domain = app.state.domain_store
    work_ref = EntityRef.from_dict(work["ref"])
    roots = domain.roots()
    limits = {"max_model_calls": 4, "max_tool_calls": 6, "max_node_visits": 16, "max_loop_rounds": 2,
              "max_output_bytes": MAX_REPLY_BYTES + MAX_INPUT_BYTES, "max_concurrency": 2,
              "max_wall_seconds": 3_600, "max_candidates": 1}
    policy = BudgetPolicy.create(profile="execution", provider_mode="subscription", **limits)
    # run B's API-priced budget, in the currency of the fixture's configured ceiling rates
    api_policy = BudgetPolicy.create(profile="execution", provider_mode="api", currency=CEILING_RATES.currency,
                                     max_api_microunits=1_000_000, **limits)
    executor.refs.update({
        "envelope": immutable(domain, roots, "execution_envelope").ref,
        "profile": immutable(domain, roots, "runtime_profile").ref,
        "observation": immutable(domain, roots, "observation_contract").ref,
        "budget": immutable(domain, roots, "budget_policy", content=policy.domain_content()).ref,
        "api_budget": immutable(domain, roots, "budget_policy", content=api_policy.domain_content()).ref,
    })
    executor.book = app.state.budget_book
    graph = immutable(domain, roots, "graph", content={
        "design_kind": "functional_graph", "design": encode_design_refs(parse(trace_graph(
            choice, executor.refs["observation"], executor.refs["budget"])).as_dict())}).ref
    environment = immutable(domain, roots, "environment").ref
    inputs = {"graph_ref": graph.as_dict(), "work_revision_ref": work_ref.as_dict(),
              "environment_ref": environment.as_dict(), "budget_policy_ref": executor.refs["budget"].as_dict()}

    def start(budget_ref=executor.refs["budget"]):
        named = {**inputs, "budget_policy_ref": budget_ref.as_dict()}
        status, consent = post("api/v1/run-consents", {"schema_version": "run-consent-command-v1",
                                                       "command_id": str(uuid4()), **named})
        assert status == 201, consent
        status, receipt = post("api/v1/runs", {"command_id": str(uuid4()), **named, "consent_ref": consent["ref"]})
        assert status == 201, receipt
        assert receipt["phase"] == "awaiting_human" and receipt["outcome"]["awaiting_human"], receipt
        return receipt["run_id"]

    def command(run_id, name):
        return post(f"api/v1/runs/{run_id}/{name}", {"command_id": str(uuid4())})

    def approve_attempt(run_id, attempt_no):
        listing = get(f"api/v1/runs/{run_id}/approvals/executions")
        ask = next(item for item in listing["requests"] if item["attempt_no"] == attempt_no)
        assert ask["state"] == "pending", ask
        status, value = post(f"api/v1/runs/{run_id}/approvals/executions", {
            "command_id": str(uuid4()), "node_id": ask["node_id"], "approval_scope": ask["approval_scope"],
            "execution_id": ask["execution_id"], "execution_node_id": ask["execution_node_id"],
            "attempt_no": attempt_no, "inputs_digest": ask["inputs_digest"], "decision": "approved"})
        assert status == 201, value

    run_a = start()
    status, value = post(f"api/v1/runs/{run_a}/approvals", {"command_id": str(uuid4()), "node_id": GATE,
                                                            "approval_scope": "release-output",
                                                            "decision": "approved"})
    assert status == 201, value
    status, receipt = command(run_a, "resume")  # the gate passes; the store asks for attempt 1
    assert status == 200 and receipt["phase"] == "awaiting_human", receipt
    approve_attempt(run_a, 1)
    tool_state["fail_next"] = 1  # the test-actor tool fails its next call: attempt 1 fails
    status, receipt = command(run_a, "resume")
    assert status == 503, receipt  # the failed tool attempt stops the execution
    status, receipt = command(run_a, "recover")  # the owner's recovery asks for attempt 2
    assert status == 200 and receipt["phase"] == "awaiting_human", receipt
    approve_attempt(run_a, 2)
    status, receipt = command(run_a, "recover")
    assert status == 200 and receipt["phase"] == "completed", receipt
    run_b = start(executor.refs["api_budget"])  # a second, API-priced run waiting on the owner at the gate
    return {"run_id": run_a, "waiting_run_id": run_b, "work_id": work_ref.id, "label": LABEL}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    if os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY"):
        raise RuntimeError("the trace fixture never runs with a live provider key set")
    monkeypatch = MonkeyPatch()
    tool_state = gate_fixture.start_worker(owned, monkeypatch)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)  # accept (queue) before the URL is announced
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    claude = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=4, max_output_tokens=512),
                               transport=httpx2.MockTransport(Spy(responder)), ceiling_rates=CEILING_RATES)
    executor = TraceExecutor(claude, {})
    # installed as the product's exact Claude executor (so the connection keeps the scripted
    # transport); its compilation and scheduling are this fixture's host wiring
    claude.compile = executor.compile
    claude.scheduler = executor.scheduler
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=claude)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                           timeout_graceful_shutdown=3))

    def seed_when_started():
        # the ledger's startup reconciliation runs in the server's lifespan: the scripted
        # actor's runs start only after it, in-process through the owner's routes
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.05)
        try:
            announced = seed(app, profile, capability, executor, tool_state)
        except BaseException as error:  # noqa: BLE001 - the fixture fails loudly and stops
            print(f"TRACE_SEED_FAILED={type(error).__name__}: {error}", flush=True)
            server.should_exit = True
            return
        print(f"TRACE_SEED={json.dumps(announced, separators=(',', ':'))}", flush=True)
        print(f"TRACE_URL={profile.http_origin}{profile.base_path}", flush=True)

    threading.Thread(target=seed_when_started, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        monkeypatch.undo()


if __name__ == "__main__":
    main()
