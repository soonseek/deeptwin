"""Offline tests of the T077 run dispatcher (``qualification/dispatch.py``).

TEST-ACTOR DEVELOPMENT DATA ONLY. The materials, expectations, critic fixture (``DevCritic``)
and judge stub (``DevJudge``) are the synthetic development data of
``test_sealed_critic_verifier.py``; every critic call streams through the Claude rig and the
product adapter to the offline FAKE PROVIDER SERVER (``claude_mock.MockClaude``; no network,
no API call, zero cost). The "USD" figures are estimates computed from the fake server's
reported token usage and test prices; nothing is paid. Nothing here is a sealed set or a
release run.

The fake server is an injected transport; release-v7 admits none, so this module admits its
name in ``q01_release_manifest.TEST_DOUBLE_TRANSPORTS`` for its duration only.
"""

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.deeptwin import q01_release_manifest
from evals.deeptwin.harness import q01_harness
from evals.deeptwin.harness.claude_rig import claude_rig
from evals.deeptwin.harness.q01_cases import case_id_for
from evals.deeptwin.qualification.dispatch import (
    AttemptLedger,
    Dispatcher,
    DispatchPlan,
    DispatchRefused,
    Pricing,
    Reservation,
    SpendMeter,
)
from evals.deeptwin.tests.claude_mock import MOCK_TRANSPORT_NAME, PLAN_MODEL, SECRET, MockClaude, Switch
from evals.deeptwin.tests.test_sealed_critic_verifier import (
    CASE_KEYS,
    COMMIT_REF,
    DEV_LENS_PACK,
    DevCritic,
    DevJudge,
    as_bytes,
    dev_case,
    dev_configuration,
    dev_expectation_cases,
    dev_manifest,
    dev_profile,
    expectation_bytes,
    load_dev_expectations,
    make_task,
    write_environment,
)

PRICING = Pricing(1.0, 100.0)  # test prices per million tokens (fake server usage; nothing is paid)
ROOMY = Reservation(PRICING, critic_max_tokens=50, max_proposed_chains=0, input_bytes_bound=12_000)


@pytest.fixture(scope="module", autouse=True)
def admit_the_fake_provider_server():
    assert q01_release_manifest.TEST_DOUBLE_TRANSPORTS == frozenset()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(q01_release_manifest, "TEST_DOUBLE_TRANSPORTS", frozenset({MOCK_TRANSPORT_NAME}))
        yield
    assert q01_release_manifest.TEST_DOUBLE_TRANSPORTS == frozenset()


@pytest.fixture(autouse=True)
def prohibit_real_startup(monkeypatch):
    monkeypatch.setattr("app.codex_rpc.CodexRPC.start",
                        lambda *_args, **_kwargs: pytest.fail("real model startup forbidden"))


# ---------------------------------------------------------------- a second dev set (new ids) for attempt 2

SUFFIX = "-v2"


def renamed_task(root):
    """The dev cases with every candidate and counterexample id renamed: a new set, new case ids."""
    task_dir = root / "v01-q01-dev-v2"
    task_dir.mkdir(parents=True)
    (task_dir / "instruction.md").write_bytes((q01_harness.TASK_DIR / "instruction.md").read_bytes())
    cases = []
    for candidate_id, ce_id in CASE_KEYS:
        case = dev_case(candidate_id, ce_id)
        case["source"]["candidate"]["id"] += SUFFIX
        for item in case["authored_counterexamples"]:
            item["counterexample"]["id"] += SUFFIX
            item["counterexample"]["candidate_id"] += SUFFIX
        case["case_id"] = case_id_for(candidate_id + SUFFIX, None if ce_id is None else ce_id + SUFFIX)
        cases.append(case)
    sha = write_environment(task_dir, cases)
    expectations = dev_expectation_cases()
    for case in expectations:
        case["candidate_id"] += SUFFIX
        if case["counterexample_id"] is not None:
            case["counterexample_id"] += SUFFIX
    return task_dir, sha, expectation_bytes(expectations, dataset_id="dev-synthetic-test-actor-v2")


