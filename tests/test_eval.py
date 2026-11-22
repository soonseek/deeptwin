"""평가 명령(`eval pairs`, `eval judge`, `eval report`)과 평가 모듈. 데이터는 모두 가상이다.

예제(`examples/inquiry-reply`)의 복사본에서 가짜 모델로 돈다. 네트워크와 모델을 쓰지 않는다.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

import deeptwin.eval
from deeptwin.cli import main, terminal
from deeptwin.cli.terminal import QUESTION, RETRY
from deeptwin.compose import fill_fluid
from deeptwin.errors import DeeptwinError, ProviderFailedError
from deeptwin.eval import p_value, record_choice
from deeptwin.eval.pairs import _arrange
from deeptwin.store.project import DeepTwin
from test_cli import (
    CHOICE_KEYS,
    error_json,
    forbid_provider,
    invoke,
    jsonl,
    ledger,
    ok_json,
    parsed,
    runner,
)

SKILL = "inquiry-reply"
KEEPS = "answers/keeps-principles.md"
"""모든 원칙을 지키는 가짜 모델의 답."""
BREAKS = "answers/breaks-promise.md"
"""원칙 prin-01을 어기는 가짜 모델의 답."""
FAKE = ("--provider", "fake", "--fake-answer", KEEPS)
PAIRS = ("eval", "pairs", SKILL, "--split", "spare")
EVAL = "eval-0001"
SPARE = ["task-0201", "task-0202"]
"""예제의 예비 과제. 파일 이름순이다."""
ALL_LAYERS = ("instinct", "tendency", "priority", "principle")
HIDDEN = ("base", "full", "바탕만", "딥트윈")
"""쌍 목록과 판정 화면에 나오면 안 되는 조건 ID와 이름."""
PAIR_KEYS = ["id", "task", "left", "right"]
CHOICE_LINE_KEYS = ["pair", "chosen", "seconds", "ts"]
PAIRS_RESULT_KEYS = ["eval", "skill", "split", "tasks", "pairs", "seed"]
REPORT_RESULT_KEYS = ["eval", "skill", "split", "pairs", "comparisons", "files"]

SPARE_TASK = """\
# 가상의 문의. 예비 과제다. 테스트용으로 지어낸 것이다.
schema: 1
id: {id}
skill: inquiry-reply
split: spare
input: 가상의 문의 {n}번입니다. 주말반 수업 시간을 알려 주세요.
context: {{purpose: 교육문의, audience: 입문자}}
"""
NO_CONTEXT_TASK = """\
# 가상의 문의. 맥락이 없는 예비 과제다. 테스트용으로 지어낸 것이다.
schema: 1
id: task-0203
skill: inquiry-reply
split: spare
input: 주말반도 있나요?
"""


def make_eval(*options: str, answer: str = KEEPS) -> dict[str, Any]:
    args = (*PAIRS, "--provider", "fake", "--fake-answer", answer, *options, "--json")
    return ok_json(invoke(*args), "eval pairs")


def judge(*args: str, input: str) -> Result:
    return runner.invoke(main.app, ["eval", "judge", *args], input=input)


def eval_dir(root: Path, eval_id: str = EVAL) -> Path:
    return root / ".deeptwin" / "eval" / eval_id


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def pair_lines(root: Path, eval_id: str = EVAL) -> list[dict[str, Any]]:
    return jsonl(eval_dir(root, eval_id) / "pairs.jsonl")


def choice_lines(root: Path, eval_id: str = EVAL) -> list[dict[str, Any]]:
    return jsonl(eval_dir(root, eval_id) / "choices.jsonl")


def files_in(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def tree(folder: Path) -> dict[str, bytes]:
    """폴더의 파일과 바이트. 잠금 파일(`.lock`)은 잠금을 잡기만 해도 생기므로 뺀다."""
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != ".lock"
    }


def arranged(root: Path, eval_id: str = EVAL) -> list[tuple[str, str, str]]:
    """대응표의 쌍마다 (과제, 왼쪽 조건, 오른쪽 조건). 쌍 ID 순서다."""
    pairs = read_json(eval_dir(root, eval_id) / "key.json")["pairs"]
    return [(key["task"], key["left"], key["right"]) for key in pairs.values()]


def answers_for(root: Path, full_wins: list[bool]) -> str:
    """쌍 목록 순서의 쌍마다 `full`을 고를지(참) 상대를 고를지(거짓)에 맞춘 판정 입력."""
    key = read_json(eval_dir(root) / "key.json")["pairs"]
    lines = []
    for pair, wins in zip(pair_lines(root), full_wins, strict=True):
        full_side = "1" if key[pair["id"]]["left"] == "full" else "2"
        lines.append(full_side if wins else {"1": "2", "2": "1"}[full_side])
    return "".join(f"{line}\n" for line in lines)


def task_input(root: Path, task_id: str) -> str:
    return DeepTwin.open(root).task(task_id).input.rstrip("\n")


def expected_arrangement(seed: str, tasks: list[str]) -> list[tuple[str, str, str]]:
    """설계대로 다시 계산한 쌍의 순서와 좌우. 상대는 `base` 하나다."""
    ranked = []
    for task in tasks:
        base = f"{seed}\n{task}\nbase"
        order = hashlib.sha256(base.encode()).hexdigest()
        full_left = hashlib.sha256(f"{base}\nside".encode()).digest()[0] % 2 == 0
        ranked.append((order, (task, "full", "base") if full_left else (task, "base", "full")))
    return [row for _, row in sorted(ranked)]


# 쌍 만들기


def test_pairs_makes_the_eval_folder_runs_and_ledger_lines(in_example: Path) -> None:
    answer = (in_example / KEEPS).read_bytes()

    result = invoke(*PAIRS, *FAKE, "--json")

    body = ok_json(result, "eval pairs")
    assert list(body) == PAIRS_RESULT_KEYS
    assert body == {
        "eval": EVAL,
        "skill": SKILL,
        "split": "spare",
        "tasks": SPARE,
        "pairs": 2,
        "seed": EVAL,
    }
    assert "run-" not in result.stdout
    folder = eval_dir(in_example)
    assert files_in(folder) == [
        "eval.json",
        "key.json",
        "outputs/base/task-0201.md",
        "outputs/base/task-0202.md",
        "outputs/full/task-0201.md",
        "outputs/full/task-0202.md",
        "pairs.jsonl",
    ]
    info = read_json(folder / "eval.json")
    assert list(info) == ["schema", "id", "ts", "skill", "split", "tasks", "against", "seed"]
    assert info["schema"] == 1
    assert info["id"] == EVAL
    assert datetime.fromisoformat(info["ts"]).utcoffset() is not None
    assert (info["skill"], info["split"], info["tasks"]) == (SKILL, "spare", SPARE)
    assert info["against"] == ["base"]
    assert info["seed"] == EVAL

    key = read_json(folder / "key.json")
    assert list(key) == ["schema", "eval", "runs", "pairs"]
    assert key["eval"] == EVAL
    assert list(key["runs"]) == SPARE
    assert all(list(runs) == ["base", "full"] for runs in key["runs"].values())
    run_ids = [run_id for runs in key["runs"].values() for run_id in runs.values()]
    assert run_ids == ["run-0001", "run-0002", "run-0003", "run-0004"]
    assert list(key["pairs"]) == ["pair-0001", "pair-0002"]

    pairs = pair_lines(in_example)
    assert [p["id"] for p in pairs] == ["pair-0001", "pair-0002"]
    assert all(list(p) == PAIR_KEYS for p in pairs)
    assert sorted(p["task"] for p in pairs) == SPARE
    for pair in pairs:
        side = key["pairs"][pair["id"]]
        assert side["task"] == pair["task"]
        assert {side["left"], side["right"]} == {"base", "full"}
        for column in ("left", "right"):
            output = folder / "outputs" / side[column] / f"{pair['task']}.md"
            assert pair[column] == output.read_text("utf-8")

    runs_root = in_example / ".deeptwin" / "runs"
    for task, runs in key["runs"].items():
        for condition, run_id in runs.items():
            output = (folder / "outputs" / condition / f"{task}.md").read_bytes()
            assert output == (runs_root / run_id / "output.md").read_bytes() == answer
    entries = [e for e in ledger(in_example) if e["type"] == "run"]
    assert [e["id"] for e in entries] == run_ids
    assert all(e["split"] == "spare" for e in entries)
    assert [e["task"] for e in entries] == ["task-0201", "task-0201", "task-0202", "task-0202"]
    assert sorted(p.name for p in runs_root.iterdir()) == run_ids
    assert ok_json(invoke("verify", "--json"), "verify")["lines"] == 14


def test_pairs_text_mode_names_the_eval_but_no_run(in_example: Path) -> None:
    result = invoke(*PAIRS, *FAKE)

    assert result.exit_code == 0, result.output
    assert EVAL in result.stdout
    assert f"deeptwin eval judge {EVAL}" in result.stdout
    assert "run-" not in result.stdout
    for word in HIDDEN:
        assert word not in result.stdout
    assert result.stderr == ""


@pytest.mark.acceptance
def test_acceptance_13_pair_list_has_no_condition_names(in_example: Path) -> None:
    make_eval()

    text = (eval_dir(in_example) / "pairs.jsonl").read_text("utf-8")

    for word in (*HIDDEN, "run-", "outputs"):
        assert word not in text
    # 조건은 대응표에만 있다
    assert {cond for _, *sides in arranged(in_example) for cond in sides} == {"base", "full"}


def test_runs_are_composed_like_run_with_every_layer_out_or_in(in_example: Path) -> None:
    skill_md = (in_example / "skills" / SKILL / "SKILL.md").read_text("utf-8")
    make_eval()
    key = read_json(eval_dir(in_example) / "key.json")
    entries = {e["id"]: e for e in ledger(in_example) if e["type"] == "run"}
    ablate_all = [arg for layer in ALL_LAYERS for arg in ("--ablate", layer)]

    for task in SPARE:
        base = ok_json(invoke("compose", SKILL, task, *ablate_all, "--json"), "compose")
        full = ok_json(invoke("compose", SKILL, task, "--json"), "compose")
        assert base["guide_hash"] != full["guide_hash"]
        for condition, composed in (("base", base), ("full", full)):
            run_id = key["runs"][task][condition]
            entry = entries[run_id]
            assert {k: entry[k] for k in CHOICE_KEYS} == {k: composed[k] for k in CHOICE_KEYS}
            run_dir = in_example / ".deeptwin" / "runs" / run_id
            assert sorted(p.name for p in run_dir.iterdir()) == [
                "SKILL.md",
                "calls.jsonl",
                "output.md",
            ]
            assert len(jsonl(run_dir / "calls.jsonl")) == 1
            copy = (run_dir / "SKILL.md").read_text("utf-8")
            assert copy == fill_fluid(skill_md, composed["guide"])


def test_answer_that_breaks_a_principle_still_makes_pairs(in_example: Path) -> None:
    answer = (in_example / BREAKS).read_bytes().decode("utf-8")

    result = invoke(*PAIRS, "--provider", "fake", "--fake-answer", BREAKS, "--json")

    assert ok_json(result, "eval pairs")["pairs"] == 2
    assert "violations" not in result.stdout
    assert "prin-01" not in result.stdout
    pairs = pair_lines(in_example)
    assert all(list(p) == PAIR_KEYS for p in pairs)
    assert all(p["left"] == p["right"] == answer for p in pairs)
    text = invoke(*PAIRS, "--provider", "fake", "--fake-answer", BREAKS)
    assert text.exit_code == 0, text.output
    assert "prin-01" not in text.stdout
    assert "어긴 원칙" not in text.stdout
    # 같은 답을 run으로 돌리면 위반이 나온다. 쌍 만들기는 그것을 쌍에 넣지 않을 뿐이다
    body = ok_json(
        invoke("run", SKILL, "task-0001", "--provider", "fake", "--fake-answer", BREAKS, "--json"),
        "run",
    )
    assert [v["principle"] for v in body["violations"]] == ["prin-01"]


# 씨앗


def test_same_seed_gives_the_same_pairs_in_the_same_order(in_example: Path) -> None:
    first = make_eval("--seed", "s")
    second = make_eval("--seed", "s")

    assert (first["eval"], second["eval"]) == (EVAL, "eval-0002")
    assert first["seed"] == second["seed"] == "s"
    assert read_json(eval_dir(in_example) / "eval.json")["seed"] == "s"
    assert arranged(in_example) == arranged(in_example, "eval-0002")
    assert [p["task"] for p in pair_lines(in_example)] == [
        p["task"] for p in pair_lines(in_example, "eval-0002")
    ]


def test_without_a_seed_the_eval_id_is_the_seed(in_example: Path) -> None:
    make_eval()
    body = make_eval()

    assert body["seed"] == "eval-0002"
    assert read_json(eval_dir(in_example, "eval-0002") / "eval.json")["seed"] == "eval-0002"
    assert arranged(in_example, "eval-0002") == expected_arrangement("eval-0002", SPARE)


@pytest.mark.parametrize("seed", ["s", "다른 씨앗", "eval-0001"])
def test_order_and_sides_follow_the_seed_rule(in_example: Path, seed: str) -> None:
    make_eval("--seed", seed)

    assert arranged(in_example) == expected_arrangement(seed, SPARE)
    assert [p["task"] for p in pair_lines(in_example)] == [
        task for task, _, _ in expected_arrangement(seed, SPARE)
    ]


def test_sides_and_order_change_with_the_seed() -> None:
    keys = [_arrange(f"seed-{n}", ("task-0201", "task-0202"), ("base",)) for n in range(20)]

    assert {key.left for found in keys for key in found} == {"base", "full"}
    assert {tuple(key.task for key in found) for found in keys} == {
        ("task-0201", "task-0202"),
        ("task-0202", "task-0201"),
    }


def test_eval_id_continues_after_the_largest_folder_number(in_example: Path) -> None:
    evals = in_example / ".deeptwin" / "eval"
    evals.mkdir()
    (evals / "eval-0007").mkdir()
    (evals / "notes").mkdir()

    assert make_eval()["eval"] == "eval-0008"


def test_eval_id_skips_a_name_that_is_already_taken(in_example: Path) -> None:
    evals = in_example / ".deeptwin" / "eval"
    evals.mkdir()
    # 폴더가 아니어서 번호에는 세지 않지만 그 이름으로 폴더를 만들 수 없다
    (evals / "eval-0001").write_text("폴더가 아닌 파일\n", encoding="utf-8")

    assert make_eval()["eval"] == "eval-0002"


# 생성 전 실패


def _add_task_without_context(root: Path) -> None:
    (root / "no-context.yaml").write_text(NO_CONTEXT_TASK, encoding="utf-8")
    ok_json(invoke("task", "add", "no-context.yaml", "--json"), "task add")


def _cut_the_last_ledger_line(root: Path) -> None:
    path = root / ".deeptwin" / "ledger.jsonl"
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:-1]) + lines[-1][: len(lines[-1]) // 2])


def _skill_without_tasks(root: Path) -> None:
    ok_json(invoke("skill", "new", "notice", "--json"), "skill new")


def _leave_alone(root: Path) -> None:
    pass


@pytest.mark.parametrize(
    ("prepare", "args", "code", "forbid"),
    [
        (_add_task_without_context, (*PAIRS, *FAKE), "context_required", True),
        (_leave_alone, (*PAIRS, "--provider", "fake"), "fake_answer_required", False),
        (_cut_the_last_ledger_line, (*PAIRS, *FAKE), "ledger_broken", True),
        (
            _skill_without_tasks,
            ("eval", "pairs", "notice", "--split", "spare", *FAKE),
            "no_tasks",
            True,
        ),
        (_leave_alone, ("eval", "pairs", SKILL, "--split", "sealed", *FAKE), "sealed_access", True),
    ],
    ids=["no-context", "no-fake-answer", "broken-ledger", "no-tasks", "sealed"],
)
def test_pairs_that_stop_before_generating_leave_nothing(
    in_example: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepare: Callable[[Path], None],
    args: tuple[str, ...],
    code: str,
    forbid: bool,
) -> None:
    prepare(in_example)
    ledger_path = in_example / ".deeptwin" / "ledger.jsonl"
    before = ledger_path.read_bytes()
    if forbid:
        forbid_provider(monkeypatch)

    message = error_json(invoke(*args, "--json"), "eval pairs", code)

    assert message.strip()
    assert not (in_example / ".deeptwin" / "eval").exists()
    assert not (in_example / ".deeptwin" / "runs").exists()
    assert ledger_path.read_bytes() == before


def test_split_must_be_given_and_be_one_of_the_three(in_example: Path) -> None:
    for args in (("eval", "pairs", SKILL, *FAKE), (*PAIRS[:-1], "nope", *FAKE)):
        result = invoke(*args)
        assert result.exit_code == 2, result.output
        assert "--split" in result.output
    assert not (in_example / ".deeptwin" / "eval").exists()


# 생성 중 실패


class _FailsOnTheSecondCall:
    """둘째 생성에서 실패하는 가짜 공급자."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, timeout: float = 120
    ) -> str:
        self.calls += 1
        if self.calls == 2:
            raise ProviderFailedError("가짜 공급자가 둘째 생성에서 실패했습니다.")
        return "가짜 답장입니다.\n"


