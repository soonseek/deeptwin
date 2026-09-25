"""Finite test-owned supported app for the records/export browser case (T074). It seeds
only what the owner's own routes cannot create — three stored graphs (one that completes
with a text and a CSV artifact, one with a human gate, one whose handler fails), one
environment and one budget policy — and the code-owned test executor. The browser test
itself bootstraps the owner, saves the work, consents to and starts every run, records
the approval and freezes the alternative through the product routes. No model, tool or
paid call; every value is synthetic test-actor data."""
import argparse
import base64
import copy
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.domain.schemas import ImmutableRecord  # noqa: E402
from app.operations.session_root import initialize_session_root  # noqa: E402
from app.operations.setup import (  # noqa: E402
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.runtime import scheduler as sch  # noqa: E402
from app.runtime.budgets import BudgetPolicy  # noqa: E402
from app.server import create_app  # noqa: E402
from app.services.design_persistence import encode_design_refs  # noqa: E402
from app.tests.test_graph_contract import graph_value, parse  # noqa: E402
from app.tests.test_graph_execution import linear_graph  # noqa: E402
from app.tests.test_runs_api import Executor  # noqa: E402
from app.tests.test_server_api_v1 import immutable  # noqa: E402

STAMP = "2026-09-25T00:00:00.000000Z"
TEXT = "첫 줄\n둘째 줄\n셋째 줄\n".encode()
CSV = "이름,값\n가,1\n나,2\n".encode()


class RecordsExecutor(Executor):
    """The test executor; a graph whose digest is listed in `failing` has handlers
    that raise, so its execution fails honestly (`run.stopped` infrastructure_failure)."""

    def __init__(self):
        super().__init__()
        self.failing = set()

    def scheduler(self, compiled, *, ledger, run_id, approvals, retry=False):
        if compiled.graph_digest not in self.failing:
            return super().scheduler(compiled, ledger=ledger, run_id=run_id, approvals=approvals, retry=retry)

        def explode(context, view):
            raise RuntimeError("synthetic handler failure")

        handlers = {key: explode for key in ("core.deterministic", "core.agent", "core.join",
                                              "core.human_gate", "core.router")}
        return sch.build_scheduler(compiled, ledger=ledger, run_id=run_id, handlers=handlers, approvals=None)


def seal(domain, executor):
    roots = domain.roots()
    policy = BudgetPolicy.create(
        profile="execution", provider_mode="subscription", max_model_calls=3, max_tool_calls=5,
        max_node_visits=7, max_loop_rounds=2, max_output_bytes=1_000, max_concurrency=2,
        max_wall_seconds=60, max_candidates=1)
    failing_raw = copy.deepcopy(linear_graph())
    failing_raw["nodes"][0]["responsibility"] = "합성 실패 경로: 원자료 정규화가 실패한다"
    graphs = {}
    for name, raw in (("completes", linear_graph()), ("gated", graph_value()), ("fails", failing_raw)):
        graph = parse(raw)
        graphs[name] = immutable(domain, roots, "graph", content={
            "design_kind": "functional_graph", "design": encode_design_refs(graph.as_dict())}).ref.as_dict()
        if name == "fails":
            executor.failing.add(executor.compile(graph).graph_digest)
    artifacts = []
    for index, (role, media, data) in enumerate((("report", "text/plain", TEXT), ("table", "text/csv", CSV))):
        blob = domain.put_blob(data, purpose="operational")
        artifacts.append({"ordinal": index, "role": role, "media_type": media, "blob": blob.as_dict()})
    result = ImmutableRecord.create(
        kind="artifact", id="5b1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e", version=1, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"schema_version": "fixture-output-v1", "output": {}, "artifacts": artifacts})
    domain.put(result)
    executor.result = result.ref
    return {"graphs": graphs,
            "environment_ref": immutable(domain, roots, "environment").ref.as_dict(),
            "budget_policy_ref": immutable(domain, roots, "budget_policy",
                                           content=policy.domain_content()).ref.as_dict()}


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
    executor = RecordsExecutor()
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor)
    seed = seal(app.state.domain_store, executor)
    print(f"RECORDS_SEED={json.dumps(seed, separators=(',', ':'))}", flush=True)
    print(f"RECORDS_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
