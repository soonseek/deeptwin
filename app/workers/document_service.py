"""The document service's codec engine (worker side of `cp-document`, T045).

This is the only module that opens a PDF or a DOCX, and it runs only inside the document
service process (`app.workers.document_worker_main`, identity 20106, no network, its own
memory/pid limits): never in the control plane. One authenticated connection carries one
request; every input and output is bounded and every failure answers a closed code —
nothing is invented to stand in for a page or a text the codec could not produce.

- PDF (`render_page`): pypdfium2 opens the bytes (an encrypted or damaged file is
  `content_rejected`), the page number is checked against the real page count
  (`page_out_of_range`, which reports that count), the page is rasterized with its
  longest edge at most `max_edge_px` (never upscaled past 4x) and encoded as a PNG that
  is then reopened with Pillow and checked for the exact pixel size before it is sent.
  PDFium here has no JavaScript engine; actions, links, forms and annotations are never
  run and are disclosed as omitted by the control plane.
- DOCX (`extract_text`): the zip container is checked first (entry count, total
  uncompressed size, compression ratio, `word/document.xml` present) so python-docx never
  inflates an archive bomb; body paragraphs and table-cell text are read in document
  order, at most `MAX_TEXT_BYTES` of UTF-8 (cut on a character boundary, `truncated`).
- PDF (`extract_pdf_text`, T074): each page's text layer read one PDFium character index
  at a time (so an index names the same character a redaction box covers), pages joined
  by a form feed, at most `MAX_PDF_TEXT_BYTES` (whole pages only, `truncated`).
- PDF (`redact_pdf`, T074): every page rasterized at 144 dpi, each named character range
  painted over with an opaque box, and a NEW PDF written from those images alone by
  Pillow with no metadata — no text layer, links, forms, attachments or info survive. A
  rotated page, an oversized page or more than `MAX_REDACT_PAGES` is refused rather than
  approximated. The copy is reopened: it must have the same page count, zero text
  characters and every painted box dark when re-rendered, or nothing is answered. This is
  a raster redaction, not an overlay: the covered glyphs are not in the copy at all.
"""

from __future__ import annotations

import io
import zipfile
from hashlib import sha256
from uuid import uuid4

from . import broker
from .document_channel import (
    DEFAULT_EDGE_PX,
    INPUT_TYPE,
    MAX_EDGE_PX,
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    MAX_PAGES,
    MAX_PDF_TEXT_BYTES,
    MAX_RANGE_CHARS,
    MAX_REDACT_PAGES,
    MAX_REDACT_RANGES,
    MAX_TEXT_BYTES,
    MIN_EDGE_PX,
    OPERATIONS,
    OUTPUT_TYPE,
    REQUEST_SCHEMA,
    REQUEST_TYPE,
    RESULT_SCHEMA,
    RESULT_TYPE,
    canonical,
    chunk_count,
    read_chunks,
    strict_object,
    write_chunks,
)

MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_UNCOMPRESSED = 64 * 1024 * 1024
MAX_ZIP_RATIO = 200
MAX_UPSCALE = 4.0
REDACTION_SCALE = 2.0  # 144 dpi
REDACTION_MAX_PAGE_PT = 2_000
REDACTION_PAD_PX = 2
REDACTION_DARKNESS = 48  # mean luminance (0-255) a painted box must stay at or below
_REQUEST_KEYS = {"schema", "op", "format", "page", "max_edge_px", "input_bytes", "input_sha256",
                 "chunk_count"}


class CodecRefusal(Exception):
    def __init__(self, code, *, page_count=None):
        super().__init__(code)
        self.code = code
        self.page_count = page_count


def render_pdf_page(data: bytes, page: int, max_edge_px: int) -> tuple[dict, bytes]:
    import pypdfium2 as pdfium
    from PIL import Image

    try:
        document = pdfium.PdfDocument(data)
    except Exception:  # noqa: BLE001 - damaged, encrypted or not a PDF at all
        raise CodecRefusal("content_rejected") from None
    try:
        count = len(document)
        if not 1 <= count <= MAX_PAGES:
            raise CodecRefusal("content_rejected")
        if not 1 <= page <= count:
            raise CodecRefusal("page_out_of_range", page_count=count)
        try:
            handle = document[page - 1]
            width_pt, height_pt = handle.get_size()
            if not (0 < width_pt <= 200_000 and 0 < height_pt <= 200_000):
                raise CodecRefusal("content_rejected")
            scale = min(max_edge_px / max(width_pt, height_pt), MAX_UPSCALE)
            image = handle.render(scale=scale).to_pil().convert("RGB")
            handle.close()
        except CodecRefusal:
            raise
        except Exception:  # noqa: BLE001 - the page could not be rasterized
            raise CodecRefusal("render_failed") from None
        # rounding may overshoot by one pixel: the bound is the contract, not the scale
        if max(image.size) > max_edge_px:
            ratio = max_edge_px / max(image.size)
            image = image.resize((max(1, int(image.size[0] * ratio)), max(1, int(image.size[1] * ratio))))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png = buffer.getvalue()
        if len(png) > MAX_OUTPUT_BYTES:
            raise CodecRefusal("too_large")
        with Image.open(io.BytesIO(png)) as reopened:  # the produced file, not the intent
            reopened.verify()
        with Image.open(io.BytesIO(png)) as reopened:
            if reopened.format != "PNG" or reopened.size != image.size:
                raise CodecRefusal("render_failed")
        return ({"page": page, "page_count": count, "width": image.size[0], "height": image.size[1],
                 "page_width_pt": max(1, round(width_pt)), "page_height_pt": max(1, round(height_pt))},
                png)
    finally:
        document.close()


