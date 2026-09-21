"""Retained deployment integrity is checked independently of current sources."""

import importlib
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest

from app.deployment import prepare_storage as storage
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.domain.refs import canonical_json, parse_canonical
from app.domain.store import _writer
from app.tests.deployment_prepare_fixture import retained_anchor, service_context
from app.tests.test_extension_candidates_persistent import owner


def records_module():
    try:
        return importlib.import_module("app.deployment.prepare_records")
    except ModuleNotFoundError:
        pytest.fail("Retained deployment journal verifier is missing")


def test_empty_journal_can_be_installed_without_sources(tmp_path):
    records = records_module()
    with (
        owner(tmp_path) as (app, _, _, profile, _),
        _writer(),
        app.state.domain_store._connection(write=True) as db,
    ):
        records.install(
            app.state.domain_store,
            db,
            profile,
            candidate_registry=app.state.first_party_exports[
                "extension-candidates.registry"
            ],
        )
        journal = records.verify(app.state.domain_store, db, profile)
        assert journal["requests"] == {}
        assert journal["control"] is None


def test_missing_private_schema_cannot_erase_committed_domain_anchor(tmp_path):
    records = records_module()
    with (
        retained_anchor(tmp_path, pre_deployment=True) as actual,
        _writer(),
        actual.domain._connection(write=True) as db,
    ):
        with pytest.raises(DeploymentPrepareError) as failure:
            records.install(
                actual.domain, db, actual.profile, candidate_registry=actual.registry
            )
        assert failure.value.code == "unavailable"


def corrupt(domain, table, change):
    with sqlite3.connect(domain.path) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA ignore_check_constraints=ON")
        row = dict(
            db.execute(
                "SELECT * FROM deployment_prepare_" + table + " LIMIT 1"
            ).fetchone()
        )
        row.update(change)
        row["hash"] = storage.digest(table, row)
        db.execute(
            "UPDATE deployment_prepare_"
            + table
            + " SET "
            + ",".join(key + "=?" for key in row),
            tuple(row.values()),
        )


@pytest.mark.parametrize(
    "table,change",
    [
        ("control", {"clock_floor_ms": 0}),
        ("control", {"topology_id": str(uuid4())}),
        ("control", {"exchange_id": str(uuid4())}),
        ("control", {"slot_capacity": 2}),
        ("control", {"topology_size": 1}),
        ("control", {"exchange_sha256": "f" * 64}),
        ("control", {"origin_digest": "f" * 64}),
        ("requests", {"extension_id": "another-extension"}),
        ("requests", {"nonce_hex": "f" * 64}),
        ("requests", {"request_digest": "_" * 42 + "8"}),
        ("requests", {"slot_id": 2}),
        ("requests", {"created_ms": 0, "expires_ms": 60000}),
        ("heads", {"lifecycle_hash": "f" * 64}),
        ("lifecycle", {"transitioned_ms": 0}),
        ("lifecycle", {"actor_ref": "{}"}),
        ("commands", {"input_digest": "f" * 64}),
        ("commands", {"input_json": "{}"}),
        ("commands", {"receipt_json": "{}"}),
        ("outbox", {"payload_sha256": "f" * 64}),
        ("outbox", {"payload_size": 1}),
        ("outbox", {"state": "suppressed", "revision": 2}),
    ],
)
def test_rehashed_semantic_corruption_denies_even_unknown_read_on_reopen(
    tmp_path, monkeypatch, table, change
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        actual.service.prepare(actual.request, actual.payload)
        corrupt(actual.domain, table, change)
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        with pytest.raises(DeploymentPrepareError) as failure:
            reopened.read(actual.read_request, str(uuid4()))
        assert failure.value.code == "unavailable"


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM deployment_prepare_requests",
        "DELETE FROM deployment_prepare_heads",
        "DELETE FROM deployment_prepare_lifecycle",
        "DELETE FROM deployment_prepare_commands",
        "DELETE FROM deployment_prepare_outbox",
        "DELETE FROM deployment_prepare_control",
        "DROP TABLE deployment_prepare_heads",
        "UPDATE deployment_prepare_migrations SET checksum='bad'",
        "DELETE FROM domain_record_blobs WHERE source_kind='deployment_request'",
        "DELETE FROM domain_edges WHERE source_kind='deployment_request'",
        "DELETE FROM domain_records WHERE kind='deployment_request'",
        "DELETE FROM api_event_envelopes WHERE event_type='deployment.request_prepared'",
        "UPDATE api_event_envelopes SET event_type='deployment.request_cancelled' WHERE event_type='deployment.request_prepared'",
        "UPDATE deployment_prepare_control SET exchange_identity_json=' { } '",
    ],
)
def test_missing_graph_journal_schema_or_event_is_unavailable(
    tmp_path, monkeypatch, sql
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        actual.service.prepare(actual.request, actual.payload)
        with sqlite3.connect(actual.domain.path) as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(sql)
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        with pytest.raises(DeploymentPrepareError) as failure:
            reopened.read(actual.read_request, str(uuid4()))
        assert failure.value.code == "unavailable"


def test_deleted_all_private_tables_cannot_reset_actual_anchor(tmp_path, monkeypatch):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        actual.service.prepare(actual.request, actual.payload)
        with sqlite3.connect(actual.domain.path) as db:
            for table in (*storage.TABLES, "migrations"):
                db.execute("DROP TABLE deployment_prepare_" + table)
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=actual.topology,
            exchange_source=actual.exchange,
        )
        with pytest.raises(DeploymentPrepareError) as failure:
            reopened.prepare(
                actual.request, {**actual.payload, "command_id": str(uuid4())}
            )
        assert failure.value.code == "unavailable"


