"""Live-driven candidate criticism over the untrusted model boundary.

The driver runs the four criticism stages (review, counterexample proposal,
validity, candidate response) through the same ``model_turn(system, user)``
boundary the generation path uses: every stage renders its code-owned
instruction profile plus the stage schema as the system prompt and the
prepared contract input as the user payload, admits the raw response only
through ``parse_response``, mints one framework-owned call record per actual
model call (purpose, profile digest, prompt/response hashes, request
binding), and folds the outcome through ``fold_candidate_criticism``. A
rejected or abstaining stage consumes no further calls than it needs; a
malformed or wrongly-bound response is a typed refusal, never a verdict.
"""

import json as _json

import pytest

from app.generation_profiles import profile_for
from app.services.design_criticism import CandidateVerdict, DesignCriticismError
from app.services.design_criticism_live import (
    CriticismCallRecord,
    run_candidate_criticism,
)
from app.tests.test_design_criticism import _citation, live_pair
from app.tests.test_design_generation import proposed_lens


def _review_payload(candidate, prepared_manifest):
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "purpose": "review",
        "findings": [
            {
                "criterion_id": criterion_id,
                "status": "pass",
                "evidence": [{
                    "document_id": prepared_manifest["work_model_id"],
                    "version": "1",
                    "location": "work_model.goals",
                }],
                "reason": "기준이 그래프에 반영되어 있다.",
                "uncertainties": [],
            }
            for criterion_id in prepared_manifest["criterion_ids"]
        ],
    }


