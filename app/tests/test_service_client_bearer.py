"""The composed service-client path on the supported factory (T025).

The owner manages durable clients from a browser session with CSRF; a client's exact TLS
bearer reaches only routes whose descriptor declares `browser_session_or_service_bearer`
and only on the portable HTTPS profile. Loopback and plain HTTP never parse a bearer.
"""

import base64
import logging
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import service_clients as service_client_api
from app.domain.request_identity import RequestDenied, ServiceClientRead
from app.server import create_app
from app.tests.test_web_owner_integration import configured, headers

CANARY = "dt_sc_" + base64.urlsafe_b64encode(b"deeptwin-t025-canary-not-issued!").rstrip(b"=").decode()


def bootstrap(client, profile, capability):
    response = client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
        "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": capability})
    assert response.status_code == 201, response.text
    return response.json()["csrf_token"]


def creation(scopes, **changes):
    value = {"client_id": str(uuid4()), "name": "자동화", "scopes": scopes,
             "allowed_network_profile": "portable_https", "expires_at": int(time.time()) + 3_600}
    value.update(changes)
    return value


def bearer(secret):
    return {"Authorization": "Bearer " + secret}


def create_client(client, profile, csrf, scopes):
    response = client.post(profile.base_path + "api/v1/service-clients", headers=headers(profile, csrf),
                           json=creation(scopes))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["secret_available_once"] is True and body["secret"].startswith("dt_sc_")
    return body["client"], body["secret"]


@pytest.fixture
def portable(tmp_path):
    profile, capability, arguments = configured(tmp_path, "https")
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap(client, profile, capability)
        yield app, client, profile, csrf, (tmp_path, arguments)


def test_descriptors_declare_exactly_the_public_reads_for_a_bearer(portable):
    app, *_ = portable
    composition = app.state.route_composition
    admitted = {route.route_id: route.required_scope for route in composition.routes
                if route.auth_policy == "browser_session_or_service_bearer"}
    assert admitted == {"events.read": "events.read", "events.stream": "events.read",
                        "events.type": "events.read", "snapshot.read": "snapshot.read"}
    assert composition.bearer_scopes() == ("events.read", "snapshot.read")
    for route in composition.routes:
        if route.route_id.startswith("service-clients."):
            assert route.auth_policy == "browser_session"
    assert composition.bearer_route("POST", "/api/v1/commands") is None
    assert composition.bearer_route("GET", "/api/v1/commands/" + str(uuid4())) is None
    assert composition.bearer_route("GET", "/api/v1/events/stream").route_id == "events.stream"


def test_owner_issues_once_and_the_bearer_reads_what_the_browser_reads(portable, caplog):
    caplog.set_level(logging.DEBUG)
    app, client, profile, csrf, _ = portable
    record, secret = create_client(client, profile, csrf, ["snapshot.read", "events.read"])
    assert record["allowed_network_profile"] == "portable_https"
    base = profile.base_path + "api/v1/"
    listing = client.get(base + "service-clients", headers=headers(profile))
    single = client.get(base + "service-clients/" + record["client_id"], headers=headers(profile))
    assert listing.status_code == single.status_code == 200
    assert single.json() == record and listing.json()["items"] == [record]
    assert secret not in listing.text + single.text

    browser_snapshot = client.get(base + "snapshot", headers=headers(profile))
    cookies = dict(client.cookies)
    client.cookies.clear()
    service_snapshot = client.get(base + "snapshot", headers=bearer(secret))
    assert service_snapshot.status_code == 200, service_snapshot.text
    # parity: the same projection and cursor through either credential
    assert service_snapshot.json() == browser_snapshot.json()
    events = client.get(base + "events", headers=bearer(secret))
    assert events.status_code == 200
    assert client.get(base + "events/stream", headers=bearer(secret)).status_code == 200
    assert client.head(base + "snapshot", headers=bearer(secret)).status_code == 200
    client.cookies.update(cookies)
    assert client.get(base + "events", headers=headers(profile)).json() == events.json()

    with app.state.store._connection() as db:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            for row in db.execute(f'SELECT * FROM "{table}"'):
                assert secret not in "".join(str(value) for value in tuple(row)), table
    assert secret not in caplog.text


