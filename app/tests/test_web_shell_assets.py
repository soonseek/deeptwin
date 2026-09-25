"""The supported factory serves the browser modules (T048 DOM-half prerequisite;
api.md: the static shell is public, everything else session-protected).

The run GUI logic (`runtime.mjs`, `approvals.mjs`) and the intake shell's
modules are reachable from the supported deployment authority as flat,
content-typed, public GET/HEAD assets behind the web boundary's headers and
path hygiene; `/` is the first screen (T025: the first-owner setup or the login
form, decided by the public setup state on `/health`). The
shell's request helper speaks the supported CSRF header name
(`X-DeepTwin-CSRF`), which the boundary alone admits.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import assets
from app.api.assets import MODULES
from app.server import create_app
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_the_catalogue_is_exactly_the_shell_modules():
    assert dict(MODULES) == {
        "app.mjs": "application/javascript",
        "styles.css": "text/css",
        "chat.mjs": "application/javascript",
        "settings.mjs": "application/javascript",
        "browser-grants.mjs": "application/javascript",
        "speech-input.mjs": "application/javascript",
        "audio-capture-worklet.mjs": "application/javascript",
        "approvals.mjs": "application/javascript",
        "approval-screen.mjs": "application/javascript",
        "records.mjs": "application/javascript",
        "runtime.mjs": "application/javascript",
        "session.mjs": "application/javascript",
        "run-panel.mjs": "application/javascript",
        "run-list.mjs": "application/javascript",
        "artifacts.mjs": "application/javascript",
        "alternatives.mjs": "application/javascript",
        "alternative-file.mjs": "application/javascript",
        "inquiry.mjs": "application/javascript",
        "work-export.mjs": "application/javascript",
        "source-deletion.mjs": "application/javascript",
        "records-page.mjs": "application/javascript",
        "records-backup.mjs": "application/javascript",
        "records-retention.mjs": "application/javascript",
        "records-update.mjs": "application/javascript",
        "account.mjs": "application/javascript",
        "claude-connection.mjs": "application/javascript",
        "work-model.mjs": "application/javascript",
        "graph.mjs": "application/javascript",
        "workspace.mjs": "application/javascript",
        "records.html": "text/html",
        "settings.html": "text/html",
        "versions.mjs": "application/javascript",
        "experiments.mjs": "application/javascript",
        "versions-page.mjs": "application/javascript",
        "versions.html": "text/html",
        "observe.mjs": "application/javascript",
        "observe.html": "text/html",
        "start.mjs": "application/javascript",
        "start.html": "text/html",
        "work.mjs": "application/javascript",
        "work.html": "text/html",
    }
    assert "index.html" not in MODULES


@pytest.fixture
def served(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        yield app, client, profile, capability


def test_the_browser_modules_are_served_publicly_with_exact_types(served):
    _app, client, profile, _capability = served
    for name, media_type in MODULES.items():
        response = client.get(profile.base_path + name, headers=headers(profile))
        assert response.status_code == 200, (name, response.status_code, response.text[:80])
        assert response.headers["content-type"].split(";", 1)[0] == media_type, name
        assert response.content == (STATIC / name).read_bytes()
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        head = client.head(profile.base_path + name, headers=headers(profile))
        assert head.status_code == 200 and head.content == b""
        assert head.headers["content-type"] == response.headers["content-type"]
    # the shell itself is the first screen (T025): the setup/login page, not the intake page
    shell = client.get(profile.base_path, headers=headers(profile))
    assert shell.status_code == 200 and "work-stage" not in shell.text
    assert shell.content == (STATIC / "start.html").read_bytes()
    assert shell.headers["content-type"].split(";", 1)[0] == "text/html"


def test_unknown_or_hostile_asset_paths_are_never_served(served):
    _app, client, profile, _capability = served
    # not an asset: the boundary treats it as a protected path (no session → 401)
    missing = client.get(profile.base_path + "nope.mjs", headers=headers(profile))
    assert missing.status_code == 401
    for hostile in ("..%2fapp.mjs", "app.mjs%00", "app.mjs%2e%2e"):
        response = client.get(profile.base_path + hostile, headers=headers(profile))
        assert response.status_code == 403, hostile
    doubled = client.get(profile.base_path + "/app.mjs", headers=headers(profile))
    assert doubled.status_code == 403
    # assets are read-only
    posted = client.post(profile.base_path + "app.mjs", headers=headers(profile, "x"), json={})
    assert posted.status_code in {401, 403, 405}
    # no query rides on an asset path: the catalogue cannot be re-aimed at another file
    # (the preview's intake shell must never leak through the supported factory)
    aimed = client.get(profile.base_path + "app.mjs?name=index.html", headers=headers(profile))
    assert aimed.status_code == 400, aimed.text
    assert "work-stage" not in aimed.text and aimed.json()["code"] == "invalid_input"
    assert client.get(profile.base_path + "app.mjs?x=1", headers=headers(profile)).status_code == 400
    # a byte range is ignored: the whole catalogued file, never a text/plain range error
    ranged = client.get(profile.base_path + "app.mjs",
                        headers={**headers(profile), "Range": "bytes=zz"})
    assert ranged.status_code == 200 and ranged.content == (STATIC / "app.mjs").read_bytes()
    assert "last-modified" not in ranged.headers and "etag" not in ranged.headers


def test_a_missing_catalogued_file_is_a_closed_unavailable_envelope(served, monkeypatch, tmp_path):
    _app, client, profile, _capability = served
    monkeypatch.setattr(assets, "STATIC", tmp_path / "empty")
    response = client.get(profile.base_path + "runtime.mjs", headers=headers(profile))
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "unavailable" and set(body) >= {"code", "message", "retryability"}
    assert "detail" not in body


def test_the_shell_speaks_the_supported_csrf_header(served):
    _app, client, profile, capability = served
    csrf = bootstrap_client(client, profile, capability)
    command = {"command_id": str(uuid4())}
    # the historical header name is not admitted by the supported boundary
    legacy = client.post(profile.base_path + "session/logout", json=command,
                         headers={**headers(profile), "X-CSRF-Token": csrf})
    assert legacy.status_code in {401, 403}, legacy.text
    assert client.get(profile.base_path + "session", headers=headers(profile)).status_code == 200
    accepted = client.post(profile.base_path + "session/logout", json=command,
                           headers=headers(profile, csrf))
    assert accepted.status_code == 200, accepted.text
    # the shell's request helper sends exactly the supported name
    source = (STATIC / "app.mjs").read_text(encoding="utf-8")
    assert "X-DeepTwin-CSRF" in source
    assert "X-CSRF-Token" not in source


def test_the_observation_page_is_served_publicly_and_references_only_catalogued_relative_assets(served):
    # T048/T025 shell mount: the page is a public static asset under the deployment base
    # path; every script/stylesheet it references is a relative, catalogued module, so it
    # resolves under `/<hex>/` as under `/`, and the CSP admits it (script-src 'self')
    import re

    _app, client, profile, _capability = served
    page = client.get(profile.base_path + "observe.html", headers=headers(profile))
    assert page.status_code == 200, page.text
    assert page.headers["content-type"].split(";", 1)[0] == "text/html"
    assert "script-src 'self'" in page.headers["content-security-policy"]
    source = (STATIC / "observe.html").read_text(encoding="utf-8")
    references = re.findall(r'(?:src|href)="([^"]+)"', source)
    assert references, source
    for reference in references:
        assert reference.startswith("./"), reference
        assert reference[2:] in MODULES, reference
    assert "<script" in source and 'type="module"' in source
    for mount in ("session-status", "run-source", "run-panel"):
        assert f'id="{mount}"' in source, mount
    # the page is not the setup/login stub and carries no form that could take a secret
    assert "<form" not in source and "password" not in source.lower()
    # the page's own head: unauthenticated readers get the page, the API stays protected
    assert client.get(profile.base_path + "api/v1/snapshot", headers=headers(profile)).status_code == 401
    # a navigation's own request shape (no Origin, Sec-Fetch-Site none, a document) is admitted
    navigated = client.get(profile.base_path + "observe.html", headers={
        "host": profile.http_origin.split("://", 1)[1], "sec-fetch-site": "none", "sec-fetch-dest": "document",
    })
    assert navigated.status_code == 200, navigated.text
    assert "data-ready" not in source  # nothing copied from the preview shell that never flips


def test_every_pages_module_graph_is_catalogued_transitively():
    # review closure: a dependency importing an uncatalogued module passes `node --test`
    # (the file is on disk) while the factory answers 401 for it and the whole graph fails
    # to load in the browser — so the import graph is walked from the page's module
    import re

    pending = ["observe.mjs", "work.mjs", "start.mjs"]
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        assert name in MODULES, name
        source = (STATIC / name).read_text(encoding="utf-8")
        pending.extend(re.findall(r"from '\./([^']+)'", source))
    assert {"run-list.mjs", "run-panel.mjs", "runtime.mjs", "session.mjs"} <= seen


@pytest.mark.parametrize("mode", ["local", "https"])
def test_the_work_screen_is_served_publicly_and_the_pages_exact_exchanges_save_a_revision(tmp_path, mode):
    # T023/T025 §5.1 items 4–6: the first work screen after login; its exact request shapes
    # (the schema names read from the module itself) against the real factory on both origin
    # profiles — create, read, revise, a stale revision refused
    import re

    profile, capability, arguments = configured(tmp_path, mode)
    app = create_app(tmp_path / "data", **arguments)
    source = (STATIC / "work.html").read_text(encoding="utf-8")
    for reference in re.findall(r'(?:src|href)="([^"]+)"', source):
        assert reference.startswith("./") and reference[2:] in MODULES, reference
    for mount in ("session-status", "intake-notice", "work-form", "save-status", "materials", "observe-link"):
        assert f'id="{mount}"' in source, mount
    assert 'method="post"' in source and "password" not in source.lower()
    module = (STATIC / "work.mjs").read_text(encoding="utf-8")
    for code in ("invalid_input", "unauthenticated", "access_denied", "not_found", "conflict", "too_large", "unavailable"):
        assert f"{code}:" in module, code
    create_schema = re.search(r"const CREATE_SCHEMA = '([^']+)'", module).group(1)
    revise_schema = re.search(r"const REVISE_SCHEMA = '([^']+)'", module).group(1)
    # the start screen lands on the work screen, and the observation page links back to it
    assert "work.html" in (STATIC / "start.mjs").read_text(encoding="utf-8")
    assert "./work.html" in (STATIC / "observe.html").read_text(encoding="utf-8")
    with TestClient(app, base_url=profile.http_origin) as client:
        page = client.get(profile.base_path + "work.html", headers=headers(profile))
        assert page.status_code == 200 and page.headers["content-type"].split(";", 1)[0] == "text/html"
        _exchanges(client, profile, capability, create_schema, revise_schema)


def _exchanges(client, profile, capability, create_schema, revise_schema):
    csrf = bootstrap_client(client, profile, capability)
    command = "11111111-1111-4111-8111-111111111111"
    created = client.post(profile.base_path + "api/v1/works", headers=headers(profile, csrf), json={
        "schema_version": create_schema, "command_id": command, "text": "보고서 요약"})
    assert created.status_code == 201, created.text
    work = created.json()
    assert client.get(profile.base_path + "api/v1/works/" + work["work_id"], headers=headers(profile)).json() == work
    revised = client.post(profile.base_path + "api/v1/works/" + work["work_id"] + "/revisions", headers=headers(profile, csrf), json={
        "schema_version": revise_schema, "command_id": "22222222-2222-4222-8222-222222222222",
        "expected_revision": 1, "text": "세 문단으로"})
    assert revised.status_code == 201 and revised.json()["revision"] == 2
    stale = client.post(profile.base_path + "api/v1/works/" + work["work_id"] + "/revisions", headers=headers(profile, csrf), json={
        "schema_version": revise_schema, "command_id": "33333333-3333-4333-8333-333333333333",
        "expected_revision": 1, "text": "늦은 편집"})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"



def test_the_first_screen_serves_the_setup_or_login_page_and_health_tells_which(served):
    # T025 / experience.md §5.1.3: the instance's first screen; the page decides the form from
    # the public setup state on /health — an owner present or not, the bootstrap claim's state
    _app, client, profile, capability = served
    import re

    source = (STATIC / "start.html").read_text(encoding="utf-8")
    for reference in re.findall(r'(?:src|href)="([^"]+)"', source):
        assert reference.startswith("./") and reference[2:] in MODULES, reference
    for mount in ("start-status", "setup-form", "login-form"):
        assert f'id="{mount}"' in source, mount
    assert 'autocomplete="off"' in source  # the setup form never offers to remember a capability
    module = (STATIC / "start.mjs").read_text(encoding="utf-8")
    assert "type: 'password'" in module and "'new-password'" in module and "'current-password'" in module
    health = client.get(profile.base_path + "health", headers=headers(profile))
    assert health.status_code == 200, health.text
    assert health.json() == {"state": "available", "owner": False, "setup": "available"}
    assert client.get(profile.base_path + "health").status_code == 200  # a navigation's own shape
    bootstrap_client(client, profile, capability)
    health = client.get(profile.base_path + "health", headers=headers(profile))
    assert health.json() == {"state": "available", "owner": True, "setup": "completed"}
    # the page module's error text covers every code the establishment routes can answer
    for code in ("credentials", "capacity", "setup_incomplete", "setup_unavailable", "invalid_input",
                 "unavailable", "access_denied", "unauthenticated"):
        assert f"{code}:" in module, code


def test_the_health_setup_state_follows_the_claim(tmp_path):
    profile, _capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        from base64 import urlsafe_b64encode

        wrong = urlsafe_b64encode(b"W" * 32).rstrip(b"=").decode()  # canonical, but not the capability
        for _ in range(5):
            refused = client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
                "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": wrong})
            assert refused.status_code == 401, refused.text
        health = client.get(profile.base_path + "health", headers=headers(profile)).json()
        assert health == {"state": "available", "owner": False, "setup": "exhausted"}


def test_the_health_setup_state_reports_an_expired_window_without_an_attempt(tmp_path, monkeypatch):
    # review closure: `expired` was written only lazily inside a bootstrap attempt, so the
    # first screen offered the setup form after the deadline and the owner learned of the
    # expiry from a 409 — the health read reports the deadline itself
    import time

    from app.services import owner_auth

    profile, _capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        assert client.get(profile.base_path + "health", headers=headers(profile)).json()["setup"] == "available"
        real = time.time_ns
        monkeypatch.setattr(owner_auth.time, "time_ns", lambda: real() + 11 * 60 * 1_000_000_000)
        assert client.get(profile.base_path + "health", headers=headers(profile)).json()["setup"] == "expired"


def test_a_storage_fault_on_health_is_the_closed_envelope_with_the_security_headers(tmp_path, monkeypatch):
    # review MUST: the setup read was the one public authority entry without the closed
    # error boundary — a storage fault escaped as a bare 500 without CSP or no-store
    from app.services import owner_auth

    profile, _capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin, raise_server_exceptions=False) as client:
        assert client.get(profile.base_path + "health", headers=headers(profile)).status_code == 200

        def broken(*_args, **_kwargs):
            raise owner_auth.storage.AuthStorageError("PRIVATE")

        monkeypatch.setattr(owner_auth.storage, "verify", broken)
        response = client.get(profile.base_path + "health", headers=headers(profile))
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["code"] == "unavailable" and "PRIVATE" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]


@pytest.mark.parametrize("mode", ["local", "https"])
def test_the_first_screens_flow_end_to_end_on_the_real_factory(tmp_path, mode):
    # the page's exact exchanges against the real factory: the page, the health state, a
    # bootstrap with the page's body shape, the cookie, the observation page, the session,
    # then a fresh browser logging in
    from app.tests.test_web_owner_integration import configured as configure

    profile, capability, arguments = configure(tmp_path, mode)
    app = create_app(tmp_path / "data", **arguments)
    base = profile.base_path
    host = profile.http_origin.split("://", 1)[1]
    navigation = {"host": host, "sec-fetch-site": "none", "sec-fetch-dest": "document"}
    with TestClient(app, base_url=profile.http_origin) as client:
        page = client.get(base, headers=navigation)
        assert page.status_code == 200 and page.content == (STATIC / "start.html").read_bytes()
        assert client.head(base, headers=navigation).status_code == 200
        assert client.get(base + "session", headers=headers(profile)).status_code == 401
        assert client.get(base + "health", headers=headers(profile)).json() == {
            "state": "available", "owner": False, "setup": "available"}
        created = client.post(base + "session/bootstrap", headers=headers(profile), json={
            "login_name": "owner", "password": "a passphrase of fifteen characters",
            "raw_capability_b64u": capability})
        assert created.status_code == 201 and created.json()["state"] == "authenticated", created.text
        assert client.get(base + "health", headers=headers(profile)).json() == {
            "state": "available", "owner": True, "setup": "completed"}
        assert client.get(base + "observe.html", headers=navigation).status_code == 200
        assert client.get(base + "session", headers=headers(profile)).status_code == 200
        client.cookies.clear()
        assert client.get(base + "session", headers=headers(profile)).status_code == 401
        logged = client.post(base + "session/login", headers=headers(profile), json={
            "login_name": "owner", "password": "a passphrase of fifteen characters"})
        assert logged.status_code == 200 and logged.json()["state"] == "authenticated", logged.text
        assert client.get(base + "session", headers=headers(profile)).status_code == 200
    # the forms never submit natively: method post, so a blocked script cannot put a secret in a URL
    source = (STATIC / "start.html").read_text(encoding="utf-8")
    assert source.count('method="post"') == 2
