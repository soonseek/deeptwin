"""T038 attempts 5–6 — a WELL-SPECIFIED work for the live design arc, authored by the
SIMULATED owner (the test actor; decisions.md 2026-09-25, "Independent people").

Attempt 6 (2026-09-26, owner decisions after attempt 5) fixes the author's own two defects
that attempt 5's live critic exposed (evidence/us2.md "attempt 5"):
- the required `verifier` responsibility was looser than completion condition 2 (no
  `cited_ids`, no overall-verdict rule, not every clause of conditions 0–1): it now states
  exactly condition 2's inputs, model separation, report format and verdict rule, and every
  clause of conditions 0 and 1; condition 2's report covers every non-empty draft line
  (the title included), so a stray non-item line is a failing line of the report;
- byte-identical storage was not performable under the authority (tools bound only to
  agents): a deterministic node may now bind the `document_create` tool (owner decision
  "Deterministic tool bindings"), and condition 4 and the storage authority say the store is
  that model-free step handing the approved bytes to the tool unchanged.
Attempt 5's verifier text is kept (`ATTEMPT5_VERIFIER_RESPONSIBILITY`) only to replay its
saved live answer offline.

This is a DIFFERENT scenario from attempts 1–4 (the YouTube research/script work of
`test_work_model_confirmation.work_model`). Attempt 4's candidates followed every design
rule and passed every review finding, but stayed `insufficient_evidence` on counterexamples
that targeted what that work's completion conditions left open (must a fact-check consult
the originals? how is "the first 30 seconds" marked? may the verifier share the
researcher's model?). Here the test actor states, in the work model the critic reads, what
counts as verified, the format of every artifact, what the approver sees, what may be
regenerated (nothing, within a run), which sources and permissions exist, and which
properties are out of scope — all checkable in a graph. It is still a genuine multi-role
task: an intake of the stored original, a writer, an independent verifier on a different
model choice, the owner's approval, and the storing of exactly the approved content.

Nothing here is live and nothing here is a qualification: the lens decision rests on the
fixture evidence verifier (`proposed_lens`), exactly as in attempts 1–4.
"""

from __future__ import annotations

import copy
from uuid import NAMESPACE_URL, uuid5

from app.domain.schemas import ImmutableRecord
from app.services.design import accept_design_decision, confirm_work_model
from app.tests.test_design_generation import value_hash
from app.tests.design_arc_fixture import STAMP
from app.tests.test_work_model_confirmation import confirmation

AUTHOR = "SIMULATED owner (test actor) — attempt 5/6 work description, not a real owner's work"

WORK_TEXT = (
    "[시험 행위자(가상 소유자)가 작성한 업무 설명 — 실제 소유자의 업무가 아니다]\n"
    "업로드한 변경 기록 파일 changelog-2.4.0.md 한 개로 버전 2.4.0의 공개용 릴리스 노트 한 부를 만든다.\n"
    "- 원본: 변경 기록 파일 하나뿐이다. 각 항목은 `## CL-###` 제목, `공개: 예|아니오` 줄, 설명 문단으로 되어 있다. "
    "웹 조회나 다른 출처는 쓰지 않는다. 원본의 내용은 내가 책임지는 참값이다.\n"
    "- 릴리스 노트: text/markdown 한 파일. 항목 줄은 `- [CL-###] 설명` 형식이며 `공개: 예` 항목만, 각각 정확히 한 번 싣는다.\n"
    "- 검증: 작성자가 아닌 검증 역할이, 작성자와 다른 모델로, 원본 파일 자체와 초안을 직접 대조해 "
    "application/json 검증 보고서를 낸다.\n"
    "- 전체 판정이 fail이면 공개 없이 끝낸다. 같은 실행 안에서 다시 쓰지 않는다.\n"
    "- 승인: 내가 검증을 통과한 초안 원문, 그 보고서, 원본 파일을 함께 보고 승인한다. 승인된 초안이 바이트 그대로 저장된다.\n"
    "- 저장: 모델을 쓰지 않는 결정적 저장 단계가 승인본을 document.create 도구에 바이트 그대로 넘겨 저장한다.\n"
    "- 문체·어조·분량은 판정하지 않는다.\n"
)

