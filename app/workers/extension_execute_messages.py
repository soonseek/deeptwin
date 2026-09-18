"""The closed execute request/reply grammar of the extension worker channel
(contracts/extension-worker-probe.md §3: the first authenticated application
frame selects the mode by its exact request schema; the message types stay
the channel's `extension-request-v1` / `extension-result-v1`).

`extension-execute-v1` carries identities and references only: the attempt,
its execution, the requested operation (a member of the port's closed
operation set), the envelope and runtime-profile references, the requester's
remaining window in milliseconds (never an absolute clock value) and a fresh
nonce. `extension-execute-result-v1` carries the runtime
ledger's result vocabulary — outcome, usage finality, remote terminal
observation, typed reason, the exact usage counters iff the usage is final —
and, for a success, the output whose grammar the reply's operation selects
(`status`: the worker's own reading; `describe_tools`: its tool table). The
worker package never imports the runtime: the closed sets are mirrored here
and pinned equal by test.

Canonical strict JSON, byte-equal on reparse, bounded by the same wire
limits as the probe grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.wire import WireInputError, WireLimits, parse_json_object
from ..extensions.port_contracts import EFFECT_CLASSES
from .artifact_stream import ArtifactDescriptor, ArtifactStreamError
from .extension_probe_messages import (
    OPERATIONS,
    _component,
    _encode,
    _identifier,
    _nonce_bytes,
    _nonce_text,
    _parse_nonce,
    _runtime,
)
from .extension_probe_messages import (
    REPLY_SCHEMA as PROBE_REPLY_SCHEMA,
)
from .extension_probe_messages import (
    REQUEST_SCHEMA as PROBE_REQUEST_SCHEMA,
)

__all__ = [
    "MAX_ARTIFACT_INPUTS",
    "MAX_INPUT_BYTES",
    "MAX_REMAINING_MS",
    "MAX_REPLY_BYTES",
    "MAX_REQUEST_BYTES",
    "MAX_ROLES",
    "MAX_TOOLS",
    "MAX_TOOLS_BYTES",
    "OPERATIONS",
    "OUTCOMES",
    "OUTPUT_OPERATIONS",
    "REASONS",
    "REMOTE_TERMINALS",
    "REPLY_SCHEMA",
    "REQUEST_SCHEMA",
    "USAGE_FIELDS",
    "USAGE_FINALITIES",
    "ArtifactInputDeclaration",
    "ExecuteMessageError",
    "ExecuteReply",
    "ExecuteRequest",
    "encode_execute_reply",
    "encode_execute_request",
    "parse_execute_reply",
    "parse_execute_request",
    "peek_schema",
]

REQUEST_SCHEMA = "extension-execute-v1"
REPLY_SCHEMA = "extension-execute-result-v1"
MAX_REQUEST_BYTES = 4_096  # since the artifact leg: up to eight declared inputs
MAX_REPLY_BYTES = 4_096
_MAX_UINT32 = 2**32 - 1
# mirrored from app/runtime/ledger.py (pinned equal by test); never imported
OUTCOMES = frozenset({
    "succeeded", "failed", "denied", "timed_out", "cancelled", "outcome_unknown",
})
REMOTE_TERMINALS = OUTCOMES | frozenset({"not_observed"})
USAGE_FINALITIES = frozenset({"final", "provisional", "unknown"})
REASONS = frozenset({
    "provider_terminal", "validation_failed", "permission_denied", "deadline",
    "transport_failure", "transport_unknown", "cancel_requested",
    "restart_reconciliation",
})
USAGE_FIELDS = (
    "model_calls", "tool_calls", "node_visits", "loop_rounds", "output_bytes",
    "candidates", "api_microunits",
)
_REF_FIELDS = ("kind", "id", "version", "sha256")
_REQUEST_FIELDS = (
    "schema_version", "attempt_id", "execution_id", "operation", "envelope_ref",
    "profile_ref", "remaining_ms", "challenge", "artifact_batch_id", "artifact_inputs",
)
MAX_REMAINING_MS = 30_000  # the channel's operation cap
# the request's declared artifact inputs (T018/T087 artifact leg): descriptors
# only — the bytes travel after the request frame over the channel's artifact
# type through the digest/chunk/credit stream, bounded by the ports contract's
# `max_input_bytes` ceiling and admitted into owned in-memory sinks
_ARTIFACT_INPUT_FIELDS = ("ordinal", "media_type", "declared_size", "sha256", "role")
MAX_ARTIFACT_INPUTS = 8
MAX_INPUT_BYTES = 1_048_576  # per artifact and for the batch (extension-ports.md resource_limits)
_PLACEHOLDER_ID = "00000000-0000-4000-8000-000000000000"
_REPLY_FIELDS = (
    "schema_version", "attempt_id", "operation", "challenge", "outcome",
    "usage_finality", "remote_terminal_observed", "reason_code", "usage", "output",
)
_OUTPUT_FIELDS = ("service_identity", "component", "runtime")
# `describe_tools` output (extension-ports.md §3.2): the worker's actual tool table
_TOOL_FIELDS = ("tool_id", "version", "argument_schema_ref", "result_schema_ref",
                "effect_class", "artifact_roles")
_TOOLS_FIELDS = ("tools",)
# the wire's version text is narrower than the ports contract's `version-text`
# (no spaces or parentheses, 64 chars), as the identifier is narrower than its
# `identifier` (probe contract §2); both narrowings are stated in §2b
_VERSION_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}")
MAX_TOOLS = 8  # entries; the binding bound is the bytes below
MAX_ROLES = 256  # artifact roles per entry (ports contract: T[] up to 256)
# a grammar-maximal entry is ~1.2 KB: the table is bounded by the canonical
# bytes the 4096 B reply can carry beside its other fields, checked where the
# table is validated so a worker refuses instead of failing to answer
MAX_TOOLS_BYTES = 3_072
# the operations whose successful output has a closed grammar here; a success
# under any other operation is outside the grammar until its output is defined
OUTPUT_OPERATIONS = frozenset({"status", "describe_tools"})
_KNOWN_SCHEMAS = frozenset({
    PROBE_REQUEST_SCHEMA, PROBE_REPLY_SCHEMA, REQUEST_SCHEMA, REPLY_SCHEMA,
})


def _limits(max_bytes: int) -> WireLimits:
    # the probe limits, two levels deeper: the reply nests the runtime's
    # operation list under the output (depth 5) and a tool entry's schema
    # references under the tool table (depth 6)
    return WireLimits(
        max_bytes=max_bytes,
        max_depth=6,
        max_items=128,
        max_members=16,
        max_string_bytes=128,
        max_integer=_MAX_UINT32,
    )


class ExecuteMessageError(ValueError):
    """The bytes or values are outside the closed execute grammar."""

    def __init__(self, *_ignored) -> None:
        # copy/pickle re-invoke __init__ with the stored args: accept and drop them
        super().__init__("invalid execute message")


@dataclass(frozen=True, slots=True)
class ArtifactInputDeclaration:
    """One declared request artifact: its position, media type, exact size and
    digest, and the role it plays for the operation (ports contract artifact roles)."""

    ordinal: int
    media_type: str
    declared_size: int
    sha256: str
    role: str

    def as_dict(self) -> dict:
        return {"ordinal": self.ordinal, "media_type": self.media_type,
                "declared_size": self.declared_size, "sha256": self.sha256, "role": self.role}


# nonces never appear in logs: the values hide them from repr/str
@dataclass(frozen=True, slots=True)
class ExecuteRequest:
    attempt_id: str
    execution_id: str
    operation: str
    envelope_ref: EntityRef
    profile_ref: EntityRef
    remaining_ms: int
    challenge: bytes = field(repr=False)
    artifact_batch_id: str | None = None
    artifact_inputs: tuple[ArtifactInputDeclaration, ...] = ()

    def artifact_descriptors(self, request_id: str) -> list[ArtifactDescriptor]:
        """The stream descriptors of the declared batch under this request's id
        (the request frame's message id, known to both ends)."""

        request_id = _uuid(request_id)
        if not self.artifact_inputs:
            return []
        return [
            ArtifactDescriptor(
                batch_id=self.artifact_batch_id, request_id=request_id,
                ordinal=item.ordinal, count=len(self.artifact_inputs),
                media_type=item.media_type, declared_size=item.declared_size,
                sha256=item.sha256,
            )
            for item in self.artifact_inputs
        ]


@dataclass(frozen=True, slots=True)
class ExecuteReply:
    attempt_id: str
    operation: str
    challenge: bytes = field(repr=False)
    outcome: str = "outcome_unknown"
    usage_finality: str = "unknown"
    remote_terminal_observed: str = "not_observed"
    reason_code: str = "transport_unknown"
    usage: dict | None = None
    output: dict | None = None


def _wrap(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (DomainContractError, ValueError, TypeError):
        raise ExecuteMessageError() from None


def _uuid(value) -> str:
    return _wrap(uuid_string, value)


def _operation(value) -> str:
    if type(value) is not str or value not in OPERATIONS:
        raise ExecuteMessageError()
    return value


def _artifact_input(value, ordinal, count) -> ArtifactInputDeclaration:
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_ARTIFACT_INPUT_FIELDS)):
        raise ExecuteMessageError()
    if value["ordinal"] != ordinal or type(value["ordinal"]) is not int:
        raise ExecuteMessageError()  # the exact ordered sequence
    size = value["declared_size"]
    if type(size) is not int or not 0 <= size <= MAX_INPUT_BYTES:
        raise ExecuteMessageError()
    media = value["media_type"]
    if type(media) is not str or len(media.encode("utf-8", "strict")) > 128:
        raise ExecuteMessageError()  # the wire's string bound, closed on encode as on parse
    try:
        # the stream's own descriptor grammar validates media type and digest
        ArtifactDescriptor(batch_id=_PLACEHOLDER_ID, request_id=_PLACEHOLDER_ID, ordinal=ordinal,
                           count=count, media_type=value["media_type"], declared_size=size,
                           sha256=value["sha256"])
    except (ArtifactStreamError, TypeError, ValueError):
        raise ExecuteMessageError() from None
    return ArtifactInputDeclaration(
        ordinal=ordinal, media_type=value["media_type"], declared_size=size,
        sha256=value["sha256"], role=_wrap(_identifier, value["role"]),
    )


