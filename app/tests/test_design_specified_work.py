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
                   "빈 줄을 뺀 초안의 모든 줄(제목 줄 포함)마다 {line, cited_ids, verdict: pass|fail, reason}, "
                   "누락된 공개 ID 목록, 노출된 비공개 ID 목록, 전체 verdict(pass|fail)를 가진다. 전체 verdict는 모든 "
                   "줄이 pass이고 두 목록이 비어 있을 때만 pass다."):
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
