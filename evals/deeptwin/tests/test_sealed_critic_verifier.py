"""Offline tests of the data-driven release-v7 verifier (``verifiers/sealed_critic.py``).

TEST-ACTOR DEVELOPMENT DATA ONLY. Every material, candidate, counterexample,
expectation, lens pack, manifest and independence profile below is synthetic
development data authored in this file by the test actor (the harness/verifier
developer) to exercise the verifier's mechanics. It is NOT a sealed set, was not
written by an independent author, was not reviewed, names no real judge, and can
never qualify anything: release-v7 forbids the developer as author and requires new,
sealed, owner-held data.

Release trials run through the real harness and the Claude rig's attested turn, over
the product Claude adapter and an offline FAKE PROVIDER SERVER (``claude_mock.MockClaude``,
an ``httpx`` mock transport; no network, no API call). The fake provider answers critic
prompts with the scripted ``DevCritic`` fixture and reports a served model, message id and
request id like the provider does, so the provider-reported identity path is exercised end
to end. A scripted ``(system, user) -> str`` callable handed to the harness directly is the
calibration/development transport: it can never complete a release trial (audit 5, X1).
``DevJudge`` is a deterministic offline stand-in whose ``judge_attested`` answers are those
of a FAKE JUDGE PROVIDER STUB (a raw reply plus a stub served model and a request id that is
unique in this test process).

The fake provider server is an INJECTED transport of the Claude rig. release-v7 allows no
injected transport for a release run (``run_identity.critic_transport``, audit 6 non-blocking
5), so this module admits the fake server's name in
``q01_release_manifest.TEST_DOUBLE_TRANSPORTS`` for its duration only
(``admit_the_fake_provider_server``); ``test_a6_5_*`` checks that nothing is admitted otherwise.

Every trial is judged at most once (audit 6, Y1): a verification with a judge opens the trial's
judge log exclusively, so the fail, invalid and not_judged suite variants below come from
separately dispatched trials under their own manifests (``variant_run``), never from re-judging.

Audit 3 (of release-v3) probes are marked ``BF1``/``BF2``/``BF3``, audit 4 (of
release-v4) probes ``B1``/``B2``/``N1``..``N7``, audit 5 (of release-v5) probes
``X1`` and ``A5_1``..``A5_7``, and audit 6 (of release-v6) probes ``A6_P1``..``A6_P5`` and
``A6_2``..``A6_6``: each forged, degenerate, cherry-picked, unattested, re-judged, id-reusing
or rerun input now fails. Every release trial here gets its own manifest, trial base directory and
dispatch journal unless a test says otherwise (``run``), so trials follow the planned slots.
"""

import ast
import dataclasses
import hashlib
import itertools
import json
import shutil
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from app.critic_contract import CONTRACT_VERSION, PARSER_VERSION
from app.critic_trial import ProviderReply
from app.services.critic_qualification import (
    CriticQualificationError,
    critic_qualification_from_suite,
)
from evals.deeptwin.harness import q01_harness
from evals.deeptwin.harness.q01_cases import TASK_DIR, case_id_for, digest, file_bytes
from evals.deeptwin.harness.q01_harness import (
    PreDispatch,
    critic_prompt_digest,
    harness_identity,
    run_release_trial,
)
from evals.deeptwin import q01_release_manifest
from evals.deeptwin.q01_release_manifest import (
    PROVIDER_FAMILIES,
    check_pre_dispatch_manifest,
    critic_configuration_digest,
    journal_entry_sha256,
    journal_line,
    judge_shares_critic,
    lens_refs_and_digests,
    planned_slots,
    read_journal,
)
from evals.deeptwin.tests.claude_mock import MOCK_TRANSPORT_NAME, attested_rig
from evals.deeptwin.verifiers import sealed_critic as sc
from evals.deeptwin.verifiers.q01_core import AttestedJudgement
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
V7 = ROOT / "evals/deeptwin/qualification/release-v7"
ACCEPT, DEFECT, REJECTED = "accept_without_false_rejection", "required_defect", "rejected_counterexample"
VALID, UNRESOLVED, INSUFFICIENT = "valid_counterexample", "unresolved_specific_claim", "insufficient_evidence"
LABEL = "test-actor development data, not sealed"
JUDGE_IDENTITY = "dev fixture judge (test actor; not independent)"
JUDGE_PROMPT_DIGEST = hashlib.sha256(b"dev fixture judge prompt (test actor)").hexdigest()
JUDGE_MODEL = "dev-fixture-judge-model"  # the fake judge provider stub's configured (and reported) model
# TEST-ACTOR commit reference: nothing is committed or timestamped for development data.
COMMIT_REF = {"kind": "external_timestamp", "ref": "test actor: development only, no commit or timestamp"}
DEV_LENS_PACK = {"id": "dev-lens", "version": "1", "rules": []}  # the configuration's (empty) lens pack


