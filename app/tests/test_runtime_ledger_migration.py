"""Test-owned historical v1 stores; no actual user database is opened."""
import importlib.util
import os
import sqlite3

import pytest

from app.domain.store import DomainStore
from app.storage import Store
from app.services.owner_admission import ServingLock


def historical(tmp_path):
    from hashlib import sha256
    from app.runtime.ledger_schema import LEDGER_V1_DDL
    legacy = Store(tmp_path / "vault")
    domain = DomainStore(legacy)
    vault = domain.initialize_vault().genesis.id
    original_digest = "b761957cfb9c21a63f928ba5c7d173ba7a4804d0dc72b240fdade0bc860ad118"
    assert sha256("\n".join(LEDGER_V1_DDL).encode()).hexdigest() == original_digest
    with sqlite3.connect(legacy.path) as db:
        for statement in LEDGER_V1_DDL:
            db.execute(statement)
        db.execute("INSERT INTO runtime_migrations VALUES ('ledger',1,?)", (original_digest,))
        db.execute("INSERT INTO runtime_control(singleton,vault_id,last_clock_ms) VALUES (1,?,0)", (vault,))
    ServingLock(legacy.path.parent, expected_uid=os.geteuid(), expected_gid=os.getegid()).close()
    return legacy, domain, vault


def migrate(legacy, vault):
    from app.operations.runtime_ledger_migrate import migrate_runtime_ledger_v1_to_v2
    return migrate_runtime_ledger_v1_to_v2(legacy.path.parent, expected_uid=os.geteuid(),
        expected_gid=os.getegid(), expected_vault_id=vault,
        expected_v1_digest="b761957cfb9c21a63f928ba5c7d173ba7a4804d0dc72b240fdade0bc860ad118")


def test_offline_operation_exists():
    assert importlib.util.find_spec("app.operations.runtime_ledger_migrate") is not None


def test_empty_v1_actual_commit_and_idempotent_verification(tmp_path):
    legacy, domain, vault = historical(tmp_path)
    result = migrate(legacy, vault)
    assert result == {"schema_version": "runtime-ledger-migration-v1", "vault_id": vault,
        "from_version": 1, "to_version": 2, "state": "migrated",
        "v1_sha256": "b761957cfb9c21a63f928ba5c7d173ba7a4804d0dc72b240fdade0bc860ad118",
        "v2_sha256": "3131be5d54e0ffdfcf980353d04b81428f27e64711f4762993e63915deeda255",
        "attempts": 0, "executions": 0}
    assert migrate(legacy, vault)["state"] == "already_current"
    from app.runtime.ledger import RuntimeLedger
    RuntimeLedger(domain)


def v1_producer(monkeypatch):
    """Install the historical tuple before the normal producer's first ledger open."""
    from app.runtime.ledger import RuntimeLedger
    from app.runtime.ledger_schema import LEDGER_V1_DDL, LEDGER_V1_SHA256
    original = RuntimeLedger._install_schema

    def install(self):
        with self._transaction(write=True) as db:
            present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "runtime_attempts" not in present:
                for statement in LEDGER_V1_DDL:
                    if statement.startswith("CREATE TABLE runtime_migrations ") and "runtime_migrations" in present:
                        continue
                    db.execute(statement)
                db.execute("INSERT INTO runtime_migrations VALUES ('ledger',1,?)", (LEDGER_V1_SHA256,))
                db.execute("INSERT INTO runtime_control(singleton,vault_id,last_clock_ms) VALUES (1,?,0)",
                           (self.vault_id,))
        original(self)
    monkeypatch.setattr(RuntimeLedger, "_install_schema", install)


def lock_for(legacy):
    ServingLock(legacy.path.parent, expected_uid=os.geteuid(), expected_gid=os.getegid()).close()


def logical(legacy):
    with sqlite3.connect(legacy.path) as db:
        return list(db.iterdump())


def migration_queries(monkeypatch):
    from app.operations import runtime_ledger_migrate as operation
    original = operation._open
    queries = []
    def traced(handles, deadline):
        db = original(handles, deadline)
        db.set_trace_callback(queries.append)
        return db
    monkeypatch.setattr(operation, "_open", traced)
    return queries


