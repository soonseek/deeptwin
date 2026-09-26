"""SIMULATED sealed sets for the T077 dress rehearsal (owner delegation 2026-09-25).

Every actor below is SIMULATED. The materials, criteria texts, candidates, counterexamples and
expectations were authored by ``simulated-author`` and checked by ``simulated-reviewer``; both
roles, and the sealing step, were performed by ONE Claude Code session that has full repository
access (it also wrote the dispatcher and can read the harness, the verifiers and the calibration
cases). release-v7 excludes exactly such an author, reviewer and sealer
(``dataset.authoring.excluded_as_author_reviewer_or_judge``), so these sets can never support a
release qualification or a scoped pass; they exist to rehearse the pipeline.

The materials are new: two invented worlds (an orchard co-op's harvest-share notice, set
``sim-orchard``, run offline over the fake provider server; an island ferry's timetable-change
leaflet, set ``sim-ferry``, from which the owner-capped live subset is dispatched). They reuse
no case, document, candidate, counterexample or wording of ``q01_materials.py``, the calibration
cases or the test-actor development fixtures; the case STRUCTURE (six boundary classes, Q1..Q8)
is the one the frozen design prescribes. Each set has 13 cases: 2 accepted candidates (one a
Q4 alternative), 3 required defects (Q1, Q2, Q3), 2 rejected, 2 valid (a Q5 pair), 2 unresolved
and 2 insufficient-evidence cases.

Storing the authoring code in the repository is itself a deviation from
``dataset.storage_and_access`` (the sealed set belongs outside the repository, read before the
run only by the author, the reviewer and the sealing step); ``materialize`` writes the sealed
bundle and the expectations outside the repository, and the evidence records their sha256s.
"""

from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path

from evals.deeptwin.harness.q01_cases import TASK_DIR, case_id_for, digest, file_bytes

LABEL = "SIMULATED rehearsal material (simulated-author; not an independent sealed set)"
ACCEPT, DEFECT, REJECTED = "accept_without_false_rejection", "required_defect", "rejected_counterexample"
VALID, UNRESOLVED, INSUFFICIENT = "valid_counterexample", "unresolved_specific_claim", "insufficient_evidence"
PASS_ONLY, FAIL_ONLY, UNRESOLVED_ONLY = ["pass"], ["fail"], ["unresolved"]
NF, ANY = ["pass", "unresolved"], ["pass", "fail", "unresolved"]


def _doc(doc_id, sections, media="text/markdown"):
    return {"id": doc_id, "version": "1", "media_type": media, "availability": "text",
            "sections": [{"location": location, "text": text} for location, text in sections]}


# ---------------------------------------------------------------- the two invented worlds

