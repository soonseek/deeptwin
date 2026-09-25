"""One-shot provider send state machine; construction is intentionally unregistered."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from queue import Empty, Queue
from uuid import uuid4

from ..domain.refs import canonical_json
from . import broker
from .artifact_stream import (
    ArtifactDescriptor,
    BytesSink,
    BytesSource,
    StreamLimits,
    receive_batch,
    send_batch,
)
from .credential_channel import decode_op, encode_op
from .listener import ListenerError
from .provider_gateway import CredentialedProviderTransport, GatewayError
from .provider_send_messages import (
    GatewayExchangeLease,
    ProviderSendCancellation,
    ProviderSendError,
    ProviderSendObservation,
    ProviderSendPrepare,
    failure_class,
    prepare_from_header,
)

_REQUEST, _RESULT = "credential_op", "credential_result"
_STREAM_LIMITS = StreamLimits(max_artifact_bytes=1_048_576,
                              max_total_bytes=1_048_576, max_chunk_bytes=16_384)


def _control(payload):
    if type(payload) is not bytes or len(payload) > 16_384:
        raise ProviderSendError("provider-send application control exceeds 16KiB")
    return decode_op(payload)


def _sequence(value, expected):
    return type(value) is int and value == expected


class _GatewayStreamTransport:
    """Artifact frames are asymmetric: gateway receives op and sends result frames.
    Over the private connection surface: the owner or the raw adapter alike."""
    def __init__(self, connection, correlation_id, deadline, *, service=None,
                 lease=None, dialogue_id=None, sequence=None):
        self.connection = connection
        self.correlation_id, self.deadline = correlation_id, deadline
        self.service, self.lease = service, lease
        self.dialogue_id, self.sequence = dialogue_id, sequence

    def send(self, payload):
        self.connection.write(message_id=str(uuid4()), correlation_id=self.correlation_id,
                              message_type=_RESULT, payload=payload, deadline=self.deadline)

    def receive(self):
        while True:
            frame = self.connection.read(deadline=self.deadline)
            if (frame.envelope.message_type != _REQUEST
                    or frame.envelope.correlation_id != self.correlation_id):
                raise ProviderSendError("stream frame is not phase-bound")
            if self.service is None:
                return frame.payload
            value = _control(frame.payload)
            if (type(value) is dict
                    and value.get("schema") == "provider-send-cancel-v1"):
                expected = {"schema", "dialogue_id", "seq", "exchange_id", "reason"}
                if (set(value) != expected or value["dialogue_id"] != self.dialogue_id
                        or not _sequence(value["seq"], self.sequence["core"])
                        or value["exchange_id"] != self.lease.exchange_id):
                    raise ProviderSendError("result-stream cancellation is not bound")
                self.sequence["core"] += 1
                cancelled = self.service.cancel(self.lease.exchange_id, value["reason"])
                self.connection.write(message_id=str(uuid4()),
                    correlation_id=self.correlation_id, message_type=_RESULT,
                    payload=encode_op({"schema": "provider-send-cancelled-v1",
                        "dialogue_id": self.dialogue_id,
                        "seq": self.sequence["gateway"],
                        "exchange_id": cancelled.exchange_id,
                        "accepted": cancelled.accepted, "phase": cancelled.phase}),
                    deadline=self.deadline)
                self.sequence["gateway"] += 1
                continue
            return frame.payload


class ProviderSendService:
    __slots__ = ("_transport", "_lock", "_pending", "_states", "_identity", "_usable")

    def __init__(self, transport: CredentialedProviderTransport):
        if type(transport) is not CredentialedProviderTransport:
            raise ProviderSendError("exact provider transport required")
        self._transport = transport
        self._lock = threading.Lock()
        self._pending = {}
        self._states = {}
        self._identity = object()
        self._usable = True

    @property
    def usable(self) -> bool:
        """False once an HTTP thread outlived its cleanup deadline: the service refuses
        further dialogues rather than start beside the retained thread."""
        return self._usable

    @property
    def vault(self):
        """The exact vault the transport delivers custody from (borrowed, never closed
        here); the ingress requires the credential service to share it."""
        return self._transport._vault

    def prepare(self, message: ProviderSendPrepare, *, deadline_end_monotonic=None):
        if type(message) is not ProviderSendPrepare:
            raise ProviderSendError()
        if deadline_end_monotonic is not None and type(deadline_end_monotonic) is not float:
            raise ProviderSendError("provider send deadline anchor is invalid")
        try:
            absolute_remaining = (datetime.strptime(message.deadline_at,
                "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            raise ProviderSendError("provider send absolute deadline is invalid") from None
        if absolute_remaining <= 0:
            raise ProviderSendError("provider send deadline elapsed")
        exchange_id = str(uuid4())
        with self._lock:
            if not self._usable:
                raise ProviderSendError("provider send service is unavailable after unsafe cleanup")
            if self._pending or any(state[0] in {"committed", "running"} for state in self._states.values()):
                raise ProviderSendError("provider send service busy")
            deadline = time.monotonic() + min(message.remaining_ms / 1000,
                                               absolute_remaining)
            if deadline_end_monotonic is not None:
                deadline = min(deadline, deadline_end_monotonic)
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms < 1:
                raise ProviderSendError("provider send deadline elapsed")
            self._pending[exchange_id] = (message, deadline)
            self._states[exchange_id] = ["ready", "not_sent", None, None]
        return {"exchange_id": exchange_id, "prepare_sha256": message.prepare_sha256,
                "remaining_ms": remaining_ms}

    @staticmethod
    def _lease_snapshot(lease):
        return canonical_json({
            "dialogue_id": lease.dialogue_id,
            "exchange_id": lease.exchange_id,
            "prepare_sha256": lease.prepare_sha256,
            "commit_id": lease.commit_id,
            "operation_ref": lease.operation_ref,
            "request_id": lease.request_id,
            "request_sha256": lease.request_sha256,
            "selected_handle_ref": lease.selected_handle_ref,
            "connection_sha256": lease.connection_sha256,
            "connection_pin": lease.connection_pin,
            "credential_metadata": lease.credential_metadata,
            "credential_record": lease.credential_record,
            "endpoint": lease.endpoint,
            "after_id": lease.after_id,
            "body_sha256": lease.body_sha256,
            "body_size": lease.body_size,
            "max_response_bytes": lease.max_response_bytes,
        })

    def commit(self, exchange_id, prepare_sha256, commit_id, remaining_ms=None):
        with self._lock:
            pending = self._pending.pop(exchange_id, None)
            if pending is None:
                raise ProviderSendError("commit does not match one ready exchange")
            message, deadline = pending
            if message.prepare_sha256 != prepare_sha256:
                self._states.pop(exchange_id, None)
                raise ProviderSendError("commit does not match one ready exchange")
            if self._states[exchange_id][0] != "ready":
                raise ProviderSendError("exchange is not ready")
            if time.monotonic() >= deadline:
                self._states.pop(exchange_id, None)
                raise ProviderSendError("provider send deadline elapsed")
            if (remaining_ms is not None and (type(remaining_ms) is not int
                    or not 1 <= remaining_ms <= message.remaining_ms)):
                self._states.pop(exchange_id, None)
                raise ProviderSendError("commit remaining deadline is invalid")
            if remaining_ms is not None:
                # the requester's budget was measured before its frame crossed the channel,
                # so it can exceed what is left here by the transit time; it may only shorten
                # this exchange's own deadline, never extend it
                deadline = min(deadline, time.monotonic() + remaining_ms / 1000)
            lease = GatewayExchangeLease(message.dialogue_id, exchange_id, prepare_sha256, commit_id,
                deepcopy(message.operation_ref), message.request_id, message.request_sha256,
                deepcopy(message.selected_handle_ref), message.connection_sha256,
                deepcopy(message.connection_pin), deepcopy(message.credential_metadata),
                deepcopy(message.credential_record), message.endpoint, message.after_id, message.body,
                message.body_sha256, message.body_size, self._transport._binding.max_response_bytes,
                deadline, threading.Event(), threading.Event(), self)
            self._states[exchange_id] = ["committed", "not_sent", lease, None,
                                         self._lease_snapshot(lease)]
            return lease

    def claim(self, lease):
        with self._lock:
            state = self._states.get(lease.exchange_id)
            if type(lease) is not GatewayExchangeLease or lease._issuer is not self \
                    or state is None or state[0] != "committed" or state[2] is not lease \
                    or state[4] != self._lease_snapshot(lease):
                raise ProviderSendError("lease is foreign, copied, or already consumed")
            state[0] = "running"

    def mark_write(self, lease):
        # Claim validated the exact object and frozen snapshot before custody.
        # This one-way event is deliberately lock-free: the first-write boundary
        # occurs while vault exclusion is held, where taking the registry mutex
        # would invert the required lock order.
        if type(lease) is not GatewayExchangeLease or lease._issuer is not self:
            raise ProviderSendError()
        lease.write_event.set()

    def register_connection(self, lease, connection):
        with self._lock:
            state = self._states.get(lease.exchange_id)
            if state is None or state[0] not in {"committed", "running"} or state[2] is not lease:
                raise ProviderSendError("exchange connection is not bound")
            if state[3] is not None:
                raise ProviderSendError("exchange connection is already bound")
            state[3] = connection

    def clear_connection(self, lease, connection):
        with self._lock:
            state = self._states.get(lease.exchange_id)
            if (state is not None and state[2] is lease
                    and (state[3] is connection
                         or type(state[3]) is tuple and state[3][0] is connection)):
                state[3] = None

    def bind_connection_socket(self, lease, connection, owned_socket):
        """Pin the concrete socket so cancel can interrupt a detached HTTPResponse reader."""
        with self._lock:
            state = self._states.get(lease.exchange_id)
            if (state is None or state[0] not in {"committed", "running"}
                    or state[2] is not lease or state[3] is not connection
                    or owned_socket is None):
                raise ProviderSendError("exchange socket is not bound")
            state[3] = (connection, owned_socket)

    def finish(self, lease, phase):
        with self._lock:
            state = self._states.get(lease.exchange_id)
            if state is not None and state[2] is lease:
                self._states.pop(lease.exchange_id, None)

    def exchange(self, lease):
        with self._lock:
            state = self._states.get(getattr(lease, "exchange_id", None))
            if state is None or state[0] != "committed" or state[2] is not lease:
                raise ProviderSendError("exchange lease is unavailable")
        try:
            observation = self._transport.exchange(lease=lease)
        except (GatewayError, ProviderSendError) as exc:
            phase = exc.phase or ("may_have_sent" if lease.write_event.is_set() else "not_sent")
            self.finish(lease, phase)
            raise ProviderSendError("provider exchange failed",
                failure_class_value=getattr(exc, "failure_class", None) or "internal_failure",
                status=getattr(exc, "status", None), body=getattr(exc, "body", b""),
                phase=phase, cancel_observed=getattr(exc, "cancel_observed", False),
                media_type=getattr(exc, "media_type", None)) from None
        self.finish(lease, observation.phase)
        return observation

    def status(self, exchange_id):
        with self._lock:
            state = self._states.get(exchange_id)
            return "unknown" if state is None else state[0]

    def cancel(self, exchange_id, reason):
        if reason not in {"user_requested", "deadline", "budget", "superseded", "shutdown", "policy_revoked"}:
            raise ProviderSendError()
        with self._lock:
            state = self._states.get(exchange_id)
            if state is None or state[0] == "closed":
                return ProviderSendCancellation(exchange_id, False, "terminal_observed")
            if state[0] == "ready":
                self._pending.pop(exchange_id, None)
                self._states.pop(exchange_id, None)
                return ProviderSendCancellation(exchange_id, True, "not_sent")
            lease = state[2]
            if lease is not None:
                lease.cancel_event.set()
            connection = state[3]
            phase = "may_have_sent" if lease is not None and lease.write_event.is_set() else state[1]
        if connection is not None:
            http_connection, owned_socket = ((connection, None) if type(connection) is not tuple
                                               else connection)
            try:
                if owned_socket is not None:
                    owned_socket.shutdown(__import__("socket").SHUT_RDWR)
            except OSError:
                pass
            try:
                http_connection.close()
            except OSError:
                pass
        return ProviderSendCancellation(exchange_id, True, phase)

    def abandon(self, exchange_id):
        """Drop an uncommitted authenticated dialogue after disconnect/deadline."""
        with self._lock:
            self._pending.pop(exchange_id, None)
            state = self._states.get(exchange_id)
            if state is not None and state[0] == "ready":
                self._states.pop(exchange_id, None)

    @staticmethod
    def _descriptor(value, request_id):
        fields = {"batch_id", "request_id", "ordinal", "count", "media_type",
                  "declared_size", "sha256"}
        if (type(value) is not dict or set(value) != fields
                or value["request_id"] != request_id):
            raise ProviderSendError("stream descriptor is not closed")
        return ArtifactDescriptor(**value)

    @staticmethod
    def _prepare_wire_deadline(header, outer_deadline):
        if (type(header) is not dict
                or header.get("schema") != "provider-send-prepare-v1"
                or type(header.get("seq")) is not int or header["seq"] != 0
                or type(header.get("remaining_ms")) is not int
                or not 1 <= header["remaining_ms"] <= 30_000
                or type(header.get("deadline_at")) is not str):
            raise ProviderSendError("prepare deadline header is invalid")
        try:
            absolute_remaining = (datetime.strptime(header["deadline_at"],
                "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                - datetime.now(timezone.utc)).total_seconds()
        except ValueError:
            raise ProviderSendError("prepare deadline header is invalid") from None
        end = min(outer_deadline.end_monotonic,
                  time.monotonic() + header["remaining_ms"] / 1000,
                  time.monotonic() + absolute_remaining)
        bounded = broker.Deadline(float(end))
        bounded.require()
        return bounded

    def serve_authenticated(self, sock, codec, *, deadline):
        """Serve one prepare/commit/result dialogue on an authenticated FrameCodec (the
        raw entry: the same engine through a borrowing adapter)."""
        from .gateway_connection import _RawConnection

        if type(codec) is not broker.FrameCodec or type(deadline) is not broker.Deadline:
            raise ProviderSendError("authenticated transport required")
        self._serve_dialogue(_RawConnection(sock, codec), start_frame=None, header=None, deadline=deadline)

    def serve_connection(self, owner, *, deadline):
        """Serve one dialogue on a factory-issued owner of the gateway channel whose local
        side is the responder; the owner stays the caller's to close."""
        from .listener import AuthenticatedConnection

        if type(owner) is not AuthenticatedConnection or type(deadline) is not broker.Deadline:
            raise ProviderSendError("authenticated transport required")
        self._serve_dialogue(owner, start_frame=None, header=None, deadline=deadline)

    def _serve_dialogue(self, connection, *, start_frame, header, deadline):
        """The engine: the actual first frame and its decoded header when a router already
        read them (both or neither), else read here; the existing prepare/header/body
        validators, ready, commit-or-cancel, the HTTP exchange polled beside the owner's
        control frames, the result and its stream, all under the shrinking deadlines."""
        if (start_frame is None) != (header is None):
            raise ProviderSendError("a start frame and its header travel together")
        exchange_id = None
        lease = None
        exchange_thread = None
        try:
            start = connection.read(deadline=deadline) if start_frame is None else start_frame
            if start.envelope.message_type != _REQUEST or start.envelope.correlation_id is not None:
                raise ProviderSendError("prepare frame is not bound")
            header = _control(start.payload) if header is None else header
            deadline = self._prepare_wire_deadline(header, deadline)
            sink = BytesSink()
            if header.get("body_descriptor") is not None:
                descriptor = self._descriptor(header["body_descriptor"], header.get("request_id"))
                receive_batch(_GatewayStreamTransport(connection, start.envelope.message_id, deadline),
                    [descriptor], [sink], limits=_STREAM_LIMITS)
            prepared = prepare_from_header(header, b"" if header.get("body_descriptor") is None
                                           else sink.value)
            ready = self.prepare(prepared, deadline_end_monotonic=deadline.end_monotonic)
            exchange_id = ready["exchange_id"]
            ready_id = str(uuid4())
            connection.write(message_id=ready_id, correlation_id=start.envelope.message_id,
                message_type=_RESULT, payload=encode_op({"schema": "provider-send-ready-v1",
                    "dialogue_id": prepared.dialogue_id, "seq": 0, **ready}),
                deadline=deadline)
            commit = connection.read(deadline=deadline)
            value = _control(commit.payload)
            if (commit.envelope.message_type == _REQUEST
                    and commit.envelope.correlation_id == start.envelope.message_id
                    and type(value) is dict
                    and set(value) == {"schema", "dialogue_id", "seq", "exchange_id", "reason"}
                    and value["schema"] == "provider-send-cancel-v1"
                    and value["dialogue_id"] == prepared.dialogue_id
                    and _sequence(value["seq"], 1)
                    and value["exchange_id"] == exchange_id):
                cancelled = self.cancel(exchange_id, value["reason"])
                connection.write(message_id=str(uuid4()), correlation_id=start.envelope.message_id,
                    message_type=_RESULT, payload=encode_op({
                        "schema": "provider-send-cancelled-v1", "dialogue_id": prepared.dialogue_id,
                        "seq": 1,
                        "exchange_id": cancelled.exchange_id, "accepted": cancelled.accepted,
                        "phase": cancelled.phase}), deadline=deadline)
                return
            if (commit.envelope.message_type != _REQUEST
                    or commit.envelope.correlation_id != start.envelope.message_id
                    or type(value) is not dict or set(value) != {"schema", "dialogue_id", "seq",
                        "exchange_id", "prepare_sha256", "commit_id", "remaining_ms"}
                    or value["schema"] != "provider-send-commit-v1"
                    or value["dialogue_id"] != prepared.dialogue_id
                    or not _sequence(value["seq"], 1)):
                raise ProviderSendError("commit frame is not bound")
            lease = self.commit(value["exchange_id"], value["prepare_sha256"], value["commit_id"],
                                value["remaining_ms"])
            deadline = broker.Deadline(min(deadline.end_monotonic, lease.deadline_monotonic))
            gateway_seq = 1
            core_seq = 2
            completed = Queue(maxsize=1)
            def run_exchange():
                try:
                    completed.put((self.exchange(lease), None))
                except BaseException as exc:
                    phase = (getattr(exc, "phase", None)
                             or ("may_have_sent" if lease.write_event.is_set() else "not_sent"))
                    completed.put((ProviderSendObservation(lease.exchange_id,
                        lease.prepare_sha256, getattr(exc, "status", None),
                        getattr(exc, "body", b""), phase,
                        lease.cancel_event.is_set() or getattr(exc, "cancel_observed", False),
                        getattr(exc, "media_type", None),
                        failure_class(getattr(exc, "failure_class", None)
                                      or "internal_failure")), exc))
            exchange_thread = threading.Thread(target=run_exchange,
                                                name="provider-send-exchange")
            exchange_thread.start()
            observed = None
            while observed is None:
                try:
                    observed, _failure = completed.get_nowait()
                    break
                except Empty:
                    pass
                # the owner is polled in bounded idle slices beside the completion queue: a
                # silent peer never blocks a completed exchange, a cancel never waits behind
                # a full-deadline read
                control = connection.read_duplex(deadline=deadline, idle_timeout_ms=10)
                if control is None:
                    continue
                control_value = _control(control.payload)
                if (control.envelope.message_type != _REQUEST
                        or control.envelope.correlation_id != start.envelope.message_id
                        or type(control_value) is not dict
                        or set(control_value) != {"schema", "dialogue_id", "seq", "exchange_id",
                            "reason"}
                        or control_value["schema"] != "provider-send-cancel-v1"
                        or control_value["dialogue_id"] != prepared.dialogue_id
                        or not _sequence(control_value["seq"], core_seq)
                        or control_value["exchange_id"] != lease.exchange_id):
                    raise ProviderSendError("exchange control frame is not bound")
                core_seq += 1
                cancelled = self.cancel(lease.exchange_id, control_value["reason"])
                connection.write(message_id=str(uuid4()), correlation_id=start.envelope.message_id,
                    message_type=_RESULT, payload=encode_op({
                        "schema": "provider-send-cancelled-v1", "dialogue_id": prepared.dialogue_id,
                        "seq": gateway_seq,
                        "exchange_id": cancelled.exchange_id, "accepted": cancelled.accepted,
                        "phase": cancelled.phase}), deadline=deadline)
                gateway_seq += 1
            exchange_thread.join(deadline.remaining())
            if exchange_thread.is_alive():
                raise ProviderSendError("provider exchange cleanup exceeded deadline")
            batch_id = str(uuid4())
            response_descriptor = (None if observed.phase == "not_sent" else
                {"batch_id": batch_id, "request_id": prepared.request_id,
                 "ordinal": 0, "count": 1, "declared_size": len(observed.body),
                 "sha256": __import__("hashlib").sha256(observed.body).hexdigest(),
                 "media_type": observed.media_type or "application/octet-stream"})
            wire_status = ("refused" if observed.phase == "not_sent" else
                "complete" if observed.failure_class is None and observed.status is not None
                and 200 <= observed.status < 300 else "unknown")
            result_id = str(uuid4())
            connection.write(message_id=result_id, correlation_id=start.envelope.message_id,
                message_type=_RESULT, payload=encode_op({
                    "schema": "provider-send-result-v1", "dialogue_id": prepared.dialogue_id,
                    "seq": gateway_seq, "exchange_id": observed.exchange_id,
                    "prepare_sha256": observed.prepare_sha256,
                    "status": wire_status,
                    "http_status": observed.status,
                    "phase": observed.phase, "cancel_observed": observed.cancel_observed,
                    "response_descriptor": response_descriptor,
                    "failure_class": observed.failure_class}),
                deadline=deadline)
            if response_descriptor is not None:
                stream_sequence = {"core": core_seq, "gateway": gateway_seq + 1}
                send_batch(_GatewayStreamTransport(connection, start.envelope.message_id, deadline,
                    service=self, lease=lease, dialogue_id=prepared.dialogue_id,
                    sequence=stream_sequence),
                    [self._descriptor(response_descriptor, prepared.request_id)],
                    [BytesSource(observed.body)], limits=_STREAM_LIMITS)
        except (broker.BrokerError, ListenerError, ValueError, TypeError, OSError):
            # the owner's listener categories are adapted here, at the engine boundary
            raise ProviderSendError("authenticated provider dialogue failed") from None
        finally:
            if lease is not None and exchange_thread is not None and exchange_thread.is_alive():
                self.cancel(lease.exchange_id, "shutdown")
                exchange_thread.join(deadline.remaining())
                if exchange_thread.is_alive():
                    with self._lock:
                        self._usable = False
            if exchange_id is not None:
                self.abandon(exchange_id)


__all__ = ["ProviderSendService"]
