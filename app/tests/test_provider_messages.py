"""Control grammar does not replace artifact-frame grammar."""

from uuid import uuid4
import pytest
from app.tests._provider_worker_fixture import encoded, text_plan


def test_strict_control_roundtrip():
    from app.workers.provider_messages import encode_control, parse_control

    value = {"schema": "provider-worker-identify-v1", "challenge": "a" * 64}
    assert parse_control(encode_control(value)) == value


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema":"provider-worker-identify-v1","challenge":"x"}',
        b'{"schema":"provider-worker-identify-v1","challenge":null}',
        b'{"schema":"provider-worker-identify-v1","challenge":"a","challenge":"a"}',
        encoded({"schema": "extension-stage-probe-v1"}),
        encoded(
            {
                "schema": "provider-worker-identify-v1",
                "challenge": "a" * 64,
                "key": "forbidden",
            }
        ),
    ],
)
def test_closed_control(raw):
    from app.workers.provider_messages import parse_control, ProviderMessageError

    with pytest.raises(ProviderMessageError):
        parse_control(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "bool",
        "float",
        "unused",
        "order",
        "no_user",
        "system_after",
        "duplicate",
    ],
)
def test_plan_is_closed_and_exact(mutation):
    from app.workers.provider_messages import parse_plan, ProviderMessageError

    value = text_plan()
    if mutation == "extra":
        value["effort"] = "high"
    if mutation == "bool":
        value["max_output_tokens"] = True
    if mutation == "float":
        value["max_output_tokens"] = 1.5
    if mutation == "unused":
        value["inputs"].append(value["inputs"][0])
    if mutation == "order":
        value["messages"][0]["input_ordinals"] = [1]
    if mutation == "no_user":
        value["messages"][0]["role"] = "assistant"
    if mutation == "system_after":
        value["messages"].append({"role": "system", "input_ordinals": [0]})
    if mutation == "duplicate":
        value["messages"][0]["input_ordinals"] = [0, 0]
    with pytest.raises(ProviderMessageError):
        parse_plan(encoded(value), "text")


def test_long_body_codec_and_exact_63_bit_integer():
    from app.workers.provider_messages import (
        encode_body,
        decode_body,
        ProviderMessageError,
    )

    value = {"text": "x" * 70000, "number": 2**63 - 1}
    assert decode_body(encode_body(value)) == value
    with pytest.raises(ProviderMessageError):
        encode_body({"number": 2**63})


@pytest.mark.parametrize(
    ("service_id", "valid"),
    [
        ("worker.slot_1", True),
        ("worker--slot", False),
        ("worker-", False),
        ("w" * 65, False),
    ],
)
def test_identity_service_id_matches_broker_grammar(service_id, valid):
    from app.workers.provider_messages import encode_control, ProviderMessageError

    value = {
        "schema": "provider-worker-identity-v1",
        "challenge": "a" * 64,
        "service_identity": service_id,
        "build_identity_digest": "b" * 64,
        "port_schema_set_digest": "c" * 64,
        "platform": "linux/amd64",
        "uid": 1,
        "gid": 1,
        "worker_profile": "claude-text-transform-v1",
        "implemented_transforms": ["catalog", "text"],
    }
    if valid:
        assert encode_control(value)
    else:
        with pytest.raises(ProviderMessageError):
            encode_control(value)


def test_result_codec_refuses_cross_operation_reason():
    from app.workers.provider_messages import encode_result, ProviderMessageError

    value = {
        "schema": "provider-transform-result-v1",
        "operation": "catalog",
        "state": "non_success",
        "reason": "refusal",
        "input_digest": "a" * 64,
        "observation": {"page_digests": [], "complete": False, "models": []},
    }
    with pytest.raises(ProviderMessageError):
        encode_result(value)
