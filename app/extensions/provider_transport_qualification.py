"""Qualification of a provider-transport manifest (T087) for the credential gateway (T090).

The gateway's credentialed transport serves sends only through a manifest-built binding
(`app/workers/provider_transport_manifest.py`), and only while the gateway holds a
qualification naming that manifest's digest. This module produces that qualification
through the existing T087 path, in two parts. Both must match completely.

1. **Installation conformance.** The owner names a completed
   `provider-conformance-command-v2` run of the provider port (the fixed
   private-provider suite over a *verified* installation,
   :class:`~app.extensions.provider_conformance_service.PersistentProviderConformance`).
   The run must be `matched` 4/4 under the current suite digest. Its verified-installation
   admission must still be the current one (the installation head and release sources are
   unchanged since the run).
2. **Transport conformance.** The manifest's own request surface is exercised offline
   against a local mock provider on 127.0.0.1. The mock serves the four fixed public
   vectors' supplied provider bodies (the same vectors as the installation suite). For
   every step, the exact method, request target (fixed query and cursor), the complete
   header set (the projected headers with their manifest values, the injected auth header
   carrying a fixed nonsecret conformance value, `host` and `content-length`, and nothing
   else), the request body digest (the vector oracle's projection digest), the response
   media type and the returned bytes must all equal what the manifest and the vector
   require. Only the origin differs from production: the loopback mock stands in for the
   pinned `api_origin`, which offline conformance cannot reach.

The qualification is sealed as an immutable `validation_report` record
(`provider-transport-qualification-record-v1`). Its parents are the verified installation
and the conformance result. The nonsecret gateway document
(`provider-transport-qualification-v1`) is published through the credential gateway
client (`bind_transport`) when a publisher is composed. Re-qualifying the same run and
manifest is idempotent: it returns, and republishes, the same record. A manifest whose
bytes differ from the digest the owner names is refused `conflict`. Nothing here contacts
a provider origin.
"""

from __future__ import annotations

import http.client
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, canonical_json, parse_canonical, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import _writer
from ..workers.provider_transport_manifest import (
    QUALIFICATION_SCHEMA,
    TransportManifest,
    TransportManifestError,
    claude_api_manifest,
    endpoint_request,
    host_header,
    parse_qualification,
)
from .provider_conformance_contracts import ConformanceError
from .provider_conformance_resolver import resolve_verified_admission
from .provider_conformance_vectors import SUITE_SHA256, fixed_vectors

COMMAND_SCHEMA = "provider-transport-qualification-command-v1"
RECORD_SCHEMA = "provider-transport-qualification-record-v1"
RESULT_SCHEMA = "provider-transport-conformance-result-v1"
TRANSPORT_SUITE_VERSION = "provider-transport-conformance-v1"
TRANSPORT_SUITE_SHA256 = sha256(canonical_json({
    "suite_version": TRANSPORT_SUITE_VERSION,
    "installation_suite_sha256": SUITE_SHA256,
    "checks": ["method", "target", "headers", "auth_injection", "body_sha256",
               "response_status", "response_media_type", "response_bytes"],
})).hexdigest()
CONFORMANCE_CREDENTIAL = "deeptwin-transport-conformance-v1"
_MOCK_DEADLINE_SECONDS = 5


class TransportQualificationError(ValueError):
    CODES = ("invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
             "unavailable")

    def __init__(self, code="invalid_input"):
        if code not in self.CODES:
            code = "unavailable"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _Step:
    endpoint: str
    after_id: str | None
    body: bytes
    body_sha256: str | None
    response: bytes


def _text_request_body(vector):
    """The provider request the vector's plan and input describe (the vector oracle's
    projection pins its digest, so a drift in either fails the suite loudly)."""
    plan = parse_canonical(vector.plan_bytes)
    text = vector.input_bytes[0].decode("utf-8")
    return canonical_json({"model": plan["model_id"], "max_tokens": plan["max_output_tokens"],
                           "stream": True, "messages": [{"role": "user", "content": [
                               {"type": "text", "text": text}]}]})


