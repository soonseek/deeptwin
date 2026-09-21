"""Authenticated serial no-network private provider transformation service.

The owned connection supplies all upstream bytes. Proposals and results are
inert observations, not admissions, provider calls, current catalogs or billing.
"""

from __future__ import annotations
import secrets
import threading
from hashlib import sha256
from uuid import uuid4

from ..adapters.claude_protocol import SSEDecoder
from ..deployment.files import RetainedHandle
from . import broker, ipc_root, listener
from . import provider_metadata as metadata, provider_messages as wire
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
from .provider_transform import (
    CatalogAccumulator,
    TextResponseAccumulator,
    UnsupportedProfile,
    prepare_text,
    result_bytes,
    unsuccessful,
)

REQUEST_TYPE = "extension-request-v1"
RESULT_TYPE = "extension-result-v1"
ARTIFACT_TYPE = "extension-artifact-v1"
_STREAM_LIMITS = StreamLimits(
    max_artifact_bytes=wire.MAX_BLOB,
    max_total_bytes=wire.MAX_BLOB,
    max_chunk_bytes=16384,
)


class ProviderServiceError(RuntimeError):
    code = "provider service error"

    def __init__(self):
        super().__init__(self.code)


class ProviderServiceBusy(ProviderServiceError):
    code = "provider service busy"


class ProviderServiceClosed(ProviderServiceError):
    code = "provider service closed"


_SANITIZED = (
    broker.BrokerError,
    listener.ListenerError,
    ipc_root.IpcRootError,
    metadata.ProviderMetadataError,
    wire.ProviderMessageError,
    ArtifactStreamError,
    ExtensionChannelError,
    OSError,
    ValueError,
    TypeError,
)


class _BudgetConnection:
    """One accounting owner for bidirectional authenticated PAYLOAD bytes.

    Artifact base64, offers, credit and acknowledgements count once. Decoded
    blobs do not count a second time. The underlying connection remains owned.
    """

    def __init__(self, connection):
        self.connection = connection
        self.total = 0

    def _charge(self, payload):
        self.total += len(payload)
        if self.total > wire.MAX_DIALOGUE:
            raise ProviderServiceError()

    def write(self, **kwargs):
        self._charge(kwargs["payload"])
        return self.connection.write(**kwargs)

    def read(self, **kwargs):
        frame = self.connection.read(**kwargs)
        self._charge(frame.payload)
        return frame

    def recheck(self):
        self.connection.recheck()


class _Dialogue:
    def __init__(self, connection, deadline):
        self.connection = connection
        self.deadline = deadline
        self.seen = set()
        self.start_id = self.dialogue_id = None

    def fresh(self, value):
        wire.uuid(value)
        wire.require(value not in self.seen and len(self.seen) < 256)
        self.seen.add(value)
        return value

    def new_id(self):
        # Finite collision handling; never spin on a broken entropy source.
        for _ in range(4):
            value = str(uuid4())
            if value not in self.seen:
                return self.fresh(value)
        raise ProviderServiceError()

    def fence(self):
        self.deadline.require()
        self.connection.recheck()

    def read(self, *, schema=None, first=False):
        self.fence()
        frame = self.connection.read(deadline=self.deadline)
        envelope = frame.envelope
        wire.require(
            envelope.message_type == REQUEST_TYPE
            and envelope.correlation_id == (None if first else self.start_id)
        )
        self.fresh(envelope.message_id)
        value = wire.parse_control(frame.payload)
        if schema is not None:
            wire.require(value["schema"] == schema)
        if not first:
            wire.require(value.get("dialogue_id") == self.dialogue_id)
        return envelope.message_id, value

    def write(self, value, *, correlation=None):
        self.fence()
        message_id = self.new_id()
        self.connection.write(
            message_id=message_id,
            correlation_id=correlation or self.start_id,
            message_type=RESULT_TYPE,
            payload=wire.encode_control(value),
            deadline=self.deadline,
        )
        self.fence()
        return message_id

    def description(self, raw):
        return {
            "batch_id": self.new_id(),
            "size": len(raw),
            "sha256": sha256(raw).hexdigest(),
            "media_type": "application/json",
        }

    def stream(self, announcing, descriptions, *, raw=None):
        descriptors = [
            ArtifactDescriptor(
                batch_id=value["batch_id"],
                request_id=announcing,
                ordinal=n,
                count=len(descriptions),
                media_type=value["media_type"],
                declared_size=value["size"],
                sha256=value["sha256"],
            )
            for n, value in enumerate(descriptions)
        ]
        transport = ConnectionStreamTransport(
            self.connection,
            message_type=ARTIFACT_TYPE,
            correlation_id=announcing,
            deadline=self.deadline,
        )
        self.fence()
        if raw is None:
            sinks = [BytesSink() for _ in descriptors]
            receive_batch(transport, descriptors, sinks, limits=_STREAM_LIMITS)
            result = tuple(sink.value for sink in sinks)
        else:
            send_batch(
                transport,
                descriptors,
                [BytesSource(value) for value in raw],
                limits=_STREAM_LIMITS,
            )
            result = None
        self.fence()  # includes the final batch acknowledgement
        return result


