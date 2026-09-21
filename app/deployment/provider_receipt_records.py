"""Provider receipt graphs on the existing domain store and verified journal."""

from hashlib import sha256
from uuid import uuid4
from ..domain.refs import EntityRef, parse_canonical, canonical_json
from ..domain.store import BlobRef
from ..domain.schemas import ImmutableRecord
from . import (
    prepare_records as old,
    prepare_storage as storage,
    prepare_lifecycle as legacy,
)
from . import provider_receipt_lifecycle as lifecycle
from .prepare_contracts import require, epoch_ms, b64, DeploymentPrepareError
from .provider_receipt_contracts import (
    validate_provider_channel_identity,
    verify_provider_receipt,
)


def load_sources(roots, rows, context):
    receipts = [
        r for r in rows.get("receipts", ()) if r.get("provider_context_id") is not None
    ]
    sources = rows.get("provider_receipt_sources", ())
    require(bool(sources) == bool(receipts), "unavailable")
    if not sources:
        return None
    require(len(sources) == 1 and context is not None, "unavailable")
    row = sources[0]
    identity = parse_canonical(row["identity_json"].encode())
    validate_provider_channel_identity(identity)
    require(
        row["vault_id"] == roots.genesis.id
        and row["context_id"] == context["row"]["context_id"]
        and identity["source_context_sha256"]
        == sha256(context["files"][16][1]).hexdigest()
        and all(
            r["provider_context_id"] == row["context_id"]
            and r["source_singleton"] is None
            for r in receipts
        ),
        "unavailable",
    )
    return {"row": row, "identity": identity}


def load_receipt(domain, db, roots, profile, item, binding, row):
    require(binding is not None and len(item["history"]) >= 2, "unavailable")
    ref = EntityRef("deployment_receipt", row["request_id"], 1, row["anchor_digest"])
    old.bound_associations(db, roots.genesis.id, ref.kind, ref.id, 1, edges=4, blobs=1)
    record = old.bounded_body(db, roots.genesis.id, ref, 8192)
    anchor = record.body["content"]
    blob = BlobRef.from_dict(anchor["receipt_blob_ref"])
    raw = old._bounded_blob(domain, db, roots, blob, 16384)
    domain._check_graph(db, [ref], roots)
    files = item["context"]["files"]
    value = verify_provider_receipt(
        raw,
        request_bytes=item["raw"],
        trust_bytes=dict(files)["provider-trust-set.json"],
        source_bundle_files=files,
        profile=profile,
    )
    history = item["history"][1]
    expected = {
        "schema_version": "deployment-provider-receipt-anchor-v1",
        "request_ref": item["ref"].as_dict(),
        "receipt_blob_ref": blob.as_dict(),
        "source_context_sha256": item["request"]["effect_payload"]["source_context"][
            "sha256"
        ],
        "channel_identity": binding["identity"],
        "import_command_id": history["command_id"],
    }
    require(
        anchor == expected
        and blob.vault_id == roots.genesis.id
        and blob.purpose == "operational"
        and blob.sha256 == row["receipt_sha256"]
        and blob.size == row["receipt_size"]
        and row["provider_context_id"] == item["context"]["row"]["context_id"]
        and row["source_singleton"] is None
        and row["import_command_id"] == history["command_id"]
        and row["lifecycle_revision"] == 2
        and value["outcome"] == row["outcome"]
        and record.body["actor_ref"] == item["actor"].as_dict()
        and record.body["access_policy_ref"] == roots.access_policy.as_dict()
        and record.body["retention_policy_ref"] == roots.retention_policy.as_dict()
        and record.body["created_at_utc"] == legacy.instant(history["transitioned_ms"])
        and history["state"]
        == ("receipt_pending" if value["outcome"] == "succeeded" else "rejected")
        and epoch_ms(value["completed_at"])
        <= history["transitioned_ms"]
        < item["row"]["expires_ms"],
        "unavailable",
    )
    return {
        "ref": ref,
        "record": record,
        "anchor": anchor,
        "row": row,
        "raw": raw,
        "value": value,
        "digest": b64(bytes.fromhex(blob.sha256)),
    }