def _artifact_inputs(batch_id, items) -> tuple[str | None, tuple[ArtifactInputDeclaration, ...]]:
    if type(items) is not list or len(items) > MAX_ARTIFACT_INPUTS:
        raise ExecuteMessageError()
    if not items:
        if batch_id is not None:
            raise ExecuteMessageError()  # a batch id names a batch
        return None, ()
    declarations = tuple(_artifact_input(item, index, len(items)) for index, item in enumerate(items))
    if sum(item.declared_size for item in declarations) > MAX_INPUT_BYTES:
        raise ExecuteMessageError()
    return _uuid(batch_id), declarations


def _member(value, allowed) -> str:
    if type(value) is not str or value not in allowed:
        raise ExecuteMessageError()
    return value


def _remaining(value) -> int:
    if type(value) is not int or not 1 <= value <= MAX_REMAINING_MS:
        raise ExecuteMessageError()
    return value


def _ref_value(value, kind) -> EntityRef:
    if type(value) is not EntityRef or value.kind != kind:
        raise ExecuteMessageError()
    return value


def _ref_dict(value, kind) -> EntityRef:
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_REF_FIELDS)):
        raise ExecuteMessageError()
    return _ref_value(_wrap(EntityRef.from_dict, value), kind)


def _usage(value) -> dict | None:
    if value is None:
        return None
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(USAGE_FIELDS)):
        raise ExecuteMessageError()
    usage = {}
    for name in USAGE_FIELDS:
        counter = value[name]
        if name == "api_microunits" and counter is None:
            usage[name] = None
            continue
        if type(counter) is not int or not 0 <= counter <= _MAX_UINT32:
            raise ExecuteMessageError()
        usage[name] = counter
    return usage


