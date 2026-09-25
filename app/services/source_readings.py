"""Owner-commanded reading of retained originals: complete, partial or unreadable (T023).

Storing an original never reads it (owner_material_intake). A reading happens only when
the owner asks for it, for one exact source of one work, and is sealed as one immutable
`extraction` record whose state says exactly how much of the original was read:

- `complete`: every part this reader extracts was read and kept;
- `partial`: some of it was read — the reasons name what was not (the kept text was cut
  at the record bound, some PDF pages have no text layer, some bytes were not UTF-8);
- `unreadable`: nothing usable was read — the reasons say why (an unsupported format,
  a corrupt document, no text at all, an original the owner deleted).

Plain text is decoded here (a UTF-8 decode is not a parser). PDF and DOCX are handed to
the isolated document worker (`DocumentCodecClient`); the control plane never parses
them. When that worker is not attached or does not answer, nothing is sealed and the
owner is told the reader is unavailable (a retry is safe: a reading has no other effect).
Nothing here infers meaning, calls a model or reads anything implicitly; the work-model
draft (work_models.py) uses a source's latest reading only when the owner made one.

The kept text is not written into the reading record: it is stored as its own
content-addressed blob (`text_blob_ref`, null when nothing was kept), so that when the
owner deletes the original (source_deletions.py) the text read from it is erased the
same way the original is — one tombstone per content address, the bytes removed after
the commit. The reading record then stays as metadata (state, reasons, counts) and
every reader answers `deleted` for its text; nothing of it is shown or sent again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.owner_material import ARTIFACT_SCHEMA, SOURCE_SCHEMA
from ..domain.public_events import _append_event_in_transaction
from ..domain.refs import EntityRef, ObjectRef, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef, ErasedBlob, _writer
from . import owner_material_journal as journal
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner, _owner_actor_ref
from .works import PersistentWorks, WorkServiceError

__all__ = ["READING_SCHEMA", "SourceReadingError", "SourceReadings", "latest_readings", "reading_text",
           "text_blob"]

READING_SCHEMA = "source-reading-v2"  # v1 kept the text inline; v2 keeps it as an erasable blob
TEXT_PURPOSE = "operational"
COMMAND_SCHEMA = "source-reading-command-v1"
MAX_KEPT_BYTES = 60_000  # under the domain record's 64 KiB canonical string bound
EXCERPT_CHARS = 280
STATES = ("complete", "partial", "unreadable")
REASONS = frozenset({
    "truncated", "pages_without_text", "invalid_encoding", "unsupported_format", "corrupt",
    "too_large", "no_text", "deleted",
})
TEXT_EXTENSIONS = (".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".text")
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "unavailable", "reader_unavailable", "capacity", "deleted"})
_GAP = {"unsupported_format": "unsupported", "corrupt": "corrupt", "too_large": "unsupported",
        "no_text": "unsupported", "deleted": "deleted"}
_INDEX_DDL = """CREATE TABLE IF NOT EXISTS source_readings_v1(
    seq INTEGER PRIMARY KEY AUTOINCREMENT, vault_id TEXT NOT NULL, work_id TEXT NOT NULL,
    source_id TEXT NOT NULL, reading_id TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL)"""


class SourceReadingError(ValueError):
    """Closed codes; storage, parser and worker detail never leak."""

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
        except (SourceReadingError, OwnerAuthError):
            raise
        except WorkServiceError as error:
            raise SourceReadingError(error.code) from None
        except Exception:  # noqa: BLE001 - storage/worker detail must not disclose
            raise SourceReadingError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _keep(text: str) -> tuple[str, bool]:
    """The text cut at a character boundary under the record bound, and whether it was cut."""
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_KEPT_BYTES:
        return text, False
    return encoded[:MAX_KEPT_BYTES].decode("utf-8", errors="ignore"), True


def _family(name: str, declared: str, indicated) -> str:
    lowered = name.lower()
    if indicated == "application/pdf":
        return "pdf"
    if indicated == "application/zip" and (lowered.endswith(".docx") or declared == DOCX_MEDIA):
        return "docx"
    if indicated is None and (declared.startswith("text/") or declared == "application/json"
                              or lowered.endswith(TEXT_EXTENSIONS)):
        return "text"
    return "other"


def read_plain_text(data: bytes) -> dict:
    """A strict UTF-8 reading; undecodable bytes make it partial, mostly-binary unreadable."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if b"\x00" in data:
        return {"state": "unreadable", "reasons": ["unsupported_format"], "text": ""}
    reasons = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        replaced = text.count("�")
        if replaced * 4 > max(len(text), 1):  # mostly undecodable: not text
            return {"state": "unreadable", "reasons": ["unsupported_format"], "text": ""}
        reasons.append("invalid_encoding")
    if not text.strip():
        return {"state": "unreadable", "reasons": ["no_text"], "text": ""}
    return {"state": "partial" if reasons else "complete", "reasons": reasons, "text": text}


