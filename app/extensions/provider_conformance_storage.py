"""Additive same-store storage for provider conformance history."""

from hashlib import sha256
import re
import sqlite3

from ..domain.refs import canonical_json, uuid_string
from .provider_conformance_contracts import ConformanceError


DDL = (
    """CREATE TABLE provider_conformance_migrations (
 version INTEGER PRIMARY KEY CHECK(version=1),
 checksum TEXT NOT NULL CHECK(length(checksum)=64)
);""",
    """CREATE TABLE provider_conformance_control (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id),
 instance_id TEXT NOT NULL CHECK(length(instance_id)=32),
 origin_digest TEXT NOT NULL CHECK(length(origin_digest)=64),
 run_count INTEGER NOT NULL CHECK(run_count BETWEEN 0 AND 64),
 retained_bytes INTEGER NOT NULL CHECK(retained_bytes BETWEEN 0 AND 67108864),
 last_now_ms INTEGER NOT NULL CHECK(last_now_ms BETWEEN 0 AND 253402300799999)
);""",
    """CREATE TABLE provider_conformance_runs (
 command_id TEXT PRIMARY KEY CHECK(length(command_id)=36),
 vault_id TEXT NOT NULL REFERENCES provider_conformance_control(vault_id),
 request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
 installation_kind TEXT NOT NULL CHECK(installation_kind='extension_installation'),
 installation_id TEXT NOT NULL CHECK(length(installation_id)=36),
 installation_version INTEGER NOT NULL CHECK(installation_version=1),
 installation_sha256 TEXT NOT NULL CHECK(length(installation_sha256)=64),
 run_kind TEXT NOT NULL CHECK(run_kind='provider_conformance_run'),
 intent_version INTEGER NOT NULL CHECK(intent_version=1),
 intent_sha256 TEXT NOT NULL CHECK(length(intent_sha256)=64),
 report_version INTEGER CHECK(report_version=2),
 report_sha256 TEXT CHECK(length(report_sha256)=64),
 state TEXT NOT NULL CHECK(state IN ('pending','matched','mismatch','incomplete')),
 admitted_ms INTEGER NOT NULL CHECK(admitted_ms BETWEEN 0 AND 253402300739999),
 deadline_ms INTEGER NOT NULL CHECK(deadline_ms=admitted_ms+60000),
 finished_ms INTEGER CHECK(finished_ms BETWEEN admitted_ms AND 253402300799999),
 started_sequence INTEGER NOT NULL CHECK(started_sequence>0),
 finished_sequence INTEGER CHECK(finished_sequence>started_sequence),
 pending_reply BLOB NOT NULL CHECK(length(pending_reply) BETWEEN 1 AND 8192),
 terminal_reply BLOB CHECK(length(terminal_reply) BETWEEN 1 AND 8192),
 retained_bytes INTEGER NOT NULL CHECK(retained_bytes BETWEEN 0 AND 1048576),
 FOREIGN KEY(vault_id,installation_kind,installation_id,installation_version,installation_sha256)
 REFERENCES domain_records(vault_id,kind,id,version,sha256),
 FOREIGN KEY(vault_id,run_kind,command_id,intent_version,intent_sha256)
 REFERENCES domain_records(vault_id,kind,id,version,sha256),
 FOREIGN KEY(vault_id,run_kind,command_id,report_version,report_sha256)
 REFERENCES domain_records(vault_id,kind,id,version,sha256),
 FOREIGN KEY(vault_id,started_sequence) REFERENCES api_event_envelopes(vault_id,sequence),
 FOREIGN KEY(vault_id,finished_sequence) REFERENCES api_event_envelopes(vault_id,sequence),
 CHECK((state='pending' AND report_version IS NULL AND report_sha256 IS NULL
 AND finished_ms IS NULL AND finished_sequence IS NULL AND terminal_reply IS NULL AND retained_bytes=0)
 OR (state!='pending' AND report_version IS NOT NULL AND report_sha256 IS NOT NULL
 AND finished_ms IS NOT NULL AND finished_sequence IS NOT NULL AND terminal_reply IS NOT NULL))
);""",
    """CREATE UNIQUE INDEX provider_conformance_one_pending
 ON provider_conformance_runs(vault_id,installation_id) WHERE state='pending';""",
)
CHECKSUM_V1 = sha256(canonical_json(list(DDL))).hexdigest()
_NAMES = {"provider_conformance_migrations", "provider_conformance_control",
          "provider_conformance_runs", "provider_conformance_one_pending"}
_AUTO_INDEXES = {"sqlite_autoindex_provider_conformance_control_1",
                 "sqlite_autoindex_provider_conformance_runs_1"}
