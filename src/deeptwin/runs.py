"""생성 길과 실행 기록: 조립, 실행 폴더의 스킬 사본, 생성, 원장의 `run` 줄, 원칙 검사.

`deeptwin run`과 평가(`deeptwin.eval`)가 같은 길을 쓴다. 두 단계로 나눈다.

1. `prepare_run`: 모델을 부르기 전에 알 수 있는 것을 모두 본다. 아무것도 쓰지 않는다.
2. `execute_run`: 실행 폴더를 만들고 생성한 뒤 원장에 남기고 원칙을 검사한다.

모델 호출은 생성 함수(`Generate`)로 주입받는다. 공급자와 호출 기록기를 묶어 넘기는 것은 부르는
쪽(명령줄)이다. 그래서 이 모듈은 모델 호출 계층(`deeptwin.llm`)을 import하지 않는다.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeAlias

from deeptwin.checks import PreparedChecks, prepare_checks
from deeptwin.compose import ExamplePick, compose, fill_fluid
from deeptwin.errors import CheckFailedAfterRunError, CheckFailedError, ContextRequiredError
from deeptwin.models import Composed, Context, Run, Skill, Task, Violation
from deeptwin.store.files import write_text
from deeptwin.store.project import CALLS_FILE, DATA_DIR, DeepTwin

__all__ = [
    "CALLS_FILE",
    "Generate",
    "PreparedRun",
    "execute_run",
    "prepare_run",
    "record_run",
]

OUTPUT_FILE = "output.md"
SKILL_COPY_FILE = "SKILL.md"

Generate: TypeAlias = Callable[[str, str, Path], str]
"""생성 함수: (system, user, `calls.jsonl` 경로) -> 결과물.

system은 지침을 넣은 `SKILL.md` 사본, user는 과제의 `input`이다. 성공한 호출을 그 경로의 파일에
한 줄 남기는 것까지 생성 함수의 몫이다. 실패하면 예외를 내고 아무것도 남기지 않는다.
"""


@dataclass(frozen=True)
class PreparedRun:
    """`prepare_run`이 모델 없이 마친 준비: 조립, 스킬 사본, 찾아 둔 검사 함수."""

    skill: Skill
    task: Task
    context: Context
    """조립에 쓴 맥락."""
    composed: Composed
    skill_copy: str
    """지침을 유동 영역에 넣은 `SKILL.md`의 글. 생성의 system이다."""
    checks: PreparedChecks


@dataclass(frozen=True)
class RunOutcome:
    """`execute_run`의 결과: 원장에 남긴 실행, 결과물, 결과물이 어긴 원칙."""

    record: Run
    output: str
    violations: list[Violation]


def prepare_run(
    deeptwin: DeepTwin,
    skill: Skill,
    task: Task,
    *,
    context: Context,
    ablate: tuple[str, ...] = (),
    example_pick: ExamplePick = "policy",
) -> PreparedRun:
    """모델을 부르기 전에 알 수 있는 것을 이 순서로 본다. 아무것도 쓰지 않는다.

    1. 맥락: 스킬에 맥락 축이 있는데 `context`가 비었으면 `context_required`
    2. 조립(`compose`, `ablate`와 `example_pick`을 그대로 넘긴다)과 스킬 사본(`fill_fluid`):
       `invalid_context`, `unknown_layer`, `over_budget`, `not_enough_examples`,
       `fluid_marker_missing` 등
    3. 원장의 끝 줄: 이어 쓸 `hash`를 얻지 못하면 `ledger_broken`
    4. 원칙의 검사 함수: `check_not_found`, `check_failed`

    `task`는 이미 읽은 과제다. 봉인 과제를 읽는 일(토큰)은 부르는 쪽의 몫이다.
    """
    _require_context(skill, task, context)
    composed = compose(
        skill, task, deeptwin, context=context, ablate=ablate, example_pick=example_pick
    )
    skill_copy = fill_fluid(skill.skill_md.read_text(encoding="utf-8"), composed.guide)
    # 원장에 남길 수 없는 실행은 돌리지 않는다
    deeptwin.ledger_tail_hash()
    # 함수 이름이 틀렸으면 생성 비용을 내기 전에 알린다
    checks = prepare_checks(skill, deeptwin)
    return PreparedRun(
        skill=skill,
        task=task,
        context=dict(context),
        composed=composed,
        skill_copy=skill_copy,
        checks=checks,
    )


def execute_run(deeptwin: DeepTwin, prepared: PreparedRun, generate: Generate) -> RunOutcome:
    """준비한 실행을 돌린다: 실행 폴더, 스킬 사본, 생성, 원장의 `run` 줄, 원칙 검사.

    - 사본 쓰기나 생성이 실패하면(Ctrl-C도) 방금 만든 실행 폴더를 지우고 그 오류를 그대로 낸다.
    - 생성 뒤의 실패(결과물 쓰기, 원장 덧붙이기)에는 폴더를 남긴다. 이미 비용을 낸 호출이다.
    - 검사 함수가 실패하면 `check_failed`(`CheckFailedAfterRunError`)이고, 메시지 다음 줄에 원장에
      남은 실행 ID와 결과물 경로를 쓴다. 위반은 오류가 아니다. 결과의 `violations`에 담는다.
    """
    task = prepared.task
    run_id = deeptwin.new_run()
    with discard_run_on_failure(deeptwin, run_id):
        write_skill_copy(deeptwin, run_id, prepared.skill_copy)
        output = generate(prepared.skill_copy, task.input, deeptwin.run_dir(run_id) / CALLS_FILE)
    record = record_run(
        prepared.composed, task, output, deeptwin, run_id=run_id, context=prepared.context
    )
    violations = _check_output(prepared.checks, output, record)
    return RunOutcome(record=record, output=output, violations=violations)


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


def _check_output(checks: PreparedChecks, output: str, record: Run) -> list[Violation]:
    """기록한 실행의 결과물에 검사 함수를 돌린다. 함수가 실패하면 오류 다음 줄에 실행 ID를 쓴다."""
    try:
        return checks.run(output)
    except CheckFailedError as error:
        raise CheckFailedAfterRunError(
            f"{error.message}\n실행 {record.id}은 원장에 남았고 "
            f"결과물은 {DATA_DIR}/{record.output}에 있습니다.",
            detail=error.message,
            output=output,
        ) from error


def _require_context(skill: Skill, task: Task, context: Context) -> None:
    """스킬의 `context_axes`에 축이 있는데 맥락이 비었으면 `context_required`다.

    스킬에 축이 없으면 줄 맥락이 없으므로 빈 맥락으로 돈다. `compose`(미리 보기)는 보지 않는다.
    """
    if not skill.context_axes or context:
        return
    axes = ", ".join(
        f"{axis}({', '.join(values) or '없음'})" for axis, values in skill.context_axes.items()
    )
    raise ContextRequiredError(
        f"과제 {task.id}에 맥락이 없습니다. "
        "과제 파일의 context에 적거나 --context 축=값으로 주세요. "
        f"스킬 {skill.id}의 축: {axes}"
    )
