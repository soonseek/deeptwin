"""T090 CredentialedProviderTransport over a real loopback fake server.

The transport lives in the dedicated provider gateway: it receives an opaque
credential handle, resolves it at send time, injects the auth header itself, pins
the connection to the exact bound origin (the caller never supplies a URL), rejects
non-projected headers before any network effect, never follows redirects, and
returns bounded, redacted responses that never carry credentials or raw provider
error bodies.
"""

import http.server
import json
import threading
from typing import ClassVar
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.workers.credential_vault import CredentialVault, CredentialVaultError
from app.tests.test_credential_root import initialized
from app.tests.test_credential_custody import metadata
from app.workers.provider_gateway import (
    CredentialedProviderTransport,
    GatewayError,
    ProviderBinding,
)

INTENT = "00000000-0000-4000-8000-00000000bb01"
SECRET = b"sk-live-gateway-secret-000"
PROVIDER = "claude"


class SyntheticCustody:
    """HTTP fixture only: never accepted by the production exact-vault type gate."""
    def __init__(self):
        self.entries = {}

    def store(self, _intent, provider, secret):
        handle = str(uuid4())
        self.entries[handle] = dict(provider=provider, secret=secret, retired=False)
        return SimpleNamespace(handle=handle)

    def metadata(self, handle):
        if handle not in self.entries:
            raise CredentialVaultError("unknown_record")
        return {"provider": self.entries[handle]["provider"]}

    def resolve_for_gateway(self, handle):
        if self.entries[handle]["retired"]:
            raise CredentialVaultError("provider_binding_unavailable")
        return self.entries[handle]["secret"]

    def retire(self, handle):
        self.entries[handle]["retired"] = True