def assert_no_history_writes(queries):
    assert not any(query.lstrip().upper().startswith(
        ("CREATE ", "INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "REPLACE "))
        for query in queries)


@pytest.mark.parametrize("reference", ["result", "approval"])
@pytest.mark.parametrize("corruption", ["wrong_sha", "missing", "null_kind", "null_id",
                                        "null_version", "null_sha256"])
def test_tool_call_refs_require_complete_exact_targets_before_rebuild(
        tmp_path, monkeypatch, reference, corruption):
    from app.tests.test_runtime_ledger import opened, prepared, identifier, immutable, tool_call_spec
    from app.runtime.ledger_migrations import LedgerMigrationError
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    run, _, _, attempt, _ = prepared(value)
    approval = immutable(value.domain, value.roots, "action_approval")
    spec = tool_call_spec(value, attempt.attempt_id, effect_class="external_reversible",
                          approval_ref=approval)
    value.ledger.record_tool_call(identifier(), spec)
    value.ledger.settle_tool_call(identifier(), spec.tool_call_id, outcome="succeeded",
                                  result_ref=run.manifest_ref)
    if corruption == "wrong_sha":
        column, replacement = "sha256", "0" * 64
    elif corruption == "missing":
        column, replacement = "id", identifier()
    else:
        column, replacement = corruption.removeprefix("null_"), None
    with sqlite3.connect(value.legacy.path) as db:
        db.execute(f"UPDATE runtime_tool_calls SET {reference}_{column}=?", (replacement,))
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    lock_for(value.legacy)
    before = logical(value.legacy)
    queries = migration_queries(monkeypatch)
    with pytest.raises(LedgerMigrationError, match="^maintenance_required$"):
        migrate(value.legacy, value.domain.vault_id)
    assert_no_history_writes(queries)
    assert logical(value.legacy) == before


def test_complete_tool_call_targets_are_preserved_and_verified_on_repeat(tmp_path, monkeypatch):
    from app.tests.test_runtime_ledger import opened, prepared, identifier, immutable, tool_call_spec
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    run, _, _, attempt, _ = prepared(value)
    approval = immutable(value.domain, value.roots, "action_approval")
    spec = tool_call_spec(value, attempt.attempt_id, effect_class="external_reversible",
                          approval_ref=approval)
    value.ledger.record_tool_call(identifier(), spec)
    before = value.ledger.settle_tool_call(identifier(), spec.tool_call_id,
                                          outcome="succeeded", result_ref=run.manifest_ref)
    lock_for(value.legacy)
    assert migrate(value.legacy, value.domain.vault_id)["state"] == "migrated"
    assert value.ledger.tool_calls_for_attempt(attempt.attempt_id) == [before]
    assert migrate(value.legacy, value.domain.vault_id)["state"] == "already_current"


def test_populated_v1_commit_children_checkpoint_and_replay(tmp_path, monkeypatch):
    from app.tests.test_runtime_ledger import opened, prepared, identifier, send, result
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    run, execution, owner, attempt, before = prepared(value)
    checkpoint = value.ledger.write_checkpoint(identifier(), run.run_id, "migration", b"exact\x00cursor",
                                                expected_revision=0)
    lock_for(value.legacy)
    with sqlite3.connect(value.legacy.path) as db:
        rows = db.execute("SELECT * FROM runtime_attempts").fetchall()
        children = db.execute("SELECT * FROM runtime_attempt_refs").fetchall()
    assert migrate(value.legacy, value.domain.vault_id)["attempts"] == 1
    assert value.ledger.get_attempt(attempt.attempt_id) == before
    assert value.ledger.read_checkpoint(run.run_id, "migration") == checkpoint
    with sqlite3.connect(value.legacy.path) as db:
        cols = [row[1] for row in db.execute("PRAGMA table_info(runtime_attempts)") if row[1] not in ("subject_kind", "subject_id")]
        assert db.execute("SELECT " + ",".join(cols) + " FROM runtime_attempts").fetchall() == rows
        assert db.execute("SELECT * FROM runtime_attempt_refs").fetchall() == children
    send(value, attempt, owner)
    assert value.ledger.accept_result(identifier(), result(value, attempt.attempt_id))["classification"] == "accepted"


@pytest.mark.parametrize("stage", ["CREATE TABLE runtime_dispatch_subjects", "INSERT INTO runtime_dispatch_subjects",
    "DELETE FROM runtime_attempts", "DROP TABLE runtime_attempts", "CREATE TABLE runtime_attempts",
    "INSERT INTO runtime_attempts (", "CREATE INDEX runtime_attempts_execution", "INSERT INTO runtime_migrations"])
def test_each_rebuild_stage_rolls_back_exact_v1(tmp_path, monkeypatch, stage):
    from app.tests.test_runtime_ledger import opened, prepared
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    prepared(value)
    lock_for(value.legacy)
    before = logical(value.legacy)
    original = operation._open

    def failing_open(handles, deadline):
        db = original(handles, deadline)
        seen = [False]
        def trace(sql):
            if sql.startswith(stage):
                seen[0] = True
            elif seen[0]:
                db.set_trace_callback(None)
                db.interrupt()
        db.set_trace_callback(trace)
        return db
    monkeypatch.setattr(operation, "_open", failing_open)
    with pytest.raises(LedgerMigrationError) as error:
        migrate(value.legacy, value.domain.vault_id)
    assert error.value.code == "maintenance_required"
    assert logical(value.legacy) == before


def test_capture_and_bound_checkpoint_survive_actual_v1_migration(tmp_path, monkeypatch):
    from app.tests.test_worker_response_capture import build_subject, wire, dispatch, PAYLOAD
    from app.runtime.ledger import RuntimeLedger
    from app.runtime.worker_response_capture import _lookup_response_capture
    from app.tests.test_runtime_ledger import identifier
    v1_producer(monkeypatch)
    value = build_subject(tmp_path)
    thread, failures = wire(value, monkeypatch)
    dispatch(value)
    thread.join(5)
    assert not thread.is_alive() and failures == []
    before = _lookup_response_capture(value.ledger, value.permit.command_id)
    attempt = value.ledger.get_attempt(value.permit.attempt_id)
    value.ledger.renew_lease(identifier(), value.permit.attempt_id, value.permit.owner,
                            expected_revision=attempt["revision"], lease_duration_ms=3000)
    attempt = value.ledger.get_attempt(value.permit.attempt_id)
    execution = value.ledger.get_execution(attempt["spec"]["execution_id"])
    run_id = execution["spec"]["run_id"]
    saved = value.ledger.write_checkpoint(identifier(), run_id, "captured", b"captured\x00",
        expected_revision=0, attempt_id=value.permit.attempt_id)
    lock_for(value.legacy)
    vault = value.domain.vault_id
    def denied(*args, **kwargs):
        raise AssertionError("offline operation invoked a live/physical hook")
    with monkeypatch.context() as m:
        m.setattr(Store, "__init__", denied)
        m.setattr(DomainStore, "__init__", denied)
        m.setattr(DomainStore, "_check_graph", denied)
        m.setattr(RuntimeLedger, "__init__", denied)
        assert migrate(value.legacy, vault)["attempts"] == 1
    assert _lookup_response_capture(value.ledger, value.permit.command_id) == before
    assert value.ledger.read_checkpoint(run_id, "captured") == saved


@pytest.mark.parametrize("mutation", ["UPDATE runtime_control SET vault_id='foreign'",
    "UPDATE runtime_migrations SET sha256='private-secret' WHERE component='ledger'",
    "CREATE TABLE extra_child(vault_id,attempt_id,FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id) ON DELETE CASCADE)",
    "CREATE TRIGGER private_secret AFTER DELETE ON runtime_attempts BEGIN SELECT 1; END"])
def test_preflight_corruption_is_sanitized_and_unchanged(tmp_path, mutation):
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute(mutation)
    before = logical(legacy)
    with pytest.raises(LedgerMigrationError) as error:
        migrate(legacy, vault)
    assert str(error.value) == "maintenance_required"
    assert logical(legacy) == before


def test_committed_but_unverified_is_outcome_unknown_then_verifiable(tmp_path, monkeypatch):
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    original = operation._open
    count = [0]
    def fail_reopen(handles, deadline):
        count[0] += 1
        if count[0] == 2:
            raise OSError("private-path")
        return original(handles, deadline)
    monkeypatch.setattr(operation, "_open", fail_reopen)
    with pytest.raises(LedgerMigrationError, match="^outcome_unknown$"):
        migrate(legacy, vault)
    monkeypatch.setattr(operation, "_open", original)
    assert migrate(legacy, vault)["state"] == "already_current"


@pytest.mark.parametrize("target", ["owner-auth.lock", "intake.sqlite3"])
def test_missing_required_files_are_never_created(tmp_path, target):
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    (legacy.path.parent / target).unlink()
    with pytest.raises(LedgerMigrationError, match="^unavailable$"):
        migrate(legacy, vault)
    assert not (legacy.path.parent / target).exists()


def test_capacity_before_parent_deletion(tmp_path, monkeypatch):
    from app.runtime import ledger_migrations as migration
    legacy, _, vault = historical(tmp_path)
    before = logical(legacy)
    monkeypatch.setattr(migration, "MAX_ROWS", 1)
    with pytest.raises(migration.LedgerMigrationError, match="^capacity_exceeded$"):
        migrate(legacy, vault)
    assert logical(legacy) == before


def growth_fixture(tmp_path, monkeypatch):
    from app.tests.test_runtime_ledger import (
        opened, prepared, identifier, execution_spec, immutable, tool_call_spec)
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    run, _, _, attempt, _ = prepared(value)
    # Every execution adds a subject, including this one without an attempt.
    value.ledger.create_execution(identifier(), execution_spec(value, run.run_id))
    approval = immutable(value.domain, value.roots, "action_approval", content={"fixture": "한"})
    call = tool_call_spec(value, attempt.attempt_id, effect_class="external_reversible",
                          approval_ref=approval)
    value.ledger.record_tool_call(identifier(), call)
    # Now every domain record in this tiny fixture is actually reachable.
    value.ledger.settle_tool_call(identifier(), call.tool_call_id, outcome="succeeded",
                                  result_ref=value.refs.result)
    lock_for(value.legacy)
    return value


def growth_fixture_totals(legacy):
    """Independent tiny-fixture oracle: Python scalar counts, no migration sizing helpers."""
    rows = size = 0
    with sqlite3.connect(legacy.path) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
            "AND (name GLOB 'runtime_*' OR name='sqlite_sequence')")]
        tables += ["domain_migrations", "domain_vault", "domain_records", "domain_edges",
                   "domain_record_blobs", "domain_blobs"]
        for table in tables:
            projection = "rowid,*" if table == "runtime_attempts" else "*"
            for row in db.execute(f'SELECT {projection} FROM "{table}"'):
                rows += 1
                for scalar in row:
                    if scalar is not None:
                        size += (8 if isinstance(scalar, (int, float)) else
                                 len(scalar.encode("utf-8")) if isinstance(scalar, str) else len(scalar))
    return rows, size


