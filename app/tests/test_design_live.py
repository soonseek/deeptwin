"""Live design-candidate generation driver: framework authority over an untrusted model.

The driver renders the exact bounded prompt from a framework-issued generation request,
sends it through one caller-supplied model boundary, mints the generation-call record
itself, and admits candidates only through ``accept_design_candidates``.  The model can
contribute nothing but graphs.
"""

import json
from hashlib import sha256

import pytest

from app.domain.refs import canonical_json
from app.generation_profiles import DesignGenerationPurpose, design_profile_for
from app.services.design import DesignContractError
from app.services.design_live import (
    _CRITIC_DESIGN_RULES,
    DesignGenerationError,
    GenerationCallRecord,
    render_candidate_prompt,
    run_candidate_generation,
)
from app.tests.test_design_generation import graph_value, prepared

MODEL_ID = "claude-fake-2026-01"


def scripted_model(response):
    calls = []

    def model_turn(system, user):
        calls.append((system, user))
        return response

    return model_turn, calls


def model_json(*graphs):
    return json.dumps({"candidates": [{"graph": graph} for graph in graphs]})


def test_scripted_model_turn_produces_accepted_candidates_and_exact_call_record():
    target, _lens, _decision, request, graph = prepared()
    model_turn, calls = scripted_model(model_json(graph))

    result = run_candidate_generation(
        request, model_turn=model_turn, model_id=MODEL_ID
    )

    assert len(calls) == 1
    system, user = calls[0]
    profile = design_profile_for(DesignGenerationPurpose.DESIGN_CANDIDATE)
    assert profile.base_instructions in system
    assert profile.developer_instructions in system
    payload = json.loads(user)
    assert canonical_json(payload["generation_request"]) == canonical_json(
        request.as_dict()
    )
    assert canonical_json(payload["work_model"]) == canonical_json(
        target.work_model.as_dict()
    )
    assert canonical_json(payload["design_decisions"]) == canonical_json(
        [item.as_dict() for item in request.decisions]
    )
    assert payload["design_disposition"] == request.design_disposition
    assert payload["requested_candidate_count"] == request.requested_candidate_count

    assert len(result.candidates) == 1
    accepted = result.candidates[0]
    record = result.call_record
    assert type(record) is GenerationCallRecord
    assert accepted.generation_call_refs == (record.call_ref,)
    assert record.request_ref == request.request_ref
    assert record.purpose == "design_candidate"
    assert record.model_id == MODEL_ID
    assert record.profile_digest == profile.digest
    assert record.prompt_sha256 == sha256(
        canonical_json({"system": system, "user": user})
    ).hexdigest()
    assert record.response_sha256 == sha256(model_json(graph).encode("utf-8")).hexdigest()
    assert record.call_ref.kind == "decision_record"


def test_prompt_rendering_is_deterministic_for_one_request():
    _target, _lens, _decision, request, _graph = prepared()
    assert render_candidate_prompt(request) == render_candidate_prompt(request)


def test_the_generator_is_told_the_critics_design_rules():
    """T038: the two design defects the live critic rejected every live candidate for are
    stated to the generator (one writer per artifact; completion conditions checked by
    another node as declared artifacts), in the first-round and the revision prompt alike."""
    _target, _lens, _decision, request, _graph = prepared()
    system, _user = render_candidate_prompt(request)
    assert "one writer per artifact" in system
    assert "never re-emits a contract it received" in system
    assert "completion_conditions" in system and "other than the one that produced" in system


def test_the_generator_is_told_the_design_hygiene_rules():
    """T038 attempt 3: the three deeper defects the live critic found in attempt 2 are stated
    to the generator as general hygiene: a check reads exactly what it verifies; nothing is
    altered after approval without a re-check before release; a check that finds unresolved
    problems blocks the downstream join, gate or release. First-round and revision alike;
    the task's own wording (dossier, script, fact-check) is not used."""
    _target, _lens, _decision, request, graph = prepared()
    system, _user = render_candidate_prompt(request)
    parent = run_candidate_generation(request, model_turn=scripted_model(model_json(graph))[0],
                                      model_id=MODEL_ID).candidates[0]
    revised, _ = render_candidate_prompt(request, revision=(parent, "shorten the pipeline"))
    for text in (system, revised):
        assert "a check reads what it verifies" in text
        assert "artifact input edge for each exact artifact it verifies" in text
        assert "nothing changes after approval unchecked" in text
        assert "re-checks it against the approved content before release" in text
        assert "a check that finds unresolved problems blocks" in text
        assert "failure_handling block" in text
    rules = _CRITIC_DESIGN_RULES
    for task_word in ("dossier", "fact-check", "fact check", "thumbnail", "research"):
        assert task_word not in rules.split("(c)")[1]


