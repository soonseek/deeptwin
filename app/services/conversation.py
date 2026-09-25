"""Durable shared conversation and target-bound command validation.

Chat text is evidence of what was said, not authority.  In particular, ordinary
acknowledgements never become alternatives, approvals, or executable commands.  A material
command is only *validated* here after a trusted local human, one current challenge, and one
exact immutable target agree.  The resulting receipt is still not proof that the downstream
domain command ran.
"""

import hmac
import re
import secrets
import time as _time
from dataclasses import dataclass
from datetime import UTC as _UTC
from datetime import datetime as _datetime
from functools import wraps as _wraps
from hashlib import sha256
from threading import RLock
from uuid import NAMESPACE_URL as _NAMESPACE_URL
from uuid import uuid4
from uuid import uuid5 as _uuid5

from ..domain.refs import (
    MAX_INTEGER,
    DomainContractError,
    EntityRef,
    ObjectRef,
    canonical_json,
    parse_canonical,
    positive_integer,
    uuid_string,
)
from ..storage import ConflictError, Store

SEMANTIC_ORIGINS = frozenset({
    "work_request",
    "clarification",
    "own_artifact",
    "analysis_evidence",
    "command_request",
})
ACTOR_KINDS = frozenset({"human", "agent", "system"})
AUTHORITIES = frozenset({"none", "local_human"})
INVOCATION_ROUTES = frozenset({"chat", "button"})
COMMAND_KINDS = frozenset({
    "action.approve",
    "design.prepare",
    "environment.activate",
    "environment.rollback",
    "promotion.activate",
    "run.cancel",
    "run.start",
})
_COMMAND_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}\.[a-z][a-z0-9_]{0,63}")
_MAX_MESSAGE_BYTES = 65_536
_MAX_REFERENCES = 64
_MAX_CHALLENGE_TTL_MS = 10 * 60 * 1000


class ConversationError(ValueError):
    pass


class ConversationConflict(ConversationError):
    pass


class ConversationAuthorityError(ConversationError):
    pass


@dataclass(frozen=True, slots=True)
class TrustedConversationActor:
    """Server-created actor context; browser JSON is never accepted in its place."""

    id: str
    kind: str
    authority: str = "none"

    def __post_init__(self):
        uuid_string(self.id)
        if self.kind not in ACTOR_KINDS or self.authority not in AUTHORITIES:
            raise ValueError("Invalid conversation actor")


_DDL = """
CREATE TABLE IF NOT EXISTS conversation_messages (
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL REFERENCES works(id),
  work_revision INTEGER NOT NULL CHECK(work_revision > 0),
  sequence INTEGER NOT NULL CHECK(sequence > 0),
  content TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  semantic_origin TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  actor_kind TEXT NOT NULL,
  referenced_entities BLOB NOT NULL,
  optional_command_id TEXT,
  exact_target BLOB,
  created_at_ms INTEGER NOT NULL,
  UNIQUE(work_id, sequence),
  FOREIGN KEY(optional_command_id) REFERENCES conversation_commands(id)
);
CREATE TABLE IF NOT EXISTS conversation_commands (
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL REFERENCES works(id),
  message_id TEXT NOT NULL UNIQUE REFERENCES conversation_messages(id),
  command_kind TEXT NOT NULL,
  exact_target BLOB NOT NULL,
  structured_args BLOB NOT NULL,
  proposer_id TEXT NOT NULL,
  proposer_kind TEXT NOT NULL,
  required_authority TEXT NOT NULL,
  validation_state TEXT NOT NULL CHECK(validation_state IN
    ('proposed','challenge_open','validated')),
  created_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_challenges (
  id TEXT PRIMARY KEY,
  command_id TEXT NOT NULL UNIQUE REFERENCES conversation_commands(id),
  token_sha256 TEXT NOT NULL,
  response_text TEXT NOT NULL,
  issued_to_actor_id TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER NOT NULL,
  consumed_at_ms INTEGER
);
CREATE TABLE IF NOT EXISTS conversation_validations (
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL REFERENCES works(id),
  command_id TEXT NOT NULL UNIQUE REFERENCES conversation_commands(id),
  challenge_id TEXT NOT NULL UNIQUE REFERENCES conversation_challenges(id),
  authority_actor_id TEXT NOT NULL,
  route TEXT NOT NULL,
  response_message_id TEXT REFERENCES conversation_messages(id),
  created_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_clock (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  last_ms INTEGER NOT NULL CHECK(last_ms >= 0)
);
""".strip()


def _exact_target(value):
    if type(value) is not ObjectRef or value.version is None or value.content_hash is None:
        raise ValueError("An exact versioned command target is required")
    return value


def _target_from_bytes(value):
    try:
        mapped = parse_canonical(bytes(value))
        if type(mapped) is not dict or set(mapped) != {
            "kind", "id", "version", "content_hash"
        }:
            raise DomainContractError("Expected exact target")
        return _exact_target(ObjectRef(**mapped))
    except (DomainContractError, TypeError, ValueError) as exc:
        raise ConversationConflict("Stored command target is invalid") from exc


def _references(value):
    if type(value) is not tuple or len(value) > _MAX_REFERENCES:
        raise ValueError("Referenced entities must be a bounded tuple")
    result = []
    identities = set()
    for item in value:
        if type(item) is not EntityRef:
            raise ValueError("Message references must be immutable entity references")
        identity = (item.kind, item.id, item.version, item.sha256)
        if identity in identities:
            raise ValueError("Duplicate message reference")
        identities.add(identity)
        result.append(item.as_dict())
    canonical_json(result)
    return result


def _reference_list(value):
    try:
        mapped = parse_canonical(bytes(value))
        if type(mapped) is not list or len(mapped) > _MAX_REFERENCES:
            raise DomainContractError("Invalid message references")
        result = [EntityRef.from_dict(item).as_dict() for item in mapped]
        if len({canonical_json(item) for item in result}) != len(result):
            raise DomainContractError("Duplicate message reference")
        return result
    except (DomainContractError, TypeError, ValueError) as exc:
        raise ConversationConflict("Stored message references are invalid") from exc