def _steps(vector):
    steps = []
    for index, raw in enumerate(vector.expected_projections):
        projection = parse_canonical(raw)
        endpoint = projection["endpoint"]
        body = _text_request_body(vector) if endpoint == "messages" else b""
        steps.append(_Step(endpoint, projection["after_id"], body, projection["body_sha256"],
                           vector.supplied_bodies[index]))
    return tuple(steps)


class _MockProvider:
    """A local mock provider on 127.0.0.1 serving scripted vector bodies (offline)."""

    def __init__(self):
        self.requests, self.script = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _serve(self):
                size = int(self.headers.get("content-length", "0"))
                body = self.rfile.read(size) if 0 <= size <= 8 * 1024 * 1024 else b""
                owner.requests.append((self.command, self.path,
                                       sorted((name.lower(), value)
                                              for name, value in self.headers.items()), body))
                scripted = bool(owner.script)
                media, payload = owner.script.pop(0) if scripted else ("text/plain", b"")
                self.send_response(200 if scripted else 500)
                self.send_header("content-type", media)
                self.send_header("content-length", str(len(payload)))
                self.send_header("connection", "close")
                self.end_headers()
                self.wfile.write(payload)
                self.close_connection = True

            do_GET = _serve
            do_POST = _serve

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(_MOCK_DEADLINE_SECONDS)


class _LoopbackSurface:
    """The manifest's request surface with only its origin replaced by the loopback mock,
    through the same request builder the gateway's `ProviderBinding.from_manifest` uses
    (this control-plane module imports no gateway/vault code)."""

    def __init__(self, manifest, port):
        self.host, self.port = "127.0.0.1", port
        self.auth_header = manifest.auth_header
        self.max_request_bytes = manifest.max_request_bytes
        self.max_response_bytes = manifest.max_response_bytes
        self._manifest = manifest

    def endpoint_request(self, endpoint, after_id):
        return endpoint_request(self._manifest.endpoints, self._manifest.request_headers,
                                endpoint, after_id)

    def host_header(self):
        return host_header("http", self.host, self.port)


def _exercise(binding, mock, step):
    """One manifest-bound request against the mock; True when every check matched."""
    method, target, headers, media = binding.endpoint_request(step.endpoint, step.after_id)
    if len(step.body) > binding.max_request_bytes:
        return False
    if (step.body_sha256 is None) != (step.endpoint == "models"):
        return False
    if step.body_sha256 is not None and sha256(step.body).hexdigest() != step.body_sha256:
        return False
    mock.script.append((media, step.response))
    before = len(mock.requests)
    connection = http.client.HTTPConnection(binding.host, binding.port,
                                            timeout=_MOCK_DEADLINE_SECONDS)
    try:
        # the gateway's own framing discipline: no implicit host/accept-encoding
        connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("host", binding.host_header())
        connection.putheader("content-length", str(len(step.body)))
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.putheader(binding.auth_header, CONFORMANCE_CREDENTIAL)
        connection.endheaders()
        if step.body:
            connection.send(step.body)
        response = connection.getresponse()
        payload = response.read(binding.max_response_bytes + 1)
        observed_media = response.getheader("content-type")
        status = response.status
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()
    if len(mock.requests) != before + 1:
        return False
    observed_method, observed_target, observed_headers, observed_body = mock.requests[-1]
    expected_headers = sorted([("host", binding.host_header()),
                               ("content-length", str(len(step.body))),
                               (binding.auth_header, CONFORMANCE_CREDENTIAL),
                               *headers.items()])
    return (observed_method == method and observed_target == target
            and observed_headers == expected_headers and observed_body == step.body
            and status == 200 and observed_media == media and payload == step.response
            and len(payload) <= binding.max_response_bytes)


