"""Closed, provider-neutral functional graph schema.

The graph is data, not executable source.  Parsing this module's values grants no runtime
authority; the runtime compiler performs cross-reference and authority compatibility checks.
"""

import re
from dataclasses import dataclass
from types import MappingProxyType

from .refs import (
    MAX_INTEGER,
    DomainContractError,
    EntityRef,
    canonical_json,
    positive_integer,
    uuid_string,
)

GRAPH_SCHEMA_VERSION = "graph-version-v1"
NODE_KINDS = frozenset({"agent", "deterministic", "router", "join", "human_gate", "bounded_loop"})
EDGE_KINDS = frozenset({"artifact", "control", "approval", "observation"})
MULTIPLICITIES = frozenset({"one", "many"})
FAILURE_POLICIES = frozenset({"fail_run", "block_dependants", "continue_optional"})
MAX_NODES = 256
MAX_EDGES = 1_024
MAX_CONTRACTS = 256
MAX_BINDINGS = 512
MAX_FACTS = 256
MAX_COMPLETION_CRITERIA = 64
MAX_LOOP_ITERATIONS = 100

_LOCAL_ID = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*\Z")
_QUALIFIED_ID = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}\Z")
_AUDIT_LENS_ID = re.compile(r"(?<![A-Za-z0-9])L-P\d{3}-\d{2}(?![A-Za-z0-9])", re.IGNORECASE)


class GraphContractError(DomainContractError):
    """A graph value is ambiguous, unbounded, or violates the closed schema."""


def _strict(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise GraphContractError(f"Expected exact {label}")
    return value


def _list(value, label, maximum, *, nonempty=False):
    if type(value) is not list or len(value) > maximum or (nonempty and not value):
        raise GraphContractError(f"Expected bounded {label} list")
    return value


def _text(value, label, maximum, *, local=False, qualified=False):
    if type(value) is not str or not value:
        raise GraphContractError(f"Expected nonempty {label}")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise GraphContractError(f"Invalid {label} Unicode") from exc
    if length > maximum or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise GraphContractError(f"Invalid or oversized {label}")
    if local and _LOCAL_ID.fullmatch(value) is None:
        raise GraphContractError(f"Invalid {label}")
    if qualified and _QUALIFIED_ID.fullmatch(value) is None:
        raise GraphContractError(f"Invalid {label}")
    return value


def _unique(values, key, label):
    seen = set()
    for value in values:
        marker = key(value)
        if marker in seen:
            raise GraphContractError(f"Duplicate {label}")
        seen.add(marker)
    return values


def _ref(value, kind):
    try:
        result = EntityRef.from_dict(value)
    except DomainContractError as exc:
        raise GraphContractError(str(exc)) from exc
    if result.kind != kind:
        raise GraphContractError(f"Expected {kind} reference")
    return result


def _ref_sort(value):
    return (value.kind, value.id, value.version, value.sha256)


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value):
    if isinstance(value, MappingProxyType):
        return {key: _thaw(child) for key, child in value.items()}
    if type(value) is tuple:
        return [_thaw(child) for child in value]
    return value


