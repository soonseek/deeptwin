"""Receipt anchors use real immutable records and ordinary graph enforcement."""

import importlib
from copy import deepcopy
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.domain.refs import DomainContractError, EntityRef
from app.domain.schemas import ImmutableRecord
from app.domain.store import BlobRef, CorruptRecord, MissingBlob, MissingRecord
from app.tests.deployment_prepare_fixture import retained_anchor


def implementation():
    try:
        return importlib.import_module("app.domain.deployment_receipt")
    except ModuleNotFoundError:
        pytest.fail("Deployment receipt domain contracts are missing")


def entity(kind, *, identity=None, digest="a" * 64):
    return EntityRef(kind, identity or str(uuid4()), 1, digest)


def blob(vault_id, *, digest, size=10):
    return BlobRef(vault_id, "operational", digest, size)


def receipt_content(request_ref, blobs, *, command_id=None):
    return {
        "schema_version": "deployment-receipt-anchor-v1",
        "receipt_blob_ref": blobs[0].as_dict(),
        "request_ref": request_ref.as_dict(),
        "trust_blob_ref": blobs[1].as_dict(),
        "ingress_blob_ref": blobs[2].as_dict(),
        "consumption_exchange_blob_ref": blobs[3].as_dict(),
        "import_command_id": command_id or str(uuid4()),
    }


def consumption_content(request_ref, receipt_ref, actor_ref):
    return {
        "schema_version": "deployment-receipt-consumption-anchor-v1",
        "request_ref": request_ref.as_dict(),
        "receipt_ref": receipt_ref.as_dict(),
        "winning_lifecycle_revision": 2,
        "consumed_at": "2023-11-14T22:13:22.123Z",
        "actor_ref": actor_ref.as_dict(),
        "transaction_id": str(uuid4()),
        "public_event_id": str(uuid4()),
        "outcome": "failed",
    }


def receipt_record(request_ref=None, blobs=None, **changes):
    request_ref = request_ref or entity("deployment_request")
    vault_id = blobs[0].vault_id if blobs else str(uuid4())
    blobs = blobs or [blob(vault_id, digest=character * 64) for character in "abcd"]
    actor_ref = changes.pop("actor_ref", entity("actor"))
    content = changes.pop("content", receipt_content(request_ref, blobs))
    return ImmutableRecord.create(
        kind="deployment_receipt",
        id=changes.pop("id", request_ref.id),
        version=changes.pop("version", 1),
        created_at_utc=changes.pop("created_at_utc", "2023-11-14T22:13:22.123456Z"),
        actor_ref=actor_ref,
        parent_refs=changes.pop("parent_refs", (request_ref,)),
        purpose=changes.pop("purpose", "operational"),
        access_policy_ref=changes.pop("access_policy_ref", entity("access_policy")),
        retention_policy_ref=changes.pop(
            "retention_policy_ref", entity("retention_policy")
        ),
        content=content,
        **changes,
    )


def consumption_record(request_ref, receipt_ref, actor_ref, **changes):
    content = changes.pop(
        "content", consumption_content(request_ref, receipt_ref, actor_ref)
    )
    return ImmutableRecord.create(
        kind="deployment_receipt_consumption",
        id=changes.pop("id", str(uuid4())),
        version=changes.pop("version", 1),
        created_at_utc=changes.pop("created_at_utc", "2023-11-14T22:13:22.123000Z"),
        actor_ref=changes.pop("actor_ref", actor_ref),
        parent_refs=changes.pop("parent_refs", (request_ref, receipt_ref)),
        purpose=changes.pop("purpose", "operational"),
        access_policy_ref=changes.pop("access_policy_ref", entity("access_policy")),
        retention_policy_ref=changes.pop(
            "retention_policy_ref", entity("retention_policy")
        ),
        content=content,
        **changes,
    )


