"""Closed provider source declarations and complete actual-byte graph joins.

These public declarations grant no runtime, image, operator or payload authority.
"""

import re

from jsonschema import Draft202012Validator

from app.domain.wire import WireLimits, parse_json_object
from app.operations.setup import OriginProfile, parse_base64url_32

from . import contracts as sources
from . import receipt_source_contracts as receipts
from .receipt_contracts import parse_trust_set
from .provider_geometry import derive_provider_geometry, parse_provider_geometry

DeploymentSourceError = sources.DeploymentSourceError

PROVIDER_RECIPE = {
    "schema_version": "deployment-provider-source-recipe-v1",
    "recipe_id": "private-provider-source-channels-v1",
    "original_prepare_recipe": {
        "path": "deploy/security/deployment-prepare-recipe-v1.json",
        "sha256": "03490ee7c676a0c78915fdef3ec48c52d6b88838ad71bce001ad2fe72f5e67b7",
        "size_bytes": 606,
    },
    "original_receipt_recipe": {
        "path": "deploy/security/deployment-receipt-recipe-v1.json",
        "sha256": "3417fbc488ab745019b909564282cc9ff971c99fa2d5ba592e4faeb2f742e173",
        "size_bytes": 487,
    },
    "renderer_id": "deeptwin-provider-source-expand-v1",
    "initializer_id": "deeptwin-provider-source-init-v1",
    "layout_id": "provider-source-bundle-v1",
    "worker_profile": "claude-text-transform-v1",
    "channel_bootstrap_policy": "owned-channel-layout-v1",
    "bundle_file_limit": 18, "bundle_bytes_max": 524288,
    "request_bytes_max": 65536, "cancellation_bytes_max": 8192,
    "receipt_bytes_max": 16384, "consumption_bytes_max": 8192,
}
PROVIDER_RECIPE_BYTES = sources.encode(PROVIDER_RECIPE)
PROVIDER_RECIPE_SHA256 = sources.digest(PROVIDER_RECIPE_BYTES)
BUNDLE_LAYOUT = (
    ("original-prepare-recipe.json", 4096), ("original-prepare-instance.json", 4096),
    ("original-topology.json", 65536), ("original-outgoing-exchange.json", 8192),
    ("original-receipt-recipe.json", 4096), ("original-receipt-instance.json", 4096),
    ("original-trust-set.json", 16384), ("original-receipt-ingress.json", 8192),
    ("original-consumption-exchange.json", 8192), ("geometry.json", 65536),
    ("provider-recipe.json", 8192), ("provider-instance.json", 8192),
    ("provider-trust-set.json", 16384), ("outgoing-exchange.json", 8192),
    ("receipt-ingress.json", 8192), ("consumption-exchange.json", 8192),
    ("source-context.json", 16384), ("source-pins.json", 8192),
)
PROVIDER_VOLUMES = (
    ("provider-stage-sources", "/run/deeptwin/provider-stage-sources", True),
    ("provider-deployment-outbox", "/run/deeptwin/provider-deployment-outbox", False),
    ("provider-deployment-receipts", "/run/deeptwin/provider-deployment-receipts", True),
    ("provider-deployment-consumed", "/run/deeptwin/provider-deployment-consumed", False),
)
ORIGINAL_PUBLIC_VOLUMES = (
    ("extension-topology-public", "/run/deeptwin/extension-topology"),
    ("deployment-exchange-public", "/run/deeptwin/deployment-exchange"),
    ("deployment-verify-public", "/run/deeptwin/deployment-verify-public"),
    ("deployment-receipt-ingress-public", "/run/deeptwin/deployment-receipt-ingress"),
    ("deployment-consumption-exchange-public", "/run/deeptwin/deployment-consumption-exchange"),
)
CONFIG_LAYOUT = (
    ("original-prepare-instance", "original-prepare-instance.json"),
    ("original-receipt-instance", "original-receipt-instance.json"),
    ("original-trust", "original-trust-set.json"), ("instance", "provider-instance.json"),
    ("trust", "provider-trust-set.json"), ("pins", "provider-source-pins.json"),
)
INPUT_ROOT = "/run/deeptwin/provider-source-init-input"


