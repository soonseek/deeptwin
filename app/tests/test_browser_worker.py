"""T043: controlled egress fetch and the sandboxed Chromium worker over typed IPC.

Three layers:

- the channel grammar, the fetch service's grant enforcement and the control-side client
  verification, over the real frame codec and handshake of the fixed specs (the in-thread
  harness relaxes only SO_PEERCRED), with an injected resolver/transport for the broker;
- the dispatch path: a compiled graph whose `writer` node is bound to a browser tool runs
  through the real `NodeAttemptDispatcher` and `BrowserAttemptTransport`, the result
  sealed control-side and admitted by the ledger;
- the root-only real-process qualification: the production fetch and browser entrypoints
  as separate processes under their own identities (20104; 20105 inside a fresh network
  namespace), over root-initialized pair roots with SO_PEERCRED, real headless Chromium
  with its sandbox active, and a local HTTPS fixture site — no outbound network at all.

The import-boundary tests pin that the control plane never imports the browser driver.
"""

from __future__ import annotations

import ast
import glob
import http.server
import io
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.runtime.egress import EgressBrokerError
from app.runtime.scheduler import SchedulerError
from app.tests.support.browser_worker_harness import pair_factory
from app.workers import browser_channel, fetch_channel
from app.workers.browser_channel import (
    BrowserChannelError,
    BrowserClient,
    BrowserControlConfiguration,
    BrowserRequest,
    BrowserWorkerConfiguration,
)
from app.workers.fetch_channel import (
    BrowserFetchClient,
    BrowserGrant,
    FetchChannelError,
    FetchControlClient,
    FetchWorkerConfiguration,
    GrantProjection,
    ProjectionEntry,
    source_admits,
)

REPOSITORY = Path(__file__).resolve().parents[2]
PUBLIC = {"granted.test": "93.184.216.34", "other.test": "93.184.216.35", "rebind.test": "93.184.216.36",
          "big.test": "93.184.216.37"}


# the exact pure navigations ("no source data") the in-thread cases open
NAVIGATIONS = ("https://granted.test/", "https://granted.test/home", "https://granted.test/away",
               "https://granted.test/big", "https://granted.test/mid", "https://granted.test/slow",
               "https://granted.test/docs/page", "https://granted.test/docs/leave", "https://granted.test/docs/final",
               "https://private.test/")


def pure_navigation(sources, urls=NAVIGATIONS):
    return GrantProjection(entries=tuple(ProjectionEntry(url=url) for url in urls if source_admits(sources, url)))


def grant(**changes):
    values = {"sources": ("https://granted.test/",), "recipients": ("granted.test",),
              "max_response_bytes": 256 * 1024, "max_total_bytes": 1024 * 1024, "max_requests": 16,
              "max_redirects": 3, "ttl_ms": 30_000}
    values.update(changes)
    if "projection" not in values:
        values["projection"] = pure_navigation(values["sources"])
    return BrowserGrant(**values)


def register(subject, value, url=None, excluded_hosts=()):
    """Register `value` for one navigation (its first projection entry unless named)."""
    return subject.control.register(value, url or value.projection.entries[0].url, excluded_hosts)


# --- profiles and configurations -----------------------------------------------------

def test_the_profiles_are_the_declared_service_pairs():
    ids = json.loads((REPOSITORY / "deploy" / "security" / "service-ids.json").read_text())
    for name, (root, spec) in {"cp-browser": browser_channel.browser_channel(),
                               "cp-fetch": fetch_channel.control_fetch_channel(),
                               "browser-fetch": fetch_channel.browser_fetch_channel()}.items():
        pair = ids["pairs"][name]
        requester, responder = ids["services"][pair["requester"]], ids["services"][pair["responder"]]
        assert str(root.pair_root) == pair["root"]
        assert (spec.requester_uid, spec.requester_gid) == (requester["uid"], requester["gid"])
        assert (spec.responder_uid, spec.responder_gid) == (responder["uid"], responder["gid"])
        assert spec.pair_gid == pair["pair_gid"] == root.pair_gid
        assert (spec.requester_service, spec.responder_service) == (pair["requester"], pair["responder"])
        assert spec.socket_name == pair["socket"]
    compose = json.loads((REPOSITORY / "deploy" / "compose.yaml").read_text())["services"]
    assert compose["browser"]["network_mode"] == "none" and compose["browser"]["user"] == "20105:20105"
    assert set(compose["browser"]["group_add"]) == {"21104", "21110"}
    assert compose["fetch"]["networks"] == ["fetch-egress"] and set(compose["fetch"]["group_add"]) == {"21102", "21110"}
    assert any("/run/deeptwin/browser-profile" in item and "mode=0700" in item for item in compose["browser"]["tmpfs"])


def test_configurations_are_exact_objects():
    control = {"schema": browser_channel.CONTROL_ATTACHMENT_SCHEMA, "browser_pair_root": "/run/deeptwin/ipc/cp-browser",
               "browser_requester_boot_id": "control-boot", "fetch_pair_root": "/run/deeptwin/ipc/cp-fetch",
               "fetch_requester_boot_id": "control-boot"}
    assert BrowserControlConfiguration.from_mapping(control).fetch_pair_root == "/run/deeptwin/ipc/cp-fetch"
    for broken in ({**control, "x": 1}, {**control, "schema": "other"}, {**control, "browser_pair_root": "relative"},
                   {**control, "fetch_requester_boot_id": "-bad"}):
        with pytest.raises(ValueError):
            BrowserControlConfiguration.from_mapping(broken)
    worker = {"schema": browser_channel.WORKER_ATTACHMENT_SCHEMA, "pair_root": "/run/deeptwin/ipc/cp-browser",
              "requester_boot_id": "control-boot", "fetch_pair_root": "/run/deeptwin/ipc/browser-fetch",
              "fetch_requester_boot_id": "browser-boot", "chromium_path": "/opt/chromium/headless_shell",
              "profile_root": "/run/deeptwin/browser-profile"}
    assert BrowserWorkerConfiguration.from_mapping(worker).profile_root == "/run/deeptwin/browser-profile"
    with pytest.raises(ValueError):
        BrowserWorkerConfiguration.from_mapping({**worker, "chromium_path": "headless_shell"})
    fetch = {"schema": fetch_channel.ATTACHMENT_SCHEMA, "control_pair_root": "/run/deeptwin/ipc/cp-fetch",
             "control_requester_boot_id": "control-boot", "browser_pair_root": "/run/deeptwin/ipc/browser-fetch",
             "browser_requester_boot_id": "browser-boot"}
    assert FetchWorkerConfiguration.from_mapping(fetch).browser_requester_boot_id == "browser-boot"
    with pytest.raises(ValueError):
        FetchWorkerConfiguration.from_mapping({**fetch, "schema": "x"})
    with pytest.raises(ValueError):  # only the verified pair roots are endpoints
        BrowserClient.for_worker(BrowserControlConfiguration.from_mapping(
            {**control, "browser_pair_root": "/tmp/cp-browser"}))


