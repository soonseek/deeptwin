"""Storage, owner revocation, competing writers and bounded inert failure evidence."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from threading import Barrier, local
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.router_composition import RouteCompositionError
from app.domain.public_events import EventCorrupt
from app.domain.refs import canonical_json
from app.domain.store import DomainStore, StorageError, _writer
from app.extensions import candidate_storage as storage
from app.extensions.candidate_contracts import CandidateError
from app.extensions.persistence import PersistentCandidateRegistry
from app.server import create_app
from app.services.owner_auth import OwnerAuthError
from app.services.owner_auth_storage import AuthStorageError
from app.tests.extension_candidate_fixture import candidate_payload
from app.tests.test_web_owner_integration import (
    bootstrap_client,
    bound_request,
    configured,
)


@contextmanager
def owner(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        request = bound_request(app, client, profile, csrf)
        yield app, client, request, profile, arguments


def counts(domain):
    with domain._connection() as db:
        return tuple(
            db.execute(query).fetchone()[0]
            for query in (
                "SELECT count(*) FROM extension_candidate_index",
                "SELECT count(*) FROM extension_candidate_commands",
                "SELECT count(*) FROM domain_records WHERE kind='extension_manifest'",
                "SELECT count(*) FROM api_event_envelopes WHERE event_type='extension.candidate_registered'",
                "SELECT candidate_count FROM extension_candidate_control",
            )
        )


@pytest.mark.parametrize(
    "stage", ["content", "anchor", "association", "index", "accounting", "event", "receipt", "precommit"]
)
def test_failure_rolls_back_all_candidate_authority_but_presealed_blobs_can_remain(tmp_path, monkeypatch, stage):
    from app.extensions import persistence

    with owner(tmp_path) as (app, _client, request, profile, args):
        registry, domain = app.state.first_party_exports["extension-candidates.registry"], app.state.domain_store
        before = counts(domain)

        def fail():
            raise RuntimeError("private-host-path-secret-must-not-escape")

        if stage == "content":
            original = domain.put_blob

            def patched(*args, **kwargs):
                original(*args, **kwargs)
                fail()

            monkeypatch.setattr(domain, "put_blob", patched)
        elif stage in {"anchor", "association"}:
            name = "_put_in_transaction" if stage == "anchor" else "_insert"
            original = getattr(domain, name)

            def patched(*args, **kwargs):
                original(*args, **kwargs)
                fail()

            monkeypatch.setattr(domain, name, patched)
        elif stage in {"index", "accounting", "receipt"}:
            original = storage.insert
            target = {"index": "index", "accounting": "contents", "receipt": "commands"}[stage]

            def patched(db, table, values):
                result = original(db, table, values)
                if table == target:
                    fail()
                return result

            monkeypatch.setattr(storage, "insert", patched)
        elif stage == "event":
            original = persistence._append_event_in_transaction

            def patched(*args, **kwargs):
                original(*args, **kwargs)
                fail()

            monkeypatch.setattr(persistence, "_append_event_in_transaction", patched)
        else:
            original = registry._verify

            def patched(db):
                result = original(db)
                if db.execute("SELECT count(*) FROM extension_candidate_commands").fetchone()[0]:
                    fail()
                return result

            monkeypatch.setattr(registry, "_verify", patched)
        with pytest.raises(CandidateError) as failure:
            registry.register(request, candidate_payload())
        assert failure.value.code == "unavailable" and "secret" not in str(failure.value)
        assert counts(domain) == before == (0, 0, 0, 0, 0)
        with domain._connection() as db:
            assert db.execute("SELECT count(*) FROM domain_blobs").fetchone()[0] > 0
        monkeypatch.undo()
    reopened = create_app(tmp_path / "data", **args)
    with TestClient(reopened, base_url=profile.http_origin):
        assert counts(reopened.state.domain_store) == before


@pytest.mark.parametrize(
    "change", ["copied_session", "read_method", "no_csrf", "bool_csrf", "wrong_host", "wrong_origin"]
)
def test_service_requires_real_owner_mutating_request_before_blob_work(tmp_path, change):
    with owner(tmp_path) as (app, _client, request, _profile, _args):
        request = {
            "copied_session": lambda: replace(request, session=replace(request.session)),
            "read_method": lambda: replace(request, method="GET"),
            "no_csrf": lambda: replace(request, csrf_verified=False),
            "bool_csrf": lambda: replace(request, csrf_verified=1),
            "wrong_host": lambda: replace(request, host="elsewhere"),
            "wrong_origin": lambda: replace(request, origin=None),
        }[change]()
        with pytest.raises(OwnerAuthError):
            app.state.first_party_exports["extension-candidates.registry"].register(request, candidate_payload())
        assert counts(app.state.domain_store) == (0, 0, 0, 0, 0)
        with app.state.domain_store._connection() as db:
            assert db.execute("SELECT count(*) FROM domain_blobs").fetchone()[0] == 0


def test_revoke_after_initial_auth_before_final_writer_denies_registration(tmp_path, monkeypatch):
    with owner(tmp_path) as (app, client, request, _profile, _args):
        domain = app.state.domain_store
        original = domain.put_blob
        revoked = []

        def revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            if not revoked:
                revoked.append(True)
                app.state.owner_authority.logout(
                    request, command_id=str(uuid4()), token_b64u=client.cookies[app.state.owner_authority.cookie_name]
                )
            return result

        monkeypatch.setattr(domain, "put_blob", revoke)
        with pytest.raises(OwnerAuthError, match="unauthenticated"):
            app.state.first_party_exports["extension-candidates.registry"].register(request, candidate_payload())
        assert counts(domain) == (0, 0, 0, 0, 0)


def test_exact_replay_reauthenticates_and_preseal_is_skipped(tmp_path, monkeypatch):
    with owner(tmp_path) as (app, client, request, _profile, _args):
        registry = app.state.first_party_exports["extension-candidates.registry"]
        payload = candidate_payload()
        receipt = registry.register(request, payload)

        def forbidden(*args, **kwargs):
            pytest.fail("exact replay unexpectedly sealed content")

        monkeypatch.setattr(app.state.domain_store, "put_blob", forbidden)
        assert registry.register(request, payload) == receipt
        app.state.owner_authority.logout(
            request, command_id=str(uuid4()), token_b64u=client.cookies[app.state.owner_authority.cookie_name]
        )
        with pytest.raises(OwnerAuthError, match="unauthenticated"):
            registry.register(request, payload)
        assert counts(app.state.domain_store) == (1, 1, 1, 1, 1)


@pytest.mark.parametrize("same_command", [True, False])
def test_competing_final_writers_replay_or_capacity_with_one_event(tmp_path, monkeypatch, same_command):
    from app.extensions import persistence

    with owner(tmp_path) as (app, _client, request, _profile, _args):
        registry, domain = app.state.first_party_exports["extension-candidates.registry"], app.state.domain_store
        if not same_command:
            monkeypatch.setattr(persistence, "MAX_CANDIDATES", 1)
        payload = candidate_payload()
        second = deepcopy(payload)
        if not same_command:
            second["command_id"] = str(uuid4())
        barrier = Barrier(2)
        state = local()
        original = domain.put_blob

        def meet(*args, **kwargs):
            result = original(*args, **kwargs)
            if not getattr(state, "met", False):
                state.met = True
                barrier.wait(timeout=10)
            return result

        monkeypatch.setattr(domain, "put_blob", meet)

        def register(value):
            try:
                return registry.register(request, value)
            except CandidateError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(register, (payload, second)))
        if same_command:
            assert results[0] == results[1] and isinstance(results[0], dict)
        else:
            assert sum(isinstance(r, dict) for r in results) == 1 and "capacity" in results
        assert counts(domain) == (1, 1, 1, 1, 1)


def test_finite_capacity_boundaries_and_unique_content():
    assert storage.CHECKSUM == "6f5cd856b54e8805dbbd44c07887f503c625d1c3733f22fb86920b83e85c6715"
    raw = b"a" * 65536
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE extension_candidate_contents(sha256 TEXT,size INTEGER)")
        assert (
            PersistentCandidateRegistry._capacity(
                db, {"candidate_count": 1023, "content_bytes": 67108864 - 65536}, [raw, raw]
            )
            == 65536
        )
        for control in (
            {"candidate_count": 1024, "content_bytes": 0},
            {"candidate_count": 1023, "content_bytes": 67108864 - 65535},
        ):
            with pytest.raises(CandidateError) as failure:
                PersistentCandidateRegistry._capacity(db, control, [raw])
            assert failure.value.code == "capacity"
        db.execute("INSERT INTO extension_candidate_contents VALUES(?,?)", (sha256(raw).hexdigest(), len(raw)))
        assert (
            PersistentCandidateRegistry._capacity(db, {"candidate_count": 1023, "content_bytes": 67108864}, [raw]) == 0
        )


def test_shared_content_counts_once_and_input_document_order_survives(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _args):
        registry, domain = app.state.first_party_exports["extension-candidates.registry"], app.state.domain_store
        payload = candidate_payload()
        payload["documents"].reverse()
        first = registry.register(request, payload)
        with domain._connection() as db:
            first_bytes = db.execute("SELECT content_bytes FROM extension_candidate_control").fetchone()[0]
        payload["command_id"] = str(uuid4())
        second = registry.register(request, payload)
        read = registry.read(replace(request, method="GET"), second["candidate_ref"]["candidate_id"])
        assert read["documents"] == payload["documents"]
        with domain._connection() as db:
            second_bytes = db.execute("SELECT content_bytes FROM extension_candidate_control").fetchone()[0]
            assert db.execute("SELECT revision FROM extension_candidate_control").fetchone()[0] == 3
        assert second_bytes - first_bytes == len(canonical_json(read["registration"]))
        read["documents"].clear()
        read["manifest"]["source"]["locator"] = "changed"
        assert (
            registry.read(replace(request, method="GET"), second["candidate_ref"]["candidate_id"])["documents"]
            == payload["documents"]
        )
        assert first["candidate_ref"] != second["candidate_ref"]


@pytest.mark.parametrize(
    "corruption",
    [
        "checksum",
        "schema",
        "row_hash",
        "index",
        "receipt",
        "content",
        "association",
        "blob",
        "event",
        "event_schema",
        "trigger",
    ],
)
def test_corruption_fails_read_unknown_register_and_cold_reopen(tmp_path, corruption):
    with owner(tmp_path) as (app, _client, request, _profile, args):
        registry, domain = app.state.first_party_exports["extension-candidates.registry"], app.state.domain_store
        receipt = registry.register(request, candidate_payload())
        with _writer(), domain._connection(write=True) as db:
            if corruption == "checksum":
                db.execute("UPDATE extension_candidate_migrations SET checksum=?", ("f" * 64,))
            elif corruption == "schema":
                db.execute("CREATE INDEX extension_candidate_extra ON extension_candidate_contents(size)")
            elif corruption == "event_schema":
                db.execute("ALTER TABLE api_event_envelopes ADD COLUMN unexpected TEXT")
            elif corruption == "trigger":
                db.execute(
                    "CREATE TRIGGER extension_candidate_trigger AFTER INSERT ON extension_candidate_contents BEGIN SELECT 1; END"
                )
            elif corruption == "row_hash":
                db.execute("UPDATE extension_candidate_control SET hash=?", ("f" * 64,))
            elif corruption in {"index", "receipt", "content"}:
                table = {"index": "index", "receipt": "commands", "content": "contents"}[corruption]
                row = dict(db.execute("SELECT * FROM extension_candidate_" + table + " LIMIT 1").fetchone())
                key, bad = {
                    "index": ("descriptor_digest", "f" * 64),
                    "receipt": ("receipt", "{}"),
                    "content": ("size", 1),
                }[corruption]
                row[key] = bad
                db.execute(
                    "UPDATE extension_candidate_" + table + " SET " + key + "=?,hash=?",
                    (bad, storage.digest(table, row)),
                )
            elif corruption == "association":
                db.execute("DELETE FROM domain_record_blobs WHERE source_kind='extension_manifest'")
            elif corruption == "blob":
                db.execute("UPDATE domain_blobs SET size=size+1")
            elif corruption == "event":
                event = db.execute(
                    "SELECT envelope FROM api_event_envelopes WHERE event_type='extension.candidate_registered'"
                ).fetchone()[0]
                value = json.loads(event)
                value["public_metadata"]["byte_count"] = 1
                db.execute(
                    "UPDATE api_event_envelopes SET envelope=? WHERE event_type='extension.candidate_registered'",
                    (canonical_json(value),),
                )
        for action in (
            lambda: registry.read(replace(request, method="GET"), receipt["candidate_ref"]["candidate_id"]),
            lambda: registry.read(replace(request, method="GET"), str(uuid4())),
            lambda: registry.register(request, candidate_payload()),
        ):
            with pytest.raises((CandidateError, OwnerAuthError)):
                action()
    with pytest.raises((CandidateError, OwnerAuthError, StorageError, EventCorrupt, AuthStorageError, RouteCompositionError)):
        create_app(tmp_path / "data", **args)


def test_registry_cannot_rebind_copied_or_different_domain_authority(tmp_path):
    with owner(tmp_path) as (app, _client, _request, _profile, _args):
        with pytest.raises(CandidateError):
            PersistentCandidateRegistry(DomainStore(app.state.store), app.state.owner_authority)
        with pytest.raises(CandidateError):
            PersistentCandidateRegistry(app.state.domain_store, object())


def test_control_cas_requires_exact_expected_revision_and_closed_identifiers(tmp_path):
    with (
        owner(tmp_path) as (app, _client, _request, _profile, _args),
        _writer(),
        app.state.domain_store._connection(write=True) as db,
    ):
        old = dict(db.execute("SELECT * FROM extension_candidate_control").fetchone())
        storage.advance(db, old, candidate_count=0, content_bytes=0)
        with pytest.raises(CandidateError):
            storage.advance(db, old, candidate_count=0, content_bytes=0)
        with pytest.raises(CandidateError):
            storage.insert(db, "control; DROP TABLE domain_records", {})


def test_old_process_session_identity_cannot_register_or_read_after_reopen(tmp_path):
    with owner(tmp_path) as (app, _client, request, profile, args):
        receipt = app.state.first_party_exports["extension-candidates.registry"].register(request, candidate_payload())
    reopened = create_app(tmp_path / "data", **args)
    with TestClient(reopened, base_url=profile.http_origin):
        with pytest.raises(OwnerAuthError, match="unauthenticated"):
            reopened.state.first_party_exports["extension-candidates.registry"].register(request, candidate_payload())
        with pytest.raises(OwnerAuthError, match="unauthenticated"):
            reopened.state.first_party_exports["extension-candidates.registry"].read(
                replace(request, method="GET"), receipt["candidate_ref"]["candidate_id"]
            )
        assert counts(reopened.state.domain_store) == (1, 1, 1, 1, 1)


def test_different_instance_control_fails_without_bootstrapping_another_owner(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _args):
        with _writer(), app.state.domain_store._connection(write=True) as db:
            row = dict(db.execute("SELECT * FROM extension_candidate_control").fetchone())
            row["instance_id"] = "f" * 32
            db.execute(
                "UPDATE extension_candidate_control SET instance_id=?,hash=?",
                (row["instance_id"], storage.digest("control", row)),
            )
        with pytest.raises(CandidateError) as failure:
            app.state.first_party_exports["extension-candidates.registry"].register(request, candidate_payload())
        assert failure.value.code == "unavailable"
        assert counts(app.state.domain_store) == (0, 0, 0, 0, 0)


def test_receipt_remains_immutable_when_event_stream_generation_advances(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _args):
        registry = app.state.first_party_exports["extension-candidates.registry"]
        value = candidate_payload()
        receipt = registry.register(request, value)
        # Same valid transition as the public journal's retained-history gap operation.
        with _writer(), app.state.domain_store._connection(write=True) as db:
            db.execute(
                "UPDATE api_event_streams SET generation=generation+1,first_available_sequence=2,gap_reason='deleted'"
            )
        assert registry.register(request, value) == receipt
        read = registry.read(replace(request, method="GET"), receipt["candidate_ref"]["candidate_id"])
        assert {k: read[k] for k in receipt} == receipt