def _require(condition):
    if not condition:
        raise DeploymentSourceError()


def _image(value):
    _require(type(value) is str and value.isascii() and len(value) <= 584 and value.count("@") == 1)
    name, digest = value.split("@")
    _require(re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None and "/" in name)
    registry, repository = name.split("/", 1)
    _require(1 <= len(registry) <= 253 and 1 <= len(repository) <= 255)
    _require(all(re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", part)
                 for part in repository.split("/")))
    _require(registry.count(":") <= 1)
    host, separator, port = registry.partition(":")
    if separator:
        _require(re.fullmatch(r"[1-9][0-9]{0,4}", port) is not None and int(port) <= 65535)
    _require(host == "localhost" or "." in host or bool(separator))
    _require(all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                 for label in host.split(".")))


def _parse(raw, kind, cap):
    from . import provider_source_schema_exports as schemas
    try:
        schema = getattr(schemas, "provider_" + kind + "_schema")()
        value = parse_json_object(raw, required=schema["required"], limits=WireLimits(
            max_bytes=cap, max_depth=12, max_items=4096, max_members=32,
            max_string_bytes=1024, max_integer=2**40))
        _require(sources.encode(value) == raw and Draft202012Validator(schema).is_valid(value))
        if "provider_recipe_sha256" in value:
            _require(value["provider_recipe_sha256"] == PROVIDER_RECIPE_SHA256)
        if kind in ("instance", "expansion_record"):
            _image(value["initializer_image"])
        if kind == "instance":
            _require(len({value[key] for key in ("context_id", "exchange_id", "ingress_id", "consumption_exchange_id")}) == 4)
        if kind == "trust":
            keys = value["keys"]
            identifiers = [key["key_id"] for key in keys]
            _require(identifiers == sorted(set(identifiers)))
            _require(len({key["public_key"] for key in keys}) == len(keys))
            for key in keys:
                parse_base64url_32(key["public_key"])
        if kind in ("exchange", "ingress", "consumption"):
            leaf = "incoming" if kind == "ingress" else "outgoing"
            suffix = {"exchange": "outbox", "ingress": "receipts", "consumption": "consumed"}[kind]
            _require(value[leaf]["volume_name"] == f"dt-{value['instance_id']}-provider-deployment-{suffix}")
        return value
    except DeploymentSourceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        raise DeploymentSourceError() from None


def parse_provider_recipe(raw: bytes) -> dict:
    return _parse(raw, "recipe", 8192)


def parse_provider_instance(raw: bytes) -> dict:
    return _parse(raw, "instance", 8192)


def parse_provider_trust(raw: bytes) -> dict:
    return _parse(raw, "trust", 16384)


def parse_provider_exchange(raw: bytes) -> dict:
    return _parse(raw, "exchange", 8192)


def parse_provider_ingress(raw: bytes) -> dict:
    return _parse(raw, "ingress", 8192)


def parse_provider_consumption(raw: bytes) -> dict:
    return _parse(raw, "consumption", 8192)


def parse_provider_context(raw: bytes) -> dict:
    return _parse(raw, "context", 16384)


def parse_provider_pins(raw: bytes) -> dict:
    return _parse(raw, "pins", 8192)


def parse_provider_expansion_record(raw: bytes) -> dict:
    return _parse(raw, "expansion_record", 8192)