def _any_ref_dict(value) -> dict:
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_REF_FIELDS)):
        raise ExecuteMessageError()
    return _wrap(EntityRef.from_dict, value).as_dict()


def _sorted_unique_identifiers(value, limit) -> list[str]:
    if type(value) is not list or len(value) > limit:
        raise ExecuteMessageError()
    items = [_wrap(_identifier, item) for item in value]
    if items != sorted(set(items)):
        raise ExecuteMessageError()
    return items


def _tool(value) -> dict:
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_TOOL_FIELDS)):
        raise ExecuteMessageError()
    version = value["version"]
    if type(version) is not str or _VERSION_TEXT.fullmatch(version) is None:
        raise ExecuteMessageError()
    if type(value["effect_class"]) is not str or value["effect_class"] not in EFFECT_CLASSES:
        raise ExecuteMessageError()
    return {
        "tool_id": _wrap(_identifier, value["tool_id"]),
        "version": version,
        "argument_schema_ref": _any_ref_dict(value["argument_schema_ref"]),
        "result_schema_ref": _any_ref_dict(value["result_schema_ref"]),
        "effect_class": value["effect_class"],
        "artifact_roles": _sorted_unique_identifiers(value["artifact_roles"], MAX_ROLES),
    }


def _tools_output(value) -> dict:
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_TOOLS_FIELDS)):
        raise ExecuteMessageError()
    tools = value["tools"]
    if type(tools) is not list or len(tools) > MAX_TOOLS:
        raise ExecuteMessageError()
    entries = [_tool(item) for item in tools]
    ids = [entry["tool_id"] for entry in entries]
    if ids != sorted(set(ids)):
        raise ExecuteMessageError()  # one entry per tool, in identifier order
    output = {"tools": entries}
    if len(_wrap(canonical_json, output)) > MAX_TOOLS_BYTES:
        raise ExecuteMessageError()  # the reply could not carry it
    return output


