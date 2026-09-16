"""Pure receipt/trust wire behavior; parsed values remain inert."""

import importlib
from base64 import urlsafe_b64encode
from copy import deepcopy

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import profile as make_profile


def implementation():
    try:
        return importlib.import_module("app.deployment.receipt_contracts")
    except ModuleNotFoundError:
        pytest.fail("Deployment receipt contract implementation is missing")


def b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def stage_result(*, presence="present"):
    common = {
        "schema_id": "deeptwin.extension-stage-result.v1",
        "extension_id": "synthetic-tool",
        "expected_installation_head": {"state": "absent"},
        "expected_next_installation_revision": 1,
        "old_service": {"presence": "absent"},
    }
    if presence == "absent":
        service = {"presence": "absent"}
    elif presence == "present":
        service = {
            "presence": "present",
            "service_identity": "ext-11111111111111111111111111111111-01",
            "manifest_digest": "1" * 64,
            "service_descriptor_digest": "2" * 64,
            "selected_platform_entry_digest": "3" * 64,
            "image_manifest_digest": "sha256:" + "4" * 64,
            "reachable_after_effect": True,
            "observed_at": "2023-11-14T22:13:22.000Z",
        }
    else:
        service = {
            "presence": "unknown",
            "expected_service_identity": "ext-11111111111111111111111111111111-01",
            "expected_manifest_digest": "1" * 64,
            "expected_service_descriptor_digest": "2" * 64,
            "expected_selected_platform_entry_digest": "3" * 64,
            "expected_image_manifest_digest": "sha256:" + "4" * 64,
            "failure_class": "observation_unavailable",
            "observed_at": "2023-11-14T22:13:22.000Z",
        }
    return {**common, "new_service": service}


def receipt_value(*, origin=None, outcome="succeeded", presence="present"):
    origin = origin or make_profile()
    failure = {
        "succeeded": None,
        "failed": "effect_failed",
        "unknown": "observation_unavailable",
    }[outcome]
    return {
        "schema": "deployment-receipt-v1",
        "domain": "deeptwin-deployment-receipt-v1",
        "request_id": "12345678-1234-4234-8234-123456789abc",
        "request_digest": b64(b"d" * 32),
        "request_nonce": b64(b"n" * 32),
        "kind": "extension_stage",
        "instance_id": origin.instance_id,
        "origin_profile_digest": b64(bytes.fromhex(origin.digest)),
        "deployment_profile_id": origin.deployment_profile_id,
        "operator_adapter": "deeptwin-stage-operator-v1",
        "operator_version": "1.0.0",
        "effect_result": stage_result(presence=presence),
        "started_at": "2023-11-14T22:13:21.000Z",
        "completed_at": "2023-11-14T22:13:23.000Z",
        "outcome": outcome,
        "failure_class": failure,
        "claimed_facts": ["request_binding"],
        "verified_facts": ["service_presence"],
        "unverified_facts": ["service_reachability"],
        "key_id": "87654321-4321-4321-8321-cba987654321",
        "trust_set_digest": b64(b"t" * 32),
        "trust_class": "instance_operator",
        "signature": b64(b"s" * 64),
    }


def trust_value(origin=None):
    origin = origin or make_profile()
    return {
        "schema": "deployment-public-trust-set-v1",
        "domain": "deeptwin-deployment-public-trust-set-v1",
        "version": 1,
        "instance_id": origin.instance_id,
        "origin_profile_digest": b64(bytes.fromhex(origin.digest)),
        "keys": [
            {
                "key_id": "87654321-4321-4321-8321-cba987654321",
                "algorithm": "ed25519",
                "public_key": b64(b"p" * 32),
                "trust_class": "instance_operator",
                "adapter_ids": ["deeptwin-stage-operator-v1"],
            }
        ],
        "adapters": [
            {
                "operator_adapter": "deeptwin-stage-operator-v1",
                "operator_version": "1.0.0",
                "deployment_profile_id": origin.deployment_profile_id,
            }
        ],
    }


def rejected(value):
    module = implementation()
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$") as error:
        module.parse_receipt(canonical_json(value))
    assert error.value.code == "receipt_invalid"


