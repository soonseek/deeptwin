"""YAML 읽기·쓰기, 모델 로더, 원자적 저장, JSONL 덧붙이기.

쓰기는 같은 폴더의 임시 파일에 쓴 뒤 `os.replace`로 바꾼다. 쓰다 죽어도 반쯤 쓴 파일이
남지 않는다. YAML은 키 순서를 지키고 한글을 그대로 쓰며, 여러 줄 글은 `|` 블록으로 쓴다.

모델 로더(`read_model`, `read_models`)는 형식이 틀린 파일을 `InvalidFileError`로 거부한다.
메시지는 오류마다 한 줄씩, 줄 번호 순서로 `<프로젝트 기준 POSIX 경로>:<줄>: <설명>`이다.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import secrets
import stat
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import ErrorDetails

from deeptwin.errors import InvalidFileError

__all__ = [
    "Problem",
    "append_jsonl",
    "display_path",
    "dump_yaml",
    "invalid_file",
    "read_model",
    "read_models",
    "read_utf8",
    "write_model",
    "write_models",
    "write_text",
]

M = TypeVar("M", bound=BaseModel)

Loc: TypeAlias = tuple[str | int, ...]
"""파일 안의 위치. pydantic 오류의 `loc`과 같은 모양이다(예: `(0, "kind")`)."""


@dataclass(frozen=True)
class Problem:
    """파일 안의 틀린 곳 하나."""

    loc: Loc
    """줄 번호를 찾을 위치. 이 위치가 파일에 없으면 가장 길게 겹치는 앞부분의 줄을 쓴다."""
    text: str
    """한국어 설명."""
    field: str = ""
    """메시지에서 설명 앞에 붙이는 필드 이름(예: `kind`). 비우면 붙이지 않는다."""


def read_yaml(path: Path) -> Any:
    """YAML 파일 하나를 읽는다. 빈 파일은 `None`이다."""
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_model(
    path: Path,
    model: type[M],
    *,
    root: Path,
    update: Mapping[str, Any] | None = None,
    show_values: bool = True,
) -> M:
    """YAML 파일 하나를 모델 하나로 읽는다. 빈 파일은 빈 매핑으로 본다.

    `update`의 값은 파일의 값 위에 얹어 함께 검사한다. 메시지의 경로는 `root` 기준이다.
    `show_values`가 거짓이면 형식 오류의 메시지에 받은 값(`(받은 값: …)`)을 쓰지 않는다.
    봉인 과제가 될 파일처럼 내용을 내보이면 안 되는 파일에 쓴다.
    """
    text, data = _load(path, root)
    if data is None:
        data = {}
    if update is not None and isinstance(data, dict):
        data = {**data, **update}
    try:
        return model.model_validate(data)
    except ValidationError as error:
        problems = _problems(error, list_file=False, show_values=show_values)
        raise invalid_file(path, root, problems, text=text) from None


def read_models(path: Path, model: type[M], *, root: Path) -> list[M]:
    """목록 파일 하나를 모델 목록으로 읽는다. 파일에 적힌 순서를 지킨다. 빈 파일은 빈 목록이다."""
    text, data = _load(path, root)
    if data is None:
        return []
    try:
        return TypeAdapter(list[model]).validate_python(data)  # type: ignore[valid-type]
    except ValidationError as error:
        raise invalid_file(path, root, _problems(error, list_file=True), text=text) from None


def invalid_file(
    path: Path, root: Path, problems: Iterable[Problem], *, text: str | None = None
) -> InvalidFileError:
    """`problems`의 위치를 줄 번호로 바꿔 오류를 만든다. `text`를 주지 않으면 파일을 다시 읽는다."""
    if text is None:
        text = path.read_bytes().decode("utf-8-sig", "replace")
    lines = _line_map(text)
    shown = display_path(path, root)
    located = sorted(((_line_of(lines, p.loc), p) for p in problems), key=lambda pair: pair[0])
    return InvalidFileError(
        "\n".join(
            f"{shown}:{line}: {f'{p.field}: ' if p.field else ''}{p.text}" for line, p in located
        )
    )


def dump_yaml(data: Any) -> str:
    return yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False)


def write_yaml(path: Path, data: Any) -> None:
    write_text(path, dump_yaml(data))


def write_model(path: Path, model: BaseModel) -> None:
    """모델 하나를 YAML 파일 하나로 원자적으로 쓴다. 필드 이름은 파일의 이름(alias)이다."""
    write_yaml(path, model.model_dump(by_alias=True))


def write_models(path: Path, models: Sequence[BaseModel]) -> None:
    """모델 목록을 목록 파일 하나로 원자적으로 쓴다. 순서는 받은 그대로다."""
    write_yaml(path, [model.model_dump(by_alias=True) for model in models])


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


class _Dumper(yaml.SafeDumper):
    """여러 줄 글을 `|` 블록으로 쓰는 `SafeDumper`. 블록으로 못 쓰는 글은 PyYAML이 따옴표로 쓴다."""


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_str(data)


_Dumper.add_representer(str, _represent_str)


def read_utf8(path: Path, *, root: Path) -> str:
    """파일을 UTF-8 글로 읽는다. 맨 앞의 BOM은 뗀다. 줄바꿈은 바꾸지 않는다.

    UTF-8이 아니면 `InvalidFileError`다. 메시지는 `<root 기준 경로>:<줄>: …`이고, 줄은
    처음으로 읽지 못한 바이트가 든 줄이다.
    """
    raw = path.read_bytes()
    data = raw.removeprefix(codecs.BOM_UTF8)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        # 위치는 BOM을 뗀 바이트 기준이다. 줄도 같은 바이트에서 센다
        line = data.count(b"\n", 0, error.start) + 1
        raise InvalidFileError(
            f"{display_path(path, root)}:{line}: UTF-8 글로 읽을 수 없습니다"
        ) from None


def _load(path: Path, root: Path) -> tuple[str, Any]:
    """파일을 UTF-8 글로 읽고 YAML로 푼다. 어느 쪽이든 실패하면 `InvalidFileError`다."""
    text = read_utf8(path, root=root)
    try:
        return text, yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise InvalidFileError(f"{display_path(path, root)}:{_yaml_error(error)}") from None
    except ValueError:
        # PyYAML은 없는 날짜·시각(예: 2026-02-30)을 YAMLError가 아닌 ValueError로 낸다.
        # 위치를 알려 주지 않으므로 1번째 줄로 쓰고, 받은 값은 쓰지 않는다
        raise InvalidFileError(
            f"{display_path(path, root)}:1: YAML 문법이 틀렸습니다: "
            "값으로 읽을 수 없는 날짜나 시각이 있습니다"
        ) from None


def _yaml_error(error: yaml.YAMLError) -> str:
    """YAML 문법 오류를 `<줄>: <설명>`으로 쓴다. 줄은 PyYAML이 알려 준 문제의 줄이다."""
    if not isinstance(error, yaml.MarkedYAMLError):
        return f"1: YAML 문법이 틀렸습니다: {error}"
    mark = error.problem_mark or error.context_mark
    line = mark.line + 1 if mark is not None else 1
    text = f"{line}: YAML 문법이 틀렸습니다: {error.problem or error.context or error}"
    if error.problem and error.context and error.context_mark is not None:
        text += f" ({error.context}: {error.context_mark.line + 1}번째 줄)"
    return text


def display_path(path: Path, root: Path) -> str:
    """메시지와 결과에 쓰는 경로: `root` 기준 POSIX 경로. `root` 밖이면 받은 경로 그대로다."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _line_map(text: str) -> dict[Loc, int]:
    """YAML 노드 트리에서 매핑 키와 목록 항목마다 1부터 센 줄 번호를 모은다."""
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return {}
    if node is None:
        return {}
    lines: dict[Loc, int] = {}
    seen: set[int] = set()
    stack: list[tuple[Loc, yaml.Node, int]] = [((), node, node.start_mark.line + 1)]
    while stack:
        loc, node, line = stack.pop()
        lines.setdefault(loc, line)
        if id(node) in seen:  # 별칭(`*a`)으로 같은 노드를 다시 만났다
            continue
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if isinstance(key, yaml.ScalarNode):
                    stack.append(((*loc, key.value), value, key.start_mark.line + 1))
        elif isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                stack.append(((*loc, index), item, item.start_mark.line + 1))
    return lines


