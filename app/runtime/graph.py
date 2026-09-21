"""Cross-reference compiler for the DeepTwin functional graph contract.

Compilation selects only fixed core handler keys.  It never imports a path, evaluates a
predicate, binds a provider client, or converts a graph declaration into authority.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256

from ..domain.graph_schema import GraphContractError, GraphVersion
from ..domain.refs import DomainContractError, EntityRef, canonical_json
from ..extensions.port_contracts import EFFECT_CLASSES, EFFECT_FAMILIES
from .gates import tool_approval_scope

HANDLER_KEYS = {
    "agent": "core.agent",
    "deterministic": "core.deterministic",
    "router": "core.router",
    "join": "core.join",
    "human_gate": "core.human_gate",
    "bounded_loop": "core.bounded_loop",
}
_CAPABILITY = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_AUTHORITY_TOKEN = object()


def _ref_sort(value):
    return (value.kind, value.id, value.version, value.sha256)


def _trusted_ref(value, kind, label):
    if type(value) is not EntityRef or value.kind != kind:
        raise GraphContractError(f"Trusted {label} must be an exact {kind} reference")
    return value


def _trusted_capabilities(values, label, *, nonempty=True):
    try:
        items = tuple(values)
    except TypeError as exc:
        raise GraphContractError(f"Trusted {label} capabilities must be bounded") from exc
    if (len(items) > 64 or (nonempty and not items)
            or any(type(item) is not str or _CAPABILITY.fullmatch(item) is None
                   for item in items)
            or len(set(items)) != len(items)):
        raise GraphContractError(f"Trusted {label} capabilities are invalid")
    return tuple(sorted(items))


# the worker's execute identifier grammar (app/workers/broker.py): a definition the graph
# vouches for must be one the transport can name
_TOOL_ID = re.compile(r"(?=.{1,64}\Z)[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*\Z")
_TOOL_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}\Z")


def _trusted_text(value, pattern, label):
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise GraphContractError(f"Trusted {label} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class TrustedToolDefinition:
    """One tool the caller vouches for: its record, its grant, its capabilities, the
    tool's identity (id, version) as the worker names it, and its effect class in the
    ports contract's vocabulary — authoritative for every binding, never the worker's
    claim (runtime.md §6; extension-ports.md `effect-class`)."""

    definition_ref: EntityRef
    required_grant_ref: EntityRef
    capabilities: tuple[str, ...]
    tool_id: str
    version: str
    effect_class: str

    @property
    def approval_scope(self):
        """The gate scope a binding to this tool requires when its effect needs an
        explicit approval (the ports' external family), else None."""
        if EFFECT_FAMILIES[self.effect_class] != "X":
            return None
        return tool_approval_scope(self.tool_id, self.version)

    def as_dict(self):
        return {
            "definition_ref": self.definition_ref.as_dict(),
            "required_grant_ref": self.required_grant_ref.as_dict(),
            "capabilities": list(self.capabilities),
            "tool_id": self.tool_id,
            "version": self.version,
            "effect_class": self.effect_class,
        }


@dataclass(frozen=True, slots=True, init=False)
class CompilationAuthority:
    """Caller-issued snapshot of records the graph is allowed to reference.

    It is deliberately supplied separately from graph JSON, so a generated graph cannot
    establish model/tool/grant/approval authority by making internally consistent claims.
    """

    model_choices: tuple[tuple[EntityRef, tuple[str, ...]], ...]
    tool_definitions: tuple[TrustedToolDefinition, ...]
    grant_refs: tuple[EntityRef, ...]
    approval_scopes: tuple[str, ...]
    observation_contract_refs: tuple[EntityRef, ...]
    budget_policy_refs: tuple[EntityRef, ...]
    artifact_schema_refs: tuple[EntityRef, ...]
    _issuer_token: object

    @classmethod
    def from_trusted(
        cls,
        *,
        model_choices,
        tool_definitions,
        grant_refs,
        approval_scopes,
        observation_contract_refs,
        budget_policy_refs,
        artifact_schema_refs,
    ):
        try:
            raw_models = tuple(model_choices)
            raw_tools = tuple(tool_definitions)
            raw_grants = tuple(grant_refs)
            raw_approvals = tuple(approval_scopes)
            raw_observations = tuple(observation_contract_refs)
            raw_budgets = tuple(budget_policy_refs)
            raw_schemas = tuple(artifact_schema_refs)
        except TypeError as exc:
            raise GraphContractError("Trusted compilation authority must be finite") from exc
        if any(len(value) > 512 for value in (
            raw_models, raw_tools, raw_grants, raw_observations, raw_budgets, raw_schemas
        )) or len(raw_approvals) > 128:
            raise GraphContractError("Trusted compilation authority exceeds its bounds")

        models = []
        for item in raw_models:
            if type(item) is not tuple or len(item) != 2:
                raise GraphContractError("Trusted model authority tuple is invalid")
            models.append((
                _trusted_ref(item[0], "model_choice", "model choice"),
                _trusted_capabilities(item[1], "model"),
            ))
        tools = []
        for item in raw_tools:
            if type(item) is not tuple or len(item) != 6:
                raise GraphContractError("Trusted tool authority tuple is invalid")
            effect_class = item[5]
            if type(effect_class) is not str or effect_class not in EFFECT_CLASSES:
                raise GraphContractError("Trusted tool effect class is outside the ports contract")
            tools.append(TrustedToolDefinition(
                _trusted_ref(item[0], "tool_definition", "tool definition"),
                _trusted_ref(item[1], "grant", "tool grant"),
                _trusted_capabilities(item[2], "tool"),
                _trusted_text(item[3], _TOOL_ID, "tool id"),
                _trusted_text(item[4], _TOOL_VERSION, "tool version"),
                effect_class,
            ))
        grants = tuple(sorted(
            (_trusted_ref(item, "grant", "grant") for item in raw_grants),
            key=_ref_sort,
        ))
        observations = tuple(sorted(
            (_trusted_ref(item, "observation_contract", "observation contract")
             for item in raw_observations),
            key=_ref_sort,
        ))
        budgets = tuple(sorted(
            (_trusted_ref(item, "budget_policy", "budget policy") for item in raw_budgets),
            key=_ref_sort,
        ))
        schemas = tuple(sorted(
            (_trusted_ref(item, "task_spec", "artifact schema") for item in raw_schemas),
            key=_ref_sort,
        ))
        if (any(type(item) is not str or _CAPABILITY.fullmatch(item) is None
                for item in raw_approvals)
                or len(set(raw_approvals)) != len(raw_approvals)):
            raise GraphContractError("Trusted approval scopes are invalid")
        # an external-family tool's approval scope is trusted by derivation from the
        # definition the caller vouched for, never listed by hand
        derived = {tool.approval_scope for tool in tools if tool.approval_scope is not None}
        raw_approvals = tuple(sorted(set(raw_approvals) | derived))
        for values, key, label in (
            (models, lambda item: _ref_sort(item[0]), "model choice"),
            (tools, lambda item: _ref_sort(item.definition_ref), "tool definition"),
            (grants, _ref_sort, "grant"),
            (observations, _ref_sort, "observation contract"),
            (budgets, _ref_sort, "budget policy"),
            (schemas, _ref_sort, "artifact schema"),
        ):
            keys = [key(item) for item in values]
            if len(set(keys)) != len(keys):
                raise GraphContractError(f"Duplicate trusted {label}")
        # one effect class per tool identity: the gate's answer must not depend on which
        # of two definitions of the same tool a graph happened to bind
        by_identity = {}
        for tool in tools:
            claimed = by_identity.setdefault((tool.tool_id, tool.version), tool.effect_class)
            if claimed != tool.effect_class:
                raise GraphContractError("Trusted tool definitions disagree on a tool's effect class")
        result = object.__new__(cls)
        for name, value in {
            "model_choices": tuple(sorted(models, key=lambda item: _ref_sort(item[0]))),
            "tool_definitions": tuple(sorted(tools, key=lambda item: _ref_sort(item.definition_ref))),
            "grant_refs": grants,
            "approval_scopes": tuple(sorted(raw_approvals)),
            "observation_contract_refs": observations,
            "budget_policy_refs": budgets,
            "artifact_schema_refs": schemas,
            "_issuer_token": _AUTHORITY_TOKEN,
        }.items():
            object.__setattr__(result, name, value)
        # The snapshot itself is bounded and canonical before it can authorize compilation.
        try:
            canonical_json(result.as_dict())
        except DomainContractError as exc:
            raise GraphContractError("Trusted compilation authority exceeds canonical bounds") from exc
        return result

    def as_dict(self):
        return {
            "model_choices": [
                {"model_choice_ref": ref.as_dict(), "capabilities": list(capabilities)}
                for ref, capabilities in self.model_choices
            ],
            "tool_definitions": [item.as_dict() for item in self.tool_definitions],
            "grant_refs": [item.as_dict() for item in self.grant_refs],
            "approval_scopes": list(self.approval_scopes),
            "observation_contract_refs": [item.as_dict()
                                          for item in self.observation_contract_refs],
            "budget_policy_refs": [item.as_dict() for item in self.budget_policy_refs],
            "artifact_schema_refs": [item.as_dict() for item in self.artifact_schema_refs],
        }

    @property
    def digest(self):
        return sha256(canonical_json(self.as_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class CompiledNode:
    node_id: str
    kind: str
    responsibility: str


@dataclass(frozen=True, slots=True)
class CompiledToolBinding:
    """Compiler projection, not persisted qualification or action authority."""

    graph_digest: str
    authority_digest: str
    node_id: str
    binding_id: str
    definition_ref: EntityRef
    grant_ref: EntityRef
    tool_id: str
    version: str
    effect_class: str
    approval_gate_node_id: str | None


class CompiledToolTransport(ABC):
    """Code-owned coherence interface; implementing it confers no qualification.

    Shared here to avoid a cycle between the dispatcher and worker transport.
    Generic injected executors remain a trusted test/code seam.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def compiled_tool_binding(self):
        """One immutable compiler projection, or None for a read-only query."""

    @abstractmethod
    def require_dispatch_ledger(self, ledger):
        """Require the invoking dispatcher to own this exact ledger/store."""

    @abstractmethod
    def require_compiled_context(self, compiled, node_id, ledger):
        """Validate the complete graph/authority/node projection before reservation."""


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    graph_digest: str
    entry_node_ids: tuple[str, ...]
    nodes: tuple[CompiledNode, ...]
    handler_keys: tuple[tuple[str, str], ...]
    activation_predecessors: tuple[tuple[str, tuple[str, ...]], ...]
    loop_regions: tuple[tuple[str, tuple[str, ...], int], ...]
    execution_graph: GraphVersion
    authority_digest: str
    # per tool binding on a node: (node id, binding id, tool id, version, effect class, the
    # human gate supplying the tool's approval scope or None) — the authority's facts, sorted
    tool_effects: tuple[tuple[str, str, str, str, str, str | None], ...] = ()
    tool_bindings: tuple[CompiledToolBinding, ...] = ()
    compilation_authority: CompilationAuthority | None = None


def graph_digest(graph):
    if type(graph) is not GraphVersion:
        raise GraphContractError("Expected parsed GraphVersion")
    graph = _normalized_graph(graph)
    return sha256(canonical_json(graph.as_dict())).hexdigest()


def _normalized_graph(graph):
    """Re-parse even directly constructed dataclasses at every authority boundary."""
    if type(graph) is not GraphVersion:
        raise GraphContractError("Expected parsed GraphVersion")
    try:
        return GraphVersion.from_untrusted(graph.as_dict())
    except GraphContractError:
        raise
    except Exception as exc:
        raise GraphContractError("Invalid directly constructed GraphVersion") from exc


def _index(values, field):
    return {getattr(value, field): value for value in values}


def _triggering(edge):
    return edge.kind != "observation"


def _strong_components(node_ids, edges):
    adjacency = {node_id: [] for node_id in node_ids}
    for edge in edges:
        if _triggering(edge):
            adjacency[edge.source_node_id].append(edge.target_node_id)
    for values in adjacency.values():
        values.sort()
    index = 0
    stack = []
    indices = {}
    lowlinks = {}
    on_stack = set()
    components = []

    def visit(node_id):
        nonlocal index
        indices[node_id] = lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target in adjacency[node_id]:
            if target not in indices:
                visit(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target])
        if lowlinks[node_id] == indices[node_id]:
            component = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node_id:
                    break
            components.append(tuple(sorted(component)))

    for node_id in sorted(node_ids):
        if node_id not in indices:
            visit(node_id)
    return tuple(sorted(components))


def _loop_regions(nodes, edges):
    node_map = {node.node_id: node for node in nodes}
    cyclic = []
    edge_pairs = {(edge.source_node_id, edge.target_node_id) for edge in edges if _triggering(edge)}
    for component in _strong_components(node_map, edges):
        if len(component) > 1 or (component[0], component[0]) in edge_pairs:
            cyclic.append(component)
    membership = {}
    regions = []
    used_loop_ids = set()
    for component in cyclic:
        members = set(component)
        internal = [edge for edge in edges if _triggering(edge)
                    and edge.source_node_id in members and edge.target_node_id in members]
        loop_ids = {edge.loop_id for edge in internal}
        if None in loop_ids or len(loop_ids) != 1:
            raise GraphContractError("Every cycle edge must name one exact bounded loop")
        loop_id = next(iter(loop_ids))
        if loop_id in used_loop_ids:
            raise GraphContractError("A loop ID can identify only one cycle region")
        used_loop_ids.add(loop_id)
        controllers = [node for node in nodes if node.node_id in members
                       and node.kind == "bounded_loop"
                       and node.config["loop_id"] == loop_id]
        if len(controllers) != 1:
            raise GraphContractError("Each cycle requires exactly one matching bounded-loop node")
        controller = controllers[0]
        exits = [edge for edge in edges if _triggering(edge)
                 and edge.source_node_id in members
                 and edge.target_node_id not in members]
        termination = controller.as_dict()["config"]["termination"]
        exit_condition = exits[0].as_dict()["condition"] if exits else None
        if (len(exits) != 1 or exits[0].kind != "control"
                or exits[0].source_node_id != controller.node_id
                or canonical_json(exit_condition) != canonical_json(termination)):
            raise GraphContractError("A bounded-loop termination must control its one exact exit")
        for node_id in component:
            if node_id in membership:
                raise GraphContractError("A node cannot belong to multiple loop regions")
            membership[node_id] = loop_id
        regions.append((loop_id, component, controller.config["hard_iteration_cap"]))
    for node in nodes:
        if node.kind == "bounded_loop" and node.node_id not in membership:
            raise GraphContractError("A bounded-loop node must control an actual cycle")
    for edge in edges:
        if (edge.loop_id is not None
                and (membership.get(edge.source_node_id) != edge.loop_id
                     or membership.get(edge.target_node_id) != edge.loop_id)):
            raise GraphContractError("Loop IDs are valid only on internal cycle edges")
    return tuple(sorted(regions)), membership


def _validate_router(node, edges):
    triggering = [edge for edge in edges if edge.source_node_id == node.node_id
                  and _triggering(edge)]
    if any(edge.kind != "control" for edge in triggering):
        raise GraphContractError("Router triggering outputs must be exact control arms")
    outgoing = triggering
    seen = []
    for edge in outgoing:
        condition = edge.data["condition"]
        if (condition is None or condition.get("op") != "eq"
                or condition.get("fact") != node.config["decision_fact"]
                or type(condition.get("value")) is not str):
            raise GraphContractError("Router branches require exact typed enum equality")
        seen.append(condition["value"])
    if sorted(seen) != sorted(node.config["allowed_values"]):
        raise GraphContractError("Router branches must cover each declared enum exactly once")


def _validate_structure(graph):
    nodes = _index(graph.nodes, "node_id")
    contracts = _index(graph.artifact_contracts, "artifact_contract_id")
    models = _index(graph.model_bindings, "binding_id")
    tools = _index(graph.tool_bindings, "binding_id")
    memories = _index(graph.memory_policies, "policy_id")
    graph_grants = set(graph.grant_refs)

    for entry in graph.entry_node_ids:
        if entry not in nodes:
            raise GraphContractError("Entry references a missing node")
    for node in graph.nodes:
        for slot in (*node.input_slots, *node.output_slots):
            if slot.artifact_contract_id not in contracts:
                raise GraphContractError("Node slot references an unknown artifact contract")
            contract = contracts[slot.artifact_contract_id]
            if getattr(slot, "required", False) and contract.min_items < 1:
                raise GraphContractError("A required input contract must require an item")
        if not set(node.grant_refs) <= graph_grants:
            raise GraphContractError("Node grant is not in the graph authority set")
    for tool in graph.tool_bindings:
        if tool.grant_ref not in graph_grants:
            raise GraphContractError("Tool binding grant is not in the graph authority set")
    for policy in graph.memory_policies:
        if not set(policy.read_grant_refs + policy.write_grant_refs) <= graph_grants:
            raise GraphContractError("Memory policy grant is not in the graph authority set")

    edge_ids = set()
    for edge in graph.edges:
        if edge.edge_id in edge_ids:
            raise GraphContractError("Duplicate edge")
        edge_ids.add(edge.edge_id)
        if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
            raise GraphContractError("Edge references a missing endpoint")
        if _triggering(edge) and edge.source_node_id == edge.target_node_id:
            raise GraphContractError("Triggering self edges are not permitted")
        if edge.kind == "artifact":
            source_outputs = {slot.slot_id: slot for slot in nodes[edge.source_node_id].output_slots}
            target_inputs = {slot.slot_id: slot for slot in nodes[edge.target_node_id].input_slots}
            source = source_outputs.get(edge.data["source_output_slot"])
            target = target_inputs.get(edge.data["target_input_slot"])
            contract_id = edge.data["artifact_contract_id"]
            if source is None or target is None:
                raise GraphContractError("Artifact edge references a missing input or output slot")
            if (contract_id not in contracts or source.artifact_contract_id != contract_id
                    or target.artifact_contract_id != contract_id):
                raise GraphContractError("Artifact edge and slot contracts do not match")
            if (edge.data["multiplicity"] != target.multiplicity
                    or (source.multiplicity == "many"
                        and edge.data["multiplicity"] != "many")):
                raise GraphContractError("Artifact edge multiplicity is incompatible with its slots")

    for node in graph.nodes:
        incoming_artifacts = [edge for edge in graph.edges if edge.kind == "artifact"
                              and edge.target_node_id == node.node_id]
        for slot in node.input_slots:
            producers = [edge for edge in incoming_artifacts
                         if edge.data["target_input_slot"] == slot.slot_id]
            mandatory = [edge for edge in producers if edge.data["mandatory"]]
            if slot.required and not mandatory:
                raise GraphContractError("Required input has no mandatory producer")
            if slot.multiplicity == "one" and len(producers) > 1:
                raise GraphContractError("Single input has multiple producers")

    for node in graph.nodes:
        if node.kind == "agent":
            model = models.get(node.config["model_binding_id"])
            if model is None:
                raise GraphContractError("Agent references an unknown model binding")
            if not set(node.config["required_model_capabilities"]) <= set(model.capabilities):
                raise GraphContractError("Model binding lacks a required capability")
            selected_tools = []
            for binding_id in node.config["tool_binding_ids"]:
                if binding_id not in tools:
                    raise GraphContractError("Agent references an unknown tool binding")
                selected_tools.append(tools[binding_id])
            memory = None
            if node.config["memory_policy_id"] is not None:
                memory = memories.get(node.config["memory_policy_id"])
                if memory is None:
                    raise GraphContractError("Agent references an unknown memory policy")
            required_grants = {tool.grant_ref for tool in selected_tools}
            if memory is not None:
                required_grants.update(memory.read_grant_refs)
                required_grants.update(memory.write_grant_refs)
            if not required_grants <= set(node.grant_refs):
                raise GraphContractError("Agent bindings exceed its node grant set")

    used_models = {node.config["model_binding_id"] for node in graph.nodes if node.kind == "agent"}
    used_tools = {binding_id for node in graph.nodes if node.kind == "agent"
                  for binding_id in node.config["tool_binding_ids"]}
    used_memories = {node.config["memory_policy_id"] for node in graph.nodes if node.kind == "agent"
                     and node.config["memory_policy_id"] is not None}
    used_grants = {grant for node in graph.nodes for grant in node.grant_refs}
    used_grants.update(tool.grant_ref for tool in graph.tool_bindings)
    for policy in graph.memory_policies:
        used_grants.update(policy.read_grant_refs)
        used_grants.update(policy.write_grant_refs)
    if used_models != set(models):
        raise GraphContractError("Graph contains an unused model binding")
    if used_tools != set(tools):
        raise GraphContractError("Graph contains an unused tool binding")
    if used_memories != set(memories):
        raise GraphContractError("Graph contains an unused memory policy")
    if used_grants != graph_grants:
        raise GraphContractError("Graph contains an unused grant")

    approval_keys = set()
    for edge in graph.edges:
        if edge.kind != "approval":
            continue
        source = nodes[edge.source_node_id]
        target = nodes[edge.target_node_id]
        scope = edge.data["approval_scope"]
        if (source.kind != "human_gate" or scope not in source.config["approval_scopes"]
                or scope not in target.required_approval_scopes):
            raise GraphContractError("approval edge does not match an exact human gate and target scope")
        key = (edge.source_node_id, edge.target_node_id, scope)
        if key in approval_keys:
            raise GraphContractError("Duplicate approval path")
        approval_keys.add(key)
    for node in graph.nodes:
        supplied = [edge.data["approval_scope"] for edge in graph.edges
                    if edge.kind == "approval" and edge.target_node_id == node.node_id]
        if (set(supplied) != set(node.required_approval_scopes)
                or len(supplied) != len(node.required_approval_scopes)):
            raise GraphContractError("required approval scopes lack exact gate paths")

    for node in graph.nodes:
        if node.kind == "router":
            _validate_router(node, graph.edges)

    regions, loop_membership = _loop_regions(graph.nodes, graph.edges)
    incoming_sources = {node_id: set() for node_id in nodes}
    for edge in graph.edges:
        if _triggering(edge):
            incoming_sources[edge.target_node_id].add(edge.source_node_id)
    for entry in graph.entry_node_ids:
        if incoming_sources[entry]:
            raise GraphContractError("Entry nodes cannot have triggering predecessors")
    for node in graph.nodes:
        source_count = len(incoming_sources[node.node_id])
        if source_count > 1 and node.kind != "join":
            if node.kind == "bounded_loop" and node.node_id in loop_membership:
                loop_members = next(
                    set(members) for _loop_id, members, _cap in regions
                    if node.node_id in members
                )
                internal = incoming_sources[node.node_id] & loop_members
                external = incoming_sources[node.node_id] - loop_members
                if len(internal) != 1 or len(external) > 1:
                    raise GraphContractError(
                        "Cycle convergence requires an explicit join or exact loop controller"
                    )
            else:
                raise GraphContractError("Multi-predecessor convergence requires an explicit join")
        if node.kind == "join" and source_count < 2:
            raise GraphContractError("Join requires at least two triggering predecessors")
        if (node.kind == "join" and node.config["mode"] == "collect"
                and (node.config["min_selected"] > source_count
                     or node.config["max_selected"] > source_count)):
            raise GraphContractError("Collect bounds exceed the actual predecessor count")

    reachable = set(graph.entry_node_ids)
    pending = list(graph.entry_node_ids)
    adjacency = {node_id: [] for node_id in nodes}
    for edge in graph.edges:
        if _triggering(edge):
            adjacency[edge.source_node_id].append(edge.target_node_id)
    while pending:
        current = pending.pop()
        for target in adjacency[current]:
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    if reachable != set(nodes):
        raise GraphContractError("Every functional node must be reachable from an entry")

    for criterion in graph.completion_criteria:
        node = nodes.get(criterion.node_id)
        if node is None or node.node_id not in reachable:
            raise GraphContractError("Completion criterion references an unreachable node")
        outputs = {slot.slot_id: slot for slot in node.output_slots}
        output = outputs.get(criterion.output_slot)
        contract = contracts.get(criterion.artifact_contract_id)
        if (output is None or contract is None
                or output.artifact_contract_id != criterion.artifact_contract_id
                or not contract.min_items <= criterion.min_items <= contract.max_items):
            raise GraphContractError("A completion criterion does not match a reachable output")

    return nodes, contracts, incoming_sources, regions


def _validate_external_authority(graph, authority):
    if (type(authority) is not CompilationAuthority
            or authority._issuer_token is not _AUTHORITY_TOKEN):
        raise GraphContractError("Trusted external compilation authority is required")
    trusted_models = dict(authority.model_choices)
    trusted_tools = {item.definition_ref: item for item in authority.tool_definitions}
    trusted_grants = set(authority.grant_refs)
    trusted_approvals = set(authority.approval_scopes)
    trusted_observations = set(authority.observation_contract_refs)
    trusted_budgets = set(authority.budget_policy_refs)
    trusted_schemas = set(authority.artifact_schema_refs)

    if not set(graph.grant_refs) <= trusted_grants:
        raise GraphContractError("Graph references an unauthorized grant")
    for binding in graph.model_bindings:
        capabilities = trusted_models.get(binding.model_choice_ref)
        if capabilities is None:
            raise GraphContractError("Graph references a non-authoritative model choice")
        if not set(binding.capabilities) <= set(capabilities):
            raise GraphContractError("Graph claims a capability absent from the authoritative model")
    for binding in graph.tool_bindings:
        definition = trusted_tools.get(binding.tool_definition_ref)
        if definition is None:
            raise GraphContractError("Graph references a non-authoritative tool definition")
        if binding.grant_ref != definition.required_grant_ref:
            raise GraphContractError("Graph tool binding does not use its authoritative grant")
        if not set(binding.capabilities) <= set(definition.capabilities):
            raise GraphContractError("Graph claims a capability absent from the authoritative tool")
    # the ToolDefinition-backed effect gate: a node bound to a tool whose effect needs an
    # explicit approval must require the tool's approval scope, which the structure already
    # binds to an exact human-gate path
    bindings = {item.binding_id: item for item in graph.tool_bindings}
    for node in graph.nodes:
        for binding_id in _bound_tool_ids(node):
            definition = trusted_tools[bindings[binding_id].tool_definition_ref]
            scope = definition.approval_scope
            if scope is not None and scope not in node.required_approval_scopes:
                raise GraphContractError(
                    "a node bound to an external-family tool must require the tool's approval scope")
    scopes = {
        scope for node in graph.nodes for scope in node.required_approval_scopes
    }
    scopes.update(
        scope for node in graph.nodes if node.kind == "human_gate"
        for scope in node.config["approval_scopes"]
    )
    scopes.update(
        edge.data["approval_scope"] for edge in graph.edges if edge.kind == "approval"
    )
    if not scopes <= trusted_approvals:
        raise GraphContractError("Graph references a non-authoritative approval scope")
    if graph.observation_contract_ref not in trusted_observations:
        raise GraphContractError("Graph references a non-authoritative observation contract")
    if graph.budget_policy_ref not in trusted_budgets:
        raise GraphContractError("Graph references a non-authoritative budget policy")
    schemas = {item.schema_ref for item in graph.artifact_contracts if item.schema_ref is not None}
    if not schemas <= trusted_schemas:
        raise GraphContractError("Graph references a non-authoritative artifact schema")


def compile_graph(graph, authority=None):
    graph = _normalized_graph(graph)
    _nodes, _contracts, incoming_sources, regions = _validate_structure(graph)
    _validate_external_authority(graph, authority)

    compiled_nodes = tuple(CompiledNode(node.node_id, node.kind, node.responsibility)
                           for node in sorted(graph.nodes, key=lambda item: item.node_id))
    predecessors = tuple((node_id, tuple(sorted(sources)))
                         for node_id, sources in sorted(incoming_sources.items()))
    digest = sha256(canonical_json(graph.as_dict())).hexdigest()
    return CompiledGraph(digest, tuple(sorted(graph.entry_node_ids)), compiled_nodes,
                         tuple((node.node_id, HANDLER_KEYS[node.kind]) for node in compiled_nodes),
                         predecessors, regions, graph, authority.digest,
                         _tool_effects(graph, authority), _tool_bindings(graph, authority, digest),
                         authority)


def resolve_compiled_tool_binding(compiled, node_id, binding_id):
    """Recheck the projection against the validated graph and caller authority.

    This only proves constructor coherence. A canonical persistent authority
    loader and registered-input lineage are still required for production use.
    """
    if type(compiled) is not CompiledGraph:
        raise GraphContractError("Exact compiled graph required for tool binding")
    if compiled != compile_graph(compiled.execution_graph, compiled.compilation_authority):
        raise GraphContractError("Compiled tool binding disagrees with graph or authority")
    for binding in compiled.tool_bindings:
        if binding.node_id == node_id and binding.binding_id == binding_id:
            return binding
    raise GraphContractError("Compiled graph has no matching node/tool binding")


def _tool_bindings(graph, authority, digest):
    bindings = {item.binding_id: item for item in graph.tool_bindings}
    return tuple(CompiledToolBinding(
        digest, authority.digest, node_id, binding_id,
        bindings[binding_id].tool_definition_ref, bindings[binding_id].grant_ref,
        tool_id, version, effect, gate,
    ) for node_id, binding_id, tool_id, version, effect, gate in _tool_effects(graph, authority))


def _bound_tool_ids(node):
    getter = getattr(node.config, "get", None)
    return tuple(getter("tool_binding_ids", ())) if callable(getter) else ()


def _tool_effects(graph, authority):
    trusted = {item.definition_ref: item for item in authority.tool_definitions}
    bindings = {item.binding_id: item for item in graph.tool_bindings}
    gates = {(edge.target_node_id, edge.data["approval_scope"]): edge.source_node_id
             for edge in graph.edges if edge.kind == "approval"}
    facts = []
    for node in graph.nodes:
        for binding_id in _bound_tool_ids(node):
            definition = trusted[bindings[binding_id].tool_definition_ref]
            scope = definition.approval_scope
            facts.append((node.node_id, binding_id, definition.tool_id, definition.version,
                          definition.effect_class, None if scope is None else gates[(node.node_id, scope)]))
    return tuple(sorted(facts))


def functional_projection(graph):
    """Return the public functional design without generator-lens audit identity."""
    graph = _normalized_graph(graph)
    _validate_structure(graph)
    value = graph.as_dict()
    for field in ("graph_id", "version", "decision_refs"):
        value.pop(field)
    return value


def structural_diversity_projection(graph):
    """Project the five functional comparison axes without candidate names or lens identities.

    Fact identity is erased structurally, never by the arbitrary fact name: aliases are
    ordered by how each fact is actually used across the graph.  Dependency endpoints use a
    one-round neighbourhood refinement so distinct wiring over identically-signatured nodes
    (a sequential chain versus a parallel fan) does not collapse into one shape.
    """
    graph = _normalized_graph(graph)
    _validate_structure(graph)
    contracts = {item.artifact_contract_id: item for item in graph.artifact_contracts}
    models = {item.binding_id: item for item in graph.model_bindings}
    tools = {item.binding_id: item for item in graph.tool_bindings}
    memory_by_id = {item.policy_id: item for item in graph.memory_policies}

    def ref_signature(ref):
        return (ref.kind, ref.sha256)

    def artifact_signature(contract_id):
        contract = contracts[contract_id]
        return {
            "media_types": list(contract.media_types),
            "schema": None if contract.schema_ref is None
            else ref_signature(contract.schema_ref),
            "min_items": contract.min_items,
            "max_items": contract.max_items,
            "max_total_bytes": contract.max_total_bytes,
        }

    def expression_signature(value, alias):
        if value is None:
            return None
        result = {}
        for key, child in value.items():
            if key == "fact":
                result[key] = alias(child)
            elif type(child) is dict:
                result[key] = expression_signature(child, alias)
            elif type(child) is list:
                result[key] = [expression_signature(item, alias) if type(item) is dict else item
                               for item in child]
            else:
                result[key] = child
        return result

    def facts_in(value):
        found = set()
        if value is None:
            return found
        for key, child in value.items():
            if key == "fact":
                found.add(child)
            elif type(child) is dict:
                found |= facts_in(child)
            elif type(child) is list:
                for item in child:
                    if type(item) is dict:
                        found |= facts_in(item)
        return found

    def functional_config(node, alias):
        config = node.as_dict()["config"]
        if node.kind == "agent":
            model = models[config["model_binding_id"]]
            return {
                "required_model_capabilities": config["required_model_capabilities"],
                "model_contract": {
                    "ref": ref_signature(model.model_choice_ref),
                    "capabilities": list(model.capabilities),
                },
            }
        if node.kind == "router":
            return {
                "allowed_values": config["allowed_values"],
                "decision_fact": alias(config["decision_fact"]),
            }
        if node.kind == "bounded_loop":
            return {
                "termination": expression_signature(config["termination"], alias),
                "hard_iteration_cap": config["hard_iteration_cap"],
            }
        if node.kind in {"join", "human_gate"}:
            return {}
        return config

    def node_sig(node, alias):
        signature = {
            "kind": node.kind,
            "responsibility": node.responsibility,
            "inputs": [(artifact_signature(slot.artifact_contract_id),
                        slot.required, slot.multiplicity)
                       for slot in node.input_slots],
            "outputs": [(artifact_signature(slot.artifact_contract_id), slot.multiplicity)
                        for slot in node.output_slots],
            "failure_policy": node.failure_policy,
            "config": functional_config(node, alias),
        }
        return sha256(canonical_json(signature)).hexdigest()

    # 1) Fact-agnostic base signatures: every fact masked to one sentinel.
    def masked(_name):
        return "·fact·"

    base_signature = {node.node_id: node_sig(node, masked) for node in graph.nodes}

    # 2) Order facts by their structural usage rather than their arbitrary names, so a
    #    consistent bijective rename (even one that inverts name sort order) is invariant.
    def marked_expression(value, target):
        return expression_signature(
            value, lambda name: "·self·" if name == target else masked(name),
        )

    usage = {name: [] for name in graph.fact_names}
    for node in graph.nodes:
        config = node.as_dict()["config"]
        if node.kind == "router":
            usage[config["decision_fact"]].append(("router", base_signature[node.node_id]))
        elif node.kind == "bounded_loop":
            for name in facts_in(config["termination"]):
                usage[name].append((
                    "loop", base_signature[node.node_id],
                    canonical_json(marked_expression(config["termination"], name)).decode(),
                ))
    for edge in graph.edges:
        if edge.kind != "control":
            continue
        condition = edge.as_dict()["condition"]
        for name in facts_in(condition):
            usage[name].append((
                "edge",
                base_signature[edge.source_node_id],
                base_signature[edge.target_node_id],
                edge.loop_id is not None,
                canonical_json(marked_expression(condition, name)).decode(),
            ))

    def fact_key(name):
        # The name is only a deterministic tie-break between facts whose entire structural
        # usage is identical; such facts are interchangeable, so the projection is invariant.
        return (sorted(usage[name]), name)

    fact_aliases = {name: f"fact-{index}"
                    for index, name in enumerate(sorted(graph.fact_names, key=fact_key))}

    def aliased(name):
        return fact_aliases[name]

    # 3) Aliased node signatures carry semantic role identity.
    node_signature = {node.node_id: node_sig(node, aliased) for node in graph.nodes}

    # 4) Dependency endpoints use a one-round neighbourhood refinement (topology sensitivity).
    incident = {node.node_id: [] for node in graph.nodes}
    edge_records = []
    for edge in graph.edges:
        if edge.kind == "observation":
            continue
        data = edge.as_dict()
        if edge.kind == "artifact":
            semantics = {
                "artifact": artifact_signature(data["artifact_contract_id"]),
                "mandatory": data["mandatory"],
                "multiplicity": data["multiplicity"],
            }
        elif edge.kind == "control":
            semantics = {"condition": expression_signature(data["condition"], aliased)}
        else:
            semantics = {"approval_scope": data["approval_scope"]}
        in_loop = edge.loop_id is not None
        edge_records.append((edge.kind, edge.source_node_id, edge.target_node_id, in_loop, semantics))
        incident[edge.source_node_id].append(
            ("out", edge.kind, base_signature[edge.target_node_id], in_loop, semantics))
        incident[edge.target_node_id].append(
            ("in", edge.kind, base_signature[edge.source_node_id], in_loop, semantics))

    refined = {
        node_id: sha256(canonical_json([
            node_signature[node_id],
            sorted(entries, key=canonical_json),
        ])).hexdigest()
        for node_id, entries in incident.items()
    }

    dependencies = [
        (kind, refined[src], refined[tgt], in_loop, semantics)
        for kind, src, tgt, in_loop, semantics in edge_records
    ]
    dependencies.sort(key=canonical_json)

    memory_access = []
    permissions = []
    for node in graph.nodes:
        config = node.as_dict()["config"]
        memory_id = config.get("memory_policy_id")
        if memory_id is not None:
            policy = memory_by_id[memory_id]
            memory_access.append((
                node_signature[node.node_id],
                policy.purpose,
                tuple(ref_signature(item) for item in policy.read_grant_refs),
                tuple(ref_signature(item) for item in policy.write_grant_refs),
            ))
        for tool_id in config.get("tool_binding_ids", []):
            tool = tools[tool_id]
            permissions.append((
                node_signature[node.node_id],
                "tool",
                ref_signature(tool.tool_definition_ref),
                ref_signature(tool.grant_ref),
                tuple(tool.capabilities),
            ))
        if node.grant_refs:
            permissions.append((
                node_signature[node.node_id],
                "node-grants",
                tuple(ref_signature(item) for item in node.grant_refs),
            ))
        scopes = node.required_approval_scopes
        if node.kind == "human_gate":
            scopes = tuple(sorted(set(scopes) | set(config["approval_scopes"])))
        if scopes:
            permissions.append((node_signature[node.node_id], "approval", scopes))
    evaluation_placement = []
    for node in graph.nodes:
        config = node.as_dict()["config"]
        if node.kind in {"router", "join", "human_gate", "bounded_loop"} \
                or config.get("handler_id") is not None:
            if node.kind == "router":
                placed = {
                    "allowed_values": config["allowed_values"],
                    "decision_fact": aliased(config["decision_fact"]),
                }
            elif node.kind == "bounded_loop":
                placed = expression_signature(config["termination"], aliased)
            elif node.kind == "join" and config.get("mode") == "any_success":
                # The runtime tie-break is the frozen branch-ID lexical ordering, which is
                # semantic even though branch IDs are erased from the projection: project
                # the predecessor signatures in that frozen order, so an ID swap that
                # changes the tie winner changes the projection while order-preserving
                # renames stay invariant.
                placed = {
                    **config,
                    "tie_break_branch_signatures": [
                        node_signature[source] for source in sorted(
                            edge.source_node_id for edge in graph.edges
                            if edge.target_node_id == node.node_id
                            and edge.kind != "observation"
                        )
                    ],
                }
            else:
                # Other join modes / human_gate / deterministic-handler configs carry no
                # fact names or IDs, and their branch order is not semantic.
                placed = config
            evaluation_placement.append((node_signature[node.node_id], node.kind, placed))
    for criterion in graph.completion_criteria:
        evaluation_placement.append((
            "completion",
            node_signature[criterion.node_id],
            artifact_signature(criterion.artifact_contract_id),
            criterion.min_items,
        ))
    evaluation_placement.sort(key=canonical_json)
    return {
        "role_responsibilities": sorted(node_signature.values()),
        "dependency_shape": dependencies,
        "memory_access": sorted(memory_access),
        "permission_and_approval_placement": sorted(permissions),
        "evaluation_placement": evaluation_placement,
    }
