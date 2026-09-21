"""Provider source output is an exact inert bundle and additive Compose artifact."""

import importlib
import json

import pytest

from app.tests.provider_source_fixture import case, digest, encode
from app.deployment.contracts import DeploymentSourceError


def renderer():
    try:
        return importlib.import_module("app.deployment.provider_source_render")
    except ModuleNotFoundError:
        assert False, "Concrete provider source renderer is missing"


def test_renderer_has_required_keyword_interface():
    import inspect
    signature = inspect.signature(renderer().render_provider_sources)
    assert tuple(signature.parameters) == (
        "base_compose_bytes", "base_service_ids_bytes",
        "original_prepare_recipe_bytes", "original_prepare_instance_bytes",
        "original_receipt_recipe_bytes", "original_receipt_instance_bytes",
        "original_trust_bytes", "provider_recipe_bytes", "provider_instance_bytes",
        "provider_trust_bytes",
    )
    assert all(p.kind == p.KEYWORD_ONLY and p.default == p.empty
               for p in signature.parameters.values())


@pytest.mark.parametrize("capacity", [1, 16])
@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
@pytest.mark.parametrize("portable", [False, True])
def test_exact_independent_bundle_and_append_only_compose(capacity, platform, portable):
    kwargs, bundle, old = case(capacity=capacity, platform=platform, portable=portable)
    result = renderer().render_provider_sources(**kwargs)
    assert result.bundle_files == bundle
    assert result.original_artifacts == old
    assert result == renderer().render_provider_sources(**kwargs)
    for field, index in (("geometry_bytes", 9), ("exchange_bytes", 13), ("ingress_bytes", 14),
                         ("consumption_exchange_bytes", 15), ("context_bytes", 16), ("pins_bytes", 17)):
        assert getattr(result, field) == bundle[index][1]
    before = json.loads(old.expanded_compose_bytes)
    after = json.loads(result.expanded_compose_bytes)
    initializer = after["services"].pop("provider-source-root-init")
    assert initializer["image"] == json.loads(kwargs["provider_instance_bytes"])["initializer_image"]
    assert initializer["entrypoint"] == ["python", "-m", "app.operations.deployment_provider_source_init"]
    assert initializer["cpus"] == 0.25
    assert initializer["depends_on"] == {name: {"condition": "service_completed_successfully"} for name in (
        "deployment-prepare-root-init", "deployment-receipt-public-init")}
    new_names = ("provider-stage-sources", "provider-deployment-outbox",
                 "provider-deployment-receipts", "provider-deployment-consumed")
    mounts = after["services"]["control"]["volumes"][-4:]
    assert mounts == [{"type": "volume", "source": name, "target": "/run/deeptwin/" + name,
                       "read_only": ro, "volume": {"nocopy": True}} for name, ro in zip(new_names, (True, False, True, False))]
    assert initializer["volumes"][:4] == [{**mount, "read_only": False} for mount in mounts]
    assert initializer["volumes"][4:] == [{"type": "volume", "source": name, "target": path,
                                          "read_only": True, "volume": {"nocopy": True}} for name, path in (
        ("extension-topology-public", "/run/deeptwin/extension-topology"),
        ("deployment-exchange-public", "/run/deeptwin/deployment-exchange"),
        ("deployment-verify-public", "/run/deeptwin/deployment-verify-public"),
        ("deployment-receipt-ingress-public", "/run/deeptwin/deployment-receipt-ingress"),
        ("deployment-consumption-exchange-public", "/run/deeptwin/deployment-consumption-exchange"))]
    identity = json.loads(bundle[1][1])["origin_profile"]["instance_id"]
    expected_configs = []
    for suffix, filename in (("original-prepare-instance", "original-prepare-instance.json"),
                             ("original-receipt-instance", "original-receipt-instance.json"),
                             ("original-trust", "original-trust-set.json"), ("instance", "provider-instance.json"),
                             ("trust", "provider-trust-set.json"), ("pins", "provider-source-pins.json")):
        name = f"dt-{identity}-provider-source-{suffix}"
        assert after["configs"].pop(name) == {"external": True, "name": name}
        expected_configs.append({"source": name, "target": "/run/deeptwin/provider-source-init-input/" + filename,
                                 "uid": "0", "gid": "0", "mode": 288})
    assert initializer["configs"] == expected_configs
    assert initializer == {
        "image": json.loads(kwargs["provider_instance_bytes"])["initializer_image"],
        "entrypoint": ["python", "-m", "app.operations.deployment_provider_source_init"],
        "command": [], "user": "0:0", "group_add": ["21201"], "restart": "no", "init": True,
        "privileged": False, "read_only": True, "network_mode": "none", "cap_drop": ["ALL"],
        "cap_add": ["CHOWN", "FOWNER", "FSETID"], "security_opt": ["no-new-privileges:true"],
        "tty": False, "stdin_open": False, "pids_limit": 32, "mem_limit": "64m", "cpus": 0.25,
        "ulimits": {"nofile": {"soft": 256, "hard": 256}}, "configs": expected_configs,
        "volumes": initializer["volumes"],
        "depends_on": {name: {"condition": "service_completed_successfully"} for name in (
            "deployment-prepare-root-init", "deployment-receipt-public-init")},
    }
    for name in new_names:
        assert after["volumes"].pop(name) == {"name": f"dt-{identity}-{name}"}
    del after["services"]["control"]["volumes"][-4:]
    assert after["services"]["control"]["environment"].pop("DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256") == digest(bundle[16][1])
    assert after["services"]["control"]["depends_on"].pop("provider-source-root-init") == {"condition": "service_completed_successfully"}
    assert after == before
    record = json.loads(result.expansion_record_bytes)
    assert record == {
        "schema_version": "deployment-provider-source-expansion-record-v1", "scope": "provider_sources_only",
        "renderer_id": "deeptwin-provider-source-expand-v1", "initializer_id": "deeptwin-provider-source-init-v1",
        "original_expansion_sha256": digest(old.expanded_compose_bytes),
        "original_expansion_size_bytes": len(old.expanded_compose_bytes),
        "original_expansion_record_sha256": digest(old.expansion_record_bytes),
        "provider_recipe_sha256": digest(bundle[10][1]), "provider_instance_sha256": digest(bundle[11][1]),
        "geometry_sha256": digest(bundle[9][1]), "context_sha256": digest(bundle[16][1]),
        "pins_sha256": digest(bundle[17][1]), "initializer_image": initializer["image"],
        "expanded_compose_sha256": digest(result.expanded_compose_bytes),
        "expanded_compose_size_bytes": len(result.expanded_compose_bytes),
    }


