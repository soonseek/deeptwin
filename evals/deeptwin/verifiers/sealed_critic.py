"""Data-driven Q01 release verifier over a sealed set (control plane; never agent-visible).

Implements the ``verifier`` block and ``acceptance.suite_outcome`` of
``evals/deeptwin/qualification/release-v6/qualification_design.json``. Unlike
``critic.py`` (whose expectations are the ten calibration cases), this module
holds no expectations, no materials and no lens pack: all are supplied at verify
time, and the lens pack is critic configuration (pinned by digest in the
pre-dispatch manifest), never sealed dataset material.

* ``load_sealed_expectations`` reads a sealed expectation document, refuses it
  unless its bytes hash to the sha256 fixed in the pre-dispatch manifest, then
  validates it against ``sealed_expectation.schema.json`` and the boundary-class
  rules below, and converts it to the shared ``Expectation``/``EvidenceRule``/
  ``Ref`` structures of ``q01_core``. Whether composition was checked is recorded
  on the result; a suite over expectations loaded without the check never passes.
* ``load_sealed_materials`` reads the sealed materials bundle: a mapping of
  published path -> bytes in the harness environment layout
  (``environment/manifest.json`` plus ``environment/cases/<case id>.json``) and
  the sha256 of the manifest file bytes. Every case file must be listed with its
  sha256, nothing unlisted is accepted, a case that carries a lens pack is
  refused, and a case source or candidate with any key the input contract would
  silently drop is refused (audit 4). Material checks and answer-leak markers are
  derived from this bundle and the expectations, never from ``q01_materials``,
  ``critic.EXPECTED`` or ``Task.md``.
* ``load_release_run`` re-checks the full pre-dispatch manifest (schema v4) and
  loads the independence profile bytes it pins: the sha256 must match, the
  profile must name this design id, and judge separation and the V3 status are
  derived from it (V3 is always ``unverified``: release-v6 cannot verify it).
  Nothing about the run is taken from the caller.
* ``verify_trial`` judges one harness release trial record with the same order and
  outcome classes as ``critic.py`` (pass / fail / not_judged / invalid): trial
  validity first (any failure is ``invalid`` and unscored; this includes a trial
  not dispatched under this manifest and a lens pack that does not hash to the
  critic configuration, a call whose durable selection is not the configuration's
  provider/mode/model/effort, a call whose durable details do not carry the
  provider-reported served model (equal to the configured model) and provider
  request id (``transport_identity_unattested``, audit 5 X1), a
  ``proposed_not_driven`` count the chain limit does not give, and a trial that is
  not journalled with its record's slot in this manifest's dispatch journal), then
  an output contract error (``fail``), rule checks, and semantic items only through
  an explicit judge. A semantic status counts only when it is re-derived from the
  judge provider's raw response, returned by ``judge_attested`` with the served
  model (equal to ``run_identity.judge_model``) and request id the judge provider
  reported, and written to the trial's durable judge log; a judge that only
  declares its identity leaves every semantic item not_judged. Each result carries
  the trial id, the trial record sha256, the ledger head and its own
  ``result_sha256``, and is registered as issued by this process. The repetition is
  read from the record's journalled slot; a caller value that differs is refused.
* ``verify_suite`` applies the release precedence exactly: ``fail`` (any valid
  repetition failed) > ``incomplete`` (an invalid, missing, duplicated or stopped
  repetition, a result not issued by ``verify_trial`` or altered since, a trial
  reused across repetitions, a result of another configuration or judge, an
  expectation set loaded without its composition check, or a manifest/profile
  that does not verify or does not pin these expectations, materials and case
  order, or results that are not exactly the trials of the manifest's dispatch
  journal, a journal that does not follow ``run_identity.planned_slots`` or holds a
  stop entry, or a dispatched trial record of this manifest under
  ``run_identity.trial_base_dir`` that is not in the journal) > ``not_judged`` (a
  not_judged repetition, or a profile without established judge separation) >
  ``pass``. Repetitions are fixed at the design's 3; whether the run was stopped
  is read from the journal, never supplied by the caller.
* ``build_suite_record`` produces the ``suite_record.schema.json`` record from an
  issued suite result and the same loaded run. ``record_sha256`` is the sha256 of
  the canonical JSON of the record without the ``record_sha256`` key, where
  canonical JSON is ``json.dumps(value, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False, allow_nan=False)`` encoded as UTF-8
  (``q01_release_manifest.canonical_bytes``).

Issued results and suites are recognised by digest within this process only; a
result or suite read back from disk is not accepted, so verification happens in
the process that verified the trials.

This module was written without access to any sealed set and is tested only on
synthetic development data. It does not import the harness.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from app.critic_audit import Ledger
from app.critic_contract import InputContractError, prepare_input
from evals.deeptwin.q01_release_manifest import (
    DESIGN_DIR,
    DESIGN_ID,
    REPETITIONS_PER_CASE,
    canonical_bytes,
    check_pre_dispatch_manifest,
    critic_configuration_digest,
    file_set_sha256,
    is_sha256,
    journal_problems,
    prepared_lens_refs,
    read_journal,
    schema_valid,
    strict_json,
)

from .q01_core import (
    ACCEPT,
    BOUNDARY_CLASSES,
    CANDIDATE,
    DEFECT,
    FAIL,
    INSUFFICIENT,
    INVALID,
    JUDGE_STATUSES,
    NOT_JUDGED,
    PASS,
    REJECTED,
    TASK_DIR,
    UNRESOLVED_CLAIM,
    VALID,
    AttestedJudgement,
    EvidenceRule,
    Expectation,
    JudgeItem,
    P,
    Ref,
    SemanticJudge,
    _case_id,
    _case_key,
    _check_completeness,
    _check_journal_coverage,
    _check_lineage,
    _instructions,
    _Invalid,
    _judge_items,
    _pointer,
    _rules,
    _Trial,
    parse_judge_reply,
)

VERIFIER_VERSION = "q01-sealed-verifier-4"
RESULT_SCHEMA = "q01-sealed-verifier-result-4"
SUITE_SCHEMA = "q01-sealed-suite-result-4"
SUITE_RECORD_SCHEMA_VERSION = "q01-release-suite-verdict-v5"
PROFILE_SCHEMA = "q01-independence-profile-6"
JUDGE_OPTIONS = frozenset({"human_reviewer", "other_provider"})
# The frozen case's source and candidate keys a sealed bundle may carry (audit 4, non-blocking 7).
SOURCE_KEYS = frozenset({"originals", "criteria", "candidate"})
CANDIDATE_KEYS = frozenset({"id", "version", "roles", "artifacts", "handoffs", "control"})
SELECTION_FIELDS = ("provider", "mode", "model", "effort")
# Designs able to verify V3 error independence: none (release-v6 has no generation path).
V3_VERIFYING_DESIGN_IDS = frozenset()
# The model identity a release call and a release judge answer must carry (audit 5, X1): what
# the provider response reported, never the selection or the judge's own declaration.
PROVIDER_REPORTED = "provider_reported"
NOT_ATTESTED = "not_attested"
TRANSPORT_UNATTESTED = "transport_identity_unattested"
JUDGE_LOG = "judge-responses.jsonl"  # durable raw judge responses, in the trial directory
_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
EXPECTATION_SCHEMA_FILE = DESIGN_DIR / "sealed_expectation.schema.json"
SUITE_RECORD_SCHEMA_FILE = DESIGN_DIR / "suite_record.schema.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
# The verifier's source files; their file-set sha256 is the verifier sha256 that a
# pre-dispatch manifest fixes (``verifier_identity``).
VERIFIER_FILES = (
    "evals/deeptwin/verifiers/sealed_critic.py",
    "evals/deeptwin/verifiers/q01_core.py",
    "evals/deeptwin/q01_release_manifest.py",
    "app/critic_contract.py",
    "app/critic_audit.py",
)
ENVIRONMENT_MANIFEST = "environment/manifest.json"
ENVIRONMENT_SCHEMA = "q01-environment-1"
CASE_SCHEMA = "q01-frozen-case-1"
CRITERIA = tuple(f"Q{index}" for index in range(1, 9))
SUITE_OUTCOMES = ("pass", "fail", "incomplete", "not_judged")
INCOMPLETE = "incomplete"
_HANDLED = frozenset({"avoid", "mitigate"})
_FRAGMENT_MIN = 24
_SPLIT = re.compile(r"[|`*#>\[\]().;:?!\n]+")
_CASE_PATH = re.compile(r"environment/cases/(q01-[0-9a-f]{10})\.json\Z")


class SealedSetError(ValueError):
    """A sealed expectation document or materials bundle is refused."""


def verifier_identity() -> dict:
    """``{"version", "sha256"}`` of this verifier, as a pre-dispatch manifest must fix it."""
    return {"version": VERIFIER_VERSION, "sha256": file_set_sha256(REPO_ROOT, VERIFIER_FILES)}


def _validator(path: Path) -> Draft202012Validator:
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _read(source) -> bytes:
    if isinstance(source, Path):
        return source.read_bytes()
    if type(source) is bytes:
        return source
    raise SealedSetError("sealed input must be bytes or a Path")


# ---------------------------------------------------------------- expectations


@dataclass(frozen=True)
class SealedCase:
    case_id: str
    candidate_id: str
    counterexample_id: str | None
    expectation: Expectation


@dataclass(frozen=True)
class SealedExpectations:
    dataset_id: str
    sha256: str
    cases: Mapping[str, SealedCase]   # case id -> sealed case
    composition_checked: bool = False  # a suite over unchecked composition never passes

    @property
    def keys(self) -> dict:
        return {case_id: (case.candidate_id, case.counterexample_id) for case_id, case in self.cases.items()}


def _rule(value):
    if value is None:
        return None
    return EvidenceRule(tuple(tuple(Ref(ref["document"], ref["location"], ref["prefix"]) for ref in group)
                              for group in value["groups"]))


def _selector(selector, has_counterexample, where):
    head, rest = selector[0], selector[1:]
    if head == "all_outputs" and not rest:
        return ("all_outputs",)
    if head in {"finding", "findings"} and rest and set(rest) <= set(CRITERIA) and len(set(rest)) == len(rest):
        if head == "finding" and len(rest) != 1:
            raise SealedSetError(f"{where}: a 'finding' selector names exactly one criterion")
        return tuple(selector)
    if head in {"validity", "response"} and not rest:
        if not has_counterexample:
            raise SealedSetError(f"{where}: a {head} selector needs an authored counterexample")
        return (head,)
    raise SealedSetError(f"{where}: unsupported judge selector {selector!r}")


def _check_boundary(case, where):
    """The six boundary classes as rules over the authored expectation (not labels only)."""
    boundary, review = case["boundary"], {name: set(value) for name, value in case["review"].items()}
    counterexample = case["counterexample_id"]
    validity, response = case.get("validity"), case.get("response")
    if (counterexample is None) != (validity is None) or (validity is None) != (response is None):
        raise SealedSetError(f"{where}: counterexample, validity and response are given together or not at all")
    if validity is None and (case.get("validity_evidence") or case.get("response_evidence")):
        raise SealedSetError(f"{where}: validity/response evidence without a counterexample")
    for criterion in case.get("review_evidence", {}):
        if review[criterion] == {"pass", "fail", "unresolved"}:
            raise SealedSetError(f"{where}: evidence rule on unconstrained criterion {criterion}")
    no_counterexample = {ACCEPT, DEFECT, INSUFFICIENT}
    if (boundary in no_counterexample) != (counterexample is None):
        raise SealedSetError(f"{where}: {boundary} {'takes no' if boundary in no_counterexample else 'needs an'} "
                             "authored counterexample")
    if boundary == ACCEPT:
        if any("fail" in allowed for allowed in review.values()) or not any(
                allowed == {"pass"} for allowed in review.values()):
            raise SealedSetError(f"{where}: an accepted candidate allows no fail and requires some pass")
    elif boundary == DEFECT:
        if not any(review[q] == {"fail"} and q in case.get("review_evidence", {}) for q in ("Q1", "Q2", "Q3")):
            raise SealedSetError(f"{where}: a required defect fails Q1, Q2 or Q3 with a source evidence rule")
    elif boundary == INSUFFICIENT:
        if not any(allowed == {"unresolved"} for allowed in review.values()):
            raise SealedSetError(f"{where}: insufficient evidence requires an unresolved criterion")
    elif boundary == REJECTED:
        if validity != "rejected" or set(response) != {"unresolved"} or any(
                "fail" in allowed for allowed in review.values()):
            raise SealedSetError(f"{where}: a rejected counterexample is rejected, unresolved in response, "
                                 "and fails no criterion")
    elif boundary == VALID:
        if validity != "valid" or not (set(response) == {"fail"} or set(response) <= _HANDLED):
            raise SealedSetError(f"{where}: a valid counterexample expects either fail or handled (avoid/mitigate)")
    elif boundary == UNRESOLVED_CLAIM and (validity != "unresolved" or set(response) != {"unresolved"}):
        raise SealedSetError(f"{where}: an unresolved specific claim stays unresolved in validity and response")


def composition_problems(expectations: SealedExpectations) -> list[str]:
    """Release-v6 ``dataset.composition`` checks that are decidable from the expectations.

    'At least one valid alternative candidate under Q4' is not decidable from the
    expectation data and stays a reviewer check.
    """
    problems = []
    cases = list(expectations.cases.values())
    for boundary in BOUNDARY_CLASSES:
        count = sum(case.expectation.boundary == boundary for case in cases)
        if count < 2:
            problems.append(f"fewer_than_2_cases:{boundary}")
    for criterion in ("Q1", "Q2", "Q3"):
        if not any(case.expectation.boundary == DEFECT and case.expectation.review[criterion] == frozenset({"fail"})
                   for case in cases):
            problems.append(f"no_required_defect:{criterion}")
    valid = [case.expectation.response for case in cases if case.expectation.boundary == VALID]
    if not any(response == frozenset({"fail"}) for response in valid) or not any(
            response <= _HANDLED for response in valid):
        problems.append("no_q5_pair")
    return problems


def load_sealed_expectations(source: bytes | Path, expected_sha256: str, *,
                             require_composition: bool = True) -> SealedExpectations:
    """Load sealed expectations; refuses a hash mismatch before parsing anything."""
    if not is_sha256(expected_sha256):
        raise SealedSetError("an expected sha256 (from the pre-dispatch manifest) is required")
    data = _read(source)
    digest = sha256(data).hexdigest()
    if digest != expected_sha256:
        raise SealedSetError("sealed expectations sha256 differs from the pinned value")
    try:
        document = strict_json(data)
    except (ValueError, UnicodeDecodeError):
        raise SealedSetError("sealed expectations are not strict UTF-8 JSON") from None
    error = best_match(_validator(EXPECTATION_SCHEMA_FILE).iter_errors(document))
    if error is not None:
        raise SealedSetError("sealed expectations schema: /" + "/".join(map(str, error.absolute_path)))
    cases = {}
    for index, case in enumerate(document["cases"]):
        where = f"cases/{index}"
        _check_boundary(case, where)
        counterexample = case["counterexample_id"]
        judge, seen = [], set()
        for item in case["judge"]:
            if item["item_id"] in seen or item["item_id"].startswith("proposed_chain_supported"):
                raise SealedSetError(f"{where}: duplicate or reserved judge item id {item['item_id']}")
            seen.add(item["item_id"])
            judge.append((item["item_id"], item["rubric"],
                          _selector(item["selector"], counterexample is not None, where)))
        expectation = Expectation(
            boundary=case["boundary"], kind=case.get("counterexample_kind"),
            review={name: frozenset(case["review"][name]) for name in CRITERIA},
            review_evidence={name: _rule(rule) for name, rule in sorted(case.get("review_evidence", {}).items())},
            validity=case.get("validity"), validity_evidence=_rule(case.get("validity_evidence")),
            response=None if case.get("response") is None else frozenset(case["response"]),
            response_evidence=_rule(case.get("response_evidence")), judge=tuple(judge), basis=case["basis"])
        case_id = _case_id(case["candidate_id"], counterexample)
        if case_id in cases:
            raise SealedSetError(f"{where}: duplicate case {case_id}")
        cases[case_id] = SealedCase(case_id, case["candidate_id"], counterexample, expectation)
    expectations = SealedExpectations(document["dataset_id"], digest, cases)
    if not require_composition:
        return expectations  # composition_checked stays False: no suite over it can pass
    problems = composition_problems(expectations)
    if problems:
        raise SealedSetError("sealed composition: " + ", ".join(problems))
    return SealedExpectations(document["dataset_id"], digest, cases, composition_checked=True)


# ---------------------------------------------------------------- materials bundle


@dataclass(frozen=True)
class SealedMaterials:
    """A verified sealed materials bundle (build it with ``load_sealed_materials``)."""

    manifest_sha256: str
    cases: Mapping[str, dict]        # case id -> frozen case (schema q01-frozen-case-1)
    case_sha256: Mapping[str, str]   # case id -> sha256 of its file bytes


def load_sealed_materials(files: Mapping[str, bytes], manifest_sha256: str) -> SealedMaterials:
    """Verify a bundle ``{published path: bytes}`` against the sha256 of its manifest bytes."""
    if not is_sha256(manifest_sha256):
        raise SealedSetError("a materials manifest sha256 is required")
    if not isinstance(files, Mapping) or not all(type(k) is str and type(v) is bytes for k, v in files.items()):
        raise SealedSetError("materials must map published paths to bytes")
    data = files.get(ENVIRONMENT_MANIFEST)
    if data is None:
        raise SealedSetError("materials bundle has no environment manifest")
    if sha256(data).hexdigest() != manifest_sha256:
        raise SealedSetError("materials manifest sha256 differs from the pinned value")
    try:
        manifest = strict_json(data)
        entries = manifest["cases"]
        if type(manifest) is not dict or manifest.get("schema") != ENVIRONMENT_SCHEMA or type(entries) is not list:
            raise ValueError
    except (ValueError, UnicodeDecodeError, KeyError, TypeError):
        raise SealedSetError("materials manifest is not a q01 environment manifest") from None
    listed = {ENVIRONMENT_MANIFEST}
    cases, shas = {}, {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"case_id", "path", "sha256"}:
            raise SealedSetError("materials manifest entry shape")
        match = _CASE_PATH.fullmatch(entry["path"]) if type(entry["path"]) is str else None
        if match is None or match.group(1) != entry["case_id"] or entry["case_id"] in cases:
            raise SealedSetError("materials manifest entry path or duplicate case")
        raw = files.get(entry["path"])
        if raw is None or sha256(raw).hexdigest() != entry["sha256"]:
            raise SealedSetError(f"materials file missing or altered: {entry['path']}")
        listed.add(entry["path"])
        try:
            case = strict_json(raw)
        except (ValueError, UnicodeDecodeError):
            raise SealedSetError(f"materials file is not strict JSON: {entry['path']}") from None
        if (type(case) is not dict or set(case) != {"schema", "case_id", "source", "authored_counterexamples"}
                or case["schema"] != CASE_SCHEMA or case["case_id"] != entry["case_id"]
                or type(case["authored_counterexamples"]) is not list or len(case["authored_counterexamples"]) > 1):
            raise SealedSetError(f"frozen case shape: {entry['path']}")
        if type(case["source"]) is not dict or "lens_pack" in case["source"]:
            # The lens pack is critic configuration (pinned by digest in the pre-dispatch
            # manifest and supplied by the harness), never sealed dataset material.
            raise SealedSetError(f"a sealed case must not carry a lens pack: {entry['path']}")
        _check_allowlisted(case, entry["path"])
        try:
            candidate_id = case["source"]["candidate"]["id"]
            authored = [item["counterexample"]["id"] for item in case["authored_counterexamples"]]
        except (KeyError, TypeError):
            raise SealedSetError(f"frozen case shape: {entry['path']}") from None
        if _case_id(candidate_id, authored[0] if authored else None) != case["case_id"]:
            raise SealedSetError(f"case id does not follow the published case-id rule: {entry['path']}")
        cases[case["case_id"]], shas[case["case_id"]] = case, entry["sha256"]
    if set(files) != listed:
        raise SealedSetError("materials bundle holds unlisted files")
    return SealedMaterials(manifest_sha256, cases, shas)


def _dropped(value, visible, path=""):
    """Key paths of ``value`` that the input contract's projection ``visible`` does not keep."""
    if type(value) is dict:
        if type(visible) is not dict:
            return [path or "/"]
        dropped = []
        for key, item in value.items():
            dropped += ([f"{path}/{key}"] if key not in visible else _dropped(item, visible[key], f"{path}/{key}"))
        return dropped
    if type(value) is list:
        if type(visible) is not list or len(visible) != len(value):
            return [path or "/"]
        return [item for index, child in enumerate(value)
                for item in _dropped(child, visible[index], f"{path}/{index}")]
    return []


