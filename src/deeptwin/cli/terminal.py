"""터미널 판정 화면: 이번 몫의 쌍을 하나씩 보여 주고 stdin에서 1이나 2를 읽어 바로 기록한다.

시작과 끝(남은 쌍, 한 번 몫과 하루 몫, 상한 문장, 요약)은 웹과 같이 `session`이 맡는다. 화면에는
쌍의 번호, 과제의 입력, 두 결과물, 물음만 쓰고 조건을 되짚을 값(조건 ID와 이름, 실행 ID, 결과물
경로)은 쓰지 않는다.

- `1`은 왼쪽(`left`), `2`는 오른쪽(`right`)이다. 다른 입력은 다시 묻는다. 비기기와 건너뛰기는 없다.
- 걸린 초는 쌍을 보여 준 때부터 고른 때까지다.
- 입력이 끝나면(EOF) 멈춘다. Ctrl-C는 `KeyboardInterrupt`로 그대로 올라간다. 어느 쪽이든 그때까지
  고른 것은 이미 기록돼 있다.
- `err`가 참이면(`--json`) 보여 주는 글과 묻는 글을 모두 stderr로 보낸다.
"""

from __future__ import annotations

import sys
import time

import typer

from deeptwin.cli.session import ASK, INPUT_LABEL, Judged, finish_judging, start_judging
from deeptwin.eval import record_choice
from deeptwin.models import Side
from deeptwin.store.project import DeepTwin

__all__ = [
    "judge_in_terminal",
]

TYPE_ONE_OR_TWO = "1 또는 2를 입력하세요: "
QUESTION = f"{ASK} {TYPE_ONE_OR_TWO}"
RETRY = "1 또는 2만 받습니다. 다시 입력하세요: "

ANSWERS: dict[str, Side] = {"1": "left", "2": "right"}
"""입력 -> 고른 쪽."""


def read_line() -> str:
    """stdin에서 한 줄을 읽는다. 입력이 끝났으면 빈 글이다."""
    stream = sys.stdin
    return stream.readline() if stream is not None else ""


def typed_on_screen() -> bool:
    """입력이 화면에 보이는지(stdin이 터미널인지). 파이프로 받은 입력은 화면에 남지 않는다."""
    stream = sys.stdin
    try:
        return stream is not None and stream.isatty()
    except (AttributeError, ValueError):
        return False


def judge_in_terminal(
    deeptwin: DeepTwin,
    eval_id: str,
    *,
    limit: int | None = None,
    daily_limit: int | None = None,
    err: bool,
) -> Judged:
    """이번 몫의 쌍을 쌍 목록 순서로 하나씩 보여 주고 고를 때마다 바로 기록한다."""
    judging = start_judging(deeptwin, eval_id, limit=limit, daily_limit=daily_limit, err=err)
    chosen = 0
    for index, item in enumerate(judging.batch):
        if index:
            typer.echo("", err=err)
        typer.echo(
            screen(item.number, judging.total, item.input, item.pair.left, item.pair.right),
            err=err,
        )
        start = time.perf_counter()
        side = _ask(err=err)
        if side is None:
            break
        record_choice(
            deeptwin, judging.eval, item.pair.id, side, seconds=time.perf_counter() - start
        )
        chosen += 1
    return finish_judging(judging, chosen, err=err)


def screen(number: int, total: int, task_input: str, left: str, right: str) -> str:
    """쌍 하나의 화면. 물음은 따로 묻는다(`QUESTION`)."""
    return "\n".join(
        [
            f"쌍 {number}/{total}",
            INPUT_LABEL,
            task_input.rstrip("\n"),
            "",
            "[1]",
            left.rstrip("\n"),
            "",
            "[2]",
            right.rstrip("\n"),
            "",
        ]
    )


def _ask(*, err: bool) -> Side | None:
    """물음을 쓰고 1이나 2를 받을 때까지 읽는다. 입력이 끝나면 `None`이다."""
    typer.echo(QUESTION, nl=False, err=err)
    while True:
        line = read_line()
        if not line or not typed_on_screen():
            # 터미널이면 누른 Enter가 줄을 바꾼다. 입력이 끝났거나 파이프면 여기서 바꾼다
            typer.echo("", err=err)
        if not line:
            return None
        side = ANSWERS.get(line.strip())
        if side is not None:
            return side
        typer.echo(RETRY, nl=False, err=err)