class RenamedCritic:
    """``DevCritic`` over the renamed set (maps the ids in and back out)."""

    def __init__(self):
        self.inner = DevCritic()

    def __call__(self, system, user):
        out = self.inner(system, user.replace(SUFFIX + '"', '"'))
        return re.sub(r'"((?:d|x)-[a-z0-9-]+)"', lambda match: f'"{match.group(1)}{SUFFIX}"', out)


# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("t077-dispatch")
    task_dir, materials_sha = make_task(root)
    expectations_bytes = expectation_bytes()
    (root / "expectations.json").write_bytes(expectations_bytes)
    return {"root": root, "task_dir": task_dir, "materials_sha": materials_sha,
            "expectations": load_dev_expectations(expectations_bytes),
            "expectations_path": root / "expectations.json"}


def make_run(world, name, *, established=True, stop=100.0, reservation=ROOMY, max_slots=None, ledger=None,
             prior=None, task=None, critic=None, configuration=None, after_trial=None):
    """A fresh manifest, journal, trial base, guarded rig and plan under ``root/name``."""
    directory = world["root"] / name
    directory.mkdir()
    meter = SpendMeter(PRICING, directory / "spend.jsonl")
    critic_switch = Switch(critic or DevCritic())
    mock = MockClaude(critic_switch)
    (directory / "rig").mkdir()
    rig = claude_rig(directory / "rig", secret=SECRET, model_id=PLAN_MODEL, effort="medium", transport=mock.transport,
                     transport_name=MOCK_TRANSPORT_NAME, max_tokens=1000, call_seconds=5, run_seconds=60.0,
                     guard=meter)
    shaped = SimpleNamespace(choice={"provider": "claude", "mode": "api", "model": rig.model_id, "effort": rig.effort},
                             config=rig.config, claude=rig)
    task_dir, materials_sha, expectations_path = world["task_dir"], world["materials_sha"], world["expectations_path"]
    expectations = world["expectations"]
    if task is not None:
        task_dir, materials_sha, data = task
        expectations_path = directory / "expectations.json"
        expectations_path.write_bytes(data)
        expectations = load_dev_expectations(data)
    profile = dev_profile(established=established)
    (directory / "profile.json").write_bytes(profile)
    ledger = ledger or AttemptLedger(directory / "attempt-ledger.json")
    manifest = dev_manifest(expectations, materials_sha, rig=shaped, task_dir=task_dir, profile_bytes=profile,
                            journal=directory / "dispatch-journal.jsonl", trial_base=directory / "trials",
                            configuration=configuration)
    manifest["run_identity"]["usd_hard_stop"] = stop
    if prior is not None:
        manifest["prior_attempts"] = prior
        manifest["attempt"] = len(prior) + 1
    data = as_bytes(manifest)
    (directory / "pre-dispatch.json").write_bytes(data)
    plan = DispatchPlan(manifest_path=directory / "pre-dispatch.json", committed_sha256=hashlib.sha256(data).hexdigest(),
                        commit_ref=dict(COMMIT_REF), task_dir=task_dir, expectations_path=expectations_path,
                        profile_path=directory / "profile.json", lens_pack=dict(DEV_LENS_PACK), ledger=ledger,
                        meter=meter, reservation=reservation, run_dir=directory / "report", max_slots=max_slots,
                        labels={"data": "test-actor development data"})
    dispatcher = Dispatcher(plan, turn=rig.attested_turn, config=rig.config, judge=DevJudge(),
                            after_trial=after_trial)
    return SimpleNamespace(directory=directory, plan=plan, dispatcher=dispatcher, mock=mock, rig=rig, meter=meter,
                           manifest=manifest, data=data, ledger=ledger, critic=critic_switch)


def journal(run):
    return q01_release_manifest.read_journal(run.directory / "dispatch-journal.jsonl")


def review_calls(mock):
    return sum(json.loads(body["messages"][0]["content"])["purpose"] == "review" for body in mock.requests("critic"))


# ---------------------------------------------------------------- full run


@pytest.fixture(scope="module")
def full(world):
    run = make_run(world, "full")
    return run, run.dispatcher.run()


