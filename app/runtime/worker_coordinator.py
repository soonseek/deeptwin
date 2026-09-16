"""One-shot authenticated dispatch from the control plane to an isolated worker.

This module consumes an already-authorized, already-budgeted process-local permit.
It rechecks the exact selected read grant around immutable-envelope loading, but it
does not grant authority, reserve budget, settle usage, retry work, or own container
lifecycle.
"""

from __future__ import annotations

import re
import socket
import threading
import weakref
from dataclasses import dataclass, field
from hashlib import sha256

from ..domain.permissions import (
    AccessDenied,
    CorruptPolicy,
    Grant,
    PolicyGate,
    Principal,
)
from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, StorageError
from ..workers import broker
from ..workers.artifact_stream import (
    ArtifactDescriptor,
    ArtifactStreamError,
    BytesSink,
    OfferedBatchPolicy,
    PushbackTransport,
    StreamLimits,
    receive_offered_batch,
    send_batch,
    validate_batch,
)
from ..workers.artifact_stream_transport import FrameCodecTransport
from .budgets import BudgetBook, BudgetError
from .ledger import DispatchPermit, LedgerError, RuntimeLedger

MAX_EXECUTION_ENVELOPE_BYTES = 32 * 1024
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MESSAGE_TYPE = re.compile(r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*\Z")


class WorkerCoordinatorError(broker.BrokerError):
    code = "worker_dispatch_rejected"


class WorkerPayloadRejected(WorkerCoordinatorError):
    code = "worker_payload_rejected"


class WorkerArtifactRejected(WorkerCoordinatorError):
    code = "worker_artifact_rejected"


class WorkerArtifactStreamFailed(WorkerCoordinatorError):
    code = "worker_artifact_stream_failed"


@dataclass(frozen=True, slots=True)
class DispatchArtifactInput:
    """One declared artifact whose bytes travel only over the bounded stream."""

    descriptor: ArtifactDescriptor
    source: object = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.descriptor) is not ArtifactDescriptor or not callable(
            getattr(self.source, "read", None)
        ):
            raise TypeError("Dispatch artifact input is invalid")


@dataclass(frozen=True, slots=True)
class SelectedDispatchReadCapability:
    """Process-local selected grant paired with one committed dispatch permit."""

    permit_id: str
    command_id: str
    principal: Principal = field(repr=False)
    grant: Grant = field(repr=False)
    resource_ref: EntityRef
    purpose: str
    episode_id: str | None

    def __post_init__(self) -> None:
        try:
            uuid_string(self.permit_id)
            uuid_string(self.command_id)
        except (DomainContractError, TypeError, ValueError):
            raise TypeError("Selected dispatch capability identity is invalid") from None
        if (
            type(self.principal) is not Principal
            or type(self.grant) is not Grant
            or type(self.resource_ref) is not EntityRef
            or self.resource_ref.kind != "execution_envelope"
            or self.principal.kind != "runtime"
            or self.principal.purpose != "operational"
            or self.grant.subject_id != self.principal.id
            or self.grant.ref != self.resource_ref
            or self.grant.action != "read"
            or self.grant.purpose != "operational"
            or self.grant.episode_id != self.episode_id
            or self.purpose != "operational"
            or self.episode_id is not None
        ):
            raise TypeError("Selected dispatch capability is not operational read")

    def __copy__(self) -> object:
        raise TypeError("Selected dispatch capability is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("Selected dispatch capability is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("Selected dispatch capability is not serializable")


@dataclass(frozen=True, slots=True)
class WorkerRouteBinding:
    profile_ref: EntityRef
    channel_spec: broker.ChannelSpec
    request_message_type: str
    response_message_types: tuple[str, ...]
    max_execution_envelope_bytes: int = MAX_EXECUTION_ENVELOPE_BYTES
    artifact_stream_message_type: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.profile_ref) is not EntityRef
            or self.profile_ref.kind != "runtime_profile"
            or type(self.channel_spec) is not broker.ChannelSpec
            or type(self.request_message_type) is not str
            or self.request_message_type
            not in self.channel_spec.requester_message_types
            or type(self.response_message_types) is not tuple
            or not self.response_message_types
            or tuple(sorted(set(self.response_message_types)))
            != self.response_message_types
            or not set(self.response_message_types).issubset(
                self.channel_spec.responder_message_types
            )
            or type(self.max_execution_envelope_bytes) is not int
            or not 1
            <= self.max_execution_envelope_bytes
            <= MAX_EXECUTION_ENVELOPE_BYTES
            or self.channel_spec.max_frame_bytes != broker.MAX_FRAME_BYTES
        ):
            raise TypeError("Worker route binding is invalid")
        stream_type = self.artifact_stream_message_type
        if stream_type is not None and (
            type(stream_type) is not str
            or _MESSAGE_TYPE.fullmatch(stream_type) is None
            or stream_type == self.request_message_type
            or stream_type in self.response_message_types
            or stream_type not in self.channel_spec.requester_message_types
            or stream_type not in self.channel_spec.responder_message_types
        ):
            raise TypeError("Worker route binding is invalid")


