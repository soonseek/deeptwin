"""Control-side stage postcondition observer (Task 24 step (d);
contracts/deployment-receipt-journal-v3.md §4 evidence blob, §5 observer;
contracts/extension-worker-probe.md §3/§4/§6).

The only constructor of `StagePostconditionEvidence`: one authenticated
probe connection to the staged worker under this process's own boot ID,
exactly two probes with fresh challenges and message ids, every reply
verified verbatim against the probe request, the owned channel and the
retained `ExpectedStageIdentity`, the kernel peer compared with the slot,
the listener fences rechecked after each reply. Any deviation is a closed
error and nothing is produced: a mismatch never becomes an admission.

A reply is a self-reported component observation at one moment over one
connection — not qualification, installation, readiness or a permit — and
the evidence is an inert value the consume transaction (step (e)) preseals
and verifies again inside its own writer. Nothing here imports `app.api`,
`app.static` or `app.server`, and the boot ID is a process label, never an
owner account.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from ..domain.refs import DomainContractError, canonical_json, uuid_string
from ..operations.setup import SetupContractError, parse_base64url_32
from ..workers import broker, ipc_root, listener
from ..workers.extension_channel import ExtensionChannelError, extension_channel
from ..workers.extension_probe_messages import (
    NONCE_BYTES,
    PLATFORMS,
    PORT_CONTRACT_VERSION,
    ProbeMessageError,
    _nonce_text,
    encode_probe_request,
    parse_probe_reply,
)

SCHEMA_VERSION = "extension-stage-postcondition-v1"
REQUEST_TYPE = "extension-request-v1"
RESULT_TYPE = "extension-result-v1"
PROBES = 2
ATTEMPT_MS = 2_000  # probe contract §4: control attempt, measured from before connect
FINAL_PROBE_MS = 500  # probe contract §4: the final probe
MAX_EVIDENCE_BYTES = 8_192
MAX_REQUEST_BYTES = 65_536
MAX_RECEIPT_BYTES = 16_384
CODES = frozenset({"probe_unavailable", "probe_mismatch", "probe_deadline", "probe_invalid"})
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_UINT32 = 2**32 - 1
_boot_lock = threading.Lock()
_boot_id: str | None = None


class StagePostconditionError(Exception):
    """Closed error family: the code is the whole message; never a digest,
    nonce, id or peer value."""

    def __init__(self, code: str = "probe_invalid", *_ignored: object) -> None:
        self.code = code if code in CODES else "probe_invalid"
        super().__init__(self.code)


def _invalid() -> StagePostconditionError:
    return StagePostconditionError("probe_invalid")


def _hex64(value: object) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise _invalid()
    return value


@dataclass(frozen=True, slots=True)
class ExpectedStageIdentity:
    """The retained expectation (journal v3 §4): built by the service from
    the admitted slot and the candidate's lineage, never from a reply."""

    service_identity: str
    build_identity_digest: str = field(repr=False)
    port_schema_set_digest: str = field(repr=False)
    port_contract_version: str
    platform: str
    uid: int
    gid: int

    def __post_init__(self) -> None:
        if (
            not broker._identifier(self.service_identity)
            or self.port_contract_version != PORT_CONTRACT_VERSION
            or type(self.platform) is not str
            or self.platform not in PLATFORMS
            or any(
                type(value) is not int or not 1 <= value <= _MAX_UINT32
                for value in (self.uid, self.gid)
            )
        ):
            raise _invalid()
        _hex64(self.build_identity_digest)
        _hex64(self.port_schema_set_digest)

    def as_dict(self) -> dict:
        return {
            "service_identity": self.service_identity,
            "build_identity_digest": self.build_identity_digest,
            "port_schema_set_digest": self.port_schema_set_digest,
            "port_contract_version": self.port_contract_version,
            "platform": self.platform,
            "uid": self.uid,
            "gid": self.gid,
        }


