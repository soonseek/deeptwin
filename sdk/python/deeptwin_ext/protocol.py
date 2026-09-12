"""Strict, side-effect-free messages for a future broker-owned worker channel."""

from dataclasses import dataclass
import json
import re
from uuid import UUID


PROTOCOL_VERSION = "deeptwin-extension-worker-v1"
WORKER_OPERATIONS = frozenset({"describe", "invoke", "health"})
WORKER_FAILURE_CODES = frozenset({
    "cancelled",
    "execution_failed",
    "input_unavailable",
    "invalid_input",
    "output_invalid",
    "policy_denied",
    "resource_exhausted",
    "timeout",
    "unavailable",
    "unsupported_operation",
})
_HASH = re.compile(r"[0-9a-f]{64}")
_REQUEST_FIELDS = frozenset({
    "protocol_version", "request_id", "operation", "manifest_digest", "input_ref",
})
_RESULT_FIELDS = frozenset({
    "protocol_version", "request_id", "status", "output_ref", "error_code",
})
_MAX_MESSAGE_BYTES = 65_536


class ProtocolError(ValueError):
    """The worker message is not an exact, bounded protocol-v1 value."""


def _uuid(value):
    if type(value) is not str:
        raise ProtocolError("request_id must be a canonical UUID")
    parsed = None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        pass
    if parsed is None or str(parsed) != value or parsed.int == 0:
        raise ProtocolError("request_id must be a canonical UUID")
    return value


def _hash(value, label):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ProtocolError(f"{label} must be a lowercase SHA-256")
    return value


def _operation(value):
    if type(value) is not str or value not in WORKER_OPERATIONS:
        raise ProtocolError("unsupported worker operation")
    return value


def _status(value):
    if type(value) is not str or value not in {"completed", "failed"}:
        raise ProtocolError("invalid worker result status")
    return value


def _failure_code(value):
    if type(value) is not str or value not in WORKER_FAILURE_CODES:
        raise ProtocolError("failed result requires a registered generic error_code")
    return value


def _canonical_bytes(value):
    encoded = None
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, UnicodeEncodeError, ValueError, TypeError):
        pass
    if encoded is None:
        raise ProtocolError("worker message is not canonical JSON")
    return encoded


def _reject_constant(_value):
    raise ProtocolError("worker message must be strict JSON")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("worker message contains a duplicate key")
        result[key] = value
    return result


def _decode(data, label):
    if type(data) is not bytes or not 1 <= len(data) <= _MAX_MESSAGE_BYTES:
        raise ProtocolError(f"{label} must be bounded bytes")
    decoded = None
    try:
        decoded = data.decode("utf-8")
    except UnicodeError:
        pass
    if decoded is None:
        raise ProtocolError(f"{label} must be UTF-8 JSON")

    invalid = object()
    value = invalid
    try:
        value = json.loads(decoded, object_pairs_hook=_object, parse_constant=_reject_constant)
    except ProtocolError:
        raise
    except (ValueError, RecursionError):
        pass
    if value is invalid:
        raise ProtocolError(f"{label} must be UTF-8 JSON")
    if _canonical_bytes(value) != data:
        raise ProtocolError(f"{label} must use canonical JSON encoding")
    return value


def _encode(value, label):
    encoded = _canonical_bytes(value)
    if not 1 <= len(encoded) <= _MAX_MESSAGE_BYTES:
        raise ProtocolError(f"{label} exceeds the byte limit")
    return encoded


@dataclass(frozen=True, slots=True, repr=False, init=False)
class WorkerRequest:
    request_id: str
    operation: str
    manifest_digest: str
    input_ref: str

    def __init__(self, request_id, operation, manifest_digest, input_ref):
        message = None
        try:
            _uuid(request_id)
            _operation(operation)
            _hash(manifest_digest, "manifest_digest")
            _hash(input_ref, "input_ref")
        except ProtocolError as exc:
            message = str(exc)
        if message is not None:
            # The public exception frame must not retain caller-controlled message values.
            request_id = operation = manifest_digest = input_ref = None
            raise ProtocolError(message)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "manifest_digest", manifest_digest)
        object.__setattr__(self, "input_ref", input_ref)

    def __repr__(self):
        return (
            f"WorkerRequest(request_id={getattr(self, 'request_id', None)!r}, "
            f"operation={getattr(self, 'operation', None)!r})"
        )

    def as_dict(self):
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "operation": self.operation,
            "manifest_digest": self.manifest_digest,
            "input_ref": self.input_ref,
        }

    def to_bytes(self):
        return _encode(self.as_dict(), "worker request")

    @classmethod
    def from_bytes(cls, data):
        value = None
        message = None
        try:
            value = _decode(data, "worker request")
            if type(value) is not dict or set(value) != _REQUEST_FIELDS:
                raise ProtocolError("worker request does not match the exact schema")
            if value["protocol_version"] != PROTOCOL_VERSION:
                raise ProtocolError("unsupported worker protocol")
            result = cls(
                request_id=value["request_id"],
                operation=value["operation"],
                manifest_digest=value["manifest_digest"],
                input_ref=value["input_ref"],
            )
        except ProtocolError as exc:
            message = str(exc)
        else:
            return result
        # Raise outside the handler so the replacement has no payload-bearing context/cause.
        data = value = None
        raise ProtocolError(message)


@dataclass(frozen=True, slots=True, repr=False, init=False)
class WorkerResult:
    request_id: str
    status: str
    output_ref: str | None
    error_code: str | None

    def __init__(self, request_id, status, output_ref, error_code):
        message = None
        try:
            _uuid(request_id)
            _status(status)
            if status == "completed":
                _hash(output_ref, "output_ref")
                if error_code is not None:
                    raise ProtocolError("completed result cannot include error_code")
            else:
                if output_ref is not None:
                    raise ProtocolError("failed result cannot include output_ref")
                _failure_code(error_code)
        except ProtocolError as exc:
            message = str(exc)
        if message is not None:
            request_id = status = output_ref = error_code = None
            raise ProtocolError(message)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "output_ref", output_ref)
        object.__setattr__(self, "error_code", error_code)

    def __repr__(self):
        return (
            f"WorkerResult(request_id={getattr(self, 'request_id', None)!r}, "
            f"status={getattr(self, 'status', None)!r})"
        )

    def as_dict(self):
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "status": self.status,
            "output_ref": self.output_ref,
            "error_code": self.error_code,
        }

    def to_bytes(self):
        return _encode(self.as_dict(), "worker result")

    @classmethod
    def from_bytes(cls, data):
        value = None
        message = None
        try:
            value = _decode(data, "worker result")
            if type(value) is not dict or set(value) != _RESULT_FIELDS:
                raise ProtocolError("worker result does not match the exact schema")
            if value["protocol_version"] != PROTOCOL_VERSION:
                raise ProtocolError("unsupported worker protocol")
            result = cls(
                request_id=value["request_id"],
                status=value["status"],
                output_ref=value["output_ref"],
                error_code=value["error_code"],
            )
        except ProtocolError as exc:
            message = str(exc)
        else:
            return result
        data = value = None
        raise ProtocolError(message)
