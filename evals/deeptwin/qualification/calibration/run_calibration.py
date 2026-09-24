"""Initial Q01 calibration runner over the frozen RunPlan (control plane).

``run(secret, out_dir)`` loads and verifies the frozen ``run_plan.json`` and
``independence_profile.json`` (pinned by hash), checks harness readiness,
builds the Claude API rig and judge from the plan, then runs each planned case
once, sequentially, with no automatic retry and no model fallback. Each trial
is verified with the judge and the suite is aggregated only when every planned
case was verified.

Spend and deadline limits are enforced before every trial, before every call
(the call's worst case must fit) and after every call. When a limit trips, the
active trial is stopped and every remaining case is recorded ``not_run``;
neither is ever verified or scored. ``results.json`` is rewritten after every
trial. The secret is passed only to the rig's in-memory vault and is checked
to be absent from every file written under ``out_dir``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from evals.deeptwin.harness.claude_rig import MAX_CALL_SECONDS, claude_rig
from evals.deeptwin.harness.q01_cases import ENVIRONMENT_MANIFEST, TASK_DIR, case_id_for
from evals.deeptwin.harness.q01_harness import INSTRUCTION_SHA256, readiness, run_trial
from evals.deeptwin.verifiers.claude_judge import JUDGE_TEMPLATE_ID, ClaudeJudge
from evals.deeptwin.verifiers.critic import (
    EXPECTED,
    VERIFIER_VERSION,
    verify_suite,
    verify_trial,
)

HERE = Path(__file__).resolve().parent
PLAN_FILE = HERE / "run_plan.json"
PROFILE_FILE = HERE / "independence_profile.json"
# Frozen artifacts: any edit is a new plan/profile and must be re-reviewed and re-pinned.
PLAN_SHA256 = "8793d002815f454a100d0dabc33fa1cb86a71cc496ff0f3bf8018da2ea02396a"
PROFILE_SHA256 = "8862505d6d8fb5a4ca72018cf19106d3af12b8f4332c422954f0df1d2fd3581a"
RESULTS_SCHEMA = "q01-calibration-results-1"
INPUT_OVERHEAD_TOKENS = 256
NOT_RUN = "not_run"


class PlanError(ValueError):
    """The frozen plan or profile is missing, altered or inconsistent."""


class LimitReached(RuntimeError):
    """A spend or deadline limit stopped dispatch (no call was sent by this refusal)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _require(condition, message):
    if not condition:
        raise PlanError(message)


