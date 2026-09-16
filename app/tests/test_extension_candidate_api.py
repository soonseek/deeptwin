"""Real supported owner-cookie admission of inert candidate metadata."""

import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from app.tests.extension_candidate_fixture import candidate_payload
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers


@pytest.mark.parametrize("mode", ["local", "https"])
def test_real_owner_cookie_register_read_replay_cold_reopen(tmp_path, mode):
    profile, capability, arguments = configured(tmp_path, mode)
    application = create_app(tmp_path / "data", **arguments)
    payload = candidate_payload()
    path = profile.base_path + "api/v1/extensions/candidates"
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        response = client.post(path, headers=headers(profile, csrf), json=payload)
        assert response.status_code == 201, response.text
        receipt = response.json()
        from jsonschema import Draft202012Validator

        from app.extensions.candidate_schema_exports import api_schema

        assert Draft202012Validator(api_schema()).is_valid(receipt)
        assert receipt["state"] == "registered_unqualified"
        assert receipt["links"]["self"].startswith(path + "/")
        read = client.get(receipt["links"]["self"], headers=headers(profile))
        assert read.status_code == 200, read.text
        saved = read.json()
        assert Draft202012Validator(api_schema()).is_valid(saved)
        assert saved["manifest"] == payload["manifest"]
        assert saved["service_descriptor"] == payload["service_descriptor"]
        assert (
            client.head(receipt["links"]["self"], headers=headers(profile)).content
            == b""
        )
        assert (
            client.post(path, headers=headers(profile, csrf), json=payload).json()
            == receipt
        )
        changed = candidate_payload()
        changed["command_id"] = payload["command_id"]
        changed["manifest"]["source"]["locator"] += "/changed"
        assert (
            client.post(path, headers=headers(profile, csrf), json=changed).status_code
            == 409
        )
        events = client.get(
            receipt["links"]["events"], headers=headers(profile)
        ).json()["events"]
        assert (
            sum(e["event_type"] == "extension.candidate_registered" for e in events)
            == 1
        )
        cookies = dict(client.cookies)
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        client.cookies.update(cookies)
        assert (
            client.get(receipt["links"]["self"], headers=headers(profile)).json()
            == saved
        )
        assert (
            client.post(path, headers=headers(profile, csrf), json=payload).json()
            == receipt
        )


@pytest.mark.parametrize(
    "raw,suffix,method,media,status",
    [
        (b'{"command_id":1,"command_id":2}', "", "POST", "application/json", 400),
        (b"{}", "?unknown=1", "POST", "application/json", 400),
        (b"{}", "", "POST", "text/plain", 400),
        (b"{}", "", "GET", "application/json", 400),
        (b"{}", "/not-a-uuid", "GET", "application/json", 400),
        (b'{"command_id":NaN}', "", "POST", "application/json", 400),
        (b'{"command_id":"\\ud800"}', "", "POST", "application/json", 400),
        (b"\xef\xbb\xbf{}", "", "POST", "application/json", 400),
        (b"{}{}", "", "POST", "application/json", 400),
        (b"x" * 1048577, "", "POST", "application/json", 413),
    ],
)
def test_invalid_wire_precedes_all_authentication_and_registry_work(
    tmp_path, monkeypatch, raw, suffix, method, media, status
):
    profile, _, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid candidate input reached auth or registry")

    monkeypatch.setattr(app.state.owner_authority, "authenticate_request", forbidden)
    monkeypatch.setattr(
        app.state.first_party_exports["extension-candidates.registry"],
        "register",
        forbidden,
    )
    with TestClient(app, base_url=profile.http_origin) as client:
        response = client.request(
            method,
            profile.base_path + "api/v1/extensions/candidates" + suffix,
            content=raw,
            headers={**headers(profile), "Content-Type": media},
        )
        assert response.status_code == status, response.text
        assert set(response.json()) == {
            "code",
            "message",
            "retryability",
            "affected_refs",
            "correlation_id",
        }
        assert response.headers["cache-control"] == "no-store"


