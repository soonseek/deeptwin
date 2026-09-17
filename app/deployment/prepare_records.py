"""Bounded admission of retained deployment anchors and their private journal."""

import sqlite3
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256

from ..domain.public_events import _assert_event_schema
from ..domain.refs import EntityRef, parse_canonical
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef
from ..extensions import candidate_storage
from ..extensions.candidate_contracts import parse_bundle
from ..extensions.candidate_records import load_candidate
from . import contracts as sources
from . import prepare_lifecycle as lifecycle
from . import prepare_storage as storage
from .prepare_contracts import (
    DeploymentPrepareError,
    epoch_ms,
    parse_request,
    require,
    stage_for_candidate,
)
from .receipt_contracts import parse_trust_set, verify_receipt
from .receipt_source_contracts import (
    RECEIPT_RECIPE_SHA256,
    parse_consumption_exchange,
    parse_ingress,
)


def install_storage(db):
    """Admit retained scalars before the unchanged installer's full-row load."""
    try:
        present = db.execute(
            "SELECT 1 FROM sqlite_master WHERE lower(name) GLOB 'deployment_prepare_*' LIMIT 1"
        ).fetchone()
        if present is not None:
            private_sizes(db)
        # Wholly absent schema still goes through the committed-anchor guard.
        storage.install(db)
    except sqlite3.Error:
        raise DeploymentPrepareError("unavailable") from None


def install(domain, db, profile, *, candidate_registry):
    from ..extensions.persistence import PersistentCandidateRegistry

    domain._assert_write_transaction(db)
    require(
        type(candidate_registry) is PersistentCandidateRegistry
        and candidate_registry._domain is domain
        and candidate_registry._owner._domain is domain
        and candidate_registry._owner.profile == profile,
        "unavailable",
    )
    bounded_candidates(domain, db)
    candidate_registry._verify(db)
    if not storage.shape(db):
        require(
            db.execute(
                "SELECT 1 FROM domain_records WHERE kind IN ('deployment_request','deployment_receipt','deployment_receipt_consumption','extension_installation') LIMIT 1"
            ).fetchone()
            is None,
            "unavailable",
        )
        require(
            db.execute(
                "SELECT 1 FROM api_event_envelopes WHERE event_type IN ('deployment.request_prepared','deployment.request_cancelled','deployment.request_expired','deployment.receipt_committed') LIMIT 1"
            ).fetchone()
            is None,
            "unavailable",
        )
        storage.install(db)
    journal = verify(domain, db, profile)
    if storage._layout(db) is storage._V1:
        storage._rebuild_v1_as_v2(db)
        journal = verify(domain, db, profile)
    if storage._layout(db) is storage._V2:
        # forward-only, in the same writer, each shape verified before the next
        storage._rebuild_v2_as_v3(db)
        journal = verify(domain, db, profile)
    require(db.execute("PRAGMA foreign_key_check").fetchone() is None, "unavailable")
    return journal