@pytest.mark.parametrize("limit,index,growth", [("MAX_ROWS", 0, 3), ("MAX_BYTES", 1, 372)])
@pytest.mark.parametrize("boundary", ["source_exact", "target_minus_one"])
def test_projected_target_capacity_refuses_before_any_write(
        tmp_path, monkeypatch, limit, index, growth, boundary):
    from app.runtime import ledger_migrations as migration
    value = growth_fixture(tmp_path, monkeypatch)
    before = logical(value.legacy)
    source = growth_fixture_totals(value.legacy)[index]
    cap = source if boundary == "source_exact" else source + growth - 1
    monkeypatch.setattr(migration, limit, cap)
    queries = migration_queries(monkeypatch)
    with pytest.raises(migration.LedgerMigrationError, match="^capacity_exceeded$"):
        migrate(value.legacy, value.domain.vault_id)
    assert_no_history_writes(queries)
    assert logical(value.legacy) == before


@pytest.mark.parametrize("limit,index,growth", [("MAX_ROWS", 0, 3), ("MAX_BYTES", 1, 372)])
def test_projected_target_exact_fit_and_v2_verify_only_capacity(
        tmp_path, monkeypatch, limit, index, growth):
    from app.runtime import ledger_migrations as migration
    value = growth_fixture(tmp_path, monkeypatch)
    source_rows, source_bytes = growth_fixture_totals(value.legacy)
    # Two UUID node subjects: 2*(36+14+36+36), one attempt: 14+36,
    # migration row: len('ledger') + integer(8) + digest(64) = 372 bytes.
    # The subjects and migration row add three rows; attempts retain their rowid.
    target = (source_rows, source_bytes)[index] + growth
    monkeypatch.setattr(migration, limit, target)
    assert migrate(value.legacy, value.domain.vault_id)["state"] == "migrated"
    assert growth_fixture_totals(value.legacy) == (source_rows + 3, source_bytes + 372)
    before = logical(value.legacy)
    queries = migration_queries(monkeypatch)
    assert migrate(value.legacy, value.domain.vault_id)["state"] == "already_current"
    assert_no_history_writes(queries)
    assert logical(value.legacy) == before
    queries.clear()
    monkeypatch.setattr(migration, limit, target - 1)
    with pytest.raises(migration.LedgerMigrationError, match="^capacity_exceeded$"):
        migrate(value.legacy, value.domain.vault_id)
    assert_no_history_writes(queries)
    assert logical(value.legacy) == before


