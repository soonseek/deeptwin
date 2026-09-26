"""T038 attempts 5–6: the simulated owner's well-specified work (`design_specified_work`) is a
valid confirmed work over a real saved work and stored original, its decision is accepted,
and the generation prompt carries its explicit conditions and the verifier effect. Attempt 6:
the verifier effect states condition 2 exactly, and the byte-exact store is performable as a
deterministic node bound to the authority's `document_create` tool. Offline."""

import json
from uuid import NAMESPACE_URL, uuid5

from app.services.design import create_generation_request
from app.services.design_live import render_candidate_prompt
from app.tests.design_specified_work import (
    ATTEMPT5_VERIFIER_RESPONSIBILITY,
    AUTHOR,
    COMPLETION_CONDITIONS,
    SOURCE_TEXT,
    VERIFIER_RESPONSIBILITY,
    WORK_TEXT,
    specified_decision,
    specified_work_model,
    specified_work_with_source,
)
from app.tests.test_design_generation import design_authority, proposed_lens
from app.tests.test_runs_api import Executor, owner_app


def test_the_specified_work_is_confirmed_and_reaches_the_generation_prompt(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        revision, sources = specified_work_with_source(subject)
        domain = subject.app.state.domain_store
        target = specified_work_model(domain, revision, sources)
        assert target.state == "confirmed" and target.design_disposition == "multi_agent"
        assert target.blocked_unknown_ids == () and target.work_model.unknowns == ()
        assert list(target.work_model.completion_conditions) == COMPLETION_CONDITIONS
        registry, lens = proposed_lens(target)
        decision = specified_decision(target, registry, lens)
        request = create_generation_request(
            target, [decision], request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:attempt5-offline:{revision.id}")),
            requested_candidate_count=2, compilation_authority=design_authority())
        _system, user = render_candidate_prompt(request)
        payload = json.loads(user)
        assert payload["work_model"]["completion_conditions"] == COMPLETION_CONDITIONS
        assert payload["required_effects"] == [{
            "effect_id": "verifier-responsibility",
            "target": {"kind": "node", "id": "verifier", "field": "responsibility"},
            "expected_value": VERIFIER_RESPONSIBILITY}]
    # labelled as the simulated owner's, and a different scenario from attempts 1-4
    assert WORK_TEXT.startswith("[시험 행위자(가상 소유자)") and "공개: 아니오" in SOURCE_TEXT
    assert "유튜브" not in WORK_TEXT + "".join(COMPLETION_CONDITIONS)


def test_the_attempt6_verifier_effect_states_condition_2_exactly():
    """Attempt 5's effect text was looser than condition 2 (the author's own defect): the
    attempt-6 text carries condition 2's inputs, model separation, report fields and verdict
    rule verbatim, and every clause of conditions 0 and 1."""

    condition = COMPLETION_CONDITIONS[2]
    for clause in ("원본 변경 기록 파일 자체(요약·발췌·작성자의 메모가 아님)와 초안 원문을 둘 다 입력으로 직접 받아",
                   "작성 역할과 다른 model choice",
                   ("빈 줄을 뺀 초안의 모든 줄(제목 줄 포함)마다 {line, cited_ids, verdict: pass|fail, reason}, "
                    "누락된 공개 ID 목록, 노출된 비공개 ID 목록, 전체 verdict(pass|fail)를 가진다. 전체 verdict는 모든 "
                    "줄이 pass이고 두 목록이 비어 있을 때만 pass다.")):
        assert clause in condition and clause in VERIFIER_RESPONSIBILITY, clause
    for clause in ("`- [CL-###] `", "`공개: 예`", "기능명·수치·버전", "`# 2.4.0 릴리스 노트`", "정확히 한 번",
                   "`공개: 아니오` 항목의 ID와 내용"):
        assert clause in VERIFIER_RESPONSIBILITY, clause
    assert "cited_ids" not in ATTEMPT5_VERIFIER_RESPONSIBILITY  # the attempt-5 gap, kept for replay
    assert len(VERIFIER_RESPONSIBILITY.encode("utf-8")) <= 4_096
    # the store is a model-free step with the storage tool, in the conditions the critic reads
    assert "결정적(deterministic) 저장 단계" in COMPLETION_CONDITIONS[4] and "document.create" in COMPLETION_CONDITIONS[4]


def test_a_deterministic_store_with_the_document_tool_is_admitted_and_shown_to_the_critic(tmp_path):
    """The byte-exact store is performable under the design authority: attempt 5's first live
    graph with its model-driven `publisher` replaced by a deterministic node bound to the
    authority's `document_create` tool (and the attempt-6 verifier text) is admitted as a
    candidate, and the critic projection names the node's tool, operations and grant."""

    from pathlib import Path

    from app.services.design_criticism import critic_candidate_projection
    from app.services.design_live import run_candidate_generation

    raw = json.loads((Path(__file__).resolve().parents[2] / "specs/001-autonomous-release/evidence/"
                      "t038-live-arc-2026-09-26/attempt5-01-arc-generation.txt").read_text(encoding="utf-8"))
    graph = raw["candidates"][0]["graph"]
    for node in graph["nodes"]:
        if node["node_id"] == "publisher":
            assert node["kind"] == "agent" and node["config"]["tool_binding_ids"] == ["doc-store"]
            node["kind"] = "deterministic"
            node["config"] = {"handler_id": "byte-exact-store-v1", "tool_binding_ids": ["doc-store"]}
        if node["node_id"] == "verifier":
            node["responsibility"] = VERIFIER_RESPONSIBILITY
    answer = json.dumps({"candidates": [{"graph": graph}]}, ensure_ascii=False)
    with owner_app(tmp_path, Executor()) as subject:
        revision, sources = specified_work_with_source(subject)
        target = specified_work_model(subject.app.state.domain_store, revision, sources)
        registry, lens = proposed_lens(target)
        request = create_generation_request(
            target, [specified_decision(target, registry, lens)],
            request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:attempt6-store:{revision.id}")),
            requested_candidate_count=2, compilation_authority=design_authority())
        system, _user = render_candidate_prompt(request)
        assert "deterministic {handler_id} or {handler_id, tool_binding_ids}" in system
        result = run_candidate_generation(request, model_turn=lambda _system, _user: answer, model_id="offline")
        [candidate] = result.candidates
        store = next(node for node in candidate.graph.nodes if node.node_id == "publisher")
        assert store.kind == "deterministic" and store.config["tool_binding_ids"] == ("doc-store",)
        notes = critic_candidate_projection(candidate)["control"]["notes"]
        assert any(note.startswith("tool:publisher:doc-store:tool_definition:") and ":operations:document.create:"
                   in note for note in notes), notes


def test_a_router_candidate_projects_for_the_critic(tmp_path):
    """Attempt 5's live generation answer (evidence, replayed offline) has routers whose control
    edges carry conditions; the critic projection used to crash on that nested frozen mapping."""

    from pathlib import Path

    from app.services.design_criticism import critic_candidate_projection
    from app.services.design_live import run_candidate_generation

    raw = (Path(__file__).resolve().parents[2] / "specs/001-autonomous-release/evidence/"
           "t038-live-arc-2026-09-26/attempt5-01-arc-generation.txt").read_text(encoding="utf-8")
    with owner_app(tmp_path, Executor()) as subject:
        revision, sources = specified_work_with_source(subject)
        target = specified_work_model(subject.app.state.domain_store, revision, sources)
        registry, lens = proposed_lens(target)
        request = create_generation_request(
            target, [specified_decision(target, registry, lens,
                                        responsibility=ATTEMPT5_VERIFIER_RESPONSIBILITY)],
            request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:attempt5-router:{revision.id}")),
            requested_candidate_count=2, compilation_authority=design_authority())
        result = run_candidate_generation(request, model_turn=lambda _system, _user: raw, model_id="replay")
        assert len(result.candidates) == 2
        for candidate in result.candidates:
            notes = critic_candidate_projection(candidate)["control"]["notes"]
            assert any('"condition":{"fact":"verification_verdict","op":"eq","value":"pass"}' in note
                       for note in notes), notes


_EVIDENCE = "specs/001-autonomous-release/evidence/t038-live-arc-2026-09-26/"


def _saved(name):
    from pathlib import Path

    return (Path(__file__).resolve().parents[2] / _EVIDENCE / name).read_text(encoding="utf-8")


def _request(subject, label):
    revision, sources = specified_work_with_source(subject)
    target = specified_work_model(subject.app.state.domain_store, revision, sources)
    registry, lens = proposed_lens(target)
    return create_generation_request(
        target, [specified_decision(target, registry, lens)],
        request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:{label}:{revision.id}")),
        requested_candidate_count=2, compilation_authority=design_authority())


def test_attempt7_condition_3_names_the_declared_verdict_step():
    """Attempt 7: the simulated owner's condition 3 says how a fail verdict blocks: a declared
    model-free step reads the report's overall verdict, and only what it passes on reaches
    approval and storage. The verifier effect (condition 2) is unchanged."""

    condition = COMPLETION_CONDITIONS[3]
    assert "검증 보고서를 입력으로 직접 받아 그 전체 verdict 필드를 읽는" in condition
    assert "모델을 쓰지 않는 선언된 판정 단계" in condition
    assert "판정 단계를 거치지 않고 승인·저장 단계로 가는 경로는 없다" in condition
    assert "모델 없는 판정 단계" in WORK_TEXT
    assert "attempt 5/6/7" in AUTHOR and "SIMULATED" in AUTHOR


def test_attempt6_saved_answer_still_replays_offline(tmp_path):
    """Attempt 6's live generation answer (evidence) is still admitted unchanged under the
    attempt-7 work: its required effect text did not change."""

    from app.services.design_live import run_candidate_generation

    raw = _saved("attempt6-01-arc-generation.txt")
    with owner_app(tmp_path, Executor()) as subject:
        request = _request(subject, "attempt6-replay")
        [candidate] = run_candidate_generation(request, model_turn=lambda _s, _u: raw,
                                               model_id="replay").candidates
        assert {"verdict-router", "approval-join", "store"} <= {node.node_id for node in candidate.graph.nodes}


def _artifact_edge(edge_id, source, out, target, into, contract, multiplicity="one"):
    return {"edge_id": edge_id, "kind": "artifact", "source_node_id": source, "target_node_id": target,
            "loop_id": None, "source_output_slot": out, "target_input_slot": into,
            "artifact_contract_id": contract, "mandatory": True, "multiplicity": multiplicity}


def test_a_declared_verdict_step_in_the_data_path_is_admitted_and_shown_to_the_critic(tmp_path):
    """Rules (i)-(j) are realizable under the design authority: attempt 6's live graph with its
    router, halt and unconditional approval join replaced by a join of the checked bundle and
    the report, then a deterministic verdict step (fail_run) that alone feeds the gate, is
    admitted; no artifact edge crosses from before the verdict step to after it, and the critic
    projection carries the step's rule."""

    from app.services.design_criticism import critic_candidate_projection
    from app.services.design_live import run_candidate_generation

    graph = json.loads(_saved("attempt6-01-arc-generation.txt"))["candidates"][0]["graph"]
    graph["nodes"] = [node for node in graph["nodes"]
                      if node["node_id"] not in {"verdict-router", "halt", "approval-join"}]
    graph["fact_names"] = []
    package = next(item for item in graph["artifact_contracts"]
                   if item["artifact_contract_id"] == "approval-package")
    graph["artifact_contracts"].append({**package, "artifact_contract_id": "verified-approval-package"})
    out = {"slot_id": "package", "artifact_contract_id": "approval-package", "multiplicity": "many"}
    graph["nodes"] += [
        {"node_id": "verdict-join", "kind": "join",
         "responsibility": "Aggregate only: the exact verification input bundle and the verification report.",
         "input_slots": [
             {"slot_id": "bundle", "artifact_contract_id": "verification-input-bundle", "required": True,
              "multiplicity": "many"},
             {"slot_id": "report", "artifact_contract_id": "verification-report", "required": True,
              "multiplicity": "one"}],
         "output_slots": [out], "grant_refs": [], "required_approval_scopes": [],
         "failure_policy": "fail_run", "config": {"mode": "all_selected", "failure_handling": "block"}},
        {"node_id": "verdict-step", "kind": "deterministic",
         "responsibility": ("Model-free verdict step: read the report's overall verdict field; only when it is "
                            "pass emit the package byte for byte as the verified approval package; otherwise "
                            "emit nothing and fail the run."),
         "input_slots": [{**out, "required": True}],
         "output_slots": [{"slot_id": "verified", "artifact_contract_id": "verified-approval-package",
                           "multiplicity": "many"}],
         "grant_refs": [], "required_approval_scopes": [], "failure_policy": "fail_run",
         "config": {"handler_id": "report-verdict-pass-through-v1"}},
    ]
    for node in graph["nodes"]:
        if node["node_id"] == "publish-gate":
            node["input_slots"] = [{"slot_id": "package", "artifact_contract_id": "verified-approval-package",
                                    "required": True, "multiplicity": "many"}]
    graph["edges"] = [edge for edge in graph["edges"]
                      if edge["edge_id"] in {"e1", "e2", "e3", "e4", "e11", "e12"}] + [
        _artifact_edge("v1", "verify-join", "bundle", "verdict-join", "bundle", "verification-input-bundle", "many"),
        _artifact_edge("v2", "verifier", "report", "verdict-join", "report", "verification-report"),
        _artifact_edge("v3", "verdict-join", "package", "verdict-step", "package", "approval-package", "many"),
        _artifact_edge("v4", "verdict-step", "verified", "publish-gate", "package", "verified-approval-package", "many"),
    ]
    answer = json.dumps({"candidates": [{"graph": graph}]}, ensure_ascii=False)
    with owner_app(tmp_path, Executor()) as subject:
        request = _request(subject, "attempt7-verdict-step")
        [candidate] = run_candidate_generation(request, model_turn=lambda _s, _u: answer,
                                               model_id="offline").candidates
        nodes = {node.node_id: node for node in candidate.graph.nodes}
        assert nodes["verdict-step"].kind == "deterministic" and nodes["verdict-step"].failure_policy == "fail_run"
        before = {"intake", "writer", "verify-join", "verifier", "verdict-join"}
        for edge in candidate.graph.edges:
            assert not (edge.source_node_id in before and edge.target_node_id in {"publish-gate", "store"}), edge
        assert "overall verdict field" in json.dumps(critic_candidate_projection(candidate), ensure_ascii=False)
