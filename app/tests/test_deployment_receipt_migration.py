"""Actual v1 history must upgrade atomically through the ordinary constructor."""

import sqlite3

import pytest

from app.deployment import prepare_records as records
from app.deployment import prepare_storage as storage
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.deployment.prepare_service import PersistentDeploymentPrepare
from app.domain.store import _writer
from app.tests.deployment_v1_history_fixture import snapshot_v1, v1_history


@pytest.mark.parametrize(
    "states", [(), ("prepared", "cancelled", "expired") * 5 + ("prepared",)]
)
def test_ordinary_constructor_upgrades_actual_old_history_without_sources(
    tmp_path, monkeypatch, states
):
    with v1_history(tmp_path, monkeypatch, states=states) as actual:
        before = snapshot_v1(actual.domain)
        service = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        assert not service._unavailable
        with actual.domain._connection() as db:
            migrations = [
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM deployment_prepare_migrations ORDER BY version"
                )
            ]
            # the constructor continues forward-only to the current v3 shape
            # (journal v3 §3): v1 → v2 → v3 in one writer, each step verified
            assert migrations == [
                (1, "68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec"),
                (2, "d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f"),
                (3, "ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457"),
            ]
            assert storage.shape(db) == storage.SHAPE_V3
        after = snapshot_v1(actual.domain)
        after["rows"]["migrations"] = after["rows"]["migrations"][:1]
        assert after == before
        for value, reply, cancel_value, cancel_reply in actual.cases:
            assert service.prepare(actual.request, value) == reply
            if cancel_reply is not None:
                assert (
                    service.cancel(
                        actual.request,
                        reply["request_id"],
                        {k: v for k, v in cancel_value.items() if k != "request_id"},
                    )
                    == cancel_reply
                )
            current = service.read(actual.read_request, reply["request_id"])
            assert (
                current["receipt"] is None
                and current["consumption_publication_state"] is None
            )


def test_fault_after_every_rebuild_write_rolls_back_exact_disk_history(
    tmp_path, monkeypatch
):
    with v1_history(
        tmp_path, monkeypatch, states=("prepared", "cancelled", "expired")
    ) as actual:
        before = snapshot_v1(actual.domain)
        old_rows = sum(
            len(before["rows"][table])
            for table in ("migrations", "lifecycle", "commands", "heads", "outbox")
        )
        total_writes = old_rows * 2 + 5 + 9 + 1
        for target in range(1, total_writes + 1):
            seen = []

            def trace(sql, seen=seen, target=target):
                # Fail on the next statement, after the selected authoritative write finished.
                if len(seen) == target:
                    db.set_progress_handler(lambda: 1, 1)
                if sql.startswith(
                    (
                        "DELETE FROM deployment_prepare_",
                        "DROP TABLE deployment_prepare_",
                        "CREATE TABLE deployment_prepare_",
                        "INSERT INTO deployment_prepare_",
                    )
                ):
                    seen.append(sql.split("\n", 1)[0])

            with (
                pytest.raises((sqlite3.Error, DeploymentPrepareError)),
                _writer(),
                actual.domain._connection(write=True) as db,
            ):
                assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
                db.set_trace_callback(trace)
                try:
                    records.install(
                        actual.domain,
                        db,
                        actual.profile,
                        candidate_registry=actual.registry,
                    )
                finally:
                    db.set_progress_handler(None, 0)
                    db.set_trace_callback(None)
            assert len(seen) >= target, (target, seen)
            assert snapshot_v1(actual.domain) == before
            with actual.domain._connection() as db:
                assert storage.shape(db) == storage.SHAPE
                assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        # Commit admission fault with the same real, FK-on writer.
        with (
            pytest.raises(sqlite3.DatabaseError),
            _writer(),
            actual.domain._connection(write=True) as db,
        ):
            records.install(
                actual.domain, db, actual.profile, candidate_registry=actual.registry
            )
            db.set_authorizer(
                lambda action, arg1, arg2, database, trigger: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_TRANSACTION and arg1 == "COMMIT"
                    else sqlite3.SQLITE_OK
                )
            )
        assert snapshot_v1(actual.domain) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE deployment_prepare_migrations SET checksum='" + "x" * 65 + "'",
        "UPDATE deployment_prepare_migrations SET checksum='" + "0" * 64 + "'",
        "UPDATE deployment_prepare_control SET clock_floor_ms='" + "x" * 8193 + "'",
        "UPDATE deployment_prepare_commands SET input_json='" + "é" * 2049 + "'",
        "UPDATE deployment_prepare_lifecycle SET previous_revision='"
        + "x" * 8193
        + "' WHERE revision=1",
        "UPDATE deployment_prepare_heads SET lifecycle_hash='" + "0" * 64 + "'",
        "CREATE TABLE deployment_prepare_receipts(extra TEXT)",
        "CREATE INDEX deployment_prepare_alien ON deployment_prepare_heads(request_id)",
        "DROP TABLE deployment_prepare_heads",
    ],
)
def test_corrupt_or_partial_v1_denies_before_rebuild(tmp_path, monkeypatch, mutation):
    with v1_history(tmp_path, monkeypatch, states=("prepared",)) as actual:
        with sqlite3.connect(actual.domain.path) as raw:
            raw.execute("PRAGMA ignore_check_constraints=ON")
            raw.execute(mutation)
        with actual.domain._connection() as db:
            before = storage.shape(db)

        def forbidden(_db):
            pytest.fail("corrupt history reached rebuild")

        monkeypatch.setattr(storage, "_rebuild_v1_as_v2", forbidden)
        service = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        assert service._unavailable
        with actual.domain._connection() as db:
            assert storage.shape(db) == before