def _deeply_immutable(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is tuple:
        return all(_deeply_immutable(child) for child in value)
    if isinstance(value, MappingProxyType):
        return all(type(key) is str and _deeply_immutable(child)
                   for key, child in value.items())
    return False


def _scalar(value):
    if value is None or type(value) in (str, bool, int):
        try:
            canonical_json(value)
        except DomainContractError as exc:
            raise GraphContractError("Invalid typed-expression scalar") from exc
        return value
    raise GraphContractError("Typed expressions accept only exact JSON scalars")


def _expression(value, facts, *, depth=0, counter=None):
    if counter is None:
        counter = [0]
    counter[0] += 1
    if depth > 8 or counter[0] > 64 or type(value) is not dict:
        raise GraphContractError("Invalid or unbounded typed expression")
    op = value.get("op")
    if op in ("eq", "neq"):
        _strict(value, {"op", "fact", "value"}, "comparison expression")
        fact = _text(value["fact"], "fact name", 64, local=True)
        if fact not in facts:
            raise GraphContractError("Expression references an undeclared fact")
        return {"op": op, "fact": fact, "value": _scalar(value["value"])}
    if op == "in":
        _strict(value, {"op", "fact", "values"}, "membership expression")
        fact = _text(value["fact"], "fact name", 64, local=True)
        if fact not in facts:
            raise GraphContractError("Expression references an undeclared fact")
        values = [_scalar(item) for item in _list(value["values"], "membership values", 32,
                                                   nonempty=True)]
        _unique(values, lambda item: canonical_json(item), "membership value")
        return {"op": op, "fact": fact,
                "values": sorted(values, key=lambda item: canonical_json(item))}
    if op == "exists":
        _strict(value, {"op", "fact"}, "existence expression")
        fact = _text(value["fact"], "fact name", 64, local=True)
        if fact not in facts:
            raise GraphContractError("Expression references an undeclared fact")
        return {"op": op, "fact": fact}
    if op == "not":
        _strict(value, {"op", "arg"}, "negation expression")
        return {"op": op, "arg": _expression(value["arg"], facts, depth=depth + 1,
                                                 counter=counter)}
    if op in ("and", "or"):
        _strict(value, {"op", "args"}, "boolean expression")
        args = _list(value["args"], "boolean arguments", 8, nonempty=True)
        if len(args) < 2:
            raise GraphContractError("Boolean expression requires at least two arguments")
        normalized = [_expression(item, facts, depth=depth + 1, counter=counter) for item in args]
        return {"op": op, "args": normalized}
    raise GraphContractError("Unknown typed-expression operation")


@dataclass(frozen=True, slots=True)
class InputSlot:
    slot_id: str
    artifact_contract_id: str
    required: bool
    multiplicity: str

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"slot_id", "artifact_contract_id", "required", "multiplicity"},
                "input slot")
        if (type(value["required"]) is not bool or type(value["multiplicity"]) is not str
                or value["multiplicity"] not in MULTIPLICITIES):
            raise GraphContractError("Invalid input-slot requirement or multiplicity")
        return cls(_text(value["slot_id"], "slot ID", 64, local=True),
                   _text(value["artifact_contract_id"], "artifact contract ID", 64, local=True),
                   value["required"], value["multiplicity"])

    def as_dict(self):
        return {"slot_id": self.slot_id, "artifact_contract_id": self.artifact_contract_id,
                "required": self.required, "multiplicity": self.multiplicity}


@dataclass(frozen=True, slots=True)
class OutputSlot:
    slot_id: str
    artifact_contract_id: str
    multiplicity: str

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"slot_id", "artifact_contract_id", "multiplicity"}, "output slot")
        if type(value["multiplicity"]) is not str or value["multiplicity"] not in MULTIPLICITIES:
            raise GraphContractError("Invalid output-slot multiplicity")
        return cls(_text(value["slot_id"], "slot ID", 64, local=True),
                   _text(value["artifact_contract_id"], "artifact contract ID", 64, local=True),
                   value["multiplicity"])

    def as_dict(self):
        return {"slot_id": self.slot_id, "artifact_contract_id": self.artifact_contract_id,
                "multiplicity": self.multiplicity}


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    artifact_contract_id: str
    media_types: tuple[str, ...]
    schema_ref: EntityRef | None
    min_items: int
    max_items: int
    max_total_bytes: int

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"artifact_contract_id", "media_types", "schema_ref", "min_items",
                        "max_items", "max_total_bytes"}, "artifact contract")
        media = _list(value["media_types"], "media types", 16, nonempty=True)
        normalized = []
        for item in media:
            item = _text(item, "media type", 255)
            if _MIME.fullmatch(item) is None:
                raise GraphContractError("Expected normalized exact MIME type")
            normalized.append(item)
        _unique(normalized, lambda item: item, "media type")
        minimum, maximum, max_bytes = value["min_items"], value["max_items"], value["max_total_bytes"]
        if (type(minimum) is not int or type(maximum) is not int or type(max_bytes) is not int
                or not 0 <= minimum <= maximum <= 1_000 or not 1 <= max_bytes <= MAX_INTEGER):
            raise GraphContractError("Invalid artifact bounds")
        schema_ref = None if value["schema_ref"] is None else _ref(value["schema_ref"], "task_spec")
        return cls(_text(value["artifact_contract_id"], "artifact contract ID", 64, local=True),
                   tuple(sorted(normalized)), schema_ref, minimum, maximum, max_bytes)

    def as_dict(self):
        return {"artifact_contract_id": self.artifact_contract_id,
                "media_types": list(self.media_types),
                "schema_ref": None if self.schema_ref is None else self.schema_ref.as_dict(),
                "min_items": self.min_items, "max_items": self.max_items,
                "max_total_bytes": self.max_total_bytes}


