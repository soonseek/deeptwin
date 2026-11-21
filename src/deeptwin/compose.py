"""유동 지침 조립: 맥락 검사, 고르기, 점수, 충돌, 상한, 표기(설계서 8.6).

모델을 부르지 않는다(`deeptwin.llm`을 import하지 않는다). 같은 입력이면 같은 지침과
같은 `guide_hash`를 낸다. 예시(8.6의 6단계)는 아직 고르지 않는다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal, TypeVar

from deeptwin.errors import FluidMarkerMissingError, InvalidContextError, OverBudgetError
from deeptwin.models import Card, Composed, Context, Principle, Priority, Rejected, Skill, Task
from deeptwin.store.project import DATA_DIR, PRINCIPLES_FILE, PRIORITIES_FILE, DeepTwin

FLUID_OPEN = "<!-- deeptwin:fluid -->"
FLUID_CLOSE = "<!-- /deeptwin:fluid -->"

GUIDE_TITLE = "## 이번 작업의 개인 기준"
PRINCIPLES_HEADING = "반드시 지킬 것"
PRIORITIES_HEADING = "부딪칠 때의 순서"
CARDS_HEADING = "판단 지점별 기준"

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
) -> Composed:
    """스킬의 유동 영역에 넣을 지침을 조립한다.

    1. 원칙과 우선순위: `active`이고 `scope`가 비었거나 이 스킬을 담은 것을 파일 순서대로
       모두 넣는다. 상한을 넘으면 자르지 않고 `over_budget`이다.
    2. 카드 후보: 판단 지점마다 `active`이고 `when`이 맥락과 맞는 카드를 모은다.
    3. 점수: (맞은 축의 수, 일치율, `last_used`) 순으로 높은 쪽이 먼저, 같으면 `id` 순이다.
    4. 충돌: 원칙·우선순위와 부딪치는 카드는 `lower_layer`, 카드끼리 부딪치면 낮은 쪽이
       `conflict`다. 점수가 같으면 둘 다 빼고 `conflicts`에 적는다.
    5. 상한: 판단 지점마다 `cards_per_point`장, 전체 `cards_total`장까지다.
    7. 표기: 원칙, 우선순위, 판단 지점별 카드 순으로 고정 틀에 쓴다.

    `ablate`에 든 층(`principle`, `priority`, `tendency`)은 고르지도 상한을 검사하지도 않는다.
    맥락의 축과 값이 스킬의 `context_axes`에 없으면 `invalid_context`다.
    """
    _check_context(skill, context)
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

    guide = _render(skill, principles, priorities, cards.injected)
    return Composed(
        guide=guide,
        injected=[
            *(p.id for p in principles),
            *(p.id for p in priorities),
            *(c.card.id for c in cards.injected),
        ],
        rejected=cards.rejected,
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


# 맥락


def _check_context(skill: Skill, context: Context) -> None:
    """맥락의 축마다 `context_axes`에 있는 축이고 그 목록에 있는 값인지 본다.

    틀린 곳마다 한 줄씩, 맥락에 적힌 순서로 알려 준다.
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
            *_rejected(lower, "lower_layer"),
            *_rejected(conflicted, "conflict"),
            *_rejected(over, "budget"),
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


def _rejected(
    candidates: list[_Candidate], reason: Literal["budget", "conflict", "lower_layer"]
) -> list[Rejected]:
    return [Rejected(id=c.card.id, reason=reason) for c in sorted(candidates, key=_rank)]


# 7단계: 표기


def _render(
    skill: Skill,
    principles: Sequence[Principle],
    priorities: Sequence[Priority],
    cards: Sequence[_Candidate],
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


def _one_line(text: str) -> str:
    """앞뒤 공백을 떼고 줄들을 공백 하나로 잇는다. YAML `|` 블록의 끝 줄바꿈도 여기서 빠진다."""
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _sentence(text: str) -> str:
    """한 줄로 만든 뒤, 끝이 `.`, `?`, `!`가 아니면 `.`을 붙인다."""
    text = _one_line(text)
    return text if text.endswith(_SENTENCE_ENDS) else text + "."
