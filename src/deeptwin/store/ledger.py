"""JSONL 원장과 해시 체인(설계서 9.5).

원장의 줄마다 끝에 `prev_hash`와 `hash`를 붙여 앞줄과 잇는다.

- `hash = "sha256:" + SHA-256(prev_hash + 본문)`. 본문은 그 줄에서 두 필드를 뺀 객체를
  정렬된 JSON(`sort_keys=True`, `ensure_ascii=False`, `separators=(",", ":")`)으로 쓴 것이고,
  UTF-8 바이트로 해시한다.
- 첫 줄의 `prev_hash`는 `GENESIS`다. 다음 줄부터는 앞줄에 저장된 `hash`다.

검사는 앞줄에 저장된 `hash`와 비교한다. 다시 계산한 값과 비교하면 한 줄을 고쳤을 때 그 뒤의
모든 줄이 손상으로 나온다. 원장을 고치거나 다시 쓰는 함수는 두지 않는다.

잠금은 부르는 쪽(`DeepTwin`)이 잡는다.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deeptwin.errors import LedgerBrokenError
from deeptwin.store.files import append_jsonl

GENESIS = "sha256:" + "0" * 64
"""첫 줄의 `prev_hash`."""

CHAIN_FIELDS = ("prev_hash", "hash")
"""원장 계층이 줄 끝에 붙이는 필드. 이 순서로 붙인다."""


@dataclass(frozen=True)
class Damage:
    """원장의 손상 하나."""

    line: int
    """1부터 센 줄 번호."""
    reason: str
    """한국어 설명."""


@dataclass(frozen=True)
class LedgerCheck:
    """원장 검사의 결과. 손상이 있어도 예외를 내지 않고 여기에 모은다."""

    lines: int
    """원장의 줄 수. 손상된 줄도 센다."""
    head: str | None
    """마지막 줄에 저장된 `hash`. 줄이 없거나 마지막 줄에서 `hash`를 읽을 수 없으면 `None`이다."""
    damages: tuple[Damage, ...]
    """줄 번호 순서의 손상 목록. 한 줄에 손상이 여럿이면 여럿이 나온다."""


def line_hash(prev_hash: str, body: Mapping[str, Any]) -> str:
    """줄 하나의 `hash`. `body`는 `prev_hash`와 `hash`를 뺀 객체다."""
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256((prev_hash + text).encode("utf-8")).hexdigest()


def append(path: Path, entry: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    """원장 끝에 `entry`를 한 줄로 덧붙이고, 덧붙인 줄(`prev_hash`, `hash`를 붙인 것)을 돌려준다.

    `prev_hash`는 `tail_hash`다: 마지막 줄의 `hash`, 파일이 없거나 비었으면 `GENESIS`다.
    마지막 줄에서 `hash`를 얻지 못하면 덧붙이지 않고 `ledger_broken`이다. 이유는 `check`와 같다.
    메시지의 경로는 `root` 기준이다.
    """
    clash = [name for name in CHAIN_FIELDS if name in entry]
    if clash:
        raise ValueError(f"원장 계층이 붙이는 필드는 넘기지 마세요: {', '.join(clash)}")
    # JSON으로 한 번 오가게 한다. 해시는 검사 때 파일에서 읽은 객체로 다시 계산하므로
    # 그 객체와 같은 것으로 만들어야 한다(예: 튜플 -> 목록, 정수 키 -> 글 키)
    body: dict[str, Any] = json.loads(json.dumps(dict(entry), ensure_ascii=False))
    prev = tail_hash(path, root=root)
    written = {**body, "prev_hash": prev, "hash": line_hash(prev, body)}
    if _ends_without_newline(path):
        # 사람이 고치다 끝 줄바꿈을 지웠다. 마지막 줄 뒤에 이어 쓰지 않게 줄을 바꾼다
        with path.open("ab") as f:
            f.write(b"\n")
    append_jsonl(path, written)
    return written


def tail_hash(path: Path, *, root: Path) -> str:
    """원장 끝에 덧붙일 줄의 `prev_hash`: 마지막 줄에 저장된 `hash`다.

    파일이 없거나 비었으면 `GENESIS`다. 마지막 줄에서 `hash`를 얻지 못하면(읽을 수 없는 줄,
    `hash`가 없는 0.0.1의 줄 등) `ledger_broken`이다. 이유는 `check`와 같고, 메시지의 경로는
    `root` 기준이다. `append`가 이 함수로 끝 줄을 읽으므로, 덧붙이기 전에 따로 불러 보면
    덧붙일 수 있는지 미리 알 수 있다. 파일은 바꾸지 않는다.
    """
    lines = _split(path.read_bytes() if path.exists() else b"")
    if not lines:
        return GENESIS
    last = _read(lines[-1])
    if isinstance(last, str):
        reason = last
    elif (problem := _field_problem(last, "hash")) is not None:
        reason = problem
    else:
        stored: str = last["hash"]
        return stored
    raise ledger_broken(
        path,
        root,
        [Damage(len(lines), reason)],
        note=(
            "원장의 마지막 줄에서 앞줄로 이을 hash를 얻지 못해 줄을 덧붙이지 않았습니다. "
            "deeptwin verify로 원장을 확인하세요."
        ),
    )


def check(path: Path) -> LedgerCheck:
    """원장의 체인을 처음부터 다시 계산해 손상된 줄을 모두 모은다. 파일이 없으면 빈 원장이다.

    줄마다 본다: JSON 객체인가, `prev_hash`와 `hash`가 글로 있는가, `hash`가 다시 계산한 값과
    같은가, `prev_hash`가 앞줄에 저장된 `hash`(첫 줄은 `GENESIS`)와 같은가.
    앞줄에서 `hash`를 읽을 수 없으면 이어짐은 보지 않는다. 그 앞줄이 이미 손상으로 나온다.
    """
    lines = _split(path.read_bytes() if path.exists() else b"")
    damages: list[Damage] = []
    # 이 줄의 prev_hash가 같아야 하는 값. 앞줄에서 hash를 읽지 못해 모르면 None이다
    expected: str | None = GENESIS
    for number, raw in enumerate(lines, start=1):
        obj = _read(raw)
        if isinstance(obj, str):
            damages.append(Damage(number, obj))
            expected = None
            continue
        stored = obj.get("hash")
        problems = [
            Damage(number, reason)
            for name in CHAIN_FIELDS
            if (reason := _field_problem(obj, name)) is not None
        ]
        if problems:
            damages.extend(problems)
        else:
            prev = obj["prev_hash"]
            body = {k: v for k, v in obj.items() if k not in CHAIN_FIELDS}
            if stored != line_hash(prev, body):
                damages.append(Damage(number, "hash가 내용과 맞지 않습니다"))
            if expected is not None and prev != expected:
                damages.append(
                    Damage(
                        number,
                        "prev_hash가 첫 줄의 시작값이 아닙니다"
                        if number == 1
                        else "앞줄의 hash와 이어지지 않습니다",
                    )
                )
        expected = stored if isinstance(stored, str) else None
    head = expected if lines else None
    return LedgerCheck(lines=len(lines), head=head, damages=tuple(damages))


def entries(path: Path) -> list[tuple[int, dict[str, Any]]]:
    """원장에서 JSON 객체로 읽을 수 있는 줄을 (1부터 센 줄 번호, 객체)로 돌려준다.

    체인은 보지 않는다. 손상된 줄이어도 JSON 객체면 넣고, 읽을 수 없는 줄은 건너뛴다.
    파일이 없으면 빈 목록이다. 중복 등록 검사와 봉인 검사가 쓴다.
    """
    lines = _split(path.read_bytes() if path.exists() else b"")
    found: list[tuple[int, dict[str, Any]]] = []
    for number, raw in enumerate(lines, start=1):
        obj = _read(raw)
        if not isinstance(obj, str):
            found.append((number, obj))
    return found


def ledger_broken(
    path: Path, root: Path, damages: Iterable[Damage], *, note: str = ""
) -> LedgerBrokenError:
    """손상마다 한 줄씩 `<root 기준 POSIX 경로>:<줄>: <이유>`로 쓴 오류. `note`는 그 뒤에 붙는다.

    `note`는 여러 줄이어도 된다(`deeptwin verify`는 봉인 검사의 줄들을 붙인다).
    """
    try:
        shown = path.relative_to(root).as_posix()
    except ValueError:
        shown = path.as_posix()
    lines = [f"{shown}:{d.line}: {d.reason}" for d in damages]
    if note:
        lines.append(note)
    return LedgerBrokenError("\n".join(lines))


def _split(data: bytes) -> list[bytes]:
    """원장을 줄로 나눈다. 파일 끝의 줄바꿈 하나는 줄이 아니다. 빈 줄도 한 줄이다."""
    if not data:
        return []
    lines = data.split(b"\n")
    if data.endswith(b"\n"):
        lines.pop()
    return lines


def _ends_without_newline(path: Path) -> bool:
    """파일이 있고 비지 않았는데 줄바꿈으로 끝나지 않으면 참이다. 마지막 바이트만 읽는다."""
    if not path.exists():
        return False
    with path.open("rb") as f:
        if f.seek(0, os.SEEK_END) == 0:
            return False
        f.seek(-1, os.SEEK_END)
        return f.read(1) != b"\n"


def _field_problem(obj: Mapping[str, Any], name: str) -> str | None:
    """체인 필드 `name`이 글로 있지 않으면 그 까닭(한국어). 있으면 `None`이다."""
    if name not in obj:
        return f"{name}가 없습니다"
    if not isinstance(obj[name], str):
        return f"{name}가 글이 아닙니다"
    return None


def _read(raw: bytes) -> dict[str, Any] | str:
    """줄 하나를 JSON 객체로 읽는다. 읽을 수 없으면 그 까닭(한국어)을 돌려준다."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "UTF-8 글로 읽을 수 없습니다"
    if not text.strip():
        return "빈 줄입니다"
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError):
        return "JSON으로 읽을 수 없는 줄입니다"
    if not isinstance(obj, dict):
        return "JSON 객체가 아닙니다"
    return obj
