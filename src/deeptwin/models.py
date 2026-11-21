"""pydantic 데이터 모델. 다른 deeptwin 모듈을 import하지 않는다.

필드 이름은 설계서 8.4와 design-deltas.md 그대로다. 지금은 1.1이 쓰는 최소 필드만 두고,
나머지 필드와 형식 검사는 뒤의 스토리가 채운다. 모르는 필드는 버리지 않고 그대로 둔다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

Status: TypeAlias = Literal["candidate", "active", "dormant", "retired"]
Approval: TypeAlias = Literal["auto", "human"]
Split: TypeAlias = Literal["train", "sealed", "spare"]

Context: TypeAlias = dict[str, str]
"""이번 작업의 맥락. 맥락 축 이름 -> 값(예: `{"purpose": "문의"}`)."""


class _FileModel(BaseModel):
    """`.deeptwin/`과 `skills/`의 파일 하나(또는 항목 하나)에 대응하는 모델."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_: int = Field(1, alias="schema")


class Principle(_FileModel):
    """원칙: 반드시 하는 것, 절대 안 하는 것. `layers/principles.yaml`의 항목 하나."""

    id: str
    rule: str
    kind: Literal["must", "never"]
    check: str | None = None
    scope: list[str] = Field(default_factory=list)
    status: Status
    approval: Approval


class Task(_FileModel):
    """과제 하나. `.deeptwin/tasks/<split>/<id>.yaml` 파일 하나."""

    id: str
    skill: str
    split: Split
    input: str
    context: Context | None = None


class DecisionPoint(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    weight: int


class Budget(BaseModel):
    model_config = ConfigDict(extra="allow")

    examples: int = 3
    cards_per_point: int = 2
    cards_total: int = 7
    principles_max: int = 10
    priorities_max: int = 5


class Skill(_FileModel):
    """`skills/<id>/skill.yaml`과 그 옆의 `SKILL.md` 경로."""

    id: str
    version: int = 1
    decision_points: list[DecisionPoint] = Field(default_factory=list)
    context_axes: dict[str, list[str]] = Field(default_factory=dict)
    budget: Budget = Field(default_factory=Budget)
    example_policy: Literal["random_signature", "similar", "recent"] = "random_signature"
    checks: str | None = None
    skill_md: Path = Field(exclude=True)


class Rejected(BaseModel):
    id: str
    reason: Literal["budget", "conflict", "lower_layer"]


class Composed(BaseModel):
    """`compose`의 결과."""

    guide: str
    injected: list[str]
    rejected: list[Rejected] = Field(default_factory=list)
    no_hit: list[str] = Field(default_factory=list)
    conflicts: list[list[str]] = Field(default_factory=list)
    guide_hash: str


class Run(BaseModel):
    """실행 하나의 기록. 원장의 `run` 줄과 같은 모양이다."""

    id: str
    type: Literal["run"] = "run"
    ts: str
    skill: str
    task: str
    split: Split
    injected: list[str]
    guide_hash: str
    output: str
