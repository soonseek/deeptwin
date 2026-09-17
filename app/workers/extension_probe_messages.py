"""Closed worker-private stage probe messages (Task 25 slice 1b;
contracts/extension-worker-probe.md §2/§2a).

Pure codecs over canonical strict JSON payload bytes. A request carries the
control side's retained request/receipt digests and a fresh 32-byte nonce;
a reply repeats them as correlation only and self-reports the worker's
build identity digests, platform, uid/gid and its (possibly empty)
registered operations. Encoders take plain validated scalars — never a
metadata reading, a channel spec or a registry object; the service, not the
codec, is the response builder — and parsers return inert frozen values.
Nothing here observes, authenticates or admits anything. The single closed
error carries a fixed message that never reflects input.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, canonical_json
from ..domain.wire import WireInputError, WireLimits, parse_json_object
from ..extensions.port_contracts import PORT_CONTRACTS
from . import broker

REQUEST_SCHEMA = "extension-stage-probe-v1"
REPLY_SCHEMA = "extension-stage-probe-result-v1"
PORT_CONTRACT_VERSION = "tool-port-v1"
PLATFORMS = ("linux/amd64", "linux/arm64")
OPERATIONS = frozenset(PORT_CONTRACTS[PORT_CONTRACT_VERSION].operations)
MAX_REQUEST_BYTES = 1_024
MAX_REPLY_BYTES = 4_096
NONCE_BYTES = 32
_NONCE_CHARS = 43
_MAX_UINT32 = 2**32 - 1
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NONCE_TEXT = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_REQUEST_FIELDS = (
    "schema_version",
    "request_blob_sha256",
    "receipt_blob_sha256",
    "challenge",
)
_REPLY_FIELDS = (*_REQUEST_FIELDS, "service_identity", "component", "runtime")
_COMPONENT_FIELDS = (
    "build_identity_digest",
    "port_contract_version",
    "port_schema_set_digest",
)
_RUNTIME_FIELDS = ("platform", "uid", "gid", "registered_operations")


class ProbeMessageError(ValueError):
    """The bytes or values are outside the closed probe grammar."""

    def __init__(self, *_ignored) -> None:
        # copy/pickle re-invoke __init__ with the stored args: accept and drop them
        super().__init__("invalid probe message")


def _limits(max_bytes: int) -> WireLimits:
    return WireLimits(
        max_bytes=max_bytes,
        max_depth=4,
        max_items=128,
        max_members=16,
        max_string_bytes=128,
        max_integer=_MAX_UINT32,
    )


# digests, nonces and bytes never appear in logs (contract §4): the values
# hide them from repr/str so a careless log line cannot leak them
@dataclass(frozen=True, slots=True)
class ProbeRequest:
    request_blob_sha256: str = field(repr=False)
    receipt_blob_sha256: str = field(repr=False)
    challenge: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProbeComponent:
    build_identity_digest: str = field(repr=False)
    port_contract_version: str
    port_schema_set_digest: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProbeRuntime:
    platform: str
    uid: int
    gid: int
    registered_operations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProbeReply:
    request_blob_sha256: str = field(repr=False)
    receipt_blob_sha256: str = field(repr=False)
    challenge: bytes = field(repr=False)
    service_identity: str
    component: ProbeComponent
    runtime: ProbeRuntime


def _hex64(value) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ProbeMessageError()
    return value


def _nonce_bytes(value) -> bytes:
    if type(value) is not bytes or len(value) != NONCE_BYTES:
        raise ProbeMessageError()
    return value


def _nonce_text(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _parse_nonce(value) -> bytes:
    if type(value) is not str or _NONCE_TEXT.fullmatch(value) is None:
        raise ProbeMessageError()
    try:
        raw = base64.urlsafe_b64decode(value + "=")
    except (binascii.Error, ValueError):
        raise ProbeMessageError() from None
    if len(raw) != NONCE_BYTES or _nonce_text(raw) != value:
        # canonical rendering only: no padding, no stray trailing bits
        raise ProbeMessageError()
    return raw


def _identifier(value) -> str:
    if not broker._identifier(value):
        raise ProbeMessageError()
    return value


def _uint32(value) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_UINT32:
        raise ProbeMessageError()
    return value


def _platform(value) -> str:
    if type(value) is not str or value not in PLATFORMS:
        raise ProbeMessageError()
    return value


def _port_contract_version(value) -> str:
    if type(value) is not str or value != PORT_CONTRACT_VERSION:
        raise ProbeMessageError()
    return value


def _operations(value, *, container) -> tuple[str, ...]:
    if type(value) is not container or any(type(item) is not str for item in value):
        raise ProbeMessageError()
    items = tuple(value)
    if (
        len(set(items)) != len(items)
        or tuple(sorted(items)) != items
        or not set(items) <= OPERATIONS
    ):
        raise ProbeMessageError()
    return items


def _component(value) -> ProbeComponent:
    if type(value) is not dict or tuple(sorted(value)) != tuple(
        sorted(_COMPONENT_FIELDS)
    ):
        raise ProbeMessageError()
    return ProbeComponent(
        build_identity_digest=_hex64(value["build_identity_digest"]),
        port_contract_version=_port_contract_version(value["port_contract_version"]),
        port_schema_set_digest=_hex64(value["port_schema_set_digest"]),
    )


def _runtime(value) -> ProbeRuntime:
    if type(value) is not dict or tuple(sorted(value)) != tuple(
        sorted(_RUNTIME_FIELDS)
    ):
        raise ProbeMessageError()
    return ProbeRuntime(
        platform=_platform(value["platform"]),
        uid=_uint32(value["uid"]),
        gid=_uint32(value["gid"]),
        registered_operations=_operations(
            value["registered_operations"], container=list
        ),
    )


def _parse(raw, *, schema: str, fields, max_bytes: int) -> dict:
    if type(raw) is not bytes:
        raise ProbeMessageError()
    try:
        value = parse_json_object(raw, required=fields, limits=_limits(max_bytes))
    except (WireInputError, ValueError):
        raise ProbeMessageError() from None
    if value["schema_version"] != schema:
        raise ProbeMessageError()
    try:
        canonical = canonical_json(value)
    except (DomainContractError, TypeError, ValueError):
        raise ProbeMessageError() from None
    if canonical != raw:
        raise ProbeMessageError()
    return value


def _encode(value: dict, *, max_bytes: int) -> bytes:
    try:
        raw = canonical_json(value)
    except (DomainContractError, TypeError, ValueError):
        raise ProbeMessageError() from None
    if len(raw) > max_bytes:
        raise ProbeMessageError()
    return raw


def encode_probe_request(
    *, request_blob_sha256, receipt_blob_sha256, challenge
) -> bytes:
    return _encode(
        {
            "schema_version": REQUEST_SCHEMA,
            "request_blob_sha256": _hex64(request_blob_sha256),
            "receipt_blob_sha256": _hex64(receipt_blob_sha256),
            "challenge": _nonce_text(_nonce_bytes(challenge)),
        },
        max_bytes=MAX_REQUEST_BYTES,
    )


def parse_probe_request(raw) -> ProbeRequest:
    value = _parse(
        raw, schema=REQUEST_SCHEMA, fields=_REQUEST_FIELDS, max_bytes=MAX_REQUEST_BYTES
    )
    return ProbeRequest(
        request_blob_sha256=_hex64(value["request_blob_sha256"]),
        receipt_blob_sha256=_hex64(value["receipt_blob_sha256"]),
        challenge=_parse_nonce(value["challenge"]),
    )


def encode_probe_reply(
    *,
    request_blob_sha256,
    receipt_blob_sha256,
    challenge,
    service_identity,
    build_identity_digest,
    port_contract_version,
    port_schema_set_digest,
    platform,
    uid,
    gid,
    registered_operations,
) -> bytes:
    return _encode(
        {
            "schema_version": REPLY_SCHEMA,
            "request_blob_sha256": _hex64(request_blob_sha256),
            "receipt_blob_sha256": _hex64(receipt_blob_sha256),
            "challenge": _nonce_text(_nonce_bytes(challenge)),
            "service_identity": _identifier(service_identity),
            "component": {
                "build_identity_digest": _hex64(build_identity_digest),
                "port_contract_version": _port_contract_version(port_contract_version),
                "port_schema_set_digest": _hex64(port_schema_set_digest),
            },
            "runtime": {
                "platform": _platform(platform),
                "uid": _uint32(uid),
                "gid": _uint32(gid),
                "registered_operations": list(
                    _operations(registered_operations, container=tuple)
                ),
            },
        },
        max_bytes=MAX_REPLY_BYTES,
    )


def parse_probe_reply(raw) -> ProbeReply:
    value = _parse(
        raw, schema=REPLY_SCHEMA, fields=_REPLY_FIELDS, max_bytes=MAX_REPLY_BYTES
    )
    return ProbeReply(
        request_blob_sha256=_hex64(value["request_blob_sha256"]),
        receipt_blob_sha256=_hex64(value["receipt_blob_sha256"]),
        challenge=_parse_nonce(value["challenge"]),
        service_identity=_identifier(value["service_identity"]),
        component=_component(value["component"]),
        runtime=_runtime(value["runtime"]),
    )
