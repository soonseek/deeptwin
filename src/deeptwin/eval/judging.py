"""판정: 남은 쌍과 이번 몫을 꺼내고 선택을 기록한다. 화면(터미널, 웹)은 부르는 쪽이 맡는다.

판정은 대응표(`key.json`)를 읽지 않는다. 어느 쪽이 어느 조건인지 모르는 채로 고른다.
봉인 평가면 `open_sealed`의 토큰으로 과제의 입력을 읽고, 봉인 과제의 기준이 등록 뒤 바뀌었는지
본다(막지 않는다). 파일에는 저장 계층(`store.evals`, `DeepTwin`)으로만 닿는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias

from deeptwin.errors import InvalidChoiceError
from deeptwin.eval.sealing import open_sealed
from deeptwin.models import Choice, EvalInfo, Pair, Side
from deeptwin.store.evals import open_eval
from deeptwin.store.guard import SealedToken
from deeptwin.store.project import DeepTwin

__all__ = [
    "Judging",
    "PendingPair",
    "Stop",
    "pending_pairs",
    "record_choice",
]

_SIDES: tuple[Side, ...] = ("left", "right")

Stop: TypeAlias = Literal["limit", "daily_limit"]
"""이번 몫이 남은 쌍보다 짧아진 까닭. `limit`은 한 번 몫, `daily_limit`은 하루 몫이다."""


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
    batch: tuple[PendingPair, ...]
    """이번에 보여 줄 쌍. `pending`의 앞에서부터 한 번 몫과 하루 몫이 허락하는 만큼이다."""
    chosen_today: int
    """이 평가에서 오늘(이 컴퓨터의 시간대) 고른 쌍의 수. `choices.jsonl`의 `ts`로 센다."""
    limit: int | None
    """한 번 몫. `None`이면 걸지 않는다."""
    daily_limit: int | None
    """하루 몫. `None`이면 걸지 않는다."""
    stop: Stop | None
    """`batch`가 `pending`보다 짧을 때 그 까닭. 짧지 않으면 `None`이다."""
    reference_changed: tuple[str, ...] = ()
    """기준이 등록 때와 다른 봉인 과제의 ID. 그 평가의 모든 과제를 본다. 봉인 평가가 아니면
    비었다."""


def pending_pairs(
    deeptwin: DeepTwin,
    eval_id: str,
    *,
    limit: int | None = None,
    daily_limit: int | None = None,
) -> Judging:
    """평가의 남은 쌍을 쌍 목록 순서로 꺼내고 이번에 보여 줄 몫을 정한다. 아무것도 쓰지 않는다.

    - `batch`는 `pending` 앞에서부터 `min(limit, daily_limit - chosen_today, 남은 수)`개이고,
      0개보다 적어지지 않는다. 상한이 `None`이면 걸지 않으므로, 둘 다 없으면 `pending`과 같다.
    - `chosen_today`는 `choices.jsonl`의 `ts`를 이 컴퓨터의 시간대로 바꾼 날짜가 오늘인 줄의 수다.
      오늘은 부를 때 한 번만 정한다.
    - `stop`은 `batch`가 `pending`보다 짧을 때만 정해진다. 하루 남은 몫이 `limit` 이하이면
      `daily_limit`, 아니면 `limit`이다.
    - 봉인 평가면 `open_sealed`로 묶음을 열어(같은 평가라 원장에는 쓰지 않는다) 그 토큰으로 과제의
      입력을 읽고, 그 평가의 모든 과제의 기준을 등록 때 해시와 견준 결과를 `reference_changed`에
      담는다(`DeepTwin.changed_references`).

    1보다 작은 상한은 `ValueError`다. 평가가 없으면 `eval_not_found`, 쌍 목록이 없으면
    `eval_incomplete`, 쌍 목록이나 선택 기록의 형식이 틀렸으면 `invalid_file`이다. 과제의 입력은
    저장 계층(`DeepTwin.task`)으로 읽고, 대응표(`key.json`)는 읽지 않는다.
    """
    for name, value in (("limit", limit), ("daily_limit", daily_limit)):
        if value is not None and value < 1:
            raise ValueError(f"{name}은 1 이상이어야 합니다(받은 값: {value}).")
    folder = open_eval(deeptwin, eval_id)
    info = folder.info()
    pairs = folder.pairs()
    choices = folder.choices()
    token: SealedToken | None = None
    changed: tuple[str, ...] = ()
    if info.split == "sealed":
        opening = open_sealed(deeptwin, folder.id)
        info, token = opening.eval, opening.token
        changed = deeptwin.changed_references(info.tasks, token=token)
    today = datetime.now().astimezone().date()
    chosen_today = sum(
        1 for choice in choices if datetime.fromisoformat(choice.ts).astimezone().date() == today
    )
    chosen = {choice.pair for choice in choices}
    inputs: dict[str, str] = {}
    pending: list[PendingPair] = []
    for number, pair in enumerate(pairs, start=1):
        if pair.id in chosen:
            continue
        if pair.task not in inputs:
            inputs[pair.task] = deeptwin.task(pair.task, token=token).input
        pending.append(PendingPair(number=number, pair=pair, input=inputs[pair.task]))
    room = len(pending)
    if limit is not None:
        room = min(room, limit)
    left_today = None if daily_limit is None else max(daily_limit - chosen_today, 0)
    if left_today is not None:
        room = min(room, left_today)
    stop: Stop | None = None
    if room < len(pending):
        daily = left_today is not None and (limit is None or left_today <= limit)
        stop = "daily_limit" if daily else "limit"
    return Judging(
        eval=folder.id,
        info=info,
        total=len(pairs),
        pending=tuple(pending),
        batch=tuple(pending[:room]),
        chosen_today=chosen_today,
        limit=limit,
        daily_limit=daily_limit,
        stop=stop,
        reference_changed=changed,
    )


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
