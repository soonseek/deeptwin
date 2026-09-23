"""Pure receipt/trust decoding and verification; returned values remain inert."""

import re
from base64 import b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from hashlib import sha256
from types import MappingProxyType

from jsonschema import Draft202012Validator, FormatChecker

from ..domain.refs import canonical_json, uuid_string
from ..domain.wire import WireLimits, parse_json_object
from ..operations.setup import OriginProfile, parse_base64url_32
from .receipt_schema_exports import (
    FACTS,
    UNKNOWN_FAILURES,
    receipt_schema,
    trust_set_schema,
)

ERRORS = MappingProxyType(
    {
        "receipt_invalid": "receipt_invalid",
        "receipt_signature_invalid": "receipt_signature_invalid",
    }
)
RECEIPT_FIELDS = (
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
    "effect_result",
    "started_at",
    "completed_at",
    "outcome",
    "failure_class",
    "claimed_facts",
    "verified_facts",
    "unverified_facts",
    "key_id",
    "trust_set_digest",
    "trust_class",
    "signature",
)
TRUST_FIELDS = (
    "schema",
    "domain",
    "version",
    "instance_id",
    "origin_profile_digest",
    "keys",
    "adapters",
)
_B64U_64 = re.compile(r"[A-Za-z0-9_-]{85}[AQgw]")
_HEX_32 = re.compile(r"[0-9a-f]{32}")


class ReceiptWireError(ValueError):
    def __init__(self, code="receipt_invalid"):
        if type(code) is not str or code not in ERRORS:
            raise ValueError("Unknown receipt wire error code")
        self.code = code
        super().__init__(ERRORS[code])


class _ReceiptRequestMismatch(ReceiptWireError):
    pass


def _require(condition):
    if not condition:
        raise ReceiptWireError()


def _validate(value, schema):
    _require(
        Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value)
    )


def _timestamp(value):
    _require(
        type(value) is str
        and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z",
            value,
        )
        is not None
    )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        raise ReceiptWireError() from None
    # isoformat always pads the year to four digits; glibc's strftime("%Y") does not
    _require(parsed.replace(tzinfo=None).isoformat(timespec="milliseconds") + "Z" == value)
    return parsed


def _signature(value):
    _require(type(value) is str and _B64U_64.fullmatch(value) is not None)
    try:
        decoded = b64decode(value + "==", altchars=b"-_", validate=True)
    except (TypeError, ValueError):
        raise ReceiptWireError() from None
    _require(
        len(decoded) == 64
        and urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") == value
    )
    return decoded


def _parse(raw, *, fields, limits):
    value = parse_json_object(raw, required=fields, limits=limits)
    _require(canonical_json(value) == raw)
    return value


def parse_receipt(raw: bytes) -> dict:
    try:
        value = _parse(
            raw,
            fields=RECEIPT_FIELDS,
            limits=WireLimits(
                max_bytes=16384,
                max_depth=12,
                max_items=512,
                max_members=32,
                max_string_bytes=1024,
            ),
        )
        _validate(value, receipt_schema())
        uuid_string(value["request_id"])
        uuid_string(value["key_id"])
        for name in (
            "request_digest",
            "request_nonce",
            "origin_profile_digest",
            "trust_set_digest",
        ):
            parse_base64url_32(value[name])
        _signature(value["signature"])
        _require(_HEX_32.fullmatch(value["instance_id"]) is not None)
        started = _timestamp(value["started_at"])
        completed = _timestamp(value["completed_at"])
        _require(started <= completed)
        service = value["effect_result"]["new_service"]
        observed = service.get("observed_at")
        if observed is not None:
            _require(started <= _timestamp(observed) <= completed)
        if value["outcome"] == "unknown":
            _require(
                value["failure_class"] in UNKNOWN_FAILURES
                and service["failure_class"] == value["failure_class"]
            )
        lists = [
            value["claimed_facts"],
            value["verified_facts"],
            value["unverified_facts"],
        ]
        _require(
            all(
                facts == sorted(facts)
                and len(facts) == len(set(facts))
                and set(facts).issubset(FACTS)
                for facts in lists
            )
        )
        flattened = [fact for facts in lists for fact in facts]
        _require(len(flattened) <= 8 and len(flattened) == len(set(flattened)))
        return value
    except ReceiptWireError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ReceiptWireError() from None