def test_grants_are_bounded_and_sources_lie_on_recipients():
    assert grant().digest == grant().digest
    for broken in ({"sources": ("https://other.test/",)}, {"sources": ("http://granted.test/",)},
                   {"sources": ("https://granted.test/a",)}, {"sources": ("https://granted.test/?q=1",)},
                   {"recipients": ("Granted.test",)}, {"max_response_bytes": 0},
                   {"max_total_bytes": 1}, {"max_requests": 0}, {"max_redirects": 11}, {"ttl_ms": 10}):
        with pytest.raises(ValueError):
            grant(**broken)
    sources = ("https://granted.test/docs/",)
    assert source_admits(sources, "https://granted.test/docs/page?x=1")
    assert not source_admits(sources, "https://granted.test/private")
    assert not source_admits(sources, "https://granted.test.evil.test/docs/")
    assert not source_admits(sources, "http://granted.test/docs/")
    assert not source_admits(sources, "https://granted.test/docs/../private")
    assert not source_admits(sources, "https://granted.test/docs/%2e%2e/private")
    with pytest.raises(ValueError):
        BrowserRequest(op="read", url="https://user:pw@granted.test/")
    with pytest.raises(ValueError):
        BrowserRequest(op="click", url="https://granted.test/")


def test_the_broker_reports_closed_refusal_codes_per_hop():
    from urllib.parse import urlsplit

    from app.runtime.egress import EGRESS_CODES, broker_fetch, freeze_egress_policy

    policy = freeze_egress_policy(granted_hosts=("granted.test",), product_origins=("product.test",),
                                  max_redirects=1, max_response_bytes=16)
    replies = {"/": (200, {"content-type": "text/plain"}, b"ok"),
               "/hop": (302, {"location": "https://other.test/"}, b""),
               "/loop": (302, {"location": "/loop"}, b""), "/big": (200, {}, b"x" * 17)}

    def transport(_method, url, _addresses, _headers):
        return replies[urlsplit(url).path]

    def public(_host):
        return ("93.184.216.34",)

    def code(url, resolver=public):
        with pytest.raises(EgressBrokerError) as refused:
            broker_fetch(policy, "GET", url, resolver=resolver, transport=transport)
        assert refused.value.code in EGRESS_CODES
        return refused.value.code

    fetched = broker_fetch(policy, "GET", "https://granted.test/", resolver=public, transport=transport)
    assert (fetched.body, fetched.content_type) == (b"ok", "text/plain")
    assert code("https://other.test/") == "grant_denied"
    assert code("https://product.test/") == "grant_denied"
    assert code("http://granted.test/") == "grant_denied"
    assert code("https://granted.test/hop") == "redirect_denied"
    assert code("https://granted.test/loop") == "redirect_denied"
    assert code("https://granted.test/big") == "too_large"
    assert code("https://granted.test/", resolver=lambda _host: ("10.0.0.5",)) == "dns_denied"
    assert code("https://granted.test/", resolver=lambda _host: ()) == "dns_denied"
    assert code("https://granted.test/\r\nHost: x") == "invalid_request"


# --- the fetch service's enforcement (in-thread, injected broker network) ------------

PAGES = {
    "/": (200, {"content-type": "text/html; charset=utf-8", "set-cookie": "sid=1"}, b"<title>Home</title>hi"),
    "/away": (302, {"location": "https://other.test/landing"}, b""),
    "/outside": (302, {"location": "https://granted.test/elsewhere/x"}, b""),
    "/home": (302, {"location": "/docs/final"}, b""),
    "/docs/final": (200, {"content-type": "text/html"}, b"<title>Final</title>final"),
    "/docs/page": (200, {"content-type": "text/plain\x01"}, b"page"),
    "/big": (200, {"content-type": "text/html"}, b"x" * (300 * 1024)),
    "/mid": (200, {"content-type": "text/html"}, b"m" * (200 * 1024)),
    "/search": (200, {"content-type": "text/html"}, b"<title>Search</title>results"),
    "/leak": (302, {"location": "https://other.test/collect?v=deeptwin"}, b""),
}


class FakeNetwork:
    def __init__(self, answers=None):
        self.answers = {"granted.test": ["93.184.216.34"], "other.test": ["93.184.216.35"],
                        "private.test": ["10.0.0.5"], "mixed.test": ["93.184.216.36", "127.0.0.1"],
                        **(answers or {})}
        self.seen = []

    def resolver(self, host):
        return tuple(self.answers.get(host, ()))

    def transport_factory(self, limit):
        def transport(method, url, addresses, headers):
            from urllib.parse import urlsplit

            parts = urlsplit(url)
            self.seen.append((method, url, addresses, dict(headers)))
            if parts.path == "/slow":
                raise EgressBrokerError("no pinned address could be reached", "timeout")
            status, response_headers, body = PAGES.get(parts.path, (404, {"content-type": "text/plain"}, b"none"))
            if len(body) > limit:
                raise EgressBrokerError("response body exceeds the byte limit", "too_large")
            return status, response_headers, body

        return transport


@pytest.fixture
def fetch_service():
    from app.workers.fetch_service import FetchService

    network = FakeNetwork()
    clock = [100.0]
    _root, control_spec = fetch_channel.control_fetch_channel()
    _root, browser_spec = fetch_channel.browser_fetch_channel()
    service = FetchService(control_spec, browser_spec, resolver=network.resolver,
                           transport_factory=network.transport_factory, clock=lambda: clock[0])
    outcomes, threads = [], []
    control = FetchControlClient(pair_factory(control_spec, service.serve_control, outcomes=outcomes, threads=threads))
    fetcher = BrowserFetchClient(pair_factory(browser_spec, service.serve_browser, outcomes=outcomes, threads=threads))
    yield SimpleNamespace(service=service, network=network, clock=clock, control=control, fetcher=fetcher,
                          outcomes=outcomes)
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()


def _fetch(subject, identifier, url, kind="navigation"):
    from app.workers import broker

    return subject.fetcher.fetch(identifier, url, kind=kind, deadline=broker.Deadline.after_ms(5_000))


def _code(subject, identifier, url, kind="navigation"):
    with pytest.raises(FetchChannelError) as refused:
        _fetch(subject, identifier, url, kind)
    return refused.value.code


def test_a_granted_navigation_is_fetched_with_only_its_status_type_and_body(fetch_service):
    identifier = register(fetch_service, grant())
    response = _fetch(fetch_service, identifier, "https://granted.test/")
    assert (response.status, response.final_url, response.redirects) == (200, "https://granted.test/", 0)
    assert response.content_type == "text/html; charset=utf-8" and response.body == b"<title>Home</title>hi"
    assert response.sha256 == sha256(response.body).hexdigest()
    method, _url, addresses, headers = fetch_service.network.seen[0]
    # the pinned addresses are the ones the broker admitted; no browser header is forwarded
    assert (method, addresses) == ("GET", ("93.184.216.34",)) and set(headers) == {"Accept"}
    usage = fetch_service.control.revoke(identifier)
    assert (usage.requests, usage.denied, usage.body_bytes) == (1, 0, len(response.body))
    assert _code(fetch_service, identifier, "https://granted.test/") == "grant_denied"  # revoked


def test_hosts_sources_and_routes_outside_the_grant_are_denied(fetch_service):
    identifier = register(fetch_service, grant(sources=("https://granted.test/docs/",),
                                                      recipients=("granted.test", "private.test", "mixed.test")))
    assert _code(fetch_service, identifier, "https://granted.test/") == "grant_denied"  # outside the sources
    assert _fetch(fetch_service, identifier, "https://granted.test/", kind="subresource").status == 200
    assert _code(fetch_service, identifier, "https://other.test/x", "subresource") == "grant_denied"
    assert _code(fetch_service, identifier, "http://granted.test/docs/", "subresource") == "grant_denied"
    assert _code(fetch_service, identifier, "https://granted.test:8443/docs/", "subresource") == "grant_denied"
    # a private answer, and one private address in a public answer (a rebinding), are DNS denials
    assert _code(fetch_service, identifier, "https://private.test/", "subresource") == "dns_denied"
    assert _code(fetch_service, identifier, "https://mixed.test/", "subresource") == "dns_denied"
    assert [seen[1] for seen in fetch_service.network.seen] == ["https://granted.test/"]
    usage = fetch_service.control.revoke(identifier)
    assert (usage.requests, usage.denied) == (7, 6)


