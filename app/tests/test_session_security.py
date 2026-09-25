"""Session security across an owner recovery (recovery port design §1–§5, approved 2026-09-24):
the private auth store's v1→v2 rebuild, CSRF bound to the root generation, and a replayed
request nonce that must never open a later epoch. Offline fixtures only.
"""

import os
import sqlite3
from base64 import urlsafe_b64decode

import pytest
from fastapi.testclient import TestClient

from app.domain.refs import parse_canonical
from app.operations.session_root import open_session_root
from app.server import create_app
from app.services import owner_auth_storage as storage
from app.services.service_clients import (
    PersistentServiceClientRegistry,
    ServiceClientDenied,
)
from app.tests.recovery_fixture import Recovery
from app.tests.test_owner_sessions import (
    NEW_PASSWORD,
    bootstrap,
    epoch_one,
    recovered_app,
    rows,
)
from app.tests.test_web_owner_integration import headers

V1_CONTROL = {"singleton": 1, "vault_id": "a" * 8 + "-aaaa-4aaa-8aaa-" + "a" * 12, "instance_id": "1" * 32,
              "origin_digest": "2" * 64, "generation_id": "b" * 8 + "-bbbb-4bbb-8bbb-" + "b" * 12,
              "key_id": "c" * 8 + "-cccc-4ccc-8ccc-" + "c" * 12, "manifest_digest": "3" * 64, "epoch": 1,
              "opened_at": 1_000, "deadline": 601_000, "clock_floor": 1_500, "revision": 2}


