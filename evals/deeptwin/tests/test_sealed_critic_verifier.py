"""Offline tests of the data-driven release-v4 verifier (``verifiers/sealed_critic.py``).

TEST-ACTOR DEVELOPMENT DATA ONLY. Every material, candidate, counterexample,
expectation, lens pack, manifest and independence profile below is synthetic
development data authored in this file by the test actor (the harness/verifier
developer) to exercise the verifier's mechanics. It is NOT a sealed set, was not
written by an independent author, was not reviewed, names no real judge, and can
never qualify anything: release-v4 forbids the developer as author and requires new,
sealed, owner-held data. Trials are produced by the real harness with a scripted
``(system, user) -> str`` fixture; ``DevJudge`` is a deterministic offline stand-in.

Audit 3 (of release-v3) probes are marked ``BF1``/``BF2``/``BF3``: each forged,
degenerate or cherry-picked input now fails.
"""

import ast
import hashlib
import itertools
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.critic_contract import CONTRACT_VERSION, PARSER_VERSION
from app.services.critic_qualification import critic_qualification_from_suite
from evals.deeptwin.harness import q01_harness
from evals.deeptwin.harness.q01_cases import TASK_DIR, case_id_for, digest, file_bytes
from evals.deeptwin.harness.q01_harness import (
    PreDispatch,
    critic_prompt_digest,
    harness_identity,
    run_release_trial,
)
from evals.deeptwin.q01_release_manifest import (
    check_pre_dispatch_manifest,
    critic_configuration_digest,
    lens_refs_and_digests,
)
from evals.deeptwin.tests.q01_support import make_rig
from evals.deeptwin.verifiers import sealed_critic as sc
from evals.deeptwin.verifiers.sealed_critic import (
    FAIL,
    INCOMPLETE,
    INVALID,
    NOT_JUDGED,
    PASS,
    RESULT_SCHEMA,
    VERIFIER_VERSION,
    SealedSetError,
    build_suite_record,
    check_suite_record,
    load_release_run,
    load_sealed_expectations,
    load_sealed_materials,
    load_sealed_materials_dir,
    record_sha256,
    verifier_identity,
    verify_suite,
    verify_trial,
)

ROOT = Path(__file__).resolve().parents[3]
V4 = ROOT / "evals/deeptwin/qualification/release-v4"
ACCEPT, DEFECT, REJECTED = "accept_without_false_rejection", "required_defect", "rejected_counterexample"
VALID, UNRESOLVED, INSUFFICIENT = "valid_counterexample", "unresolved_specific_claim", "insufficient_evidence"
LABEL = "test-actor development data, not sealed"
JUDGE_IDENTITY = "dev fixture judge (test actor; not independent)"
DEV_LENS_PACK = {"id": "dev-lens", "version": "1", "rules": []}  # the configuration's (empty) lens pack


@pytest.fixture(autouse=True)
def prohibit_real_startup(monkeypatch):
    monkeypatch.setattr("app.codex_rpc.CodexRPC.start",
                        lambda *_args, **_kwargs: pytest.fail("real model startup forbidden"))


# ---------------------------------------------------------------- synthetic development materials


def _doc(doc_id, sections, media="text/markdown"):
    return {"id": doc_id, "version": "1", "media_type": media, "availability": "text",
            "sections": [{"location": location, "text": text} for location, text in sections]}


def dev_originals(r1_status="tentative"):
    return [
        _doc("brief.md", [
            ("scope", "Dev fixture brief: plan a printed leaflet for an imaginary field-notes archive."),
            ("handoff", "Each stage passes its whole versioned output onward; digests alone are not enough."),
            ("permissions", ("Source ledgers are read-only. Release waits for a named approver. "
                             "Nobody must shred the ledgers.")),
        ]),
        _doc("register.csv", [
            ("header", "id,title,keeper,certainty"),
            ("row:R1", f"R1,Heron ledger,Marsh society,{r1_status}"),
            ("row:R2", "R2,Kestrel ledger,Ana Lind,confirmed"),
        ], media="text/csv"),
        _doc("notes.md", [
            ("R1", "Dev fixture note: the keeper of R1 is inferred from handwriting; no deed settles it."),
        ]),
    ]


DEV_CRITERIA = {"id": "fixed-criteria", "version": "dev-1", "items": [
    {"id": f"Q{index}", "text": f"Dev fixture criterion {index} for the synthetic leaflet task."}
    for index in range(1, 9)]}


def _role(role_id, responsibility, outputs, inputs, checks):
    return {"id": role_id, "responsibility": responsibility,
            "model": {"provider": "dev-design", "model": f"role-{role_id}", "reasoning": "design-only",
                      "parameters": []},
            "tools": [{"name": "ledger-files", "description": "Dev fixture tool contract (design only).",
                       "operations": ["read-full", "write-new"], "read_paths": ["archive://dev/*"],
                       "write_paths": [f"planned://dev/{role_id}/*"]}],
            "inputs": inputs, "outputs": outputs, "checks": checks}


def dev_candidate(candidate_id, *, keeper="State each keeper with the certainty the register gives.",
                  handoff="whole versioned output", publication="released once a named approver signs",
                  alt=False):
    roles = [_role("A", "Read the ledgers and write a keeper digest.", ["digest"], [], [keeper]),
             _role("B", "Lay out the leaflet from the digest. " + keeper, ["leaflet"], ["digest"], [keeper])]
    if alt:
        roles = [_role("P", "Read ledgers and lay out the leaflet in one pass. " + keeper, ["digest", "leaflet"],
                       [], [keeper])]
    producer = "P" if alt else "A"
    artifacts = [{"id": "digest", "version": "1", "format": "CSV", "reference": f"planned://dev/{producer}/digest/1",
                  "producer": producer, "consumers": [] if alt else ["B"],
                  "access": {"readers": [producer] if alt else ["A", "B"], "writers": [producer], "mode": "full"},
                  "content_contract": "Dev fixture: keep every prior version."}]
    handoffs = [] if alt else [{"id": "h1", "from_role": "A", "to_role": "B", "artifact_ids": ["digest"],
                                "mode": handoff}]
    return {"id": candidate_id, "version": "1", "roles": roles, "artifacts": artifacts, "handoffs": handoffs,
            "control": {"execution_state": "planned", "publication": publication, "original_mutation": "never",
                        "notes": ["Dev fixture design; nothing was run."]}}


CANDIDATES = {
    "d-good": dev_candidate("d-good"),
    "d-alt": dev_candidate("d-alt", alt=True),
    "d-q1": dev_candidate("d-q1", keeper="Print every keeper as settled fact."),
    "d-q2": dev_candidate("d-q2", handoff="digest-only summary"),
    "d-q3": dev_candidate("d-q3", publication="auto-released when layout ends"),
    "d-miss": dev_candidate("d-miss"),
    "d-miss2": dev_candidate("d-miss2", alt=True),
}


def dev_counterexample(ce_id, candidate_id, claim):
    return {"id": ce_id, "version": "1", "candidate_id": candidate_id, "candidate_version": "1", "claim": claim,
            "conditions": ["Dev fixture condition."], "criterion_ids": ["Q1"],
            "citations": [{"document_id": "register.csv", "version": "1", "location": "row:R1"}]}


CLAIMS = {"x-rej-1": "The plan must shred every ledger after use.",
          "x-rej-2": "The leaflet must cover a real archive.",
          "x-val": "R1 inferred and R2 confirmed share one keeper column.",
          "x-open": "Cropping the ledger photos necessarily hides the handwriting."}

# (candidate, counterexample) for the thirteen development cases.
CASE_KEYS = [("d-good", None), ("d-alt", None), ("d-q1", None), ("d-q2", None), ("d-q3", None),
             ("d-good", "x-rej-1"), ("d-alt", "x-rej-2"), ("d-q1", "x-val"), ("d-good", "x-val"),
             ("d-good", "x-open"), ("d-alt", "x-open"), ("d-miss", None), ("d-miss2", None)]
CASE = {key: case_id_for(*key) for key in CASE_KEYS}


def dev_case(candidate_id, ce_id):
    source = {"originals": dev_originals("not supplied" if candidate_id.startswith("d-miss") else "tentative"),
              "criteria": deepcopy(DEV_CRITERIA), "candidate": deepcopy(CANDIDATES[candidate_id])}
    # no lens pack: it is critic configuration (DEV_LENS_PACK via PreDispatch), not dataset material
    authored = [] if ce_id is None else [{"counterexample": dev_counterexample(ce_id, candidate_id, CLAIMS[ce_id]),
                                          "source": LABEL}]
    return {"schema": "q01-frozen-case-1", "case_id": case_id_for(candidate_id, ce_id), "source": source,
            "authored_counterexamples": authored}


def write_environment(task_dir, cases):
    (task_dir / "environment" / "cases").mkdir(parents=True, exist_ok=True)
    for case in cases:
        (task_dir / "environment" / "cases" / f"{case['case_id']}.json").write_bytes(file_bytes(case))
    manifest = {"schema": "q01-environment-1", "materials": LABEL, "network": "none",
                "cases": [{"case_id": case["case_id"], "path": f"environment/cases/{case['case_id']}.json",
                           "sha256": digest(file_bytes(case))} for case in sorted(cases, key=lambda c: c["case_id"])]}
    (task_dir / "environment" / "manifest.json").write_bytes(file_bytes(manifest))
    return digest(file_bytes(manifest))


