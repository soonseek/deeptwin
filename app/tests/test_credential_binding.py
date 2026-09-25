"""T090 provider-connection binding CAS, catalog/model authority invalidation,
`unbound_orphan` cleanup and the unknown-command fence, full stack.

Every request crosses the real development app (session, CSRF, ingress checks),
the control-plane command ledger, the frame-only `CredentialGatewayClient` and real
authenticated broker frames on socket pairs into `CredentialGatewayService` and an
encrypted `CredentialVault` (the harness of test_credential_routes_v2). The vault
journal is the custody oracle; the ledger is the binding/catalog oracle.
"""

from __future__ import annotations

import http.client
import json
import logging
import socket
import sqlite3
from uuid import uuid4

import pytest

from app.api.credential_commands import (
    CredentialCommandError,
    CredentialCommandLedger,
    record_of,
)
from app.api.credential_routes import attach_credential_gateway
from app.tests.local_http import LocalTestClient
from app.tests.test_credential_gateway_persistence import Gateway
from app.tests.test_credential_routes import make_app
from app.tests.test_credential_routes_v2 import Spy, create, delete, intent, vault_meta
from app.tests.test_server_api_v1 import FETCH, ORIGIN, assert_error
from app.workers import credential_gateway_service
from app.workers.credential_channel import GatewayServiceError

FIRST = "sk-synthetic-binding-first-0001"
SECOND = "sk-synthetic-binding-second-0002"
THIRD = "sk-synthetic-binding-third-0003"
LATE = "sk-synthetic-binding-late-0004"
SECRETS = (FIRST, SECOND, THIRD, LATE)
MODELS = ["synthetic-model-a", "synthetic-model-b"]


class Clock:
    def __init__(self):
        self.now = 1_900_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def bench(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    (tmp_path / "gateway").mkdir()
    gateway = Gateway(tmp_path / "gateway")
    spy = Spy(gateway.client())
    clock = Clock()
    ledger = CredentialCommandLedger(tmp_path / "credential-commands.sqlite3", clock=clock)
    application = make_app(tmp_path / "app")
    attach_credential_gateway(application, spy, ledger)
    original = credential_gateway_service._write_logical_connection
    armed = []

    def reply(connection, **kwargs):
        if armed:
            armed.pop()
            connection.close()  # the committed result never reaches the control plane
            return None
        return original(connection, **kwargs)

    monkeypatch.setattr(credential_gateway_service, "_write_logical_connection", reply)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        yield {"client": client, "gateway": gateway, "spy": spy, "ledger": ledger, "clock": clock,
               "lose": lambda count=1: armed.extend([True] * count)}
    gateway.close()
    for secret in SECRETS:
        assert secret not in caplog.text
    for path in tmp_path.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for secret in SECRETS:
                assert secret.encode() not in data, path


def clean(response):
    for secret in SECRETS:
        assert secret not in response.text
    return response


def status(client):
    response = client.get("/api/v1/credentials", headers=FETCH)
    assert response.status_code == 200, response.text
    return response.json()


def fence(client, act):
    return client.post("/api/v1/credentials/fences", content=json.dumps({"intent_id": act}),
                       headers={**FETCH, "X-CSRF-Token": client.csrf_token,
                                "Content-Type": "application/json"})


def retirements(gateway):
    path = gateway.args["records_directory"] / "journal.sqlite"
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        return sorted((body["record"]["record_version"], body["reason"]) for body in (
            json.loads(row[0]) for row in db.execute("SELECT body FROM retirements")))


def ledger_rows(ledger, sql):
    with sqlite3.connect(ledger._path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql)]


def connection(handle, state, revision, *, catalog="absent", model="absent", provider="claude"):
    return {"provider": provider, "state": state, "handle": handle, "binding_revision": revision,
            "catalog": catalog, "model_choice": model}


def unknown_store(spy):
    """A store request that may have left the control plane but never reached the
    gateway: the command stays `unknown` at every later query."""
    def lost_before_admission(_metadata, _secret):
        raise GatewayServiceError("gateway channel failed")  # sent=True: ambiguous

    spy.store_hook = lost_before_admission