def _channel_document(kind, *, profile, instance, geometry_sha256, instance_sha256,
                      trust_sha256, exchange_sha256=None, ingress_sha256=None):
    ingress, consumption = kind == "ingress", kind == "consumption"
    suffix = "receipts" if ingress else "consumed" if consumption else "outbox"
    schema_kind = "receipt-ingress" if ingress else "consumption-exchange" if consumption else "outgoing-exchange"
    operator = {"service_identity": "deployment-receipt-job", "uid": 20113, "gid": 20113, "pair_gid": 21201}
    result = {
        "schema_version": "deployment-provider-" + schema_kind + "-v1",
        "document_id": instance[{"exchange": "exchange_id", "ingress": "ingress_id", "consumption": "consumption_exchange_id"}[kind]],
        "revision": 1, "instance_id": profile.instance_id, "origin_profile_digest": profile.digest,
        "geometry_sha256": geometry_sha256, "provider_recipe_sha256": PROVIDER_RECIPE_SHA256,
        "provider_instance_sha256": instance_sha256,
    }
    channel = {
        "volume_name": f"dt-{profile.instance_id}-provider-deployment-{suffix}",
        "container_path": "/run/deeptwin/provider-deployment-" + suffix,
        "owner_uid": 20113 if ingress else 20102, "group_gid": 21201,
        "root_mode": "0750", "namespace_mode": "0750", "final_file_mode": "0440",
    }
    if ingress or consumption:
        result.update(outgoing_exchange_sha256=exchange_sha256, trust_sha256=trust_sha256)
    if consumption:
        result["receipt_ingress_sha256"] = ingress_sha256
    if ingress:
        result.update(writer=operator, reader={**sources.CONTROL, "pair_gid": 21201})
        channel.update(writer_read_only=False, control_read_only=True, namespaces=["receipts"])
    else:
        result.update(control=dict(sources.CONTROL), reader=operator)
        channel.update(control_read_only=False, reader_read_only=True,
                       namespaces=["consumed"] if consumption else ["cancelled", "requests"])
    result["incoming" if ingress else "outgoing"] = channel
    return result


def _context_document(*, profile, topology_id, instance, geometry_sha256, first_sixteen):
    return {
        "schema_version": "deployment-provider-source-context-v1", "context_id": instance["context_id"],
        "epoch": 1, "instance_id": profile.instance_id, "origin_profile_digest": profile.digest,
        "topology_id": topology_id, "topology_revision": 1, "geometry_sha256": geometry_sha256,
        "worker_profile": "claude-text-transform-v1", "layout_id": "provider-source-bundle-v1",
        "documents": [{"name": name, "sha256": sources.digest(raw), "size_bytes": len(raw)}
                      for name, raw in first_sixteen],
    }


def _pins_document(*, profile, instance, context_bytes, instance_sha256, geometry_sha256):
    return {
        "schema_version": "deployment-provider-source-pins-v1", "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest, "context_id": instance["context_id"],
        "context_sha256": sources.digest(context_bytes), "context_size_bytes": len(context_bytes),
        "provider_recipe_sha256": PROVIDER_RECIPE_SHA256, "provider_instance_sha256": instance_sha256,
        "geometry_sha256": geometry_sha256,
    }


def _original_joins(raw):
    """Original parsers plus their deliberately deferred actual-source edges."""
    sources.parse_recipe(raw[0])
    prepare = sources.parse_instance(raw[1])
    profile = OriginProfile.from_dict(prepare["origin_profile"])
    geometry = derive_provider_geometry(original_recipe_bytes=raw[0], original_instance_bytes=raw[1],
                                        original_topology_bytes=raw[2])
    outgoing = sources.parse_exchange(raw[3], profile=profile, recipe_sha256=sources.digest(raw[0]),
                                     instance_sha256=sources.digest(raw[1]))
    _require(outgoing["exchange_id"] == prepare["exchange_id"])
    receipts.parse_receipt_recipe(raw[4])
    receipt = receipts.parse_receipt_instance(raw[5])
    parse_trust_set(raw[6], profile=profile)
    _require(receipt["prepare_instance_sha256"] == sources.digest(raw[1]))
    _require(receipt["trust_set_sha256"] == sources.digest(raw[6]))
    options = dict(profile=profile, receipt_recipe_sha256=sources.digest(raw[4]),
                   receipt_instance_sha256=sources.digest(raw[5]))
    ingress = receipts.parse_ingress(raw[7], **options)
    consumption = receipts.parse_consumption_exchange(raw[8], **options)
    _require(ingress["ingress_id"] == receipt["receipt_ingress_id"])
    _require(consumption["exchange_id"] == receipt["consumption_exchange_id"])
    for key, index in (("prepare_recipe_digest", 0), ("prepare_instance_digest", 1),
                       ("outgoing_exchange_digest", 3), ("receipt_recipe_digest", 4),
                       ("receipt_instance_digest", 5), ("trust_set_digest", 6)):
        _require(ingress[key] == sources.digest(raw[index]))
    for key, index in (("outgoing_exchange_digest", 3), ("receipt_recipe_digest", 4),
                       ("receipt_instance_digest", 5), ("trust_set_digest", 6), ("receipt_ingress_digest", 7)):
        _require(consumption[key] == sources.digest(raw[index]))
    ids = {prepare["topology_id"], prepare["exchange_id"], receipt["receipt_ingress_id"], receipt["consumption_exchange_id"]}
    _require(len(ids) == 4)
    return profile, prepare, geometry, ids


