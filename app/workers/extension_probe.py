"""Worker-private stage probe service (Task 25 slice 3; T087 worker startup
over the T018-foundation transport; contracts/extension-worker-probe.md
§3–§5).

One service owns one process boot ID, one Task 23 metadata source and one
listener. The source is opened before the listener is bound or advertised,
so a worker whose fixed files are not measurable never publishes readiness.
`serve_one(deadline)` accepts one authenticated probe connection under every
listener fence, answers at most two probes — distinct message ids and
nonces, an identical request/receipt digest pair — with replies built from
an actual `read_current` per probe (readiness never substitutes), rechecks
the fences before the first read and after each reply, and closes after the
second reply. An execute connection (the first frame's schema is
`extension-execute-v1`) answers exactly one request through the private
router's code-owned operation table (`_OPERATIONS`: `status` since the T087
execute slice, `describe_tools` since the tool-table slice, `invoke_tool` over
the two-tool table — `text_profile`, `text_normalize` — since the first-tool
and reverse-leg slices) and closes; the probe reply's `registered_operations` is that
table's exact key set. No placeholder handler exists.

A reply is a self-reported observation over one connection; the service
compares nothing to an expected tuple, admits nothing and proves nothing
about life after the response. Errors are closed: fixed messages, never a
digest, nonce or message id. Nothing here imports `app.api`, `app.static`
or `app.server`.
"""

from __future__ import annotations

import re
import secrets
import threading
import unicodedata
from hashlib import sha256
from types import MappingProxyType
from typing import Self
from uuid import uuid4

from ..domain.refs import DomainContractError, canonical_json, uuid_string
from ..extensions.lineage_contracts import LineageContractError
from ..extensions.port_contracts import OPERATION_CONTRACTS
from ..extensions.tool_input_contracts import (
    ToolArtifactInputContract,
    ToolInputMismatch,
    check_tool_inputs,
)
from . import broker, ipc_root, listener
from . import extension_metadata as em
from .artifact_stream import (
    ArtifactDescriptor,
    ArtifactStreamError,
    BytesSink,
    BytesSource,
    StreamLimits,
    receive_batch,
    send_batch,
)
from .artifact_stream_transport import ConnectionStreamTransport
from .extension_channel import ExtensionChannelError, extension_channel
from .extension_execute_messages import (
    MAX_INPUT_BYTES,
    ExecuteMessageError,
    encode_execute_reply,
    parse_execute_request,
    peek_schema,
)
from .extension_execute_messages import (
    REQUEST_SCHEMA as EXECUTE_SCHEMA,
)
from .extension_probe_messages import (
    PORT_CONTRACT_VERSION,
    ProbeMessageError,
    encode_probe_reply,
    parse_probe_request,
)
from .extension_probe_messages import (
    REQUEST_SCHEMA as PROBE_SCHEMA,
)

REQUEST_TYPE = "extension-request-v1"
RESULT_TYPE = "extension-result-v1"
MAX_PROBES = 2
MAX_EXECUTES = 1  # one execute request per accepted connection
_CONNECTION_MS = 2_000  # contract §4: worker accepted connection
_READ_MS = 500  # contract §4: metadata reads
_BOOT_ID_BYTES = 32


class ProbeServiceError(RuntimeError):
    """Closed error family; every subclass carries one fixed message."""

    code = "probe service error"

    def __init__(self, *_ignored: object) -> None:
        # copy/pickle re-invoke __init__ with the stored args: accept and drop them
        super().__init__(self.code)


class ProbeServiceBusy(ProbeServiceError):
    code = "probe service busy"


class ProbeServiceClosed(ProbeServiceError):
    code = "probe service closed"


_SANITIZED = (
    ProbeServiceError,
    ArtifactStreamError,
    listener.ListenerError,
    broker.BrokerError,
    ipc_root.IpcRootError,
    em.WorkerMetadataError,
    ProbeMessageError,
    ExecuteMessageError,
    DomainContractError,
    LineageContractError,
    OSError,
)

_ZERO_USAGE = {
    "model_calls": 0, "tool_calls": 0, "node_visits": 1, "loop_rounds": 0,
    "output_bytes": 0, "candidates": 0, "api_microunits": None,
}


# the artifact leg's admission limits: the ports contract's input ceiling, in
# owned in-memory sinks (the worker's root is read-only; no scratch volume)
EXECUTE_STREAM_LIMITS = StreamLimits(max_artifact_bytes=MAX_INPUT_BYTES,
                                     max_total_bytes=MAX_INPUT_BYTES)
