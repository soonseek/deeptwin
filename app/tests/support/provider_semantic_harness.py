"""Synthetic-only Task47 fixtures.  Nothing in app imports this module."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from uuid import uuid4

from app.domain.refs import canonical_json
from app.extensions.port_contracts import PORT_SCHEMA_IDS
from app.tests.test_credential_custody import metadata
from app.tests.test_credential_root import initialized
from app.workers.credential_contracts import fingerprint
from app.workers.credential_vault import CredentialVault
from app.workers import broker, listener
from app.workers.provider_port_service import ProviderPortService


class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    captures = None
    response = None
    entered = None
    release = None
    block_phase = None

    def log_message(self, *_):
        pass

    def _serve(self):
        size = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(size)
        self.captures.append((self.command, self.path, dict(self.headers), body))
        if self.block_phase != "body":
            self.entered.set()
        if self.release is not None and self.block_phase == "headers":
            self.release.wait(5)
        response = (self.response[len(self.captures) - 1]
                    if type(self.response) is list else self.response)
        if len(response) == 3:
            status, media, payload = response
            extra_headers = {}
        else:
            status, media, payload, extra_headers = response
        self.send_response(status)
        if media is not None:
            self.send_header("content-type", media)
        for name, value in extra_headers.items():
            self.send_header(name, value)
        self.send_header("content-length", str(len(payload)))
        self.send_header("connection", "close")
        self.end_headers()
        if self.release is not None and self.block_phase == "body":
            self.entered.set()
            self.release.wait(5)
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    do_GET = _serve
    do_POST = _serve


@contextmanager
def controlled_upstream(*, response=(200, "application/json", b"{}"), blocked=False,
                        block_phase="headers"):
    captures, entered = [], threading.Event()
    release = threading.Event() if blocked else None
    handler = type("SyntheticClaude", (_Upstream,), {"captures": captures, "response": response,
        "entered": entered, "release": release, "block_phase": block_phase})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=False)
    thread.start()
    try:
        yield server.server_address[1], captures, entered, release
    finally:
        if release is not None:
            release.set()
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()


@contextmanager
def encrypted_credential(tmp_path, secret=b"synthetic-task47-api-key"):
    args = initialized(tmp_path)
    meta = metadata()
    with CredentialVault(**args) as vault:
        receipt = vault.store_at(metadata=meta, secret=secret)
        record = {key: receipt[key] for key in ("record_id", "record_version", "ciphertext_sha256")}
        yield vault, meta, record


def connection_values(meta, record):
    handle = {"kind": "validation_report", "id": str(uuid4()), "version": 1,
              "sha256": "a" * 64}
    pin = {"locator": {"kind": "connection", "id": str(uuid4())},
           "revision_digest": "b" * 64, "provider_id": "claude_api", "account_id": "account",
           "credential_metadata_sha256": fingerprint(meta)}
    return handle, pin, meta, record


def immutable_ref(kind="validation_report", digest="a"):
    return {"kind": kind, "id": str(uuid4()), "version": 1, "sha256": digest * 64}


def canonical_provider_request(operation, input_value, *, request_id=None,
                               artifact_inputs=None, identity=None,
                               deadline_at="2026-09-20T00:00:30.000Z"):
    """Complete provider-port-v1 request fixture; no authority is implied."""
    identity = {} if identity is None else identity
    artifact_inputs = [] if artifact_inputs is None else artifact_inputs
    value = {
        "schema_id": PORT_SCHEMA_IDS[("provider-port-v1", "request")],
        "schema_version": 1,
        "port_contract_version": "provider-port-v1",
        "request_id": str(uuid4()) if request_id is None else request_id,
        "operation": operation,
        "installation_digest": identity.get("installation_digest", "1" * 64),
        "qualification_ref": identity.get("qualification_ref", immutable_ref(digest="2")),
        "binding_revision_ref": identity.get("binding_revision_ref", immutable_ref(digest="3")),
        "purpose_ref": identity.get("purpose_ref", immutable_ref(digest="4")),
        "actor_ref": identity.get("actor_ref", immutable_ref("actor", "5")),
        "grant_refs": identity.get("grant_refs", []),
        "idempotency_key": "0" * 64,
        "deadline_at": deadline_at,
        "cancellation_ref": None,
        "artifact_inputs": artifact_inputs,
        "input": input_value,
        "extension_input": {},
    }
    key = {name: value[name] for name in ("port_contract_version", "installation_digest",
        "binding_revision_ref", "purpose_ref", "operation", "grant_refs", "artifact_inputs",
        "input", "extension_input")}
    value["idempotency_key"] = __import__("hashlib").sha256(canonical_json(key)).hexdigest()
    return value


def canonical_provider_config(handle_ref, *, identity=None, catalog_ttl_seconds=86_400):
    """Complete provider-port-v1 config fixture; callers provide real stored refs."""
    identity = {} if identity is None else identity
    slot = {"port_contract_version": "provider-port-v1",
            "target_scope_fingerprint": identity.get("target_scope_fingerprint", "6" * 64),
            "purpose": "operational", "binding_slot_id": "provider-primary",
            "capability_selector_digest": identity.get("capability_selector_digest", "7" * 64)}
    return {
        "schema_id": PORT_SCHEMA_IDS[("provider-port-v1", "config")],
        "schema_version": 1, "port_contract_version": "provider-port-v1",
        "extension_id": "claude-semantic-worker",
        "installation_digest": identity.get("installation_digest", "1" * 64),
        "qualification_ref": identity["qualification_ref"],
        "binding_revision_ref": identity["binding_revision_ref"],
        "binding_slot_key": slot,
        "binding_slot_key_digest": __import__("hashlib").sha256(canonical_json(slot)).hexdigest(),
        "extension_config": {}, "grant_refs": identity.get("grant_refs", []),
        "credential_handle_refs": [handle_ref],
        "resource_limits": {"deadline_ms": 30_000, "max_input_bytes": 262_144,
                            "max_output_bytes": 524_288, "max_artifacts": 4,
                            "max_artifact_bytes": 524_288,
                            "max_artifact_input_bytes": 262_144},
        "port_config": {"provider_id": "claude_api", "auth_mode": "api",
                        "api_origin": "https://api.anthropic.com",
                        "egress_policy_ref": identity["egress_policy_ref"],
                        "catalog_ttl_seconds": catalog_ttl_seconds,
                        "supported_modalities": ["text"],
                        "supported_input_media_types": ["text/plain"]},
    }


@contextmanager
def owned_semantic_service(root, spec, side, *, deadline_ms=3_000):
    """Serve one dialogue through a real conditional-local extension owner.

    ``side`` comes from ``test_extension_listener.seams`` and carries only the
    adopted macOS substitutions.  Socket I/O, readiness HMAC, frame MAC/sequence,
    generation/fence retention, and owner issuance remain real.  This helper is
    test-only and is not native Linux, peer-credential, release, or deployment
    evidence.
    """

    service = ProviderPortService()  # constructed before any connection, as a worker starts
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="owned-worker"
    )
    box = {}

    def serve():
        side["worker_ident"] = threading.get_ident()
        try:
            owned = listener._accept_extension_authenticated(
                worker, deadline=broker.Deadline.after_ms(deadline_ms)
            )
            box["owner"] = owned
            service.serve_connection(owned, deadline=owned.deadline)
        except BaseException as error:  # noqa: BLE001 - returned to test owner
            box["error"] = error

    thread = threading.Thread(target=serve, daemon=False)
    thread.start()
    try:
        yield box
    finally:
        thread.join((deadline_ms / 1000) + 2)
        worker.close()
        assert not thread.is_alive()
