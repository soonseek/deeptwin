"""판정: 남은 쌍을 꺼내고 선택을 기록한다. 화면(터미널, 뒤의 웹)은 부르는 쪽이 맡는다.

판정은 대응표(`key.json`)를 읽지 않는다. 어느 쪽이 어느 조건인지 모르는 채로 고른다.
파일에는 저장 계층(`store.evals`)으로만 닿는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from deeptwin.errors import InvalidChoiceError
from deeptwin.models import Choice, EvalInfo, Pair, Side
from deeptwin.store.evals import open_eval
from deeptwin.store.project import DeepTwin

__all__ = [
    "Judging",
    "PendingPair",
    "pending_pairs",
    "record_choice",
]

_SIDES: tuple[Side, ...] = ("left", "right")


@dataclass(frozen=True)
class PendingPair:
    """아직 고르지 않은 쌍 하나와 그 과제의 입력."""

    number: int
    """쌍 목록에서 몇 번째인지(1부터)."""
    pair: Pair
    input: str
    """과제의 `input`(예: 받은 문의)."""


@dataclass(frozen=True)
class Judging:
    """판정을 시작할 때의 상태."""

    eval: str
    info: EvalInfo
    total: int
    """평가의 쌍 수."""
    pending: tuple[PendingPair, ...]
    """남은 쌍(`choices.jsonl`에 없는 쌍). 쌍 목록의 순서다."""


def pending_pairs(deeptwin: DeepTwin, eval_id: str) -> Judging:
    """평가의 남은 쌍을 쌍 목록 순서로 꺼낸다. 아무것도 쓰지 않는다.

    평가가 없으면 `eval_not_found`, 쌍 목록이 없으면 `eval_incomplete`, 쌍 목록이나 선택 기록의
    형식이 틀렸으면 `invalid_file`이다. 과제의 입력은 저장 계층(`DeepTwin.task`)으로 읽는다.
    """
    folder = open_eval(deeptwin, eval_id)
    info = folder.info()
    pairs = folder.pairs()
    chosen = {choice.pair for choice in folder.choices()}
    inputs: dict[str, str] = {}
    pending: list[PendingPair] = []
    for number, pair in enumerate(pairs, start=1):
        if pair.id in chosen:
            continue
        if pair.task not in inputs:
            inputs[pair.task] = deeptwin.task(pair.task).input
        pending.append(PendingPair(number=number, pair=pair, input=inputs[pair.task]))
    return Judging(eval=folder.id, info=info, total=len(pairs), pending=tuple(pending))


def record_choice(
    deeptwin: DeepTwin, eval_id: str, pair_id: str, chosen: Side, *, seconds: float
) -> Choice:
    """선택 하나를 `choices.jsonl`에 바로 덧붙이고 그 줄을 돌려준다.

    `chosen`은 `left`나 `right`, `seconds`는 쌍을 보여 준 때부터 고른 때까지의 초다(소수 셋째
    자리로 반올림한다). 쌍 목록에 없는 쌍이거나 이미 고른 쌍이면 아무것도 쓰지 않고
    `invalid_choice`다. 확인과 덧붙이기는 저장 계층이 한 잠금 안에서 한다.
    """
    if chosen not in _SIDES:
        raise InvalidChoiceError(f"고른 쪽은 left나 right여야 합니다(받은 값: {chosen!r}).")
    folder = open_eval(deeptwin, eval_id)
    choice = Choice(
        pair=pair_id,
        chosen=chosen,
        seconds=round(max(seconds, 0.0), 3),
        ts=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    folder.add_choice(choice)
    return choice
