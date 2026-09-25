"""Gated live entry for the frozen initial Q01 calibration (makes paid API calls).

Skipped unless ``DEEPTWIN_LIVE_Q01=1``, ``DEEPTWIN_LIVE_ANTHROPIC_API_KEY`` and
``DEEPTWIN_LIVE_EVIDENCE_PATH`` are all set. The key variable is read only after
the explicit opt-in flag. Results are written to a fresh directory under the
evidence path; the key is never written. Outcomes are calibration observations,
so this test asserts only the run's integrity, never a verdict.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evals.deeptwin.qualification.calibration.run_calibration import (
    assert_secret_absent,
    load_plan,
    run,
)


def _live_settings():
    if os.environ.get("DEEPTWIN_LIVE_Q01") != "1":
        return None
    evidence = os.environ.get("DEEPTWIN_LIVE_EVIDENCE_PATH")
    key = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
    if not evidence or not key:
        return None
    return key, Path(evidence)


def test_live_q01_initial_calibration():
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Q01 calibration requires DEEPTWIN_LIVE_Q01=1, DEEPTWIN_LIVE_ANTHROPIC_API_KEY "
                    "and DEEPTWIN_LIVE_EVIDENCE_PATH")
    key, evidence = settings
    plan = load_plan()[0]
    out = evidence.resolve() / f"q01-calibration-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    # DEEPTWIN_LIVE_Q01_CONTINUE names an earlier results.json of this plan: only its
    # not_run cases run (the verified ones carry over unchanged)
    results = run(key, out, continue_from=os.environ.get("DEEPTWIN_LIVE_Q01_CONTINUE") or None)
    written = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert written["plan_sha256"] == results["plan_sha256"]
    assert len(written["trials"]) == len(plan["cases"])
    assert written["totals"]["estimated_usd"] <= plan["spend"]["hard_stop_usd"]
    assert_secret_absent(out, key)
    summary = {"out_dir": str(out), "setup_error": written["setup_error"], "suite": written["suite"],
               "not_run": written["not_run"], "totals": written["totals"],
               "trials": [(t["case_key"]["candidate_id"], t["case_key"]["counterexample_id"], t["verdict"], t["cause"])
                          for t in written["trials"]]}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
