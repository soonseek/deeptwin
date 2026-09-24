"""Offline Q01 test support: synthetic selection rig and scripted critic transports.

Nothing here contacts a provider. The scripted critic answers from a small
hand-written table for the synthetic fixtures only; it is not a judge and not
an answer key for any agent input.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from app.model_catalog import ModelCatalog
from app.model_selection import ModelSelection
from app.storage import Store
from app.tests.test_model_catalog import CodexFixture
from evals.deeptwin.harness.q01_cases import TASK_DIR, case_id_for, digest, file_bytes
from evals.deeptwin.harness.q01_harness import Q01Trial, TrialConfig


def make_rig(tmp_path: Path, **config) -> SimpleNamespace:
    store = Store(tmp_path / "synthetic-intake")
    provider = CodexFixture(store)
    catalog = ModelCatalog(store, provider)
    snapshot = catalog.refresh("codex")  # explicit offline fixture provider
    model = snapshot["models"][0]
    effort = model["reasoning_efforts"][0]["value"]
    selections = ModelSelection(store, catalog)
    work = store.create_work("synthetic Q01 harness trial")
    choice = {"provider": "codex", "mode": "subscription", "model": model["model"], "effort": effort,
              "catalog_id": snapshot["catalog_id"]}
    selections.save(work["id"], 0, choice)
    options = {"call_seconds": 5.0, "run_seconds": 60.0}
    options.update(config)
    base = tmp_path / "trials"
    base.mkdir()
    return SimpleNamespace(store=store, selections=selections, work=work, base=base, model=model["model"],
                           choice=choice, efforts=[item["value"] for item in model["reasoning_efforts"]],
                           config=TrialConfig(selections, work["id"], 1, **options))


def run(rig, case_id, turn, *, task_dir=TASK_DIR, **config):
    cfg = rig.config if not config else TrialConfig(rig.selections, rig.work["id"], 1, **{
        "call_seconds": rig.config.call_seconds, "run_seconds": rig.config.run_seconds, **config})
    return Q01Trial(case_id, turn, base_dir=rig.base, config=cfg, task_dir=task_dir).run()


CASE = {key: case_id_for(*key) for key in [
    ("c71", None), ("c24", None), ("c86", None), ("c09", None), ("c53", None), ("c71", "ce-29"),
    ("c86", "ce-17"), ("c71", "ce-17"), ("c42", "ce-43"), ("c18", None)]}


def cite(visible, document_id, location):
    if document_id == "@candidate":
        return {"document_id": visible["candidate"]["id"], "version": visible["candidate"]["version"],
                "location": location}
    if document_id == "fixed-criteria":
        return {"document_id": "fixed-criteria", "version": visible["criteria"]["version"], "location": location}
    doc = next(item for item in visible["originals"] if item["id"] == document_id)
    return {"document_id": document_id, "version": doc["version"], "location": location}


# Synthetic scripted answers for the fixtures (candidate id -> non-pass findings).
REVIEW_STATUS = {"c86": {"Q1": "fail"}, "c09": {"Q2": "fail"}, "c53": {"Q3": "fail"}, "c18": {"Q1": "unresolved"}}
FINDING_EVIDENCE = {
    ("Q1", "fail"): [("catalog.csv", "row:M01"), ("@candidate", "/roles/1/responsibility")],
    ("Q2", "fail"): [("work-contract.md", "handoff"), ("@candidate", "/handoffs/0/mode")],
    ("Q3", "fail"): [("work-contract.md", "permissions"), ("@candidate", "/control/publication")],
    ("Q1", "unresolved"): [("catalog.csv", "row:M01"), ("curation-notes.md", "M01")],
}
VALIDITY = {"ce-29": ("rejected", [("work-contract.md", "permissions")]),
            "ce-17": ("valid", [("catalog.csv", "row:M01"), ("catalog.csv", "row:M02")]),
            "ce-43": ("unresolved", [("source-access.json", "media-status")])}
RESPONSE = {"c86": ("fail", [("@candidate", "/roles/1/responsibility")]),
            "c71": ("avoid", [("@candidate", "/roles/0/checks/0")])}


class ScriptedCritic:
    """``(system, user) -> str`` fixture; ``overrides`` rewrite one purpose's answer."""

    def __init__(self, overrides=None, propose=False):
        self.calls = []
        self.overrides = overrides or {}
        self.propose = propose

    def __call__(self, system, user):
        self.calls.append((system, user))
        payload = json.loads(user)
        purpose, visible = payload["purpose"], payload["input"]
        answer = getattr(self, "_" + purpose)(visible)
        override = self.overrides.get(purpose)
        if callable(override):
            answer = override(visible, answer)
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)

    @staticmethod
    def _header(purpose, visible):
        return {"purpose": purpose, "candidate_id": visible["candidate"]["id"],
                "candidate_version": visible["candidate"]["version"]}

    def _review(self, visible):
        statuses = REVIEW_STATUS.get(visible["candidate"]["id"], {})
        findings = []
        for item in visible["criteria"]["items"]:
            status = statuses.get(item["id"], "pass")
            refs = FINDING_EVIDENCE.get((item["id"], status), [("work-contract.md", "requirements")])
            findings.append({"criterion_id": item["id"], "status": status,
                             "evidence": [cite(visible, *ref) for ref in refs],
                             "reason": "Synthetic scripted reason for an offline fixture.",
                             "uncertainties": ["Needed evidence is not supplied."] if status == "unresolved" else []})
        return {**self._header("review", visible), "findings": findings}

    def _counterexample_proposal(self, visible):
        header = self._header("counterexample_proposal", visible)
        rules = visible["lens_pack"]["rules"]
        if not self.propose:
            return {**header, "status": "abstain", "counterexamples": [], "uncertainties": ["No supported proposal."],
                    "lens_use": [{"rule_id": rule["id"], "rule_version": rule["version"], "status": "abstain",
                                  "reason": "Synthetic abstention.", "counterexample_ids": [],
                                  "evidence": [cite(visible, "work-contract.md", "requirements")]} for rule in rules]}
        example = {"id": "px-1", "version": "1", "candidate_id": visible["candidate"]["id"],
                   "candidate_version": visible["candidate"]["version"],
                   "claim": "Synthetic proposed claim for lineage testing.", "conditions": ["Synthetic condition."],
                   "criterion_ids": ["Q1"], "citations": [cite(visible, "catalog.csv", "row:M01")]}
        return {**header, "status": "proposed", "counterexamples": [example], "uncertainties": [],
                "lens_use": [{"rule_id": rule["id"], "rule_version": rule["version"],
                              "status": "used" if index == 0 else "excluded", "reason": "Synthetic lens use.",
                              "counterexample_ids": ["px-1"] if index == 0 else [],
                              "evidence": [cite(visible, "catalog.csv", "row:M01")]}
                             for index, rule in enumerate(rules)]}

    def _counterexample_validity(self, visible):
        example = visible["counterexample"]
        status, refs = VALIDITY.get(example["id"], ("unresolved", [("catalog.csv", "row:M01")]))
        return {"purpose": "counterexample_validity", "candidate_id": visible["candidate"]["id"],
                "candidate_version": visible["candidate"]["version"], "counterexample_id": example["id"],
                "counterexample_version": example["version"], "status": status,
                "evidence": [cite(visible, *ref) for ref in refs], "reason": "Synthetic validity reason.",
                "uncertainties": ["Image data and feature positions are not supplied."] if status == "unresolved"
                else []}

    def _candidate_response(self, visible):
        validity = visible["validity"]["status"]
        status, refs = ("unresolved", [("catalog.csv", "row:M01")])
        if validity == "valid":
            status, refs = RESPONSE.get(visible["candidate"]["id"], ("mitigate", [("@candidate", "/roles/0/checks/0")]))
        return {**self._header("candidate_response", visible), "counterexample_id": visible["counterexample"]["id"],
                "counterexample_version": visible["counterexample"]["version"], "validity_status": validity,
                "status": status, "evidence": [cite(visible, *ref) for ref in refs],
                "reason": "Synthetic response reason.",
                "uncertainties": [] if status != "unresolved" else ["Validity does not allow a conclusive response."]}


def set_status(purpose_key, status, **fields):
    """Override helper: change one status field in a purpose answer."""
    def override(visible, answer):
        answer = dict(answer)
        answer[purpose_key] = status
        answer.update(fields)
        return answer
    return override


def copy_task(tmp_path: Path) -> Path:
    target = tmp_path / "task-copy" / "v01-q01"
    shutil.copytree(TASK_DIR, target)
    return target


def rewrite_case(task_dir: Path, case_id: str, mutate) -> None:
    manifest_path = task_dir / "environment" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["cases"] if item["case_id"] == case_id)
    path = task_dir / entry["path"]
    case = json.loads(path.read_text(encoding="utf-8"))
    mutate(case)
    path.write_bytes(file_bytes(case))
    entry["sha256"] = digest(file_bytes(case))
    manifest_path.write_bytes(file_bytes(manifest))