def test_failure_while_generating_keeps_the_first_run_and_no_pairs(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _FailsOnTheSecondCall()
    monkeypatch.setitem(main.PROVIDERS, "fake", lambda options: provider)

    error_json(invoke(*PAIRS, *FAKE, "--json"), "eval pairs", "provider_failed")

    runs = [e for e in ledger(in_example) if e["type"] == "run"]
    assert [e["id"] for e in runs] == ["run-0001"]
    assert [p.name for p in (in_example / ".deeptwin" / "runs").iterdir()] == ["run-0001"]
    assert files_in(eval_dir(in_example)) == ["eval.json", "outputs/base/task-0201.md"]
    ok_json(invoke("verify", "--json"), "verify")
    error_json(judge(EVAL, "--json", input="1\n"), "eval judge", "eval_incomplete")
    error_json(invoke("eval", "report", EVAL, "--json"), "eval report", "eval_incomplete")
    assert not (eval_dir(in_example) / "choices.jsonl").exists()


FAILING_CHECKS = """\
# 가상의 검사 함수. 테스트용으로 지어낸 것이다.
def no_outcome_promise(output: str) -> bool:
    raise RuntimeError("가짜 검사 함수가 멈췄습니다")


def no_contact_details(output: str) -> bool:
    return True
"""


def test_failing_check_keeps_the_output_and_names_no_run(in_example: Path) -> None:
    (in_example / "skills" / SKILL / "checks.py").write_text(FAILING_CHECKS, encoding="utf-8")

    result = invoke(*PAIRS, *FAKE, "--json")

    message = error_json(result, "eval pairs", "check_failed")
    assert "task-0201" in message
    assert "prin-01" in message
    assert "no_outcome_promise" in message
    for word in (*HIDDEN, "run-", "outputs"):
        assert word not in result.stdout
    # 첫 생성의 실행은 원장에 남았고, 그 결과물이 평가 폴더에도 있다
    [entry] = [e for e in ledger(in_example) if e["type"] == "run"]
    run_output = (in_example / ".deeptwin" / "runs" / entry["id"] / "output.md").read_bytes()
    folder = eval_dir(in_example)
    assert files_in(folder) == ["eval.json", "outputs/base/task-0201.md"]
    assert (folder / "outputs" / "base" / "task-0201.md").read_bytes() == run_output
    ok_json(invoke("verify", "--json"), "verify")


# 터미널 판정


def test_judge_records_each_choice_in_pair_order(in_example: Path) -> None:
    make_eval()
    pairs = pair_lines(in_example)

    result = judge(EVAL, input="1\n2\n")

    assert result.exit_code == 0, result.output
    choices = choice_lines(in_example)
    assert [c["pair"] for c in choices] == [p["id"] for p in pairs]
    assert [c["chosen"] for c in choices] == ["left", "right"]
    for choice in choices:
        assert list(choice) == CHOICE_LINE_KEYS
        assert isinstance(choice["seconds"], float)
        assert choice["seconds"] >= 0
        assert datetime.fromisoformat(choice["ts"]).utcoffset() is not None
    screen = result.stdout
    for task in SPARE:
        assert task_input(in_example, task) in screen
    assert pairs[0]["left"].rstrip("\n") in screen
    assert screen.count(QUESTION) == 2
    assert "쌍 1/2" in screen
    assert "쌍 2/2" in screen
    for word in (*HIDDEN, "run-", "outputs/"):
        assert word not in screen
    assert "이번에 고른 쌍 2개, 남은 쌍 0개" in screen
    assert result.stderr == ""


def test_judge_asks_again_after_a_wrong_answer(in_example: Path) -> None:
    make_eval()

    result = judge(EVAL, input="x\n3\n\n1\n2\n")

    assert result.exit_code == 0, result.output
    assert [c["chosen"] for c in choice_lines(in_example)] == ["left", "right"]
    assert result.stdout.count(RETRY) == 3
    assert result.stdout.count(QUESTION) == 2


def test_judge_stops_at_the_end_of_input_and_continues_next_time(in_example: Path) -> None:
    make_eval()
    pairs = pair_lines(in_example)

    first = judge(EVAL, input="1\n")
    second = judge(EVAL, input="2\n")
    third = judge(EVAL, input="")

    assert first.exit_code == second.exit_code == third.exit_code == 0
    assert "이번에 고른 쌍 1개, 남은 쌍 1개" in first.stdout
    assert "쌍 1/2" not in second.stdout
    assert "쌍 2/2" in second.stdout
    assert task_input(in_example, pairs[1]["task"]) in second.stdout
    assert task_input(in_example, pairs[0]["task"]) not in second.stdout
    assert second.stdout.count(QUESTION) == 1
    assert "이번에 고른 쌍 1개, 남은 쌍 0개" in second.stdout
    assert [(c["pair"], c["chosen"]) for c in choice_lines(in_example)] == [
        (pairs[0]["id"], "left"),
        (pairs[1]["id"], "right"),
    ]
    assert "고를 쌍이 남지 않았습니다." in third.stdout
    assert "이번에 고른 쌍 0개, 남은 쌍 0개" in third.stdout
    assert QUESTION not in third.stdout
    done = ok_json(judge(EVAL, "--json", input=""), "eval judge")
    assert done == {"eval": EVAL, "chosen": 0, "remaining": 0}


def test_judge_json_writes_the_screen_to_stderr(in_example: Path) -> None:
    make_eval()

    result = judge(EVAL, "--json", input="1\n2\n")

    assert result.exit_code == 0, result.output
    assert parsed(result) == {
        "ok": True,
        "command": "eval judge",
        "result": {"eval": EVAL, "chosen": 2, "remaining": 0},
    }
    assert result.stderr.count(QUESTION) == 2
    for task in SPARE:
        assert task_input(in_example, task) in result.stderr
        assert task_input(in_example, task) not in result.stdout
    for word in (*HIDDEN, "run-"):
        assert word not in result.stderr


def test_ctrl_c_while_judging_keeps_the_choices_made(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_eval()
    reading = terminal.read_line
    typed = iter(["1\n"])

    def read_line() -> str:
        line = next(typed, None)
        if line is None:
            raise KeyboardInterrupt
        return line

    monkeypatch.setattr(terminal, "read_line", read_line)

    result = judge(EVAL, "--json", input="")

    assert result.exit_code == 130, result.output
    assert parsed(result)["error"] == {"code": "interrupted", "message": "Ctrl-C로 멈췄습니다."}
    assert [c["chosen"] for c in choice_lines(in_example)] == ["left"]
    monkeypatch.setattr(terminal, "read_line", reading)
    again = ok_json(judge(EVAL, "--json", input="2\n"), "eval judge")
    assert again == {"eval": EVAL, "chosen": 1, "remaining": 0}


# 보고서


@pytest.mark.parametrize("wins", [0, 1, 2])
def test_report_counts_wins_from_the_key_and_the_choices(in_example: Path, wins: int) -> None:
    make_eval()
    judge(EVAL, input=answers_for(in_example, [n < wins for n in range(2)]))
    key = read_json(eval_dir(in_example) / "key.json")["pairs"]
    counted = sum(key[c["pair"]][c["chosen"]] == "full" for c in choice_lines(in_example))

    body = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")

    assert counted == wins
    assert list(body) == REPORT_RESULT_KEYS
    assert (body["eval"], body["skill"], body["split"], body["pairs"]) == (EVAL, SKILL, "spare", 2)
    assert body["comparisons"] == [
        {
            "against": "base",
            "pairs": 2,
            "wins": wins,
            "selection_rate": wins / 2,
            "p_value": [1.0, 0.75, 0.25][wins],
        }
    ]
    assert body["files"] == ["eval/eval-0001/report.json", "eval/eval-0001/report.md"]
    folder = eval_dir(in_example)
    saved = read_json(folder / "report.json")
    assert list(saved) == ["schema", "eval", "skill", "split", "pairs", "comparisons"]
    assert saved == {"schema": 1, **{k: v for k, v in body.items() if k != "files"}}
    markdown = (folder / "report.md").read_text("utf-8")
    assert "| 바탕+딥트윈 대 바탕만 | 2 |" in markdown
    assert f"| {wins} | {wins * 50:.1f}% | {[1.0, 0.75, 0.25][wins]:.4f} |" in markdown
    assert "더 낫다" not in markdown
    ok_json(invoke("verify", "--json"), "verify")


def test_report_again_gives_the_same_bytes(in_example: Path) -> None:
    make_eval()
    judge(EVAL, input="1\n2\n")
    folder = eval_dir(in_example)

    ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")
    first = tree(folder)
    text = invoke("eval", "report", EVAL)
    second = tree(folder)

    assert first == second
    assert text.exit_code == 0, text.output
    assert (folder / "report.md").read_text("utf-8").rstrip("\n") in text.stdout
    assert ".deeptwin/eval/eval-0001/report.json" in text.stdout
    assert ".deeptwin/eval/eval-0001/report.md" in text.stdout


def test_report_with_pairs_left_writes_nothing(in_example: Path) -> None:
    make_eval()
    judge(EVAL, input="1\n")
    before = tree(eval_dir(in_example))

    message = error_json(
        invoke("eval", "report", EVAL, "--json"), "eval report", "judging_unfinished"
    )
    text = invoke("eval", "report", EVAL)

    assert "1개" in message
    assert text.exit_code == 1
    assert text.stdout == ""
    assert text.stderr == f"오류: {message}\n"
    assert tree(eval_dir(in_example)) == before
    assert not (eval_dir(in_example) / "report.json").exists()
    assert not (eval_dir(in_example) / "report.md").exists()


# 없는 평가, 기록 함수, 깨진 선택 기록


@pytest.mark.parametrize(
    ("command", "eval_id"),
    [("judge", "eval-0099"), ("report", "../x"), ("judge", "eval-1x"), ("report", "eval-")],
)
def test_unknown_eval_creates_nothing(in_example: Path, command: str, eval_id: str) -> None:
    make_eval()
    before = tree(in_example)

    result = runner.invoke(main.app, ["eval", command, eval_id, "--json"], input="1\n")

    message = error_json(result, f"eval {command}", "eval_not_found")
    assert eval_id in message
    assert tree(in_example) == before


def test_record_choice_refuses_an_unknown_or_repeated_pair(in_example: Path) -> None:
    make_eval()
    deeptwin = DeepTwin.open(in_example)
    path = eval_dir(in_example) / "choices.jsonl"

    with pytest.raises(DeeptwinError) as unknown:
        record_choice(deeptwin, EVAL, "pair-0099", "left", seconds=1.0)
    assert unknown.value.code == "invalid_choice"
    assert not path.exists()

    choice = record_choice(deeptwin, EVAL, "pair-0001", "right", seconds=1.23456)
    assert (choice.pair, choice.chosen, choice.seconds) == ("pair-0001", "right", 1.235)
    recorded = path.read_bytes()

    for pair_id in ("pair-0001", "pair-0099"):
        with pytest.raises(DeeptwinError) as info:
            record_choice(deeptwin, EVAL, pair_id, "left", seconds=1.0)
        assert info.value.code == "invalid_choice"
    assert path.read_bytes() == recorded
    assert [c["chosen"] for c in choice_lines(in_example)] == ["right"]


def test_broken_choice_line_is_reported_with_file_and_line(in_example: Path) -> None:
    make_eval()
    judge(EVAL, input="1\n")
    path = eval_dir(in_example) / "choices.jsonl"
    path.write_bytes(path.read_bytes() + b'{"pair": "pair-0002", "cho\n')

    judged = error_json(judge(EVAL, "--json", input="2\n"), "eval judge", "invalid_file")
    reported = error_json(invoke("eval", "report", EVAL, "--json"), "eval report", "invalid_file")

    prefix = ".deeptwin/eval/eval-0001/choices.jsonl:2:"
    assert judged.startswith(prefix)
    assert reported.startswith(prefix)


# 수용 테스트 13: 30쌍 중 20승


@pytest.mark.acceptance
def test_acceptance_13_twenty_wins_of_thirty_pairs_give_p_0_0494(in_example: Path) -> None:
    for n in range(28):
        task_file = in_example / "extra-task.yaml"
        task_file.write_text(SPARE_TASK.format(id=f"task-{301 + n:04d}", n=n + 1), "utf-8")
        ok_json(invoke("task", "add", "extra-task.yaml", "--json"), "task add")

    body = make_eval()
    assert body["pairs"] == 30
    assert len(body["tasks"]) == 30
    judged = ok_json(
        judge(EVAL, "--json", input=answers_for(in_example, [n < 20 for n in range(30)])),
        "eval judge",
    )
    report = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")

    assert judged == {"eval": EVAL, "chosen": 30, "remaining": 0}
    [comparison] = report["comparisons"]
    assert (comparison["against"], comparison["pairs"], comparison["wins"]) == ("base", 30, 20)
    assert comparison["selection_rate"] == 20 / 30
    assert round(comparison["p_value"], 4) == 0.0494
    markdown = (eval_dir(in_example) / "report.md").read_text("utf-8")
    assert "0.0494" in markdown
    assert "66.7%" in markdown


# p값


def test_p_value_of_twenty_wins_in_thirty_pairs() -> None:
    exact = sum(math.comb(30, k) for k in range(20, 31)) / 2**30

    assert p_value(20, 30) == exact
    assert round(p_value(20, 30), 4) == 0.0494


@pytest.mark.parametrize("pairs", [0, 1, 2, 7, 30])
def test_p_value_without_wins_is_one(pairs: int) -> None:
    assert p_value(0, pairs) == 1.0


@pytest.mark.parametrize("pairs", [1, 2, 7, 30])
def test_p_value_when_every_pair_is_won(pairs: int) -> None:
    assert p_value(pairs, pairs) == 2.0**-pairs


@pytest.mark.parametrize(("wins", "pairs"), [(3, 2), (-1, 2), (0, -1)])
def test_p_value_refuses_impossible_counts(wins: int, pairs: int) -> None:
    with pytest.raises(ValueError):
        p_value(wins, pairs)


# 평가 모듈은 저장 계층으로만 파일에 닿는다


EVAL_PACKAGE = Path(deeptwin.eval.__file__).parent
FORBIDDEN_MODULES = {"os", "shutil", "io", "pathlib"}
FILE_CALLS = {
    "open",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "mkdir",
    "iterdir",
    "unlink",
    "glob",
}


def file_access(source: str) -> list[str]:
    """금지한 import와 파일 호출. `<줄>: <이름>`이다."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [
                f"{node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in FORBIDDEN_MODULES
            ]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0 and module.split(".")[0] in FORBIDDEN_MODULES:
                found.append(f"{node.lineno}: from {module} import")
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in FILE_CALLS:
                found.append(f"{node.lineno}: {name}()")
    return found


def test_eval_package_reaches_files_only_through_the_store() -> None:
    sources = sorted(EVAL_PACKAGE.glob("*.py"))
    assert {p.name for p in sources} == {
        "__init__.py",
        "judging.py",
        "pairs.py",
        "reporting.py",
        "stats.py",
    }

    found = [f"{p.name}:{f}" for p in sources for f in file_access(p.read_text("utf-8"))]

    assert found == []


def test_file_access_check_finds_what_it_forbids() -> None:
    source = (
        "import os\n"
        "import os.path\n"
        "from pathlib import Path\n"
        "from io import StringIO\n"
        "import shutil\n"
        "open('x')\n"
        "Path('x').read_text()\n"
        "folder.mkdir()\n"
        "folder.glob('*')\n"
    )

    assert len(file_access(source)) == 9