def make_task(root, mutate=None):
    task_dir = root / "v01-q01-dev"
    task_dir.mkdir(parents=True)
    shutil.copy(TASK_DIR / "instruction.md", task_dir / "instruction.md")
    cases = [dev_case(*key) for key in CASE_KEYS]
    if mutate:
        mutate(cases)
    return task_dir, write_environment(task_dir, cases)


# ---------------------------------------------------------------- synthetic development expectations


def ref(document, location, prefix=False):
    return {"document": document, "location": location, "prefix": prefix}


def rule(*groups):
    return {"groups": [list(group) for group in groups]}


PASS_ONLY, FAIL_ONLY, UNRESOLVED_ONLY = ["pass"], ["fail"], ["unresolved"]
NF, ANY = ["pass", "unresolved"], ["pass", "fail", "unresolved"]
Q7_ITEM = {"item_id": "q7_dev_no_run_claim", "selector": ["all_outputs"],
           "rubric": "Dev rubric: do the outputs avoid claiming that anything was run or approved?"}


def review(**overrides):
    base = {"Q1": PASS_ONLY, "Q2": PASS_ONLY, "Q3": PASS_ONLY, "Q4": PASS_ONLY, "Q5": NF, "Q6": NF, "Q7": NF,
            "Q8": NF}
    base.update(overrides)
    return base


def defect_review(criterion):
    return review(**{criterion: FAIL_ONLY, "Q4": ANY, "Q5": ANY, "Q6": ANY, "Q7": ANY, "Q8": ANY})


Q1_RULE = rule([ref("register.csv", "row:R1"), ref("notes.md", "R1")], [ref("@candidate", "/roles/", True)])


def expectation(key, boundary, basis, *, review_=None, review_evidence=None, validity=None, validity_evidence=None,
                response=None, response_evidence=None, judge=()):
    case = {"candidate_id": key[0], "counterexample_id": key[1], "boundary": boundary,
            "review": review_ or review(), "basis": f"[{LABEL}] {basis}",
            "judge": [*judge, Q7_ITEM]}
    if review_evidence:
        case["review_evidence"] = review_evidence
    if key[1] is not None:
        case.update(validity=validity, validity_evidence=validity_evidence, response=response,
                    response_evidence=response_evidence)
    return case


def item(item_id, selector):
    return {"item_id": item_id, "selector": selector,
            "rubric": f"Dev rubric for {item_id}: is the cited reasoning grounded in the dev fixture sources?"}


def dev_expectation_cases():
    return [
        expectation(("d-good", None), ACCEPT, "good plan keeps certainty, whole handoffs, gated release",
                    judge=[item("accept_supported", ["findings", "Q1", "Q2", "Q3", "Q4"])]),
        expectation(("d-alt", None), ACCEPT, "single-role arrangement still meets every duty",
                    judge=[item("alternative_supported", ["findings", "Q2", "Q4"])]),
        expectation(("d-q1", None), DEFECT, "keeper wording forced to settled while R1 is inferred",
                    review_=defect_review("Q1"), review_evidence={"Q1": Q1_RULE},
                    judge=[item("q1_defect_supported", ["finding", "Q1"])]),
        expectation(("d-q2", None), DEFECT, "digest-only summary breaks the whole-output handoff",
                    review_=defect_review("Q2"),
                    review_evidence={"Q2": rule([ref("brief.md", "handoff")], [ref("@candidate", "/handoffs/", True)])},
                    judge=[item("q2_defect_supported", ["finding", "Q2"])]),
        expectation(("d-q3", None), DEFECT, "auto-release skips the named approver",
                    review_=defect_review("Q3"),
                    review_evidence={"Q3": rule([ref("brief.md", "permissions")],
                                                [ref("@candidate", "/control/publication")])},
                    judge=[item("q3_defect_supported", ["finding", "Q3"])]),
        expectation(("d-good", "x-rej-1"), REJECTED, "no duty to shred ledgers exists",
                    validity="rejected", validity_evidence=rule([ref("brief.md", "permissions")]),
                    response=UNRESOLVED_ONLY, judge=[item("rejection_grounded", ["validity"])]),
        expectation(("d-alt", "x-rej-2"), REJECTED, "the archive is imaginary by the brief",
                    validity="rejected", validity_evidence=rule([ref("brief.md", "scope")]),
                    response=UNRESOLVED_ONLY, judge=[item("rejection_grounded", ["validity"])]),
        expectation(("d-q1", "x-val"), VALID, "mixed certainty column meets the forced wording",
                    review_=defect_review("Q1"), review_evidence={"Q1": Q1_RULE},
                    validity="valid", validity_evidence=rule([ref("register.csv", "row:R1")],
                                                             [ref("register.csv", "row:R2")]),
                    response=FAIL_ONLY, response_evidence=rule([ref("@candidate", "/roles/1/", True)]),
                    judge=[item("response_failure_supported", ["response"])]),
        expectation(("d-good", "x-val"), VALID, "good plan keeps certainty so the mix is handled",
                    validity="valid", validity_evidence=rule([ref("register.csv", "row:R1")]),
                    response=["avoid", "mitigate"], response_evidence=rule([ref("@candidate", "/roles/", True)]),
                    judge=[item("response_handling_supported", ["response"])]),
        expectation(("d-good", "x-open"), UNRESOLVED, "no photo bytes; the crop effect is unknown",
                    review_=review(Q1=NF, Q4=NF), validity="unresolved",
                    validity_evidence=rule([ref("notes.md", "R1")]), response=UNRESOLVED_ONLY,
                    judge=[item("unresolved_names_missing_evidence", ["validity"])]),
        expectation(("d-alt", "x-open"), UNRESOLVED, "no photo bytes for the single-role plan either",
                    review_=review(Q1=NF, Q4=NF), validity="unresolved",
                    validity_evidence=rule([ref("notes.md", "R1")]), response=UNRESOLVED_ONLY,
                    judge=[item("unresolved_names_missing_evidence", ["validity"])]),
        expectation(("d-miss", None), INSUFFICIENT, "R1 certainty is not supplied",
                    review_=review(Q1=UNRESOLVED_ONLY, Q4=NF),
                    review_evidence={"Q1": rule([ref("register.csv", "row:R1")])},
                    judge=[item("q1_unresolved_names_missing", ["finding", "Q1"])]),
        expectation(("d-miss2", None), INSUFFICIENT, "R1 certainty is not supplied (single role)",
                    review_=review(Q1=UNRESOLVED_ONLY, Q4=NF),
                    review_evidence={"Q1": rule([ref("register.csv", "row:R1")])},
                    judge=[item("q1_unresolved_names_missing", ["finding", "Q1"])]),
    ]


def expectation_bytes(cases=None, **top):
    document = {"schema": "q01-sealed-expectations-1", "design_id": "q01-release-v4",
                "dataset_id": "dev-synthetic-test-actor", "cases": dev_expectation_cases() if cases is None else cases}
    document.update(top)
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")


def load_dev_expectations(data=None, **kwargs):
    data = expectation_bytes() if data is None else data
    return load_sealed_expectations(data, hashlib.sha256(data).hexdigest(), **kwargs)


# ---------------------------------------------------------------- scripted critic and judge


def cite(visible, document_id, location):
    if document_id == "@candidate":
        return {"document_id": visible["candidate"]["id"], "version": "1", "location": location}
    version = visible["criteria"]["version"] if document_id == "fixed-criteria" else "1"
    return {"document_id": document_id, "version": version, "location": location}


REVIEW = {"d-q1": {"Q1": ("fail", [("register.csv", "row:R1"), ("@candidate", "/roles/1/responsibility")])},
          "d-q2": {"Q2": ("fail", [("brief.md", "handoff"), ("@candidate", "/handoffs/0/mode")])},
          "d-q3": {"Q3": ("fail", [("brief.md", "permissions"), ("@candidate", "/control/publication")])},
          "d-miss": {"Q1": ("unresolved", [("register.csv", "row:R1"), ("notes.md", "R1")])},
          "d-miss2": {"Q1": ("unresolved", [("register.csv", "row:R1"), ("notes.md", "R1")])}}
VALIDITY = {"x-rej-1": ("rejected", [("brief.md", "permissions")]), "x-rej-2": ("rejected", [("brief.md", "scope")]),
            "x-val": ("valid", [("register.csv", "row:R1"), ("register.csv", "row:R2")]),
            "x-open": ("unresolved", [("notes.md", "R1")])}


