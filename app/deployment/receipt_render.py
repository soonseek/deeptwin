"""Pure expansion of accepted prepare sources into receipt-channel artifacts."""

import json
from dataclasses import dataclass

from app.domain.refs import DomainContractError
from app.operations.setup import OriginProfile, SetupContractError

from . import contracts as sources
from . import receipt_source_contracts as receipt_sources
from .receipt_contracts import ReceiptWireError, parse_trust_set
from .render import render_prepare_sources

_VOLUMES = (
    ("deployment-verify-public", "/run/deeptwin/deployment-verify-public", True),
    (
        "deployment-receipt-ingress-public",
        "/run/deeptwin/deployment-receipt-ingress",
        True,
    ),
    (
        "deployment-consumption-exchange-public",
        "/run/deeptwin/deployment-consumption-exchange",
        True,
    ),
    ("deployment-receipts", "/run/deeptwin/deployment-receipts", True),
    ("deployment-consumed", "/run/deeptwin/deployment-consumed", False),
)


@dataclass(frozen=True, slots=True)
class ReceiptSourceArtifacts:
    prepare_artifacts: sources.PrepareSourceArtifacts
    trust_bytes: bytes
    ingress_bytes: bytes
    consumption_exchange_bytes: bytes
    pins_bytes: bytes
    expanded_compose_bytes: bytes
    expansion_record_bytes: bytes


def _insert(mapping, name, value):
    if type(mapping) is not dict or name in mapping:
        raise sources.DeploymentSourceError()
    mapping[name] = value


def _mount(name, target, read_only):
    return {
        "type": "volume",
        "source": name,
        "target": target,
        "read_only": read_only,
        "volume": {"nocopy": True},
    }