SOURCE_NAME = "changelog-2.4.0.md"
SOURCE_TEXT = (
    "# changelog 2.4.0\n\n"
    "## CL-101\n공개: 예\n내보내기 대화상자에 CSV 형식이 추가되었다.\n\n"
    "## CL-102\n공개: 예\n검색 결과가 50개를 넘으면 페이지로 나뉜다.\n\n"
    "## CL-103\n공개: 아니오\n내부 결제 게이트웨이 키 교체 절차를 바꾸었다.\n\n"
    "## CL-104\n공개: 예\n로그인 세션 만료 시간이 30분에서 60분으로 늘었다.\n\n"
    "## CL-105\n공개: 아니오\n고객사 A 전용 기능 플래그를 제거했다.\n\n"
    "## CL-106\n공개: 예\n다크 모드에서 표 테두리가 보이지 않던 문제를 고쳤다.\n"
)

GOALS = [
    "업로드된 변경 기록 원본 한 개로, 원본에 근거가 확인된 버전 2.4.0 공개용 릴리스 노트 한 부를 만든다.",
    "완료 판정은 completion_conditions만으로 한다. 거기에 없는 속성(문체, 어조, 분량, 번역, 원본 변경 기록 "
    "자체의 사실 정확성)은 이 업무의 판정 대상이 아니다. 원본 변경 기록의 내용은 소유자가 책임지는 참값으로 "
    "취급하며, 원본 밖의 출처와 다시 대조할 필요가 없다.",
]

COMPLETION_CONDITIONS = [
    "릴리스 노트(text/markdown)의 모든 항목 줄은 `- [CL-###] `로 시작하고, 그 CL ID는 원본 변경 기록 파일에 "
    "있으며 원본에서 `공개: 예`로 표시된 항목이다. 항목 줄에 있는 모든 기능명·수치·버전은 그 줄이 인용한 원본 "
    "항목의 설명에 그대로 나온다. 항목 줄이 아닌 줄은 제목 한 줄(`# 2.4.0 릴리스 노트`)뿐이다.",
    "원본에서 `공개: 예`로 표시된 모든 CL ID가 릴리스 노트에 정확히 한 번 인용되고, `공개: 아니오` 항목의 "
    "ID와 내용은 릴리스 노트 어디에도 나오지 않는다.",
    "앞의 두 조건은 작성 역할이 아닌 검증 역할이 판정한다. 검증 역할은 원본 변경 기록 파일 자체(요약·발췌·"
    "작성자의 메모가 아님)와 초안 원문을 둘 다 입력으로 직접 받아 대조하고, 작성 역할과 다른 model choice를 "
    "쓴다. 결과는 검증 역할 자신의 application/json 검증 보고서이며, 빈 줄을 뺀 초안의 모든 줄(제목 줄 포함)마다 "
    "{line, cited_ids, verdict: "
    "pass|fail, reason}, 누락된 공개 ID 목록, 노출된 비공개 ID 목록, 전체 verdict(pass|fail)를 가진다. 전체 "
    "verdict는 모든 줄이 pass이고 두 목록이 비어 있을 때만 pass다.",
    "전체 verdict가 fail이면 그 초안은 승인 단계에 도달하지 않고 실행은 저장·공개 없이 끝난다. 같은 실행 "
    "안에서는 어떤 산출물도 재생성·재작성하지 않는다(소유자가 새 실행을 시작한다).",
    "승인자(소유자 한 사람)는 artifact.publish 범위로 승인하며, 승인 단계는 검증을 통과한 초안 원문, 그 "
    "초안의 검증 보고서, 원본 변경 기록 파일을 함께 입력으로 받는다. 저장되는 릴리스 노트는 승인 단계가 "
    "내보낸 승인본과 바이트 단위로 같다: 승인 뒤 어떤 역할도 내용을 재생성·수정·형식 변환하지 않는다. 저장은 "
    "모델을 쓰지 않는 결정적(deterministic) 저장 단계가 수행한다. 그 단계는 승인 단계가 내보낸 승인본만 입력으로 "
    "받아 document.create 도구에 바이트 그대로 넘기며, 어떤 모델 역할도 저장하지 않는다.",
]

