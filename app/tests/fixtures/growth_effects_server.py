"""Finite test-owned supported app for G-14 (T067, 2026-09-25): a prior-work queue
with a past gated send, re-evaluated in isolation without sending again.

It is the tool-gate fixture's app (app/tests/fixtures/tool_gate_server.py: the stored
tool-gated graph, the in-process extension worker on its real socket with the
TEST-ACTOR tool `test_actor_notify`, the real dispatcher and extension transport) plus
a test-owned growth driver. The owner performs the original send in the browser
(start the gated run, approve the writer's exact attempt, resume). The browser test
then writes DIR/g14-request.json naming that run; the driver — the product has no
growth driver of its own — reads the run's recorded ToolCall from the ledger and
persists three comparison plans, each with its own `tool_effect_policy`, then writes
DIR/g14-plans.json. The owner approves boundaries on the versions page (the product's
owner route records an owner decision over each exact boundary; the test actor
approves nothing) and the test writes DIR/g14-approved.json. The driver then freezes a
queue that names the recorded call by its record digest and runs three paired rounds
on the real scheduler in fresh isolated vaults, reading the approvals only through
the owner-decision reader (2026-09-25, G-14 approvals):

- REPLAY: a replay boundary the owner approved (the recorded result, bound to the ToolCall);
- SINK: an isolated sink the owner approved, the candidate sending a changed notice;
- UNAPPROVED: a replay boundary the owner left undecided (that item is not comparable).

Each queue is [an item without external effects, the item with the past send]. The
rounds and their per-item outcomes are persisted through the real growth store, so
the owner's versions page shows them. The driver writes DIR/g14-done.json with what
it observed before and after the rounds: the test-actor tool's invocation counter
(calls that reached the tool in the worker), and how many times the production
transport factory, the worker channel lookup, the authenticated worker connection
and the attempt dispatcher factory were entered (counting wrappers installed at
start). TEST ACTOR ONLY; every value is synthetic; no model, network or paid call.
"""
import argparse
import base64
import json
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from uuid import uuid4

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from _pytest.monkeypatch import MonkeyPatch

from app.domain.schemas import ImmutableRecord
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.runtime import extension_attempt_transport as xt
from app.runtime import node_attempts as na
from app.runtime.ledger import RuntimeLedger
from app.server import create_app
from app.services.comparisons import freeze_comparison_plan
from app.services.growth_store import (
    persist_comparison_plan,
    persist_comparison_round,
    persist_round_outputs,
)
from app.services.owner_decisions import PersistentOwnerDecisions
from app.services.paired_execution import (
    PairedSide,
    execute_paired_round,
    remove_isolated_runs,
)
from app.services.tool_effect_isolation import (
    ToolEffectSource,
    record_tool_effect_policy,
    recorded_effect_bindings,
)
from app.tests.fixtures import tool_gate_server as gate
from app.tests.support.tool_gate import TEST_ACTOR_TOOL
from app.tests.test_alternatives import ref
from app.tests.test_graph_contract import compile_value
from app.tests.test_graph_execution import linear_graph
from app.workers import listener

LABEL = "synthetic/test-actor"
STAMP = "2026-09-25T00:00:00.000000Z"
TOOL, VERSION = TEST_ACTOR_TOOL["tool_id"], TEST_ACTOR_TOOL["version"]
EFFECT = "external_irreversible"
COMPILED = compile_value(linear_graph())  # intake -> writer -> publish
CHANGED = b"synthetic test-actor notice, with the candidate's source line\n"
LINEAGES = {"REPLAY": "67014000-0000-4000-8000-000000000000",
            "SINK": "67014100-0000-4000-8000-000000000000",
            "UNAPPROVED": "67014200-0000-4000-8000-000000000000"}
PLAIN = {"text": "외부 효과가 없는 합성 업무", "label": LABEL}


def marks(domain):
    roots = domain.roots()
    return {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
            "retention_policy_ref": roots.retention_policy, "created_at_utc": STAMP}


def install_counters(monkeypatch):
    counts = {"transport_build": 0, "channel": 0, "connect": 0, "dispatcher_build": 0}

    def counting(name, original):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(xt.ExtensionAttemptTransport, "build",
                        classmethod(counting("transport_build", xt.ExtensionAttemptTransport.build.__func__)))
    monkeypatch.setattr(xt, "extension_channel", counting("channel", xt.extension_channel))
    monkeypatch.setattr(listener, "_connect_extension_authenticated",
                        counting("connect", listener._connect_extension_authenticated))
    monkeypatch.setattr(na.NodeAttemptDispatcher, "build",
                        classmethod(counting("dispatcher_build", na.NodeAttemptDispatcher.build.__func__)))
    return counts


def sides(candidate_payload):
    def factory(payload):
        def make(item, domain, effects):
            roots = domain.roots()

            def produce(context, view):
                if context.node_id == "writer" and "notice" in item:
                    return effects.invoke(TOOL, VERSION, (("document_source", "text/plain", payload),))
                record = ImmutableRecord.create(
                    kind="artifact", id=str(uuid4()), version=1, created_at_utc=STAMP,
                    actor_ref=roots.actor, parent_refs=(), purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                    content={"output": f"{context.node_id}:{item['text']}", "evidence_label": LABEL})
                domain.put(record)
                return record.ref

            return {"core.deterministic": produce, "core.agent": produce}
        return make

    return (PairedSide("baseline", COMPILED, factory(gate.OK_TEXT), uses_tool_effects=True),
            PairedSide("candidate", COMPILED, factory(candidate_payload), uses_tool_effects=True))


def evaluate(item, left, right):
    return {"valid": True, "reasons": [], "metrics": {"utility": "0.9"}}


