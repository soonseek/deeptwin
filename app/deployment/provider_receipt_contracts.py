"""Pure provider receipt codecs; parsed values never confer authority."""

from ..domain.refs import uuid_string
from ..extensions.candidate_schema_exports import const, obj, uuid_schema
from .provider_prepare_contracts import _input
from .provider_prepare_schema_exports import _b32
from .prepare_contracts import DeploymentPrepareError
from ..domain.refs import parse_canonical
from dataclasses import dataclass
from types import MappingProxyType
from hashlib import sha256
import re
from datetime import datetime, UTC
from ..domain.refs import canonical_json
from ..domain.wire import WireLimits, parse_json_object
from ..operations.setup import OriginProfile, parse_base64url_32
from .receipt_contracts import (
    ReceiptWireError,
    RECEIPT_FIELDS,
    _signature,
    _timestamp,
    _require,
    _validate,
)
from .prepare_contracts import b64, epoch_ms, stamp
from .provider_prepare_contracts import parse_provider_request
from .provider_source_contracts import (
    validate_provider_source_bundle,
    parse_provider_trust,
)
from . import provider_receipt_schema_exports as schemas


class ReceiptRequestMismatch(ReceiptWireError):
    """A structurally valid signed claim does not bind the selected request."""


def _matches(condition):
    if not condition:
        raise ReceiptRequestMismatch()


def _raw(raw, schema, cap, *, depth=12, items=512, members=32, string=1024):
    try:
        fields = schema.get("required") or schema["oneOf"][0]["required"]
        value = parse_json_object(
            raw,
            required=fields,
            limits=WireLimits(
                max_bytes=cap,
                max_depth=depth,
                max_items=items,
                max_members=members,
                max_string_bytes=string,
            ),
        )
        _require(canonical_json(value) == raw)
        _validate(value, schema)
        return value
    except ReceiptWireError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ReceiptWireError() from None


def _native_ns(value):
    _require(
        type(value) is str
        and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{9}Z", value
        )
        is not None
    )
    try:
        parsed = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        raise ReceiptWireError() from None
    delta = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + int(value[20:29])


def parse_provider_receipt(raw: bytes) -> dict:
    value = _raw(raw, schemas.provider_receipt_v1_schema(), 16384)
    try:
        for name in ("request_id", "key_id"):
            uuid_string(value[name])
        for name in (
            "request_digest",
            "request_nonce",
            "origin_profile_digest",
            "trust_set_digest",
        ):
            parse_base64url_32(value[name])
        _signature(value["signature"])
        start, end = _timestamp(value["started_at"]), _timestamp(value["completed_at"])
        _require(start <= end)
        service = value["effect_result"]["new_service"]
        if "observed_at" in service:
            _require(start <= _timestamp(service["observed_at"]) <= end)
        if value["outcome"] == "unknown":
            _require(service["failure_class"] == value["failure_class"])
        all_facts = []
        for name in ("claimed_facts", "verified_facts", "unverified_facts"):
            facts = value[name]
            _require(facts == sorted(set(facts)))
            all_facts.extend(facts)
        _require(len(all_facts) <= 8 and len(set(all_facts)) == len(all_facts))
        for observation in value["effect_result"]["preservation"].get(
            "observations", []
        ):
            before, after = observation["before"], observation["after"]
            _require(
                start
                <= _timestamp(before["observed_at"])
                <= _timestamp(after["observed_at"])
                <= end
            )
            _require(
                {k: v for k, v in before.items() if k != "observed_at"}
                == {k: v for k, v in after.items() if k != "observed_at"}
            )
            _require(
                _native_ns(before["started_at"])
                <= epoch_ms(before["observed_at"]) * 1_000_000
            )
        return value
    except ReceiptWireError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ReceiptWireError() from None