@pytest.mark.parametrize("cause", ["rows", "bytes", "utf8"])
def test_real_fixed_limits_are_sized_in_sql_before_payload_reads(tmp_path, monkeypatch, cause):
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        if cause == "rows":
            db.execute("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100001) "
                       "INSERT INTO runtime_public_events(vault_id,event_type,object_kind,object_id,payload,payload_digest,at_ms) "
                       "SELECT ?,'event','kind','id',X'7B7D','digest',0 FROM n", (vault,))
        else:
            payload = "zeroblob(67108865)" if cause == "bytes" else "replace(hex(zeroblob(12000000)),'0','한')"
            db.execute("INSERT INTO runtime_public_events(vault_id,event_type,object_kind,object_id,payload,payload_digest,at_ms) "
                       f"VALUES (?,'event','kind','id',{payload},'digest',0)", (vault,))
    original = operation._open
    queries = []
    def traced(handles, deadline):
        db = original(handles, deadline)
        db.set_trace_callback(queries.append)
        return db
    monkeypatch.setattr(operation, "_open", traced)
    with pytest.raises(LedgerMigrationError, match="^capacity_exceeded$"):
        migrate(legacy, vault)
    assert not any(q.startswith('SELECT "sequence","vault_id"') for q in queries)
    assert not any(q.startswith("DELETE FROM runtime_attempts") for q in queries)


