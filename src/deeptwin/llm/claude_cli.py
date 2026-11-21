"""claude CLI를 헤드리스로 부르는 공급자. Claude Code의 구독 로그인만으로 돈다."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from deeptwin.errors import ClaudeNotFoundError, ProviderFailedError, ProviderTimeoutError

_SYSTEM_PROMPT_FILE = "system-prompt.md"
_REASON_CHARS = 500
"""오류 메시지에 붙이는 CLI의 이유(`result`나 stderr)의 최대 글자 수."""
_VERSION_TIMEOUT = 30
"""`claude --version`을 기다리는 최대 초."""


class ClaudeCLIProvider:
    """`claude -p`를 하위 프로세스로 한 번씩 부른다.

    부르는 모양은 다음과 같다. `system`은 빈 임시 폴더의 파일로, `user`는 표준 입력으로
    넘긴다. 시스템 프롬프트를 인자로 주지 않는 것은 인자 길이 제한 때문이다.

        claude -p --output-format json --tools "" --safe-mode --no-session-persistence
               --system-prompt-file <임시 파일> [--model <model>]

    - `--tools ""`로 도구를 끄고, `--safe-mode`로 사용자의 CLAUDE.md, 플러그인, 훅을 뺀다.
      그 임시 폴더를 작업 폴더로 삼아 프로젝트의 설정도 읽지 않는다.
    - `--bare`는 쓰지 않는다. `--bare`는 구독 로그인을 읽지 않는다.
    - 환경 변수는 그대로 물려준다. `ANTHROPIC_API_KEY`가 있으면 claude CLI가 구독보다
      그것을 먼저 쓴다.
    - `temperature`는 쓰지 않는다. claude CLI에 온도를 정하는 옵션이 없다.

    `version`은 만들 때 한 번 부른 `claude --version`의 출력이다. 호출이 끝나면 `model`은
    응답의 `modelUsage`에서 출력 토큰이 가장 많은 모델 이름이다.
    """

    name: str = "claude"

    def __init__(self, *, command: Sequence[str] = ("claude",), model: str | None = None) -> None:
        executable = shutil.which(command[0])
        if executable is None:
            raise ClaudeNotFoundError(
                f"claude 실행 파일을 찾지 못했습니다: {command[0]}. "
                "Claude Code를 설치하고 claude를 한 번 실행해 로그인하세요."
            )
        # 생성은 임시 폴더를 작업 폴더로 삼으므로, PATH의 상대 경로로 찾았어도 절대 경로로 둔다
        self._command = (os.path.abspath(executable), *command[1:])
        self._model_option = model
        self.model: str | None = model
        self.version: str = self._read_version(_VERSION_TIMEOUT)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        timeout: float = 120,
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="deeptwin-claude-") as folder:
            prompt_file = Path(folder) / _SYSTEM_PROMPT_FILE
            # 줄바꿈을 바꾸지 않도록 바이트로 쓴다
            prompt_file.write_bytes(system.encode("utf-8"))
            args = [
                *self._command,
                "-p",
                "--output-format",
                "json",
                "--tools",
                "",
                "--safe-mode",
                "--no-session-persistence",
                "--system-prompt-file",
                str(prompt_file),
            ]
            if self._model_option is not None:
                args += ["--model", self._model_option]
            completed = self._run(args, stdin=user.encode("utf-8"), cwd=folder, timeout=timeout)
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")
        payload = _json_object(stdout)
        if completed.returncode != 0:
            raise ProviderFailedError(
                f"claude가 종료 코드 {completed.returncode}로 끝났습니다: "
                f"{_reason(payload, stderr, stdout)}"
            )
        if payload is None:
            raise ProviderFailedError(
                f"claude의 출력이 JSON 객체가 아닙니다: {_reason(None, stderr, stdout)}"
            )
        if payload.get("is_error"):
            raise ProviderFailedError(
                f"claude가 오류를 돌려줬습니다: {_reason(payload, stderr, stdout)}"
            )
        if payload.get("subtype") != "success":
            raise ProviderFailedError(
                f"claude가 끝까지 답하지 못했습니다(subtype: {payload.get('subtype')}): "
                f"{_reason(payload, stderr, stdout)}"
            )
        result = payload.get("result")
        if not isinstance(result, str):
            raise ProviderFailedError("claude 응답의 result가 글이 아닙니다.")
        self.model = _main_model(payload) or self._model_option
        return result

    def _read_version(self, timeout: float) -> str:
        completed = self._run([*self._command, "--version"], stdin=b"", cwd=None, timeout=timeout)
        stdout = completed.stdout.decode("utf-8", "replace").strip()
        if completed.returncode != 0 or not stdout:
            stderr = completed.stderr.decode("utf-8", "replace")
            raise ProviderFailedError(
                f"claude --version이 실패했습니다(종료 코드 {completed.returncode}): "
                f"{_head(stderr) or '출력 없음'}"
            )
        return stdout

    def _run(
        self, args: list[str], *, stdin: bytes, cwd: str | None, timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        """하위 프로세스를 부른다. 시간이 넘으면 `subprocess.run`이 하위 프로세스를 끝낸다."""
        try:
            return subprocess.run(
                args, input=stdin, capture_output=True, cwd=cwd, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            raise ProviderTimeoutError(
                f"claude가 {timeout:g}초 안에 끝나지 않아 멈췄습니다."
            ) from None
        except OSError as error:
            raise ProviderFailedError(f"claude를 실행하지 못했습니다: {error}") from None


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _reason(payload: dict[str, Any] | None, stderr: str, stdout: str) -> str:
    """CLI가 준 실패 이유. 응답의 `result`, stderr, stdout 순서로 처음 있는 것의 앞부분이다."""
    result = payload.get("result") if payload is not None else None
    if isinstance(result, str) and result.strip():
        return _head(result)
    return _head(stderr) or _head(stdout) or "이유가 출력되지 않았습니다."


def _head(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _REASON_CHARS else text[:_REASON_CHARS] + "…"


def _main_model(payload: dict[str, Any]) -> str | None:
    """`modelUsage`에서 출력 토큰(`outputTokens`)이 가장 많은 모델 이름."""
    usage = payload.get("modelUsage")
    if not isinstance(usage, dict):
        return None
    tokens = {
        name: numbers["outputTokens"]
        for name, numbers in usage.items()
        if isinstance(numbers, dict) and isinstance(numbers.get("outputTokens"), int)
    }
    return max(tokens, key=tokens.__getitem__) if tokens else None
