"""Relational subjects never grant generation dispatch authority."""
import hashlib
import importlib.util
import sqlite3

import pytest

from app.tests.test_runtime_ledger import opened, prepared


def test_versioned_schema_module_exists():
    assert importlib.util.find_spec("app.runtime.ledger_schema") is not None


def test_fresh_node_subject_and_unchanged_public_snapshot(tmp_path):
    value = opened(tmp_path)
    _, execution, _, attempt, snapshot = prepared(value)
    with sqlite3.connect(value.legacy.path) as db:
        assert db.execute("SELECT version FROM runtime_migrations WHERE component='ledger' "
                          "ORDER BY version").fetchall() == [(1,), (2,)]
        assert db.execute("SELECT subject_kind,subject_id,node_execution_id FROM "
                          "runtime_dispatch_subjects").fetchall() == [
                              ("node_execution", execution.execution_id, execution.execution_id)]
        assert db.execute("SELECT execution_id,subject_kind,subject_id FROM runtime_attempts").fetchall() == [
            (execution.execution_id, "node_execution", execution.execution_id)]
    assert "subject_kind" not in snapshot and "subject_kind" not in snapshot["spec"]
    assert value.ledger.get_attempt(attempt.attempt_id) == snapshot


def test_pinned_schema_digests():
    from app.runtime.ledger_schema import LEDGER_V1_DDL, LEDGER_V2_DDL
    assert len(LEDGER_V1_DDL) == 18 and len(LEDGER_V2_DDL) == 19
    assert hashlib.sha256("\n".join(LEDGER_V1_DDL).encode()).hexdigest() == \
        "b761957cfb9c21a63f928ba5c7d173ba7a4804d0dc72b240fdade0bc860ad118"
    assert hashlib.sha256("\n".join(LEDGER_V2_DDL).encode()).hexdigest() == \
        "3131be5d54e0ffdfcf980353d04b81428f27e64711f4762993e63915deeda255"


@pytest.mark.parametrize("extra", ["CREATE TABLE runtime_surprise(id)",
    "CREATE TRIGGER surprise AFTER INSERT ON runtime_runs BEGIN SELECT 1; END"])
def test_startup_rejects_unexpected_shape_without_writes(tmp_path, extra):
    value = opened(tmp_path)
    with sqlite3.connect(value.legacy.path) as db:
        db.execute(extra)
        before = list(db.iterdump())
    with pytest.raises(value.module.CorruptLedger):
        value.module.RuntimeLedger(value.domain)
    with sqlite3.connect(value.legacy.path) as db:
        assert list(db.iterdump()) == before


@pytest.mark.parametrize("generation", [(None, 1, "a" * 64), ("generation_call", None, "a" * 64),
    ("generation_call", 1, None), ("generation_call", 0, "a" * 64),
    ("generation_call", 1.5, "a" * 64), ("generation_call", 1, "A" * 64)])
def test_generation_null_arm_cannot_pass_sql_check(tmp_path, generation):
    value = opened(tmp_path)
    with sqlite3.connect(value.legacy.path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO runtime_dispatch_subjects VALUES (?,'generation_call','call',NULL,?,?,?)",
                       (value.domain.vault_id, *generation))


def test_complete_generation_identity_is_structural_not_dispatch_authority(tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4
    value = opened(tmp_path)
    _, _, _, attempt, _ = prepared(value)
    # SQL-only future row: generation_call deliberately has no canonical admission yet.
    ref = SimpleNamespace(id=str(uuid4()), sha256="a" * 64)
    with sqlite3.connect(value.legacy.path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO domain_records VALUES (?,'generation_call',?,1,?,'operational',X'7B7D')",
                   (value.domain.vault_id, ref.id, ref.sha256))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO runtime_dispatch_subjects VALUES (?,'generation_call',?,NULL,'generation_call',1,?)",
                       (value.domain.vault_id, ref.id, "0" * 64))
        db.execute("INSERT INTO runtime_dispatch_subjects VALUES (?,'generation_call',?,NULL,'generation_call',1,?)",
                   (value.domain.vault_id, ref.id, ref.sha256))
        db.execute("UPDATE runtime_attempts SET subject_kind='generation_call',subject_id=?,execution_id=NULL WHERE id=?",
                   (ref.id, attempt.attempt_id))
    with pytest.raises(value.module.CorruptLedger):
        value.ledger.get_attempt(attempt.attempt_id)


def test_zero_attempt_execution_gets_subject_and_missing_subject_denies_context(tmp_path):
    from app.tests.test_runtime_ledger import run_spec, execution_spec, identifier, owner, attempt_spec
    value = opened(tmp_path)
    run = run_spec(value)
    value.ledger.create_run(identifier(), run)
    execution = execution_spec(value, run.run_id)
    value.ledger.create_execution(identifier(), execution)
    with sqlite3.connect(value.legacy.path) as db:
        assert db.execute("SELECT subject_id FROM runtime_dispatch_subjects").fetchone() == (execution.execution_id,)
        db.execute("DELETE FROM runtime_dispatch_subjects")
    spec = attempt_spec(value, execution.execution_id, owner(value))
    with value.ledger._transaction() as db, pytest.raises(value.module.CorruptLedger):
        value.ledger._resolve_node_dispatch_context(db, spec)


def test_descriptive_read_preserves_transaction_fault_hooks_but_real_dispatch_denies(tmp_path):
    from app.tests.test_runtime_budget_dispatch import opened as budget_opened, prepare, commit
    value = budget_opened(tmp_path)
    lease_owner, attempt, request, before = prepare(value)
    with sqlite3.connect(value.legacy.path) as db:
        db.execute("CREATE TRIGGER synthetic_failure BEFORE UPDATE ON runtime_attempts "
                   "BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    assert value.ledger.get_attempt(attempt.attempt_id) == before
    from app.runtime.ledger import CorruptLedger
    with pytest.raises(CorruptLedger, match="trigger"):
        commit(value, lease_owner, attempt, request)
    assert value.ledger.get_attempt(attempt.attempt_id) == before


@pytest.mark.parametrize("cause", ["chain", "subject_shape", "missing_subject_table"])
def test_descriptive_context_rejects_malformed_representation(tmp_path, cause):
    value = opened(tmp_path)
    _, _, _, attempt, _ = prepared(value)
    with sqlite3.connect(value.legacy.path) as db:
        if cause == "chain":
            db.execute("UPDATE runtime_migrations SET sha256='wrong' WHERE component='ledger' AND version=2")
        elif cause == "missing_subject_table":
            db.execute("DROP TABLE runtime_dispatch_subjects")
        else:
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='runtime_dispatch_subjects'").fetchone()[0]
            db.execute("PRAGMA writable_schema=ON")
            db.execute("UPDATE sqlite_master SET sql=? WHERE name='runtime_dispatch_subjects'",
                       (sql.replace("generation_version>0", "generation_version>=0"),))
            db.execute("PRAGMA writable_schema=OFF")
            version = db.execute("PRAGMA schema_version").fetchone()[0]
            db.execute("PRAGMA schema_version=%d" % (version + 1))
    with pytest.raises(value.module.CorruptLedger):
        value.ledger.get_attempt(attempt.attempt_id)
