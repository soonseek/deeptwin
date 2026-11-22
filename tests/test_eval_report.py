"""보고서의 걸린 시간, 실행 비용, 패키지 버전과 커밋, 프롬프트 버전(`eval report`).

예제(`examples/inquiry-reply`)의 복사본에서 가짜 모델로 돈다. 커밋은 소스의 git에서 읽게 해 두고
(`conftest.from_source`), 기대값은 로컬 `git rev-parse HEAD`다. 네트워크와 모델을 쓰지 않는다.
"""

from __future__ import annotations

import json
import shutil
import statistics
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

import deeptwin.eval.pairs
from deeptwin import provenance
from deeptwin.eval.sealing import SealedOpening, open_sealed
from deeptwin.llm import FakeProvider
from deeptwin.store.project import DeepTwin
from test_cli import error_json, invoke, jsonl, ledger, ok_json, parsed
from test_eval import (
    EVAL,
    FAKE,
    HIDDEN,
    KEEPS,
    PAIRS,
    PAIRS_RESULT_KEYS,
    REPORT_RESULT_KEYS,
    SKILL,
    SPARE_TASK,
    _FailsOnTheSecondCall,
    eval_dir,
    judge,
    read_json,
    tree,
)
from test_eval_examples import SKILL_LINE, _EditsSkillYaml, edit_skill_md
from test_eval_sealed import SEALED_PAIRS, use_provider
from test_eval_web import Judge, assert_blind, serve  # noqa: F401

NAMES = {"base": "바탕만", "examples": "바탕+예시", "full": "바탕+딥트윈"}
PROMPT_NONE = "- 프롬프트 버전: 없음(이 평가의 실행은 프롬프트 자산을 쓰지 않았습니다)"
PROMPT_UNKNOWN = "- 프롬프트 버전: 알 수 없음(원장에서 이 평가의 실행 줄을 찾지 못했습니다)"
NO_RECORD_ROW = "| 바탕만 | 기록 없음 | 기록 없음 | 기록 없음 | 기록 없음 |"
P_SENTENCE = "p값은 한쪽 꼬리 이항 검정의 값입니다."
EXAMPLE_LEDGER_LINES = 10
"""예제 원장의 줄 수. 그 뒤 줄은 테스트가 만든 실행과 평가의 줄이다."""
PROVENANCE_WORDS = ("커밋", "commit", "비용", "calls", "package", "패키지", "prompt_version")
"""쌍 목록, 판정 화면, `eval pairs`와 `eval judge`의 출력에 나오면 안 되는 말."""
EXTRA_CALL = {
    "provider": "fake",
    "model": None,
    "version": None,
    "prompt_version": None,
    "input_chars": 10,
    "output_chars": 20,
    "seconds": 1.5,
    "cached": False,
}
"""실행 하나의 `calls.jsonl`에 더하는 가상의 호출."""


def report_json() -> dict[str, Any]:
    return ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")


def judged_eval(*options: str, answers: str = "1\n2\n") -> None:
    """`eval pairs`를 가짜 모델로 돌리고 `answers`로 모두 고른다. `options`는 스킬부터의 인자다."""
    args = options or PAIRS[2:]
    ok_json(invoke("eval", "pairs", *args, *FAKE, "--json"), "eval pairs")
    result = judge(EVAL, input=answers)
    assert result.exit_code == 0, result.output


def markdown(root: Path) -> str:
    return (eval_dir(root) / "report.md").read_text("utf-8")


def key_runs(root: Path) -> dict[str, dict[str, str]]:
    runs: dict[str, dict[str, str]] = read_json(eval_dir(root) / "key.json")["runs"]
    return runs


def run_ids(root: Path, condition: str) -> list[str]:
    """대응표의 `runs`에서 그 조건의 실행 ID. 과제 순서다."""
    return [runs[condition] for runs in key_runs(root).values() if condition in runs]


def calls_file(root: Path, run_id: str) -> Path:
    return root / ".deeptwin" / "runs" / run_id / "calls.jsonl"


def expected_costs(root: Path, conditions: list[str]) -> list[dict[str, Any]]:
    """실행 폴더의 `calls.jsonl`을 직접 더한 조건별 비용."""
    found = []
    for condition in conditions:
        lines = [line for r in run_ids(root, condition) for line in jsonl(calls_file(root, r))]
        found.append(
            {
                "condition": condition,
                "calls": len(lines),
                "seconds": round(sum(line["seconds"] for line in lines), 3),
                "input_chars": sum(line["input_chars"] for line in lines),
                "output_chars": sum(line["output_chars"] for line in lines),
            }
        )
    return found