class Conversation:
    def __init__(self, store, *, clock_ms):
        if type(store) is not Store or not callable(clock_ms):
            raise TypeError("Conversation requires a Store and trusted clock")
        self.store = store
        self._clock = clock_ms
        self._clock_lock = RLock()
        self._last_now = None
        with self.store._connection() as db:
            db.executescript(_DDL)

    def _now(self, db=None):
        with self._clock_lock:
            value = self._clock()
            if type(value) is not int or not 0 <= value <= MAX_INTEGER:
                raise ConversationConflict("Conversation clock is unavailable")
            if self._last_now is not None and value < self._last_now:
                raise ConversationConflict("Conversation clock moved backwards")
            if db is not None:
                row = db.execute(
                    "SELECT last_ms FROM conversation_clock WHERE singleton=1"
                ).fetchone()
                if row is not None and (type(row["last_ms"]) is not int
                                        or value < row["last_ms"]):
                    raise ConversationConflict("Conversation clock moved backwards")
                db.execute(
                    "INSERT INTO conversation_clock VALUES (1,?) "
                    "ON CONFLICT(singleton) DO UPDATE SET last_ms=excluded.last_ms",
                    (value,),
                )
            self._last_now = value
            return value

    @staticmethod
    def _actor(value):
        if type(value) is not TrustedConversationActor:
            raise ConversationAuthorityError("Trusted conversation actor required")
        return value

    @staticmethod
    def _message_row(row):
        try:
            uuid_string(row["id"])
            uuid_string(row["work_id"])
            positive_integer(row["work_revision"])
            positive_integer(row["sequence"])
            if (type(row["content"]) is not str
                    or sha256(row["content"].encode("utf-8")).hexdigest()
                    != row["content_sha256"]
                    or row["semantic_origin"] not in SEMANTIC_ORIGINS
                    or row["actor_kind"] not in ACTOR_KINDS):
                raise ValueError
            uuid_string(row["actor_id"])
            optional = row["optional_command_id"]
            if optional is not None:
                uuid_string(optional)
            exact = None if row["exact_target"] is None else \
                _target_from_bytes(row["exact_target"]).as_dict()
            if (optional is None) != (exact is None):
                raise ValueError
            if optional is not None and row["semantic_origin"] != "command_request":
                raise ValueError
            created = row["created_at_ms"]
            if type(created) is not int or not 0 <= created <= MAX_INTEGER:
                raise ValueError
            return {
                "id": row["id"],
                "work_id": row["work_id"],
                "work_revision": row["work_revision"],
                "sequence": row["sequence"],
                "content": row["content"],
                "content_sha256": row["content_sha256"],
                "semantic_origin": row["semantic_origin"],
                "actor": {"id": row["actor_id"], "kind": row["actor_kind"]},
                "referenced_entity_refs": _reference_list(row["referenced_entities"]),
                "optional_command_ref": optional,
                "exact_target_ref": exact,
                "created_at_ms": created,
            }
        except (DomainContractError, UnicodeError, TypeError, ValueError) as exc:
            if isinstance(exc, ConversationConflict):
                raise
            raise ConversationConflict("Stored conversation message is invalid") from exc

    @staticmethod
    def _command_row(row):
        try:
            for name in ("id", "work_id", "message_id", "proposer_id"):
                uuid_string(row[name])
            if (_COMMAND_KIND.fullmatch(row["command_kind"]) is None
                    or row["command_kind"] not in COMMAND_KINDS
                    or row["proposer_kind"] not in ACTOR_KINDS
                    or row["required_authority"] not in AUTHORITIES - {"none"}
                    or row["validation_state"] not in {
                        "proposed", "challenge_open", "validated"
                    }):
                raise ValueError
            target = _target_from_bytes(row["exact_target"]).as_dict()
            arguments = parse_canonical(bytes(row["structured_args"]))
            if type(arguments) is not dict:
                raise ValueError
            created = row["created_at_ms"]
            if type(created) is not int or not 0 <= created <= MAX_INTEGER:
                raise ValueError
            return {
                "id": row["id"],
                "work_id": row["work_id"],
                "message_ref": row["message_id"],
                "command_kind": row["command_kind"],
                "exact_target_ref": target,
                "structured_args": arguments,
                "proposer": {
                    "id": row["proposer_id"], "kind": row["proposer_kind"]
                },
                "required_authority": row["required_authority"],
                "validation_state": row["validation_state"],
                "created_at_ms": created,
            }
        except (DomainContractError, TypeError, ValueError) as exc:
            if isinstance(exc, ConversationConflict):
                raise
            raise ConversationConflict("Stored proposed command is invalid") from exc

    @staticmethod
    def _assert_command_links(db, command):
        message = db.execute(
            "SELECT work_id,semantic_origin,actor_id,actor_kind,optional_command_id "
            "FROM conversation_messages WHERE id=?", (command["message_ref"],)
        ).fetchone()
        if (message is None or message["work_id"] != command["work_id"]
                or message["semantic_origin"] != "command_request"
                or message["actor_id"] != command["proposer"]["id"]
                or message["actor_kind"] != command["proposer"]["kind"]
                or message["optional_command_id"] is not None):
            raise ConversationConflict(
                "Stored command does not match its proposal message"
            )
        return message

    def _message_inputs(
        self,
        work_id,
        work_revision,
        content,
        *,
        semantic_origin,
        actor,
        referenced_entities,
        optional_command_id,
        exact_target,
    ):
        actor = self._actor(actor)
        try:
            uuid_string(work_id)
            positive_integer(work_revision)
        except DomainContractError as exc:
            raise ValueError("Message work binding is invalid") from exc
        if (type(content) is not str or not content or len(content) > 20_000):
            raise ValueError("Message text must contain 1..20,000 characters")
        try:
            encoded = content.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Message text is not valid Unicode") from exc
        if len(encoded) > _MAX_MESSAGE_BYTES or semantic_origin not in SEMANTIC_ORIGINS:
            raise ValueError("Message text or semantic origin is invalid")
        refs = _references(referenced_entities)
        if optional_command_id is None:
            if exact_target is not None:
                raise ValueError("A target requires an exact command reference")
            target_bytes = None
        else:
            try:
                uuid_string(optional_command_id)
            except DomainContractError as exc:
                raise ValueError("Message command reference is invalid") from exc
            if semantic_origin != "command_request":
                raise ValueError("Only a command request can reference a command")
            target_bytes = canonical_json(_exact_target(exact_target).as_dict())
        return actor, encoded, refs, target_bytes

    def _insert_message(
        self,
        db,
        work_id,
        work_revision,
        content,
        *,
        encoded,
        semantic_origin,
        actor,
        refs,
        optional_command_id,
        target_bytes,
    ):
        work = db.execute(
            "SELECT revision FROM works WHERE id=?", (work_id,)
        ).fetchone()
        if work is None:
            raise KeyError(work_id)
        if work["revision"] != work_revision:
            raise ConflictError("Message does not match current work revision")
        if optional_command_id is not None:
            command = db.execute(
                "SELECT work_id,exact_target FROM conversation_commands WHERE id=?",
                (optional_command_id,),
            ).fetchone()
            if (command is None or command["work_id"] != work_id
                    or not hmac.compare_digest(
                        bytes(command["exact_target"]), target_bytes
                    )):
                raise ConversationConflict(
                    "Message command target does not match the current proposal"
                )
        sequence = db.execute(
            "SELECT coalesce(max(sequence),0)+1 FROM conversation_messages "
            "WHERE work_id=?", (work_id,),
        ).fetchone()[0]
        positive_integer(sequence)
        message_id, now = str(uuid4()), self._now(db)
        db.execute(
            "INSERT INTO conversation_messages VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                message_id, work_id, work_revision, sequence, content,
                sha256(encoded).hexdigest(), semantic_origin, actor.id, actor.kind,
                canonical_json(refs), optional_command_id, target_bytes, now,
            ),
        )
        Store._event(db, "chat_message_recorded", work_id, {
            "message_id": message_id,
            "work_revision": work_revision,
            "sequence": sequence,
            "semantic_origin": semantic_origin,
            "actor_kind": actor.kind,
            "referenced_entity_count": len(refs),
            "command_id": optional_command_id,
        })
        return db.execute(
            "SELECT * FROM conversation_messages WHERE id=?", (message_id,)
        ).fetchone()

    def add_message(
        self,
        work_id,
        work_revision,
        content,
        *,
        semantic_origin,
        actor,
        referenced_entities=(),
        optional_command_id=None,
        exact_target=None,
    ):
        actor, encoded, refs, target_bytes = self._message_inputs(
            work_id,
            work_revision,
            content,
            semantic_origin=semantic_origin,
            actor=actor,
            referenced_entities=referenced_entities,
            optional_command_id=optional_command_id,
            exact_target=exact_target,
        )

        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._insert_message(
                db,
                work_id,
                work_revision,
                content,
                encoded=encoded,
                semantic_origin=semantic_origin,
                actor=actor,
                refs=refs,
                optional_command_id=optional_command_id,
                target_bytes=target_bytes,
            )
        return self._message_row(row)

    def list_messages(self, work_id):
        try:
            uuid_string(work_id)
        except DomainContractError as exc:
            raise ValueError("Work ID is invalid") from exc
        with self.store._connection() as db:
            if db.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone() is None:
                raise KeyError(work_id)
            rows = list(db.execute(
                "SELECT * FROM conversation_messages WHERE work_id=? ORDER BY sequence",
                (work_id,),
            ))
        result = [self._message_row(row) for row in rows]
        if [item["sequence"] for item in result] != list(range(1, len(result) + 1)):
            raise ConversationConflict("Stored message sequence is not contiguous")
        return result

    def propose_command(
        self,
        message_id,
        *,
        command_kind,
        exact_target,
        structured_args,
        proposer,
        required_authority,
    ):
        proposer = self._actor(proposer)
        try:
            uuid_string(message_id)
        except DomainContractError as exc:
            raise ValueError("Proposal message ID is invalid") from exc
        if (type(command_kind) is not str
                or _COMMAND_KIND.fullmatch(command_kind) is None
                or command_kind not in COMMAND_KINDS):
            raise ValueError("Command kind is not registered")
        target_bytes = canonical_json(_exact_target(exact_target).as_dict())
        if type(structured_args) is not dict:
            raise ValueError("Command arguments must be an exact object")
        args_bytes = canonical_json(structured_args)
        if required_authority not in AUTHORITIES - {"none"}:
            raise ValueError("Material commands require a registered authority")

        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            message = db.execute(
                "SELECT * FROM conversation_messages WHERE id=?", (message_id,)
            ).fetchone()
            if (message is None or message["semantic_origin"] != "command_request"):
                raise ConversationConflict(
                    "A proposed command requires an explicit command-request message"
                )
            if (message["actor_id"] != proposer.id
                    or message["actor_kind"] != proposer.kind):
                raise ConversationAuthorityError(
                    "Command proposer does not match the recorded message actor"
                )
            if message["optional_command_id"] is not None:
                raise ConversationConflict("A command response cannot propose another command")
            existing = db.execute(
                "SELECT * FROM conversation_commands WHERE message_id=?", (message_id,)
            ).fetchone()
            if existing is not None:
                expected = self._command_row(existing)
                if (expected["command_kind"] != command_kind
                        or expected["exact_target_ref"] != exact_target.as_dict()
                        or expected["structured_args"] != structured_args
                        or expected["proposer"] != {
                            "id": proposer.id, "kind": proposer.kind
                        }
                        or expected["required_authority"] != required_authority):
                    raise ConversationConflict(
                        "Proposal message is already bound to another command"
                    )
                return expected
            command_id, now = str(uuid4()), self._now(db)
            db.execute(
                "INSERT INTO conversation_commands VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    command_id, message["work_id"], message_id, command_kind,
                    target_bytes, args_bytes, proposer.id, proposer.kind,
                    required_authority, "proposed", now,
                ),
            )
            Store._event(db, "command_proposed", message["work_id"], {
                "command_id": command_id,
                "message_id": message_id,
                "command_kind": command_kind,
                "target_kind": exact_target.kind,
                "target_id": exact_target.id,
                "target_version": exact_target.version,
                "required_authority": required_authority,
            })
            row = db.execute(
                "SELECT * FROM conversation_commands WHERE id=?", (command_id,)
            ).fetchone()
        return self._command_row(row)

    def get_command(self, command_id):
        try:
            uuid_string(command_id)
        except DomainContractError as exc:
            raise ValueError("Command ID is invalid") from exc
        with self.store._connection() as db:
            row = db.execute(
                "SELECT * FROM conversation_commands WHERE id=?", (command_id,)
            ).fetchone()
            if row is None:
                raise KeyError(command_id)
            parsed = self._command_row(row)
            self._assert_command_links(db, parsed)
            return parsed

    def list_proposed_commands(self, work_id):
        try:
            uuid_string(work_id)
        except DomainContractError as exc:
            raise ValueError("Work ID is invalid") from exc
        with self.store._connection() as db:
            if db.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone() is None:
                raise KeyError(work_id)
            rows = list(db.execute(
                "SELECT * FROM conversation_commands WHERE work_id=? ORDER BY rowid",
                (work_id,),
            ))
            result = [self._command_row(row) for row in rows]
            for command in result:
                self._assert_command_links(db, command)
            return result

    def open_challenge(self, command_id, *, authority, ttl_ms=5 * 60 * 1000):
        authority = self._actor(authority)
        try:
            uuid_string(command_id)
        except DomainContractError as exc:
            raise ValueError("Command ID is invalid") from exc
        if (authority.kind != "human" or authority.authority != "local_human"):
            raise ConversationAuthorityError(
                "Only the trusted local human can open this challenge"
            )
        if (type(ttl_ms) is not int or not 1 <= ttl_ms <= _MAX_CHALLENGE_TTL_MS):
            raise ValueError("Challenge lifetime is invalid")

        token = secrets.token_urlsafe(32)
        response_code = secrets.token_hex(4).upper()
        response_text = f"적용 확인 {response_code}"
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            command = db.execute(
                "SELECT * FROM conversation_commands WHERE id=?", (command_id,)
            ).fetchone()
            if command is None:
                raise KeyError(command_id)
            parsed = self._command_row(command)
            self._assert_command_links(db, parsed)
            source_revision = db.execute(
                "SELECT m.work_id AS message_work_id,m.work_revision,w.revision "
                "FROM conversation_messages m "
                "JOIN works w ON w.id=m.work_id WHERE m.id=?",
                (parsed["message_ref"],),
            ).fetchone()
            if (source_revision is None
                    or source_revision["message_work_id"] != parsed["work_id"]
                    or source_revision["work_revision"] != source_revision["revision"]):
                raise ConversationConflict(
                    "Command proposal belongs to an older work revision"
                )
            if parsed["required_authority"] != authority.authority:
                raise ConversationAuthorityError(
                    "Actor authority does not match the proposed command"
                )
            if parsed["validation_state"] != "proposed":
                raise ConversationConflict("Command already has a challenge or validation")
            if db.execute(
                "SELECT 1 FROM conversation_challenges WHERE command_id=?", (command_id,)
            ).fetchone() is not None:
                raise ConversationConflict("Command challenge already exists")
            now = self._now(db)
            if now < parsed["created_at_ms"]:
                raise ConversationConflict("Conversation clock moved backwards")
            if now > MAX_INTEGER - ttl_ms:
                raise ConversationConflict("Challenge expiry is out of range")
            challenge_id = str(uuid4())
            db.execute(
                "INSERT INTO conversation_challenges VALUES (?,?,?,?,?,?,?,NULL)",
                (
                    challenge_id, command_id,
                    sha256(token.encode("ascii")).hexdigest(), response_text,
                    authority.id, now, now + ttl_ms,
                ),
            )
            changed = db.execute(
                "UPDATE conversation_commands SET validation_state='challenge_open' "
                "WHERE id=? AND validation_state='proposed'", (command_id,),
            ).rowcount
            if changed != 1:
                raise ConversationConflict("Command challenge state changed")
            Store._event(db, "command_challenge_opened", parsed["work_id"], {
                "command_id": command_id,
                "challenge_id": challenge_id,
                "expires_at_ms": now + ttl_ms,
            })
        return {
            "id": challenge_id,
            "command_id": command_id,
            "exact_target_ref": parsed["exact_target_ref"],
            "response_text": response_text,
            "token": token,
            "expires_at_ms": now + ttl_ms,
        }

    @staticmethod
    def _validation_row(db, row):
        command = db.execute(
            "SELECT * FROM conversation_commands WHERE id=?", (row["command_id"],)
        ).fetchone()
        if command is None:
            raise ConversationConflict("Stored validation command is missing")
        parsed = Conversation._command_row(command)
        Conversation._assert_command_links(db, parsed)
        challenge = db.execute(
            "SELECT * FROM conversation_challenges WHERE id=? AND command_id=?",
            (row["challenge_id"], row["command_id"]),
        ).fetchone()
        if challenge is None:
            raise ConversationConflict("Stored validation challenge is missing")
        try:
            for name in ("id", "work_id", "command_id", "challenge_id",
                         "authority_actor_id"):
                uuid_string(row[name])
            if (row["work_id"] != parsed["work_id"]
                    or parsed["validation_state"] != "validated"
                    or challenge["issued_to_actor_id"] != row["authority_actor_id"]
                    or challenge["consumed_at_ms"] != row["created_at_ms"]
                    or row["route"] not in INVOCATION_ROUTES
                    or (row["route"] == "chat") !=
                    (row["response_message_id"] is not None)):
                raise ValueError
            if row["response_message_id"] is not None:
                uuid_string(row["response_message_id"])
            created = row["created_at_ms"]
            if type(created) is not int or not 0 <= created <= MAX_INTEGER:
                raise ValueError
            if row["route"] == "chat":
                response_row = db.execute(
                    "SELECT * FROM conversation_messages WHERE id=?",
                    (row["response_message_id"],),
                ).fetchone()
                if response_row is None:
                    raise ValueError
                response = Conversation._message_row(response_row)
                if (response["work_id"] != parsed["work_id"]
                        or response["actor"] != {
                            "id": row["authority_actor_id"], "kind": "human"
                        }
                        or response["semantic_origin"] != "command_request"
                        or response["optional_command_ref"] != row["command_id"]
                        or response["exact_target_ref"] != parsed["exact_target_ref"]
                        or response["content"] != challenge["response_text"]):
                    raise ValueError
        except (DomainContractError, TypeError, ValueError) as exc:
            raise ConversationConflict("Stored command validation is invalid") from exc
        return {
            "id": row["id"],
            "work_id": row["work_id"],
            "command_id": row["command_id"],
            "challenge_id": row["challenge_id"],
            "authority_actor_id": row["authority_actor_id"],
            "route": row["route"],
            "response_message_ref": row["response_message_id"],
            "validation_state": "validated",
            "command_kind": parsed["command_kind"],
            "exact_target_ref": parsed["exact_target_ref"],
            "structured_args": parsed["structured_args"],
            "created_at_ms": created,
        }

    def _invocation_inputs(
        self, command_id, challenge_id, token, *, authority,
        response_message_id, route, deferred_chat_response=False,
    ):
        authority = self._actor(authority)
        try:
            uuid_string(command_id)
            uuid_string(challenge_id)
            if response_message_id is not None:
                uuid_string(response_message_id)
        except DomainContractError as exc:
            raise ConversationConflict("Command invocation binding is invalid") from exc
        if (authority.kind != "human" or authority.authority != "local_human"):
            raise ConversationAuthorityError(
                "Only the trusted local human can validate a material command"
            )
        if (route not in INVOCATION_ROUTES
                or (route == "button" and response_message_id is not None)
                or (route == "chat" and response_message_id is None
                    and not deferred_chat_response)
                or type(token) is not str or not token or len(token) > 256):
            raise ConversationConflict("Command invocation is ambiguous")
        try:
            token_hash = sha256(token.encode("ascii")).hexdigest()
        except UnicodeError as exc:
            raise ConversationConflict("Command challenge token is invalid") from exc
        return authority, token_hash

    def _validate_invocation_in_db(
        self, db, command_id, challenge_id, token_hash, *, authority,
        response_message_id, route,
    ):
        command = db.execute(
            "SELECT * FROM conversation_commands WHERE id=?", (command_id,)
        ).fetchone()
        challenge = db.execute(
            "SELECT * FROM conversation_challenges WHERE id=? AND command_id=?",
            (challenge_id, command_id),
        ).fetchone()
        if command is None or challenge is None:
            raise ConversationConflict("Command challenge does not match")
        parsed = self._command_row(command)
        self._assert_command_links(db, parsed)
        source_revision = db.execute(
            "SELECT m.work_id AS message_work_id,m.work_revision,w.revision "
            "FROM conversation_messages m "
            "JOIN works w ON w.id=m.work_id WHERE m.id=?",
            (parsed["message_ref"],),
        ).fetchone()
        if (source_revision is None
                or source_revision["message_work_id"] != parsed["work_id"]
                or source_revision["work_revision"] != source_revision["revision"]):
            raise ConversationConflict(
                "Command proposal belongs to an older work revision"
            )
        if (parsed["required_authority"] != authority.authority
                or challenge["issued_to_actor_id"] != authority.id):
            raise ConversationAuthorityError(
                "Command challenge belongs to another authority"
            )
        if not hmac.compare_digest(challenge["token_sha256"], token_hash):
            raise ConversationConflict("Command challenge does not match")

        existing = db.execute(
            "SELECT * FROM conversation_validations WHERE command_id=?", (command_id,)
        ).fetchone()
        if existing is not None:
            receipt = self._validation_row(db, existing)
            if (receipt["challenge_id"] != challenge_id
                    or receipt["authority_actor_id"] != authority.id
                    or receipt["route"] != route
                    or receipt["response_message_ref"] != response_message_id):
                raise ConversationConflict(
                    "Command was validated through another exact invocation"
                )
            return receipt

        now = self._now(db)
        if (parsed["validation_state"] != "challenge_open"
                or challenge["consumed_at_ms"] is not None
                or now < challenge["created_at_ms"]
                or now >= challenge["expires_at_ms"]):
            raise ConversationConflict("Command challenge is no longer current")

        if route == "chat":
            response = db.execute(
                "SELECT * FROM conversation_messages WHERE id=?",
                (response_message_id,),
            ).fetchone()
            if response is None:
                raise ConversationConflict("Command response message is missing")
            response = self._message_row(response)
            if (response["work_id"] != parsed["work_id"]
                    or response["actor"] != {
                        "id": authority.id, "kind": authority.kind
                    }
                    or response["semantic_origin"] != "command_request"
                    or response["optional_command_ref"] != command_id
                    or response["exact_target_ref"] != parsed["exact_target_ref"]
                    or response["content"] != challenge["response_text"]):
                raise ConversationConflict(
                    "Chat response is not bound to the exact command target"
                )

        validation_id = str(uuid4())
        db.execute(
            "INSERT INTO conversation_validations VALUES (?,?,?,?,?,?,?,?)",
            (
                validation_id, parsed["work_id"], command_id, challenge_id,
                authority.id, route, response_message_id, now,
            ),
        )
        changed_challenge = db.execute(
            "UPDATE conversation_challenges SET consumed_at_ms=? "
            "WHERE id=? AND command_id=? AND consumed_at_ms IS NULL",
            (now, challenge_id, command_id),
        ).rowcount
        changed_command = db.execute(
            "UPDATE conversation_commands SET validation_state='validated' "
            "WHERE id=? AND validation_state='challenge_open'", (command_id,),
        ).rowcount
        if changed_challenge != 1 or changed_command != 1:
            raise ConversationConflict("Command validation state changed")
        Store._event(db, "command_invocation_validated", parsed["work_id"], {
            "command_id": command_id,
            "challenge_id": challenge_id,
            "validation_id": validation_id,
            "route": route,
            "target_kind": parsed["exact_target_ref"]["kind"],
            "target_id": parsed["exact_target_ref"]["id"],
            "target_version": parsed["exact_target_ref"]["version"],
        })
        row = db.execute(
            "SELECT * FROM conversation_validations WHERE id=?", (validation_id,)
        ).fetchone()
        return self._validation_row(db, row)

    def validate_invocation(
        self,
        command_id,
        challenge_id,
        token,
        *,
        authority,
        response_message_id,
        route,
    ):
        authority, token_hash = self._invocation_inputs(
            command_id,
            challenge_id,
            token,
            authority=authority,
            response_message_id=response_message_id,
            route=route,
        )
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._validate_invocation_in_db(
                db,
                command_id,
                challenge_id,
                token_hash,
                authority=authority,
                response_message_id=response_message_id,
                route=route,
            )

    def record_and_validate_chat_invocation(
        self,
        work_id,
        work_revision,
        content,
        command_id,
        challenge_id,
        token,
        *,
        authority,
        exact_target,
    ):
        authority, encoded, refs, target_bytes = self._message_inputs(
            work_id,
            work_revision,
            content,
            semantic_origin="command_request",
            actor=authority,
            referenced_entities=(),
            optional_command_id=command_id,
            exact_target=exact_target,
        )
        authority, token_hash = self._invocation_inputs(
            command_id,
            challenge_id,
            token,
            authority=authority,
            response_message_id=None,
            route="chat",
            deferred_chat_response=True,
        )
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            message_row = self._insert_message(
                db,
                work_id,
                work_revision,
                content,
                encoded=encoded,
                semantic_origin="command_request",
                actor=authority,
                refs=refs,
                optional_command_id=command_id,
                target_bytes=target_bytes,
            )
            message = self._message_row(message_row)
            validation = self._validate_invocation_in_db(
                db,
                command_id,
                challenge_id,
                token_hash,
                authority=authority,
                response_message_id=message["id"],
                route="chat",
            )
            return message, validation

    def list_validations(self, work_id):
        try:
            uuid_string(work_id)
        except DomainContractError as exc:
            raise ValueError("Work ID is invalid") from exc
        with self.store._connection() as db:
            if db.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone() is None:
                raise KeyError(work_id)
            rows = list(db.execute(
                "SELECT * FROM conversation_validations WHERE work_id=? ORDER BY rowid",
                (work_id,),
            ))
            return [self._validation_row(db, row) for row in rows]


