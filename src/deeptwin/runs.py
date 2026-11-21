"""실행 기록: 결과물을 실행 폴더에 쓰고 원장에 `run` 줄을 남긴다."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from deeptwin.models import Composed, Context, Run, Task
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


@contextmanager
def discard_run_on_failure(deeptwin: DeepTwin, run_id: str) -> Iterator[None]:
    """블록이 예외로 끝나면 실행 폴더 `runs/<run_id>/`를 지우고 그 예외를 그대로 낸다.

    `KeyboardInterrupt`(Ctrl-C)처럼 `Exception`이 아닌 것도 지운다. 지우다 실패해도 오류를
    내지 않는다. 원래 오류를 가리지 않으려는 것이다. 방금 `new_run()`으로 만든 폴더에만 쓴다.
    """
    try:
        yield
    except BaseException:
        shutil.rmtree(deeptwin.run_dir(run_id), ignore_errors=True)
        raise


def record_run(
    composed: Composed,
    task: Task,
    output: str,
    deeptwin: DeepTwin,
    *,
    run_id: str | None = None,
    context: Context | None = None,
) -> Run:
    """`runs/<run_id>/output.md`에 결과물을 쓰고 원장에 `run` 줄 하나를 덧붙인다.

    `run_id`를 주면 `DeepTwin.new_run()`이 미리 만든 그 실행 폴더를 쓰고,
    주지 않으면 새 실행 폴더를 만든다.
    `context`는 조립에 쓴 맥락이다. 주지 않으면 과제 파일의 `context`이고, 그것도 없으면 `{}`다.
    `prompt_version`은 생성이 아직 프롬프트 자산을 쓰지 않아 늘 `None`이다.
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
        context=dict(task.context or {}) if context is None else dict(context),
        injected=list(composed.injected),
        rejected=list(composed.rejected),
        no_hit=list(composed.no_hit),
        conflicts=[list(pair) for pair in composed.conflicts],
        guide_hash=composed.guide_hash,
        prompt_version=None,
        output=f"runs/{run_id}/{OUTPUT_FILE}",
    )
    deeptwin.append_ledger(run.model_dump(mode="json"))
    return run
