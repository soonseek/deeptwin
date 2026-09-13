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

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from pydantic import ValidationError

from ..critic_contract import Candidate as CriticCandidate
from ..critic_contract import (
    GenerationPurpose,
    InputContractError,
    PreparedInput,
    prepare_input,
)
from ..domain.refs import EntityRef, canonical_json
from .design import (
    DesignCandidate,
    DesignGenerationRequest,
    is_accepted_candidate,
)
from .lenses import LensError, LensRegistry


class DesignCriticismError(ValueError):
    """The candidate cannot be projected for criticism."""


def _ref_string(ref: EntityRef) -> str:
    return f"{ref.kind}:{ref.id}@{ref.version}#{ref.sha256}"


def _roles(graph) -> list[dict]:
    model_bindings = {item.binding_id: item for item in graph.model_bindings}
    tool_bindings = {item.binding_id: item for item in graph.tool_bindings}
    memory_policies = {item.policy_id: item for item in graph.memory_policies}
    roles = []
    for node in graph.nodes:
        if node.kind != "agent":
            continue
        config = node.config
        binding = model_bindings[config["model_binding_id"]]
        tools = []
        checks = [f"failure_policy:{node.failure_policy}"]
        for tool_id in config["tool_binding_ids"]:
            bound = tool_bindings[tool_id]
            tools.append({
                "name": tool_id,
                "description": _ref_string(bound.tool_definition_ref),
                "operations": list(bound.capabilities),
                "read_paths": [],
                "write_paths": [],
            })
            checks.append(f"tool_grant:{tool_id}:{_ref_string(bound.grant_ref)}")
        checks.extend(
            f"required_approval_scope:{scope}"
            for scope in node.required_approval_scopes
        )
        checks.extend(f"grant:{_ref_string(item)}" for item in node.grant_refs)
        if config.get("memory_policy_id"):
            policy = memory_policies[config["memory_policy_id"]]
            checks.append(f"memory_policy:{policy.policy_id}")
            checks.append(f"memory_purpose:{policy.purpose}")
            checks.extend(
                f"memory_read_grant:{_ref_string(item)}"
                for item in policy.read_grant_refs
            )
            checks.extend(
                f"memory_write_grant:{_ref_string(item)}"
                for item in policy.write_grant_refs
            )
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
        if not producers:
            raise DesignCriticismError(
                "an artifact contract has no producing node and cannot be reviewed"
            )
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
            config = dict(node.config)
            handler = config.pop("handler_id", None)
            if handler is not None:
                notes.append(f"handler:{handler}:{node.node_id}")
            if config:
                notes.append(
                    f"config:{node.node_id}:"
                    + canonical_json(config).decode("utf-8")
                )
        for item in node.grant_refs:
            notes.append(f"node_grant:{node.node_id}:{_ref_string(item)}")
    for edge in graph.edges:
        if edge.kind == "artifact":
            continue
        notes.append(
            f"edge:{edge.kind}:{edge.edge_id}:"
            f"{edge.source_node_id}->{edge.target_node_id}:"
            + canonical_json(dict(edge.data)).decode("utf-8")
        )
    for item in graph.grant_refs:
        notes.append(f"graph_grant:{_ref_string(item)}")
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


def _require_accepted(candidate: DesignCandidate) -> None:
    if not is_accepted_candidate(candidate):
        raise DesignCriticismError("an accepted design candidate is required")


def critic_candidate_projection(candidate: DesignCandidate) -> dict:
    """Render the exact critic-facing candidate functional contract."""

    _require_accepted(candidate)
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


def _review_source(
    candidate: DesignCandidate,
    request: DesignGenerationRequest,
) -> dict:
    _require_accepted(candidate)
    if (
        type(request) is not DesignGenerationRequest
        or candidate.generation_request_ref != request.request_ref
        or candidate.work_model_ref != request.work_target.work_model_ref
    ):
        raise DesignCriticismError(
            "an accepted candidate bound to this exact request is required"
        )
    return {
        "originals": [_work_model_original(request.work_target.work_model)],
        "criteria": _review_criteria(request),
        "candidate": critic_candidate_projection(candidate),
    }


def _prepare(purpose: GenerationPurpose, source: dict) -> PreparedInput:
    try:
        return prepare_input(purpose, source)
    except InputContractError as exc:
        raise DesignCriticismError(
            "the candidate criticism input violates the critic contract"
        ) from exc


def prepare_candidate_review(
    candidate: DesignCandidate,
    request: DesignGenerationRequest,
) -> PreparedInput:
    """Prepare the exact bounded critic review input for one live candidate."""

    return _prepare(GenerationPurpose.REVIEW, _review_source(candidate, request))