def test_bearer_denials_scope_cookie_routes_and_revocation(portable):
    _, client, profile, csrf, _ = portable
    base = profile.base_path + "api/v1/"
    _, events_secret = create_client(client, profile, csrf, ["events.read"])
    snapshot_only, secret = create_client(client, profile, csrf, ["snapshot.read"])
    cookies = dict(client.cookies)
    client.cookies.clear()
    # a valid credential without the route's declared scope
    denied = client.get(base + "snapshot", headers=bearer(events_secret))
    assert denied.status_code == 403 and denied.json()["code"] == "access_denied"
    assert client.get(base + "events", headers=bearer(secret)).status_code == 403
    # browser-session-only routes never admit a bearer, valid or not
    for path in ("commands/" + str(uuid4()), "extensions/candidates", "extensions/bindings",
                 "service-clients", "service-clients/" + snapshot_only["client_id"]):
        response = client.get(base + path, headers=bearer(secret))
        assert response.status_code == 401, path
    revoke_by_bearer = client.post(base + "service-clients/" + snapshot_only["client_id"] + "/revoke",
                                   headers=bearer(secret), json={"expected_revision": 1})
    assert revoke_by_bearer.status_code == 401
    # unknown, malformed and duplicated credentials
    assert client.get(base + "snapshot", headers=bearer(CANARY)).status_code == 401
    assert client.get(base + "snapshot", headers={"Authorization": "Basic " + secret}).status_code == 401
    assert client.get(base + "snapshot", headers=[("Authorization", "Bearer " + secret),
                                                  ("Authorization", "Bearer " + secret)]).status_code == 400
    assert client.get(base + "snapshot", headers=bearer(secret)).status_code == 200
    # no browser-cookie fallback: a bearer and a cookie together are refused
    client.cookies.update(cookies)
    assert client.get(base + "snapshot", headers={**headers(profile), **bearer(secret)}).status_code == 401
    # revocation takes effect on the very next request
    revoked = client.post(base + "service-clients/" + snapshot_only["client_id"] + "/revoke",
                          headers=headers(profile, csrf), json={"expected_revision": 1})
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    client.cookies.clear()
    assert client.get(base + "snapshot", headers=bearer(secret)).status_code == 401
    assert client.get(base + "events", headers=bearer(events_secret)).status_code == 200


def test_owner_commands_require_csrf_and_only_grantable_scopes(portable):
    _, client, profile, csrf, _ = portable
    path = profile.base_path + "api/v1/service-clients"
    assert client.post(path, headers=headers(profile), json=creation(["snapshot.read"])).status_code == 403
    for value in (creation(["command:work.revise"]), creation(["artifact.read"]),
                  creation(["snapshot.read"], allowed_network_profile="dedicated_https"),
                  creation(["snapshot.read"], expires_at=int(time.time()) + 90_000)):
        assert client.post(path, headers=headers(profile, csrf), json=value).status_code == 422
    assert client.post(path, headers=headers(profile, csrf),
                       json={**creation(["snapshot.read"]), "extra": 1}).status_code == 400
    record, secret = create_client(client, profile, csrf, ["snapshot.read"])
    rotated = client.post(path + "/" + record["client_id"] + "/rotate", headers=headers(profile, csrf),
                          json={"expected_revision": 1})
    assert rotated.status_code == 200
    new_secret = rotated.json()["secret"]
    client.cookies.clear()
    assert client.get(profile.base_path + "api/v1/snapshot", headers=bearer(secret)).status_code == 401
    assert client.get(profile.base_path + "api/v1/snapshot", headers=bearer(new_secret)).status_code == 200


def test_issued_credential_survives_a_cold_restart(tmp_path):
    profile, capability, arguments = configured(tmp_path, "https")
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap(client, profile, capability)
        _, secret = create_client(client, profile, csrf, ["snapshot.read"])
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        assert client.get(profile.base_path + "api/v1/snapshot", headers=bearer(secret)).status_code == 200


def test_rate_buckets_bound_bearer_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(service_client_api, "RATE_CAPACITY", 2)
    monkeypatch.setattr(service_client_api, "RATE_REFILL_INTERVAL_MS", 3_600_000)
    profile, capability, arguments = configured(tmp_path, "https")
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap(client, profile, capability)
        _, secret = create_client(client, profile, csrf, ["snapshot.read"])
        client.cookies.clear()
        statuses = [client.get(profile.base_path + "api/v1/snapshot", headers=bearer(secret)).status_code
                    for _ in range(3)]
        assert statuses == [200, 200, 429]


