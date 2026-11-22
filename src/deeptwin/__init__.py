"""deeptwin: 개인의 판단 기준을 층별 파일로 쌓고, 모델 없이 조립해 스킬의 유동 영역에 넣는다.

공개 API만 내보낸다.
"""

from deeptwin.checks import check
from deeptwin.compose import compose, fill_fluid
from deeptwin.errors import DeeptwinError
from deeptwin.importing import import_folder
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
    Violation,
)
from deeptwin.provenance import package_version
from deeptwin.runs import record_run
from deeptwin.status import project_status
from deeptwin.store.project import DeepTwin

__version__ = package_version()
"""설치된 패키지의 버전. 설치하지 않고 소스에서 바로 쓰면 `"0+unknown"`이다."""

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
    "Violation",
    "__version__",
    "check",
    "compose",
    "fill_fluid",
    "import_folder",
    "project_status",
    "record_run",
]
