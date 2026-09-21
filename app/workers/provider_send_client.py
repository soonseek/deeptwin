"""Control-side client for direct unit seams or authenticated provider-send frames."""

from dataclasses import dataclass
import select
import threading
import time
from uuid import uuid4

from . import broker
from .artifact_stream import (ArtifactDescriptor, BytesSink, BytesSource, StreamLimits,
                              receive_batch, send_batch)
from .credential_channel import decode_op, encode_op
from .provider_send_messages import (ProviderSendError, ProviderSendObservation,
                                     ProviderSendCancellation, failure_class, prepare_header)

_REQUEST, _RESULT = "credential_op", "credential_result"
_STREAM_LIMITS = StreamLimits(max_artifact_bytes=1_048_576,
                              max_total_bytes=1_048_576, max_chunk_bytes=16_384)


def _control(payload):
    if type(payload) is not bytes or len(payload) > 16_384:
        raise ProviderSendError("provider-send application control exceeds 16KiB")
    return decode_op(payload)


def _sequence(value, expected):
    return type(value) is int and value == expected


class _CoreStreamTransport:
    """Artifact frames are asymmetric: core sends op and receives result frames."""
    def __init__(self, sock, codec, correlation_id, deadline, channel=None,
                 exchange_id=None):
        self.sock, self.codec = sock, codec
        self.correlation_id, self.deadline = correlation_id, deadline
        self.channel, self.exchange_id = channel, exchange_id

    def send(self, payload):
        lock = None if self.channel is None else self.channel["write_lock"]
        if lock is None:
            self.codec.write(self.sock, message_id=str(uuid4()),
                correlation_id=self.correlation_id, message_type=_REQUEST,
                payload=payload, deadline=self.deadline)
        else:
            with lock:
                self.codec.write(self.sock, message_id=str(uuid4()),
                    correlation_id=self.correlation_id, message_type=_REQUEST,
                    payload=payload, deadline=self.deadline)

    def receive(self):
        while True:
            frame = self.codec.read(self.sock, deadline=self.deadline)
            if (frame.envelope.message_type != _RESULT
                    or frame.envelope.correlation_id != self.correlation_id):
                raise ProviderSendError("stream frame is not phase-bound")
            if self.channel is None:
                return frame.payload
            if len(frame.payload) > 16_384:
                return frame.payload
            value = _control(frame.payload)
            if (type(value) is dict
                    and value.get("schema") == "provider-send-cancelled-v1"):
                expected = {"schema", "dialogue_id", "seq", "exchange_id",
                            "accepted", "phase"}
                if (set(value) != expected
                        or value["dialogue_id"] != self.channel["dialogue_id"]
                        or not _sequence(value["seq"], self.channel["receive_seq"])
                        or value["exchange_id"] != self.exchange_id):
                    raise ProviderSendError("cancellation frame is not bound")
                self.channel["receive_seq"] += 1
                self.channel["cancellation"] = ProviderSendCancellation(
                    self.exchange_id, value["accepted"], value["phase"])
                self.channel["cancel_ack"].set()
                continue
            return frame.payload


@dataclass(frozen=True, slots=True)
class _RemoteLease:
    exchange_id: str
    observation: ProviderSendObservation


