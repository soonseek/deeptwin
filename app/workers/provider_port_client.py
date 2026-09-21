"""Core-side client for direct unit seams or authenticated semantic worker frames."""

from hashlib import sha256
from contextlib import contextmanager
import threading
import time
from uuid import uuid4

from ..domain.refs import canonical_json
from . import broker
from .artifact_stream import (ArtifactDescriptor, BytesSink, BytesSource, StreamLimits,
                              StreamCancelled, receive_batch, send_batch)
from .artifact_stream_transport import ConnectionStreamTransport
from .credential_channel import decode_op, encode_op
from ..extensions.provider_semantic_contracts import ProviderSemanticError, exact_ref
from .provider_port_messages import ProviderObservation, ProviderProposal, request_digest
from .provider_semantic_codec import CatalogTraversal, advance_catalog, parse_model_page
from .extension_channel import extension_channel
from . import listener
from .semantic_connection import (
    _OwnedConnectionError,
    _owned_connection,
    _raw_connection,
)

_REQUEST, _RESULT, _ARTIFACT = "extension-request-v1", "extension-result-v1", "extension-artifact-v1"
_STREAM_LIMITS = StreamLimits(max_artifact_bytes=1_048_576,
                              max_total_bytes=4 * 1_048_576, max_chunk_bytes=16_384)
# A sender can advance only one granted credit window before it must read again.
# At this receiver-side write boundary that means at most the granted chunks plus
# one terminal frame may precede the control acknowledgement.
_MAX_DEFERRED_STREAM_FRAMES = _STREAM_LIMITS.credit_window_chunks + 1


def _control(payload):
    if type(payload) is not bytes or len(payload) > 16_384:
        raise ProviderSemanticError("semantic application control exceeds 16KiB")
    return decode_op(payload)


def _sequence(value, expected):
    return type(value) is int and value == expected


def _control_observation(value, operation):
    """Validate the complete closed observation before one-shot publication."""
    if operation == "cancel":
        if (type(value) is not dict
                or set(value) != {"operation", "cancel_state"}
                or value["operation"] != "cancel"
                or type(value["cancel_state"]) is not str
                or value["cancel_state"] not in {
                    "accepted", "already_terminal", "not_cancellable"
                }):
            raise ProviderSemanticError(
                "semantic control observation is not bound"
            )
    elif operation == "status":
        if (type(value) is not dict
                or set(value) != {
                    "operation", "observed_state", "terminal_result_ref"
                }
                or value["operation"] != "status"
                or type(value["observed_state"]) is not str
                or value["observed_state"] not in {
                    "pending", "running", "succeeded", "failed",
                    "cancelled", "unknown",
                }):
            raise ProviderSemanticError(
                "semantic control observation is not bound"
            )
        if value["terminal_result_ref"] is not None:
            exact_ref(value["terminal_result_ref"])
    else:
        raise ProviderSemanticError("semantic control observation is not bound")
    return dict(value)


def _acquire(lock, deadline, *, blocking=True):
    if not blocking:
        acquired = lock.acquire(blocking=False)
    else:
        acquired = lock.acquire(timeout=deadline.require())
    if not acquired:
        raise broker.DeadlineExceeded(dispatch_effect="outcome_unknown")
    try:
        deadline.require(dispatch_effect="outcome_unknown")
    except BaseException:
        lock.release()
        raise
    return True


@contextmanager
def _bounded_lock(lock, deadline):
    _acquire(lock, deadline)
    try:
        yield
    finally:
        lock.release()


class _WorkerClientStreamTransport:
    """Artifact adapter whose one owner routes semantic control acknowledgements."""
    def __init__(self, client, channel):
        self._client, self._channel = client, channel

    def send(self, payload):
        channel = self._channel
        with _bounded_lock(channel["write_lock"], channel["deadline"]):
            self._client._settle_control_before_stream_write(channel)
            channel["connection"].write(message_id=str(uuid4()),
                correlation_id=channel["start_id"], message_type=_ARTIFACT,
                payload=payload, deadline=channel["deadline"])

    def receive(self):
        frame = self._client._read_owned(self._channel, cancel_owner=True)
        if (frame.envelope.message_type != _ARTIFACT
                or frame.envelope.correlation_id != self._channel["start_id"]):
            raise ProviderSemanticError("worker artifact frame is not bound")
        return frame.payload


