"""Closed, nonsecret values for the dedicated provider-send dialogue."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import threading
import time
from datetime import datetime
from uuid import UUID, uuid4

from ..domain.refs import EntityRef, canonical_json
from .credential_contracts import fingerprint, metadata_value, reference


FAILURE_CLASSES = frozenset({"permission_denied", "deadline_exceeded",
    "resource_exhausted", "unsupported_capability", "integrity_failed",
    "dependency_unavailable", "cancelled", "internal_failure"})


def failure_class(value):
    _require(value is None or type(value) is str and value in FAILURE_CLASSES,
             "invalid provider failure class")
    return value


class ProviderSendError(RuntimeError):
    def __init__(self, message="provider send failed", *, failure_class_value=None,
                 status=None, body=b"", phase=None, cancel_observed=False,
                 media_type=None):
        super().__init__(message)
        self.failure_class = failure_class(failure_class_value)
        self.status, self.body, self.phase = status, body, phase
        self.cancel_observed, self.media_type = cancel_observed, media_type


def _require(ok, message="provider send message rejected"):
    if not ok:
        raise ProviderSendError(message)


def _ref(value):
    try:
        return EntityRef.from_dict(value).as_dict()
    except (TypeError, ValueError):
        raise ProviderSendError("invalid immutable reference") from None


def _uuid(value):
    try:
        parsed = UUID(value)
    except (TypeError, ValueError):
        raise ProviderSendError("invalid UUID") from None
    _require(str(parsed) == value and parsed.int != 0)
    return value


@dataclass(frozen=True, slots=True)
class ProviderSendPrepare:
    operation_ref: dict
    request_id: str
    request_sha256: str
    selected_handle_ref: dict
    connection_sha256: str
    connection_pin: dict
    credential_metadata: dict = field(repr=False)
    credential_record: dict
    endpoint: str
    after_id: str | None
    body: bytes = field(repr=False)
    body_sha256: str
    body_size: int
    body_batch_id: str | None
    remaining_ms: int
    deadline_at: str
    reservation_ref: dict | None
    dialogue_id: str
    prepare_sha256: str


@dataclass(frozen=True, slots=True)
class GatewayExchangeLease:
    dialogue_id: str
    exchange_id: str
    prepare_sha256: str
    commit_id: str
    operation_ref: dict
    request_id: str
    request_sha256: str
    selected_handle_ref: dict
    connection_sha256: str
    connection_pin: dict
    credential_metadata: dict = field(repr=False)
    credential_record: dict
    endpoint: str
    after_id: str | None
    body: bytes = field(repr=False)
    body_sha256: str
    body_size: int
    max_response_bytes: int
    # the transport manifest the lease is bound to (the vault requires its adopted
    # qualification to name it) and the budget reservation this one send consumes
    transport_manifest_sha256: str | None
    reservation_ref: dict | None
    deadline_monotonic: float
    cancel_event: threading.Event = field(repr=False, compare=False)
    write_event: threading.Event = field(repr=False, compare=False)
    _issuer: object = field(repr=False, compare=False)


def prepare_message(*, operation_ref, request_sha256, selected_handle_ref, connection_pin,
                    credential_metadata, credential_record, endpoint, after_id, body,
                    remaining_ms, reservation_ref, request_id=None, deadline_at=None,
                    dialogue_id=None, body_batch_id=None):
    operation_ref = _ref(operation_ref)
    request_id = _uuid(request_id)
    dialogue_id = _uuid(str(uuid4()) if dialogue_id is None else dialogue_id)
    selected_handle_ref = _ref(selected_handle_ref)
    _require(type(request_sha256) is str and len(request_sha256) == 64)
    _require(selected_handle_ref["sha256"] == connection_pin.get("connection_sha256", selected_handle_ref["sha256"]))
    expected_pin = {"locator", "revision_digest", "provider_id", "account_id", "credential_metadata_sha256"}
    _require(type(connection_pin) is dict and set(connection_pin) == expected_pin
             and connection_pin["provider_id"] == "claude_api")
    metadata = metadata_value(credential_metadata)
    record = reference(credential_record)
    _require(metadata["provider"] == "claude" and metadata["auth_mode"] == "api"
             and metadata["record_id"] == record["record_id"]
             and metadata["record_version"] == record["record_version"]
             and connection_pin["credential_metadata_sha256"] == fingerprint(metadata))
    _require(endpoint in {"messages", "models"} and type(body) is bytes
             and len(body) <= 1_048_576 and type(remaining_ms) is int and 1 <= remaining_ms <= 30_000)
    # every send, a model page as much as a message, names the budget reservation
    # recorded for it before the send (T090 budget binding); none is refused here
    _require(reservation_ref is not None, "provider send requires a budget reservation")
    _require((endpoint == "messages" and after_id is None)
             or (endpoint == "models" and (after_id is None or type(after_id) is str)
                 and body == b""))
    reservation = _ref(reservation_ref)
    _require(type(deadline_at) is str and len(deadline_at) == 24)
    try:
        datetime.strptime(deadline_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise ProviderSendError("invalid absolute deadline") from None
    batch_id = None
    if endpoint == "messages":
        batch_id = _uuid(str(uuid4()) if body_batch_id is None else body_batch_id)
    body_digest = sha256(body).hexdigest()
    descriptor = (None if batch_id is None else {"batch_id": batch_id, "request_id": request_id,
        "ordinal": 0, "count": 1, "media_type": "application/json",
        "declared_size": len(body), "sha256": body_digest})
    projection = {"schema": "provider-send-prepare-v1", "dialogue_id": dialogue_id, "seq": 0,
        "operation_ref": operation_ref, "request_id": request_id,
        "request_sha256": request_sha256, "selected_handle_ref": selected_handle_ref,
        "connection_sha256": selected_handle_ref["sha256"], "connection_pin": connection_pin,
        "credential_metadata": metadata, "credential_record": record, "endpoint": endpoint,
        "after_id": after_id, "body_descriptor": descriptor, "remaining_ms": remaining_ms,
        "deadline_at": deadline_at, "reservation_ref": reservation}
    return ProviderSendPrepare(operation_ref, request_id, request_sha256, selected_handle_ref,
        selected_handle_ref["sha256"], dict(connection_pin), metadata, record, endpoint, after_id,
        body, body_digest, len(body), batch_id, remaining_ms, deadline_at, reservation, dialogue_id,
        sha256(canonical_json(projection)).hexdigest())


@dataclass(frozen=True, slots=True)
class ProviderSendObservation:
    exchange_id: str
    prepare_sha256: str
    status: int | None
    body: bytes = field(repr=False)
    phase: str = "not_sent"
    cancel_observed: bool = False
    media_type: str | None = None
    failure_class: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderSendCancellation:
    exchange_id: str
    accepted: bool
    phase: str


def prepare_header(message: ProviderSendPrepare) -> dict:
    """Return the closed, nonsecret control header; body bytes use artifact-stream-v1."""
    if type(message) is not ProviderSendPrepare:
        raise ProviderSendError()
    return {
        "schema": "provider-send-prepare-v1",
        "dialogue_id": message.dialogue_id,
        "seq": 0,
        "operation_ref": message.operation_ref,
        "request_id": message.request_id,
        "request_sha256": message.request_sha256,
        "selected_handle_ref": message.selected_handle_ref,
        "connection_sha256": message.connection_sha256,
        "connection_pin": message.connection_pin,
        "credential_metadata": message.credential_metadata,
        "credential_record": message.credential_record,
        "endpoint": message.endpoint,
        "after_id": message.after_id,
        "body_descriptor": (None if message.body_batch_id is None else {
            "batch_id": message.body_batch_id, "request_id": message.request_id,
            "ordinal": 0, "count": 1, "media_type": "application/json",
            "declared_size": message.body_size, "sha256": message.body_sha256}),
        "remaining_ms": message.remaining_ms,
        "deadline_at": message.deadline_at,
        "reservation_ref": message.reservation_ref,
    }


def prepare_from_header(value: dict, body: bytes) -> ProviderSendPrepare:
    fields = {"schema", "dialogue_id", "seq", "operation_ref", "request_id",
              "request_sha256", "selected_handle_ref", "connection_sha256",
              "connection_pin", "credential_metadata", "credential_record", "endpoint",
              "after_id", "body_descriptor", "remaining_ms", "deadline_at", "reservation_ref"}
    if type(value) is not dict or set(value) != fields or value["schema"] != "provider-send-prepare-v1":
        raise ProviderSendError("prepare control is not closed")
    descriptor = value["body_descriptor"]
    descriptor_fields = {"batch_id", "request_id", "ordinal", "count", "media_type",
                         "declared_size", "sha256"}
    if ((value["endpoint"] == "messages" and (type(descriptor) is not dict
            or set(descriptor) != descriptor_fields))
            or (value["endpoint"] == "models" and descriptor is not None)):
        raise ProviderSendError("body descriptor is not closed")
    prepared = prepare_message(operation_ref=value["operation_ref"],
        request_id=value["request_id"],
        request_sha256=value["request_sha256"], selected_handle_ref=value["selected_handle_ref"],
        connection_pin=value["connection_pin"], credential_metadata=value["credential_metadata"],
        credential_record=value["credential_record"], endpoint=value["endpoint"],
        after_id=value["after_id"], body=body, remaining_ms=value["remaining_ms"],
        deadline_at=value["deadline_at"], reservation_ref=value["reservation_ref"],
        dialogue_id=value["dialogue_id"],
        body_batch_id=None if descriptor is None else descriptor["batch_id"])
    if (type(value["seq"]) is not int or value["seq"] != 0
            or value["connection_sha256"] != prepared.connection_sha256
            or value != prepare_header(prepared)):
        raise ProviderSendError("prepare body does not match its control header")
    return prepared


__all__ = ["FAILURE_CLASSES", "GatewayExchangeLease", "ProviderSendCancellation", "ProviderSendError",
           "ProviderSendObservation", "ProviderSendPrepare", "prepare_from_header",
           "prepare_header", "prepare_message", "failure_class"]