def verify_provider_receipt(
    raw: bytes,
    *,
    request_bytes: bytes,
    trust_bytes: bytes,
    source_bundle_files: tuple[tuple[str, bytes], ...],
    profile: OriginProfile,
) -> dict:
    try:
        value = parse_provider_receipt(raw)
        request = parse_provider_request(request_bytes, profile=profile)
        validate_provider_source_bundle(source_bundle_files)
        sources = dict(source_bundle_files)
        _require(sources["provider-trust-set.json"] == trust_bytes)
        trust = parse_provider_trust(trust_bytes)
        _require(
            trust["instance_id"] == profile.instance_id
            and trust["origin_profile_digest"] == profile.digest
        )
        _require(value["trust_set_digest"] == b64(sha256(trust_bytes).digest()))
        key = next((k for k in trust["keys"] if k["key_id"] == value["key_id"]), None)
        _require(
            key is not None
            and key["algorithm"] == "ed25519"
            and key["trust_class"] == value["trust_class"]
            and value["operator_adapter"] in key["adapter_ids"]
        )
        _require(
            trust["adapter"]
            == {
                k: value[k]
                for k in (
                    "operator_adapter",
                    "operator_version",
                    "deployment_profile_id",
                )
            }
            and value["deployment_profile_id"] == profile.deployment_profile_id
        )
        preimage = canonical_json(
            {k: value[k] for k in RECEIPT_FIELDS if k != "signature"}
        )
        from .receipt_crypto import verify_detached

        _require(
            verify_detached(
                parse_base64url_32(key["public_key"]),
                preimage,
                _signature(value["signature"]),
            )
            == preimage
        )
        _matches(
            all(
                value[k] == request[k]
                for k in (
                    "request_id",
                    "request_digest",
                    "request_nonce",
                    "kind",
                    "instance_id",
                    "origin_profile_digest",
                )
            )
        )
        stage, result = request["effect_payload"], value["effect_result"]
        _matches(
            all(
                result[k] == stage[k]
                for k in (
                    "extension_id",
                    "expected_installation_head",
                    "expected_next_installation_revision",
                    "stage_profile",
                    "source_context",
                    "geometry",
                    "preserved_inventory_sha256",
                )
            )
        )
        _matches(
            stage["source_context"]
            == {
                "context_id": parse_canonical(sources["source-context.json"])[
                    "context_id"
                ],
                "epoch": 1,
                "sha256": sha256(sources["source-context.json"]).hexdigest(),
                "size_bytes": len(sources["source-context.json"]),
            }
        )
        _matches(
            stage["geometry"]
            == {
                "sha256": sha256(sources["geometry.json"]).hexdigest(),
                "size_bytes": len(sources["geometry.json"]),
            }
        )
        target = result["new_service"]
        expected = dict(
            service_identity=stage["new_service_effect"]["service_identity"],
            manifest_digest=stage["manifest_digest"],
            service_descriptor_digest=stage["service_descriptor_digest"],
            selected_platform_entry_digest=sha256(
                canonical_json(stage["selected_platform_entry"])
            ).hexdigest(),
            image_manifest_digest=stage["selected_platform_entry"]["manifest_digest"],
        )
        if target["presence"] != "absent":
            prefix = "expected_" if target["presence"] == "unknown" else ""
            _matches(all(target[prefix + k] == v for k, v in expected.items()))
        _require(
            _timestamp(request["created_at"])
            <= _timestamp(value["started_at"])
            <= _timestamp(value["completed_at"])
            < _timestamp(request["expires_at"])
        )
        preservation = result["preservation"]
        if preservation["state"] == "preserved":
            inventory = stage["preserved_inventory"]["installations"]
            _matches(len(inventory) == len(preservation["observations"]))
            geometry = parse_canonical(sources["geometry.json"])
            for prior, sample in zip(
                inventory, preservation["observations"], strict=True
            ):
                slot = geometry["slots"][prior["slot_id"] - 1]
                _matches(
                    sample["slot_id"] == prior["slot_id"]
                    and sample["service_identity"]
                    == prior["service_identity"]
                    == slot["service_identity"]
                )
                for snap in (sample["before"], sample["after"]):
                    _matches(
                        snap["configured_uid"] == slot["uid"]
                        and snap["configured_gid"] == slot["gid"]
                        and snap["socket_volume"] == slot["socket_mount"]["volume_name"]
                        and snap["socket_path"]
                        == slot["socket_mount"]["container_path"]
                    )
        return value
    except ReceiptWireError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise ReceiptWireError() from None