# =====================================================================================
# The supported factory's shared conversation (T023, FR-009): `conversations-v1`.
#
# The class above is the development preview's (app/server.py) over its own `Store`. The
# class below is the one the supported factory installs, over the actual domain store and
# the owner's persistent session. The same rules hold, now with real authority:
#
# - A message is the owner's words bound to the work's current revision and to the exact
#   records it refers to (a revision, a source, a reading, a work model or an earlier
#   message of this same work). Its semantic origin and actor are set by the server; the
#   browser never supplies either. Text such as `응` or even the exact approval phrase
#   posted as a message stays a message and approves nothing.
# - A referenced-object command is proposed from one such message over exactly one of the
#   records it refers to. Proposing grants nothing: the server opens a short-lived
#   challenge bound to this owner session, one random token (only its digest is stored)
#   and one exact response phrase.
# - Approval is the challenge answered, by button or by typing the exact phrase in the
#   conversation. An ambiguous reply (anything but the phrase) is refused as
#   `approval_ambiguous`; a wrong/foreign token, another session, an expired or revoked
#   challenge, a changed work revision or a target no longer undecided is `conflict`; a
#   body naming an actor, authority or origin never passes the wire. A refusal changes
#   nothing.
# - The approved command runs through the same service the button on the work-model panel
#   uses (`PersistentWorkModels.confirm`), under a command id derived from the proposal,
#   so a chat approval and a button decision are one decision, never two. The proposal's
#   sealed versions record proposed → approved → executed (or failed, with its code);
#   an approval whose execution was interrupted resumes on the command's replay.
# =====================================================================================

