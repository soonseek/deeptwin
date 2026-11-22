"""패키지의 버전과 커밋: 보고서가 어느 코드로 쟀는지 적을 때 읽는다.

- 버전은 설치된 패키지의 메타데이터다(`package_version`).
- 커밋은 빌드한 패키지면 빌드 훅이 넣은 값(`deeptwin._commit.COMMIT`)이고, 소스에서 돌면 git의
  `HEAD`다(`package_commit`). 둘 다 없으면 알 수 없음(`None`)이다. 작업 트리가 더러워도 `HEAD`
  그대로이고, 커밋하지 않은 변경이 있는지는 적지 않는다.

표준 라이브러리와 `deeptwin._commit`만 import한다.
"""

from __future__ import annotations

import re
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import deeptwin._commit as _commit

__all__ = [
    "GIT",
    "git_commit",
    "package_commit",
    "package_version",
]

GIT = "git"
"""커밋을 읽을 때 부르는 git 실행 파일."""

_PACKAGE_DIR = Path(__file__).resolve().parent
"""이 패키지의 폴더. 소스에서 돌면 저장소의 `src/deeptwin`이다."""
_HASH = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
"""커밋 해시의 모양: SHA-1(40자)이나 SHA-256(64자)의 16진 글."""
_GIT_TIMEOUT = 5.0


def package_version() -> str:
    """설치된 `deeptwin`의 버전. 설치되지 않았으면 `"0+unknown"`이다."""
    try:
        return version("deeptwin")
    except PackageNotFoundError:
        return "0+unknown"


def package_commit() -> str | None:
    """이 패키지의 커밋 해시. 부를 때마다 이 순서로 본다.

    1. 빌드 훅이 넣은 `deeptwin._commit.COMMIT`이 글이면 그 값이다. git을 부르지 않는다.
    2. 아니면 `git_commit(이 패키지 폴더)`다. 저장소 밖이면 `None`이다.
    """
    if isinstance(_commit.COMMIT, str):
        return _commit.COMMIT
    return git_commit(_PACKAGE_DIR)


def git_commit(package_dir: Path) -> str | None:
    """`package_dir`가 git 저장소의 `src/deeptwin`이면 그 저장소의 `HEAD` 해시다.

    `GIT -C <package_dir> rev-parse --show-toplevel HEAD`를 부른다. `<최상위>/src/deeptwin`이
    `package_dir`와 같은 폴더이고 해시가 16진 40자나 64자일 때만 그 해시다. 그 밖에는 모두
    `None`이다(git이 없거나 실패함, 저장소가 아님, 커밋이 없음, 출력의 모양이 틀림). 그래서 다른
    git 저장소 안의 가상 환경에 설치한 패키지는 그 저장소의 해시를 내지 않는다.
    """
    try:
        done = subprocess.run(
            [GIT, "-C", str(package_dir), "rev-parse", "--show-toplevel", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    lines = done.stdout.splitlines()
    if done.returncode != 0 or len(lines) != 2:
        return None
    top, head = lines
    try:
        same = (Path(top) / "src" / "deeptwin").samefile(package_dir)
    except (OSError, ValueError):
        return None
    if not same or not _HASH.fullmatch(head):
        return None
    return head
