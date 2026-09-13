"""Project an accepted design candidate into the critic's field contract.

The critic pipeline reviews a candidate functional contract — roles, artifacts,
handoffs and control — never the raw graph object.  This projection is deterministic
and faithful: real responsibilities and bindings, exact reference strings, and every
non-role mechanism (human gates, deterministic handlers, routers, loops, completion
criteria, observation/budget bindings) surfaced in the control notes so the critic
cannot be shown less than the graph commits to.  Projection grants no authority: it is
read-only data preparation for the already-qualified critic contract.
"""

from __future__ import annotations

from pydantic import ValidationError

from ..critic_contract import Candidate as CriticCandidate
from ..critic_contract import (
    GenerationPurpose,
    InputContractError,
    PreparedInput,
    prepare_input,
)
from ..domain.refs import EntityRef, canonical_json
from .design import DesignCandidate, DesignGenerationRequest


class DesignCriticismError(ValueError):
    """The candidate cannot be projected for criticism."""


def _ref_string(ref: EntityRef) -> str:
    return f"{ref.kind}:{ref.id}@{ref.version}#{ref.sha256}"


def _roles(graph) -> list[dict]:
    model_bindings = {item.binding_id: item for item in graph.model_bindings}
    tool_bindings = {item.binding_id: item for item in graph.tool_bindings}
    roles = []
    for node in graph.nodes:
        if node.kind != "agent":
            continue
        config = node.config
        binding = model_bindings[config["model_binding_id"]]
        tools = []
        for tool_id in config["tool_binding_ids"]:
            bound = tool_bindings[tool_id]
            tools.append({
                "name": tool_id,
                "description": _ref_string(bound.tool_definition_ref),
                "operations": list(bound.capabilities),
                "read_paths": [],
                "write_paths": [],
            })
        checks = [f"failure_policy:{node.failure_policy}"]
        checks.extend(
            f"required_approval_scope:{scope}"
            for scope in node.required_approval_scopes
        )
        if config.get("memory_policy_id"):
            checks.append(f"memory_policy:{config['memory_policy_id']}")
        roles.append({
            "id": node.node_id,
            "responsibility": node.responsibility,
            "model": {
                "provider": "model_choice",
                "model": _ref_string(binding.model_choice_ref),
                "reasoning": "capabilities:" + ",".join(binding.capabilities),
                "parameters": [
                    {"name": "required_capability", "value": capability}
                    for capability in config["required_model_capabilities"]
                ],
            },
            "tools": tools,
            "inputs": [slot.artifact_contract_id for slot in node.input_slots],
            "outputs": [slot.artifact_contract_id for slot in node.output_slots],
            "checks": checks,
        })
    return roles


def _artifacts(graph) -> list[dict]:
    artifacts = []
    for contract in graph.artifact_contracts:
        identifier = contract.artifact_contract_id
        producers = [
            node.node_id for node in graph.nodes
            if any(slot.artifact_contract_id == identifier for slot in node.output_slots)
        ]
        consumers = [
            node.node_id for node in graph.nodes
            if any(slot.artifact_contract_id == identifier for slot in node.input_slots)
        ]
        artifacts.append({
            "id": identifier,
            "version": "1",
            "format": ",".join(contract.media_types),
            "reference": (
                _ref_string(contract.schema_ref)
                if contract.schema_ref is not None else "none"
            ),
            "producer": producers[0],
            "consumers": consumers,
            "access": {
                "readers": consumers,
                "writers": producers,
                "mode": "bounded_stream",
            },
            "content_contract": (
                f"min_items:{contract.min_items},max_items:{contract.max_items},"
                f"max_total_bytes:{contract.max_total_bytes}"
            ),
        })
    return artifacts


def _handoffs(graph) -> list[dict]:
    handoffs = []
    for edge in graph.edges:
        if edge.kind != "artifact":
            continue
        handoffs.append({
            "id": edge.edge_id,
            "from_role": edge.source_node_id,
            "to_role": edge.target_node_id,
            "artifact_ids": [edge.data["artifact_contract_id"]],
            "mode": f"{edge.data['multiplicity']}," + (
                "mandatory" if edge.data["mandatory"] else "optional"
            ),
        })
    return handoffs


