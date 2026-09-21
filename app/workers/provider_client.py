"""Fixed-vector authenticated requester for one staged private provider."""

from base64 import b64decode, b64encode
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
import time
from uuid import uuid4

from ..domain.refs import canonical_json, parse_canonical
from ..extensions.provider_conformance_contracts import (
    ConformanceCapture,
    ConformanceComparison,
    ConformanceError,
    ConformanceSubject,
    parse_capture,
)
from ..extensions.provider_conformance_vectors import SUITE_SHA256, fixed_vectors
from . import broker, listener, provider_messages
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
from .extension_channel import extension_channel


REQUEST = "extension-request-v1"
RESULT = "extension-result-v1"
ARTIFACT = "extension-artifact-v1"
_LIMITS = StreamLimits(max_artifact_bytes=1048576, max_total_bytes=12 * 1048576,
                       max_chunk_bytes=16384)
_ARCHIVE_LIMIT = 1048576
_ARCHIVE_OVERHEAD = 8192


class _Stop(Exception):
    __slots__ = ("reason",)

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class _ReplayInvalid(Exception):
    """Retained flow that the requester could not have produced."""


class _ReplayObserved(Exception):
    """Authenticated received evidence that disagrees with the fixed protocol."""

    __slots__ = ("cursor",)

    def __init__(self, cursor):
        self.cursor = cursor


@dataclass(frozen=True, slots=True)
class _RunTiming:
    boot_id: str
    admitted_ms: int
    admitted_monotonic: float


_RUN_TIMING = ContextVar("provider_conformance_run_timing", default=None)


@contextmanager
def _service_timing(*, boot_id, admitted_ms, admitted_monotonic):
    timing = _RunTiming(boot_id, admitted_ms, admitted_monotonic)
    token = _RUN_TIMING.set(timing)
    try:
        yield
    finally:
        _RUN_TIMING.reset(token)


def _payload_chunks(raw):
    return [b64encode(raw[index:index + 24576]).decode("ascii")
            for index in range(0, len(raw), 24576)] or [""]


class _RecordingConnection:
    __slots__ = ("connection", "frames", "ids", "counter", "wire_bytes")

    def __init__(self, connection, counter):
        self.connection = connection
        self.frames = []
        self.ids = counter["ids"]
        self.counter = counter
        self.wire_bytes = 0

    def _record(self, direction, envelope, payload):
        frame = {"direction": direction, "message_id": envelope.message_id,
            "correlation_id": envelope.correlation_id, "message_type": envelope.message_type,
            "payload_chunks": _payload_chunks(payload)}
        archive_size = len(json.dumps(frame, ensure_ascii=False, separators=(",", ":"),
                                      sort_keys=True).encode("utf-8")) + 1
        if (self.counter["frames"] >= 256
                or self.counter["archive_bytes"] + archive_size > _ARCHIVE_LIMIT
                or self.wire_bytes + len(payload) > 12 * 1048576
                or self.counter["wire_bytes"] + len(payload) > 48 * 1048576):
            raise _Stop("observation_limit")
        if envelope.message_id in self.ids:
            raise _Stop("protocol_error")
        self.ids.add(envelope.message_id)
        self.counter["frames"] += 1
        self.counter["archive_bytes"] += archive_size
        self.wire_bytes += len(payload)
        self.counter["wire_bytes"] += len(payload)
        self.frames.append(frame)

    def write(self, **kwargs):
        envelope = type("Envelope", (), kwargs)
        # Reserve the bounded retained frame before emitting an outgoing frame.
        self._record("sent", envelope, kwargs["payload"])
        try:
            self.connection.write(**kwargs)
        except BaseException:
            frame = self.frames.pop()
            self.ids.remove(frame["message_id"])
            self.counter["frames"] -= 1
            self.counter["archive_bytes"] -= len(json.dumps(frame, ensure_ascii=False,
                separators=(",", ":"), sort_keys=True).encode("utf-8")) + 1
            self.wire_bytes -= len(kwargs["payload"])
            self.counter["wire_bytes"] -= len(kwargs["payload"])
            raise

    def read(self, **kwargs):
        frame = self.connection.read(**kwargs)
        self._record("received", frame.envelope, frame.payload)
        return frame

    def recheck(self):
        return self.connection.recheck()