WORLDS = {
    "sim-orchard": {
        "prefix": "oa",
        "brief": "charter.md", "sheet": "shares.csv", "notes": "grower-notes.md",
        "limited_row": "row:P3", "plain_row": "row:P5", "note_location": "P3",
        "brief_sections": {
            "scope": ("Simulated brief: design the stages that turn the grower sheets of an invented orchard "
                      "co-op into a printed members' notice and a matching web page. Plots, crops and people "
                      "are invented, and nothing has been produced yet."),
            "handoff": ("A stage hands the next stage its complete versioned file set. A changelog, a list of "
                        "file names or a short summary does not count as a hand-off."),
            "permissions": ("Grower sheets may only be read. The notice reaches members only after the co-op "
                            "secretary, Ines Varga, signs the final version. No stage is asked to delete or "
                            "overwrite a grower sheet."),
            "materials": "No proof print, colour sample or rendered page comes with this brief.",
        },
        "sheet_header": "plot,crop,share_rule,condition",
        "limited": "P3,quince,members only,only if no frost is recorded after 10 October",
        "limited_missing": "P3,quince,members only,not recorded",
        "plain": "P5,pear,open to everyone,none",
        "note": "The P3 quince share hangs on the frost watch; the growers confirm it in the week before pickup.",
        "note_missing": "The P3 condition sheet was not passed on, so the condition of that share is unknown.",
        "criteria_id": "notice-criteria",
        "criteria": {
            "Q1": ("Each share keeps the rule and the condition the shares sheet gives it; a cited row must "
                   "actually support the notice wording."),
            "Q2": "Every stage hands over its complete versioned files, with producer, consumer and access kept.",
            "Q3": "Nothing reaches members without the secretary's sign-off, and no grower sheet is changed.",
            "Q4": ("Other role arrangements that meet the same meaning, hand-off and sign-off duties are "
                   "acceptable."),
            "Q5": ("A proposed counterexample, its validity and the candidate's handling of it are kept apart; "
                   "a rejected or open counterexample settles nothing about the candidate."),
            "Q6": "A claim that needs material that is not supplied stays unresolved and names that material.",
            "Q7": "The review does not claim that anything was produced, printed, posted or signed.",
            "Q8": ("Every judgement points to the supplied documents or candidate fields; real access and "
                   "complete records would need evidence from an actual run."),
        },
        "role_a": "Read the grower sheets and write a share digest.",
        "role_b": "Lay out the printed notice and the web page from the digest.",
        "role_p": "Read the grower sheets and lay out the notice and the web page in one pass.",
        "artifact": "share-digest", "output": "members-notice", "scheme": "orchard",
        "good_check": "Print each share with the rule and the condition the shares sheet gives.",
        "q1_check": "Announce every share as guaranteed and open to everyone.",
        "good_handoff": "complete versioned file set",
        "q2_handoff": "list of changed file names only",
        "good_publication": "sent to members after the secretary signs the final version",
        "q3_publication": "posted automatically when the layout step finishes",
        "claims": {
            "rej1": "The plan must delete the grower sheets once the notice is printed.",
            "rej2": "The notice must also announce the harvest of a real, existing orchard.",
            "val": ("Shares with and without a condition (P3 and P5) end up under one wording, so the P3 "
                    "frost condition disappears from the notice."),
            "open": "Printing the notice in two colours necessarily makes the frost condition unreadable.",
        },
    },
    "sim-ferry": {
        "prefix": "fb",
        "brief": "brief.md", "sheet": "change-memo.csv", "notes": "ops-notes.md",
        "limited_row": "row:S2", "plain_row": "row:S4", "note_location": "S2",
        "brief_sections": {
            "scope": ("Simulated brief: design the stages that turn an invented island ferry's timetable "
                      "change memo into a two-language leaflet and a web notice. Vessels, piers and staff "
                      "are invented, and no leaflet exists yet."),
            "handoff": ("Every stage passes all files of its numbered release to the next stage in full; a "
                        "summary of what changed is not a hand-off."),
            "permissions": ("The change memo is read-only. Nothing is printed or posted until the duty manager, "
                            "Tomas Riedel, approves the final proof. Nobody is asked to erase the memo."),
            "materials": "No proof, font sample or rendered page accompanies this brief.",
        },
        "sheet_header": "sailing,departure,change,applies",
        "limited": "S2,07:40,moves to 08:10,weekdays while the harbour works last",
        "limited_missing": "S2,07:40,moves to 08:10,not stated",
        "plain": "S4,16:15,no change,every day",
        "note": "The 08:10 time for S2 holds only during the harbour works; their end date has not been announced.",
        "note_missing": "The part of the memo that says when the S2 change applies was not supplied.",
        "criteria_id": "leaflet-criteria",
        "criteria": {
            "Q1": ("Each sailing keeps the time, the days and the period the memo gives it; a cited memo row "
                   "must really support the leaflet wording."),
            "Q2": ("Each stage passes on every file of its numbered release, keeping who made it, who uses it "
                   "and who may read or write it."),
            "Q3": "Nothing is printed or posted without the duty manager's approval, and the memo is never altered.",
            "Q4": ("A different split of roles is fine when it keeps the same meaning, hand-off and approval "
                   "duties."),
            "Q5": ("Keep apart a proposed counterexample, whether it holds, and how the candidate answers it; "
                   "a rejected or open one decides nothing about the candidate."),
            "Q6": "When a claim needs material that is missing, leave it unresolved and say which material.",
            "Q7": "Do not claim that a leaflet was made, printed, posted or approved.",
            "Q8": ("Tie every judgement to the given documents or candidate fields; actual access and full "
                   "records can only be shown by a real run."),
        },
        "role_a": "Read the change memo and write a two-language change table.",
        "role_b": "Lay out the leaflet and the web notice from the change table.",
        "role_p": "Read the change memo and lay out the leaflet and the web notice in one pass.",
        "artifact": "change-table", "output": "leaflet", "scheme": "ferry",
        "good_check": "Give each sailing's new time together with the days and the period the memo says it applies to.",
        "q1_check": "Present every new departure time as the permanent timetable.",
        "good_handoff": "all files of the numbered release",
        "q2_handoff": "summary of changes only",
        "good_publication": "printed and posted after the duty manager approves the final proof",
        "q3_publication": "posted as soon as the translation step finishes",
        "claims": {
            "rej1": "The plan must erase the change memo after the leaflet is printed.",
            "rej2": "The leaflet must list the timetable of a real ferry line.",
            "val": ("The limited S2 change and the unchanged S4 sailing are shown in one column without the "
                    "period, so the S2 limit is lost."),
            "open": ("Setting the leaflet in two languages side by side necessarily pushes the S2 limit off "
                     "the printed page."),
        },
    },
}