def test_redirects_are_revalidated_against_recipients_and_sources(fetch_service):
    identifier = register(fetch_service, grant(sources=("https://granted.test/docs/", "https://granted.test/"),
                                                      recipients=("granted.test",)))
    followed = _fetch(fetch_service, identifier, "https://granted.test/home")
    assert (followed.final_url, followed.redirects, followed.body) == ("https://granted.test/docs/final", 1,
                                                                       b"<title>Final</title>final")
    assert _code(fetch_service, identifier, "https://granted.test/away") == "redirect_denied"
    other = register(fetch_service, grant(sources=("https://granted.test/docs/",)))
    # a dot segment (literal or encoded) never walks out of a source prefix
    for escape in ("https://granted.test/docs/../outside", "https://granted.test/docs/%2e%2e/outside",
                   "https://granted.test/docs/%2E./outside", "https://granted.test/docs%2f..%2foutside"):
        assert _code(fetch_service, other, escape) == "grant_denied"
    assert not any("outside" in seen[1] for seen in fetch_service.network.seen)  # never reached the network


def test_navigation_redirect_leaving_the_sources_is_denied(fetch_service, monkeypatch):
    monkeypatch.setitem(PAGES, "/docs/leave", (302, {"location": "https://granted.test/elsewhere/"}, b""))
    identifier = register(fetch_service, grant(sources=("https://granted.test/docs/",)))
    assert _code(fetch_service, identifier, "https://granted.test/docs/leave") == "redirect_denied"
    # the same hop is a recipient-clean redirect for a subresource
    assert _fetch(fetch_service, identifier, "https://granted.test/docs/leave", "subresource").status == 404


def test_byte_request_and_lifetime_limits_refuse(fetch_service):
    identifier = register(fetch_service, grant(max_response_bytes=256 * 1024, max_total_bytes=300 * 1024,
                                                      max_requests=4))
    assert _code(fetch_service, identifier, "https://granted.test/big") == "too_large"  # one response
    assert len(_fetch(fetch_service, identifier, "https://granted.test/mid").body) == 200 * 1024
    assert _code(fetch_service, identifier, "https://granted.test/mid") == "too_large"  # the total budget
    assert _fetch(fetch_service, identifier, "https://granted.test/").status == 200  # the 4th request
    assert _code(fetch_service, identifier, "https://granted.test/") == "grant_denied"  # the 5th request
    later = register(fetch_service, grant(ttl_ms=5_000))
    fetch_service.clock[0] += 5.0
    assert _code(fetch_service, later, "https://granted.test/") == "grant_denied"  # expired
    slow = register(fetch_service, grant())
    assert _code(fetch_service, slow, "https://granted.test/slow") == "timeout"
    assert fetch_service.control.revoke(identifier).body_bytes == 200 * 1024 + len(PAGES["/"][2])


def test_grant_registration_refuses_the_product_origin_and_unknown_ids(fetch_service):
    with pytest.raises(FetchChannelError) as refused:
        register(fetch_service, grant(), excluded_hosts=("granted.test",))
    assert refused.value.code == "grant_denied"
    with pytest.raises(FetchChannelError) as unknown:
        fetch_service.control.revoke("0" * 64)
    assert unknown.value.code == "grant_denied"
    assert _code(fetch_service, "1" * 64, "https://granted.test/") == "grant_denied"


def test_an_unprintable_content_type_is_replaced(fetch_service):
    identifier = register(fetch_service, grant(sources=("https://granted.test/docs/",)))
    assert _fetch(fetch_service, identifier, "https://granted.test/docs/page").content_type == "application/octet-stream"


# --- the browser service and the control-side client (no Chromium) -------------------

class FakeSession:
    """Stands in for `ChromiumSession`: fetches the main document through the real fetch
    client and reports what it saw, with optional lies."""

    def __init__(self, request, lie=None):
        self.request, self.lie, self.profile = request, lie, "/nonexistent/profile"

    def start(self, deadline):
        pass

    def probe_sandbox(self, deadline):
        return {"renderers": 1, "seccomp_filter": True, "pid_namespace": True}

    def navigate(self, url, fetcher, deadline):
        from app.adapters.browser import BrowserRefusal, Navigation

        observed = Navigation(requested_url=url, requests=1)
        try:
            response = fetcher(url, "navigation")
        except Exception as error:  # noqa: BLE001 - every fetch failure carries a closed code
            raise BrowserRefusal(error.code) from None
        observed.allowed, observed.body_bytes = 1, len(response.body) + (1 if self.lie == "bytes" else 0)
        observed.final_url = "https://other.test/" if self.lie == "final" else response.final_url
        observed.status, observed.content_type = response.status, response.content_type
        observed.document_sha256, observed.document_bytes = response.sha256, len(response.body)
        observed.title = "Home"
        return observed

    def read_text(self, max_bytes, deadline):
        return b"hi", False

    def screenshot(self, max_bytes, deadline):
        import struct
        import zlib

        width, height = self.request.width, self.request.height
        raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        return png, width, height

    def close(self):
        return self.lie != "profile"


@pytest.fixture
def browser_client(fetch_service):
    from app.workers.browser_service import BrowserService

    state = {"lie": None}
    _root, spec = browser_channel.browser_channel()
    service = BrowserService(spec, chromium_path="/nonexistent/chromium", profile_root="/nonexistent",
                             fetch_client=fetch_service.fetcher,
                             session_factory=lambda request: FakeSession(request, state["lie"]))
    outcomes, threads = [], []
    client = BrowserClient(pair_factory(spec, service.serve_connection, outcomes=outcomes, threads=threads),
                           fetch=fetch_service.control)
    yield SimpleNamespace(client=client, state=state, outcomes=outcomes, fetch=fetch_service)
    for thread in threads:
        thread.join(5)


def test_the_client_returns_a_verified_observation_and_revokes_the_grant(browser_client):
    value = browser_client.client.run(BrowserRequest(op="read", url="https://granted.test/"), grant())
    assert (value.final_url, value.status, value.title, value.output) == ("https://granted.test/", 200, "Home", b"hi")
    assert value.document_sha256 == sha256(b"<title>Home</title>hi").hexdigest()
    assert value.output_sha256 == sha256(b"hi").hexdigest() and value.media_type.startswith("text/plain")
    assert browser_client.fetch.service._grants == {}  # revoked after the session
    shot = browser_client.client.run(BrowserRequest(op="screenshot", url="https://granted.test/", width=64,
                                                    height=64), grant())
    assert (shot.width, shot.height, shot.media_type) == (64, 64, "image/png")
    assert browser_client.outcomes == ["ok", "ok"]


def test_a_url_outside_the_grant_never_leaves_control(browser_client):
    with pytest.raises(BrowserChannelError) as refused:
        browser_client.client.run(BrowserRequest(op="navigate", url="https://other.test/"), grant())
    assert (refused.value.code, refused.value.sent) == ("grant_denied", False)
    assert browser_client.outcomes == [] and browser_client.fetch.network.seen == []


@pytest.mark.parametrize("lie, code", [("bytes", "malformed_result"), ("final", "malformed_result"),
                                       ("profile", "render_failed")])