# ------------------------------------------------------------------ binding CAS


def test_create_binds_by_cas_and_a_second_create_is_refused_with_zero_effect(bench):
    client, gateway, spy = bench["client"], bench["gateway"], bench["spy"]
    handle = clean(create(client, FIRST)).json()["handle"]
    assert status(client)["connections"] == [connection(handle, "bound", 1)]
    spy.calls.clear()
    # replacing the bound key is a rotation; a second create never reaches the gateway
    refused = clean(create(client, SECOND))
    assert_error(refused, status=409, code="connection_bound")
    assert spy.calls == []
    assert gateway.counts() == (1, 1, 1, 0)
    # a different provider has its own connection
    other = create(client, SECOND, provider="codex").json()["handle"]
    assert status(client)["connections"] == [connection(handle, "bound", 1),
                                             connection(other, "bound", 1, provider="codex")]


def test_rotate_moves_the_binding_and_delete_cas_revokes_before_retiring(bench):
    client, gateway, spy, lose = bench["client"], bench["gateway"], bench["spy"], bench["lose"]
    handle = create(client, FIRST).json()["handle"]
    assert create(client, SECOND, rotate_from=handle).status_code == 201
    head = bench["ledger"].connection("claude")
    assert head["revision"] == 2 and head["record"]["record_version"] == 2
    # the delete's retirement reply is lost: the binding is already revoked
    act = intent()
    lose(1)
    assert_error(delete(client, handle, act), status=503, code="command_pending")
    view = status(client)
    assert view["connections"] == [connection(handle, "revoked_pending_erasure", 3)]
    assert view["pending_acts"] == [{"intent_id": act, "kind": "delete", "handle": handle,
                                     "provider": "claude", "state": "command_pending",
                                     "fence_available_at": None, "uncertain_record": None}]
    # a rotation of the revoked handle is refused; a new create may bind again
    spy.calls.clear()
    assert_error(create(client, THIRD, rotate_from=handle), status=409, code="conflict")
    assert spy.calls == []
    assert delete(client, handle, act).status_code == 200
    assert retirements(gateway) == [(1, "superseded"), (2, "owner_delete")]
    fresh = create(client, THIRD).json()["handle"]
    assert status(client)["connections"] == [connection(fresh, "bound", 4)]


def test_concurrent_creates_race_one_binds_the_loser_is_an_unbound_orphan(bench):
    client, gateway, spy = bench["client"], bench["gateway"], bench["spy"]
    winner = {}
    loser_act = intent()

    def interleave(metadata, secret):
        # while the first create is in flight, a second create for the same provider
        # (allocated before the first bound) wins the binding CAS
        spy.store_hook = None
        winner["response"] = create(client, SECOND)
        return spy.client.store_at(metadata=metadata, secret=secret)

    # both acts allocate against the unbound connection (revision 0)
    spy.store_hook = interleave
    lost = clean(create(client, FIRST, act=loser_act))
    assert_error(lost, status=409, code="connection_conflict")
    assert winner["response"].status_code == 201
    won = winner["response"].json()["handle"]
    loser = bench["ledger"].act(loser_act)["handle"]
    # the loser's stored record was retired as an unbound orphan and never bound
    view = status(client)
    assert view["connections"] == [connection(won, "bound", 1)]
    by_handle = {entry["handle"]: entry["state"] for entry in view["credentials"]}
    assert by_handle == {won: "stored_unbound", loser: "cleanup_pending"}
    assert retirements(gateway) == [(1, "unbound_orphan")]
    assert gateway.counts() == (2, 2, 2, 1)
    assert gateway.plaintext_of(vault_meta(gateway, record_of(won), 1)) == SECOND.encode()
    # replaying the losing act re-sends nothing and retires nothing twice
    spy.calls.clear()
    assert_error(create(client, THIRD, act=loser_act), status=409, code="connection_conflict")
    assert spy.calls == []
    assert gateway.counts() == (2, 2, 2, 1)


