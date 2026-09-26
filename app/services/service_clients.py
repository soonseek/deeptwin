"""Transport-independent, scoped service-client credentials for optional HTTPS clients.

This dependency layer owns no HTTP route and persists no secret. The supported factory composes
`PersistentServiceClientRegistry` through the `service-clients-v1` contribution
(`app/api/service_clients.py`); the in-memory `ServiceClientRegistry` stays a test contract.
"""

from __future__ import annotations

import base64
import hmac
import json
import re
import sqlite3
from dataclasses import dataclass, field, replace
from hashlib import sha256
from threading import RLock

from ..domain.events import event_metadata
from ..domain.refs import MAX_INTEGER, canonical_json, uuid_string
from ..domain.schemas import Actor
from ..storage import Store

_SCOPE = re.compile(r"(?:command:[a-z][a-z0-9_]{0,63}\.[a-z][a-z0-9_]{0,63}|"
                    r"(?:events|snapshot|artifact)\.read)")
_FORBIDDEN_CATEGORIES = frozenset({
    "bootstrap", "auth", "approval", "promotion", "deployment", "recovery",
    "service_client", "credential", "managed_login",
})
_NETWORK_PROFILES = frozenset({"portable_https", "dedicated_https"})
MAX_SERVICE_CLIENT_TTL_SECONDS = 86_400


class ServiceClientDenied(PermissionError):
    """Opaque refusal at the service credential boundary."""


class CorruptServiceClient(RuntimeError):
    """Durable service-client history or its current head failed integrity checks."""


@dataclass(frozen=True, slots=True)
class ServiceClientRecord:
    client_id: str
    owner_id: str
    name: str
    scopes: tuple[str, ...]
    allowed_network_profile: str
    created_at: int
    expires_at: int
    revision: int
    state: str
    credential_digest: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class IssuedServiceClient:
    client: ServiceClientRecord
    secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ServiceClientPrincipal:
    client_id: str
    actor: Actor
    scopes: tuple[str, ...]
    allowed_network_profile: str
    expires_at: int
    credential_revision: int
    human_authority: bool = False
    deployment_authority: bool = False


