"""Durable typed event envelopes and bounded public cursor projections.

The browser never receives stored actor, policy, vault, or private-evidence references.
Cursor tokens are resumable locators, not authority: authentication remains mandatory and
each token binds the exact vault, stream generation, and event-type filter.
"""

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .events import EVENT_TYPES, event_metadata
from .refs import (
    DomainContractError,
    EntityRef,
    MAX_INTEGER,
    ObjectRef,
    canonical_json,
    parse_canonical,
    positive_integer,
    uuid_string,
)
from .schemas import Actor
from .request_identity import AuthenticatedRequest


EVENT_VERSION = "event-envelope-v1"
CURSOR_VERSION = "public-event-cursor-v1"
MAX_PUBLIC_PAGE = 100
MAX_SCAN_ROWS = 500
MAX_REFS = 64
STATUSES = frozenset({"pending", "started", "progress", "succeeded", "failed", "blocked",
                      "cancelled", "unknown"})
ERROR_CODES = frozenset({
    "invalid_input", "unauthenticated", "access_denied", "stale_state", "not_found",
    "capacity_exhausted", "dependency_unavailable", "storage_failed", "corrupt", "missing",
    "outcome_unknown", "budget_exhausted", "cancelled",
})
RETENTION_CLASSES = frozenset({"core", "diagnostic", "cache"})
ACTOR_KINDS = frozenset({"human", "system", "provider", "service_client", "test_actor"})
GAP_REASONS = frozenset({"missing", "deleted", "corrupt", "storage_failed", "generation_changed"})
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")
_ENVELOPE_KEYS = frozenset({
    "schema_version", "event_id", "vault_id", "sequence", "observed_at_utc",
    "recorded_at_utc", "actor_kind", "actor_ref", "event_type", "object_refs",
    "correlation_id", "causation_id", "status", "error_code", "public_metadata",
    "private_evidence_refs", "retention_class", "policy_ref",
})


class EventBoundaryError(ValueError):
    pass


class EventInvalid(EventBoundaryError):
    pass


class EventCorrupt(EventBoundaryError):
    pass


class CursorMismatch(EventBoundaryError):
    pass