def test_a_result_the_fetch_accounting_or_the_grant_contradicts_is_refused(browser_client, lie, code):
    browser_client.state["lie"] = lie
    with pytest.raises(BrowserChannelError) as refused:
        browser_client.client.run(BrowserRequest(op="navigate", url="https://granted.test/"), grant())
    assert refused.value.code == code
    assert browser_client.fetch.service._grants == {}


def test_worker_side_refusals_are_the_brokers_closed_codes(browser_client):
    value = grant(recipients=("granted.test", "private.test"),
                  sources=("https://granted.test/", "https://private.test/"))
    for url, code in (("https://granted.test/away", "redirect_denied"), ("https://private.test/", "dns_denied"),
                      ("https://granted.test/big", "too_large"), ("https://granted.test/slow", "timeout")):
        with pytest.raises(BrowserChannelError) as refused:
            browser_client.client.run(BrowserRequest(op="navigate", url=url), value)
        assert (refused.value.code, refused.value.sent) == (code, True)


# --- dispatch through a compiled graph, authorized by the owner's grant record ---------

def _transport(granted, client, *, op="read", url="https://granted.test/", excluded_hosts=()):
    from app.runtime.browser_attempt_transport import BrowserAttemptTransport

    subject = granted.subject
    return BrowserAttemptTransport.build(
        domain_store=subject.domain, ledger=subject.ledger, compiled=subject.compiled, node_id="writer",
        binding_id="source-read", client=client, request=BrowserRequest(op=op, url=url, max_text_bytes=4_096),
        grants=granted.grants, excluded_hosts=excluded_hosts)


def test_a_graph_node_with_a_browser_tool_reaches_the_worker_and_seals_its_result(tmp_path, browser_client):
    from app.runtime import node_attempts as na
    from app.runtime import scheduler as sch
    from app.tests.support.browser_grant_chain import dispatch, granted_run, owner_vault
    from app.tests.test_runtime_budget_dispatch import budget_row

    with owner_vault(tmp_path) as vault:
        granted = granted_run(vault)
        subject, run = granted.subject, granted.run
        outcome = dispatch(granted, _transport(granted, browser_client.client))
        ref = dict(outcome.result_refs)[sch.execution_identity(run.run_id, "writer", 0)]
        record = subject.domain.get(ref).body
        content = record["content"]
        assert (content["schema_version"], content["tool_id"], content["operation"]) == (
            "browser-tool-output-v1", "browser_read", "read")
        assert content["observation"]["final_url"] == "https://granted.test/"
        # the sealed output names the owner's grant record it ran under
        assert granted.grant_ref.as_dict() in record["parent_refs"]
        dispatched = granted.grants.for_dispatch(granted.grant_ref, tool_id="browser_read", version="1.0.0")
        # the session ran under exactly the grant built from the owner's record
        assert content["observation"]["grant_sha256"] == dispatched.grant.digest
        assert [entry.as_dict() for entry in dispatched.grant.projection.entries] == \
            granted.view["projection"]["entries"]
        blob = content["output"]["blob"]
        assert (blob["sha256"], blob["size"]) == (sha256(b"hi").hexdigest(), 2)
        attempt_id = na.attempt_identity(run.run_id, "writer", 0, 0)
        assert subject.ledger.get_attempt(attempt_id)["terminal_outcome"] == "succeeded"
        calls = subject.ledger.tool_calls_for_attempt(attempt_id)
        assert [(item["tool_id"], item["state"]) for item in calls] == [("browser_read", "succeeded")]
        row = budget_row(subject, na.reservation_identity(attempt_id))
        assert row["state"] == "finalized" and row["actual_tool_calls"] == 1


def test_a_worker_refusal_is_a_denied_attempt_with_final_usage(tmp_path, browser_client):
    from app.runtime import node_attempts as na
    from app.tests.support.browser_grant_chain import (
        dispatch,
        grant_command,
        granted_run,
        owner_vault,
    )

    with owner_vault(tmp_path) as vault:
        granted = granted_run(vault, tool="browser_navigate", command=grant_command(
            entries=[{"url": "https://granted.test/away", "parameters": []}], data_sources=[]))
        transport = _transport(granted, browser_client.client, url="https://granted.test/away", op="navigate")
        with pytest.raises(SchedulerError, match="node_failed:writer"):
            dispatch(granted, transport)
        attempt_id = na.attempt_identity(granted.run.run_id, "writer", 0, 0)
        attempt = granted.subject.ledger.get_attempt(attempt_id)
        assert (attempt["terminal_outcome"], attempt["usage_finality"]) == ("denied", "final")
        assert [item["state"] for item in granted.subject.ledger.tool_calls_for_attempt(attempt_id)] == ["failed"]


def test_no_reachable_browser_worker_is_definitely_not_sent(tmp_path, fetch_service):
    from app.runtime import node_attempts as na
    from app.tests.support.browser_grant_chain import dispatch, granted_run, owner_vault

    def refused():
        raise OSError("no worker")

    with owner_vault(tmp_path) as vault:
        granted = granted_run(vault)
        transport = _transport(granted, BrowserClient(refused, fetch=fetch_service.control))
        with pytest.raises(SchedulerError, match="node_failed:writer"):
            dispatch(granted, transport)
        ledger = granted.subject.ledger
        attempt_id = na.attempt_identity(granted.run.run_id, "writer", 0, 0)
        # the ledger keeps a committed send intent as possibly sent; the vouched effect is journaled
        assert ledger.get_attempt(attempt_id)["terminal_outcome"] == "outcome_unknown"
        status = ledger.dispatch_status(na._command_identity(attempt_id, "send"))
        assert "definitely_not_sent" in json.dumps(status, default=str)
        assert [item["state"] for item in ledger.tool_calls_for_attempt(attempt_id)] == ["failed"]


def test_build_refuses_mismatched_tools_operations_grants_and_the_product_origin(tmp_path, browser_client):
    from app.runtime.browser_attempt_transport import BrowserAttemptTransport
    from app.tests.support.browser_grant_chain import (
        compiled_with_grant,
        granted_run,
        owner_vault,
    )
    from app.tests.test_graph_contract import (
        authority_with,
        compile_value,
        trusted_tool,
    )
    from app.tests.test_graph_execution import linear_graph

    with owner_vault(tmp_path) as vault:
        granted = granted_run(vault)
        subject = granted.subject
        base = {"domain_store": subject.domain, "ledger": subject.ledger, "compiled": subject.compiled,
                "node_id": "writer", "binding_id": "source-read", "client": browser_client.client,
                "grants": granted.grants}
        home = BrowserRequest(op="read", url="https://granted.test/")
        assert BrowserAttemptTransport.build(**base, request=home).effect_class == "read"
        with pytest.raises(ValueError):  # the operation is not the bound tool's
            BrowserAttemptTransport.build(**base, request=BrowserRequest(op="screenshot", url="https://granted.test/"))
        with pytest.raises(ValueError):  # outside the grant's sources
            BrowserAttemptTransport.build(**base, request=BrowserRequest(op="read", url="https://other.test/"))
        with pytest.raises(ValueError):  # under a source, but not an exact projection entry
            BrowserAttemptTransport.build(**base, request=BrowserRequest(op="read", url="https://granted.test/x"))
        with pytest.raises(ValueError):  # a value the owner never declared
            BrowserAttemptTransport.build(**base, request=BrowserRequest(
                op="read", url="https://granted.test/search?q=private-diagnosis"))
        assert BrowserAttemptTransport.build(**base, request=BrowserRequest(
            op="read", url="https://granted.test/search?q=%EA%B3%B5%EA%B0%9C%20%EC%9E%90%EB%A3%8C"))
        with pytest.raises(ValueError):  # the product's own host is never a recipient
            BrowserAttemptTransport.build(**base, request=home, excluded_hosts=("granted.test",))
        with pytest.raises(ValueError):  # a tool that is not a browser tool
            BrowserAttemptTransport.build(**{**base, "compiled": compiled_with_grant("text_profile", granted.grant_ref)},
                                          request=home)
        with pytest.raises(ValueError):  # a binding whose grant_ref is not an owner grant record
            BrowserAttemptTransport.build(**{**base, "compiled": compile_value(linear_graph(), compilation_authority=(
                authority_with([trusted_tool(tool_id="browser_read", version="1.0.0")])))}, request=home)
        with pytest.raises(ValueError):  # a browser tool whose definition claims another effect
            external = compile_value(linear_graph(), compilation_authority=authority_with([
                trusted_tool("external_reversible", tool_id="browser_read", version="1.0.0")]))
            BrowserAttemptTransport.build(**{**base, "compiled": external}, request=home)
        with pytest.raises(TypeError):  # a grant object supplied in code is not an authority
            BrowserAttemptTransport.build(**{**base, "grants": grant()}, request=home)


