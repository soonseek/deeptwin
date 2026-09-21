"""Closed grammar and actual-byte joins never treat declarations as authority."""

import importlib
import json

import pytest

from app.deployment.contracts import DeploymentSourceError
from app.tests.provider_source_fixture import case, encode, refresh_outer


def contracts():
    try:
        return importlib.import_module("app.deployment.provider_source_contracts")
    except ModuleNotFoundError:
        assert False, "Provider document contracts are missing"


def test_independent_bundle_parses_and_validates():
    _, bundle, _ = case()
    m = contracts()
    assert m.validate_provider_source_bundle(bundle) is None
    for kind, index in (("recipe", 10), ("instance", 11), ("trust", 12), ("exchange", 13),
                        ("ingress", 14), ("consumption", 15), ("context", 16), ("pins", 17)):
        raw = bundle[index][1]
        assert getattr(m, "parse_provider_" + kind)(raw) == json.loads(raw)


@pytest.mark.parametrize("registry", ["localhost", "registry:5000", "images.example.org", "localhost:65535"])
def test_explicit_immutable_image_grammar_accepts(registry):
    _, bundle, _ = case(); value = json.loads(bundle[11][1])
    value["initializer_image"] = registry + "/one/repo_name-2.x@sha256:" + "a" * 64
    assert contracts().parse_provider_instance(encode(value)) == value


@pytest.mark.parametrize("image", [
    "registry/repo", "registry/repo@sha256:" + "a" * 64,
    "a" * 64 + ".org/repo@sha256:" + "a" * 64,
    "localhost:01/repo@sha256:" + "a" * 64,
    "localhost:0/repo@sha256:" + "a" * 64,
    "localhost:65536/repo@sha256:" + "a" * 64,
    "https://localhost/repo@sha256:" + "a" * 64,
    "localhost/repo:tag@sha256:" + "a" * 64,
    "localhost/a//b@sha256:" + "a" * 64,
    "localhost/a__b@sha256:" + "a" * 64,
    "localhost/../b@sha256:" + "a" * 64,
    "localhost/${IMAGE}@sha256:" + "a" * 64,
    "localhost/repo@sha256:" + "A" * 64,
])
def test_ambiguous_or_mutable_image_declarations_refuse(image):
    _, bundle, _ = case(); value = json.loads(bundle[11][1]); value["initializer_image"] = image
    with pytest.raises(DeploymentSourceError, match="^deployment_source_invalid$"):
        contracts().parse_provider_instance(encode(value))


@pytest.mark.parametrize("index,field", [
    (3, "exchange_id"), (5, "prepare_instance_sha256"), (5, "trust_set_sha256"),
    (7, "ingress_id"), (7, "prepare_recipe_digest"), (7, "prepare_instance_digest"),
    (7, "outgoing_exchange_digest"), (7, "receipt_recipe_digest"),
    (7, "receipt_instance_digest"), (7, "trust_set_digest"), (8, "exchange_id"),
    (8, "outgoing_exchange_digest"), (8, "receipt_recipe_digest"),
    (8, "receipt_instance_digest"), (8, "trust_set_digest"), (8, "receipt_ingress_digest"),
])
def test_original_deferred_edges_fail_even_with_refreshed_outer_hashes(index, field):
    _, bundle, _ = case(); value = json.loads(bundle[index][1])
    value[field] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" if field.endswith("_id") else "e" * 64
    with pytest.raises(DeploymentSourceError, match="^deployment_source_invalid$"):
        contracts().validate_provider_source_bundle(refresh_outer(bundle, index, value))


@pytest.mark.parametrize("kind,index", [("recipe", 10), ("instance", 11), ("trust", 12), ("exchange", 13),
                                       ("ingress", 14), ("consumption", 15), ("context", 16), ("pins", 17)])
def test_parsers_refuse_noncanonical_wire_and_unknown_fields(kind, index):
    _, bundle, _ = case(); raw = bundle[index][1]; parse = getattr(contracts(), "parse_provider_" + kind)
    for bad in (bytearray(raw), raw + b"\n", b"\xef\xbb\xbf" + raw, b"\xff", b"null", b"{}",
                b'{"x":1,"x":1}', b'{"x":1.0}', b'{"x":NaN}', raw * 100):
        with pytest.raises(DeploymentSourceError, match="^deployment_source_invalid$"):
            parse(bad)
    value = json.loads(raw); value["unknown"] = 1
    with pytest.raises(DeploymentSourceError):
        parse(encode(value))


