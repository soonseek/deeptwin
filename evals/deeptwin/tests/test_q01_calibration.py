"""Offline tests of the frozen Q01 calibration plan and runner (mock transport only)."""

import json
import shutil

import pytest

from evals.deeptwin.harness.q01_cases import case_id_for
from evals.deeptwin.qualification.calibration import run_calibration as calibration
from evals.deeptwin.qualification.calibration.run_calibration import (
    NOT_RUN,
    PLAN_FILE,
    PROFILE_FILE,
    PlanError,
    load_plan,
    run,
)
from evals.deeptwin.tests.claude_mock import PLAN_MODEL, SECRET, MockClaude
from evals.deeptwin.tests.q01_support import ScriptedCritic
from evals.deeptwin.verifiers.critic import EXPECTED, FAIL, INVALID, NOT_JUDGED, PASS

VERDICTS = {PASS, FAIL, NOT_JUDGED, INVALID}


@pytest.fixture(autouse=True)
def prohibit_real_startup(monkeypatch):
    monkeypatch.setattr("app.codex_rpc.CodexRPC.start",
                        lambda *_args, **_kwargs: pytest.fail("real model startup forbidden"))


def no_secret(root):
    return [p for p in root.rglob("*") if p.is_file() and SECRET.encode() in p.read_bytes()]


# ---------------------------------------------------------------- plan


def test_the_frozen_plan_fixes_every_real_model_decision():
    plan, profile, plan_sha, _ = load_plan()
    assert plan["provider"] == {"provider": "claude", "mode": "api"}
    assert (plan["critic"]["model"], plan["critic"]["effort"]) == (PLAN_MODEL, "medium")
    assert plan["judge"]["model"] == PLAN_MODEL
    assert [(c["candidate_id"], c["counterexample_id"]) for c in plan["cases"]] == list(EXPECTED)
    assert all(c["case_id"] == case_id_for(c["candidate_id"], c["counterexample_id"]) for c in plan["cases"])
    assert plan["repetitions"] == 1 and plan["max_proposed_chains"] == 2 and plan["concurrency"] == 1
    assert plan["retry"]["automatic"] is False and plan["model_fallback"] is False
    assert plan["spend"]["hard_stop_usd"] == 6.0
    assert (plan["spend"]["input_usd_per_million_tokens"], plan["spend"]["output_usd_per_million_tokens"]) == (5, 25)
    assert plan["deadlines"]["call_seconds"] <= 180 < plan["deadlines"]["harness_call_seconds"]
    assert plan["critic"]["max_tokens"] > 0 and plan["judge"]["max_tokens"] > 0
    assert plan["release_heldout"] is False
    assert profile["run_plan"]["sha256"] == plan_sha
    assert profile["independence_established"] is False and profile["correlated_errors"] == "possible"
    assert profile["shared"]["provider"] is True and profile["shared"]["model"] is True
    assert profile["cases"]["release_heldout_eligible"] is False


@pytest.mark.parametrize("target", ["plan", "profile"])
def test_an_altered_plan_or_profile_is_refused(tmp_path, target):
    plan_path, profile_path = tmp_path / "run_plan.json", tmp_path / "independence_profile.json"
    shutil.copy(PLAN_FILE, plan_path)
    shutil.copy(PROFILE_FILE, profile_path)
    path = plan_path if target == "plan" else profile_path
    value = json.loads(path.read_text())
    if target == "plan":
        value["spend"]["hard_stop_usd"] = 60.0
    else:
        value["independence_established"] = True
    path.write_text(json.dumps(value))
    with pytest.raises(PlanError):
        load_plan(plan_path, profile_path)
    with pytest.raises(PlanError):
        run(SECRET, tmp_path / "out", plan_path=plan_path, profile_path=profile_path,
            transport=MockClaude(ScriptedCritic()).transport)


# ---------------------------------------------------------------- runs