def _output(value, operation) -> dict | None:
    if value is None:
        return None
    if operation not in OUTPUT_OPERATIONS:
        raise ExecuteMessageError()  # no success grammar for this operation yet
    if operation == "describe_tools":
        return _tools_output(value)
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(_OUTPUT_FIELDS)):
        raise ExecuteMessageError()
    component = _wrap(_component, value["component"])
    runtime = _wrap(_runtime, value["runtime"])
    return {
        "service_identity": _wrap(_identifier, value["service_identity"]),
        "component": {
            "build_identity_digest": component.build_identity_digest,
            "port_contract_version": component.port_contract_version,
            "port_schema_set_digest": component.port_schema_set_digest,
        },
        "runtime": {
            "platform": runtime.platform,
            "uid": runtime.uid,
            "gid": runtime.gid,
            "registered_operations": list(runtime.registered_operations),
        },
    }


def _reply_invariants(outcome, usage_finality, remote_terminal_observed, usage, output):
    if (usage_finality == "final") != (usage is not None):
        raise ExecuteMessageError()  # final usage needs the counters; otherwise none
    if (outcome == "succeeded") != (output is not None):
        raise ExecuteMessageError()  # success carries the output; nothing else does
    if outcome == "succeeded" and remote_terminal_observed != "succeeded":
        raise ExecuteMessageError()
    if outcome != "succeeded" and remote_terminal_observed == "succeeded":
        raise ExecuteMessageError()
    if (outcome == "outcome_unknown"
            and remote_terminal_observed not in {"not_observed", "outcome_unknown"}):
        raise ExecuteMessageError()  # the ledger's rule: unknown claims no known terminal


def _parse(raw, *, schema: str, fields, max_bytes: int) -> dict:
    if type(raw) is not bytes:
        raise ExecuteMessageError()
    try:
        value = parse_json_object(raw, required=fields, limits=_limits(max_bytes))
    except (WireInputError, ValueError):
        raise ExecuteMessageError() from None
    if value["schema_version"] != schema:
        raise ExecuteMessageError()
    try:
        canonical = canonical_json(value)
    except (DomainContractError, TypeError, ValueError):
        raise ExecuteMessageError() from None
    if canonical != raw:
        raise ExecuteMessageError()
    return value


def peek_schema(raw) -> str:
    """The exact `schema_version` of one bounded request or reply, so the
    worker can select the connection mode from the first frame; the exact
    parser of that schema validates everything else."""

    if type(raw) is not bytes:
        raise ExecuteMessageError()
    others = tuple(sorted((set(_REQUEST_FIELDS) | set(_REPLY_FIELDS)
                           | {"request_blob_sha256", "receipt_blob_sha256",
                              "service_identity", "component", "runtime"})
                          - {"schema_version"}))
    try:
        value = parse_json_object(
            raw, required=("schema_version",), optional=others,
            limits=_limits(max(MAX_REQUEST_BYTES, MAX_REPLY_BYTES)),
        )
    except (WireInputError, ValueError):
        raise ExecuteMessageError() from None
    schema = value["schema_version"]
    if type(schema) is not str or schema not in _KNOWN_SCHEMAS:
        raise ExecuteMessageError()
    return schema


