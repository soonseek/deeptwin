"""Projection of an accepted design candidate into the critic's field contract.

The critic pipeline reviews a candidate functional contract (roles, artifacts,
handoffs, control) — not the raw graph.  The projection must be deterministic and
faithful: real responsibilities, real bindings, every non-role mechanism surfaced in
the control notes, and the result must validate against the pure critic contract.
"""

import pytest

from app.critic_contract import Candidate
from app.services.design_criticism import (
    DesignCriticismError,
    critic_candidate_projection,
)
from app.services.design_live import run_candidate_generation
from app.tests.test_design_generation import prepared
from app.tests.test_design_live import MODEL_ID, model_json, scripted_model


def live_candidate(**kwargs):
    _target, _lens, _decision, request, graph = prepared(**kwargs)
    model_turn, _ = scripted_model(model_json(graph))
    result = run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)
    return result.candidates[0]


def test_projection_validates_against_the_pure_critic_contract():
    candidate = live_candidate()
    projection = critic_candidate_projection(candidate)
    validated = Candidate.model_validate(projection)
    assert validated.id == candidate.candidate_id
    assert validated.version == str(candidate.version)


def test_projection_is_deterministic():
    candidate = live_candidate()
    assert critic_candidate_projection(candidate) == critic_candidate_projection(candidate)


def test_roles_carry_faithful_responsibilities_bindings_and_slots():
    candidate = live_candidate()
    projection = critic_candidate_projection(candidate)
    roles = {role["id"]: role for role in projection["roles"]}
    assert set(roles) == {"research", "writer"}

    research = roles["research"]
    assert research["responsibility"] == (
        "공개 출처를 탐색하고 주장별 근거와 반증을 원형 링크로 정리한다."
    )
    assert research["model"]["provider"] == "model_choice"
    assert "model_choice:" in research["model"]["model"]
    assert research["inputs"] == []
    assert research["outputs"] == ["research-notes"]
    assert [tool["name"] for tool in research["tools"]] == ["browser-read"]
    assert "tool_definition:" in research["tools"][0]["description"]

    writer = roles["writer"]
    assert writer["inputs"] == ["research-notes"]
    assert writer["outputs"] == ["final-script"]
    assert any(check.startswith("memory_policy:") for check in writer["checks"])


def test_artifacts_and_handoffs_reflect_the_real_flow():
    candidate = live_candidate()
    projection = critic_candidate_projection(candidate)
    artifacts = {item["id"]: item for item in projection["artifacts"]}
    assert set(artifacts) == {"research-notes", "final-script"}
    assert artifacts["research-notes"]["producer"] == "research"
    assert "writer" in artifacts["research-notes"]["consumers"]
    assert artifacts["final-script"]["producer"] == "writer"
    assert "application/pdf" in artifacts["final-script"]["format"]

    handoffs = {item["id"]: item for item in projection["handoffs"]}
    assert handoffs["e-research-write"]["from_role"] == "research"
    assert handoffs["e-research-write"]["to_role"] == "writer"
    assert handoffs["e-research-write"]["artifact_ids"] == ["research-notes"]


def test_control_surfaces_every_non_role_mechanism():
    candidate = live_candidate()
    projection = critic_candidate_projection(candidate)
    control = projection["control"]
    assert control["execution_state"] == "planned"
    assert "artifact.publish" in control["publication"]
    assert control["original_mutation"] == "none"
    notes = "\n".join(control["notes"])
    assert "human_gate:owner-gate" in notes
    assert "deterministic:finalize" in notes
    assert "completion:" in notes


def test_single_agent_shape_projects_one_role():
    candidate = live_candidate(shape="single_agent", agent_count=1)
    projection = critic_candidate_projection(candidate)
    assert len(projection["roles"]) == 1
    Candidate.model_validate(projection)


def test_type_guard_rejects_foreign_objects():
    with pytest.raises(DesignCriticismError):
        critic_candidate_projection(object())


