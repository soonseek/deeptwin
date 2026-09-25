"""T076: the release-v1..v7 qualification, independence and lens-effect designs are frozen.

A changed file is a new design version, never a silent edit of the frozen one; and the
frozen designs never admit the calibration cases or a same-model judge as independent.

An earlier manifest's code hashes are checked against the file at that version's freeze
commit (``git show <commit>:<path>``). When the freeze commit is absent (a shallow clone),
those checks xfail explicitly with the reason (audit 5, note 8); they never pass silently.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "evals/deeptwin/qualification/release-v1/FROZEN.json"


def test_every_frozen_design_file_matches_its_recorded_hash():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["files"]
    for path, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_the_frozen_designs_exclude_calibration_data_and_same_model_judging():
    design = json.loads((ROOT / "evals/deeptwin/qualification/release-v1/qualification_design.json").read_text())
    profile = json.loads((ROOT / "evals/deeptwin/qualification/release-v1/independence_profile.json").read_text())
    effects = json.loads((ROOT / "evals/deeptwin/effects/lens-effects-v1.json").read_text())
    assert design["predecessor"]["calibration_cases_eligible"] is False
    assert design["dataset"]["state"] == "not_authored"
    assert "developer who built the Q01 harness" in design["dataset"]["authoring"]["author"]
    assert design["acceptance"]["incomplete"].startswith("any case with fewer valid repetitions")
    assert "must not share the critic's model" in profile["requirement"]
    assert effects["precondition"].startswith("The critic configuration has passed release-v1")
    assert any(item["id"] == "no_lens" and "nothing is removed" in item["note"] for item in effects["conditions"])


MANIFEST_V2 = ROOT / "evals/deeptwin/qualification/release-v2/FROZEN.json"


def test_release_v2_pins_its_files_and_the_unchanged_v1_designs():
    manifest = json.loads(MANIFEST_V2.read_text())
    assert "evals/deeptwin/qualification/release-v1/FROZEN.json" in manifest["files"]
    for path, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_release_v2_keeps_the_audit_limits_explicit():
    design = json.loads((ROOT / "evals/deeptwin/qualification/release-v2/qualification_design.json").read_text())
    profile = json.loads((ROOT / "evals/deeptwin/qualification/release-v2/independence_profile.json").read_text())
    effects = json.loads((ROOT / "evals/deeptwin/effects/lens-effects-v2.json").read_text())
    assert "Exactly one run per sealed set" in design["dataset"]["storage_and_access"]["single_use"]
    assert design["execution"]["output_contract_error"].startswith("a completed trial whose output breaks")
    assert any(claim.startswith("V3 (error independence) remains unmet") for claim in design["claims_if_passed"])
    assert profile["judge_separation"]["established"] is False
    assert profile["v3_error_independence"]["status"] == "unverified"
    arms = {arm["id"]: arm for arm in effects["arms"]}
    assert arms["user_construct"]["state"] == "not_runnable_data_needed"
    assert {"strong_existing_procedure", "no_lens", "general_multi_perspective"} <= arms.keys()


V3 = ROOT / "evals/deeptwin/qualification/release-v3"


V3_FROZEN_IN_COMMIT = "bd6a976"
GATE = "app/services/critic_qualification.py"
# sha256 of the gate as committed in bd6a976 (git show bd6a976:app/services/critic_qualification.py)
V3_GATE_SHA256 = "744d8448799a6f5f7451cda6bafb3a1863e13a5a27cb66cda2f8710e4403f8bb"


def _at_commit(commit, path):
    """The bytes of ``path`` as committed in ``commit`` (an earlier version's freeze commit).

    Audit 5, note 8: without the commit (a shallow clone) the check xfails explicitly with the
    reason, and any other git failure fails the test; it never silently returns.
    """
    try:
        present = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, capture_output=True,
                                 check=False, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.fail(f"git is unavailable to check the freeze commit {commit}: {exc}")
    if not present:
        pytest.xfail(f"freeze commit {commit} is absent (shallow clone?): the hash pinned for {path} cannot be "
                     "checked against the file at its freeze; fetch the full history to run this guard")
    try:
        return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=True,
                              timeout=60).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.fail(f"{path} is not readable at the freeze commit {commit}: {exc}")


def _v3_gate_bytes():
    return _at_commit(V3_FROZEN_IN_COMMIT, GATE)


def test_release_v3_pins_every_version_and_the_product_gate():
    manifest = json.loads((V3 / "FROZEN.json").read_text())
    for required in ("evals/deeptwin/qualification/release-v2/FROZEN.json",
                     "evals/deeptwin/qualification/release-v1/FROZEN.json",
                     GATE):
        assert required in manifest["files"]
    for path, digest in manifest["files"].items():
        if path == GATE:
            # release-v3's manifest records the gate AS IT WAS when v3 was frozen (bd6a976).
            # Audit 3 changed the gate, which made a new design version (release-v4, whose
            # FROZEN.json pins the new gate); v3's frozen JSON is never edited, so its gate
            # hash is verified against the gate file at the commit that froze v3, not the
            # working tree.
            assert digest == V3_GATE_SHA256
            assert hashlib.sha256(_v3_gate_bytes()).hexdigest() == digest
            continue
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_release_v3_resolves_the_second_audit():
    design = json.loads((V3 / "qualification_design.json").read_text())
    effects = json.loads((ROOT / "evals/deeptwin/effects/lens-effects-v3.json").read_text())
    # B2: dataset and judge are run identity, never critic configuration
    assert "sealed_dataset_sha256" not in design["critic_configuration"]["fields"]
    assert "judge_identity" in design["run_identity"]["fields"]
    # B1: a data-driven verifier over sealed expectations, not the calibration verifier
    assert "not evals/deeptwin/verifiers/critic.py" in design["verifier"]["requirement"]
    assert design["verifier"]["state_at_freeze"].startswith("not yet implemented")
    # B4: fail precedence and a scoped pass that is no qualification
    assert design["acceptance"]["suite_outcome"]["fail"].startswith("any valid repetition failed")
    assert "NOT a critic qualification" in design["acceptance"]["what_a_pass_confers"]
    # B5/B6: attempt ledger and a pre-dispatch freeze
    assert "prior attempts" in design["dataset"]["storage_and_access"]["attempt_ledger"]
    assert "refuses to dispatch" in design["pre_dispatch"]["freeze"]
    # B7/B8: the effect set follows the dataset rules; baseline texts are frozen before access
    assert "in full" in effects["dataset"]["rules"]
    arms = {arm["id"]: arm for arm in effects["arms"]}
    assert arms["general_multi_perspective"]["state"] == "text_not_yet_fixed"
    assert arms["strong_existing_procedure"]["state"] == "duplicate_of_no_lens"
    assert arms["user_construct"]["state"] == "not_runnable_data_needed"


def _record(schema, **overrides):
    from app.services.critic_qualification import (
        SUITE_RECORD_SCHEMA_VERSION,
        suite_record_sha256,
    )

    record = {
        "schema_version": SUITE_RECORD_SCHEMA_VERSION, "design_id": schema["properties"]["design_id"]["const"],
        "critic_configuration_digest": "c" * 64, "pre_dispatch_manifest_sha256": "a" * 64,
        "sealed_set_sha256": "d" * 64, "attempt": 1, "prior_outcomes": [], "suite_outcome": "pass",
        "independence_profile_sha256": "b" * 64, "judge_separation_established": True,
        "v3_error_independence": "unverified", "prior_sealed_set_sha256s": [],
        "prior_attempts_sha256": hashlib.sha256(b"[]").hexdigest(), "dispatch_journal_head": "e" * 64,
        "manifest_commit_ref": {"kind": "git_commit", "ref": "0123456789abcdef0123456789abcdef01234567"},
        "critic_transport_identity": "provider_reported", "judge_transport_identity": "provider_reported",
        "run_stopped": False,
        "judge_logs": [{"trial_id": "t" + "1" * 32, "lines_sha256": "f" * 64}],
        "provider_ids_sha256": "9" * 64, "provider_id_count": 6,
    }
    record.update(overrides)
    record["record_sha256"] = suite_record_sha256(record)
    return record


V4 = ROOT / "evals/deeptwin/qualification/release-v4"
V5 = ROOT / "evals/deeptwin/qualification/release-v5"
V6 = ROOT / "evals/deeptwin/qualification/release-v6"
V7 = ROOT / "evals/deeptwin/qualification/release-v7"
V4_FROZEN_IN_COMMIT = "fb718b6"  # the commit that added release-v4/FROZEN.json (git log --diff-filter=A)
# Code that release-v4/FROZEN.json pins and that audit 4 changed for release-v5. v4's frozen JSON is
# never edited, so for these files its recorded hashes are checked against the file as committed in
# fb718b6 (git show fb718b6:<path>), not against the working tree; release-v5/FROZEN.json pins the
# current files.
V5_CHANGED_CODE = frozenset({
    GATE, "evals/deeptwin/verifiers/sealed_critic.py", "evals/deeptwin/verifiers/q01_core.py",
    "evals/deeptwin/q01_release_manifest.py", "evals/deeptwin/harness/q01_harness.py",
})


def _v4_bytes(path):
    return _at_commit(V4_FROZEN_IN_COMMIT, path)


V5_FROZEN_IN_COMMIT = "4aed36d"  # the commit that added release-v5/FROZEN.json (git log --diff-filter=A)
# Code that release-v5/FROZEN.json (or v5's recorded harness) pins and that audit 5 changed for
# release-v6. v5's frozen JSON is never edited, so for these files its recorded hashes are checked
# against the file as committed in 4aed36d (git show 4aed36d:<path>), not against the working tree;
# release-v6/FROZEN.json pins the current files. app/critic_trial.py is in v4's and v5's recorded
# harness identity, so v4's recorded hash for it is checked at fb718b6 as well.
V6_CHANGED_CODE = frozenset({
    GATE, "evals/deeptwin/verifiers/sealed_critic.py", "evals/deeptwin/verifiers/q01_core.py",
    "evals/deeptwin/q01_release_manifest.py", "evals/deeptwin/harness/q01_harness.py", "app/critic_trial.py",
})


def _v5_bytes(path):
    return _at_commit(V5_FROZEN_IN_COMMIT, path)


V6_FROZEN_IN_COMMIT = "c3204d6"  # the commit that added release-v6/FROZEN.json (git log --diff-filter=A)
# Code that release-v6/FROZEN.json (or v6's recorded harness) pins and that audit 6 changed for
# release-v7. v6's frozen JSON is never edited, so for these files its recorded hashes are checked
# against the file as committed in c3204d6 (git show c3204d6:<path>), not against the working tree;
# release-v7/FROZEN.json pins the current files. q01_core.py, claude_judge.py and the product adapter
# app/adapters/claude_api.py are unchanged by audit 6.
V7_CHANGED_CODE = frozenset({
    GATE, "evals/deeptwin/verifiers/sealed_critic.py", "evals/deeptwin/q01_release_manifest.py",
    "evals/deeptwin/harness/q01_harness.py", "app/critic_trial.py", "evals/deeptwin/harness/claude_rig.py",
})


def _v6_bytes(path):
    return _at_commit(V6_FROZEN_IN_COMMIT, path)


def _file_set_sha256(hashes):
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def test_the_product_gate_accepts_exactly_the_v7_suite_record_schema():
    # Audit 3 moved the gate to v4 records, audit 4 to v5, audit 5 to v6 and audit 6 to v7 records (this
    # test read v3..v6 before; those schemas are unchanged and still pinned by their FROZEN.json).
    from jsonschema import Draft202012Validator

    from app.services.critic_qualification import (
        RELEASE_DESIGN_IDS,
        SUITE_RECORD_SCHEMA_VERSION,
        V3_VERIFYING_DESIGN_IDS,
        CriticQualificationError,
        critic_qualification_from_suite,
        suite_record_sha256,
    )

    schema = json.loads((V7 / "suite_record.schema.json").read_text())
    record = _record(schema)
    assert Draft202012Validator(schema).is_valid(record)
    assert set(schema["required"]) == set(record)
    assert schema["properties"]["schema_version"]["const"] == SUITE_RECORD_SCHEMA_VERSION
    assert SUITE_RECORD_SCHEMA_VERSION == "q01-release-suite-verdict-v6"
    assert RELEASE_DESIGN_IDS == {schema["properties"]["design_id"]["const"]} == {"q01-release-v7"}
    assert V3_VERIFYING_DESIGN_IDS == frozenset()
    # a pass is a scoped pass, never a qualification; a V3 claim the schema forbids is refused
    state = critic_qualification_from_suite(record, "c" * 64)
    assert (state.status, state.reason) == ("scoped_pass", "design_cannot_verify_v3")
    assert not Draft202012Validator(schema).is_valid(_record(schema, v3_error_independence="verified"))
    with pytest.raises(CriticQualificationError, match="V3 unverified"):
        critic_qualification_from_suite(_record(schema, v3_error_independence="verified"), "c" * 64)
    with pytest.raises(CriticQualificationError, match="record sha256"):
        critic_qualification_from_suite({**record, "record_sha256": "e" * 64}, "c" * 64)
    # a v3 design id is not a release design, and a v4-shaped record is not read at all
    v3 = json.loads((V3 / "suite_record.schema.json").read_text())
    assert critic_qualification_from_suite(_record(v3, v3_error_independence="verified"), "c" * 64).status == \
        "unqualified"
    # a v6-shaped (or v5- or v4-shaped) record is not read at all
    for older in (V4, V5, V6):
        schema_old = json.loads((older / "suite_record.schema.json").read_text())
        old = {key: value for key, value in _record(schema_old).items() if key in schema_old["required"]}
        old["schema_version"] = schema_old["properties"]["schema_version"]["const"]
        old["design_id"] = schema_old["properties"]["design_id"]["const"]
        old["record_sha256"] = suite_record_sha256(old)
        assert Draft202012Validator(schema_old).is_valid(old)
        with pytest.raises(CriticQualificationError, match="exact suite verdict record"):
            critic_qualification_from_suite(old, "c" * 64)
    # audit 5: a pass must be provider-attested on both sides and from an unstopped run
    for field, value in (("critic_transport_identity", "not_attested"), ("judge_transport_identity", "not_attested"),
                         ("run_stopped", True)):
        assert not Draft202012Validator(schema).is_valid(_record(schema, **{field: "x"}))
        assert not Draft202012Validator(schema).is_valid(_record(schema, **{field: value}))  # not as a pass
        assert Draft202012Validator(schema).is_valid(_record(schema, suite_outcome="fail", **{field: value}))
        with pytest.raises(CriticQualificationError, match="provider-reported|stopped run"):
            critic_qualification_from_suite(_record(schema, **{field: value}), "c" * 64)
    # audit 6: a pass carries a judge-log digest for every trial and its provider ids
    for field, value in (("judge_logs", []), ("judge_logs", [{"trial_id": "t1", "lines_sha256": None}]),
                         ("provider_id_count", 0)):
        assert not Draft202012Validator(schema).is_valid(_record(schema, **{field: value}))
        assert Draft202012Validator(schema).is_valid(_record(schema, suite_outcome="incomplete", **{field: value}))
        with pytest.raises(CriticQualificationError, match="judge log digest|provider ids"):
            critic_qualification_from_suite(_record(schema, **{field: value}), "c" * 64)


def test_release_v4_pins_every_version_the_gate_the_verifier_and_the_harness():
    manifest = json.loads((V4 / "FROZEN.json").read_text())
    required = [
        *(f"evals/deeptwin/qualification/release-v4/{name}" for name in (
            "qualification_design.json", "independence_profile.json", "sealed_expectation.schema.json",
            "pre_dispatch_manifest.schema.json", "suite_record.schema.json")),
        "evals/deeptwin/effects/lens-effects-v4.json", "evals/deeptwin/effects/lens-effects-v3.json",
        "evals/deeptwin/qualification/release-v3/FROZEN.json", "evals/deeptwin/qualification/release-v2/FROZEN.json",
        "evals/deeptwin/qualification/release-v1/FROZEN.json", GATE,
        "evals/deeptwin/verifiers/sealed_critic.py", "evals/deeptwin/verifiers/q01_core.py",
        "evals/deeptwin/q01_release_manifest.py", "app/critic_contract.py", "app/critic_audit.py",
        "evals/deeptwin/harness/q01_harness.py",
    ]
    for path in required:
        assert path in manifest["files"], path
    assert V5_CHANGED_CODE <= set(manifest["files"])
    for path, digest in manifest["files"].items():
        if path in V5_CHANGED_CODE:
            # pinned by v4 as it was at the v4 freeze (fb718b6); changed since only as release-v5 and v6
            assert hashlib.sha256(_v4_bytes(path)).hexdigest() == digest, path
            assert path in json.loads((V5 / "FROZEN.json").read_text())["files"], path
            continue
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_release_v4_records_the_verifier_and_harness_it_froze():
    design = json.loads((V4 / "qualification_design.json").read_text())
    manifest = json.loads((V4 / "FROZEN.json").read_text())
    state, harness = design["verifier"]["state_at_freeze"], design["verifier"]["harness_at_freeze"]
    assert state["exists"] is True and state["version"] == "q01-sealed-verifier-2"
    assert state["file_set_sha256"] == manifest["verifier"]["file_set_sha256"] == _file_set_sha256(state["files"])
    assert harness["version"] == "q01-harness-2"
    assert harness["file_set_sha256"] == manifest["harness"]["file_set_sha256"] == _file_set_sha256(
        harness["files"])
    # every recorded file hash is the file at the v4 freeze commit (the working tree for files unchanged
    # since; audit 5 changed app/critic_trial.py, so it is checked at fb718b6 too)
    for path, digest in {**state["files"], **harness["files"]}.items():
        changed = V5_CHANGED_CODE | V6_CHANGED_CODE | V7_CHANGED_CODE
        data = _v4_bytes(path) if path in changed else (ROOT / path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, path


def test_release_v4_resolves_the_third_audit():
    design = json.loads((V4 / "qualification_design.json").read_text())
    profile = json.loads((V4 / "independence_profile.json").read_text())
    effects = json.loads((ROOT / "evals/deeptwin/effects/lens-effects-v4.json").read_text())
    schema = json.loads((V4 / "pre_dispatch_manifest.schema.json").read_text())
    # BF1: no pass qualifies under v4; V3 cannot be verified here
    assert "NOT a critic qualification" in design["acceptance"]["what_a_pass_confers"]
    assert profile["design_id"] == "q01-release-v4" and profile["judge_separation"]["established"] is False
    assert profile["v3_error_independence"]["verifiable_under_this_design"] is False
    # BF2: fixed repetitions, full manifest recheck, composition recorded
    assert design["execution"]["repetitions_per_case"] == 3 and "never supplied" in design["execution"][
        "repetitions_fixed"]
    assert "no hash-values-only path" in design["pre_dispatch"]["freeze"]
    assert "one trial used for more than one slot" in design["acceptance"]["suite_outcome"]["incomplete"]
    config = schema["$defs"]["critic_configuration"]["properties"]
    assert config["call_and_run_deadlines"]["required"] == ["call_seconds", "run_seconds"]
    assert {"author", "reviewer", "sealing"} == set(schema["properties"]["attestations"]["required"])
    # BF3: lens pack is configuration; the effect run binds every arm before dispatch
    assert "never read from the sealed bundle" in design["critic_configuration"]["lens_refs_and_digests"]
    assert set(schema["properties"]["lens_effect"]["oneOf"][1]["required"]) >= {"arms", "arm_case_order"}
    assert "NOT measured" in effects["not_measured"]["joint_error_change"]
    arms = {arm["id"]: arm for arm in effects["arms"]}
    assert arms["general_multi_perspective"]["state"] == "text_not_yet_fixed"
    assert "non-null" in effects["pre_dispatch"]["text_digests"]
    assert "one run that covers all arms" in effects["single_use"]


def test_frozen_designs_before_v5_are_byte_identical_to_their_freeze():
    # v1..v4 files and lens-effects-v1..v4 are never edited in place
    for manifest_path in (MANIFEST, MANIFEST_V2, V3 / "FROZEN.json", V4 / "FROZEN.json"):
        manifest = json.loads(manifest_path.read_text())
        for path, digest in manifest["files"].items():
            if path == GATE or (manifest_path.parent == V4 and path in V5_CHANGED_CODE):
                continue  # checked against bd6a976 / fb718b6 in the v3 and v4 tests above
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


# ---------------------------------------------------------------- release-v5 (audit 4 of release-v4)


def test_release_v5_pins_every_version_every_manifest_the_gate_the_verifier_and_the_harness():
    # Audit 5 changed the gate, the verifier modules and the harness for release-v6. v5's FROZEN.json
    # is never edited, so its hashes for that code are checked against the files as committed in the
    # v5 freeze commit 4aed36d (the way v4's are checked against fb718b6); release-v6 pins the new code.
    manifest = json.loads((V5 / "FROZEN.json").read_text())
    assert manifest["release_v4_frozen_in_commit"] == V4_FROZEN_IN_COMMIT
    required = [
        *(f"evals/deeptwin/qualification/release-v5/{name}" for name in (
            "qualification_design.json", "independence_profile.json", "sealed_expectation.schema.json",
            "pre_dispatch_manifest.schema.json", "suite_record.schema.json")),
        *(f"evals/deeptwin/effects/lens-effects-v{version}.json" for version in (1, 2, 3, 4, 5)),
        *(f"evals/deeptwin/qualification/release-v{version}/FROZEN.json" for version in (1, 2, 3, 4)),
        *(f"evals/deeptwin/qualification/release-v4/{name}" for name in (
            "qualification_design.json", "independence_profile.json", "sealed_expectation.schema.json",
            "pre_dispatch_manifest.schema.json", "suite_record.schema.json")),
        GATE, *V5_CHANGED_CODE, "app/critic_contract.py", "app/critic_audit.py",
    ]
    for path in required:
        assert path in manifest["files"], path
    assert V6_CHANGED_CODE - {"app/critic_trial.py"} <= set(manifest["files"])
    v6 = json.loads((V6 / "FROZEN.json").read_text())["files"]
    for path, digest in manifest["files"].items():
        if path in V6_CHANGED_CODE:
            # pinned by v5 as it was at the v5 freeze (4aed36d); changed since only as release-v6
            assert hashlib.sha256(_v5_bytes(path)).hexdigest() == digest, path
            assert path in v6, path
            continue
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_release_v5_records_the_verifier_and_harness_it_froze():
    # v5 recorded the verifier and harness of 4aed36d; audit 5 changed both for release-v6
    # (q01-sealed-verifier-4, q01-harness-4), so the recorded identities are checked against the
    # files at 4aed36d for the changed code and against the working tree for the rest.
    from evals.deeptwin.harness.q01_harness import harness_identity
    from evals.deeptwin.verifiers.sealed_critic import verifier_identity

    design = json.loads((V5 / "qualification_design.json").read_text())
    manifest = json.loads((V5 / "FROZEN.json").read_text())
    state = design["verifier"]["state_at_freeze"]
    assert state["exists"] is True and state["version"] == "q01-sealed-verifier-3"
    assert state["file_set_sha256"] == manifest["verifier"]["file_set_sha256"] == _file_set_sha256(state["files"])
    assert {"app/critic_contract.py", "app/critic_audit.py"} <= set(state["files"])
    harness = design["verifier"]["harness_at_freeze"]
    assert harness["version"] == "q01-harness-3"
    assert harness["file_set_sha256"] == manifest["harness"]["file_set_sha256"] == _file_set_sha256(
        harness["files"])
    for path, digest in {**state["files"], **harness["files"]}.items():
        # audit 6 changed more of that code for release-v7; it is checked at 4aed36d as well
        data = _v5_bytes(path) if path in V6_CHANGED_CODE | V7_CHANGED_CODE else (ROOT / path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, path
    # a new verifier and a new harness are a new version
    assert verifier_identity()["sha256"] != state["file_set_sha256"]
    assert harness_identity()["sha256"] != harness["file_set_sha256"]
    v4 = json.loads((V4 / "FROZEN.json").read_text())
    assert v4["verifier"]["file_set_sha256"] != state["file_set_sha256"]
    assert v4["harness"]["file_set_sha256"] != harness["file_set_sha256"]


def test_release_v5_resolves_the_fourth_audit():
    design = json.loads((V5 / "qualification_design.json").read_text())
    profile = json.loads((V5 / "independence_profile.json").read_text())
    effects = json.loads((ROOT / "evals/deeptwin/effects/lens-effects-v5.json").read_text())
    schema = json.loads((V5 / "pre_dispatch_manifest.schema.json").read_text())
    record = json.loads((V5 / "suite_record.schema.json").read_text())
    assert design["design_id"] == profile["design_id"] == "q01-release-v5"
    assert schema["properties"]["schema"]["const"] == "q01-pre-dispatch-manifest-3"
    # B1: the dispatch journal, the planned slots, and the slot fixed before dispatch
    identity = schema["properties"]["run_identity"]
    assert {"planned_slots", "dispatch_journal"} <= set(identity["required"])
    journal = design["pre_dispatch"]["dispatch_journal"]
    assert "hash-chained" in journal["requirement"] and "before the trial's first read or call" in journal["write"]
    assert "equal the journal exactly" in journal["verify"]
    assert "journalled trial whose result is not submitted" in design["acceptance"]["suite_outcome"]["incomplete"]
    assert "dispatch_journal_head" in record["required"]
    # B2: a spent set is refused and prior sets travel into the suite record
    assert "sealed_expectations_sha256" in schema["$defs"]["prior_attempts"]["items"]["required"]
    assert "qualification_sets" in schema["properties"]["lens_effect"]["oneOf"][1]["required"]
    assert {"prior_sealed_set_sha256s", "prior_attempts_sha256"} <= set(record["required"])
    assert "refuses a run whose sealed_dataset_sha256 or sealed_expectations_sha256" in design["pre_dispatch"][
        "spent_sets"]
    # N3: the commit reference and its post-verdict audit item
    assert "manifest_commit_ref" in record["required"]
    assert any("before the first ledger event" in item for item in design["acceptance"]["post_verdict_audit"])
    # N4: judge separation
    assert "non-null prompt digest" in profile["judge_separation"]["requirement"]
    assert "the sealing step" in profile["judge_separation"]["excluded_as_judge"]
    # N5: the gate refuses schema-invalid records; V3 stays unverifiable
    assert record["properties"]["v3_error_independence"]["const"] == "unverified"
    assert "refuses (does not cap)" in design["acceptance"]["what_a_pass_confers"]
    assert profile["judge_separation"]["established"] is False
    assert profile["v3_error_independence"]["verifiable_under_this_design"] is False
    # N6: lens-effect manifest checks
    assert "interleaved per case" in effects["pre_dispatch"]["order"]
    assert "no two arms carry the same lens pack" in effects["pre_dispatch"]["per_arm"]
    assert "cannot execute" in effects["execution"]


def test_frozen_designs_before_v6_are_byte_identical_to_their_freeze():
    # v1..v5 files and lens-effects-v1..v5 are never edited in place; the code v5 pinned and
    # audit 5 changed is checked against 4aed36d above
    manifest = json.loads((V5 / "FROZEN.json").read_text())
    for path, digest in manifest["files"].items():
        if path in V6_CHANGED_CODE:
            continue
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


# ---------------------------------------------------------------- release-v6 (audit 5 of release-v5)


def test_release_v6_pins_every_version_every_manifest_the_gate_the_verifier_and_the_harness():
    # Audit 6 changed the gate, the verifier (sealed_critic, q01_release_manifest), the harness
    # (q01_harness, app/critic_trial.py) and claude_rig.py for release-v7. v6's FROZEN.json is never
    # edited, so its hashes for that code are checked against the files as committed in the v6 freeze
    # commit c3204d6 (the way v5's are checked against 4aed36d); release-v7 pins the new code.
    manifest = json.loads((V6 / "FROZEN.json").read_text())
    assert manifest["release_v5_frozen_in_commit"] == V5_FROZEN_IN_COMMIT
    assert manifest["release_v4_frozen_in_commit"] == V4_FROZEN_IN_COMMIT
    required = [
        *(f"evals/deeptwin/qualification/release-v{version}/{name}" for version in (5, 6) for name in (
            "qualification_design.json", "independence_profile.json", "sealed_expectation.schema.json",
            "pre_dispatch_manifest.schema.json", "suite_record.schema.json")),
        *(f"evals/deeptwin/effects/lens-effects-v{version}.json" for version in (1, 2, 3, 4, 5, 6)),
        *(f"evals/deeptwin/qualification/release-v{version}/FROZEN.json" for version in (1, 2, 3, 4, 5)),
        GATE, *V6_CHANGED_CODE, "app/critic_contract.py", "app/critic_audit.py",
        # the attested release transport and judge path (audit 5, X1)
        "evals/deeptwin/harness/claude_rig.py", "app/adapters/claude_api.py", "evals/deeptwin/verifiers/claude_judge.py",
    ]
    for path in required:
        assert path in manifest["files"], path
    v7 = json.loads((V7 / "FROZEN.json").read_text())["files"]
    assert V7_CHANGED_CODE <= set(manifest["files"])
    for path, digest in manifest["files"].items():
        if path in V7_CHANGED_CODE:
            # pinned by v6 as it was at the v6 freeze (c3204d6); changed since only as release-v7
            assert hashlib.sha256(_v6_bytes(path)).hexdigest() == digest, path
            assert path in v7, path
            continue
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_release_v6_records_the_verifier_and_harness_it_froze():
    # v6 recorded the verifier and harness of c3204d6; audit 6 changed both for release-v7
    # (q01-sealed-verifier-5, q01-harness-5), so the recorded identities are checked against the
    # files at c3204d6 for the changed code and against the working tree for the rest.
    from evals.deeptwin.harness.q01_harness import HARNESS_FILES, harness_identity
    from evals.deeptwin.verifiers.sealed_critic import VERIFIER_FILES, verifier_identity

    design = json.loads((V6 / "qualification_design.json").read_text())
    manifest = json.loads((V6 / "FROZEN.json").read_text())
    state = design["verifier"]["state_at_freeze"]
    assert state["exists"] is True and state["version"] == "q01-sealed-verifier-4"
    assert state["file_set_sha256"] == manifest["verifier"]["file_set_sha256"] == _file_set_sha256(state["files"])
    assert set(state["files"]) == set(VERIFIER_FILES) >= {"app/critic_contract.py", "app/critic_audit.py"}
    harness = design["verifier"]["harness_at_freeze"]
    assert harness["version"] == "q01-harness-4"
    assert harness["file_set_sha256"] == manifest["harness"]["file_set_sha256"] == _file_set_sha256(
        harness["files"])
    assert set(harness["files"]) == set(HARNESS_FILES) >= {"evals/deeptwin/harness/claude_rig.py",
                                                          "app/adapters/claude_api.py", "app/critic_trial.py"}
    for path, digest in {**state["files"], **harness["files"]}.items():
        data = _v6_bytes(path) if path in V7_CHANGED_CODE else (ROOT / path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, path
    # a new verifier and a new harness are a new version
    assert verifier_identity()["sha256"] != state["file_set_sha256"]
    assert harness_identity()["sha256"] != harness["file_set_sha256"]
    v5 = json.loads((V5 / "FROZEN.json").read_text())
    assert v5["verifier"]["file_set_sha256"] != state["file_set_sha256"]  # a new verifier is a new version
    assert v5["harness"]["file_set_sha256"] != harness["file_set_sha256"]


def test_release_v6_resolves_the_fifth_audit():
    design = json.loads((V6 / "qualification_design.json").read_text())
    profile = json.loads((V6 / "independence_profile.json").read_text())
    effects = json.loads((ROOT / "evals/deeptwin/effects/lens-effects-v6.json").read_text())
    schema = json.loads((V6 / "pre_dispatch_manifest.schema.json").read_text())
    record = json.loads((V6 / "suite_record.schema.json").read_text())
    assert design["design_id"] == profile["design_id"] == "q01-release-v6"
    assert profile["schema"] == "q01-independence-profile-6" and profile["judge_separation"]["established"] is False
    assert schema["properties"]["schema"]["const"] == "q01-pre-dispatch-manifest-4"
    assert effects["design_id"] == "lens-effects-v6" and "release-v6" in effects["transport"]
    # X1: the served model is what the provider reported, checked at dispatch and by the verifier
    checked = design["critic_configuration"]["checked_at_dispatch"]
    assert "provider's response" in checked and "transport_identity_unattested" in checked
    assert "what the call was ASKED to use" in checked and "exact model string" in checked
    assert "can never complete a release trial" in design["critic_configuration"]["transport"]
    assert "judge_model" in design["run_identity"]["fields"] and "judge_model" in schema["properties"][
        "run_identity"]["required"]
    assert "not_judged (never pass)" in design["judge"]["judge_attestation"]
    assert {"critic_transport_identity", "judge_transport_identity", "run_stopped"} <= set(record["required"])
    assert any("reported" in claim and "request id" in claim for claim in design["claims_if_passed"])
    assert any(item.startswith("provider attestation is what the pinned product adapter parsed")
               for item in design["open"])
    assert any("request id of every critic call" in item for item in design["acceptance"]["post_verdict_audit"])
    # non-blocking 1: the trial base directory
    assert "trial_base_dir" in schema["properties"]["run_identity"]["required"]
    assert "leaves that trial's directory as evidence" in design["run_identity"]["trial_base_dir"]
    assert any("removes the failed trial's directory" in item for item in design["open"])
    # non-blocking 3: prior attempts carry case ids and case sha256s
    assert {"case_ids", "case_sha256s"} <= set(schema["$defs"]["prior_attempts"]["items"]["required"])
    assert "case sha256s appears among" in design["pre_dispatch"]["spent_sets"]
    # non-blocking 5: no test hook in the gate
    assert "the gate has no test hook" in design["acceptance"]["what_a_pass_confers"]
    # non-blocking 6: the alias table only guards against accidental self-judging
    assert "only guards against accidental self-judging" in design["judge"]["judge_binding"]
    # non-blocking 7: who enforces the USD hard stop, and the stop comes from the journal
    assert "T077 dispatcher" in design["execution"]["spend"]
    assert "takes no caller flag" in design["pre_dispatch"]["dispatch_journal"]["stop"]
    # items 2 and 4 remain organizational, stated precisely
    assert any(item.startswith("second-manifest cherry-picking (audit 5, item 2)") for item in design["open"])
    assert any(item.startswith("hand-built record provenance (audit 5, item 4)") for item in design["open"])
    assert profile["v3_error_independence"]["verifiable_under_this_design"] is False


def test_an_absent_freeze_commit_xfails_explicitly_never_silently():
    # audit 5, note 8: a guard whose freeze commit is missing (shallow clone) reports it
    with pytest.raises(pytest.xfail.Exception, match="absent"):
        _at_commit("0" * 40, GATE)
    assert hashlib.sha256(_at_commit(V3_FROZEN_IN_COMMIT, GATE)).hexdigest() == V3_GATE_SHA256


def test_frozen_designs_before_v7_are_byte_identical_to_their_freeze():
    # v1..v6 files and lens-effects-v1..v6 are never edited in place; the code v6 pinned and
    # audit 6 changed is checked against c3204d6 above
    manifest = json.loads((V6 / "FROZEN.json").read_text())
    for path, digest in manifest["files"].items():
        if path in V7_CHANGED_CODE:
            continue
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


# ---------------------------------------------------------------- release-v7 (audit 6 of release-v6)


def test_release_v7_pins_every_version_every_manifest_the_gate_the_verifier_and_the_harness():
    manifest = json.loads((V7 / "FROZEN.json").read_text())
    assert manifest["release_v6_frozen_in_commit"] == V6_FROZEN_IN_COMMIT
    assert manifest["release_v5_frozen_in_commit"] == V5_FROZEN_IN_COMMIT
    required = [
        *(f"evals/deeptwin/qualification/release-v{version}/{name}" for version in (6, 7) for name in (
            "qualification_design.json", "independence_profile.json", "sealed_expectation.schema.json",
            "pre_dispatch_manifest.schema.json", "suite_record.schema.json")),
        *(f"evals/deeptwin/effects/lens-effects-v{version}.json" for version in range(1, 8)),
        *(f"evals/deeptwin/qualification/release-v{version}/FROZEN.json" for version in range(1, 7)),
        GATE, *V7_CHANGED_CODE, "evals/deeptwin/verifiers/q01_core.py", "app/critic_contract.py",
        "app/critic_audit.py", "evals/deeptwin/verifiers/claude_judge.py",
    ]
    for path in required:
        assert path in manifest["files"], path
    for path, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_release_v7_pins_the_product_adapter_only_per_attempt():
    # audit 6, non-blocking 6: FROZEN.json pins the evals code and the gate, never the product
    # adapter; the adapter is in the harness identity that each pre-dispatch manifest fixes
    from evals.deeptwin.harness.q01_harness import HARNESS_FILES, harness_identity

    manifest = json.loads((V7 / "FROZEN.json").read_text())
    design = json.loads((V7 / "qualification_design.json").read_text())
    adapter = "app/adapters/claude_api.py"
    assert adapter not in manifest["files"] and adapter in HARNESS_FILES
    assert manifest["harness"]["pinned_per_attempt_only"] == [adapter]
    assert "file_set_sha256" not in manifest["harness"]
    harness = design["verifier"]["harness_at_freeze"]
    assert harness["version"] == harness_identity()["version"] == "q01-harness-5"
    assert adapter not in harness["files"] and harness["pinned_per_attempt_only"] == [adapter]
    assert set(harness["files"]) | {adapter} == set(HARNESS_FILES)
    for path, digest in harness["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    assert "never the product adapter" in design["pre_dispatch"]["harness"]
    assert "refuses dispatch when the running files differ" in design["pre_dispatch"]["harness"]
    assert "does not pin the product adapter" in manifest["rule"]


def test_release_v7_records_the_verifier_that_exists():
    from evals.deeptwin.verifiers.sealed_critic import VERIFIER_FILES, verifier_identity

    design = json.loads((V7 / "qualification_design.json").read_text())
    manifest = json.loads((V7 / "FROZEN.json").read_text())
    state = design["verifier"]["state_at_freeze"]
    assert state["exists"] is True and state["version"] == verifier_identity()["version"] == "q01-sealed-verifier-5"
    assert state["file_set_sha256"] == verifier_identity()["sha256"] == manifest["verifier"]["file_set_sha256"]
    assert set(state["files"]) == set(VERIFIER_FILES)
    for path, digest in state["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    v6 = json.loads((V6 / "FROZEN.json").read_text())
    assert v6["verifier"]["file_set_sha256"] != state["file_set_sha256"]


def test_release_v7_resolves_the_sixth_audit():
    design = json.loads((V7 / "qualification_design.json").read_text())
    profile = json.loads((V7 / "independence_profile.json").read_text())
    effects = json.loads((ROOT / "evals/deeptwin/effects/lens-effects-v7.json").read_text())
    schema = json.loads((V7 / "pre_dispatch_manifest.schema.json").read_text())
    record = json.loads((V7 / "suite_record.schema.json").read_text())
    assert design["design_id"] == profile["design_id"] == "q01-release-v7"
    assert profile["schema"] == "q01-independence-profile-7" and profile["judge_separation"]["established"] is False
    assert schema["properties"]["schema"]["const"] == "q01-pre-dispatch-manifest-5"
    assert effects["design_id"] == "lens-effects-v7" and "release-v7" in effects["transport"]
    # Y1: exactly one judging per trial, in the code path and in the acceptance rule and audit
    assert "trial_already_judged" in design["judge"]["one_judging_per_trial"]
    assert "one_judging_per_trial" in design["acceptance"]["suite_outcome"]
    assert "more than one judging of a trial" in design["acceptance"]["suite_outcome"]["incomplete"]
    assert {"judge_logs", "provider_ids_sha256", "provider_id_count"} <= set(record["required"])
    audit = design["acceptance"]["post_verdict_audit"]
    assert any(item.startswith("one judging per trial") and "both directions" in item for item in audit)
    # Y2: distinct ids in the adapter's forms, reconciled with the provider's records both ways
    assert "occurs twice in the suite" in design["acceptance"]["suite_outcome"]["incomplete"]
    assert audit[3].startswith("two-way reconciliation") and "no unlogged request exists" in audit[3]
    assert "req_[A-Za-z0-9]{8,128}" in design["critic_configuration"]["checked_at_dispatch"]
    assert "the message id is required" in design["critic_configuration"]["checked_at_dispatch"]
    assert any("not on code" in claim for claim in design["claims_if_passed"])
    assert any("in-process constructed replies" in item and "two-way reconciliation" in item
               for item in design["open"])
    # non-blocking 2..6
    assert "human review" in design["pre_dispatch"]["spent_sets"]
    assert design["critic_configuration"]["transport"].startswith("A release trial must run")
    assert "(see open)" in design["critic_configuration"]["transport"]
    assert "critic_transport" in schema["properties"]["run_identity"]["required"]
    assert "critic_transport" in design["run_identity"]["fields"]
    assert "never the product adapter" in design["pre_dispatch"]["harness"]
    assert profile["v3_error_independence"]["verifiable_under_this_design"] is False


def test_release_v7_code_names_the_adapters_id_forms():
    # the id forms the verifier requires are the product adapter's (audit 6, Y2)
    import re

    from evals.deeptwin.q01_release_manifest import PROVIDER_REQUEST_ID, TEST_DOUBLE_TRANSPORTS

    adapter = (ROOT / "app/adapters/claude_api.py").read_text(encoding="utf-8")
    match = re.search(r'_PROVIDER_REQUEST_ID = re.compile\(r"([^"]+)"\)', adapter)
    assert match and match.group(1) == PROVIDER_REQUEST_ID.pattern
    assert TEST_DOUBLE_TRANSPORTS == frozenset()  # release-v7 names no test double
