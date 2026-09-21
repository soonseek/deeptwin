"""Provider v4 startup preserves actual legacy commands and retained history.

The legacy sources use controlled UID/mount observations in temporary trees;
these tests do not qualify native provisioning or an operator deployment.
"""

import sqlite3
import time
from uuid import uuid4

import pytest

from app.deployment import prepare_records as records
from app.deployment import prepare_storage as storage
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.deployment.prepare_service import PersistentDeploymentPrepare
from app.domain.store import _writer
from app.tests.deployment_prepare_fixture import service_context


def legacy_projection(actual):
    """Exact immediate history, including physical rowids of private rows."""
    with actual.domain._connection() as db:
        if "provider_context_id" in {row[1] for row in db.execute("PRAGMA table_info(deployment_prepare_receipts)")}:
            assert all(tuple(row) == (None, 1) for row in db.execute("SELECT provider_context_id,source_singleton FROM deployment_prepare_receipts"))
        rows = {
            table: tuple(
                tuple(row)
                for row in db.execute(
                    "SELECT rowid," + (",".join(storage.COLUMNS_V3["receipts"]) if table == "receipts" else "*") + " FROM deployment_prepare_"
                    + table
                    + " ORDER BY rowid"
                )
            )
            for table in storage.TABLES_V3
        }
        for table in (
            "domain_records",
            "domain_edges",
            "domain_record_blobs",
            "domain_blobs",
            "api_event_envelopes",
            "api_event_streams",
        ):
            rows[table] = tuple(
                tuple(row)
                for row in db.execute("SELECT * FROM " + table + " ORDER BY 1,2")
            )
        return rows


def reopen(actual):
    return PersistentDeploymentPrepare(
        actual.domain,
        actual.owner,
        actual.registry,
        topology_source=None,
        exchange_source=None,
    )


def install_empty_v3(actual):
    """Historical schema fixture only; commands afterward use the real service."""
    with _writer(), actual.domain._connection(write=True) as db:
        layout = storage._layout(db)
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert all(
            db.execute("SELECT count(*) FROM deployment_prepare_" + table).fetchone()[0]
            == 0
            for table in layout.tables
        )
        assert (
            db.execute(
                "SELECT 1 FROM domain_records WHERE kind IN "
                "('deployment_request','deployment_receipt',"
                "'deployment_receipt_consumption','extension_installation')"
            ).fetchone()
            is None
        )
        assert (
            db.execute(
                "SELECT 1 FROM api_event_envelopes WHERE "
                "event_type LIKE 'deployment.%' OR event_type='extension.staged'"
            ).fetchone()
            is None
        )
        for table in reversed(layout.tables):
            db.execute("DROP TABLE deployment_prepare_" + table)
        db.execute("DROP TABLE deployment_prepare_migrations")
        for statement in storage.DDL_V3:
            db.execute(statement)
        db.executemany(
            "INSERT INTO deployment_prepare_migrations VALUES(?,?)",
            [
                (1, storage.CHECKSUM),
                (2, storage.CHECKSUM_V2),
                (3, storage.CHECKSUM_V3),
            ],
        )
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None


def test_actual_v3_commands_upgrade_preserving_immediate_rowids_and_bytes(
    tmp_path, monkeypatch
):
    # Missing the new constructor migration leaves version 4 absent.
    with service_context(tmp_path, monkeypatch) as actual:
        install_empty_v3(actual)
        prepared = actual.service.prepare(actual.request, actual.payload)
        cancel = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "expected_revision": 1,
        }
        cancelled = actual.service.cancel(
            actual.request, prepared["request_id"], cancel
        )
        before = legacy_projection(actual)
        service = reopen(actual)
        assert not service._unavailable
        with actual.domain._connection() as db:
            assert [
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM deployment_prepare_migrations ORDER BY version"
                )
            ] == [
                (1, "68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec"),
                (2, "d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f"),
                (3, "ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457"),
                (4, "f89a9a8ba7f98da44e4a48f63c0363d2bfa7fafe038bd19bfdc178396c4be7d2"),
                (5, "9f3b9426d465524036c8c3ca48db3ba3360e284149b5cee8611aba0d6b4907d2"),
                (6, "8065412b2560175517eee1b56ce12f04912cb2f74fe76a7446f17b2f33924c72"),
            ]
        assert legacy_projection(actual) == before
        assert service.prepare(actual.request, actual.payload) == prepared
        assert (
            service.cancel(actual.request, prepared["request_id"], cancel) == cancelled
        )