def _descriptor(value, request_id, ordinal=0, count=1):
    return ArtifactDescriptor(batch_id=value["batch_id"], request_id=request_id,
        ordinal=ordinal, count=count, media_type=value["media_type"],
        declared_size=value["size"], sha256=value["sha256"])


class _OwnedSink:
    """Keep the stream primitive from replacing B's active primary during abort."""
    __slots__ = ("sink", "cleanup_error")

    def __init__(self):
        self.sink = BytesSink()
        self.cleanup_error = None

    def write(self, offset, data):
        return self.sink.write(offset, data)

    def finalize(self):
        return self.sink.finalize()

    def abort(self):
        try:
            return self.sink.abort()
        except BaseException as exc:
            if self.cleanup_error is None:
                self.cleanup_error = exc

    @property
    def value(self):
        return self.sink.value


def _receive_owned(transport, descriptors):
    sinks = []
    try:
        for _ in descriptors:
            sinks.append(_OwnedSink())
        receive_batch(transport, descriptors, sinks, limits=_LIMITS)
        return tuple(sink.value for sink in sinks)
    except BaseException:
        for sink in sinks:
            sink.abort()
        raise


def _stream(connection, announcing, descriptions, deadline, raws=None):
    descriptors = [_descriptor(value, announcing, index, len(descriptions))
                   for index, value in enumerate(descriptions)]
    transport = ConnectionStreamTransport(connection, message_type=ARTIFACT,
                                           correlation_id=announcing, deadline=deadline)
    if raws is None:
        try:
            return _receive_owned(transport, descriptors)
        except ArtifactStreamError:
            raise _Stop("protocol_error") from None
    send_batch(transport, descriptors, [BytesSource(raw) for raw in raws], limits=_LIMITS)
    return ()


def _control_write(connection, value, deadline, *, correlation=None):
    message_id = str(uuid4())
    connection.write(message_id=message_id, correlation_id=correlation, message_type=REQUEST,
                     payload=provider_messages.encode_control(value), deadline=deadline)
    connection.recheck()
    return message_id


def _control_read(connection, deadline, correlation, schema):
    frame = connection.read(deadline=deadline)
    if frame.envelope.message_type != RESULT or frame.envelope.correlation_id != correlation:
        raise _Stop("protocol_error")
    try:
        value = provider_messages.parse_control(frame.payload)
    except Exception:
        raise _Stop("protocol_error") from None
    if value["schema"] != schema:
        raise _Stop("protocol_error")
    connection.recheck()
    return frame.envelope.message_id, value


def _connection_value(connection):
    session, peer, record = connection.session, connection.peer, connection.record
    return {"connection_id": session.connection_id, "requester_boot_id": session.requester_boot_id,
        "responder_boot_id": session.responder_boot_id, "generation_id": record.generation_id,
        "listener_sha256": sha256(canonical_json(record.unsigned())).hexdigest(),
        "peer_pid": peer.pid, "peer_uid": peer.uid, "peer_gid": peer.gid}


def _identify(connection, subject, deadline):
    challenge = os.urandom(32).hex()
    request_id = _control_write(connection,
        {"schema": "provider-worker-identify-v1", "challenge": challenge}, deadline)
    _, reply = _control_read(connection, deadline, request_id, "provider-worker-identity-v1")
    expected = {"schema": "provider-worker-identity-v1", "challenge": challenge,
        "service_identity": subject.service_identity,
        "build_identity_digest": subject.build_identity_digest,
        "port_schema_set_digest": subject.port_schema_set_digest,
        "platform": subject.platform, "uid": subject.uid, "gid": subject.gid,
        "worker_profile": subject.worker_profile,
        "implemented_transforms": list(subject.implemented_transforms)}
    if reply != expected:
        raise _Stop("identity_mismatch")
    return challenge


def _fresh(counter, value):
    if value in counter["semantic_ids"]:
        raise _Stop("protocol_error")
    counter["semantic_ids"].add(value)
    return value