def _bounded_name(value):
    if type(value) is not str or not value:
        return None
    if (any(0xD800 <= ord(character) <= 0xDFFF for character in value)
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        return None
    # Surrogates were rejected above, so this encoding cannot expose a raw Unicode error.
    if len(value.encode("utf-8")) > 128:
        return None
    return value


def _scopes(values):
    if type(values) not in (tuple, list) or not values or len(values) > 64:
        raise ServiceClientDenied("Service client scope is invalid")
    result = tuple(values)
    if (len(set(result)) != len(result)
            or any(type(value) is not str or _SCOPE.fullmatch(value) is None for value in result)):
        raise ServiceClientDenied("Service client scope is invalid")
    for value in result:
        category = value.removeprefix("command:").split(".", 1)[0]
        if category in _FORBIDDEN_CATEGORIES:
            raise ServiceClientDenied("Service client scope cannot grant human or deployment authority")
    return tuple(sorted(result))


def _secret(raw):
    if type(raw) is not bytes or len(raw) != 32:
        raise ServiceClientDenied("Credential generator failed")
    return "dt_sc_" + base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _secret_digest(value):
    if type(value) is not str or not value.startswith("dt_sc_") or len(value) != 49:
        return None
    try:
        encoded = value[6:]
        raw = base64.urlsafe_b64decode(encoded + "=")
        canonical = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    if len(raw) != 32 or canonical != encoded:
        return None
    return sha256(value.encode("ascii")).hexdigest()


class ServiceClientRegistry:
    """Owner-gated lifecycle contract with injectable future persistence boundary."""

    def __init__(self, *, verify_owner, clock, random_bytes):
        if not all(callable(value) for value in (verify_owner, clock, random_bytes)):
            raise TypeError("Service client dependencies must be trusted callables")
        self._verify_owner = verify_owner
        self._clock = clock
        self._random_bytes = random_bytes
        self._records = {}
        self._credential_index = {}
        self._events = []
        self._last_now = None

    @property
    def events(self):
        return tuple({"event_type": value["event_type"],
                      "public_metadata": value["public_metadata"].copy()}
                     for value in self._events)

    def _now(self):
        try:
            value = self._clock()
        except Exception as exc:
            raise ServiceClientDenied("Trusted service client clock failed") from exc
        if type(value) is not int or not 0 <= value <= MAX_INTEGER:
            raise ServiceClientDenied("Trusted service client clock is invalid")
        if self._last_now is not None and value < self._last_now:
            raise ServiceClientDenied("Trusted service client clock moved backwards")
        self._last_now = value
        return value

    def _owner(self, request):
        try:
            actor = self._verify_owner(request)
        except Exception as exc:
            raise ServiceClientDenied("Authenticated owner is required") from exc
        if type(actor) is not Actor or actor.kind != "human":
            raise ServiceClientDenied("Authenticated owner is required")
        return actor

    def _emit(self, event_type, **payload):
        self._events.append({
            "event_type": event_type,
            "public_metadata": event_metadata(event_type, payload),
        })

    def _new_secret(self):
        raw = secret = digest = None
        message = None
        try:
            raw = self._random_bytes(32)
            secret = _secret(raw)
        except Exception:  # noqa: BLE001 - sanitize the entropy boundary
            message = "Credential generator failed"
        if message is not None:
            raw = secret = digest = None
            raise ServiceClientDenied(message)
        digest = _secret_digest(secret)
        if digest is None or digest in self._credential_index:
            raw = secret = digest = None
            raise ServiceClientDenied("Credential generator repeated or failed")
        raw = None
        return secret, digest

    def issue(self, owner_request, *, client_id, name, scopes, allowed_network_profile,
              expires_at):
        owner_failed = False
        owner = None
        try:
            owner = self._owner(owner_request)
        except ServiceClientDenied:
            owner_failed = True
        if owner_failed:
            self._deny("owner", "Authenticated owner is required")
        clock_failed = False
        now = None
        try:
            now = self._now()
        except ServiceClientDenied:
            clock_failed = True
        if clock_failed:
            self._deny("internal", "Trusted service client clock is unavailable")
        identifier_failed = False
        try:
            client_id = uuid_string(client_id)
        except (TypeError, ValueError):
            identifier_failed = True
        if identifier_failed:
            self._deny("identifier", "Service client ID is invalid")
        if client_id in self._records:
            self._deny("conflict", "Service client ID is already bound")
        if (type(expires_at) is not int or not now < expires_at <= MAX_INTEGER
                or expires_at - now > MAX_SERVICE_CLIENT_TTL_SECONDS):
            self._deny("expiry", "Service client expiry is invalid")
        if allowed_network_profile not in _NETWORK_PROFILES:
            self._deny("network", "Service client network profile is invalid")
        normalized_name = _bounded_name(name)
        name = None
        if normalized_name is None:
            self._deny("name", "Service client name is invalid")
        scope_failed = False
        try:
            scope_values = _scopes(scopes)
        except ServiceClientDenied:
            scope_failed = True
        if scope_failed:
            self._deny("scope", "Service client scope is invalid")
        created_event = {
            "event_type": "service_client.created",
            "public_metadata": event_metadata(
                "service_client.created", {"scope_count": len(scope_values), "revision": 1},
            ),
        }
        credential_failed = False
        secret = digest = None
        try:
            secret, digest = self._new_secret()
        except ServiceClientDenied:
            credential_failed = True
        if credential_failed:
            self._deny("credential", "Service client credential could not be issued")
        record = ServiceClientRecord(
            client_id=client_id, owner_id=owner.id, name=normalized_name,
            scopes=scope_values, allowed_network_profile=allowed_network_profile,
            created_at=now, expires_at=expires_at, revision=1, state="active",
            credential_digest=digest,
        )
        self._records[client_id] = record
        self._credential_index[digest] = client_id
        self._events.append(created_event)
        return IssuedServiceClient(replace(record, credential_digest="0" * 64), secret)

    def _owned_record(self, owner_request, client_id):
        owner_failed = False
        owner = None
        try:
            owner = self._owner(owner_request)
        except ServiceClientDenied:
            owner_failed = True
        if owner_failed:
            self._deny("owner", "Authenticated owner is required")
        record_failed = False
        record = None
        try:
            client_id = uuid_string(client_id)
            record = self._records[client_id]
        except (KeyError, TypeError, ValueError):
            record_failed = True
        if record_failed:
            self._deny("owner", "Owned service client is unavailable")
        if record.owner_id != owner.id:
            self._deny("owner", "Authenticated owner is required")
        return record

    def rotate(self, owner_request, client_id):
        record = self._owned_record(owner_request, client_id)
        clock_failed = False
        try:
            self._now()
        except ServiceClientDenied:
            clock_failed = True
        if clock_failed:
            self._deny("internal", "Trusted service client clock is unavailable")
        if record.state != "active":
            self._deny("revoked", "Revoked service client cannot rotate")
        credential_failed = False
        secret = digest = None
        try:
            secret, digest = self._new_secret()
        except ServiceClientDenied:
            credential_failed = True
        if credential_failed:
            self._deny("credential", "Service client credential could not be rotated")
        self._credential_index.pop(record.credential_digest, None)
        changed = replace(record, credential_digest=digest, revision=record.revision + 1)
        self._records[client_id] = changed
        self._credential_index[digest] = client_id
        self._emit("service_client.rotated", scope_count=len(changed.scopes),
                   revision=changed.revision)
        return IssuedServiceClient(replace(changed, credential_digest="0" * 64), secret)

    def revoke(self, owner_request, client_id):
        record = self._owned_record(owner_request, client_id)
        clock_failed = False
        try:
            self._now()
        except ServiceClientDenied:
            clock_failed = True
        if clock_failed:
            self._deny("internal", "Trusted service client clock is unavailable")
        if record.state != "active":
            self._deny("state", "Service client is already revoked")
        self._credential_index.pop(record.credential_digest, None)
        changed = replace(record, credential_digest="0" * 64,
                          revision=record.revision + 1, state="revoked")
        self._records[client_id] = changed
        self._emit("service_client.revoked", scope_count=len(changed.scopes),
                   revision=changed.revision)
        return changed

    def _deny(self, reason, message):
        self._emit("service_client.denied", reason_code=reason)
        raise ServiceClientDenied(message)

    def authenticate(self, secret, *, network_profile):
        digest = _secret_digest(secret)
        # A raised denial must not retain the bearer value in this traceback frame.
        secret = None
        clock_failed = False
        now = None
        try:
            now = self._now()
        except ServiceClientDenied:
            clock_failed = True
        if clock_failed:
            self._deny("internal", "Trusted service client clock is unavailable")
        client_id = None if digest is None else self._credential_index.get(digest)
        if client_id is None:
            self._deny("credential", "Service client credential is invalid")
        record = self._records.get(client_id)
        if record is None or record.credential_digest != digest:
            self._deny("credential", "Service client credential is invalid")
        if record.state != "active":
            self._deny("revoked", "Service client is revoked")
        if now >= record.expires_at:
            self._deny("expired", "Service client credential expired")
        if network_profile != record.allowed_network_profile:
            self._deny("network", "Service client network profile differs")
        actor = Actor(record.client_id, "service_client", "service_credential")
        return ServiceClientPrincipal(
            client_id=record.client_id, actor=actor, scopes=record.scopes,
            allowed_network_profile=record.allowed_network_profile,
            expires_at=record.expires_at, credential_revision=record.revision,
        )

    def snapshot(self, owner_request, client_id):
        record = self._owned_record(owner_request, client_id)
        clock_failed = False
        try:
            self._now()
        except ServiceClientDenied:
            clock_failed = True
        if clock_failed:
            self._deny("internal", "Trusted service client clock is unavailable")
        return {
            "client_id": record.client_id,
            "owner_id": record.owner_id,
            "name": record.name,
            "scopes": list(record.scopes),
            "allowed_network_profile": record.allowed_network_profile,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
            "revision": record.revision,
            "state": record.state,
        }


_PERSISTENT_SCHEMA_VERSION = 1
_PERSISTENT_SCHEMA = """
CREATE TABLE service_client_migrations (
    version INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL
);
CREATE TABLE service_client_control (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    recovery_epoch INTEGER NOT NULL,
    event_sequence INTEGER NOT NULL,
    event_hash TEXT,
    last_observed_at INTEGER NOT NULL,
    control_hash TEXT NOT NULL
);
CREATE TABLE service_client_records (
    client_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    scopes_json TEXT NOT NULL,
    network_profile TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    state TEXT NOT NULL,
    credential_digest TEXT,
    recovery_epoch INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL,
    previous_hash TEXT,
    record_hash TEXT NOT NULL,
    PRIMARY KEY(client_id, revision),
    UNIQUE(credential_digest)
);
CREATE TABLE service_client_heads (
    client_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    record_hash TEXT NOT NULL,
    state TEXT NOT NULL
);
CREATE TABLE service_client_usage (
    client_id TEXT NOT NULL,
    credential_revision INTEGER NOT NULL,
    last_used_at INTEGER,
    use_revision INTEGER NOT NULL,
    usage_hash TEXT NOT NULL,
    PRIMARY KEY(client_id, credential_revision)
);
CREATE TABLE service_client_events (
    sequence INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL,
    client_id TEXT NOT NULL,
    client_revision INTEGER NOT NULL,
    recovery_epoch INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL
);
"""
_PERSISTENT_SCHEMA_HASH = sha256(_PERSISTENT_SCHEMA.encode("utf-8")).hexdigest()
_PERSISTENT_EVENT_TYPES = frozenset({
    "service_client.created",
    "service_client.rotated",
    "service_client.revoked",
    "service_client.recovery_advanced",
    "service_client.recovery_revoked",
})
_PERSISTENT_TABLE_COLUMNS = {
    "service_client_migrations": (
        "version", "sha256",
    ),
    "service_client_control": (
        "singleton", "recovery_epoch", "event_sequence", "event_hash",
        "last_observed_at", "control_hash",
    ),
    "service_client_records": (
        "client_id", "revision", "owner_id", "name", "scopes_json",
        "network_profile", "created_at", "expires_at", "state",
        "credential_digest", "recovery_epoch", "recorded_at", "previous_hash",
        "record_hash",
    ),
    "service_client_heads": (
        "client_id", "revision", "record_hash", "state",
    ),
    "service_client_usage": (
        "client_id", "credential_revision", "last_used_at", "use_revision",
        "usage_hash",
    ),
    "service_client_events": (
        "sequence", "event_type", "client_id", "client_revision", "recovery_epoch",
        "observed_at", "previous_hash", "event_hash",
    ),
}


def _normalize_schema_sql(value):
    if type(value) is not str:
        return ""
    return re.sub(r"\s*([(),=<>])\s*", r"\1", " ".join(value.split()).casefold())


_EXPECTED_PERSISTENT_SQL = {}
for _match in re.finditer(
    r"CREATE TABLE (service_client_[a-z_]+)\s*(\(.*?\))\s*;",
    _PERSISTENT_SCHEMA,
    re.DOTALL,
):
    _EXPECTED_PERSISTENT_SQL[_match.group(1)] = _normalize_schema_sql(
        f"CREATE TABLE {_match.group(1)} {_match.group(2)}"
    )
if set(_EXPECTED_PERSISTENT_SQL) != set(_PERSISTENT_TABLE_COLUMNS):
    raise RuntimeError("Invalid persistent service-client schema constant")


def _canonical_text(value):
    return canonical_json(value).decode("utf-8")


def _record_payload(
    *,
    client_id,
    revision,
    owner_id,
    name,
    scopes,
    network_profile,
    created_at,
    expires_at,
    state,
    credential_digest,
    recovery_epoch,
    recorded_at,
    previous_hash,
):
    return {
        "schema_version": "service-client-record-v1",
        "client_id": client_id,
        "revision": revision,
        "owner_id": owner_id,
        "name": name,
        "scopes": list(scopes),
        "allowed_network_profile": network_profile,
        "created_at": created_at,
        "expires_at": expires_at,
        "state": state,
        "credential_digest": credential_digest,
        "recovery_epoch": recovery_epoch,
        "recorded_at": recorded_at,
        "previous_hash": previous_hash,
    }


def _payload_hash(value):
    return sha256(canonical_json(value)).hexdigest()


def _control_hash(epoch, event_sequence, event_hash, last_observed_at):
    return _payload_hash({
        "schema_version": "service-client-control-v1",
        "recovery_epoch": epoch,
        "event_sequence": event_sequence,
        "event_hash": event_hash,
        "last_observed_at": last_observed_at,
    })


def _usage_hash(client_id, credential_revision, last_used_at, use_revision):
    return _payload_hash({
        "schema_version": "service-client-usage-v1",
        "client_id": client_id,
        "credential_revision": credential_revision,
        "last_used_at": last_used_at,
        "use_revision": use_revision,
    })


def _event_payload(
    sequence,
    event_type,
    client_id,
    client_revision,
    recovery_epoch,
    observed_at,
    previous_hash,
):
    return {
        "schema_version": "service-client-event-v1",
        "sequence": sequence,
        "event_type": event_type,
        "client_id": client_id,
        "client_revision": client_revision,
        "recovery_epoch": recovery_epoch,
        "observed_at": observed_at,
        "previous_hash": previous_hash,
    }


class PersistentServiceClientRegistry:
    """SQLite-backed immutable credential history with a CAS current head."""

    def __init__(
        self,
        store,
        *,
        verify_owner,
        verify_recovery,
        clock,
        random_bytes,
    ):
        if not isinstance(store, Store):
            raise TypeError("Persistent service clients require the application Store")
        if not all(callable(value) for value in (
            verify_owner, verify_recovery, clock, random_bytes,
        )):
            raise TypeError("Persistent service client dependencies must be trusted callables")
        self._store = store
        self._verify_owner = verify_owner
        self._verify_recovery = verify_recovery
        self._clock = clock
        self._random_bytes = random_bytes
        self._last_now = None
        self._clock_lock = RLock()
        self._initialize()

    def _initialize(self):
        try:
            self._initialize_checked()
        except sqlite3.Error as exc:
            raise CorruptServiceClient(
                "Persistent service-client schema cannot be read"
            ) from exc

    def _initialize_checked(self):
        expected_names = set(_PERSISTENT_TABLE_COLUMNS)
        with self._store._connection() as db:
            existing = {
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND lower(name) GLOB 'service_client_*'"
                )
            }
            if not existing:
                db.executescript(_PERSISTENT_SCHEMA)
                db.execute(
                    "INSERT INTO service_client_migrations VALUES (?,?)",
                    (_PERSISTENT_SCHEMA_VERSION, _PERSISTENT_SCHEMA_HASH),
                )
                db.execute(
                    "INSERT INTO service_client_control VALUES (1,0,0,NULL,0,?)",
                    (_control_hash(0, 0, None, 0),),
                )
            elif existing != expected_names:
                raise CorruptServiceClient("Persistent service-client schema is incomplete")
            for table, columns in _PERSISTENT_TABLE_COLUMNS.items():
                observed = tuple(
                    row["name"] for row in db.execute(f"PRAGMA table_info({table})")
                )
                if observed != columns:
                    raise CorruptServiceClient("Persistent service-client schema changed")
            objects = {
                row["name"]: _normalize_schema_sql(row["sql"])
                for row in db.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='table' "
                    "AND lower(name) GLOB 'service_client_*'"
                )
            }
            if objects != _EXPECTED_PERSISTENT_SQL:
                raise CorruptServiceClient(
                    "Persistent service-client constraints changed"
                )
            governed = tuple(sorted(expected_names))
            placeholders = ",".join("?" for _ in governed)
            unexpected = []
            for item in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                f"WHERE type IN ('index','trigger') AND tbl_name IN ({placeholders})",
                governed,
            ):
                automatic = (
                    item["type"] == "index"
                    and item["sql"] is None
                    and item["name"].startswith("sqlite_autoindex_")
                )
                if not automatic:
                    unexpected.append((item["type"], item["name"], item["tbl_name"]))
            service_target = re.compile(r"\bservice_client_[a-z0-9_]+\b", re.IGNORECASE)
            for item in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE type IN ('trigger','view')"
            ):
                if type(item["sql"]) is str and service_target.search(item["sql"]):
                    marker = (item["type"], item["name"], item["tbl_name"])
                    if marker not in unexpected:
                        unexpected.append(marker)
            if unexpected:
                raise CorruptServiceClient(
                    "Unexpected persistent service-client schema object"
                )
            migrations = list(db.execute(
                "SELECT version,sha256 FROM service_client_migrations ORDER BY version"
            ))
            if (
                len(migrations) != 1
                or migrations[0]["version"] != _PERSISTENT_SCHEMA_VERSION
                or migrations[0]["sha256"] != _PERSISTENT_SCHEMA_HASH
            ):
                raise CorruptServiceClient("Persistent service-client migration is invalid")
            _epoch, event_sequence, event_hash, last_observed_at, _ = self._read_control(db)
            observed_sequence, observed_hash = self._audit_events(db)
            if (event_sequence, event_hash) != (observed_sequence, observed_hash):
                raise CorruptServiceClient("Service-client event head is inconsistent")
            self._audit_storage(db, recovery_epoch=_epoch, last_observed_at=last_observed_at)
            if event_sequence:
                final_event = db.execute(
                    "SELECT observed_at FROM service_client_events WHERE sequence=?",
                    (event_sequence,),
                ).fetchone()
                if final_event is None or final_event["observed_at"] > last_observed_at:
                    raise CorruptServiceClient("Service-client durable clock is inconsistent")

    def _now(self):
        with self._clock_lock:
            try:
                value = self._clock()
            except Exception:  # noqa: BLE001 - sanitize the trusted clock boundary
                raise ServiceClientDenied("Trusted service client clock is unavailable") from None
            if type(value) is not int or not 0 <= value <= MAX_INTEGER:
                raise ServiceClientDenied("Trusted service client clock is invalid")
            if self._last_now is not None and value < self._last_now:
                raise ServiceClientDenied("Trusted service client clock moved backwards")
            self._last_now = value
            return value

    def _owner(self, request):
        try:
            actor = self._verify_owner(request)
        except Exception:  # noqa: BLE001 - sanitize the owner-verification boundary
            raise ServiceClientDenied("Authenticated owner is required") from None
        if type(actor) is not Actor or actor.kind != "human":
            raise ServiceClientDenied("Authenticated owner is required")
        return actor

    def _recovery(self, request):
        try:
            verified = self._verify_recovery(request)
        except Exception:  # noqa: BLE001 - sanitize the recovery-verification boundary
            verified = False
        if verified is not True:
            raise ServiceClientDenied("Authenticated recovery authority is required")

    def _new_secret(self):
        try:
            raw = self._random_bytes(32)
            secret = _secret(raw)
        except Exception:  # noqa: BLE001 - sanitize the entropy boundary
            raise ServiceClientDenied("Service client credential could not be issued") from None
        digest = _secret_digest(secret)
        raw = None
        if digest is None:
            secret = None
            raise ServiceClientDenied("Service client credential could not be issued")
        return secret, digest

    @staticmethod
    def _read_control(db):
        rows = list(db.execute(
            "SELECT singleton,recovery_epoch,event_sequence,event_hash,last_observed_at,"
            "control_hash "
            "FROM service_client_control"
        ))
        if len(rows) != 1:
            raise CorruptServiceClient("Service-client recovery control is invalid")
        row = rows[0]
        epoch = row["recovery_epoch"]
        event_sequence = row["event_sequence"]
        event_hash = row["event_hash"]
        last_observed_at = row["last_observed_at"]
        if (
            row["singleton"] != 1
            or type(epoch) is not int
            or epoch < 0
            or type(event_sequence) is not int
            or event_sequence < 0
            or type(last_observed_at) is not int
            or not 0 <= last_observed_at <= MAX_INTEGER
            or (event_sequence == 0 and event_hash is not None)
            or (
                event_sequence > 0
                and (
                    type(event_hash) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", event_hash) is None
                )
            )
            or type(row["control_hash"]) is not str
            or not hmac.compare_digest(
                row["control_hash"],
                _control_hash(epoch, event_sequence, event_hash, last_observed_at),
            )
        ):
            raise CorruptServiceClient("Service-client recovery control is invalid")
        return (
            epoch,
            event_sequence,
            event_hash,
            last_observed_at,
            row["control_hash"],
        )

    @classmethod
    def _read_epoch(cls, db):
        return cls._read_control(db)[0]

    @classmethod
    def _claim_time(cls, db, now):
        epoch, sequence, event_hash, last_observed_at, control_hash = cls._read_control(db)
        if now < last_observed_at:
            raise ServiceClientDenied("Trusted service client clock moved backwards")
        if now == last_observed_at:
            return epoch
        next_hash = _control_hash(epoch, sequence, event_hash, now)
        changed = db.execute(
            "UPDATE service_client_control SET last_observed_at=?,control_hash=? "
            "WHERE singleton=1 AND recovery_epoch=? AND event_sequence=? "
            "AND event_hash IS ? AND last_observed_at=? AND control_hash=?",
            (
                now,
                next_hash,
                epoch,
                sequence,
                event_hash,
                last_observed_at,
                control_hash,
            ),
        ).rowcount
        if changed != 1:
            raise ServiceClientDenied("Service-client durable clock changed concurrently")
        return epoch

    def _persist_time(self, now):
        """Advance the durable clock before an operation that may be denied.

        The second in-transaction claim at each mutation/authentication boundary prevents
        a concurrent process with a newer trusted time from being followed by an older
        authorization decision. Keeping this first claim in its own committed transaction
        also means an expiry denial cannot be rolled back and later resurrected on restart.
        """
        try:
            with self._store._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                return self._claim_time(db, now)
        except sqlite3.Error as exc:
            raise ServiceClientDenied("Service client storage is unavailable") from exc

    @staticmethod
    def _parse_record(row):
        try:
            client_id = uuid_string(row["client_id"])
            owner_id = uuid_string(row["owner_id"])
            revision = row["revision"]
            created_at = row["created_at"]
            expires_at = row["expires_at"]
            recovery_epoch = row["recovery_epoch"]
            recorded_at = row["recorded_at"]
            if (
                type(revision) is not int
                or revision < 1
                or type(created_at) is not int
                or type(expires_at) is not int
                or not 0 <= created_at < expires_at <= MAX_INTEGER
                or expires_at - created_at > MAX_SERVICE_CLIENT_TTL_SECONDS
                or type(recovery_epoch) is not int
                or recovery_epoch < 0
                or type(recorded_at) is not int
                or not created_at <= recorded_at <= MAX_INTEGER
            ):
                raise ValueError
            name = _bounded_name(row["name"])
            if name is None:
                raise ValueError
            decoded_scopes = json.loads(row["scopes_json"])
            scopes = _scopes(decoded_scopes)
            if decoded_scopes != list(scopes) or row["scopes_json"] != _canonical_text(decoded_scopes):
                raise ValueError
            network_profile = row["network_profile"]
            if network_profile not in _NETWORK_PROFILES:
                raise ValueError
            state = row["state"]
            credential_digest = row["credential_digest"]
            if state == "active":
                if (
                    type(credential_digest) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", credential_digest) is None
                ):
                    raise ValueError
            elif state == "revoked":
                if credential_digest is not None:
                    raise ValueError
            else:
                raise ValueError
            previous_hash = row["previous_hash"]
            if revision == 1:
                if previous_hash is not None:
                    raise ValueError
            elif (
                type(previous_hash) is not str
                or re.fullmatch(r"[0-9a-f]{64}", previous_hash) is None
            ):
                raise ValueError
            payload = _record_payload(
                client_id=client_id,
                revision=revision,
                owner_id=owner_id,
                name=name,
                scopes=scopes,
                network_profile=network_profile,
                created_at=created_at,
                expires_at=expires_at,
                state=state,
                credential_digest=credential_digest,
                recovery_epoch=recovery_epoch,
                recorded_at=recorded_at,
                previous_hash=previous_hash,
            )
            record_hash = row["record_hash"]
            if (
                type(record_hash) is not str
                or not hmac.compare_digest(record_hash, _payload_hash(payload))
            ):
                raise ValueError
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            ServiceClientDenied,
        ) as exc:
            raise CorruptServiceClient(
                "Immutable service-client record failed integrity checks"
            ) from exc
        record = ServiceClientRecord(
            client_id=client_id,
            owner_id=owner_id,
            name=name,
            scopes=scopes,
            allowed_network_profile=network_profile,
            created_at=created_at,
            expires_at=expires_at,
            revision=revision,
            state=state,
            credential_digest=credential_digest or "0" * 64,
        )
        return record, payload, record_hash

    @classmethod
    def _history(cls, db, client_id):
        rows = list(db.execute(
            "SELECT * FROM service_client_records WHERE client_id=? ORDER BY revision",
            (client_id,),
        ))
        head = db.execute(
            "SELECT * FROM service_client_heads WHERE client_id=?", (client_id,),
        ).fetchone()
        if not rows and head is None:
            raise KeyError(client_id)
        if not rows or head is None:
            raise CorruptServiceClient("Service-client head or history is missing")
        parsed = []
        previous_hash = None
        previous_record = None
        previous_payload = None
        for expected_revision, row in enumerate(rows, 1):
            record, payload, record_hash = cls._parse_record(row)
            if (
                record.client_id != client_id
                or record.revision != expected_revision
                or payload["previous_hash"] != previous_hash
            ):
                raise CorruptServiceClient("Service-client revision chain is invalid")
            if previous_record is None:
                if record.state != "active":
                    raise CorruptServiceClient("Service-client genesis revision is invalid")
            else:
                stable_fields = (
                    "owner_id",
                    "name",
                    "scopes",
                    "allowed_network_profile",
                    "created_at",
                    "expires_at",
                )
                stable_fields_changed = any(
                        payload[field] != previous_payload[field]
                        for field in stable_fields
                    )
                transition_valid = False
                if previous_record.state == "active":
                    transition_valid = (
                        record.state == "revoked"
                        or (
                            record.state == "active"
                            and payload["recovery_epoch"]
                            == previous_payload["recovery_epoch"]
                        )
                    )
                elif previous_record.state == "revoked":
                    transition_valid = (
                        record.state == "revoked"
                        and payload["recovery_epoch"]
                        > previous_payload["recovery_epoch"]
                    )
                if (
                    stable_fields_changed
                    or payload["recorded_at"] < previous_payload["recorded_at"]
                    or payload["recovery_epoch"] < previous_payload["recovery_epoch"]
                    or not transition_valid
                ):
                    raise CorruptServiceClient(
                        "Service-client revision transition is invalid"
                    )
            parsed.append((record, payload, record_hash))
            previous_hash = record_hash
            previous_record = record
            previous_payload = payload
        current = parsed[-1]
        if (
            head["client_id"] != client_id
            or head["revision"] != current[0].revision
            or head["state"] != current[0].state
            or type(head["record_hash"]) is not str
            or not hmac.compare_digest(head["record_hash"], current[2])
        ):
            raise CorruptServiceClient("Service-client current head is invalid")
        return current, tuple(parsed)

    @classmethod
    def _audit_storage(cls, db, *, recovery_epoch, last_observed_at):
        record_keys = {
            (row["client_id"], row["revision"])
            for row in db.execute(
                "SELECT client_id,revision FROM service_client_records"
            )
        }
        client_ids = {client_id for client_id, _revision in record_keys}
        head_ids = {
            row["client_id"] for row in db.execute("SELECT client_id FROM service_client_heads")
        }
        if client_ids != head_ids:
            raise CorruptServiceClient("Service-client history/head set is inconsistent")

        event_keys = [
            (row["client_id"], row["client_revision"])
            for row in db.execute(
                "SELECT client_id,client_revision FROM service_client_events"
            )
        ]
        if len(event_keys) != len(set(event_keys)) or set(event_keys) != record_keys:
            raise CorruptServiceClient("Service-client lifecycle coverage is inconsistent")

        active_keys = set()
        records_by_key = {}
        for client_id in sorted(client_ids):
            current, history = cls._history(db, client_id)
            if current[1]["recovery_epoch"] != recovery_epoch:
                raise CorruptServiceClient("Service-client recovery epoch is inconsistent")
            for record, payload, _record_hash in history:
                records_by_key[(record.client_id, record.revision)] = record
                if record.state == "active":
                    active_keys.add((record.client_id, record.revision))
                if payload["recorded_at"] > last_observed_at:
                    raise CorruptServiceClient("Service-client record exceeds the durable clock")

        usage_keys = {
            (row["client_id"], row["credential_revision"])
            for row in db.execute(
                "SELECT client_id,credential_revision FROM service_client_usage"
            )
        }
        if usage_keys != active_keys:
            raise CorruptServiceClient("Service-client usage coverage is inconsistent")
        for client_id, revision in sorted(usage_keys):
            last_used_at, _use_revision, _usage_hash_value = cls._usage(
                db, client_id, revision,
            )
            record = records_by_key[(client_id, revision)]
            if last_used_at is not None and not (
                record.created_at <= last_used_at <= last_observed_at
            ):
                raise CorruptServiceClient("Service-client usage time is inconsistent")

    @staticmethod
    def _insert_record(db, payload):
        record_hash = _payload_hash(payload)
        try:
            db.execute(
                "INSERT INTO service_client_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["client_id"], payload["revision"], payload["owner_id"],
                    payload["name"], _canonical_text(payload["scopes"]),
                    payload["allowed_network_profile"], payload["created_at"],
                    payload["expires_at"], payload["state"],
                    payload["credential_digest"], payload["recovery_epoch"],
                    payload["recorded_at"], payload["previous_hash"], record_hash,
                ),
            )
        except sqlite3.IntegrityError:
            raise ServiceClientDenied("Service client credential or revision conflicts") from None
        return record_hash

    @staticmethod
    def _set_head(db, payload, record_hash, *, expected=None):
        if expected is None:
            try:
                db.execute(
                    "INSERT INTO service_client_heads VALUES (?,?,?,?)",
                    (
                        payload["client_id"], payload["revision"], record_hash,
                        payload["state"],
                    ),
                )
            except sqlite3.IntegrityError:
                raise ServiceClientDenied("Service client ID is already bound") from None
            return
        changed = db.execute(
            "UPDATE service_client_heads SET revision=?,record_hash=?,state=? "
            "WHERE client_id=? AND revision=? AND record_hash=?",
            (
                payload["revision"], record_hash, payload["state"],
                payload["client_id"], expected[0], expected[1],
            ),
        ).rowcount
        if changed != 1:
            raise ServiceClientDenied("Service client head changed concurrently")

    @staticmethod
    def _insert_usage(db, client_id, credential_revision):
        db.execute(
            "INSERT INTO service_client_usage VALUES (?,?,NULL,0,?)",
            (
                client_id,
                credential_revision,
                _usage_hash(client_id, credential_revision, None, 0),
            ),
        )

    @classmethod
    def _audit_events(cls, db):
        rows = list(db.execute("SELECT * FROM service_client_events ORDER BY sequence"))
        previous_hash = None
        previous_observed_at = 0
        for expected_sequence, row in enumerate(rows, 1):
            try:
                client_id = uuid_string(row["client_id"])
                sequence = row["sequence"]
                client_revision = row["client_revision"]
                recovery_epoch = row["recovery_epoch"]
                observed_at = row["observed_at"]
                event_type = row["event_type"]
                if (
                    sequence != expected_sequence
                    or event_type not in _PERSISTENT_EVENT_TYPES
                    or type(client_revision) is not int
                    or client_revision < 1
                    or type(recovery_epoch) is not int
                    or recovery_epoch < 0
                    or type(observed_at) is not int
                    or observed_at < 0
                    or observed_at < previous_observed_at
                    or row["previous_hash"] != previous_hash
                ):
                    raise ValueError
                record_row = db.execute(
                    "SELECT * FROM service_client_records "
                    "WHERE client_id=? AND revision=?",
                    (client_id, client_revision),
                ).fetchone()
                record, record_payload, _ = cls._parse_record(record_row)
                if client_revision == 1:
                    expected_event_type = "service_client.created"
                    transition_valid = record.state == "active"
                else:
                    previous_row = db.execute(
                        "SELECT * FROM service_client_records "
                        "WHERE client_id=? AND revision=?",
                        (client_id, client_revision - 1),
                    ).fetchone()
                    previous_record, previous_payload, _ = cls._parse_record(previous_row)
                    transition_valid = previous_record.state == "active"
                    if previous_record.state == "revoked":
                        transition_valid = (
                            record.state == "revoked"
                            and record_payload["recovery_epoch"]
                            > previous_payload["recovery_epoch"]
                        )
                        expected_event_type = "service_client.recovery_advanced"
                    elif record.state == "active":
                        expected_event_type = "service_client.rotated"
                    elif (
                        record_payload["recovery_epoch"]
                        > previous_payload["recovery_epoch"]
                    ):
                        expected_event_type = "service_client.recovery_revoked"
                    else:
                        expected_event_type = "service_client.revoked"
                if (
                    event_type != expected_event_type
                    or not transition_valid
                    or record_payload["recovery_epoch"] != recovery_epoch
                    or record_payload["recorded_at"] != observed_at
                ):
                    raise ValueError
                payload = _event_payload(
                    sequence,
                    event_type,
                    client_id,
                    client_revision,
                    recovery_epoch,
                    observed_at,
                    previous_hash,
                )
                event_hash = row["event_hash"]
                if (
                    type(event_hash) is not str
                    or not hmac.compare_digest(event_hash, _payload_hash(payload))
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError) as exc:
                raise CorruptServiceClient(
                    "Service-client event history failed integrity checks"
                ) from exc
            previous_hash = event_hash
            previous_observed_at = observed_at
        return len(rows), previous_hash

    @classmethod
    def _append_event(
        cls,
        db,
        *,
        event_type,
        client_id,
        client_revision,
        recovery_epoch,
        observed_at,
    ):
        if event_type not in _PERSISTENT_EVENT_TYPES:
            raise ValueError("Unknown service-client event type")
        count, previous_hash = cls._audit_events(db)
        (
            epoch,
            control_sequence,
            control_event_hash,
            last_observed_at,
            control_hash,
        ) = cls._read_control(db)
        if (control_sequence, control_event_hash) != (count, previous_hash):
            raise CorruptServiceClient("Service-client event head is inconsistent")
        if observed_at > last_observed_at:
            raise CorruptServiceClient("Service-client event exceeds the durable clock")
        sequence = count + 1
        payload = _event_payload(
            sequence,
            event_type,
            client_id,
            client_revision,
            recovery_epoch,
            observed_at,
            previous_hash,
        )
        event_hash = _payload_hash(payload)
        db.execute(
            "INSERT INTO service_client_events VALUES (?,?,?,?,?,?,?,?)",
            (
                sequence,
                event_type,
                client_id,
                client_revision,
                recovery_epoch,
                observed_at,
                previous_hash,
                event_hash,
            ),
        )
        next_control_hash = _control_hash(
            epoch, sequence, event_hash, last_observed_at,
        )
        changed = db.execute(
            "UPDATE service_client_control SET event_sequence=?,event_hash=?,control_hash=? "
            "WHERE singleton=1 AND recovery_epoch=? AND event_sequence=? "
            "AND event_hash IS ? AND last_observed_at=? AND control_hash=?",
            (
                sequence,
                event_hash,
                next_control_hash,
                epoch,
                control_sequence,
                control_event_hash,
                last_observed_at,
                control_hash,
            ),
        ).rowcount
        if changed != 1:
            raise ServiceClientDenied("Service-client event head changed concurrently")

    @staticmethod
    def _usage(db, client_id, credential_revision):
        row = db.execute(
            "SELECT * FROM service_client_usage WHERE client_id=? AND credential_revision=?",
            (client_id, credential_revision),
        ).fetchone()
        if row is None:
            raise CorruptServiceClient("Service-client usage head is missing")
        last_used_at = row["last_used_at"]
        use_revision = row["use_revision"]
        if (
            row["client_id"] != client_id
            or row["credential_revision"] != credential_revision
            or (
                last_used_at is not None
                and (
                    type(last_used_at) is not int
                    or not 0 <= last_used_at <= MAX_INTEGER
                )
            )
            or type(use_revision) is not int
            or use_revision < 0
            or (last_used_at is None) != (use_revision == 0)
            or type(row["usage_hash"]) is not str
            or not hmac.compare_digest(
                row["usage_hash"],
                _usage_hash(client_id, credential_revision, last_used_at, use_revision),
            )
        ):
            raise CorruptServiceClient("Service-client usage head is invalid")
        return last_used_at, use_revision, row["usage_hash"]

    @staticmethod
    def _record_for_return(payload):
        return ServiceClientRecord(
            client_id=payload["client_id"],
            owner_id=payload["owner_id"],
            name=payload["name"],
            scopes=tuple(payload["scopes"]),
            allowed_network_profile=payload["allowed_network_profile"],
            created_at=payload["created_at"],
            expires_at=payload["expires_at"],
            revision=payload["revision"],
            state=payload["state"],
            credential_digest="0" * 64,
        )

    def issue(
        self,
        owner_request,
        *,
        client_id,
        name,
        scopes,
        allowed_network_profile,
        expires_at,
    ):
        owner = self._owner(owner_request)
        now = self._now()
        try:
            client_id = uuid_string(client_id)
        except (TypeError, ValueError):
            raise ServiceClientDenied("Service client ID is invalid") from None
        name = _bounded_name(name)
        if name is None:
            raise ServiceClientDenied("Service client name is invalid")
        scopes = _scopes(scopes)
        if (
            allowed_network_profile not in _NETWORK_PROFILES
            or type(expires_at) is not int
            or not now < expires_at <= MAX_INTEGER
            or expires_at - now > MAX_SERVICE_CLIENT_TTL_SECONDS
        ):
            raise ServiceClientDenied("Service client expiry or network profile is invalid")
        self._persist_time(now)
        secret = digest = None
        try:
            secret, digest = self._new_secret()
            with self._store._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                epoch = self._claim_time(db, now)
                if db.execute(
                    "SELECT 1 FROM service_client_heads WHERE client_id=?", (client_id,),
                ).fetchone() is not None:
                    raise ServiceClientDenied("Service client ID is already bound")
                payload = _record_payload(
                    client_id=client_id,
                    revision=1,
                    owner_id=owner.id,
                    name=name,
                    scopes=scopes,
                    network_profile=allowed_network_profile,
                    created_at=now,
                    expires_at=expires_at,
                    state="active",
                    credential_digest=digest,
                    recovery_epoch=epoch,
                    recorded_at=now,
                    previous_hash=None,
                )
                record_hash = self._insert_record(db, payload)
                self._set_head(db, payload, record_hash)
                self._insert_usage(db, client_id, 1)
                self._append_event(
                    db,
                    event_type="service_client.created",
                    client_id=client_id,
                    client_revision=1,
                    recovery_epoch=epoch,
                    observed_at=now,
                )
        except sqlite3.Error as exc:
            secret = digest = None
            raise ServiceClientDenied("Service client storage is unavailable") from exc
        except BaseException:
            secret = digest = None
            raise
        return IssuedServiceClient(self._record_for_return(payload), secret)

    def _owned_current(self, db, owner, client_id):
        try:
            client_id = uuid_string(client_id)
            current, history = self._history(db, client_id)
        except (KeyError, TypeError, ValueError):
            raise ServiceClientDenied("Owned service client is unavailable") from None
        if current[0].owner_id != owner.id:
            raise ServiceClientDenied("Authenticated owner is required")
        return current, history

    def rotate(self, owner_request, client_id, *, expected_revision):
        owner = self._owner(owner_request)
        now = self._now()
        if type(expected_revision) is not int or expected_revision < 1:
            raise ServiceClientDenied("Service client revision is invalid")
        self._persist_time(now)
        secret = digest = None
        try:
            secret, digest = self._new_secret()
            with self._store._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                current, _ = self._owned_current(db, owner, client_id)
                record, payload, record_hash = current
                epoch = self._claim_time(db, now)
                if (
                    record.revision != expected_revision
                    or record.state != "active"
                    or now >= record.expires_at
                    or payload["recovery_epoch"] != epoch
                ):
                    raise ServiceClientDenied("Service client cannot rotate")
                next_payload = _record_payload(
                    client_id=record.client_id,
                    revision=record.revision + 1,
                    owner_id=record.owner_id,
                    name=record.name,
                    scopes=record.scopes,
                    network_profile=record.allowed_network_profile,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                    state="active",
                    credential_digest=digest,
                    recovery_epoch=payload["recovery_epoch"],
                    recorded_at=now,
                    previous_hash=record_hash,
                )
                next_hash = self._insert_record(db, next_payload)
                self._set_head(
                    db, next_payload, next_hash, expected=(record.revision, record_hash),
                )
                self._insert_usage(db, record.client_id, record.revision + 1)
                self._append_event(
                    db,
                    event_type="service_client.rotated",
                    client_id=record.client_id,
                    client_revision=record.revision + 1,
                    recovery_epoch=payload["recovery_epoch"],
                    observed_at=now,
                )
        except sqlite3.Error as exc:
            secret = digest = None
            raise ServiceClientDenied("Service client storage is unavailable") from exc
        except BaseException:
            secret = digest = None
            raise
        return IssuedServiceClient(self._record_for_return(next_payload), secret)

    def revoke(self, owner_request, client_id, *, expected_revision):
        owner = self._owner(owner_request)
        now = self._now()
        if type(expected_revision) is not int or expected_revision < 1:
            raise ServiceClientDenied("Service client revision is invalid")
        self._persist_time(now)
        try:
            with self._store._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                current, _ = self._owned_current(db, owner, client_id)
                record, payload, record_hash = current
                epoch = self._claim_time(db, now)
                if (
                    record.revision != expected_revision
                    or record.state != "active"
                    or payload["recovery_epoch"] != epoch
                ):
                    raise ServiceClientDenied("Service client is already revoked")
                next_payload = _record_payload(
                    client_id=record.client_id,
                    revision=record.revision + 1,
                    owner_id=record.owner_id,
                    name=record.name,
                    scopes=record.scopes,
                    network_profile=record.allowed_network_profile,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                    state="revoked",
                    credential_digest=None,
                    recovery_epoch=payload["recovery_epoch"],
                    recorded_at=now,
                    previous_hash=record_hash,
                )
                next_hash = self._insert_record(db, next_payload)
                self._set_head(
                    db, next_payload, next_hash, expected=(record.revision, record_hash),
                )
                self._append_event(
                    db,
                    event_type="service_client.revoked",
                    client_id=record.client_id,
                    client_revision=record.revision + 1,
                    recovery_epoch=payload["recovery_epoch"],
                    observed_at=now,
                )
        except sqlite3.Error as exc:
            raise ServiceClientDenied("Service client storage is unavailable") from exc
        return self._record_for_return(next_payload)

    def authenticate(self, secret, *, network_profile):
        digest = _secret_digest(secret)
        secret = None
        now = self._now()
        if digest is None:
            raise ServiceClientDenied("Service client credential is invalid")
        self._persist_time(now)
        try:
            with self._store._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT client_id FROM service_client_records WHERE credential_digest=?",
                    (digest,),
                ).fetchone()
                if row is None:
                    raise ServiceClientDenied("Service client credential is invalid")
                current, _ = self._history(db, row["client_id"])
                record, payload, _record_hash = current
                epoch = self._claim_time(db, now)
                if (
                    record.state != "active"
                    or payload["credential_digest"] != digest
                    or payload["recovery_epoch"] != epoch
                    or now >= record.expires_at
                ):
                    reason = "expired" if now >= record.expires_at else "invalid"
                    raise ServiceClientDenied(f"Service client credential is {reason}")
                if network_profile != record.allowed_network_profile:
                    raise ServiceClientDenied("Service client network profile differs")
                _last_used_at, use_revision, usage_hash = self._usage(
                    db, record.client_id, record.revision,
                )
                next_use_revision = use_revision + 1
                next_usage_hash = _usage_hash(
                    record.client_id, record.revision, now, next_use_revision,
                )
                changed = db.execute(
                    "UPDATE service_client_usage SET last_used_at=?,use_revision=?,usage_hash=? "
                    "WHERE client_id=? AND credential_revision=? AND use_revision=? "
                    "AND usage_hash=?",
                    (
                        now, next_use_revision, next_usage_hash, record.client_id,
                        record.revision, use_revision, usage_hash,
                    ),
                ).rowcount
                if changed != 1:
                    raise ServiceClientDenied("Service client usage changed concurrently")
        except sqlite3.Error as exc:
            raise ServiceClientDenied("Service client storage is unavailable") from exc
        actor = Actor(record.client_id, "service_client", "service_credential")
        return ServiceClientPrincipal(
            client_id=record.client_id,
            actor=actor,
            scopes=record.scopes,
            allowed_network_profile=record.allowed_network_profile,
            expires_at=record.expires_at,
            credential_revision=record.revision,
        )

    def verify_current(self, client_id, *, credential_revision, scope, network_profile):
        """Read-only re-check that an authenticated credential still holds its grant.

        Used after a bearer read is materialized, so a revoke, rotation, expiry or recovery
        committed while the read ran withholds the projection. It never touches last-used.
        """
        now = self._now()
        try:
            client_id = uuid_string(client_id)
            with self._store._connection() as db:
                current, _history = self._history(db, client_id)
                record, payload, _record_hash = current
                epoch = self._read_epoch(db)
        except (KeyError, TypeError, ValueError, CorruptServiceClient, sqlite3.Error):
            raise ServiceClientDenied("Service client credential is invalid") from None
        if (
            record.state != "active"
            or record.revision != credential_revision
            or payload["recovery_epoch"] != epoch
            or now >= record.expires_at
            or record.allowed_network_profile != network_profile
            or scope not in record.scopes
        ):
            raise ServiceClientDenied("Service client credential is invalid")
        return Actor(record.client_id, "service_client", "service_credential")

    @staticmethod
    def _public(record):
        return {
            "client_id": record.client_id,
            "owner_id": record.owner_id,
            "name": record.name,
            "scopes": list(record.scopes),
            "allowed_network_profile": record.allowed_network_profile,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
            "revision": record.revision,
            "state": record.state,
        }

    def list_for_owner(self, owner_request, *, after_client_id=None, limit=50):
        owner = self._owner(owner_request)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ServiceClientDenied("Service client page size is invalid")
        if after_client_id is not None:
            try:
                after_client_id = uuid_string(after_client_id)
            except (TypeError, ValueError):
                raise ServiceClientDenied("Service client cursor is invalid") from None
        now = self._now()
        self._persist_time(now)
        try:
            with self._store._connection() as db:
                parameters = [owner.id]
                cursor_clause = ""
                if after_client_id is not None:
                    cursor_clause = "AND h.client_id>? "
                    parameters.append(after_client_id)
                parameters.append(limit + 1)
                rows = list(db.execute(
                    "SELECT h.client_id FROM service_client_heads h "
                    "JOIN service_client_records r ON r.client_id=h.client_id "
                    "AND r.revision=h.revision "
                    "WHERE r.owner_id=? "
                    f"{cursor_clause}ORDER BY h.client_id LIMIT ?",
                    tuple(parameters),
                ))
                page = rows[:limit]
                items = []
                for row in page:
                    current, _history = self._history(db, row["client_id"])
                    if current[0].owner_id != owner.id:
                        raise CorruptServiceClient(
                            "Service-client owner projection is inconsistent"
                        )
                    items.append(self._public(current[0]))
        except sqlite3.Error as exc:
            raise ServiceClientDenied("Service client storage is unavailable") from exc
        return {
            "items": items,
            "next_cursor": page[-1]["client_id"] if len(rows) > limit else None,
        }

    def snapshot(self, owner_request, client_id):
        owner = self._owner(owner_request)
        now = self._now()
        self._persist_time(now)
        with self._store._connection() as db:
            current, _ = self._owned_current(db, owner, client_id)
            return self._public(current[0])

    def usage_snapshot(self, owner_request, client_id):
        owner = self._owner(owner_request)
        now = self._now()
        self._persist_time(now)
        with self._store._connection() as db:
            current, history = self._owned_current(db, owner, client_id)
            record = current[0]
            credential_revision = record.revision
            if record.state != "active":
                active = [item[0] for item in history if item[0].state == "active"]
                if not active:
                    raise CorruptServiceClient("Service client has no credential history")
                credential_revision = active[-1].revision
            last_used_at, use_revision, _ = self._usage(
                db, record.client_id, credential_revision,
            )
            return {
                "credential_revision": credential_revision,
                "last_used_at": last_used_at,
                "use_revision": use_revision,
            }

    @classmethod
    def _revoke_all_in_transaction(cls, db, *, expected_epoch, new_epoch, now):
        """Revoke every head and advance the recovery epoch inside the caller's writer.

        The owner-recovery reconciliation start calls this in its one DB transaction; the
        caller has already authenticated the recovery and owns the transaction.
        """
        if (
            type(expected_epoch) is not int
            or type(new_epoch) is not int
            or expected_epoch < 0
            or new_epoch <= expected_epoch
        ):
            raise ServiceClientDenied("Service client recovery epoch is invalid")
        observed_epoch = cls._claim_time(db, now)
        if observed_epoch != expected_epoch:
            raise ServiceClientDenied("Service client recovery epoch changed")
        head_ids = [
            row["client_id"]
            for row in db.execute(
                "SELECT client_id FROM service_client_heads "
                "ORDER BY client_id"
            )
        ]
        revoked_count = 0
        for current_id in head_ids:
            current, _ = cls._history(db, current_id)
            record, _, record_hash = current
            if record.state == "active":
                revoked_count += 1
                recovery_event = "service_client.recovery_revoked"
            elif record.state == "revoked":
                recovery_event = "service_client.recovery_advanced"
            else:
                raise CorruptServiceClient("Service-client recovery head changed")
            next_payload = _record_payload(
                client_id=record.client_id,
                revision=record.revision + 1,
                owner_id=record.owner_id,
                name=record.name,
                scopes=record.scopes,
                network_profile=record.allowed_network_profile,
                created_at=record.created_at,
                expires_at=record.expires_at,
                state="revoked",
                credential_digest=None,
                recovery_epoch=new_epoch,
                recorded_at=now,
                previous_hash=record_hash,
            )
            next_hash = cls._insert_record(db, next_payload)
            cls._set_head(
                db,
                next_payload,
                next_hash,
                expected=(record.revision, record_hash),
            )
            cls._append_event(
                db,
                event_type=recovery_event,
                client_id=record.client_id,
                client_revision=record.revision + 1,
                recovery_epoch=new_epoch,
                observed_at=now,
            )
        (
            current_epoch,
            event_sequence,
            event_hash,
            last_observed_at,
            current_control_hash,
        ) = cls._read_control(db)
        if current_epoch != expected_epoch:
            raise ServiceClientDenied("Service client recovery epoch changed")
        next_control_hash = _control_hash(
            new_epoch, event_sequence, event_hash, last_observed_at,
        )
        changed = db.execute(
            "UPDATE service_client_control SET recovery_epoch=?,control_hash=? "
            "WHERE singleton=1 AND recovery_epoch=? AND event_sequence=? "
            "AND event_hash IS ? AND last_observed_at=? AND control_hash=?",
            (
                new_epoch,
                next_control_hash,
                expected_epoch,
                event_sequence,
                event_hash,
                last_observed_at,
                current_control_hash,
            ),
        ).rowcount
        if changed != 1:
            raise ServiceClientDenied("Service client recovery epoch changed")
        return revoked_count

    def revoke_all_for_recovery(
        self,
        recovery_request,
        *,
        expected_epoch,
        new_epoch,
    ):
        self._recovery(recovery_request)
        now = self._now()
        if (
            type(expected_epoch) is not int
            or type(new_epoch) is not int
            or expected_epoch < 0
            or new_epoch <= expected_epoch
        ):
            raise ServiceClientDenied("Service client recovery epoch is invalid")
        self._persist_time(now)
        try:
            with self._store._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                revoked_count = self._revoke_all_in_transaction(
                    db, expected_epoch=expected_epoch, new_epoch=new_epoch, now=now,
                )
        except sqlite3.Error as exc:
            raise ServiceClientDenied("Service client storage is unavailable") from exc
        return {
            "previous_epoch": expected_epoch,
            "new_epoch": new_epoch,
            "revoked_count": revoked_count,
        }