def validate_provider_source_bundle(bundle_files: tuple[tuple[str, bytes], ...]) -> None:
    """Reparse all eighteen actual files; no cached values or ambient sources."""
    try:
        _require(type(bundle_files) is tuple and len(bundle_files) == 18)
        for pair, (name, cap) in zip(bundle_files, BUNDLE_LAYOUT, strict=True):
            _require(type(pair) is tuple and len(pair) == 2)
            _require(type(pair[0]) is str and pair[0] == name)
            _require(type(pair[1]) is bytes and 1 <= len(pair[1]) <= cap)
        raw = tuple(pair[1] for pair in bundle_files)
        _require(sum(map(len, raw)) <= 524288)
        profile, prepare, geometry, old_ids = _original_joins(raw)
        parsed_geometry = parse_provider_geometry(raw[9])
        _require(parsed_geometry.content_bytes == geometry.content_bytes)
        parse_provider_recipe(raw[10])
        instance = parse_provider_instance(raw[11])
        trust = parse_provider_trust(raw[12])
        new_ids = {instance[key] for key in ("context_id", "exchange_id", "ingress_id", "consumption_exchange_id")}
        _require(len(new_ids) == 4 and not new_ids.intersection(old_ids))
        for field, index in (("original_prepare_instance_sha256", 1), ("original_receipt_instance_sha256", 5),
                             ("geometry_sha256", 9), ("provider_recipe_sha256", 10), ("provider_trust_sha256", 12)):
            _require(instance[field] == sources.digest(raw[index]))
        _require(trust["instance_id"] == profile.instance_id and trust["origin_profile_digest"] == profile.digest)
        _require(trust["adapter"]["deployment_profile_id"] == profile.deployment_profile_id)
        options = dict(profile=profile, instance=instance, geometry_sha256=sources.digest(raw[9]),
                       instance_sha256=sources.digest(raw[11]), trust_sha256=sources.digest(raw[12]))
        for kind, index in (("exchange", 13), ("ingress", 14), ("consumption", 15)):
            _parse(raw[index], kind, 8192)
            expected = _channel_document(kind, **options, exchange_sha256=sources.digest(raw[13]),
                                         ingress_sha256=sources.digest(raw[14]))
            _require(raw[index] == sources.encode(expected))
        parse_provider_context(raw[16])
        expected_context = _context_document(profile=profile, topology_id=prepare["topology_id"], instance=instance,
                                             geometry_sha256=sources.digest(raw[9]), first_sixteen=bundle_files[:16])
        _require(raw[16] == sources.encode(expected_context))
        parse_provider_pins(raw[17])
        expected_pins = _pins_document(profile=profile, instance=instance, context_bytes=raw[16],
                                       instance_sha256=sources.digest(raw[11]), geometry_sha256=sources.digest(raw[9]))
        _require(raw[17] == sources.encode(expected_pins))
    except DeploymentSourceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        raise DeploymentSourceError() from None