def _run_vector(connection, vector, deadline, guard, counter):
    def checkpoint():
        guard()
        connection.recheck()

    checkpoint()
    dialogue = _fresh(counter, str(uuid4()))
    plan_description = {"batch_id": _fresh(counter, str(uuid4())), "size": len(vector.plan_bytes),
        "sha256": sha256(vector.plan_bytes).hexdigest(), "media_type": "application/json"}
    remaining = min(30000, int(deadline.remaining() * 1000))
    if remaining <= 0:
        raise broker.DeadlineExceeded()
    start_id = _control_write(connection, {"schema": "provider-transform-start-v1",
        "dialogue_id": dialogue, "operation": vector.operation, "remaining_ms": remaining,
        "plan": plan_description}, deadline)
    _, ready = _control_read(connection, deadline, start_id, "provider-transform-ready-v1")
    if ready != {"schema": "provider-transform-ready-v1", "dialogue_id": dialogue, "phase": "plan"}:
        raise _Stop("protocol_error")
    _stream(connection, start_id, (plan_description,), deadline, (vector.plan_bytes,))
    _, ready = _control_read(connection, deadline, start_id, "provider-transform-ready-v1")
    if ready != {"schema": "provider-transform-ready-v1", "dialogue_id": dialogue, "phase": "inputs"}:
        raise _Stop("protocol_error")
    checkpoint()
    batch_id = _fresh(counter, str(uuid4())) if vector.input_bytes else None
    inputs_id = _control_write(connection, {"schema": "provider-transform-inputs-v1",
        "dialogue_id": dialogue, "batch_id": batch_id}, deadline, correlation=start_id)
    if vector.input_bytes:
        descriptions = tuple({"batch_id": batch_id, "size": len(raw),
            "sha256": sha256(raw).hexdigest(), "media_type": "text/plain"}
            for raw in vector.input_bytes)
        _stream(connection, inputs_id, descriptions, deadline, vector.input_bytes)
    checkpoint()
    for index, supplied in enumerate(vector.supplied_bodies):
        checkpoint()
        projection_id, projection = _control_read(
            connection, deadline, start_id, "provider-transform-projection-v1")
        if projection["dialogue_id"] != dialogue or projection["step"] != index + 1:
            raise _Stop("protocol_error")
        if projection["body"] is not None:
            _fresh(counter, projection["body"]["batch_id"])
        body = None if projection["body"] is None else _stream(
            connection, projection_id, (projection["body"],), deadline)[0]
        actual = canonical_json({"step": projection["step"], "endpoint": projection["endpoint"],
            "after_id": projection["after_id"],
            "body_sha256": None if body is None else sha256(body).hexdigest()})
        if actual != vector.expected_projections[index]:
            raise _Stop("protocol_error")
        media = "text/event-stream" if vector.operation == "text" else "application/json"
        response = {"batch_id": _fresh(counter, str(uuid4())), "size": len(supplied),
                    "sha256": sha256(supplied).hexdigest(), "media_type": media}
        response_id = _control_write(connection, {"schema": "provider-transform-response-v1",
            "dialogue_id": dialogue, "step": index + 1, "status": "supplied", "body": response},
            deadline, correlation=start_id)
        _stream(connection, response_id, (response,), deadline, (supplied,))
        checkpoint()
    checkpoint()
    final_id, final = _control_read(connection, deadline, start_id, "provider-transform-final-v1")
    if final["dialogue_id"] != dialogue:
        raise _Stop("protocol_error")
    _fresh(counter, final["result"]["batch_id"])
    result = _stream(connection, final_id, (final["result"],), deadline)[0]
    provider_messages.parse_result(result)
    if result != vector.expected_result_bytes:
        raise _Stop("protocol_error")
    checkpoint()