def test_receipt_parser_returns_exact_canonical_inert_value():
    module = implementation()
    value = receipt_value()
    raw = canonical_json(value)
    parsed = module.parse_receipt(raw)
    assert parsed == value
    assert canonical_json(parsed) == raw
    bad = {**value, "unknown": "must-not-be-reflected"}
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$") as error:
        module.parse_receipt(canonical_json(bad))
    assert "must-not-be-reflected" not in str(error.value)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("schema", "deployment-receipt-v2"),
        ("domain", "deeptwin-deployment-receipt-v2"),
        ("request_id", "00000000-0000-0000-0000-000000000000"),
        ("request_id", "12345678-1234-4234-8234-123456789ABC"),
        ("request_digest", "A" * 42 + "B"),
        ("request_nonce", "A" * 44),
        ("kind", "extension_update"),
        ("instance_id", "A" * 32),
        ("origin_profile_digest", "A" * 42 + "B"),
        ("deployment_profile_id", "future-profile"),
        ("operator_adapter", "future-adapter"),
        ("operator_version", "1.0.1"),
        ("started_at", "2023-02-30T22:13:21.000Z"),
        ("completed_at", "9999-12-31T23:59:59.9999Z"),
        ("outcome", "cancelled"),
        ("claimed_facts", "request_binding"),
        ("key_id", True),
        ("trust_set_digest", "A" * 42 + "B"),
        ("trust_class", "runtime_worker"),
        ("signature", "A" * 85 + "B"),
    ],
)
def test_receipt_closed_scalar_and_canonical_base64_rejections(field, bad):
    value = receipt_value()
    value[field] = bad
    rejected(value)


@pytest.mark.parametrize(
    "outcome,failure,presence,accepted",
    [
        ("succeeded", None, "present", True),
        ("succeeded", None, "absent", False),
        ("succeeded", "effect_failed", "present", False),
        ("failed", "effect_failed", "absent", True),
        ("failed", "precondition_failed", "unknown", True),
        ("failed", None, "absent", False),
        ("unknown", "observation_unavailable", "unknown", True),
        ("unknown", "deadline_exceeded", "unknown", True),
        ("unknown", "effect_failed", "unknown", False),
        ("unknown", "observation_unavailable", "absent", False),
    ],
)
def test_outcome_failure_and_observation_matrix(outcome, failure, presence, accepted):
    module = implementation()
    value = receipt_value(outcome=outcome, presence=presence)
    value["failure_class"] = failure
    if presence == "unknown" and outcome == "unknown" and failure is not None:
        value["effect_result"]["new_service"]["failure_class"] = failure
    if accepted:
        assert module.parse_receipt(canonical_json(value)) == value
    else:
        rejected(value)


@pytest.mark.parametrize(
    "change",
    ["old", "revision", "extra", "missing", "wrong_presence", "bad_id", "bool", "observed"],
)
def test_stage_result_is_the_exact_first_installation_arm(change):
    value = receipt_value()
    result = value["effect_result"]
    service = result["new_service"]
    if change == "old":
        result["old_service"] = {"presence": "present"}
    elif change == "revision":
        result["expected_next_installation_revision"] = True
    elif change == "extra":
        service["future"] = None
    elif change == "missing":
        service.pop("manifest_digest")
    elif change == "wrong_presence":
        service["presence"] = "unknown"
    elif change == "bad_id":
        result["extension_id"] = "bad\n"
    elif change == "bool":
        service["reachable_after_effect"] = 1
    else:
        service["observed_at"] = "2023-11-14T22:13:24.000Z"
    rejected(value)


@pytest.mark.parametrize(
    "presence,field,identity",
    [
        ("present", "service_identity", "1service"),
        ("unknown", "expected_service_identity", "a" * 65),
    ],
)
def test_receipt_service_identities_use_full_wire_id_grammar(
    presence, field, identity
):
    module = implementation()
    value = receipt_value(
        outcome="succeeded" if presence == "present" else "failed",
        presence=presence,
    )
    value["effect_result"]["new_service"][field] = identity
    assert module.parse_receipt(canonical_json(value)) == value


@pytest.mark.parametrize(
    "change",
    ["unsorted", "duplicate", "overlap", "unknown", "too_many"],
)
def test_fact_lists_are_sorted_unique_disjoint_and_bounded(change):
    value = receipt_value()
    if change == "unsorted":
        value["claimed_facts"] = ["service_presence", "request_binding"]
    elif change == "duplicate":
        value["claimed_facts"] = ["request_binding", "request_binding"]
    elif change == "overlap":
        value["verified_facts"] = ["request_binding"]
    elif change == "unknown":
        value["claimed_facts"] = ["future_fact"]
    else:
        facts = [
            "image_identity",
            "mount_configuration",
            "network_configuration",
            "operator_preconditions",
            "request_binding",
            "resource_configuration",
            "service_presence",
            "service_reachability",
        ]
        value["claimed_facts"] = facts
        value["verified_facts"] = ["request_binding"]
        value["unverified_facts"] = []
    rejected(value)


@pytest.mark.parametrize(
    "raw",
    [
        b"\xef\xbb\xbf{}",
        b"{}\n",
        b'{"schema":"deployment-receipt-v1","schema":"deployment-receipt-v1"}',
        b"[]",
        b"{\xff}",
    ],
)
def test_receipt_rejects_noncanonical_duplicate_bom_and_non_object_bytes(raw):
    module = implementation()
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$"):
        module.parse_receipt(raw)


