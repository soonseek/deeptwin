import ast
import json
import re
import unicodedata
from base64 import urlsafe_b64decode
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import jsonschema
import pytest

from app.domain.refs import canonical_json
from app.operations import setup
from app.operations.setup import (
    CapabilityVerifier,
    OriginProfile,
    SetupContractError,
    build_bootstrap_configuration,
    derive_capability_verifier,
    parse_base64url_32,
    verify_bootstrap_capability,
)

ROOT = Path(__file__).resolve().parents[2]
VECTORS_PATH = ROOT / "schemas" / "v1" / "test-vectors" / "bootstrap-origin-profile-v1.json"
SCHEMA_PATH = ROOT / "schemas" / "v1" / "origin-profile.schema.json"
HELPER_PATH = ROOT / "deploy" / "bootstrap" / "index.html"


@pytest.fixture(scope="module")
def vectors():
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _without_digest(profile):
    return {key: value for key, value in profile.items() if key != "digest"}


def test_shared_capability_vectors_are_strict_and_constant_time_ready(vectors):
    assert vectors["schema_version"] == "bootstrap-origin-profile-v1"
    for item in vectors["capability_vectors"]:
        raw = item["raw_capability_b64u"]
        expected = item["verifier_b64u"]
        assert parse_base64url_32(raw) == bytes.fromhex(item["raw_capability_hex"])
        assert derive_capability_verifier(raw) == expected
        verifier = CapabilityVerifier(expected)
        assert verifier.matches(raw) is True
        assert verify_bootstrap_capability(raw, expected) is True

        changed = ("A" if raw[0] != "A" else "B") + raw[1:]
        assert verifier.matches(changed) is False
        assert verify_bootstrap_capability(changed, expected) is False

    for value in vectors["invalid_capability_b64u"]:
        with pytest.raises(SetupContractError):
            parse_base64url_32(value)
        with pytest.raises(SetupContractError):
            derive_capability_verifier(value)


def test_capability_match_uses_the_standard_constant_time_primitive(vectors, monkeypatch):
    calls = []

    def compare(left, right):
        calls.append((left, right))
        return left == right

    monkeypatch.setattr(setup.hmac, "compare_digest", compare)
    item = vectors["capability_vectors"][1]
    assert verify_bootstrap_capability(
        item["raw_capability_b64u"], item["verifier_b64u"],
    ) is True
    assert len(calls) == 1
    assert all(type(value) is bytes and len(value) == 32 for value in calls[0])


