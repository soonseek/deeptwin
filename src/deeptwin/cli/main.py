"""`deeptwin` 명령줄."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Self, cast, get_args

import typer

from deeptwin.cli.output import Reply, respond
from deeptwin.cli.session import SKILL_CHANGED, summary
from deeptwin.cli.terminal import judge_in_terminal
from deeptwin.cli.web import judge_in_web
from deeptwin.compose import LAYERS, check_context, compose
from deeptwin.errors import (
    FakeAnswerRequiredError,
    InvalidContextError,
    TaskSkillMismatchError,
    UnknownProviderError,
)
from deeptwin.eval import AGAINST, build_pairs, prepare_pairs, prepare_resume, report
from deeptwin.importing import TEXT_SUFFIXES, import_folder
from deeptwin.llm import ClaudeCLIProvider, FakeProvider, Provider
from deeptwin.llm.calls import CallRecorder
from deeptwin.models import Composed, Condition, Context, Run, Split, Task, Violation
from deeptwin.runs import Generate, execute_run, prepare_run
from deeptwin.status import STATUSES, project_status
from deeptwin.store.files import display_path
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
skill_app = typer.Typer(
    name="skill",
    help="스킬 폴더(skills/<id>/)를 만든다.",
    no_args_is_help=True,
)
app.add_typer(skill_app, name="skill")
eval_app = typer.Typer(
    name="eval",
    help=(
        "바탕만, 바탕+예시, 바탕+딥트윈의 결과물을 과제마다 만들어, 어느 쪽인지 가린 채 둘씩 "
        "고르고 보고서를 낸다."
    ),
    no_args_is_help=True,
)
app.add_typer(eval_app, name="eval")

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
ProviderOption = Annotated[
    str,
    typer.Option(
        "--provider",
        help=(
            "모델 공급자 이름. 기본값 claude는 claude CLI를 Claude Code의 구독 로그인으로 "
            "부른다. fake는 테스트와 예제 확인용이다."
        ),
    ),
]
FakeAnswerOption = Annotated[
    Path | None,
    typer.Option(
        "--fake-answer",
        exists=True,
        dir_okay=False,
        readable=True,
        help="fake 공급자가 돌려줄 답 파일. 테스트와 예제 확인용이다.",
    ),
]
"""`--provider`와 `--fake-answer`는 `run`과 `eval pairs`가 같은 정의를 쓴다."""
EvalArgument = Annotated[
    str, typer.Argument(metavar="EVAL", help="평가 ID(예: eval-0001)", show_default=False)
]


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
    fake_repeat: int = 1
    """fake 공급자가 답 파일을 몇 번 돌려줄지. 만들 생성 수만큼 준다(`eval pairs`, 이어 가기면
    남은 생성 수)."""


def _fake_provider(options: ProviderOptions) -> Provider:
    if options.fake_answer is None:
        raise FakeAnswerRequiredError("--provider fake에는 --fake-answer <파일>이 필요합니다.")
    # 줄바꿈을 바꾸지 않고 읽는다. 결과물 output.md가 답 파일과 바이트까지 같다
    answer = options.fake_answer.read_bytes().decode("utf-8")
    return FakeProvider([answer] * options.fake_repeat)


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


def _recorded(llm: Provider) -> Generate:
    """공급자를 생성 함수로 묶는다. 성공한 호출마다 받은 `calls.jsonl`에 한 줄을 남긴다."""

    def generate(system: str, user: str, calls: Path) -> str:
        return CallRecorder(llm, calls).complete(system, user)

    return generate


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
    provider: ProviderOption = DEFAULT_PROVIDER,
    fake_answer: FakeAnswerOption = None,
    as_json: JsonOption = False,
) -> None:
    """스킬을 과제 하나로 돌린다: 조립, 실행 폴더에 SKILL.md 사본 쓰기, 생성, 실행 기록, 원칙 검사.

    맥락과 뺄 층은 compose와 같다. 스킬에 맥락 축이 있는데 맥락이 없거나, 원장에 이어 쓸 수
    없거나, 원칙의 검사 함수를 찾지 못하면 모델을 부르기 전에 멈춘다. 생성이 실패하면 만든 실행
    폴더를 지운다. 결과물이 어긴 원칙은 결과에 보여 줄 뿐 오류가 아니다.
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
        # 3. 맥락(context_required), 조립, 원장의 끝 줄, 원칙의 검사 함수. 아무것도 쓰지 않는다
        prepared = prepare_run(
            deeptwin, skill, task, context=options.context_for(task), ablate=options.ablate
        )
        # 4. 공급자. claude가 없거나 fake에 답 파일이 없으면 여기서 멈춘다
        llm = make_provider(provider, ProviderOptions(fake_answer=fake_answer))
        # 5. 실행 폴더, 생성, 원장 줄, 원칙 검사. 생성이 실패하면(Ctrl-C도) 실행 폴더를 지운다.
        # 위반이 있어도 실행과 원장 줄은 그대로다
        outcome = execute_run(deeptwin, prepared, _recorded(llm))
        record, violations = outcome.record, outcome.violations
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
                "violations": [v.model_dump(mode="json") for v in violations],
            },
            text="\n".join(
                [
                    f"{record.id} 실행을 마쳤습니다.",
                    *_choice_lines(record),
                    *_violation_lines(violations),
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


def _violation_lines(violations: list[Violation]) -> list[str]:
    """어긴 원칙마다 한 줄. 없으면 `어긴 원칙이 없습니다.` 한 줄이다."""
    if not violations:
        return ["어긴 원칙이 없습니다."]
    return [f"어긴 원칙: {v.principle} {v.rule}" for v in violations]


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


@skill_app.command("new")
def skill_new(
    skill_id: Annotated[
        str,
        typer.Argument(
            metavar="ID",
            help="새 스킬 ID. 영문자, 숫자, '.', '_', '-'만 쓰고 영문자나 숫자로 시작한다.",
            show_default=False,
        ),
    ],
    as_json: JsonOption = False,
) -> None:
    """skills/<id>/에 스킬 뼈대를 만든다: skill.yaml, 유동 영역이 표시된 SKILL.md, 빈 checks.py.

    그 폴더가 이미 있으면 아무 파일도 바꾸지 않고 멈춘다.
    """

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        made = deeptwin.new_skill(skill_id)
        files = [display_path(path, deeptwin.root) for path in made.files]
        return Reply(
            result={"skill": made.skill.id, "files": files},
            text="\n".join(
                [
                    f"스킬 {made.skill.id}의 뼈대를 만들었습니다: {', '.join(files)}",
                    "SKILL.md에 고정 지침을, skill.yaml에 판단 지점과 맥락 축을 채우세요.",
                ]
            ),
        )

    respond("skill new", action, as_json=as_json)


@app.command("import")
def import_examples(
    folder: Annotated[
        Path,
        typer.Argument(
            metavar="FOLDER",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help=(
                f"과거 작업물 폴더. 바로 아래의 {', '.join(TEXT_SUFFIXES)} 파일 하나가 예시 "
                "하나가 된다."
            ),
            show_default=False,
        ),
    ],
    skill_id: Annotated[
        str,
        typer.Option("--skill", metavar="ID", help="예시를 넣을 스킬 ID", show_default=False),
    ],
    signature: Annotated[
        bool,
        typer.Option("--signature", help="대표작(grade: signature)으로 표시한다."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """과거 작업물을 본능 층의 예시로 가져온다. 글 파일 하나가 예시 하나다.

    파일 이름순으로 ex-NNNN 번호를 매긴다. 같은 스킬에 글이 같은 예시가 있으면 건너뛰어,
    같은 폴더를 다시 가져와도 늘지 않는다. 비었거나 UTF-8이 아닌 파일이 있으면 아무것도
    쓰지 않는다.
    """

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        done = import_folder(deeptwin, folder, skill=skill_id, signature=signature)
        grade = "signature" if signature else "usual"
        root = deeptwin.root
        imported = [{"id": i.example.id, "file": display_path(i.file, root)} for i in done.imported]
        skipped = [{"file": display_path(s.file, root), "same_as": s.same_as} for s in done.skipped]
        lines = [
            f"스킬 {skill_id}에 예시 {len(imported)}건을 가져왔습니다(grade: {grade})."
            if imported
            else f"스킬 {skill_id}에 새로 가져온 예시가 없습니다."
        ]
        if skipped:
            shown = ", ".join(f"{s['file']}(같은 예시: {s['same_as']})" for s in skipped)
            lines.append(f"같은 글이 있어 건너뛴 파일 {len(skipped)}개: {shown}")
        return Reply(
            result={"skill": skill_id, "imported": imported, "skipped": skipped},
            text="\n".join(lines),
        )

    respond("import", action, as_json=as_json)


LAYER_NAMES = {
    "instinct": "예시",
    "tendency": "판단 카드",
    "priority": "우선순위",
    "principle": "원칙",
}
"""`status`의 글 모드에 쓰는 층 이름."""
SPLIT_NAMES = {"train": "학습", "sealed": "봉인", "spare": "예비"}


@app.command()
def status(as_json: JsonOption = False) -> None:
    """쌓인 상태를 한 번에 본다: 층별 항목 수, 승인 대기 후보 수, 분할별 과제 수.

    봉인 과제는 파일 수만 세고 내용을 읽지 않는다.
    """

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        counts = project_status(deeptwin)
        layers: dict[str, dict[str, int]] = {}
        for layer, count in counts.layers.items():
            layers[layer] = {"total": count.total, **{s: count.by_status[s] for s in STATUSES}}
            if count.signature is not None:
                layers[layer]["signature"] = count.signature
        layer_text = ", ".join(
            f"{LAYER_NAMES[layer]} {count.by_status['active']}/{count.total}"
            + (f"(대표작 {count.signature})" if count.signature is not None else "")
            for layer, count in counts.layers.items()
        )
        task_text = ", ".join(f"{SPLIT_NAMES[split]} {n}" for split, n in counts.tasks.items())
        return Reply(
            result={
                "layers": layers,
                "candidates": {"pending": counts.pending_candidates},
                "tasks": dict(counts.tasks),
            },
            text="\n".join(
                [
                    f"층별 항목(active/전체): {layer_text}",
                    f"승인 대기 후보 {counts.pending_candidates}개. 과제: {task_text}",
                ]
            ),
        )

    respond("status", action, as_json=as_json)


SPLIT_CHOICES: tuple[str, ...] = get_args(Split)
"""`--split`에 줄 수 있는 값. 세 분할(train, sealed, spare)이다."""


def _split_choice(value: str | None) -> str | None:
    """`--split`을 세 분할 가운데 하나로 받는다. 아니면 Click의 인자 오류(종료 2)다.

    주지 않았으면 `None`이다(`--resume`이면 주지 않는다). `Literal` 인자를 받지 못하는 typer에서도
    돌도록 `str`로 받아 여기서 본다. typer 0.29는 click을 안에 품고 `click_type`을 받지 않으므로
    click을 직접 import하지 않고 `typer.BadParameter`를 낸다.
    """
    if value is None:
        return None
    if value not in SPLIT_CHOICES:
        raise typer.BadParameter(
            f"쓸 수 있는 값은 {', '.join(SPLIT_CHOICES)}입니다(받은 값: {value!r})."
        )
    return value


def _against_choice(values: list[str] | None) -> list[str] | None:
    """`--against`를 `AGAINST`(base, examples)의 값으로만 받는다.

    다른 값이면 Click의 인자 오류(종료 2)다. 주지 않았으면 `None`이다(그러면 상대 전부다).
    `_split_choice`와 같은 꼴로 `str`로 받아 여기서 본다.
    """
    if not values:
        return None
    for value in values:
        if value not in AGAINST:
            raise typer.BadParameter(
                f"쓸 수 있는 값은 {', '.join(AGAINST)}입니다(받은 값: {value!r})."
            )
    return values


@eval_app.command("pairs")
def eval_pairs(
    skill_id: Annotated[
        str | None,
        typer.Argument(
            metavar="SKILL",
            help="skills/ 아래의 스킬 ID. --resume이 없으면 꼭 준다.",
            show_default=False,
        ),
    ] = None,
    split: Annotated[
        str | None,
        typer.Option(
            "--split",
            metavar="train|sealed|spare",
            callback=_split_choice,
            help=(
                "평가할 과제의 분할: train, sealed, spare. --resume이 없으면 꼭 준다. 봉인"
                "(sealed)은 평가를 시작할 때 묶음을 열고 원장에 seal_open 줄을 남긴다."
            ),
            show_default=False,
        ),
    ] = None,
    task_options: Annotated[
        list[str] | None,
        typer.Option(
            "--task",
            metavar="과제 ID",
            help=(
                "평가할 과제를 이 ID로 좁힌다. 여러 번 줄 수 있다. 순서는 그래도 파일 이름순이다."
            ),
            show_default=False,
        ),
    ] = None,
    against_options: Annotated[
        list[str] | None,
        typer.Option(
            "--against",
            metavar="상대",
            callback=_against_choice,
            help=(
                "바탕+딥트윈과 견줄 상대: base(바탕만), examples(바탕+예시). 여러 번 줄 수 있다. "
                "주지 않으면 둘 다다. 과제마다 상대 하나에 쌍 하나를 만든다."
            ),
            show_default=False,
        ),
    ] = None,
    seed: Annotated[
        str | None,
        typer.Option(
            "--seed",
            metavar="글",
            help="쌍의 순서와 좌우를 정하는 씨앗. 주지 않으면 평가 ID다.",
            show_default=False,
        ),
    ] = None,
    resume: Annotated[
        str | None,
        typer.Option(
            "--resume",
            metavar="EVAL",
            help=(
                "생성이 멈춘 평가를 이어 간다. 남은 결과물만 만들고 쌍 목록을 쓴다. "
                "SKILL, --split, --task, --against, --seed와 함께 주지 않는다."
            ),
            show_default=False,
        ),
    ] = None,
    provider: ProviderOption = DEFAULT_PROVIDER,
    fake_answer: FakeAnswerOption = None,
    as_json: JsonOption = False,
) -> None:
    """분할의 과제마다 바탕+딥트윈과 상대(바탕만, 바탕+예시)의 결과물을 만들고, 어느 쪽인지 가린
    쌍 목록을 쓴다.

    쌍은 과제마다 상대 하나에 하나다. 바탕+예시는 가져온 대표작 3개만 넣고, 3개가 안 되면
    not_enough_examples로 멈춘다. 결과물은 deeptwin run과 같은 길로 만들어 실행마다 원장에 남는다.
    모든 과제와 조건을 모델 없이 준비한 뒤에 공급자와 평가 폴더(.deeptwin/eval/<평가 ID>/)를
    만들므로, 생성 전에 멈추면 평가 폴더, 실행 폴더, 원장 줄, 모델 호출이 생기지 않는다. 봉인
    분할은 생성 바로 앞에서 묶음을 열어 원장에 seal_open 줄을 남기고, 다른 평가에서 이미 연 과제는
    재사용으로 적는다. 바탕 스킬의 파일이 평가 중에 바뀌면 알리고 보고서에 표시한다(막지 않는다).
    생성이 중간에 멈추면 --resume <평가 ID>로 남은 것만 만든다.
    """
    tasks = task_options or None
    against = cast(list[Condition] | None, against_options or None)
    if resume is None:
        if skill_id is None:
            raise typer.BadParameter("--resume이 없으면 스킬 ID를 줍니다.", param_hint="'SKILL'")
        if split is None:
            raise typer.BadParameter("--resume이 없으면 --split을 줍니다.", param_hint="'--split'")
    else:
        given = [
            hint
            for hint, value in (
                ("'SKILL'", skill_id),
                ("'--split'", split),
                ("'--task'", tasks),
                ("'--seed'", seed),
                ("'--against'", against),
            )
            if value is not None
        ]
        if given:
            raise typer.BadParameter(
                "--resume에는 줄 수 없습니다. 이어 가는 평가의 eval.json에 적힌 스킬, 분할, 과제, "
                "상대, 씨앗을 씁니다.",
                param_hint=given[0],
            )

    def action() -> Reply:
        # 1. 프로젝트, 스킬, 과제(no_tasks, task_not_found). 봉인 분할도 준비에서는 원장에
        #    쓰지 않는다
        # 2. 만들 생성마다의 준비(맥락, 조립, 원장의 끝 줄, 검사 함수, 대표작 수). 아무것도 쓰지
        #    않는다. 이어 가기는 eval.json의 스킬, 분할, 과제, 상대, 씨앗으로 남은 생성만 준비한다
        deeptwin = DeepTwin.open(Path.cwd())
        if resume is None:
            assert skill_id is not None and split is not None
            plan = prepare_pairs(
                deeptwin, skill_id, split=cast(Split, split), tasks=tasks, against=against
            )
        else:
            plan = prepare_resume(deeptwin, resume)
        # 3. 공급자. fake는 만들 생성 수만큼 같은 답을 준다
        options = ProviderOptions(fake_answer=fake_answer, fake_repeat=plan.generations)
        llm = make_provider(provider, options)
        # 4. 평가 폴더, 봉인이면 묶음 열기(seal_open 줄), 생성. 어느 실행이 어느 조건인지는
        #    key.json에만 남고 출력하지 않는다
        built = build_pairs(deeptwin, plan, _recorded(llm), seed=seed)
        lines = [
            f"평가 {built.eval}을 만들었습니다. 스킬 {built.skill}, 분할 {built.split}, "
            f"과제 {len(built.tasks)}개, 쌍 {built.pairs}개, 씨앗 {built.seed}."
            if resume is None
            else f"평가 {built.eval}을 이어 만들었습니다. "
            f"이번에 만든 결과물 {built.made}개, 쌍 {built.pairs}개."
        ]
        if built.reused:
            lines.append(
                f"다른 평가에서 이미 연 봉인 과제가 들어 있습니다: {', '.join(built.reused)}. "
                "보고서에 재사용으로 적습니다."
            )
        if built.skill_changed:
            lines.append(SKILL_CHANGED.format(skill=built.skill))
        lines.append(f"deeptwin eval judge {built.eval}로 고르세요.")
        return Reply(
            result={
                "eval": built.eval,
                "skill": built.skill,
                "split": built.split,
                "tasks": list(built.tasks),
                "pairs": built.pairs,
                "seed": built.seed,
                "reused": list(built.reused),
                "skill_changed": built.skill_changed,
            },
            text="\n".join(lines),
        )

    respond("eval pairs", action, as_json=as_json)


DEFAULT_LIMIT = 15
"""`eval judge`가 한 번에 보여 주는 쌍 수의 기본값(설계서 11의 평가 피로)."""
DEFAULT_DAILY_LIMIT = 30
"""`eval judge`로 한 평가에서 하루에 고르는 쌍 수의 기본값."""


@eval_app.command("judge")
def eval_judge(
    eval_id: EvalArgument,
    web: Annotated[
        bool,
        typer.Option(
            "--web",
            help=(
                "터미널 대신 127.0.0.1에만 여는 웹 화면에서 고른다. 알려 주는 주소를 브라우저로 "
                "연다. 다 고르면 서버가 저절로 닫힌다."
            ),
        ),
    ] = False,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            min=0,
            max=65535,
            metavar="번호",
            help="--web의 포트(0~65535). 주지 않으면 빈 포트를 쓴다. --web과 함께만 준다.",
            show_default=False,
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            metavar="수",
            help="한 번에 보여 주는 쌍의 수. 남은 쌍은 다음에 이어 고른다.",
        ),
    ] = DEFAULT_LIMIT,
    daily_limit: Annotated[
        int,
        typer.Option(
            "--daily-limit",
            min=1,
            metavar="수",
            help="이 평가에서 하루에 고르는 쌍의 수. choices.jsonl에서 오늘 고른 줄을 센다.",
        ),
    ] = DEFAULT_DAILY_LIMIT,
    as_json: JsonOption = False,
) -> None:
    """남은 쌍을 하나씩 보여 주고 고를 때마다 바로 기록한다. 기본은 터미널, --web이면 웹 화면이다.

    한 번에 --limit쌍, 이 평가에서 하루에 --daily-limit쌍까지 보여 주고, 상한에 닿으면 남은 쌍의
    수를 알리고 멈춘다. 고른 쌍은 다시 보여 주지 않고 다음에는 남은 쌍부터 잇는다. 터미널은 1이나
    2를 받고 입력이 끝나면(EOF) 멈춘다. 웹 화면은 127.0.0.1에만 열고 버튼 둘로 고른다. 화면에는
    어느 쪽이 어느 조건인지 나오지 않는다. --json이면 보여 주는 글은 stderr로 가고, stdout에는
    끝난 뒤 결과 하나를 쓴다.
    """
    if port is not None and not web:
        raise typer.BadParameter("--port는 --web과 함께만 줍니다.", param_hint="'--port'")

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        if web:
            judged = judge_in_web(
                deeptwin,
                eval_id,
                port=port,
                limit=limit,
                daily_limit=daily_limit,
                err=as_json,
            )
        else:
            judged = judge_in_terminal(
                deeptwin, eval_id, limit=limit, daily_limit=daily_limit, err=as_json
            )
        return Reply(
            result={"eval": judged.eval, "chosen": judged.chosen, "remaining": judged.remaining},
            text=summary(judged),
        )

    respond("eval judge", action, as_json=as_json)


@eval_app.command("report")
def eval_report(eval_id: EvalArgument, as_json: JsonOption = False) -> None:
    """모든 쌍을 골랐으면 대응표를 합쳐 이긴 횟수, 선택률, p값을 report.json과 report.md로 쓴다.

    남은 쌍이 있으면 그 수를 알리고 보고서를 쓰지 않는다. 다시 내면 같은 바이트다.
    """

    def action() -> Reply:
        deeptwin = DeepTwin.open(Path.cwd())
        made = report(deeptwin, eval_id)
        files = list(made.files)
        return Reply(
            result={**made.report.model_dump(mode="json", exclude={"schema_"}), "files": files},
            text="\n".join(
                [
                    made.markdown.rstrip("\n"),
                    "",
                    f"보고서 파일: {', '.join(f'{DATA_DIR}/{f}' for f in files)}",
                ]
            ),
        )

    respond("eval report", action, as_json=as_json)
