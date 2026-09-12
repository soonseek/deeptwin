"""Strict local command envelopes and a fail-closed durable idempotency journal.

The journal commits an ``executing`` intent before invoking a handler.  A crash or handler
error is never permission to invoke that command again: the outcome remains unknown until a
separate reconciliation path resolves it.  Local domain handlers that require true atomic
state+receipt commits use the root transaction coordinator; this standalone journal remains
the conservative boundary for effects that cannot share the local SQLite transaction.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import sqlite3

from ..domain.refs import (
    DomainContractError,
    LOCATOR_KINDS,
    MAX_INTEGER,
    ObjectRef,
    canonical_json,
    parse_canonical,
    positive_integer,
    uuid_string,
)
from ..domain.schemas import Actor
from .session import AuthenticatedRequest


COMMAND_VERSION = "command-v1"
RESULT_STATES = frozenset({"accepted", "pending", "completed", "blocked", "cancelled",
                           "outcome_unknown"})
LINK_NAMES = frozenset({"self", "status", "events", "snapshot"})
_COMMAND_KEYS = frozenset({
    "schema_version", "command_id", "command_type", "target",
    "expected_revision", "target_hash", "args",
})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMAND_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\.[a-z][a-z0-9_]{0,63}")


class CommandError(ValueError):
    pass


class CommandInvalid(CommandError):
    pass


class CommandConflict(CommandError):
    pass


class CommandOutcomeUnknown(CommandError):
    pass


class CommandCorrupt(CommandError):
    pass


@dataclass(frozen=True, slots=True)
class ArgField:
    name: str
    kind: str
    required: bool = True
    max_bytes: int = 65_536
    values: tuple[str, ...] = ()

    def __post_init__(self):
        if (type(self.name) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.name) is None
                or self.kind not in {"text", "uuid", "positive_integer", "boolean", "sha256", "enum"}
                or type(self.required) is not bool
                or type(self.max_bytes) is not int or not 1 <= self.max_bytes <= 65_536):
            raise ValueError("Invalid command argument field")
        if self.kind == "enum":
            if (type(self.values) is not tuple or not self.values or len(self.values) > 64
                    or len(self.values) != len(set(self.values))
                    or any(type(value) is not str or not value or len(value) > 128
                           for value in self.values)):
                raise ValueError("Enum arguments require bounded unique values")
        elif self.values:
            raise ValueError("Only enum arguments accept values")

    def validate(self, value):
        try:
            if self.kind == "text":
                if type(value) is not str or len(value.encode("utf-8")) > self.max_bytes:
                    raise ValueError
            elif self.kind == "uuid":
                uuid_string(value)
            elif self.kind == "positive_integer":
                positive_integer(value)
            elif self.kind == "boolean":
                if type(value) is not bool:
                    raise ValueError
            elif self.kind == "sha256":
                if type(value) is not str or _SHA256.fullmatch(value) is None:
                    raise ValueError
            elif type(value) is not str or value not in self.values:
                raise ValueError
        except (ValueError, UnicodeError, DomainContractError) as exc:
            raise CommandInvalid(f"Invalid command argument: {self.name}") from exc
        return value


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    command_type: str
    target_kind: str | None
    revision: str
    target_hash: str
    arguments: tuple[ArgField, ...]

    def __post_init__(self):
        if type(self.command_type) is not str or _COMMAND_NAME.fullmatch(self.command_type) is None:
            raise ValueError("Command type must be a bounded category.action")
        if self.target_kind is not None and self.target_kind not in LOCATOR_KINDS:
            raise ValueError("Command target kind is not registered")
        if self.revision not in {"required", "optional", "forbidden"}:
            raise ValueError("Invalid revision rule")
        if self.target_hash not in {"required", "optional", "forbidden"}:
            raise ValueError("Invalid target hash rule")
        if (type(self.arguments) is not tuple or len(self.arguments) > 64
                or any(type(field) is not ArgField for field in self.arguments)
                or len({field.name for field in self.arguments}) != len(self.arguments)):
            raise ValueError("Command arguments must be a bounded exact tuple")

    def validate(self, *, target, expected_revision, target_hash, arguments):
        if self.target_kind is None:
            if target is not None:
                raise CommandInvalid("This command has no target")
        elif type(target) is not dict or set(target) != {"kind", "id"}:
            raise CommandInvalid("Command target must be an exact locator")
        else:
            try:
                target = ObjectRef(target["kind"], target["id"])
            except (DomainContractError, TypeError) as exc:
                raise CommandInvalid("Command target is invalid") from exc
            if target.kind != self.target_kind:
                raise CommandInvalid("Command target kind differs from its definition")

        expected_revision = _conditional_value(
            expected_revision, self.revision, positive_integer, "expected revision")
        target_hash = _conditional_value(
            target_hash, self.target_hash,
            lambda value: value if type(value) is str and _SHA256.fullmatch(value) else _raise(),
            "target hash",
        )
        if type(arguments) is not dict:
            raise CommandInvalid("Command arguments must be an object")
        fields = {field.name: field for field in self.arguments}
        required = {field.name for field in self.arguments if field.required}
        if not required <= set(arguments) or set(arguments) - fields.keys():
            raise CommandInvalid("Command arguments do not match their exact schema")
        result = {name: fields[name].validate(value) for name, value in arguments.items()}
        canonical_json(result)
        return target, expected_revision, target_hash, result


def _raise():
    raise ValueError


def _conditional_value(value, rule, validator, label):
    if rule == "forbidden":
        if value is not None:
            raise CommandInvalid(f"Command {label} is forbidden")
        return None
    if value is None:
        if rule == "required":
            raise CommandInvalid(f"Command {label} is required")
        return None
    try:
        return validator(value)
    except (ValueError, DomainContractError, TypeError) as exc:
        raise CommandInvalid(f"Command {label} is invalid") from exc


class CommandRegistry:
    """Frozen trusted definitions; browser/model input cannot register command kinds."""

    def __init__(self, definitions):
        if type(definitions) is not tuple or not definitions or len(definitions) > 256:
            raise ValueError("A bounded tuple of command definitions is required")
        if any(type(item) is not CommandDefinition for item in definitions):
            raise ValueError("Expected command definitions")
        values = {item.command_type: item for item in definitions}
        if len(values) != len(definitions):
            raise ValueError("Duplicate command definition")
        self._definitions = values

    def definition(self, command_type):
        try:
            return self._definitions[command_type]
        except (KeyError, TypeError) as exc:
            raise CommandInvalid("Command type is not registered") from exc


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    command_id: str
    command_type: str
    target: ObjectRef | None
    expected_revision: int | None
    target_hash: str | None
    arguments: dict

    @classmethod
    def from_mapping(cls, value, registry):
        if type(registry) is not CommandRegistry:
            raise TypeError("A trusted command registry is required")
        if type(value) is not dict or set(value) != _COMMAND_KEYS:
            raise CommandInvalid("Command envelope must match the exact schema")
        if value.get("schema_version") != COMMAND_VERSION:
            raise CommandInvalid("Unsupported command envelope version")
        try:
            command_id = uuid_string(value["command_id"])
        except (DomainContractError, TypeError) as exc:
            raise CommandInvalid("Command ID must be a canonical UUID") from exc
        definition = registry.definition(value["command_type"])
        target, revision, target_hash, arguments = definition.validate(
            target=value["target"], expected_revision=value["expected_revision"],
            target_hash=value["target_hash"], arguments=value["args"],
        )
        envelope = cls(command_id, definition.command_type, target, revision, target_hash, arguments)
        canonical_json(envelope.as_dict())
        return envelope

    @classmethod
    def from_bytes(cls, data, registry):
        try:
            value = parse_canonical(data)
        except DomainContractError as exc:
            raise CommandInvalid("Command bytes must use the canonical bounded encoding") from exc
        return cls.from_mapping(value, registry)

    def as_dict(self):
        return {
            "schema_version": COMMAND_VERSION,
            "command_id": self.command_id,
            "command_type": self.command_type,
            "target": None if self.target is None else self.target.as_dict(),
            "expected_revision": self.expected_revision,
            "target_hash": self.target_hash,
            "args": self.arguments.copy(),
        }

    @property
    def body_bytes(self):
        return canonical_json(self.as_dict())


def _object_ref(value):
    if type(value) is not dict or not {"kind", "id"} <= set(value) or set(value) - {
            "kind", "id", "version", "content_hash"}:
        raise CommandInvalid("Result object reference is invalid")
    try:
        return ObjectRef(value["kind"], value["id"], value.get("version"), value.get("content_hash"))
    except (DomainContractError, TypeError) as exc:
        raise CommandInvalid("Result object reference is invalid") from exc


def _result(envelope, value):
    required = {"state", "event_cursor", "links"}
    optional = {"object_ref", "revision"}
    if type(value) is not dict or not required <= set(value) or set(value) - required - optional:
        raise CommandInvalid("Command result must match its exact schema")
    if value["state"] not in RESULT_STATES:
        raise CommandInvalid("Command result state is invalid")
    cursor = value["event_cursor"]
    if (type(cursor) is not str or not cursor or len(cursor) > 2_048
            or any(ord(char) < 0x21 or ord(char) > 0x7e for char in cursor)):
        raise CommandInvalid("Command result cursor is invalid")
    links = value["links"]
    if (type(links) is not dict or set(links) - LINK_NAMES
            or any(type(name) is not str or type(path) is not str or len(path) > 512
                   or not path.startswith("/api/v1/") or any(char in path for char in "?#\\\r\n")
                   for name, path in links.items())):
        raise CommandInvalid("Command result links are invalid")
    object_ref = None if value.get("object_ref") is None else _object_ref(value["object_ref"])
    revision = value.get("revision")
    if revision is not None:
        try:
            positive_integer(revision)
        except DomainContractError as exc:
            raise CommandInvalid("Command result revision is invalid") from exc
    result = {
        "command_id": envelope.command_id,
        "state": value["state"],
        "event_cursor": cursor,
        "links": links.copy(),
    }
    if object_ref is not None:
        result["object_ref"] = object_ref.as_dict()
    if revision is not None:
        result["revision"] = revision
    canonical_json(result)
    return result


_DDL = """
CREATE TABLE IF NOT EXISTS api_command_migrations (
  version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_commands (
  vault_id TEXT NOT NULL,
  command_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload BLOB NOT NULL,
  actor_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('executing','completed','outcome_unknown')),
  result BLOB,
  error_code TEXT,
  started_at INTEGER NOT NULL,
  completed_at INTEGER,
  PRIMARY KEY(vault_id, command_id)
);
""".strip()
_MIGRATION_HASH = sha256(_DDL.encode("utf-8")).hexdigest()


def _normalize_schema_sql(value):
    if type(value) is not str:
        return ""
    compact = " ".join(value.split()).casefold().replace(" if not exists ", " ")
    return re.sub(r"\s*([(),=<>])\s*", r"\1", compact)


_COMMAND_DDL = tuple(
    statement.strip() for statement in _DDL.split(";") if statement.strip()
)
_EXPECTED_COMMAND_SCHEMA = {
    re.match(r"CREATE TABLE(?: IF NOT EXISTS)? ([a-z_]+)", statement).group(1):
        _normalize_schema_sql(statement)
    for statement in _COMMAND_DDL
}


def _assert_command_schema(db):
    """Validate the exact command journal inside a caller-owned transaction."""
    if type(db) is not sqlite3.Connection or not db.in_transaction:
        raise CommandCorrupt("Command schema requires an active SQLite transaction")
    names = tuple(sorted(_EXPECTED_COMMAND_SCHEMA))
    stored = {
        row[0]: _normalize_schema_sql(row[1])
        for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='table' AND name IN (?,?)",
            names,
        )
    }
    if stored != _EXPECTED_COMMAND_SCHEMA:
        raise CommandCorrupt("Command journal schema is inconsistent")
    rows = list(db.execute(
        "SELECT version,sha256 FROM api_command_migrations ORDER BY version"
    ))
    if [tuple(row) for row in rows] != [(1, _MIGRATION_HASH)]:
        raise CommandCorrupt("Unknown or corrupt command migration")
    unexpected = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' "
        "OR (type='index' AND lower(tbl_name) IN "
        "('api_commands','api_command_migrations') AND sql IS NOT NULL) LIMIT 1"
    ).fetchone()
    if unexpected is not None:
        raise CommandCorrupt("Unexpected command journal schema object")


def _install_command_schema(db):
    """Install once, or fail closed on a partial/unversioned caller-owned schema."""
    if type(db) is not sqlite3.Connection or not db.in_transaction:
        raise CommandCorrupt("Command schema installation requires an active transaction")
    present = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('api_command_migrations','api_commands')"
        )
    }
    if not present:
        for statement in _COMMAND_DDL:
            db.execute(statement)
        db.execute("INSERT INTO api_command_migrations VALUES (1,?)", (_MIGRATION_HASH,))
    elif present != set(_EXPECTED_COMMAND_SCHEMA):
        raise CommandCorrupt("Partial command journal schema")
    _assert_command_schema(db)


def _existing_command(db, *, vault_id, envelope, actor, session):
    """Return a completed exact receipt, or ``None`` for a new command."""
    row = db.execute(
        "SELECT * FROM api_commands WHERE vault_id=? AND command_id=?",
        (vault_id, envelope.command_id),
    ).fetchone()
    if row is None:
        return None
    payload_hash = sha256(envelope.body_bytes).hexdigest()
    if (row["payload_hash"] != payload_hash
            or bytes(row["payload"]) != envelope.body_bytes
            or row["actor_id"] != actor.id
            or row["session_id"] != session.session_id):
        raise CommandConflict("Command ID is already bound to another exact request")
    if row["state"] == "completed":
        try:
            value = parse_canonical(bytes(row["result"]))
            expected = _result(
                envelope,
                {key: item for key, item in value.items() if key != "command_id"},
            )
        except (DomainContractError, CommandInvalid, TypeError, AttributeError) as exc:
            raise CommandCorrupt("Stored command result is corrupt") from exc
        if value != expected:
            raise CommandCorrupt("Stored command result differs from its receipt")
        return expected
    if row["state"] in {"executing", "outcome_unknown"}:
        raise CommandOutcomeUnknown("Command may already have produced an effect; reconcile it")
    raise CommandCorrupt("Stored command state is invalid")


def _insert_command_intent(db, *, vault_id, envelope, actor, session, now):
    payload = envelope.body_bytes
    db.execute(
        "INSERT INTO api_commands(vault_id,command_id,payload_hash,payload,actor_id,"
        "session_id,state,started_at) VALUES (?,?,?,?,?,?,?,?)",
        (vault_id, envelope.command_id, sha256(payload).hexdigest(), payload,
         actor.id, session.session_id, "executing", now),
    )


def _complete_command(db, *, vault_id, envelope, receipt, now):
    result_bytes = canonical_json(receipt)
    changed = db.execute(
        "UPDATE api_commands SET state='completed',result=?,completed_at=? "
        "WHERE vault_id=? AND command_id=? AND state='executing' "
        "AND payload_hash=? AND payload=?",
        (result_bytes, now, vault_id, envelope.command_id,
         sha256(envelope.body_bytes).hexdigest(), envelope.body_bytes),
    ).rowcount
    if changed != 1:
        raise CommandCorrupt("Command receipt changed before result commit")


class CommandJournal:
    def __init__(self, path, *, vault_id, registry, authenticate_session, clock):
        self.path = Path(os.path.abspath(path))
        self.vault_id = uuid_string(vault_id)
        if type(registry) is not CommandRegistry:
            raise TypeError("A trusted command registry is required")
        if not callable(authenticate_session) or not callable(clock):
            raise TypeError("Session authentication and trusted clock are required")
        self.registry = registry
        self._authenticate_session = authenticate_session
        self._clock = clock
        self._last_now = None
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError("Command database cannot be a symlink")
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with self._connection(immediate=True) as db:
            db.executescript(_DDL)
            rows = db.execute("SELECT version,sha256 FROM api_command_migrations ORDER BY version").fetchall()
            if not rows:
                db.execute("INSERT INTO api_command_migrations VALUES (1,?)", (_MIGRATION_HASH,))
            elif [tuple(row) for row in rows] != [(1, _MIGRATION_HASH)]:
                raise CommandCorrupt("Unknown or corrupt command migration")

    def _now(self):
        value = self._clock()
        if type(value) is not int or not 0 <= value <= MAX_INTEGER:
            raise CommandInvalid("Trusted command clock is unavailable")
        if self._last_now is not None and value < self._last_now:
            raise CommandInvalid("Trusted command clock moved backwards")
        self._last_now = value
        return value

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

    def _existing(self, db, envelope, actor, session):
        row = db.execute(
            "SELECT * FROM api_commands WHERE vault_id=? AND command_id=?",
            (self.vault_id, envelope.command_id),
        ).fetchone()
        if row is None:
            return None
        payload_hash = sha256(envelope.body_bytes).hexdigest()
        if (row["payload_hash"] != payload_hash or bytes(row["payload"]) != envelope.body_bytes
                or row["actor_id"] != actor.id or row["session_id"] != session.session_id):
            raise CommandConflict("Command ID is already bound to another exact request")
        if row["state"] == "completed":
            try:
                value = parse_canonical(bytes(row["result"]))
                expected = _result(envelope, {key: item for key, item in value.items()
                    if key != "command_id"})
            except (DomainContractError, CommandInvalid, TypeError, AttributeError) as exc:
                raise CommandCorrupt("Stored command result is corrupt") from exc
            if value != expected:
                raise CommandCorrupt("Stored command result differs from its receipt")
            return expected
        if row["state"] in {"executing", "outcome_unknown"}:
            raise CommandOutcomeUnknown("Command may already have produced an effect; reconcile it")
        raise CommandCorrupt("Stored command state is invalid")

    def execute(self, value, *, request, handler):
        if type(request) is not AuthenticatedRequest or request.is_read or not request.csrf_verified:
            raise CommandInvalid("Only an authenticated state-changing request can dispatch")
        actor = self._authenticate_session(request.session)
        if type(actor) is not Actor or actor != request.session.actor or actor.kind != "human":
            raise CommandInvalid("Command actor is not an authenticated local human")
        if not callable(handler):
            raise TypeError("A trusted command handler is required")
        envelope = value if type(value) is CommandEnvelope else CommandEnvelope.from_mapping(value, self.registry)
        # Revalidate instances so a hand-constructed dataclass cannot bypass the registry.
        envelope = CommandEnvelope.from_bytes(envelope.body_bytes, self.registry)
        payload = envelope.body_bytes
        payload_hash = sha256(payload).hexdigest()
        now = self._now()

        with self._connection(immediate=True) as db:
            existing = self._existing(db, envelope, actor, request.session)
            if existing is not None:
                return existing
            db.execute(
                "INSERT INTO api_commands(vault_id,command_id,payload_hash,payload,actor_id,"
                "session_id,state,started_at) VALUES (?,?,?,?,?,?,?,?)",
                (self.vault_id, envelope.command_id, payload_hash, payload, actor.id,
                 request.session.session_id, "executing", now),
            )

        try:
            completed = _result(envelope, handler(envelope))
            result_bytes = canonical_json(completed)
        except Exception as exc:
            with self._connection(immediate=True) as db:
                row = db.execute(
                    "SELECT state,payload_hash FROM api_commands WHERE vault_id=? AND command_id=?",
                    (self.vault_id, envelope.command_id),
                ).fetchone()
                if row is None or row["payload_hash"] != payload_hash:
                    raise CommandCorrupt("Command intent disappeared during execution") from exc
                if row["state"] == "executing":
                    db.execute(
                        "UPDATE api_commands SET state='outcome_unknown',error_code=?,completed_at=? "
                        "WHERE vault_id=? AND command_id=?",
                        ("handler_outcome_unknown", self._now(), self.vault_id, envelope.command_id),
                    )
            raise CommandOutcomeUnknown(
                "Command handler outcome is unknown; it will not be automatically retried") from exc

        with self._connection(immediate=True) as db:
            row = db.execute(
                "SELECT state,payload_hash FROM api_commands WHERE vault_id=? AND command_id=?",
                (self.vault_id, envelope.command_id),
            ).fetchone()
            if row is None or row["payload_hash"] != payload_hash or row["state"] != "executing":
                raise CommandCorrupt("Command receipt changed before result commit")
            db.execute(
                "UPDATE api_commands SET state='completed',result=?,completed_at=? "
                "WHERE vault_id=? AND command_id=?",
                (result_bytes, self._now(), self.vault_id, envelope.command_id),
            )
        return completed