def test_unknown_inbound_fk_refuses_before_mutation(tmp_path, monkeypatch):
    with service_context(tmp_path, monkeypatch) as actual:
        install_empty_v3(actual)
        actual.service.prepare(actual.request, actual.payload)
        with _writer(), actual.domain._connection(write=True) as db:
            db.execute(
                "CREATE TABLE unrelated_commands (id TEXT REFERENCES deployment_prepare_commands(command_id))"
            )
        before = legacy_projection(actual)
        assert reopen(actual)._unavailable
        assert legacy_projection(actual) == before
        with actual.domain._connection() as db:
            assert storage.shape(db) == storage.SHAPE_V3


@pytest.mark.parametrize("version", [1, 2])
def test_accepted_v1_v2_chain_preserves_logical_history_before_v4(
    tmp_path, monkeypatch, version
):
    from app.tests.deployment_v1_history_fixture import snapshot_v1, v1_history
    from app.tests.test_deployment_journal_v3_migration import to_v2

    # The retained accepted v1 fixture is explicit historical-layout construction.
    with v1_history(
        tmp_path, monkeypatch, states=("prepared", "cancelled", "expired")
    ) as actual:
        if version == 2:
            to_v2(actual.domain)
        before = snapshot_v1(actual.domain)
        service = reopen(actual)
        assert not service._unavailable
        after = snapshot_v1(actual.domain)
        after["rows"]["migrations"] = after["rows"]["migrations"][:version]
        assert after == before
        with actual.domain._connection() as db:
            assert storage._layout(db) is storage._V6


@pytest.mark.parametrize("mutation", ["missing_index", "forged_index", "checksum"])
def test_corrupt_v4_shape_or_migration_never_rebuilds(tmp_path, monkeypatch, mutation):
    with service_context(tmp_path, monkeypatch) as actual:
        from app.tests.test_provider_receipt_migration import install_empty_v4
        install_empty_v4(actual)
        actual.service.prepare(actual.request, actual.payload)
        with sqlite3.connect(actual.domain.path) as db:
            if mutation == "checksum":
                db.execute(
                    "UPDATE deployment_prepare_migrations SET checksum=? WHERE version=4",
                    ("0" * 64,),
                )
            else:
                db.execute("DROP INDEX deployment_prepare_requests_vault_request")
                if mutation == "forged_index":
                    db.execute(
                        "CREATE UNIQUE INDEX deployment_prepare_requests_vault_request ON deployment_prepare_requests(request_id,vault_id)"
                    )
        before = legacy_projection(actual)
        assert reopen(actual)._unavailable
        assert legacy_projection(actual) == before


def test_v3_expired_history_and_final_verification_fault_preserve_history(
    tmp_path, monkeypatch
):
    with service_context(tmp_path, monkeypatch) as actual:
        install_empty_v3(actual)
        prepared = actual.service.prepare(actual.request, actual.payload)
        with actual.domain._connection() as db:
            deadline = db.execute(
                "SELECT expires_ms FROM deployment_prepare_requests"
            ).fetchone()[0]
        monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
        actual.service.reconcile_startup()
        assert (
            actual.service.read(actual.read_request, prepared["request_id"])["state"]
            == "expired"
        )
        before = legacy_projection(actual)
        verify = storage.verify

        def fail_after_verified(db, *args, **kwargs):
            result = verify(db, *args, **kwargs)
            if storage._layout(db) is storage._V4:
                raise sqlite3.OperationalError("injected after actual v4 verification")
            return result

        with monkeypatch.context() as fault:
            fault.setattr(storage, "verify", fail_after_verified)
            assert reopen(actual)._unavailable
        assert legacy_projection(actual) == before
        assert not reopen(actual)._unavailable
        assert legacy_projection(actual) == before