def test_receipt_bounds_precede_semantics():
    module = implementation()
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$"):
        module.parse_receipt(b"{" + b" " * 16384)
    value = receipt_value()
    value["effect_result"]["extension_id"] = "a" * 1025
    rejected(value)


@pytest.mark.parametrize(
    "started,observed,completed",
    [
        (
            "0001-01-01T00:00:00.000Z",
            "0001-01-01T00:00:00.000Z",
            "0001-01-01T00:00:00.001Z",
        ),
        (
            "9999-12-31T23:59:59.997Z",
            "9999-12-31T23:59:59.999Z",
            "9999-12-31T23:59:59.999Z",
        ),
    ],
)
def test_calendar_extrema_and_observation_endpoint_equalities(started, observed, completed):
    module = implementation()
    value = receipt_value()
    value["started_at"] = started
    value["completed_at"] = completed
    value["effect_result"]["new_service"]["observed_at"] = observed
    assert module.parse_receipt(canonical_json(value)) == value


def test_all_eight_distinct_facts_are_accepted_once():
    module = implementation()
    value = receipt_value()
    value["claimed_facts"] = sorted(
        [
            "request_binding",
            "image_identity",
            "mount_configuration",
            "service_presence",
            "service_reachability",
            "network_configuration",
            "resource_configuration",
            "operator_preconditions",
        ]
    )
    value["verified_facts"] = []
    value["unverified_facts"] = []
    assert module.parse_receipt(canonical_json(value)) == value


@pytest.mark.parametrize("change", ["nested_duplicate", "unicode_escape"])
def test_nested_duplicates_and_alternate_unicode_spelling_are_noncanonical(change):
    module = implementation()
    raw = canonical_json(receipt_value())
    if change == "nested_duplicate":
        raw = raw.replace(
            b'{"presence":"absent"}',
            b'{"presence":"absent","presence":"absent"}',
            1,
        )
    else:
        raw = raw.replace(b"synthetic-tool", b"synthetic\\u002dtool", 1)
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$"):
        module.parse_receipt(raw)


def test_trust_parser_binds_exact_origin_profile_and_returns_fresh_value():
    module = implementation()
    origin = make_profile()
    value = trust_value(origin)
    raw = canonical_json(value)
    parsed = module.parse_trust_set(raw, profile=origin)
    assert parsed == value and parsed is not value
    parsed["keys"].clear()
    assert module.parse_trust_set(raw, profile=origin) == value
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$"):
        module.parse_trust_set(raw, profile=origin.as_dict())


@pytest.mark.parametrize(
    "change",
    [
        "instance",
        "origin",
        "profile",
        "empty_keys",
        "key_order",
        "key_id_duplicate",
        "public_duplicate",
        "algorithm",
        "class",
        "adapter_ids",
        "extra_adapter",
        "unknown",
    ],
)
def test_trust_set_is_closed_unique_sorted_and_profile_specific(change):
    module = implementation()
    origin = make_profile()
    value = trust_value(origin)
    if change == "instance":
        value["instance_id"] = "2" * 32
    elif change == "origin":
        value["origin_profile_digest"] = b64(b"x" * 32)
    elif change == "profile":
        value["adapters"][0]["deployment_profile_id"] = "portable-compose-v1"
    elif change == "empty_keys":
        value["keys"] = []
    elif change in {"key_order", "key_id_duplicate", "public_duplicate"}:
        second = deepcopy(value["keys"][0])
        second["key_id"] = "11111111-1111-4111-8111-111111111111"
        second["public_key"] = b64(b"q" * 32)
        value["keys"].append(second)
        if change == "key_id_duplicate":
            second["key_id"] = value["keys"][0]["key_id"]
        elif change == "public_duplicate":
            second["public_key"] = value["keys"][0]["public_key"]
    elif change == "algorithm":
        value["keys"][0]["algorithm"] = "Ed25519ph"
    elif change == "class":
        value["keys"][0]["trust_class"] = "runtime_worker"
    elif change == "adapter_ids":
        value["keys"][0]["adapter_ids"] = []
    elif change == "extra_adapter":
        value["adapters"].append(deepcopy(value["adapters"][0]))
    else:
        value["unknown"] = "canary"
    with pytest.raises(module.ReceiptWireError, match="^receipt_invalid$") as error:
        module.parse_trust_set(canonical_json(value), profile=origin)
    assert "canary" not in str(error.value)


def test_trust_set_accepts_exact_eight_sorted_unique_public_keys():
    module = implementation()
    origin = make_profile()
    value = trust_value(origin)
    value["keys"] = []
    for number in range(1, 9):
        value["keys"].append(
            {
                "key_id": f"0000000{number}-0000-4000-8000-000000000000",
                "algorithm": "ed25519",
                "public_key": b64(bytes([number]) * 32),
                "trust_class": "instance_operator",
                "adapter_ids": ["deeptwin-stage-operator-v1"],
            }
        )
    assert module.parse_trust_set(canonical_json(value), profile=origin) == value
