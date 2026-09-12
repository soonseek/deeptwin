"""Bounded, lifespan-owned handoff from committed commands to worker IPC.

The service reserves finite in-process capacity before the root transaction and accepts
the transaction's exact one-shot capability only after commit.  Its worker threads do
not retry, infer semantic success, or settle usage.  Every terminal transport
observation is written to the runtime ledger before the slot is released.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256

from ..domain.refs import DomainContractError, EntityRef, uuid_string
from ..workers import broker
from ..workers.artifact_stream import OfferedBatchPolicy
from .artifact_cas import store_received_artifact
from .ledger import DispatchPermit, LedgerError, RuntimeLedger, TransportObservation
from .worker_coordinator import (
    AuthenticatedWorkerResponse,
    DispatchArtifactInput,
    SelectedDispatchReadCapability,
    WorkerCoordinator,
)


def _inhibit_runtime_dispatch(runtime_ledger: RuntimeLedger) -> bool:
    """Set the exact in-memory safety latch without trusting a public seam.

    Worker threads use the class-owned implementation so an abnormal or
    monkeypatched public notification method cannot kill the thread or leave a
    permit live.  The direct primitive fallback is deliberately non-IO.
    """
    if type(runtime_ledger) is not RuntimeLedger:
        return False
    try:
        RuntimeLedger._inhibit_all_dispatch(runtime_ledger)
    except BaseException:  # noqa: BLE001 - final non-IO safety fallback
        try:
            with runtime_ledger._permit_lock:
                runtime_ledger._global_emergency_inhibited = True
                runtime_ledger._pending_permits.clear()
        except BaseException:  # noqa: BLE001 - never terminate a profile thread
            return False
    return True


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    """Exact post-commit permit/capability pair, or an immutable replay."""

    receipt: dict
    permit: DispatchPermit | None
    replayed: bool
    read_capability: SelectedDispatchReadCapability | None

    def __post_init__(self) -> None:
        if (
            type(self.receipt) is not dict
            or type(self.replayed) is not bool
            or (
                self.replayed
                and (self.permit is not None or self.read_capability is not None)
            )
            or (
                not self.replayed
                and (
                    type(self.permit) is not DispatchPermit
                    or type(self.read_capability)
                    is not SelectedDispatchReadCapability
                    or self.read_capability.permit_id != self.permit.permit_id
                    or self.read_capability.command_id != self.permit.command_id
                    or self.read_capability.resource_ref != self.permit.envelope_ref
                    or self.read_capability.principal is not self.permit.principal
                    or self.read_capability.grant is not self.permit.grant
                )
            )
        ):
            raise TypeError("Dispatch outcome capability binding is invalid")


class WorkerDispatchError(RuntimeError):
    """Sanitized dispatcher failure."""


class WorkerDispatchUnavailable(WorkerDispatchError):
    pass


class WorkerDispatchBusy(WorkerDispatchError):
    pass


@dataclass(frozen=True, slots=True)
class DispatchReservation:
    """One non-transferable pre-commit capacity reservation."""

    command_id: str
    profile_ref: EntityRef
    deadline: broker.Deadline
    _service_token: object = field(repr=False, compare=False)
    _slot_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            uuid_string(self.command_id)
        except (DomainContractError, TypeError, ValueError):
            raise TypeError("Dispatch reservation command identity is invalid") from None
        if (
            type(self.profile_ref) is not EntityRef
            or self.profile_ref.kind != "runtime_profile"
            or type(self.deadline) is not broker.Deadline
            or type(self._service_token) is not object
            or type(self._slot_token) is not object
        ):
            raise TypeError("Dispatch reservation is invalid")

    def __copy__(self) -> object:
        raise TypeError("Dispatch reservation is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("Dispatch reservation is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("Dispatch reservation is not serializable")


_ACCEPTANCE_CONSTRUCTION_TOKEN = object()


class DispatchAcceptance:
    """Immutable one-shot proof issued only after an atomic queue transfer."""

    __slots__ = (
        "__claim_lock",
        "__claimed",
        "__permit",
        "__service_token",
        "__slot_token",
        "command_id",
        "deadline",
        "permit_id",
        "profile_ref",
    )

    def __init__(
        self,
        command_id: str,
        permit: DispatchPermit,
        profile_ref: EntityRef,
        deadline: broker.Deadline,
        service_token: object,
        slot_token: object,
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _ACCEPTANCE_CONSTRUCTION_TOKEN:
            raise TypeError("Dispatch acceptance cannot be constructed externally")
        try:
            uuid_string(command_id)
        except (DomainContractError, TypeError, ValueError):
            raise TypeError("Dispatch acceptance identity is invalid") from None
        if (
            type(permit) is not DispatchPermit
            or permit.command_id != command_id
            or type(profile_ref) is not EntityRef
            or profile_ref.kind != "runtime_profile"
            or permit.profile_ref != profile_ref
            or type(deadline) is not broker.Deadline
            or type(service_token) is not object
            or type(slot_token) is not object
        ):
            raise TypeError("Dispatch acceptance is invalid")
        object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "permit_id", permit.permit_id)
        object.__setattr__(self, "profile_ref", profile_ref)
        object.__setattr__(self, "deadline", deadline)
        object.__setattr__(self, "_DispatchAcceptance__service_token", service_token)
        object.__setattr__(self, "_DispatchAcceptance__slot_token", slot_token)
        object.__setattr__(self, "_DispatchAcceptance__permit", permit)
        object.__setattr__(self, "_DispatchAcceptance__claim_lock", threading.Lock())
        object.__setattr__(self, "_DispatchAcceptance__claimed", False)

    @classmethod
    def _issue(
        cls,
        *,
        command_id: str,
        permit: DispatchPermit,
        profile_ref: EntityRef,
        deadline: broker.Deadline,
        service_token: object,
        slot_token: object,
    ) -> DispatchAcceptance:
        return cls(
            command_id,
            permit,
            profile_ref,
            deadline,
            service_token,
            slot_token,
            _construction_token=_ACCEPTANCE_CONSTRUCTION_TOKEN,
        )

    def _claim(
        self,
        *,
        service_token: object,
        slot_token: object,
        permit: DispatchPermit,
        command_id: str,
        profile_ref: EntityRef,
        deadline: broker.Deadline,
    ) -> bool:
        if type(self) is not DispatchAcceptance:
            return False
        with self.__claim_lock:
            if self.__claimed:
                return False
            if (
                self.__service_token is not service_token
                or self.__slot_token is not slot_token
                or self.__permit is not permit
                or self.command_id != command_id
                or self.command_id != permit.command_id
                or self.permit_id != permit.permit_id
                or self.profile_ref != profile_ref
                or self.profile_ref != permit.profile_ref
                or self.deadline is not deadline
            ):
                return False
            object.__setattr__(self, "_DispatchAcceptance__claimed", True)
            return True

    def _is_claimed_for(
        self,
        *,
        service_token: object,
        slot_token: object,
        permit: DispatchPermit,
        deadline: broker.Deadline,
    ) -> bool:
        if type(self) is not DispatchAcceptance:
            return False
        with self.__claim_lock:
            return (
                self.__claimed
                and self.__service_token is service_token
                and self.__slot_token is slot_token
                and self.__permit is permit
                and self.command_id == permit.command_id
                and self.permit_id == permit.permit_id
                and self.profile_ref == permit.profile_ref
                and self.deadline is deadline
            )

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("Dispatch acceptance is immutable")

    def __repr__(self) -> str:
        return "<DispatchAcceptance redacted>"

    def __copy__(self) -> object:
        raise TypeError("Dispatch acceptance is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("Dispatch acceptance is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("Dispatch acceptance is not serializable")


@dataclass(frozen=True, slots=True)
class _DispatchItem:
    permit: DispatchPermit
    capability: SelectedDispatchReadCapability
    deadline: broker.Deadline
    slot_token: object
    artifact_inputs: tuple[DispatchArtifactInput, ...] = ()
    artifact_output_policy: OfferedBatchPolicy | None = None


class WorkerDispatchService:
    """One serial worker thread and one bounded queue per exact runtime profile."""

    def __init__(self, *, runtime_ledger: RuntimeLedger,
                 coordinators: tuple[WorkerCoordinator, ...]) -> None:
        if (
            type(runtime_ledger) is not RuntimeLedger
            or type(coordinators) is not tuple
            or not coordinators
            or len(coordinators) > 64
            or any(type(item) is not WorkerCoordinator for item in coordinators)
        ):
            raise TypeError("Worker dispatcher requires bounded exact coordinators")
        routes: dict[EntityRef, WorkerCoordinator] = {}
        channel_ids: set[str] = set()
        declared_pair_roots = set()
        resolved_pair_roots = set()
        socket_endpoints = set()
        service_pairs: set[tuple[str, str]] = set()
        secret_digests: set[bytes] = set()
        requester_boot_ids: set[str] = set()
        worker_boot_ids: set[str] = set()
        for coordinator in coordinators:
            route = coordinator._route
            channel = route.channel_spec
            pair_root = channel.pair_root
            try:
                # This is a construction-time collision key, not an authorization
                # decision.  The broker still opens each configured component with
                # O_NOFOLLOW at use time.  Resolving here prevents lexical aliases
                # from creating two process-local coordinators for one endpoint.
                resolved_pair_root = pair_root.resolve(strict=False)
            except (OSError, RuntimeError):
                raise TypeError(
                    "Worker dispatcher route binding is duplicated or foreign"
                ) from None
            socket_endpoint = resolved_pair_root / channel.socket_name
            service_pair = (channel.requester_service, channel.responder_service)
            secret_digest = sha256(coordinator._secret._material()).digest()
            if (
                coordinator._ledger is not runtime_ledger
                or route.profile_ref in routes
                or channel.channel_id in channel_ids
                or pair_root in declared_pair_roots
                or resolved_pair_root in resolved_pair_roots
                or socket_endpoint in socket_endpoints
                or service_pair in service_pairs
                or secret_digest in secret_digests
                or coordinator._requester_boot_id in requester_boot_ids
                or coordinator._worker_boot_id in worker_boot_ids
            ):
                raise TypeError("Worker dispatcher route binding is duplicated or foreign")
            routes[route.profile_ref] = coordinator
            channel_ids.add(channel.channel_id)
            declared_pair_roots.add(pair_root)
            resolved_pair_roots.add(resolved_pair_root)
            socket_endpoints.add(socket_endpoint)
            service_pairs.add(service_pair)
            secret_digests.add(secret_digest)
            requester_boot_ids.add(coordinator._requester_boot_id)
            worker_boot_ids.add(coordinator._worker_boot_id)
        self._ledger = runtime_ledger
        self._routes = routes
        self._service_token = object()
        self._condition = threading.Condition()
        self._queues = {profile: deque() for profile in routes}
        self._capacity = {
            profile: coordinator._route.channel_spec.max_queue_depth + 1
            for profile, coordinator in routes.items()
        }
        self._occupied = {profile: 0 for profile in routes}
        self._active_deadlines: dict[EntityRef, broker.Deadline | None] = {
            profile: None for profile in routes
        }
        self._active_items: dict[EntityRef, _DispatchItem | None] = {
            profile: None for profile in routes
        }
        self._reservations: dict[object, DispatchReservation] = {}
        self._owned_slots: dict[object, EntityRef] = {}
        self._issued_acceptances: dict[object, DispatchAcceptance] = {}
        self._threads: tuple[threading.Thread, ...] = ()
        self._started = False
        self._closing = False
        self._closed = False

    def assert_components(self, *, domain_store, permission_gate,
                          budget_book, runtime_ledger) -> None:
        if runtime_ledger is not self._ledger:
            raise TypeError("Worker dispatcher runtime ledger binding changed")
        for coordinator in self._routes.values():
            if (
                coordinator._domain is not domain_store
                or coordinator._permission_gate is not permission_gate
                or coordinator._budget is not budget_book
                or coordinator._ledger is not runtime_ledger
            ):
                raise TypeError("Worker dispatcher component binding changed")

    @property
    def started(self) -> bool:
        with self._condition:
            return self._started and not self._closing and not self._closed

    def start(self) -> None:
        try:
            self._ledger.assert_dispatch_session_ready()
        except (LedgerError, TypeError, ValueError):
            raise WorkerDispatchUnavailable() from None
        with self._condition:
            if self._started or self._closing or self._closed:
                raise WorkerDispatchUnavailable()
            if (
                any(self._occupied.values())
                or self._reservations
                or self._owned_slots
                or self._issued_acceptances
                or any(self._queues.values())
                or any(item is not None for item in self._active_items.values())
            ):
                raise WorkerDispatchUnavailable()
            threads = tuple(
                threading.Thread(
                    target=self._run_profile,
                    args=(profile,),
                    name=f"deeptwin-worker-{index}",
                    daemon=False,
                )
                for index, profile in enumerate(self._routes, 1)
            )
            self._threads = threads
            self._started = True
            for thread in threads:
                thread.start()

    def reserve(self, command_id: str, profile_ref: EntityRef, *,
                deadline: broker.Deadline) -> DispatchReservation:
        try:
            uuid_string(command_id)
        except (DomainContractError, TypeError, ValueError):
            raise WorkerDispatchUnavailable() from None
        if type(profile_ref) is not EntityRef or type(deadline) is not broker.Deadline:
            raise WorkerDispatchUnavailable()
        deadline.require()
        try:
            self._ledger.assert_dispatch_session_ready()
        except (LedgerError, TypeError, ValueError):
            raise WorkerDispatchUnavailable() from None
        deadline.require()
        with self._condition:
            if not self._started or self._closing or self._closed:
                raise WorkerDispatchUnavailable()
            if profile_ref not in self._routes:
                raise WorkerDispatchUnavailable()
            if self._occupied[profile_ref] >= self._capacity[profile_ref]:
                raise WorkerDispatchBusy()
            slot_token = object()
            reservation = DispatchReservation(
                command_id,
                profile_ref,
                deadline,
                self._service_token,
                slot_token,
            )
            self._reservations[slot_token] = reservation
            self._owned_slots[slot_token] = profile_ref
            self._occupied[profile_ref] += 1
            return reservation

    def _held(self, reservation: DispatchReservation) -> bool:
        return (
            type(reservation) is DispatchReservation
            and reservation._service_token is self._service_token
            and self._reservations.get(reservation._slot_token) is reservation
        )

    def release(self, reservation: DispatchReservation) -> None:
        with self._condition:
            if not self._held(reservation):
                raise WorkerDispatchUnavailable()
            self._reservations.pop(reservation._slot_token)
            self._owned_slots.pop(reservation._slot_token)
            self._occupied[reservation.profile_ref] -= 1
            self._condition.notify_all()

    def accept(self, reservation: DispatchReservation, outcome: DispatchOutcome, *,
               deadline: broker.Deadline,
               artifact_inputs: tuple[DispatchArtifactInput, ...] = (),
               artifact_output_policy: OfferedBatchPolicy | None = None,
               ) -> DispatchAcceptance:
        committed = (
            type(outcome) is DispatchOutcome
            and not outcome.replayed
            and type(outcome.permit) is DispatchPermit
            and type(outcome.read_capability) is SelectedDispatchReadCapability
            and type(artifact_inputs) is tuple
            and all(
                type(item) is DispatchArtifactInput for item in artifact_inputs
            )
            and (
                artifact_output_policy is None
                or type(artifact_output_policy) is OfferedBatchPolicy
            )
        )
        if not committed:
            raise WorkerDispatchUnavailable()
        permit = outcome.permit
        capability = outcome.read_capability
        with self._condition:
            binding_valid = (
                self._held(reservation)
                and deadline is reservation.deadline
                and permit.command_id == reservation.command_id
                and permit.profile_ref == reservation.profile_ref
                and capability.permit_id == permit.permit_id
                and capability.command_id == permit.command_id
                and capability.principal is permit.principal
                and capability.grant is permit.grant
            )
            if (
                binding_valid
                and self._started
                and not self._closing
                and not self._closed
                and deadline.remaining() > 0.0
            ):
                acceptance = DispatchAcceptance._issue(
                    command_id=permit.command_id,
                    permit=permit,
                    profile_ref=permit.profile_ref,
                    deadline=deadline,
                    service_token=self._service_token,
                    slot_token=reservation._slot_token,
                )
                self._reservations.pop(reservation._slot_token)
                self._queues[reservation.profile_ref].append(_DispatchItem(
                    permit,
                    capability,
                    deadline,
                    reservation._slot_token,
                    artifact_inputs,
                    artifact_output_policy,
                ))
                self._issued_acceptances[reservation._slot_token] = acceptance
                self._condition.notify_all()
                return acceptance
            if binding_valid:
                self._reservations.pop(reservation._slot_token)
                self._owned_slots.pop(reservation._slot_token)
                self._occupied[reservation.profile_ref] -= 1
                self._condition.notify_all()
            else:
                stored = (
                    self._reservations.get(reservation._slot_token)
                    if type(reservation) is DispatchReservation
                    and reservation._service_token is self._service_token
                    else None
                )
                if stored is not None:
                    self._reservations.pop(stored._slot_token)
                    self._owned_slots.pop(stored._slot_token)
                    self._occupied[stored.profile_ref] -= 1
                    self._condition.notify_all()
        # Commit is already durable, so failure to submit can never roll it back or
        # release it as though dispatch never existed.
        self._record_failure(permit, "outcome_unknown")
        raise WorkerDispatchUnavailable()

    def claim_acceptance(
        self,
        acceptance: DispatchAcceptance,
        reservation: DispatchReservation,
        outcome: DispatchOutcome,
        *,
        deadline: broker.Deadline,
    ) -> DispatchAcceptance:
        """Consume the exact proof atomically registered by ``accept``.

        This is receipt validation only.  Worker execution never waits for this
        claim and may already be active or complete when the HTTP owner claims it.
        """
        committed = (
            type(outcome) is DispatchOutcome
            and not outcome.replayed
            and type(outcome.permit) is DispatchPermit
            and type(outcome.read_capability) is SelectedDispatchReadCapability
        )
        if (
            not committed
            or type(acceptance) is not DispatchAcceptance
            or type(reservation) is not DispatchReservation
            or reservation._service_token is not self._service_token
            or deadline is not reservation.deadline
        ):
            raise WorkerDispatchUnavailable()
        permit = outcome.permit
        with self._condition:
            if self._issued_acceptances.get(reservation._slot_token) is not acceptance:
                raise WorkerDispatchUnavailable()
            if not DispatchAcceptance._claim(
                acceptance,
                service_token=self._service_token,
                slot_token=reservation._slot_token,
                permit=permit,
                command_id=reservation.command_id,
                profile_ref=reservation.profile_ref,
                deadline=deadline,
            ):
                raise WorkerDispatchUnavailable()
            claimed = self._issued_acceptances.pop(reservation._slot_token, None)
            if claimed is not acceptance:
                raise WorkerDispatchUnavailable()
            return claimed

    def quarantine(
        self,
        reservation: DispatchReservation,
        outcome: DispatchOutcome,
    ) -> str:
        """Best-effort exact cleanup after an unverifiable post-commit transition."""
        if (
            type(reservation) is not DispatchReservation
            or reservation._service_token is not self._service_token
            or type(outcome) is not DispatchOutcome
            or outcome.replayed
            or type(outcome.permit) is not DispatchPermit
            or outcome.permit.command_id != reservation.command_id
            or outcome.permit.profile_ref != reservation.profile_ref
        ):
            raise WorkerDispatchUnavailable()
        permit = outcome.permit
        with self._condition:
            issued = self._issued_acceptances.pop(
                reservation._slot_token,
                None,
            )
            if self._held(reservation):
                self._reservations.pop(reservation._slot_token)
                self._owned_slots.pop(reservation._slot_token)
                self._occupied[reservation.profile_ref] -= 1
                self._condition.notify_all()
                return "reservation"
            queue = self._queues[reservation.profile_ref]
            for index, item in enumerate(queue):
                if (
                    item.slot_token is reservation._slot_token
                    and item.permit is permit
                ):
                    del queue[index]
                    self._owned_slots.pop(reservation._slot_token)
                    self._occupied[reservation.profile_ref] -= 1
                    self._condition.notify_all()
                    return "queued"
            active = self._active_items[reservation.profile_ref]
            if (
                type(active) is _DispatchItem
                and active.slot_token is reservation._slot_token
                and active.permit is permit
            ):
                return "active"
            if self._owned_slots.get(reservation._slot_token) == reservation.profile_ref:
                self._owned_slots.pop(reservation._slot_token)
                self._occupied[reservation.profile_ref] -= 1
                self._condition.notify_all()
                return "orphan"
            if issued is not None:
                return "completed"
            return "absent"

    def _observation_for_response(
        self,
        permit: DispatchPermit,
        response: AuthenticatedWorkerResponse,
    ) -> TransportObservation:
        return TransportObservation(
            permit_id=permit.permit_id,
            command_id=permit.command_id,
            attempt_id=permit.attempt_id,
            effect="transport_accepted",
            connection_id=response.connection_id,
            worker_boot_id=response.worker_boot_id,
            message_id=response.message_id,
            message_type=response.message_type,
            payload_bytes=len(response.payload),
            payload_sha256=sha256(response.payload).hexdigest(),
        )

    def _record_observation(
        self,
        permit: DispatchPermit,
        observation: TransportObservation,
    ) -> None:
        """Require an exact durable write and its exact immediate projection."""
        bound_record = getattr(self._ledger, "record_transport_observation", None)
        if (
            getattr(bound_record, "__self__", None) is not self._ledger
            or getattr(bound_record, "__func__", None)
            is not RuntimeLedger.record_transport_observation
        ):
            raise WorkerDispatchUnavailable()
        result = RuntimeLedger.record_transport_observation(
            self._ledger,
            permit,
            observation,
        )
        if (
            type(result) is not dict
            or set(result) != {"observation", "attempt"}
            or result["observation"] != observation.as_dict()
            or type(result["attempt"]) is not dict
        ):
            raise WorkerDispatchUnavailable()
        status = RuntimeLedger.dispatch_status(self._ledger, permit.command_id)
        if (
            type(status) is not dict
            or set(status) != {"state", "dispatch", "attempt"}
            or status["attempt"] != result["attempt"]
        ):
            raise WorkerDispatchUnavailable()
        attempt = status["attempt"]
        spec = attempt.get("spec") if type(attempt) is dict else None
        if (
            type(spec) is not dict
            or spec.get("attempt_id") != permit.attempt_id
            or spec.get("profile_ref") != permit.profile_ref.as_dict()
        ):
            raise WorkerDispatchUnavailable()
        if observation.effect == "transport_accepted":
            valid = (
                status["state"] == "running"
                and status["dispatch"] == {
                    "state": "transport_accepted",
                    "effect": "transport_accepted",
                }
                and attempt.get("phase") == "running"
                and attempt.get("dispatch_gate") == "open"
                and attempt.get("send_finality") == "transport_accepted"
                and attempt.get("recovery_state") == "clean"
            )
        elif observation.effect == "definitely_not_sent":
            valid = (
                status["state"] == "blocked"
                and status["dispatch"] == {
                    "state": "recovery_pending",
                    "effect": "definitely_not_sent",
                }
                and attempt.get("phase") == "send_intent"
                and attempt.get("dispatch_gate") == "closed"
                and attempt.get("recovery_state") == "pending"
            )
        else:
            valid = (
                status["state"] == "outcome_unknown"
                and status["dispatch"] == {
                    "state": "recovery_pending",
                    "effect": observation.effect,
                }
                and attempt.get("dispatch_gate") == "closed"
                and attempt.get("recovery_state") == "pending"
            )
        if not valid:
            raise WorkerDispatchUnavailable()

    def _record_failure(self, permit: DispatchPermit, effect: str) -> None:
        try:
            RuntimeLedger.discard_dispatch_permit(self._ledger, permit)
            observation = TransportObservation(
                permit_id=permit.permit_id,
                command_id=permit.command_id,
                attempt_id=permit.attempt_id,
                effect=effect,
                connection_id=None,
                worker_boot_id=None,
                message_id=None,
                message_type=None,
                payload_bytes=None,
                payload_sha256=None,
            )
            self._record_observation(permit, observation)
        except BaseException:  # noqa: BLE001 - crash semantics must fail closed
            _inhibit_runtime_dispatch(self._ledger)

    def _run_profile(self, profile_ref: EntityRef) -> None:
        coordinator = self._routes[profile_ref]
        while True:
            item: _DispatchItem | None = None
            abort = False
            with self._condition:
                while not self._queues[profile_ref] and not self._closing:
                    self._condition.wait()
                if self._queues[profile_ref]:
                    item = self._queues[profile_ref].popleft()
                    abort = self._closing
                    self._active_items[profile_ref] = item
                    self._active_deadlines[profile_ref] = item.deadline
                elif self._closing:
                    return
            assert item is not None
            permit = item.permit
            try:
                if abort:
                    self._record_failure(permit, "outcome_unknown")
                else:
                    try:
                        response = coordinator.exchange(
                            permit,
                            item.capability,
                            deadline=item.deadline,
                            artifact_inputs=item.artifact_inputs,
                            artifact_output_policy=item.artifact_output_policy,
                        )
                    except broker.BrokerError as exc:
                        self._record_failure(permit, exc.dispatch_effect)
                    except BaseException:  # noqa: BLE001 - crash semantics must fail closed
                        self._record_failure(permit, "outcome_unknown")
                    else:
                        try:
                            # Returned bytes must be registered content before the
                            # attempt may claim clean transport acceptance.
                            for artifact in response.artifacts:
                                store_received_artifact(
                                    coordinator._domain,
                                    artifact,
                                    purpose="operational",
                                )
                        except BaseException:  # noqa: BLE001 - unpersisted output fails closed
                            self._record_failure(permit, "outcome_unknown")
                        else:
                            try:
                                RuntimeLedger.discard_dispatch_permit(self._ledger, permit)
                                self._record_observation(
                                    permit,
                                    self._observation_for_response(permit, response),
                                )
                            except BaseException:  # noqa: BLE001 - durable-write failure latch
                                _inhibit_runtime_dispatch(self._ledger)
            finally:
                with self._condition:
                    self._active_items[profile_ref] = None
                    self._active_deadlines[profile_ref] = None
                    self._owned_slots.pop(item.slot_token, None)
                    self._occupied[profile_ref] -= 1
                    self._condition.notify_all()

    def wait_idle(self, deadline: broker.Deadline) -> None:
        if type(deadline) is not broker.Deadline:
            raise WorkerDispatchUnavailable()
        with self._condition:
            while any(self._occupied.values()):
                remaining = deadline.remaining()
                if remaining <= 0.0:
                    raise broker.DeadlineExceeded()
                self._condition.wait(remaining)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closing = True
            # Reservations have no committed outcome and can be released. Accepted
            # queued work remains owned and is recorded as unknown by its profile thread.
            for reservation in tuple(self._reservations.values()):
                self._owned_slots.pop(reservation._slot_token, None)
                self._occupied[reservation.profile_ref] -= 1
            self._reservations.clear()
            # Proofs do not gate workers.  Once shutdown begins they can no longer
            # authorize a successful HTTP handoff and are invalidated immediately.
            self._issued_acceptances.clear()
            self._condition.notify_all()
            threads = self._threads
            accepted_deadline_ends = tuple(
                deadline.end_monotonic
                for deadline in (
                    *(
                        active for active in self._active_deadlines.values()
                        if active is not None
                    ),
                    *(
                        item.deadline
                        for queue in self._queues.values()
                        for item in queue
                    ),
                )
            )
        # Idle coordinators receive only a small lifecycle wake-up bound.  Once
        # accepted work exists, its original absolute route deadline is the hard
        # shutdown bound; close never manufactures execution time beyond it.
        shutdown_end = (
            max(accepted_deadline_ends)
            if accepted_deadline_ends
            else time.monotonic() + 0.1
        )
        for thread in threads:
            thread.join(max(0.0, shutdown_end - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            _inhibit_runtime_dispatch(self._ledger)
            raise WorkerDispatchUnavailable()
        with self._condition:
            if (
                any(self._occupied.values())
                or self._reservations
                or self._owned_slots
                or self._issued_acceptances
                or any(self._queues.values())
                or any(item is not None for item in self._active_items.values())
            ):
                _inhibit_runtime_dispatch(self._ledger)
                raise WorkerDispatchUnavailable()
            self._started = False
            self._closed = True
            self._condition.notify_all()


class WorkerDispatchServiceSlot:
    """Lifespan-only publication point for one fresh dispatcher generation."""

    def __init__(self, *, domain_store, permission_gate, budget_book,
                 runtime_ledger) -> None:
        if type(runtime_ledger) is not RuntimeLedger:
            raise TypeError("Worker dispatcher slot requires exact runtime components")
        self._domain = domain_store
        self._permission_gate = permission_gate
        self._budget = budget_book
        self._ledger = runtime_ledger
        self._condition = threading.Condition()
        self._current: WorkerDispatchService | None = None

    def publish(self, service: WorkerDispatchService) -> None:
        if type(service) is not WorkerDispatchService or not service.started:
            raise WorkerDispatchUnavailable()
        service.assert_components(
            domain_store=self._domain,
            permission_gate=self._permission_gate,
            budget_book=self._budget,
            runtime_ledger=self._ledger,
        )
        with self._condition:
            if self._current is not None:
                raise WorkerDispatchUnavailable()
            self._current = service
            self._condition.notify_all()

    def current(self) -> WorkerDispatchService:
        with self._condition:
            service = self._current
            if type(service) is not WorkerDispatchService or not service.started:
                raise WorkerDispatchUnavailable()
            return service

    def clear(self, service: WorkerDispatchService) -> None:
        with self._condition:
            if self._current is not service:
                raise WorkerDispatchUnavailable()
            self._current = None
            self._condition.notify_all()