@pytest.fixture(scope="module", autouse=True)
def admit_the_fake_provider_server():
    """Admit the offline fake provider server as a named test double for this module only.

    release-v7 names no test double (``TEST_DOUBLE_TRANSPORTS`` is empty), so without this a
    manifest naming the injected fake server is refused and nothing is dispatched.
    """
    assert q01_release_manifest.TEST_DOUBLE_TRANSPORTS == frozenset()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(q01_release_manifest, "TEST_DOUBLE_TRANSPORTS", frozenset({MOCK_TRANSPORT_NAME}))
        yield
    assert q01_release_manifest.TEST_DOUBLE_TRANSPORTS == frozenset()


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
    document = {"schema": "q01-sealed-expectations-1", "design_id": "q01-release-v7",
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


class DeclaredJudge:
    """Deterministic offline judge that only declares its identity (no provider-reported answer)."""

    version = "dev-fixture-judge-1"
    prompt_digest = JUDGE_PROMPT_DIGEST

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


# fake judge provider request/message ids, unique across this test process (audit 6, Y2)
JUDGE_IDS = itertools.count(1)


class DevJudge(DeclaredJudge):
    """``DeclaredJudge`` whose answers come back as a FAKE JUDGE PROVIDER STUB would return them.

    ``judge_attested`` wraps the scripted status in a raw provider reply and a stub
    provider-reported model (``served_model``, by default the manifest's ``JUDGE_MODEL``) and
    a request id unique in this process; ``request_ids=False`` reports none. Test-actor
    development stand-in only.
    """

    def __init__(self, default="supported", identity=None, served_model=JUDGE_MODEL, request_ids=True,
                 raw=None, **by_prefix):
        super().__init__(default, identity, **by_prefix)
        self.served_model, self.request_ids, self.raw, self.answers = served_model, request_ids, raw, 0

    def judge_attested(self, item_):
        status = self.judge(item_)
        self.answers += 1
        raw = self.raw if self.raw is not None else json.dumps({"verdict": status,
                                                                "reason": "Dev fake judge provider stub."})
        number = next(JUDGE_IDS)
        request_id = f"req_devjudge{number:08d}" if self.request_ids else None
        return AttestedJudgement(raw, self.served_model, request_id, f"msg_devjudge{number:08d}")




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
    """A TEST-ACTOR successor profile naming release-v7 (never a real judge arrangement)."""
    profile = json.loads((V7 / "independence_profile.json").read_text(encoding="utf-8"))
    profile["profile_id"] = "test-actor-dev-profile"
    profile["judge_separation"]["established"] = established
    profile["judge_separation"]["judge"] = ({"identity": JUDGE_IDENTITY, "prompt_digest": JUDGE_PROMPT_DIGEST,
                                             "option": "other_provider"} if established else None)
    profile.update(changes)
    return json.dumps(profile, ensure_ascii=False, indent=1).encode("utf-8")


UNUSED_JOURNAL = "/nonexistent-dev-journal/q01-dispatch-journal.jsonl"  # manifests that never dispatch
UNUSED_TRIALS = "/nonexistent-dev-trials"  # the trial base directory of manifests that never dispatch


def environment_case_shas(task_dir):
    """``run_identity.sealed_case_sha256s``: the case entries of the environment manifest."""
    manifest = json.loads((Path(task_dir) / "environment" / "manifest.json").read_bytes())
    return {entry["case_id"]: entry["sha256"] for entry in manifest["cases"]}


def prior_attempt(index, outcome, dataset="4" * 64, expectations="3" * 64, case_ids=None, case_shas=None):
    """One prior attempt of a manifest: its set digests, case ids and case sha256s (all spent)."""
    return {"attempt": index, "design_id": "q01-release-v7", "sealed_dataset_sha256": dataset,
            "sealed_expectations_sha256": expectations,
            "case_ids": case_ids or [f"q01-{index:010x}"], "case_sha256s": case_shas or [f"{index:x}" * 64],
            "suite_outcome": outcome}


def order_first(case_id):
    """A case order that plans ``case_id`` first (the dev expectations' ids, sorted, otherwise)."""
    return [case_id, *sorted(value for value in CASE.values() if value != case_id)]


def dev_manifest(expectations, materials_sha, *, rig, task_dir, attempt=1, prior=(), configuration=None,
                 digest_=None, order=None, profile_bytes=None, lens_effect=None, journal=None, trial_base=None):
    configuration = configuration or dev_configuration(rig, task_dir)
    profile_bytes = dev_profile() if profile_bytes is None else profile_bytes
    order = sorted(expectations.cases) if order is None else order
    return {
        "schema": "q01-pre-dispatch-manifest-5", "design_id": "q01-release-v7",
        "critic_configuration": configuration,
        "critic_configuration_digest": digest_ or critic_configuration_digest(configuration),
        "run_identity": {
            "sealed_dataset_sha256": materials_sha, "sealed_expectations_sha256": expectations.sha256,
            "judge_identity": JUDGE_IDENTITY, "judge_prompt_digest": JUDGE_PROMPT_DIGEST,
            "judge_model": JUDGE_MODEL, "sealed_case_sha256s": environment_case_shas(task_dir),
            "trial_base_dir": {"path": str(trial_base or (Path(journal).parent / "trials" if journal
                                                          else UNUSED_TRIALS))},
            "independence_profile": {"path": "dev/profile.json",
                                     "sha256": hashlib.sha256(profile_bytes).hexdigest()},
            "harness": harness_identity(), "verifier": verifier_identity(),
            "case_order": {"seed": "dev", "order": order},
            "authority_ref": "test actor: development only, no authority", "usd_hard_stop": 0.01,
            "planned_slots": planned_slots(order),
            "dispatch_journal": {"path": str(journal or UNUSED_JOURNAL)},
            # the rig's declared transport: the INJECTED fake provider server (admitted above)
            "critic_transport": deepcopy(rig.claude.critic_transport)},
        "attempt": attempt,
        "prior_attempts": [prior_attempt(index + 1, outcome) for index, outcome in enumerate(prior)],
        "attestations": {"author": attestation("test actor as author"),
                         "reviewer": attestation("test actor as reviewer"),
                         "sealing": attestation("test actor as sealer")},
        "lens_effect": lens_effect,
    }


def as_bytes(manifest):
    return json.dumps(manifest, indent=1).encode("utf-8")


# loaded release runs by manifest path and by trial id, so ``verify`` checks each trial
# against the manifest (and dispatch journal) it was dispatched under
LOADED, RUNS = {}, {}


def release_setup(world, directory, *, manifest=None, manifest_sha=None, task_dir=None, profile_bytes=None,
                  committed=None, lens_pack=None, harness=None, repetition=1, commit_ref=None, **manifest_options):
    """(PreDispatch, loaded ReleaseRun) for one dev manifest, its journal and its trial base under ``directory``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "trials").mkdir(exist_ok=True)
    profile_bytes = dev_profile() if profile_bytes is None else profile_bytes
    if manifest is None:
        manifest_options.setdefault("journal", directory / "dispatch-journal.jsonl")
        manifest_options.setdefault("trial_base", directory / "trials")
        manifest = dev_manifest(world["expectations"], manifest_sha or world["manifest_sha"], rig=world["rig"],
                                task_dir=task_dir or world["task_dir"], profile_bytes=profile_bytes,
                                **manifest_options)
    data = as_bytes(manifest)
    path = directory / "pre-dispatch.json"
    path.write_bytes(data)
    committed = committed or hashlib.sha256(data).hexdigest()
    pre_dispatch = PreDispatch(path, committed, harness_identity() if harness is None else harness,
                               deepcopy(DEV_LENS_PACK) if lens_pack is None else lens_pack, repetition,
                               deepcopy(COMMIT_REF) if commit_ref is None else commit_ref)
    loaded = load_release_run(data, committed_sha256=committed, profile_bytes=profile_bytes)
    LOADED[path] = loaded
    return pre_dispatch, loaded


def scratch(world):
    return world["root"] / f"scratch-{uuid4().hex[:12]}"


def dev_rig(root, **options):
    """The attested Claude rig over the fake provider server, with the fields these tests read."""
    rig = attested_rig(root / "rig", **options)
    base = root / "plain-trials"  # plain (non-release) trials only
    base.mkdir(exist_ok=True)
    choice = {"provider": "claude", "mode": "api", "model": rig.model_id, "effort": rig.effort}
    return SimpleNamespace(choice=choice, config=rig.config, base=base, attested_turn=rig.attested_turn,
                           critic=rig.critic, mock=rig.mock, claude=rig)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("sealed-dev")
    task_dir, manifest_sha = make_task(root)
    (root / "rig").mkdir()
    rig = dev_rig(root)
    state = {"root": root, "task_dir": task_dir, "rig": rig, "expectations": load_dev_expectations(),
             "materials": load_sealed_materials_dir(task_dir, manifest_sha), "manifest_sha": manifest_sha}
    state["pre_dispatch"], state["run"] = release_setup(state, root / "run")
    assert state["run"].errors == () and state["run"].judge_separation_established is True
    return state


def trial_base(world, pre_dispatch):
    """The manifest's ``trial_base_dir`` (the only base directory the harness accepts)."""
    try:
        return Path(json.loads(Path(pre_dispatch.manifest_path).read_bytes())["run_identity"]["trial_base_dir"]["path"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return world["rig"].base


def run(world, key, critic=None, task_dir=None, pre_dispatch=None, repetition=None, scripted=False, rig=None):
    """One release trial of ``key``. Without ``pre_dispatch`` it gets a fresh manifest and journal
    planning ``key`` first, so it is journalled as slot (key, 1).

    The critic fixture answers through the fake provider server and the rig's attested turn;
    with ``scripted=True`` the fixture itself is handed to the harness as a plain
    ``(system, user) -> str`` transport (the calibration/development path), carrying the rig's
    transport declaration the way an in-process caller can attach it (so the per-call
    attestation checks, not the declared-transport check, are what refuse it)."""
    rig = rig or world["rig"]
    if pre_dispatch is None:
        assert task_dir is None, "a trial in another environment needs its own manifest"
        pre_dispatch, _loaded = release_setup(world, scratch(world), order=order_first(CASE[key]))
    if repetition is not None:
        pre_dispatch = dataclasses.replace(pre_dispatch, repetition=repetition)
    critic = critic or DevCritic()
    rig.critic.target = critic
    if scripted and not hasattr(critic, "critic_transport"):
        critic.critic_transport = deepcopy(rig.claude.critic_transport)
    record = run_release_trial(CASE[key], critic if scripted else rig.attested_turn,
                               base_dir=trial_base(world, pre_dispatch), config=rig.config,
                               pre_dispatch=pre_dispatch, task_dir=task_dir or world["task_dir"])
    if Path(pre_dispatch.manifest_path) in LOADED:
        RUNS[record["trial_id"]] = LOADED[Path(pre_dispatch.manifest_path)]
    return record


def verify(world, record, judge=None, **kwargs):
    if "run" not in kwargs:
        kwargs["run"] = (RUNS.get(record.get("trial_id")) if type(record) is dict else None) or world["run"]
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
    result = verify(world, run(world, ("d-alt", None), down), DevJudge(), repetition=1)
    invalid(result, "trial_transport_or_fixture_error")
    assert (result["case_id"], result["repetition"], result["boundary"]) == (CASE[("d-alt", None)], 1, ACCEPT)
    assert result["journal_entry_sha256"]  # journalled before its first call, so attributable
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
    pre_dispatch, other_run = release_setup(world, tmp_path / "altered", manifest_sha=sha, task_dir=altered,
                                            order=order_first(CASE[("d-good", None)]))
    record = run(world, ("d-good", None), task_dir=altered, pre_dispatch=pre_dispatch)
    assert record["status"] == "completed"
    invalid(verify(world, record, DevJudge(), run=other_run), "material_mismatch")
    # the same record against the world's manifest is not a trial of that manifest
    invalid(verify(world, record, DevJudge(), run=world["run"]), "not_a_release_trial_of_this_manifest")

    basis = world["expectations"].cases[CASE[("d-q3", None)]].expectation.basis

    def leak(cases):
        cases[[c["case_id"] for c in cases].index(CASE[("d-good", None)])]["source"]["candidate"]["control"][
            "notes"].append(basis)
    leaked, sha = make_task(tmp_path / "leaked", leak)
    pre_dispatch, other_run = release_setup(world, tmp_path / "leaked", manifest_sha=sha, task_dir=leaked,
                                            order=order_first(CASE[("d-good", None)]))
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


KEY = {case_id: key for key, case_id in CASE.items()}


# The slot of each suite variant and the judge that produces it on a freshly dispatched trial
# (audit 6, Y1: a variant is never a second judging of a trial that was already judged).
VARIANT_SLOTS = {FAIL: (CASE_KEYS[0], 1), INVALID: (CASE_KEYS[1], 1), NOT_JUDGED: (CASE_KEYS[2], 1)}
VARIANT_JUDGES = {FAIL: lambda: DevJudge(accept="not_supported"),
                  INVALID: lambda: DevJudge(q7=RuntimeError("judge down")),
                  NOT_JUDGED: lambda: DeclaredJudge()}  # a judge that only declares its identity


def _full(world, directory, profile_bytes, critics=None, variants=frozenset()):
    """Every dev case x 3 repetitions as real release trials under one manifest, dispatched in
    its planned slot order and journalled; ``critics`` maps a slot to a scripted critic.

    Each trial is verified exactly once. ``variants`` (a subset of fail, invalid, not_judged)
    judges the variant's slot with the variant's judge instead of the passing ``DevJudge``:
    a variant is its own separately dispatched run, never a re-judged trial."""
    pre_dispatch, loaded = release_setup(world, directory, profile_bytes=profile_bytes)
    records, results = {}, {}
    judges = {VARIANT_SLOTS[variant]: VARIANT_JUDGES[variant] for variant in variants}
    for slot in loaded.identity["planned_slots"]:
        key, rep = KEY[slot["case_id"]], slot["repetition"]
        critic = (critics or {}).get((key, rep))
        records[(key, rep)] = run(world, key, critic, pre_dispatch=pre_dispatch, repetition=rep)
        results[(key, rep)] = verify(world, records[(key, rep)], judges.get((key, rep), DevJudge)(), run=loaded)
    for variant in variants:
        assert results[VARIANT_SLOTS[variant]]["verdict"] == variant
    return {"run": loaded, "pre_dispatch": pre_dispatch, "records": records, "passes": results,
            "variants": {variant: results[VARIANT_SLOTS[variant]] for variant in variants}}


@pytest.fixture(scope="module")
def runs(world):
    """Full dev runs by (separated, variants), each dispatched and judged once, built on demand."""
    cache = {}

    def get(separated, variants=frozenset()):
        key = (separated, frozenset(variants))
        if key not in cache:
            name = ("full" if separated else "unseparated") + "".join(f"-{v}" for v in sorted(variants))
            cache[key] = _full(world, world["root"] / name, dev_profile(established=separated), variants=variants)
        return cache[key]

    return get


@pytest.fixture(scope="module")
def full(runs):
    data = runs(True)
    assert all(result["verdict"] == PASS for result in data["passes"].values())
    return data


@pytest.fixture(scope="module")
def unseparated(runs):
    """The same dev run under a profile without established judge separation."""
    return runs(False)


def variant_run(runs, separated, fail=False, invalid_=False, not_judged=False):
    """The run for a set of variant flags. Fail takes precedence over invalid and not_judged, and
    invalid over not_judged, so the run with every lower-precedence variant as well decides the
    same outcome: four runs per separation instead of eight."""
    if fail:
        return runs(separated, {FAIL, INVALID, NOT_JUDGED})
    if invalid_:
        return runs(separated, {INVALID, NOT_JUDGED})
    if not_judged:
        return runs(separated, {NOT_JUDGED})
    return runs(separated)


def passes(full_run):
    return [full_run["passes"][(key, rep)] for key in CASE_KEYS for rep in (1, 2, 3)]


@contextmanager
def stopped_journal(loaded, reason="usd_hard_stop reached (test actor)"):
    """The run's dispatch journal with the dispatcher's stop entry appended, restored afterwards."""
    path = Path(loaded.identity["dispatch_journal"]["path"])
    original = path.read_bytes()
    entry, errors = q01_harness.DispatchJournal(path).stop(
        manifest_sha256=loaded.manifest_sha256, commit_ref=COMMIT_REF, planned=loaded.identity["planned_slots"],
        reason=reason)
    assert entry is not None and errors == [], errors
    try:
        yield entry
    finally:
        path.write_bytes(original)


# ---------------------------------------------------------------- suite precedence


def oracle(fail, invalid_, missing, not_judged, mismatch, stopped, separated):
    """release-v7 acceptance.suite_outcome, transcribed from the frozen design text."""
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
def test_suite_precedence_table(world, runs, flags):
    state = dict(zip(FLAGS, flags))
    # every variant is a separately dispatched trial of its own run, judged once (audit 6, Y1)
    source = variant_run(runs, state["separated"], state["fail"], state["invalid_"], state["not_judged"])
    results = {slot: result for slot, result in source["passes"].items()}
    if state["missing"]:
        del results[(CASE_KEYS[5], 3)]
    loaded = source["run"]
    if state["mismatch"]:  # the same bytes against another committed value
        manifest_bytes = source["pre_dispatch"].manifest_path.read_bytes()
        loaded = load_release_run(manifest_bytes, committed_sha256="0" * 64,
                                  profile_bytes=dev_profile(established=state["separated"]))
    with (stopped_journal(source["run"]) if state["stopped"] else nullcontext()):
        # the stop is the dispatcher's journal entry; verify_suite takes no caller flag
        suite = verify_suite(list(results.values()), expectations=world["expectations"], run=loaded)
    assert suite["suite_outcome"] == oracle(**state), suite["reasons"]
    all_pass = not any(state[name] for name in ("fail", "invalid_", "missing", "not_judged"))
    assert all(case["case_pass"] for case in suite["cases"].values()) is all_pass
    # no result of a run is a second judging: every judge log is exactly its result's one judging
    assert not {"judge_log_differs_from_result", "judge_log_without_a_judging_result"} & set(suite["reasons"])


def test_case_pass_needs_every_repetition_valid_and_passing(world, full, runs):
    base = passes(full)
    options = {"expectations": world["expectations"], "run": full["run"]}
    assert verify_suite(base, **options)["suite_outcome"] == "pass"
    ids = [CASE[key] for key in CASE_KEYS]
    suite = verify_suite(base[:-1], **options)
    assert suite["suite_outcome"] == "incomplete" and "missing_repetition" in suite["reasons"]
    assert "journalled_trial_not_submitted" in suite["reasons"]
    assert suite["cases"][ids[-1]]["case_pass"] is False
    assert sum(case["case_pass"] for case in suite["cases"].values()) == len(ids) - 1
    # a second result for a slot is never absorbed (and a trial is never judged twice)
    extra = verify(world, full["records"][(CASE_KEYS[0], 1)], DevJudge(), run=full["run"])
    invalid(extra, "trial_already_judged")
    suite = verify_suite([*base, extra], **options)
    assert suite["suite_outcome"] == "incomplete" and "duplicate_repetition" in suite["reasons"]
    unjudged = verify(world, full["records"][(CASE_KEYS[0], 1)], None, run=full["run"])
    suite = verify_suite([*base, unjudged], **options)
    assert suite["suite_outcome"] == "incomplete" and "duplicate_repetition" in suite["reasons"]
    # a fail keeps precedence over every incomplete cause
    failed = runs(True, {FAIL, INVALID, NOT_JUDGED})
    failing = passes(failed)[:-1]
    assert failing[0]["verdict"] == FAIL
    with stopped_journal(failed["run"]):
        assert verify_suite(failing, expectations=world["expectations"], run=failed["run"])[
            "suite_outcome"] == "fail"


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
    record = full["records"][(CASE_KEYS[3], 1)]
    # B1: the repetition is the record's journalled slot; a caller cannot relabel it
    for rep in (2, 3):
        invalid(verify(world, record, DevJudge(), repetition=rep, run=full["run"]),
                "repetition_differs_from_journalled_slot")
    # the trial was judged once already (its pass); it is never judged again (audit 6, Y1)
    again = [verify(world, record, DevJudge(), run=full["run"]) for _ in (1, 2)]
    assert all(result["cause"] == "trial_already_judged" for result in again)
    reused = [full["passes"][(CASE_KEYS[3], 1)]] * 3
    assert len({result["trial_id"] for result in reused}) == 1
    assert {result["repetition"] for result in reused} == {1}
    assert all(result["verdict"] == PASS and result["ledger_head"] and result["trial_record_sha256"]
               for result in reused)
    results = [result for (key, _rep), result in full["passes"].items() if key != CASE_KEYS[3]] + reused
    suite = verify_suite(results, expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == INCOMPLETE
    assert {"trial_reused", "duplicate_repetition", "missing_repetition",
            "journalled_trial_not_submitted"} <= set(suite["reasons"])
    # a copy of the record under a fresh trial id does not match its own ledger
    copy = deepcopy(record)
    copy["trial_id"] = copy["run_id"] = "t" + "0" * 32
    invalid(verify(world, copy, DevJudge(), run=full["run"]), "evidence_incomplete")


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
                                                                         max_tokens=2000),
                                         order=order_first(CASE[CASE_KEYS[-1]]))
    other = verify(world, run(world, CASE_KEYS[-1], pre_dispatch=other_pre), DevJudge(), run=other_run)
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
    for profile, error in [(dev_profile(design_id="q01-release-v4"), "profile:does_not_name_this_design"),
                           (dev_profile(schema="q01-independence-profile-4"), "profile:schema")]:
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
    # the pinned (frozen) v7 profile itself establishes nothing
    pinned = (V7 / "independence_profile.json").read_bytes()
    _pre, loaded = release_setup(world, tmp_path / "pinned", profile_bytes=pinned)
    assert loaded.errors == () and loaded.judge_separation_established is False
    # results judged by another judge than run_identity names are not this run's judgement
    stranger = verify(world, full["records"][(CASE_KEYS[4], 3)], DevJudge(identity="another judge"), run=full["run"])
    results = [result for (key, rep), result in full["passes"].items() if (key, rep) != (CASE_KEYS[4], 3)]
    suite = verify_suite([*results, stranger], expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == INCOMPLETE and "judge_differs_from_run_identity" in suite["reasons"]


def test_unseparated_profile_makes_a_would_be_pass_not_judged(world, unseparated):
    suite = verify_suite(passes(unseparated), expectations=world["expectations"], run=unseparated["run"])
    assert suite["suite_outcome"] == NOT_JUDGED and "judge_separation_not_established" in suite["reasons"]
    record = build_suite_record(suite, run=unseparated["run"])
    assert record["judge_separation_established"] is False and record["suite_outcome"] == NOT_JUDGED


# ---------------------------------------------------------------- B1 probes (audit 4): best 3 of N, slots, journal


@pytest.fixture(scope="module")
def cherry(world):
    """A full dev run whose first planned slot (CASE_KEYS[0], 1) genuinely fails (a false rejection)."""
    failing = DevCritic(review=set_finding("Q2", "fail", [("brief.md", "handoff"), ("@candidate", "/handoffs/0/mode")]))
    order = order_first(CASE[CASE_KEYS[0]])
    pre_dispatch, loaded = release_setup(world, world["root"] / "cherry", order=order)
    records, results = {}, {}
    for slot in loaded.identity["planned_slots"]:
        key, rep = KEY[slot["case_id"]], slot["repetition"]
        critic = failing if (key, rep) == (CASE_KEYS[0], 1) else None
        records[(key, rep)] = run(world, key, critic, pre_dispatch=pre_dispatch, repetition=rep)
        results[(key, rep)] = verify(world, records[(key, rep)], DevJudge(), run=loaded)
    assert results[(CASE_KEYS[0], 1)]["verdict"] == FAIL
    assert all(result["verdict"] == PASS for slot, result in results.items() if slot != (CASE_KEYS[0], 1))
    return {"run": loaded, "pre_dispatch": pre_dispatch, "records": records, "results": results}


def test_b1_audit_probe_best_3_of_n_never_passes(world, full):
    """The audit-4 probe as written: 4 trials of one case, one failing; the 3 passing are submitted."""
    key, pre, loaded = CASE_KEYS[0], full["pre_dispatch"], full["run"]
    critic = DevCritic(review=set_finding("Q2", "fail", [("brief.md", "handoff"), ("@candidate", "/handoffs/0/mode")]))
    failing = run(world, key, critic, pre_dispatch=pre, repetition=1)
    # the manifest's journal already holds every planned slot: the harness sends nothing more
    assert (failing["status"], failing["cause"]) == ("invalid", "pre_dispatch_manifest_unverified")
    assert "no_planned_slot_left" in failing["pre_dispatch"]["errors"] and critic.calls == []
    invalid(verify(world, failing, DevJudge(), repetition=1, run=loaded), "trial_pre_dispatch_manifest_unverified")
    good = [run(world, key, pre_dispatch=pre, repetition=rep) for rep in (1, 2, 3)]
    assert all(record["cause"] == "pre_dispatch_manifest_unverified" for record in good)
    good = [verify(world, record, DevJudge(), repetition=rep, run=loaded) for rep, record in zip((1, 2, 3), good)]
    others = [result for (k, _), result in full["passes"].items() if k != key]
    suite = verify_suite(others + good, expectations=world["expectations"], run=loaded)
    assert suite["suite_outcome"] == INCOMPLETE and "journalled_trial_not_submitted" in suite["reasons"]
    record = build_suite_record(suite, run=loaded)
    state = critic_qualification_from_suite(record, record["critic_configuration_digest"])
    assert (state.status, state.reason) == ("unqualified", "suite_incomplete")
    assert len(read_journal(Path(loaded.identity["dispatch_journal"]["path"])).dispatches) == 39


def test_b1_the_harness_refuses_any_slot_but_the_next_planned_one(world, tmp_path):
    key = CASE_KEYS[0]
    pre, loaded = release_setup(world, tmp_path, order=order_first(CASE[key]))
    journal = Path(loaded.identity["dispatch_journal"]["path"])
    critic = DevCritic(review=set_finding("Q2", "fail", [("brief.md", "handoff"), ("@candidate", "/handoffs/0/mode")]))
    first = run(world, key, critic, pre_dispatch=pre, repetition=1)
    assert first["slot"] == {"case_id": CASE[key], "repetition": 1} == first["pre_dispatch"]["slot"]
    assert verify(world, first, DevJudge())["verdict"] == FAIL
    for repetition, error in ((1, "slot_is_not_the_next_planned_slot"), (3, "slot_is_not_the_next_planned_slot"),
                              (4, "repetition_is_not_a_planned_repetition")):
        again = DevCritic()
        record = run(world, key, again, pre_dispatch=pre, repetition=repetition)
        assert (record["status"], again.calls, record["access_log"]) == ("invalid", [], [])
        assert error in record["pre_dispatch"]["errors"]
    other = run(world, CASE_KEYS[1], DevCritic(), pre_dispatch=pre, repetition=1)
    assert "slot_is_not_the_next_planned_slot" in other["pre_dispatch"]["errors"]
    state = read_journal(journal)
    assert state.ok and [entry["trial_id"] for entry in state.dispatches] == [first["trial_id"]]
    assert state.header["manifest_sha256"] == pre.committed_sha256 and state.header["commit_ref"] == COMMIT_REF
    second = run(world, key, pre_dispatch=pre, repetition=2)
    assert second["status"] == "completed" and second["pre_dispatch"]["journal"]["prev_sha256"] == \
        first["pre_dispatch"]["journal"]["entry_sha256"]
    # every frozen call is bound to the trial's journal entry in the durable ledger
    assert verify(world, second, DevJudge())["journal_entry_sha256"] == read_journal(journal).head


def test_b1_cherry_picking_around_a_journalled_failure_is_incomplete(world, cherry, monkeypatch):
    options = {"expectations": world["expectations"], "run": cherry["run"]}
    key = CASE_KEYS[0]
    everything = list(cherry["results"].values())
    assert verify_suite(everything, **options)["suite_outcome"] == FAIL
    # a modified harness that skips the next-slot rule dispatches a 4th trial of the case
    monkeypatch.setattr(q01_harness, "slot_errors", lambda *_args: [])
    fourth = run(world, key, pre_dispatch=cherry["pre_dispatch"], repetition=1)
    assert fourth["status"] == "completed"
    passing = verify(world, fourth, DevJudge(), run=cherry["run"])
    assert passing["verdict"] == PASS and passing["repetition"] == 1
    best = [passing, *(result for slot, result in cherry["results"].items() if slot != (key, 1))]
    suite = verify_suite(best, **options)
    assert suite["suite_outcome"] == INCOMPLETE, suite["reasons"]
    assert {"journalled_trial_not_submitted", "dispatch_journal:unplanned_slot"} <= set(suite["reasons"])
    record = build_suite_record(suite, run=cherry["run"])
    assert record["suite_outcome"] == INCOMPLETE and record["dispatch_journal_head"] is None
    # submitting the failure as well keeps the fail
    assert verify_suite([*everything, passing], **options)["suite_outcome"] == FAIL


def test_b1_a_trial_outside_the_journal_is_not_a_release_trial(world, full, tmp_path):
    """Audit-4 probe: a plain (unjournalled) trial relabelled as a release trial of the manifest."""
    from evals.deeptwin.harness.q01_harness import run_trial

    def carry(cases):  # the plain path reads the lens pack from the case, as a calibration run does
        for case in cases:
            case["source"]["lens_pack"] = deepcopy(DEV_LENS_PACK)

    plain_task, _sha = make_task(tmp_path, carry)
    rig, loaded = world["rig"], full["run"]
    record = run_trial(CASE[CASE_KEYS[0]], DevCritic(), base_dir=rig.base, config=rig.config, task_dir=plain_task)
    assert record["status"] == "completed" and "slot" not in record
    record["pre_dispatch"] = {"manifest_sha256": loaded.manifest_sha256, "errors": []}
    invalid(verify(world, record, DevJudge(), repetition=1, run=loaded), "repetition_differs_from_journalled_slot")
    invalid(verify(world, record, DevJudge(), run=loaded), "not_journalled_under_this_manifest")
    # borrowing the slot and journal entry of a journalled trial does not help
    donor = full["records"][(CASE_KEYS[0], 1)]
    record["slot"], record["pre_dispatch"] = deepcopy(donor["slot"]), deepcopy(donor["pre_dispatch"])
    invalid(verify(world, record, DevJudge(), run=loaded), "not_journalled_under_this_manifest")
    donor_record = deepcopy(donor)
    donor_record["pre_dispatch"]["commit_ref"] = {"kind": "git_commit", "ref": "abcdef1"}
    invalid(verify(world, donor_record, DevJudge(), run=loaded), "commit_ref_differs_from_dispatch_journal")


def test_b1_an_edited_or_truncated_journal_is_refused(world, tmp_path):
    key = CASE_KEYS[1]
    pre, loaded = release_setup(world, tmp_path, order=order_first(CASE[key]))
    records = [run(world, key, pre_dispatch=pre, repetition=rep) for rep in (1, 2)]
    journal = Path(loaded.identity["dispatch_journal"]["path"])
    original = journal.read_bytes()
    assert all(verify(world, record, DevJudge())["verdict"] == PASS for record in records)
    lines = original.splitlines(keepends=True)
    # the last entry relabelled as repetition 3 with its own hash recomputed: the chain still
    # holds, but the entry no longer matches the record or the ledger binding
    entry = json.loads(lines[-1])
    entry["repetition"] = 3
    entry["entry_sha256"] = journal_entry_sha256(entry)
    journal.write_bytes(b"".join(lines[:-1]) + journal_line(entry))
    invalid(verify(world, records[1], DevJudge()), "not_journalled_under_this_manifest")
    journal.write_bytes(b"".join(lines[:-1]))  # the second entry removed
    invalid(verify(world, records[1], DevJudge()), "not_journalled_under_this_manifest")
    edited = original.replace(b'"repetition":1', b'"repetition":2', 1)
    journal.write_bytes(edited)  # an edited entry breaks the hash chain
    assert read_journal(journal).errors == ("journal_chain_broken",)
    invalid(verify(world, records[0], DevJudge()), "dispatch_journal_unverified")
    journal.write_bytes(original[:-5])  # a torn tail
    invalid(verify(world, records[0], DevJudge()), "dispatch_journal_unverified")
    # and the harness refuses to append to a journal that does not verify
    blocked = DevCritic()
    record = run(world, key, blocked, pre_dispatch=pre, repetition=3)
    assert "dispatch_journal:journal_torn_tail" in record["pre_dispatch"]["errors"] and blocked.calls == []
    journal.write_bytes(original)
    # the restored journal verifies again; each trial was judged once already, so a second
    # judging is refused and only a judge-less verification remains possible (audit 6, Y1)
    assert all(verify(world, record)["verdict"] == NOT_JUDGED for record in records)
    assert all(verify(world, record, DevJudge())["cause"] == "trial_already_judged" for record in records)


def test_b1_a_manifest_edited_after_the_first_dispatch_is_not_the_journalled_manifest(world, full):
    """Audit-4 probe: the manifest is edited (and re-hashed) after its trials were dispatched."""
    manifest = json.loads(full["pre_dispatch"].manifest_path.read_bytes())
    manifest["run_identity"]["usd_hard_stop"] = 999.0
    data = as_bytes(manifest)
    edited = load_release_run(data, committed_sha256=hashlib.sha256(data).hexdigest(), profile_bytes=dev_profile())
    assert edited.errors == ()
    suite = verify_suite(passes(full), expectations=world["expectations"], run=edited)
    assert suite["suite_outcome"] == INCOMPLETE
    assert {"unattributable_result", "dispatch_journal:is_for_another_manifest"} <= set(suite["reasons"])
    invalid(verify(world, full["records"][CASE_KEYS[0], 1], DevJudge(), run=edited),
            "not_a_release_trial_of_this_manifest")


def test_b1_planned_slots_are_case_order_times_three(world):
    order = sorted(CASE.values())
    assert planned_slots(order)[:4] == [{"case_id": order[0], "repetition": 1}, {"case_id": order[0], "repetition": 2},
                                        {"case_id": order[0], "repetition": 3}, {"case_id": order[1], "repetition": 1}]
    manifest = dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"])
    for change in (lambda slots: slots.reverse(), lambda slots: slots.pop(), lambda slots: slots.append(slots[0])):
        broken = deepcopy(manifest)
        change(broken["run_identity"]["planned_slots"])
        data = as_bytes(broken)
        assert "planned_slots_are_not_case_order_times_three" in check_pre_dispatch_manifest(
            data, committed_sha256=hashlib.sha256(data).hexdigest()).errors


# ---------------------------------------------------------------- B2 probes (audit 4): a spent set is never rerun


@pytest.mark.parametrize("field,value", [
    ("sealed_dataset_sha256", "dataset"), ("sealed_expectations_sha256", "expectations"),
    ("sealed_dataset_sha256", "expectations"), ("sealed_expectations_sha256", "dataset")])
def test_b2_a_set_spent_by_a_prior_attempt_is_refused(world, tmp_path, field, value):
    """Audit-4 probe: attempt 2 on the set attempt 1 already spent."""
    manifest = dev_manifest(world["expectations"], world["manifest_sha"], rig=world["rig"],
                            task_dir=world["task_dir"], attempt=2, prior=("fail",),
                            order=order_first(CASE[CASE_KEYS[0]]), journal=tmp_path / "journal.jsonl")
    current = {"dataset": world["manifest_sha"], "expectations": world["expectations"].sha256}[value]
    manifest["prior_attempts"][0][field] = current
    data = as_bytes(manifest)
    assert "sealed_set_already_spent_by_a_prior_attempt" in check_pre_dispatch_manifest(
        data, committed_sha256=hashlib.sha256(data).hexdigest()).errors
    pre, loaded = release_setup(world, tmp_path, manifest=manifest)
    assert "manifest:sealed_set_already_spent_by_a_prior_attempt" in loaded.errors
    critic = DevCritic()
    record = run(world, CASE_KEYS[0], critic, pre_dispatch=pre)
    assert record["cause"] == "pre_dispatch_manifest_unverified" and critic.calls == []
    assert not (tmp_path / "journal.jsonl").exists() or not read_journal(tmp_path / "journal.jsonl").dispatches


def test_b2_prior_attempts_carry_their_sets_into_the_suite_record(world, full):
    record = build_suite_record(verify_suite(passes(full), expectations=world["expectations"], run=full["run"]),
                                run=full["run"])
    assert record["prior_sealed_set_sha256s"] == [] and record["attempt"] == 1
    assert record["prior_attempts_sha256"] == hashlib.sha256(b"[]").hexdigest()
    from app.services.critic_qualification import suite_record_sha256
    spent = {**record, "attempt": 2, "prior_outcomes": ["fail"], "prior_sealed_set_sha256s": [record["sealed_set_sha256"]]}
    spent["record_sha256"] = suite_record_sha256(spent)
    with pytest.raises(CriticQualificationError, match="already spent"):
        critic_qualification_from_suite(spent, record["critic_configuration_digest"])
    unlisted = {**record, "attempt": 2, "prior_outcomes": ["fail"]}
    unlisted["record_sha256"] = suite_record_sha256(unlisted)
    with pytest.raises(CriticQualificationError, match="prior attempt"):
        critic_qualification_from_suite(unlisted, record["critic_configuration_digest"])


# ---------------------------------------------------------------- pre-dispatch manifest (schema v3)


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
                   lambda m: m["run_identity"].pop("planned_slots"),
                   lambda m: m["run_identity"].pop("dispatch_journal"),
                   lambda m: m["run_identity"]["dispatch_journal"].update(path="relative/journal.jsonl"),
                   lambda m: m.update(schema="q01-pre-dispatch-manifest-2"),
                   lambda m: m.update(design_id="q01-release-v4")):
        broken = deepcopy(manifest)
        mutate(broken)
        data = as_bytes(broken)
        errors = check_pre_dispatch_manifest(data, committed_sha256=hashlib.sha256(data).hexdigest()).errors
        assert errors and errors[0].startswith("manifest_schema"), errors
    prior = dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"], attempt=2,
                         prior=("fail",))
    prior["prior_attempts"][0].pop("sealed_expectations_sha256")
    data = as_bytes(prior)
    assert check_pre_dispatch_manifest(data, committed_sha256=hashlib.sha256(data).hexdigest()).errors[0].startswith(
        "manifest_schema:/prior_attempts/0")
    assert "manifest_not_strict_json" in check_pre_dispatch_manifest(b"{", committed_sha256="0" * 64).errors
    same = deepcopy(manifest)
    same["attestations"]["reviewer"]["name"] = same["attestations"]["author"]["name"]
    data = as_bytes(same)
    assert "attestation:author_is_reviewer" in check_pre_dispatch_manifest(
        data, committed_sha256=hashlib.sha256(data).hexdigest()).errors


# ---------------------------------------------------------------- N4 probes (audit 4): judge separation


def _manifest_check(manifest):
    data = as_bytes(manifest)
    return check_pre_dispatch_manifest(data, committed_sha256=hashlib.sha256(data).hexdigest()).errors


def test_n4_attestation_names_are_compared_normalized_and_the_sealer_is_not_the_judge(world):
    """Audit-4 probe: the judge as the author in another case, and as the sealer."""
    manifest = dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"])
    manifest["attestations"]["author"]["name"] = "  " + JUDGE_IDENTITY.upper().replace(" ", "   ") + " "
    manifest["attestations"]["sealing"]["name"] = JUDGE_IDENTITY
    errors = _manifest_check(manifest)
    assert {"attestation:judge_is_author_or_reviewer", "attestation:judge_is_sealer"} <= set(errors)
    same = dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"])
    same["attestations"]["reviewer"]["name"] = same["attestations"]["author"]["name"].title()
    assert "attestation:author_is_reviewer" in _manifest_check(same)


@pytest.mark.parametrize("identity", ["{provider}/{model}", "{model}", "judge on {PROVIDER} (another model)",
                                      "  {model_upper}  via proxy"])
def test_n4_a_judge_of_the_critic_provider_or_model_is_refused(world, identity):
    """Audit-4 probe: judge_identity = the critic's provider/model."""
    configuration = dev_configuration(world["rig"], world["task_dir"])
    name = identity.format(provider=configuration["provider"], model=configuration["model"],
                           PROVIDER=configuration["provider"].upper(), model_upper=configuration["model"].upper())
    manifest = dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"])
    manifest["run_identity"]["judge_identity"] = name
    assert "judge:shares_the_critic_provider_or_model" in _manifest_check(manifest)
    profile = json.loads(dev_profile())
    profile["judge_separation"]["judge"]["identity"] = name
    profile_bytes = json.dumps(profile).encode("utf-8")
    manifest["run_identity"]["independence_profile"]["sha256"] = hashlib.sha256(profile_bytes).hexdigest()
    data = as_bytes(manifest)
    loaded = load_release_run(data, committed_sha256=hashlib.sha256(data).hexdigest(), profile_bytes=profile_bytes)
    assert "manifest:judge:shares_the_critic_provider_or_model" in loaded.errors


def test_n4_an_other_provider_judge_needs_a_prompt_digest(world, tmp_path):
    """Audit-4 probe: option other_provider with a null prompt digest."""
    profile = json.loads(dev_profile())
    profile["judge_separation"]["judge"]["prompt_digest"] = None
    profile_bytes = json.dumps(profile).encode("utf-8")
    manifest = dev_manifest(world["expectations"], world["manifest_sha"], rig=world["rig"],
                            task_dir=world["task_dir"], profile_bytes=profile_bytes)
    manifest["run_identity"]["judge_prompt_digest"] = None
    _pre, loaded = release_setup(world, tmp_path / "null", manifest=manifest, profile_bytes=profile_bytes)
    assert "profile:other_provider_judge_without_prompt_digest" in loaded.errors
    assert loaded.judge_separation_established is False
    profile["judge_separation"]["judge"]["option"] = "human_reviewer"  # a named person needs no prompt digest
    profile_bytes = json.dumps(profile).encode("utf-8")
    manifest["run_identity"]["independence_profile"]["sha256"] = hashlib.sha256(profile_bytes).hexdigest()
    _pre, loaded = release_setup(world, tmp_path / "human", manifest=manifest, profile_bytes=profile_bytes)
    assert loaded.errors == () and loaded.judge_separation_established is True


# ---------------------------------------------------------------- lens-effect section (N6)


CHECKLIST_PACK = {"id": "dev-checklist", "version": "1", "rules": [{"id": "dev-check-1", "version": "1"}]}
MIX_PACK = {"id": "dev-mix", "version": "1", "rules": [{"id": "L-P050-01", "version": "1"},
                                                        {"id": "L-P033-02", "version": "1"}]}


def effect_section(world, **changes):
    """A lens-effects-v7 section: every dispatched arm with its own configuration and attempt."""
    base = dev_configuration(world["rig"], world["task_dir"])
    arms = []
    for arm_id, pack in [("no_lens", DEV_LENS_PACK), ("general_multi_perspective", CHECKLIST_PACK),
                         ("mix", MIX_PACK)]:
        configuration = {**base, "lens_refs_and_digests": lens_refs_and_digests(pack)}
        arms.append({"id": arm_id, "critic_configuration": configuration,
                     "critic_configuration_digest": critic_configuration_digest(configuration),
                     "text_sha256": None if arm_id == "no_lens" else lens_refs_and_digests(pack)["pack_sha256"],
                     "attempt": 1, "prior_attempts": []})
    order = [{"arm": arm["id"], "case_id": case_id} for case_id in sorted(CASE.values()) for arm in arms]
    section = {"design_id": "lens-effects-v7", "effect_set_sha256": "5" * 64,
               "qualification_sets": [{"design_id": "q01-release-v7", "sealed_dataset_sha256": "2" * 64,
                                       "sealed_expectations_sha256": "1" * 64}],
               "arms": arms, "arm_case_order": order, "predictions_sha256": "8" * 64}
    for change in changes.values():
        change(section)
    return section


def _repack(arm_index, pack):
    def change(section):
        arm = section["arms"][arm_index]
        arm["critic_configuration"]["lens_refs_and_digests"] = lens_refs_and_digests(pack)
        arm["critic_configuration_digest"] = critic_configuration_digest(arm["critic_configuration"])
        arm["text_sha256"] = lens_refs_and_digests(pack)["pack_sha256"]
    return change


def _spend_arm(section):
    section["arms"][2]["attempt"] = 2
    section["arms"][2]["prior_attempts"] = [prior_attempt(1, "fail", dataset="5" * 64, expectations="0" * 64)]


def _swap_first_block(section):
    order = section["arm_case_order"]
    order[2], order[3] = order[3], order[2]  # one pair of the first case moved into the second block


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
    # audit 4, N6
    (_repack(2, {"id": "dev-mix", "version": "1", "rules": [{"id": "L-P050-01", "version": "1"}]}),
     "lens_effect:mix:lens_rules_do_not_match_the_arm"),
    (_repack(1, {"id": "dev-checklist", "version": "1", "rules": []}),
     "lens_effect:general_multi_perspective:lens_rules_do_not_match_the_arm"),
    (_repack(1, {"id": "dev-checklist", "version": "1", "rules": [{"id": "L-P033-02", "version": "1"}]}),
     "lens_effect:general_multi_perspective:lens_rules_do_not_match_the_arm"),
    (_repack(1, MIX_PACK), "lens_effect:identical_lens_pack_on_different_arms"),
    (_swap_first_block, "lens_effect:arm_case_order_is_not_interleaved_per_case_order"),
    (lambda s: s["arm_case_order"].reverse(), "lens_effect:arm_case_order_is_not_interleaved_per_case_order"),
    (lambda s: s["arms"][0].update(attempt=2, prior_attempts=[
        prior_attempt(1, "pass", dataset="2" * 64, expectations="1" * 64)]),
     "lens_effect:no_lens:baseline_attempt_differs_from_the_run_attempt"),
    # audit 4, B2
    (lambda s: s["qualification_sets"][0].update(sealed_dataset_sha256="5" * 64),
     "lens_effect:effect_set_is_a_qualification_set"),
    (_spend_arm, "lens_effect:mix:sealed_set_already_spent_by_a_prior_attempt"),
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
    journal = read_journal(Path(full["run"].identity["dispatch_journal"]["path"]))
    assert suite["dispatch_journal"] == {"verified": True, "head": journal.head, "entries": 39,
                                         "commit_ref": COMMIT_REF}
    record = build_suite_record(suite, run=full["run"])
    schema = json.loads((V7 / "suite_record.schema.json").read_text(encoding="utf-8"))
    assert Draft202012Validator(schema).is_valid(record) and check_suite_record(record) == []
    assert record["design_id"] == "q01-release-v7" and record["attempt"] == 1 and record["prior_outcomes"] == []
    assert record["critic_configuration_digest"] == critic_configuration_digest(
        dev_configuration(world["rig"], world["task_dir"]))
    assert record["sealed_set_sha256"] == world["manifest_sha"]
    assert record["pre_dispatch_manifest_sha256"] == full["pre_dispatch"].committed_sha256
    assert record["judge_separation_established"] is True and record["v3_error_independence"] == "unverified"
    # N3: the journal head and the manifest's commit reference are in the record
    assert record["dispatch_journal_head"] == journal.head and record["manifest_commit_ref"] == COMMIT_REF
    # audit 5: every critic call and judge answer was provider-reported, and the journal holds no stop
    assert (record["critic_transport_identity"], record["judge_transport_identity"], record["run_stopped"]) == (
        "provider_reported", "provider_reported", False)
    assert all(item["pre_dispatch"]["commit_ref"] == COMMIT_REF for item in full["records"].values())
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
    assert check_suite_record(forged)  # schema: v7 records can only say unverified
    from app.services.critic_qualification import suite_record_sha256
    with pytest.raises(CriticQualificationError, match="record sha256"):
        critic_qualification_from_suite(forged, record["critic_configuration_digest"])
    forged["record_sha256"] = suite_record_sha256(forged)
    # N5 (audit 4): a schema-invalid v7 record is refused, not capped
    with pytest.raises(CriticQualificationError, match="V3 unverified"):
        critic_qualification_from_suite(forged, record["critic_configuration_digest"])
    # an altered suite result is not an issued suite
    for altered in ({**suite, "suite_outcome": "pass", "judge_separation_established": True, "reasons": ["x"]},
                    {**suite, "composition_checked": True, "stopped": False, "dataset_id": "x"}):
        with pytest.raises(ValueError, match="issued by verify_suite"):
            build_suite_record(altered, run=full["run"])


def test_unjudged_dev_suite_is_not_judged(world, full, runs):
    # a run one of whose trials was never attested-judged (its only verification) is not_judged
    unjudged = runs(True, {NOT_JUDGED})
    suite = verify_suite(passes(unjudged), expectations=world["expectations"], run=unjudged["run"])
    assert suite["suite_outcome"] == "not_judged", suite["reasons"]
    # audit 6, Y1: a judged trial re-verified without a judge does not turn into not_judged: its
    # judge log exists, so the judge-less result is refused (a fail cannot be hidden this way)
    results = [verify(world, full["records"][(key, 1)], None, run=full["run"]) for key in CASE_KEYS[:4]]
    assert {result["verdict"] for result in results} == {NOT_JUDGED}
    results += [result for (key, rep), result in full["passes"].items() if not (key in CASE_KEYS[:4] and rep == 1)]
    suite = verify_suite(results, expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == INCOMPLETE and "judge_log_without_a_judging_result" in suite["reasons"]


# ---------------------------------------------------------------- harness pre-dispatch refusal


def release_trial(world, key, pre_dispatch, critic):
    rig = world["rig"]
    rig.critic.target = critic
    return run_release_trial(CASE[key], rig.attested_turn, base_dir=trial_base(world, pre_dispatch), config=rig.config,
                             pre_dispatch=pre_dispatch, task_dir=world["task_dir"])


def test_release_trial_requires_a_pre_dispatch_manifest_with_harness_lens_pack_and_slot(world):
    template = world["pre_dispatch"]
    with pytest.raises(TypeError):
        release_trial(world, ("d-good", None), None, DevCritic())
    with pytest.raises(TypeError):
        PreDispatch(template.manifest_path, template.committed_sha256)
    with pytest.raises(TypeError):  # the slot's repetition and the commit reference are mandatory
        PreDispatch(template.manifest_path, template.committed_sha256, harness_identity(), DEV_LENS_PACK)
    for broken in (dataclasses.replace(template, harness=None), dataclasses.replace(template, lens_pack=None)):
        with pytest.raises(TypeError):
            release_trial(world, ("d-good", None), broken, DevCritic())


def _configured(world, tmp_path, key=("d-good", None), **overrides):
    return dev_manifest(world["expectations"], world["manifest_sha"], rig=world["rig"], task_dir=world["task_dir"],
                        configuration=dev_configuration(world["rig"], world["task_dir"], **overrides),
                        order=order_first(CASE[key]), journal=tmp_path / "journal.jsonl")


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
    ("slot", "slot_is_not_the_next_planned_slot"),
    ("repetition", "repetition_is_not_a_planned_repetition"),
    ("commit_ref", "commit_ref_malformed"),
    ("git_commit_ref", "commit_ref_malformed"),
    ("journal", "dispatch_journal:is_for_another_manifest"),
    ("spent", "sealed_set_already_spent_by_a_prior_attempt"),
])
def test_harness_refuses_dispatch_without_a_verifying_manifest(world, tmp_path, variant, error):
    manifest = _configured(world, tmp_path)
    options = {}
    configuration_changes = {"chains": {"max_proposed_chains": 2},
                             "call_deadline": {"call_and_run_deadlines": {"call_seconds": 99.0, "run_seconds": 60.0}},
                             "run_deadline": {"call_and_run_deadlines": {"call_seconds": 5.0, "run_seconds": 99.0}},
                             "contract": {"parser_version": "other-parser"},
                             "prompt": {"critic_prompt_digest": "1" * 64}}
    if variant in configuration_changes:
        manifest = _configured(world, tmp_path, **configuration_changes[variant])
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
    elif variant == "slot":
        options["repetition"] = 2
    elif variant == "repetition":
        options["repetition"] = 0
    elif variant == "commit_ref":
        options["commit_ref"] = {"kind": "hearsay", "ref": "x"}
    elif variant == "git_commit_ref":
        options["commit_ref"] = {"kind": "git_commit", "ref": "not a commit id"}
    elif variant == "journal":  # the manifest's journal already belongs to another manifest
        other_pre, _other = release_setup(world, tmp_path / "other", manifest=_configured(world, tmp_path,
                                                                                          max_tokens=7))
        (tmp_path / "trials").mkdir(exist_ok=True)  # the shared trial base both manifests name
        assert run(world, ("d-good", None), pre_dispatch=other_pre)["status"] == "completed"
    elif variant == "spent":
        manifest["attempt"] = 2
        manifest["prior_attempts"] = [prior_attempt(1, "incomplete", dataset=world["manifest_sha"])]
    pre_dispatch, _loaded = release_setup(world, tmp_path, manifest=manifest, **options)
    critic = DevCritic()
    record = release_trial(world, ("d-good", None), pre_dispatch, critic)
    assert (record["status"], record["cause"]) == ("invalid", "pre_dispatch_manifest_unverified")
    assert error in record["pre_dispatch"]["errors"], record["pre_dispatch"]["errors"]
    assert critic.calls == [] and record["calls"] == [] and record["access_log"] == []  # nothing read or sent
    assert record["pre_dispatch"]["journal"] is None
    invalid(verify(world, record, DevJudge()), "trial_pre_dispatch_manifest_unverified")