def verify(domain, db, profile):
    private_sizes(db)
    rows = storage.verify(db)
    for kind in (
        "deployment_request",
        "deployment_receipt",
        "deployment_receipt_consumption",
        "extension_installation",
    ):
        _anchor_dimensions(db, kind)
    if "receipts" not in rows:
        require(
            db.execute(
                "SELECT 1 FROM domain_records WHERE kind IN ('deployment_receipt','deployment_receipt_consumption') LIMIT 1"
            ).fetchone()
            is None,
            "unavailable",
        )
    if "installations" not in rows:
        # before v3 no installation anchor can be owned by this journal
        require(
            db.execute(
                "SELECT 1 FROM domain_records WHERE kind='extension_installation' LIMIT 1"
            ).fetchone()
            is None,
            "unavailable",
        )
    else:
        # journal v3 §4: heads ↔ installations, revision 1, same anchor digest
        require(
            {
                (r["extension_id"], r["request_id"], r["installation_anchor_digest"])
                for r in rows["installation_heads"]
                if r["revision"] == 1
            }
            == {
                (r["extension_id"], r["request_id"], r["anchor_digest"])
                for r in rows["installations"]
            }
            and len(rows["installation_heads"]) == len(rows["installations"]),
            "unavailable",
        )
    anchors = list(
        db.execute(
            "SELECT vault_id,kind,id,version,sha256 FROM domain_records "
            "WHERE kind='deployment_request' LIMIT 17"
        )
    )
    require(len(anchors) <= 16, "unavailable")
    require(
        {tuple(r) for r in anchors}
        == {
            (
                r["vault_id"],
                r["kind"],
                r["request_id"],
                r["version"],
                r["anchor_digest"],
            )
            for r in rows["requests"]
        },
        "unavailable",
    )
    require(bool(rows["control"]) == bool(anchors), "unavailable")
    for kind, table, key in (
        ("deployment_receipt", "receipts", "request_id"),
        ("deployment_receipt_consumption", "consumptions", "consumption_id"),
        ("extension_installation", "installations", "installation_id"),
    ):
        entities = {
            tuple(row)
            for row in db.execute(
                "SELECT vault_id,kind,id,version,sha256 FROM domain_records WHERE kind=? LIMIT 17",
                (kind,),
            )
        }
        require(
            entities
            == {
                (r["vault_id"], r["kind"], r[key], r["version"], r["anchor_digest"])
                for r in rows.get(table, ())
            },
            "unavailable",
        )
    events = list(
        db.execute(
            "SELECT event_id FROM api_event_envelopes WHERE event_type IN "
            "('deployment.request_prepared','deployment.request_cancelled','deployment.request_expired','deployment.receipt_committed','deployment.request_accepted') LIMIT 49"
        )
    )
    require(
        len(events) <= (48 if "receipts" in rows else 32)
        and {r[0] for r in events} == {r["event_id"] for r in rows["lifecycle"]},
        "unavailable",
    )
    if not anchors:
        require(not any(rows.values()), "unavailable")
        return {"control": None, "requests": {}, "rows": rows, "receipt_sources": None}
    roots = domain._read_roots(db)
    _assert_event_schema(db, roots.genesis.id)
    control = rows["control"][0]
    require(
        control["vault_id"] == roots.genesis.id
        and control["instance_id"] == profile.instance_id
        and control["origin_digest"] == profile.digest
        and len(anchors) <= control["slot_capacity"],
        "unavailable",
    )
    result = {}
    source_binding = _load_receipt_sources(domain, db, roots, profile, control, rows)
    commands = {r["command_id"]: r for r in rows["commands"]}
    for row in rows["requests"]:
        item = load(domain, db, roots, profile, control, row)
        item["history"] = sorted(
            (r for r in rows["lifecycle"] if r["request_id"] == row["request_id"]),
            key=lambda r: r["revision"],
        )
        heads = [r for r in rows["heads"] if r["request_id"] == row["request_id"]]
        require(len(heads) == 1, "unavailable")
        item["head"] = heads[0]
        item["outbox"] = {
            r["role"]: r for r in rows["outbox"] if r["request_id"] == row["request_id"]
        }
        receipt_rows = [
            r for r in rows.get("receipts", ()) if r["request_id"] == row["request_id"]
        ]
        consumption_rows = [
            r
            for r in rows.get("consumptions", ())
            if r["request_id"] == row["request_id"]
        ]
        item["receipt"] = (
            _load_receipt(
                domain, db, roots, profile, item, source_binding, receipt_rows[0]
            )
            if receipt_rows
            else None
        )
        item["consumption"] = (
            _load_consumption(
                domain, db, roots, item, item["receipt"], consumption_rows[0]
            )
            if consumption_rows
            else None
        )
        consumed = [
            r
            for r in rows.get("consumed_outbox", ())
            if item["consumption"] is not None
            and r["consumption_id"] == item["consumption"]["ref"].id
        ]
        item["consumed_outbox"] = consumed[0] if consumed else None
        installation_rows = [
            r
            for r in rows.get("installations", ())
            if r["request_id"] == row["request_id"]
        ]
        is_receipt = len(item["history"]) >= 2 and item["history"][1]["state"] in {
            "receipt_pending",
            "rejected",
        }
        rejected = is_receipt and item["history"][1]["state"] == "rejected"
        accepted = (
            len(item["history"]) == 3 and item["history"][2]["state"] == "accepted"
        )
        # journal v3 §4: accepted3 has exactly one success consumption and one
        # installation with its head and no consumed outbox; rejected2 keeps
        # its one v1 consumption with the marker intent; nothing else has any
        require(
            bool(receipt_rows) == is_receipt
            and bool(consumption_rows) == (rejected or accepted)
            and bool(consumed) == rejected
            and bool(installation_rows) == accepted,
            "unavailable",
        )
        item["installation"] = (
            _load_installation(
                domain,
                db,
                roots,
                profile,
                item,
                item["consumption"],
                installation_rows[0],
                rows.get("installation_heads", ()),
            )
            if installation_rows
            else None
        )
        if rejected:
            out = item["consumed_outbox"]
            payload = lifecycle.consumed_payload(item)
            require(
                out["payload_sha256"] == sha256(payload).hexdigest()
                and out["payload_size"] == len(payload),
                "unavailable",
            )
            if out["state"] == "published":
                require(
                    item["consumption"]["row"]["consumed_ms"]
                    <= out["published_ms"]
                    <= control["clock_floor_ms"],
                    "unavailable",
                )
        lifecycle.verify(db, roots, profile, item, commands)
        result[row["request_id"]] = item
    return {
        "control": control,
        "requests": result,
        "rows": rows,
        "receipt_sources": source_binding,
    }


def receipt_bindings(trust_raw, ingress_raw, consumption_raw, profile, control):
    """Shared historical/live byte relations; never a live-source authority object."""
    trust = parse_trust_set(trust_raw, profile=profile)
    claims = sources.parse(ingress_raw, cap=8192, depth=8, items=256)
    ingress = parse_ingress(
        ingress_raw,
        profile=profile,
        receipt_recipe_sha256=RECEIPT_RECIPE_SHA256,
        receipt_instance_sha256=claims["receipt_instance_digest"],
    )
    consumption = parse_consumption_exchange(
        consumption_raw,
        profile=profile,
        receipt_recipe_sha256=RECEIPT_RECIPE_SHA256,
        receipt_instance_sha256=ingress["receipt_instance_digest"],
    )
    require(
        ingress["trust_set_digest"]
        == consumption["trust_set_digest"]
        == sha256(trust_raw).hexdigest()
        and consumption["receipt_ingress_digest"] == sha256(ingress_raw).hexdigest()
        and ingress["outgoing_exchange_digest"]
        == consumption["outgoing_exchange_digest"]
        == control["exchange_sha256"]
        and len(
            {
                control["topology_id"],
                control["exchange_id"],
                ingress["ingress_id"],
                consumption["exchange_id"],
            }
        )
        == 4,
        "unavailable",
    )
    return trust, ingress, consumption


