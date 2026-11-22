"""pydantic 데이터 모델. 다른 deeptwin 모듈을 import하지 않는다.

필드 이름은 설계서 8.4, 9.4와 design-deltas.md 그대로다. 모르는 필드(`x_` 확장 필드 등)는
버리지 않고 그대로 둔다. 파일과 목록 파일의 항목은 모두 `schema`를 가진다. 없으면 1로 읽고,
`SCHEMA_VERSION`보다 크면 거부한다.
"""

from __future__ import annotations

from datetime import date, datetime
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

__all__ = [
    "Call",
    "Candidate",
    "Card",
    "Choice",
    "Comparison",
    "Composed",
    "Condition",
    "Context",
    "EvalInfo",
    "EvalKey",
    "EvalReport",
    "Example",
    "FLUID_CLOSE",
    "FLUID_OPEN",
    "Grade",
    "Item",
    "Layer",
    "Pair",
    "PairKey",
    "Principle",
    "Priority",
    "Reference",
    "Rejected",
    "Run",
    "SealOpen",
    "Side",
    "Skill",
    "Split",
    "Status",
    "Task",
    "TaskEntry",
    "Violation",
]

SCHEMA_VERSION = 1
"""이 deeptwin이 읽고 쓰는 파일 형식의 버전."""

FLUID_OPEN = "<!-- deeptwin:fluid -->"
FLUID_CLOSE = "<!-- /deeptwin:fluid -->"
"""`SKILL.md`의 유동 영역 표시 쌍. 조립한 지침이 이 둘 사이에 들어간다(`compose.fill_fluid`).

조립(`compose`)과 스킬 뼈대 만들기(`DeepTwin.new_skill`)가 같은 표시를 쓰도록 여기에 둔다.
"""

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
Condition: TypeAlias = Literal["base", "examples", "full"]
"""평가의 조건 ID. `base`는 바탕만(네 층을 모두 뺀 조립), `examples`는 바탕+예시(본능 층만 남기고
가져온 대표작 3개를 넣은 조립), `full`은 바탕+딥트윈(네 층을 다 넣은 조립)이다. 조건 ID는
대응표(`key.json`)와 보고서에만 쓰고 쌍 목록과 판정 화면에는 쓰지 않는다."""
Side: TypeAlias = Literal["left", "right"]
"""판정에서 고른 쪽. 쌍 목록의 `left`(화면의 [1])나 `right`(화면의 [2])다."""


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


class Violation(BaseModel):
    """결과물이 어긴 원칙 하나. 원칙 검사(`checks.check`)의 반환 항목이다(설계서 8.5).

    `principle`은 원칙 ID, `rule`은 그 원칙의 글, `check`는 `False`를 돌려준 검사 함수 이름이다.
    """

    principle: str
    rule: str
    check: str


class Run(BaseModel):
    """실행 하나의 기록. 원장의 `run` 줄과 같은 모양이다.

    필드 순서는 설계서 8.4를 따른다. `context`는 조립에 쓴 맥락이다.
    `prompt_version`은 생성에 쓴 프롬프트 자산의 버전이다. 생성은 아직 프롬프트 자산을 쓰지
    않으므로 늘 `None`이다. 키를 미리 두어 자산이 생겨도 원장 줄의 모양이 바뀌지 않게 한다.
    """

    id: str
    type: Literal["run"] = "run"
    ts: str
    skill: str
    task: str
    split: Split
    context: Context
    injected: list[str]
    rejected: list[Rejected] = Field(default_factory=list)
    no_hit: list[str] = Field(default_factory=list)
    conflicts: list[list[str]] = Field(default_factory=list)
    guide_hash: str
    prompt_version: str | None = None
    output: str


class TaskEntry(BaseModel):
    """과제 등록 하나의 기록. 원장의 `task` 줄과 같은 모양이다(design-deltas.md 2026-11-21).

    `reference_hash`는 봉인 과제면 기준의 해시(`store.guard.reference_hash`)이고 아니면 `None`이다.
    """

    id: str
    type: Literal["task"] = "task"
    ts: str
    skill: str
    split: Split
    reference_hash: str | None


class SealOpen(BaseModel):
    """봉인 묶음을 연 기록 하나. 원장의 `seal_open` 줄과 같은 모양이다.

    평가 하나에 한 줄이다. `tasks`는 그 평가의 과제 ID, `reused`는 그 가운데 원장에서 이 줄보다
    앞선 다른 평가의 `seal_open` 줄에 든 과제 ID다(이 평가의 과제 순서).
    """

    id: str
    type: Literal["seal_open"] = "seal_open"
    ts: str
    eval: str
    skill: str
    tasks: list[str]
    reused: list[str]


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