SUPPORTED_MESSAGE_COMMAND = "conversation-message-command-v1"
SUPPORTED_PROPOSAL_COMMAND = "conversation-proposal-command-v1"
SUPPORTED_CHALLENGE_COMMAND = "conversation-challenge-command-v1"
SUPPORTED_APPROVAL_COMMAND = "conversation-approval-command-v1"
SUPPORTED_MESSAGE_SCHEMA = "conversation-message-v1"
SUPPORTED_PROPOSAL_SCHEMA = "conversation-proposal-v1"
SUPPORTED_COMMANDS = {
    "work_model.confirm": ("accepted", "작업 모델 확정"),
    "work_model.reject": ("rejected", "작업 모델 반려"),
}
SUPPORTED_REFERENCE_KINDS = frozenset({"work_revision", "source", "extraction", "work_model", "chat_message"})
SUPPORTED_MAX_TEXT_CHARS = 20_000
SUPPORTED_MAX_TEXT_BYTES = 65_536
SUPPORTED_MAX_REFERENCES = 16
SUPPORTED_MAX_MESSAGES = 10_000
SUPPORTED_CHALLENGE_TTL_MS = 5 * 60 * 1000
SUPPORTED_CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                             "approval_ambiguous", "unavailable", "capacity"})
_SUPPORTED_DDL = (
    """CREATE TABLE IF NOT EXISTS conversation_v1_messages(
        vault_id TEXT NOT NULL, work_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence > 0),
        message_id TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, PRIMARY KEY(vault_id, work_id, sequence))""",
    """CREATE TABLE IF NOT EXISTS conversation_v1_proposals(
        vault_id TEXT NOT NULL, proposal_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
        message_id TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('proposed','approved','executed','failed')),
        head_version INTEGER NOT NULL, head_sha256 TEXT NOT NULL, created_seq INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS conversation_v1_challenges(
        challenge_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES conversation_v1_proposals(proposal_id),
        token_sha256 TEXT NOT NULL, response_text TEXT NOT NULL, session_id TEXT NOT NULL, owner_id TEXT NOT NULL,
        issued_at_ms INTEGER NOT NULL, expires_at_ms INTEGER NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('open','consumed','revoked')))""",
)