def _guard_docx(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise CodecRefusal("content_rejected") from None
    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise CodecRefusal("content_rejected")
        total = sum(entry.file_size for entry in entries)
        if total > MAX_ZIP_UNCOMPRESSED or total > MAX_ZIP_RATIO * max(len(data), 1):
            raise CodecRefusal("content_rejected")
        if any(entry.flag_bits & 0x1 for entry in entries):  # encrypted members
            raise CodecRefusal("content_rejected")
        if "word/document.xml" not in {entry.filename for entry in entries}:
            raise CodecRefusal("media_unsupported")  # a zip, but not a word-processing document


def extract_docx_text(data: bytes) -> tuple[dict, bytes]:
    _guard_docx(data)
    from docx import Document
    from docx.table import Table

    try:
        document = Document(io.BytesIO(data))
        blocks = list(document.iter_inner_content())
    except Exception:  # noqa: BLE001 - malformed parts or relationships
        raise CodecRefusal("content_rejected") from None
    lines, paragraphs, tables, cells = [], 0, 0, 0
    for block in blocks:
        if isinstance(block, Table):
            tables += 1
            for row in block.rows:
                texts = [cell.text for cell in row.cells]
                cells += len(texts)
                lines.append("\t".join(texts))
        else:
            paragraphs += 1
            lines.append(block.text)
    encoded = "\n".join(lines).encode("utf-8")
    truncated = len(encoded) > MAX_TEXT_BYTES
    if truncated:
        encoded = encoded[:MAX_TEXT_BYTES]
        while encoded:
            try:
                encoded.decode("utf-8")
                break
            except UnicodeDecodeError:
                encoded = encoded[:-1]
    return {"paragraphs": paragraphs, "tables": tables, "table_cells": cells, "truncated": truncated}, encoded


def _pdf_text_layer(textpage) -> str:
    """The page's text with exactly one character per PDFium character index, so an index
    in this text names the same character the redaction boxes; a form feed (the page
    separator) or an unmapped code point is replaced, never dropped."""

    import pypdfium2_raw as raw

    characters = []
    for index in range(textpage.count_chars()):
        code = raw.FPDFText_GetUnicode(textpage.raw, index)
        characters.append(" " if code == 0x0C else chr(code) if 0 < code <= 0x10FFFF
                          and not 0xD800 <= code <= 0xDFFF else "�")
    return "".join(characters)


def _open_pdf(data: bytes):
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(data)
    except Exception:  # noqa: BLE001 - damaged, encrypted or not a PDF at all
        raise CodecRefusal("content_rejected") from None
    count = len(document)
    if not 1 <= count <= MAX_PAGES:
        document.close()
        raise CodecRefusal("content_rejected")
    return document, count


def extract_pdf_text(data: bytes) -> tuple[dict, bytes]:
    document, count = _open_pdf(data)
    try:
        texts, size, truncated = [], 0, False
        for number in range(count):
            try:
                page = document[number]
                textpage = page.get_textpage()
                text = _pdf_text_layer(textpage)
                textpage.close()
                page.close()
            except Exception:  # noqa: BLE001 - a page whose text layer cannot be read
                raise CodecRefusal("content_rejected") from None
            encoded = len(text.encode("utf-8")) + (1 if texts else 0)
            if size + encoded > MAX_PDF_TEXT_BYTES:
                truncated = True  # later pages are not claimed as read
                break
            texts.append(text)
            size += encoded
        return {"page_count": count, "truncated": truncated}, "\f".join(texts).encode("utf-8")
    finally:
        document.close()


def _dark(image, box) -> bool:
    left, top, right, bottom = box
    region = image.crop((left, top, right, bottom)).convert("L")
    pixels = region.tobytes()
    return bool(pixels) and sum(pixels) / len(pixels) <= REDACTION_DARKNESS


def redact_pdf(data: bytes, ranges) -> tuple[dict, bytes]:
    """A new, image-only PDF: each page rasterized, every named character range painted
    over with an opaque box, then re-encoded by Pillow's PDF writer with no metadata. The
    result is reopened and must have the same page count, no text at all and every box
    dark, or nothing is answered."""

    from PIL import ImageDraw

    document, count = _open_pdf(data)
    try:
        if count > MAX_REDACT_PAGES:
            raise CodecRefusal("too_large")
        by_page = {}
        for page_number, start, length in ranges:
            if page_number > count:
                raise CodecRefusal("page_out_of_range", page_count=count)
            by_page.setdefault(page_number, []).append((start, length))
        images, scales, boxes = [], [], []
        for number in range(1, count + 1):
            try:
                page = document[number - 1]
                width_pt, height_pt = page.get_size()
                if not (0 < width_pt <= REDACTION_MAX_PAGE_PT and 0 < height_pt <= REDACTION_MAX_PAGE_PT):
                    raise CodecRefusal("content_rejected")
                if page.get_rotation() != 0:
                    raise CodecRefusal("content_rejected")  # char boxes are unrotated page space
                scale = REDACTION_SCALE  # one resolution for every page of the copy
                left0, _bottom0, _right0, top0 = page.get_cropbox()
                page_boxes = []
                if number in by_page:
                    textpage = page.get_textpage()
                    total = textpage.count_chars()
                    for start, length in by_page[number]:
                        if start + length > total:
                            raise CodecRefusal("invalid_request")
                        for index in range(start, start + length):
                            left, bottom, right, top = textpage.get_charbox(index, loose=True)
                            if right <= left or top <= bottom:
                                continue  # a generated character (a space, a line break) has no glyph
                            page_boxes.append((
                                max(0, int((left - left0) * scale) - REDACTION_PAD_PX),
                                max(0, int((top0 - top) * scale) - REDACTION_PAD_PX),
                                int((right - left0) * scale) + 1 + REDACTION_PAD_PX,
                                int((top0 - bottom) * scale) + 1 + REDACTION_PAD_PX))
                    textpage.close()
                image = page.render(scale=scale, may_draw_forms=False).to_pil().convert("RGB")
                page.close()
            except CodecRefusal:
                raise
            except Exception:  # noqa: BLE001 - the page could not be rasterized
                raise CodecRefusal("render_failed") from None
            clipped = []
            draw = ImageDraw.Draw(image)
            for left, top, right, bottom in page_boxes:
                box = (left, top, min(right, image.size[0]), min(bottom, image.size[1]))
                if box[2] > box[0] and box[3] > box[1]:
                    draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=(0, 0, 0))
                    clipped.append(box)
            images.append(image)
            scales.append(scale)
            boxes.append(clipped)
        if not any(boxes):
            raise CodecRefusal("invalid_request")  # nothing to paint over is not a redaction
        buffer = io.BytesIO()
        # no title, author, producer or dates: the copy says nothing about the original
        images[0].save(buffer, format="PDF", save_all=True, append_images=images[1:],
                       resolution=72.0 * scales[0], title=None, author=None, subject=None,
                       keywords=None, creator=None, producer=None, creationDate=None, modDate=None)
        output = buffer.getvalue()
        if len(output) > MAX_OUTPUT_BYTES:
            raise CodecRefusal("too_large")
    finally:
        document.close()
    # the produced file, not the intent: reopened, no text layer, every box dark
    produced, produced_count = _open_pdf(output)
    try:
        if produced_count != count:
            raise CodecRefusal("render_failed")
        characters = 0
        for number in range(count):
            page = produced[number]
            textpage = page.get_textpage()
            characters += textpage.count_chars()
            textpage.close()
            width_pt, _height_pt = page.get_size()
            again = page.render(scale=images[number].size[0] / width_pt).to_pil().convert("RGB")
            page.close()
            if again.size != images[number].size:
                raise CodecRefusal("render_failed")
            if not all(_dark(again, box) for box in boxes[number]):
                raise CodecRefusal("render_failed")
        if characters != 0:
            raise CodecRefusal("render_failed")
    finally:
        produced.close()
    return ({"page_count": count, "boxes": sum(len(item) for item in boxes), "text_chars": 0,
             "verified": True}, output)


