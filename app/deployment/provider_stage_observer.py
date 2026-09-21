"""Two authenticated provider identifies; observations confer no admission."""

from .stage_observer import StagePostconditionError
from .stage_observer import _process_boot_id, _now
from ..domain.refs import canonical_json, uuid_string
from ..operations.setup import parse_base64url_32
from .provider_receipt_contracts import _raw
from .provider_receipt_schema_exports import (
    provider_stage_postcondition_v1_schema,
    _expected,
)
from .prepare_contracts import epoch_ms
from .receipt_contracts import _validate
from ..workers import broker, ipc_root, listener, provider_messages
from ..workers.extension_channel import extension_channel
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4
import math
import secrets
import time


def _require(condition, code="probe_invalid"):
    if not condition:
        raise StagePostconditionError(code)


@dataclass(frozen=True, slots=True)
class ExpectedProviderStageIdentity:
    service_identity: str
    build_identity_digest: str
    port_schema_set_digest: str
    port_contract_version: str
    platform: str
    uid: int
    gid: int
    worker_profile: str = "claude-text-transform-v1"
    implemented_transforms: tuple = ("catalog", "text")

    def __post_init__(self):
        try:
            _require(
                type(self.uid) is int
                and type(self.gid) is int
                and type(self.implemented_transforms) is tuple
            )
            _validate(self.as_dict(), _expected())
        except (ValueError, TypeError):
            raise StagePostconditionError("probe_invalid") from None

    def as_dict(self):
        return {
            "service_identity": self.service_identity,
            "build_identity_digest": self.build_identity_digest,
            "port_schema_set_digest": self.port_schema_set_digest,
            "port_contract_version": self.port_contract_version,
            "platform": self.platform,
            "uid": self.uid,
            "gid": self.gid,
            "worker_profile": self.worker_profile,
            "implemented_transforms": list(self.implemented_transforms),
        }


class ProviderStageEvidence:
    __slots__ = ("content_bytes", "digest", "size_bytes")

    def __new__(cls):
        raise TypeError("evidence requires the actual observer")

    def __setattr__(self, name, value):
        raise AttributeError("evidence is immutable")

    def __delattr__(self, name):
        raise AttributeError("evidence is immutable")

    def __reduce__(self):
        raise TypeError("evidence cannot be serialized")


def _challenge(value, ordinal, nonce):
    return sha256(
        canonical_json(
            {
                "domain": "deeptwin-provider-stage-identify-challenge-v1",
                **{
                    k: value[k]
                    for k in (
                        "request_blob_sha256",
                        "receipt_blob_sha256",
                        "source_context_sha256",
                        "preserved_inventory_sha256",
                    )
                },
                "ordinal": ordinal,
                "nonce": nonce,
            }
        )
    ).hexdigest()


def parse_provider_stage_evidence(raw: bytes) -> dict:
    try:
        value = _raw(raw, provider_stage_postcondition_v1_schema(), 8192)
        for k in ("request_digest", "receipt_digest"):
            parse_base64url_32(value[k])
        _require(
            parse_base64url_32(value["receipt_digest"]).hex()
            == value["receipt_blob_sha256"]
        )
        observations = value["observations"]
        _require([o["ordinal"] for o in observations] == [1, 2])
        _require(
            len(
                {
                    o[k]
                    for o in observations
                    for k in ("request_message_id", "reply_message_id")
                }
            )
            == 4
        )
        for k in ("connection_id", "nonce", "challenge"):
            _require(observations[0][k] != observations[1][k])
        for k in ("requester_boot_id", "responder_boot_id", "listener_record_sha256"):
            _require(observations[0][k] == observations[1][k])
        expected = {
            k: v for k, v in value["expected"].items() if k != "port_contract_version"
        }
        for observation in observations:
            _require(
                observation["challenge"]
                == _challenge(value, observation["ordinal"], observation["nonce"])
            )
            _require(
                observation["reply"]
                == {
                    "schema": "provider-worker-identity-v1",
                    "challenge": observation["challenge"],
                    **expected,
                },
                "probe_mismatch",
            )
            _require(
                (observation["peer_uid"], observation["peer_gid"])
                == (expected["uid"], expected["gid"]),
                "probe_mismatch",
            )
        _require(
            epoch_ms(observations[0]["observed_at"])
            <= epoch_ms(observations[1]["observed_at"])
            == epoch_ms(value["observed_at"])
        )
        return value
    except StagePostconditionError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise StagePostconditionError("probe_invalid") from None