@dataclass(frozen=True, slots=True)
class ModelBinding:
    binding_id: str
    model_choice_ref: EntityRef
    capabilities: tuple[str, ...]

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"binding_id", "model_choice_ref", "capabilities"}, "model binding")
        capabilities = [_text(item, "model capability", 64, qualified=True)
                        for item in _list(value["capabilities"], "model capabilities", 64,
                                          nonempty=True)]
        _unique(capabilities, lambda item: item, "model capability")
        return cls(_text(value["binding_id"], "model binding ID", 64, local=True),
                   _ref(value["model_choice_ref"], "model_choice"), tuple(sorted(capabilities)))

    def as_dict(self):
        return {"binding_id": self.binding_id, "model_choice_ref": self.model_choice_ref.as_dict(),
                "capabilities": list(self.capabilities)}


@dataclass(frozen=True, slots=True)
class ToolBinding:
    binding_id: str
    tool_definition_ref: EntityRef
    grant_ref: EntityRef
    capabilities: tuple[str, ...]

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"binding_id", "tool_definition_ref", "grant_ref", "capabilities"},
                "tool binding")
        capabilities = [_text(item, "tool capability", 64, qualified=True)
                        for item in _list(value["capabilities"], "tool capabilities", 64,
                                          nonempty=True)]
        _unique(capabilities, lambda item: item, "tool capability")
        return cls(_text(value["binding_id"], "tool binding ID", 64, local=True),
                   _ref(value["tool_definition_ref"], "tool_definition"),
                   _ref(value["grant_ref"], "grant"), tuple(sorted(capabilities)))

    def as_dict(self):
        return {"binding_id": self.binding_id,
                "tool_definition_ref": self.tool_definition_ref.as_dict(),
                "grant_ref": self.grant_ref.as_dict(), "capabilities": list(self.capabilities)}


@dataclass(frozen=True, slots=True)
class MemoryPolicy:
    policy_id: str
    purpose: str
    read_grant_refs: tuple[EntityRef, ...]
    write_grant_refs: tuple[EntityRef, ...]

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"policy_id", "purpose", "read_grant_refs", "write_grant_refs"},
                "memory policy")
        reads = [_ref(item, "grant") for item in _list(value["read_grant_refs"],
                                                         "memory read grants", 64)]
        writes = [_ref(item, "grant") for item in _list(value["write_grant_refs"],
                                                          "memory write grants", 64)]
        _unique(reads, _ref_sort, "memory read grant")
        _unique(writes, _ref_sort, "memory write grant")
        return cls(_text(value["policy_id"], "memory policy ID", 64, local=True),
                   _text(value["purpose"], "memory purpose", 64, qualified=True),
                   tuple(sorted(reads, key=_ref_sort)), tuple(sorted(writes, key=_ref_sort)))

    def as_dict(self):
        return {"policy_id": self.policy_id, "purpose": self.purpose,
                "read_grant_refs": [item.as_dict() for item in self.read_grant_refs],
                "write_grant_refs": [item.as_dict() for item in self.write_grant_refs]}


