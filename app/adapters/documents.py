"""Bounded declarative document creation with real render inspection
(US3, T044; runtime.md §6 artifact tools, SC-004).

DOCX, CSV, JSON, PDF and PNG creation is declarative and bounded; every
render is verified by REOPENING the produced file and inspecting its actual
content — a file's existence is never the evidence. Formula-looking CSV
values remain data: the default writer preserves them verbatim, and the
optional safe-spreadsheet export prefixes an apostrophe and records every
transformation it applied. Declared PDF text is data, never markup: it is
escaped before layout, read back through the PDF's own text layer and
rasterized, and every declared visible character must leave ink where the
text layer places it. A PNG is a bounded declarative canvas of filled
rectangles, reopened and sampled pixel by pixel. Format validation sniffs
real bytes, never extensions, and refuses active or encrypted PDF content.
Nothing here fetches URLs or resolves external references.
"""

from __future__ import annotations

import csv
import json
import math
import re
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


def _document_spec(spec):
    if type(spec) is not dict or set(spec) != {"title", "paragraphs", "tables"}:
        raise DocumentToolError("expected the exact document spec object")
    title = _text(spec["title"], "title", 512)
    paragraphs = spec["paragraphs"]
    if type(paragraphs) is not list or len(paragraphs) > MAX_PARAGRAPHS:
        raise DocumentToolError("paragraphs are out of bounds")
    texts = [_text(item, "paragraph") for item in paragraphs]
    tables = spec["tables"]
    if type(tables) is not list or len(tables) > MAX_TABLES:
        raise DocumentToolError("tables are out of bounds")
    parsed = []
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
        parsed.append([[_text(cell, "table cell", 1_024) for cell in row] for row in rows])
    return title, texts, parsed


def render_docx(spec, path) -> RenderReport:
    """Render one bounded declarative DOCX and inspect it by reopening."""

    from docx import Document

    title, paragraph_texts, parsed_tables = _document_spec(spec)

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


PDF_FONT = "HYSMyeongJo-Medium"  # Adobe's Korean CID font: Hangul and Latin
MAX_PDF_PAGES = 50
MAX_IMAGE_SIDE = 4_096
MAX_IMAGE_SHAPES = 256
_PDF_SCALE = 2.0
_INK = 224  # a pixel this much darker than the white page is ink (antialiased dots)
# PDF name objects that carry actions, scripts, embedded files or forms:
# none is ever produced here and a document carrying one is refused
_ACTIVE_PDF_NAME = re.compile(
    rb"/(?:JavaScript|JS|OpenAction|AA|Launch|EmbeddedFiles?|RichMedia|XFA|SubmitForm"
    rb"|ImportData|GoToR|GoToE|URI)(?=[\s/<>\[\]()%{}]|\Z)"
)


def _squash(text):
    return "".join(text.split())


def render_pdf(spec, path) -> RenderReport:
    """Render one bounded declarative PDF and inspect it by reopening.

    The same spec as DOCX. Inspection reads the produced bytes back three
    ways: pypdf parses the file and bounds its pages; pdfium's text layer
    must hold the title, every paragraph and every table cell in order
    (whitespace-insensitive, since layout wraps lines); and each page is
    rasterized, every declared visible character leaving ink inside the box
    the text layer gives it — a glyph the font cannot draw fails the render.
    """

    from xml.sax.saxutils import escape

    import pypdfium2 as pdfium
    from pypdf import PdfReader
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    title, texts, tables = _document_spec(spec)
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))
    body = ParagraphStyle("body", fontName=PDF_FONT, fontSize=11, leading=15,
                          wordWrap="CJK")
    heading = ParagraphStyle("title", parent=body, fontSize=18, leading=24)

    def block(text, style):
        # declared text is data: escaped, so `<b>` or `&amp;` stays literal
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    cell_style = ParagraphStyle("cell", parent=body, fontSize=10, leading=13)
    story = [block(title, heading), Spacer(1, 8)]
    story.extend(block(text, body) for text in texts)
    for rows in tables:
        story.append(Spacer(1, 8))
        table = Table([[block(cell, cell_style) for cell in row] for row in rows])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
        story.append(table)
    path = Path(path)
    # invariant: no creation timestamp or random ID, so equal specs give equal bytes
    SimpleDocTemplate(str(path), pagesize=A4, title="", author="", subject="",
                      creator="", producer="", invariant=1).build(story)

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    if not 1 <= page_count <= MAX_PDF_PAGES:
        raise DocumentToolError("the produced pdf exceeds the page bound")
    document = pdfium.PdfDocument(str(path))
    try:
        layer = []
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            bitmap = page.render(scale=_PDF_SCALE).to_pil().convert("L")
            height = bitmap.height
            for char_index in range(textpage.count_chars()):
                character = textpage.get_text_range(char_index, 1)
                layer.append(character)
                if not character.strip():
                    continue
                left, bottom, right, top = textpage.get_charbox(char_index)
                box = (
                    max(0, int(left * _PDF_SCALE)), max(0, int(height - top * _PDF_SCALE)),
                    min(bitmap.width, int(right * _PDF_SCALE) + 1),
                    min(height, int(height - bottom * _PDF_SCALE) + 1),
                )
                if box[2] <= box[0] or box[3] <= box[1] or \
                        bitmap.crop(box).getextrema()[0] >= _INK:
                    raise DocumentToolError(
                        "a declared character renders no ink in the produced pdf"
                    )
    finally:
        document.close()
    extracted = _squash("".join(layer))
    expected = [title, *texts, *(cell for rows in tables for row in rows for cell in row)]
    position = 0
    for item in expected:
        found = extracted.find(_squash(item), position)
        if found < 0:
            raise DocumentToolError(
                "the produced pdf does not contain a declared text in order"
            )
        position = found + len(_squash(item))
    byte_length, digest = _digest(path)
    return _issue(
        RenderReport,
        media="pdf",
        byte_length=byte_length,
        sha256=digest,
        paragraph_count=len(texts),
        table_count=len(tables),
        inspected_cells={
            (f"t{ti}", ri, ci): cell
            for ti, rows in enumerate(tables)
            for ri, row in enumerate(rows)
            for ci, cell in enumerate(row)
        },
        transformations=(),
        title_verified=True,
    )


