"""Offline checks of the SIMULATED T077 rehearsal sets and profile (no dispatch, no provider).

The sets are simulated rehearsal material (``qualification/rehearsal_t077``), never a sealed
set of a release run; these checks only keep them well formed and new.
"""

import json
import re
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from evals.deeptwin.harness import q01_cases
from evals.deeptwin.qualification.rehearsal_t077 import simulated_sets
from evals.deeptwin.verifiers import sealed_critic as sc
from evals.deeptwin.verifiers.q01_core import BOUNDARY_CLASSES

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "evals/deeptwin/qualification/rehearsal_t077"


@pytest.fixture(scope="module")
def sets(tmp_path_factory):
    root = tmp_path_factory.mktemp("t077-sets")
    return {world: simulated_sets.materialize(world, root) for world in simulated_sets.WORLDS}


@pytest.mark.parametrize("world", sorted(simulated_sets.WORLDS))
def test_each_simulated_set_meets_the_v7_composition_and_binds(sets, world):
    info = sets[world]
    expectations = sc.load_sealed_expectations(Path(info["expectations_path"]), info["sealed_expectations_sha256"])
    materials = sc.load_sealed_materials_dir(Path(info["task_dir"]), info["sealed_dataset_sha256"])
    sc.check_binding(expectations, materials)
    assert expectations.composition_checked and sc.composition_problems(expectations) == []
    counts = {name: sum(case.expectation.boundary == name for case in expectations.cases.values())
              for name in BOUNDARY_CLASSES}
    assert len(expectations.cases) == 13 and min(counts.values()) >= 2
    assert all(case.expectation.basis.startswith("[simulated-author]") for case in expectations.cases.values())


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_simulated_sets_are_new_material(sets):
    calibration = q01_cases.materialize_all()
    calibration_ids = {case["case_id"] for case in calibration}
    ids = {world: set(info["sealed_case_sha256s"]) for world, info in sets.items()}
    assert not ids["sim-orchard"] & ids["sim-ferry"] and not calibration_ids & (ids["sim-orchard"] | ids["sim-ferry"])
    calibration_text = "\n".join(_strings(calibration))
    dev_text = (ROOT / "evals/deeptwin/tests/test_sealed_critic_verifier.py").read_text(encoding="utf-8")
    other = {"sim-orchard": "sim-ferry", "sim-ferry": "sim-orchard"}
    for world in simulated_sets.WORLDS:
        own = [text for case in simulated_sets.all_cases(world) for text in _strings(case["source"])]
        fragments = {piece.strip() for text in own for piece in re.split(r"[.;:,\n]", text) if len(piece.strip()) >= 24}
        foreign = "\n".join(_strings(simulated_sets.all_cases(other[world])))
        assert not [f for f in fragments if f in calibration_text or f in dev_text]
        # Finding of the rehearsal (recorded in the T077 rehearsal evidence): the two simulated worlds
        # share two template phrases of the authoring skeleton. release-v7 dataset.must_be_new bars any
        # wording of a previously dispatched set, and no code check (spent digests, case ids) sees it:
        # only human review does. Pinned here so a change to the shared template is noticed.
        assert sorted(f for f in fragments if f in foreign) == [
            "Keep every earlier version next to the new one", "Simulated tool contract (design only)"]


def test_simulated_profile_never_establishes_judge_separation():
    data = (PACKAGE / "simulated_independence_profile.json").read_bytes()
    profile = json.loads(data)
    assert profile["simulated"] is True and profile["design_id"] == "q01-release-v7"
    assert profile["judge_separation"]["established"] is False and profile["judge_separation"]["judge"] is None
    assert profile["v3_error_independence"]["status"] == "unverified"
    # a manifest pinning it loads with judge separation NOT established
    problems, established = sc._profile_problems(data, {"independence_profile": {"sha256": sha256(data).hexdigest()},
                                                        "judge_identity": "simulated-judge",
                                                        "judge_prompt_digest": None})
    assert problems == [] and established is False
    # no product code and no gate names it
    hits = subprocess.run(["git", "-C", str(ROOT), "grep", "-l", "simulated_independence_profile", "--", "app"],
                          capture_output=True, text=True, check=False).stdout
    assert hits == ""


def test_committed_manifest_record_is_labelled_simulated():
    record = json.loads((PACKAGE / "committed_manifests.json").read_text(encoding="utf-8"))
    assert record["simulated"] is True and "Not a release qualification" in record["statement"]
    assert {item["label"] for item in record["manifests"]} == {"offline", "live_same_family_judge", "live"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in record["manifests"])
    assert record["profile"]["sha256"] == sha256((PACKAGE / "simulated_independence_profile.json").read_bytes()).hexdigest()