# ------------------------------------------------- review-input preparation


import json as _json

from app.critic_contract import (
    GenerationPurpose,
    PreparedInput,
    ResponseContractError,
    parse_response,
)
from app.services.design_criticism import prepare_candidate_review


def live_pair(**kwargs):
    _target, _lens, _decision, request, graph = prepared(**kwargs)
    model_turn, _ = scripted_model(model_json(graph))
    result = run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)
    return request, result.candidates[0]


def test_review_input_prepares_from_a_live_candidate():
    request, candidate = live_pair()
    prepared_input = prepare_candidate_review(candidate, request)
    assert type(prepared_input) is PreparedInput
    assert prepared_input.purpose is GenerationPurpose.REVIEW
    assert prepared_input.candidate_id == candidate.candidate_id

    manifest = _json.loads(prepared_input.manifest_json)
    criterion_ids = manifest["criterion_ids"]
    decision_id = request.decisions[0].decision_ref.id
    assert any(item.startswith(f"{decision_id}:claim:") for item in criterion_ids)
    assert any(item.startswith(f"{decision_id}:effect:") for item in criterion_ids)
    assert "shape:disposition" in criterion_ids
    assert any(item.startswith("work:completion:") for item in criterion_ids)

    prompt = _json.loads(prepared_input.prompt)
    original = prompt["input"]["originals"][0]
    assert original["id"] == request.work_target.work_model.work_model_id
    locations = [section["location"] for section in original["sections"]]
    assert "work_model.goals" in locations
    assert "work_model.risks" in locations


def test_review_preparation_is_deterministic():
    request, candidate = live_pair()
    assert prepare_candidate_review(candidate, request) == \
        prepare_candidate_review(candidate, request)


def test_review_preparation_rejects_a_foreign_request():
    request, candidate = live_pair()
    from app.services.design import create_generation_request
    from app.tests.test_design_generation import design_authority

    foreign = create_generation_request(
        request.work_target,
        list(request.decisions),
        request_id="00000000-0000-4000-8000-000000000888",
        requested_candidate_count=3,
        compilation_authority=design_authority(),
    )
    with pytest.raises(DesignCriticismError):
        prepare_candidate_review(candidate, foreign)
    with pytest.raises(DesignCriticismError):
        prepare_candidate_review(object(), request)


def test_scripted_review_response_round_trips_through_the_parser():
    request, candidate = live_pair()
    prepared_input = prepare_candidate_review(candidate, request)
    manifest = _json.loads(prepared_input.manifest_json)
    work_model_id = request.work_target.work_model.work_model_id
    findings = [
        {
            "criterion_id": criterion_id,
            "status": "pass",
            "evidence": [{
                "document_id": work_model_id,
                "version": "1",
                "location": "work_model.goals",
            }],
            "reason": "목표와 산출물 계약이 그래프에 그대로 반영되어 있다.",
            "uncertainties": [],
        }
        for criterion_id in manifest["criterion_ids"]
    ]
    result = parse_response(prepared_input, _json.dumps({
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "purpose": "review",
        "findings": findings,
    }))
    assert {item["criterion_id"] for item in result["findings"]} == set(
        manifest["criterion_ids"]
    )

    with pytest.raises(ResponseContractError):
        parse_response(prepared_input, _json.dumps({
            "candidate_id": candidate.candidate_id,
            "candidate_version": str(candidate.version),
            "purpose": "review",
            "findings": findings[:1],  # coverage violation
        }))


# ---------------------------------- proposal / validity / response chain


from app.services.design_criticism import (
    prepare_candidate_proposal,
    prepare_candidate_response,
    prepare_candidate_validity,
)
from app.tests.test_design_generation import proposed_lens


def _citation(request):
    return {
        "document_id": request.work_target.work_model.work_model_id,
        "version": "1",
        "location": "work_model.risks",
    }


