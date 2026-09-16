"""Closed request bytes and real candidate-to-slot reconstruction."""

import importlib
from copy import deepcopy
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.domain.refs import canonical_json
from app.extensions.candidate_contracts import metadata_ref, parse_bundle
from app.tests.deployment_source_fixture import decoded_artifacts, profile
from app.tests.extension_candidate_fixture import candidate_payload


def implementation(name="prepare_contracts"):
    try:
        return importlib.import_module("app.deployment." + name)
    except ModuleNotFoundError:
        pytest.fail("Deployment prepare implementation is missing")


def matching_bundle():
    value = candidate_payload()
    topology = decoded_artifacts()[0]
    slot = topology["slots"][0]
    descriptor = value["service_descriptor"]
    descriptor.update(
        service_identity=slot["service_identity"],
        uid=slot["uid"],
        gid=slot["gid"],
        socket_mounts=[slot["socket_mount"]],
    )
    descriptor["broker_endpoint"] = {
        "channel_id": slot["channel_id"],
        "requester_service": "control",
        "responder_service": slot["service_identity"],
        "protocol_id": slot["protocol_id"],
        "requester_uid": 20102,
        "requester_gid": 20102,
        "pair_gid": slot["pair_gid"],
        "socket_mount_id": slot["socket_mount"]["mount_id"],
        "socket_name": "worker.sock",
    }
    for entry in descriptor["platforms"]:
        entry["layers"].append({**entry["layers"][0], "position": 2})
    value["manifest"]["artifact"]["service_descriptor_ref"] = metadata_ref(
        "service_descriptor", canonical_json(descriptor)
    )
    return parse_bundle(value), topology, slot


def prepare_input():
    return {
        "command_id": str(uuid4()),
        "kind": "extension_stage",
        "candidate_id": str(uuid4()),
        "slot_id": 1,
        "expires_in_seconds": 60,
    }


@pytest.mark.parametrize(
    "field,bad",
    [
        ("slot_id", True),
        ("slot_id", 0),
        ("slot_id", 17),
        ("expires_in_seconds", 59),
        ("expires_in_seconds", 86401),
        ("expires_in_seconds", 60.0),
        ("kind", "extension_update"),
        ("candidate_id", "00000000-0000-0000-0000-000000000000"),
        ("extra", "private-canary"),
    ],
)
def test_prepare_closed_input(field, bad):
    module = implementation()
    value = prepare_input()
    value[field] = bad
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.parse_prepare(value)
    assert error.value.code == "invalid_input"
    assert "private-canary" not in str(error.value)


def test_stage_preserves_actual_metadata_and_repeated_layer_order():
    module = implementation()
    bundle, topology, slot = matching_bundle()
    stage = module.stage_for_candidate(bundle, topology, slot)
    assert (
        stage["selected_platform_entry"]["ordered_layer_digests"]
        == ["sha256:" + "a" * 64] * 2
    )
    assert (
        stage["new_service_effect"]["network_policy_ref"]
        == bundle.descriptor.as_dict()["network_policy_ref"]
    )
    assert stage["expected_installation_head"] == {"state": "absent"}
    assert stage["expected_next_installation_revision"] == 1
    assert stage["extension_id"] == "synthetic-tool"


@pytest.mark.parametrize(
    "field",
    [
        "uid",
        "gid",
        "service_identity",
        "channel_id",
        "socket_name",
        "requester_uid",
        "requester_gid",
        "pair_gid",
        "platforms",
        "grant_ids",
        "filesystem_needs",
        "memory_bytes",
        "cpu_millicores",
        "pids_limit",
        "tmpfs_bytes",
    ],
)
def test_candidate_slot_mismatch_cannot_construct_stage(field):
    module = implementation()
    bundle, topology, slot = matching_bundle()
    value = bundle.as_dict()
    descriptor = value["service_descriptor"]
    if field in {"uid", "gid"}:
        descriptor[field] += 1
    elif field == "service_identity":
        descriptor[field] = descriptor["broker_endpoint"]["responder_service"] = (
            "another-worker"
        )
    elif field in {"channel_id", "socket_name"}:
        descriptor["broker_endpoint"][field] = "another"
    elif field in {"requester_uid", "requester_gid", "pair_gid"}:
        descriptor["broker_endpoint"][field] += 50
    elif field == "platforms":
        descriptor[field] = descriptor[field][:1]
    elif field in {"grant_ids", "filesystem_needs"}:
        value["manifest"]["requirements"][field] = (
            ["grant"] if field == "grant_ids" else []
        )
    else:
        doc = next(
            d
            for d in value["documents"]
            if d["document_kind"] == "resource_declaration"
        )
        doc["content"][field] = slot["resource_budget"][field] + 1
        ref = metadata_ref("resource_declaration", canonical_json(doc["content"]))
        descriptor["resource_profile_ref"] = value["manifest"]["requirements"][
            "resource_profile_ref"
        ] = ref
        if field == "tmpfs_bytes":
            doc["content"]["memory_bytes"] = 1073741824
            ref = metadata_ref("resource_declaration", canonical_json(doc["content"]))
            descriptor["resource_profile_ref"] = value["manifest"]["requirements"][
                "resource_profile_ref"
            ] = ref
    value["manifest"]["artifact"]["service_descriptor_ref"] = metadata_ref(
        "service_descriptor", canonical_json(descriptor)
    )
    with pytest.raises(module.DeploymentPrepareError):
        module.stage_for_candidate(parse_bundle(value), topology, slot)


