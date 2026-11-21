from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from deeptwin.compose import FLUID_CLOSE, FLUID_OPEN, compose, fill_fluid
from deeptwin.errors import DeeptwinError
from deeptwin.models import Composed, Principle, Rejected, Skill, Task
from deeptwin.store.files import read_yaml, write_text, write_yaml
from deeptwin.store.project import DeepTwin

CONTEXT = {"purpose": "문의"}

GUIDE_ONE_PRINCIPLE = "## 이번 작업의 개인 기준\n\n반드시 지킬 것\n- 수치를 부풀리지 않는다\n"

AXES = {"purpose": ["문의", "상담", "기타"], "channel": ["email", "kakao"]}
CARD_CONTEXT = {"purpose": "문의", "channel": "email"}
POINTS = [
    {"id": "opening", "name": "첫 문장", "weight": 3},
    {"id": "answer", "name": "답", "weight": 2},
    {"id": "tone", "name": "말투", "weight": 1},
]


@pytest.fixture
def deeptwin(tmp_path: Path) -> DeepTwin:
    return DeepTwin.init(tmp_path).deeptwin


def make_skill(skill_id: str = "minimal", **fields: Any) -> Skill:
    data = {
        "id": skill_id,
        "skill_md": Path("skills") / skill_id / "SKILL.md",
        "context_axes": {"purpose": AXES["purpose"]},
        **fields,
    }
    return Skill.model_validate(data)


def card_skill(**budget: int) -> Skill:
    """판단 지점 셋(weight 3, 2, 1)과 축 둘을 가진 스킬. 상한은 넉넉하고 `budget`으로 바꾼다."""
    return make_skill(
        decision_points=POINTS,
        context_axes=AXES,
        budget={"cards_per_point": 9, "cards_total": 99, **budget},
    )


def make_task(task_id: str = "task-0001") -> Task:
    return Task(
        id=task_id,
        skill="minimal",
        split="train",
        input="수강료가 얼마인가요?",
        context=CONTEXT,
    )


def principle(item_id: str, rule: str, **fields: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "id": item_id,
        "rule": rule,
        "kind": "never",
        "check": None,
        "scope": [],
        "status": "active",
        "approval": "human",
        **fields,
    }


def priority(item_id: str, rule: str, **fields: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "id": item_id,
        "rule": rule,
        "scope": [],
        "status": "active",
        "approval": "human",
        **fields,
    }


def card(item_id: str, point: str, choose: str, **fields: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "id": item_id,
        "layer": "tendency",
        "skill": "minimal",
        "decision_point": point,
        "status": "active",
        "approval": "human",
        "choose": choose,
        **fields,
    }


def example(item_id: str, **fields: Any) -> dict[str, Any]:
    """이 스킬의 `active` 대표작 good 예시. 글은 `<id>의 글`이고 `fields`로 바꾼다."""
    return {
        "schema": 1,
        "id": item_id,
        "layer": "instinct",
        "skill": "minimal",
        "kind": "good",
        "grade": "signature",
        "text": f"{item_id}의 글",
        "status": "active",
        "approval": "human",
        **fields,
    }


def write_principles(deeptwin: DeepTwin, items: list[dict[str, Any]]) -> None:
    write_yaml(deeptwin.path / "layers" / "principles.yaml", items)


def write_priorities(deeptwin: DeepTwin, items: list[dict[str, Any]]) -> None:
    write_yaml(deeptwin.path / "layers" / "priorities.yaml", items)


def write_cards(deeptwin: DeepTwin, items: list[dict[str, Any]]) -> None:
    for item in items:
        write_yaml(deeptwin.path / "layers" / "cards" / f"{item['id']}.yaml", item)


def write_examples(deeptwin: DeepTwin, items: list[dict[str, Any]]) -> None:
    for item in items:
        write_yaml(deeptwin.path / "layers" / "examples" / f"{item['id']}.yaml", item)


def drawn(task_id: str, ids: Iterable[str]) -> list[str]:
    """계획의 뽑기 순서: `sha256(과제 ID + "\n" + 예시 ID)`의 16진 글 오름차순."""
    return sorted(ids, key=lambda i: hashlib.sha256(f"{task_id}\n{i}".encode()).hexdigest())


def compose_cards(deeptwin: DeepTwin, skill: Skill | None = None, **options: Any) -> Composed:
    options.setdefault("context", CARD_CONTEXT)
    return compose(skill or card_skill(), make_task(), deeptwin, **options)


def reasons(composed: Composed) -> list[tuple[str, str]]:
    return [(r.id, r.reason) for r in composed.rejected]


# 1단계와 표기: 원칙과 우선순위


def test_guide_follows_fixed_template(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.guide == GUIDE_ONE_PRINCIPLE
    assert composed.injected == ["prin-01"]
    assert composed.rejected == []
    assert composed.no_hit == []
    assert composed.conflicts == []
    expected_hash = hashlib.sha256(GUIDE_ONE_PRINCIPLE.encode("utf-8")).hexdigest()
    assert composed.guide_hash == "sha256:" + expected_hash


def test_leaves_out_inactive_and_other_scope(deeptwin: DeepTwin) -> None:
    write_principles(
        deeptwin,
        [
            principle("prin-01", "수치를 부풀리지 않는다"),
            principle("prin-02", "쉬는 원칙", status="dormant"),
            principle("prin-03", "후보 원칙", status="candidate"),
            principle("prin-04", "다른 스킬의 원칙", scope=["post-writer"]),
            principle("prin-05", "모르는 것은 모른다고 쓴다", kind="must", scope=["minimal"]),
            principle("prin-06", "물러난 원칙", status="retired"),
        ],
    )

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.injected == ["prin-01", "prin-05"]
    assert composed.guide == (
        "## 이번 작업의 개인 기준\n\n반드시 지킬 것\n"
        "- 수치를 부풀리지 않는다\n- 모르는 것은 모른다고 쓴다\n"
    )


def test_priorities_follow_principles_in_file_order_with_numbers(deeptwin: DeepTwin) -> None:
    write_priorities(
        deeptwin,
        [
            priority("pri-02", "빠짐없음이 짧음보다 먼저다"),
            priority("pri-03", "쉬는 우선순위", status="dormant"),
            priority("pri-04", "다른 스킬의 우선순위", scope=["post-writer"]),
            priority("pri-01", "정확함이 재미보다 먼저다", scope=["minimal"]),
        ],
    )

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.injected == ["pri-02", "pri-01"]
    assert composed.guide == (
        "## 이번 작업의 개인 기준\n\n부딪칠 때의 순서\n"
        "1. 빠짐없음이 짧음보다 먼저다\n2. 정확함이 재미보다 먼저다\n"
    )


def test_no_principles_gives_empty_guide(deeptwin: DeepTwin) -> None:
    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.guide == ""
    assert composed.injected == []


def test_ablate_principle_leaves_principles_out(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT, ablate=("principle",))

    assert composed.guide == ""
    assert composed.injected == []


def test_ablate_priority_leaves_priorities_out_and_skips_their_budget(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])
    write_priorities(deeptwin, [priority(f"pri-{n:02d}", f"우선순위 {n}") for n in range(1, 4)])
    skill = make_skill(budget={"priorities_max": 2})

    composed = compose(skill, make_task(), deeptwin, context=CONTEXT, ablate=("priority",))

    assert composed.guide == GUIDE_ONE_PRINCIPLE
    assert composed.injected == ["prin-01"]


