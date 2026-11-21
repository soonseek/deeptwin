"""실행 기록: 결과물을 실행 폴더에 쓰고 원장에 `run` 줄을 남긴다."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from deeptwin.models import Composed, Run, Task
from deeptwin.store.files import write_text
from deeptwin.store.project import DeepTwin

OUTPUT_FILE = "output.md"
SKILL_COPY_FILE = "SKILL.md"
CALLS_FILE = "calls.jsonl"
"""모델 호출마다 한 줄씩 남기는 기록. 필드는 `models.Call`이다."""


def write_skill_copy(deeptwin: DeepTwin, run_id: str, skill_md: str) -> Path:
    """지침을 넣은 SKILL.md 사본을 실행 폴더에 쓴다. 원본 스킬 파일은 건드리지 않는다."""
    path = deeptwin.run_dir(run_id) / SKILL_COPY_FILE
    write_text(path, skill_md)
    return path


def record_run(
    composed: Composed,
    task: Task,
    output: str,
    deeptwin: DeepTwin,
    *,
    run_id: str | None = None,
) -> Run:
    """`runs/<run_id>/output.md`에 결과물을 쓰고 원장에 `run` 줄 하나를 덧붙인다.

    `run_id`를 주면 `DeepTwin.new_run()`이 미리 만든 그 실행 폴더를 쓰고,
    주지 않으면 새 실행 폴더를 만든다.
    """
    if run_id is None:
        run_id = deeptwin.new_run()
    write_text(deeptwin.run_dir(run_id) / OUTPUT_FILE, output)
    run = Run(
        id=run_id,
        ts=datetime.now().astimezone().isoformat(timespec="seconds"),
        skill=task.skill,
        task=task.id,
        split=task.split,
        injected=list(composed.injected),
        guide_hash=composed.guide_hash,
        output=f"runs/{run_id}/{OUTPUT_FILE}",
    )
    deeptwin.append_ledger(run.model_dump(mode="json"))
    return run
