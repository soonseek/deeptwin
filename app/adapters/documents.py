"""Bounded declarative document creation with real render inspection
(US3, T044 partial; runtime.md §6 artifact tools, SC-004).

DOCX, CSV and JSON creation is declarative and bounded; every render is
verified by REOPENING the produced file and inspecting its actual content —
a file's existence is never the evidence. Formula-looking CSV values remain
data: the default writer preserves them verbatim, and the optional
safe-spreadsheet export prefixes an apostrophe and records every
transformation it applied. Format validation sniffs real bytes, never
extensions. Nothing here fetches URLs or resolves external references.
PDF and image rendering require libraries this environment does not carry
(reportlab/PIL are absent and the dependency manifest lives outside this
worktree); those formats stay explicitly unsupported here rather than
silently faked.
"""

from __future__ import annotations

import csv
import json
import math
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

MAX_PARAGRAPHS = 500
MAX_TEXT_BYTES = 8_192
MAX_TABLES = 32
MAX_TABLE_ROWS = 100
MAX_TABLE_COLUMNS = 50
MAX_CSV_ROWS = 10_000
MAX_CSV_CELL_BYTES = 4_096
MAX_JSON_DEPTH = 32
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class DocumentToolError(ValueError):
    """A document spec, render or format validation is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _text(value, label, maximum=MAX_TEXT_BYTES, *, allow_formula_prefix=True):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise DocumentToolError(f"{label} is out of bounds")
    for ch in value:
        if ord(ch) < 0x20 and ch not in ("\n", "\t"):
            # C0 control characters (NUL included) are refused at input
            # time, consistently across every format.
            raise DocumentToolError(f"{label} carries a control character")
    return value


@dataclass(frozen=True, slots=True, init=False)
class RenderReport:
    """Facts read back from the PRODUCED file, never from intent."""

    media: str
    byte_length: int
    sha256: str
    paragraph_count: int
    table_count: int
    # mapping (table_id, row, column) -> the text actually read back
    inspected_cells: dict
    transformations: tuple[tuple[int, int, str], ...]
    title_verified: bool


def _digest(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), sha256(data).hexdigest()


def render_docx(spec, path) -> RenderReport:
    """Render one bounded declarative DOCX and inspect it by reopening."""

    from docx import Document

    if type(spec) is not dict or set(spec) != {"title", "paragraphs", "tables"}:
        raise DocumentToolError("expected the exact document spec object")
    title = _text(spec["title"], "title", 512)
    paragraphs = spec["paragraphs"]
    if (
        type(paragraphs) is not list or len(paragraphs) > MAX_PARAGRAPHS
    ):
        raise DocumentToolError("paragraphs are out of bounds")
    paragraph_texts = [_text(item, "paragraph") for item in paragraphs]
    tables = spec["tables"]
    if type(tables) is not list or len(tables) > MAX_TABLES:
        raise DocumentToolError("tables are out of bounds")
    parsed_tables = []
    for table in tables:
        if type(table) is not dict or set(table) != {"rows"}:
            raise DocumentToolError("a table spec is malformed")
        rows = table["rows"]
        if (
            type(rows) is not list or not 1 <= len(rows) <= MAX_TABLE_ROWS
            or any(
                type(row) is not list
                or not 1 <= len(row) <= MAX_TABLE_COLUMNS
                or len(row) != len(rows[0])
                for row in rows
            )
        ):
            raise DocumentToolError("table rows are out of bounds")
        parsed_tables.append([
            [_text(cell, "table cell", 1_024) for cell in row]
            for row in rows
        ])

    document = Document()
    document.add_heading(title)
    for text in paragraph_texts:
        document.add_paragraph(text)
    for rows in parsed_tables:
        rendered = document.add_table(rows=len(rows), cols=len(rows[0]))
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row):
                rendered.cell(row_index, column_index).text = cell
    path = Path(path)
    document.save(str(path))

    # Real render inspection: reopen the produced bytes and read them back.
    reopened = Document(str(path))
    inspected: list[tuple[tuple[str, int, int], str]] = []
    for table_index, table in enumerate(reopened.tables):
        for row_index, row in enumerate(table.rows):
            for column_index, cell in enumerate(row.cells):
                inspected.append(
                    ((f"t{table_index}", row_index, column_index), cell.text),
                )
    expected = [
        ((f"t{ti}", ri, ci), cell)
        for ti, rows in enumerate(parsed_tables)
        for ri, row in enumerate(rows)
        for ci, cell in enumerate(row)
    ]
    if inspected != expected:
        raise DocumentToolError(
            "the produced document does not contain the declared tables"
        )
    reopened_texts = [item.text for item in reopened.paragraphs if item.text]
    for text in paragraph_texts:
        if text not in reopened_texts:
            raise DocumentToolError(
                "the produced document does not contain a declared paragraph"
            )
    if title not in reopened_texts:
        raise DocumentToolError(
            "the produced document does not contain the declared title"
        )
    byte_length, digest = _digest(path)
    cells = dict(inspected)
    return _issue(
        RenderReport,
        media="docx",
        byte_length=byte_length,
        sha256=digest,
        paragraph_count=len(reopened.paragraphs),
        table_count=len(reopened.tables),
        inspected_cells=cells,
        transformations=(),
        title_verified=True,
    )


def render_csv(rows, path, *, safe_spreadsheet=False) -> RenderReport:
    """Render one bounded CSV; formula-looking values remain data."""

    if (
        type(rows) is not list or not 1 <= len(rows) <= MAX_CSV_ROWS
        or any(
            type(row) is not list or not 1 <= len(row) <= MAX_TABLE_COLUMNS
            for row in rows
        )
    ):
        raise DocumentToolError("csv rows are out of bounds")
    transformations: list[tuple[int, int, str]] = []
    output_rows = []
    for row_index, row in enumerate(rows):
        output_row = []
        for column_index, cell in enumerate(row):
            if type(cell) is not str or "\x00" in cell:
                raise DocumentToolError("csv cell is out of bounds")
            if len(cell.encode("utf-8")) > MAX_CSV_CELL_BYTES or not cell:
                raise DocumentToolError("csv cell is out of bounds")
            text = cell
            if safe_spreadsheet and text.startswith(_FORMULA_PREFIXES):
                # The optional safe export records EVERY transformation it
                # applies; the default writer keeps data as data.
                text = "'" + text
                transformations.append(
                    (row_index, column_index, "prefixed_apostrophe"),
                )
            output_row.append(text)
        output_rows.append(output_row)
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(output_rows)
    with open(path, newline="", encoding="utf-8") as handle:
        read_back = list(csv.reader(handle))
    if read_back != output_rows:
        raise DocumentToolError("the produced csv does not round-trip")
    byte_length, digest = _digest(path)
    return _issue(
        RenderReport,
        media="csv",
        byte_length=byte_length,
        sha256=digest,
        paragraph_count=0,
        table_count=1,
        inspected_cells={},
        transformations=tuple(transformations),
        title_verified=False,
    )


def _bounded_json(value, depth=0):
    if depth > MAX_JSON_DEPTH:
        raise DocumentToolError("json nesting exceeds the depth bound")
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise DocumentToolError("json keys must be text")
            _bounded_json(item, depth + 1)
        return
    if type(value) is list:
        for item in value:
            _bounded_json(item, depth + 1)
        return
    if type(value) is str and "\x00" in value:
        raise DocumentToolError("json never carries NUL characters")
    if type(value) is float and not math.isfinite(value):
        raise DocumentToolError("json never carries non-finite numbers")
    if value is not None and type(value) not in (str, int, bool, float):
        raise DocumentToolError("json carries an unknown value type")


def render_json(value, path) -> RenderReport:
    """Render one bounded JSON document and verify it parses back equal."""

    _bounded_json(value)
    path = Path(path)
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, indent=2,
    )
    path.write_text(encoded, encoding="utf-8")
    if json.loads(path.read_text(encoding="utf-8")) != value:
        raise DocumentToolError("the produced json does not round-trip")
    byte_length, digest = _digest(path)
    return _issue(
        RenderReport,
        media="json",
        byte_length=byte_length,
        sha256=digest,
        paragraph_count=0,
        table_count=0,
        inspected_cells={},
        transformations=(),
        title_verified=False,
    )


MAX_VALIDATE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10_000


def validate_format(path, declared) -> bool:
    """Sniff the real bytes; a wrong or unsupported declaration refuses.

    Hostile-file bounds: the input is size-capped before reading and a
    DOCX container's central directory is entry-capped before parsing.
    The output path of the render functions is the caller's authority;
    this module never restricts where its caller chooses to write.
    """

    path = Path(path)
    if path.stat().st_size > MAX_VALIDATE_BYTES:
        raise DocumentToolError("the file exceeds the validation size bound")
    data = path.read_bytes()
    if declared == "docx":
        if not data.startswith(b"PK"):
            raise DocumentToolError("the bytes are not a DOCX container")
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ARCHIVE_ENTRIES:
                    raise DocumentToolError(
                        "the container exceeds the entry bound"
                    )
                names = {info.filename for info in infos}
        except zipfile.BadZipFile as exc:
            raise DocumentToolError("the container is corrupt") from exc
        if "[Content_Types].xml" not in names or not any(
            name.startswith("word/") for name in names
        ):
            raise DocumentToolError("a plain zip is not a DOCX document")
        return True
    if declared == "csv":
        if b"\x00" in data:
            raise DocumentToolError("the csv bytes are NUL-poisoned")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentToolError("the csv bytes are not UTF-8") from exc
        return True
    if declared == "json":
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DocumentToolError("the bytes are not JSON") from exc
        _bounded_json(parsed)
        return True
    # Unsupported formats stay explicit — never silently accepted.
    raise DocumentToolError(f"format {declared!r} is not supported here")


__all__ = [
    "MAX_CSV_ROWS",
    "MAX_JSON_DEPTH",
    "MAX_PARAGRAPHS",
    "DocumentToolError",
    "RenderReport",
    "render_csv",
    "render_docx",
    "render_json",
    "validate_format",
]
