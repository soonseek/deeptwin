"""T090 full-stack credential routes: HTTP -> command ledger -> v2 frames -> vault.

Every request crosses the real development app (session, CSRF, ingress wire
checks), the control-plane command ledger, the frame-only
`CredentialGatewayClient` and real authenticated broker frames on socket pairs
into `CredentialGatewayService` and an encrypted `CredentialVault` (the harness
of test_credential_gateway_persistence). The vault journal is the oracle. A lost
response is injected where it can happen after a commit: the service's reply
write closes the connection instead of answering.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import sqlite3
from uuid import uuid4

import pytest

from app.api.credential_commands import CredentialCommandLedger, record_of
from app.api.credential_routes import attach_credential_gateway
from app.tests.local_http import LocalTestClient
from app.tests.test_credential_custody import _crash_store
from app.tests.test_credential_gateway_persistence import Gateway
from app.tests.test_credential_routes import make_app
from app.tests.test_server_api_v1 import FETCH, ORIGIN, assert_error
from app.workers import credential_gateway_service
from app.workers.credential_channel import GatewayServiceError

FIRST = "sk-synthetic-route-first-0001"
SECOND = "sk-synthetic-route-second-0002"
OTHER = "sk-synthetic-route-other-0003"
SECRETS = (FIRST, SECOND, OTHER)


class Spy:
    """The real frame client, with every gateway call counted by operation."""

    def __init__(self, client):
        self.client = client
        self.calls = []
        self.store_hook = None

    def store_at(self, *, metadata, secret):
        self.calls.append("store_at")
        if self.store_hook is not None:
            return self.store_hook(metadata, secret)
        return self.client.store_at(metadata=metadata, secret=secret)

    def query_record(self, *, metadata):
        self.calls.append("query_record")
        return self.client.query_record(metadata=metadata)

    def retire(self, **kwargs):
        self.calls.append("retire")
        return self.client.retire(**kwargs)


@pytest.fixture
def stack(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    (tmp_path / "gateway").mkdir()
    gateway = Gateway(tmp_path / "gateway")
    spy = Spy(gateway.client())
    ledger = CredentialCommandLedger(tmp_path / "credential-commands.sqlite3")
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
        yield client, gateway, spy, (lambda count=1: armed.extend([True] * count))
    gateway.close()
    # no secret in any log record, in the control-plane ledger or anywhere on disk in cleartext
    for secret in SECRETS:
        assert secret not in caplog.text
    for path in tmp_path.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for secret in SECRETS:
                assert secret.encode() not in data, path


def intent():
    return str(uuid4())


def create(client, secret, *, act=None, provider="claude", rotate_from=None):
    body = {"intent_id": act or intent(), "provider": provider, "secret": secret}
    if rotate_from is not None:
        body["rotate_from"] = rotate_from
    return client.post("/api/v1/credentials", content=json.dumps(body), headers={
        **FETCH, "X-CSRF-Token": client.csrf_token, "Content-Type": "application/json"})


def delete(client, handle, act):
    return client.request("DELETE", f"/api/v1/credentials/{handle}",
                          content=json.dumps({"intent_id": act}),
                          headers={**FETCH, "X-CSRF-Token": client.csrf_token,
                                   "Content-Type": "application/json"})


def status(client):
    response = client.get("/api/v1/credentials", headers=FETCH)
    assert response.status_code == 200, response.text
    return response.json()["credentials"]


def clean(response):
    for secret in SECRETS:
        assert secret not in response.text
    return response


def vault_rows(gateway):
    path = gateway.args["records_directory"] / "journal.sqlite"
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            "SELECT command_id, record_id, version, state FROM commands ORDER BY version")]


def vault_meta(gateway, record_id, version):
    path = gateway.args["records_directory"] / "journal.sqlite"
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        (body,) = db.execute("SELECT metadata FROM commands WHERE record_id=? AND version=?",
                             (record_id, version)).fetchone()
    return json.loads(body)


def test_create_rotate_delete_end_to_end_over_the_real_channel(stack):
    client, gateway, spy, _lose = stack
    created = clean(create(client, FIRST))
    assert created.status_code == 201, created.text
    handle = created.json()["handle"]
    assert created.json() == {"handle": handle, "provider": "claude", "state": "stored_unbound"}
    assert spy.calls == ["store_at"]
    assert status(client) == [{"handle": handle, "provider": "claude", "state": "stored_unbound",
                               "provider_revocation": "not_performed"}]

    rotated = clean(create(client, SECOND, rotate_from=handle))
    assert rotated.status_code == 201, rotated.text
    assert rotated.json() == {"handle": handle, "provider": "claude", "state": "stored_unbound"}
    # rotate = store the successor (version 2, predecessor reference), then supersede
    assert spy.calls == ["store_at", "store_at", "retire"]
    assert gateway.counts() == (2, 2, 2, 1)
    record_id = record_of(handle)
    first_meta, second_meta = vault_meta(gateway, record_id, 1), vault_meta(gateway, record_id, 2)
    assert second_meta["predecessor"]["record_version"] == 1
    assert spy.client.query_record(metadata=first_meta)["state"] == "cleanup_pending"
    assert spy.client.query_record(metadata=second_meta)["state"] == "stored_unbound"
    assert gateway.plaintext_of(second_meta) == SECOND.encode()
    spy.calls.clear()

    removed = clean(delete(client, handle, intent()))
    assert removed.status_code == 200, removed.text
    # local cleanup only; the provider-side key is explicitly not revoked by DeepTwin
    assert removed.json() == {"handle": handle, "state": "cleanup_pending",
                              "provider_revocation": "not_performed"}
    assert spy.calls == ["retire"]
    assert gateway.counts() == (2, 2, 2, 2)
    assert spy.client.query_record(metadata=second_meta)["state"] == "cleanup_pending"
    assert status(client) == [{"handle": handle, "provider": "claude", "state": "cleanup_pending",
                               "provider_revocation": "not_performed"}]
    # a retired handle cannot be rotated or deleted again by a new act
    assert_error(create(client, OTHER, rotate_from=handle), status=409, code="conflict")
    assert_error(delete(client, handle, intent()), status=409, code="conflict")
    assert gateway.counts() == (2, 2, 2, 2)


def test_same_act_replay_with_a_different_secret_returns_the_original_receipt(stack):
    client, gateway, spy, _lose = stack
    act = intent()
    first = create(client, FIRST, act=act)
    assert first.status_code == 201
    replay = clean(create(client, OTHER, act=act))
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert spy.calls == ["store_at"]  # the replayed secret never left the control plane
    assert gateway.counts() == (1, 1, 1, 0)
    (row,) = vault_rows(gateway)
    assert gateway.plaintext_of(vault_meta(gateway, row["record_id"], 1)) == FIRST.encode()
    # the same key for a different act is a conflict, not a replay
    assert_error(create(client, OTHER, act=act, provider="codex"), status=409, code="conflict")
    assert_error(create(client, OTHER, act=act, rotate_from=first.json()["handle"]),
                 status=409, code="conflict")
    assert gateway.counts() == (1, 1, 1, 0)


@pytest.mark.parametrize("kind", ["create", "rotate"])
def test_a_lost_store_response_is_recovered_by_query_never_by_resending(stack, kind):
    client, gateway, spy, lose = stack
    rotate_from = None
    if kind == "rotate":
        rotate_from = create(client, FIRST).json()["handle"]
        spy.calls.clear()
    before = gateway.counts()
    act = intent()
    # the store commits but its reply is lost, and so is the recovery query's reply
    lose(2)
    pending = clean(create(client, SECOND, act=act, rotate_from=rotate_from))
    assert_error(pending, status=503, code="command_pending")
    assert pending.json()["retryability"] == "retryable"
    assert spy.calls == ["store_at", "query_record"]
    assert gateway.counts()[:3] == (before[0] + 1, before[1] + 1, before[2] + 1)
    # the owner retries the same act (even with other bytes): query, adopt, never resend
    spy.calls.clear()
    retried = clean(create(client, OTHER, act=act, rotate_from=rotate_from))
    assert retried.status_code == 201, retried.text
    assert spy.calls == (["query_record"] if kind == "create" else ["query_record", "retire"])
    assert gateway.counts()[:3] == (before[0] + 1, before[1] + 1, before[2] + 1)
    row = vault_rows(gateway)[-1]
    assert gateway.plaintext_of(vault_meta(gateway, row["record_id"], row["version"])) == SECOND.encode()
    # a single lost reply is recovered inside the same request by the query
    spy.calls.clear()
    lose(1)
    # (claude is bound now; one bound credential per provider connection)
    immediate = create(client, FIRST, provider="codex")
    assert immediate.status_code == 201, immediate.text
    assert spy.calls == ["store_at", "query_record"]


def test_a_lost_retire_response_is_recovered_by_same_command_replay(stack):
    client, gateway, spy, lose = stack
    handle = create(client, FIRST).json()["handle"]
    act = intent()
    lose(1)
    lost = delete(client, handle, act)
    assert_error(lost, status=503, code="command_pending")
    assert gateway.counts() == (1, 1, 1, 1)  # committed despite the lost reply
    spy.calls.clear()
    replay = delete(client, handle, act)
    assert replay.status_code == 200, replay.text
    assert replay.json()["state"] == "cleanup_pending"
    assert spy.calls == ["retire"]
    assert gateway.counts() == (1, 1, 1, 1)  # the same retirement command, not a second one
    # the unfinished-act guard released once the act settled
    assert_error(delete(client, handle, intent()), status=409, code="conflict")


def test_a_journaled_command_whose_ingress_was_lost_is_secret_input_lost(stack):
    client, gateway, spy, _lose = stack

    def crash_after_journaling(metadata, _secret):
        # the gateway journals the pending command and dies before encryption; the
        # reply never arrives and startup recovery marks the ingress lost
        gateway.vault.close()
        process = multiprocessing.get_context("spawn").Process(
            target=_crash_store, args=(gateway.args, metadata, "after_reservation"))
        process.start()
        process.join(20)
        if process.is_alive():
            process.terminate()
            process.join(3)
            pytest.fail("owned crash helper exceeded its deadline")
        assert process.exitcode == 71
        process.close()
        from app.workers.credential_vault import CredentialVault

        gateway.vault = CredentialVault(**gateway.args)
        raise GatewayServiceError("gateway channel failed")

    spy.store_hook = crash_after_journaling
    act = intent()
    lost = clean(create(client, FIRST, act=act))
    assert_error(lost, status=409, code="secret_input_lost")
    assert lost.json()["retryability"] == "not_retryable"
    assert spy.calls == ["store_at", "query_record"]
    spy.store_hook = None
    # the same act with re-entered bytes stays lost and never ingests them
    spy.calls.clear()
    assert_error(create(client, OTHER, act=act), status=409, code="secret_input_lost")
    assert spy.calls == []
    assert gateway.counts() == (1, 1, 0, 0)
    (entry,) = status(client)
    assert entry["state"] == "secret_input_lost"
    # only a new act (fresh intent, explicit re-entry) may try again
    fresh = create(client, OTHER)
    assert fresh.status_code == 201, fresh.text
    assert gateway.counts() == (2, 2, 1, 0)


def test_route_refusals_make_zero_gateway_effect(stack):
    client, gateway, spy, _lose = stack
    # unsupported provider, unknown rotation/delete targets
    assert_error(create(client, FIRST, provider="acme"), status=400, code="invalid_input")
    assert_error(create(client, FIRST, rotate_from="a" * 32), status=404, code="not_found")
    assert_error(delete(client, "a" * 32, intent()), status=404, code="not_found")
    # oversize framing is refused before the ledger or gateway
    oversized = client.post("/api/v1/credentials", content=b"x" * (96 * 1024 + 1), headers={
        **FETCH, "X-CSRF-Token": client.csrf_token, "Content-Type": "application/json"})
    assert_error(oversized, status=413, code="invalid_input")
    # missing CSRF on a write
    denied = client.post("/api/v1/credentials", content=json.dumps(
        {"intent_id": intent(), "provider": "claude", "secret": FIRST}),
        headers={**FETCH, "Content-Type": "application/json"})
    assert_error(denied, status=403, code="access_denied")
    assert spy.calls == []
    assert gateway.counts() == (0, 0, 0, 0)
    assert status(client) == []


def test_a_pre_send_failure_releases_the_command_for_the_same_act(stack):
    client, gateway, spy, _lose = stack

    def refused(_metadata, _secret):
        raise GatewayServiceError("gateway channel failed", sent=False)

    spy.store_hook = refused
    act = intent()
    assert_error(create(client, FIRST, act=act), status=503, code="dependency_unavailable")
    assert gateway.counts() == (0, 0, 0, 0)
    spy.store_hook = None
    stored = create(client, FIRST, act=act)
    assert stored.status_code == 201, stored.text
    assert gateway.counts() == (1, 1, 1, 0)


def test_an_unfinished_rotation_blocks_other_acts_on_the_handle(stack):
    client, gateway, _spy, lose = stack
    handle = create(client, FIRST).json()["handle"]
    act = intent()
    lose(2)
    assert_error(create(client, SECOND, act=act, rotate_from=handle), status=503, code="command_pending")
    # neither a delete nor another rotation may target the record while that outcome is open
    blocked = delete(client, handle, intent())
    assert_error(blocked, status=409, code="conflict")
    assert blocked.json()["retryability"] == "retryable"
    assert_error(create(client, OTHER, rotate_from=handle), status=409, code="conflict")
    assert create(client, OTHER, act=act, rotate_from=handle).status_code == 201
    assert delete(client, handle, intent()).status_code == 200
    assert gateway.counts() == (2, 2, 2, 2)


def test_status_reads_make_zero_gateway_or_vault_effect(stack, monkeypatch):
    client, gateway, spy, _lose = stack
    handle = create(client, FIRST).json()["handle"]
    tree = {path: path.read_bytes() for path in gateway.tmp_path.rglob("*")
            if path.is_file() and path.name != "journal.sqlite-journal"}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a status read reached the gateway")

    for name in ("store_at", "query_record", "retire", "snapshot", "_call"):
        monkeypatch.setattr(type(spy.client), name, forbidden)
    for _ in range(3):
        assert status(client) == [{"handle": handle, "provider": "claude", "state": "stored_unbound",
                                   "provider_revocation": "not_performed"}]
    after = {path: path.read_bytes() for path in gateway.tmp_path.rglob("*")
             if path.is_file() and path.name != "journal.sqlite-journal"}
    assert after == tree