@pytest.mark.parametrize("field", ["context_id", "exchange_id", "ingress_id", "consumption_exchange_id"])
def test_renderer_rejects_original_identifier_reuse(field):
    kwargs, bundle, _ = case()
    original_ids = (json.loads(bundle[1][1])["topology_id"], json.loads(bundle[1][1])["exchange_id"],
                    json.loads(bundle[5][1])["receipt_ingress_id"], json.loads(bundle[5][1])["consumption_exchange_id"])
    for identity in original_ids:
        instance = json.loads(kwargs["provider_instance_bytes"]); instance[field] = identity
        with pytest.raises(DeploymentSourceError, match="^deployment_source_invalid$"):
            renderer().render_provider_sources(**(kwargs | {"provider_instance_bytes": encode(instance)}))


def test_fresh_imports_refuse_runtime_source_opening_and_initializer_dependencies():
    import os
    import subprocess
    import sys
    program = r'''
import builtins, sys
original = builtins.__import__
forbidden = ("app.runtime", "app.api", "app.services", "app.workers", "app.adapters",
             "app.deployment.sources", "app.deployment.files", "app.deployment.source_common",
             "app.deployment.public_init_files", "app.deployment.receipt_sources",
             "app.operations.deployment_")
def guarded(name, *args, **kwargs):
    if name.startswith(forbidden):
        raise AssertionError("unexpected authority import: " + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import app.deployment.provider_geometry
import app.deployment.provider_source_contracts
import app.deployment.provider_source_schema_exports
import app.deployment.provider_source_render
assert not [name for name in sys.modules if name.startswith(forbidden)]
print("pure imports only")
'''
    result = subprocess.run([sys.executable, "-B", "-c", program], capture_output=True, text=True,
                            env={**os.environ, "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"})
    assert result.returncode == 0, result.stderr
    assert result.stdout == "pure imports only\n"


def test_pure_render_validation_and_projection_do_not_open_files_or_start_effects(monkeypatch):
    import builtins
    import io
    import os
    import socket
    import subprocess
    from app.deployment import provider_geometry as geometry
    from app.deployment import provider_source_contracts as contracts
    from app.deployment.provider_source_schema_exports import exported_schemas
    kwargs, expected, _ = case()
    render = renderer().render_provider_sources
    def forbidden(*args, **kw):
        raise AssertionError("pure source producer attempted I/O")
    for owner, name in ((builtins, "open"), (io, "open"), (os, "open"), (socket, "socket"), (subprocess, "Popen")):
        monkeypatch.setattr(owner, name, forbidden)
    result = render(**kwargs)
    assert result.bundle_files == expected
    assert contracts.validate_provider_source_bundle(expected) is None
    parsed = geometry.parse_provider_geometry(result.geometry_bytes)
    assert parsed.slot(1)["uid"] == 22001
    assert parsed.digest == digest(expected[9][1])
    assert parsed.content_bytes == expected[9][1]
    assert len(exported_schemas()) == 10
    assert contracts.parse_provider_expansion_record(result.expansion_record_bytes)["scope"] == "provider_sources_only"