class ProviderSendClient:
    def __init__(self, service=None, *, transport_factory=None, deadline_ms=30_000):
        direct = service is not None
        if ((direct == callable(transport_factory))
                or (direct and not all(callable(getattr(service, name, None))
                                       for name in ("prepare", "commit", "exchange", "status", "cancel")))
                or type(deadline_ms) is not int or not 1 <= deadline_ms <= 30_000):
            raise ProviderSendError("one exact provider-send transport is required")
        self._service = service
        self._factory = transport_factory
        self._deadline_ms = deadline_ms
        self._channel = None
        self._authenticated_session = None

    @staticmethod
    def _session_observation(frame):
        envelope = frame.envelope
        return (envelope.protocol_id, envelope.channel_id, envelope.connection_id,
                envelope.requester_boot_id, envelope.responder_boot_id,
                envelope.sender, envelope.receiver, envelope.direction)

    @property
    def authenticated_session_observation(self):
        return self._authenticated_session

    @staticmethod
    def _descriptor(value, request_id):
        fields = {"batch_id", "request_id", "ordinal", "count", "media_type",
                  "declared_size", "sha256"}
        if (type(value) is not dict or set(value) != fields
                or value["request_id"] != request_id):
            raise ProviderSendError("stream descriptor is not closed")
        return ArtifactDescriptor(**value)

    def _close(self):
        if self._channel is not None:
            sock, codec = self._channel["sock"], self._channel["codec"]
            codec.close()
            try:
                sock.close()
            except OSError:
                pass
            self._channel = None

    def prepare(self, message, *, deadline_end_monotonic=None):
        if self._service is not None:
            return self._service.prepare(message)
        if self._channel is not None:
            raise ProviderSendError("provider-send dialogue already active")
        end = time.monotonic() + min(self._deadline_ms, message.remaining_ms) / 1000
        if deadline_end_monotonic is not None:
            if type(deadline_end_monotonic) is not float:
                raise ProviderSendError("provider-send deadline anchor is invalid")
            end = min(end, deadline_end_monotonic)
        deadline = broker.Deadline(end)
        sock, codec = self._factory()
        try:
            deadline.require()
        except BaseException:
            codec.close()
            sock.close()
            raise
        start_id = str(uuid4())
        header = prepare_header(message)
        try:
            codec.write(sock, message_id=start_id, correlation_id=None, message_type=_REQUEST,
                        payload=encode_op(header), deadline=deadline)
            if header["body_descriptor"] is not None:
                descriptor = self._descriptor(header["body_descriptor"], message.request_id)
                send_batch(_CoreStreamTransport(sock, codec, start_id, deadline), [descriptor],
                    [BytesSource(message.body)], limits=_STREAM_LIMITS)
            ready_wait_started = time.monotonic()
            frame = codec.read(sock, deadline=deadline)
            self._authenticated_session = self._session_observation(frame)
            ready = _control(frame.payload)
            if (frame.envelope.message_type != _RESULT
                    or frame.envelope.correlation_id != start_id
                    or type(ready) is not dict
                    or set(ready) != {"schema", "dialogue_id", "seq", "exchange_id",
                        "prepare_sha256", "remaining_ms"}
                    or ready["schema"] != "provider-send-ready-v1"
                    or ready["dialogue_id"] != message.dialogue_id
                    or not _sequence(ready["seq"], 0)
                    or ready["prepare_sha256"] != message.prepare_sha256
                    or type(ready["remaining_ms"]) is not int
                    or not 1 <= ready["remaining_ms"] <= message.remaining_ms):
                raise ProviderSendError("ready frame is not bound")
            deadline = broker.Deadline(min(deadline.end_monotonic,
                ready_wait_started + ready["remaining_ms"] / 1000))
            deadline.require()
            self._channel = {"sock": sock, "codec": codec, "deadline": deadline,
                             "start_id": start_id, "committing": False,
                             "dialogue_id": message.dialogue_id, "request_id": message.request_id,
                             "send_seq": 1, "receive_seq": 1,
                             "write_lock": threading.Lock(), "cancel_ack": threading.Event(),
                             "cancellation": None}
            return {name: ready[name] for name in ("exchange_id", "prepare_sha256", "remaining_ms")}
        except BaseException:
            codec.close()
            try:
                sock.close()
            except OSError:
                pass
            raise

    def commit(self, exchange_id, prepare_sha256, commit_id):
        if self._service is not None:
            return self._service.commit(exchange_id, prepare_sha256, commit_id)
        if self._channel is None:
            raise ProviderSendError("no ready provider-send dialogue")
        channel = self._channel
        sock, codec, deadline, start_id = (channel[name] for name in
                                           ("sock", "codec", "deadline", "start_id"))
        commit_message_id = str(uuid4())
        try:
            channel["committing"] = True
            with channel["write_lock"]:
                remaining_ms = max(1, int(deadline.remaining() * 1000))
                codec.write(sock, message_id=commit_message_id, correlation_id=start_id,
                    message_type=_REQUEST, payload=encode_op({"schema": "provider-send-commit-v1",
                        "dialogue_id": channel["dialogue_id"], "seq": channel["send_seq"],
                        "exchange_id": exchange_id, "prepare_sha256": prepare_sha256,
                        "commit_id": commit_id, "remaining_ms": remaining_ms}), deadline=deadline)
                channel["send_seq"] += 1
            value = None
            frame = None
            while value is None:
                readable, _, _ = select.select([sock], [], [], min(0.010, deadline.require()))
                if not readable:
                    continue
                candidate = codec.read(sock, deadline=deadline)
                candidate_value = _control(candidate.payload)
                if (type(candidate_value) is dict
                        and candidate.envelope.message_type == _RESULT
                        and candidate.envelope.correlation_id == start_id
                        and set(candidate_value) == {"schema", "dialogue_id", "seq",
                            "exchange_id", "accepted", "phase"}
                        and candidate_value["schema"] == "provider-send-cancelled-v1"
                        and candidate_value["dialogue_id"] == channel["dialogue_id"]
                        and _sequence(candidate_value["seq"], channel["receive_seq"])
                        and candidate_value["exchange_id"] == exchange_id):
                    channel["receive_seq"] += 1
                    channel["cancellation"] = ProviderSendCancellation(
                        exchange_id, candidate_value["accepted"], candidate_value["phase"])
                    channel["cancel_ack"].set()
                    continue
                frame, value = candidate, candidate_value
            expected = {"schema", "dialogue_id", "seq", "exchange_id", "prepare_sha256",
                        "status", "http_status", "phase", "cancel_observed", "response_descriptor",
                        "failure_class"}
            if (frame.envelope.message_type != _RESULT
                    or frame.envelope.correlation_id != start_id
                    or type(value) is not dict or set(value) != expected
                    or value["schema"] != "provider-send-result-v1"
                    or value["dialogue_id"] != channel["dialogue_id"]
                    or not _sequence(value["seq"], channel["receive_seq"])
                    or value["exchange_id"] != exchange_id
                    or value["prepare_sha256"] != prepare_sha256):
                raise ProviderSendError("observation frame is not bound")
            category = failure_class(value["failure_class"])
            if (type(value["status"]) is not str
                    or value["status"] not in {"complete", "refused", "truncated", "unknown"}
                    or (value["http_status"] is not None
                        and (type(value["http_status"]) is not int
                             or not 100 <= value["http_status"] <= 599))
                    or type(value["phase"]) is not str
                    or value["phase"] not in {"not_sent", "may_have_sent", "terminal_observed"}
                    or type(value["cancel_observed"]) is not bool
                    or (value["status"] == "complete" and category is not None)
                    or (value["status"] == "refused") != (value["phase"] == "not_sent")
                    or (value["phase"] == "not_sent" and (value["http_status"] is not None
                        or value["response_descriptor"] is not None))
                    or (category == "cancelled" and not value["cancel_observed"])):
                raise ProviderSendError("provider result failure classification is incoherent")
            channel["receive_seq"] += 1
            sink = BytesSink()
            if value["response_descriptor"] is not None:
                descriptor = self._descriptor(value["response_descriptor"], channel["request_id"])
                receive_batch(_CoreStreamTransport(sock, codec, start_id, deadline,
                    channel, exchange_id),
                    [descriptor], [sink], limits=_STREAM_LIMITS)
            status = value["http_status"]
            observation = ProviderSendObservation(exchange_id, prepare_sha256, status,
                b"" if value["response_descriptor"] is None else sink.value,
                value["phase"], value["cancel_observed"],
                None if value["response_descriptor"] is None else value["response_descriptor"]["media_type"],
                category)
            return _RemoteLease(exchange_id, observation)
        except BaseException:
            self._close()
            raise

    def exchange(self, lease):
        if self._service is not None:
            return self._service.exchange(lease)
        if type(lease) is not _RemoteLease or self._channel is None:
            raise ProviderSendError("remote exchange lease is unavailable")
        try:
            return lease.observation
        finally:
            self._close()

    def status(self, exchange_id):
        if self._service is None:
            return ("running" if self._channel is not None
                    and self._channel["committing"] else "unknown")
        return self._service.status(exchange_id)

    def cancel(self, exchange_id, reason):
        if self._service is None:
            channel = self._channel
            if channel is None:
                return ProviderSendCancellation(exchange_id, False, "terminal_observed")
            with channel["write_lock"]:
                payload = encode_op({"schema": "provider-send-cancel-v1",
                    "dialogue_id": channel["dialogue_id"], "seq": channel["send_seq"],
                    "exchange_id": exchange_id, "reason": reason})
                channel["codec"].write(channel["sock"], message_id=str(uuid4()),
                    correlation_id=channel["start_id"], message_type=_REQUEST,
                    payload=payload, deadline=channel["deadline"])
                channel["send_seq"] += 1
            if channel["committing"]:
                if not channel["cancel_ack"].wait(channel["deadline"].remaining()):
                    raise ProviderSendError("provider cancellation acknowledgement timed out")
                return channel["cancellation"]
            try:
                frame = channel["codec"].read(channel["sock"], deadline=channel["deadline"])
                value = _control(frame.payload)
                if (frame.envelope.message_type != _RESULT
                        or frame.envelope.correlation_id != channel["start_id"]
                        or type(value) is not dict
                        or set(value) != {"schema", "dialogue_id", "seq", "exchange_id",
                            "accepted", "phase"}
                        or value["schema"] != "provider-send-cancelled-v1"
                        or value["dialogue_id"] != channel["dialogue_id"]
                        or not _sequence(value["seq"], channel["receive_seq"])
                        or value["exchange_id"] != exchange_id):
                    raise ProviderSendError("cancellation frame is not bound")
                return ProviderSendCancellation(exchange_id, value["accepted"], value["phase"])
            finally:
                self._close()
        return self._service.cancel(exchange_id, reason)


__all__ = ["ProviderSendClient"]
