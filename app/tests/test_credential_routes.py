"""Authenticated HTTP credential routes at their state seams (T090).

The routes sit on the existing session/CSRF authority, apply the exact wire
checks before any effect, forward the validated act to the attached seams (the
control plane never imports the vault), and return only redacted projections.
Without an attachment the routes are honestly unavailable. The full stack over
the real gateway channel is in test_credential_routes_v2.py.
"""

import json

from app.server import create_development_app as create_app
from app.tests.local_http import LocalTestClient
from app.tests.test_server_api_v1 import FETCH, ORIGIN, assert_error

INTENT = "00000000-0000-4000-8000-00000000dd01"
SECRET = "sk-route-secret-000"


def payload(**overrides):
    value = {"intent_id": INTENT, "provider": "claude", "secret": SECRET}
    value.update(overrides)
    return value


def post_credentials(client, body, **header_overrides):
    headers = {
        **FETCH,
        "X-CSRF-Token": client.csrf_token,
        "Content-Type": "application/json",
        **header_overrides,
    }
    return client.post("/api/v1/credentials", content=body, headers=headers)


def make_app(tmp_path):
    return create_app(tmp_path, port=4193, understanding_provider_ready=False)


def test_unauthenticated_requests_are_denied(tmp_path):
    application = make_app(tmp_path)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        # A write without the CSRF proof is refused by the local boundary.
        response = client.post(
            "/api/v1/credentials",
            content=json.dumps(payload()),
            headers={**FETCH, "Content-Type": "application/json"},
        )
        assert_error(response, status=403, code="access_denied")


def test_without_an_attached_gateway_the_route_is_unavailable(tmp_path):
    application = make_app(tmp_path)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = post_credentials(client, json.dumps(payload()))
        assert_error(response, status=503, code="dependency_unavailable")


def test_a_valid_intent_forwards_once_and_returns_a_redacted_receipt(tmp_path):
    application = make_app(tmp_path)
    forwarded = []

    def gateway_submit(ingress):
        forwarded.append(ingress)
        return {"handle": "0" * 32, "provider": ingress.provider, "state": "stored_unbound"}

    application.state.credential_gateway_submit = gateway_submit
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = post_credentials(client, json.dumps(payload()))
        assert response.status_code == 201, response.text
        body = response.json()
        assert body == {"handle": "0" * 32, "provider": "claude", "state": "stored_unbound"}
        assert SECRET not in response.text
    assert len(forwarded) == 1
    assert forwarded[0].intent_id == INTENT
    assert forwarded[0].secret == SECRET.encode("utf-8")
    assert forwarded[0].rotate_from is None


def test_wire_violations_fail_before_the_gateway(tmp_path):
    application = make_app(tmp_path)
    forwarded = []
    application.state.credential_gateway_submit = (
        lambda ingress: forwarded.append(ingress)
    )
    duplicate = ('{"intent_id":"' + INTENT
                 + '","provider":"claude","secret":"sk-route-a","secret":"sk-route-b"}')
    with LocalTestClient(application, base_url=ORIGIN) as client:
        for body, extra in (
            (json.dumps(payload(secret="sk\nmultiline")), {}),
            (json.dumps(payload(secret="")), {}),
            (json.dumps(payload(extra=True)), {}),
            (duplicate, {}),
            (b"not json", {}),
            (
                json.dumps(payload()),
                {"Content-Type": "text/plain"},
            ),
        ):
            response = post_credentials(client, body, **extra)
            assert_error(response, status=400, code="invalid_input")
            assert "sk-route" not in response.text
            assert "multiline" not in response.text
        # a secret above 65,536 UTF-8 bytes inside an acceptable frame is a 413
        response = post_credentials(client, json.dumps(payload(secret="x" * 65_537)))
        assert_error(response, status=413, code="invalid_input")
        # a query string is not part of the act
        response = client.post("/api/v1/credentials?x=1", content=json.dumps(payload()),
                               headers={**FETCH, "X-CSRF-Token": client.csrf_token,
                                        "Content-Type": "application/json"})
        assert_error(response, status=400, code="invalid_input")
    assert forwarded == []


def test_a_misbehaving_gateway_receipt_is_never_echoed(tmp_path):
    application = make_app(tmp_path)
    application.state.credential_gateway_submit = lambda ingress: {
        "handle": "0" * 32,
        "provider": "claude",
        "state": "stored_unbound",
        "secret": ingress.secret.decode("utf-8"),  # hostile extra field
    }
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = post_credentials(client, json.dumps(payload()))
        assert response.status_code == 503, response.text
        assert SECRET not in response.text


