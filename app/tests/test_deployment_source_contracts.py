import json
from copy import deepcopy

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import (
    artifacts,
    instance,
    module,
    profile,
    recipe,
)


@pytest.mark.parametrize("capacity", [1, 16])
@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
@pytest.mark.parametrize("portable", [False, True])
def test_exact_instance_supported(capacity, platform, portable):
    c = module("contracts")
    value = instance(capacity, platform, portable)
    assert c.parse_instance(canonical_json(value)) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("slot_capacity", True),
        ("slot_capacity", 0),
        ("slot_capacity", 17),
        ("platform", "darwin/arm64"),
        ("extra", 1),
        ("topology_id", "00000000-0000-0000-0000-000000000000"),
        ("topology_id", "22222222-2222-4222-8222-222222222222"),
    ],
)
def test_invalid_instance_denied(field, value):
    c = module("contracts")
    data = instance()
    data[field] = value
    with pytest.raises(c.DeploymentSourceError, match="^deployment_source_invalid$"):
        c.parse_instance(canonical_json(data))


@pytest.mark.parametrize(
    "raw", [b"{} ", b'{"x":1,"x":1}', b'{"x":1.0}', b"[]", b"[" * 2000, b" " * 4097]
)
def test_bounded_canonical_parser(raw):
    c = module("contracts")
    with pytest.raises(c.DeploymentSourceError):
        c.parse_instance(raw)


def test_recipe_is_exact_release_profile():
    c = module("contracts")
    assert c.parse_recipe(canonical_json(recipe())) == recipe()
    for path in [("slot_budget", "cpu_millicores"), ("base_compose", "sha256")]:
        value = deepcopy(recipe())
        value[path[0]][path[1]] = 1
        with pytest.raises(c.DeploymentSourceError):
            c.parse_recipe(canonical_json(value))
    value = recipe()
    value["slot_capacity_max"] = 16.0
    with pytest.raises(c.DeploymentSourceError):
        c.parse_recipe(json.dumps(value).encode())


@pytest.mark.parametrize(
    "target",
    [
        "uid",
        "pair_gid",
        "channel_id",
        "socket_name",
        "resource_budget",
        "socket_mount",
        "extra",
    ],
)
def test_topology_derived_values_cannot_be_rewritten(target):
    c = module("contracts")
    raw = artifacts().topology_bytes
    value = json.loads(raw)
    value["slots"][0][target] = "changed"
    with pytest.raises(c.DeploymentSourceError):
        c.parse_topology(
            canonical_json(value),
            profile=profile(),
            recipe_sha256=c.digest(canonical_json(recipe())),
            platform="linux/amd64",
        )


def test_domain_documents_deny_nested_floats_and_depth_before_encoding():
    c = module("contracts")
    for value in [{"nested": {"cpu": 1.0}}, {"nested": [[[[[[1]]]]]]}]:
        with pytest.raises(c.DeploymentSourceError):
            c.parse(json.dumps(value).encode(), cap=4096, depth=4, items=128)