def test_model_supplies_only_graphs_never_identity_or_call_refs():
    _target, _lens, _decision, request, graph = prepared()
    forged = {
        "graph": graph,
        "generation_call_refs": [
            {"kind": "decision_record", "id": "00000000-0000-4000-8000-000000000999",
             "version": 1, "sha256": "f" * 64}
        ],
    }
    model_turn, _ = scripted_model(json.dumps({"candidates": [forged]}))
    with pytest.raises(DesignGenerationError):
        run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)

    named = {"graph": graph, "candidate_id": "00000000-0000-4000-8000-000000000998"}
    model_turn, _ = scripted_model(json.dumps({"candidates": [named]}))
    with pytest.raises(DesignGenerationError):
        run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)


def test_duplicate_topology_from_the_model_is_rejected_by_the_authority():
    target, _lens, decision, request, graph = prepared()
    twin = graph_value(target, decision.decision_ref.as_dict(), graph_suffix=205)
    model_turn, _ = scripted_model(model_json(graph, twin))
    with pytest.raises(DesignContractError):
        run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)


def test_malformed_model_output_is_terminal_without_acceptance():
    _target, _lens, _decision, request, graph = prepared()
    for raw in (
        b"bytes not text",
        "not json at all",
        json.dumps(["not", "an", "object"]),
        json.dumps({"no_candidates": []}),
        json.dumps({"candidates": []}),
        json.dumps({"candidates": "not-a-list"}),
        json.dumps({"candidates": [{"graph": graph}] * 4}),  # beyond requested count
        json.dumps({"candidates": ["not-an-object"]}),
        json.dumps({"candidates": [{}]}),
        json.dumps({"candidates": [{"graph": graph}], "extra": True}),
    ):
        model_turn, _ = scripted_model(raw)
        with pytest.raises(DesignGenerationError):
            run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)


def test_a_failing_model_boundary_is_wrapped_terminally():
    _target, _lens, _decision, request, _graph = prepared()

    def broken_model(system, user):
        raise ValueError("provider transport exploded")

    with pytest.raises(DesignGenerationError):
        run_candidate_generation(request, model_turn=broken_model, model_id=MODEL_ID)


def test_request_and_model_identity_are_validated():
    _target, _lens, _decision, request, graph = prepared()
    model_turn, _ = scripted_model(model_json(graph))
    with pytest.raises(DesignGenerationError):
        run_candidate_generation(object(), model_turn=model_turn, model_id=MODEL_ID)
    for bad_model_id in ("", "  ", "x" * 200, 7, None):
        with pytest.raises(DesignGenerationError):
            run_candidate_generation(
                request, model_turn=model_turn, model_id=bad_model_id
            )
    with pytest.raises(DesignGenerationError):
        run_candidate_generation(request, model_turn=object(), model_id=MODEL_ID)


FRAMEWORK_FIELDS = ("schema_version", "graph_id", "version", "work_model_ref", "decision_refs",
                    "observation_contract_ref", "budget_policy_ref")


def test_the_framework_fills_identities_and_record_refs_the_model_omits():
    target, _lens, _decision, request, graph = prepared()
    authored = {key: value for key, value in graph.items() if key not in FRAMEWORK_FIELDS}
    model_turn, calls = scripted_model(model_json(authored))

    [candidate] = run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID).candidates

    assert candidate.graph.work_model_ref == target.work_model_ref
    assert candidate.graph.decision_refs == tuple(item.decision_ref for item in request.decisions)
    assert candidate.graph.observation_contract_ref.as_dict() == graph["observation_contract_ref"]
    assert candidate.graph.budget_policy_ref.as_dict() == graph["budget_policy_ref"]
    assert candidate.graph.version == 1 and candidate.graph.graph_id != graph["graph_id"]
    system, user = calls[0]
    # the model sees what it may reference, and is told the framework owns the rest
    assert json.loads(user)["compilation_authority"] == json.loads(
        canonical_json(request.compilation_authority.as_dict()))
    assert "Omit schema_version, graph_id" in system


def test_a_model_supplied_reference_is_still_admitted_strictly():
    _target, _lens, _decision, request, graph = prepared()
    forged = {key: value for key, value in graph.items() if key not in FRAMEWORK_FIELDS}
    forged["work_model_ref"] = {**graph["work_model_ref"], "sha256": "0" * 64}
    model_turn, _calls = scripted_model(model_json(forged))

    with pytest.raises(DesignContractError):
        run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)
