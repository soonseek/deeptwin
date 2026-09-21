"""Pure deterministic provider bundle production and additive candidate Compose."""

import json
from copy import deepcopy
from dataclasses import dataclass

from app.operations.setup import OriginProfile

from . import contracts as sources
from . import provider_source_contracts as provider
from .provider_geometry import derive_provider_geometry
from .receipt_render import ReceiptSourceArtifacts, render_receipt_sources


@dataclass(frozen=True, slots=True)
class ProviderSourceArtifacts:
    original_artifacts: ReceiptSourceArtifacts
    geometry_bytes: bytes
    exchange_bytes: bytes
    ingress_bytes: bytes
    consumption_exchange_bytes: bytes
    context_bytes: bytes
    pins_bytes: bytes
    bundle_files: tuple[tuple[str, bytes], ...]
    expanded_compose_bytes: bytes
    expansion_record_bytes: bytes


def _insert(mapping, name, value):
    if type(mapping) is not dict or name in mapping:
        raise sources.DeploymentSourceError()
    mapping[name] = value


def _mount(name, target, read_only):
    return {"type": "volume", "source": name, "target": target, "read_only": read_only,
            "volume": {"nocopy": True}}


def _overlap(left, right):
    return left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")


def _expand(original_bytes, *, instance_id, initializer_image, context_sha256):
    before = sources.parse(original_bytes, cap=1048576, depth=32, items=10000, canonical=False)
    expanded = deepcopy(before)
    services, volumes, configs = (expanded[key] for key in ("services", "volumes", "configs"))
    provider._require(all(type(value) is dict for value in (services, volumes, configs)))
    control = services["control"]
    provider._require(type(control) is dict and type(control["volumes"]) is list
                      and type(control["group_add"]) is list and control["group_add"].count("21201") == 1)
    new_targets = [target for _, target, _ in provider.PROVIDER_VOLUMES] + [provider.INPUT_ROOT]
    # No existing mount or config target may be shadowed by any new provider root.
    for service in services.values():
        for mount in (*service.get("volumes", ()), *service.get("configs", ())):
            provider._require(type(mount) is dict and type(mount.get("target")) is str)
            provider._require(not any(_overlap(mount["target"], target) for target in new_targets))
    init_mounts = []
    for name, target, readonly in provider.PROVIDER_VOLUMES:
        actual_name = f"dt-{instance_id}-{name}"
        provider._require(not any(value.get("name") == actual_name for value in volumes.values()))
        _insert(volumes, name, {"name": actual_name})
        control["volumes"].append(_mount(name, target, readonly))
        init_mounts.append(_mount(name, target, False))
    for name, target in provider.ORIGINAL_PUBLIC_VOLUMES:
        provider._require(name in volumes)
        init_mounts.append(_mount(name, target, True))
    config_mounts = []
    new_configs = []
    for suffix, filename in provider.CONFIG_LAYOUT:
        name = f"dt-{instance_id}-provider-source-{suffix}"
        provider._require(not any(value.get("name") == name for value in configs.values()))
        _insert(configs, name, {"external": True, "name": name})
        new_configs.append(name)
        config_mounts.append({"source": name, "target": provider.INPUT_ROOT + "/" + filename,
                              "uid": "0", "gid": "0", "mode": 0o440})
    condition = {"condition": "service_completed_successfully"}
    _insert(control["depends_on"], "provider-source-root-init", dict(condition))
    _insert(control["environment"], "DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256", context_sha256)
    _insert(services, "provider-source-root-init", {
        "image": initializer_image,
        "entrypoint": ["python", "-m", "app.operations.deployment_provider_source_init"],
        "command": [], "user": "0:0", "group_add": ["21201"], "restart": "no", "init": True,
        "privileged": False, "read_only": True, "network_mode": "none", "cap_drop": ["ALL"],
        "cap_add": ["CHOWN", "FOWNER", "FSETID"], "security_opt": ["no-new-privileges:true"],
        "tty": False, "stdin_open": False, "pids_limit": 32, "mem_limit": "64m", "cpus": 0.25,
        "ulimits": {"nofile": {"soft": 256, "hard": 256}}, "volumes": init_mounts,
        "configs": config_mounts,
        "depends_on": {name: dict(condition) for name in (
            "deployment-prepare-root-init", "deployment-receipt-public-init")},
    })
    stripped = deepcopy(expanded)
    del stripped["services"]["provider-source-root-init"]
    del stripped["services"]["control"]["volumes"][-4:]
    del stripped["services"]["control"]["depends_on"]["provider-source-root-init"]
    del stripped["services"]["control"]["environment"]["DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256"]
    for name, _, _ in provider.PROVIDER_VOLUMES:
        del stripped["volumes"][name]
    for name in new_configs:
        del stripped["configs"][name]
    provider._require(stripped == before)
    # Compose uses its historical finite-number codec, not integer-only source JSON.
    result = json.dumps(expanded, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False).encode("utf-8")
    sources.parse(result, cap=1048576, depth=32, items=10000, canonical=False)
    return result