def test_shared_origin_vectors_match_adr008_canonical_bytes_and_schema(vectors):
    assert f"idna=={setup.idna.__version__}" == vectors["idna_profile"]["python_package"]
    assert setup.idna.idnadata.__version__ == vectors["idna_profile"]["unicode_version"]
    assert unicodedata.unidata_version == vectors["idna_profile"]["python_unicodedata_version"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for item in vectors["origin_profile_vectors"]:
        if item["constructor"] == "local":
            profile = OriginProfile.local(**item["input"])
        else:
            profile = OriginProfile.portable(**item["input"])
        expected = item["profile"]
        assert profile.as_dict() == expected
        assert profile.canonical_preimage().decode("utf-8") == item["canonical_preimage_utf8"]
        assert sha256(canonical_json(_without_digest(expected))).hexdigest() == expected["digest"]
        assert list(validator.iter_errors(expected)) == []
        assert OriginProfile.from_dict(expected) == profile


def test_helper_embeds_the_exact_pinned_python_idna_and_bidi_tables(vectors):
    source = HELPER_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"const PVALID_DELTA_B64U =\s*\[(.*?)\]\.join\(\"\"\);",
        source,
        re.DOTALL,
    )
    assert match is not None
    encoded = "".join(re.findall(r'\"([A-Za-z0-9_-]+)\"', match.group(1)))
    embedded = urlsafe_b64decode(encoded + "=")

    def leb128(value):
        encoded_value = bytearray()
        while True:
            byte = value & 127
            value >>= 7
            if value:
                byte |= 128
            encoded_value.append(byte)
            if not value:
                return encoded_value

    expected = bytearray()
    previous_end = 0
    ranges = setup.idna.idnadata.codepoint_classes["PVALID"]
    for packed in ranges:
        start, end = packed >> 32, packed & 0xFFFFFFFF
        expected.extend(leb128(start - previous_end))
        expected.extend(leb128(end - start))
        previous_end = end

    assert embedded == bytes(expected)
    assert len(ranges) == vectors["idna_profile"]["pvalid_range_count"]
    assert sha256(embedded).hexdigest() == vectors["idna_profile"]["pvalid_table_sha256"]

    bidi_match = re.search(
        r"const BIDI_DELTA_B64U =\s*\[(.*?)\]\.join\(\"\"\);",
        source,
        re.DOTALL,
    )
    assert bidi_match is not None
    bidi_encoded = "".join(re.findall(r'\"([A-Za-z0-9_-]+)\"', bidi_match.group(1)))
    embedded_bidi = urlsafe_b64decode(bidi_encoded + "=")
    classes = vectors["idna_profile"]["bidi_classes"]
    class_ids = {name: index for index, name in enumerate(classes)}

    bidi_ranges = []
    run_start = run_end = run_class = None
    for codepoint in range(0x110000):
        bidi_class = unicodedata.bidirectional(chr(codepoint))
        if bidi_class not in class_ids:
            if run_start is not None:
                bidi_ranges.append((run_start, run_end, run_class))
                run_start = run_end = run_class = None
            continue
        if run_start is None:
            run_start, run_end, run_class = codepoint, codepoint + 1, bidi_class
        elif codepoint == run_end and bidi_class == run_class:
            run_end += 1
        else:
            bidi_ranges.append((run_start, run_end, run_class))
            run_start, run_end, run_class = codepoint, codepoint + 1, bidi_class
    if run_start is not None:
        bidi_ranges.append((run_start, run_end, run_class))

    expected_bidi = bytearray()
    previous_end = 0
    for start, end, bidi_class in bidi_ranges:
        expected_bidi.extend(leb128(start - previous_end))
        expected_bidi.extend(leb128(end - start))
        expected_bidi.append(class_ids[bidi_class])
        previous_end = end
    assert embedded_bidi == bytes(expected_bidi)
    assert len(bidi_ranges) == vectors["idna_profile"]["bidi_range_count"]
    assert sha256(embedded_bidi).hexdigest() == vectors["idna_profile"]["bidi_table_sha256"]


def test_local_profile_rejects_noncanonical_ids_bool_and_ports(vectors):
    for item in vectors["invalid_local_inputs"]:
        with pytest.raises(SetupContractError):
            OriginProfile.local(**item["input"])


def test_portable_profile_rejects_ambiguous_urls_before_digest(vectors):
    for item in vectors["invalid_portable_urls"]:
        with pytest.raises(SetupContractError):
            OriginProfile.portable(instance_id=vectors["portable_instance_id"], url=item["url"])


def test_default_port_is_explicit_while_http_origin_and_origin_base_are_distinct(vectors):
    local = OriginProfile.from_dict(vectors["origin_profile_vectors"][1]["profile"])
    portable = OriginProfile.from_dict(vectors["origin_profile_vectors"][2]["profile"])
    assert (local.port, local.http_origin, local.origin_base) == (
        80,
        "http://0123456789abcdef0123456789abcdef.localhost",
        "http://0123456789abcdef0123456789abcdef.localhost/abcdef0123456789abcdef0123456789/",
    )
    assert (portable.port, portable.http_origin, portable.origin_base) == (
        443,
        "https://deeptwin.example.com",
        "https://deeptwin.example.com/",
    )


