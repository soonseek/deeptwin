"""pydantic 데이터 모델. 다른 deeptwin 모듈을 import하지 않는다.

필드 이름은 설계서 8.4, 9.4와 design-deltas.md 그대로다. 모르는 필드(`x_` 확장 필드 등)는
버리지 않고 그대로 둔다. 파일과 목록 파일의 항목은 모두 `schema`를 가진다. 없으면 1로 읽고,
`SCHEMA_VERSION`보다 크면 거부한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 1
"""이 deeptwin이 읽고 쓰는 파일 형식의 버전."""

Status: TypeAlias = Literal["candidate", "active", "dormant", "retired"]
Approval: TypeAlias = Literal["auto", "human"]
Split: TypeAlias = Literal["train", "sealed", "spare"]
Layer: TypeAlias = Literal["instinct", "tendency", "priority", "principle"]
"""네 층. 본능(예시), 경향(판단 카드), 우선순위, 원칙."""
Grade: TypeAlias = Literal["signature", "usual", "rushed"]
"""대표작, 보통, 서둘러 쓴 것."""
Cause: TypeAlias = Literal[
    "principle_violation",
    "not_retrieved",
    "ignored",
    "wrong_card",
    "priority_order",
    "missing_card",
    "missing_example",
]
"""차이의 원인(설계서 8.7 원인 분류)."""

Context: TypeAlias = dict[str, str]
"""이번 작업의 맥락. 맥락 축 이름 -> 값(예: `{"purpose": "문의"}`)."""


class _FileModel(BaseModel):
    """`.deeptwin/`과 `skills/`의 파일 하나(또는 목록 파일의 항목 하나)에 대응하는 모델."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_: int = Field(1, alias="schema")

    @field_validator("schema_")
    @classmethod
    def _known_schema(cls, value: int) -> int:
        if value > SCHEMA_VERSION:
            raise ValueError(
                f"읽을 수 있는 schema는 {SCHEMA_VERSION}까지입니다(받은 값: {value}). "
                "deeptwin을 새 버전으로 올리세요."
            )
        if value < 1:
            raise ValueError(f"schema는 1 이상이어야 합니다(받은 값: {value})")
        return value


class Item(_FileModel):
    """계층 항목의 공통 필드(설계서 9.4). `layer`는 하위 모델마다 하나로 고정한다."""

    id: str
    layer: Layer
    status: Status
    approval: Approval
    evidence: list[str] = Field(default_factory=list)
    version: int = 1
    supersedes: str | None = None


class Example(Item):
    """예시(본능). `layers/examples/<id>.yaml` 파일 하나.

    `kind`가 `good`이나 `avoid`면 `text`가, `pair`면 `before`와 `after`가 있어야 한다.
    """

    layer: Literal["instinct"] = "instinct"
    skill: str
    kind: Literal["good", "avoid", "pair"]
    grade: Grade = "usual"
    text: str | None = None
    before: str | None = None
    after: str | None = None
    tags: Context = Field(default_factory=dict)
    source: Literal["past_work", "my_version", "edit", "pick"] = "past_work"

    @model_validator(mode="after")
    def _body_matches_kind(self) -> Example:
        if self.kind == "pair":
            missing = [name for name in ("before", "after") if not getattr(self, name)]
            if missing:
                names = ", ".join(missing)
                raise ValueError(
                    f"kind가 pair이면 before와 after가 있어야 합니다(없는 필드: {names})"
                )
        elif not self.text:
            raise ValueError(f"kind가 {self.kind}이면 text가 있어야 합니다")
        return self


class CardStats(BaseModel):
    """카드의 주입·일치 횟수. 원장에서 다시 계산할 수 있는 캐시다(설계서 9.5)."""

    model_config = ConfigDict(extra="allow")

    injected: int = 0
    agreed: int = 0
    last_used: date | None = None