def attach_receipt(
    service, db, journal, item, value, actor_ref, now, blob, raw, identity, verified
):
    roots = service._domain._read_roots(db)
    if journal["provider_receipt_sources"] is None:
        storage.insert(
            db,
            "provider_receipt_sources",
            {
                "context_id": item["context"]["row"]["context_id"],
                "vault_id": roots.genesis.id,
                "identity_json": storage.encoded(identity),
            },
        )
    anchor = {
        "schema_version": "deployment-provider-receipt-anchor-v1",
        "request_ref": item["ref"].as_dict(),
        "receipt_blob_ref": blob.as_dict(),
        "source_context_sha256": item["request"]["effect_payload"]["source_context"][
            "sha256"
        ],
        "channel_identity": identity,
        "import_command_id": value["command_id"],
    }
    record = ImmutableRecord.create(
        kind="deployment_receipt",
        id=item["ref"].id,
        version=1,
        created_at_utc=legacy.instant(now),
        actor_ref=actor_ref,
        parent_refs=(item["ref"],),
        purpose="operational",
        access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content=anchor,
    )
    service._domain._put_in_transaction(db, record)
    item["receipt"] = {
        "ref": record.ref,
        "anchor": anchor,
        "raw": raw,
        "value": verified,
        "digest": value["receipt_digest"],
    }
    state = "receipt_pending" if verified["outcome"] == "succeeded" else "rejected"
    _, event = legacy._append_transition(
        db,
        roots,
        service._profile,
        item,
        state=state,
        now=now,
        actor_ref=actor_ref,
        command_id=value["command_id"],
        receipt_outcome=verified["outcome"],
    )
    if state == "rejected":
        content = {
            "schema_version": "deployment-receipt-consumption-anchor-v1",
            "request_ref": item["ref"].as_dict(),
            "receipt_ref": record.ref.as_dict(),
            "winning_lifecycle_revision": 2,
            "consumed_at": legacy.stamp(now),
            "actor_ref": actor_ref.as_dict(),
            "transaction_id": value["command_id"],
            "public_event_id": event.event_id,
            "outcome": verified["outcome"],
        }
        consumption = ImmutableRecord.create(
            kind="deployment_receipt_consumption",
            id=str(uuid4()),
            version=1,
            created_at_utc=legacy.instant(now),
            actor_ref=actor_ref,
            parent_refs=(item["ref"], record.ref),
            purpose="operational",
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content=content,
        )
        service._domain._put_in_transaction(db, consumption)
        item["consumption"] = {"ref": consumption.ref, "anchor": content}
        item["consumed_outbox"] = {"state": "pending"}
    result = lifecycle._freeze_command(
        db, roots, service._profile, item, actor_ref=actor_ref, value=value, event=event
    )
    row = storage.insert(
        db,
        "receipts",
        {
            "request_id": item["ref"].id,
            "vault_id": roots.genesis.id,
            "kind": "deployment_receipt",
            "version": 1,
            "anchor_digest": record.ref.sha256,
            "receipt_sha256": blob.sha256,
            "receipt_size": blob.size,
            "outcome": verified["outcome"],
            "source_singleton": None,
            "provider_context_id": item["context"]["row"]["context_id"],
            "import_command_id": value["command_id"],
            "lifecycle_revision": 2,
        },
    )
    item["receipt"] = {
        "ref": record.ref,
        "anchor": anchor,
        "row": row,
        "raw": raw,
        "value": verified,
        "digest": value["receipt_digest"],
    }
    if state == "rejected":
        item["consumption"]["row"] = storage.insert(
            db,
            "consumptions",
            {
                "request_id": item["ref"].id,
                "receipt_sha256": blob.sha256,
                "consumption_id": consumption.ref.id,
                "vault_id": roots.genesis.id,
                "kind": "deployment_receipt_consumption",
                "version": 1,
                "anchor_digest": consumption.ref.sha256,
                "lifecycle_revision": 2,
                "command_id": value["command_id"],
                "event_id": event.event_id,
                "consumed_ms": now,
            },
        )
        marker = lifecycle.consumed_payload(item)
        item["consumed_outbox"] = storage.insert(
            db,
            "consumed_outbox",
            {
                "consumption_id": consumption.ref.id,
                "payload_sha256": sha256(marker).hexdigest(),
                "payload_size": len(marker),
                "state": "pending",
                "published_ms": None,
                "revision": 1,
            },
        )
    return result