ARTIFACT_TYPE = "extension-artifact-v1"


def _status_operation(service: WorkerProbeService, request, deadline, inputs) -> dict:
    """`status` (tool-port-v1): the worker's own reading — the same actual
    measurement the probe reports — as the operation's output."""

    reading = service._source.read_current(deadline=deadline.bounded(_READ_MS))
    identity = reading.build_identity
    output = {
        "service_identity": service._listener.spec.responder_service,
        "component": {
            "build_identity_digest": identity.digest,
            "port_contract_version": identity.as_dict()["port_contract_version"],
            "port_schema_set_digest": identity.schema_set_digest,
        },
        "runtime": {
            "platform": reading.platform,
            "uid": reading.uid,
            "gid": reading.gid,
            "registered_operations": list(service._router.operations()),
        },
    }
    return {
        "outcome": "succeeded", "usage_finality": "final",
        "remote_terminal_observed": "succeeded", "reason_code": "provider_terminal",
        "usage": {**_ZERO_USAGE, "output_bytes": len(canonical_json(output))},
        "output": output,
    }


# the first real tool: `text_profile` reads exactly one streamed `document_source`
# text/plain artifact (strict UTF-8) and returns its byte/character/line/word
# counts and digest — a deterministic read-effect reading, no arguments
TEXT_PROFILE_ARGUMENT_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {}}
TEXT_PROFILE_RESULT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["byte_count", "char_count", "line_count", "word_count", "sha256", "utf8"],
    "properties": {
        "byte_count": {"type": "integer", "minimum": 0}, "char_count": {"type": "integer", "minimum": 0},
        "line_count": {"type": "integer", "minimum": 0}, "word_count": {"type": "integer", "minimum": 0},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "utf8": {"const": True},
    },
}
TEXT_PROFILE_ENTRY = MappingProxyType({
    "tool_id": "text_profile", "version": "1.0.0",
    "argument_schema_sha256": sha256(canonical_json(TEXT_PROFILE_ARGUMENT_SCHEMA)).hexdigest(),
    "result_schema_sha256": sha256(canonical_json(TEXT_PROFILE_RESULT_SCHEMA)).hexdigest(),
    "effect_class": "read", "artifact_roles": ("document_source",),
})
# exactly one `document_source` text/plain input, no selector: the tool's declared
# ToolArtifactInputContractV1 (extension-ports.md §3.9 T-tool), as this worker states it
_TEXT_DOCUMENT_INPUT = ToolArtifactInputContract.bounded(
    min_items=1, max_items=1, role="document_source", allowed_media_types=("text/plain",),
    selector_policy="forbidden",
)

# the second real tool: `text_normalize` derives a normalized text (NFC, LF line
# endings, a leading BOM removed, nothing else changed) from exactly one streamed
# `document_source` text/plain artifact and returns it as its output artifact
# (`normalized_text`, text/plain) over the reverse leg; a deterministic reading
# with no external effect — the derived artifact is sealed by control
TEXT_NORMALIZE_RESULT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["byte_count_in", "byte_count_out", "changed", "sha256_in", "sha256_out"],
    "properties": {
        "byte_count_in": {"type": "integer", "minimum": 0}, "byte_count_out": {"type": "integer", "minimum": 0},
        "changed": {"type": "boolean"},
        "sha256_in": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "sha256_out": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}
TEXT_NORMALIZE_ENTRY = MappingProxyType({
    "tool_id": "text_normalize", "version": "1.0.0",
    "argument_schema_sha256": sha256(canonical_json(TEXT_PROFILE_ARGUMENT_SCHEMA)).hexdigest(),
    "result_schema_sha256": sha256(canonical_json(TEXT_NORMALIZE_RESULT_SCHEMA)).hexdigest(),
    "effect_class": "read", "artifact_roles": ("document_source", "normalized_text"),
})
_TEXT_NORMALIZE_OUTPUT = ("normalized_text", "text/plain")
# what each tool takes: its declared input contract (count, role, media, selector);
# control declares its own table and the two are pinned equal by test
TOOL_INPUT_CONTRACTS = MappingProxyType({
    ("text_profile", "1.0.0"): _TEXT_DOCUMENT_INPUT,
    ("text_normalize", "1.0.0"): _TEXT_DOCUMENT_INPUT,
})