def test_a_rotation_that_loses_its_cas_leaves_the_predecessor_bound_and_unretired(bench):
    client, gateway, spy, ledger = bench["client"], bench["gateway"], bench["spy"], bench["ledger"]
    handle = create(client, FIRST).json()["handle"]
    predecessor = ledger.connection("claude")["record"]

    def concurrent_binding_change(metadata, secret):
        receipt = spy.client.store_at(metadata=metadata, secret=secret)
        # a concurrent binding writer advances the connection's binding revision
        with sqlite3.connect(ledger._path) as db:
            db.execute("UPDATE connections SET revision=revision+1")
        return receipt

    spy.store_hook = concurrent_binding_change
    act = intent()
    assert_error(clean(create(client, SECOND, act=act, rotate_from=handle)),
                 status=409, code="connection_conflict")
    head = ledger.connection("claude")
    assert head["record"] == predecessor and head["state"] == "bound"
    # the successor is the orphan; the predecessor was never superseded
    assert retirements(gateway) == [(2, "unbound_orphan")]
    assert status(client)["credentials"][0]["state"] == "stored_unbound"
    spy.store_hook = None
    # a new rotation allocates past the orphaned version and binds
    assert create(client, THIRD, rotate_from=handle).status_code == 201
    assert ledger.connection("claude")["record"]["record_version"] == 3
    assert retirements(gateway) == [(1, "superseded"), (2, "unbound_orphan")]


def test_a_crash_between_receipt_and_binding_is_completed_by_the_same_act(bench, monkeypatch):
    client, gateway, spy, ledger = bench["client"], bench["gateway"], bench["spy"], bench["ledger"]
    act = intent()
    original = CredentialCommandLedger.bind

    def crash(self, intent_id):
        raise sqlite3.OperationalError("process died before the binding transaction")

    monkeypatch.setattr(CredentialCommandLedger, "bind", crash)
    assert create(client, FIRST, act=act).status_code >= 500
    assert ledger.connection("claude") is None  # receipt persisted, binding not applied
    assert status(client)["pending_acts"][0]["state"] == "command_pending"
    monkeypatch.setattr(CredentialCommandLedger, "bind", original)
    spy.calls.clear()
    retried = clean(create(client, THIRD, act=act))
    assert retried.status_code == 201, retried.text
    assert spy.calls == []  # the receipt was already persisted; the binding is local
    assert ledger.connection("claude")["revision"] == 1
    assert gateway.counts() == (1, 1, 1, 0)


# ------------------------------------------------------------------ catalog/model authority


def test_rotate_invalidates_catalog_and_model_and_only_an_explicit_refresh_creates_one(bench):
    client, ledger = bench["client"], bench["ledger"]
    handle = create(client, FIRST).json()["handle"]
    assert ledger.catalog("claude") is None  # a create never produces a catalog
    ledger.record_catalog_refresh("claude", refresh_command=str(uuid4()),
                                  expected_binding_revision=1, models=MODELS)
    ledger.choose_model("claude", expected_binding_revision=1, model=MODELS[0])
    assert status(client)["connections"] == [connection(handle, "bound", 1, catalog="current",
                                                        model="current")]
    assert create(client, SECOND, rotate_from=handle).status_code == 201
    # the rotation voided the predecessor's catalog and model choice atomically
    assert status(client)["connections"] == [connection(handle, "bound", 2)]
    assert ledger.catalog("claude") is None and ledger.model_choice("claude") is None
    assert [row["state"] for row in ledger_rows(ledger, "SELECT state FROM catalogs")] == ["invalidated"]
    assert [row["state"] for row in ledger_rows(ledger, "SELECT state FROM model_choices")] == ["invalidated"]
    # a refresh answered for the old binding cannot land; a model cannot be chosen yet
    with pytest.raises(CredentialCommandError):
        ledger.record_catalog_refresh("claude", refresh_command=str(uuid4()),
                                      expected_binding_revision=1, models=MODELS)
    with pytest.raises(CredentialCommandError):
        ledger.choose_model("claude", expected_binding_revision=2, model=MODELS[0])
    # only the explicit refresh for the current binding establishes the new catalog
    refresh = str(uuid4())
    ledger.record_catalog_refresh("claude", refresh_command=refresh, expected_binding_revision=2,
                                  models=MODELS[1:])
    ledger.record_catalog_refresh("claude", refresh_command=refresh, expected_binding_revision=2,
                                  models=MODELS[1:])  # idempotent replay
    assert ledger.catalog("claude") == {"binding_revision": 2, "models": MODELS[1:]}
    with pytest.raises(CredentialCommandError):
        ledger.choose_model("claude", expected_binding_revision=2, model=MODELS[0])  # unlisted
    ledger.choose_model("claude", expected_binding_revision=2, model=MODELS[1])
    # a delete revokes the binding and voids its authority too
    assert delete(client, handle, intent()).status_code == 200
    assert ledger.catalog("claude") is None and ledger.model_choice("claude") is None
    assert status(client)["connections"] == [connection(handle, "revoked_pending_erasure", 3)]