def test_cross_profile_and_changed_digest_mappings_fail_closed(vectors):
    local = dict(vectors["origin_profile_vectors"][0]["profile"])
    portable = dict(vectors["origin_profile_vectors"][2]["profile"])
    invalid = (
        {**local, "mode": "portable_https"},
        {**local, "scheme": "https"},
        {**local, "host": portable["host"]},
        {**portable, "base_path": local["base_path"]},
        {**portable, "deployment_profile_id": "local-no-terminal-v1"},
        {**portable, "origin_base": local["origin_base"]},
        {**portable, "digest": "0" * 64},
        {**portable, "raw_capability_b64u": "A" * 43},
    )
    for value in invalid:
        with pytest.raises(SetupContractError):
            OriginProfile.from_dict(value)
    for value in vectors["invalid_origin_profiles"]:
        with pytest.raises(SetupContractError):
            OriginProfile.from_dict(value)


def test_origin_profile_is_immutable_and_exactly_serializable(vectors):
    profile = OriginProfile.from_dict(vectors["origin_profile_vectors"][0]["profile"])
    with pytest.raises((FrozenInstanceError, AttributeError)):
        profile.port = 9999
    assert set(profile.as_dict()) == {
        "deployment_profile_id",
        "instance_id",
        "mode",
        "scheme",
        "host",
        "port",
        "base_path",
        "origin_base",
        "digest",
    }


def test_bootstrap_configuration_contains_only_nonsecret_delivery_fields(vectors):
    item = vectors["origin_profile_vectors"][0]
    capability = vectors["capability_vectors"][0]
    profile = OriginProfile.from_dict(item["profile"])
    configuration = build_bootstrap_configuration(
        profile=profile,
        verifier_b64u=capability["verifier_b64u"],
        recovery_epoch=1,
    )
    assert set(configuration) == {
        "origin_profile",
        "recovery_epoch",
        "verifier_b64u",
    }
    assert configuration["origin_profile"] == item["profile"]
    rendered = canonical_json(configuration).decode("utf-8")
    assert capability["raw_capability_b64u"] not in rendered
    assert "raw_capability" not in rendered
    with pytest.raises(SetupContractError):
        build_bootstrap_configuration(
            profile=profile,
            verifier_b64u=capability["verifier_b64u"],
            recovery_epoch=True,
        )
    with pytest.raises(SetupContractError):
        build_bootstrap_configuration(
            profile=profile,
            verifier_b64u=capability["verifier_b64u"],
            recovery_epoch=2,
        )


def test_setup_module_has_no_network_file_log_or_raw_capability_state():
    source_path = ROOT / "app" / "operations" / "setup.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    forbidden_imports = {
        "http",
        "logging",
        "os",
        "pathlib",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(
        name == forbidden or name.startswith(f"{forbidden}.")
        for name in imported
        for forbidden in forbidden_imports
    )
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert all("raw_capability" not in ast.unparse(node) for node in classes)
    assert HELPER_PATH.is_file()


def test_offline_helper_matches_the_frozen_release_checksum(vectors):
    assert sha256(HELPER_PATH.read_bytes()).hexdigest() == vectors["bootstrap_helper_sha256"]


def test_invalid_values_never_escape_through_contract_error_text(vectors):
    sentinel = "SECRET-SENTINEL"
    with pytest.raises(SetupContractError) as captured:
        derive_capability_verifier(sentinel)
    assert sentinel not in str(captured.value)
    assert sentinel not in repr(captured.value)


def test_exported_schema_is_structural_and_never_substitutes_for_authority_validation(vectors):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    local = vectors["origin_profile_vectors"][0]["profile"]
    portable = vectors["origin_profile_vectors"][2]["profile"]
    for invalid in (
        {**local, "mode": "portable_https"},
        {**local, "port": True},
        {**portable, "scheme": "http"},
        {**portable, "unknown": "field"},
    ):
        assert list(validator.iter_errors(invalid))

    semantic_forgery = {
        **local,
        "origin_base": "http://ffffffffffffffffffffffffffffffff.localhost/"
        "ffeeddccbbaa99887766554433221100/",
    }
    assert list(validator.iter_errors(semantic_forgery)) == []
    with pytest.raises(SetupContractError):
        OriginProfile.from_dict(semantic_forgery)