# the code-owned tool table of this worker (tool-port-v1 `describe_tools`
# entries, identifier order): fixed at import — never a copy of the port
# catalogue, never a placeholder
_TOOLS: tuple[MappingProxyType, ...] = (TEXT_NORMALIZE_ENTRY, TEXT_PROFILE_ENTRY)


def tool_descriptions() -> list[dict]:
    """The table as `describe_tools` describes it: one plain wire entry per tool."""

    return [{**dict(entry), "artifact_roles": list(entry["artifact_roles"])} for entry in _TOOLS]


def _tool_contract_admits(request) -> bool:
    """Whether an `invoke_tool` request names a tool of the table and declares
    exactly the inputs that tool's contract takes (count, role, media; the wire
    names no selector) — re-checked here, before any artifact byte is read,
    whatever control already checked."""

    if request.tool is None:
        return False
    contract = TOOL_INPUT_CONTRACTS.get((request.tool.tool_id, request.tool.version))
    if contract is None:
        return False
    try:
        check_tool_inputs(contract, ((item.role, item.media_type, None) for item in request.artifact_inputs))
    except ToolInputMismatch:
        return False
    return True


_ASCII_WHITESPACE = re.compile(r"[ \t\n\r\f\v]+")


def _text_profile(raw: bytes) -> dict | None:
    """The definitions a non-Python worker can repeat under the same result schema
    digest: `byte_count` = the bytes; `char_count` = Unicode code points (a BOM is
    kept and counted); `line_count` = "\\n"-terminated segments plus one final
    unterminated segment (no other separator breaks a line); `word_count` = runs
    between ASCII whitespace (space, tab, LF, CR, FF, VT); `sha256` = the bytes'."""

    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return None
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    words = len([run for run in _ASCII_WHITESPACE.split(text) if run])
    return {
        "byte_count": len(raw), "char_count": len(text), "line_count": lines,
        "word_count": words, "sha256": sha256(raw).hexdigest(), "utf8": True,
    }


def _text_normalize(raw: bytes) -> tuple[bytes, bool] | None:
    """NFC; CRLF and a lone CR become LF; one leading BOM is removed; nothing else
    changes. Returns the derived bytes and whether they differ from the input."""

    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return None
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    derived = unicodedata.normalize("NFC", text).encode("utf-8")
    return derived, derived != raw


def _tool_failed(reason_code: str, tool_calls: int) -> dict:
    return {
        "outcome": "failed", "usage_finality": "final",
        "remote_terminal_observed": "failed", "reason_code": reason_code,
        "usage": {**_ZERO_USAGE, "tool_calls": tool_calls}, "output": None,
    }


def _invoke_tool_operation(service: WorkerProbeService, request, deadline, inputs) -> dict:
    """`invoke_tool` (tool-port-v1, class C, effect from the tool): runs the named
    tool of the table over the admitted inputs; the reply carries the tool's own
    result and binds its output artifacts, which travel as an offered batch before
    the reply (`artifacts` here: the bindings and bytes the serve loop streams);
    control seals both. Usage: one tool call; the reply bytes plus the artifact
    bytes as the output."""

    if not _tool_contract_admits(request) or len(inputs) != 1:
        return _tool_failed("validation_failed", 0)
    _declaration, raw = inputs[0]
    if request.tool.tool_id == "text_profile":
        result = _text_profile(raw)
        if result is None:
            # the bytes were read (the call happened) but are not a text: the tool's own failure
            return _tool_failed("provider_terminal", 1)
        output = {"tool_id": TEXT_PROFILE_ENTRY["tool_id"], "version": TEXT_PROFILE_ENTRY["version"],
                  "result": result, "artifacts": []}
        produced = ()
    else:
        normalized = _text_normalize(raw)
        if normalized is None:
            return _tool_failed("provider_terminal", 1)
        derived, changed = normalized
        if len(derived) > MAX_INPUT_BYTES:
            # NFC can triple UTF-8 bytes: a legal input under the ceiling may derive an
            # output the reply cannot carry — the tool's own typed failure, never no answer
            return _tool_failed("provider_terminal", 1)
        binding = {"ordinal": 0, "role": _TEXT_NORMALIZE_OUTPUT[0], "media_type": _TEXT_NORMALIZE_OUTPUT[1],
                   "declared_size": len(derived), "sha256": sha256(derived).hexdigest()}
        output = {"tool_id": TEXT_NORMALIZE_ENTRY["tool_id"], "version": TEXT_NORMALIZE_ENTRY["version"],
                  "result": {"byte_count_in": len(raw), "byte_count_out": len(derived), "changed": changed,
                             "sha256_in": sha256(raw).hexdigest(), "sha256_out": binding["sha256"]},
                  "artifacts": [binding]}
        produced = ((binding, derived),)
    return {
        "outcome": "succeeded", "usage_finality": "final",
        "remote_terminal_observed": "succeeded", "reason_code": "provider_terminal",
        "usage": {**_ZERO_USAGE, "tool_calls": 1,
                  "output_bytes": len(canonical_json(output)) + sum(len(raw) for _, raw in produced)},
        "output": output, "artifacts": produced,
    }


