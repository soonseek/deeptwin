"""무작위로 만든 계층으로 조립 규칙의 성질을 확인한다(설계서 9.8, `hypothesis`).

예마다 무작위 원칙, 우선순위, 카드, 예시, 상한, 맥락, 뺄 층으로 조립해 아래 넷을 본다.

1. 상한을 넘지 않는다. 원칙이나 우선순위가 상한을 넘을 때만 `over_budget`이 난다.
2. 같은 입력으로 두 번 조립하면 `Composed`가 같다.
3. 뺀 층의 항목은 `injected`, `rejected`, 지침 글에 없다.
4. 2단계에서 맞은 카드와 예시 후보는 모두 `injected`나 `rejected` 가운데 정확히 한 곳에 있다.

항목마다 글에 `«ID»`를 넣는다. 다른 글에는 `«`와 `»`가 없으므로, 지침에 `«ID»`가 있으면
그 항목이 지침에 들어간 것이다.

`derandomize=True`라 돌 때마다 같은 예를 만든다(CI에서도 같다). 함수 범위 fixture
(`tmp_path`)는 `hypothesis`와 함께 쓰면 HealthCheck에 걸리므로, 예마다 `tempfile`로 폴더를
만든다. 넷을 한 테스트에서 함께 보는 것은 파일을 쓰는 데 드는 시간을 한 번만 쓰고 예를 더
많이 돌리려는 것이다.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from deeptwin.compose import compose
from deeptwin.errors import OverBudgetError
from deeptwin.models import Card, Composed, Context, Example, Principle, Priority, Skill, Task
from deeptwin.store.project import DeepTwin

SKILL_ID = "prop-skill"
OTHER_SKILL = "other-skill"
AXES = {"purpose": ["모집", "알림", "휴강"], "channel": ["instagram", "email"]}
POINT_IDS = ("opening", "schedule", "tone")
LAYERS = ("instinct", "tendency", "priority", "principle")
TASK_IDS = ("task-0001", "task-0002", "task-0003")

# 고를 대상과 상한에 걸리는 경우가 자주 생기도록 맞는 값 쪽으로 기울인다.
# sampled_from은 앞의 값 쪽으로 줄여 가므로 넉넉한 기본값을 앞에 둔다
STATUSES = st.sampled_from(["active"] * 5 + ["dormant", "candidate", "retired"])
SKILLS = st.sampled_from([SKILL_ID] * 5 + [OTHER_SKILL])
SCOPES = st.sampled_from([[], [], [SKILL_ID], [OTHER_SKILL], [OTHER_SKILL, SKILL_ID]])
GRADES = st.sampled_from(["signature"] * 4 + ["usual", "rushed"])
EXAMPLE_KINDS = st.sampled_from(["good", "avoid"] * 2 + ["pair"])
BODY = st.text(alphabet="가나다 .\n", max_size=8)
"""항목 글의 나머지. 앞뒤 공백, 빈 줄, 여러 줄이 섞인다."""


def token(item_id: str) -> str:
    return f"«{item_id}»"


@dataclass(frozen=True)
class World:
    """조립 한 번의 입력: 스킬, 과제(맥락을 담는다), 네 층의 항목, 뺄 층."""

    skill: Skill
    task: Task
    principles: list[Principle]
    priorities: list[Priority]
    cards: list[Card]
    examples: list[Example]
    ablate: tuple[str, ...]

    @property
    def context(self) -> Context:
        return self.task.context or {}


@st.composite
def worlds(draw: st.DrawFn) -> World:
    points = [
        {"id": point, "name": f"지점 {n}", "weight": draw(st.integers(0, 2))}
        for n, point in enumerate(POINT_IDS[: draw(st.integers(1, len(POINT_IDS)))])
    ]
    point_ids = [p["id"] for p in points]
    budget = {
        "examples": draw(st.sampled_from([3, 1, 2, 5, 0, -1])),
        "cards_per_point": draw(st.sampled_from([2, 1, 3, 0, -1])),
        "cards_total": draw(st.sampled_from([7, 4, 3, 2, 1, 0, -1])),
        "principles_max": draw(st.sampled_from([10, 3, 2, 1, 0])),
        "priorities_max": draw(st.sampled_from([5, 3, 2, 1, 0])),
    }
    skill = Skill.model_validate(
        {
            "id": SKILL_ID,
            "skill_md": Path("skills") / SKILL_ID / "SKILL.md",
            "decision_points": points,
            "context_axes": AXES,
            "budget": budget,
        }
    )
    context = {
        axis: value
        for axis, values in AXES.items()
        if (value := draw(st.sampled_from([*values, None]))) is not None
    }
    task = Task(
        id=draw(st.sampled_from(TASK_IDS)),
        skill=SKILL_ID,
        split="train",
        input="과제",
        context=context,
    )

    principle_ids = [f"prin-{n:02d}" for n in range(draw(st.integers(0, 4)))]
    priority_ids = [f"pri-{n:02d}" for n in range(draw(st.integers(0, 4)))]
    card_ids = [f"card-{n:04d}" for n in range(draw(st.integers(2, 12)))]
    example_ids = [f"ex-{n:04d}" for n in range(draw(st.integers(2, 12)))]
    conflict_pool = [*card_ids, *principle_ids, *priority_ids, "card-9999"]

    def ruled(item_id: str, **fields: Any) -> dict[str, Any]:
        return {
            "id": item_id,
            "rule": token(item_id) + draw(BODY),
            "scope": draw(SCOPES),
            "status": draw(STATUSES),
            "approval": "human",
            **fields,
        }

    def when() -> dict[str, list[str]]:
        """축마다 적지 않거나, 빈 목록이거나, 그 축의 값 몇 개다. 스킬에 없는 축도 가끔 적는다."""
        axes = {**AXES, "audience": ["입문자"]}
        found: dict[str, list[str]] = {}
        for axis, values in axes.items():
            if draw(
                st.sampled_from([False, False, True] if axis in AXES else [False] * 5 + [True])
            ):
                found[axis] = draw(st.lists(st.sampled_from(values), unique=True))
        return found

    def card(item_id: str) -> Card:
        injected = draw(st.integers(0, 3))
        return Card.model_validate(
            {
                "id": item_id,
                "skill": draw(SKILLS),
                "decision_point": draw(st.sampled_from([*point_ids * 3, "hashtags"])),
                "status": draw(STATUSES),
                "approval": "human",
                "when": when(),
                "choose": token(item_id) + draw(BODY),
                "because": draw(st.none() | BODY),
                "except": draw(st.none() | BODY),
                "conflicts_with": draw(st.lists(st.sampled_from(conflict_pool), max_size=2)),
                "stats": {
                    "injected": injected,
                    "agreed": draw(st.integers(0, injected + 1)),
                    "last_used": draw(
                        st.none() | st.sampled_from([date(2026, 11, 1), date(2026, 11, 20)])
                    ),
                },
            }
        )

    def example(item_id: str) -> Example:
        kind = draw(EXAMPLE_KINDS)
        body = (
            {"before": token(item_id) + draw(BODY), "after": token(item_id) + draw(BODY)}
            if kind == "pair"
            else {"text": draw(BODY) + token(item_id) + draw(BODY)}
        )
        return Example.model_validate(
            {
                "id": item_id,
                "skill": draw(SKILLS),
                "kind": kind,
                "grade": draw(GRADES),
                "status": draw(STATUSES),
                "approval": "human",
                **body,
            }
        )

    return World(
        skill=skill,
        task=task,
        principles=[
            Principle.model_validate(ruled(i, kind=draw(st.sampled_from(["must", "never"]))))
            for i in principle_ids
        ],
        priorities=[Priority.model_validate(ruled(i)) for i in priority_ids],
        cards=[card(i) for i in card_ids],
        examples=[example(i) for i in example_ids],
        ablate=tuple(draw(st.lists(st.sampled_from(LAYERS), max_size=3))),
    )


def compose_twice(world: World) -> tuple[Composed, Composed] | None:
    """`world`를 새 폴더에 쓰고 같은 입력으로 두 번 조립한다.

    `over_budget`이면 `None`이다. 다른 오류는 그대로 올라가 테스트가 실패한다.
    """
    with tempfile.TemporaryDirectory() as tmp:
        deeptwin = DeepTwin.init(Path(tmp)).deeptwin
        deeptwin.write_principles(world.principles)
        deeptwin.write_priorities(world.priorities)
        for card in world.cards:
            deeptwin.write_card(card)
        for example in world.examples:
            deeptwin.write_example(example)
        options: dict[str, Any] = {"context": world.context, "ablate": world.ablate}
        try:
            first = compose(world.skill, world.task, deeptwin, **options)
        except OverBudgetError:
            return None
        return first, compose(world.skill, world.task, deeptwin, **options)


# 테스트 쪽에서 따로 계산한 기대값


def in_scope(world: World, items: Sequence[Principle | Priority]) -> list[str]:
    return [
        i.id for i in items if i.status == "active" and (not i.scope or world.skill.id in i.scope)
    ]


def over_budget(world: World) -> bool:
    budget = world.skill.budget
    principles = "principle" not in world.ablate and (
        len(in_scope(world, world.principles)) > budget.principles_max
    )
    priorities = "priority" not in world.ablate and (
        len(in_scope(world, world.priorities)) > budget.priorities_max
    )
    return principles or priorities


def matched_cards(world: World) -> set[str]:
    """2단계에서 맞는 카드: 이 스킬의 `active` 카드, 판단 지점이 스킬에 있고 `when`이 맞는다."""
    points = {p.id for p in world.skill.decision_points}
    return {
        c.id
        for c in world.cards
        if c.skill == world.skill.id
        and c.status == "active"
        and c.decision_point in points
        and all(not values or world.context.get(axis) in values for axis, values in c.when.items())
    }


def example_candidates(world: World) -> set[str]:
    return {
        e.id
        for e in world.examples
        if e.skill == world.skill.id
        and e.status == "active"
        and e.grade == "signature"
        and e.kind in ("good", "avoid")
    }


def layer_of(world: World) -> dict[str, str]:
    """항목 ID -> 층 이름."""
    return {
        **{p.id: "principle" for p in world.principles},
        **{p.id: "priority" for p in world.priorities},
        **{c.id: "tendency" for c in world.cards},
        **{e.id: "instinct" for e in world.examples},
    }


# 성질


def check_caps(world: World, composed: Composed) -> None:
    """1. 판단 지점마다의 카드, 전체 카드, 예시 수와 good·avoid 수, 원칙, 우선순위."""
    budget = world.skill.budget
    cards = {c.id: c for c in world.cards}
    examples = {e.id: e for e in world.examples}
    layers = layer_of(world)
    per_point = Counter(cards[i].decision_point for i in composed.injected if i in cards)
    kinds = Counter(examples[i].kind for i in composed.injected if i in examples)
    per_layer = Counter(layers[i] for i in composed.injected)
    assert max(per_point.values(), default=0) <= max(0, budget.cards_per_point)
    assert per_point.total() <= max(0, budget.cards_total)
    assert kinds.total() <= max(0, budget.examples)
    assert kinds["good"] <= 2
    assert kinds["avoid"] <= 1
    assert kinds["pair"] == 0
    assert per_layer["principle"] <= budget.principles_max
    assert per_layer["priority"] <= budget.priorities_max
    # 예시를 budget으로 뺐다면 전체 상한이나 그 종류의 최대 수가 찼다
    kind_max = {"good": 2, "avoid": 1}
    for r in composed.rejected:
        if r.id in examples:
            kind = examples[r.id].kind
            assert r.reason == "budget"
            assert kinds[kind] == kind_max[kind] or kinds.total() == max(0, budget.examples)


def check_ablated(world: World, composed: Composed) -> None:
    """3. 뺀 층의 항목은 어디에도 없다. 지침 글에 든 항목은 정확히 `injected`의 항목이다."""
    layers = layer_of(world)
    rejected = {r.id for r in composed.rejected}
    for item_id, layer in layers.items():
        if layer in world.ablate:
            assert item_id not in composed.injected
            assert item_id not in rejected
            assert token(item_id) not in composed.guide
    assert {i for i in layers if token(i) in composed.guide} == set(composed.injected)


def check_one_place(world: World, composed: Composed) -> None:
    """4. 맞은 카드와 예시 후보는 `injected`와 `rejected`를 통틀어 한 번씩 나온다."""
    placed = Counter([*composed.injected, *(r.id for r in composed.rejected)])
    cards = matched_cards(world) if "tendency" not in world.ablate else set()
    examples = example_candidates(world) if "instinct" not in world.ablate else set()
    assert {i for i in placed if i.startswith("card-")} == cards
    assert {i for i in placed if i.startswith("ex-")} == examples
    assert set(placed.values()) <= {1}


@settings(derandomize=True, max_examples=300, deadline=None)
@given(worlds())
def test_compose_rules_hold_for_random_layers(world: World) -> None:
    result = compose_twice(world)

    # 1. 원칙이나 우선순위가 상한을 넘을 때만 over_budget이다
    assert (result is None) == over_budget(world)
    if result is None:
        return
    first, second = result
    check_caps(world, first)
    # 2. 같은 입력이면 같은 결과다
    assert first == second
    check_ablated(world, first)
    check_one_place(world, first)
