"""`deeptwin` 명령줄."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from deeptwin.cli.output import Reply, respond
from deeptwin.compose import LAYERS, compose, fill_fluid
from deeptwin.errors import (
    FakeAnswerRequiredError,
    InvalidContextError,
    TaskSkillMismatchError,
    UnknownProviderError,
)
from deeptwin.llm import ClaudeCLIProvider, FakeProvider, Provider
from deeptwin.llm.calls import CallRecorder
from deeptwin.models import Context, Task
from deeptwin.runs import CALLS_FILE, record_run, write_skill_copy
from deeptwin.store.ledger import ledger_broken
from deeptwin.store.project import DATA_DIR, LEDGER_FILE, DeepTwin

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
SkillArgument = Annotated[
    str, typer.Argument(metavar="SKILL", help="skills/ 아래의 스킬 ID", show_default=False)
]
TaskArgument = Annotated[
    str, typer.Argument(metavar="TASK", help="과제 ID(예: task-0001)", show_default=False)
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


def _claude_provider(options: ProviderOptions) -> Provider:
    # 실행 파일이 없으면 여기서 claude_not_found가 난다. 실행 폴더를 만들기 전이다
    return ClaudeCLIProvider()


PROVIDERS: dict[str, Callable[[ProviderOptions], Provider]] = {
    "claude": _claude_provider,
    "fake": _fake_provider,
}
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
    skill_id: SkillArgument,
    task_id: TaskArgument,
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help=(
                "모델 공급자 이름. 기본값 claude는 claude CLI를 Claude Code의 구독 로그인으로 "
                "부른다. fake는 테스트와 예제 확인용이다."
            ),
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
        _ensure_task_of_skill(task, skill_id, doing="실행한")
        composed = compose(skill, task, deeptwin, context=task.context or {})
        skill_copy = fill_fluid(skill.skill_md.read_text(encoding="utf-8"), composed.guide)
        run_id = deeptwin.new_run()
        write_skill_copy(deeptwin, run_id, skill_copy)
        recorder = CallRecorder(llm, deeptwin.run_dir(run_id) / CALLS_FILE)
        output = recorder.complete(skill_copy, task.input)
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


@app.command("compose")
def compose_guide(
    skill_id: SkillArgument,
    task_id: TaskArgument,
    context_options: Annotated[
        list[str] | None,
        typer.Option(
            "--context",
            metavar="축=값",
            help=(
                "맥락 축 하나의 값. 과제 파일의 context 위에 축마다 덮어쓴다. 여러 번 줄 수 있다."
            ),
            show_default=False,
        ),
    ] = None,
    ablate_options: Annotated[
        list[str] | None,
        typer.Option(
            "--ablate",
            metavar="층",
            help=(
                f"빼고 조립할 층({', '.join(LAYERS)}). 여러 번 줄 수 있고, "
                "같은 층을 두 번 주면 한 번 준 것과 같다."
            ),
            show_default=False,
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """조립한 지침만 출력한다. 모델을 부르지 않고, 실행 폴더와 원장에도 쓰지 않는다."""

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        overrides = parse_context_options(context_options or [])
        # 준 순서는 지키고 겹친 이름은 하나로 친다. 모르는 이름은 compose가 거부한다
        ablate = tuple(dict.fromkeys(ablate_options or []))
        skill = deeptwin.skill(skill_id)
        task = deeptwin.task(task_id)
        _ensure_task_of_skill(task, skill_id, doing="조립한")
        context = {**(task.context or {}), **overrides}
        composed = compose(skill, task, deeptwin, context=context, ablate=ablate)
        rejected = ", ".join(f"{r.id}({r.reason})" for r in composed.rejected)
        return Reply(
            result={
                "guide": composed.guide,
                "injected": composed.injected,
                "rejected": [r.model_dump(mode="json") for r in composed.rejected],
                "no_hit": composed.no_hit,
                "conflicts": composed.conflicts,
                "guide_hash": composed.guide_hash,
                "context": context,
                "ablate": list(ablate),
            },
            text="\n".join(
                [
                    composed.guide.removesuffix("\n") or "넣을 기준이 없습니다.",
                    "",
                    f"넣은 항목: {', '.join(composed.injected) or '없음'}",
                    f"뺀 항목: {rejected or '없음'}",
                    f"맞는 카드가 없던 판단 지점: {', '.join(composed.no_hit) or '없음'}",
                    f"guide_hash: {composed.guide_hash}",
                ]
            ),
        )

    respond("compose", action, as_json=as_json)


def parse_context_options(options: list[str]) -> Context:
    """`--context 축=값`들을 맥락으로 바꾼다. 값에 든 `=`는 값의 일부다.

    `=`가 없거나, 축 이름이 비었거나, 같은 축을 두 번 주면 `invalid_context`다.
    축과 값이 스킬에 있는지는 `compose`가 본다.
    """
    context: Context = {}
    for option in options:
        axis, sep, value = option.partition("=")
        if not sep:
            raise InvalidContextError(f"--context는 축=값 모양이어야 합니다(받은 값: {option}).")
        if not axis.strip():
            raise InvalidContextError(f"--context의 축 이름이 비었습니다(받은 값: {option}).")
        if axis in context:
            raise InvalidContextError(
                f"--context에 같은 축을 두 번 줬습니다: {axis}. 축마다 한 번만 주세요."
            )
        context[axis] = value
    return context


def _ensure_task_of_skill(task: Task, skill_id: str, *, doing: str) -> None:
    """과제 파일의 `skill`이 명령에 준 스킬과 같은지 본다. `doing`은 메시지의 동사다."""
    if task.skill != skill_id:
        raise TaskSkillMismatchError(
            f"과제와 스킬이 맞지 않습니다. 과제 {task.id}의 skill: {task.skill}, "
            f"{doing} 스킬: {skill_id}"
        )


@app.command()
def verify(as_json: JsonOption = False) -> None:
    """원장(.deeptwin/ledger.jsonl)의 해시 체인을 처음부터 다시 계산해 손상된 줄을 찾는다."""

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        check = deeptwin.verify_ledger()
        if check.damages:
            raise ledger_broken(deeptwin.path / LEDGER_FILE, deeptwin.root, check.damages)
        shown = f"{DATA_DIR}/{LEDGER_FILE}"
        return Reply(
            result={"lines": check.lines, "head": check.head},
            text=(
                f"원장 {shown}의 {check.lines}줄이 모두 해시로 이어져 있습니다."
                if check.lines
                else f"원장 {shown}에 아직 줄이 없습니다."
            ),
        )

    respond("verify", action, as_json=as_json)