def observe_provider_stage_postcondition(
    *,
    request_id,
    request_digest,
    receipt_digest,
    request_bytes,
    receipt_bytes,
    source_context_sha256,
    preserved_inventory_sha256,
    instance_id,
    slot_number,
    expected,
    deadline,
):
    try:
        uuid_string(request_id)
        parse_base64url_32(request_digest)
        parse_base64url_32(receipt_digest)
        _require(
            type(request_bytes) is bytes
            and 1 <= len(request_bytes) <= 65536
            and type(receipt_bytes) is bytes
            and 1 <= len(receipt_bytes) <= 16384
        )
        _require(
            type(expected) is ExpectedProviderStageIdentity
            and type(deadline) is broker.Deadline
        )
        expected.__post_init__()
        _require(type(slot_number) is int and 1 <= slot_number <= 16)
        for digest in (source_context_sha256, preserved_inventory_sha256):
            _require(
                type(digest) is str
                and len(digest) == 64
                and all(c in "0123456789abcdef" for c in digest)
            )
        _require(parse_base64url_32(receipt_digest) == sha256(receipt_bytes).digest())
        root, spec = extension_channel(instance_id=instance_id, slot_number=slot_number)
    except StagePostconditionError:
        raise
    except (ValueError, TypeError, AttributeError):
        raise StagePostconditionError("probe_invalid") from None
    value = {
        "schema_version": "provider-stage-postcondition-v1",
        "request_id": request_id,
        "request_digest": request_digest,
        "receipt_digest": receipt_digest,
        "request_blob_sha256": sha256(request_bytes).hexdigest(),
        "receipt_blob_sha256": sha256(receipt_bytes).hexdigest(),
        "source_context_sha256": source_context_sha256,
        "preserved_inventory_sha256": preserved_inventory_sha256,
        "expected": expected.as_dict(),
        "comparison": "equal",
    }
    started = time.monotonic()
    attempt = deadline.bounded(2000)
    boot = _process_boot_id()
    observations, records, ids, nonces, connections = [], [], set(), set(), set()
    try:
        for ordinal in (1, 2):
            connection = None
            primary = None
            try:
                one = attempt.bounded(1000)
                connection = listener._connect_extension_authenticated(
                    root, spec, requester_boot_id=boot, deadline=one
                )
                session, peer = connection.session, connection.peer
                _require(
                    type(peer) is broker.PeerCredentials
                    and (peer.uid, peer.gid) == (expected.uid, expected.gid),
                    "probe_mismatch",
                )
                _require(
                    session.requester_boot_id == boot
                    and session.responder_boot_id == connection.record.responder_boot_id
                )
                _require(session.connection_id not in connections)
                connections.add(session.connection_id)
                nonce, mid = secrets.token_hex(32), str(uuid4())
                _require(nonce not in nonces and mid not in ids)
                nonces.add(nonce)
                ids.add(mid)
                challenge = _challenge(value, ordinal, nonce)
                connection.write(
                    message_id=mid,
                    correlation_id=None,
                    message_type="extension-request-v1",
                    payload=provider_messages.encode_control(
                        {
                            "schema": "provider-worker-identify-v1",
                            "challenge": challenge,
                        }
                    ),
                    deadline=one,
                )
                frame = connection.read(deadline=one)
                envelope = frame.envelope
                _require(
                    envelope.message_type == "extension-result-v1"
                    and envelope.correlation_id == mid
                )
                rid = uuid_string(envelope.message_id)
                _require(rid not in ids)
                ids.add(rid)
                reply = provider_messages.parse_control(frame.payload)
                _require(
                    reply
                    == {
                        "schema": "provider-worker-identity-v1",
                        "challenge": challenge,
                        **{
                            k: v
                            for k, v in expected.as_dict().items()
                            if k != "port_contract_version"
                        },
                    },
                    "probe_mismatch",
                )
                connection.recheck()
                _require(
                    one.remaining() > 0 and attempt.remaining() > 0, "probe_deadline"
                )
                record = connection.record.unsigned()
                if records:
                    _require(record == records[0], "probe_mismatch")
                records.append(record)
                observed = _now()
                observations.append(
                    {
                        "ordinal": ordinal,
                        "observed_at": observed,
                        "connection_id": session.connection_id,
                        "requester_boot_id": boot,
                        "responder_boot_id": session.responder_boot_id,
                        "listener_record_sha256": sha256(
                            canonical_json(record)
                        ).hexdigest(),
                        "peer_uid": peer.uid,
                        "peer_gid": peer.gid,
                        "nonce": nonce,
                        "challenge": challenge,
                        "request_message_id": mid,
                        "reply_message_id": rid,
                        "reply": reply,
                    }
                )
                if ordinal == 2:
                    elapsed = max(1, math.ceil((time.monotonic() - started) * 1000))
                    _require(
                        elapsed <= 2000 and attempt.remaining() > 0, "probe_deadline"
                    )
            except BaseException as error:
                primary = error
                raise
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except BaseException:
                        if primary is None:
                            raise
        value.update(
            observations=observations,
            observed_at=observations[-1]["observed_at"],
            attempt_ms=elapsed,
        )
        raw = canonical_json(value)
        parse_provider_stage_evidence(raw)
        result = object.__new__(ProviderStageEvidence)
        for name, val in (
            ("content_bytes", raw),
            ("digest", sha256(raw).hexdigest()),
            ("size_bytes", len(raw)),
        ):
            object.__setattr__(result, name, val)
        return result
    except StagePostconditionError:
        raise
    except broker.DeadlineExceeded:
        raise StagePostconditionError("probe_deadline") from None
    except (listener.ListenerError, broker.BrokerError, ipc_root.IpcRootError, OSError):
        raise StagePostconditionError(
            "probe_deadline" if attempt.remaining() <= 0 else "probe_unavailable"
        ) from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise StagePostconditionError("probe_invalid") from None