def test_no_credential_mutation_checks_refreshes_or_runs_a_model(bench, monkeypatch):
    client, spy, ledger = bench["client"], bench["spy"], bench["ledger"]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a credential mutation made a provider/catalog/model effect")

    for owner, name in ((CredentialCommandLedger, "record_catalog_refresh"),
                        (CredentialCommandLedger, "choose_model"),
                        (http.client.HTTPConnection, "connect"),
                        (http.client.HTTPSConnection, "connect"),
                        (socket, "create_connection"), (socket, "getaddrinfo")):
        monkeypatch.setattr(owner, name, forbidden)
    handle = create(client, FIRST).json()["handle"]
    assert create(client, SECOND, rotate_from=handle).status_code == 201
    unknown_store(spy)
    act = intent()
    assert_error(create(client, THIRD, act=act, rotate_from=handle), status=503, code="command_pending")
    spy.store_hook = None
    bench["clock"].now += ledger.fence_after_seconds
    assert fence(client, act).status_code == 200
    assert delete(client, handle, intent()).status_code == 200
    # only custody operations ever crossed the channel
    assert set(spy.calls) <= {"store_at", "query_record", "retire"}
    assert ledger_rows(ledger, "SELECT * FROM catalogs") == []
    assert ledger_rows(ledger, "SELECT * FROM model_choices") == []


# ------------------------------------------------------------------ unknown-command fence


