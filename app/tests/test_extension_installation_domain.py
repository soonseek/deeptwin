"""Task 24 step (c1): the immutable `extension_installation` anchor
(`extension-installation-anchor-v1`) and the success consumption anchor v2
(`deployment-receipt-consumption-anchor-v2`), contracts/deployment-receipt-journal-v3.md §4.

Pure codecs over real immutable records and the ordinary envelope checks:
valid structure grants no installation, acceptance or head authority, and
no event, blob or head is inferred to exist.
"""

import importlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.domain import deployment_receipt, schema_exports
from app.domain.refs import DomainContractError, EntityRef
from app.domain.schemas import ImmutableRecord
from app.domain.store import BlobRef

ROOT = Path(__file__).resolve().parents[2] / "schemas" / "v1"
TIME = "2023-11-14T22:13:22.123Z"
CREATED = "2023-11-14T22:13:22.123000Z"


def implementation():
    try:
        return importlib.import_module("app.domain.extension_installation")
    except ModuleNotFoundError:
        pytest.fail("Extension installation domain contracts are missing")


def entity(kind, *, identity=None, digest="a" * 64):
    return EntityRef(kind, identity or str(uuid4()), 1, digest)


def installation_content(request_ref, receipt_ref, actor_ref, evidence):
    return {
        "schema_version": "extension-installation-anchor-v1",
        "extension_id": "synthetic-tool",
        "manifest_digest": "1" * 64,
        "service_descriptor_digest": "2" * 64,
        "selected_platform_entry_digest": "3" * 64,
        "image_manifest_digest": "sha256:" + "4" * 64,
        "platform": "linux/amd64",
        "service_identity": "ext-0123456789abcdef0123456789abcdef-04",
        "staging_authority": "deployment-receipt-v1",
        "request_ref": request_ref.as_dict(),
        "receipt_ref": receipt_ref.as_dict(),
        "postcondition_evidence_blob_ref": evidence.as_dict(),
        "consume_command_id": str(uuid4()),
        "state": "staged",
        "revision": 1,
        "previous_record_digest": None,
        "installed_at": TIME,
        "actor_ref": actor_ref.as_dict(),
    }


def consumption_v2_content(request_ref, receipt_ref, actor_ref, installation_ref):
    return {
        "schema_version": "deployment-receipt-consumption-anchor-v2",
        "request_ref": request_ref.as_dict(),
        "receipt_ref": receipt_ref.as_dict(),
        "winning_lifecycle_revision": 3,
        "consumed_at": TIME,
        "actor_ref": actor_ref.as_dict(),
        "transaction_id": str(uuid4()),
        "public_event_id": str(uuid4()),
        "outcome": "succeeded",
        "effect_ref": installation_ref.as_dict(),
    }


def refs():
    request_ref = entity("deployment_request")
    receipt_ref = entity("deployment_receipt", identity=request_ref.id, digest="b" * 64)
    actor_ref = entity("actor")
    evidence = BlobRef(str(uuid4()), "operational", "e" * 64, 512)
    return request_ref, receipt_ref, actor_ref, evidence