class EvalInfo(_FileModel):
    """평가 하나의 정보. `.deeptwin/eval/<평가 ID>/eval.json`.

    조건과 이어지지 않는 것만 적는다. 어느 실행이 어느 조건인지는 대응표(`EvalKey`)에 둔다.
    """

    id: str
    ts: str
    skill: str
    split: Split
    tasks: list[str]
    """평가한 과제 ID. 파일 이름순이다."""
    against: list[Condition]
    """`full`의 상대 조건. `base`, `examples` 가운데 고른 것이고 이 순서다(예: `["base",
    "examples"]`). 과제마다 상대 하나에 쌍 하나다."""
    seed: str
    """쌍의 순서와 좌우를 정한 씨앗. 주지 않으면 평가 ID다."""
    skill_hash: str | None = None
    """평가를 준비할 때 계산한 바탕 스킬의 해시(`DeepTwin.skill_hash`, `sha256:...`). `None`이면(이
    필드가 없는 예전 파일) 바탕 스킬이 바뀌었는지 보지 않는다."""
    skill_changed: bool = False
    """쌍을 만드는 동안 바탕 스킬의 해시가 `skill_hash`와 달라진 것을 봤으면 참이다. 한 번 참이 되면
    파일을 되돌려도 그대로다."""
    seal_open: str | None = None
    """봉인 평가면 원장의 `seal_open` 줄 ID(`seal-NNNN`). 봉인이 아니거나 아직 열기 전이면
    `None`이다."""
    reused: list[str] = Field(default_factory=list)
    """다른 평가에서 이미 연 봉인 과제의 ID. 원장에서 계산한 값이다. 봉인이 아니면 늘 비었다."""


class PairKey(BaseModel):
    """쌍 하나의 대응: 과제와, 왼쪽과 오른쪽 글을 만든 조건."""

    model_config = ConfigDict(extra="forbid")

    task: str
    left: Condition
    right: Condition


class EvalKey(_FileModel):
    """평가 하나의 대응표. `.deeptwin/eval/<평가 ID>/key.json`. 판정이 끝난 뒤에만 합친다."""

    eval: str
    runs: dict[str, dict[Condition, str]]
    """과제 ID -> 조건 -> 그 결과물을 만든 실행 ID."""
    pairs: dict[str, PairKey]
    """쌍 ID -> 그 쌍의 대응."""


class Pair(BaseModel):
    """쌍 목록(`pairs.jsonl`)의 한 줄. 조건을 되짚을 값(조건, 실행 ID, 결과물 경로)은 없다."""

    model_config = ConfigDict(extra="forbid")

    id: str
    task: str
    left: str
    """왼쪽(화면의 [1]) 결과물의 글."""
    right: str
    """오른쪽(화면의 [2]) 결과물의 글."""


class Choice(BaseModel):
    """선택 기록(`choices.jsonl`)의 한 줄."""

    model_config = ConfigDict(extra="forbid")

    pair: str
    chosen: Side
    seconds: float
    """쌍을 보여 준 때부터 고른 때까지의 초(소수 셋째 자리까지)."""
    ts: str
    """고른 시각. ISO 8601(`datetime.fromisoformat`으로 읽히는 글)이다. 하루 몫을 셀 때 읽는다."""

    @field_validator("ts")
    @classmethod
    def _iso_time(cls, value: str) -> str:
        try:
            # 하루 몫을 셀 때처럼 이 컴퓨터의 시간대로 바꿔 본다. 바꿀 수 없는 시각도 막는다
            datetime.fromisoformat(value).astimezone()
        except (ValueError, OverflowError, OSError):
            raise ValueError(f"ISO 8601 시각이어야 합니다(받은 값: {value!r})") from None
        return value


class Comparison(BaseModel):
    """보고서의 상대 하나: `full`과 `against`를 견준 쌍들의 결과."""

    model_config = ConfigDict(extra="forbid")

    against: Condition
    pairs: int
    wins: int
    """고른 쪽이 `full`인 쌍의 수."""
    selection_rate: float
    """`wins / pairs`."""
    p_value: float
    """한쪽 꼬리 이항 검정의 값 P(X >= wins), X ~ B(pairs, 0.5)."""


class EvalReport(_FileModel):
    """판정 보고서. `.deeptwin/eval/<평가 ID>/report.json`."""

    eval: str
    skill: str
    split: Split
    pairs: int
    """평가의 쌍 수. 모두 고른 뒤에만 보고서를 내므로 고른 쌍 수와 같다."""
    reused: list[str] = Field(default_factory=list)
    """다른 평가에서 이미 연 봉인 과제의 ID. 봉인이 아니면 비었다."""
    reference_changed: list[str] = Field(default_factory=list)
    """기준이 등록 때와 다른 봉인 과제의 ID. 보고서를 낼 때마다 다시 본다. 봉인이 아니면 비었다."""
    skill_changed: bool = False
    """평가를 시작한 뒤 바탕 스킬(`SKILL.md`, `skill.yaml`, `checks.py`)이 바뀌었으면 참이다.
    `eval.json`의 `skill_changed`이거나 보고서를 낼 때의 해시가 `skill_hash`와 다를 때다."""
    comparisons: list[Comparison]
    """상대마다 하나. `eval.json`의 `against` 순서다."""
