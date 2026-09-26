"""Construct the public extension-manifest-v1 wire shape without framework imports."""

import json
import re


EXTENSION_KINDS = frozenset({
    "provider", "model_runtime", "tool", "artifact_codec", "lens", "evaluator",
    "storage", "credential_vault", "export_sink",
})
_HASH = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_PROTOCOLS = frozenset({
    "definition-v1", "worker-json-v1", "managed-provider-rpc-v1", "deployment-port-v1",
})
_SCHEMA_TYPES = frozenset({"object", "array", "string", "integer", "boolean", "null"})
_MAX_JSON_BYTES = 1_048_576
_MAX_STRING_BYTES = 65_536
_MAX_DEPTH = 32
_MAX_ITEMS = 10_000
_MAX_INTEGER = 2 ** 63 - 1


def _choice(value, choices, label):
    if type(value) is not str or value not in choices:
        raise ValueError(f"invalid {label}")
    return value


def _text(value, label, maximum=2048, *, pattern=None):
    if type(value) is not str or not value:
        raise ValueError(f"invalid {label}")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError(f"invalid {label}")
    size = len(value.encode("utf-8"))
    if (size > maximum
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or (pattern is not None and pattern.fullmatch(value) is None)):
        raise ValueError(f"invalid {label}")
    return value


def _digest(value, label):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    return value


def _version(value, label):
    return _text(value, label, 32, pattern=_VERSION)


def _version_tuple(value):
    match = _VERSION.fullmatch(value)
    if match is None:  # Guarded by _version.
        raise ValueError("invalid version")
    return tuple(int(part) for part in match.groups())


def _strings(values, label, *, required=False):
    if type(values) not in (tuple, list) or len(values) > 64:
        raise ValueError(f"invalid {label}")
    result = [_text(value, label, 256) for value in values]
    if (required and not result) or len(set(result)) != len(result):
        raise ValueError(f"invalid {label}")
    return result


def _schema(value, label):
    if (type(value) is not dict or type(value.get("type")) is not str
            or value.get("type") not in _SCHEMA_TYPES):
        raise ValueError(f"invalid {label}")
    encoded = canonical_manifest_bytes(value)
    return json.loads(encoded.decode("utf-8"))


def _canonical_manifest_bytes(value):
    """Encode the framework's bounded canonical JSON subset.

    This private wire format is deterministic but is not an execution authority.
    Floats, non-string keys, oversized integers/strings, cycles, and structural
    bombs fail closed before JSON encoding.
    """
    count = 0
    string_bytes = 0

    def inspect(item, depth):
        nonlocal count, string_bytes
        count += 1
        if depth > _MAX_DEPTH or count > _MAX_ITEMS:
            raise ValueError("manifest exceeds structural limits")
        kind = type(item)
        if item is None or kind is bool:
            return
        if kind is int:
            if abs(item) > _MAX_INTEGER:
                raise ValueError("manifest integer is out of range")
            return
        if kind is str:
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                raise ValueError("manifest contains invalid Unicode")
            size = len(item.encode("utf-8"))
            string_bytes += size
            if size > _MAX_STRING_BYTES or string_bytes > _MAX_JSON_BYTES:
                raise ValueError("manifest string limit exceeded")
            return
        if kind is list or kind is tuple:
            for child in item:
                inspect(child, depth + 1)
            return
        if kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("manifest keys must be strings")
                inspect(key, depth + 1)
                inspect(child, depth + 1)
            return
        raise ValueError("manifest contains a non-JSON or floating value")

    inspect(value, 0)
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_JSON_BYTES:
        raise ValueError("manifest exceeds byte limit")
    return encoded


def canonical_manifest_bytes(value):
    """Public secret-safe boundary for deterministic manifest encoding."""
    message = None
    try:
        return _canonical_manifest_bytes(value)
    except (ValueError, UnicodeError, RecursionError, TypeError) as exc:
        message = str(exc) if str(exc) else "manifest encoding failed"
    value = None
    raise ValueError(message)