WORK_MODEL = {
    "schema_version": "work-model-v1",
    "work_model_id": "00000000-0000-4000-8000-000000000501",
    "version": 1,
    "work_revision_ref": None,  # set to the saved work's revision
    "semantic_origin": "work_understanding",
    "goals": GOALS,
    "deliverables": [{
        "deliverable_id": "release-notes",
        "description": "승인된 원문 그대로 저장된 버전 2.4.0 릴리스 노트(markdown 한 파일)",
        "media_types": ["text/markdown"],
        "min_items": 1,
        "max_items": 1,
        "max_total_bytes": 65_536,
    }],
    "completion_conditions": COMPLETION_CONDITIONS,
    "authorities": [
        {"authority_id": "source-read", "capability": "artifact.read",
         "scope": "업로드된 변경 기록 원본 파일 changelog-2.4.0.md 하나만 읽는다. 실행 시작 시 프레임워크가 이 "
                  "파일을 바꾸지 않고 그대로 넘긴다. 웹 조회와 다른 출처는 허용되지 않으며 필요하지 않다.",
         "effect": "read"},
        {"authority_id": "notes-store", "capability": "document.create",
         "scope": "승인된 릴리스 노트 markdown 한 부를 문서 저장소에 새 문서로 저장한다(되돌릴 수 있다). "
                  "승인 전에는 저장하지 않는다. 모델 없는 결정적 저장 단계가 document.create 도구로 승인본 "
                  "바이트를 그대로 저장한다.",
         "effect": "write"},
        {"authority_id": "publish-approval", "capability": "artifact.publish",
         "scope": "소유자 한 사람이 검증을 통과한 릴리스 노트 원문의 저장·공개를 승인한다.",
         "effect": "human_approval"},
    ],
    "risks": [{
        "risk_id": "unsupported-or-private-line",
        "description": "원본에 근거하지 않은 내용이나 `공개: 아니오` 항목이 릴리스 노트에 실릴 수 있다. "
                       "완료 조건 0–2의 독립 검증과 조건 3의 차단으로 막는다.",
        "severity": "high",
        "mitigation_required": True,
    }],
    "unknowns": [],
    "suitability": {
        "recommended_shape": "multi_agent",
        "rationale": "작성과 검증을 서로 다른 역할·모델로 분리하고, 사람의 승인과 승인본의 저장을 분리해야 한다.",
        "evidence_refs": [],
    },
    "source_refs": [],
}

# attempt 5's text (looser than condition 2); kept only to replay attempt 5's live answer
ATTEMPT5_VERIFIER_RESPONSIBILITY = (
    "초안 원문의 각 항목 줄과 공개 ID 누락·비공개 ID 노출을 원본 변경 기록 파일 자체와 직접 대조해, 줄별 "
    "pass/fail과 이유, 누락 ID, 노출 ID, 전체 verdict를 application/json 검증 보고서로 낸다."
)
# attempt 6: exactly completion condition 2 (inputs, model separation, report format and
# verdict rule) over every clause of conditions 0 and 1
VERIFIER_RESPONSIBILITY = (
    "작성 역할과 다른 model choice로, 원본 변경 기록 파일 자체(요약·발췌·작성자의 메모가 아님)와 초안 원문을 "
    "둘 다 입력으로 직접 받아 대조해 완료 조건 0과 1을 판정한다: 모든 항목 줄이 `- [CL-###] `로 시작하고 그 CL "
    "ID가 원본에 있는 `공개: 예` 항목이며 줄의 모든 기능명·수치·버전이 그 항목 설명에 그대로 나오는지, 항목 줄이 "
    "아닌 줄이 제목 한 줄(`# 2.4.0 릴리스 노트`)뿐인지, `공개: 예`인 모든 CL ID가 정확히 한 번 인용되는지, "
    "`공개: 아니오` 항목의 ID와 내용이 어디에도 나오지 않는지. 결과는 자신의 application/json 검증 보고서이며, "
    "빈 줄을 뺀 초안의 모든 줄(제목 줄 포함)마다 {line, cited_ids, verdict: pass|fail, reason}, 누락된 공개 ID "
    "목록, 노출된 비공개 ID 목록, 전체 verdict(pass|fail)를 가진다. 전체 verdict는 모든 줄이 pass이고 두 목록이 "
    "비어 있을 때만 pass다."
)


