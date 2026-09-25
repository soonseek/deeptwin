"""T090 explicit catalog refresh, model choice and the gateway's claim-time binding check.

Full stack as in test_credential_binding: the real development app (session, CSRF), the
control-plane ledger, the frame-only `CredentialGatewayClient` over real authenticated
broker frames on socket pairs into `CredentialGatewayService` and an encrypted
`CredentialVault`. The refresh additionally crosses the gateway's provider-send path: a
`ProviderSendClient` speaking `provider-send-prepare-v1` frames to a `ProviderSendService`
over the SAME vault, whose `CredentialedProviderTransport` is bound to a loopback mock of
the provider's models endpoint (this module's `Upstream`; no outbound network). The mock
records every request it receives, so "no provider byte" is observed at the provider.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.api.credential_catalog import GatewayCatalogLister
from app.api.credential_commands import (
    CredentialActs,
    CredentialCommandLedger,
    record_of,
)
from app.api.credential_routes import attach_credential_gateway
from app.tests.local_http import LocalTestClient
from app.tests.support.provider_semantic_harness import connection_values
from app.tests.test_credential_gateway_persistence import Gateway
from app.tests.test_credential_routes import make_app
from app.tests.test_credential_routes_v2 import Spy, create, delete, intent, vault_meta
from app.tests.test_provider_send_gateway import binding, prepared_catalog
from app.tests.test_server_api_v1 import FETCH, ORIGIN, assert_error
from app.workers.credential_channel import GatewayServiceError
from app.workers.provider_gateway import CredentialedProviderTransport
from app.workers.provider_send_messages import ProviderSendError
from app.workers.provider_send_service import ProviderSendService

FIRST = "sk-synthetic-refresh-first-0001"
SECOND = "sk-synthetic-refresh-second-0002"
THIRD = "sk-synthetic-refresh-third-0003"
SECRETS = (FIRST, SECOND, THIRD)
PAGE_ONE = ["synthetic-model-c", "synthetic-model-b"]
PAGE_TWO = ["synthetic-model-a"]
ALL = PAGE_ONE + PAGE_TWO


def _model(identifier, day):
    return {"type": "model", "id": identifier, "display_name": identifier,
            "created_at": f"2026-01-{day:02d}T00:00:00Z"}


class Upstream:
    """A loopback mock of the provider's paginated models endpoint."""

    def __init__(self):
        self.requests = []   # (path, query, api key) of every request received
        self.status = 200
        self.on_request = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                split = urlsplit(self.path)
                owner.requests.append((split.path, parse_qs(split.query),
                                       self.headers.get("x-api-key")))
                if owner.on_request is not None:
                    hook, owner.on_request = owner.on_request, None
                    hook()
                if owner.status != 200:
                    body = b'{"type":"error"}'
                else:
                    after = parse_qs(split.query).get("after_id", [None])[0]
                    if after is None:
                        page = {"data": [_model(PAGE_ONE[0], 3), _model(PAGE_ONE[1], 2)],
                                "first_id": PAGE_ONE[0], "last_id": PAGE_ONE[1], "has_more": True}
                    else:
                        page = {"data": [_model(PAGE_TWO[0], 1)], "first_id": PAGE_TWO[0],
                                "last_id": PAGE_TWO[0], "has_more": False}
                    body = json.dumps(page).encode()
                self.send_response(owner.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def bench(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    (tmp_path / "gateway").mkdir()
    gateway = Gateway(tmp_path / "gateway")
    upstream = Upstream()
    spy = Spy(gateway.client())
    ledger = CredentialCommandLedger(tmp_path / "credential-commands.sqlite3")
    lister_calls = []
    inner = GatewayCatalogLister(lambda: gateway.send_client(upstream.port))

    def lister(**kwargs):
        lister_calls.append(kwargs["binding_revision"])
        return inner(**kwargs)

    application = make_app(tmp_path / "app")
    attach_credential_gateway(application, spy, ledger, catalog_lister=lister)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        yield SimpleNamespace(client=client, gateway=gateway, spy=spy, ledger=ledger,
                              upstream=upstream, lister_calls=lister_calls,
                              acts=CredentialActs(spy, ledger))
    upstream.close()
    gateway.close()
    for secret in SECRETS:
        assert secret not in caplog.text
    for path in tmp_path.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for secret in SECRETS:
                assert secret.encode() not in data, path


def post(client, path, body):
    return client.post(path, content=json.dumps(body), headers={
        **FETCH, "X-CSRF-Token": client.csrf_token, "Content-Type": "application/json"})


def refresh(client, act=None, provider="claude"):
    return post(client, f"/api/v1/credentials/connections/{provider}/catalog-refresh",
                {"intent_id": act or intent()})


def choose(client, revision, model, provider="claude"):
    return post(client, f"/api/v1/credentials/connections/{provider}/model-choice",
                {"binding_revision": revision, "model": model})


def connections(client):
    response = client.get("/api/v1/credentials", headers=FETCH)
    assert response.status_code == 200, response.text
    for secret in SECRETS:
        assert secret not in response.text
    return response.json()["connections"]


def gateway_heads(gateway):
    return [(head["provider"], head["revision"], head["state"], head["record"]["record_version"])
            for head in gateway.vault.heads()]


# ------------------------------------------------------------------ refresh and choice


def test_refresh_lists_the_current_revision_through_the_gateway_and_a_choice_is_validated(bench):
    client, upstream = bench.client, bench.upstream
    handle = create(client, FIRST).json()["handle"]
    assert gateway_heads(bench.gateway) == [("claude", 1, "bound", 1)]
    # the create itself made no provider request
    assert upstream.requests == []
    act = intent()
    response = refresh(client, act)
    assert response.status_code == 200, response.text
    assert response.json() == {"provider": "claude", "binding_revision": 1, "catalog": "current",
                               "models": ALL, "chosen_model": None}
    # two pages, the second after the first page's last id; the key was injected by the
    # gateway at send time (the control plane's frames never carried it)
    assert [(path, query.get("after_id")) for path, query, _key in upstream.requests] == [
        ("/v1/models", None), ("/v1/models", [PAGE_ONE[-1]])]
    assert {key for _path, _query, key in upstream.requests} == {FIRST}
    assert bench.spy.calls == ["store_at"]  # no custody call carried a secret for the refresh
    (entry,) = connections(client)
    assert entry == {"provider": "claude", "state": "bound", "handle": handle,
                     "binding_revision": 1, "catalog": "current", "model_choice": "absent",
                     "gateway_head": "applied", "models": ALL, "chosen_model": None}
    # a replay of the same refresh answers from the ledger: no provider request
    assert refresh(client, act).json()["models"] == ALL
    assert len(upstream.requests) == 2 and bench.lister_calls == [1]

    assert_error(choose(client, 1, "synthetic-model-z"), status=409, code="model_not_listed")
    assert_error(choose(client, 2, ALL[0]), status=409, code="catalog_stale")
    chosen = choose(client, 1, ALL[1])
    assert chosen.status_code == 200, chosen.text
    assert chosen.json() == {"provider": "claude", "binding_revision": 1, "model": ALL[1]}
    assert connections(client)[0]["chosen_model"] == ALL[1]
    assert len(upstream.requests) == 2  # a choice makes no provider call

    # a rotation voids both; only a new explicit refresh restores a catalog
    assert create(client, SECOND, rotate_from=handle).status_code == 201
    assert gateway_heads(bench.gateway) == [("claude", 2, "bound", 2)]
    (entry,) = connections(client)
    assert (entry["binding_revision"], entry["catalog"], entry["models"], entry["chosen_model"]) == (
        2, "absent", [], None)
    assert len(upstream.requests) == 2
    assert_error(choose(client, 2, ALL[1]), status=409, code="catalog_stale")
    assert refresh(client).json()["binding_revision"] == 2
    assert {key for _path, _query, key in upstream.requests[2:]} == {SECOND}


def test_a_rotation_between_request_and_result_makes_the_result_stale(bench):
    client, upstream, ledger = bench.client, bench.upstream, bench.ledger
    handle = create(client, FIRST).json()["handle"]

    def rotate_while_the_provider_answers():
        # the gateway already claimed and wrote this page under revision 1; the owner's
        # rotation lands before the result reaches the ledger
        bench.acts.store(SimpleNamespace(intent_id=intent(), provider="claude",
                                         secret=SECOND.encode(), rotate_from=handle))

    upstream.on_request = rotate_while_the_provider_answers
    act = intent()
    assert_error(refresh(client, act), status=409, code="catalog_stale")
    assert ledger.connection("claude")["revision"] == 2
    assert ledger.catalog("claude") is None
    # the stale page was the only request; the next page was never asked for
    assert len(upstream.requests) == 1 and upstream.requests[0][2] == FIRST
    # the refused result stays refused on replay, with no provider request
    assert_error(refresh(client, act), status=409, code="catalog_stale")
    assert len(upstream.requests) == 1
    assert connections(client)[0]["catalog"] == "absent"


def test_refresh_refusals_have_no_provider_effect(bench, tmp_path):
    client, upstream = bench.client, bench.upstream
    assert_error(refresh(client), status=409, code="connection_unbound")
    create(client, FIRST, provider="codex")
    assert_error(refresh(client, provider="codex"), status=409, code="catalog_unsupported")
    assert_error(refresh(client, provider="other"), status=400, code="invalid_input")
    missing_csrf = client.post("/api/v1/credentials/connections/claude/catalog-refresh",
                               content=json.dumps({"intent_id": intent()}),
                               headers={**FETCH, "Content-Type": "application/json"})
    assert_error(missing_csrf, status=403, code="access_denied")
    for body in ({}, {"intent_id": "x"}, {"intent_id": intent(), "extra": 1}):
        assert_error(post(client, "/api/v1/credentials/connections/claude/catalog-refresh", body),
                     status=400, code="invalid_input")
    for body in ({"binding_revision": True, "model": "m"}, {"binding_revision": 1},
                 {"binding_revision": 1, "model": "bad model"}):
        assert_error(post(client, "/api/v1/credentials/connections/claude/model-choice", body),
                     status=400, code="invalid_input")
    assert_error(choose(client, 1, ALL[0]), status=409, code="catalog_stale")
    assert upstream.requests == [] and bench.lister_calls == []
    # the provider refuses the key: no catalog, the refusal is named
    create(client, FIRST)
    upstream.status = 401
    assert_error(refresh(client), status=424, code="provider_rejected")
    upstream.status = 503
    assert_error(refresh(client), status=503, code="provider_unavailable")
    assert bench.ledger.catalog("claude") is None
    # without a lister the refresh is honestly unavailable
    application = make_app(tmp_path / "bare")
    attach_credential_gateway(application, bench.spy, bench.ledger)
    with LocalTestClient(application, base_url=ORIGIN) as bare:
        assert_error(refresh(bare), status=503, code="dependency_unavailable")


def test_the_status_read_stays_zero_effect_with_a_catalog(bench, monkeypatch):
    client = bench.client
    create(client, FIRST)
    assert refresh(client).status_code == 200
    before = len(bench.upstream.requests)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a status read made a gateway/provider effect")

    for name in ("store_at", "query_record", "retire", "bind_head", "_call"):
        monkeypatch.setattr(type(bench.spy.client), name, forbidden)
    monkeypatch.setattr(GatewayCatalogLister, "__call__", forbidden)
    assert connections(client)[0]["models"] == ALL
    assert len(bench.upstream.requests) == before


# ------------------------------------------------------------------ claim-time binding check


def _catalog_send(bench, handle, version):
    """Prepare and commit one gateway models exchange naming one exact record version."""
    meta = vault_meta(bench.gateway, record_of(handle), version)
    receipt = bench.gateway.vault.query_record(metadata=meta)
    record = {name: receipt[name] for name in ("record_id", "record_version", "ciphertext_sha256")}
    handle_ref, pin, _, _ = connection_values(meta, record)
    service = ProviderSendService(CredentialedProviderTransport(bench.gateway.vault,
                                                                binding(bench.upstream.port)))
    ready = service.prepare(prepared_catalog(meta, record, handle_ref, pin))
    lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
    return service, lease


def test_a_rotation_racing_a_send_is_refused_at_claim_time_before_any_provider_byte(bench):
    client, upstream = bench.client, bench.upstream
    handle = create(client, FIRST).json()["handle"]
    # the send is committed under revision 1, then the rotation lands before its claim.
    # The predecessor's retirement is held back, so only the binding head refuses it.
    service, lease = _catalog_send(bench, handle, 1)
    retire = bench.spy.retire
    bench.spy.retire = lambda **_kwargs: (_ for _ in ()).throw(
        GatewayServiceError("gateway channel failed", sent=False))
    act = intent()
    assert_error(create(client, SECOND, act=act, rotate_from=handle), status=503,
                 code="command_pending")
    assert gateway_heads(bench.gateway) == [("claude", 2, "bound", 2)]
    first = vault_meta(bench.gateway, record_of(handle), 1)
    assert bench.gateway.vault.query_record(metadata=first)["state"] == "stored_unbound"
    with pytest.raises(ProviderSendError) as refused:
        service.exchange(lease)
    assert (refused.value.failure_class, refused.value.phase) == ("permission_denied", "not_sent")
    assert upstream.requests == []
    bench.spy.retire = retire
    assert create(client, SECOND, act=act, rotate_from=handle).status_code == 201
    # a send naming the new head's record is delivered
    service, lease = _catalog_send(bench, handle, 2)
    assert service.exchange(lease).status == 200
    assert [key for _path, _query, key in upstream.requests] == [SECOND]


def test_a_send_claimed_first_completes_and_the_rotation_is_serialized_after_it(bench):
    client, upstream = bench.client, bench.upstream
    handle = create(client, FIRST).json()["handle"]
    service, lease = _catalog_send(bench, handle, 1)
    rotated = {}

    def rotate_now():
        # the gateway already wrote this request under revision 1; the rotation's head
        # publication waits for the vault exclusion the claim held while writing
        rotated["receipt"] = bench.acts.store(SimpleNamespace(
            intent_id=intent(), provider="claude", secret=SECOND.encode(), rotate_from=handle))

    upstream.on_request = rotate_now
    assert service.exchange(lease).status == 200
    assert rotated["receipt"]["state"] == "stored_unbound"
    assert [key for _path, _query, key in upstream.requests] == [FIRST]
    # from here on the predecessor is refused
    service, lease = _catalog_send(bench, handle, 1)
    with pytest.raises(ProviderSendError):
        service.exchange(lease)
    assert len(upstream.requests) == 1


def test_revoked_orphaned_and_unacknowledged_heads_refuse_sends(bench):
    client, upstream, spy = bench.client, bench.upstream, bench.spy
    handle = create(client, FIRST).json()["handle"]
    # the rotation's head publication does not reach the gateway: the act is incomplete,
    # the head is listed pending, the gateway still enforces revision 1
    spy.head_hook = lambda _kwargs: (_ for _ in ()).throw(
        GatewayServiceError("gateway channel failed", sent=False))
    act = intent()
    assert_error(create(client, SECOND, act=act, rotate_from=handle), status=503,
                 code="command_pending")
    (entry,) = connections(client)
    assert (entry["binding_revision"], entry["gateway_head"]) == (2, "pending")
    assert gateway_heads(bench.gateway) == [("claude", 1, "bound", 1)]
    service, lease = _catalog_send(bench, handle, 2)
    with pytest.raises(ProviderSendError):
        service.exchange(lease)  # the successor is not usable before its head is enforced
    assert upstream.requests == []
    # a refresh never names a record whose head the gateway has not acknowledged
    assert_error(refresh(client), status=503, code="command_pending")
    assert upstream.requests == []
    # the same act replays the publication, then retires the predecessor
    spy.head_hook = None
    assert create(client, SECOND, act=act, rotate_from=handle).status_code == 201
    assert gateway_heads(bench.gateway) == [("claude", 2, "bound", 2)]
    assert connections(client)[0]["gateway_head"] == "applied"
    # delete: the revoked head reaches the gateway before the retirement
    assert delete(client, handle, intent()).status_code == 200
    assert gateway_heads(bench.gateway) == [("claude", 3, "revoked_pending_erasure", 2)]
    for version in (1, 2):
        service, lease = _catalog_send(bench, handle, version)
        with pytest.raises(ProviderSendError):
            service.exchange(lease)
    assert upstream.requests == []
    assert_error(refresh(client), status=409, code="connection_unbound")


def test_a_stored_record_that_no_head_binds_is_never_delivered(bench):
    """An orphan, a fenced command's late commit or any record stored outside a binding
    is custody without binding authority: the send path refuses it."""
    from app.tests.test_credential_custody import metadata

    create(bench.client, FIRST)
    loose = metadata()
    receipt = bench.gateway.client().store_at(metadata=loose, secret=THIRD.encode())
    record = {name: receipt[name] for name in ("record_id", "record_version", "ciphertext_sha256")}
    handle_ref, pin, _, _ = connection_values(loose, record)
    service = ProviderSendService(CredentialedProviderTransport(bench.gateway.vault,
                                                                binding(bench.upstream.port)))
    ready = service.prepare(prepared_catalog(loose, record, handle_ref, pin))
    lease = service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
    with pytest.raises(ProviderSendError) as refused:
        service.exchange(lease)
    assert (refused.value.failure_class, refused.value.phase) == ("permission_denied", "not_sent")
    assert bench.upstream.requests == []


def test_the_gateway_refuses_a_stale_or_conflicting_head(bench):
    client, gateway = bench.client, bench.gateway
    handle = create(client, FIRST).json()["handle"]
    assert create(client, SECOND, rotate_from=handle).status_code == 201
    head = gateway.vault.heads()[0]
    old = dict(head, revision=1, record=dict(head["record"], record_version=1))
    raw = gateway.client()
    with pytest.raises(GatewayServiceError) as stale:
        raw.bind_head(provider="claude", revision=1, state="bound", record=old["record"])
    assert stale.value.code == "conflict"
    with pytest.raises(GatewayServiceError):
        raw.bind_head(provider="claude", revision=2, state="revoked_pending_erasure",
                      record=head["record"])
    # the identical head is an idempotent replay
    assert raw.bind_head(**{name: head[name] for name in ("provider", "revision", "state",
                                                         "record")}) == head
    assert gateway_heads(gateway) == [("claude", 2, "bound", 2)]


def test_a_first_layout_journal_gains_the_heads_table(tmp_path):
    from app.workers.credential_journal import HEADS_SCHEMA  # noqa: F401
    from app.workers.credential_vault import CredentialVault

    (tmp_path / "gateway").mkdir()
    gateway = Gateway(tmp_path / "gateway")
    gateway.vault.close()
    path = gateway.args["records_directory"] / "journal.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE heads")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        assert "heads" not in {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    gateway.vault = CredentialVault(**gateway.args)
    assert gateway.vault.heads() == []
    gateway.close()