def test_full_run_dispatches_every_planned_slot_in_order_and_reaches_the_gate(world, full):
    run, outcome = full
    state = journal(run)
    planned = run.manifest["run_identity"]["planned_slots"]
    assert outcome["dispatch"] == {"dispatched": 39, "planned": 39, "stop_reason": None}
    assert [{"case_id": e["case_id"], "repetition": e["repetition"]} for e in state.dispatches] == planned
    assert state.stop is None and review_calls(run.mock) == 39
    assert outcome["suite"]["suite_outcome"] == "pass", outcome["suite"]["reasons"]
    record = outcome["record"]
    assert (record["suite_outcome"], record["attempt"], record["run_stopped"]) == ("pass", 1, False)
    assert record["dispatch_journal_head"] == state.head
    # the product gate caps a release-v7 pass at scoped_pass: never qualified
    assert (outcome["gate"]["status"], outcome["gate"]["reason"]) == ("scoped_pass", "design_cannot_verify_v3")
    # the verifier ran exactly once per trial: one judge log per journalled trial
    assert len(record["judge_logs"]) == 39 and len(outcome["results"]) == 39
    assert run.ledger.attempts()[0]["suite_outcome"] == "pass" and run.ledger.attempts()[0]["state"] == "decided"


def test_full_run_report_has_every_reporting_section(world, full):
    run, outcome = full
    report = json.loads((run.directory / "report" / "report.json").read_text(encoding="utf-8"))
    for key in ("per_case", "per_boundary", "judge_disagreements", "same_item_misses_and_false_rejections",
                "v3_joint_error_metrics", "clusters", "invalid_trials", "attempt", "dispatch_journal",
                "provider_ids", "provider_reconciliation", "stop_entry", "spend"):
        assert key in report, key
    assert all(row["passes"] == 3 * row["cases"] for row in report["per_boundary"].values())
    assert len(report["per_boundary"]) == 6
    assert report["clusters"]["count"] >= 1 and report["attempt"] == {"attempt": 1, "prior_verdicts": []}
    assert len(report["dispatch_journal"]["entries"]) == 40 and report["stop_entry"] is None
    calls = [call for trial in report["provider_ids"] for call in trial["critic_calls"]]
    assert calls and all(call["provider_request_id"].startswith("req_") and call["served_model"] == PLAN_MODEL
                         for call in calls)
    answers = [answer for trial in report["provider_ids"] for answer in trial["judge_answers"]]
    assert answers and all(answer["provider_request_id"].startswith("req_") for answer in answers)
    assert report["spend"]["calls"] == len(calls) and 0 < report["spend"]["estimated_usd"] <= 100.0


# ---------------------------------------------------------------- USD hard stop


def test_usd_stop_before_a_trial_that_could_cross_it_journals_the_stop_and_the_suite_is_incomplete(world):
    run = make_run(world, "usd-stop", stop=0.12)
    outcome = run.dispatcher.run()
    state = journal(run)
    assert 1 <= len(state.dispatches) < 39
    assert state.stop is not None and state.stop["reason"].startswith("usd_hard_stop 0.12")
    assert outcome["dispatch"]["stop_reason"] == state.stop["reason"]
    assert run.meter.spent <= 0.12
    suite = outcome["suite"]
    assert suite["suite_outcome"] == "incomplete" and "run_stopped" in suite["reasons"]
    assert outcome["record"]["run_stopped"] is True
    assert (outcome["gate"]["status"], outcome["gate"]["reason"]) == ("unqualified", "suite_incomplete")
    # the harness refuses any dispatch after the stop
    record = q01_harness.run_release_trial(
        state.dispatches[-1]["case_id"], run.rig.attested_turn, base_dir=run.directory / "trials",
        config=run.rig.config, pre_dispatch=run.dispatcher._pre_dispatch(1), task_dir=world["task_dir"])
    assert record["cause"] == "pre_dispatch_manifest_unverified"
    assert "dispatch_journal:run_stopped" in record["pre_dispatch"]["errors"]