def _timestamp(value):
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise EventInvalid("Expected an exact UTC event timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise EventInvalid("Invalid UTC event timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise EventInvalid("Event timestamp must be UTC")
    return value


def _at_epoch(value):
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise EventInvalid("Trusted event clock is unavailable")
    try:
        return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (OverflowError, OSError, ValueError) as exc:
        raise EventInvalid("Trusted event clock is out of range") from exc


def _entity(value):
    if type(value) is EntityRef:
        return value
    try:
        return EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise EventInvalid("Event entity reference is invalid") from exc


def _object(value):
    if type(value) is ObjectRef:
        return value
    if type(value) is not dict or not {"kind", "id"} <= set(value) or set(value) - {
            "kind", "id", "version", "content_hash"}:
        raise EventInvalid("Event object reference is invalid")
    try:
        return ObjectRef(value["kind"], value["id"], value.get("version"), value.get("content_hash"))
    except (DomainContractError, TypeError) as exc:
        raise EventInvalid("Event object reference is invalid") from exc


def _unique_tuple(values, parser, label):
    if type(values) not in (tuple, list) or len(values) > MAX_REFS:
        raise EventInvalid(f"{label} must be a bounded reference list")
    result = tuple(parser(value) for value in values)
    if len(result) != len(set(result)):
        raise EventInvalid(f"{label} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    vault_id: str
    sequence: int
    observed_at_utc: str
    recorded_at_utc: str
    actor_kind: str
    actor_ref: EntityRef
    event_type: str
    object_refs: tuple[ObjectRef, ...]
    correlation_id: str
    causation_id: str | None
    status: str
    error_code: str | None
    public_metadata: dict
    private_evidence_refs: tuple[EntityRef, ...]
    retention_class: str
    policy_ref: EntityRef

    @classmethod
    def create(cls, *, event_id, vault_id, sequence, observed_at_utc, recorded_at_utc,
               actor_kind, actor_ref, event_type, object_refs, correlation_id,
               causation_id, status, error_code, public_metadata,
               private_evidence_refs, retention_class, policy_ref):
        try:
            event_id = uuid_string(event_id)
            vault_id = uuid_string(vault_id)
            sequence = positive_integer(sequence)
            correlation_id = uuid_string(correlation_id)
            if causation_id is not None:
                causation_id = uuid_string(causation_id)
        except DomainContractError as exc:
            raise EventInvalid("Event identity or sequence is invalid") from exc
        _timestamp(observed_at_utc)
        _timestamp(recorded_at_utc)
        actor_ref = _entity(actor_ref)
        if actor_kind not in ACTOR_KINDS or actor_ref.kind != "actor":
            raise EventInvalid("Event actor provenance is invalid")
        if type(event_type) is not str or event_type not in EVENT_TYPES:
            raise EventInvalid("Event type is not registered")
        object_refs = _unique_tuple(object_refs, _object, "Object references")
        if status not in STATUSES:
            raise EventInvalid("Event status is not registered")
        if error_code is not None and error_code not in ERROR_CODES:
            raise EventInvalid("Event error code is not registered")
        if status not in {"failed", "blocked", "unknown"} and error_code is not None:
            raise EventInvalid("Successful events cannot carry an error code")
        try:
            public_metadata = event_metadata(event_type, public_metadata)
        except DomainContractError as exc:
            raise EventInvalid("Event public metadata is invalid") from exc
        private_evidence_refs = _unique_tuple(
            private_evidence_refs, _entity, "Private evidence references")
        if retention_class not in RETENTION_CLASSES:
            raise EventInvalid("Event retention class is not registered")
        policy_ref = _entity(policy_ref)
        if policy_ref.kind != "access_policy":
            raise EventInvalid("Event policy reference must bind an access policy")
        result = cls(
            event_id, vault_id, sequence, observed_at_utc, recorded_at_utc,
            actor_kind, actor_ref, event_type, object_refs, correlation_id,
            causation_id, status, error_code, public_metadata,
            private_evidence_refs, retention_class, policy_ref,
        )
        canonical_json(result.as_dict())
        return result

    @classmethod
    def from_mapping(cls, value):
        if type(value) is not dict or set(value) != _ENVELOPE_KEYS:
            raise EventInvalid("Stored event envelope has the wrong fields")
        if value.get("schema_version") != EVENT_VERSION:
            raise EventInvalid("Stored event envelope version is unsupported")
        return cls.create(**{key: item for key, item in value.items() if key != "schema_version"})

    @classmethod
    def from_bytes(cls, value):
        try:
            decoded = parse_canonical(value)
        except DomainContractError as exc:
            raise EventInvalid("Stored event envelope is not canonical") from exc
        return cls.from_mapping(decoded)

    def as_dict(self):
        return {
            "schema_version": EVENT_VERSION,
            "event_id": self.event_id,
            "vault_id": self.vault_id,
            "sequence": self.sequence,
            "observed_at_utc": self.observed_at_utc,
            "recorded_at_utc": self.recorded_at_utc,
            "actor_kind": self.actor_kind,
            "actor_ref": self.actor_ref.as_dict(),
            "event_type": self.event_type,
            "object_refs": [item.as_dict() for item in self.object_refs],
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "status": self.status,
            "error_code": self.error_code,
            "public_metadata": self.public_metadata.copy(),
            "private_evidence_refs": [item.as_dict() for item in self.private_evidence_refs],
            "retention_class": self.retention_class,
            "policy_ref": self.policy_ref.as_dict(),
        }

    @property
    def body_bytes(self):
        return canonical_json(self.as_dict())

    def public_view(self):
        return PublicEventView(
            self.event_id, self.sequence, self.observed_at_utc, self.event_type,
            self.object_refs, self.status, self.error_code, self.public_metadata.copy(),
        )


@dataclass(frozen=True, slots=True)
class PublicEventView:
    event_id: str
    sequence: int
    observed_at_utc: str
    event_type: str
    object_refs: tuple[ObjectRef, ...]
    status: str
    error_code: str | None
    public_metadata: dict

    def as_dict(self):
        try:
            uuid_string(self.event_id)
            positive_integer(self.sequence)
            _timestamp(self.observed_at_utc)
            if self.event_type not in EVENT_TYPES or self.status not in STATUSES:
                raise EventInvalid("Public event enum is invalid")
            if self.error_code is not None and self.error_code not in ERROR_CODES:
                raise EventInvalid("Public event error code is invalid")
            object_refs = _unique_tuple(self.object_refs, _object, "Public object references")
            metadata = event_metadata(self.event_type, self.public_metadata)
        except (DomainContractError, EventInvalid, TypeError) as exc:
            raise EventCorrupt("Public event view no longer matches its allowlist") from exc
        value = {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "observed_at_utc": self.observed_at_utc,
            "event_type": self.event_type,
            "object_refs": [item.as_dict() for item in object_refs],
            "status": self.status,
            "public_metadata": metadata,
        }
        if self.error_code is not None:
            value["error_code"] = self.error_code
        return value


@dataclass(frozen=True, slots=True)
class GapView:
    reason: str
    from_sequence: int
    to_sequence: int

    def as_dict(self):
        return {
            "reason": self.reason,
            "from_sequence": self.from_sequence,
            "to_sequence": self.to_sequence,
        }


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[PublicEventView, ...]
    next_cursor: str
    snapshot_required: bool
    gap: GapView | None
    event_cursors: tuple[str, ...]


def _filter(event_types):
    if type(event_types) not in (tuple, list) or len(event_types) > 64:
        raise EventInvalid("Event filter must be a bounded list")
    if any(type(value) is not str or value not in EVENT_TYPES for value in event_types):
        raise EventInvalid("Event filter contains an unregistered type")
    values = tuple(sorted(set(event_types)))
    if len(values) != len(event_types):
        raise EventInvalid("Event filter must be unique")
    digest = sha256(canonical_json(list(values))).hexdigest()
    return values, digest


def _cursor_body(*, vault_id, stream_id, generation, sequence, filter_hash):
    return canonical_json({
        "schema_version": CURSOR_VERSION,
        "vault_id": vault_id,
        "stream_id": stream_id,
        "generation": generation,
        "sequence": sequence,
        "filter_hash": filter_hash,
    })


def _encode_cursor(**values):
    body = _cursor_body(**values)
    raw = len(body).to_bytes(2, "big") + body + sha256(b"deeptwin-public-cursor-v1\0" + body).digest()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value):
    if type(value) is not str or not 32 <= len(value) <= 1_024 or not value.isascii():
        raise CursorMismatch("Event cursor is invalid")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if len(raw) < 35:
            raise ValueError
        length = int.from_bytes(raw[:2], "big")
        body, digest = raw[2:2 + length], raw[2 + length:]
        if len(body) != length or len(digest) != 32:
            raise ValueError
        expected = sha256(b"deeptwin-public-cursor-v1\0" + body).digest()
        if digest != expected:
            raise ValueError
        result = parse_canonical(body)
    except (ValueError, DomainContractError, UnicodeError) as exc:
        raise CursorMismatch("Event cursor is invalid") from exc
    if type(result) is not dict or set(result) != {
            "schema_version", "vault_id", "stream_id", "generation", "sequence", "filter_hash"}:
        raise CursorMismatch("Event cursor has the wrong fields")
    if result["schema_version"] != CURSOR_VERSION:
        raise CursorMismatch("Event cursor version is unsupported")
    try:
        uuid_string(result["vault_id"])
        uuid_string(result["stream_id"])
    except DomainContractError as exc:
        raise CursorMismatch("Event cursor identity is invalid") from exc
    if (type(result["generation"]) is not int or result["generation"] < 1
            or type(result["sequence"]) is not int or result["sequence"] < 0
            or type(result["filter_hash"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", result["filter_hash"]) is None):
        raise CursorMismatch("Event cursor values are invalid")
    return result


_DDL = """
CREATE TABLE IF NOT EXISTS api_event_migrations (
  version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_event_streams (
  vault_id TEXT PRIMARY KEY,
  stream_id TEXT NOT NULL UNIQUE,
  generation INTEGER NOT NULL CHECK(generation > 0),
  next_sequence INTEGER NOT NULL CHECK(next_sequence > 0),
  first_available_sequence INTEGER NOT NULL CHECK(first_available_sequence > 0),
  gap_reason TEXT
);
CREATE TABLE IF NOT EXISTS api_event_envelopes (
  vault_id TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK(sequence > 0),
  event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  envelope BLOB NOT NULL,
  PRIMARY KEY(vault_id, sequence),
  FOREIGN KEY(vault_id) REFERENCES api_event_streams(vault_id)
);
CREATE INDEX IF NOT EXISTS api_event_type_sequence
  ON api_event_envelopes(vault_id, event_type, sequence);
""".strip()
_MIGRATION_HASH = sha256(_DDL.encode("utf-8")).hexdigest()


def _normalize_schema_sql(value):
    if type(value) is not str:
        return ""
    compact = " ".join(value.split()).casefold().replace(" if not exists ", " ")
    return re.sub(r"\s*([(),=<>])\s*", r"\1", compact)


_EVENT_DDL = tuple(statement.strip() for statement in _DDL.split(";") if statement.strip())
_EXPECTED_EVENT_SCHEMA = {}
for _statement in _EVENT_DDL:
    _match = re.match(r"CREATE (TABLE|INDEX)(?: IF NOT EXISTS)? ([a-z_]+)", _statement)
    if _match is None:  # pragma: no cover - module constant invariant
        raise RuntimeError("Invalid public event schema statement")
    _EXPECTED_EVENT_SCHEMA[_match.group(2)] = (
        _match.group(1).casefold(), _normalize_schema_sql(_statement)
    )


def _assert_event_schema(db, vault_id):
    if type(db) is not sqlite3.Connection or not db.in_transaction:
        raise EventCorrupt("Public event schema requires an active SQLite transaction")
    vault_id = uuid_string(vault_id)
    names = tuple(sorted(_EXPECTED_EVENT_SCHEMA))
    stored = {
        row["name"]: (row["type"], _normalize_schema_sql(row["sql"]))
        for row in db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name IN (?,?,?,?)", names
        )
    }
    if stored != _EXPECTED_EVENT_SCHEMA:
        raise EventCorrupt("Public event schema is inconsistent")
    rows = list(db.execute(
        "SELECT version,sha256 FROM api_event_migrations ORDER BY version"
    ))
    if [tuple(row) for row in rows] != [(1, _MIGRATION_HASH)]:
        raise EventCorrupt("Unknown or corrupt event migration")
    unexpected = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' "
        "OR (type='index' AND lower(tbl_name) IN "
        "('api_event_migrations','api_event_streams','api_event_envelopes') "
        "AND sql IS NOT NULL AND lower(name)<>'api_event_type_sequence') LIMIT 1"
    ).fetchone()
    if unexpected is not None:
        raise EventCorrupt("Unexpected public event schema object")
    _event_stream(db, vault_id)


def _install_event_schema(db, vault_id):
    if type(db) is not sqlite3.Connection or not db.in_transaction:
        raise EventCorrupt("Public event installation requires an active transaction")
    vault_id = uuid_string(vault_id)
    names = tuple(sorted(_EXPECTED_EVENT_SCHEMA))
    present = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE name IN (?,?,?,?)", names
        )
    }
    if not present:
        for statement in _EVENT_DDL:
            db.execute(statement)
        db.execute("INSERT INTO api_event_migrations VALUES (1,?)", (_MIGRATION_HASH,))
    elif present != set(_EXPECTED_EVENT_SCHEMA):
        raise EventCorrupt("Partial public event schema")
    row = db.execute(
        "SELECT stream_id FROM api_event_streams WHERE vault_id=?", (vault_id,)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO api_event_streams VALUES (?,?,?,?,?,NULL)",
            (vault_id, str(uuid4()), 1, 1, 1),
        )
    _assert_event_schema(db, vault_id)