class FakeProvider(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    script: ClassVar[dict] = {}

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).seen.append({
            "method": self.command,
            "path": self.path,
            "headers": {key.lower(): value for key, value in self.headers.items()},
            "body": body,
        })
        script = type(self).script
        status = script.get("status", 200)
        payload = script.get("body", b'{"ok": true}')
        self.send_response(status)
        for name, value in script.get("headers", {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_POST = _handle
    do_GET = _handle

    def log_message(self, *_args):
        pass


@pytest.fixture
def provider_server():
    FakeProvider.seen = []
    FakeProvider.script = {}
    server = http.server.HTTPServer(("127.0.0.1", 0), FakeProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(3)
    server.server_close()
    assert not thread.is_alive()


@pytest.fixture
def subject(tmp_path, provider_server, monkeypatch):
    from app.workers import provider_gateway
    # Patch only this test module's consumer type gate. No production activation seam.
    monkeypatch.setattr(provider_gateway, "CredentialVault", SyntheticCustody)
    vault = SyntheticCustody()
    record = vault.store(INTENT, PROVIDER, SECRET)
    binding = ProviderBinding(
        provider=PROVIDER,
        scheme="http",
        host="127.0.0.1",
        port=provider_server.server_address[1],
        allowed_methods=("POST",),
        allowed_path_prefixes=("/v1/messages",),
        allowed_request_headers=("content-type", "accept", "anthropic-version"),
        auth_header="x-api-key",
        max_request_bytes=65_536,
        max_response_bytes=65_536,
        timeout_seconds=5,
    )
    transport = CredentialedProviderTransport(vault, binding)
    return vault, record, transport


def send(transport, handle, **overrides):
    request = {
        "method": "POST",
        "path": "/v1/messages",
        "headers": {"content-type": "application/json"},
        "body": b'{"model": "fake"}',
    }
    request.update(overrides)
    return transport.send(
        handle=handle,
        method=request["method"],
        path=request["path"],
        headers=request["headers"],
        body=request["body"],
    )


def test_auth_is_injected_at_send_time_and_bytes_round_trip(subject):
    _vault, record, transport = subject
    response = send(transport, record.handle)
    assert response.status == 200
    assert json.loads(response.body) == {"ok": True}
    assert len(FakeProvider.seen) == 1
    seen = FakeProvider.seen[0]
    assert seen["path"] == "/v1/messages"
    assert seen["headers"]["x-api-key"] == SECRET.decode()
    assert seen["body"] == b'{"model": "fake"}'


def test_caller_supplied_auth_or_proxy_headers_never_reach_the_wire(subject):
    _vault, record, transport = subject
    for headers in (
        {"content-type": "application/json", "x-api-key": "sk-forged"},
        {"content-type": "application/json", "authorization": "Bearer forged"},
        {"content-type": "application/json", "host": "evil.example"},
        {"content-type": "application/json", "proxy-authorization": "x"},
        {"content-type": "application/json", "transfer-encoding": "chunked"},
        {"content-type": "application/json", "cookie": "session=1"},
        {"content-type": "application/json", "x-unlisted": "value"},
    ):
        with pytest.raises(GatewayError):
            send(transport, record.handle, headers=headers)
    assert FakeProvider.seen == []  # zero network effect


def test_the_caller_cannot_choose_a_destination(subject):
    _vault, record, transport = subject
    for path in (
        "http://evil.example/v1/messages",
        "//evil.example/v1/messages",
        "/v1/messages/../../admin",
        "/other/endpoint",
        "v1/messages",
        "/v1/messages\r\nHost: evil",
    ):
        with pytest.raises(GatewayError):
            send(transport, record.handle, path=path)
    with pytest.raises(GatewayError):
        send(transport, record.handle, method="GET")
    assert FakeProvider.seen == []


def test_redirects_are_never_followed(subject):
    _vault, record, transport = subject
    FakeProvider.script = {
        "status": 302,
        "headers": {"Location": "http://evil.example/steal"},
        "body": b"",
    }
    with pytest.raises(GatewayError) as failure:
        send(transport, record.handle)
    assert len(FakeProvider.seen) == 1  # exactly one request, no follow
    assert "evil.example" not in str(failure.value)


def test_provider_error_bodies_are_redacted(subject):
    _vault, record, transport = subject
    FakeProvider.script = {
        "status": 400,
        "body": b'{"error": "invalid key sk-live-gateway-secret-000 for acct 42"}',
    }
    with pytest.raises(GatewayError) as failure:
        send(transport, record.handle)
    message = str(failure.value)
    assert "sk-live" not in message
    assert "acct 42" not in message


def test_oversized_bodies_fail_closed(subject):
    _vault, record, transport = subject
    with pytest.raises(GatewayError):
        send(transport, record.handle, body=b"x" * 65_537)
    assert FakeProvider.seen == []
    FakeProvider.script = {"status": 200, "body": b"y" * 70_000}
    with pytest.raises(GatewayError):
        send(transport, record.handle)


def test_handle_binding_and_lifecycle_are_enforced(subject):
    vault, record, transport = subject
    other = vault.store(
        "00000000-0000-4000-8000-00000000bb02", "codex", b"sk-other-provider",
    )
    with pytest.raises(GatewayError):
        send(transport, other.handle)  # provider mismatch
    vault.retire(record.handle)
    with pytest.raises(GatewayError):
        send(transport, record.handle)  # retired handle cannot resolve
    assert FakeProvider.seen == []


def test_nothing_ever_leaks_the_secret(subject):
    _vault, record, transport = subject
    assert SECRET.decode() not in repr(transport)
    try:
        send(transport, record.handle, path="/other/endpoint")
    except GatewayError as exc:
        assert SECRET.decode() not in str(exc)


def test_binding_validation_is_fail_closed(tmp_path):
    with pytest.raises(GatewayError):
        ProviderBinding(
            provider=PROVIDER,
            scheme="http",
            host="provider.example",  # plain http is loopback-only
            port=443,
            allowed_methods=("POST",),
            allowed_path_prefixes=("/v1/messages",),
            allowed_request_headers=("content-type",),
            auth_header="x-api-key",
            max_request_bytes=1_024,
            max_response_bytes=1_024,
            timeout_seconds=5,
        )
    with pytest.raises(GatewayError):
        ProviderBinding(
            provider=PROVIDER,
            scheme="https",
            host="provider.example",
            port=443,
            allowed_methods=("POST",),
            allowed_path_prefixes=("relative-path",),  # must be absolute
            allowed_request_headers=("content-type",),
            auth_header="x-api-key",
            max_request_bytes=1_024,
            max_response_bytes=1_024,
            timeout_seconds=5,
        )
    with pytest.raises(GatewayError):
        CredentialedProviderTransport(object(), None)


def test_production_constructor_rejects_synthetic_resolver(provider_server):
    binding = ProviderBinding(PROVIDER, "http", "127.0.0.1", provider_server.server_address[1],
        ("POST",), ("/v1/messages",), ("content-type",), "x-api-key", 65536, 65536, 5)
    with pytest.raises(GatewayError):
        CredentialedProviderTransport(SyntheticCustody(), binding)


def test_actual_encrypted_unbound_backend_sends_zero_requests(tmp_path, provider_server):
    binding = ProviderBinding(PROVIDER, "http", "127.0.0.1", provider_server.server_address[1],
        ("POST",), ("/v1/messages",), ("content-type",), "x-api-key", 65536, 65536, 5)
    with CredentialVault(**initialized(tmp_path)) as vault:
        record = vault.store_at(metadata=metadata(), secret=SECRET)
        transport = CredentialedProviderTransport(vault, binding)
        with pytest.raises(GatewayError):
            send(transport, record["record_id"])
        reference = {k: record[k] for k in ("record_id", "record_version", "ciphertext_sha256")}
        vault.retire(command_id=str(uuid4()), record=reference, reason="owner_delete")
        with pytest.raises(GatewayError):
            send(transport, record["record_id"])
    assert FakeProvider.seen == []


def test_a_header_unsafe_secret_fails_sanitized_with_zero_network_effect(
    subject, monkeypatch,
):
    """Audit F1: a resolved secret hostile to header framing must never leak."""

    vault, record, transport = subject
    hostile = b"line1\nsk-secret-TOPSECRET-abc123"
    monkeypatch.setattr(
        type(vault), "resolve_for_gateway", lambda _self, _handle: hostile,
    )
    with pytest.raises(GatewayError) as failure:
        send(transport, record.handle)
    assert "TOPSECRET" not in str(failure.value)
    assert failure.value.__cause__ is None or "TOPSECRET" not in str(
        failure.value.__cause__
    )
    assert FakeProvider.seen == []
