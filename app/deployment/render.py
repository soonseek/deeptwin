"""Pure expansion of the exact release template into finite source artifacts."""

import json

from app.operations.setup import OriginProfile

from . import contracts as c


def _insert(mapping, name, value):
    if name in mapping:
        raise c.DeploymentSourceError()
    mapping[name] = value


def _mount(name, target, read_only):
    return {
        "type": "volume",
        "source": name,
        "target": str(target),
        "read_only": read_only,
        "volume": {"nocopy": True},
    }


def render_prepare_sources(
    base_compose_bytes, base_service_ids_bytes, recipe_bytes, instance_bytes
):
    recipe = c.parse_recipe(recipe_bytes)
    instance = c.parse_instance(instance_bytes)
    for data, key in (
        (base_compose_bytes, "base_compose"),
        (base_service_ids_bytes, "base_service_ids"),
    ):
        if (
            type(data) is not bytes
            or len(data) != recipe[key]["size_bytes"]
            or c.digest(data) != recipe[key]["sha256"]
        ):
            raise c.DeploymentSourceError()
    base = c.parse(
        base_compose_bytes, cap=1048576, depth=32, items=10000, canonical=False
    )
    c.parse(base_service_ids_bytes, cap=65536, depth=32, items=10000, canonical=False)
    profile = OriginProfile.from_dict(instance["origin_profile"])
    rh, ih = c.digest(recipe_bytes), c.digest(instance_bytes)
    topology = c.topology(
        profile,
        instance["topology_id"],
        instance["platform"],
        instance["slot_capacity"],
        rh,
    )
    t = c.encode(topology)
    e = c.encode(c.exchange(profile, instance["exchange_id"], rh, ih))
    pins = {
        "schema_version": "deployment-prepare-source-pins-v1",
        "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest,
        "recipe_sha256": rh,
        "instance_sha256": ih,
        "topology_sha256": c.digest(t),
        "exchange_sha256": c.digest(e),
    }
    p = c.encode(pins)
    control = base["services"]["control"]
    groups = ["21201"] + [str(s["pair_gid"]) for s in topology["slots"]]
    if set(groups) & set(control["group_add"]):
        raise c.DeploymentSourceError()
    control["group_add"].extend(groups)
    _insert(
        control.setdefault("depends_on", {}),
        "deployment-prepare-root-init",
        {"condition": "service_completed_successfully"},
    )
    for key in ("recipe", "instance", "topology", "exchange"):
        prefix = "PREPARE_" if key in ("recipe", "instance") else ""
        _insert(
            control.setdefault("environment", {}),
            f"DEEPTWIN_{prefix}{key.upper()}_SHA256",
            pins[f"{key}_sha256"],
        )
    definitions = [
        ("extension-topology-public", c.TOPOLOGY_ROOT, True),
        ("deployment-exchange-public", c.EXCHANGE_ROOT, True),
        ("deployment-outbox", c.OUTBOX_ROOT, False),
    ] + [
        (f"ipc-xs{s['slot_number']:02}", s["socket_mount"]["container_path"], True)
        for s in topology["slots"]
    ]
    init_mounts = []
    for name, path, ro in definitions:
        _insert(base["volumes"], name, {"name": f"dt-{profile.instance_id}-{name}"})
        if any(v.get("target") == str(path) for v in control["volumes"]):
            raise c.DeploymentSourceError()
        control["volumes"].append(_mount(name, path, ro))
        init_mounts.append(_mount(name, path, False))
    configs = []
    for suffix, filename in (
        ("instance", "prepare-instance.json"),
        ("pins", "prepare-source-pins.json"),
    ):
        name = f"dt-{profile.instance_id}-prepare-{suffix}"
        _insert(base["configs"], name, {"external": True, "name": name})
        configs.append(
            {
                "source": name,
                "target": str(c.INPUT_ROOT / filename),
                "uid": "0",
                "gid": "0",
                "mode": 0o440,
            }
        )
    _insert(
        base["services"],
        "deployment-prepare-root-init",
        {
            "image": "${DEPLOYMENT_PREPARE_INIT_IMAGE:?exact @sha256 image required}",
            "entrypoint": ["python", "-m", "app.operations.deployment_prepare_init"],
            "command": [],
            "user": "0:0",
            "restart": "no",
            "init": True,
            "privileged": False,
            "read_only": True,
            "network_mode": "none",
            "cap_drop": ["ALL"],
            "cap_add": ["CHOWN", "FOWNER", "FSETID"],
            "group_add": list(groups),
            "security_opt": ["no-new-privileges:true"],
            "tty": False,
            "stdin_open": False,
            "pids_limit": 32,
            "mem_limit": "64m",
            "cpus": 0.25,
            "ulimits": {"nofile": {"soft": 256, "hard": 256}},
            "volumes": init_mounts,
            "configs": configs,
        },
    )
    x = json.dumps(
        base, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    c.parse(x, cap=1048576, depth=32, items=10000, canonical=False)
    a = c.encode(
        {
            "schema_version": "deployment-prepare-expansion-record-v1",
            "scope": "topology_only",
            "base_compose_sha256": c.digest(base_compose_bytes),
            "base_service_ids_sha256": c.digest(base_service_ids_bytes),
            "recipe_sha256": rh,
            "instance_sha256": ih,
            "topology_sha256": c.digest(t),
            "exchange_sha256": c.digest(e),
            "pins_sha256": c.digest(p),
            "expanded_compose_sha256": c.digest(x),
            "expanded_compose_size_bytes": len(x),
        }
    )
    return c.PrepareSourceArtifacts(t, e, p, x, a)