def boundary(kind):
    value = {"tool_id": TOOL, "version": VERSION, "effect_class": EFFECT, "boundary": kind}
    if kind == "isolated_sink":
        value["sink_id"] = "g14-isolated-sink"
    return value


def prepare(domain, lineage_id, boundaries):
    policy = record_tool_effect_policy(domain, boundaries, **marks(domain))
    plan = freeze_comparison_plan({
        "lineage_id": lineage_id, "baseline_environment": ref("environment", 67901),
        "queue": ref("run_manifest", 67915), "quality_profile": ref("evaluation_profile", 67906),
        "evaluator_bundle": ref("rubric", 67907), "reset_manifest": ref("run_manifest", 67908),
        "allowed_changes": ref("decision_record", 67909), "tool_effect_policy": policy.as_dict(),
        "budget": ref("budget_policy", 67911), "mode": "automatic"})
    return plan, persist_comparison_plan(domain, plan, **marks(domain))


def execute(domain, source, plan, plan_record, items, candidate_payload, reset):
    lineage_id = plan.lineage_id
    baseline, candidate = sides(candidate_payload)
    paired = execute_paired_round(
        plan, items=items, baseline=baseline, candidate=candidate, evaluator=evaluate, reset_root=reset,
        declared_changes=("writer",), tool_effects=source,
        round_value={"round_id": f"{lineage_id[:5]}-round-0", "round_index": 0,
                     "candidate": ref("change_candidate", 67140), "mandatory_checks": ref("validation_report", 67925),
                     "evidence": [], "usage": ref("decision_record", 67927)})
    value = paired.result.as_dict()
    record = persist_comparison_round(domain, plan, {
        "round_id": value["round_id"], "round_index": value["round_index"], "candidate": value["candidate_ref"],
        "baseline_runs": value["baseline_run_refs"], "candidate_runs": value["candidate_run_refs"],
        "validity": value["validity"], "validity_reasons": value["validity_reasons"],
        "mandatory_checks": value["mandatory_checks_ref"], "metric_vector": value["metric_vector"],
        "utility": value["utility"], "evidence": value["evidence_refs"], "usage": value["usage_ref"]},
        plan_record_ref=plan_record, **marks(domain))
    persist_round_outputs(domain, record, paired, **marks(domain))
    remove_isolated_runs(reset)
    return {"validity": value["validity"], "validity_reasons": value["validity_reasons"],
            "item_outcomes": [dict(item) for item in paired.item_outcomes]}


ROUNDS = (("REPLAY", "replay", gate.OK_TEXT), ("SINK", "isolated_sink", CHANGED),
          ("UNAPPROVED", "replay", gate.OK_TEXT))


def prepare_plans(app, tool, counts, request):
    domain = app.state.domain_store
    bindings = recorded_effect_bindings(RuntimeLedger(domain), request["run_id"])
    before = {"tool_calls": tool["calls"], **counts}
    plans = {name: prepare(domain, LINEAGES[name], [boundary(kind)]) for name, kind, _payload in ROUNDS}
    return {"bindings": bindings, "before": before, "plans": plans}


def run_rounds(app, owned, tool, counts, prepared):
    domain = app.state.domain_store
    ledger = RuntimeLedger(domain)
    # approvals are read only as the owner's recorded decisions over each exact boundary
    decisions = PersistentOwnerDecisions(domain, app.state.owner_authority)
    source = ToolEffectSource.build(domain_store=domain, ledger=ledger, decisions=decisions)
    past = {"text": "과거 발송이 있는 합성 업무", "label": LABEL, "notice": True,
            "past_tool_effects": prepared["bindings"]}
    rounds = {}
    for name, _kind, payload in ROUNDS:
        plan, plan_record = prepared["plans"][name]
        rounds[name] = execute(domain, source, plan, plan_record, [dict(PLAIN), dict(past)], payload,
                               owned / f"reset-{name.lower()}")
    after = {"tool_calls": tool["calls"], **counts}
    return {"evidence_label": LABEL, "bindings": prepared["bindings"], "before": prepared["before"],
            "after": after, "lineages": LINEAGES, "rounds": rounds}


def wait_for(path):
    while not path.is_file():
        time.sleep(0.1)
    time.sleep(0.1)  # the file is written whole by the test
    return json.loads(path.read_text(encoding="utf-8"))


def publish(target, value):
    target.with_suffix(".tmp").write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    target.with_suffix(".tmp").replace(target)


def driver(app, owned, tool, counts):
    try:
        prepared = prepare_plans(app, tool, counts, wait_for(owned / "g14-request.json"))
        publish(owned / "g14-plans.json", {"plans": {name: record.as_dict() for name, (_plan, record)
                                                     in prepared["plans"].items()}})
    except Exception:  # noqa: BLE001 - the test reads the failure instead of waiting forever
        publish(owned / "g14-plans.json", {"error": traceback.format_exc()})
        return
    wait_for(owned / "g14-approved.json")
    try:
        result = run_rounds(app, owned, tool, counts, prepared)
    except Exception:  # noqa: BLE001 - the test reads the failure instead of waiting forever
        result = {"error": traceback.format_exc()}
    publish(owned / "g14-done.json", result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    monkeypatch = MonkeyPatch()
    tool = gate.start_worker(owned, monkeypatch)
    counts = install_counters(monkeypatch)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)  # accept (queue) before the URL is announced
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    executor = gate.ToolGateExecutor()
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(), run_executor=executor)
    seed = gate.seal(app, executor)
    threading.Thread(target=driver, args=(app, owned, tool, counts), daemon=True).start()
    print(f"G14_SEED={json.dumps(seed, separators=(',', ':'))}", flush=True)
    print(f"G14_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()
        monkeypatch.undo()


if __name__ == "__main__":
    main()
