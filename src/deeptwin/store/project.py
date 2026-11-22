"""`.deeptwin/` 폴더 핸들.

`DeepTwin`은 학습 가능한 상태를 들고 있지 않다. 부를 때마다 파일에서 읽는다.
폴더를 만드는 것은 `DeepTwin.init`뿐이고, `DeepTwin.open`은 폴더가 없으면 오류를 낸다.

읽기는 형식이 틀린 파일을 `invalid_file`로 거부한다. 쓰기는 `.deeptwin/.lock`을 잡고
원자적으로 한다. 목록은 정해진 순서로 돌려준다: 폴더의 파일은 파일 이름순,
`priorities.yaml`과 `principles.yaml`은 파일에 적힌 순서다.

봉인 과제는 여기서 막는다(`store.guard`). `tasks("sealed")`와 봉인 과제의 `task(id)`는
`SealedToken` 없이 부르면 `sealed_access`다. 과제의 분할은 등록한 뒤 바꿀 수 없다.
과제 파일 수를 세는 `task_counts`는 파일 이름만 보므로 봉인 과제도 토큰 없이 센다.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypeVar, get_args

from filelock import FileLock, Timeout

from deeptwin.errors import (
    InvalidFileError,
    InvalidIdError,
    NotInitializedError,
    ReferenceRequiredError,
    SkillExistsError,
    SkillNotFoundError,
    StoreLockedError,
    TaskExistsError,
    TaskNotFoundError,
)
from deeptwin.models import (
    FLUID_CLOSE,
    FLUID_OPEN,
    Candidate,
    Card,
    Example,
    Principle,
    Priority,
    Skill,
    Split,
    Task,
    TaskEntry,
)
from deeptwin.store import ledger
from deeptwin.store.files import (
    Problem,
    dump_yaml,
    invalid_file,
    read_model,
    read_models,
    write_model,
    write_models,
    write_text,
)
from deeptwin.store.guard import (
    SealedCheck,
    SealedProblem,
    SealedToken,
    reference_hash,
    require_token,
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

SKILLS_DIR = "skills"
"""스킬 폴더들을 두는 곳. 프로젝트 루트 기준이다(`skills/<id>/`)."""
SKILL_CONFIG_FILE = "skill.yaml"
SKILL_MD_FILE = "SKILL.md"
CHECKS_FILE = "checks.py"
"""스킬 폴더의 세 파일: 설정, 고정 지침과 유동 영역 표시, 원칙의 검사 함수."""

EXAMPLE_ID_PREFIX = "ex-"
"""`add_examples`가 매기는 예시 ID의 앞부분. 뒤에 4자리 번호가 붙는다(`ex-0001`)."""

TASKS_DIR = "tasks"
SPLITS: tuple[Split, ...] = get_args(Split)
"""과제의 세 분할: 학습(`train`), 봉인(`sealed`), 예비(`spare`). 폴더 이름과 같다."""

_TASK_SPLITS: tuple[Split, ...] = ("sealed", "train", "spare")
"""`task(id)`가 찾아보는 순서. 봉인을 먼저 본다: 손으로 같은 ID를 다른 분할에도 두었어도
봉인 과제로 친다."""

_RUN_DIR = re.compile(r"run-(\d+)")
_EXAMPLE_NUMBER = re.compile(re.escape(EXAMPLE_ID_PREFIX) + r"([0-9]+)")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ID_RULE = "영문자, 숫자, '.', '_', '-'만 쓰고 영문자나 숫자로 시작하세요."

_FolderItem = TypeVar("_FolderItem", Example, Card, Candidate, Task)
_ListItem = TypeVar("_ListItem", Priority, Principle)


@dataclass(frozen=True)
class InitResult:
    deeptwin: DeepTwin
    created: tuple[str, ...]
    """새로 만든 폴더. `.deeptwin/` 기준 POSIX 경로."""
    gitignore: Literal["added", "present"]
    """`.gitignore`에 `.deeptwin/` 줄을 더했으면 `added`, 이미 있었으면 `present`."""


@dataclass(frozen=True)
class NewSkill:
    """`DeepTwin.new_skill`의 결과."""

    skill: Skill
    """만든 `skill.yaml`을 `DeepTwin.skill`로 다시 읽은 것."""
    files: tuple[Path, ...]
    """만든 파일: `skill.yaml`, `SKILL.md`, `checks.py` 순이다."""


@dataclass(frozen=True)
class AddedExample:
    """`DeepTwin.add_examples`가 받은 예시 하나의 결과."""

    example: Example | None
    """새 ID를 매겨 쓴 예시. 건너뛰었으면 `None`이다."""
    same_as: str | None = None
    """건너뛴 까닭이 된 예시의 ID. `text`가 같은, 이미 있던 예시나 이번에 앞서 쓴 예시다."""


@dataclass(frozen=True)
class AddedTask:
    """`DeepTwin.add_task`의 결과."""

    entry: TaskEntry
    """원장에 덧붙인 `task` 줄(`prev_hash`, `hash`를 뺀 것)."""
    path: Path
    """쓴 과제 파일(`tasks/<split>/<id>.yaml`)."""


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

    def task(self, task_id: str, *, token: SealedToken | None = None) -> Task:
        """세 분할(`sealed`, `train`, `spare` 순)에서 `task_id`를 찾는다.

        봉인 과제면 `token`이 없을 때 파일을 읽지 않고 `sealed_access`다.
        파일의 `split`이 과제가 든 폴더와 다르면 `invalid_file`이다.
        """
        if _SAFE_ID.fullmatch(task_id):
            for split in _TASK_SPLITS:
                path = self._task_path(split, task_id)
                if path.is_file():
                    if split == "sealed":
                        require_token(token, f"과제 {task_id}은")
                    task = read_model(path, Task, root=self.root)
                    if task.id != task_id:
                        raise TaskNotFoundError(
                            f"과제 파일의 id가 찾은 과제 ID와 다릅니다: "
                            f"{DATA_DIR}/{TASKS_DIR}/{split}/{task_id}.yaml의 id: {task.id}, "
                            f"찾은 과제 ID: {task_id}"
                        )
                    self._check_task_split(path, task, split)
                    return task
        looked = ", ".join(
            f"{DATA_DIR}/{TASKS_DIR}/{split}/{task_id}.yaml" for split in _TASK_SPLITS
        )
        raise TaskNotFoundError(f"과제를 찾지 못했습니다: {task_id}. 찾아본 곳: {looked}")

    def tasks(self, split: Split, *, token: SealedToken | None = None) -> list[Task]:
        """`tasks/<split>/`의 과제. 파일 이름순이다. 폴더가 없으면 빈 목록이다.

        `split`이 `sealed`면 `token`이 없을 때 파일을 읽지 않고 `sealed_access`다.
        파일 이름과 `id`가 다르거나 `split`이 폴더와 다르면 `invalid_file`이다.
        """
        if split not in SPLITS:
            names = ", ".join(SPLITS)
            raise ValueError(f"알 수 없는 분할입니다: {split!r}. 쓸 수 있는 값: {names}")
        if split == "sealed":
            require_token(token, f"{DATA_DIR}/{TASKS_DIR}/sealed/의 과제는")
        tasks = self._read_folder(f"{TASKS_DIR}/{split}", Task)
        for task in tasks:
            self._check_task_split(self._task_path(split, task.id), task, split)
        return tasks

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

    def task_counts(self) -> dict[Split, int]:
        """분할마다 `tasks/<split>/`의 과제 파일 수. 분할 순서는 `SPLITS`(train, sealed, spare)다.

        파일을 열지 않고 이름만 센다(`.yaml` 파일, 점으로 시작하는 파일은 뺀다). 그래서 봉인
        과제도 토큰 없이 세고, 형식이 틀린 파일도 하나로 센다. 폴더가 없으면 0이다.
        """
        counts: dict[Split, int] = {}
        for split in SPLITS:
            folder = self.path / TASKS_DIR / split
            counts[split] = sum(1 for _ in _yaml_files(folder)) if folder.is_dir() else 0
        return counts

    # 쓰기: 모두 잠금 안에서 원자적으로 쓴다. 쓴 파일의 경로를 돌려준다

    def write_example(self, example: Example) -> Path:
        """`layers/examples/<id>.yaml`에 쓴다."""
        return self._write_one(self.path / EXAMPLES_DIR, example)

    def add_examples(self, drafts: Sequence[Example]) -> list[AddedExample]:
        """예시 여러 건에 한 잠금 안에서 새 ID를 매겨 쓴다. 받은 순서대로 결과를 돌려준다.

        - ID는 `ex-NNNN`이다. 지금 있는 `ex-` 번호의 최댓값 + 1부터 받은 순서로 매긴다.
          받은 예시의 `id`는 쓰지 않는다(아무 값이나 두면 된다).
        - 같은 스킬에 `text`가 같은 예시가 이미 있거나, 이번에 앞서 받은 예시와 같으면 쓰지 않고
          건너뛴다. `text`는 앞뒤 공백을 떼고 견준다. `text`가 없는 예시(`pair`)는 견주지 않는다.
        - 쓰다가 실패하면 이번에 쓴 파일을 지우고 그 오류를 그대로 낸다.

        지금 있는 예시를 먼저 모두 읽으므로, 형식이 틀린 예시 파일이 있으면 아무것도 쓰지 않고
        `invalid_file`이다. 스킬이 있는지는 부르는 쪽이 먼저 본다.
        """
        folder = self.path / EXAMPLES_DIR
        with self.lock():
            existing = self.examples()
            known: dict[tuple[str, str], str] = {}
            for example in existing:
                if example.text is not None:
                    known.setdefault((example.skill, example.text.strip()), example.id)
            number = 1 + max(
                (int(m.group(1)) for e in existing if (m := _EXAMPLE_NUMBER.fullmatch(e.id))),
                default=0,
            )
            results: list[AddedExample] = []
            written: list[Path] = []
            try:
                for draft in drafts:
                    key = (draft.skill, draft.text.strip()) if draft.text is not None else None
                    if key is not None and key in known:
                        results.append(AddedExample(example=None, same_as=known[key]))
                        continue
                    # 읽지 않는 이름의 파일(예: 대소문자만 다른 확장자)도 덮어쓰지 않는다
                    while (folder / f"{EXAMPLE_ID_PREFIX}{number:04d}.yaml").exists():
                        number += 1
                    example = draft.model_copy(update={"id": f"{EXAMPLE_ID_PREFIX}{number:04d}"})
                    number += 1
                    written.append(self.write_example(example))
                    if key is not None:
                        known[key] = example.id
                    results.append(AddedExample(example=example))
            except BaseException:
                for path in written:
                    path.unlink(missing_ok=True)
                raise
        return results

    def new_skill(self, skill_id: str) -> NewSkill:
        """프로젝트 루트의 `skills/<skill_id>/`에 스킬 뼈대를 만든다.

        - `skill.yaml`: `schema: 1`, `id`, `version: 1`, 빈 `decision_points`와 `context_axes`,
          기본 `budget`, `example_policy: random_signature`, `checks: checks.py`.
        - `SKILL.md`: 고정 지침을 적을 자리와 유동 영역 표시 쌍 한 번.
        - `checks.py`: 함수 없이 검사 함수 규약을 적은 주석만.

        ID가 ID 규칙에 맞지 않으면 `invalid_id`, 그 폴더가 이미 있으면(비었어도) `skill_exists`다.
        어느 쪽이든 아무 파일도 만들거나 바꾸지 않는다. 쓰다가 실패하면 만든 폴더를 지운다.
        만든 뒤 `skill(skill_id)`로 다시 읽어 돌려준다.
        """
        if not _SAFE_ID.fullmatch(skill_id):
            raise InvalidIdError(f"쓸 수 없는 스킬 ID입니다: {skill_id!r}. {_ID_RULE}")
        skills = self.root / SKILLS_DIR
        folder = skills / skill_id
        contents = {
            SKILL_CONFIG_FILE: _skill_yaml(skill_id),
            SKILL_MD_FILE: _skill_md(skill_id),
            CHECKS_FILE: _checks_py(skill_id),
        }
        with self.lock():
            skills.mkdir(parents=True, exist_ok=True)
            try:
                folder.mkdir()
            except FileExistsError:
                raise SkillExistsError(
                    f"스킬 폴더가 이미 있습니다: {SKILLS_DIR}/{skill_id}/. "
                    "그 안의 파일은 바꾸지 않았습니다. 다른 ID를 쓰거나 그 폴더의 파일을 고치세요."
                ) from None
            try:
                for name, text in contents.items():
                    write_text(folder / name, text)
            except BaseException:
                shutil.rmtree(folder, ignore_errors=True)
                raise
        return NewSkill(skill=self.skill(skill_id), files=tuple(folder / name for name in contents))

    def write_card(self, card: Card) -> Path:
        """`layers/cards/<id>.yaml`에 쓴다."""
        return self._write_one(self.path / CARDS_DIR, card)

    def write_candidate(self, candidate: Candidate) -> Path:
        """`candidates/<id>.yaml`에 쓴다."""
        return self._write_one(self.path / CANDIDATES_DIR, candidate)

    def write_task(self, task: Task) -> Path:
        """`tasks/<split>/<id>.yaml`에 쓴다.

        같은 ID의 파일이 다른 분할 폴더에 있으면 쓰지 않고 `task_exists`다. 분할은 바꿀 수 없다.
        원장에는 쓰지 않는다. 과제를 등록하려면 `add_task`를 쓴다.
        """
        _check_id(task.id)
        with self.lock():
            places = self._task_files(task.id, [s for s in SPLITS if s != task.split])
            if places:
                raise _task_exists(task.id, places)
            return self._write_one(self.path / TASKS_DIR / task.split, task)

    def add_task(self, task: Task) -> AddedTask:
        """과제를 등록한다. 잠금 안에서 검사하고, 원장에 `task` 줄을 덧붙인 뒤 과제 파일을 쓴다.

        - 같은 ID의 과제 파일이 세 분할 폴더 어디에 있거나 원장에 그 ID의 `task` 줄이 있으면
          분할과 상관없이 `task_exists`다. 그래서 분할은 바뀌지 않는다.
        - 봉인 과제에 `reference`가 없으면 `reference_required`다.
        - 원장의 마지막 줄에서 `hash`를 얻지 못하면 `ledger_broken`이고 과제 파일도 쓰지 않는다.
        - 원장 줄을 쓴 뒤 파일을 쓰다 실패하면 원장 줄만 남는다. 그 ID는 다시 등록할 수 없다.

        검사에 걸리면 아무것도 쓰지 않는다. 스킬과 맥락은 부르는 쪽이 먼저 본다.
        """
        _check_id(task.id)
        with self.lock():
            places = self._task_files(task.id, SPLITS) + self._task_lines(task.id)
            if places:
                raise _task_exists(task.id, places)
            sealed_hash: str | None = None
            if task.split == "sealed":
                if task.reference is None:
                    raise ReferenceRequiredError(
                        f"봉인(sealed) 과제 {task.id}에는 기준(reference)이 있어야 합니다. "
                        "봉인 과제의 기준은 결과물을 만들기 전에 받아 둡니다."
                    )
                sealed_hash = reference_hash(task.reference)
            entry = TaskEntry(
                id=task.id,
                ts=datetime.now().astimezone().isoformat(timespec="seconds"),
                skill=task.skill,
                split=task.split,
                reference_hash=sealed_hash,
            )
            self.append_ledger(entry.model_dump(mode="json"))
            path = self.write_task(task)
        return AddedTask(entry=entry, path=path)

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

    def append_ledger(self, entry: dict[str, Any]) -> dict[str, Any]:
        """원장(`ledger.jsonl`)에 잠금 안에서 한 줄을 덧붙이고, 덧붙인 줄을 돌려준다.

        줄 끝에 앞줄과 잇는 `prev_hash`와 그 줄의 `hash`를 붙인다(`store.ledger`).
        마지막 줄에서 `hash`를 얻지 못하면 덧붙이지 않고 `ledger_broken`이다.
        원장의 줄은 고치거나 지우지 않는다.
        """
        with self.lock():
            return ledger.append(self.path / LEDGER_FILE, entry, root=self.root)

    def ledger_tail_hash(self) -> str:
        """잠금 안에서 원장의 끝 줄을 읽어 다음에 덧붙일 줄의 `prev_hash`를 돌려준다.

        마지막 줄의 `hash`이고, 원장이 없거나 비었으면 `GENESIS`다. 얻지 못하면
        `append_ledger`가 덧붙일 때와 같은 `ledger_broken`이다(같은 `ledger.tail_hash`로 본다).
        원장은 바꾸지 않는다. 모델 호출처럼 비용이 드는 일을 하기 전에, 그 결과를 원장에
        남길 수 있는지 미리 볼 때 쓴다.
        """
        with self.lock():
            return ledger.tail_hash(self.path / LEDGER_FILE, root=self.root)

    def verify_ledger(self) -> ledger.LedgerCheck:
        """잠금 안에서 원장의 해시 체인을 처음부터 다시 계산한다.

        줄 수, 마지막 줄의 `hash`, 손상 목록(줄, 이유)을 돌려준다. 손상이 있어도 예외를 내지 않는다.
        """
        with self.lock():
            return ledger.check(self.path / LEDGER_FILE)

    def verify_sealed(self) -> SealedCheck:
        """잠금 안에서 봉인 과제의 기준이 원장에 등록한 해시와 같은지 본다.

        원장에서 읽을 수 있는 `task` 줄 가운데 `split: sealed`인 것마다(같은 ID가 여럿이면 첫
        줄) 그 과제 파일을 저장 계층 안에서 직접 읽는다. 토큰이 필요한 길을 거치지 않는다.
        파일이 없거나 읽을 수 없거나 기준 해시가 다르면 알린다. `tasks/sealed/`에 있는데
        원장에 봉인 과제로 등록한 줄이 없는 파일도 알린다. 이유에는 과제의 내용을 쓰지 않는다.
        문제가 있어도 예외를 내지 않는다.
        """
        with self.lock():
            ledger_path = self.path / LEDGER_FILE
            registered: dict[str, Any] = {}
            problems: list[SealedProblem] = []
            for number, obj in ledger.entries(ledger_path):
                if obj.get("type") != "task" or obj.get("split") != "sealed":
                    continue
                task_id = obj.get("id")
                if not (isinstance(task_id, str) and _SAFE_ID.fullmatch(task_id)):
                    problems.append(
                        SealedProblem(
                            f"{DATA_DIR}/{LEDGER_FILE}:{number}",
                            "봉인 과제로 등록한 task 줄의 id를 과제 ID로 읽을 수 없습니다",
                        )
                    )
                    continue
                registered.setdefault(task_id, obj.get("reference_hash"))
            for task_id, stored in registered.items():
                reason = self._sealed_problem(task_id, stored)
                if reason is not None:
                    problems.append(SealedProblem(_shown_task("sealed", task_id), reason))
            folder = self.path / TASKS_DIR / "sealed"
            if folder.is_dir():
                for path in sorted(_yaml_files(folder), key=lambda p: p.name):
                    if path.stem not in registered:
                        problems.append(
                            SealedProblem(
                                f"{DATA_DIR}/{TASKS_DIR}/sealed/{path.name}",
                                "원장에 봉인 과제로 등록한 task 줄이 없습니다",
                            )
                        )
            return SealedCheck(checked=len(registered), problems=tuple(problems))

    # 내부

    def _task_path(self, split: str, task_id: str) -> Path:
        return self.path / TASKS_DIR / split / f"{task_id}.yaml"

    def _check_task_split(self, path: Path, task: Task, split: str) -> None:
        """파일의 `split`이 과제가 든 폴더와 다르면 `invalid_file`이다."""
        if task.split != split:
            raise invalid_file(
                path,
                self.root,
                [
                    Problem(
                        ("split",),
                        f"과제가 든 폴더({TASKS_DIR}/{split})와 다릅니다(받은 값: {task.split!r})",
                        field="split",
                    )
                ],
            )

    def _task_files(self, task_id: str, splits: Sequence[Split]) -> list[tuple[str | None, str]]:
        """`splits` 폴더에 있는 `task_id`의 파일. (분할, 프로젝트 기준 경로) 목록이다."""
        return [
            (split, _shown_task(split, task_id))
            for split in splits
            if self._task_path(split, task_id).exists()
        ]

    def _task_lines(self, task_id: str) -> list[tuple[str | None, str]]:
        """원장에서 읽을 수 있는 `task_id`의 `task` 줄. (적힌 분할, `<원장>:<줄>`) 목록이다.

        적힌 분할이 세 분할 가운데 하나가 아니면 분할은 `None`이다.
        """
        return [
            (
                obj.get("split") if obj.get("split") in SPLITS else None,
                f"{DATA_DIR}/{LEDGER_FILE}:{number}",
            )
            for number, obj in ledger.entries(self.path / LEDGER_FILE)
            if obj.get("type") == "task" and obj.get("id") == task_id
        ]

    def _sealed_problem(self, task_id: str, stored: Any) -> str | None:
        """등록한 봉인 과제 하나의 문제. 없으면 `None`이다. 이유에 내용을 쓰지 않는다."""
        path = self._task_path("sealed", task_id)
        if not path.is_file():
            return "파일이 없습니다"
        try:
            task = read_model(path, Task, root=self.root)
        except (InvalidFileError, OSError):
            # 형식 오류의 메시지에는 받은 값이 들어갈 수 있어 그대로 쓰지 않는다
            return "과제 파일로 읽을 수 없습니다"
        if task.id != task_id:
            return "파일의 id가 원장에 등록한 과제 ID와 다릅니다"
        if task.split != "sealed":
            return "파일의 split이 sealed가 아닙니다"
        if not isinstance(stored, str):
            return "원장의 task 줄에 기준 해시(reference_hash)가 없습니다"
        if task.reference is None:
            return "기준(reference)이 없습니다"
        if reference_hash(task.reference) != stored:
            return "기준(reference)이 등록 때와 다릅니다"
        return None

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
        paths = sorted(_yaml_files(folder), key=lambda p: p.name)
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


def read_task_file(path: Path, *, root: Path) -> Task:
    """등록할 과제 파일 하나를 읽는다. 메시지의 경로는 `root` 기준이다.

    형식이 틀리거나 `id`가 ID 규칙(경로 문자 금지)에 맞지 않으면 `invalid_file`이다.
    봉인 과제가 될 수 있으므로 형식 오류의 메시지에는 받은 값을 쓰지 않는다(`id`만 쓴다).
    """
    task = read_model(path, Task, root=root, show_values=False)
    if not _SAFE_ID.fullmatch(task.id):
        raise invalid_file(
            path,
            root,
            [
                Problem(
                    ("id",), f"쓸 수 없는 ID입니다(받은 값: {task.id!r}). {_ID_RULE}", field="id"
                )
            ],
        )
    return task


def _skill_yaml(skill_id: str) -> str:
    """새 스킬의 `skill.yaml` 글. 값은 `Skill`의 기본값이라 다시 읽으면 같은 설정이다.

    `dump_yaml`이 쓰므로 `123`, `true` 같은 ID도 글로 따옴표를 쳐서 쓴다.
    """
    skill = Skill(id=skill_id, checks=CHECKS_FILE, skill_md=Path(SKILL_MD_FILE))
    head = (
        f"# 스킬 {skill_id}의 설정. 판단 지점(decision_points)과 맥락 축(context_axes)을 채운다.\n"
        "# 예:\n"
        "#   decision_points:\n"
        "#     - {id: opening, name: 첫 문장, weight: 2}\n"
        "#   context_axes:\n"
        "#     purpose: [문의, 상담, 기타]\n"
    )
    return head + dump_yaml(skill.model_dump(by_alias=True))


def _skill_md(skill_id: str) -> str:
    """새 스킬의 `SKILL.md` 글. 유동 영역 표시 쌍이 정확히 한 번 든다."""
    return (
        "---\n"
        f"name: {skill_id}\n"
        "description: 이 스킬이 하는 일을 한 문장으로 적는다.\n"
        "---\n"
        "\n"
        f"# {skill_id}\n"
        "\n"
        "이 스킬의 고정 지침(하는 일, 절차, 형식)을 여기에 적는다.\n"
        "deeptwin은 아래 표시 쌍 사이에 이번 작업의 개인 기준을 넣는다. 표시 쌍은 한 번만 둔다.\n"
        "\n"
        f"{FLUID_OPEN}\n"
        f"{FLUID_CLOSE}\n"
    )


def _checks_py(skill_id: str) -> str:
    """새 스킬의 `checks.py` 글. 함수 없이 검사 함수 규약을 적은 주석만 든다."""
    return (
        f"# 스킬 {skill_id}의 원칙 검사 함수.\n"
        "#\n"
        "# 원칙(.deeptwin/layers/principles.yaml)의 check에 함수 이름을 적고, 그 이름의 함수를\n"
        "# 이 파일의 모듈 수준에 둔다. 함수는 결과물 글을 받아 원칙을 지켰으면 True,\n"
        "# 어겼으면 False를 돌려준다: fn(output: str) -> bool\n"
        "# 표준 라이브러리와 설치한 패키지는 import할 수 있고,\n"
        "# 같은 폴더의 다른 파일은 import할 수 없다.\n"
        "#\n"
        "# 예:\n"
        "#\n"
        "# import re\n"
        "#\n"
        "#\n"
        "# def no_inflated_numbers(output: str) -> bool:\n"
        '#     return not re.search(r"역대급|최고의|100%", output)\n'
    )


def _check_id(item_id: str) -> None:
    """파일 이름과 원장에 쓰는 ID인지 본다. 아니면 쓰지 않고 `ValueError`를 낸다."""
    if not _SAFE_ID.fullmatch(item_id):
        raise ValueError(f"쓸 수 없는 ID입니다: {item_id!r}. {_ID_RULE}")


def _yaml_files(folder: Path) -> Iterator[Path]:
    """폴더의 `.yaml` 파일. 점으로 시작하는 파일은 건너뛴다.

    확장자는 대소문자까지 `.yaml`이어야 한다. 운영체제마다 읽는 파일이 같게 하려는 것이다.
    """
    return (
        p
        for p in folder.iterdir()
        if p.suffix == ".yaml" and not p.name.startswith(".") and p.is_file()
    )


def _shown_task(split: str, task_id: str) -> str:
    """메시지에 쓰는 과제 파일의 경로(프로젝트 루트 기준)."""
    return f"{DATA_DIR}/{TASKS_DIR}/{split}/{task_id}.yaml"


def _task_exists(task_id: str, places: Sequence[tuple[str | None, str]]) -> TaskExistsError:
    """`places`는 (분할, 있는 곳) 목록이다. 분할을 모르는 곳은 분할이 `None`이다."""
    splits = list(dict.fromkeys(split for split, _ in places if split is not None))
    head = (
        f"과제 {task_id}은 이미 {', '.join(splits)} 분할에 있습니다."
        if splits
        else f"과제 {task_id}은 이미 있습니다."
    )
    where = ", ".join(place for _, place in places)
    return TaskExistsError(f"{head} 분할은 바꿀 수 없습니다. 있는 곳: {where}")


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
