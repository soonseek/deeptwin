"""Independent structural vectors for immutable extension image lineage values."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.domain.refs import canonical_json
from app.extensions.candidate_contracts import ExtensionServiceDescriptor, metadata_ref
from app.extensions.lineage_contracts import (
    BuildIdentity,
    LineageContractError,
    LineageEvidence,
    parse_build_identity,
    parse_lineage,
    validate_descriptor_lineage,
    validate_schema_bytes,
)
from app.extensions.lineage_schema_exports import (
    build_identity_schema,
    exported_schemas,
    lineage_schema,
)
from app.extensions.port_contracts import PORT_SCHEMA_SHAPES
from app.tests.extension_candidate_fixture import candidate_payload

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas" / "v1" / "extensions"
PORT_SCHEMA_ROOT = SCHEMA_ROOT / "ports" / "tool-port-v1"
INSTANCE_ID = "1" * 32


def shipped_schema_bytes() -> tuple[bytes, bytes, bytes, bytes]:
    return tuple(
        (PORT_SCHEMA_ROOT / f"{role}.schema.json").read_bytes()
        for role in PORT_SCHEMA_SHAPES
    )


def identity_mapping(platform: str = "linux/amd64") -> dict:
    marker = "a" if platform == "linux/amd64" else "b"
    schemas = shipped_schema_bytes()
    return {
        "schema_version": "extension-build-identity-v1",
        "extension_id": "synthetic-tool",
        "extension_version": "1.0.0",
        "platform": platform,
        "port_contract_version": "tool-port-v1",
        "inputs": {
            "schema_version": "extension-build-inputs-v1",
            "source_bundle": {"sha256": marker * 64, "size_bytes": 1},
            "build_recipe": {
                "sha256": ("c" if marker == "a" else "d") * 64,
                "size_bytes": 2,
            },
            "dependency_input_set": {
                "sha256": ("e" if marker == "a" else "f") * 64,
                "size_bytes": 3,
            },
        },
        "entrypoint": {
            "sha256": ("1" if marker == "a" else "2") * 64,
            "size_bytes": 16_777_216,
        },
        "port_schemas": [
            {
                "role": role,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
            for role, raw in zip(PORT_SCHEMA_SHAPES, schemas, strict=True)
        ],
    }


def lineage_mapping(*, layer_count: int = 2, repeated: bool = False) -> dict:
    descriptor = candidate_payload()["service_descriptor"]
    platforms = deepcopy(descriptor["platforms"])
    for platform_index, entry in enumerate(platforms):
        layers = []
        for position in range(1, layer_count + 1):
            digest_character = (
                "7" if repeated else format((platform_index * 3 + position) % 16, "x")
            )
            layers.append(
                {
                    "position": position,
                    "media_type": (
                        "application/vnd.oci.image.layer.v1.tar+gzip"
                        if position % 2
                        else "application/vnd.oci.image.layer.v1.tar+zstd"
                    ),
                    "digest": "sha256:" + digest_character * 64,
                    "size_bytes": 100 + position,
                }
            )
        entry["layers"] = layers
    return {
        "schema_version": "extension-build-lineage-v1",
        "extension_id": "synthetic-tool",
        "extension_version": "1.0.0",
        "port_contract_version": "tool-port-v1",
        "launch_profile": "extension-fixed-slot-argv-v1",
        "index": deepcopy(descriptor["index"]),
        "platforms": [
            {
                "measured_platform_entry": entry,
                "build_identity": identity_mapping(entry["platform"]),
                "extraction_evidence_sha256": ("8" if index == 0 else "9") * 64,
            }
            for index, entry in enumerate(platforms)
        ],
    }


def parsed_lineage(
    *, layer_count: int = 2, repeated: bool = False
) -> tuple[LineageEvidence, dict]:
    mapping = lineage_mapping(layer_count=layer_count, repeated=repeated)
    return parse_lineage(canonical_json(mapping)), mapping


def descriptor_for(
    lineage: LineageEvidence, *, slot: int = 1
) -> ExtensionServiceDescriptor:
    value = candidate_payload()["service_descriptor"]
    lineage_value = lineage.as_dict()
    value["index"] = deepcopy(lineage_value["index"])
    value["platforms"] = [
        deepcopy(item["measured_platform_entry"]) for item in lineage_value["platforms"]
    ]
    value["evidence"]["provenance_ref"] = metadata_ref(
        "provenance", lineage.content_bytes
    )
    value["command"] = {
        "protocol_id": "deeptwin-extension-worker-v1",
        "argv": [
            "/opt/deeptwin-extension/bin/worker",
            "--instance-id",
            INSTANCE_ID,
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


def assert_invalid(parser, raw) -> None:
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        parser(raw)


def test_build_identity_is_canonical_immutable_and_uses_independent_hashes():
    mapping = identity_mapping()
    raw = canonical_json(mapping)
    value = parse_build_identity(raw)
    assert value.content_bytes == raw
    assert value.digest == hashlib.sha256(raw).hexdigest()
    assert (
        value.input_digest
        == hashlib.sha256(canonical_json(mapping["inputs"])).hexdigest()
    )
    assert (
        value.schema_set_digest
        == hashlib.sha256(canonical_json(mapping["port_schemas"])).hexdigest()
    )
    detached = value.as_dict()
    detached["entrypoint"]["sha256"] = "0" * 64
    assert value.content_bytes == raw
    assert value.as_dict() == mapping
    with pytest.raises(TypeError):
        BuildIdentity()


def test_lineage_projection_is_detached_and_hashed_from_literal_shape():
    value, mapping = parsed_lineage()
    raw = canonical_json(mapping)
    assert value.content_bytes == raw
    assert value.digest == hashlib.sha256(raw).hexdigest()
    entry = mapping["platforms"][1]["measured_platform_entry"]
    expected = {
        "platform": "linux/arm64",
        "index_digest": mapping["index"]["digest"],
        "manifest_digest": entry["manifest"]["digest"],
        "config_digest": entry["config"]["digest"],
        "ordered_layer_digests": [layer["digest"] for layer in entry["layers"]],
    }
    projection = value.selected_platform("linux/arm64")
    assert projection == expected
    assert (
        value.selected_platform_digest("linux/arm64")
        == hashlib.sha256(canonical_json(expected)).hexdigest()
    )
    projection["ordered_layer_digests"].clear()
    detached = value.as_dict()
    detached["index"]["digest"] = "sha256:" + "0" * 64
    assert value.selected_platform("linux/arm64") == expected
    with pytest.raises(TypeError):
        LineageEvidence()


@pytest.mark.parametrize(
    "platform", [None, b"linux/amd64", "LINUX/AMD64", "linux/386", " linux/amd64"]
)
def test_selected_platform_rejects_every_nonexact_value(platform):
    value, _ = parsed_lineage()
    assert_invalid(value.selected_platform, platform)
    assert_invalid(value.selected_platform_digest, platform)


def test_actual_schema_bytes_validate_in_fixed_role_order_including_large_result():
    raw = shipped_schema_bytes()
    assert len(raw[2]) > 65_536
    identity = parse_build_identity(canonical_json(identity_mapping()))
    assert validate_schema_bytes(identity, raw) is None


@pytest.mark.parametrize(
    "case",
    ["not_tuple", "wrong_count", "wrong_type", "order", "truncated", "oversized"],
)
def test_schema_byte_validation_requires_exact_actual_bytes(case):
    identity = parse_build_identity(canonical_json(identity_mapping()))
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
    else:
        raw = (raw[0], raw[1], b"x" * 262_145, raw[3])
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        validate_schema_bytes(identity, raw)  # type: ignore[arg-type]


def test_schema_byte_validation_revalidates_the_identity_value_bytes():
    forged_mapping = identity_mapping()
    forged_mapping["extension_id"] = "NOT-CANONICAL"
    forged = object.__new__(BuildIdentity)
    object.__setattr__(forged, "content_bytes", canonical_json(forged_mapping))
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        validate_schema_bytes(forged, shipped_schema_bytes())


@pytest.mark.parametrize(
    "path,bad",
    [
        (("schema_version",), "extension-build-identity-v2"),
        (("extension_id",), "Synthetic-Tool"),
        (("extension_id",), "a" * 129),
        (("extension_version",), "01.0.0"),
        (("extension_version",), "2147483648.0.0"),
        (("extension_version",), "1.0"),
        (("platform",), "linux/386"),
        (("port_contract_version",), "provider-port-v1"),
        (("inputs", "schema_version"), "extension-build-inputs-v2"),
        (("inputs", "source_bundle", "sha256"), "A" * 64),
        (("inputs", "source_bundle", "size_bytes"), True),
        (("inputs", "source_bundle", "size_bytes"), 0),
        (("inputs", "source_bundle", "size_bytes"), 1_073_741_825),
        (("entrypoint", "size_bytes"), 16_777_217),
        (("port_schemas", 0, "role"), "request"),
        (("port_schemas", 0, "size_bytes"), 262_145),
    ],
)
def test_build_identity_rejects_closed_scalar_and_bound_mutations(path, bad):
    mapping = identity_mapping()
    assert_invalid(
        parse_build_identity, canonical_json(replace_path(mapping, path, bad))
    )


def test_build_identity_accepts_exact_numeric_caps_and_rejects_unknown_fields():
    mapping = identity_mapping()
    for field in mapping["inputs"].values():
        if isinstance(field, dict):
            field["size_bytes"] = 1_073_741_824
    mapping["entrypoint"]["size_bytes"] = 16_777_216
    for schema in mapping["port_schemas"]:
        schema["size_bytes"] = 262_144
    assert parse_build_identity(canonical_json(mapping)).as_dict() == mapping
    mapping["verified"] = True
    assert_invalid(parse_build_identity, canonical_json(mapping))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xef\xbb\xbf{}",
        b'{"schema_version":"extension-build-identity-v1","schema_version":"extension-build-identity-v1"}',
        b'{"schema_version":"extension-build-identity-v1" }',
        b'{"schema_version":"extension-build-identity-v1","x":1.0}',
        b'{"schema_version":"extension-build-identity-v1","x":null}',
        b'"extension-build-identity-v1"',
        b"\xff",
        "not-bytes",
    ],
)
def test_build_identity_rejects_noncanonical_or_wrong_class_input_with_sanitized_error(
    raw,
):
    assert_invalid(parse_build_identity, raw)


def test_build_identity_rejects_escaped_surrogate_and_schema_role_reordering():
    raw = canonical_json(identity_mapping()).replace(
        b'"extension_id":"synthetic-tool"', b'"extension_id":"\\ud800"'
    )
    assert_invalid(parse_build_identity, raw)
    mapping = identity_mapping()
    mapping["port_schemas"].reverse()
    assert_invalid(parse_build_identity, canonical_json(mapping))


def test_build_identity_rejects_bytes_beyond_its_exact_wire_cap():
    assert_invalid(parse_build_identity, b"{" + b" " * 8_191 + b"}")


@pytest.mark.parametrize(
    "path,bad",
    [
        (("schema_version",), "extension-build-lineage-v2"),
        (("extension_id",), "other-tool"),
        (("extension_version",), "2147483648.0.0"),
        (("port_contract_version",), "provider-port-v1"),
        (("launch_profile",), "shell-v1"),
        (("index", "size_bytes"), True),
        (("index", "size_bytes"), 1_099_511_627_777),
        (("platforms", 0, "extraction_evidence_sha256"), "A" * 64),
        (("platforms", 0, "build_identity", "extension_id"), "other-tool"),
        (("platforms", 0, "build_identity", "platform"), "linux/arm64"),
        (("platforms", 1, "measured_platform_entry", "platform"), "linux/amd64"),
        (("platforms", 0, "measured_platform_entry", "layers", 0, "position"), True),
        (("platforms", 0, "measured_platform_entry", "layers", 0, "position"), 2),
        (
            ("platforms", 0, "measured_platform_entry", "layers", 0, "media_type"),
            "application/octet-stream",
        ),
    ],
)
def test_lineage_rejects_closed_scalar_relationship_and_bound_mutations(path, bad):
    mapping = lineage_mapping()
    if path == ("extension_id",):
        mapping["extension_id"] = bad
    else:
        mapping = replace_path(mapping, path, bad)
    assert_invalid(parse_lineage, canonical_json(mapping))


def test_lineage_requires_both_platforms_in_fixed_order_and_no_unknown_fields():
    mapping = lineage_mapping()
    only_one = deepcopy(mapping)
    only_one["platforms"].pop()
    reversed_platforms = deepcopy(mapping)
    reversed_platforms["platforms"].reverse()
    unknown = deepcopy(mapping)
    unknown["platforms"][0]["measured_platform_entry"]["manifest"]["verified"] = True
    for changed in (only_one, reversed_platforms, unknown):
        assert_invalid(parse_lineage, canonical_json(changed))


def test_lineage_preserves_repeated_digests_at_maximum_layer_count_and_caps():
    value, mapping = parsed_lineage(layer_count=128, repeated=True)
    assert len(value.content_bytes) <= 65_536
    assert [
        layer["position"]
        for layer in mapping["platforms"][0]["measured_platform_entry"]["layers"]
    ] == list(range(1, 129))
    projection = value.selected_platform("linux/amd64")
    assert projection["ordered_layer_digests"] == ["sha256:" + "7" * 64] * 128
    descriptor = descriptor_for(value, slot=16)
    assert (
        validate_descriptor_lineage(
            value, descriptor, instance_id=INSTANCE_ID, slot_number=16
        )
        is None
    )


def test_lineage_rejects_129_layers_and_oversized_or_noncanonical_bytes():
    mapping = lineage_mapping(layer_count=128)
    layers = mapping["platforms"][0]["measured_platform_entry"]["layers"]
    layers.append({**layers[-1], "position": 129})
    assert_invalid(parse_lineage, canonical_json(mapping))
    valid = canonical_json(lineage_mapping())
    assert_invalid(parse_lineage, valid + b" ")
    assert_invalid(parse_lineage, b"{" + b" " * 65_535 + b"}")


def test_descriptor_join_accepts_only_exact_complete_structural_match_for_slot_edges():
    lineage, _ = parsed_lineage()
    for slot in (1, 16):
        descriptor = descriptor_for(lineage, slot=slot)
        assert (
            validate_descriptor_lineage(
                lineage, descriptor, instance_id=INSTANCE_ID, slot_number=slot
            )
            is None
        )


def test_descriptor_join_rejects_a_structurally_valid_one_platform_descriptor():
    lineage, _ = parsed_lineage()
    changed = descriptor_for(lineage).as_dict()
    changed["platforms"].pop()
    descriptor = ExtensionServiceDescriptor.from_mapping(changed)
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        validate_descriptor_lineage(
            lineage, descriptor, instance_id=INSTANCE_ID, slot_number=1
        )


@pytest.mark.parametrize("field", ["media_type", "size_bytes", "digest", "order"])
def test_descriptor_join_rejects_nonselected_platform_tampering(field):
    lineage, _ = parsed_lineage()
    changed = descriptor_for(lineage).as_dict()
    platform = changed["platforms"][1]
    if field == "media_type":
        platform["layers"][0][field] = "application/vnd.oci.image.layer.v1.tar"
    elif field == "size_bytes":
        platform["config"][field] += 1
    elif field == "digest":
        platform["config"][field] = "sha256:" + "f" * 64
    else:
        first, second = platform["layers"]
        first["digest"], second["digest"] = second["digest"], first["digest"]
    descriptor = ExtensionServiceDescriptor.from_mapping(changed)
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        validate_descriptor_lineage(
            lineage, descriptor, instance_id=INSTANCE_ID, slot_number=1
        )


@pytest.mark.parametrize("field", ["size_bytes", "digest"])
def test_descriptor_join_rejects_index_tampering(field):
    lineage, _ = parsed_lineage()
    changed = descriptor_for(lineage).as_dict()
    if field == "size_bytes":
        changed["index"][field] += 1
    else:
        changed["index"][field] = "sha256:" + "f" * 64
    descriptor = ExtensionServiceDescriptor.from_mapping(changed)
    assert_invalid(
        lambda _: validate_descriptor_lineage(
            lineage, descriptor, instance_id=INSTANCE_ID, slot_number=1
        ),
        None,
    )


def test_descriptor_join_rejects_provenance_ref_independently_of_digest_like_fields():
    lineage, _ = parsed_lineage()
    changed = descriptor_for(lineage).as_dict()
    changed["evidence"]["provenance_ref"] = {
        "document_kind": "provenance",
        "sha256": lineage.digest,
        "size_bytes": len(lineage.content_bytes) + 1,
    }
    descriptor = ExtensionServiceDescriptor.from_mapping(changed)
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        validate_descriptor_lineage(
            lineage, descriptor, instance_id=INSTANCE_ID, slot_number=1
        )


@pytest.mark.parametrize(
    "argv",
    [
        [
            "/opt/deeptwin-extension/bin/worker",
            "--instance-id",
            INSTANCE_ID,
            "--slot-number",
            "01",
        ],
        [
            "/opt/deeptwin-extension/bin/worker",
            "--instance-id",
            INSTANCE_ID,
            "--slot-number",
            "1",
            "--verified",
        ],
        [
            "/opt/deeptwin-extension/bin/worker",
            "--slot-number",
            "1",
            "--instance-id",
            INSTANCE_ID,
        ],
        [
            "/opt/deeptwin-extension/bin/worker",
            "--instance-id",
            INSTANCE_ID,
            "--slot-number",
            "1",
            "--shell",
        ],
        ["/bin/sh", "--instance-id", INSTANCE_ID, "--slot-number", "1"],
    ],
)
def test_descriptor_join_rejects_extra_missing_reordered_or_semantic_argv(argv):
    lineage, _ = parsed_lineage()
    changed = descriptor_for(lineage).as_dict()
    changed["command"]["argv"] = argv
    descriptor = ExtensionServiceDescriptor.from_mapping(changed)
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        validate_descriptor_lineage(
            lineage, descriptor, instance_id=INSTANCE_ID, slot_number=1
        )


def test_descriptor_join_rejects_wrong_protocol_and_descriptor_identity_fields():
    lineage, _ = parsed_lineage()
    mutations = (
        ("protocol", ("command", "protocol_id"), "other-protocol"),
        ("id", ("extension_id",), "other-tool"),
        ("version", ("extension_version",), "2.0.0"),
        ("port", ("port_contract_version",), "provider-port-v1"),
    )
    for label, path, bad in mutations:
        changed = replace_path(descriptor_for(lineage).as_dict(), path, bad)
        if label == "protocol":
            changed["broker_endpoint"]["protocol_id"] = bad
        descriptor = ExtensionServiceDescriptor.from_mapping(changed)
        with pytest.raises(LineageContractError, match="^invalid lineage value$"):
            validate_descriptor_lineage(
                lineage, descriptor, instance_id=INSTANCE_ID, slot_number=1
            )


def test_current_descriptor_schema_rejects_command_config_and_environment_fields():
    lineage, _ = parsed_lineage()
    for field in ("config", "env"):
        changed = descriptor_for(lineage).as_dict()
        changed["command"][field] = {}
        with pytest.raises(ValueError):
            ExtensionServiceDescriptor.from_mapping(changed)


@pytest.mark.parametrize(
    "instance,slot",
    [
        ("A" * 32, 1),
        ("1" * 31, 1),
        (b"1" * 32, 1),
        (INSTANCE_ID, True),
        (INSTANCE_ID, 0),
        (INSTANCE_ID, 17),
        (INSTANCE_ID, "1"),
    ],
)
def test_descriptor_join_rejects_wrong_instance_and_slot_scalars(instance, slot):
    lineage, _ = parsed_lineage()
    descriptor = descriptor_for(lineage)
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        validate_descriptor_lineage(
            lineage, descriptor, instance_id=instance, slot_number=slot
        )


def test_descriptor_join_requires_exact_supported_value_classes():
    lineage, _ = parsed_lineage()
    descriptor = descriptor_for(lineage)
    for bad_lineage, bad_descriptor in (
        (lineage.as_dict(), descriptor),
        (lineage, descriptor.as_dict()),
    ):
        with pytest.raises(LineageContractError, match="^invalid lineage value$"):
            validate_descriptor_lineage(
                bad_lineage, bad_descriptor, instance_id=INSTANCE_ID, slot_number=1
            )
    with pytest.raises(LineageContractError, match="^invalid lineage value$"):
        validate_schema_bytes(lineage, shipped_schema_bytes())


def test_exported_schemas_are_deterministic_valid_and_match_runtime_shapes():
    exports = exported_schemas()
    assert tuple(exports) == (
        "build-identity-v1.schema.json",
        "build-lineage-v1.schema.json",
    )
    assert exports["build-identity-v1.schema.json"] == build_identity_schema()
    assert exports["build-lineage-v1.schema.json"] == lineage_schema()
    for name, schema in exports.items():
        Draft202012Validator.check_schema(schema)
        expected_id = "urn:deeptwin:schemas:v1:extensions:" + name.removesuffix(
            ".schema.json"
        )
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == expected_id
        assert "structural" in schema["$comment"].lower()
        checked_in = SCHEMA_ROOT / name
        expected_bytes = (
            json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        assert checked_in.read_bytes() == expected_bytes
    assert Draft202012Validator(build_identity_schema()).is_valid(identity_mapping())
    assert Draft202012Validator(lineage_schema()).is_valid(lineage_mapping())


def test_schema_and_runtime_agree_on_closed_order_and_boolean_shapes():
    identity_validator = Draft202012Validator(build_identity_schema())
    lineage_validator = Draft202012Validator(lineage_schema())
    identity = identity_mapping()
    identity["entrypoint"]["size_bytes"] = True
    lineage = lineage_mapping()
    lineage["platforms"].reverse()
    for validator, parser, value in (
        (identity_validator, parse_build_identity, identity),
        (lineage_validator, parse_lineage, lineage),
    ):
        assert not validator.is_valid(value)
        assert_invalid(parser, canonical_json(value))
    overflow = identity_mapping()
    overflow["extension_version"] = "2147483648.0.0"
    assert identity_validator.is_valid(overflow)
    assert_invalid(parse_build_identity, canonical_json(overflow))


def test_existing_68_schema_artifacts_remain_byte_identical():
    manifest = (
        ROOT
        / ".superpowers"
        / "sdd"
        / "resumption-plan"
        / "task-22-schema-before.sha256"
    )
    entries = [
        line.split(maxsplit=1) for line in manifest.read_text().splitlines() if line
    ]
    assert len(entries) == 68
    for expected, relative in entries:
        path = ROOT / relative.lstrip(" *")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
