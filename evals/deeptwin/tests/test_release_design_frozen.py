"""T076: the release-v1, -v2 and -v3 qualification, independence and lens-effect designs are frozen.

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


V3 = ROOT / "evals/deeptwin/qualification/release-v3"


def test_release_v3_pins_every_version_and_the_product_gate():
    manifest = json.loads((V3 / "FROZEN.json").read_text())
    for required in ("evals/deeptwin/qualification/release-v2/FROZEN.json",
                     "evals/deeptwin/qualification/release-v1/FROZEN.json",
                     "app/services/critic_qualification.py"):
        assert required in manifest["files"]
    for path, digest in manifest["files"].items():
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


def test_the_product_gate_accepts_exactly_the_v3_suite_record_schema():
    from jsonschema import Draft202012Validator

    from app.services.critic_qualification import (
        RELEASE_DESIGN_IDS,
        SUITE_RECORD_SCHEMA_VERSION,
        critic_qualification_from_suite,
    )

    schema = json.loads((V3 / "suite_record.schema.json").read_text())
    record = {
        "schema_version": SUITE_RECORD_SCHEMA_VERSION, "design_id": "q01-release-v3",
        "critic_configuration_digest": "c" * 64, "pre_dispatch_manifest_sha256": "a" * 64,
        "sealed_set_sha256": "d" * 64, "attempt": 1, "prior_outcomes": [], "suite_outcome": "pass",
        "independence_profile_sha256": "b" * 64, "judge_separation_established": True,
        "v3_error_independence": "unverified", "record_sha256": "e" * 64,
    }
    assert Draft202012Validator(schema).is_valid(record)
    assert set(schema["required"]) == set(record)
    assert RELEASE_DESIGN_IDS == {schema["properties"]["design_id"]["const"]}
    # a pass while V3 is unverified is a scoped pass, never a qualification
    assert critic_qualification_from_suite(record, "c" * 64).status == "scoped_pass"