def _event_stream(db, vault_id):
    row = db.execute(
        "SELECT * FROM api_event_streams WHERE vault_id=?", (vault_id,)
    ).fetchone()
    if row is None:
        raise EventCorrupt("Event stream identity is missing")
    try:
        uuid_string(row["stream_id"])
    except (DomainContractError, TypeError) as exc:
        raise EventCorrupt("Event stream identity is invalid") from exc
    if (type(row["generation"]) is not int or row["generation"] < 1
            or type(row["next_sequence"]) is not int or row["next_sequence"] < 1
            or type(row["first_available_sequence"]) is not int
            or not 1 <= row["first_available_sequence"] <= row["next_sequence"]
            or row["gap_reason"] is not None and row["gap_reason"] not in GAP_REASONS):
        raise EventCorrupt("Event stream counters are corrupt")
    return row


def _cursor_for(vault_id, stream, sequence, filter_hash):
    return _encode_cursor(
        vault_id=vault_id,
        stream_id=stream["stream_id"],
        generation=stream["generation"],
        sequence=sequence,
        filter_hash=filter_hash,
    )


def _append_event_in_transaction(db, *, vault_id, recorded_at_utc, observed_at_utc,
                                 actor_kind, actor_ref, event_type, object_refs,
                                 correlation_id, causation_id, status, error_code,
                                 public_metadata, private_evidence_refs,
                                 retention_class, policy_ref):
    _assert_event_schema(db, vault_id)
    stream = _event_stream(db, vault_id)
    sequence = stream["next_sequence"]
    envelope = EventEnvelope.create(
        event_id=str(uuid4()), vault_id=vault_id, sequence=sequence,
        observed_at_utc=observed_at_utc, recorded_at_utc=recorded_at_utc,
        actor_kind=actor_kind, actor_ref=actor_ref, event_type=event_type,
        object_refs=object_refs, correlation_id=correlation_id,
        causation_id=causation_id, status=status, error_code=error_code,
        public_metadata=public_metadata,
        private_evidence_refs=private_evidence_refs,
        retention_class=retention_class, policy_ref=policy_ref,
    )
    db.execute(
        "INSERT INTO api_event_envelopes VALUES (?,?,?,?,?)",
        (vault_id, sequence, envelope.event_id, envelope.event_type,
         envelope.body_bytes),
    )
    changed = db.execute(
        "UPDATE api_event_streams SET next_sequence=? "
        "WHERE vault_id=? AND next_sequence=?",
        (sequence + 1, vault_id, sequence),
    ).rowcount
    if changed != 1:
        raise EventCorrupt("Event stream sequence changed concurrently")
    return envelope


