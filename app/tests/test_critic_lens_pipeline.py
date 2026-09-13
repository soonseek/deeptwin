"""T036: the qualified lens routing → LensPack → counterexample →
independent validity/response pipeline, with input isolation.

The registry's qualified lens decisions become the proposal stage's exact
LensPack; lens contribution and abstention are recorded per rule with
evidence and never invented (the parser refuses a lens_use set that does
not match the pack exactly, and a "used" entry must name counterexamples
while an abstaining one must not). Input isolation holds across stages:
the review sees NO lens identity at all, and validity/response see the
bound counterexample but never the lens pack or another critic's verdict
— so validity is genuinely independent of the proposer's lens framing
(runtime.md §1 critic-* profile; FR-004/FR-006).
"""

import json as _json

import pytest

from app.critic_contract import ResponseContractError, parse_response
from app.services.design_criticism import (
    prepare_candidate_proposal,
    prepare_candidate_review,
    prepare_candidate_validity,
)
from app.tests.test_design_criticism import _citation, live_pair
from app.tests.test_design_generation import proposed_lens


def pipeline():
    request, candidate = live_pair()
    registry, lens = proposed_lens(request.work_target)
    proposal_input = prepare_candidate_proposal(candidate, request, registry)
    payload = _json.loads(proposal_input.prompt)["input"]
    return request, candidate, registry, lens, proposal_input, payload


def counterexample(candidate, criterion_id, request):
    return {
        "id": "ce-lens-1",
        "version": "1",
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "claim": "렌즈의 반증 질문이 지목한 실패 조건이다.",
        "conditions": ["research 노드가 반례 자료를 놓친 경우"],
        "criterion_ids": [criterion_id],
        "citations": [_citation(request)],
    }


def test_qualified_lens_decisions_become_the_exact_pack():
    request, _candidate, _registry, lens, _input, payload = pipeline()
    pack = payload["lens_pack"]
    assert pack["id"] == f"lenses:{request.request_id}"
    rules = pack["rules"]
    assert len(rules) == 1
    assert rules[0]["id"] in str(lens.lens_ref)  # the exact qualified decision
    assert rules[0]["status"] == "research_draft"  # academic status honest


def test_contribution_and_abstention_are_recorded_per_rule():
    request, candidate, _registry, _lens, proposal_input, payload = pipeline()
    rule = payload["lens_pack"]["rules"][0]
    criterion = _json.loads(proposal_input.manifest_json)["criterion_ids"][0]
    cex = counterexample(candidate, criterion, request)
    used = parse_response(proposal_input, _json.dumps({
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "purpose": "counterexample_proposal",
        "status": "proposed",
        "counterexamples": [cex],
        "lens_use": [{
            "rule_id": rule["id"], "rule_version": rule["version"],
            "status": "used", "reason": "반증 질문이 이 반례를 지목한다.",
            "evidence": [_citation(request)],
            "counterexample_ids": ["ce-lens-1"],
        }],
        "uncertainties": [],
    }))
    assert used["lens_use"][0]["status"] == "used"
    with pytest.raises(ResponseContractError):
        # a "used" contribution must name the counterexamples it produced
        parse_response(proposal_input, _json.dumps({
            "candidate_id": candidate.candidate_id,
            "candidate_version": str(candidate.version),
            "purpose": "counterexample_proposal",
            "status": "proposed",
            "counterexamples": [cex],
            "lens_use": [{
                "rule_id": rule["id"], "rule_version": rule["version"],
                "status": "used", "reason": "이유",
                "evidence": [_citation(request)],
                "counterexample_ids": [],
            }],
            "uncertainties": [],
        }))
    with pytest.raises(ResponseContractError):
        # the lens_use set must match the pack exactly — no invented rules
        parse_response(proposal_input, _json.dumps({
            "candidate_id": candidate.candidate_id,
            "candidate_version": str(candidate.version),
            "purpose": "counterexample_proposal",
            "status": "proposed",
            "counterexamples": [cex],
            "lens_use": [{
                "rule_id": "L-INVENTED-99", "rule_version": rule["version"],
                "status": "used", "reason": "이유",
                "evidence": [_citation(request)],
                "counterexample_ids": ["ce-lens-1"],
            }],
            "uncertainties": [],
        }))


def test_input_isolation_across_the_stages():
    request, candidate, _registry, _lens, proposal_input, payload = pipeline()
    # the review stage sees no lens identity at all
    review_payload = _json.loads(
        prepare_candidate_review(candidate, request).prompt,
    )["input"]
    assert set(review_payload) == {"candidate", "criteria", "originals"}
    assert "lens" not in _json.dumps(review_payload)
    # validity sees the bound counterexample but never the lens pack or
    # any other critic's verdict
    criterion = _json.loads(proposal_input.manifest_json)["criterion_ids"][0]
    validity_payload = _json.loads(prepare_candidate_validity(
        candidate, request, counterexample(candidate, criterion, request),
    ).prompt)["input"]
    assert set(validity_payload) == {
        "candidate", "counterexample", "criteria", "originals",
    }
    assert "lens_pack" not in validity_payload
    flattened = _json.dumps(validity_payload)
    assert "verdict" not in flattened
    assert "review_findings" not in flattened
    del payload


def test_the_projection_carries_no_generator_identity():
    _request, candidate, _registry, _lens, _input, payload = pipeline()
    projected = _json.dumps(payload["candidate"])
    # the critic never learns which lens generated the candidate or any
    # self-score the generator produced
    assert candidate.audit_lens_refs  # the identity EXISTS on the record
    for ref in candidate.audit_lens_refs:
        assert ref not in projected
    assert "self_score" not in projected
