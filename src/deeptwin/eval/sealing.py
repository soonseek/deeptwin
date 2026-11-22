"""봉인 묶음 열기. 봉인 토큰(`SealedToken`)을 만드는 곳은 이 모듈뿐이다.

- `open_sealed`: 봉인 평가 하나의 묶음을 연다. 그 평가에서 처음 부를 때만 원장에 `seal_open` 줄을
  남기고, 토큰을 돌려준다. 모듈 밖으로 토큰을 내주는 함수는 이것 하나다.
- `read_sealed`: 생성을 준비할 때 이 스킬의 봉인 과제를 읽는다. 토큰을 돌려주지 않고 원장에도 쓰지
  않는다. 공개 이름(`__all__`)이 아니다.

봉인 묶음은 평가 하나가 여는 봉인 과제들이다. 생성 전에 알 수 있는 실패(맥락, 원장, 검사 함수,
공급자)는 `read_sealed`로 읽은 과제로 모두 본 뒤에 `open_sealed`를 부르므로, 그런 실패로는 묶음을
쓴 기록이 생기지 않는다. 파일에는 저장 계층(`store.evals`, `DeepTwin`)으로만 닿는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptwin.models import EvalInfo, Task
from deeptwin.store.evals import open_eval, seal_open_line
from deeptwin.store.guard import SealedToken
from deeptwin.store.project import DeepTwin

__all__ = [
    "open_sealed",
]


@dataclass(frozen=True)
class SealedOpening:
    """`open_sealed`의 결과."""

    eval: EvalInfo
    """평가 정보. `seal_open`과 `reused`가 원장의 줄과 맞게 적혀 있다."""
    line: str
    """원장의 `seal_open` 줄 ID(`seal-NNNN`)."""
    reused: tuple[str, ...]
    """다른 평가에서 이미 연 봉인 과제의 ID. 원장에서 계산한 값이고 순서는 평가의 과제 순서다."""
    token: SealedToken
    """봉인 과제를 읽어도 된다는 표. 저장 계층(`DeepTwin.task`, `changed_references`)에 넘긴다."""


def open_sealed(deeptwin: DeepTwin, eval_id: str) -> SealedOpening:
    """봉인 평가 `eval_id`의 묶음을 열고 토큰을 준다.

    - `eval.json`을 읽는다. 평가가 없으면 `eval_not_found`, 분할이 `sealed`가 아니면 `ValueError`다.
    - 원장에 이 평가의 `seal_open` 줄이 없으면(처음 부를 때) 한 줄을 덧붙이고, 있으면 쓰지 않고 그
      줄의 ID와 재사용을 돌려준다(`store.evals.seal_open_line`). 같은 평가의 이어 가기, 판정,
      보고서에서 다시 불러도 원장은 그대로다.
    - `eval.json`의 `seal_open`이 그 줄 ID와 다를 때만 `seal_open`과 `reused`를 적는다.
    """
    folder = open_eval(deeptwin, eval_id)
    with deeptwin.lock():
        info = folder.info()
        if info.split != "sealed":
            raise ValueError(
                f"평가 {folder.id}은 {info.split} 분할의 평가입니다. "
                "봉인 묶음은 봉인(sealed) 평가만 엽니다."
            )
        line = seal_open_line(deeptwin, info)
        if info.seal_open != line.id:
            info = info.model_copy(update={"seal_open": line.id, "reused": list(line.reused)})
            folder.save_info(info)
    return SealedOpening(eval=info, line=line.id, reused=line.reused, token=SealedToken())


def read_sealed(deeptwin: DeepTwin, skill_id: str) -> list[Task]:
    """이 스킬의 봉인 과제. 파일 이름순이다. 토큰을 돌려주지 않고 원장에도 쓰지 않는다.

    생성을 준비할 때(`prepare_pairs`, `prepare_resume`)만 쓴다. 생성에는 기준이 필요 없으므로
    돌려주는 과제의 `reference`는 `None`이다. 준비 결과(`PairPlan`)로 기준이 새어 나가지 않는다.
    기준 검사는 저장 계층(`changed_references`, `verify_sealed`)이 파일을 직접 읽어 한다.
    오류는 `DeepTwin.tasks`와 같다(`invalid_file` 등, 받은 값은 쓰지 않는다).
    """
    return [
        task.model_copy(update={"reference": None})
        for task in deeptwin.tasks("sealed", token=SealedToken())
        if task.skill == skill_id
    ]