def _ranges(value) -> list:
    if (type(value) is not list or not 1 <= len(value) <= MAX_REDACT_RANGES
            or any(type(item) is not list or len(item) != 3 or any(type(part) is not int for part in item)
                   or not 1 <= item[0] <= MAX_REDACT_PAGES or item[1] < 0
                   or not 1 <= item[2] <= MAX_RANGE_CHARS for item in value)):
        raise CodecRefusal("invalid_request")
    return [tuple(item) for item in value]


def _request(value) -> dict:
    keys = _REQUEST_KEYS | ({"ranges"} if type(value) is dict and value.get("op") == "redact_pdf" else set())
    if type(value) is not dict or set(value) != keys or value["schema"] != REQUEST_SCHEMA:
        raise CodecRefusal("invalid_request")
    if value["op"] not in OPERATIONS or value["format"] != OPERATIONS[value["op"]]:
        raise CodecRefusal("media_unsupported")
    size = value["input_bytes"]
    if type(size) is not int or not 1 <= size <= MAX_INPUT_BYTES:
        raise CodecRefusal("too_large")
    if type(value["input_sha256"]) is not str or value["chunk_count"] != chunk_count(size):
        raise CodecRefusal("invalid_request")
    if value["op"] == "render_page":
        if (type(value["page"]) is not int or not 1 <= value["page"] <= MAX_PAGES
                or type(value["max_edge_px"]) is not int
                or not MIN_EDGE_PX <= value["max_edge_px"] <= MAX_EDGE_PX):
            raise CodecRefusal("invalid_request")
    elif value["page"] is not None or value["max_edge_px"] is not None:
        raise CodecRefusal("invalid_request")
    if value["op"] == "redact_pdf":
        value = {**value, "ranges": _ranges(value["ranges"])}
    return value


