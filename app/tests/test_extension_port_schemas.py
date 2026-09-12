"""T087-A0 tests for the immutable semantic extension-port contract kernel.

This slice deliberately tests the source catalog only.  It does not claim that the 44
JSON Schema artifacts, persistence, HTTP routes, or broker integration exist yet.
"""

from __future__ import annotations

import ast
import inspect
from collections import Counter
from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

from app.domain.refs import canonical_json
from app.extensions import port_contracts as subject
from app.extensions.port_contracts import (
    ALLOWED_EFFECT_TUPLES,
    ALLOWED_TERMINAL_CANDIDATES,
    BINDING_SLOT_KEY_FIELDS,
    EFFECT_CLASSES,
    ERROR_FIELDS,
    OPERATION_CONTRACTS,
    PORT_CONTRACTS,
    PORT_SCHEMA_IDS,
    REJECTED_TERMINAL_CANDIDATES,
    RESULT_ARTIFACT_CONTRACTS,
    RESULT_EFFECT_FIELDS,
    TERMINAL_CANDIDATES,
    BindingSlotKeyV1,
    PortContractError,
    effect_tuple_allowed,
    operation_contract,
    validate_port_tuple,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


EXPECTED_OPERATIONS = {
    "provider-port-v1": (
        "capabilities", "catalog", "model_step", "status", "cancel",
    ),
    "managed-provider-runner-port-v1": (
        "preflight", "device_auth_start", "device_auth_status", "device_auth_cancel",
        "run_start", "run_status", "run_cancel",
    ),
    "model-runtime-port-v1": (
        "capabilities", "model_step", "status", "cancel",
    ),
    "tool-port-v1": ("describe_tools", "invoke_tool", "status", "cancel"),
    "artifact-codec-port-v1": (
        "probe", "decode_projection", "render_preview", "encode", "cancel",
    ),
    "lens-definition-port-v1": (
        "validate_definition", "compose", "apply_decision",
    ),
    "evaluator-definition-port-v1": (
        "describe_rubric", "evaluate", "abstain",
    ),
    "evaluator-runtime-port-v1": (
        "describe_rubric", "evaluate", "abstain", "status", "cancel",
    ),
    "storage-port-v1": (
        "capabilities", "health", "migrate_plan", "read", "write_cas",
    ),
    "credential-vault-port-v1": (
        "capabilities", "health", "store", "resolve_for_gateway", "retire", "erase",
    ),
    "export-sink-port-v1": (
        "capabilities", "prepare", "transmit", "status", "cancel",
    ),
}


EXPECTED_PORT_MATRIX = {
    "provider-port-v1": (
        "provider", "oci_extension_service", "runtime_worker", {"deployment_operator"},
    ),
    "managed-provider-runner-port-v1": (
        "provider", "release_pinned_oci_service", "managed_provider_runner",
        {"deployment_operator"},
    ),
    "model-runtime-port-v1": (
        "model_runtime", "oci_extension_service", "runtime_worker",
        {"deployment_operator"},
    ),
    "tool-port-v1": (
        "tool", "oci_extension_service", "runtime_worker", {"deployment_operator"},
    ),
    "artifact-codec-port-v1": (
        "artifact_codec", "oci_extension_service", "runtime_worker",
        {"deployment_operator"},
    ),
    "lens-definition-port-v1": (
        "lens", "code_free_definition", "definition_package",
        {"product_owner", "deployment_operator"},
    ),
    "evaluator-definition-port-v1": (
        "evaluator", "code_free_definition", "definition_package",
        {"product_owner", "deployment_operator"},
    ),
    "evaluator-runtime-port-v1": (
        "evaluator", "oci_extension_service", "runtime_worker",
        {"deployment_operator"},
    ),
    "storage-port-v1": (
        "storage", "deployment_pinned_oci_service", "deployment_trusted",
        {"deployment_operator"},
    ),
    "credential-vault-port-v1": (
        "credential_vault", "deployment_pinned_oci_service", "deployment_trusted",
        {"deployment_operator"},
    ),
    "export-sink-port-v1": (
        "export_sink", "oci_extension_service", "runtime_worker",
        {"deployment_operator"},
    ),
}


def binding_key_mapping(**changes):
    value = {
        "port_contract_version": "tool-port-v1",
        "target_scope_fingerprint": HASH_A,
        "purpose": "operational",
        "binding_slot_id": "graph.browser-read",
        "capability_selector_digest": HASH_B,
    }
    value.update(changes)
    return value


def test_catalog_has_exact_eleven_closed_port_tuples_and_operations():
    assert set(PORT_CONTRACTS) == set(EXPECTED_PORT_MATRIX)
    assert len(PORT_CONTRACTS) == 11
    for port, expected in EXPECTED_PORT_MATRIX.items():
        contract = PORT_CONTRACTS[port]
        assert (
            contract.extension_kind,
            contract.artifact_form,
            contract.trust_tier,
            set(contract.staging_authorities),
        ) == expected
        assert contract.operations == EXPECTED_OPERATIONS[port]


def test_only_exact_port_tuple_is_accepted_and_wrong_semantic_ports_fail_closed():
    for port, expected in EXPECTED_PORT_MATRIX.items():
        kind, artifact, trust, authorities = expected
        for authority in authorities:
            assert validate_port_tuple(
                extension_kind=kind,
                artifact_form=artifact,
                port_contract_version=port,
                trust_tier=trust,
                staging_authority=authority,
            ) is PORT_CONTRACTS[port]

    wrong = [
        ("tool", "oci_extension_service", "storage-port-v1", "runtime_worker",
         "deployment_operator"),
        ("provider", "oci_extension_service", "managed-provider-runner-port-v1",
         "runtime_worker", "deployment_operator"),
        ("lens", "oci_extension_service", "lens-definition-port-v1", "runtime_worker",
         "deployment_operator"),
        ("storage", "deployment_pinned_oci_service", "storage-port-v1",
         "deployment_trusted", "product_owner"),
    ]
    for kind, artifact, port, trust, authority in wrong:
        with pytest.raises(PortContractError):
            validate_port_tuple(
                extension_kind=kind,
                artifact_form=artifact,
                port_contract_version=port,
                trust_tier=trust,
                staging_authority=authority,
            )


def test_schema_identifier_catalog_is_exact_unique_https_set_of_44():
    assert len(PORT_SCHEMA_IDS) == 44
    assert len(set(PORT_SCHEMA_IDS.values())) == 44
    assert {shape for _, shape in PORT_SCHEMA_IDS} == {
        "config", "request", "result", "error",
    }
    for (port, shape), identifier in PORT_SCHEMA_IDS.items():
        assert identifier == (
            f"https://deeptwin.local/schemas/v1/extensions/ports/"
            f"{port}/{shape}.schema.json"
        )


def test_operation_catalog_is_port_qualified_exhaustive_and_unique():
    assert len(OPERATION_CONTRACTS) == 52
    assert set(OPERATION_CONTRACTS) == {
        (port, operation)
        for port, operations in EXPECTED_OPERATIONS.items()
        for operation in operations
    }
    assert operation_contract("provider-port-v1", "status") \
        is not operation_contract("tool-port-v1", "status")
    with pytest.raises(PortContractError):
        operation_contract("tool-port-v1", "model_step")


def test_terminal_partition_enumerates_208_candidates_as_127_allowed_81_rejected():
    assert Counter(value.terminal_class for value in OPERATION_CONTRACTS.values()) == {
        "Q": 37, "C": 8, "M": 7,
    }
    assert len(TERMINAL_CANDIDATES) == 208
    assert len(set(TERMINAL_CANDIDATES)) == 208
    assert len(ALLOWED_TERMINAL_CANDIDATES) == 127
    assert len(REJECTED_TERMINAL_CANDIDATES) == 81
    assert ALLOWED_TERMINAL_CANDIDATES.isdisjoint(REJECTED_TERMINAL_CANDIDATES)
    assert ALLOWED_TERMINAL_CANDIDATES | REJECTED_TERMINAL_CANDIDATES \
        == frozenset(TERMINAL_CANDIDATES)


def test_terminal_class_assignment_is_exact_for_every_port_qualified_operation():
    cancellable = {
        ("provider-port-v1", "model_step"),
        ("model-runtime-port-v1", "model_step"),
        ("tool-port-v1", "invoke_tool"),
        ("artifact-codec-port-v1", "decode_projection"),
        ("artifact-codec-port-v1", "render_preview"),
        ("artifact-codec-port-v1", "encode"),
        ("evaluator-runtime-port-v1", "evaluate"),
        ("export-sink-port-v1", "transmit"),
    }
    mutating = {
        ("managed-provider-runner-port-v1", "device_auth_start"),
        ("managed-provider-runner-port-v1", "run_start"),
        ("storage-port-v1", "write_cas"),
        ("credential-vault-port-v1", "store"),
        ("credential-vault-port-v1", "resolve_for_gateway"),
        ("credential-vault-port-v1", "retire"),
        ("credential-vault-port-v1", "erase"),
    }
    expected = {
        key: "C" if key in cancellable else "M" if key in mutating else "Q"
        for key in OPERATION_CONTRACTS
    }
    assert {
        key: value.terminal_class for key, value in OPERATION_CONTRACTS.items()
    } == expected


def test_request_artifact_profiles_partition_52_as_11_and_41():
    expected_nonempty = {
        ("provider-port-v1", "model_step"): "F-model",
        ("managed-provider-runner-port-v1", "run_start"): "F-runner",
        ("model-runtime-port-v1", "model_step"): "F-model",
        ("tool-port-v1", "invoke_tool"): "T-tool",
        ("artifact-codec-port-v1", "probe"): "C-one",
        ("artifact-codec-port-v1", "decode_projection"): "C-one-selected",
        ("artifact-codec-port-v1", "render_preview"): "C-one-selected",
        ("artifact-codec-port-v1", "encode"): "C-many",
        ("storage-port-v1", "write_cas"): "S-one",
        ("export-sink-port-v1", "prepare"): "X-export-prepare",
        ("export-sink-port-v1", "transmit"): "X-export-transmit",
    }
    observed = {
        key: value.request_artifact_profile
        for key, value in OPERATION_CONTRACTS.items()
        if value.request_artifact_profile != "E"
    }
    assert observed == expected_nonempty
    assert Counter(
        value.request_artifact_profile == "E" for value in OPERATION_CONTRACTS.values()
    ) == {True: 41, False: 11}


def test_export_profiles_require_exact_bounded_stream_and_never_grant_result_artifacts():
    prepare = operation_contract("export-sink-port-v1", "prepare")
    transmit = operation_contract("export-sink-port-v1", "transmit")
    assert prepare.request_artifact_profile == "X-export-prepare"
    assert transmit.request_artifact_profile == "X-export-transmit"
    for contract, source in ((prepare, "export_snapshot"),
                             (transmit, "prepared_delivery")):
        profile = subject.REQUEST_ARTIFACT_PROFILES[contract.request_artifact_profile]
        assert (profile.min_items, profile.max_items) == (1, 256)
        assert profile.role == "export_payload"
        assert profile.selector_policy == "forbidden"
        assert profile.list_source == source
        assert profile.exact_order is True
        assert profile.requires_bounded_stream is True
        assert profile.ref_only_allowed is False
        assert profile.shared_store_allowed is False
        assert contract.result_artifact_mode == "E"
        assert contract.result_artifact_metadata == "none"
    assert transmit.request_target_source == "prepared_delivery"


def test_result_artifact_modes_and_metadata_sources_are_exact():
    expected = {
        ("provider-port-v1", "model_step"): ("V", "model_content"),
        ("managed-provider-runner-port-v1", "run_status"): ("V", "runner_artifact"),
        ("model-runtime-port-v1", "model_step"): ("V", "model_content"),
        ("tool-port-v1", "invoke_tool"): ("V", "tool_result"),
        ("artifact-codec-port-v1", "decode_projection"): ("O", "decoded_projection"),
        ("artifact-codec-port-v1", "render_preview"): ("O", "render_preview"),
        ("artifact-codec-port-v1", "encode"): ("O", "encoded_output"),
        ("storage-port-v1", "read"): ("O", "storage_object"),
    }
    observed = {
        key: (value.result_artifact_mode, value.result_artifact_metadata)
        for key, value in OPERATION_CONTRACTS.items()
        if value.result_artifact_mode != "E"
    }
    assert observed == expected
    assert Counter(value.result_artifact_mode for value in OPERATION_CONTRACTS.values()) == {
        "E": 44, "V": 4, "O": 4,
    }
    assert {
        name: (
            metadata.role, metadata.binding_source, metadata.media_source,
            metadata.omissions_source,
        )
        for name, metadata in subject.RESULT_ARTIFACT_METADATA.items()
    } == {
        "none": (None, "none", "none", "none"),
        "model_content": (
            "model_content", "output.content_block_refs", "durable_artifact.media_type", "null",
        ),
        "runner_artifact": (
            "runner_artifact", "output.normalized_event_refs[*].artifact_ref",
            "normalized_event.media_type", "normalized_event.omissions_ref",
        ),
        "tool_result": (
            None, "output.result_ref.ToolResultArtifactBindingV1[]",
            "binding.media_type", "binding.omissions_ref",
        ),
        "decoded_projection": (
            "decoded_projection", "output.projection_artifact_ref",
            "input.target_projection_schema_ref.media_type", "output.omissions_ref",
        ),
        "render_preview": (
            "render_preview", "output.preview_artifact_ref", "input.target_media_type",
            "output.omissions_ref",
        ),
        "encoded_output": (
            "encoded_output", "output.encoded_artifact_ref", "input.target_media_type",
            "output.omissions_ref",
        ),
        "storage_object": (
            "storage_object", "output.object_artifact_ref", "durable_artifact.media_type", "null",
        ),
    }


def test_every_allowed_non_success_result_has_empty_artifacts():
    assert len(RESULT_ARTIFACT_CONTRACTS) == 127
    assert Counter(mode for mode, _ in RESULT_ARTIFACT_CONTRACTS.values()) == {
        "E": 119, "V": 4, "O": 4,
    }
    assert all(
        result_contract == ("E", "none")
        for (*_, terminal), result_contract in RESULT_ARTIFACT_CONTRACTS.items()
        if terminal != "succeeded"
    )


def test_effect_assignments_cover_every_operation_exactly_once():
    sources = Counter(value.effect_source for value in OPERATION_CONTRACTS.values())
    assert sources == {
        "literal_none": 8,
        "literal_read": 24,
        "literal_write_reversible": 9,
        "literal_external": 9,
        "tool_definition": 1,
        "export_destination": 1,
    }
    tool = operation_contract("tool-port-v1", "invoke_tool")
    assert tool.allowed_effect_classes == EFFECT_CLASSES
    export = operation_contract("export-sink-port-v1", "transmit")
    assert export.allowed_effect_classes == frozenset({
        "external_reversible", "external_irreversible",
    })
    assert operation_contract("export-sink-port-v1", "prepare").allowed_effect_classes \
        == frozenset({"read"})


def test_literal_effect_assignments_are_exact_per_port_qualified_operation():
    none_operations = {
        ("provider-port-v1", "cancel"),
        ("managed-provider-runner-port-v1", "device_auth_cancel"),
        ("managed-provider-runner-port-v1", "run_cancel"),
        ("model-runtime-port-v1", "cancel"),
        ("tool-port-v1", "cancel"),
        ("artifact-codec-port-v1", "cancel"),
        ("evaluator-runtime-port-v1", "cancel"),
        ("export-sink-port-v1", "cancel"),
    }
    reversible_operations = {
        ("artifact-codec-port-v1", "decode_projection"),
        ("artifact-codec-port-v1", "render_preview"),
        ("artifact-codec-port-v1", "encode"),
        ("lens-definition-port-v1", "compose"),
        ("lens-definition-port-v1", "apply_decision"),
        ("evaluator-definition-port-v1", "evaluate"),
        ("evaluator-definition-port-v1", "abstain"),
        ("evaluator-runtime-port-v1", "evaluate"),
        ("evaluator-runtime-port-v1", "abstain"),
    }
    exact_external = {
        ("provider-port-v1", "model_step"): "external_irreversible",
        ("managed-provider-runner-port-v1", "run_start"): "external_irreversible",
        ("model-runtime-port-v1", "model_step"): "external_irreversible",
        ("managed-provider-runner-port-v1", "device_auth_start"): "external_reversible",
        ("storage-port-v1", "write_cas"): "instance_critical_storage",
        ("credential-vault-port-v1", "store"): "instance_critical_secret",
        ("credential-vault-port-v1", "resolve_for_gateway"): "instance_critical_secret",
        ("credential-vault-port-v1", "retire"): "instance_critical_secret",
        ("credential-vault-port-v1", "erase"): "instance_critical_secret",
    }
    dynamic = {
        ("tool-port-v1", "invoke_tool"),
        ("export-sink-port-v1", "transmit"),
    }
    for key, contract in OPERATION_CONTRACTS.items():
        if key in none_operations:
            expected = frozenset({"none"})
        elif key in reversible_operations:
            expected = frozenset({"write_reversible"})
        elif key in exact_external:
            expected = frozenset({exact_external[key]})
        elif key in dynamic:
            continue
        else:
            expected = frozenset({"read"})
        assert contract.allowed_effect_classes == expected


def test_effect_tuple_table_is_exhaustive_with_25_symbolic_concrete_rows():
    expected_counts = {
        ("succeeded", "N"): 1, ("failed", "N"): 1,
        ("cancelled", "N"): 1, ("unknown", "N"): 0,
        ("succeeded", "L"): 1, ("failed", "L"): 2,
        ("cancelled", "L"): 4, ("unknown", "L"): 1,
        ("succeeded", "X"): 1, ("failed", "X"): 2,
        ("cancelled", "X"): 7, ("unknown", "X"): 4,
    }
    assert {key: len(value) for key, value in ALLOWED_EFFECT_TUPLES.items()} \
        == expected_counts
    assert sum(len(value) for value in ALLOWED_EFFECT_TUPLES.values()) == 25
    assert effect_tuple_allowed(
        effect_class="external_irreversible", terminal="succeeded",
        effect_state="committed", receipt_presence="ref", remote_outcome="confirmed",
    )
    assert not effect_tuple_allowed(
        effect_class="external_irreversible", terminal="succeeded",
        effect_state="unknown", receipt_presence="ref", remote_outcome="unknown",
    )
    assert not effect_tuple_allowed(
        effect_class="read", terminal="unknown", effect_state="unknown",
        receipt_presence="null", remote_outcome="unknown",
    )


def test_result_is_the_only_effect_truth_and_error_shape_has_no_effect_fields():
    assert RESULT_EFFECT_FIELDS == frozenset({
        "effect_class", "effect_state", "effect_receipt_ref", "remote_outcome",
    })
    assert ERROR_FIELDS == frozenset({
        "schema_id", "schema_version", "port_contract_version", "request_id", "operation",
        "code", "port_error_code", "extension_error_code", "message_class", "retry_class",
        "affected_refs", "evidence_ref",
    })
    assert not ({"effect_state", "effect_receipt_ref", "remote_outcome"} & ERROR_FIELDS)


def test_binding_slot_key_is_exact_five_field_canonical_value():
    value = binding_key_mapping()
    key = BindingSlotKeyV1.from_mapping(value)
    assert BINDING_SLOT_KEY_FIELDS == frozenset(value)
    assert key.as_dict() == value
    assert key.digest == sha256(canonical_json(value)).hexdigest()
    returned = key.as_dict()
    returned["purpose"] = "changed"
    assert key.as_dict() == value
    with pytest.raises(FrozenInstanceError):
        key.purpose = "changed"
    with pytest.raises(TypeError):
        BindingSlotKeyV1()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("port_contract_version"),
        lambda value: value.update(extension_id="org.example.tool"),
        lambda value: value.update(port_contract_version="unknown-port-v1"),
        lambda value: value.update(target_scope_fingerprint="A" * 64),
        lambda value: value.update(capability_selector_digest="b" * 63),
        lambda value: value.update(purpose="1invalid"),
        lambda value: value.update(binding_slot_id="bad slot"),
        lambda value: value.update(binding_slot_id="a" * 129),
    ],
)
def test_binding_slot_key_rejects_four_field_extra_unknown_and_malformed_values(mutation):
    value = binding_key_mapping()
    mutation(value)
    with pytest.raises(PortContractError):
        BindingSlotKeyV1.from_mapping(value)