def comparison_row(c: dict[str, Any]) -> str:
    return (
        f"| 바탕+딥트윈 대 {NAMES[c['against']]} | {c['judged']} | {c['pairs']} | {c['wins']} | "
        f"{c['selection_rate'] * 100:.1f}% | {c['p_value']:.4f} | {c['mean_seconds']:.3f} | "
        f"{c['median_seconds']:.3f} |"
    )


def cost_row(cost: dict[str, Any]) -> str:
    return (
        f"| {NAMES[cost['condition']]} | {cost['calls']} | {cost['seconds']:.3f} | "
        f"{cost['input_chars']} | {cost['output_chars']} |"
    )


def set_seconds(root: Path, seconds: list[float]) -> None:
    """`choices.jsonl`의 줄마다 `seconds`를 차례로 바꾼다."""
    path = eval_dir(root) / "choices.jsonl"
    rows = jsonl(path)
    assert len(rows) == len(seconds)
    for row, value in zip(rows, seconds, strict=True):
        row["seconds"] = value
    write_jsonl(path, rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def edit_eval_info(root: Path, *, eval_id: str = EVAL, **changes: Any) -> None:
    """`eval.json`의 필드를 바꾼다. 값이 `...`이면 그 필드를 지운다."""
    path = eval_dir(root, eval_id) / "eval.json"
    info = read_json(path)
    for name, value in changes.items():
        if value is ...:
            del info[name]
        else:
            info[name] = value
    path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_prompt_version(root: Path, run_id: str, value: str) -> None:
    """원장에서 그 실행의 `run` 줄의 `prompt_version`을 바꾼다. 해시는 맞추지 않는다."""
    path = root / ".deeptwin" / "ledger.jsonl"
    rows = jsonl(path)
    [row] = [r for r in rows if r["type"] == "run" and r["id"] == run_id]
    row["prompt_version"] = value
    write_jsonl(path, rows)


def add_spare_task(root: Path, task_id: str, n: int) -> None:
    (root / "extra-task.yaml").write_text(SPARE_TASK.format(id=task_id, n=n), "utf-8")
    ok_json(invoke("task", "add", "extra-task.yaml", "--json"), "task add")


def unknown(commit: str | None) -> str:
    return "알 수 없음" if commit is None else commit


# 보고서의 새 값


def test_report_has_judged_pairs_times_costs_and_the_package(
    in_example: Path, from_source: str | None
) -> None:
    judged_eval()
    folder = eval_dir(in_example)

    body = report_json()
    saved = tree(folder)
    text = invoke("eval", "report", EVAL)

    assert text.exit_code == 0, text.output
    assert tree(folder) == saved
    assert list(body) == REPORT_RESULT_KEYS
    seconds = [line["seconds"] for line in jsonl(folder / "choices.jsonl")]
    [c] = body["comparisons"]
    assert list(c) == [
        "against",
        "pairs",
        "judged",
        "wins",
        "selection_rate",
        "p_value",
        "mean_seconds",
        "median_seconds",
    ]
    assert (c["against"], c["pairs"], c["judged"]) == ("base", 2, 2)
    assert c["mean_seconds"] == round(statistics.fmean(seconds), 3)
    assert c["median_seconds"] == round(statistics.median(seconds), 3)
    assert body["costs"] == expected_costs(in_example, ["base", "full"])
    assert [cost["calls"] for cost in body["costs"]] == [2, 2]
    assert all(
        list(cost) == ["condition", "calls", "seconds", "input_chars", "output_chars"]
        for cost in body["costs"]
    )
    installed = version("deeptwin")
    assert (body["package_version"], body["commit"]) == (installed, from_source)
    assert (body["package_changed"], body["prompt_versions"]) == (False, [None])
    info = read_json(folder / "eval.json")
    assert (info["package_version"], info["commit"]) == (installed, from_source)
    assert read_json(folder / "report.json") == {
        "schema": 1,
        **{k: v for k, v in body.items() if k != "files"},
    }
    md = markdown(in_example)
    assert md.rstrip("\n") in text.stdout
    lines = md.splitlines()
    assert lines[:4] == [
        f"# 판정 보고서 {EVAL}",
        "",
        f"- 스킬: {SKILL}, 분할: spare, 쌍: 2개(모두 골랐습니다)",
        "",
    ]
    assert lines[4] == (
        "| 비교 | 판정한 쌍 | 전체 쌍 | 바탕+딥트윈이 이긴 횟수 | 선택률 | p값 | "
        "고르는 데 걸린 초(평균) | 고르는 데 걸린 초(중앙값) |"
    )
    assert comparison_row(c) in lines
    assert all(cost_row(cost) in lines for cost in body["costs"])
    assert lines[-5:] == [
        "## 패키지와 프롬프트",
        "",
        f"- 패키지: deeptwin {installed}",
        f"- 커밋: {unknown(from_source)}",
        PROMPT_NONE,
    ]
    assert md.index(P_SENTENCE) < md.index("## 실행 비용") < md.index("## 패키지와 프롬프트")
    assert "토큰 수는 재지 않으므로 적지 않습니다." in md
    assert "토큰" not in json.dumps(body, ensure_ascii=False)
    assert "더 낫다" not in md


def test_mean_and_median_of_the_seconds(in_example: Path) -> None:
    add_spare_task(in_example, "task-0203", 3)
    judged_eval(answers="1\n2\n1\n")
    set_seconds(in_example, [1.0, 2.0, 6.0])

    [c] = report_json()["comparisons"]

    assert (c["pairs"], c["judged"], c["mean_seconds"], c["median_seconds"]) == (3, 3, 3.0, 2.0)
    [row] = [
        line for line in markdown(in_example).splitlines() if line.startswith("| 바탕+딥트윈 대 ")
    ]
    assert row.endswith("| 3.000 | 2.000 |")


def test_each_opponent_counts_only_its_own_pairs(in_example: Path) -> None:
    judged_eval(SKILL, "--split", "spare", answers="1\n2\n1\n2\n")
    set_seconds(in_example, [1.0, 2.0, 4.0, 8.0])
    key = read_json(eval_dir(in_example) / "key.json")["pairs"]
    choices = jsonl(eval_dir(in_example) / "choices.jsonl")
    own: dict[str, list[float]] = {"base": [], "examples": []}
    for choice in choices:
        pair = key[choice["pair"]]
        own[pair["right"] if pair["left"] == "full" else pair["left"]].append(choice["seconds"])

    body = report_json()

    assert [c["against"] for c in body["comparisons"]] == ["base", "examples"]
    for c in body["comparisons"]:
        assert (c["pairs"], c["judged"]) == (2, 2)
        assert c["mean_seconds"] == round(statistics.fmean(own[c["against"]]), 3)
        assert c["median_seconds"] == round(statistics.median(own[c["against"]]), 3)
        assert comparison_row(c) in markdown(in_example).splitlines()
    assert own["base"] != own["examples"]
    assert body["costs"] == expected_costs(in_example, ["base", "examples", "full"])
    assert [cost["calls"] for cost in body["costs"]] == [2, 2, 2]


# 실행 비용


def test_costs_add_up_every_call_of_the_condition(in_example: Path) -> None:
    judged_eval()
    before = report_json()["costs"]
    path = calls_file(in_example, run_ids(in_example, "full")[0])
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(EXTRA_CALL) + "\n")

    after = report_json()["costs"]

    assert after[0] == before[0]
    assert after[1] == expected_costs(in_example, ["base", "full"])[1]
    assert after[1]["calls"] == before[1]["calls"] + 1 == 3
    assert after[1]["seconds"] == round(before[1]["seconds"] + 1.5, 3)
    assert after[1]["input_chars"] == before[1]["input_chars"] + 10
    assert after[1]["output_chars"] == before[1]["output_chars"] + 20
    assert cost_row(after[1]) in markdown(in_example).splitlines()