def installation_record(request_ref, receipt_ref, actor_ref, evidence, **changes):
    content = changes.pop(
        "content", installation_content(request_ref, receipt_ref, actor_ref, evidence)
    )
    return ImmutableRecord.create(
        kind="extension_installation",
        id=changes.pop("id", str(uuid4())),
        version=changes.pop("version", 1),
        created_at_utc=changes.pop("created_at_utc", CREATED),
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


def consumption_record(request_ref, receipt_ref, actor_ref, installation_ref, **changes):
    content = changes.pop(
        "content",
        consumption_v2_content(request_ref, receipt_ref, actor_ref, installation_ref),
    )
    return ImmutableRecord.create(
        kind="deployment_receipt_consumption",
        id=changes.pop("id", str(uuid4())),
        version=changes.pop("version", 1),
        created_at_utc=changes.pop("created_at_utc", CREATED),
        actor_ref=changes.pop("actor_ref", actor_ref),
        parent_refs=changes.pop(
            "parent_refs", (request_ref, receipt_ref, installation_ref)
        ),
        purpose=changes.pop("purpose", "operational"),
        access_policy_ref=changes.pop("access_policy_ref", entity("access_policy")),
        retention_policy_ref=changes.pop(
            "retention_policy_ref", entity("retention_policy")
        ),
        content=content,
        **changes,
    )


def test_installation_content_schema_is_closed_and_validates_the_exact_shape():
    module = implementation()
    request_ref, receipt_ref, actor_ref, evidence = refs()
    content = installation_content(request_ref, receipt_ref, actor_ref, evidence)
    validator = Draft202012Validator(
        module.installation_content_schema(), format_checker=FormatChecker()
    )
    assert validator.is_valid(content)
    first = module.installation_content_schema()
    first["properties"].clear()
    assert module.installation_content_schema()["properties"]  # detached copies
    for change in (
        {"future": None},
        {"state": "verified"},
        {"revision": 2},
        {"previous_record_digest": "0" * 64},
        {"staging_authority": "operator"},
        {"platform": "linux/riscv64"},
        {"image_manifest_digest": "4" * 64},
        {"extension_id": "Bad_Id"},
        {"service_identity": "Ext-1"},
        {"installed_at": CREATED},
        # jsonschema patterns use re.search, where `$` also matches before a
        # final newline: the anchoring must refuse a trailing LF
        {"extension_id": "synthetic-tool\n"},
        {"service_identity": "ext-1\n"},
        {"manifest_digest": "1" * 63 + "\n"},
    ):
        assert not validator.is_valid({**content, **change}), change
    for missing in content:
        assert not validator.is_valid({k: v for k, v in content.items() if k != missing})


def test_installation_record_round_trips_through_the_real_envelope():
    module = implementation()
    request_ref, receipt_ref, actor_ref, evidence = refs()
    record = installation_record(request_ref, receipt_ref, actor_ref, evidence)
    assert record.ref.kind == "extension_installation" and record.ref.version == 1
    module.validate_installation_body(record.body)  # creation already ran it
    assert record.body["content"]["state"] == "staged"


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "purpose",
        "parents",
        "parent_order",
        "request_kind",
        "receipt_kind",
        "receipt_version",
        "different_ids",
        "evidence_purpose",
        "evidence_oversize",
        "evidence_empty",
        "actor",
        "created",
        "command",
        "revision",
        "extra",
        "oversize",
    ],
)
def test_installation_envelope_rejects_every_header_ref_blob_time_and_cap_violation(
    change,
):
    request_ref, receipt_ref, actor_ref, evidence = refs()
    content = installation_content(request_ref, receipt_ref, actor_ref, evidence)
    headers = {}
    if change == "version":
        headers["version"] = 2
    elif change == "purpose":
        headers["purpose"] = "diagnosis"
    elif change == "parents":
        headers["parent_refs"] = (request_ref,)
    elif change == "parent_order":
        headers["parent_refs"] = (receipt_ref, request_ref)
    elif change == "request_kind":
        content["request_ref"]["kind"] = "actor"
    elif change == "receipt_kind":
        content["receipt_ref"]["kind"] = "deployment_request"
    elif change == "receipt_version":
        content["receipt_ref"]["version"] = 2
    elif change == "different_ids":
        content["receipt_ref"]["id"] = str(uuid4())
        # the parents match the mutated content, so only the id rule can refuse
        headers["parent_refs"] = (request_ref, EntityRef.from_dict(content["receipt_ref"]))
    elif change == "evidence_purpose":
        content["postcondition_evidence_blob_ref"]["purpose"] = "diagnosis"
    elif change == "evidence_oversize":
        content["postcondition_evidence_blob_ref"]["size"] = 8193
    elif change == "evidence_empty":
        content["postcondition_evidence_blob_ref"]["size"] = 0
    elif change == "actor":
        content["actor_ref"] = entity("actor").as_dict()
    elif change == "created":
        headers["created_at_utc"] = "2023-11-14T22:13:22.124000Z"
    elif change == "command":
        content["consume_command_id"] = "not-a-uuid-private-canary"
    elif change == "revision":
        content["revision"] = True  # a bool is not the integer 1
    elif change == "extra":
        content["future"] = "private-canary"
    else:
        # the closed content and headers cannot exceed the cap on their own,
        # so the cap is exercised on the validator directly: every other rule
        # holds and only the byte bound can refuse
        module = implementation()
        body = installation_record(request_ref, receipt_ref, actor_ref, evidence).body
        module.validate_installation_body(body)
        with pytest.raises(DomainContractError) as error:
            module.validate_installation_body({**body, "padding": "p" * 8_192})
        assert str(error.value) == "Invalid extension installation anchor"
        return
    with pytest.raises(DomainContractError) as error:
        installation_record(request_ref, receipt_ref, actor_ref, evidence, content=content, **headers)
    assert str(error.value) == "Invalid extension installation anchor"
    assert "private-canary" not in str(error.value)


def test_consumption_v2_round_trips_and_v1_rules_are_unchanged():
    request_ref, receipt_ref, actor_ref, evidence = refs()
    installation = installation_record(request_ref, receipt_ref, actor_ref, evidence)
    installation_ref = installation.ref
    record = consumption_record(request_ref, receipt_ref, actor_ref, installation_ref)
    deployment_receipt.validate_consumption_body(record.body)
    assert record.body["content"]["effect_ref"] == installation_ref.as_dict()
    # the v1 shape still validates exactly as before and refuses v2-only fields
    v1 = {
        **consumption_v2_content(request_ref, receipt_ref, actor_ref, installation_ref),
        "schema_version": "deployment-receipt-consumption-anchor-v1",
        "winning_lifecycle_revision": 2,
        "outcome": "failed",
    }
    del v1["effect_ref"]
    consumption_record(
        request_ref, receipt_ref, actor_ref, installation_ref,
        content=v1, parent_refs=(request_ref, receipt_ref),
    )
    with pytest.raises(DomainContractError):
        consumption_record(
            request_ref, receipt_ref, actor_ref, installation_ref,
            content={**v1, "outcome": "succeeded"}, parent_refs=(request_ref, receipt_ref),
        )
    schema = deployment_receipt.consumption_content_schema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert validator.is_valid(v1)
    assert validator.is_valid(record.body["content"])


