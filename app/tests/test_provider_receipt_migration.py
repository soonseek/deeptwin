"""Same-owner v4 to v5 migration of actual historical commands."""

from uuid import uuid4
import sqlite3
import pytest
from app.domain.store import _writer
from app.deployment import prepare_records as records
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.deployment import prepare_storage as storage
from app.tests.provider_receipt_fixture import provider_receipt_context
from app.tests.test_provider_prepare_migration import reopen

C5 = "9f3b9426d465524036c8c3ca48db3ba3360e284149b5cee8611aba0d6b4907d2"


def install_empty_v4(actual):
    """Only an empty historical schema; real commands populate it afterward."""
    with _writer(), actual.domain._connection(write=True) as db:
        layout = storage._layout(db)
        assert all(
            db.execute("SELECT count(*) FROM deployment_prepare_" + table).fetchone()[0]
            == 0
            for table in layout.tables
        )
        assert (
            db.execute(
                "SELECT count(*) FROM domain_records WHERE kind IN ('deployment_request','deployment_receipt','deployment_receipt_consumption','extension_installation')"
            ).fetchone()[0]
            == 0
        )
        for table in reversed(layout.tables):
            db.execute("DROP TABLE deployment_prepare_" + table)
        db.execute("DROP TABLE deployment_prepare_migrations")
        for statement in storage.DDL_V4:
            db.execute(statement)
        db.executemany(
            "INSERT INTO deployment_prepare_migrations VALUES(?,?)",
            [
                (1, storage.CHECKSUM),
                (2, storage.CHECKSUM_V2),
                (3, storage.CHECKSUM_V3),
                (4, storage.CHECKSUM_V4),
            ],
        )
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None


def snapshot_v4(actual):
    with actual.domain._connection() as db:
        result = {
            table: tuple(
                tuple(r)
                for r in db.execute(
                    "SELECT rowid,"
                    + ",".join(storage.COLUMNS_V4[table])
                    + " FROM deployment_prepare_"
                    + table
                    + " ORDER BY rowid"
                )
            )
            for table in storage.TABLES_V4
        }
        for table in (
            "domain_records",
            "domain_edges",
            "domain_record_blobs",
            "domain_blobs",
            "api_event_envelopes",
            "api_event_streams",
        ):
            result[table] = tuple(
                tuple(row)
                for row in db.execute("SELECT * FROM " + table + " ORDER BY 1,2")
            )
        return result


@pytest.mark.parametrize(
    "legacy_case", ["valid_failed_absent", "valid_succeeded_present"]
)
def test_populated_v4_old_receipts_and_provider_commands_keep_cells_rowids_and_replays(
    tmp_path, monkeypatch, legacy_case
):
    with provider_receipt_context(
        tmp_path.resolve(),
        monkeypatch,
        slot_id=2,
        legacy_staged=True,
        defer_legacy_stage=True,
        legacy_case=legacy_case,
    ) as actual:
        install_empty_v4(actual)
        actual.stage_legacy()
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        cancel = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "expected_revision": 1,
        }
        cancelled = actual.service.cancel_provider(
            actual.request, prepared["request_id"], cancel
        )
        before = snapshot_v4(actual)
        actual.context.close()
        service = reopen(actual)
        assert not service._unavailable
        assert snapshot_v4(actual) == before
        with actual.domain._connection() as db:
            assert storage._layout(db) is storage._V6
            assert all(
                tuple(row) == (None, 1)
                for row in db.execute(
                    "SELECT provider_context_id,source_singleton FROM deployment_prepare_receipts"
                )
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_provider_receipt_sources"
                ).fetchone()[0]
                == 0
            )
            assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        assert service.prepare_provider(actual.request, actual.payload) == prepared
        assert (
            service.cancel_provider(actual.request, prepared["request_id"], cancel)
            == cancelled
        )
        assert (
            service.prepare(actual.request, actual.legacy_payload)
            == actual.legacy_request
        )


def test_v5_destructive_checkpoints_roll_back_populated_immediate_v4(
    tmp_path, monkeypatch
):
    with provider_receipt_context(
        tmp_path.resolve(),
        monkeypatch,
        slot_id=2,
        legacy_staged=True,
        defer_legacy_stage=True,
        legacy_case="valid_failed_absent",
    ) as actual:
        install_empty_v4(actual)
        actual.stage_legacy()
        actual.service.prepare_provider(actual.request, actual.payload)
        before = snapshot_v4(actual)
        statements = []

        class ProbeRollback(Exception):
            pass

        prefixes = (
            "DELETE FROM deployment_prepare_",
            "DROP TABLE deployment_prepare_",
            "CREATE TABLE deployment_prepare_",
            "CREATE UNIQUE INDEX deployment_prepare_",
            "INSERT INTO deployment_prepare_",
        )
        with (
            pytest.raises(ProbeRollback),
            _writer(),
            actual.domain._connection(write=True) as db,
        ):
            db.set_trace_callback(
                lambda sql: statements.append(sql) if sql.startswith(prefixes) else None
            )
            records.install(
                actual.domain, db, actual.profile, candidate_registry=actual.registry
            )
            db.set_trace_callback(None)
            raise ProbeRollback()
        assert snapshot_v4(actual) == before
        assert len(statements) > 15
        for target in range(1, len(statements) + 1):
            seen = []
            with (
                pytest.raises((sqlite3.Error, DeploymentPrepareError)),
                _writer(),
                actual.domain._connection(write=True) as db,
            ):

                def trace(sql):
                    if sql.startswith(prefixes):
                        seen.append(sql)
                        if len(seen) == target:
                            db.set_progress_handler(lambda: 1, 1)

                db.set_trace_callback(trace)
                try:
                    records.install(
                        actual.domain,
                        db,
                        actual.profile,
                        candidate_registry=actual.registry,
                    )
                finally:
                    db.set_trace_callback(None)
                    db.set_progress_handler(None, 0)
            assert snapshot_v4(actual) == before
            with actual.domain._connection() as db:
                assert storage._layout(db) is storage._V4
                assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        print(
            f"Task43 immediate-v4 destructive checkpoints={len(statements)}; all rolled back"
        )


