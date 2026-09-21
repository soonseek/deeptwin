"""Task 24 step (e1): the v3 storage layout and the v2 → v3 migration
(contracts/deployment-receipt-journal-v3.md §2/§3/§7/§8).

An actual v2 history must upgrade atomically through the ordinary
constructor: the four recreated parents (migrations, lifecycle, commands,
consumptions) are snapshotted, deleted, dropped, recreated and restored under
deferred foreign keys while their populated children (heads, outbox,
receipts, consumed_outbox) stay in place; any fault rolls back to exact v2;
a commit without the restores is refused by SQLite. Old helpers reject v3.
"""

import sqlite3

import pytest

from app.deployment import prepare_records as records
from app.deployment import prepare_storage as storage
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.deployment.prepare_service import PersistentDeploymentPrepare
from app.domain import extension_installation
from app.domain.store import _writer
from app.tests.deployment_v1_history_fixture import v1_history

C1 = "68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec"
C2 = "d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f"
C3 = "ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457"
C4 = "f89a9a8ba7f98da44e4a48f63c0363d2bfa7fafe038bd19bfdc178396c4be7d2"
C5 = "9f3b9426d465524036c8c3ca48db3ba3360e284149b5cee8611aba0d6b4907d2"
KINDS = (
    "deployment_request",
    "deployment_receipt",
    "deployment_receipt_consumption",
    "extension_installation",
)


def snapshot(domain, tables, migrations):
    """Bounded deployment rows/records/events only; never owner or session storage."""
    with domain._connection() as db:
        if "provider_context_id" in {row[1] for row in db.execute("PRAGMA table_info(deployment_prepare_receipts)")}:
            assert all(tuple(row) == (None, 1) for row in db.execute("SELECT provider_context_id,source_singleton FROM deployment_prepare_receipts"))
        rows = {
            table: tuple(
                tuple(row)
                for row in db.execute(
                    "SELECT " + (",".join(storage.COLUMNS_V2["receipts"]) if table == "receipts" else "*") + " FROM deployment_prepare_"
                    + table
                    + " ORDER BY 1,2 LIMIT ?",
                    (cap + 1,),
                )
            )
            for table, cap in {
                "migrations": migrations,
                **{t: storage.CAPS_V3.get(t, 16) for t in tables},
            }.items()
        }
        deployment = tuple(
            tuple(row)
            for row in db.execute(
                "SELECT * FROM domain_records WHERE kind IN (?,?,?,?) ORDER BY kind,id,version LIMIT 65",
                KINDS,
            )
        )
        events = tuple(
            tuple(row)
            for row in db.execute(
                "SELECT * FROM api_event_envelopes WHERE event_type LIKE 'deployment.%' "
                "OR event_type LIKE 'extension.%' ORDER BY sequence LIMIT 97"
            )
        )
        return {"rows": rows, "records": deployment, "events": events}


def snapshot_v2(domain):
    return snapshot(domain, storage.TABLES_V2, 2)


def snapshot_v3(domain):
    return snapshot(domain, storage.TABLES_V3, 3)


def to_v2(domain):
    """An exact v2 journal from the v1 fixture, through the mechanical v1 → v2
    primitive in a real FK-on writer (the constructor would go on to v3)."""
    with _writer(), domain._connection(write=True) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        storage._rebuild_v1_as_v2(db)
    with domain._connection() as db:
        assert storage.shape(db) == storage.SHAPE_V2


def construct(actual):
    return PersistentDeploymentPrepare(
        actual.domain,
        actual.owner,
        actual.registry,
        topology_source=None,
        exchange_source=None,
    )


@pytest.mark.parametrize(
    "states", [(), ("prepared", "cancelled", "expired") * 5 + ("prepared",)]
)
def test_ordinary_constructor_upgrades_actual_v2_history_without_sources(
    tmp_path, monkeypatch, states
):
    with v1_history(tmp_path, monkeypatch, states=states) as actual:
        to_v2(actual.domain)
        before = snapshot_v2(actual.domain)
        service = construct(actual)
        assert not service._unavailable
        with actual.domain._connection() as db:
            migrations = [
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM deployment_prepare_migrations ORDER BY version"
                )
            ]
            assert migrations == [(1, C1), (2, C2), (3, C3), (4, C4), (5, C5), (6, storage.CHECKSUM_V6)]
            assert storage.shape(db) == storage.SHAPE_V6
            assert storage._layout(db) is storage._V6
            for table in ("installations", "installation_heads"):
                assert (
                    db.execute(
                        "SELECT count(*) FROM deployment_prepare_" + table
                    ).fetchone()[0]
                    == 0
                )
        after = snapshot_v3(actual.domain)
        after["rows"]["migrations"] = after["rows"]["migrations"][:2]
        for table in ("installations", "installation_heads"):
            assert after["rows"].pop(table) == ()
        assert after == before
        # the journal is served as before on the new layout
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
            assert (
                service.read(actual.read_request, reply["request_id"])["receipt"]
                is None
            )
        # A second ordinary construction is write-free and stays on current v4.
        again = snapshot_v3(actual.domain)
        assert not construct(actual)._unavailable
        assert snapshot_v3(actual.domain) == again


