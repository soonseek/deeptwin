"""실행 기록의 공개 함수 `record_run`, 실행 폴더 지우기, 실행 ID 매기기. 데이터는 모두 가상이다."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import deeptwin.runs as runs
from deeptwin import Composed, DeepTwin, DeeptwinError, Task, record_run
from deeptwin.errors import ProviderFailedError
from deeptwin.models import Rejected
from deeptwin.runs import OUTPUT_FILE, discard_run_on_failure

LEDGER_KEYS = [
    "id",
    "type",
    "ts",
    "skill",
    "task",
    "split",
    "context",
    "injected",
    "rejected",
    "no_hit",
    "conflicts",
    "guide_hash",
    "prompt_version",
    "output",
    "prev_hash",
    "hash",
]

COMPOSED = Composed(
    guide="## 이번 작업의 개인 기준\n",
    injected=["prin-01", "card-0001"],
    rejected=[Rejected(id="card-0002", reason="budget")],
    no_hit=["tone"],
    conflicts=[],
    guide_hash="sha256:" + "1" * 64,
)


@pytest.fixture
def deeptwin(tmp_path: Path) -> DeepTwin:
    return DeepTwin.init(tmp_path).deeptwin


def task(context: dict[str, str] | None) -> Task:
    """가상의 문의 과제."""
    return Task(
        id="task-0001",
        skill="minimal",
        split="train",
        input="수강료를 알려 주세요.",
        context=context,
    )


def ledger(deeptwin: DeepTwin) -> list[dict[str, Any]]:
    text = (deeptwin.path / "ledger.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


# record_run


def test_record_run_with_four_arguments_takes_the_task_context(deeptwin: DeepTwin) -> None:
    run = record_run(COMPOSED, task({"purpose": "문의"}), "가짜 답장\n", deeptwin)

    [entry] = ledger(deeptwin)
    assert list(entry) == LEDGER_KEYS
    assert entry["id"] == run.id == "run-0001"
    assert entry["type"] == "run"
    assert entry["context"] == run.context == {"purpose": "문의"}
    assert entry["prompt_version"] is None
    assert run.prompt_version is None
    assert entry["injected"] == ["prin-01", "card-0001"]
    assert entry["rejected"] == [{"id": "card-0002", "reason": "budget"}]
    assert entry["no_hit"] == ["tone"]
    assert entry["guide_hash"] == COMPOSED.guide_hash
    assert entry["output"] == f"runs/run-0001/{OUTPUT_FILE}"
    assert (deeptwin.run_dir("run-0001") / OUTPUT_FILE).read_text("utf-8") == "가짜 답장\n"


def test_record_run_of_a_task_without_context_writes_an_empty_context(deeptwin: DeepTwin) -> None:
    record_run(COMPOSED, task(None), "가짜 답장\n", deeptwin)

    assert ledger(deeptwin)[0]["context"] == {}


def test_record_run_writes_the_given_context(deeptwin: DeepTwin) -> None:
    run_id = deeptwin.new_run()

    run = record_run(
        COMPOSED,
        task({"purpose": "문의"}),
        "가짜 답장\n",
        deeptwin,
        run_id=run_id,
        context={"purpose": "상담"},
    )

    [entry] = ledger(deeptwin)
    assert entry["id"] == run.id == run_id
    assert entry["context"] == {"purpose": "상담"}


# 실행 폴더 지우기


@pytest.mark.parametrize(
    "error",
    [RuntimeError("가짜 실패"), KeyboardInterrupt()],
    ids=["error", "ctrl-c"],
)
def test_failed_block_removes_the_run_folder_and_raises_the_same_error(
    deeptwin: DeepTwin, error: BaseException
) -> None:
    kept = deeptwin.new_run()
    run_id = deeptwin.new_run()

    with pytest.raises(type(error)) as info, discard_run_on_failure(deeptwin, run_id):
        (deeptwin.run_dir(run_id) / "SKILL.md").write_text("사본\n", encoding="utf-8")
        raise error

    assert info.value is error
    assert not deeptwin.run_dir(run_id).exists()
    assert deeptwin.run_dir(kept).is_dir()


def test_finished_block_keeps_the_run_folder(deeptwin: DeepTwin) -> None:
    run_id = deeptwin.new_run()

    with discard_run_on_failure(deeptwin, run_id):
        (deeptwin.run_dir(run_id) / "SKILL.md").write_text("사본\n", encoding="utf-8")

    assert (deeptwin.run_dir(run_id) / "SKILL.md").is_file()


# 실행 ID


def test_record_run_after_deleting_the_latest_run_folder_takes_a_new_id(deeptwin: DeepTwin) -> None:
    record_run(COMPOSED, task(None), "첫 답장\n", deeptwin)
    record_run(COMPOSED, task(None), "둘째 답장\n", deeptwin)
    shutil.rmtree(deeptwin.run_dir("run-0002"))

    run = record_run(COMPOSED, task(None), "셋째 답장\n", deeptwin)

    assert run.id == "run-0003"
    assert [entry["id"] for entry in ledger(deeptwin)] == ["run-0001", "run-0002", "run-0003"]


def test_new_run_counts_run_lines_of_the_ledger_without_run_folders(deeptwin: DeepTwin) -> None:
    deeptwin.append_ledger({"id": "run-0005", "type": "run"})
    # 실행 줄이 아니면 ID가 run-NNNN 모양이어도 세지 않는다
    deeptwin.append_ledger({"id": "run-0009", "type": "task"})
    assert list((deeptwin.path / "runs").iterdir()) == []

    assert deeptwin.new_run() == "run-0006"
    assert deeptwin.run_dir("run-0006").is_dir()


def test_new_run_takes_the_larger_of_folders_and_ledger(deeptwin: DeepTwin) -> None:
    deeptwin.append_ledger({"id": "run-0002", "type": "run"})
    (deeptwin.path / "runs" / "run-0004").mkdir()

    assert deeptwin.new_run() == "run-0005"
    deeptwin.append_ledger({"id": "run-0009", "type": "run"})
    assert deeptwin.new_run() == "run-0010"


def test_new_run_skips_ledger_lines_it_cannot_read(deeptwin: DeepTwin) -> None:
    deeptwin.append_ledger({"id": "run-0002", "type": "run"})
    path = deeptwin.path / "ledger.jsonl"
    unreadable = [
        b"{not json",
        b"[1]",
        b"",
        b"\xff\xfe",
        b'{"type": "run", "id": "run-0007"',  # 반쯤 잘린 줄
        b'{"type": "run", "id": 8}',
        b'{"type": "run", "id": "run-x9"}',
        b'{"type": "run"}',
    ]
    path.write_bytes(path.read_bytes() + b"\n".join(unreadable) + b"\n")

    # 원장이 깨졌는지는 번호 매기기가 보지 않는다. 그것은 verify와 ledger_tail_hash의 몫이다
    assert deeptwin.new_run() == "run-0003"
    with pytest.raises(DeeptwinError) as info:
        deeptwin.ledger_tail_hash()
    assert info.value.code == "ledger_broken"


def test_new_run_ignores_ledger_run_ids_longer_than_nine_digits(deeptwin: DeepTwin) -> None:
    deeptwin.append_ledger({"id": "run-0003", "type": "run"})
    # int()가 거부하는 길이(4300자리 넘음)와, 한 자리 넘는 것
    deeptwin.append_ledger({"id": "run-" + "9" * 5000, "type": "run"})
    deeptwin.append_ledger({"id": "run-" + "1" * 10, "type": "run"})

    assert deeptwin.new_run() == "run-0004"
    deeptwin.append_ledger({"id": "run-" + "9" * 9, "type": "run"})
    assert deeptwin.new_run() == "run-1000000000"


# 생성 길: prepare_run, execute_run


def tree(folder: Path) -> dict[str, bytes]:
    """폴더의 파일과 바이트. 잠금 파일(`.lock`)은 잠금을 잡기만 해도 생기므로 뺀다."""
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != ".lock"
    }


def test_execute_run_gives_the_generator_the_copy_and_a_calls_path_in_the_run_folder(
    minimal_copy: Path,
) -> None:
    deeptwin = DeepTwin.open(minimal_copy)
    skill = deeptwin.skill("minimal")
    the_task = deeptwin.task("task-0001")
    seen: list[tuple[str, str, Path]] = []

    def generate(system: str, user: str, calls: Path) -> str:
        seen.append((system, user, calls))
        calls.write_text('{"가짜": "호출 기록"}\n', encoding="utf-8")
        return "가짜 답장\n"

    prepared = runs.prepare_run(deeptwin, skill, the_task, context={"purpose": "문의"})
    outcome = runs.execute_run(deeptwin, prepared, generate)

    run_dir = deeptwin.run_dir(outcome.record.id)
    [(system, user, calls_path)] = seen
    assert system == (run_dir / "SKILL.md").read_text("utf-8") == prepared.skill_copy
    assert user == the_task.input
    assert calls_path == run_dir / runs.CALLS_FILE
    assert calls_path.parent == run_dir
    assert outcome.output == "가짜 답장\n"
    assert (run_dir / OUTPUT_FILE).read_text("utf-8") == "가짜 답장\n"
    assert outcome.violations == []
    [entry] = ledger(deeptwin)
    assert list(entry) == LEDGER_KEYS
    assert entry["id"] == outcome.record.id == "run-0001"
    assert entry["context"] == {"purpose": "문의"}
    assert entry["guide_hash"] == prepared.composed.guide_hash


def test_execute_run_with_every_layer_ablated_still_records_the_run(minimal_copy: Path) -> None:
    deeptwin = DeepTwin.open(minimal_copy)
    skill = deeptwin.skill("minimal")
    the_task = deeptwin.task("task-0001")
    prepared = runs.prepare_run(
        deeptwin,
        skill,
        the_task,
        context={"purpose": "문의"},
        ablate=("instinct", "tendency", "priority", "principle"),
    )

    outcome = runs.execute_run(deeptwin, prepared, lambda system, user, calls: "가짜 답장\n")

    assert prepared.composed.injected == []
    assert ledger(deeptwin)[0]["injected"] == []
    assert outcome.record.injected == []


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ("no-context", "context_required"),
        ("broken-ledger", "ledger_broken"),
    ],
)
def test_prepare_run_that_stops_writes_nothing(minimal_copy: Path, damage: str, code: str) -> None:
    deeptwin = DeepTwin.open(minimal_copy)
    skill = deeptwin.skill("minimal")
    the_task = deeptwin.task("task-0001")
    context = {"purpose": "문의"}
    if damage == "no-context":
        context = {}
    else:
        (deeptwin.path / "ledger.jsonl").write_bytes(b'{"id": "run-0001", "type": "run"')
    before = tree(minimal_copy)

    with pytest.raises(DeeptwinError) as info:
        runs.prepare_run(deeptwin, skill, the_task, context=context)

    assert info.value.code == code
    assert tree(minimal_copy) == before
    assert not (deeptwin.path / "runs").exists() or list((deeptwin.path / "runs").iterdir()) == []


def test_failed_generation_leaves_no_run_folder_and_no_ledger_line(minimal_copy: Path) -> None:
    deeptwin = DeepTwin.open(minimal_copy)
    prepared = runs.prepare_run(
        deeptwin,
        deeptwin.skill("minimal"),
        deeptwin.task("task-0001"),
        context={"purpose": "문의"},
    )

    def generate(system: str, user: str, calls: Path) -> str:
        raise ProviderFailedError("가짜 공급자가 실패했습니다.")

    with pytest.raises(ProviderFailedError):
        runs.execute_run(deeptwin, prepared, generate)

    assert list((deeptwin.path / "runs").iterdir()) == []
    assert not (deeptwin.path / "ledger.jsonl").exists()
