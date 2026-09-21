"""Bounded FK-on same-name rebuild, used only by the offline deployment operation."""
import time

from ..domain.refs import EntityRef
from ..domain.store import DomainStore
from .ledger import CorruptLedger
from .ledger_history import _verify_history
from .ledger_schema import LEDGER_V2_DDL, LEDGER_V2_SHA256, _schema_version

MAX_ROWS = 100_000
MAX_BYTES = 64 * 1024 * 1024


class LedgerMigrationError(ValueError):
    """A closed, payload-free deployment outcome."""
    def __init__(self, code):
        if code not in {"invalid_request", "unavailable", "busy", "maintenance_required",
                        "capacity_exceeded", "deadline_exceeded", "outcome_unknown"}:
            code = "maintenance_required"
        self.code = code
        super().__init__(code)


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LedgerMigrationError("deadline_exceeded")
    return remaining


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _inbound_attempt_foreign_keys(db):
    actual = []
    for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        groups = {}
        for row in db.execute(f"PRAGMA foreign_key_list({_quote(table)})"):
            if row[2].casefold() == "runtime_attempts":
                groups.setdefault(row[0], []).append(tuple(row))
        for rows in groups.values():
            rows.sort(key=lambda row: row[1])
            actual.append((table, tuple((row[3], row[4]) for row in rows),
                           tuple((row[5], row[6]) for row in rows)))
    expected = [(table, (("vault_id", "vault_id"), ("attempt_id", "id")),
                 (("NO ACTION", "NO ACTION"), ("NO ACTION", "NO ACTION"))) for table in
                ("runtime_attempt_refs", "runtime_result_observations", "runtime_tool_calls",
                 "runtime_attempt_journal")]
    if sorted(actual) != sorted(expected):
        raise CorruptLedger("Unexpected inbound attempt foreign key")


# Only record identities are expanded. Bodies are fetched after aggregate SQL sizing.
_REACHABLE = """WITH RECURSIVE needed(kind,id,version) AS (
 SELECT kind,id,version FROM runtime_run_refs
 UNION SELECT kind,id,version FROM runtime_attempt_refs
 UNION SELECT kind,id,version FROM runtime_result_refs
 UNION SELECT result_kind,result_id,result_version FROM runtime_tool_calls WHERE result_kind IS NOT NULL
 UNION SELECT approval_kind,approval_id,approval_version FROM runtime_tool_calls WHERE approval_kind IS NOT NULL
 UNION SELECT kind,id,version FROM domain_records WHERE kind IN
 ('vault_genesis','actor','access_policy','retention_policy','worker_response_capture')
 UNION SELECT e.target_kind,e.target_id,e.target_version FROM domain_edges e JOIN needed n
 ON e.source_kind=n.kind AND e.source_id=n.id AND e.source_version=n.version
) """


def _plans(db):
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
        "AND (name GLOB 'runtime_*' OR name='sqlite_sequence') ORDER BY name")]
    plans = {}
    for table in tables + ["domain_migrations", "domain_vault", "domain_records", "domain_edges",
                           "domain_record_blobs", "domain_blobs"]:
        info = list(db.execute(f"PRAGMA table_info({_quote(table)})"))
        columns = tuple(row[1] for row in info)
        if table == "runtime_attempts":
            # Public run projections use insertion order. Retain the hidden rowid
            # while still snapshotting in deterministic primary-key order.
            columns = ("rowid",) + columns
        keys = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
        order = ",".join(_quote(x) for x in (keys or list(columns)))
        prefix, where = "", ""
        if table in {"domain_records", "domain_edges", "domain_record_blobs"}:
            prefix = _REACHABLE
            names = ("kind", "id", "version") if table == "domain_records" else (
                "source_kind", "source_id", "source_version")
            where = " WHERE EXISTS (SELECT 1 FROM needed n WHERE " + " AND ".join(
                f'n.{key}=t.{column}' for key, column in zip(("kind", "id", "version"), names)) + ")"
        elif table == "domain_blobs":
            prefix = _REACHABLE
            where = """ WHERE EXISTS (SELECT 1 FROM domain_record_blobs b JOIN needed n
 ON b.source_kind=n.kind AND b.source_id=n.id AND b.source_version=n.version
 WHERE b.vault_id=t.vault_id AND b.purpose=t.purpose AND b.sha256=t.sha256)"""
        plans[table] = (columns, prefix, f" FROM {_quote(table)} t" + where, order)
    return plans


def _size(db, plans, deadline):
    count = size = 0
    # Pre-size all retained values before materializing any payload.
    for columns, prefix, source, order in plans.values():
        _remaining(deadline)
        expressions = [f"CASE typeof({_quote(name)}) WHEN 'null' THEN 0 "
            f"WHEN 'integer' THEN 8 WHEN 'real' THEN 8 ELSE length(CAST({_quote(name)} AS BLOB)) END"
            for name in columns]
        query = prefix + "SELECT count(*),coalesce(sum(scalar_bytes),0) FROM (SELECT " + "+".join(
            expressions) + " AS scalar_bytes" + source + " LIMIT ?)"
        n, amount = db.execute(query, (MAX_ROWS - count + 1,)).fetchone()
        count += n
        size += amount
        if count > MAX_ROWS or size > MAX_BYTES:
            raise LedgerMigrationError("capacity_exceeded")