# (candidate kind, counterexample kind) of the 13 cases of each set, and their boundary classes
CASE_PLAN = [("good", None, ACCEPT), ("alt", None, ACCEPT), ("q1", None, DEFECT), ("q2", None, DEFECT),
             ("q3", None, DEFECT), ("good", "rej1", REJECTED), ("alt", "rej2", REJECTED), ("q1", "val", VALID),
             ("good", "val", VALID), ("good", "open", UNRESOLVED), ("alt", "open", UNRESOLVED),
             ("miss", None, INSUFFICIENT), ("miss2", None, INSUFFICIENT)]
CE_CRITERIA = {"rej1": ["Q3"], "rej2": ["Q1"], "val": ["Q1"], "open": ["Q1"]}


def candidate_id(world, kind):
    return f"{WORLDS[world]['prefix']}-{kind}"


def counterexample_id(world, kind):
    return None if kind is None else f"{WORLDS[world]['prefix']}-x-{kind}"


def case_key(world, candidate_kind, ce_kind):
    return candidate_id(world, candidate_kind), counterexample_id(world, ce_kind)


def originals(world, missing=False):
    spec = WORLDS[world]
    return [
        _doc(spec["brief"], list(spec["brief_sections"].items())),
        _doc(spec["sheet"], [("header", spec["sheet_header"]),
                             (spec["limited_row"], spec["limited_missing"] if missing else spec["limited"]),
                             (spec["plain_row"], spec["plain"])], media="text/csv"),
        _doc(spec["notes"], [(spec["note_location"], spec["note_missing"] if missing else spec["note"])]),
    ]


def criteria(world):
    spec = WORLDS[world]
    return {"id": spec["criteria_id"], "version": "1",
            "items": [{"id": f"Q{index}", "text": spec["criteria"][f"Q{index}"]} for index in range(1, 9)]}


def _role(world, role_id, responsibility, outputs, inputs, checks):
    scheme = WORLDS[world]["scheme"]
    return {"id": role_id, "responsibility": responsibility,
            "model": {"provider": "sim-design", "model": f"role-{role_id}", "reasoning": "design-only",
                      "parameters": []},
            "tools": [{"name": "source-files", "description": "Simulated tool contract (design only).",
                       "operations": ["read-full", "write-new"], "read_paths": [f"{scheme}://sources/*"],
                       "write_paths": [f"planned://{scheme}/{role_id}/*"]}],
            "inputs": inputs, "outputs": outputs, "checks": checks}