def _describe_tools_operation(service: WorkerProbeService, request, deadline, inputs) -> dict:
    """`describe_tools` (tool-port-v1, query class, read effect): the tools this
    worker actually offers, from its code-owned table; the execute grammar carries
    no selection yet, so the whole table is described."""

    output = {"tools": tool_descriptions()}
    return {
        "outcome": "succeeded", "usage_finality": "final",
        "remote_terminal_observed": "succeeded", "reason_code": "provider_terminal",
        "usage": {**_ZERO_USAGE, "output_bytes": len(canonical_json(output))},
        "output": output,
    }


# the code-owned semantic registry of this worker: exact port operations only
_OPERATIONS: MappingProxyType[str, object] = MappingProxyType({
    "status": _status_operation,
    "describe_tools": _describe_tools_operation,
    "invoke_tool": _invoke_tool_operation,
})


class _Router:
    """The worker's private router over the code-owned operation table. There
    is no registration surface: the table is fixed at import, keyed by
    tool-port-v1 operation names, and the probe reply reports its exact key
    set. An unregistered operation is a typed refusal, never a placeholder."""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        self._handlers: MappingProxyType[str, object] = _OPERATIONS

    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def admits_inputs(self, request) -> bool:
        """Whether this request's declared artifact inputs are admissible before a
        single artifact frame is read: the operation must be registered and its port
        contract's request artifact profile must take request artifacts (profile `E`
        takes none — `status` and `describe_tools` today)."""

        if not request.artifact_inputs:
            return True
        if request.operation not in self._handlers:
            return False
        profile = OPERATION_CONTRACTS[(PORT_CONTRACT_VERSION, request.operation)]
        if profile.request_artifact_profile == "E":
            return False
        # a tool call streams only what the named tool takes (its input contract)
        return request.operation != "invoke_tool" or _tool_contract_admits(request)

    def execute(self, service: WorkerProbeService, request, deadline, inputs=()) -> dict:
        handler = self._handlers.get(request.operation)
        if handler is None or not self.admits_inputs(request):
            return {
                "outcome": "failed", "usage_finality": "final",
                "remote_terminal_observed": "failed", "reason_code": "validation_failed",
                "usage": dict(_ZERO_USAGE), "output": None,
            }
        return handler(service, request, deadline, inputs)

    def __reduce__(self) -> object:
        raise TypeError("the worker router is not serializable")