def test_current_storage_rejects_old_installer_and_v2_startup_is_write_free(
    tmp_path, monkeypatch
):
    with v1_history(tmp_path, monkeypatch) as actual:
        PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        with _writer(), actual.domain._connection(write=True) as db:
            with pytest.raises(DeploymentPrepareError):
                storage.install(db)
            with pytest.raises(DeploymentPrepareError):
                records.install_storage(db)
            before = db.total_changes
            records.install(
                actual.domain, db, actual.profile, candidate_registry=actual.registry
            )
            assert db.total_changes == before


def test_concurrent_ordinary_constructors_observe_one_complete_committed_v2(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with v1_history(
        tmp_path, monkeypatch, states=("prepared", "cancelled", "expired")
    ) as actual:
        before = snapshot_v1(actual.domain)
        gate = Barrier(2)

        def open_service():
            gate.wait(timeout=5)
            return PersistentDeploymentPrepare(
                actual.domain,
                actual.owner,
                actual.registry,
                topology_source=None,
                exchange_source=None,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(open_service) for _ in range(2)]
            services = [future.result(timeout=20) for future in futures]
        assert all(not service._unavailable for service in services)
        after = snapshot_v1(actual.domain)
        after["rows"]["migrations"] = after["rows"]["migrations"][:1]
        assert after == before


def test_actual_orphan_receipt_anchor_in_v1_is_rejected_before_ddl(
    tmp_path, monkeypatch
):
    from app.domain.schemas import ImmutableRecord

    with v1_history(tmp_path, monkeypatch, states=("prepared",)) as actual:
        with _writer(), actual.domain._connection(write=True) as db:
            item = next(
                iter(
                    records.verify(actual.domain, db, actual.profile)[
                        "requests"
                    ].values()
                )
            )
            roots = actual.domain._read_roots(db)
            blob = item["anchor"]["request_blob_ref"]
            record = ImmutableRecord.create(
                kind="deployment_receipt",
                id=item["ref"].id,
                version=1,
                created_at_utc="2026-09-16T00:00:00.000000Z",
                actor_ref=item["actor"],
                parent_refs=(item["ref"],),
                purpose="operational",
                access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={
                    "schema_version": "deployment-receipt-anchor-v1",
                    "request_ref": item["ref"].as_dict(),
                    "import_command_id": str(__import__("uuid").uuid4()),
                    **{
                        name + "_blob_ref": blob
                        for name in (
                            "receipt",
                            "trust",
                            "ingress",
                            "consumption_exchange",
                        )
                    },
                },
            )
            actual.domain._put_in_transaction(db, record)
        monkeypatch.setattr(
            storage,
            "_rebuild_v1_as_v2",
            lambda _db: pytest.fail("orphan anchor reached DDL"),
        )
        assert PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )._unavailable
        with actual.domain._connection() as db:
            assert storage.shape(db) == storage.SHAPE