def test_content_schemas_are_closed_detached_and_validate_exact_shapes():
    module = implementation()
    request_ref = entity("deployment_request")
    vault_id = str(uuid4())
    blobs = [blob(vault_id, digest=character * 64) for character in "abcd"]
    receipt = receipt_content(request_ref, blobs)
    receipt_ref = entity("deployment_receipt", identity=request_ref.id)
    actor_ref = entity("actor")
    consumption = consumption_content(request_ref, receipt_ref, actor_ref)
    assert Draft202012Validator(module.receipt_content_schema()).is_valid(receipt)
    assert Draft202012Validator(
        module.consumption_content_schema(), format_checker=FormatChecker()
    ).is_valid(consumption)
    first = module.receipt_content_schema()
    first["properties"].clear()
    assert module.receipt_content_schema()["properties"]
    assert not Draft202012Validator(module.receipt_content_schema()).is_valid(
        {**receipt, "future": None}
    )


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "purpose",
        "id",
        "parent",
        "request_kind",
        "request_version",
        "blob_purpose",
        "foreign_blob",
        "empty_blob",
        "oversize_receipt",
        "oversize_ingress",
        "command",
        "extra",
    ],
)
def test_receipt_envelope_rejects_every_header_ref_blob_and_cap_violation(change):
    request_ref = entity("deployment_request")
    vault_id = str(uuid4())
    blobs = [blob(vault_id, digest=character * 64) for character in "abcd"]
    content = receipt_content(request_ref, blobs)
    headers = {}
    if change == "version":
        headers["version"] = 2
    elif change == "purpose":
        headers["purpose"] = "diagnosis"
    elif change == "id":
        headers["id"] = str(uuid4())
    elif change == "parent":
        headers["parent_refs"] = ()
    elif change == "request_kind":
        content["request_ref"]["kind"] = "actor"
    elif change == "request_version":
        content["request_ref"]["version"] = 2
    elif change == "blob_purpose":
        content["trust_blob_ref"]["purpose"] = "diagnosis"
    elif change == "foreign_blob":
        content["ingress_blob_ref"]["vault_id"] = str(uuid4())
    elif change == "empty_blob":
        content["receipt_blob_ref"]["size"] = 0
    elif change == "oversize_receipt":
        content["receipt_blob_ref"]["size"] = 16385
    elif change == "oversize_ingress":
        content["ingress_blob_ref"]["size"] = 8193
    elif change == "command":
        content["import_command_id"] = "not-a-uuid-private-canary"
    else:
        content["future"] = "private-canary"
    with pytest.raises(DomainContractError) as error:
        receipt_record(request_ref, blobs, content=content, **headers)
    assert str(error.value) == "Invalid deployment receipt anchor"
    assert "private-canary" not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "purpose",
        "parents",
        "request_kind",
        "receipt_kind",
        "request_version",
        "receipt_version",
        "different_ids",
        "revision_bool",
        "revision",
        "actor",
        "created",
        "transaction",
        "event",
        "outcome",
        "extra",
    ],
)
def test_consumption_envelope_rejects_every_header_ref_actor_time_and_outcome_violation(
    change,
):
    request_ref = entity("deployment_request")
    receipt_ref = entity("deployment_receipt", identity=request_ref.id)
    actor_ref = entity("actor")
    content = consumption_content(request_ref, receipt_ref, actor_ref)
    headers = {}
    if change == "version":
        headers["version"] = 2
    elif change == "purpose":
        headers["purpose"] = "diagnosis"
    elif change == "parents":
        headers["parent_refs"] = (receipt_ref, request_ref)
    elif change == "request_kind":
        content["request_ref"]["kind"] = "actor"
    elif change == "receipt_kind":
        content["receipt_ref"]["kind"] = "deployment_request"
    elif change == "request_version":
        content["request_ref"]["version"] = 2
    elif change == "receipt_version":
        content["receipt_ref"]["version"] = 2
    elif change == "different_ids":
        content["receipt_ref"]["id"] = str(uuid4())
    elif change == "revision_bool":
        content["winning_lifecycle_revision"] = True
    elif change == "revision":
        content["winning_lifecycle_revision"] = 3
    elif change == "actor":
        content["actor_ref"] = entity("actor").as_dict()
    elif change == "created":
        headers["created_at_utc"] = "2023-11-14T22:13:22.124000Z"
    elif change == "transaction":
        content["transaction_id"] = "private-canary"
    elif change == "event":
        content["public_event_id"] = "00000000-0000-0000-0000-000000000000"
    elif change == "outcome":
        content["outcome"] = "succeeded"
    else:
        content["future"] = "private-canary"
    with pytest.raises(DomainContractError) as error:
        consumption_record(
            request_ref, receipt_ref, actor_ref, content=content, **headers
        )
    assert str(error.value) == "Invalid deployment receipt consumption anchor"
    assert "private-canary" not in str(error.value)