def run_fixed_suite(subject, *, deadline, guard):
    if type(subject) is not ConformanceSubject or type(deadline) is not broker.Deadline or not callable(guard):
        raise ConformanceError("invalid_input")
    root, spec = extension_channel(instance_id=subject.instance_id, slot_number=subject.slot_id)
    if spec.responder_service != subject.service_identity:
        raise ConformanceError("unavailable")
    timing = _RUN_TIMING.get()
    started_ms = time.time_ns() // 1000000 if timing is None else timing.admitted_ms
    started = time.monotonic() if timing is None else timing.admitted_monotonic
    roles = ("identify-before", *(vector.vector_id for vector in fixed_vectors()), "identify-after")
    boot = "provider-conformance-" + uuid4().hex if timing is None else timing.boot_id
    counter = {"ids": set(), "frames": 0, "wire_bytes": 0, "archive_bytes": _ARCHIVE_OVERHEAD,
               "connections": set(), "continuity": None, "semantic_ids": set()}
    attempts = []
    vectors = fixed_vectors()
    for index, role in enumerate(roles):
        raw_connection = proxy = None
        attempt = {"role": role, "connection": None, "frames": [], "failure": None}
        primary = cleanup = None
        try:
            guard()
            one = deadline.bounded(1000 if role.startswith("identify") else
                                   min(30000, max(1, int(deadline.remaining() * 1000))))
            raw_connection = listener._connect_extension_authenticated(
                root, spec, requester_boot_id=boot, deadline=one)
            connection_value = _connection_value(raw_connection)
            attempt["connection"] = connection_value
            if (connection_value["requester_boot_id"] != boot
                    or connection_value["peer_uid"] != subject.uid
                    or connection_value["peer_gid"] != subject.gid):
                raise _Stop("identity_mismatch")
            if connection_value["connection_id"] in counter["connections"]:
                raise _Stop("identity_mismatch")
            counter["connections"].add(connection_value["connection_id"])
            continuity = tuple(connection_value[name] for name in (
                "requester_boot_id", "responder_boot_id", "generation_id", "listener_sha256",
                "peer_pid", "peer_uid", "peer_gid"))
            if counter["continuity"] is None:
                counter["continuity"] = continuity
            elif counter["continuity"] != continuity:
                raise _Stop("identity_mismatch")
            proxy = _RecordingConnection(raw_connection, counter)
            guard(); proxy.recheck()
            if role == "identify-before" or role == "identify-after":
                _fresh(counter, _identify(proxy, subject, one))
            else:
                _run_vector(proxy, vectors[index - 1], one, guard, counter)
            guard(); proxy.recheck()
        except _Stop as exc:
            attempt["failure"] = exc.reason
        except ConformanceError as exc:
            attempt["failure"] = ({"source_changed": "source_changed",
                "access_denied": "owner_revoked", "unauthenticated": "owner_revoked"}
                .get(exc.code, "connection_unavailable"))
        except broker.DeadlineExceeded:
            attempt["failure"] = "deadline"
        except Exception:
            attempt["failure"] = "connection_unavailable"
        except BaseException as exc:
            primary = exc
        finally:
            if proxy is not None:
                attempt["frames"] = proxy.frames
            if raw_connection is not None:
                try:
                    raw_connection.close()
                except BaseException as exc:
                    cleanup = exc
            attempts.append(attempt)
        if primary is not None:
            raise primary
        if cleanup is not None:
            raise cleanup
        if attempt["failure"] is not None:
            break
    finished_ms = time.time_ns() // 1000000
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if elapsed_ms < 0:
        raise ConformanceError("unavailable")
    raw = canonical_json({"schema_version": "provider-conformance-observations-v1",
        "context_sha256": sha256(canonical_json(subject.as_dict())).hexdigest(),
        "suite_sha256": SUITE_SHA256, "started_ms": started_ms, "finished_ms": finished_ms,
        "elapsed_ms": elapsed_ms, "attempts": attempts})
    if len(raw) > _ARCHIVE_LIMIT:
        raise ConformanceError("unavailable")
    return parse_capture(raw)


def _frame_payload(frame):
    return b"".join(b64decode(part.encode("ascii"), validate=True) for part in frame["payload_chunks"])