def test_a_revoke_committed_during_a_read_withholds_it(portable):
    app, client, profile, csrf, _ = portable
    record, secret = create_client(client, profile, csrf, ["snapshot.read"])
    registry = app.state.first_party_exports["service-clients.registry"]
    read = ServiceClientRead("GET", record["client_id"], 1, "snapshot.read", "snapshot.read",
                             lambda: registry.verify_current(record["client_id"], credential_revision=1,
                                                             scope="snapshot.read",
                                                             network_profile="portable_https"))
    assert read.verify().kind == "service_client"
    assert "secret" not in repr(read) and secret not in repr(read)
    wrong_scope = ServiceClientRead("GET", record["client_id"], 1, "events.read", "events.read",
                                    lambda: registry.verify_current(record["client_id"], credential_revision=1,
                                                                    scope="events.read",
                                                                    network_profile="portable_https"))
    with pytest.raises(RequestDenied):
        wrong_scope.verify()
    assert client.post(profile.base_path + "api/v1/service-clients/" + record["client_id"] + "/revoke",
                       headers=headers(profile, csrf), json={"expected_revision": 1}).status_code == 200
    with pytest.raises(RequestDenied):
        read.verify()
    with pytest.raises(RequestDenied):
        app.state.api_v1.root_commands.read_events(request=read)


def test_loopback_profile_never_parses_or_issues_a_bearer(tmp_path):
    profile, capability, arguments = configured(tmp_path, "local")
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap(client, profile, capability)
        base = profile.base_path + "api/v1/"
        created = client.post(base + "service-clients", headers=headers(profile, csrf),
                              json=creation(["snapshot.read"]))
        assert created.status_code == 422
        assert client.get(base + "service-clients", headers=headers(profile)).json()["items"] == []
        # a fixed non-secret canary: the uniform pre-auth denial, even beside a live cookie
        assert client.get(base + "snapshot", headers=headers(profile)).status_code == 200
        assert client.get(base + "snapshot", headers={**headers(profile), **bearer(CANARY)}).status_code == 401
        client.cookies.clear()
        response = client.get(base + "snapshot", headers=bearer(CANARY))
        assert response.status_code == 401 and response.json()["code"] == "unauthenticated"


def test_plain_http_to_the_portable_profile_is_refused_before_auth(tmp_path):
    profile, _, arguments = configured(tmp_path, "https")
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin.replace("https://", "http://")) as client:
        response = client.get("/api/v1/snapshot", headers=bearer(CANARY))
        assert response.status_code == 403
        assert response.json()["code"] == "access_denied"


def test_the_settings_panel_offers_exactly_the_grantable_scopes_and_expiries(portable):
    # UI phase 6 (설정 > 서비스 클라이언트, app/static/service-clients.mjs): the panel offers only the
    # scopes a composed route declares for a bearer, under the server's own expiry limit, bound to
    # the portable profile; it is a catalogued public asset. A new bearer scope without a label in
    # the panel (or a label for a scope no route grants) makes this fail instead of drifting.
    import re
    from pathlib import Path

    from app.api.assets import MODULES
    from app.services.service_clients import MAX_SERVICE_CLIENT_TTL_SECONDS

    app, *_ = portable
    source = (Path(__file__).resolve().parents[1] / "static" / "service-clients.mjs").read_text(encoding="utf-8")
    assert MODULES["service-clients.mjs"] == "application/javascript"
    block = re.search(r"export const GRANTABLE_SCOPES = Object\.freeze\(\{(.*?)\}\);", source, re.DOTALL)
    assert block is not None
    offered = set(re.findall(r"'([a-z_.]+)':", block.group(1)))
    assert offered == set(app.state.route_composition.bearer_scopes())
    hours = [int(value) for value in re.findall(r"hours: (\d+)", source)]
    assert hours and max(hours) * 3600 < MAX_SERVICE_CLIENT_TTL_SECONDS
    assert re.search(r"MAX_SERVER_TTL_SECONDS = 86_400;", source) and MAX_SERVICE_CLIENT_TTL_SECONDS == 86_400
    assert f"NETWORK_PROFILE = '{service_client_api.BEARER_NETWORK_PROFILE}'" in source
    # the code (comments aside) writes no markup and touches no browser storage
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "localStorage", "sessionStorage", "document.write"):
        assert sink not in code, sink