def _anchor_dimensions(db, kind):
    dimensions = list(
        db.execute(
            "SELECT typeof(vault_id),length(CAST(vault_id AS BLOB)),typeof(id),length(CAST(id AS BLOB)),typeof(version),typeof(sha256),length(CAST(sha256 AS BLOB)),typeof(body),length(body) FROM domain_records WHERE kind=? LIMIT 17",
            (kind,),
        )
    )
    require(
        len(dimensions) <= 16
        and all(
            row[0] == row[2] == row[5] == "text"
            and row[1] == row[3] == 36
            and row[4] == "integer"
            and row[6] == 64
            and row[7] == "blob"
            and 0 < row[8] <= 8192
            for row in dimensions
        ),
        "unavailable",
    )


def _bounded_blob(domain, db, roots, blob, cap):
    require(
        blob.vault_id == roots.genesis.id
        and blob.purpose == "operational"
        and 0 < blob.size <= cap,
        "unavailable",
    )
    scalar = db.execute(
        "SELECT typeof(size),CASE WHEN typeof(size)='integer' THEN size END FROM domain_blobs WHERE vault_id=? AND purpose=? AND sha256=? LIMIT 2",
        (blob.vault_id, blob.purpose, blob.sha256),
    ).fetchone()
    require(
        scalar is not None and scalar[0] == "integer" and scalar[1] == blob.size,
        "unavailable",
    )
    return domain._blob_bytes(db, blob, roots, purpose="operational")


def _load_receipt_sources(domain, db, roots, profile, control, rows):
    require(
        bool(rows.get("receipt_sources")) == bool(rows.get("receipts")), "unavailable"
    )
    if not rows.get("receipt_sources"):
        return None
    row = rows["receipt_sources"][0]
    names = ("trust", "ingress", "consumption_exchange")
    blobs = [
        BlobRef(
            row["vault_id"], row["purpose"], row[name + "_sha256"], row[name + "_size"]
        )
        for name in names
    ]
    raw = [
        _bounded_blob(domain, db, roots, blob, cap)
        for blob, cap in zip(blobs, (16384, 8192, 8192), strict=True)
    ]
    parsed = receipt_bindings(*raw, profile, control)
    identity = parse_canonical(row["identity_json"].encode())
    storage.validate_receipt_identity(identity)
    return {
        "row": row,
        "blobs": blobs,
        "raw": raw,
        "parsed": parsed,
        "identity": identity,
    }


def _load_receipt(domain, db, roots, profile, item, source_binding, row):
    require(source_binding is not None and len(item["history"]) >= 2, "unavailable")
    ref = EntityRef("deployment_receipt", row["request_id"], 1, row["anchor_digest"])
    bound_associations(db, roots.genesis.id, ref.kind, ref.id, 1, edges=4, blobs=4)
    record = bounded_body(db, roots.genesis.id, ref, 8192)
    anchor = record.body["content"]
    blobs = [
        BlobRef.from_dict(anchor[name + "_blob_ref"])
        for name in ("receipt", "trust", "ingress", "consumption_exchange")
    ]
    raw = [
        _bounded_blob(domain, db, roots, blob, cap)
        for blob, cap in zip(blobs, (16384, 16384, 8192, 8192), strict=True)
    ]
    require(
        blobs[1:] == source_binding["blobs"] and raw[1:] == source_binding["raw"],
        "unavailable",
    )
    domain._check_graph(db, [ref], roots)
    value = verify_receipt(
        raw[0],
        request_bytes=item["raw"],
        trust_bytes=raw[1],
        trust_sha256=blobs[1].sha256,
        profile=profile,
    )
    history = item["history"][1]
    ingress = source_binding["parsed"][1]
    require(
        ingress["prepare_recipe_digest"] == item["exchange"]["deployment_recipe_digest"]
        and ingress["prepare_instance_digest"]
        == item["exchange"]["instance_configuration_digest"],
        "unavailable",
    )
    require(
        record.body["actor_ref"] == item["actor"].as_dict()
        and record.body["access_policy_ref"] == roots.access_policy.as_dict()
        and record.body["retention_policy_ref"] == roots.retention_policy.as_dict()
        and record.body["created_at_utc"]
        == lifecycle.instant(history["transitioned_ms"])
        and anchor["request_ref"] == item["ref"].as_dict()
        and anchor["import_command_id"]
        == row["import_command_id"]
        == history["command_id"]
        and blobs[0].sha256 == row["receipt_sha256"]
        and blobs[0].size == row["receipt_size"]
        and value["outcome"] == row["outcome"]
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
        "raw": raw[0],
        "value": value,
        "digest": urlsafe_b64encode(bytes.fromhex(row["receipt_sha256"]))
        .decode()
        .rstrip("="),
    }


