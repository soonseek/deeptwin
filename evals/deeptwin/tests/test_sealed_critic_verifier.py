"""Offline tests of the data-driven release-v3 verifier (``verifiers/sealed_critic.py``).

TEST-ACTOR DEVELOPMENT DATA ONLY. Every material, candidate, counterexample and
expectation below is synthetic development data authored in this file by the test
actor (the harness/verifier developer) to exercise the verifier's mechanics. It is
NOT a sealed set, was not written by an independent author, was not reviewed, and
can never qualify anything: release-v3 forbids the developer as author and requires
new, sealed, owner-held data. Trials are produced by the real harness with a scripted
``(system, user) -> str`` fixture; ``DevJudge`` is a deterministic offline stand-in.
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

from app.services.critic_qualification import critic_qualification_from_suite
from evals.deeptwin.harness.q01_cases import TASK_DIR, case_id_for, digest, file_bytes
from evals.deeptwin.harness.q01_harness import (
    PreDispatch,
    Q01Trial,
    run_release_trial,
)
from evals.deeptwin.q01_release_manifest import (
    check_pre_dispatch_manifest,
    critic_configuration_digest,
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
    load_sealed_expectations,
    load_sealed_materials,
    load_sealed_materials_dir,
    record_sha256,
    verifier_identity,
    verify_suite,
    verify_trial,
)

ROOT = Path(__file__).resolve().parents[3]
V3 = ROOT / "evals/deeptwin/qualification/release-v3"
ACCEPT, DEFECT, REJECTED = "accept_without_false_rejection", "required_defect", "rejected_counterexample"
VALID, UNRESOLVED, INSUFFICIENT = "valid_counterexample", "unresolved_specific_claim", "insufficient_evidence"
LABEL = "test-actor development data, not sealed"


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
              "criteria": deepcopy(DEV_CRITERIA), "candidate": deepcopy(CANDIDATES[candidate_id]),
              "lens_pack": {"id": "dev-lens", "version": "1", "rules": []}}
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
    document = {"schema": "q01-sealed-expectations-1", "design_id": "q01-release-v3",
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

    def __init__(self, default="supported", **by_prefix):
        self.default, self.by_prefix, self.items = default, by_prefix, []

    def judge(self, item_):
        self.items.append(item_)
        for prefix, status in self.by_prefix.items():
            if item_.item_id.startswith(prefix):
                if isinstance(status, Exception):
                    raise status
                return status
        return self.default


# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("sealed-dev")
    task_dir, manifest_sha = make_task(root)
    rig = make_rig(root)
    return {"root": root, "task_dir": task_dir, "rig": rig, "expectations": load_dev_expectations(),
            "materials": load_sealed_materials_dir(task_dir, manifest_sha), "manifest_sha": manifest_sha}


def run(world, key, critic=None, task_dir=None):
    rig = world["rig"]
    return Q01Trial(CASE[key], critic or DevCritic(), base_dir=rig.base, config=rig.config,
                    task_dir=task_dir or world["task_dir"]).run()


def verify(world, record, judge=None, **kwargs):
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
    other = verify_trial(record, expectations=world["expectations"], materials="not a bundle", judge=DevJudge())
    invalid(other, "sealed_set_mismatch")


def test_material_mismatch_and_answer_leak_are_derived_from_the_sealed_set(world, tmp_path):
    def alter(cases):
        cases[[c["case_id"] for c in cases].index(CASE[("d-good", None)])]["source"]["candidate"]["control"][
            "publication"] = "released on request"
    altered, _sha = make_task(tmp_path / "altered", alter)
    record = run(world, ("d-good", None), task_dir=altered)
    assert record["status"] == "completed"
    invalid(verify(world, record, DevJudge()), "material_mismatch")

    basis = world["expectations"].cases[CASE[("d-q3", None)]].expectation.basis

    def leak(cases):
        cases[[c["case_id"] for c in cases].index(CASE[("d-good", None)])]["source"]["candidate"]["control"][
            "notes"].append(basis)
    leaked, _sha = make_task(tmp_path / "leaked", leak)
    record = run(world, ("d-good", None), task_dir=leaked)
    assert record["status"] == "completed"  # the harness scan does not know sealed answers
    invalid(verify(world, record, DevJudge()), "answer_leak")


def test_leak_markers_come_from_the_sealed_set_not_calibration_sources(world):
    markers = sc.answer_markers(world["expectations"], world["materials"], {"x": "instruction"})
    assert set(sc.BOUNDARY_CLASSES) <= set(markers) and set(CASE.values()) <= set(markers)
    assert any(LABEL in marker for marker in markers)
    calibration = (ROOT / "evals/deeptwin/tasks/v01-q01/Task.md").read_text(encoding="utf-8")
    assert not any(marker in calibration for marker in markers if marker not in sc.BOUNDARY_CLASSES)


# ---------------------------------------------------------------- suite precedence


def fake_result(expectations, case_id, repetition, verdict, materials_sha="f" * 64):
    return {"schema": RESULT_SCHEMA, "verifier_version": VERIFIER_VERSION, "case_id": case_id,
            "repetition": repetition, "verdict": verdict, "cause": None if verdict != INVALID else "dev",
            "expectations_sha256": expectations.sha256, "materials_manifest_sha256": materials_sha}


def oracle(fail, invalid_, missing, not_judged, mismatch, stopped, separated):
    """release-v3 acceptance.suite_outcome, transcribed from the frozen design text."""
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
def test_suite_precedence_table(flags):
    expectations = load_dev_expectations()
    state = dict(zip(FLAGS, flags))
    ids = sorted(expectations.cases)
    results = [fake_result(expectations, case_id, rep, PASS) for case_id in ids for rep in (1, 2, 3)]
    if state["fail"]:
        results[0]["verdict"] = FAIL
    if state["invalid_"]:
        results[3]["verdict"] = INVALID
    if state["not_judged"]:
        results[6]["verdict"] = NOT_JUDGED
    if state["missing"]:
        del results[10]
    committed = "a" * 64
    suite = verify_suite(results, expectations=expectations, planned_repetitions=3,
                         pre_dispatch_manifest_sha256="b" * 64 if state["mismatch"] else committed,
                         committed_manifest_sha256=committed, stopped=state["stopped"],
                         judge_separation_established=state["separated"])
    assert suite["suite_outcome"] == oracle(**state), suite["reasons"]
    all_pass = not any(state[name] for name in ("fail", "invalid_", "missing", "not_judged"))
    assert all(case["case_pass"] for case in suite["cases"].values()) is all_pass


def test_case_pass_needs_every_repetition_valid_and_passing():
    expectations = load_dev_expectations()
    ids = sorted(expectations.cases)
    base = [fake_result(expectations, case_id, rep, PASS) for case_id in ids for rep in (1, 2, 3)]
    options = {"expectations": expectations, "planned_repetitions": 3, "pre_dispatch_manifest_sha256": "a" * 64,
               "committed_manifest_sha256": "a" * 64, "judge_separation_established": True}
    assert verify_suite(base, **options)["suite_outcome"] == "pass"
    for verdict, outcome in [(NOT_JUDGED, "not_judged"), (INVALID, "incomplete"), (FAIL, "fail")]:
        results = deepcopy(base)
        results[-1]["verdict"] = verdict
        suite = verify_suite(results, **options)
        assert suite["suite_outcome"] == outcome and suite["cases"][ids[-1]]["case_pass"] is False
        assert sum(case["case_pass"] for case in suite["cases"].values()) == len(ids) - 1
    # one repetition short of the plan is missing, hence incomplete
    suite = verify_suite(base[:-1], **options)
    assert suite["suite_outcome"] == "incomplete" and "missing_repetition" in suite["reasons"]
    # replacement, extra repetitions, foreign results and mixed materials are never absorbed
    for extra, reason in [(fake_result(expectations, ids[0], 1, PASS), "duplicate_repetition"),
                          (fake_result(expectations, ids[0], 4, PASS), "unplanned_repetition"),
                          ({**base[0], "verifier_version": "q01-critic-verifier-1"}, "unattributable_result"),
                          ({**base[0], "expectations_sha256": "0" * 64}, "unattributable_result"),
                          ({**base[0], "case_id": None, "verdict": INVALID}, "unattributable_result")]:
        suite = verify_suite([*base, extra], **options)
        assert suite["suite_outcome"] == "incomplete" and reason in suite["reasons"]
    mixed = deepcopy(base)
    mixed[0]["materials_manifest_sha256"] = "e" * 64
    assert "results_verified_against_different_materials" in verify_suite(mixed, **options)["reasons"]
    # a fail keeps precedence over every incomplete cause
    failing = deepcopy(base[:-1])
    failing[0]["verdict"] = FAIL
    assert verify_suite(failing, **{**options, "stopped": True})["suite_outcome"] == "fail"


def test_manifest_mismatch_makes_the_suite_incomplete():
    expectations = load_dev_expectations()
    results = [fake_result(expectations, case_id, 1, PASS) for case_id in expectations.cases]
    options = {"expectations": expectations, "planned_repetitions": 1, "judge_separation_established": True}
    assert verify_suite(results, pre_dispatch_manifest_sha256="a" * 64, committed_manifest_sha256="a" * 64,
                        **options)["suite_outcome"] == "pass"
    for recorded, committed in [("a" * 64, "b" * 64), (None, "a" * 64), ("a" * 64, None), ("zz", "zz")]:
        suite = verify_suite(results, pre_dispatch_manifest_sha256=recorded, committed_manifest_sha256=committed,
                             **options)
        assert suite["suite_outcome"] == INCOMPLETE


# ---------------------------------------------------------------- pre-dispatch manifest


def dev_configuration(**overrides):
    configuration = {"provider": "dev-fixture", "mode": "offline", "model": "dev-fixture-critic", "effort": None,
                     "max_tokens": 1000, "critic_prompt_digest": "1" * 64, "contract_version": "dev",
                     "parser_version": "dev", "max_proposed_chains": 16,
                     "call_and_run_deadlines": {"call_seconds": 5.0, "run_seconds": 60.0},
                     "lens_refs_and_digests": []}
    configuration.update(overrides)
    return configuration


def dev_manifest(expectations, materials_sha, *, attempt=1, prior=(), configuration=None, digest_=None, order=None):
    configuration = configuration or dev_configuration()
    return {
        "schema": "q01-pre-dispatch-manifest-1", "design_id": "q01-release-v3",
        "critic_configuration": configuration,
        "critic_configuration_digest": digest_ or critic_configuration_digest(configuration),
        "run_identity": {
            "sealed_dataset_sha256": materials_sha, "sealed_expectations_sha256": expectations.sha256,
            "judge_identity": "dev fixture judge (test actor; not independent)", "judge_prompt_digest": None,
            "independence_profile": {"path": "dev/profile.json", "sha256": "2" * 64},
            "harness": {"version": "dev", "sha256": "3" * 64}, "verifier": verifier_identity(),
            "case_order": {"seed": "dev", "order": sorted(expectations.cases) if order is None else order},
            "authority_ref": "test actor: development only, no authority", "usd_hard_stop": 0.01},
        "attempt": attempt,
        "prior_attempts": [{"attempt": index + 1, "design_id": "q01-release-v3", "sealed_dataset_sha256": "4" * 64,
                            "suite_outcome": outcome} for index, outcome in enumerate(prior)],
        "lens_effect": None,
    }


def as_bytes(manifest):
    return json.dumps(manifest, indent=1).encode("utf-8")


def test_critic_configuration_digest_is_recomputed_canonically():
    configuration = dev_configuration(model="dév-fixture")  # non-ASCII stays literal UTF-8
    expected = hashlib.sha256(json.dumps(configuration, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
    assert critic_configuration_digest(configuration) == expected
    assert critic_configuration_digest(dict(reversed(list(configuration.items())))) == expected
    assert expected != hashlib.sha256(json.dumps(configuration, sort_keys=True).encode("utf-8")).hexdigest()
    expectations = load_dev_expectations()
    good = as_bytes(dev_manifest(expectations, "5" * 64, configuration=configuration))
    assert check_pre_dispatch_manifest(good, committed_sha256=hashlib.sha256(good).hexdigest()).ok
    bad = as_bytes(dev_manifest(expectations, "5" * 64, configuration=configuration, digest_="6" * 64))
    check = check_pre_dispatch_manifest(bad, committed_sha256=hashlib.sha256(bad).hexdigest())
    assert check.errors == ("critic_configuration_digest_mismatch",)


@pytest.mark.parametrize("change,error", [
    ({"attempt": 2}, "attempt_does_not_follow_prior_attempts"),
    ({"attempt": 1, "prior": ("fail",)}, "attempt_does_not_follow_prior_attempts"),
])
def test_manifest_attempt_must_follow_prior_attempts(change, error):
    expectations = load_dev_expectations()
    data = as_bytes(dev_manifest(expectations, "5" * 64, **change))
    assert error in check_pre_dispatch_manifest(data, committed_sha256=hashlib.sha256(data).hexdigest()).errors
    data = as_bytes(dev_manifest(expectations, "5" * 64, attempt=3, prior=("fail", "incomplete")))
    assert check_pre_dispatch_manifest(data, committed_sha256=hashlib.sha256(data).hexdigest()).ok


def test_manifest_refuses_schema_violations_and_uncommitted_bytes():
    expectations = load_dev_expectations()
    manifest = dev_manifest(expectations, "5" * 64)
    data = as_bytes(manifest)
    assert check_pre_dispatch_manifest(data, committed_sha256=None).errors == ("no_committed_manifest_sha256",)
    assert "manifest_sha256_differs_from_committed" in check_pre_dispatch_manifest(
        data, committed_sha256="0" * 64).errors
    broken = deepcopy(manifest)
    del broken["run_identity"]["usd_hard_stop"]
    data = as_bytes(broken)
    errors = check_pre_dispatch_manifest(data, committed_sha256=hashlib.sha256(data).hexdigest()).errors
    assert errors and errors[0].startswith("manifest_schema")
    assert "manifest_not_strict_json" in check_pre_dispatch_manifest(b"{", committed_sha256="0" * 64).errors


# ---------------------------------------------------------------- end to end on dev data, suite record


def test_dev_suite_record_validates_and_reaches_the_product_gate(world):
    expectations, materials_sha = world["expectations"], world["manifest_sha"]
    results = [verify(world, run(world, key), DevJudge(), repetition=1) for key in CASE_KEYS]
    manifest_bytes = as_bytes(dev_manifest(expectations, materials_sha, attempt=2, prior=("fail",)))
    committed = hashlib.sha256(manifest_bytes).hexdigest()
    suite = verify_suite(results, expectations=expectations, planned_repetitions=1,
                         pre_dispatch_manifest_sha256=committed, committed_manifest_sha256=committed,
                         judge_separation_established=True, manifest_bytes=manifest_bytes)
    assert suite["suite_outcome"] == "pass", suite["reasons"]
    assert all(counts["cases"] >= 2 and counts[PASS] == counts["cases"] for counts in suite["boundaries"].values())
    record = build_suite_record(suite, manifest_bytes=manifest_bytes)
    schema = json.loads((V3 / "suite_record.schema.json").read_text(encoding="utf-8"))
    assert Draft202012Validator(schema).is_valid(record) and check_suite_record(record) == []
    assert record["attempt"] == 2 and record["prior_outcomes"] == ["fail"]
    assert record["critic_configuration_digest"] == critic_configuration_digest(dev_configuration())
    assert record["sealed_set_sha256"] == materials_sha and record["pre_dispatch_manifest_sha256"] == committed
    stripped = {k: v for k, v in record.items() if k != "record_sha256"}
    assert record["record_sha256"] == hashlib.sha256(json.dumps(
        stripped, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    assert record_sha256(record) == record["record_sha256"]
    assert check_suite_record({**record, "attempt": 3}) == ["record_sha256_mismatch"]
    state = critic_qualification_from_suite(record, record["critic_configuration_digest"])
    assert state.status == "scoped_pass"  # never a qualification while V3 is unverified

    # the same results against a manifest pinning other expectations do not verify
    other = dev_manifest(expectations, materials_sha)
    other["run_identity"]["sealed_expectations_sha256"] = "7" * 64
    other_bytes = as_bytes(other)
    other_sha = hashlib.sha256(other_bytes).hexdigest()
    suite = verify_suite(results, expectations=expectations, planned_repetitions=1,
                         pre_dispatch_manifest_sha256=other_sha, committed_manifest_sha256=other_sha,
                         judge_separation_established=True, manifest_bytes=other_bytes)
    assert suite["suite_outcome"] == INCOMPLETE
    assert "manifest:sealed_expectations_sha256_mismatch" in suite["reasons"]
    assert build_suite_record(suite, manifest_bytes=other_bytes)["suite_outcome"] == INCOMPLETE
    # a pass verified only by hash values is downgraded when the manifest bytes do not verify
    loose = verify_suite(results, expectations=expectations, planned_repetitions=1,
                         pre_dispatch_manifest_sha256=other_sha, committed_manifest_sha256=other_sha,
                         judge_separation_established=True)
    assert loose["suite_outcome"] == "pass"
    bad_digest = dev_manifest(expectations, materials_sha, digest_="8" * 64)
    bad_bytes = as_bytes(bad_digest)
    bad_sha = hashlib.sha256(bad_bytes).hexdigest()
    loose = {**loose, "pre_dispatch_manifest_sha256": bad_sha, "committed_manifest_sha256": bad_sha}
    assert build_suite_record(loose, manifest_bytes=bad_bytes)["suite_outcome"] == INCOMPLETE
    with pytest.raises(ValueError, match="not the manifest"):
        build_suite_record(loose, manifest_bytes=other_bytes)


def test_unjudged_dev_suite_is_not_judged(world):
    expectations = world["expectations"]
    results = [verify(world, run(world, key), repetition=1) for key in CASE_KEYS[:4]]
    results += [fake_result(expectations, CASE[key], 1, PASS, world["manifest_sha"]) for key in CASE_KEYS[4:]]
    suite = verify_suite(results, expectations=expectations, planned_repetitions=1,
                         pre_dispatch_manifest_sha256="a" * 64, committed_manifest_sha256="a" * 64,
                         judge_separation_established=True)
    assert suite["suite_outcome"] == "not_judged"


# ---------------------------------------------------------------- harness pre-dispatch refusal


def _pre_dispatch(world, tmp_path, manifest, committed=None):
    path = tmp_path / "pre-dispatch.json"
    path.write_bytes(as_bytes(manifest))
    return PreDispatch(path, committed or hashlib.sha256(path.read_bytes()).hexdigest())


def release_trial(world, key, pre_dispatch, critic):
    rig = world["rig"]
    return run_release_trial(CASE[key], critic, base_dir=rig.base, config=rig.config, pre_dispatch=pre_dispatch,
                             task_dir=world["task_dir"])


def test_release_trial_requires_a_pre_dispatch_manifest(world):
    with pytest.raises(TypeError):
        release_trial(world, ("d-good", None), None, DevCritic())


@pytest.mark.parametrize("variant,error", [
    ("uncommitted", "manifest_sha256_differs_from_committed"),
    ("digest", "critic_configuration_digest_mismatch"),
    ("attempt", "attempt_does_not_follow_prior_attempts"),
    ("chains", "max_proposed_chains_differs_from_manifest"),
    ("deadline", "call_seconds_differs_from_manifest"),
    ("order", "case_not_in_manifest_case_order"),
    ("dataset", "environment_differs_from_sealed_dataset_sha256"),
])
def test_harness_refuses_dispatch_without_a_verifying_manifest(world, tmp_path, variant, error):
    expectations = world["expectations"]
    manifest = dev_manifest(expectations, world["manifest_sha"])
    committed = None
    if variant == "uncommitted":
        committed = "0" * 64
    elif variant == "digest":
        manifest["critic_configuration_digest"] = "9" * 64
    elif variant == "attempt":
        manifest["attempt"] = 2
    elif variant == "chains":
        manifest["critic_configuration"]["max_proposed_chains"] = 2
        manifest["critic_configuration_digest"] = critic_configuration_digest(manifest["critic_configuration"])
    elif variant == "deadline":
        manifest["critic_configuration"]["call_and_run_deadlines"]["call_seconds"] = 99.0
        manifest["critic_configuration_digest"] = critic_configuration_digest(manifest["critic_configuration"])
    elif variant == "order":
        manifest["run_identity"]["case_order"]["order"] = [CASE[("d-alt", None)]]
    elif variant == "dataset":
        manifest["run_identity"]["sealed_dataset_sha256"] = "5" * 64
    critic = DevCritic()
    record = release_trial(world, ("d-good", None), _pre_dispatch(world, tmp_path, manifest, committed), critic)
    assert (record["status"], record["cause"]) == ("invalid", "pre_dispatch_manifest_unverified")
    assert error in record["pre_dispatch"]["errors"]
    assert critic.calls == [] and record["calls"] == [] and record["access_log"] == []  # nothing read or sent
    invalid(verify(world, record, DevJudge()), "trial_pre_dispatch_manifest_unverified")


def test_harness_dispatches_with_a_verifying_manifest(world, tmp_path):
    manifest = dev_manifest(world["expectations"], world["manifest_sha"])
    pre_dispatch = _pre_dispatch(world, tmp_path, manifest)
    record = release_trial(world, ("d-q3", None), pre_dispatch, DevCritic())
    assert record["status"] == "completed" and record["pre_dispatch"]["errors"] == []
    assert record["pre_dispatch"]["manifest_sha256"] == pre_dispatch.committed_sha256
    assert record["pre_dispatch"]["environment_manifest_sha256"] == world["manifest_sha"]
    assert verify(world, record, DevJudge())["verdict"] == PASS
    bound = PreDispatch(pre_dispatch.manifest_path, pre_dispatch.committed_sha256,
                        harness={"version": "other", "sha256": "3" * 64})
    record = release_trial(world, ("d-q3", None), bound, DevCritic())
    assert "harness_identity_mismatch" in record["pre_dispatch"]["errors"]


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
    assert identity["version"] == "q01-sealed-verifier-1"
    files = {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() for relative in sc.VERIFIER_FILES}
    assert identity["sha256"] == hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"))
                                                .encode("utf-8")).hexdigest()
