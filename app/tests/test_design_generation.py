"""FR-004/005: qualified lens decisions must change real functional graphs."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from app.domain.refs import EntityRef, canonical_json
from app.generation_profiles import DesignGenerationPurpose, design_profile_for
from app.runtime.graph import (
    CompilationAuthority,
    compile_graph,
    structural_diversity_projection,
)
from app.services.design import (
    DesignContractError,
    accept_design_candidates,
    accept_design_decision,
    confirm_work_model,
    create_generation_request,
)
from app.services.lenses import (
    ApplicabilityAssessment,
    CompositionInput,
    LensDecision,
    LensQualification,
    LensRegistry,
    RouteEvidence,
)
from app.tests.test_work_model_confirmation import confirmation, ref, work_model

ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_HASH = "d" * 64


class FixtureEvidenceVerifier:
    def verify_route(self, route):
        return isinstance(route, RouteEvidence)

    def verify_assessment(self, assessment, route):
        return isinstance(assessment, ApplicabilityAssessment)

    def verify_qualification(self, qualification):
        return qualification.qualification_record_hash == QUALIFICATION_HASH

    def verify_composition_input(self, item, decision):
        return isinstance(item, CompositionInput) and isinstance(decision, LensDecision)


def confirmed(*, shape="multi_agent", unknown_status="acknowledged"):
    raw = work_model(shape=shape, unknown_status=unknown_status)
    prepared = confirm_work_model(raw, None)
    return confirm_work_model(raw, confirmation(prepared.work_model_ref.as_dict()))


def proposed_lens(target):
    registry = LensRegistry.from_markdown(
        ROOT / "docs/lenses/definition-candidates.md",
        ROOT / "docs/lenses/composition-contract.md",
        evidence_verifier=FixtureEvidenceVerifier(),
    )
    item = registry.get("L-P032-01")
    route = RouteEvidence.create(
        path="initial_design",
        scope_hash=target.work_model_ref.sha256,
        work_revision_hash=target.work_model.work_revision_ref.sha256,
        purpose_confirmed=True,
        deliverables_confirmed=True,
        completion_confirmed=True,
        observable_conditions=True,
        authorized_source_hashes=tuple(value.sha256 for value in target.work_model.source_refs),
    )
    assessment = ApplicabilityAssessment.create(
        lens_ref=item.ref,
        status="supported",
        evidence_hashes=("e" * 64,),
    )
    qualification = LensQualification.create(
        lens_ref=item.ref,
        path="initial_design",
        scope_hash=target.work_model_ref.sha256,
        status="qualified",
        qualification_record_hash=QUALIFICATION_HASH,
    )
    return registry, registry.decide(item.ref, route, assessment, qualification)


def graph_value(target, decision_ref, *, graph_suffix=201, agent_count=2):
    notes = {
        "artifact_contract_id": "research-notes",
        "media_types": ["application/json"],
        "schema_ref": None,
        "min_items": 1,
        "max_items": 1,
        "max_total_bytes": 1_048_576,
    }
    final = {
        "artifact_contract_id": "final-script",
        "media_types": ["application/pdf", "text/markdown"],
        "schema_ref": None,
        "min_items": 1,
        "max_items": 2,
        "max_total_bytes": 8_388_608,
    }

    def slot(slot_id, contract, *, required=None):
        value = {
            "slot_id": slot_id,
            "artifact_contract_id": contract,
            "multiplicity": "one",
        }
        if required is not None:
            value["required"] = required
        return value

    def agent(node_id, responsibility, inputs, outputs, model, tools, memory, grants):
        return {
            "node_id": node_id,
            "kind": "agent",
            "responsibility": responsibility,
            "input_slots": inputs,
            "output_slots": outputs,
            "grant_refs": grants,
            "required_approval_scopes": [],
            "failure_policy": "block_dependants",
            "config": {
                "model_binding_id": model,
                "required_model_capabilities": ["text"],
                "tool_binding_ids": tools,
                "memory_policy_id": memory,
            },
        }

    browser_grant, document_grant = ref("grant", 211), ref("grant", 212)
    if agent_count:
        nodes = [
            agent(
                "research",
                "공개 출처를 탐색하고 주장별 근거와 반증을 원형 링크로 정리한다.",
                [],
                [slot("notes", "research-notes")],
                "research-model",
                ["browser-read"],
                None,
                [browser_grant],
            )
        ]
        model_bindings = [{
            "binding_id": "research-model",
            "model_choice_ref": ref("model_choice", 213),
            "capabilities": ["text"],
        }]
        tool_bindings = [{
            "binding_id": "browser-read",
            "tool_definition_ref": ref("tool_definition", 214),
            "grant_ref": browser_grant,
            "capabilities": ["browser.read"],
        }]
        memories = []
        grants = [browser_grant]
        entry = "research"
    else:
        nodes = [{
            "node_id": "research",
            "kind": "deterministic",
            "responsibility": "고정된 공개 자료 목록의 무결성을 결정적으로 검사한다.",
            "input_slots": [],
            "output_slots": [slot("notes", "research-notes")],
            "grant_refs": [],
            "required_approval_scopes": [],
            "failure_policy": "block_dependants",
            "config": {"handler_id": "source-integrity-v1"},
        }]
        model_bindings, tool_bindings, memories, grants = [], [], [], []
        entry = "research"

    if agent_count == 2:
        nodes.append(agent(
            "writer",
            "근거 묶음을 받아 첫 30초·썸네일 약속·전체 정보 가치를 연결한 대본과 PDF를 만든다.",
            [slot("evidence", "research-notes", required=True)],
            [slot("script", "final-script")],
            "writer-model",
            ["document-create"],
            "writer-memory",
            [document_grant],
        ))
        model_bindings.append({
            "binding_id": "writer-model",
            "model_choice_ref": ref("model_choice", 215),
            "capabilities": ["text"],
        })
        tool_bindings.append({
            "binding_id": "document-create",
            "tool_definition_ref": ref("tool_definition", 216),
            "grant_ref": document_grant,
            "capabilities": ["document.create", "pdf.create"],
        })
        memories.append({
            "policy_id": "writer-memory",
            "purpose": "work.context",
            "read_grant_refs": [document_grant],
            "write_grant_refs": [],
        })
        grants.append(document_grant)
        producer = "writer"
    else:
        producer = "research"
        nodes[0]["output_slots"] = [slot("script", "final-script")]

    nodes.extend([
        {
            "node_id": "owner-gate",
            "kind": "human_gate",
            "responsibility": "사용자가 전체 원형 산출물을 보고 외부 공개 여부를 판단한다.",
            "input_slots": [slot("candidate", "final-script", required=True)],
            "output_slots": [slot("approved", "final-script")],
            "grant_refs": [],
            "required_approval_scopes": [],
            "failure_policy": "block_dependants",
            "config": {"approval_scopes": ["artifact.publish"]},
        },
        {
            "node_id": "finalize",
            "kind": "deterministic",
            "responsibility": "승인된 대본과 PDF 버전을 변경 불가능하게 고정한다.",
            "input_slots": [slot("approved", "final-script", required=True)],
            "output_slots": [slot("result", "final-script")],
            "grant_refs": [],
            "required_approval_scopes": ["artifact.publish"],
            "failure_policy": "block_dependants",
            "config": {"handler_id": "artifact-finalizer-v1"},
        },
    ])

    def artifact(edge_id, source, source_slot, target_node, target_slot, contract):
        return {
            "edge_id": edge_id,
            "kind": "artifact",
            "source_node_id": source,
            "target_node_id": target_node,
            "loop_id": None,
            "source_output_slot": source_slot,
            "target_input_slot": target_slot,
            "artifact_contract_id": contract,
            "mandatory": True,
            "multiplicity": "one",
        }

    edges = []
    if agent_count == 2:
        edges.append(artifact("e-research-write", "research", "notes", "writer", "evidence", "research-notes"))
    edges.extend([
        artifact("e-candidate", producer, "script", "owner-gate", "candidate", "final-script"),
        artifact("e-approved", "owner-gate", "approved", "finalize", "approved", "final-script"),
        {
            "edge_id": "e-approval",
            "kind": "approval",
            "source_node_id": "owner-gate",
            "target_node_id": "finalize",
            "loop_id": None,
            "approval_scope": "artifact.publish",
        },
    ])
    return {
        "schema_version": "graph-version-v1",
        "graph_id": f"00000000-0000-4000-8000-{graph_suffix:012d}",
        "version": 1,
        "work_model_ref": target.work_model_ref.as_dict(),
        "decision_refs": [decision_ref],
        "entry_node_ids": [entry],
        "nodes": nodes,
        "edges": edges,
        "artifact_contracts": [notes, final] if agent_count == 2 else [final],
        "model_bindings": model_bindings,
        "tool_bindings": tool_bindings,
        "memory_policies": memories,
        "grant_refs": grants,
        "fact_names": [],
        "observation_contract_ref": ref("observation_contract", 217),
        "completion_criteria": [{
            "criterion_id": "complete-script",
            "node_id": "finalize",
            "output_slot": "result",
            "artifact_contract_id": "final-script",
            "min_items": 1,
        }],
        "budget_policy_ref": ref("budget_policy", 218),
    }


def value_hash(value):
    return sha256(canonical_json(value)).hexdigest()


def design_authority():
    return CompilationAuthority.from_trusted(
        model_choices=[
            (EntityRef.from_dict(ref("model_choice", 213)), ("text",)),
            (EntityRef.from_dict(ref("model_choice", 215)), ("text",)),
        ],
        tool_definitions=[
            (
                EntityRef.from_dict(ref("tool_definition", 214)),
                EntityRef.from_dict(ref("grant", 211)),
                ("browser.read",),
            ),
            (
                EntityRef.from_dict(ref("tool_definition", 216)),
                EntityRef.from_dict(ref("grant", 212)),
                ("document.create", "pdf.create"),
            ),
        ],
        grant_refs=[
            EntityRef.from_dict(ref("grant", 211)),
            EntityRef.from_dict(ref("grant", 212)),
        ],
        approval_scopes=["artifact.publish"],
        observation_contract_refs=[EntityRef.from_dict(ref("observation_contract", 217))],
        budget_policy_refs=[EntityRef.from_dict(ref("budget_policy", 218))],
        artifact_schema_refs=[],
    )


def design_decision(target, registry, lens, *, responsibility=None):
    responsibility = responsibility or "공개 출처를 탐색하고 주장별 근거와 반증을 원형 링크로 정리한다."
    return accept_design_decision(target, [lens], {
        "decision_id": "00000000-0000-4000-8000-000000000221",
        "version": 1,
        "functional_claims": ["조사 산출물과 작성 산출물의 책임을 분리한다."],
        "proposed_effects": [{
            "effect_id": "research-responsibility",
            "axis": "responsibility",
            "target": {"kind": "node", "id": "research", "field": "responsibility"},
            "expected_value_sha256": value_hash(responsibility),
            "rationale": "근거와 반증을 작성자의 서술 편의와 분리한다.",
            "contributing_lens_refs": [str(lens.lens_ref)],
        }],
        "conflicts": [],
        "abstentions": [],
    }, registry=registry)


def candidate(request, graph, *, suffix=231):
    return {
        "schema_version": "design-candidate-v1",
        "candidate_id": f"00000000-0000-4000-8000-{suffix:012d}",
        "version": 1,
        "generation_request_ref": request.request_ref.as_dict(),
        "parent_candidate_refs": [],
        "generation_call_refs": [ref("decision_record", suffix + 100)],
        "graph": graph,
    }


def prepared(*, shape="multi_agent", unknown_status="acknowledged", agent_count=2):
    target = confirmed(shape=shape, unknown_status=unknown_status)
    registry, lens = proposed_lens(target)
    decision = design_decision(target, registry, lens)
    request = create_generation_request(
        target,
        [decision],
        request_id="00000000-0000-4000-8000-000000000230",
        requested_candidate_count=3,
        compilation_authority=design_authority(),
    )
    graph = graph_value(target, decision.decision_ref.as_dict(), agent_count=agent_count)
    return target, lens, decision, request, graph


def test_real_generated_candidate_binds_work_lens_effect_graph_and_original_formats():
    target, lens, decision, request, graph = prepared()
    accepted = accept_design_candidates(request, [candidate(request, graph)])

    assert len(accepted) == 1
    item = accepted[0]
    assert item.work_model_ref == target.work_model_ref
    assert item.decision_refs == (decision.decision_ref,)
    assert compile_graph(item.graph, request.compilation_authority).graph_digest == \
        item.graph_ref.sha256
    assert set(item.graph.artifact_contracts[-1].media_types) == {
        "application/pdf", "text/markdown"
    }
    assert item.applied_effect_ids == ("research-responsibility",)
    assert str(lens.lens_ref) in item.audit_lens_refs


def test_fixed_three_template_substitution_and_duplicate_functional_graphs_are_rejected():
    _, _, _, request, graph = prepared()
    templated = candidate(request, graph)
    templated["template_id"] = "pipeline-a"
    with pytest.raises(DesignContractError, match="candidate"):
        accept_design_candidates(request, [templated])

    repeated = [candidate(request, deepcopy(graph), suffix=240 + index) for index in range(3)]
    for index, item in enumerate(repeated):
        item["graph"]["graph_id"] = f"00000000-0000-4000-8000-{250 + index:012d}"
        for edge_index, edge in enumerate(item["graph"]["edges"]):
            edge["edge_id"] = f"candidate-{index}-edge-{edge_index}"
        item["graph"]["completion_criteria"][0]["criterion_id"] = \
            f"candidate-{index}-completion"
    with pytest.raises(DesignContractError, match="functionally duplicate"):
        accept_design_candidates(request, repeated)


def test_candidate_cannot_swap_the_confirmed_work_or_lens_decisions():
    _, _, _, request, graph = prepared()
    wrong_work = deepcopy(graph)
    wrong_work["work_model_ref"] = ref("work_model", 299)
    with pytest.raises(DesignContractError, match="work model"):
        accept_design_candidates(request, [candidate(request, wrong_work)])

    wrong_decision = deepcopy(graph)
    wrong_decision["decision_refs"] = [ref("design_decision", 298)]
    with pytest.raises(DesignContractError, match="design decisions"):
        accept_design_candidates(request, [candidate(request, wrong_decision)])


def test_lens_effect_must_be_observable_at_the_declared_graph_target():
    target = confirmed()
    registry, lens = proposed_lens(target)
    decision = design_decision(target, registry, lens, responsibility="다른 책임 문구")
    request = create_generation_request(
        target,
        [decision],
        request_id="00000000-0000-4000-8000-000000000260",
        requested_candidate_count=1,
        compilation_authority=design_authority(),
    )
    graph = graph_value(target, decision.decision_ref.as_dict())
    with pytest.raises(DesignContractError, match="effect"):
        accept_design_candidates(request, [candidate(request, graph)])


def test_blocking_unknown_and_unqualified_or_nonproposed_lens_stop_generation():
    target = confirmed(unknown_status="blocking")
    registry, lens = proposed_lens(target)
    decision = design_decision(target, registry, lens)
    with pytest.raises(DesignContractError, match="blocking unknown"):
        create_generation_request(
            target,
            [decision],
            request_id="00000000-0000-4000-8000-000000000270",
            requested_candidate_count=1,
            compilation_authority=design_authority(),
        )

    normal = confirmed()
    normal_registry, _ = proposed_lens(normal)
    with pytest.raises(DesignContractError, match="lens decision"):
        accept_design_decision(normal, [], {
            "decision_id": "00000000-0000-4000-8000-000000000271",
            "version": 1,
            "functional_claims": ["주장"],
            "proposed_effects": [],
            "conflicts": [],
            "abstentions": [],
        }, registry=normal_registry)


@pytest.mark.parametrize(
    ("shape", "agent_count", "allowed"),
    [
        ("multi_agent", 2, True),
        ("single_agent", 1, True),
        ("single_agent", 2, False),
        ("deterministic", 0, True),
        ("deterministic", 1, False),
        ("human_only", 0, False),
    ],
)
def test_candidate_shape_must_honor_single_and_deterministic_suitability(shape, agent_count, allowed):
    target = confirmed(shape=shape)
    registry, lens = proposed_lens(target)
    responsibility = (
        "고정된 공개 자료 목록의 무결성을 결정적으로 검사한다."
        if agent_count == 0 else
        "공개 출처를 탐색하고 주장별 근거와 반증을 원형 링크로 정리한다."
    )
    decision = design_decision(target, registry, lens, responsibility=responsibility)
    request = create_generation_request(
        target,
        [decision],
        request_id="00000000-0000-4000-8000-000000000280",
        requested_candidate_count=1,
        compilation_authority=design_authority(),
    )
    graph = graph_value(target, decision.decision_ref.as_dict(), agent_count=agent_count)
    operation = lambda: accept_design_candidates(request, [candidate(request, graph)])
    if allowed:
        accepted = operation()
        assert len([node for node in accepted[0].graph.nodes if node.kind == "agent"]) == agent_count
    else:
        with pytest.raises(DesignContractError, match="suitability"):
            operation()


def test_generation_profiles_separate_decision_and_graph_jobs_without_tool_authority():
    decision = design_profile_for(DesignGenerationPurpose.DESIGN_DECISION)
    candidate_profile = design_profile_for(DesignGenerationPurpose.DESIGN_CANDIDATE)
    assert decision.digest != candidate_profile.digest
    assert "fixed three" in candidate_profile.developer_instructions.lower()
    for profile in (decision, candidate_profile):
        assert "Do not use tools" in profile.base_instructions
        assert "untrusted reference data" in profile.developer_instructions


def test_candidate_projection_exposes_real_structural_axes_not_names_or_coordinates():
    _, _, _, request, graph = prepared()
    item = accept_design_candidates(request, [candidate(request, graph)])[0]
    projection = structural_diversity_projection(item.graph)
    assert set(projection) == {
        "role_responsibilities",
        "dependency_shape",
        "memory_access",
        "permission_and_approval_placement",
        "evaluation_placement",
    }


# --- regression: 2026-09-12 graph-compiler adversarial audit (F1-F5) ------------------
# Each test encodes one reproduced audit finding. F1/F2 = false diversity through fact
# names; F3 = a genuinely different topology wrongly merged; F4 = a valid loop wrongly
# rejected; F5 = a forged lens decision admitted.
from app.domain.graph_schema import GraphVersion

_AUDIT_RESP = "고정된 공개 자료 목록의 무결성을 결정적으로 검사한다."


def _det(node_id, handler, responsibility="분기 결과를 결정적으로 기록한다."):
    return {
        "node_id": node_id, "kind": "deterministic", "responsibility": responsibility,
        "input_slots": [], "output_slots": [], "grant_refs": [],
        "required_approval_scopes": [], "failure_policy": "continue_optional",
        "config": {"handler_id": handler},
    }


def _control(edge_id, source, target, condition=None, loop_id=None):
    return {"edge_id": edge_id, "kind": "control", "source_node_id": source,
            "target_node_id": target, "loop_id": loop_id, "condition": condition}


def _eq(fact, value):
    return {"op": "eq", "fact": fact, "value": value}


def _audit_target():
    target = confirmed(shape="deterministic")
    registry, lens = proposed_lens(target)
    decision = design_decision(target, registry, lens, responsibility=_AUDIT_RESP)
    return registry, target, decision.decision_ref.as_dict()


def _proj(graph_dict):
    return structural_diversity_projection(GraphVersion.from_untrusted(graph_dict))


def _router_twin(target, dref, fact, suffix):
    graph = graph_value(target, dref, graph_suffix=suffix, agent_count=0)
    graph["fact_names"] = sorted({fact})
    graph["nodes"].append({
        "node_id": "route", "kind": "router",
        "responsibility": "검증 결과 열거값에 따라 후속 기록 분기를 선택한다.",
        "input_slots": [], "output_slots": [], "grant_refs": [],
        "required_approval_scopes": [], "failure_policy": "fail_run",
        "config": {"decision_fact": fact, "allowed_values": ["left", "right"]},
    })
    graph["nodes"].append(_det("branch-a", "branch-a-v1"))
    graph["nodes"].append(_det("branch-b", "branch-b-v1"))
    graph["edges"].append(_control("e-to-route", "research", "route"))
    graph["edges"].append(_control("e-arm-0", "route", "branch-a", _eq(fact, "left")))
    graph["edges"].append(_control("e-arm-1", "route", "branch-b", _eq(fact, "right")))
    return graph


def _two_fact(target, dref, first, second, suffix):
    graph = graph_value(target, dref, graph_suffix=suffix, agent_count=0)
    graph["fact_names"] = sorted({first, second})
    graph["nodes"].append(_det("branch-a", "branch-a-v1"))
    graph["nodes"].append(_det("branch-b", "branch-b-v1"))
    graph["edges"].append(_control("e-cond-a", "research", "branch-a", _eq(first, "go")))
    graph["edges"].append(_control("e-cond-b", "research", "branch-b", _eq(second, "go")))
    return graph


def _shape(target, dref, chain, suffix):
    graph = graph_value(target, dref, graph_suffix=suffix, agent_count=0)
    for node_id in ("n1", "n2", "n3"):
        graph["nodes"].append(_det(node_id, "same-handler-v1", "동일한 후처리 기록을 남긴다."))
    graph["edges"].append(_control("e-r-n1", "research", "n1"))
    graph["edges"].append(_control("e-x1", "n1", "n2"))
    graph["edges"].append(_control("e-x2", "n2" if chain else "n1", "n3"))
    return graph


def test_projection_is_invariant_under_router_decision_fact_rename():
    # F1: two graphs that differ only in the router's decision-fact name must project
    # identically, so a rename cannot masquerade as genuine diversity.
    _, target, dref = _audit_target()
    assert _proj(_router_twin(target, dref, "alpha", 412)) == \
        _proj(_router_twin(target, dref, "omega", 413))


def test_projection_is_invariant_under_order_inverting_fact_rename():
    # F2: a consistent bijective rename that inverts fact-name sort order must still
    # project identically.
    _, target, dref = _audit_target()
    assert _proj(_two_fact(target, dref, "aa", "bb", 414)) == \
        _proj(_two_fact(target, dref, "zz", "yy", 415))


def test_projection_distinguishes_chain_from_fan_topology():
    # F3: a 3-deep chain and a 1->2 fan over identically-signatured nodes are genuinely
    # different candidates and must not collapse to one shape.
    _, target, dref = _audit_target()
    assert _proj(_shape(target, dref, True, 416)) != _proj(_shape(target, dref, False, 417))


def _loop_graph(target, dref, termination, *, cap=5, facts=("done",), suffix=510):
    graph = graph_value(target, dref, graph_suffix=suffix, agent_count=0)
    graph["fact_names"] = sorted(set(facts))
    graph["nodes"].append({
        "node_id": "loop-ctl", "kind": "bounded_loop",
        "responsibility": "반복 상한과 종료 조건을 통제한다.",
        "input_slots": [], "output_slots": [], "grant_refs": [],
        "required_approval_scopes": [], "failure_policy": "fail_run",
        "config": {"loop_id": "refine", "termination": termination, "hard_iteration_cap": cap},
    })
    graph["nodes"].append(_det("worker", "loop-worker-v1", "반복 본문 작업을 수행한다."))
    graph["nodes"].append(_det("after", "loop-after-v1", "반복 종료 후 기록한다."))
    graph["edges"].append(_control("e-enter", "research", "loop-ctl"))
    graph["edges"].append(_control("e-body", "loop-ctl", "worker", None, "refine"))
    graph["edges"].append(_control("e-back", "worker", "loop-ctl", None, "refine"))
    graph["edges"].append(_control("e-exit", "loop-ctl", "after", deepcopy(termination)))
    return graph


@pytest.mark.parametrize("termination", [
    {"op": "eq", "fact": "done", "value": "yes"},
    {"op": "in", "fact": "done", "values": ["no", "yes"]},
    {"op": "and", "args": [
        {"op": "eq", "fact": "done", "value": "yes"},
        {"op": "exists", "fact": "done"},
    ]},
    {"op": "not", "arg": {"op": "eq", "fact": "done", "value": "no"}},
])
def test_bounded_loop_accepts_every_closed_termination_expression(termination):
    # F4: a byte-identical exit condition and controller termination must compile even
    # when the expression carries a list (in/and/or), not only scalar eq/not.
    _, target, dref = _audit_target()
    graph = _loop_graph(target, dref, termination, suffix=520)
    compile_graph(GraphVersion.from_untrusted(graph), design_authority())


def test_accept_design_decision_rejects_a_forged_lens_decision():
    # F5: a reconstructed LensDecision carrying a fabricated issuer token must not pass,
    # while the registry-issued decision does.
    registry, target, _ = _audit_target()
    genuine = registry.decide(
        registry.get("L-P032-01").ref,
        RouteEvidence.create(
            path="initial_design",
            scope_hash=target.work_model_ref.sha256,
            work_revision_hash=target.work_model.work_revision_ref.sha256,
            purpose_confirmed=True, deliverables_confirmed=True,
            completion_confirmed=True, observable_conditions=True,
            authorized_source_hashes=tuple(v.sha256 for v in target.work_model.source_refs),
        ),
        ApplicabilityAssessment.create(
            lens_ref=registry.get("L-P032-01").ref, status="supported",
            evidence_hashes=("e" * 64,)),
        LensQualification.create(
            lens_ref=registry.get("L-P032-01").ref, path="initial_design",
            scope_hash=target.work_model_ref.sha256, status="qualified",
            qualification_record_hash=QUALIFICATION_HASH),
    )
    # LensDecision is init=False; a forger reconstructs it field-by-field with a fake token.
    forged = object.__new__(LensDecision)
    for name, field_value in {
        "lens_ref": genuine.lens_ref,
        "registry_bundle_id": genuine.registry_bundle_id,
        "path": genuine.path,
        "scope_hash": genuine.scope_hash,
        "alternative_scope": genuine.alternative_scope,
        "qualification_status": "qualified",
        "state": "proposed",
        "reason": genuine.reason,
        "evidence_hashes": genuine.evidence_hashes,
        "_issuer_token": object(),
    }.items():
        object.__setattr__(forged, name, field_value)
    body = {
        "decision_id": "00000000-0000-4000-8000-000000000733",
        "version": 1,
        "functional_claims": ["주장"],
        "proposed_effects": [],
        "conflicts": [],
        "abstentions": [],
    }
    with pytest.raises(DesignContractError, match="not issued by the qualified registry"):
        accept_design_decision(target, [forged], body, registry=registry)
