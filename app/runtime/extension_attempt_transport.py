"""The real attempt transport over the extension worker channel (T087/T018
slice; the callable `NodeAttemptDispatcher` takes in place of a test fake).

One call performs one authenticated AF_UNIX exchange under the one-shot
permit: connect to the slot's staged worker, write the execute request for
the bound operation (identities and references only; the frame's message id
is the send-intent command id), read the one reply, verify the correlation,
attempt, operation and nonce, recheck the fences, and map the reply to the
ledger's result vocabulary. A succeeded reply's output is sealed
control-side as an immutable `artifact` record — the worker never touches
the store — and its reference is the transport result; admission still
happens only through `accept_result_and_settle`. Any failure raises a typed
error, which the dispatcher records as `outcome_unknown` (the send may have
started). No provider, model, effort or paid call is involved: the only
operations a worker offers today are the read-class queries `status` and
`describe_tools` (over an empty tool table).
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from ..deployment.stage_observer import _process_boot_id
from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore
from ..workers import broker, ipc_root, listener
from ..workers.extension_channel import ExtensionChannelError, extension_channel
from ..workers.extension_execute_messages import (
    MAX_REMAINING_MS,
    OPERATIONS,
    REPLY_SCHEMA,
    ExecuteMessageError,
    encode_execute_request,
    parse_execute_reply,
    peek_schema,
)
from .budgets import BudgetUsage
from .ledger import ConsumedDispatchWindow, DispatchPermit
from .node_attempts import AttemptDispatchRequest, AttemptTransportResult

__all__ = [
    "OUTPUT_SCHEMA",
    "ExtensionAttemptTransport",
    "ExtensionTransportError",
    "sealed_artifact_identity",
]

OUTPUT_SCHEMA = "extension-execute-output-v1"
RESULT_TYPE = "extension-result-v1"
REQUEST_TYPE = "extension-request-v1"
ATTEMPT_MS = 2_000  # probe contract §4: the control attempt window
CODES = frozenset({
    "transport_unavailable", "transport_deadline", "transport_invalid", "transport_mismatch",
    "seal_failed",
})
_NONCE_BYTES = 32
_MAX_SLOT = 64


_EFFECTS = frozenset({"definitely_not_sent", "may_have_started", "outcome_unknown"})


class ExtensionTransportError(RuntimeError):
    """Closed error family: one code and the dispatch effect control can vouch
    for (`definitely_not_sent` before any write; the broker's own effect after
    it; `outcome_unknown` otherwise). The dispatcher records every failure as an
    unknown outcome today: no ledger path reopens a post-intent attempt."""

    __slots__ = ("code", "dispatch_effect")

    def __init__(self, code: str, *, dispatch_effect: str = "outcome_unknown") -> None:
        if code not in CODES or dispatch_effect not in _EFFECTS:
            raise ValueError("unknown transport error code")
        super().__init__(code)
        self.code = code
        self.dispatch_effect = dispatch_effect


def sealed_artifact_identity(send_command_id) -> str:
    """The one artifact id a succeeded execute of one send-intent command seals:
    addressable from the command, so an orphan (a crash between the seal and the
    acceptance) is findable and never multiplied."""

    uuid_string(send_command_id)
    return str(uuid5(NAMESPACE_URL, f"deeptwin:artifact:execute:{send_command_id}"))


def _unsent(deadline, code_if_open="transport_unavailable"):
    return ExtensionTransportError(
        "transport_deadline" if deadline.remaining() <= 0 else code_if_open,
        dispatch_effect="definitely_not_sent",
    )


# the read-class queries whose usage control measures itself (never trusted)
_CONTROL_MEASURED = frozenset({"status", "describe_tools"})


class ExtensionAttemptTransport:
    """Built only by `build`; one bound operation over one extension slot."""

    __slots__ = ("_attempt_ms", "_domain", "_instance_id", "_operation", "_slot_number")

    def __init__(self) -> None:
        raise TypeError("Use ExtensionAttemptTransport.build")

    @classmethod
    def build(cls, *, domain_store, instance_id, slot_number, operation="status",
              attempt_ms=ATTEMPT_MS):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(instance_id) is not str or not instance_id:
            raise TypeError("instance id must be a string")
        if type(slot_number) is not int or not 1 <= slot_number <= _MAX_SLOT:
            raise ValueError("slot number out of bounds")
        if type(operation) is not str or operation not in OPERATIONS:
            raise ValueError("operation must be a tool-port-v1 operation")
        if type(attempt_ms) is not int or not 1 <= attempt_ms <= 30_000:
            raise ValueError("attempt window out of bounds")
        transport = object.__new__(cls)
        transport._domain = domain_store
        transport._instance_id = instance_id
        transport._slot_number = slot_number
        transport._operation = operation
        transport._attempt_ms = attempt_ms
        return transport

    @property
    def operation(self) -> str:
        return self._operation

    def __call__(self, permit, request, window) -> AttemptTransportResult:
        if type(permit) is not DispatchPermit:
            raise TypeError("Exact DispatchPermit required")
        if type(request) is not AttemptDispatchRequest:
            raise TypeError("Exact AttemptDispatchRequest required")
        if type(window) is not ConsumedDispatchWindow or window.permit is not permit:
            raise TypeError("The consumed window of this exact permit is required")
        if (permit.attempt_id != request.attempt_id
                or permit.execution_id != request.execution_id
                or permit.envelope_ref != request.envelope_ref
                or permit.profile_ref != request.profile_ref):
            raise ExtensionTransportError("transport_mismatch",
                                          dispatch_effect="definitely_not_sent")
        # the exchange lives inside the consumed window and the attempt budget,
        # whichever ends first; an exhausted window never connects
        deadline = broker.Deadline(min(
            broker.Deadline.after_ms(self._attempt_ms).end_monotonic,
            window.deadline_end_monotonic,
        ))
        remaining_ms = int(deadline.remaining() * 1_000)
        if remaining_ms <= 0:
            raise ExtensionTransportError("transport_deadline",
                                          dispatch_effect="definitely_not_sent")
        try:
            root, spec = extension_channel(
                instance_id=self._instance_id, slot_number=self._slot_number
            )
        except (ExtensionChannelError, DomainContractError, ValueError, TypeError):
            raise ExtensionTransportError("transport_invalid",
                                          dispatch_effect="definitely_not_sent") from None
        challenge = os.urandom(_NONCE_BYTES)
        try:
            payload = encode_execute_request(
                attempt_id=request.attempt_id, execution_id=request.execution_id,
                operation=self._operation, envelope_ref=request.envelope_ref,
                profile_ref=request.profile_ref,
                remaining_ms=min(remaining_ms, MAX_REMAINING_MS), challenge=challenge,
            )
        except ExecuteMessageError:
            raise ExtensionTransportError("transport_invalid",
                                          dispatch_effect="definitely_not_sent") from None
        try:
            connection = listener._connect_extension_authenticated(
                root, spec, requester_boot_id=_process_boot_id(), deadline=deadline
            )
        except (broker.BrokerError, listener.ListenerError, ipc_root.IpcRootError,
                OSError):
            raise _unsent(deadline) from None  # nothing was written yet
        try:
            reply = self._exchange(connection, permit, request, payload, challenge, deadline)
        finally:
            try:
                connection.close()
            except OSError:
                pass  # a close fault cannot unmake a reply already in hand
        return self._result(permit, request, reply)

    def _exchange(self, connection, permit, request, payload, challenge, deadline):
        message_id = permit.command_id
        try:
            connection.write(
                message_id=message_id, correlation_id=None, message_type=REQUEST_TYPE,
                payload=payload, deadline=deadline,
            )
        except broker.BrokerError as error:
            # the broker vouches for the effect of an interrupted write
            raise ExtensionTransportError(
                "transport_deadline" if isinstance(error, broker.DeadlineExceeded)
                else "transport_unavailable", dispatch_effect=error.dispatch_effect,
            ) from None
        except (listener.ListenerError, ipc_root.IpcRootError, OSError):
            raise ExtensionTransportError("transport_unavailable",
                                          dispatch_effect="may_have_started") from None
        try:
            frame = connection.read(deadline=deadline)
            connection.recheck()
        except broker.DeadlineExceeded:
            raise ExtensionTransportError("transport_deadline") from None
        except (broker.ProtocolViolation, broker.AuthenticationError):
            # the worker was reached and authenticated and answered outside the framing
            raise ExtensionTransportError("transport_invalid") from None
        except (broker.BrokerError, listener.ListenerError, ipc_root.IpcRootError,
                OSError):
            raise ExtensionTransportError(
                "transport_deadline" if deadline.remaining() <= 0 else "transport_unavailable"
            ) from None
        envelope = frame.envelope
        if (envelope.message_type != RESULT_TYPE or envelope.correlation_id != message_id
                or envelope.message_id == message_id):
            raise ExtensionTransportError("transport_invalid")
        try:
            if peek_schema(frame.payload) != REPLY_SCHEMA:
                raise ExtensionTransportError("transport_invalid")
            reply = parse_execute_reply(frame.payload)
        except ExecuteMessageError:
            raise ExtensionTransportError("transport_invalid") from None
        if (reply.attempt_id != request.attempt_id or reply.operation != self._operation
                or reply.challenge != challenge):
            raise ExtensionTransportError("transport_mismatch")
        return reply

    def _result(self, permit, request, reply) -> AttemptTransportResult:
        usage = None
        if (self._operation in _CONTROL_MEASURED and reply.outcome in ("succeeded", "failed")
                and reply.usage is None):
            # a completed read-class query has no unknown usage: control measures
            # it, so a claim of unknown finality is a dodge, not an observation
            raise ExtensionTransportError("transport_mismatch")
        if reply.usage is not None:
            if self._operation in _CONTROL_MEASURED and reply.usage != {
                "model_calls": 0, "tool_calls": 0, "node_visits": 1, "loop_rounds": 0,
                "output_bytes": 0 if reply.output is None else len(canonical_json(reply.output)),
                "candidates": 0, "api_microunits": None,
            }:
                # a read-class query (`status`, `describe_tools`) makes no model or
                # tool call and control measures its only real counter itself:
                # any other claim is a lie
                raise ExtensionTransportError("transport_mismatch")
            try:
                usage = BudgetUsage.create(**reply.usage)
            except (TypeError, ValueError):
                raise ExtensionTransportError("transport_invalid") from None
        result_ref = None
        if reply.outcome == "succeeded":
            result_ref = self._seal(permit, request, reply)
        return AttemptTransportResult(
            outcome=reply.outcome, result_ref=result_ref,
            usage_finality=reply.usage_finality,
            remote_terminal_observed=reply.remote_terminal_observed,
            reason_code=reply.reason_code, usage=usage,
        )

    def _seal(self, permit, request, reply) -> EntityRef:
        """Seal the operation's output as an immutable artifact of this vault,
        descending from the attempt's envelope; the worker never writes here."""

        try:
            roots = self._domain.roots()
            record = ImmutableRecord.create(
                kind="artifact", id=sealed_artifact_identity(permit.command_id), version=1,
                created_at_utc=datetime.fromtimestamp(time.time(), UTC).strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"),
                actor_ref=roots.actor, parent_refs=(request.envelope_ref,),
                purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={
                    "schema_version": OUTPUT_SCHEMA,
                    "operation": reply.operation,
                    "attempt_id": request.attempt_id,
                    "execution_id": request.execution_id,
                    "send_command_id": permit.command_id,
                    "output": reply.output,
                },
            )
            self._domain.put(record)
        except Exception:  # noqa: BLE001 - the store's detail stays private
            raise ExtensionTransportError("seal_failed") from None
        return record.ref
