"""계획의 I/O 매트릭스 전 줄을 `CliRunner`로 돌린다."""

from __future__ import annotations

import functools
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

import claude_stub
from deeptwin.cli import main
from deeptwin.compose import FLUID_CLOSE, FLUID_OPEN
from deeptwin.errors import DeeptwinError
from deeptwin.llm import ClaudeCLIProvider, FakeProvider
from deeptwin.store.ledger import line_hash

RUN_FAKE = ("run", "minimal", "task-0001", "--provider", "fake", "--fake-answer", "answer.txt")
RUN_DEFAULT = ("run", "minimal", "task-0001")

LEDGER_KEYS = [
    "id",
    "type",
    "ts",
    "skill",
    "task",
    "split",
    "injected",
    "rejected",
    "no_hit",
    "conflicts",
    "guide_hash",
    "output",
    "prev_hash",
    "hash",
]
CALL_KEYS = [
    "provider",
    "model",
    "version",
    "prompt_version",
    "input_chars",
    "output_chars",
    "seconds",
    "cached",
]

STUB_COMMAND = (sys.executable, claude_stub.__file__)

TASK_INPUT = (
    "안녕하세요. 주말 파이썬 교실 문의드립니다.\n"
    "수업을 다 들으면 한 달 안에 개발자로 취업할 수 있을까요?\n"
    "수강료와 다음 기수 시작일도 알려 주세요.\n"
)

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
    return jsonl(root / ".deeptwin" / "ledger.jsonl")


def calls(root: Path, run_id: str = "run-0001") -> list[dict[str, Any]]:
    return jsonl(root / ".deeptwin" / "runs" / run_id / "calls.jsonl")


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class _QuickTimeoutClaude(ClaudeCLIProvider):
    """CLI는 시간 제한을 바꾸지 않으므로 테스트에서만 짧게 줄인다."""

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, timeout: float = 120
    ) -> str:
        return super().complete(system, user, temperature=temperature, timeout=2)


def use_stub_claude(
    monkeypatch: pytest.MonkeyPatch,
    mode: str = "success",
    provider: type[ClaudeCLIProvider] = ClaudeCLIProvider,
) -> None:
    """기본 공급자 claude가 가짜 claude 스크립트를 부르게 한다."""
    monkeypatch.setenv("CLAUDE_STUB_MODE", mode)
    monkeypatch.setattr(
        main, "ClaudeCLIProvider", functools.partial(provider, command=STUB_COMMAND)
    )


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
    assert entry["rejected"] == []
    assert entry["no_hit"] == ["opening", "tone"]  # minimal에는 카드가 없다
    assert entry["conflicts"] == []
    assert entry["guide_hash"] == body["guide_hash"]
    assert entry["output"] == "runs/run-0001/output.md"
    assert entry["prev_hash"] == "sha256:" + "0" * 64
    assert entry["hash"].startswith("sha256:")


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
    assert fake.calls == [(copy, TASK_INPUT)]


def test_fake_run_writes_one_call_line(in_minimal: Path) -> None:
    invoke("init")

    ok_json(invoke(*RUN_FAKE, "--json"), "run")

    run_dir = in_minimal / ".deeptwin" / "runs" / "run-0001"
    copy = (run_dir / "SKILL.md").read_text("utf-8")
    answer = (in_minimal / "answer.txt").read_bytes().decode("utf-8")
    [call] = calls(in_minimal)
    assert list(call) == CALL_KEYS
    assert call["provider"] == "fake"
    assert call["model"] is None
    assert call["version"] is None
    assert call["prompt_version"] is None
    assert call["input_chars"] == len(copy) + len(TASK_INPUT)
    assert call["output_chars"] == len(answer)
    assert isinstance(call["seconds"], float)
    assert call["cached"] is False
    assert list(ledger(in_minimal)[0]) == LEDGER_KEYS


# 기본 공급자 claude(가짜 claude 스크립트)


