"""판정의 공용 시작과 끝. 터미널(`terminal`)과 웹(`web`)이 같은 시작, 같은 끝, 같은 문장을 쓴다.

- 시작(`start_judging`)은 남은 쌍과 이번 몫을 정한다. 판정 명령에서 `pending_pairs`를 부르는 곳은
  여기 하나뿐이다. 봉인 과제의 기준이 등록 때와 다르면 가장 먼저 그 과제 ID를 알리고
  (`REFERENCE_CHANGED`), 남은 쌍이 없으면 `고를 쌍이 남지 않았습니다.`를 쓴다.
- 끝(`finish_judging`)은 판정 한 번의 결과(`Judged`)를 돌려준다. 이번 몫을 다 지났는데(처음부터
  0개였을 때도) 상한에 걸려 쌍이 남았으면 상한 문장을 쓴다.
- 화면 쪽 스트림은 `err`가 참이면(`--json`) stderr, 아니면 stdout이다.

판정 화면에 나오는 문장(물음, 상한 문장, 요약)은 조건을 되짚을 값을 담지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from deeptwin.eval import pending_pairs
from deeptwin.eval.judging import Judging
from deeptwin.store.project import DeepTwin

__all__ = [
    "ASK",
    "DAILY_LIMIT_REACHED",
    "INPUT_LABEL",
    "Judged",
    "LIMIT_REACHED",
    "NOTHING_LEFT",
    "REFERENCE_CHANGED",
    "end_of",
    "finish_judging",
    "start_judging",
    "summary",
]

ASK = "어느 쪽이 더 나답고 그대로 보낼 만한가요?"
"""판정의 물음. 터미널과 웹이 같이 쓴다."""
INPUT_LABEL = "문의:"
"""과제의 입력 앞에 붙이는 제목."""
NOTHING_LEFT = "고를 쌍이 남지 않았습니다."
REFERENCE_CHANGED = (
    "봉인 과제의 기준이 등록 때와 다릅니다: {tasks}. 판정은 그대로 하고 보고서에 표시합니다."
)
"""봉인 과제의 기준이 등록 뒤 바뀌었을 때의 알림. `{tasks}`는 과제 ID를 `, `로 이은 것이다."""
LIMIT_REACHED = "한 번에 {limit}쌍까지 보여 줍니다. 남은 쌍 {n}개는 다음에 이어 고릅니다."
"""한 번 몫에 걸렸을 때의 문장."""
DAILY_LIMIT_REACHED = (
    "오늘은 이 평가에서 {daily_limit}쌍까지 고릅니다. 남은 쌍 {n}개는 내일 이어 고르세요."
)
"""하루 몫에 걸렸을 때의 문장."""


@dataclass(frozen=True)
class Judged:
    """판정 한 번(터미널이든 웹이든)의 결과."""

    eval: str
    chosen: int
    """이번에 고른 쌍의 수."""
    remaining: int
    """아직 고르지 않은 쌍의 수. 시작할 때 남은 쌍에서 이번에 고른 수를 뺀 값이다."""
    notice: str | None = None
    """상한 문장. 이번 몫을 다 지났는데 상한에 걸려 쌍이 남았을 때만 있다."""


def start_judging(
    deeptwin: DeepTwin,
    eval_id: str,
    *,
    limit: int | None = None,
    daily_limit: int | None = None,
    err: bool,
) -> Judging:
    """남은 쌍과 이번 몫을 정한다. 화면 쪽 스트림에 이 순서로 쓴다.

    1. 봉인 과제의 기준이 등록 때와 다르면 그 과제 ID의 알림(`REFERENCE_CHANGED`). 막지 않는다.
    2. 남은 쌍이 없으면 `NOTHING_LEFT`.

    평가가 없으면 `eval_not_found`, 쌍 목록이 없으면 `eval_incomplete`, 쌍 목록이나 선택 기록의
    형식이 틀렸으면 `invalid_file`이다(`pending_pairs`).
    """
    judging = pending_pairs(deeptwin, eval_id, limit=limit, daily_limit=daily_limit)
    if judging.reference_changed:
        tasks = ", ".join(judging.reference_changed)
        typer.echo(REFERENCE_CHANGED.format(tasks=tasks), err=err)
    if not judging.pending:
        typer.echo(NOTHING_LEFT, err=err)
    return judging


def end_of(judging: Judging, chosen: int, *, handled: int | None = None) -> Judged:
    """판정 한 번의 결과를 정한다. 화면에는 쓰지 않는다(웹의 끝 화면이 먼저 쓴다).

    `handled`는 이번 몫에서 지나간 쌍의 수(고른 쌍과, 기록하지 못해 이번 판정에서 뺀 쌍)이고
    주지 않으면 `chosen`이다. 그 수가 이번 몫과 같고 `stop`이 있으면 상한 문장이 든다.
    """
    remaining = len(judging.pending) - chosen
    passed = chosen if handled is None else handled
    notice = None
    if judging.stop is not None and passed >= len(judging.batch):
        if judging.stop == "daily_limit":
            notice = DAILY_LIMIT_REACHED.format(daily_limit=judging.daily_limit, n=remaining)
        else:
            notice = LIMIT_REACHED.format(limit=judging.limit, n=remaining)
    return Judged(eval=judging.eval, chosen=chosen, remaining=remaining, notice=notice)


def finish_judging(
    judging: Judging, chosen: int, *, err: bool, handled: int | None = None
) -> Judged:
    """판정 한 번의 결과를 돌려주고, 상한 문장이 있으면 화면 쪽 스트림에 쓴다(`end_of`)."""
    judged = end_of(judging, chosen, handled=handled)
    if judged.notice is not None:
        typer.echo(judged.notice, err=err)
    return judged


def summary(judged: Judged) -> str:
    """글 모드의 끝에 쓰는 요약 문장. `--json`의 결과와 같은 내용이다."""
    line = f"평가 {judged.eval}: 이번에 고른 쌍 {judged.chosen}개, 남은 쌍 {judged.remaining}개."
    if judged.remaining:
        return f"{line} deeptwin eval judge {judged.eval}로 남은 쌍부터 이어 고릅니다."
    return f"{line} deeptwin eval report {judged.eval}로 보고서를 냅니다."