@pytest.mark.parametrize(
    "change",
    [
        "revision_two",
        "outcome",
        "no_effect",
        "effect_kind",
        "effect_version",
        "parents_two",
        "parent_mismatch",
        "created",
        "extra",
    ],
)
def test_consumption_v2_rejects_every_success_rule_violation(change):
    request_ref, receipt_ref, actor_ref, evidence = refs()
    installation_ref = installation_record(request_ref, receipt_ref, actor_ref, evidence).ref
    content = consumption_v2_content(request_ref, receipt_ref, actor_ref, installation_ref)
    headers = {}
    if change == "revision_two":
        content["winning_lifecycle_revision"] = 2
    elif change == "outcome":
        content["outcome"] = "failed"
    elif change == "no_effect":
        del content["effect_ref"]
    elif change == "effect_kind":
        content["effect_ref"]["kind"] = "deployment_receipt"
    elif change == "effect_version":
        content["effect_ref"]["version"] = 2
    elif change == "parents_two":
        headers["parent_refs"] = (request_ref, receipt_ref)
    elif change == "parent_mismatch":
        headers["parent_refs"] = (request_ref, receipt_ref, entity("extension_installation"))
    elif change == "created":
        headers["created_at_utc"] = "2023-11-14T22:13:22.123456Z"
    else:
        content["future"] = "private-canary"
    with pytest.raises(DomainContractError) as error:
        consumption_record(
            request_ref, receipt_ref, actor_ref, installation_ref, content=content, **headers
        )
    assert str(error.value) == "Invalid deployment receipt consumption anchor"
    assert "private-canary" not in str(error.value)


def test_domain_envelope_export_covers_both_anchors_and_is_regenerated():
    schema = schema_exports.domain_schema()
    branches = {
        branch["if"]["properties"]["kind"]["const"]: branch
        for branch in schema["$defs"]["DomainBody"]["allOf"]
        if "if" in branch and "kind" in branch["if"].get("properties", {})
    }
    # the installation anchor is one variant beside the provider installation's
    # verified record; the extension anchor's own shape is unchanged
    installation_variants = {
        alternative["properties"]["content"]["properties"]["schema_version"]["const"]: alternative["properties"]
        for alternative in branches["extension_installation"]["then"]["oneOf"]
    }
    assert set(installation_variants) == {"extension-installation-anchor-v1", "provider-installation-verified-v1"}
    installation = installation_variants["extension-installation-anchor-v1"]
    assert installation["version"]["const"] == 1
    assert (
        installation["content"]["properties"]["schema_version"]["const"]
        == "extension-installation-anchor-v1"
    )
    assert installation["parent_refs"]["minItems"] == installation["parent_refs"]["maxItems"] == 2
    # the consumption branch pairs each content variant with its parent arity
    arities = {}
    for alternative in branches["deployment_receipt_consumption"]["then"]["oneOf"]:
        properties = alternative["properties"]
        version = properties["content"]["properties"]["schema_version"]["const"]
        parents = properties["parent_refs"]
        assert parents["minItems"] == parents["maxItems"] == len(parents["prefixItems"])
        arities[version] = parents["maxItems"]
    assert arities == {
        "deployment-receipt-consumption-anchor-v1": 2,
        "deployment-receipt-consumption-anchor-v2": 3,
    }
    assert schema == json.loads((ROOT / "domain-envelopes.schema.json").read_text())
    # the structural export admits the real records
    request_ref, receipt_ref, actor_ref, evidence = refs()
    installation_record_ = installation_record(request_ref, receipt_ref, actor_ref, evidence)
    consumption_record_ = consumption_record(
        request_ref, receipt_ref, actor_ref, installation_record_.ref
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for record in (installation_record_, consumption_record_):
        assert validator.is_valid(deepcopy(record.as_dict())), record.ref.kind
    # and refuses the crossed shapes the runtime refuses: v1 content with the
    # installation as a third parent, v2 content with only two parents
    v2 = deepcopy(consumption_record_.as_dict())
    v2["body"]["parent_refs"] = v2["body"]["parent_refs"][:2]
    assert not validator.is_valid(v2)
    v1 = deepcopy(consumption_record_.as_dict())
    v1["body"]["content"] = {
        **v1["body"]["content"],
        "schema_version": "deployment-receipt-consumption-anchor-v1",
        "winning_lifecycle_revision": 2,
        "outcome": "failed",
    }
    del v1["body"]["content"]["effect_ref"]
    assert not validator.is_valid(v1)
    v1["body"]["parent_refs"] = v1["body"]["parent_refs"][:2]
    assert validator.is_valid(v1)
