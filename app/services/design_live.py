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
# 2026-09-26 owner decision: a deterministic node may name tool bindings (runtime.md §2);
# the grammar below tells the generator so, under the same grant and approval rules.
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
    "memory_policy_id (a memory policy id or null)}; deterministic {handler_id} or {handler_id, "
    "tool_binding_ids} (a model-free step that calls approved tools, e.g. a byte-exact store; "
    "its tools follow the same grant and approval rules as an agent's); router "
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
    "or deterministic node's grant_refs include the grants of its tool bindings and memory "
    "policy; graph grant_refs "
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


# T038 (2026-09-26): the live critic rejected every live candidate on the same two design
# defects (evidence/t038-live-arc-2026-09-26): downstream nodes re-emitting an artifact
# contract they received (read by the critic as shared write access) and completion
# conditions left to the producing node's own responsibility text. The critic contract is
# unchanged; the generator is told the rules it is judged by.
_CRITIC_DESIGN_RULES = (
    " Design rules the critic checks (a candidate that breaks one is rejected): (a) one writer"
    " per artifact: the critic treats every node with an output slot under an artifact contract as"
    " a writer of that artifact, so each artifact contract is produced by exactly one node; a node"
    " that verifies, approves, forwards or releases an artifact emits its own result under its own"
    " new artifact contract (e.g. approved-script, release-record) and never re-emits a contract it"
    " received or one another node produces. (b) every entry of the work model's"
    " completion_conditions, and every risk with mitigation_required, is checked explicitly by a node"
    " other than the one that produced the checked content: that node's responsibility names the"
    " condition, its result is its own artifact (e.g. a check report) on the path to the human gate"
    " or to the completion criterion, and whatever the condition depends on (e.g. a citation map, a"
    " thumbnail promise) is a declared artifact, not only responsibility text. A node that needs"
    " artifacts from two predecessors is preceded by a join, per the structure rules and rule (f)."
    # T038 attempt 2: the candidate passed every review finding and was rejected on three
    # deeper defects (a checker that could not read what it verified; content regenerated
    # after approval with no re-check; a check report of unresolved problems that did not
    # block). Stated here as general design hygiene, not as task wording.
    " (c) a check reads what it verifies: every checking node has an artifact input edge for"
    " each exact artifact it verifies or compares against (e.g. the source material a claim is"
    " checked against, not only a summary or map derived from it); a check whose responsibility"
    " names an artifact it cannot read is invalid. (d) nothing changes after approval unchecked:"
    " the content a human gate approves is the content released; no node after an approval"
    " regenerates, rewrites, reformats or otherwise alters approved content, and if a later"
    " derived artifact is unavoidable, a node other than its producer re-checks it against the"
    " approved content before release, and that check's report is an input of the release path."
    " (e) a check that finds unresolved problems blocks: a checking node's findings decide what"
    " happens next in the graph, not only in its report; route on a declared verdict fact (a"
    " router whose only onward edge to the join, gate or release is conditioned on the passing"
    " value, while a failing value goes back to revision through a bounded loop or ends the"
    " run, within the limits of rules (i) and (j)), or give the check a failure_policy that stops its dependants when it finds a"
    " problem and have every downstream join use failure_handling block; a report that lists"
    " unverified or failed items must never reach the join, gate or release as if it passed."
    # T038 attempt 3: following (c)-(e) under the one-predecessor structure rule, the
    # candidate made the checker and the release themselves joins (a join has no model and
    # performs nothing), let the release read a fresh copy from the producer, and gave a
    # text-only checker an artifact that could be in a format it cannot read. General
    # principles only, no task wording.
    " (f) a join only aggregates: a join has no model and performs nothing, so it never carries a"
    " check, review, approval or release responsibility; a check, review or release that needs"
    " inputs from several producers is a join followed by an agent or deterministic node that"
    " performs it; the join emits its own new aggregate artifact contract (a bundle carrying"
    " the exact, unaltered inputs, declared with their media types), and that node's single"
    " triggering predecessor is the join, from which it reads the bundle. (g) release takes"
    " exactly what was approved, through the gate's path: the human gate receives the exact"
    " content it approves (with the check reports) and emits it unaltered under its own"
    " approved-content contract; the releasing node reads that approved content from the gate"
    " (its artifact edge and its approval edge come from the same gate) and never takes a fresh"
    " copy, or any artifact edge, from the original producer or any node before the gate. (h) a"
    " check reads the artifact in a format it can inspect: declare the format the checker"
    " consumes (the checked contract's media_types are ones the checker's required capabilities"
    " can read, and its responsibility names that format); if the producer's format is not"
    " inspectable by the checker, add a conversion node before the check that emits an"
    " inspectable rendition under its own contract, and the check, the approval and the release"
    " all use that same checked content, never an alternative format the check did not read."
    # T038 attempt 6: the candidate passed every review finding but stayed unresolved on two
    # graph-level points: the approval join's artifact inputs came straight from nodes before
    # the verdict router (only the router's control edge carried the pass condition), and no
    # node was declared to set the routing fact from the check report. General design rules,
    # true of the graph grammar itself (an artifact edge carries no condition and triggers its
    # target; a router has no artifact output), not task wording.
    " (i) a verdict gates the data, not only the control flow: an artifact edge carries no"
    " condition and triggers its target, so a condition on one control edge never stops a node"
    " or join whose other inputs come from nodes before the decision, and a router cannot"
    " forward artifacts. So no artifact produced before a check's pass decision reaches the"
    " join, gate or release after that decision except through the decision itself: make the"
    " decision an explicitly declared deterministic verdict step in the data path. It is the"
    " only node that reads the check report for the decision (through its own artifact input"
    " edge, via a join that also carries the exact checked content, and the originals the"
    " approver must see, unaltered). Its responsibility states the rule: only when the"
    " report's overall verdict field is the passing value does it emit those inputs, byte for"
    " byte, under its own new verified-package contract; otherwise it emits nothing and fails"
    " with failure_policy fail_run, so the run ends and nothing downstream runs. The gate and"
    " the release read only that verified package (or what the gate emits from it), and no"
    " artifact edge goes from any node before the verdict step to any node after it. (j) a"
    " routing fact is set by a declared node from the report: whenever a router decides on a"
    " check's verdict, it reads the check report through its own artifact input edge from the"
    " checker, its decision fact is that report's overall verdict field, and its"
    " responsibility says so; since a router carries no data, a router's passing arm never"
    " leads to a node, join, gate or release that also takes artifact inputs from before the"
    " router, and whenever the path after the decision needs such artifacts, use the"
    " verdict step of (i) instead of a router."
)

# T038 attempt 6: two candidates were requested and one came back; the output schema only
# said "between one and the requested number" while the profile forbids renaming one
# topology as several candidates. The generator is now told to aim for the requested count
# with genuinely different structures, and when returning fewer is right.
_CANDIDATE_COUNT_RULE = (
    " Candidate count: return requested_candidate_count candidates whenever that many"
    " structurally different graphs satisfy every rule above; return fewer only when no further"
    " structurally different graph satisfies them all. Candidates differ in structure (the"
    " nodes' kinds and the edges between them), never only in ids, names or wording; for"
    " example, one checker for every condition versus several independent checkers, each for"
    " some conditions, whose reports a join aggregates before the verdict step, or a"
    " deterministic precheck of the checked format before the model check, each still"
    " following every rule above. Each candidate is complete on its own."
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
        + _CRITIC_DESIGN_RULES
        + (_REVISION_SYSTEM if revision is not None else _CANDIDATE_COUNT_RULE)
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
