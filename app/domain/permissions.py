"""Default-deny authorization and compiler projection firewall.

This module deliberately separates an immutable Actor provenance value from a live
principal. Only a trusted host integration may call :class:`HostPolicy` methods. Live
principals remain session/process capabilities; descriptors, grants, revocations and
verified compiler projections can be persisted in the existing vault SQLite database.
HTTP command authentication and cross-component command atomicity remain separate.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
from threading import RLock
from types import MappingProxyType
from uuid import uuid4

from .refs import (DomainContractError, EntityRef, MAX_INTEGER, MAX_JSON_BYTES, canonical_json,
                   parse_canonical, uuid_string)
from .schemas import Actor, ImmutableRecord, PURPOSES, SCHEMA_VERSION
from .store import DomainStore, StorageError, _writer


_ACTIONS = frozenset({"read", "write", "compile"})
_RUNTIME_PURPOSES = PURPOSES | frozenset({"compiler"})
_COMPILER_FIELDS = ("condition", "action", "exception", "prediction")
_CHANGE_KINDS = frozenset({"restore", "learn", "protect"})
_COMPILER_TARGETS = frozenset({
    "graph_config", "node_instruction", "handoff_schema", "memory_rule", "tool_policy"
})
_PROTECTED_TARGETS = frozenset({
    "authority_policy", "constitution", "final_human_approval", "current_test_requirements"
})
_SENSITIVE_KEYS = frozenset({"h_phi", "s_phi", "api_key", "credential", "secret"})
_SENSITIVE_KINDS = frozenset({"own_alternative", "inquiry_audit"})
# These are the only domain-v1 records in the current contract that directly record
# observed work behaviour. Audit/lens/design/source records are intentionally not a
# permissive fallback; extending this set requires a versioned contract change.
_BEHAVIOR_SUPPORT_KINDS = frozenset({"original_execution", "comparison_result"})
_MAX_POLICY_ROWS = 100_000


class CorruptPolicy(ValueError):
    """Persistent policy state or its migration contract cannot be verified."""


class AccessDenied(PermissionError):
    """Opaque refusal: callers do not learn whether another scope owns the object."""


def _expiry(value, now):
    if type(value) is not int or not now < value <= MAX_INTEGER:
        raise ValueError("Expiry must be a bounded future integer")
    return value


def _episode(value):
    if value is None:
        return None
    return uuid_string(value)


def _content_dependencies(record):
    """Return explicit parents and exact entity refs inside schema-owned content only."""
    body = record.body
    found = {EntityRef.from_dict(value) for value in body.get("parent_refs", [])}

    def visit(value, depth=0):
        if depth > 32:
            raise ValueError("Dependency nesting limit exceeded")
        if type(value) is dict:
            if set(value) == {"kind", "id", "version", "sha256"}:
                found.add(EntityRef.from_dict(value))
                return
            # Blob references are authorized by the artifact/resource record that owns
            # them; a persistent object registry will give blobs their own descriptors.
            if set(value) == {"vault_id", "purpose", "sha256", "size"}:
                return
            for child in value.values():
                visit(child, depth + 1)
        elif type(value) is list:
            for child in value:
                visit(child, depth + 1)

    visit(body["content"])
    return frozenset(found)


def _contains_sensitive_claim(value, depth=0):
    if depth > 32:
        raise ValueError("Sensitivity nesting limit exceeded")
    if type(value) is dict:
        for key, child in value.items():
            if key.casefold() in _SENSITIVE_KEYS:
                return True
            if _contains_sensitive_claim(child, depth + 1):
                return True
    elif type(value) is list:
        return any(_contains_sensitive_claim(child, depth + 1) for child in value)
    return False


@dataclass(frozen=True, slots=True)
class Principal:
    id: str
    actor: Actor
    kind: str
    purpose: str | None
    expires_at: int
    _session: object | None = None


@dataclass(frozen=True, slots=True)
class Grant:
    id: str
    issuer_id: str
    subject_id: str
    ref: EntityRef
    action: str
    purpose: str
    episode_id: str | None
    expires_at: int
    policy_revision: int


@dataclass(frozen=True, slots=True)
class ResourceDescriptor:
    ref: EntityRef
    purpose: str
    episode_id: str | None
    dependencies: frozenset[EntityRef]
    tainted: bool
    available: bool
    revision: int
    record: ImmutableRecord
    declared_secret: bool = False


@dataclass(frozen=True, slots=True)
class CompilerProjection:
    source_ref: EntityRef
    target: str
    change_kind: str
    values: tuple[tuple[str, str], ...]
    support_by_field: tuple[tuple[str, tuple[EntityRef, ...]], ...]
    expires_at: int
    digest: str

    @classmethod
    def create(cls, source, *, target, change_kind, support_by_field, expires_at):
        if type(source) is not ImmutableRecord or source.ref.kind != "hypothesis":
            raise ValueError("Compiler projection requires an exact hypothesis record")
        if type(target) is not str or target in _PROTECTED_TARGETS or target not in _COMPILER_TARGETS:
            raise ValueError("Protected or unsupported compiler target")
        if type(change_kind) is not str or change_kind not in _CHANGE_KINDS:
            raise ValueError("Unsupported change kind")
        if type(expires_at) is not int or not 0 < expires_at <= MAX_INTEGER:
            raise ValueError("Projection expiry must be bounded")
        if type(support_by_field) is not dict or set(support_by_field) != set(_COMPILER_FIELDS):
            raise ValueError("Every compiler field requires explicit behavioral support")
        content = source.body["content"]
        values = []
        support = []
        for field in _COMPILER_FIELDS:
            value = content.get(field)
            if type(value) is not str or not value or len(value.encode("utf-8")) > 65_536:
                raise ValueError("Compiler fields must be bounded nonempty text")
            refs = support_by_field[field]
            if type(refs) not in (tuple, list) or not refs or any(type(ref) is not EntityRef for ref in refs):
                raise ValueError("Behavior support must contain exact references")
            refs = tuple(refs)
            if len(refs) > 64 or len(set(refs)) != len(refs):
                raise ValueError("Behavior support must be bounded and unique")
            if any(ref == source.ref or ref.kind not in _BEHAVIOR_SUPPORT_KINDS for ref in refs):
                raise ValueError("Compiler support must reference observed behavioral evidence")
            values.append((field, value))
            support.append((field, refs))
        preimage = canonical_json({
            "schema_version": "compiler-projection-v1",
            "source_ref": source.ref.as_dict(),
            "target": target,
            "change_kind": change_kind,
            "values": dict(values),
            "support_by_field": {name: [ref.as_dict() for ref in refs] for name, refs in support},
            "expires_at": expires_at,
        })
        return cls(source.ref, target, change_kind, tuple(values), tuple(support), expires_at,
                   sha256(preimage).hexdigest())


def _actor_dict(actor):
    return {"id": actor.id, "kind": actor.kind, "origin": actor.origin}


def _actor_from_bytes(value):
    body = parse_canonical(value)
    if type(body) is not dict or set(body) != {"id", "kind", "origin"}:
        raise DomainContractError("Expected exact stored actor")
    return Actor(**body)


def _ref_key(ref):
    return ref.kind, ref.id, ref.version, ref.sha256


def _projection_bytes(projection):
    return canonical_json({
        "schema_version": "compiler-projection-v1",
        "source_ref": projection.source_ref.as_dict(),
        "target": projection.target,
        "change_kind": projection.change_kind,
        "values": {name: value for name, value in projection.values},
        "support_by_field": {
            name: [ref.as_dict() for ref in refs]
            for name, refs in projection.support_by_field
        },
        "expires_at": projection.expires_at,
        "digest": projection.digest,
    })


def _projection_from_bytes(value):
    body = parse_canonical(value)
    expected = {"schema_version", "source_ref", "target", "change_kind", "values",
                "support_by_field", "expires_at", "digest"}
    if type(body) is not dict or set(body) != expected \
            or body["schema_version"] != "compiler-projection-v1":
        raise DomainContractError("Invalid stored compiler projection")
    source_ref = EntityRef.from_dict(body["source_ref"])
    target = body["target"]
    change_kind = body["change_kind"]
    expires_at = body["expires_at"]
    values_body = body["values"]
    supports_body = body["support_by_field"]
    if (type(target) is not str or target not in _COMPILER_TARGETS
            or target in _PROTECTED_TARGETS or type(change_kind) is not str
            or change_kind not in _CHANGE_KINDS or type(expires_at) is not int
            or not 0 < expires_at <= MAX_INTEGER or type(values_body) is not dict
            or set(values_body) != set(_COMPILER_FIELDS)
            or type(supports_body) is not dict
            or set(supports_body) != set(_COMPILER_FIELDS)):
        raise DomainContractError("Invalid stored compiler projection")
    values = []
    support = []
    for field in _COMPILER_FIELDS:
        text = values_body[field]
        refs_body = supports_body[field]
        if (type(text) is not str or not text or len(text.encode("utf-8")) > 65_536
                or type(refs_body) is not list or not refs_body or len(refs_body) > 64):
            raise DomainContractError("Invalid stored compiler projection")
        refs = tuple(EntityRef.from_dict(item) for item in refs_body)
        if (len(refs) != len(set(refs))
                or any(ref == source_ref or ref.kind not in _BEHAVIOR_SUPPORT_KINDS
                       for ref in refs)):
            raise DomainContractError("Invalid stored compiler projection")
        values.append((field, text))
        support.append((field, refs))
    preimage = canonical_json({
        "schema_version": "compiler-projection-v1",
        "source_ref": source_ref.as_dict(),
        "target": target,
        "change_kind": change_kind,
        "values": dict(values),
        "support_by_field": {
            name: [ref.as_dict() for ref in refs] for name, refs in support
        },
        "expires_at": expires_at,
    })
    digest = sha256(preimage).hexdigest()
    if type(body["digest"]) is not str or body["digest"] != digest:
        raise DomainContractError("Stored compiler projection digest mismatch")
    return CompilerProjection(source_ref, target, change_kind, tuple(values), tuple(support),
                              expires_at, digest)


def _rebuild_projection(value):
    """Return the one canonical projection represented by an in-memory value."""
    if type(value) is not CompilerProjection:
        raise DomainContractError("Expected exact compiler projection")
    try:
        rebuilt = _projection_from_bytes(_projection_bytes(value))
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise DomainContractError("Invalid compiler projection") from exc
    if rebuilt != value:
        raise DomainContractError("Compiler projection is not canonical")
    return rebuilt


_PERMISSION_MIGRATIONS_DDL = (
    "CREATE TABLE permission_migrations(component TEXT NOT NULL, version INTEGER NOT NULL "
    "CHECK(typeof(version)='integer' AND version>0), sha256 TEXT NOT NULL, "
    "PRIMARY KEY(component,version))"
)
_PERMISSION_DDL = (
    "CREATE TABLE permission_control(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "vault_id TEXT NOT NULL UNIQUE, policy_revision INTEGER NOT NULL "
    "CHECK(typeof(policy_revision)='integer' AND policy_revision>0), "
    "last_observed INTEGER NOT NULL CHECK(typeof(last_observed)='integer' AND last_observed>=0), "
    "row_digest TEXT NOT NULL)",
    "CREATE TABLE permission_descriptors(vault_id TEXT NOT NULL, kind TEXT NOT NULL, "
    "id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, purpose TEXT NOT NULL, "
    "episode_id TEXT, dependencies BLOB NOT NULL, declared_secret INTEGER NOT NULL "
    "CHECK(declared_secret IN (0,1)), tainted INTEGER NOT NULL CHECK(tainted IN (0,1)), "
    "available INTEGER NOT NULL CHECK(available IN (0,1)), revision INTEGER NOT NULL "
    "CHECK(typeof(revision)='integer' AND revision>0), row_digest TEXT NOT NULL, "
    "PRIMARY KEY(vault_id,kind,id,version,sha256))",
    "CREATE TABLE permission_grants(vault_id TEXT NOT NULL, id TEXT NOT NULL, "
    "issuer_actor BLOB NOT NULL, subject_actor BLOB NOT NULL, subject_kind TEXT NOT NULL, "
    "subject_purpose TEXT, ref_kind TEXT NOT NULL, ref_id TEXT NOT NULL, ref_version INTEGER NOT NULL, "
    "ref_sha256 TEXT NOT NULL, action TEXT NOT NULL, purpose TEXT NOT NULL, episode_id TEXT, "
    "expires_at INTEGER NOT NULL, policy_revision INTEGER NOT NULL, state TEXT NOT NULL "
    "CHECK(state IN ('active','revoked')), row_digest TEXT NOT NULL, PRIMARY KEY(vault_id,id))",
    "CREATE INDEX permission_grants_target ON permission_grants(vault_id,subject_kind,"
    "ref_kind,ref_id,ref_version,ref_sha256,state)",
    "CREATE TABLE permission_projections(vault_id TEXT NOT NULL, source_kind TEXT NOT NULL, "
    "source_id TEXT NOT NULL, source_version INTEGER NOT NULL, source_sha256 TEXT NOT NULL, "
    "payload BLOB NOT NULL, projection_digest TEXT NOT NULL, expires_at INTEGER NOT NULL, "
    "state TEXT NOT NULL CHECK(state IN ('active','withdrawn')), registered_revision INTEGER NOT NULL, "
    "row_digest TEXT NOT NULL, PRIMARY KEY(vault_id,source_kind,source_id,source_version,source_sha256))",
)
PERMISSION_MIGRATION_SHA256 = sha256("\n".join(_PERMISSION_DDL).encode("utf-8")).hexdigest()
_POLICY_OBJECTS = frozenset({
    "permission_control", "permission_descriptors", "permission_grants",
    "permission_grants_target", "permission_projections",
})


def _normalize_schema_sql(value):
    if type(value) is not str:
        return ""
    return re.sub(r"\s*([(),=<>])\s*", r"\1", " ".join(value.split()).casefold())


_EXPECTED_MIGRATION_SQL = _normalize_schema_sql(_PERMISSION_MIGRATIONS_DDL)
_EXPECTED_POLICY_SQL = {}
for _statement in _PERMISSION_DDL:
    _match = re.match(r"CREATE (?:TABLE|INDEX) ([a-z_]+)", _statement)
    if _match is None:  # pragma: no cover - module constant invariant
        raise RuntimeError("Invalid permission migration statement")
    _EXPECTED_POLICY_SQL[_match.group(1)] = _normalize_schema_sql(_statement)


def _row_digest(value):
    return sha256(canonical_json(value)).hexdigest()


def _control_semantics(vault_id, policy_revision, last_observed):
    return {
        "vault_id": vault_id,
        "policy_revision": policy_revision,
        "last_observed": last_observed,
    }


def _descriptor_semantics(descriptor, vault_id):
    return {
        "vault_id": vault_id,
        "ref": descriptor.ref.as_dict(),
        "purpose": descriptor.purpose,
        "episode_id": descriptor.episode_id,
        "dependencies": [ref.as_dict() for ref in sorted(descriptor.dependencies, key=_ref_key)],
        "declared_secret": descriptor.declared_secret,
        "tainted": descriptor.tainted,
        "available": descriptor.available,
        "revision": descriptor.revision,
        "record_sha256": sha256(descriptor.record.body_bytes).hexdigest(),
    }


class _PermissionStore:
    """Hashed component using the canonical DomainStore connection and writer."""

    def __init__(self, domain_store, *, _db=None):
        if type(domain_store) is not DomainStore:
            raise TypeError("Persistent policy requires the exact initialized DomainStore")
        if _db is not None:
            domain_store._assert_write_transaction(_db)
        roots = domain_store.roots() if _db is None else domain_store._read_roots(_db)
        self.domain_store = domain_store
        self.path = domain_store.path
        self.vault_id = roots.genesis.id
        if _db is None:
            with self.transaction(write=True) as db:
                self._install(db, allow_create=True)
        else:
            self._install(_db)

    @contextmanager
    def transaction(self, *, write=False):
        if write:
            with _writer(), self.domain_store._connection(write=True) as db:
                yield db
            return
        with self.domain_store._connection() as db:
            yield db

    @staticmethod
    def _migration_shape(db):
        return [(row["name"], row["type"].upper(), row["notnull"], row["pk"])
                for row in db.execute("PRAGMA table_info(permission_migrations)")]

    @classmethod
    def _install(cls, db, *, allow_create=False):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='permission_migrations'").fetchone() is not None
        if not exists:
            if not allow_create:
                raise CorruptPolicy("Permission migration ledger is missing")
            db.execute(_PERMISSION_MIGRATIONS_DDL)
        expected_shape = [("component", "TEXT", 1, 1), ("version", "INTEGER", 1, 2),
                          ("sha256", "TEXT", 1, 0)]
        if cls._migration_shape(db) != expected_shape:
            raise CorruptPolicy("Permission migration ledger has an incompatible shape")
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                         "AND name='permission_migrations'").fetchone()
        if row is None or _normalize_schema_sql(row["sql"]) != _EXPECTED_MIGRATION_SQL:
            raise CorruptPolicy("Permission migration constraints are incompatible")
        objects = {row["name"]: _normalize_schema_sql(row["sql"])
                   for row in db.execute("SELECT name,sql FROM sqlite_master WHERE "
                                         "name IN (?,?,?,?,?)", tuple(sorted(_POLICY_OBJECTS)))}
        reserved = {(row["type"], row["name"]) for row in db.execute(
            "SELECT type,name FROM sqlite_master WHERE lower(name) GLOB 'permission_*'")}
        allowed_reserved = {("table", "permission_migrations")}
        allowed_reserved.update(
            ("index" if name == "permission_grants_target" else "table", name)
            for name in _POLICY_OBJECTS)
        if reserved - allowed_reserved:
            raise CorruptPolicy("Unexpected reserved permission schema object")
        governed = ("permission_migrations", "permission_control", "permission_descriptors",
                    "permission_grants", "permission_projections")
        unexpected = []
        for item in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN ('index','trigger') "
                "AND tbl_name IN (?,?,?,?,?)", governed):
            automatic = item["type"] == "index" and item["sql"] is None \
                and item["name"].startswith("sqlite_autoindex_")
            expected = item["type"] == "index" and item["name"] in _POLICY_OBJECTS
            if not automatic and not expected:
                unexpected.append((item["type"], item["name"], item["tbl_name"]))
        # This database is intentionally shared. A trigger attached to a legacy or
        # another component's table can still mutate permission state, so attachment
        # alone is not a sufficient boundary. There are no legitimate permission
        # triggers in policy@1.
        permission_target = re.compile(r"\bpermission_[a-z0-9_]+\b", re.IGNORECASE)
        for item in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type='trigger'"):
            if type(item["sql"]) is str and permission_target.search(item["sql"]):
                marker = (item["type"], item["name"], item["tbl_name"])
                if marker not in unexpected:
                    unexpected.append(marker)
        if unexpected:
            raise CorruptPolicy("Unexpected permission schema object")
        rows = list(db.execute("SELECT version,sha256 FROM permission_migrations "
                               "WHERE component='policy' ORDER BY version"))
        if rows:
            if ([(item["version"], item["sha256"]) for item in rows]
                    != [(1, PERMISSION_MIGRATION_SHA256)]
                    or set(objects) != _POLICY_OBJECTS or objects != _EXPECTED_POLICY_SQL):
                raise CorruptPolicy("Permission migration digest or schema is inconsistent")
            return
        if objects:
            raise CorruptPolicy("Unversioned or partial permission schema exists")
        if not allow_create:
            raise CorruptPolicy("Permission migration row is missing")
        for statement in _PERMISSION_DDL:
            db.execute(statement)
        db.execute("INSERT INTO permission_migrations VALUES ('policy',1,?)",
                   (PERMISSION_MIGRATION_SHA256,))

    def initialize(self, now):
        if type(now) is not int or not 0 <= now <= MAX_INTEGER:
            raise AccessDenied("Invalid trusted clock")
        with self.transaction(write=True) as db:
            self._install(db)
            self._verify_domain_binding(db)
            row = db.execute("SELECT vault_id,policy_revision,last_observed,row_digest "
                             "FROM permission_control WHERE singleton=1").fetchone()
            if row is None:
                digest = _row_digest(_control_semantics(self.vault_id, 1, now))
                db.execute("INSERT INTO permission_control VALUES (1,?,1,?,?)",
                           (self.vault_id, now, digest))
                return 1
            revision, last_observed = self.control(db)
            if now < last_observed:
                raise AccessDenied("Trusted clock moved backwards")
            self.observe_clock(db, now)
            return revision

    def _verify_domain_binding(self, db):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='domain_vault'").fetchone() is not None
        if not exists:
            raise CorruptPolicy("Canonical domain vault is missing")
        rows = list(db.execute("SELECT vault_id FROM domain_vault LIMIT 2"))
        if len(rows) != 1 or rows[0]["vault_id"] != self.vault_id:
            raise CorruptPolicy("Permission registry does not match the canonical domain vault")

    def control(self, db):
        row = db.execute("SELECT vault_id,policy_revision,last_observed,row_digest "
                         "FROM permission_control WHERE singleton=1").fetchone()
        if row is None or row["vault_id"] != self.vault_id \
                or type(row["policy_revision"]) is not int or row["policy_revision"] < 1 \
                or type(row["last_observed"]) is not int or row["last_observed"] < 0 \
                or type(row["row_digest"]) is not str \
                or row["row_digest"] != _row_digest(_control_semantics(
                    self.vault_id, row["policy_revision"], row["last_observed"])):
            raise CorruptPolicy("Permission control is missing or corrupt")
        return row["policy_revision"], row["last_observed"]

    def observe_clock(self, db, now):
        if type(now) is not int or not 0 <= now <= MAX_INTEGER:
            raise AccessDenied("Invalid trusted clock")
        revision, previous = self.control(db)
        if now < previous:
            raise AccessDenied("Trusted clock moved backwards")
        if now == previous:
            return now
        digest = _row_digest(_control_semantics(self.vault_id, revision, now))
        changed = db.execute(
            "UPDATE permission_control SET last_observed=?,row_digest=? "
            "WHERE singleton=1 AND vault_id=? AND policy_revision=? "
            "AND last_observed=?",
            (now, digest, self.vault_id, revision, previous),
        ).rowcount
        if changed != 1:
            raise CorruptPolicy("Concurrent permission clock conflict")
        return now

    def advance_revision(self, db, current):
        if current >= MAX_INTEGER:
            raise CorruptPolicy("Permission revision limit reached")
        revision, last_observed = self.control(db)
        if revision != current:
            raise CorruptPolicy("Permission revision cannot decrease or skip")
        digest = _row_digest(_control_semantics(
            self.vault_id, current + 1, last_observed))
        changed = db.execute(
            "UPDATE permission_control SET policy_revision=?,row_digest=? "
            "WHERE singleton=1 AND vault_id=? AND policy_revision=? AND last_observed=?",
            (current + 1, digest, self.vault_id, current, last_observed),
        ).rowcount
        if changed != 1:
            raise CorruptPolicy("Concurrent permission revision conflict")
        return current + 1

    def _descriptor_from_row(self, row, resolve_registered):
        try:
            ref = EntityRef(row["kind"], row["id"], row["version"], row["sha256"])
            if row["vault_id"] != self.vault_id or type(row["dependencies"]) is not bytes:
                raise DomainContractError("Invalid descriptor storage types")
            dependencies_body = parse_canonical(row["dependencies"])
            if type(dependencies_body) is not list or len(dependencies_body) > 4096:
                raise DomainContractError("Invalid stored dependency set")
            dependencies = frozenset(EntityRef.from_dict(value) for value in dependencies_body)
            if len(dependencies) != len(dependencies_body):
                raise DomainContractError("Duplicate stored dependencies")
            record = resolve_registered(ref)
            if type(record) is not ImmutableRecord or record.ref != ref:
                raise DomainContractError("Registered resolver returned the wrong record")
            record = ImmutableRecord.from_bytes(record.body_bytes, expected_ref=ref)
            episode_id = _episode(row["episode_id"])
            if (type(row["purpose"]) is not str or row["purpose"] not in PURPOSES
                    or record.body["purpose"] != row["purpose"]
                    or row["declared_secret"] not in (0, 1)
                    or row["tainted"] not in (0, 1) or row["available"] not in (0, 1)
                    or type(row["revision"]) is not int or row["revision"] < 1):
                raise DomainContractError("Invalid stored resource descriptor")
            if ((ref.kind == "inquiry_audit" or row["purpose"] == "inquiry_audit")
                    and episode_id is None):
                raise DomainContractError("Stored inquiry descriptor lacks episode")
            descriptor = ResourceDescriptor(
                ref, row["purpose"], episode_id, dependencies, bool(row["tainted"]),
                bool(row["available"]), row["revision"], record,
                bool(row["declared_secret"]),
            )
            if (dependencies != _content_dependencies(record)
                    or type(row["row_digest"]) is not str
                    or row["row_digest"] != _row_digest(
                        _descriptor_semantics(descriptor, self.vault_id))):
                raise DomainContractError("Stored descriptor digest mismatch")
            return descriptor
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise CorruptPolicy("Persistent resource descriptor is corrupt") from exc

    def _projection_from_row(self, row):
        try:
            source_ref = EntityRef(row["source_kind"], row["source_id"],
                                   row["source_version"], row["source_sha256"])
            if row["vault_id"] != self.vault_id or type(row["payload"]) is not bytes:
                raise DomainContractError("Invalid projection storage types")
            projection = _projection_from_bytes(row["payload"])
            semantics = {
                "vault_id": self.vault_id,
                "source_ref": source_ref.as_dict(),
                "payload_sha256": sha256(row["payload"]).hexdigest(),
                "projection_digest": projection.digest,
                "expires_at": projection.expires_at,
                "state": row["state"],
                "registered_revision": row["registered_revision"],
            }
            if (projection.source_ref != source_ref
                    or row["projection_digest"] != projection.digest
                    or row["expires_at"] != projection.expires_at
                    or row["state"] not in ("active", "withdrawn")
                    or type(row["registered_revision"]) is not int
                    or row["registered_revision"] < 1
                    or row["row_digest"] != _row_digest(semantics)):
                raise DomainContractError("Stored projection row mismatch")
            return projection, row["state"], row["registered_revision"]
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise CorruptPolicy("Persistent compiler projection is corrupt") from exc

    def load(self, db, resolve_registered):
        self._verify_domain_binding(db)
        revision = self.control(db)[0]
        for table in ("permission_descriptors", "permission_grants", "permission_projections"):
            if db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > _MAX_POLICY_ROWS:
                raise CorruptPolicy("Persistent permission registry row bound exceeded")
            if db.execute(f"SELECT 1 FROM {table} WHERE vault_id<>? LIMIT 1",
                          (self.vault_id,)).fetchone() is not None:
                raise CorruptPolicy("Foreign vault state exists in permission registry")
        if db.execute(
                "SELECT 1 FROM permission_descriptors WHERE typeof(dependencies)<>'blob' "
                "OR length(dependencies)>? OR length(row_digest)<>64 LIMIT 1",
                (MAX_JSON_BYTES,)).fetchone() is not None:
            raise CorruptPolicy("Persistent descriptor storage bounds are invalid")
        if db.execute(
                "SELECT 1 FROM permission_grants WHERE typeof(issuer_actor)<>'blob' "
                "OR typeof(subject_actor)<>'blob' OR length(issuer_actor)>? "
                "OR length(subject_actor)>? OR length(row_digest)<>64 LIMIT 1",
                (MAX_JSON_BYTES, MAX_JSON_BYTES)).fetchone() is not None:
            raise CorruptPolicy("Persistent grant storage bounds are invalid")
        if db.execute(
                "SELECT 1 FROM permission_projections WHERE typeof(payload)<>'blob' "
                "OR length(payload)>? OR length(projection_digest)<>64 "
                "OR length(row_digest)<>64 LIMIT 1",
                (MAX_JSON_BYTES,)).fetchone() is not None:
            raise CorruptPolicy("Persistent projection storage bounds are invalid")
        resources = {}
        for row in db.execute("SELECT * FROM permission_descriptors WHERE vault_id=?",
                              (self.vault_id,)):
            descriptor = self._descriptor_from_row(row, resolve_registered)
            if descriptor.ref in resources:
                raise CorruptPolicy("Duplicate persistent resource descriptor")
            resources[descriptor.ref] = descriptor

        checked = set()
        for root in resources:
            if root in checked:
                continue
            visiting = set()
            stack = [(root, False, 0)]
            while stack:
                ref, leaving, depth = stack.pop()
                if leaving:
                    descriptor = resources[ref]
                    inherited = any(resources[child].tainted
                                    for child in descriptor.dependencies)
                    expected = (descriptor.declared_secret
                                or descriptor.ref.kind in _SENSITIVE_KINDS
                                or descriptor.purpose == "evaluation_sealed"
                                or _contains_sensitive_claim(descriptor.record.body["content"])
                                or inherited)
                    visiting.remove(ref)
                    checked.add(ref)
                    if descriptor.tainted is not expected:
                        raise CorruptPolicy("Persistent descriptor taint is inconsistent")
                    continue
                if ref in checked:
                    continue
                if (depth > 4096 or ref in visiting or ref not in resources
                        or len(checked) + len(visiting) >= 4096):
                    raise CorruptPolicy("Persistent descriptor dependency graph is invalid")
                visiting.add(ref)
                stack.append((ref, True, depth))
                stack.extend((child, False, depth + 1)
                             for child in resources[ref].dependencies)

        projections = {}
        projection_states = {}
        for row in db.execute("SELECT * FROM permission_projections WHERE vault_id=?",
                              (self.vault_id,)):
            projection, state, registered_revision = self._projection_from_row(row)
            if projection.source_ref in projections or registered_revision > revision:
                raise CorruptPolicy("Persistent projection revision is inconsistent")
            required = {projection.source_ref}
            for _, refs in projection.support_by_field:
                required.update(refs)
            if any(ref not in resources for ref in required):
                raise CorruptPolicy("Persistent projection has missing evidence")
            source = resources[projection.source_ref].record.body["content"]
            if any(source.get(name) != value for name, value in projection.values):
                raise CorruptPolicy("Persistent projection no longer matches its source")
            projections[projection.source_ref] = projection
            projection_states[projection.source_ref] = state

        for row in db.execute("SELECT id FROM permission_grants WHERE vault_id=?",
                              (self.vault_id,)):
            try:
                stored, _, _, ref, episode_id = self.grant_row(db, row["id"])
            except (AccessDenied, DomainContractError) as exc:
                raise CorruptPolicy("Persistent grant identity is corrupt") from exc
            descriptor = resources.get(ref)
            if (descriptor is None or stored["policy_revision"] > revision
                    or stored["episode_id"] != episode_id
                    or descriptor.episode_id != episode_id
                    or (stored["purpose"] != "compiler"
                        and descriptor.purpose != stored["purpose"])
                    or (stored["subject_kind"] == "runtime"
                        and stored["subject_purpose"] != stored["purpose"])):
                raise CorruptPolicy("Persistent grant scope is inconsistent")
        return revision, resources, projections, projection_states

    def insert_descriptor(self, db, descriptor):
        dependencies = canonical_json(
            [ref.as_dict() for ref in sorted(descriptor.dependencies, key=_ref_key)])
        values = (*_ref_key(descriptor.ref), descriptor.purpose, descriptor.episode_id,
                  dependencies, int(descriptor.declared_secret), int(descriptor.tainted),
                  int(descriptor.available), descriptor.revision,
                  _row_digest(_descriptor_semantics(descriptor, self.vault_id)))
        try:
            db.execute("INSERT INTO permission_descriptors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (self.vault_id, *values))
        except sqlite3.IntegrityError:
            rows = list(db.execute(
                "SELECT * FROM permission_descriptors WHERE vault_id=? AND kind=? AND id=? "
                "AND version=? AND sha256=?", (self.vault_id, *_ref_key(descriptor.ref))))
            if (len(rows) != 1 or rows[0]["row_digest"] != _row_digest(
                    _descriptor_semantics(descriptor, self.vault_id))):
                raise AccessDenied("Resource descriptor conflict")

    def replace_descriptor(self, db, descriptor, prior_revision):
        digest = _row_digest(_descriptor_semantics(descriptor, self.vault_id))
        changed = db.execute(
            "UPDATE permission_descriptors SET available=?,revision=?,row_digest=? "
            "WHERE vault_id=? AND kind=? AND id=? AND version=? AND sha256=? AND revision=?",
            (int(descriptor.available), descriptor.revision, digest, self.vault_id,
             *_ref_key(descriptor.ref), prior_revision),
        ).rowcount
        if changed != 1:
            raise AccessDenied("Concurrent resource descriptor change")

    @staticmethod
    def _grant_semantics(vault_id, grant_id, issuer_actor, subject_actor, subject_kind,
                         subject_purpose, ref, action, purpose, episode_id, expires_at,
                         policy_revision, state):
        return {
            "vault_id": vault_id, "id": grant_id,
            "issuer_actor": _actor_dict(issuer_actor),
            "subject_actor": _actor_dict(subject_actor), "subject_kind": subject_kind,
            "subject_purpose": subject_purpose, "ref": ref.as_dict(), "action": action,
            "purpose": purpose, "episode_id": episode_id, "expires_at": expires_at,
            "policy_revision": policy_revision, "state": state,
        }

    def insert_grant(self, db, grant_id, issuer, subject, ref, action, purpose,
                     episode_id, expires_at, policy_revision):
        issuer_bytes = canonical_json(_actor_dict(issuer.actor))
        subject_bytes = canonical_json(_actor_dict(subject.actor))
        semantics = self._grant_semantics(
            self.vault_id, grant_id, issuer.actor, subject.actor, subject.kind,
            subject.purpose, ref, action, purpose, episode_id, expires_at, policy_revision,
            "active",
        )
        try:
            db.execute("INSERT INTO permission_grants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (self.vault_id, grant_id, issuer_bytes, subject_bytes, subject.kind,
                        subject.purpose, *_ref_key(ref), action, purpose, episode_id, expires_at,
                        policy_revision, "active", _row_digest(semantics)))
        except sqlite3.IntegrityError as exc:
            raise AccessDenied("Grant identity conflict") from exc

    def grant_row(self, db, grant_id):
        try:
            uuid_string(grant_id)
        except DomainContractError as exc:
            raise AccessDenied("Invalid grant identity") from exc
        rows = list(db.execute("SELECT * FROM permission_grants WHERE vault_id=? AND id=?",
                               (self.vault_id, grant_id)))
        if len(rows) != 1:
            raise AccessDenied("Unknown grant")
        row = rows[0]
        try:
            issuer_actor = _actor_from_bytes(row["issuer_actor"])
            subject_actor = _actor_from_bytes(row["subject_actor"])
            ref = EntityRef(row["ref_kind"], row["ref_id"], row["ref_version"],
                            row["ref_sha256"])
            episode_id = _episode(row["episode_id"])
            semantics = self._grant_semantics(
                self.vault_id, row["id"], issuer_actor, subject_actor, row["subject_kind"],
                row["subject_purpose"], ref, row["action"], row["purpose"], episode_id,
                row["expires_at"], row["policy_revision"], row["state"],
            )
            if (row["vault_id"] != self.vault_id or issuer_actor.kind != "human"
                    or issuer_actor.origin != "local_session"
                    or row["subject_kind"] not in ("human", "runtime")
                    or ((row["subject_kind"] == "human")
                        != (subject_actor.kind == "human"))
                    or (row["subject_kind"] == "human" and row["subject_purpose"] is not None)
                    or (row["subject_kind"] == "runtime"
                        and row["subject_purpose"] not in _RUNTIME_PURPOSES)
                    or row["action"] not in _ACTIONS or row["purpose"] not in _RUNTIME_PURPOSES
                    or ((row["purpose"] == "compiler")
                        != (row["action"] == "compile"))
                    or type(row["expires_at"]) is not int or row["expires_at"] < 1
                    or type(row["policy_revision"]) is not int or row["policy_revision"] < 1
                    or row["state"] not in ("active", "revoked")
                    or row["row_digest"] != _row_digest(semantics)):
                raise DomainContractError("Invalid stored grant")
            return row, issuer_actor, subject_actor, ref, episode_id
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise CorruptPolicy("Persistent grant is corrupt") from exc

    def revoke_grant(self, db, grant_id):
        row, issuer_actor, subject_actor, ref, episode_id = self.grant_row(db, grant_id)
        if row["state"] != "active":
            raise AccessDenied("Grant already revoked")
        semantics = self._grant_semantics(
            self.vault_id, grant_id, issuer_actor, subject_actor, row["subject_kind"],
            row["subject_purpose"], ref, row["action"], row["purpose"], episode_id,
            row["expires_at"], row["policy_revision"], "revoked",
        )
        changed = db.execute("UPDATE permission_grants SET state='revoked',row_digest=? "
                             "WHERE vault_id=? AND id=? AND state='active'",
                             (_row_digest(semantics), self.vault_id, grant_id)).rowcount
        if changed != 1:
            raise AccessDenied("Concurrent grant revocation")

    def insert_projection(self, db, projection, registered_revision):
        payload = _projection_bytes(projection)
        semantics = {
            "vault_id": self.vault_id, "source_ref": projection.source_ref.as_dict(),
            "payload_sha256": sha256(payload).hexdigest(),
            "projection_digest": projection.digest, "expires_at": projection.expires_at,
            "state": "active", "registered_revision": registered_revision,
        }
        try:
            db.execute("INSERT INTO permission_projections VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (self.vault_id, *_ref_key(projection.source_ref), payload,
                        projection.digest, projection.expires_at, "active", registered_revision,
                        _row_digest(semantics)))
        except sqlite3.IntegrityError:
            rows = list(db.execute(
                "SELECT * FROM permission_projections WHERE vault_id=? AND source_kind=? "
                "AND source_id=? AND source_version=? AND source_sha256=?",
                (self.vault_id, *_ref_key(projection.source_ref))))
            if len(rows) != 1 or self._projection_from_row(rows[0])[:2] != (projection, "active"):
                raise AccessDenied("Compiler projection conflict")

    def withdraw_projection(self, db, source_ref):
        rows = list(db.execute(
            "SELECT * FROM permission_projections WHERE vault_id=? AND source_kind=? "
            "AND source_id=? AND source_version=? AND source_sha256=?",
            (self.vault_id, *_ref_key(source_ref))))
        if len(rows) != 1:
            raise AccessDenied("Unknown compiler projection")
        projection, state, registered_revision = self._projection_from_row(rows[0])
        if state != "active":
            raise AccessDenied("Compiler projection already withdrawn")
        payload = rows[0]["payload"]
        semantics = {
            "vault_id": self.vault_id, "source_ref": source_ref.as_dict(),
            "payload_sha256": sha256(payload).hexdigest(),
            "projection_digest": projection.digest, "expires_at": projection.expires_at,
            "state": "withdrawn", "registered_revision": registered_revision,
        }
        changed = db.execute("UPDATE permission_projections SET state='withdrawn',row_digest=? "
                             "WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=? "
                             "AND source_sha256=? AND state='active'",
                             (_row_digest(semantics), self.vault_id, *_ref_key(source_ref))).rowcount
        if changed != 1:
            raise AccessDenied("Concurrent compiler projection withdrawal")




class HostPolicy:
    """Trusted-host mutation surface. Never expose this object to page/model code."""

    def __init__(self, vault_id, *, authenticate_session, verify_registered,
                 verify_projection, clock, _domain_store=None):
        self.vault_id = uuid_string(vault_id)
        if not all(callable(item) for item in
                   (authenticate_session, verify_projection, clock)):
            raise TypeError("Policy integrations must be callable")
        if _domain_store is None and not callable(verify_registered):
            raise TypeError("Process-local policy requires a record verifier")
        if _domain_store is not None:
            if type(_domain_store) is not DomainStore:
                raise TypeError("Persistent policy requires the exact initialized DomainStore")
            roots = _domain_store.roots()
            if roots.genesis.id != self.vault_id:
                raise CorruptPolicy("Persistent policy vault does not match DomainStore")

            def verify_domain_record(value):
                try:
                    ref = value.ref if type(value) is ImmutableRecord else value
                    registered = _domain_store.get(ref)
                    return registered == value if type(value) is ImmutableRecord \
                        else registered.ref == value
                except Exception:
                    return False

            verify_registered = verify_domain_record
        self._authenticate_session = authenticate_session
        self._verify_registered = verify_registered
        self._verify_projection = verify_projection
        self._resolve_registered = None if _domain_store is None else _domain_store.get
        self._clock = clock
        self._clock_lock = RLock()
        self._last_now = None
        self._principals = {}
        self._grants = {}
        self._resources = {}
        self._projections = {}
        self._projection_states = {}
        self._policy_revision = 1
        self._storage = None if _domain_store is None else _PermissionStore(_domain_store)
        if self._storage is not None:
            self._storage.initialize(self._now())
            self._sync_persistent()

    def _sync_persistent(self, db=None):
        if self._storage is None:
            return
        if db is None:
            with self._storage.transaction(write=True) as connection:
                self._storage._install(connection)
                self._storage.observe_clock(connection, self._now())
                revision, resources, projections, states = self._storage.load(
                    connection,
                    lambda ref: self._resolve_registered_in_transaction(connection, ref),
                )
        else:
            self._storage._install(db)
            self._storage.observe_clock(db, self._now())
            revision, resources, projections, states = self._storage.load(
                db, lambda ref: self._resolve_registered_in_transaction(db, ref))
        if revision < self._policy_revision:
            raise CorruptPolicy("Permission revision moved backwards")
        self._policy_revision = revision
        self._resources = resources
        self._projection_states = states
        self._projections = {
            ref: projection for ref, projection in projections.items()
            if states[ref] == "active"
        }

    def _resolve_registered_in_transaction(self, db, ref):
        """Resolve one canonical record without opening a second SQLite connection."""
        if self._storage is None:
            raise AccessDenied("Persistent record registry is not configured")
        domain = self._storage.domain_store
        roots = domain._read_roots(db)
        if roots.genesis.id != self.vault_id:
            raise CorruptPolicy("Transaction vault does not match permission authority")
        domain._check_graph(db, [ref], roots)
        return domain._load(db, ref, roots)[0]

    def _verify_registered_record(self, value, db=None):
        if db is None:
            return self._verify_registered(value)
        ref = value.ref if type(value) is ImmutableRecord else value
        registered = self._resolve_registered_in_transaction(db, ref)
        return registered == value if type(value) is ImmutableRecord else registered.ref == value

    def _load_persistent_in_transaction(self, db):
        if self._storage is None:
            raise AccessDenied("Persistent permission registry is not configured")
        return self._storage.load(
            db, lambda ref: self._resolve_registered_in_transaction(db, ref))

    def _persist_clock_watermark(self):
        """Commit only the trusted-clock floor after an outer command rollback."""
        if self._storage is None:
            raise AccessDenied("Persistent permission registry is not configured")
        now = self._now()
        with self._storage.transaction(write=True) as db:
            self._persist_clock_watermark_in_transaction(db, now)
        return None

    def _persist_clock_watermark_in_transaction(self, db, observed):
        """Persist an already-observed floor in a caller-owned recovery transaction."""
        if self._storage is None:
            raise AccessDenied("Persistent permission registry is not configured")
        if (type(db) is not sqlite3.Connection or not db.in_transaction
                or db.row_factory is not sqlite3.Row
                or type(observed) is not int or not 0 <= observed <= MAX_INTEGER):
            raise AccessDenied("Exact recovery transaction and clock floor required")
        self._storage._install(db)
        self._storage._verify_domain_binding(db)
        _, previous = self._storage.control(db)
        if observed > previous:
            self._storage.observe_clock(db, observed)
        revision, _, _, _ = self._load_persistent_in_transaction(db)
        if revision < self._policy_revision:
            raise CorruptPolicy("Permission revision moved backwards")
        return None

    def _now(self):
        with self._clock_lock:
            value = self._clock()
            if type(value) is not int or not 0 <= value <= MAX_INTEGER:
                raise AccessDenied("Invalid trusted clock")
            if self._last_now is not None and value < self._last_now:
                raise AccessDenied("Trusted clock moved backwards")
            self._last_now = value
            return value

    def _observed_clock_floor(self):
        """Return the greatest trusted clock value observed in this process."""
        with self._clock_lock:
            if type(self._last_now) is not int:
                raise AccessDenied("Trusted permission clock has not been observed")
            return self._last_now

    def _principal(self, value, *, human=None, db=None):
        if type(value) is not Principal or self._principals.get(id(value)) is not value:
            raise AccessDenied("Unregistered principal")
        if value.expires_at <= self._now():
            raise AccessDenied("Principal expired")
        if human is not None and (value.kind == "human") is not human:
            raise AccessDenied("Wrong principal authority")
        if value.kind == "human":
            from .request_identity import authenticate_in_transaction
            actor = (self._authenticate_session(value._session) if db is None else
                     authenticate_in_transaction(self._authenticate_session, value._session, db))
            if type(actor) is not Actor or actor != value.actor or actor.kind != "human":
                raise AccessDenied("Human session is no longer authenticated")
        return value

    def bind_human(self, session, *, expires_at):
        self._sync_persistent()
        actor = self._authenticate_session(session)
        if type(actor) is not Actor or actor.kind != "human" or actor.origin != "local_session":
            raise AccessDenied("Authenticated local human session required")
        principal = Principal(str(uuid4()), actor, "human", None,
                              _expiry(expires_at, self._now()), session)
        self._sync_persistent()
        self._principals[id(principal)] = principal
        return principal

    def bind_runtime(self, actor, *, purpose, expires_at):
        self._sync_persistent()
        if (type(actor) is not Actor or actor.kind == "human"
                or type(purpose) is not str or purpose not in _RUNTIME_PURPOSES):
            raise AccessDenied("Trusted nonhuman runtime binding required")
        principal = Principal(str(uuid4()), actor, "runtime", purpose,
                              _expiry(expires_at, self._now()))
        self._sync_persistent()
        self._principals[id(principal)] = principal
        return principal

    def register_record(self, record, *, episode_id=None, secret=False):
        if self._storage is not None:
            with self._storage.transaction(write=True) as db:
                descriptor = self._register_record_in_transaction(
                    db, record, episode_id=episode_id, secret=secret)
            self._sync_persistent()
            return descriptor
        if (type(record) is not ImmutableRecord or record.body["schema_version"] != SCHEMA_VERSION
                or type(secret) is not bool):
            raise AccessDenied("Only verified ordinary records can be registered")
        try:
            verified = self._verify_registered(record)
        except Exception as exc:
            raise AccessDenied("Record verification failed") from exc
        if verified is not True:
            raise AccessDenied("Record is not registered in this vault")
        episode_id = _episode(episode_id)
        body = record.body
        def build():
            dependencies = _content_dependencies(record)
            missing = [ref for ref in dependencies if ref not in self._resources]
            if missing:
                raise AccessDenied("Dependency is not registered in this vault")
            if ((record.ref.kind == "inquiry_audit" or body["purpose"] == "inquiry_audit")
                    and episode_id is None):
                raise AccessDenied("Inquiry evidence requires an exact episode")
            inherited = any(self._resources[ref].tainted for ref in dependencies)
            tainted = (secret or record.ref.kind in _SENSITIVE_KINDS
                       or body["purpose"] == "evaluation_sealed"
                       or _contains_sensitive_claim(body["content"]) or inherited)
            return ResourceDescriptor(record.ref, body["purpose"], episode_id, dependencies,
                                      tainted, True, 1, record, secret)

        descriptor = build()
        prior = self._resources.get(record.ref)
        if prior is not None and prior != descriptor:
            raise AccessDenied("Resource descriptor conflict")
        self._resources[record.ref] = prior or descriptor
        return self._resources[record.ref]

    def _register_record_in_transaction(self, db, record, *, episode_id=None, secret=False):
        """Stage a descriptor without publishing uncommitted in-memory authority."""
        if self._storage is None:
            raise AccessDenied("Persistent permission registry is required")
        self._storage.domain_store._assert_write_transaction(db)
        self._storage._install(db)
        self._storage._verify_domain_binding(db)
        if (type(record) is not ImmutableRecord
                or record.body["schema_version"] != SCHEMA_VERSION or type(secret) is not bool):
            raise AccessDenied("Only verified ordinary records can be registered")
        try:
            verified = self._verify_registered_record(record, db)
        except (StorageError, DomainContractError, KeyError, TypeError):
            raise AccessDenied("Record is not registered in this vault") from None
        if verified is not True:
            raise AccessDenied("Record is not registered in this vault")
        episode_id = _episode(episode_id)
        revision, resources, _, _ = self._load_persistent_in_transaction(db)
        if revision < self._policy_revision:
            raise CorruptPolicy("Permission revision moved backwards")
        body = record.body
        dependencies = _content_dependencies(record)
        if any(ref not in resources for ref in dependencies):
            raise AccessDenied("Dependency is not registered in this vault")
        if ((record.ref.kind == "inquiry_audit" or body["purpose"] == "inquiry_audit")
                and episode_id is None):
            raise AccessDenied("Inquiry evidence requires an exact episode")
        tainted = (secret or record.ref.kind in _SENSITIVE_KINDS
                   or body["purpose"] == "evaluation_sealed"
                   or _contains_sensitive_claim(body["content"])
                   or any(resources[ref].tainted for ref in dependencies))
        descriptor = ResourceDescriptor(record.ref, body["purpose"], episode_id,
                                        dependencies, tainted, True, 1, record, secret)
        self._storage.insert_descriptor(db, descriptor)
        self._storage.observe_clock(db, self._now())
        _, committed, _, _ = self._load_persistent_in_transaction(db)
        if committed.get(record.ref) != descriptor:
            raise CorruptPolicy("Resource descriptor commit invariant failed")
        return descriptor

    def set_available(self, ref, available):
        if type(ref) is not EntityRef or type(available) is not bool:
            raise AccessDenied("Unknown resource descriptor")
        if self._storage is None:
            if ref not in self._resources:
                raise AccessDenied("Unknown resource descriptor")
            current = self._resources[ref]
            self._resources[ref] = ResourceDescriptor(
                current.ref, current.purpose, current.episode_id, current.dependencies,
                current.tainted, available, current.revision + 1, current.record,
                current.declared_secret)
            self._policy_revision += 1
            return
        with self._storage.transaction(write=True) as db:
            self._sync_persistent(db)
            current = self._resources.get(ref)
            if current is None:
                raise AccessDenied("Unknown resource descriptor")
            replacement = ResourceDescriptor(
                current.ref, current.purpose, current.episode_id, current.dependencies,
                current.tainted, available, current.revision + 1, current.record,
                current.declared_secret)
            self._storage.replace_descriptor(db, replacement, current.revision)
            new_revision = self._storage.advance_revision(db, self._policy_revision)
            self._storage.observe_clock(db, self._now())
            revision, resources, _, _ = self._load_persistent_in_transaction(db)
            if revision != new_revision or resources.get(ref) != replacement:
                raise CorruptPolicy("Resource availability commit invariant failed")
        self._sync_persistent()

    def _validated_projection(self, value):
        try:
            projection = _rebuild_projection(value)
        except (DomainContractError, TypeError, ValueError) as exc:
            raise AccessDenied("Invalid compiler projection") from exc
        descriptor = self._resources.get(projection.source_ref)
        if descriptor is None or descriptor.ref.kind != "hypothesis":
            raise AccessDenied("Compiler projection source is unavailable")
        content = descriptor.record.body["content"]
        expected_values = tuple((field, content.get(field)) for field in _COMPILER_FIELDS)
        if projection.values != expected_values:
            raise AccessDenied("Compiler projection no longer matches its source")
        return projection

    def register_projection(self, projection):
        self._sync_persistent()
        projection = self._validated_projection(projection)
        if projection.expires_at <= self._now():
            raise AccessDenied("Invalid compiler projection")
        try:
            verified = self._verify_projection(projection)
        except Exception as exc:
            raise AccessDenied("Projection verification failed") from exc
        if verified is not True:
            raise AccessDenied("Trusted semantic verification receipt required")
        def validate():
            self._validated_projection(projection)
            refs = {projection.source_ref}
            for _, values in projection.support_by_field:
                refs.update(values)
            for ref in refs:
                descriptor = self._resources.get(ref)
                if descriptor is None or not descriptor.available or descriptor.tainted:
                    raise AccessDenied("Projection depends on unavailable or sensitive evidence")
                try:
                    registered = self._verify_registered(descriptor.record)
                except Exception as exc:
                    raise AccessDenied("Projection evidence verification failed") from exc
                if registered is not True:
                    raise AccessDenied("Projection evidence registration was withdrawn")

        if self._storage is None:
            validate()
            self._projections[projection.source_ref] = projection
            self._policy_revision += 1
            return projection.digest
        with self._storage.transaction(write=True) as db:
            self._sync_persistent(db)
            projection = self._validated_projection(projection)
            if projection.expires_at <= self._now():
                raise AccessDenied("Compiler projection expired during registration")
            try:
                verified = self._verify_projection(projection)
            except Exception as exc:
                raise AccessDenied("Projection verification failed") from exc
            if verified is not True:
                raise AccessDenied("Projection verification was withdrawn")
            all_projections = {ref: item for ref, item in self._projections.items()}
            existing_state = self._projection_states.get(projection.source_ref)
            if existing_state is not None:
                existing = all_projections.get(projection.source_ref)
                if existing_state == "active" and existing == projection:
                    return projection.digest
                raise AccessDenied("Compiler projection conflict")
            validate()
            new_revision = self._storage.advance_revision(db, self._policy_revision)
            self._storage.insert_projection(db, projection, new_revision)
            validate()
            try:
                still_verified = self._verify_projection(projection)
            except Exception as exc:
                raise AccessDenied("Projection verification failed") from exc
            if projection.expires_at <= self._now() or still_verified is not True:
                raise AccessDenied("Projection authority changed before commit")
            self._storage.observe_clock(db, self._now())
            revision, _, projections, states = self._load_persistent_in_transaction(db)
            if (revision != new_revision or projections.get(projection.source_ref) != projection
                    or states.get(projection.source_ref) != "active"):
                raise CorruptPolicy("Compiler projection commit invariant failed")
        self._sync_persistent()
        return projection.digest

    def withdraw_projection(self, source_ref):
        if type(source_ref) is not EntityRef:
            raise AccessDenied("Exact projection source required")
        if self._storage is None:
            if source_ref not in self._projections:
                raise AccessDenied("Unknown compiler projection")
            del self._projections[source_ref]
            self._projection_states[source_ref] = "withdrawn"
            self._policy_revision += 1
            return
        with self._storage.transaction(write=True) as db:
            self._sync_persistent(db)
            self._storage.withdraw_projection(db, source_ref)
            new_revision = self._storage.advance_revision(db, self._policy_revision)
            self._storage.observe_clock(db, self._now())
            revision, _, _, states = self._load_persistent_in_transaction(db)
            if revision != new_revision or states.get(source_ref) != "withdrawn":
                raise CorruptPolicy("Projection withdrawal commit invariant failed")
        self._sync_persistent()

    def _compiler_member(self, ref):
        for projection in self._projections.values():
            if projection.expires_at <= self._now():
                continue
            members = {projection.source_ref}
            for _, refs in projection.support_by_field:
                members.update(refs)
            if ref in members:
                return True
        return False

    def grant(self, issuer, subject, ref, *, action, purpose, expires_at, episode_id=None):
        self._sync_persistent()
        issuer = self._principal(issuer, human=True)
        subject = self._principal(subject)
        if type(ref) is not EntityRef or type(action) is not str or action not in _ACTIONS:
            raise AccessDenied("Invalid grant target or action")
        if type(purpose) is not str or purpose not in _RUNTIME_PURPOSES:
            raise AccessDenied("Invalid grant purpose")
        if (purpose == "compiler") != (action == "compile"):
            raise AccessDenied("Compiler action and purpose must be bound together")
        episode_id = _episode(episode_id)
        expires_at = _expiry(expires_at, self._now())
        if expires_at > issuer.expires_at or expires_at > subject.expires_at:
            raise AccessDenied("Grant cannot outlive its principals")

        def validate():
            descriptor = self._resources.get(ref)
            if descriptor is None or not descriptor.available:
                raise AccessDenied("Resource is unavailable for this purpose")
            try:
                registered = self._verify_registered(descriptor.record)
            except Exception as exc:
                raise AccessDenied("Resource verification failed") from exc
            if registered is not True:
                raise AccessDenied("Resource registration was withdrawn")
            if subject.kind == "runtime":
                if subject.purpose != purpose:
                    raise AccessDenied("Runtime purpose cannot be widened")
                if descriptor.tainted:
                    raise AccessDenied(
                        "Sensitive evidence requires a dedicated human-scoped projection")
            elif purpose != descriptor.purpose:
                raise AccessDenied("Human grant purpose must match the resource")
            if purpose == "compiler":
                if action != "compile" or not self._compiler_member(ref):
                    raise AccessDenied("Only a verified projection may enter the compiler")
            elif descriptor.purpose != purpose:
                raise AccessDenied("Cross-purpose access denied")
            if descriptor.episode_id is not None:
                if episode_id != descriptor.episode_id:
                    raise AccessDenied("Exact episode scope required")
            elif episode_id is not None:
                raise AccessDenied("Unexpected episode scope")

        grant_id = str(uuid4())
        grant_revision = self._policy_revision
        if self._storage is not None:
            with self._storage.transaction(write=True) as db:
                self._sync_persistent(db)
                self._principal(issuer, human=True, db=db)
                self._principal(subject, db=db)
                validate()
                grant_revision = self._policy_revision
                self._storage.insert_grant(
                    db, grant_id, issuer, subject, ref, action, purpose, episode_id,
                    expires_at, grant_revision)
                self._principal(issuer, human=True, db=db)
                self._principal(subject, db=db)
                self._storage.observe_clock(db, self._now())
                revision, _, _, _ = self._load_persistent_in_transaction(db)
                row, _, _, stored_ref, stored_episode = self._storage.grant_row(db, grant_id)
                if (revision != grant_revision or stored_ref != ref
                        or stored_episode != episode_id or row["state"] != "active"):
                    raise CorruptPolicy("Grant commit invariant failed")
            self._sync_persistent()
        else:
            validate()
        grant = Grant(grant_id, issuer.id, subject.id, ref, action, purpose,
                      episode_id, expires_at, grant_revision)
        self._grants[id(grant)] = (grant, issuer, subject)
        return grant

    def claim_grant(self, grant_id, issuer, subject):
        """Rebind a persisted grant to newly authenticated live principals after restart."""
        if self._storage is None:
            raise AccessDenied("Persistent grant registry is not configured")
        self._sync_persistent()
        issuer = self._principal(issuer, human=True)
        subject = self._principal(subject)
        with self._storage.transaction(write=True) as db:
            self._sync_persistent(db)
            row, stored_issuer, stored_subject, ref, episode_id = \
                self._storage.grant_row(db, grant_id)
            if (row["state"] != "active" or row["policy_revision"] != self._policy_revision
                    or row["expires_at"] <= self._now()
                    or stored_issuer != issuer.actor or stored_subject != subject.actor
                    or row["subject_kind"] != subject.kind
                    or row["subject_purpose"] != subject.purpose
                    or row["expires_at"] > issuer.expires_at
                    or row["expires_at"] > subject.expires_at):
                raise AccessDenied("Persisted grant cannot be rebound")
            grant = Grant(row["id"], issuer.id, subject.id, ref, row["action"],
                          row["purpose"], episode_id, row["expires_at"],
                          row["policy_revision"])
            self._principal(issuer, human=True, db=db)
            self._principal(subject, db=db)
            self._storage.observe_clock(db, self._now())
            self._load_persistent_in_transaction(db)
        self._grants[id(grant)] = (grant, issuer, subject)
        return grant

    def revoke(self, grant):
        self._sync_persistent()
        if type(grant) is not Grant or self._grants.get(id(grant), (None,))[0] is not grant:
            raise AccessDenied("Unknown grant")
        if self._storage is not None:
            with self._storage.transaction(write=True) as db:
                self._sync_persistent(db)
                self._principal(self._grants[id(grant)][1], human=True, db=db)
                self._storage.revoke_grant(db, grant.id)
                new_revision = self._storage.advance_revision(db, self._policy_revision)
                self._storage.observe_clock(db, self._now())
                revision, _, _, _ = self._load_persistent_in_transaction(db)
                row, _, _, _, _ = self._storage.grant_row(db, grant.id)
                if revision != new_revision or row["state"] != "revoked":
                    raise CorruptPolicy("Grant revocation commit invariant failed")
        del self._grants[id(grant)]
        if self._storage is None:
            self._policy_revision += 1
        else:
            self._sync_persistent()


class PolicyGate:
    def __init__(self, host):
        self._host = host

    def _descriptor(self, ref, db=None):
        if type(ref) is not EntityRef:
            raise AccessDenied("Exact immutable reference required")
        self._host._sync_persistent(db)
        descriptor = self._host._resources.get(ref)
        if descriptor is None or not descriptor.available:
            raise AccessDenied("Resource unavailable")
        try:
            valid = self._host._verify_registered_record(descriptor.record, db)
        except Exception as exc:
            raise AccessDenied("Resource verification failed") from exc
        if valid is not True:
            raise AccessDenied("Resource registration withdrawn")
        return descriptor

    def _matching_grant(self, principal, ref, action, purpose, episode_id, grants, db=None):
        if type(grants) not in (tuple, list) or len(grants) > 512:
            raise AccessDenied("Bounded grant list required")
        for value in grants:
            if type(value) is not Grant:
                continue
            registered = self._host._grants.get(id(value))
            if registered is None or registered[0] is not value:
                continue
            grant, issuer, subject = registered
            if subject is not principal:
                continue
            if (grant.ref == ref and grant.action == action and grant.purpose == purpose
                    and grant.episode_id == episode_id):
                if self._host._storage is not None:
                    def validate_persisted(connection):
                        self._host._sync_persistent(connection)
                        row, stored_issuer, stored_subject, stored_ref, stored_episode = \
                            self._host._storage.grant_row(connection, grant.id)
                        if (row["state"] != "active" or stored_ref != grant.ref
                                or row["action"] != grant.action
                                or row["purpose"] != grant.purpose
                                or stored_episode != grant.episode_id
                                or row["expires_at"] != grant.expires_at
                                or row["policy_revision"] != grant.policy_revision
                                or stored_issuer != issuer.actor or stored_subject != subject.actor
                                or row["subject_kind"] != subject.kind
                                or row["subject_purpose"] != subject.purpose):
                            raise AccessDenied("Persistent grant binding is invalid")
                        if grant.policy_revision != self._host._policy_revision:
                            raise AccessDenied("Grant policy revision is stale")
                        if grant.expires_at <= self._host._now():
                            raise AccessDenied("Grant expired")
                        self._host._principal(issuer, human=True, db=connection)
                        self._host._principal(subject, db=connection)
                        self._host._storage.observe_clock(connection, self._host._now())
                        self._host._load_persistent_in_transaction(connection)
                    if db is None:
                        with self._host._storage.transaction(write=True) as connection:
                            validate_persisted(connection)
                    else:
                        validate_persisted(db)
                else:
                    if grant.policy_revision != self._host._policy_revision:
                        raise AccessDenied("Grant policy revision is stale")
                    if grant.expires_at <= self._host._now():
                        raise AccessDenied("Grant expired")
                    self._host._principal(issuer, human=True)
                    self._host._principal(subject)
                return grant
        raise AccessDenied("No exact active grant")

    def _authorize_descriptor(self, principal, ref, *, action, purpose, grants,
                              episode_id=None, db=None):
        self._host._sync_persistent(db)
        principal = self._host._principal(principal, db=db)
        if type(action) is not str or action not in _ACTIONS:
            raise AccessDenied("Invalid action")
        if type(purpose) is not str or purpose not in _RUNTIME_PURPOSES:
            raise AccessDenied("Invalid purpose")
        if (purpose == "compiler") != (action == "compile"):
            raise AccessDenied("Compiler action and purpose must be bound together")
        episode_id = _episode(episode_id)
        descriptor = self._descriptor(ref, db)
        if principal.kind == "runtime" and principal.purpose != purpose:
            raise AccessDenied("Runtime purpose cannot be widened")
        if principal.kind == "runtime" and descriptor.tainted:
            raise AccessDenied("Sensitive evidence is not a raw runtime input")
        if purpose == "compiler":
            if action != "compile" or not self._host._compiler_member(ref):
                raise AccessDenied("Unverified compiler source")
        elif descriptor.purpose != purpose:
            raise AccessDenied("Cross-purpose access denied")
        if descriptor.episode_id != episode_id:
            raise AccessDenied("Episode scope mismatch")
        self._matching_grant(
            principal, ref, action, purpose, episode_id, grants, db=db)
        return descriptor

    def authorize(self, principal, ref, *, action, purpose, grants, episode_id=None):
        """Authorize without returning record-bearing internal descriptor state."""
        self._authorize_descriptor(principal, ref, action=action, purpose=purpose,
                                   grants=grants, episode_id=episode_id)
        return None

    def _authorize_in_transaction(self, db, principal, ref, *, action, purpose,
                                  grants, episode_id=None):
        """Revalidate authority inside the caller's exact open vault transaction."""
        storage = self._host._storage
        if storage is None:
            raise AccessDenied("Persistent permission registry is required")
        try:
            databases = list(db.execute("PRAGMA database_list")) \
                if type(db) is sqlite3.Connection else []
            settings = {
                name: db.execute(f"PRAGMA {name}").fetchone()[0]
                for name in ("journal_mode", "synchronous", "fullfsync", "foreign_keys")
            } if databases else {}
            exact_main = (
                len(databases) == 1
                and databases[0]["name"] == "main"
                and Path(databases[0]["file"]).resolve() == storage.path.resolve()
            )
            hardened = (settings == {
                "journal_mode": "wal", "synchronous": 2,
                "fullfsync": 1, "foreign_keys": 1,
            })
            if (db.row_factory is not sqlite3.Row or not db.in_transaction
                    or not exact_main or not hardened):
                raise AccessDenied("Exact active DomainStore transaction required")
        except AccessDenied:
            raise
        except (KeyError, OSError, TypeError, ValueError, sqlite3.Error) as exc:
            raise AccessDenied("Exact active DomainStore transaction required") from exc

        self._host._sync_persistent(db)
        try:
            # This no-op CAS proves the supplied transaction is writable. It neither
            # opens nor commits a connection and is covered by the caller's rollback.
            changed = db.execute(
                "UPDATE permission_control SET row_digest=row_digest "
                "WHERE singleton=1 AND vault_id=?", (self._host.vault_id,)).rowcount
        except sqlite3.Error as exc:
            raise AccessDenied("Writable DomainStore transaction required") from exc
        if changed != 1:
            raise CorruptPolicy("Permission control disappeared during authorization")
        self._authorize_descriptor(
            principal, ref, action=action, purpose=purpose, grants=grants,
            episode_id=episode_id, db=db)
        return None

    def _authorize_graph(self, principal, ref, *, action, purpose, grants, episode_id):
        stack, seen = [ref], set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            if len(seen) >= 4096:
                raise AccessDenied("Authorization graph bound exceeded")
            descriptor = self._authorize_descriptor(
                principal, current, action=action, purpose=purpose,
                grants=grants, episode_id=episode_id)
            seen.add(current)
            stack.extend(descriptor.dependencies)
        return seen

    def read(self, principal, ref, *, purpose, grants, episode_id=None, loader):
        if not callable(loader):
            raise TypeError("Loader must be callable")
        self._authorize_graph(principal, ref, action="read", purpose=purpose,
                              grants=grants, episode_id=episode_id)
        value = loader(ref)
        # Authorization is time/revocation sensitive; never release bytes obtained after
        # a grant/session changed while the loader was running.
        self._authorize_graph(principal, ref, action="read", purpose=purpose,
                              grants=grants, episode_id=episode_id)
        return value

    def compiler_input(self, principal, source_ref, *, grants):
        def authorize_projection():
            self._host._sync_persistent()
            candidate = self._host._projections.get(source_ref)
            if candidate is None or candidate.expires_at <= self._host._now():
                raise AccessDenied("No active verified compiler projection")
            try:
                verified = self._host._verify_projection(candidate)
            except Exception as exc:
                raise AccessDenied("Projection re-verification failed") from exc
            if verified is not True:
                raise AccessDenied("Projection verification withdrawn")
            required = {candidate.source_ref}
            for _, refs in candidate.support_by_field:
                required.update(refs)
            for ref in required:
                self._authorize_descriptor(
                    principal, ref, action="compile", purpose="compiler",
                    grants=grants, episode_id=None)
                descriptor = self._descriptor(ref)
                if descriptor.tainted:
                    raise AccessDenied("Sensitive evidence cannot enter compiler projection")
            return candidate

        projection = authorize_projection()
        payload = {
            "schema_version": "compiler-input-v1",
            "target": projection.target,
            "change_kind": projection.change_kind,
            **dict(projection.values),
            "support_by_field": MappingProxyType({
                name: tuple(MappingProxyType(ref.as_dict()) for ref in refs)
                for name, refs in projection.support_by_field
            }),
        }
        # Like byte reads, do not release a compiler payload if policy, grants or
        # the separately trusted semantic receipt changed during materialization.
        if authorize_projection() != projection:
            raise AccessDenied("Compiler projection changed during authorization")
        return MappingProxyType(payload)


def create_policy(vault_id, *, authenticate_session, verify_registered,
                  verify_projection, clock):
    """Create the deliberately process-local policy used by bounded unit services."""
    host = HostPolicy(vault_id, authenticate_session=authenticate_session,
                      verify_registered=verify_registered,
                      verify_projection=verify_projection, clock=clock)
    return host, PolicyGate(host)


def create_persistent_policy(domain_store, *, authenticate_session,
                             verify_projection, clock):
    """Release constructor bound to one initialized canonical DomainStore."""
    if type(domain_store) is not DomainStore:
        raise TypeError("Persistent policy requires the exact initialized DomainStore")
    vault_id = domain_store.roots().genesis.id
    host = HostPolicy(
        vault_id, authenticate_session=authenticate_session,
        verify_registered=None, verify_projection=verify_projection, clock=clock,
        _domain_store=domain_store,
    )
    return host, PolicyGate(host)
