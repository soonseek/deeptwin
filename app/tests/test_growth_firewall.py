"""US5 growth firewall (T059, G-05, OPS-AC09; growth.md §4, runtime.md §8).

Adversarial cross-purpose tests over the growth chain's firewalls: retrieval
purposes are fenced (tuning material never flows into operation and vice
versa); forbidden source spans cannot evade the copy check through zero-width
characters or Unicode compatibility variants in either policy compiler;
judge/heldout internals (evaluation datasets, rubrics) never become policy or
knowledge provenance; peeking at sealed data burns it for every future unseen
claim regardless of the path taken; and no path mints a sensitive personal
profile — diagnosis only competes the five behavior families and the
knowledge registry only carries the closed purpose set.
"""

import pytest

from app.runtime.compiler import ChangeCompilerError, compile_change_candidate
from app.runtime.memory import MemoryCompilationError, compile_knowledge
from app.services.diagnosis import DiagnosisError, propose_hypotheses
from app.services.knowledge import KnowledgeError, register_knowledge
from app.services.validation import (
    GrowthValidationError,
    expose_dataset,
    register_dataset,
    run_validation,
)
from app.tests.test_alternatives import ref
from app.tests.test_change_compiler import patch_value, supported_inquiry
from app.tests.test_knowledge import entry_value, registry_with_entry
from app.tests.test_memory_compilation import compilation_value, entry
from app.tests.test_validation import (
    candidate_value,
    ledger_with_sealed,
    report_value,
)


def test_cross_purpose_retrieval_is_fenced():
    from app.services.knowledge import open_knowledge_registry, retrieve_active

    registry = register_knowledge(
        open_knowledge_registry(),
        entry_value(purposes=["tuning"]),
    )
    operation = retrieve_active(registry, {
        "scope": "writer-node", "purpose": "operation",
        "at": "2026-09-13T05:00:00.000000Z",
    })
    assert operation.entries == ()
    assert operation.gaps == (("k-research-precheck", "purpose_mismatch"),)
    tuning = retrieve_active(registry, {
        "scope": "writer-node", "purpose": "tuning",
        "at": "2026-09-13T05:00:00.000000Z",
    })
    assert len(tuning.entries) == 1


@pytest.mark.parametrize("evasion", [
    "대안\u200b 원문을 그대로 재현한다",      # zero-width space
    "대안⁠ 원문을 그대로 재현한다",      # word joiner
    "대안 원문을 그대로 재현한다﻿",      # BOM tail
])
def test_zero_width_evasion_never_defeats_the_span_check(evasion):
    span = ["대안 원문을 그대로 재현한다"]
    _accepted, inquiry = supported_inquiry()
    value = patch_value()
    value["action"] = {
        "text": evasion, "evidence_refs": value["action"]["evidence_refs"],
    }
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, value, forbidden_spans=span)
    compilation = compilation_value(fields={
        "instruction": {
            "text": evasion,
            "provenance": [ref("comparison_result", 1004)],
        },
    })
    with pytest.raises(MemoryCompilationError):
        compile_knowledge(entry(), compilation, forbidden_spans=span)


def test_compatibility_variants_never_defeat_the_span_check():
    # Fullwidth compatibility characters normalize to the forbidden ASCII.
    span = ["research artifact copy"]
    compilation = compilation_value(fields={
        "instruction": {
            "text": "ｒｅｓｅａｒｃｈ　ａｒｔｉｆａｃｔ　ｃｏｐｙ",
            "provenance": [ref("comparison_result", 1004)],
        },
    })
    with pytest.raises(MemoryCompilationError):
        compile_knowledge(entry(), compilation, forbidden_spans=span)


def test_judge_internals_never_become_policy_provenance():
    for kind in ("evaluation_dataset", "rubric"):
        compilation = compilation_value()
        compilation["fields"]["instruction"]["provenance"] = [ref(kind, 1040)]
        with pytest.raises(MemoryCompilationError):
            compile_knowledge(entry(), compilation)
        with pytest.raises(KnowledgeError):
            register_knowledge(
                registry_with_entry(),
                entry_value(
                    knowledge_id="k-leak", scope="other-node",
                    provenance=[ref(kind, 1040)],
                ),
            )


def test_any_peek_at_sealed_data_burns_every_future_unseen_claim():
    from app.services.validation import freeze_candidate

    candidate = freeze_candidate(candidate_value())
    for peek in ("tuning", "candidate_authoring", "report_review"):
        ledger = expose_dataset(ledger_with_sealed(), "sealed-a", peek)
        with pytest.raises(GrowthValidationError):
            run_validation(candidate, ledger, report_value())
        with pytest.raises(GrowthValidationError):
            # nor does the burned manifest re-enter under a fresh name
            register_dataset(ledger, {
                "dataset_id": "sealed-reborn",
                "classification": "sealed_validation",
                "manifest": ref("run_manifest", 950),
            })


def test_no_path_mints_a_personal_profile():
    for family in (
        "user_philosophy_profile", "personality", "political_alignment",
        "moral_grade",
    ):
        with pytest.raises(DiagnosisError):
            propose_hypotheses(_difference(), [{
                "family": family,
                "claim": "사용자의 성향은 이러하다",
                "conditions": ["항상"],
                "predictions": ["없음"],
            }])
    with pytest.raises(KnowledgeError):
        register_knowledge(
            registry_with_entry(),
            entry_value(
                knowledge_id="k-profile", scope="user-model",
                purposes=["profiling"],
            ),
        )


def _difference():
    from app.services.diagnosis import record_difference
    from app.tests.test_diagnosis import alternative, observation

    return record_difference(
        alternative(), [observation()], uncertainties=["원인 미확정"],
    )