def test_a_complete_offline_run_verifies_every_case_and_writes_results(tmp_path):
    mock = MockClaude(ScriptedCritic(propose=True))
    out = tmp_path / "out"
    results = run(SECRET, out, transport=mock.transport)
    written = json.loads((out / "results.json").read_text())
    assert written == json.loads(json.dumps(results))
    assert results["readiness"]["ready"] is True and results["setup_error"] is None
    assert results["independence_established"] is False and results["release_heldout"] is False
    assert results["catalog"]["model"] == PLAN_MODEL and results["judge"]["version"].startswith("claude-judge-")
    trials = results["trials"]
    assert [t["case_id"] for t in trials] == [c["case_id"] for c in load_plan()[0]["cases"]]
    assert results["not_run"] == []
    for trial in trials:
        assert trial["run_state"] == "completed_trial" and trial["verdict"] in VERDICTS
        assert set(trial["case_key"]) == {"candidate_id", "counterexample_id"}
        assert trial["score"] == {PASS: 1.0, FAIL: 0.0}.get(trial["verdict"])
        assert trial["calls"] and all(c["provider_message_id"] and c["usage_observed"] and c["state"] == "completed"
                                      and c["input_tokens"] > 0 and c["output_tokens"] == 50
                                      for c in trial["calls"] + trial["judge_calls"])
        assert len(trial["judge_items"]) == len(trial["judge_calls"])
        assert all(item["status"] == "supported" and item["reason"] for item in trial["judge_items"])
        assert (out / trial["trial_record"]).is_file()
    assert results["suite"]["complete"] is True and results["suite"]["verdict"] in VERDICTS
    assert sum(results["suite"]["counts"].values()) == 10
    totals = results["totals"]
    assert totals["calls"] == len(mock.requests()) == sum(len(t["calls"]) + len(t["judge_calls"]) for t in trials)
    assert totals["limit_reached"] is None and 0 < totals["estimated_usd"] < 6.0
    expected_usd = ((totals["input_tokens"] + totals["cache_input_tokens"]) * 5 + totals["output_tokens"] * 25) / 1e6
    assert totals["estimated_usd"] == pytest.approx(expected_usd)
    # every critic request carries the frozen critic settings
    assert all(b["model"] == PLAN_MODEL and b["output_config"] == {"effort": "medium"} and b["max_tokens"] == 16000
               for b in mock.requests("critic"))
    assert all(b["max_tokens"] == 4000 for b in mock.requests("judge"))
    assert no_secret(tmp_path) == [] and SECRET not in json.dumps(results)


def expensive(kind, system, user):
    # Byte-consistent input, heavy output: each critic call costs about $0.40.
    return len((system + user).encode()) // 4, (15000 if kind == "critic" else 3000)


def test_the_spend_stop_halts_cleanly_and_never_scores_unrun_cases(tmp_path):
    mock = MockClaude(ScriptedCritic(propose=True), usage=expensive)
    out = tmp_path / "out"
    results = run(SECRET, out, transport=mock.transport)
    totals, trials = results["totals"], results["trials"]
    assert totals["limit_reached"] == "spend_limit"
    assert totals["estimated_usd"] <= 6.0
    assert totals["calls"] == len(mock.requests())  # nothing dispatched outside the meter
    states = [t["run_state"] for t in trials]
    assert len(trials) == 10 and "not_started" in states
    first_stop = next(i for i, t in enumerate(trials) if t["verdict"] == NOT_RUN)
    assert all(t["verdict"] == NOT_RUN for t in trials[first_stop:])
    assert all(t["verdict"] != NOT_RUN and t["run_state"] == "completed_trial" for t in trials[:first_stop])
    for trial in trials[first_stop:]:
        assert trial["score"] is None and trial["scored"] is False and "verifier_result" not in trial
        assert trial["cause"] == "spend_limit"
    assert all(t["calls"] == [] for t in trials if t["run_state"] == "not_started")
    assert results["not_run"] == [t["case_id"] for t in trials[first_stop:]]
    assert results["suite"] == {"complete": False, "verdict": "incomplete", "score": None,
                                "counts": results["suite"]["counts"]}
    assert results["suite"]["counts"][NOT_RUN] == 10 - first_stop
    assert no_secret(tmp_path) == []