def _check_allowlisted(case, where):
    """Refuse any source or candidate key the input contract would silently drop (audit 4).

    A lens pack or lens rules hidden under another key (``source.lens_rules``,
    ``candidate.lens_pack``, ...) never reaches an agent, but it would sit in the sealed
    bundle as unexamined material; the bundle carries exactly the agent-visible fields.
    """
    source = case["source"]
    candidate = source.get("candidate")
    if set(source) != SOURCE_KEYS or type(candidate) is not dict or set(candidate) != CANDIDATE_KEYS:
        raise SealedSetError(f"a sealed case source or candidate carries a key outside the allowlist: {where}")
    try:
        visible = json.loads(prepare_input(P.REVIEW, deepcopy(source)).prompt)["input"]
        dropped = _dropped(source, visible)
        for item in case["authored_counterexamples"]:
            if type(item) is not dict or set(item) != {"counterexample", "source"}:
                raise SealedSetError(f"authored counterexample shape: {where}")
            prepared = prepare_input(P.COUNTEREXAMPLE_VALIDITY, {**deepcopy(source),
                                                                 "counterexample": deepcopy(item["counterexample"])})
            dropped += _dropped(item["counterexample"], json.loads(prepared.prompt)["input"]["counterexample"])
    except InputContractError:
        raise SealedSetError(f"materials break the input contract: {where}") from None
    if dropped:
        raise SealedSetError(f"a sealed case carries keys the input contract drops ({', '.join(dropped[:3])}): "
                             f"{where}")