def test_deadline_before_transaction_does_not_reset_and_releases_lock(tmp_path, monkeypatch):
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    now = [100.0]
    monkeypatch.setattr(operation.time, "monotonic", lambda: now[0])
    original = operation._open
    def expired(handles, deadline):
        now[0] = 130.01
        return original(handles, deadline)
    monkeypatch.setattr(operation, "_open", expired)
    with pytest.raises(LedgerMigrationError, match="^deadline_exceeded$"):
        migrate(legacy, vault)
    lock_for(legacy)


@pytest.mark.parametrize("name", ["owner-auth.lock", "intake.sqlite3", "intake.sqlite3-wal",
                                 "intake.sqlite3-shm", "intake.sqlite3-journal"])
def test_unsafe_modes_are_not_repaired(tmp_path, name):
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    path = legacy.path.parent / name
    if not path.exists():
        path.touch(mode=0o600)
    path.chmod(0o640)
    with pytest.raises(LedgerMigrationError, match="^unavailable$"):
        migrate(legacy, vault)
    assert path.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("target", ["owner-auth.lock", "intake.sqlite3"])
def test_substitution_after_lock_denies_before_transaction(tmp_path, monkeypatch, target):
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    original = operation._open
    def substituted(handles, deadline):
        path = legacy.path.parent / target
        path.rename(path.with_suffix(".saved"))
        path.touch(mode=0o600)
        return original(handles, deadline)
    monkeypatch.setattr(operation, "_open", substituted)
    with pytest.raises(LedgerMigrationError, match="^unavailable$"):
        migrate(legacy, vault)


