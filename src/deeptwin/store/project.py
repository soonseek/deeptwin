"""`.deeptwin/` 폴더 핸들.

`DeepTwin`은 학습 가능한 상태를 들고 있지 않다. 부를 때마다 파일에서 읽는다.
폴더를 만드는 것은 `DeepTwin.init`뿐이고, `DeepTwin.open`은 폴더가 없으면 오류를 낸다.

읽기는 형식이 틀린 파일을 `invalid_file`로 거부한다. 쓰기는 `.deeptwin/.lock`을 잡고
원자적으로 한다. 목록은 정해진 순서로 돌려준다: 폴더의 파일은 파일 이름순,
`priorities.yaml`과 `principles.yaml`은 파일에 적힌 순서다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

from filelock import FileLock, Timeout

from deeptwin.errors import (
    NotInitializedError,
    SkillNotFoundError,
    StoreLockedError,
    TaskNotFoundError,
)
from deeptwin.models import Candidate, Card, Example, Principle, Priority, Skill, Task
from deeptwin.store.files import (
    Problem,
    append_jsonl,
    invalid_file,
    read_model,
    read_models,
    write_model,
    write_models,
    write_text,
)

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

EXAMPLES_DIR = "layers/examples"
CARDS_DIR = "layers/cards"
CANDIDATES_DIR = "candidates"
PRIORITIES_FILE = "layers/priorities.yaml"
PRINCIPLES_FILE = "layers/principles.yaml"
LEDGER_FILE = "ledger.jsonl"
LOCK_FILE = ".lock"

LOCK_TIMEOUT = 30.0
"""쓰기 잠금을 기다리는 최대 초. 넘으면 `store_locked`다."""

GITIGNORE_LINE = ".deeptwin/"
_GITIGNORE_SAME = frozenset({".deeptwin/", ".deeptwin", "/.deeptwin/", "/.deeptwin"})

_TASK_SPLITS = ("train", "spare")
"""`task(id)`가 찾아보는 분할. 봉인 과제는 이 길로 읽지 않는다."""

_RUN_DIR = re.compile(r"run-(\d+)")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

_FolderItem = TypeVar("_FolderItem", Example, Card, Candidate)
_ListItem = TypeVar("_ListItem", Priority, Principle)


@dataclass(frozen=True)
class InitResult:
    deeptwin: DeepTwin
    created: tuple[str, ...]
    """새로 만든 폴더. `.deeptwin/` 기준 POSIX 경로."""
    gitignore: Literal["added", "present"]
    """`.gitignore`에 `.deeptwin/` 줄을 더했으면 `added`, 이미 있었으면 `present`."""


class DeepTwin:
    """프로젝트 루트(`root`)와 그 아래 `.deeptwin/`(`path`)의 핸들."""

    lock_timeout: float = LOCK_TIMEOUT
    """쓰기 잠금을 기다리는 최대 초. 핸들마다 바꿀 수 있다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / DATA_DIR
        self._lock = FileLock(self.path / LOCK_FILE)

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

    # 잠금

    @contextmanager
    def lock(self) -> Iterator[None]:
        """`.deeptwin/.lock`을 잡는다. 같은 핸들에서는 잡은 채로 다시 잡을 수 있다.

        `lock_timeout`초 안에 잡지 못하면 `store_locked`다. 잠금을 쥔 프로세스가 죽으면
        운영체제가 잠금을 푼다.
        """
        if not self.path.is_dir():
            raise NotInitializedError("먼저 deeptwin init을 실행하세요.")
        try:
            self._lock.acquire(timeout=self.lock_timeout)
        except Timeout:
            raise StoreLockedError(
                f"다른 쓰기가 {DATA_DIR}/{LOCK_FILE} 잠금을 쥐고 있어 "
                f"{self.lock_timeout:g}초 동안 기다렸지만 잡지 못했습니다. "
                "그 작업이 끝난 뒤 다시 실행하세요."
            ) from None
        try:
            yield
        finally:
            self._lock.release()

    # 읽기

    def examples(self) -> list[Example]:
        """`layers/examples/`의 예시. 파일 이름순이다."""
        return self._read_folder(EXAMPLES_DIR, Example)

    def cards(self) -> list[Card]:
        """`layers/cards/`의 판단 카드. 파일 이름순이다."""
        return self._read_folder(CARDS_DIR, Card)

    def priorities(self) -> list[Priority]:
        """`layers/priorities.yaml`의 우선순위. 파일에 적힌 순서(위가 먼저)다.

        파일이 없으면 빈 목록이다.
        """
        return self._read_list(PRIORITIES_FILE, Priority)

    def principles(self) -> list[Principle]:
        """`layers/principles.yaml`의 원칙. 파일에 적힌 순서다. 파일이 없으면 빈 목록이다."""
        return self._read_list(PRINCIPLES_FILE, Principle)

    def candidates(self) -> list[Candidate]:
        """`candidates/`의 후보. 파일 이름순이다."""
        return self._read_folder(CANDIDATES_DIR, Candidate)

    def task(self, task_id: str) -> Task:
        """학습(`train`)과 예비(`spare`) 과제에서 `task_id`를 찾는다.

        파일의 `split`이 과제가 든 폴더와 다르면 `invalid_file`이다.
        """
        if _SAFE_ID.fullmatch(task_id):
            for split in _TASK_SPLITS:
                path = self.path / "tasks" / split / f"{task_id}.yaml"
                if path.is_file():
                    task = read_model(path, Task, root=self.root)
                    if task.id != task_id:
                        raise TaskNotFoundError(
                            f"과제 파일의 id가 찾은 과제 ID와 다릅니다: "
                            f"{DATA_DIR}/tasks/{split}/{task_id}.yaml의 id: {task.id}, "
                            f"찾은 과제 ID: {task_id}"
                        )
                    if task.split != split:
                        raise invalid_file(
                            path,
                            self.root,
                            [
                                Problem(
                                    ("split",),
                                    f"과제가 든 폴더(tasks/{split})와 다릅니다"
                                    f"(받은 값: {task.split!r})",
                                    field="split",
                                )
                            ],
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
        skill = read_model(config, Skill, root=self.root, update={"skill_md": skill_md})
        if skill.id != skill_id:
            raise SkillNotFoundError(
                f"스킬 파일의 id가 찾은 스킬 ID와 다릅니다: "
                f"skills/{skill_id}/skill.yaml의 id: {skill.id}, 찾은 스킬 ID: {skill_id}"
            )
        return skill

    # 쓰기: 모두 잠금 안에서 원자적으로 쓴다. 쓴 파일의 경로를 돌려준다

    def write_example(self, example: Example) -> Path:
        """`layers/examples/<id>.yaml`에 쓴다."""
        return self._write_one(self.path / EXAMPLES_DIR, example)

    def write_card(self, card: Card) -> Path:
        """`layers/cards/<id>.yaml`에 쓴다."""
        return self._write_one(self.path / CARDS_DIR, card)

    def write_candidate(self, candidate: Candidate) -> Path:
        """`candidates/<id>.yaml`에 쓴다."""
        return self._write_one(self.path / CANDIDATES_DIR, candidate)

    def write_task(self, task: Task) -> Path:
        """`tasks/<split>/<id>.yaml`에 쓴다."""
        return self._write_one(self.path / "tasks" / task.split, task)

    def write_priorities(self, priorities: Sequence[Priority]) -> Path:
        """`layers/priorities.yaml`을 받은 순서(위가 먼저)대로 통째로 다시 쓴다."""
        return self._write_list(self.path / PRIORITIES_FILE, priorities)

    def write_principles(self, principles: Sequence[Principle]) -> Path:
        """`layers/principles.yaml`을 받은 순서대로 통째로 다시 쓴다."""
        return self._write_list(self.path / PRINCIPLES_FILE, principles)

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
        """원장(`ledger.jsonl`)에 잠금 안에서 한 줄을 덧붙인다.

        원장의 줄은 고치거나 지우지 않는다.
        """
        with self.lock():
            append_jsonl(self.path / LEDGER_FILE, entry)

    # 내부

    def _read_list(self, rel: str, model: type[_ListItem]) -> list[_ListItem]:
        path = self.path / rel
        if not path.is_file():
            return []
        return read_models(path, model, root=self.root)

    def _read_folder(self, rel: str, model: type[_FolderItem]) -> list[_FolderItem]:
        """폴더의 `.yaml` 파일을 파일 이름순으로 읽는다. 점으로 시작하는 파일은 건너뛴다.

        확장자는 대소문자까지 `.yaml`이어야 한다. 운영체제마다 읽는 파일이 같게 하려는 것이다.
        파일 이름(확장자 뺀 것)과 `id`가 다르면 `invalid_file`이다.
        """
        folder = self.path / rel
        if not folder.is_dir():
            return []
        paths = sorted(
            (
                p
                for p in folder.iterdir()
                if p.suffix == ".yaml" and not p.name.startswith(".") and p.is_file()
            ),
            key=lambda p: p.name,
        )
        items: list[_FolderItem] = []
        for path in paths:
            item = read_model(path, model, root=self.root)
            if item.id != path.stem:
                raise invalid_file(
                    path,
                    self.root,
                    [
                        Problem(
                            ("id",),
                            f"파일 이름과 다릅니다(파일 이름: {path.stem}, 받은 값: {item.id!r})",
                            field="id",
                        )
                    ],
                )
            items.append(item)
        return items

    def _write_one(self, folder: Path, item: Example | Card | Candidate | Task) -> Path:
        _check_id(item.id)
        path = folder / f"{item.id}.yaml"
        with self.lock():
            folder.mkdir(parents=True, exist_ok=True)
            write_model(path, item)
        return path

    def _write_list(self, path: Path, items: Sequence[_ListItem]) -> Path:
        for item in items:
            _check_id(item.id)
        with self.lock():
            path.parent.mkdir(parents=True, exist_ok=True)
            write_models(path, items)
        return path


def _check_id(item_id: str) -> None:
    """파일 이름과 원장에 쓰는 ID인지 본다. 아니면 쓰지 않고 `ValueError`를 낸다."""
    if not _SAFE_ID.fullmatch(item_id):
        raise ValueError(
            f"쓸 수 없는 ID입니다: {item_id!r}. 영문자, 숫자, '.', '_', '-'만 쓰고 "
            "영문자나 숫자로 시작하세요."
        )


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