def _event_cursor_in_transaction(db, *, vault_id, sequence, event_types):
    _, filter_hash = _filter(event_types)
    stream = _event_stream(db, vault_id)
    if type(sequence) is not int or not 1 <= sequence < stream["next_sequence"]:
        raise EventCorrupt("Event cursor sequence is not committed in this transaction")
    return _cursor_for(vault_id, stream, sequence, filter_hash)


def _subject_filter_hash(filter_hash, subject):
    """The cursor's filter identity with a subject filter folded in; without one it is
    the event-type filter's own digest, so existing cursors keep their meaning."""
    if subject is None:
        return filter_hash
    kind, identity = subject
    if kind not in {"run", "work"}:
        raise EventInvalid("Event subject filter kind is unknown")
    try:
        identity = uuid_string(identity)
    except DomainContractError as exc:
        raise EventInvalid("Event subject filter is not a canonical UUID") from exc
    return sha256(canonical_json({"event_types_sha256": filter_hash, "subject_kind": kind,
                                  "subject_id": identity})).hexdigest()


def _read_events_in_transaction(db, *, vault_id, after_cursor=None,
                                event_types=(), limit=100, subject=None, match=None):
    """Read public projections and the matching cursor from one SQLite snapshot.

    `subject` (`("run"|"work", uuid)`) with its `match(envelope) -> bool` narrows the
    page to the envelopes the caller's predicate recognises from what each envelope
    carries (its object references, its correlation); the pair is part of the cursor's
    filter identity, so a cursor never crosses subjects."""
    _assert_event_schema(db, vault_id)
    if type(limit) is not int or not 1 <= limit <= MAX_PUBLIC_PAGE:
        raise EventInvalid("Public event page must contain 1..100 events")
    if (subject is None) != (match is None) or (match is not None and not callable(match)):
        raise EventInvalid("An event subject filter needs exactly its predicate")
    selected_types, filter_hash = _filter(event_types)
    filter_hash = _subject_filter_hash(filter_hash, subject)
    stream = _event_stream(db, vault_id)
    first = stream["first_available_sequence"]
    if after_cursor is None:
        sequence = first - 1
    else:
        cursor = _decode_cursor(after_cursor)
        if (cursor["vault_id"] != vault_id
                or cursor["stream_id"] != stream["stream_id"]
                or cursor["filter_hash"] != filter_hash):
            raise CursorMismatch("Event cursor belongs to another exact stream or filter")
        sequence = cursor["sequence"]
        if sequence >= stream["next_sequence"]:
            raise CursorMismatch("Event cursor is ahead of the durable stream")
        if cursor["generation"] != stream["generation"] or sequence < first - 1:
            start = sequence + 1
            end = max(start, first - 1)
            reason = stream["gap_reason"] or "generation_changed"
            return EventPage(
                (), _cursor_for(vault_id, stream, first - 1, filter_hash), True,
                GapView(reason, start, end), (),
            )

    rows = db.execute(
        "SELECT sequence,event_id,event_type,envelope FROM api_event_envelopes "
        "WHERE vault_id=? AND sequence>? AND sequence>=? ORDER BY sequence LIMIT ?",
        (vault_id, sequence, first, MAX_SCAN_ROWS),
    ).fetchall()
    expected = sequence + 1
    public = []
    cursors = []
    scanned = sequence
    for row in rows:
        if row["sequence"] != expected:
            return EventPage(
                (), _cursor_for(vault_id, stream, scanned, filter_hash), True,
                GapView("missing", expected, row["sequence"] - 1), (),
            )
        try:
            envelope = EventEnvelope.from_bytes(bytes(row["envelope"]))
        except EventInvalid as exc:
            raise EventCorrupt("Stored event envelope is corrupt") from exc
        if (envelope.vault_id != vault_id or envelope.sequence != row["sequence"]
                or envelope.event_id != row["event_id"]
                or envelope.event_type != row["event_type"]):
            raise EventCorrupt("Stored event index differs from its envelope")
        scanned = row["sequence"]
        expected = scanned + 1
        if ((not selected_types or envelope.event_type in selected_types)
                and (match is None or match(envelope) is True)):
            public.append(envelope.public_view())
            cursors.append(_cursor_for(vault_id, stream, scanned, filter_hash))
            if len(public) == limit:
                break
    if not rows and sequence < stream["next_sequence"] - 1:
        return EventPage(
            (), _cursor_for(vault_id, stream, sequence, filter_hash), True,
            GapView("missing", sequence + 1, stream["next_sequence"] - 1), (),
        )
    return EventPage(
        tuple(public), _cursor_for(vault_id, stream, scanned, filter_hash),
        False, None, tuple(cursors),
    )


