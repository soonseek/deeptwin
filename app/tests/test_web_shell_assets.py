"""The supported factory serves the browser modules (T048 DOM-half prerequisite;
api.md: the static shell is public, everything else session-protected).

The run GUI logic (`runtime.mjs`, `approvals.mjs`) and the intake shell's
modules are reachable from the supported deployment authority as flat,
content-typed, public GET/HEAD assets behind the web boundary's headers and
path hygiene; `/` stays the honest setup/login stub (UX-AC01 open, T025). The
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
        "speech-input.mjs": "application/javascript",
        "audio-capture-worklet.mjs": "application/javascript",
        "approvals.mjs": "application/javascript",
        "records.mjs": "application/javascript",
        "runtime.mjs": "application/javascript",
        "session.mjs": "application/javascript",
        "run-panel.mjs": "application/javascript",
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
    # the shell itself is still the honest setup/login stub, not the intake page
    shell = client.get(profile.base_path, headers=headers(profile))
    assert shell.status_code == 200 and "pending" in shell.text
    assert "work-stage" not in shell.text


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
