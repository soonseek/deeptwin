"""T090 budget binding of every gateway send (catalog pages and message sends).

Full stack as in test_credential_catalog_refresh (the `bench` fixture): the development
app, the control-plane ledger, real authenticated frames on socket pairs into the
gateway's credential and provider-send services over one encrypted vault, and a loopback
mock of the provider's models endpoint that records every request it receives. The
catalog lister reserves each page in a real `BudgetBook` before the send and settles it
after; the gateway refuses a lease without a reservation and journals each consumed one.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

from app.api import credential_catalog
from app.api.credential_catalog import GatewayCatalogLister
from app.api.credential_commands import CatalogListError
from app.runtime.budgets import BudgetBook
from app.runtime.gateway_send_budget import (
    CATALOG_MAX_PAGES,
    GatewayCatalogBudget,
    GatewaySendBudgetError,
    catalog_refresh_policy,
)
from app.storage import Store
from app.tests.support.provider_semantic_harness import (
    connection_values,
    controlled_upstream,
    encrypted_credential,
)
from app.tests.support.transport_manifest import (
    loopback_binding,
    synthetic_qualification,
)
from app.tests.test_credential_catalog_refresh import (  # noqa: F401 - the shared fixture
    ALL,
    FIRST,
    bench,
    connections,
    refresh,
)
from app.tests.test_credential_routes_v2 import create, intent
from app.tests.test_provider_send_gateway import prepared, prepared_catalog
from app.tests.test_server_api_v1 import FETCH, assert_error
from app.workers.provider_gateway import CredentialedProviderTransport
from app.workers.provider_send_messages import ProviderSendError, prepare_message
from app.workers.provider_send_service import ProviderSendService


class Crash(BaseException):
    """A simulated process death: nothing below it runs, nothing is settled."""


def book(tmp_path, name="budget"):
    return BudgetBook(Store(tmp_path / name), clock=lambda: int(time.time()))


def sessions(budget_book):
    with budget_book._connection() as db:
        return [dict(row) for row in db.execute(
            "SELECT id, policy_hash, api_microunits, output_bytes, loop_rounds, active "
            "FROM runtime_budget_sessions ORDER BY id")]


def reservations(budget_book):
    with budget_book._connection() as db:
        return [dict(row) for row in db.execute(
            "SELECT request_id, state, usage_finality, output_bytes, api_microunits, "
            "actual_output_bytes, actual_api_microunits, actual_loop_rounds "
            "FROM runtime_budget_reservations ORDER BY created_at, rowid")]


def head_arguments(bench_value, refresh_id):
    head = bench_value.ledger.bound_head("claude")
    return {"provider": "claude", "metadata": head["metadata"], "record": head["record"],
            "binding_revision": head["revision"], "refresh_id": refresh_id}


# ------------------------------------------------------------------ the policy itself


def test_the_catalog_policy_is_zero_cost_and_bounded(tmp_path):
    budget = GatewayCatalogBudget(book(tmp_path))
    policy = budget.policy
    assert policy == catalog_refresh_policy(1_048_576)
    assert (policy.provider_mode, policy.currency, policy.max_api_microunits) == ("api", "USD", 1)
    assert policy.max_loop_rounds == CATALOG_MAX_PAGES and policy.max_concurrency == 1
    assert policy.max_output_bytes == CATALOG_MAX_PAGES * 1_048_576
    session = budget.open("scope")
    assert budget.open("scope") == session  # resumable, same policy
    pages = []
    for ordinal in range(CATALOG_MAX_PAGES):
        page = budget.reserve_page(session, ordinal)
        # recorded dispatched (the may-have-sent barrier) before any send exists
        assert budget.book.reservation_state(page.request_id) == "dispatched"
        budget.settle(page, observed=type("O", (), {"phase": "terminal_observed",
                                                   "body": b"x" * 10})())
        pages.append(page)
    rows = reservations(budget.book)
    assert [row["state"] for row in rows] == ["finalized"] * CATALOG_MAX_PAGES
    assert {(row["api_microunits"], row["actual_api_microunits"], row["actual_output_bytes"])
            for row in rows} == {(0, 0, 10)}
    # beyond the policy: the eleventh page is refused and nothing is written
    with pytest.raises(GatewaySendBudgetError) as refused:
        budget.reserve_page(session, CATALOG_MAX_PAGES)
    assert refused.value.code == "budget_refused"
    assert len(reservations(budget.book)) == CATALOG_MAX_PAGES
    assert budget.book.status(session)["remaining"]["api_microunits"] == 1


def test_an_unsettled_page_blocks_the_session_and_is_never_reserved_again(tmp_path):
    budget = GatewayCatalogBudget(book(tmp_path))
    session = budget.open("crashed")
    page = budget.reserve_page(session, 0)  # ... and the process died before the send
    # one page in flight at a time: the next page is refused while it is unsettled
    with pytest.raises(GatewaySendBudgetError) as blocked:
        budget.reserve_page(session, 1)
    assert blocked.value.code == "budget_refused"
    # the same page again: its outcome is unknown, it is settled so and never re-sent
    with pytest.raises(GatewaySendBudgetError) as again:
        budget.reserve_page(session, 0)
    assert again.value.code == "outcome_unknown"
    assert budget.book.reservation_state(page.request_id) == "unknown"
    with pytest.raises(GatewaySendBudgetError):
        budget.reserve_page(session, 0)
    assert budget.book.reservation_state(page.request_id) == "unknown"


# ------------------------------------------------------------------ the catalog refresh


def test_each_page_is_reserved_before_and_settled_after_its_send(bench):
    client, upstream = bench.client, bench.upstream
    create(client, FIRST)
    assert sessions(bench.book) == [] and bench.gateway.vault.consumed_reservations() == []
    act = intent()
    response = refresh(client, act)
    assert response.status_code == 200, response.text
    assert len(upstream.requests) == 2
    (session,) = sessions(bench.book)
    assert session["id"] == GatewayCatalogBudget.session_id("credential-catalog-refresh:" + act)
    assert (session["api_microunits"], session["active"], session["loop_rounds"]) == (0, 0, 2)
    rows = reservations(bench.book)
    assert [(row["state"], row["usage_finality"], row["actual_api_microunits"],
             row["actual_loop_rounds"]) for row in rows] == [("finalized", "known", 0, 1)] * 2
    assert all(0 < row["actual_output_bytes"] <= row["output_bytes"] for row in rows)
    # the gateway consumed exactly these two reservations, one per send
    consumed = bench.gateway.vault.consumed_reservations()
    assert [row["reservation_id"] for row in consumed] == [row["request_id"] for row in rows]
    assert {row["endpoint"] for row in consumed} == {"models"}
    # a replay answers from the ledger: no reservation, no send
    assert refresh(client, act).status_code == 200
    assert len(reservations(bench.book)) == 2 and len(upstream.requests) == 2


def test_a_crash_between_reservation_and_send_never_sends_twice(bench):
    create(bench.client, FIRST)
    budget = GatewayCatalogBudget(bench.book)
    calls = []

    def crashing_factory():
        calls.append(1)
        raise Crash()

    refresh_id = str(uuid4())
    with pytest.raises(Crash):
        GatewayCatalogLister(crashing_factory, budget=budget)(**head_arguments(bench, refresh_id))
    (row,) = reservations(bench.book)
    assert row["state"] == "dispatched" and bench.upstream.requests == []
    # the retried refresh finds its page already reserved: settled unknown, never sent
    working = GatewayCatalogLister(lambda: bench.gateway.send_client(bench.upstream.port),
                                   budget=budget)
    with pytest.raises(CatalogListError) as refused:
        working(**head_arguments(bench, refresh_id))
    assert refused.value.code == "budget_refused"
    assert [row["state"] for row in reservations(bench.book)] == ["unknown"]
    assert bench.upstream.requests == [] and bench.gateway.vault.consumed_reservations() == []
    # a new refresh is a new budget session and lists normally
    assert working(**head_arguments(bench, str(uuid4()))) == ALL
    assert len(bench.upstream.requests) == 2


def test_a_crash_after_the_send_keeps_the_reservation_and_the_page_is_not_resent(bench):
    create(bench.client, FIRST)
    budget = GatewayCatalogBudget(bench.book)

    class DiesAfterTheExchange:
        def __init__(self):
            self._client = bench.gateway.send_client(bench.upstream.port)

        def prepare(self, message):
            return self._client.prepare(message)

        def commit(self, *args):
            return self._client.commit(*args)

        def exchange(self, lease):
            self._client.exchange(lease)
            raise Crash()

        def abandon(self):
            self._client.abandon()

    refresh_id = str(uuid4())
    with pytest.raises(Crash):
        GatewayCatalogLister(DiesAfterTheExchange, budget=budget)(
            **head_arguments(bench, refresh_id))
    assert len(bench.upstream.requests) == 1
    (row,) = reservations(bench.book)
    assert row["state"] == "dispatched"
    working = GatewayCatalogLister(lambda: bench.gateway.send_client(bench.upstream.port),
                                   budget=budget)
    with pytest.raises(CatalogListError) as refused:
        working(**head_arguments(bench, refresh_id))
    assert refused.value.code == "budget_refused"
    # the full reservation is retained as unknown usage; the page was sent exactly once
    assert [row["state"] for row in reservations(bench.book)] == ["unknown"]
    assert len(bench.upstream.requests) == 1


def test_a_lister_without_a_budget_sends_nothing(bench):
    create(bench.client, FIRST)
    unbudgeted = GatewayCatalogLister(lambda: bench.gateway.send_client(bench.upstream.port))
    with pytest.raises(CatalogListError) as refused:
        unbudgeted(**head_arguments(bench, str(uuid4())))
    assert refused.value.code == "budget_refused"
    assert bench.upstream.requests == [] and sessions(bench.book) == []


def test_pages_beyond_the_policy_are_refused_before_any_provider_byte(bench, monkeypatch):
    create(bench.client, FIRST)
    requests = []

    class Endless(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            index = len(requests)
            body = json.dumps({"data": [{"type": "model", "id": f"synthetic-model-{index:03d}",
                                         "display_name": "m", "created_at": "2026-01-01T00:00:00Z"}],
                               "first_id": f"synthetic-model-{index:03d}",
                               "last_id": f"synthetic-model-{index:03d}", "has_more": True}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Endless)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(credential_catalog, "_MAX_PAGES", CATALOG_MAX_PAGES + 2)
        lister = GatewayCatalogLister(lambda: bench.gateway.send_client(server.server_address[1]),
                                      budget=GatewayCatalogBudget(bench.book))
        with pytest.raises(CatalogListError) as refused:
            lister(**head_arguments(bench, str(uuid4())))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    assert refused.value.code == "budget_refused"
    assert len(requests) == CATALOG_MAX_PAGES
    assert [row["state"] for row in reservations(bench.book)] == ["finalized"] * CATALOG_MAX_PAGES
    assert len(bench.gateway.vault.consumed_reservations()) == CATALOG_MAX_PAGES


def test_no_owner_act_or_read_reserves_or_sends(bench):
    client = bench.client
    handle = create(client, FIRST).json()["handle"]
    create(client, "sk-synthetic-refresh-second-0002", rotate_from=handle)
    connections(client)
    response = client.get("/api/v1/credentials", headers=FETCH)
    assert response.status_code == 200
    assert sessions(bench.book) == [] and reservations(bench.book) == []
    assert bench.upstream.requests == [] and bench.gateway.vault.consumed_reservations() == []


def test_a_changed_manifest_refuses_the_refresh_with_zero_provider_requests(bench):
    create(bench.client, FIRST)
    # the gateway's adopted qualification now names another manifest digest
    bench.gateway.vault.bind_transport(qualification=synthetic_qualification(
        revision=2, manifest_sha256="0" * 64))
    assert_error(refresh(bench.client), status=409, code="transport_unqualified")
    assert bench.upstream.requests == []
    (row,) = reservations(bench.book)
    # refused before any provider byte: settled with zero usage
    assert (row["state"], row["actual_output_bytes"], row["actual_loop_rounds"]) == (
        "finalized", 0, 0)
    assert bench.gateway.vault.consumed_reservations() == []
    # a qualification of the shipped manifest (a later revision) restores the path
    bench.gateway.vault.bind_transport(qualification=synthetic_qualification(revision=3))
    assert refresh(bench.client).status_code == 200


# ------------------------------------------------------------------ the gateway's own checks


def test_a_prepare_without_a_reservation_is_refused_for_every_endpoint(tmp_path):
    with encrypted_credential(tmp_path) as (_vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        common = dict(operation_ref={"kind": "validation_report", "id": str(uuid4()),
                                     "version": 1, "sha256": "c" * 64},
                      request_id=str(uuid4()), request_sha256="d" * 64,
                      selected_handle_ref=handle, connection_pin=pin, credential_metadata=meta,
                      credential_record=record, remaining_ms=2_000,
                      deadline_at=prepared(meta, record, handle, pin).deadline_at,
                      reservation_ref=None)
        for endpoint, body in (("messages", b"{}"), ("models", b"")):
            with pytest.raises(ProviderSendError, match="budget reservation"):
                prepare_message(endpoint=endpoint, after_id=None, body=body, **common)


def test_the_gateway_consumes_each_reservation_once_across_restarts(tmp_path):
    from app.tests.support.transport_manifest import qualify_vault
    from app.tests.test_credential_custody import metadata
    from app.tests.test_credential_root import initialized
    from app.workers.credential_vault import CredentialVault

    page = b'{"data":[],"has_more":false,"first_id":null,"last_id":null}'
    args = initialized(tmp_path)
    meta = metadata()
    with controlled_upstream(response=(200, "application/json", page)) as (
            port, captures, _entered, _release):
        with CredentialVault(**args) as vault:
            receipt = vault.store_at(metadata=meta, secret=b"synthetic-budget-key-0001")
            record = {key: receipt[key] for key in ("record_id", "record_version",
                                                    "ciphertext_sha256")}
            vault.bind_head(provider="claude", revision=1, state="bound", record=record)
            qualify_vault(vault)
            handle, pin, _, _ = connection_values(meta, record)
            service = ProviderSendService(CredentialedProviderTransport(vault, loopback_binding(port)))
            first = prepared_catalog(meta, record, handle, pin)
            ready = service.prepare(first)
            observed = service.exchange(service.commit(ready["exchange_id"],
                                                       ready["prepare_sha256"], str(uuid4())))
            assert observed.status == 200 and len(captures) == 1

            def reusing():
                return prepare_message(
                    operation_ref=first.operation_ref, request_id=str(uuid4()),
                    request_sha256=first.request_sha256, selected_handle_ref=handle,
                    connection_pin=pin, credential_metadata=meta, credential_record=record,
                    endpoint="models", after_id=None, body=b"", remaining_ms=2_000,
                    deadline_at=first.deadline_at, reservation_ref=first.reservation_ref)

            # another dialogue naming the same reservation: refused before any provider byte
            ready = service.prepare(reusing())
            with pytest.raises(ProviderSendError) as refused:
                service.exchange(service.commit(ready["exchange_id"], ready["prepare_sha256"],
                                                str(uuid4())))
            assert (refused.value.failure_class, refused.value.phase) == (
                "resource_exhausted", "not_sent")
            assert len(captures) == 1
            assert [row["reservation_id"] for row in vault.consumed_reservations()] == [
                first.reservation_ref["id"]]
        # the journal row is durable: after a gateway restart the reservation stays spent
        with CredentialVault(**args) as reopened:
            service = ProviderSendService(CredentialedProviderTransport(
                reopened, loopback_binding(port)))
            ready = service.prepare(reusing())
            with pytest.raises(ProviderSendError) as refused:
                service.exchange(service.commit(ready["exchange_id"], ready["prepare_sha256"],
                                                str(uuid4())))
            assert refused.value.phase == "not_sent" and len(captures) == 1
            # a fresh reservation is served
            ready = service.prepare(prepared_catalog(meta, record, handle, pin))
            assert service.exchange(service.commit(ready["exchange_id"], ready["prepare_sha256"],
                                                   str(uuid4()))).status == 200
            assert len(captures) == 2 and len(reopened.consumed_reservations()) == 2


def test_a_message_send_consumes_its_ledger_reservation_once(tmp_path):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n")) as (
            port, captures, _entered, _release), encrypted_credential(tmp_path) as (vault, meta, record):
        handle, pin, _, _ = connection_values(meta, record)
        service = ProviderSendService(CredentialedProviderTransport(vault, loopback_binding(port)))
        message = prepared(meta, record, handle, pin)
        ready = service.prepare(message)
        service.exchange(service.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
        assert len(captures) == 1
        # the same prepared message (the same reservation) in a second dialogue
        ready = service.prepare(message)
        with pytest.raises(ProviderSendError) as refused:
            service.exchange(service.commit(ready["exchange_id"], ready["prepare_sha256"],
                                            str(uuid4())))
        assert (refused.value.failure_class, refused.value.phase) == ("resource_exhausted", "not_sent")
        assert len(captures) == 1
        assert [(row["reservation_id"], row["endpoint"]) for row in vault.consumed_reservations()] == [
            (message.reservation_ref["id"], "messages")]