@pytest.mark.acceptance
@pytest.mark.parametrize(
    ("layer", "write", "item", "budget_field", "path"),
    [
        ("원칙", write_principles, principle, "principles_max", "layers/principles.yaml"),
        ("우선순위", write_priorities, priority, "priorities_max", "layers/priorities.yaml"),
    ],
    ids=["principle", "priority"],
)
def test_more_items_than_the_cap_is_over_budget(
    deeptwin: DeepTwin,
    layer: str,
    write: Any,
    item: Any,
    budget_field: str,
    path: str,
) -> None:
    """설계서 8.11 수용 테스트 5: 원칙이 `principles_max`를 넘으면 오류가 난다(우선순위도 같다)."""
    write(
        deeptwin,
        [
            item("item-01", "하나"),
            item("item-02", "둘", scope=["minimal"]),
            item("item-03", "셋"),
            item("item-04", "쉬는 항목", status="dormant"),
            item("item-05", "다른 스킬의 항목", scope=["post-writer"]),
        ],
    )
    skill = make_skill(budget={budget_field: 2})

    with pytest.raises(DeeptwinError) as info:
        compose(skill, make_task(), deeptwin, context=CONTEXT)

    assert info.value.code == "over_budget"
    assert info.value.message == (
        f"{layer} 상한을 넘었습니다: 스킬 minimal에 맞는 active {layer} 3개, {budget_field} 2개. "
        f"지침을 자르지 않으니 .deeptwin/{path}의 {layer} 항목을 합쳐 2개 이하로 줄이세요."
    )


def test_items_up_to_the_cap_are_all_kept(deeptwin: DeepTwin) -> None:
    write_principles(
        deeptwin,
        [
            principle("prin-01", "하나"),
            principle("prin-02", "둘"),
            principle("prin-03", "쉬는 원칙", status="dormant"),
            principle("prin-04", "다른 스킬의 원칙", scope=["post-writer"]),
        ],
    )

    composed = compose(
        make_skill(budget={"principles_max": 2}), make_task(), deeptwin, context=CONTEXT
    )

    assert composed.injected == ["prin-01", "prin-02"]


def test_ablate_principle_skips_its_budget(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle(f"prin-{n:02d}", f"원칙 {n}") for n in range(1, 4)])
    skill = make_skill(budget={"principles_max": 2})

    composed = compose(skill, make_task(), deeptwin, context=CONTEXT, ablate=("principle",))

    assert composed.injected == []


# 맥락 검사


@pytest.mark.parametrize(
    ("context", "message"),
    [
        (
            {"purpose": "문의", "audience": "입문자"},
            "맥락 축이 스킬 minimal의 context_axes에 없습니다: audience=입문자. "
            "쓸 수 있는 축: purpose, channel",
        ),
        (
            {"purpose": "없는값"},
            "맥락 값이 스킬 minimal의 context_axes에 없습니다: purpose=없는값. "
            "purpose에 쓸 수 있는 값: 문의, 상담, 기타",
        ),
        (
            {"channel": "fax", "audience": "입문자"},
            "맥락 값이 스킬 minimal의 context_axes에 없습니다: channel=fax. "
            "channel에 쓸 수 있는 값: email, kakao\n"
            "맥락 축이 스킬 minimal의 context_axes에 없습니다: audience=입문자. "
            "쓸 수 있는 축: purpose, channel",
        ),
    ],
)
def test_context_outside_the_skill_axes_is_invalid(
    deeptwin: DeepTwin, context: dict[str, str], message: str
) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])

    with pytest.raises(DeeptwinError) as info:
        compose_cards(deeptwin, context=context)

    assert info.value.code == "invalid_context"
    assert info.value.message == message


def test_skill_without_axes_takes_no_context(deeptwin: DeepTwin) -> None:
    with pytest.raises(DeeptwinError) as info:
        compose(make_skill(context_axes={}), make_task(), deeptwin, context=CONTEXT)

    assert info.value.code == "invalid_context"
    assert info.value.message.endswith("쓸 수 있는 축: 없음")


def test_empty_context_is_valid(deeptwin: DeepTwin) -> None:
    write_cards(deeptwin, [card("card-0001", "opening", "아무 맥락에나 맞는다")])

    composed = compose_cards(deeptwin, context={})

    assert composed.injected == ["card-0001"]


# 2단계: 카드 후보


def test_when_must_match_every_written_axis(deeptwin: DeepTwin) -> None:
    write_cards(
        deeptwin,
        [
            card("card-0001", "opening", "두 축", when={"purpose": ["문의"], "channel": ["kakao"]}),
            card("card-0002", "opening", "축을 적지 않음"),
            card("card-0003", "opening", "빈 목록", when={"purpose": [], "channel": []}),
            card("card-0004", "opening", "맞는 값", when={"purpose": ["상담", "문의"]}),
            card("card-0005", "opening", "다른 값", when={"purpose": ["상담"]}),
            card("card-0006", "opening", "스킬에 없는 축", when={"audience": ["입문자"]}),
        ],
    )

    composed = compose_cards(deeptwin, context={"purpose": "문의"})

    assert composed.injected == ["card-0004", "card-0002", "card-0003"]
    assert composed.rejected == []