def test_a_call_that_could_cross_the_stop_is_never_sent_and_the_stop_is_journalled(world):
    tiny = Reservation(PRICING, critic_max_tokens=0, max_proposed_chains=0, input_bytes_bound=0)
    run = make_run(world, "usd-guard", stop=0.15, reservation=tiny)
    sent_before = len(run.mock.requests())
    outcome = run.dispatcher.run()
    state = journal(run)
    assert state.stop is not None and "worst case" in state.stop["reason"]
    assert run.meter.spent <= 0.15 and len(run.mock.requests()) - sent_before == len(
        [entry for entry in run.meter.entries if entry["dispatched"] is not False])
    assert outcome["suite"]["suite_outcome"] == "incomplete"
    causes = {item["cause"] for item in outcome["suite"]["invalid_causes"]}
    assert causes == {"trial_transport_or_fixture_error"}, causes


# ---------------------------------------------------------------- crash and restart


class Crash(Exception):
    pass


def test_crash_between_trials_resumes_without_re_dispatch(world):
    count = {"n": 0}

    def crash_after_four(_trial):
        count["n"] += 1
        if count["n"] == 4:
            raise Crash()

    run = make_run(world, "crash", after_trial=crash_after_four)
    with pytest.raises(Crash):
        run.dispatcher.run()
    assert len(journal(run).dispatches) == 4 and review_calls(run.mock) == 4
    spent = run.meter.spent
    # a new process: a new meter reads the persisted spend; the dispatcher resumes at slot 5
    meter = SpendMeter(PRICING, run.directory / "spend.jsonl")
    assert meter.spent == pytest.approx(spent)
    run.plan.meter = meter
    resumed = Dispatcher(run.plan, turn=run.rig.attested_turn, config=run.rig.config, judge=DevJudge())
    outcome = resumed.run()
    state = journal(run)
    assert len(state.dispatches) == 39 and len({e["trial_id"] for e in state.dispatches}) == 39
    assert review_calls(run.mock) == 39  # no journalled trial was dispatched again
    assert len([p for p in (run.directory / "trials").iterdir() if p.is_dir()]) == 39
    assert outcome["suite"]["suite_outcome"] == "pass", outcome["suite"]["reasons"]
    assert len(run.ledger.attempts()) == 1


def test_a_trial_journalled_before_a_crash_is_never_redispatched_and_the_suite_is_incomplete(world):
    run = make_run(world, "crash-mid", max_slots=3)
    planned = run.manifest["run_identity"]["planned_slots"]
    # the crashed process had marked the set spent and journalled slot 1, then died before any record
    run.ledger.mark_spent(run.manifest, run.plan.committed_sha256)
    pre = run.dispatcher._pre_dispatch(planned[0]["repetition"])
    entry, errors = q01_harness.journal_dispatch(pre, planned[0]["case_id"], "t" + "0" * 32)
    assert errors == [] and entry is not None
    (run.directory / "trials" / ("t" + "0" * 32)).mkdir(parents=True)
    outcome = run.dispatcher.run()
    state = journal(run)
    assert [e["trial_id"] for e in state.dispatches][0] == "t" + "0" * 32
    assert len(state.dispatches) == 3 and review_calls(run.mock) == 2
    assert outcome["report"]["missing_trials"][0]["trial_id"] == "t" + "0" * 32
    assert outcome["suite"]["suite_outcome"] == "incomplete"
    assert "journalled_trial_not_submitted" in outcome["suite"]["reasons"]


# ---------------------------------------------------------------- spent sets and the attempt ledger


