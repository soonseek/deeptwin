"""Closed, separately versioned private authentication component in DomainStore.

Row digests detect corruption, not a malicious administrator who can rewrite the DB.
Every statement is code-owned; no arbitrary auth record import is exposed.
"""
import sqlite3
from hashlib import sha256

from ..domain.refs import canonical_json


class AuthStorageError(RuntimeError):
    pass


_DDL = (
    "CREATE TABLE owner_auth_migrations(version INTEGER PRIMARY KEY CHECK(version=1),checksum TEXT NOT NULL)",
    """CREATE TABLE owner_auth_control(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), vault_id TEXT NOT NULL UNIQUE,
        instance_id TEXT NOT NULL, origin_digest TEXT NOT NULL, generation_id TEXT NOT NULL,
        key_id TEXT NOT NULL, manifest_digest TEXT NOT NULL, epoch INTEGER NOT NULL CHECK(epoch=1),
        opened_at INTEGER NOT NULL, deadline INTEGER NOT NULL CHECK(deadline=opened_at+600000),
        clock_floor INTEGER NOT NULL CHECK(clock_floor>=opened_at),
        revision INTEGER NOT NULL CHECK(revision>=1), hash TEXT NOT NULL)""",
    """CREATE TABLE owner_auth_bootstrap_claims(
        epoch INTEGER PRIMARY KEY REFERENCES owner_auth_control(epoch), verifier TEXT NOT NULL,
        attempts INTEGER NOT NULL CHECK(attempts BETWEEN 0 AND 5),
        state TEXT NOT NULL CHECK(state IN ('available','consumed','completed','expired','exhausted')),
        claim_id TEXT UNIQUE, consumed_at INTEGER, completed_at INTEGER,
        revision INTEGER NOT NULL CHECK(revision>=1), hash TEXT NOT NULL,
        CHECK((state IN ('consumed','completed'))=(claim_id IS NOT NULL)),
        CHECK((claim_id IS NOT NULL)=(consumed_at IS NOT NULL)),
        CHECK((state='completed')=(completed_at IS NOT NULL)))""",
    "CREATE UNIQUE INDEX owner_auth_control_epoch ON owner_auth_control(epoch)",
    """CREATE TABLE owner_auth_accounts(
        owner_id TEXT PRIMARY KEY, singleton INTEGER NOT NULL UNIQUE CHECK(singleton=1),
        actor_ref TEXT NOT NULL UNIQUE, login_name TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL CHECK(state IN ('active','disabled')),
        auth_epoch INTEGER NOT NULL CHECK(auth_epoch>=1), recovery_epoch INTEGER NOT NULL,
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL CHECK(updated_at>=created_at),
        revision INTEGER NOT NULL CHECK(revision>=1), hash TEXT NOT NULL,
        FOREIGN KEY(recovery_epoch) REFERENCES owner_auth_control(epoch))""",
    """CREATE TABLE owner_auth_authenticators(
        owner_id TEXT NOT NULL REFERENCES owner_auth_accounts(owner_id),
        revision INTEGER NOT NULL CHECK(revision>=1), previous_revision INTEGER,
        kind TEXT NOT NULL CHECK(kind='password'), profile TEXT NOT NULL CHECK(profile='argon2id-v19-m65536-t3-p4-s16-h32'),
        encoded_hash TEXT NOT NULL, created_at INTEGER NOT NULL, revoked_at INTEGER,
        hash TEXT NOT NULL, PRIMARY KEY(owner_id,revision),
        FOREIGN KEY(owner_id,previous_revision) REFERENCES owner_auth_authenticators(owner_id,revision),
        CHECK((revision=1 AND previous_revision IS NULL) OR
              (revision>1 AND previous_revision IS NOT NULL AND previous_revision=revision-1)))""",
    """CREATE TABLE owner_auth_sessions(
        session_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES owner_auth_accounts(owner_id),
        token_digest TEXT NOT NULL UNIQUE, authenticator_revision INTEGER NOT NULL,
        auth_epoch INTEGER NOT NULL, recovery_epoch INTEGER NOT NULL, origin_digest TEXT NOT NULL,
        created_at INTEGER NOT NULL, last_seen INTEGER NOT NULL CHECK(last_seen>=created_at),
        idle_expires INTEGER NOT NULL CHECK(idle_expires<=last_seen+43200000),
        absolute_expires INTEGER NOT NULL CHECK(absolute_expires=created_at+604800000),
        revoked_at INTEGER, revision INTEGER NOT NULL CHECK(revision>=1), hash TEXT NOT NULL,
        FOREIGN KEY(owner_id,authenticator_revision) REFERENCES owner_auth_authenticators(owner_id,revision),
        FOREIGN KEY(recovery_epoch) REFERENCES owner_auth_control(epoch))""",
    """CREATE TABLE owner_auth_commands(
        command_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES owner_auth_sessions(session_id),
        kind TEXT NOT NULL CHECK(kind='logout'), request_digest TEXT NOT NULL,
        response_json TEXT NOT NULL, created_at INTEGER NOT NULL,
        epoch INTEGER NOT NULL REFERENCES owner_auth_control(epoch), hash TEXT NOT NULL)""",
    """CREATE TABLE owner_auth_audit(
        sequence INTEGER PRIMARY KEY CHECK(sequence>=1),
        kind TEXT NOT NULL CHECK(kind IN ('opened','guess','claim','owner','login','logout')),
        entity_id TEXT, observed_at INTEGER NOT NULL, previous_hash TEXT, hash TEXT NOT NULL)""",
)
CHECKSUM = sha256(canonical_json(list(_DDL))).hexdigest()


