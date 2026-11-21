"""deeptwin: 개인의 판단 기준을 층별 파일로 쌓고, 모델 없이 조립해 스킬의 유동 영역에 넣는다.

공개 API만 내보낸다.
"""

from importlib.metadata import PackageNotFoundError, version

from deeptwin.compose import compose, fill_fluid
from deeptwin.errors import DeeptwinError
from deeptwin.llm import ClaudeCLIProvider, FakeProvider, Provider
from deeptwin.models import (
    Candidate,
    Card,
    Composed,
    Example,
    Principle,
    Priority,
    Reference,
    Run,
    Skill,
    Task,
)
from deeptwin.runs import record_run
from deeptwin.store.project import DeepTwin

try:
    __version__ = version("deeptwin")
except PackageNotFoundError:  # pragma: no cover - 설치하지 않고 소스에서 바로 쓸 때
    __version__ = "0+unknown"

__all__ = [
    "Candidate",
    "Card",
    "ClaudeCLIProvider",
    "Composed",
    "DeepTwin",
    "DeeptwinError",
    "Example",
    "FakeProvider",
    "Principle",
    "Priority",
    "Provider",
    "Reference",
    "Run",
    "Skill",
    "Task",
    "__version__",
    "compose",
    "fill_fluid",
    "record_run",
]
