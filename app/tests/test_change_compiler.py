"""T057 change compiler: typed patches with per-field provenance, no copying.

A change candidate compiles only from a concluded *supported* inquiry. Each
patch field (condition/action/exception) carries its own evidence provenance,
and every provenance ref must be evidence the inquiry actually observed after
its freeze. Patch text may not contain verbatim spans of the alternative or
philosophy material (the copy-absorption shortcut), and no reference to the
unpromoted alternative/interpretation store may appear anywhere in a compiled
candidate. The leak check is mandatory: every compilation is handed the
forbidden material. Growth §4's system-repair path is the second admission: a
`system` hypothesis confirmed over its competitors grounds a `restore` candidate
(only) over its own confirmation basis, without an inquiry. Values are issued,
never constructed.
"""

import dataclasses

import pytest

from app.runtime.compiler import (
    ChangeCandidate,
    ChangeCompilerError,
    compile_change_candidate,
)
from app.services.inquiry import conclude_inquiry, observe_evidence
from app.tests.test_alternatives import ref
from app.tests.test_inquiry import AFTER, opened

PARENT = ref("environment", 901)
COMPATIBILITY = ref("validation_report", 902)
ROLLBACK = ref("backup_manifest", 903)
EVIDENCE = ref("comparison_result", 803)
# the alternative's own wording: the leak check is mandatory on every compilation
LEAK = ["원형 링크를 남긴다"]


def supported_inquiry():
    accepted, inquiry = opened()
    observed = observe_evidence(inquiry, [EVIDENCE], observed_at=AFTER)
    return accepted, conclude_inquiry(observed, "supported")


def patch_value(**overrides):
    value = {
        "kind": "learn",
        "condition": {
            "text": "research 산출물이 비어 있으면",
            "evidence_refs": [EVIDENCE],
        },
        "action": {
            "text": "작성 전에 출처 수집 단계를 다시 실행한다",
            "evidence_refs": [EVIDENCE],
        },
        "exception": {
            "text": "사용자가 명시적으로 출처 생략을 지시한 경우",
            "evidence_refs": [EVIDENCE],
        },
        "change_scope": "writer 노드의 사전 조건 검사",
        "predicted_impact_scope": "writer 산출물 품질; 후속 전달 영향은 별도 관측",
        "parent_environment": PARENT,
        "compatibility": COMPATIBILITY,
        "rollback_bundle": ROLLBACK,
    }
    value.update(overrides)
    return value


def test_a_supported_inquiry_compiles_a_typed_candidate():
    _accepted, inquiry = supported_inquiry()
    candidate = compile_change_candidate(inquiry, patch_value(), forbidden_spans=LEAK)
    assert type(candidate) is ChangeCandidate
    assert candidate.kind == "learn"
    assert candidate.condition.text.startswith("research")
    assert candidate.condition.evidence_refs[0].id == EVIDENCE["id"]
    payload = candidate.as_dict()
    assert payload["kind"] == "learn"
    assert payload["predicted_impact_scope"].endswith("별도 관측")
    assert payload["grounds"] == "supported_inquiry"
    for kind in ("restore", "protect"):
        assert compile_change_candidate(
            inquiry, patch_value(kind=kind), forbidden_spans=LEAK,
        ).kind == kind


def test_only_supported_outcomes_compile():
    _accepted, inquiry = opened()
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, patch_value(), forbidden_spans=LEAK)  # not concluded
    declined = conclude_inquiry(inquiry, "declined")
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(declined, patch_value(), forbidden_spans=LEAK)


def test_field_provenance_must_be_the_inquirys_fresh_evidence():
    _accepted, inquiry = supported_inquiry()
    foreign = patch_value()
    foreign["action"]["evidence_refs"] = [ref("comparison_result", 999)]
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, foreign, forbidden_spans=LEAK)
    empty = patch_value()
    empty["condition"]["evidence_refs"] = []
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, empty, forbidden_spans=LEAK)


def test_verbatim_spans_of_forbidden_material_cannot_be_copied():
    _accepted, inquiry = supported_inquiry()
    leak = patch_value()
    leak["action"]["text"] = "출처마다 원형 링크를 남긴다 — 대안 문서 3절 그대로"
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(
            inquiry, leak,
            forbidden_spans=["원형 링크를 남긴다"],
        )
    normalized = patch_value()
    normalized["action"]["text"] = "출처마다  원형   링크를 남긴다"
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(
            inquiry, normalized,
            forbidden_spans=["원형 링크를 남긴다"],
        )
    clean = compile_change_candidate(
        inquiry, patch_value(), forbidden_spans=["원형 링크를 남긴다"],
    )
    assert type(clean) is ChangeCandidate


def test_unpromoted_store_references_never_enter_a_candidate():
    _accepted, inquiry = supported_inquiry()
    smuggled = patch_value()
    smuggled["condition"]["evidence_refs"] = [
        EVIDENCE,
        {"kind": "own_alternative", "id": "00000000-0000-4000-8000-000000000901",
         "version": 1, "sha256": "a" * 64},
    ]
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, smuggled, forbidden_spans=LEAK)