def _load_consumption(domain, db, roots, item, receipt, row):
    """The one-use consumption: v1 for a rejected2 non-success (revision 2),
    v2 for an accepted3 success (revision 3, the installation as effect; the
    effect itself is compared by `_load_installation`)."""
    accepted = len(item["history"]) == 3 and item["history"][2]["state"] == "accepted"
    require(
        receipt is not None
        and (
            receipt["value"]["outcome"] == "succeeded"
            if accepted
            else receipt["value"]["outcome"] in {"failed", "unknown"}
        )
        and row["lifecycle_revision"] == (3 if accepted else 2),
        "unavailable",
    )
    ref = EntityRef(
        "deployment_receipt_consumption", row["consumption_id"], 1, row["anchor_digest"]
    )
    bound_associations(
        db, roots.genesis.id, ref.kind, ref.id, 1, edges=6 if accepted else 5, blobs=0
    )
    record = bounded_body(db, roots.genesis.id, ref, 8192)
    domain._check_graph(db, [ref], roots)
    anchor, history = record.body["content"], item["history"][2 if accepted else 1]
    expected = {
        "schema_version": "deployment-receipt-consumption-anchor-v2"
        if accepted
        else "deployment-receipt-consumption-anchor-v1",
        "request_ref": item["ref"].as_dict(),
        "receipt_ref": receipt["ref"].as_dict(),
        "winning_lifecycle_revision": 3 if accepted else 2,
        "consumed_at": lifecycle.stamp(history["transitioned_ms"]),
        "actor_ref": item["actor"].as_dict(),
        "transaction_id": history["command_id"],
        "public_event_id": history["event_id"],
        "outcome": receipt["value"]["outcome"],
    }
    if accepted:
        expected["effect_ref"] = anchor.get("effect_ref")
    require(
        anchor == expected
        and row["command_id"] == history["command_id"]
        and row["event_id"] == history["event_id"]
        and row["consumed_ms"] == history["transitioned_ms"]
        and row["receipt_sha256"] == receipt["row"]["receipt_sha256"]
        and record.body["actor_ref"] == item["actor"].as_dict()
        and record.body["access_policy_ref"] == roots.access_policy.as_dict()
        and record.body["retention_policy_ref"] == roots.retention_policy.as_dict(),
        "unavailable",
    )
    return {"ref": ref, "record": record, "anchor": anchor, "row": row}


def _load_installation(domain, db, roots, profile, item, consumption, row, head_rows):
    """The accepted3 installation (journal v3 §4): anchor, evidence blob, head,
    the consume command/consumption linkage and the `extension.staged` event."""
    from ..domain.public_events import EventEnvelope
    from .stage_observer import StagePostconditionError, parse_stage_evidence

    history = item["history"]
    require(
        len(history) == 3
        and history[2]["state"] == "accepted"
        and consumption is not None
        and item["receipt"] is not None,
        "unavailable",
    )
    accepted = history[2]
    ref = EntityRef("extension_installation", row["installation_id"], 1, row["anchor_digest"])
    bound_associations(db, roots.genesis.id, ref.kind, ref.id, 1, edges=5, blobs=1)
    record = bounded_body(db, roots.genesis.id, ref, 8192)
    domain._check_graph(db, [ref], roots)
    anchor = record.body["content"]
    evidence = BlobRef(row["vault_id"], row["purpose"], row["evidence_sha256"], row["evidence_size"])
    raw = _bounded_blob(domain, db, roots, evidence, 8192)
    try:
        parsed = parse_stage_evidence(raw)
    except StagePostconditionError:
        raise DeploymentPrepareError("unavailable") from None
    request = item["request"]
    require(
        anchor == _installation_anchor(item, evidence, accepted["command_id"], accepted["transitioned_ms"])
        and _evidence_agrees(
            parsed,
            item,
            profile,
            item["receipt"],
            history[1]["transitioned_ms"],
            accepted["transitioned_ms"],
        )
        and row["request_id"] == item["ref"].id
        and row["extension_id"] == request["effect_payload"]["extension_id"]
        and row["vault_id"] == roots.genesis.id
        and row["consumption_id"] == consumption["ref"].id
        and row["command_id"] == accepted["command_id"]
        and row["installed_ms"] == accepted["transitioned_ms"]
        and consumption["anchor"]["effect_ref"] == ref.as_dict()
        and record.body["actor_ref"] == item["actor"].as_dict()
        and record.body["access_policy_ref"] == roots.access_policy.as_dict()
        and record.body["retention_policy_ref"] == roots.retention_policy.as_dict()
        and record.body["parent_refs"] == [item["ref"].as_dict(), item["receipt"]["ref"].as_dict()],
        "unavailable",
    )
    heads = [h for h in head_rows if h["request_id"] == item["ref"].id]
    require(
        len(heads) == 1
        and heads[0]["extension_id"] == row["extension_id"]
        and heads[0]["revision"] == 1
        and heads[0]["installation_anchor_digest"] == row["anchor_digest"],
        "unavailable",
    )
    event_row = db.execute(
        "SELECT * FROM api_event_envelopes WHERE event_id=? LIMIT 2", (row["event_id"],)
    ).fetchone()
    accepted_sequence = db.execute(
        "SELECT sequence FROM api_event_envelopes WHERE event_id=? LIMIT 2",
        (accepted["event_id"],),
    ).fetchone()
    require(
        event_row is not None
        and event_row["event_type"] == "extension.staged"
        and event_row["vault_id"] == roots.genesis.id
        and len(event_row["envelope"]) <= 8192
        # appended in the one writer right after the acceptance event
        and accepted_sequence is not None
        and event_row["sequence"] == accepted_sequence[0] + 1,
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
        "head": heads[0],
        "evidence": parsed,
        "evidence_blob": evidence,
    }


