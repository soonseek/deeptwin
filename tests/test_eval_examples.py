"""세 조건(바탕만, 바탕+예시, 바탕+딥트윈), 상대 고르기(`--against`), 바탕 스킬의 해시와 알림.

예제(`examples/inquiry-reply`)의 복사본에서 가짜 모델로 돈다. 더 필요한 예시는 테스트 안에서
가상으로 만든다. 뽑기의 예상값은 해시 규칙(`sha256(과제 ID + "\\n" + 예시 ID)`의 16진 글 순)으로
테스트 안에서 계산한다. 네트워크와 모델을 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest
import yaml

from deeptwin.cli import main
from deeptwin.cli.session import NOTHING_LEFT, SKILL_CHANGED
from deeptwin.compose import LAYERS, PAST_WORK_EXAMPLES, compose, fill_fluid
from deeptwin.errors import DeeptwinError
from deeptwin.eval import AGAINST, CONDITIONS, p_value, prepare_pairs
from deeptwin.eval.pairs import Recipe, base_skill_changed
from deeptwin.llm import FakeProvider
from deeptwin.models import EvalInfo
from deeptwin.store.project import DeepTwin
from test_cli import error_json, forbid_provider, invoke, jsonl, ledger, ok_json, parsed, runner
from test_eval import (
    EVAL,
    FAKE,
    KEEPS,
    PAIRS_RESULT_KEYS,
    SKILL,
    SPARE,
    _FailsOnTheSecondCall,
    eval_dir,
    files_in,
    judge,
    read_json,
    tree,
)
from test_eval_sealed import NOTICE, SEALED, assert_no_reference, change_reference, use_provider
from test_eval_web import Judge, address_line, assert_blind, no_server, serve  # noqa: F401

SPARE_PAIRS = ("eval", "pairs", SKILL, "--split", "spare")
SEALED_PAIRS = ("eval", "pairs", SKILL, "--split", "sealed")
SECOND = "eval-0002"
X = ["ex-0001", "ex-0002", "ex-0003", "ex-0004"]
"""예제의 가져온 대표작 good(`source: past_work`, `grade: signature`)."""
CONDITION_ORDER = ["base", "examples", "full"]
BLIND = ("base", "full", "examples", "바탕만", "딥트윈", "바탕+예시", "run-", "outputs")
"""쌍 목록, 판정 화면, `eval pairs` 출력에 나오면 안 되는 말."""
SKILL_NOTICE = SKILL_CHANGED.format(skill=SKILL)
SKILL_LINE = "- 바탕 스킬이 평가를 시작한 뒤 바뀌었습니다(SKILL.md, skill.yaml, checks.py)."
OTHER_SECTIONS = ("반드시 지킬 것", "부딪칠 때의 순서", "판단 지점별 기준", "이렇게는 쓰지 않는다")
"""바탕+예시의 지침에 없어야 하는 섹션 제목."""
SKILL_FILES = ("SKILL.md", "skill.yaml", "checks.py")
EVAL_KEYS = [
    "schema",
    "id",
    "ts",
    "skill",
    "split",
    "tasks",
    "against",
    "seed",
    "skill_hash",
    "skill_changed",
    "seal_open",
    "reused",
]
REPORT_KEYS = [
    "schema",
    "eval",
    "skill",
    "split",
    "pairs",
    "reused",
    "reference_changed",
    "skill_changed",
    "comparisons",
]
LEARNED_EXAMPLE = """\
# 가상의 강사 서도윤이 학습 중에 고쳐 승인한 대표작(good). 테스트용으로 지어낸 것이다.
schema: 1
id: ex-0009
layer: instinct
skill: inquiry-reply
kind: good
grade: signature
text: |
  문의 고맙습니다. 학습 중에 고쳐 둔 가상의 답장입니다.

  서도윤 드림
