"""Offline Q01 harness tests: materialization, isolation, stage driving, classification.

No provider is contacted: every transport is a scripted ``(system, user) -> str``
fixture and the model catalog is the explicit offline CodexFixture.
"""

import json
import sqlite3
import threading
from hashlib import sha256
from pathlib import Path

import pytest

from app.critic_audit import FrozenCall, Ledger, canonical
from app.critic_contract import prepare_input
from app.generation_profiles import GenerationPurpose as P
from app.services.design_criticism_live import render_criticism_prompt
from evals.deeptwin.harness import q01_cases
from evals.deeptwin.harness.q01_harness import (
    CONTROL_PLANE_FILES,
    INSTRUCTION_SHA256,
    REPO_ROOT,
    Q01Trial,
    ReaderRefusal,
    TaskReader,
    readiness,
    stage_input,
)
from evals.deeptwin.q01_materials import q01_counterexample
from evals.deeptwin.tests.q01_support import (
    CASE,
    ScriptedCritic,
    copy_task,
    make_rig,
    rewrite_case,
    run,
    set_status,
)

TASK_MD = q01_cases.TASK_DIR / "Task.md"


@pytest.fixture(autouse=True)
def prohibit_real_startup(monkeypatch):
    monkeypatch.setattr("app.codex_rpc.CodexRPC.start",
                        lambda *_args, **_kwargs: pytest.fail("real model startup forbidden"))


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path)


# ---------------------------------------------------------------- materialization


def test_frozen_environment_equals_a_fresh_materialization(tmp_path):
    target = tmp_path / "fresh"
    manifest = q01_cases.write_environment(target)
    repo_env = q01_cases.TASK_DIR / "environment"
    assert (repo_env / "manifest.json").read_bytes() == (target / "environment" / "manifest.json").read_bytes()
    for entry in manifest["cases"]:
        assert (q01_cases.TASK_DIR / entry["path"]).read_bytes() == (target / entry["path"]).read_bytes()
    assert sorted(path.name for path in (repo_env / "cases").iterdir()) == sorted(
        entry["case_id"] + ".json" for entry in manifest["cases"])
    assert {entry["case_id"] for entry in manifest["cases"]} == set(CASE.values())


def test_every_development_case_is_materialized_once_with_stable_opaque_ids():
    cases = q01_cases.materialize_all()
    assert len(cases) == len(q01_cases.CASE_SPECS) == 10
    assert [case["case_id"] for case in cases] == sorted(case["case_id"] for case in cases)
    assert [case["case_id"] for case in cases] == [case["case_id"] for case in q01_cases.materialize_all()]
    for case in cases:
        assert set(case) == {"schema", "case_id", "source", "authored_counterexamples"}
        candidate_id = case["source"]["candidate"]["id"]
        assert candidate_id not in case["case_id"]
        assert len(case["authored_counterexamples"]) <= 1
        for item in case["authored_counterexamples"]:
            assert item["counterexample"]["candidate_id"] == candidate_id
    pairs = {(case["source"]["candidate"]["id"],
              case["authored_counterexamples"][0]["counterexample"]["id"] if case["authored_counterexamples"]
              else None) for case in cases}
    assert pairs == set(CASE)