def _evidence_agrees(parsed, item, profile, receipt, observed_after_ms, observed_before_ms):
    """The parsed evidence describes this request, this receipt and the admitted
    slot (journal v3 §4: `service_identity`, `uid`, `gid` and the channel come
    from `contracts.slot`, never from the blob alone), observed inside the
    receipt-import → acceptance window. The build/schema digests are compared
    with the candidate lineage by the service (e2b)."""
    request = item["request"]
    present = receipt["value"]["effect_result"]["new_service"]
    try:
        slot = sources.slot(profile.instance_id, item["row"]["slot_id"])
        observed_ms = epoch_ms(parsed["observed_at"])
    except (sources.DeploymentSourceError, DeploymentPrepareError):
        return False
    expected = parsed["expected"]
    return (
        parsed["request_id"] == item["ref"].id
        and parsed["request_digest"] == request["request_digest"]
        and parsed["receipt_digest"] == receipt["digest"]
        and parsed["request_blob_sha256"] == sha256(item["raw"]).hexdigest()
        and parsed["receipt_blob_sha256"] == receipt["row"]["receipt_sha256"]
        and expected["service_identity"] == present["service_identity"]
        and expected["service_identity"] == slot["service_identity"]
        and expected["uid"] == slot["uid"]
        and expected["gid"] == slot["gid"]
        and parsed["connection"]["channel_id"] == slot["channel_id"]
        and expected["platform"]
        == request["effect_payload"]["selected_platform_entry"]["platform"]
        and observed_after_ms <= observed_ms <= observed_before_ms
    )


def _installation_anchor(item, evidence, command_id, installed_ms):
    """The exact `extension-installation-anchor-v1` content of an acceptance,
    derived from the retained request and the receipt's Present result only."""
    request = item["request"]
    payload = request["effect_payload"]
    present = item["receipt"]["value"]["effect_result"]["new_service"]
    return {
        "schema_version": "extension-installation-anchor-v1",
        "extension_id": payload["extension_id"],
        "manifest_digest": present["manifest_digest"],
        "service_descriptor_digest": present["service_descriptor_digest"],
        "selected_platform_entry_digest": present["selected_platform_entry_digest"],
        "image_manifest_digest": present["image_manifest_digest"],
        "platform": payload["selected_platform_entry"]["platform"],
        "service_identity": present["service_identity"],
        "staging_authority": "deployment-receipt-v1",
        "request_ref": item["ref"].as_dict(),
        "receipt_ref": item["receipt"]["ref"].as_dict(),
        "postcondition_evidence_blob_ref": evidence.as_dict(),
        "consume_command_id": command_id,
        "state": "staged",
        "revision": 1,
        "previous_record_digest": None,
        "installed_at": lifecycle.stamp(installed_ms),
        "actor_ref": item["actor"].as_dict(),
    }


