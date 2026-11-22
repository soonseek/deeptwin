"""유동 지침 조립: 맥락 검사, 고르기, 점수, 충돌, 상한, 예시, 표기(설계서 8.6).

모델을 부르지 않는다(`deeptwin.llm`을 import하지 않는다). 같은 입력이면 같은 지침과
같은 `guide_hash`를 낸다. 예시를 뽑는 무작위 순서도 과제 ID로 정해진다. 평가의 바탕+예시는
6단계만 바꿔(`example_pick="past_work"`) 가져온 대표작 3개를 넣는다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal, TypeAlias, TypeVar, get_args

from deeptwin.errors import (
    FluidMarkerMissingError,
    InvalidContextError,
    NotEnoughExamplesError,
    OverBudgetError,
    UnknownLayerError,
    UnsupportedExamplePolicyError,
)

# 유동 영역 표시는 저장 계층(스킬 뼈대)도 쓰므로 `models`에 두고 여기서 다시 내보낸다
from deeptwin.models import FLUID_CLOSE as FLUID_CLOSE
from deeptwin.models import FLUID_OPEN as FLUID_OPEN
from deeptwin.models import (
    Card,
    Composed,
    Context,
    Example,
    Layer,
    Principle,
    Priority,
    Rejected,
    Skill,
    Task,
)
from deeptwin.store.project import DATA_DIR, PRINCIPLES_FILE, PRIORITIES_FILE, DeepTwin

__all__ = [
    "FLUID_CLOSE",
    "FLUID_OPEN",
    "LAYERS",
    "ExamplePick",
    "check_context",
    "compose",
    "fill_fluid",
]

GUIDE_TITLE = "## 이번 작업의 개인 기준"
PRINCIPLES_HEADING = "반드시 지킬 것"
PRIORITIES_HEADING = "부딪칠 때의 순서"
CARDS_HEADING = "판단 지점별 기준"
GOOD_EXAMPLES_HEADING = "이렇게 쓴다"
AVOID_EXAMPLES_HEADING = "이렇게는 쓰지 않는다"
EXAMPLE_SEPARATOR = "---"
"""한 섹션 안 두 예시 사이에 두는 줄. 앞뒤에 빈 줄이 하나씩 있다."""

LAYERS: tuple[str, ...] = get_args(Layer)
"""`ablate`에 줄 수 있는 층 이름: 본능(예시), 경향(카드), 우선순위, 원칙."""

GOOD_EXAMPLES_MAX = 2
AVOID_EXAMPLES_MAX = 1
"""한 지침에 넣는 good, avoid 예시의 최대 수. `budget.examples`가 이보다 커도 늘지 않는다."""

ExamplePick: TypeAlias = Literal["policy", "past_work"]
"""6단계(예시)를 고르는 방식. `policy`는 스킬의 `example_policy`(`random_signature`)를 따르고,
`past_work`는 가져온 대표작 good만 `PAST_WORK_EXAMPLES`개 넣는다(평가의 바탕+예시)."""
_EXAMPLE_PICKS: tuple[str, ...] = get_args(ExamplePick)

PAST_WORK_EXAMPLES = 3
"""`past_work`로 넣는 예시의 수. 후보가 이보다 적으면 `not_enough_examples`다."""

_SENTENCE_ENDS = (".", "?", "!")

_Ruled = TypeVar("_Ruled", Principle, Priority)
_Score = tuple[int, Fraction, int]
"""카드의 점수: (맞은 축의 수, 일치율, `last_used`의 서수). 클수록 먼저다."""


def compose(
    skill: Skill,
    task: Task,
    deeptwin: DeepTwin,
    *,
    context: Context,
    ablate: tuple[str, ...] = (),
    example_pick: ExamplePick = "policy",
) -> Composed:
    """스킬의 유동 영역에 넣을 지침을 조립한다.

    1. 원칙과 우선순위: `active`이고 `scope`가 비었거나 이 스킬을 담은 것을 파일 순서대로
       모두 넣는다. 상한을 넘으면 자르지 않고 `over_budget`이다.
    2. 카드 후보: 판단 지점마다 `active`이고 `when`이 맥락과 맞는 카드를 모은다.
    3. 점수: (맞은 축의 수, 일치율, `last_used`) 순으로 높은 쪽이 먼저, 같으면 `id` 순이다.
    4. 충돌: 원칙·우선순위와 부딪치는 카드는 `lower_layer`, 카드끼리 부딪치면 낮은 쪽이
       `conflict`다. 점수가 같으면 둘 다 빼고 `conflicts`에 적는다.
    5. 상한: 판단 지점마다 `cards_per_point`장, 전체 `cards_total`장까지다.
    6. 예시(`random_signature`): 이 스킬의 `active` 대표작 가운데 good 둘과 avoid 하나를
       과제 ID로 정해지는 순서로 뽑는다. `budget.examples`가 전체 상한이고 avoid부터 줄인다.
    7. 표기: 원칙, 우선순위, 판단 지점별 카드, 예시 순으로 고정 틀에 쓴다.

    `ablate`에 든 층(`instinct`, `tendency`, `priority`, `principle`)은 고르지도 상한을
    검사하지도 않는다. 네 이름이 아닌 것이 있으면 `unknown_layer`다.
    맥락의 축과 값이 스킬의 `context_axes`에 없으면 `invalid_context`다.
    예시를 빼지 않았는데 `example_policy`가 `random_signature`가 아니면
    `unsupported_example_policy`다.

    `example_pick`이 `past_work`면 6단계만 바뀐다(`_pick_past_work`). 이 스킬의 `active` 예시
    가운데 `source: past_work`, `grade: signature`, `kind: good`인 것을 뽑기 순서로 줄 세워 앞의
    `PAST_WORK_EXAMPLES`개를 "이렇게 쓴다"에 넣고, 남은 후보는 `budget`으로 적는다. avoid는 넣지
    않고 `budget.examples`와 `example_policy`는 보지 않는다. 후보가 모자라면
    `not_enough_examples`다. `ablate`에 `instinct`가 있으면 `example_pick`은 쓰지 않는다.
    `example_pick`이 두 값이 아니면 `ValueError`다.
    """
    if example_pick not in _EXAMPLE_PICKS:
        names = ", ".join(_EXAMPLE_PICKS)
        raise ValueError(f"example_pick은 {names} 가운데 하나입니다(받은 값: {example_pick!r}).")
    _check_ablate(ablate)
    check_context(skill, context)
    if "instinct" not in ablate and example_pick == "policy":
        _check_example_policy(skill)
    all_principles = deeptwin.principles()
    all_priorities = deeptwin.priorities()

    principles: list[Principle] = []
    if "principle" not in ablate:
        principles = _in_scope(skill, all_principles)
        _check_budget(skill, principles, "principle")
    priorities: list[Priority] = []
    if "priority" not in ablate:
        priorities = _in_scope(skill, all_priorities)
        _check_budget(skill, priorities, "priority")

    cards = _Cards()
    if "tendency" not in ablate:
        lower_ids = {
            item.id for item in (*all_principles, *all_priorities) if item.status == "active"
        }
        cards = _pick_cards(skill, deeptwin.cards(), context, lower_ids)

    examples = _Examples()
    if "instinct" not in ablate:
        if example_pick == "past_work":
            examples = _pick_past_work(skill, task, deeptwin.examples())
        else:
            examples = _pick_examples(skill, task, deeptwin.examples())

    guide = _render(skill, principles, priorities, cards.injected, examples)
    return Composed(
        guide=guide,
        injected=[
            *(p.id for p in principles),
            *(p.id for p in priorities),
            *(c.card.id for c in cards.injected),
            *(e.id for e in examples.injected),
        ],
        rejected=[*cards.rejected, *examples.rejected],
        no_hit=cards.no_hit,
        conflicts=cards.conflicts,
        guide_hash=guide_hash(guide),
    )


def guide_hash(guide: str) -> str:
    return "sha256:" + hashlib.sha256(guide.encode("utf-8")).hexdigest()


def fill_fluid(skill_md: str, guide: str) -> str:
    """`SKILL.md` 글의 유동 영역 표시 쌍 사이를 `guide`로 바꾼 글을 돌려준다.

    표시 쌍 밖의 글은 그대로 둔다. 표시 쌍이 정확히 한 번, 여는 표시가 먼저 있어야 한다.
    """
    opens, closes = skill_md.count(FLUID_OPEN), skill_md.count(FLUID_CLOSE)
    start = skill_md.find(FLUID_OPEN)
    end = skill_md.find(FLUID_CLOSE)
    if opens == 0 or closes == 0 or end < start:
        raise FluidMarkerMissingError(
            f"SKILL.md에 유동 영역 표시 쌍({FLUID_OPEN} … {FLUID_CLOSE})이 없습니다."
        )
    if opens > 1 or closes > 1:
        raise FluidMarkerMissingError(
            f"SKILL.md에 유동 영역 표시 쌍({FLUID_OPEN} … {FLUID_CLOSE})이 두 번 이상 있습니다. "
            "한 번만 두세요."
        )
    head = skill_md[: start + len(FLUID_OPEN)]
    tail = skill_md[end:]
    return f"{head}\n{guide}{tail}"


# 층 이름, 맥락, 예시 정책


def _check_ablate(ablate: Iterable[str]) -> None:
    """`ablate`의 이름이 모두 네 층 가운데 하나인지 본다. 모르는 이름은 받은 순서로 알려 준다."""
    unknown = [name for name in dict.fromkeys(ablate) if name not in LAYERS]
    if unknown:
        raise UnknownLayerError(
            f"알 수 없는 층입니다: {', '.join(unknown)}. 쓸 수 있는 이름: {', '.join(LAYERS)}"
        )


def check_context(skill: Skill, context: Context) -> None:
    """맥락의 축마다 `context_axes`에 있는 축이고 그 목록에 있는 값인지 본다.

    틀린 곳이 있으면 `invalid_context`다. 틀린 곳마다 한 줄씩, 맥락에 적힌 순서로 알려 준다.
    `compose`와 `deeptwin task add`가 쓴다.
    """
    problems: list[str] = []
    for axis, value in context.items():
        allowed = skill.context_axes.get(axis)
        if allowed is None:
            axes = ", ".join(skill.context_axes) or "없음"
            problems.append(
                f"맥락 축이 스킬 {skill.id}의 context_axes에 없습니다: {axis}={value}. "
                f"쓸 수 있는 축: {axes}"
            )
        elif value not in allowed:
            values = ", ".join(allowed) or "없음"
            problems.append(
                f"맥락 값이 스킬 {skill.id}의 context_axes에 없습니다: {axis}={value}. "
                f"{axis}에 쓸 수 있는 값: {values}"
            )
    if problems:
        raise InvalidContextError("\n".join(problems))


def _check_example_policy(skill: Skill) -> None:
    """예시 고르는 방식은 아직 `random_signature`만 있다."""
    if skill.example_policy != "random_signature":
        raise UnsupportedExamplePolicyError(
            f"스킬 {skill.id}의 example_policy는 아직 만들지 않은 방식입니다: "
            f"{skill.example_policy}. 쓸 수 있는 값: random_signature"
        )


# 1단계: 원칙과 우선순위


def _in_scope(skill: Skill, items: Sequence[_Ruled]) -> list[_Ruled]:
    return [i for i in items if i.status == "active" and (not i.scope or skill.id in i.scope)]


_BUDGETS: dict[str, tuple[str, str, str]] = {
    "principle": ("원칙", "principles_max", PRINCIPLES_FILE),
    "priority": ("우선순위", "priorities_max", PRIORITIES_FILE),
}
"""층 -> (메시지에 쓰는 이름, `budget`의 상한 필드, 항목 파일)."""


def _check_budget(
    skill: Skill, items: Sequence[Principle | Priority], layer: Literal["principle", "priority"]
) -> None:
    """범위가 맞는 항목이 상한보다 많으면 자르지 않고 `over_budget`을 낸다."""
    label, name, rel = _BUDGETS[layer]
    limit: int = getattr(skill.budget, name)
    if len(items) > limit:
        raise OverBudgetError(
            f"{label} 상한을 넘었습니다: 스킬 {skill.id}에 맞는 active {label} {len(items)}개, "
            f"{name} {limit}개. 지침을 자르지 않으니 {DATA_DIR}/{rel}의 {label} 항목을 "
            f"합쳐 {limit}개 이하로 줄이세요."
        )


# 2~5단계: 카드


@dataclass(frozen=True)
class _Candidate:
    """맥락과 맞은 카드 하나와 그 점수."""

    card: Card
    point: int
    """판단 지점이 `skill.yaml`에서 몇 번째인지(0부터)."""
    score: _Score


@dataclass
class _Cards:
    injected: list[_Candidate] = field(default_factory=list)
    """넣을 카드. 판단 지점 순, 그 안에서 점수 순이다."""
    rejected: list[Rejected] = field(default_factory=list)
    no_hit: list[str] = field(default_factory=list)
    conflicts: list[list[str]] = field(default_factory=list)


def _pick_cards(
    skill: Skill, cards: Iterable[Card], context: Context, lower_ids: set[str]
) -> _Cards:
    candidates, no_hit = _candidates(skill, cards, context)
    candidates, lower = _split_lower_layer(candidates, lower_ids)
    candidates, conflicted, conflicts = _resolve_conflicts(candidates)
    injected, over = _apply_budget(skill, candidates)
    return _Cards(
        injected=injected,
        rejected=[
            *_rejected(_by_rank(lower), "lower_layer"),
            *_rejected(_by_rank(conflicted), "conflict"),
            *_rejected(_by_rank(over), "budget"),
        ],
        no_hit=no_hit,
        conflicts=conflicts,
    )


def _candidates(
    skill: Skill, cards: Iterable[Card], context: Context
) -> tuple[list[_Candidate], list[str]]:
    """2~3단계. 맞는 카드를 판단 지점 순, 그 안에서 점수 순으로 돌려준다.

    맞는 카드가 하나도 없던 판단 지점의 ID(`skill.yaml` 순)도 함께 돌려준다.
    판단 지점이 `skill.yaml`에 없는 카드와 다른 스킬의 카드는 보지 않는다.
    """
    points = {point.id: index for index, point in enumerate(skill.decision_points)}
    found: list[_Candidate] = []
    for card in cards:
        point = points.get(card.decision_point)
        if card.skill != skill.id or card.status != "active" or point is None:
            continue
        matched = _matched_axes(card, context)
        if matched is not None:
            found.append(_Candidate(card=card, point=point, score=_score(card, matched)))
    found.sort(key=lambda c: (c.point, _rank(c)))
    hit = {c.point for c in found}
    no_hit = [p.id for index, p in enumerate(skill.decision_points) if index not in hit]
    return found, no_hit


def _matched_axes(card: Card, context: Context) -> int | None:
    """`when`이 맥락과 맞으면 맞은 축의 수를, 맞지 않으면 `None`을 돌려준다.

    값 목록이 빈 축은 적지 않은 축처럼 맞는 것으로 보고 수에 넣지 않는다.
    맥락에 없는 축이 적혀 있으면 맞지 않는다.
    """
    matched = 0
    for axis, values in card.when.items():
        if not values:
            continue
        if axis not in context or context[axis] not in values:
            return None
        matched += 1
    return matched


def _score(card: Card, matched: int) -> _Score:
    stats = card.stats
    rate = Fraction(stats.agreed + 1, stats.injected + 2)
    # last_used가 없으면 어느 날짜보다 오래된 것으로 본다(date.min의 서수가 1이다)
    last_used = stats.last_used.toordinal() if stats.last_used is not None else 0
    return (matched, rate, last_used)


def _rank(candidate: _Candidate) -> tuple[int, Fraction, int, str]:
    """점수가 높은 쪽이 먼저, 같으면 `id` 오름차순인 정렬 열쇠."""
    matched, rate, last_used = candidate.score
    return (-matched, -rate, -last_used, candidate.card.id)


def _split_lower_layer(
    candidates: list[_Candidate], lower_ids: set[str]
) -> tuple[list[_Candidate], list[_Candidate]]:
    """4단계 앞부분. `conflicts_with`에 `active`인 원칙이나 우선순위의 ID가 든 카드를 뗀다."""
    kept = [c for c in candidates if not lower_ids.intersection(c.card.conflicts_with)]
    lower = [c for c in candidates if lower_ids.intersection(c.card.conflicts_with)]
    return kept, lower


def _resolve_conflicts(
    candidates: list[_Candidate],
) -> tuple[list[_Candidate], list[_Candidate], list[list[str]]]:
    """4단계 뒷부분. 남은 후보 가운데 `conflicts_with`로 묶인 쌍마다 점수를 견준다.

    어느 쪽 카드에 적혀 있어도 묶인 쌍이다. 낮은 쪽을 빼고, 같으면 둘 다 빼며 그 쌍을
    `[작은 id, 큰 id]`로 적는다. 쌍은 모두 처음 남은 후보끼리 견주므로 순서와 상관없다.
    """
    by_id = {c.card.id: c for c in candidates}
    pairs = sorted(
        {
            (min(c.card.id, other), max(c.card.id, other))
            for c in candidates
            for other in c.card.conflicts_with
            if other in by_id and other != c.card.id
        }
    )
    losers: set[str] = set()
    ties: list[list[str]] = []
    for a, b in pairs:
        score_a, score_b = by_id[a].score, by_id[b].score
        if score_a > score_b:
            losers.add(b)
        elif score_b > score_a:
            losers.add(a)
        else:
            losers.update((a, b))
            ties.append([a, b])
    kept = [c for c in candidates if c.card.id not in losers]
    conflicted = [c for c in candidates if c.card.id in losers]
    return kept, conflicted, ties


def _apply_budget(
    skill: Skill, candidates: list[_Candidate]
) -> tuple[list[_Candidate], list[_Candidate]]:
    """5단계. 판단 지점마다 `cards_per_point`장까지 두고, 그래도 `cards_total`을 넘으면
    `weight`가 낮은 판단 지점(같으면 `skill.yaml`에서 뒤의 것)의 낮은 순위 카드부터 뺀다.
    """
    per_point = max(0, skill.budget.cards_per_point)
    total = max(0, skill.budget.cards_total)
    groups: list[list[_Candidate]] = [[] for _ in skill.decision_points]
    for candidate in candidates:
        groups[candidate.point].append(candidate)
    over = [c for group in groups for c in group[per_point:]]
    kept = [group[:per_point] for group in groups]
    count = sum(len(group) for group in kept)
    weights = [point.weight for point in skill.decision_points]
    for index in sorted(range(len(kept)), key=lambda i: (weights[i], -i)):
        while count > total and kept[index]:
            over.append(kept[index].pop())
            count -= 1
    return [c for group in kept for c in group], over


def _by_rank(candidates: Iterable[_Candidate]) -> list[str]:
    """카드 ID를 점수 순(같으면 `id` 순)으로 돌려준다. 판단 지점과 상관없는 전체 순서다."""
    return [c.card.id for c in sorted(candidates, key=_rank)]


def _rejected(
    ids: Iterable[str], reason: Literal["budget", "conflict", "lower_layer"]
) -> list[Rejected]:
    return [Rejected(id=item_id, reason=reason) for item_id in ids]


# 6단계: 예시


@dataclass
class _Examples:
    good: list[Example] = field(default_factory=list)
    """넣을 good 예시. 뽑은 순서다."""
    avoid: list[Example] = field(default_factory=list)
    """넣을 avoid 예시. 뽑은 순서다."""
    rejected: list[Rejected] = field(default_factory=list)

    @property
    def injected(self) -> list[Example]:
        return [*self.good, *self.avoid]


def _pick_examples(skill: Skill, task: Task, examples: Iterable[Example]) -> _Examples:
    """`random_signature`. 후보는 이 스킬의 `active` 예시 가운데 `grade: signature`이고
    `kind`가 `good`이나 `avoid`인 것이다. 후보가 아닌 예시는 `rejected`에도 적지 않는다.

    종류마다 후보를 뽑기 순서(`_draw_order`)로 줄 세워 앞에서부터 뽑는다. `budget.examples`는
    good과 avoid를 합친 상한이다. good을 먼저 채우고(`GOOD_EXAMPLES_MAX`까지) 남는 자리에
    avoid를 둔다(`AVOID_EXAMPLES_MAX`까지). 후보가 모자라면 있는 만큼만 넣고, good이 모자라
    빈 자리는 avoid가 쓸 수 있다. 뽑히지 않은 후보는 good, avoid 순, 각각 뽑기 순서로
    `budget`에 적는다. 그래서 `budget`은 상한이나 그 종류의 최대 수가 찼을 때만 나온다.
    """
    candidates = [
        e
        for e in examples
        if e.skill == skill.id and e.status == "active" and e.grade == "signature"
    ]
    good = _draw_order(task.id, [e for e in candidates if e.kind == "good"])
    avoid = _draw_order(task.id, [e for e in candidates if e.kind == "avoid"])
    limit = max(0, skill.budget.examples)
    good_count = min(GOOD_EXAMPLES_MAX, limit, len(good))
    avoid_count = min(AVOID_EXAMPLES_MAX, limit - good_count, len(avoid))
    left = (*good[good_count:], *avoid[avoid_count:])
    return _Examples(
        good=good[:good_count],
        avoid=avoid[:avoid_count],
        rejected=_rejected((e.id for e in left), "budget"),
    )


def _pick_past_work(skill: Skill, task: Task, examples: Iterable[Example]) -> _Examples:
    """`past_work`. 후보는 이 스킬의 `active` 예시 가운데 `source: past_work`, `grade: signature`,
    `kind: good`인 것이다(가져온 대표작). 학습 중 승인된 예시와 avoid는 후보가 아니고, 후보가 아닌
    예시는 `rejected`에도 적지 않는다.

    후보를 뽑기 순서(`_draw_order`)로 줄 세워 앞의 `PAST_WORK_EXAMPLES`개를 그 순서로 넣고, 남은
    후보는 뽑기 순서로 `budget`에 적는다. 후보가 그보다 적으면 `not_enough_examples`다.
    """
    candidates = [
        e
        for e in examples
        if e.skill == skill.id
        and e.status == "active"
        and e.grade == "signature"
        and e.kind == "good"
        and e.source == "past_work"
    ]
    if len(candidates) < PAST_WORK_EXAMPLES:
        raise NotEnoughExamplesError(
            f"스킬 {skill.id}의 가져온 대표작이 {len(candidates)}개뿐이라 바탕+예시를 만들 수 "
            f"없습니다. {PAST_WORK_EXAMPLES}개가 필요합니다(active이고 source: past_work, "
            "grade: signature, kind: good인 예시). "
            f"deeptwin import <폴더> --skill {skill.id} --signature로 대표작을 더 가져오세요. "
            "새 평가라면 --against base를 주어 바탕+예시 없이 바탕만과 견줄 수도 있습니다."
        )
    drawn = _draw_order(task.id, candidates)
    return _Examples(
        good=drawn[:PAST_WORK_EXAMPLES],
        rejected=_rejected((e.id for e in drawn[PAST_WORK_EXAMPLES:]), "budget"),
    )


def _draw_order(task_id: str, examples: Iterable[Example]) -> list[Example]:
    """과제 ID를 씨앗으로 한 무작위 순서: `sha256(과제 ID + "\n" + 예시 ID)`의 16진 글 오름차순.

    `random.Random(seed)`와 달리 Python 버전과 OS가 달라도 같은 과제면 같은 순서다.
    """

    def key(example: Example) -> tuple[str, str]:
        digest = hashlib.sha256(f"{task_id}\n{example.id}".encode()).hexdigest()
        return (digest, example.id)

    return sorted(examples, key=key)


# 7단계: 표기


def _render(
    skill: Skill,
    principles: Sequence[Principle],
    priorities: Sequence[Priority],
    cards: Sequence[_Candidate],
    examples: _Examples,
) -> str:
    """설계서 8.6의 고정 틀로 쓴다. 빈 섹션은 쓰지 않고, 넣을 것이 없으면 빈 글이다."""
    sections: list[list[str]] = []
    if principles:
        sections.append([PRINCIPLES_HEADING, *(f"- {_one_line(p.rule)}" for p in principles)])
    if priorities:
        numbered = (f"{n}. {_one_line(p.rule)}" for n, p in enumerate(priorities, start=1))
        sections.append([PRIORITIES_HEADING, *numbered])
    if cards:
        names = [point.name for point in skill.decision_points]
        lines = [line for c in cards for line in _card_lines(names[c.point], c.card)]
        sections.append([CARDS_HEADING, *lines])
    if examples.good:
        sections.append([GOOD_EXAMPLES_HEADING, *_example_lines(examples.good)])
    if examples.avoid:
        sections.append([AVOID_EXAMPLES_HEADING, *_example_lines(examples.avoid)])
    if not sections:
        return ""
    return "\n\n".join([GUIDE_TITLE, *("\n".join(s) for s in sections)]) + "\n"


def _card_lines(point_name: str, card: Card) -> list[str]:
    lines = [f"- [{point_name}] {_sentence(card.choose)}"]
    because, except_ = _one_line(card.because or ""), _one_line(card.except_ or "")
    notes = []
    if because:
        notes.append(f"이유: {_sentence(because)}")
    if except_:
        notes.append(f"예외: {_sentence(except_)}")
    if notes:
        lines.append("  " + " ".join(notes))
    return lines


def _example_lines(examples: Sequence[Example]) -> list[str]:
    """예시 글을 뽑은 순서로 쓰고, 두 예시 사이에 빈 줄, `---`, 빈 줄을 둔다."""
    lines: list[str] = []
    for index, example in enumerate(examples):
        if index:
            lines.extend(["", EXAMPLE_SEPARATOR, ""])
        lines.extend(_example_text(example.text or ""))
    return lines


def _example_text(text: str) -> list[str]:
    """줄 끝 공백과 앞뒤의 빈 줄만 뗀 줄들. 안의 줄바꿈, 빈 줄, 들여쓰기는 그대로 둔다.

    예시는 글 모양이 기준이라 `_one_line`처럼 한 줄로 잇지 않는다.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _one_line(text: str) -> str:
    """앞뒤 공백을 떼고 줄들을 공백 하나로 잇는다. YAML `|` 블록의 끝 줄바꿈도 여기서 빠진다."""
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _sentence(text: str) -> str:
    """한 줄로 만든 뒤, 끝이 `.`, `?`, `!`가 아니면 `.`을 붙인다."""
    text = _one_line(text)
    return text if text.endswith(_SENTENCE_ENDS) else text + "."