class _TranscriptCursor:
    __slots__ = ("frames", "index")

    def __init__(self, frames):
        self.frames = frames
        self.index = 0

    def take(self, direction, message_type, correlation_id, payload=None):
        if self.index >= len(self.frames):
            raise _TranscriptEnd()
        frame = self.frames[self.index]
        self.index += 1
        raw = _frame_payload(frame)
        if frame["direction"] != direction:
            raise _ReplayInvalid()
        if (frame["message_type"] != message_type
                or frame["correlation_id"] != correlation_id
                or (payload is not None and raw != payload)):
            raise (_ReplayObserved(self) if direction == "received" else _ReplayInvalid())
        return frame, raw

    def control(self, direction, correlation_id):
        message_type = REQUEST if direction == "sent" else RESULT
        frame, raw = self.take(direction, message_type, correlation_id)
        try:
            return frame, provider_messages.parse_control(raw)
        except Exception:
            raise (_ReplayObserved(self) if direction == "received" else _ReplayInvalid()) from None

    def complete(self):
        if self.index != len(self.frames):
            raise _ReplayInvalid()


class _TranscriptEnd(Exception):
    pass


class _TranscriptStreamTransport:
    __slots__ = ("cursor", "correlation_id")

    def __init__(self, cursor, correlation_id):
        self.cursor = cursor
        self.correlation_id = correlation_id

    def send(self, payload):
        self.cursor.take("sent", ARTIFACT, self.correlation_id, payload)

    def receive(self):
        return self.cursor.take("received", ARTIFACT, self.correlation_id)[1]


def _replay_stream(cursor, announcing, descriptions, raws=None):
    descriptors = [_descriptor(value, announcing, index, len(descriptions))
                   for index, value in enumerate(descriptions)]
    transport = _TranscriptStreamTransport(cursor, announcing)
    if raws is None:
        try:
            return _receive_owned(transport, descriptors)
        except ArtifactStreamError:
            raise _ReplayObserved(cursor) from None
    try:
        send_batch(transport, descriptors, [BytesSource(raw) for raw in raws], limits=_LIMITS)
    except ArtifactStreamError:
        raise _ReplayInvalid() from None
    return ()


def _replay_identity(attempt, subject):
    cursor = _TranscriptCursor(attempt["frames"])
    request_frame, request = cursor.control("sent", None)
    _, response = cursor.control("received", request_frame["message_id"])
    cursor.complete()
    expected = {"schema": "provider-worker-identity-v1", "challenge": request["challenge"],
        "service_identity": subject.service_identity,
        "build_identity_digest": subject.build_identity_digest,
        "port_schema_set_digest": subject.port_schema_set_digest,
        "platform": subject.platform, "uid": subject.uid, "gid": subject.gid,
        "worker_profile": subject.worker_profile,
        "implemented_transforms": list(subject.implemented_transforms)}
    if request["schema"] != "provider-worker-identify-v1":
        raise _ReplayInvalid()
    if response != expected:
        raise _ReplayObserved(cursor)
    return request["challenge"]


def _retained_identity_matches(attempt, subject):
    try:
        _replay_identity(attempt, subject)
        return True
    except Exception:
        return False


def _replay_fresh(cursor, identifiers, value, *, received=False):
    if value in identifiers:
        # Received batch IDs are visible in an already-recorded control. Generated
        # outgoing IDs are checked before writing, so their announcing frame is impossible.
        raise _ReplayObserved(cursor) if received else _ReplayInvalid()
    identifiers.add(value)


