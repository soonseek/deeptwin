"""SIMULATED T077 rehearsal: the owner-capped LIVE subset (makes paid Claude API calls).

A ``_live_`` module: regression runs never import or run it. It runs only when invoked as
``python -m evals.deeptwin.qualification.rehearsal_t077.rehearsal_live_subset --commit REF``
with ``DEEPTWIN_T077_LIVE=1`` and the owner-configured ``DEEPTWIN_LIVE_ANTHROPIC_API_KEY`` set;
the key is read only after that flag, handed to the rig's in-memory vault once, and never
printed, logged or written (the output directory is scanned for it afterwards).

THIS IS A SIMULATION AND NEVER A RELEASE QUALIFICATION. Owner limits: at most 2 cases x 3
repetitions (``max_slots=6``; the dispatcher then journals a stop, so the suite is
incomplete), USD hard stop 3.00 (``run_identity.usd_hard_stop``, enforced by the dispatcher
before each trial and by its spend meter before each call), no retry, no model fallback,
concurrency 1. The critic runs through the product Claude adapter with no injected transport.
The judge is the Claude judge over the same rig: the critic's own provider family. Declared
honestly (its model as ``judge_model``), the manifest check refuses it before anything is sent;
the dispatched manifest therefore names no provider judge model, so every semantic item is
not_judged by construction, and the pinned simulated profile records judge separation as not
established.
"""

from __future__ import annotations

import argparse
import json
import os

from evals.deeptwin.harness.claude_rig import claude_rig
from evals.deeptwin.qualification.calibration.run_calibration import assert_secret_absent
from evals.deeptwin.qualification.dispatch import Dispatcher, DispatchRefused, Reservation, SpendMeter
from evals.deeptwin.verifiers.claude_judge import ClaudeJudge

from .rehearsal import committed, live_settings, plan_for, pricing

MAX_SLOTS = 6  # owner cap: 2 cases x 3 repetitions


def run_live(commit: str, secret: str) -> dict:
    settings = live_settings()
    entry = committed("live")
    out = entry["out_dir"]
    run_dir = out / "runs" / "live"
    meter = SpendMeter(pricing(), run_dir / "spend.jsonl")
    reservation = Reservation(pricing(), critic_max_tokens=settings["max_tokens"],
                              max_proposed_chains=settings["max_proposed_chains"], input_bytes_bound=14_000,
                              judge_calls=1, judge_max_tokens=settings["judge_max_tokens"],
                              judge_input_bytes_bound=12_000)
    summary = {"simulated": True, "not_a_release_qualification": True}
    # 1. the honestly declared same-family judge: refused before any network call
    honest = plan_for("live_same_family_judge", commit, meter=meter, reservation=reservation, max_slots=MAX_SLOTS)
    try:
        Dispatcher(honest, turn=None, config=None).dispatch()
        summary["same_family_judge_manifest"] = {"refused": False}
    except DispatchRefused as refused:
        summary["same_family_judge_manifest"] = {"refused": True, "errors": list(refused.errors)}
    # 2. the dispatched manifest: the live critic through the product adapter, the Claude judge logged only
    (run_dir / "rig").mkdir(parents=True, exist_ok=True)
    rig = claude_rig(run_dir / "rig", secret=secret, model_id=settings["model"], effort=settings["effort"],
                     max_tokens=settings["max_tokens"], call_seconds=settings["call_seconds"],
                     run_seconds=settings["run_seconds"], max_proposed_chains=settings["max_proposed_chains"],
                     guard=meter)
    secret = ""
    judge_turn = rig.make_turn(model=settings["judge_model"], effort=settings["judge_effort"],
                               max_tokens=settings["judge_max_tokens"], role="judge", agent="q01-judge", attested=True)
    judge = ClaudeJudge(judge_turn, model_id=settings["judge_model"], identity="simulated-judge")
    plan = plan_for("live", commit, meter=meter, reservation=reservation, max_slots=MAX_SLOTS)
    outcome = Dispatcher(plan, turn=rig.attested_turn, config=rig.config, judge=judge).run()
    summary.update(catalog=rig.catalog, dispatch=outcome["dispatch"], suite_outcome=outcome["suite"]["suite_outcome"],
                   reasons=outcome["suite"]["reasons"], gate=outcome["gate"],
                   verdicts=[(r["case_id"], r["repetition"], r["verdict"], r["cause"]) for r in outcome["results"]],
                   spend=outcome["report"]["spend"])
    (run_dir / "report" / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str),
                                                     encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="SIMULATED T077 rehearsal: owner-capped live subset")
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    if os.environ.get("DEEPTWIN_T077_LIVE") != "1":
        raise SystemExit("set DEEPTWIN_T077_LIVE=1 to run the paid live subset")
    secret = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
    if not secret:
        raise SystemExit("DEEPTWIN_LIVE_ANTHROPIC_API_KEY is not set")
    summary = run_live(args.commit, secret)
    assert_secret_absent(committed("live")["out_dir"], secret)
    secret = ""
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
