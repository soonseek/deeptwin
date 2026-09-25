"""Pure owner-recovery request/receipt/trust-set v2 decoding and verification.

A recovery advances the deployment's recovery epoch N to exactly N+1: the product seals a
`deployment-request-v1` of kind `owner_recovery` naming the current session-root generation,
and the instance operator returns a detached PureEd25519 `deployment-recovery-receipt-v1`
over the ADR-008 canonical JSON of every other receipt field, verified against the
`deployment-public-trust-set-v2` with a key that lists `deeptwin-recovery-operator-v1`.

The receipt fixes the new generation completely: its `new_manifest_sha256` is the digest of
the recovered manifest core, which `recovered_manifest_core` rebuilds from the receipt alone
(generation id, a key id derived from it, the epoch, the completion time and the parent), so
the root maintenance and the reconciliation start can each recompute it. Returned values
remain inert: nothing here touches a root, a database or a network.
"""

import re
from base64 import urlsafe_b64encode
from datetime import timedelta
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, canonical_json, parse_canonical, uuid_string
from ..domain.wire import WireLimits
from ..operations.setup import OriginProfile, parse_base64url_32
from .receipt_contracts import (
    ReceiptWireError,
    _parse,
    _require,
    _signature,
    _timestamp,
    _validate,
)
from .recovery_schema_exports import (
    ADAPTER_VERSION,
    RECOVERY_ADAPTER,
    STAGE_ADAPTER,
    recovery_receipt_schema,
    recovery_request_schema,
    trust_set_v2_schema,
)

TRUST_V2_FIELDS = (
    "schema",
    "domain",
    "version",
    "instance_id",
    "origin_profile_digest",
    "previous_trust_set_digest",
    "keys",
    "adapters",
)
RECOVERY_RECEIPT_FIELDS = (
    "schema",
    "domain",
    "request_id",
    "request_digest",
    "request_nonce",
    "kind",
    "instance_id",
    "origin_profile_digest",
    "deployment_profile_id",
    "operator_adapter",
    "operator_version",
    "previous_epoch",
    "previous_generation_id",
    "previous_manifest_sha256",
    "new_epoch",
    "new_generation_id",
    "new_manifest_sha256",
    "new_verifier_sha256",
    "completed_at",
    "key_id",
    "trust_set_digest",
    "trust_class",
    "signature",
)
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_MAX_REQUEST_MS = 86_400_000


def _b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _origin(profile):
    return _b64(bytes.fromhex(profile.digest))


def _hex(value):
    _require(type(value) is str and _HEX_64.fullmatch(value) is not None)
    return value


def verifier_sha256(verifier_b64u: str) -> str:
    """The receipt's binding of the new deployment verifier (never the capability)."""
    parse_base64url_32(verifier_b64u)
    return sha256(verifier_b64u.encode("ascii")).hexdigest()


def recovery_key_id(generation_id: str) -> str:
    """The recovered generation's key id: derived, so the receipt alone fixes the core."""
    return str(uuid5(NAMESPACE_URL, "deeptwin:session-root-key:" + uuid_string(generation_id)))


def recovered_manifest_core(receipt: dict, *, profile: OriginProfile) -> dict:
    """The recovered generation's manifest without its receipt digest and integrity tag."""
    _require(type(profile) is OriginProfile)
    return {
        "schema_version": "session-root-v2",
        "generation_id": receipt["new_generation_id"],
        "key_id": recovery_key_id(receipt["new_generation_id"]),
        "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest,
        "recovery_epoch": receipt["new_epoch"],
        "created_at": receipt["completed_at"],
        "state": "recovered",
        "parent_generation_id": receipt["previous_generation_id"],
    }


def manifest_core_sha256(core: dict) -> str:
    return sha256(canonical_json(core)).hexdigest()


def parse_trust_set_v2(raw: bytes, *, profile: OriginProfile) -> dict:
    try:
        _require(type(profile) is OriginProfile)
        value = _parse(
            raw,
            fields=TRUST_V2_FIELDS,
            limits=WireLimits(
                max_bytes=16384,
                max_depth=8,
                max_items=512,
                max_members=32,
                max_string_bytes=256,
            ),
        )
        _validate(value, trust_set_v2_schema())
        _require(
            value["instance_id"] == profile.instance_id
            and value["origin_profile_digest"] == _origin(profile)
            # v1 plus exactly one recovery adapter entry, in that order
            and value["adapters"]
            == [
                {
                    "operator_adapter": adapter,
                    "operator_version": ADAPTER_VERSION,
                    "deployment_profile_id": profile.deployment_profile_id,
                }
                for adapter in (STAGE_ADAPTER, RECOVERY_ADAPTER)
            ]
        )
        if value["previous_trust_set_digest"] is not None:
            parse_base64url_32(value["previous_trust_set_digest"])
        ids, public_keys = [], []
        for key in value["keys"]:
            uuid_string(key["key_id"])
            parse_base64url_32(key["public_key"])
            _require(key["adapter_ids"] == sorted(key["adapter_ids"]))
            ids.append(key["key_id"])
            public_keys.append(key["public_key"])
        _require(ids == sorted(ids) and len(ids) == len(set(ids)))
        _require(len(public_keys) == len(set(public_keys)))
        return value
    except ReceiptWireError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ReceiptWireError() from None


