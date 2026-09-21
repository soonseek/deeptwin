"""Independent structural vectors for provider-only two-platform lineage."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.domain.refs import canonical_json
from app.extensions.candidate_contracts import (
    CandidateError,
    ExtensionServiceDescriptor,
    metadata_ref,
)
from app.extensions.lineage_contracts import LineageContractError, parse_lineage
from app.extensions.port_contracts import PORT_SCHEMA_SHAPES
from app.tests.extension_candidate_fixture import candidate_payload

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas" / "v1" / "extensions" / "ports" / "provider-port-v1"
INSTANCE_ID = "1" * 32
PLATFORMS = ("linux/amd64", "linux/arm64")


def shipped_schema_bytes() -> tuple[bytes, bytes, bytes, bytes]:
    return tuple(
        (SCHEMA_ROOT / f"{role}.schema.json").read_bytes()
        for role in PORT_SCHEMA_SHAPES
    )


def provider_identity_fixture(platform: str, schema_bytes: tuple[bytes, ...]) -> dict:
    return {
        "schema_version": "extension-build-identity-v2",
        "extension_id": "synthetic-provider",
        "extension_version": "1.0.0",
        "platform": platform,
        "port_contract_version": "provider-port-v1",
        "worker_profile": "claude-text-transform-v1",
        "inputs": {
            "schema_version": "extension-build-inputs-v1",
            "source_bundle": {"sha256": "1" * 64, "size_bytes": 1},
            "build_recipe": {"sha256": "2" * 64, "size_bytes": 2},
            "dependency_input_set": {"sha256": "3" * 64, "size_bytes": 3},
        },
        "entrypoint": {
            "sha256": ("4" if platform == "linux/amd64" else "5") * 64,
            "size_bytes": 100,
        },
        "port_schemas": [
            {"role": role, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            for role, raw in zip(
                ("config", "request", "result", "error"), schema_bytes, strict=True
            )
        ],
    }


def lineage_mapping(*, layer_count: int = 2, repeated: bool = False) -> dict:
    source = candidate_payload()["service_descriptor"]
    schemas = shipped_schema_bytes()
    measured = deepcopy(source["platforms"])
    media = (
        "application/vnd.oci.image.layer.v1.tar",
        "application/vnd.oci.image.layer.v1.tar+gzip",
        "application/vnd.oci.image.layer.v1.tar+zstd",
    )
    for platform_index, entry in enumerate(measured):
        entry["manifest"] = {
            "media_type": "application/vnd.oci.image.manifest.v1+json",
            "digest": "sha256:" + ("a" if platform_index == 0 else "b") * 64,
            "size_bytes": 201 + platform_index,
        }
        entry["config"] = {
            "media_type": "application/vnd.oci.image.config.v1+json",
            "digest": "sha256:" + ("c" if platform_index == 0 else "d") * 64,
            "size_bytes": 301 + platform_index,
        }
        entry["layers"] = [
            {
                "position": position,
                "media_type": media[(position - 1) % len(media)],
                "digest": "sha256:"
                + (
                    "e"
                    if repeated
                    else format((platform_index * 7 + position) % 16, "x")
                )
                * 64,
                "size_bytes": 400 + position,
            }
            for position in range(1, layer_count + 1)
        ]
    return {
        "schema_version": "extension-build-lineage-v2",
        "extension_id": "synthetic-provider",
        "extension_version": "1.0.0",
        "port_contract_version": "provider-port-v1",
        "launch_profile": "provider-private-transform-v1",
        "index": {
            "media_type": "application/vnd.oci.image.index.v1+json",
            "digest": "sha256:" + "f" * 64,
            "size_bytes": 101,
        },
        "platforms": [
            {
                "measured_platform_entry": entry,
                "build_identity": provider_identity_fixture(entry["platform"], schemas),
                "extraction_evidence_sha256": ("6" if index == 0 else "7") * 64,
            }
            for index, entry in enumerate(measured)
        ],
    }


def parsed_lineage(*, layer_count: int = 2, repeated: bool = False):
    from app.extensions.provider_lineage import parse_provider_lineage

    mapping = lineage_mapping(layer_count=layer_count, repeated=repeated)
    return parse_provider_lineage(canonical_json(mapping)), mapping


def descriptor_for(lineage, *, instance_id: str = INSTANCE_ID, slot: int = 1):
    value = candidate_payload()["service_descriptor"]
    lineage_value = lineage.as_dict()
    value["extension_id"] = lineage_value["extension_id"]
    value["extension_version"] = lineage_value["extension_version"]
    value["port_contract_version"] = lineage_value["port_contract_version"]
    value["index"] = deepcopy(lineage_value["index"])
    value["platforms"] = [
        deepcopy(item["measured_platform_entry"])
        for item in lineage_value["platforms"]
    ]
    value["evidence"]["provenance_ref"] = metadata_ref(
        "provenance", lineage.content_bytes
    )
    value["command"] = {
        "protocol_id": "deeptwin-extension-worker-v1",
        "argv": [
            "/opt/deeptwin-extension/bin/worker",
            "--instance-id",
            instance_id,
            "--slot-number",
            str(slot),
        ],
    }
    return ExtensionServiceDescriptor.from_mapping(value)


def replace_path(value: dict, path: tuple[object, ...], replacement: object) -> dict:
    changed = deepcopy(value)
    target = changed
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    return changed


def assert_invalid(callable_, *args, **kwargs) -> None:
    from app.extensions.provider_lineage import ProviderLineageError

    with pytest.raises(ProviderLineageError, match="^invalid provider lineage value$"):
        callable_(*args, **kwargs)


def test_valid_provider_lineage_join_and_literal_projection():
    from app.extensions.provider_lineage import validate_provider_descriptor_lineage

    lineage, mapping = parsed_lineage(repeated=True)
    descriptor = descriptor_for(lineage, slot=16)
    assert (
        validate_provider_descriptor_lineage(
            lineage,
            descriptor,
            instance_id=INSTANCE_ID,
            slot_number=16,
            schema_bytes=shipped_schema_bytes(),
        )
        is None
    )
    entry = mapping["platforms"][1]["measured_platform_entry"]
    expected = {
        "platform": "linux/arm64",
        "index_digest": "sha256:" + "f" * 64,
        "manifest_digest": entry["manifest"]["digest"],
        "config_digest": entry["config"]["digest"],
        "ordered_layer_digests": ["sha256:" + "e" * 64] * 2,
    }
    assert lineage.selected_platform("linux/arm64") == expected


def test_value_hashes_detachment_constructor_and_immutability():
    from app.extensions.provider_lineage import ProviderLineage

    lineage, mapping = parsed_lineage()
    raw = canonical_json(mapping)
    expected = lineage.selected_platform("linux/amd64")
    assert lineage.content_bytes == raw
    assert lineage.digest == hashlib.sha256(raw).hexdigest()
    assert lineage.selected_platform_digest("linux/amd64") == hashlib.sha256(
        canonical_json(expected)
    ).hexdigest()
    mapping_copy = lineage.as_dict()
    mapping_copy["index"]["digest"] = "sha256:" + "0" * 64
    expected["ordered_layer_digests"].clear()
    assert lineage.as_dict() == mapping
    assert len(lineage.selected_platform("linux/amd64")["ordered_layer_digests"]) == 2
    with pytest.raises(TypeError):
        ProviderLineage()
    with pytest.raises((AttributeError, TypeError)):
        lineage.content_bytes = b"{}"


@pytest.mark.parametrize(
    "platform", [None, b"linux/amd64", "LINUX/AMD64", "linux/386", " linux/amd64"]
)
def test_projection_accessors_reject_nonexact_platform(platform):
    lineage, _ = parsed_lineage()
    assert_invalid(lineage.selected_platform, platform)
    assert_invalid(lineage.selected_platform_digest, platform)


@pytest.mark.parametrize(
    "path,bad",
    [
        (("schema_version",), "extension-build-lineage-v1"),
        (("extension_id",), "Synthetic-Provider"),
        (("extension_id",), "a" * 129),
        (("extension_version",), "01.0.0"),
        (("extension_version",), "2147483648.0.0"),
        (("port_contract_version",), "tool-port-v1"),
        (("launch_profile",), "extension-fixed-slot-argv-v1"),
        (("index", "media_type"), "application/octet-stream"),
        (("index", "digest"), "sha256:" + "A" * 64),
        (("index", "size_bytes"), True),
        (("index", "size_bytes"), 2**40 + 1),
        (("platforms", 0, "extraction_evidence_sha256"), "A" * 64),
        (("platforms", 0, "build_identity", "extension_id"), "other-provider"),
        (("platforms", 0, "build_identity", "extension_version"), "2.0.0"),
        (("platforms", 0, "build_identity", "platform"), "linux/arm64"),
        (("platforms", 0, "build_identity", "port_contract_version"), "tool-port-v1"),
        (("platforms", 0, "build_identity", "worker_profile"), "other"),
        (("platforms", 0, "build_identity", "schema_version"), "extension-build-identity-v1"),
        (("platforms", 1, "measured_platform_entry", "platform"), "linux/amd64"),
        (("platforms", 0, "measured_platform_entry", "manifest", "media_type"), "bad"),
        (("platforms", 0, "measured_platform_entry", "manifest", "digest"), "bad"),
        (("platforms", 0, "measured_platform_entry", "manifest", "size_bytes"), 0),
        (("platforms", 0, "measured_platform_entry", "config", "media_type"), "bad"),
        (("platforms", 0, "measured_platform_entry", "config", "digest"), "bad"),
        (("platforms", 0, "measured_platform_entry", "config", "size_bytes"), 0),
        (("platforms", 0, "measured_platform_entry", "layers", 0, "position"), 2),
        (("platforms", 0, "measured_platform_entry", "layers", 0, "media_type"), "bad"),
        (("platforms", 0, "measured_platform_entry", "layers", 0, "digest"), "bad"),
        (("platforms", 0, "measured_platform_entry", "layers", 0, "size_bytes"), 0),
    ],
)
def test_parser_rejects_scalar_relationship_oci_and_bound_mutations(path, bad):
    from app.extensions.provider_lineage import parse_provider_lineage

    assert_invalid(parse_provider_lineage, canonical_json(replace_path(lineage_mapping(), path, bad)))


def test_parser_requires_exact_two_platform_order_and_closed_objects():
    from app.extensions.provider_lineage import parse_provider_lineage

    one = lineage_mapping()
    one["platforms"].pop()
    reversed_platforms = lineage_mapping()
    reversed_platforms["platforms"].reverse()
    duplicate = lineage_mapping()
    duplicate["platforms"].append(deepcopy(duplicate["platforms"][0]))
    unknown = lineage_mapping()
    unknown["platforms"][0]["measured_platform_entry"]["verified"] = True
    for changed in (one, reversed_platforms, duplicate, unknown):
        assert_invalid(parse_provider_lineage, canonical_json(changed))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xef\xbb\xbf{}",
        b'{"schema_version":"extension-build-lineage-v2","schema_version":"extension-build-lineage-v2"}',
        b'{"schema_version":"extension-build-lineage-v2" }',
        b'{"schema_version":"extension-build-lineage-v2","x":1.0}',
        b'{"schema_version":"extension-build-lineage-v2","x":NaN}',
        b'{"schema_version":"extension-build-lineage-v2","x":null}',
        b'"extension-build-lineage-v2"',
        b"\xff",
        "not-bytes",
    ],
)
def test_parser_rejects_malformed_noncanonical_or_wrong_input_with_fixed_error(raw):
    from app.extensions.provider_lineage import parse_provider_lineage

    assert_invalid(parse_provider_lineage, raw)


def test_parser_wire_caps_and_128_layers_with_repeated_digests():
    from app.extensions.provider_lineage import parse_provider_lineage

    lineage, mapping = parsed_lineage(layer_count=128, repeated=True)
    assert len(lineage.content_bytes) <= 65_536
    assert lineage.selected_platform("linux/amd64")["ordered_layer_digests"] == [
        "sha256:" + "e" * 64
    ] * 128
    descriptor = descriptor_for(lineage, slot=16)
    from app.extensions.provider_lineage import validate_provider_descriptor_lineage

    assert validate_provider_descriptor_lineage(
        lineage,
        descriptor,
        instance_id=INSTANCE_ID,
        slot_number=16,
        schema_bytes=shipped_schema_bytes(),
    ) is None
    too_many = deepcopy(mapping)
    too_many["platforms"][0]["measured_platform_entry"]["layers"].append(
        {**too_many["platforms"][0]["measured_platform_entry"]["layers"][-1], "position": 129}
    )
    assert_invalid(parse_provider_lineage, canonical_json(too_many))
    assert_invalid(parse_provider_lineage, b"{" + b" " * 65_535 + b"}")


def test_parser_accepts_independently_set_exact_numeric_boundaries():
    from app.extensions.provider_lineage import parse_provider_lineage

    mapping = lineage_mapping()
    mapping["extension_version"] = "2147483647.2147483647.2147483647"
    mapping["index"]["size_bytes"] = 2**40
    for item in mapping["platforms"]:
        identity = item["build_identity"]
        identity["extension_version"] = mapping["extension_version"]
        for name in ("source_bundle", "build_recipe", "dependency_input_set"):
            identity["inputs"][name]["size_bytes"] = 1_073_741_824
        identity["entrypoint"]["size_bytes"] = 16_777_216
        for declaration in identity["port_schemas"]:
            declaration["size_bytes"] = 262_144
        entry = item["measured_platform_entry"]
        entry["manifest"]["size_bytes"] = 2**40
        entry["config"]["size_bytes"] = 2**40
        for layer in entry["layers"]:
            layer["size_bytes"] = 2**40
    assert parse_provider_lineage(canonical_json(mapping)).as_dict() == mapping


@pytest.mark.parametrize(
    "identity_index,path,bad",
    [
        (0, ("port_schemas", 0, "role"), "request"),
        (1, ("port_schemas", 3, "role"), "result"),
        (1, ("worker_profile",), "other"),
    ],
)
def test_parser_rejects_either_identity_schema_or_profile_drift(identity_index, path, bad):
    from app.extensions.provider_lineage import parse_provider_lineage

    mapping = lineage_mapping()
    identity = mapping["platforms"][identity_index]["build_identity"]
    changed_identity = replace_path(identity, path, bad)
    mapping["platforms"][identity_index]["build_identity"] = changed_identity
    assert_invalid(parse_provider_lineage, canonical_json(mapping))


@pytest.mark.parametrize(
    "case",
    [
        "not_tuple",
        "wrong_count",
        "wrong_type",
        "order",
        "truncated",
        "second_identity_hash",
        "first_identity_size",
    ],
)
def test_join_requires_exact_schema_tuple_for_both_embedded_identities(case):
    from app.extensions.provider_lineage import (
        parse_provider_lineage,
        validate_provider_descriptor_lineage,
    )

    mapping = lineage_mapping()
    raw: object = shipped_schema_bytes()
    if case == "not_tuple":
        raw = list(raw)
    elif case == "wrong_count":
        raw = raw[:3]
    elif case == "wrong_type":
        raw = (raw[0], raw[1], bytearray(raw[2]), raw[3])
    elif case == "order":
        raw = (raw[1], raw[0], raw[2], raw[3])
    elif case == "truncated":
        raw = (raw[0][:-1], raw[1], raw[2], raw[3])
    elif case == "second_identity_hash":
        mapping["platforms"][1]["build_identity"]["port_schemas"][3]["sha256"] = "0" * 64
    else:
        mapping["platforms"][0]["build_identity"]["port_schemas"][2]["size_bytes"] = 1
    lineage = parse_provider_lineage(canonical_json(mapping))
    assert_invalid(
        validate_provider_descriptor_lineage,
        lineage,
        descriptor_for(lineage),
        instance_id=INSTANCE_ID,
        slot_number=1,
        schema_bytes=raw,
    )


@pytest.mark.parametrize(
    "path,bad",
    [
        (("extension_id",), "other-provider"),
        (("extension_version",), "2.0.0"),
        (("port_contract_version",), "tool-port-v1"),
        (("index", "digest"), "sha256:" + "0" * 64),
        (("platforms", 0, "manifest", "media_type"), "application/octet-stream"),
        (("platforms", 0, "manifest", "digest"), "sha256:" + "0" * 64),
        (("platforms", 0, "manifest", "size_bytes"), 999),
        (("platforms", 1, "config", "media_type"), "application/octet-stream"),
        (("platforms", 1, "config", "digest"), "sha256:" + "0" * 64),
        (("platforms", 1, "config", "size_bytes"), 999),
        (("platforms", 0, "layers", 0, "position"), 2),
        (("platforms", 0, "layers", 0, "media_type"), "application/vnd.oci.image.layer.v1.tar+gzip"),
        (("platforms", 0, "layers", 0, "digest"), "sha256:" + "0" * 64),
        (("platforms", 0, "layers", 0, "size_bytes"), 999),
        (("evidence", "provenance_ref", "document_kind"), "sbom"),
        (("evidence", "provenance_ref", "sha256"), "0" * 64),
        (("evidence", "provenance_ref", "size_bytes"), 1),
        (("command", "protocol_id"), "other-protocol"),
        (("command", "argv", 0), "/other/worker"),
        (("command", "argv", 1), "--slot-number"),
        (("command", "argv", 2), "2" * 32),
        (("command", "argv", 3), "--instance-id"),
        (("command", "argv", 4), "2"),
    ],
)
def test_join_rejects_full_descriptor_provenance_and_argv_drift(path, bad):
    from app.extensions.provider_lineage import validate_provider_descriptor_lineage

    lineage, _ = parsed_lineage()
    value = descriptor_for(lineage).as_dict()
    value = replace_path(value, path, bad)
    try:
        descriptor = ExtensionServiceDescriptor.from_mapping(value)
    except CandidateError:
        # Invalid Candidate shapes must still be sanitized when presented as forged bytes.
        descriptor = object.__new__(ExtensionServiceDescriptor)
        object.__setattr__(descriptor, "content_bytes", canonical_json(value))
    assert_invalid(
        validate_provider_descriptor_lineage,
        lineage,
        descriptor,
        instance_id=INSTANCE_ID,
        slot_number=1,
        schema_bytes=shipped_schema_bytes(),
    )


@pytest.mark.parametrize(
    "instance_id,slot", [("A" * 32, 1), ("1" * 31, 1), (b"1" * 32, 1), (INSTANCE_ID, True), (INSTANCE_ID, 0), (INSTANCE_ID, 17)]
)
def test_join_rejects_nonexact_instance_and_slot_bounds(instance_id, slot):
    from app.extensions.provider_lineage import validate_provider_descriptor_lineage

    lineage, _ = parsed_lineage()
    assert_invalid(
        validate_provider_descriptor_lineage,
        lineage,
        descriptor_for(lineage),
        instance_id=instance_id,
        slot_number=slot,
        schema_bytes=shipped_schema_bytes(),
    )


def test_all_accessors_and_join_reject_hollow_forged_and_subclass_objects():
    from app.extensions.provider_lineage import (
        ProviderLineage,
        validate_provider_descriptor_lineage,
    )

    class FalseLineage(ProviderLineage):
        pass

    valid, _ = parsed_lineage()
    hollow = object.__new__(ProviderLineage)
    forged = object.__new__(ProviderLineage)
    object.__setattr__(forged, "content_bytes", b"{}")
    nonbytes = object.__new__(ProviderLineage)
    object.__setattr__(nonbytes, "content_bytes", bytearray(valid.content_bytes))
    subclass = object.__new__(FalseLineage)
    object.__setattr__(subclass, "content_bytes", valid.content_bytes)
    for value in (hollow, forged, nonbytes, subclass):
        assert_invalid(lambda item=value: item.digest)
        assert_invalid(value.as_dict)
        assert_invalid(value.selected_platform, "linux/amd64")
        assert_invalid(value.selected_platform_digest, "linux/amd64")
        assert_invalid(
            validate_provider_descriptor_lineage,
            value,
            descriptor_for(valid),
            instance_id=INSTANCE_ID,
            slot_number=1,
            schema_bytes=shipped_schema_bytes(),
        )
    descriptor = descriptor_for(valid)
    hollow_descriptor = object.__new__(ExtensionServiceDescriptor)
    forged_descriptor = object.__new__(ExtensionServiceDescriptor)
    object.__setattr__(forged_descriptor, "content_bytes", b"{}")

    class FalseDescriptor(ExtensionServiceDescriptor):
        pass

    subclass_descriptor = object.__new__(FalseDescriptor)
    object.__setattr__(subclass_descriptor, "content_bytes", descriptor.content_bytes)
    for bad_descriptor in (hollow_descriptor, forged_descriptor, subclass_descriptor):
        assert_invalid(
            validate_provider_descriptor_lineage,
            valid,
            bad_descriptor,
            instance_id=INSTANCE_ID,
            slot_number=1,
            schema_bytes=shipped_schema_bytes(),
        )


def test_tool_and_provider_lineages_remain_separate():
    from app.extensions.provider_lineage import parse_provider_lineage

    provider_raw = canonical_json(lineage_mapping())
    assert_invalid(parse_provider_lineage, canonical_json({**lineage_mapping(), "schema_version": "extension-build-lineage-v1"}))
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        parse_lineage(provider_raw)


def test_schema_export_parity_validity_freshness_and_single_identity_resource():
    from app.extensions.provider_identity_schema_exports import (
        provider_build_identity_schema,
    )
    from app.extensions.provider_lineage_schema_exports import (
        exported_schemas,
        provider_lineage_schema,
    )

    schema = provider_lineage_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "urn:deeptwin:schemas:v2:extensions:provider-build-lineage-v2"
    assert schema["$defs"]["provider_identity"] == provider_build_identity_schema()
    encoded_schema = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    shipped = ROOT / "schemas/v2/extensions/provider-build-lineage-v2.schema.json"
    assert shipped.read_text(encoding="utf-8") == encoded_schema
    assert exported_schemas() == {"provider-build-lineage-v2.schema.json": schema}
    assert encoded_schema.count("urn:deeptwin:schemas:v2:extensions:provider-build-identity-v2") == 1
    schema["properties"].clear()
    assert provider_lineage_schema()["properties"]
    exported_schemas()["provider-build-lineage-v2.schema.json"]["required"].clear()
    assert provider_lineage_schema()["required"]


def test_fresh_import_has_no_runtime_worker_network_sdk_or_credentials_side_effects():
    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
before = set(sys.modules)
import app.extensions.provider_lineage
import app.extensions.provider_lineage_schema_exports
loaded = set(sys.modules) - before
blocked = [name for name in loaded if name.startswith(('app.runtime', 'app.workers', 'anthropic', 'httpx', 'requests'))]
assert not blocked, blocked
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
