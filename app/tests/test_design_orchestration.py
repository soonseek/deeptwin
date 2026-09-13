"""US2 bounded supplementation orchestration (T036 third slice).

`propose_environment` ties the offline design arc together: generate up to
the requested candidates, criticize every one through the live driver, and
assemble the honest pool; when fewer than three structurally different
passed candidates exist and rounds remain, one bounded supplementation
round generates more — regeneration preserves every prior candidate,
verdict and exclusion (experience.md: 다시 생성해도 이전 후보·평가·제시
순서·선택 이력은 남는다), rounds are hard-bounded, and a shortfall ends as
the real count with reasons, never as padding. A criticism-contract
violation is a typed refusal of the whole proposal, never a silently
skipped candidate.
"""

import dataclasses
import json as _json

import pytest

from app.services.design_criticism import DesignCriticismError
from app.services.design_orchestration import (
    EnvironmentProposal,
    propose_environment,
)
from app.tests.test_design_generation import graph_value, prepared, proposed_lens
from app.tests.test_design_live import model_json

MODEL_ID = "claude-sonnet-5"


class ScriptedRounds:
    """Return one scripted generation response per generation round."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, system, user):
        self.calls += 1
        return self.responses.pop(0)


def auto_critic(reject_ids=frozenset(), fail=frozenset()):
    """A stage-aware scripted critic: passes review, abstains at proposal.

    Candidates in ``reject_ids`` get one failed review finding; candidates
    in ``fail`` produce contract-violating garbage.
    """

    def turn(system, user):
        payload = _json.loads(user)["input"]
        candidate = payload["candidate"]
        if candidate["id"] in fail:
            return "not json"
        if "lens_pack" in payload:  # proposal stage → abstain honestly
            return _json.dumps({
                "candidate_id": candidate["id"],
                "candidate_version": candidate["version"],
                "purpose": "counterexample_proposal",
                "status": "abstain",
                "counterexamples": [],
                "lens_use": [{
                    "rule_id": rule["id"],
                    "rule_version": rule["version"],
                    "status": "abstain",
                    "reason": "반례를 세울 근거가 부족하다.",
                    "evidence": [{
                        "document_id": payload["originals"][0]["id"],
                        "version": payload["originals"][0]["version"],
                        "location": "work_model.risks",
                    }],
                    "counterexample_ids": [],
                } for rule in payload["lens_pack"]["rules"]],
                "uncertainties": ["반례 근거 부족"],
            })
        criteria = [item["id"] for item in payload["criteria"]["items"]]
        rejected = candidate["id"] in reject_ids
        findings = []
        for index, criterion in enumerate(criteria):
            findings.append({
                "criterion_id": criterion,
                "status": "fail" if rejected and index == 0 else "pass",
                "evidence": [{
                    "document_id": payload["originals"][0]["id"],
                    "version": payload["originals"][0]["version"],
                    "location": "work_model.goals",
                }],
                "reason": "근거가 그래프에 있다." if not rejected else "필수 결함",
                "uncertainties": [],
            })
        return _json.dumps({
            "candidate_id": candidate["id"],
            "candidate_version": candidate["version"],
            "purpose": "review",
            "findings": findings,
        })

    return turn


def graphs():
    target, _lens, decision, request, base = prepared()
    registry, _proposed = proposed_lens(target)
    reshaped = graph_value(
        target, decision.decision_ref.as_dict(), graph_suffix=205,
    )
    for contract in reshaped["artifact_contracts"]:
        if contract["artifact_contract_id"] == "final-script":
            contract["max_items"] = 1
            contract["media_types"] = ["text/markdown"]
    third = graph_value(
        target, decision.decision_ref.as_dict(), graph_suffix=206,
    )
    for contract in third["artifact_contracts"]:
        if contract["artifact_contract_id"] == "research-notes":
            contract["max_items"] = 1
            contract["min_items"] = 1
            contract["max_total_bytes"] = 524_288
    return request, registry, base, reshaped, third


def test_one_short_round_supplements_once_and_preserves_everything():
    request, registry, base, reshaped, third = graphs()
    generation = ScriptedRounds([
        model_json(base, reshaped),  # round 1: two distinct shapes
        model_json(third),           # supplementation: a third shape
    ])
    proposal = propose_environment(
        request, registry,
        generation_turn=generation, criticism_turn=auto_critic(),
        model_id=MODEL_ID, max_rounds=3,
    )
    assert type(proposal) is EnvironmentProposal
    assert proposal.rounds == 2
    assert len(proposal.pool.presented) == 3
    assert len(proposal.candidates) == 3  # every candidate preserved
    assert len(proposal.verdicts) == 3
    assert len(proposal.generation_records) == 2
    assert len(proposal.criticism_runs) == 3
    assert generation.calls == 2


def test_a_full_first_round_never_spends_a_supplementation_call():
    request, registry, base, reshaped, third = graphs()
    generation = ScriptedRounds([model_json(base, reshaped, third)])
    proposal = propose_environment(
        request, registry,
        generation_turn=generation, criticism_turn=auto_critic(),
        model_id=MODEL_ID, max_rounds=3,
    )
    assert proposal.rounds == 1
    assert len(proposal.pool.presented) == 3
    assert generation.calls == 1


def test_a_shortfall_ends_honestly_with_reasons():
    request, registry, base, reshaped, _third = graphs()
    generation = ScriptedRounds([model_json(base, reshaped)])
    proposal = propose_environment(
        request, registry,
        generation_turn=generation, criticism_turn=auto_critic(),
        model_id=MODEL_ID, max_rounds=1,
    )
    assert proposal.rounds == 1
    assert len(proposal.pool.presented) == 2
    assert proposal.pool.supplementation_available is True
    assert proposal.pool.passed_count == 2


def test_rejected_candidates_stay_recorded_with_their_reasons():
    request, registry, base, reshaped, third = graphs()

    class RejectSecond:
        """Reject whichever candidate the second criticism run reviews."""

        def __init__(self):
            self.reviewed = []

        def __call__(self, system, user):
            payload = _json.loads(user)["input"]
            candidate_id = payload["candidate"]["id"]
            if candidate_id not in self.reviewed:
                self.reviewed.append(candidate_id)
            reject = {self.reviewed[1]} if len(self.reviewed) > 1 else set()
            return auto_critic(reject_ids=reject)(system, user)

    generation = ScriptedRounds([model_json(base, reshaped), model_json(third)])
    proposal = propose_environment(
        request, registry,
        generation_turn=generation, criticism_turn=RejectSecond(),
        model_id=MODEL_ID, max_rounds=2,
    )
    assert proposal.rounds == 2
    assert len(proposal.pool.presented) == 2
    assert any(
        reason.startswith("rejected:")
        for _cid, reason in proposal.pool.excluded
    )
    assert len(proposal.candidates) == 3  # the rejected one is preserved


def test_bounds_and_contract_violations_are_typed_refusals():
    request, registry, base, _reshaped, _third = graphs()
    with pytest.raises(DesignCriticismError):
        propose_environment(
            request, registry,
            generation_turn=ScriptedRounds([model_json(base)]),
            criticism_turn=auto_critic(),
            model_id=MODEL_ID, max_rounds=0,
        )
    with pytest.raises(DesignCriticismError):
        propose_environment(
            request, registry,
            generation_turn=ScriptedRounds([model_json(base)]),
            criticism_turn=auto_critic(),
            model_id=MODEL_ID, max_rounds=4,
        )
    with pytest.raises(DesignCriticismError):
        # a criticism-contract violation refuses the proposal, never
        # silently skips the candidate
        propose_environment(
            request, registry,
            generation_turn=ScriptedRounds([model_json(base)]),
            criticism_turn=lambda system, user: "garbage",
            model_id=MODEL_ID, max_rounds=1,
        )
    proposal = propose_environment(
        request, registry,
        generation_turn=ScriptedRounds([model_json(base)]),
        criticism_turn=auto_critic(),
        model_id=MODEL_ID, max_rounds=1,
    )
    with pytest.raises(TypeError):
        dataclasses.replace(proposal, rounds=1)
