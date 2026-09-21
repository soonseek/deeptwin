"""Control-side client for direct unit seams or authenticated provider-send frames."""

import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from . import broker
from .artifact_stream import (
    ArtifactDescriptor,
    ArtifactStreamError,
    BytesSink,
    BytesSource,
    StreamLimits,
    receive_batch,
    send_batch,
)
from .credential_channel import GatewayServiceError, decode_op, encode_op
from .provider_send_messages import (
    ProviderSendCancellation,
    ProviderSendError,
    ProviderSendObservation,
    failure_class,
    prepare_header,
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


class _CoreStreamTransport:
    """Artifact frames are asymmetric: core sends op and receives result frames.
    Over the private connection surface: the owner or the raw adapter alike."""
    def __init__(self, connection, correlation_id, deadline, channel=None,
                 exchange_id=None):
        self.connection = connection
        self.correlation_id, self.deadline = correlation_id, deadline
        self.channel, self.exchange_id = channel, exchange_id

    def send(self, payload):
        lock = None if self.channel is None else self.channel["write_lock"]
        if lock is None:
            self.connection.write(message_id=str(uuid4()),
                correlation_id=self.correlation_id, message_type=_REQUEST,
                payload=payload, deadline=self.deadline)
        else:
            with _bounded(lock, self.deadline):
                self.connection.write(message_id=str(uuid4()),
                    correlation_id=self.correlation_id, message_type=_REQUEST,
                    payload=payload, deadline=self.deadline)

    def receive(self):
        while True:
            frame = self.connection.read(deadline=self.deadline)
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
                _deliver_cancellation(self.channel, ProviderSendCancellation(
                    self.exchange_id, value["accepted"], value["phase"]))
                continue
            return frame.payload


@dataclass(frozen=True, slots=True)
class _RemoteLease:
    exchange_id: str
    observation: ProviderSendObservation


class ProviderSendCleanupAfterCancellation(ProviderSendError):
    """The ready-cancel arm owns the final close: a cleanup failure after the exact
    cancellation was observed keeps that observation instead of erasing it or
    reporting success. No wire field, retry or authority; one fixed message."""

    MESSAGE = "provider send cleanup failed after cancellation observation"

    def __init__(self, cancellation_observation):
        if type(cancellation_observation) is not ProviderSendCancellation:
            raise ProviderSendError("a cancellation observation is required")
        super().__init__(self.MESSAGE, failure_class_value="internal_failure",
                         cancel_observed=True)
        self.cancellation_observation = cancellation_observation


class _bounded:
    """A lock held only within a deadline: never a wait past the dialogue's end."""

    __slots__ = ("_deadline", "_lock")

    def __init__(self, lock, deadline):
        self._lock, self._deadline = lock, deadline

    def __enter__(self):
        if not self._lock.acquire(timeout=self._deadline.require()):
            raise ProviderSendError("provider-send dialogue lock exceeded deadline",
                                    failure_class_value="deadline_exceeded")
        return self

    def __exit__(self, _kind, _value, _traceback):
        self._lock.release()


def _deliver_cancellation(channel, cancellation):
    """The reader commits one validated acknowledgement to the one-shot control slot
    and wakes the waiter; a later terminal close never replaces it."""
    with channel["slot_lock"]:
        if channel["cancellation"] is None:
            channel["cancellation"] = cancellation
        channel["cancel_ack"].set()


def _terminal_wake(channel):
    """A terminal close wakes a waiter with a fixed terminal state — never a guessed
    acknowledgement — unless a validated one was already committed."""
    with channel["slot_lock"]:
        channel["cancel_ack"].set()


class ProviderSendClient:
    def __init__(self, service=None, *, transport_factory=None, deadline_ms=30_000, _connect=None):
        direct = service is not None
        remote = callable(transport_factory) or _connect is not None
        if ((direct == remote)
                or (direct and not all(callable(getattr(service, name, None))
                                       for name in ("prepare", "commit", "exchange", "status", "cancel")))
                or type(deadline_ms) is not int or not 1 <= deadline_ms <= 30_000):
            raise ProviderSendError("one exact provider-send transport is required")
        self._service = service
        self._factory = transport_factory
        self._connect = _connect
        self._deadline_ms = deadline_ms
        self._channel = None
        self._authenticated_session = None

    @classmethod
    def for_gateway(cls, *, requester_boot_id, deadline_ms=30_000):
        """The fixed owned client over the shared gateway profile: each prepare connects
        as the control side of the `cp-provider` channel under the prepare's own deadline,
        with the caller's process boot as the requester boot. No profile, path or peer
        override; no general connection-factory parameter."""
        from . import gateway_channel as profile
        from . import listener

        if type(requester_boot_id) is not str or not requester_boot_id:
            raise ProviderSendError("a requester boot id is required")

        def connect(deadline):
            root, spec = profile.gateway_channel()
            return listener.connect_authenticated(root, spec, requester_boot_id=requester_boot_id,
                                                  deadline=deadline)

        return cls(None, deadline_ms=deadline_ms, _connect=connect)

    def _mapped(self, error):
        """The owned client's local mapping of transport faults to the closed failure
        classes (design §6): the generic owner preserved the broker's own categories, the
        engine boundary names them. The raw pair keeps its historical raw exceptions."""
        if self._connect is None or isinstance(error, ProviderSendError):
            return error
        from . import listener

        if isinstance(error, ArtifactStreamError):
            # the stream engine wraps a foreign transport fault: the broker's own category
            # is the one that names the failure; a malformed stream frame is integrity
            cause = error.__cause__
            if isinstance(cause, broker.BrokerError | listener.ListenerError | OSError):
                return self._mapped(cause)
            return ProviderSendError("provider send transport integrity failed", failure_class_value="integrity_failed")
        if isinstance(error, broker.DeadlineExceeded):
            return ProviderSendError("provider send deadline elapsed", failure_class_value="deadline_exceeded")
        if isinstance(error, broker.ProtocolViolation | broker.AuthenticationError | GatewayServiceError
                      | listener.ListenerIntegrityError | listener.ListenerIdentityError):
            return ProviderSendError("provider send transport integrity failed", failure_class_value="integrity_failed")
        if isinstance(error, broker.BrokerError | listener.ListenerError | OSError):
            return ProviderSendError("provider send transport unavailable", failure_class_value="dependency_unavailable")
        return error

    def _close_quietly(self, channel=None):
        """Close the dialogue once under a primary failure: a cleanup failure of any
        local kind never hides that primary."""
        try:
            self._close(channel)
        except Exception:  # noqa: BLE001, S110 - the primary failure is the one that matters
            pass

    def _open(self, deadline):
        if self._connect is not None:
            try:
                return self._connect(deadline)
            except BaseException as error:
                mapped = self._mapped(error)
                if mapped is error:
                    raise
                raise mapped from None
        from .gateway_connection import _RawConnection

        sock, codec = self._factory()
        return _RawConnection(sock, codec, owns_socket=True)

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

    def _close(self, channel=None):
        """Detach the given dialogue (the active one by default) and close its connection
        once; wake any cancel waiter with the terminal state. A caller of an earlier
        dialogue never detaches a successor: the detach is bound to its own channel. A
        close failure propagates to the caller."""
        if channel is None:
            channel = self._channel
        if channel is None:
            return
        if self._channel is channel:
            self._channel = None
        with channel["state_lock"]:
            channel["state"] = "closed"
        try:
            channel["connection"].close()
        finally:
            _terminal_wake(channel)

    def abandon(self):
        """Detach and close an active dialogue without any resend."""
        if self._service is not None:
            return
        self._close_quietly()  # abandon reports nothing

    def prepare(self, message, *, deadline_end_monotonic=None):
        if self._service is not None:
            return self._service.prepare(message)
        if self._channel is not None:
            raise ProviderSendError("provider-send dialogue already active")
        # a failed acquisition cannot leave a previous ready session as this attempt's identity
        self._authenticated_session = None
        end = time.monotonic() + min(self._deadline_ms, message.remaining_ms) / 1000
        if deadline_end_monotonic is not None:
            if type(deadline_end_monotonic) is not float:
                raise ProviderSendError("provider-send deadline anchor is invalid")
            end = min(end, deadline_end_monotonic)
        deadline = broker.Deadline(end)
        header = prepare_header(message)  # nothing owned yet: a bad message costs no resource
        try:
            deadline.require()
        except BaseException as error:
            mapped = self._mapped(error)
            if mapped is error:
                raise
            raise mapped from None
        connection = self._open(deadline)
        try:
            # every fallible step after acquisition — the UUID, the encoding, the state —
            # is inside the guard, so the connection never outlives a failure here
            deadline.require()
            start_id = str(uuid4())
            connection.write(message_id=start_id, correlation_id=None, message_type=_REQUEST,
                             payload=encode_op(header), deadline=deadline)
            if header["body_descriptor"] is not None:
                descriptor = self._descriptor(header["body_descriptor"], message.request_id)
                send_batch(_CoreStreamTransport(connection, start_id, deadline), [descriptor],
                    [BytesSource(message.body)], limits=_STREAM_LIMITS)
            ready_wait_started = time.monotonic()
            frame = connection.read(deadline=deadline)
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
            # ownership moves to the dialogue state only after the complete ready validation;
            # the state is explicit and serialized: ready → committing | cancelling → closed
            self._channel = {"connection": connection, "deadline": deadline,
                             "start_id": start_id, "state": "ready",
                             "dialogue_id": message.dialogue_id, "request_id": message.request_id,
                             "send_seq": 1, "receive_seq": 1,
                             "write_lock": threading.Lock(), "state_lock": threading.Lock(),
                             "control_lock": threading.Lock(), "slot_lock": threading.Lock(),
                             "cancel_ack": threading.Event(), "cancellation": None}
            from .gateway_connection import _RawConnection

            if type(connection) is _RawConnection:
                # the raw pair's historical private seams stay reachable for its own tests;
                # an owned dialogue exposes no socket or codec
                self._channel["sock"], self._channel["codec"] = connection._socket, connection._codec
            return {name: ready[name] for name in ("exchange_id", "prepare_sha256", "remaining_ms")}
        except BaseException as error:
            try:
                connection.close()
            except Exception:  # noqa: BLE001, S110 - the primary failure is the one that matters
                pass
            mapped = self._mapped(error)
            if mapped is error:
                raise
            raise mapped from None

    def commit(self, exchange_id, prepare_sha256, commit_id):
        if self._service is not None:
            return self._service.commit(exchange_id, prepare_sha256, commit_id)
        if self._channel is None:
            raise ProviderSendError("no ready provider-send dialogue")
        channel = self._channel
        connection, deadline, start_id = (channel[name] for name in ("connection", "deadline", "start_id"))
        # commit versus ready-cancel is claimed under the one state lock before either
        # sends: whichever claims first determines the branch
        try:
            with _bounded(channel["state_lock"], deadline):
                claimed = channel["state"] == "ready"
                if claimed:
                    channel["state"] = "committing"
                    # the claim order is the wire order: the winner's frame is written under
                    # the claim, so a losing cancel never precedes it on the wire
                    with _bounded(channel["write_lock"], deadline):
                        remaining_ms = max(1, int(deadline.remaining() * 1000))
                        connection.write(message_id=str(uuid4()), correlation_id=start_id,
                            message_type=_REQUEST, payload=encode_op({"schema": "provider-send-commit-v1",
                                "dialogue_id": channel["dialogue_id"], "seq": channel["send_seq"],
                                "exchange_id": exchange_id, "prepare_sha256": prepare_sha256,
                                "commit_id": commit_id, "remaining_ms": remaining_ms}), deadline=deadline)
                        channel["send_seq"] += 1
        except BaseException as error:
            # the deadline elapsed at the claim, or the winner's frame failed: this dialogue
            # is over for every caller (never a successor's)
            self._close_quietly(channel)
            mapped = self._mapped(error)
            if mapped is error:
                raise
            raise mapped from None
        if not claimed:
            # the loser: refused locally, the claimant's in-flight dialogue untouched
            raise ProviderSendError("provider-send dialogue is not ready to commit")
        try:
            value = None
            frame = None
            while value is None:
                # this thread is the one reader of the dialogue; a concurrent cancel sends its
                # frame and waits on the slot, never reads
                candidate = connection.read_duplex(deadline=deadline, idle_timeout_ms=10)
                if candidate is None:
                    continue
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
                    _deliver_cancellation(channel, ProviderSendCancellation(
                        exchange_id, candidate_value["accepted"], candidate_value["phase"]))
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
                receive_batch(_CoreStreamTransport(connection, start_id, deadline,
                    channel, exchange_id),
                    [descriptor], [sink], limits=_STREAM_LIMITS)
            status = value["http_status"]
            observation = ProviderSendObservation(exchange_id, prepare_sha256, status,
                b"" if value["response_descriptor"] is None else sink.value,
                value["phase"], value["cancel_observed"],
                None if value["response_descriptor"] is None else value["response_descriptor"]["media_type"],
                category)
            return _RemoteLease(exchange_id, observation)
        except BaseException as error:
            self._close_quietly(channel)
            mapped = self._mapped(error)
            if mapped is error:
                raise
            raise mapped from None

    def exchange(self, lease):
        if self._service is not None:
            return self._service.exchange(lease)
        if type(lease) is not _RemoteLease or self._channel is None:
            raise ProviderSendError("remote exchange lease is unavailable")
        observation = lease.observation
        try:
            self._close()
        except Exception:  # noqa: BLE001 - a cleanup failure of any local kind, the observation retained
            # a cleanup-only failure never erases the validated observation nor turns a
            # possible write into "not sent": it is reported with the observation retained
            raise ProviderSendError("provider send cleanup failed after the observation",
                failure_class_value="internal_failure", status=observation.status,
                body=observation.body, phase=observation.phase,
                cancel_observed=observation.cancel_observed,
                media_type=observation.media_type) from None
        return observation

    def status(self, exchange_id):
        if self._service is None:
            channel = self._channel
            return "running" if channel is not None and channel["state"] == "committing" else "unknown"
        return self._service.status(exchange_id)

    def cancel(self, exchange_id, reason):
        if self._service is not None:
            return self._service.cancel(exchange_id, reason)
        channel = self._channel
        if channel is None:
            return ProviderSendCancellation(exchange_id, False, "terminal_observed")
        deadline = channel["deadline"]
        try:
            # duplicate or concurrent cancels serialize here: each sends its own frame and
            # waits for its own acknowledgement, never sharing a stale one
            with _bounded(channel["control_lock"], deadline):
                claimed = False
                try:
                    with _bounded(channel["state_lock"], deadline):
                        state = channel["state"]
                        if state == "closed":
                            # the dialogue ended under an earlier cancel or result: the fixed
                            # terminal state, the same as with no dialogue at all
                            return ProviderSendCancellation(exchange_id, False, "terminal_observed")
                        ready_cancel = state == "ready"
                        if ready_cancel:
                            channel["state"] = "cancelling"  # commit can no longer claim
                        with channel["slot_lock"]:
                            channel["cancellation"] = None
                            channel["cancel_ack"].clear()
                        claimed = True
                        # the claim order is the wire order: the frame is written under the
                        # claim, never after a later claimant's frame
                        with _bounded(channel["write_lock"], deadline):
                            payload = encode_op({"schema": "provider-send-cancel-v1",
                                "dialogue_id": channel["dialogue_id"], "seq": channel["send_seq"],
                                "exchange_id": exchange_id, "reason": reason})
                            channel["connection"].write(message_id=str(uuid4()),
                                correlation_id=channel["start_id"], message_type=_REQUEST,
                                payload=payload, deadline=deadline)
                            channel["send_seq"] += 1
                except BaseException as error:
                    # a cancel frame that may not have left (or the deadline over at the
                    # claim): this dialogue is unusable for every caller and is closed here,
                    # never left dead for a reused client, never a successor's
                    if claimed or isinstance(error, broker.DeadlineExceeded):
                        self._close_quietly(channel)
                    mapped = self._mapped(error)
                    if mapped is error:
                        raise
                    raise mapped from None
                if not ready_cancel:
                    # the commit thread is the reader and owns the close: wait for the
                    # one-shot slot under the dialogue's own deadline
                    if not channel["cancel_ack"].wait(deadline.remaining()):
                        raise ProviderSendError("provider cancellation acknowledgement timed out",
                                                failure_class_value="deadline_exceeded")
                    with channel["slot_lock"]:
                        cancellation = channel["cancellation"]
                    if cancellation is None:  # the dialogue ended first: never a guessed False
                        raise ProviderSendError("provider-send dialogue ended before the cancellation was acknowledged")
                    return cancellation
                # the ready-cancel arm: this thread reads the one acknowledgement and owns
                # the final close
                try:
                    frame = channel["connection"].read(deadline=deadline)
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
                    observation = ProviderSendCancellation(exchange_id, value["accepted"], value["phase"])
                except BaseException as error:
                    self._close_quietly(channel)
                    mapped = self._mapped(error)
                    if mapped is error:
                        raise
                    raise mapped from None
                try:
                    self._close(channel)
                except Exception:  # noqa: BLE001 - a cleanup failure of any local kind, the cancellation retained
                    raise ProviderSendCleanupAfterCancellation(observation) from None
                return observation
        except BaseException as error:
            # a lock or deadline failure before the claim: mapped, and the dialogue closed
            # only when its deadline is over (a losing competitor never closes a claimant)
            if isinstance(error, broker.DeadlineExceeded):
                self._close_quietly(channel)
            mapped = self._mapped(error)
            if mapped is error:
                raise
            raise mapped from None


__all__ = ["ProviderSendCleanupAfterCancellation", "ProviderSendClient"]
