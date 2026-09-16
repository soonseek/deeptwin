"""Independent bounded candidate contract examples and negative cases."""

from copy import deepcopy
from hashlib import sha256

import pytest
from jsonschema import Draft202012Validator

from app.domain.refs import canonical_json
from app.tests.extension_candidate_fixture import candidate_payload


def parse(value):
    from app.extensions.candidate_contracts import parse_bundle

    return parse_bundle(value)


def refresh(value):
    raw = canonical_json(value["service_descriptor"])
    value["manifest"]["artifact"]["service_descriptor_ref"].update(sha256=sha256(raw).hexdigest(), size_bytes=len(raw))
    return value


def test_bundle_detaches_all_input_and_output():
    value = candidate_payload()
    expected = deepcopy(value)
    parsed = parse(value)
    value["manifest"]["source"]["locator"] = "changed"
    out = parsed.as_dict()
    out["service_descriptor"]["command"]["argv"].clear()
    assert parsed.as_dict() == expected
    assert parsed.manifest.as_dict() == expected["manifest"]
    assert parsed.descriptor.as_dict() == expected["service_descriptor"]


@pytest.mark.parametrize(
    "path,bad",
    [
        (("manifest", "schema_version"), "extension-manifest-v1"),
        (("manifest", "extension_id"), "id\n"),
        (("manifest", "extension_version"), "2147483648.0.0"),
        (("manifest", "extension_version"), "01.0.0"),
        (("manifest", "extension_kind"), "lens"),
        (("manifest", "qualified"), True),
        (("manifest", "source", "verified"), True),
        (("manifest", "compatibility", "framework_max"), "0.0.0"),
        (("manifest", "compatibility", "schema_versions"), ["uploaded-v1"]),
        (("manifest", "refinements", "config"), {"type": "object"}),
        (("manifest", "requirements", "grant_ids"), ["z", "a"]),
        (("service_descriptor", "uid"), True),
        (("service_descriptor", "uid"), 0),
        (("service_descriptor", "uid"), 2**32),
        (("service_descriptor", "service_identity"), "worker\n"),
        (("service_descriptor", "command", "argv"), ["relative"]),
        (("service_descriptor", "command", "argv"), ["/opt/../worker"]),
        (("service_descriptor", "command", "argv"), ["/opt//worker"]),
        (("service_descriptor", "broker_endpoint", "pair_gid"), 2001),
        (("service_descriptor", "broker_endpoint", "requester_uid"), 2001),
        (("service_descriptor", "broker_endpoint", "socket_mount_id"), "absent"),
        (("service_descriptor", "image_repository"), "example.test/tool:latest"),
        (("service_descriptor", "image_repository"), "EXAMPLE.test/tool"),
        (("service_descriptor", "image_repository"), "example.test/../tool"),
    ],
)
def test_closed_scalar_and_identity_rejections(path, bad):
    value = candidate_payload()
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad
    with pytest.raises(ValueError):
        parse(refresh(value))


@pytest.mark.parametrize(
    "locator",
    [
        "http://example.test",
        "https://EXAMPLE.test",
        "https://example.test:0443",
        "https://u:p@example.test",
        "https://example.test?token=secret",
        "https://example.test/#part",
        "https://example.test/a/../b",
        "https://example.test/%2E%2E",
        "https://example.test/a%2Fb",
        "https://example.test/a%5Cb",
        "https://example.test/%0A",
        "https://example.test/%aa",
        "https://example.test/é",
        "https://example.test./",
        "https://[::ffff:192.0.2.1]/",
        "https://[2001:0db8::1]/",
    ],
)
def test_unsafe_source_metadata_is_rejected_without_fetch(locator):
    value = candidate_payload()
    value["manifest"]["source"]["locator"] = locator
    with pytest.raises(ValueError):
        parse(value)


@pytest.mark.parametrize(
    "mode", ["missing", "unused", "duplicate", "digest", "kind", "size", "layers", "platforms", "mounts"]
)
def test_bundle_requires_exact_leaves_and_ordered_declarations(mode):
    value = candidate_payload()
    if mode == "missing":
        value["documents"].pop()
    elif mode == "unused":
        value["documents"].append({"document_kind": "sbom", "content": {"extra": True}})
    elif mode == "duplicate":
        value["documents"].append(deepcopy(value["documents"][0]))
    elif mode in {"digest", "size", "kind"}:
        ref = value["manifest"]["source"]["provenance_ref"]
        ref[{"digest": "sha256", "size": "size_bytes", "kind": "document_kind"}[mode]] = {
            "digest": "b" * 64,
            "size": 999,
            "kind": "sbom",
        }[mode]
    elif mode == "layers":
        value["service_descriptor"]["platforms"][0]["layers"][0]["position"] = 2
    elif mode == "platforms":
        value["service_descriptor"]["platforms"].reverse()
    elif mode == "mounts":
        value["service_descriptor"]["socket_mounts"][0]["container_path"] = "/host/socket"
    with pytest.raises(ValueError):
        parse(refresh(value))