def load_sealed_materials_dir(root: Path, manifest_sha256: str) -> SealedMaterials:
    """Read a bundle laid out as ``<root>/environment/...`` (no symlinks followed)."""
    root = Path(root)
    files = {}
    for path in sorted((root / "environment").rglob("*")):
        if path.is_symlink():
            raise SealedSetError("symlinked sealed material is refused")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return load_sealed_materials(files, manifest_sha256)


def _sections(source):
    return {(doc["id"], section["location"]) for doc in source["originals"] for section in doc["sections"]}


def _pointer_exists(document, location, prefix):
    if prefix:
        def walk(value, path=""):
            if path.startswith(location):
                return True
            if type(value) is dict:
                return any(walk(child, f"{path}/{key}") for key, child in value.items())
            if type(value) is list:
                return any(walk(child, f"{path}/{index}") for index, child in enumerate(value))
            return False
        return walk(document)
    try:
        _pointer(document, location)
    except (KeyError, IndexError, ValueError, TypeError):
        return False
    return True


def _ref_visible(ref, visible):
    if ref.document == CANDIDATE:
        return _pointer_exists(visible["candidate"], ref.location, ref.prefix)
    if ref.document == visible["criteria"]["id"]:
        return _pointer_exists(visible["criteria"], ref.location, ref.prefix)
    return any(doc == ref.document and (loc.startswith(ref.location) if ref.prefix else loc == ref.location)
               for doc, loc in _sections(visible))


def check_binding(expectations: SealedExpectations, materials: SealedMaterials) -> None:
    """The expectations and the bundle describe the same cases and every rule is satisfiable."""
    if type(expectations) is not SealedExpectations or type(materials) is not SealedMaterials:
        raise SealedSetError("expectations and materials must be loaded sealed inputs")
    if set(expectations.cases) != set(materials.cases):
        raise SealedSetError("expectation cases differ from material cases")
    for case_id, sealed in expectations.cases.items():
        case = materials.cases[case_id]
        source = case["source"]
        try:
            visible = json.loads(prepare_input(P.REVIEW, deepcopy(source)).prompt)["input"]
        except InputContractError:
            raise SealedSetError(f"{case_id}: materials break the input contract") from None
        if [item["id"] for item in visible["criteria"]["items"]] != list(CRITERIA):
            raise SealedSetError(f"{case_id}: fixed criteria must be exactly Q1..Q8")
        authored = [item["counterexample"]["id"] for item in case["authored_counterexamples"]]
        if authored != ([] if sealed.counterexample_id is None else [sealed.counterexample_id]):
            raise SealedSetError(f"{case_id}: authored counterexample differs from the expectation")
        expectation = sealed.expectation
        rules = [*expectation.review_evidence.values(), expectation.validity_evidence, expectation.response_evidence]
        for rule in filter(None, rules):
            for group in rule.groups:
                if not any(_ref_visible(ref, visible) for ref in group):
                    raise SealedSetError(f"{case_id}: an evidence group cites nothing visible")
    corpus = _material_corpus(materials)
    if any(marker in corpus for marker in _always_markers(expectations)):
        raise SealedSetError("sealed materials contain answer content (a boundary class, case id, basis or rubric)")


