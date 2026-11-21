"""YAML 읽기·쓰기, 원자적 저장, JSONL 덧붙이기.

쓰기는 같은 폴더의 임시 파일에 쓴 뒤 `os.replace`로 바꾼다. 쓰다 죽어도 반쯤 쓴 파일이
남지 않는다. YAML은 키 순서를 지키고 한글을 그대로 쓴다.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

import yaml


def read_yaml(path: Path) -> Any:
    """YAML 파일 하나를 읽는다. 빈 파일은 `None`이다."""
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def write_yaml(path: Path, data: Any) -> None:
    write_text(path, dump_yaml(data))


def write_text(path: Path, text: str, *, errors: str = "strict") -> None:
    """UTF-8 글을 원자적으로 쓴다. 줄바꿈은 바꾸지 않는다."""
    write_bytes(path, text.encode("utf-8", errors=errors))


def write_bytes(path: Path, data: bytes) -> None:
    """바이트를 원자적으로 쓴다: 같은 폴더의 임시 파일 -> `os.replace`.

    파일 권한은 기존 파일이 있으면 그대로 두고, 없으면 커널이 umask를 적용한 기본값이다.
    """
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o666)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    """JSONL 파일 끝에 한 줄을 덧붙이고 fsync한다. 한글은 그대로, 줄바꿈은 LF로 쓴다."""
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
