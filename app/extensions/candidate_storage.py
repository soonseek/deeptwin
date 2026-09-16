"""Closed private v1 index/journal; immutable content authority is DomainStore."""

import sqlite3
from hashlib import sha256

from ..domain.refs import canonical_json
from .candidate_contracts import CandidateError

DDL = (
    "CREATE TABLE extension_candidate_migrations(version INTEGER PRIMARY KEY CHECK(version=1),checksum TEXT NOT NULL)",
    """CREATE TABLE extension_candidate_control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id), instance_id TEXT NOT NULL,
        candidate_count INTEGER NOT NULL CHECK(candidate_count BETWEEN 0 AND 1024),
        content_bytes INTEGER NOT NULL CHECK(content_bytes BETWEEN 0 AND 67108864),
        revision INTEGER NOT NULL CHECK(revision>=1), hash TEXT NOT NULL)""",
    """CREATE TABLE extension_candidate_index(candidate_id TEXT PRIMARY KEY,
        vault_id TEXT NOT NULL REFERENCES extension_candidate_control(vault_id),
        kind TEXT NOT NULL CHECK(kind='extension_manifest'), version INTEGER NOT NULL CHECK(version=1),
        anchor_digest TEXT NOT NULL, manifest_digest TEXT NOT NULL, descriptor_digest TEXT NOT NULL,
        registration_digest TEXT NOT NULL, actor_ref TEXT NOT NULL, command_id TEXT NOT NULL UNIQUE,
        hash TEXT NOT NULL, FOREIGN KEY(vault_id,kind,candidate_id,version,anchor_digest)
        REFERENCES domain_records(vault_id,kind,id,version,sha256))""",
    """CREATE TABLE extension_candidate_commands(command_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL UNIQUE REFERENCES extension_candidate_index(candidate_id),
        namespace TEXT NOT NULL CHECK(namespace='extension-candidate-register-v1'),
        actor_ref TEXT NOT NULL, request_digest TEXT NOT NULL, document_order TEXT NOT NULL,
        receipt TEXT NOT NULL, event_sequence INTEGER NOT NULL CHECK(event_sequence>=1), hash TEXT NOT NULL)""",
    """CREATE TABLE extension_candidate_contents(sha256 TEXT PRIMARY KEY,
        vault_id TEXT NOT NULL REFERENCES extension_candidate_control(vault_id),
        purpose TEXT NOT NULL CHECK(purpose='operational'), size INTEGER NOT NULL CHECK(size BETWEEN 1 AND 1048576),
        hash TEXT NOT NULL, FOREIGN KEY(vault_id,purpose,sha256) REFERENCES domain_blobs(vault_id,purpose,sha256))""",
)
CHECKSUM = sha256(canonical_json(list(DDL))).hexdigest()


def shape(db):
    return {
        r["name"]: (r["type"], r["tbl_name"], r["sql"])
        for r in db.execute(
            "SELECT name,type,tbl_name,sql FROM sqlite_master WHERE lower(name) GLOB 'extension_candidate_*' "
            "OR type='trigger' OR (lower(tbl_name) GLOB 'extension_candidate_*' AND sql IS NOT NULL) "
            "OR (type='view' AND lower(sql) LIKE '%extension_candidate_%')"
        )
    }


def _expected():
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        for statement in DDL:
            db.execute(statement)
        result = shape(db)
        columns = {
            name.removeprefix("extension_candidate_"): frozenset(r[1] for r in db.execute(f"PRAGMA table_info({name})"))
            for name, item in result.items()
            if item[0] == "table"
        }
        return result, columns


SHAPE, COLUMNS = _expected()
TABLES = ("control", "index", "commands", "contents")


def digest(table, values):
    if type(table) is not str or table not in TABLES:
        raise CandidateError("unavailable")
    return sha256(
        canonical_json(
            {
                "namespace": "extension-candidate-storage-v1",
                "table": table,
                "row": {k: v for k, v in dict(values).items() if k != "hash"},
            }
        )
    ).hexdigest()


def insert(db, table, values):
    if (
        type(table) is not str
        or table not in TABLES
        or type(values) is not dict
        or set(values) != COLUMNS[table] - {"hash"}
    ):
        raise CandidateError("unavailable")
    row = {**values, "hash": digest(table, values)}
    db.execute(
        f"INSERT INTO extension_candidate_{table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
        tuple(row.values()),
    )
    return row


def advance(db, old, *, candidate_count, content_bytes):
    if set(dict(old)) != COLUMNS["control"] or old["hash"] != digest("control", old):
        raise CandidateError("unavailable")
    row = {
        **dict(old),
        "candidate_count": candidate_count,
        "content_bytes": content_bytes,
        "revision": old["revision"] + 1,
    }
    row["hash"] = digest("control", row)
    changed = db.execute(
        "UPDATE extension_candidate_control SET candidate_count=?,content_bytes=?,revision=?,hash=? "
        "WHERE singleton=1 AND revision=?",
        (candidate_count, content_bytes, row["revision"], row["hash"], old["revision"]),
    ).rowcount
    if changed != 1:
        raise CandidateError("unavailable")


def install(db):
    if not shape(db):
        for statement in DDL:
            db.execute(statement)
        db.execute("INSERT INTO extension_candidate_migrations VALUES(1,?)", (CHECKSUM,))
    verify(db)


def verify(db):
    if shape(db) != SHAPE or [
        tuple(r) for r in db.execute("SELECT version,checksum FROM extension_candidate_migrations")
    ] != [(1, CHECKSUM)]:
        raise CandidateError("unavailable")
    for table in TABLES:
        for row in db.execute(f"SELECT * FROM extension_candidate_{table}"):
            if row["hash"] != digest(table, row):
                raise CandidateError("unavailable")
    if list(db.execute("PRAGMA foreign_key_check")):
        raise CandidateError("unavailable")