def test_an_unknown_rotation_is_fenced_by_the_owner_and_a_late_commit_is_retired(bench):
    client, gateway, spy, ledger, clock = (bench[name] for name in
                                           ("client", "gateway", "spy", "ledger", "clock"))
    handle = create(client, FIRST).json()["handle"]
    unknown_store(spy)
    act = intent()
    assert_error(create(client, SECOND, act=act, rotate_from=handle), status=503, code="command_pending")
    spy.store_hook = None
    (metadata,) = [json.loads(row["store_metadata"]) for row in ledger_rows(
        ledger, "SELECT store_metadata FROM acts WHERE kind='rotate'")]
    # the act blocks the handle, and the owner can see when a fence becomes available
    assert_error(delete(client, handle, intent()), status=409, code="conflict")
    (pending,) = status(client)["pending_acts"]
    assert pending["intent_id"] == act and pending["state"] == "command_pending"
    assert pending["fence_available_at"] is not None
    # a retry of the same act only queries: still unknown, still pending
    spy.calls.clear()
    assert_error(create(client, THIRD, act=act, rotate_from=handle), status=503, code="command_pending")
    assert spy.calls == ["query_record"]
    # too early: refused before any gateway call
    spy.calls.clear()
    early = fence(client, act)
    assert_error(early, status=409, code="fence_not_due")
    assert early.json()["retryability"] == "retryable"
    assert spy.calls == []
    clock.now += ledger.fence_after_seconds
    fenced = fence(client, act)
    assert fenced.status_code == 200, fenced.text
    assert fenced.json() == {"intent_id": act, "state": "fenced", "uncertain_record": "unknown",
                             "provider_revocation": "not_performed"}
    assert spy.calls == ["query_record"]  # one fresh query; no secret was re-sent
    assert fence(client, act).json() == fenced.json()  # idempotent
    # the fenced act is terminal: its secret is never sent again, even re-entered
    spy.calls.clear()
    assert_error(create(client, THIRD, act=act, rotate_from=handle), status=409, code="fenced")
    assert spy.calls == ["query_record"]  # only the open fence's reconciliation query
    assert gateway.counts() == (1, 1, 1, 0)
    assert ledger.connection("claude")["record"]["record_version"] == 1  # binding unchanged
    # the delayed store now reaches the gateway and commits there
    late = spy.client.store_at(metadata=metadata, secret=LATE.encode())
    assert late["state"] == "stored_unbound" and gateway.counts() == (2, 2, 2, 0)
    # the next owner act reconciles the fence: the late record is an unbound orphan
    assert create(client, THIRD, rotate_from=handle).status_code == 201
    assert retirements(gateway) == [(1, "superseded"), (2, "unbound_orphan")]
    head = ledger.connection("claude")
    assert head["record"]["record_version"] == 3 and head["revision"] == 2  # v2 was never bound
    assert gateway.plaintext_of(vault_meta(gateway, record_of(handle), 3)) == THIRD.encode()
    view = status(client)
    assert view["credentials"] == [{"handle": handle, "provider": "claude", "state": "stored_unbound",
                                    "provider_revocation": "not_performed"}]
    assert [entry["uncertain_record"] for entry in view["pending_acts"]] == ["cleanup_pending"]


def test_a_fence_whose_query_finds_the_command_committed_retires_it_unbound(bench):
    client, gateway, spy, ledger, clock, lose = (bench[name] for name in
                                                 ("client", "gateway", "spy", "ledger", "clock", "lose"))
    handle = create(client, FIRST).json()["handle"]
    act = intent()
    lose(2)  # the store commits, and both its reply and the recovery query's reply are lost
    assert_error(create(client, SECOND, act=act, rotate_from=handle), status=503, code="command_pending")
    clock.now += ledger.fence_after_seconds
    spy.calls.clear()
    fenced = fence(client, act)
    assert fenced.status_code == 200, fenced.text
    assert fenced.json()["uncertain_record"] == "cleanup_pending"
    assert spy.calls == ["query_record", "retire"]
    assert retirements(gateway) == [(2, "unbound_orphan")]
    # the owner abandoned that act: the predecessor stays bound and unretired
    assert ledger.connection("claude")["record"]["record_version"] == 1
    assert status(client)["credentials"][0]["state"] == "stored_unbound"


def test_a_fenced_create_leaves_the_connection_free_for_a_new_create(bench):
    client, spy, ledger, clock = (bench[name] for name in ("client", "spy", "ledger", "clock"))
    unknown_store(spy)
    act = intent()
    assert_error(create(client, FIRST, act=act), status=503, code="command_pending")
    spy.store_hook = None
    (entry,) = status(client)["credentials"]
    assert entry["state"] == "pending"
    clock.now += ledger.fence_after_seconds
    assert fence(client, act).status_code == 200
    view = status(client)
    assert view["credentials"] == [] and view["connections"] == []
    assert view["pending_acts"][0]["state"] == "fenced"
    fresh = create(client, SECOND)
    assert fresh.status_code == 201
    assert status(client)["connections"] == [connection(fresh.json()["handle"], "bound", 1)]


