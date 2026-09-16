"""The pure receipt producer extends accepted prepare artifacts without authority."""

import hashlib
import json
import os
import socket
import subprocess
import sys
from base64 import urlsafe_b64encode

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import ROOT, inputs, module, profile


def b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def trust(origin, *, key_count=1):
    return {
        "schema": "deployment-public-trust-set-v1",
        "domain": "deeptwin-deployment-public-trust-set-v1",
        "version": 1,
        "instance_id": origin.instance_id,
        "origin_profile_digest": b64(bytes.fromhex(origin.digest)),
        "keys": [
            {
                "key_id": f"{number:08x}-0000-4000-8000-{number:012x}",
                "algorithm": "ed25519",
                "public_key": b64(bytes([number]) * 32),
                "trust_class": "instance_operator",
                "adapter_ids": ["deeptwin-stage-operator-v1"],
            }
            for number in range(1, key_count + 1)
        ],
        "adapters": [
            {
                "operator_adapter": "deeptwin-stage-operator-v1",
                "operator_version": "1.0.0",
                "deployment_profile_id": origin.deployment_profile_id,
            }
        ],
    }


def receipt_inputs(**kwargs):
    key_count = kwargs.pop("key_count", 1)
    raw = inputs(**kwargs)
    origin = profile(kwargs.get("portable", False), kwargs.get("identity", "1" * 32))
    source_contracts = module("receipt_source_contracts")
    trust_bytes = canonical_json(trust(origin, key_count=key_count))
    value = {
        "schema_version": "deployment-receipt-instance-v1",
        "prepare_instance_sha256": hashlib.sha256(raw[3]).hexdigest(),
        "trust_set_sha256": hashlib.sha256(trust_bytes).hexdigest(),
        "receipt_ingress_id": "33333333-3333-4333-8333-333333333333",
        "consumption_exchange_id": "44444444-4444-4444-8444-444444444444",
    }
    return (
        *raw,
        source_contracts.RECEIPT_RECIPE_BYTES,
        canonical_json(value),
        trust_bytes,
    )


@pytest.mark.parametrize("capacity", [1, 16])
@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
@pytest.mark.parametrize("portable", [False, True])
def test_renderer_is_deterministic_and_keeps_prepare_outputs_exact(
    capacity, platform, portable
):
    raw = receipt_inputs(capacity=capacity, platform=platform, portable=portable)
    old = module("render").render_prepare_sources(*raw[:4])
    render = module("receipt_render").render_receipt_sources
    result = render(*raw)
    assert result == render(*raw)
    assert result.prepare_artifacts == old
    assert result.trust_bytes == raw[6]
    base = json.loads(old.expanded_compose_bytes)
    expanded = json.loads(result.expanded_compose_bytes)
    for name, service in base["services"].items():
        if name != "control":
            assert expanded["services"][name] == service
    for key in ("networks",):
        assert expanded[key] == base[key]
    for key in ("volumes", "configs"):
        for name, value in base[key].items():
            assert expanded[key][name] == value


