"""Finite test-owned supported app for the design-arc (T038) and run-start (T048) browser
cases. The browser saves a real work through the work page; then
`POST /__test__/seed-design-arc` (a wrapper route in front of the app, never a product
route) registers the TEST-ACTOR design scenarios of `app/tests/design_arc_fixture.py`
over that work's actual revision: design requests served with a scripted generator and
a scripted critic, and a SIMULATED critic qualification (the test-only V3-verifying
design id; decisions.md 2026-09-25 — never a release qualification). Everything after
that — generation, criticism, the pool, derivations, re-review, preparation, the run
consent and the run — goes through the product's own owner routes from the page.

`--unqualified` registers the same scenarios with no qualification (production's state:
preparation refused). The run executor is the code-owned test executor compiling under the
design request's authority, whose handlers forward one synthetic artifact (no model, tool
or paid call); the owner creates the run budget through `POST /api/v1/budget-policies`
from the page.

`--design-source simulated|none` (T038, request creation from the work page): the executor
is a Claude connection whose transport is an in-process mock answering the work-understanding
turn with one synthetic work model (no network, key or paid call), so the owner drafts and
accepts a work model on the page. `simulated` configures the design workspace with the
TEST-ACTOR `DesignSource` (SIMULATED lens qualification, scripted generator and critic, the
simulated critic qualification); `none` configures nothing — production's state, where the
page states why no design request can be created."""
import argparse
import base64
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.server import create_app
from app.tests.test_runs_api import Executor
from app.tests.test_server_api_v1 import immutable


class DesignExecutor(Executor):
    """The code-owned test executor, compiling under the design request's authority."""

    def compile(self, graph):
        from app.runtime.graph import compile_graph
        from app.tests.test_design_generation import design_authority

        return compile_graph(graph, design_authority())


def with_test_routes(app, *, qualified):
    from starlette.concurrency import run_in_threadpool

    from app.tests.design_arc_fixture import seed_for_work

    async def wrapper(scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/__test__/seed-design-arc" or scope["method"] != "POST":
            return await app(scope, receive, send)
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        try:
            value = json.loads(body)
            options = {"scenarios": tuple(value["scenarios"])} if value.get("scenarios") else {}
            payload = await run_in_threadpool(seed_for_work, app, value["work_id"], qualified=qualified, **options)
            status = 200
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
    parser.add_argument("--unqualified", action="store_true")
    parser.add_argument("--no-executor", action="store_true")
    parser.add_argument("--design-source", choices=("simulated", "none"))
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
    executor = None if args.no_executor or args.design_source else DesignExecutor()
    if args.design_source:
        import httpx2

        from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
        from app.tests.test_claude_api import Spy, complete_text_stream, model, model_page, response
        from app.tests.test_claude_design_turn import EFFORTS
        from app.tests.test_work_models import authored

        answer = authored()

        def responder(request, body):
            if request.url.path == "/v1/models":
                return response(request, payload=model_page([model(capabilities=EFFORTS)]))
            return response(request, body=complete_text_stream(answer), headers={"content-type": "text/event-stream"})

        claude_executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=5),
                                            transport=httpx2.MockTransport(Spy(responder)))
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(),
                     run_executor=claude_executor if args.design_source else executor)
    if args.design_source == "simulated":
        from app.tests.design_arc_fixture import actor_source, simulated_qualification

        app.state.first_party_exports["design-workspace.service"].configure_design_source(
            actor_source(scenario="three", critic_qualification=simulated_qualification()))
    if executor is not None:
        domain = app.state.domain_store
        executor.result = immutable(domain, domain.roots(), "artifact").ref
    print("ARC_SEED={}", flush=True)
    print(f"ARC_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(with_test_routes(app, qualified=not args.unqualified), log_level="warning",
                                      access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
