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


# ----------------------------------------- delete retirement and zero-effect reads


HANDLE = "f" * 32


def delete_credential(client, handle):
    return client.request(
        "DELETE",
        f"/api/v1/credentials/{handle}",
        headers={**FETCH, "X-CSRF-Token": client.csrf_token},
    )


def test_delete_retirement_forwards_and_returns_a_redacted_receipt(tmp_path):
    application = make_app(tmp_path)
    retired = []

    def gateway_retire(handle):
        retired.append(handle)
        return {"handle": handle, "state": "erasure_completed"}

    application.state.credential_gateway_retire = gateway_retire
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = delete_credential(client, HANDLE)
        assert response.status_code == 200, response.text
        assert response.json() == {"handle": HANDLE, "state": "erasure_completed"}
    assert retired == [HANDLE]


def test_delete_requires_gateway_valid_handle_and_csrf(tmp_path):
    application = make_app(tmp_path)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        assert_error(
            delete_credential(client, HANDLE),
            status=503, code="dependency_unavailable",
        )
        application.state.credential_gateway_retire = lambda handle: {
            "handle": handle, "state": "erasure_completed",
        }
        assert_error(
            delete_credential(client, "not-a-handle"),
            status=400, code="invalid_input",
        )
        response = client.request(
            "DELETE", f"/api/v1/credentials/{HANDLE}", headers=FETCH,
        )
        assert_error(response, status=403, code="access_denied")


def test_delete_rejects_a_misbehaving_retire_receipt(tmp_path):
    application = make_app(tmp_path)
    application.state.credential_gateway_retire = lambda handle: {
        "handle": handle, "state": "erasure_completed", "secret": "sk-leak",
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
        lambda handle: effects.append("retire")
    )
    application.state.credential_status_snapshot = lambda: [
        {"handle": HANDLE, "provider": "claude", "state": "active"},
    ]
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = client.get("/api/v1/credentials", headers=FETCH)
        assert response.status_code == 200, response.text
        assert response.json() == {"credentials": [
            {"handle": HANDLE, "provider": "claude", "state": "active"},
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
        {"handle": HANDLE, "provider": "claude", "state": "active",
         "secret": "sk-snap-leak"},
    ]
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = client.get("/api/v1/credentials", headers=FETCH)
        assert response.status_code == 503, response.text
        assert "sk-snap-leak" not in response.text


# --------------------------------------- end-to-end: HTTP to vault over frames


def test_full_stack_credential_flow_over_authenticated_frames(tmp_path):
    import socket as socket_module
    import threading as threading_module

    from app.api.credential_routes import attach_credential_gateway
    from app.tests.test_credential_gateway_service import (
        REQUESTER_BOOT,
        RESPONDER_BOOT,
        channel_spec,
    )
    from app.workers import broker
    from app.workers.credential_channel import CredentialGatewayClient
    from app.workers.credential_gateway_service import CredentialGatewayService
    from app.workers.credential_vault import CredentialVault

    vault = CredentialVault(str(tmp_path / "gateway-vault"))
    spec = channel_spec(tmp_path / "pair")
    boot_secret = broker.BootSecret(b"k" * broker.AUTH_SECRET_BYTES)
    service = CredentialGatewayService(vault, spec, boot_secret)
    threads = []

    def transport_factory():
        left, right = socket_module.socketpair(
            socket_module.AF_UNIX, socket_module.SOCK_STREAM,
        )

        def serve():
            session = broker._server_handshake_impl(
                right, spec, boot_secret,
                requester_boot_id=REQUESTER_BOOT,
                responder_boot_id=RESPONDER_BOOT,
                deadline=broker.Deadline.after_ms(5_000),
                verify_peer=False,
            )
            codec = broker.FrameCodec(
                spec, session, local_service=spec.responder_service,
            )
            try:
                service.serve_one(
                    right, codec, deadline=broker.Deadline.after_ms(5_000),
                )
            finally:
                codec.close()
                right.close()

        thread = threading_module.Thread(target=serve)
        thread.start()
        threads.append(thread)
        session = broker._client_handshake_impl(
            left, spec, boot_secret,
            requester_boot_id=REQUESTER_BOOT,
            responder_boot_id=RESPONDER_BOOT,
            deadline=broker.Deadline.after_ms(5_000),
            verify_peer=False,
        )
        return left, broker.FrameCodec(
            spec, session, local_service=spec.requester_service,
        )

    application = make_app(tmp_path)
    attach_credential_gateway(
        application, CredentialGatewayClient(transport_factory),
    )
    with LocalTestClient(application, base_url=ORIGIN) as client:
        created = post_credentials(client, json.dumps(payload()))
        assert created.status_code == 201, created.text
        handle = created.json()["handle"]
        assert SECRET not in created.text
        assert vault.resolve_for_gateway(handle) == SECRET.encode("utf-8")

        listed = client.get("/api/v1/credentials", headers=FETCH)
        assert listed.json() == {"credentials": [
            {"handle": handle, "provider": "claude", "state": "active"},
        ]}

        removed = delete_credential(client, handle)
        assert removed.json() == {"handle": handle, "state": "erasure_completed"}
        assert vault.health()["active"] == 0
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
