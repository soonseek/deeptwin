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
from dataclasses import dataclass
from hashlib import sha256
from threading import RLock
from uuid import uuid4

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
