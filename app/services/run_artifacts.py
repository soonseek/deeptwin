"""The owner's view of what a run produced: artifact listing, originals,
bounded ranges and derived previews (T045; runtime.md §5, FR-015).

A run's artifacts are exactly the registered output blobs its accepted node
results name: a result record of kind `artifact` whose content carries an
`artifacts` list (`ordinal`, `role`, `media_type`, `blob`), as the extension
and provider attempt transports seal them. Nothing else is an artifact — not
a path, a filename or a caller-supplied reference. The store verifies every
blob a record names when it reads the record, so an original whose bytes
vanished fails the read closed (`unavailable`) instead of being listed.

The original is preserved and served as-is (whole or one bounded byte range),
never transcoded. A preview is a DERIVED artifact with its own digest, a
fidelity note and its disclosed coverage: this process derives previews only
for formats it can read with bounded standard-library parsers — UTF-8 text,
JSON and CSV. Images are identified by their magic bytes and left to the
browser to decode. PDF and DOCX are never parsed here: worker-produced
documents are untrusted input, so their bytes go to the isolated document
service over the verified `cp-document` channel (`app.workers.document_channel`)
when the deployment names it — a PDF page comes back as a bounded PNG
(`page_image`, page N of the real page count), a DOCX as its body and table
text (`document_text`), each with the worker's output digest, a fidelity note
and the parts it did not cover. Without the worker, or when it cannot answer,
the preview says so (`codec_required` / `codec_failed`) and nothing stands in
for the page. The declared media type is shown as declared; what the preview
does follows the bytes.

The vault-wide index (`index`) lists every run's artifacts, oldest run first,
in bounded pages with run and media-type filters; each entry names its run so
the viewer opens it through the same run-scoped routes.
"""

from __future__ import annotations

import csv
import io
import json
import re
import threading
from collections import OrderedDict
from functools import wraps
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef, uuid_string
from ..domain.store import BlobRef
from ..workers.document_channel import (
    DEFAULT_EDGE_PX,
    DOCX_OMITTED,
    MAX_INPUT_BYTES as CODEC_INPUT_BYTES,
    MAX_PAGES,
    PDF_OMITTED,
    DocumentCodecClient,
    DocumentCodecError,
)
from .owner_auth import OwnerAuthError
from .runs import RunServiceError

__all__ = ["PersistentRunArtifacts", "RunArtifactError", "artifact_identity"]

CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found",
                   "unavailable", "range_not_satisfiable", "too_large", "unsupported_media",
                   "codec_failed"})
MAX_ARTIFACTS = 256
MAX_INDEX_RUNS = 1_000
MAX_INDEX_LIMIT = 100
DEFAULT_INDEX_LIMIT = 25
MAX_CACHED_PAGES = 16
_MEDIA_FILTER = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/(?:\*|[a-z0-9][a-z0-9!#$&^_.+-]{0,63})\Z")
MAX_RANGE_BYTES = 1_048_576
PREVIEW_TEXT_BYTES = 65_536
PREVIEW_TABLE_ROWS = 200
PREVIEW_TABLE_COLUMNS = 50
PREVIEW_CELL_CHARS = 1_000
PREVIEW_JSON_DEPTH = 32
_ROLE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MEDIA = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}\Z")
_RANGE = re.compile(r"bytes=(\d{1,19})-(\d{0,19})\Z")
_IMAGES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))
_CODEC_FORMATS = ((b"%PDF-", "pdf"), (b"PK\x03\x04", "zip_container"))


