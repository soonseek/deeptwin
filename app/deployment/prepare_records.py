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
                "SELECT 1 FROM domain_records WHERE kind IN ('deployment_request','deployment_receipt','deployment_receipt_consumption') LIMIT 1"
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
    require(db.execute("PRAGMA foreign_key_check").fetchone() is None, "unavailable")
    return journal


def verify(domain, db, profile):
    private_sizes(db)
    rows = storage.verify(db)
    for kind in (
        "deployment_request",
        "deployment_receipt",
        "deployment_receipt_consumption",
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
            "('deployment.request_prepared','deployment.request_cancelled','deployment.request_expired','deployment.receipt_committed') LIMIT 49"
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
        is_receipt = len(item["history"]) >= 2 and item["history"][1]["state"] in {
            "receipt_pending",
            "rejected",
        }
        rejected = is_receipt and item["history"][1]["state"] == "rejected"
        require(
            bool(receipt_rows) == is_receipt
            and bool(consumption_rows) == rejected
            and bool(consumed) == rejected,
            "unavailable",
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
    require(
        receipt is not None and receipt["value"]["outcome"] in {"failed", "unknown"},
        "unavailable",
    )
    ref = EntityRef(
        "deployment_receipt_consumption", row["consumption_id"], 1, row["anchor_digest"]
    )
    bound_associations(db, roots.genesis.id, ref.kind, ref.id, 1, edges=5, blobs=0)
    record = bounded_body(db, roots.genesis.id, ref, 8192)
    domain._check_graph(db, [ref], roots)
    anchor, history = record.body["content"], item["history"][1]
    require(
        anchor
        == {
            "schema_version": "deployment-receipt-consumption-anchor-v1",
            "request_ref": item["ref"].as_dict(),
            "receipt_ref": receipt["ref"].as_dict(),
            "winning_lifecycle_revision": 2,
            "consumed_at": lifecycle.stamp(history["transitioned_ms"]),
            "actor_ref": item["actor"].as_dict(),
            "transaction_id": history["command_id"],
            "public_event_id": history["event_id"],
            "outcome": receipt["value"]["outcome"],
        }
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