class DevCritic:
    """Scripted ``(system, user) -> str`` fixture over the dev materials; ``overrides`` per purpose."""

    def __init__(self, **overrides):
        self.calls, self.overrides = [], overrides

    def __call__(self, system, user):
        self.calls.append((system, user))
        payload = json.loads(user)
        purpose, visible = payload["purpose"], payload["input"]
        answer = getattr(self, "_" + purpose)(visible)
        if purpose in self.overrides:
            answer = self.overrides[purpose](visible, deepcopy(answer))
        return answer if isinstance(answer, str) else json.dumps(answer)

    @staticmethod
    def _head(purpose, visible):
        return {"purpose": purpose, "candidate_id": visible["candidate"]["id"], "candidate_version": "1"}

    def _review(self, visible):
        table = REVIEW.get(visible["candidate"]["id"], {})
        findings = []
        for criterion in (item["id"] for item in visible["criteria"]["items"]):
            status, refs = table.get(criterion, ("pass", [("brief.md", "scope")]))
            findings.append({"criterion_id": criterion, "status": status,
                             "evidence": [cite(visible, *r) for r in refs], "reason": "Dev scripted reason.",
                             "uncertainties": ["Needed data is absent."] if status == "unresolved" else []})
        return {**self._head("review", visible), "findings": findings}

    def _counterexample_proposal(self, visible):
        return {**self._head("counterexample_proposal", visible), "status": "abstain", "counterexamples": [],
                "uncertainties": ["Dev scripted abstention."], "lens_use": []}

    def _counterexample_validity(self, visible):
        example = visible["counterexample"]
        status, refs = VALIDITY[example["id"]]
        return {**self._head("counterexample_validity", visible), "counterexample_id": example["id"],
                "counterexample_version": "1", "status": status, "evidence": [cite(visible, *r) for r in refs],
                "reason": "Dev scripted validity.",
                "uncertainties": ["Photo bytes are absent."] if status == "unresolved" else []}

    def _candidate_response(self, visible):
        validity = visible["validity"]["status"]
        status, refs = "unresolved", [("notes.md", "R1")]
        if validity == "valid":
            status, refs = (("fail", [("@candidate", "/roles/1/responsibility")])
                            if visible["candidate"]["id"] == "d-q1" else ("avoid", [("@candidate", "/roles/0/checks/0")]))
        return {**self._head("candidate_response", visible), "counterexample_id": visible["counterexample"]["id"],
                "counterexample_version": "1", "validity_status": validity, "status": status,
                "evidence": [cite(visible, *r) for r in refs], "reason": "Dev scripted response.",
                "uncertainties": ["Validity is not settled."] if status == "unresolved" else []}


def set_finding(criterion, status, refs=None):
    def override(visible, answer):
        for finding in answer["findings"]:
            if finding["criterion_id"] == criterion:
                finding["status"] = status
                if refs is not None:
                    finding["evidence"] = [cite(visible, *r) for r in refs]
                finding["uncertainties"] = ["Unknown."] if status == "unresolved" else []
        return answer
    return override


def set_field(name, value, **extra):
    def override(_visible, answer):
        answer[name] = value
        answer.update(extra)
        return answer
    return override


class DevJudge:
    """Deterministic offline judge for the dev fixtures only."""

    version = "dev-fixture-judge-1"
    prompt_digest = None

    def __init__(self, default="supported", identity=None, **by_prefix):
        self.default, self.by_prefix, self.items = default, by_prefix, []
        self.identity = JUDGE_IDENTITY if identity is None else identity

    def judge(self, item_):
        self.items.append(item_)
        for prefix, status in self.by_prefix.items():
            if item_.item_id.startswith(prefix):
                if isinstance(status, Exception):
                    raise status
                return status
        return self.default




# ---------------------------------------------------------------- manifest, profile and fixtures


def dev_configuration(rig, task_dir, **overrides):
    """The dev critic configuration the rig actually runs (checked field by field at dispatch)."""
    configuration = {"provider": rig.choice["provider"], "mode": rig.choice["mode"], "model": rig.choice["model"],
                     "effort": rig.choice["effort"], "max_tokens": 1000,
                     "critic_prompt_digest": critic_prompt_digest(task_dir), "contract_version": CONTRACT_VERSION,
                     "parser_version": PARSER_VERSION, "max_proposed_chains": 16,
                     "call_and_run_deadlines": {"call_seconds": rig.config.call_seconds,
                                                "run_seconds": rig.config.run_seconds},
                     "lens_refs_and_digests": lens_refs_and_digests(DEV_LENS_PACK)}
    configuration.update(overrides)
    return configuration


def attestation(name):
    return {"name": name, "statement": f"{LABEL}: no independent authoring, review or sealing",
            "attested_on": "2026-09-25"}


def dev_profile(established=True, **changes):
    """A TEST-ACTOR successor profile naming release-v4 (never a real judge arrangement)."""
    profile = json.loads((V4 / "independence_profile.json").read_text(encoding="utf-8"))
    profile["profile_id"] = "test-actor-dev-profile"
    profile["judge_separation"]["established"] = established
    profile["judge_separation"]["judge"] = ({"identity": JUDGE_IDENTITY, "prompt_digest": None,
                                             "option": "other_provider"} if established else None)
    profile.update(changes)
    return json.dumps(profile, ensure_ascii=False, indent=1).encode("utf-8")


def dev_manifest(expectations, materials_sha, *, rig, task_dir, attempt=1, prior=(), configuration=None,
                 digest_=None, order=None, profile_bytes=None, lens_effect=None):
    configuration = configuration or dev_configuration(rig, task_dir)
    profile_bytes = dev_profile() if profile_bytes is None else profile_bytes
    return {
        "schema": "q01-pre-dispatch-manifest-2", "design_id": "q01-release-v4",
        "critic_configuration": configuration,
        "critic_configuration_digest": digest_ or critic_configuration_digest(configuration),
        "run_identity": {
            "sealed_dataset_sha256": materials_sha, "sealed_expectations_sha256": expectations.sha256,
            "judge_identity": JUDGE_IDENTITY, "judge_prompt_digest": None,
            "independence_profile": {"path": "dev/profile.json",
                                     "sha256": hashlib.sha256(profile_bytes).hexdigest()},
            "harness": harness_identity(), "verifier": verifier_identity(),
            "case_order": {"seed": "dev", "order": sorted(expectations.cases) if order is None else order},
            "authority_ref": "test actor: development only, no authority", "usd_hard_stop": 0.01},
        "attempt": attempt,
        "prior_attempts": [{"attempt": index + 1, "design_id": "q01-release-v4", "sealed_dataset_sha256": "4" * 64,
                            "suite_outcome": outcome} for index, outcome in enumerate(prior)],
        "attestations": {"author": attestation("test actor as author"),
                         "reviewer": attestation("test actor as reviewer"),
                         "sealing": attestation("test actor as sealer")},
        "lens_effect": lens_effect,
    }


def as_bytes(manifest):
    return json.dumps(manifest, indent=1).encode("utf-8")


