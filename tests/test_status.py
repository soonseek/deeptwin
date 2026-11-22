"""상태 보기: 층별 항목 수, 승인 대기 후보 수, 분할별 과제 수. 데이터는 모두 가상이다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pytest

from deeptwin.importing import import_folder
from deeptwin.models import Candidate, Card, Example, Grade, Principle, Priority, Status, Task
from deeptwin.status import STATUSES, LayerCount, ProjectStatus, project_status
from deeptwin.store.project import DeepTwin


@pytest.fixture
def deeptwin(tmp_path: Path) -> DeepTwin:
    deeptwin = DeepTwin.init(tmp_path / "project").deeptwin
    deeptwin.new_skill("notice")
    return deeptwin


def counts(total: int = 0, signature: int | None = None, **by_status: int) -> LayerCount:
    """적지 않은 상태는 0이다."""
    return LayerCount(
        total=total,
        by_status={status: by_status.get(status, 0) for status in STATUSES},
        signature=signature,
    )


def principle(principle_id: str) -> Principle:
    return Principle(
        id=principle_id,
        rule="수치를 부풀리지 않는다",
        kind="never",
        status="active",
        approval="human",
    )


def card(card_id: str, status: Status = "active") -> Card:
    return Card(
        id=card_id,
        skill="notice",
        decision_point="opening",
        choose="첫 문장에 날짜를 쓴다",
        status=status,
        approval="human",
    )


def candidate(candidate_id: str, status: Literal["pending", "approved", "rejected"]) -> Candidate:
    return Candidate(
        id=candidate_id,
        action="add",
        layer="tendency",
        item=card("card-0101", status="candidate"),
        cause="missing_card",
        status=status,
    )


def test_status_of_the_plan_example(deeptwin: DeepTwin) -> None:
    past = deeptwin.root / "past"
    past.mkdir()
    for n in range(1, 6):
        (past / f"p{n}.txt").write_text(f"{n}번째 지난 공지입니다.\n", encoding="utf-8")
    import_folder(deeptwin, past, skill="notice", signature=True)
    deeptwin.write_principles([principle("prin-01"), principle("prin-02")])
    deeptwin.write_candidate(candidate("cand-0001", "pending"))
    deeptwin.write_candidate(candidate("cand-0002", "approved"))
    deeptwin.add_task(Task(id="task-0001", skill="notice", split="train", input="휴강 공지"))

    assert project_status(deeptwin) == ProjectStatus(
        layers={
            "instinct": counts(5, signature=5, active=5),
            "tendency": counts(),
            "priority": counts(),
            "principle": counts(2, active=2),
        },
        pending_candidates=1,
        tasks={"train": 1, "sealed": 0, "spare": 0},
    )


def test_every_state_is_counted(deeptwin: DeepTwin) -> None:
    statuses: list[Status] = ["active", "candidate", "dormant", "retired", "retired"]
    grades: list[Grade] = ["signature", "usual", "rushed", "signature", "usual"]
    for n, (status, grade) in enumerate(zip(statuses, grades, strict=True), start=1):
        deeptwin.write_example(
            Example(
                id=f"ex-000{n}",
                skill="notice",
                kind="good",
                grade=grade,
                text=f"예시 {n}",
                status=status,
                approval="auto",
            )
        )
    deeptwin.write_card(card("card-0001"))
    deeptwin.write_card(card("card-0002", status="dormant"))
    deeptwin.write_priorities(
        [
            Priority(
                id="pri-01", rule="정확함이 재미보다 먼저다", status="active", approval="human"
            ),
            Priority(
                id="pri-02", rule="짧음이 빠짐없음보다 먼저다", status="retired", approval="human"
            ),
        ]
    )

    layers = project_status(deeptwin).layers

    assert layers["instinct"] == counts(5, signature=2, active=1, candidate=1, dormant=1, retired=2)
    assert layers["tendency"] == counts(2, active=1, dormant=1)
    assert layers["priority"] == counts(2, active=1, retired=1)
    assert layers["principle"] == counts()


def test_an_empty_project_counts_nothing(deeptwin: DeepTwin) -> None:
    status = project_status(deeptwin)

    assert status.layers == {
        "instinct": counts(signature=0),
        "tendency": counts(),
        "priority": counts(),
        "principle": counts(),
    }
    assert status.pending_candidates == 0
    assert status.tasks == {"train": 0, "sealed": 0, "spare": 0}


def test_sealed_tasks_are_counted_without_being_opened(
    deeptwin: DeepTwin, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = deeptwin.path / "tasks" / "sealed"
    # 형식도 틀린 파일이다. 읽었다면 invalid_file로 멈춘다
    (sealed / "task-0101.yaml").write_text("input: [닫히지 않은\n", encoding="utf-8")
    (sealed / "task-0102.yaml").write_text("schema: 1\n", encoding="utf-8")
    (sealed / "._task-0101.yaml").write_bytes(b"\x00")
    (sealed / ".DS_Store").write_bytes(b"\x00")
    (sealed / "notes.txt").write_text("과제 메모", encoding="utf-8")
    (deeptwin.path / "tasks" / "spare" / "task-0201.yaml").write_text("schema: 1\n", "utf-8")

    def no_sealed(original: Any) -> Any:
        def guarded(self: Path, *args: Any, **kwargs: Any) -> Any:
            assert "sealed" not in self.parts, f"봉인 과제를 열었습니다: {self}"
            return original(self, *args, **kwargs)

        return guarded

    for name in ("open", "read_bytes", "read_text"):
        monkeypatch.setattr(Path, name, no_sealed(getattr(Path, name)))

    assert project_status(deeptwin).tasks == {"train": 0, "sealed": 2, "spare": 1}


def test_status_writes_nothing(deeptwin: DeepTwin) -> None:
    deeptwin.add_task(Task(id="task-0001", skill="notice", split="train", input="휴강 공지"))
    before = {p: p.read_bytes() for p in deeptwin.root.rglob("*") if p.is_file()}

    project_status(deeptwin)

    after = {p: p.read_bytes() for p in deeptwin.root.rglob("*") if p.is_file()}
    assert after == before
