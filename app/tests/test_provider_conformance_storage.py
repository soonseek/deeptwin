import sqlite3
from uuid import uuid4

import pytest

from app.domain.refs import canonical_json
from app.domain.store import _writer
from app.extensions.provider_conformance_contracts import ConformanceError
from app.extensions import provider_conformance_storage as storage_module
from app.extensions.provider_conformance_storage import CHECKSUM_V1, DDL, install, verify_layout
from app.tests.provider_conformance_fixture import staged_conformance_app


def _db(*, deployment=True):
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("CREATE TABLE domain_vault(vault_id TEXT PRIMARY KEY)")
    db.execute("CREATE TABLE domain_records(vault_id TEXT,kind TEXT,id TEXT,version INTEGER,sha256 TEXT,"
               "PRIMARY KEY(vault_id,kind,id,version,sha256))")
    db.execute("CREATE TABLE api_event_envelopes(vault_id TEXT,sequence INTEGER,event_id TEXT,event_type TEXT,"
               "PRIMARY KEY(vault_id,sequence))")
    db.execute("CREATE TABLE deployment_prepare_control(vault_id TEXT,instance_id TEXT,origin_digest TEXT)")
    db.execute("CREATE TABLE owner_auth_control(vault_id TEXT,instance_id TEXT,origin_digest TEXT)")
    vault = str(uuid4())
    db.execute("INSERT INTO domain_vault VALUES (?)", (vault,))
    db.execute("INSERT INTO owner_auth_control VALUES (?,?,?)", (vault, "1" * 32, "2" * 64))
    if deployment:
        db.execute("INSERT INTO deployment_prepare_control VALUES (?,?,?)", (vault, "1" * 32, "2" * 64))
    db.execute("BEGIN IMMEDIATE")
    return db, vault


def test_literal_layout_checksum_and_owner_bound_empty_control_are_exact():
    assert len(DDL) == 4 and len(canonical_json(list(DDL))) == 3306
    assert CHECKSUM_V1 == "c8557c5bd0ce04379531434e7edba156662011f6a12321a9e28ded8f646d40f5"
    db, vault = _db()
    install(db)
    verify_layout(db)
    assert tuple(db.execute("SELECT * FROM provider_conformance_migrations").fetchone()) == (1, CHECKSUM_V1)
    assert tuple(db.execute("SELECT * FROM provider_conformance_control").fetchone()) == (
        1, vault, "1" * 32, "2" * 64, 0, 0, 0)


def test_install_is_atomic_and_refuses_partial_or_alien_family():
    db, _ = _db()
    db.execute(DDL[0])
    with pytest.raises(ConformanceError) as caught:
        install(db)
    assert caught.value.code == "unavailable"
    assert db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'provider_conformance_%'").fetchone()[0] == 1


def test_layout_verifier_rejects_extra_index_trigger_and_counter_drift():
    for mutation in ("CREATE INDEX provider_conformance_alien ON provider_conformance_runs(state)",
                     "CREATE TRIGGER provider_conformance_alien AFTER INSERT ON provider_conformance_runs BEGIN SELECT 1; END",
                     "CREATE INDEX arbitrary_extra_index ON provider_conformance_runs(state)",
                     "CREATE TRIGGER arbitrary_extra_trigger AFTER INSERT ON provider_conformance_runs BEGIN SELECT 1; END"):
        db, _ = _db(); install(db); db.execute(mutation)
        with pytest.raises(ConformanceError):
            verify_layout(db)
    db, _ = _db(); install(db)
    db.execute("UPDATE provider_conformance_control SET run_count=1")
    with pytest.raises(ConformanceError):
        verify_layout(db)


def test_empty_install_rejects_orphan_records_and_events():
    for statement, arguments in (
        ("INSERT INTO domain_records VALUES (?,?,?,?,?)",
         (str(uuid4()), "provider_conformance_run", str(uuid4()), 1, "a" * 64)),
        ("INSERT INTO api_event_envelopes VALUES (?,?,?)",
         (str(uuid4()), 1, str(uuid4()))),
    ):
        db, vault = _db()
        if "domain_records" in statement:
            arguments = (vault, *arguments[1:])
        else:
            arguments = (vault, arguments[1], arguments[2])
            statement = "INSERT INTO api_event_envelopes VALUES (?,?,?,?)"
            arguments = (*arguments, "provider.conformance_started")
        db.execute(statement, arguments)
        with pytest.raises(ConformanceError, match="^unavailable$"):
            install(db)


@pytest.mark.parametrize("fault_index", range(6))
def test_each_install_create_and_control_write_rolls_back(fault_index, monkeypatch):
    db, _ = _db()
    actual = storage_module._install_statement
    reached = 0

    def execute(connection, statement, arguments=()):
        nonlocal reached
        if statement.startswith("CREATE ") or statement.startswith("INSERT "):
            if reached == fault_index:
                raise sqlite3.OperationalError("controlled install write")
            reached += 1
        return actual(connection, statement, arguments)

    monkeypatch.setattr(storage_module, "_install_statement", execute)
    with pytest.raises(sqlite3.OperationalError, match="controlled install write"):
        install(db)
    assert db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE "
                      "'provider_conformance_%'").fetchone()[0] == 0


def test_install_cleanup_preserves_primary_and_attempts_release(monkeypatch):
    db, _ = _db()
    actual = storage_module._install_statement
    primary = KeyboardInterrupt("primary")
    cleanup = []

    def execute(connection, statement, arguments=()):
        if statement == DDL[0]:
            raise primary
        if statement.startswith("ROLLBACK TO") or statement.startswith("RELEASE"):
            cleanup.append(statement)
            raise SystemExit("cleanup")
        return actual(connection, statement, arguments)

    monkeypatch.setattr(storage_module, "_install_statement", execute)
    with pytest.raises(KeyboardInterrupt) as caught:
        install(db)
    assert caught.value is primary
    assert cleanup == ["ROLLBACK TO provider_conformance_install",
                       "RELEASE provider_conformance_install"]


def test_verified_empty_startup_fallback_is_narrow_and_later_requires_deployment_equality():
    db, vault = _db(deployment=False)
    with pytest.raises(ConformanceError):
        install(db)
    install(db, verified_empty=True)
    verify_layout(db)
    db.execute("INSERT INTO deployment_prepare_control VALUES (?,?,?)",
               (vault, "1" * 32, "2" * 64))
    verify_layout(db)
    db.execute("UPDATE deployment_prepare_control SET origin_digest=?", ("3" * 64,))
    with pytest.raises(ConformanceError):
        verify_layout(db)


def test_additive_install_preserves_every_rowid_and_byte_in_real_populated_store(
        tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            old_tables = tuple(row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'provider_conformance_%' ORDER BY name"))

            def snapshot():
                return {name: tuple(tuple(row) for row in db.execute(
                    'SELECT rowid,* FROM "' + name.replace('"', '""') + '" ORDER BY rowid'))
                    for name in old_tables}

            before = snapshot()
            assert before["domain_records"] and before["api_event_envelopes"]
            assert before["deployment_prepare_requests"]
            db.execute("DROP TABLE provider_conformance_runs")
            db.execute("DROP TABLE provider_conformance_control")
            db.execute("DROP TABLE provider_conformance_migrations")
            assert snapshot() == before
            install(db)
            verify_layout(db)
            assert snapshot() == before
