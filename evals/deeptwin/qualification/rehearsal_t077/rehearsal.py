"""SIMULATED T077 dress rehearsal: prepare the sets and manifests, run the offline pipeline.

THIS IS A SIMULATION AND NEVER A RELEASE QUALIFICATION (owner delegation 2026-09-25,
decisions.md "Owner delegations recorded"). Every independent-person role is simulated
(``simulated-author``, ``simulated-reviewer``, ``simulated-sealer``, ``simulated-judge``); the
author, reviewer and sealer are one Claude Code session with repository access, the offline
judge is a stub and the live judge shares the critic's provider family. The pinned profile
(``simulated_independence_profile.json``) records judge separation as NOT established.

Commands (``python -m evals.deeptwin.qualification.rehearsal_t077.rehearsal``):

``prepare --out DIR``
    Materialize both simulated sets outside the repository, write the three pre-dispatch
    manifests (offline ``sim-orchard``; live ``sim-ferry`` with the Claude judge declared
    honestly, which the manifest check refuses; live ``sim-ferry`` with no provider judge model,
    so the Claude judge's answers are logged but count as not_judged) and write their sha256s
    to ``committed_manifests.json`` in this package, to be committed before any dispatch.
``offline --out DIR --commit REF``
    Run the whole pipeline for ``sim-orchard`` through the T077 dispatcher, the pinned harness
    and the Claude rig over the OFFLINE FAKE PROVIDER SERVER (``claude_mock.MockClaude``; zero
    cost), admitting the fake server as a named test double for this run only; then probe that
    the spent set is refused.

The live subset runner is ``rehearsal_live_subset.py`` (a ``_live_`` module; regressions skip it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from app.critic_contract import CONTRACT_VERSION, PARSER_VERSION
from evals.deeptwin import q01_release_manifest
from evals.deeptwin.harness.q01_harness import critic_prompt_digest, harness_identity
from evals.deeptwin.q01_release_manifest import critic_configuration_digest, lens_refs_and_digests, planned_slots
from evals.deeptwin.qualification.dispatch import (
    AttemptLedger,
    Dispatcher,
    DispatchPlan,
    DispatchRefused,
    Pricing,
    Reservation,
    SpendMeter,
)
from evals.deeptwin.verifiers import claude_judge
from evals.deeptwin.verifiers.sealed_critic import verifier_identity

from . import simulated_sets
from .simulated_actors import STUB_JUDGE_IDENTITY, STUB_JUDGE_MODEL, STUB_JUDGE_PROMPT_DIGEST

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[3]
PROFILE = PACKAGE / "simulated_independence_profile.json"
COMMITTED = PACKAGE / "committed_manifests.json"
CALIBRATION_PLAN = REPO_ROOT / "evals/deeptwin/qualification/calibration/run_plan.json"
LENS_PACK = {"id": "t077-rehearsal-no-lens", "version": "1", "rules": []}
OFFLINE_WORLD, LIVE_WORLD = "sim-orchard", "sim-ferry"
LIVE_CASES = (("good", None), ("q1", None))  # the owner cap: 2 cases x 3 repetitions
DATE = "2026-09-25"
AUTHORITY = ("owner delegation 2026-09-25 (decisions.md 'Owner delegations recorded'): SIMULATED dress rehearsal "
             "of T077; independent-person steps simulated; not a release run and never a release qualification")


def calibration_plan() -> dict:
    return json.loads(CALIBRATION_PLAN.read_text(encoding="utf-8"))


def pricing() -> Pricing:
    spend = calibration_plan()["spend"]
    return Pricing(float(spend["input_usd_per_million_tokens"]), float(spend["output_usd_per_million_tokens"]))


# The two critic configurations (run through the product adapter's rig; the model string is data:
# the offline one is the fake server's model, the live one is read from the calibration plan).
def offline_settings() -> dict:
    from evals.deeptwin.tests.claude_mock import PLAN_MODEL
    return {"model": PLAN_MODEL, "effort": "medium", "max_tokens": 1000, "call_seconds": 30,
            "run_seconds": 600.0, "max_proposed_chains": 0, "usd_hard_stop": 25.0}


def live_settings() -> dict:
    plan = calibration_plan()
    return {"model": plan["critic"]["model"], "effort": plan["critic"]["effort"], "max_tokens": 8000,
            "call_seconds": 180, "run_seconds": 1800.0, "max_proposed_chains": 0, "usd_hard_stop": 3.00,
            "judge_model": plan["judge"]["model"], "judge_effort": "low", "judge_max_tokens": 1000}


def configuration(settings: dict, task_dir: Path) -> dict:
    return {"provider": "claude", "mode": "api", "model": settings["model"], "effort": settings["effort"],
            "max_tokens": settings["max_tokens"], "critic_prompt_digest": critic_prompt_digest(task_dir),
            "contract_version": CONTRACT_VERSION, "parser_version": PARSER_VERSION,
            "max_proposed_chains": settings["max_proposed_chains"],
            # claude_rig's harness deadline is the adapter's call deadline + 15 s
            "call_and_run_deadlines": {"call_seconds": float(settings["call_seconds"] + 15),
                                       "run_seconds": settings["run_seconds"]},
            "lens_refs_and_digests": lens_refs_and_digests(LENS_PACK)}


def attestation(role: str) -> dict:
    return {"name": role, "attested_on": DATE,
            "statement": (f"SIMULATED {role}: performed by one Claude Code session with full repository access "
                          "(the same session for author, reviewer and sealer). release-v7 excludes such an "
                          "actor; this attestation supports no qualification.")}


def manifest(set_info: dict, settings: dict, *, run_dir: Path, order: list, judge_identity: str,
             judge_prompt_digest: str | None, judge_model: str | None, critic_transport: dict,
             authority: str, prior: list | None = None) -> dict:
    task_dir = Path(set_info["task_dir"])
    config = configuration(settings, task_dir)
    prior = list(prior or [])
    return {
        "schema": "q01-pre-dispatch-manifest-5", "design_id": "q01-release-v7",
        "critic_configuration": config, "critic_configuration_digest": critic_configuration_digest(config),
        "run_identity": {
            "sealed_dataset_sha256": set_info["sealed_dataset_sha256"],
            "sealed_expectations_sha256": set_info["sealed_expectations_sha256"],
            "judge_identity": judge_identity, "judge_prompt_digest": judge_prompt_digest, "judge_model": judge_model,
            "sealed_case_sha256s": set_info["sealed_case_sha256s"],
            "trial_base_dir": {"path": str(run_dir / "trials")},
            "independence_profile": {"path": str(PROFILE.relative_to(REPO_ROOT)),
                                     "sha256": hashlib.sha256(PROFILE.read_bytes()).hexdigest()},
            "harness": harness_identity(), "verifier": verifier_identity(),
            "case_order": {"seed": "simulated rehearsal: fixed by simulated-sealer", "order": order},
            "authority_ref": authority, "usd_hard_stop": settings["usd_hard_stop"],
            "planned_slots": planned_slots(order),
            "dispatch_journal": {"path": str(run_dir / "dispatch-journal.jsonl")},
            "critic_transport": critic_transport},
        "attempt": len(prior) + 1, "prior_attempts": prior,
        "attestations": {"author": attestation("simulated-author"), "reviewer": attestation("simulated-reviewer"),
                         "sealing": attestation("simulated-sealer")},
        "lens_effect": None,
    }


def _write(path: Path, value) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def prepare(out: Path) -> dict:
    from evals.deeptwin.tests.claude_mock import MOCK_TRANSPORT_NAME
    out = Path(out)
    sets = {world: simulated_sets.materialize(world, out / "sets") for world in (OFFLINE_WORLD, LIVE_WORLD)}
    offline = sets[OFFLINE_WORLD]
    offline_manifest = manifest(
        offline, offline_settings(), run_dir=out / "runs" / "offline", order=sorted(offline["sealed_case_sha256s"]),
        judge_identity=STUB_JUDGE_IDENTITY, judge_prompt_digest=STUB_JUDGE_PROMPT_DIGEST, judge_model=STUB_JUDGE_MODEL,
        critic_transport={"injected": True, "name": MOCK_TRANSPORT_NAME},
        authority=AUTHORITY + "; offline over the fake provider server (zero cost)")
    live = sets[LIVE_WORLD]
    ids = simulated_sets.case_ids(LIVE_WORLD)
    first = [ids[key] for key in LIVE_CASES]
    order = first + sorted(case_id for case_id in live["sealed_case_sha256s"] if case_id not in first)
    settings = live_settings()
    live_authority = (AUTHORITY + "; live subset through the Claude API rig, owner cap 2 cases x 3 repetitions, "
                      "USD hard stop 3.00, no retry, no model fallback")
    common = {"run_dir": out / "runs" / "live", "order": order, "judge_identity": "simulated-judge",
              "judge_prompt_digest": claude_judge.prompt_digest(),
              "critic_transport": {"injected": False, "name": None}}
    # declared honestly: the Claude judge's model is the critic's family (the manifest check refuses it)
    same_family = manifest(live, settings, judge_model=settings["judge_model"], authority=live_authority, **common)
    # dispatched: no provider judge model, so the Claude judge's logged answers count as not_judged
    dispatched = manifest(live, settings, judge_model=None, authority=live_authority, **common)
    paths = {"offline": out / "manifests" / "offline-sim-orchard.json",
             "live_same_family_judge": out / "manifests" / "live-sim-ferry-same-family-judge.json",
             "live": out / "manifests" / "live-sim-ferry.json"}
    shas = {"offline": _write(paths["offline"], offline_manifest),
            "live_same_family_judge": _write(paths["live_same_family_judge"], same_family),
            "live": _write(paths["live"], dispatched)}
    record = {
        "schema": "t077-rehearsal-committed-manifests-1", "simulated": True,
        "statement": ("SIMULATED dress rehearsal (owner delegation 2026-09-25): these manifest sha256s are committed "
                      "before any dispatch as release-v7 pre_dispatch.freeze requires. Not a release qualification."),
        "out_dir": str(out),
        "manifests": [{"label": label, "path": str(paths[label]), "sha256": shas[label]} for label in paths],
        "sets": [{"world": world, "task_dir": info["task_dir"], "expectations_path": info["expectations_path"],
                  "sealed_dataset_sha256": info["sealed_dataset_sha256"],
                  "sealed_expectations_sha256": info["sealed_expectations_sha256"],
                  "case_count": len(info["sealed_case_sha256s"])} for world, info in sets.items()],
        "profile": {"path": str(PROFILE.relative_to(REPO_ROOT)), "sha256": hashlib.sha256(PROFILE.read_bytes()).hexdigest()},
    }
    COMMITTED.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return record


def committed(label: str) -> dict:
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    entry = next(item for item in data["manifests"] if item["label"] == label)
    return {**entry, "out_dir": Path(data["out_dir"])}


def set_info(world: str) -> dict:
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    return next(item for item in data["sets"] if item["world"] == world)


@contextmanager
def admitted(name: str):
    """Admit the offline fake provider server as a named test double for this rehearsal only."""
    before = q01_release_manifest.TEST_DOUBLE_TRANSPORTS
    if before != frozenset():
        raise RuntimeError("release-v7 names no test double; refusing to extend a modified value")
    q01_release_manifest.TEST_DOUBLE_TRANSPORTS = frozenset({name})
    try:
        yield
    finally:
        q01_release_manifest.TEST_DOUBLE_TRANSPORTS = before


def plan_for(label: str, commit: str, *, meter: SpendMeter, reservation: Reservation, max_slots=None) -> DispatchPlan:
    entry = committed(label)
    out = entry["out_dir"]
    world = OFFLINE_WORLD if label == "offline" else LIVE_WORLD
    info = set_info(world)
    run_dir = out / "runs" / ("offline" if label == "offline" else "live")
    return DispatchPlan(manifest_path=Path(entry["path"]), committed_sha256=entry["sha256"],
                        commit_ref={"kind": "git_commit", "ref": commit}, task_dir=Path(info["task_dir"]),
                        expectations_path=Path(info["expectations_path"]), profile_path=PROFILE,
                        lens_pack=dict(LENS_PACK), ledger=AttemptLedger(out / "attempt-ledger.json"), meter=meter,
                        reservation=reservation, run_dir=run_dir / "report", max_slots=max_slots,
                        commit_repo=REPO_ROOT,
                        labels={"simulated": True, "label": label,
                                "not_a_release_qualification": "simulated actors; judge separation not established"})


def run_offline(commit: str) -> dict:
    from evals.deeptwin.harness.claude_rig import claude_rig
    from evals.deeptwin.tests.claude_mock import MOCK_TRANSPORT_NAME, SECRET, MockClaude

    from .simulated_actors import SimulatedCritic, SimulatedJudgeStub

    entry = committed("offline")
    run_dir = entry["out_dir"] / "runs" / "offline"
    settings = offline_settings()
    meter = SpendMeter(pricing(), run_dir / "spend.jsonl")
    reservation = Reservation(pricing(), critic_max_tokens=settings["max_tokens"],
                              max_proposed_chains=settings["max_proposed_chains"])
    plan = plan_for("offline", commit, meter=meter, reservation=reservation)
    with admitted(MOCK_TRANSPORT_NAME):
        mock = MockClaude(SimulatedCritic(OFFLINE_WORLD))
        (run_dir / "rig").mkdir(parents=True, exist_ok=True)
        rig = claude_rig(run_dir / "rig", secret=SECRET, model_id=settings["model"], effort=settings["effort"],
                         transport=mock.transport, transport_name=MOCK_TRANSPORT_NAME,
                         max_tokens=settings["max_tokens"], call_seconds=settings["call_seconds"],
                         run_seconds=settings["run_seconds"], max_proposed_chains=settings["max_proposed_chains"],
                         guard=meter)
        outcome = Dispatcher(plan, turn=rig.attested_turn, config=rig.config, judge=SimulatedJudgeStub()).run()
        probes = spent_set_probes(plan, rig, commit)
    (run_dir / "report" / "probes.json").write_text(json.dumps(probes, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"suite_outcome": outcome["suite"]["suite_outcome"], "reasons": outcome["suite"]["reasons"],
            "gate": outcome["gate"], "dispatch": outcome["dispatch"], "fake_requests": len(mock.requests()),
            "probes": probes}


def spent_set_probes(plan: DispatchPlan, rig, commit: str) -> list:
    """After the offline attempt: the same manifest, and a second attempt on the same set, are refused."""
    probes = []
    try:
        Dispatcher(plan, turn=rig.attested_turn, config=rig.config).dispatch()
        probes.append({"probe": "rerun_same_manifest", "refused": False})
    except DispatchRefused as refused:
        probes.append({"probe": "rerun_same_manifest", "refused": True, "errors": list(refused.errors)})
    original = json.loads(Path(plan.manifest_path).read_bytes())
    prior = plan.ledger.prior_attempts(original["critic_configuration_digest"])
    second = {**original, "attempt": len(prior) + 1, "prior_attempts": prior,
              "run_identity": {**original["run_identity"],
                               "dispatch_journal": {"path": str(Path(plan.run_dir).parent / "probe-journal.jsonl")}}}
    path = Path(plan.run_dir).parent / "probe-attempt-2-manifest.json"
    sha = _write(path, second)
    probe_plan = DispatchPlan(**{**plan.__dict__, "manifest_path": path, "committed_sha256": sha})
    try:
        Dispatcher(probe_plan, turn=rig.attested_turn, config=rig.config).dispatch()
        probes.append({"probe": "attempt_2_on_the_spent_set", "refused": False})
    except DispatchRefused as refused:
        probes.append({"probe": "attempt_2_on_the_spent_set", "refused": True, "errors": list(refused.errors)})
    return probes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--out", required=True, type=Path)
    off = sub.add_parser("offline")
    off.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare(args.out)
    else:
        result = run_offline(args.commit)
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
