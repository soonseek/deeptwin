"""Finite test-owned supported app for the records/export browser case (T074). It seeds
only what the owner's own routes cannot create — three stored graphs (one that completes
with a text and a CSV artifact, one with a human gate, one whose handler fails), one
environment and one budget policy — and the code-owned test executor. The browser test
itself bootstraps the owner, saves the work, consents to and starts every run, records
the approval and freezes the alternative through the product routes. No model, tool or
paid call; every value is synthetic test-actor data.

T074 additions, all test-owned:
- the isolated document service runs as a SEPARATE PROCESS
  (`app.tests.support.document_worker_harness`) that the supported app reaches through its
  frame-only client, so attached PDFs are scanned and redacted in that process only;
- `--growth-rounds`: comparison rounds whose frozen plan's baseline is the seeded
  environment (plus one over an unrelated environment), produced by the real paired
  execution in fresh isolated vaults (`growth_chain_fixture.seed_environment_rounds`);
- `POST /__test__/seed-design` (a wrapper route in front of the app, not a product route):
  given a saved work id, seeds a TEST-ACTOR work model over the work's actual latest
  revision and sources and the scripted test-actor design pool over it
  (`design_workspace_fixture.open_seeded_for_work`), registered with a scripted
  test-actor critic turn and a TEST-ACTOR critic qualification, so the owner's own
  derive / review / prepare routes can run over it."""
import argparse
import base64
import copy
import json
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.domain.schemas import ImmutableRecord
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.runtime import scheduler as sch
from app.runtime.budgets import BudgetPolicy
from app.server import create_app
from app.services.design_persistence import encode_design_refs
from app.tests.support.document_worker_harness import process_client
from app.tests.test_graph_contract import graph_value, parse
from app.tests.test_graph_execution import linear_graph
from app.tests.test_runs_api import Executor
from app.tests.test_server_api_v1 import immutable

REPOSITORY = Path(__file__).resolve().parents[3]

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


def seed_design(app, work_id):
    """TEST ACTOR: the design pool over the saved work's actual latest revision."""
    from app.domain.refs import EntityRef
    from app.services.critic_qualification import critic_qualification_from_suite
    from app.tests.design_workspace_fixture import (
        CRITIC_ID,
        GENERATOR_ID,
        open_seeded_for_work,
    )
    from app.tests.test_environments import CRITIC_DIGEST, actor_record, actor_v3_design

    work = app.state.first_party_exports["works.service"].read(work_id)
    revision = EntityRef.from_dict(work["ref"])
    sources = [EntityRef.from_dict(item) for item in work.get("source_refs", [])]
    with actor_v3_design():
        qualified = critic_qualification_from_suite(actor_record(), CRITIC_DIGEST)
    request, roles = open_seeded_for_work(app, revision, sources, criticism_turn=True,
                                          critic_qualification=qualified)
    return {"request_id": request.request_id, "generator": GENERATOR_ID, "critic": CRITIC_ID,
            **{name: item.candidate_id for name, item in roles.items()}}


def with_test_routes(app):
    """The app, with one test-owned route in front of it (never part of the product)."""

    async def wrapper(scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/__test__/seed-design" or scope["method"] != "POST":
            return await app(scope, receive, send)
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        from starlette.concurrency import run_in_threadpool

        try:
            value = await run_in_threadpool(seed_design, app, json.loads(body)["work_id"])
            status, payload = 200, value
        except Exception as error:  # noqa: BLE001 - the test reads the failure class
            status, payload = 500, {"error": type(error).__name__, "detail": str(error)[:500]}
        data = json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": data})

    return wrapper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    parser.add_argument("--growth-rounds", action="store_true")
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
    worker_socket = owned / "document.sock"
    worker_secret = secrets.token_bytes(32)
    worker = subprocess.Popen([sys.executable, "-B", "-m", "app.tests.support.document_worker_harness",
                               str(worker_socket)], cwd=REPOSITORY, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    worker.stdin.write(worker_secret.hex().encode() + b"\n")
    worker.stdin.close()
    if worker.stdout.readline().strip() != b"ready":
        raise RuntimeError("document worker did not start")
    executor = RecordsExecutor()
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor,
                     document_worker=process_client(worker_socket, worker_secret))
    seed = seal(app.state.domain_store, executor)
    if args.growth_rounds:
        from app.domain.refs import EntityRef
        from app.tests.growth_chain_fixture import seed_environment_rounds

        seed["rounds"] = seed_environment_rounds(app.state.domain_store, owned / "reset",
                                                 EntityRef.from_dict(seed["environment_ref"]))
    print(f"RECORDS_SEED={json.dumps(seed, separators=(',', ':'))}", flush=True)
    print(f"RECORDS_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(with_test_routes(app), log_level="warning", access_log=False,
                                      timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()
        worker.kill()
        worker.wait(5)


if __name__ == "__main__":
    main()