def test_exact_tuple_bundle_shape_order_and_all_file_mutations():
    _, bundle, _ = case(); validate = contracts().validate_provider_source_bundle
    for bad in (list(bundle), bundle[:-1], bundle + (bundle[-1],), tuple(reversed(bundle)),
                tuple([list(bundle[0]), *bundle[1:]])):
        with pytest.raises(DeploymentSourceError):
            validate(bad)
    for index, (name, raw) in enumerate(bundle):
        for replacement in ((name + ".x", raw), (name, raw + b" "), (name, bytearray(raw))):
            values = list(bundle); values[index] = replacement
            with pytest.raises(DeploymentSourceError):
                validate(tuple(values))


def test_recipe_and_all_ten_schema_exports_are_detached_exact_release_files():
    from app.tests.deployment_source_fixture import ROOT
    from app.tests.provider_source_fixture import recipe
    from jsonschema import Draft202012Validator
    exports = importlib.import_module("app.deployment.provider_source_schema_exports")
    expected_names = (
        "provider-stage-geometry-v1", "provider-source-recipe-v1", "provider-source-instance-v1",
        "provider-public-trust-set-v1", "provider-outgoing-exchange-v1", "provider-receipt-ingress-v1",
        "provider-consumption-exchange-v1", "provider-source-context-v1", "provider-source-pins-v1",
        "provider-source-expansion-record-v1",
    )
    schemas = exports.exported_schemas()
    assert tuple(schemas) == tuple(name + ".schema.json" for name in expected_names)
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        assert schema["$id"] == "urn:deeptwin:schemas:v2:deployment:" + name.removesuffix(".schema.json")
        assert (ROOT / "schemas/v2/deployment" / name).read_bytes() == (json.dumps(schema, sort_keys=True, indent=2) + "\n").encode()
        schema["properties"].clear()
    assert all(value["properties"] for value in exports.exported_schemas().values())
    assert (ROOT / "deploy/security/deployment-provider-source-recipe-v1.json").read_bytes() == encode(recipe())


@pytest.mark.parametrize("index,path,replacement", [
    (10, ("bundle_bytes_max",), True), (10, ("cancellation_bytes_max",), 4096),
    (11, ("context_id",), "00000000-0000-0000-0000-000000000000"),
    (11, ("geometry_sha256",), "A" * 64), (11, ("initializer_image",), None),
    (12, ("version",), True), (12, ("keys", 0, "public_key"), "A" * 42 + "B"),
    (12, ("keys", 0, "adapter_ids"), ["deeptwin-stage-operator-v1"]),
    (12, ("adapter", "operator_version"), "2.0.0"),
    (13, ("revision",), True), (13, ("outgoing", "namespaces"), ["requests", "cancelled"]),
    (13, ("outgoing", "owner_uid"), 0), (13, ("outgoing", "root_mode"), 488),
    (13, ("outgoing", "control_read_only"), 0), (13, ("outgoing", "volume_name"), "dt-" + "2" * 32 + "-provider-deployment-outbox"),
    (14, ("writer", "service_identity"), "control"), (14, ("incoming", "namespaces"), []),
    (15, ("reader", "pair_gid"), 21202), (15, ("outgoing", "unknown"), 1),
    (16, ("epoch",), 2), (16, ("documents", 0, "size_bytes"), 0),
    (16, ("documents", 0, "size_bytes"), 4097), (16, ("documents", 0, "name"), "provider-recipe.json"),
    (16, ("layout_id",), "other"), (17, ("context_size_bytes",), 16385),
])
def test_closed_semantic_types_roles_modes_and_caps(index, path, replacement):
    _, bundle, _ = case(); value = json.loads(bundle[index][1]); parent = value
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = replacement
    kind = {10: "recipe", 11: "instance", 12: "trust", 13: "exchange", 14: "ingress",
            15: "consumption", 16: "context", 17: "pins"}[index]
    with pytest.raises(DeploymentSourceError):
        getattr(contracts(), "parse_provider_" + kind)(encode(value))


