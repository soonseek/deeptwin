from __future__ import annotations

import shutil
from pathlib import Path

import pytest

MINIMAL = Path(__file__).parent / "fixtures" / "minimal"


@pytest.fixture
def minimal_copy(tmp_path: Path) -> Path:
    """`tests/fixtures/minimal`의 복사본. 테스트는 원본 fixture를 고치지 않는다."""
    dest = tmp_path / "minimal"
    shutil.copytree(MINIMAL, dest)
    return dest


@pytest.fixture
def in_minimal(minimal_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """fixture 복사본으로 옮겨 간 상태. CLI는 지금 폴더를 프로젝트 루트로 본다."""
    monkeypatch.chdir(minimal_copy)
    return minimal_copy


COMPOSE_RULES = Path(__file__).parent / "fixtures" / "compose-rules"


@pytest.fixture
def rules_copy(tmp_path: Path) -> Path:
    """`tests/fixtures/compose-rules`의 복사본. 조립 규칙을 모두 거치는 가상 인물의 데이터다."""
    dest = tmp_path / "compose-rules"
    shutil.copytree(COMPOSE_RULES, dest)
    return dest


@pytest.fixture
def in_rules(rules_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`compose-rules` 복사본으로 옮겨 간 상태."""
    monkeypatch.chdir(rules_copy)
    return rules_copy


EXAMPLE = Path(__file__).parent.parent / "examples" / "inquiry-reply"
"""저장소의 예제 폴더. 테스트는 복사본에서만 돌고 이 폴더를 고치지 않는다."""


EXAMPLE_LEFT_OUT = ("runs", "eval", ".lock", ".DS_Store", "Thumbs.db", "__pycache__")
"""예제를 복사할 때 옮기지 않는 이름. git에 오르지 않는 것들이다: 예제를 저장소 안에서 돌려 생긴
실행 폴더, 평가 폴더, 잠금 파일, 운영체제와 Python이 남기는 파일."""


def copy_example(dest: Path, source: Path = EXAMPLE) -> Path:
    """예제 폴더 `source`를 `dest`에 복사한다. `EXAMPLE_LEFT_OUT`의 이름은 옮기지 않는다."""
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*EXAMPLE_LEFT_OUT))
    return dest


@pytest.fixture
def example_copy(tmp_path: Path) -> Path:
    """`examples/inquiry-reply`의 복사본. 가상의 강사 서도윤의 문의 답변 예제다."""
    return copy_example(tmp_path / "inquiry-reply")


@pytest.fixture
def in_example(example_copy: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """예제 복사본으로 옮겨 간 상태."""
    monkeypatch.chdir(example_copy)
    return example_copy