def test_harness_dispatches_with_a_verifying_manifest(world, tmp_path):
    pre_dispatch, _loaded = release_setup(world, tmp_path, order=order_first(CASE[("d-q3", None)]))
    record = run(world, ("d-q3", None), pre_dispatch=pre_dispatch)
    assert record["status"] == "completed" and record["pre_dispatch"]["errors"] == []
    assert record["pre_dispatch"]["manifest_sha256"] == pre_dispatch.committed_sha256
    assert record["pre_dispatch"]["environment_manifest_sha256"] == world["manifest_sha"]
    assert record["pre_dispatch"]["harness"] == harness_identity()
    assert record["pre_dispatch"]["unchecked_configuration_fields"] == ["max_tokens"]
    assert record["pre_dispatch"]["journal"]["seq"] == 1 and record["slot"]["repetition"] == 1
    assert verify(world, record, DevJudge())["verdict"] == PASS


def test_harness_checks_the_selection_at_every_call(world, tmp_path):
    pre_dispatch, _loaded = release_setup(world, tmp_path, manifest=_configured(world, tmp_path, key=("d-q3", None),
                                                                                model="another-model"))
    critic = DevCritic()
    record = release_trial(world, ("d-q3", None), pre_dispatch, critic)
    assert (record["status"], record["cause"]) == ("invalid", "selection_differs_from_configuration")
    assert critic.calls == []


