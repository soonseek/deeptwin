"""쌍 만들기: 과제마다 두 조건의 결과물을 만들고, 조건 이름 없이 좌우를 섞은 쌍 목록을 쓴다.

조건별 결과물은 `deeptwin run`과 같은 생성 길(`runs.prepare_run`, `runs.execute_run`)로 만든다.
실행마다 실행 폴더의 스킬 사본, `calls.jsonl`, 원장의 `run` 줄이 남고 원칙도 검사한다. 원칙을
어긴 결과물도 그대로 쌍에 든다.

두 단계로 나눈다. `prepare_pairs`가 모델 없이 모든 과제와 조건을 준비하고, 부르는 쪽이 공급자를
만든 뒤 `build_pairs`가 평가 폴더를 만들고 생성한다. 그래서 생성 전에 알 수 있는 실패로는 평가
폴더, 실행 폴더, 원장 줄, 모델 호출이 생기지 않는다.

모델 호출 계층(`deeptwin.llm`)을 import하지 않고, 파일에는 저장 계층(`store.evals`)으로만 닿는다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from deeptwin.compose import LAYERS
from deeptwin.errors import CheckFailedAfterRunError, CheckFailedError, NoTasksError
from deeptwin.models import Condition, EvalInfo, EvalKey, Pair, PairKey, Split
from deeptwin.runs import Generate, PreparedRun, execute_run, prepare_run
from deeptwin.store.evals import new_eval
from deeptwin.store.project import DeepTwin

__all__ = [
    "AGAINST",
    "BuiltPairs",
    "CONDITIONS",
    "PairPlan",
    "PlannedRun",
    "build_pairs",
    "prepare_pairs",
]

CONDITIONS: dict[Condition, tuple[str, ...]] = {
    "base": LAYERS,
    "full": (),
}
"""조건 ID -> 조립에서 뺄 층. `base`(바탕만)는 네 층을 모두 빼고, `full`(바탕+딥트윈)은 다 넣는다.

과제마다 이 순서로 만든다.
"""

AGAINST: tuple[Condition, ...] = ("base",)
"""`full`과 견주는 상대. 과제마다 상대 하나에 쌍 하나다."""

_TARGET: Condition = "full"


@dataclass(frozen=True)
class PlannedRun:
    """준비한 생성 하나: 과제, 조건, 준비한 실행."""

    task: str
    condition: Condition
    prepared: PreparedRun


@dataclass(frozen=True)
class PairPlan:
    """`prepare_pairs`가 모델 없이 마친 준비."""

    skill: str
    split: Split
    tasks: tuple[str, ...]
    """평가할 과제 ID. 파일 이름순이다."""
    runs: tuple[PlannedRun, ...]
    """만들 생성. 과제마다 `CONDITIONS` 순서다."""

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


def prepare_pairs(deeptwin: DeepTwin, skill_id: str, *, split: Split) -> PairPlan:
    """분할 `split`에서 이 스킬의 과제마다 두 조건의 실행을 준비한다. 아무것도 쓰지 않는다.

    과제는 파일 이름순이다. 봉인 분할은 저장 계층이 `sealed_access`로 막는다. 과제가 없으면
    `no_tasks`다. 맥락은 과제 파일의 `context`이고, 준비의 오류는 `runs.prepare_run`과 같다
    (`context_required`, `ledger_broken`, `check_not_found` 등).
    """
    skill = deeptwin.skill(skill_id)
    tasks = [task for task in deeptwin.tasks(split) if task.skill == skill_id]
    if not tasks:
        raise NoTasksError(
            f"{split} 분할에 스킬 {skill_id}의 과제가 없습니다. "
            "deeptwin task add로 과제를 먼저 등록하세요."
        )
    runs = tuple(
        PlannedRun(
            task=task.id,
            condition=condition,
            prepared=prepare_run(deeptwin, skill, task, context=task.context or {}, ablate=ablate),
        )
        for task in tasks
        for condition, ablate in CONDITIONS.items()
    )
    return PairPlan(skill=skill_id, split=split, tasks=tuple(task.id for task in tasks), runs=runs)


def build_pairs(
    deeptwin: DeepTwin, plan: PairPlan, generate: Generate, *, seed: str | None = None
) -> BuiltPairs:
    """평가 폴더를 만들고 준비한 생성을 차례로 돌린 뒤 대응표와 쌍 목록을 쓴다.

    쓰는 순서는 `eval.json`, 생성마다 `outputs/<조건>/<과제 ID>.md`, `key.json`, 마지막에
    `pairs.jsonl`이다. 생성이 실패하면 그 오류를 그대로 내고, 그때까지 만든 실행과 결과물은
    남지만 `key.json`과 `pairs.jsonl`은 생기지 않는다. 검사 함수가 실패하면 그 실행의 결과물까지
    `outputs/`에 쓴 뒤 `check_failed`를 내고, 메시지에는 과제와 검사의 문제만 쓴다(실행 ID 없이).

    `seed`를 주지 않으면 평가 ID가 씨앗이다. 쌍의 순서와 좌우는 (씨앗, 과제 ID, 상대)에서만
    정해진다(`_arrange`). 쌍 ID(`pair-NNNN`)는 섞은 순서로 매긴다.
    """
    folder = new_eval(deeptwin)
    used_seed = folder.id if seed is None else seed
    folder.save_info(
        EvalInfo(
            id=folder.id,
            ts=datetime.now().astimezone().isoformat(timespec="seconds"),
            skill=plan.skill,
            split=plan.split,
            tasks=list(plan.tasks),
            against=list(AGAINST),
            seed=used_seed,
        )
    )
    runs: dict[str, dict[Condition, str]] = {}
    outputs: dict[tuple[str, Condition], str] = {}
    for planned in plan.runs:
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

    keys: dict[str, PairKey] = {}
    pairs: list[Pair] = []
    for number, key in enumerate(_arrange(used_seed, plan.tasks, AGAINST), start=1):
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
    folder.save_key(EvalKey(eval=folder.id, runs=runs, pairs=keys))
    folder.save_pairs(pairs)
    return BuiltPairs(
        eval=folder.id,
        skill=plan.skill,
        split=plan.split,
        tasks=plan.tasks,
        pairs=len(pairs),
        seed=used_seed,
    )


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
