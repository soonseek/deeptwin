"""`deeptwin` 명령줄."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from deeptwin.cli.output import Reply, respond
from deeptwin.compose import compose, fill_fluid
from deeptwin.errors import (
    FakeAnswerRequiredError,
    TaskSkillMismatchError,
    UnknownProviderError,
)
from deeptwin.llm import FakeProvider, Provider
from deeptwin.runs import record_run, write_skill_copy
from deeptwin.store.project import DATA_DIR, DeepTwin

app = typer.Typer(
    name="deeptwin",
    help="개인의 판단 기준을 쌓아 스킬의 유동 영역에 조립하고 실행한다.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)

JsonOption = Annotated[
    bool,
    typer.Option("--json", help="결과를 JSON 객체 하나로 stdout에 쓴다. 에이전트가 읽는 용도다."),
]


@dataclass(frozen=True)
class ProviderOptions:
    """공급자를 만들 때 명령줄에서 넘겨받는 값."""

    fake_answer: Path | None = None


def _fake_provider(options: ProviderOptions) -> Provider:
    if options.fake_answer is None:
        raise FakeAnswerRequiredError("--provider fake에는 --fake-answer <파일>이 필요합니다.")
    # 줄바꿈을 바꾸지 않고 읽는다. 결과물 output.md가 답 파일과 바이트까지 같다
    return FakeProvider([options.fake_answer.read_bytes().decode("utf-8")])


PROVIDERS: dict[str, Callable[[ProviderOptions], Provider]] = {"fake": _fake_provider}
"""공급자 이름표. 이름 -> 공급자를 만드는 함수."""

DEFAULT_PROVIDER = "claude"


def make_provider(name: str, options: ProviderOptions) -> Provider:
    factory = PROVIDERS.get(name)
    if factory is None:
        names = ", ".join(sorted(PROVIDERS))
        raise UnknownProviderError(f"알 수 없는 공급자입니다: {name}. 쓸 수 있는 이름: {names}")
    return factory(options)


@app.command()
def init(as_json: JsonOption = False) -> None:
    """지금 폴더에 .deeptwin/을 만들고 .gitignore에 .deeptwin/을 더한다."""

    def action() -> Reply:
        done = DeepTwin.init(Path.cwd())
        lines = [
            f"{DATA_DIR}/ 폴더를 준비했습니다."
            if done.created
            else f"{DATA_DIR}/ 폴더는 이미 준비돼 있습니다."
        ]
        lines.append(
            f".gitignore에 {DATA_DIR}/을 더했습니다."
            if done.gitignore == "added"
            else f".gitignore에는 이미 {DATA_DIR}/이 있습니다."
        )
        return Reply(
            result={"created": list(done.created), "gitignore": done.gitignore},
            text="\n".join(lines),
        )

    respond("init", action, as_json=as_json)


@app.command()
def run(
    skill_id: Annotated[
        str, typer.Argument(metavar="SKILL", help="skills/ 아래의 스킬 ID", show_default=False)
    ],
    task_id: Annotated[
        str, typer.Argument(metavar="TASK", help="과제 ID(예: task-0001)", show_default=False)
    ],
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="모델 공급자 이름. fake는 테스트와 예제 확인용이다.",
        ),
    ] = DEFAULT_PROVIDER,
    fake_answer: Annotated[
        Path | None,
        typer.Option(
            "--fake-answer",
            exists=True,
            dir_okay=False,
            readable=True,
            help="fake 공급자가 돌려줄 답 파일. 테스트와 예제 확인용이다.",
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """스킬을 과제 하나로 돌린다: 조립, 실행 폴더에 SKILL.md 사본 쓰기, 생성, 실행 기록."""

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        llm = make_provider(provider, ProviderOptions(fake_answer=fake_answer))
        skill = deeptwin.skill(skill_id)
        task = deeptwin.task(task_id)
        if task.skill != skill_id:
            raise TaskSkillMismatchError(
                f"과제와 스킬이 맞지 않습니다. 과제 {task.id}의 skill: {task.skill}, "
                f"실행한 스킬: {skill_id}"
            )
        composed = compose(skill, task, deeptwin, context=task.context or {})
        skill_copy = fill_fluid(skill.skill_md.read_text(encoding="utf-8"), composed.guide)
        run_id = deeptwin.new_run()
        write_skill_copy(deeptwin, run_id, skill_copy)
        output = llm.complete(skill_copy, task.input)
        record = record_run(composed, task, output, deeptwin, run_id=run_id)
        injected = ", ".join(record.injected) or "없음"
        return Reply(
            result={
                "run": record.id,
                "guide_hash": record.guide_hash,
                "injected": record.injected,
                "output": record.output,
            },
            text="\n".join(
                [
                    f"{record.id} 실행을 마쳤습니다.",
                    f"넣은 항목: {injected}",
                    f"결과물: {DATA_DIR}/{record.output}",
                ]
            ),
        )

    respond("run", action, as_json=as_json)
