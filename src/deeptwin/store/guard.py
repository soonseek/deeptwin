"""봉인 보호(설계서 9.5): 봉인 과제는 함수마다가 아니라 저장 계층에서 막는다.

- `DeepTwin.tasks("sealed")`와 봉인 과제의 `DeepTwin.task(id)`는 `SealedToken` 없이 부르면
  `sealed_access`다. 토큰은 평가 모듈의 `open_sealed`가 만든다(epic-blind-eval). 공개 API로는
  내보내지 않는다.
- 봉인 과제의 기준(`reference`)은 등록할 때 `reference_hash`로 원장의 `task` 줄에 남기고,
  `deeptwin verify`가 같은 함수로 다시 계산해 견준다.

오류 메시지와 검사 결과에는 봉인 과제의 `input`이나 `reference` 내용을 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from deeptwin.errors import SealedAccessError, SealedChangedError
from deeptwin.models import Reference

__all__ = [
    "SealedCheck",
    "SealedProblem",
    "SealedToken",
    "problem_lines",
    "reference_hash",
    "require_token",
    "sealed_changed",
]

SEALED_PURPOSE = "봉인 과제는 평가에서만 씁니다."
"""봉인 과제를 막을 때 메시지 끝에 붙이는 문장."""


@dataclass(frozen=True)
class SealedToken:
    """봉인 과제를 읽어도 된다는 표. 저장 계층은 이 형인지만 본다."""


def require_token(token: SealedToken | None, what: str) -> None:
    """`token`이 `SealedToken`이 아니면 `sealed_access`다. `what`은 메시지에서 막은 대상이다."""
    if not isinstance(token, SealedToken):
        raise SealedAccessError(f"{what} 봉인 과제라 읽을 수 없습니다. {SEALED_PURPOSE}")


def reference_hash(reference: Reference) -> str:
    """기준의 해시: `"sha256:" + SHA-256(정렬된 JSON)`.

    정렬된 JSON은 `model_dump(mode="json", by_alias=True)`를 `sort_keys=True`,
    `ensure_ascii=False`, `separators=(",", ":")`로 쓴 것이고 UTF-8 바이트로 해시한다.
    기본값(`grade: usual` 등)도 들어가므로 파일에 기본값을 적든 말든 해시가 같다.
    """
    text = json.dumps(
        reference.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SealedProblem:
    """봉인 검사의 문제 하나."""

    path: str
    """프로젝트 루트 기준 POSIX 경로(예: `.deeptwin/tasks/sealed/task-0101.yaml`)."""
    reason: str
    """한국어 설명. 과제의 내용은 쓰지 않는다."""


@dataclass(frozen=True)
class SealedCheck:
    """봉인 검사의 결과. 문제가 있어도 예외를 내지 않고 여기에 모은다."""

    checked: int
    """원장에 봉인 과제로 등록된 과제의 수(ID마다 하나)."""
    problems: tuple[SealedProblem, ...]


def problem_lines(problems: tuple[SealedProblem, ...]) -> list[str]:
    """문제마다 한 줄씩 `<경로>: <이유>`."""
    return [f"{p.path}: {p.reason}" for p in problems]


def sealed_changed(problems: tuple[SealedProblem, ...]) -> SealedChangedError:
    return SealedChangedError("\n".join(problem_lines(problems)))