def test_skips_inactive_cards_other_skills_and_unknown_points(deeptwin: DeepTwin) -> None:
    write_cards(
        deeptwin,
        [
            card("card-0001", "opening", "들어간다"),
            card("card-0002", "opening", "쉬는 카드", status="dormant"),
            card("card-0003", "opening", "후보 카드", status="candidate"),
            card("card-0004", "opening", "다른 스킬의 카드", skill="post-writer"),
            card("card-0005", "hashtags", "skill.yaml에 없는 판단 지점"),
        ],
    )

    composed = compose_cards(deeptwin, skill=card_skill(cards_per_point=0, cards_total=0))

    assert composed.injected == []
    assert reasons(composed) == [("card-0001", "budget")]
    assert composed.no_hit == ["answer", "tone"]


@pytest.mark.acceptance
def test_point_without_matching_card_is_no_hit(deeptwin: DeepTwin) -> None:
    """설계서 8.11 수용 테스트 4: 맞는 카드가 없는 판단 지점은 `no_hit`에 적힌다."""
    write_cards(
        deeptwin,
        [
            card("card-0001", "tone", "맞지 않는 말투", when={"channel": ["kakao"]}),
            card("card-0002", "answer", "맞는 답"),
        ],
    )

    composed = compose_cards(deeptwin)

    assert composed.injected == ["card-0002"]
    assert composed.no_hit == ["opening", "tone"]


def test_no_hit_counts_cards_before_conflicts_and_budget(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])
    write_cards(
        deeptwin,
        [
            card("card-0001", "opening", "원칙과 부딪친다", conflicts_with=["prin-01"]),
            card("card-0002", "answer", "상한으로 빠진다"),
        ],
    )

    composed = compose_cards(deeptwin, skill=card_skill(cards_per_point=0))

    assert composed.injected == ["prin-01"]
    assert reasons(composed) == [("card-0001", "lower_layer"), ("card-0002", "budget")]
    assert composed.no_hit == ["tone"]


# 3단계: 점수


def test_cards_sorted_by_axes_then_rate_then_last_used_then_id(deeptwin: DeepTwin) -> None:
    def stats(injected: int, agreed: int, last_used: str | None = None) -> dict[str, Any]:
        return {"injected": injected, "agreed": agreed, "last_used": last_used}

    write_cards(
        deeptwin,
        [
            card("card-0001", "opening", "id가 작다"),
            card("card-0002", "opening", "늦게 씀", stats=stats(0, 0, "2026-11-18")),
            card("card-0003", "opening", "일찍 씀", stats=stats(0, 0, "2026-11-01")),
            card("card-0004", "opening", "일치율 높음", stats=stats(2, 2)),
            card("card-0005", "opening", "일치율 낮음", stats=stats(2, 0, "2026-11-20")),
            card("card-0006", "opening", "축 하나", when={"purpose": ["문의"]}),
            card(
                "card-0007",
                "opening",
                "축 둘",
                when={"purpose": ["문의"], "channel": ["email"]},
                stats=stats(9, 0),
            ),
            card("card-0000", "opening", "id가 더 작다"),
        ],
    )

    composed = compose_cards(deeptwin)

    assert composed.injected == [
        "card-0007",  # 맞은 축 2
        "card-0006",  # 맞은 축 1
        "card-0004",  # 일치율 3/4
        "card-0002",  # 일치율 1/2, 2026-11-18
        "card-0003",  # 일치율 1/2, 2026-11-01
        "card-0000",  # 일치율 1/2, last_used 없음, id 순
        "card-0001",
        "card-0005",  # 일치율 1/4
    ]


def test_rate_is_compared_as_exact_fraction(deeptwin: DeepTwin) -> None:
    big = 10**17
    # 두 일치율은 (big + 1) / (big + 2)와 big / (big + 1)이다. 앞쪽이 크지만 float로는 같다
    assert (big + 1) / (big + 2) == big / (big + 1)
    write_cards(
        deeptwin,
        [
            card(
                "card-0001", "opening", "조금 낮다", stats={"injected": big - 1, "agreed": big - 1}
            ),
            card("card-0002", "opening", "조금 높다", stats={"injected": big, "agreed": big}),
        ],
    )

    composed = compose_cards(deeptwin)

    assert composed.injected == ["card-0002", "card-0001"]


# 4단계: 충돌


@pytest.mark.acceptance
@pytest.mark.parametrize("written_on", ["higher", "lower"])
def test_conflicting_cards_keep_only_the_higher_score(deeptwin: DeepTwin, written_on: str) -> None:
    """설계서 8.11 수용 테스트 3: `conflicts_with`로 묶인 두 카드 중 점수가 높은 쪽만 들어간다."""
    higher = card(
        "card-0002", "opening", "축이 둘", when={"purpose": ["문의"], "channel": ["email"]}
    )
    lower = card("card-0001", "tone", "축이 하나", when={"purpose": ["문의"]})
    (higher if written_on == "higher" else lower)["conflicts_with"] = [
        "card-0001" if written_on == "higher" else "card-0002"
    ]
    write_cards(deeptwin, [higher, lower])

    composed = compose_cards(deeptwin)

    assert composed.injected == ["card-0002"]
    assert composed.rejected == [Rejected(id="card-0001", reason="conflict")]
    assert composed.conflicts == []


def test_tied_conflict_drops_both_and_records_the_pair(deeptwin: DeepTwin) -> None:
    write_cards(
        deeptwin,
        [
            card("card-0009", "opening", "같은 점수 하나", conflicts_with=["card-0003"]),
            card("card-0003", "answer", "같은 점수 둘", conflicts_with=["card-0009"]),
            card("card-0005", "tone", "부딪치지 않는다"),
        ],
    )

    composed = compose_cards(deeptwin)

    assert composed.injected == ["card-0005"]
    assert reasons(composed) == [("card-0003", "conflict"), ("card-0009", "conflict")]
    assert composed.conflicts == [["card-0003", "card-0009"]]


