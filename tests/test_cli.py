"""계획의 I/O 매트릭스 전 줄을 `CliRunner`로 돌린다."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from deeptwin.cli import main
from deeptwin.compose import FLUID_CLOSE, FLUID_OPEN
from deeptwin.llm import FakeProvider

RUN_FAKE = ("run", "minimal", "task-0001", "--provider", "fake", "--fake-answer", "answer.txt")

LEDGER_KEYS = ["id", "type", "ts", "skill", "task", "split", "injected", "guide_hash", "output"]

runner = CliRunner()


def invoke(*args: str) -> Result:
    return runner.invoke(main.app, list(args))


def ok_json(result: Result, command: str) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    payload = parsed(result)
    assert payload["ok"] is True
    assert payload["command"] == command
    result_body: dict[str, Any] = payload["result"]
    return result_body


def error_json(result: Result, command: str, code: str) -> str:
    assert result.exit_code == 1, result.output
    payload = parsed(result)
    assert payload["ok"] is False
    assert payload["command"] == command
    assert payload["error"]["code"] == code
    message: str = payload["error"]["message"]
    return message


def parsed(result: Result) -> dict[str, Any]:
    """`--json`이면 stdout에는 JSON 객체 하나만 있다."""
    assert result.stdout.count("\n") == 1, result.stdout
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


def ledger(root: Path) -> list[dict[str, Any]]:
    path = root / ".deeptwin" / "ledger.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def fluid_part(skill_md: str) -> list[str]:
    return skill_md.split(FLUID_OPEN, 1)[1].split(FLUID_CLOSE, 1)[0].splitlines()


# 줄기


def test_tracer(in_minimal: Path) -> None:
    original = in_minimal / "skills" / "minimal" / "SKILL.md"
    original_bytes = original.read_bytes()

    assert ok_json(invoke("init", "--json"), "init")["gitignore"] == "added"
    body = ok_json(invoke(*RUN_FAKE, "--json"), "run")

    assert body["run"] == "run-0001"
    assert body["injected"] == ["prin-01"]
    assert body["output"] == "runs/run-0001/output.md"
    assert body["guide_hash"].startswith("sha256:")

    run_dir = in_minimal / ".deeptwin" / "runs" / "run-0001"
    assert "- 수치를 부풀리지 않는다" in fluid_part((run_dir / "SKILL.md").read_text("utf-8"))
    assert (run_dir / "output.md").read_bytes() == (in_minimal / "answer.txt").read_bytes()
    assert original.read_bytes() == original_bytes
    assert ".deeptwin/" in (in_minimal / ".gitignore").read_text("utf-8").splitlines()

    [entry] = ledger(in_minimal)
    assert list(entry) == LEDGER_KEYS
    assert entry["id"] == "run-0001"
    assert entry["type"] == "run"
    assert datetime.fromisoformat(entry["ts"]).utcoffset() is not None
    assert entry["skill"] == "minimal"
    assert entry["task"] == "task-0001"
    assert entry["split"] == "train"
    assert entry["injected"] == ["prin-01"]
    assert entry["guide_hash"] == body["guide_hash"]
    assert entry["output"] == "runs/run-0001/output.md"


def test_second_run_is_run_0002(in_minimal: Path) -> None:
    original = in_minimal / "skills" / "minimal" / "SKILL.md"
    original_bytes = original.read_bytes()
    invoke("init", "--json")

    first = ok_json(invoke(*RUN_FAKE, "--json"), "run")
    second = ok_json(invoke(*RUN_FAKE, "--json"), "run")

    assert second["run"] == "run-0002"
    assert second["output"] == "runs/run-0002/output.md"
    assert second["guide_hash"] == first["guide_hash"]
    assert [e["id"] for e in ledger(in_minimal)] == ["run-0001", "run-0002"]
    assert original.read_bytes() == original_bytes


def test_provider_gets_skill_copy_as_system_and_task_input_as_user(
    in_minimal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeProvider(["가짜 답"])
    monkeypatch.setitem(main.PROVIDERS, "fake", lambda options: fake)
    invoke("init", "--json")

    ok_json(invoke("run", "minimal", "task-0001", "--provider", "fake", "--json"), "run")

    copy = (in_minimal / ".deeptwin" / "runs" / "run-0001" / "SKILL.md").read_text("utf-8")
    task_input = (
        "안녕하세요. 주말 파이썬 교실 문의드립니다.\n"
        "수업을 다 들으면 한 달 안에 개발자로 취업할 수 있을까요?\n"
        "수강료와 다음 기수 시작일도 알려 주세요.\n"
    )
    assert fake.calls == [(copy, task_input)]


def test_output_keeps_answer_bytes(in_minimal: Path) -> None:
    (in_minimal / "crlf.txt").write_bytes("첫 줄\r\n둘째 줄\r\n".encode())
    invoke("init")

    args = ("run", "minimal", "task-0001", "--provider", "fake", "--fake-answer", "crlf.txt")
    ok_json(invoke(*args, "--json"), "run")

    output = in_minimal / ".deeptwin" / "runs" / "run-0001" / "output.md"
    assert output.read_bytes() == "첫 줄\r\n둘째 줄\r\n".encode()


def test_text_mode_success(in_minimal: Path) -> None:
    invoke("init")

    result = invoke(*RUN_FAKE)

    assert result.exit_code == 0, result.output
    assert "run-0001 실행을 마쳤습니다." in result.stdout
    assert ".deeptwin/runs/run-0001/output.md" in result.stdout
    assert result.stderr == ""


# init 반복


def test_init_twice_keeps_gitignore_lines_and_files(in_minimal: Path) -> None:
    gitignore = in_minimal / ".gitignore"
    gitignore.write_text("# 내 줄\nnode_modules/\n", encoding="utf-8")
    principles = in_minimal / ".deeptwin" / "layers" / "principles.yaml"
    principles_bytes = principles.read_bytes()

    first = ok_json(invoke("init", "--json"), "init")
    second = ok_json(invoke("init", "--json"), "init")

    assert first["gitignore"] == "added"
    assert second == {"created": [], "gitignore": "present"}
    assert gitignore.read_text("utf-8").splitlines() == ["# 내 줄", "node_modules/", ".deeptwin/"]
    assert principles.read_bytes() == principles_bytes
    assert (in_minimal / ".deeptwin" / "tasks" / "train" / "task-0001.yaml").is_file()


def test_init_reports_created_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    body = ok_json(invoke("init", "--json"), "init")

    assert body["created"] == [
        "layers/examples",
        "layers/cards",
        "candidates",
        "tasks/train",
        "tasks/sealed",
        "tasks/spare",
        "runs",
    ]


# init 전 run


def test_run_before_init(minimal_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.rmtree(minimal_copy / ".deeptwin")
    monkeypatch.chdir(minimal_copy)

    message = error_json(invoke(*RUN_FAKE, "--json"), "run", "not_initialized")

    assert "deeptwin init" in message
    assert not (minimal_copy / ".deeptwin").exists()


def test_text_mode_error_goes_to_stderr(
    minimal_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.rmtree(minimal_copy / ".deeptwin")
    monkeypatch.chdir(minimal_copy)

    result = invoke(*RUN_FAKE)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "먼저 deeptwin init을 실행하세요." in result.stderr


# 없는 과제·스킬


def test_unknown_task(in_minimal: Path) -> None:
    invoke("init")
    args = ("run", "minimal", "task-9999", "--provider", "fake", "--fake-answer", "answer.txt")

    message = error_json(invoke(*args, "--json"), "run", "task_not_found")

    assert ".deeptwin/tasks/train/task-9999.yaml" in message
    assert ".deeptwin/tasks/spare/task-9999.yaml" in message
    assert not (in_minimal / ".deeptwin" / "ledger.jsonl").exists()


def test_unknown_skill(in_minimal: Path) -> None:
    invoke("init")
    args = ("run", "nope", "task-0001", "--provider", "fake", "--fake-answer", "answer.txt")

    message = error_json(invoke(*args, "--json"), "run", "skill_not_found")

    assert "skills/nope/" in message


def test_task_of_another_skill(in_minimal: Path) -> None:
    other = in_minimal / "skills" / "other"
    shutil.copytree(in_minimal / "skills" / "minimal", other)
    config = other / "skill.yaml"
    config.write_text(
        config.read_text("utf-8").replace("id: minimal", "id: other"), encoding="utf-8"
    )
    invoke("init")
    args = ("run", "other", "task-0001", "--provider", "fake", "--fake-answer", "answer.txt")

    error_json(invoke(*args, "--json"), "run", "task_skill_mismatch")

    assert list((in_minimal / ".deeptwin" / "runs").iterdir()) == []


# fake인데 답 파일 없음


def test_fake_needs_answer_file(in_minimal: Path) -> None:
    invoke("init")

    message = error_json(
        invoke("run", "minimal", "task-0001", "--provider", "fake", "--json"),
        "run",
        "fake_answer_required",
    )

    assert "--fake-answer" in message


def test_missing_answer_file_is_an_argument_error(in_minimal: Path) -> None:
    invoke("init")

    result = invoke(
        "run", "minimal", "task-0001", "--provider", "fake", "--fake-answer", "없음.txt", "--json"
    )

    assert result.exit_code == 2
    assert result.stdout == ""


# 모르는 공급자


@pytest.mark.parametrize("provider_args", [("--provider", "claude"), ()])
def test_unknown_provider(in_minimal: Path, provider_args: tuple[str, ...]) -> None:
    invoke("init")

    message = error_json(
        invoke("run", "minimal", "task-0001", *provider_args, "--json"), "run", "unknown_provider"
    )

    assert "claude" in message
    assert "쓸 수 있는 이름: fake" in message


# 표시 없음


def test_missing_fluid_marker_makes_no_run_folder(in_minimal: Path) -> None:
    skill_md = in_minimal / "skills" / "minimal" / "SKILL.md"
    text = skill_md.read_text("utf-8")
    skill_md.write_text(text.replace(FLUID_OPEN, "").replace(FLUID_CLOSE, ""), encoding="utf-8")
    invoke("init")

    error_json(invoke(*RUN_FAKE, "--json"), "run", "fluid_marker_missing")

    assert list((in_minimal / ".deeptwin" / "runs").iterdir()) == []
    assert not (in_minimal / ".deeptwin" / "ledger.jsonl").exists()


def test_help_lists_commands() -> None:
    result = invoke("--help")

    assert result.exit_code == 0
    assert "init" in result.stdout
    assert "run" in result.stdout
