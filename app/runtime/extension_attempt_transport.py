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
started). No provider, model, effort or paid call is involved: a worker offers
the read-class queries `status` and `describe_tools` and `invoke_tool` over its
two-tool table (`text_profile`, `text_normalize`: deterministic read-effect
readings; the second returns its derived text over the reverse leg).
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import NAMESPACE_URL, uuid4, uuid5

from ..deployment.stage_observer import _process_boot_id
from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore
from ..extensions.port_contracts import OPERATION_CONTRACTS
from ..workers import broker, ipc_root, listener
from ..workers.artifact_stream import (
    ArtifactStreamError,
    BytesSink,
    BytesSource,
    OfferedBatchPolicy,
    PushbackTransport,
    StreamLimits,
    receive_offered_batch,
    send_batch,
)
from ..workers.artifact_stream_transport import ConnectionStreamTransport
from ..workers.extension_channel import ExtensionChannelError, extension_channel
from ..workers.extension_execute_messages import (
    MAX_INPUT_BYTES,
    MAX_REMAINING_MS,
    MAX_REPLY_BYTES,
    OPERATIONS,
    REPLY_SCHEMA,
    ArtifactInputDeclaration,
    ExecuteMessageError,
    encode_execute_request,
    parse_execute_reply,
    parse_execute_request,
    peek_schema,
)
from .artifact_cas import store_received_artifact
from .budgets import BudgetUsage
from .ledger import (
    TOOL_APPROVAL_EFFECTS,
    ConsumedDispatchWindow,
    DispatchPermit,
    RuntimeLedger,
    ToolCallSpec,
    tool_call_identity,
)
from .node_attempts import AttemptDispatchRequest, AttemptTransportResult
from .worker_coordinator import ReceivedWorkerArtifact

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
    "transport_unavailable", "transport_deadline", "transport_invalid", "transport_stream", "transport_mismatch",
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


# the operations whose usage control verifies itself (never trusted): the
# read-class queries make no call at all; a tool call is exactly one tool call
# (none when the worker refused it before it ran: validation_failed,
# permission_denied)
_CONTROL_MEASURED = frozenset({"status", "describe_tools", "invoke_tool"})
_EXPECTED_TOOL_CALLS = {"status": 0, "describe_tools": 0, "invoke_tool": 1}
_REFUSED_BEFORE_THE_CALL = frozenset({"validation_failed", "permission_denied"})
# the worker's tool table, mirrored statically on control until ToolDefinition
# records exist (pinned equal to the worker's entries by test): what each tool
# takes — so a call declaring other inputs is refused at build, never streamed
# into a worker that would refuse it before reading a byte (control would only
# see the reply mid-stream as an unknown outcome) — and its effect class
TOOL_INPUT_CONTRACTS = MappingProxyType({
    ("text_profile", "1.0.0"): (("document_source", "text/plain"),),
    ("text_normalize", "1.0.0"): (("document_source", "text/plain"),),
})
# what each tool returns over the reverse leg: exactly these (role, media)
# output artifacts, in order; an offered batch for a tool that returns none, or
# not matching, is never admitted
TOOL_OUTPUT_CONTRACTS = MappingProxyType({
    ("text_profile", "1.0.0"): (),
    ("text_normalize", "1.0.0"): (("normalized_text", "text/plain"),),
})
TOOL_EFFECTS = MappingProxyType({("text_profile", "1.0.0"): "read", ("text_normalize", "1.0.0"): "read"})
# the effect gate (ports contract: the ToolDefinition's effect class is authoritative;
# external and instance-critical effects require an explicit action approval; a read
# or reversible effect carries no approval requirement)
APPROVAL_EFFECTS = TOOL_APPROVAL_EFFECTS  # the ledger's, pinned to the ports contract
# what each tool can return in bytes: (growth factor over the input, absolute ceiling)
# — `output_bytes_bound` reserves from both and `_result` enforces the artifact part
# (the tool's derived text is at most three times its input under NFC: the widest
# UTF-8 growth of any code point is 3.0, the U+1D15E–U+1D1C0 musical-symbol family,
# 4 bytes to 12; never over the leg's ceiling)
TOOL_OUTPUT_BOUNDS = MappingProxyType({
    ("text_profile", "1.0.0"): (0, 0),
    ("text_normalize", "1.0.0"): (3, MAX_INPUT_BYTES),
})
ARTIFACT_TYPE = "extension-artifact-v1"
_STREAM_LIMITS = StreamLimits(max_artifact_bytes=MAX_INPUT_BYTES, max_total_bytes=MAX_INPUT_BYTES)


