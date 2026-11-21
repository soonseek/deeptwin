"""`.deeptwin/` 폴더 핸들.

`DeepTwin`은 학습 가능한 상태를 들고 있지 않다. 부를 때마다 파일에서 읽는다.
폴더를 만드는 것은 `DeepTwin.init`뿐이고, `DeepTwin.open`은 폴더가 없으면 오류를 낸다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from deeptwin.errors import NotInitializedError, SkillNotFoundError, TaskNotFoundError
from deeptwin.models import Principle, Skill, Task
from deeptwin.store.files import append_jsonl, read_yaml, write_text

DATA_DIR = ".deeptwin"
"""개인 데이터 폴더 이름. 프로젝트 루트에 둔다."""

LAYOUT: tuple[str, ...] = (
    "layers/examples",
    "layers/cards",
    "candidates",
    "tasks/train",
    "tasks/sealed",
    "tasks/spare",
    "runs",
)
"""`deeptwin init`이 만드는 폴더(설계서 8.3). `.deeptwin/` 기준 경로다."""

GITIGNORE_LINE = ".deeptwin/"
_GITIGNORE_SAME = frozenset({".deeptwin/", ".deeptwin", "/.deeptwin/", "/.deeptwin"})

_TASK_SPLITS = ("train", "spare")
"""`task(id)`가 찾아보는 분할. 봉인 과제는 이 길로 읽지 않는다."""

_RUN_DIR = re.compile(r"run-(\d+)")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class InitResult:
    deeptwin: DeepTwin
    created: tuple[str, ...]
    """새로 만든 폴더. `.deeptwin/` 기준 POSIX 경로."""
    gitignore: Literal["added", "present"]
    """`.gitignore`에 `.deeptwin/` 줄을 더했으면 `added`, 이미 있었으면 `present`."""


class DeepTwin:
    """프로젝트 루트(`root`)와 그 아래 `.deeptwin/`(`path`)의 핸들."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / DATA_DIR

    @classmethod
    def init(cls, root: Path) -> InitResult:
        """`.deeptwin/`의 폴더를 만들고 `.gitignore`에 `.deeptwin/`을 더한다.

        이미 있는 폴더와 파일은 건드리지 않는다. 여러 번 불러도 결과가 같다.
        """
        deeptwin = cls(root)
        created: list[str] = []
        for rel in LAYOUT:
            folder = deeptwin.path / rel
            if not folder.is_dir():
                folder.mkdir(parents=True, exist_ok=True)
                created.append(rel)
        gitignore = _ensure_gitignore(root / ".gitignore")
        return InitResult(deeptwin=deeptwin, created=tuple(created), gitignore=gitignore)

    @classmethod
    def open(cls, root: Path) -> DeepTwin:
        deeptwin = cls(root)
        if not deeptwin.path.is_dir():
            raise NotInitializedError("먼저 deeptwin init을 실행하세요.")
        return deeptwin

    def principles(self) -> list[Principle]:
        """`layers/principles.yaml`의 원칙. 파일이 없으면 빈 목록이다."""
        path = self.path / "layers" / "principles.yaml"
        if not path.is_file():
            return []
        data = read_yaml(path) or []
        return [Principle.model_validate(item) for item in data]

    def task(self, task_id: str) -> Task:
        """학습(`train`)과 예비(`spare`) 과제에서 `task_id`를 찾는다."""
        if _SAFE_ID.fullmatch(task_id):
            for split in _TASK_SPLITS:
                path = self.path / "tasks" / split / f"{task_id}.yaml"
                if path.is_file():
                    task = Task.model_validate(read_yaml(path))
                    if task.id != task_id:
                        raise TaskNotFoundError(
                            f"과제 파일의 id가 찾은 과제 ID와 다릅니다: "
                            f"{DATA_DIR}/tasks/{split}/{task_id}.yaml의 id: {task.id}, "
                            f"찾은 과제 ID: {task_id}"
                        )
                    return task
        looked = ", ".join(f"{DATA_DIR}/tasks/{split}/{task_id}.yaml" for split in _TASK_SPLITS)
        raise TaskNotFoundError(f"과제를 찾지 못했습니다: {task_id}. 찾아본 곳: {looked}")

    def skill(self, skill_id: str) -> Skill:
        """프로젝트 루트의 `skills/<skill_id>/`에서 `skill.yaml`과 `SKILL.md`를 찾는다."""
        folder = self.root / "skills" / skill_id
        config, skill_md = folder / "skill.yaml", folder / "SKILL.md"
        if not (_SAFE_ID.fullmatch(skill_id) and config.is_file() and skill_md.is_file()):
            raise SkillNotFoundError(
                f"스킬을 찾지 못했습니다: {skill_id}. "
                f"찾아본 곳: skills/{skill_id}/skill.yaml, skills/{skill_id}/SKILL.md"
            )
        data = read_yaml(config) or {}
        skill = Skill.model_validate({**data, "skill_md": skill_md})
        if skill.id != skill_id:
            raise SkillNotFoundError(
                f"스킬 파일의 id가 찾은 스킬 ID와 다릅니다: "
                f"skills/{skill_id}/skill.yaml의 id: {skill.id}, 찾은 스킬 ID: {skill_id}"
            )
        return skill

    def run_dir(self, run_id: str) -> Path:
        return self.path / "runs" / run_id

    def new_run(self) -> str:
        """`runs/run-NNNN/`을 만들고 그 ID를 돌려준다. 번호는 지금 있는 최댓값 + 1이다."""
        runs = self.path / "runs"
        runs.mkdir(exist_ok=True)
        number = 1 + max(
            (
                int(m.group(1))
                for child in runs.iterdir()
                if child.is_dir() and (m := _RUN_DIR.fullmatch(child.name))
            ),
            default=0,
        )
        while True:
            run_id = f"run-{number:04d}"
            try:
                (runs / run_id).mkdir(exist_ok=False)
            except FileExistsError:
                number += 1
                continue
            return run_id

    def append_ledger(self, entry: dict[str, Any]) -> None:
        """원장(`ledger.jsonl`)에 한 줄을 덧붙인다. 원장의 줄은 고치거나 지우지 않는다."""
        append_jsonl(self.path / "ledger.jsonl", entry)


def _ensure_gitignore(path: Path) -> Literal["added", "present"]:
    """`.gitignore`에 `.deeptwin/` 줄이 없으면 끝에 더한다. 다른 줄은 바이트 그대로 둔다."""
    text = path.read_bytes().decode("utf-8", "surrogateescape") if path.exists() else ""
    if any(line.strip() in _GITIGNORE_SAME for line in text.splitlines()):
        return "present"
    newline = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith(("\n", "\r")):
        text += newline
    write_text(path, text + GITIGNORE_LINE + newline, errors="surrogateescape")
    return "added"