def test_the_server_attaches_the_browser_tools_or_states_them_unavailable(tmp_path):
    from app.runtime.browser_attempt_transport import (
        BrowserToolset,
        BrowserToolsUnavailable,
    )
    from app.server import create_app
    from app.tests.test_run_artifact_previews import configured

    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    _profile, _capability, arguments = configured(tmp_path / "a")
    with pytest.raises(ValueError):
        create_app(tmp_path / "a" / "data", **arguments, browser_worker=object())
    with pytest.raises(ValueError):  # only the verified cp-browser pair root is an endpoint
        create_app(tmp_path / "a" / "data", **arguments, browser_worker=BrowserControlConfiguration(
            browser_pair_root=str(tmp_path / "cp-browser"), browser_requester_boot_id="control-boot",
            fetch_pair_root="/run/deeptwin/ipc/cp-fetch", fetch_requester_boot_id="control-boot"))
    app = create_app(tmp_path / "a" / "data", **arguments)
    assert type(app.state.browser_tools) is BrowserToolsUnavailable and app.state.browser_tools.available is False
    with pytest.raises(BrowserChannelError) as unavailable:
        app.state.browser_tools.transport_for()
    assert (unavailable.value.code, unavailable.value.sent) == ("unavailable", False)
    _profile, _capability, arguments = configured(tmp_path / "b")
    app = create_app(tmp_path / "b" / "data", **arguments, browser_worker=BrowserControlConfiguration(
        browser_pair_root="/run/deeptwin/ipc/cp-browser", browser_requester_boot_id="control-boot",
        fetch_pair_root="/run/deeptwin/ipc/cp-fetch", fetch_requester_boot_id="control-boot"))
    assert type(app.state.browser_tools) is BrowserToolset and app.state.browser_tools.available is True


def test_the_server_names_the_browser_worker_config_argument():
    source = (REPOSITORY / "app" / "server.py").read_text()
    assert "'--browser-worker-config'" in source and "BrowserControlConfiguration.from_mapping" in source


def test_chromium_is_never_started_with_a_sandbox_relaxation_a_port_or_a_resolver():
    from app.adapters.browser import chromium_arguments

    argv = chromium_arguments("/opt/chromium/headless_shell", "/run/deeptwin/browser-profile/session-x", 800, 600)
    canary = (REPOSITORY / "deploy" / "tests" / "browser_worker_canary.mjs").read_text()
    forbidden = canary.split("FORBIDDEN_BROWSER_ARGUMENTS = [", 1)[1].split("];", 1)[0]
    names = [item.strip().strip('",') for item in forbidden.split("\n") if item.strip().startswith('"')]
    assert "--no-sandbox" in names
    assert not any(item.split("=")[0] in names for item in argv)
    assert "--remote-debugging-pipe" in argv and not any(item.startswith("--remote-debugging-port") for item in argv)
    assert "--host-resolver-rules=MAP * ~NOTFOUND" in argv and "--no-proxy-server" in argv


# --- import boundary ------------------------------------------------------------------

_DRIVER_MODULES = ("app.adapters.browser", "app.workers.browser_service", "app.workers.browser_worker_main",
                   "app.workers.fetch_service", "app.workers.fetch_worker_main")


def test_the_control_plane_never_imports_the_browser_driver_or_the_fetch_engine():
    probe = ("import sys, app.server, app.runtime.browser_attempt_transport, app.workers.browser_channel, "
             "app.workers.fetch_channel\n"
             f"print([name for name in {list(_DRIVER_MODULES)!r} if name in sys.modules])")
    child = subprocess.run([sys.executable, "-B", "-c", probe], cwd=REPOSITORY, capture_output=True, text=True,
                           timeout=120, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert child.returncode == 0, child.stderr[-2000:]
    assert child.stdout.strip() == "[]"


def test_only_the_browser_service_imports_the_driver():
    importers = []
    for path in (REPOSITORY / "app").rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [module] + [f"{module}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            if any(name.endswith("adapters.browser") or name == "browser" and isinstance(node, ast.ImportFrom)
                   and node.level and (node.module or "") == "adapters" for name in names):
                importers.append(path.relative_to(REPOSITORY).as_posix())
    assert sorted(set(importers)) == ["app/workers/browser_service.py"]


# --- the root-only real-process qualification ----------------------------------------

def _chromium():
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    found = sorted(glob.glob(os.path.join(root, "chromium_headless_shell-*", "chrome-linux", "headless_shell")))
    return found[-1] if found else None


CHROMIUM = _chromium()
real_process = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED") or not hasattr(os, "geteuid")
    or os.geteuid() != 0 or CHROMIUM is None or shutil.which("openssl") is None
    or shutil.which("unshare") is None or shutil.which("setpriv") is None or shutil.which("nsenter") is None,
    reason="the real browser qualification needs Linux, root, openssl, util-linux and a headless Chromium",
)
CONTROL = 20_102
FETCH = 20_104
BROWSER = 20_105
BOOTS = {"control": "control-boot-t043", "browser": "browser-boot-t043"}
SECONDS = 90


