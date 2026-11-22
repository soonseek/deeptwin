"""평가 폴더 `.deeptwin/eval/<평가 ID>/`의 읽기와 쓰기.

평가 모듈(`deeptwin.eval`)은 이 모듈을 거쳐서만 평가 파일에 닿는다. 한 평가 폴더의 파일은
다음과 같다. 쓰는 순서도 이 순서다.

- `eval.json`: 평가 정보(`EvalInfo`). 조건과 이어지지 않는 것만 적는다.
- `outputs/<조건>/<과제 ID>.md`: 조건별 결과물. 그 실행의 `output.md`와 같은 바이트다.
- `key.json`: 대응표(`EvalKey`). 과제와 조건마다의 실행 ID, 쌍마다 좌우의 조건. 생성마다 그때까지의
  `runs`와 빈 `pairs`로 다시 쓰고, 다 만든 뒤 `pairs`를 채워 쓴다.
- `pairs.jsonl`: 쌍 목록(`Pair`). 마지막에 쓴다. 이 파일이 있으면 쌍을 다 만든 것이다.
- `choices.jsonl`: 선택 기록(`Choice`). 고를 때마다 잠금 안에서 한 줄씩 덧붙인다.
- `report.json`, `report.md`: 보고서. 모두 고른 뒤에만 쓴다.

JSON은 `ensure_ascii=False`로 원자적으로 쓴다. 형식이 틀린 파일은 `invalid_file`이다.
`DeepTwin`(`store.project`)은 이 모듈을 import하지 않는다.

봉인 평가가 원장에 남기는 `seal_open` 줄(`SealOpen`)도 여기서 찾고 덧붙인다(`seal_open_line`).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from deeptwin.errors import EvalIncompleteError, EvalNotFoundError, InvalidChoiceError
from deeptwin.models import Choice, Condition, EvalInfo, EvalKey, EvalReport, Pair, SealOpen
from deeptwin.store import ledger
from deeptwin.store.files import (
    append_jsonl,
    read_json_model,
    read_jsonl_models,
    read_utf8,
    write_json_model,
    write_jsonl_models,
    write_text,
)
from deeptwin.store.project import DATA_DIR, LEDGER_FILE, DeepTwin

__all__ = [
    "CHOICES_FILE",
    "EVAL_DIR",
    "EVAL_FILE",
    "EvalFolder",
    "KEY_FILE",
    "OUTPUTS_DIR",
    "PAIRS_FILE",
    "REPORT_JSON_FILE",
    "REPORT_MD_FILE",
    "SealLine",
    "new_eval",
    "open_eval",
    "seal_open_line",
]

EVAL_DIR = "eval"
"""평가 폴더들을 두는 곳. `.deeptwin/` 기준이다."""
EVAL_FILE = "eval.json"
KEY_FILE = "key.json"
PAIRS_FILE = "pairs.jsonl"
CHOICES_FILE = "choices.jsonl"
REPORT_JSON_FILE = "report.json"
REPORT_MD_FILE = "report.md"
OUTPUTS_DIR = "outputs"

_EVAL_ID = re.compile(r"eval-([0-9]+)")
"""평가 ID의 모양. 숫자는 ASCII 숫자만 받는다."""
_SEAL_ID = re.compile(r"seal-([0-9]+)")
"""원장 `seal_open` 줄 ID의 모양. 숫자는 ASCII 숫자만 받는다."""
_SEAL_DIGITS = 9
"""`seal_open_line`이 세는 `seal_open` 줄 번호의 최대 자릿수. 넘는 ID는 세지 않는다."""


@dataclass(frozen=True)
class EvalFolder:
    """평가 폴더 하나의 핸들. `new_eval`이나 `open_eval`로 얻는다."""

    deeptwin: DeepTwin
    id: str
    """평가 ID(`eval-NNNN`)."""

    @property
    def path(self) -> Path:
        return self.deeptwin.path / EVAL_DIR / self.id

    def shown(self, name: str) -> str:
        """메시지에 쓰는 이 폴더의 파일 경로(프로젝트 루트 기준)."""
        return f"{DATA_DIR}/{EVAL_DIR}/{self.id}/{name}"

    def stored(self, name: str) -> str:
        """결과에 쓰는 이 폴더의 파일 경로(`.deeptwin/` 기준)."""
        return f"{EVAL_DIR}/{self.id}/{name}"

    # 정보

    def save_info(self, info: EvalInfo) -> None:
        write_json_model(self.path / EVAL_FILE, info)

    def info(self) -> EvalInfo:
        path = self.path / EVAL_FILE
        if not path.is_file():
            raise _not_found(self.id)
        return read_json_model(path, EvalInfo, root=self.deeptwin.root)

    # 결과물

    def save_output(self, condition: Condition, task_id: str, output: str) -> None:
        """`outputs/<조건>/<과제 ID>.md`에 결과물을 쓴다. 줄바꿈은 바꾸지 않는다."""
        folder = self.path / OUTPUTS_DIR / condition
        folder.mkdir(parents=True, exist_ok=True)
        write_text(folder / f"{task_id}.md", output)

    def output(self, condition: Condition, task_id: str) -> str | None:
        """`outputs/<조건>/<과제 ID>.md`의 글. 쓴 바이트 그대로 읽는다. 파일이 없으면 `None`이다.

        UTF-8이 아니면 `invalid_file`이다.
        """
        path = self.path / OUTPUTS_DIR / condition / f"{task_id}.md"
        if not path.is_file():
            return None
        data = path.read_bytes()
        try:
            # utf-8은 맨 앞의 BOM도 글자로 남긴다. 쓴 글과 같은 글이다
            return data.decode("utf-8")
        except UnicodeDecodeError:
            # 파일과 줄을 담은 invalid_file을 낸다
            return read_utf8(path, root=self.deeptwin.root)

    # 대응표와 쌍 목록

    def save_key(self, key: EvalKey) -> None:
        write_json_model(self.path / KEY_FILE, key)

    def key(self) -> EvalKey:
        """대응표. 없으면 `eval_incomplete`다."""
        path = self.path / KEY_FILE
        if not path.is_file():
            raise self._incomplete(KEY_FILE)
        return read_json_model(path, EvalKey, root=self.deeptwin.root)

    def saved_runs(self) -> dict[str, dict[Condition, str]]:
        """대응표에 적어 둔 실행(과제 ID -> 조건 -> 실행 ID). 대응표가 아직 없으면 빈 사전이다.

        대응표는 생성마다 다시 쓰므로, 생성이 중간에 멈춘 평가에서는 그때까지 만든 실행이다.
        """
        if not (self.path / KEY_FILE).is_file():
            return {}
        return {task: dict(runs) for task, runs in self.key().runs.items()}

    def save_pairs(self, pairs: Sequence[Pair]) -> None:
        write_jsonl_models(self.path / PAIRS_FILE, pairs)

    def has_pairs(self) -> bool:
        """쌍 목록(`pairs.jsonl`)이 있는지. 있으면 쌍을 다 만든 것이다."""
        return (self.path / PAIRS_FILE).is_file()

    def pairs(self) -> list[Pair]:
        """쌍 목록. 파일에 적힌 순서다. 없으면 `eval_incomplete`다."""
        path = self.path / PAIRS_FILE
        if not path.is_file():
            raise self._incomplete(PAIRS_FILE)
        return read_jsonl_models(path, Pair, root=self.deeptwin.root)

    # 선택

    def choices(self) -> list[Choice]:
        """선택 기록. 적힌 순서다. 아직 고른 쌍이 없어 파일이 없으면 빈 목록이다."""
        path = self.path / CHOICES_FILE
        if not path.is_file():
            return []
        return read_jsonl_models(path, Choice, root=self.deeptwin.root)

    def add_choice(self, choice: Choice) -> None:
        """잠금 안에서 쌍 목록과 선택 기록을 다시 읽고, 고를 수 있는 쌍이면 한 줄을 덧붙인다.

        쌍 목록에 없는 쌍이거나 이미 고른 쌍이면 아무것도 쓰지 않고 `invalid_choice`다.
        """
        with self.deeptwin.lock():
            if choice.pair not in {pair.id for pair in self.pairs()}:
                raise InvalidChoiceError(f"평가 {self.id}의 쌍 목록에 없는 쌍입니다: {choice.pair}")
            if choice.pair in {c.pair for c in self.choices()}:
                raise InvalidChoiceError(
                    f"평가 {self.id}의 쌍 {choice.pair}은 이미 골랐습니다. "
                    "한 쌍은 한 번만 고릅니다."
                )
            append_jsonl(self.path / CHOICES_FILE, choice.model_dump(mode="json"))

    # 보고서

    def save_report(self, report: EvalReport, markdown: str) -> tuple[str, str]:
        """`report.json`과 `report.md`를 쓰고 두 경로(`.deeptwin/` 기준)를 그 순서로 돌려준다."""
        write_json_model(self.path / REPORT_JSON_FILE, report)
        write_text(self.path / REPORT_MD_FILE, markdown)
        return self.stored(REPORT_JSON_FILE), self.stored(REPORT_MD_FILE)

    def _incomplete(self, name: str) -> EvalIncompleteError:
        return EvalIncompleteError(
            f"평가 {self.id}의 쌍을 다 만들지 못했습니다. {self.shown(name)}이 없습니다. "
            f"deeptwin eval pairs --resume {self.id}로 남은 것을 마저 만드세요."
        )


def new_eval(deeptwin: DeepTwin) -> EvalFolder:
    """`eval/eval-NNNN/`을 만들고 그 핸들을 돌려준다.

    번호는 `eval/`의 `eval-NNNN` 폴더 번호의 최댓값 + 1이다. 그 번호의 폴더가 이미 있으면(다른
    프로세스가 방금 만들었으면) 다음 번호로 넘어간다.
    """
    folder = deeptwin.path / EVAL_DIR
    folder.mkdir(exist_ok=True)
    number = 1 + max(
        (
            int(m.group(1))
            for child in folder.iterdir()
            if child.is_dir() and (m := _EVAL_ID.fullmatch(child.name))
        ),
        default=0,
    )
    while True:
        eval_id = f"eval-{number:04d}"
        try:
            (folder / eval_id).mkdir(exist_ok=False)
        except FileExistsError:
            number += 1
            continue
        return EvalFolder(deeptwin=deeptwin, id=eval_id)


def open_eval(deeptwin: DeepTwin, eval_id: str) -> EvalFolder:
    """평가 폴더를 연다. 아무것도 만들거나 쓰지 않는다.

    경로를 만들기 전에 ID가 `eval-<숫자>`인지 본다. 아니거나, 그 폴더나 `eval.json`이 없으면
    `eval_not_found`다.
    """
    if not _EVAL_ID.fullmatch(eval_id):
        raise _not_found(eval_id)
    found = EvalFolder(deeptwin=deeptwin, id=eval_id)
    if not (found.path.is_dir() and (found.path / EVAL_FILE).is_file()):
        raise _not_found(eval_id)
    return found


@dataclass(frozen=True)
class SealLine:
    """원장에 있는 평가 하나의 `seal_open` 줄."""

    id: str
    """줄 ID(`seal-NNNN`)."""
    reused: tuple[str, ...]
    """그 평가의 과제 가운데 원장에서 이 줄보다 앞선 다른 평가의 `seal_open` 줄에 든 과제."""
    added: bool
    """이번에 덧붙인 줄이면 참, 이미 있던 줄이면 거짓이다."""


def seal_open_line(deeptwin: DeepTwin, info: EvalInfo) -> SealLine:
    """잠금 안에서 원장의 이 평가의 `seal_open` 줄을 찾고, 없으면 하나를 덧붙인다.

    - 이 평가의 줄은 `eval`이 평가 ID이고 `id`가 글인 첫 `seal_open` 줄이다. 있으면 쓰지 않고
      그 줄을 돌려준다.
    - 없으면 `SealOpen` 줄(`id`, `type`, `ts`, `eval`, `skill`, `tasks`, `reused` 순)을 덧붙인다.
      `id`는 원장 `seal_open` 줄의 `seal-NNNN` 번호 최댓값 + 1이다(`_SEAL_DIGITS`자리까지만 센다).
      원장의 마지막 줄이 깨졌으면 덧붙이지 않고 `ledger_broken`이다.
    - `reused`는 `info.tasks` 가운데 이 줄보다 앞선 다른 평가의 `seal_open` 줄에 든 과제이고,
      순서는 `info.tasks`의 순서다. 상태 파일 없이 원장에서 계산한다.

    원장에서 읽을 수 없는 줄과 `tasks`가 글 목록이 아닌 `seal_open` 줄은 건너뛴다.
    """
    path = deeptwin.path / LEDGER_FILE
    with deeptwin.lock():
        entries = ledger.entries(path)
        lines = [
            (number, obj)
            for number, obj in entries
            if obj.get("type") == "seal_open" and _str_list(obj.get("tasks"))
        ]
        own = next(
            (
                (number, obj)
                for number, obj in lines
                if obj.get("eval") == info.id and isinstance(obj.get("id"), str)
            ),
            None,
        )
        if own is not None:
            number, obj = own
            earlier = [o for n, o in lines if n < number and o.get("eval") != info.id]
            return SealLine(id=obj["id"], reused=_reused(info.tasks, earlier), added=False)
        reused = _reused(info.tasks, [o for _, o in lines if o.get("eval") != info.id])
        entry = SealOpen(
            id=f"seal-{1 + max(_seal_numbers(entries), default=0):04d}",
            ts=datetime.now().astimezone().isoformat(timespec="seconds"),
            eval=info.id,
            skill=info.skill,
            tasks=list(info.tasks),
            reused=list(reused),
        )
        deeptwin.append_ledger(entry.model_dump(mode="json"))
        return SealLine(id=entry.id, reused=reused, added=True)


def _str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _reused(tasks: Sequence[str], earlier: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    """`tasks` 가운데 `earlier` 줄들의 `tasks`에 든 과제. `tasks`의 순서이고 겹친 ID는 하나다."""
    opened = {task for obj in earlier for task in obj["tasks"]}
    return tuple(task for task in dict.fromkeys(tasks) if task in opened)


def _seal_numbers(entries: Sequence[tuple[int, dict[str, Any]]]) -> Iterator[int]:
    """`seal_open` 줄 가운데 `id`가 `seal-NNNN`인 줄의 번호. `_SEAL_DIGITS`자리를 넘으면 안 센다.

    사람이 고친 줄 하나로 번호가 터무니없이 커지지 않게 하려는 것이다(`run` 줄과 같다).
    """
    for _, obj in entries:
        line_id = obj.get("id")
        if (
            obj.get("type") == "seal_open"
            and isinstance(line_id, str)
            and (m := _SEAL_ID.fullmatch(line_id))
            and len(m.group(1)) <= _SEAL_DIGITS
        ):
            yield int(m.group(1))


def _not_found(eval_id: str) -> EvalNotFoundError:
    looked = f"{DATA_DIR}/{EVAL_DIR}/"
    return EvalNotFoundError(
        f"평가를 찾지 못했습니다: {eval_id}. 평가 ID는 eval-0001 꼴이고, "
        f"{looked}<평가 ID>/{EVAL_FILE}이 있어야 합니다."
    )