def load_plan(plan_path: Path = PLAN_FILE, profile_path: Path = PROFILE_FILE, *,
              task_dir: Path = TASK_DIR) -> tuple[dict, dict, str, str]:
    """Load the frozen plan and profile; every enforced value is re-checked here."""
    plan_bytes, profile_bytes = Path(plan_path).read_bytes(), Path(profile_path).read_bytes()
    plan_sha, profile_sha = _sha(plan_bytes), _sha(profile_bytes)
    _require(plan_sha == PLAN_SHA256, "run plan differs from the frozen, pinned plan")
    _require(profile_sha == PROFILE_SHA256, "independence profile differs from the frozen, pinned profile")
    plan, profile = json.loads(plan_bytes), json.loads(profile_bytes)
    _require(plan.get("schema") == "q01-calibration-run-plan-1", "unsupported run plan schema")
    _require(plan["provider"] == {"provider": "claude", "mode": "api"}, "the plan provider must be claude/api")
    _require(plan["task"]["instruction_sha256"] == INSTRUCTION_SHA256, "plan instruction pin differs")
    manifest_sha = _sha((Path(task_dir) / ENVIRONMENT_MANIFEST).read_bytes())
    _require(plan["task"]["environment_manifest_sha256"] == manifest_sha, "plan environment pin differs")
    manifest = json.loads((Path(task_dir) / ENVIRONMENT_MANIFEST).read_bytes())
    cases = plan["cases"]
    keys = [(item["candidate_id"], item["counterexample_id"]) for item in cases]
    _require(sorted(map(str, keys)) == sorted(map(str, EXPECTED)) and len(set(keys)) == len(keys),
             "the plan must list every development case exactly once")
    _require(all(item["case_id"] == case_id_for(*key) for item, key in zip(cases, keys)),
             "a planned case id does not match its candidate/counterexample")
    _require(sorted(item["case_id"] for item in cases) == sorted(e["case_id"] for e in manifest["cases"]),
             "planned cases differ from the environment manifest")
    _require(plan["repetitions"] == 1 and plan["concurrency"] == 1, "one repetition, concurrency 1")
    _require(plan["retry"] == {"automatic": False, "max_attempts_per_call": 1}, "automatic retry is not allowed")
    _require(plan["model_fallback"] is False, "model fallback is not allowed")
    _require(type(plan["max_proposed_chains"]) is int and 0 <= plan["max_proposed_chains"] <= 16,
             "invalid max_proposed_chains")
    deadlines = plan["deadlines"]
    _require(type(deadlines["call_seconds"]) is int and 0 < deadlines["call_seconds"] <= MAX_CALL_SECONDS,
             "call deadline exceeds the adapter ceiling")
    _require(deadlines["harness_call_seconds"] > deadlines["call_seconds"],
             "the harness call deadline must exceed the adapter deadline")
    _require(0 < deadlines["trial_seconds"] <= deadlines["run_seconds"] <= 24 * 3600, "invalid run deadlines")
    spend = plan["spend"]
    _require(spend["currency"] == "USD" and spend["hard_stop_usd"] > 0
             and spend["input_usd_per_million_tokens"] > 0 and spend["output_usd_per_million_tokens"] > 0,
             "invalid spend stop")
    for role in ("critic", "judge"):
        _require(type(plan[role]["max_tokens"]) is int and plan[role]["max_tokens"] > 0, f"invalid {role} tokens")
        _require(type(plan[role]["model"]) is str and plan[role]["model"], f"missing {role} model")
    _require(plan["judge"]["template_id"] == JUDGE_TEMPLATE_ID, "judge template differs from the plan")
    _require(plan["scoring"]["verifier_version"] == VERIFIER_VERSION, "verifier version differs from the plan")
    _require(plan["scoring"]["not_run_is_scored"] is False and plan["scoring"]["stopped_trial_is_scored"] is False,
             "not-run or stopped trials can never be scored")
    _require(plan["release_heldout"] is False, "calibration cases are never release heldout")
    _require(profile.get("schema") == "q01-independence-profile-1", "unsupported independence profile")
    _require(profile["run_plan"]["sha256"] == plan_sha, "profile names a different run plan")
    _require(profile["critic"] == {**plan["provider"], "model": plan["critic"]["model"]}
             and profile["judge"] == {**plan["provider"], "model": plan["judge"]["model"]},
             "profile critic/judge differ from the plan")
    _require(profile["independence_established"] is False and profile["correlated_errors"] == "possible",
             "a shared-provider/model judge cannot establish independence")
    _require(profile["cases"]["release_heldout_eligible"] is False, "development cases are never release heldout")
    return plan, profile, plan_sha, profile_sha


class SpendMeter:
    """Guard for the rig: estimated spend and run deadline, checked around every call."""

    def __init__(self, plan: dict, *, clock=time.monotonic):
        spend = plan["spend"]
        self.limit = float(spend["hard_stop_usd"])
        self.input_rate = float(spend["input_usd_per_million_tokens"]) / 1_000_000
        self.output_rate = float(spend["output_usd_per_million_tokens"]) / 1_000_000
        self.clock = clock
        self.deadline = clock() + float(plan["deadlines"]["run_seconds"])
        self.entries: list[dict] = []
        self.tripped: str | None = None
        self._lock = threading.Lock()

    def worst_case(self, entry: dict) -> float:
        input_bound = entry["system_bytes"] + entry["user_bytes"] + INPUT_OVERHEAD_TOKENS
        return input_bound * self.input_rate + entry["max_tokens"] * self.output_rate

    def charged(self, entry: dict) -> float:
        if entry.get("usage_observed"):
            inputs = (entry["input_tokens"] + (entry["cache_creation_input_tokens"] or 0)
                      + (entry["cache_read_input_tokens"] or 0))
            return inputs * self.input_rate + entry["output_tokens"] * self.output_rate
        if entry.get("dispatched") is False:
            return 0.0
        return self.worst_case(entry)  # sent or possibly sent, usage unknown

    @property
    def spent(self) -> float:
        with self._lock:
            return sum(self.charged(entry) for entry in self.entries)

    def _trip(self, reason: str):
        with self._lock:
            if self.tripped is None:
                self.tripped = reason
        raise LimitReached(self.tripped)

    def check(self):
        """Pre-trial check; raises ``LimitReached`` when no further work may start."""
        if self.tripped is not None:
            raise LimitReached(self.tripped)
        if self.clock() >= self.deadline:
            self._trip("run_deadline")
        if self.spent >= self.limit:
            self._trip("spend_limit")

    def before_call(self, entry: dict):
        self.check()
        if self.spent + self.worst_case(entry) > self.limit:
            self._trip("spend_limit")
        # Registered before dispatch: an in-flight or abandoned call is charged
        # at its worst case until its usage is observed.
        with self._lock:
            self.entries.append(entry)

    def after_call(self, entry: dict):
        with self._lock:
            if not any(item is entry for item in self.entries):
                self.entries.append(entry)
        entry["estimated_usd"] = round(self.charged(entry), 6)
        if self.spent >= self.limit:
            self._trip("spend_limit")
        if self.clock() >= self.deadline:
            self._trip("run_deadline")

    def totals(self) -> dict:
        with self._lock:
            entries = list(self.entries)
        observed = [e for e in entries if e.get("usage_observed")]
        return {"calls": len(entries), "calls_with_observed_usage": len(observed),
                "input_tokens": sum(e["input_tokens"] for e in observed),
                "output_tokens": sum(e["output_tokens"] for e in observed),
                "cache_input_tokens": sum((e["cache_creation_input_tokens"] or 0)
                                          + (e["cache_read_input_tokens"] or 0) for e in observed),
                "estimated_usd": round(sum(self.charged(e) for e in entries), 6),
                "hard_stop_usd": self.limit, "limit_reached": self.tripped}