@dataclass(frozen=True, slots=True)
class ExtensionArtifactInput:
    """One artifact control streams to the worker after the request frame:
    its declaration (media type, exact size and digest, role) and its bytes.
    Declared at build for the bound operation; the bytes are held (bounded by
    the input ceiling) so every attempt of the visit — the owner's recovery
    retry included — streams them again from a fresh source, never from a
    consumed one-shot reader."""

    media_type: str
    declared_size: int
    sha256: str
    role: str
    payload: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.payload) is not bytes:
            raise TypeError("an artifact input carries its bytes")
        if (len(self.payload) != self.declared_size
                or hashlib.sha256(self.payload).hexdigest() != self.sha256):
            raise TypeError("an artifact input declaration must be its bytes' own")
        try:
            self.declaration(0, 1)
        except ExecuteMessageError:
            raise TypeError("an artifact input declaration is outside the grammar") from None

    def source(self) -> BytesSource:
        return BytesSource(self.payload)

    def declaration(self, ordinal: int, count: int) -> ArtifactInputDeclaration:
        # validated through the wire grammar so a bad input fails at build, not at send
        request = parse_execute_request(encode_execute_request(
            attempt_id=_PLACEHOLDER, execution_id=_PLACEHOLDER, operation="invoke_tool",
            envelope_ref=EntityRef("execution_envelope", _PLACEHOLDER, 1, "0" * 64),
            profile_ref=EntityRef("runtime_profile", _PLACEHOLDER, 1, "0" * 64),
            remaining_ms=1, challenge=bytes(_NONCE_BYTES), artifact_batch_id=_PLACEHOLDER,
            tool={"tool_id": "placeholder", "version": "0"},
            artifact_inputs=[
                {"ordinal": index, "media_type": self.media_type, "declared_size": self.declared_size,
                 "sha256": self.sha256, "role": self.role} if index == ordinal else
                {"ordinal": index, "media_type": "application/octet-stream", "declared_size": 0,
                 "sha256": "0" * 64, "role": "placeholder"}
                for index in range(count)
            ],
        ))
        return request.artifact_inputs[ordinal]


_PLACEHOLDER = "00000000-0000-4000-8000-000000000000"