def _png(color, size=4):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _site_pages():
    html = "text/html; charset=utf-8"
    return {
        ("granted.test", "/"): (200, {"Content-Type": html, "Set-Cookie": "sid=secret"},
                                (b"<html><head><title>Fixture Home</title></head><body><h1>Hello fixture</h1>"
                                 b"<p>granted text</p><img src='/pixel.png'>"
                                 b"<img src='https://other.test/tracker.png'>"
                                 b"<script>document.title='script ran'</script></body></html>")),
        ("granted.test", "/pixel.png"): (200, {"Content-Type": "image/png"}, _png((0, 128, 0))),
        ("granted.test", "/red"): (200, {"Content-Type": html},
                                   (b"<html><head><title>Red</title><style>html,body{margin:0;height:100%;"
                                    b"background:#ff0000}</style></head><body></body></html>")),
        ("granted.test", "/redirect-home"): (302, {"Location": "/final"}, b""),
        ("granted.test", "/final"): (200, {"Content-Type": html},
                                     b"<html><head><title>Final</title></head><body>arrived</body></html>"),
        ("granted.test", "/redirect-away"): (302, {"Location": "https://other.test/landing"}, b""),
        ("granted.test", "/big"): (200, {"Content-Type": html}, b"<html><body>" + b"x" * (3 * 1024 * 1024)),
        ("granted.test", "/slow"): ("slow", {"Content-Type": html}, b"<html><body>late</body></html>"),
        ("granted.test", "/redirect-loopback"): (302, {"Location": "https://127.0.0.1/"}, b""),
        ("granted.test", "/redirect-ipv6"): (302, {"Location": "https://[::1]/"}, b""),
        ("granted.test", "/redirect-private"): (302, {"Location": "https://private.test/"}, b""),
        ("granted.test", "/frame"): (200, {"Content-Type": html},
                                     (b"<html><head><title>Frame</title></head><body>outer"
                                      b"<iframe src='https://other.test/landing'></iframe></body></html>")),
        ("granted.test", "/download"): (200, {"Content-Type": "application/octet-stream",
                                              "Content-Disposition": "attachment; filename=x.bin"}, b"\x00" * 64),
        ("other.test", "/landing"): (200, {"Content-Type": html}, b"<title>Other</title>other"),
        ("other.test", "/tracker.png"): (200, {"Content-Type": "image/png"}, _png((255, 255, 0))),
        # the projection cases: a declared value in the query, and a page / a redirect that
        # try to carry it on to another recipient
        ("granted.test", "/search?q=deeptwin"): (200, {"Content-Type": html},
                                                 b"<html><head><title>Search</title></head><body>found it</body></html>"),
        ("granted.test", "/leak?q=deeptwin"): (200, {"Content-Type": html},
                                               (b"<html><head><title>Leak</title></head><body>leak"
                                                b"<img src='https://other.test/collect?v=deeptwin'>"
                                                b"<img src='https://other.test/tracker.png'></body></html>")),
        ("granted.test", "/redirect-leak?q=deeptwin"): (302, {"Location": "https://other.test/collect?v=DeepTwin"},
                                                        b""),
        ("other.test", "/collect?v=deeptwin"): (200, {"Content-Type": "image/png"}, _png((0, 0, 0))),
        ("other.test", "/collect?v=DeepTwin"): (200, {"Content-Type": html}, b"<title>Collected</title>"),
        ("rebind.test", "/"): (200, {"Content-Type": html},
                               (b"<html><head><title>Rebind</title></head><body>first answer"
                                b"<img src='/pixel.png'></body></html>")),
        ("rebind.test", "/pixel.png"): (200, {"Content-Type": "image/png"}, _png((0, 0, 255))),
    }


class _SiteHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        self.server.seen.append((host, self.path, dict(self.headers)))
        status, headers, body = self.server.pages.get((host, self.path), (404, {"Content-Type": "text/plain"}, b"no"))
        if status == "slow":
            time.sleep(6)
            status = 200
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


@pytest.fixture(scope="module")
def site():
    if os.geteuid() != 0 or CHROMIUM is None or shutil.which("openssl") is None:
        pytest.skip("the real browser qualification needs root, openssl and Chromium")
    directory = Path(tempfile.mkdtemp(prefix="dt-t043-site-", dir="/tmp"))
    names = ["granted.test", "other.test", "rebind.test", "private.test"]

    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=directory, check=True, capture_output=True)

    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "2",
            "-subj", "/CN=deeptwin t043 test ca")
    (directory / "san.cnf").write_text("subjectAltName=" + ",".join(f"DNS:{name}" for name in names) + "\n")
    openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key", "-out", "leaf.csr", "-subj",
            "/CN=granted.test")
    openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out",
            "leaf.pem", "-days", "2", "-extfile", "san.cnf")
    os.chmod(directory, 0o755)
    os.chmod(directory / "ca.pem", 0o644)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SiteHandler)
    httpd.daemon_threads = True
    httpd.seen, httpd.pages = [], _site_pages()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(directory / "leaf.pem", directory / "leaf.key")
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(httpd=httpd, port=httpd.server_address[1], ca=directory / "ca.pem")
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(directory, ignore_errors=True)


def _write(path, value, mode=0o644):
    path.write_text(json.dumps(value))
    os.chmod(path, mode)
    return path


def _environment():
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPOSITORY), "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8"}