def _replay_vector(attempt, vector, identifiers):
        cursor = _TranscriptCursor(attempt["frames"])
        start_frame, start = cursor.control("sent", None)
        if (start["schema"] != "provider-transform-start-v1"
                or start["operation"] != vector.operation
                or not 1 <= start["remaining_ms"] <= 30000
                or start["plan"] != {"batch_id": start["plan"]["batch_id"],
                    "size": len(vector.plan_bytes), "sha256": sha256(vector.plan_bytes).hexdigest(),
                    "media_type": "application/json"}):
            raise _ReplayInvalid()
        dialogue = start["dialogue_id"]
        _replay_fresh(cursor, identifiers, dialogue)
        _replay_fresh(cursor, identifiers, start["plan"]["batch_id"])
        _, ready = cursor.control("received", start_frame["message_id"])
        if ready != {"schema": "provider-transform-ready-v1", "dialogue_id": dialogue,
                     "phase": "plan"}:
            raise _ReplayObserved(cursor)
        _replay_stream(cursor, start_frame["message_id"], (start["plan"],), (vector.plan_bytes,))
        _, ready = cursor.control("received", start_frame["message_id"])
        if ready != {"schema": "provider-transform-ready-v1", "dialogue_id": dialogue,
                     "phase": "inputs"}:
            raise _ReplayObserved(cursor)
        inputs_frame, inputs = cursor.control("sent", start_frame["message_id"])
        if (inputs["schema"] != "provider-transform-inputs-v1"
                or inputs["dialogue_id"] != dialogue
                or (inputs["batch_id"] is None) != (not vector.input_bytes)):
            raise _ReplayInvalid()
        if inputs["batch_id"] is not None:
            _replay_fresh(cursor, identifiers, inputs["batch_id"])
        if vector.input_bytes:
            descriptions = tuple({"batch_id": inputs["batch_id"], "size": len(raw),
                "sha256": sha256(raw).hexdigest(), "media_type": "text/plain"}
                for raw in vector.input_bytes)
            _replay_stream(cursor, inputs_frame["message_id"], descriptions, vector.input_bytes)
        for index, expected_projection in enumerate(vector.expected_projections):
            projection_frame, projection = cursor.control("received", start_frame["message_id"])
            if (projection["schema"] != "provider-transform-projection-v1"
                    or projection["dialogue_id"] != dialogue or projection["step"] != index + 1):
                raise _ReplayObserved(cursor)
            if projection["body"] is not None:
                _replay_fresh(cursor, identifiers, projection["body"]["batch_id"], received=True)
            body = None if projection["body"] is None else _replay_stream(
                cursor, projection_frame["message_id"], (projection["body"],))[0]
            actual_projection = canonical_json({"step": projection["step"],
                "endpoint": projection["endpoint"], "after_id": projection["after_id"],
                "body_sha256": None if body is None else sha256(body).hexdigest()})
            if actual_projection != expected_projection:
                raise _ReplayObserved(cursor)
            response_frame, response = cursor.control("sent", start_frame["message_id"])
            supplied = vector.supplied_bodies[index]
            expected_media = "text/event-stream" if vector.operation == "text" else "application/json"
            if (response["schema"] != "provider-transform-response-v1"
                    or response["dialogue_id"] != dialogue or response["step"] != index + 1
                    or response["status"] != "supplied" or response["body"]["size"] != len(supplied)
                    or response["body"]["sha256"] != sha256(supplied).hexdigest()
                    or response["body"]["media_type"] != expected_media):
                raise _ReplayInvalid()
            _replay_fresh(cursor, identifiers, response["body"]["batch_id"])
            _replay_stream(cursor, response_frame["message_id"], (response["body"],), (supplied,))
        final_frame, final = cursor.control("received", start_frame["message_id"])
        if final["schema"] != "provider-transform-final-v1" or final["dialogue_id"] != dialogue:
            raise _ReplayObserved(cursor)
        _replay_fresh(cursor, identifiers, final["result"]["batch_id"], received=True)
        result = _replay_stream(cursor, final_frame["message_id"], (final["result"],))[0]
        cursor.complete()
        if result != vector.expected_result_bytes:
            raise _ReplayObserved(cursor)


def _retained_vector_matches(attempt, vector):
    try:
        _replay_vector(attempt, vector, set())
        return True
    except Exception:
        return False


def _replay_status(callback, *args):
    try:
        return "complete", callback(*args)
    except _TranscriptEnd:
        return "prefix", None
    except _ReplayObserved as exc:
        if exc.cursor.index != len(exc.cursor.frames):
            return "invalid", None
        return "mismatch", None
    except _ReplayInvalid:
        return "invalid", None
    except Exception:
        return "invalid", None