def accept_stage(domain, db, roots, profile, item, *, now, actor_ref, value, evidence,
                 evidence_bytes):
    """The final-writer body of the consume transaction (journal v3 §5): a
    receipt_pending2 request with a succeeded receipt and a presealed
    postcondition evidence blob becomes accepted3 with its installation
    anchor and absent-only head, the acceptance and staged events, the
    success consumption anchor v2 and the index rows, in this one writer.
    Everything is derived from retained records and the evidence; the caller
    owns admission, expiry precedence, the observation and the rechecks."""
    from uuid import uuid4

    from ..domain.schemas import ImmutableRecord
    from .prepare_v3_contracts import parse_consume
    from .stage_observer import StagePostconditionError, parse_stage_evidence

    domain._assert_write_transaction(db)
    history = item["history"]
    receipt = item.get("receipt")
    require(
        type(value) is dict
        and parse_consume(
            item["ref"].id, {k: v for k, v in value.items() if k != "request_id"}
        )
        == value,
        "conflict",
    )
    require(
        len(history) == 2
        and history[1]["state"] == "receipt_pending"
        and item["head"]["revision"] == 2
        and receipt is not None
        and receipt["value"]["outcome"] == "succeeded"
        and value["expected_revision"] == 2
        and value["request_digest"] == item["request"]["request_digest"]
        and value["receipt_digest"] == receipt["digest"]
        # the final-writer time precondition: never at or after the deadline
        # (the caller's expiry precedence owns that transition) and never
        # before the receipt import this acceptance consumes
        and type(now) is int
        and history[1]["transitioned_ms"] <= now < item["row"]["expires_ms"],
        "conflict",
    )
    require(
        db.execute(
            "SELECT 1 FROM domain_records WHERE kind IN ('extension_installation','extension_qualification','extension_binding') LIMIT 1"
        ).fetchone()
        is None,
        "conflict",
    )
    require(
        type(evidence) is BlobRef
        and type(evidence_bytes) is bytes
        and evidence.vault_id == roots.genesis.id
        and evidence.purpose == "operational"
        and evidence.sha256 == sha256(evidence_bytes).hexdigest()
        and evidence.size == len(evidence_bytes)
        and _bounded_blob(domain, db, roots, evidence, 8192) == evidence_bytes,
        "conflict",
    )
    try:
        parsed = parse_stage_evidence(evidence_bytes)
    except StagePostconditionError:
        raise DeploymentPrepareError("conflict") from None
    require(
        _evidence_agrees(parsed, item, profile, receipt, history[1]["transitioned_ms"], now),
        "conflict",
    )
    common = {
        "version": 1,
        "created_at_utc": lifecycle.instant(now),
        "actor_ref": actor_ref,
        "purpose": "operational",
        "access_policy_ref": roots.access_policy,
        "retention_policy_ref": roots.retention_policy,
    }
    anchor = _installation_anchor(item, evidence, value["command_id"], now)
    installation_record = ImmutableRecord.create(
        kind="extension_installation",
        id=str(uuid4()),
        parent_refs=(item["ref"], receipt["ref"]),
        content=anchor,
        **common,
    )
    domain._put_in_transaction(db, installation_record)
    installation = {"ref": installation_record.ref, "anchor": anchor}
    reply, accepted_event = lifecycle.commit_acceptance_transition(
        db,
        roots,
        profile,
        item,
        now=now,
        actor_ref=actor_ref,
        value=value,
        installation=installation,
    )
    staged = lifecycle.append_staged_event(
        db,
        roots,
        item,
        now=now,
        actor_ref=actor_ref,
        installation_ref=installation_record.ref,
        correlation_id=value["command_id"],
        causation_id=accepted_event.event_id,
    )
    content = {
        "schema_version": "deployment-receipt-consumption-anchor-v2",
        "request_ref": item["ref"].as_dict(),
        "receipt_ref": receipt["ref"].as_dict(),
        "winning_lifecycle_revision": 3,
        "consumed_at": lifecycle.stamp(now),
        "actor_ref": actor_ref.as_dict(),
        "transaction_id": value["command_id"],
        "public_event_id": accepted_event.event_id,
        "outcome": "succeeded",
        "effect_ref": installation_record.ref.as_dict(),
    }
    consumption = ImmutableRecord.create(
        kind="deployment_receipt_consumption",
        id=str(uuid4()),
        parent_refs=(item["ref"], receipt["ref"], installation_record.ref),
        content=content,
        **common,
    )
    domain._put_in_transaction(db, consumption)
    consumption_row = storage.insert(
        db,
        "consumptions",
        {
            "request_id": item["ref"].id,
            "receipt_sha256": receipt["row"]["receipt_sha256"],
            "consumption_id": consumption.ref.id,
            "vault_id": roots.genesis.id,
            "kind": "deployment_receipt_consumption",
            "version": 1,
            "anchor_digest": consumption.ref.sha256,
            "lifecycle_revision": 3,
            "command_id": value["command_id"],
            "event_id": accepted_event.event_id,
            "consumed_ms": now,
        },
    )
    installation_row = storage.insert(
        db,
        "installations",
        {
            "request_id": item["ref"].id,
            "extension_id": anchor["extension_id"],
            "vault_id": roots.genesis.id,
            "purpose": "operational",
            "kind": "extension_installation",
            "installation_id": installation_record.ref.id,
            "version": 1,
            "anchor_digest": installation_record.ref.sha256,
            "evidence_sha256": evidence.sha256,
            "evidence_size": evidence.size,
            "consumption_id": consumption.ref.id,
            "lifecycle_revision": 3,
            "command_id": value["command_id"],
            "event_id": staged.event_id,
            "installed_ms": now,
        },
    )
    head_row = storage.insert(
        db,
        "installation_heads",
        {
            "extension_id": anchor["extension_id"],
            "request_id": item["ref"].id,
            "revision": 1,
            "installation_anchor_digest": installation_record.ref.sha256,
        },
    )
    item["consumption"] = {"ref": consumption.ref, "anchor": content, "row": consumption_row}
    item["consumed_outbox"] = None
    item["installation"] = {
        **installation,
        "record": installation_record,
        "row": installation_row,
        "head": head_row,
        "evidence": parsed,
        "evidence_blob": evidence,
    }
    return reply