def test_consumption_time_accepts_millisecond_content_with_zero_padded_envelope():
    implementation()
    request_ref = entity("deployment_request")
    receipt_ref = entity("deployment_receipt", identity=request_ref.id)
    actor_ref = entity("actor")
    content = consumption_content(request_ref, receipt_ref, actor_ref)
    content["consumed_at"] = "2023-11-14T22:13:22.123Z"

    record = consumption_record(
        request_ref,
        receipt_ref,
        actor_ref,
        content=content,
        created_at_utc="2023-11-14T22:13:22.123000Z",
    )

    assert record.body["content"]["consumed_at"] == "2023-11-14T22:13:22.123Z"
    assert record.body["created_at_utc"] == "2023-11-14T22:13:22.123000Z"


def test_consumption_time_rejects_six_digit_content_even_when_header_matches():
    implementation()
    request_ref = entity("deployment_request")
    receipt_ref = entity("deployment_receipt", identity=request_ref.id)
    actor_ref = entity("actor")
    content = consumption_content(request_ref, receipt_ref, actor_ref)
    content["consumed_at"] = "2023-11-14T22:13:22.123000Z"

    with pytest.raises(DomainContractError) as error:
        consumption_record(
            request_ref,
            receipt_ref,
            actor_ref,
            content=content,
            created_at_utc="2023-11-14T22:13:22.123000Z",
        )

    assert str(error.value) == "Invalid deployment receipt consumption anchor"


def test_consumption_time_rejects_invalid_calendar_content_without_header_masking():
    module = implementation()
    request_ref = entity("deployment_request")
    receipt_ref = entity("deployment_receipt", identity=request_ref.id)
    actor_ref = entity("actor")
    body = deepcopy(consumption_record(request_ref, receipt_ref, actor_ref).body)
    body["content"]["consumed_at"] = "2023-02-30T22:13:22.123Z"

    with pytest.raises(DomainContractError) as error:
        module.validate_consumption_body(body)

    assert str(error.value) == "Invalid deployment receipt consumption anchor"


def test_consumption_time_rejects_a_different_envelope_instant():
    implementation()
    request_ref = entity("deployment_request")
    receipt_ref = entity("deployment_receipt", identity=request_ref.id)
    actor_ref = entity("actor")
    content = consumption_content(request_ref, receipt_ref, actor_ref)
    content["consumed_at"] = "2023-11-14T22:13:22.123Z"

    with pytest.raises(DomainContractError) as error:
        consumption_record(
            request_ref,
            receipt_ref,
            actor_ref,
            content=content,
            created_at_utc="2023-11-14T22:13:22.124000Z",
        )

    assert str(error.value) == "Invalid deployment receipt consumption anchor"


def test_structural_event_uuid_and_valid_record_shape_remain_inert():
    request_ref = entity("deployment_request")
    receipt_ref = entity("deployment_receipt", identity=request_ref.id)
    actor_ref = entity("actor")
    record = consumption_record(request_ref, receipt_ref, actor_ref)
    assert record.body["content"]["public_event_id"]
    assert record.ref.kind == "deployment_receipt_consumption"


