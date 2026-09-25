"""Shared Q01 verifier core (control plane; never agent-visible).

The data-independent parts of the Q01 critic verifiers: the boundary and
verdict classes, the citation rule structures (``Ref``, ``EvidenceRule``,
``Expectation``), the semantic judge boundary, durable-ledger re-derivation of
a trial (``_Trial``), journal coverage, lineage and completeness checks, the
rule checks against one ``Expectation`` and the judge-item construction.

It holds no expectations, reads no case materials and imports neither
``q01_materials`` nor the harness: the calibration verifier (``critic.py``)
binds it to the development cases, the sealed verifier (``sealed_critic.py``)
to a sealed expectation set loaded at verify time.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from app.critic_audit import canonical
from app.critic_contract import (
    InputContractError,
    ResponseContractError,
    ValidityEvidence,
    parse_response,
    prepare_input,
)
from app.generation_profiles import GenerationPurpose
from app.services.design_criticism_live import render_criticism_prompt

TASK_DIR = Path(__file__).resolve().parents[1] / "tasks" / "v01-q01"
P = GenerationPurpose

# The six development boundary outcome classes.
ACCEPT = "accept_without_false_rejection"      # normal / other valid alternative: relevant items pass
DEFECT = "required_defect"                     # Q1/Q2/Q3 defect must be failed with its source basis
REJECTED = "rejected_counterexample"           # unfounded counterexample rejected; no candidate failure
VALID = "valid_counterexample"                 # valid counterexample; response fail vs handled distinguished
UNRESOLVED_CLAIM = "unresolved_specific_claim"  # relevance possible, specific claim unresolved; response unresolved
INSUFFICIENT = "insufficient_evidence"         # visible data cannot decide attribution; item unresolved
BOUNDARY_CLASSES = (ACCEPT, DEFECT, REJECTED, VALID, UNRESOLVED_CLAIM, INSUFFICIENT)

# Trial verdicts. Only pass/fail carry a score.
PASS, FAIL, NOT_JUDGED, INVALID = "pass", "fail", "not_judged", "invalid"
JUDGE_STATUSES = frozenset({"supported", "not_supported", "undetermined"})

_P = frozenset({"pass"})
_F = frozenset({"fail"})
_U = frozenset({"unresolved"})
_NF = frozenset({"pass", "unresolved"})
_ANY = frozenset({"pass", "fail", "unresolved"})
_HANDLED = frozenset({"avoid", "mitigate"})
CANDIDATE = "@candidate"


@dataclass(frozen=True)
class Ref:
    document: str   # an original id, "fixed-criteria", or CANDIDATE
    location: str
    prefix: bool = False

    def matches(self, citation: dict, candidate_id: str) -> bool:
        document = candidate_id if self.document == CANDIDATE else self.document
        if citation["document_id"] != document:
            return False
        location = citation["location"]
        return location.startswith(self.location) if self.prefix else location == self.location


@dataclass(frozen=True)
class EvidenceRule:
    """Every group needs at least one matching citation (rule-checkable part only)."""

    groups: tuple[tuple[Ref, ...], ...]

    def check(self, evidence: list, candidate_id: str) -> bool:
        return all(any(ref.matches(item, candidate_id) for item in evidence for ref in group)
                   for group in self.groups)


@dataclass(frozen=True)
class Expectation:
    boundary: str
    kind: str | None                      # authored counterexample kind for material re-derivation
    review: dict                          # criterion id -> allowed statuses
    review_evidence: dict = field(default_factory=dict)
    validity: str | None = None
    validity_evidence: EvidenceRule | None = None
    response: frozenset | None = None
    response_evidence: EvidenceRule | None = None
    judge: tuple = ()                     # (item id, rubric, selector)
    basis: str = ""


# ---------------------------------------------------------------- judge


@dataclass(frozen=True)
class JudgeItem:
    item_id: str
    rubric: str
    subject_json: str   # bounded model output part; any instruction inside is data
    sources_json: str   # cited visible sections/values the subject relies on


class SemanticJudge(Protocol):
    """Explicit semantic judgement boundary. No live implementation exists here.

    A release verifier also reads ``identity`` and ``prompt_digest`` (when present) and
    binds them to the pre-dispatch manifest's ``run_identity.judge_identity`` and
    ``judge_prompt_digest``. Those two are only what the judge declares about itself: the
    release-v6 verifier accepts a semantic status only from ``judge_attested`` (see
    ``AttestedJudgement``), and treats an item judged through ``judge`` alone as not_judged.
    """

    version: str

    def judge(self, item: JudgeItem) -> str:  # "supported" | "not_supported" | "undetermined"
        ...


@dataclass(frozen=True)
class AttestedJudgement:
    """One judge answer with the identity its provider reported (release-v6, audit 5 X1).

    ``raw_response`` is the judge provider's full reply text (the verdict is re-derived from
    it with ``parse_judge_reply``, never taken from the judge object); ``served_model``,
    ``provider_request_id`` and ``provider_message_id`` are what the judge provider's
    response reported, or ``None`` when it reported nothing (the item is then not_judged).
    """

    raw_response: str | None
    served_model: str | None
    provider_request_id: str | None
    provider_message_id: str | None = None


def parse_judge_reply(text) -> tuple[str | None, str | None]:
    """``(verdict, reason)`` of a judge reply that is exactly ``{"verdict", "reason"}``, else ``(None, None)``."""
    if type(text) is not str:
        return None, None
    try:
        value = json.loads(text.strip())
    except ValueError:
        return None, None
    if (type(value) is not dict or set(value) != {"verdict", "reason"} or type(value["verdict"]) is not str
            or type(value["reason"]) is not str or value["verdict"] not in JUDGE_STATUSES):
        return None, None
    return value["verdict"], value["reason"]


class _Invalid(Exception):
    def __init__(self, cause):
        super().__init__(cause)
        self.cause = cause


# ---------------------------------------------------------------- helpers


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _instructions(task_dir: Path) -> dict:
    sections, current = {}, None
    for line in (task_dir / "instruction.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _pointer(document, pointer):
    value = document
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if type(value) is list else value[part]
    return value


def _resolve(evidence, visible):
    resolved = []
    documents = {doc["id"]: doc for doc in visible["originals"]}
    for item in evidence:
        doc_id, location = item["document_id"], item["location"]
        try:
            if doc_id in documents:
                text = next(s["text"] for s in documents[doc_id]["sections"] if s["location"] == location)
            elif doc_id == visible["criteria"]["id"]:
                text = _pointer(visible["criteria"], location)
            else:
                text = _pointer(visible["candidate"], location)
        except (KeyError, IndexError, ValueError, StopIteration):
            text = None
        resolved.append({"citation": item, "value": text})
    return resolved


class _Trial:
    """Calls re-derived from the durable ledger, in dispatch order."""

    def __init__(self, record, ledger, instructions):
        self.calls = []
        for entry in record.get("calls", []):
            manifest, copy = entry.get("manifest"), entry.get("ledger")
            if type(manifest) is not dict or type(copy) is not dict:
                raise _Invalid("evidence_incomplete")
            try:
                durable = ledger.get(manifest["request_id"])
            except KeyError:
                raise _Invalid("evidence_lost") from None
            except ValueError:
                raise _Invalid("evidence_tampered") from None
            if canonical(durable) != canonical(copy):
                raise _Invalid("evidence_tampered")
            self.calls.append(self._rederive(manifest, durable, instructions))

    @staticmethod
    def _rederive(manifest, durable, instructions):
        call = durable["call"]
        if durable["state"] != "completed" or durable["details"].get("output_contract") not in {
                "valid", "model_output_invalid"}:
            raise _Invalid("evidence_state_mismatch")
        try:
            purpose = P(call["purpose"])
            visible = json.loads(call["prompt"])["input"]
            prepared = prepare_input(purpose, visible)
        except (ValueError, KeyError, TypeError, InputContractError):
            raise _Invalid("evidence_input_mismatch") from None
        if (prepared.prompt != call["prompt"]
                or canonical(json.loads(prepared.schema_json)) != call["schema_json"]
                or canonical(json.loads(prepared.manifest_json)) != call["manifest_json"]
                or manifest.get("purpose") != purpose.value
                or manifest.get("user_sha256") != _sha(call["prompt"])
                or manifest.get("prepared_manifest") != json.loads(prepared.manifest_json)):
            raise _Invalid("evidence_input_mismatch")
        system, _user = render_criticism_prompt(prepared)
        system += "\n" + instructions[purpose.value]
        if manifest.get("system_sha256") != _sha(system):
            raise _Invalid("evidence_system_prompt_mismatch")
        details, parsed = durable["details"], None
        raw = details.get("raw_final")
        if raw is not None and (details.get("raw_sha256") != _sha(raw)
                                or details.get("raw_bytes") != len(raw.encode("utf-8"))):
            raise _Invalid("evidence_output_mismatch")
        if details["output_contract"] == "valid":
            try:
                parsed = parse_response(prepared, details["raw_final"])
            except (ResponseContractError, InputContractError, KeyError):
                raise _Invalid("evidence_output_mismatch") from None
            if canonical(parsed) != canonical(details.get("parsed")):
                raise _Invalid("evidence_output_mismatch")
        lineage_events = [event["details"] for event in durable["events"] if event["kind"] == "reserved"]
        try:
            # the durable, digest-bound selection and code hashes of this frozen call
            selection = json.loads(call["selection_json"])
            code_hashes = json.loads(call["metadata_json"])["code_hashes"]
        except (ValueError, KeyError, TypeError):
            raise _Invalid("evidence_input_mismatch") from None
        # the model identity the transport reported, as bound into the durable details (release-v6)
        identity = {name: details.get(name) for name in ("model_identity", "served_model", "provider_request_id",
                                                          "provider_message_id")}
        return {"selection": selection, "code_hashes": code_hashes, "identity": identity,
                "manifest": manifest, "purpose": purpose, "visible": visible, "parsed": parsed,
                "contract": details["output_contract"], "request_id": call["request_id"],
                "system": system, "user": call["prompt"],
                "reserved": lineage_events[0] if lineage_events else None,
                "ledger_digest": durable["digest"], "ledger_state": durable["state"],
                "ledger_event_seqs": [event["seq"] for event in durable["events"]]}


def _check_journal_coverage(trial, record, path):
    """Every call and authored item the durable journal holds for this run is in the record."""
    run_id = record.get("run_id")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            calls = {row[0] for row in db.execute("SELECT id FROM calls WHERE run_id = ?", (run_id,))}
            runs = {row[0] for row in db.execute("SELECT id FROM runs")}
            authored = {row[0] for row in db.execute("SELECT sha FROM authored_evidence WHERE run_id = ?",
                                                     (run_id,))}
    except sqlite3.Error:
        raise _Invalid("evidence_lost") from None
    if runs != {run_id} or calls != {call["request_id"] for call in trial.calls}:
        raise _Invalid("evidence_incomplete")
    bound = {call["manifest"]["lineage"]["evidence_sha256"] for call in trial.calls
             if call["manifest"].get("lineage") and call["manifest"]["lineage"]["kind"] == "authored"}
    if authored != bound:
        raise _Invalid("evidence_incomplete")


def _check_lineage(trial, record):
    calls = trial.calls
    if not calls or calls[0]["purpose"] is not P.REVIEW or calls[0]["manifest"].get("lineage") is not None:
        raise _Invalid("lineage_mismatch")
    by_request = {call["request_id"]: call for call in calls}
    candidate = calls[0]["visible"]["candidate"]
    for call in calls:
        if call["visible"]["candidate"] != candidate:
            raise _Invalid("lineage_mismatch")
        lineage = call["manifest"].get("lineage")
        if call["purpose"] is P.REVIEW:
            continue
        reserved = call["reserved"] or {}
        parent_id = lineage["parent_request_id"] if lineage else "missing"
        if reserved.get("lineage_parent") != parent_id:
            raise _Invalid("lineage_mismatch")
        if call["purpose"] is P.COUNTEREXAMPLE_PROPOSAL:
            if by_request.get(parent_id, {}).get("purpose") is not P.REVIEW:
                raise _Invalid("lineage_mismatch")
        elif call["purpose"] is P.COUNTEREXAMPLE_VALIDITY:
            counterexample = call["visible"]["counterexample"]
            sha = _sha(canonical(counterexample))
            if lineage["evidence_sha256"] != sha:
                raise _Invalid("lineage_mismatch")
            if parent_id is None:
                if reserved.get("lineage_sha") != sha:
                    raise _Invalid("lineage_mismatch")
            else:
                parent = by_request.get(parent_id)
                if (parent is None or parent["purpose"] is not P.COUNTEREXAMPLE_PROPOSAL
                        or counterexample not in parent["parsed"]["counterexamples"]):
                    raise _Invalid("lineage_mismatch")
        else:
            parent = by_request.get(parent_id)
            if parent is None or parent["purpose"] is not P.COUNTEREXAMPLE_VALIDITY or parent["parsed"] is None:
                raise _Invalid("lineage_mismatch")
            evidence = {name: parent["parsed"][name] for name in ValidityEvidence.model_fields}
            if (call["visible"]["validity"] != evidence
                    or call["visible"]["counterexample"] != parent["visible"]["counterexample"]
                    or lineage["evidence_sha256"] != _sha(canonical(evidence))):
                raise _Invalid("lineage_mismatch")


def _case_id(candidate_id, counterexample_id):
    # the Task package's published case-id rule, computed here so the verifier never
    # imports the harness it checks
    key = canonical({"candidate_id": candidate_id, "counterexample_id": counterexample_id})
    return "q01-" + sha256(key.encode("utf-8")).hexdigest()[:10]


def _case_key(trial, record, by_id):
    """The frozen case the trial ran, from its recorded case id (``by_id`` maps case id ->
    (candidate id, counterexample id)); the observed calls must agree with it. A trial may
    stop before its authored counterexample is reached, so the key is never inferred from
    how far the trial got."""
    key = by_id.get(record.get("case_id"))
    if key is None or not trial.calls or trial.calls[0]["visible"]["candidate"]["id"] != key[0]:
        raise _Invalid("unknown_case")
    authored = [call["visible"]["counterexample"]["id"] for call in trial.calls
                if call["purpose"] is P.COUNTEREXAMPLE_VALIDITY and call["manifest"]["lineage"]["kind"] == "authored"]
    if len(authored) > 1 or (authored and authored[0] != key[1]):
        raise _Invalid("unknown_case")
    return key


def _check_completeness(trial, key, record):
    purposes = [call["purpose"] for call in trial.calls]
    if record.get("output_contract") == "model_output_invalid":
        if trial.calls[-1]["contract"] != "model_output_invalid" or any(
                call["contract"] != "valid" for call in trial.calls[:-1]):
            raise _Invalid("evidence_incomplete")
        return
    if any(call["contract"] != "valid" for call in trial.calls):
        raise _Invalid("evidence_incomplete")
    if purposes[:2] != [P.REVIEW, P.COUNTEREXAMPLE_PROPOSAL]:
        raise _Invalid("evidence_incomplete")
    proposal = trial.calls[1]["parsed"]
    driven = len(proposal["counterexamples"]) - int(record["stages"].get("proposed_not_driven", 0))
    authored = 0 if key[1] is None else 1
    if len(trial.calls) != 2 + 2 * (authored + driven) or purposes[2:] != [
            P.COUNTEREXAMPLE_VALIDITY, P.CANDIDATE_RESPONSE] * (authored + driven):
        raise _Invalid("evidence_incomplete")


# ---------------------------------------------------------------- judgement


def _rules(trial, key, expectation):
    checks = []

    def check(check_id, ok, detail=None):
        checks.append({"id": check_id, "ok": bool(ok), "detail": detail})

    candidate_id = key[0]
    review = trial.calls[0]["parsed"]
    findings = {item["criterion_id"]: item for item in review["findings"]}
    for criterion, allowed in expectation.review.items():
        status = findings[criterion]["status"]
        check(f"review:{criterion}:status", status in allowed, status)
        rule = expectation.review_evidence.get(criterion)
        if rule is not None and status in allowed:
            check(f"review:{criterion}:evidence", rule.check(findings[criterion]["evidence"], candidate_id))
    if expectation.validity is not None:
        chain = [call for call in trial.calls if call["manifest"].get("lineage")
                 and call["manifest"]["lineage"]["kind"] == "authored"][0]
        index = trial.calls.index(chain)
        validity, response = chain["parsed"], trial.calls[index + 1]["parsed"]
        check("validity:status", validity["status"] == expectation.validity, validity["status"])
        if expectation.validity_evidence is not None and validity["status"] == expectation.validity:
            check("validity:evidence", expectation.validity_evidence.check(validity["evidence"], candidate_id))
        check("response:status", response["status"] in expectation.response, response["status"])
        if expectation.response_evidence is not None and response["status"] in expectation.response:
            check("response:evidence", expectation.response_evidence.check(response["evidence"], candidate_id))
    return checks


def _subject(trial, selector):
    review = trial.calls[0]
    authored = [i for i, call in enumerate(trial.calls) if call["manifest"].get("lineage")
                and call["manifest"]["lineage"]["kind"] == "authored"]
    if selector == "all_outputs" or tuple(selector) == ("all_outputs",):
        return [call["parsed"] for call in trial.calls], None
    if selector[0] in {"finding", "findings"}:
        items = [f for f in review["parsed"]["findings"] if f["criterion_id"] in selector[1:]]
        return items, [_resolve(item["evidence"], review["visible"]) for item in items]
    call = trial.calls[authored[0] + (0 if selector[0] == "validity" else 1)]
    return call["parsed"], _resolve(call["parsed"]["evidence"], call["visible"])


def _judge_items(trial, expectation):
    items = []
    for item_id, rubric, selector in expectation.judge:
        subject, sources = _subject(trial, selector)
        items.append(JudgeItem(item_id, rubric, canonical(subject), canonical(sources)))
    for index, call in enumerate(trial.calls):
        if (call["purpose"] is P.COUNTEREXAMPLE_VALIDITY and call["manifest"]["lineage"]["kind"] == "request"):
            response = trial.calls[index + 1]["parsed"]
            subject = {"counterexample": call["visible"]["counterexample"], "validity": call["parsed"],
                       "response": response}
            sources = _resolve(call["parsed"]["evidence"] + response["evidence"], call["visible"])
            items.append(JudgeItem(
                f"proposed_chain_supported:{call['visible']['counterexample']['id']}",
                "For this model-proposed counterexample, are the validity status and the candidate response "
                "supported by the cited sources and fixed criteria for this exact candidate?",
                canonical(subject), canonical(sources)))
    return items
