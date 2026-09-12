"""Internal additive repository, not an authorization or UI/model-facing API.

The passed legacy Store remains owner of intake.sqlite3. These methods enforce content
integrity and purpose partitioning, not actor permission. T009/010 must authorize callers
before invoking them. No imported object can invoke the host-only bootstrap operation.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from threading import RLock
from uuid import uuid4

from ..storage import Store
from .refs import DomainContractError, EntityRef, canonical_json, parse_canonical, uuid_string
from .schemas import BOOTSTRAP_VERSION, GENESIS_VERSION, ImmutableRecord, PURPOSES


DEFAULT_MAX_BLOB_BYTES = 16 * 1024 * 1024
MAX_GRAPH_NODES = 4096
MAX_GRAPH_DEPTH = 256
MAX_GRAPH_BLOB_BYTES = 64 * 1024 * 1024
MAX_LEGACY_MIGRATION_ITEMS = 1000
MAX_LEGACY_MIGRATION_BYTES = 64 * 1024 * 1024
MAX_LEGACY_LINKS = 4096
MAX_LEGACY_LINK_VERIFY_BYTES = 64 * 1024 * 1024
WRITER_TIMEOUT_SECONDS = 5.0
_WRITER = RLock()
_REF_KEYS = frozenset({"kind", "id", "version", "sha256"})
_BLOB_KEYS = frozenset({"vault_id", "purpose", "sha256", "size"})
_ROOT_NAMES = ("genesis", "actor", "access_policy", "retention_policy")


class StorageError(ValueError):
    """Repository integrity failure; never permission to omit required evidence."""


class UninitializedVault(StorageError):
    pass


class AlreadyInitialized(StorageError):
    pass


class BootstrapDenied(StorageError):
    pass


class MissingRecord(StorageError):
    """No registered identity in this vault; does not reveal another vault's contents."""


class CorruptRecord(StorageError):
    pass


class VerificationLimit(StorageError):
    """Verification could not finish within this implementation's graph limits."""


class ImmutableConflict(StorageError):
    pass


class MissingBlob(StorageError):
    pass


class CorruptBlob(StorageError):
    pass


class ForeignVault(StorageError):
    pass


class PurposeMismatch(StorageError):
    pass


class UnsafePath(StorageError):
    pass


@contextmanager
def _writer():
    if not _WRITER.acquire(timeout=WRITER_TIMEOUT_SECONDS):
        raise StorageError("Domain writer wait limit exceeded")
    try:
        yield
    finally:
        _WRITER.release()


def _purpose(value):
    if type(value) is not str or value not in PURPOSES:
        raise DomainContractError("Expected registered storage purpose")
    return value


