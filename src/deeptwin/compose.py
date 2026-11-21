"""유동 지침 조립. 모델을 부르지 않는다(`deeptwin.llm`을 import하지 않는다).

같은 입력이면 같은 지침과 같은 `guide_hash`를 낸다. 지금은 설계서 8.6의 1단계 가운데
원칙만 넣는다. 우선순위, 카드, 예시, 상한은 뒤의 스토리가 더한다.
"""

from __future__ import annotations

import hashlib

from deeptwin.errors import FluidMarkerMissingError
from deeptwin.models import Composed, Context, Principle, Skill, Task
from deeptwin.store.project import DeepTwin

FLUID_OPEN = "<!-- deeptwin:fluid -->"
FLUID_CLOSE = "<!-- /deeptwin:fluid -->"

GUIDE_TITLE = "## 이번 작업의 개인 기준"
PRINCIPLES_HEADING = "반드시 지킬 것"


def compose(
    skill: Skill,
    task: Task,
    deeptwin: DeepTwin,
    *,
    context: Context,
    ablate: tuple[str, ...] = (),
) -> Composed:
    """스킬의 유동 영역에 넣을 지침을 조립한다.

    `status: active`이고 `scope`가 비었거나 이 스킬을 담은 원칙을 파일 순서대로 넣는다.
    `ablate`에 `"principle"`이 있으면 원칙을 넣지 않는다.
    """
    principles = [] if "principle" in ablate else _matching_principles(skill, deeptwin)
    guide = _render(principles)
    return Composed(
        guide=guide,
        injected=[p.id for p in principles],
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


def _matching_principles(skill: Skill, deeptwin: DeepTwin) -> list[Principle]:
    return [
        p
        for p in deeptwin.principles()
        if p.status == "active" and (not p.scope or skill.id in p.scope)
    ]


def _render(principles: list[Principle]) -> str:
    """설계서 8.6의 고정 틀로 쓴다. 넣을 것이 없으면 빈 글이다."""
    if not principles:
        return ""
    lines = [GUIDE_TITLE, "", PRINCIPLES_HEADING, *(f"- {p.rule}" for p in principles)]
    return "\n".join(lines) + "\n"
