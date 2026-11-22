"""예제(`examples/inquiry-reply`)의 봉인 평가를 처음부터 끝까지 돈다. 데이터는 모두 가상이다.

새 예제 복사본에서 봉인 과제 3개를 세 조건으로 만들고(결과물 9개, 쌍 6개), 터미널과 웹 화면에서
나눠 고르고, 보고서를 내고, 원장을 검사한다. 예제 README의 평가하는 법과 같은 순서다. 섞기 규칙,
해시, 웹 보안, 보고서 형식의 세부는 다른 파일이 보고, 여기서는 흐름과 상태 변화만 본다.

기본 공급자 claude의 길은 가짜 claude 스크립트로 보고, 생성 중 Ctrl-C는 넷째 생성에서 멈추는 가짜
공급자로 본다. 웹 판정은 127.0.0.1만 쓰고 바깥 네트워크와 모델은 쓰지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

import claude_stub
from conftest import EXAMPLE
from deeptwin.llm import FakeProvider
from test_cli import (
    calls,
    error_json,
    files_under,
    interrupted_json,
    invoke,
    ledger,
    ok_json,
    use_stub_claude,
)
from test_eval import (
    EVAL,
    FAKE,
    KEEPS,
    answers_for,
    choice_lines,
    eval_dir,
    files_in,
    judge,
    pair_lines,
)
from test_eval_examples import (
    CONDITION_ORDER,
    SEALED_PAIRS,
    assert_blind_text,
    comparison_counts,
    key_of,
)
from test_eval_sealed import SEALED, ledger_bytes, run_lines, seal_lines, use_provider
from test_eval_web import Judge, assert_blind, serve  # noqa: F401
from test_example import GOLDEN, snapshot

FULL_WINS = [True, True, False, True, False, True]
"""쌍 목록 순서로 쌍마다 바탕+딥트윈을 고를지(참) 상대를 고를지(거짓)."""
P_VALUES = {0: 1.0, 1: 0.875, 2: 0.5, 3: 0.125}
"""세 쌍 가운데 바탕+딥트윈이 이긴 횟수마다의 한쪽 꼬리 이항 검정 p값."""
ALL_SIX = "1\n2\n1\n2\n1\n2\n"
"""여섯 쌍을 모두 고르는 터미널 입력."""
THREE_CALLS_EACH = [(condition, 3) for condition in CONDITION_ORDER]
"""보고서의 `costs`: 봉인 과제 3개라 조건마다 호출 3번."""


@dataclass(frozen=True)
class Walk:
    """예제의 봉인 평가를 가짜 모델로 처음부터 끝까지 돈 기록."""

    made: Result
    """① 쌍 만들기(`--json`)."""
    entries: list[str]
    """①을 마친 뒤 원장 줄의 `type`."""
    outputs: list[str]
    """①을 마친 뒤 평가 폴더 `outputs/`의 파일."""
    first: Result
    """② 터미널 판정(글 모드). 두 줄을 주고 입력이 끝난다."""
    early: Result
    """③ 다 고르기 전에 낸 보고서(`--json`)."""
    early_files: list[str]
    """③을 마친 뒤 평가 폴더의 파일."""
    web: Judge
    """④ 웹 판정(`--limit 2`)으로 두 쌍."""
    on_web: Result
    """④를 띄운 명령의 결과."""
    second: Result
    """⑤ 터미널 판정(`--json`)으로 남은 두 쌍."""
    reported: Result
    """⑥ 보고서(`--json`)."""
    verified: Result
    """⑦ `verify --json`."""


def side_for(key: dict[str, Any], pair_id: str, full_wins: bool) -> str:
    """웹 판정에서 고를 쪽. `full_wins`면 바탕+딥트윈 쪽, 아니면 상대 쪽이다."""
    full = "left" if key[pair_id]["left"] == "full" else "right"
    return full if full_wins else {"left": "right", "right": "left"}[full]


def walk(root: Path, start_web: Callable[..., Judge]) -> Walk:
    """새 예제 복사본 `root`에서 봉인 평가를 끝까지 돈다. 고르는 쪽은 `FULL_WINS`를 따른다.

    `start_web`은 웹 판정을 띄우는 fixture `serve`다.
    """
    made = invoke(*SEALED_PAIRS, *FAKE, "--json")
    assert made.exit_code == 0, made.output
    entries = [entry["type"] for entry in ledger(root)]
    outputs = files_in(eval_dir(root) / "outputs")
    answers = answers_for(root, FULL_WINS).splitlines(keepends=True)

    first = judge(EVAL, input="".join(answers[:2]))
    early = invoke("eval", "report", EVAL, "--json")
    early_files = files_in(eval_dir(root))

    key = key_of(root)["pairs"]
    pairs = pair_lines(root)
    session = start_web("--limit", "2")
    for index in (2, 3):
        session.get()
        pair_id = pairs[index]["id"]
        session.choose(pair_id, side_for(key, pair_id, FULL_WINS[index]))
    on_web = session.finish()

    second = judge(EVAL, "--json", input="".join(answers[4:]))
    reported = invoke("eval", "report", EVAL, "--json")
    verified = invoke("verify", "--json")
    return Walk(
        made=made,
        entries=entries,
        outputs=outputs,
        first=first,
        early=early,
        early_files=early_files,
        web=session,
        on_web=on_web,
        second=second,
        reported=reported,
        verified=verified,
    )


def costs(report: dict[str, Any]) -> list[tuple[str, int]]:
    """보고서의 조건마다 (조건, 호출 수)."""
    return [(cost["condition"], cost["calls"]) for cost in report["costs"]]


# 예제 끝까지


def test_example_sealed_eval_goes_from_pairs_to_report_and_verify(
    in_example: Path,
    serve: Callable[..., Judge],  # noqa: F811
    from_source: str | None,
) -> None:
    done = walk(in_example, serve)

    made = ok_json(done.made, "eval pairs")
    assert (made["eval"], made["tasks"], made["pairs"], made["reused"]) == (EVAL, SEALED, 6, [])
    assert done.entries == ["task"] * 10 + ["seal_open"] + ["run"] * 9
    assert done.outputs == sorted(f"{c}/{task}.md" for c in CONDITION_ORDER for task in SEALED)

    assert done.first.exit_code == 0, done.first.output
    assert "이번에 고른 쌍 2개, 남은 쌍 4개" in done.first.stdout
    message = error_json(done.early, "eval report", "judging_unfinished")
    assert "4개" in message
    assert "report.md" not in done.early_files
    assert "report.json" not in done.early_files

    responses = done.web.responses
    assert "쌍 3/6" in responses[0].body
    assert "남은 쌍 2개" in responses[-1].body
    assert done.on_web.exit_code == 0, done.on_web.output
    judged = ok_json(done.second, "eval judge")
    assert judged == {"eval": EVAL, "chosen": 2, "remaining": 0}

    # 고른 쌍은 쌍 목록 순서이고, 고른 쪽은 정해 둔 대로다
    key = key_of(in_example)["pairs"]
    choices = choice_lines(in_example)
    assert [choice["pair"] for choice in choices] == [pair["id"] for pair in pair_lines(in_example)]
    assert [key[choice["pair"]][choice["chosen"]] == "full" for choice in choices] == FULL_WINS

    report = ok_json(done.reported, "eval report")
    assert (report["split"], report["pairs"]) == ("sealed", 6)
    assert [c["against"] for c in report["comparisons"]] == ["base", "examples"]
    for comparison in report["comparisons"]:
        pairs, wins = comparison_counts(in_example, comparison["against"])
        assert (comparison["pairs"], comparison["judged"], pairs) == (3, 3, 3)
        assert comparison["wins"] == wins
        assert comparison["selection_rate"] == wins / 3
        assert comparison["p_value"] == pytest.approx(P_VALUES[wins])
    assert costs(report) == THREE_CALLS_EACH
    assert report["prompt_versions"] == [None]
    assert report["commit"] == from_source
    assert (report["reused"], report["reference_changed"]) == ([], [])
    assert (report["skill_changed"], report["package_changed"]) == (False, False)
    folder = eval_dir(in_example)
    assert (folder / "report.json").is_file()
    markdown = (folder / "report.md").read_text("utf-8")
    assert "| 바탕+딥트윈 대 바탕만 | 3 | 3 |" in markdown
    assert "| 바탕+딥트윈 대 바탕+예시 | 3 | 3 |" in markdown

    verified = ok_json(done.verified, "verify")
    assert (verified["lines"], verified["sealed"]) == (20, 3)


def test_the_flow_names_no_condition_run_or_output(
    in_example: Path,
    serve: Callable[..., Judge],  # noqa: F811
) -> None:
    done = walk(in_example, serve)

    pairs = (eval_dir(in_example) / "pairs.jsonl").read_text("utf-8")
    judging = (done.first, done.on_web, done.second)
    for result in judging:
        assert result.exit_code == 0, result.output
    assert_blind_text(
        pairs,
        done.made.stdout,
        *(result.stdout for result in judging),
        *(result.stderr for result in judging),
    )
    # 웹 응답(헤더와 본문)은 소문자로 바꿔도 조건 말이 없고 "바탕"도 없다
    assert_blind(done.web.responses)


def test_the_flow_leaves_the_example_and_the_golden_files_alone(
    in_example: Path,
    serve: Callable[..., Judge],  # noqa: F811
) -> None:
    repo_ledger = EXAMPLE / ".deeptwin" / "ledger.jsonl"
    ledger_before = repo_ledger.read_bytes()
    golden = files_under(GOLDEN)
    watched = snapshot(in_example)

    walk(in_example, serve)

    assert len(ledger_before.splitlines()) == 10
    assert repo_ledger.read_bytes() == ledger_before
    assert files_under(GOLDEN) == golden
    assert snapshot(in_example) == watched


# 기본 공급자 claude


def test_default_provider_claude_makes_the_nine_outputs_and_the_report(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_stub_claude(monkeypatch)

    made = ok_json(invoke(*SEALED_PAIRS, "--json"), "eval pairs")

    assert made["pairs"] == 6
    runs = key_of(in_example)["runs"]
    assert list(runs) == SEALED
    run_ids = [runs[task][condition] for task in SEALED for condition in CONDITION_ORDER]
    for run_id in run_ids:
        [call] = calls(in_example, run_id)
        assert call["provider"] == "claude"
        assert call["model"] == claude_stub.MAIN_MODEL
        assert call["version"] == claude_stub.VERSION
    assert files_under(eval_dir(in_example) / "outputs") == {
        f"{condition}/{task}.md": claude_stub.RESULT.encode("utf-8")
        for condition in CONDITION_ORDER
        for task in SEALED
    }

    chosen = judge(EVAL, input=ALL_SIX)
    assert chosen.exit_code == 0, chosen.output
    report = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")
    assert costs(report) == THREE_CALLS_EACH
    verified = ok_json(invoke("verify", "--json"), "verify")
    assert (verified["lines"], verified["sealed"]) == (20, 3)


def test_without_claude_the_sealed_eval_opens_nothing(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = ledger_bytes(in_example)
    monkeypatch.setenv("PATH", "")

    message = error_json(invoke(*SEALED_PAIRS, "--json"), "eval pairs", "claude_not_found")

    assert "Claude Code" in message
    assert not (in_example / ".deeptwin" / "eval").exists()
    assert not (in_example / ".deeptwin" / "runs").exists()
    # 묶음을 열지 않았으므로 seal_open 줄도 없다
    assert ledger_bytes(in_example) == before


# 생성 중 Ctrl-C


class _StopsAtTheFourth:
    """넷째 생성에서 Ctrl-C를 누른 가짜 공급자. 앞의 셋에는 `answer`를 준다."""

    name = "fake"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, timeout: float = 120
    ) -> str:
        self.calls += 1
        if self.calls == 4:
            raise KeyboardInterrupt
        return self.answer


def test_ctrl_c_while_generating_keeps_the_first_task_and_resume_makes_the_rest(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = (in_example / KEEPS).read_bytes().decode("utf-8")
    use_provider(monkeypatch, _StopsAtTheFourth(answer))

    interrupted_json(invoke(*SEALED_PAIRS, *FAKE, "--json"), "eval pairs")

    assert len(seal_lines(in_example)) == 1
    made = [entry["id"] for entry in run_lines(in_example)]
    assert len(made) == 3
    # 멈춘 넷째 생성의 실행 폴더는 남지 않는다
    runs_folder = in_example / ".deeptwin" / "runs"
    assert sorted(p.name for p in runs_folder.iterdir()) == sorted(made)
    key = key_of(in_example)
    assert list(key["runs"]) == ["task-0101"]
    assert list(key["runs"]["task-0101"]) == CONDITION_ORDER
    assert not (eval_dir(in_example) / "pairs.jsonl").exists()
    verified = ok_json(invoke("verify", "--json"), "verify")
    assert (verified["lines"], verified["sealed"]) == (14, 3)
    error_json(judge(EVAL, "--json", input="1\n"), "eval judge", "eval_incomplete")

    repeats = use_provider(monkeypatch, FakeProvider([answer] * 6))
    body = ok_json(invoke("eval", "pairs", "--resume", EVAL, *FAKE, "--json"), "eval pairs")

    assert repeats == [6]
    assert body["pairs"] == 6
    assert len(seal_lines(in_example)) == 1
    assert len(run_lines(in_example)) == 9
    chosen = judge(EVAL, input=ALL_SIX)
    assert chosen.exit_code == 0, chosen.output
    report = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")
    # 멈춘 호출은 세지 않는다
    assert costs(report) == THREE_CALLS_EACH