def test_case_files_carry_no_expected_labels():
    forbidden_keys = {"expected", "label", "class", "boundary", "verdict", "answer", "kind", "score"}
    for path in (q01_cases.TASK_DIR / "environment" / "cases").iterdir():
        case = json.loads(path.read_text(encoding="utf-8"))

        def keys(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from keys(item)
            elif isinstance(value, list):
                for item in value:
                    yield from keys(item)

        assert not forbidden_keys & set(keys(case))
        text = path.read_text(encoding="utf-8")
        for label in ("images-delete", "mixed-attribution", "central-crop", "정상 후보", "그럴듯한 오류",
                      "전달 결손", "편의 단축", "자료 부족"):
            assert label not in text


def test_instruction_is_the_exact_task_instruction():
    task = TASK_MD.read_text(encoding="utf-8")
    quoted = next(line[2:] for line in task.splitlines() if line.startswith("> 제공한"))
    rows = {line.split("|")[1].strip(): line.split("|")[3].strip()
            for line in task.splitlines() if line.startswith("| 반례 타당성") or line.startswith("| 후보 대응")}
    sections = TaskReader().instructions()
    assert sections["review"] == quoted
    assert sections["counterexample_proposal"] == quoted
    assert sections["counterexample_validity"] == rows["반례 타당성"]
    assert sections["candidate_response"] == rows["후보 대응"]


def test_task_toml_names_existing_paths_and_no_harbor_claim():
    import tomllib

    task = tomllib.loads((q01_cases.TASK_DIR / "task.toml").read_text(encoding="utf-8"))
    assert task["agent"]["stages"] == [stage.value for stage in (P.REVIEW, P.COUNTEREXAMPLE_PROPOSAL,
                                                                  P.COUNTEREXAMPLE_VALIDITY, P.CANDIDATE_RESPONSE)]
    for relative in (task["control_plane"]["spec"], task["control_plane"]["verifier"],
                     task["control_plane"]["world_skill"], task["agent"]["instruction"],
                     task["environment"]["manifest"]):
        assert (q01_cases.TASK_DIR / relative).resolve().exists()
    assert "NOT a Harbor" in (q01_cases.TASK_DIR / "task.toml").read_text(encoding="utf-8")


# ---------------------------------------------------------------- readiness / reader


def test_readiness_proves_completeness_and_isolation_with_the_trial_read_path():
    report = readiness()
    assert report["ready"], report["checks"]
    assert {item["check"] for item in report["checks"]} >= {
        "environment_readable", "cases_match_materials", "control_plane_refused", "stage_inputs_clean",
        "stage_inputs_allowlisted", "environment_files_clean"}
    refused = [entry["path"] for entry in report["access_log"] if entry["outcome"] == "refused"]
    assert "Task.md" in refused and "../../verifiers/critic.py" in refused


def test_readiness_detects_tampered_or_drifted_cases(tmp_path):
    task_dir = copy_task(tmp_path)
    path = next((task_dir / "environment" / "cases").iterdir())
    path.write_text(path.read_text(encoding="utf-8").replace("추정", "확정"), encoding="utf-8")
    assert readiness(task_dir)["ready"] is False  # manifest hash mismatch
    task_dir = copy_task(tmp_path / "second")
    rewrite_case(task_dir, CASE[("c71", None)],
                 lambda case: case["source"]["candidate"]["control"].update(publication="published"))
    report = readiness(task_dir)
    assert report["ready"] is False
    assert {item["check"]: item["ok"] for item in report["checks"]}["cases_match_materials"] is False


def test_readiness_detects_control_plane_text_in_agent_material(tmp_path):
    task_dir = copy_task(tmp_path)
    leak = next(line for line in TASK_MD.read_text(encoding="utf-8").splitlines()
                if line.startswith("| 그럴듯한 오류"))
    instruction = task_dir / "instruction.md"
    instruction.write_text(instruction.read_text(encoding="utf-8") + "\n" + leak.split("|")[2] + "\n",
                           encoding="utf-8")
    report = readiness(task_dir)
    assert report["ready"] is False
    assert {"path": "instruction.md", "outcome": "refused"} in report["access_log"]
    record = run(make_rig(tmp_path / "rig"), CASE[("c24", None)], ScriptedCritic(), task_dir=task_dir)
    assert record["status"] == "invalid" and record["cause"] == "environment_read_refused"


def test_instruction_pin_matches_the_reviewed_file():
    assert q01_cases.digest((q01_cases.TASK_DIR / "instruction.md").read_bytes()) == INSTRUCTION_SHA256


def test_readiness_scans_case_material_against_trusted_corpus(tmp_path):
    task_dir = copy_task(tmp_path)
    leak = next(line for line in TASK_MD.read_text(encoding="utf-8").splitlines()
                if line.startswith("| 그럴듯한 오류")).split("|")[2].strip()
    rewrite_case(task_dir, CASE[("c86", None)],
                 lambda case: case["source"]["candidate"]["control"]["notes"].append(leak))
    checks = {item["check"]: item["ok"] for item in readiness(task_dir)["checks"]}
    assert checks["environment_files_clean"] is False
    assert checks["stage_inputs_clean"] is False
    assert checks["cases_match_materials"] is False


@pytest.mark.parametrize("probe", ["Task.md", "task.toml", "../../verifiers/critic.py", "/etc/hosts",
                                   "environment/../Task.md", "environment", "", "environment\\manifest.json"])
def test_reader_refuses_everything_outside_the_allowlist(probe):
    reader = TaskReader()
    with pytest.raises(ReaderRefusal):
        reader.read_bytes(probe)
    assert reader.log[-1]["outcome"] == "refused"


def test_reader_refuses_symlinked_material(tmp_path):
    task_dir = copy_task(tmp_path)
    instruction = task_dir / "instruction.md"
    target = tmp_path / "elsewhere.md"
    target.write_text(instruction.read_text(encoding="utf-8"), encoding="utf-8")
    instruction.unlink()
    instruction.symlink_to(target)
    with pytest.raises(ReaderRefusal):
        TaskReader(task_dir).instructions()


# ---------------------------------------------------------------- stage driving


def _control_plane_texts():
    texts = [(REPO_ROOT / relative).read_text(encoding="utf-8") for relative in CONTROL_PLANE_FILES
             if (REPO_ROOT / relative).exists()]
    return texts


def test_valid_trial_drives_four_stages_through_the_product_render(rig):
    critic = ScriptedCritic()
    record = run(rig, CASE[("c71", "ce-17")], critic)
    assert record["status"] == "completed" and record["output_contract"] == "valid"
    assert record["semantic"] == "not_checked" and record["score"] is None and record["cause"] is None
    purposes = [entry["manifest"]["purpose"] for entry in record["calls"]]
    assert purposes == ["review", "counterexample_proposal", "counterexample_validity", "candidate_response"]
    assert [entry["manifest"]["lineage"] and entry["manifest"]["lineage"]["kind"] for entry in record["calls"]] == [
        None, "request", "authored", "request"]
    assert len(critic.calls) == 4
    for (system, user), entry in zip(critic.calls, record["calls"]):
        manifest = entry["manifest"]
        payload = json.loads(user)
        prepared = prepare_input(P(payload["purpose"]), payload["input"])
        product_system, product_user = render_criticism_prompt(prepared)
        assert user == product_user == entry["ledger"]["call"]["prompt"]
        assert system.startswith(product_system + "\n")
        assert manifest["system_sha256"] == sha256(system.encode()).hexdigest()
        assert manifest["user_sha256"] == sha256(user.encode()).hexdigest()
        assert manifest["prepared_manifest"] == json.loads(prepared.manifest_json)
        assert manifest["case_sha256"] == record["case_sha256"]
        assert entry["ledger"]["state"] == "completed"
        assert entry["ledger"]["details"]["score"] is None
    validity_input = json.loads(critic.calls[2][1])["input"]
    assert validity_input["counterexample"] == q01_counterexample("mixed-attribution", "c71")
    assert set(validity_input) == {"originals", "criteria", "candidate", "counterexample"}
    assert "lens_pack" not in json.loads(critic.calls[0][1])["input"]
    assert "lens_pack" in json.loads(critic.calls[1][1])["input"]
    assert Path(record["ledger_path"]).is_file()
    assert json.loads((Path(record["ledger_path"]).parents[1] / "trial-record.json").read_text()) == record


@pytest.mark.parametrize("key", sorted(CASE, key=str))
def test_no_agent_input_contains_control_plane_content_or_case_ids(rig, key):
    critic = ScriptedCritic(propose=True)
    record = run(rig, CASE[key], critic)
    assert record["status"] == "completed", record["cause"]
    assert record["leak_scan"]["hits"] == [] and record["leak_scan"]["fragments"] > 100
    agent_text = "\n".join(system + "\n" + user for system, user in critic.calls)
    for case_id in CASE.values():
        assert case_id not in agent_text
    for text in _control_plane_texts():
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= 40 and "|" not in line and not line.startswith(">"):
                assert line not in agent_text
    for marker in ("required_defect", "accept_without_false_rejection", "insufficient_evidence",
                   "EXPECTED", "Expectation(", "예상 경계", "deeptwin-eval-world"):
        assert marker not in agent_text
    assert all(entry["outcome"] == "read" for entry in record["access_log"])
    assert {entry["path"] for entry in record["access_log"]} <= {
        "instruction.md", "environment/manifest.json", f"environment/cases/{CASE[key]}.json"}


def test_each_trial_gets_fresh_state(rig):
    first_critic, second_critic = ScriptedCritic(), ScriptedCritic()
    first = run(rig, CASE[("c09", None)], first_critic)
    second = run(rig, CASE[("c09", None)], second_critic)
    assert first["trial_id"] != second["trial_id"]
    assert first["ledger_path"] != second["ledger_path"]
    assert [user for _s, user in first_critic.calls] == [user for _s, user in second_critic.calls]
    with sqlite3.connect(second["ledger_path"]) as db:
        ids = {row[0] for row in db.execute("SELECT id FROM calls")}
    assert ids and all(identifier.startswith(second["trial_id"]) for identifier in ids)
    trial = Q01Trial(CASE[("c09", None)], ScriptedCritic(), base_dir=rig.base, config=rig.config)
    trial.run()
    with pytest.raises(RuntimeError):
        trial.run()


def test_proposed_counterexamples_are_driven_with_exact_request_lineage(rig):
    critic = ScriptedCritic(propose=True)
    record = run(rig, CASE[("c71", "ce-29")], critic)
    assert record["status"] == "completed"
    lineages = [entry["manifest"]["lineage"] for entry in record["calls"]]
    assert [item and item["kind"] for item in lineages] == [None, "request", "authored", "request", "request",
                                                           "request"]
    proposal_request = record["calls"][1]["manifest"]["request_id"]
    proposed = record["stages"]["proposal"]["counterexamples"][0]
    assert lineages[4]["parent_request_id"] == proposal_request
    assert lineages[4]["evidence_sha256"] == sha256(canonical(proposed).encode()).hexdigest()
    assert record["stages"]["proposed_chains"][0]["counterexample_id"] == "px-1"
    capped = run(rig, CASE[("c71", "ce-29")], ScriptedCritic(propose=True), max_proposed_chains=0)
    assert capped["status"] == "completed" and capped["stages"]["proposed_not_driven"] == 1
    assert len(capped["calls"]) == 4


def test_response_is_driven_for_rejected_and_unresolved_validity(rig):
    for key in (("c71", "ce-29"), ("c42", "ce-43")):
        record = run(rig, CASE[key], ScriptedCritic())
        chain = record["stages"]["authored_chains"][0]
        assert chain["response"]["status"] == "unresolved"
        assert chain["response"]["validity_status"] == chain["validity"]["status"]


# ---------------------------------------------------------------- classification


def test_contract_invalid_output_is_completed_model_output_invalid_without_score(rig):
    critic = ScriptedCritic(overrides={"review": lambda _v, _a: "not json"})
    record = run(rig, CASE[("c71", None)], critic)
    assert record["status"] == "completed"
    assert record["output_contract"] == "model_output_invalid" and record["cause"] == "model_output_invalid"
    assert record["score"] is None and record["semantic"] == "not_checked"
    assert len(record["calls"]) == 1 and len(critic.calls) == 1
    details = record["calls"][0]["ledger"]["details"]
    assert details["output_contract"] == "model_output_invalid" and "parsed" not in details


def test_rejected_counterexample_cannot_fail_the_candidate_under_the_contract(rig):
    critic = ScriptedCritic(overrides={"candidate_response": set_status("status", "fail", uncertainties=[])})
    record = run(rig, CASE[("c71", "ce-29")], critic)
    assert record["status"] == "completed" and record["output_contract"] == "model_output_invalid"
    assert record["calls"][-1]["manifest"]["purpose"] == "candidate_response"


@pytest.mark.parametrize("behaviour,cause", [
    ("raise", "transport_or_fixture_error"),
    ("not_text", "transport_contract_or_model_mismatch"),
])
def test_transport_faults_are_invalid_with_a_general_cause(rig, behaviour, cause):
    def turn(system, user):
        if behaviour == "raise":
            raise RuntimeError("PRIVATE-TRANSPORT-DETAIL")
        return {"not": "text"}

    record = run(rig, CASE[("c24", None)], turn)
    assert record["status"] == "invalid" and record["cause"] == cause
    assert record["score"] is None and record["output_contract"] is None
    assert "PRIVATE" not in canonical(record)


def test_cancellation_is_invalid_and_committed_before_signal(rig):
    entered, release = threading.Event(), threading.Event()

    def turn(system, user):
        entered.set()
        release.wait(5)
        return "{}"

    trial = Q01Trial(CASE[("c53", None)], turn, base_dir=rig.base, config=rig.config)
    assert trial.cancel() is False
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(record=trial.run()))
    worker.start()
    assert entered.wait(5)
    assert trial.cancel() is True
    worker.join(5)
    release.set()
    record = outcome["record"]
    assert record["status"] == "invalid" and record["cause"] == "cancelled" and record["score"] is None
    assert record["calls"][0]["ledger"]["state"] == "cancelled"


