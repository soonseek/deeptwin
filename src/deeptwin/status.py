"""쌓인 상태 보기: 층별 항목 수, 승인 대기 후보 수, 분할별 과제 수(R16).

층과 후보는 파일을 읽어 센다. 형식이 틀린 파일이 있으면 읽기처럼 `invalid_file`이다.
과제는 파일 이름만 센다(`DeepTwin.task_counts`). 봉인 과제도 내용을 읽지 않는다.
원장에는 쓰지 않는다. 모델을 부르지 않는다(`deeptwin.llm`을 import하지 않는다).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from deeptwin.models import Item, Layer, Split, Status
from deeptwin.store.project import DeepTwin

__all__ = [
    "STATUSES",
    "project_status",
]

STATUSES: tuple[Status, ...] = ("active", "candidate", "dormant", "retired")
"""층 항목의 네 상태. `LayerCount.by_status`의 순서다."""


@dataclass(frozen=True)
class LayerCount:
    """한 층의 항목 수."""

    total: int
    by_status: dict[Status, int]
    """상태마다의 수. 네 상태가 모두 든다(`STATUSES` 순)."""
    signature: int | None = None
    """대표작(`grade: signature`) 수. 상태와 상관없이 센다. 본능 층에만 있고 다른 층은 `None`."""


@dataclass(frozen=True)
class ProjectStatus:
    """`project_status`의 결과."""

    layers: dict[Layer, LayerCount]
    """네 층(instinct, tendency, priority, principle 순)의 항목 수."""
    pending_candidates: int
    """후보 파일 가운데 `status: pending`인 수."""
    tasks: dict[Split, int]
    """분할(train, sealed, spare 순)마다의 과제 파일 수."""


def project_status(deeptwin: DeepTwin) -> ProjectStatus:
    """`.deeptwin/`에 쌓인 상태를 센다. 아무것도 쓰지 않는다."""
    examples = deeptwin.examples()
    signature = sum(1 for e in examples if e.grade == "signature")
    return ProjectStatus(
        layers={
            "instinct": _count(examples, signature=signature),
            "tendency": _count(deeptwin.cards()),
            "priority": _count(deeptwin.priorities()),
            "principle": _count(deeptwin.principles()),
        },
        pending_candidates=sum(1 for c in deeptwin.candidates() if c.status == "pending"),
        tasks=deeptwin.task_counts(),
    )


def _count(items: Sequence[Item], *, signature: int | None = None) -> LayerCount:
    by_status: dict[Status, int] = dict.fromkeys(STATUSES, 0)
    for item in items:
        by_status[item.status] += 1
    return LayerCount(total=len(items), by_status=by_status, signature=signature)