def specified_work_model(domain, revision_ref, source_refs):
    """Confirm and store the attempt-5 work model over the saved work's revision."""

    roots = domain.roots()
    raw = copy.deepcopy(WORK_MODEL)
    raw["work_model_id"] = str(uuid5(NAMESPACE_URL, f"deeptwin:attempt5-specified-work-model:{revision_ref.id}"))
    raw["work_revision_ref"] = revision_ref.as_dict()
    raw["source_refs"] = [ref.as_dict() for ref in source_refs]
    raw["suitability"]["evidence_refs"] = [ref.as_dict() for ref in source_refs]
    prepared = confirm_work_model(raw, None)
    target = confirm_work_model(raw, confirmation(prepared.work_model_ref.as_dict()))
    domain.put(ImmutableRecord.create(
        kind="work_model", id=raw["work_model_id"], version=1, created_at_utc=STAMP, actor_ref=roots.actor,
        parent_refs=(revision_ref,), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content=target.work_model.as_dict()))
    return target


def specified_decision(target, registry, lens, *, responsibility=VERIFIER_RESPONSIBILITY):
    """The test actor's functional decision for this work: the lens `L-P032-01` (a proposal
    accepted or rejected against observation) as a separate verifier's responsibility
    (attempt 6's text by default; attempt 5's only to replay its saved answer)."""

    return accept_design_decision(target, [lens], {
        "decision_id": "00000000-0000-4000-8000-000000000521",
        "version": 1,
        "functional_claims": ["초안(제안)을 원본(관찰)과 대조해 수용하거나 기각하는 검증 책임을 작성 책임과 분리한다."],
        "proposed_effects": [{
            "effect_id": "verifier-responsibility",
            "axis": "responsibility",
            "target": {"kind": "node", "id": "verifier", "field": "responsibility"},
            "expected_value_sha256": value_hash(responsibility),
            "expected_value": responsibility,
            "rationale": "작성자의 서술을 원본 관찰로 수용·기각하는 판단을 작성자와 다른 역할이 맡게 한다.",
            "contributing_lens_refs": [str(lens.lens_ref)],
        }],
        "conflicts": [],
        "abstentions": [],
    }, registry=registry)


def specified_work_with_source(subject):
    """A real saved work carrying WORK_TEXT, with the changelog stored as its one original."""

    from types import SimpleNamespace

    from app.domain.refs import EntityRef
    from app.tests.test_claude_live_path import real_work
    from app.tests.test_owner_material_intake import metadata, upload

    revision = real_work(subject, WORK_TEXT)
    data = SOURCE_TEXT.encode()
    target = SimpleNamespace(client=subject.client, profile=subject.profile, csrf=subject.csrf,
                             path=subject.profile.base_path + "api/v1/works")
    response = upload(target, {"work_id": revision.id}, data,
                      metadata(data, name=SOURCE_NAME, declared_media_type="text/markdown", expected_revision=1))
    assert response.status_code == 201, response.text
    value = response.json()
    return EntityRef.from_dict(value["ref"]), [EntityRef.from_dict(item) for item in value["source_refs"]]