@pytest.mark.parametrize("input_name", ["base_compose_bytes", "base_service_ids_bytes", "original_prepare_recipe_bytes",
    "original_prepare_instance_bytes", "original_receipt_recipe_bytes", "original_receipt_instance_bytes", "original_trust_bytes",
    "provider_recipe_bytes", "provider_instance_bytes", "provider_trust_bytes"])
def test_renderer_rejects_missing_nonbytes_and_oversized_inputs(input_name):
    kwargs, _, _ = case()
    for replacement in (None, {}, bytearray(kwargs[input_name]), b" " * 2097153):
        with pytest.raises(DeploymentSourceError, match="^deployment_source_invalid$"):
            renderer().render_provider_sources(**(kwargs | {input_name: replacement}))


def test_original_source_instance_profile_platform_capacity_changes_refuse_stale_new_pins():
    kwargs, _, _ = case()
    for options in ({"portable": True}, {"platform": "linux/arm64"}, {"capacity": 16}, {"identity": "2" * 32}):
        alternate, _, _ = case(**options)
        mixed = kwargs | {key: value for key, value in alternate.items() if key.startswith("original_")}
        with pytest.raises(DeploymentSourceError):
            renderer().render_provider_sources(**mixed)


def test_all_new_ids_must_be_mutually_distinct():
    kwargs, _, _ = case(); original = json.loads(kwargs["provider_instance_bytes"])
    for field in ("exchange_id", "ingress_id", "consumption_exchange_id"):
        instance = original | {field: original["context_id"]}
        with pytest.raises(DeploymentSourceError):
            renderer().render_provider_sources(**(kwargs | {"provider_instance_bytes": encode(instance)}))


def test_record_parser_enforces_closed_bounds_types_and_image_grammar():
    from app.deployment.provider_source_contracts import parse_provider_expansion_record
    kwargs, _, _ = case(); record = renderer().render_provider_sources(**kwargs).expansion_record_bytes
    value = json.loads(record)
    assert parse_provider_expansion_record(record) == value
    for field, bad in (("scope", "qualified"), ("original_expansion_size_bytes", True),
                       ("expanded_compose_size_bytes", 1048577), ("initializer_image", "registry/repo@sha256:" + "a" * 64),
                       ("provider_recipe_sha256", "e" * 64), ("context_sha256", "E" * 64), ("unknown", 1)):
        with pytest.raises(DeploymentSourceError):
            parse_provider_expansion_record(encode(value | {field: bad}))
    for raw in (record + b"\n", b"\xef\xbb\xbf" + record, bytearray(record), b" " * 8193):
        with pytest.raises(DeploymentSourceError):
            parse_provider_expansion_record(raw)


@pytest.mark.parametrize("collision", ["service", "volume_key", "volume_name", "config_key", "config_name",
                                      "target", "target_parent", "target_child", "config_target", "environment", "dependency", "group"])
def test_additive_expansion_refuses_every_collision_boundary(collision):
    # Exercise the pure expansion guard using a detached baseline, never a public override.
    kwargs, bundle, old = case(); baseline = json.loads(old.expanded_compose_bytes)
    identity = json.loads(bundle[1][1])["origin_profile"]["instance_id"]
    name = f"dt-{identity}-provider-source-instance"
    control = baseline["services"]["control"]
    if collision == "service":
        baseline["services"]["provider-source-root-init"] = {}
    elif collision == "volume_key":
        baseline["volumes"]["provider-stage-sources"] = {}
    elif collision == "volume_name":
        baseline["volumes"]["alias"] = {"name": f"dt-{identity}-provider-stage-sources"}
    elif collision == "config_key":
        baseline["configs"][name] = {}
    elif collision == "config_name":
        baseline["configs"]["alias"] = {"name": name}
    elif collision in ("target", "target_parent", "target_child"):
        target = {"target": "/run/deeptwin/provider-stage-sources", "target_parent": "/run/deeptwin",
                  "target_child": "/run/deeptwin/provider-stage-sources/documents"}[collision]
        control["volumes"].append({"target": target})
    elif collision == "config_target":
        control.setdefault("configs", []).append({"target": "/run/deeptwin/provider-source-init-input/extra.json"})
    elif collision == "environment":
        control["environment"]["DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256"] = "e" * 64
    elif collision == "dependency":
        control["depends_on"]["provider-source-root-init"] = {}
    else:
        control["group_add"].append("21201")
    with pytest.raises(DeploymentSourceError):
        renderer()._expand(json.dumps(baseline).encode(), instance_id=identity,
                           initializer_image=json.loads(kwargs["provider_instance_bytes"])["initializer_image"],
                           context_sha256=digest(bundle[16][1]))
