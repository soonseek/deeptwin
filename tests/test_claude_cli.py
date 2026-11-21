"""`ClaudeCLIProvider`를 가짜 claude(`tests/claude_stub.py`)로 확인한다. 네트워크 없이 돈다."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import claude_stub
from deeptwin.errors import DeeptwinError
from deeptwin.llm import ClaudeCLIProvider, Provider

STUB = Path(claude_stub.__file__)
COMMAND = (sys.executable, str(STUB))
OPTIONS = [
    "-p",
    "--output-format",
    "json",
    "--tools",
    "",
    "--safe-mode",
    "--no-session-persistence",
    "--system-prompt-file",
]

SYSTEM = "# 문의 답변\r\n\n지침 한 줄\n"
USER = "안녕하세요.\n수강료를 알려 주세요.\n"


@pytest.fixture
def stub_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "stub-log.jsonl"
    monkeypatch.setenv("CLAUDE_STUB_LOG", str(path))
    return path


def invocations(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def generations(path: Path) -> list[dict[str, Any]]:
    return [entry for entry in invocations(path) if entry["argv"] != ["--version"]]


def test_calls_claude_headless(stub_log: Path) -> None:
    provider = ClaudeCLIProvider(command=COMMAND)

    assert provider.complete(SYSTEM, USER) == claude_stub.RESULT

    [call] = generations(stub_log)
    assert call["argv"][:-1] == OPTIONS
    prompt_file = Path(call["argv"][-1])
    assert call["system_prompt"] == SYSTEM
    assert call["stdin"] == USER
    assert call["cwd_files"] == [prompt_file.name]
    assert Path(call["cwd"]).resolve() == prompt_file.parent.resolve()
    assert not prompt_file.exists()
    assert not prompt_file.parent.exists()


def test_model_and_version(stub_log: Path) -> None:
    provider = ClaudeCLIProvider(command=COMMAND)
    assert provider.model is None
    assert provider.version == claude_stub.VERSION

    provider.complete(SYSTEM, USER)
    provider.complete(SYSTEM, USER)

    assert provider.model == claude_stub.MAIN_MODEL
    assert provider.version == claude_stub.VERSION
    versions = [entry for entry in invocations(stub_log) if entry["argv"] == ["--version"]]
    assert len(versions) == 1
    assert len(generations(stub_log)) == 2


def test_model_option(stub_log: Path) -> None:
    provider = ClaudeCLIProvider(command=COMMAND, model="sonnet")

    provider.complete(SYSTEM, USER)

    [call] = generations(stub_log)
    assert call["argv"][: len(OPTIONS)] == OPTIONS
    assert call["argv"][-2:] == ["--model", "sonnet"]
    assert provider.model == claude_stub.MAIN_MODEL


def test_no_model_option_by_default(stub_log: Path) -> None:
    ClaudeCLIProvider(command=COMMAND).complete(SYSTEM, USER)

    [call] = generations(stub_log)
    assert "--model" not in call["argv"]


def test_claude_not_found(tmp_path: Path) -> None:
    with pytest.raises(DeeptwinError) as info:
        ClaudeCLIProvider(command=(str(tmp_path / "claude"),))

    assert info.value.code == "claude_not_found"
    assert "Claude Code" in info.value.message
    assert "로그인" in info.value.message


def test_claude_not_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")

    with pytest.raises(DeeptwinError) as info:
        ClaudeCLIProvider()

    assert info.value.code == "claude_not_found"


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("exit1", claude_stub.STDERR),
        ("is_error", claude_stub.IS_ERROR_RESULT),
        ("not_json", "JSON이 아닌 출력"),
        ("error_subtype", "error_max_turns"),
        ("result_not_text", "result"),
    ],
)
def test_cli_failure(
    stub_log: Path, monkeypatch: pytest.MonkeyPatch, mode: str, reason: str
) -> None:
    monkeypatch.setenv("CLAUDE_STUB_MODE", mode)
    provider = ClaudeCLIProvider(command=COMMAND)

    with pytest.raises(DeeptwinError) as info:
        provider.complete(SYSTEM, USER)

    assert info.value.code == "provider_failed"
    assert reason in info.value.message
    [call] = generations(stub_log)
    assert not Path(call["argv"][len(OPTIONS)]).exists()


def test_timeout_stops_the_subprocess(stub_log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_STUB_MODE", "slow")
    provider = ClaudeCLIProvider(command=COMMAND)
    started = time.monotonic()

    with pytest.raises(DeeptwinError) as info:
        provider.complete(SYSTEM, USER, timeout=2)

    assert info.value.code == "provider_timeout"
    assert time.monotonic() - started < 30
    [call] = generations(stub_log)
    assert not Path(call["argv"][len(OPTIONS)]).exists()
    if sys.platform != "win32":
        with pytest.raises(ProcessLookupError):
            os.kill(call["pid"], 0)


def test_is_a_provider() -> None:
    provider = ClaudeCLIProvider(command=COMMAND)

    assert isinstance(provider, Provider)
    assert provider.name == "claude"
