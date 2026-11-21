"""실제 claude CLI를 한 번 부른다. `uv run pytest -m live`로 따로 돈다.

Claude Code가 설치되고 로그인돼 있어야 한다. claude가 없으면 건너뛴다.
"""

from __future__ import annotations

import shutil

import pytest

from deeptwin.llm import ClaudeCLIProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude 실행 파일이 없다"),
]


def test_real_claude_answers() -> None:
    provider = ClaudeCLIProvider()

    output = provider.complete(
        "너는 질문에 한국어 한 문장으로만 답한다.", "하늘은 보통 무슨 색인가요?", timeout=180
    )

    assert output.strip()
    assert provider.model
    assert provider.version is not None
    assert "Claude Code" in provider.version