@dataclass(frozen=True, slots=True)
class BlobRef:
    vault_id: str
    purpose: str
    sha256: str
    size: int

    def __post_init__(self):
        uuid_string(self.vault_id)
        _purpose(self.purpose)
        if type(self.sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise DomainContractError("Expected exact blob SHA-256")
        if type(self.size) is not int or not 0 <= self.size <= 2 ** 63 - 1:
            raise DomainContractError("Expected bounded byte count")

    def as_dict(self):
        return dict(vault_id=self.vault_id, purpose=self.purpose,
                    sha256=self.sha256, size=self.size)

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != _BLOB_KEYS:
            raise DomainContractError("Expected exact blob reference")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class VaultRoots:
    genesis: EntityRef
    actor: EntityRef
    access_policy: EntityRef
    retention_policy: EntityRef


@dataclass(frozen=True, slots=True)
class LegacyFileLink:
    vault_id: str
    work_id: str
    file_id: str
    metadata_sha256: str
    legacy_sha256: str
    blob: BlobRef
    migrated_at_utc: str


@dataclass(frozen=True, slots=True)
class LegacyMigrationPage:
    links: tuple[LegacyFileLink, ...]
    remaining: int


_MIGRATION_1_DDL = (
    "CREATE TABLE domain_migrations (version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL)",
    "CREATE TABLE domain_vault (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "vault_id TEXT NOT NULL UNIQUE, roots BLOB NOT NULL, "
    "dispatch_enabled INTEGER NOT NULL DEFAULT 0 CHECK(dispatch_enabled=0))",
    "CREATE TABLE domain_records (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), "
    "kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0), "
    "sha256 TEXT NOT NULL, purpose TEXT NOT NULL, body BLOB NOT NULL, "
    "PRIMARY KEY(vault_id,kind,id,version), UNIQUE(vault_id,kind,id,version,sha256))",
    "CREATE TABLE domain_edges (vault_id TEXT NOT NULL, source_kind TEXT NOT NULL, "
    "source_id TEXT NOT NULL, source_version INTEGER NOT NULL, target_kind TEXT NOT NULL, "
    "target_id TEXT NOT NULL, target_version INTEGER NOT NULL, target_sha256 TEXT NOT NULL, "
    "PRIMARY KEY(vault_id,source_kind,source_id,source_version,target_kind,target_id,target_version), "
    "FOREIGN KEY(vault_id,source_kind,source_id,source_version) "
    "REFERENCES domain_records(vault_id,kind,id,version), "
    "FOREIGN KEY(vault_id,target_kind,target_id,target_version,target_sha256) "
    "REFERENCES domain_records(vault_id,kind,id,version,sha256))",
    "CREATE INDEX domain_edges_target ON domain_edges(vault_id,target_kind,target_id,target_version)",
    "CREATE TABLE domain_blobs (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), "
    "purpose TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL CHECK(size>=0), "
    "PRIMARY KEY(vault_id,purpose,sha256))",
    "CREATE TABLE domain_record_blobs (vault_id TEXT NOT NULL, source_kind TEXT NOT NULL, "
    "source_id TEXT NOT NULL, source_version INTEGER NOT NULL, purpose TEXT NOT NULL, "
    "sha256 TEXT NOT NULL, size INTEGER NOT NULL, "
    "PRIMARY KEY(vault_id,source_kind,source_id,source_version,purpose,sha256), "
    "FOREIGN KEY(vault_id,source_kind,source_id,source_version) "
    "REFERENCES domain_records(vault_id,kind,id,version), "
    "FOREIGN KEY(vault_id,purpose,sha256) REFERENCES domain_blobs(vault_id,purpose,sha256))",
)
MIGRATION_SHA256 = sha256("\n".join(_MIGRATION_1_DDL).encode("utf-8")).hexdigest()

_MIGRATION_2_DDL = (
    "CREATE UNIQUE INDEX domain_files_identity ON files(id,work_id)",
    "CREATE TABLE domain_legacy_files (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), "
    "file_id TEXT NOT NULL, work_id TEXT NOT NULL, metadata_sha256 TEXT NOT NULL, "
    "legacy_sha256 TEXT NOT NULL, legacy_size INTEGER NOT NULL CHECK(legacy_size>=0), "
    "purpose TEXT NOT NULL CHECK(purpose='operational'), blob_sha256 TEXT NOT NULL, "
    "blob_size INTEGER NOT NULL CHECK(blob_size>=0), "
    "read_source TEXT NOT NULL CHECK(read_source='cas'), migrated_at_utc TEXT NOT NULL, "
    "PRIMARY KEY(vault_id,file_id), "
    "FOREIGN KEY(file_id,work_id) REFERENCES files(id,work_id), "
    "FOREIGN KEY(vault_id,purpose,blob_sha256) "
    "REFERENCES domain_blobs(vault_id,purpose,sha256), "
    "CHECK(legacy_sha256=blob_sha256), CHECK(legacy_size=blob_size))",
    "CREATE INDEX domain_legacy_files_work ON domain_legacy_files(vault_id,work_id,file_id)",
)
MIGRATION_2_SHA256 = sha256("\n".join(_MIGRATION_2_DDL).encode("utf-8")).hexdigest()


def _normalize_schema_sql(value):
    if type(value) is not str:
        return ""
    compact = " ".join(value.split()).casefold()
    return re.sub(r"\s*([(),=<>])\s*", r"\1", compact)


def _schema_name(statement):
    match = re.match(r"CREATE (?:UNIQUE )?(TABLE|INDEX) ([a-z_]+)", statement)
    if match is None:  # pragma: no cover - module constant invariant
        raise RuntimeError("Invalid domain migration statement")
    return match.group(1).lower(), match.group(2)


_EXPECTED_SCHEMA = {}
for _statement in _MIGRATION_1_DDL + _MIGRATION_2_DDL:
    _type, _name = _schema_name(_statement)
    _EXPECTED_SCHEMA[_name] = (_type, _normalize_schema_sql(_statement))

_MIGRATION_ROWS = ((1, MIGRATION_SHA256), (2, MIGRATION_2_SHA256))
_GOVERNED_TABLES = tuple(sorted(
    name for name, (object_type, _) in _EXPECTED_SCHEMA.items()
    if object_type == "table"
))


def _domain_schema_rows(db):
    """Return reserved objects and explicit schema attached to governed tables."""
    placeholders = ",".join("?" for _ in _GOVERNED_TABLES)
    return list(db.execute(
        "SELECT type,name,sql,tbl_name FROM sqlite_master "
        "WHERE lower(name) GLOB 'domain_*' "
        "OR (type IN ('index','trigger') AND sql IS NOT NULL "
        f"AND lower(tbl_name) IN ({placeholders})) ORDER BY name",
        _GOVERNED_TABLES,
    ))


def _references(body):
    """Index exact refs at any depth; reserved *_ref(s) fields cannot hide malformed refs."""
    entities, blobs = set(), set()

    def reference(value):
        if type(value) is dict and set(value) == _BLOB_KEYS:
            blobs.add(BlobRef.from_dict(value))
        else:
            entities.add(EntityRef.from_dict(value))

    def visit(value):
        if type(value) is dict:
            if _REF_KEYS <= set(value) or _BLOB_KEYS <= set(value):
                reference(value)
                return
            for name, child in value.items():
                if name.endswith("_ref") and child is not None:
                    reference(child)
                elif name.endswith("_refs"):
                    if type(child) is not list:
                        raise DomainContractError("Expected exact reference list")
                    for item in child:
                        reference(item)
                else:
                    visit(child)
        elif type(value) is list:
            for child in value:
                visit(child)

    visit(body)
    return entities, blobs


@contextmanager
def _directory(path):
    """Open every existing component without following symlinks; retain a directory fd."""
    absolute = Path(os.path.abspath(path))
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in absolute.parts[1:]:
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
            except OSError as exc:
                if not isinstance(exc, FileNotFoundError):
                    raise UnsafePath("Unsafe directory component") from exc
                raise
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _child_directory(parent, name, *, create=False):
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        else:
            os.fsync(parent)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise UnsafePath("Unsafe owned directory") from exc
    try:
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
            raise UnsafePath("Owned directory must have mode 0700")
        yield descriptor
    finally:
        os.close(descriptor)


class DomainStore:
    """Bounded internal repository. Instantiation never initializes authority or a vault."""

    def __init__(self, legacy_store, *, max_blob_bytes=DEFAULT_MAX_BLOB_BYTES):
        if type(legacy_store) is not Store:
            raise TypeError("Pass the existing legacy Store")
        if type(max_blob_bytes) is not int or not 1 <= max_blob_bytes <= 64 * 1024 * 1024:
            raise ValueError("CAS implementation ceiling must be 1..64 MiB")
        self.path = Path(os.path.abspath(legacy_store.path))
        self.data_dir = Path(os.path.abspath(legacy_store.data_dir))
        if self.path != self.data_dir / "intake.sqlite3":
            raise UnsafePath("Domain storage must share the legacy database")
        self._legacy_store = legacy_store
        self.max_blob_bytes = max_blob_bytes
        with _writer(), self._connection(write=True) as db:
            objects = {row["name"] for row in _domain_schema_rows(db)}
            if not objects:
                for statement in _MIGRATION_1_DDL:
                    db.execute(statement)
                db.execute("INSERT INTO domain_migrations VALUES (1, ?)",
                           (MIGRATION_SHA256,))
                for statement in _MIGRATION_2_DDL:
                    db.execute(statement)
                db.execute("INSERT INTO domain_migrations VALUES (2, ?)",
                           (MIGRATION_2_SHA256,))
            else:
                if "domain_migrations" not in objects:
                    raise CorruptRecord("Unversioned domain schema")
                rows = [tuple(row) for row in db.execute(
                    "SELECT version,sha256 FROM domain_migrations ORDER BY version")]
                if rows == [_MIGRATION_ROWS[0]]:
                    self._verify_schema(db, through_version=1)
                    for statement in _MIGRATION_2_DDL:
                        db.execute(statement)
                    db.execute("INSERT INTO domain_migrations VALUES (2, ?)",
                               (MIGRATION_2_SHA256,))
                elif rows != list(_MIGRATION_ROWS):
                    raise CorruptRecord("Unknown or corrupt domain migration ledger")
            self._verify_schema(db, through_version=2)

    @staticmethod
    def _verify_schema(db, *, through_version):
        if through_version not in (1, 2):  # pragma: no cover - internal constant boundary
            raise RuntimeError("Unknown domain schema version")
        statements = _MIGRATION_1_DDL
        if through_version == 2:
            statements += _MIGRATION_2_DDL
        expected_names = {_schema_name(statement)[1] for statement in statements}
        rows = _domain_schema_rows(db)
        if {row["name"] for row in rows} != expected_names:
            raise CorruptRecord("Domain schema object set is inconsistent")
        expected = {name: _EXPECTED_SCHEMA[name] for name in expected_names}
        for row in rows:
            object_type, sql = expected[row["name"]]
            if row["type"] != object_type or _normalize_schema_sql(row["sql"]) != sql:
                raise CorruptRecord("Domain schema definition is inconsistent")

    @contextmanager
    def _connection(self, *, write=False):
        with self._legacy_store._borrow_verified_handles() as retained, \
                _directory(self.data_dir) as parent:
            directory_metadata = os.fstat(parent)
            if (stat.S_IMODE(directory_metadata.st_mode) != 0o700
                    or directory_metadata.st_uid != os.getuid()):
                raise UnsafePath("Vault directory must be current-user-owned mode 0700")
            try:
                metadata = os.stat("intake.sqlite3", dir_fd=parent, follow_symlinks=False)
            except OSError as exc:
                raise UnsafePath("Missing legacy database") from exc
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != os.getuid()):
                raise UnsafePath("Database must be current-user-owned regular non-linked mode 0600")
            for suffix in ("-wal", "-shm", "-journal"):
                try:
                    sidecar = os.stat("intake.sqlite3" + suffix, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if (not stat.S_ISREG(sidecar.st_mode) or sidecar.st_nlink != 1
                        or stat.S_IMODE(sidecar.st_mode) != 0o600 or sidecar.st_uid != os.getuid()):
                    raise UnsafePath("Unsafe SQLite sidecar")
            # The legacy database already exists. ``mode=rw`` prevents SQLite's
            # pathname open from creating a file if the visible directory is swapped
            # after the no-follow stat. The connected inode is checked before any
            # mutable PRAGMA, migration, or transaction statement.
            db = sqlite3.connect(
                self.path.as_uri() + "?mode=rw", timeout=5,
                isolation_level=None, uri=True,
            )
            try:
                def verify_open_path():
                    try:
                        held_database = os.stat(
                            "intake.sqlite3", dir_fd=parent, follow_symlinks=False)
                        with _directory(self.data_dir) as visible_parent:
                            visible_directory = os.fstat(visible_parent)
                            visible_database = os.stat(
                                "intake.sqlite3", dir_fd=visible_parent,
                                follow_symlinks=False)
                        databases = db.execute("PRAGMA database_list").fetchall()
                        if (len(databases) != 1 or databases[0][1] != "main"
                                or not databases[0][2]):
                            raise UnsafePath("Vault connection identity is unavailable")
                        connected_path = Path(os.path.abspath(databases[0][2]))
                        connected_database = os.stat(
                            connected_path, follow_symlinks=False)
                    except OSError as exc:
                        raise UnsafePath("Vault path changed during connection") from exc
                    if ((directory_metadata.st_dev, directory_metadata.st_ino)
                            != (visible_directory.st_dev, visible_directory.st_ino)
                            or (metadata.st_dev, metadata.st_ino)
                            != (held_database.st_dev, held_database.st_ino)
                            or (metadata.st_dev, metadata.st_ino)
                            != (visible_database.st_dev, visible_database.st_ino)
                            or (metadata.st_dev, metadata.st_ino)
                            != (connected_database.st_dev, connected_database.st_ino)):
                        raise UnsafePath("Vault path changed during connection")
                    if retained is not None:
                        try:
                            self._legacy_store._assert_verified_identity(
                                retained[0], retained[1], connected_path,
                            )
                        except ValueError as exc:
                            raise UnsafePath(
                                "Vault differs from the retained legacy identity"
                            ) from exc

                # sqlite3 opens by pathname. Re-resolve that pathname immediately and
                # again before BEGIN so a one-shot directory/database replacement cannot
                # bind this repository instance to a different vault.
                verify_open_path()
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA busy_timeout=5000")
                if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                    raise StorageError("WAL journal mode unavailable")
                db.execute("PRAGMA synchronous=FULL")
                db.execute("PRAGMA fullfsync=ON")
                if (db.execute("PRAGMA synchronous").fetchone()[0] != 2
                        or db.execute("PRAGMA foreign_keys").fetchone()[0] != 1
                        or db.execute("PRAGMA fullfsync").fetchone()[0] != 1):
                    raise StorageError("Required SQLite durability settings unavailable")
                verify_open_path()
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield db
                verify_open_path()
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def sqlite_settings(self):
        """Actual per-connection settings; not a universal hardware durability guarantee."""
        with self._connection() as db:
            return {name: db.execute(f"PRAGMA {name}").fetchone()[0] for name in
                    ("journal_mode", "synchronous", "fullfsync", "foreign_keys", "busy_timeout")}

    @staticmethod
    def _has_domain_data(db):
        # Missing roots with any residual data are partial corruption, never fresh setup.
        return any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
                   for table in ("domain_records", "domain_edges", "domain_blobs",
                                 "domain_record_blobs", "domain_legacy_files"))

    def _read_roots(self, db):
        row = db.execute("SELECT vault_id, roots, dispatch_enabled FROM domain_vault "
                         "WHERE singleton=1").fetchone()
        if row is None:
            if self._has_domain_data(db):
                raise CorruptRecord("Root registry is missing from a nonempty domain vault")
            raise UninitializedVault("Host initialization is required")
        try:
            value = parse_canonical(row["roots"])
            if type(value) is not dict or set(value) != set(_ROOT_NAMES) or row["dispatch_enabled"] != 0:
                raise DomainContractError("Invalid root registry")
            roots = VaultRoots(**{name: EntityRef.from_dict(value[name]) for name in _ROOT_NAMES})
            for name in _ROOT_NAMES:
                ref = getattr(roots, name)
                if ref.kind != ("vault_genesis" if name == "genesis" else name) or ref.version != 1:
                    raise DomainContractError("Invalid root kind/version")
            if roots.genesis.id != row["vault_id"]:
                raise DomainContractError("Invalid vault binding")
        except (DomainContractError, TypeError) as exc:
            raise CorruptRecord("Invalid vault root registry") from exc
        for name in _ROOT_NAMES:
            try:
                record = self._load(db, getattr(roots, name), roots)[0]
            except MissingRecord as exc:
                raise CorruptRecord("Incomplete bootstrap root set") from exc
            expected = GENESIS_VERSION if name == "genesis" else BOOTSTRAP_VERSION
            if record.body["schema_version"] != expected:
                raise CorruptRecord("Root registry does not identify the installed bootstrap")
        return roots

    def roots(self):
        with self._connection() as db:
            roots = self._read_roots(db)
            self._check_graph(db, [getattr(roots, name) for name in _ROOT_NAMES], roots)
            return roots

    @property
    def vault_id(self):
        return self.roots().genesis.id

    def initialize_vault(self):
        """Host-only first setup, no imported body/ID/root arguments; no external authority."""
        with _writer(), self._connection(write=True) as db:
            if db.execute("SELECT count(*) FROM domain_vault").fetchone()[0]:
                raise AlreadyInitialized("Root set is immutable and already installed")
            if self._has_domain_data(db):
                raise BootstrapDenied("Cannot bootstrap a nonempty domain store")
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            genesis = ImmutableRecord.genesis(vault_id=str(uuid4()), created_at_utc=stamp)
            records = [genesis] + [ImmutableRecord.bootstrap(kind=name, id=str(uuid4()),
                genesis_ref=genesis.ref, created_at_utc=stamp) for name in _ROOT_NAMES[1:]]
            roots = VaultRoots(*(item.ref for item in records))
            encoded = canonical_json({name: getattr(roots, name).as_dict() for name in _ROOT_NAMES})
            db.execute("INSERT INTO domain_vault(singleton,vault_id,roots) VALUES (1,?,?)",
                       (genesis.ref.id, encoded))
            for item in records:
                self._insert(db, item, genesis.ref.id)
            self._check_graph(db, [item.ref for item in records], roots)
        return roots

    @staticmethod
    def _insert(db, record, vault_id):
        ref, body = record.ref, record.body
        db.execute("INSERT INTO domain_records VALUES (?,?,?,?,?,?,?)",
                   (vault_id, ref.kind, ref.id, ref.version, ref.sha256,
                    body.get("purpose", "bootstrap"), record.body_bytes))
        entities, blobs = _references(body)
        for target in entities:
            db.execute("INSERT INTO domain_edges VALUES (?,?,?,?,?,?,?,?)",
                       (vault_id, ref.kind, ref.id, ref.version, target.kind, target.id,
                        target.version, target.sha256))
        for blob in blobs:
            db.execute("INSERT INTO domain_record_blobs VALUES (?,?,?,?,?,?,?)",
                       (vault_id, ref.kind, ref.id, ref.version, blob.purpose, blob.sha256, blob.size))

    @staticmethod
    def _load(db, ref, roots):
        row = db.execute("SELECT sha256,purpose,body FROM domain_records "
            "WHERE vault_id=? AND kind=? AND id=? AND version=?",
            (roots.genesis.id, ref.kind, ref.id, ref.version)).fetchone()
        if row is None:
            raise MissingRecord("Exact record identity is not registered in this vault")
        try:
            record = ImmutableRecord.from_bytes(row["body"], expected_ref=ref)
            body = record.body
            if row["sha256"] != ref.sha256 or row["purpose"] != body.get("purpose", "bootstrap"):
                raise DomainContractError("Indexed hash/purpose mismatch")
            if body["schema_version"] == GENESIS_VERSION and ref != roots.genesis:
                raise DomainContractError("Foreign genesis")
            if body["schema_version"] == BOOTSTRAP_VERSION:
                if (ref != getattr(roots, ref.kind)
                        or EntityRef.from_dict(body["genesis_ref"]) != roots.genesis):
                    raise DomainContractError("Foreign bootstrap root")
            entities, blobs = _references(body)
            indexed = {EntityRef(row[0], row[1], row[2], row[3]) for row in db.execute(
                "SELECT target_kind,target_id,target_version,target_sha256 FROM domain_edges "
                "WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?",
                (roots.genesis.id, ref.kind, ref.id, ref.version))}
            indexed_blobs = {BlobRef(roots.genesis.id, row[0], row[1], row[2]) for row in db.execute(
                "SELECT purpose,sha256,size FROM domain_record_blobs "
                "WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?",
                (roots.genesis.id, ref.kind, ref.id, ref.version))}
            if entities != indexed or blobs != indexed_blobs:
                raise DomainContractError("Reference index/body mismatch")
        except (DomainContractError, TypeError, AttributeError) as exc:
            raise CorruptRecord("Record bytes, reference or indexes are corrupt") from exc
        return record, entities, blobs

    def _check_graph(self, db, refs, roots):
        active, done = set(), set()
        seen_blobs = set()
        verified_blob_bytes = 0
        stack = [(ref, False, 0) for ref in refs]
        while stack:
            ref, leaving, depth = stack.pop()
            if leaving:
                active.remove(ref)
                done.add(ref)
                continue
            if ref in active:
                raise CorruptRecord("Cyclic reference graph")
            if ref in done:
                continue
            if depth > MAX_GRAPH_DEPTH or len(active) + len(done) >= MAX_GRAPH_NODES:
                raise VerificationLimit("Reference verification bound exceeded")
            _, entities, blobs = self._load(db, ref, roots)
            for blob in blobs:
                if blob not in seen_blobs:
                    if (blob.size > MAX_GRAPH_BLOB_BYTES - verified_blob_bytes):
                        raise VerificationLimit("Reference blob byte verification bound exceeded")
                    self._blob_bytes(db, blob, roots, purpose=blob.purpose)
                    verified_blob_bytes += blob.size
                    seen_blobs.add(blob)
            active.add(ref)
            stack.append((ref, True, depth))
            stack.extend((child, False, depth + 1) for child in entities)

    def put(self, record):
        if type(record) is not ImmutableRecord:
            raise DomainContractError("Expected immutable record")
        record = ImmutableRecord.from_bytes(record.body_bytes, expected_ref=record.ref)
        if record.body["schema_version"] in (GENESIS_VERSION, BOOTSTRAP_VERSION):
            raise BootstrapDenied("Only first host initialization may install roots")
        with _writer(), self._connection(write=True) as db:
            roots = self._read_roots(db)
            existing = db.execute("SELECT sha256 FROM domain_records "
                "WHERE vault_id=? AND kind=? AND id=? AND version=?",
                (roots.genesis.id, record.ref.kind, record.ref.id, record.ref.version)).fetchone()
            if existing is not None:
                if existing[0] != record.ref.sha256:
                    raise ImmutableConflict("Immutable identity/version already has different content")
                self._check_graph(db, [record.ref], roots)
                return record.ref
            entities, blobs = _references(record.body)
            self._check_graph(db, entities, roots)
            for blob in blobs:
                self._blob_bytes(db, blob, roots, purpose=blob.purpose)
            self._insert(db, record, roots.genesis.id)
            # Include the new root in the same bounded traversal used by reads.
            # A limit failure rolls back body and indexes with this transaction.
            self._check_graph(db, [record.ref], roots)
        return record.ref

    def get(self, ref):
        if type(ref) is not EntityRef:
            raise DomainContractError("Expected exact immutable EntityRef, not a locator")
        with self._connection() as db:
            roots = self._read_roots(db)
            self._check_graph(db, [ref], roots)
            return self._load(db, ref, roots)[0]

    @staticmethod
    def _legacy_metadata(value, *, work_id, file_id):
        if type(value) is not str:
            raise CorruptRecord("legacy file metadata is not text")
        try:
            encoded = value.encode("utf-8")
            metadata = json.loads(value)
        except (UnicodeEncodeError, json.JSONDecodeError) as exc:
            raise CorruptRecord("legacy file metadata is invalid") from exc
        if (type(metadata) is not dict or metadata.get("id") != file_id
                or type(metadata.get("sha256")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"]) is None
                or type(metadata.get("size")) is not int or metadata["size"] < 0):
            raise CorruptRecord("legacy file metadata identity is invalid")
        return metadata, encoded, sha256(encoded).hexdigest()

    def _legacy_snapshot(self, db, *, work_id, file_id):
        row = db.execute("SELECT metadata,typeof(data) AS data_type,length(data) AS data_size FROM files "
                         "WHERE work_id=? AND id=?",
                         (work_id, file_id)).fetchone()
        if row is None:
            raise KeyError((work_id, file_id))
        metadata, _, metadata_sha256 = self._legacy_metadata(
            row["metadata"], work_id=work_id, file_id=file_id)
        if row["data_type"] != "blob":
            raise CorruptRecord("legacy file storage class is not BLOB")
        if type(row["data_size"]) is not int or row["data_size"] < 0:
            raise CorruptRecord("legacy file byte length is invalid")
        if row["data_size"] > self.max_blob_bytes:
            raise VerificationLimit("Legacy content exceeds this backend's verification bound")
        data_row = db.execute("SELECT data FROM files WHERE work_id=? AND id=?",
                              (work_id, file_id)).fetchone()
        data = data_row["data"]
        if type(data) is not bytes or len(data) != row["data_size"]:
            raise CorruptRecord("legacy file bytes are invalid")
        actual = sha256(data).hexdigest()
        if len(data) != metadata["size"] or actual != metadata["sha256"]:
            raise CorruptRecord("legacy file bytes do not match their stored metadata")
        return metadata_sha256, actual, len(data), data

    def _legacy_link(self, db, row, roots):
        try:
            if (row["vault_id"] != roots.genesis.id or row["read_source"] != "cas"
                    or row["purpose"] != "operational"):
                raise DomainContractError("Legacy link vault/read source mismatch")
            uuid_string(row["work_id"])
            uuid_string(row["file_id"])
            metadata_row = db.execute(
                "SELECT metadata FROM files WHERE work_id=? AND id=?",
                (row["work_id"], row["file_id"])).fetchone()
            if metadata_row is None:
                raise DomainContractError("Legacy link target is missing")
            metadata, _, metadata_sha256 = self._legacy_metadata(
                metadata_row["metadata"], work_id=row["work_id"], file_id=row["file_id"])
            if (metadata_sha256 != row["metadata_sha256"]
                    or metadata["sha256"] != row["legacy_sha256"]
                    or metadata["size"] != row["legacy_size"]
                    or row["legacy_sha256"] != row["blob_sha256"]
                    or row["legacy_size"] != row["blob_size"]
                    or type(row["migrated_at_utc"]) is not str
                    or re.fullmatch(
                        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z",
                        row["migrated_at_utc"]) is None):
                raise DomainContractError("Legacy link content binding mismatch")
            datetime.strptime(row["migrated_at_utc"], "%Y-%m-%dT%H:%M:%S.%fZ")
            blob = BlobRef(row["vault_id"], row["purpose"], row["blob_sha256"],
                           row["blob_size"])
            self._blob_bytes(db, blob, roots, purpose=blob.purpose)
            return LegacyFileLink(row["vault_id"], row["work_id"], row["file_id"],
                                  row["metadata_sha256"], row["legacy_sha256"], blob,
                                  row["migrated_at_utc"])
        except StorageError:
            raise
        except (DomainContractError, TypeError, ValueError) as exc:
            raise CorruptRecord("legacy file link or indexed content is corrupt") from exc

    @staticmethod
    def _legacy_link_row(db, *, vault_id, file_id):
        return db.execute(
            "SELECT vault_id,work_id,file_id,metadata_sha256,legacy_sha256,legacy_size,"
            "purpose,blob_sha256,blob_size,read_source,migrated_at_utc "
            "FROM domain_legacy_files WHERE vault_id=? AND file_id=?",
            (vault_id, file_id)).fetchone()

    def migrate_legacy_file(self, work_id, file_id):
        """Seal one immutable legacy file, then atomically switch only its stable-ID read."""
        uuid_string(work_id)
        uuid_string(file_id)
        with _writer():
            with self._connection() as db:
                roots = self._read_roots(db)
                existing = self._legacy_link_row(
                    db, vault_id=roots.genesis.id, file_id=file_id)
                if existing is not None:
                    link = self._legacy_link(db, existing, roots)
                    if link.work_id != work_id:
                        raise KeyError((work_id, file_id))
                    return link
                before = self._legacy_snapshot(db, work_id=work_id, file_id=file_id)
            metadata_sha256, legacy_sha256, legacy_size, data = before
            if legacy_size > self.max_blob_bytes:
                raise VerificationLimit("Legacy content exceeds this backend's verification bound")
            blob = self.put_blob(data, purpose="operational")
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            with self._connection(write=True) as db:
                roots = self._read_roots(db)
                after = self._legacy_snapshot(db, work_id=work_id, file_id=file_id)
                if after[:3] != before[:3] or after[3] != data:
                    raise CorruptRecord("legacy file changed while its CAS copy was staged")
                self._blob_bytes(db, blob, roots, purpose="operational")
                current = self._legacy_link_row(
                    db, vault_id=roots.genesis.id, file_id=file_id)
                if current is None:
                    db.execute(
                        "INSERT INTO domain_legacy_files "
                        "(vault_id,file_id,work_id,metadata_sha256,legacy_sha256,legacy_size,"
                        "purpose,blob_sha256,blob_size,read_source,migrated_at_utc) "
                        "VALUES (?,?,?,?,?,?,?,?,?,'cas',?)",
                        (roots.genesis.id, file_id, work_id, metadata_sha256, legacy_sha256,
                         legacy_size, blob.purpose, blob.sha256, blob.size, stamp))
                row = self._legacy_link_row(
                    db, vault_id=roots.genesis.id, file_id=file_id)
                link = self._legacy_link(db, row, roots) if row is not None else None
                if (link is None or link.work_id != work_id
                        or link.metadata_sha256 != metadata_sha256
                        or link.legacy_sha256 != legacy_sha256 or link.blob != blob):
                    raise CorruptRecord("legacy file has a conflicting migration link")
                return link

    def migrate_legacy_files(self, *, max_items=20):
        """Bounded resumable migration page; each file switches only after its own commit."""
        if type(max_items) is not int or not 1 <= max_items <= MAX_LEGACY_MIGRATION_ITEMS:
            raise ValueError("max_items must be a bounded positive integer")
        with self._connection() as db:
            roots = self._read_roots(db)
            candidates = list(db.execute(
                "SELECT files.work_id,files.id,typeof(files.data) AS data_type,"
                "length(files.data) AS data_size "
                "FROM files LEFT JOIN domain_legacy_files migrated "
                "ON migrated.vault_id=? AND migrated.file_id=files.id "
                "WHERE migrated.file_id IS NULL ORDER BY files.rowid LIMIT ?",
                (roots.genesis.id, max_items)))
            identities, total_bytes = [], 0
            for row in candidates:
                if row["data_type"] != "blob":
                    raise CorruptRecord("legacy file storage class is not BLOB")
                size = row["data_size"]
                if type(size) is not int or size < 0:
                    raise CorruptRecord("legacy file byte length is invalid")
                if size > self.max_blob_bytes:
                    raise VerificationLimit(
                        "Legacy content exceeds this backend's verification bound")
                if size > MAX_LEGACY_MIGRATION_BYTES - total_bytes:
                    if not identities:
                        raise VerificationLimit("Legacy migration page byte bound exceeded")
                    break
                identities.append((row["work_id"], row["id"]))
                total_bytes += size
        links = tuple(self.migrate_legacy_file(work_id, file_id)
                      for work_id, file_id in identities)
        with self._connection() as db:
            roots = self._read_roots(db)
            remaining = db.execute(
                "SELECT count(*) FROM files LEFT JOIN domain_legacy_files migrated "
                "ON migrated.vault_id=? AND migrated.file_id=files.id "
                "WHERE migrated.file_id IS NULL", (roots.genesis.id,)).fetchone()[0]
        return LegacyMigrationPage(links, remaining)

    def legacy_file_links(self):
        with self._connection() as db:
            roots = self._read_roots(db)
            rows = list(db.execute(
                "SELECT vault_id,work_id,file_id,metadata_sha256,legacy_sha256,legacy_size,"
                "purpose,blob_sha256,blob_size,read_source,migrated_at_utc "
                "FROM domain_legacy_files WHERE vault_id=? ORDER BY rowid LIMIT ?",
                (roots.genesis.id, MAX_LEGACY_LINKS + 1)))
            if len(rows) > MAX_LEGACY_LINKS:
                raise VerificationLimit("Legacy link verification bound exceeded")
            total_bytes = 0
            for row in rows:
                if type(row["blob_size"]) is not int or row["blob_size"] < 0:
                    raise CorruptRecord("legacy file link size is corrupt")
                if row["blob_size"] > MAX_LEGACY_LINK_VERIFY_BYTES - total_bytes:
                    raise VerificationLimit("Legacy link byte verification bound exceeded")
                total_bytes += row["blob_size"]
            return tuple(self._legacy_link(db, row, roots) for row in rows)

    @contextmanager
    def _blob_directory(self, purpose, *, create=False):
        with _directory(self.data_dir) as parent:
            with _child_directory(parent, "domain-cas", create=create) as cas:
                with _child_directory(cas, purpose, create=create) as directory:
                    yield directory

    def _file_bytes(self, directory, blob):
        try:
            descriptor = os.open(blob.sha256, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory)
        except FileNotFoundError as exc:
            raise MissingBlob("Registered content bytes are missing") from exc
        except OSError as exc:
            raise UnsafePath("Unsafe content file") from exc
        try:
            metadata = os.fstat(descriptor)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or stat.S_IMODE(metadata.st_mode) != 0o600):
                raise UnsafePath("Content must be an unlinked-to regular 0600 file")
            if metadata.st_size != blob.size:
                raise CorruptBlob("Content size mismatch")
            if blob.size > self.max_blob_bytes:
                raise VerificationLimit("Content exceeds this backend's verification bound")
            chunks, count = [], 0
            while chunk := os.read(descriptor, min(65536, self.max_blob_bytes + 1 - count)):
                chunks.append(chunk)
                count += len(chunk)
                if count > self.max_blob_bytes:
                    raise CorruptBlob("Content byte limit exceeded")
            data = b"".join(chunks)
            if len(data) != blob.size or sha256(data).hexdigest() != blob.sha256:
                raise CorruptBlob("Content digest mismatch")
            return data
        finally:
            os.close(descriptor)

    def _blob_bytes(self, db, blob, roots, *, purpose):
        if type(blob) is not BlobRef:
            raise DomainContractError("Expected exact BlobRef")
        _purpose(purpose)
        if blob.vault_id != roots.genesis.id:
            raise ForeignVault("Explicit blob vault binding differs")
        if blob.purpose != purpose:
            raise PurposeMismatch("Requested purpose differs from stored partition")
        row = db.execute("SELECT size FROM domain_blobs WHERE vault_id=? AND purpose=? AND sha256=?",
                         (blob.vault_id, blob.purpose, blob.sha256)).fetchone()
        if row is None:
            raise MissingBlob("Blob is not registered in this vault")
        if row[0] != blob.size:
            raise CorruptBlob("Registered blob size differs")
        try:
            with self._blob_directory(purpose) as directory:
                return self._file_bytes(directory, blob)
        except FileNotFoundError as exc:
            raise MissingBlob("Registered content directory is missing") from exc

    def read_blob(self, blob, *, purpose):
        with self._connection() as db:
            roots = self._read_roots(db)
            self._check_graph(db, [roots.genesis], roots)
            return self._blob_bytes(db, blob, roots, purpose=purpose)

    def put_blob(self, data, *, purpose):
        _purpose(purpose)
        if type(data) is not bytes or len(data) > self.max_blob_bytes:
            raise DomainContractError("Expected bounded exact bytes; no truncation")
        with _writer(), self._connection(write=True) as db:
            roots = self._read_roots(db)
            self._check_graph(db, [roots.genesis], roots)
            blob = BlobRef(roots.genesis.id, purpose, sha256(data).hexdigest(), len(data))
            row = db.execute("SELECT size FROM domain_blobs WHERE vault_id=? AND purpose=? AND sha256=?",
                             (blob.vault_id, purpose, blob.sha256)).fetchone()
            if row is not None:
                self._blob_bytes(db, blob, roots, purpose=purpose)
                return blob
            with self._blob_directory(purpose, create=True) as directory:
                try:
                    self._file_bytes(directory, blob)
                except MissingBlob:
                    staging = ".stage-" + str(uuid4())
                    descriptor = os.open(staging, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=directory)
                    try:
                        os.fchmod(descriptor, 0o600)
                        written = 0
                        while written < len(data):
                            count = os.write(descriptor, data[written:])
                            if count <= 0:
                                raise OSError("Content write made no progress")
                            written += count
                        os.fsync(descriptor)
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        actual = sha256()
                        verified = 0
                        while chunk := os.read(descriptor, min(65536, self.max_blob_bytes + 1 - verified)):
                            verified += len(chunk)
                            if verified > self.max_blob_bytes:
                                raise CorruptBlob("Staged content verification byte limit exceeded")
                            actual.update(chunk)
                        if (verified != blob.size or os.fstat(descriptor).st_size != blob.size
                                or actual.hexdigest() != blob.sha256):
                            raise CorruptBlob("Staged content failed verification")
                        # SQLite's writer transaction serializes participating publishers.
                        # App-owned 0700 directory; hostile same-user OS races are not a sandbox.
                        try:
                            os.stat(blob.sha256, dir_fd=directory, follow_symlinks=False)
                        except FileNotFoundError:
                            os.rename(staging, blob.sha256, src_dir_fd=directory, dst_dir_fd=directory)
                        else:
                            raise UnsafePath("Destination appeared during staging; reconciliation required")
                    finally:
                        os.close(descriptor)
                os.fsync(directory)
                self._file_bytes(directory, blob)
            db.execute("INSERT INTO domain_blobs VALUES (?,?,?,?)",
                       (blob.vault_id, purpose, blob.sha256, blob.size))
        return blob
