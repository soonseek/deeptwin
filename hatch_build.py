"""hatchling 빌드 훅: sdist와 wheel 안의 `src/deeptwin/_commit.py`에 빌드한 커밋 해시를 넣는다.

- editable 설치(`uv sync`, `uv run`)는 건너뛴다. 소스에서 돌면 `deeptwin.provenance`가 git에서
  읽는다.
- 풀어 둔 sdist(최상위에 `PKG-INFO`가 있는 폴더)도 git을 부르지 않고 건너뛴다. 그 폴더를 git
  저장소로 만들어 꾸리는 배포판 도구가 있어도 sdist에 든 `_commit.py`를 그대로 쓴다.
- 빌드하는 폴더가 git 저장소의 최상위이고 `HEAD`가 있을 때만 넣는다. 아니면(git이 없음, 저장소가
  아님, 다른 저장소 안, 커밋이 없음) 아무것도 하지 않는다. sdist를 풀어 wheel을 만들 때가 여기에
  든다. 그때는 sdist에 이미 든 `_commit.py`가 그대로 쓰인다.
- 넣은 파일은 저장소 밖의 임시 폴더에 만들어 `force_include`로 결과물에만 넣는다. 저장소 안에는
  아무 파일도 쓰지 않고, 임시 폴더는 `finalize`가 지운다.

표준 라이브러리와 hatchling만 import한다. 출력은 쓰지 않는다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

COMMIT_FILE = "src/deeptwin/_commit.py"
"""커밋을 넣을 파일. 저장소 최상위 기준이다(wheel에서는 `deeptwin/_commit.py`가 된다)."""
DEFAULT_LINE = "COMMIT: str | None = None"
"""저장소의 `_commit.py`에 정확히 한 번 있어야 하는 줄. 이 줄의 값만 바꾼다."""

_HASH = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_GIT_TIMEOUT = 10.0


class CommitHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    _tmp: str | None = None

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version == "editable":
            return
        root = Path(self.root)
        if (root / "PKG-INFO").is_file():
            # 풀어 둔 sdist다. git 저장소 안이어도 sdist에 든 _commit.py를 그대로 쓴다
            return
        commit = _git_head(root)
        if commit is None:
            # sdist로 만드는 wheel은 sdist에 든 _commit.py를 쓴다
            return
        text = _with_commit(root, commit)
        self._tmp = tempfile.mkdtemp(prefix="deeptwin-commit-")
        made = Path(self._tmp) / "_commit.py"
        made.write_text(text, encoding="utf-8", newline="\n")
        build_data["force_include"][str(made)] = COMMIT_FILE

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None


def _git_head(root: Path) -> str | None:
    """`root`가 git 저장소의 최상위이면 그 `HEAD` 해시다. 아니면 `None`이다."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel", "HEAD"],
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
        same = Path(top).samefile(root)
    except (OSError, ValueError):
        return None
    if not same or not _HASH.fullmatch(head):
        return None
    return head


def _with_commit(root: Path, commit: str) -> str:
    """저장소의 `_commit.py` 글에서 `DEFAULT_LINE`만 값이 `commit`인 줄로 바꾼 글(줄바꿈은 LF).

    그 줄이 정확히 한 번 있지 않으면 `RuntimeError`로 빌드를 멈춘다. 저장소에 진짜 해시를
    커밋했을 때도 여기서 막힌다.
    """
    path = root / COMMIT_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    found = lines.count(DEFAULT_LINE)
    if found != 1:
        raise RuntimeError(
            f"{COMMIT_FILE}에 줄 '{DEFAULT_LINE}'이 정확히 한 번 있어야 커밋 해시를 넣습니다"
            f"(찾은 수: {found}). 저장소의 이 파일은 값을 None으로 둡니다."
        )
    made = [f'COMMIT: str | None = "{commit}"' if line == DEFAULT_LINE else line for line in lines]
    return "\n".join(made) + "\n"
