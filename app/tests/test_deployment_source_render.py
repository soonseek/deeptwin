import hashlib
import json

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import (
    BASE_HASH,
    IDS_HASH,
    ROOT,
    inputs,
    module,
)


@pytest.mark.parametrize("capacity", [1, 16])
@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
@pytest.mark.parametrize("portable", [False, True])
def test_expansion_is_deterministic_and_preserves_base(capacity, platform, portable):
    render = module("render").render_prepare_sources
    raw = inputs(capacity=capacity, platform=platform, portable=portable)
    first = render(*raw)
    assert first == render(*raw)
    t, e, p, x, a = [
        json.loads(getattr(first, field))
        for field in (
            "topology_bytes",
            "exchange_bytes",
            "pins_bytes",
            "expanded_compose_bytes",
            "expansion_record_bytes",
        )
    ]
    base = json.loads(raw[0])
    assert x["services"]["control"]["cpus"] == 1.0
    for field in (
        "topology_bytes",
        "exchange_bytes",
        "pins_bytes",
        "expansion_record_bytes",
    ):
        assert canonical_json(json.loads(getattr(first, field))) == getattr(
            first, field
        )
    for name, service in base["services"].items():
        if name != "control":
            assert x["services"][name] == service
    for key, value in base.items():
        if key not in {"services", "volumes", "configs"}:
            assert x[key] == value
    for key in ("volumes", "configs"):
        for name, value in base[key].items():
            assert x[key][name] == value
    assert set(x["services"]) == set(base["services"]) | {
        "deployment-prepare-root-init"
    }
    control = x["services"]["control"]
    for key, value in base["services"]["control"].items():
        if key not in {"group_add", "volumes", "depends_on", "environment"}:
            assert control[key] == value
    assert control["group_add"][-capacity - 1 :] == ["21201"] + [
        str(23000 + n) for n in range(1, capacity + 1)
    ]
    assert len(t["slots"]) == capacity
    slot = t["slots"][-1]
    assert slot["uid"] == 22000 + capacity
    assert slot["socket_mount"]["mount_id"] == f"xs{capacity:02}"
    assert (
        slot["socket_mount"]["container_path"] == f"/run/deeptwin/ipc/xs{capacity:02}"
    )
    assert t["platform"] == platform
    assert e["outgoing"]["namespaces"] == ["cancelled", "requests"]
    assert p["topology_sha256"] == hashlib.sha256(first.topology_bytes).hexdigest()
    assert p["exchange_sha256"] == hashlib.sha256(first.exchange_bytes).hexdigest()
    assert a["pins_sha256"] == hashlib.sha256(first.pins_bytes).hexdigest()
    assert (
        a["expanded_compose_sha256"]
        == hashlib.sha256(first.expanded_compose_bytes).hexdigest()
    )
    init = x["services"]["deployment-prepare-root-init"]
    assert init["network_mode"] == "none"
    assert init["user"] == "0:0"
    assert init["cap_add"] == ["CHOWN", "FOWNER", "FSETID"]
    assert init["group_add"] == ["21201"] + [
        str(23000 + number) for number in range(1, capacity + 1)
    ]
    assert init["entrypoint"] == [
        "python",
        "-m",
        "app.operations.deployment_prepare_init",
    ]
    assert all(v["volume"] == {"nocopy": True} for v in init["volumes"])
    assert len(init["volumes"]) == capacity + 3
    assert hashlib.sha256(raw[0]).hexdigest() == BASE_HASH
    assert hashlib.sha256(raw[1]).hexdigest() == IDS_HASH


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_modified_input_bytes_deny(index):
    c, r = module("contracts"), module("render")
    raw = list(inputs())
    raw[index] += b" "
    with pytest.raises(c.DeploymentSourceError):
        r.render_prepare_sources(*raw)


def test_recipe_file_matches_fixed_canonical_release():
    raw = inputs()
    assert (
        ROOT / "deploy/security/deployment-prepare-recipe-v1.json"
    ).read_bytes() == raw[2]


def test_independent_instances_keep_common_template_and_recipe():
    r = module("render")
    first, second = inputs(), inputs(identity="3" * 32)
    assert first[:3] == second[:3]
    assert r.render_prepare_sources(*first) != r.render_prepare_sources(*second)


def test_render_has_no_external_effects(monkeypatch):
    import os
    import secrets
    import socket
    import subprocess
    import time

    raw, r = inputs(), module("render")

    def forbidden(*args, **kwargs):
        raise AssertionError("external effect during rendering")

    for owner, name in [
        (os, "urandom"),
        (secrets, "token_bytes"),
        (socket, "socket"),
        (subprocess, "Popen"),
        (time, "time"),
    ]:
        monkeypatch.setattr(owner, name, forbidden)
    assert r.render_prepare_sources(*raw).topology_bytes
