"""Finite test-owned supported app for the credentials-panel browser case (T090).

The real supported `create_app` composes the `credentials-v1` routes over a credential
attachment, the real control-plane `CredentialCommandLedger` and the real frame-only
`CredentialGatewayClient`, which speaks authenticated broker frames on socket pairs to a
`CredentialGatewayService` over an encrypted `CredentialVault` (the harness of
test_credential_gateway_persistence, in this process). Test-owned substitutions only:

- `open_credential_attachment` is replaced, so the attachment is that in-process
  socket-pair gateway rather than the verified `cp-provider` pair root;
- the ledger's fence delay is `--fence-delay-seconds` (the production default stays
  `FENCE_AFTER_SECONDS`, 300 s);
- two synthetic secret prefixes script the gateway, as a test actor would:
  `sk-fixture-noreply-…` is committed by the gateway, but its reply and the immediate
  recovery query's reply are dropped (a gateway that commits without replying);
  `sk-fixture-unadmitted-…` fails ambiguously before the gateway admits it, so every later
  query answers `unknown`. Any other secret passes through unchanged;
- the gateway's provider-send path (`ProviderSendService` over the same vault, reached by a
  `ProviderSendClient` on socket pairs) is bound to a loopback mock of the provider's
  models endpoint in this process (`MockModels`), never a real provider;
- the gateway vault adopts a synthetic `provider-transport-qualification-v1` document of
  the shipped manifest (the real qualification act needs a verified extension
  installation, which this fixture does not stage); every catalog page is still reserved
  in the app's own budget book by the product composition;
- `GET /__test__/upstream` (a wrapper route in front of the app, not a product route) only
  reports how many requests the mock provider received and how many carried the key the
  gateway currently binds (counts, never the key).

The catalog refresh and model choice are the product routes. No real provider, model or
outbound network call; every secret is synthetic test-actor data."""
import argparse
import base64
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.api import credential_wiring
from app.api.credential_catalog import GatewayCatalogLister
from app.api.credential_commands import CredentialCommandLedger
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.server import create_app
from app.tests.support.transport_manifest import qualify_vault
from app.tests.test_credential_gateway_persistence import Gateway
from app.workers import credential_gateway_service
from app.workers.credential_attachment import (
    CredentialGatewayConfiguration,
)
from app.workers.credential_channel import GatewayServiceError

NO_REPLY = b"sk-fixture-noreply-"
UNADMITTED = b"sk-fixture-unadmitted-"
MODELS = ["synthetic-model-a", "synthetic-model-b"]

_dropped = []
_drop_lock = threading.Lock()
_original_write = credential_gateway_service._write_logical_connection


def _reply(connection, **kwargs):
    with _drop_lock:
        drop = bool(_dropped) and _dropped.pop() is True
    if drop:
        connection.close()  # committed at the gateway; the answer never reaches the control plane
        return None
    return _original_write(connection, **kwargs)


class ScriptedClient:
    """The real frame client; only the two synthetic prefixes change what happens."""

    def __init__(self, client):
        self._client = client

    def store_at(self, *, metadata, secret):
        if bytes(secret[:len(UNADMITTED)]) == UNADMITTED:
            raise GatewayServiceError("gateway channel failed")  # sent: ambiguous, never admitted
        if bytes(secret[:len(NO_REPLY)]) == NO_REPLY:
            with _drop_lock:
                _dropped.extend([True, True])  # the store reply and the recovery query reply
        return self._client.store_at(metadata=metadata, secret=secret)

    def query_record(self, *, metadata):
        return self._client.query_record(metadata=metadata)

    def retire(self, **kwargs):
        return self._client.retire(**kwargs)

    def bind_head(self, **kwargs):
        return self._client.bind_head(**kwargs)

    def bind_transport(self, **kwargs):
        return self._client.bind_transport(**kwargs)


class MockModels:
    """A loopback mock of the provider's models endpoint: one page of synthetic models."""

    def __init__(self):
        self.keys = []  # the key of each request, held in memory only, never written out
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.keys.append(self.headers.get("x-api-key"))
                body = json.dumps({"data": [
                    {"type": "model", "id": MODELS[0], "display_name": MODELS[0],
                     "created_at": "2026-01-02T00:00:00Z"},
                    {"type": "model", "id": MODELS[1], "display_name": MODELS[1],
                     "created_at": "2026-01-01T00:00:00Z"}],
                    "first_id": MODELS[0], "last_id": MODELS[1], "has_more": False}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def with_upstream_route(app, upstream):
    """The app, with one observation-only test route in front of it (never the product):
    how many requests the mock provider received, and how many distinct keys they carried
    (counts only, never a key)."""

    async def wrapper(scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/__test__/upstream" or scope["method"] != "GET":
            return await app(scope, receive, send)
        payload = {"requests": len(upstream.keys),
                   "distinct_keys": len({key for key in upstream.keys if key is not None})}
        data = json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": data})

    return wrapper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    parser.add_argument("--fence-delay-seconds", required=True, type=float)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    (owned / "gateway").mkdir(mode=0o700)
    (owned / "ledger").mkdir(mode=0o700)
    gateway = Gateway(owned / "gateway")
    # the gateway sends only through a qualified provider-transport manifest (T087); the
    # fixture adopts a synthetic qualification document of the shipped manifest, as the
    # authenticated control side would publish it (test_provider_transport_manifest runs
    # the real qualification act)
    qualify_vault(gateway.vault)
    ledger_path = owned / "ledger" / credential_wiring.LEDGER_NAME
    ledger = CredentialCommandLedger(ledger_path, fence_after_seconds=args.fence_delay_seconds)
    credential_gateway_service._write_logical_connection = _reply

    upstream = MockModels()
    lister = GatewayCatalogLister(lambda: gateway.send_client(upstream.port))

    def attachment(configuration, *, state_directory):
        return credential_wiring.CredentialAttachment(client=ScriptedClient(gateway.client()), ledger=ledger,
                                                      ledger_path=ledger_path, catalog_lister=lister)

    credential_wiring.open_credential_attachment = attachment  # test-owned endpoint substitution
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)  # accept (queue) before the URL is announced
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(),
                     credential_gateway=CredentialGatewayConfiguration(
                         pair_root=str(owned / "gateway" / "pair"), requester_boot_id="fixture-control-boot"))
    print(f"CREDENTIALS_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(with_upstream_route(app, upstream), log_level="warning",
                                      access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()
        upstream.close()
        gateway.close()


if __name__ == "__main__":
    main()