def test_n1_the_verifier_rederives_the_selection_from_the_ledger(world, monkeypatch, tmp_path):
    """Audit-4 probe: a modified harness that skips the model check; the manifest claims another model."""
    claimed = dev_configuration(world["rig"], world["task_dir"], model="claimed-stronger-model", effort="max")
    pre, claimed_run = release_setup(world, tmp_path / "claimed", configuration=claimed,
                                     order=order_first(CASE[CASE_KEYS[0]]))
    assert claimed_run.errors == ()
    actual = dev_configuration(world["rig"], world["task_dir"])
    real = q01_harness.pre_dispatch_errors

    def patched(pre_dispatch, case_id, config, task_dir=q01_harness.TASK_DIR, base_dir=None, transport=None):
        info, _errors, _configuration = real(pre_dispatch, case_id, config, task_dir, base_dir, transport)
        return dict(info, errors=[]), [], actual

    monkeypatch.setattr(q01_harness, "pre_dispatch_errors", patched)
    record = run(world, CASE_KEYS[0], pre_dispatch=pre)
    assert record["status"] == "completed"
    invalid(verify(world, record, DevJudge(), run=claimed_run), "selection_differs_from_configuration")


def test_n2_proposed_not_driven_must_follow_the_chain_limit(world):
    record = run(world, ("d-alt", None))
    assert verify(world, record, DevJudge())["verdict"] == PASS
    for value in (1, -1, "0"):
        copy = deepcopy(record)
        copy["stages"]["proposed_not_driven"] = value
        invalid(verify(world, copy, DevJudge()), "proposed_not_driven_differs_from_chain_limit")