tags: {purpose: 교육문의, audience: 입문자}
source: my_version
status: active
approval: human
"""


def make(*args: str) -> dict[str, Any]:
    """`eval pairs`를 가짜 모델로 돌리고 결과를 돌려준다. `args`는 스킬부터의 인자다."""
    return ok_json(invoke("eval", "pairs", *args, *FAKE, "--json"), "eval pairs")


def spare_eval(*options: str) -> dict[str, Any]:
    return make(SKILL, "--split", "spare", *options)


def sealed_eval(*options: str) -> dict[str, Any]:
    return make(SKILL, "--split", "sealed", *options)


def draw_order(task_id: str, example_ids: list[str]) -> list[str]:
    """설계대로 다시 계산한 뽑기 순서."""

    def key(example_id: str) -> tuple[str, str]:
        return (hashlib.sha256(f"{task_id}\n{example_id}".encode()).hexdigest(), example_id)

    return sorted(example_ids, key=key)


def skill_dir(root: Path) -> Path:
    return root / "skills" / SKILL


def example_file(root: Path, example_id: str) -> Path:
    return root / ".deeptwin" / "layers" / "examples" / f"{example_id}.yaml"


def example_text(root: Path, example_id: str) -> str:
    """지침에 쓰이는 예시 글: 줄 끝 공백과 앞뒤의 빈 줄을 뗀 것."""
    data = yaml.safe_load(example_file(root, example_id).read_text(encoding="utf-8"))
    return "\n".join(line.rstrip() for line in data["text"].splitlines()).strip("\n")


def retire(root: Path, *example_ids: str) -> None:
    for example_id in example_ids:
        path = example_file(root, example_id)
        text = path.read_text(encoding="utf-8")
        assert text.count("status: active") == 1
        path.write_text(text.replace("status: active", "status: retired"), encoding="utf-8")


def edit_skill_md(root: Path) -> None:
    """`SKILL.md`의 한 글자를 고친다."""
    path = skill_dir(root) / "SKILL.md"
    data = path.read_bytes()
    old = "# 문의 답변".encode()
    assert data.count(old) == 1
    path.write_bytes(data.replace(old, "# 문의 답장".encode()))


def expected_skill_hash(folder: Path) -> str:
    """설계대로 다시 계산한 바탕 스킬의 해시."""
    digests = {
        name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if (folder / name).is_file()
        else None
        for name in SKILL_FILES
    }
    text = json.dumps(digests, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def runs_by_id(root: Path) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in ledger(root) if e["type"] == "run"}


def key_of(root: Path, eval_id: str = EVAL) -> dict[str, Any]:
    key: dict[str, Any] = read_json(eval_dir(root, eval_id) / "key.json")
    return key


def pair_sides(root: Path, eval_id: str = EVAL) -> list[tuple[str, list[str]]]:
    """대응표의 쌍마다 (과제, 정렬한 두 조건). 정렬한 목록이다."""
    return sorted(
        (p["task"], sorted((p["left"], p["right"])))
        for p in key_of(root, eval_id)["pairs"].values()
    )


def expected_sides(tasks: list[str], against: list[str]) -> list[tuple[str, list[str]]]:
    return sorted((task, sorted(("full", other))) for task in tasks for other in against)


def assert_blind_text(*texts: str) -> None:
    for text in texts:
        for word in BLIND:
            assert word not in text, (word, text)


def no_project(*args: object) -> NoReturn:
    raise AssertionError("프로젝트를 열지 않아야 합니다")


class _EditsSkillYaml:
    """`at`번째 생성에서 `skill.yaml` 끝에 주석 한 줄을 더하는 가짜 공급자."""

    name = "fake"

    def __init__(self, root: Path, at: int) -> None:
        self.path = skill_dir(root) / "skill.yaml"
        self.answer = (root / KEEPS).read_bytes().decode("utf-8")
        self.at = at
        self.calls = 0

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, timeout: float = 120
    ) -> str:
        self.calls += 1
        if self.calls == self.at:
            self.path.write_bytes(self.path.read_bytes() + "# 가상의 주석 한 줄\n".encode())
        return self.answer


def edit_skill_while_generating(
    monkeypatch: pytest.MonkeyPatch, root: Path, *, last: bool = False
) -> None:
    """fake 공급자 자리에 첫 생성(또는 마지막 생성)에서 `skill.yaml`을 고치는 공급자를 둔다."""

    def make_provider(options: main.ProviderOptions) -> _EditsSkillYaml:
        return _EditsSkillYaml(root, at=options.fake_repeat if last else 1)

    monkeypatch.setitem(main.PROVIDERS, "fake", make_provider)


# 기본 상대의 봉인 평가


def test_default_sealed_eval_makes_three_runs_and_two_pairs_per_task(in_example: Path) -> None:
    result = invoke(*SEALED_PAIRS, *FAKE, "--json")

    body = ok_json(result, "eval pairs")
    assert list(body) == PAIRS_RESULT_KEYS
    assert (body["tasks"], body["pairs"], body["reused"]) == (SEALED, 6, [])
    assert body["skill_changed"] is False
    entries = ledger(in_example)
    assert [e["type"] for e in entries] == ["task"] * 10 + ["seal_open"] + ["run"] * 9
    key = key_of(in_example)
    assert list(key["runs"]) == SEALED
    assert all(list(runs) == CONDITION_ORDER for runs in key["runs"].values())
    # 과제 안에서는 base, examples, full 순서로 만든다
    made = [e["id"] for e in entries if e["type"] == "run"]
    assert made == [key["runs"][task][c] for task in SEALED for c in CONDITION_ORDER]
    assert pair_sides(in_example) == expected_sides(SEALED, ["base", "examples"])
    folder = eval_dir(in_example)
    assert read_json(folder / "eval.json")["against"] == ["base", "examples"]
    assert files_in(folder) == sorted(
        [
            "eval.json",
            "key.json",
            "pairs.jsonl",
            *(f"outputs/{c}/{task}.md" for c in CONDITION_ORDER for task in SEALED),
        ]
    )
    assert len(jsonl(folder / "pairs.jsonl")) == 6
    verified = ok_json(invoke("verify", "--json"), "verify")
    assert (verified["lines"], verified["sealed"]) == (20, 3)
    assert_blind_text(result.stdout)
    assert_no_reference(result.stdout, result.stderr)


# 바탕+예시의 조립


def test_examples_runs_inject_the_first_three_past_work_signatures(in_example: Path) -> None:
    skill_md = (skill_dir(in_example) / "SKILL.md").read_text("utf-8")
    texts = {example_id: example_text(in_example, example_id) for example_id in X}
    sealed_eval()
    key = key_of(in_example)
    entries = runs_by_id(in_example)

    assert entries[key["runs"]["task-0101"]["examples"]]["injected"] == [
        "ex-0001",
        "ex-0002",
        "ex-0004",
    ]
    for task in SEALED:
        order = draw_order(task, X)
        run_id = key["runs"][task]["examples"]
        entry = entries[run_id]
        assert entry["injected"] == order[:PAST_WORK_EXAMPLES]
        assert entry["rejected"] == [{"id": order[3], "reason": "budget"}]
        guide = (
            "## 이번 작업의 개인 기준\n\n이렇게 쓴다\n"
            + "\n\n---\n\n".join(texts[example_id] for example_id in order[:3])
            + "\n"
        )
        assert entry["guide_hash"] == "sha256:" + hashlib.sha256(guide.encode()).hexdigest()
        copy = (in_example / ".deeptwin" / "runs" / run_id / "SKILL.md").read_text("utf-8")
        assert copy == fill_fluid(skill_md, guide)
        for heading in OTHER_SECTIONS:
            assert heading not in copy
        assert entries[key["runs"][task]["base"]]["injected"] == []
        assert entries[key["runs"][task]["base"]]["rejected"] == []

    # 같은 과제를 다른 평가에서 만들어도 같은 지침이다
    sealed_eval()
    again = key_of(in_example, SECOND)
    entries = runs_by_id(in_example)
    for task in SEALED:
        first = entries[key["runs"][task]["examples"]]
        second = entries[again["runs"][task]["examples"]]
        assert first["id"] != second["id"]
        assert (first["guide_hash"], first["injected"]) == (
            second["guide_hash"],
            second["injected"],
        )


def test_learned_examples_go_only_into_the_full_runs(in_example: Path) -> None:
    example_file(in_example, "ex-0009").write_text(LEARNED_EXAMPLE, encoding="utf-8")

    spare_eval()

    key = key_of(in_example)
    entries = runs_by_id(in_example)
    # 대표작 good이면 바탕+딥트윈의 예시 후보다. 그 가운데 뽑기 순서로 앞의 둘이 들어간다
    picked = [task for task in SPARE if "ex-0009" in draw_order(task, [*X, "ex-0009"])[:2]]
    assert picked == ["task-0201"]
    for task in picked:
        assert "ex-0009" in entries[key["runs"][task]["full"]]["injected"]
    for task in SPARE:
        entry = entries[key["runs"][task]["examples"]]
        assert "ex-0009" not in entry["injected"]
        assert "ex-0009" not in [r["id"] for r in entry["rejected"]]
        assert entry["injected"] == draw_order(task, X)[:3]


# 대표작 모자람


@pytest.mark.parametrize("split", ["sealed", "spare"])
def test_too_few_past_work_signatures_stop_before_anything_is_written(
    in_example: Path, monkeypatch: pytest.MonkeyPatch, split: str
) -> None:
    retire(in_example, "ex-0003", "ex-0004")
    before = tree(in_example)
    forbid_provider(monkeypatch)

    result = invoke("eval", "pairs", SKILL, "--split", split, *FAKE, "--json")

    message = error_json(result, "eval pairs", "not_enough_examples")
    # 예제의 avoid(ex-0005), usual(ex-0006), pair(ex-0007)는 세지 않는다
    assert "2개" in message
    assert "3개" in message
    assert SKILL in message
    assert f"deeptwin import <폴더> --skill {SKILL} --signature" in message
    assert "--against base" in message
    assert_no_reference(message, result.stderr)
    assert not (in_example / ".deeptwin" / "eval").exists()
    assert not (in_example / ".deeptwin" / "runs").exists()
    assert tree(in_example) == before


def test_too_few_signatures_still_allow_against_base(in_example: Path) -> None:
    retire(in_example, "ex-0003", "ex-0004")

    body = spare_eval("--against", "base")

    assert (body["tasks"], body["pairs"]) == (SPARE, 2)
    assert pair_sides(in_example) == expected_sides(SPARE, ["base"])


def test_resume_stops_before_writing_when_signatures_ran_short(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, _FailsOnTheSecondCall())
    error_json(invoke(*SPARE_PAIRS, *FAKE, "--json"), "eval pairs", "provider_failed")
    retire(in_example, "ex-0003", "ex-0004")
    before = tree(in_example)
    forbid_provider(monkeypatch)

    result = invoke("eval", "pairs", "--resume", EVAL, *FAKE, "--json")

    message = error_json(result, "eval pairs", "not_enough_examples")
    assert "2개" in message
    assert tree(in_example) == before
    assert [p.name for p in (in_example / ".deeptwin" / "eval").iterdir()] == [EVAL]


# 상대 고르기


def test_against_base_makes_one_pair_per_task_and_no_examples_outputs(in_example: Path) -> None:
    body = spare_eval("--against", "base")

    assert body["pairs"] == 2
    folder = eval_dir(in_example)
    assert not (folder / "outputs" / "examples").exists()
    assert read_json(folder / "eval.json")["against"] == ["base"]
    assert all(list(runs) == ["base", "full"] for runs in key_of(in_example)["runs"].values())
    assert pair_sides(in_example) == expected_sides(SPARE, ["base"])


def test_against_examples_makes_one_pair_per_task_and_reports_only_it(in_example: Path) -> None:
    body = spare_eval("--against", "examples")

    assert body["pairs"] == 2
    folder = eval_dir(in_example)
    assert not (folder / "outputs" / "base").exists()
    assert read_json(folder / "eval.json")["against"] == ["examples"]
    assert all(list(runs) == ["examples", "full"] for runs in key_of(in_example)["runs"].values())
    assert pair_sides(in_example) == expected_sides(SPARE, ["examples"])
    assert judge(EVAL, input="1\n2\n").exit_code == 0
    report = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")
    assert [(c["against"], c["pairs"]) for c in report["comparisons"]] == [("examples", 2)]
    markdown = (folder / "report.md").read_text("utf-8")
    assert "| 바탕+딥트윈 대 바탕+예시 | 2 |" in markdown
    assert "바탕만" not in markdown


def test_repeated_against_values_count_once_in_the_fixed_order(in_example: Path) -> None:
    body = spare_eval("--against", "examples", "--against", "base", "--against", "base")

    assert body["pairs"] == 4
    assert read_json(eval_dir(in_example) / "eval.json")["against"] == ["base", "examples"]
    assert pair_sides(in_example) == expected_sides(SPARE, ["base", "examples"])


@pytest.mark.parametrize(
    "args",
    [
        (*SPARE_PAIRS, "--against", "full"),
        (*SPARE_PAIRS, "--against", "x"),
        (*SPARE_PAIRS, "--against", "base", "--against", "x"),
        ("eval", "pairs", "--resume", EVAL, "--against", "base"),
    ],
    ids=["full", "unknown", "one-of-two", "with-resume"],
)
def test_wrong_against_exits_2_before_reading_anything(
    in_example: Path, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...]
) -> None:
    spare_eval("--against", "base")
    before = tree(in_example)
    monkeypatch.setattr(DeepTwin, "open", no_project)

    result = invoke(*args, *FAKE, "--json")

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert "--against" in result.output
    assert tree(in_example) == before


def test_help_names_both_opponents_and_the_default() -> None:
    result = runner.invoke(main.app, ["eval", "pairs", "--help"])

    assert result.exit_code == 0, result.output
    # 도움말은 틀 안에서 줄을 바꾸므로 틀 글자와 줄바꿈을 지우고 본다
    shown = " ".join(re.sub("[│╭╮╰╯─]", " ", result.stdout).split())
    assert "--against" in shown
    assert "base(바탕만), examples(바탕+예시)" in shown
    assert "주지 않으면 둘 다다" in shown


# 블라인드


def test_default_eval_names_no_condition_in_pairs_screens_or_output(
    in_example: Path,
    serve: Callable[..., Judge],  # noqa: F811
) -> None:
    made = invoke(*SPARE_PAIRS, *FAKE, "--json")
    text = invoke(*SPARE_PAIRS, *FAKE)

    assert ok_json(made, "eval pairs")["pairs"] == 4
    assert text.exit_code == 0, text.output
    pairs = [
        (eval_dir(in_example, eval_id) / "pairs.jsonl").read_text("utf-8")
        for eval_id in (EVAL, SECOND)
    ]
    assert all(len(lines.splitlines()) == 4 for lines in pairs)
    in_terminal = judge(SECOND, input="1\n2\n")
    in_json = judge(SECOND, "--json", input="2\n1\n")
    assert in_terminal.exit_code == in_json.exit_code == 0
    assert ok_json(in_json, "eval judge") == {"eval": SECOND, "chosen": 2, "remaining": 0}
    assert "쌍 1/4" in in_terminal.stdout
    assert "쌍 4/4" in in_json.stderr
    assert_blind_text(made.stdout, text.stdout, *pairs, in_terminal.stdout, in_json.stderr)

    ids = [pair["id"] for pair in jsonl(eval_dir(in_example) / "pairs.jsonl")]
    session = serve()
    for pair_id in ids:
        assert "쌍 " in session.get().body
        session.choose(pair_id, "left")
    on_web = session.finish()

    assert on_web.exit_code == 0, on_web.output
    assert [r.status for r in session.responses] == [200, 303, 200, 303, 200, 303, 200, 200]
    # 웹 응답(헤더와 본문)은 소문자로 바꿔도 조건 말이 없고 "바탕"도 없다
    assert_blind(session.responses)
    assert_blind_text(on_web.stdout)


# 해시 기록


def test_new_eval_records_the_base_skill_hash(in_example: Path) -> None:
    deeptwin = DeepTwin.open(in_example)

    spare_eval()

    info = read_json(eval_dir(in_example) / "eval.json")
    assert list(info) == EVAL_KEYS
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", info["skill_hash"])
    assert (
        info["skill_hash"]
        == deeptwin.skill_hash(SKILL)
        == expected_skill_hash(skill_dir(in_example))
    )
    assert info["skill_changed"] is False
    assert EvalInfo.model_validate(info).skill_hash == info["skill_hash"]


def test_skill_hash_follows_only_the_three_files(in_example: Path) -> None:
    deeptwin = DeepTwin.open(in_example)
    folder = skill_dir(in_example)
    original = deeptwin.skill_hash(SKILL)
    assert original == expected_skill_hash(folder)

    # 스킬 폴더의 다른 파일은 보지 않는다
    (folder / "notes.md").write_text("가상의 메모입니다.\n", encoding="utf-8")
    (folder / "__pycache__").mkdir(exist_ok=True)
    (folder / "__pycache__" / "checks.cpython-311.pyc").write_bytes(b"\x00\x01")
    assert deeptwin.skill_hash(SKILL) == original

    seen = {original}
    for name in SKILL_FILES:
        path = folder / name
        data = path.read_bytes()
        # 한 바이트만 고친다
        path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        changed = deeptwin.skill_hash(SKILL)
        assert changed not in seen
        assert changed == expected_skill_hash(folder)
        seen.add(changed)
        path.write_bytes(data)
        assert deeptwin.skill_hash(SKILL) == original

    # 줄바꿈을 바꾸지 않고 읽으므로 CRLF로 바꾸는 것도 바뀜이다
    skill_md = folder / "SKILL.md"
    data = skill_md.read_bytes()
    skill_md.write_bytes(data.replace(b"\n", b"\r\n"))
    assert deeptwin.skill_hash(SKILL) not in seen
    skill_md.write_bytes(data)

    (folder / "checks.py").unlink()
    gone = deeptwin.skill_hash(SKILL)
    assert gone not in seen
    assert gone == expected_skill_hash(folder)


@pytest.mark.parametrize("skill_id", ["../inquiry-reply", "-x", "a/b", ""])
def test_skill_hash_refuses_an_id_outside_the_rule(in_example: Path, skill_id: str) -> None:
    deeptwin = DeepTwin.open(in_example)

    with pytest.raises(DeeptwinError) as hashed:
        deeptwin.skill_hash(skill_id)
    with pytest.raises(DeeptwinError) as read:
        deeptwin.skill(skill_id)

    assert hashed.value.code == read.value.code == "skill_not_found"
    assert hashed.value.message == read.value.message


# 판정 시작의 알림


def test_skill_notice_text() -> None:
    assert SKILL_NOTICE == (
        "평가를 시작한 뒤 스킬 inquiry-reply의 파일(SKILL.md, skill.yaml, checks.py)이 "
        "바뀌었습니다. 막지 않고 보고서에 표시합니다."
    )
    assert "바탕" not in SKILL_CHANGED
    assert_blind_text(SKILL_NOTICE)


def test_judging_starts_with_the_skill_notice_after_the_skill_changed(in_example: Path) -> None:
    sealed_eval()
    edit_skill_md(in_example)
    info = (eval_dir(in_example) / "eval.json").read_bytes()
    lines_before = len(ledger(in_example))

    result = judge(EVAL, input="1\n" * 6)

    assert result.exit_code == 0, result.output
    screen = result.stdout
    lines = screen.splitlines()
    assert lines[0] == SKILL_NOTICE
    assert lines[1] == "쌍 1/6"
    assert screen.count(SKILL_NOTICE) == 1
    assert "쌍 6/6" in screen
    assert len(jsonl(eval_dir(in_example) / "choices.jsonl")) == 6
    # 판정은 eval.json을 쓰지 않는다
    assert (eval_dir(in_example) / "eval.json").read_bytes() == info
    assert len(ledger(in_example)) == lines_before
    assert_blind_text(screen)
    assert_no_reference(screen)
    assert result.stderr == ""


# 알림의 자리


def test_reference_notice_comes_first_then_the_skill_notice(in_example: Path) -> None:
    sealed_eval()
    edit_skill_md(in_example)
    change_reference(in_example)

    result = judge(EVAL, input="1\n" * 6)

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[:3] == [NOTICE.format("task-0101"), SKILL_NOTICE, "쌍 1/6"]


def test_skill_notice_goes_to_stderr_with_json_and_keeps_the_result_shape(
    in_example: Path,
) -> None:
    sealed_eval()
    edit_skill_md(in_example)

    result = judge(EVAL, "--json", input="1\n" * 6)

    assert result.exit_code == 0, result.output
    assert parsed(result) == {
        "ok": True,
        "command": "eval judge",
        "result": {"eval": EVAL, "chosen": 6, "remaining": 0},
    }
    assert result.stderr.splitlines()[0] == SKILL_NOTICE
    assert SKILL_NOTICE not in result.stdout


def test_web_skill_notice_comes_before_nothing_left_and_opens_no_server(
    in_example: Path,
    no_server: None,  # noqa: F811
) -> None:
    sealed_eval()
    edit_skill_md(in_example)
    assert judge(EVAL, input="1\n" * 6).exit_code == 0

    result = runner.invoke(main.app, ["eval", "judge", EVAL, "--web", "--json"])

    assert ok_json(result, "eval judge") == {"eval": EVAL, "chosen": 0, "remaining": 0}
    assert result.stderr.splitlines()[:2] == [SKILL_NOTICE, NOTHING_LEFT]
    assert "http://" not in result.stderr


def test_web_skill_notice_goes_to_the_stream_and_not_into_the_page(
    in_example: Path,
    serve: Callable[..., Judge],  # noqa: F811
) -> None:
    spare_eval("--against", "base")
    edit_skill_md(in_example)
    ids = [pair["id"] for pair in jsonl(eval_dir(in_example) / "pairs.jsonl")]
    session = serve()

    for pair_id in ids:
        session.get()
        session.choose(pair_id, "right")
    result = session.finish()

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == SKILL_NOTICE
    assert lines[1] == address_line(session.port)
    for response in session.responses:
        assert "바뀌었습니다" not in response.body
        assert "SKILL.md" not in response.body
    assert_blind(session.responses)


def test_no_skill_notice_for_an_unchanged_skill(in_example: Path) -> None:
    sealed_eval()

    result = judge(EVAL, input="1\n" * 6)

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("쌍 1/6")
    assert "바뀌었습니다" not in result.stdout


def test_old_eval_without_a_skill_hash_gives_no_skill_notice(in_example: Path) -> None:
    spare_eval()
    path = eval_dir(in_example) / "eval.json"
    info = read_json(path)
    # 두 필드가 없는 예전 eval.json
    del info["skill_hash"], info["skill_changed"]
    path.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    edit_skill_md(in_example)

    result = judge(EVAL, input="1\n" * 4)
    report = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("쌍 1/4")
    assert "바뀌었습니다" not in result.stdout
    assert report["skill_changed"] is False
    assert SKILL_LINE not in (eval_dir(in_example) / "report.md").read_text("utf-8")


# 생성 중 바뀜


def test_skill_changed_while_generating_is_marked_and_pairs_are_still_made(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill_yaml = skill_dir(in_example) / "skill.yaml"
    original = skill_yaml.read_bytes()
    recorded = DeepTwin.open(in_example).skill_hash(SKILL)
    edit_skill_while_generating(monkeypatch, in_example)

    body = ok_json(invoke(*SPARE_PAIRS, *FAKE, "--json"), "eval pairs")
    text = invoke(*SPARE_PAIRS, *FAKE)

    assert list(body) == PAIRS_RESULT_KEYS
    assert (body["pairs"], body["skill_changed"]) == (4, True)
    info = read_json(eval_dir(in_example) / "eval.json")
    assert list(info) == EVAL_KEYS
    assert (info["skill_hash"], info["skill_changed"]) == (recorded, True)
    assert len(jsonl(eval_dir(in_example) / "pairs.jsonl")) == 4
    assert text.exit_code == 0, text.output
    lines = text.stdout.splitlines()
    assert lines[-2:] == [SKILL_NOTICE, f"deeptwin eval judge {SECOND}로 고르세요."]
    assert read_json(eval_dir(in_example, SECOND) / "eval.json")["skill_changed"] is True
    assert len(jsonl(eval_dir(in_example, SECOND) / "pairs.jsonl")) == 4
    assert_blind_text(text.stdout)

    # 파일을 되돌려도 쌍을 만드는 동안 본 표시가 남는다
    skill_yaml.write_bytes(original)
    assert DeepTwin.open(in_example).skill_hash(SKILL) == recorded
    judged = judge(EVAL, input="1\n" * 4)
    report = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")

    assert judged.exit_code == 0, judged.output
    assert judged.stdout.splitlines()[0] == SKILL_NOTICE
    assert report["skill_changed"] is True
    assert SKILL_LINE in (eval_dir(in_example) / "report.md").read_text("utf-8").splitlines()


def test_change_at_the_last_generation_is_caught_before_writing_pairs(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edit_skill_while_generating(monkeypatch, in_example, last=True)

    body = ok_json(invoke(*SPARE_PAIRS, *FAKE, "--json"), "eval pairs")

    assert (body["pairs"], body["skill_changed"]) == (4, True)
    assert read_json(eval_dir(in_example) / "eval.json")["skill_changed"] is True


def test_sealed_eval_keeps_its_seal_fields_when_the_skill_changes(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed_eval()
    edit_skill_while_generating(monkeypatch, in_example)

    body = ok_json(invoke(*SEALED_PAIRS, *FAKE, "--json"), "eval pairs")

    assert (body["eval"], body["reused"], body["skill_changed"]) == (SECOND, SEALED, True)
    info = read_json(eval_dir(in_example, SECOND) / "eval.json")
    assert list(info) == EVAL_KEYS
    assert (info["seal_open"], info["reused"], info["skill_changed"]) == ("seal-0002", SEALED, True)
    ok_json(invoke("verify", "--json"), "verify")


# 보고서


def comparison_counts(root: Path, against: str) -> tuple[int, int]:
    """대응표와 선택을 합친 (쌍 수, `full`이 이긴 수)."""
    keys = key_of(root)["pairs"]
    pairs = wins = 0
    for choice in jsonl(eval_dir(root) / "choices.jsonl"):
        side = keys[choice["pair"]]
        if {side["left"], side["right"]} == {"full", against}:
            pairs += 1
            wins += side[choice["chosen"]] == "full"
    return pairs, wins


def test_report_has_one_comparison_per_opponent_in_against_order(in_example: Path) -> None:
    sealed_eval()
    assert judge(EVAL, input="1\n2\n1\n2\n1\n2\n").exit_code == 0
    folder = eval_dir(in_example)

    first = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")
    saved = tree(folder)
    second = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")

    assert first == second
    assert tree(folder) == saved
    assert first["pairs"] == 6
    assert [c["against"] for c in first["comparisons"]] == ["base", "examples"]
    for comparison in first["comparisons"]:
        pairs, wins = comparison_counts(in_example, comparison["against"])
        assert (comparison["pairs"], comparison["wins"]) == (pairs, wins) == (3, wins)
        assert comparison["selection_rate"] == wins / 3
        assert comparison["p_value"] == p_value(wins, 3)
    assert first["skill_changed"] is False
    assert list(read_json(folder / "report.json")) == REPORT_KEYS
    markdown = (folder / "report.md").read_text("utf-8")
    assert "바탕 스킬" not in markdown
    rows = [line for line in markdown.splitlines() if line.startswith("| 바탕+딥트윈 대 ")]
    assert [row.split(" | ")[0:2] for row in rows] == [
        ["| 바탕+딥트윈 대 바탕만", "3"],
        ["| 바탕+딥트윈 대 바탕+예시", "3"],
    ]


def test_report_marks_a_changed_skill_below_the_reference_line(in_example: Path) -> None:
    sealed_eval()
    assert judge(EVAL, input="1\n2\n1\n2\n1\n2\n").exit_code == 0
    edit_skill_md(in_example)
    change_reference(in_example)
    folder = eval_dir(in_example)

    first = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")
    saved = tree(folder)
    second = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")

    assert first == second
    assert tree(folder) == saved
    assert first["skill_changed"] is True
    report = read_json(folder / "report.json")
    assert list(report) == REPORT_KEYS
    assert report["skill_changed"] is True
    markdown = (folder / "report.md").read_text("utf-8")
    assert markdown.splitlines()[:6] == [
        f"# 판정 보고서 {EVAL}",
        "",
        f"- 스킬: {SKILL}, 분할: sealed, 쌍: 6개(모두 골랐습니다)",
        "- 기준이 등록 때와 다른 봉인 과제: task-0101",
        SKILL_LINE,
        "",
    ]
    assert "| 바탕+딥트윈 대 바탕만 | 3 |" in markdown
    assert "| 바탕+딥트윈 대 바탕+예시 | 3 |" in markdown
    # 판정과 보고서는 eval.json에 쓰지 않는다
    assert read_json(folder / "eval.json")["skill_changed"] is False


# 이어 가기


def test_resume_of_a_default_eval_makes_the_remaining_five(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, _FailsOnTheSecondCall())
    error_json(invoke(*SPARE_PAIRS, *FAKE, "--json"), "eval pairs", "provider_failed")
    folder = eval_dir(in_example)
    [first_run] = [e for e in ledger(in_example) if e["type"] == "run"]
    assert key_of(in_example)["runs"] == {"task-0201": {"base": first_run["id"]}}
    started = read_json(folder / "eval.json")
    assert started["against"] == ["base", "examples"]

    answer = (in_example / KEEPS).read_bytes().decode("utf-8")
    repeats = use_provider(monkeypatch, FakeProvider([answer] * 5))
    body = ok_json(invoke("eval", "pairs", "--resume", EVAL, *FAKE, "--json"), "eval pairs")

    assert repeats == [5]
    assert (body["pairs"], body["skill_changed"]) == (4, False)
    info = read_json(folder / "eval.json")
    assert (info["against"], info["skill_hash"]) == (started["against"], started["skill_hash"])
    assert info == started
    key = key_of(in_example)
    assert all(list(runs) == CONDITION_ORDER for runs in key["runs"].values())
    assert key["runs"]["task-0201"]["base"] == first_run["id"]
    assert len(jsonl(folder / "pairs.jsonl")) == 4
    assert pair_sides(in_example) == expected_sides(SPARE, ["base", "examples"])


# 라이브러리


def test_conditions_and_opponents() -> None:
    assert list(CONDITIONS) == CONDITION_ORDER
    assert CONDITIONS["base"] == Recipe(LAYERS)
    assert CONDITIONS["examples"] == Recipe(("tendency", "priority", "principle"), "past_work")
    assert CONDITIONS["full"] == Recipe(())
    assert AGAINST == ("base", "examples")
    assert PAST_WORK_EXAMPLES == 3


def test_compose_with_past_work_is_the_same_every_time(in_example: Path) -> None:
    deeptwin = DeepTwin.open(in_example)
    skill = deeptwin.skill(SKILL)
    task = deeptwin.task("task-0001")
    context = task.context or {}
    ablate = ("tendency", "priority", "principle")

    first = compose(skill, task, deeptwin, context=context, ablate=ablate, example_pick="past_work")
    second = compose(
        skill, task, deeptwin, context=context, ablate=ablate, example_pick="past_work"
    )

    assert first == second
    assert first.injected == draw_order("task-0001", X)[:3]
    assert [r.id for r in first.rejected] == draw_order("task-0001", X)[3:]
    assert (first.no_hit, first.conflicts) == ([], [])


@pytest.mark.parametrize(
    "ablate",
    [(), ("tendency", "priority", "principle"), ("instinct",), LAYERS],
    ids=["none", "keep-instinct", "instinct", "all"],
)
def test_policy_is_the_default_pick(in_example: Path, ablate: tuple[str, ...]) -> None:
    deeptwin = DeepTwin.open(in_example)
    skill = deeptwin.skill(SKILL)
    task = deeptwin.task("task-0001")
    context = task.context or {}

    picked = compose(skill, task, deeptwin, context=context, ablate=ablate, example_pick="policy")

    assert picked == compose(skill, task, deeptwin, context=context, ablate=ablate)


def test_without_instinct_the_pick_is_not_used(in_example: Path) -> None:
    retire(in_example, "ex-0003", "ex-0004")
    deeptwin = DeepTwin.open(in_example)
    skill = deeptwin.skill(SKILL)
    task = deeptwin.task("task-0001")
    context = task.context or {}

    with pytest.raises(DeeptwinError) as short:
        compose(
            skill,
            task,
            deeptwin,
            context=context,
            ablate=("tendency", "priority", "principle"),
            example_pick="past_work",
        )
    nothing = compose(
        skill, task, deeptwin, context=context, ablate=LAYERS, example_pick="past_work"
    )

    assert short.value.code == "not_enough_examples"
    assert "2개" in short.value.message
    assert (nothing.guide, nothing.injected, nothing.rejected) == ("", [], [])


def test_unknown_pick_and_wrong_opponents_are_value_errors(in_example: Path) -> None:
    deeptwin = DeepTwin.open(in_example)
    skill = deeptwin.skill(SKILL)
    task = deeptwin.task("task-0001")

    with pytest.raises(ValueError):
        compose(skill, task, deeptwin, context={}, example_pick=cast(Any, "x"))
    wrong: list[Any] = [[], ["full"], ["x"]]
    for against in wrong:
        with pytest.raises(ValueError):
            prepare_pairs(deeptwin, SKILL, split="spare", against=against)
    plan = prepare_pairs(deeptwin, SKILL, split="spare", against=["examples", "base", "base"])
    assert plan.against == ("base", "examples")
    assert [(r.task, r.condition) for r in plan.runs] == [
        (task_id, condition) for task_id in SPARE for condition in CONDITION_ORDER
    ]
    assert prepare_pairs(deeptwin, SKILL, split="spare").against == AGAINST
    assert plan.skill_hash == deeptwin.skill_hash(SKILL)


def test_base_skill_changed_reads_the_mark_and_the_current_hash(in_example: Path) -> None:
    deeptwin = DeepTwin.open(in_example)
    now = deeptwin.skill_hash(SKILL)
    base = {"id": EVAL, "ts": "2026-11-23T10:00:00+09:00", "skill": SKILL, "split": "spare"}
    info = EvalInfo.model_validate({**base, "tasks": SPARE, "against": ["base"], "seed": EVAL})

    assert base_skill_changed(deeptwin, info) is False
    assert base_skill_changed(deeptwin, info.model_copy(update={"skill_changed": True})) is True
    assert base_skill_changed(deeptwin, info.model_copy(update={"skill_hash": now})) is False
    other = info.model_copy(update={"skill_hash": "sha256:" + "0" * 64})
    assert base_skill_changed(deeptwin, other) is True
