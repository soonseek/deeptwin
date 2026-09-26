"""SIMULATED actors of the offline T077 rehearsal: a scripted critic and a judge stub.

``SimulatedCritic`` answers the critic prompts of the offline rehearsal through the offline fake
provider server (``claude_mock.MockClaude``). It is a hand-written answer table over the
simulated sets, written by the same Claude Code session that authored them (simulated-author);
it tests the pipeline, never a critic. ``SimulatedJudgeStub`` is ``simulated-judge`` of the
offline run: a deterministic stub returning ``supported`` with stub provider ids, written by the
same session. Neither is independent of anything.
"""

from __future__ import annotations

import itertools
import json
from copy import deepcopy
from hashlib import sha256

from evals.deeptwin.verifiers.q01_core import AttestedJudgement

from .simulated_sets import WORLDS

STUB_JUDGE_IDENTITY = "simulated-judge (offline deterministic stub; not an independent judge)"
STUB_JUDGE_MODEL = "simulated-judge-stub-1"
STUB_JUDGE_PROMPT_DIGEST = sha256(b"t077 rehearsal simulated-judge stub: always answers supported").hexdigest()


class SimulatedCritic:
    """Scripted ``(system, user) -> str`` answers for one simulated world."""

    def __init__(self, world: str, **overrides):
        self.spec, self.overrides, self.calls = WORLDS[world], overrides, 0

    def __call__(self, system, user):
        self.calls += 1
        payload = json.loads(user)
        purpose, visible = payload["purpose"], payload["input"]
        answer = getattr(self, "_" + purpose)(visible)
        if purpose in self.overrides:
            answer = self.overrides[purpose](visible, deepcopy(answer))
        return json.dumps(answer)

    def _cite(self, visible, document, location):
        if document == "@candidate":
            return {"document_id": visible["candidate"]["id"], "version": "1", "location": location}
        version = visible["criteria"]["version"] if document == visible["criteria"]["id"] else "1"
        return {"document_id": document, "version": version, "location": location}

    @staticmethod
    def _kind(identifier, marker="-"):
        return identifier.split(marker, 1)[1]

    @staticmethod
    def _head(purpose, visible):
        return {"purpose": purpose, "candidate_id": visible["candidate"]["id"], "candidate_version": "1"}

    def _review(self, visible):
        spec = self.spec
        table = {
            "q1": {"Q1": ("fail", [(spec["sheet"], spec["limited_row"]), ("@candidate", "/roles/1/checks/0")])},
            "q2": {"Q2": ("fail", [(spec["brief"], "handoff"), ("@candidate", "/handoffs/0/mode")])},
            "q3": {"Q3": ("fail", [(spec["brief"], "permissions"), ("@candidate", "/control/publication")])},
            "miss": {"Q1": ("unresolved", [(spec["sheet"], spec["limited_row"]), (spec["notes"], spec["note_location"])])},
            "miss2": {"Q1": ("unresolved", [(spec["sheet"], spec["limited_row"]),
                                            (spec["notes"], spec["note_location"])])},
        }.get(self._kind(visible["candidate"]["id"]), {})
        findings = []
        for criterion in (item["id"] for item in visible["criteria"]["items"]):
            status, refs = table.get(criterion, ("pass", [(spec["brief"], "scope")]))
            findings.append({"criterion_id": criterion, "status": status,
                             "evidence": [self._cite(visible, *ref) for ref in refs],
                             "reason": "Simulated scripted reason.",
                             "uncertainties": ["The needed material is not supplied."] if status == "unresolved" else []})
        return {**self._head("review", visible), "findings": findings}

    def _counterexample_proposal(self, visible):
        return {**self._head("counterexample_proposal", visible), "status": "abstain", "counterexamples": [],
                "uncertainties": ["Simulated scripted abstention."], "lens_use": []}

    def _counterexample_validity(self, visible):
        spec = self.spec
        example = visible["counterexample"]
        status, refs = {
            "rej1": ("rejected", [(spec["brief"], "permissions")]),
            "rej2": ("rejected", [(spec["brief"], "scope")]),
            "val": ("valid", [(spec["sheet"], spec["limited_row"]), (spec["sheet"], spec["plain_row"])]),
            "open": ("unresolved", [(spec["brief"], "materials")]),
        }[self._kind(example["id"], "-x-")]
        return {**self._head("counterexample_validity", visible), "counterexample_id": example["id"],
                "counterexample_version": "1", "status": status,
                "evidence": [self._cite(visible, *ref) for ref in refs], "reason": "Simulated scripted validity.",
                "uncertainties": ["No proof material is supplied."] if status == "unresolved" else []}

    def _candidate_response(self, visible):
        spec = self.spec
        validity = visible["validity"]["status"]
        status, refs = "unresolved", [(spec["notes"], spec["note_location"])]
        if validity == "valid":
            status, refs = (("fail", [("@candidate", "/roles/1/checks/0")])
                            if self._kind(visible["candidate"]["id"]) == "q1"
                            else ("avoid", [("@candidate", "/roles/0/checks/0")]))
        return {**self._head("candidate_response", visible), "counterexample_id": visible["counterexample"]["id"],
                "counterexample_version": "1", "validity_status": validity, "status": status,
                "evidence": [self._cite(visible, *ref) for ref in refs], "reason": "Simulated scripted response.",
                "uncertainties": ["Validity is not settled."] if status == "unresolved" else []}


_STUB_IDS = itertools.count(1)


class SimulatedJudgeStub:
    """simulated-judge of the offline rehearsal: answers ``supported`` with stub provider ids."""

    version = "t077-simulated-judge-stub-1"
    identity = STUB_JUDGE_IDENTITY
    prompt_digest = STUB_JUDGE_PROMPT_DIGEST

    def __init__(self):
        self.items = []

    def judge(self, item):
        self.items.append(item)
        return "supported"

    def judge_attested(self, item):
        status = self.judge(item)
        number = next(_STUB_IDS)
        raw = json.dumps({"verdict": status, "reason": "Simulated judge stub (offline, deterministic)."})
        return AttestedJudgement(raw, STUB_JUDGE_MODEL, f"req_simjudge{number:08d}", f"msg_simjudge{number:08d}")


__all__ = ["STUB_JUDGE_IDENTITY", "STUB_JUDGE_MODEL", "STUB_JUDGE_PROMPT_DIGEST", "SimulatedCritic",
           "SimulatedJudgeStub"]