@pytest.mark.parametrize("missing", ["deleted", "full-width-digits", "path"])
def test_a_condition_without_call_records_has_no_cost(in_example: Path, missing: str) -> None:
    judged_eval()
    first_base = run_ids(in_example, "base")[0]
    if missing == "deleted":
        calls_file(in_example, first_base).unlink()
    else:
        # 모양이 틀린 실행 ID는 그 폴더가 있어도 읽지 않는다
        odd = "run-０００１" if missing == "full-width-digits" else "../runs/x"
        target = calls_file(in_example, odd)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(calls_file(in_example, first_base), target)
        key_path = eval_dir(in_example) / "key.json"
        key = read_json(key_path)
        task = next(iter(key["runs"]))
        key["runs"][task]["base"] = odd
        key_path.write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")

    result = invoke("eval", "report", EVAL, "--json")

    body = ok_json(result, "eval report")
    base, full = body["costs"]
    assert base == {
        "condition": "base",
        "calls": None,
        "seconds": None,
        "input_chars": None,
        "output_chars": None,
    }
    assert full == expected_costs(in_example, ["full"])[0]
    lines = markdown(in_example).splitlines()
    assert NO_RECORD_ROW in lines
    assert cost_row(full) in lines
    assert (eval_dir(in_example) / "report.json").is_file()