class WorkerProbeService:
    """One boot ID, one metadata source, one listener; serves one connection
    at a time. Nonconstructible, uncopyable, unserializable."""

    __slots__ = ("_closed", "_listener", "_lock", "_router", "_source")

    def __init__(self) -> None:
        raise TypeError("a probe service is opened with open_worker_probe_service")

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def listener(self) -> listener.WorkerListener:
        """The owned listener; its `spec.responder_service` is the reply's
        service identity, so it cannot be rebound from outside."""

        return self._listener

    def serve_one(self, deadline: broker.Deadline) -> int:
        """Accept and answer one connection; returns the number of probes
        answered (1 when the requester ends the connection after its first
        reply, 2 when the service closes it after the second). The accept
        waits under the caller's deadline; the accepted connection lives in
        its own window from the transport accept, handshake included. Any
        rule violation closes the connection with the closed error; a
        poisoned metadata source, or a listener that no longer verifies
        against its own record, closes the whole service."""

        if type(deadline) is not broker.Deadline:
            raise ProbeServiceError()
        if not self._lock.acquire(blocking=False):
            raise ProbeServiceBusy()
        try:
            if self._closed:
                raise ProbeServiceClosed()
            try:
                connection = listener._accept_extension_authenticated(
                    self._listener, deadline=deadline, connection_ms=_CONNECTION_MS
                )
                try:
                    return self._serve(connection, connection.deadline)
                finally:
                    connection.close()
            except BaseException as error:
                if self._source.closed or (
                    isinstance(error, listener.ListenerError)
                    and not self._listener_verifies()
                ):
                    # integrity or unavailability poisoned the source, or the
                    # listener's own record/socket is gone: neither can be
                    # restored in this process, so the service cannot answer
                    # truthfully again and the entrypoint must not spin on it
                    self._close_locked(suppress=True)
                if isinstance(error, _SANITIZED):
                    raise ProbeServiceError() from None
                raise
        finally:
            self._lock.release()

    def _listener_verifies(self) -> bool:
        """Does the listener still verify against the record, readiness and
        socket identities it published? The same comparison the accept makes."""

        worker = self._listener
        try:
            generation = ipc_root.acquire_generation(worker.root_spec)
        except (ipc_root.IpcRootError, OSError):
            return False
        try:
            record, readiness, socket_identity = listener._verify_record(
                generation, worker.root_spec, worker.spec
            )
            return (
                record == worker.record
                and readiness == worker._readiness_identity
                and socket_identity == worker._socket_identity
            )
        except (listener.ListenerError, ipc_root.IpcRootError, OSError):
            return False
        finally:
            generation.close()

    def _serve(self, connection: listener.ExtensionConnection,
               deadline: broker.Deadline) -> int:
        seen_ids: set[str] = set()
        nonces: set[bytes] = set()
        digests: tuple[str, str] | None = None
        answered = 0
        connection.recheck()
        # the first authenticated application frame selects the mode by its
        # exact request schema (contract §3): probe or execute, never both
        first = connection.read(deadline=deadline)
        if peek_schema(first.payload) == EXECUTE_SCHEMA:
            return self._serve_execute(connection, first, deadline)
        while answered < MAX_PROBES:
            if first is not None:
                frame, first = first, None
            else:
                try:
                    frame = connection.read(deadline=deadline)
                except broker.TransportClosed:
                    # the requester ended the connection after a reply; a
                    # truncated later request is indistinguishable and is
                    # equally the requester's end of the exchange
                    return answered
            envelope = frame.envelope
            if envelope.message_type != REQUEST_TYPE or envelope.correlation_id is not None:
                raise ProbeServiceError()
            message_id = uuid_string(envelope.message_id)  # the framing admits nil
            if message_id in seen_ids:
                raise ProbeServiceError()
            seen_ids.add(message_id)
            if peek_schema(frame.payload) != PROBE_SCHEMA:
                raise ProbeServiceError()  # the mode was selected by the first frame
            request = parse_probe_request(frame.payload)
            pair = (request.request_blob_sha256, request.receipt_blob_sha256)
            if digests is None:
                digests = pair
            elif pair != digests:
                raise ProbeServiceError()
            if request.challenge in nonces:
                raise ProbeServiceError()
            nonces.add(request.challenge)
            # an actual measurement per probe; the source poisons itself on drift
            reading = self._source.read_current(deadline=deadline.bounded(_READ_MS))
            identity = reading.build_identity
            reply_id = str(uuid4())
            while reply_id in seen_ids:
                reply_id = str(uuid4())
            payload = encode_probe_reply(
                request_blob_sha256=request.request_blob_sha256,
                receipt_blob_sha256=request.receipt_blob_sha256,
                challenge=request.challenge,
                service_identity=self._listener.spec.responder_service,
                build_identity_digest=identity.digest,
                port_contract_version=identity.as_dict()["port_contract_version"],
                port_schema_set_digest=identity.schema_set_digest,
                platform=reading.platform,
                uid=reading.uid,
                gid=reading.gid,
                registered_operations=self._router.operations(),
            )
            connection.write(
                message_id=reply_id,
                correlation_id=message_id,
                message_type=RESULT_TYPE,
                payload=payload,
                deadline=deadline,
            )
            seen_ids.add(reply_id)
            answered += 1
            connection.recheck()
        return answered

    def _serve_execute(self, connection: listener.ExtensionConnection, frame,
                       deadline: broker.Deadline) -> int:
        """Execute mode: exactly one request, one reply, then the worker closes."""

        envelope = frame.envelope
        if envelope.message_type != REQUEST_TYPE or envelope.correlation_id is not None:
            raise ProbeServiceError()
        message_id = uuid_string(envelope.message_id)
        request = parse_execute_request(frame.payload)
        inputs = ()
        if request.artifact_inputs and self._router.admits_inputs(request):
            # the declared batch follows the request on the channel's artifact type;
            # a stream violation is terminal — the connection closes without a reply
            # and the operation never runs (control records an unknown outcome).
            # The descriptor build stays inside the sanitizer: the domain admits any
            # non-nil canonical UUID as a message id, the stream's grammar only a
            # versioned one
            try:
                descriptors = request.artifact_descriptors(message_id)
                sinks = [BytesSink() for _ in descriptors]
                transport = ConnectionStreamTransport(
                    connection, message_type=ARTIFACT_TYPE, correlation_id=message_id,
                    deadline=deadline,
                )
                receive_batch(transport, descriptors, sinks, limits=EXECUTE_STREAM_LIMITS)
            except ArtifactStreamError:
                raise ProbeServiceError() from None
            inputs = tuple(zip(request.artifact_inputs, [sink.value for sink in sinks], strict=True))
        result = dict(self._router.execute(self, request, deadline, inputs))
        produced = result.pop("artifacts", ())
        reply_id = str(uuid4())
        while reply_id == message_id:
            reply_id = str(uuid4())
        payload = encode_execute_reply(
            attempt_id=request.attempt_id, operation=request.operation,
            challenge=request.challenge, **result,
        )
        if produced:
            # the reverse leg: the tool's output artifacts go as an offered batch on
            # the artifact type, correlated to the request, before the reply frame
            batch_id = str(uuid4())
            descriptors = [
                ArtifactDescriptor(batch_id=batch_id, request_id=message_id, ordinal=index,
                                   count=len(produced), media_type=binding["media_type"],
                                   declared_size=len(raw), sha256=sha256(raw).hexdigest())
                for index, (binding, raw) in enumerate(produced)
            ]
            try:
                send_batch(
                    ConnectionStreamTransport(connection, message_type=ARTIFACT_TYPE,
                                              correlation_id=message_id, deadline=deadline),
                    descriptors, [BytesSource(raw) for _, raw in produced], limits=EXECUTE_STREAM_LIMITS,
                )
            except ArtifactStreamError:
                raise ProbeServiceError() from None
        connection.write(
            message_id=reply_id,
            correlation_id=message_id,
            message_type=RESULT_TYPE,
            payload=payload,
            deadline=deadline,
        )
        connection.recheck()
        return MAX_EXECUTES

    def close(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise ProbeServiceBusy()
        try:
            self._close_locked(suppress=False)
        finally:
            self._lock.release()

    def _close_locked(self, *, suppress: bool) -> None:
        if self._closed:
            return
        self._closed = True
        violation = False
        try:
            self._listener.close()
        except listener.ListenerError:
            violation = True
        finally:
            try:
                self._source.close()
            except em.WorkerMetadataError:
                violation = True
        if violation and not suppress:
            raise ProbeServiceError()

    def __enter__(self) -> Self:
        if self._closed:
            raise ProbeServiceClosed()
        return self

    def __exit__(self, _kind: object, value: object, _traceback: object) -> None:
        try:
            self.close()
        except ProbeServiceError:
            # never replace an exception that is already propagating
            if value is None:
                raise

    def __repr__(self) -> str:
        return f"WorkerProbeService(closed={self._closed!r})"

    def __copy__(self) -> object:
        raise TypeError("a probe service cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("a probe service cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("a probe service cannot be serialized")


def open_worker_probe_service(*, instance_id, slot_number) -> WorkerProbeService:
    """Derive the slot's channel, open the metadata source, then bind the
    listener under a fresh process boot ID. Every failure after the source
    was opened releases the source (and the listener, once bound)."""

    try:
        root, spec = extension_channel(instance_id=instance_id, slot_number=slot_number)
    except ExtensionChannelError:
        raise ProbeServiceError() from None
    try:
        source = em.open_worker_metadata_source()
    except em.WorkerMetadataError:
        raise ProbeServiceError() from None
    worker: listener.WorkerListener | None = None
    try:
        worker = listener.bind_worker_listener(
            root, spec, responder_boot_id=secrets.token_hex(_BOOT_ID_BYTES)
        )
        service = object.__new__(WorkerProbeService)
        service._lock = threading.Lock()
        service._closed = False
        service._router = _Router()
        service._source = source
        service._listener = worker
        return service
    except BaseException as error:
        if worker is not None:
            try:
                worker.close()
            except listener.ListenerError:
                pass
        try:
            source.close()
        except em.WorkerMetadataError:
            pass
        if isinstance(error, _SANITIZED):
            raise ProbeServiceError() from None
        raise