def bounded_candidates(domain, db):
    """Preflight reached collections before inherited candidate materialization."""
    root_row = db.execute(
        "SELECT vault_id,typeof(roots),length(roots) FROM domain_vault LIMIT 2"
    ).fetchone()
    require(
        root_row is not None and root_row[1] == "blob" and root_row[2] <= 8192,
        "unavailable",
    )
    vault = root_row[0]
    root_map = parse_canonical(
        db.execute("SELECT roots FROM domain_vault LIMIT 2").fetchone()[0]
    )
    require(
        set(root_map) == {"genesis", "actor", "access_policy", "retention_policy"},
        "unavailable",
    )
    for value in root_map.values():
        ref = EntityRef.from_dict(value)
        bound_associations(db, vault, ref.kind, ref.id, ref.version, edges=1, blobs=0)
        bounded_body(db, vault, ref, 8192)
    indices = None
    for table, cap in (
        ("index", 1024),
        ("commands", 1024),
        ("contents", 35840),
        ("control", 1),
        ("migrations", 1),
    ):
        values = list(
            db.execute(
                "SELECT rowid FROM extension_candidate_" + table + " LIMIT ?",
                (cap + 1,),
            )
        )
        require(len(values) <= cap, "unavailable")
        # Closed candidate JSON fields are bounded by the actual input/receipt schemas.
        integer_columns = {
            "singleton",
            "candidate_count",
            "content_bytes",
            "revision",
            "version",
            "size",
            "event_sequence",
        }
        columns = sorted(candidate_storage.COLUMNS[table] - integer_columns)
        lengths = list(
            db.execute(
                "SELECT "
                + ",".join("length(CAST(" + name + " AS BLOB))" for name in columns)
                + " FROM extension_candidate_"
                + table
                + " LIMIT ?",
                (cap + 1,),
            )
        )
        for row in lengths:
            require(
                all(
                    type(size) is int
                    and size
                    <= (8192 if name in {"receipt", "document_order"} else 1024)
                    for name, size in zip(columns, row, strict=True)
                ),
                "unavailable",
            )
        if table == "index":
            indices = list(
                db.execute(
                    "SELECT candidate_id,anchor_digest FROM extension_candidate_index LIMIT 1025"
                )
            )
    for row in indices:
        ref = EntityRef("extension_manifest", row[0], 1, row[1])
        bound_associations(db, vault, ref.kind, ref.id, 1, edges=3, blobs=35)
        body = bounded_body(db, vault, ref, 65536).body
        require(
            body["parent_refs"] == []
            and body["access_policy_ref"] == root_map["access_policy"]
            and body["retention_policy_ref"] == root_map["retention_policy"],
            "unavailable",
        )
        actor = EntityRef.from_dict(body["actor_ref"])
        bound_associations(
            db, vault, actor.kind, actor.id, actor.version, edges=3, blobs=0
        )
        actor_body = bounded_body(db, vault, actor, 8192).body
        require(
            actor_body["parent_refs"] == []
            and actor_body["actor_ref"] == root_map["actor"]
            and actor_body["access_policy_ref"] == root_map["access_policy"]
            and actor_body["retention_policy_ref"] == root_map["retention_policy"]
            and actor_body["content"]
            == {"id": actor.id, "kind": "human", "origin": "local_session"},
            "unavailable",
        )


def bounded_body(db, vault, ref, cap):
    params = (vault, ref.kind, ref.id, ref.version)
    size = db.execute(
        "SELECT typeof(body),length(body) FROM domain_records "
        "WHERE vault_id=? AND kind=? AND id=? AND version=? LIMIT 2",
        params,
    ).fetchone()
    require(
        size is not None and size[0] == "blob" and 0 < size[1] <= cap, "unavailable"
    )
    raw = db.execute(
        "SELECT body FROM domain_records WHERE vault_id=? AND kind=? AND id=? AND version=? LIMIT 2",
        params,
    ).fetchone()[0]
    return ImmutableRecord.from_bytes(raw, expected_ref=ref)


def private_sizes(db):
    """Observe exact layout and scalar caps before any full private-row load."""
    storage._layout(db)


def bound_associations(db, vault, kind, identity, version, *, edges, blobs):
    for table, cap in (("domain_edges", edges), ("domain_record_blobs", blobs)):
        columns = (
            (
                ("target_kind", str, 128),
                ("target_id", str, 36),
                ("target_version", int, 0),
                ("target_sha256", str, 64),
            )
            if table == "domain_edges"
            else (("purpose", str, 32), ("sha256", str, 64), ("size", int, 0))
        )
        dimensions = list(
            db.execute(
                "SELECT "
                + ",".join(
                    expression
                    for name, _, _ in columns
                    for expression in (
                        "typeof(" + name + ")",
                        "length(CAST(" + name + " AS BLOB))",
                    )
                )
                + " FROM "
                + table
                + " WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=? LIMIT ?",
                (vault, kind, identity, version, cap + 1),
            )
        )
        require(
            len(dimensions) <= cap
            and all(
                all(
                    row[index * 2] == "integer"
                    if expected is int
                    else row[index * 2] == "text" and row[index * 2 + 1] <= limit
                    for index, (_, expected, limit) in enumerate(columns)
                )
                for row in dimensions
            ),
            "unavailable",
        )


def retained_sources(topology_raw, exchange_raw, profile):
    topology_claims = sources.parse(topology_raw, cap=65536, depth=12, items=2048)
    exchange_claims = sources.parse(exchange_raw, cap=8192, depth=8, items=256)
    recipe = sources.digest(sources.encode(sources.RECIPE))
    topology = sources.parse_topology(
        topology_raw,
        profile=profile,
        recipe_sha256=recipe,
        platform=topology_claims["platform"],
    )
    instance_hash = sources.hex_digest(exchange_claims["instance_configuration_digest"])
    exchange = sources.parse_exchange(
        exchange_raw,
        profile=profile,
        recipe_sha256=recipe,
        instance_sha256=instance_hash,
    )
    require(topology["topology_id"] != exchange["exchange_id"], "unavailable")
    return topology, exchange


