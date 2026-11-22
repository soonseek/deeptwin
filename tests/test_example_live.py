"""예제 `examples/inquiry-reply`를 실제 claude CLI로 한 번 돌린다.

`uv run pytest -m live`로 따로 돈다. Claude Code가 설치되고 로그인돼 있어야 하고,
claude가 없으면 건너뛴다. 모델을 한 번 부른다.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from test_cli import calls, files_under, invoke, ok_json

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude 실행 파일이 없다"),
]


def test_example_runs_with_the_real_model(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 구독 로그인으로 돌린다. ANTHROPIC_API_KEY가 있으면 claude가 구독보다 키를 먼저 쓴다
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    skills = files_under(in_example / "skills")

    body = ok_json(invoke("run", "inquiry-reply", "task-0001", "--json"), "run")

    output = in_example / ".deeptwin" / body["output"]
    assert output.read_text(encoding="utf-8").strip()
    assert files_under(in_example / "skills") == skills
    [call] = calls(in_example, body["run"])
    assert call["provider"] == "claude"
    verified = ok_json(invoke("verify", "--json"), "verify")
    assert verified["lines"] == 11
    assert verified["sealed"] == 3
