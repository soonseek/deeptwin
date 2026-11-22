"""원칙 검사: 스킬의 `checks.py`에 든 함수로 결과물이 원칙을 어겼는지 본다(설계서 8.5).

검사 함수는 `checks.py`의 모듈 수준 함수 `fn(output: str) -> bool`이다. `True`면 지켰고
`False`면 어겼다. 함수 이름이 원칙의 `check`다.

검사하는 원칙은 `compose`와 같은 범위다: `active`이고 `scope`가 비었거나 이 스킬을 담은 것을
`principles.yaml` 순서대로 본다. `check`가 없는 원칙은 건너뛴다. `ablate`와는 상관없다.

찾기(`prepare_checks`)와 돌리기(`PreparedChecks.run`)를 나눈다. 함수 이름이 틀렸으면 생성
비용을 내기 전에 알 수 있게 하려는 것이다. 모델을 부르지 않는다(`deeptwin.llm`을 import하지
않는다).

`checks.py`는 파일 경로로 불러 `sys.modules`에 넣지 않고 `sys.path`도 고치지 않는다. 그래서
여러 스킬의 `checks.py`에 같은 이름의 함수가 있어도 섞이지 않는다. `__pycache__`도 읽거나 쓰지
않아 스킬 폴더에 파일이 생기지 않고, 고친 `checks.py`는 다음에 부를 때 그대로 읽힌다.
"""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import re
import reprlib
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import CodeType, ModuleType

from deeptwin.compose import _in_scope
from deeptwin.errors import CheckFailedError, CheckNotFoundError
from deeptwin.models import Principle, Skill, Violation
from deeptwin.store.project import DeepTwin

__all__ = [
    "PreparedChecks",
    "check",
    "prepare_checks",
]

_MODULE_PREFIX = "deeptwin_checks_"
"""불러온 `checks.py` 모듈의 내부 이름 앞부분. 뒤에 스킬 ID를 붙여 스킬마다 다른 이름을 준다."""


@dataclass(frozen=True)
class FoundCheck:
    """찾아 둔 검사 함수 하나와 그 함수가 지키는지 보는 원칙."""

    principle: Principle
    name: str
    """함수 이름. 원칙의 `check`다."""
    function: Callable[[str], object]
    source: str
    """메시지에 쓰는 검사 파일 경로(`skills/<id>/checks.py`)."""


@dataclass(frozen=True)
class PreparedChecks:
    """`prepare_checks`가 찾아 둔 검사 함수들. `run`으로 결과물에 돌린다."""

    found: tuple[FoundCheck, ...] = ()
    """검사할 원칙과 함수. `principles.yaml` 순서다."""

    def run(self, output: str) -> list[Violation]:
        """함수마다 결과물을 주고, `False`를 돌려준 원칙을 `principles.yaml` 순서로 돌려준다.

        함수가 예외를 내거나 `bool`이 아닌 것을 돌려주면 `check_failed`다.
        """
        violations: list[Violation] = []
        for found in self.found:
            principle = found.principle
            where = f"원칙 {principle.id}의 검사 함수 {found.name}({found.source})"
            try:
                # 함수가 쓰는 글은 stderr로 보낸다. `--json`의 stdout은 JSON 객체 하나다
                with contextlib.redirect_stdout(sys.stderr):
                    kept = found.function(output)
            except (Exception, SystemExit) as error:
                raise CheckFailedError(
                    f"{where}에서 오류가 났습니다: {_error_text(error)}"
                ) from error
            if not isinstance(kept, bool):
                raise CheckFailedError(
                    f"{where}의 반환값이 bool이 아닙니다: {reprlib.repr(kept)}. "
                    "지켰으면 True, 어겼으면 False를 돌려주세요."
                )
            if not kept:
                violations.append(
                    Violation(principle=principle.id, rule=principle.rule, check=found.name)
                )
        return violations


def check(skill: Skill, output: str, deeptwin: DeepTwin) -> list[Violation]:
    """결과물이 어긴 원칙을 돌려준다(설계서 8.5). 어긴 원칙이 없으면 빈 목록이다.

    `prepare_checks(skill, deeptwin).run(output)`과 같다. 오류도 그 둘이 내는 것과 같다.
    """
    return prepare_checks(skill, deeptwin).run(output)


