"""Finite test-owned supported app for the T045 browser case: two recorded runs' worth of
seeds (a three-page PDF with a text note, and a DOCX) and the isolated document service
running as a SEPARATE PROCESS (`app.tests.support.document_worker_harness`) that the
supported factory reaches through its frame-only client. The browser test starts the runs
itself through the owner's consent and run routes. No model, tool or paid call."""
import argparse
import base64
import io
import json
import os
import secrets
import socket
import subprocess
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
from app.tests.support.document_worker_harness import process_client  # noqa: E402
from app.tests.test_graph_contract import parse  # noqa: E402
from app.tests.test_graph_execution import linear_graph  # noqa: E402
from app.tests.test_runs_api import Executor  # noqa: E402
from app.tests.test_server_api_v1 import immutable  # noqa: E402

STAMP = "2026-09-25T00:00:00.000000Z"
REPOSITORY = Path(__file__).resolve().parents[3]
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def pdf_bytes():
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    drawing = canvas.Canvas(buffer, pagesize=(612, 792))
    for number in range(3):
        drawing.setFont("Helvetica", 64)
        drawing.drawString(120, 600, f"Page {number + 1}")
        drawing.rect(100, 200, 400, 80 + number * 60, fill=1)
        drawing.showPage()
    drawing.save()
    return buffer.getvalue()


def docx_bytes():
    from docx import Document

    document = Document()
    document.add_paragraph("브라우저 확인용 문서 본문")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def result(domain, outputs, identity):
    roots = domain.roots()
    artifacts = []
    for index, (role, media, data) in enumerate(outputs):
        blob = domain.put_blob(data, purpose="operational")
        artifacts.append({"ordinal": index, "role": role, "media_type": media, "blob": blob.as_dict()})
    record = ImmutableRecord.create(
        kind="artifact", id=identity, version=1, created_at_utc=STAMP, actor_ref=roots.actor, parent_refs=(),
        purpose="operational", access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content={"schema_version": "fixture-output-v1", "output": {}, "artifacts": artifacts})
    domain.put(record)
    return record.ref


def seal(domain):
    roots = domain.roots()
    policy = BudgetPolicy.create(
        profile="execution", provider_mode="subscription", max_model_calls=3, max_tool_calls=5,
        max_node_visits=7, max_loop_rounds=2, max_output_bytes=1_000, max_concurrency=2,
        max_wall_seconds=60, max_candidates=1)
    refs = {"work_revision_ref": immutable(domain, roots, "work_revision").ref.as_dict(),
            "environment_ref": immutable(domain, roots, "environment").ref.as_dict(),
            "budget_policy_ref": immutable(domain, roots, "budget_policy",
                                           content=policy.domain_content()).ref.as_dict()}
    graphs = [immutable(domain, roots, "graph", content={
        "design_kind": "functional_graph", "design": encode_design_refs(parse(linear_graph()).as_dict())}).ref.as_dict()
        for _ in range(2)]
    results = [result(domain, [("paper", "application/pdf", pdf_bytes()), ("note", "text/plain", "메모\n".encode())],
                      "4f5a8c2e-7a1f-4d1e-9d0e-0a5b6c7d8e01"),
               result(domain, [("draft", DOCX, docx_bytes())], "4f5a8c2e-7a1f-4d1e-9d0e-0a5b6c7d8e02")]
    return refs, graphs, results


class SwitchingExecutor(Executor):
    """Each started run produces the next sealed result (a run executes on creation)."""

    def __init__(self, results):
        super().__init__()
        self._results = list(results)
        self._run_results = {}

    def scheduler(self, compiled, *, ledger, run_id, approvals, retry=False):
        if run_id not in self._run_results:
            self._run_results[run_id] = self._results.pop(0) if self._results else self.result
        self.result = self._run_results[run_id]
        return super().scheduler(compiled, ledger=ledger, run_id=run_id, approvals=approvals, retry=retry)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    worker_socket = owned / "document.sock"
    secret = secrets.token_bytes(32)
    worker = subprocess.Popen([sys.executable, "-B", "-m", "app.tests.support.document_worker_harness",
                               str(worker_socket)], cwd=REPOSITORY, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    worker.stdin.write(secret.hex().encode() + b"\n")
    worker.stdin.close()
    if worker.stdout.readline().strip() != b"ready":
        raise RuntimeError("document worker did not start")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    executor = SwitchingExecutor([])
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor,
                     document_worker=process_client(worker_socket, secret))
    refs, graphs, results = seal(app.state.domain_store)
    executor._results = results
    print(f"PREVIEWS_SEED={json.dumps({'refs': refs, 'graphs': graphs}, separators=(',', ':'))}", flush=True)
    print(f"PREVIEWS_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()
        worker.kill()
        worker.wait(5)


if __name__ == "__main__":
    main()