def expected_stage_identity(domain, db, profile, item):
    from ..extensions.provider_lineage import (
        parse_provider_lineage,
        validate_provider_descriptor_lineage,
    )
    from ..extensions.provider_identity import parse_provider_build_identity
    from .provider_prepare_records import _provider_schema_bytes
    from .provider_stage_observer import (
        ExpectedProviderStageIdentity,
        StagePostconditionError,
    )
    from .contracts import slot

    try:
        bundle, ref = old.candidate(domain, db, item["anchor"]["candidate_ref"]["id"])
        require(ref.as_dict() == item["anchor"]["candidate_ref"], "conflict")
        documents = [raw for kind, raw in bundle.documents if kind == "provenance"]
        require(len(documents) == 1, "conflict")
        lineage = parse_provider_lineage(documents[0])
        validate_provider_descriptor_lineage(
            lineage,
            bundle.descriptor,
            instance_id=profile.instance_id,
            slot_number=item["row"]["slot_id"],
            schema_bytes=_provider_schema_bytes(),
        )
        platform = item["request"]["effect_payload"]["selected_platform_entry"][
            "platform"
        ]
        entries = [
            entry
            for entry in lineage.as_dict()["platforms"]
            if entry["measured_platform_entry"]["platform"] == platform
        ]
        require(len(entries) == 1, "conflict")
        identity = parse_provider_build_identity(
            canonical_json(entries[0]["build_identity"])
        )
        routing = slot(profile.instance_id, item["row"]["slot_id"])
        return ExpectedProviderStageIdentity(
            routing["service_identity"],
            identity.digest,
            identity.schema_set_digest,
            "provider-port-v1",
            platform,
            routing["uid"],
            routing["gid"],
        )
    except (
        ValueError,
        KeyError,
        TypeError,
        DeploymentPrepareError,
        StagePostconditionError,
    ):
        raise DeploymentPrepareError("conflict") from None


def evidence_agrees(parsed, item, expected, now):
    stage, receipt = item["request"]["effect_payload"], item["receipt"]
    return (
        parsed["expected"] == expected.as_dict()
        and parsed["request_id"] == item["ref"].id
        and parsed["request_digest"] == item["request"]["request_digest"]
        and parsed["receipt_digest"] == receipt["digest"]
        and parsed["request_blob_sha256"] == sha256(item["raw"]).hexdigest()
        and parsed["receipt_blob_sha256"] == receipt["row"]["receipt_sha256"]
        and parsed["source_context_sha256"] == stage["source_context"]["sha256"]
        and parsed["preserved_inventory_sha256"] == stage["preserved_inventory_sha256"]
        and expected.service_identity
        == receipt["value"]["effect_result"]["new_service"]["service_identity"]
        and all(
            item["history"][1]["transitioned_ms"] <= epoch_ms(o["observed_at"]) <= now
            for o in parsed["observations"]
        )
    )


def _installation_anchor(item, evidence, command_id, now):
    stage = item["request"]["effect_payload"]
    present = item["receipt"]["value"]["effect_result"]["new_service"]
    return {
        "schema_version": "extension-provider-installation-anchor-v1",
        "extension_id": stage["extension_id"],
        **{
            k: present[k]
            for k in (
                "manifest_digest",
                "service_descriptor_digest",
                "selected_platform_entry_digest",
                "image_manifest_digest",
                "service_identity",
            )
        },
        "platform": stage["selected_platform_entry"]["platform"],
        "staging_authority": "deployment-provider-receipt-v1",
        "request_ref": item["ref"].as_dict(),
        "receipt_ref": item["receipt"]["ref"].as_dict(),
        "postcondition_evidence_blob_ref": evidence.as_dict(),
        "consume_command_id": command_id,
        "state": "staged",
        "revision": 1,
        "previous_record_digest": None,
        "installed_at": legacy.stamp(now),
        "actor_ref": item["actor"].as_dict(),
        "stage_profile": "claude-text-transform-v1",
        "source_context_sha256": stage["source_context"]["sha256"],
        "preserved_inventory_sha256": stage["preserved_inventory_sha256"],
    }