def _shape(db):
    return {row["name"]: (row["type"], row["tbl_name"], row["sql"])
            for row in db.execute("SELECT name,type,tbl_name,sql FROM sqlite_master "
                "WHERE lower(name) GLOB 'owner_auth_*' OR type='trigger' "
                "OR (lower(tbl_name) GLOB 'owner_auth_*' AND sql IS NOT NULL) "
                "OR (type='view' AND lower(sql) LIKE '%owner_auth_%')")}


def _expected():
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        for statement in _DDL:
            db.execute(statement)
        shape = _shape(db)
        columns = {name.removeprefix("owner_auth_"): frozenset(row[1] for row in db.execute(f"PRAGMA table_info({name})"))
                   for name, item in shape.items() if item[0] == "table"}
        return shape, columns


SHAPE, COLUMNS = _expected()
TABLES = tuple(name.removeprefix("owner_auth_") for name, item in SHAPE.items()
               if item[0] == "table" and name != "owner_auth_migrations")


def digest(row):
    return sha256(canonical_json({key: value for key, value in row.items() if key != "hash"})).hexdigest()


def insert(db, table, values):
    if type(table) is not str or table not in TABLES:
        raise AuthStorageError("Unknown private auth table")
    if type(values) is not dict or set(values) != COLUMNS[table] - {"hash"}:
        raise AuthStorageError("Invalid private auth columns")
    row = {**values, "hash": digest(values)}
    db.execute(f"INSERT INTO owner_auth_{table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
               tuple(row.values()))
    return row


def update(db, table, old, changes, *, identity):
    identities = {"control": "singleton", "bootstrap_claims": "epoch", "accounts": "owner_id", "sessions": "session_id"}
    if table not in identities or identity != identities[table]:
        raise AuthStorageError("Invalid private auth update")
    columns = COLUMNS[table]
    if (set(dict(old)) != columns or set(changes) - columns or set(changes) & {identity, "hash", "revision"}
            or old["hash"] != digest(dict(old))):
        raise AuthStorageError("Invalid private auth update")
    values = {**dict(old), **changes, "revision": old["revision"] + 1}
    values["hash"] = digest(values)
    changed = db.execute(
        f"UPDATE owner_auth_{table} SET {','.join(key+'=?' for key in values)} "
        f"WHERE {identity}=? AND revision=?", (*values.values(), old[identity], old["revision"])).rowcount
    if changed != 1:
        raise AuthStorageError("Private auth revision conflict")
    return values


def audit(db, kind, entity_id, now):
    prior = db.execute("SELECT sequence,hash FROM owner_auth_audit ORDER BY sequence DESC LIMIT 1").fetchone()
    insert(db, "audit", {"sequence": 1 if prior is None else prior["sequence"] + 1,
                             "kind": kind, "entity_id": entity_id, "observed_at": now,
                             "previous_hash": None if prior is None else prior["hash"]})


def install(db):
    found = _shape(db)
    if not found:
        for statement in _DDL:
            db.execute(statement)
        db.execute("INSERT INTO owner_auth_migrations VALUES(1,?)", (CHECKSUM,))
    verify(db)


def verify(db):
    if _shape(db) != SHAPE:
        raise AuthStorageError("Private auth schema mismatch")
    migrations = [tuple(row) for row in db.execute("SELECT version,checksum FROM owner_auth_migrations")]
    if migrations != [(1, CHECKSUM)]:
        raise AuthStorageError("Private auth migration mismatch")
    for table in TABLES:
        for row in db.execute(f"SELECT * FROM owner_auth_{table}"):
            if row["hash"] != digest(dict(row)):
                raise AuthStorageError("Private auth row integrity mismatch")
            if table == "authenticators":
                revision = row["revision"]
                if (type(revision) is not int or revision < 1
                        or row["previous_revision"] != (None if revision == 1 else revision - 1)):
                    raise AuthStorageError("Private authenticator history mismatch")
    previous, sequence = None, 0
    for row in db.execute("SELECT * FROM owner_auth_audit ORDER BY sequence"):
        if row["sequence"] != sequence + 1 or row["previous_hash"] != previous:
            raise AuthStorageError("Private auth audit chain mismatch")
        previous, sequence = row["hash"], row["sequence"]
    if list(db.execute("PRAGMA foreign_key_check")):
        raise AuthStorageError("Private auth relationship mismatch")