# ---------------------------------------------------------------- BF3 / N7 probes: the lens pack is configuration


def test_bf3_a_sealed_bundle_carrying_a_lens_pack_is_refused(world, tmp_path):
    def carry(cases):
        for case in cases:
            case["source"]["lens_pack"] = deepcopy(DEV_LENS_PACK)
    task_dir, sha = make_task(tmp_path / "carry", carry)
    with pytest.raises(SealedSetError, match="lens pack"):
        load_sealed_materials_dir(task_dir, sha)
    pre_dispatch, _loaded = release_setup(world, tmp_path / "carry-run", manifest_sha=sha, task_dir=task_dir,
                                          order=order_first(CASE[("d-good", None)]))
    critic = DevCritic()
    record = run(world, ("d-good", None), critic, task_dir=task_dir, pre_dispatch=pre_dispatch)
    assert (record["status"], record["cause"]) == ("invalid", "sealed_case_carries_a_lens_pack")
    assert critic.calls == [] and record["calls"] == []


@pytest.mark.parametrize("where", ["source.lens_rules", "source.lenses", "candidate.lens_pack",
                                   "candidate.roles.0.lens", "counterexample.lens_pack"])
def test_n7_a_lens_pack_hidden_under_another_key_is_refused(world, tmp_path, where):
    """Audit-4 probe: a lens pack under a key the input contract silently drops."""
    def hide(cases):
        for case in cases:
            source = case["source"]
            if where.startswith("source."):
                source[where.split(".")[1]] = deepcopy(DEV_LENS_PACK)
            elif where == "candidate.lens_pack":
                source["candidate"]["lens_pack"] = deepcopy(DEV_LENS_PACK)
            elif where == "candidate.roles.0.lens":
                source["candidate"]["roles"][0]["lens"] = deepcopy(DEV_LENS_PACK)
            else:
                for item in case["authored_counterexamples"]:
                    item["counterexample"]["lens_pack"] = deepcopy(DEV_LENS_PACK)
    task_dir, sha = make_task(tmp_path / "hide", hide)
    with pytest.raises(SealedSetError, match="allowlist|input contract drops"):
        load_sealed_materials_dir(task_dir, sha)
    if where.startswith("source."):
        pre_dispatch, _loaded = release_setup(world, tmp_path / "hide-run", manifest_sha=sha, task_dir=task_dir,
                                              order=order_first(CASE[("d-good", None)]))
        critic = DevCritic()
        record = run(world, ("d-good", None), critic, task_dir=task_dir, pre_dispatch=pre_dispatch)
        assert (record["status"], record["cause"]) == ("invalid", "sealed_case_source_keys_not_allowlisted")
        assert critic.calls == []


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
    assert identity["version"] == "q01-sealed-verifier-5"
    assert {"app/critic_contract.py", "app/critic_audit.py"} <= set(sc.VERIFIER_FILES)
    files = {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() for relative in sc.VERIFIER_FILES}
    assert identity["sha256"] == hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"))
                                                .encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- X1 (audit 5): provider-attested critic transport