# ---------------------------------------------------------------- leak markers


def _strings(value):
    if type(value) is str:
        yield value
    elif type(value) is dict:
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif type(value) is list:
        for item in value:
            yield from _strings(item)


def _fragments(text):
    for piece in _SPLIT.split(text):
        piece = piece.strip(" -,\t\"'")
        if len(piece) >= _FRAGMENT_MIN:
            yield piece


def answer_markers(expectations: SealedExpectations, materials: SealedMaterials, instructions: dict) -> list[str]:
    """Strings that would reveal sealed answers if they reached an agent input.

    Boundary class names, case ids and every whole basis and rubric text always count
    (``check_binding`` refuses a bundle whose materials contain any of them). Fragments
    of basis and rubric text of at least 24 characters count unless the fragment also
    occurs in the agent-visible corpus (the bundle's materials and the instruction),
    since an author may quote the materials.
    """
    corpus = "\n".join([*instructions.values(), _material_corpus(materials)])
    markers = set(_always_markers(expectations))
    for text in _answer_texts(expectations):
        markers.update(fragment for fragment in _fragments(text) if fragment not in corpus)
    return sorted(markers)


def _answer_texts(expectations):
    for sealed in expectations.cases.values():
        yield sealed.expectation.basis
        yield from (rubric for _id, rubric, _selector in sealed.expectation.judge)


def _always_markers(expectations):
    markers = set(BOUNDARY_CLASSES) | set(expectations.cases)
    markers.update(text.strip() for text in _answer_texts(expectations) if len(text.strip()) >= _FRAGMENT_MIN)
    return markers


def _material_corpus(materials):
    return "\n".join(text for case in materials.cases.values()
                     for text in _strings([case["source"], case["authored_counterexamples"]]))


# ---------------------------------------------------------------- trial checks


def _check_access_and_leakage(trial, record, markers):
    for entry in record.get("access_log", []):
        path = entry.get("path", "")
        if entry.get("outcome") != "read" or not (path == "instruction.md" or path.startswith("environment/")):
            raise _Invalid("forbidden_access")
    if (record.get("leak_scan") or {}).get("hits"):
        raise _Invalid("isolation_boundary")
    for call in trial.calls:
        text = call["system"] + "\n" + call["user"]
        if any(marker in text for marker in markers):
            raise _Invalid("answer_leak")


def _check_configuration(trial, configuration):
    """Every call was frozen with the critic configuration of the manifest (as far as a call records it).

    Provider, mode, model and effort are re-derived from each call's durable, digest-bound
    ``selection_json`` in the ledger (audit 4, non-blocking 1): a harness that skipped its
    own check cannot pass a trial whose calls were frozen under another selection. The
    selection is what the call was asked to use, not what served it; which model served
    each call is checked separately from the provider-reported identity
    (``_check_transport_identity``, audit 5 X1).
    """
    lenses = configuration["lens_refs_and_digests"]
    for call in trial.calls:
        selection = call.get("selection")
        if type(selection) is not dict or any(selection.get(name) != configuration[name]
                                              for name in SELECTION_FIELDS):
            raise _Invalid("selection_differs_from_configuration")
        prepared = call["manifest"]["prepared_manifest"]  # re-derived from the ledger by _Trial
        if (prepared.get("contract_version"), prepared.get("parser_version")) != (
                configuration["contract_version"], configuration["parser_version"]):
            raise _Invalid("contract_differs_from_configuration")
        if call["purpose"] is P.COUNTEREXAMPLE_PROPOSAL and prepared_lens_refs(prepared) != lenses:
            # the lens pack actually sent must hash to critic_configuration.lens_refs_and_digests
            raise _Invalid("lens_pack_differs_from_configuration")


def _check_transport_identity(trial, configuration):
    """Every call was served by the configured model, as the provider response reported it (audit 5, X1).

    Each call's durable, digest-bound ledger details must carry ``model_identity``
    ``provider_reported``, a provider request id and a served model exactly equal to
    ``critic_configuration.model``. The harness writes these only from what the transport
    returned in an ``app.critic_trial.ProviderReply`` (the Claude rig's attested turn, whose
    served model, message id and request id the product adapter parsed from the provider
    response); a scripted ``(system, user) -> str`` transport records none of them, so a
    trial it drives is invalid here even when the harness's own check was bypassed.
    """
    for call in trial.calls:
        identity = call.get("identity") or {}
        if (identity.get("model_identity") != PROVIDER_REPORTED
                or type(identity.get("provider_request_id")) is not str
                or _PROVIDER_ID.fullmatch(identity["provider_request_id"]) is None
                or identity.get("served_model") != configuration["model"]):
            raise _Invalid(TRANSPORT_UNATTESTED)


def _check_materials(trial, record, case, case_sha):
    if record.get("case_sha256") != case_sha or any(
            call["manifest"].get("case_sha256") != case_sha for call in trial.calls):
        raise _Invalid("material_mismatch")
    source = case["source"]
    # the lens pack is not dataset material: materials are compared on the review input
    expected = json.loads(prepare_input(P.REVIEW, deepcopy(source)).prompt)["input"]
    authored = {}
    for item in case["authored_counterexamples"]:
        prepared = prepare_input(P.COUNTEREXAMPLE_VALIDITY, {**deepcopy(source),
                                                             "counterexample": deepcopy(item["counterexample"])})
        authored[item["counterexample"]["id"]] = json.loads(prepared.prompt)["input"]["counterexample"]
    for call in trial.calls:
        visible = call["visible"]
        if any(visible[name] != expected[name] for name in ("originals", "criteria", "candidate")):
            raise _Invalid("material_mismatch")
        if (call["purpose"] is P.COUNTEREXAMPLE_VALIDITY and call["manifest"]["lineage"]["kind"] == "authored"
                and visible["counterexample"] != authored.get(visible["counterexample"]["id"])):
            raise _Invalid("material_mismatch")




# ---------------------------------------------------------------- release run (manifest + profile)


_RUN_TOKEN = object()
_ISSUED_RESULTS: set[str] = set()
_ISSUED_SUITES: set[str] = set()


@dataclass(frozen=True, eq=False)
class ReleaseRun:
    """One attempt's re-checked pre-dispatch manifest and the profile it pins (``load_release_run``)."""

    manifest_sha256: str | None
    committed_sha256: str | None
    manifest: dict | None
    errors: tuple[str, ...]
    profile_sha256: str | None
    judge_separation_established: bool
    v3_error_independence: str
    _token: object

    @property
    def configuration(self) -> dict | None:
        return None if self.manifest is None else self.manifest["critic_configuration"]

    @property
    def identity(self) -> dict | None:
        return None if self.manifest is None else self.manifest["run_identity"]


def _is_run(run) -> bool:
    return type(run) is ReleaseRun and run._token is _RUN_TOKEN


def _profile_problems(profile_bytes, identity):
    """(problems, judge separation) of the profile the manifest pins."""
    pinned = identity["independence_profile"]["sha256"]
    if type(profile_bytes) is not bytes or sha256(profile_bytes).hexdigest() != pinned:
        return ["profile:sha256_differs_from_manifest"], False
    try:
        profile = strict_json(profile_bytes)
    except (ValueError, UnicodeDecodeError):
        return ["profile:not_strict_json"], False
    if type(profile) is not dict or profile.get("schema") != PROFILE_SCHEMA:
        return ["profile:schema"], False
    if profile.get("design_id") != DESIGN_ID:
        return ["profile:does_not_name_this_design"], False
    separation = profile.get("judge_separation")
    v3 = profile.get("v3_error_independence")
    if type(separation) is not dict or type(separation.get("established")) is not bool or type(v3) is not dict:
        return ["profile:schema"], False
    problems = []
    if v3.get("status") != "unverified" and DESIGN_ID not in V3_VERIFYING_DESIGN_IDS:
        problems.append("profile:claims_v3_verified_under_a_design_that_cannot_verify_it")
    established = separation["established"]
    if established:
        judge = separation.get("judge")
        if (type(judge) is not dict or set(judge) != {"identity", "prompt_digest", "option"}
                or judge["option"] not in JUDGE_OPTIONS
                or judge["identity"] != identity["judge_identity"]
                or judge["prompt_digest"] != identity["judge_prompt_digest"]):
            problems.append("profile:judge_differs_from_run_identity")
        elif judge["option"] == "other_provider" and not is_sha256(judge["prompt_digest"]):
            # a model judge is only identifiable with the digest of the prompt it ran (audit 4)
            problems.append("profile:other_provider_judge_without_prompt_digest")
        elif judge["option"] == "human_reviewer" and judge["prompt_digest"] is not None and not is_sha256(
                judge["prompt_digest"]):
            problems.append("profile:judge_differs_from_run_identity")
    return problems, established and not problems