class StagePostconditionEvidence:
    """The canonical evidence bytes with their digest and size; inert,
    nonconstructible, immutable, uncopyable; no live socket is retained."""

    __slots__ = ("content_bytes", "digest", "size")

    def __init__(self) -> None:
        raise TypeError("evidence is produced by observe_stage_postcondition only")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("evidence is immutable")

    def __delattr__(self, _name: str) -> None:
        raise AttributeError("evidence is immutable")

    def __repr__(self) -> str:
        return f"StagePostconditionEvidence(size={self.size!r})"

    def __copy__(self) -> object:
        raise TypeError("evidence cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("evidence cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("evidence cannot be serialized")


def _evidence(raw: bytes) -> StagePostconditionEvidence:
    result = object.__new__(StagePostconditionEvidence)
    object.__setattr__(result, "content_bytes", raw)
    object.__setattr__(result, "digest", hashlib.sha256(raw).hexdigest())
    object.__setattr__(result, "size", len(raw))
    return result


def _process_boot_id() -> str:
    """One boot ID per process (probe contract §5): a random label, generated
    on first use, never an owner account or authorization."""

    global _boot_id
    with _boot_lock:
        if _boot_id is None:
            _boot_id = secrets.token_hex(32)
        return _boot_id


def _now() -> str:
    """The wire Time grammar: exactly three fractional digits, `Z`."""

    return (
        datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def observe_stage_postcondition(
    *,
    request_id,
    request_digest,
    receipt_digest,
    request_bytes,
    receipt_bytes,
    slot_number,
    instance_id,
    expected,
    deadline,
) -> StagePostconditionEvidence:
    """Observe the staged service once; return the evidence or raise the
    closed error. Inputs are validated before any socket is opened."""

    try:
        uuid_string(request_id)
        parse_base64url_32(request_digest)
        parse_base64url_32(receipt_digest)
        if (
            type(request_bytes) is not bytes
            or not 1 <= len(request_bytes) <= MAX_REQUEST_BYTES
            or type(receipt_bytes) is not bytes
            or not 1 <= len(receipt_bytes) <= MAX_RECEIPT_BYTES
            or type(expected) is not ExpectedStageIdentity
            or type(deadline) is not broker.Deadline
            or type(slot_number) is not int
            or not 1 <= slot_number <= 16
        ):
            raise _invalid()
        root, spec = extension_channel(instance_id=instance_id, slot_number=slot_number)
    except (
        DomainContractError,
        SetupContractError,
        ExtensionChannelError,
        TypeError,
        ValueError,
    ):
        raise _invalid() from None
    started = time.monotonic()
    attempt = deadline.bounded(ATTEMPT_MS)
    try:
        connection = listener._connect_extension_authenticated(
            root, spec, requester_boot_id=_process_boot_id(), deadline=attempt
        )
    except broker.DeadlineExceeded:
        raise StagePostconditionError("probe_deadline") from None
    except (listener.ListenerError, broker.BrokerError, ipc_root.IpcRootError, OSError):
        # a handshake that stalls until the attempt is exhausted is the
        # deadline, exactly as a stalled probe is (the framing reports the
        # socket timeout as an uncertain transport)
        if attempt.remaining() <= 0.0:
            raise StagePostconditionError("probe_deadline") from None
        raise StagePostconditionError("probe_unavailable") from None
    try:
        connection_facts, probes = _exchange(
            connection, spec, expected, request_bytes, receipt_bytes, attempt
        )
        # the attempt is the exchange (connect, handshake, probes, rechecks);
        # the teardown below is not part of the window it reports
        elapsed_ms = max(1, math.ceil((time.monotonic() - started) * 1000))
    finally:
        try:
            connection.close()
        except (listener.ListenerError, broker.BrokerError, ipc_root.IpcRootError, OSError):
            pass
    if elapsed_ms > ATTEMPT_MS:
        raise StagePostconditionError("probe_deadline")
    value = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "request_digest": request_digest,
        "receipt_digest": receipt_digest,
        "request_blob_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "receipt_blob_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "observed_at": _now(),
        "attempt_ms": elapsed_ms,
        "connection": connection_facts,
        "probes": probes,
        "expected": expected.as_dict(),
        "comparison": "equal",
    }
    try:
        raw = canonical_json(value)
    except (DomainContractError, TypeError, ValueError):
        raise _invalid() from None
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise _invalid()
    return _evidence(raw)


def _exchange(connection, spec, expected, request_bytes, receipt_bytes, attempt):
    session = connection.session
    facts = {
        "channel_id": spec.channel_id,
        "connection_id": _hex64(session.connection_id),
        # both producers use token_hex(32); a wider session id is refused
        "requester_boot_id": _hex64(session.requester_boot_id),
        "responder_boot_id": _hex64(session.responder_boot_id),
    }
    peer = connection.peer
    if type(peer) is not broker.PeerCredentials:
        raise _invalid()
    if (peer.uid, peer.gid) != (expected.uid, expected.gid):
        raise StagePostconditionError("probe_mismatch")
    facts["peer_uid"] = peer.uid
    facts["peer_gid"] = peer.gid
    request_sha = hashlib.sha256(request_bytes).hexdigest()
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    seen_ids: set[str] = set()
    challenges: set[bytes] = set()
    probes = []
    try:
        for index in range(PROBES):
            challenge = os.urandom(NONCE_BYTES)
            while challenge in challenges:
                challenge = os.urandom(NONCE_BYTES)
            challenges.add(challenge)
            message_id = str(uuid4())
            while message_id in seen_ids:
                message_id = str(uuid4())
            seen_ids.add(message_id)
            probe_deadline = attempt if index < PROBES - 1 else attempt.bounded(FINAL_PROBE_MS)
            connection.write(
                message_id=message_id,
                correlation_id=None,
                message_type=REQUEST_TYPE,
                payload=encode_probe_request(
                    request_blob_sha256=request_sha,
                    receipt_blob_sha256=receipt_sha,
                    challenge=challenge,
                ),
                deadline=probe_deadline,
            )
            frame = connection.read(deadline=probe_deadline)
            envelope = frame.envelope
            if envelope.message_type != RESULT_TYPE or envelope.correlation_id != message_id:
                raise _invalid()
            reply_id = uuid_string(envelope.message_id)
            if reply_id in seen_ids:
                raise _invalid()
            seen_ids.add(reply_id)
            reply = parse_probe_reply(frame.payload)
            if (
                reply.request_blob_sha256 != request_sha
                or reply.receipt_blob_sha256 != receipt_sha
                or reply.challenge != challenge
                or reply.service_identity != spec.responder_service
            ):
                raise _invalid()
            component, runtime = reply.component, reply.runtime
            if (
                reply.service_identity != expected.service_identity
                or component.build_identity_digest != expected.build_identity_digest
                or component.port_contract_version != expected.port_contract_version
                or component.port_schema_set_digest != expected.port_schema_set_digest
                or runtime.platform != expected.platform
                or runtime.uid != expected.uid
                or runtime.gid != expected.gid
            ):
                raise StagePostconditionError("probe_mismatch")
            connection.recheck()
            probes.append(
                {
                    "challenge": _nonce_text(challenge),
                    "request_message_id": message_id,
                    "reply_message_id": reply_id,
                    "reply": {
                        "service_identity": reply.service_identity,
                        "component": {
                            "build_identity_digest": component.build_identity_digest,
                            "port_contract_version": component.port_contract_version,
                            "port_schema_set_digest": component.port_schema_set_digest,
                        },
                        "runtime": {
                            "platform": runtime.platform,
                            "uid": runtime.uid,
                            "gid": runtime.gid,
                            # recorded, never compared: a staged worker reports []
                            "registered_operations": list(runtime.registered_operations),
                        },
                    },
                }
            )
    except StagePostconditionError:
        raise
    except broker.DeadlineExceeded:
        raise StagePostconditionError("probe_deadline") from None
    except (ProbeMessageError, DomainContractError):
        raise _invalid() from None
    except (broker.ProtocolViolation, broker.AuthenticationError):
        # the worker was reached and authenticated and answered outside the
        # framing: that is an invalid reply, not an unavailable service
        raise _invalid() from None
    except (listener.ListenerError, broker.BrokerError, ipc_root.IpcRootError, OSError):
        # a socket timeout surfaces from the framing as an uncertain transport;
        # with the attempt budget exhausted it is the deadline that ended it
        if attempt.remaining() <= 0.0:
            raise StagePostconditionError("probe_deadline") from None
        raise StagePostconditionError("probe_unavailable") from None
    return facts, probes
