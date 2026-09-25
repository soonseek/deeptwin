"""The owner's attached originals in a work export, scanned and — for a PDF — redacted
through the isolated document worker (US7, T074; operations.md §7).

Only when the owner explicitly asks for attached originals (`include_source_originals`,
which requires raw originals) is any source's content considered at all; otherwise a
source is listed by kind/id/version only, as before. The control plane never parses a
PDF: the document worker (`cp-document`) extracts every page's text layer and, when the
secret scan (`export_secret_scan.scan_text_spans`) finds something there, produces a NEW
image-only copy with each matched span painted over, which it reopens and verifies (no
text characters, every box dark). The control plane then has the worker extract that copy
again, scans it again and checks the copy's bytes for every matched value; only a copy
that passes all of that is exported, as `redacted` — never as the original, never as a
faithful reproduction. What cannot be scanned or safely redacted is left out with the
stated reason (`unavailable` / `redacted`), unless the owner confirmed the exact finding
set, in which case the original is exported as chosen (operations.md §7: raw by explicit
choice, or excluded).

- PDF with no finding: the original bytes, `raw`.
- PDF with findings, not confirmed: the verified redacted copy, `redacted`; if the scan
  was bounded (`unscanned_text`) or any step fails, excluded.
- plain UTF-8 text: scanned here (it is not a document format); with an unconfirmed
  finding it is withheld (no text redaction is offered).
- anything else (images, archives, DOCX…): excluded, `unavailable` — no scan exists for it.
- no document worker: every PDF excluded, `unavailable`.
- a deleted original: `deleted`.
"""

from __future__ import annotations

from ..domain.owner_material import ARTIFACT_SCHEMA, SOURCE_SCHEMA
from ..domain.refs import EntityRef
from ..domain.store import BlobRef
from ..workers.document_channel import (
    MAX_RANGE_CHARS,
    MAX_REDACT_RANGES,
    DocumentCodecError,
)
from .export_secret_scan import Finding, scan_text_spans

__all__ = ["assess", "load_sources", "materialize"]

MAX_SOURCES = 64
MAX_CACHE = 32
PDF = "application/pdf"


def load_sources(domain, db, roots, revisions, *, with_bytes):
    """Every source any revision of the work names, in order of first appearance."""

    seen, found = set(), []
    for record in revisions:
        for value in record.body["content"].get("source_refs", []):
            ref = EntityRef.from_dict(value)
            if ref.id in seen:
                continue
            seen.add(ref.id)
            if len(found) == MAX_SOURCES:
                raise ValueError("too many sources")
            source = domain._load(db, ref, roots)[0]
            detail = source.body["content"]
            if detail.get("schema_version") != SOURCE_SCHEMA:
                raise ValueError("not an owner source")
            artifact = domain._load(db, EntityRef.from_dict(detail["artifact_ref"]), roots)[0].body["content"]
            if artifact.get("schema_version") != ARTIFACT_SCHEMA:
                raise ValueError("not an owner original")
            blob = BlobRef.from_dict(artifact["blob_ref"])
            deleted = domain._erasure(db, blob, roots) is not None
            data = None
            if with_bytes and not deleted:
                data = domain._blob_bytes(db, blob, roots, purpose="operational")
            found.append({"number": len(found) + 1, "ref": ref, "declared": artifact["declared_media_type"],
                          "indicated": (artifact.get("media_indication") or {}).get("media_type"),
                          "deleted": deleted, "data": data, "sha256": blob.sha256})
    return found


class _Cache:
    """Bounded memo of worker answers by input digest: extraction and redaction are
    deterministic, and a preview and its confirmation must see the same bytes."""

    def __init__(self):
        self._values = {}

    def get(self, key, compute):
        if key not in self._values:
            if len(self._values) >= MAX_CACHE:
                self._values.pop(next(iter(self._values)))
            self._values[key] = compute()
        return self._values[key]


def _kind(source):
    if source["declared"] == PDF and source["indicated"] == PDF:
        return "pdf"
    if source["declared"].split(";", 1)[0].strip() == "text/plain" and source["indicated"] is None:
        return "text"
    return "other"


def _path(source, suffix):
    return f"originals/sources/source-{source['number']}.{suffix}"


def assess(source, *, codec, known, cache):
    """What the scan of one attached original found: findings (as shown), matched values,
    spans per page and why it could not be scanned, if it could not."""

    kind = _kind(source)
    base = {"source": source, "kind": kind, "findings": [], "values": [], "spans": [], "refusal": None,
            "bounded": False}
    if source["deleted"]:
        return {**base, "refusal": "deleted"}
    data = source["data"]
    if kind == "other":
        return {**base, "refusal": "format_not_scannable"}
    if kind == "text":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return {**base, "kind": "other", "refusal": "format_not_scannable"}
        found, _cut, values, _spans = scan_text_spans(text, known=known)
        base["findings"] = [{"relative_path": _path(source, "txt"), **item.as_dict()} for item in found]
        base["values"] = values
        base["bounded"] = any(item.kind.startswith("unscanned_") for item in found)
        return base
    if codec is None:
        return {**base, "refusal": "document_worker_unavailable"}
    try:
        extraction = cache.get(("text", source["sha256"]), lambda: codec.extract_pdf_text(data))
    except DocumentCodecError as error:
        return {**base, "refusal": f"document_worker_{error.code}"}
    for page_number, text in enumerate(extraction.pages, start=1):
        found, _cut, values, spans = scan_text_spans(text, known=known)
        base["findings"].extend({"relative_path": _path(source, "pdf"), "page": page_number, **item.as_dict()}
                                for item in found)
        base["values"].extend(values)
        base["spans"].extend((page_number, start, end) for start, end in spans)
        base["bounded"] = base["bounded"] or any(item.kind.startswith("unscanned_") for item in found)
    if extraction.truncated:
        # pages past the worker's text bound were not read: nothing there is claimed clean
        base["findings"].append({"relative_path": _path(source, "pdf"), "page": len(extraction.pages) + 1,
                                 **Finding("unscanned_text", 1, 1).as_dict()})
        base["bounded"] = True
    return base