def load_release_run(manifest_bytes: bytes, *, committed_sha256: str | None, profile_bytes: bytes) -> ReleaseRun:
    """Re-check the full pre-dispatch manifest and load the independence profile it pins.

    Never raises for a bad manifest or profile: every problem is recorded in ``errors``
    (and makes a suite over this run incomplete). Judge separation is derived from the
    profile bytes, never supplied by the caller; the V3 status is ``unverified`` because
    this design cannot verify V3.
    """
    if type(manifest_bytes) is not bytes:
        raise TypeError("the pre-dispatch manifest bytes are required")
    check = check_pre_dispatch_manifest(manifest_bytes, committed_sha256=committed_sha256,
                                        verifier=verifier_identity())
    errors = [f"manifest:{error}" for error in check.errors]
    manifest, established, profile_sha = None, False, None
    if schema_valid(check):
        manifest = deepcopy(check.manifest)
        profile_sha = manifest["run_identity"]["independence_profile"]["sha256"]
        problems, established = _profile_problems(profile_bytes, manifest["run_identity"])
        errors += problems
    else:
        errors.append("profile:no_verifiable_manifest")
    v3 = "verified" if DESIGN_ID in V3_VERIFYING_DESIGN_IDS else "unverified"
    return ReleaseRun(check.manifest_sha256, committed_sha256, manifest, tuple(errors), profile_sha,
                      bool(established), v3, _RUN_TOKEN)


# ---------------------------------------------------------------- trial results


def _digest(value):
    try:
        return sha256(canonical_bytes(value)).hexdigest()
    except (TypeError, ValueError):
        return None


def _ledger_head(trial):
    """Digest of the durable journal state of the trial's calls, in dispatch order."""
    return _digest([{"request_id": call["request_id"], "digest": call["ledger_digest"],
                     "state": call["ledger_state"], "events": call["ledger_event_seqs"]} for call in trial.calls])


def _result(case_id, sealed, verdict, *, context, cause=None, rules=(), judged=(), judge=None):
    expectations, materials, run = context["expectations"], context["materials"], context["run"]
    manifest = run.manifest if _is_run(run) else None
    result = {"schema": RESULT_SCHEMA, "verifier_version": VERIFIER_VERSION,
              "case_id": case_id, "repetition": context["repetition"],
              "trial_id": context["trial_id"], "trial_record_sha256": context["record_sha256"],
              "ledger_head": context["ledger_head"],
              "journal_entry_sha256": context["journal_entry_sha256"],
              "case_key": None if sealed is None else {"candidate_id": sealed.candidate_id,
                                                       "counterexample_id": sealed.counterexample_id},
              "boundary": None if sealed is None else sealed.expectation.boundary,
              "verdict": verdict, "score": {PASS: 1.0, FAIL: 0.0}.get(verdict), "cause": cause,
              "agent_capability_scored": verdict in {PASS, FAIL},
              "rule_checks": list(rules), "judge_items": list(judged),
              # audit 5, X1: whether every critic call and every judged item carried the identity
              # its provider reported (never the selection or the judge's own declaration)
              "critic_transport_identity": context["critic_transport_identity"],
              "judge_transport_identity": (PROVIDER_REPORTED if judged and all(
                  item.get("attestation") == PROVIDER_REPORTED for item in judged) else NOT_ATTESTED),
              "judge_log": context["judge_log"],
              "judge": {"available": judge is not None,
                        "version": getattr(judge, "version", None) if judge is not None else None,
                        "identity": getattr(judge, "identity", None) if judge is not None else None,
                        "prompt_digest": getattr(judge, "prompt_digest", None) if judge is not None else None},
              "expectations_sha256": getattr(expectations, "sha256", None),
              "materials_manifest_sha256": getattr(materials, "manifest_sha256", None),
              # the bundle's case-file digests, which the manifest's sealed_case_sha256s must equal
              "materials_case_sha256s_sha256": (_digest(dict(materials.case_sha256))
                                                if type(materials) is SealedMaterials else None),
              "pre_dispatch_manifest_sha256": run.manifest_sha256 if _is_run(run) else None,
              "critic_configuration_digest": None if manifest is None else manifest["critic_configuration_digest"]}
    result["result_sha256"] = _digest(result)
    _ISSUED_RESULTS.add(result["result_sha256"])
    return result


def _is_issued(value, registry, key):
    if type(value) is not dict or value.get(key) not in registry:
        return False
    return _digest({name: item for name, item in value.items() if name != key}) == value[key]


def _record_slot(record):
    """The (case id, repetition) slot fixed in the record before dispatch, or ``None``."""
    slot = record.get("slot")
    if (type(slot) is not dict or set(slot) != {"case_id", "repetition"} or slot["case_id"] != record.get("case_id")
            or type(slot["repetition"]) is not int or not 1 <= slot["repetition"] <= REPETITIONS_PER_CASE):
        return None
    return slot


def _journal_path(run):
    return Path(run.identity["dispatch_journal"]["path"])


def _check_journalled(trial, record, run, slot):
    """The trial is journalled under this manifest with the slot its record carries (audit 4, B1).

    The journal entry (trial id and slot) was written before the first call; its
    ``entry_sha256`` is in the record and bound into every frozen call's code hashes in
    the durable ledger, and the journal header names this manifest and the record's
    commit reference.
    """
    pre_dispatch = record["pre_dispatch"]
    written = pre_dispatch.get("journal")
    state = read_journal(_journal_path(run))
    if not state.ok or state.header["manifest_sha256"] != run.manifest_sha256:
        raise _Invalid("dispatch_journal_unverified")
    entry = state.by_trial.get(record["trial_id"])
    if (entry is None or type(written) is not dict or written.get("entry_sha256") != entry["entry_sha256"]
            or {"case_id": entry["case_id"], "repetition": entry["repetition"]} != slot
            or pre_dispatch.get("slot") != slot):
        raise _Invalid("not_journalled_under_this_manifest")
    if pre_dispatch.get("commit_ref") != state.header["commit_ref"]:
        raise _Invalid("commit_ref_differs_from_dispatch_journal")
    if any(call["code_hashes"].get("dispatch_journal_entry") != entry["entry_sha256"] for call in trial.calls):
        raise _Invalid("journal_entry_not_bound_in_ledger")
    return entry


def _check_proposed_not_driven(trial, record, configuration):
    """``proposed_not_driven`` is what the configuration's chain limit gives (audit 4, non-blocking 2)."""
    proposal = next((call for call in trial.calls if call["purpose"] is P.COUNTEREXAMPLE_PROPOSAL), None)
    if proposal is None or proposal["parsed"] is None:
        return
    expected = max(0, len(proposal["parsed"]["counterexamples"]) - configuration["max_proposed_chains"])
    recorded = (record.get("stages") or {}).get("proposed_not_driven")
    if type(recorded) is not int or recorded != expected:
        raise _Invalid("proposed_not_driven_differs_from_chain_limit")


def _append_judge_log(path: Path, lines: list[dict]) -> None:
    """Append raw judge responses to the trial's durable judge log (O_APPEND, fsync)."""
    data = b"".join(canonical_bytes(line) + b"\n" for line in lines)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        while data:
            data = data[os.write(fd, data):]
        os.fsync(fd)
    finally:
        os.close(fd)