def _public_call(entry: dict) -> dict:
    keys = ("index", "role", "call_id", "model", "effort", "max_tokens", "dispatched", "provider_message_id",
            "observed_model", "request_id", "input_tokens", "output_tokens", "cache_creation_input_tokens",
            "cache_read_input_tokens", "usage_observed", "stop_reason", "state", "failure", "estimated_usd")
    return {key: entry.get(key) for key in keys}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, value: dict, secret: str):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    if secret and secret in text:
        raise RuntimeError("refusing to write output that contains the credential")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def assert_secret_absent(out_dir: Path, secret: str):
    """Raise if any file under ``out_dir`` contains the credential bytes."""
    needle = secret.encode("utf-8")
    for path in Path(out_dir).rglob("*"):
        if path.is_file() and not path.is_symlink() and needle in path.read_bytes():
            raise RuntimeError("a written file contains the credential")


def _not_run(case: dict, reason: str, state: str = "not_started") -> dict:
    return {"case_id": case["case_id"],
            "case_key": {"candidate_id": case["candidate_id"], "counterexample_id": case["counterexample_id"]},
            "run_state": state, "verdict": NOT_RUN, "score": None, "cause": reason, "scored": False,
            "trial_id": None, "trial_status": None, "trial_cause": None, "boundary": None,
            "judge_items": [], "calls": [], "judge_calls": []}


def _prior(continue_from, plan_sha, profile_sha):
    """The trials of an earlier run of this exact plan, keyed by case id, when continuing.

    Only a completed run of the same frozen plan and independence profile qualifies; its
    verified trials are reused unchanged (their records stay where that run wrote them)
    and only its `not_run` cases are run again."""
    if continue_from is None:
        return None, None
    path = Path(continue_from).resolve()
    data = path.read_bytes()
    prior = json.loads(data)
    _require(prior.get("schema") == RESULTS_SCHEMA, "the continued run has another results schema")
    _require(prior.get("plan_sha256") == plan_sha and prior.get("independence_profile_sha256") == profile_sha,
             "the continued run used another plan or independence profile")
    _require(prior.get("setup_error") is None and (prior.get("readiness") or {}).get("ready") is True,
             "the continued run never reached its trials")
    trials = {trial["case_id"]: trial for trial in prior["trials"]}
    return trials, {"results_sha256": sha256(data).hexdigest(), "path": str(path),
                    "totals": prior.get("totals")}