@dataclass(frozen=True, slots=True)
class ReceivedWorkerArtifact:
    """One worker-returned artifact whose bytes were verified against its offer."""

    descriptor: ArtifactDescriptor
    payload: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.descriptor) is not ArtifactDescriptor
            or type(self.payload) is not bytes
            or len(self.payload) != self.descriptor.declared_size
            or sha256(self.payload).hexdigest() != self.descriptor.sha256
        ):
            raise TypeError("Received worker artifact is invalid")


@dataclass(frozen=True, slots=True, weakref_slot=True)
class AuthenticatedWorkerResponse:
    attempt_id: str
    connection_id: str
    worker_boot_id: str
    message_id: str
    correlation_id: str
    message_type: str
    payload: bytes = field(repr=False)
    artifacts: tuple[ReceivedWorkerArtifact, ...] = ()
    _capture_receipt: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            uuid_string(self.attempt_id)
            uuid_string(self.message_id)
            uuid_string(self.correlation_id)
        except (DomainContractError, TypeError, ValueError):
            raise TypeError("Authenticated worker response identity is invalid") from None
        if (
            type(self.connection_id) is not str
            or _SHA256.fullmatch(self.connection_id) is None
            or type(self.worker_boot_id) is not str
            or _BOOT_ID.fullmatch(self.worker_boot_id) is None
            or type(self.message_type) is not str
            or _MESSAGE_TYPE.fullmatch(self.message_type) is None
            or type(self.payload) is not bytes
            or type(self.artifacts) is not tuple
            or any(
                type(artifact) is not ReceivedWorkerArtifact
                for artifact in self.artifacts
            )
        ):
            raise TypeError("Authenticated worker response is invalid")


class _ResponseReceipt:
    """Coordinator-local provenance, not a Python arbitrary-code-execution sandbox."""

    __slots__ = ("aborted", "captured_ref", "deadline", "fingerprint", "generation",
                 "output_policy_digest", "permit", "response", "route", "token")

    def __init__(self, response, permit, coordinator, deadline, output_policy_digest):
        from .worker_response_capture import _response_fingerprint

        self.response = weakref.ref(response)
        self.permit = weakref.ref(permit)
        self.token = coordinator._response_token
        self.generation = coordinator._ledger._session_id
        self.fingerprint = _response_fingerprint(coordinator, permit, response)
        self.route = coordinator._route
        self.captured_ref = None
        self.aborted = False
        self.deadline = deadline
        self.output_policy_digest = output_policy_digest


def _output_policy_digest(policy):
    if policy is None:
        return sha256(b"null").hexdigest()
    return sha256(canonical_json({"request_id": policy.request_id,
                                 "allowed_media_types": policy.allowed_media_types,
                                 "max_artifacts": policy.max_artifacts})).hexdigest()


