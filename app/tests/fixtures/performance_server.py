"""Finite test-owned supported app for the T080 responsiveness measurement.

It seeds the plan's declared workload: one recorded run over a 20-node / 40-edge graph
(19 artifact hand-offs and 21 observation edges; the code-owned test executor seals one
text artifact per node) and 1,000 public events, so the records log pages through a
full thousand. The browser test starts the run through the owner's own consent and run
routes. No model, tool or paid call; every seeded fact is synthetic test-actor data."""
import argparse
import base64
import json
import os
import socket
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.domain.public_events import _append_event_in_transaction  # noqa: E402
from app.domain.refs import ObjectRef  # noqa: E402
from app.domain.schemas import ImmutableRecord  # noqa: E402
from app.domain.store import _writer  # noqa: E402
from app.operations.session_root import initialize_session_root  # noqa: E402
from app.operations.setup import (  # noqa: E402
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.runtime.budgets import BudgetPolicy  # noqa: E402
from app.server import create_app  # noqa: E402
from app.services.design_persistence import encode_design_refs  # noqa: E402
from app.tests.test_graph_contract import artifact_edge, graph_value, input_slot, node, output_slot, parse  # noqa: E402
from app.tests.test_runs_api import Executor  # noqa: E402
from app.tests.test_server_api_v1 import immutable  # noqa: E402

STAMP = "2026-09-25T00:00:00.000000Z"
NODES = 20
EVENTS = 1_000


def workload_graph():
    raw = graph_value()
    ids = [f"n{index:02d}" for index in range(NODES)]
    raw["nodes"] = [node(name, "deterministic", f"단계 {index + 1}",
                         inputs=[] if index == 0 else [input_slot("in", "text-document")],
                         outputs=[output_slot("out", "text-document")]) for index, name in enumerate(ids)]
    edges = [artifact_edge(f"a{index:02d}", ids[index], "out", ids[index + 1], "in", "text-document")
             for index in range(NODES - 1)]
    for index in range(40 - len(edges)):
        source = index % (NODES - 1)
        edges.append({"edge_id": f"o{index:02d}", "kind": "observation", "source_node_id": ids[source],
                      "target_node_id": ids[source + 1], "loop_id": None, "observation_name": f"obs-{index:02d}"})
    raw["edges"] = edges
    raw["entry_node_ids"] = ["n00"]
    raw["completion_criteria"] = [{"criterion_id": "final", "node_id": ids[-1], "output_slot": "out",
                                   "artifact_contract_id": "text-document", "min_items": 1}]
    raw["model_bindings"], raw["tool_bindings"], raw["memory_policies"], raw["grant_refs"] = [], [], [], []
    for item in raw["nodes"]:
        item["grant_refs"] = []
    return raw


def seal(domain):
    roots = domain.roots()
    policy = BudgetPolicy.create(
        profile="execution", provider_mode="subscription", max_model_calls=3, max_tool_calls=5,
        max_node_visits=NODES + 5, max_loop_rounds=2, max_output_bytes=1_000, max_concurrency=2,
        max_wall_seconds=60, max_candidates=1)
    graph = immutable(domain, roots, "graph", content={
        "design_kind": "functional_graph", "design": encode_design_refs(parse(workload_graph()).as_dict())})
    blob = domain.put_blob("합성 산출물\n".encode(), purpose="operational")
    result = ImmutableRecord.create(
        kind="artifact", id="5e4a8c2e-7a1f-4d1e-9d0e-0a5b6c7d8e9f", version=1, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"schema_version": "fixture-output-v1", "output": {},
                 "artifacts": [{"ordinal": 0, "role": "report", "media_type": "text/plain", "blob": blob.as_dict()}]})
    domain.put(result)
    refs = {"graph_ref": graph.ref.as_dict(),
            "work_revision_ref": immutable(domain, roots, "work_revision").ref.as_dict(),
            "environment_ref": immutable(domain, roots, "environment").ref.as_dict(),
            "budget_policy_ref": immutable(domain, roots, "budget_policy",
                                           content=policy.domain_content()).ref.as_dict()}
    # the declared 1,000-row event page: synthetic events on the real public event journal
    with _writer(), domain._connection(write=True) as db:
        for index in range(EVENTS):
            stamp = f"2026-09-25T00:{index // 60 % 60:02d}:{index % 60:02d}.{index:06d}Z"
            _append_event_in_transaction(
                db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
                actor_kind="system", actor_ref=roots.actor, event_type="work.revised",
                object_refs=(ObjectRef(result.ref.kind, result.ref.id, result.ref.version, result.ref.sha256),),
                correlation_id=str(uuid5(NAMESPACE_URL, f"deeptwin:perf-event:{index}")), causation_id=None,
                status="succeeded", error_code=None, public_metadata={"revision": index + 1, "source_count": 0}, private_evidence_refs=(),
                retention_class="core", policy_ref=roots.access_policy)
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
    sock.listen(128)
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    executor = Executor()
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor)
    executor.result, refs = seal(app.state.domain_store)
    print(f"PERFORMANCE_SEED={json.dumps(refs, separators=(',', ':'))}", flush=True)
    print(f"PERFORMANCE_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