def test_fault_after_every_rebuild_write_rolls_back_exact_v2_history(
    tmp_path, monkeypatch
):
    with v1_history(
        tmp_path, monkeypatch, states=("prepared", "cancelled", "expired")
    ) as actual:
        to_v2(actual.domain)
        before = snapshot_v2(actual.domain)
        old_rows = sum(
            len(before["rows"][table])
            for table in ("migrations", "lifecycle", "commands", "consumptions")
        )
        # every parent row deleted and restored, four drops, six creates, one insert
        total_writes = old_rows * 2 + 4 + 6 + 1
        for target in range(1, total_writes + 1):
            seen = []

            def trace(sql, seen=seen, target=target):
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
            assert snapshot_v2(actual.domain) == before
            with actual.domain._connection() as db:
                assert storage.shape(db) == storage.SHAPE_V2
                assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        # commit refused by the same real FK-on writer: exact v2 remains
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
        assert snapshot_v2(actual.domain) == before


def test_a_commit_without_the_restores_is_refused_and_children_survive_the_rebuild(
    tmp_path, monkeypatch
):
    # the contract's stated reliance: populated children (heads, outbox) keep
    # referencing the recreated parents by name; the deferred counter is only
    # settled by the restores, so a commit without them is refused by SQLite
    with v1_history(tmp_path, monkeypatch, states=("prepared", "cancelled")) as actual:
        to_v2(actual.domain)
        before = snapshot_v2(actual.domain)
        assert before["rows"]["heads"] and before["rows"]["outbox"]
        with (
            pytest.raises(
                sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"
            ),
            _writer(),
            actual.domain._connection(write=True) as db,
        ):
            db.execute("PRAGMA defer_foreign_keys=ON")
            for table, key in (
                ("consumptions", "request_id"),
                ("commands", "command_id"),
                ("lifecycle", "request_id"),
                ("migrations", "version"),
            ):
                for row in db.execute(
                    "SELECT "
                    + key
                    + (", revision" if table == "lifecycle" else "")
                    + " FROM deployment_prepare_"
                    + table
                    + (" ORDER BY revision DESC" if table == "lifecycle" else "")
                ).fetchall():
                    db.execute(
                        "DELETE FROM deployment_prepare_"
                        + table
                        + " WHERE "
                        + key
                        + "=?"
                        + (" AND revision=?" if table == "lifecycle" else ""),
                        tuple(row),
                    )
            for table in ("consumptions", "commands", "lifecycle", "migrations"):
                db.execute("DROP TABLE deployment_prepare_" + table)
            for index in (0, 3, 5, 9, 11, 12):
                db.execute(storage.DDL_V3[index])
            # heads and outbox still hold their rows although their parents are gone
            assert db.execute(
                "SELECT count(*) FROM deployment_prepare_heads"
            ).fetchone()[0] == len(before["rows"]["heads"])
            assert db.execute("PRAGMA foreign_key_check").fetchone() is not None
        assert snapshot_v2(actual.domain) == before