def test_conflicts_compare_pairs_among_first_survivors(deeptwin: DeepTwin) -> None:
    write_cards(
        deeptwin,
        [
            card(
                "card-0001",
                "opening",
                "가장 높다",
                when={"purpose": ["문의"], "channel": ["email"]},
                conflicts_with=["card-0002"],
            ),
            card("card-0002", "opening", "가운데", when={"purpose": ["문의"]}),
            card("card-0003", "opening", "가장 낮다", conflicts_with=["card-0002"]),
            card(
                "card-0004", "opening", "자기 자신과 없는 카드", conflicts_with=["card-0004", "x"]
            ),
        ],
    )

    composed = compose_cards(deeptwin)

    assert composed.injected == ["card-0001", "card-0004"]
    assert reasons(composed) == [("card-0002", "conflict"), ("card-0003", "conflict")]
    assert composed.conflicts == []


@pytest.mark.parametrize(
    ("principles", "priorities", "ablate"),
    [
        ([principle("prin-01", "원칙")], [], ()),
        ([principle("prin-01", "다른 스킬의 원칙", scope=["post-writer"])], [], ()),
        ([principle("prin-01", "원칙")], [], ("principle",)),
        ([], [priority("pri-01", "우선순위")], ("priority",)),
    ],
    ids=["principle", "other-scope", "ablated", "priority"],
)
def test_card_against_an_active_lower_layer_item_is_lower_layer(
    deeptwin: DeepTwin,
    principles: list[dict[str, Any]],
    priorities: list[dict[str, Any]],
    ablate: tuple[str, ...],
) -> None:
    write_principles(deeptwin, principles)
    write_priorities(deeptwin, priorities)
    write_cards(
        deeptwin,
        [
            card(
                "card-0001",
                "opening",
                "아래 층과 부딪친다",
                when={"purpose": ["문의"], "channel": ["email"]},
                conflicts_with=["prin-01", "pri-01", "card-0002"],
            ),
            card("card-0002", "opening", "남는다"),
        ],
    )

    composed = compose_cards(deeptwin, ablate=ablate)

    assert [i for i in composed.injected if i.startswith("card-")] == ["card-0002"]
    assert composed.rejected == [Rejected(id="card-0001", reason="lower_layer")]


def test_inactive_lower_layer_item_does_not_reject(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "쉬는 원칙", status="dormant")])
    write_cards(deeptwin, [card("card-0001", "opening", "남는다", conflicts_with=["prin-01"])])

    composed = compose_cards(deeptwin)

    assert composed.injected == ["card-0001"]
    assert composed.rejected == []


# 5단계: 상한


@pytest.mark.acceptance
def test_cards_over_the_point_cap_are_rejected_as_budget(deeptwin: DeepTwin) -> None:
    """설계서 8.11 수용 테스트 2: 카드가 상한보다 많으면 상한만큼만 들어가고 나머지는 `budget`."""
    write_cards(
        deeptwin,
        [
            card("card-0001", "opening", "셋째"),
            card("card-0002", "opening", "첫째", when={"purpose": ["문의"], "channel": ["email"]}),
            card("card-0003", "opening", "둘째", when={"purpose": ["문의"]}),
            card("card-0004", "answer", "다른 판단 지점"),
        ],
    )

    composed = compose_cards(deeptwin, skill=card_skill(cards_per_point=2))

    assert composed.injected == ["card-0002", "card-0003", "card-0004"]
    assert composed.rejected == [Rejected(id="card-0001", reason="budget")]


def test_total_cap_drops_the_lowest_weight_point_first(deeptwin: DeepTwin) -> None:
    axis = {"when": {"purpose": ["문의"]}}
    write_cards(
        deeptwin,
        [
            card("card-0001", "opening", "첫 문장 1", **axis),
            card("card-0002", "opening", "첫 문장 2"),
            card("card-0003", "answer", "답 1", **axis),
            card("card-0004", "answer", "답 2"),
            card("card-0005", "tone", "말투 1", **axis),
        ],
    )

    composed = compose_cards(deeptwin, skill=card_skill(cards_per_point=2, cards_total=3))

    assert composed.injected == ["card-0001", "card-0002", "card-0003"]
    assert reasons(composed) == [
        ("card-0005", "budget"),
        ("card-0004", "budget"),
    ]


def test_total_cap_with_equal_weights_drops_the_later_point_first(deeptwin: DeepTwin) -> None:
    points = [
        {"id": "opening", "name": "첫 문장", "weight": 1},
        {"id": "answer", "name": "답", "weight": 1},
        {"id": "tone", "name": "말투", "weight": 2},
    ]
    write_cards(
        deeptwin,
        [
            card("card-0001", "opening", "첫 문장"),
            card("card-0002", "answer", "답 1"),
            card("card-0003", "answer", "답 2"),
            card("card-0004", "tone", "말투"),
        ],
    )
    skill = make_skill(
        decision_points=points,
        context_axes=AXES,
        budget={"cards_per_point": 2, "cards_total": 2},
    )

    composed = compose_cards(deeptwin, skill=skill)

    assert composed.injected == ["card-0001", "card-0004"]
    assert reasons(composed) == [("card-0002", "budget"), ("card-0003", "budget")]


def test_rejected_is_in_stage_order_then_score_order(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "원칙")])
    two_axes = {"when": {"purpose": ["문의"], "channel": ["email"]}}
    write_cards(
        deeptwin,
        [
            card("card-0001", "tone", "상한으로 먼저 빠지지만 점수가 낮다"),
            card("card-0002", "opening", "weight가 가장 높아 남는다"),
            card("card-0003", "answer", "충돌 낮은 쪽", conflicts_with=["card-0004"]),
            card("card-0004", "answer", "충돌 높은 쪽, 상한으로 나중에 빠진다", **two_axes),
            card("card-0005", "tone", "아래 층 낮은 순위", conflicts_with=["prin-01"]),
            card(
                "card-0006", "opening", "아래 층 높은 순위", conflicts_with=["prin-01"], **two_axes
            ),
        ],
    )

    composed = compose_cards(deeptwin, skill=card_skill(cards_total=1))

    assert composed.injected == ["prin-01", "card-0002"]
    # 상한은 card-0001(말투), card-0004(답) 순으로 뺐지만 rejected에는 점수 순으로 적는다
    assert reasons(composed) == [
        ("card-0006", "lower_layer"),
        ("card-0005", "lower_layer"),
        ("card-0003", "conflict"),
        ("card-0004", "budget"),
        ("card-0001", "budget"),
    ]


# 6단계: 예시


