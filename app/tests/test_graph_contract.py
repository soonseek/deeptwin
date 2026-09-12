"""R01 functional graph contract tests.

These tests deliberately stop before LangGraph scheduling.  They freeze the product-owned
graph vocabulary that the later scheduler must consume without inventing authority or code.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from app.domain.graph_schema import GraphContractError, GraphNode, GraphVersion
from app.domain.refs import EntityRef
from app.runtime.graph import (
    CompilationAuthority,
    compile_graph,
    functional_projection,
    graph_digest,
    structural_diversity_projection,
)

ID = "00000000-0000-4000-8000-000000000001"


def ref(kind, suffix):
    return {
        "kind": kind,
        "id": f"00000000-0000-4000-8000-{suffix:012d}",
        "version": 1,
        "sha256": f"{suffix % 16:x}" * 64,
    }


def input_slot(slot_id, contract_id, *, required=True, multiplicity="one"):
    return {
        "slot_id": slot_id,
        "artifact_contract_id": contract_id,
        "required": required,
        "multiplicity": multiplicity,
    }


def output_slot(slot_id, contract_id, *, multiplicity="one"):
    return {
        "slot_id": slot_id,
        "artifact_contract_id": contract_id,
        "multiplicity": multiplicity,
    }


def node(node_id, kind, responsibility, *, inputs=(), outputs=(), config=None,
         required_approval_scopes=(), failure_policy="block_dependants"):
    defaults = {
        "agent": {
            "model_binding_id": "writer-model",
            "required_model_capabilities": ["text"],
            "tool_binding_ids": ["source-read"],
            "memory_policy_id": "work-memory",
        },
        "deterministic": {"handler_id": "artifact-normalizer-v1"},
        "router": {"decision_fact": "route", "allowed_values": ["accept", "revise"]},
        "join": {"mode": "all_selected", "failure_handling": "block"},
        "human_gate": {"approval_scopes": ["release-output"]},
        "bounded_loop": {
            "loop_id": "revision-loop",
            "termination": {"op": "eq", "fact": "loop_done", "value": True},
            "hard_iteration_cap": 5,
        },
    }
    return {
        "node_id": node_id,
        "kind": kind,
        "responsibility": responsibility,
        "input_slots": list(inputs),
        "output_slots": list(outputs),
        "grant_refs": [ref("grant", 6)] if kind == "agent" else [],
        "required_approval_scopes": list(required_approval_scopes),
        "failure_policy": failure_policy,
        "config": deepcopy(defaults[kind] if config is None else config),
    }


def artifact_edge(edge_id, source, source_slot, target, target_slot, contract_id,
                  *, mandatory=True, multiplicity="one", loop_id=None):
    return {
        "edge_id": edge_id,
        "kind": "artifact",
        "source_node_id": source,
        "target_node_id": target,
        "loop_id": loop_id,
        "source_output_slot": source_slot,
        "target_input_slot": target_slot,
        "artifact_contract_id": contract_id,
        "mandatory": mandatory,
        "multiplicity": multiplicity,
    }


def approval_edge(edge_id, source, target, scope, *, loop_id=None):
    return {
        "edge_id": edge_id,
        "kind": "approval",
        "source_node_id": source,
        "target_node_id": target,
        "loop_id": loop_id,
        "approval_scope": scope,
    }


def control_edge(edge_id, source, target, condition=None, *, loop_id=None):
    return {
        "edge_id": edge_id,
        "kind": "control",
        "source_node_id": source,
        "target_node_id": target,
        "loop_id": loop_id,
        "condition": condition,
    }


def graph_value():
    text = {
        "artifact_contract_id": "text-document",
        "media_types": ["text/markdown"],
        "schema_ref": None,
        "min_items": 1,
        "max_items": 1,
        "max_total_bytes": 1_048_576,
    }
    nodes = [
        node("intake", "deterministic", "원자료를 정규화한다",
             outputs=[output_slot("draft", "text-document")]),
        node("writer", "agent", "전체 초안을 만든다",
             inputs=[input_slot("source", "text-document")],
             outputs=[output_slot("draft", "text-document")]),
        node("owner-gate", "human_gate", "사람이 외부 공개를 승인한다",
             inputs=[input_slot("candidate", "text-document")],
             outputs=[output_slot("approved", "text-document")]),
        node("publish", "deterministic", "승인된 산출물을 고정한다",
             inputs=[input_slot("approved", "text-document")],
             outputs=[output_slot("result", "text-document")],
             required_approval_scopes=["release-output"]),
    ]
    edges = [
        artifact_edge("e1", "intake", "draft", "writer", "source", "text-document"),
        artifact_edge("e2", "writer", "draft", "owner-gate", "candidate", "text-document"),
        artifact_edge("e3", "owner-gate", "approved", "publish", "approved", "text-document"),
        approval_edge("e4", "owner-gate", "publish", "release-output"),
        {
            "edge_id": "e5",
            "kind": "observation",
            "source_node_id": "writer",
            "target_node_id": "publish",
            "loop_id": None,
            "observation_name": "draft-lineage",
        },
    ]
    return {
        "schema_version": "graph-version-v1",
        "graph_id": ID,
        "version": 1,
        "work_model_ref": ref("work_model", 1),
        "decision_refs": [ref("design_decision", 2)],
        "entry_node_ids": ["intake"],
        "nodes": nodes,
        "edges": edges,
        "artifact_contracts": [text],
        "model_bindings": [{
            "binding_id": "writer-model",
            "model_choice_ref": ref("model_choice", 3),
            "capabilities": ["text"],
        }],
        "tool_bindings": [{
            "binding_id": "source-read",
            "tool_definition_ref": ref("tool_definition", 4),
            "grant_ref": ref("grant", 6),
            "capabilities": ["read-source"],
        }],
        "memory_policies": [{
            "policy_id": "work-memory",
            "purpose": "operational",
            "read_grant_refs": [ref("grant", 6)],
            "write_grant_refs": [],
        }],
        "grant_refs": [ref("grant", 6)],
        "fact_names": ["route", "loop_done"],
        "observation_contract_ref": ref("observation_contract", 7),
        "completion_criteria": [{
            "criterion_id": "final-artifact",
            "node_id": "publish",
            "output_slot": "result",
            "artifact_contract_id": "text-document",
            "min_items": 1,
        }],
        "budget_policy_ref": ref("budget_policy", 8),
    }


def parse(value=None):
    return GraphVersion.from_untrusted(graph_value() if value is None else value)


def authority(*, artifact_schema_refs=()):
    return CompilationAuthority.from_trusted(
        model_choices=[(EntityRef.from_dict(ref("model_choice", 3)), ("text",))],
        tool_definitions=[(
            EntityRef.from_dict(ref("tool_definition", 4)),
            EntityRef.from_dict(ref("grant", 6)),
            ("read-source",),
        )],
        grant_refs=[EntityRef.from_dict(ref("grant", 6))],
        approval_scopes=["release-output"],
        observation_contract_refs=[EntityRef.from_dict(ref("observation_contract", 7))],
        budget_policy_refs=[EntityRef.from_dict(ref("budget_policy", 8))],
        artifact_schema_refs=[EntityRef.from_dict(item) for item in artifact_schema_refs],
    )


def compile_value(value=None, *, compilation_authority=None):
    return compile_graph(
        parse(graph_value() if value is None else value),
        compilation_authority or authority(),
    )


def test_valid_graph_roundtrips_to_a_deterministic_compiled_plan():
    graph = parse()
    compiled = compile_graph(graph, authority())
    assert compiled.graph_digest == graph_digest(graph)
    assert compiled.entry_node_ids == ("intake",)
    assert [item.node_id for item in compiled.nodes] == [
        "intake", "owner-gate", "publish", "writer"
    ]
    assert dict(compiled.handler_keys) == {
        "intake": "core.deterministic",
        "owner-gate": "core.human_gate",
        "publish": "core.deterministic",
        "writer": "core.agent",
    }
    assert graph.as_dict() == GraphVersion.from_untrusted(graph.as_dict()).as_dict()
    assert compiled.execution_graph.as_dict() == graph.as_dict()
    assert compiled.authority_digest == authority().digest


def test_graph_and_nested_values_are_immutable_and_detached_from_input():
    raw = graph_value()
    graph = parse(raw)
    raw["nodes"][0]["responsibility"] = "mutated"
    assert graph.nodes[0].responsibility == "원자료를 정규화한다"
    with pytest.raises(FrozenInstanceError):
        graph.version = 2
    with pytest.raises(TypeError):
        graph.nodes[0].config["handler_id"] = "other"


@pytest.mark.parametrize("field", [
    "schema_version", "graph_id", "version", "work_model_ref", "decision_refs",
    "entry_node_ids", "nodes", "edges", "artifact_contracts", "model_bindings",
    "tool_bindings", "memory_policies", "grant_refs", "fact_names",
    "observation_contract_ref", "completion_criteria", "budget_policy_ref",
])
def test_graph_requires_every_exact_top_level_field(field):
    raw = graph_value()
    raw.pop(field)
    with pytest.raises(GraphContractError):
        parse(raw)


def test_unknown_fields_floats_noncanonical_types_and_bounds_fail_closed():
    mutations = []
    extra = graph_value()
    extra["ambient_prompt"] = "do it"
    mutations.append(extra)
    wrong_bool = graph_value()
    wrong_bool["version"] = True
    mutations.append(wrong_bool)
    floating = graph_value()
    floating["artifact_contracts"][0]["max_total_bytes"] = 1.5
    mutations.append(floating)
    huge = graph_value()
    huge["nodes"][0]["responsibility"] = "x" * 4097
    mutations.append(huge)
    duplicate = graph_value()
    duplicate["nodes"].append(deepcopy(duplicate["nodes"][0]))
    mutations.append(duplicate)
    unhashable_edge_kind = graph_value()
    unhashable_edge_kind["edges"][0]["kind"] = []
    mutations.append(unhashable_edge_kind)
    unhashable_multiplicity = graph_value()
    unhashable_multiplicity["nodes"][1]["input_slots"][0]["multiplicity"] = []
    mutations.append(unhashable_multiplicity)
    for raw in mutations:
        with pytest.raises(GraphContractError):
            parse(raw)


def test_missing_endpoint_duplicate_edge_and_self_edge_are_rejected():
    cases = []
    missing = graph_value()
    missing["edges"][0]["target_node_id"] = "absent"
    cases.append(missing)
    duplicate = graph_value()
    duplicate["edges"].append(deepcopy(duplicate["edges"][0]))
    cases.append(duplicate)
    self_edge = graph_value()
    self_edge["edges"][0]["target_node_id"] = "intake"
    cases.append(self_edge)
    for raw in cases:
        with pytest.raises(GraphContractError):
            compile_value(raw)


def test_required_input_needs_a_mandatory_matching_producer():
    missing = graph_value()
    missing["edges"] = [edge for edge in missing["edges"] if edge["edge_id"] != "e1"]
    mismatch = graph_value()
    mismatch["edges"][0]["artifact_contract_id"] = "other"
    optional = graph_value()
    optional["edges"][0]["mandatory"] = False
    for raw in (missing, mismatch, optional):
        with pytest.raises(GraphContractError, match="input|contract|mandatory"):
            compile_value(raw)


def test_artifact_edge_must_match_both_slots_and_multiplicity():
    cases = []
    wrong_source = graph_value()
    wrong_source["edges"][0]["source_output_slot"] = "missing"
    cases.append(wrong_source)
    wrong_target = graph_value()
    wrong_target["edges"][0]["target_input_slot"] = "missing"
    cases.append(wrong_target)
    wrong_count = graph_value()
    wrong_count["edges"][0]["multiplicity"] = "many"
    cases.append(wrong_count)
    for raw in cases:
        with pytest.raises(GraphContractError):
            compile_value(raw)


def test_completion_output_must_exist_match_and_be_reachable():
    missing = graph_value()
    missing["completion_criteria"][0]["output_slot"] = "missing"
    mismatch = graph_value()
    mismatch["completion_criteria"][0]["artifact_contract_id"] = "other"
    unreachable = graph_value()
    unreachable["entry_node_ids"] = ["publish"]
    for raw in (missing, mismatch, unreachable):
        with pytest.raises(GraphContractError):
            compile_value(raw)


def test_human_approval_scope_cannot_be_declared_without_exact_gate_edge():
    absent = graph_value()
    absent["edges"] = [edge for edge in absent["edges"] if edge["kind"] != "approval"]
    wrong_scope = graph_value()
    wrong_scope["edges"][3]["approval_scope"] = "different"
    wrong_source = graph_value()
    wrong_source["edges"][3]["source_node_id"] = "writer"
    for raw in (absent, wrong_scope, wrong_source):
        with pytest.raises(GraphContractError, match="approval"):
            compile_value(raw)


def test_each_required_approval_scope_has_one_unambiguous_gate_path():
    raw = graph_value()
    raw["nodes"].insert(3, node("second-gate", "human_gate", "두 번째 승인 경로"))
    raw["edges"].append(control_edge("e6", "writer", "second-gate"))
    raw["edges"].append(approval_edge("e7", "second-gate", "publish", "release-output"))
    with pytest.raises(GraphContractError, match="approval"):
        compile_value(raw)


def test_approval_edge_cannot_grant_a_scope_the_target_did_not_request():
    raw = graph_value()
    raw["nodes"][3]["required_approval_scopes"] = []
    with pytest.raises(GraphContractError, match="approval"):
        compile_value(raw)


def test_agent_model_tool_memory_and_grants_are_exact_graph_bindings():
    cases = []
    missing_model = graph_value()
    missing_model["nodes"][1]["config"]["model_binding_id"] = "ambient"
    cases.append(missing_model)
    incapable = graph_value()
    incapable["nodes"][1]["config"]["required_model_capabilities"] = ["vision"]
    cases.append(incapable)
    missing_tool = graph_value()
    missing_tool["nodes"][1]["config"]["tool_binding_ids"] = ["shell"]
    cases.append(missing_tool)
    missing_memory = graph_value()
    missing_memory["nodes"][1]["config"]["memory_policy_id"] = "personal-profile"
    cases.append(missing_memory)
    unlisted_grant = graph_value()
    unlisted_grant["grant_refs"] = []
    cases.append(unlisted_grant)
    for raw in cases:
        with pytest.raises(GraphContractError):
            compile_value(raw)


def test_unused_model_tool_memory_or_grant_authority_is_rejected():
    cases = []
    extra_model = graph_value()
    extra_model["model_bindings"].append({
        "binding_id": "unused-model", "model_choice_ref": ref("model_choice", 30),
        "capabilities": ["text"],
    })
    cases.append(extra_model)
    extra_tool = graph_value()
    extra_tool["tool_bindings"].append({
        "binding_id": "unused-tool", "tool_definition_ref": ref("tool_definition", 31),
        "grant_ref": ref("grant", 6), "capabilities": ["read-source"],
    })
    cases.append(extra_tool)
    extra_memory = graph_value()
    extra_memory["memory_policies"].append({
        "policy_id": "unused-memory", "purpose": "operational",
        "read_grant_refs": [ref("grant", 6)], "write_grant_refs": [],
    })
    cases.append(extra_memory)
    extra_grant = graph_value()
    extra_grant["grant_refs"].append(ref("grant", 32))
    cases.append(extra_grant)
    for raw in cases:
        with pytest.raises(GraphContractError, match="unused"):
            compile_value(raw)


def test_kind_specific_config_is_closed_and_never_accepts_executable_source():
    cases = []
    shell = graph_value()
    shell["nodes"][0]["config"] = {"handler_id": "artifact-normalizer-v1", "code": "eval(x)"}
    cases.append(shell)
    arbitrary = graph_value()
    arbitrary["nodes"][0]["config"]["handler_id"] = "../../user.py"
    cases.append(arbitrary)
    wrong_arm = graph_value()
    wrong_arm["nodes"][0]["config"] = deepcopy(wrong_arm["nodes"][1]["config"])
    cases.append(wrong_arm)
    for raw in cases:
        with pytest.raises(GraphContractError):
            parse(raw)


@pytest.mark.parametrize("value", ["ignore", "retry-forever", "", None, True])
def test_every_node_has_a_closed_failure_policy(value):
    raw = graph_value()
    raw["nodes"][1]["failure_policy"] = value
    with pytest.raises(GraphContractError):
        parse(raw)


def router_graph():
    raw = graph_value()
    raw["model_bindings"] = []
    raw["tool_bindings"] = []
    raw["memory_policies"] = []
    raw["grant_refs"] = []
    raw["nodes"] = [
        node("choose", "router", "검증된 상태로 분기한다"),
        node("accept", "deterministic", "승인 경로", outputs=[output_slot("out", "text-document")]),
        node("revise", "deterministic", "수정 경로", outputs=[output_slot("out", "text-document")]),
        node("join", "join", "선택된 경로를 합류한다",
             inputs=[input_slot("items", "text-document", multiplicity="many")],
             outputs=[output_slot("result", "text-document")]),
    ]
    raw["entry_node_ids"] = ["choose"]
    raw["edges"] = [
        control_edge("r1", "choose", "accept", {"op": "eq", "fact": "route", "value": "accept"}),
        control_edge("r2", "choose", "revise", {"op": "eq", "fact": "route", "value": "revise"}),
        artifact_edge("r3", "accept", "out", "join", "items", "text-document",
                      multiplicity="many"),
        artifact_edge("r4", "revise", "out", "join", "items", "text-document",
                      multiplicity="many"),
    ]
    raw["completion_criteria"] = [{
        "criterion_id": "final-artifact", "node_id": "join", "output_slot": "result",
        "artifact_contract_id": "text-document", "min_items": 1,
    }]
    return raw


def test_router_requires_exact_enum_branch_coverage_with_typed_conditions():
    assert compile_value(router_graph()).graph_digest
    missing = router_graph()
    missing["edges"] = [edge for edge in missing["edges"] if edge["edge_id"] != "r2"]
    duplicate = router_graph()
    duplicate["edges"][1]["condition"]["value"] = "accept"
    unknown_fact = router_graph()
    unknown_fact["edges"][0]["condition"]["fact"] = "ambient"
    source = router_graph()
    source["edges"][0]["condition"] = "route == 'accept'"
    executable = router_graph()
    executable["edges"][0]["condition"] = {"op": "eval", "source": "__import__('os')"}
    for raw in (missing, duplicate, unknown_fact, source, executable):
        with pytest.raises(GraphContractError):
            compile_value(raw)


def test_multi_predecessor_convergence_requires_an_explicit_join():
    raw = router_graph()
    raw["nodes"][3]["kind"] = "deterministic"
    raw["nodes"][3]["config"] = {"handler_id": "artifact-normalizer-v1"}
    with pytest.raises(GraphContractError, match="join"):
        compile_value(raw)


def test_join_requires_multiple_predecessors_and_valid_closed_mode():
    one = router_graph()
    one["edges"] = [edge for edge in one["edges"] if edge["edge_id"] not in {"r2", "r4"}]
    bad_mode = router_graph()
    bad_mode["nodes"][3]["config"] = {"mode": "race", "failure_handling": "block"}
    for raw in (one, bad_mode):
        with pytest.raises(GraphContractError):
            compile_value(raw) if raw is one else parse(raw)


def test_join_modes_freeze_any_success_tie_break_and_collect_bounds():
    any_success = router_graph()
    any_success["nodes"][3]["config"] = {
        "mode": "any_success", "failure_handling": "collect_failures",
        "tie_break": "branch_id_lexical",
    }
    collect = router_graph()
    collect["nodes"][3]["config"] = {
        "mode": "collect", "min_selected": 1, "max_selected": 2,
        "failure_handling": "collect_failures",
    }
    assert compile_value(any_success).graph_digest
    assert compile_value(collect).graph_digest

    missing_tie_break = deepcopy(any_success)
    missing_tie_break["nodes"][3]["config"].pop("tie_break")
    wrong_tie_break = deepcopy(any_success)
    wrong_tie_break["nodes"][3]["config"]["tie_break"] = "completion_time"
    invalid_collect = deepcopy(collect)
    invalid_collect["nodes"][3]["config"]["min_selected"] = 3
    for raw in (missing_tie_break, wrong_tie_break, invalid_collect):
        with pytest.raises(GraphContractError):
            parse(raw)


def loop_graph():
    raw = graph_value()
    raw["nodes"] = [
        node("seed", "deterministic", "초기 상태를 만든다"),
        node("revise", "agent", "초안을 다시 쓴다"),
        node("loop", "bounded_loop", "종료 조건과 반복 한도를 판정한다"),
        node("done", "deterministic", "최종 결과를 고정한다",
             outputs=[output_slot("result", "text-document")]),
    ]
    raw["entry_node_ids"] = ["seed"]
    raw["edges"] = [
        control_edge("l1", "seed", "loop"),
        control_edge("l2", "loop", "revise", loop_id="revision-loop"),
        control_edge("l3", "revise", "loop", loop_id="revision-loop"),
        control_edge("l4", "loop", "done", {"op": "eq", "fact": "loop_done", "value": True}),
    ]
    raw["completion_criteria"] = [{
        "criterion_id": "final-artifact", "node_id": "done", "output_slot": "result",
        "artifact_contract_id": "text-document", "min_items": 1,
    }]
    return raw


def test_only_a_declared_single_bounded_loop_can_own_a_cycle():
    assert compile_value(loop_graph()).loop_regions == (("revision-loop", ("loop", "revise"), 5),)
    no_id = loop_graph()
    no_id["edges"][1]["loop_id"] = None
    no_loop_node = loop_graph()
    no_loop_node["nodes"][2]["kind"] = "deterministic"
    no_loop_node["nodes"][2]["config"] = {"handler_id": "artifact-normalizer-v1"}
    two_loops = loop_graph()
    two_loops["nodes"].append(node("loop2", "bounded_loop", "두 번째 반복 제어"))
    two_loops["edges"].append(control_edge("l5", "revise", "loop2", loop_id="revision-loop"))
    for raw in (no_id, no_loop_node, two_loops):
        with pytest.raises(GraphContractError, match="loop|cycle"):
            compile_value(raw)


def test_bounded_loop_termination_expression_must_control_an_exit():
    missing_exit = loop_graph()
    missing_exit["edges"][3]["condition"] = None
    different_exit = loop_graph()
    different_exit["edges"][3]["condition"] = {
        "op": "neq", "fact": "loop_done", "value": True,
    }
    for raw in (missing_exit, different_exit):
        with pytest.raises(GraphContractError, match="termination"):
            compile_value(raw)


@pytest.mark.parametrize("cap", [0, -1, True, 101])
def test_loop_hard_cap_is_a_strict_finite_product_limit(cap):
    raw = loop_graph()
    raw["nodes"][2]["config"]["hard_iteration_cap"] = cap
    with pytest.raises(GraphContractError):
        parse(raw)


def test_observation_edges_never_create_execution_reachability_or_cycles():
    raw = graph_value()
    raw["nodes"].append(node("hidden", "deterministic", "관찰만 되는 노드"))
    raw["edges"].append({
        "edge_id": "observe-hidden", "kind": "observation", "source_node_id": "writer",
        "target_node_id": "hidden", "loop_id": None, "observation_name": "hidden-status",
    })
    with pytest.raises(GraphContractError, match="reachable"):
        compile_value(raw)


def test_public_functional_projection_omits_generation_lens_identity_and_self_scores():
    raw = graph_value()
    first = parse(raw)
    raw["decision_refs"] = [ref("design_decision", 99)]
    second = parse(raw)
    assert graph_digest(first) != graph_digest(second)
    assert functional_projection(first) == functional_projection(second)
    projection_text = repr(functional_projection(first))
    assert "decision_refs" not in projection_text
    assert "lens" not in projection_text
    assert "self_score" not in projection_text


def test_structural_projection_changes_on_real_axes_not_graph_names_or_decision_refs():
    first_raw = graph_value()
    second_raw = graph_value()
    second_raw["graph_id"] = "00000000-0000-4000-8000-000000000099"
    second_raw["version"] = 2
    second_raw["decision_refs"] = [ref("design_decision", 99)]
    assert structural_diversity_projection(parse(first_raw)) == structural_diversity_projection(parse(second_raw))

    changed = graph_value()
    changed["nodes"][1]["responsibility"] = "초안과 팩트 검증을 함께 수행한다"
    assert structural_diversity_projection(parse(first_raw)) != structural_diversity_projection(parse(changed))


def test_graph_digest_is_order_independent_for_set_like_collections():
    first = graph_value()
    second = graph_value()
    second["nodes"].reverse()
    second["edges"].reverse()
    second["decision_refs"].reverse()
    second["fact_names"].reverse()
    assert graph_digest(parse(first)) == graph_digest(parse(second))


def test_compiler_requires_external_authority_and_rejects_graph_self_claims():
    graph = parse()
    with pytest.raises(GraphContractError, match="authority"):
        compile_graph(graph)

    capability = graph_value()
    capability["model_bindings"][0]["capabilities"] = ["ambient.superpower"]
    capability["nodes"][1]["config"]["required_model_capabilities"] = [
        "ambient.superpower"
    ]
    with pytest.raises(GraphContractError, match="authoritative model"):
        compile_value(capability)

    tool = graph_value()
    tool["tool_bindings"][0]["tool_definition_ref"] = ref("tool_definition", 44)
    with pytest.raises(GraphContractError, match="authoritative tool"):
        compile_value(tool)

    grant = graph_value()
    replacement = ref("grant", 45)
    grant["grant_refs"] = [replacement]
    grant["nodes"][1]["grant_refs"] = [replacement]
    grant["tool_bindings"][0]["grant_ref"] = replacement
    grant["memory_policies"][0]["read_grant_refs"] = [replacement]
    with pytest.raises(GraphContractError, match="authorized grant"):
        compile_value(grant)


def test_compiled_graph_preserves_typed_execution_contract_not_only_an_opaque_digest():
    baseline = compile_value()
    pdf = graph_value()
    pdf["artifact_contracts"][0]["media_types"] = ["application/pdf"]
    changed = compile_value(pdf)

    assert baseline.execution_graph.artifact_contracts[0].media_types == ("text/markdown",)
    assert changed.execution_graph.artifact_contracts[0].media_types == ("application/pdf",)
    assert baseline.execution_graph.edges == parse().edges
    assert baseline.execution_graph.completion_criteria == parse().completion_criteria
    assert baseline.graph_digest != changed.graph_digest


def test_router_cannot_activate_a_target_outside_its_exact_enum_control_arms():
    raw = router_graph()
    raw["nodes"][0]["output_slots"] = [output_slot("leak", "text-document")]
    raw["nodes"].append(node(
        "side-path",
        "deterministic",
        "열거되지 않은 분기",
        inputs=[input_slot("input", "text-document")],
    ))
    raw["edges"].append(artifact_edge(
        "r5", "choose", "leak", "side-path", "input", "text-document"
    ))
    with pytest.raises(GraphContractError, match="Router"):
        compile_value(raw)


def _rename_artifact_contract(raw, old, new):
    raw = deepcopy(raw)
    for contract in raw["artifact_contracts"]:
        if contract["artifact_contract_id"] == old:
            contract["artifact_contract_id"] = new
    for node_value in raw["nodes"]:
        for slot_value in [*node_value["input_slots"], *node_value["output_slots"]]:
            if slot_value["artifact_contract_id"] == old:
                slot_value["artifact_contract_id"] = new
    for edge in raw["edges"]:
        if edge["kind"] == "artifact" and edge["artifact_contract_id"] == old:
            edge["artifact_contract_id"] = new
    for criterion in raw["completion_criteria"]:
        if criterion["artifact_contract_id"] == old:
            criterion["artifact_contract_id"] = new
    return raw


def test_structural_projection_is_semantic_id_invariant_and_condition_format_sensitive():
    baseline = graph_value()
    renamed = _rename_artifact_contract(baseline, "text-document", "renamed-document")
    assert structural_diversity_projection(parse(baseline)) == \
        structural_diversity_projection(parse(renamed))

    mime_changed = deepcopy(baseline)
    mime_changed["artifact_contracts"][0]["media_types"] = ["application/pdf"]
    assert structural_diversity_projection(parse(baseline)) != \
        structural_diversity_projection(parse(mime_changed))

    routed = router_graph()
    swapped = deepcopy(routed)
    swapped["edges"][0]["condition"]["value"] = "revise"
    swapped["edges"][1]["condition"]["value"] = "accept"
    assert structural_diversity_projection(parse(routed)) != \
        structural_diversity_projection(parse(swapped))

    grant_changed = deepcopy(baseline)
    replacement = ref("grant", 46)
    grant_changed["grant_refs"] = [replacement]
    grant_changed["nodes"][1]["grant_refs"] = [replacement]
    grant_changed["tool_bindings"][0]["grant_ref"] = replacement
    grant_changed["memory_policies"][0]["read_grant_refs"] = [replacement]
    assert structural_diversity_projection(parse(baseline)) != \
        structural_diversity_projection(parse(grant_changed))


def test_loop_has_one_exact_exit_and_loop_ids_are_unique_across_regions():
    extra_exit = loop_graph()
    extra_exit["nodes"].append(node("also-done", "deterministic", "두 번째 종료"))
    extra_exit["edges"].append(control_edge("l5", "loop", "also-done"))
    with pytest.raises(GraphContractError, match="exit|termination"):
        compile_value(extra_exit)

    duplicate_region = loop_graph()
    duplicate_region["nodes"].extend([
        node("seed-two", "deterministic", "둘째 초기 상태"),
        node("revise-two", "deterministic", "둘째 수정"),
        node("loop-two", "bounded_loop", "둘째 반복 제어"),
        node("done-two", "deterministic", "둘째 종료"),
    ])
    duplicate_region["entry_node_ids"].append("seed-two")
    duplicate_region["edges"].extend([
        control_edge("l5", "seed-two", "loop-two"),
        control_edge("l6", "loop-two", "revise-two", loop_id="revision-loop"),
        control_edge("l7", "revise-two", "loop-two", loop_id="revision-loop"),
        control_edge(
            "l8", "loop-two", "done-two",
            {"op": "eq", "fact": "loop_done", "value": True},
        ),
    ])
    with pytest.raises(GraphContractError, match="loop ID"):
        compile_value(duplicate_region)


def test_cycle_convergence_and_collect_bounds_match_actual_predecessors():
    raw = loop_graph()
    raw["nodes"].append(node("review", "deterministic", "반복 산출물을 검토한다"))
    raw["edges"].extend([
        control_edge("l5", "revise", "review", loop_id="revision-loop"),
        control_edge("l6", "loop", "review", loop_id="revision-loop"),
        control_edge("l7", "review", "loop", loop_id="revision-loop"),
    ])
    with pytest.raises(GraphContractError, match="join"):
        compile_value(raw)

    collect = router_graph()
    collect["nodes"][3]["config"] = {
        "mode": "collect",
        "min_selected": 3,
        "max_selected": 3,
        "failure_handling": "collect_failures",
    }
    with pytest.raises(GraphContractError, match="predecessor"):
        compile_value(collect)


def test_required_and_completion_cardinality_respect_artifact_contract_minimum():
    required_zero = graph_value()
    required_zero["artifact_contracts"][0]["min_items"] = 0
    with pytest.raises(GraphContractError, match="required"):
        compile_value(required_zero)

    incomplete = graph_value()
    incomplete["artifact_contracts"][0]["min_items"] = 2
    incomplete["artifact_contracts"][0]["max_items"] = 2
    incomplete["completion_criteria"][0]["min_items"] = 1
    for node_value in incomplete["nodes"]:
        for slot_value in [*node_value["input_slots"], *node_value["output_slots"]]:
            slot_value["multiplicity"] = "many"
    for edge in incomplete["edges"]:
        if edge["kind"] == "artifact":
            edge["multiplicity"] = "many"
    with pytest.raises(GraphContractError, match="completion"):
        compile_value(incomplete)


def test_schema_rejects_a_combined_graph_larger_than_the_canonical_record_limit():
    raw = graph_value()
    for index in range(4, 256):
        raw["nodes"].append(node(
            f"bulk-{index}",
            "deterministic",
            "x" * 4_096,
        ))
    with pytest.raises(GraphContractError, match="canonical|limit|size"):
        parse(raw)


def test_direct_dataclass_mutability_and_unexpected_as_dict_fail_at_the_boundary():
    valid = parse()
    first = valid.nodes[0]
    with pytest.raises(GraphContractError, match="immutable"):
        GraphNode(
            first.node_id,
            first.kind,
            first.responsibility,
            first.input_slots,
            first.output_slots,
            first.grant_refs,
            first.required_approval_scopes,
            first.failure_policy,
            {"handler_id": "artifact-normalizer-v1"},
        )

    class ExplodingRef:
        def as_dict(self):
            raise RuntimeError("untrusted exception")

    forged = replace(valid, work_model_ref=ExplodingRef())
    with pytest.raises(GraphContractError, match="directly constructed"):
        graph_digest(forged)


def test_audit_only_atomic_lens_identifiers_cannot_enter_public_graph_text():
    raw = graph_value()
    raw["nodes"][1]["responsibility"] = "Apply L-P032-01 to the draft"
    with pytest.raises(GraphContractError, match="audit-only"):
        parse(raw)


def test_multiformat_and_schema_bound_artifacts_survive_compile():
    raw = graph_value()
    schema_ref = ref("task_spec", 47)
    raw["artifact_contracts"][0]["media_types"] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/png",
        "text/csv",
    ]
    raw["artifact_contracts"][0]["schema_ref"] = schema_ref
    compiled = compile_value(raw, compilation_authority=authority(
        artifact_schema_refs=[schema_ref]
    ))
    contract = compiled.execution_graph.artifact_contracts[0]
    assert contract.schema_ref == EntityRef.from_dict(schema_ref)
    assert contract.media_types == (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/png",
        "text/csv",
    )
