"""US5 policy compilation of active knowledge (T058, FR-021/032; runtime §8).

Compilation targets are exactly the allowlisted five (node instructions,
retrieval rules, tool restrictions, handoff schemas, graph/gate config) —
unknown targets are refused. The compiler rejects autonomous relaxation of
protected requirement classes (constitutional, safety, authority,
final-human-approval, current-test) while ordinary authorized work-policy
changes with before/after criteria remain valid. Direct H_phi/S_phi inputs
and current-alternative leakage are blocked in refs and in verbatim spans.
Every compiled field carries supporting behavior refs. Compiled policies are
issued values bound to the exact knowledge entry.
"""

import dataclasses

import pytest

from app.runtime.memory import (
    COMPILATION_TARGETS,
    CompiledPolicy,
    MemoryCompilationError,
    compile_knowledge,
)
from app.tests.test_alternatives import ref
from app.tests.test_knowledge import registry_with_entry


def compilation_value(**overrides):
    value = {
        "target": "node_instructions",
        "fields": {
            "instruction": {
                "text": "research 산출물이 비어 있으면 출처 수집을 재실행한다",
                "provenance": [ref("comparison_result", 1004)],
            },
        },
        "removes_requirements": [],
        "before_after_criteria": "재실행 후 출처 수 0건 → 1건 이상",
    }
    value.update(overrides)
    return value


def entry():
    return registry_with_entry().entries[0]


def test_only_allowlisted_targets_compile():
    assert COMPILATION_TARGETS == frozenset({
        "node_instructions", "retrieval_rules", "tool_restrictions",
        "handoff_schemas", "graph_gate_config",
    })
    policy = compile_knowledge(entry(), compilation_value())
    assert type(policy) is CompiledPolicy
    assert policy.target == "node_instructions"
    assert policy.knowledge_id == "k-research-precheck"
    with pytest.raises(MemoryCompilationError):
        compile_knowledge(entry(), compilation_value(target="system_prompt"))
    with pytest.raises(MemoryCompilationError):
        compile_knowledge(entry(), compilation_value(target="vibes"))


def test_protected_requirements_can_never_be_relaxed_autonomously():
    for protected in (
        "constitutional", "safety", "authority",
        "final_human_approval", "current_test",
    ):
        with pytest.raises(MemoryCompilationError):
            compile_knowledge(entry(), compilation_value(
                removes_requirements=[protected],
            ))
    # an ordinary authorized work-policy change stays a valid candidate
    ordinary = compile_knowledge(entry(), compilation_value(
        removes_requirements=["redundant_review"],
    ))
    assert ordinary.removed_requirements == ("redundant_review",)
    with pytest.raises(MemoryCompilationError):
        # ordinary removals still require before/after criteria
        compile_knowledge(entry(), compilation_value(
            removes_requirements=["redundant_review"],
            before_after_criteria="",
        ))


def test_h_phi_and_alternative_leakage_are_blocked():
    for kind in ("hypothesis", "own_alternative", "difference", "selector"):
        value = compilation_value()
        value["fields"]["instruction"]["provenance"] = [ref(kind, 1030)]
        with pytest.raises(MemoryCompilationError):
            compile_knowledge(entry(), value)
    with pytest.raises(MemoryCompilationError):
        compile_knowledge(
            entry(),
            compilation_value(fields={
                "instruction": {
                    "text": "대안 원문을  그대로 재현한다",
                    "provenance": [ref("comparison_result", 1004)],
                },
            }),
            forbidden_spans=["대안 원문을 그대로 재현한다"],
        )


def test_every_compiled_field_carries_behavior_provenance():
    value = compilation_value()
    value["fields"]["instruction"]["provenance"] = []
    with pytest.raises(MemoryCompilationError):
        compile_knowledge(entry(), value)
    with pytest.raises(MemoryCompilationError):
        compile_knowledge(entry(), compilation_value(fields={}))


def test_compilation_requires_an_active_issued_entry():
    with pytest.raises(MemoryCompilationError):
        compile_knowledge(object(), compilation_value())
    from app.services.knowledge import declare_condition_change

    suspended = declare_condition_change(
        registry_with_entry(), "writer-node", "평가기 교체",
    ).entries[0]
    with pytest.raises(MemoryCompilationError):
        # knowledge awaiting revalidation compiles nothing
        compile_knowledge(suspended, compilation_value())
    policy = compile_knowledge(entry(), compilation_value())
    with pytest.raises(TypeError):
        dataclasses.replace(policy, target="tool_restrictions")