def test_exact_control_append_only_topology_and_public_initializer():
    raw = receipt_inputs()
    old = module("render").render_prepare_sources(*raw[:4])
    output = module("receipt_render").render_receipt_sources(*raw)
    before = json.loads(old.expanded_compose_bytes)
    after = json.loads(output.expanded_compose_bytes)
    pins = json.loads(output.pins_bytes)
    old_control, control = before["services"]["control"], after["services"]["control"]
    for key, value in old_control.items():
        if key not in {"volumes", "environment", "depends_on"}:
            assert control[key] == value
    assert control["group_add"] == old_control["group_add"]
    assert control["volumes"][: len(old_control["volumes"])] == old_control["volumes"]
    assert all(
        control["environment"][key] == value
        for key, value in old_control["environment"].items()
    )
    assert len(control["environment"]) == len(old_control["environment"]) + 5
    assert all(
        control["depends_on"][key] == value
        for key, value in old_control["depends_on"].items()
    )
    assert len(control["depends_on"]) == len(old_control["depends_on"]) + 1
    logical = [
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
    ]
    expected_mounts = [
        {
            "type": "volume",
            "source": name,
            "target": target,
            "read_only": read_only,
            "volume": {"nocopy": True},
        }
        for name, target, read_only in logical
    ]
    assert control["volumes"][-5:] == expected_mounts
    assert control["depends_on"]["deployment-receipt-public-init"] == {
        "condition": "service_completed_successfully"
    }
    assert {
        key: control["environment"][key]
        for key in control["environment"]
        if "RECEIPT" in key or "TRUST" in key or "CONSUMPTION" in key
    } == {
        "DEEPTWIN_RECEIPT_RECIPE_SHA256": pins["receipt_recipe_sha256"],
        "DEEPTWIN_RECEIPT_INSTANCE_SHA256": pins["receipt_instance_sha256"],
        "DEEPTWIN_DEPLOYMENT_TRUST_SHA256": pins["trust_sha256"],
        "DEEPTWIN_RECEIPT_INGRESS_SHA256": pins["ingress_sha256"],
        "DEEPTWIN_CONSUMPTION_EXCHANGE_SHA256": pins["consumption_exchange_sha256"],
    }
    assert set(after["services"]) == set(before["services"]) | {
        "deployment-receipt-public-init"
    }
    initializer = after["services"]["deployment-receipt-public-init"]
    expected_initializer = {
        "image": "${DEPLOYMENT_RECEIPT_PUBLIC_INIT_IMAGE:?exact @sha256 image required}",
        "entrypoint": ["python", "-m", "app.operations.deployment_receipt_public_init"],
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
        "volumes": [{**mount, "read_only": False} for mount in expected_mounts],
        "configs": [
            {
                "source": "dt-11111111111111111111111111111111-receipt-prepare-instance",
                "target": "/run/deeptwin/receipt-init-input/prepare-instance.json",
                "uid": "0",
                "gid": "0",
                "mode": 0o440,
            },
            {
                "source": "dt-11111111111111111111111111111111-receipt-instance",
                "target": "/run/deeptwin/receipt-init-input/receipt-instance.json",
                "uid": "0",
                "gid": "0",
                "mode": 0o440,
            },
            {
                "source": "dt-11111111111111111111111111111111-receipt-trust",
                "target": "/run/deeptwin/receipt-init-input/trust-set.json",
                "uid": "0",
                "gid": "0",
                "mode": 0o440,
            },
            {
                "source": "dt-11111111111111111111111111111111-receipt-pins",
                "target": "/run/deeptwin/receipt-init-input/receipt-source-pins.json",
                "uid": "0",
                "gid": "0",
                "mode": 0o440,
            },
        ],
    }
    assert initializer == expected_initializer
    assert "deployment-receipt-job" not in after["services"]


def test_exact_volume_and_config_names_are_external_and_collision_free():
    output = module("receipt_render").render_receipt_sources(*receipt_inputs())
    expanded = json.loads(output.expanded_compose_bytes)
    instance = "1" * 32
    logical = [
        "deployment-verify-public",
        "deployment-receipt-ingress-public",
        "deployment-consumption-exchange-public",
        "deployment-receipts",
        "deployment-consumed",
    ]
    assert {name: expanded["volumes"][name] for name in logical} == {
        name: {"name": f"dt-{instance}-{name}"} for name in logical
    }
    old = json.loads(
        module("render")
        .render_prepare_sources(*receipt_inputs()[:4])
        .expanded_compose_bytes
    )
    assert set(expanded["volumes"]) == set(old["volumes"]) | set(logical)
    config_names = [
        f"dt-{instance}-receipt-prepare-instance",
        f"dt-{instance}-receipt-instance",
        f"dt-{instance}-receipt-trust",
        f"dt-{instance}-receipt-pins",
    ]
    assert {name: expanded["configs"][name] for name in config_names} == {
        name: {"external": True, "name": name} for name in config_names
    }
    assert set(expanded["configs"]) == set(old["configs"]) | set(config_names)


