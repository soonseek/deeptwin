"""FR-003: an exact common-work target precedes any design generation."""

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from app.services.design import WorkModelContractError, confirm_work_model


def ref(kind, suffix):
    return {
        "kind": kind,
        "id": f"00000000-0000-4000-8000-{suffix:012d}",
        "version": 1,
        "sha256": f"{suffix % 16:x}" * 64,
    }


def work_model(*, shape="multi_agent", unknown_status="acknowledged"):
    return {
        "schema_version": "work-model-v1",
        "work_model_id": "00000000-0000-4000-8000-000000000101",
        "version": 1,
        "work_revision_ref": ref("work_revision", 102),
        "semantic_origin": "work_understanding",
        "goals": ["근거가 확인된 유튜브 기획과 완성 대본을 만든다."],
        "deliverables": [
            {
                "deliverable_id": "script",
                "description": "출처와 편집 자료가 연결된 완성 대본",
                "media_types": ["application/pdf", "text/markdown"],
                "min_items": 1,
                "max_items": 2,
                "max_total_bytes": 8_388_608,
            }
        ],
        "completion_conditions": [
            "사실 검증 근거와 대본의 인용 위치가 연결되어 있다.",
            "첫 30초와 썸네일 약속이 같은 시청 동기를 전달한다.",
        ],
        "authorities": [
            {
                "authority_id": "web-research",
                "capability": "browser.read",
                "scope": "사용자가 허용한 공개 웹 출처",
                "effect": "read",
            },
            {
                "authority_id": "publish-approval",
                "capability": "artifact.publish",
                "scope": "최종 대본 외부 공개",
                "effect": "human_approval",
            },
        ],
        "risks": [
            {
                "risk_id": "unsupported-claim",
                "description": "검증되지 않은 사실이 대본에 들어갈 수 있다.",
                "severity": "high",
                "mitigation_required": True,
            }
        ],
        "unknowns": [
            {
                "unknown_id": "target-duration",
                "question": "영상 목표 길이는 아직 정하지 않았다.",
                "impact": "design",
                "status": unknown_status,
            }
        ],
        "suitability": {
            "recommended_shape": shape,
            "rationale": "조사·검증·작성 책임과 원형 산출물 전달을 분리해야 한다.",
            "evidence_refs": [ref("source", 103)],
        },
        "source_refs": [ref("source", 103)],
    }


DIMENSIONS = ["authority", "completion", "goal", "risk", "suitability", "unknowns"]


def confirmation(model_ref=None):
    return {
        "schema_version": "work-model-confirmation-v1",
        "confirmation_id": "00000000-0000-4000-8000-000000000104",
        "version": 1,
        "work_model_ref": model_ref,
        "confirmed_dimensions": list(DIMENSIONS),
        "confirmed_by": ref("actor", 105),
        "decision": "accepted",
    }


def accept(raw=None):
    raw = work_model() if raw is None else raw
    prepared = confirm_work_model(raw, None)
    return confirm_work_model(raw, confirmation(prepared.work_model_ref.as_dict()))


def test_confirmation_freezes_the_exact_common_work_target_and_all_dimensions():
    raw = work_model()
    prepared = confirm_work_model(raw, None)
    confirmed = confirm_work_model(raw, confirmation(prepared.work_model_ref.as_dict()))

    assert confirmed.state == "confirmed"
    assert confirmed.work_model_ref.sha256 == prepared.work_model_ref.sha256
    assert confirmed.confirmed_dimensions == tuple(DIMENSIONS)
    assert confirmed.design_disposition == "multi_agent"
    assert confirmed.blocked_unknown_ids == ()
    assert confirmed.confirmation_ref.kind == "decision_record"

    raw["goals"][0] = "입력 객체를 나중에 바꾼다."
    assert confirmed.work_model.goals == ("근거가 확인된 유튜브 기획과 완성 대본을 만든다.",)
    with pytest.raises(FrozenInstanceError):
        confirmed.state = "other"


@pytest.mark.parametrize("missing", DIMENSIONS)
def test_every_common_work_dimension_requires_exact_confirmation(missing):
    raw = work_model()
    prepared = confirm_work_model(raw, None)
    command = confirmation(prepared.work_model_ref.as_dict())
    command["confirmed_dimensions"].remove(missing)
    with pytest.raises(WorkModelContractError, match="dimensions"):
        confirm_work_model(raw, command)


def test_confirmation_is_content_bound_and_cannot_be_reused_after_an_edit():
    original = work_model()
    prepared = confirm_work_model(original, None)
    command = confirmation(prepared.work_model_ref.as_dict())
    changed = deepcopy(original)
    changed["completion_conditions"].append("게시 전 사람이 원형 PDF를 확인한다.")

    with pytest.raises(WorkModelContractError, match="exact work model"):
        confirm_work_model(changed, command)


@pytest.mark.parametrize("shape", ["single_agent", "deterministic", "multi_agent", "human_only"])
def test_single_deterministic_multi_agent_and_human_only_suitability_stay_explicit(shape):
    raw = work_model(shape=shape)
    prepared = confirm_work_model(raw, None)
    confirmed = confirm_work_model(raw, confirmation(prepared.work_model_ref.as_dict()))
    assert confirmed.design_disposition == shape


def test_blocking_unknown_is_confirmed_as_unknown_not_silently_resolved():
    raw = work_model(unknown_status="blocking")
    prepared = confirm_work_model(raw, None)
    confirmed = confirm_work_model(raw, confirmation(prepared.work_model_ref.as_dict()))
    assert confirmed.blocked_unknown_ids == ("target-duration",)


def test_onboarding_and_confirmation_can_never_be_relabelled_as_feedback():
    raw = work_model()
    raw["semantic_origin"] = "own_alternative"
    with pytest.raises(WorkModelContractError, match="work understanding"):
        confirm_work_model(raw, None)

    raw = work_model()
    prepared = confirm_work_model(raw, None)
    command = confirmation(prepared.work_model_ref.as_dict())
    command["feedback_ref"] = ref("own_alternative", 106)
    with pytest.raises(WorkModelContractError, match="confirmation"):
        confirm_work_model(raw, command)


def test_unknown_fields_noncanonical_types_and_oversized_values_fail_closed():
    mutations = []
    extra = work_model()
    extra["confidence"] = 0.99
    mutations.append(extra)
    boolean_version = work_model()
    boolean_version["version"] = True
    mutations.append(boolean_version)
    duplicate_goal = work_model()
    duplicate_goal["goals"].append(duplicate_goal["goals"][0])
    mutations.append(duplicate_goal)
    too_long = work_model()
    too_long["goals"] = ["가" * 4097]
    mutations.append(too_long)

    for value in mutations:
        with pytest.raises(WorkModelContractError):
            confirm_work_model(value, None)
