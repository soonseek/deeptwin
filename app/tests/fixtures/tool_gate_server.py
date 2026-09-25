"""Finite test-owned supported app for the gated external-tool browser case (T087,
2026-09-25). It seeds only what the owner's own routes cannot create — two stored
graphs whose `writer` binds the TEST-ACTOR tool `test_actor_notify` behind the human
gate `tool-gate` (one completes, one whose tool input fails its first call so the
owner's recovery retries it), one environment and one budget policy — and the
code-owned test executor that binds the writer to the real attempt dispatcher and the
real extension attempt transport over an in-process extension worker served on the
real socket (the same test seams the pytest `staged` fixture uses).

TEST ACTOR ONLY: `register_test_actor_tool` adds `test_actor_notify` to the worker's
tool table and to control's mirror inside THIS fixture process; the production table
is unchanged and holds no external-effect tool. The tool claims the ports'
`external_irreversible` effect class so the graph must gate it, and performs no
external effect. No model, network or paid call; every value is synthetic.
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
from uuid import uuid4

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from _pytest.monkeypatch import MonkeyPatch

from app.domain.permissions import Grant, Principal
from app.domain.schemas import Actor, ImmutableRecord
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.runtime import extension_attempt_transport as xt
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.budgets import BudgetPolicy
from app.runtime.graph import compile_graph
from app.runtime.ledger import OwnerIdentity
from app.server import create_app
from app.services.design_persistence import encode_design_refs
from app.tests import test_extension_listener as listener_fixtures
from app.tests import test_extension_probe as probe_fixtures
from app.tests.support.tool_gate import (
    FAIL_ONCE,
    register_test_actor_tool,
    tool_authority,
    tool_gated_graph,
)
from app.tests.test_extension_attempt_transport import text_input
from app.tests.test_graph_contract import parse
from app.tests.test_server_api_v1 import immutable
from app.workers import broker
from app.workers import extension_probe as ep
from app.workers.extension_execute_messages import (
    MAX_INPUT_BYTES,
    MAX_REPLY_BYTES,
)

STAMP = "2026-09-25T00:00:00.000000Z"
INSTANCE, SLOT = probe_fixtures.INSTANCE, probe_fixtures.SLOT
OK_TEXT = b"synthetic test-actor notice\n"
RETRY_TEXT = FAIL_ONCE + b" synthetic test-actor notice\n"


class _Factory:
    """The one method of pytest's tmp_path_factory the worker-tree fixture uses."""

    def __init__(self, base: Path):
        self._base = base

    def mktemp(self, name):
        path = self._base / f"{name}-{uuid4().hex[:8]}"
        path.mkdir()
        return path


def start_worker(owned: Path, monkeypatch: MonkeyPatch):
    """The in-process extension worker on its real socket, through the test seams (no
    peer credentials, synthetic mountinfo, a temporary fixed-file tree)."""

    pair = owned / "pair"
    pair.mkdir()
    channel = listener_fixtures.channel.__wrapped__(pair, monkeypatch)
    root, spec = next(channel)
    tree = probe_fixtures.worker_tree.__wrapped__(_Factory(owned), monkeypatch)
    _root, _spec, side, _tree = probe_fixtures.slot.__wrapped__((root, spec), tree, monkeypatch)
    monkeypatch.setattr(xt, "extension_channel", lambda *, instance_id, slot_number: (root, spec))
    state = register_test_actor_tool(monkeypatch)  # before the service builds its router
    service = ep.open_worker_probe_service(instance_id=INSTANCE, slot_number=SLOT)

    def serve():
        side["worker_ident"] = threading.get_ident()
        while True:
            try:
                service.serve_one(broker.Deadline.after_ms(600_000))
            except Exception:  # noqa: BLE001 - one refused exchange never stops the fixture
                time.sleep(0.05)

    threading.Thread(target=serve, daemon=True).start()
    return state