def test_trust_sorted_distinct_key_and_public_key_bounds():
    from base64 import urlsafe_b64encode
    _, bundle, _ = case(); value = json.loads(bundle[12][1])
    keys = [{**value["keys"][0], "key_id": f"{n:08x}-aaaa-4aaa-8aaa-{n:012x}",
             "public_key": urlsafe_b64encode(bytes([n]) * 32).rstrip(b"=").decode()} for n in range(1, 9)]
    value["keys"] = keys
    assert contracts().parse_provider_trust(encode(value)) == value
    for bad in ([], keys + [keys[-1]], keys[::-1], [keys[0], keys[0]],
                [keys[0], {**keys[1], "public_key": keys[0]["public_key"]}]):
        with pytest.raises(DeploymentSourceError):
            contracts().parse_provider_trust(encode(value | {"keys": bad}))


@pytest.mark.parametrize("index,field", [(11, "original_prepare_instance_sha256"), (11, "original_receipt_instance_sha256"),
    (11, "geometry_sha256"), (11, "provider_trust_sha256"), (12, "origin_profile_digest"),
    (13, "geometry_sha256"), (13, "provider_instance_sha256"), (13, "origin_profile_digest"),
    (14, "outgoing_exchange_sha256"), (14, "trust_sha256"), (15, "outgoing_exchange_sha256"),
    (15, "receipt_ingress_sha256"), (15, "trust_sha256"), (16, "geometry_sha256"),
    (16, "origin_profile_digest"), (17, "context_sha256"), (17, "provider_instance_sha256")])
def test_new_source_edges_require_actual_bytes_not_rehashed_outer_declarations(index, field):
    _, bundle, _ = case(); value = json.loads(bundle[index][1]); value[field] = "e" * 64
    altered = refresh_outer(bundle, index, value) if index < 16 else tuple(
        (name, encode(value) if n == index else data) for n, (name, data) in enumerate(bundle))
    with pytest.raises(DeploymentSourceError):
        contracts().validate_provider_source_bundle(altered)


def test_deferred_original_document_changes_remain_valid_under_original_parsers():
    from app.deployment import contracts as old
    from app.deployment import receipt_source_contracts as receipt
    from app.operations.setup import OriginProfile
    from app.tests.provider_source_fixture import digest
    _, bundle, _ = case(); raw = [pair[1] for pair in bundle]
    profile = OriginProfile.from_dict(json.loads(raw[1])["origin_profile"])
    options = dict(profile=profile, receipt_recipe_sha256=digest(raw[4]), receipt_instance_sha256=digest(raw[5]))
    cases = ((3, "exchange_id"), (5, "prepare_instance_sha256"), (5, "trust_set_sha256"),
             (7, "ingress_id"), (7, "prepare_recipe_digest"), (7, "prepare_instance_digest"),
             (7, "outgoing_exchange_digest"), (7, "trust_set_digest"),
             (8, "exchange_id"), (8, "outgoing_exchange_digest"), (8, "trust_set_digest"), (8, "receipt_ingress_digest"))
    for index, field in cases:
        value = json.loads(raw[index]); value[field] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" if field.endswith("_id") else "e" * 64
        changed = encode(value)
        if index == 3:
            old.parse_exchange(changed, profile=profile, recipe_sha256=digest(raw[0]), instance_sha256=digest(raw[1]))
        elif index == 5:
            receipt.parse_receipt_instance(changed)
        elif index == 7:
            receipt.parse_ingress(changed, **options)
        else:
            receipt.parse_consumption_exchange(changed, **options)
        with pytest.raises(DeploymentSourceError):
            contracts().validate_provider_source_bundle(refresh_outer(bundle, index, value))


def test_provider_source_recipe_hash_cannot_be_replaced_with_another_valid_shape():
    _, bundle, _ = case(); value = json.loads(bundle[10][1]); value["renderer_id"] = "unimplemented"
    with pytest.raises(DeploymentSourceError):
        contracts().validate_provider_source_bundle(refresh_outer(bundle, 10, value))