def v1_store():
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for statement in storage._DDL:
        db.execute(statement)
    db.execute("INSERT INTO owner_auth_migrations VALUES(1,?)", (storage.CHECKSUM,))

    def put(table, values):
        row = {**values, "hash": storage.digest(values)}
        db.execute(f"INSERT INTO owner_auth_{table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                   tuple(row.values()))
        return row

    put("control", V1_CONTROL)
    claim = put("bootstrap_claims", {"epoch": 1, "verifier": "V" * 43, "attempts": 1, "state": "available",
                                     "claim_id": None, "consumed_at": None, "completed_at": None, "revision": 2})
    audit = put("audit", {"sequence": 1, "kind": "opened", "entity_id": None, "observed_at": 1_000,
                          "previous_hash": None})
    return db, claim, audit


def test_a_verified_v1_auth_store_is_rebuilt_as_v2_with_every_row_kept():
    db, claim, audit = v1_store()
    db.execute("BEGIN IMMEDIATE")
    storage.install(db)
    db.execute("COMMIT")
    assert [tuple(row) for row in db.execute("SELECT * FROM owner_auth_migrations ORDER BY version")] == [
        (1, storage.CHECKSUM), (2, storage.CHECKSUM_V2)]
    control = dict(storage.current_control(db))
    assert {key: control[key] for key in V1_CONTROL if key != "singleton"} == {
        key: value for key, value in V1_CONTROL.items() if key != "singleton"}
    assert (control["previous_epoch"], control["recovery_request_id"], control["recovery_receipt_digest"]) == (
        None, None, None)
    assert dict(db.execute("SELECT * FROM owner_auth_bootstrap_claims").fetchone()) == claim
    assert dict(db.execute("SELECT * FROM owner_auth_audit").fetchone()) == audit
    # the rebuilt layout is exactly the declared v2 shape and re-verifies on the next open
    storage.install(db)
    # the v2 control keeps one row per epoch; an epoch-2 row must name its recovery
    with pytest.raises(sqlite3.IntegrityError):
        storage.insert(db, "control", {**{key: value for key, value in control.items() if key != "hash"},
                                       "epoch": 2, "previous_epoch": 1, "generation_id": "x", "key_id": "y",
                                       "manifest_digest": "z"})


@pytest.mark.parametrize("damage", ["row", "migration", "foreign_table"])
def test_a_damaged_v1_auth_store_is_never_rebuilt(damage):
    db, _, _ = v1_store()
    if damage == "row":
        db.execute("UPDATE owner_auth_bootstrap_claims SET attempts=0")
    elif damage == "migration":
        db.execute("UPDATE owner_auth_migrations SET checksum='0'")
    else:
        db.execute("CREATE INDEX owner_auth_unregistered ON owner_auth_audit(kind)")
    before = [tuple(row) for row in db.execute("SELECT name, sql FROM sqlite_master ORDER BY name")]
    db.execute("BEGIN IMMEDIATE")
    with pytest.raises(storage.AuthStorageError):
        storage.install(db)
    db.execute("ROLLBACK")
    assert [tuple(row) for row in db.execute("SELECT name, sql FROM sqlite_master ORDER BY name")] == before


def test_the_old_csrf_token_and_cookie_never_authenticate_under_the_recovered_root(tmp_path):
    state = epoch_one(tmp_path)
    recovery = Recovery(state.profile, state.arguments)
    recovery.advance()
    handle = open_session_root(state.arguments["session_root_dir"], profile=state.profile, recovery_epoch=2,
                               expected_uid=os.getuid(), expected_gid=os.getgid())
    try:
        # the recovered generation has its own key and epoch: the old token derives new CSRF
        assert handle.derive_csrf(state.cookie) != state.csrf
    finally:
        handle.close()
    app = recovered_app(tmp_path, state, recovery)
    path = state.profile.base_path
    with TestClient(app, base_url=state.profile.http_origin) as client:
        client.cookies.set(state.cookie_name, state.cookie)
        for method, target in (("get", "session"), ("get", "api/v1/snapshot")):
            assert getattr(client, method)(path + target, headers=headers(state.profile)).status_code == 401
        logout = client.post(path + "session/logout", headers=headers(state.profile, state.csrf),
                             json={"command_id": "d" * 8 + "-dddd-4ddd-8ddd-" + "d" * 12})
        assert logout.status_code in {401, 403}
        client.cookies.clear()
        created = bootstrap(client, state.profile, recovery.capability)
        assert created.status_code == 201 and created.json()["csrf_token"] != state.csrf
        # the recovered owner's new session works; a second bootstrap is refused
        assert client.get(path + "session", headers=headers(state.profile)).status_code == 200
        assert bootstrap(client, state.profile, recovery.capability).status_code == 409


@pytest.mark.parametrize("replayed", [False, True])
def test_a_replayed_request_nonce_never_opens_a_later_epoch(tmp_path, replayed):
    state = epoch_one(tmp_path)
    first = Recovery(state.profile, state.arguments)
    first.advance()
    with TestClient(recovered_app(tmp_path, state, first), base_url=state.profile.http_origin) as client:
        assert bootstrap(client, state.profile, first.capability).status_code == 201
    # a correctly signed 2->3 request; the replay reuses the first request's nonce
    nonce = urlsafe_b64decode(parse_canonical(first.request)["request_nonce"] + "=") if replayed else None
    second = Recovery(state.profile, first.arguments, epoch=2, signer=first.signer, nonce=nonce)
    # the root keeps no nonce history, so it advances either way; the database decides
    assert second.advance()["recovery_epoch"] == 3
    before = rows(tmp_path, "SELECT * FROM owner_auth_control")
    if replayed:
        with pytest.raises(Exception):  # noqa: B017 - the start fails closed whatever it reports
            create_app(tmp_path / "data", **second.arguments, recovery_trust_set=second.trust)
        assert rows(tmp_path, "SELECT * FROM owner_auth_control") == before
        return
    with TestClient(create_app(tmp_path / "data", **second.arguments, recovery_trust_set=second.trust),
                    base_url=state.profile.http_origin) as client:
        assert bootstrap(client, state.profile, second.capability, password=NEW_PASSWORD + " 3").status_code == 201
    assert rows(tmp_path, "SELECT epoch, previous_epoch FROM owner_auth_control ORDER BY epoch") == [
        (1, None), (2, 1), (3, 2)]


def test_the_in_transaction_service_client_revocation_only_moves_the_epoch_forward(tmp_path):
    from app.storage import Store

    store = Store(tmp_path)
    PersistentServiceClientRegistry(store, verify_owner=lambda _c: None, verify_recovery=lambda _c: False,
                                    clock=lambda: 1_000, random_bytes=os.urandom)
    with store._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        for expected, new in ((0, 0), (1, 2), (-1, 3)):
            with pytest.raises(ServiceClientDenied):
                PersistentServiceClientRegistry._revoke_all_in_transaction(
                    db, expected_epoch=expected, new_epoch=new, now=1_000)
        assert PersistentServiceClientRegistry._revoke_all_in_transaction(
            db, expected_epoch=0, new_epoch=2, now=1_000) == 0
        db.execute("COMMIT")
    with store._connection() as db:
        assert db.execute("SELECT recovery_epoch FROM service_client_control").fetchone()[0] == 2
