"""Independent vectors for the pure provider prepare/cancel protocol."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from base64 import urlsafe_b64encode
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.deployment.provider_source_contracts import validate_provider_source_bundle
from app.domain.refs import canonical_json
from app.extensions.candidate_contracts import (
    CandidateBundle,
    CandidateError,
    metadata_ref,
    parse_bundle,
)
from app.operations.setup import OriginProfile
from app.tests.extension_candidate_fixture import candidate_payload
from app.tests.provider_source_fixture import case
from app.tests.test_provider_lineage import lineage_mapping, shipped_schema_bytes

ROOT = Path(__file__).resolve().parents[2]
REQUEST_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
COMMAND_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ACTOR_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
VAULT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
CREATED_MS = 1_700_000_000_000
NONCE = bytes(range(32))


def _b32(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _ref(kind: str, raw: bytes) -> dict:
    return {"document_kind": kind, "sha256": _hash(raw), "size_bytes": len(raw)}


def _provider_candidate(slot: dict) -> tuple[CandidateBundle, dict]:
    payload = candidate_payload()
    lineage = lineage_mapping()
    documents = {
        entry["document_kind"]: entry["content"] for entry in payload["documents"]
    }
    documents["provenance"] = lineage
    refs = {
        kind: _ref(
            kind, value.encode() if type(value) is str else canonical_json(value)
        )
        for kind, value in documents.items()
    }
    descriptor = payload["service_descriptor"]
    descriptor.update(
        extension_id="synthetic-provider",
        extension_version="1.0.0",
        port_contract_version="provider-port-v1",
        index=deepcopy(lineage["index"]),
        platforms=[
            deepcopy(item["measured_platform_entry"]) for item in lineage["platforms"]
        ],
        service_identity=slot["service_identity"],
        uid=slot["uid"],
        gid=slot["gid"],
        command={
            "protocol_id": slot["protocol_id"],
            "argv": [
                "/opt/deeptwin-extension/bin/worker",
                "--instance-id",
                slot["service_identity"].split("-")[1],
                "--slot-number",
                str(slot["slot_number"]),
            ],
        },
        broker_endpoint={
            "channel_id": slot["channel_id"],
            "requester_service": "control",
            "responder_service": slot["service_identity"],
            "protocol_id": slot["protocol_id"],
            "requester_uid": 20102,
            "requester_gid": 20102,
            "pair_gid": slot["pair_gid"],
            "socket_mount_id": slot["socket_mount"]["mount_id"],
            "socket_name": slot["socket_name"],
        },
        socket_mounts=[deepcopy(slot["socket_mount"])],
        named_volume_mounts=[],
        network_policy_ref=refs["network_declaration"],
        resource_profile_ref=refs["resource_declaration"],
        isolation_profile_ref=refs["isolation_declaration"],
        secret_needs=[],
        evidence={
            "sbom_ref": refs["sbom"],
            "provenance_ref": refs["provenance"],
            "license_ref": refs["license"],
        },
    )
    manifest = payload["manifest"]
    manifest.update(
        extension_id="synthetic-provider",
        extension_version="1.0.0",
        extension_kind="provider",
        port_contract_version="provider-port-v1",
        artifact={
            "artifact_form": "oci_extension_service",
            "service_descriptor_ref": metadata_ref(
                "service_descriptor", canonical_json(descriptor)
            ),
        },
        source={
            "kind": "third_party",
            "locator": "https://example.test/synthetic-provider",
            "provenance_ref": refs["provenance"],
        },
        license={"expression": "Synthetic", "text_ref": refs["license"]},
        requirements={
            "network_policy_ref": refs["network_declaration"],
            "resource_profile_ref": refs["resource_declaration"],
            "isolation_profile_ref": refs["isolation_declaration"],
            "secret_needs": [],
            "grant_ids": [],
            "filesystem_needs": ["owned_scratch"],
        },
    )
    payload["manifest"] = manifest
    payload["service_descriptor"] = descriptor
    payload["documents"] = [
        {"document_kind": kind, "content": value}
        for kind, value in sorted(documents.items())
    ]
    return parse_bundle(payload), lineage


def _head_digest(entry: dict) -> str:
    preimage = {
        "namespace": "deployment-prepare-storage-v3",
        "table": "installation_heads",
        "row": {
            "extension_id": entry["extension_id"],
            "request_id": entry["request_ref"]["id"],
            "revision": entry["head_revision"],
            "installation_anchor_digest": entry["installation_ref"]["sha256"],
        },
    }
    return _hash(canonical_json(preimage))


def _inventory(bundle, profile, *, entries=()) -> bytes:
    geometry = json.loads(bundle[9][1])
    value = {
        "schema_version": "deployment-provider-preserved-inventory-v1",
        "vault_id": VAULT_ID,
        "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest,
        "topology_id": geometry["topology_id"],
        "topology_sha256": _hash(bundle[2][1]),
        "at_event_sequence": 17,
        "installations": list(entries),
    }
    return canonical_json(value)


def _actor() -> dict:
    return {"kind": "actor", "id": ACTOR_ID, "version": 1, "sha256": "9" * 64}


def _inventory_entry(source_files, number: int, extension_id: str) -> dict:
    slot = json.loads(source_files[9][1])["slots"][number - 1]
    entry = {
        "installation_ref": {
            "kind": "extension_installation",
            "id": f"{number:08d}-1000-4000-8000-{number:012d}",
            "version": 1,
            "sha256": f"{number:064x}",
        },
        "extension_id": extension_id,
        "request_ref": {
            "kind": "deployment_request",
            "id": f"{number:08d}-2000-4000-8000-{number:012d}",
            "version": 1,
            "sha256": f"{number + 2:064x}",
        },
        "head_revision": 1,
        "head_digest": "",
        "slot_id": number,
        "service_identity": slot["service_identity"],
        "accepted_event_id": f"{number:08d}-3000-4000-8000-{number:012d}",
        "staged_event_id": f"{number:08d}-4000-4000-8000-{number:012d}",
    }
    entry["head_digest"] = _head_digest(entry)
    return entry


def _inputs(
    *,
    capacity=1,
    platform="linux/amd64",
    portable=False,
    slot_number=1,
    identity="1" * 32,
):
    _, source_files, _ = case(
        capacity=capacity, platform=platform, portable=portable, identity=identity
    )
    geometry = json.loads(source_files[9][1])
    profile = OriginProfile.from_dict(geometry["origin_profile"])
    candidate, lineage = _provider_candidate(geometry["slots"][slot_number - 1])
    return {
        "candidate_bundle": candidate,
        "source_bundle_files": source_files,
        "provider_schema_bytes": shipped_schema_bytes(),
        "inventory_bytes": _inventory(source_files, profile),
        "slot_number": slot_number,
        "profile": profile,
        "request_id": REQUEST_ID,
        "nonce": NONCE,
        "actor_ref": _actor(),
        "created_ms": CREATED_MS,
        "ttl_seconds": 3600,
    }, lineage


def _contracts():
    return importlib.import_module("app.deployment.provider_prepare_contracts")


def _expected_effect(inputs: dict, lineage: dict) -> dict:
    source = inputs["source_bundle_files"]
    descriptor = inputs["candidate_bundle"].descriptor.as_dict()
    platform = json.loads(source[9][1])["platform"]
    selected = next(
        item["measured_platform_entry"]
        for item in lineage["platforms"]
        if item["measured_platform_entry"]["platform"] == platform
    )
    return {
        "schema_id": "deeptwin.extension-stage-request.v2",
        "extension_id": "synthetic-provider",
        "manifest_digest": inputs["candidate_bundle"].manifest.digest,
        "service_descriptor_digest": inputs["candidate_bundle"].descriptor.digest,
        "selected_platform_entry": {
            "platform": platform,
            "index_digest": "sha256:" + "f" * 64,
            "manifest_digest": selected["manifest"]["digest"],
            "config_digest": selected["config"]["digest"],
            "ordered_layer_digests": [layer["digest"] for layer in selected["layers"]],
        },
        "new_service_effect": {
            "service_identity": descriptor["service_identity"],
            "socket_mounts": descriptor["socket_mounts"],
            "named_volume_mounts": [],
            "network_policy_ref": descriptor["network_policy_ref"],
            "resource_profile_ref": descriptor["resource_profile_ref"],
        },
        "expected_installation_head": {"state": "absent"},
        "expected_next_installation_revision": 1,
        "stage_profile": "claude-text-transform-v1",
        "source_context": {
            "context_id": json.loads(source[16][1])["context_id"],
            "epoch": 1,
            "sha256": _hash(source[16][1]),
            "size_bytes": len(source[16][1]),
        },
        "geometry": {"sha256": _hash(source[9][1]), "size_bytes": len(source[9][1])},
        "preserved_inventory": json.loads(inputs["inventory_bytes"]),
        "preserved_inventory_sha256": _hash(inputs["inventory_bytes"]),
    }


def test_upstream_fixture_is_valid_before_new_constructor_red():
    inputs, _ = _inputs(
        capacity=16, platform="linux/arm64", portable=True, slot_number=16
    )
    validate_provider_source_bundle(inputs["source_bundle_files"])
    reparsed = parse_bundle(json.loads(inputs["candidate_bundle"].content_bytes))
    assert reparsed.content_bytes == inputs["candidate_bundle"].content_bytes
    assert (
        json.loads(inputs["source_bundle_files"][9][1])["slots"][15]["slot_number"]
        == 16
    )


@pytest.mark.parametrize("capacity,slot_number", [(1, 1), (16, 16)])
@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
@pytest.mark.parametrize("portable", [False, True])
def test_request_constructor_covers_modes_platforms_capacities_and_literal_effect(
    capacity, slot_number, platform, portable
):
    inputs, lineage = _inputs(
        capacity=capacity, platform=platform, portable=portable, slot_number=slot_number
    )
    module = _contracts()
    raw = module.make_provider_request(**inputs)
    value = module.parse_provider_request(raw, profile=inputs["profile"])
    assert value["schema"] == "deployment-request-v2"
    assert value["domain"] == "deeptwin-deployment-request-v2"
    assert value["preconditions"] == {}
    assert value["effect_payload"] == _expected_effect(inputs, lineage)
    unsigned = {key: item for key, item in value.items() if key != "request_digest"}
    assert value["request_digest"] == _b32(
        hashlib.sha256(canonical_json(unsigned)).digest()
    )
    assert raw == canonical_json(value)
    assert (
        module.validate_provider_request_sources(
            raw,
            candidate_bundle=inputs["candidate_bundle"],
            source_bundle_files=inputs["source_bundle_files"],
            provider_schema_bytes=inputs["provider_schema_bytes"],
            inventory_bytes=inputs["inventory_bytes"],
            profile=inputs["profile"],
        )
        is None
    )


def test_inputs_inventory_cancellation_and_v1_v2_separation():
    module = _contracts()
    inputs, _ = _inputs()
    prepare = {
        "command_id": COMMAND_ID,
        "kind": "extension_stage",
        "candidate_id": REQUEST_ID,
        "slot_id": 1,
        "expires_in_seconds": 3600,
        "source_context_sha256": _hash(inputs["source_bundle_files"][16][1]),
    }
    assert module.parse_provider_prepare(prepare) == prepare
    cancel = {
        "command_id": COMMAND_ID,
        "request_digest": _b32(NONCE),
        "expected_revision": 1,
    }
    assert module.parse_provider_cancel(REQUEST_ID, cancel) == {
        **cancel,
        "request_id": REQUEST_ID,
    }
    assert (
        module.parse_provider_inventory(inputs["inventory_bytes"])["installations"]
        == []
    )
    raw = module.make_provider_request(**inputs)
    marker = module.make_provider_cancellation(
        raw, profile=inputs["profile"], cancelled_ms=CREATED_MS + 1
    )
    cancelled = module.parse_provider_cancellation(marker, profile=inputs["profile"])
    request = module.parse_provider_request(raw, profile=inputs["profile"])
    assert cancelled["request_digest"] == request["request_digest"]
    assert cancelled["source_context_sha256"] == _hash(
        inputs["source_bundle_files"][16][1]
    )
    from app.deployment.prepare_contracts import parse_request

    with pytest.raises(module.DeploymentPrepareError):
        parse_request(raw, profile=inputs["profile"])
    legacy = canonical_json(
        {
            **request,
            "schema": "deployment-request-v1",
            "domain": "deeptwin-deployment-request-v1",
        }
    )
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_provider_request(legacy, profile=inputs["profile"])


def test_inventory_pins_literal_head_digest_and_rejects_duplicates_and_selected_extension():
    module = _contracts()
    inputs, _ = _inputs(capacity=16, slot_number=16)
    geometry = json.loads(inputs["source_bundle_files"][9][1])
    entry = {
        "installation_ref": {
            "kind": "extension_installation",
            "id": "10000000-0000-4000-8000-000000000001",
            "version": 1,
            "sha256": "1" * 64,
        },
        "extension_id": "other-provider",
        "request_ref": {
            "kind": "deployment_request",
            "id": "20000000-0000-4000-8000-000000000002",
            "version": 1,
            "sha256": "2" * 64,
        },
        "head_revision": 1,
        "head_digest": "",
        "slot_id": 1,
        "service_identity": geometry["slots"][0]["service_identity"],
        "accepted_event_id": "30000000-0000-4000-8000-000000000003",
        "staged_event_id": "40000000-0000-4000-8000-000000000004",
    }
    entry["head_digest"] = _head_digest(entry)
    assert (
        entry["head_digest"]
        == "684d472f7e24e114d1ef2546379ae2c3eaaee72ac96bf49d4705cbd0d4b456e4"
    )
    inputs["inventory_bytes"] = _inventory(
        inputs["source_bundle_files"], inputs["profile"], entries=(entry,)
    )
    raw = module.make_provider_request(**inputs)
    assert module.parse_provider_request(raw, profile=inputs["profile"])[
        "effect_payload"
    ]["preserved_inventory"]["installations"] == [entry]
    changed = json.loads(inputs["inventory_bytes"])
    changed["installations"][0]["head_digest"] = "0" * 64
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_provider_inventory(canonical_json(changed))
    changed = json.loads(inputs["inventory_bytes"])
    changed["installations"][0]["extension_id"] = "synthetic-provider"
    changed["installations"][0]["head_digest"] = _head_digest(
        changed["installations"][0]
    )
    inputs["inventory_bytes"] = canonical_json(changed)
    with pytest.raises(module.DeploymentPrepareError):
        module.make_provider_request(**inputs)


def test_pure_constructor_and_reconstruction_accept_two_preserved_installations():
    module = _contracts()
    inputs, _ = _inputs(capacity=16, slot_number=16)
    entries = (
        _inventory_entry(inputs["source_bundle_files"], 1, "other-a"),
        _inventory_entry(inputs["source_bundle_files"], 2, "other-b"),
    )
    inputs["inventory_bytes"] = _inventory(
        inputs["source_bundle_files"], inputs["profile"], entries=entries
    )
    assert (
        len(module.parse_provider_inventory(inputs["inventory_bytes"])["installations"])
        == 2
    )
    raw = module.make_provider_request(**inputs)
    assert (
        module.validate_provider_request_sources(
            raw,
            candidate_bundle=inputs["candidate_bundle"],
            source_bundle_files=inputs["source_bundle_files"],
            provider_schema_bytes=inputs["provider_schema_bytes"],
            inventory_bytes=inputs["inventory_bytes"],
            profile=inputs["profile"],
        )
        is None
    )


@pytest.mark.parametrize(
    "mutation",
    ["extension", "installation", "request", "slot", "accepted_event", "cross_event"],
)
def test_inventory_duplicate_classes_are_rejected_independently(mutation):
    module = _contracts()
    inputs, _ = _inputs(capacity=16, slot_number=16)
    first = _inventory_entry(inputs["source_bundle_files"], 1, "other-a")
    second = _inventory_entry(inputs["source_bundle_files"], 2, "other-b")
    if mutation == "extension":
        second["extension_id"] = first["extension_id"]
    elif mutation == "installation":
        second["installation_ref"]["id"] = first["installation_ref"]["id"]
    elif mutation == "request":
        second["request_ref"]["id"] = first["request_ref"]["id"]
    elif mutation == "slot":
        second["slot_id"] = first["slot_id"]
    elif mutation == "accepted_event":
        second["accepted_event_id"] = first["accepted_event_id"]
    else:
        second["staged_event_id"] = first["accepted_event_id"]
    second["head_digest"] = _head_digest(second)
    raw = _inventory(
        inputs["source_bundle_files"], inputs["profile"], entries=(first, second)
    )
    with pytest.raises(module.DeploymentPrepareError) as caught:
        module.parse_provider_inventory(raw)
    assert caught.value.code == "invalid_input"


def test_inventory_unsorted_selected_slot_and_bad_vault_fail_intended_boundaries():
    module = _contracts()
    inputs, _ = _inputs(capacity=16, slot_number=16)
    first = _inventory_entry(inputs["source_bundle_files"], 1, "other-a")
    second = _inventory_entry(inputs["source_bundle_files"], 2, "other-b")
    unsorted = _inventory(
        inputs["source_bundle_files"], inputs["profile"], entries=(second, first)
    )
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_provider_inventory(unsorted)
    selected = _inventory_entry(inputs["source_bundle_files"], 16, "other-z")
    selected_inventory = _inventory(
        inputs["source_bundle_files"], inputs["profile"], entries=(selected,)
    )
    assert module.parse_provider_inventory(selected_inventory)["installations"] == [
        selected
    ]
    inputs["inventory_bytes"] = selected_inventory
    with pytest.raises(module.DeploymentPrepareError):
        module.make_provider_request(**inputs)
    vault_entry = _inventory_entry(inputs["source_bundle_files"], 1, "other-vault")
    valid_vault_inventory = _inventory(
        inputs["source_bundle_files"], inputs["profile"], entries=(vault_entry,)
    )
    assert module.parse_provider_inventory(valid_vault_inventory)["installations"] == [
        vault_entry
    ]
    malformed = json.loads(valid_vault_inventory)
    malformed["vault_id"] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(module.DeploymentPrepareError) as bad_vault:
        module.parse_provider_inventory(canonical_json(malformed))
    assert bad_vault.value.code == "invalid_input"


@pytest.mark.parametrize(
    "mutation",
    ["network", "isolation", "resource", "uid", "broker", "mount", "argv", "schema"],
)
def test_candidate_schema_or_provider_join_mismatches_fail_at_request_boundary(
    mutation,
):
    module = _contracts()
    inputs, _ = _inputs()
    payload = json.loads(inputs["candidate_bundle"].content_bytes)
    if mutation == "network":
        next(
            x
            for x in payload["documents"]
            if x["document_kind"] == "network_declaration"
        )["content"]["network_mode"] = "bridge"
    elif mutation == "isolation":
        next(
            x
            for x in payload["documents"]
            if x["document_kind"] == "isolation_declaration"
        )["content"]["privileged"] = True
    elif mutation == "resource":
        next(
            x
            for x in payload["documents"]
            if x["document_kind"] == "resource_declaration"
        )["content"]["memory_bytes"] = 4_294_967_296
    elif mutation == "uid":
        payload["service_descriptor"]["uid"] += 1
    elif mutation == "broker":
        payload["service_descriptor"]["broker_endpoint"]["channel_id"] = "wrong"
    elif mutation == "mount":
        payload["service_descriptor"]["socket_mounts"][0]["volume_name"] = "wrong"
    elif mutation == "argv":
        payload["service_descriptor"]["command"]["argv"][-1] = "2"
    else:
        schemas = list(inputs["provider_schema_bytes"])
        schemas[0] += b" "
        inputs["provider_schema_bytes"] = tuple(schemas)
        with pytest.raises(module.DeploymentPrepareError):
            module.make_provider_request(**inputs)
        return
    # Refresh ordinary candidate refs. Network/isolation remain rejected by the accepted
    # candidate schema; the other mutations produce a valid candidate and reach later joins.
    docs = payload["documents"]
    refs = {
        item["document_kind"]: _ref(
            item["document_kind"],
            item["content"].encode()
            if type(item["content"]) is str
            else canonical_json(item["content"]),
        )
        for item in docs
    }
    descriptor = payload["service_descriptor"]
    for field, kind in (
        ("network_policy_ref", "network_declaration"),
        ("resource_profile_ref", "resource_declaration"),
        ("isolation_profile_ref", "isolation_declaration"),
    ):
        descriptor[field] = refs[kind]
        payload["manifest"]["requirements"][field] = refs[kind]
    payload["manifest"]["artifact"]["service_descriptor_ref"] = metadata_ref(
        "service_descriptor", canonical_json(descriptor)
    )
    if mutation in {"network", "isolation"}:
        with pytest.raises(CandidateError):
            parse_bundle(payload)
        inputs["candidate_bundle"] = CandidateBundle(
            canonical_json(payload),
            inputs["candidate_bundle"].manifest,
            inputs["candidate_bundle"].descriptor,
            inputs["candidate_bundle"].documents,
        )
    else:
        inputs["candidate_bundle"] = parse_bundle(payload)
    with pytest.raises(
        module.DeploymentPrepareError, match=r"^Invalid deployment request\.$"
    ):
        module.make_provider_request(**inputs)


@pytest.mark.parametrize(
    "bad",
    [b"{}", b'{"schema":"x","schema":"x"}', b'{"x":1.0}', b"\xff", b"[]", b"null"],
)
def test_raw_parsers_reject_malformed_duplicate_noncanonical_and_hollow_values(bad):
    module = _contracts()
    inputs, _ = _inputs()
    for parser, kwargs in (
        (module.parse_provider_inventory, {}),
        (module.parse_provider_request, {"profile": inputs["profile"]}),
        (module.parse_provider_cancellation, {"profile": inputs["profile"]}),
    ):
        with pytest.raises(module.DeploymentPrepareError) as caught:
            parser(bad, **kwargs)
        assert caught.value.code == "invalid_input"


@pytest.mark.parametrize(
    "parser,cap",
    [
        ("parse_provider_inventory", 16384),
        ("parse_provider_request", 65536),
        ("parse_provider_cancellation", 8192),
    ],
)
def test_raw_parser_caps_keep_in_budget_malformed_distinct_from_too_large(parser, cap):
    module = _contracts()
    inputs, _ = _inputs()
    kwargs = (
        {} if parser == "parse_provider_inventory" else {"profile": inputs["profile"]}
    )
    with pytest.raises(module.DeploymentPrepareError) as in_budget:
        getattr(module, parser)(b" " * cap, **kwargs)
    assert in_budget.value.code == "invalid_input"
    with pytest.raises(module.DeploymentPrepareError) as oversized:
        getattr(module, parser)(b" " * (cap + 1), **kwargs)
    assert oversized.value.code == "too_large"


def test_command_and_candidate_caps_classify_oversize_before_narrow_validation():
    module = _contracts()
    inputs, _ = _inputs()
    malformed = {
        "command_id": "x" * 4080,
        "kind": "extension_stage",
        "candidate_id": REQUEST_ID,
        "slot_id": 1,
        "expires_in_seconds": 60,
        "source_context_sha256": "1" * 64,
    }
    with pytest.raises(module.DeploymentPrepareError) as oversized_command:
        module.parse_provider_prepare(malformed)
    assert oversized_command.value.code == "too_large"

    def hollow_candidate(raw):
        return CandidateBundle(
            raw,
            inputs["candidate_bundle"].manifest,
            inputs["candidate_bundle"].descriptor,
            inputs["candidate_bundle"].documents,
        )

    inputs["candidate_bundle"] = hollow_candidate(b" " * 1_048_576)
    with pytest.raises(module.DeploymentPrepareError) as in_budget:
        module.make_provider_request(**inputs)
    assert in_budget.value.code == "invalid_input"
    inputs["candidate_bundle"] = hollow_candidate(b" " * 1_048_577)
    with pytest.raises(module.DeploymentPrepareError) as oversized_candidate:
        module.make_provider_request(**inputs)
    assert oversized_candidate.value.code == "too_large"
    inputs, _ = _inputs()
    source_files = list(inputs["source_bundle_files"])
    source_files[0] = (source_files[0][0], b" " * 4097)
    inputs["source_bundle_files"] = tuple(source_files)
    with pytest.raises(module.DeploymentPrepareError) as oversized_source:
        module.make_provider_request(**inputs)
    assert oversized_source.value.code == "too_large"


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("unknown", 1),
        ("preconditions", {"state": "absent"}),
        ("request_id", "00000000-0000-0000-0000-000000000000"),
        ("request_nonce", "A" * 42 + "B"),
        ("created_at", "2023-11-14T22:13:20.000+00:00"),
    ],
)
def test_otherwise_valid_rehashed_request_rejects_exact_field_violation(
    field, replacement
):
    module = _contracts()
    inputs, _ = _inputs()
    value = json.loads(module.make_provider_request(**inputs))
    value[field] = replacement
    unsigned = {name: item for name, item in value.items() if name != "request_digest"}
    value["request_digest"] = _b32(hashlib.sha256(canonical_json(unsigned)).digest())
    with pytest.raises(module.DeploymentPrepareError) as caught:
        module.parse_provider_request(canonical_json(value), profile=inputs["profile"])
    assert caught.value.code == "invalid_input"


def test_valid_request_rejects_noncanonical_wire_without_conflating_size():
    module = _contracts()
    inputs, _ = _inputs()
    raw = module.make_provider_request(**inputs)
    with pytest.raises(module.DeploymentPrepareError) as caught:
        module.parse_provider_request(raw + b"\n", profile=inputs["profile"])
    assert caught.value.code == "invalid_input"


def test_hollow_exact_inputs_normalize_and_control_exceptions_propagate(monkeypatch):
    module = _contracts()
    inputs, _ = _inputs()
    hollow_bundle = object.__new__(CandidateBundle)
    inputs["candidate_bundle"] = hollow_bundle
    with pytest.raises(module.DeploymentPrepareError) as bundle_error:
        module.make_provider_request(**inputs)
    assert bundle_error.value.code == "invalid_input"
    inputs, _ = _inputs()
    hollow_profile = object.__new__(OriginProfile)
    inputs["profile"] = hollow_profile
    with pytest.raises(module.DeploymentPrepareError) as profile_error:
        module.make_provider_request(**inputs)
    assert profile_error.value.code == "invalid_input"
    inputs, _ = _inputs()
    for exception in (KeyboardInterrupt, SystemExit):
        monkeypatch.setattr(
            module,
            "validate_provider_source_bundle",
            lambda *_args, _exception=exception, **_kwargs: (_ for _ in ()).throw(
                _exception()
            ),
        )
        with pytest.raises(exception):
            module.make_provider_request(**inputs)


def test_bounds_bool_as_integer_cancellation_boundaries_and_frozen_cache_substitution():
    module = _contracts()
    inputs, _ = _inputs()
    bad_prepare = {
        "command_id": COMMAND_ID,
        "kind": "extension_stage",
        "candidate_id": REQUEST_ID,
        "slot_id": True,
        "expires_in_seconds": 3600,
        "source_context_sha256": _hash(inputs["source_bundle_files"][16][1]),
    }
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_provider_prepare(bad_prepare)
    with pytest.raises(module.DeploymentPrepareError) as too_large:
        module.parse_provider_inventory(b"{" + b" " * 16384 + b"}")
    assert too_large.value.code == "too_large"
    raw = module.make_provider_request(**inputs)
    with pytest.raises(module.DeploymentPrepareError):
        module.make_provider_cancellation(
            raw, profile=inputs["profile"], cancelled_ms=CREATED_MS - 1
        )
    with pytest.raises(module.DeploymentPrepareError):
        module.make_provider_cancellation(
            raw, profile=inputs["profile"], cancelled_ms=CREATED_MS + 3_600_000
        )
    fake = CandidateBundle(
        inputs["candidate_bundle"].content_bytes,
        parse_bundle(candidate_payload()).manifest,
        parse_bundle(candidate_payload()).descriptor,
        (),
    )
    inputs["candidate_bundle"] = fake
    assert module.make_provider_request(**inputs) == raw


def test_request_parser_rejects_rehashed_envelope_with_wrong_embedded_inventory_digest():
    module = _contracts()
    inputs, _ = _inputs()
    value = json.loads(module.make_provider_request(**inputs))
    value["effect_payload"]["preserved_inventory_sha256"] = "0" * 64
    unsigned = {key: item for key, item in value.items() if key != "request_digest"}
    value["request_digest"] = _b32(hashlib.sha256(canonical_json(unsigned)).digest())
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_provider_request(canonical_json(value), profile=inputs["profile"])


def test_request_digest_sensitivity_and_exact_external_source_reconstruction():
    module = _contracts()
    inputs, _ = _inputs(capacity=16, slot_number=16)
    baseline = module.make_provider_request(**inputs)
    digests = set()
    for field, replacement in (
        ("nonce", bytes(reversed(NONCE))),
        ("created_ms", CREATED_MS + 1),
        ("actor_ref", {**_actor(), "sha256": "8" * 64}),
    ):
        changed = {**inputs, field: replacement}
        digests.add(
            module.parse_provider_request(
                module.make_provider_request(**changed), profile=inputs["profile"]
            )["request_digest"]
        )
    assert len(digests) == 3
    inventory = json.loads(inputs["inventory_bytes"])
    inventory["at_event_sequence"] += 1
    with pytest.raises(module.DeploymentPrepareError):
        module.validate_provider_request_sources(
            baseline,
            candidate_bundle=inputs["candidate_bundle"],
            source_bundle_files=inputs["source_bundle_files"],
            provider_schema_bytes=inputs["provider_schema_bytes"],
            inventory_bytes=canonical_json(inventory),
            profile=inputs["profile"],
        )
    other, _ = _inputs(capacity=16, platform="linux/arm64", slot_number=16)
    with pytest.raises(module.DeploymentPrepareError):
        module.validate_provider_request_sources(
            baseline,
            candidate_bundle=inputs["candidate_bundle"],
            source_bundle_files=other["source_bundle_files"],
            provider_schema_bytes=inputs["provider_schema_bytes"],
            inventory_bytes=inputs["inventory_bytes"],
            profile=inputs["profile"],
        )


@pytest.mark.parametrize(
    "index,field",
    [
        (3, "exchange_id"),
        (5, "prepare_instance_sha256"),
        (5, "trust_set_sha256"),
        (7, "ingress_id"),
        (7, "prepare_recipe_digest"),
        (7, "prepare_instance_digest"),
        (7, "outgoing_exchange_digest"),
        (7, "receipt_recipe_digest"),
        (7, "receipt_instance_digest"),
        (7, "trust_set_digest"),
        (8, "exchange_id"),
        (8, "outgoing_exchange_digest"),
        (8, "receipt_recipe_digest"),
        (8, "receipt_instance_digest"),
        (8, "trust_set_digest"),
        (8, "receipt_ingress_digest"),
    ],
)
def test_request_boundary_normalizes_each_refreshed_deferred_source_edge_failure(
    index, field
):
    from app.tests.provider_source_fixture import refresh_outer

    module = _contracts()
    inputs, _ = _inputs()
    raw = module.make_provider_request(**inputs)
    changed = json.loads(inputs["source_bundle_files"][index][1])
    changed[field] = (
        "abababab-abab-4bab-8bab-abababababab" if field.endswith("_id") else "e" * 64
    )
    changed_source = refresh_outer(inputs["source_bundle_files"], index, changed)
    with pytest.raises(module.DeploymentPrepareError) as caught:
        module.validate_provider_request_sources(
            raw,
            candidate_bundle=inputs["candidate_bundle"],
            source_bundle_files=changed_source,
            provider_schema_bytes=inputs["provider_schema_bytes"],
            inventory_bytes=inputs["inventory_bytes"],
            profile=inputs["profile"],
        )
    assert caught.value.code == "invalid_input"


def test_request_boundary_rejects_independently_valid_different_profile_context():
    module = _contracts()
    inputs, _ = _inputs()
    raw = module.make_provider_request(**inputs)
    other, _ = _inputs(identity="2" * 32)
    validate_provider_source_bundle(other["source_bundle_files"])
    with pytest.raises(module.DeploymentPrepareError) as caught:
        module.validate_provider_request_sources(
            raw,
            candidate_bundle=other["candidate_bundle"],
            source_bundle_files=other["source_bundle_files"],
            provider_schema_bytes=other["provider_schema_bytes"],
            inventory_bytes=other["inventory_bytes"],
            profile=inputs["profile"],
        )
    assert caught.value.code == "invalid_input"


def test_request_boundary_rejects_refreshed_source_context_identity_mismatch():
    from app.tests.provider_source_fixture import refresh_outer

    module = _contracts()
    inputs, _ = _inputs()
    raw = module.make_provider_request(**inputs)
    context = json.loads(inputs["source_bundle_files"][16][1])
    context["context_id"] = "cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd"
    changed_source = refresh_outer(inputs["source_bundle_files"], 16, context)
    with pytest.raises(module.DeploymentPrepareError):
        module.validate_provider_request_sources(
            raw,
            candidate_bundle=inputs["candidate_bundle"],
            source_bundle_files=changed_source,
            provider_schema_bytes=inputs["provider_schema_bytes"],
            inventory_bytes=inputs["inventory_bytes"],
            profile=inputs["profile"],
        )


def test_source_validation_rejects_selected_extension_with_refreshed_hashes():
    module = _contracts()
    inputs, _ = _inputs(capacity=16, slot_number=16)
    entry = _inventory_entry(inputs["source_bundle_files"], 1, "other-a")
    inputs["inventory_bytes"] = _inventory(
        inputs["source_bundle_files"], inputs["profile"], entries=(entry,)
    )
    value = json.loads(module.make_provider_request(**inputs))
    entry["extension_id"] = "synthetic-provider"
    entry["head_digest"] = _head_digest(entry)
    conflicting_inventory = _inventory(
        inputs["source_bundle_files"], inputs["profile"], entries=(entry,)
    )
    value["effect_payload"]["preserved_inventory"] = json.loads(conflicting_inventory)
    value["effect_payload"]["preserved_inventory_sha256"] = _hash(conflicting_inventory)
    unsigned = {name: item for name, item in value.items() if name != "request_digest"}
    value["request_digest"] = _b32(hashlib.sha256(canonical_json(unsigned)).digest())
    raw = canonical_json(value)
    assert (
        module.parse_provider_request(raw, profile=inputs["profile"])["request_id"]
        == REQUEST_ID
    )
    with pytest.raises(module.DeploymentPrepareError):
        module.validate_provider_request_sources(
            raw,
            candidate_bundle=inputs["candidate_bundle"],
            source_bundle_files=inputs["source_bundle_files"],
            provider_schema_bytes=inputs["provider_schema_bytes"],
            inventory_bytes=conflicting_inventory,
            profile=inputs["profile"],
        )


def test_pure_calls_and_fresh_import_do_not_touch_effect_apis(monkeypatch):
    inputs, _ = _inputs()
    module = _contracts()
    blocked = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("effect API called")
    )
    for owner, name in (
        (os, "open"),
        (socket, "socket"),
        (sqlite3, "connect"),
        (time, "time"),
        (secrets, "token_bytes"),
    ):
        monkeypatch.setattr(owner, name, blocked)
    raw = module.make_provider_request(**inputs)
    assert (
        module.parse_provider_request(raw, profile=inputs["profile"])["request_id"]
        == REQUEST_ID
    )
    marker = module.make_provider_cancellation(
        raw, profile=inputs["profile"], cancelled_ms=CREATED_MS
    )
    assert (
        module.parse_provider_cancellation(marker, profile=inputs["profile"])[
            "lifecycle_revision"
        ]
        == 2
    )
    script = r"""import builtins, importlib, io, os, random, secrets, socket, sqlite3, sys, time, uuid