def _lens_pack(request: DesignGenerationRequest, registry) -> dict:
    if type(registry) is not LensRegistry:
        raise DesignCriticismError("the qualified lens registry is required")
    rules = []
    seen = set()
    for decision in request.decisions:
        for lens_decision in decision.lens_decisions:
            ref = lens_decision.lens_ref
            if str(ref) in seen:
                continue
            seen.add(str(ref))
            try:
                definition = registry.get(ref.lens_id)
            except LensError as exc:
                raise DesignCriticismError(
                    "a decision lens is not in the supplied registry"
                ) from exc
            if definition.ref != ref:
                raise DesignCriticismError(
                    "the registry lens version differs from the decision binding"
                )
            rules.append({
                "id": ref.lens_id,
                "version": ref.version,
                "status": "research_draft",
                "question": definition.distinguishing_question,
                "prediction": definition.expected_contrast,
                "falsifier": definition.disconfirmation,
                "applies_when": definition.applicability,
                "exclude_when": definition.non_applicability,
                "abstain_when": definition.abstention_condition,
                "limits": [
                    definition.confounders_and_prohibitions,
                    definition.no_change_condition,
                ],
                "provenance": [{
                    "url": "docs/lenses/definition-candidates.md",
                    "locator": str(definition.ref),
                    "read_scope": definition.source_scope,
                    "unread_scope": "none",
                }],
            })
    rules.sort(key=lambda rule: (rule["id"], rule["version"]))
    return {"id": f"lenses:{request.request_id}", "version": "1", "rules": rules}


def prepare_candidate_proposal(
    candidate: DesignCandidate,
    request: DesignGenerationRequest,
    registry,
) -> PreparedInput:
    """Prepare the counterexample-proposal input with the decisions' lens pack."""

    source = _review_source(candidate, request)
    source["lens_pack"] = _lens_pack(request, registry)
    return _prepare(GenerationPurpose.COUNTEREXAMPLE_PROPOSAL, source)


def _bound_counterexample(candidate: DesignCandidate, counterexample: object) -> dict:
    if (
        type(counterexample) is not dict
        or counterexample.get("candidate_id") != candidate.candidate_id
        or counterexample.get("candidate_version") != str(candidate.version)
    ):
        raise DesignCriticismError(
            "the counterexample does not bind this exact candidate"
        )
    return counterexample


def prepare_candidate_validity(
    candidate: DesignCandidate,
    request: DesignGenerationRequest,
    counterexample: dict,
) -> PreparedInput:
    """Prepare the validity-assessment input for one proposed counterexample."""

    source = _review_source(candidate, request)
    source["counterexample"] = _bound_counterexample(candidate, counterexample)
    return _prepare(GenerationPurpose.COUNTEREXAMPLE_VALIDITY, source)


def prepare_candidate_response(
    candidate: DesignCandidate,
    request: DesignGenerationRequest,
    counterexample: dict,
    validity: dict,
) -> PreparedInput:
    """Prepare the candidate-response input for one validity-assessed counterexample."""

    source = _review_source(candidate, request)
    source["counterexample"] = _bound_counterexample(candidate, counterexample)
    if (
        type(validity) is not dict
        or validity.get("candidate_id") != candidate.candidate_id
        or validity.get("counterexample_id") != counterexample.get("id")
    ):
        raise DesignCriticismError(
            "the validity evidence does not bind this exact counterexample"
        )
    source["validity"] = {
        key: value for key, value in validity.items() if key != "purpose"
    }
    return _prepare(GenerationPurpose.CANDIDATE_RESPONSE, source)


_VERDICT_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class CandidateVerdict:
    """Framework-owned fold of one candidate's criticism into a selectability state.

    Selection itself remains a human act (experience contract): this verdict only
    determines whether a candidate may be presented as a passed, selectable option.
    A mandatory defect is never hidden behind aggregation. The fold is the only
    issuer: a constructed or field-swapped look-alike carries no authority, and
    the verdict binds its candidate by content hash, never only by name.
    """

    candidate_id: str
    candidate_version: str
    candidate_sha: str
    status: str
    reasons: tuple[str, ...]
    _issuer_token: object = dataclass_field(repr=False, compare=False)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "candidate-criticism-verdict-v1",
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "candidate_sha": self.candidate_sha,
            "status": self.status,
            "reasons": list(self.reasons),
        }


def is_issued_verdict(value: object) -> bool:
    """True only for a verdict issued by fold_candidate_criticism."""

    return (
        type(value) is CandidateVerdict
        and getattr(value, "_issuer_token", None) is _VERDICT_TOKEN
    )


def verdict_binds_candidate(verdict, candidate) -> bool:
    """True when an issued verdict binds this exact candidate content."""

    return (
        is_issued_verdict(verdict)
        and verdict.candidate_id == candidate.candidate_id
        and verdict.candidate_version == str(candidate.version)
        and verdict.candidate_sha == candidate.graph_ref.sha256
    )