def test_a_spent_set_is_refused(world):
    first = make_run(world, "spent-1", max_slots=3)
    first.dispatcher.run()
    assert first.ledger.attempts()[0]["suite_outcome"] == "incomplete"
    # the same manifest again: its attempt is decided
    again = Dispatcher(first.plan, turn=first.rig.attested_turn, config=first.rig.config, judge=DevJudge())
    with pytest.raises(DispatchRefused, match="attempt_already_decided"):
        again.dispatch()
    # attempt 2 on the same set, listing attempt 1: the manifest check refuses the spent cases
    second = make_run(world, "spent-2", ledger=first.ledger,
                      prior=first.ledger.prior_attempts(first.manifest["critic_configuration_digest"]))
    with pytest.raises(DispatchRefused) as refused:
        second.dispatcher.dispatch()
    assert {"sealed_set_already_spent_by_a_prior_attempt", "case_id_already_spent_by_a_prior_attempt",
            "case_sha256_already_spent_by_a_prior_attempt"} <= set(refused.value.errors)
    # a second attempt-1 manifest that hides attempt 1 (cherry-picking): the ledger refuses it
    hidden = make_run(world, "spent-3", ledger=first.ledger)
    with pytest.raises(DispatchRefused) as refused:
        hidden.dispatcher.dispatch()
    assert set(refused.value.errors) == {"attempt_ledger:prior_attempts_differ_from_ledger",
                                         "attempt_ledger:sealed_set_already_spent"}
    # another critic configuration on the same set: spent across configurations too
    other = make_run(world, "spent-4", ledger=first.ledger,
                     configuration={**dev_configuration(SimpleNamespace(
                         choice={"provider": "claude", "mode": "api", "model": PLAN_MODEL, "effort": "medium"},
                         config=first.rig.config), world["task_dir"]), "max_tokens": 999})
    with pytest.raises(DispatchRefused) as refused:
        other.dispatcher.dispatch()
    assert refused.value.errors == ("attempt_ledger:sealed_set_already_spent",)
    for run in (second, hidden, other):
        assert not (run.directory / "dispatch-journal.jsonl").exists() and review_calls(run.mock) == 0


def test_attempt_ledger_numbers_attempts_across_two_sets(world, tmp_path):
    first = make_run(world, "ledger-1", max_slots=3)
    first.dispatcher.run()
    digest = first.manifest["critic_configuration_digest"]
    prior = first.ledger.prior_attempts(digest)
    assert [item["suite_outcome"] for item in prior] == ["incomplete"] and prior[0]["attempt"] == 1
    second = make_run(world, "ledger-2", ledger=first.ledger, prior=prior, max_slots=3,
                      task=renamed_task(tmp_path), critic=RenamedCritic())
    assert second.manifest["critic_configuration_digest"] == digest
    outcome = second.dispatcher.run()
    assert len(journal(second).dispatches) == 3
    assert outcome["results"] and {r["verdict"] for r in outcome["results"]} == {"pass"}
    record = outcome["record"]
    assert (record["attempt"], record["prior_outcomes"]) == (2, ["incomplete"])
    assert record["prior_sealed_set_sha256s"] == [world["materials_sha"]]
    assert outcome["report"]["attempt"] == {"attempt": 2, "prior_verdicts": ["incomplete"]}
    attempts = first.ledger.attempts()
    assert [(item["attempt"], item["suite_outcome"], item["state"]) for item in attempts] == [
        (1, "incomplete", "decided"), (2, "incomplete", "decided")]
    assert len(first.ledger.prior_attempts(digest)) == 2


def test_an_unverifying_manifest_or_commit_ref_is_refused_before_anything_is_sent(world):
    run = make_run(world, "refused")
    run.plan.committed_sha256 = "0" * 64
    with pytest.raises(DispatchRefused, match="manifest_sha256_differs_from_committed"):
        run.dispatcher.dispatch()
    run.plan.committed_sha256 = hashlib.sha256(run.data).hexdigest()
    run.plan.commit_ref = {"kind": "git_commit", "ref": "not a commit"}
    with pytest.raises(DispatchRefused, match="commit_ref_malformed"):
        run.dispatcher.dispatch()
    run.plan.commit_ref = {"kind": "git_commit", "ref": "0" * 40}
    run.plan.commit_repo = Path(__file__).resolve().parents[3]
    with pytest.raises(DispatchRefused, match="commit_does_not_contain_manifest_sha256"):
        run.dispatcher.dispatch()
    assert run.ledger.attempts() == [] and review_calls(run.mock) == 0


def test_a_same_family_judge_is_refused_by_the_manifest_check(world):
    run = make_run(world, "same-family")
    manifest = json.loads(run.data)
    manifest["run_identity"]["judge_model"] = PLAN_MODEL
    data = as_bytes(manifest)
    run.plan.manifest_path.write_bytes(data)
    run.plan.committed_sha256 = hashlib.sha256(data).hexdigest()
    with pytest.raises(DispatchRefused, match="judge:shares_the_critic_provider_or_model"):
        run.dispatcher.dispatch()
    assert run.ledger.attempts() == [] and review_calls(run.mock) == 0