def run(secret: str, out_dir, *, transport=None, clock=time.monotonic, plan_path: Path = PLAN_FILE,
        profile_path: Path = PROFILE_FILE, task_dir: Path = TASK_DIR, continue_from=None) -> dict:
    """Run the frozen initial calibration; returns (and writes) ``results.json`` content.

    With ``continue_from`` (an earlier ``results.json`` of the same frozen plan) only that
    run's `not_run` cases run; its verified trials are carried over unchanged and the
    spend stop applies to this run's own spend."""
    if type(secret) is not str or not secret:
        raise ValueError("an API secret is required")
    out = Path(out_dir).resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("out_dir must be empty (fresh calibration state)")
    plan, profile, plan_sha, profile_sha = load_plan(plan_path, profile_path, task_dir=task_dir)
    prior_trials, continued = _prior(continue_from, plan_sha, profile_sha)
    meter = SpendMeter(plan, clock=clock)
    results = {"schema": RESULTS_SCHEMA, "plan_id": plan["plan_id"], "plan_sha256": plan_sha,
               "independence_profile_sha256": profile_sha,
               "independence_established": profile["independence_established"],
               "correlated_errors": profile["correlated_errors"],
               "release_heldout": False, "started_at": _now(), "finished_at": None,
               "provider": plan["provider"], "critic": plan["critic"], "judge": dict(plan["judge"]),
               "catalog": None, "readiness": None, "setup_error": None, "trials": [], "suite": None,
               "not_run": [], "totals": None, "continued_from": continued}
    results_path = out / "results.json"

    def finish():
        results["totals"] = meter.totals()
        results["finished_at"] = _now()
        results["not_run"] = [t["case_id"] for t in results["trials"] if t["verdict"] == NOT_RUN]
        verified = [t["verifier_result"] for t in results["trials"] if t.get("verifier_result") is not None]
        if len(verified) == len(plan["cases"]):
            results["suite"] = {"complete": True, **verify_suite(verified)}
        else:
            counts = {}
            for trial in results["trials"]:
                counts[trial["verdict"]] = counts.get(trial["verdict"], 0) + 1
            results["suite"] = {"complete": False, "verdict": "incomplete", "score": None, "counts": counts}
        _write_json(results_path, results, secret)
        assert_secret_absent(out, secret)
        return results

    ready = readiness(task_dir)
    results["readiness"] = {"ready": ready["ready"], "checks": ready["checks"]}
    if not ready["ready"]:
        results["trials"] = [_not_run(case, "readiness_failed") for case in plan["cases"]]
        return finish()
    trials_dir = out / "trials"
    trials_dir.mkdir(mode=0o700)
    deadlines = plan["deadlines"]
    try:
        rig = claude_rig(out, secret=secret, model_id=plan["critic"]["model"], effort=plan["critic"]["effort"],
                         transport=transport, max_tokens=plan["critic"]["max_tokens"],
                         call_seconds=deadlines["call_seconds"],
                         harness_call_seconds=float(deadlines["harness_call_seconds"]),
                         run_seconds=float(deadlines["trial_seconds"]),
                         max_proposed_chains=plan["max_proposed_chains"],
                         catalog_max_age_ms=(deadlines["run_seconds"] + 600) * 1000, guard=meter)
        judge_turn = rig.make_turn(model=plan["judge"]["model"], effort=plan["judge"]["effort"],
                                   max_tokens=plan["judge"]["max_tokens"], role="judge", agent="q01-judge")
    except Exception as exc:  # noqa: BLE001 - setup failure: nothing is scored
        results["setup_error"] = type(exc).__name__
        results["trials"] = [_not_run(case, "setup_failed") for case in plan["cases"]]
        return finish()
    judge = ClaudeJudge(judge_turn, model_id=plan["judge"]["model"])
    results["catalog"] = rig.catalog
    results["judge"]["version"] = judge.version
    stop_reason = None
    for case in plan["cases"]:
        carried = None if prior_trials is None else prior_trials.get(case["case_id"])
        if carried is not None and carried.get("verdict") != NOT_RUN:
            results["trials"].append({**carried, "carried_over": True})
            _write_json(results_path, results, secret)
            continue
        if stop_reason is None:
            try:
                meter.check()
            except LimitReached as limit:
                stop_reason = limit.reason
        if stop_reason is not None:
            results["trials"].append(_not_run(case, stop_reason))
            _write_json(results_path, results, secret)
            continue
        first_call, first_judgement = len(rig.usage), len(judge.log)
        record = run_trial(case["case_id"], rig.turn, base_dir=trials_dir, config=rig.config, task_dir=task_dir)
        verification = None
        if meter.tripped is None:
            verification = verify_trial(record, judge=judge, task_dir=task_dir)
        calls = [_public_call(e) for e in rig.usage[first_call:]]
        judgements = {item["id"]: item for item in judge.log[first_judgement:]}
        entry = _not_run(case, None)
        entry.update(run_state="completed_trial", trial_id=record["trial_id"], trial_status=record["status"],
                     trial_record=f"trials/{record['trial_id']}/trial-record.json",
                     trial_cause=record["cause"],
                     calls=[c for c in calls if c["role"] == "critic"],
                     judge_calls=[c for c in calls if c["role"] == "judge"])
        if meter.tripped is not None:
            # The limit tripped inside this trial or its judgement: never verified or scored.
            stop_reason = meter.tripped
            entry.update(run_state="stopped_in_progress", cause=stop_reason)
        else:
            entry.update(verdict=verification["verdict"], score=verification["score"],
                         cause=verification["cause"], scored=verification["agent_capability_scored"],
                         boundary=verification["boundary"], verifier_result=verification,
                         judge_items=[{"id": item["id"], "status": item["status"],
                                       "reason": judgements.get(item["id"], {}).get("reason"),
                                       "reply": judgements.get(item["id"], {}).get("reply")}
                                      for item in verification["judge_items"]])
        results["trials"].append(entry)
        _write_json(results_path, results, secret)
    return finish()


__all__ = ["LimitReached", "PlanError", "SpendMeter", "assert_secret_absent", "load_plan", "run"]