def test_v5_post_restore_semantic_verification_failure_rolls_back_populated_v4(
    tmp_path, monkeypatch
):
    with provider_receipt_context(
        tmp_path.resolve(),
        monkeypatch,
        slot_id=2,
        legacy_staged=True,
        defer_legacy_stage=True,
        legacy_case="valid_failed_absent",
    ) as actual:
        install_empty_v4(actual)
        actual.stage_legacy()
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        before = snapshot_v4(actual)
        real_verify, observed = records.verify, []

        def verify(domain, db, profile):
            result = real_verify(domain, db, profile)
            layout = storage._layout(db)
            observed.append(layout)
            if layout is storage._V5:
                assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
                assert db.execute("PRAGMA foreign_key_check").fetchone() is None
                assert tuple(
                    db.execute(
                        "SELECT version,checksum FROM deployment_prepare_migrations ORDER BY version DESC LIMIT 1"
                    ).fetchone()
                ) == (5, C5)
                assert all(
                    tuple(row) == (None, 1)
                    for row in db.execute(
                        "SELECT provider_context_id,source_singleton FROM deployment_prepare_receipts"
                    )
                )
                raise DeploymentPrepareError("unavailable")
            return result

        with monkeypatch.context() as fault:
            fault.setattr(records, "verify", verify)
            with (
                pytest.raises(DeploymentPrepareError) as caught,
                _writer(),
                actual.domain._connection(write=True) as db,
            ):
                records.install(
                    actual.domain,
                    db,
                    actual.profile,
                    candidate_registry=actual.registry,
                )
            assert caught.value.code == "unavailable"
        assert observed == [storage._V4, storage._V5]
        assert snapshot_v4(actual) == before
        with actual.domain._connection() as db:
            assert storage._layout(db) is storage._V4
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        actual.context.close()
        service = reopen(actual)
        assert not service._unavailable and snapshot_v4(actual) == before
        assert service.prepare_provider(actual.request, actual.payload) == prepared
        assert (
            service.prepare(actual.request, actual.legacy_payload)
            == actual.legacy_request
        )


def test_actual_owner_installs_v5_and_replays_without_sources(tmp_path, monkeypatch):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        cancel = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "expected_revision": 1,
        }
        cancelled = actual.service.cancel_provider(
            actual.request, prepared["request_id"], cancel
        )
        with actual.domain._connection() as db:
            migrations = [
                tuple(r)
                for r in db.execute(
                    "SELECT * FROM deployment_prepare_migrations ORDER BY version"
                )
            ]
        assert migrations[-2:] == [(5, C5), (6, storage.CHECKSUM_V6)]
        actual.context.close()
        service = reopen(actual)
        assert not service._unavailable
        assert service.prepare_provider(actual.request, actual.payload) == prepared
        assert (
            service.cancel_provider(actual.request, prepared["request_id"], cancel)
            == cancelled
        )


def test_immediate_v4_provider_expired_history_migrates_without_live_time(
    tmp_path, monkeypatch
):
    from app.deployment.prepare_contracts import epoch_ms
    import time

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        install_empty_v4(actual)
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        with monkeypatch.context() as expired:
            expired.setattr(
                time, "time_ns", lambda: epoch_ms(request["expires_at"]) * 1_000_000
            )
            actual.service.reconcile_startup()
        assert (
            actual.service.read_provider(actual.read_request, prepared["request_id"])[
                "state"
            ]
            == "expired"
        )
        before = snapshot_v4(actual)
        actual.context.close()
        service = reopen(actual)
        assert not service._unavailable and snapshot_v4(actual) == before
        assert service.prepare_provider(actual.request, actual.payload) == prepared
        assert (
            service.read_provider(actual.read_request, prepared["request_id"])["state"]
            == "expired"
        )


@pytest.mark.parametrize(
    "fault", ["inbound", "composite_inbound", "missing_index", "checksum"]
)
def test_immediate_v4_corruption_is_not_rebuilt(tmp_path, monkeypatch, fault):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        install_empty_v4(actual)
        actual.service.prepare_provider(actual.request, actual.payload)
        with actual.domain._connection(write=True) as db:
            if fault == "inbound":
                db.execute(
                    "CREATE TABLE task43_unexpected_inbound(command_id TEXT REFERENCES deployment_prepare_commands(command_id))"
                )
            elif fault == "composite_inbound":
                db.execute(
                    "CREATE TABLE task43_unexpected_inbound(request_id TEXT,vault_id TEXT,FOREIGN KEY(request_id,vault_id) REFERENCES deployment_prepare_receipts(request_id,vault_id))"
                )
            elif fault == "missing_index":
                db.execute("DROP INDEX deployment_prepare_requests_vault_request")
            else:
                db.execute(
                    "UPDATE deployment_prepare_migrations SET checksum=? WHERE version=4",
                    ("0" * 64,),
                )
        before = snapshot_v4(actual)
        with actual.domain._connection() as db:
            schema = tuple(
                tuple(r)
                for r in db.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name"
                )
            )
        assert reopen(actual)._unavailable
        assert snapshot_v4(actual) == before
        with actual.domain._connection() as db:
            assert (
                tuple(
                    tuple(r)
                    for r in db.execute(
                        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name"
                    )
                )
                == schema
            )