class WorkerCoordinator:
    """Consume one exact permit and exchange one authenticated worker message."""

    def __init__(
        self,
        *,
        domain_store: DomainStore,
        permission_gate: PolicyGate,
        runtime_ledger: RuntimeLedger,
        budget_book: BudgetBook,
        route: WorkerRouteBinding,
        boot_secret: broker.BootSecret,
        requester_boot_id: str,
        worker_boot_id: str,
    ) -> None:
        storage = (
            permission_gate._host._storage
            if type(permission_gate) is PolicyGate
            else None
        )
        if (
            type(domain_store) is not DomainStore
            or type(permission_gate) is not PolicyGate
            or storage is None
            or storage.domain_store is not domain_store
            or type(runtime_ledger) is not RuntimeLedger
            or runtime_ledger._domain is not domain_store
            or type(budget_book) is not BudgetBook
            or budget_book.path != domain_store.path
            or budget_book._domain.data_dir != domain_store.data_dir
            or type(route) is not WorkerRouteBinding
            or type(boot_secret) is not broker.BootSecret
            or type(requester_boot_id) is not str
            or _BOOT_ID.fullmatch(requester_boot_id) is None
            or type(worker_boot_id) is not str
            or _BOOT_ID.fullmatch(worker_boot_id) is None
            or requester_boot_id == worker_boot_id
        ):
            raise TypeError("Worker coordinator components are not exactly bound")
        self._domain = domain_store
        self._permission_gate = permission_gate
        self._ledger = runtime_ledger
        self._budget = budget_book
        self._route = route
        self._secret = boot_secret
        self._requester_boot_id = requester_boot_id
        self._worker_boot_id = worker_boot_id
        self._response_token = object()
        self._response_lock = threading.RLock()
        self._response_slot = threading.BoundedSemaphore(1)
        self._active_responses = {}
        self._admission = broker.AdmissionGate(
            max_queue_depth=route.channel_spec.max_queue_depth
        )

    def _checked_response_receipt(self, permit, response):
        from .worker_response_capture import _response_fingerprint

        receipt = getattr(response, "_capture_receipt", None)
        if (type(response) is not AuthenticatedWorkerResponse
                or type(permit) is not DispatchPermit or type(receipt) is not _ResponseReceipt
                or receipt.response() is not response or receipt.permit() is not permit
                or receipt.token is not self._response_token or receipt.aborted
                or receipt.generation != self._ledger._session_id
                or receipt.route is not self._route
                or receipt.fingerprint != _response_fingerprint(self, permit, response)
                or (receipt.captured_ref is None
                    and self._active_responses.get(id(response)) is not receipt)):
            raise WorkerCoordinatorError(dispatch_effect="outcome_unknown")
        return receipt

    def capture_response(self, permit, response):
        """Persist only the exact response authenticated by this coordinator."""
        from .worker_response_capture import _capture_authenticated

        with self._response_lock:
            receipt = self._checked_response_receipt(permit, response)
            try:
                ref = _capture_authenticated(self, permit, response, receipt)
                receipt.captured_ref = ref
                return ref
            except BaseException:  # noqa: BLE001 - unknown capture commit must inhibit dispatch
                # A receive/commit failure is uncertain. No retry/resend authority.
                RuntimeLedger._inhibit_all_dispatch(self._ledger)
                receipt.aborted = True
                try:
                    from .worker_response_capture import (
                        _lookup_response_capture,
                        _response_content,
                    )

                    committed = _lookup_response_capture(self._ledger, permit.command_id)
                    if (committed is not None
                            and self._domain.get(committed).body["content"]
                            == _response_content(self, permit, response)):
                        receipt.captured_ref = committed
                        receipt.aborted = False
                except Exception:  # noqa: BLE001, S110 - retain sanitized uncertainty, never log bytes
                    pass
                raise WorkerCoordinatorError(dispatch_effect="outcome_unknown") from None
            finally:
                if self._active_responses.pop(id(response), None) is not None:
                    self._response_slot.release()

    def abort_response(self, response):
        """Release a received response's active admission and revoke fresh capture."""
        with self._response_lock:
            receipt = self._active_responses.pop(id(response), None)
            if receipt is not None:
                receipt.aborted = True
                self._response_slot.release()

    def _validate_capability(
        self,
        permit: DispatchPermit,
        capability: SelectedDispatchReadCapability,
    ) -> None:
        if (
            type(permit) is not DispatchPermit
            or type(capability) is not SelectedDispatchReadCapability
            or capability.permit_id != permit.permit_id
            or capability.command_id != permit.command_id
            or capability.resource_ref != permit.envelope_ref
            or permit.principal is not capability.principal
            or permit.grant is not capability.grant
            or permit.principal_id != capability.principal.id
            or permit.grant_id != capability.grant.id
            or permit.envelope_ref.kind != "execution_envelope"
            or permit.profile_ref != self._route.profile_ref
        ):
            raise WorkerCoordinatorError()

    def _load_payload(
        self,
        permit: DispatchPermit,
        capability: SelectedDispatchReadCapability,
    ) -> bytes:
        ref = permit.envelope_ref

        def loader(exact_ref: EntityRef) -> bytes:
            stored = self._domain.get(exact_ref)
            verified = ImmutableRecord.from_bytes(
                stored.body_bytes,
                expected_ref=exact_ref,
            )
            body = verified.body
            if (
                type(stored) is not ImmutableRecord
                or stored != verified
                or verified.ref != ref
                or body["kind"] != "execution_envelope"
                or body["purpose"] != "operational"
                or sha256(verified.body_bytes).hexdigest() != ref.sha256
                or len(verified.body_bytes)
                > self._route.max_execution_envelope_bytes
            ):
                raise WorkerPayloadRejected()
            return verified.body_bytes

        try:
            payload = self._permission_gate.read(
                capability.principal,
                ref,
                purpose=capability.purpose,
                grants=(capability.grant,),
                episode_id=capability.episode_id,
                loader=loader,
            )
        except WorkerCoordinatorError:
            raise
        except (
            AccessDenied,
            CorruptPolicy,
            DomainContractError,
            StorageError,
            KeyError,
            TypeError,
            ValueError,
        ):
            raise WorkerPayloadRejected() from None
        if type(payload) is not bytes:
            raise WorkerPayloadRejected()
        return payload

    def _validate_artifact_inputs(
        self,
        permit: DispatchPermit,
        artifact_inputs: tuple[DispatchArtifactInput, ...],
    ) -> None:
        if type(artifact_inputs) is not tuple:
            raise WorkerArtifactRejected()
        if not artifact_inputs:
            return
        if self._route.artifact_stream_message_type is None:
            raise WorkerArtifactRejected()
        descriptors = []
        for item in artifact_inputs:
            if (
                type(item) is not DispatchArtifactInput
                or item.descriptor.request_id != permit.command_id
            ):
                raise WorkerArtifactRejected()
            descriptors.append(item.descriptor)
        try:
            validate_batch(descriptors, StreamLimits())
        except (ArtifactStreamError, TypeError, ValueError):
            raise WorkerArtifactRejected() from None

    def _validate_artifact_output_policy(
        self,
        permit: DispatchPermit,
        policy: OfferedBatchPolicy | None,
    ) -> None:
        if policy is None:
            return
        if (
            type(policy) is not OfferedBatchPolicy
            or self._route.artifact_stream_message_type is None
            or policy.request_id != permit.command_id
        ):
            raise WorkerArtifactRejected()

    def exchange(
        self,
        permit: DispatchPermit,
        capability: SelectedDispatchReadCapability,
        *,
        deadline: broker.Deadline,
        artifact_inputs: tuple[DispatchArtifactInput, ...] = (),
        artifact_output_policy: OfferedBatchPolicy | None = None,
    ) -> AuthenticatedWorkerResponse:
        """Perform one transport exchange; semantic acceptance remains upstream."""

        if type(deadline) is not broker.Deadline:
            raise WorkerCoordinatorError()
        self._validate_capability(permit, capability)
        self._validate_artifact_inputs(permit, artifact_inputs)
        self._validate_artifact_output_policy(permit, artifact_output_policy)
        output_policy_digest = _output_policy_digest(artifact_output_policy)
        operation_deadline = deadline.bounded(
            self._route.channel_spec.max_operation_ms
        )
        admission = self._admission.acquire(operation_deadline)
        sock: socket.socket | None = None
        codec: broker.FrameCodec | None = None
        claimed = False
        issued = False
        try:
            claimed = self._response_slot.acquire(blocking=False)
            if not claimed:
                raise WorkerCoordinatorError()
            try:
                window = self._ledger.consume_dispatch_permit_window(
                    permit,
                    budget_book=self._budget,
                )
            except (LedgerError, BudgetError, TypeError, ValueError):
                raise WorkerCoordinatorError() from None
            effective = broker.Deadline(
                min(
                    operation_deadline.end_monotonic,
                    window.deadline_end_monotonic,
                )
            )
            effective.require()
            payload = self._load_payload(permit, capability)
            effective.require()
            sock, _, _ = broker.connect_verified(
                self._route.channel_spec,
                local_service=self._route.channel_spec.requester_service,
                deadline=effective,
            )
            session = broker.client_handshake(
                sock,
                self._route.channel_spec,
                self._secret,
                requester_boot_id=self._requester_boot_id,
                responder_boot_id=self._worker_boot_id,
                deadline=effective,
            )
            if (
                session.requester_boot_id != self._requester_boot_id
                or session.responder_boot_id != self._worker_boot_id
            ):
                raise broker.AuthenticationError()
            codec = broker.FrameCodec(
                self._route.channel_spec,
                session,
                local_service=self._route.channel_spec.requester_service,
            )
            codec.write(
                sock,
                message_id=permit.command_id,
                correlation_id=permit.attempt_id,
                message_type=self._route.request_message_type,
                payload=payload,
                deadline=effective,
            )
            if artifact_inputs:
                transport = FrameCodecTransport(
                    codec,
                    sock,
                    message_type=self._route.artifact_stream_message_type,
                    correlation_id=permit.command_id,
                    deadline=effective,
                )
                try:
                    send_batch(
                        transport,
                        [item.descriptor for item in artifact_inputs],
                        [item.source for item in artifact_inputs],
                        limits=StreamLimits(),
                    )
                except Exception:  # noqa: BLE001 - effect-preserving barrier
                    # Any failure past the request frame — a stream violation or a
                    # foreign source/transport exception — has an unknown effect.
                    raise WorkerArtifactStreamFailed(
                        dispatch_effect="outcome_unknown"
                    ) from None
            frame = codec.read(sock, deadline=effective)
            received_artifacts: tuple[ReceivedWorkerArtifact, ...] = ()
            if (
                artifact_output_policy is not None
                and type(frame) is broker.ReceivedFrame
                and type(frame.envelope) is broker.FrameEnvelope
                and frame.envelope.message_type
                == self._route.artifact_stream_message_type
            ):
                if frame.envelope.correlation_id != permit.command_id:
                    raise broker.ProtocolViolation(
                        dispatch_effect="outcome_unknown"
                    )
                transport = PushbackTransport(
                    FrameCodecTransport(
                        codec,
                        sock,
                        message_type=self._route.artifact_stream_message_type,
                        correlation_id=permit.command_id,
                        deadline=effective,
                    ),
                    first=frame.payload,
                )
                try:
                    admitted = receive_offered_batch(
                        transport,
                        artifact_output_policy,
                        lambda _descriptor: BytesSink(),
                        limits=StreamLimits(),
                    )
                    received_artifacts = tuple(
                        ReceivedWorkerArtifact(
                            descriptor=descriptor, payload=sink.value
                        )
                        for descriptor, sink in admitted
                    )
                except Exception:  # noqa: BLE001 - effect-preserving barrier
                    raise WorkerArtifactStreamFailed(
                        dispatch_effect="outcome_unknown"
                    ) from None
                frame = codec.read(sock, deadline=effective)
            if (
                type(frame) is not broker.ReceivedFrame
                or type(frame.envelope) is not broker.FrameEnvelope
                or type(frame.payload) is not bytes
                or frame.envelope.correlation_id != permit.command_id
                or frame.envelope.message_type
                not in self._route.response_message_types
            ):
                raise broker.ProtocolViolation(dispatch_effect="outcome_unknown")
            response = AuthenticatedWorkerResponse(
                attempt_id=permit.attempt_id,
                connection_id=session.connection_id,
                worker_boot_id=session.responder_boot_id,
                message_id=frame.envelope.message_id,
                correlation_id=frame.envelope.correlation_id,
                message_type=frame.envelope.message_type,
                payload=frame.payload,
                artifacts=received_artifacts,
            )
            if _output_policy_digest(artifact_output_policy) != output_policy_digest:
                raise WorkerArtifactRejected(dispatch_effect="outcome_unknown")
            receipt = _ResponseReceipt(response, permit, self, effective, output_policy_digest)
            with self._response_lock:
                self._active_responses[id(response)] = receipt
                object.__setattr__(response, "_capture_receipt", receipt)
                issued = True
            return response
        finally:
            if claimed and not issued:
                self._response_slot.release()
            if codec is not None:
                codec.close()
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            admission.release()