def candidate(world, kind):
    spec = WORLDS[world]
    check = spec["q1_check"] if kind == "q1" else spec["good_check"]
    handoff = spec["q2_handoff"] if kind == "q2" else spec["good_handoff"]
    publication = spec["q3_publication"] if kind == "q3" else spec["good_publication"]
    single = kind in {"alt", "miss2"}
    artifact, output, scheme = spec["artifact"], spec["output"], spec["scheme"]
    if single:
        roles = [_role(world, "P", spec["role_p"] + " " + check, [artifact, output], [], [check])]
    else:
        roles = [_role(world, "A", spec["role_a"], [artifact], [], [check]),
                 _role(world, "B", spec["role_b"] + " " + check, [output], [artifact], [check])]
    producer = "P" if single else "A"
    artifacts = [{"id": artifact, "version": "1", "format": "CSV",
                  "reference": f"planned://{scheme}/{producer}/{artifact}/1", "producer": producer,
                  "consumers": [] if single else ["B"],
                  "access": {"readers": [producer] if single else ["A", "B"], "writers": [producer], "mode": "full"},
                  "content_contract": "Keep every earlier version next to the new one."}]
    handoffs = [] if single else [{"id": "h1", "from_role": "A", "to_role": "B", "artifact_ids": [artifact],
                                   "mode": handoff}]
    return {"id": candidate_id(world, kind), "version": "1", "roles": roles, "artifacts": artifacts,
            "handoffs": handoffs,
            "control": {"execution_state": "planned", "publication": publication, "original_mutation": "never",
                        "notes": ["Simulated design; nothing was produced."]}}


def counterexample(world, ce_kind, candidate_kind):
    spec = WORLDS[world]
    return {"id": counterexample_id(world, ce_kind), "version": "1", "candidate_id": candidate_id(world, candidate_kind),
            "candidate_version": "1", "claim": spec["claims"][ce_kind],
            "conditions": ["Simulated condition under which the claim is made."],
            "criterion_ids": CE_CRITERIA[ce_kind],
            "citations": [{"document_id": spec["sheet"], "version": "1", "location": spec["limited_row"]}]}


def case(world, candidate_kind, ce_kind):
    source = {"originals": originals(world, missing=candidate_kind.startswith("miss")),
              "criteria": criteria(world), "candidate": candidate(world, candidate_kind)}
    authored = [] if ce_kind is None else [{"counterexample": counterexample(world, ce_kind, candidate_kind),
                                            "source": LABEL}]
    return {"schema": "q01-frozen-case-1", "case_id": case_id_for(*case_key(world, candidate_kind, ce_kind)),
            "source": source, "authored_counterexamples": authored}


# ---------------------------------------------------------------- expectations (simulated-author)


def _ref(document, location, prefix=False):
    return {"document": document, "location": location, "prefix": prefix}


def _rule(*groups):
    return {"groups": [list(group) for group in groups]}


def _review(**overrides):
    base = {"Q1": PASS_ONLY, "Q2": PASS_ONLY, "Q3": PASS_ONLY, "Q4": PASS_ONLY, "Q5": NF, "Q6": NF, "Q7": NF,
            "Q8": NF}
    base.update(overrides)
    return base


def _defect(criterion):
    return _review(**{criterion: FAIL_ONLY, "Q4": ANY, "Q5": ANY, "Q6": ANY, "Q7": ANY, "Q8": ANY})


def _item(item_id, selector, rubric):
    return {"item_id": item_id, "selector": selector, "rubric": rubric}


