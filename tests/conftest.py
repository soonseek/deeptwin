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
