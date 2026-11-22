"""모든 명령이 따르는 출력 규칙(R23).

- `--json`을 켜면 stdout에 JSON 객체 하나만 쓴다(`ensure_ascii=False`).
  성공은 `{"ok": true, "command": ..., "result": {...}}`,
  실패는 `{"ok": false, "command": ..., "error": {"code": ..., "message": ...}}`이다.
- 결과에 든 경로는 `.deeptwin/` 안의 파일이면 `.deeptwin/` 기준 POSIX 상대 경로다. 그 밖의
  파일(스킬 폴더, 가져온 글 파일)은 프로젝트 루트 기준이고, 루트 밖이면 받은 경로 그대로다.
- 종료 코드는 성공 0, `DeeptwinError` 1, Ctrl-C(`KeyboardInterrupt`) 130이다. Ctrl-C는 오류 코드
  `interrupted`로 쓴다. 인자 오류는 Click 기본값(2, 글)을 그대로 둔다.
- `--json`을 끄면 한국어 문장을 쓰고, 오류는 stderr로 보낸다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import typer

from deeptwin.errors import DeeptwinError

INTERRUPTED_CODE = "interrupted"
"""Ctrl-C로 멈췄을 때의 오류 코드."""
INTERRUPTED_MESSAGE = "Ctrl-C로 멈췄습니다."
INTERRUPTED_EXIT = 130
"""Ctrl-C로 멈췄을 때의 종료 코드. 셸의 관례(128 + SIGINT 2)를 따른다."""


@dataclass(frozen=True)
class Reply:
    """명령 하나의 성공 결과. `result`는 JSON으로, `text`는 사람에게 보여 준다."""

    result: dict[str, Any]
    text: str


def respond(command: str, action: Callable[[], Reply], *, as_json: bool) -> None:
    """`action`을 돌리고 결과나 실패를 출력 규칙대로 쓴다.

    실패는 `DeeptwinError`(종료 1)와 Ctrl-C(`KeyboardInterrupt`, 종료 130)다.
    """
    try:
        reply = action()
    except DeeptwinError as error:
        _echo_error(command, error.code, error.message, as_json=as_json)
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        _echo_error(command, INTERRUPTED_CODE, INTERRUPTED_MESSAGE, as_json=as_json)
        raise typer.Exit(INTERRUPTED_EXIT) from None
    if as_json:
        _echo_json({"ok": True, "command": command, "result": reply.result})
    else:
        typer.echo(reply.text)


def _echo_error(command: str, code: str, message: str, *, as_json: bool) -> None:
    if as_json:
        _echo_json({"ok": False, "command": command, "error": {"code": code, "message": message}})
    else:
        typer.echo(f"오류: {message}", err=True)


def _echo_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False))