def accept_stage(
    domain, db, roots, profile, item, *, now, actor_ref, value, evidence, evidence_bytes
):
    from ..domain.public_events import _append_event_in_transaction
    from .provider_stage_observer import parse_provider_stage_evidence
    from .provider_receipt_contracts import parse_provider_consume

    domain._assert_write_transaction(db)
    require(
        parse_provider_consume(
            item["ref"].id, {k: v for k, v in value.items() if k != "request_id"}
        )
        == value
        and item["head"]["revision"] == 2
        and len(item["history"]) == 2
        and item["history"][-1]["state"] == "receipt_pending"
        and item["receipt"]["value"]["outcome"] == "succeeded"
        and value["request_digest"] == item["request"]["request_digest"]
        and value["receipt_digest"] == item["receipt"]["digest"]
        and actor_ref == item["actor"]
        and item["history"][-1]["transitioned_ms"] <= now < item["row"]["expires_ms"],
        "conflict",
    )
    require(
        type(evidence) is BlobRef
        and evidence.vault_id == roots.genesis.id
        and evidence.purpose == "operational"
        and evidence.sha256 == sha256(evidence_bytes).hexdigest()
        and evidence.size == len(evidence_bytes)
        and old._bounded_blob(domain, db, roots, evidence, 8192) == evidence_bytes,
        "conflict",
    )
    parsed = parse_provider_stage_evidence(evidence_bytes)
    require(
        evidence_agrees(
            parsed, item, expected_stage_identity(domain, db, profile, item), now
        ),
        "conflict",
    )
    common = {
        "version": 1,
        "created_at_utc": legacy.instant(now),
        "actor_ref": actor_ref,
        "purpose": "operational",
        "access_policy_ref": roots.access_policy,
        "retention_policy_ref": roots.retention_policy,
    }
    anchor = _installation_anchor(item, evidence, value["command_id"], now)
    installation = ImmutableRecord.create(
        kind="extension_installation",
        id=str(uuid4()),
        parent_refs=(item["ref"], item["receipt"]["ref"]),
        content=anchor,
        **common,
    )
    domain._put_in_transaction(db, installation)
    _, event = legacy._append_transition(
        db,
        roots,
        profile,
        item,
        state="accepted",
        now=now,
        actor_ref=actor_ref,
        command_id=value["command_id"],
    )
    staged = _append_event_in_transaction(
        db,
        **lifecycle.staged_event_fields(
            roots,
            installation.ref,
            now,
            actor_ref,
            correlation_id=value["command_id"],
            causation_id=event.event_id,
        ),
    )
    content = {
        "schema_version": "deployment-receipt-consumption-anchor-v2",
        "request_ref": item["ref"].as_dict(),
        "receipt_ref": item["receipt"]["ref"].as_dict(),
        "winning_lifecycle_revision": 3,
        "consumed_at": legacy.stamp(now),
        "actor_ref": actor_ref.as_dict(),
        "transaction_id": value["command_id"],
        "public_event_id": event.event_id,
        "outcome": "succeeded",
        "effect_ref": installation.ref.as_dict(),
    }
    consumption = ImmutableRecord.create(
        kind="deployment_receipt_consumption",
        id=str(uuid4()),
        parent_refs=(item["ref"], item["receipt"]["ref"], installation.ref),
        content=content,
        **common,
    )
    domain._put_in_transaction(db, consumption)
    item["installation"] = {"ref": installation.ref, "anchor": anchor}
    item["consumption"] = {"ref": consumption.ref, "anchor": content}
    item["consumed_outbox"] = None
    result = lifecycle._freeze_command(
        db, roots, profile, item, actor_ref=actor_ref, value=value, event=event
    )
    item["consumption"]["row"] = storage.insert(
        db,
        "consumptions",
        {
            "request_id": item["ref"].id,
            "receipt_sha256": item["receipt"]["row"]["receipt_sha256"],
            "consumption_id": consumption.ref.id,
            "vault_id": roots.genesis.id,
            "kind": "deployment_receipt_consumption",
            "version": 1,
            "anchor_digest": consumption.ref.sha256,
            "lifecycle_revision": 3,
            "command_id": value["command_id"],
            "event_id": event.event_id,
            "consumed_ms": now,
        },
    )
    item["installation"]["row"] = storage.insert(
        db,
        "installations",
        {
            "request_id": item["ref"].id,
            "extension_id": anchor["extension_id"],
            "vault_id": roots.genesis.id,
            "purpose": "operational",
            "kind": "extension_installation",
            "installation_id": installation.ref.id,
            "version": 1,
            "anchor_digest": installation.ref.sha256,
            "evidence_sha256": evidence.sha256,
            "evidence_size": evidence.size,
            "consumption_id": consumption.ref.id,
            "lifecycle_revision": 3,
            "command_id": value["command_id"],
            "event_id": staged.event_id,
            "installed_ms": now,
        },
    )
    item["installation"]["head"] = storage.insert(
        db,
        "installation_heads",
        {
            "extension_id": anchor["extension_id"],
            "request_id": item["ref"].id,
            "revision": 1,
            "installation_anchor_digest": installation.ref.sha256,
        },
    )
    return result