def test_schema_invalid_complete_body_and_streamed_overflow_are_early(
    tmp_path, monkeypatch
):
    profile, _, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid candidate input reached auth")

    monkeypatch.setattr(app.state.owner_authority, "authenticate_request", forbidden)
    with TestClient(app, base_url=profile.http_origin) as client:
        path = profile.base_path + "api/v1/extensions/candidates"
        value = candidate_payload()
        value["manifest"]["qualified"] = True
        assert (
            client.post(path, json=value, headers=headers(profile)).status_code == 400
        )
        chunks = (b"x" * 65536 for _ in range(17))
        assert (
            client.post(
                path,
                content=chunks,
                headers={**headers(profile), "Content-Type": "application/json"},
            ).status_code
            == 413
        )
        read_path = path + "/11111111-1111-4111-8111-111111111111"
        assert (
            client.request(
                "GET",
                read_path,
                content=iter([b"hidden-body"]),
                headers=headers(profile),
            ).status_code
            == 400
        )


def test_no_owner_csrf_origin_unknown_and_other_body_caps(tmp_path):
    from uuid import uuid4

    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        path = profile.base_path + "api/v1/extensions/candidates"
        value = candidate_payload()
        assert client.post(
            path, json=value, headers=headers(profile, "invalid")
        ).status_code in (401, 403)
        csrf = bootstrap_client(client, profile, capability)
        assert (
            client.post(path, json=value, headers=headers(profile)).status_code == 403
        )
        assert (
            client.post(
                path,
                json=value,
                headers={**headers(profile, csrf), "Origin": "https://wrong.test"},
            ).status_code
            == 403
        )
        assert (
            client.get(path + "/" + str(uuid4()), headers=headers(profile)).status_code
            == 404
        )
        assert (
            client.head(path + "/" + str(uuid4()), headers=headers(profile)).content
            == b""
        )
        assert (
            client.post(
                profile.base_path + "api/v1/commands",
                content=b"x" * 131073,
                headers=headers(profile, csrf),
            ).status_code
            == 413
        )


def test_candidate_operations_create_no_execution_authority_or_external_effects(
    tmp_path, monkeypatch
):
    import subprocess
    import urllib.request
    from dataclasses import replace

    from app.domain.permissions import HostPolicy
    from app.extensions import contracts
    from app.tests.test_web_owner_integration import bound_request
    from app.workers import broker

    profile, capability, arguments = configured(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("inert metadata invoked an execution boundary")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(broker.ChannelSpec, "__post_init__", forbidden)
    monkeypatch.setattr(contracts, "new_installation", forbidden)
    monkeypatch.setattr(contracts, "new_binding", forbidden)
    monkeypatch.setattr(contracts, "new_qualification", forbidden)
    monkeypatch.setattr(HostPolicy, "grant", forbidden)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        request = bound_request(app, client, profile, csrf)
        value = candidate_payload()
        import socket

        from app.extensions.persistence import PersistentCandidateRegistry

        with monkeypatch.context() as effects:
            effects.setattr(socket, "socket", forbidden)
            effects.setattr(socket, "create_connection", forbidden)
            effects.setattr(socket, "socketpair", forbidden)
            registry = PersistentCandidateRegistry(
                app.state.domain_store, app.state.owner_authority
            )
            receipt = registry.register(request, value)
            registry.read(
                replace(request, method="GET"), receipt["candidate_ref"]["candidate_id"]
            )
            assert registry.register(request, value) == receipt
        with app.state.domain_store._connection() as db:
            kinds = {
                r[0] for r in db.execute("SELECT DISTINCT kind FROM domain_records")
            }
            assert not kinds & {
                "extension_installation",
                "extension_binding",
                "extension_qualification",
                "runtime_profile",
                "grant",
            }
            assert (
                db.execute("SELECT dispatch_enabled FROM domain_vault").fetchone()[0]
                == 0
            )
        assert app.state.worker_dispatch is None
        assert (
            client.post(
                profile.base_path + "api/v1/extensions/stage",
                headers=headers(profile, csrf),
                json={},
            ).status_code
            == 404
        )