def candidate(domain, db, candidate_id):
    row = db.execute(
        "SELECT * FROM extension_candidate_index WHERE candidate_id=? LIMIT 2",
        (candidate_id,),
    ).fetchone()
    require(row is not None, "not_found")
    value, _ = load_candidate(domain, db, row)
    bundle = parse_bundle(
        {
            key: value[key]
            for key in ("command_id", "manifest", "service_descriptor", "documents")
        }
    )
    return bundle, EntityRef(
        "extension_manifest", candidate_id, 1, row["anchor_digest"]
    )


def load(domain, db, roots, profile, control, row):
    ref = EntityRef("deployment_request", row["request_id"], 1, row["anchor_digest"])
    sizes = db.execute(
        "SELECT typeof(body),length(body) FROM domain_records WHERE vault_id=? "
        "AND kind=? AND id=? AND version=? LIMIT 2",
        (roots.genesis.id, ref.kind, ref.id, 1),
    ).fetchone()
    require(
        sizes is not None and sizes[0] == "blob" and 0 < sizes[1] <= 8192, "unavailable"
    )
    bound_associations(db, roots.genesis.id, ref.kind, ref.id, 1, edges=4, blobs=3)
    record = domain._load(db, ref, roots)[0]
    anchor, body = record.body["content"], record.body
    actor = EntityRef.from_dict(body["actor_ref"])
    bound_associations(
        db, roots.genesis.id, actor.kind, actor.id, actor.version, edges=3, blobs=0
    )
    for root in (
        roots.genesis,
        roots.actor,
        roots.access_policy,
        roots.retention_policy,
    ):
        bound_associations(
            db, roots.genesis.id, root.kind, root.id, root.version, edges=1, blobs=0
        )
    blobs = [
        BlobRef.from_dict(anchor[name + "_blob_ref"])
        for name in ("request", "topology", "exchange")
    ]
    require(
        all(
            b.vault_id == roots.genesis.id and b.purpose == "operational" for b in blobs
        )
        and all(
            0 < b.size <= cap
            for b, cap in zip(blobs, (65536, 65536, 8192), strict=True)
        ),
        "unavailable",
    )
    bundle, candidate_ref = candidate(domain, db, anchor["candidate_ref"]["id"])
    account = db.execute(
        "SELECT actor_ref FROM owner_auth_accounts WHERE owner_id=? LIMIT 2",
        (actor.id,),
    ).fetchone()
    require(
        account is not None
        and account[0] == storage.encoded(actor.as_dict())
        and body["access_policy_ref"] == roots.access_policy.as_dict()
        and body["retention_policy_ref"] == roots.retention_policy.as_dict()
        and anchor["candidate_ref"] == candidate_ref.as_dict(),
        "unavailable",
    )
    domain._check_graph(db, [ref], roots)
    raw, topology_raw, exchange_raw = [
        domain._blob_bytes(db, b, roots, purpose="operational") for b in blobs
    ]
    request = parse_request(raw, profile=profile)
    topology, exchange = retained_sources(topology_raw, exchange_raw, profile)
    require(row["slot_id"] <= len(topology["slots"]), "unavailable")
    actor_record = domain._load(db, actor, roots)[0]
    require(
        account is not None
        and account[0] == storage.encoded(actor.as_dict())
        and actor_record.body["content"]
        == {"id": actor.id, "kind": "human", "origin": "local_session"},
        "unavailable",
    )
    require(
        anchor["candidate_ref"] == candidate_ref.as_dict()
        and body["parent_refs"] == [candidate_ref.as_dict()]
        and body["purpose"] == "operational"
        and body["access_policy_ref"] == roots.access_policy.as_dict()
        and body["retention_policy_ref"] == roots.retention_policy.as_dict()
        and body["created_at_utc"] == lifecycle.instant(row["created_ms"])
        and request["created_by"] == actor.as_dict()
        and request["request_id"] == ref.id
        and request["request_digest"] == row["request_digest"]
        and urlsafe_b64decode(request["request_nonce"] + "=").hex() == row["nonce_hex"]
        and epoch_ms(request["created_at"]) == row["created_ms"]
        and epoch_ms(request["expires_at"]) == row["expires_ms"]
        and request["effect_payload"]
        == stage_for_candidate(bundle, topology, topology["slots"][row["slot_id"] - 1])
        and request["effect_payload"]["extension_id"] == row["extension_id"]
        and anchor["slot_id"] == row["slot_id"]
        and anchor["reservation_revision"] == row["reservation_revision"]
        and anchor["topology_id"]
        == row["topology_id"]
        == control["topology_id"]
        == topology["topology_id"]
        and anchor["topology_revision"]
        == control["topology_revision"]
        == topology["revision"]
        and control["slot_capacity"] == len(topology["slots"])
        and control["exchange_id"] == exchange["exchange_id"]
        and control["exchange_revision"] == exchange["revision"],
        "unavailable",
    )
    for name, blob in zip(("topology", "exchange"), blobs[1:], strict=True):
        require(
            all(
                control[name + "_" + field] == getattr(blob, field)
                for field in ("purpose", "sha256", "size")
            ),
            "unavailable",
        )
    return {
        "ref": ref,
        "row": row,
        "anchor": anchor,
        "actor": actor,
        "request": request,
        "raw": raw,
        "topology_raw": topology_raw,
        "exchange_raw": exchange_raw,
        "topology": topology,
        "exchange": exchange,
        "control": control,
    }