def test_request_hashes_and_closed_stage_schema_parity():
    module = implementation()
    schemas = implementation("prepare_schema_exports")
    bundle, topology, slot = matching_bundle()
    request = module.make_request(
        bundle=bundle,
        topology=topology,
        slot=slot,
        profile=profile(),
        request_id=str(uuid4()),
        nonce=b"n" * 32,
        actor_ref={
            "kind": "actor",
            "id": str(uuid4()),
            "version": 1,
            "sha256": "b" * 64,
        },
        created_ms=1700000000000,
        ttl_seconds=60,
    )
    raw = canonical_json(request)
    assert module.parse_request(raw, profile=profile()) == request
    assert request["created_at"] == "2023-11-14T22:13:20.000Z"
    assert request["expires_at"] == "2023-11-14T22:14:20.000Z"
    validator = Draft202012Validator(
        schemas.request_schema(), format_checker=FormatChecker()
    )
    assert validator.is_valid(request)
    for bad in [
        dict(request, preconditions={"future": 1}),
        dict(request, created_at="2023-02-30T22:13:20.000Z"),
        dict(request, request_nonce="A" * 42 + "B"),
    ]:
        assert not validator.is_valid(bad)
        with pytest.raises(module.DeploymentPrepareError):
            module.parse_request(canonical_json(bad), profile=profile())
    bad = deepcopy(request)
    bad["effect_payload"]["expected_installation_head"] = {"state": "tombstone"}
    assert not validator.is_valid(bad)
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_request(canonical_json(bad), profile=profile())


def test_explicit_ttl_and_calendar_overflow_are_rejected():
    module = implementation()
    with pytest.raises(module.DeploymentPrepareError):
        module.interval(253402300799999, 60)
    with pytest.raises(module.DeploymentPrepareError):
        module.interval(1700000000000, True)


def anchor_content():
    vault = str(uuid4())
    blob = {"vault_id": vault, "purpose": "operational", "sha256": "a" * 64, "size": 10}
    return {
        "schema_version": "deployment-request-anchor-v1",
        "request_id": str(uuid4()),
        "request_blob_ref": blob,
        "topology_blob_ref": {**blob, "sha256": "b" * 64},
        "exchange_blob_ref": {**blob, "sha256": "c" * 64},
        "candidate_ref": {
            "kind": "extension_manifest",
            "id": str(uuid4()),
            "version": 1,
            "sha256": "d" * 64,
        },
        "topology_id": str(uuid4()),
        "topology_revision": 1,
        "slot_id": 1,
        "reservation_revision": 1,
        "prepare_command_id": str(uuid4()),
    }


def anchor_record(anchor=None, **changes):
    from app.domain.refs import EntityRef
    from app.domain.schemas import ImmutableRecord

    content = anchor_content() if anchor is None else anchor
    values = {
        "kind": "deployment_request",
        "id": content["request_id"],
        "version": 1,
        "created_at_utc": "2023-11-14T22:13:20.000000Z",
        "purpose": "operational",
        "actor_ref": EntityRef("actor", str(uuid4()), 1, "e" * 64),
        "parent_refs": (EntityRef.from_dict(content["candidate_ref"]),),
        "access_policy_ref": EntityRef("access_policy", str(uuid4()), 1, "f" * 64),
        "retention_policy_ref": EntityRef(
            "retention_policy", str(uuid4()), 1, "1" * 64
        ),
        "content": content,
    }
    return ImmutableRecord.create(**(values | changes))