def test_full_offline_criticism_chain_over_a_live_candidate():
    request, candidate = live_pair()
    registry, _lens = proposed_lens(request.work_target)

    proposal_input = prepare_candidate_proposal(candidate, request, registry)
    assert proposal_input.purpose is GenerationPurpose.COUNTEREXAMPLE_PROPOSAL
    pack = _json.loads(proposal_input.prompt)["input"]["lens_pack"]
    assert pack["id"] == f"lenses:{request.request_id}"
    assert len(pack["rules"]) == 1
    rule = pack["rules"][0]
    assert rule["id"] == "L-P032-01"
    assert rule["status"] == "research_draft"
    manifest = _json.loads(proposal_input.manifest_json)
    criterion_ids = manifest["criterion_ids"]

    counterexample = {
        "id": "ce-unsupported-claim",
        "version": "1",
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "claim": "검증 단계 없이 작성자가 미확인 주장을 대본에 넣을 수 있다.",
        "conditions": ["research 노드가 반증 자료를 수집하지 못한 경우"],
        "criterion_ids": [criterion_ids[0]],
        "citations": [_citation(request)],
    }
    proposal_result = parse_response(proposal_input, _json.dumps({
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "purpose": "counterexample_proposal",
        "status": "proposed",
        "counterexamples": [counterexample],
        "lens_use": [{
            "rule_id": rule["id"],
            "rule_version": rule["version"],
            "status": "used",
            "reason": "렌즈의 반증 질문이 이 반례를 지목한다.",
            "evidence": [_citation(request)],
            "counterexample_ids": ["ce-unsupported-claim"],
        }],
        "uncertainties": [],
    }))
    proposed = proposal_result["counterexamples"][0]

    validity_input = prepare_candidate_validity(candidate, request, proposed)
    assert validity_input.purpose is GenerationPurpose.COUNTEREXAMPLE_VALIDITY
    validity_result = parse_response(validity_input, _json.dumps({
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "counterexample_id": proposed["id"],
        "counterexample_version": proposed["version"],
        "purpose": "counterexample_validity",
        "status": "valid",
        "evidence": [_citation(request)],
        "reason": "위험 항목이 명시적으로 이 실패 조건을 예고한다.",
        "uncertainties": [],
    }))

    response_input = prepare_candidate_response(
        candidate, request, proposed, validity_result,
    )
    assert response_input.purpose is GenerationPurpose.CANDIDATE_RESPONSE
    response_result = parse_response(response_input, _json.dumps({
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "purpose": "candidate_response",
        "counterexample_id": proposed["id"],
        "counterexample_version": proposed["version"],
        "validity_status": "valid",
        "status": "mitigate",
        "evidence": [_citation(request)],
        "reason": "research 책임 분리와 인용 연결 조건이 실패 경로를 완화한다.",
        "uncertainties": [],
    }))
    assert response_result["status"] == "mitigate"


def test_chain_preparation_rejects_foreign_bindings():
    request, candidate = live_pair()
    with pytest.raises(DesignCriticismError):
        prepare_candidate_proposal(candidate, request, object())
    foreign_counterexample = {
        "id": "ce-foreign",
        "version": "1",
        "candidate_id": "00000000-0000-4000-8000-000000000999",
        "candidate_version": "1",
        "claim": "다른 후보에 대한 반례",
        "conditions": ["조건"],
        "criterion_ids": ["shape:disposition"],
        "citations": [_citation(request)],
    }
    with pytest.raises(DesignCriticismError):
        prepare_candidate_validity(candidate, request, foreign_counterexample)


# ------------------------------------------------- criticism verdict fold


from app.services.design_criticism import CandidateVerdict, fold_candidate_criticism


def _finding(criterion_id, status, request):
    return {
        "criterion_id": criterion_id,
        "status": status,
        "evidence": [_citation(request)],
        "reason": "근거",
        "uncertainties": ["미해결 사유"] if status == "unresolved" else [],
    }