def _judge_item(judge, item, judge_model):
    """``(status, entry, log line)`` of one semantic item (audit 5, X1).

    The status is re-derived from the judge provider's raw response and counts only when the
    judge provider reported serving ``run_identity.judge_model`` with a request id. A judge
    without ``judge_attested`` (identity only declared), or an answer without a reported
    model or request id, leaves the item not_judged; a reported model other than the
    configured judge model, or a reply that is not the judge contract, is a judge failure.
    """
    attested = getattr(judge, "judge_attested", None)
    if not callable(attested):
        return "not_judged", {"attestation": "self_declared"}, None
    answer = attested(item)  # a raise is a judge fault (caller)
    if type(answer) is not AttestedJudgement:
        raise _JudgeFault("judge_fault")
    if (judge_model is None or type(answer.raw_response) is not str or type(answer.served_model) is not str
            or type(answer.provider_request_id) is not str
            or _PROVIDER_ID.fullmatch(answer.provider_request_id) is None
            or (answer.provider_message_id is not None and (type(answer.provider_message_id) is not str
                                                             or _PROVIDER_ID.fullmatch(answer.provider_message_id)
                                                             is None))):
        return "not_judged", {"attestation": NOT_ATTESTED}, None
    if answer.served_model != judge_model:
        raise _JudgeFault("judge_identity_mismatch")
    status, _reason = parse_judge_reply(answer.raw_response)
    if status is None:
        raise _JudgeFault("judge_fault")
    entry = {"attestation": PROVIDER_REPORTED, "served_model": answer.served_model,
             "provider_request_id": answer.provider_request_id, "provider_message_id": answer.provider_message_id,
             "raw_response_sha256": sha256(answer.raw_response.encode("utf-8")).hexdigest()}
    line = {"item_id": item.item_id, "status": status, "raw_response": answer.raw_response,
            **{name: entry[name] for name in ("served_model", "provider_request_id", "provider_message_id")}}
    return status, entry, line


class _JudgeFault(Exception):
    def __init__(self, cause):
        super().__init__(cause)
        self.cause = cause


def verify_trial(record: dict, *, expectations: SealedExpectations, materials: SealedMaterials,
                 run: ReleaseRun, judge: SemanticJudge | None = None, repetition: int | None = None,
                 ledger_path: Path | None = None, task_dir: Path = TASK_DIR) -> dict:
    """Verify one harness release trial record against the sealed set. Never raises for a bad record.

    The repetition is the one fixed in the record's slot and journalled before dispatch;
    ``repetition`` is only an assertion by the caller, and a value that differs from the
    record's slot makes the result invalid (audit 4, B1). Every critic call must carry the
    provider-reported served model and request id (``_check_transport_identity``), and every
    semantic status comes from an attested, durably logged raw judge response
    (``_judge_item``; audit 5, X1).
    """
    case_id = sealed = None
    context = {"expectations": expectations, "materials": materials, "run": run, "repetition": None,
               "trial_id": None, "record_sha256": None, "ledger_head": None, "journal_entry_sha256": None,
               "critic_transport_identity": NOT_ATTESTED, "judge_log": None}
    try:
        try:
            check_binding(expectations, materials)
        except SealedSetError:
            raise _Invalid("sealed_set_mismatch") from None
        if not _is_run(run) or run.manifest is None:
            raise _Invalid("release_run_unverified")
        if type(record) is not dict or record.get("schema") != "q01-trial-record-1":
            raise _Invalid("record_schema")
        context["record_sha256"] = _digest(record)
        if type(record.get("trial_id")) is str and record.get("run_id") == record["trial_id"]:
            context["trial_id"] = record["trial_id"]
        if record.get("case_id") in expectations.cases:  # attributable even if the trial is invalid
            case_id = record["case_id"]
            sealed = expectations.cases[case_id]
        slot = _record_slot(record)
        if slot is not None:
            context["repetition"] = slot["repetition"]
            pre_dispatch = record.get("pre_dispatch")
            written = pre_dispatch.get("journal") if type(pre_dispatch) is dict else None
            if type(written) is dict and is_sha256(written.get("entry_sha256")):
                context["journal_entry_sha256"] = written["entry_sha256"]
        if repetition is not None and (slot is None or repetition != slot["repetition"]):
            raise _Invalid("repetition_differs_from_journalled_slot")
        if record.get("status") != "completed":
            if record.get("cause") == TRANSPORT_UNATTESTED:
                raise _Invalid(TRANSPORT_UNATTESTED)  # the harness stopped an unattested release call
            raise _Invalid("trial_" + str(record.get("cause") or "invalid"))
        pre_dispatch = record.get("pre_dispatch")
        if (context["trial_id"] is None or type(pre_dispatch) is not dict
                or pre_dispatch.get("manifest_sha256") != run.manifest_sha256 or pre_dispatch.get("errors") != []):
            raise _Invalid("not_a_release_trial_of_this_manifest")
        if slot is None:
            raise _Invalid("not_journalled_under_this_manifest")
        path = Path(ledger_path or record.get("ledger_path") or "")
        if not path.is_absolute() or not path.is_file():
            raise _Invalid("evidence_lost")
        try:
            ledger = Ledger(path)
        except (ValueError, OSError):
            raise _Invalid("evidence_lost") from None
        instructions = _instructions(Path(task_dir))
        trial = _Trial(record, ledger, instructions)
        context["ledger_head"] = _ledger_head(trial)
        _check_journal_coverage(trial, record, path)
        _check_journalled(trial, record, run, slot)
        _check_lineage(trial, record)
        key = _case_key(trial, record, expectations.keys)
        case_id = _case_id(*key)
        sealed = expectations.cases[case_id]
        _check_access_and_leakage(trial, record, answer_markers(expectations, materials, instructions))
        _check_materials(trial, record, materials.cases[case_id], materials.case_sha256[case_id])
        _check_configuration(trial, run.configuration)
        _check_transport_identity(trial, run.configuration)
        context["critic_transport_identity"] = PROVIDER_REPORTED
        _check_proposed_not_driven(trial, record, run.configuration)
        _check_completeness(trial, key, record)
    except _Invalid as invalid:
        return _result(case_id, sealed, INVALID, cause=invalid.cause, context=context)
    except Exception:  # noqa: BLE001 - verifier fault: no score, never an agent zero
        return _result(case_id, sealed, INVALID, cause="verifier_fault", context=context)
    if record.get("output_contract") == "model_output_invalid":
        return _result(case_id, sealed, FAIL, cause="output_contract", context=context)
    expectation = sealed.expectation
    rules = _rules(trial, key, expectation)
    sealed_items = {item_id for item_id, _rubric, _selector in expectation.judge}
    judged, log_lines = [], []
    for item in _judge_items(trial, expectation):
        origin = "sealed" if item.item_id in sealed_items else "verifier"
        if judge is None:
            judged.append({"id": item.item_id, "origin": origin, "status": "not_judged", "attestation": None})
            continue
        try:
            status, entry, line = _judge_item(judge, item, run.identity["judge_model"])
        except _JudgeFault as fault:
            return _result(case_id, sealed, INVALID, cause=fault.cause, rules=rules, judged=judged,
                           judge=judge, context=context)
        except Exception:  # noqa: BLE001 - judge fault invalidates, never scores
            return _result(case_id, sealed, INVALID, cause="judge_fault", rules=rules, judged=judged,
                           judge=judge, context=context)
        if status not in JUDGE_STATUSES | {"not_judged"}:
            return _result(case_id, sealed, INVALID, cause="judge_fault", rules=rules, judged=judged,
                           judge=judge, context=context)
        judged.append({"id": item.item_id, "origin": origin, "status": status, **entry})
        if line is not None:
            log_lines.append({"trial_id": context["trial_id"], "judge_identity": getattr(judge, "identity", None),
                              **line})
    if log_lines:
        # durable raw judge responses, beside the trial record, before any verdict is issued
        log_path = path.parent.parent / JUDGE_LOG
        try:
            _append_judge_log(log_path, log_lines)
        except OSError:
            return _result(case_id, sealed, INVALID, cause="judge_evidence_unwritable", rules=rules,
                           judged=judged, judge=judge, context=context)
        context["judge_log"] = {"path": str(log_path), "lines_sha256": _digest(log_lines)}
    extra = {"rules": rules, "judged": judged, "judge": judge, "context": context}
    if not all(item["ok"] for item in rules):
        return _result(case_id, sealed, FAIL, cause="rule_check", **extra)
    if any(item["status"] == "not_supported" for item in judged):
        return _result(case_id, sealed, FAIL, cause="semantic_judgement", **extra)
    if any(item["status"] in {"not_judged", "undetermined"} for item in judged):
        return _result(case_id, sealed, NOT_JUDGED, cause="semantic_items_not_judged", **extra)
    return _result(case_id, sealed, PASS, **extra)