def test_complete_graph_hashes_actual_bytes_and_has_no_back_reference_cycles():
    raw = receipt_inputs(key_count=8)
    output = module("receipt_render").render_receipt_sources(*raw)
    old = output.prepare_artifacts
    j = json.loads(output.ingress_bytes)
    k = json.loads(output.consumption_exchange_bytes)
    pins = json.loads(output.pins_bytes)
    record = json.loads(output.expansion_record_bytes)
    assert set(pins) == {
        "schema_version",
        "instance_id",
        "origin_profile_digest",
        "prepare_recipe_sha256",
        "prepare_instance_sha256",
        "prepare_exchange_sha256",
        "receipt_recipe_sha256",
        "receipt_instance_sha256",
        "trust_sha256",
        "ingress_sha256",
        "consumption_exchange_sha256",
    }
    expected_pins = {
        "prepare_recipe_sha256": hashlib.sha256(raw[2]).hexdigest(),
        "prepare_instance_sha256": hashlib.sha256(raw[3]).hexdigest(),
        "prepare_exchange_sha256": hashlib.sha256(old.exchange_bytes).hexdigest(),
        "receipt_recipe_sha256": hashlib.sha256(raw[4]).hexdigest(),
        "receipt_instance_sha256": hashlib.sha256(raw[5]).hexdigest(),
        "trust_sha256": hashlib.sha256(raw[6]).hexdigest(),
        "ingress_sha256": hashlib.sha256(output.ingress_bytes).hexdigest(),
        "consumption_exchange_sha256": hashlib.sha256(
            output.consumption_exchange_bytes
        ).hexdigest(),
    }
    for name, digest in expected_pins.items():
        assert pins[name] == digest
    assert j["outgoing_exchange_digest"] == expected_pins["prepare_exchange_sha256"]
    assert k["receipt_ingress_digest"] == expected_pins["ingress_sha256"]
    assert "ingress_sha256" not in j
    assert "consumption_exchange_sha256" not in k
    assert "pins_sha256" not in pins
    assert (
        record["expanded_compose_sha256"]
        == hashlib.sha256(output.expanded_compose_bytes).hexdigest()
    )
    assert record["expanded_compose_size_bytes"] == len(output.expanded_compose_bytes)
    assert record["pins_sha256"] == hashlib.sha256(output.pins_bytes).hexdigest()
    assert (
        record["prepare_expansion_sha256"]
        == hashlib.sha256(old.expanded_compose_bytes).hexdigest()
    )
    assert (
        record["prepare_record_sha256"]
        == hashlib.sha256(old.expansion_record_bytes).hexdigest()
    )
    expected_record_hashes = {
        "base_compose_sha256": hashlib.sha256(raw[0]).hexdigest(),
        "base_service_ids_sha256": hashlib.sha256(raw[1]).hexdigest(),
        "prepare_recipe_sha256": hashlib.sha256(raw[2]).hexdigest(),
        "prepare_instance_sha256": hashlib.sha256(raw[3]).hexdigest(),
        "prepare_topology_sha256": hashlib.sha256(old.topology_bytes).hexdigest(),
        "prepare_exchange_sha256": hashlib.sha256(old.exchange_bytes).hexdigest(),
        "prepare_pins_sha256": hashlib.sha256(old.pins_bytes).hexdigest(),
        "prepare_expansion_sha256": hashlib.sha256(
            old.expanded_compose_bytes
        ).hexdigest(),
        "prepare_record_sha256": hashlib.sha256(old.expansion_record_bytes).hexdigest(),
        "receipt_recipe_sha256": hashlib.sha256(raw[4]).hexdigest(),
        "receipt_instance_sha256": hashlib.sha256(raw[5]).hexdigest(),
        "trust_sha256": hashlib.sha256(raw[6]).hexdigest(),
        "ingress_sha256": hashlib.sha256(output.ingress_bytes).hexdigest(),
        "consumption_exchange_sha256": hashlib.sha256(
            output.consumption_exchange_bytes
        ).hexdigest(),
        "pins_sha256": hashlib.sha256(output.pins_bytes).hexdigest(),
        "expanded_compose_sha256": hashlib.sha256(
            output.expanded_compose_bytes
        ).hexdigest(),
    }
    for field, digest in expected_record_hashes.items():
        assert record[field] == digest
    assert set(record) == {
        "schema_version",
        "scope",
        "base_compose_sha256",
        "base_service_ids_sha256",
        "prepare_recipe_sha256",
        "prepare_instance_sha256",
        "prepare_topology_sha256",
        "prepare_exchange_sha256",
        "prepare_pins_sha256",
        "prepare_expansion_sha256",
        "prepare_record_sha256",
        "receipt_recipe_sha256",
        "receipt_instance_sha256",
        "trust_sha256",
        "ingress_sha256",
        "consumption_exchange_sha256",
        "pins_sha256",
        "expanded_compose_sha256",
        "expanded_compose_size_bytes",
    }
    assert "expansion_record_sha256" not in record
    source_contracts = module("receipt_source_contracts")
    assert (
        source_contracts.parse_ingress(
            output.ingress_bytes,
            profile=profile(),
            receipt_recipe_sha256=expected_pins["receipt_recipe_sha256"],
            receipt_instance_sha256=expected_pins["receipt_instance_sha256"],
        )
        == j
    )
    assert (
        source_contracts.parse_consumption_exchange(
            output.consumption_exchange_bytes,
            profile=profile(),
            receipt_recipe_sha256=expected_pins["receipt_recipe_sha256"],
            receipt_instance_sha256=expected_pins["receipt_instance_sha256"],
        )
        == k
    )


