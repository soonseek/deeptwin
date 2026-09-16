"""T087-A1 executable JSON Schema generation/validation acceptance tests."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.domain.refs import canonical_json
from app.extensions.port_contracts import (
    ALLOWED_EFFECT_TUPLES,
    ALLOWED_TERMINAL_CANDIDATES,
    EFFECT_FAMILIES,
    OPERATION_CONTRACTS,
    PORT_CONTRACTS,
    PORT_SCHEMA_IDS,
    REJECTED_TERMINAL_CANDIDATES,
)
from app.extensions.port_schema_generator import (
    BUILTIN_TOOL_ARTIFACT_INPUT_CONTRACTS,
    PortSchemaValidationError,
    canonical_schema_bytes,
    generate_port_schemas,
    validate_port_payload,
    validate_refinement_schema,
    write_port_schemas,
)

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "v1" / "extensions" / "ports"


def test_generates_exact_closed_draft_2020_12_catalog():
    generated = generate_port_schemas()
    assert set(generated) == set(PORT_SCHEMA_IDS)
    assert len(generated) == 44
    assert {schema["$id"] for schema in generated.values()} == set(PORT_SCHEMA_IDS.values())
    for (port, shape), schema in generated.items():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == PORT_SCHEMA_IDS[(port, shape)]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_generated_files_are_byte_deterministic_and_hash_equal(tmp_path):
    first = write_port_schemas(tmp_path / "first")
    second = write_port_schemas(tmp_path / "second")
    assert set(first) == set(second) == set(PORT_SCHEMA_IDS)
    for key in PORT_SCHEMA_IDS:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == canonical_schema_bytes(generate_port_schemas()[key])
        checked_in = SCHEMA_ROOT / key[0] / f"{key[1]}.schema.json"
        assert checked_in.read_bytes() == first[key].read_bytes()


def test_request_and_result_discriminators_are_exhaustive():
    generated = generate_port_schemas()
    request_pairs = set()
    result_pairs = set()
    for port, contract in PORT_CONTRACTS.items():
        request = generated[(port, "request")]
        result = generated[(port, "result")]
        assert len(request["oneOf"]) == len(contract.operations)
        for branch in request["oneOf"]:
            operation = branch["properties"]["operation"]["const"]
            request_pairs.add((port, operation))
        for branch in result["oneOf"]:
            operation = branch["properties"]["operation"]["const"]
            terminal = branch["properties"]["terminal"]["const"]
            result_pairs.add((port, operation, terminal))
    assert request_pairs == set(OPERATION_CONTRACTS)
    assert result_pairs == set(ALLOWED_TERMINAL_CANDIDATES)
    assert len(result_pairs) == 127
    assert len(REJECTED_TERMINAL_CANDIDATES) == 81


def test_request_artifact_profiles_are_embedded_as_11_nonempty_and_41_empty():
    generated = generate_port_schemas()
    counts = {"empty": 0, "nonempty": 0}
    for port, operation in OPERATION_CONTRACTS:
        branch = next(
            item for item in generated[(port, "request")]["oneOf"]
            if item["properties"]["operation"]["const"] == operation
        )
        artifact_schema = branch["properties"]["artifact_inputs"]
        expected = OPERATION_CONTRACTS[(port, operation)].request_artifact_profile
        if expected == "E":
            assert artifact_schema["maxItems"] == 0
            counts["empty"] += 1
        else:
            assert artifact_schema["maxItems"] > 0
            counts["nonempty"] += 1
    assert counts == {"empty": 41, "nonempty": 11}


def test_non_success_artifacts_are_exactly_empty_and_success_modes_are_44_4_4():
    generated = generate_port_schemas()
    modes = {"E": 0, "V": 0, "O": 0}
    for port, operation in OPERATION_CONTRACTS:
        result = generated[(port, "result")]
        branches = [
            branch for branch in result["oneOf"]
            if branch["properties"]["operation"]["const"] == operation
        ]
        success = next(branch for branch in branches
                       if branch["properties"]["terminal"]["const"] == "succeeded")
        artifacts = success["properties"]["artifacts"]
        mode = OPERATION_CONTRACTS[(port, operation)].result_artifact_mode
        modes[mode] += 1
        if mode == "E":
            assert artifacts["maxItems"] == 0
        elif mode == "O":
            assert artifacts["minItems"] == artifacts["maxItems"] == 1
        else:
            assert artifacts["minItems"] == 0
            assert artifacts["maxItems"] == 256
        for branch in branches:
            if branch["properties"]["terminal"]["const"] != "succeeded":
                assert branch["properties"]["artifacts"]["maxItems"] == 0
    assert modes == {"E": 44, "V": 4, "O": 4}


def test_tool_success_output_is_exact_two_fields_and_rejects_receipt_alias():
    schema = generate_port_schemas()[("tool-port-v1", "result")]
    branch = next(
        item for item in schema["oneOf"]
        if item["properties"]["operation"]["const"] == "invoke_tool"
        and item["properties"]["terminal"]["const"] == "succeeded"
    )
    output = branch["properties"]["output"]
    assert set(output["properties"]) == {"tool_call_ref", "result_ref"}
    assert output["additionalProperties"] is False
    assert "effect_receipt_ref" not in json.dumps(output, sort_keys=True)
    candidate = _result_instance("tool-port-v1", "invoke_tool", "succeeded")
    candidate["output"]["effect_receipt_ref"] = _ref("effect_receipt")
    assert list(Draft202012Validator(schema).iter_errors(candidate))
    alias = _result_instance("tool-port-v1", "invoke_tool", "succeeded")
    alias["output"]["receipt_ref"] = _ref("effect_receipt")
    assert list(Draft202012Validator(schema).iter_errors(alias))


def test_refinement_schema_must_be_closed_local_and_bounded():
    valid = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"temperature": {"type": "integer", "minimum": 0, "maximum": 2}},
        "required": ["temperature"],
        "additionalProperties": False,
    }
    validate_refinement_schema(valid)
    for mutation in (
        {**valid, "additionalProperties": True},
        {**valid, "$ref": "https://attacker.invalid/schema.json"},
        {**valid, "$dynamicRef": "#x"},
        {**valid, "properties": {"x": {"type": "string", "default": "secret"}}},
        {**valid, "properties": {"x": {"type": "string", "maxLength": 4097}}},
    ):
        with pytest.raises(PortSchemaValidationError):
            validate_refinement_schema(mutation)


def test_refinement_is_applied_after_base_and_cannot_replace_core_fields():
    config = _provider_config()
    config["binding_slot_key_digest"] = _slot_digest(config["binding_slot_key"])
    config["extension_config"] = {"temperature": 1}
    refinement = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "temperature": {"type": "integer", "minimum": 0, "maximum": 2},
        },
        "required": ["temperature"],
        "additionalProperties": False,
    }
    validate_port_payload(
        "provider-port-v1", "config", config,
        context=_config_context(config), refinement_schema=refinement,
    )
    wrong = deepcopy(config)
    wrong["extension_config"]["temperature"] = 3
    with pytest.raises(PortSchemaValidationError, match="refinement rejected"):
        validate_port_payload(
            "provider-port-v1", "config", wrong,
            context=_config_context(wrong), refinement_schema=refinement,
        )
    with pytest.raises(PortSchemaValidationError, match="without a frozen refinement"):
        validate_port_payload(
            "provider-port-v1", "config", config, context=_config_context(config),
        )
    replaced = deepcopy(config)
    replaced["schema_version"] = 2
    with pytest.raises(PortSchemaValidationError, match="base schema rejected"):
        validate_port_payload(
            "provider-port-v1", "config", replaced,
            context=_config_context(replaced), refinement_schema=refinement,
        )


def test_extension_error_code_requires_the_manifest_frozen_operation_enum():
    request = _request_instance("tool-port-v1", "invoke_tool")
    error = _error_instance("tool-port-v1", "invoke_tool")
    error["code"] = "port_specific_failure"
    error["port_error_code"] = "execution_failed"
    error["extension_error_code"] = "vendor_failure"
    with pytest.raises(PortSchemaValidationError, match="manifest-frozen"):
        validate_port_payload(
            "tool-port-v1", "error", error,
            context={"request": request, "extension_error_codes": {}},
        )
    validate_port_payload(
        "tool-port-v1", "error", error,
        context={
            "request": request,
            "extension_error_codes": {"invoke_tool": ["vendor_failure"]},
        },
    )


def test_actual_jsonschema_validator_rejects_unknown_missing_wrong_type_and_operation():
    schema = generate_port_schemas()[("provider-port-v1", "config")]
    valid = {
        "schema_id": PORT_SCHEMA_IDS[("provider-port-v1", "config")],
        "schema_version": 1,
        "port_contract_version": "provider-port-v1",
        "extension_id": "org.example.provider",
        "installation_digest": "a" * 64,
        "qualification_ref": _ref("qualification"),
        "binding_revision_ref": _ref("binding"),
        "binding_slot_key": _slot("provider-port-v1"),
        "binding_slot_key_digest": "b" * 64,
        "extension_config": {},
        "grant_refs": [],
        "credential_handle_refs": [],
        "resource_limits": _limits(),
        "port_config": {
            "provider_id": "anthropic",
            "auth_mode": "api",
            "api_origin": "https://api.anthropic.com/v1",
            "egress_policy_ref": _ref("egress_policy"),
            "catalog_ttl_seconds": 3600,
            "supported_modalities": ["text"],
            "supported_input_media_types": ["text/plain"],
        },
    }
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(valid)) == []
    for mutation in (
        lambda value: value.update(extra=True),
        lambda value: value.pop("resource_limits"),
        lambda value: value.update(schema_version=True),
        lambda value: value.update(port_contract_version="tool-port-v1"),
        lambda value: value["port_config"].update(auth_mode="subscription"),
        lambda value: value["resource_limits"].update(deadline_ms=600001),
    ):
        candidate = deepcopy(valid)
        mutation(candidate)
        assert list(validator.iter_errors(candidate))


def test_semantic_validator_rejects_binding_digest_and_nested_port_mismatch():
    valid = _provider_config()
    with pytest.raises(PortSchemaValidationError):
        validate_port_payload(
            "provider-port-v1", "config", valid, context=_config_context(valid),
        )
    valid["binding_slot_key_digest"] = _slot_digest(valid["binding_slot_key"])
    validate_port_payload(
        "provider-port-v1", "config", valid, context=_config_context(valid),
    )
    wrong = deepcopy(valid)
    wrong["binding_slot_key"]["port_contract_version"] = "tool-port-v1"
    wrong["binding_slot_key_digest"] = _slot_digest(wrong["binding_slot_key"])
    with pytest.raises(PortSchemaValidationError):
        validate_port_payload(
            "provider-port-v1", "config", wrong, context=_config_context(wrong),
        )


def test_every_request_and_allowed_result_branch_has_a_real_valid_instance():
    generated = generate_port_schemas()
    for port, contract in PORT_CONTRACTS.items():
        request_schema = generated[(port, "request")]
        result_schema = generated[(port, "result")]
        for operation in contract.operations:
            request = _request_instance(port, operation)
            assert list(Draft202012Validator(request_schema).iter_errors(request)) == []
            for terminal in (
                terminal for candidate_port, candidate_operation, terminal
                in ALLOWED_TERMINAL_CANDIDATES
                if (candidate_port, candidate_operation) == (port, operation)
            ):
                result = _result_instance(port, operation, terminal)
                assert list(Draft202012Validator(result_schema).iter_errors(result)) == []


def test_all_44_schemas_reject_unknown_missing_and_wrong_core_fields():
    generated = generate_port_schemas()
    for (port, shape), schema in generated.items():
        if shape == "config":
            value = _config_instance(port)
        elif shape == "request":
            value = _request_instance(port, PORT_CONTRACTS[port].operations[0])
        elif shape == "result":
            operation = PORT_CONTRACTS[port].operations[0]
            value = _result_instance(port, operation, "succeeded")
        else:
            value = _error_instance(port, PORT_CONTRACTS[port].operations[0])
        validator = Draft202012Validator(schema)
        assert list(validator.iter_errors(value)) == []
        unknown = deepcopy(value)
        unknown["unknown_core_field"] = True
        assert list(validator.iter_errors(unknown))
        missing = deepcopy(value)
        missing.pop("schema_id")
        assert list(validator.iter_errors(missing))
        wrong_type = deepcopy(value)
        wrong_type["schema_version"] = True
        assert list(validator.iter_errors(wrong_type))


def test_result_artifact_role_media_omissions_metadata_is_embedded_exactly():
    generated = generate_port_schemas()
    expected = {
        ("provider-port-v1", "model_step"): ("model_content", "null"),
        ("managed-provider-runner-port-v1", "run_status"): ("runner_artifact", "dynamic"),
        ("model-runtime-port-v1", "model_step"): ("model_content", "null"),
        ("tool-port-v1", "invoke_tool"): (None, "dynamic"),
        ("artifact-codec-port-v1", "decode_projection"): ("decoded_projection", "dynamic"),
        ("artifact-codec-port-v1", "render_preview"): ("render_preview", "dynamic"),
        ("artifact-codec-port-v1", "encode"): ("encoded_output", "dynamic"),
        ("storage-port-v1", "read"): ("storage_object", "null"),
    }
    for (port, operation), (role, omissions) in expected.items():
        branch = next(
            item for item in generated[(port, "result")]["oneOf"]
            if item["properties"]["operation"]["const"] == operation
            and item["properties"]["terminal"]["const"] == "succeeded"
        )
        item = branch["properties"]["artifacts"]["items"]
        if role is None:
            assert "const" not in item["properties"]["role"]
        else:
            assert item["properties"]["role"]["const"] == role
        omission_schema = item["properties"]["omissions_ref"]
        if omissions == "null":
            assert omission_schema == {"type": "null"}
        else:
            assert {arm.get("type") for arm in omission_schema["oneOf"]} == {"object", "null"}


def test_all_81_disallowed_operation_terminal_candidates_are_rejected():
    generated = generate_port_schemas()
    for port, operation, rejected_terminal in REJECTED_TERMINAL_CANDIDATES:
        allowed_terminal = next(
            terminal for candidate_port, candidate_operation, terminal
            in ALLOWED_TERMINAL_CANDIDATES
            if (candidate_port, candidate_operation) == (port, operation)
        )
        candidate = _result_instance(port, operation, allowed_terminal)
        candidate["terminal"] = rejected_terminal
        assert list(Draft202012Validator(
            generated[(port, "result")],
        ).iter_errors(candidate))


def test_result_schema_accepts_only_the_exhaustive_effect_table():
    schema = generate_port_schemas()[("tool-port-v1", "result")]
    effect_states = ("none", "not_committed", "committed", "unknown")
    remote_outcomes = ("not_applicable", "confirmed", "unconfirmed", "unknown")
    effect_classes = (
        "none", "read", "write_reversible", "external_reversible",
        "external_irreversible", "instance_critical_secret", "instance_critical_storage",
    )
    for terminal in ("succeeded", "failed", "cancelled", "unknown"):
        baseline = _result_instance("tool-port-v1", "invoke_tool", terminal)
        for effect_class in effect_classes:
            family = EFFECT_FAMILIES[effect_class]
            for state in effect_states:
                for receipt_presence in ("null", "ref"):
                    for outcome in remote_outcomes:
                        candidate = deepcopy(baseline)
                        candidate["effect"] = {
                            "effect_class": effect_class,
                            "effect_state": state,
                            "effect_receipt_ref": (
                                None if receipt_presence == "null" else _ref("effect_receipt")
                            ),
                            "remote_outcome": outcome,
                        }
                        accepted = not list(Draft202012Validator(schema).iter_errors(candidate))
                        expected = (state, receipt_presence, outcome) in (
                            ALLOWED_EFFECT_TUPLES[(terminal, family)]
                        )
                        assert accepted is expected, (
                            terminal, effect_class, state, receipt_presence, outcome,
                        )


def test_artifact_profile_cardinality_role_selector_and_duplicate_guards():
    generated = generate_port_schemas()
    # Exact-empty profiles cannot smuggle a byte input.
    empty_request = _request_instance("provider-port-v1", "catalog")
    empty_request["artifact_inputs"] = [_artifact_input("unexpected")]
    assert list(Draft202012Validator(
        generated[("provider-port-v1", "request")],
    ).iter_errors(empty_request))

    # Exact-one storage and codec source roles/selectors are closed by the schema.
    storage = _request_instance("storage-port-v1", "write_cas")
    storage["artifact_inputs"][0]["role"] = "wrong"
    assert list(Draft202012Validator(
        generated[("storage-port-v1", "request")],
    ).iter_errors(storage))
    codec = _request_instance("artifact-codec-port-v1", "encode")
    codec["artifact_inputs"][0]["selector_ref"] = _ref("selector")
    assert list(Draft202012Validator(
        generated[("artifact-codec-port-v1", "request")],
    ).iter_errors(codec))
    export = _request_instance("export-sink-port-v1", "prepare")
    export["artifact_inputs"] = []
    assert list(Draft202012Validator(
        generated[("export-sink-port-v1", "request")],
    ).iter_errors(export))


def test_semantic_validator_rejects_frozen_list_mismatch_and_hidden_tool_ref():
    provider = _request_instance("provider-port-v1", "model_step")
    provider_context = _request_context("provider-port-v1", provider)
    validate_port_payload(
        "provider-port-v1", "request", provider, context=provider_context,
    )
    provider_context["frozen_record"]["artifact_input_bindings"] = [
        _artifact_input("model_input", marker="b"),
    ]
    with pytest.raises(PortSchemaValidationError, match="frozen source list"):
        validate_port_payload(
            "provider-port-v1", "request", provider, context=provider_context,
        )

    tool = _request_instance("tool-port-v1", "invoke_tool")
    tool_context = _request_context("tool-port-v1", tool)
    validate_port_payload("tool-port-v1", "request", tool, context=tool_context)
    tool_context["resolved_arguments"] = {"nested": {"artifact": _ref("artifact")}}
    with pytest.raises(PortSchemaValidationError, match="hidden artifact"):
        validate_port_payload("tool-port-v1", "request", tool, context=tool_context)


def test_semantic_validator_enforces_builtin_tool_profiles_and_export_exact_list():
    request = _request_instance("tool-port-v1", "invoke_tool")
    request["input"]["tool_id"] = "browser_upload"
    request["artifact_inputs"] = [_artifact_input("browser_upload")]
    context = _request_context("tool-port-v1", request)
    validate_port_payload("tool-port-v1", "request", request, context=context)
    context["tool_definition"]["artifact_input_contract"] = {
        "mode": "bounded", "min_items": 0, "max_items": 32,
        "role": "browser_upload", "allowed_media_types": ["text/plain"],
        "selector_policy": "optional",
    }
    with pytest.raises(PortSchemaValidationError, match="widened or changed"):
        validate_port_payload("tool-port-v1", "request", request, context=context)

    export = _request_instance("export-sink-port-v1", "transmit")
    export_context = _request_context("export-sink-port-v1", export)
    validate_port_payload(
        "export-sink-port-v1", "request", export, context=export_context,
    )
    export_context["prepared_delivery_record"]["artifact_input_bindings"] = [
        _artifact_input("export_payload", marker="b"),
    ]
    with pytest.raises(PortSchemaValidationError, match="frozen source list"):
        validate_port_payload(
            "export-sink-port-v1", "request", export, context=export_context,
        )


def test_result_lineage_enforces_codec_refs_media_omissions_and_tool_bindings():
    _, result, context = _complete_result_case(
        "artifact-codec-port-v1", "render_preview",
    )
    validate_port_payload(
        "artifact-codec-port-v1", "result", result, context=context,
    )
    wrong = deepcopy(result)
    wrong["artifacts"][0]["omissions_ref"] = _ref("omissions", marker="b")
    with pytest.raises(PortSchemaValidationError, match="omissions"):
        validate_port_payload(
            "artifact-codec-port-v1", "result", wrong, context=context,
        )

    _, tool_result, tool_context = _complete_result_case(
        "tool-port-v1", "invoke_tool",
    )
    validate_port_payload(
        "tool-port-v1", "result", tool_result, context=tool_context,
    )
    tool_context["tool_definition"]["artifact_output_contract"]["max_items"] = 1
    tool_context["tool_result_artifact_bindings"] = [{
        "artifact_ref": _ref("artifact", marker="b"),
        "role": "tool_output", "media_type": "text/plain",
        "omissions_ref": None,
    }]
    with pytest.raises(PortSchemaValidationError, match="sealed artifact bindings"):
        validate_port_payload(
            "tool-port-v1", "result", tool_result,
            context=tool_context,
        )


def test_contract_structure_guard_accepts_source_and_rejects_broken_port_table():
    from app.extensions.port_schema_generator import validate_contract_source_structure

    source = (Path(__file__).resolve().parents[2] /
              "specs/001-autonomous-release/contracts/extension-ports.md").read_text()
    assert len(validate_contract_source_structure(source)) == 11
    broken = source.replace(
        "| `provider-port-v1` |", "intervening prose\n| `provider-port-v1` |", 1,
    )
    with pytest.raises(PortSchemaValidationError):
        validate_contract_source_structure(broken)


def test_semantic_validation_fails_closed_without_trusted_context():
    config = _config_instance("provider-port-v1")
    request = _request_instance("tool-port-v1", "invoke_tool")
    result = _result_instance("tool-port-v1", "invoke_tool", "succeeded")
    error = _error_instance("tool-port-v1", "invoke_tool")

    for port, shape, value in (
        ("provider-port-v1", "config", config),
        ("tool-port-v1", "request", request),
        ("tool-port-v1", "result", result),
        ("tool-port-v1", "error", error),
    ):
        with pytest.raises(PortSchemaValidationError, match="trusted context"):
            validate_port_payload(port, shape, value)


def test_every_artifact_input_profile_rejects_duplicate_binding_tuples():
    generated = generate_port_schemas()
    for port, operation, role in (
        ("provider-port-v1", "model_step", "model_input"),
        ("managed-provider-runner-port-v1", "run_start", "runner_input"),
        ("tool-port-v1", "invoke_tool", "tool_input"),
    ):
        candidate = _request_instance(port, operation)
        binding = _artifact_input(role)
        candidate["artifact_inputs"] = [binding, deepcopy(binding)]
        candidate["idempotency_key"] = _request_digest(candidate)
        assert list(Draft202012Validator(
            generated[(port, "request")],
        ).iter_errors(candidate)), (port, operation)


def test_refinement_rejects_recursive_open_numeric_and_cyclic_widening():
    nested_open = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "payload": {"properties": {
                "known": {"type": "string", "maxLength": 4096},
            }},
        },
        "required": ["payload"],
        "additionalProperties": False,
    }
    wildcard = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "patternProperties": {".*": {"type": "string", "maxLength": 4096}},
        "additionalProperties": False,
    }
    cyclic = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"payload": {"$ref": "#/$defs/loop"}},
        "additionalProperties": False,
        "$defs": {"loop": {"$ref": "#/$defs/loop"}},
    }
    float_schema = {
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    unbounded_integer = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    for schema in (nested_open, wildcard, cyclic, float_schema, unbounded_integer):
        with pytest.raises(PortSchemaValidationError):
            validate_refinement_schema(schema)


@pytest.mark.parametrize("uri", (
    "https://example.com/a/../b",
    "https://example.com/%41",
    "https://example.com//a",
))
def test_https_uri_rejects_noncanonical_paths(uri):
    config = _config_instance("provider-port-v1")
    config["port_config"]["api_origin"] = uri
    with pytest.raises(PortSchemaValidationError, match="canonical"):
        validate_port_payload(
            "provider-port-v1", "config", config,
            context={},
        )


def test_contract_guard_rejects_a_decoy_port_table_outside_normative_sections():
    from app.extensions.port_schema_generator import validate_contract_source_structure

    source = (Path(__file__).resolve().parents[2] /
              "specs/001-autonomous-release/contracts/extension-ports.md").read_text()
    ports = tuple(PORT_CONTRACTS)
    changed = source
    for port in ports:
        changed = changed.replace(f"| `{port}` |", "| REMOVED |", 1)
    decoy = "\n\n| Port | Decoy |\n| --- | --- |\n" + "".join(
        f"| `{port}` | fake |\n" for port in ports
    )
    with pytest.raises(PortSchemaValidationError, match="normative"):
        validate_contract_source_structure(changed + decoy)


def _minimal(schema: dict) -> object:
    if "const" in schema:
        return deepcopy(schema["const"])
    if "enum" in schema:
        return deepcopy(schema["enum"][0])
    if "oneOf" in schema:
        return _minimal(schema["oneOf"][0])
    kind = schema.get("type")
    if kind == "object":
        return {
            name: _minimal(schema["properties"][name])
            for name in schema.get("required", [])
        }
    if kind == "array":
        return [_minimal(schema["items"]) for _ in range(schema.get("minItems", 0))]
    if kind == "integer":
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    if kind == "string":
        pattern = schema.get("pattern")
        if pattern == UUID_PATTERN_FOR_TEST:
            return "123e4567-e89b-42d3-a456-426614174000"
        if pattern == r"^[0-9a-f]{64}$":
            return "a" * 64
        if pattern == (
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
            r"[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
        ):
            return "2026-09-09T00:00:00.000Z"
        if schema.get("format") == "uri":
            return "https://example.com/path"
        if pattern and pattern.startswith("^[a-z0-9][a-z0-9!#"):
            return "text/plain"
        return "x"
    raise AssertionError(f"cannot synthesize schema: {schema!r}")


UUID_PATTERN_FOR_TEST = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _config_instance(port: str) -> dict:
    schema = generate_port_schemas()[(port, "config")]
    value = {name: _minimal(field) for name, field in schema["properties"].items()}
    value["binding_slot_key_digest"] = _slot_digest(value["binding_slot_key"])
    return value


def _error_instance(port: str, operation: str) -> dict:
    schema = generate_port_schemas()[(port, "error")]
    value = {name: _minimal(field) for name, field in schema["properties"].items()}
    value["operation"] = operation
    value["code"] = "invalid_request"
    value["port_error_code"] = None
    value["extension_error_code"] = None
    value["retry_class"] = "never"
    return value


def _request_instance(port: str, operation: str) -> dict:
    schema = generate_port_schemas()[(port, "request")]
    value = {name: _minimal(field) for name, field in schema["properties"].items()}
    branch = next(
        branch for branch in schema["oneOf"]
        if branch["properties"]["operation"]["const"] == operation
    )
    for name, field in branch["properties"].items():
        value[name] = _minimal(field)
    value["idempotency_key"] = _request_digest(value)
    return value


def _request_digest(value: dict) -> str:
    return sha256(canonical_json({
        "port_contract_version": value["port_contract_version"],
        "installation_digest": value["installation_digest"],
        "binding_revision_ref": value["binding_revision_ref"],
        "purpose_ref": value["purpose_ref"],
        "operation": value["operation"],
        "grant_refs": value["grant_refs"],
        "artifact_inputs": value["artifact_inputs"],
        "input": value["input"],
        "extension_input": value["extension_input"],
    })).hexdigest()


def _result_instance(port: str, operation: str, terminal: str) -> dict:
    schema = generate_port_schemas()[(port, "result")]
    value = {name: _minimal(field) for name, field in schema["properties"].items()}
    branch = next(
        branch for branch in schema["oneOf"]
        if branch["properties"]["operation"]["const"] == operation
        and branch["properties"]["terminal"]["const"] == terminal
    )
    for name, field in branch["properties"].items():
        value[name] = _minimal(field)
    if terminal != "succeeded":
        value["error"]["port_error_code"] = None
        value["error"]["extension_error_code"] = None
        value["error"]["retry_class"] = "never"
        if terminal == "cancelled":
            value["error"]["code"] = "cancelled"
        elif terminal == "unknown":
            value["error"]["code"] = "external_effect_unknown"
        else:
            value["error"]["code"] = "invalid_request"
    return value


def _effect_for(effect_class: str, terminal: str) -> dict:
    state, receipt, outcome = min(
        ALLOWED_EFFECT_TUPLES[(terminal, EFFECT_FAMILIES[effect_class])],
    )
    return {
        "effect_class": effect_class, "effect_state": state,
        "effect_receipt_ref": None if receipt == "null" else _ref("effect_receipt"),
        "remote_outcome": outcome,
    }


def _artifact_input(role: str, *, marker: str = "a") -> dict:
    return {
        "artifact_ref": _ref("artifact", marker=marker),
        "selector_ref": None,
        "declared_media_type": "text/plain",
        "role": role,
    }


def _ref(kind: str = "artifact", *, marker: str = "a") -> dict:
    return {
        "kind": kind,
        "id": "123e4567-e89b-42d3-a456-426614174000",
        "version": 1,
        "sha256": marker * 64,
    }


def _slot(port: str) -> dict:
    return {
        "port_contract_version": port,
        "target_scope_fingerprint": "c" * 64,
        "purpose": "operational",
        "binding_slot_id": "primary",
        "capability_selector_digest": "d" * 64,
    }


def _slot_digest(slot: dict) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(slot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _limits() -> dict:
    return {
        "deadline_ms": 60_000,
        "max_input_bytes": 1_048_576,
        "max_output_bytes": 1_048_576,
        "max_artifacts": 16,
        "max_artifact_bytes": 67_108_864,
        "max_artifact_input_bytes": 67_108_864,
    }


def _provider_config() -> dict:
    slot = _slot("provider-port-v1")
    return {
        "schema_id": PORT_SCHEMA_IDS[("provider-port-v1", "config")],
        "schema_version": 1,
        "port_contract_version": "provider-port-v1",
        "extension_id": "org.example.provider",
        "installation_digest": "a" * 64,
        "qualification_ref": _ref("qualification"),
        "binding_revision_ref": _ref("binding"),
        "binding_slot_key": slot,
        "binding_slot_key_digest": "b" * 64,
        "extension_config": {},
        "grant_refs": [],
        "credential_handle_refs": [],
        "resource_limits": _limits(),
        "port_config": {
            "provider_id": "anthropic",
            "auth_mode": "api",
            "api_origin": "https://api.anthropic.com/v1",
            "egress_policy_ref": _ref("egress_policy"),
            "catalog_ttl_seconds": 3600,
            "supported_modalities": ["text"],
            "supported_input_media_types": ["text/plain"],
        },
    }


_ACCEPTED_AT = "2026-09-08T23:59:59.900Z"
_UNEXPIRED_AT = "2027-01-01T00:00:00.000Z"


def _config_context(config: dict) -> dict:
    """Trusted durable-store records matching one exact validated config."""
    return {
        "validated_at": _ACCEPTED_AT,
        "qualification_record": {
            "ref": deepcopy(config["qualification_ref"]),
            "status": "qualified",
            "installation_digest": config["installation_digest"],
            "port_contract_version": config["port_contract_version"],
            "expires_at": _UNEXPIRED_AT,
        },
        "binding_revision_record": {
            "ref": deepcopy(config["binding_revision_ref"]),
            "state": "active",
            "extension_id": config["extension_id"],
            "installation_digest": config["installation_digest"],
            "qualification_ref": deepcopy(config["qualification_ref"]),
            "port_contract_version": config["port_contract_version"],
            "binding_slot_key": deepcopy(config["binding_slot_key"]),
            "binding_slot_key_digest": config["binding_slot_key_digest"],
            "grant_refs": deepcopy(config["grant_refs"]),
            "credential_handle_refs": deepcopy(config["credential_handle_refs"]),
        },
        "binding_head_record": {
            "state": "active",
            "current_binding_revision_ref": deepcopy(config["binding_revision_ref"]),
            "binding_slot_key": deepcopy(config["binding_slot_key"]),
            "binding_slot_key_digest": config["binding_slot_key_digest"],
        },
    }


def _record_type(field: str) -> str:
    if field.endswith("_refs"):
        return field[:-5]
    if field.endswith("_ref"):
        return field[:-4]
    return field


def _uniquify_input_refs(request: dict) -> list[tuple[str, dict]]:
    """Give every named operation-input ref a distinct digest, then reseal the key."""
    named: list[tuple[str, dict]] = []

    def walk(value: object, field: str) -> None:
        if type(value) is dict:
            if set(value) == {"kind", "id", "version", "sha256"}:
                value["sha256"] = f"{len(named) + 1:064x}"
                named.append((field, value))
                return
            for name, child in value.items():
                walk(child, name)
        elif type(value) is list:
            for child in value:
                walk(child, field)

    walk(request["input"], "input")
    request["idempotency_key"] = _request_digest(request)
    return named


def _request_context(port: str, request: dict) -> dict:
    """Full trusted context under which the given request is exactly acceptable.

    Mutates the request only to make its named input refs distinct records,
    resealing the idempotency key afterwards.
    """
    config = _config_instance(port)
    config["installation_digest"] = request["installation_digest"]
    config["qualification_ref"] = deepcopy(request["qualification_ref"])
    config["binding_revision_ref"] = deepcopy(request["binding_revision_ref"])
    config["grant_refs"] = deepcopy(request["grant_refs"])
    config["resource_limits"] = _limits()
    media = sorted({item["declared_media_type"] for item in request["artifact_inputs"]})
    for field in ("supported_input_media_types", "input_media_types",
                  "accepted_value_media_types", "supported_media_types"):
        if field in config["port_config"] and media:
            config["port_config"][field] = media
    named = _uniquify_input_refs(request)
    context = {
        "config": config,
        "accepted_at": _ACCEPTED_AT,
        "actor_record": {
            "ref": deepcopy(request["actor_ref"]),
            "authenticated": True,
            "actor_type": "system",
        },
        "purpose_record": {
            "ref": deepcopy(request["purpose_ref"]),
            "active": True,
            "purpose": config["binding_slot_key"]["purpose"],
        },
        "grant_records": {
            ref["sha256"]: {
                "ref": deepcopy(ref),
                "active": True,
                "purpose_ref": deepcopy(request["purpose_ref"]),
                "allowed_operations": [request["operation"]],
            }
            for ref in request["grant_refs"]
        },
        "artifact_records": {
            binding["artifact_ref"]["sha256"]: {
                "ref": deepcopy(binding["artifact_ref"]),
                "readable": True,
                "purpose_ref": deepcopy(request["purpose_ref"]),
                "grant_refs": deepcopy(request["grant_refs"]),
                "media_type": binding["declared_media_type"],
                "byte_count": 1,
            }
            for binding in request["artifact_inputs"]
        },
        "selector_records": {},
        "input_records": {
            ref["sha256"]: {"ref": deepcopy(ref), "record_type": _record_type(field)}
            for field, ref in named
        },
    }
    profile = OPERATION_CONTRACTS[(port, request["operation"])].request_artifact_profile
    source = {
        "artifact_input_bindings": deepcopy(request["artifact_inputs"]),
        "purpose_ref": deepcopy(request["purpose_ref"]),
        "grant_refs": deepcopy(request["grant_refs"]),
    }
    if profile == "F-model":
        context["frozen_record"] = {
            "ref": deepcopy(request["input"]["frozen_turn_ref"]), **source,
        }
    elif profile == "F-runner":
        context["frozen_record"] = {
            "ref": deepcopy(request["input"]["frozen_run_projection_ref"]), **source,
        }
    elif profile == "X-export-prepare":
        context["export_snapshot_record"] = {
            "ref": deepcopy(request["input"]["snapshot_ref"]),
            "bounded_stream_authorized": True,
            **source,
        }
    elif profile == "X-export-transmit":
        context["prepared_delivery_record"] = {
            "ref": deepcopy(request["input"]["prepared_delivery_ref"]),
            "bounded_stream_authorized": True,
            "target_ref": deepcopy(request["input"]["target_ref"]),
            "expires_at": _UNEXPIRED_AT,
            **source,
        }
    elif profile == "T-tool":
        tool_ref = _ref("tool_definition", marker="f")
        config["port_config"]["tool_definition_refs"] = [deepcopy(tool_ref)]
        tool_id = request["input"]["tool_id"]
        context["tool_definition"] = {
            "ref": tool_ref,
            "tool_id": tool_id,
            "version": request["input"]["tool_version"],
            "effect_class": request["input"]["expected_effect_class"],
            "artifact_input_contract": deepcopy(
                BUILTIN_TOOL_ARTIFACT_INPUT_CONTRACTS.get(tool_id, {"mode": "none"}),
            ),
        }
        context["resolved_arguments"] = {}
    return context


@pytest.mark.parametrize("port,operation,artifact_count", (
    ("provider-port-v1", "catalog", 0),
    ("tool-port-v1", "invoke_tool", 0),
    ("storage-port-v1", "read", 1),
))
def test_success_result_rejects_empty_context(port, operation, artifact_count):
    """Catch result validation silently skipping every trusted comparison."""
    request = _request_instance(port, operation)
    result = _result_instance(port, operation, "succeeded")
    result["request_id"] = request["request_id"]
    assert len(result["artifacts"]) == artifact_count

    with pytest.raises(PortSchemaValidationError, match="trusted context"):
        validate_port_payload(port, "result", result, context={})


def _complete_result_case(port: str, operation: str,
                          terminal: str = "succeeded") -> tuple[dict, dict, dict]:
    """Build controlled mappings; these do not establish store authenticity."""
    request = _request_instance(port, operation)
    if port == "artifact-codec-port-v1" and request["artifact_inputs"]:
        request["artifact_inputs"][0]["selector_ref"] = None
        request["idempotency_key"] = _request_digest(request)
    result = _result_instance(port, operation, terminal)
    result["request_id"] = request["request_id"]
    if port == "tool-port-v1" and operation == "invoke_tool":
        result["effect"] = _effect_for(request["input"]["expected_effect_class"], terminal)

    result_ref_field = {
        ("artifact-codec-port-v1", "decode_projection"): "projection_artifact_ref",
        ("artifact-codec-port-v1", "render_preview"): "preview_artifact_ref",
        ("artifact-codec-port-v1", "encode"): "encoded_artifact_ref",
        ("storage-port-v1", "read"): "object_artifact_ref",
    }.get((port, operation))
    if result_ref_field is not None:
        output_ref = _ref("artifact", marker="e")
        result["artifacts"][0]["artifact_ref"] = deepcopy(output_ref)
        result["output"][result_ref_field] = deepcopy(output_ref)
    if (port == "artifact-codec-port-v1"
            and operation in {"render_preview", "encode"}):
        result["artifacts"][0]["media_type"] = request["input"]["target_media_type"]

    context = _request_context(port, request)
    context.update(_config_context(context["config"]))
    context["request"] = request
    context["extension_error_codes"] = {}
    for artifact in result["artifacts"]:
        context["artifact_records"][artifact["artifact_ref"]["sha256"]] = {
            "ref": deepcopy(artifact["artifact_ref"]),
            "media_type": artifact["media_type"],
            "byte_count": artifact["byte_count"],
            "content_digest": artifact["content_digest"],
        }
    if port == "managed-provider-runner-port-v1" and operation == "run_status":
        context["normalized_event_artifact_bindings"] = [
            {
                "artifact_ref": deepcopy(item["artifact_ref"]),
                "role": item["role"],
                "media_type": item["media_type"],
                "omissions_ref": deepcopy(item["omissions_ref"]),
            }
            for item in result["artifacts"]
        ]
    if port == "tool-port-v1" and operation == "invoke_tool":
        bindings = [
            {
                "artifact_ref": deepcopy(item["artifact_ref"]),
                "role": item["role"],
                "media_type": item["media_type"],
                "omissions_ref": deepcopy(item["omissions_ref"]),
            }
            for item in result["artifacts"]
        ]
        context["tool_result_artifact_bindings"] = bindings
        context["tool_definition"]["artifact_output_contract"] = {
            "min_items": len(bindings),
            "max_items": len(bindings),
            "roles": [{
                "role": "tool_output",
                "allowed_media_types": ["text/plain"],
                "omissions_policy": "optional",
            }],
        }
    if port == "artifact-codec-port-v1" and operation == "decode_projection":
        context["target_projection_media_type"] = result["artifacts"][0]["media_type"]
    if port == "export-sink-port-v1" and operation == "transmit":
        context["transmit_effect_class"] = result["effect"]["effect_class"]
    return request, result, context


@pytest.mark.parametrize("field,bad_value", (
    ("config", None),
    ("config", []),
    ("request", None),
    ("request", []),
    ("artifact_records", None),
    ("artifact_records", []),
))
def test_result_context_rejects_explicit_null_and_wrong_common_types(field, bad_value):
    _, result, context = _complete_result_case("provider-port-v1", "catalog")
    validate_port_payload("provider-port-v1", "result", result, context=context)
    context[field] = bad_value

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("provider-port-v1", "result", result, context=context)


@pytest.mark.parametrize("mutation", (
    lambda context: context["binding_revision_record"].update(state="inactive"),
    lambda context: context["actor_record"].update(authenticated=False),
    lambda context: context["config"].pop("resource_limits"),
    lambda context: context["request"].update(operation="status"),
    lambda context: context.update(validated_at=None),
    lambda context: context.update(accepted_at=None),
))
def test_result_context_rechecks_complete_config_request_and_trusted_records(mutation):
    _, result, context = _complete_result_case("provider-port-v1", "catalog")
    validate_port_payload("provider-port-v1", "result", result, context=context)
    mutation(context)

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("provider-port-v1", "result", result, context=context)


def test_storage_result_requires_exact_durable_artifact_metadata_and_bounds():
    _, result, context = _complete_result_case("storage-port-v1", "read")
    validate_port_payload("storage-port-v1", "result", result, context=context)

    digest = result["artifacts"][0]["artifact_ref"]["sha256"]
    wrong_metadata = deepcopy(context)
    wrong_metadata["artifact_records"][digest]["content_digest"] = "f" * 64
    with pytest.raises(PortSchemaValidationError, match="durable Artifact"):
        validate_port_payload(
            "storage-port-v1", "result", result, context=wrong_metadata,
        )

    over_bound = deepcopy(context)
    over_bound["config"]["resource_limits"]["max_artifact_bytes"] = 1
    over_bound["artifact_records"][digest]["byte_count"] = 2
    over_bound["request"]["idempotency_key"] = _request_digest(over_bound["request"])
    oversized = deepcopy(result)
    oversized["artifacts"][0]["byte_count"] = 2
    with pytest.raises(PortSchemaValidationError, match="config limits"):
        validate_port_payload(
            "storage-port-v1", "result", oversized, context=over_bound,
        )


def test_runner_result_requires_present_ordered_event_bindings_even_when_empty():
    _, result, context = _complete_result_case(
        "managed-provider-runner-port-v1", "run_status",
    )
    assert context["normalized_event_artifact_bindings"] == []
    assert context["artifact_records"] == {}
    validate_port_payload(
        "managed-provider-runner-port-v1", "result", result, context=context,
    )
    context.pop("normalized_event_artifact_bindings")

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload(
            "managed-provider-runner-port-v1", "result", result, context=context,
        )
    malformed = _complete_result_case(
        "managed-provider-runner-port-v1", "run_status",
    )[2]
    malformed["normalized_event_artifact_bindings"] = {}
    with pytest.raises(PortSchemaValidationError):
        validate_port_payload(
            "managed-provider-runner-port-v1", "result", result, context=malformed,
        )


def test_tool_result_requires_present_sealed_bindings_and_output_contract_when_empty():
    _, result, context = _complete_result_case("tool-port-v1", "invoke_tool")
    assert context["tool_result_artifact_bindings"] == []
    assert context["artifact_records"] == {}
    validate_port_payload("tool-port-v1", "result", result, context=context)

    missing_bindings = deepcopy(context)
    missing_bindings.pop("tool_result_artifact_bindings")
    with pytest.raises(PortSchemaValidationError):
        validate_port_payload(
            "tool-port-v1", "result", result, context=missing_bindings,
        )

    missing_contract = deepcopy(context)
    missing_contract["tool_definition"].pop("artifact_output_contract")
    with pytest.raises(PortSchemaValidationError, match="output artifact contract"):
        validate_port_payload(
            "tool-port-v1", "result", result, context=missing_contract,
        )

    malformed_bindings = deepcopy(context)
    malformed_bindings["tool_result_artifact_bindings"] = [{}]
    with pytest.raises(PortSchemaValidationError):
        validate_port_payload(
            "tool-port-v1", "result", result, context=malformed_bindings,
        )

    wrong_binding_type = deepcopy(context)
    wrong_binding_type["tool_definition"]["artifact_output_contract"]["max_items"] = 1
    wrong_binding_type["tool_result_artifact_bindings"] = [{
        "artifact_ref": _ref("artifact", marker="b"),
        "role": [], "media_type": "text/plain", "omissions_ref": None,
    }]
    with pytest.raises(PortSchemaValidationError):
        validate_port_payload(
            "tool-port-v1", "result", result, context=wrong_binding_type,
        )

    wrong_contract_type = deepcopy(context)
    wrong_contract_type["tool_definition"]["artifact_output_contract"]["roles"][0][
        "allowed_media_types"
    ] = [{}]
    with pytest.raises(PortSchemaValidationError):
        validate_port_payload(
            "tool-port-v1", "result", result, context=wrong_contract_type,
        )


def test_codec_result_requires_resolved_decode_media_and_request_target_media():
    for operation in ("decode_projection", "render_preview", "encode"):
        _, result, context = _complete_result_case("artifact-codec-port-v1", operation)
        validate_port_payload(
            "artifact-codec-port-v1", "result", result, context=context,
        )
        if operation == "decode_projection":
            context.pop("target_projection_media_type")
        else:
            context["request"]["input"]["target_media_type"] = "application/json"
            context["request"]["idempotency_key"] = _request_digest(context["request"])
        with pytest.raises(PortSchemaValidationError, match="media"):
            validate_port_payload(
                "artifact-codec-port-v1", "result", result, context=context,
            )


def test_export_transmit_result_requires_frozen_target_effect_class():
    _, result, context = _complete_result_case("export-sink-port-v1", "transmit")
    validate_port_payload("export-sink-port-v1", "result", result, context=context)
    context.pop("transmit_effect_class")

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("export-sink-port-v1", "result", result, context=context)


@pytest.mark.parametrize("bad_value", (None, [], "not-a-map"))
def test_non_success_result_requires_manifest_frozen_error_context(bad_value):
    _, result, context = _complete_result_case("tool-port-v1", "invoke_tool", "failed")
    validate_port_payload("tool-port-v1", "result", result, context=context)
    if bad_value is None:
        context.pop("extension_error_codes")
    else:
        context["extension_error_codes"] = bad_value

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("tool-port-v1", "result", result, context=context)


def test_result_context_preserves_prior_frozen_refinements_while_rechecking_core_shape():
    _, result, context = _complete_result_case("provider-port-v1", "catalog")
    context["config"]["extension_config"] = {"fixture_mode": "bounded"}
    context["request"]["extension_input"] = {"fixture_mode": "bounded"}
    context["request"]["idempotency_key"] = _request_digest(context["request"])

    validate_port_payload("provider-port-v1", "result", result, context=context)


def _complete_custom_bounded_tool_result() -> tuple[dict, dict]:
    request = _request_instance("tool-port-v1", "invoke_tool")
    request["input"]["tool_id"] = "custom_tool"
    request["artifact_inputs"] = [_artifact_input("custom_input")]
    request["idempotency_key"] = _request_digest(request)
    result = _result_instance("tool-port-v1", "invoke_tool", "succeeded")
    result["request_id"] = request["request_id"]
    result["effect"] = _effect_for(request["input"]["expected_effect_class"], "succeeded")
    context = _request_context("tool-port-v1", request)
    context.update(_config_context(context["config"]))
    context.update({
        "request": request,
        "extension_error_codes": {},
        "tool_result_artifact_bindings": [],
    })
    context["tool_definition"]["artifact_input_contract"] = {
        "mode": "bounded",
        "min_items": 1,
        "max_items": 1,
        "role": "custom_input",
        "allowed_media_types": ["text/plain"],
        "selector_policy": "forbidden",
    }
    context["tool_definition"]["artifact_output_contract"] = {
        "min_items": 0,
        "max_items": 0,
        "roles": [{
            "role": "tool_output",
            "allowed_media_types": ["text/plain"],
            "omissions_policy": "optional",
        }],
    }
    return result, context


def test_result_context_rejects_wrong_actor_type_without_leaking_type_error():
    _, result, context = _complete_result_case("provider-port-v1", "catalog")
    validate_port_payload("provider-port-v1", "result", result, context=context)
    context["actor_record"]["actor_type"] = []

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("provider-port-v1", "result", result, context=context)


@pytest.mark.parametrize("field,bad_value", (
    ("role", [1]),
    ("allowed_media_types", [{}]),
    ("selector_policy", []),
))
def test_result_context_rejects_malformed_custom_tool_input_contract(field, bad_value):
    result, context = _complete_custom_bounded_tool_result()
    validate_port_payload("tool-port-v1", "result", result, context=context)
    context["tool_definition"]["artifact_input_contract"][field] = bad_value

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("tool-port-v1", "result", result, context=context)


def test_result_context_rejects_nonstring_tool_id_before_contract_lookup():
    result, context = _complete_custom_bounded_tool_result()
    validate_port_payload("tool-port-v1", "result", result, context=context)
    context["tool_definition"]["tool_id"] = []

    with pytest.raises(PortSchemaValidationError, match="does not match ToolDefinition"):
        validate_port_payload("tool-port-v1", "result", result, context=context)


@pytest.mark.parametrize("bad_kind", ([], {}))
def test_result_context_rejects_malformed_ref_shaped_tool_arguments(bad_kind):
    result, context = _complete_custom_bounded_tool_result()
    validate_port_payload("tool-port-v1", "result", result, context=context)
    context["resolved_arguments"] = {
        "payload": {
            "kind": bad_kind,
            "id": "x",
            "version": 1,
            "sha256": "a" * 64,
        },
    }

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("tool-port-v1", "result", result, context=context)


def _overdeep_tool_arguments() -> dict:
    value: dict = {"leaf": "x"}
    for _ in range(32):
        value = {"nested": value}
    return value


@pytest.mark.parametrize("bad_arguments", (
    {"payload": 1.5},
    {"payload": "x" * 65_537},
    _overdeep_tool_arguments(),
    {"payload": ["x" * 4096] * 256},
))
def test_result_context_bounds_resolved_tool_arguments_as_safe_json(bad_arguments):
    result, context = _complete_custom_bounded_tool_result()
    validate_port_payload("tool-port-v1", "result", result, context=context)
    context["resolved_arguments"] = bad_arguments

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("tool-port-v1", "result", result, context=context)


def test_result_context_scans_tuple_projection_for_hidden_artifact_ref():
    result, context = _complete_custom_bounded_tool_result()
    validate_port_payload("tool-port-v1", "result", result, context=context)
    context["resolved_arguments"] = {"payload": (_ref("artifact"),)}

    with pytest.raises(PortSchemaValidationError, match="hidden artifact"):
        validate_port_payload("tool-port-v1", "result", result, context=context)


def test_resolved_tool_arguments_do_not_inherit_port_envelope_field_semantics():
    result, context = _complete_custom_bounded_tool_result()
    context["resolved_arguments"] = {
        "api_origin": "ordinary argument, not a URI",
        "started_at": "ordinary argument, not a timestamp",
        "version": "e\u0301",
        "payload": "x" * 4097,
    }

    validate_port_payload("tool-port-v1", "result", result, context=context)


@pytest.mark.parametrize("stored_field,bad_value", (
    ("byte_count", True),
    ("byte_count", 1.0),
    ("size", True),
    ("size", 1.0),
))
def test_result_artifact_rejects_non_integer_durable_size(stored_field, bad_value):
    _, result, context = _complete_result_case("storage-port-v1", "read")
    result["artifacts"][0]["byte_count"] = 1
    digest = result["artifacts"][0]["artifact_ref"]["sha256"]
    record = context["artifact_records"][digest]
    record.pop("byte_count", None)
    record[stored_field] = 1
    validate_port_payload("storage-port-v1", "result", result, context=context)
    record[stored_field] = bad_value

    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("storage-port-v1", "result", result, context=context)


def _install_variable_result_artifacts(port: str, operation: str, result: dict,
                                       context: dict) -> list[dict]:
    schema = generate_port_schemas()[(port, "result")]
    branch = next(
        item for item in schema["oneOf"]
        if item["properties"]["operation"]["const"] == operation
        and item["properties"]["terminal"]["const"] == "succeeded"
    )
    artifacts = []
    for index, marker in enumerate(("e", "f"), start=1):
        artifact = _minimal(branch["properties"]["artifacts"]["items"])
        artifact["artifact_ref"] = _ref("artifact", marker=marker)
        artifact["byte_count"] = index
        artifact["content_digest"] = str(index) * 64
        artifact["media_type"] = "text/plain"
        artifact["omissions_ref"] = None
        if port == "tool-port-v1":
            artifact["role"] = "tool_output"
        artifacts.append(artifact)
        context["artifact_records"][artifact["artifact_ref"]["sha256"]] = {
            "ref": deepcopy(artifact["artifact_ref"]),
            "media_type": artifact["media_type"],
            "byte_count": artifact["byte_count"],
            "content_digest": artifact["content_digest"],
        }
    result["artifacts"] = artifacts
    return [{
        "artifact_ref": deepcopy(item["artifact_ref"]),
        "role": item["role"],
        "media_type": item["media_type"],
        "omissions_ref": None,
    } for item in artifacts]


@pytest.mark.parametrize("port,operation,binding_field", (
    (
        "managed-provider-runner-port-v1",
        "run_status",
        "normalized_event_artifact_bindings",
    ),
    ("tool-port-v1", "invoke_tool", "tool_result_artifact_bindings"),
))
def test_nonempty_result_bindings_preserve_exact_order(port, operation, binding_field):
    _, result, context = _complete_result_case(port, operation)
    bindings = _install_variable_result_artifacts(port, operation, result, context)
    context[binding_field] = bindings
    if port == "tool-port-v1":
        context["tool_definition"]["artifact_output_contract"].update(
            min_items=2, max_items=2,
        )
    validate_port_payload(port, "result", result, context=context)
    context[binding_field] = list(reversed(bindings))

    with pytest.raises(PortSchemaValidationError, match="sealed artifact bindings"):
        validate_port_payload(port, "result", result, context=context)