# ---------------------------------------------------------------- suite


def _attributable(result, expectations, run):
    return (result.get("schema") == RESULT_SCHEMA
            and result.get("verifier_version") == VERIFIER_VERSION
            and result.get("expectations_sha256") == expectations.sha256
            and result.get("verdict") in {PASS, FAIL, NOT_JUDGED, INVALID}
            and result.get("case_id") in expectations.cases
            and type(result.get("repetition")) is int
            and result.get("pre_dispatch_manifest_sha256") == run.manifest_sha256
            and result.get("critic_configuration_digest") == run.manifest["critic_configuration_digest"])


def _run_problems(run, expectations, materials_shas, case_shas=frozenset()):
    """The manifest must pin exactly these expectations, materials and cases."""
    problems = list(run.errors)
    if run.manifest is None:
        return problems
    identity = run.identity
    if identity["sealed_expectations_sha256"] != expectations.sha256:
        problems.append("manifest:sealed_expectations_sha256_mismatch")
    if materials_shas and materials_shas != {identity["sealed_dataset_sha256"]}:
        problems.append("manifest:sealed_dataset_sha256_mismatch")
    if case_shas and case_shas != {_digest(identity["sealed_case_sha256s"])}:
        # the case digests the spent-set check relied on must be the sealed bundle's (audit 5, 3)
        problems.append("manifest:sealed_case_sha256s_mismatch")
    order = identity["case_order"]["order"]
    if len(order) != len(expectations.cases) or set(order) != set(expectations.cases):
        problems.append("manifest:case_order_does_not_list_every_case_once")
    return problems


def _journal_state(run):
    """(journal state or None, problems) of the manifest's dispatch journal."""
    if run.manifest is None:
        return None, ["dispatch_journal:no_verifiable_manifest"]
    state = read_journal(_journal_path(run))
    return state, journal_problems(state, run.manifest_sha256, run.identity["planned_slots"])


def _trial_base_dir_problems(run, journal) -> list[str]:
    """Every dispatched trial record of this manifest under ``trial_base_dir`` is journalled (audit 5, 1).

    The harness creates a release trial's directory only under ``run_identity.trial_base_dir``
    and writes its record there. A record that names this manifest and was dispatched (it
    carries a journal entry, a call or a read) must be in the journal with that entry; a
    trial directory without a record, an unreadable record or a symlink is a problem too.
    Restoring an earlier copy of the journal after a failed trial therefore leaves that
    trial's directory as evidence, unless the operator also removes the directory (an
    organizational limit recorded in the design's ``open``). A record refused before any
    read or call (no journal entry, no call) was never dispatched and is not counted.
    """
    base = Path(run.identity["trial_base_dir"]["path"])
    if base.is_symlink() or not base.is_dir():
        return ["trial_base_dir:missing"]
    journalled = journal.by_trial if journal is not None and journal.ok else {}
    problems = set()
    for child in sorted(base.iterdir()):
        if child.is_symlink():
            problems.add("trial_base_dir:symlink_refused")
            continue
        if not child.is_dir():
            continue
        path = child / "trial-record.json"
        if path.is_symlink() or not path.is_file():
            problems.add("trial_base_dir:trial_directory_without_record")
            continue
        try:
            record = strict_json(path.read_bytes())
        except (OSError, ValueError, UnicodeDecodeError):
            problems.add("trial_base_dir:unreadable_trial_record")
            continue
        pre_dispatch = record.get("pre_dispatch") if type(record) is dict else None
        if type(pre_dispatch) is not dict or pre_dispatch.get("manifest_sha256") != run.manifest_sha256:
            continue
        written = pre_dispatch.get("journal")
        if written is None and not record.get("calls") and not record.get("access_log"):
            continue  # refused before any read or call: never dispatched
        entry = journalled.get(record.get("trial_id"))
        if entry is None or type(written) is not dict or written.get("entry_sha256") != entry["entry_sha256"]:
            problems.add("trial_base_dir:trial_not_in_dispatch_journal")
    return sorted(problems)


def verify_suite(results: list[dict], *, expectations: SealedExpectations, run: ReleaseRun) -> dict:
    """Aggregate per-repetition results into the release-v6 suite outcome.

    ``run`` is the loaded pre-dispatch manifest and profile (``load_release_run``): the
    manifest is always re-checked in full, and judge separation comes only from the
    profile it pins. Repetitions are the design's 3. The results must be exactly the
    trials of the manifest's dispatch journal (every journalled trial submitted, nothing
    else), and the journal must follow ``run_identity.planned_slots`` in order (audit 4,
    B1): a best-of-N selection is incomplete. Whether the run was stopped is read from
    the journal's stop entry, never supplied by the caller, and every dispatched trial
    record of this manifest under ``run_identity.trial_base_dir`` must be journalled
    (audit 5, non-blocking 7 and 1).
    """
    if type(expectations) is not SealedExpectations:
        raise SealedSetError("loaded sealed expectations are required")
    if not _is_run(run):
        raise SealedSetError("a loaded release run (load_release_run) is required")
    reasons = set()
    if not expectations.composition_checked:
        reasons.add("composition_not_checked")
    repetitions = range(1, REPETITIONS_PER_CASE + 1)
    slots = {(case_id, rep): [] for case_id in expectations.cases for rep in repetitions}
    invalid_causes, materials_shas, case_shas = [], set(), set()
    seen = {"trial_id": set(), "trial_record_sha256": set(), "ledger_head": set()}
    identity = run.identity
    journal, journal_issues = _journal_state(run)
    reasons.update(journal_issues)
    journalled = journal.by_trial if journal is not None and journal.ok else {}
    submitted, critic_transport, judge_transport = set(), set(), set()
    for result in results:
        if not _is_issued(result, _ISSUED_RESULTS, "result_sha256"):
            reasons.add("result_not_issued_by_verify_trial")
            continue
        materials_shas.add(result.get("materials_manifest_sha256"))
        case_shas.add(result.get("materials_case_sha256s_sha256"))
        if run.manifest is None or not _attributable(result, expectations, run):
            reasons.add("unattributable_result")
            continue
        slot = (result["case_id"], result["repetition"])
        if slot not in slots:
            reasons.add("unplanned_repetition")
            continue
        entry = journalled.get(result.get("trial_id"))
        if (entry is None or (entry["case_id"], entry["repetition"]) != slot
                or entry["entry_sha256"] != result.get("journal_entry_sha256")):
            reasons.add("result_not_in_dispatch_journal")
        else:
            submitted.add(result["trial_id"])
        if slots[slot]:
            reasons.add("duplicate_repetition")
        for name, values in seen.items():
            value = result.get(name)
            if value is not None:
                if value in values:
                    reasons.add("trial_reused")
                values.add(value)
        if result["verdict"] != INVALID and result.get("trial_id") is None:
            reasons.add("unattributable_result")
        judge = result["judge"]
        if judge["available"] and (judge["identity"], judge["prompt_digest"]) != (
                identity["judge_identity"], identity["judge_prompt_digest"]):
            reasons.add("judge_differs_from_run_identity")
        slots[slot].append(result["verdict"])
        critic_transport.add(result.get("critic_transport_identity"))
        judge_transport.add(result.get("judge_transport_identity"))
        if result["verdict"] == INVALID:
            invalid_causes.append({"case_id": slot[0], "repetition": slot[1], "cause": result.get("cause")})
    if set(journalled) - submitted:
        # a journalled trial that is not among the results: best-of-N selection or a lost trial
        reasons.add("journalled_trial_not_submitted")
    if len(materials_shas) > 1:
        reasons.add("results_verified_against_different_materials")
    verdicts = [verdict for items in slots.values() for verdict in items]
    if any(not items for items in slots.values()):
        reasons.add("missing_repetition")
    if INVALID in verdicts:
        reasons.add("invalid_repetition")
    # the stop comes from the dispatcher's journal entry, never from the caller (audit 5, 7)
    stopped = journal is not None and journal.ok and journal.stopped
    if stopped:
        reasons.add("run_stopped")
    if run.manifest is not None:
        reasons.update(_trial_base_dir_problems(run, journal))
    reasons.update(_run_problems(run, expectations, materials_shas, case_shas))
    separated = run.judge_separation_established
    if FAIL in verdicts:
        outcome = FAIL
    elif reasons:
        outcome = INCOMPLETE
    elif NOT_JUDGED in verdicts or not separated:
        outcome = NOT_JUDGED
        if not separated:
            reasons.add("judge_separation_not_established")
    else:
        outcome = PASS
    cases, boundaries = {}, {name: {"cases": 0, PASS: 0, FAIL: 0, NOT_JUDGED: 0, INVALID: 0, "missing": 0}
                             for name in BOUNDARY_CLASSES}
    for case_id, sealed in sorted(expectations.cases.items()):
        per_rep = {rep: slots[(case_id, rep)] for rep in repetitions}
        boundary = boundaries[sealed.expectation.boundary]
        boundary["cases"] += 1
        for items in per_rep.values():
            boundary["missing"] += not items
            for verdict in items:
                boundary[verdict] += 1
        cases[case_id] = {"boundary": sealed.expectation.boundary,
                          "case_key": {"candidate_id": sealed.candidate_id,
                                       "counterexample_id": sealed.counterexample_id},
                          "case_pass": all(items == [PASS] for items in per_rep.values()),
                          "verdicts": {str(rep): items for rep, items in per_rep.items()}}
    journal_ok = journal is not None and not journal_issues
    suite = {"schema": SUITE_SCHEMA, "verifier_version": VERIFIER_VERSION, "design_id": DESIGN_ID,
             "suite_outcome": outcome, "reasons": sorted(reasons),
             "repetitions_per_case": REPETITIONS_PER_CASE, "cases": cases, "boundaries": boundaries,
             "counts": {name: verdicts.count(name) for name in (PASS, FAIL, NOT_JUDGED, INVALID)},
             "invalid_causes": invalid_causes,
             "dataset_id": expectations.dataset_id, "expectations_sha256": expectations.sha256,
             "composition_checked": expectations.composition_checked,
             "materials_manifest_sha256": next(iter(materials_shas)) if len(materials_shas) == 1 else None,
             "pre_dispatch_manifest_sha256": run.manifest_sha256,
             "committed_manifest_sha256": run.committed_sha256,
             "independence_profile_sha256": run.profile_sha256,
             "case_order": None if identity is None else list(identity["case_order"]["order"]),
             "dispatch_journal": {"verified": journal_ok,
                                  "head": journal.head if journal_ok else None,
                                  "entries": len(journal.dispatches) if journal_ok else None,
                                  "commit_ref": deepcopy(journal.header["commit_ref"]) if journal_ok else None},
             "judge_separation_established": separated, "stopped": bool(stopped),
             "critic_transport_identity": (PROVIDER_REPORTED if critic_transport == {PROVIDER_REPORTED}
                                           else NOT_ATTESTED),
             "judge_transport_identity": (PROVIDER_REPORTED if judge_transport == {PROVIDER_REPORTED}
                                          else NOT_ATTESTED)}
    suite["suite_sha256"] = _digest(suite)
    _ISSUED_SUITES.add(suite["suite_sha256"])
    return suite


