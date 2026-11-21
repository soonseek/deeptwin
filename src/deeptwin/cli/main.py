"""`deeptwin` 명령줄."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Self

import typer

from deeptwin.cli.output import Reply, respond
from deeptwin.compose import LAYERS, check_context, compose, fill_fluid
from deeptwin.errors import (
    ContextRequiredError,
    FakeAnswerRequiredError,
    InvalidContextError,
    TaskSkillMismatchError,
    UnknownProviderError,
)
from deeptwin.llm import ClaudeCLIProvider, FakeProvider, Provider
from deeptwin.llm.calls import CallRecorder
from deeptwin.models import Composed, Context, Run, Skill, Task
from deeptwin.runs import CALLS_FILE, discard_run_on_failure, record_run, write_skill_copy
from deeptwin.store.guard import problem_lines, sealed_changed
from deeptwin.store.ledger import ledger_broken
from deeptwin.store.project import DATA_DIR, LEDGER_FILE, DeepTwin, read_task_file

app = typer.Typer(
    name="deeptwin",
    help="개인의 판단 기준을 쌓아 스킬의 유동 영역에 조립하고 실행한다.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
task_app = typer.Typer(
    name="task",
    help="과제를 학습(train), 봉인(sealed), 예비(spare) 가운데 하나로 등록한다.",
    no_args_is_help=True,
)
app.add_typer(task_app, name="task")

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
ContextOption = Annotated[
    list[str] | None,
    typer.Option(
        "--context",
        metavar="축=값",
        help="맥락 축 하나의 값. 과제 파일의 context 위에 축마다 덮어쓴다. 여러 번 줄 수 있다.",
        show_default=False,
    ),
]
AblateOption = Annotated[
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
]
"""`--context`와 `--ablate`는 `compose`와 `run`이 같은 정의를 쓴다. 푸는 것은 `ComposeOptions`다."""


@dataclass(frozen=True)
class ComposeOptions:
    """`--context`와 `--ablate`를 푼 값. `compose`와 `run`이 같은 길로 맥락과 뺄 층을 정한다."""

    overrides: Context
    """`--context`로 준 축과 값."""
    ablate: tuple[str, ...]
    """뺄 층. 준 순서대로, 겹친 이름은 한 번만 든다."""

    @classmethod
    def parse(cls, context_options: list[str] | None, ablate_options: list[str] | None) -> Self:
        """`--context`의 모양이 틀리면 `invalid_context`다(`parse_context_options`).

        층 이름이 네 층인지는 `compose`가 본다(`unknown_layer`).
        """
        return cls(
            overrides=parse_context_options(context_options or []),
            # 준 순서는 지키고 겹친 이름은 하나로 친다
            ablate=tuple(dict.fromkeys(ablate_options or [])),
        )

    def context_for(self, task: Task) -> Context:
        """조립에 쓸 맥락: 과제 파일의 `context` 위에 `--context`를 축마다 덮어쓴 것."""
        return {**(task.context or {}), **self.overrides}


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
    context_options: ContextOption = None,
    ablate_options: AblateOption = None,
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
    """스킬을 과제 하나로 돌린다: 조립, 실행 폴더에 SKILL.md 사본 쓰기, 생성, 실행 기록.

    맥락과 뺄 층은 compose와 같다. 스킬에 맥락 축이 있는데 맥락이 없거나, 원장에 이어 쓸 수
    없으면 모델을 부르기 전에 멈춘다. 생성이 실패하면 만든 실행 폴더를 지운다.
    """

    def action() -> Reply:
        # 아래 순서로 본다. 생성 전에 멈추면 실행 폴더, 원장 줄, 모델 호출이 생기지 않는다
        # 1. 프로젝트, 스킬, 과제. 봉인 과제면 저장 계층이 sealed_access를 낸다
        deeptwin = DeepTwin.open(Path.cwd())
        skill = deeptwin.skill(skill_id)
        task = deeptwin.task(task_id)
        _ensure_task_of_skill(task, skill_id, doing="실행한")
        # 2. 맥락과 뺄 층. compose와 같은 길로 정한다
        options = ComposeOptions.parse(context_options, ablate_options)
        context = options.context_for(task)
        _require_context(skill, task, context)
        # 3. 조립
        composed = compose(skill, task, deeptwin, context=context, ablate=options.ablate)
        skill_copy = fill_fluid(skill.skill_md.read_text(encoding="utf-8"), composed.guide)
        # 4. 원장에 이어 쓸 수 있는지. 원장에 남길 수 없는 실행은 돌리지 않는다
        deeptwin.ledger_tail_hash()
        # 5. 공급자. claude가 없거나 fake에 답 파일이 없으면 여기서 멈춘다
        llm = make_provider(provider, ProviderOptions(fake_answer=fake_answer))
        # 6. 실행 폴더. 사본 쓰기나 생성이 실패하면(Ctrl-C도) 이 폴더를 지운다
        run_id = deeptwin.new_run()
        with discard_run_on_failure(deeptwin, run_id):
            write_skill_copy(deeptwin, run_id, skill_copy)
            recorder = CallRecorder(llm, deeptwin.run_dir(run_id) / CALLS_FILE)
            output = recorder.complete(skill_copy, task.input)
        # 생성 뒤의 실패(결과물 쓰기, 원장 덧붙이기)에는 폴더를 남긴다. 이미 비용을 낸 호출이다
        record = record_run(composed, task, output, deeptwin, run_id=run_id, context=context)
        return Reply(
            result={
                "run": record.id,
                "task": record.task,
                "split": record.split,
                "context": record.context,
                "ablate": list(options.ablate),
                "injected": record.injected,
                "rejected": [r.model_dump(mode="json") for r in record.rejected],
                "no_hit": record.no_hit,
                "conflicts": record.conflicts,
                "guide_hash": record.guide_hash,
                "output": record.output,
            },
            text="\n".join(
                [
                    f"{record.id} 실행을 마쳤습니다.",
                    *_choice_lines(record),
                    f"결과물: {DATA_DIR}/{record.output}",
                ]
            ),
        )

    respond("run", action, as_json=as_json)


@app.command("compose")
def compose_guide(
    skill_id: SkillArgument,
    task_id: TaskArgument,
    context_options: ContextOption = None,
    ablate_options: AblateOption = None,
    as_json: JsonOption = False,
) -> None:
    """조립한 지침만 출력한다. 모델을 부르지 않고, 실행 폴더와 원장에도 쓰지 않는다."""

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        options = ComposeOptions.parse(context_options, ablate_options)
        skill = deeptwin.skill(skill_id)
        task = deeptwin.task(task_id)
        _ensure_task_of_skill(task, skill_id, doing="조립한")
        # 미리 보기라 맥락이 비어도 조립한다(run과 달리 context_required를 보지 않는다)
        context = options.context_for(task)
        composed = compose(skill, task, deeptwin, context=context, ablate=options.ablate)
        return Reply(
            result={
                "guide": composed.guide,
                "injected": composed.injected,
                "rejected": [r.model_dump(mode="json") for r in composed.rejected],
                "no_hit": composed.no_hit,
                "conflicts": composed.conflicts,
                "guide_hash": composed.guide_hash,
                "context": context,
                "ablate": list(options.ablate),
            },
            text="\n".join(
                [
                    composed.guide.removesuffix("\n") or "넣을 기준이 없습니다.",
                    "",
                    *_choice_lines(composed),
                    f"guide_hash: {composed.guide_hash}",
                ]
            ),
        )

    respond("compose", action, as_json=as_json)


def _choice_lines(made: Composed | Run) -> list[str]:
    """조립의 선택을 사람에게 보이는 세 줄: 넣은 항목, 뺀 항목, 맞는 카드가 없던 판단 지점.

    `compose`와 `run`의 글 모드가 같은 문구를 쓴다.
    """
    rejected = ", ".join(f"{r.id}({r.reason})" for r in made.rejected)
    return [
        f"넣은 항목: {', '.join(made.injected) or '없음'}",
        f"뺀 항목: {rejected or '없음'}",
        f"맞는 카드가 없던 판단 지점: {', '.join(made.no_hit) or '없음'}",
    ]


def _require_context(skill: Skill, task: Task, context: Context) -> None:
    """스킬의 `context_axes`에 축이 있는데 맥락이 비었으면 `context_required`다.

    스킬에 축이 없으면 줄 맥락이 없으므로 빈 맥락으로 돈다. `run`만 본다.
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
    """원장(.deeptwin/ledger.jsonl)의 해시 체인과 봉인 과제의 기준 해시를 검사한다."""

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        # 체인과 봉인을 같은 잠금 안에서 본다. 그 사이에 과제가 등록되지 않는다
        with deeptwin.lock():
            check = deeptwin.verify_ledger()
            sealed = deeptwin.verify_sealed()
        if check.damages:
            raise ledger_broken(
                deeptwin.path / LEDGER_FILE,
                deeptwin.root,
                check.damages,
                note="\n".join(problem_lines(sealed.problems)),
            )
        if sealed.problems:
            raise sealed_changed(sealed.problems)
        shown = f"{DATA_DIR}/{LEDGER_FILE}"
        lines = [
            f"원장 {shown}의 {check.lines}줄이 모두 해시로 이어져 있습니다."
            if check.lines
            else f"원장 {shown}에 아직 줄이 없습니다."
        ]
        if sealed.checked:
            lines.append(f"봉인 과제 {sealed.checked}개의 기준이 등록 때와 같습니다.")
        return Reply(
            result={"lines": check.lines, "head": check.head, "sealed": sealed.checked},
            text="\n".join(lines),
        )

    respond("verify", action, as_json=as_json)