def test_candidates_are_issued_never_constructed():
    _accepted, inquiry = supported_inquiry()
    candidate = compile_change_candidate(inquiry, patch_value(), forbidden_spans=LEAK)
    with pytest.raises(TypeError):
        dataclasses.replace(candidate, kind="restore")
    with pytest.raises(TypeError):
        ChangeCandidate(
            "learn", candidate.condition, candidate.action, candidate.exception,
            candidate.change_scope, candidate.predicted_impact_scope,
            candidate.parent_environment, candidate.compatibility,
            candidate.rollback_bundle, candidate.inquiry_ref, candidate.grounds,
        )


def test_shapes_are_strict():
    _accepted, inquiry = supported_inquiry()
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(object(), patch_value(), forbidden_spans=LEAK)
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, {"unexpected": True}, forbidden_spans=LEAK)
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, patch_value(kind="upgrade"), forbidden_spans=LEAK)
    bad_parent = patch_value(parent_environment=ref("artifact", 904))
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, bad_parent, forbidden_spans=LEAK)


def test_the_leak_check_is_never_optional():
    _accepted, inquiry = supported_inquiry()
    with pytest.raises(TypeError):
        compile_change_candidate(inquiry, patch_value())  # the material must be handed over
    for missing in ([], None, "원형 링크를 남긴다"):
        with pytest.raises(ChangeCompilerError, match="required"):
            compile_change_candidate(inquiry, patch_value(), forbidden_spans=missing)
    scope_leak = patch_value(change_scope="출처마다 원형 링크를 남긴다")
    with pytest.raises(ChangeCompilerError):
        compile_change_candidate(inquiry, scope_leak, forbidden_spans=LEAK)


# --- growth §4's system-repair path ----------------------------------------------


SYSTEM_BASIS = ref("comparison_result", 811)
OTHER_BASIS = ref("comparison_result", 812)


def system_hypotheses(*, confirm=True):
    from app.services.diagnosis import propose_hypotheses, record_difference
    from app.tests.test_diagnosis import alternative, hypothesis, observation

    difference = record_difference(alternative(), [observation(0)], uncertainties=[])
    proposed = propose_hypotheses(difference, [hypothesis("system"), hypothesis("expert_judgment")])
    examined = proposed.resolve("expert_judgment-1", "refuted", basis_refs=[OTHER_BASIS])
    if not confirm:
        return examined
    return examined.resolve("system-0", "confirmed", basis_refs=[SYSTEM_BASIS])


def restore_value(**overrides):
    value = patch_value(kind="restore")
    for label in ("condition", "action", "exception"):
        value[label]["evidence_refs"] = [SYSTEM_BASIS]
    value.update(overrides)
    return value


def test_a_confirmed_system_hypothesis_grounds_a_restore_without_an_inquiry():
    from app.runtime.compiler import compile_system_restore

    hypotheses = system_hypotheses()
    candidate = compile_system_restore(hypotheses, "system-0", restore_value(), forbidden_spans=LEAK)
    assert candidate.kind == "restore" and candidate.grounds == "confirmed_system_hypothesis"
    assert candidate.inquiry_ref == hypotheses.difference_ref
    assert candidate.action.evidence_refs[0].id == SYSTEM_BASIS["id"]


def test_the_system_path_admits_restore_only_and_only_over_its_basis():
    from app.runtime.compiler import compile_system_restore

    hypotheses = system_hypotheses()
    for kind in ("learn", "protect"):
        with pytest.raises(ChangeCompilerError, match="restore"):
            compile_system_restore(hypotheses, "system-0", restore_value(kind=kind), forbidden_spans=LEAK)
    foreign = restore_value()
    foreign["action"]["evidence_refs"] = [OTHER_BASIS]  # the refuted competitor's evidence
    with pytest.raises(ChangeCompilerError, match="fresh evidence"):
        compile_system_restore(hypotheses, "system-0", foreign, forbidden_spans=LEAK)
    with pytest.raises(ChangeCompilerError, match="confirmed system"):
        compile_system_restore(hypotheses, "expert_judgment-1", restore_value(), forbidden_spans=LEAK)
    with pytest.raises(ChangeCompilerError, match="confirmed system"):
        compile_system_restore(system_hypotheses(confirm=False), "system-0", restore_value(),
                               forbidden_spans=LEAK)
    with pytest.raises(ChangeCompilerError, match="framework-issued"):
        compile_system_restore(object(), "system-0", restore_value(), forbidden_spans=LEAK)
    with pytest.raises(ChangeCompilerError, match="required"):
        compile_system_restore(hypotheses, "system-0", restore_value(), forbidden_spans=[])
    leak = restore_value()
    leak["action"]["text"] = "출처마다 원형 링크를 남긴다"
    with pytest.raises(ChangeCompilerError, match="forbidden"):
        compile_system_restore(hypotheses, "system-0", leak, forbidden_spans=LEAK)
