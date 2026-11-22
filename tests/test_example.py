"""예제 `examples/inquiry-reply`가 가짜 모델로 끝까지 돈다. 데이터는 모두 가상이다.

테스트는 예제를 복사한 폴더(`in_example`)에서 돌고 저장소의 예제 폴더를 고치지 않는다.
"""

from __future__ import annotations

import ast
import difflib
import itertools
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import EXAMPLE_LEFT_OUT, copy_example
from deeptwin.checks import prepare_checks
from deeptwin.compose import compose, fill_fluid
from deeptwin.models import Task
from deeptwin.store.guard import SealedToken
from deeptwin.store.project import DeepTwin
from test_cli import CHOICE_KEYS, error_json, files_under, invoke, ledger, ok_json

SKILL = "inquiry-reply"
TRAIN_TASK = "task-0001"
SEALED_TASK = "task-0101"
KEEPS = "answers/keeps-principles.md"
"""모든 원칙을 지키는 가짜 모델의 답."""
BREAKS = "answers/breaks-promise.md"
"""검사 함수가 있는 원칙 prin-01(`no_outcome_promise`)만 어기는 가짜 모델의 답."""

TASK_IDS = {
    "train": ["task-0001", "task-0002", "task-0003", "task-0004", "task-0005"],
    "sealed": ["task-0101", "task-0102", "task-0103"],
    "spare": ["task-0201", "task-0202"],
}
"""예제에 등록한 과제. 원장의 `task` 줄도 이 순서다."""

GOLDEN = Path(__file__).parent / "golden" / "inquiry-reply"
GOLDEN_TASKS = ["task-0001", "task-0002"]
UPDATE_GOLDEN = "DEEPTWIN_UPDATE_GOLDEN"
REGENERATE = f"{UPDATE_GOLDEN}=1 uv run pytest tests/test_example.py -k golden"

STATUSES = ("active", "candidate", "dormant", "retired")
WATCHED = ("skills", ".deeptwin/layers")
"""실행 전후로 바이트까지 같아야 하는 폴더."""


def run_fake(answer: str, task_id: str = TRAIN_TASK) -> tuple[str, ...]:
    return ("run", SKILL, task_id, "--provider", "fake", "--fake-answer", answer, "--json")


def snapshot(root: Path) -> dict[str, dict[str, bytes]]:
    return {name: files_under(root / name) for name in WATCHED}