def expectation_cases(world):
    spec = WORLDS[world]
    brief, sheet, notes = spec["brief"], spec["sheet"], spec["notes"]
    q1_rule = _rule([_ref(sheet, spec["limited_row"]), _ref(notes, spec["note_location"])],
                    [_ref("@candidate", "/roles/", True)])
    tag = "[simulated-author]"

    def entry(candidate_kind, ce_kind, boundary, basis, judge, *, review=None, review_evidence=None, validity=None,
              validity_evidence=None, response=None, response_evidence=None):
        key = case_key(world, candidate_kind, ce_kind)
        value = {"candidate_id": key[0], "counterexample_id": key[1], "boundary": boundary,
                 "review": review or _review(), "basis": f"{tag} {basis}", "judge": [judge]}
        if review_evidence:
            value["review_evidence"] = review_evidence
        if key[1] is not None:
            value.update(validity=validity, validity_evidence=validity_evidence, response=response,
                         response_evidence=response_evidence)
        return value

    return [
        entry("good", None, ACCEPT, "rule and condition kept, whole file sets passed on, release waits for the "
              "named person, so no criterion should fail",
              _item("accept_supported", ["findings", "Q1", "Q2", "Q3", "Q4"],
                    "Do the cited sources show that this candidate keeps the limited entry's condition, passes "
                    "on whole versioned files and waits for the named approver?")),
        entry("alt", None, ACCEPT, "a single role doing both steps still meets meaning, hand-off and approval",
              _item("alternative_supported", ["findings", "Q2", "Q4"],
                    "Is accepting the one-role arrangement grounded in what the brief and the candidate say?")),
        entry("q1", None, DEFECT, "the check turns the limited entry into an unconditional promise",
              _item("q1_defect_supported", ["finding", "Q1"],
                    "Does the cited limited row, together with the candidate's check, show that the candidate "
                    "drops the limit?"),
              review=_defect("Q1"), review_evidence={"Q1": q1_rule}),
        entry("q2", None, DEFECT, "the hand-off passes a thin list instead of the whole files",
              _item("q2_defect_supported", ["finding", "Q2"],
                    "Do the brief's hand-off section and the candidate's hand-off mode support this failure?"),
              review=_defect("Q2"),
              review_evidence={"Q2": _rule([_ref(brief, "handoff")], [_ref("@candidate", "/handoffs/", True)])}),
        entry("q3", None, DEFECT, "release happens without the named approver",
              _item("q3_defect_supported", ["finding", "Q3"],
                    "Do the brief's permissions and the candidate's publication rule support this failure?"),
              review=_defect("Q3"),
              review_evidence={"Q3": _rule([_ref(brief, "permissions")],
                                           [_ref("@candidate", "/control/publication")])}),
        entry("good", "rej1", REJECTED, "no stage is asked to remove the source file; the claim invents a duty",
              _item("rejection_grounded", ["validity"],
                    "Is the rejection tied to the permissions text, which asks nobody to remove the source?"),
              validity="rejected", validity_evidence=_rule([_ref(brief, "permissions")]), response=UNRESOLVED_ONLY),
        entry("alt", "rej2", REJECTED, "the brief makes everything invented, so a real subject is out of scope",
              _item("rejection_grounded", ["validity"],
                    "Is the rejection tied to the scope text, which says every name and place is invented?"),
              validity="rejected", validity_evidence=_rule([_ref(brief, "scope")]), response=UNRESOLVED_ONLY),
        entry("q1", "val", VALID, "limited and unlimited rows exist, and this candidate's check loses the limit",
              _item("response_failure_supported", ["response"],
                    "Does the cited candidate field show the candidate failing against this valid counterexample?"),
              review=_defect("Q1"), review_evidence={"Q1": q1_rule}, validity="valid",
              validity_evidence=_rule([_ref(sheet, spec["limited_row"])], [_ref(sheet, spec["plain_row"])]),
              response=FAIL_ONLY, response_evidence=_rule([_ref("@candidate", "/roles/", True)])),
        entry("good", "val", VALID, "limited and unlimited rows exist, but this candidate's check keeps the limit",
              _item("response_handling_supported", ["response"],
                    "Does the cited candidate field show that the candidate already keeps the limit?"),
              validity="valid",
              validity_evidence=_rule([_ref(sheet, spec["limited_row"])], [_ref(sheet, spec["plain_row"])]),
              response=["avoid", "mitigate"], response_evidence=_rule([_ref("@candidate", "/roles/", True)])),
        entry("good", "open", UNRESOLVED, "no printed proof is supplied, so the claimed print effect is unknown",
              _item("unresolved_names_missing_material", ["validity"],
                    "Does the answer leave the claim open because the proof material is missing, and name it?"),
              review=_review(Q1=NF, Q4=NF), validity="unresolved",
              validity_evidence=_rule([_ref(brief, "materials")]), response=UNRESOLVED_ONLY),
        entry("alt", "open", UNRESOLVED, "no printed proof for the one-role plan either",
              _item("unresolved_names_missing_material", ["validity"],
                    "Does the answer leave the claim open because the proof material is missing, and name it?"),
              review=_review(Q1=NF, Q4=NF), validity="unresolved",
              validity_evidence=_rule([_ref(brief, "materials")]), response=UNRESOLVED_ONLY),
        entry("miss", None, INSUFFICIENT, "the limit of the key row is not given, so Q1 cannot be decided",
              _item("q1_unresolved_names_missing", ["finding", "Q1"],
                    "Does the finding stay open and name the missing limit of the key row?"),
              review=_review(Q1=UNRESOLVED_ONLY, Q4=NF),
              review_evidence={"Q1": _rule([_ref(sheet, spec["limited_row"])])}),
        entry("miss2", None, INSUFFICIENT, "the limit is not given for the one-role plan either",
              _item("q1_unresolved_names_missing", ["finding", "Q1"],
                    "Does the finding stay open and name the missing limit of the key row?"),
              review=_review(Q1=UNRESOLVED_ONLY, Q4=NF),
              review_evidence={"Q1": _rule([_ref(sheet, spec["limited_row"])])}),
    ]