def _bound_result(candidate: DesignCandidate, value: object, label: str) -> dict:
    if (
        type(value) is not dict
        or value.get("candidate_id") != candidate.candidate_id
        or value.get("candidate_version") != str(candidate.version)
    ):
        raise DesignCriticismError(f"the {label} does not bind this exact candidate")
    return value


def fold_candidate_criticism(
    candidate: DesignCandidate,
    request: DesignGenerationRequest,
    review: dict,
    chains: list[dict],
) -> CandidateVerdict:
    """Fold review findings and counterexample chains into one selectability verdict.

    A passed verdict requires positive evidence for every derived criterion of the
    exact request: the findings must cover the criteria set exactly, so absence of
    evidence can never fold to "passed".
    """

    _require_accepted(candidate)
    if (
        type(request) is not DesignGenerationRequest
        or candidate.generation_request_ref != request.request_ref
    ):
        raise DesignCriticismError(
            "the fold requires the exact generation request of this candidate"
        )
    review = _bound_result(candidate, review, "review result")
    expected_ids = {item["id"] for item in _review_criteria(request)["items"]}
    findings = review.get("findings")
    if type(findings) is not list:
        raise DesignCriticismError("the review result carries no findings list")
    rejections: list[str] = []
    insufficiencies: list[str] = []
    seen_ids: list[str] = []
    for finding in findings:
        if type(finding) is not dict:
            raise DesignCriticismError("a review finding is malformed")
        status = finding.get("status")
        criterion = finding.get("criterion_id")
        seen_ids.append(criterion)
        if status == "fail":
            rejections.append(f"review_fail:{criterion}")
        elif status == "unresolved":
            insufficiencies.append(f"review_unresolved:{criterion}")
        elif status != "pass":
            raise DesignCriticismError("a review finding status is unknown")
    if len(set(seen_ids)) != len(seen_ids) or set(seen_ids) != expected_ids:
        raise DesignCriticismError(
            "review findings must cover the derived criteria exactly once each"
        )
    if type(chains) is not list:
        raise DesignCriticismError("counterexample chains must be a bounded list")
    for chain in chains:
        if type(chain) is not dict or set(chain) != {
            "counterexample", "validity", "response",
        }:
            raise DesignCriticismError("a counterexample chain is malformed")
        counterexample = _bound_counterexample(candidate, chain["counterexample"])
        identifier = counterexample.get("id")
        cited = counterexample.get("criterion_ids")
        if type(cited) is not list or not set(cited) <= expected_ids:
            raise DesignCriticismError(
                "a counterexample cites a criterion outside the derived set"
            )
        validity = _bound_result(candidate, chain["validity"], "validity result")
        if validity.get("counterexample_id") != identifier:
            raise DesignCriticismError(
                "the validity evidence does not bind this exact counterexample"
            )
        validity_status = validity.get("status")
        response = chain["response"]
        if response is not None:
            response = _bound_result(candidate, response, "response result")
            if (
                response.get("counterexample_id") != identifier
                or response.get("validity_status") != validity_status
            ):
                raise DesignCriticismError(
                    "the candidate response does not bind this exact validity"
                )
        if validity_status == "rejected":
            continue
        if validity_status == "unresolved":
            insufficiencies.append(f"validity_unresolved:{identifier}")
            continue
        if validity_status != "valid":
            raise DesignCriticismError("a validity status is unknown")
        if response is None or response.get("status") == "unresolved":
            insufficiencies.append(f"response_unresolved:{identifier}")
        elif response.get("status") == "fail":
            rejections.append(f"counterexample_fail:{identifier}")
        elif response.get("status") not in ("avoid", "mitigate"):
            raise DesignCriticismError("a candidate response status is unknown")
    if rejections:
        status = "rejected"
        reasons = tuple(rejections + insufficiencies)
    elif insufficiencies:
        status = "insufficient_evidence"
        reasons = tuple(insufficiencies)
    else:
        status = "passed"
        reasons = ()
    verdict = object.__new__(CandidateVerdict)
    for name, item in (
        ("candidate_id", candidate.candidate_id),
        ("candidate_version", str(candidate.version)),
        ("candidate_sha", candidate.graph_ref.sha256),
        ("status", status),
        ("reasons", reasons),
        ("_issuer_token", _VERDICT_TOKEN),
    ):
        object.__setattr__(verdict, name, item)
    return verdict


__all__ = [
    "CandidateVerdict",
    "DesignCriticismError",
    "critic_candidate_projection",
    "fold_candidate_criticism",
    "is_issued_verdict",
    "prepare_candidate_proposal",
    "prepare_candidate_response",
    "prepare_candidate_review",
    "prepare_candidate_validity",
    "verdict_binds_candidate",
]