def test_timeout_is_invalid_without_score(rig):
    release = threading.Event()

    def turn(system, user):
        release.wait(5)
        return "{}"

    try:
        record = run(rig, CASE[("c53", None)], turn, call_seconds=0.2)
    finally:
        release.set()
    assert record["status"] == "invalid" and record["cause"] == "timed_out" and record["score"] is None
    assert record["calls"][0]["ledger"]["state"] == "timed_out"


def test_unknown_case_or_changed_selection_is_invalid_before_dispatch(rig):
    critic = ScriptedCritic()
    record = run(rig, "q01-0000000000", critic)
    assert record["status"] == "invalid" and record["cause"] == "environment_read_refused"
    other = next(effort for effort in rig.efforts if effort != rig.choice["effort"])
    rig.selections.save(rig.work["id"], 1, {**rig.choice, "effort": other})
    record = run(rig, CASE[("c24", None)], critic)
    assert record["status"] == "invalid" and record["cause"] == "selection_or_freeze_refused"
    assert critic.calls == []


def test_leaked_control_plane_text_blocks_dispatch(rig, tmp_path):
    task_dir = copy_task(tmp_path)
    leak = next(line for line in TASK_MD.read_text(encoding="utf-8").splitlines()
                if line.startswith("| 편의 단축")).split("|")[1].strip()
    rewrite_case(task_dir, CASE[("c71", None)],
                 lambda case: case["source"]["candidate"]["control"]["notes"].append(leak))
    critic = ScriptedCritic()
    record = run(rig, CASE[("c71", None)], critic, task_dir=task_dir)
    assert record["status"] == "invalid" and record["cause"] == "isolation_boundary"
    assert record["leak_scan"]["hits"] and critic.calls == []
    assert record["calls"][0]["ledger"] is None


