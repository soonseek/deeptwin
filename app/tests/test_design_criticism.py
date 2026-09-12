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