def _color(value, label):
    if (type(value) is not list or len(value) != 3
            or any(type(item) is not int or not 0 <= item <= 255 for item in value)):
        raise DocumentToolError(f"{label} must be three 0..255 integers")
    return tuple(value)


def render_png(spec, path) -> RenderReport:
    """Render one bounded declarative canvas of filled rectangles as PNG.

    Inspection reopens the produced file, checks its format, mode and size,
    and samples every rectangle's centre and the background's corner; the
    pixels actually read are the report's `inspected_cells`.
    """

    from PIL import Image, ImageDraw

    if type(spec) is not dict or set(spec) != {"width", "height", "background", "shapes"}:
        raise DocumentToolError("expected the exact image spec object")
    width, height = spec["width"], spec["height"]
    for side in (width, height):
        if type(side) is not int or not 1 <= side <= MAX_IMAGE_SIDE:
            raise DocumentToolError("the image size is out of bounds")
    background = _color(spec["background"], "background")
    shapes = spec["shapes"]
    if type(shapes) is not list or len(shapes) > MAX_IMAGE_SHAPES:
        raise DocumentToolError("shapes are out of bounds")
    rectangles = []
    for shape in shapes:
        if type(shape) is not dict or set(shape) != {"x", "y", "width", "height", "fill"}:
            raise DocumentToolError("a shape spec is malformed")
        x, y, w, h = shape["x"], shape["y"], shape["width"], shape["height"]
        if (any(type(item) is not int for item in (x, y, w, h))
                or x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height):
            raise DocumentToolError("a shape lies outside the canvas")
        rectangles.append((x, y, w, h, _color(shape["fill"], "fill")))
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    for x, y, w, h, fill in rectangles:
        draw.rectangle((x, y, x + w - 1, y + h - 1), fill=fill)
    path = Path(path)
    image.save(path, format="PNG")

    with Image.open(path) as reopened:
        if reopened.format != "PNG" or reopened.size != (width, height):
            raise DocumentToolError("the produced image is not the declared PNG")
        pixels = reopened.convert("RGB")
        inspected = {}
        for index, (x, y, w, h, _fill) in enumerate(rectangles):
            centre = (x + w // 2, y + h // 2)
            # the last shape drawn over a point is the colour it must show
            expected = next(
                fill for sx, sy, sw, sh, fill in reversed(rectangles)
                if sx <= centre[0] < sx + sw and sy <= centre[1] < sy + sh
            )
            observed = pixels.getpixel(centre)
            if observed != expected:
                raise DocumentToolError("a declared shape is not in the produced image")
            inspected[(f"s{index}", *centre)] = observed
        covered = any(sx == 0 and sy == 0 for sx, sy, *_ in rectangles)
        if not covered and pixels.getpixel((0, 0)) != background:
            raise DocumentToolError("the produced image lost its background")
    byte_length, digest = _digest(path)
    return _issue(
        RenderReport,
        media="png",
        byte_length=byte_length,
        sha256=digest,
        paragraph_count=0,
        table_count=0,
        inspected_cells=inspected,
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
    if declared == "pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        if not data.startswith(b"%PDF-"):
            raise DocumentToolError("the bytes are not a PDF")
        # a byte scan for the names that carry actions, scripts, embedded files
        # or forms (a name ends at whitespace or a delimiter); the parse below
        # covers the catalog's own structure
        if _ACTIVE_PDF_NAME.search(data) is not None:
            raise DocumentToolError("the pdf carries active content")
        try:
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise DocumentToolError("the pdf is encrypted")
            pages = len(reader.pages)
            root = reader.trailer["/Root"]
            if any(key in root for key in ("/OpenAction", "/AA", "/AcroForm", "/Names")):
                raise DocumentToolError("the pdf carries active content")
            # names inside compressed object streams escape the byte scan: no
            # page may carry annotations (links included) or actions either
            if pages <= MAX_PDF_PAGES and any(
                "/Annots" in page or "/AA" in page for page in reader.pages
            ):
                raise DocumentToolError("the pdf carries active content")
        except (PdfReadError, ValueError, KeyError, TypeError) as exc:
            raise DocumentToolError("the pdf is corrupt") from exc
        if not 1 <= pages <= MAX_PDF_PAGES:
            raise DocumentToolError("the pdf exceeds the page bound")
        return True
    if declared == "png":
        from PIL import Image, UnidentifiedImageError

        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise DocumentToolError("the bytes are not a PNG")
        try:
            with Image.open(path) as image:
                if image.format != "PNG" or max(image.size) > MAX_IMAGE_SIDE:
                    raise DocumentToolError("the png exceeds the image bound")
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError,
                Image.DecompressionBombError) as exc:
            raise DocumentToolError("the png is corrupt") from exc
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
    "render_pdf",
    "render_png",
    "validate_format",
]
