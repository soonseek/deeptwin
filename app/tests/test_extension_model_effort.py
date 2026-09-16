"""Exact catalog effort values at each model-execution port boundary.

The generated refs and trusted mappings below are complete controlled fixture
context for request validation.  They are not durable production authority,
qualification evidence, a binding resolver, or an execution dispatcher.
"""

from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator

from app.extensions.port_contracts import (
    ALLOWED_TERMINAL_CANDIDATES,
    OPERATION_CONTRACTS,
    PORT_SCHEMA_IDS,
    REJECTED_TERMINAL_CANDIDATES,
)
from app.extensions.port_schema_generator import (
    generate_port_schemas,
    validate_port_payload,
)
from app.model_catalog import ModelCatalog
from app.storage import Store
from app.tests.test_extension_port_schema_generation import (
    _config_instance,
    _minimal,
    _request_context,
    _request_digest,
    _request_instance,
    _result_instance,
)
from app.tests.test_gateway_catalog_integration import (
    ControlledCodexCatalog,
    choice,
    freeze_validated_choice,
)

EXECUTION_FIELDS = (
    ("provider-port-v1", "model_step", "effort"),
    ("model-runtime-port-v1", "model_step", "effort"),
    ("managed-provider-runner-port-v1", "preflight", "requested_effort"),
    ("managed-provider-runner-port-v1", "run_start", "effort"),
)
CAPABILITY_ARRAYS = (
    ("provider-port-v1", "result", "catalog", "effort_values"),
    ("model-runtime-port-v1", "config", None, "supported_efforts"),
    ("model-runtime-port-v1", "result", "capabilities", "effort_values"),
)
EXACT_EFFORT_VALUES = (
    "ordinary",
    "Case Preserved",
    " leading and trailing ",
    "punctuation !?/+",
    "노력 단계",
    "e\u0301",
    "line\nbreak",
    "nul\x00value",
    "e" * 80,
)


def _catalog_frozen_turn(tmp_path, effort):
    source = ControlledCodexCatalog(Store(tmp_path))
    advertised = "medium" if effort is None else effort
    source.models = [source.model("gpt-fixture", efforts=(advertised,))]
    subject = ModelCatalog(source.store, source)
    catalog = subject.refresh("codex")
    validated = subject.validate_choice(choice(catalog, effort=effort))
    return freeze_validated_choice(validated)


def _validated_execution_request(tmp_path, port, operation, field, effort):
    frozen = _catalog_frozen_turn(tmp_path, effort)
    request = _request_instance(port, operation)
    request["input"][field] = frozen.effort
    request["idempotency_key"] = _request_digest(request)
    context = _request_context(port, request)
    if "frozen_record" in context:
        context["frozen_record"]["effort"] = frozen.effort

    validate_port_payload(port, "request", request, context=context)
    encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    assert json.loads(encoded)["input"][field] == frozen.effort
    if frozen.effort is not None:
        assert request["input"][field].encode("utf-8") == frozen.effort.encode("utf-8")
    return request, context


@pytest.mark.parametrize("port,operation,field", EXECUTION_FIELDS)
@pytest.mark.parametrize("effort", (*EXACT_EFFORT_VALUES, None))
def test_catalog_frozen_effort_survives_full_execution_request_validation(
    tmp_path, port, operation, field, effort,
):
    _validated_execution_request(tmp_path, port, operation, field, effort)


def _capability_instance(port, shape, operation, field, effort_values):
    if shape == "config":
        value = _config_instance(port)
        value["port_config"][field] = effort_values
        return value
    value = _result_instance(port, operation, "succeeded")
    if port == "provider-port-v1":
        branch = next(
            item for item in generate_port_schemas()[(port, shape)]["oneOf"]
            if item["properties"]["operation"]["const"] == operation
            and item["properties"]["terminal"]["const"] == "succeeded"
        )
        model_schema = branch["properties"]["output"]["properties"]["models"]["items"]
        value["output"]["models"] = [_minimal(model_schema)]
        value["output"]["models"][0][field] = effort_values
    else:
        value["output"][field] = effort_values
    return value


@pytest.mark.parametrize("port,shape,operation,field", CAPABILITY_ARRAYS)
@pytest.mark.parametrize("effort", EXACT_EFFORT_VALUES)
def test_effort_capability_arrays_accept_exact_non_null_values(
    port, shape, operation, field, effort,
):
    value = _capability_instance(port, shape, operation, field, [effort])
    errors = list(Draft202012Validator(
        generate_port_schemas()[(port, shape)],
    ).iter_errors(value))
    assert errors == []


@pytest.mark.parametrize("port,operation,field", EXECUTION_FIELDS)
def test_execution_effort_field_is_required(port, operation, field):
    request = _request_instance(port, operation)
    request["input"].pop(field)
    request["idempotency_key"] = _request_digest(request)
    errors = list(Draft202012Validator(
        generate_port_schemas()[(port, "request")],
    ).iter_errors(request))
    assert errors


@pytest.mark.parametrize("port,operation,field", EXECUTION_FIELDS)
@pytest.mark.parametrize("bad_effort", (True, 1, {}, [], "", "e" * 81))
def test_execution_effort_field_rejects_wrong_type_or_length(
    port, operation, field, bad_effort,
):
    request = _request_instance(port, operation)
    request["input"][field] = bad_effort
    request["idempotency_key"] = _request_digest(request)
    errors = list(Draft202012Validator(
        generate_port_schemas()[(port, "request")],
    ).iter_errors(request))
    assert errors


@pytest.mark.parametrize("port,shape,operation,field", CAPABILITY_ARRAYS)
@pytest.mark.parametrize("bad_effort", (None, True, 1, {}, [], "", "e" * 81))
def test_effort_capability_arrays_reject_null_wrong_type_or_length(
    port, shape, operation, field, bad_effort,
):
    value = _capability_instance(port, shape, operation, field, [bad_effort])
    errors = list(Draft202012Validator(
        generate_port_schemas()[(port, shape)],
    ).iter_errors(value))
    assert errors


@pytest.mark.parametrize("port,shape,operation,field", CAPABILITY_ARRAYS)
def test_effort_capability_arrays_retain_closed_array_contract(
    port, shape, operation, field,
):
    if shape == "config":
        array_schema = generate_port_schemas()[(port, shape)]["properties"][
            "port_config"
        ]["properties"][field]
    else:
        branch = next(
            item for item in generate_port_schemas()[(port, shape)]["oneOf"]
            if item["properties"]["operation"]["const"] == operation
            and item["properties"]["terminal"]["const"] == "succeeded"
        )
        output = branch["properties"]["output"]["properties"]
        array_schema = (
            output["models"]["items"]["properties"][field]
            if port == "provider-port-v1"
            else output[field]
        )
    assert array_schema["minItems"] == 0
    assert array_schema["maxItems"] == 256
    assert array_schema["uniqueItems"] is True
    assert array_schema["x-deeptwin-sorted"] == "canonical-json-byte-order"
    assert array_schema["items"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 80,
    }


def test_effort_schema_change_preserves_catalog_and_terminal_invariants():
    generated = generate_port_schemas()
    branches = sum(
        len(schema["oneOf"])
        for (port, shape), schema in generated.items()
        if shape == "result"
    )
    assert len(generated) == len(PORT_SCHEMA_IDS) == 44
    assert len(OPERATION_CONTRACTS) == 52
    assert branches == len(ALLOWED_TERMINAL_CANDIDATES) == 127
    assert len(REJECTED_TERMINAL_CANDIDATES) == 81