class ScriptedCritic:
    """Feed stage responses in order; record every (system, user) prompt."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload if type(payload) is str else _json.dumps(payload)


def scripted_chain(candidate, request, rule, criterion_ids, work_model_id,
                   *, validity_status="valid", response_status="mitigate"):
    counterexample = {
        "id": "ce-unsupported-claim",
        "version": "1",
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "claim": "검증 단계 없이 미확인 주장이 대본에 들어갈 수 있다.",
        "conditions": ["research 노드가 반증 자료를 수집하지 못한 경우"],
        "criterion_ids": [criterion_ids[0]],
        "citations": [_citation(request)],
    }
    manifest = {
        "criterion_ids": criterion_ids, "work_model_id": work_model_id,
    }
    review = _review_payload(candidate, manifest)
    proposal = {
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
    }
    validity = {
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "counterexample_id": "ce-unsupported-claim",
        "counterexample_version": "1",
        "purpose": "counterexample_validity",
        "status": validity_status,
        "evidence": [_citation(request)],
        "reason": "위험 항목이 이 실패 조건을 예고한다.",
        "uncertainties": (
            ["판정 근거 부족"] if validity_status == "unresolved" else []
        ),
    }
    response = {
        "candidate_id": candidate.candidate_id,
        "candidate_version": str(candidate.version),
        "purpose": "candidate_response",
        "counterexample_id": "ce-unsupported-claim",
        "counterexample_version": "1",
        "validity_status": validity_status,
        "status": response_status,
        "evidence": [_citation(request)],
        "reason": "책임 분리와 인용 조건이 실패 경로를 완화한다.",
        "uncertainties": [],
    }
    return review, proposal, validity, response


def driven(validity_status="valid", response_status="mitigate"):
    request, candidate = live_pair()
    registry, _lens = proposed_lens(request.work_target)
    from app.services.design_criticism import prepare_candidate_proposal

    pack = _json.loads(
        prepare_candidate_proposal(candidate, request, registry).prompt
    )["input"]["lens_pack"]
    rule = pack["rules"][0]
    manifest = _json.loads(
        prepare_candidate_proposal(candidate, request, registry).manifest_json
    )
    review, proposal, validity, response = scripted_chain(
        candidate, request, rule, manifest["criterion_ids"],
        request.work_target.work_model.work_model_id,
        validity_status=validity_status, response_status=response_status,
    )
    return request, candidate, registry, review, proposal, validity, response


MODEL_ID = "claude-sonnet-5"


def test_the_four_stage_chain_drives_and_folds_to_a_verdict():
    request, candidate, registry, review, proposal, validity, response = driven()
    model = ScriptedCritic([review, proposal, validity, response])
    result = run_candidate_criticism(
        candidate, request, registry, model_turn=model, model_id=MODEL_ID,
    )
    assert type(result.verdict) is CandidateVerdict
    assert result.verdict.status == "passed"
    assert len(result.call_records) == 4
    # the lens's contribution is recorded with the exact counterexample it named
    assert result.proposal_status == "proposed"
    assert [(use["status"], use["counterexample_ids"]) for use in result.lens_use] == [
        ("used", ("ce-unsupported-claim",)),
    ]
    purposes = [record.purpose for record in result.call_records]
    assert purposes == [
        "review", "counterexample_proposal",
        "counterexample_validity", "candidate_response",
    ]
    for record, (system, user) in zip(result.call_records, model.calls):
        assert type(record) is CriticismCallRecord
        assert record.request_ref == request.request_ref
        assert record.model_id == MODEL_ID
        assert record.profile_digest  # the code-owned instruction identity
        assert record.call_ref.kind == "decision_record"
    # every stage's system prompt is the code-owned profile + stage schema
    for (system, _user), record in zip(model.calls, result.call_records):
        from app.generation_profiles import GenerationPurpose

        profile = profile_for(GenerationPurpose(record.purpose))
        assert profile.base_instructions in system
        assert profile.developer_instructions in system


def test_a_rejected_validity_skips_the_response_stage():
    request, candidate, registry, review, proposal, validity, _response = driven(
        validity_status="rejected",
    )
    model = ScriptedCritic([review, proposal, validity])
    result = run_candidate_criticism(
        candidate, request, registry, model_turn=model, model_id=MODEL_ID,
    )
    assert len(result.call_records) == 3  # no response call was spent
    assert result.chains[0]["response"] is None
    assert result.verdict.status == "passed"  # rejected counterexample folds out


def test_an_abstaining_proposal_ends_with_two_calls():
    request, candidate, registry, review, proposal, _v, _r = driven()
    proposal = {
        **proposal, "status": "abstain", "counterexamples": [],
        "uncertainties": ["반례를 세울 근거가 부족하다"],
        "lens_use": [{**proposal["lens_use"][0], "status": "abstain",
                      "counterexample_ids": []}],
    }
    model = ScriptedCritic([review, proposal])
    result = run_candidate_criticism(
        candidate, request, registry, model_turn=model, model_id=MODEL_ID,
    )
    assert len(result.call_records) == 2
    assert result.chains == ()
    # abstention is recorded as such, never as a silent absence
    assert result.proposal_status == "abstain"
    assert [(use["status"], use["counterexample_ids"]) for use in result.lens_use] == [("abstain", ())]
    assert result.verdict.status == "passed"


def test_malformed_or_misbound_responses_are_typed_refusals():
    request, candidate, registry, review, _proposal, _validity, _response = driven()
    with pytest.raises(DesignCriticismError):
        run_candidate_criticism(
            candidate, request, registry,
            model_turn=ScriptedCritic(["not json at all"]),
            model_id=MODEL_ID,
        )
    misbound = {**review, "candidate_id": "00000000-0000-4000-8000-000000000999"}
    with pytest.raises(DesignCriticismError):
        run_candidate_criticism(
            candidate, request, registry,
            model_turn=ScriptedCritic([misbound]),
            model_id=MODEL_ID,
        )
    with pytest.raises(DesignCriticismError):
        run_candidate_criticism(
            candidate, request, registry,
            model_turn=ScriptedCritic([RuntimeError("provider down")]),
            model_id=MODEL_ID,
        )
    with pytest.raises(DesignCriticismError):
        run_candidate_criticism(
            candidate, request, registry,
            model_turn=object(), model_id=MODEL_ID,
        )
    with pytest.raises(DesignCriticismError):
        run_candidate_criticism(
            candidate, request, registry,
            model_turn=ScriptedCritic([review]), model_id="bad model id!",
        )


def _refused(request, candidate, registry, answers):
    from app.services.design_criticism_live import CriticismStageRefused

    with pytest.raises(CriticismStageRefused) as caught:
        run_candidate_criticism(candidate, request, registry, model_turn=ScriptedCritic(answers),
                                model_id=MODEL_ID)
    return caught.value


def test_a_refused_stage_keeps_the_raw_answer_and_the_exact_violation():
    """T038: the first live design-arc review was refused and only digests were kept, so its
    cause was unknown. A refused stage now carries the model's own answer (bounded) and the
    exact rule it broke; the message stays the closed one and nothing becomes a verdict."""

    from hashlib import sha256

    request, candidate, registry, review, proposal, _validity, _response = driven()
    refused = _refused(request, candidate, registry, ["not json at all"])
    assert str(refused) == "the review response violates the contract"
    assert refused.purpose == "review" and refused.raw_text == "not json at all"
    assert refused.violation.startswith("json: Expecting value")
    assert refused.response_sha256 == sha256(b"not json at all").hexdigest()
    assert refused.completed_calls == 0 and refused.truncated is False
    assert set(refused.as_dict()) >= {"violation", "response_text", "prompt_sha256", "model_id"}

    bad_citation = _json.loads(_json.dumps(review))
    bad_citation["findings"][-1]["evidence"][0]["location"] = "the research node"
    last = len(bad_citation["findings"]) - 1
    refused = _refused(request, candidate, registry, [bad_citation])
    assert refused.violation.startswith(f"citation is not visible: /findings/{last}/evidence/0")
    assert "'the research node'" in refused.violation
    assert _json.loads(refused.raw_text) == bad_citation

    missing = {**review, "findings": review["findings"][:-1]}
    assert _refused(request, candidate, registry, [missing]).violation.startswith(
        "rule: finding coverage mismatch: missing [")

    schema = _json.loads(_json.dumps(review))
    schema["findings"][0]["status"] = "maybe"
    schema["verdict"] = "pass"
    violation = _refused(request, candidate, registry, [schema]).violation
    assert violation.startswith("schema: ") and "findings/0/status" in violation and "verdict" in violation

    unresolved = _json.loads(_json.dumps(review))
    unresolved["findings"][0]["status"] = "unresolved"
    assert _refused(request, candidate, registry, [unresolved]).violation == (
        "rule: unresolved result needs uncertainty (/findings/0)")

    # a later stage: the proposal's lens usage must cover the pack exactly
    no_lens = {**proposal, "lens_use": []}
    refused = _refused(request, candidate, registry, [review, no_lens])
    assert refused.purpose == "counterexample_proposal" and refused.completed_calls == 1
    assert refused.violation == "rule: lens usage set mismatch"


def test_the_diagnosis_agrees_with_the_contract_and_bounds_what_it_keeps():
    from app.services.design_criticism import prepare_candidate_review
    from app.services.design_criticism_live import (
        MAX_REFUSED_RESPONSE_BYTES,
        CriticismStageRefused,
        diagnose_contract_violation,
    )

    request, candidate, registry, review, *_rest = driven()
    prepared = prepare_candidate_review(candidate, request)
    assert diagnose_contract_violation(prepared, _json.dumps(review)) is None
    huge = "가" * (MAX_REFUSED_RESPONSE_BYTES // 2)
    refused = _refused(request, candidate, registry, [huge])
    assert refused.truncated is True and refused.raw_bytes == len(huge.encode("utf-8"))
    assert len(refused.raw_text.encode("utf-8")) <= MAX_REFUSED_RESPONSE_BYTES
    assert refused.violation == "json: JSON text or byte limit"
    # a boundary failure (no answer) carries nothing to keep and is not a stage refusal
    with pytest.raises(DesignCriticismError) as caught:
        run_candidate_criticism(candidate, request, registry,
                                model_turn=ScriptedCritic([RuntimeError("down")]), model_id=MODEL_ID)
    assert type(caught.value) is not CriticismStageRefused