def _ledger_details(record):
    return [call["ledger"]["details"] for call in record["calls"]]


def test_x1_release_calls_carry_the_identity_the_provider_reported(world):
    """Every call of a release trial records the served model and request id of the provider response."""
    record = run(world, ("d-good", None))
    assert record["status"] == "completed" and record["model_identity"] == "provider_reported"
    for details, call in zip(_ledger_details(record), record["calls"]):
        assert details["model_identity"] == "provider_reported"
        assert details["served_model"] == world["rig"].choice["model"] == call["manifest"]["served_model"]
        assert details["provider_request_id"].startswith("req_q01mock")
        assert details["provider_message_id"].startswith("msg_q01mock")
    result = verify(world, record, DevJudge())
    assert result["verdict"] == PASS and result["critic_transport_identity"] == "provider_reported"


def test_x1_audit_probe_g_a_scripted_transport_never_completes_a_release_trial(world, monkeypatch):
    """Audit-5 probe G: a turn that ignores the configured model (any scripted oracle) is refused."""
    critic = DevCritic()
    record = run(world, ("d-good", None), critic, scripted=True)
    assert (record["status"], record["cause"]) == ("invalid", "transport_identity_unattested")
    assert record["model_identity"] == "selection_declared_not_transport_reported"
    assert len(critic.calls) == 1  # the first completed call was unattested: nothing further was sent
    invalid(verify(world, record, DevJudge()), "transport_identity_unattested")
    # a modified harness that skips its check: the verifier re-derives the identity from the ledger
    monkeypatch.setattr(q01_harness, "transport_identity_errors", lambda *_args: [])
    record = run(world, ("d-good", None), DevCritic(), scripted=True)
    assert record["status"] == "completed"
    assert all("model_identity" not in details for details in _ledger_details(record))
    result = verify(world, record, DevJudge())
    invalid(result, "transport_identity_unattested")
    assert result["critic_transport_identity"] == "not_attested"


def test_x1_a_provider_that_reports_no_request_id_is_unattested(world, tmp_path):
    rig = dev_rig(tmp_path, request_ids=False)
    record = run(world, ("d-alt", None), rig=rig)
    assert (record["status"], record["cause"]) == ("invalid", "transport_identity_unattested")
    invalid(verify(world, record, DevJudge()), "transport_identity_unattested")


def test_x1_a_provider_serving_another_model_is_refused(world, tmp_path):
    # the product adapter refuses a served model other than the requested one before any text is used
    rig = dev_rig(tmp_path, served_model=world["rig"].choice["model"] + "-other-snapshot")
    record = run(world, ("d-alt", None), rig=rig)
    assert (record["status"], record["cause"]) == ("invalid", "transport_or_fixture_error")
    invalid(verify(world, record, DevJudge()), "trial_transport_or_fixture_error")


def test_x1_a_reply_attesting_another_model_is_refused_and_the_check_is_exact(world):
    """A transport whose ProviderReply names another served model is refused by the runner."""
    model = world["rig"].choice["model"]

    def other(system, user):
        return ProviderReply(DevCritic()(system, user), served_model=model + "-snapshot",
                             provider_request_id="req_0123456789")

    record = run(world, ("d-alt", None), other, scripted=True)
    assert (record["status"], record["cause"]) == ("invalid", "transport_contract_or_model_mismatch")
    # the harness check itself is exact: another snapshot or alias of the model is a mismatch
    reported = {"model_identity": "provider_reported", "provider_request_id": "req_0123456789",
                "provider_message_id": "msg_0123456789"}
    configuration = dev_configuration(world["rig"], world["task_dir"])
    assert q01_harness.transport_identity_errors({**reported, "served_model": model}, configuration) == []
    for served in (model + "-20260101", model.upper(), None):
        assert q01_harness.transport_identity_errors({**reported, "served_model": served}, configuration) == [
            "transport_identity_unattested"]
    assert q01_harness.transport_identity_errors({"served_model": model}, configuration) == [
        "transport_identity_unattested"]


# ---------------------------------------------------------------- X1 (audit 5): attested judge answers


def test_x1_a_judge_that_only_declares_its_identity_judges_nothing(world, runs):
    record = run(world, CASE_KEYS[0])
    judge = DeclaredJudge()
    result = verify(world, record, judge)
    assert (result["verdict"], result["cause"]) == (NOT_JUDGED, "semantic_items_not_judged")
    assert {item["attestation"] for item in result["judge_items"]} == {"self_declared"}
    assert result["judge_transport_identity"] == "not_attested" and result["judge_log"] is None
    assert judge.items == []  # nothing was asked, so no judge log was opened
    # the not_judged variant run: one slot verified with a judge that only declares its identity
    declared = runs(True, {NOT_JUDGED})
    suite = verify_suite(passes(declared), expectations=world["expectations"], run=declared["run"])
    assert suite["suite_outcome"] == NOT_JUDGED and suite["judge_transport_identity"] == "not_attested"
    assert build_suite_record(suite, run=declared["run"])["judge_transport_identity"] == "not_attested"


@pytest.mark.parametrize("judge,verdict,cause", [
    (lambda: DevJudge(request_ids=False), NOT_JUDGED, "semantic_items_not_judged"),
    (lambda: DevJudge(served_model=None), NOT_JUDGED, "semantic_items_not_judged"),
    (lambda: DevJudge(served_model="another-judge-model"), INVALID, "judge_identity_mismatch"),
    (lambda: DevJudge(raw="I think it is supported."), INVALID, "judge_fault"),
    # the verdict is re-derived from the raw provider reply, never taken from the judge object
    (lambda: DevJudge(raw=json.dumps({"verdict": "not_supported", "reason": "raw"})), FAIL, "semantic_judgement"),
], ids=["no_request_id", "no_served_model", "other_model", "malformed_reply", "raw_reply_decides"])
def test_x1_judge_answers_count_only_with_the_judge_providers_reported_identity(world, judge, verdict, cause):
    result = verify(world, run(world, CASE_KEYS[3]), judge())  # a fresh trial, judged once
    assert (result["verdict"], result["cause"]) == (verdict, cause)