def _node_config(kind, value, facts):
    if kind == "agent":
        _strict(value, {"model_binding_id", "required_model_capabilities", "tool_binding_ids",
                        "memory_policy_id"}, "agent config")
        caps = [_text(item, "required model capability", 64, qualified=True)
                for item in _list(value["required_model_capabilities"], "required capabilities", 64)]
        tools = [_text(item, "tool binding ID", 64, local=True)
                 for item in _list(value["tool_binding_ids"], "tool bindings", 64)]
        _unique(caps, lambda item: item, "required model capability")
        _unique(tools, lambda item: item, "tool binding ID")
        memory = value["memory_policy_id"]
        if memory is not None:
            memory = _text(memory, "memory policy ID", 64, local=True)
        return {"model_binding_id": _text(value["model_binding_id"], "model binding ID", 64,
                                            local=True),
                "required_model_capabilities": sorted(caps),
                "tool_binding_ids": sorted(tools), "memory_policy_id": memory}
    if kind == "deterministic":
        # 2026-09-26 owner decision: a deterministic (model-free) node may name approved
        # tool bindings (e.g. a byte-exact store step). The field is optional and, when
        # empty, omitted from the canonical form, so a tool-free node keeps its exact
        # earlier bytes and digest. The bindings are validated like an agent's.
        if type(value) is dict and "tool_binding_ids" in value:
            _strict(value, {"handler_id", "tool_binding_ids"}, "deterministic config")
        else:
            _strict(value, {"handler_id"}, "deterministic config")
        config = {"handler_id": _text(value["handler_id"], "handler ID", 128, qualified=True)}
        tools = [_text(item, "tool binding ID", 64, local=True)
                 for item in _list(value.get("tool_binding_ids", []), "tool bindings", 64)]
        _unique(tools, lambda item: item, "tool binding ID")
        if tools:
            config["tool_binding_ids"] = sorted(tools)
        return config
    if kind == "router":
        _strict(value, {"decision_fact", "allowed_values"}, "router config")
        fact = _text(value["decision_fact"], "router decision fact", 64, local=True)
        if fact not in facts:
            raise GraphContractError("Router references an undeclared fact")
        values = [_text(item, "router enum value", 64, local=True)
                  for item in _list(value["allowed_values"], "router values", 32, nonempty=True)]
        _unique(values, lambda item: item, "router enum value")
        return {"decision_fact": fact, "allowed_values": sorted(values)}
    if kind == "join":
        mode = value.get("mode") if type(value) is dict else None
        if mode == "all_selected":
            _strict(value, {"mode", "failure_handling"}, "join config")
        elif mode == "any_success":
            _strict(value, {"mode", "failure_handling", "tie_break"}, "any-success join config")
            if value["tie_break"] != "branch_id_lexical":
                raise GraphContractError("Invalid any-success tie break")
        elif mode == "collect":
            _strict(value, {"mode", "min_selected", "max_selected", "failure_handling"},
                    "collect join config")
            if (type(value["min_selected"]) is not int or type(value["max_selected"]) is not int
                    or not 1 <= value["min_selected"] <= value["max_selected"] <= MAX_NODES):
                raise GraphContractError("Invalid collect join bounds")
        else:
            raise GraphContractError("Invalid join mode")
        if value["failure_handling"] not in ("block", "collect_failures"):
            raise GraphContractError("Invalid join failure handling")
        return dict(value)
    if kind == "human_gate":
        _strict(value, {"approval_scopes"}, "human-gate config")
        scopes = [_text(item, "approval scope", 64, qualified=True)
                  for item in _list(value["approval_scopes"], "approval scopes", 64,
                                    nonempty=True)]
        _unique(scopes, lambda item: item, "approval scope")
        return {"approval_scopes": sorted(scopes)}
    if kind == "bounded_loop":
        _strict(value, {"loop_id", "termination", "hard_iteration_cap"}, "bounded-loop config")
        cap = value["hard_iteration_cap"]
        if type(cap) is not int or not 1 <= cap <= MAX_LOOP_ITERATIONS:
            raise GraphContractError("Invalid bounded-loop hard cap")
        return {"loop_id": _text(value["loop_id"], "loop ID", 64, local=True),
                "termination": _expression(value["termination"], facts),
                "hard_iteration_cap": cap}
    raise GraphContractError("Unknown graph node kind")


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    kind: str
    responsibility: str
    input_slots: tuple[InputSlot, ...]
    output_slots: tuple[OutputSlot, ...]
    grant_refs: tuple[EntityRef, ...]
    required_approval_scopes: tuple[str, ...]
    failure_policy: str
    config: MappingProxyType

    def __post_init__(self):
        if not isinstance(self.config, MappingProxyType) or not _deeply_immutable(self.config):
            raise GraphContractError("Graph-node config must be deeply immutable")

    @classmethod
    def from_untrusted(cls, value, facts):
        _strict(value, {"node_id", "kind", "responsibility", "input_slots", "output_slots",
                        "grant_refs", "required_approval_scopes", "failure_policy", "config"},
                "graph node")
        kind = value["kind"]
        if type(kind) is not str or kind not in NODE_KINDS:
            raise GraphContractError("Invalid node kind")
        inputs = [InputSlot.from_untrusted(item) for item in
                  _list(value["input_slots"], "input slots", 128)]
        outputs = [OutputSlot.from_untrusted(item) for item in
                   _list(value["output_slots"], "output slots", 128)]
        grants = [_ref(item, "grant") for item in _list(value["grant_refs"], "node grants", 128)]
        scopes = [_text(item, "required approval scope", 64, qualified=True)
                  for item in _list(value["required_approval_scopes"], "approval scopes", 64)]
        _unique(inputs, lambda item: item.slot_id, "input slot")
        _unique(outputs, lambda item: item.slot_id, "output slot")
        _unique(grants, _ref_sort, "node grant")
        _unique(scopes, lambda item: item, "approval scope")
        failure_policy = value["failure_policy"]
        if type(failure_policy) is not str or failure_policy not in FAILURE_POLICIES:
            raise GraphContractError("Invalid node failure policy")
        config = _node_config(kind, value["config"], facts)
        responsibility = _text(value["responsibility"], "node responsibility", 4_096)
        if _AUDIT_LENS_ID.search(responsibility):
            raise GraphContractError("Atomic lens identifiers are audit-only graph data")
        return cls(_text(value["node_id"], "node ID", 64, local=True), kind,
                   responsibility,
                   tuple(sorted(inputs, key=lambda item: item.slot_id)),
                   tuple(sorted(outputs, key=lambda item: item.slot_id)),
                   tuple(sorted(grants, key=_ref_sort)), tuple(sorted(scopes)), failure_policy,
                   _freeze(config))

    def as_dict(self):
        return {"node_id": self.node_id, "kind": self.kind,
                "responsibility": self.responsibility,
                "input_slots": [item.as_dict() for item in self.input_slots],
                "output_slots": [item.as_dict() for item in self.output_slots],
                "grant_refs": [item.as_dict() for item in self.grant_refs],
                "required_approval_scopes": list(self.required_approval_scopes),
                "failure_policy": self.failure_policy,
                "config": _thaw(self.config)}