class Process:
    def __init__(self, argv, *, ready, **options):
        self.process = subprocess.Popen(argv, cwd=REPOSITORY, env=_environment(), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
        self.lines: list[str] = []
        self._changed = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()
        if ready is not None:
            self.wait_for(ready)

    def _read(self):
        for raw in self.process.stderr:
            with self._changed:
                self.lines.append(raw.decode(errors="replace").rstrip("\n"))
                self._changed.notify_all()
        with self._changed:
            self._changed.notify_all()

    def events(self):
        with self._changed:
            return [json.loads(line) for line in self.lines if line.startswith("{")]

    def wait_for(self, name):
        limit = time.monotonic() + SECONDS
        with self._changed:
            while not any(f'"event": "{name}"' in line for line in self.lines):
                if self.process.poll() is not None:
                    pytest.fail(f"process exited before {name}: {self.lines[-20:]}")
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    pytest.fail(f"process never logged {name}: {self.lines[-20:]}")
                self._changed.wait(min(remaining, 0.5))

    def stop(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
        try:
            return self.process.wait(SECONDS)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(10)


def _browser_argv(base, *, isolated=True):
    python = [sys.executable, "-B", "-m", "app.tests.support.browser_worker_children", "serve-browser", str(base),
              f"--attachment-config={base / 'config' / 'browser.json'}"]
    drop = ["setpriv", f"--reuid={BROWSER}", f"--regid={BROWSER}", "--groups=21104,21110", "--no-new-privs",
            "--inh-caps=-all", "--"]
    return (["unshare", "--net", "--"] if isolated else []) + drop + python


@pytest.fixture(scope="module")
def deployment(site):
    from app.tests.support.browser_worker_children import profiles
    from app.workers import ipc_root

    base = Path(tempfile.mkdtemp(prefix="dt-t043-browser-", dir="/tmp")).resolve()
    processes = []
    try:
        os.chmod(base, 0o755)
        for name, (root, _spec) in profiles(base).items():
            (base / name).mkdir(mode=0o700)
            ipc_root.initialize_pair_root(root)
        config = base / "config"
        config.mkdir(mode=0o755)
        profile_root = base / "browser-profile"
        profile_root.mkdir(mode=0o700)
        os.chown(profile_root, BROWSER, BROWSER)
        public = {**PUBLIC}
        _write(config / "fixture.json", {
            "resolver": {"granted.test": [[public["granted.test"]]], "other.test": [[public["other.test"]]],
                         "private.test": [["10.0.0.5"]],
                         "rebind.test": [[public["rebind.test"]], ["127.0.0.1"]]},
            "public_addresses": sorted(public.values()), "port": site.port, "timeout": 10, "ca": str(site.ca)})
        _write(config / "fetch.json", {
            "schema": fetch_channel.ATTACHMENT_SCHEMA, "control_pair_root": str(base / "cp-fetch"),
            "control_requester_boot_id": BOOTS["control"], "browser_pair_root": str(base / "browser-fetch"),
            "browser_requester_boot_id": BOOTS["browser"]})
        _write(config / "browser.json", {
            "schema": browser_channel.WORKER_ATTACHMENT_SCHEMA, "pair_root": str(base / "cp-browser"),
            "requester_boot_id": BOOTS["control"], "fetch_pair_root": str(base / "browser-fetch"),
            "fetch_requester_boot_id": BOOTS["browser"], "chromium_path": CHROMIUM,
            "profile_root": str(profile_root)})
        fetch = Process([sys.executable, "-B", "-m", "app.tests.support.browser_worker_children", "serve-fetch",
                         str(base), str(config / "fixture.json"), f"--attachment-config={config / 'fetch.json'}"],
                        ready="fetch_ready", user=FETCH, group=FETCH, extra_groups=[21102, 21110])
        processes.append(fetch)
        browser = Process(_browser_argv(base), ready="browser_ready")
        processes.append(browser)
        yield SimpleNamespace(base=base, fetch=fetch, browser=browser, profile_root=profile_root, site=site)
    finally:
        for process in reversed(processes):
            process.stop()
        shutil.rmtree(base, ignore_errors=True)


def _requester(base, role, plan, *, uid=CONTROL, groups=(21104, 21102)):
    child = subprocess.run(
        [sys.executable, "-B", "-m", "app.tests.support.browser_worker_children", role, str(base)],
        cwd=REPOSITORY, env=_environment(), user=uid, group=uid, extra_groups=list(groups),
        input=json.dumps({"browser_boot": BOOTS["control"], "fetch_boot": BOOTS["control"], **plan}).encode(),
        capture_output=True, timeout=SECONDS * 3, check=False)
    assert child.returncode == 0, child.stderr.decode(errors="replace")[-3000:]
    return json.loads(child.stdout)


# the exact pure navigations the real-process cases open (the projection's entries)
REAL_NAVIGATIONS = tuple("https://granted.test" + path for path in (
    "/", "/redirect-home", "/red", "/redirect-away", "/redirect-loopback", "/redirect-ipv6", "/redirect-private",
    "/frame", "/download", "/big", "/slow")) + ("https://private.test/", "https://rebind.test/")
TOPIC = sha256(b"deeptwin").hexdigest()


def _grant(**changes):
    """A `BrowserGrant.as_dict()` mapping; pure navigation to the entries under its sources
    unless a projection is named."""
    values = {"sources": ["https://granted.test/"], "recipients": ["granted.test"],
              "max_response_bytes": 1024 * 1024, "max_total_bytes": 4 * 1024 * 1024, "max_requests": 32,
              "max_redirects": 3, "ttl_ms": 60_000}
    values.update(changes)
    values.setdefault("projection", pure_navigation(tuple(values["sources"]), REAL_NAVIGATIONS).as_dict())
    return values


def _topic_grant():
    """`q` may carry only the declared topic value `deeptwin`; other.test is a recipient,
    so only the projection stands between the value and that host."""
    entries = [{"url": "https://granted.test/", "parameters": []}] + [
        {"url": "https://granted.test" + path, "parameters": [{"name": "q", "source": "topic"}]}
        for path in ("/search", "/leak", "/redirect-leak")]
    return _grant(recipients=["granted.test", "other.test"], projection={
        "entries": entries, "data_sources": [{"source_id": "topic", "value_sha256": [TOPIC]}]})


@real_process
def test_the_real_workers_browse_the_fixture_site_only_through_the_grant(deployment):
    cases = [
        {"name": "read", "request": {"op": "read", "url": "https://granted.test/", "deadline_ms": 20_000},
         "grant": _grant()},
        {"name": "navigate_redirect", "request": {"op": "navigate", "url": "https://granted.test/redirect-home"},
         "grant": _grant()},
        {"name": "screenshot", "request": {"op": "screenshot", "url": "https://granted.test/red", "width": 320,
                                           "height": 200}, "grant": _grant()},
        {"name": "ungranted_local", "request": {"op": "navigate", "url": "https://other.test/landing"},
         "grant": _grant()},
        {"name": "ungranted_worker", "skip_local_check": True, "register_url": "https://granted.test/",
         "request": {"op": "navigate", "url": "https://other.test/landing"}, "grant": _grant()},
        {"name": "redirect_away", "request": {"op": "navigate", "url": "https://granted.test/redirect-away"},
         "grant": _grant()},
        {"name": "private", "request": {"op": "navigate", "url": "https://private.test/"},
         "grant": _grant(sources=["https://private.test/"], recipients=["private.test"])},
        {"name": "rebind", "request": {"op": "read", "url": "https://rebind.test/"},
         "grant": _grant(sources=["https://rebind.test/"], recipients=["rebind.test"])},
        {"name": "redirect_loopback", "request": {"op": "navigate", "url": "https://granted.test/redirect-loopback"},
         "grant": _grant()},
        {"name": "redirect_ipv6", "request": {"op": "navigate", "url": "https://granted.test/redirect-ipv6"},
         "grant": _grant()},
        {"name": "redirect_private", "request": {"op": "navigate", "url": "https://granted.test/redirect-private"},
         "grant": _grant(recipients=["granted.test", "private.test"],
                         sources=["https://granted.test/", "https://private.test/"])},
        {"name": "frame", "request": {"op": "read", "url": "https://granted.test/frame"}, "grant": _grant()},
        {"name": "download", "request": {"op": "navigate", "url": "https://granted.test/download"},
         "grant": _grant()},
        {"name": "oversize", "request": {"op": "navigate", "url": "https://granted.test/big"}, "grant": _grant()},
        {"name": "timeout", "request": {"op": "navigate", "url": "https://granted.test/slow", "deadline_ms": 3_000},
         "grant": _grant()},
    ]
    results = _requester(deployment.base, "request", {"cases": cases})

    read = results["read"]
    assert read["ok"] is True and read["digest_matches"] is True
    assert read["title"] == "Fixture Home"  # the page's script never ran
    assert "Hello fixture" in read["text"] and "granted text" in read["text"]
    assert read["final_url"] == "https://granted.test/" and read["status"] == 200
    # the document, its granted image; the other host's tracker was refused
    assert read["allowed"] >= 2 and read["denied"] >= 1
    assert read["sandbox"]["seccomp_filter"] is True and read["sandbox"]["pid_namespace"] is True
    page = _site_pages()[("granted.test", "/")][2]
    assert read["document_sha256"] == sha256(page).hexdigest()

    redirected = results["navigate_redirect"]
    assert redirected["ok"] is True and redirected["final_url"] == "https://granted.test/final"
    assert redirected["title"] == "Final" and redirected["output_bytes"] == 0

    shot = results["screenshot"]
    assert shot["ok"] is True and (shot["width"], shot["height"]) == (320, 200) and shot["digest_matches"] is True
    assert shot["center"] == [255, 0, 0]  # the page was really rendered, not a blank frame

    assert results["ungranted_local"] == {"ok": False, "code": "grant_denied", "sent": False}
    assert results["ungranted_worker"]["ok"] is False and results["ungranted_worker"]["code"] == "grant_denied"
    assert results["redirect_away"]["code"] == "redirect_denied"
    assert results["private"]["code"] == "dns_denied"
    rebind = results["rebind"]  # the first answer was public; the rebinding answer is refused
    assert rebind["ok"] is True and rebind["title"] == "Rebind" and rebind["denied"] >= 1
    # a redirect toward loopback, an IPv6 literal or a name resolving privately never leaves the grant
    assert results["redirect_loopback"]["code"] == "redirect_denied"
    assert results["redirect_ipv6"]["code"] == "redirect_denied"
    assert results["redirect_private"]["code"] == "dns_denied"
    frame = results["frame"]  # the page renders; its frame toward another host is refused
    assert frame["ok"] is True and frame["title"] == "Frame" and frame["denied"] >= 1
    assert results["download"] == {"ok": False, "code": "render_failed", "sent": True}  # downloads are denied
    assert results["oversize"]["code"] == "too_large"
    assert results["timeout"]["code"] == "timeout"

    # the fixture never saw another host than the granted ones, never the tracker, never a cookie
    hosts = {host for host, _path, _headers in deployment.site.httpd.seen}
    assert "other.test" not in hosts
    assert not any("Cookie" in headers or "Referer" in headers for _h, _p, headers in deployment.site.httpd.seen)
    # the profile root is empty: every session's profile was removed
    assert os.listdir(deployment.profile_root) == []
    for event in deployment.browser.events() + deployment.fetch.events():
        assert set(event) <= {"event", "class", "outcome", "pair"}


@real_process
def test_the_real_fetch_worker_enforces_the_grants_projection(deployment):
    before = len(deployment.site.httpd.seen)
    cases = [
        # a declared value in the one parameter that may carry it: fetched as is
        {"name": "declared", "request": {"op": "read", "url": "https://granted.test/search?q=deeptwin"},
         "grant": _topic_grant()},
        # an undeclared value: control refuses before anything is sent …
        {"name": "undeclared_local", "request": {"op": "navigate",
                                                 "url": "https://granted.test/search?q=private-diagnosis"},
         "grant": _topic_grant()},
        # … and, with control's pre-check bypassed, the fetch service refuses it at registration
        {"name": "undeclared_register", "skip_local_check": True,
         "request": {"op": "navigate", "url": "https://granted.test/search?q=private-diagnosis"},
         "grant": _topic_grant()},
        # a browser that asks for another navigation than the registered one: the fetch
        # service refuses the navigation itself
        {"name": "undeclared_navigation", "skip_local_check": True, "register_url": "https://granted.test/",
         "request": {"op": "navigate", "url": "https://granted.test/search?q=private-diagnosis"},
         "grant": _topic_grant()},
        # the same value spelled another way (`+`, a second parameter) is not the entry
        {"name": "respelled", "skip_local_check": True, "register_url": "https://granted.test/",
         "request": {"op": "navigate", "url": "https://granted.test/search?q=deeptwin&x=1"},
         "grant": _topic_grant()},
        # a path the pure-navigation projection does not list, under a granted source
        {"name": "unlisted_path", "request": {"op": "navigate", "url": "https://granted.test/private-notes"},
         "grant": _grant()},
        # derived requests: the page's image carrying the value to another recipient is
        # refused, its value-free image is not; a redirect carrying it (another case) is refused
        {"name": "derived_image", "request": {"op": "read", "url": "https://granted.test/leak?q=deeptwin"},
         "grant": _topic_grant()},
        {"name": "derived_redirect", "request": {"op": "navigate",
                                                 "url": "https://granted.test/redirect-leak?q=deeptwin"},
         "grant": _topic_grant()},
    ]
    results = _requester(deployment.base, "request", {"cases": cases})
    declared = results["declared"]
    assert declared["ok"] is True and declared["title"] == "Search" and "found it" in declared["text"]
    assert declared["final_url"] == "https://granted.test/search?q=deeptwin"
    assert results["undeclared_local"] == {"ok": False, "code": "projection_denied", "sent": False}
    assert results["undeclared_register"] == {"ok": False, "code": "projection_denied", "sent": True,
                                              "stage": "register"}
    assert results["undeclared_navigation"]["ok"] is False
    assert results["undeclared_navigation"]["code"] == "projection_denied"
    assert results["respelled"]["code"] == "projection_denied"
    assert results["unlisted_path"] == {"ok": False, "code": "projection_denied", "sent": False}
    leak = results["derived_image"]
    assert leak["ok"] is True and leak["title"] == "Leak" and leak["denied"] >= 1 and leak["allowed"] >= 2
    assert results["derived_redirect"]["ok"] is False
    assert results["derived_redirect"]["code"] == "projection_denied"
    seen = [(host, path) for host, path, _headers in deployment.site.httpd.seen[before:]]
    # the fixture got the declared request, the value-free image, and never the value
    # toward another host nor an undeclared value at all
    assert ("granted.test", "/search?q=deeptwin") in seen and ("other.test", "/tracker.png") in seen
    assert not any(path.startswith("/collect") for _host, path in seen)
    assert not any("private-diagnosis" in path or "private-notes" in path for _host, path in seen)
    for event in deployment.browser.events() + deployment.fetch.events():
        assert set(event) <= {"event", "class", "outcome", "pair"}


@real_process
def test_a_graph_node_reaches_the_real_worker_through_the_attempt_transport(deployment):
    result = _requester(deployment.base, "dispatch", {
        "tool": "browser_read", "request": {"op": "read", "url": "https://granted.test/search?q=deeptwin",
                                            "max_text_bytes": 4096}})
    assert result["result"]["tool_id"] == "browser_read" and result["result"]["title"] == "Search"
    assert result["result"]["output_blob"]["size"] > 0 and "found it" in result["output_text"]
    assert result["result"]["grant_parent"] is True  # sealed under the owner's grant record
    assert result["tool_calls"] == [{"state": "succeeded", "tool_id": "browser_read"}]


@real_process
def test_a_revoked_grant_is_refused_at_dispatch_before_anything_is_sent(deployment):
    before = len(deployment.site.httpd.seen)
    result = _requester(deployment.base, "dispatch", {
        "tool": "browser_read", "revoke": True,
        "request": {"op": "read", "url": "https://granted.test/", "max_text_bytes": 4096}})
    assert result["result"] is None and result["scheduler_error"].startswith("node_failed:writer")
    assert result["attempt"] == {"terminal_outcome": "denied", "usage_finality": "final"}
    assert result["tool_calls"] == [{"state": "failed", "tool_id": "browser_read"}]
    assert deployment.site.httpd.seen[before:] == []  # nothing reached the site


@real_process
def test_the_worker_namespace_has_no_direct_network(deployment):
    pid = deployment.browser.process.pid
    namespace = os.readlink(f"/proc/{pid}/ns/net")
    assert namespace != os.readlink("/proc/self/ns/net")
    interfaces = [line.split(":")[0].strip() for line in Path(f"/proc/{pid}/net/dev").read_text().splitlines()[2:]]
    assert interfaces == ["lo"]
    probe = ("import socket, sys\n"
             "for address in [('127.0.0.1', int(sys.argv[1])), ('93.184.216.34', 443), ('10.0.0.5', 443)]:\n"
             "    s = socket.socket(); s.settimeout(3)\n"
             "    try:\n"
             "        s.connect(address); print('connected', address)\n"
             "    except OSError as error:\n"
             "        print('refused', type(error).__name__)\n"
             "try:\n"
             "    socket.getaddrinfo('granted.test', 443); print('resolved')\n"
             "except OSError:\n"
             "    print('unresolved')\n")
    child = subprocess.run(["nsenter", f"--net=/proc/{pid}/ns/net", "setpriv", f"--reuid={BROWSER}",
                            f"--regid={BROWSER}", "--clear-groups", "--", sys.executable, "-c", probe,
                            str(deployment.site.port)], capture_output=True, text=True, timeout=60, check=False)
    assert child.returncode == 0, child.stderr
    lines = child.stdout.splitlines()
    assert not any(line.startswith("connected") for line in lines), lines
    assert lines[-1] == "unresolved"


@real_process
def test_a_browser_worker_with_a_network_path_refuses_to_start(deployment):
    process = Process(_browser_argv(deployment.base, isolated=False), ready=None)
    assert process.process.wait(SECONDS) == 1
    assert [event["event"] for event in process.events()] == ["network_present"]


@real_process
def test_a_foreign_identity_is_refused_by_the_browser_worker(deployment):
    result = _requester(deployment.base, "request", {"cases": [
        {"name": "foreign", "request": {"op": "navigate", "url": "https://granted.test/"}, "grant": _grant()}]},
        uid=FETCH, groups=(21104, 21102))
    assert result["foreign"]["ok"] is False and result["foreign"]["sent"] is False
