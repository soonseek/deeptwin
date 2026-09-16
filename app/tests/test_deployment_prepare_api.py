"""Actual browser owner → candidate → durable prepare/read/cancel HTTP chain."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.refs import canonical_json
from app.server import create_app
from app.tests.deployment_prepare_fixture import http_sources
from app.tests.test_deployment_prepare_contracts import matching_bundle
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers


def prepare_payload(candidate_id):
    return {
        "command_id": str(uuid4()),
        "kind": "extension_stage",
        "candidate_id": candidate_id,
        "slot_id": 1,
        "expires_in_seconds": 60,
    }


def test_unexpected_actual_service_failure_is_generic500_without_diagnostics(
    tmp_path, monkeypatch
):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    assert app.debug is False
    with TestClient(
        app, base_url=profile.http_origin, raise_server_exceptions=False
    ) as client:
        bootstrap_client(client, profile, capability)
        service = app.state.first_party_exports["deployment-prepare.service"]

        def broken_journal(*args, **kwargs):
            raise RuntimeError("private source path and internal diagnostic")

        monkeypatch.setattr(service, "_journal", broken_journal)
        response = client.get(
            profile.base_path + "api/v1/deployment/requests/" + str(uuid4()),
            headers=headers(profile),
        )
        assert response.status_code == 500
        assert response.content == b"Internal Server Error"


@pytest.mark.parametrize("mode", ["local", "https"])
def test_actual_http_receipts_head_replay_cancel_and_restart(
    tmp_path, monkeypatch, mode
):
    from app.extensions.persistence import PersistentCandidateRegistry

    registries = []
    original_init = PersistentCandidateRegistry.__init__

    def counted_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        registries.append(self)

    monkeypatch.setattr(PersistentCandidateRegistry, "__init__", counted_init)
    profile, capability, arguments = configured(tmp_path, mode)
    actual, values = http_sources(tmp_path, monkeypatch, profile)
    arguments["first_party_startup_values"] = values
    app = create_app(tmp_path / "data", **arguments)
    path = profile.base_path + "api/v1/deployment/requests"
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        registration = client.post(
            profile.base_path + "api/v1/extensions/candidates",
            json=matching_bundle()[0].as_dict(),
            headers=headers(profile, csrf),
        )
        assert registration.status_code == 201, registration.text
        with app.state.domain_store._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_requests"
                ).fetchone()[0]
                == 0
            )
        payload = prepare_payload(registration.json()["candidate_ref"]["candidate_id"])
        response = client.post(path, json=payload, headers=headers(profile, csrf))
        assert response.status_code == 201, response.text
        receipt = response.json()
        assert receipt["state"] == "prepared" and receipt["revision"] == 1
        assert (
            receipt["publication_state"] == "pending"
            and receipt["cancellation_publication_state"] is None
        )
        assert response.content == canonical_json(receipt)
        with app.state.domain_store._connection() as db:
            import json

            stored = json.loads(
                db.execute(
                    "SELECT receipt_json FROM deployment_prepare_commands WHERE command_id=?",
                    (payload["command_id"],),
                ).fetchone()[0]
            )
        assert (
            stored["links"]["self"]
            == "/api/v1/deployment/requests/" + receipt["request_id"]
        )
        assert receipt["links"]["self"] == path + "/" + receipt["request_id"]
        read = client.get(receipt["links"]["self"], headers=headers(profile))
        head = client.head(receipt["links"]["self"], headers=headers(profile))
        assert read.status_code == head.status_code == 200
        assert not head.content
        for name in (
            "content-type",
            "content-length",
            "cache-control",
            "content-security-policy",
        ):
            assert head.headers[name] == read.headers[name]
        assert read.content == canonical_json(read.json())
        service = app.state.first_party_exports["deployment-prepare.service"]
        assert registries == [service._registry]
        assert (
            service._registry
            is app.state.first_party_exports["extension-candidates.registry"]
        )
        assert (
            service._domain is app.state.domain_store
            and service._owner is app.state.owner_authority
        )
        assert service._topology is not None and service._exchange is not None
        # Physical topology loss must not disable the independent cancellation channel.
        actual.actual(actual.c.TOPOLOGY_ROOT).rename(
            actual.actual(actual.c.TOPOLOGY_ROOT).with_name("lost-topology")
        )
        cancel_payload = {
            "command_id": str(uuid4()),
            "request_digest": receipt["request_digest"],
            "expected_revision": 1,
        }
        cancelled = client.post(
            receipt["links"]["cancel"],
            json=cancel_payload,
            headers=headers(profile, csrf),
        )
        assert cancelled.status_code == 200, cancelled.text
        assert (
            cancelled.json()["state"] == "cancelled"
            and cancelled.json()["revision"] == 2
        )
        assert cancelled.json()["cancellation_publication_state"] == "pending"
        assert (
            client.post(path, json=payload, headers=headers(profile, csrf)).content
            == response.content
        )
        assert (
            client.post(
                receipt["links"]["cancel"],
                json=cancel_payload,
                headers=headers(profile, csrf),
            ).content
            == cancelled.content
        )
    assert service._topology._closed and service._exchange._closed
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        login = client.post(
            profile.base_path + "session/login",
            headers=headers(profile),
            json={"login_name": "owner", "password": "synthetic owner passphrase"},
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        assert (
            reopened.state.first_party_exports["deployment-prepare.service"]._topology
            is None
        )
        assert (
            reopened.state.first_party_exports["deployment-prepare.service"]._exchange
            is not None
        )
        assert (
            client.get(receipt["links"]["self"], headers=headers(profile)).json()[
                "state"
            ]
            == "cancelled"
        )
        assert (
            client.post(path, json=payload, headers=headers(profile, csrf)).content
            == response.content
        )
        assert (
            client.post(
                receipt["links"]["cancel"],
                json=cancel_payload,
                headers=headers(profile, csrf),
            ).content
            == cancelled.content
        )
        assert (
            len(registries) == 2
            and registries[1]
            is reopened.state.first_party_exports["extension-candidates.registry"]
        )


@pytest.mark.parametrize(
    "raw,suffix,method,media,status",
    [
        (b'{"command_id":1,"command_id":2}', "", "POST", "application/json", 400),
        (b"{}", "?x=1", "POST", "application/json", 400),
        (b"{}", "", "POST", "text/plain", 400),
        (b"", "", "GET", "application/json", 400),
        (b"", "/invalid", "GET", "application/json", 400),
        (b"", "/00000000-0000-0000-0000-000000000000", "HEAD", "application/json", 400),
        (b"{}", "", "PUT", "application/json", 400),
        (b"x" * 4097, "", "POST", "application/json", 413),
        (
            b"{}",
            "/11111111-1111-4111-8111-111111111111",
            "GET",
            "application/json",
            400,
        ),
        (
            b"{}",
            "/11111111-1111-4111-8111-111111111111/cancel/more",
            "POST",
            "application/json",
            400,
        ),
    ],
)
def test_deployment_preflight_is_bounded_before_auth(
    tmp_path, monkeypatch, raw, suffix, method, media, status
):
    profile, _, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid deployment wire reached authentication")

    monkeypatch.setattr(app.state.owner_authority, "authenticate_request", forbidden)
    with TestClient(app, base_url=profile.http_origin) as client:
        response = client.request(
            method,
            profile.base_path + "api/v1/deployment/requests" + suffix,
            content=raw,
            headers={**headers(profile), "Content-Type": media},
        )
        assert response.status_code == status
        if method != "HEAD":
            assert set(response.json()) == {
                "code",
                "message",
                "retryability",
                "affected_refs",
                "correlation_id",
            }
        assert response.headers["cache-control"] == "no-store"


def test_absent_sources_keep_owner_candidate_and_closed_deployment_errors(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", first_party_startup_values={}, **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        path = profile.base_path + "api/v1/deployment/requests"
        payload = prepare_payload(str(uuid4()))
        assert (
            client.post(
                path,
                json=payload,
                headers={**headers(profile), "Authorization": "Bearer service-client"},
            ).status_code
            == 401
        )
        csrf = bootstrap_client(client, profile, capability)
        registration = client.post(
            profile.base_path + "api/v1/extensions/candidates",
            json=matching_bundle()[0].as_dict(),
            headers=headers(profile, csrf),
        )
        assert registration.status_code == 201
        payload["candidate_id"] = registration.json()["candidate_ref"]["candidate_id"]
        assert (
            client.post(path, json=payload, headers=headers(profile)).status_code == 403
        )
        assert (
            client.post(
                path,
                json=payload,
                headers={**headers(profile, csrf), "Origin": "https://evil.test"},
            ).status_code
            == 403
        )
        response = client.post(path, json=payload, headers=headers(profile, csrf))
        assert response.status_code == 503
        assert response.json()["code"] == "dependency_unavailable"
        assert response.json()["message"] == "Deployment preparation is unavailable."
        assert (
            client.get(path + "/" + str(uuid4()), headers=headers(profile)).status_code
            == 404
        )


def test_chunked_limits_unknown_fields_and_strict_scalars_before_auth(
    tmp_path, monkeypatch
):
    profile, _, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid deployment body reached authentication")

    monkeypatch.setattr(app.state.owner_authority, "authenticate_request", forbidden)
    with TestClient(app, base_url=profile.http_origin) as client:
        path = profile.base_path + "api/v1/deployment/requests"
        for changes in (
            {"slot_id": True},
            {"expires_in_seconds": 59},
            {"pin": "a" * 64},
            {"slot_id": 17},
            {"candidate_id": "x" * 257},
            {"kind": {"nested": {"nested": {"nested": {}}}}},
        ):
            assert (
                client.post(
                    path,
                    json={**prepare_payload(str(uuid4())), **changes},
                    headers=headers(profile),
                ).status_code
                == 400
            )
        assert (
            client.post(
                path,
                content=iter([b"x" * 4096, b"x"]),
                headers={**headers(profile), "Content-Type": "application/json"},
            ).status_code
            == 413
        )
        assert (
            client.request(
                "GET",
                path + "/" + str(uuid4()),
                content=iter([b"x"]),
                headers=headers(profile),
            ).status_code
            == 400
        )


def test_recovery_publication_waits_for_composition_and_survives_worker_failure(
    tmp_path, monkeypatch
):
    from base64 import urlsafe_b64decode

    from app.api import session_routes
    from app.tests.test_deployment_publication import syscall_fixture

    profile, capability, arguments = configured(tmp_path)
    actual, values = http_sources(tmp_path, monkeypatch, profile)
    arguments["first_party_startup_values"] = values
    app = create_app(tmp_path / "data", **arguments)
    path = profile.base_path + "api/v1/deployment/requests"
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        registered = client.post(
            profile.base_path + "api/v1/extensions/candidates",
            json=matching_bundle()[0].as_dict(),
            headers=headers(profile, csrf),
        )
        payload = prepare_payload(registered.json()["candidate_ref"]["candidate_id"])
        prepared = client.post(path, json=payload, headers=headers(profile, csrf))
        assert prepared.status_code == 201
        receipt = prepared.json()
        current = client.get(receipt["links"]["self"], headers=headers(profile)).json()
        assert current["publication_state"] == "pending"
        cookies = dict(client.cookies)
    final = actual.actual(actual.c.OUTBOX_ROOT / "requests") / (
        urlsafe_b64decode(receipt["request_digest"] + "=").hex() + ".json"
    )
    assert not final.exists()
    syscall_fixture(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("controlled startup failure")

    with monkeypatch.context() as failure:
        failure.setattr(session_routes, "create_session_router", fail)
        with pytest.raises(RuntimeError, match="controlled startup"):
            create_app(tmp_path / "data", **arguments)
    assert not final.exists()
    app = create_app(tmp_path / "data", worker_dispatch_factory=fail, **arguments)
    assert not final.exists()
    sources = app.state.first_party_exports["deployment-prepare.service"]
    with (
        pytest.raises(RuntimeError, match="controlled startup"),
        TestClient(app, base_url=profile.http_origin),
    ):
        pytest.fail("Worker failure admitted requests")
    assert final.read_bytes() == canonical_json(current["request"])
    assert sources._topology._closed and sources._exchange._closed
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        client.cookies.update(cookies)
        assert (
            client.get(receipt["links"]["self"], headers=headers(profile)).json()[
                "publication_state"
            ]
            == "published"
        )
        assert (
            client.post(path, json=payload, headers=headers(profile, csrf)).content
            == prepared.content
        )


def test_http_expired_cancel_commits_expiry_but_read_and_replay_do_not(
    tmp_path, monkeypatch
):
    import time

    from app.deployment.prepare_contracts import epoch_ms

    profile, capability, arguments = configured(tmp_path)
    _, values = http_sources(tmp_path, monkeypatch, profile)
    app = create_app(tmp_path / "data", first_party_startup_values=values, **arguments)
    path = profile.base_path + "api/v1/deployment/requests"
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        registration = client.post(
            profile.base_path + "api/v1/extensions/candidates",
            json=matching_bundle()[0].as_dict(),
            headers=headers(profile, csrf),
        )
        payload = prepare_payload(registration.json()["candidate_ref"]["candidate_id"])
        prepared = client.post(path, json=payload, headers=headers(profile, csrf))
        assert prepared.status_code == 201
        receipt = prepared.json()
        current = client.get(receipt["links"]["self"], headers=headers(profile)).json()
        deadline = epoch_ms(current["request"]["expires_at"])
        monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
        assert (
            client.get(receipt["links"]["self"], headers=headers(profile)).json()[
                "state"
            ]
            == "prepared"
        )
        assert (
            client.post(path, json=payload, headers=headers(profile, csrf)).content
            == prepared.content
        )
        cancelled = client.post(
            receipt["links"]["cancel"],
            headers=headers(profile, csrf),
            json={
                "command_id": str(uuid4()),
                "request_digest": receipt["request_digest"],
                "expected_revision": 1,
            },
        )
        assert cancelled.status_code == 409 and cancelled.json()["code"] == "conflict"
        assert (
            client.get(receipt["links"]["self"], headers=headers(profile)).json()[
                "state"
            ]
            == "expired"
        )
        with app.state.domain_store._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_commands"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_lifecycle"
                ).fetchone()[0]
                == 2
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_outbox WHERE role='cancel'"
                ).fetchone()[0]
                == 0
            )


@pytest.mark.parametrize(
    "key,value,expected",
    [
        ("DEEPTWIN_TOPOLOGY_SHA256", None, (False, True)),
        ("DEEPTWIN_TOPOLOGY_SHA256", "invalid", (False, True)),
        ("DEEPTWIN_EXCHANGE_SHA256", False, (True, False)),
        ("DEEPTWIN_PREPARE_RECIPE_SHA256", "invalid", (False, False)),
        ("DEEPTWIN_PREPARE_INSTANCE_SHA256", "x" * 257, (False, False)),
    ],
)
def test_actual_source_open_is_independent_and_malformed_pins_never_fallback(
    tmp_path, monkeypatch, key, value, expected
):
    profile, _, arguments = configured(tmp_path)
    _, values = http_sources(tmp_path, monkeypatch, profile)
    values[key] = value
    app = create_app(tmp_path / "data", first_party_startup_values=values, **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        service = app.state.first_party_exports["deployment-prepare.service"]
        assert (
            service._topology is not None,
            service._exchange is not None,
        ) == expected
        assert client.get(profile.base_path + "health").status_code == 200


@pytest.mark.parametrize("fault", ["second-source", "router", "factory-return"])
def test_factory_local_stack_closes_actual_sources_on_partial_failure(
    tmp_path, monkeypatch, fault
):
    from app.api import deployment_prepare
    from app.api.router_composition import RouteCompositionError

    profile, _, arguments = configured(tmp_path)
    _, values = http_sources(tmp_path, monkeypatch, profile)
    opened = []
    for name in ("open_topology_source", "open_exchange_source"):
        original = getattr(deployment_prepare, name)

        def tracked(*, _original=original, _name=name, **kwargs):
            assert kwargs["profile"] == profile
            assert kwargs["protected_roots"] == (tmp_path / "data", tmp_path / "root")
            if fault == "second-source" and _name == "open_exchange_source":
                raise RuntimeError("private unexpected source failure")
            result = _original(**kwargs)
            opened.append(result)
            return result

        monkeypatch.setattr(deployment_prepare, name, tracked)

    def fail(*args, **kwargs):
        raise RuntimeError("private factory failure")

    if fault == "router":
        monkeypatch.setattr(deployment_prepare, "create_router", fail)
    elif fault == "factory-return":
        monkeypatch.setattr(deployment_prepare, "ContributionServices", fail)
    with pytest.raises(RouteCompositionError) as failure:
        create_app(tmp_path / "data", first_party_startup_values=values, **arguments)
    assert "private" not in str(failure.value)
    assert len(opened) == (1 if fault == "second-source" else 2)
    assert all(source._closed for source in opened)