@pytest.mark.parametrize("kind", ["serving", "writer"])
def test_real_process_exclusion_and_direct_writer_contention(tmp_path, kind):
    import subprocess
    import sys
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    script = ("import os,sys; from app.services.owner_admission import ServingLock; "
              "lock=ServingLock(sys.argv[1],expected_uid=os.geteuid(),expected_gid=os.getegid(),create=False); "
              "print('ready',flush=True); sys.stdin.readline(); lock.close()") if kind == "serving" else (
              "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute('BEGIN IMMEDIATE'); "
              "print('ready',flush=True); sys.stdin.readline(); db.rollback(); db.close()")
    process = subprocess.Popen([sys.executable, "-B", "-c", script,
        str(legacy.path.parent if kind == "serving" else legacy.path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(LedgerMigrationError, match="^busy$"):
            migrate(legacy, vault)
    finally:
        process.communicate("done\n", timeout=10)
    assert process.returncode == 0
    assert migrate(legacy, vault)["state"] == "migrated"


@pytest.mark.parametrize("control", ["omit_parent", "rename_rebuild"])
def test_real_deferred_commit_rejects_missing_parent_and_rename_control(tmp_path, monkeypatch, control):
    import time
    from app.tests.test_runtime_ledger import opened, prepared
    from app.runtime.ledger_migrations import _preflight, _rebuild
    from app.runtime.ledger_schema import LEDGER_V2_DDL
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    prepared(value)
    before = logical(value.legacy)
    db = sqlite3.connect(value.legacy.path, isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN EXCLUSIVE")
        _, snapshot = _preflight(db, value.domain.vault_id, time.monotonic() + 30)
        if control == "omit_parent":
            _rebuild(db, snapshot, time.monotonic() + 30)
            db.execute("DELETE FROM runtime_attempts")
        else:
            db.execute("PRAGMA defer_foreign_keys=ON")
            db.execute("ALTER TABLE runtime_attempts RENAME TO runtime_attempts_old")
            for sql in LEDGER_V2_DDL:
                if sql.startswith(("CREATE TABLE runtime_dispatch_subjects ", "CREATE TABLE runtime_attempts ")):
                    db.execute(sql)
            db.execute("DROP TABLE runtime_attempts_old")
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA defer_foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("COMMIT")
        db.execute("ROLLBACK")
    finally:
        db.close()
    assert logical(value.legacy) == before


@pytest.mark.parametrize("mutation", ["UPDATE runtime_attempt_refs SET role='wrong' WHERE role='profile'",
    "UPDATE runtime_checkpoints SET bound_execution_id='00000000-0000-4000-8000-000000000001'",
    "UPDATE runtime_attempts SET spec_digest='private-secret'",
    "UPDATE runtime_attempts SET accepted_observation_id='00000000-0000-4000-8000-000000000001'"])
def test_shared_pure_binding_corruption_denies_migration(tmp_path, monkeypatch, mutation):
    from app.tests.test_runtime_ledger import opened, prepared, identifier
    from app.runtime.ledger_migrations import LedgerMigrationError
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    run, _, _, attempt, _ = prepared(value)
    value.ledger.write_checkpoint(identifier(), run.run_id, "bound", b"cursor", expected_revision=0,
                                  attempt_id=attempt.attempt_id)
    lock_for(value.legacy)
    with sqlite3.connect(value.legacy.path) as db:
        db.execute(mutation)
    before = logical(value.legacy)
    with pytest.raises(LedgerMigrationError, match="^maintenance_required$"):
        migrate(value.legacy, value.domain.vault_id)
    assert logical(value.legacy) == before


def test_accepted_observation_requires_reverse_attempt_pointer(tmp_path, monkeypatch):
    from app.tests.test_runtime_ledger import opened, prepared, identifier, send, result
    from app.runtime.ledger_migrations import LedgerMigrationError
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    _, _, owner, attempt, _ = prepared(value)
    send(value, attempt, owner)
    value.ledger.accept_result(identifier(), result(value, attempt.attempt_id))
    lock_for(value.legacy)
    with sqlite3.connect(value.legacy.path) as db:
        db.execute("UPDATE runtime_attempts SET accepted_observation_id=NULL")
    with pytest.raises(LedgerMigrationError, match="^maintenance_required$"):
        migrate(value.legacy, value.domain.vault_id)


def test_loaded_langgraph_checkpoint_remains_writable_after_migration(tmp_path, monkeypatch):
    from app.tests.test_langgraph_checkpoints import setup, saver, put
    from uuid import uuid4
    v1_producer(monkeypatch)
    module, value, run = setup(tmp_path)
    saved = saver(module, value, run)
    cfg = put(saved, run)
    loaded = saved.get_tuple(cfg)
    lock_for(value.legacy)
    assert migrate(value.legacy, value.domain.vault_id)["state"] == "migrated"
    assert saved.get_tuple(cfg) == loaded
    task_id = str(uuid4())
    saved.put_writes(cfg, [("counters", {"first": 1})], task_id)
    assert saved.get_tuple(cfg).pending_writes == [(task_id, "counters", {"first": 1})]


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("change", ["null_arm", "extra_fk", "cascade", "revision"])
def test_changed_constraints_fail_exact_compiled_shape(tmp_path, version, change):
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    if version == 2:
        migrate(legacy, vault)
    with sqlite3.connect(legacy.path) as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='runtime_attempts'").fetchone()[0]
        if change == "revision":
            sql = sql.replace("revision>0", "revision>=0")
        elif change == "cascade":
            sql = sql.replace("REFERENCES runtime_node_executions(vault_id,id)",
                              "REFERENCES runtime_node_executions(vault_id,id) ON DELETE CASCADE")
        elif change == "extra_fk":
            sql = sql[:-1] + ", FOREIGN KEY(vault_id,id) REFERENCES runtime_node_executions(vault_id,id))"
        else:
            sql = sql.replace("execution_id IS NOT NULL AND ", "") if version == 2 else sql.replace(
                "execution_id TEXT NOT NULL", "execution_id TEXT")
        db.execute("PRAGMA writable_schema=ON")
        db.execute("UPDATE sqlite_master SET sql=? WHERE name='runtime_attempts'", (sql,))
        db.execute("PRAGMA writable_schema=OFF")
        schema = db.execute("PRAGMA schema_version").fetchone()[0]
        db.execute("PRAGMA schema_version=%d" % (schema + 1))
    with pytest.raises(LedgerMigrationError, match="^maintenance_required$"):
        migrate(legacy, vault)


def test_commit_failure_after_attempted_commit_is_unknown_and_rolls_back(tmp_path, monkeypatch):
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    from app.tests.test_runtime_ledger import opened, prepared
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    prepared(value)
    lock_for(value.legacy)
    before = logical(value.legacy)
    original = operation._open
    def broken_commit(handles, deadline):
        db = original(handles, deadline)
        def trace(sql):
            if sql == "COMMIT":
                db.set_trace_callback(None)
                db.execute("DELETE FROM runtime_attempts")
        db.set_trace_callback(trace)
        return db
    monkeypatch.setattr(operation, "_open", broken_commit)
    with pytest.raises(LedgerMigrationError, match="^outcome_unknown$"):
        migrate(value.legacy, value.domain.vault_id)
    assert logical(value.legacy) == before


def test_baseexception_releases_handles_and_rolls_back(tmp_path, monkeypatch):
    from app.operations import runtime_ledger_migrate as operation
    legacy, _, vault = historical(tmp_path)
    before = logical(legacy)
    def interrupted(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(operation, "_preflight", interrupted)
    with pytest.raises(KeyboardInterrupt):
        migrate(legacy, vault)
    assert logical(legacy) == before
    lock_for(legacy)


@pytest.mark.parametrize("case", ["uid_bool", "gid_negative", "nil_vault", "digest", "effective_uid"])
def test_invalid_authority_inputs_never_open_path(tmp_path, case):
    from app.operations.runtime_ledger_migrate import migrate_runtime_ledger_v1_to_v2
    from app.runtime.ledger_migrations import LedgerMigrationError
    from uuid import uuid4
    args = dict(expected_uid=os.geteuid(), expected_gid=os.getegid(), expected_vault_id=str(uuid4()),
                expected_v1_digest="b761957cfb9c21a63f928ba5c7d173ba7a4804d0dc72b240fdade0bc860ad118")
    if case == "uid_bool":
        args["expected_uid"] = True
    elif case == "gid_negative":
        args["expected_gid"] = -1
    elif case == "nil_vault":
        args["expected_vault_id"] = "00000000-0000-0000-0000-000000000000"
    elif case == "digest":
        args["expected_v1_digest"] = "SECRET"
    else:
        args["expected_uid"] += 1
    with pytest.raises(LedgerMigrationError) as error:
        migrate_runtime_ledger_v1_to_v2(tmp_path / "absent", **args)
    assert error.value.code == ("unavailable" if case == "effective_uid" else "invalid_request")
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("kind", ["directory_symlink", "database_symlink", "database_hardlink", "fifo_sidecar"])
def test_no_follow_and_single_link_profile(tmp_path, kind):
    from app.operations.runtime_ledger_migrate import migrate_runtime_ledger_v1_to_v2
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    directory = legacy.path.parent
    if kind == "directory_symlink":
        link = tmp_path / "alias"
        link.symlink_to(directory, target_is_directory=True)
        directory = link
    elif kind == "database_symlink":
        target = directory / "original.sqlite3"
        legacy.path.rename(target)
        legacy.path.symlink_to(target)
    elif kind == "database_hardlink":
        os.link(legacy.path, directory / "alias.sqlite3")
    else:
        os.mkfifo(str(legacy.path) + "-journal", mode=0o600)
    with pytest.raises(LedgerMigrationError, match="^unavailable$"):
        migrate_runtime_ledger_v1_to_v2(directory, expected_uid=os.geteuid(), expected_gid=os.getegid(),
            expected_vault_id=vault, expected_v1_digest="b761957cfb9c21a63f928ba5c7d173ba7a4804d0dc72b240fdade0bc860ad118")


def test_unknown_version_is_refused_without_changes(tmp_path):
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute("INSERT INTO runtime_migrations VALUES ('ledger',3,?)", ("a" * 64,))
    before = logical(legacy)
    with pytest.raises(LedgerMigrationError, match="^maintenance_required$"):
        migrate(legacy, vault)
    assert logical(legacy) == before


def test_old_v1_only_verifier_refuses_v2_and_fresh_connection_enforces_fk(tmp_path):
    from app.runtime import ledger
    legacy, _, vault = historical(tmp_path)
    migrate(legacy, vault)
    with sqlite3.connect(legacy.path) as db:
        # The old verifier's exact schema/migration comparison, with its frozen v1 tuple.
        actual = {name: (kind, ledger._normalize_schema_sql(sql)) for kind, name, sql in db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name IN (%s)" %
            ",".join("?" for _ in ledger._EXPECTED_LEDGER_SCHEMA), tuple(ledger._EXPECTED_LEDGER_SCHEMA))}
        assert actual != ledger._EXPECTED_LEDGER_SCHEMA
        assert db.execute("SELECT version,sha256 FROM runtime_migrations WHERE component='ledger' ORDER BY version").fetchall() != [(1, ledger.RUNTIME_MIGRATION_SHA256)]
        db.execute("PRAGMA foreign_keys=ON")
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO runtime_dispatch_subjects VALUES (?,'node_execution','missing','missing',NULL,NULL,NULL)", (vault,))


def test_postcommit_preservation_detects_changed_bytes(tmp_path, monkeypatch):
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    original = operation._open
    count = [0]
    def changed(handles, deadline):
        count[0] += 1
        if count[0] == 2:
            with sqlite3.connect(legacy.path) as db:
                db.execute("UPDATE runtime_control SET last_clock_ms=1")
        return original(handles, deadline)
    monkeypatch.setattr(operation, "_open", changed)
    with pytest.raises(LedgerMigrationError, match="^outcome_unknown$"):
        migrate(legacy, vault)


def test_postcommit_values_are_resized_before_streaming(tmp_path, monkeypatch):
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    original = operation._open
    count, queries = [0], []
    def changed(handles, deadline):
        count[0] += 1
        if count[0] == 2:
            with sqlite3.connect(legacy.path) as db:
                db.execute("INSERT INTO runtime_public_events(vault_id,event_type,object_kind,object_id,payload,payload_digest,at_ms) "
                           "VALUES (?,'event','kind','id',zeroblob(67108865),'digest',0)", (vault,))
        db = original(handles, deadline)
        if count[0] == 2:
            db.set_trace_callback(queries.append)
        return db
    monkeypatch.setattr(operation, "_open", changed)
    with pytest.raises(LedgerMigrationError, match="^outcome_unknown$"):
        migrate(legacy, vault)
    assert not any(q.startswith('SELECT "sequence","vault_id"') for q in queries)


def test_case_insensitive_extra_inbound_fk_is_rejected(tmp_path):
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute("CREATE TABLE external_child(vault_id,attempt_id,FOREIGN KEY(vault_id,attempt_id) "
                   "REFERENCES RUNTIME_ATTEMPTS(vault_id,id))")
    before = logical(legacy)
    with pytest.raises(LedgerMigrationError, match="^maintenance_required$"):
        migrate(legacy, vault)
    assert logical(legacy) == before


def test_close_failure_has_fixed_unknown_outcome(tmp_path, monkeypatch):
    from app.operations import runtime_ledger_migrate as operation
    from app.runtime.ledger_migrations import LedgerMigrationError
    legacy, _, vault = historical(tmp_path)
    original = operation._Handles.close
    def close(self):
        original(self)
        raise OSError("SECRET private close path")
    monkeypatch.setattr(operation._Handles, "close", close)
    with pytest.raises(LedgerMigrationError, match="^outcome_unknown$"):
        migrate(legacy, vault)


@pytest.mark.parametrize("mutation", ["UPDATE runtime_attempt_journal SET transition='unsupported'",
    "UPDATE runtime_public_events SET event_type='unsupported'",
    "UPDATE runtime_result_observations SET observed_at_ms=-1"])
def test_existing_history_metadata_validators_are_shared(tmp_path, monkeypatch, mutation):
    from app.tests.test_runtime_ledger import opened, prepared, identifier, send, result
    from app.runtime.ledger_migrations import LedgerMigrationError
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    _, _, owner, attempt, _ = prepared(value)
    send(value, attempt, owner)
    value.ledger.accept_result(identifier(), result(value, attempt.attempt_id))
    lock_for(value.legacy)
    with sqlite3.connect(value.legacy.path) as db:
        db.execute(mutation)
    with pytest.raises(LedgerMigrationError, match="^maintenance_required$"):
        migrate(value.legacy, value.domain.vault_id)


def test_attempt_insertion_order_remains_identical_after_primary_key_rebuild(tmp_path, monkeypatch):
    from app.tests.test_runtime_ledger import opened, run_spec, execution_spec, owner, attempt_spec, identifier
    v1_producer(monkeypatch)
    value = opened(tmp_path)
    run = run_spec(value)
    value.ledger.create_run(identifier(), run)
    other = run_spec(value)
    value.ledger.create_run(identifier(), other)
    for attempt_id, run_id in (("ffffffff-ffff-4fff-8fff-ffffffffffff", run.run_id),
                              ("88888888-8888-4888-8888-888888888888", other.run_id),
                              ("11111111-1111-4111-8111-111111111111", run.run_id)):
        execution = execution_spec(value, run_id)
        value.ledger.create_execution(identifier(), execution)
        attempt = attempt_spec(value, execution.execution_id, owner(value), attempt_id=attempt_id)
        value.ledger.reserve_attempt(identifier(), attempt, lease_duration_ms=1000)
    before = value.ledger.attempts_for_run(run.run_id)
    other_before = value.ledger.attempts_for_run(other.run_id)
    lock_for(value.legacy)
    migrate(value.legacy, value.domain.vault_id)
    assert value.ledger.attempts_for_run(run.run_id) == before
    assert value.ledger.attempts_for_run(other.run_id) == other_before
