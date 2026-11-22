"""모든 명령의 `--json` 출력(R23). 명령마다 성공 한 번과 알려 주는 오류 한 번을 돌린다.

stdout은 JSON 객체 하나이고, `ok`, `command`, 그리고 성공이면 `result`, 오류면
`error.code`와 `error.message`가 있다. 종료 코드는 성공 0, 오류 1이다.
`init`은 빈 폴더에서, 나머지는 예제(`examples/inquiry-reply`)의 복사본에서 돈다.
평가 명령은 앞서 다른 명령으로 평가를 만들어 두고 돌리고, 판정은 stdin으로 고른다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import typer

from deeptwin.cli import main
from test_cli import invoke, ok_json, parsed, runner

SKILL = "inquiry-reply"
FAKE = ("--provider", "fake", "--fake-answer", "answers/keeps-principles.md")
ADD = ("task", "add", "new-task.yaml")
EVAL = "eval-0001"
PAIRS = ("eval", "pairs", SKILL, "--against", "base", "--split", "spare")


def _nothing(root: Path) -> None:
    pass


def _no_step() -> None:
    pass


def _made_eval() -> None:
    """예비 과제 둘로 평가 eval-0001을 만든다(쌍 2개)."""
    ok_json(invoke(*PAIRS, *FAKE, "--json"), "eval pairs")


def _judged_eval() -> None:
    """평가 eval-0001을 만들고 두 쌍을 모두 고른다."""
    _made_eval()
    ok_json(
        runner.invoke(main.app, ["eval", "judge", EVAL, "--json"], input="1\n2\n"), "eval judge"
    )


def _block_data_folder(root: Path) -> None:
    (root / ".deeptwin").write_text("폴더가 아닌 파일\n", encoding="utf-8")


def _past_work(root: Path) -> None:
    (root / "past").mkdir()
    (root / "past" / "p1.txt").write_text("가상의 지난 답장입니다.\n", encoding="utf-8")


def _empty_past_folder(root: Path) -> None:
    (root / "past").mkdir()


def _task_file(task_id: str, split: str) -> Callable[[Path], None]:
    def write(root: Path) -> None:
        (root / "new-task.yaml").write_text(
            "# 가상의 문의. 테스트용으로 지어낸 것이다.\n"
            f"schema: 1\nid: {task_id}\nskill: {SKILL}\nsplit: {split}\n"
            "input: 수업 시간을 알려 주세요.\n"
            "context: {purpose: 교육문의, audience: 입문자}\n",
            encoding="utf-8",
        )

    return write


def _tamper_ledger(root: Path) -> None:
    # 가운데 줄 하나의 값을 바꾼다. 줄바꿈은 그대로 둔다
    path = root / ".deeptwin" / "ledger.jsonl"
    lines = path.read_bytes().splitlines(keepends=True)
    lines[1] = lines[1].replace(b'"split": "train"', b'"split": "spare"')
    path.write_bytes(b"".join(lines))


def _retire_two_signature_examples(root: Path) -> None:
    """가져온 대표작 넷 가운데 둘을 `retired`로 바꾼다. 바탕+예시에 넣을 대표작이 둘만 남는다."""
    for example_id in ("ex-0003", "ex-0004"):
        path = root / ".deeptwin" / "layers" / "examples" / f"{example_id}.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("status: active", "status: retired"), encoding="utf-8")


def _break_principles(root: Path) -> None:
    (root / ".deeptwin" / "layers" / "principles.yaml").write_text(
        "- {schema: 1, id: prin-01, rule: 가상의 원칙, kind: nevr, status: active, "
        "approval: human}\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class Case:
    command: str
    """`--json` 출력의 `command`."""
    args: tuple[str, ...]
    """`--json`을 뺀 인자."""
    code: str | None = None
    """오류 코드. 성공하는 경우면 `None`이다."""
    prepare: Callable[[Path], None] = _nothing
    """돌리기 전에 프로젝트 폴더를 바꾸는 함수."""
    in_example: bool = True
    """예제 복사본에서 돌리는지. 아니면 빈 폴더다."""
    before: Callable[[], None] = _no_step
    """프로젝트 폴더로 옮긴 뒤, 돌리기 전에 부르는 명령들."""
    input: str | None = None
    """stdin에 줄 입력."""

    @property
    def id(self) -> str:
        return f"{self.command.replace(' ', '-')}-{self.code or 'ok'}"


CASES = [
    Case("init", ("init",), in_example=False),
    Case("init", ("init",), "init_blocked", _block_data_folder, in_example=False),
    Case("skill new", ("skill", "new", "notice")),
    Case("skill new", ("skill", "new", SKILL), "skill_exists"),
    Case("import", ("import", "past", "--skill", SKILL), prepare=_past_work),
    Case("import", ("import", "past", "--skill", SKILL), "nothing_to_import", _empty_past_folder),
    Case("task add", ADD, prepare=_task_file("task-0301", "spare")),
    Case("task add", ADD, "task_exists", _task_file("task-0001", "train")),
    Case("compose", ("compose", SKILL, "task-0001")),
    Case("compose", ("compose", SKILL, "task-0101"), "sealed_access"),
    Case("run", ("run", SKILL, "task-0001", *FAKE)),
    Case("run", ("run", SKILL, "task-0101", *FAKE), "sealed_access"),
    Case("verify", ("verify",)),
    Case("verify", ("verify",), "ledger_broken", _tamper_ledger),
    Case("status", ("status",)),
    Case("status", ("status",), "invalid_file", _break_principles),
    Case("eval pairs", (*PAIRS, *FAKE)),
    Case("eval pairs", (*PAIRS, "--provider", "fake"), "fake_answer_required"),
    Case("eval pairs", ("eval", "pairs", SKILL, "--split", "sealed", *FAKE)),
    Case(
        "eval pairs",
        ("eval", "pairs", SKILL, "--split", "spare", *FAKE),
        "not_enough_examples",
        _retire_two_signature_examples,
    ),
    Case("eval pairs", ("eval", "pairs", "--resume", "eval-0099", *FAKE), "eval_not_found"),
    Case("eval judge", ("eval", "judge", EVAL), before=_made_eval, input="1\n2\n"),
    Case("eval judge", ("eval", "judge", "eval-0099"), "eval_not_found"),
    Case("eval report", ("eval", "report", EVAL), before=_judged_eval),
    Case("eval report", ("eval", "report", EVAL), "judging_unfinished", before=_made_eval),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_json_output_is_one_object(
    case: Case, example_copy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = example_copy if case.in_example else tmp_path / "empty"
    root.mkdir(exist_ok=True)
    case.prepare(root)
    monkeypatch.chdir(root)
    case.before()

    result = runner.invoke(main.app, [*case.args, "--json"], input=case.input)

    payload = parsed(result)
    assert payload["command"] == case.command
    if case.code is None:
        assert result.exit_code == 0, result.output
        assert list(payload) == ["ok", "command", "result"]
        assert payload["ok"] is True
        assert isinstance(payload["result"], dict)
    else:
        assert result.exit_code == 1, result.output
        assert list(payload) == ["ok", "command", "error"]
        assert payload["ok"] is False
        assert list(payload["error"]) == ["code", "message"]
        assert payload["error"]["code"] == case.code
        assert isinstance(payload["error"]["message"], str)
        assert payload["error"]["message"].strip()


def test_every_command_has_a_success_and_an_error_case() -> None:
    succeeding = {case.command for case in CASES if case.code is None}
    failing = {case.command for case in CASES if case.code is not None}

    assert succeeding == failing == set(_cli_commands())


def _cli_commands() -> Iterator[str]:
    """명령줄의 모든 명령 이름. 하위 명령은 `task add`처럼 띄어 쓴다."""

    def walk(group: Any, prefix: str) -> Iterator[str]:
        # 하위 명령을 가진 것(그룹)에만 `commands`가 있다
        for name, command in group.commands.items():
            if isinstance(getattr(command, "commands", None), dict):
                yield from walk(command, f"{prefix}{name} ")
            else:
                yield f"{prefix}{name}"

    return walk(typer.main.get_command(main.app), "")