GOOD = ["ex-0001", "ex-0002", "ex-0003", "ex-0004"]
AVOID = ["ex-0005", "ex-0006"]


def write_candidates(deeptwin: DeepTwin) -> None:
    """예시 후보: 대표작 good 넷(`GOOD`)과 avoid 둘(`AVOID`)."""
    write_examples(
        deeptwin,
        [*(example(i) for i in GOOD), *(example(i, kind="avoid") for i in AVOID)],
    )


def example_ids(composed: Composed) -> list[str]:
    return [i for i in composed.injected if i.startswith("ex-")]


def test_draws_two_good_and_one_avoid_among_signature_examples(deeptwin: DeepTwin) -> None:
    write_candidates(deeptwin)
    not_candidates = [
        example("ex-0007", grade="usual"),
        example("ex-0008", grade="rushed"),
        example("ex-0009", kind="pair", text=None, before="고치기 전 글", after="고친 뒤 글"),
        example("ex-0010", status="retired"),
        example("ex-0011", skill="post-writer"),
    ]
    write_examples(deeptwin, not_candidates)

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    good, avoid = drawn("task-0001", GOOD), drawn("task-0001", AVOID)
    assert composed.injected == [good[0], good[1], avoid[0]]
    assert reasons(composed) == [(good[2], "budget"), (good[3], "budget"), (avoid[1], "budget")]
    assert composed.guide == (
        "## 이번 작업의 개인 기준\n\n"
        f"이렇게 쓴다\n{good[0]}의 글\n\n---\n\n{good[1]}의 글\n\n"
        f"이렇게는 쓰지 않는다\n{avoid[0]}의 글\n"
    )
    for item in not_candidates:
        assert item["id"] not in composed.guide
    assert "고치" not in composed.guide


def test_same_task_draws_the_same_examples_twice(deeptwin: DeepTwin) -> None:
    write_candidates(deeptwin)

    first = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)
    second = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert first == second
    assert first.guide_hash == second.guide_hash
    assert len(example_ids(first)) == 3


def test_draw_order_is_seeded_by_the_task_id(deeptwin: DeepTwin) -> None:
    write_candidates(deeptwin)
    picks: set[tuple[str, ...]] = set()

    for task_id in ("task-0001", "task-0002", "task-0003", "task-0004"):
        composed = compose(make_skill(), make_task(task_id), deeptwin, context=CONTEXT)
        expected = [*drawn(task_id, GOOD)[:2], drawn(task_id, AVOID)[0]]
        assert example_ids(composed) == expected
        picks.add(tuple(expected))

    # 후보가 같아도 과제가 다르면 다른 예시가 뽑힌다
    assert len(picks) > 1


def test_too_few_candidates_fill_only_what_there_is(deeptwin: DeepTwin) -> None:
    write_examples(
        deeptwin,
        [
            example("ex-0001", text="보강은 다음 주 화요일입니다."),
            example("ex-0002", kind="avoid", grade="usual"),
        ],
    )

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.injected == ["ex-0001"]
    assert composed.rejected == []
    assert (
        composed.guide == "## 이번 작업의 개인 기준\n\n이렇게 쓴다\n보강은 다음 주 화요일입니다.\n"
    )


@pytest.mark.parametrize(
    ("limit", "good_count", "avoid_count"),
    [(-1, 0, 0), (0, 0, 0), (1, 1, 0), (2, 2, 0), (3, 2, 1), (10, 2, 1)],
)
def test_examples_cap_cuts_avoid_first(
    deeptwin: DeepTwin, limit: int, good_count: int, avoid_count: int
) -> None:
    write_candidates(deeptwin)

    composed = compose(
        make_skill(budget={"examples": limit}), make_task(), deeptwin, context=CONTEXT
    )

    good, avoid = drawn("task-0001", GOOD), drawn("task-0001", AVOID)
    assert composed.injected == [*good[:good_count], *avoid[:avoid_count]]
    assert reasons(composed) == [(i, "budget") for i in (*good[good_count:], *avoid[avoid_count:])]
    assert ("이렇게 쓴다" in composed.guide) == (good_count > 0)
    assert ("이렇게는 쓰지 않는다" in composed.guide) == (avoid_count > 0)
    if not good_count:
        assert composed.guide == ""


@pytest.mark.parametrize(
    ("limit", "goods"),
    [(1, []), (2, ["ex-0001"]), (2, [])],
    ids=["cap-1-no-good", "cap-2-one-good", "cap-2-no-good"],
)
def test_good_shortfall_leaves_room_for_avoid(
    deeptwin: DeepTwin, limit: int, goods: list[str]
) -> None:
    write_examples(
        deeptwin,
        [*(example(i) for i in goods), *(example(i, kind="avoid") for i in AVOID)],
    )

    composed = compose(
        make_skill(budget={"examples": limit}), make_task(), deeptwin, context=CONTEXT
    )

    avoid = drawn("task-0001", AVOID)
    assert composed.injected == [*goods, avoid[0]]
    # avoid는 한 지침에 하나까지라 남은 avoid 하나만 budget이다
    assert reasons(composed) == [(avoid[1], "budget")]
    assert "이렇게는 쓰지 않는다" in composed.guide


def test_examples_follow_cards_in_rejected(deeptwin: DeepTwin) -> None:
    write_cards(deeptwin, [card("card-0001", "opening", "상한으로 빠진다")])
    write_candidates(deeptwin)

    composed = compose_cards(deeptwin, skill=card_skill(cards_per_point=0, examples=1))

    good, avoid = drawn("task-0001", GOOD), drawn("task-0001", AVOID)
    assert composed.injected == [good[0]]
    assert reasons(composed) == [
        ("card-0001", "budget"),
        *((i, "budget") for i in good[1:]),
        *((i, "budget") for i in avoid),
    ]


def test_examples_that_are_not_candidates_change_nothing(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])
    write_examples(
        deeptwin,
        [
            example("ex-0001", grade="usual"),
            example("ex-0002", grade="rushed", kind="avoid"),
            example("ex-0003", kind="pair", text=None, before="전", after="후"),
            example("ex-0004", status="dormant"),
            example("ex-0005", status="candidate", kind="avoid"),
            example("ex-0006", skill="post-writer"),
        ],
    )

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.guide == GUIDE_ONE_PRINCIPLE
    assert composed.injected == ["prin-01"]
    assert composed.rejected == []


