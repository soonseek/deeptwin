"""Closed receipt-source contracts remain inert and independently parseable."""

import hashlib
import json
from copy import deepcopy

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import ROOT, profile


def implementation():
    from app.tests.deployment_source_fixture import module

    return module("receipt_source_contracts")


def receipt_instance():
    return {
        "schema_version": "deployment-receipt-instance-v1",
        "prepare_instance_sha256": "1" * 64,
        "trust_set_sha256": "2" * 64,
        "receipt_ingress_id": "33333333-3333-4333-8333-333333333333",
        "consumption_exchange_id": "44444444-4444-4444-8444-444444444444",
    }


def ingress(origin=None):
    origin = origin or profile()
    return {
        "schema_version": "deployment-receipt-ingress-v1",
        "ingress_id": "33333333-3333-4333-8333-333333333333",
        "revision": 1,
        "instance_id": origin.instance_id,
        "origin_profile_digest": origin.digest,
        "prepare_recipe_digest": "5" * 64,
        "prepare_instance_digest": "1" * 64,
        "outgoing_exchange_digest": "6" * 64,
        "receipt_recipe_digest": implementation().RECEIPT_RECIPE_SHA256,
        "receipt_instance_digest": "7" * 64,
        "trust_set_digest": "2" * 64,
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
            "volume_name": f"dt-{origin.instance_id}-deployment-receipts",
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


def consumption(origin=None):
    origin = origin or profile()
    return {
        "schema_version": "deployment-consumption-exchange-v1",
        "exchange_id": "44444444-4444-4444-8444-444444444444",
        "revision": 1,
        "instance_id": origin.instance_id,
        "origin_profile_digest": origin.digest,
        "outgoing_exchange_digest": "6" * 64,
        "receipt_recipe_digest": implementation().RECEIPT_RECIPE_SHA256,
        "receipt_instance_digest": "7" * 64,
        "trust_set_digest": "2" * 64,
        "receipt_ingress_digest": "8" * 64,
        "control": {"service_identity": "control", "uid": 20102, "gid": 20102},
        "reader": {
            "service_identity": "deployment-receipt-job",
            "uid": 20113,
            "gid": 20113,
            "pair_gid": 21201,
        },
        "outgoing": {
            "volume_name": f"dt-{origin.instance_id}-deployment-consumed",
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


def parse_ingress(value, *, origin=None, recipe=None, instance="7" * 64):
    module = implementation()
    return module.parse_ingress(
        canonical_json(value),
        profile=origin or profile(),
        receipt_recipe_sha256=recipe or module.RECEIPT_RECIPE_SHA256,
        receipt_instance_sha256=instance,
    )


def parse_consumption(value, *, origin=None, recipe=None, instance="7" * 64):
    module = implementation()
    return module.parse_consumption_exchange(
        canonical_json(value),
        profile=origin or profile(),
        receipt_recipe_sha256=recipe or module.RECEIPT_RECIPE_SHA256,
        receipt_instance_sha256=instance,
    )


def test_fixed_recipe_is_exact_canonical_release_artifact():
    module = implementation()
    expected = {
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
    assert module.RECEIPT_RECIPE == expected
    assert module.RECEIPT_RECIPE_BYTES == canonical_json(expected)
    assert len(module.RECEIPT_RECIPE_BYTES) == 487
    assert module.RECEIPT_RECIPE_SHA256 == (
        "3417fbc488ab745019b909564282cc9ff971c99fa2d5ba592e4faeb2f742e173"
    )
    assert module.parse_receipt_recipe(module.RECEIPT_RECIPE_BYTES) == expected
    assert (
        ROOT / "deploy/security/deployment-receipt-recipe-v1.json"
    ).read_bytes() == module.RECEIPT_RECIPE_BYTES


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b'{"schema_version":"x","schema_version":"x"}',
        b"\xef\xbb\xbf{}",
        b"{}\n",
        b"[1]",
        b" " * 4097,
    ],
)
def test_recipe_rejects_malformed_noncanonical_duplicate_and_bounds(raw):
    module = implementation()
    with pytest.raises(module.DeploymentSourceError):
        module.parse_receipt_recipe(raw)


@pytest.mark.parametrize(
    "path,bad",
    [
        (("incoming_final_limit",), True),
        (("consumed_final_limit",), 15),
        (("staging_limit",), 33),
        (("receipt_bytes_max",), 16383),
        (("prepare_recipe", "size_bytes"), 606.0),
        (("renderer_id",), "other"),
    ],
)
def test_recipe_rejects_equivalent_looking_or_changed_policy(path, bad):
    module = implementation()
    value = deepcopy(module.RECEIPT_RECIPE)
    target = value
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = bad
    with pytest.raises(module.DeploymentSourceError):
        module.parse_receipt_recipe(json.dumps(value, separators=(",", ":")).encode())


def test_receipt_instance_is_closed_and_checks_hashes_and_distinct_nonnil_ids():
    module = implementation()
    value = receipt_instance()
    assert module.parse_receipt_instance(canonical_json(value)) == value
    mutations = [
        {**value, "prepare_instance_sha256": True},
        {**value, "trust_set_sha256": "A" * 64},
        {**value, "receipt_ingress_id": "00000000-0000-0000-0000-000000000000"},
        {**value, "receipt_ingress_id": value["consumption_exchange_id"]},
        {**value, "unknown": 1},
    ]
    for changed in mutations:
        with pytest.raises(module.DeploymentSourceError):
            module.parse_receipt_instance(canonical_json(changed))


@pytest.mark.parametrize(
    "path,bad",
    [
        (("schema_version",), "deployment-receipt-ingress-v2"),
        (("ingress_id",), "00000000-0000-0000-0000-000000000000"),
        (("revision",), True),
        (("revision",), 2),
        (("instance_id",), "a" * 31),
        (("origin_profile_digest",), "A" * 64),
        (("receipt_recipe_digest",), "9" * 64),
        (("receipt_instance_digest",), "9" * 64),
        (("writer", "uid"), 20112),
        (("reader", "pair_gid"), 21202),
        (("incoming", "namespaces"), ["receipt"]),
        (("incoming", "writer_read_only"), True),
        (("incoming", "writer_read_only"), 0),
        (("incoming", "control_read_only"), False),
        (("incoming", "control_read_only"), 1),
        (("incoming", "container_path"), "/tmp/incoming"),
        (("incoming", "volume_name"), "dt-foreign-deployment-receipts"),
    ],
)
def test_ingress_rejects_every_fixed_identity_or_layout_mutation(path, bad):
    module = implementation()
    value = ingress()
    target = value
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = bad
    with pytest.raises(module.DeploymentSourceError):
        parse_ingress(value)


@pytest.mark.parametrize(
    "path,bad",
    [
        (("schema_version",), "deployment-consumption-exchange-v2"),
        (("revision",), True),
        (("exchange_id",), "00000000-0000-0000-0000-000000000000"),
        (("instance_id",), "b" * 32),
        (("receipt_recipe_digest",), "9" * 64),
        (("receipt_instance_digest",), "9" * 64),
        (("control", "uid"), 20103),
        (("reader", "gid"), 20114),
        (("outgoing", "namespaces"), "consumed"),
        (("outgoing", "control_read_only"), True),
        (("outgoing", "control_read_only"), 0),
        (("outgoing", "reader_read_only"), False),
        (("outgoing", "reader_read_only"), 1),
        (("outgoing", "owner_uid"), 20113),
        (("outgoing", "container_path"), "/tmp/consumed"),
    ],
)
def test_consumption_exchange_rejects_fixed_identity_or_layout_mutation(path, bad):
    module = implementation()
    value = consumption()
    target = value
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = bad
    with pytest.raises(module.DeploymentSourceError):
        parse_consumption(value)


def test_standalone_parsers_keep_unavailable_counterpart_hashes_inert():
    j = ingress()
    j["prepare_instance_digest"] = "a" * 64
    j["outgoing_exchange_digest"] = "b" * 64
    j["trust_set_digest"] = "c" * 64
    assert parse_ingress(j) == j
    k = consumption()
    k["outgoing_exchange_digest"] = "d" * 64
    k["trust_set_digest"] = "e" * 64
    k["receipt_ingress_digest"] = "f" * 64
    assert parse_consumption(k) == k


def test_parsers_require_actual_profile_and_compiled_recipe_and_instance_pins():
    module = implementation()
    for call, value in ((parse_ingress, ingress()), (parse_consumption, consumption())):
        with pytest.raises(module.DeploymentSourceError):
            call(value, origin=profile(instance="9" * 32))
        with pytest.raises(module.DeploymentSourceError):
            call(value, recipe="9" * 64)
        with pytest.raises(module.DeploymentSourceError):
            call(value, instance="8" * 64)


def test_parsers_reject_unknown_nested_fields_and_string_bounds():
    module = implementation()
    j = ingress()
    j["writer"]["unknown"] = "not-reflected"
    with pytest.raises(
        module.DeploymentSourceError, match="^deployment_source_invalid$"
    ) as error:
        parse_ingress(j)
    assert "not-reflected" not in str(error.value)
    k = consumption()
    k["outgoing"]["namespaces"] = ["x" * 257]
    with pytest.raises(module.DeploymentSourceError):
        parse_consumption(k)
    with pytest.raises(module.DeploymentSourceError):
        module.parse_ingress(
            b" " * 8193,
            profile=profile(),
            receipt_recipe_sha256=module.RECEIPT_RECIPE_SHA256,
            receipt_instance_sha256="7" * 64,
        )


def test_recipe_constant_has_no_terminal_newline_or_self_digest():
    module = implementation()
    assert not module.RECEIPT_RECIPE_BYTES.endswith(b"\n")
    assert b"receipt_recipe_sha256" not in module.RECEIPT_RECIPE_BYTES
    assert hashlib.sha256(module.RECEIPT_RECIPE_BYTES).hexdigest() == (
        module.RECEIPT_RECIPE_SHA256
    )
