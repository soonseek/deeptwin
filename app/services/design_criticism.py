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
from ..domain.refs import EntityRef
from .design import DesignCandidate


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


__all__ = ["DesignCriticismError", "critic_candidate_projection"]