class ExtensionAttemptTransport:
    """Built only by `build`; one bound operation over one extension slot."""

    __slots__ = ("_artifact_inputs", "_attempt_ms", "_domain", "_effect_approval_ref", "_instance_id",
                 "_ledger", "_operation", "_slot_number", "_tool")

    def __init__(self) -> None:
        raise TypeError("Use ExtensionAttemptTransport.build")

    @classmethod
    def build(cls, *, domain_store, instance_id, slot_number, operation="status",
              attempt_ms=ATTEMPT_MS, artifact_inputs=(), tool=None, ledger=None,
              effect_approval_ref=None):
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
        if type(artifact_inputs) is not tuple or any(
                type(item) is not ExtensionArtifactInput for item in artifact_inputs):
            raise TypeError("artifact inputs must be a tuple of ExtensionArtifactInput")
        if artifact_inputs:
            # the same gate the worker applies before reading a byte: the operation's
            # port contract must take request artifacts (profile E takes none)
            contract = OPERATION_CONTRACTS[("tool-port-v1", operation)]
            if contract.request_artifact_profile == "E":
                raise ValueError("this operation takes no request artifacts")
            if sum(item.declared_size for item in artifact_inputs) > MAX_INPUT_BYTES:
                raise ValueError("artifact inputs exceed the input byte ceiling")
        if (operation == "invoke_tool") != (tool is not None):
            raise ValueError("invoke_tool names its tool; a query names none")
        if ledger is not None and type(ledger) is not RuntimeLedger:
            raise TypeError("ledger must be the exact RuntimeLedger")
        if effect_approval_ref is not None and (type(effect_approval_ref) is not EntityRef
                                                or effect_approval_ref.kind != "action_approval"):
            raise TypeError("an effect approval is an exact action_approval reference")
        if tool is not None:
            key = (tool.get("tool_id"), tool.get("version")) if type(tool) is dict else None
            if key not in TOOL_INPUT_CONTRACTS:
                raise ValueError("the named tool is not in the worker's table mirror")
            declared = tuple((item.role, item.media_type) for item in artifact_inputs
                             if type(item) is ExtensionArtifactInput)
            if declared != TOOL_INPUT_CONTRACTS[key]:
                raise ValueError("the declared inputs are not the tool's input contract")
            # the effect gate, from the mirror's effect class
            if (TOOL_EFFECTS[key] in APPROVAL_EFFECTS) != (effect_approval_ref is not None):
                raise ValueError("an external effect requires an explicit approval; a read carries none")
        elif effect_approval_ref is not None:
            raise ValueError("a query carries no effect approval")
        if tool is not None:
            if type(tool) is not dict:
                raise TypeError("tool must be a {tool_id, version} mapping")
            try:
                tool = parse_execute_request(encode_execute_request(
                    attempt_id=_PLACEHOLDER, execution_id=_PLACEHOLDER, operation="invoke_tool",
                    envelope_ref=EntityRef("execution_envelope", _PLACEHOLDER, 1, "0" * 64),
                    profile_ref=EntityRef("runtime_profile", _PLACEHOLDER, 1, "0" * 64),
                    remaining_ms=1, challenge=bytes(_NONCE_BYTES), tool=tool,
                )).tool
            except ExecuteMessageError:
                raise ValueError("tool selection is outside the grammar") from None
        transport = object.__new__(cls)
        transport._domain = domain_store
        transport._instance_id = instance_id
        transport._slot_number = slot_number
        transport._operation = operation
        transport._attempt_ms = attempt_ms
        transport._artifact_inputs = artifact_inputs
        transport._tool = tool
        transport._ledger = ledger
        transport._effect_approval_ref = effect_approval_ref
        return transport

    @property
    def operation(self) -> str:
        return self._operation

    @property
    def output_bytes_bound(self) -> int:
        """The most output bytes control will measure for one attempt of this
        bound operation: the reply's canonical output (a closed sub-object of a
        reply frame the grammar accepts only when the raw bytes equal their
        canonical encoding, within the frame's ceiling — so a re-encoding never
        grows past it) plus the output artifacts the tool can return (its stated
        growth over the declared inputs, never over the leg's ceiling; `_result`
        refuses a batch over it). The dispatcher refuses a binding reserving
        less, so an attempt never settles as an accounting overrun that blocks
        the whole budget session."""
        return MAX_REPLY_BYTES + self._artifact_output_bound()

    def _artifact_output_bound(self) -> int:
        if self._tool is None:
            return 0
        growth, ceiling = TOOL_OUTPUT_BOUNDS[(self._tool.tool_id, self._tool.version)]
        return min(growth * sum(item.declared_size for item in self._artifact_inputs), ceiling)

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
        inputs = self._artifact_inputs
        try:
            declarations = [
                item.declaration(index, len(inputs)) for index, item in enumerate(inputs)
            ]
            payload = encode_execute_request(
                attempt_id=request.attempt_id, execution_id=request.execution_id,
                operation=self._operation, envelope_ref=request.envelope_ref,
                profile_ref=request.profile_ref,
                remaining_ms=min(remaining_ms, MAX_REMAINING_MS), challenge=challenge,
                artifact_batch_id=str(uuid4()) if inputs else None,
                artifact_inputs=declarations,
                tool=self._tool,
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
        # the ToolCall's write-ahead intent, recorded before the request frame leaves
        tool_call_id = self._record_tool_call_intent(permit, request, declarations)
        try:
            try:
                reply, received = self._exchange(connection, permit, request, payload, challenge, deadline)
            finally:
                try:
                    connection.close()
                except OSError:
                    pass  # a close fault cannot unmake a reply already in hand
            result = self._result(permit, request, reply, received)
        except ExtensionTransportError as error:
            # a vouched non-send: the call definitely never ran; anything else (a refused
            # reply, a broken exchange): the call's effect is unknown
            self._settle_tool_call(permit, tool_call_id,
                                   "failed" if error.dispatch_effect == "definitely_not_sent" else "unknown",
                                   None)
            raise
        except Exception:
            # any other fault out of the exchange leaves the dispatcher an unknown outcome:
            # the call must not stay an intent on a terminal attempt until the next startup
            self._settle_tool_call(permit, tool_call_id, "unknown", None)
            raise
        # `_result` admits only succeeded|failed for a tool call (anything else is a
        # mismatch above), so the remaining arms are closed by construction
        self._settle_tool_call(permit, tool_call_id,
                               "succeeded" if result.outcome == "succeeded" else "failed",
                               result.result_ref)
        return result

    def _record_tool_call_intent(self, permit, request, declarations):
        """The ToolCall's write-ahead intent, recorded in the ledger before the request
        frame leaves (a failure here is `definitely_not_sent`); nothing when no ledger is
        bound or the operation is not a tool call."""

        if self._ledger is None or self._operation != "invoke_tool":
            return None
        try:
            spec = ToolCallSpec(
                tool_call_id=tool_call_identity(request.attempt_id), attempt_id=request.attempt_id,
                tool_id=self._tool.tool_id, version=self._tool.version,
                effect_class=TOOL_EFFECTS[(self._tool.tool_id, self._tool.version)],
                artifact_inputs=tuple(item.as_dict() for item in declarations),
                approval_ref=self._effect_approval_ref,
            )
            self._ledger.record_tool_call(str(uuid5(NAMESPACE_URL, f"deeptwin:command:tool-call:{permit.command_id}")), spec)
        except Exception:  # noqa: BLE001 - the ledger's detail stays private
            raise ExtensionTransportError("transport_invalid", dispatch_effect="definitely_not_sent") from None
        return spec.tool_call_id

    def _settle_tool_call(self, permit, tool_call_id, outcome, result_ref):
        """Settle the ToolCall from what control observed. A settlement fault after a
        succeeded reply raises `transport_invalid`: the attempt is recorded unknown, the
        call stays intent and the sealed result is not re-linked (open)."""

        if tool_call_id is None:
            return
        try:
            self._ledger.settle_tool_call(
                str(uuid5(NAMESPACE_URL, f"deeptwin:command:tool-call:{permit.command_id}:{outcome}")),
                tool_call_id, outcome=outcome, result_ref=result_ref,
            )
        except Exception:  # noqa: BLE001 - the ledger's detail stays private
            # an unrecordable settlement: control must not claim a result whose call it
            # cannot account for — the attempt is recorded unknown, the call stays intent
            raise ExtensionTransportError("transport_invalid") from None

    def _exchange(self, connection, permit, request, payload, challenge, deadline):
        message_id = permit.command_id
        # the descriptors of the declared batch, from the exact bytes about to be sent
        descriptors = parse_execute_request(payload).artifact_descriptors(message_id)
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
        if self._artifact_inputs:
            # the declared batch follows the request frame on the channel's artifact
            # type. Any failure past the request has an unknown effect: the worker
            # runs the operation only after it accepted the last artifact, so a
            # failure while reading that final acceptance (a deadline, an EOF)
            # leaves the run possible — control cannot tell which side of the
            # acceptance the fault fell on
            try:
                send_batch(
                    ConnectionStreamTransport(connection, message_type=ARTIFACT_TYPE,
                                              correlation_id=message_id, deadline=deadline),
                    descriptors,
                    [item.source() for item in self._artifact_inputs],
                    limits=_STREAM_LIMITS,
                )
            except Exception:  # noqa: BLE001 - effect-preserving barrier
                raise ExtensionTransportError("transport_stream") from None
        received = []
        try:
            frame = connection.read(deadline=deadline)
            if (frame.envelope.message_type == ARTIFACT_TYPE
                    and frame.envelope.correlation_id == message_id):
                # the reverse leg: an offered batch before the reply, admitted only under
                # the named tool's output contract (media types, count, the byte ceiling)
                contract = (TOOL_OUTPUT_CONTRACTS.get((self._tool.tool_id, self._tool.version), ())
                            if self._tool is not None else ())
                if not contract:
                    raise ExtensionTransportError("transport_invalid")
                policy = OfferedBatchPolicy(
                    request_id=message_id,
                    allowed_media_types=tuple(sorted({media for _, media in contract})),
                    max_artifacts=len(contract),
                )
                try:
                    admitted = receive_offered_batch(
                        PushbackTransport(
                            ConnectionStreamTransport(connection, message_type=ARTIFACT_TYPE,
                                                      correlation_id=message_id, deadline=deadline),
                            first=frame.payload,
                        ),
                        policy, lambda _descriptor: BytesSink(), limits=_STREAM_LIMITS,
                    )
                except ArtifactStreamError:
                    raise ExtensionTransportError("transport_stream") from None
                received = [ReceivedWorkerArtifact(descriptor=descriptor, payload=sink.value)
                            for descriptor, sink in admitted]
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
        return reply, received

    def _result(self, permit, request, reply, received=()) -> AttemptTransportResult:
        usage = None
        if received and (self._operation != "invoke_tool" or reply.outcome != "succeeded"):
            raise ExtensionTransportError("transport_invalid")  # artifacts belong to a succeeded tool call
        if self._operation in _CONTROL_MEASURED and reply.outcome not in ("succeeded", "failed"):
            # a read-class query, and an in-process deterministic read-effect tool, has
            # no unknown or cancelled terminal: such an answer dodges the verification
            # (an external-effect tool would be class C for real; none is in the table)
            raise ExtensionTransportError("transport_mismatch")
        if self._operation in _CONTROL_MEASURED and reply.usage is None:
            # a completed query or call has no unknown usage: control measures it,
            # so a claim of unknown finality is a dodge, not an observation
            raise ExtensionTransportError("transport_mismatch")
        if reply.usage is not None:
            refused = reply.outcome == "failed" and reply.reason_code in _REFUSED_BEFORE_THE_CALL
            if self._operation in _CONTROL_MEASURED and reply.usage != {
                "model_calls": 0,
                "tool_calls": 0 if refused else _EXPECTED_TOOL_CALLS[self._operation],
                "node_visits": 1, "loop_rounds": 0,
                "output_bytes": (0 if reply.output is None else len(canonical_json(reply.output)))
                + sum(item.descriptor.declared_size for item in received),
                "candidates": 0, "api_microunits": None,
            }:
                # a read-class query makes no call at all; a tool call is exactly one
                # tool call (none when refused before it ran); control measures the
                # bytes itself (the reply and the artifacts): any other claim is a lie
                raise ExtensionTransportError("transport_mismatch")
            try:
                usage = BudgetUsage.create(**reply.usage)
            except (TypeError, ValueError):
                raise ExtensionTransportError("transport_invalid") from None
        if self._operation == "invoke_tool" and reply.output is not None:
            # the result must be the named tool's, and the facts control already holds
            # about the streamed bytes (digest, size) must agree with its claim; the
            # rest of the result is the worker's claim, sealed as such
            if (reply.output["tool_id"], reply.output["version"]) != (self._tool.tool_id, self._tool.version):
                raise ExtensionTransportError("transport_mismatch")
            if self._tool.tool_id == "text_profile":
                result, (item,) = reply.output["result"], self._artifact_inputs
                if result.get("sha256") != item.sha256 or result.get("byte_count") != item.declared_size:
                    raise ExtensionTransportError("transport_mismatch")
            if self._tool.tool_id == "text_normalize":
                # control holds the input it streamed and the output it admitted: the
                # result's digests, sizes and `changed` are facts, not the worker's claim
                result, (item,) = reply.output["result"], self._artifact_inputs
                if result.get("sha256_in") != item.sha256 or result.get("byte_count_in") != item.declared_size:
                    raise ExtensionTransportError("transport_mismatch")
                if len(received) != 1 or (
                        result.get("sha256_out") != received[0].descriptor.sha256
                        or result.get("byte_count_out") != received[0].descriptor.declared_size
                        or result.get("changed") is not (received[0].payload != item.payload)):
                    raise ExtensionTransportError("transport_mismatch")
            # the bindings must be exactly the tool's output contract over what was admitted
            contract = TOOL_OUTPUT_CONTRACTS[(self._tool.tool_id, self._tool.version)]
            expected = [
                {"ordinal": index, "role": role, "media_type": item.descriptor.media_type,
                 "declared_size": item.descriptor.declared_size, "sha256": item.descriptor.sha256}
                for index, ((role, _media), item) in enumerate(zip(contract, received, strict=False))
            ]
            if len(received) != len(contract) or reply.output["artifacts"] != expected or any(
                    item.descriptor.media_type != media for (_role, media), item in zip(contract, received, strict=True)):
                raise ExtensionTransportError("transport_mismatch")
            # the tool's stated output bound is enforced, not measured: a worker returning
            # more than the growth over its inputs is a mismatch, never an accounting overrun
            if sum(item.descriptor.declared_size for item in received) > self._artifact_output_bound():
                raise ExtensionTransportError("transport_mismatch")
        result_ref = None
        if reply.outcome == "succeeded":
            result_ref = self._seal(permit, request, reply, received)
        return AttemptTransportResult(
            outcome=reply.outcome, result_ref=result_ref,
            usage_finality=reply.usage_finality,
            remote_terminal_observed=reply.remote_terminal_observed,
            reason_code=reply.reason_code, usage=usage,
        )

    def _seal(self, permit, request, reply, received=()) -> EntityRef:
        """Seal the operation's output as an immutable artifact of this vault,
        descending from the attempt's envelope, with each admitted output artifact
        imported as registered content first; the worker never writes here."""

        try:
            roots = self._domain.roots()
            artifacts = []
            for index, item in enumerate(received):
                blob = store_received_artifact(self._domain, item, purpose="operational")
                artifacts.append({"ordinal": index, "role": reply.output["artifacts"][index]["role"],
                                  "media_type": item.descriptor.media_type, "blob": blob.as_dict()})
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
                    "artifacts": artifacts,
                },
            )
            self._domain.put(record)
        except Exception:  # noqa: BLE001 - the store's detail stays private
            raise ExtensionTransportError("seal_failed") from None
        return record.ref