# ---------------------------------------------------------------- suite record


def record_sha256(record: dict) -> str:
    """sha256 of the canonical JSON of ``record`` without its ``record_sha256`` key."""
    return sha256(canonical_bytes({key: value for key, value in record.items() if key != "record_sha256"})).hexdigest()


def check_suite_record(record: dict) -> list[str]:
    """Schema and ``record_sha256`` problems of one suite record (empty when it verifies)."""
    problems = []
    error = best_match(_validator(SUITE_RECORD_SCHEMA_FILE).iter_errors(record))
    if error is not None:
        problems.append("suite_record_schema:/" + "/".join(map(str, error.absolute_path)))
    elif record["record_sha256"] != record_sha256(record):
        problems.append("record_sha256_mismatch")
    return problems


def build_suite_record(suite: dict, *, run: ReleaseRun) -> dict:
    """The ``suite_record.schema.json`` record of one attempt, from its issued suite result and run.

    The suite must be the unaltered result of ``verify_suite`` over the same loaded run.
    The fields come from the re-checked pre-dispatch manifest (configuration digest
    recomputed, sealed dataset sha256, attempt, prior outcomes, every prior attempt's
    sealed set sha256 and a digest of the prior-attempt list, profile sha256), from the
    dispatch journal the suite verified (its head and the manifest's commit reference);
    judge separation and the V3 status come from the run (the profile and this design),
    never from the caller; the critic and judge transport identities and the stop come
    from the suite (the verified results and the journal). A manifest or profile problem,
    a suite whose expectations, materials or case order are not the ones the manifest
    pins, or a journal that is unverified, stopped or has grown since the suite was
    verified, turns a would-be pass or not_judged into incomplete (a fail keeps
    precedence).
    """
    if not _is_issued(suite, _ISSUED_SUITES, "suite_sha256") or suite.get("schema") != SUITE_SCHEMA:
        raise ValueError("an unaltered suite result issued by verify_suite is required")
    if not _is_run(run) or suite["pre_dispatch_manifest_sha256"] != run.manifest_sha256:
        raise ValueError("the run is not the manifest this suite recorded")
    if run.manifest is None:
        raise ValueError("a schema-valid pre-dispatch manifest is required to build a suite record")
    manifest, identity = run.manifest, run.identity
    outcome = suite["suite_outcome"]
    journal = suite["dispatch_journal"]
    current, current_issues = _journal_state(run)
    consistent = (not run.errors and suite["composition_checked"]
                  and suite["expectations_sha256"] == identity["sealed_expectations_sha256"]
                  and suite["materials_manifest_sha256"] == identity["sealed_dataset_sha256"]
                  and suite["case_order"] == identity["case_order"]["order"]
                  and suite["independence_profile_sha256"] == identity["independence_profile"]["sha256"]
                  and journal["verified"] and not current_issues and current.head == journal["head"]
                  and not current.stopped)
    if not consistent and outcome in {PASS, NOT_JUDGED}:
        outcome = INCOMPLETE
    if outcome == PASS and (suite["critic_transport_identity"], suite["judge_transport_identity"]) != (
            PROVIDER_REPORTED, PROVIDER_REPORTED):
        outcome = INCOMPLETE  # unreachable through verify_suite; the gate refuses such a pass too
    prior = manifest["prior_attempts"]
    record = {
        "schema_version": SUITE_RECORD_SCHEMA_VERSION,
        "design_id": DESIGN_ID,
        "critic_configuration_digest": critic_configuration_digest(manifest["critic_configuration"]),
        "pre_dispatch_manifest_sha256": run.manifest_sha256,
        "sealed_set_sha256": identity["sealed_dataset_sha256"],
        "attempt": manifest["attempt"],
        "prior_outcomes": [item["suite_outcome"] for item in prior],
        "suite_outcome": outcome,
        "independence_profile_sha256": identity["independence_profile"]["sha256"],
        "judge_separation_established": run.judge_separation_established,
        "v3_error_independence": run.v3_error_independence,
        "prior_sealed_set_sha256s": [item["sealed_dataset_sha256"] for item in prior],
        "prior_attempts_sha256": _digest(prior),
        "dispatch_journal_head": journal["head"],
        "manifest_commit_ref": deepcopy(journal["commit_ref"]),
        "critic_transport_identity": suite["critic_transport_identity"],
        "judge_transport_identity": suite["judge_transport_identity"],
        "run_stopped": bool(suite["stopped"] or current.stopped),
    }
    record["record_sha256"] = record_sha256(record)
    problems = check_suite_record(record)
    if problems:
        raise ValueError("suite record does not validate: " + ", ".join(problems))
    return record


__all__ = [
    "INCOMPLETE",
    "PROVIDER_REPORTED",
    "REPETITIONS_PER_CASE",
    "RESULT_SCHEMA",
    "SUITE_SCHEMA",
    "V3_VERIFYING_DESIGN_IDS",
    "VERIFIER_VERSION",
    "AttestedJudgement",
    "JudgeItem",
    "ReleaseRun",
    "SealedCase",
    "SealedExpectations",
    "SealedMaterials",
    "SealedSetError",
    "SemanticJudge",
    "answer_markers",
    "build_suite_record",
    "check_binding",
    "check_pre_dispatch_manifest",
    "check_suite_record",
    "composition_problems",
    "critic_configuration_digest",
    "load_release_run",
    "load_sealed_expectations",
    "load_sealed_materials",
    "load_sealed_materials_dir",
    "record_sha256",
    "verifier_identity",
    "verify_suite",
    "verify_trial",
]