def test_x1_raw_judge_responses_are_durable_beside_the_trial(world):
    record = run(world, CASE_KEYS[4])
    result = verify(world, record, DevJudge())
    assert result["verdict"] == PASS and result["judge_transport_identity"] == "provider_reported"
    log = Path(result["judge_log"]["path"])
    assert log == Path(record["ledger_path"]).parent.parent / "judge-responses.jsonl"
    assert log == sc.judge_log_path(RUNS[record["trial_id"]], record["trial_id"])
    lines = [json.loads(line) for line in log.read_bytes().splitlines()]
    # one judging: the opening line, then one answer per judged item, nothing else (audit 6, Y1)
    assert lines[0]["kind"] == "judging_opened" and lines[0]["trial_id"] == record["trial_id"]
    assert lines[0]["items"] == [item["id"] for item in result["judge_items"]]
    mine = lines[1:]
    assert result["judge_log"]["lines"] == len(lines) and result["judge_log"]["lines_sha256"] == hashlib.sha256(
        json.dumps(lines, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    assert len(mine) == len(result["judge_items"]) and {line["kind"] for line in mine} == {"answer"}
    for item, line in zip(result["judge_items"], mine):
        assert item["id"] == line["item_id"] and item["served_model"] == line["served_model"] == JUDGE_MODEL
        assert item["raw_response_sha256"] == hashlib.sha256(line["raw_response"].encode("utf-8")).hexdigest()
        assert item["provider_request_id"] == line["provider_request_id"]


def test_x1_a_run_without_a_judge_model_judges_nothing(world, tmp_path):
    manifest = dev_manifest(world["expectations"], world["manifest_sha"], rig=world["rig"],
                            task_dir=world["task_dir"], order=order_first(CASE[CASE_KEYS[2]]),
                            journal=tmp_path / "journal.jsonl")
    manifest["run_identity"]["judge_model"] = None
    pre, loaded = release_setup(world, tmp_path, manifest=manifest)
    assert loaded.errors == ()
    result = verify(world, run(world, CASE_KEYS[2], pre_dispatch=pre), DevJudge(), run=loaded)
    assert (result["verdict"], result["cause"]) == (NOT_JUDGED, "semantic_items_not_judged")


def test_x1_claude_judge_reports_the_judge_providers_identity(tmp_path):
    """The release judge path over the rig: served model and request id come from the provider response."""
    from evals.deeptwin.verifiers.claude_judge import ClaudeJudge
    from evals.deeptwin.verifiers.q01_core import JudgeItem, parse_judge_reply

    rig = attested_rig(tmp_path)
    turn = rig.make_turn(model=rig.model_id, effort="medium", max_tokens=256, role="judge", agent="q01-judge",
                         attested=True)
    judge = ClaudeJudge(turn, model_id=rig.model_id, identity="dev judge")
    answer = judge.judge_attested(JudgeItem("i1", "Is it supported?", "{}", "[]"))
    assert type(answer) is AttestedJudgement and answer.served_model == rig.model_id
    assert answer.provider_request_id.startswith("req_q01mock") and answer.provider_message_id.startswith("msg_")
    assert parse_judge_reply(answer.raw_response)[0] == "supported"
    plain = ClaudeJudge(rig.turn, model_id=rig.model_id).judge_attested(JudgeItem("i2", "?", "{}", "[]"))
    assert (plain.served_model, plain.provider_request_id) == (None, None)


# ---------------------------------------------------------------- audit 5, non-blocking 1: the trial base directory


def test_a5_1_audit_probe_a_a_restored_journal_backup_is_detectable(world, tmp_path):
    """Audit-5 probe A: back up the journal, run slot 1 (fails), restore the backup, rerun every slot."""
    pre, loaded = release_setup(world, tmp_path, order=order_first(CASE[CASE_KEYS[0]]))
    journal = Path(loaded.identity["dispatch_journal"]["path"])
    failing = DevCritic(review=set_finding("Q2", "fail", [("brief.md", "handoff"), ("@candidate", "/handoffs/0/mode")]))
    bad = run(world, CASE_KEYS[0], failing, pre_dispatch=pre, repetition=1)
    assert verify(world, bad, DevJudge(), run=loaded)["verdict"] == FAIL
    journal.write_bytes(journal.read_bytes().splitlines(keepends=True)[0])  # the header-only backup
    results = []
    for slot in loaded.identity["planned_slots"]:
        record = run(world, KEY[slot["case_id"]], pre_dispatch=pre, repetition=slot["repetition"])
        results.append(verify(world, record, DevJudge(), run=loaded))
    assert all(result["verdict"] == PASS for result in results)
    suite = verify_suite(results, expectations=world["expectations"], run=loaded)
    assert suite["suite_outcome"] == INCOMPLETE
    assert "trial_base_dir:trial_not_in_dispatch_journal" in suite["reasons"]
    record = build_suite_record(suite, run=loaded)
    state = critic_qualification_from_suite(record, record["critic_configuration_digest"])
    assert (state.status, state.reason) == ("unqualified", "suite_incomplete")


def test_a5_1_the_harness_refuses_any_other_base_directory(world, tmp_path):
    pre, loaded = release_setup(world, tmp_path, order=order_first(CASE[CASE_KEYS[1]]))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    critic = DevCritic()
    world["rig"].critic.target = critic
    record = run_release_trial(CASE[CASE_KEYS[1]], world["rig"].attested_turn, base_dir=elsewhere,
                               config=world["rig"].config, pre_dispatch=pre, task_dir=world["task_dir"])
    assert (record["status"], record["cause"]) == ("invalid", "pre_dispatch_manifest_unverified")
    assert "trial_base_dir_differs_from_manifest" in record["pre_dispatch"]["errors"] and critic.calls == []
    journal = Path(loaded.identity["dispatch_journal"]["path"])
    assert not journal.exists() or not read_journal(journal).dispatches


def test_a5_1_stray_or_unreadable_trial_directories_are_reported(world, full):
    base = Path(full["run"].identity["trial_base_dir"]["path"])
    stray = base / ("t" + "e" * 32)
    stray.mkdir()
    try:
        suite = verify_suite(passes(full), expectations=world["expectations"], run=full["run"])
        assert suite["suite_outcome"] == INCOMPLETE
        assert "trial_base_dir:trial_directory_without_record" in suite["reasons"]
        (stray / "trial-record.json").write_bytes(b"{not json")
        suite = verify_suite(passes(full), expectations=world["expectations"], run=full["run"])
        assert "trial_base_dir:unreadable_trial_record" in suite["reasons"]
    finally:
        shutil.rmtree(stray)
    assert verify_suite(passes(full), expectations=world["expectations"], run=full["run"])["suite_outcome"] == PASS


# ---------------------------------------------------------------- audit 5, non-blocking 3: spent cases


def test_a5_3_audit_probe_c_a_re_serialized_spent_set_is_refused(world, tmp_path):
    """Audit-5 probe C: the spent set's cases under a re-serialized environment manifest."""
    env = Path(world["task_dir"]) / "environment" / "manifest.json"
    re_serialized = (json.dumps(json.loads(env.read_bytes()), indent=3) + "\n").encode("utf-8")
    new_sha = hashlib.sha256(re_serialized).hexdigest()
    assert new_sha != world["manifest_sha"]
    spent = environment_case_shas(world["task_dir"])
    manifest = dev_manifest(world["expectations"], new_sha, rig=world["rig"], task_dir=world["task_dir"], attempt=2,
                            prior=("fail",), journal=tmp_path / "journal.jsonl")
    manifest["prior_attempts"][0].update(sealed_dataset_sha256=world["manifest_sha"],
                                         sealed_expectations_sha256="5" * 64, case_ids=sorted(spent),
                                         case_sha256s=sorted(spent.values()))
    errors = _manifest_check(manifest)
    assert {"case_id_already_spent_by_a_prior_attempt", "case_sha256_already_spent_by_a_prior_attempt"} <= set(errors)
    assert "sealed_set_already_spent_by_a_prior_attempt" not in errors  # the set digests alone would not catch it
    # one spent case (by id or by file digest) is enough
    for name, value in (("case_ids", [sorted(spent)[3]]), ("case_sha256s", [sorted(spent.values())[5]])):
        partial = deepcopy(manifest)
        partial["prior_attempts"][0].update(case_ids=["q01-0000000000"], case_sha256s=["0" * 64])
        partial["prior_attempts"][0][name] = value
        assert any(error.endswith("_already_spent_by_a_prior_attempt") for error in _manifest_check(partial))


def test_a5_3_sealed_case_digests_must_be_the_bundles(world, tmp_path):
    manifest = dev_manifest(world["expectations"], world["manifest_sha"], rig=world["rig"],
                            task_dir=world["task_dir"], order=order_first(CASE[CASE_KEYS[0]]),
                            journal=tmp_path / "journal.jsonl")
    first = next(iter(manifest["run_identity"]["sealed_case_sha256s"]))
    manifest["run_identity"]["sealed_case_sha256s"][first] = "0" * 64  # would hide a spent case digest
    pre, _loaded = release_setup(world, tmp_path, manifest=manifest)
    critic = DevCritic()
    record = run(world, CASE_KEYS[0], critic, pre_dispatch=pre)
    assert "environment_differs_from_sealed_case_sha256s" in record["pre_dispatch"]["errors"] and critic.calls == []
    missing = deepcopy(manifest)
    missing["run_identity"]["sealed_case_sha256s"].pop(first)
    assert "sealed_case_sha256s_do_not_match_case_order" in _manifest_check(missing)


# ---------------------------------------------------------------- audit 5, non-blocking 6: provider family aliases


@pytest.mark.parametrize("judge,provider,model", [
    ("Claude Opus judge", "anthropic", "claude-sonnet-4"),
    ("claude/api opus-4", "claude/api", "claude-sonnet-4-5"),
    ("ClaudeAPI-opus", "claude/api", "claude-sonnet-4-5"),
    ("Anthropic judge", "claude/api", "claude-sonnet-4-5"),
    ("gpt-5 via openai", "codex", "gpt-5"),
    ("GPT 5 via OpenAI", "codex", "gpt-5"),
    ("codex-subscription gpt5", "codex/subscription", "gpt-5.1"),
    ("Gemini reviewer", "google", "gemini-2.5-pro"),
    ("a sonnet judge", "claude", "claude-opus-5"),
])
def test_a5_6_audit_probe_f_judge_family_aliases_are_refused(judge, provider, model):
    """Audit-5 probe F: the judge names the critic's family by an alias the old token check missed."""
    assert judge_shares_critic(judge, {"provider": provider, "model": model})


def test_a5_6_the_judge_model_is_checked_and_other_families_pass(world):
    configuration = {"provider": "claude", "model": "claude-opus-5"}
    assert judge_shares_critic("neutral judge", configuration, "claude-haiku-4")
    assert not judge_shares_critic("neutral judge", configuration, "gpt-5")
    assert not judge_shares_critic(JUDGE_IDENTITY, configuration, JUDGE_MODEL)
    assert set(PROVIDER_FAMILIES) >= {"anthropic", "openai", "google"}
    manifest = dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"])
    manifest["run_identity"]["judge_model"] = "Claude-Sonnet-9"
    assert "judge:shares_the_critic_provider_or_model" in _manifest_check(manifest)


# ---------------------------------------------------------------- audit 5, non-blocking 7: the stop is journalled


def test_a5_7_the_stop_is_a_journal_entry_not_a_caller_flag(world, full, tmp_path):
    with pytest.raises(TypeError):
        verify_suite(passes(full), expectations=world["expectations"], run=full["run"], stopped=True)
    assert verify_suite(passes(full), expectations=world["expectations"], run=full["run"])["stopped"] is False
    with stopped_journal(full["run"]):
        suite = verify_suite(passes(full), expectations=world["expectations"], run=full["run"])
        assert suite["suite_outcome"] == INCOMPLETE and "run_stopped" in suite["reasons"] and suite["stopped"]
        record = build_suite_record(suite, run=full["run"])
        assert record["run_stopped"] is True and record["suite_outcome"] == INCOMPLETE
    # the dispatcher writes the stop through the harness; nothing is dispatched after it
    pre, loaded = release_setup(world, tmp_path, order=order_first(CASE[CASE_KEYS[5]]))
    assert run(world, CASE_KEYS[5], pre_dispatch=pre)["status"] == "completed"
    entry, errors = q01_harness.journal_stop(pre, "usd_hard_stop reached")
    assert errors == [] and entry["kind"] == "stop" and entry["seq"] == 2
    critic = DevCritic()
    record = run(world, CASE_KEYS[5], critic, pre_dispatch=pre, repetition=2)
    assert "dispatch_journal:run_stopped" in record["pre_dispatch"]["errors"] and critic.calls == []
    path = Path(loaded.identity["dispatch_journal"]["path"])
    state = read_journal(path)
    assert state.ok and state.stopped and len(state.dispatches) == 1
    assert q01_harness.journal_stop(pre, "again")[1] == ["dispatch_journal:run_stopped"]
    # an entry after the stop breaks the journal
    extra = {"seq": 3, "kind": "dispatch", "trial_id": "t" + "0" * 32, "case_id": CASE[CASE_KEYS[5]],
             "repetition": 2, "prev": state.head}
    extra["entry_sha256"] = journal_entry_sha256(extra)
    path.write_bytes(path.read_bytes() + journal_line(extra))
    assert read_journal(path).errors == ("journal_entry_after_stop",)


# ---------------------------------------------------------------- audit 6 (of release-v6): one judging, distinct ids


def _judge_log_lines(result):
    return [json.loads(line) for line in Path(result["judge_log"]["path"]).read_bytes().splitlines()]


def test_a6_every_trial_of_the_dev_run_was_judged_exactly_once(world, full):
    """Audit-6 finding on the repo's own fixture: no result of the passing run is a re-judging."""
    suite = verify_suite(passes(full), expectations=world["expectations"], run=full["run"])
    assert suite["suite_outcome"] == PASS
    for result in passes(full):
        lines = _judge_log_lines(result)
        assert [line["kind"] for line in lines].count("judging_opened") == 1
        assert lines[0]["trial_id"] == result["trial_id"]
    record = build_suite_record(suite, run=full["run"])
    assert record["judge_logs"] == sorted(({"trial_id": r["trial_id"], "lines_sha256": r["judge_log"]["lines_sha256"]}
                                           for r in passes(full)), key=lambda item: item["trial_id"])
    ids = sorted(value for r in passes(full) for values in r["provider_ids"].values() for value in values)
    assert len(ids) == len(set(ids)) == record["provider_id_count"]
    assert record["provider_ids_sha256"] == hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def test_a6_p1_audit_probe_a_judge_reroll_is_refused(world, runs):
    """Audit-6 probe P1: a trial judged not_supported (FAIL) is re-verified until supported."""
    failed = runs(True, {FAIL, INVALID, NOT_JUDGED})
    record = failed["records"][VARIANT_SLOTS[FAIL]]
    first = failed["variants"][FAIL]
    assert first["verdict"] == FAIL
    before = Path(first["judge_log"]["path"]).read_bytes()
    judge = DevJudge()
    reroll = verify(world, record, judge, run=failed["run"])
    invalid(reroll, "trial_already_judged")
    assert judge.items == [] and judge.answers == 0  # the judge was never asked
    assert Path(first["judge_log"]["path"]).read_bytes() == before
    options = {"expectations": world["expectations"], "run": failed["run"]}
    rerolled = [reroll if result is first else result for result in passes(failed)]
    suite = verify_suite(rerolled, **options)
    assert suite["suite_outcome"] == INCOMPLETE and "judge_log_without_a_judging_result" in suite["reasons"]
    assert verify_suite(passes(failed), **options)["suite_outcome"] == FAIL


def test_a6_p1_a_faulting_judge_leaves_its_judging_and_blocks_a_second(world):
    record = run(world, CASE_KEYS[1])
    faulted = verify(world, record, DevJudge(q7=RuntimeError("judge down")))
    invalid(faulted, "judge_fault")
    lines = _judge_log_lines(faulted)
    assert lines[0]["kind"] == "judging_opened"
    assert lines[-1] == {"kind": "fault", "item_id": lines[-1]["item_id"], "cause": "judge_fault"}
    invalid(verify(world, record, DevJudge()), "trial_already_judged")


def test_a6_p1_a_copied_ledger_cannot_open_a_second_judge_log(world, tmp_path):
    record = run(world, CASE_KEYS[2])
    assert verify(world, record, DevJudge())["verdict"] == PASS
    trial_dir = Path(record["ledger_path"]).parent.parent
    copy_dir = tmp_path / record["trial_id"]
    shutil.copytree(trial_dir, copy_dir)
    (copy_dir / "judge-responses.jsonl").unlink()
    moved = {**record, "ledger_path": str(copy_dir / "audit" / "eval.sqlite3")}
    invalid(verify(world, moved, DevJudge()), "evidence_outside_trial_base_dir")
    invalid(verify(world, record, DevJudge(), ledger_path=copy_dir / "audit" / "eval.sqlite3"),
            "evidence_outside_trial_base_dir")


def _hand_built(model, ids):
    """A scripted critic wrapped in hand-built ProviderReply objects with the ids ``ids()`` gives."""
    critic = DevCritic()

    def turn(system, user):
        request_id, message_id = ids()
        return ProviderReply(critic(system, user), served_model=model, provider_request_id=request_id,
                             provider_message_id=message_id)
    return turn


def test_a6_p2_audit_probe_one_request_id_for_every_call_is_refused(world):
    """Audit-6 probe P2: one request id (and message id) for every call of the trial."""
    turn = _hand_built(world["rig"].choice["model"], lambda: ("req_REUSED0001", "msg_REUSED0001"))
    record = run(world, ("d-good", None), turn, scripted=True)
    assert record["status"] == "completed"  # the harness sees well-formed ids on each call
    invalid(verify(world, record, DevJudge()), "provider_id_reused")


def test_a6_p2_ids_reused_across_trials_make_the_suite_incomplete(world, tmp_path):
    key = CASE_KEYS[0]
    pre, loaded = release_setup(world, tmp_path, order=order_first(CASE[key]))
    results = []
    for rep in (1, 2):
        counter = itertools.count(1)  # every trial restarts its ids: distinct within, reused across

        def ids(counter=counter):
            number = next(counter)
            return f"req_TRIALID{number:04d}", f"msg_TRIALID{number:04d}"
        turn = _hand_built(world["rig"].choice["model"], ids)
        record = run(world, key, turn, pre_dispatch=pre, repetition=rep, scripted=True)
        results.append(verify(world, record, DevJudge(), run=loaded))
    assert [result["verdict"] for result in results] == [PASS, PASS]
    suite = verify_suite(results, expectations=world["expectations"], run=loaded)
    assert suite["suite_outcome"] == INCOMPLETE and "provider_id_reused_across_suite" in suite["reasons"]


@pytest.mark.parametrize("request_id,message_id", [("x", "msg_0123456789"), ("msg_0123456789", "msg_abcdefghij"),
                                                   ("req_0123456789", None), ("req_0123456789", "x")])
def test_a6_p2b_ids_outside_the_adapters_forms_are_refused(world, monkeypatch, request_id, message_id):
    """Audit-6 probe P2b: a request id 'x', a non-req id, no message id, a non-msg message id."""
    import re

    import app.critic_trial as critic_trial

    turn = _hand_built(world["rig"].choice["model"], lambda: (request_id, message_id))
    record = run(world, ("d-good", None), turn, scripted=True)
    assert record["status"] == "invalid"
    assert record["cause"] in {"transport_contract_or_model_mismatch", "transport_identity_unattested"}
    # with the runner's and the harness's checks bypassed, the verifier still refuses the ids
    monkeypatch.setattr(critic_trial, "_REQUEST_ID", re.compile(r".+\Z"))
    monkeypatch.setattr(q01_harness, "transport_identity_errors", lambda *_args: [])
    record = run(world, ("d-good", None), _hand_built(world["rig"].choice["model"], lambda: (request_id, message_id)),
                 scripted=True)
    assert record["status"] == "completed"
    invalid(verify(world, record, DevJudge()), "transport_identity_unattested")


class SpoofJudge:
    """A judge that answers 'supported' with a stub provider identity of the caller's choosing."""

    version, identity, prompt_digest = "spoof", JUDGE_IDENTITY, JUDGE_PROMPT_DIGEST

    def __init__(self, ids):
        self.ids = ids

    def judge_attested(self, _item):
        return AttestedJudgement(json.dumps({"verdict": "supported", "reason": "."}), JUDGE_MODEL, self.ids(), None)


def test_a6_p4_audit_probe_a_judge_spoof_with_a_reused_request_id(world, tmp_path):
    """Audit-6 probe P4: every judge answer carries the same request id."""
    record = run(world, ("d-good", None))
    result = verify(world, record, SpoofJudge(lambda: "req_SAMEID0001"))
    invalid(result, "provider_id_reused")
    assert _judge_log_lines(result)[-1]["cause"] == "provider_id_reused"
    # the probe's own id ('req_SAME', too short for the adapter's form) is not an attestation at all
    result = verify(world, run(world, ("d-good", None)), SpoofJudge(lambda: "req_SAME"))
    assert (result["verdict"], result["judge_transport_identity"]) == (NOT_JUDGED, "not_attested")
    # distinct within each trial but reused across trials: the suite is incomplete
    key = CASE_KEYS[0]
    pre, loaded = release_setup(world, tmp_path, order=order_first(CASE[key]))
    results = []
    for rep in (1, 2):
        counter = itertools.count(1)
        record = run(world, key, pre_dispatch=pre, repetition=rep)
        judge = SpoofJudge(lambda counter=counter: f"req_JUDGEID{next(counter):04d}")
        results.append(verify(world, record, judge, run=loaded))
    assert [result["verdict"] for result in results] == [PASS, PASS]
    suite = verify_suite(results, expectations=world["expectations"], run=loaded)
    assert "provider_id_reused_across_suite" in suite["reasons"] and suite["suite_outcome"] == INCOMPLETE


def test_a6_p5_audit_probe_an_altered_or_removed_judge_log_is_incomplete(world, full):
    """Audit-6 probe P5: the judge log is overwritten, extended, then deleted."""
    results = passes(full)
    options = {"expectations": world["expectations"], "run": full["run"]}
    log = Path(results[0]["judge_log"]["path"])
    original = log.read_bytes()
    try:
        log.write_bytes(b"garbage\n")
        suite = verify_suite(results, **options)
        assert suite["suite_outcome"] == INCOMPLETE and "judge_log_differs_from_result" in suite["reasons"]
        log.write_bytes(original + original.splitlines(keepends=True)[1])  # one extra answer line
        assert "judge_log_differs_from_result" in verify_suite(results, **options)["reasons"]
        log.unlink()
        suite = verify_suite(results, **options)
        assert suite["suite_outcome"] == INCOMPLETE and "judge_log_differs_from_result" in suite["reasons"]
    finally:
        log.write_bytes(original)
    assert verify_suite(results, **options)["suite_outcome"] == PASS


def test_a6_5_an_injected_transport_is_refused_for_release(world, tmp_path, monkeypatch):
    """Audit-6 non-blocking 5: the manifest and every trial record say whether a transport was injected."""
    manifest = dev_manifest(world["expectations"], "5" * 64, rig=world["rig"], task_dir=world["task_dir"])
    assert manifest["run_identity"]["critic_transport"] == {"injected": True, "name": MOCK_TRANSPORT_NAME}
    assert world["rig"].attested_turn.critic_transport == world["rig"].claude.critic_transport
    product = _configured(world, tmp_path)
    product["run_identity"]["critic_transport"] = {"injected": False, "name": None}
    pre, _loaded = release_setup(world, tmp_path, manifest=product)
    # outside this module's admission, release-v7 names no test double: the manifest is refused
    monkeypatch.setattr(q01_release_manifest, "TEST_DOUBLE_TRANSPORTS", frozenset())
    assert "critic_transport:injected_transport_not_allowed_for_release" in _manifest_check(manifest)
    allowed = deepcopy(manifest)
    allowed["run_identity"]["critic_transport"] = {"injected": False, "name": None}
    assert _manifest_check(allowed) == ()
    for malformed in ({"injected": False, "name": "x"}, {"injected": True, "name": ""}, {"injected": "no"}):
        broken = deepcopy(manifest)
        broken["run_identity"]["critic_transport"] = malformed
        assert _manifest_check(broken)
    # a manifest naming the product adapter path: the rig over the fake server is refused before any read
    critic = DevCritic()
    record = release_trial(world, ("d-good", None), pre, critic)
    assert "critic_transport_differs_from_manifest" in record["pre_dispatch"]["errors"] and critic.calls == []
    assert record["critic_transport"] == {"injected": True, "name": MOCK_TRANSPORT_NAME}


def test_a6_5_a_turn_without_a_declared_transport_is_refused(world):
    critic = DevCritic()
    critic.critic_transport = None  # a scripted callable declares nothing
    record = run(world, ("d-good", None), critic, scripted=True)
    assert "critic_transport_differs_from_manifest" in record["pre_dispatch"]["errors"] and critic.calls == []
    assert record["critic_transport"] is None


def test_a6_5_the_verifier_checks_the_recorded_and_bound_transport(world):
    record = run(world, ("d-alt", None))
    edited = {**record, "critic_transport": {"injected": False, "name": None}}
    invalid(verify(world, edited), "critic_transport_differs_from_manifest")
    assert verify(world, record, DevJudge())["verdict"] == PASS


def test_a6_5_the_rig_declares_how_it_was_built(tmp_path):
    from evals.deeptwin.harness.claude_rig import claude_rig

    rig = attested_rig(tmp_path)
    assert rig.critic_transport == {"injected": True, "name": MOCK_TRANSPORT_NAME}
    assert rig.turn.critic_transport == rig.attested_turn.critic_transport == rig.critic_transport
    with pytest.raises(ValueError, match="only given with an injected transport"):
        claude_rig(tmp_path, secret="s", model_id="m", effort=None, transport=None, transport_name="named")
