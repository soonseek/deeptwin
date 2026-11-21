"""실행 기록의 공개 함수 `record_run`과 실행 폴더 지우기. 데이터는 모두 가상이다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptwin import Composed, DeepTwin, Task, record_run
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
