"""과거 작업물 가져오기: 폴더의 글 파일 하나를 본능 층의 예시 하나로 만든다(R16).

- 고르는 파일: 폴더 바로 아래의 `.txt`, `.md` 파일(확장자 대소문자 무관). 점으로 시작하는
  파일과 하위 폴더는 보지 않는다. 파일 이름순으로 가져온다.
- 글: UTF-8(BOM 허용)로 읽어 줄바꿈(`\\r\\n`, `\\r`, U+0085, U+2028, U+2029)을 `\\n`으로
  바꾸고 앞뒤 공백을 뗀 것이다.
- 예시: `kind: good`, `grade`는 대표작이면 `signature` 아니면 `usual`, `tags: {}`,
  `source: past_work`, `status: active`, `approval: human`(사람이 직접 가져왔다).
- 전부 아니면 전무다. 모든 파일을 먼저 읽고 검사한 뒤 저장 계층(`DeepTwin.add_examples`)이 한
  잠금 안에서 번호를 정하고 쓴다. 비었거나 UTF-8이 아닌 파일이 하나라도 있으면 아무것도 쓰지 않는다.

원장에는 쓰지 않는다. 모델을 부르지 않는다(`deeptwin.llm`을 import하지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from deeptwin.errors import InvalidFileError, NothingToImportError
from deeptwin.models import Example, Grade
from deeptwin.store.files import Problem, display_path, invalid_file, read_utf8
from deeptwin.store.project import DeepTwin

__all__ = [
    "TEXT_SUFFIXES",
    "import_folder",
]

TEXT_SUFFIXES: tuple[str, ...] = (".txt", ".md")
"""가져오는 글 파일의 확장자. 대소문자는 가리지 않는다."""

_LINE_BREAKS = ("\r\n", "\r", "\x85", "\u2028", "\u2029")
"""`\\n`으로 바꾸는 줄바꿈. `\\r\\n`을 `\\r`보다 먼저 바꾼다. YAML은 U+0085, U+2028, U+2029도
줄바꿈으로 읽으므로, 그대로 두면 다시 읽은 `text`가 달라져 다시 가져올 때 같은 글로 보지 못한다."""

_DRAFT_ID = "draft"
"""저장 계층에 넘기는 예시의 임시 ID. 저장 계층이 `ex-NNNN`으로 바꿔 쓴다."""


@dataclass(frozen=True)
class ImportedFile:
    """예시로 가져온 글 파일 하나."""

    file: Path
    example: Example
    """쓴 예시. `id`는 저장 계층이 새로 매긴 것이다."""


@dataclass(frozen=True)
class SkippedFile:
    """같은 글의 예시가 있어 건너뛴 글 파일 하나."""

    file: Path
    same_as: str
    """`text`가 같은 예시의 ID. 이미 있던 예시이거나 이번에 앞서 가져온 파일의 예시다."""


@dataclass(frozen=True)
class ImportResult:
    """`import_folder`의 결과. 둘 다 파일 이름순이다."""

    imported: tuple[ImportedFile, ...]
    skipped: tuple[SkippedFile, ...]


def import_folder(
    deeptwin: DeepTwin, folder: Path, *, skill: str, signature: bool = False
) -> ImportResult:
    """`folder` 바로 아래의 글 파일을 하나씩 스킬 `skill`의 예시로 가져온다.

    `signature`가 참이면 대표작(`grade: signature`)으로, 아니면 `grade: usual`로 쓴다.
    같은 스킬에 글이 같은 예시가 이미 있거나 이번에 앞서 가져온 파일과 같으면 만들지 않고
    `skipped`에 둔다. 그래서 같은 폴더를 다시 가져와도 예시가 늘지 않는다.

    - `skill_not_found`: 스킬이 없다.
    - `nothing_to_import`: 고를 글 파일이 없다.
    - `invalid_file`: 비었거나 UTF-8이 아닌 파일이 있다. 그런 파일마다 한 줄씩, 파일 이름순으로
      `<경로>:<줄>: <이유>`를 쓴다. 아무것도 쓰지 않는다.

    `folder`가 상대 경로면 지금 폴더 기준이다. 메시지의 경로는 프로젝트 루트 기준이다.
    """
    deeptwin.skill(skill)
    folder = folder.absolute()
    files = text_files(folder)
    if not files:
        suffixes = ", ".join(TEXT_SUFFIXES)
        raise NothingToImportError(
            f"가져올 글 파일이 없습니다: {display_path(folder, deeptwin.root)}. "
            f"폴더 바로 아래의 {suffixes} 파일을 가져옵니다"
            "(하위 폴더와 점으로 시작하는 파일은 보지 않습니다)."
        )
    texts: list[str] = []
    problems: list[str] = []
    for path in files:
        try:
            texts.append(read_past_work(path, root=deeptwin.root))
        except InvalidFileError as error:
            problems.append(error.message)
    if problems:
        raise InvalidFileError("\n".join(problems))
    grade: Grade = "signature" if signature else "usual"
    drafts = [
        Example(
            id=_DRAFT_ID,
            skill=skill,
            kind="good",
            grade=grade,
            text=text,
            tags={},
            source="past_work",
            status="active",
            approval="human",
        )
        for text in texts
    ]
    imported: list[ImportedFile] = []
    skipped: list[SkippedFile] = []
    for path, added in zip(files, deeptwin.add_examples(drafts), strict=True):
        if added.example is not None:
            imported.append(ImportedFile(file=path, example=added.example))
        else:
            skipped.append(SkippedFile(file=path, same_as=added.same_as or ""))
    return ImportResult(imported=tuple(imported), skipped=tuple(skipped))


def text_files(folder: Path) -> list[Path]:
    """`folder` 바로 아래의 글 파일(`TEXT_SUFFIXES`, 대소문자 무관)을 파일 이름순으로 돌려준다.

    점으로 시작하는 파일(macOS의 `._a.txt` 같은 것)과 하위 폴더는 뺀다.
    """
    return sorted(
        (
            p
            for p in folder.iterdir()
            if p.suffix.lower() in TEXT_SUFFIXES and not p.name.startswith(".") and p.is_file()
        ),
        key=lambda p: p.name,
    )


def read_past_work(path: Path, *, root: Path) -> str:
    """글 파일 하나를 예시의 글로 읽는다: UTF-8(BOM 허용), 줄바꿈(`_LINE_BREAKS`)은 `\\n`,
    앞뒤 공백을 뗀다.

    UTF-8이 아니면 읽지 못한 바이트가 든 줄을, 비었으면(공백뿐이어도) 1번째 줄을 가리키는
    `invalid_file`이다. 메시지의 경로는 `root` 기준이다.
    """
    text = read_utf8(path, root=root)
    for line_break in _LINE_BREAKS:
        text = text.replace(line_break, "\n")
    text = text.strip()
    if not text:
        # 글 파일이라 YAML로 줄을 찾지 않는다(빈 `text`를 주면 1번째 줄이다)
        raise invalid_file(
            path, root, [Problem((), "글이 비었습니다(공백뿐인 파일도 빈 글로 봅니다)")], text=""
        )
    return text