def _codec_reading(codec, family: str, data: bytes) -> dict:
    from ..workers.document_channel import DocumentCodecError

    if codec is None:
        raise SourceReadingError("reader_unavailable")
    try:
        if family == "pdf":
            extraction = codec.extract_pdf_text(data)
            pages = list(extraction.pages)
            empty = sum(1 for page in pages if not page.strip())
            text = "\f".join(pages)
            reasons = (["pages_without_text"] if empty else []) + (["truncated"] if extraction.truncated else [])
            base = {"page_count": extraction.page_count, "pages_without_text": empty}
            if not text.strip():
                return {**base, "state": "unreadable", "reasons": ["no_text"], "text": ""}
            return {**base, "state": "partial" if reasons else "complete", "reasons": reasons, "text": text}
        extraction = codec.extract_text(data)
        if not extraction.text.strip():
            return {"state": "unreadable", "reasons": ["no_text"], "text": ""}
        reasons = ["truncated"] if extraction.truncated else []
        return {"state": "partial" if reasons else "complete", "reasons": reasons, "text": extraction.text}
    except DocumentCodecError as error:
        if error.code in {"unavailable", "transport_failed", "malformed_result"}:
            raise SourceReadingError("reader_unavailable") from None
        reason = "too_large" if error.code == "too_large" else "corrupt"
        return {"state": "unreadable", "reasons": [reason], "text": "",
                **({"page_count": error.page_count} if error.page_count else {})}


def text_blob(record):
    """The blob holding a reading's kept text, or None when nothing was kept."""
    value = record.body["content"].get("text_blob_ref")
    return None if value is None else BlobRef.from_dict(value)


def _original_erased(domain, db, roots, record) -> bool:
    source = domain._load(db, EntityRef.from_dict(record.body["content"]["source_ref"]), roots)[0]
    artifact = domain._load(db, EntityRef.from_dict(source.body["content"]["artifact_ref"]), roots)[0]
    return domain._erasure(db, BlobRef.from_dict(artifact.body["content"]["blob_ref"]), roots) is not None


def text_erased(domain, db, roots, record) -> bool:
    """True once the owner deleted the original or the text read from it."""
    blob = text_blob(record)
    return (_original_erased(domain, db, roots, record)
            or (blob is not None and domain._erasure(db, blob, roots) is not None))


def reading_text(domain, db, roots, record):
    """The kept text of a reading ("" when nothing was kept), or None once it was deleted."""
    if text_erased(domain, db, roots, record):
        return None
    blob = text_blob(record)
    if blob is None:
        return ""
    try:
        return domain._blob_bytes(db, blob, roots, purpose=TEXT_PURPOSE).decode("utf-8")
    except ErasedBlob:
        return None


def _view(record, text, *, full=True) -> dict:
    """`text` is the kept text, or None when the owner deleted it: the record then reads
    as metadata only, with `text_state: deleted` and neither text nor excerpt."""
    content = record.body["content"]
    value = {
        "reading_ref": record.ref.as_dict(), "source_ref": content["source_ref"],
        "state": content["state"], "reasons": list(content["reasons"]), "method": content["method"],
        "kept_characters": content["kept_characters"], "page_count": content["page_count"],
        "pages_without_text": content["pages_without_text"], "read_at_utc": record.body["created_at_utc"],
        "text_state": "deleted" if text is None else "kept",
    }
    if text is None:
        return value
    if full:
        value["text"] = text
    else:
        value["excerpt"] = text[:EXCERPT_CHARS]
    return value


def _index(db):
    db.execute(_INDEX_DDL)


def _latest_record(domain, db, roots, ref):
    row = db.execute("SELECT reading_id, sha256 FROM source_readings_v1 WHERE vault_id=? AND source_id=? "
                     "ORDER BY seq DESC LIMIT 1", (roots.genesis.id, ref["id"])).fetchone()
    if row is None:
        return None
    record = domain._load(db, EntityRef("extraction", row["reading_id"], 1, row["sha256"]), roots)[0]
    if record.body["content"].get("schema_version") != READING_SCHEMA \
            or record.body["content"]["source_ref"] != ref:
        return None  # a reading of another source version (or an older format) never stands in
    return record


def latest_readings(domain, db, roots, source_refs) -> list:
    """The latest sealed reading of each named source (in order), None where none was made
    or where the owner deleted the original and the text read from it."""
    result = []
    for ref in source_refs:
        record = _latest_record(domain, db, roots, ref)
        if record is not None and text_erased(domain, db, roots, record):
            record = None  # deleted: text read from it is no longer shown or sent
        result.append(record)
    return result