def persisted_receipt(actual, *, request_ref=None, receipt_blobs=None):
    from app.deployment.receipt_render import render_receipt_sources
    from app.tests.deployment_receipt_source_fixture import _public_receipt_case
    from app.tests.test_deployment_receipt_source_render import receipt_inputs

    domain = actual.domain
    roots = domain.roots()
    request_ref = request_ref or actual.record.ref
    actor_ref = EntityRef.from_dict(actual.record.body["actor_ref"])
    inputs = receipt_inputs()
    sources = render_receipt_sources(*inputs)
    case = _public_receipt_case()
    public_bytes = (
        case["receipt_utf8"].encode(),
        sources.trust_bytes,
        sources.ingress_bytes,
        sources.consumption_exchange_bytes,
    )
    receipt_blobs = receipt_blobs or [
        domain.put_blob(raw, purpose="operational") for raw in public_bytes
    ]
    record = receipt_record(
        request_ref,
        receipt_blobs,
        actor_ref=actor_ref,
        access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
    )
    return record, actor_ref, roots


def test_real_domain_store_roundtrip_uses_actual_request_graph_and_four_public_blobs(
    tmp_path,
):
    with retained_anchor(tmp_path) as actual:
        receipt, actor_ref, roots = persisted_receipt(actual)
        assert actual.domain.put(receipt) == receipt.ref
        assert actual.domain.get(receipt.ref) == receipt
        consumption = consumption_record(
            actual.record.ref,
            receipt.ref,
            actor_ref,
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
        )
        assert actual.domain.put(consumption) == consumption.ref
        assert actual.domain.get(consumption.ref) == consumption


def test_real_domain_store_rejects_missing_or_foreign_refs_and_missing_blobs(tmp_path):
    with retained_anchor(tmp_path) as actual:
        _receipt, actor_ref, roots = persisted_receipt(actual)
        missing_request = entity("deployment_request")
        missing_receipt = receipt_record(
            missing_request,
            [
                actual.domain.put_blob(value, purpose="operational")
                for value in (b"a", b"b", b"c", b"d")
            ],
            actor_ref=actor_ref,
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
        )
        with pytest.raises(MissingRecord):
            actual.domain.put(missing_receipt)
        wrong_hash = EntityRef(
            actual.record.ref.kind,
            actual.record.ref.id,
            actual.record.ref.version,
            "f" * 64,
        )
        foreign_receipt = receipt_record(
            wrong_hash,
            [
                actual.domain.put_blob(value, purpose="operational")
                for value in (b"e", b"f", b"g", b"h")
            ],
            actor_ref=actor_ref,
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
        )
        with pytest.raises(CorruptRecord):
            actual.domain.put(foreign_receipt)
        values = [
            actual.domain.put_blob(value, purpose="operational")
            for value in (b"i", b"j", b"k", b"l")
        ]
        values[0] = BlobRef(actual.domain.vault_id, "operational", "0" * 64, 1)
        absent_blob_receipt = receipt_record(
            actual.record.ref,
            values,
            actor_ref=actor_ref,
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
        )
        with pytest.raises(MissingBlob):
            actual.domain.put(absent_blob_receipt)


def test_domain_schema_registers_both_closed_body_variants_without_authority_claim():
    from app.domain.schema_exports import domain_schema

    request_ref = entity("deployment_request")
    vault_id = str(uuid4())
    receipt = receipt_record(
        request_ref,
        [blob(vault_id, digest=character * 64) for character in "abcd"],
    )
    receipt_ref = receipt.ref
    actor_ref = EntityRef.from_dict(receipt.body["actor_ref"])
    consumption = consumption_record(request_ref, receipt_ref, actor_ref)
    check = Draft202012Validator(domain_schema(), format_checker=FormatChecker())
    assert check.is_valid(receipt.as_dict())
    assert check.is_valid(consumption.as_dict())
    malformed = deepcopy(receipt.as_dict())
    malformed["body"]["content"]["receipt_blob_ref"]["size"] = 16385
    assert not check.is_valid(malformed)
    assert "authority" in domain_schema()["$comment"]