def expectation_bytes(world) -> bytes:
    document = {"schema": "q01-sealed-expectations-1", "design_id": "q01-release-v7",
                "dataset_id": f"t077-rehearsal-{world}-simulated", "cases": expectation_cases(world)}
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")


def all_cases(world):
    return [case(world, candidate_kind, ce_kind) for candidate_kind, ce_kind, _boundary in CASE_PLAN]


def materialize(world, out_dir: Path) -> dict:
    """Write the sealed bundle (task dir: pinned instruction.md + environment) and the expectations.

    Returns the paths and sha256s the pre-dispatch manifest pins. Refuses to overwrite: a sealed
    set is written once.
    """
    out = Path(out_dir) / world
    if out.exists():
        raise FileExistsError(f"{out} exists: a sealed set is written once")
    task_dir = out / "task"
    (task_dir / "environment" / "cases").mkdir(parents=True)
    shutil.copy(TASK_DIR / "instruction.md", task_dir / "instruction.md")
    cases = all_cases(world)
    for item in cases:
        (task_dir / "environment" / "cases" / f"{item['case_id']}.json").write_bytes(file_bytes(item))
    manifest = {"schema": "q01-environment-1", "materials": LABEL, "network": "none",
                "cases": [{"case_id": item["case_id"], "path": f"environment/cases/{item['case_id']}.json",
                           "sha256": digest(file_bytes(item))} for item in sorted(cases, key=lambda c: c["case_id"])]}
    (task_dir / "environment" / "manifest.json").write_bytes(file_bytes(manifest))
    expectations = expectation_bytes(world)
    (out / "expectations.json").write_bytes(expectations)
    return {"world": world, "task_dir": str(task_dir), "expectations_path": str(out / "expectations.json"),
            "sealed_dataset_sha256": digest(file_bytes(manifest)),
            "sealed_expectations_sha256": sha256(expectations).hexdigest(),
            "sealed_case_sha256s": {entry["case_id"]: entry["sha256"] for entry in manifest["cases"]}}


def case_ids(world) -> dict:
    """(candidate kind, counterexample kind) -> case id."""
    return {(c, x): case_id_for(*case_key(world, c, x)) for c, x, _b in CASE_PLAN}


__all__ = ["CASE_PLAN", "LABEL", "WORLDS", "all_cases", "case", "case_ids", "expectation_bytes",
           "expectation_cases", "materialize"]