class ProviderWorkerService(RetainedHandle):
    __slots__ = ("_closed", "_listener", "_lock", "_source")

    def __init__(self):
        raise TypeError("Use open_provider_worker_service")

    @property
    def closed(self):
        return self._closed

    @property
    def listener(self):
        return self._listener

    def _listener_verifies(self):
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

    def serve_one(self, deadline):
        if type(deadline) is not broker.Deadline:
            raise ProviderServiceError()
        if not self._lock.acquire(blocking=False):
            raise ProviderServiceBusy()
        try:
            if self._closed:
                raise ProviderServiceClosed()
            try:
                connection = listener._accept_extension_authenticated(
                    self._listener, deadline=deadline, connection_ms=30000
                )
                try:
                    self._serve(_BudgetConnection(connection), connection.deadline)
                except BaseException:
                    # Cleanup must not hide the failure that decides whether the
                    # owning service is poisoned or interrupted and must close.
                    try:
                        connection.close()
                    except BaseException:
                        pass
                    raise
                else:
                    connection.close()
                    return 1
            except BaseException as error:
                if (
                    not isinstance(error, Exception)
                    or self._source.closed
                    or (
                        isinstance(error, listener.ListenerError)
                        and not self._listener_verifies()
                    )
                ):
                    self._close_locked(suppress=True)
                if isinstance(error, _SANITIZED):
                    raise ProviderServiceError() from None
                raise
        finally:
            self._lock.release()

    def _measure(self, dialogue):
        dialogue.fence()
        # Source applies its own 500ms read ceiling to this unchanged deadline.
        result = self._source.read_current(deadline=dialogue.deadline)
        dialogue.fence()
        return result

    def _serve(self, connection, deadline):
        d = _Dialogue(connection, deadline)
        first_id, start = d.read(first=True)
        if start["schema"] == "provider-worker-identify-v1":
            reading = self._measure(d)
            d.write(
                {
                    "schema": "provider-worker-identity-v1",
                    "challenge": start["challenge"],
                    "service_identity": self._listener.spec.responder_service,
                    "build_identity_digest": reading.build_identity.digest,
                    "port_schema_set_digest": reading.build_identity.schema_set_digest,
                    "platform": reading.platform,
                    "uid": reading.uid,
                    "gid": reading.gid,
                    "worker_profile": wire.PROFILE,
                    "implemented_transforms": ["catalog", "text"],
                },
                correlation=first_id,
            )
            return
        wire.require(start["schema"] == "provider-transform-start-v1")
        d.deadline = deadline.bounded(start["remaining_ms"])
        d.start_id, d.dialogue_id = first_id, start["dialogue_id"]
        operation = start["operation"]
        d.fresh(start["plan"]["batch_id"])
        d.write(
            {
                "schema": "provider-transform-ready-v1",
                "dialogue_id": d.dialogue_id,
                "phase": "plan",
            }
        )
        plan_raw = d.stream(first_id, [start["plan"]])[0]
        plan = wire.parse_plan(plan_raw, operation)
        plan_digest = sha256(plan_raw).hexdigest()
        d.write(
            {
                "schema": "provider-transform-ready-v1",
                "dialogue_id": d.dialogue_id,
                "phase": "inputs",
            }
        )
        input_id, inputs = d.read(schema="provider-transform-inputs-v1")
        raw_inputs = ()
        if operation == "catalog":
            wire.require(inputs["batch_id"] is None)
        else:
            d.fresh(inputs["batch_id"])
            descriptions = [
                {"batch_id": inputs["batch_id"], **entry, "media_type": "text/plain"}
                for entry in plan["inputs"]
            ]
            raw_inputs = d.stream(input_id, descriptions)
        # Validate UTF8 and prepare privately before publishing any projection.
        body = None
        overflow = False
        if operation == "text":
            try:
                body = prepare_text(plan, raw_inputs)
            except UnsupportedProfile:
                overflow = True
        self._measure(d)
        if overflow:
            observation = unsuccessful(
                "text", "unsupported", plan["model_id"], state="unsupported_profile"
            )
            self._final(d, operation, plan_digest, observation)
            return
        catalog = CatalogAccumulator() if operation == "catalog" else None
        cursor = None
        for step in range(1, 21):
            description = d.description(body) if body is not None else None
            projection_id = d.write(
                {
                    "schema": "provider-transform-projection-v1",
                    "dialogue_id": d.dialogue_id,
                    "step": step,
                    "endpoint": "messages" if operation == "text" else "models",
                    "after_id": cursor,
                    "body": description,
                }
            )
            if description is not None:
                d.stream(projection_id, [description], raw=(body,))
            response_id, response = d.read(schema="provider-transform-response-v1")
            wire.require(response["step"] == step)
            if response["status"] != "supplied":
                observation = unsuccessful(
                    operation,
                    "upstream_unavailable"
                    if response["status"] == "unavailable"
                    else "truncated",
                    plan.get("model_id"),
                    prior=catalog.finish() if catalog is not None else None,
                )
                self._measure(d)
                self._final(d, operation, plan_digest, observation)
                return
            description = response["body"]
            wire.descriptor(
                description,
                "text/event-stream" if operation == "text" else "application/json",
            )
            d.fresh(description["batch_id"])
            raw = d.stream(response_id, [description])[0]
            if operation == "text":
                observation = self._parse_text(plan["model_id"], raw, d.deadline)
                cursor = None
            else:
                d.deadline.require()
                cursor = catalog.accept_page(raw)
                d.deadline.require()
                observation = catalog.finish()
            self._measure(d)
            if cursor is None:
                self._final(d, operation, plan_digest, observation)
                return
        raise ProviderServiceError()  # accumulator enforces the last-page cap first

    @staticmethod
    def _parse_text(model, raw, deadline):
        accumulator = TextResponseAccumulator(model)
        decoder = SSEDecoder()
        try:
            for offset in range(0, len(raw), 16384):
                deadline.require()
                steps = iter(decoder.feed(raw[offset : offset + 16384]))
                while True:
                    deadline.require()
                    try:
                        event = next(steps)
                    except StopIteration:
                        break
                    if event is not None:
                        accumulator.accept(event)
                    if accumulator.invalid:
                        return accumulator.finish()
            deadline.require()
            list(decoder.finish())
            deadline.require()
        except ValueError:
            # Includes ProtocolError and JSON integer-conversion failures.
            # Deadline/integrity errors are transport RuntimeErrors, not data.
            accumulator.fail()
        return accumulator.finish()

    def _final(self, d, operation, plan_digest, observation):
        raw = result_bytes(operation, plan_digest, observation)
        description = d.description(raw)
        final_id = d.write(
            {
                "schema": "provider-transform-final-v1",
                "dialogue_id": d.dialogue_id,
                "result": description,
            }
        )
        d.stream(final_id, [description], raw=(raw,))

    def _close_locked(self, *, suppress):
        if self._closed:
            return
        self._closed = True
        error = None
        try:
            self._listener.close()
        except BaseException as caught:
            error = caught
        try:
            self._source.close()
        except BaseException as caught:
            error = error or caught
        if error is not None and not suppress:
            if isinstance(error, Exception):
                raise ProviderServiceError() from None
            raise error

    def close(self):
        if not self._lock.acquire(blocking=False):
            raise ProviderServiceBusy()
        try:
            self._close_locked(suppress=False)
        finally:
            self._lock.release()

    def __enter__(self):
        if self._closed:
            raise ProviderServiceClosed()
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.close()
        except BaseException:
            if value is None:
                raise


def open_provider_worker_service(*, instance_id, slot_number):
    source = worker = None
    try:
        root, spec = extension_channel(instance_id=instance_id, slot_number=slot_number)
        source = metadata.open_provider_metadata_source()
        worker = listener.bind_worker_listener(
            root, spec, responder_boot_id=secrets.token_hex(32)
        )
        service = object.__new__(ProviderWorkerService)
        service._closed = False
        service._lock = threading.Lock()
        service._source, service._listener = source, worker
        return service
    except BaseException as error:
        for handle in (worker, source):
            if handle is not None:
                try:
                    handle.close()
                except BaseException:
                    pass
        if isinstance(error, _SANITIZED):
            raise ProviderServiceError() from None
        raise
