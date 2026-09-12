"""Immutable core-owned catalog for DeepTwin semantic extension ports.

This T087-A0 module is intentionally free of I/O, framework presentation code, persistence,
and worker dispatch.  It records the closed semantic identities that later schema generators,
runtime validators, and durable lifecycle code must consume.  Catalog membership alone grants
no installation, binding, artifact access, effect, or execution authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType

from ..domain.refs import canonical_json


class PortContractError(ValueError):
    """A value is outside the closed semantic extension-port contract."""


PORT_SCHEMA_SHAPES = ("config", "request", "result", "error")
TERMINALS = ("succeeded", "failed", "cancelled", "unknown")
TERMINAL_CLASSES = frozenset({"Q", "C", "M"})
REQUEST_ARTIFACT_PROFILE_NAMES = frozenset({
    "E", "F-model", "F-runner", "T-tool", "C-one", "C-one-selected",
    "C-many", "S-one", "X-export-prepare", "X-export-transmit",
})
RESULT_ARTIFACT_MODES = frozenset({"E", "V", "O"})
EFFECT_CLASSES = frozenset({
    "none", "read", "write_reversible", "external_reversible",
    "external_irreversible", "instance_critical_secret", "instance_critical_storage",
})
EFFECT_FAMILIES = MappingProxyType({
    "none": "N",
    "read": "N",
    "write_reversible": "L",
    "external_reversible": "X",
    "external_irreversible": "X",
    "instance_critical_secret": "X",
    "instance_critical_storage": "X",
})
RESULT_EFFECT_FIELDS = frozenset({
    "effect_class", "effect_state", "effect_receipt_ref", "remote_outcome",
})
ERROR_FIELDS = frozenset({
    "schema_id", "schema_version", "port_contract_version", "request_id", "operation",
    "code", "port_error_code", "extension_error_code", "message_class", "retry_class",
    "affected_refs", "evidence_ref",
})
BINDING_SLOT_KEY_FIELDS = frozenset({
    "port_contract_version", "target_scope_fingerprint", "purpose", "binding_slot_id",
    "capability_selector_digest",
})

_IDENTIFIER = re.compile(r"[a-z][a-z0-9._:-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class PortContract:
    port_contract_version: str
    extension_kind: str
    artifact_form: str
    trust_tier: str
    staging_authorities: frozenset[str]
    operations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequestArtifactProfile:
    name: str
    min_items: int
    max_items: int
    role: str | None
    selector_policy: str
    list_source: str
    exact_order: bool
    requires_bounded_stream: bool
    ref_only_allowed: bool
    shared_store_allowed: bool


@dataclass(frozen=True, slots=True)
class ResultArtifactMetadata:
    name: str
    role: str | None
    binding_source: str
    media_source: str
    omissions_source: str


@dataclass(frozen=True, slots=True)
class OperationContract:
    port_contract_version: str
    operation: str
    terminal_class: str
    request_artifact_profile: str
    request_target_source: str
    result_artifact_mode: str
    result_artifact_metadata: str
    effect_source: str
    allowed_effect_classes: frozenset[str]


_PORT_ROWS = (
    ("provider-port-v1", "provider", "oci_extension_service", "runtime_worker",
     frozenset({"deployment_operator"}),
     ("capabilities", "catalog", "model_step", "status", "cancel")),
    ("managed-provider-runner-port-v1", "provider", "release_pinned_oci_service",
     "managed_provider_runner", frozenset({"deployment_operator"}),
     ("preflight", "device_auth_start", "device_auth_status", "device_auth_cancel",
      "run_start", "run_status", "run_cancel")),
    ("model-runtime-port-v1", "model_runtime", "oci_extension_service", "runtime_worker",
     frozenset({"deployment_operator"}),
     ("capabilities", "model_step", "status", "cancel")),
    ("tool-port-v1", "tool", "oci_extension_service", "runtime_worker",
     frozenset({"deployment_operator"}),
     ("describe_tools", "invoke_tool", "status", "cancel")),
    ("artifact-codec-port-v1", "artifact_codec", "oci_extension_service", "runtime_worker",
     frozenset({"deployment_operator"}),
     ("probe", "decode_projection", "render_preview", "encode", "cancel")),
    ("lens-definition-port-v1", "lens", "code_free_definition", "definition_package",
     frozenset({"product_owner", "deployment_operator"}),
     ("validate_definition", "compose", "apply_decision")),
    ("evaluator-definition-port-v1", "evaluator", "code_free_definition",
     "definition_package", frozenset({"product_owner", "deployment_operator"}),
     ("describe_rubric", "evaluate", "abstain")),
    ("evaluator-runtime-port-v1", "evaluator", "oci_extension_service", "runtime_worker",
     frozenset({"deployment_operator"}),
     ("describe_rubric", "evaluate", "abstain", "status", "cancel")),
    ("storage-port-v1", "storage", "deployment_pinned_oci_service", "deployment_trusted",
     frozenset({"deployment_operator"}),
     ("capabilities", "health", "migrate_plan", "read", "write_cas")),
    ("credential-vault-port-v1", "credential_vault", "deployment_pinned_oci_service",
     "deployment_trusted", frozenset({"deployment_operator"}),
     ("capabilities", "health", "store", "resolve_for_gateway", "retire", "erase")),
    ("export-sink-port-v1", "export_sink", "oci_extension_service", "runtime_worker",
     frozenset({"deployment_operator"}),
     ("capabilities", "prepare", "transmit", "status", "cancel")),
)

PORT_CONTRACTS = MappingProxyType({
    row[0]: PortContract(*row) for row in _PORT_ROWS
})

PORT_SCHEMA_IDS = MappingProxyType({
    (port, shape):
        f"https://deeptwin.local/schemas/v1/extensions/ports/{port}/{shape}.schema.json"
    for port in PORT_CONTRACTS
    for shape in PORT_SCHEMA_SHAPES
})


def _keys(port: str, *operations: str) -> tuple[tuple[str, str], ...]:
    return tuple((port, operation) for operation in operations)


_ALL_OPERATION_KEYS = tuple(
    (port, operation)
    for port, contract in PORT_CONTRACTS.items()
    for operation in contract.operations
)
_ALL_OPERATION_KEY_SET = frozenset(_ALL_OPERATION_KEYS)


def _closed_partition(label: str, groups):
    result = {}
    for assigned_value, keys in groups:
        for key in keys:
            if key not in _ALL_OPERATION_KEY_SET:
                raise RuntimeError(f"{label} names an unknown operation: {key!r}")
            if key in result:
                raise RuntimeError(f"{label} assigns an operation twice: {key!r}")
            result[key] = assigned_value
    missing = _ALL_OPERATION_KEY_SET - result.keys()
    if missing:
        raise RuntimeError(f"{label} omits operations: {sorted(missing)!r}")
    return MappingProxyType(result)


_TERMINAL_CLASS_BY_OPERATION = _closed_partition("terminal class", (
    ("Q", (
        *_keys("provider-port-v1", "capabilities", "catalog", "status", "cancel"),
        *_keys("managed-provider-runner-port-v1", "preflight", "device_auth_status",
               "device_auth_cancel", "run_status", "run_cancel"),
        *_keys("model-runtime-port-v1", "capabilities", "status", "cancel"),
        *_keys("tool-port-v1", "describe_tools", "status", "cancel"),
        *_keys("artifact-codec-port-v1", "probe", "cancel"),
        *_keys("lens-definition-port-v1", "validate_definition", "compose", "apply_decision"),
        *_keys("evaluator-definition-port-v1", "describe_rubric", "evaluate", "abstain"),
        *_keys("evaluator-runtime-port-v1", "describe_rubric", "abstain", "status", "cancel"),
        *_keys("storage-port-v1", "capabilities", "health", "migrate_plan", "read"),
        *_keys("credential-vault-port-v1", "capabilities", "health"),
        *_keys("export-sink-port-v1", "capabilities", "prepare", "status", "cancel"),
    )),
    ("C", (
        *_keys("provider-port-v1", "model_step"),
        *_keys("model-runtime-port-v1", "model_step"),
        *_keys("tool-port-v1", "invoke_tool"),
        *_keys("artifact-codec-port-v1", "decode_projection", "render_preview", "encode"),
        *_keys("evaluator-runtime-port-v1", "evaluate"),
        *_keys("export-sink-port-v1", "transmit"),
    )),
    ("M", (
        *_keys("managed-provider-runner-port-v1", "device_auth_start", "run_start"),
        *_keys("storage-port-v1", "write_cas"),
        *_keys("credential-vault-port-v1", "store", "resolve_for_gateway", "retire", "erase"),
    )),
))

TERMINALS_BY_CLASS = MappingProxyType({
    "Q": ("succeeded", "failed"),
    "C": ("succeeded", "failed", "cancelled", "unknown"),
    "M": ("succeeded", "failed", "unknown"),
})


REQUEST_ARTIFACT_PROFILES = MappingProxyType({
    "E": RequestArtifactProfile(
        "E", 0, 0, None, "forbidden", "none", True, False, False, False,
    ),
    "F-model": RequestArtifactProfile(
        "F-model", 0, 32, "model_input", "frozen_exact", "frozen_turn", True,
        False, False, False,
    ),
    "F-runner": RequestArtifactProfile(
        "F-runner", 0, 32, "runner_input", "frozen_exact", "frozen_run_projection", True,
        False, False, False,
    ),
    "T-tool": RequestArtifactProfile(
        "T-tool", 0, 32, None, "tool_definition", "tool_definition", True,
        False, False, False,
    ),
    "C-one": RequestArtifactProfile(
        "C-one", 1, 1, "codec_source", "forbidden", "request_artifact_inputs", True,
        False, False, False,
    ),
    "C-one-selected": RequestArtifactProfile(
        "C-one-selected", 1, 1, "codec_source", "optional_qualified_kind",
        "request_artifact_inputs", True, False, False, False,
    ),
    "C-many": RequestArtifactProfile(
        "C-many", 1, 32, "codec_source", "forbidden", "request_artifact_inputs", True,
        False, False, False,
    ),
    "S-one": RequestArtifactProfile(
        "S-one", 1, 1, "storage_value", "forbidden", "request_artifact_inputs", True,
        False, False, False,
    ),
    "X-export-prepare": RequestArtifactProfile(
        "X-export-prepare", 1, 256, "export_payload", "forbidden", "export_snapshot", True,
        True, False, False,
    ),
    "X-export-transmit": RequestArtifactProfile(
        "X-export-transmit", 1, 256, "export_payload", "forbidden", "prepared_delivery", True,
        True, False, False,
    ),
})

_REQUEST_PROFILE_BY_OPERATION = _closed_partition("request artifact profile", (
    ("E", (
        *_keys("provider-port-v1", "capabilities", "catalog", "status", "cancel"),
        *_keys("managed-provider-runner-port-v1", "preflight", "device_auth_start",
               "device_auth_status", "device_auth_cancel", "run_status", "run_cancel"),
        *_keys("model-runtime-port-v1", "capabilities", "status", "cancel"),
        *_keys("tool-port-v1", "describe_tools", "status", "cancel"),
        *_keys("artifact-codec-port-v1", "cancel"),
        *_keys("lens-definition-port-v1", "validate_definition", "compose", "apply_decision"),
        *_keys("evaluator-definition-port-v1", "describe_rubric", "evaluate", "abstain"),
        *_keys("evaluator-runtime-port-v1", "describe_rubric", "evaluate", "abstain", "status",
               "cancel"),
        *_keys("storage-port-v1", "capabilities", "health", "migrate_plan", "read"),
        *_keys("credential-vault-port-v1", "capabilities", "health", "store",
               "resolve_for_gateway", "retire", "erase"),
        *_keys("export-sink-port-v1", "capabilities", "status", "cancel"),
    )),
    ("F-model", (
        *_keys("provider-port-v1", "model_step"),
        *_keys("model-runtime-port-v1", "model_step"),
    )),
    ("F-runner", _keys("managed-provider-runner-port-v1", "run_start")),
    ("T-tool", _keys("tool-port-v1", "invoke_tool")),
    ("C-one", _keys("artifact-codec-port-v1", "probe")),
    ("C-one-selected", _keys("artifact-codec-port-v1", "decode_projection", "render_preview")),
    ("C-many", _keys("artifact-codec-port-v1", "encode")),
    ("S-one", _keys("storage-port-v1", "write_cas")),
    ("X-export-prepare", _keys("export-sink-port-v1", "prepare")),
    ("X-export-transmit", _keys("export-sink-port-v1", "transmit")),
))

_REQUEST_TARGET_SOURCE_BY_OPERATION = MappingProxyType({
    key: "prepared_delivery" if key == ("export-sink-port-v1", "transmit") else "request"
    for key in _ALL_OPERATION_KEYS
})


RESULT_ARTIFACT_METADATA = MappingProxyType({
    "none": ResultArtifactMetadata("none", None, "none", "none", "none"),
    "model_content": ResultArtifactMetadata(
        "model_content", "model_content", "output.content_block_refs",
        "durable_artifact.media_type", "null",
    ),
    "runner_artifact": ResultArtifactMetadata(
        "runner_artifact", "runner_artifact",
        "output.normalized_event_refs[*].artifact_ref",
        "normalized_event.media_type", "normalized_event.omissions_ref",
    ),
    "tool_result": ResultArtifactMetadata(
        "tool_result", None, "output.result_ref.ToolResultArtifactBindingV1[]",
        "binding.media_type", "binding.omissions_ref",
    ),
    "decoded_projection": ResultArtifactMetadata(
        "decoded_projection", "decoded_projection", "output.projection_artifact_ref",
        "input.target_projection_schema_ref.media_type", "output.omissions_ref",
    ),
    "render_preview": ResultArtifactMetadata(
        "render_preview", "render_preview", "output.preview_artifact_ref",
        "input.target_media_type", "output.omissions_ref",
    ),
    "encoded_output": ResultArtifactMetadata(
        "encoded_output", "encoded_output", "output.encoded_artifact_ref",
        "input.target_media_type", "output.omissions_ref",
    ),
    "storage_object": ResultArtifactMetadata(
        "storage_object", "storage_object", "output.object_artifact_ref",
        "durable_artifact.media_type", "null",
    ),
})

_RESULT_ARTIFACT_BY_OPERATION = _closed_partition("result artifact contract", (
    (("E", "none"), (
        *_keys("provider-port-v1", "capabilities", "catalog", "status", "cancel"),
        *_keys("managed-provider-runner-port-v1", "preflight", "device_auth_start",
               "device_auth_status", "device_auth_cancel", "run_start", "run_cancel"),
        *_keys("model-runtime-port-v1", "capabilities", "status", "cancel"),
        *_keys("tool-port-v1", "describe_tools", "status", "cancel"),
        *_keys("artifact-codec-port-v1", "probe", "cancel"),
        *_keys("lens-definition-port-v1", "validate_definition", "compose", "apply_decision"),
        *_keys("evaluator-definition-port-v1", "describe_rubric", "evaluate", "abstain"),
        *_keys("evaluator-runtime-port-v1", "describe_rubric", "evaluate", "abstain", "status",
               "cancel"),
        *_keys("storage-port-v1", "capabilities", "health", "migrate_plan", "write_cas"),
        *_keys("credential-vault-port-v1", "capabilities", "health", "store",
               "resolve_for_gateway", "retire", "erase"),
        *_keys("export-sink-port-v1", "capabilities", "prepare", "transmit", "status", "cancel"),
    )),
    (("V", "model_content"), (
        *_keys("provider-port-v1", "model_step"),
        *_keys("model-runtime-port-v1", "model_step"),
    )),
    (("V", "runner_artifact"), _keys("managed-provider-runner-port-v1", "run_status")),
    (("V", "tool_result"), _keys("tool-port-v1", "invoke_tool")),
    (("O", "decoded_projection"), _keys("artifact-codec-port-v1", "decode_projection")),
    (("O", "render_preview"), _keys("artifact-codec-port-v1", "render_preview")),
    (("O", "encoded_output"), _keys("artifact-codec-port-v1", "encode")),
    (("O", "storage_object"), _keys("storage-port-v1", "read")),
))


def _effect_assignment(source: str, *effect_classes: str):
    return source, frozenset(effect_classes)


_EFFECT_BY_OPERATION = _closed_partition("effect assignment", (
    (_effect_assignment("literal_none", "none"), (
        *_keys("provider-port-v1", "cancel"),
        *_keys("managed-provider-runner-port-v1", "device_auth_cancel", "run_cancel"),
        *_keys("model-runtime-port-v1", "cancel"),
        *_keys("tool-port-v1", "cancel"),
        *_keys("artifact-codec-port-v1", "cancel"),
        *_keys("evaluator-runtime-port-v1", "cancel"),
        *_keys("export-sink-port-v1", "cancel"),
    )),
    (_effect_assignment("literal_read", "read"), (
        *_keys("provider-port-v1", "capabilities", "catalog", "status"),
        *_keys("managed-provider-runner-port-v1", "preflight", "device_auth_status", "run_status"),
        *_keys("model-runtime-port-v1", "capabilities", "status"),
        *_keys("tool-port-v1", "describe_tools", "status"),
        *_keys("artifact-codec-port-v1", "probe"),
        *_keys("lens-definition-port-v1", "validate_definition"),
        *_keys("evaluator-definition-port-v1", "describe_rubric"),
        *_keys("evaluator-runtime-port-v1", "describe_rubric", "status"),
        *_keys("storage-port-v1", "capabilities", "health", "migrate_plan", "read"),
        *_keys("credential-vault-port-v1", "capabilities", "health"),
        *_keys("export-sink-port-v1", "capabilities", "prepare", "status"),
    )),
    (_effect_assignment("literal_write_reversible", "write_reversible"), (
        *_keys("artifact-codec-port-v1", "decode_projection", "render_preview", "encode"),
        *_keys("lens-definition-port-v1", "compose", "apply_decision"),
        *_keys("evaluator-definition-port-v1", "evaluate", "abstain"),
        *_keys("evaluator-runtime-port-v1", "evaluate", "abstain"),
    )),
    (_effect_assignment("literal_external", "external_irreversible"), (
        *_keys("provider-port-v1", "model_step"),
        *_keys("managed-provider-runner-port-v1", "run_start"),
        *_keys("model-runtime-port-v1", "model_step"),
    )),
    (_effect_assignment("literal_external", "external_reversible"),
     _keys("managed-provider-runner-port-v1", "device_auth_start")),
    (_effect_assignment("literal_external", "instance_critical_storage"),
     _keys("storage-port-v1", "write_cas")),
    (_effect_assignment("literal_external", "instance_critical_secret"),
     _keys("credential-vault-port-v1", "store", "resolve_for_gateway", "retire", "erase")),
    (_effect_assignment("tool_definition", *sorted(EFFECT_CLASSES)),
     _keys("tool-port-v1", "invoke_tool")),
    (_effect_assignment("export_destination", "external_reversible", "external_irreversible"),
     _keys("export-sink-port-v1", "transmit")),
))


OPERATION_CONTRACTS = MappingProxyType({
    key: OperationContract(
        port_contract_version=key[0],
        operation=key[1],
        terminal_class=_TERMINAL_CLASS_BY_OPERATION[key],
        request_artifact_profile=_REQUEST_PROFILE_BY_OPERATION[key],
        request_target_source=_REQUEST_TARGET_SOURCE_BY_OPERATION[key],
        result_artifact_mode=_RESULT_ARTIFACT_BY_OPERATION[key][0],
        result_artifact_metadata=_RESULT_ARTIFACT_BY_OPERATION[key][1],
        effect_source=_EFFECT_BY_OPERATION[key][0],
        allowed_effect_classes=_EFFECT_BY_OPERATION[key][1],
    )
    for key in _ALL_OPERATION_KEYS
})


TERMINAL_CANDIDATES = tuple(
    (port, operation, terminal)
    for port, operation in _ALL_OPERATION_KEYS
    for terminal in TERMINALS
)
ALLOWED_TERMINAL_CANDIDATES = frozenset(
    (port, operation, terminal)
    for port, operation in _ALL_OPERATION_KEYS
    for terminal in TERMINALS_BY_CLASS[_TERMINAL_CLASS_BY_OPERATION[(port, operation)]]
)
REJECTED_TERMINAL_CANDIDATES = frozenset(TERMINAL_CANDIDATES) \
    - ALLOWED_TERMINAL_CANDIDATES

RESULT_ARTIFACT_CONTRACTS = MappingProxyType({
    (port, operation, terminal): (
        (OPERATION_CONTRACTS[(port, operation)].result_artifact_mode,
         OPERATION_CONTRACTS[(port, operation)].result_artifact_metadata)
        if terminal == "succeeded" else ("E", "none")
    )
    for port, operation, terminal in ALLOWED_TERMINAL_CANDIDATES
})


def _effect_rows():
    null = "null"
    ref = "ref"
    not_applicable = "not_applicable"
    unknown_external = frozenset(
        ("unknown", receipt, outcome)
        for receipt in (null, ref)
        for outcome in ("unconfirmed", "unknown")
    )
    return {
        ("succeeded", "N"): frozenset({("none", null, not_applicable)}),
        ("failed", "N"): frozenset({("none", null, not_applicable)}),
        ("cancelled", "N"): frozenset({("none", null, not_applicable)}),
        ("unknown", "N"): frozenset(),
        ("succeeded", "L"): frozenset({("committed", ref, not_applicable)}),
        ("failed", "L"): frozenset({
            ("none", null, not_applicable),
            ("not_committed", ref, not_applicable),
        }),
        ("cancelled", "L"): frozenset({
            ("none", null, not_applicable),
            ("not_committed", ref, not_applicable),
            ("committed", ref, not_applicable),
            ("unknown", ref, not_applicable),
        }),
        ("unknown", "L"): frozenset({("unknown", ref, not_applicable)}),
        ("succeeded", "X"): frozenset({("committed", ref, "confirmed")}),
        ("failed", "X"): frozenset({
            ("none", null, not_applicable),
            ("not_committed", ref, "confirmed"),
        }),
        ("cancelled", "X"): frozenset({
            ("none", null, not_applicable),
            ("not_committed", ref, "confirmed"),
            ("committed", ref, "confirmed"),
            *unknown_external,
        }),
        ("unknown", "X"): unknown_external,
    }


ALLOWED_EFFECT_TUPLES = MappingProxyType(_effect_rows())


def validate_port_tuple(*, extension_kind, artifact_form, port_contract_version,
                        trust_tier, staging_authority):
    """Return the exact port contract or reject the complete semantic tuple."""
    if type(port_contract_version) is not str:
        raise PortContractError("Unknown semantic port tuple")
    contract = PORT_CONTRACTS.get(port_contract_version)
    if (contract is None
            or type(extension_kind) is not str
            or type(artifact_form) is not str
            or type(trust_tier) is not str
            or type(staging_authority) is not str
            or extension_kind != contract.extension_kind
            or artifact_form != contract.artifact_form
            or trust_tier != contract.trust_tier
            or staging_authority not in contract.staging_authorities):
        raise PortContractError("Unknown semantic port tuple")
    return contract


def operation_contract(port_contract_version, operation):
    if type(port_contract_version) is not str or type(operation) is not str:
        raise PortContractError("Unknown port-qualified operation")
    try:
        return OPERATION_CONTRACTS[(port_contract_version, operation)]
    except KeyError:
        raise PortContractError("Unknown port-qualified operation") from None


def effect_tuple_allowed(*, effect_class, terminal, effect_state,
                         receipt_presence, remote_outcome):
    """Check one concrete result-effect tuple against the exhaustive family table."""
    if (type(effect_class) is not str or type(terminal) is not str
            or type(effect_state) is not str or type(receipt_presence) is not str
            or type(remote_outcome) is not str):
        return False
    family = EFFECT_FAMILIES.get(effect_class)
    if family is None or receipt_presence not in {"null", "ref"}:
        return False
    return (effect_state, receipt_presence, remote_outcome) in \
        ALLOWED_EFFECT_TUPLES.get((terminal, family), ())


def _identifier(value, label):
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise PortContractError(f"{label} must be an exact identifier")
    return value


def _digest(value, label):
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise PortContractError(f"{label} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True, init=False)
class BindingSlotKeyV1:
    port_contract_version: str
    target_scope_fingerprint: str
    purpose: str
    binding_slot_id: str
    capability_selector_digest: str

    def __new__(cls):
        raise TypeError("Use BindingSlotKeyV1.from_mapping")

    @classmethod
    def from_mapping(cls, value, *, expected_port_contract_version=None,
                     expected_digest=None):
        if type(value) is not dict or set(value) != BINDING_SLOT_KEY_FIELDS:
            raise PortContractError("BindingSlotKeyV1 must have exactly five fields")
        port = _identifier(value["port_contract_version"], "port_contract_version")
        if port not in PORT_CONTRACTS:
            raise PortContractError("BindingSlotKeyV1 names an unknown port")
        if (expected_port_contract_version is not None
                and (type(expected_port_contract_version) is not str
                     or port != expected_port_contract_version)):
            raise PortContractError("BindingSlotKeyV1 port version mismatch")
        result = object.__new__(cls)
        object.__setattr__(result, "port_contract_version", port)
        object.__setattr__(result, "target_scope_fingerprint", _digest(
            value["target_scope_fingerprint"], "target_scope_fingerprint",
        ))
        object.__setattr__(result, "purpose", _identifier(value["purpose"], "purpose"))
        object.__setattr__(result, "binding_slot_id", _identifier(
            value["binding_slot_id"], "binding_slot_id",
        ))
        object.__setattr__(result, "capability_selector_digest", _digest(
            value["capability_selector_digest"], "capability_selector_digest",
        ))
        if (expected_digest is not None
                and (_digest(expected_digest, "binding_slot_key_digest") != result.digest)):
            raise PortContractError("BindingSlotKeyV1 digest mismatch")
        return result

    def as_dict(self):
        return {
            "port_contract_version": self.port_contract_version,
            "target_scope_fingerprint": self.target_scope_fingerprint,
            "purpose": self.purpose,
            "binding_slot_id": self.binding_slot_id,
            "capability_selector_digest": self.capability_selector_digest,
        }

    @property
    def digest(self):
        return sha256(canonical_json(self.as_dict())).hexdigest()


def _assert_structural_invariants():
    if len(PORT_CONTRACTS) != 11:
        raise RuntimeError("Semantic port catalog must contain exactly eleven ports")
    if len(_ALL_OPERATION_KEYS) != 52 or len(_ALL_OPERATION_KEY_SET) != 52:
        raise RuntimeError("Semantic port catalog must contain 52 unique operations")
    if len(PORT_SCHEMA_IDS) != 44 or len(set(PORT_SCHEMA_IDS.values())) != 44:
        raise RuntimeError("Semantic port catalog must contain 44 unique schema IDs")
    terminal_counts = {
        name: tuple(_TERMINAL_CLASS_BY_OPERATION.values()).count(name)
        for name in TERMINAL_CLASSES
    }
    if terminal_counts != {"Q": 37, "C": 8, "M": 7}:
        raise RuntimeError("Terminal classes must partition operations as 37/8/7")
    if (len(TERMINAL_CANDIDATES), len(ALLOWED_TERMINAL_CANDIDATES),
            len(REJECTED_TERMINAL_CANDIDATES)) != (208, 127, 81):
        raise RuntimeError("Terminal candidate partition must be 208/127/81")
    request_empty = tuple(_REQUEST_PROFILE_BY_OPERATION.values()).count("E")
    if request_empty != 41 or len(_REQUEST_PROFILE_BY_OPERATION) - request_empty != 11:
        raise RuntimeError("Request artifact profiles must partition as 11/41")
    result_modes = tuple(value[0] for value in _RESULT_ARTIFACT_BY_OPERATION.values())
    if {name: result_modes.count(name) for name in RESULT_ARTIFACT_MODES} \
            != {"E": 44, "V": 4, "O": 4}:
        raise RuntimeError("Result artifact modes must partition as 44/4/4")
    if (set(RESULT_ARTIFACT_CONTRACTS) != ALLOWED_TERMINAL_CANDIDATES
            or len(RESULT_ARTIFACT_CONTRACTS) != 127):
        raise RuntimeError("Result artifact branches must match the 127 allowed terminals")
    if any(
        value != ("E", "none")
        for (*_, terminal), value in RESULT_ARTIFACT_CONTRACTS.items()
        if terminal != "succeeded"
    ):
        raise RuntimeError("Every non-success result must have empty artifacts")
    if set(_REQUEST_PROFILE_BY_OPERATION.values()) - REQUEST_ARTIFACT_PROFILE_NAMES:
        raise RuntimeError("Unknown request artifact profile")
    if {value[1] for value in _RESULT_ARTIFACT_BY_OPERATION.values()} \
            - RESULT_ARTIFACT_METADATA.keys():
        raise RuntimeError("Unknown result artifact metadata profile")
    if sum(len(value) for value in ALLOWED_EFFECT_TUPLES.values()) != 25:
        raise RuntimeError("Effect table must contain 25 concrete allowed tuples")
    if set(ALLOWED_EFFECT_TUPLES) != {
        (terminal, family) for terminal in TERMINALS for family in ("N", "L", "X")
    }:
        raise RuntimeError("Effect table must cover every terminal/family candidate")
    for contract in OPERATION_CONTRACTS.values():
        if (contract.terminal_class not in TERMINAL_CLASSES
                or contract.request_artifact_profile not in REQUEST_ARTIFACT_PROFILES
                or contract.result_artifact_mode not in RESULT_ARTIFACT_MODES
                or contract.result_artifact_metadata not in RESULT_ARTIFACT_METADATA
                or not contract.allowed_effect_classes
                or not contract.allowed_effect_classes <= EFFECT_CLASSES):
            raise RuntimeError("Operation contract contains an unknown semantic value")


_assert_structural_invariants()