def _ranges(spans):
    ranges = []
    for page, start, end in spans:
        while start < end:
            length = min(end - start, MAX_RANGE_CHARS)
            ranges.append((page, start, length))
            start += length
    return ranges


def _redacted(assessed, *, codec, known, cache):
    """The verified redacted copy's bytes, or None when it cannot be made AND verified."""

    source = assessed["source"]
    ranges = _ranges(assessed["spans"])
    if assessed["bounded"] or not ranges or len(ranges) > MAX_REDACT_RANGES:
        return None
    key = ("redact", source["sha256"], tuple(ranges))
    try:
        copy = cache.get(key, lambda: codec.redact_pdf(source["data"], ranges))
        again = cache.get(("text", copy.sha256), lambda: codec.extract_pdf_text(copy.pdf))
    except DocumentCodecError:
        return None
    # verified independently of the worker's own check: the copy's text layer, extracted
    # again by the worker, holds no finding and no matched value, and its bytes hold none
    for text in again.pages:
        found, _cut, _values, _spans = scan_text_spans(text, known=known)
        if found or any(value in text for value in assessed["values"]):
            return None
    if again.truncated or any(value.encode("utf-8") in copy.pdf for value in assessed["values"]):
        return None
    return copy.pdf


REFUSAL_CLAIMS = {
    "deleted": "첨부 원본 {n}은 소유자가 삭제해 넣을 수 없다.",
    "format_not_scannable": "첨부 원본 {n}은 비밀 검사를 할 수 없는 형식이라 넣지 않았다.",
    "document_worker_unavailable": "문서 격리 작업자가 연결되지 않아 첨부 PDF {n}의 내용을 검사할 수 없어 넣지 않았다.",
}


def materialize(assessed, *, confirmed, codec, known, cache):
    """(item or None, missing entry or None) for one assessed source."""

    source, n = assessed["source"], assessed["source"]["number"]
    refusal = assessed["refusal"]
    if refusal is not None:
        claim = REFUSAL_CLAIMS.get(refusal, "문서 격리 작업자가 첨부 PDF {n}을 읽지 못해({code}) 검사할 수 없어 넣지 않았다.")
        return None, {"category": "originals", "reason": "deleted" if refusal == "deleted" else "unavailable",
                      "claim": claim.format(n=n, code=refusal.removeprefix("document_worker_"))}
    suffix = "pdf" if assessed["kind"] == "pdf" else "txt"
    media = PDF if assessed["kind"] == "pdf" else "text/plain; charset=utf-8"
    name = "PDF" if assessed["kind"] == "pdf" else "텍스트"
    if not assessed["findings"] or confirmed:
        label = (f"첨부 원본 {n} ({name}) 원문" + (" — 확인한 비밀 의심 값 포함" if assessed["findings"] else ""))
        return {"category": "originals", "relative_path": _path(source, suffix), "media_type": media,
                "data": source["data"], "content_mode": "raw", "label": label,
                "source_ref": source["ref"]}, None
    if assessed["kind"] == "pdf":
        copy = _redacted(assessed, codec=codec, known=known, cache=cache)
        if copy is not None:
            spans = len(assessed["spans"])
            return {"category": "originals", "relative_path": _path(source, "redacted.pdf"), "media_type": PDF,
                    "data": copy, "content_mode": "redacted",
                    "label": (f"첨부 원본 {n} (PDF 가림 사본: 비밀 의심 값 {spans}곳을 덮은 이미지 PDF, "
                              "텍스트 층 없음, 원본과 같지 않음)"),
                    "source_ref": source["ref"]}, {
                "category": "originals", "reason": "redacted",
                "claim": (f"첨부 PDF {n}은 비밀 의심 값을 덮은 이미지 사본으로만 넣었다. 사본은 원본과 같지 않고 "
                          "텍스트 층·메타데이터·링크가 없다.")}
        return None, {"category": "originals", "reason": "redacted",
                      "claim": f"첨부 PDF {n}에 비밀 의심 값이 있고 가림 사본을 만들어 검증하지 못해 넣지 않았다."}
    return None, {"category": "originals", "reason": "redacted",
                  "claim": f"첨부 원본 {n}에 비밀 의심 값이 있어 넣지 않았다."}
