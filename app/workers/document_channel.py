"""Control-plane side of the isolated document codec channel (`cp-document`, T045).

The control plane never parses a PDF or a DOCX: worker-produced documents are untrusted
input (runtime.md §6). It hands the original bytes of one artifact to the document
service — a separate process under its own identity (`document`, 20106:20106, pair group
21105, `network_mode: none` in deploy/compose.yaml) — over the verified pair-root
machinery the credential gateway uses (`ipc_root` generation, `listener` readiness record
and socket inode, SO_PEERCRED, boot-secret HMAC handshake, per-frame MACs), and receives
one bounded derived result:

- `render_page` (PDF): page N rasterized to a PNG whose longest edge is at most
  `max_edge_px`, with the page count, the pixel size and the page's size in points;
- `extract_text` (DOCX): the body paragraphs and table-cell text in document order,
  bounded, with the counts and the parts that were not extracted.

This module imports no parser (pypdfium2, pypdf, python-docx, Pillow) and no vault, route
or web code; `app.tests.test_document_codec` pins that. It checks what it can check
without parsing: the declared result shape, the output digest over the bytes actually
received, and — for a PNG — the signature and the IHDR size against the declared size.

Wire (one request per connection, both directions bounded):
  requester → `document_request` (canonical JSON header) + `document_input` × n (raw
  chunks of the original, each correlated to the header's message id);
  responder → `document_result` (canonical JSON header: `ok` + `result` + the output's
  byte count, digest and chunk count, or `ok: false` + a closed `code`) + `document_output`
  × m (raw chunks).
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ..deployment.contracts import CONTROL, IPC_ROOT
from . import broker
from .ipc_root import PairRootSpec

PROFILE_ID = "document-codec-channel-v1"
CHANNEL_ID = "cp-document"
PROTOCOL_ID = "document-codec-v1"
DOCUMENT_SERVICE = "document"
DOCUMENT_UID = 20_106
DOCUMENT_GID = 20_106
PAIR_GID = 21_105
SOCKET_NAME = "worker.sock"
REQUEST_TYPE = "document_request"
INPUT_TYPE = "document_input"
RESULT_TYPE = "document_result"
OUTPUT_TYPE = "document_output"
MAX_FRAME_BYTES = 65_536
MAX_OPERATION_MS = 30_000
CHUNK_BYTES = 32_768
MAX_HEADER_BYTES = 4_096
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_PAGES = 10_000
MIN_EDGE_PX = 64
MAX_EDGE_PX = 2_048
DEFAULT_EDGE_PX = 1_200
MAX_TEXT_BYTES = 65_536
REQUEST_SCHEMA = "document-codec-request-v1"
RESULT_SCHEMA = "document-codec-result-v1"
ATTACHMENT_SCHEMA = "deeptwin-document-worker-attachment-v1"
FORMATS = ("docx", "pdf")
OPERATIONS = {"render_page": "pdf", "extract_text": "docx"}
# closed codes a worker may answer; anything else is `malformed_result`
WORKER_CODES = frozenset({"invalid_request", "media_unsupported", "page_out_of_range",
                          "content_rejected", "render_failed", "too_large"})
CLIENT_CODES = WORKER_CODES | {"unavailable", "transport_failed", "malformed_result"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PDF_OMITTED = ("annotations_interactive", "links", "text_layer", "forms", "attachments")
DOCX_OMITTED = ("comments", "footnotes", "formatting", "headers_footers", "images",
                "text_boxes", "tracked_changes")
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")

__all__ = [
    "ATTACHMENT_SCHEMA", "DocumentCodecClient", "DocumentCodecError", "DocumentWorkerConfiguration",
    "PageRendering", "TextExtraction", "document_channel",
]


class DocumentCodecError(RuntimeError):
    """A closed, sanitized codec failure. `sent` is False only when nothing of the request
    left this process (the connection or the handshake failed)."""

    def __init__(self, code: str = "transport_failed", *, sent: bool = True, page_count=None):
        if code not in CLIENT_CODES:
            code = "malformed_result"
        super().__init__(code)
        self.code = code
        self.sent = sent is not False
        self.page_count = page_count if type(page_count) is int and 1 <= page_count <= MAX_PAGES else None


def document_channel() -> tuple[PairRootSpec, broker.ChannelSpec]:
    """The fixed pair root and channel of the document service, from nothing."""

    root = PairRootSpec(pair_root=IPC_ROOT / CHANNEL_ID, responder_uid=DOCUMENT_UID,
                        responder_gid=DOCUMENT_GID, pair_gid=PAIR_GID)
    spec = broker.ChannelSpec(
        channel_id=CHANNEL_ID,
        requester_service=CONTROL["service_identity"],
        responder_service=DOCUMENT_SERVICE,
        request_direction=f"{CONTROL['service_identity']}-to-{DOCUMENT_SERVICE}",
        protocol_id=PROTOCOL_ID,
        requester_uid=CONTROL["uid"],
        requester_gid=CONTROL["gid"],
        responder_uid=DOCUMENT_UID,
        responder_gid=DOCUMENT_GID,
        pair_gid=PAIR_GID,
        pair_root=root.endpoint_path,
        socket_name=SOCKET_NAME,
        root_uid=DOCUMENT_UID,
        root_gid=PAIR_GID,
        socket_uid=DOCUMENT_UID,
        socket_gid=PAIR_GID,
        requester_message_types=(INPUT_TYPE, REQUEST_TYPE),
        responder_message_types=(OUTPUT_TYPE, RESULT_TYPE),
        max_frame_bytes=MAX_FRAME_BYTES,
        max_in_flight=1,
        max_queue_depth=8,
        max_operation_ms=MAX_OPERATION_MS,
    )
    return root, spec


@dataclass(frozen=True, slots=True)
class DocumentWorkerConfiguration:
    """The deployment's nonsecret naming of the document service endpoint; both sides
    read the same object (`app.server --document-worker-config`,
    `app.workers.document_worker_main --attachment-config`)."""

    pair_root: str
    requester_boot_id: str

    def __post_init__(self):
        if (type(self.pair_root) is not str or not 1 <= len(self.pair_root.encode("utf-8")) <= 4096
                or not self.pair_root.startswith("/") or ".." in Path(self.pair_root).parts):
            raise ValueError("document worker pair root is invalid")
        if type(self.requester_boot_id) is not str or _BOOT_ID.fullmatch(self.requester_boot_id) is None:
            raise ValueError("document worker requester boot id is invalid")

    @classmethod
    def from_mapping(cls, value) -> DocumentWorkerConfiguration:
        if type(value) is not dict or set(value) != {"schema", "pair_root", "requester_boot_id"}:
            raise ValueError("document worker configuration is not the exact attachment object")
        if value["schema"] != ATTACHMENT_SCHEMA:
            raise ValueError("document worker configuration schema is unsupported")
        return cls(pair_root=value["pair_root"], requester_boot_id=value["requester_boot_id"])


# --- the shared wire grammar (both sides) -------------------------------------------

def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _no_duplicates(pairs):
    result = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = item
    return result


def _reject_float(_text):
    raise ValueError("floats are not part of the grammar")


def strict_object(raw: bytes) -> dict:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_HEADER_BYTES:
        raise ValueError("header is out of bounds")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                       parse_float=_reject_float, parse_constant=_reject_float)
    if type(value) is not dict or canonical(value) != raw:
        raise ValueError("header is not canonical")
    return value


def chunk_count(size: int) -> int:
    return 0 if size == 0 else (size + CHUNK_BYTES - 1) // CHUNK_BYTES


def write_chunks(connection, data: bytes, *, message_type, correlation_id, deadline) -> None:
    for index in range(chunk_count(len(data))):
        connection.write(message_id=str(uuid4()), correlation_id=correlation_id,
                         message_type=message_type,
                         payload=data[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES], deadline=deadline)


def read_chunks(connection, *, size, count, digest, message_type, correlation_id, deadline) -> bytes:
    if type(size) is not int or type(count) is not int or count != chunk_count(size):
        raise ValueError("chunk declaration is inconsistent")
    data, seen = bytearray(), set()
    for index in range(count):
        frame = connection.read(deadline=deadline)
        expected = CHUNK_BYTES if index < count - 1 else size - index * CHUNK_BYTES
        if (frame.envelope.message_type != message_type
                or frame.envelope.correlation_id != correlation_id
                or frame.envelope.message_id in seen or len(frame.payload) != expected):
            raise ValueError("chunk is not bound")
        seen.add(frame.envelope.message_id)
        data.extend(frame.payload)
    data = bytes(data)
    if len(data) != size or sha256(data).hexdigest() != digest:
        raise ValueError("chunk digest mismatch")
    return data


# --- results ------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PageRendering:
    png: bytes
    sha256: str
    page: int
    page_count: int
    width: int
    height: int
    page_width_pt: int
    page_height_pt: int
    max_edge_px: int


@dataclass(frozen=True, slots=True)
class TextExtraction:
    text: str
    sha256: str
    paragraphs: int
    tables: int
    table_cells: int
    truncated: bool


def _bounded_int(value, low, high) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("result integer is out of bounds")
    return value


def _png_size(data: bytes) -> tuple[int, int]:
    """The IHDR width and height: fixed offsets, never a decode."""

    if (len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR"
            or data[8:12] != b"\x00\x00\x00\r"):
        raise ValueError("output is not a PNG")
    return struct.unpack(">II", data[16:24])


class DocumentCodecClient:
    """The control plane's frame-only client; never sees a parser."""

    __slots__ = ("_connect", "_deadline_ms", "_transport_factory")

    def __init__(self, transport_factory=None, *, deadline_ms: int = 20_000, _connect=None) -> None:
        if _connect is None and not callable(transport_factory):
            raise TypeError("a transport factory is required")
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= MAX_OPERATION_MS:
            raise ValueError("client deadline is out of bounds")
        self._transport_factory = transport_factory
        self._deadline_ms = deadline_ms
        self._connect = _connect

    @classmethod
    def for_worker(cls, configuration, *, deadline_ms: int = 20_000) -> DocumentCodecClient:
        """The fixed client over the `cp-document` profile: each call runs the listener's
        verified connect and the authenticated handshake under its own deadline."""

        from . import listener

        if type(configuration) is not DocumentWorkerConfiguration:
            raise TypeError("an exact document worker configuration is required")
        root, _spec = document_channel()
        if Path(configuration.pair_root) != root.pair_root:
            raise ValueError("document worker endpoint is not the verified pair root")
        boot = configuration.requester_boot_id

        def connect(deadline):
            fixed_root, spec = document_channel()
            try:
                return listener.connect_authenticated(fixed_root, spec, requester_boot_id=boot,
                                                      deadline=deadline)
            except listener.ListenerError as error:
                raise DocumentCodecError("unavailable", sent=False) from error

        return cls(None, deadline_ms=deadline_ms, _connect=connect)

    def _open(self, deadline):
        if self._connect is not None:
            return self._connect(deadline)
        from .gateway_connection import _RawConnection

        sock, codec = self._transport_factory()
        return _RawConnection(sock, codec, owns_socket=True)

    def _call(self, header: dict, data: bytes):
        if type(data) is not bytes or not 1 <= len(data) <= MAX_INPUT_BYTES:
            raise DocumentCodecError("too_large", sent=False)
        deadline = broker.Deadline.after_ms(self._deadline_ms)
        try:
            connection = self._open(deadline)
        except DocumentCodecError:
            raise
        except (broker.BrokerError, OSError, ValueError) as error:
            raise DocumentCodecError("unavailable", sent=False) from error
        try:
            message_id = str(uuid4())
            request = {**header, "schema": REQUEST_SCHEMA, "input_bytes": len(data),
                       "input_sha256": sha256(data).hexdigest(), "chunk_count": chunk_count(len(data))}
            connection.write(message_id=message_id, correlation_id=None, message_type=REQUEST_TYPE,
                             payload=canonical(request), deadline=deadline)
            write_chunks(connection, data, message_type=INPUT_TYPE, correlation_id=message_id,
                         deadline=deadline)
            first = connection.read(deadline=deadline)
            if (first.envelope.message_type != RESULT_TYPE
                    or first.envelope.correlation_id != message_id):
                raise DocumentCodecError("malformed_result")
            try:
                response = strict_object(first.payload)
            except ValueError:
                raise DocumentCodecError("malformed_result") from None
            if response.get("schema") != RESULT_SCHEMA or type(response.get("ok")) is not bool:
                raise DocumentCodecError("malformed_result")
            if response["ok"] is False:
                if set(response) - {"schema", "ok", "code", "page_count"} or response.get("code") not in WORKER_CODES:
                    raise DocumentCodecError("malformed_result")
                raise DocumentCodecError(response["code"], page_count=response.get("page_count"))
            if set(response) != {"schema", "ok", "result", "output_bytes", "output_sha256", "chunk_count"}:
                raise DocumentCodecError("malformed_result")
            size, digest = response["output_bytes"], response["output_sha256"]
            if (type(size) is not int or not 0 <= size <= MAX_OUTPUT_BYTES or type(digest) is not str
                    or _HEX64.fullmatch(digest) is None or type(response["result"]) is not dict):
                raise DocumentCodecError("malformed_result")
            try:
                output = read_chunks(connection, size=size, count=response["chunk_count"], digest=digest,
                                     message_type=OUTPUT_TYPE, correlation_id=message_id,
                                     deadline=deadline)
            except ValueError:
                raise DocumentCodecError("malformed_result") from None
            deadline.require()
            return response["result"], output, digest
        except DocumentCodecError:
            raise
        except broker.BrokerError as error:
            raise DocumentCodecError("transport_failed") from error
        except OSError as error:
            raise DocumentCodecError("transport_failed") from error
        finally:
            try:
                connection.close()
            except (broker.BrokerError, OSError):
                pass

    def render_page(self, data: bytes, *, page: int, max_edge_px: int = DEFAULT_EDGE_PX) -> PageRendering:
        if type(page) is not int or not 1 <= page <= MAX_PAGES:
            raise DocumentCodecError("invalid_request", sent=False)
        if type(max_edge_px) is not int or not MIN_EDGE_PX <= max_edge_px <= MAX_EDGE_PX:
            raise DocumentCodecError("invalid_request", sent=False)
        result, png, digest = self._call({"op": "render_page", "format": "pdf", "page": page,
                                          "max_edge_px": max_edge_px}, data)
        try:
            if set(result) != {"page", "page_count", "width", "height", "page_width_pt", "page_height_pt"}:
                raise ValueError("result shape")
            width, height = _png_size(png)
            rendering = PageRendering(
                png=png, sha256=digest, page=_bounded_int(result["page"], page, page),
                page_count=_bounded_int(result["page_count"], page, MAX_PAGES),
                width=_bounded_int(result["width"], 1, max_edge_px),
                height=_bounded_int(result["height"], 1, max_edge_px),
                page_width_pt=_bounded_int(result["page_width_pt"], 1, 200_000),
                page_height_pt=_bounded_int(result["page_height_pt"], 1, 200_000),
                max_edge_px=max_edge_px)
            if (width, height) != (rendering.width, rendering.height):
                raise ValueError("declared size differs from the PNG")
            return rendering
        except ValueError:
            raise DocumentCodecError("malformed_result") from None

    def extract_text(self, data: bytes) -> TextExtraction:
        result, output, digest = self._call({"op": "extract_text", "format": "docx", "page": None,
                                             "max_edge_px": None}, data)
        try:
            if set(result) != {"paragraphs", "tables", "table_cells", "truncated"} \
                    or type(result["truncated"]) is not bool or len(output) > MAX_TEXT_BYTES:
                raise ValueError("result shape")
            return TextExtraction(
                text=output.decode("utf-8"), sha256=digest,
                paragraphs=_bounded_int(result["paragraphs"], 0, 1_000_000),
                tables=_bounded_int(result["tables"], 0, 100_000),
                table_cells=_bounded_int(result["table_cells"], 0, 10_000_000),
                truncated=result["truncated"])
        except (ValueError, UnicodeDecodeError):
            raise DocumentCodecError("malformed_result") from None