# ---------------------------------------------------------------- authored lineage (ledger)


def _frozen(request_id, purpose, *, run="run-1", candidate="c71"):
    return FrozenCall(request_id=request_id, run_id=run, purpose=purpose, candidate_id=candidate,
                      candidate_version="1", prompt='{"input": {}}', schema_json=canonical({"a": 1}),
                      manifest_json=canonical({"b": 2}), selection_json=canonical({"c": 3}),
                      metadata_json=canonical({"d": 4}))


@pytest.fixture
def ledger(tmp_path):
    journal = Ledger(tmp_path / "audit" / "eval.sqlite3")
    journal.open_run("run-1", max_calls=8, max_seconds=600)
    journal.open_run("run-2", max_calls=8, max_seconds=600)
    return journal


def test_authored_counterexample_binds_only_its_run_and_candidate(ledger):
    item = q01_counterexample("images-delete", "c71")
    sha = ledger.register_authored_evidence("run-1", candidate_id="c71", candidate_version="1", item=item,
                                            source="authored-fixture")
    assert sha == sha256(canonical(item).encode()).hexdigest()
    ledger.reserve_with_lineage(_frozen("v-1", "counterexample_validity"), parent_request_id=None, evidence_sha=sha)
    record = ledger.get("v-1")
    assert record["events"][0]["details"] == {"lineage_parent": None, "lineage_sha": sha,
                                              "lineage_source": "authored:authored-fixture"}
    with pytest.raises(ValueError):  # forged hash
        ledger.reserve_with_lineage(_frozen("v-2", "counterexample_validity"), parent_request_id=None,
                                    evidence_sha="ab" * 32)
    with pytest.raises(ValueError):  # another run
        ledger.reserve_with_lineage(_frozen("v-3", "counterexample_validity", run="run-2"),
                                    parent_request_id=None, evidence_sha=sha)
    with pytest.raises(ValueError):  # another candidate
        ledger.reserve_with_lineage(_frozen("v-4", "counterexample_validity", candidate="c86"),
                                    parent_request_id=None, evidence_sha=sha)
    for purpose in ("counterexample_proposal", "candidate_response"):
        with pytest.raises(ValueError):  # only validity may bind authored material
            ledger.reserve_with_lineage(_frozen("v-5", purpose), parent_request_id=None, evidence_sha=sha)
    with pytest.raises(ValueError):
        ledger.register_authored_evidence("run-9", candidate_id="c71", candidate_version="1", item=item,
                                          source="x")
    with pytest.raises(ValueError):
        ledger.register_authored_evidence("run-1", candidate_id="c86", candidate_version="1", item=item,
                                          source="x")
    with pytest.raises(ValueError):  # authored material is never proposal evidence
        ledger.register_result_evidence("v-1", [item])


def test_stage_input_projects_only_allowed_fields():
    case = q01_cases.materialize_case("c71", "images-delete")
    polluted = json.loads(json.dumps(case))
    polluted["source"]["expected"] = "LEAK-CANARY"
    polluted["source"]["candidate"]["self_score"] = "LEAK-CANARY"
    for purpose in (P.REVIEW, P.COUNTEREXAMPLE_PROPOSAL):
        assert "LEAK-CANARY" not in stage_input(purpose, polluted).prompt
    prepared = stage_input(P.COUNTEREXAMPLE_VALIDITY, polluted,
                           counterexample=case["authored_counterexamples"][0]["counterexample"])
    assert "LEAK-CANARY" not in prepared.prompt


def test_harness_code_reads_no_environment_variables():
    for relative in ("evals/deeptwin/harness/q01_harness.py", "evals/deeptwin/harness/q01_cases.py",
                     "evals/deeptwin/verifiers/critic.py"):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "os.environ" not in text and "getenv" not in text