def release_setup(world, directory, *, manifest=None, manifest_sha=None, task_dir=None, profile_bytes=None,
                  committed=None, lens_pack=None, harness=None, **manifest_options):
    """(PreDispatch, loaded ReleaseRun) for one dev manifest written under ``directory``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    profile_bytes = dev_profile() if profile_bytes is None else profile_bytes
    if manifest is None:
        manifest = dev_manifest(world["expectations"], manifest_sha or world["manifest_sha"], rig=world["rig"],
                                task_dir=task_dir or world["task_dir"], profile_bytes=profile_bytes,
                                **manifest_options)
    data = as_bytes(manifest)
    path = directory / "pre-dispatch.json"
    path.write_bytes(data)
    committed = committed or hashlib.sha256(data).hexdigest()
    pre_dispatch = PreDispatch(path, committed, harness_identity() if harness is None else harness,
                               deepcopy(DEV_LENS_PACK) if lens_pack is None else lens_pack)
    return pre_dispatch, load_release_run(data, committed_sha256=committed, profile_bytes=profile_bytes)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("sealed-dev")
    task_dir, manifest_sha = make_task(root)
    rig = make_rig(root)
    state = {"root": root, "task_dir": task_dir, "rig": rig, "expectations": load_dev_expectations(),
             "materials": load_sealed_materials_dir(task_dir, manifest_sha), "manifest_sha": manifest_sha}
    state["pre_dispatch"], state["run"] = release_setup(state, root / "run")
    assert state["run"].errors == () and state["run"].judge_separation_established is True
    return state


def run(world, key, critic=None, task_dir=None, pre_dispatch=None):
    rig = world["rig"]
    return run_release_trial(CASE[key], critic or DevCritic(), base_dir=rig.base, config=rig.config,
                             pre_dispatch=pre_dispatch or world["pre_dispatch"],
                             task_dir=task_dir or world["task_dir"])


def verify(world, record, judge=None, **kwargs):
    kwargs.setdefault("run", world["run"])
    return verify_trial(record, expectations=world["expectations"], materials=world["materials"], judge=judge,
                        **kwargs)


def fails(result, check_id=None, cause="rule_check"):
    assert (result["verdict"], result["cause"], result["score"]) == (FAIL, cause, 0.0), result
    assert result["agent_capability_scored"] is True
    if check_id:
        assert any(c["id"] == check_id and not c["ok"] for c in result["rule_checks"]), result["rule_checks"]


def invalid(result, cause):
    assert (result["verdict"], result["cause"], result["score"]) == (INVALID, cause, None), result
    assert result["agent_capability_scored"] is False


# ---------------------------------------------------------------- loading and refusal


def test_dev_expectations_load_into_the_shared_structures():
    from evals.deeptwin.verifiers.q01_core import EvidenceRule, Expectation, Ref

    expectations = load_dev_expectations()
    assert len(expectations.cases) == 13 and expectations.dataset_id == "dev-synthetic-test-actor"
    assert {c.expectation.boundary for c in expectations.cases.values()} == set(sc.BOUNDARY_CLASSES)
    defect = expectations.cases[CASE[("d-q1", None)]].expectation
    assert type(defect) is Expectation and type(defect.review_evidence["Q1"]) is EvidenceRule
    assert defect.review_evidence["Q1"].groups[1] == (Ref("@candidate", "/roles/", True),)
    assert defect.review["Q1"] == frozenset({"fail"})
    assert ("q7_dev_no_run_claim", Q7_ITEM["rubric"], ("all_outputs",)) in defect.judge
    assert sc.composition_problems(expectations) == []


def test_expectations_refuse_a_sha256_mismatch_before_parsing():
    data = expectation_bytes()
    with pytest.raises(SealedSetError, match="sha256"):
        load_sealed_expectations(data, hashlib.sha256(data + b" ").hexdigest())
    with pytest.raises(SealedSetError, match="expected sha256"):
        load_sealed_expectations(data, None)
    with pytest.raises(SealedSetError, match="sha256"):  # not parsed: garbage with a wrong pin
        load_sealed_expectations(b"{not json", "0" * 64)


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d.pop("dataset_id"), "schema"),
    (lambda d: d.update(schema="other"), "schema"),
    (lambda d: d["cases"][0].pop("basis"), "schema"),
    (lambda d: d["cases"][0]["review"].update(Q1=["maybe"]), "schema"),
    (lambda d: d["cases"][0].update(extra=1), "schema"),
    (lambda d: d.update(cases=d["cases"][:11]), "schema"),  # fewer than 12 cases
    (lambda d: d["cases"][2].update(review=review()), "required defect"),
    (lambda d: d["cases"][0]["review"].update(Q3=ANY), "accepted candidate"),
    (lambda d: d["cases"][5].update(validity="valid"), "rejected counterexample"),
    (lambda d: d["cases"][8].update(response=["fail", "avoid"]), "valid counterexample"),
    (lambda d: d["cases"][9].update(response=["fail"]), "unresolved specific claim"),
    (lambda d: d["cases"][11].update(review=review()), "insufficient evidence"),
    (lambda d: d["cases"][0].update(counterexample_id="x-rej-1"), "together"),
    (lambda d: d["cases"][0]["judge"].append(item("q7_dev_no_run_claim", ["all_outputs"])), "duplicate"),
    (lambda d: d["cases"][0]["judge"].append(item("bad", ["validity"])), "counterexample"),
    (lambda d: d["cases"][0]["judge"].append(item("bad2", ["finding", "Q1", "Q2"])), "exactly one"),
    (lambda d: d["cases"].append(deepcopy(d["cases"][0])), "duplicate case"),
    (lambda d: d["cases"].pop(12), "composition"),
    (lambda d: d["cases"][4].update(boundary=ACCEPT, review=review(), review_evidence={}), "composition"),
])
def test_expectations_refuse_schema_and_boundary_violations(mutate, match):
    document = json.loads(expectation_bytes())
    mutate(document)
    data = json.dumps(document).encode("utf-8")
    with pytest.raises(SealedSetError, match=match):
        load_sealed_expectations(data, hashlib.sha256(data).hexdigest())


def test_expectations_refuse_duplicate_json_keys_and_allow_composition_opt_out():
    data = expectation_bytes()
    doubled = data.replace(b'"dataset_id"', b'"dataset_id": "x", "dataset_id"', 1)
    with pytest.raises(SealedSetError, match="strict"):
        load_sealed_expectations(doubled, hashlib.sha256(doubled).hexdigest())
    document = json.loads(data)
    document["cases"].pop(12)
    short = json.dumps(document).encode("utf-8")
    assert len(load_dev_expectations(short, require_composition=False).cases) == 12


def test_materials_bundle_is_verified_against_its_manifest(world):
    task_dir, sha = world["task_dir"], world["manifest_sha"]
    files = {p.relative_to(task_dir).as_posix(): p.read_bytes()
             for p in (task_dir / "environment").rglob("*") if p.is_file()}
    assert set(load_sealed_materials(files, sha).cases) == set(CASE.values())
    with pytest.raises(SealedSetError, match="manifest sha256"):
        load_sealed_materials(files, "0" * 64)
    with pytest.raises(SealedSetError, match="unlisted"):
        load_sealed_materials({**files, "environment/cases/extra.json": b"{}"}, sha)
    case_path = next(name for name in files if name.startswith("environment/cases/"))
    with pytest.raises(SealedSetError, match="altered"):
        load_sealed_materials({**files, case_path: files[case_path] + b" "}, sha)
    with pytest.raises(SealedSetError, match="altered"):
        load_sealed_materials({k: v for k, v in files.items() if k != case_path}, sha)
    with pytest.raises(SealedSetError, match="no environment manifest"):
        load_sealed_materials({case_path: files[case_path]}, sha)


def test_binding_refuses_mismatched_or_leaking_sets(world, tmp_path):
    expectations = world["expectations"]
    document = json.loads(expectation_bytes())
    document["cases"][2]["review_evidence"]["Q1"] = rule([ref("register.csv", "row:R9")])
    data = json.dumps(document).encode("utf-8")
    with pytest.raises(SealedSetError, match="cites nothing visible"):
        sc.check_binding(load_dev_expectations(data), world["materials"])
    _task, sha = make_task(tmp_path / "leak", lambda cases: cases[0]["source"]["candidate"]["control"]["notes"]
                           .append("Dev leak: " + DEFECT))
    with pytest.raises(SealedSetError, match="answer content"):
        sc.check_binding(expectations, load_sealed_materials_dir(_task, sha))
    _task, sha = make_task(tmp_path / "short", lambda cases: cases.pop())
    with pytest.raises(SealedSetError, match="differ"):
        sc.check_binding(expectations, load_sealed_materials_dir(_task, sha))
    sc.check_binding(expectations, world["materials"])


# ---------------------------------------------------------------- trial verdicts


@pytest.mark.parametrize("key", CASE_KEYS, ids=[f"{a}-{b}" for a, b in CASE_KEYS])
def test_every_dev_boundary_case_passes_only_with_a_judge(world, key):
    record = run(world, key)
    assert record["status"] == "completed"
    unjudged = verify(world, record, repetition=1)
    assert unjudged["verdict"] == NOT_JUDGED and unjudged["score"] is None
    assert all(c["ok"] for c in unjudged["rule_checks"]), unjudged["rule_checks"]
    judge = DevJudge()
    judged = verify(world, record, judge, repetition=1)
    expected = world["expectations"].cases[CASE[key]].expectation.boundary
    assert (judged["verdict"], judged["boundary"], judged["case_id"]) == (PASS, expected, CASE[key])
    assert judged["expectations_sha256"] == world["expectations"].sha256
    assert judged["materials_manifest_sha256"] == world["manifest_sha"]
    assert {i["origin"] for i in judged["judge_items"]} == {"sealed"}
    for judge_item in judge.items:  # judge inputs carry outputs and cited sources, never the answer
        assert expected not in judge_item.subject_json + judge_item.sources_json


def test_accept_boundary_fails_on_false_rejection(world):
    critic = DevCritic(review=set_finding("Q2", "fail", [("brief.md", "handoff"), ("@candidate", "/handoffs/0/mode")]))
    fails(verify(world, run(world, ("d-good", None), critic)), "review:Q2:status")
    critic = DevCritic(review=set_finding("Q4", "fail", [("brief.md", "scope")]))
    fails(verify(world, run(world, ("d-alt", None), critic)), "review:Q4:status")


def test_defect_boundary_fails_when_missed_or_without_its_source(world):
    fails(verify(world, run(world, ("d-q1", None), DevCritic(review=set_finding("Q1", "pass")))), "review:Q1:status")
    no_source = DevCritic(review=set_finding("Q1", "fail", [("@candidate", "/roles/1/responsibility")]))
    fails(verify(world, run(world, ("d-q1", None), no_source)), "review:Q1:evidence")
    no_rule = DevCritic(review=set_finding("Q3", "fail", [("brief.md", "permissions")]))
    fails(verify(world, run(world, ("d-q3", None), no_rule)), "review:Q3:evidence")
    fails(verify(world, run(world, ("d-q2", None), DevCritic(review=set_finding("Q2", "unresolved")))),
          "review:Q2:status")


def test_rejected_boundary_fails_when_accepted_or_blamed(world):
    accepted = DevCritic(counterexample_validity=set_field("status", "valid"))
    fails(verify(world, run(world, ("d-good", "x-rej-1"), accepted)), "validity:status")
    blamed = DevCritic(review=set_finding("Q1", "fail", [("register.csv", "row:R1")]))
    fails(verify(world, run(world, ("d-alt", "x-rej-2"), blamed)), "review:Q1:status")


def test_valid_boundary_distinguishes_failure_from_handling(world):
    fails(verify(world, run(world, ("d-good", "x-val"), DevCritic(candidate_response=set_field("status", "fail")))),
          "response:status")
    fails(verify(world, run(world, ("d-q1", "x-val"), DevCritic(candidate_response=set_field("status", "mitigate")))),
          "response:status")
    rejected = DevCritic(counterexample_validity=set_field("status", "rejected"))
    fails(verify(world, run(world, ("d-q1", "x-val"), rejected)), "validity:status")


@pytest.mark.parametrize("status", ["valid", "rejected"])
def test_unresolved_claim_boundary_fails_when_decided(world, status):
    critic = DevCritic(counterexample_validity=set_field("status", status, uncertainties=[]))
    fails(verify(world, run(world, ("d-good", "x-open"), critic)), "validity:status")


@pytest.mark.parametrize("status", ["pass", "fail"])
def test_insufficient_boundary_fails_when_decided(world, status):
    critic = DevCritic(review=set_finding("Q1", status, [("register.csv", "row:R1")]))
    fails(verify(world, run(world, ("d-miss", None), critic)), "review:Q1:status")


def test_output_contract_errors_are_fails_not_invalid(world):
    record = run(world, ("d-miss2", None), DevCritic(review=lambda _v, _a: "{}"))
    assert record["status"] == "completed" and record["output_contract"] == "model_output_invalid"
    fails(verify(world, record, DevJudge()), cause="output_contract")
    # a rejected counterexample answered with a fail response breaks the contract transition
    record = run(world, ("d-good", "x-rej-1"), DevCritic(candidate_response=set_field("status", "fail",
                                                                                         uncertainties=[])))
    result = verify(world, record, DevJudge())
    fails(result, cause="output_contract")
    assert result["case_key"] == {"candidate_id": "d-good", "counterexample_id": "x-rej-1"}


@pytest.mark.parametrize("status,verdict,cause", [
    ("undetermined", NOT_JUDGED, "semantic_items_not_judged"),
    ("not_supported", FAIL, "semantic_judgement"),
    ("maybe", INVALID, "judge_fault"),
    (RuntimeError("judge down"), INVALID, "judge_fault"),
])
def test_judge_outcomes(world, status, verdict, cause):
    record = run(world, ("d-q2", None))
    result = verify(world, record, DevJudge(q2_defect=status))
    assert (result["verdict"], result["cause"]) == (verdict, cause)
    assert result["score"] == (0.0 if verdict == FAIL else None)


def test_invalid_trials_are_attributed_and_unscored(world):
    def down(_system, _user):
        raise RuntimeError("down")
    result = verify(world, run(world, ("d-alt", None), down), DevJudge(), repetition=2)
    invalid(result, "trial_transport_or_fixture_error")
    assert (result["case_id"], result["repetition"], result["boundary"]) == (CASE[("d-alt", None)], 2, ACCEPT)
    record = run(world, ("d-q3", None))
    copy = deepcopy(record)
    copy["calls"][0]["ledger"]["details"]["parsed"]["findings"][0]["status"] = "fail"
    invalid(verify(world, copy, DevJudge()), "evidence_tampered")
    copy = deepcopy(record)
    copy["access_log"].append({"path": "Task.md", "outcome": "read"})
    invalid(verify(world, copy, DevJudge()), "forbidden_access")
    invalid(verify(world, {**record, "schema": "other"}), "record_schema")
    other = verify_trial(record, expectations=world["expectations"], materials="not a bundle", run=world["run"],
                         judge=DevJudge())
    invalid(other, "sealed_set_mismatch")


def test_material_mismatch_and_answer_leak_are_derived_from_the_sealed_set(world, tmp_path):
    def alter(cases):
        cases[[c["case_id"] for c in cases].index(CASE[("d-good", None)])]["source"]["candidate"]["control"][
            "publication"] = "released on request"
    # a manifest pinning the altered environment lets the harness dispatch; the verifier
    # still compares every visible input with the sealed bundle
    altered, sha = make_task(tmp_path / "altered", alter)
    pre_dispatch, other_run = release_setup(world, tmp_path / "altered", manifest_sha=sha, task_dir=altered)
    record = run(world, ("d-good", None), task_dir=altered, pre_dispatch=pre_dispatch)
    assert record["status"] == "completed"
    invalid(verify(world, record, DevJudge(), run=other_run), "material_mismatch")
    # the same record against the world's manifest is not a trial of that manifest
    invalid(verify(world, record, DevJudge()), "not_a_release_trial_of_this_manifest")

    basis = world["expectations"].cases[CASE[("d-q3", None)]].expectation.basis

    def leak(cases):
        cases[[c["case_id"] for c in cases].index(CASE[("d-good", None)])]["source"]["candidate"]["control"][
            "notes"].append(basis)
    leaked, sha = make_task(tmp_path / "leaked", leak)
    pre_dispatch, other_run = release_setup(world, tmp_path / "leaked", manifest_sha=sha, task_dir=leaked)
    record = run(world, ("d-good", None), task_dir=leaked, pre_dispatch=pre_dispatch)
    assert record["status"] == "completed"  # the harness scan does not know sealed answers
    invalid(verify(world, record, DevJudge(), run=other_run), "answer_leak")


def test_leak_markers_come_from_the_sealed_set_not_calibration_sources(world):
    markers = sc.answer_markers(world["expectations"], world["materials"], {"x": "instruction"})
    assert set(sc.BOUNDARY_CLASSES) <= set(markers) and set(CASE.values()) <= set(markers)
    assert any(LABEL in marker for marker in markers)
    calibration = (ROOT / "evals/deeptwin/tasks/v01-q01/Task.md").read_text(encoding="utf-8")
    assert not any(marker in calibration for marker in markers if marker not in sc.BOUNDARY_CLASSES)




# ---------------------------------------------------------------- full dev runs (3 repetitions, real trials)


def _full(world, directory, profile_bytes):
    """Every dev case x 3 repetitions as real release trials, plus one fail, invalid and
    not_judged variant, all under one manifest."""
    pre_dispatch, loaded = release_setup(world, directory, profile_bytes=profile_bytes)

    def check(key, rep, critic=None, judge="dev"):
        record = run(world, key, critic, pre_dispatch=pre_dispatch)
        return verify(world, record, DevJudge() if judge == "dev" else judge, repetition=rep, run=loaded)

    def down(_system, _user):
        raise RuntimeError("down")

    passes = {(key, rep): check(key, rep) for key in CASE_KEYS for rep in (1, 2, 3)}
    variants = {
        FAIL: check(CASE_KEYS[0], 1, DevCritic(review=set_finding(
            "Q2", "fail", [("brief.md", "handoff"), ("@candidate", "/handoffs/0/mode")]))),
        INVALID: check(CASE_KEYS[1], 1, down),
        NOT_JUDGED: check(CASE_KEYS[2], 1, judge=None),
    }
    return {"run": loaded, "pre_dispatch": pre_dispatch, "passes": passes, "variants": variants}


@pytest.fixture(scope="module")
def full(world):
    data = _full(world, world["root"] / "full", dev_profile())
    assert all(result["verdict"] == PASS for result in data["passes"].values())
    assert [data["variants"][v]["verdict"] for v in (FAIL, INVALID, NOT_JUDGED)] == [FAIL, INVALID, NOT_JUDGED]
    return data


@pytest.fixture(scope="module")
def unseparated(world):
    """The same dev run under a profile without established judge separation."""
    return _full(world, world["root"] / "unseparated", dev_profile(established=False))


def passes(full_run):
    return [full_run["passes"][(key, rep)] for key in CASE_KEYS for rep in (1, 2, 3)]


# ---------------------------------------------------------------- suite precedence


def oracle(fail, invalid_, missing, not_judged, mismatch, stopped, separated):
    """release-v4 acceptance.suite_outcome, transcribed from the frozen design text."""
    if fail:
        return "fail"
    if invalid_ or missing or stopped or mismatch:
        return "incomplete"
    if not_judged or not separated:
        return "not_judged"
    return "pass"


FLAGS = ("fail", "invalid_", "missing", "not_judged", "mismatch", "stopped", "separated")


@pytest.mark.parametrize("flags", list(itertools.product([False, True], repeat=len(FLAGS))),
                         ids=lambda f: "".join("1" if x else "0" for x in f))
def test_suite_precedence_table(world, full, unseparated, flags):
    state = dict(zip(FLAGS, flags))
    source = full if state["separated"] else unseparated
    results = {slot: result for slot, result in source["passes"].items()}
    for flag, verdict, key in (("fail", FAIL, CASE_KEYS[0]), ("invalid_", INVALID, CASE_KEYS[1]),
                               ("not_judged", NOT_JUDGED, CASE_KEYS[2])):
        if state[flag]:
            results[(key, 1)] = source["variants"][verdict]
    if state["missing"]:
        del results[(CASE_KEYS[5], 3)]
    loaded = source["run"]
    if state["mismatch"]:  # the same bytes against another committed value
        manifest_bytes = source["pre_dispatch"].manifest_path.read_bytes()
        loaded = load_release_run(manifest_bytes, committed_sha256="0" * 64,
                                  profile_bytes=dev_profile(established=state["separated"]))
    suite = verify_suite(list(results.values()), expectations=world["expectations"], run=loaded,
                         stopped=state["stopped"])
    assert suite["suite_outcome"] == oracle(**state), suite["reasons"]
    all_pass = not any(state[name] for name in ("fail", "invalid_", "missing", "not_judged"))
    assert all(case["case_pass"] for case in suite["cases"].values()) is all_pass


def test_case_pass_needs_every_repetition_valid_and_passing(world, full):
    base = passes(full)
    options = {"expectations": world["expectations"], "run": full["run"]}
    assert verify_suite(base, **options)["suite_outcome"] == "pass"
    ids = [CASE[key] for key in CASE_KEYS]
    suite = verify_suite(base[:-1], **options)
    assert suite["suite_outcome"] == "incomplete" and "missing_repetition" in suite["reasons"]
    assert suite["cases"][ids[-1]]["case_pass"] is False
    assert sum(case["case_pass"] for case in suite["cases"].values()) == len(ids) - 1
    # a replacement for a slot is never absorbed
    extra = verify(world, run(world, CASE_KEYS[0], pre_dispatch=full["pre_dispatch"]), DevJudge(), repetition=1,
                   run=full["run"])
    suite = verify_suite([*base, extra], **options)
    assert suite["suite_outcome"] == "incomplete" and "duplicate_repetition" in suite["reasons"]
    fourth = verify(world, run(world, CASE_KEYS[0], pre_dispatch=full["pre_dispatch"]), DevJudge(), repetition=4,
                    run=full["run"])
    assert "unplanned_repetition" in verify_suite([*base, fourth], **options)["reasons"]
    # a fail keeps precedence over every incomplete cause
    failing = [full["variants"][FAIL], *base[1:-1]]
    assert verify_suite(failing, **options, stopped=True)["suite_outcome"] == "fail"


# ---------------------------------------------------------------- BF2 probes: degenerate or cherry-picked runs


def test_bf2_repetitions_are_fixed_at_three_not_caller_supplied(world, full):
    base = passes(full)
    with pytest.raises(TypeError):
        verify_suite(base, expectations=world["expectations"], run=full["run"], planned_repetitions=1)
    one_each = [full["passes"][(key, 1)] for key in CASE_KEYS]
    suite = verify_suite(one_each, expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == INCOMPLETE and "missing_repetition" in suite["reasons"]
    assert suite["repetitions_per_case"] == 3 == sc.REPETITIONS_PER_CASE


def test_bf2_one_trial_reused_for_three_repetitions_is_refused(world, full):
    record = run(world, CASE_KEYS[3], pre_dispatch=full["pre_dispatch"])
    reused = [verify(world, record, DevJudge(), repetition=rep, run=full["run"]) for rep in (1, 2, 3)]
    assert len({result["trial_id"] for result in reused}) == 1
    assert all(result["verdict"] == PASS and result["ledger_head"] and result["trial_record_sha256"]
               for result in reused)
    results = [result for (key, _rep), result in full["passes"].items() if key != CASE_KEYS[3]] + reused
    suite = verify_suite(results, expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == INCOMPLETE and "trial_reused" in suite["reasons"]
    # a copy of the record under a fresh trial id does not match its own ledger
    copy = deepcopy(record)
    copy["trial_id"] = copy["run_id"] = "t" + "0" * 32
    invalid(verify(world, copy, DevJudge(), repetition=2), "evidence_incomplete")


def test_bf2_hand_built_or_altered_results_are_refused(world, full):
    base = passes(full)
    options = {"expectations": world["expectations"], "run": full["run"]}
    forged = {key: value for key, value in base[0].items()}
    forged["trial_id"] = "t" + "1" * 32
    forged.pop("result_sha256")
    forged["result_sha256"] = hashlib.sha256(json.dumps(forged, sort_keys=True, separators=(",", ":"))
                                             .encode("utf-8")).hexdigest()
    for bad in (forged, {**base[0], "verdict": PASS, "repetition": 2}, {**base[-1], "cause": "edited"},
                {"schema": RESULT_SCHEMA, "verifier_version": VERIFIER_VERSION}):
        suite = verify_suite([*base[1:], bad] if bad is not forged else [*base[:-1], bad], **options)
        assert suite["suite_outcome"] == INCOMPLETE
        assert "result_not_issued_by_verify_trial" in suite["reasons"]
    # a result issued under another manifest (another configuration) is unattributable here
    other_pre, other_run = release_setup(world, world["root"] / "other-config",
                                         configuration=dev_configuration(world["rig"], world["task_dir"],
                                                                         max_tokens=2000))
    other = verify(world, run(world, CASE_KEYS[-1], pre_dispatch=other_pre), DevJudge(), repetition=3,
                   run=other_run)
    assert other["verdict"] == PASS
    suite = verify_suite([*base[:-1], other], **options)
    assert "unattributable_result" in suite["reasons"] and suite["suite_outcome"] == INCOMPLETE


def test_bf2_a_manifest_for_another_set_never_passes(world, full):
    base = passes(full)
    for change, reason in [
            (lambda m: m["run_identity"].update(sealed_expectations_sha256="7" * 64),
             "manifest:sealed_expectations_sha256_mismatch"),
            (lambda m: m["run_identity"].update(sealed_dataset_sha256="7" * 64),
             "manifest:sealed_dataset_sha256_mismatch"),
            (lambda m: m["run_identity"]["case_order"].update(order=sorted(CASE.values())[1:]),
             "manifest:case_order_does_not_list_every_case_once")]:
        manifest = dev_manifest(world["expectations"], world["manifest_sha"], rig=world["rig"],
                                task_dir=world["task_dir"])
        change(manifest)
        data = as_bytes(manifest)
        wrong = load_release_run(data, committed_sha256=hashlib.sha256(data).hexdigest(), profile_bytes=dev_profile())
        suite = verify_suite(base, expectations=world["expectations"], run=wrong)
        assert suite["suite_outcome"] == INCOMPLETE and reason in suite["reasons"], suite["reasons"]
        with pytest.raises(ValueError, match="not the manifest"):
            build_suite_record(verify_suite(base, expectations=world["expectations"], run=full["run"]), run=wrong)
    # the manifest recheck is not optional: there is no hash-values-only path
    with pytest.raises(TypeError):
        verify_suite(base, expectations=world["expectations"], pre_dispatch_manifest_sha256="a" * 64,
                     committed_manifest_sha256="a" * 64)
    with pytest.raises(SealedSetError, match="release run"):
        verify_suite(base, expectations=world["expectations"], run=None)


def test_bf2_expectations_loaded_without_composition_never_pass(world, full):
    unchecked = load_dev_expectations(require_composition=False)
    assert unchecked.composition_checked is False and world["expectations"].composition_checked is True
    assert unchecked.sha256 == world["expectations"].sha256
    suite = verify_suite(passes(full), expectations=unchecked, run=full["run"])
    assert suite["suite_outcome"] == INCOMPLETE and "composition_not_checked" in suite["reasons"]
    assert build_suite_record(suite, run=full["run"])["suite_outcome"] == INCOMPLETE


def test_bf2_judge_separation_comes_only_from_the_pinned_profile(world, full, tmp_path):
    base = passes(full)
    with pytest.raises(TypeError):  # the caller's judge flag is gone
        verify_suite(base, expectations=world["expectations"], run=full["run"], judge_separation_established=True)
    manifest_bytes = full["pre_dispatch"].manifest_path.read_bytes()
    committed = full["pre_dispatch"].committed_sha256
    for profile, error in [
            (dev_profile(established=False), "profile:sha256_differs_from_manifest"),
            (b"{}", "profile:sha256_differs_from_manifest"),
            (None, "profile:sha256_differs_from_manifest")]:
        loaded = load_release_run(manifest_bytes, committed_sha256=committed, profile_bytes=profile)
        assert error in loaded.errors and loaded.judge_separation_established is False
        assert verify_suite(base, expectations=world["expectations"], run=loaded)["suite_outcome"] == INCOMPLETE
    # a profile that is pinned but does not name this design, or names another judge
    for profile, error in [(dev_profile(design_id="q01-release-v3"), "profile:does_not_name_this_design"),
                           (dev_profile(schema="q01-independence-profile-3"), "profile:schema")]:
        _pre, loaded = release_setup(world, tmp_path / error.replace(":", "-"), profile_bytes=profile)
        assert error in loaded.errors and loaded.judge_separation_established is False
    other_judge = json.loads(dev_profile())
    other_judge["judge_separation"]["judge"]["identity"] = "someone else"
    _pre, loaded = release_setup(world, tmp_path / "other-judge",
                                 profile_bytes=json.dumps(other_judge).encode("utf-8"))
    assert "profile:judge_differs_from_run_identity" in loaded.errors
    claims_v3 = json.loads(dev_profile())
    claims_v3["v3_error_independence"]["status"] = "verified"
    _pre, loaded = release_setup(world, tmp_path / "claims-v3", profile_bytes=json.dumps(claims_v3).encode("utf-8"))
    assert "profile:claims_v3_verified_under_a_design_that_cannot_verify_it" in loaded.errors
    assert loaded.v3_error_independence == "unverified"
    # the pinned (frozen) v4 profile itself establishes nothing
    pinned = (V4 / "independence_profile.json").read_bytes()
    _pre, loaded = release_setup(world, tmp_path / "pinned", profile_bytes=pinned)
    assert loaded.errors == () and loaded.judge_separation_established is False
    # results judged by another judge than run_identity names are not this run's judgement
    record = run(world, CASE_KEYS[4], pre_dispatch=full["pre_dispatch"])
    stranger = verify(world, record, DevJudge(identity="another judge"), repetition=3, run=full["run"])
    results = [result for (key, rep), result in full["passes"].items() if (key, rep) != (CASE_KEYS[4], 3)]
    suite = verify_suite([*results, stranger], expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == INCOMPLETE and "judge_differs_from_run_identity" in suite["reasons"]


def test_unseparated_profile_makes_a_would_be_pass_not_judged(world, unseparated):
    suite = verify_suite(passes(unseparated), expectations=world["expectations"], run=unseparated["run"])
    assert suite["suite_outcome"] == NOT_JUDGED and "judge_separation_not_established" in suite["reasons"]
    record = build_suite_record(suite, run=unseparated["run"])
    assert record["judge_separation_established"] is False and record["suite_outcome"] == NOT_JUDGED


# ---------------------------------------------------------------- pre-dispatch manifest (schema v2)


def manifest_errors(world, **options):
    data = as_bytes(dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"],
                                 **options))
    return check_pre_dispatch_manifest(data, committed_sha256=hashlib.sha256(data).hexdigest()).errors


def test_critic_configuration_digest_is_recomputed_canonically(world):
    configuration = dev_configuration(world["rig"], world["task_dir"], model="dév-fixture")
    expected = hashlib.sha256(json.dumps(configuration, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
    assert critic_configuration_digest(configuration) == expected
    assert critic_configuration_digest(dict(reversed(list(configuration.items())))) == expected
    assert expected != hashlib.sha256(json.dumps(configuration, sort_keys=True).encode("utf-8")).hexdigest()
    assert manifest_errors(world, configuration=configuration) == ()
    assert manifest_errors(world, configuration=configuration, digest_="6" * 64) == (
        "critic_configuration_digest_mismatch",)


@pytest.mark.parametrize("change,error", [
    ({"attempt": 2}, "attempt_does_not_follow_prior_attempts"),
    ({"attempt": 1, "prior": ("fail",)}, "attempt_does_not_follow_prior_attempts"),
])
def test_manifest_attempt_must_follow_prior_attempts(world, change, error):
    assert error in manifest_errors(world, **change)
    assert manifest_errors(world, attempt=3, prior=("fail", "incomplete")) == ()


def test_manifest_refuses_schema_violations_and_uncommitted_bytes(world):
    manifest = dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"])
    data = as_bytes(manifest)
    assert check_pre_dispatch_manifest(data, committed_sha256=None).errors == ("no_committed_manifest_sha256",)
    assert "manifest_sha256_differs_from_committed" in check_pre_dispatch_manifest(
        data, committed_sha256="0" * 64).errors
    for mutate in (lambda m: m["run_identity"].pop("usd_hard_stop"),
                   lambda m: m["critic_configuration"]["call_and_run_deadlines"].pop("run_seconds"),
                   lambda m: m["critic_configuration"]["call_and_run_deadlines"].pop("call_seconds"),
                   lambda m: m["critic_configuration"].update(lens_refs_and_digests=[]),
                   lambda m: m.pop("attestations"),
                   lambda m: m["attestations"].pop("sealing"),
                   lambda m: m.update(schema="q01-pre-dispatch-manifest-1"),
                   lambda m: m.update(design_id="q01-release-v3")):
        broken = deepcopy(manifest)
        mutate(broken)
        data = as_bytes(broken)
        errors = check_pre_dispatch_manifest(data, committed_sha256=hashlib.sha256(data).hexdigest()).errors
        assert errors and errors[0].startswith("manifest_schema"), errors
    assert "manifest_not_strict_json" in check_pre_dispatch_manifest(b"{", committed_sha256="0" * 64).errors
    same = deepcopy(manifest)
    same["attestations"]["reviewer"]["name"] = same["attestations"]["author"]["name"]
    data = as_bytes(same)
    assert "attestation:author_is_reviewer" in check_pre_dispatch_manifest(
        data, committed_sha256=hashlib.sha256(data).hexdigest()).errors


def effect_section(world, **changes):
    """A lens-effects-v4 section: every dispatched arm with its own configuration and attempt."""
    base = dev_configuration(world["rig"], world["task_dir"])
    arms = []
    for arm_id, pack in [("no_lens", DEV_LENS_PACK),
                         ("general_multi_perspective", {"id": "dev-checklist", "version": "1", "rules": []}),
                         ("mix", {"id": "dev-mix", "version": "1", "rules": []})]:
        configuration = {**base, "lens_refs_and_digests": lens_refs_and_digests(pack)}
        arms.append({"id": arm_id, "critic_configuration": configuration,
                     "critic_configuration_digest": critic_configuration_digest(configuration),
                     "text_sha256": None if arm_id == "no_lens" else lens_refs_and_digests(pack)["pack_sha256"],
                     "attempt": 1, "prior_attempts": []})
    order = [{"arm": arm["id"], "case_id": case_id} for case_id in sorted(CASE.values()) for arm in arms]
    section = {"design_id": "lens-effects-v4", "effect_set_sha256": "5" * 64, "arms": arms,
               "arm_case_order": order, "predictions_sha256": "8" * 64}
    for change in changes.values():
        change(section)
    return section


@pytest.mark.parametrize("change,error", [
    (lambda s: s["arms"][1].update(text_sha256=None), "lens_effect:general_multi_perspective:text_digest_not_fixed"),
    (lambda s: s["arms"][2].update(text_sha256="9" * 64), "lens_effect:mix:text_digest_is_not_the_sent_lens_pack"),
    (lambda s: s["arms"][0].update(text_sha256="9" * 64), "lens_effect:no_lens:baseline_carries_lens_text"),
    (lambda s: s["arms"].pop(0), "lens_effect:no_baseline_arm"),
    (lambda s: s["arm_case_order"].pop(), "lens_effect:arm_case_order_is_not_every_arm_on_every_case_once"),
    (lambda s: s["arm_case_order"].append(s["arm_case_order"][0]),
     "lens_effect:arm_case_order_is_not_every_arm_on_every_case_once"),
    (lambda s: s.update(effect_set_sha256="6" * 64), "lens_effect:effect_set_is_not_the_sealed_dataset"),
    (lambda s: s["arms"][2].update(attempt=2), "lens_effect:mix:attempt_does_not_follow_prior_attempts"),
    (lambda s: s["arms"][2]["critic_configuration"].update(max_tokens=5),
     "lens_effect:mix:critic_configuration_digest_mismatch"),
])
def test_lens_effect_section_binds_every_arm_before_dispatch(world, change, error):
    assert manifest_errors(world, lens_effect=effect_section(world)) == ()
    errors = manifest_errors(world, lens_effect=effect_section(world, change=change))
    assert any(item.startswith(error) for item in errors), errors


def test_lens_effect_arms_differ_only_in_their_lens_set(world):
    def widen(section):
        arm = section["arms"][2]
        arm["critic_configuration"]["max_tokens"] = 5
        arm["critic_configuration_digest"] = critic_configuration_digest(arm["critic_configuration"])
    errors = manifest_errors(world, lens_effect=effect_section(world, change=widen))
    assert "lens_effect:mix:differs_from_the_run_configuration_beyond_its_lens_set" in errors


# ---------------------------------------------------------------- end to end on dev data, suite record (BF1)


def test_dev_suite_record_validates_and_reaches_the_product_gate(world, full):
    suite = verify_suite(passes(full), expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == "pass", suite["reasons"]
    assert all(counts["cases"] >= 2 and counts[PASS] == 3 * counts["cases"] for counts in suite["boundaries"].values())
    record = build_suite_record(suite, run=full["run"])
    schema = json.loads((V4 / "suite_record.schema.json").read_text(encoding="utf-8"))
    assert Draft202012Validator(schema).is_valid(record) and check_suite_record(record) == []
    assert record["design_id"] == "q01-release-v4" and record["attempt"] == 1 and record["prior_outcomes"] == []
    assert record["critic_configuration_digest"] == critic_configuration_digest(
        dev_configuration(world["rig"], world["task_dir"]))
    assert record["sealed_set_sha256"] == world["manifest_sha"]
    assert record["pre_dispatch_manifest_sha256"] == full["pre_dispatch"].committed_sha256
    assert record["judge_separation_established"] is True and record["v3_error_independence"] == "unverified"
    stripped = {k: v for k, v in record.items() if k != "record_sha256"}
    assert record["record_sha256"] == hashlib.sha256(json.dumps(
        stripped, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    assert record_sha256(record) == record["record_sha256"]
    assert check_suite_record({**record, "attempt": 3}) == ["record_sha256_mismatch"]
    state = critic_qualification_from_suite(record, record["critic_configuration_digest"])
    assert (state.status, state.reason) == ("scoped_pass", "design_cannot_verify_v3")


def test_bf1_v3_status_is_never_taken_from_the_caller_or_the_record(world, full):
    suite = verify_suite(passes(full), expectations=world["expectations"], run=full["run"])
    with pytest.raises(TypeError):
        build_suite_record(suite, run=full["run"], v3_error_independence="verified")
    with pytest.raises(TypeError):
        build_suite_record(suite, manifest_bytes=full["pre_dispatch"].manifest_path.read_bytes())
    assert sc.V3_VERIFYING_DESIGN_IDS == frozenset() and full["run"].v3_error_independence == "unverified"
    record = build_suite_record(suite, run=full["run"])
    forged = {**record, "v3_error_independence": "verified"}
    assert check_suite_record(forged)  # schema: v4 records can only say unverified
    from app.services.critic_qualification import (
        CriticQualificationError,
        suite_record_sha256,
    )
    with pytest.raises(CriticQualificationError, match="record sha256"):
        critic_qualification_from_suite(forged, record["critic_configuration_digest"])
    forged["record_sha256"] = suite_record_sha256(forged)
    state = critic_qualification_from_suite(forged, record["critic_configuration_digest"])
    assert state.status == "scoped_pass"  # the gate caps a design that cannot verify V3
    # an altered suite result is not an issued suite
    for altered in ({**suite, "suite_outcome": "pass", "judge_separation_established": True, "reasons": ["x"]},
                    {**suite, "composition_checked": True, "stopped": False, "dataset_id": "x"}):
        with pytest.raises(ValueError, match="issued by verify_suite"):
            build_suite_record(altered, run=full["run"])


def test_unjudged_dev_suite_is_not_judged(world, full):
    results = [verify(world, run(world, key, pre_dispatch=full["pre_dispatch"]), repetition=1, run=full["run"])
               for key in CASE_KEYS[:4]]
    results += [result for (key, rep), result in full["passes"].items() if not (key in CASE_KEYS[:4] and rep == 1)]
    suite = verify_suite(results, expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == "not_judged"


# ---------------------------------------------------------------- harness pre-dispatch refusal


def release_trial(world, key, pre_dispatch, critic):
    rig = world["rig"]
    return run_release_trial(CASE[key], critic, base_dir=rig.base, config=rig.config, pre_dispatch=pre_dispatch,
                             task_dir=world["task_dir"])


def test_release_trial_requires_a_pre_dispatch_manifest_with_harness_and_lens_pack(world):
    with pytest.raises(TypeError):
        release_trial(world, ("d-good", None), None, DevCritic())
    with pytest.raises(TypeError):
        PreDispatch(world["pre_dispatch"].manifest_path, world["pre_dispatch"].committed_sha256)
    for broken in (PreDispatch(world["pre_dispatch"].manifest_path, world["pre_dispatch"].committed_sha256, None,
                               DEV_LENS_PACK),
                   PreDispatch(world["pre_dispatch"].manifest_path, world["pre_dispatch"].committed_sha256,
                               harness_identity(), None)):
        with pytest.raises(TypeError):
            release_trial(world, ("d-good", None), broken, DevCritic())


def _configured(world, **overrides):
    manifest = dev_manifest(world["expectations"], world["manifest_sha"], rig=world["rig"],
                            task_dir=world["task_dir"],
                            configuration=dev_configuration(world["rig"], world["task_dir"], **overrides))
    return manifest


@pytest.mark.parametrize("variant,error", [
    ("uncommitted", "manifest_sha256_differs_from_committed"),
    ("digest", "critic_configuration_digest_mismatch"),
    ("attempt", "attempt_does_not_follow_prior_attempts"),
    ("chains", "max_proposed_chains_differs_from_manifest"),
    ("call_deadline", "call_seconds_differs_from_manifest"),
    ("run_deadline", "run_seconds_differs_from_manifest"),
    ("contract", "contract_or_parser_version_differs_from_manifest"),
    ("prompt", "critic_prompt_digest_differs_from_manifest"),
    ("lens", "lens_pack_differs_from_configuration"),
    ("order", "case_not_in_manifest_case_order"),
    ("dataset", "environment_differs_from_sealed_dataset_sha256"),
    ("harness", "harness_is_not_the_running_code"),
    ("manifest_harness", "harness_identity_mismatch"),
])
def test_harness_refuses_dispatch_without_a_verifying_manifest(world, tmp_path, variant, error):
    manifest = dev_manifest(world["expectations"], world["manifest_sha"], rig=world["rig"],
                            task_dir=world["task_dir"])
    options = {}
    configuration_changes = {"chains": {"max_proposed_chains": 2},
                             "call_deadline": {"call_and_run_deadlines": {"call_seconds": 99.0, "run_seconds": 60.0}},
                             "run_deadline": {"call_and_run_deadlines": {"call_seconds": 5.0, "run_seconds": 99.0}},
                             "contract": {"parser_version": "other-parser"},
                             "prompt": {"critic_prompt_digest": "1" * 64}}
    if variant in configuration_changes:
        manifest = _configured(world, **configuration_changes[variant])
    elif variant == "uncommitted":
        options["committed"] = "0" * 64
    elif variant == "digest":
        manifest["critic_configuration_digest"] = "9" * 64
    elif variant == "attempt":
        manifest["attempt"] = 2
    elif variant == "lens":
        options["lens_pack"] = {"id": "dev-lens", "version": "2", "rules": []}
    elif variant == "order":
        manifest["run_identity"]["case_order"]["order"] = [CASE[("d-alt", None)]]
    elif variant == "dataset":
        manifest["run_identity"]["sealed_dataset_sha256"] = "5" * 64
    elif variant == "harness":
        options["harness"] = {"version": "other", "sha256": "3" * 64}
    elif variant == "manifest_harness":
        manifest["run_identity"]["harness"] = {"version": "other", "sha256": "3" * 64}
    pre_dispatch, _loaded = release_setup(world, tmp_path, manifest=manifest, **options)
    critic = DevCritic()
    record = release_trial(world, ("d-good", None), pre_dispatch, critic)
    assert (record["status"], record["cause"]) == ("invalid", "pre_dispatch_manifest_unverified")
    assert error in record["pre_dispatch"]["errors"], record["pre_dispatch"]["errors"]
    assert critic.calls == [] and record["calls"] == [] and record["access_log"] == []  # nothing read or sent
    invalid(verify(world, record, DevJudge()), "trial_pre_dispatch_manifest_unverified")


def test_harness_dispatches_with_a_verifying_manifest(world):
    pre_dispatch = world["pre_dispatch"]
    record = release_trial(world, ("d-q3", None), pre_dispatch, DevCritic())
    assert record["status"] == "completed" and record["pre_dispatch"]["errors"] == []
    assert record["pre_dispatch"]["manifest_sha256"] == pre_dispatch.committed_sha256
    assert record["pre_dispatch"]["environment_manifest_sha256"] == world["manifest_sha"]
    assert record["pre_dispatch"]["harness"] == harness_identity()
    assert record["pre_dispatch"]["unchecked_configuration_fields"] == ["max_tokens"]
    assert verify(world, record, DevJudge())["verdict"] == PASS


def test_harness_checks_the_selection_at_every_call(world, tmp_path):
    pre_dispatch, _loaded = release_setup(world, tmp_path, manifest=_configured(world, model="another-model"))
    critic = DevCritic()
    record = release_trial(world, ("d-q3", None), pre_dispatch, critic)
    assert (record["status"], record["cause"]) == ("invalid", "selection_differs_from_configuration")
    assert critic.calls == []


# ---------------------------------------------------------------- BF3 probes: the lens pack is configuration


def test_bf3_a_sealed_bundle_carrying_a_lens_pack_is_refused(world, tmp_path):
    def carry(cases):
        for case in cases:
            case["source"]["lens_pack"] = deepcopy(DEV_LENS_PACK)
    task_dir, sha = make_task(tmp_path / "carry", carry)
    with pytest.raises(SealedSetError, match="lens pack"):
        load_sealed_materials_dir(task_dir, sha)
    pre_dispatch, _loaded = release_setup(world, tmp_path / "carry-run", manifest_sha=sha, task_dir=task_dir)
    critic = DevCritic()
    record = run(world, ("d-good", None), critic, task_dir=task_dir, pre_dispatch=pre_dispatch)
    assert (record["status"], record["cause"]) == ("invalid", "sealed_case_carries_a_lens_pack")
    assert critic.calls == [] and record["calls"] == []


def test_bf3_the_lens_pack_sent_at_each_call_must_hash_to_the_configuration(world, monkeypatch):
    original = q01_harness.stage_input

    def swapped(purpose, case, **kwargs):
        if purpose is q01_harness.P.COUNTEREXAMPLE_PROPOSAL:
            case = {**case, "source": {**case["source"],
                                       "lens_pack": {"id": "swapped-lens", "version": "1", "rules": []}}}
        return original(purpose, case, **kwargs)

    monkeypatch.setattr(q01_harness, "stage_input", swapped)
    critic = DevCritic()
    record = run(world, ("d-good", None), critic)
    assert (record["status"], record["cause"]) == ("invalid", "lens_pack_differs_from_configuration")
    assert len(critic.calls) == 1  # the review call only; the proposal was never sent
    # with the harness check bypassed, the verifier still refuses the trial from the ledger
    monkeypatch.setattr(q01_harness.Q01Trial, "_check_call_configuration", lambda *_args: None)
    record = run(world, ("d-good", None))
    assert record["status"] == "completed"
    invalid(verify(world, record, DevJudge()), "lens_pack_differs_from_configuration")


def test_bf3_the_verifier_takes_no_lens_pack_from_materials(world):
    assert all("lens_pack" not in case["source"] for case in world["materials"].cases.values())
    record = run(world, ("d-alt", None))
    proposal = next(call for call in record["calls"] if call["manifest"]["purpose"] == "counterexample_proposal")
    assert proposal["manifest"]["prepared_manifest"]["lens_pack"]["sha256"] == \
        lens_refs_and_digests(DEV_LENS_PACK)["pack_sha256"]
    assert verify(world, record, DevJudge())["verdict"] == PASS


# ---------------------------------------------------------------- independence from calibration sources


def _imports_and_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports, names, strings = set(), set(), set()
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body
                  and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(("." * node.level) + (node.module or ""))
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            strings.add(node.value)
    return imports, names, strings


@pytest.mark.parametrize("relative", ["evals/deeptwin/verifiers/sealed_critic.py", "evals/deeptwin/verifiers/q01_core.py",
                                      "evals/deeptwin/q01_release_manifest.py"])
def test_sealed_verifier_code_uses_no_calibration_source(relative):
    imports, names, strings = _imports_and_names(ROOT / relative)
    assert not any("q01_materials" in module or "harness" in module or module.endswith("critic")
                   or "q01_cases" in module for module in imports), imports
    assert not {"EXPECTED", "q01_source", "q01_counterexample", "CASE_SPECS"} & names
    assert not any("Task.md" in text or "q01_materials" in text or "q01_lenses" in text for text in strings)


def test_importing_the_sealed_verifier_loads_no_calibration_module():
    code = ("import sys; import evals.deeptwin.verifiers.sealed_critic as m; "
            "bad = [n for n in sys.modules if n.endswith(('q01_materials', 'verifiers.critic', 'q01_cases'))"
            " or '.harness' in n]; print(bad); raise SystemExit(1 if bad else 0)")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
                            check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_verifier_identity_hashes_its_source_files():
    identity = verifier_identity()
    assert identity["version"] == "q01-sealed-verifier-2"
    assert {"app/critic_contract.py", "app/critic_audit.py"} <= set(sc.VERIFIER_FILES)
    files = {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() for relative in sc.VERIFIER_FILES}
    assert identity["sha256"] == hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"))
                                                .encode("utf-8")).hexdigest()
