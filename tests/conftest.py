from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import deeptwin._commit

# GitHub Actions(GITHUB_ACTIONS)에서는 typer가 도움말과 인자 오류를 색 있는 터미널 글로 내서
# 옵션 이름이 이스케이프 코드로 갈라진다. typer를 import하기 전에 꺼 둔다
os.environ.setdefault("_TYPER_FORCE_DISABLE_TERMINAL", "1")

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


REPO = Path(__file__).resolve().parent.parent
"""저장소(또는 sdist를 푼 폴더)의 최상위."""


def source_head() -> str | None:
    """이 패키지가 저장소의 `src/deeptwin`에서 돌면 그 저장소의 `git rev-parse HEAD`다.

    저장소 밖(예: sdist를 푼 폴더)이거나 git이 없으면 `None`이다.
    """
    package = Path(deeptwin._commit.__file__).parent
    source = REPO / "src" / "deeptwin"
    if shutil.which("git") is None or not (source.is_dir() and source.samefile(package)):
        return None
    found: list[str] = []
    for args in (("rev-parse", "--show-toplevel"), ("rev-parse", "HEAD")):
        done = subprocess.run(
            ["git", *args],
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if done.returncode != 0:
            return None
        found.append(done.stdout.strip())
    top, head = found
    return head if Path(top).samefile(REPO) else None


@pytest.fixture
def from_source(monkeypatch: pytest.MonkeyPatch) -> str | None:
    """빌드 훅이 넣은 커밋 없이 소스의 git에서 커밋을 읽게 한다. 기대하는 커밋을 돌려준다.

    sdist를 풀어 돌릴 때는 그 안의 `_commit.py`에 해시가 있으므로 값을 `None`으로 바꿔 둔다.
    """
    monkeypatch.setattr(deeptwin._commit, "COMMIT", None)
    return source_head()