def _review(candidate, request, statuses):
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "purpose": "review",
        "findings": [
            _finding(f"criterion:{index}", status, request)
            for index, status in enumerate(statuses)
        ],
    }


def _chain(candidate, request, *, validity_status, response_status):
    counterexample = {
        "id": "ce-1",
        "version": "1",
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "claim": "주장",
        "conditions": ["조건"],
        "criterion_ids": ["criterion:0"],
        "citations": [_citation(request)],
    }
    validity = {
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "counterexample_id": "ce-1",
        "counterexample_version": "1",
        "purpose": "counterexample_validity",
        "status": validity_status,
        "evidence": [_citation(request)],
        "reason": "근거",
        "uncertainties": ["사유"] if validity_status == "unresolved" else [],
    }
    response = None
    if response_status is not None:
        response = {
            "candidate_id": candidate.candidate_id,
            "candidate_version": str(candidate.version),
            "purpose": "candidate_response",
            "counterexample_id": "ce-1",
            "counterexample_version": "1",
            "validity_status": validity_status,
            "status": response_status,
            "evidence": [_citation(request)],
            "reason": "근거",
            "uncertainties": ["사유"] if response_status == "unresolved" else [],
        }
    return {"counterexample": counterexample, "validity": validity, "response": response}


def test_clean_criticism_folds_to_passed():
    request, candidate = live_pair()
    verdict = fold_candidate_criticism(
        candidate,
        _review(candidate, request, ["pass", "pass"]),
        [_chain(candidate, request, validity_status="rejected", response_status=None)],
    )
    assert type(verdict) is CandidateVerdict
    assert verdict.status == "passed"
    assert verdict.reasons == ()


def test_mandatory_defects_reject_and_are_never_hidden():
    request, candidate = live_pair()
    failed = fold_candidate_criticism(
        candidate, _review(candidate, request, ["pass", "fail"]), [],
    )
    assert failed.status == "rejected"
    assert any("criterion:1" in reason for reason in failed.reasons)

    beaten = fold_candidate_criticism(
        candidate,
        _review(candidate, request, ["pass"]),
        [_chain(candidate, request, validity_status="valid", response_status="fail")],
    )
    assert beaten.status == "rejected"
    assert any("ce-1" in reason for reason in beaten.reasons)

    # A mandatory defect outranks any surrounding insufficiency.
    mixed = fold_candidate_criticism(
        candidate,
        _review(candidate, request, ["unresolved", "fail"]),
        [_chain(candidate, request, validity_status="unresolved", response_status=None)],
    )
    assert mixed.status == "rejected"


def test_unresolved_evidence_folds_to_insufficient():
    request, candidate = live_pair()
    for review_statuses, chain_spec in (
        (["unresolved"], None),
        (["pass"], ("unresolved", None)),
        (["pass"], ("valid", "unresolved")),
        (["pass"], ("valid", None)),
    ):
        chains = []
        if chain_spec is not None:
            validity_status, response_status = chain_spec
            chains = [_chain(
                candidate, request,
                validity_status=validity_status,
                response_status=response_status,
            )]
        verdict = fold_candidate_criticism(
            candidate, _review(candidate, request, review_statuses), chains,
        )
        assert verdict.status == "insufficient_evidence"
        assert verdict.reasons


def test_fold_rejects_foreign_or_inconsistent_bindings():
    request, candidate = live_pair()
    foreign_review = _review(candidate, request, ["pass"])
    foreign_review["candidate_id"] = "00000000-0000-4000-8000-000000000999"
    with pytest.raises(DesignCriticismError):
        fold_candidate_criticism(candidate, foreign_review, [])

    mismatched = _chain(
        candidate, request, validity_status="valid", response_status="mitigate",
    )
    mismatched["response"]["validity_status"] = "unresolved"
    with pytest.raises(DesignCriticismError):
        fold_candidate_criticism(
            candidate, _review(candidate, request, ["pass"]), [mismatched],
        )
