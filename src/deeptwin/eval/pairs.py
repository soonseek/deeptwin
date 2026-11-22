"""쌍 만들기: 과제마다 조건별 결과물을 만들고, 조건 이름 없이 좌우를 섞은 쌍 목록을 쓴다.

조건은 셋이다(`CONDITIONS`): 바탕만(`base`), 바탕+예시(`examples`), 바탕+딥트윈(`full`). `full`과
견줄 상대(`AGAINST`의 일부나 전부)를 고르고, 과제마다 `full`과 그 상대들의 결과물을 만든다. 쌍은
과제마다 상대 하나에 하나다.

조건별 결과물은 `deeptwin run`과 같은 생성 길(`runs.prepare_run`, `runs.execute_run`)로 만든다.
실행마다 실행 폴더의 스킬 사본, `calls.jsonl`, 원장의 `run` 줄이 남고 원칙도 검사한다. 원칙을
어긴 결과물도 그대로 쌍에 든다.

두 단계로 나눈다. `prepare_pairs`(새 평가)나 `prepare_resume`(멈춘 평가 이어 가기)가 모델 없이
만들 생성을 모두 준비하고, 부르는 쪽이 공급자를 만든 뒤 `build_pairs`가 평가 폴더에 쓰고 생성한다.
그래서 생성 전에 알 수 있는 실패로는 평가 폴더, 실행 폴더, 원장 줄(`seal_open` 줄 포함), 모델
호출이 생기지 않는다.

봉인 분할은 준비할 때 `sealing.read_sealed`로 과제를 읽고, `build_pairs`가 생성 바로 앞에서
`sealing.open_sealed`로 묶음을 연다(원장의 `seal_open` 줄).

새 평가의 `eval.json`에는 시작할 때의 패키지 버전과 커밋(`provenance`)도 적는다. 보고서가 그
값과 보고서를 낼 때의 값을 견준다. 이어 가기와 봉인 열기는 이 두 값을 바꾸지 않는다.

바탕 스킬의 해시(`DeepTwin.skill_hash`)는 준비할 때 계산해 `eval.json`에 적고, 생성마다 그 앞과
쌍을 쓰기 앞에 다시 계산한다. 다르면 `eval.json`의 `skill_changed`를 참으로 적을 뿐 막지 않는다.
생성에 쓰는 스킬 사본과 검사 함수는 준비 때 이미 만들었으므로 그 명령의 결과물은 달라지지 않는다.

모델 호출 계층(`deeptwin.llm`)을 import하지 않고, 파일에는 저장 계층(`store.evals`,
`DeepTwin`)으로만 닿는다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from deeptwin.compose import LAYERS, ExamplePick
from deeptwin.errors import (
    CheckFailedAfterRunError,
    CheckFailedError,
    NoTasksError,
    TaskNotFoundError,
)
from deeptwin.eval.sealing import open_sealed, read_sealed
from deeptwin.models import Condition, EvalInfo, EvalKey, Pair, PairKey, Skill, Split, Task
from deeptwin.provenance import package_commit, package_version
from deeptwin.runs import Generate, PreparedRun, execute_run, prepare_run
from deeptwin.store.evals import EvalFolder, new_eval, open_eval
from deeptwin.store.project import DeepTwin

__all__ = [
    "AGAINST",
    "BuiltPairs",
    "CONDITIONS",
    "PairPlan",
    "PlannedRun",
    "Recipe",
    "base_skill_changed",
    "build_pairs",
    "prepare_pairs",
    "prepare_resume",
]


@dataclass(frozen=True)
class Recipe:
    """조건 하나를 조립하는 법: 뺄 층과 예시를 고르는 방식(`compose`의 `ablate`, `example_pick`)."""

    ablate: tuple[str, ...]
    example_pick: ExamplePick = "policy"


CONDITIONS: dict[Condition, Recipe] = {
    "base": Recipe(LAYERS),
    "examples": Recipe(("tendency", "priority", "principle"), "past_work"),
    "full": Recipe(()),
}
"""조건 ID -> 조립하는 법.

