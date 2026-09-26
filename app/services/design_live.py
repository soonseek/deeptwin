"""Live design-candidate generation over one untrusted model boundary.

The framework keeps every authority here: it renders the exact bounded prompt from a
framework-issued :class:`DesignGenerationRequest`, sends it through one caller-supplied
``model_turn`` callable, mints the generation-call record itself, and admits the returned
graphs only through :func:`accept_design_candidates`.  The model contributes nothing but
functional graphs — never identities, refs, or acceptance.  A malformed model turn is
terminal; this driver performs no retry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import uuid4

from ..domain.graph_schema import GRAPH_SCHEMA_VERSION
from ..domain.refs import EntityRef, canonical_json
from ..generation_profiles import DesignGenerationPurpose, design_profile_for
from .design import (
    DESIGN_CANDIDATE_SCHEMA_VERSION,
    DesignCandidate,
    DesignGenerationRequest,
    accept_design_candidates,
    is_accepted_candidate,
)

MAX_MODEL_RESPONSE_CHARS = 1_048_576
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)

# The framework owns every identity and record reference of a candidate graph: it
# fills the top-level fields in _FRAMEWORK_FIELDS itself, and the model may only
# copy references that the payload's compilation authority lists.
_FRAMEWORK_FIELDS = (
    "schema_version", "graph_id", "version", "work_model_ref", "decision_refs",
    "observation_contract_ref", "budget_policy_ref",
)
_EXAMPLE_GRAPH = {
    "entry_node_ids": ["intake"],
    "nodes": [
        {"node_id": "intake", "kind": "deterministic", "responsibility": "Normalize the source",
         "input_slots": [],
         "output_slots": [{"slot_id": "out", "artifact_contract_id": "text-document",
                           "multiplicity": "one"}],
         "grant_refs": [], "required_approval_scopes": [], "failure_policy": "block_dependants",
         "config": {"handler_id": "artifact-normalizer-v1"}},
        {"node_id": "writer", "kind": "agent", "responsibility": "Write the draft",
         "input_slots": [{"slot_id": "source", "artifact_contract_id": "text-document",
                          "required": True, "multiplicity": "one"}],
         "output_slots": [{"slot_id": "draft", "artifact_contract_id": "text-document",
                           "multiplicity": "one"}],
         "grant_refs": [], "required_approval_scopes": [], "failure_policy": "block_dependants",
         "config": {"model_binding_id": "writer-model", "required_model_capabilities": ["text"],
                    "tool_binding_ids": [], "memory_policy_id": "work-memory"}},
    ],
    "edges": [
        {"edge_id": "e1", "kind": "artifact", "source_node_id": "intake",
         "target_node_id": "writer", "loop_id": None, "source_output_slot": "out",
         "target_input_slot": "source", "artifact_contract_id": "text-document",
         "mandatory": True, "multiplicity": "one"},
    ],
    "artifact_contracts": [
        {"artifact_contract_id": "text-document", "media_types": ["text/markdown"],
         "schema_ref": None, "min_items": 1, "max_items": 1, "max_total_bytes": 1048576},
    ],
    "model_bindings": [
        {"binding_id": "writer-model", "model_choice_ref": "<one compilation_authority model "
         "choice ref object, copied exactly>", "capabilities": ["text"]},
    ],
    "tool_bindings": [],
    "memory_policies": [
        {"policy_id": "work-memory", "purpose": "operational", "read_grant_refs": [],
         "write_grant_refs": []},
    ],
    "grant_refs": [],
    "fact_names": [],
    "completion_criteria": [
        {"criterion_id": "final-draft", "node_id": "writer", "output_slot": "draft",
         "artifact_contract_id": "text-document", "min_items": 1},
    ],
}
_OUTPUT_SCHEMA = (
    'Return exactly one JSON object of the form {"candidates": [{"graph": '
    "<functional-graph-object>}, ...]} with between one and the requested number of "
    "candidates, no commentary and no markdown. Each graph has exactly the fields of this "
    "illustrative two-node graph (its topology is an example, not a template): "
    + json.dumps(_EXAMPLE_GRAPH, ensure_ascii=False, separators=(",", ":"))
    + " Grammar (exact field sets, no extra keys): node kind is one of agent, deterministic, "
    "router, join, human_gate, bounded_loop; node failure_policy is one of fail_run, "
    "block_dependants, continue_optional; slot and edge multiplicity is one or many. Node "
    "config by kind: agent {model_binding_id, required_model_capabilities, tool_binding_ids, "
    "memory_policy_id (a memory policy id or null)}; deterministic {handler_id}; router "
    "{decision_fact (declared in fact_names), allowed_values}; join {mode: all_selected, "
    "failure_handling} or {mode: any_success, failure_handling, tie_break: branch_id_lexical} "
    "or {mode: collect, min_selected, max_selected, failure_handling}, with failure_handling "
    "block or collect_failures; human_gate {approval_scopes (from the authority)}; "
    "bounded_loop {loop_id, termination (an expression), hard_iteration_cap 1..100}. Edge "
    "kinds, each with edge_id, kind, source_node_id, target_node_id, loop_id (null unless "
    "inside a loop): artifact {source_output_slot, target_input_slot, artifact_contract_id, "
    "mandatory, multiplicity}; control {condition (an expression or null)}; approval "
    "{approval_scope}; observation {observation_name}. Expressions: {op: eq|neq, fact, value}, "
    "{op: in, fact, values}, {op: exists, fact}, {op: not, arg}, {op: and|or, args}, over "
    "declared fact_names. Bindings: model binding {binding_id, model_choice_ref, "
    "capabilities}; tool binding {binding_id, tool_definition_ref (a tool definition's "
    "definition_ref), grant_ref (that definition's required_grant_ref), capabilities}; memory "
    "policy {policy_id, purpose, read_grant_refs, write_grant_refs}; artifact contract "
    "{artifact_contract_id, media_types, schema_ref (null), min_items, max_items, "
    "max_total_bytes}; completion criterion {criterion_id, node_id, output_slot, "
    "artifact_contract_id, min_items}; capabilities are a subset of the authority's. "
    "Structure: every edge except an observation edge triggers its target; a node with more "
    "than one triggering predecessor must be a join, and a join needs at least two; entry "
    "nodes have none; every node is reachable from an entry; each required input slot has "
    "exactly one mandatory producing artifact edge, from an existing output slot under the "
    "same artifact contract. Each binding, memory policy and graph grant is used; an agent's "
    "grant_refs include the grants of its tool bindings and memory policy; graph grant_refs "
    "are exactly the grants used. A node with required_approval_scopes receives exactly one "
    "approval edge per scope, from a human_gate whose approval_scopes contain it, and approval "
    "edges go nowhere else; a node bound to a tool listed in tool_approval_scopes requires that "
    "scope. A router's triggering out-edges are control edges whose conditions are {op: eq, "
    "fact: its decision_fact, value} covering allowed_values exactly once. Avoid cycles "
    "unless revision needs one; then every edge of the cycle carries the loop's loop_id, the "
    "cycle contains exactly one bounded_loop node with that loop_id, and its termination "
    "controls the cycle's one exit. Omit "
    + ", ".join(_FRAMEWORK_FIELDS)
    + ": the framework sets them. Every candidate must realize every entry of "
    "required_effects verbatim: the graph element named by target (a node, edge, binding "
    "or contract with exactly that id) exists, and its field holds exactly expected_value, "
    "character for character; never paraphrase it. Copy model choice, tool definition and grant references "
    "only from the payload's compilation_authority, exactly; invent no reference, identity "
    "or approval scope."
)


def _complete_graph(request: DesignGenerationRequest, graph: object) -> object:
    """Fill the framework-owned top-level fields the model omitted. A value the model
    did supply is kept and must pass the same strict admission as any other field."""

    if type(graph) is not dict:
        return graph
    authority = request.compilation_authority
    owned = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "graph_id": str(uuid4()),
        "version": 1,
        "work_model_ref": request.work_target.work_model_ref.as_dict(),
        "decision_refs": [item.decision_ref.as_dict() for item in request.decisions],
    }
    for name, refs in (("observation_contract_ref", authority.observation_contract_refs),
                       ("budget_policy_ref", authority.budget_policy_refs)):
        if len(refs) == 1:
            owned[name] = refs[0].as_dict()
    return {**{name: value for name, value in owned.items() if name not in graph}, **graph}


class DesignGenerationError(ValueError):
    """Terminal live-generation failure; the model turn cannot be retried here."""


@dataclass(frozen=True, slots=True)
class GenerationCallRecord:
    """The framework-minted durable fact of one exact model generation call."""

    call_id: str
    version: int
    request_ref: EntityRef
    purpose: str
    profile_digest: str
    model_id: str
    prompt_sha256: str
    response_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.call_id) is not str
            or _UUID.fullmatch(self.call_id) is None
            or self.version != 1
            or type(self.request_ref) is not EntityRef
            or self.purpose != DesignGenerationPurpose.DESIGN_CANDIDATE.value
            or type(self.profile_digest) is not str
            or _SHA256.fullmatch(self.profile_digest) is None
            or type(self.model_id) is not str
            or _MODEL_ID.fullmatch(self.model_id) is None
            or type(self.prompt_sha256) is not str
            or _SHA256.fullmatch(self.prompt_sha256) is None
            or type(self.response_sha256) is not str
            or _SHA256.fullmatch(self.response_sha256) is None
        ):
            raise DesignGenerationError("generation call record is invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "design-generation-call-v1",
            "call_id": self.call_id,
            "version": self.version,
            "request_ref": self.request_ref.as_dict(),
            "purpose": self.purpose,
            "profile_digest": self.profile_digest,
            "model_id": self.model_id,
            "prompt_sha256": self.prompt_sha256,
            "response_sha256": self.response_sha256,
        }

    @property
    def call_ref(self) -> EntityRef:
        return EntityRef(
            "decision_record",
            self.call_id,
            self.version,
            sha256(canonical_json(self.as_dict())).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class DesignGenerationResult:
    candidates: tuple[DesignCandidate, ...]
    call_record: GenerationCallRecord = field(repr=False)


MAX_REVISION_INSTRUCTION_BYTES = 4096
_REVISION_SYSTEM = (
    " Revision: the payload's `revision` names one accepted parent graph of this request and the"
    " owner's instruction. Return exactly one candidate: the parent graph changed so that it follows"
    " the instruction, still realizing every required effect and every rule above. Do not copy the"
    " parent unchanged."
)


def _revision(request, revision):
    """The (parent candidate, instruction) of an owner's edit, checked: the parent is an
    accepted candidate of THIS request and the instruction is bounded owner text."""

    if revision is None:
        return None
    if type(revision) is not tuple or len(revision) != 2:
        raise DesignGenerationError("a revision is (accepted parent candidate, instruction)")
    parent, instruction = revision
    if not is_accepted_candidate(parent) or parent.generation_request_ref != request.request_ref:
        raise DesignGenerationError("a revision parent must be an accepted candidate of this request")
    if (type(instruction) is not str or not instruction.strip()
            or len(instruction.encode("utf-8")) > MAX_REVISION_INSTRUCTION_BYTES):
        raise DesignGenerationError("a revision instruction is bounded non-empty text")
    return parent, instruction


def render_candidate_prompt(request: DesignGenerationRequest, revision=None) -> tuple[str, str]:
    """Render the deterministic (system, user) prompt pair for one request; with a
    `revision` (an owner's edit of one accepted candidate) the payload also carries the
    parent graph and the owner's instruction, and exactly one candidate is asked for."""

    if type(request) is not DesignGenerationRequest:
        raise DesignGenerationError("a framework-issued generation request is required")
    revision = _revision(request, revision)
    profile = design_profile_for(DesignGenerationPurpose.DESIGN_CANDIDATE)
    system = (
        f"{profile.base_instructions}\n{profile.developer_instructions}\n{_OUTPUT_SCHEMA}"
        + (_REVISION_SYSTEM if revision is not None else "")
    )
    payload = {
        "generation_request": request.as_dict(),
        "work_model": request.work_target.work_model.as_dict(),
        "design_decisions": [item.as_dict() for item in request.decisions],
        "design_disposition": request.design_disposition,
        "requested_candidate_count": request.requested_candidate_count,
        # the lens effects every candidate must realize exactly, lifted out of the
        # decisions so they cannot be missed; hash-only effects appear without a value
        "required_effects": [
            {key: value for key, value in effect.as_dict().items()
             if key in ("effect_id", "target", "expected_value")}
            for decision in request.decisions for effect in decision.proposed_effects
        ],
        "compilation_authority": request.compilation_authority.as_dict(),
        # derived from the authority: the approval scope a node bound to each such tool
        # must require (the compiler enforces it; the model cannot compute it)
        "tool_approval_scopes": [
            {"definition_ref": item.definition_ref.as_dict(), "approval_scope": item.approval_scope}
            for item in request.compilation_authority.tool_definitions
            if item.approval_scope is not None
        ],
    }
    if revision is not None:
        parent, instruction = revision
        payload["requested_candidate_count"] = 1
        payload["revision"] = {"parent_candidate_id": parent.candidate_id,
                               "parent_graph": parent.graph.as_dict(), "instruction": instruction}
    return system, canonical_json(payload).decode("utf-8")


def _parse_model_graphs(raw: object, maximum: int) -> list[object]:
    if type(raw) is not str or not 1 <= len(raw) <= MAX_MODEL_RESPONSE_CHARS:
        raise DesignGenerationError("model response is not bounded text")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise DesignGenerationError("model response is not valid JSON") from exc
    if type(value) is not dict or set(value) != {"candidates"}:
        raise DesignGenerationError("model response is not the exact candidates object")
    candidates = value["candidates"]
    if type(candidates) is not list or not 1 <= len(candidates) <= maximum:
        raise DesignGenerationError("model candidate list is out of bounds")
    graphs = []
    for item in candidates:
        if type(item) is not dict or set(item) != {"graph"}:
            raise DesignGenerationError(
                "a model candidate may contain exactly one graph and nothing else"
            )
        graphs.append(item["graph"])
    return graphs


def _response_bytes(raw: str) -> bytes:
    try:
        return raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DesignGenerationError("model response is not encodable text") from exc


def run_candidate_generation(
    request: DesignGenerationRequest,
    *,
    model_turn,
    model_id: str,
    call_id: str | None = None,
    revision=None,
) -> DesignGenerationResult:
    """Run one bounded generation call and admit its graphs through the authority.

    With `revision=(parent, instruction)` the call realizes an owner's edit: exactly one
    graph is admitted, as a new candidate whose parent is that exact accepted candidate;
    it carries no verdict and must be criticized from scratch."""

    if type(request) is not DesignGenerationRequest:
        raise DesignGenerationError("a framework-issued generation request is required")
    if type(model_id) is not str or _MODEL_ID.fullmatch(model_id) is None:
        raise DesignGenerationError("an exact bounded model identity is required")
    if not callable(model_turn):
        raise DesignGenerationError("a callable model boundary is required")
    revision = _revision(request, revision)
    system, user = render_candidate_prompt(request, revision)
    try:
        raw = model_turn(system, user)
    except Exception as exc:
        raise DesignGenerationError("the model boundary failed") from exc
    graphs = _parse_model_graphs(raw, 1 if revision is not None else request.requested_candidate_count)
    record = GenerationCallRecord(
        call_id=call_id if call_id is not None else str(uuid4()),
        version=1,
        request_ref=request.request_ref,
        purpose=DesignGenerationPurpose.DESIGN_CANDIDATE.value,
        profile_digest=design_profile_for(
            DesignGenerationPurpose.DESIGN_CANDIDATE
        ).digest,
        model_id=model_id,
        prompt_sha256=sha256(
            canonical_json({"system": system, "user": user})
        ).hexdigest(),
        response_sha256=sha256(_response_bytes(raw)).hexdigest(),
    )
    values = [
        {
            "schema_version": DESIGN_CANDIDATE_SCHEMA_VERSION,
            "candidate_id": str(uuid4()),
            "version": 1,
            "generation_request_ref": request.request_ref.as_dict(),
            "parent_candidate_refs": [] if revision is None else [revision[0].candidate_ref.as_dict()],
            "generation_call_refs": [record.call_ref.as_dict()],
            # a revision is a new design version: the framework mints its identity even
            # when the model echoes the parent's
            "graph": (_complete_graph(request, graph) if revision is None or type(graph) is not dict
                      else {**_complete_graph(request, graph), "graph_id": str(uuid4()), "version": 1}),
        }
        for graph in graphs
    ]
    accepted = accept_design_candidates(request, values)
    return DesignGenerationResult(candidates=tuple(accepted), call_record=record)


__all__ = [
    "MAX_MODEL_RESPONSE_CHARS",
    "MAX_REVISION_INSTRUCTION_BYTES",
    "DesignGenerationError",
    "DesignGenerationResult",
    "GenerationCallRecord",
    "render_candidate_prompt",
    "run_candidate_generation",
]
