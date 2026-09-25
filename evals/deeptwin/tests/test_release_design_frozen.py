"""T076: the release-v1 qualification, independence and lens-effect designs are frozen.

A changed file is a new design version, never a silent edit of the frozen one; and the
frozen designs never admit the calibration cases or a same-model judge as independent.
"""

import hashlib
import json
from pathlib import Path

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