class ToolGateExecutor:
    """The code-owned test executor: the compilation authority carries the test-actor
    tool definition; `writer` is bound to the real dispatcher and the real extension
    transport in its per-attempt approval mode; every other node forwards a fixed
    synthetic artifact. Per run it keeps one attempt context (owner, principal, grant,
    deadline) so every rebuilt scheduler replays the same ledger commands."""

    def __init__(self):
        self.domain = None
        self.book = None
        self.result = None
        self.refs = None
        self.payloads = {}
        self.contexts = {}
        self.owner = OwnerIdentity(str(uuid4()), 4321, 900, str(uuid4()))

    def compile(self, graph):
        return compile_graph(graph, tool_authority())

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
        from app.domain.refs import EntityRef

        context = self._context(ledger, run_id)
        payload = self.payloads.get(compiled.graph_digest, OK_TEXT)
        transport = xt.ExtensionAttemptTransport.build(
            domain_store=self.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
            artifact_inputs=(text_input(payload),), compiled=compiled, node_id="writer",
            binding_id="source-read", ledger=ledger, approvals=approvals)
        dispatcher = na.NodeAttemptDispatcher.build(
            ledger=ledger, budget_book=self.book, owner=self.owner,
            bindings={"writer": na.AttemptBinding.create(
                envelope_ref=self.refs["envelope"], profile_ref=self.refs["profile"],
                budget_policy_ref=EntityRef.from_dict(context["policy"]), deadline_at_ms=context["deadline"],
                lease_duration_ms=60_000, model_calls=0, tool_calls=1, node_visits=1, loop_rounds=0,
                output_bytes=transport.output_bytes_bound, candidates=0, api_microunits=None,
                principal=context["principal"], grant=context["grant"],
            )},
            transport=transport, retry_after_terminal=retry,
        )

        def produce(context, view):
            return self.result

        def dispatch(context, view):
            return context.attempt.dispatch()

        handlers = {"core.deterministic": produce, "core.human_gate": produce, "core.agent": dispatch}
        return sch.build_scheduler(compiled, ledger=ledger, run_id=run_id,
                                   handlers={key: handlers[key] for _, key in compiled.handler_keys},
                                   approvals=approvals, attempts=dispatcher)


def seal(app, executor):
    domain = app.state.domain_store
    roots = domain.roots()
    executor.domain, executor.book = domain, app.state.budget_book
    policy = BudgetPolicy.create(
        profile="execution", provider_mode="subscription", max_model_calls=3, max_tool_calls=5,
        max_node_visits=9, max_loop_rounds=2, max_output_bytes=MAX_REPLY_BYTES + MAX_INPUT_BYTES,
        max_concurrency=2, max_wall_seconds=600, max_candidates=1)
    executor.refs = {"envelope": immutable(domain, roots, "execution_envelope").ref,
                     "profile": immutable(domain, roots, "runtime_profile").ref}
    graphs = {}
    retry_raw = copy.deepcopy(tool_gated_graph())
    retry_raw["nodes"][0]["responsibility"] = "합성 재시도 경로: 첫 도구 호출이 실패한다"
    for name, raw in (("gated", tool_gated_graph()), ("retry", retry_raw)):
        graph = parse(raw)
        graphs[name] = immutable(domain, roots, "graph", content={
            "design_kind": "functional_graph", "design": encode_design_refs(graph.as_dict())}).ref.as_dict()
        if name == "retry":
            executor.payloads[executor.compile(graph).graph_digest] = RETRY_TEXT
    blob = domain.put_blob(b"synthetic forwarded text\n", purpose="operational")
    result = ImmutableRecord.create(
        kind="artifact", id="6c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f", version=1, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"schema_version": "fixture-output-v1", "output": {},
                 "artifacts": [{"ordinal": 0, "role": "report", "media_type": "text/plain",
                                "blob": blob.as_dict()}]})
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
    monkeypatch = MonkeyPatch()
    start_worker(owned, monkeypatch)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)  # accept (queue) before the URL is announced
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    executor = ToolGateExecutor()
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor)
    seed = seal(app, executor)
    print(f"TOOLGATE_SEED={json.dumps(seed, separators=(',', ':'))}", flush=True)
    print(f"TOOLGATE_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()
        monkeypatch.undo()


if __name__ == "__main__":
    main()