class SupportedConversationError(ValueError):
    """Closed codes for the supported conversation; storage detail never leaks."""

    def __init__(self, code="invalid_input"):
        if code not in SUPPORTED_CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _supported_closed(method):
    @_wraps(method)
    def invoke(*args, **kwargs):
        from .owner_auth import OwnerAuthError
        from .works import WorkServiceError

        try:
            return method(*args, **kwargs)
        except (SupportedConversationError, OwnerAuthError):
            raise
        except WorkServiceError as error:
            raise SupportedConversationError(error.code) from None
        except Exception:  # noqa: BLE001 - storage detail must not disclose
            raise SupportedConversationError("unavailable") from None

    return invoke


def _supported_stamp():
    return _datetime.now(_UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _supported_command(payload, schema, fields):
    if (type(payload) is not dict or set(payload) != {"schema_version", "command_id", *fields}
            or payload["schema_version"] != schema):
        raise SupportedConversationError("invalid_input")
    try:
        uuid_string(payload["command_id"])
    except (TypeError, ValueError):
        raise SupportedConversationError("invalid_input") from None
    return payload


def _supported_text(value):
    if (type(value) is not str or not value.strip() or len(value) > SUPPORTED_MAX_TEXT_CHARS
            or len(value.encode("utf-8")) > SUPPORTED_MAX_TEXT_BYTES):
        raise SupportedConversationError("invalid_input")
    return value


def _supported_ref(value):
    try:
        return EntityRef.from_dict(value)
    except Exception:  # noqa: BLE001 - any malformed reference is plain invalid input
        raise SupportedConversationError("invalid_input") from None


class PersistentConversation:
    """The owner's shared conversation per work over the actual domain store."""

    def __init__(self, works, work_models, *, clock_ms=None):
        from .work_models import PersistentWorkModels
        from .works import PersistentWorks

        if type(works) is not PersistentWorks or type(work_models) is not PersistentWorkModels:
            raise TypeError("Exact works and work-model services required")
        if work_models._domain is not works._domain or work_models._owner is not works._owner:
            raise TypeError("Conversation services must share one domain store and owner authority")
        self.works, self.work_models = works, work_models
        self.domain, self.owner = works._domain, works._owner
        self._clock = clock_ms if callable(clock_ms) else (lambda: _time.time_ns() // 1_000_000)
        from ..domain.store import _writer

        with _writer(), self.domain._connection(write=True) as db:
            for statement in _SUPPORTED_DDL:
                db.execute(statement)

    # --- helpers -----------------------------------------------------------------

    def _writer(self):
        from ..domain.store import _writer

        return _writer()

    def _now(self):
        value = self._clock()
        if type(value) is not int or not 0 <= value <= MAX_INTEGER:
            raise SupportedConversationError("unavailable")
        return value

    def _latest(self, db, roots, work_id):
        latest = self.works._latest(db, roots, work_id)
        if latest is None:
            raise SupportedConversationError("not_found")
        return latest

    def _exact(self, db, roots, ref):
        row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? AND version=?",
                         (roots.genesis.id, ref.kind, ref.id, ref.version)).fetchone()
        if row is None:
            raise SupportedConversationError("not_found")
        if not hmac.compare_digest(row["sha256"], ref.sha256):
            raise SupportedConversationError("conflict")  # a reference to content that is not this record
        return self.domain._load(db, ref, roots)[0]

    def _reference(self, db, roots, work_id, latest, value):
        """One exact record of this same work, or a refusal."""
        from .source_readings import READING_SCHEMA

        ref = _supported_ref(value)
        if ref.kind not in SUPPORTED_REFERENCE_KINDS:
            raise SupportedConversationError("invalid_input")
        record = self._exact(db, roots, ref)
        content = record.body["content"]
        membership = latest.body["content"].get("source_refs", [])
        if ref.kind == "work_revision":
            same = ref.id == work_id
        elif ref.kind == "source":
            same = ref.as_dict() in membership
        elif ref.kind == "extraction":
            same = (content.get("schema_version") == READING_SCHEMA and content.get("work_id") == work_id
                    and content.get("source_ref") in membership)
        elif ref.kind == "work_model":
            same = type(content.get("work_revision_ref")) is dict and content["work_revision_ref"].get("id") == work_id
        else:
            same = content.get("schema_version") == SUPPORTED_MESSAGE_SCHEMA and content.get("work_id") == work_id
        if not same:
            raise SupportedConversationError("conflict")  # another work's record never joins this conversation
        return ref

    def _message_view(self, record):
        content = record.body["content"]
        return {
            "message_id": record.ref.id, "message_ref": record.ref.as_dict(), "sequence": content["sequence"],
            "text": content["text"], "semantic_origin": content["semantic_origin"],
            "actor": {"kind": "human", "role": "owner"}, "references": content["references"],
            "work_revision": content["work_revision_ref"]["version"], "proposal_id": content["proposal_id"],
            "created_at_utc": record.body["created_at_utc"],
        }

    def _proposal_record(self, db, roots, row):
        return self.domain._load(db, EntityRef("proposed_command", row["proposal_id"], row["head_version"],
                                               row["head_sha256"]), roots)[0]

    def _proposal_view(self, db, roots, row, session_id=None):
        record = self._proposal_record(db, roots, row)
        content = record.body["content"]
        challenge = None
        if session_id is not None and content["state"] == "proposed":
            open_row = db.execute(
                "SELECT challenge_id, response_text, expires_at_ms FROM conversation_v1_challenges "
                "WHERE proposal_id=? AND state='open' AND session_id=? ORDER BY issued_at_ms DESC LIMIT 1",
                (row["proposal_id"], session_id)).fetchone()
            if open_row is not None and open_row["expires_at_ms"] > self._now():
                challenge = {"challenge_id": open_row["challenge_id"], "response_text": open_row["response_text"],
                             "expires_at_ms": open_row["expires_at_ms"]}
        return {
            "proposal_id": content["proposal_id"], "proposal_ref": record.ref.as_dict(),
            "command_kind": content["command_kind"], "target_ref": content["target_ref"],
            "message_id": content["message_ref"]["id"], "state": content["state"],
            "approval": content["approval"], "result": content["result"], "challenge": challenge,
        }

    def _proposal_row(self, db, roots, work_id, proposal_id):
        try:
            uuid_string(proposal_id)
        except (TypeError, ValueError):
            raise SupportedConversationError("invalid_input") from None
        row = db.execute("SELECT * FROM conversation_v1_proposals WHERE vault_id=? AND proposal_id=?",
                         (roots.genesis.id, proposal_id)).fetchone()
        if row is None or row["work_id"] != work_id:
            raise SupportedConversationError("not_found")
        return row

    def _seal_message(self, db, roots, actor_ref, *, work_id, latest, command_id, text, origin, references,
                      proposal_id):
        from ..domain.schemas import ImmutableRecord

        count = db.execute("SELECT count(*) FROM conversation_v1_messages WHERE vault_id=? AND work_id=?",
                           (roots.genesis.id, work_id)).fetchone()[0]
        if count >= SUPPORTED_MAX_MESSAGES:
            raise SupportedConversationError("capacity")
        parents = [latest.ref, *(ref for ref in references if ref != latest.ref)]
        record = ImmutableRecord.create(
            kind="chat_message", id=str(_uuid5(_NAMESPACE_URL, f"deeptwin:conversation-message:{command_id}")),
            version=1, created_at_utc=_supported_stamp(), actor_ref=actor_ref, parent_refs=tuple(parents),
            purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content={"schema_version": SUPPORTED_MESSAGE_SCHEMA, "work_id": work_id,
                     "work_revision_ref": latest.ref.as_dict(), "sequence": count + 1, "text": text,
                     "semantic_origin": origin, "actor_kind": "human",
                     "references": [ref.as_dict() for ref in references], "proposal_id": proposal_id,
                     "command_id": command_id})
        self.domain._put_in_transaction(db, record)
        db.execute("INSERT INTO conversation_v1_messages VALUES (?,?,?,?,?)",
                   (roots.genesis.id, work_id, count + 1, record.ref.id, record.ref.sha256))
        return self.domain._load(db, record.ref, roots)[0]

    def _seal_proposal(self, db, roots, actor_ref, content, *, version, parent=None):
        from ..domain.schemas import ImmutableRecord

        parents = (parent.ref,) if parent is not None else (
            EntityRef.from_dict(content["message_ref"]), EntityRef.from_dict(content["target_ref"]))
        record = ImmutableRecord.create(
            kind="proposed_command", id=content["proposal_id"], version=version,
            created_at_utc=_supported_stamp(), actor_ref=actor_ref, parent_refs=parents, purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy, content=content)
        self.domain._put_in_transaction(db, record)
        return self.domain._load(db, record.ref, roots)[0]

    def _issue_challenge(self, db, proposal_id, request, command_kind):
        token = secrets.token_urlsafe(32)
        code = secrets.token_hex(4).upper()
        response_text = f"{SUPPORTED_COMMANDS[command_kind][1]} 승인 {code}"
        now = self._now()
        db.execute("UPDATE conversation_v1_challenges SET state='revoked' WHERE proposal_id=? AND state='open'",
                   (proposal_id,))
        challenge_id = str(uuid4())
        db.execute("INSERT INTO conversation_v1_challenges VALUES (?,?,?,?,?,?,?,?,'open')",
                   (challenge_id, proposal_id, sha256(token.encode("ascii")).hexdigest(), response_text,
                    request.session.session_id, request.session.actor.id, now,
                    now + SUPPORTED_CHALLENGE_TTL_MS))
        return {"challenge_id": challenge_id, "token": token, "response_text": response_text,
                "expires_at_ms": now + SUPPORTED_CHALLENGE_TTL_MS}

    def _event(self, db, roots, actor_ref, kind, ref, command_id, metadata):
        from ..domain.public_events import _append_event_in_transaction

        stamp = _supported_stamp()
        _append_event_in_transaction(
            db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp, actor_kind="human",
            actor_ref=actor_ref, event_type=kind, object_refs=(ObjectRef(ref.kind, ref.id, ref.version, ref.sha256),),
            correlation_id=command_id, causation_id=None, status="succeeded", error_code=None,
            public_metadata=metadata, private_evidence_refs=(), retention_class="core",
            policy_ref=roots.access_policy)

    def _undecided_target(self, request, target_ref):
        """The work model's current view when it is exactly the target and still undecided."""
        from .work_models import WorkModelServiceError

        try:
            view = self.work_models.read(request, target_ref.id)
        except WorkModelServiceError as error:
            raise SupportedConversationError("not_found" if error.code == "not_found" else "unavailable") from None
        if view["record_ref"] != target_ref.as_dict() or view["state"] != "unconfirmed":
            raise SupportedConversationError("conflict")
        return view

    def _replay(self, db, roots, command_id, digest):
        from . import owner_material_journal as journal

        row = journal.lookup(db, roots.genesis.id, command_id)
        if row is not None:
            if row["fingerprint"] != digest:
                raise SupportedConversationError("conflict")
            return journal.receipt(row)
        if self.works._by_command(db, roots, command_id) is not None:
            raise SupportedConversationError("conflict")  # a works command id is not a conversation's
        return None

    # --- reads -------------------------------------------------------------------

    @_supported_closed
    def read(self, request, work_id):
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise SupportedConversationError("invalid_input") from None
        with self.domain._connection() as db:
            self.owner.authenticate_bound(request.session)
            roots = self.domain._read_roots(db)
            latest = self._latest(db, roots, work_id)
            messages = [self._message_view(self.domain._load(db, EntityRef("chat_message", row["message_id"], 1,
                                                                            row["sha256"]), roots)[0])
                        for row in db.execute("SELECT message_id, sha256 FROM conversation_v1_messages "
                                              "WHERE vault_id=? AND work_id=? ORDER BY sequence",
                                              (roots.genesis.id, work_id))]
            proposals = [self._proposal_view(db, roots, row, request.session.session_id)
                         for row in db.execute("SELECT * FROM conversation_v1_proposals WHERE vault_id=? "
                                               "AND work_id=? ORDER BY created_seq", (roots.genesis.id, work_id))]
        return {"work_id": work_id, "revision": latest.ref.version, "messages": messages, "proposals": proposals}

    # --- the owner's commands ----------------------------------------------------------

    @_supported_closed
    def post_message(self, request, work_id, payload):
        from . import owner_material_journal as journal
        from .run_approvals import _authenticate_owner, _owner_actor_ref

        _authenticate_owner(self.owner, request)
        command = _supported_command(payload, SUPPORTED_MESSAGE_COMMAND, ("expected_revision", "text", "references"))
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise SupportedConversationError("invalid_input") from None
        text = _supported_text(command["text"])
        expected = command["expected_revision"]
        references = command["references"]
        if (type(expected) is not int or expected < 1 or type(references) is not list
                or len(references) > SUPPORTED_MAX_REFERENCES):
            raise SupportedConversationError("invalid_input")
        digest = journal.fingerprint("conversation_message", work_id, payload)
        with self._writer(), self.domain._connection(write=True) as db:
            actor = _authenticate_owner(self.owner, request, db)
            roots = self.domain._read_roots(db)
            replay = self._replay(db, roots, command["command_id"], digest)
            if replay is not None:
                return {"message": self._message_view(self.domain._load(
                    db, EntityRef.from_dict(replay["message_ref"]), roots)[0])}
            latest = self._latest(db, roots, work_id)
            if latest.ref.version != expected:
                raise SupportedConversationError("conflict")  # the message would bind a revision not shown
            refs = [self._reference(db, roots, work_id, latest, item) for item in references]
            if len(set(refs)) != len(refs):
                raise SupportedConversationError("invalid_input")
            actor_ref = _owner_actor_ref(db, actor)
            sealed = self._seal_message(db, roots, actor_ref, work_id=work_id, latest=latest,
                                        command_id=command["command_id"], text=text, origin="owner_message",
                                        references=refs, proposal_id=None)
            journal.save(db, roots.genesis.id, command["command_id"], digest,
                         {"message_ref": sealed.ref.as_dict()})
            return {"message": self._message_view(sealed)}

    @_supported_closed
    def propose(self, request, work_id, payload):
        from . import owner_material_journal as journal
        from .run_approvals import _authenticate_owner, _owner_actor_ref

        _authenticate_owner(self.owner, request)
        command = _supported_command(payload, SUPPORTED_PROPOSAL_COMMAND, ("message_id", "command_kind", "target_ref"))
        try:
            work_id = uuid_string(work_id)
            message_id = uuid_string(command["message_id"])
        except (TypeError, ValueError):
            raise SupportedConversationError("invalid_input") from None
        if command["command_kind"] not in SUPPORTED_COMMANDS:
            raise SupportedConversationError("invalid_input")
        target = _supported_ref(command["target_ref"])
        if target.kind != "work_model":
            raise SupportedConversationError("invalid_input")
        digest = journal.fingerprint("conversation_proposal", work_id, payload)
        proposal_id = str(_uuid5(_NAMESPACE_URL, f"deeptwin:conversation-proposal:{command['command_id']}"))
        with self.domain._connection() as db:
            roots = self.domain._read_roots(db)
            replay = self._replay(db, roots, command["command_id"], digest)
        if replay is None:
            self._undecided_target(request, target)
        with self._writer(), self.domain._connection(write=True) as db:
            actor = _authenticate_owner(self.owner, request, db)
            roots = self.domain._read_roots(db)
            replay = self._replay(db, roots, command["command_id"], digest)
            if replay is not None:
                row = self._proposal_row(db, roots, work_id, replay["proposal_id"])
                # the token was never stored: a replayed proposal asks for a fresh challenge
                return {"proposal": self._proposal_view(db, roots, row, request.session.session_id),
                        "challenge": None}
            latest = self._latest(db, roots, work_id)
            row = db.execute("SELECT sha256 FROM conversation_v1_messages WHERE vault_id=? AND work_id=? "
                             "AND message_id=?", (roots.genesis.id, work_id, message_id)).fetchone()
            if row is None:
                raise SupportedConversationError("not_found")
            message = self.domain._load(db, EntityRef("chat_message", message_id, 1, row["sha256"]), roots)[0]
            content = message.body["content"]
            if content["semantic_origin"] != "owner_message" or content["work_revision_ref"] != latest.ref.as_dict():
                raise SupportedConversationError("conflict")  # proposed only from a current owner message
            if target.as_dict() not in content["references"]:
                raise SupportedConversationError("conflict")  # only over a record the message named exactly
            open_targets = [
                self._proposal_record(db, roots, item).body["content"]["target_ref"]
                for item in db.execute("SELECT * FROM conversation_v1_proposals WHERE vault_id=? AND "
                                       "work_id=? AND state IN ('proposed','approved')", (roots.genesis.id, work_id))]
            if target.as_dict() in open_targets:
                raise SupportedConversationError("conflict")  # one open proposal per target
            actor_ref = _owner_actor_ref(db, actor)
            sealed = self._seal_proposal(db, roots, actor_ref, {
                "schema_version": SUPPORTED_PROPOSAL_SCHEMA, "work_id": work_id, "proposal_id": proposal_id,
                "command_kind": command["command_kind"], "target_ref": target.as_dict(),
                "message_ref": message.ref.as_dict(), "proposer": "owner", "state": "proposed",
                "required_authority": "owner_session_challenge", "approval": None, "result": None,
                "command_id": command["command_id"]}, version=1)
            sequence = db.execute("SELECT coalesce(max(created_seq), 0) + 1 FROM conversation_v1_proposals").fetchone()[0]
            db.execute("INSERT INTO conversation_v1_proposals VALUES (?,?,?,?,?,?,?,?)",
                       (roots.genesis.id, proposal_id, work_id, message_id, "proposed", 1, sealed.ref.sha256,
                        sequence))
            challenge = self._issue_challenge(db, proposal_id, request, command["command_kind"])
            self._event(db, roots, actor_ref, "approval.requested", sealed.ref, command["command_id"],
                        {"approval_kind": "action"})
            journal.save(db, roots.genesis.id, command["command_id"], digest, {"proposal_id": proposal_id})
            row = self._proposal_row(db, roots, work_id, proposal_id)
            return {"proposal": self._proposal_view(db, roots, row, request.session.session_id),
                    "challenge": challenge}

    @_supported_closed
    def reissue(self, request, work_id, payload):
        """A fresh challenge for an undecided proposal (after a reload the token is gone)."""
        from .run_approvals import _authenticate_owner

        _authenticate_owner(self.owner, request)
        command = _supported_command(payload, SUPPORTED_CHALLENGE_COMMAND, ("proposal_id",))
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise SupportedConversationError("invalid_input") from None
        with self._writer(), self.domain._connection(write=True) as db:
            _authenticate_owner(self.owner, request, db)
            roots = self.domain._read_roots(db)
            row = self._proposal_row(db, roots, work_id, command["proposal_id"])
            if row["state"] != "proposed":
                raise SupportedConversationError("conflict")
            kind = self._proposal_record(db, roots, row).body["content"]["command_kind"]
            challenge = self._issue_challenge(db, row["proposal_id"], request, kind)
            return {"proposal": self._proposal_view(db, roots, row, request.session.session_id),
                    "challenge": challenge}

    @_supported_closed
    def approve(self, request, work_id, payload):
        from . import owner_material_journal as journal
        from .run_approvals import _authenticate_owner, _owner_actor_ref

        _authenticate_owner(self.owner, request)
        command = _supported_command(payload, SUPPORTED_APPROVAL_COMMAND,
                                     ("proposal_id", "challenge_id", "token", "route", "text"))
        try:
            work_id = uuid_string(work_id)
            proposal_id = uuid_string(command["proposal_id"])
            challenge_id = uuid_string(command["challenge_id"])
        except (TypeError, ValueError):
            raise SupportedConversationError("invalid_input") from None
        route, text, token = command["route"], command["text"], command["token"]
        if (route not in {"button", "chat"} or (route == "button") != (text is None)
                or type(token) is not str or not 1 <= len(token) <= 256 or not token.isascii()):
            raise SupportedConversationError("invalid_input")
        if route == "chat":
            _supported_text(text)
        digest = journal.fingerprint("conversation_approval", work_id, payload)
        with self.domain._connection() as db:
            roots = self.domain._read_roots(db)
            replay = self._replay(db, roots, command["command_id"], digest)
            row = self._proposal_row(db, roots, work_id, proposal_id)
            proposal = self._proposal_record(db, roots, row)
        if replay is not None:
            return self._execute(request, work_id, proposal_id)  # resumes an interrupted execution
        target = EntityRef.from_dict(proposal.body["content"]["target_ref"])
        self._undecided_target(request, target)
        with self._writer(), self.domain._connection(write=True) as db:
            actor = _authenticate_owner(self.owner, request, db)
            roots = self.domain._read_roots(db)
            if self._replay(db, roots, command["command_id"], digest) is not None:
                replay = True
            else:
                row = self._proposal_row(db, roots, work_id, proposal_id)
                challenge = db.execute("SELECT * FROM conversation_v1_challenges WHERE challenge_id=? AND "
                                       "proposal_id=?", (challenge_id, proposal_id)).fetchone()
                if (challenge is None or row["state"] != "proposed" or challenge["state"] != "open"
                        or challenge["session_id"] != request.session.session_id
                        or challenge["owner_id"] != actor.id
                        or not hmac.compare_digest(challenge["token_sha256"],
                                                   sha256(token.encode("ascii")).hexdigest())
                        or not challenge["issued_at_ms"] <= self._now() < challenge["expires_at_ms"]):
                    raise SupportedConversationError("conflict")
                if route == "chat" and text.strip() != challenge["response_text"]:
                    raise SupportedConversationError("approval_ambiguous")  # nothing but the exact phrase
                proposal = self._proposal_record(db, roots, row)
                content = proposal.body["content"]
                latest = self._latest(db, roots, work_id)
                message = self.domain._load(db, EntityRef.from_dict(content["message_ref"]), roots)[0]
                if message.body["content"]["work_revision_ref"] != latest.ref.as_dict():
                    raise SupportedConversationError("conflict")  # the work changed since it was proposed
                actor_ref = _owner_actor_ref(db, actor)
                response = None
                if route == "chat":
                    response = self._seal_message(
                        db, roots, actor_ref, work_id=work_id, latest=latest, command_id=command["command_id"],
                        text=text.strip(), origin="approval_response",
                        references=[EntityRef.from_dict(content["target_ref"])], proposal_id=proposal_id)
                changed = db.execute("UPDATE conversation_v1_challenges SET state='consumed' WHERE challenge_id=? "
                                     "AND state='open'", (challenge_id,)).rowcount
                if changed != 1:
                    raise SupportedConversationError("conflict")
                sealed = self._seal_proposal(db, roots, actor_ref, {
                    **content, "state": "approved",
                    "approval": {"route": route, "challenge_id": challenge_id, "approved_at_utc": _supported_stamp(),
                                 "response_message_ref": None if response is None else response.ref.as_dict(),
                                 "command_id": command["command_id"]}}, version=2, parent=proposal)
                db.execute("UPDATE conversation_v1_proposals SET state='approved', head_version=2, head_sha256=? "
                           "WHERE proposal_id=? AND state='proposed'", (sealed.ref.sha256, proposal_id))
                journal.save(db, roots.genesis.id, command["command_id"], digest, {"proposal_id": proposal_id})
        return self._execute(request, work_id, proposal_id)

    def _execute(self, request, work_id, proposal_id):
        """Run an approved command once through the shared work-model service and seal the result."""
        from .run_approvals import _authenticate_owner, _owner_actor_ref
        from .work_models import CONFIRM_SCHEMA, WorkModelServiceError

        with self.domain._connection() as db:
            roots = self.domain._read_roots(db)
            row = self._proposal_row(db, roots, work_id, proposal_id)
            proposal = self._proposal_record(db, roots, row)
        content = proposal.body["content"]
        if row["state"] != "approved":
            with self.domain._connection() as db:
                roots = self.domain._read_roots(db)
                return {"proposal": self._proposal_view(db, roots, row, request.session.session_id)}
        target = EntityRef.from_dict(content["target_ref"])
        decision = SUPPORTED_COMMANDS[content["command_kind"]][0]
        try:
            view = self.work_models.read(request, target.id)
            if view["record_ref"] != target.as_dict():
                raise WorkModelServiceError("conflict")
            decided = self.work_models.confirm(request, target.id, {
                "schema_version": CONFIRM_SCHEMA,
                "command_id": str(_uuid5(_NAMESPACE_URL, f"deeptwin:conversation-execution:{proposal_id}")),
                "work_model_ref": view["work_model_ref"], "decision": decision})
            result = {"outcome": "executed", "code": None, "work_model_state": decided["state"],
                      "confirmation_ref": decided["confirmation_ref"]}
        except WorkModelServiceError as error:
            if error.code in {"unavailable", "unauthenticated", "access_denied"}:
                # stays approved: the approval command's replay resumes it
                raise SupportedConversationError(error.code) from None
            result = {"outcome": "failed", "code": error.code, "work_model_state": None, "confirmation_ref": None}
        with self._writer(), self.domain._connection(write=True) as db:
            actor = _authenticate_owner(self.owner, request, db)
            roots = self.domain._read_roots(db)
            row = self._proposal_row(db, roots, work_id, proposal_id)
            if row["state"] == "approved":
                current = self._proposal_record(db, roots, row)
                state = "executed" if result["outcome"] == "executed" else "failed"
                sealed = self._seal_proposal(db, roots, _owner_actor_ref(db, actor), {
                    **current.body["content"], "state": state, "result": result}, version=3, parent=current)
                db.execute("UPDATE conversation_v1_proposals SET state=?, head_version=3, head_sha256=? "
                           "WHERE proposal_id=? AND state='approved'", (state, sealed.ref.sha256, proposal_id))
                row = self._proposal_row(db, roots, work_id, proposal_id)
            return {"proposal": self._proposal_view(db, roots, row, request.session.session_id)}