def verify_trust_set_upgrade(v1_raw: bytes, v2_raw: bytes, *, profile: OriginProfile) -> dict:
    """The update-safe v1→v2 step: v2 names the exact prior v1 bytes and keeps every v1
    key (same id, public key and trust class) able to sign stage receipts."""
    from .receipt_contracts import parse_trust_set

    try:
        previous = parse_trust_set(v1_raw, profile=profile)
        current = parse_trust_set_v2(v2_raw, profile=profile)
        _require(current["previous_trust_set_digest"] == _b64(sha256(v1_raw).digest()))
        keys = {key["key_id"]: key for key in current["keys"]}
        for key in previous["keys"]:
            kept = keys.get(key["key_id"])
            _require(
                kept is not None
                and kept["public_key"] == key["public_key"]
                and kept["trust_class"] == key["trust_class"]
                and STAGE_ADAPTER in kept["adapter_ids"]
            )
        return current
    except ReceiptWireError:
        raise
    except (KeyError, TypeError, ValueError):
        raise ReceiptWireError() from None


def make_recovery_request(
    *,
    profile,
    request_id,
    nonce,
    actor_ref,
    created_ms,
    ttl_seconds,
    current_epoch,
    current_generation_id,
    current_manifest_sha256,
):
    """Seal one owner-recovery request; it never carries a capability or a verifier."""
    from .prepare_contracts import interval

    _require(type(nonce) is bytes and len(nonce) == 32 and type(current_epoch) is int)
    created_at, expires_at = interval(created_ms, ttl_seconds)
    value = {
        "schema": "deployment-request-v1",
        "domain": "deeptwin-deployment-request-v1",
        "request_id": request_id,
        "kind": "owner_recovery",
        "request_nonce": _b64(nonce),
        "instance_id": profile.instance_id,
        "origin_profile_digest": _origin(profile),
        "effect_payload": {"target_recovery_epoch": current_epoch + 1},
        "preconditions": {
            "current_recovery_epoch": current_epoch,
            "current_session_root_generation_id": current_generation_id,
            "current_session_root_manifest_sha256": current_manifest_sha256,
        },
        "created_by": actor_ref,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    value["request_digest"] = _b64(sha256(canonical_json(value)).digest())
    raw = canonical_json(value)
    parse_recovery_request(raw, profile=profile)
    return raw


def parse_recovery_request(raw: bytes, *, profile: OriginProfile) -> dict:
    try:
        _require(type(profile) is OriginProfile and type(raw) is bytes and len(raw) <= 4096)
        value = parse_canonical(raw)
        _validate(value, recovery_request_schema())
        _require(
            value["instance_id"] == profile.instance_id
            and value["origin_profile_digest"] == _origin(profile)
        )
        uuid_string(value["request_id"])
        parse_base64url_32(value["request_nonce"])
        _require(EntityRef.from_dict(value["created_by"]).kind == "actor")
        preconditions = value["preconditions"]
        uuid_string(preconditions["current_session_root_generation_id"])
        _hex(preconditions["current_session_root_manifest_sha256"])
        # exactly N -> N+1: a skipped (or repeated) epoch is refused at parse time
        _require(
            value["effect_payload"]["target_recovery_epoch"]
            == preconditions["current_recovery_epoch"] + 1
        )
        preimage = canonical_json(
            {key: item for key, item in value.items() if key != "request_digest"}
        )
        _require(value["request_digest"] == _b64(sha256(preimage).digest()))
        duration = _timestamp(value["expires_at"]) - _timestamp(value["created_at"])
        _require(
            timedelta(minutes=1) <= duration <= timedelta(milliseconds=_MAX_REQUEST_MS)
            and duration % timedelta(seconds=1) == timedelta(0)
        )
        return value
    except ReceiptWireError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ReceiptWireError() from None


def parse_recovery_receipt(raw: bytes) -> dict:
    try:
        value = _parse(
            raw,
            fields=RECOVERY_RECEIPT_FIELDS,
            limits=WireLimits(
                max_bytes=8192,
                max_depth=4,
                max_items=64,
                max_members=32,
                max_string_bytes=256,
            ),
        )
        _validate(value, recovery_receipt_schema())
        for name in ("request_id", "key_id", "previous_generation_id", "new_generation_id"):
            uuid_string(value[name])
        for name in (
            "request_digest",
            "request_nonce",
            "origin_profile_digest",
            "trust_set_digest",
        ):
            parse_base64url_32(value[name])
        for name in ("previous_manifest_sha256", "new_manifest_sha256", "new_verifier_sha256"):
            _hex(value[name])
        _signature(value["signature"])
        _timestamp(value["completed_at"])
        _require(
            value["new_epoch"] == value["previous_epoch"] + 1
            and value["new_generation_id"] != value["previous_generation_id"]
        )
        return value
    except ReceiptWireError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ReceiptWireError() from None


def receipt_preimage(receipt: dict) -> bytes:
    """The exact signed bytes: ADR-008 canonical JSON of every field but the signature."""
    return canonical_json(
        {name: receipt[name] for name in RECOVERY_RECEIPT_FIELDS if name != "signature"}
    )


def verify_recovery_receipt(
    raw: bytes,
    *,
    request_bytes: bytes,
    trust_bytes: bytes,
    profile: OriginProfile,
) -> dict:
    """Verify a recovery receipt against its request and the v2 trust set.

    The caller still binds the result to the actual current generations (the root being
    advanced, or the database control row being reconciled): this checks only that the
    receipt is authentic, request-bound, in time and internally a single N→N+1 step.
    """
    try:
        receipt = parse_recovery_receipt(raw)
        request = parse_recovery_request(request_bytes, profile=profile)
        trust = parse_trust_set_v2(trust_bytes, profile=profile)
        _require(receipt["trust_set_digest"] == _b64(sha256(trust_bytes).digest()))
        key = next(
            (entry for entry in trust["keys"] if entry["key_id"] == receipt["key_id"]),
            None,
        )
        # a stage-only key never signs a recovery, whatever the receipt claims
        _require(
            key is not None
            and key["algorithm"] == "ed25519"
            and key["trust_class"] == receipt["trust_class"]
            and RECOVERY_ADAPTER in key["adapter_ids"]
            and receipt["operator_adapter"] == RECOVERY_ADAPTER
            and receipt["operator_version"] == ADAPTER_VERSION
            and receipt["deployment_profile_id"] == profile.deployment_profile_id
        )
        preimage = receipt_preimage(receipt)
        from .receipt_crypto import verify_detached

        verified = verify_detached(
            parse_base64url_32(key["public_key"]),
            preimage,
            _signature(receipt["signature"]),
        )
        _require(verified == preimage)
        preconditions = request["preconditions"]
        _require(
            all(
                receipt[name] == request[name]
                for name in (
                    "request_id",
                    "request_digest",
                    "request_nonce",
                    "kind",
                    "instance_id",
                    "origin_profile_digest",
                )
            )
            and receipt["instance_id"] == profile.instance_id
            and receipt["origin_profile_digest"] == _origin(profile)
            and receipt["previous_epoch"] == preconditions["current_recovery_epoch"]
            and receipt["previous_generation_id"]
            == preconditions["current_session_root_generation_id"]
            and receipt["previous_manifest_sha256"]
            == preconditions["current_session_root_manifest_sha256"]
            and receipt["new_epoch"] == request["effect_payload"]["target_recovery_epoch"]
        )
        _require(
            _timestamp(request["created_at"])
            <= _timestamp(receipt["completed_at"])
            < _timestamp(request["expires_at"])
        )
        _require(
            receipt["new_manifest_sha256"]
            == manifest_core_sha256(recovered_manifest_core(receipt, profile=profile))
        )
        return receipt
    except ReceiptWireError:
        raise
    except (KeyError, StopIteration, TypeError, ValueError, RecursionError):
        raise ReceiptWireError() from None


__all__ = [
    "RECOVERY_RECEIPT_FIELDS",
    "make_recovery_request",
    "manifest_core_sha256",
    "parse_recovery_receipt",
    "parse_recovery_request",
    "parse_trust_set_v2",
    "receipt_preimage",
    "recovered_manifest_core",
    "recovery_key_id",
    "verifier_sha256",
    "verify_recovery_receipt",
    "verify_trust_set_upgrade",
]
