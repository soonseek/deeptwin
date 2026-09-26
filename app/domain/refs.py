"""Bounded domain-v1 canonical encoding and immutable references, with no I/O."""

from dataclasses import dataclass
import json
import re
from uuid import UUID


MAX_JSON_BYTES = 1_048_576
MAX_STRING_BYTES = 65_536
MAX_DEPTH = 32
MAX_ITEMS = 10_000
MAX_INTEGER = 2 ** 63 - 1
ENTITY_KINDS = frozenset("""
vault_genesis actor access_policy retention_policy work_revision chat_message proposed_command source
extraction work_model model_catalog model_choice runtime_profile design_decision
design_candidate graph environment design_approval run_consent action_approval run_manifest
budget_policy frozen_turn artifact artifact_projection handoff memory_event decision_record
original_execution own_alternative selector difference hypothesis inquiry change_candidate
comparison_plan comparison_result promotion_decision lens_definition lens_composition
inquiry_audit knowledge_candidate evaluation_dataset evaluation_profile validation_report
independence_profile qualification extension_manifest extension_installation
extension_qualification extension_binding backup_manifest export_manifest
tool_definition grant execution_envelope task_spec rubric observation_contract worker_response_capture deployment_request
deployment_receipt deployment_receipt_consumption
provider_conformance_run
process_feedback
""".split())
LOCATOR_KINDS = ENTITY_KINDS | frozenset("""
work setup session connection run node_execution attempt tool_call budget_reservation
approval_challenge environment_head speech_session series round event record_gap backup export
credential_handle service_client
""".split())


class DomainContractError(ValueError):
    """Invalid/unbounded domain data; never interpreted as missing-but-successful content."""


def uuid_string(value):
    if type(value) is not str or len(value) != 36:
        raise DomainContractError("Expected canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise DomainContractError("Expected canonical UUID") from exc
    if str(parsed) != value or parsed.int == 0:
        raise DomainContractError("Expected non-nil canonical UUID")
    return value


def positive_integer(value):
    if type(value) is not int or not 1 <= value <= MAX_INTEGER:
        raise DomainContractError("Expected bounded positive integer")
    return value


def decimal_string(value):
    """Normalize explicit fixed-point text without context rounding or float conversion."""
    if (type(value) is not str or len(value) > 128
            or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is None):
        raise DomainContractError("Expected bounded fixed-point decimal string")
    result = value.rstrip("0").rstrip(".") if "." in value else value
    return "0" if result == "-0" else result


def canonical_json(value):
    """Private format v1: sorted UTF-8 JSON, no normalization, floats or coercion.

    This is not RFC 8785. Decimal quantities use decimal_string before serialization;
    arbitrary text is preserved exactly. Cycles and size/depth bombs fail before encoding.
    """
    count = 0
    string_bytes = 0

    def inspect(item, depth):
        nonlocal count, string_bytes
        count += 1
        if depth > MAX_DEPTH or count > MAX_ITEMS:
            raise DomainContractError("JSON nesting or item limit exceeded")
        kind = type(item)
        if item is None or kind is bool:
            return
        if kind is int:
            if abs(item) > MAX_INTEGER:
                raise DomainContractError("Integer is out of range")
            return
        if kind is str:
            if len(item) > MAX_STRING_BYTES:
                raise DomainContractError("JSON string limit exceeded")
            try:
                length = len(item.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise DomainContractError("Invalid Unicode scalar") from exc
            string_bytes += length
            if length > MAX_STRING_BYTES or string_bytes > MAX_JSON_BYTES:
                raise DomainContractError("JSON string limit exceeded")
            return
        if kind is list or kind is tuple:
            for child in item:
                inspect(child, depth + 1)
            return
        if kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise DomainContractError("JSON keys must be strings")
                inspect(key, depth + 1)
                inspect(child, depth + 1)
            return
        raise DomainContractError("Unsupported JSON value; decimals require strings")

    inspect(value, 0)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise DomainContractError("JSON byte limit exceeded")
    return encoded


def parse_canonical(data):
    if type(data) is not bytes or len(data) > MAX_JSON_BYTES:
        raise DomainContractError("Expected bounded canonical bytes")
    def bounded_int(text):
        if len(text.lstrip("-")) > 19:
            raise DomainContractError("Integer is out of range")
        value = int(text)
        if abs(value) > MAX_INTEGER:
            raise DomainContractError("Integer is out of range")
        return value

    try:
        value = json.loads(data.decode("utf-8"), parse_int=bounded_int)
        if canonical_json(value) != data:
            raise DomainContractError("Noncanonical JSON encoding")
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise DomainContractError("Invalid canonical JSON") from exc
    return value


@dataclass(frozen=True, slots=True)
class EntityRef:
    kind: str
    id: str
    version: int
    sha256: str

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in ENTITY_KINDS:
            raise DomainContractError("Unregistered entity kind")
        uuid_string(self.id)
        positive_integer(self.version)
        if type(self.sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise DomainContractError("Expected lowercase SHA-256")

    def as_dict(self):
        return {"kind": self.kind, "id": self.id, "version": self.version, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {"kind", "id", "version", "sha256"}:
            raise DomainContractError("Expected exact immutable content reference")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """Navigation only; intentionally not accepted by EntityRef.from_dict."""
    kind: str
    id: str
    version: int | None = None
    content_hash: str | None = None

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in LOCATOR_KINDS:
            raise DomainContractError("Unregistered locator kind")
        uuid_string(self.id)
        if self.version is not None:
            positive_integer(self.version)
        if self.content_hash is not None and (type(self.content_hash) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.content_hash) is None):
            raise DomainContractError("Expected lowercase content hash")

    def as_dict(self):
        value = {"kind": self.kind, "id": self.id}
        if self.version is not None:
            value["version"] = self.version
        if self.content_hash is not None:
            value["content_hash"] = self.content_hash
        return value