def _control(graph) -> dict:
    scopes = {
        scope for node in graph.nodes for scope in node.required_approval_scopes
    }
    for node in graph.nodes:
        if node.kind == "human_gate":
            scopes.update(node.config.get("approval_scopes", ()))
    notes = ["entry_nodes:" + ",".join(graph.entry_node_ids)]
    for node in graph.nodes:
        if node.kind != "agent":
            notes.append(f"{node.kind}:{node.node_id}:{node.responsibility}")
    for edge in graph.edges:
        if edge.kind == "artifact":
            continue
        notes.append(
            f"edge:{edge.kind}:{edge.edge_id}:"
            f"{edge.source_node_id}->{edge.target_node_id}"
        )
    for criterion in graph.completion_criteria:
        notes.append(
            f"completion:{criterion.criterion_id}:{criterion.node_id}."
            f"{criterion.output_slot}:{criterion.artifact_contract_id}"
            f">={criterion.min_items}"
        )
    notes.append("observation_contract:" + _ref_string(graph.observation_contract_ref))
    notes.append("budget_policy:" + _ref_string(graph.budget_policy_ref))
    if graph.fact_names:
        notes.append("facts:" + ",".join(graph.fact_names))
    return {
        "execution_state": "planned",
        "publication": (
            "approval_scopes:" + ",".join(sorted(scopes)) if scopes else "none"
        ),
        "original_mutation": "none",
        "notes": notes,
    }


def critic_candidate_projection(candidate: DesignCandidate) -> dict:
    """Render the exact critic-facing candidate functional contract."""

    if type(candidate) is not DesignCandidate:
        raise DesignCriticismError("an accepted design candidate is required")
    graph = candidate.graph
    projection = {
        "id": candidate.candidate_id,
        "version": str(candidate.version),
        "roles": _roles(graph),
        "artifacts": _artifacts(graph),
        "handoffs": _handoffs(graph),
        "control": _control(graph),
    }
    try:
        CriticCandidate.model_validate(projection)
    except ValidationError as exc:
        raise DesignCriticismError(
            "the candidate projection violates the critic contract"
        ) from exc
    return projection


_WORK_MODEL_SECTIONS = (
    "goals",
    "deliverables",
    "completion_conditions",
    "authorities",
    "risks",
    "unknowns",
    "suitability",
)


def _work_model_original(work_model) -> dict:
    value = work_model.as_dict()
    sections = [
        {
            "location": f"work_model.{name}",
            "text": canonical_json(value[name]).decode("utf-8"),
        }
        for name in _WORK_MODEL_SECTIONS
    ]
    return {
        "id": work_model.work_model_id,
        "version": str(work_model.version),
        "media_type": "application/json",
        "availability": "text",
        "sections": sections,
    }


def _review_criteria(request: DesignGenerationRequest) -> dict:
    items = []
    for decision in request.decisions:
        decision_id = decision.decision_id
        for index, claim in enumerate(decision.functional_claims):
            items.append({"id": f"{decision_id}:claim:{index}", "text": claim})
        for effect in decision.proposed_effects:
            target = effect.target
            items.append({
                "id": f"{decision_id}:effect:{effect.effect_id}",
                "text": (
                    f"제안된 효과가 그래프의 선언 지점에서 실현된다 "
                    f"(axis={effect.axis}, target={target.kind}:{target.identifier}"
                    f".{target.field_path}): {effect.rationale}"
                ),
            })
    items.append({
        "id": "shape:disposition",
        "text": f"설계 형상이 확인된 적합성({request.design_disposition})을 준수한다.",
    })
    for index, condition in enumerate(
        request.work_target.work_model.completion_conditions
    ):
        items.append({"id": f"work:completion:{index}", "text": condition})
    return {"id": f"review:{request.request_id}", "version": "1", "items": items}


def prepare_candidate_review(
    candidate: DesignCandidate,
    request: DesignGenerationRequest,
) -> PreparedInput:
    """Prepare the exact bounded critic review input for one live candidate."""

    if (
        type(candidate) is not DesignCandidate
        or type(request) is not DesignGenerationRequest
        or candidate.generation_request_ref != request.request_ref
        or candidate.work_model_ref != request.work_target.work_model_ref
    ):
        raise DesignCriticismError(
            "an accepted candidate bound to this exact request is required"
        )
    source = {
        "originals": [_work_model_original(request.work_target.work_model)],
        "criteria": _review_criteria(request),
        "candidate": critic_candidate_projection(candidate),
    }
    try:
        return prepare_input(GenerationPurpose.REVIEW, source)
    except InputContractError as exc:
        raise DesignCriticismError(
            "the candidate review input violates the critic contract"
        ) from exc


__all__ = [
    "DesignCriticismError",
    "critic_candidate_projection",
    "prepare_candidate_review",
]