- `base`(바탕만): 네 층을 모두 뺀다.
- `examples`(바탕+예시): 본능 층만 남기고, 가져온 대표작 good 3개를 과제 ID로 정해지는 순서로
  넣는다(`example_pick="past_work"`). avoid, 학습 중 승인된 예시, 카드, 우선순위, 원칙은 없다.
- `full`(바탕+딥트윈): 아무것도 빼지 않는다.

이 순서가 과제 안의 생성 순서이고 대응표(`key.json`)의 `runs` 순서다.
"""

AGAINST: tuple[Condition, ...] = ("base", "examples")
"""`full`과 견줄 수 있는 상대. 고르지 않으면 모두다. 과제마다 상대 하나에 쌍 하나다."""

_TARGET: Condition = "full"


@dataclass(frozen=True)
class PlannedRun:
    """준비한 생성 하나: 과제, 조건, 준비한 실행."""

    task: str
    condition: Condition
    prepared: PreparedRun


@dataclass(frozen=True)
class PairPlan:
    """`prepare_pairs`나 `prepare_resume`가 모델 없이 마친 준비."""

    skill: str
    split: Split
    tasks: tuple[str, ...]
    """평가할 과제 ID. 파일 이름순이다(이어 가기면 `eval.json`의 순서)."""
    runs: tuple[PlannedRun, ...]
    """만들 생성. 과제마다 `CONDITIONS` 순서다. 이어 가기면 남은 생성뿐이다."""
    eval: str | None = None
    """이어 갈 평가 ID. 새 평가면 `None`이다."""
    seed: str | None = None
    """이어 갈 평가의 씨앗(`eval.json`). 새 평가면 `None`이고 `build_pairs`의 `seed`를 쓴다."""
    against: tuple[Condition, ...] = AGAINST
    """`full`과 견줄 상대. `AGAINST` 순서다. 이어 가기면 `eval.json`의 `against`다."""
    skill_hash: str | None = None
    """바탕 스킬의 해시. 새 평가면 준비할 때 계산한 값이고, 이어 가기면 `eval.json`의 값이다."""

    @property
    def generations(self) -> int:
        """모델을 부를 횟수(생성 수)."""
        return len(self.runs)


@dataclass(frozen=True)
class BuiltPairs:
    """`build_pairs`의 결과. 어느 실행이 어느 조건인지와 위반은 담지 않는다."""

    eval: str
    skill: str
    split: Split
    tasks: tuple[str, ...]
    pairs: int
    seed: str
    reused: tuple[str, ...] = ()
    """다른 평가에서 이미 연 봉인 과제의 ID(`open_sealed`). 봉인이 아니면 비었다."""
    skill_changed: bool = False
    """쌍을 만드는 동안 바탕 스킬이 바뀌었거나, 지금 바탕 스킬이 평가를 시작할 때의 해시와 다르면
    참이다."""
    made: int = 0
    """이번에 만든 결과물(생성)의 수."""


def prepare_pairs(
    deeptwin: DeepTwin,
    skill_id: str,
    *,
    split: Split,
    tasks: Sequence[str] | None = None,
    against: Sequence[Condition] | None = None,
) -> PairPlan:
    """분할 `split`에서 이 스킬의 과제마다 `full`과 상대 조건의 실행을 준비한다. 쓰지 않는다.

    - `against`는 `full`과 견줄 상대다. `None`이면 `AGAINST` 전부이고, 주면 겹친 값을 하나로 쳐
      `AGAINST` 순서로 늘어놓는다. 비었거나 `AGAINST`에 없는 값이 있으면 `ValueError`다.
    - 스킬을 읽은 직후, 과제와 실행을 준비하기 전에 바탕 스킬의 해시를 계산한다(`skill_hash`).
    - 과제는 파일 이름순이다. 봉인 분할은 `sealing.read_sealed`로 읽는다(원장에는 쓰지 않는다).
    - `tasks`를 주면 그 ID의 과제로 좁힌다. 순서는 그래도 파일 이름순이고 겹친 ID는 하나로 친다.
      그 분할에 이 스킬의 과제로 없는 ID가 있으면 `task_not_found`이고 메시지에는 ID만 쓴다.
    - 과제가 없으면 `no_tasks`다. 맥락은 과제 파일의 `context`이고, 준비의 오류는
      `runs.prepare_run`과 같다(`context_required`, `ledger_broken`, `check_not_found` 등).
      바탕+예시를 견주는데 가져온 대표작이 3개보다 적으면 `not_enough_examples`다.
    """
    chosen = _against(against)
    skill = deeptwin.skill(skill_id)
    skill_hash = deeptwin.skill_hash(skill_id)
    found = _skill_tasks(deeptwin, skill_id, split)
    if tasks is not None:
        known = {task.id for task in found}
        missing = [task_id for task_id in dict.fromkeys(tasks) if task_id not in known]
        if missing:
            raise TaskNotFoundError(
                f"{split} 분할에 스킬 {skill_id}의 과제로 없는 ID입니다: {', '.join(missing)}"
            )
        wanted = set(tasks)
        found = [task for task in found if task.id in wanted]
    if not found:
        raise NoTasksError(
            f"{split} 분할에 스킬 {skill_id}의 과제가 없습니다. "
            "deeptwin task add로 과제를 먼저 등록하세요."
        )
    runs = _planned(deeptwin, skill, found, against=chosen, done=set())
    return PairPlan(
        skill=skill_id,
        split=split,
        tasks=tuple(task.id for task in found),
        runs=runs,
        against=chosen,
        skill_hash=skill_hash,
    )


def prepare_resume(deeptwin: DeepTwin, eval_id: str) -> PairPlan:
    """멈춘 평가 `eval_id`의 남은 생성만 준비한다. 아무것도 쓰지 않는다.

    - 스킬, 분할, 과제, 상대, 씨앗, 바탕 스킬의 해시는 `eval.json`의 값이다(`against`가 `["base"]`인
      예전 평가도 그대로 잇는다). 봉인 평가면 과제를 `sealing.read_sealed`로 읽는다. 평가가 없으면
      `eval_not_found`, 과제 파일이 사라졌으면 `task_not_found`다.
    - 끝난 생성은 대응표(`key.json`)의 `runs`에 있고 `outputs/<조건>/<과제 ID>.md`도 있는 것이다.
      나머지를 과제마다 `CONDITIONS` 순서로 준비한다(오류는 `prepare_pairs`와 같다).
    - 쌍 목록(`pairs.jsonl`)이 이미 있으면 만들 생성이 없다.
    """
    folder = open_eval(deeptwin, eval_id)
    info = folder.info()
    against = tuple(info.against)
    plan = PairPlan(
        skill=info.skill,
        split=info.split,
        tasks=tuple(info.tasks),
        runs=(),
        eval=folder.id,
        seed=info.seed,
        against=against,
        skill_hash=info.skill_hash,
    )
    if folder.has_pairs():
        return plan
    skill = deeptwin.skill(info.skill)
    by_id = {task.id: task for task in _skill_tasks(deeptwin, info.skill, info.split)}
    missing = [task_id for task_id in info.tasks if task_id not in by_id]
    if missing:
        raise TaskNotFoundError(
            f"평가 {folder.id}의 과제를 {info.split} 분할에서 찾지 못했습니다: {', '.join(missing)}"
        )
    done = set(_finished(folder))
    wanted = [by_id[task_id] for task_id in info.tasks]
    runs = _planned(deeptwin, skill, wanted, against=against, done=done)
    return replace(plan, runs=runs)


def build_pairs(
    deeptwin: DeepTwin, plan: PairPlan, generate: Generate, *, seed: str | None = None
) -> BuiltPairs:
    """평가 폴더에 준비한 생성을 차례로 돌린 뒤 대응표와 쌍 목록을 쓴다.

    - 새 평가(`plan.eval`이 `None`)면 평가 폴더를 만들고 `eval.json`(`against`는 `plan.against`,
      `skill_hash`는 `plan.skill_hash`, `skill_changed: false`, `package_version`과 `commit`은
      지금의 `package_version()`과 `package_commit()`, `seal_open: null`, `reused: []`)을 쓴다.
      이어 가기면 그 평가 폴더에 이어 쓴다. 그때 `seed`는 줄 수 없다(`ValueError`). 씨앗과 상대,
      시작할 때의 버전과 커밋은 `eval.json`의 값이다.
    - 봉인 평가면 생성 전에 `open_sealed`로 묶음을 연다. 처음이면 원장에 `seal_open` 줄이 생기고
      `eval.json`에 그 줄 ID와 재사용이 적힌다. 이어 가기에서는 줄이 이미 있어 생기지 않는다.
    - 생성마다 `outputs/<조건>/<과제 ID>.md`를 쓰고, 그때까지의 `runs`와 빈 `pairs`로 `key.json`을
      쓴다. 다 만든 뒤 `pairs`를 채운 `key.json`을 쓰고 마지막에 `pairs.jsonl`을 쓴다.
    - 바탕 스킬의 해시를 생성마다 그 바로 앞에서, 그리고 마지막 `key.json`과 `pairs.jsonl`을 쓰기
      바로 앞에서 다시 계산한다. 처음 `eval.json`의 `skill_hash`와 다르다고 보면 잠금 안에서
      `eval.json`을 다시 읽어 `skill_changed`만 참으로 바꿔 쓴다(한 번만). 막지 않는다.
      `skill_hash`가 없는 예전 평가는 보지 않는다.
    - 생성이 실패하면 그 오류를 그대로 낸다. 그때까지 만든 실행, 결과물, `key.json`은 남고
      `pairs.jsonl`은 생기지 않는다. 검사 함수가 실패하면 그 실행의 결과물까지 `outputs/`에 쓴 뒤
      `check_failed`를 내고, 메시지에는 과제와 검사의 문제만 쓴다(실행 ID 없이). 그 생성은
      `runs`에 넣지 않으므로 이어 갈 때 다시 만든다.
    - 이어 가는 평가에 쌍 목록이 이미 있으면 아무것도 만들거나 쓰지 않고 같은 결과를 낸다.
      `skill_changed`는 `base_skill_changed`로 본다.

    `seed`를 주지 않으면 평가 ID가 씨앗이다. 쌍의 순서와 좌우는 (씨앗, 과제 ID, 상대)에서만
    정해진다(`_arrange`). 이어 가면 이전 결과물과 새 결과물을 합쳐 같은 규칙으로 만든다. 쌍
    ID(`pair-NNNN`)는 섞은 순서로 매긴다.
    """
    if plan.eval is None:
        folder = new_eval(deeptwin)
        info = EvalInfo(
            id=folder.id,
            ts=datetime.now().astimezone().isoformat(timespec="seconds"),
            skill=plan.skill,
            split=plan.split,
            tasks=list(plan.tasks),
            against=list(plan.against),
            seed=folder.id if seed is None else seed,
            skill_hash=plan.skill_hash,
            skill_changed=False,
            package_version=package_version(),
            commit=package_commit(),
        )
        folder.save_info(info)
    else:
        if seed is not None:
            raise ValueError("이어 가는 평가의 씨앗은 eval.json의 값입니다. seed는 줄 수 없습니다.")
        folder = open_eval(deeptwin, plan.eval)
        info = folder.info()
    reused: tuple[str, ...] = ()
    if info.split == "sealed":
        opening = open_sealed(deeptwin, folder.id)
        # open_sealed가 적은 seal_open과 reused를 이어 쓴다
        info, reused = opening.eval, opening.reused
    against = tuple(info.against)

    def built(pairs: int, made: int, skill_changed: bool) -> BuiltPairs:
        return BuiltPairs(
            eval=folder.id,
            skill=info.skill,
            split=info.split,
            tasks=tuple(info.tasks),
            pairs=pairs,
            seed=info.seed,
            reused=reused,
            skill_changed=skill_changed,
            made=made,
        )

    if plan.eval is not None and folder.has_pairs():
        return built(len(folder.pairs()), 0, base_skill_changed(deeptwin, info))

    # 한 번 다르다고 보면 다시 보지 않는다(eval.json에는 한 번만 쓴다)
    changed = info.skill_changed

    outputs: dict[tuple[str, Condition], str] = {}
    runs: dict[str, dict[Condition, str]] = {}
    for task, saved in folder.saved_runs().items():
        for condition, run_id in saved.items():
            output = folder.output(condition, task)
            if output is not None:
                outputs[(task, condition)] = output
                runs.setdefault(task, {})[condition] = run_id
    made = 0
    for planned in plan.runs:
        changed = changed or _mark_skill_changed(deeptwin, folder, info)
        try:
            outcome = execute_run(deeptwin, planned.prepared, generate)
        except CheckFailedAfterRunError as error:
            # 실행은 원장에 남았으므로 결과물도 평가 폴더에 둔다. 메시지에는 실행 ID를 쓰지 않는다
            # (만든 순서로 조건을 되짚을 수 있다)
            folder.save_output(planned.condition, planned.task, error.output)
            raise CheckFailedError(
                f"과제 {planned.task}의 결과물을 검사하다 멈췄습니다. {error.detail}"
            ) from None
        folder.save_output(planned.condition, planned.task, outcome.output)
        runs.setdefault(planned.task, {})[planned.condition] = outcome.record.id
        outputs[(planned.task, planned.condition)] = outcome.output
        made += 1
        # 생성이 멈춰도 여기까지 만든 실행을 이어 갈 때 다시 쓰도록 생성마다 남긴다
        folder.save_key(EvalKey(eval=folder.id, runs=_ordered(runs, info.tasks), pairs={}))

    changed = changed or _mark_skill_changed(deeptwin, folder, info)
    keys: dict[str, PairKey] = {}
    pairs: list[Pair] = []
    for number, key in enumerate(_arrange(info.seed, tuple(info.tasks), against), start=1):
        pair_id = f"pair-{number:04d}"
        keys[pair_id] = key
        pairs.append(
            Pair(
                id=pair_id,
                task=key.task,
                left=outputs[(key.task, key.left)],
                right=outputs[(key.task, key.right)],
            )
        )
    folder.save_key(EvalKey(eval=folder.id, runs=_ordered(runs, info.tasks), pairs=keys))
    folder.save_pairs(pairs)
    return built(len(pairs), made, changed)


def base_skill_changed(deeptwin: DeepTwin, info: EvalInfo) -> bool:
    """평가를 시작한 뒤 바탕 스킬이 바뀌었는가. 아무것도 쓰지 않는다.

    `info.skill_changed`(쌍을 만드는 동안 본 표시)가 참이거나, `info.skill_hash`가 있는데 지금
    해시(`DeepTwin.skill_hash`)와 다르면 참이다. `skill_hash`가 없는 예전 평가는 표시만 본다.
    """
    if info.skill_changed:
        return True
    return info.skill_hash is not None and deeptwin.skill_hash(info.skill) != info.skill_hash


def _mark_skill_changed(deeptwin: DeepTwin, folder: EvalFolder, info: EvalInfo) -> bool:
    """바탕 스킬의 지금 해시가 `info.skill_hash`와 다르면 `eval.json`의 `skill_changed`를 참으로
    적고 참을 돌려준다. 같거나 `skill_hash`가 없으면 아무것도 쓰지 않고 거짓이다.

    잠금 안에서 `eval.json`을 다시 읽어 `skill_changed`만 바꿔 쓴다. 그 사이 `open_sealed`가 적은
    `seal_open`과 `reused`는 그대로 남는다.
    """
    if info.skill_hash is None or deeptwin.skill_hash(info.skill) == info.skill_hash:
        return False
    with deeptwin.lock():
        saved = folder.info()
        folder.save_info(saved.model_copy(update={"skill_changed": True}))
    return True


def _against(against: Sequence[Condition] | None) -> tuple[Condition, ...]:
    """`full`과 견줄 상대를 `AGAINST` 순서로 정한다. `None`이면 `AGAINST` 전부다.

    겹친 값은 하나로 친다. 비었거나 `AGAINST`에 없는 값이 있으면 `ValueError`다.
    """
    if against is None:
        return AGAINST
    given = list(dict.fromkeys(against))
    unknown = [value for value in given if value not in AGAINST]
    if unknown:
        raise ValueError(
            f"against에 줄 수 있는 값은 {', '.join(AGAINST)}입니다(받은 값: {unknown[0]!r})."
        )
    if not given:
        raise ValueError(f"against가 비었습니다. {', '.join(AGAINST)} 가운데 하나 이상을 줍니다.")
    return tuple(condition for condition in AGAINST if condition in given)


def _skill_tasks(deeptwin: DeepTwin, skill_id: str, split: Split) -> list[Task]:
    """분할 `split`에서 이 스킬의 과제. 파일 이름순이다. 봉인 분할은 `read_sealed`로 읽는다."""
    if split == "sealed":
        return read_sealed(deeptwin, skill_id)
    return [task for task in deeptwin.tasks(split) if task.skill == skill_id]


def _planned(
    deeptwin: DeepTwin,
    skill: Skill,
    tasks: Sequence[Task],
    *,
    against: Sequence[Condition],
    done: set[tuple[str, Condition]],
) -> tuple[PlannedRun, ...]:
    """과제마다 `full`과 `against`의 조건을 `CONDITIONS` 순서로, `done`에 없는 생성을 준비한다."""
    wanted = {_TARGET, *against}
    return tuple(
        PlannedRun(
            task=task.id,
            condition=condition,
            prepared=prepare_run(
                deeptwin,
                skill,
                task,
                context=task.context or {},
                ablate=recipe.ablate,
                example_pick=recipe.example_pick,
            ),
        )
        for task in tasks
        for condition, recipe in CONDITIONS.items()
        if condition in wanted and (task.id, condition) not in done
    )


def _finished(folder: EvalFolder) -> list[tuple[str, Condition]]:
    """끝난 생성: 대응표의 `runs`에 있고 결과물 파일도 있는 (과제, 조건)."""
    return [
        (task, condition)
        for task, saved in folder.saved_runs().items()
        for condition in saved
        if folder.output(condition, task) is not None
    ]


def _ordered(
    runs: dict[str, dict[Condition, str]], tasks: Sequence[str]
) -> dict[str, dict[Condition, str]]:
    """대응표의 `runs`를 과제 순서, 과제마다 `CONDITIONS` 순서로 늘어놓는다.

    이어 가도 새로 만든 평가와 같은 모양이다.
    """
    return {
        task: {
            condition: runs[task][condition] for condition in CONDITIONS if condition in runs[task]
        }
        for task in tasks
        if task in runs
    }


def _arrange(seed: str, tasks: tuple[str, ...], against: tuple[Condition, ...]) -> list[PairKey]:
    """과제와 상대마다 쌍 하나를 만들어 섞는다.

    - 순서: `sha256(f"{seed}\\n{task}\\n{against}")`의 16진 글 순.
    - 좌우: `sha256(f"{seed}\\n{task}\\n{against}\\nside")`의 첫 바이트가 짝수면 왼쪽이 `full`,
      홀수면 오른쪽이 `full`이다.

    해시만 쓰므로 Python 버전과 운영체제에 상관없이 같고, 상대가 늘어도 같은 규칙이다.
    """
    ranked: list[tuple[str, PairKey]] = []
    for task in tasks:
        for other in against:
            base = f"{seed}\n{task}\n{other}"
            order = hashlib.sha256(base.encode("utf-8")).hexdigest()
            side = hashlib.sha256(f"{base}\nside".encode()).digest()[0]
            left, right = (_TARGET, other) if side % 2 == 0 else (other, _TARGET)
            ranked.append((order, PairKey(task=task, left=left, right=right)))
    ranked.sort(key=lambda item: (item[0], item[1].task, item[1].left, item[1].right))
    return [key for _, key in ranked]