@dataclass(frozen=True, slots=True)
class GraphEdge:
    edge_id: str
    kind: str
    source_node_id: str
    target_node_id: str
    loop_id: str | None
    data: MappingProxyType

    def __post_init__(self):
        if not isinstance(self.data, MappingProxyType) or not _deeply_immutable(self.data):
            raise GraphContractError("Graph-edge data must be deeply immutable")

    @classmethod
    def from_untrusted(cls, value, facts):
        common = {"edge_id", "kind", "source_node_id", "target_node_id", "loop_id"}
        kind = value.get("kind") if type(value) is dict else None
        fields = {
            "artifact": {"source_output_slot", "target_input_slot", "artifact_contract_id",
                         "mandatory", "multiplicity"},
            "control": {"condition"},
            "approval": {"approval_scope"},
            "observation": {"observation_name"},
        }
        if type(kind) is not str or kind not in EDGE_KINDS:
            raise GraphContractError("Invalid edge kind")
        _strict(value, common | fields[kind], f"{kind} edge")
        loop_id = value["loop_id"]
        if loop_id is not None:
            loop_id = _text(loop_id, "loop ID", 64, local=True)
        if kind == "artifact":
            if (type(value["mandatory"]) is not bool or type(value["multiplicity"]) is not str
                    or value["multiplicity"] not in MULTIPLICITIES):
                raise GraphContractError("Invalid artifact edge requirement or multiplicity")
            data = {"source_output_slot": _text(value["source_output_slot"], "source slot", 64,
                                                  local=True),
                    "target_input_slot": _text(value["target_input_slot"], "target slot", 64,
                                                 local=True),
                    "artifact_contract_id": _text(value["artifact_contract_id"],
                                                    "artifact contract ID", 64, local=True),
                    "mandatory": value["mandatory"], "multiplicity": value["multiplicity"]}
        elif kind == "control":
            data = {"condition": None if value["condition"] is None
                    else _expression(value["condition"], facts)}
        elif kind == "approval":
            data = {"approval_scope": _text(value["approval_scope"], "approval scope", 64,
                                              qualified=True)}
        else:
            data = {"observation_name": _text(value["observation_name"], "observation name", 64,
                                                qualified=True)}
        return cls(_text(value["edge_id"], "edge ID", 64, local=True), kind,
                   _text(value["source_node_id"], "source node ID", 64, local=True),
                   _text(value["target_node_id"], "target node ID", 64, local=True), loop_id,
                   _freeze(data))

    def as_dict(self):
        return {"edge_id": self.edge_id, "kind": self.kind,
                "source_node_id": self.source_node_id, "target_node_id": self.target_node_id,
                "loop_id": self.loop_id, **_thaw(self.data)}