@task_app.command("add")
def task_add(
    task_file: Annotated[
        Path,
        typer.Argument(
            metavar="FILE",
            exists=True,
            dir_okay=False,
            readable=True,
            help="등록할 과제 파일(YAML). split에 train, sealed, spare 가운데 하나를 적는다.",
            show_default=False,
        ),
    ],
    as_json: JsonOption = False,
) -> None:
    """과제 파일 하나를 등록한다: 원장에 task 줄을 남기고 .deeptwin/tasks/<split>/<id>.yaml에 쓴다.

    같은 ID는 다시 등록할 수 없어 분할은 바뀌지 않는다.
    봉인(sealed) 과제는 기준(reference)이 있어야 하고, 원장에 기준의 해시가 남는다.
    기준의 내용은 출력하지 않는다.
    """

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        task = read_task_file(task_file, root=deeptwin.root)
        skill = deeptwin.skill(task.skill)
        check_context(skill, task.context or {})
        added = deeptwin.add_task(task)
        entry = added.entry
        path = added.path.relative_to(deeptwin.path).as_posix()
        lines = [
            f"과제 {entry.id}을 {entry.split} 분할에 등록했습니다.",
            f"과제 파일: {DATA_DIR}/{path}",
        ]
        if entry.reference_hash is not None:
            lines.append(f"기준 해시: {entry.reference_hash}")
        return Reply(
            result={
                "task": entry.id,
                "split": entry.split,
                "skill": entry.skill,
                "path": path,
                "reference_hash": entry.reference_hash,
            },
            text="\n".join(lines),
        )

    respond("task add", action, as_json=as_json)
