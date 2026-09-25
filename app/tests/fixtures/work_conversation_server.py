"""Finite test-owned supported owner app for the work screen's readings and conversation (T023).

The real supported factory over a fresh owned directory, with the isolated document
worker's real service in-thread and a Claude connection whose transport is an in-process
mock (a synthetic catalog and one synthetic work model): no network, key or paid call.
"""
import argparse
import base64
import os
import socket
import sys
from pathlib import Path

import httpx2
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.server import create_app
from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
from app.tests.support.document_worker_harness import in_thread_client
from app.tests.test_claude_api import (
    Spy,
    complete_text_stream,
    model,
    model_page,
    response,
)
from app.tests.test_claude_design_turn import EFFORTS
from app.tests.test_work_models import authored


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    answer = authored()

    def responder(request, body):
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model(capabilities=EFFORTS)]))
        print("MODEL_CALL=work_understanding", flush=True)
        return response(request, body=complete_text_stream(answer), headers={"content-type": "text/event-stream"})

    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=5), transport=httpx2.MockTransport(Spy(responder)))
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor,
                     document_worker=in_thread_client()[0])
    print(f"WORK_CONVERSATION_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