def _expand_compose(base, profile, pins):
    services = base.get("services")
    volumes = base.get("volumes")
    configs = base.get("configs")
    if not all(type(value) is dict for value in (services, volumes, configs)):
        raise sources.DeploymentSourceError()
    control = services.get("control")
    if type(control) is not dict:
        raise sources.DeploymentSourceError()
    control_volumes = control.get("volumes")
    environment = control.get("environment")
    dependencies = control.get("depends_on")
    groups = control.get("group_add")
    if (
        type(control_volumes) is not list
        or type(environment) is not dict
        or type(dependencies) is not dict
        or type(groups) is not list
        or groups.count("21201") != 1
    ):
        raise sources.DeploymentSourceError()
    existing_targets = {
        item.get("target")
        for item in control_volumes
        if type(item) is dict and type(item.get("target")) is str
    }
    init_mounts = []
    for name, target, control_read_only in _VOLUMES:
        if target in existing_targets:
            raise sources.DeploymentSourceError()
        _insert(volumes, name, {"name": f"dt-{profile.instance_id}-{name}"})
        control_volumes.append(_mount(name, target, control_read_only))
        init_mounts.append(_mount(name, target, False))
        existing_targets.add(target)
    _insert(
        dependencies,
        "deployment-receipt-public-init",
        {"condition": "service_completed_successfully"},
    )
    for name, pin in (
        ("DEEPTWIN_RECEIPT_RECIPE_SHA256", "receipt_recipe_sha256"),
        ("DEEPTWIN_RECEIPT_INSTANCE_SHA256", "receipt_instance_sha256"),
        ("DEEPTWIN_DEPLOYMENT_TRUST_SHA256", "trust_sha256"),
        ("DEEPTWIN_RECEIPT_INGRESS_SHA256", "ingress_sha256"),
        (
            "DEEPTWIN_CONSUMPTION_EXCHANGE_SHA256",
            "consumption_exchange_sha256",
        ),
    ):
        _insert(environment, name, pins[pin])
    config_mounts = []
    for suffix, filename in (
        ("prepare-instance", "prepare-instance.json"),
        ("instance", "receipt-instance.json"),
        ("trust", "trust-set.json"),
        ("pins", "receipt-source-pins.json"),
    ):
        name = f"dt-{profile.instance_id}-receipt-{suffix}"
        _insert(configs, name, {"external": True, "name": name})
        config_mounts.append(
            {
                "source": name,
                "target": f"/run/deeptwin/receipt-init-input/{filename}",
                "uid": "0",
                "gid": "0",
                "mode": 0o440,
            }
        )
    _insert(
        services,
        "deployment-receipt-public-init",
        {
            "image": "${DEPLOYMENT_RECEIPT_PUBLIC_INIT_IMAGE:?exact @sha256 image required}",
            "entrypoint": [
                "python",
                "-m",
                "app.operations.deployment_receipt_public_init",
            ],
            "command": [],
            "user": "0:0",
            "group_add": ["21201"],
            "restart": "no",
            "init": True,
            "privileged": False,
            "read_only": True,
            "network_mode": "none",
            "cap_drop": ["ALL"],
            "cap_add": ["CHOWN", "FOWNER", "FSETID"],
            "security_opt": ["no-new-privileges:true"],
            "tty": False,
            "stdin_open": False,
            "pids_limit": 32,
            "mem_limit": "64m",
            "cpus": 0.25,
            "ulimits": {"nofile": {"soft": 256, "hard": 256}},
            "volumes": init_mounts,
            "configs": config_mounts,
        },
    )
    encoded = json.dumps(
        base,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    sources.parse(encoded, cap=1048576, depth=32, items=10000, canonical=False)
    return encoded


def render_receipt_sources(
    base_compose_bytes,
    base_service_ids_bytes,
    prepare_recipe_bytes,
    prepare_instance_bytes,
    receipt_recipe_bytes,
    receipt_instance_bytes,
    trust_bytes,
):
    """Reconstruct the complete acyclic receipt-source graph from seven byte inputs."""
    try:
        prepare = render_prepare_sources(
            base_compose_bytes,
            base_service_ids_bytes,
            prepare_recipe_bytes,
            prepare_instance_bytes,
        )
        prepare_instance = sources.parse_instance(prepare_instance_bytes)
        profile = OriginProfile.from_dict(prepare_instance["origin_profile"])
        receipt_sources.parse_receipt_recipe(receipt_recipe_bytes)
        receipt_instance = receipt_sources.parse_receipt_instance(
            receipt_instance_bytes
        )
        if (
            sources.digest(prepare_recipe_bytes)
            != receipt_sources.RECEIPT_RECIPE["prepare_recipe"]["sha256"]
            or len(prepare_recipe_bytes)
            != receipt_sources.RECEIPT_RECIPE["prepare_recipe"]["size_bytes"]
            or receipt_instance["prepare_instance_sha256"]
            != sources.digest(prepare_instance_bytes)
            or receipt_instance["trust_set_sha256"] != sources.digest(trust_bytes)
        ):
            raise sources.DeploymentSourceError()
        parse_trust_set(trust_bytes, profile=profile)
        identifiers = {
            prepare_instance["topology_id"],
            prepare_instance["exchange_id"],
            receipt_instance["receipt_ingress_id"],
            receipt_instance["consumption_exchange_id"],
        }
        if len(identifiers) != 4:
            raise sources.DeploymentSourceError()

        receipt_recipe_sha256 = sources.digest(receipt_recipe_bytes)
        receipt_instance_sha256 = sources.digest(receipt_instance_bytes)
        trust_sha256 = sources.digest(trust_bytes)
        prepare_exchange_sha256 = sources.digest(prepare.exchange_bytes)
        ingress = receipt_sources._ingress_document(
            profile,
            ingress_id=receipt_instance["receipt_ingress_id"],
            prepare_recipe_digest=sources.digest(prepare_recipe_bytes),
            prepare_instance_digest=sources.digest(prepare_instance_bytes),
            outgoing_exchange_digest=prepare_exchange_sha256,
            receipt_recipe_digest=receipt_recipe_sha256,
            receipt_instance_digest=receipt_instance_sha256,
            trust_set_digest=trust_sha256,
        )
        ingress_bytes = sources.encode(ingress)
        receipt_sources.parse_ingress(
            ingress_bytes,
            profile=profile,
            receipt_recipe_sha256=receipt_recipe_sha256,
            receipt_instance_sha256=receipt_instance_sha256,
        )
        ingress_sha256 = sources.digest(ingress_bytes)
        consumption = receipt_sources._consumption_document(
            profile,
            exchange_id=receipt_instance["consumption_exchange_id"],
            outgoing_exchange_digest=prepare_exchange_sha256,
            receipt_recipe_digest=receipt_recipe_sha256,
            receipt_instance_digest=receipt_instance_sha256,
            trust_set_digest=trust_sha256,
            receipt_ingress_digest=ingress_sha256,
        )
        consumption_bytes = sources.encode(consumption)
        receipt_sources.parse_consumption_exchange(
            consumption_bytes,
            profile=profile,
            receipt_recipe_sha256=receipt_recipe_sha256,
            receipt_instance_sha256=receipt_instance_sha256,
        )
        consumption_sha256 = sources.digest(consumption_bytes)
        pins = {
            "schema_version": "deployment-receipt-source-pins-v1",
            "instance_id": profile.instance_id,
            "origin_profile_digest": profile.digest,
            "prepare_recipe_sha256": sources.digest(prepare_recipe_bytes),
            "prepare_instance_sha256": sources.digest(prepare_instance_bytes),
            "prepare_exchange_sha256": prepare_exchange_sha256,
            "receipt_recipe_sha256": receipt_recipe_sha256,
            "receipt_instance_sha256": receipt_instance_sha256,
            "trust_sha256": trust_sha256,
            "ingress_sha256": ingress_sha256,
            "consumption_exchange_sha256": consumption_sha256,
        }
        pins_bytes = sources.encode(pins)
        sources.parse(pins_bytes, cap=4096, depth=4, items=96)
        expanded = sources.parse(
            prepare.expanded_compose_bytes,
            cap=1048576,
            depth=32,
            items=10000,
            canonical=False,
        )
        expanded_bytes = _expand_compose(expanded, profile, pins)
        record = {
            "schema_version": "deployment-receipt-expansion-record-v1",
            "scope": "receipt_channels_only",
            "base_compose_sha256": sources.digest(base_compose_bytes),
            "base_service_ids_sha256": sources.digest(base_service_ids_bytes),
            "prepare_recipe_sha256": sources.digest(prepare_recipe_bytes),
            "prepare_instance_sha256": sources.digest(prepare_instance_bytes),
            "prepare_topology_sha256": sources.digest(prepare.topology_bytes),
            "prepare_exchange_sha256": prepare_exchange_sha256,
            "prepare_pins_sha256": sources.digest(prepare.pins_bytes),
            "prepare_expansion_sha256": sources.digest(prepare.expanded_compose_bytes),
            "prepare_record_sha256": sources.digest(prepare.expansion_record_bytes),
            "receipt_recipe_sha256": receipt_recipe_sha256,
            "receipt_instance_sha256": receipt_instance_sha256,
            "trust_sha256": trust_sha256,
            "ingress_sha256": ingress_sha256,
            "consumption_exchange_sha256": consumption_sha256,
            "pins_sha256": sources.digest(pins_bytes),
            "expanded_compose_sha256": sources.digest(expanded_bytes),
            "expanded_compose_size_bytes": len(expanded_bytes),
        }
        record_bytes = sources.encode(record)
        sources.parse(record_bytes, cap=4096, depth=4, items=128)
        return ReceiptSourceArtifacts(
            prepare,
            trust_bytes,
            ingress_bytes,
            consumption_bytes,
            pins_bytes,
            expanded_bytes,
            record_bytes,
        )
    except sources.DeploymentSourceError:
        raise
    except (
        DomainContractError,
        ReceiptWireError,
        SetupContractError,
        KeyError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise sources.DeploymentSourceError() from None


__all__ = ["ReceiptSourceArtifacts", "render_receipt_sources"]