_TABLES = {"provider_conformance_migrations", "provider_conformance_control",
           "provider_conformance_runs"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _fail():
    raise ConformanceError("unavailable")


def _normalize(sql):
    return " ".join(sql.rstrip(";").split())


def _objects(db):
    placeholders = ",".join("?" for _ in _TABLES)
    return list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name LIKE 'provider_conformance_%' OR tbl_name IN (" + placeholders + ") "
        "ORDER BY name", tuple(sorted(_TABLES))))


def _install_statement(db, statement, arguments=()):
    return db.execute(statement, arguments)


def install(db, *, verified_empty=False):
    if type(db) is not sqlite3.Connection or not db.in_transaction:
        _fail()
    objects = _objects(db)
    if objects:
        verify_layout(db)
        return
    if (db.execute("SELECT 1 FROM domain_records WHERE kind='provider_conformance_run' LIMIT 1").fetchone()
            or db.execute("SELECT 1 FROM api_event_envelopes WHERE event_type IN "
                          "('provider.conformance_started','provider.conformance_completed') "
                          "LIMIT 1").fetchone()):
        _fail()
    source = list(db.execute("SELECT vault_id,instance_id,origin_digest "
                             "FROM deployment_prepare_control LIMIT 2"))
    if not source and verified_empty is True:
        # Composition precedes deployment startup reconciliation.  The exact same-store
        # owner binding already exists and is the authority from which prepare later creates
        # its identical control row; no caller profile values are accepted here.
        source = list(db.execute("SELECT vault_id,instance_id,origin_digest "
                                 "FROM owner_auth_control LIMIT 2"))
    if len(source) != 1:
        _fail()
    row = source[0]
    try:
        uuid_string(row["vault_id"])
        if (type(row["instance_id"]) is not str or re.fullmatch(r"[0-9a-f]{32}", row["instance_id"]) is None
                or type(row["origin_digest"]) is not str or _HASH.fullmatch(row["origin_digest"]) is None):
            _fail()
    except (ValueError, TypeError, KeyError):
        _fail()
    _install_statement(db, "SAVEPOINT provider_conformance_install")
    try:
        for statement in DDL:
            _install_statement(db, statement)
        _install_statement(db, "INSERT INTO provider_conformance_migrations VALUES (1,?)",
                           (CHECKSUM_V1,))
        _install_statement(db, "INSERT INTO provider_conformance_control VALUES (1,?,?,?,?,?,?)",
                           (row["vault_id"], row["instance_id"], row["origin_digest"], 0, 0, 0))
        verify_layout(db)
        _install_statement(db, "RELEASE provider_conformance_install")
    except BaseException:
        for statement in ("ROLLBACK TO provider_conformance_install",
                          "RELEASE provider_conformance_install"):
            try:
                _install_statement(db, statement)
            except BaseException:
                pass
        raise


def _strict_scalar(value, kind):
    return type(value) is kind


