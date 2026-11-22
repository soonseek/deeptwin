"""모든 명령이 따르는 출력 규칙(R23).

- `--json`을 켜면 stdout에 JSON 객체 하나만 쓴다(`ensure_ascii=False`).
  성공은 `{"ok": true, "command": ..., "result": {...}}`,
  실패는 `{"ok": false, "command": ..., "error": {"code": ..., "message": ...}}`이다.
- 결과에 든 경로는 `.deeptwin/` 안의 파일이면 `.deeptwin/` 기준 POSIX 상대 경로다. 그 밖의
  파일(스킬 폴더, 가져온 글 파일)은 프로젝트 루트 기준이고, 루트 밖이면 받은 경로 그대로다.
- 종료 코드는 성공 0, `DeeptwinError` 1이다. 인자 오류는 Click 기본값(2, 글)을 그대로 둔다.
- `--json`을 끄면 한국어 문장을 쓰고, 오류는 stderr로 보낸다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import typer

from deeptwin.errors import DeeptwinError


@dataclass(frozen=True)
class Reply:
    """명령 하나의 성공 결과. `result`는 JSON으로, `text`는 사람에게 보여 준다."""

    result: dict[str, Any]
    text: str


def respond(command: str, action: Callable[[], Reply], *, as_json: bool) -> None:
    """`action`을 돌리고 결과나 `DeeptwinError`를 출력 규칙대로 쓴다."""
    try:
        reply = action()
    except DeeptwinError as error:
        if as_json:
            _echo_json(
                {
                    "ok": False,
                    "command": command,
                    "error": {"code": error.code, "message": error.message},
                }
            )
        else:
            typer.echo(f"오류: {error.message}", err=True)
        raise typer.Exit(1) from None
    if as_json:
        _echo_json({"ok": True, "command": command, "result": reply.result})
    else:
        typer.echo(reply.text)


def _echo_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False))
