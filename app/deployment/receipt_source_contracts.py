"""Closed inert receipt-source documents and their fixed release recipe."""

from hashlib import sha256

from app.domain.refs import DomainContractError, canonical_json
from app.domain.wire import WireInputError, WireLimits, parse_json_object
from app.operations.setup import OriginProfile, SetupContractError

from . import contracts as sources

DeploymentSourceError = sources.DeploymentSourceError

RECEIPT_RECIPE = {
    "schema_version": "deployment-receipt-recipe-v1",
    "recipe_id": "stage-receipt-channels-v1",
    "prepare_recipe": {
        "path": "deploy/security/deployment-prepare-recipe-v1.json",
        "sha256": "03490ee7c676a0c78915fdef3ec48c52d6b88838ad71bce001ad2fe72f5e67b7",
        "size_bytes": 606,
    },
    "renderer_id": "deeptwin-receipt-source-expand-v1",
    "initializer_id": "deeptwin-receipt-public-init-v1",
    "incoming_final_limit": 64,
    "consumed_final_limit": 16,
    "staging_limit": 32,
    "receipt_bytes_max": 16384,
    "consumption_bytes_max": 4096,
}
RECEIPT_RECIPE_BYTES = canonical_json(RECEIPT_RECIPE)
RECEIPT_RECIPE_SHA256 = sha256(RECEIPT_RECIPE_BYTES).hexdigest()

_RECIPE_FIELDS = tuple(RECEIPT_RECIPE)
_INSTANCE_FIELDS = (
    "schema_version",
    "prepare_instance_sha256",
    "trust_set_sha256",
    "receipt_ingress_id",
    "consumption_exchange_id",
)
_INGRESS_FIELDS = (
    "schema_version",
    "ingress_id",
    "revision",
    "instance_id",
    "origin_profile_digest",
    "prepare_recipe_digest",
    "prepare_instance_digest",
    "outgoing_exchange_digest",
    "receipt_recipe_digest",
    "receipt_instance_digest",
    "trust_set_digest",
    "writer",
    "reader",
    "incoming",
)
_CONSUMPTION_FIELDS = (
    "schema_version",
    "exchange_id",
    "revision",
    "instance_id",
    "origin_profile_digest",
    "outgoing_exchange_digest",
    "receipt_recipe_digest",
    "receipt_instance_digest",
    "trust_set_digest",
    "receipt_ingress_digest",
    "control",
    "reader",
    "outgoing",
)


def _parse(raw, *, fields, cap, depth, items):
    value = parse_json_object(
        raw,
        required=fields,
        limits=WireLimits(
            max_bytes=cap,
            max_depth=depth,
            max_items=items,
            max_members=32,
            max_string_bytes=256,
        ),
    )
    if canonical_json(value) != raw:
        raise DeploymentSourceError()
    return value


def _profile(value):
    if type(value) is not OriginProfile:
        raise DeploymentSourceError()
    return value


def _supported_pins(receipt_recipe_sha256, receipt_instance_sha256):
    recipe = sources.hex_digest(receipt_recipe_sha256)
    instance = sources.hex_digest(receipt_instance_sha256)
    if recipe != RECEIPT_RECIPE_SHA256:
        raise DeploymentSourceError()
    return recipe, instance


def _ingress_document(
    profile,
    *,
    ingress_id,
    prepare_recipe_digest,
    prepare_instance_digest,
    outgoing_exchange_digest,
    receipt_recipe_digest,
    receipt_instance_digest,
    trust_set_digest,
):
    return {
        "schema_version": "deployment-receipt-ingress-v1",
        "ingress_id": sources.uuid(ingress_id),
        "revision": 1,
        "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest,
        "prepare_recipe_digest": sources.hex_digest(prepare_recipe_digest),
        "prepare_instance_digest": sources.hex_digest(prepare_instance_digest),
        "outgoing_exchange_digest": sources.hex_digest(outgoing_exchange_digest),
        "receipt_recipe_digest": sources.hex_digest(receipt_recipe_digest),
        "receipt_instance_digest": sources.hex_digest(receipt_instance_digest),
        "trust_set_digest": sources.hex_digest(trust_set_digest),
        "writer": {
            "service_identity": "deployment-receipt-job",
            "uid": 20113,
            "gid": 20113,
            "pair_gid": 21201,
        },
        "reader": {
            "service_identity": "control",
            "uid": 20102,
            "gid": 20102,
            "pair_gid": 21201,
        },
        "incoming": {
            "volume_name": f"dt-{profile.instance_id}-deployment-receipts",
            "container_path": "/run/deeptwin/deployment-receipts",
            "owner_uid": 20113,
            "group_gid": 21201,
            "root_mode": "0750",
            "namespace_mode": "0750",
            "final_file_mode": "0440",
            "writer_read_only": False,
            "control_read_only": True,
            "namespaces": ["receipts"],
        },
    }