def parse_trust_set(raw: bytes, *, profile: OriginProfile) -> dict:
    try:
        _require(type(profile) is OriginProfile)
        value = _parse(
            raw,
            fields=TRUST_FIELDS,
            limits=WireLimits(
                max_bytes=16384,
                max_depth=8,
                max_items=512,
                max_members=32,
                max_string_bytes=256,
            ),
        )
        _validate(value, trust_set_schema())
        expected_origin = (
            urlsafe_b64encode(bytes.fromhex(profile.digest))
            .rstrip(b"=")
            .decode("ascii")
        )
        _require(
            value["instance_id"] == profile.instance_id
            and value["origin_profile_digest"] == expected_origin
            and value["adapters"]
            == [
                {
                    "operator_adapter": "deeptwin-stage-operator-v1",
                    "operator_version": "1.0.0",
                    "deployment_profile_id": profile.deployment_profile_id,
                }
            ]
        )
        ids, public_keys = [], []
        for key in value["keys"]:
            uuid_string(key["key_id"])
            parse_base64url_32(key["public_key"])
            ids.append(key["key_id"])
            public_keys.append(key["public_key"])
        _require(ids == sorted(ids) and len(ids) == len(set(ids)))
        _require(len(public_keys) == len(set(public_keys)))
        return value
    except ReceiptWireError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ReceiptWireError() from None


def _check_request_binding(receipt, request, *, profile) -> None:
    def matches(condition):
        if not condition:
            raise _ReceiptRequestMismatch()

    expected_origin = (
        urlsafe_b64encode(bytes.fromhex(profile.digest)).rstrip(b"=").decode("ascii")
    )
    matches(
        all(
            receipt[receipt_name] == request[request_name]
            for receipt_name, request_name in (
                ("request_id", "request_id"),
                ("request_digest", "request_digest"),
                ("request_nonce", "request_nonce"),
                ("kind", "kind"),
                ("instance_id", "instance_id"),
                ("origin_profile_digest", "origin_profile_digest"),
            )
        )
        and receipt["instance_id"] == profile.instance_id
        and receipt["origin_profile_digest"] == expected_origin
        and receipt["deployment_profile_id"] == profile.deployment_profile_id
    )
    result = receipt["effect_result"]
    stage = request["effect_payload"]
    matches(
        result["extension_id"] == stage["extension_id"]
        and result["expected_installation_head"]
        == stage["expected_installation_head"]
        and result["expected_next_installation_revision"]
        == stage["expected_next_installation_revision"]
    )
    service = result["new_service"]
    if service["presence"] == "absent":
        return
    selected = stage["selected_platform_entry"]
    expected = {
        "service_identity": stage["new_service_effect"]["service_identity"],
        "manifest_digest": stage["manifest_digest"],
        "service_descriptor_digest": stage["service_descriptor_digest"],
        "selected_platform_entry_digest": sha256(canonical_json(selected)).hexdigest(),
        "image_manifest_digest": selected["manifest_digest"],
    }
    if service["presence"] == "present":
        matches(all(service[name] == value for name, value in expected.items()))
    else:
        matches(
            all(
                service["expected_" + name] == value
                for name, value in expected.items()
            )
        )


def verify_receipt(
    raw: bytes,
    *,
    request_bytes: bytes,
    trust_bytes: bytes,
    trust_sha256: str,
    profile: OriginProfile,
) -> dict:
    try:
        receipt = parse_receipt(raw)
        from .prepare_contracts import parse_request

        request = parse_request(request_bytes, profile=profile)
        trust = parse_trust_set(trust_bytes, profile=profile)
        _require(
            type(trust_sha256) is str
            and re.fullmatch(r"[0-9a-f]{64}", trust_sha256) is not None
        )
        actual_trust_digest = sha256(trust_bytes).digest()
        _require(
            actual_trust_digest.hex() == trust_sha256
            and receipt["trust_set_digest"]
            == urlsafe_b64encode(actual_trust_digest).rstrip(b"=").decode("ascii")
        )
        key = next(
            (entry for entry in trust["keys"] if entry["key_id"] == receipt["key_id"]),
            None,
        )
        adapter = trust["adapters"][0]
        _require(
            key is not None
            and key["algorithm"] == "ed25519"
            and key["trust_class"] == receipt["trust_class"]
            and receipt["operator_adapter"] in key["adapter_ids"]
            and adapter
            == {
                "operator_adapter": receipt["operator_adapter"],
                "operator_version": receipt["operator_version"],
                "deployment_profile_id": receipt["deployment_profile_id"],
            }
            and receipt["deployment_profile_id"] == profile.deployment_profile_id
        )
        unsigned = {name: receipt[name] for name in RECEIPT_FIELDS if name != "signature"}
        preimage = canonical_json(unsigned)
        from .receipt_crypto import verify_detached

        verified = verify_detached(
            parse_base64url_32(key["public_key"]),
            preimage,
            _signature(receipt["signature"]),
        )
        _require(verified == preimage)
        _check_request_binding(receipt, request, profile=profile)
        _require(
            _timestamp(request["created_at"])
            <= _timestamp(receipt["started_at"])
            <= _timestamp(receipt["completed_at"])
            < _timestamp(request["expires_at"])
        )
        return receipt
    except ReceiptWireError:
        raise
    except (KeyError, StopIteration, TypeError, ValueError, RecursionError):
        raise ReceiptWireError() from None


__all__ = [
    "ReceiptWireError",
    "parse_receipt",
    "parse_trust_set",
    "verify_receipt",
]
