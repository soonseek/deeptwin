"""US5 active knowledge registry (T058, FR-021/032; runtime.md §8).

Active knowledge is canonical structured condition/action/exception text with
behavior provenance, never an ever-growing prompt. Registration requires the
promoted candidate lineage (candidate + approval + compatibility refs) and an
authority scope; the draft stores (alternatives, differences, hypotheses,
inquiries) are never operating memory in any field. Retrieval filters scope,
authority, effective time, lifecycle and purpose, and reports exactly which
refs were supplied and which gaps remain. Conflicting authority in one scope
is never averaged away — a conflicting registration must explicitly supersede
with authority or it is refused. A declared condition change suspends the
affected scope's entries into revalidation_required, which excludes them from
retrieval until revalidated with fresh evidence; past qualification is never
a permanent guarantee. Values are issued, never constructed.
"""

import dataclasses

import pytest

from app.services.knowledge import (
    ActiveKnowledge,
    KnowledgeError,
    KnowledgeRegistry,
    declare_condition_change,
    open_knowledge_registry,
    register_knowledge,
    retire_knowledge,
    retrieve_active,
    revalidate_knowledge,
)
from app.tests.test_alternatives import ref

STAMP = "2026-09-13T04:00:00.000000Z"
LATER = "2026-09-13T05:00:00.000000Z"


def entry_value(**overrides):
    value = {
        "knowledge_id": "k-research-precheck",
        "condition": "research 산출물이 비어 있으면",
        "action": "작성 전에 출처 수집 단계를 다시 실행한다",
        "exception": "사용자가 명시적으로 출처 생략을 지시한 경우",
        "scope": "writer-node",
        "purposes": ["operation"],
        "candidate": ref("change_candidate", 1001),
        "approval": ref("action_approval", 1002),
        "compatibility": ref("validation_report", 1003),
        "provenance": [ref("comparison_result", 1004)],
        "effective_from": STAMP,
        "supersedes": None,
    }
    value.update(overrides)
    return value


def registry_with_entry(**overrides):
    registry = open_knowledge_registry()
    return register_knowledge(registry, entry_value(**overrides))


def query(**overrides):
    value = {
        "scope": "writer-node",
        "purpose": "operation",
        "at": LATER,
    }
    value.update(overrides)
    return value


def test_registration_requires_the_promoted_lineage_and_issues_a_value():
    registry = registry_with_entry()
    assert type(registry) is KnowledgeRegistry
    entry = registry.entries[0]
    assert type(entry) is ActiveKnowledge
    assert entry.lifecycle == "active"
    with pytest.raises(KnowledgeError):
        register_knowledge(registry, entry_value())  # duplicate id
    with pytest.raises(KnowledgeError):
        register_knowledge(
            open_knowledge_registry(),
            entry_value(provenance=[]),  # knowledge without behavior refs
        )
    with pytest.raises(KnowledgeError):
        register_knowledge(
            open_knowledge_registry(),
            entry_value(approval=ref("decision_record", 1002)),
        )


def test_draft_stores_are_never_operating_memory():
    for kind in ("own_alternative", "difference", "hypothesis", "inquiry"):
        with pytest.raises(KnowledgeError):
            register_knowledge(
                open_knowledge_registry(),
                entry_value(provenance=[ref(kind, 1010)]),
            )
    with pytest.raises(KnowledgeError):
        register_knowledge(
            open_knowledge_registry(),
            entry_value(candidate=ref("own_alternative", 1001)),
        )


def test_retrieval_filters_scope_purpose_time_and_reports_gaps():
    registry = registry_with_entry()
    supplied = retrieve_active(registry, query())
    assert [entry.knowledge_id for entry in supplied.entries] == [
        "k-research-precheck",
    ]
    assert supplied.query_scope == "writer-node"
    assert supplied.gaps == ()
    other_scope = retrieve_active(registry, query(scope="critic-node"))
    assert other_scope.entries == ()
    wrong_purpose = retrieve_active(registry, query(purpose="tuning"))
    assert wrong_purpose.entries == ()
    too_early = retrieve_active(registry, query(
        at="2026-09-13T03:00:00.000000Z",  # before effective_from
    ))
    assert too_early.entries == ()
    assert too_early.gaps == (("k-research-precheck", "not_yet_effective"),)


def test_conflicting_authority_is_never_averaged_away():
    registry = registry_with_entry()
    with pytest.raises(KnowledgeError):
        # same scope, contradicting action, no explicit supersession
        register_knowledge(registry, entry_value(
            knowledge_id="k-research-precheck-2",
            action="출처 수집 없이 바로 작성한다",
        ))
    superseding = register_knowledge(registry, entry_value(
        knowledge_id="k-research-precheck-2",
        action="출처 수집 없이 바로 작성한다",
        supersedes="k-research-precheck",
    ))
    supplied = retrieve_active(superseding, query())
    assert [entry.knowledge_id for entry in supplied.entries] == [
        "k-research-precheck-2",
    ]
    old = next(entry for entry in superseding.entries
               if entry.knowledge_id == "k-research-precheck")
    assert old.lifecycle == "superseded"  # preserved, never erased


def test_condition_change_suspends_until_revalidated():
    registry = registry_with_entry()
    suspended = declare_condition_change(
        registry, "writer-node", "제공자 모델 교체",
    )
    entry = suspended.entries[0]
    assert entry.lifecycle == "revalidation_required"
    excluded = retrieve_active(suspended, query())
    assert excluded.entries == ()
    assert excluded.gaps == (
        ("k-research-precheck", "revalidation_required"),
    )
    with pytest.raises(KnowledgeError):
        revalidate_knowledge(suspended, "k-research-precheck", [])
    restored = revalidate_knowledge(
        suspended, "k-research-precheck",
        [ref("validation_report", 1020)],
    )
    assert restored.entries[0].lifecycle == "active"
    assert retrieve_active(restored, query()).entries != ()


def test_retirement_is_explicit_and_preserved():
    registry = registry_with_entry()
    retired = retire_knowledge(registry, "k-research-precheck", "정책 폐기")
    assert retired.entries[0].lifecycle == "retired"
    assert retrieve_active(retired, query()).entries == ()
    with pytest.raises(KnowledgeError):
        retire_knowledge(retired, "k-research-precheck", "이중 폐기")
    with pytest.raises(KnowledgeError):
        retire_knowledge(registry, "k-research-precheck", "")


def test_values_are_issued_never_constructed():
    registry = registry_with_entry()
    entry = registry.entries[0]
    with pytest.raises(TypeError):
        dataclasses.replace(entry, lifecycle="active")
    with pytest.raises(TypeError):
        dataclasses.replace(registry, entries=())
    with pytest.raises(KnowledgeError):
        register_knowledge(object(), entry_value())
    with pytest.raises(KnowledgeError):
        retrieve_active(object(), query())
