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


def _request(value) -> dict:
    if type(value) is not dict or set(value) != _REQUEST_KEYS or value["schema"] != REQUEST_SCHEMA:
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
            else:
                result, output = extract_docx_text(data)
            deadline.require(dispatch_effect="outcome_unknown")
        except CodecRefusal as refusal:
            self._answer(connection, message_id, deadline=deadline, code=refusal.code,
                         page_count=refusal.page_count)
            return refusal.code
        self._answer(connection, message_id, deadline=deadline, result=result, output=output)
        return "ok"


__all__ = ["DEFAULT_EDGE_PX", "DocumentCodecService", "extract_docx_text", "render_pdf_page"]
