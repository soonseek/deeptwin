"""Receipt schemas are deterministic structural validators, never authority."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.domain.refs import canonical_json
from app.operations.setup import OriginProfile
from app.tests.test_deployment_receipt_contracts import receipt_value, trust_value

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "schemas/v1/deployment"
FIXTURE = ROOT / "app/tests/fixtures/deployment-receipt-ed25519-v1.json"


def implementation():
    return importlib.import_module("app.deployment.receipt_schema_exports")


def validators():
    values = implementation().exported_schemas()
    return {
        name: Draft202012Validator(schema, format_checker=FormatChecker())
        for name, schema in values.items()
    }


def test_exact_two_closed_structural_exports_have_distinct_authority_comment():
    values = implementation().exported_schemas()
    assert set(values) == {
        "receipt-stage-v1.schema.json",
        "public-trust-set-v1.schema.json",
    }
    for name, schema in values.items():
        Draft202012Validator.check_schema(schema)
        assert schema["$id"] == (
            "urn:deeptwin:schemas:v1:deployment:" + name.removesuffix(".schema.json")
        )
        assert "Structural only" in schema["$comment"]
        assert "signature authenticity" in schema["$comment"]
        assert schema["additionalProperties"] is False


def test_exports_are_detached_and_write_exact_fresh_bytes(tmp_path):
    module = implementation()
    values = module.exported_schemas()
    values["receipt-stage-v1.schema.json"]["properties"].clear()
    assert module.exported_schemas()["receipt-stage-v1.schema.json"]["properties"]
    module.write_schemas(tmp_path)
    for name, schema in module.exported_schemas().items():
        expected = (
            json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        assert (tmp_path / name).read_bytes() == expected
        assert (ARTIFACT_ROOT / name).read_bytes() == expected


@pytest.mark.parametrize(
    "kind,change",
    [
        ("receipt", "unknown"),
        ("receipt", "nil_uuid"),
        ("receipt", "calendar"),
        ("receipt", "bool_integer"),
        ("receipt", "bad_b64"),
        ("receipt", "fixed_arm"),
        ("trust", "unknown"),
        ("trust", "empty_keys"),
        ("trust", "algorithm"),
        ("trust", "bool_integer"),
        ("trust", "bad_b64"),
    ],
)
def test_runtime_and_schema_agree_on_structural_rejections(kind, change):
    contracts = importlib.import_module("app.deployment.receipt_contracts")
    origin = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=8080)
    value = receipt_value(origin=origin) if kind == "receipt" else trust_value(origin)
    if change == "unknown":
        value["unknown"] = None
    elif change == "nil_uuid":
        value["request_id"] = "00000000-0000-0000-0000-000000000000"
    elif change == "calendar":
        value["started_at"] = "2023-02-30T22:13:21.000Z"
    elif change == "bool_integer":
        if kind == "receipt":
            value["effect_result"]["expected_next_installation_revision"] = True
        else:
            value["version"] = True
    elif change == "bad_b64":
        value["origin_profile_digest"] = "A" * 42 + "B"
    elif change == "fixed_arm":
        value["effect_result"]["old_service"] = {"presence": "present"}
    elif change == "empty_keys":
        value["keys"] = []
    else:
        value["keys"][0]["algorithm"] = "Ed25519ph"
    validator = validators()[
        "receipt-stage-v1.schema.json"
        if kind == "receipt"
        else "public-trust-set-v1.schema.json"
    ]
    assert not validator.is_valid(value)
    parser = contracts.parse_receipt if kind == "receipt" else contracts.parse_trust_set
    arguments = {} if kind == "receipt" else {"profile": origin}
    with pytest.raises(contracts.ReceiptWireError, match="^receipt_invalid$"):
        parser(canonical_json(value), **arguments)


def test_schema_accepts_valid_shapes_for_both_profiles_and_all_outcomes():
    values = json.loads(FIXTURE.read_bytes())
    receipt_validator = validators()["receipt-stage-v1.schema.json"]
    trust_validator = validators()["public-trust-set-v1.schema.json"]
    valid = [case for case in values["cases"] if case["name"].startswith("valid_")]
    assert {case["profile"]["deployment_profile_id"] for case in valid} == {
        "local-no-terminal-v1",
        "portable-compose-v1",
    }
    assert {json.loads(case["receipt_utf8"])["outcome"] for case in valid} == {
        "succeeded",
        "failed",
        "unknown",
    }
    for case in valid:
        assert receipt_validator.is_valid(json.loads(case["receipt_utf8"]))
        assert trust_validator.is_valid(json.loads(case["trust_utf8"]))


@pytest.mark.parametrize(
    "presence,field,identity",
    [
        ("present", "service_identity", "1service"),
        ("unknown", "expected_service_identity", "a" * 65),
    ],
)
def test_receipt_schema_accepts_full_wire_id_grammar(
    presence, field, identity
):
    value = receipt_value(
        outcome="succeeded" if presence == "present" else "failed",
        presence=presence,
    )
    value["effect_result"]["new_service"][field] = identity
    assert validators()["receipt-stage-v1.schema.json"].is_valid(value)


def test_relational_and_crypto_invalid_documents_can_remain_structurally_valid():
    values = json.loads(FIXTURE.read_bytes())
    receipt_validator = validators()["receipt-stage-v1.schema.json"]
    structurally_valid = {
        "invalid_cross_request",
        "invalid_profile",
        "invalid_tuple",
        "invalid_time",
        "invalid_expiry",
    }
    structurally_invalid = {"invalid_key_adapter", "invalid_fact"}
    observed = {}
    for case in values["cases"]:
        if case["name"].startswith("invalid_"):
            observed[case["name"]] = receipt_validator.is_valid(
                json.loads(case["receipt_utf8"])
            )
    assert {name for name, accepted in observed.items() if accepted} == structurally_valid
    assert {name for name, accepted in observed.items() if not accepted} == structurally_invalid


def test_schema_objects_do_not_claim_signatures_or_relations_were_verified():
    value = receipt_value()
    value["signature"] = "A" * 86
    value["request_nonce"] = "A" * 43
    assert validators()["receipt-stage-v1.schema.json"].is_valid(deepcopy(value))