def test_repeated_ordered_layers_argv_and_evidence_authority_text_are_inert():
    value = candidate_payload()
    layers = value["service_descriptor"]["platforms"][0]["layers"]
    layers.append({**layers[0], "position": 2})
    value["service_descriptor"]["command"]["argv"] += ["--serve"]
    assert parse(refresh(value)).as_dict() == value


def test_all_executable_core_catalog_tuples():
    from app.extensions.port_contracts import PORT_CONTRACTS

    for port, contract in PORT_CONTRACTS.items():
        value = candidate_payload()
        value["manifest"].update(extension_kind=contract.extension_kind, port_contract_version=port)
        value["manifest"]["artifact"]["artifact_form"] = contract.artifact_form
        value["service_descriptor"]["port_contract_version"] = port
        if contract.artifact_form == "code_free_definition":
            with pytest.raises(ValueError):
                parse(refresh(value))
        else:
            assert parse(refresh(value)).as_dict() == value


def test_structural_schemas_and_end_line_bool_parity():
    from app.extensions.candidate_schema_exports import exported_schemas, input_schema

    for schema in exported_schemas().values():
        Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(input_schema())
    assert validator.is_valid(candidate_payload())
    for field, bad in [("uid", True), ("service_identity", "worker\n"), ("extension_version", "1.0.0\n")]:
        value = candidate_payload()
        value["service_descriptor"][field] = bad
        assert not validator.is_valid(value)


@pytest.mark.parametrize("case", ["depth", "items", "surrogate", "float", "utf8_bytes", "aggregate"])
def test_canonical_and_aggregate_limits_precede_semantics(case):
    value = candidate_payload()
    if case == "depth":
        child = {}
        for _ in range(34):
            child = {"nested": child}
        value["documents"][0]["content"] = child
    elif case == "items":
        value["documents"][0]["content"] = {"items": [0] * 10001}
    elif case == "surrogate":
        value["manifest"]["license"]["expression"] = "\ud800"
    elif case == "float":
        value["service_descriptor"]["uid"] = 1.0
    elif case == "utf8_bytes":
        value["service_descriptor"]["command"]["argv"].append("한" * 86)
    else:
        value["documents"] = [{"document_kind": "license", "content": "x" * 65536} for _ in range(17)]
    with pytest.raises(ValueError):
        parse(value)


@pytest.mark.parametrize(
    "locator",
    [
        "https://example.test",
        "https://example.test:65535/a%20b",
        "https://127.0.0.1/metadata",
        "https://[2001:db8::1]:443/path",
    ],
)
def test_safe_metadata_locator_remains_only_text(locator):
    value = candidate_payload()
    value["manifest"]["source"]["locator"] = locator
    value["service_descriptor"]["image_repository"] = "registry.example.test/a__b/c---d"
    assert parse(refresh(value)).as_dict() == value


def test_candidate_event_is_exact_bounded_and_matches_structural_export():
    from app.domain.events import event_metadata, event_schema
    from app.domain.refs import DomainContractError

    value = {"extension_kind": "tool", "port_contract_version": "tool-port-v1", "candidate_count": 1, "byte_count": 100}
    schema = Draft202012Validator(event_schema("extension.candidate_registered"))
    assert schema.is_valid(value)
    for patch in ({"candidate_count": 0}, {"candidate_count": 2}, {"byte_count": 1114113}, {"byte_count": True}):
        bad = {**value, **patch}
        assert not schema.is_valid(bad)
        with pytest.raises(DomainContractError):
            event_metadata("extension.candidate_registered", bad)


def test_structural_refinement_keywords_are_closed_recursively():
    from app.extensions.candidate_schema_exports import input_schema

    value = candidate_payload()
    refinement = value["manifest"]["refinements"]["config"]
    refinement["properties"] = {"note": {"type": "string", "maxLength": 64}}
    validator = Draft202012Validator(input_schema())
    assert validator.is_valid(value)
    assert parse(value).as_dict() == value
    refinement["properties"]["note"]["qualified"] = True
    assert not validator.is_valid(value)


def test_uninterpreted_evidence_claims_remain_inert_metadata():
    value = candidate_payload()
    evidence = {"verified": True, "authority": "untrusted uploaded claim"}
    entry = next(e for e in value["documents"] if e["document_kind"] == "provenance")
    entry["content"] = evidence
    raw = canonical_json(evidence)
    ref = {"document_kind": "provenance", "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}
    value["manifest"]["source"]["provenance_ref"] = ref
    value["service_descriptor"]["evidence"]["provenance_ref"] = ref
    assert parse(refresh(value)).as_dict() == value