def load_installation(domain, db, roots, profile, item, consumption, row, head_rows):
    from ..domain.public_events import EventEnvelope
    from .provider_stage_observer import (
        parse_provider_stage_evidence,
        StagePostconditionError,
    )

    require(
        len(item["history"]) == 3
        and item["history"][-1]["state"] == "accepted"
        and consumption is not None,
        "unavailable",
    )
    accepted = item["history"][-1]
    ref = EntityRef(
        "extension_installation", row["installation_id"], 1, row["anchor_digest"]
    )
    old.bound_associations(db, roots.genesis.id, ref.kind, ref.id, 1, edges=5, blobs=1)
    record = old.bounded_body(db, roots.genesis.id, ref, 8192)
    domain._check_graph(db, [ref], roots)
    evidence = BlobRef(
        row["vault_id"], row["purpose"], row["evidence_sha256"], row["evidence_size"]
    )
    try:
        parsed = parse_provider_stage_evidence(
            old._bounded_blob(domain, db, roots, evidence, 8192)
        )
    except StagePostconditionError:
        raise DeploymentPrepareError("unavailable") from None
    anchor = record.body["content"]
    require(
        anchor
        == _installation_anchor(
            item, evidence, accepted["command_id"], accepted["transitioned_ms"]
        )
        and evidence_agrees(
            parsed,
            item,
            expected_stage_identity(domain, db, profile, item),
            accepted["transitioned_ms"],
        )
        and row["request_id"] == item["ref"].id
        and row["vault_id"] == roots.genesis.id
        and row["extension_id"] == anchor["extension_id"]
        and row["consumption_id"] == consumption["ref"].id
        and row["command_id"] == accepted["command_id"]
        and row["installed_ms"] == accepted["transitioned_ms"]
        and consumption["anchor"]["effect_ref"] == ref.as_dict()
        and record.body["actor_ref"] == item["actor"].as_dict()
        and record.body["access_policy_ref"] == roots.access_policy.as_dict()
        and record.body["retention_policy_ref"] == roots.retention_policy.as_dict(),
        "unavailable",
    )
    historical_head = old.stage_head(row)
    event_row = db.execute(
        "SELECT * FROM api_event_envelopes WHERE event_id=? LIMIT 2", (row["event_id"],)
    ).fetchone()
    sequence = db.execute(
        "SELECT sequence FROM api_event_envelopes WHERE event_id=? LIMIT 2",
        (accepted["event_id"],),
    ).fetchone()
    require(
        event_row is not None
        and sequence is not None
        and event_row["sequence"] == sequence[0] + 1
        and event_row["event_type"] == "extension.staged"
        and event_row["vault_id"] == roots.genesis.id
        and type(event_row["envelope"]) is bytes
        and len(event_row["envelope"]) <= 8192,
        "unavailable",
    )
    event = EventEnvelope.from_bytes(event_row["envelope"])
    expected_event = EventEnvelope.create(
        event_id=row["event_id"],
        sequence=event_row["sequence"],
        **lifecycle.staged_event_fields(
            roots,
            ref,
            accepted["transitioned_ms"],
            item["actor"],
            correlation_id=accepted["command_id"],
            causation_id=accepted["event_id"],
        ),
    )
    require(event.body_bytes == expected_event.body_bytes, "unavailable")
    return {
        "ref": ref,
        "record": record,
        "anchor": anchor,
        "row": row,
        "head": historical_head,
        "evidence": parsed,
        "evidence_blob": evidence,
    }