def _build_manifest(
    *,
    extension_id,
    extension_version,
    extension_kind,
    artifact_type,
    artifact_sha256,
    source_kind,
    source_locator,
    provenance_sha256,
    license_expression,
    entrypoint_protocol,
    entrypoint_name,
    isolation_profile,
    extension_api="1.0.0",
    framework_min="0.1.0",
    framework_max="0.1.99",
    schema_versions=("domain-v1",),
    config_schema=None,
    input_schema=None,
    output_schema=None,
    declared_grants=(),
    declared_resources=(),
    network_needs=(),
    filesystem_needs=(),
    secret_needs=(),
    migration_policy="none",
    uninstall_policy="retain_records",
):
    """Build inert manifest data accepted only after framework validation."""
    protocol = _choice(entrypoint_protocol, _PROTOCOLS, "entrypoint protocol")
    artifact = _choice(artifact_type, {"package", "image", "definition"}, "artifact type")
    kind = _choice(extension_kind, EXTENSION_KINDS, "extension kind")
    if (protocol == "definition-v1") != (artifact == "definition"):
        raise ValueError("definition protocol and artifact type must agree")
    if protocol == "definition-v1" and kind not in {"lens", "evaluator"}:
        raise ValueError("code-free definitions are limited to lens or evaluator kinds")
    if kind == "lens" and protocol != "definition-v1":
        raise ValueError("lens extensions must be code-free definitions")
    if kind in {"storage", "credential_vault"} and protocol != "deployment-port-v1":
        raise ValueError("instance-critical adapters require deployment port protocol")
    if protocol == "managed-provider-rpc-v1" and kind != "provider":
        raise ValueError("managed provider protocol is provider-only")

    minimum = _version(framework_min, "framework minimum")
    maximum = _version(framework_max, "framework maximum")
    if _version_tuple(minimum) > _version_tuple(maximum):
        raise ValueError("framework compatibility range is reversed")

    closed = {"type": "object", "additionalProperties": False}
    value = {
        "schema_version": "extension-manifest-v1",
        "extension_id": _text(extension_id, "extension id", 128, pattern=_IDENTIFIER),
        "extension_version": _version(extension_version, "extension version"),
        "extension_kind": kind,
        "artifact": {"type": artifact, "sha256": _digest(artifact_sha256, "artifact digest")},
        "source": {
            "kind": _choice(source_kind, {"built_in", "third_party", "operator_deployment"},
                            "source kind"),
            "locator": _text(source_locator, "source locator"),
            "provenance_sha256": _digest(provenance_sha256, "provenance digest"),
        },
        "license_expression": _text(license_expression, "license expression", 256),
        "compatibility": {
            "extension_api": _version(extension_api, "extension API"),
            "framework_min": minimum,
            "framework_max": maximum,
            "schema_versions": _strings(schema_versions, "schema versions", required=True),
        },
        "entrypoint": {
            "protocol": protocol,
            "name": _text(entrypoint_name, "entrypoint name", 128, pattern=_IDENTIFIER),
        },
        "config_schema": _schema(closed if config_schema is None else config_schema,
                                 "config schema"),
        "input_schema": _schema(closed if input_schema is None else input_schema, "input schema"),
        "output_schema": _schema(closed if output_schema is None else output_schema,
                                 "output schema"),
        "declared_grants": _strings(declared_grants, "declared grants"),
        "declared_resources": _strings(declared_resources, "declared resources"),
        "network_needs": _strings(network_needs, "network needs"),
        "filesystem_needs": _strings(filesystem_needs, "filesystem needs"),
        "secret_needs": _strings(secret_needs, "secret needs"),
        "isolation_profile": _text(isolation_profile, "isolation profile", 128,
                                   pattern=_IDENTIFIER),
        "migration_policy": _choice(migration_policy, {"none", "compatible", "required"},
                                    "migration policy"),
        "uninstall_policy": _choice(uninstall_policy, {"retain_records", "block_if_bound"},
                                    "uninstall policy"),
    }
    canonical_manifest_bytes(value)
    return value


def build_manifest(
    *,
    extension_id,
    extension_version,
    extension_kind,
    artifact_type,
    artifact_sha256,
    source_kind,
    source_locator,
    provenance_sha256,
    license_expression,
    entrypoint_protocol,
    entrypoint_name,
    isolation_profile,
    extension_api="1.0.0",
    framework_min="0.1.0",
    framework_max="0.1.99",
    schema_versions=("domain-v1",),
    config_schema=None,
    input_schema=None,
    output_schema=None,
    declared_grants=(),
    declared_resources=(),
    network_needs=(),
    filesystem_needs=(),
    secret_needs=(),
    migration_policy="none",
    uninstall_policy="retain_records",
):
    """Build inert manifest data without retaining rejected caller payloads in tracebacks."""
    message = None
    try:
        return _build_manifest(
            extension_id=extension_id,
            extension_version=extension_version,
            extension_kind=extension_kind,
            artifact_type=artifact_type,
            artifact_sha256=artifact_sha256,
            source_kind=source_kind,
            source_locator=source_locator,
            provenance_sha256=provenance_sha256,
            license_expression=license_expression,
            entrypoint_protocol=entrypoint_protocol,
            entrypoint_name=entrypoint_name,
            isolation_profile=isolation_profile,
            extension_api=extension_api,
            framework_min=framework_min,
            framework_max=framework_max,
            schema_versions=schema_versions,
            config_schema=config_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            declared_grants=declared_grants,
            declared_resources=declared_resources,
            network_needs=network_needs,
            filesystem_needs=filesystem_needs,
            secret_needs=secret_needs,
            migration_policy=migration_policy,
            uninstall_policy=uninstall_policy,
        )
    except ValueError as exc:
        message = str(exc) if str(exc) else "invalid extension manifest"
    (extension_id, extension_version, extension_kind, artifact_type, artifact_sha256,
     source_kind, source_locator, provenance_sha256, license_expression, entrypoint_protocol,
     entrypoint_name, isolation_profile, extension_api, framework_min, framework_max,
     schema_versions, config_schema, input_schema, output_schema, declared_grants,
     declared_resources, network_needs, filesystem_needs, secret_needs, migration_policy,
     uninstall_policy) = (None,) * 26
    raise ValueError(message)