def test_anchor_is_a_closed_version_one_operational_domain_kind():
    record = anchor_record()
    assert record.ref.kind == "deployment_request" and record.ref.version == 1
    assert record.body["parent_refs"] == [record.body["content"]["candidate_ref"]]


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "purpose",
        "id",
        "parents",
        "empty_content",
        "extra",
        "slot_bool",
        "future_candidate",
        "wrong_kind",
        "wrong_blob_purpose",
        "foreign_blob",
        "oversize_blob",
    ],
)
def test_anchor_refuses_incoherent_header_or_content(change):
    from app.domain.refs import DomainContractError

    # Require the positive implementation before asserting a malformed record rejects.
    anchor_record()
    content = anchor_content()
    headers = {}
    if change == "version":
        headers["version"] = 2
    elif change == "purpose":
        headers["purpose"] = "diagnosis"
    elif change == "id":
        headers["id"] = str(uuid4())
    elif change == "parents":
        headers["parent_refs"] = ()
    elif change == "empty_content":
        headers["content"] = {}
    elif change == "extra":
        content["future"] = 1
    elif change == "slot_bool":
        content["slot_id"] = True
    elif change == "future_candidate":
        content["candidate_ref"]["version"] = 2
    elif change == "wrong_kind":
        content["candidate_ref"]["kind"] = "actor"
    elif change == "wrong_blob_purpose":
        content["exchange_blob_ref"]["purpose"] = "diagnosis"
    elif change == "foreign_blob":
        content["exchange_blob_ref"]["vault_id"] = str(uuid4())
    else:
        content["exchange_blob_ref"]["size"] = 8193
    with pytest.raises(DomainContractError):
        anchor_record(content, **headers)


def test_all_four_structural_exports_validate_and_are_detached():
    schemas = implementation("prepare_schema_exports")
    values = schemas.exported_schemas()
    assert set(values) == {
        "request-stage-v1.schema.json",
        "request-anchor-v1.schema.json",
        "prepare-api-v1.schema.json",
        "cancellation-v1.schema.json",
    }
    for name, schema in values.items():
        Draft202012Validator.check_schema(schema)
        assert schema[
            "$id"
        ] == "urn:deeptwin:schemas:v1:deployment:" + name.removesuffix(".schema.json")
    assert Draft202012Validator(values["request-anchor-v1.schema.json"]).is_valid(
        anchor_content()
    )
    values["request-anchor-v1.schema.json"]["properties"].clear()
    assert schemas.exported_schemas()["request-anchor-v1.schema.json"]["properties"]


def test_domain_schema_and_event_exports_cover_request_and_expiry():
    from app.domain.schema_exports import domain_schema, events_schema

    assert Draft202012Validator(
        domain_schema(), format_checker=FormatChecker()
    ).is_valid(anchor_record().as_dict())
    bad = anchor_record().as_dict()
    bad["body"]["content"]["slot_id"] = True
    assert not Draft202012Validator(domain_schema()).is_valid(bad)
    expiry = events_schema()["$defs"]["deployment.request_expired"]
    assert Draft202012Validator(expiry).is_valid({"revision": 2})


def test_cancel_parser_retains_route_identity_and_closed_error_codes():
    module = implementation()
    request_id = str(uuid4())
    payload = {
        "command_id": str(uuid4()),
        "request_digest": "A" * 43,
        "expected_revision": 2,
    }
    assert module.parse_cancel(request_id, payload) == {
        **payload,
        "request_id": request_id,
    }
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.parse_cancel(request_id, {**payload, "command_id": "x" * 4097})
    assert error.value.code == "too_large"
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_cancel(request_id, {**payload, "request_id": str(uuid4())})


def test_stage_candidate_reconstruction_ignores_forged_cached_dataclass_members():
    from dataclasses import replace

    module = implementation()
    bundle, topology, slot = matching_bundle()
    forged = replace(bundle, descriptor=parse_bundle(candidate_payload()).descriptor)
    assert module.stage_for_candidate(
        forged, topology, slot
    ) == module.stage_for_candidate(bundle, topology, slot)


def test_cancellation_rejects_malformed_reconstructed_request_identity():
    module = implementation()
    request = {
        "request_id": "not-a-uuid",
        "request_digest": "A" * 43,
        "instance_id": profile().instance_id,
        "origin_profile_digest": module.b64(bytes.fromhex(profile().digest)),
    }
    with pytest.raises(module.DeploymentPrepareError):
        module.cancellation(request, 1700000000000, profile=profile())


