"""Finite test-owned supported app with one recorded run that produced a text and a CSV
artifact (T054). The run is started by the browser test itself through the owner's
consent and run routes; the executor is the code-owned test executor whose only
result is the artifact record sealed here. No model, tool or paid call."""
import argparse
import base64
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
from app.runtime.budgets import BudgetPolicy  # noqa: E402
from app.server import create_app  # noqa: E402
from app.services.design_persistence import encode_design_refs  # noqa: E402
from app.tests.test_graph_contract import parse  # noqa: E402
from app.tests.test_graph_execution import linear_graph  # noqa: E402
from app.tests.test_runs_api import Executor  # noqa: E402
from app.tests.test_server_api_v1 import immutable  # noqa: E402

STAMP = "2026-09-23T00:00:00.000000Z"
TEXT = "첫 줄\n둘째 줄\n셋째 줄\n".encode()
CSV = "이름,값\n가,1\n나,2\n".encode()


def seal(domain):
    roots = domain.roots()
    policy = BudgetPolicy.create(
        profile="execution", provider_mode="subscription", max_model_calls=3, max_tool_calls=5,
        max_node_visits=7, max_loop_rounds=2, max_output_bytes=1_000, max_concurrency=2,
        max_wall_seconds=60, max_candidates=1)
    graph = immutable(domain, roots, "graph", content={
        "design_kind": "functional_graph", "design": encode_design_refs(parse(linear_graph()).as_dict())})
    artifacts = []
    for index, (role, media, data) in enumerate((("report", "text/plain", TEXT), ("table", "text/csv", CSV))):
        blob = domain.put_blob(data, purpose="operational")
        artifacts.append({"ordinal": index, "role": role, "media_type": media, "blob": blob.as_dict()})
    result = ImmutableRecord.create(
        kind="artifact", id="3e4a8c2e-7a1f-4d1e-9d0e-0a5b6c7d8e9f", version=1, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"schema_version": "fixture-output-v1", "output": {}, "artifacts": artifacts})
    domain.put(result)
    refs = {"graph_ref": graph.ref.as_dict(),
            "work_revision_ref": immutable(domain, roots, "work_revision").ref.as_dict(),
            "environment_ref": immutable(domain, roots, "environment").ref.as_dict(),
            "budget_policy_ref": immutable(domain, roots, "budget_policy",
                                           content=policy.domain_content()).ref.as_dict()}
    return result.ref, refs


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
    executor = Executor()
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor)
    executor.result, refs = seal(app.state.domain_store)
    print(f"ALTERNATIVES_SEED={json.dumps(refs, separators=(',', ':'))}", flush=True)
    print(f"ALTERNATIVES_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