def prepare_checks(skill: Skill, deeptwin: DeepTwin) -> PreparedChecks:
    """이 스킬에 걸리는 원칙 가운데 `check`가 있는 것마다 `checks.py`에서 함수를 찾아 둔다.

    그런 원칙이 없으면 `checks.py`를 읽지 않는다. `Skill.checks`는 스킬 폴더(`skill.yaml`이 든
    폴더) 기준 상대 경로다.

    - `check_not_found`: 스킬에 `checks`가 없다, 검사 파일이 없거나 스킬 폴더 밖이다, 그 파일에
      함수가 없거나 부를 수 없다.
    - `check_failed`: 검사 파일을 불러오다 예외가 났다(문법 오류 등).
    """
    checked = [p for p in _in_scope(skill, deeptwin.principles()) if p.check is not None]
    if not checked:
        return PreparedChecks()
    folder = skill.skill_md.parent
    shown_folder = _display(folder, deeptwin.root)
    if skill.checks is None:
        raise CheckNotFoundError(
            f"스킬 {skill.id}의 skill.yaml에 checks가 없는데, 검사 함수를 적은 원칙이 있습니다: "
            f"{_named(checked)}. {shown_folder}/skill.yaml에 checks: checks.py를 적고 "
            "그 파일에 함수를 두거나, 원칙의 check를 null로 바꾸세요."
        )
    source = f"{shown_folder}/{skill.checks}"
    path = _checks_path(skill, folder, shown_folder)
    if not path.is_file():
        raise CheckNotFoundError(
            f"검사 파일이 없습니다: {source}. 검사 함수를 적은 원칙: {_named(checked)}"
        )
    module = _load(path, skill, source)
    found: list[FoundCheck] = []
    problems: list[str] = []
    for principle in checked:
        name = principle.check or ""  # checked에는 check가 있는 원칙만 있다
        function = vars(module).get(name)
        if function is None:
            problems.append(f"{source}에 원칙 {principle.id}의 검사 함수가 없습니다: {name}")
        elif not callable(function):
            problems.append(
                f"{source}에 있는 원칙 {principle.id}의 검사 함수를 부를 수 없습니다: "
                f"{name}({type(function).__name__}). "
                f"모듈 수준에 def {name}(output: str) -> bool 함수를 두세요."
            )
        else:
            found.append(
                FoundCheck(principle=principle, name=name, function=function, source=source)
            )
    if problems:
        raise CheckNotFoundError("\n".join(problems))
    return PreparedChecks(found=tuple(found))


def _checks_path(skill: Skill, folder: Path, shown_folder: str) -> Path:
    """`Skill.checks`를 스킬 폴더 기준으로 푼 경로. 폴더 밖을 가리키면 `check_not_found`다.

    절대 경로와, `..`이나 심볼릭 링크로 폴더 밖에 닿는 경로가 폴더 밖이다.
    """
    relative = Path(skill.checks or "")
    path = (folder / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(folder.resolve()):
        raise CheckNotFoundError(
            f"스킬 {skill.id}의 checks가 스킬 폴더 밖을 가리킵니다: {skill.checks}. "
            f"{shown_folder}/ 안의 상대 경로(예: checks.py)를 적으세요."
        )
    return path


class _SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    """늘 원본 글에서 컴파일하는 로더. `__pycache__`를 읽지도 쓰지도 않는다."""

    def get_code(self, fullname: str) -> CodeType:
        # deeptwin의 `from __future__` 설정이 사용자 코드에 옮지 않게 한다
        return compile(self.get_data(self.path), self.path, "exec", dont_inherit=True)


def _load(path: Path, skill: Skill, source: str) -> ModuleType:
    """`checks.py`를 새 모듈 객체로 불러온다. `sys.modules`와 `sys.path`는 건드리지 않는다."""
    name = _MODULE_PREFIX + re.sub(r"\W", "_", skill.id)
    loader = _SourceOnlyLoader(name, str(path))
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    if spec is None:  # pragma: no cover - 로더를 주면 None이 아니다
        raise CheckFailedError(f"검사 파일을 불러오지 못했습니다: {source}")
    module = importlib.util.module_from_spec(spec)
    try:
        # 불러오며 쓰는 글은 stderr로 보낸다. `--json`의 stdout은 JSON 객체 하나다
        with contextlib.redirect_stdout(sys.stderr):
            loader.exec_module(module)
    except (Exception, SystemExit) as error:
        raise CheckFailedError(
            f"검사 파일을 불러오다 오류가 났습니다: {source}. {_error_text(error)}"
        ) from error
    return module


def _named(principles: Sequence[Principle]) -> str:
    """`prin-01(no_inflated_numbers), prin-02(...)` 꼴."""
    return ", ".join(f"{p.id}({p.check})" for p in principles)


def _error_text(error: BaseException) -> str:
    text = str(error)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def _display(path: Path, root: Path) -> str:
    """메시지에 쓰는 경로: 프로젝트 루트 기준 POSIX 경로. 루트 밖이면 받은 경로 그대로다."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