class PublicEventJournal:
    def __init__(self, path, *, vault_id, authenticate_session, clock):
        self.path = Path(os.path.abspath(path))
        self.vault_id = uuid_string(vault_id)
        if not callable(authenticate_session) or not callable(clock):
            raise TypeError("Session authentication and trusted clock are required")
        self._authenticate_session = authenticate_session
        self._clock = clock
        self._last_now = None
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError("Event database cannot be a symlink")
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with self._connection(immediate=True) as db:
            db.executescript(_DDL)
            rows = db.execute("SELECT version,sha256 FROM api_event_migrations ORDER BY version").fetchall()
            if not rows:
                db.execute("INSERT INTO api_event_migrations VALUES (1,?)", (_MIGRATION_HASH,))
            elif [tuple(row) for row in rows] != [(1, _MIGRATION_HASH)]:
                raise EventCorrupt("Unknown or corrupt event migration")
            row = db.execute("SELECT stream_id FROM api_event_streams WHERE vault_id=?",
                             (self.vault_id,)).fetchone()
            if row is None:
                db.execute("INSERT INTO api_event_streams VALUES (?,?,?,?,?,NULL)",
                           (self.vault_id, str(uuid4()), 1, 1, 1))

    @contextmanager
    def _connection(self, *, immediate=False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _now(self):
        value = self._clock()
        if type(value) is not int or not 0 <= value <= MAX_INTEGER:
            raise EventInvalid("Trusted event clock is unavailable")
        if self._last_now is not None and value < self._last_now:
            raise EventInvalid("Trusted event clock moved backwards")
        self._last_now = value
        return value

    def append(self, *, observed_at_utc, actor_kind, actor_ref, event_type, object_refs,
               correlation_id, causation_id, status, error_code, public_metadata,
               private_evidence_refs, retention_class, policy_ref):
        recorded_at = _at_epoch(self._now())
        with self._connection(immediate=True) as db:
            stream = db.execute("SELECT * FROM api_event_streams WHERE vault_id=?",
                                (self.vault_id,)).fetchone()
            if stream is None:
                raise EventCorrupt("Event stream identity is missing")
            sequence = stream["next_sequence"]
            envelope = EventEnvelope.create(
                event_id=str(uuid4()), vault_id=self.vault_id, sequence=sequence,
                observed_at_utc=observed_at_utc, recorded_at_utc=recorded_at,
                actor_kind=actor_kind, actor_ref=actor_ref, event_type=event_type,
                object_refs=object_refs, correlation_id=correlation_id,
                causation_id=causation_id, status=status, error_code=error_code,
                public_metadata=public_metadata, private_evidence_refs=private_evidence_refs,
                retention_class=retention_class, policy_ref=policy_ref,
            )
            db.execute("INSERT INTO api_event_envelopes VALUES (?,?,?,?,?)",
                       (self.vault_id, sequence, envelope.event_id,
                        envelope.event_type, envelope.body_bytes))
            db.execute("UPDATE api_event_streams SET next_sequence=? WHERE vault_id=?",
                       (sequence + 1, self.vault_id))
            return envelope

    def _stream(self, db):
        row = db.execute("SELECT * FROM api_event_streams WHERE vault_id=?",
                         (self.vault_id,)).fetchone()
        if row is None:
            raise EventCorrupt("Event stream identity is missing")
        if (type(row["generation"]) is not int or row["generation"] < 1
                or type(row["next_sequence"]) is not int or row["next_sequence"] < 1
                or type(row["first_available_sequence"]) is not int
                or not 1 <= row["first_available_sequence"] <= row["next_sequence"]
                or row["gap_reason"] is not None and row["gap_reason"] not in GAP_REASONS):
            raise EventCorrupt("Event stream counters are corrupt")
        return row

    def _cursor(self, stream, sequence, filter_hash):
        return _encode_cursor(
            vault_id=self.vault_id, stream_id=stream["stream_id"],
            generation=stream["generation"], sequence=sequence, filter_hash=filter_hash,
        )

    def read(self, *, request, after_cursor=None, event_types=(), limit=100):
        if type(request) is not AuthenticatedRequest or not request.is_read:
            raise EventInvalid("Public event reads require an authenticated GET or HEAD")
        actor = self._authenticate_session(request.session)
        if type(actor) is not Actor or actor != request.session.actor or actor.kind != "human":
            raise EventInvalid("Public event reader is not an authenticated local human")
        if type(limit) is not int or not 1 <= limit <= MAX_PUBLIC_PAGE:
            raise EventInvalid("Public event page must contain 1..100 events")
        selected_types, filter_hash = _filter(event_types)

        with self._connection() as db:
            stream = self._stream(db)
            first = stream["first_available_sequence"]
            if after_cursor is None:
                sequence = first - 1
            else:
                cursor = _decode_cursor(after_cursor)
                if (cursor["vault_id"] != self.vault_id
                        or cursor["stream_id"] != stream["stream_id"]
                        or cursor["filter_hash"] != filter_hash):
                    raise CursorMismatch("Event cursor belongs to another exact stream or filter")
                sequence = cursor["sequence"]
                if sequence >= stream["next_sequence"]:
                    raise CursorMismatch("Event cursor is ahead of the durable stream")
                if cursor["generation"] != stream["generation"] or sequence < first - 1:
                    start = sequence + 1
                    end = max(start, first - 1)
                    reason = stream["gap_reason"] or "generation_changed"
                    return EventPage(
                        (), self._cursor(stream, first - 1, filter_hash), True,
                        GapView(reason, start, end), (),
                    )

            rows = db.execute(
                "SELECT sequence,event_id,event_type,envelope FROM api_event_envelopes "
                "WHERE vault_id=? AND sequence>? AND sequence>=? ORDER BY sequence LIMIT ?",
                (self.vault_id, sequence, first, MAX_SCAN_ROWS),
            ).fetchall()
            expected = sequence + 1
            public = []
            cursors = []
            scanned = sequence
            for row in rows:
                if row["sequence"] != expected:
                    return EventPage(
                        (), self._cursor(stream, scanned, filter_hash), True,
                        GapView("missing", expected, row["sequence"] - 1), (),
                    )
                try:
                    envelope = EventEnvelope.from_bytes(bytes(row["envelope"]))
                except EventInvalid as exc:
                    raise EventCorrupt("Stored event envelope is corrupt") from exc
                if (envelope.vault_id != self.vault_id or envelope.sequence != row["sequence"]
                        or envelope.event_id != row["event_id"]
                        or envelope.event_type != row["event_type"]):
                    raise EventCorrupt("Stored event index differs from its envelope")
                scanned = row["sequence"]
                expected = scanned + 1
                if not selected_types or envelope.event_type in selected_types:
                    public.append(envelope.public_view())
                    cursors.append(self._cursor(stream, scanned, filter_hash))
                    if len(public) == limit:
                        break
            if not rows and sequence < stream["next_sequence"] - 1:
                return EventPage(
                    (), self._cursor(stream, sequence, filter_hash), True,
                    GapView("missing", sequence + 1, stream["next_sequence"] - 1), (),
                )
            return EventPage(
                tuple(public), self._cursor(stream, scanned, filter_hash),
                False, None, tuple(cursors),
            )

    def declare_gap(self, *, first_available_sequence, reason):
        if type(first_available_sequence) is not int or first_available_sequence < 1:
            raise EventInvalid("Gap boundary must be a positive sequence")
        if reason not in GAP_REASONS - {"generation_changed"}:
            raise EventInvalid("Gap reason is not registered")
        with self._connection(immediate=True) as db:
            stream = self._stream(db)
            if not stream["first_available_sequence"] < first_available_sequence <= stream["next_sequence"]:
                raise EventInvalid("Gap boundary must advance within the durable stream")
            db.execute(
                "UPDATE api_event_streams SET generation=generation+1,"
                "first_available_sequence=?,gap_reason=? WHERE vault_id=?",
                (first_available_sequence, reason, self.vault_id),
            )