def test_every_v4_destructive_checkpoint_rolls_back(tmp_path, monkeypatch):
    with service_context(tmp_path, monkeypatch) as actual:
        install_empty_v3(actual)
        prepared = actual.service.prepare(actual.request, actual.payload)
        actual.service.cancel(
            actual.request,
            prepared["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": prepared["request_digest"],
                "expected_revision": 1,
            },
        )
        before = legacy_projection(actual)
        # 5 parent deletes, 2 drops, 6 creates, 5 restores, migration insert.
        for target in range(1, 20):
            writes = []
            with (
                pytest.raises((sqlite3.Error, DeploymentPrepareError)),
                _writer(),
                actual.domain._connection(write=True) as db,
            ):

                def trace(sql, writes=writes, target=target):
                    if len(writes) == target:
                        db.set_progress_handler(lambda: 1, 1)
                    if sql.startswith(
                        (
                            "DELETE FROM deployment_prepare_",
                            "DROP TABLE deployment_prepare_",
                            "CREATE TABLE deployment_prepare_",
                            "CREATE UNIQUE INDEX deployment_prepare_",
                            "INSERT INTO deployment_prepare_",
                        )
                    ):
                        writes.append(sql)

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
            assert len(writes) >= target
            assert legacy_projection(actual) == before
            with actual.domain._connection() as db:
                assert storage.shape(db) == storage.SHAPE_V3
                assert db.execute("PRAGMA foreign_key_check").fetchone() is None


@pytest.mark.parametrize("case", ["valid_succeeded_present", "valid_failed_absent"])
def test_populated_v3_receipt_consumption_installation_children_and_http_replay_survive(
    tmp_path, monkeypatch, case
):
    from app.tests.provider_prepare_fixture import provider_context
    from app.tests.test_web_owner_integration import headers

    with provider_context(
        tmp_path,
        monkeypatch,
        slot_id=2,
        legacy_staged=True,
        historical_v3=True,
        legacy_case=case,
    ) as actual:
        with actual.domain._connection() as db:
            assert storage._layout(db) is storage._V3
        csrf = actual.csrf
        path = actual.profile.base_path + "api/v1/deployment/requests"
        response = actual.client.post(
            path, headers=headers(actual.profile, csrf), json=actual.legacy_payload
        )
        assert response.status_code == 201
        before = legacy_projection(actual)
        with monkeypatch.context() as clock:
            clock.setattr(
                actual.owner,
                "_now",
                lambda *a, **kw: pytest.fail("migration sampled owner clock"),
            )
            service = reopen(actual)
            assert not service._unavailable
        assert legacy_projection(actual) == before
        with actual.domain._connection() as db:
            assert storage._layout(db) is storage._V6
            assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        replay = actual.client.post(
            path, headers=headers(actual.profile, csrf), json=actual.legacy_payload
        )
        assert replay.status_code == 201 and replay.content == response.content


@pytest.mark.parametrize("cancelled", [False, True])
def test_legacy_actual_commands_reopen_without_history_or_replay_change(
    tmp_path,
    monkeypatch,
    cancelled,
):
    # Catches changes to old frozen replay, permanent reservations, or startup writes.
    with service_context(tmp_path, monkeypatch) as actual:
        prepared = actual.service.prepare(actual.request, actual.payload)
        cancel = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "expected_revision": 1,
        }
        receipt = (
            actual.service.cancel(actual.request, prepared["request_id"], cancel)
            if cancelled
            else None
        )
        before = legacy_projection(actual)
        opened = reopen(actual)
        assert not opened._unavailable
        assert legacy_projection(actual) == before
        assert opened.prepare(actual.request, actual.payload) == prepared
        if cancelled:
            assert (
                opened.cancel(actual.request, prepared["request_id"], cancel) == receipt
            )
        assert opened.read(actual.read_request, prepared["request_id"])["state"] == (
            "cancelled" if cancelled else "prepared"
        )
        assert legacy_projection(actual) == before
        with pytest.raises(DeploymentPrepareError) as denied:
            opened.prepare(
                actual.request, {**actual.payload, "command_id": str(uuid4())}
            )
        assert denied.value.code == "conflict"