@pytest.mark.parametrize("policy", ["similar", "recent"])
def test_example_policy_other_than_random_signature_is_unsupported(
    deeptwin: DeepTwin, policy: str
) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])
    write_candidates(deeptwin)
    skill = make_skill(example_policy=policy)

    with pytest.raises(DeeptwinError) as info:
        compose(skill, make_task(), deeptwin, context=CONTEXT)

    assert info.value.code == "unsupported_example_policy"
    assert info.value.message == (
        f"스킬 minimal의 example_policy는 아직 만들지 않은 방식입니다: {policy}. "
        "쓸 수 있는 값: random_signature"
    )
    # 예시를 빼면 정책을 보지 않는다
    composed = compose(skill, make_task(), deeptwin, context=CONTEXT, ablate=("instinct",))
    assert composed.guide == GUIDE_ONE_PRINCIPLE
    assert composed.injected == ["prin-01"]


# ablate


def test_ablate_tendency_leaves_cards_out_and_no_hit_empty(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])
    write_cards(deeptwin, [card("card-0001", "opening", "들어가지 않는다")])

    composed = compose_cards(deeptwin, skill=card_skill(cards_total=0), ablate=("tendency",))

    assert composed.guide == GUIDE_ONE_PRINCIPLE
    assert composed.injected == ["prin-01"]
    assert composed.rejected == []
    assert composed.no_hit == []
    assert composed.conflicts == []


def test_ablate_instinct_leaves_examples_out(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])
    write_candidates(deeptwin)

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT, ablate=("instinct",))

    assert composed.guide == GUIDE_ONE_PRINCIPLE
    assert composed.injected == ["prin-01"]
    assert composed.rejected == []


@pytest.mark.parametrize(
    ("ablate", "names"),
    [
        (("examples",), "examples"),
        (("instinct", "cards", "examples", "cards"), "cards, examples"),
    ],
    ids=["one", "several"],
)
def test_unknown_layer_name_is_rejected(
    deeptwin: DeepTwin, ablate: tuple[str, ...], names: str
) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])

    with pytest.raises(DeeptwinError) as info:
        compose(make_skill(), make_task(), deeptwin, context=CONTEXT, ablate=ablate)

    assert info.value.code == "unknown_layer"
    assert info.value.message == (
        f"알 수 없는 층입니다: {names}. 쓸 수 있는 이름: instinct, tendency, priority, principle"
    )


def layer_items(deeptwin: DeepTwin) -> dict[str, list[tuple[str, list[str]]]]:
    """층 이름 -> (항목 ID, 그 항목이 지침에 쓰일 수 있는 글의 줄들)."""

    def lines(*texts: str | None) -> list[str]:
        return [
            line.strip() for text in texts for line in (text or "").splitlines() if line.strip()
        ]

    return {
        "instinct": [(e.id, lines(e.text, e.before, e.after)) for e in deeptwin.examples()],
        "tendency": [(c.id, lines(c.choose, c.because, c.except_)) for c in deeptwin.cards()],
        "priority": [(p.id, lines(p.rule)) for p in deeptwin.priorities()],
        "principle": [(p.id, lines(p.rule)) for p in deeptwin.principles()],
    }


@pytest.mark.acceptance
@pytest.mark.parametrize("layer", ["instinct", "tendency", "priority", "principle"])
def test_ablated_layer_leaves_none_of_its_items(rules_copy: Path, layer: str) -> None:
    """설계서 8.11 수용 테스트 6: `ablate`에 준 계층의 항목은 지침에 하나도 들어가지 않는다."""
    deeptwin = DeepTwin.open(rules_copy)
    skill, task = deeptwin.skill("class-notice"), deeptwin.task("task-0001")
    items = layer_items(deeptwin)
    ids = {item_id for item_id, _ in items[layer]}
    texts = [line for _, lines in items[layer] for line in lines]

    full = compose(skill, task, deeptwin, context=task.context or {})
    ablated = compose(skill, task, deeptwin, context=task.context or {}, ablate=(layer,))

    # 네 층 모두 빼지 않으면 지침에 들어가는 항목이 있다
    assert ids & set(full.injected)
    assert any(text in full.guide for text in texts)
    assert not ids & set(ablated.injected)
    assert not ids & {r.id for r in ablated.rejected}
    assert [text for text in texts if text in ablated.guide] == []
    # 다른 층은 그대로다
    assert ablated.injected == [i for i in full.injected if i not in ids]
    assert ablated.rejected == [r for r in full.rejected if r.id not in ids]


# 7단계: 표기


GUIDE_ALL_LAYERS = """\
## 이번 작업의 개인 기준

반드시 지킬 것
- 수치를 부풀리지 않는다

부딪칠 때의 순서
1. 정확함이 재미보다 먼저다
2. 빠짐없음이 짧음보다 먼저다

판단 지점별 기준
- [첫 문장] 첫 문장은 질문이 아니라 숫자가 든 단정문으로 쓴다.
  이유: 질문형 첫 문장은 넘겨 읽힌다고 본다. 예외: 후기 글은 인용문으로 시작해도 된다.
- [첫 문장] 첫 문장에서 문의에 고맙다고 한다!
- [답] 모르는 것은 모른다고 쓴다.
  예외: 수강료처럼 공개된 것은 바로 답한다.
- [답] 확인할 날짜를 적는다?
  이유: 기다리는 사람은 언제까지인지 궁금해한다고 본다.
"""


def test_guide_renders_every_layer_in_the_fixed_template(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])
    write_priorities(
        deeptwin,
        [
            priority("pri-01", "정확함이 재미보다 먼저다"),
            priority("pri-02", "빠짐없음이 짧음보다 먼저다"),
        ],
    )
    write_cards(
        deeptwin,
        [
            card(
                "card-0001",
                "opening",
                "첫 문장은 질문이 아니라 숫자가 든 단정문으로 쓴다",
                when={"purpose": ["문의"]},
                because="질문형 첫 문장은 넘겨 읽힌다고 본다",
                **{"except": "후기 글은 인용문으로 시작해도 된다."},
            ),
            card("card-0002", "opening", "첫 문장에서 문의에 고맙다고 한다!"),
            card(
                "card-0003",
                "answer",
                "모르는 것은 모른다고 쓴다.",
                when={"purpose": ["문의"]},
                **{"except": "수강료처럼 공개된 것은 바로 답한다"},
            ),
            card(
                "card-0004",
                "answer",
                "확인할 날짜를 적는다?",
                because="기다리는 사람은 언제까지인지 궁금해한다고 본다",
            ),
        ],
    )

    composed = compose_cards(deeptwin)

    assert composed.guide == GUIDE_ALL_LAYERS
    assert composed.injected == [
        "prin-01",
        "pri-01",
        "pri-02",
        "card-0001",
        "card-0002",
        "card-0003",
        "card-0004",
    ]
    assert composed.no_hit == ["tone"]