def test_the_pre_call_worst_case_keeps_spend_under_the_hard_stop(tmp_path):
    plan = load_plan()[0]
    meter = calibration.SpendMeter(plan)
    entry = {"system_bytes": 20_000, "user_bytes": 2_000, "max_tokens": 16000, "dispatched": True,
             "usage_observed": False}
    worst = meter.worst_case(entry)
    assert worst == pytest.approx((22_256 * 5 + 16000 * 25) / 1_000_000)
    meter.entries.append({**entry, "usage_observed": True, "input_tokens": 0, "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0, "output_tokens": int((6.0 - worst / 2) / 25e-6)})
    with pytest.raises(calibration.LimitReached):
        meter.before_call(dict(entry))
    assert meter.tripped == "spend_limit"
    # An unobserved but possibly sent call is charged at its worst case; an unsent one is free.
    assert meter.charged(entry) == worst and meter.charged({**entry, "dispatched": False}) == 0.0


def test_a_run_deadline_stops_the_active_trial_and_leaves_the_rest_not_run(tmp_path):
    now = [0.0]

    def judge(payload):
        now[0] = 10.0 ** 7  # the run deadline passes during the first trial's judgement
        return json.dumps({"verdict": "supported", "reason": "r"})

    mock = MockClaude(ScriptedCritic(), judge=judge)
    results = run(SECRET, tmp_path / "out", transport=mock.transport, clock=lambda: now[0])
    trials = results["trials"]
    assert trials[0]["run_state"] == "stopped_in_progress" and trials[0]["verdict"] == NOT_RUN
    assert trials[0]["calls"] and trials[0]["score"] is None and "verifier_result" not in trials[0]
    assert all(t["run_state"] == "not_started" and t["cause"] == "run_deadline" for t in trials[1:])
    assert results["totals"]["limit_reached"] == "run_deadline"
    assert len(mock.requests("judge")) == 1


def test_a_setup_failure_sends_no_message_and_scores_nothing(tmp_path):
    mock = MockClaude(ScriptedCritic(), models=[{**MockClaude(None).models[0], "id": "claude-absent-1",
                                                 "display_name": "claude-absent-1"}])
    results = run(SECRET, tmp_path / "out", transport=mock.transport)
    assert results["setup_error"] == "ValueError" and mock.requests() == []
    assert all(t["verdict"] == NOT_RUN and t["cause"] == "setup_failed" for t in results["trials"])
    assert results["suite"]["score"] is None and no_secret(tmp_path) == []


def test_output_must_start_empty(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "old.json").write_text("{}")
    with pytest.raises(ValueError, match="empty"):
        run(SECRET, out, transport=MockClaude(ScriptedCritic()).transport)


def test_a_continuation_runs_only_the_unrun_cases_and_completes_the_suite(tmp_path):
    first = run(SECRET, tmp_path / "first", transport=MockClaude(ScriptedCritic(propose=True), usage=expensive).transport)
    unrun = set(first["not_run"])
    assert unrun and first["suite"]["complete"] is False
    mock = MockClaude(ScriptedCritic(propose=True))
    second = run(SECRET, tmp_path / "second", transport=mock.transport,
                 continue_from=tmp_path / "first" / "results.json")
    carried = [t for t in second["trials"] if t.get("carried_over")]
    fresh = [t for t in second["trials"] if not t.get("carried_over")]
    # verified trials carry over unchanged; only the unrun cases run, and only they are billed
    assert {t["case_id"] for t in fresh} == unrun
    assert all({k: v for k, v in t.items() if k != "carried_over"} in first["trials"] for t in carried)
    assert second["totals"]["calls"] == len(mock.requests()) == sum(len(t["calls"]) + len(t["judge_calls"]) for t in fresh)
    assert second["suite"]["complete"] is True and second["not_run"] == []
    assert second["continued_from"]["totals"] == first["totals"]
    # a continuation of another plan is refused before anything runs
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**first, "plan_sha256": "0" * 64}))
    with pytest.raises(Exception):
        run(SECRET, tmp_path / "third", transport=MockClaude(ScriptedCritic()).transport, continue_from=bad)
    assert no_secret(tmp_path) == []