def verify_layout(db):
    if type(db) is not sqlite3.Connection or not db.in_transaction:
        _fail()
    objects = _objects(db)
    if {row["name"] for row in objects} != _NAMES | _AUTO_INDEXES or len(objects) != 6:
        _fail()
    expected = {}
    for statement in DDL:
        match = re.match(r"CREATE (TABLE|UNIQUE INDEX) ([a-z0-9_]+)", statement)
        expected[match.group(2)] = ("table" if match.group(1) == "TABLE" else "index", _normalize(statement))
    for row in objects:
        if row["name"] in _AUTO_INDEXES:
            if row["type"] != "index" or row["tbl_name"] not in _TABLES or row["sql"] is not None:
                _fail()
        elif (row["type"] != expected[row["name"]][0]
                or _normalize(row["sql"]) != expected[row["name"]][1]):
            _fail()
    expected_indexes = {
        "provider_conformance_migrations": set(),
        "provider_conformance_control": {("sqlite_autoindex_provider_conformance_control_1", 1, "u", 0)},
        "provider_conformance_runs": {("provider_conformance_one_pending", 1, "c", 1),
            ("sqlite_autoindex_provider_conformance_runs_1", 1, "pk", 0)},
    }
    for table, wanted in expected_indexes.items():
        actual = {(row[1], row[2], row[3], row[4]) for row in db.execute(
            "PRAGMA index_list('" + table + "')")}
        if actual != wanted:
            _fail()
    expected_fks = {
        "provider_conformance_migrations": (),
        "provider_conformance_control": (
            (0, 0, "domain_vault", "vault_id", "vault_id", "NO ACTION", "NO ACTION", "NONE"),),
        "provider_conformance_runs": (
            (0, 0, "api_event_envelopes", "vault_id", "vault_id", "NO ACTION", "NO ACTION", "NONE"),
            (0, 1, "api_event_envelopes", "finished_sequence", "sequence", "NO ACTION", "NO ACTION", "NONE"),
            (1, 0, "api_event_envelopes", "vault_id", "vault_id", "NO ACTION", "NO ACTION", "NONE"),
            (1, 1, "api_event_envelopes", "started_sequence", "sequence", "NO ACTION", "NO ACTION", "NONE"),
            (2, 0, "domain_records", "vault_id", "vault_id", "NO ACTION", "NO ACTION", "NONE"),
            (2, 1, "domain_records", "run_kind", "kind", "NO ACTION", "NO ACTION", "NONE"),
            (2, 2, "domain_records", "command_id", "id", "NO ACTION", "NO ACTION", "NONE"),
            (2, 3, "domain_records", "report_version", "version", "NO ACTION", "NO ACTION", "NONE"),
            (2, 4, "domain_records", "report_sha256", "sha256", "NO ACTION", "NO ACTION", "NONE"),
            (3, 0, "domain_records", "vault_id", "vault_id", "NO ACTION", "NO ACTION", "NONE"),
            (3, 1, "domain_records", "run_kind", "kind", "NO ACTION", "NO ACTION", "NONE"),
            (3, 2, "domain_records", "command_id", "id", "NO ACTION", "NO ACTION", "NONE"),
            (3, 3, "domain_records", "intent_version", "version", "NO ACTION", "NO ACTION", "NONE"),
            (3, 4, "domain_records", "intent_sha256", "sha256", "NO ACTION", "NO ACTION", "NONE"),
            (4, 0, "domain_records", "vault_id", "vault_id", "NO ACTION", "NO ACTION", "NONE"),
            (4, 1, "domain_records", "installation_kind", "kind", "NO ACTION", "NO ACTION", "NONE"),
            (4, 2, "domain_records", "installation_id", "id", "NO ACTION", "NO ACTION", "NONE"),
            (4, 3, "domain_records", "installation_version", "version", "NO ACTION", "NO ACTION", "NONE"),
            (4, 4, "domain_records", "installation_sha256", "sha256", "NO ACTION", "NO ACTION", "NONE"),
            (5, 0, "provider_conformance_control", "vault_id", "vault_id", "NO ACTION", "NO ACTION", "NONE"),
        ),
    }
    for table, wanted in expected_fks.items():
        if tuple(tuple(row) for row in db.execute(
                "PRAGMA foreign_key_list('" + table + "')")) != wanted:
            _fail()
    migrations = list(db.execute("SELECT version,checksum,typeof(version),typeof(checksum) "
                                 "FROM provider_conformance_migrations LIMIT 2"))
    if len(migrations) != 1 or tuple(migrations[0]) != (1, CHECKSUM_V1, "integer", "text"):
        _fail()
    control = list(db.execute("SELECT *,typeof(singleton),typeof(vault_id),typeof(instance_id),"
        "typeof(origin_digest),typeof(run_count),typeof(retained_bytes),typeof(last_now_ms) "
        "FROM provider_conformance_control LIMIT 2"))
    if len(control) != 1:
        _fail()
    row = control[0]
    values = tuple(row)
    if (values[-7:] != ("integer", "text", "text", "text", "integer", "integer", "integer")
            or row["singleton"] != 1 or type(row["run_count"]) is not int
            or type(row["retained_bytes"]) is not int or type(row["last_now_ms"]) is not int
            or not 0 <= row["run_count"] <= 64 or not 0 <= row["retained_bytes"] <= 67108864
            or not 0 <= row["last_now_ms"] <= 253402300799999):
        _fail()
    deployment = list(db.execute("SELECT vault_id,instance_id,origin_digest "
                                 "FROM deployment_prepare_control LIMIT 2"))
    binding = deployment
    if not binding:
        binding = list(db.execute("SELECT vault_id,instance_id,origin_digest "
                                  "FROM owner_auth_control LIMIT 2"))
    if (len(binding) != 1 or (row["vault_id"], row["instance_id"], row["origin_digest"])
            != tuple(binding[0])):
        _fail()
    aggregate = db.execute("SELECT count(*),coalesce(sum(retained_bytes),0) "
                           "FROM provider_conformance_runs").fetchone()
    if aggregate[0] != row["run_count"] or aggregate[1] != row["retained_bytes"] or aggregate[0] > 64:
        _fail()
    if db.execute("SELECT count(*) FROM provider_conformance_runs").fetchone()[0] > 64:
        _fail()
    for table in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if table[0] in {"provider_conformance_migrations", "provider_conformance_control",
                        "provider_conformance_runs"}:
            continue
        for foreign in db.execute("PRAGMA foreign_key_list('" + table[0].replace("'", "''") + "')"):
            if foreign[2] in {"provider_conformance_migrations", "provider_conformance_control",
                              "provider_conformance_runs"}:
                _fail()