def test_fence_refusals(bench, monkeypatch):
    client, spy, ledger, clock = (bench[name] for name in ("client", "spy", "ledger", "clock"))
    assert_error(fence(client, intent()), status=404, code="not_found")
    settled = intent()
    handle = create(client, FIRST, act=settled).json()["handle"]
    assert_error(fence(client, settled), status=409, code="conflict")  # nothing uncertain
    removal = intent()
    unknown_store(spy)
    act = intent()
    assert_error(create(client, SECOND, act=act, rotate_from=handle), status=503, code="command_pending")
    spy.store_hook = None
    clock.now += ledger.fence_after_seconds
    # the gateway journaled the command (pending): its own recovery settles it; no fence
    real_query = spy.query_record
    monkeypatch.setattr(spy, "query_record", lambda *, metadata: (
        spy.calls.append("query_record"), {"command_id": metadata["command_id"], "state": "pending"})[1])
    assert_error(fence(client, act), status=503, code="command_pending")
    # the gateway cannot be reached: no fence without a fresh `unknown` answer
    def unreachable(*, metadata):
        raise GatewayServiceError("gateway channel failed", sent=False)
    monkeypatch.setattr(spy, "query_record", unreachable)
    assert_error(fence(client, act), status=503, code="dependency_unavailable")
    assert ledger.act(act)["store_state"] == "sent"
    monkeypatch.setattr(spy, "query_record", real_query)
    assert fence(client, act).status_code == 200
    # a delete act has no secret: its recovery is a same-command replay, not a fence
    assert delete(client, handle, removal).status_code == 200
    assert_error(fence(client, removal), status=409, code="conflict")
    # framing and CSRF
    bad = client.post("/api/v1/credentials/fences", content=b'{"intent_id": "x"}', headers={
        **FETCH, "X-CSRF-Token": client.csrf_token, "Content-Type": "application/json"})
    assert_error(bad, status=400, code="invalid_input")
    denied = client.post("/api/v1/credentials/fences", content=json.dumps({"intent_id": act}),
                         headers={**FETCH, "Content-Type": "application/json"})
    assert_error(denied, status=403, code="access_denied")


def test_the_status_read_with_binding_state_still_makes_zero_gateway_effect(bench, monkeypatch):
    client, gateway, spy = bench["client"], bench["gateway"], bench["spy"]
    handle = create(client, FIRST).json()["handle"]
    bench["ledger"].record_catalog_refresh("claude", refresh_command=str(uuid4()),
                                           expected_binding_revision=1, models=MODELS)
    tree = {path: path.read_bytes() for path in gateway.tmp_path.rglob("*")
            if path.is_file() and path.name != "journal.sqlite-journal"}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a status read reached the gateway")

    for name in ("store_at", "query_record", "retire", "snapshot", "_call"):
        monkeypatch.setattr(type(spy.client), name, forbidden)
    for _ in range(3):
        assert status(client)["connections"] == [connection(handle, "bound", 1, catalog="current")]
    after = {path: path.read_bytes() for path in gateway.tmp_path.rglob("*")
             if path.is_file() and path.name != "journal.sqlite-journal"}
    assert after == tree


def test_an_older_ledger_gains_the_binding_columns_on_open(tmp_path):
    path = tmp_path / "credential-commands.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE acts (
                intent_id TEXT PRIMARY KEY, kind TEXT NOT NULL, fingerprint TEXT NOT NULL,
                handle TEXT NOT NULL, provider TEXT NOT NULL,
                store_metadata TEXT, store_state TEXT,
                retire_command TEXT, retire_record TEXT, retire_reason TEXT, retire_state TEXT,
                outcome TEXT, created_at TEXT NOT NULL);
            CREATE TABLE records (
                record_id TEXT NOT NULL, record_version INTEGER NOT NULL,
                provider TEXT NOT NULL, command_id TEXT NOT NULL UNIQUE,
                ciphertext_sha256 TEXT NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY(record_id, record_version));
        """)
    ledger = CredentialCommandLedger(path)
    assert {"sent_at", "binding_expected", "bind_state"} <= {
        row["name"] for row in ledger_rows(ledger, "PRAGMA table_info(acts)")}
    assert ledger.snapshot() == {"credentials": [], "connections": [], "pending_acts": []}