def _line_of(lines: Mapping[Loc, int], loc: Loc) -> int:
    for end in range(len(loc), -1, -1):
        line = lines.get(loc[:end])
        if line is not None:
            return line
    return 1


def _problems(
    error: ValidationError, *, list_file: bool, show_values: bool = True
) -> list[Problem]:
    problems = []
    for detail in error.errors():
        loc: Loc = tuple(detail["loc"])
        field_loc = loc[1:] if list_file and loc and isinstance(loc[0], int) else loc
        text = _describe(detail, show_values=show_values)
        problems.append(Problem(loc=loc, text=text, field=_field_name(field_loc)))
    return problems


_TYPE_TEXT = {
    "string_type": "글이어야 합니다",
    "int_type": "정수여야 합니다",
    "int_parsing": "정수여야 합니다",
    "int_from_float": "정수여야 합니다",
    "float_type": "수여야 합니다",
    "float_parsing": "수여야 합니다",
    "bool_type": "true나 false여야 합니다",
    "bool_parsing": "true나 false여야 합니다",
    "list_type": "목록이어야 합니다",
    "dict_type": "매핑(키: 값)이어야 합니다",
    "model_type": "매핑(키: 값)이어야 합니다",
    "model_attributes_type": "매핑(키: 값)이어야 합니다",
    "date_type": "날짜(YYYY-MM-DD)여야 합니다",
    "date_parsing": "날짜(YYYY-MM-DD)여야 합니다",
    "date_from_datetime_parsing": "날짜(YYYY-MM-DD)여야 합니다",
    "date_from_datetime_inexact": "날짜(YYYY-MM-DD)여야 합니다",
}
"""pydantic 형식 오류의 종류 -> 한국어 설명."""

