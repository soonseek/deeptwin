"""평가 폴더 `.deeptwin/eval/<평가 ID>/`의 읽기와 쓰기.

평가 모듈(`deeptwin.eval`)은 이 모듈을 거쳐서만 평가 파일에 닿는다. 한 평가 폴더의 파일은
다음과 같다. 쓰는 순서도 이 순서다.

- `eval.json`: 평가 정보(`EvalInfo`). 조건과 이어지지 않는 것만 적는다.
- `outputs/<조건>/<과제 ID>.md`: 조건별 결과물. 그 실행의 `output.md`와 같은 바이트다.
- `key.json`: 대응표(`EvalKey`). 과제와 조건마다의 실행 ID, 쌍마다 좌우의 조건.
- `pairs.jsonl`: 쌍 목록(`Pair`). 마지막에 쓴다. 이 파일이 있으면 쌍을 다 만든 것이다.
- `choices.jsonl`: 선택 기록(`Choice`). 고를 때마다 잠금 안에서 한 줄씩 덧붙인다.
- `report.json`, `report.md`: 보고서. 모두 고른 뒤에만 쓴다.

JSON은 `ensure_ascii=False`로 원자적으로 쓴다. 형식이 틀린 파일은 `invalid_file`이다.
`DeepTwin`(`store.project`)은 이 모듈을 import하지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from deeptwin.errors import EvalIncompleteError, EvalNotFoundError, InvalidChoiceError
from deeptwin.models import Choice, Condition, EvalInfo, EvalKey, EvalReport, Pair
from deeptwin.store.files import (
    append_jsonl,
    read_json_model,
    read_jsonl_models,
    write_json_model,
    write_jsonl_models,
    write_text,
)
from deeptwin.store.project import DATA_DIR, DeepTwin

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
    "new_eval",
    "open_eval",
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

    # 대응표와 쌍 목록

    def save_key(self, key: EvalKey) -> None:
        write_json_model(self.path / KEY_FILE, key)

    def key(self) -> EvalKey:
        """대응표. 없으면 `eval_incomplete`다."""
        path = self.path / KEY_FILE
        if not path.is_file():
            raise self._incomplete(KEY_FILE)
        return read_json_model(path, EvalKey, root=self.deeptwin.root)

    def save_pairs(self, pairs: Sequence[Pair]) -> None:
        write_jsonl_models(self.path / PAIRS_FILE, pairs)

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
            "deeptwin eval pairs로 새 평가를 만드세요."
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


def _not_found(eval_id: str) -> EvalNotFoundError:
    looked = f"{DATA_DIR}/{EVAL_DIR}/"
    return EvalNotFoundError(
        f"평가를 찾지 못했습니다: {eval_id}. 평가 ID는 eval-0001 꼴이고, "
        f"{looked}<평가 ID>/{EVAL_FILE}이 있어야 합니다."
    )