# ----------------------------------------- delete retirement and zero-effect reads


HANDLE = "f" * 32
DELETE_INTENT = "00000000-0000-4000-8000-00000000dd02"


def delete_credential(client, handle, intent=DELETE_INTENT, **header_overrides):
    return client.request(
        "DELETE",
        f"/api/v1/credentials/{handle}",
        content=json.dumps({"intent_id": intent}),
        headers={**FETCH, "X-CSRF-Token": client.csrf_token,
                 "Content-Type": "application/json", **header_overrides},
    )


def test_delete_retirement_forwards_and_returns_a_redacted_receipt(tmp_path):
    application = make_app(tmp_path)
    retired = []

    def gateway_retire(intent_id, handle):
        retired.append((intent_id, handle))
        return {"handle": handle, "state": "cleanup_pending"}

    application.state.credential_gateway_retire = gateway_retire
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = delete_credential(client, HANDLE)
        assert response.status_code == 200, response.text
        # local cleanup state, and explicitly no provider-side revocation
        assert response.json() == {"handle": HANDLE, "state": "cleanup_pending",
                                   "provider_revocation": "not_performed"}
    assert retired == [(DELETE_INTENT, HANDLE)]


def test_delete_requires_gateway_valid_handle_intent_and_csrf(tmp_path):
    application = make_app(tmp_path)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        assert_error(
            delete_credential(client, HANDLE),
            status=503, code="dependency_unavailable",
        )
        calls = []

        def retire(intent_id, handle):
            calls.append(handle)
            return {"handle": handle, "state": "cleanup_pending"}

        application.state.credential_gateway_retire = retire
        assert_error(
            delete_credential(client, "not-a-handle"),
            status=400, code="invalid_input",
        )
        duplicate = '{"intent_id":"' + DELETE_INTENT + '","intent_id":"' + DELETE_INTENT + '"}'
        for body in ("", "{}", '{"intent_id":"x"}', duplicate,
                     json.dumps({"intent_id": DELETE_INTENT, "extra": 1})):
            response = client.request(
                "DELETE", f"/api/v1/credentials/{HANDLE}", content=body,
                headers={**FETCH, "X-CSRF-Token": client.csrf_token,
                         "Content-Type": "application/json"})
            assert_error(response, status=400, code="invalid_input")
        assert_error(delete_credential(client, HANDLE, **{"Content-Type": "text/plain"}),
                     status=400, code="invalid_input")
        response = client.request(
            "DELETE", f"/api/v1/credentials/{HANDLE}",
            content=json.dumps({"intent_id": DELETE_INTENT}),
            headers={**FETCH, "Content-Type": "application/json"},
        )
        assert_error(response, status=403, code="access_denied")
        assert calls == []


def test_delete_rejects_a_misbehaving_retire_receipt(tmp_path):
    application = make_app(tmp_path)
    application.state.credential_gateway_retire = lambda intent_id, handle: {
        "handle": handle, "state": "cleanup_pending", "secret": "sk-leak",
    }
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = delete_credential(client, HANDLE)
        assert response.status_code == 503, response.text
        assert "sk-leak" not in response.text


def test_status_read_is_redacted_and_makes_zero_gateway_effect(tmp_path):
    application = make_app(tmp_path)
    effects = []
    application.state.credential_gateway_submit = (
        lambda ingress: effects.append("submit")
    )
    application.state.credential_gateway_retire = (
        lambda intent_id, handle: effects.append("retire")
    )
    application.state.credential_status_snapshot = lambda: [
        {"handle": HANDLE, "provider": "claude", "state": "stored_unbound"},
    ]
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = client.get("/api/v1/credentials", headers=FETCH)
        assert response.status_code == 200, response.text
        assert response.json() == {"credentials": [
            {"handle": HANDLE, "provider": "claude", "state": "stored_unbound",
             "provider_revocation": "not_performed"},
        ]}
    assert effects == []  # a snapshot read touches neither vault nor gateway


def test_status_read_without_a_snapshot_source_is_unavailable(tmp_path):
    application = make_app(tmp_path)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        assert_error(
            client.get("/api/v1/credentials", headers=FETCH),
            status=503, code="dependency_unavailable",
        )


def test_status_read_rejects_a_misbehaving_snapshot(tmp_path):
    application = make_app(tmp_path)
    application.state.credential_status_snapshot = lambda: [
        {"handle": HANDLE, "provider": "claude", "state": "stored_unbound",
         "secret": "sk-snap-leak"},
    ]
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = client.get("/api/v1/credentials", headers=FETCH)
        assert response.status_code == 503, response.text
        assert "sk-snap-leak" not in response.text
