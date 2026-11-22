"""봉인 평가: 묶음 열기(`seal_open` 줄), 재사용, `--task`, 이어 가기(`--resume`), 기준 알림, 보고서.

예제(`examples/inquiry-reply`)의 복사본에서 가짜 모델로 돈다. 예제의 봉인 과제 셋을 쓰고, 더 필요한
봉인 과제는 테스트 안에서 가상으로 만든다. 네트워크와 모델을 쓰지 않는다.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import pytest
import yaml
from typer.testing import Result

import deeptwin.cli
from deeptwin.cli import main, web
from deeptwin.cli.session import NOTHING_LEFT
from deeptwin.errors import DeeptwinError
from deeptwin.eval import open_sealed, prepare_pairs, prepare_resume
from deeptwin.llm import FakeProvider, Provider
from deeptwin.store.project import DeepTwin
from test_cli import error_json, forbid_provider, invoke, jsonl, ledger, ok_json, parsed, runner
from test_eval import (
    FAKE,
    HIDDEN,
    KEEPS,
    PAIRS,
    PAIRS_RESULT_KEYS,
    SKILL,
    _add_sealed_task_without_context,
    _cut_the_last_ledger_line,
    _FailsOnTheSecondCall,
    _leave_alone,
    _skill_without_tasks,
    eval_dir,
    files_in,
    judge,
    make_eval,
    read_json,
    tree,
)

SEALED = ["task-0101", "task-0102", "task-0103"]
"""예제의 봉인 과제. 파일 이름순이다."""
SEALED_PAIRS = ("eval", "pairs", SKILL, "--split", "sealed")
FIRST, SECOND = "eval-0001", "eval-0002"
REFERENCE_WORDS = ("수료하시려면", "13번 이상", "12번 이상", "노트북 사양은", "SUM이나 COUNT")
"""예제 봉인 과제의 기준에만 있는 글. 출력, 오류, 알림, 판정 화면에 나오면 안 된다."""
SEAL_KEYS = ["id", "type", "ts", "eval", "skill", "tasks", "reused", "prev_hash", "hash"]
NOTICE = "봉인 과제의 기준이 등록 때와 다릅니다: {}. 판정은 그대로 하고 보고서에 표시합니다."
REUSED_LINE = "다른 평가에서 이미 연 봉인 과제가 들어 있습니다: {}. 보고서에 재사용으로 적습니다."
REPORT_REUSED = "- 재사용: 다른 평가에서 이미 연 봉인 과제가 들어 있습니다({})."
REPORT_CHANGED = "- 기준이 등록 때와 다른 봉인 과제: {}"


def sealed_eval(*options: str) -> dict[str, Any]:
    return ok_json(invoke(*SEALED_PAIRS, *FAKE, *options, "--json"), "eval pairs")


def resume(eval_id: str, *options: str) -> dict[str, Any]:
    return ok_json(invoke("eval", "pairs", "--resume", eval_id, *FAKE, *options), "eval pairs")


def seal_lines(root: Path) -> list[dict[str, Any]]:
    return [e for e in ledger(root) if e["type"] == "seal_open"]


def run_lines(root: Path) -> list[dict[str, Any]]:
    return [e for e in ledger(root) if e["type"] == "run"]


def ledger_bytes(root: Path) -> bytes:
    return (root / ".deeptwin" / "ledger.jsonl").read_bytes()


def task_file(root: Path, task_id: str) -> Path:
    return root / ".deeptwin" / "tasks" / "sealed" / f"{task_id}.yaml"


def change_reference(root: Path, old: str = "13번 이상", new: str = "12번 이상") -> None:
    """`task-0101`의 기준 글 한 곳을 손으로 고친다."""
    path = task_file(root, "task-0101")
    text = path.read_bytes().decode("utf-8")
    assert text.count(old) == 1
    path.write_bytes(text.replace(old, new).encode("utf-8"))


def restore_reference(root: Path) -> None:
    change_reference(root, "12번 이상", "13번 이상")


def assert_no_reference(*texts: str) -> None:
    for text in texts:
        for word in REFERENCE_WORDS:
            assert word not in text


def judge_all(eval_id: str, *options: str) -> Result:
    """세 쌍을 모두 고른다."""
    result = judge(eval_id, *options, input="1\n2\n1\n")
    assert result.exit_code == 0, result.output
    return result


def use_provider(monkeypatch: pytest.MonkeyPatch, provider: Provider) -> list[int]:
    """fake 공급자 자리에 `provider`를 둔다. 명령줄이 넘긴 `fake_repeat`를 차례로 모은다."""
    repeats: list[int] = []

    def make(options: main.ProviderOptions) -> Provider:
        repeats.append(options.fake_repeat)
        return provider

    monkeypatch.setitem(main.PROVIDERS, "fake", make)
    return repeats


@pytest.fixture
def no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """웹 판정이 서버를 열어 기다리면 멈춰 서지 않고 바로 실패한다."""

    def wait(done: object) -> NoReturn:
        raise AssertionError("서버를 열지 않아야 합니다")

    monkeypatch.setattr(web, "wait_until_done", wait)


# 처음 연 봉인 평가


def test_first_sealed_eval_leaves_one_seal_open_line_before_its_runs(in_example: Path) -> None:
    result = invoke(*SEALED_PAIRS, *FAKE, "--json")

    body = ok_json(result, "eval pairs")
    assert list(body) == PAIRS_RESULT_KEYS
    assert body == {
        "eval": FIRST,
        "skill": SKILL,
        "split": "sealed",
        "tasks": SEALED,
        "pairs": 3,
        "seed": FIRST,
        "reused": [],
    }
    entries = ledger(in_example)
    assert [e["type"] for e in entries] == ["task"] * 10 + ["seal_open"] + ["run"] * 6
    seal = entries[10]
    assert list(seal) == SEAL_KEYS
    assert (seal["id"], seal["eval"], seal["skill"]) == ("seal-0001", FIRST, SKILL)
    assert (seal["tasks"], seal["reused"]) == (SEALED, [])
    assert all(e["split"] == "sealed" for e in entries[11:])
    assert sorted(e["task"] for e in entries[11:]) == sorted(SEALED * 2)
    info = read_json(eval_dir(in_example) / "eval.json")
    assert (info["split"], info["tasks"]) == ("sealed", SEALED)
    assert (info["seal_open"], info["reused"]) == ("seal-0001", [])
    assert len(jsonl(eval_dir(in_example) / "pairs.jsonl")) == 3
    verified = ok_json(invoke("verify", "--json"), "verify")
    assert (verified["lines"], verified["sealed"]) == (17, 3)
    assert_no_reference(result.stdout, result.stderr)
    for word in (*HIDDEN, "run-"):
        assert word not in result.stdout


def test_sealed_pair_list_and_text_mode_show_no_condition_or_reference(in_example: Path) -> None:
    result = invoke(*SEALED_PAIRS, *FAKE)

    assert result.exit_code == 0, result.output
    assert f"deeptwin eval judge {FIRST}" in result.stdout
    assert "재사용" not in result.stdout
    pairs = (eval_dir(in_example) / "pairs.jsonl").read_text("utf-8")
    for text in (result.stdout, pairs):
        assert_no_reference(text)
        for word in (*HIDDEN, "run-"):
            assert word not in text
    assert result.stderr == ""


# 다시 연 묶음


def test_opening_the_same_bundle_again_makes_pairs_and_marks_them_reused(in_example: Path) -> None:
    sealed_eval()

    body = sealed_eval()

    assert (body["eval"], body["tasks"], body["pairs"]) == (SECOND, SEALED, 3)
    assert body["reused"] == SEALED
    assert len(jsonl(eval_dir(in_example, SECOND) / "pairs.jsonl")) == 3
    info = read_json(eval_dir(in_example, SECOND) / "eval.json")
    assert (info["seal_open"], info["reused"]) == ("seal-0002", SEALED)
    first, second = seal_lines(in_example)
    assert (first["id"], first["eval"], first["reused"]) == ("seal-0001", FIRST, [])
    assert (second["id"], second["eval"], second["reused"]) == ("seal-0002", SECOND, SEALED)
    assert read_json(eval_dir(in_example) / "eval.json")["reused"] == []
    verified = ok_json(invoke("verify", "--json"), "verify")
    assert (verified["lines"], verified["sealed"]) == (24, 3)


def test_text_mode_says_the_bundle_was_opened_before(in_example: Path) -> None:
    sealed_eval()

    result = invoke(*SEALED_PAIRS, *FAKE)

    assert result.exit_code == 0, result.output
    assert REUSED_LINE.format(", ".join(SEALED)) in result.stdout.splitlines()
    assert f"deeptwin eval judge {SECOND}" in result.stdout
    for word in (*HIDDEN, "run-"):
        assert word not in result.stdout
    assert_no_reference(result.stdout)


# --task


def test_task_option_narrows_the_bundle_and_counts_only_those_tasks(in_example: Path) -> None:
    narrowed = sealed_eval("--task", "task-0102")
    whole = sealed_eval()

    assert (narrowed["tasks"], narrowed["pairs"], narrowed["reused"]) == (["task-0102"], 1, [])
    assert (whole["tasks"], whole["pairs"]) == (SEALED, 3)
    assert whole["reused"] == ["task-0102"]
    assert [(s["tasks"], s["reused"]) for s in seal_lines(in_example)] == [
        (["task-0102"], []),
        (SEALED, ["task-0102"]),
    ]
    assert read_json(eval_dir(in_example, SECOND) / "eval.json")["reused"] == ["task-0102"]


def test_task_order_is_the_file_order_and_repeats_count_once(in_example: Path) -> None:
    body = sealed_eval("--task", "task-0102", "--task", "task-0101", "--task", "task-0102")

    assert (body["tasks"], body["pairs"]) == (["task-0101", "task-0102"], 2)
    assert read_json(eval_dir(in_example) / "eval.json")["tasks"] == ["task-0101", "task-0102"]
    assert seal_lines(in_example)[0]["tasks"] == ["task-0101", "task-0102"]


def test_task_option_narrows_other_splits_too(in_example: Path) -> None:
    body = ok_json(invoke(*PAIRS, *FAKE, "--task", "task-0202", "--json"), "eval pairs")

    assert (body["tasks"], body["pairs"], body["reused"]) == (["task-0202"], 1, [])
    assert seal_lines(in_example) == []


@pytest.mark.parametrize(
    "unknown",
    [["task-9999"], ["task-0001"], ["task-0101", "task-9999"]],
    ids=["missing", "other-split", "one-of-two"],
)
def test_task_outside_the_bundle_writes_nothing(
    in_example: Path, monkeypatch: pytest.MonkeyPatch, unknown: list[str]
) -> None:
    before = tree(in_example)
    forbid_provider(monkeypatch)
    options = [arg for task_id in unknown for arg in ("--task", task_id)]

    result = invoke(*SEALED_PAIRS, *FAKE, *options, "--json")

    message = error_json(result, "eval pairs", "task_not_found")
    missing = [task_id for task_id in unknown if task_id not in SEALED]
    assert all(task_id in message for task_id in missing)
    assert_no_reference(message, result.stderr)
    assert tree(in_example) == before
    assert not (in_example / ".deeptwin" / "eval").exists()


# 생성 전 실패


@pytest.mark.parametrize(
    ("prepare", "args", "code", "forbid"),
    [
        (_add_sealed_task_without_context, (*SEALED_PAIRS, *FAKE), "context_required", True),
        (_leave_alone, (*SEALED_PAIRS, "--provider", "fake"), "fake_answer_required", False),
        (_cut_the_last_ledger_line, (*SEALED_PAIRS, *FAKE), "ledger_broken", True),
        (
            _skill_without_tasks,
            ("eval", "pairs", "notice", "--split", "sealed", *FAKE),
            "no_tasks",
            True,
        ),
    ],
    ids=["no-context", "no-fake-answer", "broken-ledger", "no-tasks"],
)
def test_sealed_pairs_that_stop_before_generating_leave_no_seal_open_line(
    in_example: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepare: Callable[[Path], None],
    args: tuple[str, ...],
    code: str,
    forbid: bool,
) -> None:
    prepare(in_example)
    before = ledger_bytes(in_example)
    if forbid:
        forbid_provider(monkeypatch)

    result = invoke(*args, "--json")

    message = error_json(result, "eval pairs", code)
    assert_no_reference(message, result.stderr)
    assert not (in_example / ".deeptwin" / "eval").exists()
    assert not (in_example / ".deeptwin" / "runs").exists()
    assert ledger_bytes(in_example) == before


# 생성 중 실패 뒤 이어 가기


def test_resume_after_a_failure_makes_only_the_rest_and_opens_no_new_line(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, _FailsOnTheSecondCall())

    failed = invoke(*SEALED_PAIRS, *FAKE, "--json")

    error_json(failed, "eval pairs", "provider_failed")
    assert len(seal_lines(in_example)) == 1
    [first_run] = run_lines(in_example)
    folder = eval_dir(in_example)
    assert files_in(folder) == ["eval.json", "key.json", "outputs/base/task-0101.md"]
    key = read_json(folder / "key.json")
    assert key["runs"] == {"task-0101": {"base": first_run["id"]}}
    assert key["pairs"] == {}
    assert not (folder / "pairs.jsonl").exists()
    ok_json(invoke("verify", "--json"), "verify")
    message = error_json(judge(FIRST, "--json", input="1\n"), "eval judge", "eval_incomplete")
    assert f"deeptwin eval pairs --resume {FIRST}" in message
    seal = read_json(folder / "eval.json")["seal_open"]
    assert seal == "seal-0001"

    repeats = use_provider(
        monkeypatch, FakeProvider([(in_example / KEEPS).read_bytes().decode("utf-8")] * 5)
    )
    body = resume(FIRST, "--json")

    assert repeats == [5]
    assert body == {
        "eval": FIRST,
        "skill": SKILL,
        "split": "sealed",
        "tasks": SEALED,
        "pairs": 3,
        "seed": FIRST,
        "reused": [],
    }
    runs = run_lines(in_example)
    assert len(runs) == 6
    assert runs[0] == first_run
    assert len(seal_lines(in_example)) == 1
    assert len(jsonl(folder / "pairs.jsonl")) == 3
    info = read_json(folder / "eval.json")
    assert (info["seal_open"], info["reused"]) == (seal, [])
    key = read_json(folder / "key.json")
    assert list(key["runs"]) == SEALED
    assert all(list(conditions) == ["base", "full"] for conditions in key["runs"].values())
    assert key["runs"]["task-0101"]["base"] == first_run["id"]
    assert sorted(r for c in key["runs"].values() for r in c.values()) == [r["id"] for r in runs]
    assert len(key["pairs"]) == 3

    judge_all(FIRST)
    reported = ok_json(invoke("eval", "report", FIRST, "--json"), "eval report")
    assert (reported["pairs"], reported["reused"], reported["reference_changed"]) == (3, [], [])
    ok_json(invoke("verify", "--json"), "verify")
    assert len(seal_lines(in_example)) == 1


def test_resume_of_a_spare_eval_makes_the_rest_without_a_seal_open_line(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, _FailsOnTheSecondCall())
    error_json(invoke(*PAIRS, *FAKE, "--json"), "eval pairs", "provider_failed")
    monkeypatch.setitem(main.PROVIDERS, "fake", main._fake_provider)

    result = invoke("eval", "pairs", "--resume", FIRST, *FAKE)

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == f"평가 {FIRST}을 이어 만들었습니다. 이번에 만든 결과물 3개, 쌍 2개."
    assert f"deeptwin eval judge {FIRST}" in result.stdout
    assert "재사용" not in result.stdout
    for word in (*HIDDEN, "run-"):
        assert word not in result.stdout
    assert len(run_lines(in_example)) == 4
    assert seal_lines(in_example) == []
    info = read_json(eval_dir(in_example) / "eval.json")
    assert (info["seal_open"], info["reused"]) == (None, [])
    assert len(jsonl(eval_dir(in_example) / "pairs.jsonl")) == 2


def test_resume_rebuilds_a_check_that_failed_after_the_run(in_example: Path) -> None:
    checks = in_example / "skills" / SKILL / "checks.py"
    working = checks.read_bytes()
    checks.write_text(
        "def no_outcome_promise(output: str) -> bool:\n"
        "    raise RuntimeError('가짜 검사 함수가 멈췄습니다')\n\n\n"
        "def no_contact_details(output: str) -> bool:\n"
        "    return True\n",
        encoding="utf-8",
    )
    error_json(invoke(*SEALED_PAIRS, *FAKE, "--json"), "eval pairs", "check_failed")
    assert not (eval_dir(in_example) / "key.json").exists()
    checks.write_bytes(working)

    body = resume(FIRST, "--json")

    assert body["pairs"] == 3
    # 검사가 멈춘 생성은 대응표에 없으므로 다시 만든다
    assert len(run_lines(in_example)) == 7
    key = read_json(eval_dir(in_example) / "key.json")
    assert run_lines(in_example)[0]["id"] not in {
        r for c in key["runs"].values() for r in c.values()
    }
    ok_json(invoke("verify", "--json"), "verify")


# 이어 갈 것 없음


def test_resume_of_a_finished_eval_changes_nothing(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = sealed_eval()
    before = tree(in_example)
    repeats = use_provider(monkeypatch, FakeProvider([]))

    again = resume(FIRST, "--json")
    text = invoke("eval", "pairs", "--resume", FIRST, *FAKE)

    assert again == made
    assert repeats == [0, 0]
    assert text.exit_code == 0, text.output
    assert "이번에 만든 결과물 0개, 쌍 3개." in text.stdout
    assert tree(in_example) == before


# 틀린 이어 가기


def test_resume_of_an_unknown_eval_creates_nothing(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed_eval()
    before = tree(in_example)
    forbid_provider(monkeypatch)

    message = error_json(
        invoke("eval", "pairs", "--resume", "eval-0099", *FAKE, "--json"),
        "eval pairs",
        "eval_not_found",
    )

    assert "eval-0099" in message
    assert tree(in_example) == before


@pytest.mark.parametrize(
    ("args", "named"),
    [
        (("eval", "pairs", "--resume", FIRST, SKILL), "SKILL"),
        (("eval", "pairs", "--resume", FIRST, "--split", "spare"), "--split"),
        (("eval", "pairs", "--resume", FIRST, "--task", "task-0101"), "--task"),
        (("eval", "pairs", "--resume", FIRST, "--seed", "s"), "--seed"),
        (("eval", "pairs", "--split", "sealed"), "SKILL"),
        (("eval", "pairs"), "SKILL"),
    ],
    ids=["skill", "split", "task", "seed", "no-skill", "nothing"],
)
def test_wrong_resume_options_exit_2_before_reading_anything(
    in_example: Path, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...], named: str
) -> None:
    sealed_eval()
    before = tree(in_example)

    def no_project(*args: object) -> NoReturn:
        raise AssertionError("프로젝트를 열지 않아야 합니다")

    monkeypatch.setattr(DeepTwin, "open", no_project)

    result = invoke(*args, *FAKE, "--json")

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert named in result.output
    assert tree(in_example) == before


# 판정 시작의 알림


def two_sealed_evals_with_a_changed_reference(root: Path) -> None:
    sealed_eval()
    sealed_eval()
    change_reference(root)


def test_judging_starts_by_naming_the_task_whose_reference_changed(in_example: Path) -> None:
    two_sealed_evals_with_a_changed_reference(in_example)
    lines_before = len(ledger(in_example))

    result = judge_all(SECOND)

    screen = result.stdout
    lines = screen.splitlines()
    assert lines[0] == NOTICE.format("task-0101")
    assert lines[1] == "쌍 1/3"
    assert screen.count(NOTICE.format("task-0101")) == 1
    assert "쌍 3/3" in screen
    assert len(jsonl(eval_dir(in_example, SECOND) / "choices.jsonl")) == 3
    deeptwin = DeepTwin.open(in_example)
    token = open_sealed(deeptwin, SECOND).token
    for task_id in SEALED:
        assert deeptwin.task(task_id, token=token).input.rstrip("\n") in screen
    assert_no_reference(screen)
    for word in (*HIDDEN, "run-"):
        assert word not in screen
    assert result.stderr == ""
    assert len(ledger(in_example)) == lines_before


def test_notice_goes_to_stderr_with_json_and_keeps_the_result_shape(in_example: Path) -> None:
    two_sealed_evals_with_a_changed_reference(in_example)

    result = judge(SECOND, "--json", input="1\n2\n1\n")

    assert result.exit_code == 0, result.output
    assert parsed(result) == {
        "ok": True,
        "command": "eval judge",
        "result": {"eval": SECOND, "chosen": 3, "remaining": 0},
    }
    assert result.stderr.splitlines()[0] == NOTICE.format("task-0101")
    assert "봉인 과제의 기준" not in result.stdout
    assert_no_reference(result.stdout, result.stderr)


def test_web_notice_comes_before_nothing_left_and_opens_no_server(
    in_example: Path, no_server: None
) -> None:
    two_sealed_evals_with_a_changed_reference(in_example)
    judge_all(SECOND)

    result = runner.invoke(main.app, ["eval", "judge", SECOND, "--web", "--json"])

    assert ok_json(result, "eval judge") == {"eval": SECOND, "chosen": 0, "remaining": 0}
    assert result.stderr.splitlines()[:2] == [NOTICE.format("task-0101"), NOTHING_LEFT]
    assert "http://" not in result.stderr


def test_no_notice_without_a_changed_reference_or_for_a_spare_eval(in_example: Path) -> None:
    sealed_eval()
    make_eval()

    unchanged = judge(FIRST, input="1\n2\n1\n")
    change_reference(in_example)
    spare = judge(SECOND, input="1\n2\n")

    for result in (unchanged, spare):
        assert result.exit_code == 0, result.output
        assert "봉인 과제의 기준" not in result.stdout
        assert result.stdout.startswith("쌍 1/")


# 보고서


def test_report_names_reused_tasks_and_the_changed_reference(in_example: Path) -> None:
    two_sealed_evals_with_a_changed_reference(in_example)
    judge_all(SECOND)
    lines_before = len(ledger(in_example))
    folder = eval_dir(in_example, SECOND)

    first = ok_json(invoke("eval", "report", SECOND, "--json"), "eval report")
    saved = tree(folder)
    second = ok_json(invoke("eval", "report", SECOND, "--json"), "eval report")

    assert first == second
    assert (first["reused"], first["reference_changed"]) == (SEALED, ["task-0101"])
    assert [c["pairs"] for c in first["comparisons"]] == [3]
    report = read_json(folder / "report.json")
    assert list(report) == [
        "schema",
        "eval",
        "skill",
        "split",
        "pairs",
        "reused",
        "reference_changed",
        "comparisons",
    ]
    assert (report["reused"], report["reference_changed"]) == (SEALED, ["task-0101"])
    markdown = (folder / "report.md").read_text("utf-8")
    head = markdown.splitlines()[:6]
    assert head == [
        f"# 판정 보고서 {SECOND}",
        "",
        f"- 스킬: {SKILL}, 분할: sealed, 쌍: 3개(모두 골랐습니다)",
        REPORT_REUSED.format(", ".join(SEALED)),
        REPORT_CHANGED.format("task-0101"),
        "",
    ]
    assert tree(folder) == saved
    assert len(ledger(in_example)) == lines_before
    assert_no_reference(markdown, json.dumps(first, ensure_ascii=False))
    text = invoke("eval", "report", SECOND)
    assert text.exit_code == 0, text.output
    assert REPORT_CHANGED.format("task-0101") in text.stdout


def test_first_opened_eval_is_not_reused_and_a_restored_reference_clears(
    in_example: Path,
) -> None:
    two_sealed_evals_with_a_changed_reference(in_example)
    judge_all(SECOND)
    ok_json(invoke("eval", "report", SECOND, "--json"), "eval report")
    judge_all(FIRST)

    earlier = ok_json(invoke("eval", "report", FIRST, "--json"), "eval report")

    assert (earlier["reused"], earlier["reference_changed"]) == ([], ["task-0101"])
    earlier_md = (eval_dir(in_example) / "report.md").read_text("utf-8")
    assert "재사용" not in earlier_md
    restore_reference(in_example)

    later = ok_json(invoke("eval", "report", SECOND, "--json"), "eval report")

    assert (later["reused"], later["reference_changed"]) == (SEALED, [])
    later_md = (eval_dir(in_example, SECOND) / "report.md").read_text("utf-8")
    assert REPORT_REUSED.format(", ".join(SEALED)) in later_md
    assert "기준이 등록 때와 다른" not in later_md


# 예비 평가는 그대로


def test_spare_eval_keeps_empty_seal_fields_and_the_same_report_text(in_example: Path) -> None:
    body = make_eval()
    judge("eval-0001", input="1\n2\n")

    reported = ok_json(invoke("eval", "report", FIRST, "--json"), "eval report")

    assert body["reused"] == []
    info = read_json(eval_dir(in_example) / "eval.json")
    assert (info["seal_open"], info["reused"]) == (None, [])
    assert (reported["reused"], reported["reference_changed"]) == ([], [])
    [c] = reported["comparisons"]
    markdown = (eval_dir(in_example) / "report.md").read_text("utf-8")
    assert markdown == (
        f"# 판정 보고서 {FIRST}\n"
        "\n"
        f"- 스킬: {SKILL}, 분할: spare, 쌍: 2개(모두 골랐습니다)\n"
        "\n"
        "| 비교 | 쌍 | 바탕+딥트윈이 이긴 횟수 | 선택률 | p값 |\n"
        "|------|----|----|----|----|\n"
        f"| 바탕+딥트윈 대 바탕만 | 2 | {c['wins']} | {c['selection_rate'] * 100:.1f}% | "
        f"{c['p_value']:.4f} |\n"
        "\n"
        "p값은 한쪽 꼬리 이항 검정의 값입니다. "
        "두 결과물을 반반으로 고른다고 할 때 이만큼 이상 이길 확률입니다.\n"
    )
    assert seal_lines(in_example) == []


# 봉인 차단


@pytest.mark.parametrize(
    ("command", "args"),
    [("run", ("run", SKILL, "task-0101", *FAKE)), ("compose", ("compose", SKILL, "task-0101"))],
)
def test_run_and_compose_still_refuse_sealed_tasks_after_sealed_evals(
    in_example: Path, command: str, args: tuple[str, ...]
) -> None:
    sealed_eval()
    sealed_eval()
    runs = sorted(p.name for p in (in_example / ".deeptwin" / "runs").iterdir())
    lines = len(ledger(in_example))

    result = invoke(*args, "--json")

    message = error_json(result, command, "sealed_access")
    assert_no_reference(message)
    assert sorted(p.name for p in (in_example / ".deeptwin" / "runs").iterdir()) == runs
    assert len(ledger(in_example)) == lines


# 라이브러리


def test_open_sealed_twice_gives_the_same_line_and_writes_nothing(in_example: Path) -> None:
    sealed_eval()
    sealed_eval()
    deeptwin = DeepTwin.open(in_example)
    before = tree(in_example)
    # 다시 쓰면 같은 바이트여도 새 파일(새 inode)로 바뀐다
    written = (eval_dir(in_example, SECOND) / "eval.json").stat().st_ino

    first = open_sealed(deeptwin, SECOND)
    second = open_sealed(deeptwin, SECOND)

    assert (
        (first.line, first.reused) == (second.line, second.reused) == ("seal-0002", tuple(SEALED))
    )
    assert first.eval.id == SECOND
    assert (first.eval.seal_open, first.eval.reused) == ("seal-0002", SEALED)
    assert tree(in_example) == before
    assert (eval_dir(in_example, SECOND) / "eval.json").stat().st_ino == written


def test_open_sealed_refuses_a_spare_eval_and_an_unknown_eval(in_example: Path) -> None:
    make_eval()
    deeptwin = DeepTwin.open(in_example)
    before = tree(in_example)

    with pytest.raises(ValueError):
        open_sealed(deeptwin, FIRST)
    with pytest.raises(DeeptwinError) as unknown:
        open_sealed(deeptwin, "eval-0099")

    assert unknown.value.code == "eval_not_found"
    assert tree(in_example) == before


def test_open_sealed_numbers_the_line_and_skips_lines_it_cannot_use(in_example: Path) -> None:
    sealed_eval("--task", "task-0101")
    deeptwin = DeepTwin.open(in_example)
    # 사람이 남긴 seal_open 줄. 열 자리 번호는 번호로 세지 않고, tasks가 글 목록이 아닌 줄은
    # 재사용에서 건너뛴다
    deeptwin.append_ledger(
        {"id": "seal-0007", "type": "seal_open", "eval": "eval-0050", "tasks": ["task-0103"]}
    )
    deeptwin.append_ledger(
        {"id": "seal-1234567890", "type": "seal_open", "tasks": ["task-0102", 5]}
    )
    copied = eval_dir(in_example, SECOND)
    copied.mkdir()
    info = read_json(eval_dir(in_example) / "eval.json")
    info.update({"id": SECOND, "tasks": SEALED, "seed": SECOND})
    # 두 필드가 없는 예전 eval.json도 읽고, 줄을 남긴 뒤 두 필드를 적는다
    del info["seal_open"], info["reused"]
    (copied / "eval.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")

    opened = open_sealed(deeptwin, SECOND)

    assert opened.line == "seal-0008"
    assert opened.reused == ("task-0101", "task-0103")
    last = ledger(in_example)[-1]
    assert list(last) == SEAL_KEYS
    assert (last["id"], last["eval"], last["skill"]) == ("seal-0008", SECOND, SKILL)
    assert (last["tasks"], last["reused"]) == (SEALED, ["task-0101", "task-0103"])
    saved = read_json(copied / "eval.json")
    assert list(saved)[-2:] == ["seal_open", "reused"]
    assert (saved["seal_open"], saved["reused"]) == ("seal-0008", ["task-0101", "task-0103"])
    # 먼저 연 평가는 뒤에 연 줄과 상관없이 재사용이 아니다
    assert open_sealed(deeptwin, FIRST).reused == ()
    ok_json(invoke("verify", "--json"), "verify")


def test_changed_references_needs_a_token_and_names_only_changed_tasks(in_example: Path) -> None:
    sealed_eval()
    deeptwin = DeepTwin.open(in_example)

    with pytest.raises(DeeptwinError) as refused:
        deeptwin.changed_references(SEALED)
    assert refused.value.code == "sealed_access"
    assert_no_reference(refused.value.message)

    token = open_sealed(deeptwin, FIRST).token
    assert deeptwin.changed_references(SEALED, token=token) == ()
    change_reference(in_example)
    task_file(in_example, "task-0103").unlink()

    changed = deeptwin.changed_references(SEALED, token=token)

    assert changed == ("task-0101", "task-0103")
    assert deeptwin.changed_references(["task-0103", "task-0101"], token=token) == (
        "task-0103",
        "task-0101",
    )


def test_sealed_file_errors_do_not_show_the_input_or_reference(in_example: Path) -> None:
    sealed_eval()
    path = task_file(in_example, "task-0101")
    data = yaml.safe_load(path.read_bytes().decode("utf-8"))
    data["input"] = ["비밀 문의 글입니다"]
    data["reference"]["text"] = ["비밀 기준 글입니다"]
    path.write_bytes(yaml.safe_dump(data, allow_unicode=True).encode("utf-8"))

    judged = judge(FIRST, "--json", input="1\n2\n1\n")
    made = invoke(*SEALED_PAIRS, *FAKE, "--json")

    for result, command in ((judged, "eval judge"), (made, "eval pairs")):
        message = error_json(result, command, "invalid_file")
        assert message.startswith(".deeptwin/tasks/sealed/task-0101.yaml:")
        assert "비밀" not in result.stdout + result.stderr


def test_prepared_runs_carry_no_sealed_reference(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deeptwin = DeepTwin.open(in_example)
    use_provider(monkeypatch, _FailsOnTheSecondCall())
    error_json(invoke(*SEALED_PAIRS, *FAKE, "--json"), "eval pairs", "provider_failed")

    plans = [prepare_pairs(deeptwin, SKILL, split="sealed"), prepare_resume(deeptwin, FIRST)]

    assert [len(plan.runs) for plan in plans] == [6, 5]
    for plan in plans:
        for planned in plan.runs:
            task = planned.prepared.task
            assert task.reference is None
            assert_no_reference(task.model_dump_json(), repr(planned.prepared))
    # 원장과 기준 검사는 그대로 파일의 기준을 본다
    token = open_sealed(deeptwin, FIRST).token
    assert deeptwin.changed_references(SEALED, token=token) == ()
    assert deeptwin.task("task-0101", token=token).reference is not None


# 토큰은 한곳


SRC = Path(deeptwin.cli.__file__).parent.parent
"""`src/deeptwin`."""


def token_calls(source: str) -> list[int]:
    """`SealedToken(...)`을 부르는 줄."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name == "SealedToken":
                found.append(node.lineno)
    return found


def test_only_the_sealing_module_makes_tokens() -> None:
    sources = sorted(SRC.rglob("*.py"))
    assert SRC / "eval" / "sealing.py" in sources

    making = [p.relative_to(SRC).as_posix() for p in sources if token_calls(p.read_text("utf-8"))]

    assert making == ["eval/sealing.py"]
    assert token_calls("from x import SealedToken\nt = SealedToken()\ny = guard.SealedToken()\n")


def test_command_line_never_touches_the_token() -> None:
    cli = sorted((SRC / "cli").glob("*.py"))
    assert {"main.py", "session.py"} <= {p.name for p in cli}

    for path in cli:
        text = path.read_text("utf-8")
        for name in ("open_sealed", "read_sealed", "SealedToken"):
            assert name not in text, f"{path.name}: {name}"
