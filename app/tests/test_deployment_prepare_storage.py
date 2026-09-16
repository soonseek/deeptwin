"""Private SQL enrollment, bounded row integrity and compare-and-swap."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest

from app.domain.public_events import _install_event_schema
from app.domain.refs import canonical_json
from app.domain.store import DomainStore, _writer
from app.storage import Store
from app.tests.test_deployment_prepare_contracts import implementation


@pytest.fixture
def db(tmp_path):
    store = Store(tmp_path / "vault")
    domain = DomainStore(store)
    roots = domain.initialize_vault()
    with _writer(), domain._connection(write=True) as connection:
        _install_event_schema(connection, roots.genesis.id)
    # Raw connection is intentionally FK-off for isolated row/CHECK corruption cases;
    # production storage.verify still performs real foreign_key_check.
    with closing(sqlite3.connect(domain.path)) as connection:
        connection.row_factory = sqlite3.Row
        yield connection
    store.close_verified_handles()


def test_only_wholly_absent_private_schema_installs(db):
    storage = implementation("prepare_storage")
    storage.install(db)
    assert (
        len(
            [
                r
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'deployment_prepare_%'"
                )
            ]
        )
        == 7
    )
    storage.install(db)
    assert (
        db.execute("SELECT count(*) FROM deployment_prepare_migrations").fetchone()[0]
        == 1
    )


def test_deleted_private_schema_cannot_restore_absence(db):
    storage = implementation("prepare_storage")
    storage.install(db)
    db.execute("UPDATE domain_records SET kind='deployment_request' WHERE kind='actor'")
    for suffix in reversed(("migrations", *storage.TABLES)):
        db.execute("DROP TABLE deployment_prepare_" + suffix)
    with pytest.raises(implementation().DeploymentPrepareError):
        storage.install(db)
    assert (
        db.execute(
            "SELECT count(*) FROM domain_records WHERE kind='deployment_request'"
        ).fetchone()[0]
        == 1
    )
    assert not storage.shape(db)


@pytest.mark.parametrize(
    "damage", ["partial", "checksum", "renamed_index", "trigger", "foreign_view"]
)
def test_schema_corruption_never_reinstalled(db, damage):
    storage = implementation("prepare_storage")
    storage.install(db)
    if damage == "partial":
        db.execute("DROP TABLE deployment_prepare_outbox")
    elif damage == "checksum":
        db.execute("UPDATE deployment_prepare_migrations SET checksum=?", ("f" * 64,))
    elif damage == "renamed_index":
        db.execute(
            "CREATE INDEX unrelated_name ON deployment_prepare_requests(slot_id)"
        )
    elif damage == "foreign_view":
        db.execute(
            "CREATE VIEW unrelated_view AS SELECT * FROM deployment_prepare_requests"
        )
    else:
        db.execute(
            "CREATE TRIGGER unrelated_trigger AFTER INSERT ON domain_records BEGIN SELECT 1; END"
        )
    with pytest.raises(implementation().DeploymentPrepareError):
        storage.install(db)


def test_sql_null_predecessor_does_not_pass_three_valued_check(db):
    storage = implementation("prepare_storage")
    storage.install(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO deployment_prepare_lifecycle VALUES(?,2,NULL,?,'cancelled',0,?,?,?,?)",
            (str(uuid4()), "a" * 64, "{}", str(uuid4()), str(uuid4()), "b" * 64),
        )


def request_row():
    return {
        "request_id": str(uuid4()),
        "vault_id": str(uuid4()),
        "kind": "deployment_request",
        "version": 1,
        "anchor_digest": "a" * 64,
        "request_digest": "A" * 43,
        "nonce_hex": "b" * 64,
        "topology_id": str(uuid4()),
        "slot_id": 1,
        "reservation_revision": 1,
        "extension_id": "synthetic-tool",
        "created_ms": 0,
        "expires_ms": 60000,
    }


@pytest.mark.parametrize(
    "field,bad",
    [
        ("created_ms", True),
        ("expires_ms", 59999),
        ("slot_id", 0),
        ("request_digest", "A" * 42 + "B"),
        ("nonce_hex", "F" * 64),
        ("request_id", "00000000-0000-0000-0000-000000000000"),
        ("extension_id", "not a valid id"),
    ],
)
def test_row_validation_rejects_rehashed_invalid_scalars(db, field, bad):
    storage = implementation("prepare_storage")
    storage.install(db)
    value = request_row()
    value[field] = bad
    with pytest.raises(implementation().DeploymentPrepareError):
        storage.insert(db, "requests", value)


def test_row_hash_binds_table_and_all_nonhash_columns(db):
    storage = implementation("prepare_storage")
    storage.install(db)
    value = request_row()
    row = storage.insert(db, "requests", value)
    storage.validate_row("requests", row)
    db.execute("UPDATE deployment_prepare_requests SET extension_id='altered'")
    damaged = dict(db.execute("SELECT * FROM deployment_prepare_requests").fetchone())
    with pytest.raises(implementation().DeploymentPrepareError):
        storage.validate_row("requests", damaged)
    with pytest.raises(implementation().DeploymentPrepareError):
        storage.verify(db)
    assert row["hash"] != storage.digest("requests", {**value, "slot_id": 2})


def test_outbox_cas_requires_old_hash_and_revision_and_closed_columns(db):
    storage = implementation("prepare_storage")
    storage.install(db)
    old = storage.insert(
        db,
        "outbox",
        {
            "request_id": str(uuid4()),
            "role": "request",
            "lifecycle_revision": 1,
            "payload_sha256": "a" * 64,
            "payload_size": 100,
            "state": "pending",
            "published_ms": None,
            "revision": 1,
        },
    )
    new = storage.advance(
        db, "outbox", old, {"state": "published", "published_ms": 123}
    )
    assert new["revision"] == 2 and new["published_ms"] == 123
    with pytest.raises(implementation().DeploymentPrepareError):
        storage.advance(
            db, "outbox", old, {"state": "suppressed", "published_ms": None}
        )
    with pytest.raises(implementation().DeploymentPrepareError):
        storage.advance(db, "outbox", new, {"payload_size": 200})


def test_control_rejects_noncanonical_or_open_continuity_identity():
    storage = implementation("prepare_storage")
    value = {
        "schema_version": "deployment-outbox-identity-v1",
        "root": {"device": 1, "inode": 2},
        "requests": {"device": 1, "inode": 3},
        "cancelled": {"device": 1, "inode": 4},
        "backing_root_digest": "a" * 64,
    }
    storage.validate_identity(canonical_json(value).decode())
    for bad in [
        canonical_json(value).decode() + " ",
        canonical_json({**value, "extra": 1}).decode(),
        canonical_json({**value, "root": {"device": 1, "inode": True}}).decode(),
    ]:
        with pytest.raises(implementation().DeploymentPrepareError):
            storage.validate_identity(bad)


def test_actual_domain_anchor_prevents_reenrollment_even_without_private_index(
    tmp_path,
):
    from app.tests.deployment_prepare_fixture import retained_anchor

    storage = implementation("prepare_storage")
    with retained_anchor(tmp_path, pre_deployment=True) as fixture:
        domain = fixture.domain
        loaded = domain.get(fixture.record.ref)
        assert loaded == fixture.record
        assert (
            loaded.body["content"]["request_blob_ref"]["sha256"]
            != fixture.record.ref.sha256
        )
        with _writer(), domain._connection(write=True) as connection:
            with pytest.raises(implementation().DeploymentPrepareError):
                storage.install(connection)
            assert not storage.shape(connection)
            assert (
                connection.execute(
                    "SELECT count(*) FROM domain_records WHERE kind='deployment_request'"
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM domain_record_blobs WHERE source_kind='deployment_request'"
                ).fetchone()[0]
                == 3
            )


def test_actual_domain_anchor_cannot_dereference_missing_blob_association(tmp_path):
    from app.domain.store import StorageError
    from app.tests.deployment_prepare_fixture import retained_anchor

    with retained_anchor(tmp_path) as fixture:
        with _writer(), fixture.domain._connection(write=True) as connection:
            connection.execute(
                "DELETE FROM domain_record_blobs WHERE source_kind='deployment_request'"
            )
        with pytest.raises(StorageError):
            fixture.domain.get(fixture.record.ref)


def test_control_cas_cannot_succeed_after_same_revision_hash_change(db):
    storage = implementation("prepare_storage")
    storage.install(db)
    old = storage.insert(
        db,
        "outbox",
        {
            "request_id": str(uuid4()),
            "role": "request",
            "lifecycle_revision": 1,
            "payload_sha256": "a" * 64,
            "payload_size": 100,
            "state": "pending",
            "published_ms": None,
            "revision": 1,
        },
    )
    changed = {**old, "payload_size": 101}
    db.execute(
        "UPDATE deployment_prepare_outbox SET payload_size=?,hash=?",
        (101, storage.digest("outbox", changed)),
    )
    with pytest.raises(implementation().DeploymentPrepareError):
        storage.advance(db, "outbox", old, {"state": "published", "published_ms": 1})
    assert (
        db.execute("SELECT state FROM deployment_prepare_outbox").fetchone()[0]
        == "pending"
    )


@pytest.mark.parametrize("operation", ["expected", "valid_row", "invalid_row"])
def test_transient_sql_validation_connections_close_before_return(
    monkeypatch, operation
):
    storage = implementation("prepare_storage")
    original_connect = sqlite3.connect
    connections = []

    def capture_connection(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", capture_connection)
    try:
        if operation == "expected":
            storage._expected()
        else:
            row = request_row()
            if operation == "invalid_row":
                row["slot_id"] = 0
            row["hash"] = storage.digest("requests", row)
            if operation == "invalid_row":
                with pytest.raises(implementation().DeploymentPrepareError):
                    storage.validate_row("requests", row)
            else:
                storage.validate_row("requests", row)
        assert connections
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
    finally:
        for connection in connections:
            connection.close()
