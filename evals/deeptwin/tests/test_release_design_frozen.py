"""T076: the release-v1..v4 qualification, independence and lens-effect designs are frozen.

A changed file is a new design version, never a silent edit of the frozen one; and the
frozen designs never admit the calibration cases or a same-model judge as independent.
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


def _v3_gate_bytes():
    try:
        return subprocess.run(["git", "show", f"{V3_FROZEN_IN_COMMIT}:{GATE}"], cwd=ROOT, capture_output=True,
                              check=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None  # e.g. a shallow checkout without bd6a976: the recorded hash still stands


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
            historical = _v3_gate_bytes()
            if historical is not None:
                assert hashlib.sha256(historical).hexdigest() == digest
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
        "v3_error_independence": "unverified",
    }
    record.update(overrides)
    record["record_sha256"] = suite_record_sha256(record)
    return record


def test_the_product_gate_accepts_exactly_the_v4_suite_record_schema():
    # Audit 3 moved the gate from v3 to v4 records (this test read v3 before; the v3
    # schema itself is unchanged and still pinned by release-v3/FROZEN.json).
    from jsonschema import Draft202012Validator

    from app.services.critic_qualification import (
        RELEASE_DESIGN_IDS,
        SUITE_RECORD_SCHEMA_VERSION,
        V3_VERIFYING_DESIGN_IDS,
        CriticQualificationError,
        critic_qualification_from_suite,
    )

    schema = json.loads((V4 / "suite_record.schema.json").read_text())
    record = _record(schema)
    assert Draft202012Validator(schema).is_valid(record)
    assert set(schema["required"]) == set(record)
    assert schema["properties"]["schema_version"]["const"] == SUITE_RECORD_SCHEMA_VERSION
    assert RELEASE_DESIGN_IDS == {schema["properties"]["design_id"]["const"]} == {"q01-release-v4"}
    assert V3_VERIFYING_DESIGN_IDS == frozenset()
    # a pass is a scoped pass, never a qualification, whatever the V3 field says
    for v3 in ("unverified", "verified"):
        state = critic_qualification_from_suite(_record(schema, v3_error_independence=v3), "c" * 64)
        assert (state.status, state.reason) == ("scoped_pass", "design_cannot_verify_v3")
    assert not Draft202012Validator(schema).is_valid(_record(schema, v3_error_independence="verified"))
    with pytest.raises(CriticQualificationError, match="record sha256"):
        critic_qualification_from_suite({**record, "record_sha256": "e" * 64}, "c" * 64)
    # a v3 record is no longer a release design
    v3 = json.loads((V3 / "suite_record.schema.json").read_text())
    old = _record(v3, v3_error_independence="verified")
    assert critic_qualification_from_suite(old, "c" * 64).status == "unqualified"


V4 = ROOT / "evals/deeptwin/qualification/release-v4"


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
    for path, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_release_v4_records_the_verifier_and_harness_that_exist():
    from evals.deeptwin.harness.q01_harness import harness_identity
    from evals.deeptwin.verifiers.sealed_critic import VERIFIER_FILES, verifier_identity

    design = json.loads((V4 / "qualification_design.json").read_text())
    manifest = json.loads((V4 / "FROZEN.json").read_text())
    state = design["verifier"]["state_at_freeze"]
    assert state["exists"] is True and state["version"] == verifier_identity()["version"]
    assert state["file_set_sha256"] == verifier_identity()["sha256"] == manifest["verifier"]["file_set_sha256"]
    assert set(state["files"]) == set(VERIFIER_FILES) >= {"app/critic_contract.py", "app/critic_audit.py"}
    for path, digest in state["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    harness = design["verifier"]["harness_at_freeze"]
    assert harness["file_set_sha256"] == harness_identity()["sha256"] == manifest["harness"]["file_set_sha256"]


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


def test_frozen_designs_before_v4_are_byte_identical_to_their_freeze():
    # v1, v2 and v3 files and lens-effects-v1..v3 are never edited in place
    for manifest_path in (MANIFEST, MANIFEST_V2, V3 / "FROZEN.json"):
        manifest = json.loads(manifest_path.read_text())
        for path, digest in manifest["files"].items():
            if path == GATE:
                continue  # checked against bd6a976 in the v3 test above
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
