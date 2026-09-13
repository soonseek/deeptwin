"""Authenticated HTTP ingress for credential create/rotate (T090).

The route sits on the existing session/CSRF authority, applies the exact wire
checks before any effect, forwards the validated intent to the attached gateway
boundary (the control plane never imports the vault), and returns only a
redacted receipt. Without an attached gateway the route is honestly unavailable.
"""

import json

from app.server import create_app
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
        return {"handle": "0" * 32, "provider": ingress.provider, "state": "active"}

    application.state.credential_gateway_submit = gateway_submit
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = post_credentials(client, json.dumps(payload()))
        assert response.status_code == 201, response.text
        body = response.json()
        assert body == {"handle": "0" * 32, "provider": "claude", "state": "active"}
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
    with LocalTestClient(application, base_url=ORIGIN) as client:
        for body, extra in (
            (json.dumps(payload(secret="sk\nmultiline")), {}),
            (json.dumps(payload(secret="")), {}),
            (json.dumps(payload(extra=True)), {}),
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
    assert forwarded == []


def test_a_misbehaving_gateway_receipt_is_never_echoed(tmp_path):
    application = make_app(tmp_path)
    application.state.credential_gateway_submit = lambda ingress: {
        "handle": "0" * 32,
        "provider": "claude",
        "state": "active",
        "secret": ingress.secret.decode("utf-8"),  # hostile extra field
    }
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = post_credentials(client, json.dumps(payload()))
        assert response.status_code == 503, response.text
        assert SECRET not in response.text
