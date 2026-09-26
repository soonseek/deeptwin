"""Finite test-owned supported app for the owner's inquiry flow in a real browser (T060).

The real supported factory over a fresh owned directory, whose run executor is the Claude
executor over an in-process mock transport — no network, key or paid call. The scripted
transport answers the run's writer with a fixed text, a diagnosis turn with two competing
hypotheses, and an inquiry turn with one proposed question (questions only, never an
answer). Once the browser's test actor has connected Claude and chosen a model through the
product routes, the fixture seals a graph that binds exactly that owner-chosen model, plus
a work revision, environment and budget, and announces their refs. Scripted test actor
only: nothing here stands in for a real person.
"""
import argparse
import base64
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import httpx2
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.domain.refs import EntityRef  # noqa: E402
from app.operations.session_root import initialize_session_root  # noqa: E402
from app.operations.setup import (  # noqa: E402
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.runtime.budgets import BudgetPolicy  # noqa: E402
from app.server import create_app  # noqa: E402
from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits  # noqa: E402
from app.services.design_persistence import encode_design_refs  # noqa: E402
from app.tests.test_claude_api import Spy, complete_text_stream, model, model_page, response  # noqa: E402
from app.tests.test_claude_design_turn import EFFORTS  # noqa: E402
from app.tests.test_graph_contract import parse  # noqa: E402
from app.tests.test_graph_execution import linear_graph  # noqa: E402
from app.tests.test_server_api_v1 import immutable  # noqa: E402

WRITER_TEXT = "첫 줄\n둘째 줄\n셋째 줄\n"
COMPETING = json.dumps({"hypotheses": [
    {"family": "system", "claim": "작성 노드가 원자료의 표현 규칙을 받지 못했다.",
     "conditions": ["인계가 요약뿐일 때"], "predictions": ["규칙을 인계하면 차이가 사라진다"]},
    {"family": "expert_judgment", "claim": "소유자는 둘째 줄을 더 구체적으로 쓴다.",
     "conditions": ["보고서의 핵심 문장일 때"], "predictions": ["다른 문서에서도 같은 수정이 나타난다"]},
]}, ensure_ascii=False)
QUESTIONS = json.dumps({"questions": [
    {"text": "다른 보고서에서도 둘째 줄을 이렇게 고치십니까?", "hypothesis_ids": ["system-0", "expert_judgment-1"]},
]}, ensure_ascii=False)


def responder(request, body):
    if request.url.path == "/v1/models":
        return response(request, payload=model_page([model(capabilities=EFFORTS)]))
    if b"diagnosis worker" in body:
        answer = COMPETING
    elif b"inquiry worker" in body:
        answer = QUESTIONS
    else:
        answer = WRITER_TEXT
    return response(request, body=complete_text_stream(answer), headers={"content-type": "text/event-stream"})


def seal_when_chosen(domain, stop):
    """Once the owner's model choice exists, seal the run inputs that bind it."""

    while not stop.is_set():
        with domain._connection() as db:
            row = db.execute("SELECT id, version, sha256 FROM domain_records WHERE kind='model_choice' "
                             "ORDER BY rowid LIMIT 1").fetchone()
        if row is None:
            time.sleep(0.05)
            continue
        choice = EntityRef("model_choice", row["id"], row["version"], row["sha256"])
        roots = domain.roots()
        policy = BudgetPolicy.create(
            profile="execution", provider_mode="subscription", max_model_calls=3, max_tool_calls=5,
            max_node_visits=7, max_loop_rounds=2, max_output_bytes=1_000, max_concurrency=2,
            max_wall_seconds=60, max_candidates=1)
        budget = immutable(domain, roots, "budget_policy", content=policy.domain_content()).ref
        raw = linear_graph()
        raw["model_bindings"][0]["model_choice_ref"] = choice.as_dict()
        raw["tool_bindings"] = []
        raw["grant_refs"] = []
        raw["memory_policies"][0]["read_grant_refs"] = []
        for node in raw["nodes"]:
            node["grant_refs"] = []
            if node["kind"] == "agent":
                node["config"]["tool_binding_ids"] = []
        raw["observation_contract_ref"] = immutable(domain, roots, "observation_contract").ref.as_dict()
        raw["budget_policy_ref"] = budget.as_dict()
        graph = immutable(domain, roots, "graph", content={
            "design_kind": "functional_graph", "design": encode_design_refs(parse(raw).as_dict())}).ref
        refs = {"graph_ref": graph.as_dict(),
                "work_revision_ref": immutable(domain, roots, "work_revision",
                                               content={"text": "분기 보고서 초안을 세 줄로 써 주세요."}).ref.as_dict(),
                "environment_ref": immutable(domain, roots, "environment").ref.as_dict(),
                "budget_policy_ref": budget.as_dict()}
        print(f"INQUIRY_SEED={json.dumps(refs, separators=(',', ':'))}", flush=True)
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)  # accept (queue) before the URL is announced
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=6), transport=httpx2.MockTransport(Spy(responder)))
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor)
    stop = threading.Event()
    sealer = threading.Thread(target=seal_when_chosen, args=(app.state.domain_store, stop), daemon=True)
    sealer.start()
    print(f"INQUIRY_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        stop.set()
        sock.close()


if __name__ == "__main__":
    main()
