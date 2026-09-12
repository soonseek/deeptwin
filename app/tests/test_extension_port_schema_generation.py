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
        "provider-port-v1", "config", config, refinement_schema=refinement,
    )
    wrong = deepcopy(config)
    wrong["extension_config"]["temperature"] = 3
    with pytest.raises(PortSchemaValidationError, match="refinement rejected"):
        validate_port_payload(
            "provider-port-v1", "config", wrong, refinement_schema=refinement,
        )
    with pytest.raises(PortSchemaValidationError, match="without a frozen refinement"):
        validate_port_payload("provider-port-v1", "config", config)
    replaced = deepcopy(config)
    replaced["schema_version"] = 2
    with pytest.raises(PortSchemaValidationError, match="base schema rejected"):
        validate_port_payload(
            "provider-port-v1", "config", replaced, refinement_schema=refinement,
        )


def test_extension_error_code_requires_the_manifest_frozen_operation_enum():
    error = _error_instance("tool-port-v1", "invoke_tool")
    error["code"] = "port_specific_failure"
    error["port_error_code"] = "execution_failed"
    error["extension_error_code"] = "vendor_failure"
    with pytest.raises(PortSchemaValidationError, match="manifest-frozen"):
        validate_port_payload("tool-port-v1", "error", error)
    validate_port_payload(
        "tool-port-v1", "error", error,
        context={"extension_error_codes": {"invoke_tool": ["vendor_failure"]}},
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
        validate_port_payload("provider-port-v1", "config", valid)
    valid["binding_slot_key_digest"] = _slot_digest(valid["binding_slot_key"])
    validate_port_payload("provider-port-v1", "config", valid)
    wrong = deepcopy(valid)
    wrong["binding_slot_key"]["port_contract_version"] = "tool-port-v1"
    wrong["binding_slot_key_digest"] = _slot_digest(wrong["binding_slot_key"])
    with pytest.raises(PortSchemaValidationError):
        validate_port_payload("provider-port-v1", "config", wrong)


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
    with pytest.raises(PortSchemaValidationError, match="frozen source list"):
        validate_port_payload(
            "provider-port-v1", "request", provider,
            context={"expected_artifact_inputs": [_artifact_input("model_input", marker="b")]},
        )

    tool = _request_instance("tool-port-v1", "invoke_tool")
    with pytest.raises(PortSchemaValidationError, match="hidden artifact"):
        validate_port_payload(
            "tool-port-v1", "request", tool,
            context={
                "tool_definition": {
                    "tool_id": tool["input"]["tool_id"],
                    "version": tool["input"]["tool_version"],
                    "artifact_input_contract": {"mode": "none"},
                },
                "resolved_arguments": {"nested": {"artifact": _ref("artifact")}},
            },
        )


def test_semantic_validator_enforces_builtin_tool_profiles_and_export_exact_list():
    request = _request_instance("tool-port-v1", "invoke_tool")
    request["input"]["tool_id"] = "browser_upload"
    request["artifact_inputs"] = [_artifact_input("browser_upload")]
    request["idempotency_key"] = _request_digest(request)
    widened = {
        "tool_id": "browser_upload", "version": request["input"]["tool_version"],
        "artifact_input_contract": {
            "mode": "bounded", "min_items": 0, "max_items": 32,
            "role": "browser_upload", "allowed_media_types": ["text/plain"],
            "selector_policy": "optional",
        },
    }
    with pytest.raises(PortSchemaValidationError, match="widened or changed"):
        validate_port_payload(
            "tool-port-v1", "request", request,
            context={"tool_definition": widened},
        )

    export = _request_instance("export-sink-port-v1", "transmit")
    with pytest.raises(PortSchemaValidationError, match="frozen source list"):
        validate_port_payload(
            "export-sink-port-v1", "request", export,
            context={"expected_artifact_inputs": [_artifact_input("export_payload", marker="b")]},
        )


def test_result_lineage_enforces_codec_refs_media_omissions_and_tool_bindings():
    request = _request_instance("artifact-codec-port-v1", "render_preview")
    result = _result_instance("artifact-codec-port-v1", "render_preview", "succeeded")
    result["request_id"] = request["request_id"]
    result["artifacts"][0]["media_type"] = request["input"]["target_media_type"]
    validate_port_payload(
        "artifact-codec-port-v1", "result", result, context={"request": request},
    )
    wrong = deepcopy(result)
    wrong["artifacts"][0]["omissions_ref"] = _ref("omissions", marker="b")
    with pytest.raises(PortSchemaValidationError, match="omissions"):
        validate_port_payload(
            "artifact-codec-port-v1", "result", wrong, context={"request": request},
        )

    tool_request = _request_instance("tool-port-v1", "invoke_tool")
    tool_request["input"]["expected_effect_class"] = "read"
    tool_request["idempotency_key"] = _request_digest(tool_request)
    tool_result = _result_instance("tool-port-v1", "invoke_tool", "succeeded")
    tool_result["request_id"] = tool_request["request_id"]
    tool_result["effect"] = _effect_for("read", "succeeded")
    with pytest.raises(PortSchemaValidationError, match="sealed artifact bindings"):
        validate_port_payload(
            "tool-port-v1", "result", tool_result,
            context={
                "request": tool_request,
                "tool_result_artifact_bindings": [{
                    "artifact_ref": _ref("artifact", marker="b"),
                    "role": "tool_output", "media_type": "text/plain",
                    "omissions_ref": None,
                }],
            },
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