def test_complete_bundle_rejects_valid_alternate_topology_id_capacity_and_platform():
    from app.deployment import contracts as original
    from app.operations.setup import OriginProfile
    from app.tests.provider_source_fixture import digest
    _, bundle, _ = case(); value = json.loads(bundle[2][1])
    profile = OriginProfile.from_dict(json.loads(bundle[1][1])["origin_profile"])
    alternatives = [value | {"topology_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"},
                    value | {"platform": "linux/arm64"}, json.loads(case(capacity=16)[1][2][1])]
    for changed in alternatives:
        raw = encode(changed)
        original.parse_topology(raw, profile=profile, recipe_sha256=digest(bundle[0][1]), platform=changed["platform"])
        with pytest.raises(DeploymentSourceError):
            contracts().validate_provider_source_bundle(refresh_outer(bundle, 2, changed))


def test_provider_role_and_profile_swaps_refuse_with_fresh_context_references():
    _, bundle, _ = case(); validate = contracts().validate_provider_source_bundle
    for left, right in ((10, 11), (12, 6), (13, 15), (14, 7), (16, 17)):
        changed = refresh_outer(bundle, left, json.loads(bundle[right][1]))
        with pytest.raises(DeploymentSourceError):
            validate(changed)
    trust = json.loads(bundle[12][1]); trust["adapter"]["deployment_profile_id"] = "portable-compose-v1"
    assert contracts().parse_provider_trust(encode(trust)) == trust
    with pytest.raises(DeploymentSourceError):
        validate(refresh_outer(bundle, 12, trust))


def test_original_ids_must_be_distinct_even_with_valid_original_documents():
    from app.deployment import contracts as old
    from app.deployment import receipt_source_contracts as receipts
    from app.operations.setup import OriginProfile
    from app.tests.provider_source_fixture import digest
    _, bundle, _ = case(); pairs = list(bundle)
    prepare = json.loads(pairs[1][1]); profile = OriginProfile.from_dict(prepare["origin_profile"])
    receipt = json.loads(pairs[5][1]); receipt["receipt_ingress_id"] = prepare["topology_id"]
    pairs[5] = (pairs[5][0], encode(receipt))
    ingress = json.loads(pairs[7][1]); ingress["ingress_id"] = receipt["receipt_ingress_id"]
    ingress["receipt_instance_digest"] = digest(pairs[5][1]); pairs[7] = (pairs[7][0], encode(ingress))
    consumption = json.loads(pairs[8][1]); consumption["receipt_instance_digest"] = digest(pairs[5][1])
    consumption["receipt_ingress_digest"] = digest(pairs[7][1]); pairs[8] = (pairs[8][0], encode(consumption))
    opts = dict(profile=profile, receipt_recipe_sha256=digest(pairs[4][1]), receipt_instance_sha256=digest(pairs[5][1]))
    receipts.parse_receipt_instance(pairs[5][1]); receipts.parse_ingress(pairs[7][1], **opts)
    receipts.parse_consumption_exchange(pairs[8][1], **opts)
    with pytest.raises(DeploymentSourceError):
        contracts().validate_provider_source_bundle(refresh_outer(tuple(pairs), 8, consumption))


@pytest.mark.parametrize("kind,index", [("recipe", 10), ("instance", 11), ("trust", 12), ("exchange", 13),
                                       ("ingress", 14), ("consumption", 15), ("context", 16), ("pins", 17)])
def test_new_wire_numeric_string_member_and_depth_bounds(kind, index):
    _, bundle, _ = case(); raw = bundle[index][1]; parse = getattr(contracts(), "parse_provider_" + kind)
    key = b'"schema_version":'
    prefix, remainder = raw.split(key, 1)
    for bad_value in (b"1099511627777", b"-1099511627777", b"1.5", b"Infinity", b"true", b"null",
                      b'"' + b"x" * 1025 + b'"', b"[" * 13 + b"0" + b"]" * 13,
                      b"{" + b",".join(b'"k%d":0' % n for n in range(33)) + b"}"):
        end = remainder.index(b'"', 1) + 1
        with pytest.raises(DeploymentSourceError):
            parse(prefix + key + bad_value + remainder[end:])