def test_already_v3_startup_requires_exact_rows_and_old_helpers_reject_v3(
    tmp_path, monkeypatch
):
    with v1_history(tmp_path, monkeypatch, states=("prepared",)) as actual:
        to_v2(actual.domain)
        assert not construct(actual)._unavailable
        with _writer(), actual.domain._connection(write=True) as db:
            with pytest.raises(DeploymentPrepareError):
                storage.install(db)  # the historical v1 installer never migrates
            with pytest.raises(DeploymentPrepareError):
                records.install_storage(db)  # the v1-only foundation helper
            with pytest.raises(DeploymentPrepareError):
                storage.validate_row("installations", {})  # v1 wrapper: no v3 rows
            assert storage.validate_current_row is not None
            row = {
                "extension_id": "ext",
                "request_id": "r",
                "revision": 1,
                "installation_anchor_digest": "a" * 64,
            }
            assert storage.digest("installation_heads", row) == storage.digest(
                "installation_heads", {**row, "hash": "ignored"}
            )
            assert storage.digest("installation_heads", row) != storage.digest(
                "consumed_outbox", row
            )  # the v3 suffixes hash under their own namespace
            with pytest.raises(DeploymentPrepareError):
                storage.digest("not-a-table", row)
            db.execute(
                "UPDATE deployment_prepare_migrations SET checksum=? WHERE version=3",
                ("0" * 64,),
            )
        assert construct(actual)._unavailable  # exact (3,C3) is required
        with _writer(), actual.domain._connection(write=True) as db:
            db.execute(
                "UPDATE deployment_prepare_migrations SET checksum=? WHERE version=3",
                (C3,),
            )
        assert not construct(actual)._unavailable


def test_an_installation_anchor_outside_the_journal_index_denies_verification(
    tmp_path, monkeypatch
):
    # journal v3 §4: installations ↔ extension_installation anchors is a
    # bijection; an anchor with no index row is an integrity failure
    from uuid import uuid4

    from app.domain.schemas import ImmutableRecord

    with v1_history(tmp_path, monkeypatch, states=("prepared",)) as actual:
        to_v2(actual.domain)
        assert not construct(actual)._unavailable
        roots = actual.domain.roots()
        monkeypatch.setattr(
            extension_installation, "validate_installation_body", lambda body: None
        )
        actual.domain.put(
            ImmutableRecord.create(
                kind="extension_installation",
                id=str(uuid4()),
                version=1,
                created_at_utc="2026-09-18T00:00:00.000000Z",
                actor_ref=roots.actor,
                parent_refs=(),
                purpose="operational",
                access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={"historical_state": "other-schema"},
            )
        )
        assert construct(actual)._unavailable
        with actual.domain._connection() as db, pytest.raises(DeploymentPrepareError):
            records.verify(actual.domain, db, actual.profile)


def test_a_v2_journal_with_a_consumed_receipt_migrates_with_its_children_in_place(
    tmp_path, monkeypatch
):
    # the populated children of the recreated parents: a rejected2 receipt with
    # its consumption and pending consumed outbox (→ consumptions), receipts and
    # heads (→ lifecycle/commands) all survive the rebuild untouched
    from app.tests.deployment_receipt_import_fixture import receipt_context, signed_case
    from app.tests.deployment_prepare_fixture import pre_deployment_catalog

    real = storage._rebuild_v2_as_v3
    gate = {"upgrade": False}
    monkeypatch.setattr(
        storage,
        "_rebuild_v2_as_v3",
        lambda db: real(db) if gate["upgrade"] else None,
    )
    # The genuine held-V2 journal is built by the actual receipt services, not
    # composed with the newly installed route whose constructor requires V6.
    with pre_deployment_catalog(), receipt_context(tmp_path, monkeypatch) as actual:
        prepared, command, _, _ = signed_case(
            actual, monkeypatch, case_name="valid_failed_absent"
        )
        result = actual.service.import_receipt(
            actual.request, prepared["request_id"], command
        )
        assert result["disposition"] == "consumed_non_success"
        with actual.domain._connection() as db:
            assert storage._layout(db) is storage._V2  # held at v2 by the gate
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumptions"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumed_outbox"
                ).fetchone()[0]
                == 1
            )
        before = snapshot_v2(actual.domain)
        gate["upgrade"] = True
        with _writer(), actual.domain._connection(write=True) as db:
            journal = records.install(
                actual.domain, db, actual.profile, candidate_registry=actual.registry
            )
            assert storage._layout(db) is storage._V6
        item = journal["requests"][prepared["request_id"]]
        assert (
            item["consumption"] is not None
            and item["consumed_outbox"]["state"] == "pending"
        )
        after = snapshot_v3(actual.domain)
        after["rows"]["migrations"] = after["rows"]["migrations"][:2]
        for table in ("installations", "installation_heads"):
            assert after["rows"].pop(table) == ()
        assert after == before
        with actual.domain._connection() as db:
            assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        # the ordinary constructor accepts the migrated consumed journal as well
        assert not construct(actual)._unavailable