def render_provider_sources(*, base_compose_bytes, base_service_ids_bytes,
                            original_prepare_recipe_bytes, original_prepare_instance_bytes,
                            original_receipt_recipe_bytes, original_receipt_instance_bytes,
                            original_trust_bytes, provider_recipe_bytes, provider_instance_bytes,
                            provider_trust_bytes) -> ProviderSourceArtifacts:
    """Produce source artifacts only: no image fetching, source opening or admission."""
    try:
        raw = (base_compose_bytes, base_service_ids_bytes, original_prepare_recipe_bytes,
               original_prepare_instance_bytes, original_receipt_recipe_bytes,
               original_receipt_instance_bytes, original_trust_bytes,
               provider_recipe_bytes, provider_instance_bytes, provider_trust_bytes)
        provider._require(all(type(value) is bytes for value in raw))
        provider._require(sum(map(len, raw)) <= 2097152)
        original = render_receipt_sources(*raw[:7])
        provider.parse_provider_recipe(provider_recipe_bytes)
        instance = provider.parse_provider_instance(provider_instance_bytes)
        provider.parse_provider_trust(provider_trust_bytes)
        prepare_instance = sources.parse_instance(original_prepare_instance_bytes)
        profile = OriginProfile.from_dict(prepare_instance["origin_profile"])
        geometry = derive_provider_geometry(original_recipe_bytes=original_prepare_recipe_bytes,
                                             original_instance_bytes=original_prepare_instance_bytes,
                                             original_topology_bytes=original.prepare_artifacts.topology_bytes)
        geometry_bytes = geometry.content_bytes
        common = dict(profile=profile, instance=instance, geometry_sha256=geometry.digest,
                      instance_sha256=sources.digest(provider_instance_bytes), trust_sha256=sources.digest(provider_trust_bytes))
        exchange = sources.encode(provider._channel_document("exchange", **common))
        ingress = sources.encode(provider._channel_document("ingress", **common, exchange_sha256=sources.digest(exchange)))
        consumption = sources.encode(provider._channel_document("consumption", **common,
                                      exchange_sha256=sources.digest(exchange), ingress_sha256=sources.digest(ingress)))
        contents = (
            original_prepare_recipe_bytes, original_prepare_instance_bytes,
            original.prepare_artifacts.topology_bytes, original.prepare_artifacts.exchange_bytes,
            original_receipt_recipe_bytes, original_receipt_instance_bytes, original_trust_bytes,
            original.ingress_bytes, original.consumption_exchange_bytes, geometry_bytes,
            provider_recipe_bytes, provider_instance_bytes, provider_trust_bytes, exchange, ingress, consumption,
        )
        first_sixteen = tuple((name, content) for (name, _), content in zip(provider.BUNDLE_LAYOUT[:16], contents, strict=True))
        context = sources.encode(provider._context_document(profile=profile, topology_id=prepare_instance["topology_id"],
                                 instance=instance, geometry_sha256=geometry.digest, first_sixteen=first_sixteen))
        pins = sources.encode(provider._pins_document(profile=profile, instance=instance, context_bytes=context,
                              instance_sha256=sources.digest(provider_instance_bytes), geometry_sha256=geometry.digest))
        bundle = first_sixteen + (("source-context.json", context), ("source-pins.json", pins))
        provider.validate_provider_source_bundle(bundle)
        expanded = _expand(original.expanded_compose_bytes, instance_id=profile.instance_id,
                           initializer_image=instance["initializer_image"], context_sha256=sources.digest(context))
        record = sources.encode({
            "schema_version": "deployment-provider-source-expansion-record-v1", "scope": "provider_sources_only",
            "renderer_id": "deeptwin-provider-source-expand-v1", "initializer_id": "deeptwin-provider-source-init-v1",
            "original_expansion_sha256": sources.digest(original.expanded_compose_bytes),
            "original_expansion_size_bytes": len(original.expanded_compose_bytes),
            "original_expansion_record_sha256": sources.digest(original.expansion_record_bytes),
            "provider_recipe_sha256": sources.digest(provider_recipe_bytes), "provider_instance_sha256": sources.digest(provider_instance_bytes),
            "geometry_sha256": geometry.digest, "context_sha256": sources.digest(context), "pins_sha256": sources.digest(pins),
            "initializer_image": instance["initializer_image"], "expanded_compose_sha256": sources.digest(expanded),
            "expanded_compose_size_bytes": len(expanded),
        })
        provider.parse_provider_expansion_record(record)
        return ProviderSourceArtifacts(original, geometry_bytes, exchange, ingress, consumption,
                                       context, pins, bundle, expanded, record)
    except sources.DeploymentSourceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        raise sources.DeploymentSourceError() from None