def _project_v2(plans):
    """SQL-only target rows: charge derived values before any payload fetch or write."""
    projected = dict(plans)
    columns, prefix, _, order = plans["runtime_attempts"]
    projected["runtime_attempts"] = (columns + ("subject_kind", "subject_id"), prefix,
        " FROM (SELECT rowid,*, 'node_execution' AS subject_kind, execution_id AS subject_id "
        "FROM runtime_attempts) t", order)
    projected["runtime_dispatch_subjects"] = (
        ("vault_id", "subject_kind", "subject_id", "node_execution_id", "generation_kind",
         "generation_version", "generation_sha256"), "",
        " FROM (SELECT vault_id,'node_execution' AS subject_kind,id AS subject_id,"
        "id AS node_execution_id,NULL AS generation_kind,NULL AS generation_version,"
        "NULL AS generation_sha256 FROM runtime_node_executions) t", "")
    columns, prefix, _, order = plans["runtime_migrations"]
    projected["runtime_migrations"] = (columns, prefix,
        " FROM (SELECT * FROM runtime_migrations UNION ALL SELECT 'ledger',2,'"
        + LEDGER_V2_SHA256 + "') t", order)
    return projected


def _snapshot(db, deadline, *, target_v2=False):
    plans = _plans(db)
    _size(db, _project_v2(plans) if target_v2 else plans, deadline)
    snapshots = {}
    for table, (columns, prefix, source, order) in plans.items():
        rows = []
        for row in db.execute(prefix + "SELECT " + ",".join(_quote(x) for x in columns) + source + " ORDER BY " + order):
            _remaining(deadline)
            rows.append(tuple(row))
        snapshots[table] = (columns, prefix, source, order, rows)
    return snapshots


def _compare(db, snapshots, deadline, *, migrated=False):
    for table, (columns, prefix, source, order, rows) in snapshots.items():
        if migrated and table == "runtime_migrations":
            source += " WHERE NOT (component='ledger' AND version=2)"
        cursor = db.execute(prefix + "SELECT " + ",".join(_quote(x) for x in columns) + source + " ORDER BY " + order)
        for expected in rows:
            _remaining(deadline)
            actual = cursor.fetchone()
            if actual is None or tuple(actual) != expected:
                raise CorruptLedger("Migration preservation failed")
        extra = cursor.fetchone()
        if extra is not None:
            raise CorruptLedger("Migration preservation failed")


def _verify_metadata(db, snapshots, roots, deadline):
    columns, _, _, _, rows = snapshots["domain_records"]
    indices = [columns.index(key) for key in ("kind", "id", "version", "sha256")]
    for row in rows:
        _remaining(deadline)
        record, entities, blobs = DomainStore._load(db, EntityRef(*(row[index] for index in indices)), roots)
        for blob in blobs:
            actual = db.execute("SELECT size FROM domain_blobs WHERE vault_id=? AND purpose=? AND sha256=?",
                                (blob.vault_id, blob.purpose, blob.sha256)).fetchone()
            if actual is None or actual[0] != blob.size:
                raise CorruptLedger("Blob metadata changed")


def _preflight(db, vault_id, deadline):
    version = _schema_version(db)
    if version not in (1, 2):
        raise CorruptLedger("Runtime ledger schema absent")
    _inbound_attempt_foreign_keys(db)
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise CorruptLedger("Database foreign key violation")
    snapshots = _snapshot(db, deadline, target_v2=version == 1)
    roots = _verify_history(db, vault_id)
    _verify_metadata(db, snapshots, roots, deadline)
    _remaining(deadline)
    return version, snapshots


def _rebuild(db, snapshots, deadline):
    subject_ddl = next(sql for sql in LEDGER_V2_DDL if sql.startswith("CREATE TABLE runtime_dispatch_subjects "))
    attempt_ddl = next(sql for sql in LEDGER_V2_DDL if sql.startswith("CREATE TABLE runtime_attempts "))
    index_ddl = next(sql for sql in LEDGER_V2_DDL if sql.startswith("CREATE INDEX runtime_attempts_execution "))
    db.execute(subject_ddl)
    db.execute("INSERT INTO runtime_dispatch_subjects SELECT vault_id,'node_execution',id,id,NULL,NULL,NULL "
               "FROM runtime_node_executions")
    db.execute("PRAGMA defer_foreign_keys=ON")
    if (db.execute("PRAGMA defer_foreign_keys").fetchone()[0] != 1
            or db.execute("PRAGMA foreign_keys").fetchone()[0] != 1):
        raise CorruptLedger("Deferred foreign key enforcement unavailable")
    _remaining(deadline)
    db.execute("DELETE FROM runtime_attempts")
    if db.execute("SELECT count(*) FROM runtime_attempts").fetchone()[0] != 0:
        raise CorruptLedger("Attempt deletion incomplete")
    db.execute("DROP TABLE runtime_attempts")
    db.execute(attempt_ddl)
    columns, _, _, _, rows = snapshots["runtime_attempts"]
    statement = "INSERT INTO runtime_attempts (" + ",".join(_quote(x) for x in columns) + ",subject_kind,subject_id) VALUES (" + ",".join("?" for _ in range(len(columns) + 2)) + ")"
    execution_index = columns.index("execution_id")
    for row in rows:
        _remaining(deadline)
        db.execute(statement, row + ("node_execution", row[execution_index]))
    db.execute(index_ddl)
    _compare(db, snapshots, deadline)
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise CorruptLedger("Restored database foreign key violation")
    db.execute("INSERT INTO runtime_migrations VALUES ('ledger',2,?)", (LEDGER_V2_SHA256,))
    if _schema_version(db) != 2:
        raise CorruptLedger("Target schema verification failed")