def readings_of_source(db, roots, source_id) -> list:
    """Every reading ever sealed for this source id, oldest first (the index rows)."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_readings_v1'").fetchone() is None:
        return []
    return [EntityRef("extraction", row[0], 1, row[1]) for row in db.execute(
        "SELECT reading_id, sha256 FROM source_readings_v1 WHERE vault_id=? AND source_id=? ORDER BY seq",
        (roots.genesis.id, source_id))]


class SourceReadings:
    """The owner's explicit readings of a work's retained originals."""

    def __init__(self, works, codec=None):
        if type(works) is not PersistentWorks:
            raise TypeError("Exact PersistentWorks required")
        self.works = works
        self.domain, self.owner = works._domain, works._owner
        self.codec = codec
        with _writer(), self.domain._connection(write=True) as db:
            _index(db)

    def _membership(self, db, roots, work_id):
        latest = self.works._latest(db, roots, work_id)
        if latest is None:
            raise SourceReadingError("not_found")
        return latest, latest.body["content"].get("source_refs", [])

    def _original(self, db, roots, ref):
        source = self.domain._load(db, EntityRef.from_dict(ref), roots)[0]
        detail = source.body["content"]
        if detail.get("schema_version") != SOURCE_SCHEMA:
            raise SourceReadingError("unavailable")
        artifact = self.domain._load(db, EntityRef.from_dict(detail["artifact_ref"]), roots)[0]
        if artifact.body["content"].get("schema_version") != ARTIFACT_SCHEMA:
            raise SourceReadingError("unavailable")
        return source, artifact

    @_closed
    def list(self, request, work_id) -> dict:
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise SourceReadingError("invalid_input") from None
        with self.domain._connection() as db:
            self.owner.authenticate_bound(request.session)
            roots = self.domain._read_roots(db)
            latest, refs = self._membership(db, roots, work_id)
            sources = []
            for ref in refs:
                source, artifact = self._original(db, roots, ref)
                blob = BlobRef.from_dict(artifact.body["content"]["blob_ref"])
                reading = _latest_record(self.domain, db, roots, ref)
                sources.append({
                    "source_id": ref["id"], "source_ref": ref, "name": source.body["content"]["name"],
                    "original_state": "deleted" if self.domain._erasure(db, blob, roots) is not None else "stored",
                    "reading": None if reading is None else _view(
                        reading, reading_text(self.domain, db, roots, reading), full=False),
                })
        return {"work_id": work_id, "revision": latest.ref.version, "reader_attached": self.codec is not None,
                "sources": sources}

    @_closed
    def read(self, request, work_id, source_id) -> dict:
        try:
            work_id, source_id = uuid_string(work_id), uuid_string(source_id)
        except (TypeError, ValueError):
            raise SourceReadingError("invalid_input") from None
        with self.domain._connection() as db:
            self.owner.authenticate_bound(request.session)
            roots = self.domain._read_roots(db)
            _, refs = self._membership(db, roots, work_id)
            ref = next((item for item in refs if item["id"] == source_id), None)
            if ref is None:
                raise SourceReadingError("not_found")
            reading = _latest_record(self.domain, db, roots, ref)
            if reading is None:
                raise SourceReadingError("not_found")
            text = reading_text(self.domain, db, roots, reading)
        if text is None:
            raise SourceReadingError("deleted")  # the record stays; its text was erased with the original
        return _view(reading, text)

    @_closed
    def command(self, request, work_id, payload) -> dict:
        """One owner-commanded reading of one exact source of the work's latest revision."""
        _authenticate_owner(self.owner, request)
        if (type(payload) is not dict or set(payload) != {"schema_version", "command_id", "source_ref"}
                or payload["schema_version"] != COMMAND_SCHEMA):
            raise SourceReadingError("invalid_input")
        try:
            work_id = uuid_string(work_id)
            command_id = uuid_string(payload["command_id"])
            source_ref = EntityRef.from_dict(payload["source_ref"])
        except (TypeError, ValueError, KeyError):
            raise SourceReadingError("invalid_input") from None
        if source_ref.kind != "source":
            raise SourceReadingError("invalid_input")
        digest = journal.fingerprint("read_source", work_id, payload)
        reading_id = str(uuid5(NAMESPACE_URL, f"deeptwin:source-reading:{command_id}"))
        with self.domain._connection() as db:
            roots = self.domain._read_roots(db)
            replay = journal.lookup(db, roots.genesis.id, command_id)
            if replay is not None:
                if replay["fingerprint"] != digest:
                    raise SourceReadingError("conflict")
                ref = EntityRef.from_dict(journal.receipt(replay)["reading_ref"])
                return self._replayed(db, roots, ref)
            if self.works._by_command(db, roots, command_id) is not None:
                raise SourceReadingError("conflict")  # one command id, one meaning
            _, refs = self._membership(db, roots, work_id)
            if source_ref.as_dict() not in refs:
                raise SourceReadingError("not_found")  # only a source of this work, exactly
            _, artifact = self._original(db, roots, source_ref.as_dict())
            original = artifact.body["content"]
            blob = BlobRef.from_dict(original["blob_ref"])
            deleted = self.domain._erasure(db, blob, roots) is not None
            data = None if deleted else self.domain._blob_bytes(db, blob, roots, purpose="operational")
        family = _family(original["name"], original["declared_media_type"],
                         original["media_indication"]["media_type"])
        if deleted:
            outcome, method = {"state": "unreadable", "reasons": ["deleted"], "text": ""}, "none"
        elif family == "text":
            outcome, method = read_plain_text(data), "utf8-text-v1"
        elif family in {"pdf", "docx"}:
            outcome = _codec_reading(self.codec, family, data)  # reader_unavailable: nothing sealed
            method = f"document-worker-{family}-text-v1"
        else:
            outcome, method = {"state": "unreadable", "reasons": ["unsupported_format"], "text": ""}, "none"
        del data
        text, cut = _keep(outcome["text"])
        reasons = list(outcome["reasons"])
        if cut and "truncated" not in reasons:
            reasons.append("truncated")
        state = outcome["state"]
        if state == "complete" and reasons:
            state = "partial"
        if not set(reasons) <= REASONS or state not in STATES:
            raise SourceReadingError("unavailable")
        blob = None
        if text:
            # the kept text is its own content-addressed blob, so a deletion can erase it
            try:
                blob = self.domain.put_blob(text.encode("utf-8"), purpose=TEXT_PURPOSE)
            except ErasedBlob:
                # these exact characters were deleted by the owner before: never stored again
                text, state, reasons, blob = "", "unreadable", ["deleted"], None
        with _writer(), self.domain._connection(write=True) as db:
            actor = _authenticate_owner(self.owner, request, db)
            roots = self.domain._read_roots(db)
            _index(db)
            replay = journal.lookup(db, roots.genesis.id, command_id)
            if replay is not None:
                if replay["fingerprint"] != digest:
                    raise SourceReadingError("conflict")
                ref = EntityRef.from_dict(journal.receipt(replay)["reading_ref"])
                return self._replayed(db, roots, ref)
            _, refs = self._membership(db, roots, work_id)
            if source_ref.as_dict() not in refs:
                raise SourceReadingError("not_found")
            actor_ref = _owner_actor_ref(db, actor)
            stamp = _stamp()
            record = ImmutableRecord.create(
                kind="extraction", id=reading_id, version=1, created_at_utc=stamp, actor_ref=actor_ref,
                parent_refs=(source_ref, artifact.ref), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content={"schema_version": READING_SCHEMA, "work_id": work_id,
                         "source_ref": source_ref.as_dict(), "artifact_sha256": original["sha256"],
                         "method": method, "state": state, "reasons": reasons,
                         "text_blob_ref": None if blob is None else blob.as_dict(),
                         "kept_characters": len(text), "page_count": outcome.get("page_count"),
                         "pages_without_text": outcome.get("pages_without_text"),
                         "command_id": command_id})
            self.domain._put_in_transaction(db, record)
            db.execute("INSERT INTO source_readings_v1(vault_id, work_id, source_id, reading_id, sha256) "
                       "VALUES (?,?,?,?,?)", (roots.genesis.id, work_id, source_ref.id, reading_id,
                                              record.ref.sha256))
            if state == "unreadable":
                event, metadata = "ingestion.failed", {"reason_code": _GAP[reasons[0]]}
            else:
                omitted = (outcome.get("pages_without_text") or 0) + (1 if "truncated" in reasons else 0)
                event, metadata = "ingestion.completed", {"supplied_count": len(text), "omitted_count": omitted,
                                                          "complete": state == "complete"}
            _append_event_in_transaction(
                db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp, actor_kind="human",
                actor_ref=actor_ref, event_type=event,
                object_refs=(ObjectRef(record.ref.kind, record.ref.id, record.ref.version, record.ref.sha256),),
                correlation_id=command_id, causation_id=None, status="failed" if state == "unreadable" else "succeeded",
                error_code=None, public_metadata=metadata, private_evidence_refs=(), retention_class="core",
                policy_ref=roots.access_policy)
            journal.save(db, roots.genesis.id, command_id, digest, {"reading_ref": record.ref.as_dict()})
            return _view(self.domain._load(db, record.ref, roots)[0], text)

    def _replayed(self, db, roots, ref):
        record = self.domain._load(db, ref, roots)[0]
        return _view(record, reading_text(self.domain, db, roots, record))