def _selector(request_id, value, revision):
    try:
        uuid_string(request_id)
        if type(value) is not dict or type(value.get("expected_revision")) is not int:
            raise DeploymentPrepareError("invalid_input")
        parsed = _input(
            value,
            obj(
                command_id=uuid_schema(),
                request_digest=_b32(),
                receipt_digest=_b32(),
                expected_revision=const(revision),
            ),
        )
        return {**parsed, "request_id": request_id}
    except (TypeError, ValueError):
        raise DeploymentPrepareError("invalid_input") from None


def parse_provider_receipt_import(request_id: str, value: dict) -> dict:
    return _selector(request_id, value, 1)


def parse_provider_consume(request_id: str, value: dict) -> dict:
    return _selector(request_id, value, 2)


def parse_provider_pending_cancel(request_id: str, value: dict) -> dict:
    return _selector(request_id, value, 2)


def validate_provider_channel_identity(value: dict) -> None:
    _raw(
        canonical_json(value),
        schemas._identity(),
        2048,
        depth=4,
        items=64,
        members=8,
        string=256,
    )


@dataclass(frozen=True, slots=True)
class ProviderReceiptChannelIdentity:
    schema_version: str
    source_context_sha256: str
    incoming: dict
    consumed: dict

    def __post_init__(self):
        value = self.as_dict()
        for name in ("incoming", "consumed"):
            channel = value[name]
            object.__setattr__(
                self,
                name,
                MappingProxyType(
                    {
                        key: MappingProxyType(child) if type(child) is dict else child
                        for key, child in channel.items()
                    }
                ),
            )

    def as_dict(self):
        value = {
            k: getattr(self, k) for k in ("schema_version", "source_context_sha256")
        }
        for name in ("incoming", "consumed"):
            value[name] = {
                key: dict(child)
                if isinstance(child, (dict, MappingProxyType))
                else child
                for key, child in getattr(self, name).items()
            }
        validate_provider_channel_identity(value)
        return parse_canonical(canonical_json(value))


def _marker(raw, profile, schema):
    value = _raw(raw, schema, 8192, depth=4, items=64, members=16, string=256)
    _require(
        type(profile) is OriginProfile
        and OriginProfile.from_dict(profile.as_dict()) == profile
    )
    _matches(
        value["instance_id"] == profile.instance_id
        and value["origin_profile_digest"] == b64(bytes.fromhex(profile.digest))
    )
    for key in ("request_digest", "receipt_digest", "origin_profile_digest"):
        parse_base64url_32(value[key])
    for key in ("cancelled_at", "consumed_at"):
        if key in value:
            _timestamp(value[key])
    return value


def parse_provider_pending_cancellation(raw: bytes, *, profile: OriginProfile) -> dict:
    return _marker(raw, profile, schemas.provider_cancellation_v2_schema())


def parse_provider_consumed(raw: bytes, *, profile: OriginProfile) -> dict:
    return _marker(raw, profile, schemas.provider_consumption_v1_schema())


def make_provider_pending_cancellation(
    *,
    request_bytes: bytes,
    receipt_bytes: bytes,
    profile: OriginProfile,
    cancelled_ms: int,
) -> bytes:
    request = parse_provider_request(request_bytes, profile=profile)
    receipt = parse_provider_receipt(receipt_bytes)
    _matches(
        receipt["outcome"] == "succeeded"
        and all(
            receipt[k] == request[k]
            for k in (
                "request_id",
                "request_digest",
                "request_nonce",
                "instance_id",
                "origin_profile_digest",
            )
        )
    )
    _matches(
        type(cancelled_ms) is int
        and epoch_ms(receipt["completed_at"])
        <= cancelled_ms
        < epoch_ms(request["expires_at"])
    )
    raw = canonical_json(
        {
            "schema": "deployment-provider-cancellation-v2",
            "domain": "deeptwin-deployment-provider-cancellation-v2",
            **{
                k: request[k]
                for k in (
                    "request_id",
                    "request_digest",
                    "instance_id",
                    "origin_profile_digest",
                )
            },
            "receipt_digest": b64(sha256(receipt_bytes).digest()),
            "source_context_sha256": request["effect_payload"]["source_context"][
                "sha256"
            ],
            "preserved_inventory_sha256": request["effect_payload"][
                "preserved_inventory_sha256"
            ],
            "lifecycle_revision": 3,
            "cancelled_at": stamp(cancelled_ms),
        }
    )
    parse_provider_pending_cancellation(raw, profile=profile)
    return raw