def test_unavailable_instance_never_revives_after_database_repair(
    tmp_path, monkeypatch
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        with sqlite3.connect(actual.domain.path) as db:
            before = db.execute(
                "SELECT receipt_json,hash FROM deployment_prepare_commands"
            ).fetchone()
        corrupt(actual.domain, "commands", {"receipt_json": "{}"})
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        with sqlite3.connect(actual.domain.path) as db:
            db.execute(
                "UPDATE deployment_prepare_commands SET receipt_json=?,hash=?", before
            )
        with pytest.raises(DeploymentPrepareError) as failure:
            reopened.read(actual.read_request, receipt["request_id"])
        assert failure.value.code == "unavailable"


def test_empty_private_history_with_orphan_deployment_event_is_unavailable(tmp_path):
    from app.deployment.prepare_lifecycle import event_fields
    from app.domain.public_events import _append_event_in_transaction
    from app.domain.refs import EntityRef

    records = records_module()
    with owner(tmp_path) as (app, _, _, profile, _):
        domain = app.state.domain_store
        with _writer(), domain._connection(write=True) as db:
            records.install(
                domain,
                db,
                profile,
                candidate_registry=app.state.first_party_exports[
                    "extension-candidates.registry"
                ],
            )
            roots = domain._read_roots(db)
            ref = EntityRef("deployment_request", str(uuid4()), 1, "a" * 64)
            _append_event_in_transaction(
                db,
                **event_fields(
                    roots, ref, "expired", 1700000000000, roots.actor, str(uuid4())
                ),
            )
            with pytest.raises(DeploymentPrepareError) as failure:
                records.verify(domain, db, profile)
            assert failure.value.code == "unavailable"


def test_oversized_private_receipt_denied_before_row_materialization(
    tmp_path, monkeypatch
):
    records = records_module()
    with service_context(tmp_path, monkeypatch) as actual:
        actual.service.prepare(actual.request, actual.payload)
        with sqlite3.connect(actual.domain.path) as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                "UPDATE deployment_prepare_commands SET receipt_json=?", ("x" * 8193,)
            )
        original = storage.verify

        def should_not_load(db):
            pytest.fail("Oversized private JSON reached full row loader")

        monkeypatch.setattr(storage, "verify", should_not_load)
        with (
            actual.domain._connection() as db,
            pytest.raises(DeploymentPrepareError) as failure,
        ):
            records.verify(actual.domain, db, actual.profile)
        assert failure.value.code == "unavailable"
        monkeypatch.setattr(storage, "verify", original)