def _consumption_document(
    profile,
    *,
    exchange_id,
    outgoing_exchange_digest,
    receipt_recipe_digest,
    receipt_instance_digest,
    trust_set_digest,
    receipt_ingress_digest,
):
    return {
        "schema_version": "deployment-consumption-exchange-v1",
        "exchange_id": sources.uuid(exchange_id),
        "revision": 1,
        "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest,
        "outgoing_exchange_digest": sources.hex_digest(outgoing_exchange_digest),
        "receipt_recipe_digest": sources.hex_digest(receipt_recipe_digest),
        "receipt_instance_digest": sources.hex_digest(receipt_instance_digest),
        "trust_set_digest": sources.hex_digest(trust_set_digest),
        "receipt_ingress_digest": sources.hex_digest(receipt_ingress_digest),
        "control": {
            "service_identity": "control",
            "uid": 20102,
            "gid": 20102,
        },
        "reader": {
            "service_identity": "deployment-receipt-job",
            "uid": 20113,
            "gid": 20113,
            "pair_gid": 21201,
        },
        "outgoing": {
            "volume_name": f"dt-{profile.instance_id}-deployment-consumed",
            "container_path": "/run/deeptwin/deployment-consumed",
            "owner_uid": 20102,
            "group_gid": 21201,
            "root_mode": "0750",
            "namespace_mode": "0750",
            "final_file_mode": "0440",
            "control_read_only": False,
            "reader_read_only": True,
            "namespaces": ["consumed"],
        },
    }


def parse_receipt_recipe(raw: bytes) -> dict:
    try:
        value = _parse(
            raw,
            fields=_RECIPE_FIELDS,
            cap=4096,
            depth=6,
            items=128,
        )
        if raw != RECEIPT_RECIPE_BYTES:
            raise DeploymentSourceError()
        return value
    except DeploymentSourceError:
        raise
    except (DomainContractError, WireInputError, TypeError, ValueError, RecursionError):
        raise DeploymentSourceError() from None


def parse_receipt_instance(raw: bytes) -> dict:
    try:
        value = _parse(
            raw,
            fields=_INSTANCE_FIELDS,
            cap=4096,
            depth=4,
            items=64,
        )
        if value["schema_version"] != "deployment-receipt-instance-v1":
            raise DeploymentSourceError()
        sources.hex_digest(value["prepare_instance_sha256"])
        sources.hex_digest(value["trust_set_sha256"])
        sources.uuid(value["receipt_ingress_id"])
        sources.uuid(value["consumption_exchange_id"])
        if value["receipt_ingress_id"] == value["consumption_exchange_id"]:
            raise DeploymentSourceError()
        return value
    except DeploymentSourceError:
        raise
    except (
        DomainContractError,
        WireInputError,
        KeyError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise DeploymentSourceError() from None


def parse_ingress(
    raw: bytes,
    *,
    profile: OriginProfile,
    receipt_recipe_sha256: str,
    receipt_instance_sha256: str,
) -> dict:
    try:
        checked_profile = _profile(profile)
        recipe_pin, instance_pin = _supported_pins(
            receipt_recipe_sha256, receipt_instance_sha256
        )
        value = _parse(
            raw,
            fields=_INGRESS_FIELDS,
            cap=8192,
            depth=8,
            items=256,
        )
        sources.integer(value["revision"], 1, 1)
        expected = _ingress_document(
            checked_profile,
            ingress_id=value["ingress_id"],
            prepare_recipe_digest=value["prepare_recipe_digest"],
            prepare_instance_digest=value["prepare_instance_digest"],
            outgoing_exchange_digest=value["outgoing_exchange_digest"],
            receipt_recipe_digest=recipe_pin,
            receipt_instance_digest=instance_pin,
            trust_set_digest=value["trust_set_digest"],
        )
        if raw != sources.encode(expected):
            raise DeploymentSourceError()
        return value
    except DeploymentSourceError:
        raise
    except (
        DomainContractError,
        SetupContractError,
        WireInputError,
        KeyError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise DeploymentSourceError() from None


def parse_consumption_exchange(
    raw: bytes,
    *,
    profile: OriginProfile,
    receipt_recipe_sha256: str,
    receipt_instance_sha256: str,
) -> dict:
    try:
        checked_profile = _profile(profile)
        recipe_pin, instance_pin = _supported_pins(
            receipt_recipe_sha256, receipt_instance_sha256
        )
        value = _parse(
            raw,
            fields=_CONSUMPTION_FIELDS,
            cap=8192,
            depth=8,
            items=256,
        )
        sources.integer(value["revision"], 1, 1)
        expected = _consumption_document(
            checked_profile,
            exchange_id=value["exchange_id"],
            outgoing_exchange_digest=value["outgoing_exchange_digest"],
            receipt_recipe_digest=recipe_pin,
            receipt_instance_digest=instance_pin,
            trust_set_digest=value["trust_set_digest"],
            receipt_ingress_digest=value["receipt_ingress_digest"],
        )
        if raw != sources.encode(expected):
            raise DeploymentSourceError()
        return value
    except DeploymentSourceError:
        raise
    except (
        DomainContractError,
        SetupContractError,
        WireInputError,
        KeyError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise DeploymentSourceError() from None


__all__ = [
    "RECEIPT_RECIPE",
    "RECEIPT_RECIPE_BYTES",
    "RECEIPT_RECIPE_SHA256",
    "DeploymentSourceError",
    "parse_consumption_exchange",
    "parse_ingress",
    "parse_receipt_instance",
    "parse_receipt_recipe",
]