def cancellation_request(origin_profile):
    from base64 import urlsafe_b64encode

    return {
        "request_id": "12345678-1234-4234-8234-123456789abc",
        "request_digest": "A" * 43,
        "instance_id": origin_profile.instance_id,
        "origin_profile_digest": urlsafe_b64encode(bytes.fromhex(origin_profile.digest))
        .rstrip(b"=")
        .decode(),
    }


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize(
    "instant,want",
    [
        (0, "1970-01-01T00:00:00.000Z"),
        (1700000000123, "2023-11-14T22:13:20.123Z"),
        (253402300799999, "9999-12-31T23:59:59.999Z"),
    ],
)
def test_cancellation_marker_has_exact_schema_and_shared_codec_parity(
    portable, instant, want
):
    from hashlib import sha256

    from app.deployment.publication import validate_projection
    from app.domain.refs import parse_canonical

    module = implementation()
    origin_profile = profile(portable)
    request = cancellation_request(origin_profile)
    before = deepcopy(request)
    raw = module.cancellation(request, instant, profile=origin_profile)
    expected = {
        "schema": "deployment-cancellation-v1",
        "domain": "deeptwin-deployment-cancellation-v1",
        "request_id": "12345678-1234-4234-8234-123456789abc",
        "request_digest": "A" * 43,
        "instance_id": origin_profile.instance_id,
        "origin_profile_digest": request["origin_profile_digest"],
        "lifecycle_revision": 2,
        "cancelled_at": want,
    }
    assert raw == canonical_json(expected)
    assert request == before
    schema = implementation("prepare_schema_exports").cancellation_schema()
    assert Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(
        parse_canonical(raw)
    )
    observation = validate_projection(
        role="cancel", request_digest="A" * 43, payload=raw, profile=origin_profile
    )
    assert observation.payload_sha256 == sha256(raw).hexdigest()
    assert observation.size_bytes == len(raw)


@pytest.mark.parametrize(
    "field,bad,schema_valid",
    [
        ("request_id", "not-a-uuid-private-canary", False),
        ("request_id", "00000000-0000-0000-0000-000000000000", False),
        ("request_id", "12345678-1234-4234-8234-123456789ABC", False),
        ("request_id", None, False),
        ("request_digest", "A" * 42, False),
        ("request_digest", "A" * 43 + "=", False),
        ("request_digest", "A" * 42 + "B", False),
        ("instance_id", "F" * 32, False),
        ("instance_id", "3" * 32, True),
        ("origin_profile_digest", "a" * 64, False),
        ("origin_profile_digest", "A" * 42 + "B", False),
        ("origin_profile_digest", "A" * 43, True),
    ],
)
def test_cancellation_rejects_identity_bytes_rejected_by_shared_codec(
    field, bad, schema_valid
):
    from app.deployment.contracts import DeploymentSourceError
    from app.deployment.publication import validate_projection

    module = implementation()
    origin_profile = profile()
    request = {**cancellation_request(origin_profile), field: bad}
    marker = {
        **request,
        "schema": "deployment-cancellation-v1",
        "domain": "deeptwin-deployment-cancellation-v1",
        "lifecycle_revision": 2,
        "cancelled_at": "2023-11-14T22:13:20.000Z",
    }
    schema = implementation("prepare_schema_exports").cancellation_schema()
    assert (
        Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(marker)
        is schema_valid
    )
    with pytest.raises(DeploymentSourceError):
        validate_projection(
            role="cancel",
            request_digest=request["request_digest"],
            payload=canonical_json(marker),
            profile=origin_profile,
        )
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.cancellation(request, 1700000000000, profile=origin_profile)
    assert error.value.code == "invalid_input"
    assert str(error.value) == "Invalid deployment request."


@pytest.mark.parametrize("bad_profile", [None, {}, "private-profile-canary"])
def test_cancellation_requires_actual_explicit_profile_type(bad_profile):
    module = implementation()
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.cancellation(
            cancellation_request(profile()), 1700000000000, profile=bad_profile
        )
    assert error.value.code == "invalid_input"
    assert str(error.value) == "Invalid deployment request."


def test_cancellation_does_not_infer_missing_profile_or_rebind_request_to_another_profile():
    module = implementation()
    request = cancellation_request(profile())
    with pytest.raises(TypeError):
        module.cancellation(request, 1700000000000)
    with pytest.raises(module.DeploymentPrepareError):
        module.cancellation(request, 1700000000000, profile=profile(True))


@pytest.mark.parametrize(
    "instant", [True, -1, 253402300800000, 1700000000000.0, "private-time-canary"]
)
def test_cancellation_rejects_invalid_transition_time_with_fixed_error(instant):
    module = implementation()
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.cancellation(cancellation_request(profile()), instant, profile=profile())
    assert error.value.code == "invalid_input"
    assert str(error.value) == "Invalid deployment request."


@pytest.mark.parametrize("bad_request", [None, {}, [], "private-request-canary"])
def test_cancellation_missing_identity_has_fixed_prepare_error(bad_request):
    module = implementation()
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.cancellation(bad_request, 1700000000000, profile=profile())
    assert error.value.code == "invalid_input"
    assert str(error.value) == "Invalid deployment request."