def compare_capture(subject, capture):
    if type(subject) is not ConformanceSubject or type(capture) is not ConformanceCapture:
        raise ConformanceError("invalid_input")
    value = parse_canonical(capture.content_bytes)
    expected_context = sha256(canonical_json(subject.as_dict())).hexdigest()
    if value["context_sha256"] != expected_context or value["suite_sha256"] != SUITE_SHA256:
        return ConformanceComparison("mismatch", "compared", tuple(
            (vector.vector_id, "not_observed") for vector in fixed_vectors()), ())
    attempts = value["attempts"]
    identifies = [item for item in attempts if item["role"] in ("identify-before", "identify-after")]
    connections = [item["connection"] for item in attempts if item["connection"] is not None]
    continuity_names = ("requester_boot_id", "responder_boot_id", "generation_id",
        "listener_sha256", "peer_pid", "peer_uid", "peer_gid")
    failure = next((item["failure"] for item in attempts if item["failure"] is not None), None)

    def require_stopping_boundary(index):
        if index != len(attempts) - 1 or attempts[index]["failure"] is None:
            raise ConformanceError("unavailable")

    identity_mismatch = False
    connection_ids = set()
    frame_ids = set()
    continuity = None
    for index, attempt in enumerate(attempts):
        connection = attempt["connection"]
        violated = False
        if connection is not None:
            current = tuple(connection[name] for name in continuity_names)
            violated = (connection["peer_uid"] != subject.uid
                or connection["peer_gid"] != subject.gid
                or connection["connection_id"] in connection_ids
                or continuity is not None and current != continuity)
            connection_ids.add(connection["connection_id"])
            if continuity is None:
                continuity = current
        if violated:
            require_stopping_boundary(index)
            # Acquisition identity is checked before the recording proxy exists.
            if attempt["frames"]:
                raise ConformanceError("unavailable")
            identity_mismatch = True
        for frame in attempt["frames"]:
            # The recorder refuses repeated IDs before appending, in either direction.
            if frame["message_id"] in frame_ids:
                raise ConformanceError("unavailable")
            frame_ids.add(frame["message_id"])
    identity_ids = set()
    for attempt in identifies:
        index = attempts.index(attempt)
        status, challenge = _replay_status(_replay_identity, attempt, subject)
        if status == "invalid":
            raise ConformanceError("unavailable")
        if status == "mismatch":
            require_stopping_boundary(index)
            identity_mismatch = True
        if status == "complete":
            if challenge in identity_ids:
                require_stopping_boundary(index)
                identity_mismatch = True
            identity_ids.add(challenge)
        elif attempt["failure"] is None:
            raise ConformanceError("unavailable")
    outcomes = []
    protocol_mismatch = False
    semantic_ids = set()
    for vector in fixed_vectors():
        attempt = next((item for item in attempts if item["role"] == vector.vector_id), None)
        if attempt is None:
            outcomes.append((vector.vector_id, "not_observed"))
            continue
        index = attempts.index(attempt)
        status, _ = _replay_status(_replay_vector, attempt, vector, semantic_ids)
        if status == "complete":
            outcomes.append((vector.vector_id, "matched"))
        elif status == "prefix" and attempt["failure"] is not None:
            outcomes.append((vector.vector_id, "not_observed"))
        elif status == "invalid" or status == "prefix":
            raise ConformanceError("unavailable")
        else:
            require_stopping_boundary(index)
            outcomes.append((vector.vector_id, "mismatch"))
            protocol_mismatch = True
    covered = tuple(vector_id for vector_id, result in outcomes if result == "matched")
    if identity_mismatch:
        return ConformanceComparison("mismatch", "identity_mismatch", tuple(outcomes), covered)
    if protocol_mismatch:
        return ConformanceComparison("mismatch", "compared", tuple(outcomes), covered)
    if failure is not None:
        return ConformanceComparison("incomplete", failure, tuple(outcomes), covered)
    if len(attempts) != 6 or len(identifies) != 2 or len(connections) != 6:
        raise ConformanceError("unavailable")
    if all(result == "matched" for _, result in outcomes):
        return ConformanceComparison("matched", "compared", tuple(outcomes), covered)
    if any(result == "mismatch" for _, result in outcomes):
        return ConformanceComparison("mismatch", "compared", tuple(outcomes), covered)
    return ConformanceComparison("incomplete", "protocol_error", tuple(outcomes), covered)