def test_block_scalar_and_multi_line_text_render_as_one_line(deeptwin: DeepTwin) -> None:
    (deeptwin.path / "layers" / "principles.yaml").write_text(
        "- schema: 1\n"
        "  id: prin-01\n"
        "  rule: |\n"
        "    수치를 부풀리지 않는다\n"
        "  kind: never\n"
        "  status: active\n"
        "  approval: human\n",
        encoding="utf-8",
    )
    (deeptwin.path / "layers" / "priorities.yaml").write_text(
        "- schema: 1\n"
        "  id: pri-01\n"
        "  rule: |\n"
        "    정확함이\n"
        "    재미보다 먼저다\n"
        "  status: active\n"
        "  approval: human\n",
        encoding="utf-8",
    )
    (deeptwin.path / "layers" / "cards" / "card-0001.yaml").write_text(
        "schema: 1\n"
        "id: card-0001\n"
        "skill: minimal\n"
        "decision_point: opening\n"
        "status: active\n"
        "approval: human\n"
        "choose: |\n"
        "  첫 문장은 질문이 아니라\n"
        "\n"
        "    숫자가 든 단정문으로 쓴다\n"
        "because: |\n"
        "  질문형 첫 문장은 넘겨 읽힌다고 본다\n"
        "except: |+\n"
        "  후기 글은 인용문으로 시작해도 된다!\n"
        "\n",
        encoding="utf-8",
    )
    [loaded] = deeptwin.cards()
    assert loaded.because == "질문형 첫 문장은 넘겨 읽힌다고 본다\n"

    composed = compose_cards(deeptwin)

    assert composed.guide == (
        "## 이번 작업의 개인 기준\n\n"
        "반드시 지킬 것\n- 수치를 부풀리지 않는다\n\n"
        "부딪칠 때의 순서\n1. 정확함이 재미보다 먼저다\n\n"
        "판단 지점별 기준\n"
        "- [첫 문장] 첫 문장은 질문이 아니라 숫자가 든 단정문으로 쓴다.\n"
        "  이유: 질문형 첫 문장은 넘겨 읽힌다고 본다. 예외: 후기 글은 인용문으로 시작해도 된다!\n"
    )


def test_whitespace_only_because_is_left_out(deeptwin: DeepTwin) -> None:
    write_cards(deeptwin, [card("card-0001", "tone", "존댓말로 쓴다", because="\n  ")])

    composed = compose_cards(deeptwin)

    assert (
        composed.guide == "## 이번 작업의 개인 기준\n\n판단 지점별 기준\n- [말투] 존댓말로 쓴다.\n"
    )


def test_cards_only_guide_has_no_empty_sections(deeptwin: DeepTwin) -> None:
    write_cards(deeptwin, [card("card-0001", "tone", "존댓말로 쓴다")])

    composed = compose_cards(deeptwin)

    assert (
        composed.guide == "## 이번 작업의 개인 기준\n\n판단 지점별 기준\n- [말투] 존댓말로 쓴다.\n"
    )


GUIDE_WITH_EXAMPLES = """\
## 이번 작업의 개인 기준

반드시 지킬 것
- 수치를 부풀리지 않는다

부딪칠 때의 순서
1. 정확함이 재미보다 먼저다

판단 지점별 기준
- [첫 문장] 첫 문장에 휴강 날짜를 쓴다.

이렇게 쓴다
보강은 다음 주 화요일 저녁 7시입니다.
자리는 그대로 두었습니다.

---

휴강 소식을 먼저 알리고,
보강 날짜를 바로 뒤에 씁니다.

이렇게는 쓰지 않는다
갑작스럽게 죄송합니다!!! 사정이 생겨서요…
"""


def test_examples_follow_cards_in_the_fixed_template(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])
    write_priorities(deeptwin, [priority("pri-01", "정확함이 재미보다 먼저다")])
    write_cards(deeptwin, [card("card-0001", "opening", "첫 문장에 휴강 날짜를 쓴다")])
    write_examples(
        deeptwin,
        [
            example("ex-0001", text="휴강 소식을 먼저 알리고,\n보강 날짜를 바로 뒤에 씁니다.\n"),
            example(
                "ex-0002", text="보강은 다음 주 화요일 저녁 7시입니다.\n자리는 그대로 두었습니다.\n"
            ),
            example("ex-0003", kind="avoid", text="갑작스럽게 죄송합니다!!! 사정이 생겨서요…\n"),
        ],
    )
    assert drawn("task-0001", ["ex-0001", "ex-0002"]) == ["ex-0002", "ex-0001"]

    composed = compose_cards(deeptwin)

    assert composed.guide == GUIDE_WITH_EXAMPLES
    assert composed.injected == ["prin-01", "pri-01", "card-0001", "ex-0002", "ex-0001", "ex-0003"]


def test_example_text_keeps_inner_lines_and_drops_edge_blank_lines(deeptwin: DeepTwin) -> None:
    text = "\n  \n  들여 쓴 첫 줄  \n둘째 줄\t\n\n\n넷째 줄 \n \n\n"
    write_examples(deeptwin, [example("ex-0001", text=text)])
    [loaded] = deeptwin.examples()
    assert loaded.text == text

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.guide == (
        "## 이번 작업의 개인 기준\n\n이렇게 쓴다\n  들여 쓴 첫 줄\n둘째 줄\n\n\n넷째 줄\n"
    )