def test_broken_call_records_write_no_report(in_example: Path) -> None:
    judged_eval()
    run_id = run_ids(in_example, "full")[1]
    path = calls_file(in_example, run_id)
    path.write_text("JSON이 아닌 줄\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    before = tree(eval_dir(in_example))

    message = error_json(invoke("eval", "report", EVAL, "--json"), "eval report", "invalid_file")

    assert message.startswith(f".deeptwin/runs/{run_id}/calls.jsonl:1:")
    assert tree(eval_dir(in_example)) == before
    assert not (eval_dir(in_example) / "report.json").exists()
    assert not (eval_dir(in_example) / "report.md").exists()


# 프롬프트 버전


def test_prompt_versions_without_prompt_assets(in_example: Path) -> None:
    judged_eval()

    assert report_json()["prompt_versions"] == [None]
    assert PROMPT_NONE in markdown(in_example).splitlines()


@pytest.mark.parametrize(
    ("which", "expected", "line"),
    [("last", [None, "diff@3"], "없음, diff@3"), ("first", ["diff@3", None], "diff@3, 없음")],
)
def test_prompt_versions_follow_the_key_order_and_the_first_run_line(
    in_example: Path, which: str, expected: list[str | None], line: str
) -> None:
    judged_eval()
    ordered = [r for runs in key_runs(in_example).values() for r in runs.values()]
    run_id = ordered[-1] if which == "last" else ordered[0]
    set_prompt_version(in_example, run_id, "diff@3")
    # 같은 ID의 뒤 줄은 보지 않는다
    rows = jsonl(in_example / ".deeptwin" / "ledger.jsonl")
    [late] = [dict(r) for r in rows if r["type"] == "run" and r["id"] == ordered[0]]
    late["prompt_version"] = "late@9"
    write_jsonl(in_example / ".deeptwin" / "ledger.jsonl", [*rows, late])

    assert report_json()["prompt_versions"] == expected
    assert f"- 프롬프트 버전: {line}" in markdown(in_example).splitlines()


def test_prompt_versions_are_unknown_without_run_lines(in_example: Path) -> None:
    judged_eval()
    path = in_example / ".deeptwin" / "ledger.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:EXAMPLE_LEDGER_LINES]), encoding="utf-8")

    assert report_json()["prompt_versions"] == []
    assert PROMPT_UNKNOWN in markdown(in_example).splitlines()


# 커밋을 알 수 없음


def test_unknown_commit_is_null_and_written_as_unknown(
    in_example: Path, from_source: str | None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(provenance, "GIT", str(tmp_path / "no-such-git"))
    judged_eval()

    body = report_json()

    assert body["commit"] is None
    assert read_json(eval_dir(in_example) / "eval.json")["commit"] is None
    assert body["package_changed"] is False
    assert "- 커밋: 알 수 없음" in markdown(in_example).splitlines()


# 시작과 다른 패키지


@pytest.mark.parametrize(
    "change",
    [{"package_version": "0.0.1"}, {"commit": "0" * 40}, {"package_version": ..., "commit": ...}],
    ids=["version", "commit", "old-file"],
)
def test_report_marks_a_package_different_from_the_start(
    in_example: Path, from_source: str | None, change: dict[str, Any]
) -> None:
    judged_eval()
    started = read_json(eval_dir(in_example) / "eval.json")
    edit_eval_info(in_example, **change)

    body = report_json()

    lines = markdown(in_example).splitlines()
    now = f"지금 deeptwin {version('deeptwin')}, 커밋 {unknown(from_source)}"
    if "package_version" in change and change["package_version"] is ...:
        assert body["package_changed"] is False
        assert not any("패키지가 다릅니다" in line for line in lines)
        assert lines[3] == ""
    else:
        start_version = change.get("package_version", started["package_version"])
        start_commit = change.get("commit", started["commit"])
        assert body["package_changed"] is True
        assert lines[3] == (
            f"- 평가를 시작할 때와 패키지가 다릅니다(시작할 때 deeptwin {start_version}, "
            f"커밋 {unknown(start_commit)}. {now})."
        )
        assert lines[4] == ""
    assert (eval_dir(in_example) / "report.json").is_file()
    assert "더 낫다" not in "\n".join(lines)


def test_package_line_comes_after_the_skill_line(in_example: Path) -> None:
    judged_eval()
    edit_eval_info(in_example, package_version="0.0.1")
    edit_skill_md(in_example)

    body = report_json()

    assert (body["skill_changed"], body["package_changed"]) == (True, True)
    lines = markdown(in_example).splitlines()
    assert lines[3] == SKILL_LINE
    assert lines[4].startswith("- 평가를 시작할 때와 패키지가 다릅니다(시작할 때 deeptwin 0.0.1,")
    assert lines[5] == ""


# 시작할 때의 값은 바뀌지 않는다


def test_resume_keeps_the_package_recorded_at_the_start(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, _FailsOnTheSecondCall())
    error_json(invoke(*PAIRS, *FAKE, "--json"), "eval pairs", "provider_failed")
    edit_eval_info(in_example, commit="0" * 40)
    answer = (in_example / KEEPS).read_bytes().decode("utf-8")
    use_provider(monkeypatch, FakeProvider([answer] * 3))

    ok_json(invoke("eval", "pairs", "--resume", EVAL, *FAKE, "--json"), "eval pairs")

    info = read_json(eval_dir(in_example) / "eval.json")
    assert (info["package_version"], info["commit"]) == (version("deeptwin"), "0" * 40)


class _EditsSkillAndPackage(_EditsSkillYaml):
    """첫 생성에서 `skill.yaml`을 고치고, `eval.json`의 버전과 커밋을 가상의 값으로 바꾼다."""

    def __init__(self, root: Path, eval_id: str) -> None:
        super().__init__(root, at=1)
        self.root = root
        self.eval_id = eval_id

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, timeout: float = 120
    ) -> str:
        if self.calls == 0:
            edit_eval_info(
                self.root, eval_id=self.eval_id, package_version="8.8.8", commit="2" * 40
            )
        return super().complete(system, user, temperature=temperature, timeout=timeout)


def test_opening_the_seal_and_marking_the_skill_keep_the_package(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def open_after_edit(project: DeepTwin, eval_id: str) -> SealedOpening:
        # 묶음을 처음 열기 바로 앞에 시작할 때의 값을 가상의 값으로 바꿔 둔다
        edit_eval_info(in_example, eval_id=eval_id, package_version="9.9.9", commit="1" * 40)
        return open_sealed(project, eval_id)

    monkeypatch.setattr(deeptwin.eval.pairs, "open_sealed", open_after_edit)
    ok_json(invoke(*SEALED_PAIRS, *FAKE, "--json"), "eval pairs")
    use_provider(monkeypatch, _EditsSkillAndPackage(in_example, "eval-0002"))
    ok_json(invoke(*PAIRS, *FAKE, "--json"), "eval pairs")

    sealed = read_json(eval_dir(in_example) / "eval.json")
    marked = read_json(eval_dir(in_example, "eval-0002") / "eval.json")

    assert sealed["seal_open"] is not None
    assert (sealed["package_version"], sealed["commit"]) == ("9.9.9", "1" * 40)
    assert marked["skill_changed"] is True
    assert (marked["package_version"], marked["commit"]) == ("8.8.8", "2" * 40)


# 블라인드와 출력


def assert_quiet(text: str, commit: str | None) -> None:
    """조건 이름, 버전, 커밋, 비용이 나오지 않는다."""
    for word in (*HIDDEN, *PROVENANCE_WORDS, version("deeptwin")):
        assert word not in text, (word, text)
    if commit is not None:
        assert commit not in text


def test_pairs_screens_and_outputs_show_no_conditions_versions_or_costs(
    in_example: Path,
    from_source: str | None,
    serve: Callable[..., Judge],  # noqa: F811
) -> None:
    made = invoke(*PAIRS, *FAKE, "--json")
    body = ok_json(made, "eval pairs")
    assert list(body) == PAIRS_RESULT_KEYS
    terminal = judge(EVAL, "--json", input="1\n")
    assert terminal.exit_code == 0, terminal.output
    assert list(parsed(terminal)["result"]) == ["eval", "chosen", "remaining"]
    session = serve()
    page = session.get()
    [second] = [p["id"] for p in jsonl(eval_dir(in_example) / "pairs.jsonl")][1:]
    session.choose(second, "left")
    web = session.finish()
    assert web.exit_code == 0, web.output
    report_json()

    pairs_text = (eval_dir(in_example) / "pairs.jsonl").read_text(encoding="utf-8")
    for text in (pairs_text, made.stdout, terminal.stdout, terminal.stderr, web.stdout):
        assert_quiet(text, from_source)
    assert_blind(session.responses)
    for response in session.responses:
        assert_quiet(response.text(), from_source)
    assert page.status == 200
    sealed = invoke(*SEALED_PAIRS, *FAKE, "--json")
    assert_quiet(sealed.stdout, from_source)
    assert_quiet(
        (eval_dir(in_example, "eval-0002") / "pairs.jsonl").read_text("utf-8"), from_source
    )
    assert [e["type"] for e in ledger(in_example)].count("run") == 4 + 6