@pytest.mark.parametrize("entrypoint", ["constructor", "records_install"])
@pytest.mark.parametrize(
    "table,column,value",
    [
        ("commands", "receipt_json", "x" * 8193),
        ("commands", "input_json", "x" * 4097),
        ("control", "exchange_identity_json", "x" * 4097),
        ("lifecycle", "actor_ref", "x" * 1025),
        ("migrations", "checksum", "x" * 8193),
        ("control", "revision", "x" * 8193),
        ("lifecycle", "previous_revision", "x" * 8193),
        ("outbox", "published_ms", "x" * 8193),
        ("commands", "input_json", "é" * 2049),
    ],
    ids=[
        "receipt",
        "input",
        "identity",
        "actor",
        "migration",
        "integer",
        "nullable_integer",
        "ack",
        "utf8",
    ],
)
def test_install_preflights_retained_scalars_before_full_loader(
    tmp_path, monkeypatch, entrypoint, table, column, value
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        actual.service.prepare(actual.request, actual.payload)
        with sqlite3.connect(actual.domain.path) as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute(
                "UPDATE deployment_prepare_" + table + " SET " + column + "=?",
                (value,),
            )

        def should_not_load(db):
            pytest.fail("Retained oversized scalar reached full row loader on install")

        monkeypatch.setattr(storage, "verify", should_not_load)
        if entrypoint == "constructor":
            reopened = PersistentDeploymentPrepare(
                actual.domain,
                actual.owner,
                actual.registry,
                topology_source=None,
                exchange_source=None,
            )
            with pytest.raises(DeploymentPrepareError) as failure:
                reopened.read(actual.read_request, str(uuid4()))
        else:
            with (
                _writer(),
                actual.domain._connection(write=True) as db,
                pytest.raises(DeploymentPrepareError) as failure,
            ):
                records_module().install(
                    actual.domain,
                    db,
                    actual.profile,
                    candidate_registry=actual.registry,
                )
        assert failure.value.code == "unavailable"


@pytest.mark.parametrize("entrypoint", ["constructor", "records_install"])
def test_install_routing_preserves_absent_schema_initialization(tmp_path, entrypoint):
    from app.deployment.prepare_service import PersistentDeploymentPrepare
    from app.tests.deployment_prepare_fixture import pre_deployment_catalog

    with pre_deployment_catalog(), owner(tmp_path) as (app, _, request, profile, _):
        domain = app.state.domain_store
        with domain._connection() as db:
            assert storage.shape(db) == {}
        if entrypoint == "constructor":
            service = PersistentDeploymentPrepare(
                domain,
                app.state.owner_authority,
                app.state.first_party_exports["extension-candidates.registry"],
                topology_source=None,
                exchange_source=None,
            )
            with pytest.raises(DeploymentPrepareError) as failure:
                service.read(replace(request, method="GET"), str(uuid4()))
            assert failure.value.code == "not_found"
        else:
            with _writer(), domain._connection(write=True) as db:
                assert (
                    records_module().install(
                        domain,
                        db,
                        profile,
                        candidate_registry=app.state.first_party_exports[
                            "extension-candidates.registry"
                        ],
                    )["requests"]
                    == {}
                )
        with domain._connection() as db:
            # A wholly absent schema installs v1 and migrates forward to the
            # current v6 shape in the same writer.
            assert storage.shape(db) == storage.SHAPE_V6
            assert not any(storage.verify(db).values())


@pytest.mark.parametrize("entrypoint", ["constructor", "records_install"])
def test_install_routing_retains_absent_schema_anchor_guard(tmp_path, entrypoint):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with retained_anchor(tmp_path, pre_deployment=True) as actual:
        with actual.domain._connection() as db:
            assert storage.shape(db) == {}
        if entrypoint == "constructor":
            service = PersistentDeploymentPrepare(
                actual.domain,
                actual.owner,
                actual.registry,
                topology_source=None,
                exchange_source=None,
            )
            with pytest.raises(DeploymentPrepareError) as failure:
                service.read(
                    replace(actual.authenticated_request, method="GET"), str(uuid4())
                )
        else:
            with (
                _writer(),
                actual.domain._connection(write=True) as db,
                pytest.raises(DeploymentPrepareError) as failure,
            ):
                records_module().install(
                    actual.domain,
                    db,
                    actual.profile,
                    candidate_registry=actual.registry,
                )
        assert failure.value.code == "unavailable"
        with actual.domain._connection() as db:
            assert storage.shape(db) == {}


@pytest.mark.parametrize("entrypoint", ["constructor", "records_install"])
@pytest.mark.parametrize(
    "corruption",
    [
        "DROP TABLE deployment_prepare_heads",
        "ALTER TABLE deployment_prepare_commands RENAME COLUMN receipt_json TO invalid_receipt",
    ],
    ids=["missing_table", "missing_column"],
)
def test_install_routing_denies_partial_schema_without_repair(
    tmp_path, monkeypatch, entrypoint, corruption
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with owner(tmp_path) as (app, _, request, profile, _):
        domain = app.state.domain_store
        with _writer(), domain._connection(write=True) as db:
            records_module().install(
                domain,
                db,
                profile,
                candidate_registry=app.state.first_party_exports[
                    "extension-candidates.registry"
                ],
            )
        with sqlite3.connect(domain.path) as db:
            db.execute(corruption)
        with domain._connection() as db:
            before = storage.shape(db)

        def should_not_load(db):
            pytest.fail("Partial private schema reached full row loader on install")

        monkeypatch.setattr(storage, "verify", should_not_load)
        if entrypoint == "constructor":
            service = PersistentDeploymentPrepare(
                domain,
                app.state.owner_authority,
                app.state.first_party_exports["extension-candidates.registry"],
                topology_source=None,
                exchange_source=None,
            )
            with pytest.raises(DeploymentPrepareError) as failure:
                service.read(replace(request, method="GET"), str(uuid4()))
        else:
            with (
                _writer(),
                domain._connection(write=True) as db,
                pytest.raises(DeploymentPrepareError) as failure,
            ):
                records_module().install(
                    domain,
                    db,
                    profile,
                    candidate_registry=app.state.first_party_exports[
                        "extension-candidates.registry"
                    ],
                )
        assert failure.value.code == "unavailable"
        with domain._connection() as db:
            assert storage.shape(db) == before


@pytest.mark.parametrize("kind", ["indices", "candidate_associations"])
def test_oversized_related_candidates_denied_before_inherited_registry_walk(
    tmp_path, monkeypatch, kind
):
    with service_context(tmp_path, monkeypatch) as actual:
        with sqlite3.connect(actual.domain.path) as db:
            if kind == "indices":
                db.row_factory = sqlite3.Row
                original = dict(
                    db.execute("SELECT * FROM extension_candidate_index").fetchone()
                )
                for _ in range(1024):
                    row = {
                        **original,
                        "candidate_id": str(uuid4()),
                        "command_id": str(uuid4()),
                    }
                    db.execute(
                        "INSERT INTO extension_candidate_index ("
                        + ",".join(row)
                        + ") VALUES ("
                        + ",".join("?" for _ in row)
                        + ")",
                        tuple(row.values()),
                    )
            else:
                for index in range(36):
                    db.execute(
                        "INSERT INTO domain_record_blobs VALUES (?,?,?,?,?,?,?)",
                        (
                            actual.domain.vault_id,
                            "extension_manifest",
                            actual.payload["candidate_id"],
                            1,
                            "operational",
                            f"{index:064x}",
                            1,
                        ),
                    )

        def should_not_walk(db):
            pytest.fail(
                "Oversized related collection reached inherited materialization"
            )

        monkeypatch.setattr(actual.registry, "_verify", should_not_walk)
        with pytest.raises(DeploymentPrepareError) as failure:
            actual.service.read(actual.read_request, str(uuid4()))
        assert failure.value.code == "unavailable"


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("lifecycle", "previous_hash", "f" * 64),
        ("lifecycle", "transitioned_ms", 0),
        ("commands", "input_digest", "f" * 64),
        ("commands", "receipt_json", "{}"),
        ("outbox", "payload_sha256", "f" * 64),
        ("outbox", "payload_size", 1),
    ],
)
def test_terminal_successor_command_and_cancel_projection_are_verified_on_reopen(
    tmp_path, monkeypatch, target, field, value
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare

    with service_context(tmp_path, monkeypatch) as actual:
        receipt = actual.service.prepare(actual.request, actual.payload)
        actual.service.cancel(
            actual.request,
            receipt["request_id"],
            {
                "command_id": str(uuid4()),
                "request_digest": receipt["request_digest"],
                "expected_revision": 1,
            },
        )
        selector = {
            "lifecycle": "revision=2",
            "commands": "lifecycle_revision=2",
            "outbox": "role='cancel'",
        }[target]
        with sqlite3.connect(actual.domain.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA ignore_check_constraints=ON")
            row = dict(
                db.execute(
                    "SELECT * FROM deployment_prepare_" + target + " WHERE " + selector
                ).fetchone()
            )
            row[field] = value
            db.execute(
                "UPDATE deployment_prepare_"
                + target
                + " SET "
                + field
                + "=?,hash=? WHERE "
                + selector,
                (value, storage.digest(target, row)),
            )
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        with pytest.raises(DeploymentPrepareError) as failure:
            reopened.read(actual.read_request, receipt["request_id"])
        assert failure.value.code == "unavailable"


def test_extra_actual_domain_anchor_without_index_is_not_hidden_by_valid_first_request(
    tmp_path, monkeypatch
):
    from app.deployment.prepare_service import PersistentDeploymentPrepare
    from app.domain.schemas import ImmutableRecord

    with service_context(tmp_path, monkeypatch) as actual:
        actual.service.prepare(actual.request, actual.payload)
        with actual.domain._connection() as db:
            body = parse_canonical(
                db.execute(
                    "SELECT body FROM domain_records WHERE kind='deployment_request'"
                ).fetchone()[0]
            )
        identity = str(uuid4())
        body["id"] = identity
        body["content"]["request_id"] = identity
        actual.domain.put(ImmutableRecord.from_bytes(canonical_json(body)))
        reopened = PersistentDeploymentPrepare(
            actual.domain,
            actual.owner,
            actual.registry,
            topology_source=None,
            exchange_source=None,
        )
        with pytest.raises(DeploymentPrepareError) as failure:
            reopened.read(actual.read_request, identity)
        assert failure.value.code == "unavailable"