class ProviderPortClient:
    def __init__(self, service=None, *, transport_factory=None, deadline_ms=30_000):
        direct = service is not None
        if ((direct == callable(transport_factory))
                or (direct and not all(callable(getattr(service, name, None))
                                       for name in ("begin", "observe", "execute")))
                or type(deadline_ms) is not int or not 1 <= deadline_ms <= 30_000):
            raise ProviderSemanticError("one exact semantic worker transport is required")
        self._service = service
        self._factory = transport_factory
        self._deadline_ms = deadline_ms
        self._channel = None
        self._authenticated_session = None
        self._extension_slot = None

    @classmethod
    def for_extension_slot(
        cls,
        *,
        instance_id: str,
        slot_number: int,
        requester_boot_id: str,
        deadline_ms: int = 30_000,
    ):
        """Create a client fixed to one derived extension slot.

        This constructor grants no admission/binding authority and exposes no
        path or peer-verification override.  Each operation connects using the
        operation's original absolute monotonic deadline.
        """

        root, spec = extension_channel(
            instance_id=instance_id, slot_number=slot_number
        )
        if (
            type(requester_boot_id) is not str
            or listener._BOOT_ID.fullmatch(requester_boot_id) is None
        ):
            raise ProviderSemanticError("requester boot identity is invalid")
        result = cls(transport_factory=lambda: None, deadline_ms=deadline_ms)
        result._extension_slot = (root, spec, requester_boot_id)
        return result

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
    def _description(raw, media_type, request_id, ordinal=0, count=1):
        return {"batch_id": str(uuid4()), "request_id": request_id, "ordinal": ordinal,
                "count": count, "declared_size": len(raw),
                "sha256": sha256(raw).hexdigest(), "media_type": media_type}

    @staticmethod
    def _descriptors(values, request_id):
        if type(values) is not list or len(values) > 4:
            raise ProviderSemanticError("artifact descriptors are out of bounds")
        expected = {"batch_id", "request_id", "ordinal", "count", "media_type",
                    "declared_size", "sha256"}
        if any(type(value) is not dict or set(value) != expected
               or value["request_id"] != request_id or value["ordinal"] != index
               or value["count"] != len(values) for index, value in enumerate(values)):
            raise ProviderSemanticError("artifact descriptor is not semantically bound")
        return [ArtifactDescriptor(**value) for value in values]

    def _open(self, deadline_end_monotonic=None):
        if self._channel is not None:
            raise ProviderSemanticError("worker dialogue already active")
        configured_end = time.monotonic() + self._deadline_ms / 1000
        if deadline_end_monotonic is not None:
            if type(deadline_end_monotonic) is not float:
                raise ProviderSemanticError("worker deadline anchor is invalid")
            configured_end = min(configured_end, deadline_end_monotonic)
        deadline = broker.Deadline(configured_end)
        if self._extension_slot is not None:
            root, spec, requester_boot_id = self._extension_slot
            try:
                owner = listener._connect_extension_authenticated(
                    root,
                    spec,
                    requester_boot_id=requester_boot_id,
                    deadline=deadline,
                )
            except listener.ListenerError:
                raise _OwnedConnectionError("owned_connection_unavailable") from None
            try:
                connection = _owned_connection(owner, deadline)
                connection.checkpoint()
                return connection, connection.deadline
            except BaseException:
                try:
                    owner.close()
                except BaseException:  # noqa: BLE001, S110 - preserve guard primary
                    pass
                raise
        sock, codec = self._factory()
        connection = _raw_connection(sock, codec, deadline, owns=True)
        try:
            connection.checkpoint()
        except BaseException:
            try:
                connection.close()
            except BaseException:  # noqa: BLE001, S110 - preserve guard primary
                pass
            raise
        return connection, deadline

    @staticmethod
    def _close(channel, *, after_control_observation=False):
        if channel is None:
            return
        if type(channel) is dict:
            connection = channel["connection"]
        elif type(channel) is tuple:
            sock, codec, *_ = channel
            codec.close()
            try:
                sock.close()
            except OSError:
                pass
            return
        else:
            connection = channel
        connection.close(after_control_observation=after_control_observation)

    def _read_owned(self, channel, *, cancel_owner, stop_after_control=None,
                    wire_only=False):
        """Read as the phase owner, delivering control results to their waiter."""
        while True:
            frame = (self._read_wire_frame(channel) if wire_only
                     else self._read_authenticated_frame(channel))
            if (frame.envelope.message_type != _RESULT
                    or frame.envelope.correlation_id != channel["start_id"]):
                return frame
            value = _control(frame.payload)
            if not (type(value) is dict
                    and value.get("schema") == "provider-semantic-control-result-v1"):
                return frame
            with _bounded_lock(channel["state_lock"], channel["deadline"]):
                pending = channel["pending_control"]
            expected = {"schema", "dialogue_id", "seq", "operation_ref",
                        "request_id", "observation"}
            if (pending is None or set(value) != expected
                    or value["dialogue_id"] != channel["dialogue_id"]
                    or not _sequence(value["seq"], channel["receive_seq"])
                    or value["operation_ref"] != channel["operation_ref"]
                    or value["request_id"] != pending["request"]["request_id"]):
                raise ProviderSemanticError("semantic control result is not bound")
            observation = _control_observation(
                value["observation"], pending["request"]["operation"]
            )
            channel["connection"].checkpoint()
            accepted = (pending["request"]["operation"] == "cancel"
                        and observation.get("cancel_state") == "accepted")
            with _bounded_lock(channel["state_lock"], channel["deadline"]):
                if (channel["failed"] or channel["pending_control"] is not pending
                        or pending["outcome"] is not None):
                    raise _OwnedConnectionError("owned_connection_unavailable")
                channel["deadline"].require(dispatch_effect="outcome_unknown")
                channel["receive_seq"] += 1
                channel["cancelled"] = channel["cancelled"] or accepted
                pending["outcome"] = ("observation", dict(observation))
            pending["event"].set()
            if accepted and cancel_owner:
                raise StreamCancelled("semantic dialogue cancellation was accepted")
            if pending is stop_after_control:
                return None

    def _settle_control_before_stream_write(self, channel):
        """Let the sole reader authenticate a queued control before stream credit.

        A peer may acknowledge an accepted cancel and stop its artifact sender
        before reading the receiver's next credit.  Writing that credit first can
        therefore latch the codec closed while the authenticated control result is
        already queued.  The active stream owner settles that result first and
        preserves any earlier application frames for the stream consumer.
        """

        with _bounded_lock(channel["state_lock"], channel["deadline"]):
            pending = channel["pending_control"]
            if pending is None or pending["event"].is_set():
                return
        deferred = []
        try:
            while not pending["event"].is_set():
                frame = self._read_owned(
                    channel,
                    cancel_owner=True,
                    stop_after_control=pending,
                    wire_only=True,
                )
                if frame is not None:
                    if (
                        len(channel["deferred_frames"]) + len(deferred)
                        >= _MAX_DEFERRED_STREAM_FRAMES
                    ):
                        raise ProviderSemanticError(
                            "semantic stream exceeded control deferral bound"
                        )
                    deferred.append(frame)
        finally:
            if deferred:
                channel["deferred_frames"].extend(deferred)

    @staticmethod
    def _read_wire_frame(channel):
        """Own bounded wire reads without holding FrameCodec across peer waits."""
        connection = channel.get("connection")
        if connection is None:
            connection = _raw_connection(
                channel["sock"],
                channel["codec"],
                channel["deadline"],
                owns=False,
            )
        return connection.read_duplex()

    @staticmethod
    def _read_authenticated_frame(channel):
        deferred = channel.get("deferred_frames")
        if deferred:
            return deferred.pop(0)
        return ProviderPortClient._read_wire_frame(channel)

    @staticmethod
    def _publish_failure(channel):
        pending = None
        state_lock = channel["state_lock"]
        acquired = state_lock.acquire(blocking=False)
        if not acquired:
            remaining = channel["deadline"].remaining()
            if remaining > 0.0:
                acquired = state_lock.acquire(timeout=remaining)
        if not acquired:
            return
        try:
            channel["failed"] = True
            pending = channel["pending_control"]
            if pending is not None and pending["outcome"] is None:
                pending["outcome"] = (
                    "error",
                    _OwnedConnectionError("owned_connection_unavailable"),
                )
        finally:
            state_lock.release()
        if pending is not None:
            pending["event"].set()

    def abandon(self):
        """Close this client's unfinished authenticated dialogue, if any."""
        if self._service is None and self._channel is not None:
            self._close(self._channel)
            self._channel = None

    def begin(self, request, **kwargs):
        if self._service is not None:
            return self._service.begin(request, **kwargs)
        connection, deadline = self._open(
            kwargs.pop("deadline_end_monotonic", None)
        )
        try:
            start_id, dialogue_id = str(uuid4()), str(uuid4())
            inputs = tuple(kwargs.get("input_bytes", ()))
            descriptions = [self._description(raw, "text/plain", request["request_id"], index,
                                               len(inputs))
                            for index, raw in enumerate(inputs)]
            operation_ref = kwargs.get("operation_ref")
            config = kwargs.get("config")
            frozen_content = kwargs.get("frozen_content")
            frozen_raw = None if frozen_content is None else canonical_json(frozen_content)
            frozen_descriptor = (None if frozen_raw is None else
                                 self._description(frozen_raw, "application/json",
                                                   request["request_id"]))
        except BaseException:
            try:
                self._close(connection)
            except BaseException:  # noqa: BLE001, S110 - preserve setup primary
                pass
            raise
        channel = None
        try:
            channel = {"connection": connection, "deadline": deadline,
                "sock": getattr(connection, "raw_socket", None),
                "codec": getattr(connection, "raw_codec", None),
                "start_id": start_id, "dialogue_id": dialogue_id,
                "operation_ref": operation_ref, "request": request,
                "proposal": None, "send_seq": 1, "receive_seq": 0,
                "write_lock": threading.RLock(), "owner_lock": threading.RLock(),
                "state_lock": threading.Lock(), "pending_control": None,
                "deferred_frames": [], "cancelled": False, "failed": False}
            self._channel = channel
            stream = _WorkerClientStreamTransport(self, channel)
            _acquire(channel["owner_lock"], deadline)
        except BaseException:
            self._channel = None
            try:
                self._close(connection)
            except BaseException:  # noqa: BLE001, S110 - setup primary wins
                pass
            raise
        try:
            with channel["owner_lock"]:
                payload = encode_op({"schema": "provider-semantic-begin-v1",
                    "dialogue_id": dialogue_id, "seq": 0, "operation_ref": operation_ref,
                    "config": config, "request": request, "frozen_descriptor": frozen_descriptor,
                    "input_descriptors": descriptions, "query_state": None})
                if len(payload) > 16_384:
                    raise ProviderSemanticError("semantic control exceeds 16KiB")
                with _bounded_lock(channel["write_lock"], deadline):
                    connection.write(message_id=start_id, correlation_id=None,
                        message_type=_REQUEST, payload=payload, deadline=deadline)
                if frozen_descriptor is not None:
                    send_batch(stream, self._descriptors([frozen_descriptor],
                        request["request_id"]), [BytesSource(frozen_raw)], limits=_STREAM_LIMITS)
                if descriptions:
                    send_batch(stream, self._descriptors(descriptions, request["request_id"]),
                        [BytesSource(raw) for raw in inputs], limits=_STREAM_LIMITS)
                frame = self._read_owned(channel, cancel_owner=True)
            self._authenticated_session = self._session_observation(frame)
            value = _control(frame.payload)
            expected = {"schema", "dialogue_id", "seq", "operation_ref", "request_sha256",
                        "endpoint", "after_id", "body_descriptor"}
            if (frame.envelope.message_type != _RESULT or frame.envelope.correlation_id != start_id
                    or type(value) is not dict or set(value) != expected
                    or value["schema"] != "provider-semantic-proposal-v1"
                    or value["dialogue_id"] != dialogue_id
                    or not _sequence(value["seq"], channel["receive_seq"])
                    or value["operation_ref"] != operation_ref
                    or value["request_sha256"] != sha256(canonical_json(request)).hexdigest()):
                raise ProviderSemanticError("worker proposal is not bound")
            # The authenticated proposal header is application frame zero. Controls
            # can be routed while its artifact body is in flight, so reserve the next
            # worker application sequence before entering that stream phase.
            channel["receive_seq"] += 1
            sink = BytesSink()
            if value["body_descriptor"] is not None:
                descriptor = self._descriptors([value["body_descriptor"]], request["request_id"])
                with channel["owner_lock"]:
                    receive_batch(stream, descriptor, [sink], limits=_STREAM_LIMITS)
            proposal = ProviderProposal(request["request_id"], request["operation"],
                value["request_sha256"], value["endpoint"], value["after_id"],
                None if value["body_descriptor"] is None else sink.value, CatalogTraversal())
            connection.checkpoint()
            channel["proposal"] = proposal
            return proposal
        except StreamCancelled:
            try:
                self._close(channel)
            except BaseException:  # noqa: BLE001, S110 - cancel primary wins
                pass
            self._channel = None
            raise
        except BaseException:
            self._publish_failure(channel)
            try:
                self._close(channel)
            except BaseException:  # noqa: BLE001, S110 - preserve operation primary
                pass
            self._channel = None
            raise
        finally:
            channel["owner_lock"].release()

    def observe(self, proposal, **kwargs):
        if self._service is not None:
            return self._service.observe(proposal, **kwargs)
        if self._channel is None or self._channel["proposal"] is not proposal:
            raise ProviderSemanticError("worker proposal has no active dialogue")
        channel = self._channel
        connection, deadline, start_id = (channel[name] for name in
            ("connection", "deadline", "start_id"))
        try:
            raw, status = kwargs["raw"], kwargs["status"]
            exchange_id = kwargs.get("exchange_id")
            if (type(raw) is not bytes or type(status) is not int
                    or type(exchange_id) is not str):
                raise ProviderSemanticError("upstream observation is incomplete")
            description = self._description(
                raw,
                kwargs.get("media_type", "application/octet-stream"),
                proposal.request_id,
            )
            observe_id = str(uuid4())
        except BaseException:
            self._publish_failure(channel)
            try:
                self._close(channel)
            except BaseException:  # noqa: BLE001, S110 - preserve validation primary
                pass
            self._channel = None
            raise
        owner_acquired = False
        try:
            _acquire(channel["owner_lock"], deadline)
            owner_acquired = True
            stream = _WorkerClientStreamTransport(self, channel)
            with channel["owner_lock"]:
                seq = channel["send_seq"]
                with _bounded_lock(channel["write_lock"], deadline):
                    connection.write(message_id=observe_id, correlation_id=start_id,
                        message_type=_REQUEST, payload=encode_op({
                            "schema": "provider-semantic-observation-v1",
                            "dialogue_id": channel["dialogue_id"], "seq": seq,
                            "operation_ref": channel["operation_ref"],
                            "request_sha256": proposal.request_sha256,
                            "exchange_id": exchange_id,
                            "status": "complete" if 200 <= status < 300 else "refused",
                            "http_status": status, "body_descriptor": description}),
                        deadline=deadline)
                    channel["send_seq"] += 1
                send_batch(stream, self._descriptors([description], proposal.request_id),
                    [BytesSource(raw)], limits=_STREAM_LIMITS)
                frame = self._read_owned(channel, cancel_owner=True)
            value = _control(frame.payload)
            if (frame.envelope.message_type != _RESULT
                    or frame.envelope.correlation_id != start_id or type(value) is not dict
                    or value.get("dialogue_id") != channel["dialogue_id"]
                    or not _sequence(value.get("seq"), channel["receive_seq"])
                    or value.get("operation_ref") != channel["operation_ref"]):
                raise ProviderSemanticError("worker observation is not bound")
            channel["receive_seq"] += 1
            if value.get("schema") == "provider-semantic-proposal-v1":
                expected = {"schema", "dialogue_id", "seq", "operation_ref", "request_sha256",
                            "endpoint", "after_id", "body_descriptor"}
                if (set(value) != expected or proposal.operation != "catalog"
                        or value["request_sha256"] != proposal.request_sha256
                        or value["endpoint"] != "models" or value["body_descriptor"] is not None):
                    raise ProviderSemanticError("next catalog proposal is not bound")
                traversal = advance_catalog(proposal.traversal, parse_model_page(raw))
                next_proposal = ProviderProposal(proposal.request_id, "catalog",
                    proposal.request_sha256, "models", value["after_id"], None, traversal)
                connection.checkpoint()
                channel["proposal"] = next_proposal
                return next_proposal
            expected = {"schema", "dialogue_id", "seq", "operation_ref", "request_sha256",
                        "observation_descriptor"}
            if (set(value) != expected or value.get("schema") != "provider-semantic-final-v1"
                    or value["request_sha256"] != proposal.request_sha256):
                raise ProviderSemanticError("worker final is not closed")
            descriptor = self._descriptors([value["observation_descriptor"]], proposal.request_id)
            if descriptor[0].declared_size > 65_536:
                raise ProviderSemanticError("worker observation exceeds 64KiB")
            observation_sink = BytesSink()
            with channel["owner_lock"]:
                receive_batch(stream, descriptor, [observation_sink], limits=_STREAM_LIMITS)
            if len(observation_sink.value) > 65_536:
                raise ProviderSemanticError("worker observation exceeds 64KiB")
            observed = decode_op(observation_sink.value)
            if (type(observed) is not dict
                    or observed.get("schema") != "provider-semantic-worker-observation-v1"
                    or observed.get("request_sha256") != proposal.request_sha256
                    or observed.get("operation") != proposal.operation):
                raise ProviderSemanticError("worker observation payload is not bound")
            if proposal.operation == "model_step":
                fields = {"schema", "request_sha256", "operation", "reason", "observed_model",
                          "stop_reason", "text_descriptors", "usage"}
                if set(observed) != fields:
                    raise ProviderSemanticError("model observation is not closed")
                descriptors = self._descriptors(observed["text_descriptors"], proposal.request_id)
                sinks = [BytesSink() for _ in descriptors]
                if descriptors:
                    with channel["owner_lock"]:
                        receive_batch(stream, descriptors, sinks, limits=_STREAM_LIMITS)
                result = ProviderObservation(proposal.request_id, "model_step", observed["reason"],
                    True, observed["observed_model"], observed["stop_reason"],
                    tuple(sink.value for sink in sinks), observed["usage"])
                connection.checkpoint()
                return result
            fields = {"schema", "request_sha256", "operation", "complete", "page_sha256s",
                      "model_ids_sha256", "model_count", "reason"}
            if set(observed) != fields:
                raise ProviderSemanticError("catalog observation is not closed")
            traversal = advance_catalog(proposal.traversal, parse_model_page(raw))
            model_ids = traversal.model_ids
            if (not observed["complete"] or observed["page_sha256s"] !=
                    [page.raw_sha256 for page in traversal.pages]
                    or observed["model_count"] != len(model_ids)
                    or observed["model_ids_sha256"] != sha256(canonical_json(
                        list(model_ids))).hexdigest()):
                raise ProviderSemanticError("worker catalog observation disagrees with captured bytes")
            result = ProviderObservation(proposal.request_id, "catalog", observed["reason"], True,
                                         model_ids=model_ids, traversal=traversal)
            connection.checkpoint()
            return result
        except StreamCancelled:
            try:
                self._close(self._channel)
            except BaseException:  # noqa: BLE001, S110 - cancel primary wins
                pass
            self._channel = None
            raise
        except BaseException:
            self._publish_failure(channel)
            try:
                self._close(self._channel)
            except BaseException:  # noqa: BLE001, S110 - preserve operation primary
                pass
            self._channel = None
            raise
        finally:
            if owner_acquired:
                channel["owner_lock"].release()
            if self._channel is not None and self._channel.get("proposal") is proposal:
                self._close(self._channel)
                self._channel = None

    def control(self, request, *, query_state):
        """Route one status/cancel on the authenticated active model dialogue."""
        if self._service is not None:
            return self._service.execute(request, query_state=query_state)
        if (self._channel is None or request.get("operation") not in {"status", "cancel"}):
            raise ProviderSemanticError("no active dialogue for semantic control")
        channel = self._channel
        connection, deadline, start_id = (channel[name] for name in
            ("connection", "deadline", "start_id"))
        pending = None
        owns = False
        try:
            control_id = str(uuid4())
            pending = {
                "request": request,
                "event": threading.Event(),
                "outcome": None,
            }
            with _bounded_lock(channel["write_lock"], deadline):
                with _bounded_lock(channel["state_lock"], deadline):
                    if channel["failed"] or channel["pending_control"] is not None:
                        raise ProviderSemanticError("one semantic control is already pending")
                    channel["pending_control"] = pending
                seq = channel["send_seq"]
                connection.write(message_id=control_id, correlation_id=start_id,
                    message_type=_REQUEST, payload=encode_op({
                        "schema": "provider-semantic-control-v1",
                        "dialogue_id": channel["dialogue_id"], "seq": seq,
                        "operation_ref": channel["operation_ref"], "request": request,
                    "query_state": query_state}), deadline=deadline)
                channel["send_seq"] += 1
            owns = channel["owner_lock"].acquire(blocking=False)
            if owns:
                try:
                    while not pending["event"].is_set():
                        self._read_owned(channel, cancel_owner=False,
                                         stop_after_control=pending)
                finally:
                    channel["owner_lock"].release()
            elif not pending["event"].wait(deadline.remaining()):
                if channel["state_lock"].acquire(blocking=False):
                    try:
                        channel["failed"] = True
                        if pending["outcome"] is None:
                            pending["outcome"] = (
                                "error",
                                _OwnedConnectionError(
                                    "owned_connection_unavailable"
                                ),
                            )
                    finally:
                        channel["state_lock"].release()
                pending["event"].set()
                try:
                    self._close(channel)
                except BaseException:  # noqa: BLE001, S110 - timeout remains primary
                    pass
                self._channel = None
            outcome = pending["outcome"]
            if outcome is None:
                raise _OwnedConnectionError("owned_connection_unavailable")
            kind, value = outcome
            if kind == "error":
                raise value
            observation = value
            output = {name: item for name, item in observation.items() if name != "operation"}
            result = {"request_id": request["request_id"], "operation": request["operation"],
                      "terminal": "succeeded", "output": output, "artifacts": []}
            if request["operation"] == "cancel" and output.get("cancel_state") == "accepted":
                if owns:
                    self._close(
                        self._channel, after_control_observation=True
                    )
                    self._channel = None
            return result
        except BaseException as error:
            if pending is not None and not pending["event"].is_set():
                try:
                    with _bounded_lock(channel["state_lock"], deadline):
                        channel["failed"] = True
                        if pending["outcome"] is None:
                            pending["outcome"] = (
                                "error",
                                _OwnedConnectionError(
                                    "owned_connection_unavailable"
                                ),
                            )
                    pending["event"].set()
                except BaseException:  # noqa: BLE001, S110 - preserve control primary
                    pass
            try:
                self._close(self._channel)
            except BaseException:  # noqa: BLE001, S110 - preserve operation primary
                pass
            self._channel = None
            raise
        finally:
            if pending is not None:
                try:
                    with _bounded_lock(channel["state_lock"], deadline):
                        if channel.get("pending_control") is pending:
                            channel["pending_control"] = None
                except BaseException:  # noqa: BLE001, S110 - channel already failed
                    pass

    def execute(self, request, **kwargs):
        try:
            if request.get("operation") in {"model_step", "catalog"}:
                return self.begin(request, **kwargs)
            if self._service is not None:
                return self._service.execute(request, **kwargs)
            connection, deadline = self._open(
                kwargs.pop("deadline_end_monotonic", None)
            )
            try:
                message_id, dialogue_id = str(uuid4()), str(uuid4())
                operation_ref = kwargs.get("operation_ref")
                config = kwargs.get("config")
                connection.write(message_id=message_id, correlation_id=None, message_type=_REQUEST,
                    payload=encode_op({"schema": "provider-semantic-begin-v1",
                        "dialogue_id": dialogue_id, "seq": 0, "operation_ref": operation_ref,
                        "config": config, "request": request, "frozen_descriptor": None,
                        "input_descriptors": [], "query_state": kwargs.get("query_state")}),
                    deadline=deadline)
                frame = connection.read()
                self._authenticated_session = self._session_observation(frame)
                value = _control(frame.payload)
                if (frame.envelope.message_type != _RESULT
                        or frame.envelope.correlation_id != message_id
                        or type(value) is not dict
                        or set(value) != {"schema", "dialogue_id", "seq", "operation_ref",
                                              "request_sha256", "observation_descriptor"}
                        or value["schema"] != "provider-semantic-final-v1"
                        or value["dialogue_id"] != dialogue_id
                        or not _sequence(value["seq"], 0)
                        or value["operation_ref"] != operation_ref
                        or value["request_sha256"] != request_digest(request)):
                    raise ProviderSemanticError("worker result is not bound")
                descriptor = self._descriptors([value["observation_descriptor"]],
                                               request["request_id"])
                if descriptor[0].declared_size > 65_536:
                    raise ProviderSemanticError("worker observation exceeds 64KiB")
                sink = BytesSink()
                receive_batch(ConnectionStreamTransport(connection, message_type=_ARTIFACT,
                    correlation_id=message_id, deadline=deadline), descriptor, [sink],
                    limits=_STREAM_LIMITS)
                if len(sink.value) > 65_536:
                    raise ProviderSemanticError("worker observation exceeds 64KiB")
                observed = decode_op(sink.value)
                expected = {"schema", "request_sha256", "operation"}
                if (type(observed) is not dict or not expected.issubset(observed)
                        or observed["schema"] != "provider-semantic-worker-observation-v1"
                        or observed["request_sha256"] != request_digest(request)
                        or observed["operation"] != request["operation"]):
                    raise ProviderSemanticError("worker result payload is not bound")
                output = (observed["output"] if request["operation"] == "capabilities" else
                          {name: item for name, item in observed.items()
                           if name not in expected})
                connection.checkpoint()
                result = {"request_id": request["request_id"], "operation": request["operation"],
                          "terminal": "succeeded", "output": output, "artifacts": []}
            except BaseException:
                try:
                    self._close(connection)
                except BaseException:  # noqa: BLE001, S110 - preserve operation primary
                    pass
                raise
            else:
                self._close(connection)
                return result
        except _OwnedConnectionError as error:
            if error.cleanup_failure:
                raise
            return {"request_id": request.get("request_id"), "operation": request.get("operation"),
                    "terminal": "failed", "output": {}, "artifacts": []}
        except (ProviderSemanticError, broker.BrokerError):
            return {"request_id": request.get("request_id"), "operation": request.get("operation"),
                    "terminal": "failed", "output": {}, "artifacts": []}


__all__ = ["ProviderPortClient"]