class DocumentCodecService:
    """Serves one request per authenticated connection."""

    def __init__(self, spec: broker.ChannelSpec) -> None:
        if type(spec) is not broker.ChannelSpec:
            raise TypeError("an exact channel spec is required")
        self.spec = spec

    def _answer(self, connection, message_id, *, deadline, result=None, output=b"", code=None,
                page_count=None) -> None:
        if code is not None:
            header = {"schema": RESULT_SCHEMA, "ok": False, "code": code}
            if page_count is not None:
                header["page_count"] = page_count
            connection.write(message_id=str(uuid4()), correlation_id=message_id, message_type=RESULT_TYPE,
                             payload=canonical(header), deadline=deadline)
            return
        header = {"schema": RESULT_SCHEMA, "ok": True, "result": result, "output_bytes": len(output),
                  "output_sha256": sha256(output).hexdigest(), "chunk_count": chunk_count(len(output))}
        connection.write(message_id=str(uuid4()), correlation_id=message_id, message_type=RESULT_TYPE,
                         payload=canonical(header), deadline=deadline)
        write_chunks(connection, output, message_type=OUTPUT_TYPE, correlation_id=message_id,
                     deadline=deadline)

    def serve_connection(self, connection, *, deadline: broker.Deadline) -> str:
        """One request, one answer. Returns the closed outcome (`ok` or the refusal code)."""

        from .gateway_connection import _require_connection

        _require_connection(connection)
        first = connection.read(deadline=deadline)
        if first.envelope.message_type != REQUEST_TYPE or first.envelope.correlation_id is not None:
            raise broker.ProtocolViolation()
        message_id = first.envelope.message_id
        try:
            try:
                value = strict_object(first.payload)
            except (ValueError, UnicodeDecodeError):
                raise CodecRefusal("invalid_request") from None
            size, count = value.get("input_bytes"), value.get("chunk_count")
            if (type(size) is not int or not 1 <= size <= MAX_INPUT_BYTES
                    or type(count) is not int or count != chunk_count(size)):
                raise CodecRefusal("too_large" if type(size) is int and size > MAX_INPUT_BYTES
                                   else "invalid_request")
            # the declared input is consumed before the request is judged, so a refusal
            # reaches a requester that is still writing its chunks
            try:
                data = read_chunks(connection, size=size, count=count,
                                   digest=value.get("input_sha256"), message_type=INPUT_TYPE,
                                   correlation_id=message_id, deadline=deadline)
            except ValueError:
                raise CodecRefusal("invalid_request") from None
            request = _request(value)
            if request["op"] == "render_page":
                result, output = render_pdf_page(data, request["page"], request["max_edge_px"])
            elif request["op"] == "extract_pdf_text":
                result, output = extract_pdf_text(data)
            elif request["op"] == "redact_pdf":
                result, output = redact_pdf(data, request["ranges"])
            else:
                result, output = extract_docx_text(data)
            deadline.require(dispatch_effect="outcome_unknown")
        except CodecRefusal as refusal:
            self._answer(connection, message_id, deadline=deadline, code=refusal.code,
                         page_count=refusal.page_count)
            return refusal.code
        self._answer(connection, message_id, deadline=deadline, result=result, output=output)
        return "ok"


__all__ = ["DEFAULT_EDGE_PX", "DocumentCodecService", "extract_docx_text", "extract_pdf_text", "redact_pdf",
           "render_pdf_page"]