@pytest.mark.parametrize(
    "index,mutation",
    [
        (0, lambda raw: raw + b" "),
        (1, lambda raw: raw + b" "),
        (2, lambda raw: raw + b" "),
        (3, lambda raw: raw + b" "),
        (4, lambda raw: raw + b" "),
        (5, lambda raw: raw + b" "),
        (6, lambda raw: raw + b" "),
    ],
)
def test_modified_source_bytes_fail_closed(index, mutation):
    raw = list(receipt_inputs())
    raw[index] = mutation(raw[index])
    contracts = module("contracts")
    with pytest.raises(contracts.DeploymentSourceError):
        module("receipt_render").render_receipt_sources(*raw)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("prepare_instance_sha256", "9" * 64),
        ("trust_set_sha256", "9" * 64),
        ("receipt_ingress_id", "11111111-1111-4111-8111-111111111111"),
        ("receipt_ingress_id", "22222222-2222-4222-8222-222222222222"),
        ("consumption_exchange_id", "11111111-1111-4111-8111-111111111111"),
        ("consumption_exchange_id", "33333333-3333-4333-8333-333333333333"),
    ],
)
def test_renderer_rejects_complete_input_relationship_mutations(field, bad):
    raw = list(receipt_inputs())
    value = json.loads(raw[5])
    value[field] = bad
    raw[5] = canonical_json(value)
    with pytest.raises(module("contracts").DeploymentSourceError):
        module("receipt_render").render_receipt_sources(*raw)


@pytest.mark.parametrize("mutation", ["profile", "adapter", "key_order", "key_shape"])
def test_renderer_rejects_wrong_trust_profile_adapter_and_key_list(mutation):
    raw = list(receipt_inputs(key_count=2))
    value = json.loads(raw[6])
    if mutation == "profile":
        value["instance_id"] = "9" * 32
    elif mutation == "adapter":
        value["adapters"][0]["operator_version"] = "2.0.0"
    elif mutation == "key_order":
        value["keys"].reverse()
    else:
        value["keys"][0]["adapter_ids"] = []
    raw[6] = canonical_json(value)
    receipt_instance = json.loads(raw[5])
    receipt_instance["trust_set_sha256"] = hashlib.sha256(raw[6]).hexdigest()
    raw[5] = canonical_json(receipt_instance)
    with pytest.raises(module("contracts").DeploymentSourceError):
        module("receipt_render").render_receipt_sources(*raw)


def test_renderer_has_no_filesystem_environment_socket_process_or_random_authority(
    monkeypatch,
):
    raw = receipt_inputs()

    def forbidden(*args, **kwargs):
        raise AssertionError("external authority used by pure renderer")

    for owner, name in (
        (os, "getenv"),
        (os, "urandom"),
        (socket, "socket"),
        (subprocess, "Popen"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    assert module("receipt_render").render_receipt_sources(*raw).pins_bytes


def test_fresh_process_import_and_behavior_do_not_load_nacl_or_observe_sources():
    code = r"""
import builtins, os, socket, sqlite3, sys
real_open = builtins.open
def guarded_open(path, *args, **kwargs):
    if str(path).startswith(("/run/", "/var/lib/")):
        raise AssertionError("live source access")
    return real_open(path, *args, **kwargs)
builtins.open = guarded_open
os.getenv = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("environment authority"))
socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("socket authority"))
sqlite3.connect = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("database authority"))
from app.tests.test_deployment_receipt_source_render import receipt_inputs
from app.deployment.receipt_render import render_receipt_sources
result = render_receipt_sources(*receipt_inputs())
assert result.pins_bytes and "nacl" not in sys.modules
"""
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_expanded_compose_preserves_finite_cpu_fraction_exception():
    output = module("receipt_render").render_receipt_sources(*receipt_inputs())
    expanded = json.loads(output.expanded_compose_bytes)
    assert expanded["services"]["control"]["cpus"] == 1.0
    assert expanded["services"]["deployment-receipt-public-init"]["cpus"] == 0.25


def test_prepare_recipe_remains_the_accepted_606_byte_artifact():
    raw = receipt_inputs()
    assert len(raw[2]) == 606
    assert hashlib.sha256(raw[2]).hexdigest() == (
        "03490ee7c676a0c78915fdef3ec48c52d6b88838ad71bce001ad2fe72f5e67b7"
    )
