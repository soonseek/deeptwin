"""Adversarial conformance tests for the dependency-free public extension SDK."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import traceback

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
SDK_ROOT = REPOSITORY / "sdk" / "python" / "deeptwin_ext" / "src"
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

from app.domain.refs import DomainContractError, canonical_json  # noqa: E402
from app.extensions.contracts import ExtensionManifest  # noqa: E402
from deeptwin_ext import (  # noqa: E402
    PROTOCOL_VERSION,
    WORKER_FAILURE_CODES,
    WORKER_OPERATIONS,
    ProtocolError,
    WorkerRequest,
    WorkerResult,
    build_manifest,
    canonical_manifest_bytes,
)


REQUEST_ID = "12345678-1234-4234-8234-123456789abc"
HASH_A = "a" * 64
HASH_B = "b" * 64


def manifest_arguments(**changes):
    value = {
        "extension_id": "org.example.worker",
        "extension_version": "1.2.3",
        "extension_kind": "tool",
        "artifact_type": "package",
        "artifact_sha256": HASH_A,
        "source_kind": "third_party",
        "source_locator": "https://example.invalid/worker",
        "provenance_sha256": HASH_B,
        "license_expression": "MIT",
        "entrypoint_protocol": "worker-json-v1",
        "entrypoint_name": "main",
        "isolation_profile": "runtime-worker-v1",
    }
    value.update(changes)
    return value


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def request():
    return WorkerRequest(REQUEST_ID, "invoke", HASH_A, HASH_B)


def test_sdk_manifest_is_accepted_by_core_parser_and_uses_identical_canonical_bytes():
    value = build_manifest(**manifest_arguments())
    parsed = ExtensionManifest.from_mapping(value)

    assert parsed.extension_id == "org.example.worker"
    assert canonical_manifest_bytes(value) == canonical_json(value)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"extension_id": "Org.example.worker"}, "extension id"),
        ({"extension_id": "-org.example"}, "extension id"),
        ({"extension_id": "org.example-"}, "extension id"),
        ({"entrypoint_name": "not allowed"}, "entrypoint name"),
        ({"isolation_profile": "profile\nother"}, "isolation profile"),
        ({"source_locator": "https://example.invalid/\x7f"}, "source locator"),
        ({"framework_min": "2.0.0", "framework_max": "1.9.9"}, "range is reversed"),
        ({"schema_versions": ()}, "schema versions"),
        ({"schema_versions": ("domain-v1", "domain-v1")}, "schema versions"),
        ({"config_schema": {"type": "number"}}, "config schema"),
        ({"config_schema": {"type": ["object"]}}, "config schema"),
    ],
)
def test_sdk_manifest_rejects_core_invalid_identifiers_text_ranges_and_schemas(changes, match):
    with pytest.raises(ValueError, match=match):
        build_manifest(**manifest_arguments(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {
            "extension_kind": "lens",
            "artifact_type": "package",
            "entrypoint_protocol": "worker-json-v1",
        },
        {
            "extension_kind": "tool",
            "artifact_type": "definition",
            "entrypoint_protocol": "definition-v1",
        },
        {"extension_kind": "storage", "entrypoint_protocol": "worker-json-v1"},
        {"extension_kind": "credential_vault", "entrypoint_protocol": "worker-json-v1"},
        {"extension_kind": "tool", "entrypoint_protocol": "managed-provider-rpc-v1"},
    ],
)
def test_sdk_manifest_enforces_protocol_kind_cross_field_rules(changes):
    with pytest.raises(ValueError):
        build_manifest(**manifest_arguments(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {
            "extension_kind": "lens",
            "artifact_type": "definition",
            "entrypoint_protocol": "definition-v1",
        },
        {
            "extension_kind": "evaluator",
            "artifact_type": "definition",
            "entrypoint_protocol": "definition-v1",
        },
        {
            "extension_kind": "storage",
            "entrypoint_protocol": "deployment-port-v1",
        },
        {
            "extension_kind": "credential_vault",
            "entrypoint_protocol": "deployment-port-v1",
        },
        {
            "extension_kind": "provider",
            "entrypoint_protocol": "managed-provider-rpc-v1",
        },
    ],
)
def test_sdk_manifest_valid_cross_field_combinations_have_core_parser_parity(changes):
    value = build_manifest(**manifest_arguments(**changes))
    assert ExtensionManifest.from_mapping(value).extension_kind == changes["extension_kind"]


def test_sdk_canonical_encoding_matches_core_integer_tuple_and_string_limits():
    value = {"items": (2 ** 63 - 1, "한글", True, None)}
    assert canonical_manifest_bytes(value) == canonical_json(value)

    for invalid in ({"value": 2 ** 63}, {"value": "x" * 65_537}, {"value": 1.5}):
        with pytest.raises(ValueError):
            canonical_manifest_bytes(invalid)
        with pytest.raises(DomainContractError):
            canonical_json(invalid)


def test_sdk_manifest_rejects_depth_item_and_total_size_bombs():
    deep = {"type": "object"}
    cursor = deep
    for _ in range(34):
        child = {"type": "object"}
        cursor["child"] = child
        cursor = child
    with pytest.raises(ValueError, match="structural limits"):
        build_manifest(**manifest_arguments(config_schema=deep))

    with pytest.raises(ValueError, match="structural limits"):
        build_manifest(**manifest_arguments(
            input_schema={"type": "array", "enum": list(range(10_001))},
        ))

    with pytest.raises(ValueError, match="string limit|byte limit"):
        canonical_manifest_bytes({"values": ["x" * 128 for _ in range(8_200)]})


@pytest.mark.parametrize(
    "arguments",
    [
        ("00000000-0000-0000-0000-000000000000", "invoke", HASH_A, HASH_B),
        (REQUEST_ID.upper(), "invoke", HASH_A, HASH_B),
        (REQUEST_ID, "shell", HASH_A, HASH_B),
        (REQUEST_ID, ["invoke"], HASH_A, HASH_B),
        (REQUEST_ID, "invoke", "A" * 64, HASH_B),
        (REQUEST_ID, "invoke", HASH_A, "not-a-digest"),
    ],
)
def test_worker_request_direct_construction_fails_closed(arguments):
    with pytest.raises(ProtocolError):
        WorkerRequest(*arguments)


def test_worker_request_direct_uuid_error_discards_payload_bearing_context():
    secret = "raw-token-that-should-not-leak"
    with pytest.raises(ProtocolError) as caught:
        WorkerRequest(secret, "invoke", HASH_A, HASH_B)

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in repr(caught.value)
    assert secret not in rendered


def test_worker_request_round_trip_is_exact_and_repr_hides_content_references():
    original = request()
    encoded = original.to_bytes()

    assert encoded == canonical(original.as_dict())
    assert WorkerRequest.from_bytes(encoded) == original
    assert HASH_A not in repr(original)
    assert HASH_B not in repr(original)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not-json",
        b"\xff",
        b"[1,2,3]",
        b"[" * 2_000 + b"]" * 2_000,
        b"x" * 65_537,
        b'{"constant":NaN}',
        b'{"integer":' + b"9" * 5_000 + b"}",
        b'{"text":"\\ud800"}',
    ],
)
def test_worker_request_parser_rejects_malformed_or_unbounded_messages(data):
    with pytest.raises(ProtocolError):
        WorkerRequest.from_bytes(data)


def test_protocol_parse_errors_discard_payload_bearing_exception_causes():
    secret = "raw-token-that-should-not-leak"
    with pytest.raises(ProtocolError) as caught:
        WorkerRequest.from_bytes(b"\xff" + secret.encode("utf-8"))

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in repr(caught.value)
    assert secret not in rendered


@pytest.mark.parametrize(
    "operation",
    [
        lambda secret: WorkerRequest(secret, "invoke", HASH_A, HASH_B),
        lambda secret: WorkerResult(REQUEST_ID, "failed", None, secret),
        lambda secret: WorkerRequest.from_bytes(canonical({
            **request().as_dict(), "unexpected": secret,
        })),
        lambda secret: WorkerResult.from_bytes(canonical({
            **WorkerResult(REQUEST_ID, "failed", None, "execution_failed").as_dict(),
            "unexpected": secret,
        })),
    ],
)
def test_protocol_error_traceback_frames_do_not_retain_caller_payload(operation):
    secret = "raw-provider-secret-that-must-not-survive"
    with pytest.raises(ProtocolError) as caught:
        operation(secret)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    current = caught.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "deeptwin_ext.protocol":
            assert secret not in repr(current.tb_frame.f_locals)
        current = current.tb_next


def test_worker_request_parser_rejects_duplicate_unknown_and_missing_fields():
    value = request().as_dict()
    unknown = {**value, "unexpected": "field"}
    missing = {key: item for key, item in value.items() if key != "input_ref"}
    duplicate = (
        b'{"input_ref":"' + HASH_B.encode() + b'","manifest_digest":"'
        + HASH_A.encode() + b'","operation":"invoke","operation":"health",'
        b'"protocol_version":"deeptwin-extension-worker-v1",'
        b'"request_id":"12345678-1234-4234-8234-123456789abc"}'
    )

    for encoded in (canonical(unknown), canonical(missing), duplicate):
        with pytest.raises(ProtocolError):
            WorkerRequest.from_bytes(encoded)


def test_worker_request_parser_rejects_semantically_equal_noncanonical_encodings():
    value = request().as_dict()
    variants = (
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        canonical(value).replace(b'"invoke"', br'"\u0069nvoke"'),
    )
    for encoded in variants:
        assert json.loads(encoded) == value
        with pytest.raises(ProtocolError, match="canonical"):
            WorkerRequest.from_bytes(encoded)


def test_worker_result_completed_and_every_closed_failure_code_round_trip():
    assert WORKER_FAILURE_CODES == frozenset({
        "cancelled", "execution_failed", "input_unavailable", "invalid_input",
        "output_invalid", "policy_denied", "resource_exhausted", "timeout",
        "unavailable", "unsupported_operation",
    })
    completed = WorkerResult(REQUEST_ID, "completed", HASH_A, None)
    assert WorkerResult.from_bytes(completed.to_bytes()) == completed

    for code in WORKER_FAILURE_CODES:
        failed = WorkerResult(REQUEST_ID, "failed", None, code)
        assert WorkerResult.from_bytes(failed.to_bytes()) == failed


@pytest.mark.parametrize(
    "arguments",
    [
        (REQUEST_ID, "unknown", None, None),
        (REQUEST_ID, "completed", None, None),
        (REQUEST_ID, "completed", HASH_A, "execution_failed"),
        (REQUEST_ID, "failed", HASH_A, "execution_failed"),
        (REQUEST_ID, "failed", None, None),
        (REQUEST_ID, "failed", None, "provider_401_secret=raw-token"),
        (REQUEST_ID, "failed", None, "x" * 129),
    ],
)
def test_worker_result_direct_construction_allows_no_detailed_or_open_errors(arguments):
    with pytest.raises(ProtocolError):
        WorkerResult(*arguments)


def test_worker_result_parser_is_exact_canonical_and_duplicate_safe():
    result = WorkerResult(REQUEST_ID, "failed", None, "execution_failed")
    value = result.as_dict()
    invalid = (
        canonical({**value, "detail": "raw provider response"}),
        canonical({key: item for key, item in value.items() if key != "output_ref"}),
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        canonical(value).replace(
            b'"status":"failed"', b'"status":"failed","status":"completed"',
        ),
    )
    for encoded in invalid:
        with pytest.raises(ProtocolError):
            WorkerResult.from_bytes(encoded)


def test_worker_result_repr_omits_output_and_error_data():
    completed = WorkerResult(REQUEST_ID, "completed", HASH_A, None)
    failed = WorkerResult(REQUEST_ID, "failed", None, "execution_failed")

    assert HASH_A not in repr(completed)
    assert "execution_failed" not in repr(failed)
    assert "output_ref" not in repr(completed)
    assert "error_code" not in repr(failed)


def test_manifest_errors_discard_payload_bearing_unicode_exception_causes():
    secret = "raw-token-that-should-not-leak"
    with pytest.raises(ValueError) as caught:
        build_manifest(**manifest_arguments(source_locator="\ud800" + secret))

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in repr(caught.value)
    assert secret not in rendered
    current = caught.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "deeptwin_ext.manifest":
            assert secret not in repr(current.tb_frame.f_locals)
        current = current.tb_next

    with pytest.raises(ValueError) as canonical_error:
        canonical_manifest_bytes({"private": "x" * 65_537 + secret})
    current = canonical_error.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "deeptwin_ext.manifest":
            assert secret not in repr(current.tb_frame.f_locals)
        current = current.tb_next


def test_protocol_version_is_closed_for_both_message_directions():
    request_value = request().as_dict()
    request_value["protocol_version"] = "deeptwin-extension-worker-v2"
    result_value = WorkerResult(REQUEST_ID, "completed", HASH_A, None).as_dict()
    result_value["protocol_version"] = "deeptwin-extension-worker-v2"

    assert PROTOCOL_VERSION == "deeptwin-extension-worker-v1"
    assert WORKER_OPERATIONS == frozenset({"describe", "invoke", "health"})
    with pytest.raises(ProtocolError, match="unsupported worker protocol"):
        WorkerRequest.from_bytes(canonical(request_value))
    with pytest.raises(ProtocolError, match="unsupported worker protocol"):
        WorkerResult.from_bytes(canonical(result_value))


def test_manifest_builder_does_not_mutate_caller_schema_values():
    schema = {"type": "object", "properties": {"message": {"type": "string"}}}
    before = deepcopy(schema)
    value = build_manifest(**manifest_arguments(config_schema=schema))

    value["config_schema"]["properties"]["message"]["type"] = "integer"
    assert schema == before