_SHOWN_CHARS = 60
"""메시지에 보이는 받은 값의 최대 글자 수."""


def _describe(detail: ErrorDetails, *, show_values: bool = True) -> str:
    """pydantic 오류 하나를 한국어로 옮긴다. 옮길 줄 모르는 오류는 원문을 쓴다.

    `show_values`가 거짓이면 `(받은 값: …)`을 붙이지 않는다.
    """
    kind = detail["type"]
    ctx = detail.get("ctx") or {}
    received = f"(받은 값: {_shown(detail['input'])})" if show_values else ""
    if kind == "missing":
        return "꼭 있어야 하는 필드가 없습니다"
    if kind == "literal_error":
        allowed = ", ".join(re.split(r", | or ", str(ctx.get("expected", ""))))
        return f"쓸 수 있는 값은 {allowed}입니다{received}"
    if kind in ("value_error", "assertion_error") and "error" in ctx:
        return str(ctx["error"])
    if kind in _TYPE_TEXT:
        return f"{_TYPE_TEXT[kind]}{received}"
    return detail["msg"]


def _shown(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = repr(value)
    return text if len(text) <= _SHOWN_CHARS else text[:_SHOWN_CHARS] + "…"


def _field_name(loc: Loc) -> str:
    """`("decision_points", 1, "weight")` -> `decision_points[1].weight`."""
    name = ""
    for part in loc:
        if isinstance(part, int):
            name += f"[{part}]"
        else:
            name += f".{part}" if name else part
    return name