def run_transport_conformance(manifest: TransportManifest) -> bytes:
    """Run the offline transport conformance of one manifest; its canonical result."""
    if type(manifest) is not TransportManifest:
        raise TransportQualificationError("invalid_input")
    rows = []
    with _MockProvider() as mock:
        binding = _LoopbackSurface(manifest, mock.port)
        for vector in fixed_vectors():
            steps = _steps(vector)
            try:
                matched = all(_exercise(binding, mock, step) for step in steps)
            except (TransportManifestError, ValueError, KeyError):
                matched = False
            rows.append({"vector_id": vector.vector_id, "steps": len(steps), "matched": matched})
    return canonical_json({"schema_version": RESULT_SCHEMA,
                           "suite_version": TRANSPORT_SUITE_VERSION,
                           "suite_sha256": TRANSPORT_SUITE_SHA256,
                           "manifest_sha256": manifest.manifest_sha256, "vectors": rows,
                           "completed_count": len(rows),
                           "matched_count": sum(row["matched"] for row in rows)})


def _parse_command(payload):
    if (type(payload) is not dict
            or set(payload) != {"schema_version", "command_id", "conformance_command_id",
                                "manifest_sha256"}
            or payload["schema_version"] != COMMAND_SCHEMA
            or type(payload["manifest_sha256"]) is not str or len(payload["manifest_sha256"]) != 64):
        raise TransportQualificationError("invalid_input")
    try:
        uuid_string(payload["command_id"])
        uuid_string(payload["conformance_command_id"])
    except (ValueError, TypeError):
        raise TransportQualificationError("invalid_input") from None
    return dict(payload)