def test_default_provider_is_claude(in_minimal: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_stub_claude(monkeypatch)
    invoke("init")

    body = ok_json(invoke(*RUN_DEFAULT, "--json"), "run")

    assert body["run"] == "run-0001"
    run_dir = in_minimal / ".deeptwin" / "runs" / "run-0001"
    assert (run_dir / "output.md").read_bytes() == claude_stub.RESULT.encode("utf-8")
    copy = (run_dir / "SKILL.md").read_text("utf-8")
    [call] = calls(in_minimal)
    assert list(call) == CALL_KEYS
    assert call["provider"] == "claude"
    assert call["model"] == claude_stub.MAIN_MODEL
    assert call["version"] == claude_stub.VERSION
    assert call["prompt_version"] is None
    assert call["input_chars"] == len(copy) + len(TASK_INPUT)
    assert call["output_chars"] == len(claude_stub.RESULT)
    assert call["seconds"] > 0
    assert call["cached"] is False
    [entry] = ledger(in_minimal)
    assert list(entry) == LEDGER_KEYS
    assert entry["output"] == "runs/run-0001/output.md"


def test_claude_not_found_makes_no_run_folder(
    in_minimal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoke("init")
    monkeypatch.setenv("PATH", "")

    message = error_json(invoke(*RUN_DEFAULT, "--json"), "run", "claude_not_found")

    assert "Claude Code" in message
    assert list((in_minimal / ".deeptwin" / "runs").iterdir()) == []


@pytest.mark.parametrize(
    ("mode", "provider", "code"),
    [
        ("exit1", ClaudeCLIProvider, "provider_failed"),
        ("slow", _QuickTimeoutClaude, "provider_timeout"),
    ],
)
def test_failed_claude_call_leaves_no_records(
    in_minimal: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    provider: type[ClaudeCLIProvider],
    code: str,
) -> None:
    use_stub_claude(monkeypatch, mode, provider)
    invoke("init")

    error_json(invoke(*RUN_DEFAULT, "--json"), "run", code)

    run_dir = in_minimal / ".deeptwin" / "runs" / "run-0001"
    assert not (in_minimal / ".deeptwin" / "ledger.jsonl").exists()
    assert not (run_dir / "calls.jsonl").exists()
    assert not (run_dir / "output.md").exists()


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


def test_unknown_provider(in_minimal: Path) -> None:
    invoke("init")

    message = error_json(
        invoke("run", "minimal", "task-0001", "--provider", "nope", "--json"),
        "run",
        "unknown_provider",
    )

    assert "nope" in message
    assert "쓸 수 있는 이름: claude, fake" in message
    assert list((in_minimal / ".deeptwin" / "runs").iterdir()) == []


def test_help_says_default_provider_is_claude() -> None:
    result = invoke("run", "--help")

    assert result.exit_code == 0
    # 터미널 폭에 따라 줄이 꺾여도 되도록 공백과 상자 테두리를 뺀다
    flat = "".join(ch for ch in result.stdout if not ch.isspace() and ch not in "│|")
    assert "기본값claude는claudeCLI" in flat


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
    assert "compose" in result.stdout
    assert "verify" in result.stdout


# 형식이 틀린 파일


def test_wrong_value_stops_with_file_and_line_then_runs_after_fix(in_minimal: Path) -> None:
    principles = in_minimal / ".deeptwin" / "layers" / "principles.yaml"
    good = principles.read_bytes()
    principles.write_bytes(good.replace(b"kind: never", b"kind: nevr"))
    invoke("init")

    message = error_json(invoke(*RUN_FAKE, "--json"), "run", "invalid_file")
    text = invoke(*RUN_FAKE)

    assert message == (
        ".deeptwin/layers/principles.yaml:5: kind: 쓸 수 있는 값은 'must', 'never'입니다"
        "(받은 값: 'nevr')"
    )
    assert text.exit_code == 1
    assert text.stdout == ""
    assert text.stderr == f"오류: {message}\n"
    assert list((in_minimal / ".deeptwin" / "runs").iterdir()) == []
    assert not (in_minimal / ".deeptwin" / "ledger.jsonl").exists()

    principles.write_bytes(good)
    body = ok_json(invoke(*RUN_FAKE, "--json"), "run")

    assert body["run"] == "run-0001"
    assert body["injected"] == ["prin-01"]
    assert [e["id"] for e in ledger(in_minimal)] == ["run-0001"]


# 원장 검사


def run_three_times(root: Path) -> Path:
    """`run`을 세 번 돌린 원장의 경로."""
    invoke("init")
    for _ in range(3):
        ok_json(invoke(*RUN_FAKE, "--json"), "run")
    return root / ".deeptwin" / "ledger.jsonl"


def ledger_lines(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines()


def write_lines(path: Path, lines: list[bytes]) -> None:
    path.write_bytes(b"".join(line + b"\n" for line in lines))


def test_verify_whole_ledger(in_minimal: Path) -> None:
    run_three_times(in_minimal)

    body = ok_json(invoke("verify", "--json"), "verify")

    assert body == {"lines": 3, "head": ledger(in_minimal)[-1]["hash"]}


def test_verify_finds_the_changed_middle_line_then_passes_after_undo(in_minimal: Path) -> None:
    path = run_three_times(in_minimal)
    good = path.read_bytes()
    first, second, third = ledger_lines(path)
    write_lines(path, [first, second.replace(b"run-0002", b"run-0009", 1), third])
    assert json.loads(ledger_lines(path)[1])["id"] == "run-0009"  # JSON은 그대로 맞다

    message = error_json(invoke("verify", "--json"), "verify", "ledger_broken")
    text = invoke("verify")

    assert message == ".deeptwin/ledger.jsonl:2: hash가 내용과 맞지 않습니다"
    assert text.exit_code == 1
    assert text.stdout == ""
    assert text.stderr == f"오류: {message}\n"

    path.write_bytes(good)
    assert ok_json(invoke("verify", "--json"), "verify")["lines"] == 3


def test_verify_reports_a_line_that_is_not_json(in_minimal: Path) -> None:
    path = run_three_times(in_minimal)
    first, second, third = ledger_lines(path)
    write_lines(path, [first, second.removeprefix(b"{"), third])

    message = error_json(invoke("verify", "--json"), "verify", "ledger_broken")

    assert message == ".deeptwin/ledger.jsonl:2: JSON으로 읽을 수 없는 줄입니다"


def test_verify_catches_a_line_whose_hash_was_rewritten(in_minimal: Path) -> None:
    path = run_three_times(in_minimal)
    first, second, third = ledger_lines(path)
    entry = json.loads(second)
    entry["task"] = "task-0009"
    body = {k: v for k, v in entry.items() if k not in ("prev_hash", "hash")}
    entry["hash"] = line_hash(entry["prev_hash"], body)
    write_lines(path, [first, json.dumps(entry, ensure_ascii=False).encode(), third])

    message = error_json(invoke("verify", "--json"), "verify", "ledger_broken")

    assert message == ".deeptwin/ledger.jsonl:3: 앞줄의 hash와 이어지지 않습니다"


def test_verify_catches_a_deleted_line(in_minimal: Path) -> None:
    path = run_three_times(in_minimal)
    first, _, third = ledger_lines(path)
    write_lines(path, [first, third])

    message = error_json(invoke("verify", "--json"), "verify", "ledger_broken")

    assert message == ".deeptwin/ledger.jsonl:2: 앞줄의 hash와 이어지지 않습니다"


@pytest.mark.parametrize("field", ["prev_hash", "hash"])
def test_verify_reports_a_line_without_chain_field(in_minimal: Path, field: str) -> None:
    path = run_three_times(in_minimal)
    first, second, third = ledger_lines(path)
    entry = json.loads(second)
    del entry[field]
    write_lines(path, [first, json.dumps(entry, ensure_ascii=False).encode(), third])

    message = error_json(invoke("verify", "--json"), "verify", "ledger_broken")

    assert message == f".deeptwin/ledger.jsonl:2: {field}가 없습니다"


def test_verify_reports_old_lines_without_hashes(in_minimal: Path) -> None:
    path = run_three_times(in_minimal)
    old = []
    for line in ledger_lines(path):
        entry = json.loads(line)
        del entry["prev_hash"], entry["hash"]
        old.append(json.dumps(entry, ensure_ascii=False).encode())
    write_lines(path, old)

    message = error_json(invoke("verify", "--json"), "verify", "ledger_broken")

    assert message.splitlines() == [
        f".deeptwin/ledger.jsonl:{number}: {field}가 없습니다"
        for number in (1, 2, 3)
        for field in ("prev_hash", "hash")
    ]


def test_verify_empty_ledger(in_minimal: Path) -> None:
    invoke("init")

    body = ok_json(invoke("verify", "--json"), "verify")
    text = invoke("verify")

    assert body == {"lines": 0, "head": None}
    assert not (in_minimal / ".deeptwin" / "ledger.jsonl").exists()
    assert text.exit_code == 0
    assert text.stdout == "원장 .deeptwin/ledger.jsonl에 아직 줄이 없습니다.\n"


def test_verify_text_mode_success(in_minimal: Path) -> None:
    run_three_times(in_minimal)

    result = invoke("verify")

    assert result.exit_code == 0, result.output
    assert result.stdout == "원장 .deeptwin/ledger.jsonl의 3줄이 모두 해시로 이어져 있습니다.\n"
    assert result.stderr == ""


def test_verify_before_init(minimal_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.rmtree(minimal_copy / ".deeptwin")
    monkeypatch.chdir(minimal_copy)

    message = error_json(invoke("verify", "--json"), "verify", "not_initialized")

    assert "deeptwin init" in message
    assert not (minimal_copy / ".deeptwin").exists()


def test_run_does_not_append_after_a_broken_last_line(in_minimal: Path) -> None:
    path = run_three_times(in_minimal)
    first, second, third = ledger_lines(path)
    write_lines(path, [first, second, third[: len(third) // 2]])
    before = path.read_bytes()

    message = error_json(invoke(*RUN_FAKE, "--json"), "run", "ledger_broken")

    assert message.splitlines()[0] == ".deeptwin/ledger.jsonl:3: JSON으로 읽을 수 없는 줄입니다"
    assert "deeptwin verify" in message
    assert path.read_bytes() == before


# compose


COMPOSE = ("compose", "class-notice", "task-0001")

RULES_GUIDE = """\
## 이번 작업의 개인 기준

반드시 지킬 것
- 수치를 부풀리지 않는다
- 수업 날짜와 시간은 숫자로 쓴다

부딪칠 때의 순서
1. 정확함이 재미보다 먼저다
2. 빠짐없음이 짧음보다 먼저다

판단 지점별 기준
- [첫 문장] 첫 문장은 질문이 아니라 숫자가 든 단정문으로 쓴다.
  이유: 질문형 첫 문장은 넘겨 읽힌다고 본다. 예외: 마감이 사흘 안이면 마감일로 시작한다.
- [첫 문장] 첫 문장에 다음 기수 시작일을 쓴다.
  이유: 모집 글을 여는 사람은 날짜부터 찾는다고 본다.
- [말투] 존댓말로 쓰되 문장을 짧게 끊는다.
"""

RULES_INJECTED = ["prin-01", "prin-02", "pri-01", "pri-02", "card-0002", "card-0001", "card-0004"]
RULES_REJECTED = [
    {"id": "card-0008", "reason": "lower_layer"},
    {"id": "card-0005", "reason": "conflict"},
    {"id": "card-0007", "reason": "budget"},
    {"id": "card-0003", "reason": "budget"},
]


def data_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in (root / ".deeptwin").rglob("*"))


@pytest.mark.acceptance
def test_compose_json_twice_is_byte_identical(in_rules: Path) -> None:
    """설계서 8.11 수용 테스트 1: 같은 입력으로 `deeptwin compose --json`을 두 번 돌리면 같다."""
    before = data_files(in_rules)

    first = invoke(*COMPOSE, "--json")
    second = invoke(*COMPOSE, "--json")

    assert first.stdout_bytes == second.stdout_bytes
    body = ok_json(first, "compose")
    assert list(body) == [
        "guide",
        "injected",
        "rejected",
        "no_hit",
        "conflicts",
        "guide_hash",
        "context",
    ]
    assert body["guide"] == RULES_GUIDE
    assert body["injected"] == RULES_INJECTED
    assert body["rejected"] == RULES_REJECTED
    assert body["no_hit"] == ["schedule"]
    assert body["conflicts"] == []
    assert body["guide_hash"] == "sha256:" + hashlib.sha256(RULES_GUIDE.encode()).hexdigest()
    assert body["context"] == {"purpose": "모집", "channel": "instagram"}
    assert data_files(in_rules) == before
    assert not (in_rules / ".deeptwin" / "ledger.jsonl").exists()
    assert not (in_rules / ".deeptwin" / "runs").exists()


def test_compose_text_mode(in_rules: Path) -> None:
    result = invoke(*COMPOSE)

    assert result.exit_code == 0, result.output
    guide_hash = "sha256:" + hashlib.sha256(RULES_GUIDE.encode()).hexdigest()
    assert result.stdout == (
        RULES_GUIDE + "\n"
        "넣은 항목: prin-01, prin-02, pri-01, pri-02, card-0002, card-0001, card-0004\n"
        "뺀 항목: card-0008(lower_layer), card-0005(conflict), card-0007(budget), "
        "card-0003(budget)\n"
        "맞는 카드가 없던 판단 지점: schedule\n"
        f"guide_hash: {guide_hash}\n"
    )
    assert result.stderr == ""


def test_compose_with_nothing_to_put_in(in_rules: Path) -> None:
    layers = in_rules / ".deeptwin" / "layers"
    shutil.rmtree(layers)
    layers.mkdir()

    result = invoke(*COMPOSE)

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "넣을 기준이 없습니다.\n\n"
        "넣은 항목: 없음\n"
        "뺀 항목: 없음\n"
        "맞는 카드가 없던 판단 지점: opening, schedule, tone, closing\n"
        f"guide_hash: sha256:{hashlib.sha256(b'').hexdigest()}\n"
    )


def test_compose_context_option_overrides_task_context(in_rules: Path) -> None:
    body = ok_json(invoke(*COMPOSE, "--context", "purpose=휴강", "--json"), "compose")

    assert body["context"] == {"purpose": "휴강", "channel": "instagram"}
    # 모집 카드(card-0001, card-0002)는 맞지 않고, 휴강 카드(card-0006)가 일정 안내에 들어간다
    assert [i for i in body["injected"] if i.startswith("card-")] == [
        "card-0003",
        "card-0006",
        "card-0004",
    ]
    assert body["no_hit"] == []
    assert "- [일정 안내] 보강 날짜를 휴강 날짜 바로 뒤에 쓴다.\n" in body["guide"]


def test_compose_context_option_adds_an_axis_the_task_lacks(in_rules: Path) -> None:
    task = in_rules / ".deeptwin" / "tasks" / "train" / "task-0001.yaml"
    text = task.read_text("utf-8")
    task.write_text(text.replace("  channel: instagram\n", ""), encoding="utf-8")
    assert "channel" not in task.read_text("utf-8")

    body = ok_json(invoke(*COMPOSE, "--context", "channel=email", "--json"), "compose")

    assert body["context"] == {"purpose": "모집", "channel": "email"}
    # instagram 카드(card-0002, card-0004)는 맞지 않는다. 마무리(card-0007)는 전체 상한으로 빠진다
    assert [i for i in body["injected"] if i.startswith("card-")] == [
        "card-0001",
        "card-0003",
        "card-0005",
    ]


def test_parse_context_options_keeps_equals_in_the_value() -> None:
    assert main.parse_context_options(["purpose=a=b"]) == {"purpose": "a=b"}


def test_parse_context_options_rejects_whitespace_only_axis() -> None:
    with pytest.raises(DeeptwinError) as info:
        main.parse_context_options(["  =x"])

    assert info.value.code == "invalid_context"
    assert info.value.message == "--context의 축 이름이 비었습니다(받은 값:   =x)."


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            ["--context", "audience=입문자"],
            "맥락 축이 스킬 class-notice의 context_axes에 없습니다: audience=입문자. "
            "쓸 수 있는 축: purpose, channel",
        ),
        (
            ["--context", "purpose=없는값"],
            "맥락 값이 스킬 class-notice의 context_axes에 없습니다: purpose=없는값. "
            "purpose에 쓸 수 있는 값: 모집, 알림, 휴강",
        ),
        (
            ["--context", "purpose"],
            "--context는 축=값 모양이어야 합니다(받은 값: purpose).",
        ),
        (
            ["--context", "=모집"],
            "--context의 축 이름이 비었습니다(받은 값: =모집).",
        ),
        (
            ["--context", "purpose=모집", "--context", "purpose=알림"],
            "--context에 같은 축을 두 번 줬습니다: purpose. 축마다 한 번만 주세요.",
        ),
    ],
    ids=["unknown-axis", "unknown-value", "no-equals", "empty-axis", "same-axis-twice"],
)
def test_compose_rejects_invalid_context(in_rules: Path, options: list[str], message: str) -> None:
    assert error_json(invoke(*COMPOSE, *options, "--json"), "compose", "invalid_context") == message

    text = invoke(*COMPOSE, *options)

    assert text.exit_code == 1
    assert text.stdout == ""
    assert text.stderr == f"오류: {message}\n"


def test_compose_rejects_invalid_task_context(in_rules: Path) -> None:
    task = in_rules / ".deeptwin" / "tasks" / "train" / "task-0001.yaml"
    task.write_text(
        task.read_text("utf-8").replace("channel: instagram", "channel: threads"), encoding="utf-8"
    )

    message = error_json(invoke(*COMPOSE, "--json"), "compose", "invalid_context")
    fixed = ok_json(invoke(*COMPOSE, "--context", "channel=email", "--json"), "compose")

    assert "channel=threads" in message
    assert fixed["context"] == {"purpose": "모집", "channel": "email"}


def test_compose_over_budget(in_rules: Path) -> None:
    config = in_rules / "skills" / "class-notice" / "skill.yaml"
    config.write_text(
        config.read_text("utf-8").replace("principles_max: 10", "principles_max: 1"),
        encoding="utf-8",
    )

    message = error_json(invoke(*COMPOSE, "--json"), "compose", "over_budget")

    assert message == (
        "원칙 상한을 넘었습니다: 스킬 class-notice에 맞는 active 원칙 2개, principles_max 1개. "
        "지침을 자르지 않으니 .deeptwin/layers/principles.yaml의 원칙 항목을 합쳐 1개 이하로 "
        "줄이세요."
    )


def test_compose_task_of_another_skill(in_rules: Path) -> None:
    other = in_rules / "skills" / "other"
    shutil.copytree(in_rules / "skills" / "class-notice", other)
    config = other / "skill.yaml"
    config.write_text(
        config.read_text("utf-8").replace("id: class-notice", "id: other"), encoding="utf-8"
    )

    message = error_json(
        invoke("compose", "other", "task-0001", "--json"), "compose", "task_skill_mismatch"
    )

    assert message == (
        "과제와 스킬이 맞지 않습니다. 과제 task-0001의 skill: class-notice, 조립한 스킬: other"
    )


def test_compose_makes_no_provider(in_rules: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_provider(*args: object) -> None:
        raise AssertionError("compose가 공급자를 만들었다")

    monkeypatch.setattr(main, "make_provider", no_provider)
    monkeypatch.setenv("PATH", "")

    assert ok_json(invoke(*COMPOSE, "--json"), "compose")["injected"] == RULES_INJECTED


def test_compose_before_init(rules_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.rmtree(rules_copy / ".deeptwin")
    monkeypatch.chdir(rules_copy)

    error_json(invoke(*COMPOSE, "--json"), "compose", "not_initialized")

    assert not (rules_copy / ".deeptwin").exists()


def test_run_ledger_line_matches_compose(in_rules: Path) -> None:
    (in_rules / "answer.txt").write_text("가짜 공지\n", encoding="utf-8")
    composed = ok_json(invoke(*COMPOSE, "--json"), "compose")

    body = ok_json(
        invoke(
            "run",
            "class-notice",
            "task-0001",
            "--provider",
            "fake",
            "--fake-answer",
            "answer.txt",
            "--json",
        ),
        "run",
    )

    [entry] = ledger(in_rules)
    assert list(entry) == LEDGER_KEYS
    assert entry["injected"] == composed["injected"] == body["injected"]
    assert entry["rejected"] == composed["rejected"] == RULES_REJECTED
    assert entry["no_hit"] == composed["no_hit"] == ["schedule"]
    assert entry["conflicts"] == composed["conflicts"] == []
    assert entry["guide_hash"] == composed["guide_hash"]
    copy = (in_rules / ".deeptwin" / "runs" / "run-0001" / "SKILL.md").read_text("utf-8")
    assert f"{FLUID_OPEN}\n{RULES_GUIDE}{FLUID_CLOSE}" in copy