class RunArtifactError(ValueError):
    """Closed codes; storage detail never leaks."""

    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RunServiceError as error:
            raise RunArtifactError(error.code) from None  # the run's own closed code
        except (RunArtifactError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise RunArtifactError("unavailable") from None

    return invoke


def artifact_identity(result_ref: EntityRef, ordinal: int) -> str:
    """One stable ID per (exact result record version, ordinal)."""

    return str(uuid5(NAMESPACE_URL,
                     f"deeptwin:run-artifact:{result_ref.id}:{result_ref.version}:{ordinal}"))


def _entries(record) -> list[dict]:
    """A result record's declared artifacts, validated strictly or not at all."""

    if record.ref.kind != "artifact":
        return []
    content = record.body["content"]
    items = content.get("artifacts") if type(content) is dict else None
    if items is None:
        return []
    if type(items) is not list or len(items) > MAX_ARTIFACTS:
        raise RunArtifactError("unavailable")
    entries = []
    for index, item in enumerate(items):
        if (type(item) is not dict or set(item) != {"ordinal", "role", "media_type", "blob"}
                or item["ordinal"] != index or type(item["ordinal"]) is not int
                or type(item["role"]) is not str or _ROLE.fullmatch(item["role"]) is None
                or type(item["media_type"]) is not str
                or _MEDIA.fullmatch(item["media_type"]) is None
                or type(item["blob"]) is not dict):
            raise RunArtifactError("unavailable")  # a malformed result is not an artifact list
        blob = BlobRef(**item["blob"])
        entries.append({"ordinal": index, "role": item["role"],
                        "media_type": item["media_type"], "blob": blob})
    return entries


def _sniff(data: bytes) -> str:
    for magic, media in _IMAGES:
        if data.startswith(magic):
            return media
    for magic, name in _CODEC_FORMATS:
        if data.startswith(magic):
            return name
    return "bytes"


def _text_of(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _json_depth(value, depth=0) -> None:
    if depth > PREVIEW_JSON_DEPTH:
        raise ValueError("depth")
    if type(value) is dict:
        for item in value.values():
            _json_depth(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _json_depth(item, depth + 1)


def _derived(kind, body, *, fidelity, covered, omissions, total):
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return {
        "kind": kind,
        "derived": True,
        "sha256": sha256(encoded).hexdigest(),
        "fidelity": fidelity,
        "coverage": {"original_bytes": total, "covered": covered, "omissions": omissions},
        "body": body,
    }


_CODEC_REASONS = {
    "not_connected": "no preview: this format is rendered only by the isolated document worker, "
                     "which this deployment does not name; the original is downloadable",
    "too_large": "no preview: the original exceeds the document worker's input bound; "
                 "the original is downloadable",
    "unavailable": "no preview: the isolated document worker did not answer; nothing was "
                   "rendered in its place and the original is downloadable",
}


def codec_required(sniffed: str, total: int, reason: str) -> dict:
    return {"kind": "codec_required", "derived": False, "sha256": None,
            "fidelity": _CODEC_REASONS[reason],
            "coverage": {"original_bytes": total, "covered": [], "omissions": [[0, total]]},
            "body": {"format": sniffed, "reason": reason}}


def codec_failed(sniffed: str, total: int, code: str) -> dict:
    if code == "media_unsupported":
        return {"kind": "unsupported", "derived": False, "sha256": None,
                "fidelity": "no preview: the isolated document worker does not read this container "
                            "(it is not a word-processing document); the original is downloadable",
                "coverage": {"original_bytes": total, "covered": [], "omissions": [[0, total]]},
                "body": {"format": sniffed, "worker_code": code}}
    return {"kind": "codec_failed", "derived": False, "sha256": None,
            "fidelity": "no preview: the isolated document worker refused or failed to read this "
                        f"file ({code}); nothing was rendered in its place and the original is "
                        "downloadable",
            "coverage": {"original_bytes": total, "covered": [], "omissions": [[0, total]]},
            "body": {"format": sniffed, "code": code}}


def page_preview(rendering, total: int) -> dict:
    """One worker-rendered PDF page, disclosed by page coverage (never bytes)."""

    page, count = rendering.page, rendering.page_count
    omissions = [span for span in ([1, page - 1], [page + 1, count]) if span[0] <= span[1]]
    return {
        "kind": "page_image", "derived": True, "sha256": rendering.sha256,
        "fidelity": (f"page {page} of {count} rasterized by the isolated document worker to a "
                     f"{rendering.width}x{rendering.height} px PNG (longest edge at most "
                     f"{rendering.max_edge_px} px); the image carries no text layer, links, "
                     "forms or interactive annotations; the original PDF is downloadable"),
        "coverage": {"original_bytes": total, "unit": "page", "page_count": count,
                     "covered": [[page, page]], "omissions": omissions,
                     "not_rendered": list(PDF_OMITTED)},
        "body": {"media_type": "image/png", "page": page, "page_count": count,
                 "width": rendering.width, "height": rendering.height,
                 "page_width_pt": rendering.page_width_pt, "page_height_pt": rendering.page_height_pt,
                 "byte_length": len(rendering.png)},
    }


def document_text_preview(extraction, total: int) -> dict:
    omitted = list(DOCX_OMITTED) + (["text_beyond_bound"] if extraction.truncated else [])
    return {
        "kind": "document_text", "derived": True, "sha256": extraction.sha256,
        "fidelity": ("body paragraphs and table cells as plain text in document order, extracted "
                     "by the isolated document worker; table rows are tab-separated and "
                     "formatting is not preserved; the original is downloadable"),
        "coverage": {"original_bytes": total, "unit": "text_layer",
                     "covered": ["body_paragraphs", "table_cells"], "omissions": omitted},
        "body": {"text": extraction.text, "truncated": extraction.truncated,
                 "paragraphs": extraction.paragraphs, "tables": extraction.tables,
                 "table_cells": extraction.table_cells},
    }


def derive_preview(entry: dict, data: bytes) -> dict:
    """The bounded derived preview of one original's bytes (never the original)."""

    total = len(data)
    sniffed = _sniff(data)
    if sniffed.startswith("image/"):
        return {"kind": "image", "derived": False, "sha256": None,
                "fidelity": "the original image bytes, decoded by the browser",
                "coverage": {"original_bytes": total, "covered": [[0, total]], "omissions": []},
                "body": {"media_type": sniffed}}
    if sniffed in {"pdf", "zip_container"}:
        return codec_required(sniffed, total, "not_connected")
    head = data[:PREVIEW_TEXT_BYTES]
    text = _text_of(head)
    if text is None and len(head) < total:
        # the cut may split one multi-byte character: drop at most three trailing bytes
        for cut in range(1, 4):
            text = _text_of(head[:-cut])
            if text is not None:
                head = head[:-cut]
                break
    if text is None:
        return {"kind": "unsupported", "derived": False, "sha256": None,
                "fidelity": "no preview: the bytes are neither UTF-8 text nor a recognised image",
                "coverage": {"original_bytes": total, "covered": [], "omissions": [[0, total]]},
                "body": {}}
    shown = len(head)
    omissions = [] if shown == total else [[shown, total]]
    declared = entry["media_type"]
    if declared == "application/json" and shown == total:
        try:
            value = json.loads(text)
            _json_depth(value)
        except (ValueError, RecursionError):
            value = None
        if value is not None:
            return _derived("json", {"text": json.dumps(value, ensure_ascii=False, indent=2)},
                            fidelity="parsed and re-indented; key order and values preserved",
                            covered=[[0, total]], omissions=[], total=total)
    if declared == "text/csv":
        rows, cut = [], False
        for row in csv.reader(io.StringIO(text, newline="")):
            if len(rows) == PREVIEW_TABLE_ROWS:
                cut = True
                break
            clipped = [cell[:PREVIEW_CELL_CHARS] for cell in row[:PREVIEW_TABLE_COLUMNS]]
            cut = cut or len(row) > PREVIEW_TABLE_COLUMNS or clipped != row[:PREVIEW_TABLE_COLUMNS]
            rows.append(clipped)
        return _derived("table", {"rows": rows, "truncated": cut or bool(omissions)},
                        fidelity="cells shown as text; formulas are never evaluated",
                        covered=[[0, shown]], omissions=omissions, total=total)
    return _derived("text", {"text": text},
                    fidelity="UTF-8 text shown verbatim, never rendered as markup",
                    covered=[[0, shown]], omissions=omissions, total=total)


class PersistentRunArtifacts:
    """Owner-read artifacts of one run, resolved from its accepted results."""

    def __init__(self, domain_store, owner_authority, runs, *, codec=None):
        if codec is not None and type(codec) is not DocumentCodecClient:
            raise TypeError("an exact document codec client is required")
        self._domain = domain_store
        self._owner = owner_authority
        self._runs = runs
        self._codec = codec
        self._pages = OrderedDict()  # (sha256, page, edge) -> PageRendering, bounded
        self._pages_lock = threading.Lock()

    @property
    def codec_connected(self) -> bool:
        return self._codec is not None

    def _check(self, request):
        if request is None:
            raise RunArtifactError("unauthenticated")
        self._owner.authenticate_bound(request.session)

    def _catalog(self, run_id, *, base_path):
        try:
            run_id = uuid_string(run_id)
        except (TypeError, ValueError):
            raise RunArtifactError("invalid_input") from None
        outcome = self._runs.read(run_id, base_path=base_path)["outcome"]
        nodes = {execution: node for node, execution in outcome["execution_ids"]}
        items = []
        seen = set()
        for execution_id, raw in outcome["result_refs"]:
            ref = EntityRef.from_dict(raw)
            if ref in seen:
                continue  # one result named by several visits lists its artifacts once
            seen.add(ref)
            record = self._domain.get(ref)
            for entry in _entries(record):
                items.append({
                    "artifact_id": artifact_identity(ref, entry["ordinal"]),
                    "execution_id": execution_id,
                    "node_id": nodes.get(execution_id),
                    "result_ref": ref.as_dict(),
                    **entry,
                })
                if len(items) > MAX_ARTIFACTS:
                    raise RunArtifactError("unavailable")
        return run_id, items

    def _bytes(self, item):
        blob = item["blob"]
        try:
            return self._domain.read_blob(blob, purpose=blob.purpose)
        except (DomainContractError, KeyError, OSError, ValueError):
            return None

    def _projection(self, item, *, available):
        blob = item["blob"]
        return {
            "artifact_id": item["artifact_id"], "execution_id": item["execution_id"],
            "node_id": item["node_id"], "ordinal": item["ordinal"], "role": item["role"],
            "declared_media_type": item["media_type"], "sha256": blob.sha256,
            "size": blob.size, "result_ref": item["result_ref"],
            "availability": "available" if available else "missing",
        }

    def _find(self, items, artifact_id):
        try:
            artifact_id = uuid_string(artifact_id)
        except (TypeError, ValueError):
            raise RunArtifactError("invalid_input") from None
        for item in items:
            if item["artifact_id"] == artifact_id:
                return item
        raise RunArtifactError("not_found")

    @_closed
    def list(self, request, run_id, *, base_path) -> dict:
        self._check(request)
        run_id, items = self._catalog(run_id, base_path=base_path)
        return {"run_id": run_id, "artifacts": [
            self._projection(item, available=self._bytes(item) is not None) for item in items]}

    @_closed
    def read(self, request, run_id, artifact_id, *, base_path) -> dict:
        self._check(request)
        _run, items = self._catalog(run_id, base_path=base_path)
        item = self._find(items, artifact_id)
        return self._projection(item, available=self._bytes(item) is not None)

    @_closed
    def content(self, request, run_id, artifact_id, *, base_path, range_header=None):
        """(metadata, bytes, served range or None, sniffed media) of the original."""

        self._check(request)
        _run, items = self._catalog(run_id, base_path=base_path)
        item = self._find(items, artifact_id)
        data = self._bytes(item)
        if data is None:
            raise RunArtifactError("not_found")  # a missing original serves nothing
        served = None
        if range_header is not None:
            match = _RANGE.fullmatch(range_header)
            if match is None:
                raise RunArtifactError("invalid_input")
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else len(data) - 1
            if start >= len(data) or end < start:
                raise RunArtifactError("range_not_satisfiable")
            end = min(end, len(data) - 1, start + MAX_RANGE_BYTES - 1)
            served = (start, end)
            data = data[start:end + 1]
        return (self._projection(item, available=True), data, served,
                _sniff(self._bytes(item) if served else data))

    @_closed
    def preview(self, request, run_id, artifact_id, *, base_path) -> dict:
        item, data = self._original(request, run_id, artifact_id, base_path=base_path)
        sniffed = _sniff(data)
        if sniffed in {"pdf", "zip_container"}:
            preview = self._document_preview(item, data, sniffed)
        else:
            preview = derive_preview(item, data)
        return {"artifact": self._projection(item, available=True), "preview": preview}

    def _original(self, request, run_id, artifact_id, *, base_path):
        self._check(request)
        _run, items = self._catalog(run_id, base_path=base_path)
        item = self._find(items, artifact_id)
        data = self._bytes(item)
        if data is None:
            raise RunArtifactError("not_found")
        return item, data

    # --- documents through the isolated worker (never parsed here) -----------------

    def _render(self, item, data, page):
        key = (item["blob"].sha256, page, DEFAULT_EDGE_PX)
        with self._pages_lock:
            cached = self._pages.get(key)
            if cached is not None:
                self._pages.move_to_end(key)
                return cached
        rendering = self._codec.render_page(data, page=page, max_edge_px=DEFAULT_EDGE_PX)
        with self._pages_lock:
            self._pages[key] = rendering
            while len(self._pages) > MAX_CACHED_PAGES:
                self._pages.popitem(last=False)
        return rendering

    def _document_preview(self, item, data, sniffed):
        total = len(data)
        if self._codec is None:
            return codec_required(sniffed, total, "not_connected")
        if total > CODEC_INPUT_BYTES:
            return codec_required(sniffed, total, "too_large")
        try:
            if sniffed == "pdf":
                return page_preview(self._render(item, data, 1), total)
            return document_text_preview(self._codec.extract_text(data), total)
        except DocumentCodecError as error:
            if error.code in {"unavailable", "transport_failed"}:
                return codec_required(sniffed, total, "unavailable")
            if error.code == "too_large":
                return codec_required(sniffed, total, "too_large")
            return codec_failed(sniffed, total, error.code)

    def _page(self, request, run_id, artifact_id, page, *, base_path):
        if type(page) is not int or not 1 <= page <= MAX_PAGES:
            raise RunArtifactError("invalid_input")
        item, data = self._original(request, run_id, artifact_id, base_path=base_path)
        if _sniff(data) != "pdf":
            raise RunArtifactError("unsupported_media")  # only a PDF has pages to render
        if self._codec is None:
            raise RunArtifactError("unavailable")  # the worker is not named: nothing is faked
        if len(data) > CODEC_INPUT_BYTES:
            raise RunArtifactError("too_large")
        try:
            rendering = self._render(item, data, page)
        except DocumentCodecError as error:
            raise RunArtifactError({
                "page_out_of_range": "range_not_satisfiable", "unavailable": "unavailable",
                "transport_failed": "unavailable", "too_large": "too_large",
                "media_unsupported": "unsupported_media"}.get(error.code, "codec_failed")) from None
        return item, data, rendering

    @_closed
    def page(self, request, run_id, artifact_id, page, *, base_path) -> dict:
        """The disclosure of one worker-rendered page (its PNG is `page_image`)."""

        item, data, rendering = self._page(request, run_id, artifact_id, page, base_path=base_path)
        return {"artifact": self._projection(item, available=True),
                "preview": page_preview(rendering, len(data))}

    @_closed
    def page_image(self, request, run_id, artifact_id, page, *, base_path):
        """(metadata, the worker's PNG bytes, their digest) of one rendered page."""

        item, _data, rendering = self._page(request, run_id, artifact_id, page, base_path=base_path)
        return self._projection(item, available=True), rendering.png, rendering.sha256

    # --- the vault-wide index ---------------------------------------------------------

    def _run_ids(self):
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            rows = list(db.execute(
                "SELECT id FROM runtime_runs WHERE vault_id=? ORDER BY rowid LIMIT ?",
                (roots.genesis.id, MAX_INDEX_RUNS + 1)))
            total = db.execute("SELECT count(*) FROM runtime_runs WHERE vault_id=?",
                               (roots.genesis.id,)).fetchone()[0]
        return [uuid_string(row["id"]) for row in rows[:MAX_INDEX_RUNS]], total

    @_closed
    def index(self, request, *, base_path, run_id=None, media_type=None, cursor=0,
              limit=DEFAULT_INDEX_LIMIT) -> dict:
        """Every run's artifacts, oldest run first, one bounded page at a time."""

        self._check(request)
        if (type(cursor) is not int or cursor < 0 or type(limit) is not int
                or not 1 <= limit <= MAX_INDEX_LIMIT):
            raise RunArtifactError("invalid_input")
        if media_type is not None and (type(media_type) is not str
                                       or _MEDIA_FILTER.fullmatch(media_type) is None):
            raise RunArtifactError("invalid_input")
        if run_id is not None:
            try:
                run_id = uuid_string(run_id)
            except (TypeError, ValueError):
                raise RunArtifactError("invalid_input") from None
            run_ids, total_runs = [run_id], 1
        else:
            run_ids, total_runs = self._run_ids()
        matched, unreadable = [], 0
        for current in run_ids:
            try:
                _run, items = self._catalog(current, base_path=base_path)
            except (RunServiceError, RunArtifactError, OwnerAuthError):
                if run_id is not None:
                    raise  # the one named run answers its own code
                unreadable += 1  # not a runs-v1 run, or its record cannot be read now
                continue
            except Exception:  # noqa: BLE001 - one unreadable run never hides the others
                if run_id is not None:
                    raise
                unreadable += 1
                continue
            for item in items:
                if media_type is not None:
                    declared = item["media_type"]
                    wanted = media_type[:-1] if media_type.endswith("/*") else None
                    if (declared != media_type) if wanted is None else not declared.startswith(wanted):
                        continue
                matched.append((current, item))
        shown = matched[cursor:cursor + limit]
        following = cursor + limit if cursor + limit < len(matched) else None
        return {
            "artifacts": [{"run_id": current, **self._projection(item, available=self._bytes(item) is not None)}
                          for current, item in shown],
            "total": len(matched), "cursor": cursor, "limit": limit,
            "next_cursor": None if following is None else str(following),
            "filters": {"run_id": run_id, "media_type": media_type},
            "runs": {"scanned": len(run_ids), "unreadable": unreadable,
                     "omitted": max(0, total_runs - len(run_ids))},
        }