def counted_from_files(root: Path) -> dict[str, dict[str, int]]:
    """층 파일을 deeptwin을 거치지 않고 YAML로 읽어 센 `status`의 `layers`."""
    layers = root / ".deeptwin" / "layers"

    def folder(name: str) -> list[dict[str, Any]]:
        return [
            yaml.safe_load(p.read_text("utf-8")) for p in sorted((layers / name).glob("*.yaml"))
        ]

    def listed(name: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = yaml.safe_load((layers / name).read_text("utf-8"))
        return items

    groups = {
        "instinct": folder("examples"),
        "tendency": folder("cards"),
        "priority": listed("priorities.yaml"),
        "principle": listed("principles.yaml"),
    }
    counts: dict[str, dict[str, int]] = {}
    for layer, items in groups.items():
        statuses = [item["status"] for item in items]
        counts[layer] = {"total": len(items), **{s: statuses.count(s) for s in STATUSES}}
    counts["instinct"]["signature"] = sum(
        1 for e in groups["instinct"] if e["grade"] == "signature"
    )
    return counts


# 예제 검사


def test_copied_example_verifies(in_example: Path) -> None:
    body = ok_json(invoke("verify", "--json"), "verify")

    assert body["lines"] == 10
    assert body["sealed"] == 3
    # 원장은 과제 등록(task add)으로만 만들었다
    entries = ledger(in_example)
    assert [(e["type"], e["split"], e["id"]) for e in entries] == [
        ("task", split, task_id) for split, ids in TASK_IDS.items() for task_id in ids
    ]
    assert all((e["reference_hash"] is None) == (e["split"] != "sealed") for e in entries)


def test_status_of_the_copied_example(in_example: Path) -> None:
    body = ok_json(invoke("status", "--json"), "status")

    assert body == {
        "layers": counted_from_files(in_example),
        "candidates": {"pending": 0},
        "tasks": {"train": 5, "sealed": 3, "spare": 2},
    }


# 가짜 모델로 끝까지


def test_fake_model_runs_the_example_end_to_end(in_example: Path) -> None:
    before = snapshot(in_example)
    original_skill_md = (in_example / "skills" / SKILL / "SKILL.md").read_text("utf-8")

    composed = ok_json(invoke("compose", SKILL, TRAIN_TASK, "--json"), "compose")
    body = ok_json(invoke(*run_fake(KEEPS)), "run")
    verified = ok_json(invoke("verify", "--json"), "verify")
    status = ok_json(invoke("status", "--json"), "status")

    assert body["violations"] == []
    assert {key: body[key] for key in CHOICE_KEYS} == {key: composed[key] for key in CHOICE_KEYS}
    run_dir = in_example / ".deeptwin" / "runs" / body["run"]
    assert (run_dir / "SKILL.md").read_text("utf-8") == fill_fluid(
        original_skill_md, composed["guide"]
    )
    assert (in_example / ".deeptwin" / body["output"]).read_bytes() == (
        in_example / KEEPS
    ).read_bytes()
    entries = ledger(in_example)
    assert len(entries) == 11
    assert entries[-1]["type"] == "run"
    assert entries[-1]["id"] == body["run"]
    assert verified["lines"] == 11
    assert verified["sealed"] == 3
    assert status["layers"] == counted_from_files(in_example)
    assert status["tasks"] == {"train": 5, "sealed": 3, "spare": 2}
    assert snapshot(in_example) == before


def test_answer_that_breaks_a_principle(in_example: Path) -> None:
    body = ok_json(invoke(*run_fake(BREAKS)), "run")

    assert body["violations"] == [
        {
            "principle": "prin-01",
            "rule": "취업이나 성과를 보장한다고 쓰지 않는다",
            "check": "no_outcome_promise",
        }
    ]
    # 위반은 오류가 아니다. 실행은 원장에 남는다
    assert len(ledger(in_example)) == 11
    ok_json(invoke("verify", "--json"), "verify")


def test_sealed_task_does_not_run(in_example: Path) -> None:
    ledger_path = in_example / ".deeptwin" / "ledger.jsonl"
    ledger_before = ledger_path.read_bytes()

    message = error_json(invoke(*run_fake(KEEPS, SEALED_TASK)), "run", "sealed_access")

    assert SEALED_TASK in message
    assert not (in_example / ".deeptwin" / "runs").exists()
    assert ledger_path.read_bytes() == ledger_before


# 골든


@pytest.mark.parametrize("task_id", GOLDEN_TASKS)
def test_compose_matches_golden(in_example: Path, task_id: str) -> None:
    """학습 과제의 `deeptwin compose --json` 결과(`result`)가 골든 파일과 바이트까지 같다.

    골든 파일은 `tests/golden/inquiry-reply/<과제 ID>.json`이다. `result`를 들여쓰기 2칸의
    JSON(`ensure_ascii=False`)으로 쓰고 끝에 줄바꿈 하나를 붙인 것이다.

    조립 규칙이나 예제 데이터를 일부러 바꿨다면 골든 파일을 다시 만든다:

        DEEPTWIN_UPDATE_GOLDEN=1 uv run pytest tests/test_example.py -k golden

    다시 만든 뒤 `git diff tests/golden`으로 바뀐 곳이 의도한 것인지 읽고 함께 올린다.
    """
    result = ok_json(invoke("compose", SKILL, task_id, "--json"), "compose")
    path = GOLDEN / f"{task_id}.json"
    actual = golden_text(result)
    if os.environ.get(UPDATE_GOLDEN) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")

    expected = path.read_text(encoding="utf-8")

    if actual != expected:
        pytest.fail(golden_diff(json.loads(expected), result, path.name), pytrace=False)


def test_golden_diff_shows_the_changed_lines() -> None:
    golden = {"guide": "반드시 지킬 것\n- 가\n- 나\n", "injected": ["prin-01"], "guide_hash": "a"}
    now = {"guide": "반드시 지킬 것\n- 가\n- 다\n", "injected": ["prin-02"], "guide_hash": "b"}

    message = golden_diff(golden, now, "task-0001.json")

    lines = message.splitlines()
    assert "-- 나" in lines
    assert "+- 다" in lines
    assert '-  "injected": [' not in lines  # 같은 줄은 차이로 나오지 않는다
    assert '-    "prin-01"' in lines
    assert '+    "prin-02"' in lines
    assert REGENERATE in message


def golden_text(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def golden_diff(expected: dict[str, Any], actual: dict[str, Any], name: str) -> str:
    """골든과 지금 결과의 차이. 지침(`guide`)은 줄마다, 나머지는 JSON 줄마다 견준다."""
    lines = [f"조립 결과가 골든 파일 tests/golden/inquiry-reply/{name}과 다릅니다."]
    lines += difflib.unified_diff(
        str(expected.get("guide", "")).splitlines(),
        str(actual.get("guide", "")).splitlines(),
        "골든의 guide",
        "지금의 guide",
        lineterm="",
    )

    def rest(result: dict[str, Any]) -> list[str]:
        others = {key: value for key, value in result.items() if key != "guide"}
        return json.dumps(others, ensure_ascii=False, indent=2).splitlines()

    lines += difflib.unified_diff(
        rest(expected), rest(actual), "골든의 나머지", "지금의 나머지", lineterm=""
    )
    lines.append(f"바꾼 것이 의도한 것이면 골든 파일을 다시 만드세요: {REGENERATE}")
    return "\n".join(lines)


# 예제 데이터의 모양. 평가와 피드백 기능도 이 데이터를 쓴다


def test_skill_has_decision_points_axes_and_checks(example_copy: Path) -> None:
    deeptwin = DeepTwin.open(example_copy)
    skill = deeptwin.skill(SKILL)

    assert len(skill.decision_points) >= 4
    assert skill.context_axes == {
        "purpose": ["교육문의", "수강상담", "구독자질문"],
        "audience": ["입문자", "실무자"],
    }
    assert skill.checks == "checks.py"
    found = prepare_checks(skill, deeptwin).found
    assert [(f.principle.id, f.name) for f in found] == [
        ("prin-01", "no_outcome_promise"),
        ("prin-02", "no_contact_details"),
    ]
    # checks.py는 표준 라이브러리만 쓴다
    source = (example_copy / "skills" / SKILL / "checks.py").read_text("utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported
    assert imported <= sys.stdlib_module_names


def test_layers_have_what_the_later_epics_need(example_copy: Path) -> None:
    deeptwin = DeepTwin.open(example_copy)
    skill = deeptwin.skill(SKILL)
    examples, cards = deeptwin.examples(), deeptwin.cards()

    assert len(examples) >= 6
    signature = [e for e in examples if e.grade == "signature"]
    assert sum(1 for e in signature if e.kind == "good") >= 3
    assert sum(1 for e in signature if e.kind == "avoid") >= 1
    assert sum(1 for e in examples if e.grade == "usual") >= 1

    assert len(cards) >= 8
    points = {point.id for point in skill.decision_points}
    assert {card.decision_point for card in cards} == points
    assert len({json.dumps(card.when, sort_keys=True) for card in cards}) >= 2
    card_ids = {card.id for card in cards}
    assert any(other in card_ids for card in cards for other in card.conflicts_with)

    assert len(deeptwin.priorities()) == 3
    principles = deeptwin.principles()
    assert len(principles) == 3
    assert sum(1 for p in principles if p.check is not None) == 2
    assert all(item.status == "active" for item in [*examples, *cards, *principles])


def test_tasks_have_contexts_and_references(example_copy: Path) -> None:
    deeptwin = DeepTwin.open(example_copy)
    tasks: dict[str, list[Task]] = {
        "train": deeptwin.tasks("train"),
        "sealed": deeptwin.tasks("sealed", token=SealedToken()),
        "spare": deeptwin.tasks("spare"),
    }

    assert {split: [t.id for t in found] for split, found in tasks.items()} == TASK_IDS
    assert all(t.context for found in tasks.values() for t in found)
    assert all(t.reference is not None for t in [*tasks["train"], *tasks["sealed"]])
    kinds = {t.reference.kind for t in tasks["train"] if t.reference is not None}
    assert kinds == {"my_version", "edit", "pick"}


def test_no_task_composes_over_budget(example_copy: Path) -> None:
    deeptwin = DeepTwin.open(example_copy)
    skill = deeptwin.skill(SKILL)
    tasks = [
        *deeptwin.tasks("train"),
        *deeptwin.tasks("sealed", token=SealedToken()),
        *deeptwin.tasks("spare"),
    ]

    for task in tasks:
        composed = compose(skill, task, deeptwin, context=task.context or {})
        assert composed.guide, task.id


def test_every_file_says_its_data_is_made_up(example_copy: Path) -> None:
    assert_files_say_made_up(example_copy)


def test_no_file_has_a_link_mail_address_or_number(example_copy: Path) -> None:
    assert_no_contact_details(example_copy)


def test_os_junk_in_the_example_folder_is_not_copied(tmp_path: Path) -> None:
    # Finder, 탐색기, Python이 추적하지 않는 예제 폴더에 남기는 파일
    source = copy_example(tmp_path / "source")
    (source / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1\xff\xfe")
    (source / "skills" / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1\xff\xfe")
    (source / "Thumbs.db").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1")
    cache = source / "skills" / SKILL / "__pycache__"
    cache.mkdir()
    (cache / "checks.cpython-312.pyc").write_bytes(b"\xcb\r\r\n\x00\xff")

    copied = copy_example(tmp_path / "copy", source)

    assert [p for p in copied.rglob("*") if p.name in EXAMPLE_LEFT_OUT] == []
    assert_files_say_made_up(copied)
    assert_no_contact_details(copied)


def assert_files_say_made_up(root: Path) -> None:
    """예제의 데이터 파일마다 가상 데이터라고 밝혔는지 본다. 규칙 밖의 파일이 있어도 실패한다."""
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        name = path.relative_to(root).as_posix()
        text = path.read_text("utf-8")
        first = text.splitlines()[0]
        if path.suffix in (".yaml", ".py"):
            # 맨 앞의 주석 줄들. 길면 두 줄로 나눠 적는다
            head = " ".join(
                itertools.takewhile(lambda line: line.startswith("#"), text.splitlines())
            )
            assert head.startswith("# 가상의") and "지어낸 것이다." in head, name
        elif name.startswith("answers/"):
            assert first.startswith("<!-- 가상의") and "지어낸 것이다." in first, name
        elif name == f"skills/{SKILL}/SKILL.md":
            # 맨 앞은 스킬의 머리말(---)이라 본문에 적는다
            assert first == "---", name
            assert "모두 예제로 지어낸 것이다." in text, name
        else:
            # 원장(JSONL)에는 주석을 둘 수 없다. 예제 설명서는 데이터가 아니다
            assert name in (".deeptwin/ledger.jsonl", "README.md"), name


CONTACT = re.compile(r"https?://|www\.|[\w.+-]+@[\w-]+\.[\w.-]+|\d{2,6}-\d{2,6}-\d{4,}")
"""링크, 메일 주소, 전화번호나 계좌 번호의 꼴. 날짜(`2026-11-18`)는 걸리지 않는다."""


def assert_no_contact_details(root: Path) -> None:
    """예제의 파일에 링크, 메일 주소, 전화번호나 계좌 번호가 없는지 본다."""
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name == "checks.py":  # 그런 꼴을 찾는 검사 함수의 정규식이 든다
            continue
        found = CONTACT.findall(path.read_text("utf-8"))
        assert found == [], path.relative_to(root).as_posix()