class PersistentTransportQualification:
    """The owner's qualification act for the shipped provider-transport manifest."""

    def __init__(self, conformance_service, *, publisher=None, manifest_loader=claude_api_manifest):
        from .provider_conformance_service import PersistentProviderConformance

        if type(conformance_service) is not PersistentProviderConformance:
            raise TransportQualificationError("unavailable")
        if publisher is not None and not callable(publisher):
            raise TransportQualificationError("unavailable")
        self._conformance = conformance_service
        self._domain = conformance_service._domain
        self._publisher = publisher
        self._manifest_loader = manifest_loader

    def _installation_evidence(self, db, conformance_command_id):
        row = db.execute("SELECT * FROM provider_conformance_runs WHERE command_id=?",
                         (conformance_command_id,)).fetchone()
        if row is None:
            raise TransportQualificationError("not_found")
        reply = self._conformance._row_reply(row)
        if (reply.get("schema_version") != "provider-conformance-reply-v2"
                or reply["state"] != "matched" or reply["completed_count"] != 4
                or reply["matched_count"] != 4 or reply["suite_sha256"] != SUITE_SHA256):
            # only a complete match over a verified installation qualifies
            raise TransportQualificationError("conflict")
        staged = EntityRef.from_dict(reply["staged_installation_ref"])
        verified = EntityRef.from_dict(reply["verified_installation_ref"])
        try:
            admission = resolve_verified_admission(self._conformance._prepare, db, staged, verified)
        except ConformanceError:
            raise TransportQualificationError("conflict") from None
        if sha256(canonical_json(admission.as_dict())).hexdigest() != reply["admission_sha256"]:
            # the installation head or its release sources moved since the run
            raise TransportQualificationError("conflict")
        return {"command_id": conformance_command_id,
                "staged_installation_ref": staged.as_dict(),
                "verified_installation_ref": verified.as_dict(),
                "result_ref": reply["result_ref"], "suite_sha256": reply["suite_sha256"],
                "completed_count": 4, "matched_count": 4}

    @staticmethod
    def _document(record):
        content = record.body["content"]
        transport = parse_canonical(content["transport_conformance_result"].encode())
        return parse_qualification({
            "schema_version": QUALIFICATION_SCHEMA, "provider": content["provider"],
            "revision": content["qualified_at_ms"], "manifest_sha256": content["manifest_sha256"],
            "qualification_ref": record.ref.as_dict(),
            "installation_conformance": content["installation_conformance"],
            "transport_conformance": {
                "suite_sha256": transport["suite_sha256"],
                "result_sha256": sha256(content["transport_conformance_result"].encode()).hexdigest(),
                "completed_count": transport["completed_count"],
                "matched_count": transport["matched_count"]}})

    def qualify(self, authenticated_request, payload):
        """Qualify the shipped manifest from a matched verified conformance run, seal the
        record and publish the gateway document; returns the document and publication."""
        command = _parse_command(payload)
        try:
            manifest = self._manifest_loader()
        except (TransportManifestError, OSError):
            raise TransportQualificationError("unavailable") from None
        if manifest.manifest_sha256 != command["manifest_sha256"]:
            # the manifest the owner reviewed is not the one shipped (it changed)
            raise TransportQualificationError("conflict")
        record_id = str(uuid5(NAMESPACE_URL, "deeptwin:provider-transport-qualification:"
                              f"{manifest.manifest_sha256}:{command['conformance_command_id']}"))
        try:
            with _writer(), self._domain._connection(write=True) as db:
                self._conformance._authenticate(authenticated_request, db)
                installation = self._installation_evidence(db, command["conformance_command_id"])
                existing = db.execute(
                    "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND "
                    "kind='validation_report' AND id=?",
                    (self._domain._read_roots(db).genesis.id, record_id)).fetchone()
            if existing is None:
                # offline: the loopback mock only, no provider origin
                result = run_transport_conformance(manifest)
                parsed = parse_canonical(result)
                if parsed["completed_count"] != 4 or parsed["matched_count"] != 4:
                    raise TransportQualificationError("conflict")
            with _writer(), self._domain._connection(write=True) as db:
                _actor, actor_ref = self._conformance._authenticate(authenticated_request, db)
                if self._installation_evidence(db, command["conformance_command_id"]) != installation:
                    raise TransportQualificationError("conflict")
                roots = self._domain._read_roots(db)
                row = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND "
                                 "kind='validation_report' AND id=?",
                                 (roots.genesis.id, record_id)).fetchone()
                if row is not None:
                    record = self._domain._load(
                        db, EntityRef("validation_report", record_id, row["version"], row["sha256"]),
                        roots)[0]
                else:
                    now = datetime.now(UTC)
                    record = ImmutableRecord.create(
                        kind="validation_report", id=record_id, version=1,
                        created_at_utc=now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                        actor_ref=actor_ref,
                        parent_refs=(EntityRef.from_dict(installation["verified_installation_ref"]),
                                     EntityRef.from_dict(installation["result_ref"])),
                        purpose="operational", access_policy_ref=roots.access_policy,
                        retention_policy_ref=roots.retention_policy,
                        content={"schema_version": RECORD_SCHEMA, "provider": manifest.provider,
                                 "manifest_sha256": manifest.manifest_sha256,
                                 "manifest": manifest.content_bytes.decode("utf-8"),
                                 "installation_conformance": installation,
                                 "transport_conformance_result": result.decode("utf-8"),
                                 "qualified_at_ms": int(now.timestamp() * 1000)})
                    self._domain._put_in_transaction(db, record)
                document = self._document(record)
        except TransportQualificationError:
            raise
        except ConformanceError as error:
            raise TransportQualificationError(error.code) from None
        except (TransportManifestError, ValueError, TypeError, KeyError, OSError):
            raise TransportQualificationError("unavailable") from None
        published = False
        if self._publisher is not None:
            try:
                self._publisher(qualification=document)
                published = True
            except Exception:  # noqa: BLE001 - republished by re-qualifying (idempotent)
                published = False
        return {"qualification": document, "published": published}


__all__ = [
    "COMMAND_SCHEMA",
    "CONFORMANCE_CREDENTIAL",
    "TRANSPORT_SUITE_SHA256",
    "PersistentTransportQualification",
    "TransportQualificationError",
    "run_transport_conformance",
]