def test_example_from_a_yaml_block_drops_its_final_newline(deeptwin: DeepTwin) -> None:
    (deeptwin.path / "layers" / "examples" / "ex-0001.yaml").write_text(
        "schema: 1\n"
        "id: ex-0001\n"
        "skill: minimal\n"
        "kind: good\n"
        "grade: signature\n"
        "status: active\n"
        "approval: human\n"
        "text: |+\n"
        "  첫 줄\n"
        "\n"
        "  셋째 줄\n"
        "\n"
        "\n",
        encoding="utf-8",
    )

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.guide == "## 이번 작업의 개인 기준\n\n이렇게 쓴다\n첫 줄\n\n셋째 줄\n"


# 같은 입력


@pytest.mark.acceptance
def test_same_input_gives_same_guide_and_hash(deeptwin: DeepTwin) -> None:
    """설계서 8.11 수용 테스트 1: 같은 입력으로 두 번 조립하면 `guide_hash`가 같다."""
    write_principles(
        deeptwin,
        [principle("prin-01", "수치를 부풀리지 않는다"), principle("prin-02", "약속하지 않는다")],
    )
    write_priorities(deeptwin, [priority("pri-01", "정확함이 재미보다 먼저다")])
    write_cards(
        deeptwin,
        [
            card("card-0001", "opening", "고맙다고 한다", when={"purpose": ["문의"]}),
            card("card-0002", "opening", "날짜부터 쓴다"),
            card("card-0003", "opening", "상한으로 빠진다"),
            card("card-0004", "answer", "동점 하나", conflicts_with=["card-0005"]),
            card("card-0005", "answer", "동점 둘"),
        ],
    )
    skill = card_skill(cards_per_point=2)

    first = compose_cards(deeptwin, skill=skill)
    second = compose_cards(deeptwin, skill=skill)

    assert first.guide == second.guide
    assert first.guide_hash == second.guide_hash
    assert first == second
    assert reasons(first) == [
        ("card-0004", "conflict"),
        ("card-0005", "conflict"),
        ("card-0003", "budget"),
    ]
    assert first.conflicts == [["card-0004", "card-0005"]]


def test_fixture_composes_with_every_rule(rules_copy: Path) -> None:
    deeptwin = DeepTwin.open(rules_copy)
    task = deeptwin.task("task-0001")

    composed = compose(deeptwin.skill("class-notice"), task, deeptwin, context=task.context or {})

    good = drawn("task-0001", ["ex-0001", "ex-0002", "ex-0003"])
    avoid = drawn("task-0001", ["ex-0004", "ex-0005"])
    assert (good, avoid) == (["ex-0003", "ex-0002", "ex-0001"], ["ex-0005", "ex-0004"])
    assert composed.injected == [
        "prin-01",
        "prin-02",
        "pri-01",
        "pri-02",
        "card-0002",
        "card-0001",
        "card-0004",
        *good[:2],
        avoid[0],
    ]
    assert reasons(composed) == [
        ("card-0008", "lower_layer"),
        ("card-0005", "conflict"),
        ("card-0007", "budget"),
        ("card-0003", "budget"),
        (good[2], "budget"),
        (avoid[1], "budget"),
    ]
    assert composed.no_hit == ["schedule"]
    assert composed.conflicts == []


SKILL_MD = f"# 문의 답변\n\n절차를 따른다.\n\n{FLUID_OPEN}\n{FLUID_CLOSE}\n\n맺음말.\n"


def test_fill_fluid_puts_guide_between_markers() -> None:
    filled = fill_fluid(SKILL_MD, GUIDE_ONE_PRINCIPLE)

    assert filled == (
        f"# 문의 답변\n\n절차를 따른다.\n\n{FLUID_OPEN}\n"
        f"{GUIDE_ONE_PRINCIPLE}{FLUID_CLOSE}\n\n맺음말.\n"
    )


def test_fill_fluid_replaces_what_was_there() -> None:
    once = fill_fluid(SKILL_MD, GUIDE_ONE_PRINCIPLE)

    assert fill_fluid(once, GUIDE_ONE_PRINCIPLE) == once
    assert fill_fluid(once, "") == SKILL_MD


@pytest.mark.parametrize(
    "skill_md",
    [
        "# 표시가 없다\n",
        f"# 여는 표시만 있다\n{FLUID_OPEN}\n",
        f"# 닫는 표시만 있다\n{FLUID_CLOSE}\n",
        f"# 순서가 거꾸로다\n{FLUID_CLOSE}\n{FLUID_OPEN}\n",
        f"# 두 번 있다\n{FLUID_OPEN}\n{FLUID_CLOSE}\n{FLUID_OPEN}\n{FLUID_CLOSE}\n",
    ],
)
def test_fill_fluid_needs_one_marker_pair(skill_md: str) -> None:
    with pytest.raises(DeeptwinError) as info:
        fill_fluid(skill_md, GUIDE_ONE_PRINCIPLE)

    assert info.value.code == "fluid_marker_missing"


def test_yaml_keeps_korean_and_key_order(tmp_path: Path) -> None:
    path = tmp_path / "principles.yaml"
    items = [principle("prin-01", "수치를 부풀리지 않는다")]

    write_yaml(path, items)

    text = path.read_text(encoding="utf-8")
    assert "rule: 수치를 부풀리지 않는다" in text
    assert text.index("schema:") < text.index("id:") < text.index("rule:")
    assert read_yaml(path) == items
    assert [p.name for p in tmp_path.iterdir()] == ["principles.yaml"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX 권한 비트")
def test_write_keeps_existing_mode_and_new_files_follow_umask(tmp_path: Path) -> None:
    existing = tmp_path / "existing.txt"
    existing.write_text("전", encoding="utf-8")
    existing.chmod(0o640)
    umask = os.umask(0o022)
    try:
        write_text(existing, "후")
        write_text(tmp_path / "new.txt", "새 파일")
    finally:
        os.umask(umask)

    assert stat.S_IMODE(existing.stat().st_mode) == 0o640
    assert existing.read_text(encoding="utf-8") == "후"
    assert stat.S_IMODE((tmp_path / "new.txt").stat().st_mode) == 0o644
    assert sorted(p.name for p in tmp_path.iterdir()) == ["existing.txt", "new.txt"]


def test_principle_reads_schema_alias() -> None:
    item = Principle.model_validate(principle("prin-01", "수치를 부풀리지 않는다", x_note="확장"))

    assert item.schema_ == 1
    assert item.model_dump(by_alias=True)["schema"] == 1
    assert item.model_dump()["x_note"] == "확장"