@dataclass(frozen=True, slots=True)
class CompletionCriterion:
    criterion_id: str
    node_id: str
    output_slot: str
    artifact_contract_id: str
    min_items: int

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"criterion_id", "node_id", "output_slot", "artifact_contract_id",
                        "min_items"}, "completion criterion")
        minimum = value["min_items"]
        if type(minimum) is not int or not 1 <= minimum <= 1_000:
            raise GraphContractError("Invalid completion minimum")
        return cls(_text(value["criterion_id"], "criterion ID", 64, local=True),
                   _text(value["node_id"], "completion node ID", 64, local=True),
                   _text(value["output_slot"], "completion output slot", 64, local=True),
                   _text(value["artifact_contract_id"], "artifact contract ID", 64, local=True),
                   minimum)

    def as_dict(self):
        return {"criterion_id": self.criterion_id, "node_id": self.node_id,
                "output_slot": self.output_slot,
                "artifact_contract_id": self.artifact_contract_id, "min_items": self.min_items}


@dataclass(frozen=True, slots=True)
class GraphVersion:
    schema_version: str
    graph_id: str
    version: int
    work_model_ref: EntityRef
    decision_refs: tuple[EntityRef, ...]
    entry_node_ids: tuple[str, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    artifact_contracts: tuple[ArtifactContract, ...]
    model_bindings: tuple[ModelBinding, ...]
    tool_bindings: tuple[ToolBinding, ...]
    memory_policies: tuple[MemoryPolicy, ...]
    grant_refs: tuple[EntityRef, ...]
    fact_names: tuple[str, ...]
    observation_contract_ref: EntityRef
    completion_criteria: tuple[CompletionCriterion, ...]
    budget_policy_ref: EntityRef

    def __post_init__(self):
        collections = (
            self.decision_refs,
            self.entry_node_ids,
            self.nodes,
            self.edges,
            self.artifact_contracts,
            self.model_bindings,
            self.tool_bindings,
            self.memory_policies,
            self.grant_refs,
            self.fact_names,
            self.completion_criteria,
        )
        if any(type(value) is not tuple for value in collections):
            raise GraphContractError("Graph collections must be immutable tuples")

    @classmethod
    def from_untrusted(cls, value):
        fields = {"schema_version", "graph_id", "version", "work_model_ref", "decision_refs",
                  "entry_node_ids", "nodes", "edges", "artifact_contracts", "model_bindings",
                  "tool_bindings", "memory_policies", "grant_refs", "fact_names",
                  "observation_contract_ref", "completion_criteria", "budget_policy_ref"}
        _strict(value, fields, "graph-version-v1 object")
        if value["schema_version"] != GRAPH_SCHEMA_VERSION:
            raise GraphContractError("Unsupported graph schema version")
        try:
            uuid_string(value["graph_id"])
            positive_integer(value["version"])
        except DomainContractError as exc:
            raise GraphContractError(str(exc)) from exc
        facts = [_text(item, "fact name", 64, local=True)
                 for item in _list(value["fact_names"], "fact names", MAX_FACTS)]
        _unique(facts, lambda item: item, "fact name")
        fact_set = frozenset(facts)
        decisions = [_ref(item, "design_decision") for item in
                     _list(value["decision_refs"], "design decisions", 256, nonempty=True)]
        entries = [_text(item, "entry node ID", 64, local=True)
                   for item in _list(value["entry_node_ids"], "entry nodes", MAX_NODES,
                                     nonempty=True)]
        nodes = [GraphNode.from_untrusted(item, fact_set) for item in
                 _list(value["nodes"], "nodes", MAX_NODES, nonempty=True)]
        edges = [GraphEdge.from_untrusted(item, fact_set) for item in
                 _list(value["edges"], "edges", MAX_EDGES)]
        contracts = [ArtifactContract.from_untrusted(item) for item in
                     _list(value["artifact_contracts"], "artifact contracts", MAX_CONTRACTS,
                           nonempty=True)]
        models = [ModelBinding.from_untrusted(item) for item in
                  _list(value["model_bindings"], "model bindings", MAX_BINDINGS)]
        tools = [ToolBinding.from_untrusted(item) for item in
                 _list(value["tool_bindings"], "tool bindings", MAX_BINDINGS)]
        memories = [MemoryPolicy.from_untrusted(item) for item in
                    _list(value["memory_policies"], "memory policies", MAX_BINDINGS)]
        grants = [_ref(item, "grant") for item in _list(value["grant_refs"], "graph grants", 512)]
        criteria = [CompletionCriterion.from_untrusted(item) for item in
                    _list(value["completion_criteria"], "completion criteria",
                          MAX_COMPLETION_CRITERIA, nonempty=True)]
        for collection, key, label in (
            (decisions, _ref_sort, "design decision"), (entries, lambda item: item, "entry node"),
            (nodes, lambda item: item.node_id, "node"), (edges, lambda item: item.edge_id, "edge"),
            (contracts, lambda item: item.artifact_contract_id, "artifact contract"),
            (models, lambda item: item.binding_id, "model binding"),
            (tools, lambda item: item.binding_id, "tool binding"),
            (memories, lambda item: item.policy_id, "memory policy"),
            (grants, _ref_sort, "graph grant"),
            (criteria, lambda item: item.criterion_id, "completion criterion"),
        ):
            _unique(collection, key, label)
        result = cls(GRAPH_SCHEMA_VERSION, value["graph_id"], value["version"],
                     _ref(value["work_model_ref"], "work_model"),
                     tuple(sorted(decisions, key=_ref_sort)), tuple(sorted(entries)), tuple(nodes),
                     tuple(edges), tuple(contracts), tuple(models), tuple(tools), tuple(memories),
                     tuple(sorted(grants, key=_ref_sort)), tuple(sorted(facts)),
                     _ref(value["observation_contract_ref"], "observation_contract"),
                     tuple(criteria), _ref(value["budget_policy_ref"], "budget_policy"))
        try:
            canonical_json(result.as_dict())
        except DomainContractError as exc:
            raise GraphContractError("Graph exceeds the canonical record size or depth limit") from exc
        return result

    def as_dict(self):
        return {"schema_version": self.schema_version, "graph_id": self.graph_id,
                "version": self.version, "work_model_ref": self.work_model_ref.as_dict(),
                "decision_refs": [item.as_dict() for item in sorted(self.decision_refs,
                                                                      key=_ref_sort)],
                "entry_node_ids": sorted(self.entry_node_ids),
                "nodes": [item.as_dict() for item in sorted(self.nodes, key=lambda item: item.node_id)],
                "edges": [item.as_dict() for item in sorted(self.edges, key=lambda item: item.edge_id)],
                "artifact_contracts": [item.as_dict() for item in sorted(
                    self.artifact_contracts, key=lambda item: item.artifact_contract_id)],
                "model_bindings": [item.as_dict() for item in sorted(
                    self.model_bindings, key=lambda item: item.binding_id)],
                "tool_bindings": [item.as_dict() for item in sorted(
                    self.tool_bindings, key=lambda item: item.binding_id)],
                "memory_policies": [item.as_dict() for item in sorted(
                    self.memory_policies, key=lambda item: item.policy_id)],
                "grant_refs": [item.as_dict() for item in sorted(self.grant_refs, key=_ref_sort)],
                "fact_names": sorted(self.fact_names),
                "observation_contract_ref": self.observation_contract_ref.as_dict(),
                "completion_criteria": [item.as_dict() for item in sorted(
                    self.completion_criteria, key=lambda item: item.criterion_id)],
                "budget_policy_ref": self.budget_policy_ref.as_dict()}