def encode_execute_request(
    *, attempt_id, execution_id, operation, envelope_ref, profile_ref, remaining_ms,
    challenge, artifact_batch_id=None, artifact_inputs=(),
) -> bytes:
    if type(artifact_inputs) in (tuple, list):
        artifact_inputs = [
            item.as_dict() if type(item) is ArtifactInputDeclaration else item
            for item in artifact_inputs
        ]
    batch_id, declarations = _artifact_inputs(artifact_batch_id, artifact_inputs)
    return _wrap(_encode, {
        "schema_version": REQUEST_SCHEMA,
        "attempt_id": _uuid(attempt_id),
        "execution_id": _uuid(execution_id),
        "operation": _operation(operation),
        "envelope_ref": _ref_value(envelope_ref, "execution_envelope").as_dict(),
        "profile_ref": _ref_value(profile_ref, "runtime_profile").as_dict(),
        "remaining_ms": _remaining(remaining_ms),
        "challenge": _nonce_text(_wrap(_nonce_bytes, challenge)),
        "artifact_batch_id": batch_id,
        "artifact_inputs": [item.as_dict() for item in declarations],
    }, max_bytes=MAX_REQUEST_BYTES)


def parse_execute_request(raw) -> ExecuteRequest:
    value = _parse(raw, schema=REQUEST_SCHEMA, fields=_REQUEST_FIELDS,
                   max_bytes=MAX_REQUEST_BYTES)
    batch_id, declarations = _artifact_inputs(value["artifact_batch_id"], value["artifact_inputs"])
    return ExecuteRequest(
        attempt_id=_uuid(value["attempt_id"]),
        execution_id=_uuid(value["execution_id"]),
        operation=_operation(value["operation"]),
        envelope_ref=_ref_dict(value["envelope_ref"], "execution_envelope"),
        profile_ref=_ref_dict(value["profile_ref"], "runtime_profile"),
        remaining_ms=_remaining(value["remaining_ms"]),
        challenge=_wrap(_parse_nonce, value["challenge"]),
        artifact_batch_id=batch_id,
        artifact_inputs=declarations,
    )


def encode_execute_reply(
    *, attempt_id, operation, challenge, outcome, usage_finality, remote_terminal_observed,
    reason_code, usage, output,
) -> bytes:
    outcome = _member(outcome, OUTCOMES)
    usage_finality = _member(usage_finality, USAGE_FINALITIES)
    remote_terminal_observed = _member(remote_terminal_observed, REMOTE_TERMINALS)
    usage = _usage(usage)
    operation = _operation(operation)
    output = _output(output, operation)
    _reply_invariants(outcome, usage_finality, remote_terminal_observed, usage, output)
    return _wrap(_encode, {
        "schema_version": REPLY_SCHEMA,
        "attempt_id": _uuid(attempt_id),
        "operation": operation,
        "challenge": _nonce_text(_wrap(_nonce_bytes, challenge)),
        "outcome": outcome,
        "usage_finality": usage_finality,
        "remote_terminal_observed": remote_terminal_observed,
        "reason_code": _member(reason_code, REASONS),
        "usage": usage,
        "output": output,
    }, max_bytes=MAX_REPLY_BYTES)


def parse_execute_reply(raw) -> ExecuteReply:
    value = _parse(raw, schema=REPLY_SCHEMA, fields=_REPLY_FIELDS, max_bytes=MAX_REPLY_BYTES)
    outcome = _member(value["outcome"], OUTCOMES)
    usage_finality = _member(value["usage_finality"], USAGE_FINALITIES)
    remote = _member(value["remote_terminal_observed"], REMOTE_TERMINALS)
    usage = _usage(value["usage"])
    operation = _operation(value["operation"])
    output = _output(value["output"], operation)
    _reply_invariants(outcome, usage_finality, remote, usage, output)
    return ExecuteReply(
        attempt_id=_uuid(value["attempt_id"]),
        operation=operation,
        challenge=_wrap(_parse_nonce, value["challenge"]),
        outcome=outcome,
        usage_finality=usage_finality,
        remote_terminal_observed=remote,
        reason_code=_member(value["reason_code"], REASONS),
        usage=usage,
        output=output,
    )