import jsonschema
import app.domain.refs, app.domain.wire
import app.extensions.candidate_contracts, app.extensions.provider_lineage
import app.deployment.prepare_contracts, app.deployment.provider_geometry
import app.deployment.provider_source_contracts
targets = {
    "app.deployment.provider_prepare_contracts",
    "app.deployment.provider_prepare_schema_exports",
}
assert targets.isdisjoint(sys.modules)
def blocked(*args, **kwargs): raise AssertionError("effect API called")
builtins.open = blocked
io.open = blocked
os.open = blocked
os.urandom = blocked
socket.socket = blocked
sqlite3.connect = blocked
time.time = blocked
time.monotonic = blocked
secrets.token_bytes = blocked
random.SystemRandom = blocked
uuid.uuid4 = blocked
before = set(sys.modules)
for target in sorted(targets): importlib.import_module(target)
loaded = set(sys.modules) - before
forbidden = [name for name in loaded if name.startswith(("app.runtime", "app.services", "app.api"))]
assert not forbidden, forbidden
print("imported")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "imported\n", "")


def test_anchor_exact_order_caps_vault_and_seven_schema_artifacts():
    module = _contracts()
    exports = importlib.import_module("app.deployment.provider_prepare_schema_exports")
    source_names = [name for name, _ in _inputs()[0]["source_bundle_files"]]
    blob = lambda size=1, vault=VAULT_ID, sha="1" * 64: {
        "vault_id": vault,
        "purpose": "operational",
        "sha256": sha,
        "size": size,
    }
    anchor = {
        "schema_version": "deployment-provider-request-anchor-v2",
        "request_id": REQUEST_ID,
        "request_blob_ref": blob(65536),
        "source_documents": [
            {"name": name, "blob_ref": blob(sha=_hash(name.encode()))}
            for name in source_names
        ],
        "preserved_inventory_blob_ref": blob(16384),
        "candidate_ref": {
            "kind": "extension_manifest",
            "id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            "version": 1,
            "sha256": "2" * 64,
        },
        "topology_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
        "topology_revision": 1,
        "slot_id": 1,
        "reservation_revision": 1,
        "prepare_command_id": COMMAND_ID,
    }
    from app.domain.store import _references

    entities, blobs = _references(anchor)
    assert len(entities) == 1
    assert len(blobs) == 20
    assert module.validate_provider_anchor_content(anchor) is None
    old_name = {**anchor, "source_document_blob_refs": anchor["source_documents"]}
    del old_name["source_documents"]
    with pytest.raises(module.DeploymentPrepareError):
        module.validate_provider_anchor_content(old_name)
    wrong = deepcopy(anchor)
    wrong["source_documents"] = list(reversed(wrong["source_documents"]))
    with pytest.raises(module.DeploymentPrepareError):
        module.validate_provider_anchor_content(wrong)
    wrong = deepcopy(anchor)
    wrong["source_documents"][0]["blob_ref"]["vault_id"] = (
        "11111111-1111-4111-8111-111111111111"
    )
    with pytest.raises(module.DeploymentPrepareError):
        module.validate_provider_anchor_content(wrong)
    wrong = deepcopy(anchor)
    wrong["source_documents"][0]["blob_ref"]["purpose"] = "retained"
    with pytest.raises(module.DeploymentPrepareError) as bad_purpose:
        module.validate_provider_anchor_content(wrong)
    assert bad_purpose.value.code == "invalid_input"
    wrong = deepcopy(anchor)
    wrong["source_documents"][0]["blob_ref"]["size"] = 4097
    with pytest.raises(module.DeploymentPrepareError) as oversized_blob:
        module.validate_provider_anchor_content(wrong)
    assert oversized_blob.value.code == "invalid_input"
    wrong = {**anchor, "padding": "x" * 9000}
    with pytest.raises(module.DeploymentPrepareError) as oversized_anchor:
        module.validate_provider_anchor_content(wrong)
    assert oversized_anchor.value.code == "too_large"
    schemas = exports.exported_schemas()
    assert tuple(schemas) == (
        "provider-preserved-inventory-v1.schema.json",
        "provider-stage-request-v2.schema.json",
        "provider-request-v2.schema.json",
        "provider-prepare-input-v1.schema.json",
        "provider-cancel-input-v1.schema.json",
        "provider-cancellation-v1.schema.json",
        "provider-request-anchor-v2.schema.json",
    )
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        expected = (
            json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        assert (ROOT / "schemas/v2/deployment" / name).read_bytes() == expected
        schema["properties"].clear()
    assert all(value["properties"] for value in exports.exported_schemas().values())