class Card(Item):
    """판단 카드(경향). `layers/cards/<id>.yaml` 파일 하나.

    파일의 필드 `except`는 Python 예약어라 속성 이름이 `except_`다.
    """

    layer: Literal["tendency"] = "tendency"
    skill: str
    decision_point: str
    when: dict[str, list[str]] = Field(default_factory=dict)
    """맥락 축 -> 맞는 값. 적지 않은 축은 무엇이든 맞는 것으로 본다."""
    choose: str
    because: str | None = None
    except_: str | None = Field(None, alias="except")
    outcome: str | None = None
    differs_from_default: str | None = None
    conflicts_with: list[str] = Field(default_factory=list)
    stats: CardStats = Field(default_factory=CardStats)


class Priority(Item):
    """우선순위. `layers/priorities.yaml`의 항목 하나. 파일에서 위에 있을수록 먼저다."""

    layer: Literal["priority"] = "priority"
    rule: str
    scope: list[str] = Field(default_factory=list)


class Principle(Item):
    """원칙: 반드시 하는 것, 절대 안 하는 것. `layers/principles.yaml`의 항목 하나."""

    layer: Literal["principle"] = "principle"
    rule: str
    kind: Literal["must", "never"]
    check: str | None = None
    scope: list[str] = Field(default_factory=list)


LAYER_MODELS: dict[str, type[Item]] = {
    "instinct": Example,
    "tendency": Card,
    "priority": Priority,
    "principle": Principle,
}
"""층 이름 -> 그 층의 항목 모델."""


class Reference(BaseModel):
    """과제의 기준: 결과물과 비교할 사람의 답(design-deltas.md).

    `kind`가 `my_version`이나 `edit`면 `text`가, `pick`이면 `picked`와 `rejected`가 있어야 한다.
    """

    model_config = ConfigDict(extra="allow")

    kind: Literal["my_version", "edit", "pick"]
    grade: Grade = "usual"
    text: str | None = None
    picked: str | None = None
    rejected: str | None = None

    @model_validator(mode="after")
    def _body_matches_kind(self) -> Reference:
        if self.kind == "pick":
            missing = [name for name in ("picked", "rejected") if not getattr(self, name)]
            if missing:
                names = ", ".join(missing)
                raise ValueError(
                    f"kind가 pick이면 picked와 rejected가 있어야 합니다(없는 필드: {names})"
                )
        elif not self.text:
            raise ValueError(f"kind가 {self.kind}이면 text가 있어야 합니다")
        return self


class Task(_FileModel):
    """과제 하나. `.deeptwin/tasks/<split>/<id>.yaml` 파일 하나."""

    id: str
    skill: str
    split: Split
    input: str
    context: Context | None = None
    reference: Reference | None = None


class Candidate(_FileModel):
    """후보: 아직 승인되지 않은 계층 변경안. `.deeptwin/candidates/<id>.yaml` 파일 하나.

    `item`은 제안하는 항목 전체이고, `layer`에 맞는 항목 모델(`LAYER_MODELS`)의 형식이어야 한다.
    """

    id: str
    action: Literal["add", "revise", "adjust"]
    layer: Layer
    target: str | None = None
    """고칠 기존 항목의 ID. 새로 더하는 후보면 `None`이다."""
    item: Example | Card | Priority | Principle
    cause: Cause
    evidence: list[str] = Field(default_factory=list)
    status: Literal["pending", "approved", "rejected"] = "pending"

    @field_validator("item", mode="wrap")
    @classmethod
    def _item_of_layer(
        cls, value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> Any:
        layer = info.data.get("layer")
        if layer is None:
            # layer가 틀려 이미 오류가 났다. 층을 모르면 item은 검사하지 않는다
            return value
        model = LAYER_MODELS[layer]
        if isinstance(value, model):
            return value
        if isinstance(value, Item):
            value = value.model_dump(by_alias=True)
        # 항목 모델의 오류는 위치(`item.<필드>`)를 지닌 채 그대로 올라간다
        return model.model_validate(value)


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


class Call(BaseModel):
    """모델 호출 하나의 기록. 실행 폴더의 `calls.jsonl` 한 줄과 같은 모양이다(설계서 9.6)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str | None
    version: str | None
    prompt_version: str | None
    input_chars: int
    output_chars: int
    seconds: float
    cached: bool
