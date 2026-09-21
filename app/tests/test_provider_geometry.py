"""Geometry keeps the original transport identity and joins actual sources."""

import importlib
from hashlib import sha256

import pytest

from app.domain.refs import canonical_json
from app.tests.provider_source_fixture import case

from app.tests.deployment_source_fixture import inputs
from app.deployment.render import render_prepare_sources


def geometry_module():
    try:
        return importlib.import_module("app.deployment.provider_geometry")
    except ModuleNotFoundError:
        assert False, "Final provider geometry implementation is missing"


def test_geometry_preserves_original_sixteen_slot_identity():
    raw = inputs(capacity=16)
    original = render_prepare_sources(*raw)
    geometry = geometry_module().derive_provider_geometry(
        original_recipe_bytes=raw[2], original_instance_bytes=raw[3],
        original_topology_bytes=original.topology_bytes,
    ).as_dict()
    assert geometry["original_topology"] == {
        "sha256": sha256(original.topology_bytes).hexdigest(),
        "size_bytes": len(original.topology_bytes),
    }
    assert geometry["slots"][-1]["socket_mount"] == {
        "mount_id": "xs16", "volume_name": "dt-" + "1" * 32 + "-ipc-xs16",
        "container_path": "/run/deeptwin/ipc/xs16", "read_only": False,
        "purpose": "broker_pair",
    }


@pytest.mark.parametrize("capacity", [1, 16])
@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
@pytest.mark.parametrize("portable", [False, True])
def test_geometry_exact_bytes_detached_slots_and_source_join(capacity, platform, portable):
    kwargs, bundle, _ = case(capacity=capacity, platform=platform, portable=portable)
    m = geometry_module()
    sources = dict(original_recipe_bytes=kwargs["original_prepare_recipe_bytes"],
                   original_instance_bytes=kwargs["original_prepare_instance_bytes"],
                   original_topology_bytes=bundle[2][1])
    g = m.derive_provider_geometry(**sources)
    assert g.content_bytes == bundle[9][1]
    assert g.digest == sha256(bundle[9][1]).hexdigest()
    assert m.validate_provider_geometry_sources(g, **sources) is None
    detached = g.as_dict()
    detached["slots"][0]["socket_mount"]["read_only"] = True
    assert g.slot(1)["socket_mount"]["read_only"] is False
    projected = g.slot(capacity)
    projected["uid"] = 0
    assert g.slot(capacity)["uid"] == 22000 + capacity
    for number in (0, capacity + 1, True, 1.0, "1"):
        with pytest.raises(m.ProviderGeometryError, match="^invalid provider geometry$"):
            g.slot(number)
    with pytest.raises((AttributeError, TypeError)):
        g.content_bytes = b"{}"
    with pytest.raises(TypeError):
        m.ProviderGeometry()


def test_geometry_rejects_structurally_valid_alternate_sources_and_forged_values():
    import json
    kwargs, bundle, _ = case()
    m = geometry_module()
    g = m.parse_provider_geometry(bundle[9][1])
    for index, field, replacement in ((1, "topology_id", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
                                       (1, "slot_capacity", 16),
                                       (2, "topology_id", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")):
        value = json.loads(bundle[index][1]); value[field] = replacement
        source = {"original_recipe_bytes": bundle[0][1], "original_instance_bytes": bundle[1][1],
                  "original_topology_bytes": bundle[2][1]}
        source[("original_recipe_bytes", "original_instance_bytes", "original_topology_bytes")[index]] = canonical_json(value)
        with pytest.raises(m.ProviderGeometryError):
            m.validate_provider_geometry_sources(g, **source)
    hollow = object.__new__(m.ProviderGeometry)
    malformed = object.__new__(m.ProviderGeometry)
    object.__setattr__(malformed, "_content_bytes", b"{}")
    class Subclass(m.ProviderGeometry):
        pass
    subclass = object.__new__(Subclass)
    object.__setattr__(subclass, "_content_bytes", bundle[9][1])
    for forged in (hollow, malformed, subclass):
        for operation in (lambda: forged.content_bytes, lambda: forged.digest,
                          lambda: forged.as_dict(), lambda: forged.slot(1)):
            with pytest.raises(m.ProviderGeometryError):
                operation()


def test_slot_method_revalidates_receiver_even_when_projection_is_overridden():
    m = geometry_module()
    class Forged:
        def as_dict(self):
            return {"slots": [{"uid": 0}]}
    with pytest.raises(m.ProviderGeometryError):
        m.ProviderGeometry.slot(Forged(), 1)


@pytest.mark.parametrize("path,value", [
    (("instance_id",), "2" * 32), (("origin_profile", "digest"), "e" * 64),
    (("original_recipe", "sha256"), "e" * 64), (("original_recipe", "size_bytes"), 607),
    (("original_instance", "size_bytes"), 4097), (("original_topology", "size_bytes"), 65537),
    (("topology_revision",), True), (("platform",), "darwin/arm64"),
    (("control", "uid"), 0), (("slots", 0, "slot_number"), 2),
    (("slots", 0, "service_identity"), "ext-" + "2" * 32 + "-01"),
    (("slots", 0, "uid"), 22002), (("slots", 0, "pair_gid"), 23002),
    (("slots", 0, "socket_mount", "read_only"), 0),
    (("slots", 0, "socket_mount", "volume_name"), "dt-" + "2" * 32 + "-ipc-xs01"),
    (("slots", 0, "resource_budget", "memory_bytes"), 1), (("slots",), []),
])
def test_geometry_refuses_changes_to_original_identity_or_strict_types(path, value):
    import json
    _, bundle, _ = case(); document = json.loads(bundle[9][1]); target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(geometry_module().ProviderGeometryError):
        geometry_module().parse_provider_geometry(canonical_json(document))


def test_geometry_refuses_noncanonical_bounded_wire():
    _, bundle, _ = case(); raw = bundle[9][1]; m = geometry_module()
    for bad in (bytearray(raw), raw + b"\n", b"\xef\xbb\xbf" + raw, b"\xff", b"null",
                b'{"x":1,"x":1}', raw.replace(b'"topology_revision":1', b'"topology_revision":1.0'),
                raw.replace(b'"topology_revision":1', b'"topology_revision":1099511627777'),
                b"[" * 20 + b"0" + b"]" * 20, b" " * 65537):
        with pytest.raises(m.ProviderGeometryError, match="^invalid provider geometry$"):
            m.parse_provider_geometry(bad)