def test_binding_slot_key_rejects_sibling_version_and_digest_mismatch():
    value = binding_key_mapping()
    key = BindingSlotKeyV1.from_mapping(
        value,
        expected_port_contract_version="tool-port-v1",
        expected_digest=sha256(canonical_json(value)).hexdigest(),
    )
    assert key.port_contract_version == "tool-port-v1"
    with pytest.raises(PortContractError):
        BindingSlotKeyV1.from_mapping(
            value, expected_port_contract_version="provider-port-v1",
        )
    with pytest.raises(PortContractError):
        BindingSlotKeyV1.from_mapping(value, expected_digest="0" * 64)


def test_each_binding_slot_component_changes_the_canonical_digest():
    baseline = BindingSlotKeyV1.from_mapping(binding_key_mapping()).digest
    changes = {
        "port_contract_version": "provider-port-v1",
        "target_scope_fingerprint": "c" * 64,
        "purpose": "diagnosis",
        "binding_slot_id": "graph.browser-write",
        "capability_selector_digest": "d" * 64,
    }
    changed_digests = {
        BindingSlotKeyV1.from_mapping(binding_key_mapping(**{name: value})).digest
        for name, value in changes.items()
    }
    assert len(changed_digests) == 5
    assert baseline not in changed_digests
    assert all(
        BindingSlotKeyV1.from_mapping(binding_key_mapping(**{name: value})).digest != baseline
        for name, value in changes.items()
    )


def test_contract_kernel_has_no_io_framework_or_dynamic_import_dependency():
    tree = ast.parse(inspect.getsource(subject))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"__import__", "eval", "exec", "open"}
    assert imported.isdisjoint({
        "os", "pathlib", "sqlite3", "socket", "subprocess", "fastapi", "starlette",
        "httpx", "requests",
    })
