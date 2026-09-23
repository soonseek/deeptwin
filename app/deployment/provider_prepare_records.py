"""Transaction-local provider context, CAS, anchor and frozen inventory joins."""

from base64 import urlsafe_b64decode
from functools import cache
from hashlib import sha256

from ..domain.refs import EntityRef, canonical_json, parse_canonical
from ..domain.store import BlobRef
from ..extensions.port_schema_generator import (
    canonical_schema_bytes,
    generate_port_schemas,
)
from . import prepare_lifecycle as lifecycle
from . import prepare_records as legacy
from . import prepare_storage as storage
from .prepare_contracts import epoch_ms, require
from .provider_prepare_contracts import (
    parse_provider_inventory,
    parse_provider_request,
    validate_provider_request_sources,
)
from .provider_source_contracts import (
    BUNDLE_LAYOUT,
    parse_provider_context,
    validate_provider_source_bundle,
)


@cache
def _provider_schema_bytes():
    # Immutable bytes of the code-owned generator; one deep copy per process.
    schemas = generate_port_schemas()
    return tuple(
        canonical_schema_bytes(schemas[("provider-port-v1", role)])
        for role in ("config", "request", "result", "error")
    )


def load_context(domain, db, roots, profile, control, rows):
    contexts = rows.get("provider_contexts", ())
    docs = rows.get("provider_context_documents", ())
    requests = rows.get("provider_requests", ())
    require(bool(contexts) == bool(requests) and len(contexts) <= 1, "unavailable")
    if not contexts:
        require(not docs, "unavailable")
        return None
    row = contexts[0]
    require(
        len(docs) == 18
        and row["vault_id"] == roots.genesis.id
        and row["topology_id"] == control["topology_id"],
        "unavailable",
    )
    ordered = sorted(docs, key=lambda item: item["ordinal"])
    files, refs = [], []
    for ordinal, (doc, (name, cap)) in enumerate(
        zip(ordered, BUNDLE_LAYOUT, strict=True), 1
    ):
        require(
            doc["ordinal"] == ordinal
            and doc["name"] == name
            and doc["context_id"] == row["context_id"]
            and doc["vault_id"] == roots.genesis.id,
            "unavailable",
        )
        blob = BlobRef(doc["vault_id"], doc["purpose"], doc["sha256"], doc["size"])
        files.append((name, legacy._bounded_blob(domain, db, roots, blob, cap)))
        refs.append({"name": name, "blob_ref": blob.as_dict()})
    files = tuple(files)
    validate_provider_source_bundle(files)
    value = parse_provider_context(files[16][1])
    require(
        row["context_id"] == value["context_id"]
        and row["epoch"] == value["epoch"]
        and row["worker_profile"] == value["worker_profile"]
        and row["purpose"] == "operational"
        and row["context_sha256"] == sha256(files[16][1]).hexdigest()
        and row["context_size"] == len(files[16][1])
        and value["instance_id"] == profile.instance_id
        and value["origin_profile_digest"] == profile.digest
        and value["topology_id"] == control["topology_id"],
        "unavailable",
    )
    topology, exchange = legacy.retained_sources(files[2][1], files[3][1], profile)
    require(
        control["topology_id"] == topology["topology_id"]
        and control["topology_revision"] == topology["revision"]
        and control["slot_capacity"] == len(topology["slots"])
        and control["exchange_id"] == exchange["exchange_id"]
        and control["exchange_revision"] == exchange["revision"],
        "unavailable",
    )
    for prefix, index in (("topology", 2), ("exchange", 3)):
        require(
            control[prefix + "_purpose"] == "operational"
            and control[prefix + "_sha256"] == refs[index]["blob_ref"]["sha256"]
            and control[prefix + "_size"] == refs[index]["blob_ref"]["size"],
            "unavailable",
        )
    for binding in rows.get("receipt_sources", ()):
        for prefix, index in (
            ("trust", 6),
            ("ingress", 7),
            ("consumption_exchange", 8),
        ):
            require(
                binding[prefix + "_sha256"] == refs[index]["blob_ref"]["sha256"]
                and binding[prefix + "_size"] == refs[index]["blob_ref"]["size"],
                "unavailable",
            )
    require(
        all(
            item["context_id"] == row["context_id"]
            and item["vault_id"] == roots.genesis.id
            for item in requests
        ),
        "unavailable",
    )
    return {
        "row": row,
        "files": files,
        "refs": refs,
        "value": value,
        "topology": topology,
        "exchange": exchange,
    }


def load(domain, db, roots, profile, control, row, *, context, provider_row):
    require(
        context is not None
        and provider_row is not None
        and row["vault_id"] == roots.genesis.id
        and provider_row["vault_id"] == roots.genesis.id,
        "unavailable",
    )
    ref = EntityRef("deployment_request", row["request_id"], 1, row["anchor_digest"])
    legacy.bound_associations(
        db, roots.genesis.id, ref.kind, ref.id, 1, edges=4, blobs=20
    )
    record = domain._load(db, ref, roots)[0]
    body, anchor = record.body, record.body["content"]
    actor = EntityRef.from_dict(body["actor_ref"])
    legacy.bound_associations(
        db, roots.genesis.id, actor.kind, actor.id, actor.version, edges=3, blobs=0
    )
    bundle, candidate_ref = legacy.candidate(domain, db, anchor["candidate_ref"]["id"])
    blob = BlobRef.from_dict(anchor["request_blob_ref"])
    inventory_blob = BlobRef.from_dict(anchor["preserved_inventory_blob_ref"])
    raw = legacy._bounded_blob(domain, db, roots, blob, 65536)
    inventory_raw = legacy._bounded_blob(domain, db, roots, inventory_blob, 16384)
    require(
        anchor["source_documents"] == context["refs"]
        and inventory_blob.vault_id == blob.vault_id == roots.genesis.id
        and provider_row["context_id"] == context["row"]["context_id"]
        and provider_row["request_id"] == ref.id
        and inventory_blob.purpose == provider_row["purpose"]
        and inventory_blob.sha256 == provider_row["inventory_sha256"]
        and inventory_blob.size == provider_row["inventory_size"],
        "unavailable",
    )
    validate_provider_request_sources(
        raw,
        candidate_bundle=bundle,
        source_bundle_files=context["files"],
        provider_schema_bytes=_provider_schema_bytes(),
        inventory_bytes=inventory_raw,
        profile=profile,
    )
    request = parse_provider_request(raw, profile=profile)
    inventory_value = parse_provider_inventory(inventory_raw)
    account = db.execute(
        "SELECT actor_ref FROM owner_auth_accounts WHERE owner_id=? LIMIT 2",
        (actor.id,),
    ).fetchone()
    domain._check_graph(db, [ref], roots)
    actor_record = domain._load(db, actor, roots)[0]
    require(
        account is not None
        and account[0] == storage.encoded(actor.as_dict())
        and actor_record.body["content"]
        == {"id": actor.id, "kind": "human", "origin": "local_session"}
        and body["parent_refs"] == [candidate_ref.as_dict()]
        and anchor["candidate_ref"] == candidate_ref.as_dict()
        and body["purpose"] == "operational"
        and body["access_policy_ref"] == roots.access_policy.as_dict()
        and body["retention_policy_ref"] == roots.retention_policy.as_dict()
        and body["created_at_utc"] == lifecycle.instant(row["created_ms"])
        and request["created_by"] == actor.as_dict()
        and request["request_id"] == ref.id == anchor["request_id"]
        and request["request_digest"] == row["request_digest"]
        and urlsafe_b64decode(request["request_nonce"] + "=").hex() == row["nonce_hex"]
        and epoch_ms(request["created_at"]) == row["created_ms"]
        and epoch_ms(request["expires_at"]) == row["expires_ms"]
        and request["effect_payload"]["extension_id"] == row["extension_id"]
        and anchor["topology_id"] == row["topology_id"] == control["topology_id"]
        and anchor["topology_revision"] == control["topology_revision"] == 1
        and anchor["slot_id"] == row["slot_id"]
        and anchor["reservation_revision"] == row["reservation_revision"] == 1
        and bundle.descriptor.as_dict()["service_identity"]
        == context["topology"]["slots"][row["slot_id"] - 1]["service_identity"]
        and inventory_value["vault_id"] == roots.genesis.id
        and inventory_value["at_event_sequence"] == provider_row["at_event_sequence"],
        "unavailable",
    )
    return {
        "ref": ref,
        "row": row,
        "anchor": anchor,
        "actor": actor,
        "request": request,
        "raw": raw,
        "control": control,
        "context": context,
        "provider_row": provider_row,
        "inventory_raw": inventory_raw,
        "topology": context["topology"],
        "exchange": context["exchange"],
        "topology_raw": context["files"][2][1],
        "exchange_raw": context["files"][3][1],
    }


def inventory(
    domain, db, roots, profile, journal, *, source_bundle_files, at_event_sequence
):
    stream = db.execute(
        "SELECT next_sequence FROM api_event_streams WHERE vault_id=?",
        (roots.genesis.id,),
    ).fetchone()
    require(
        stream is not None
        and type(at_event_sequence) is int
        and 0 <= at_event_sequence < stream[0] <= 2**40 + 1,
        "unavailable",
    )
    entries = []
    for item in journal["requests"].values():
        installed = item.get("installation")
        if installed is None:
            continue
        staged = db.execute(
            "SELECT sequence FROM api_event_envelopes WHERE event_id=?",
            (installed["row"]["event_id"],),
        ).fetchone()
        accepted = db.execute(
            "SELECT sequence FROM api_event_envelopes WHERE event_id=?",
            (item["history"][2]["event_id"],),
        ).fetchone()
        require(
            staged is not None and accepted is not None and accepted[0] < staged[0],
            "unavailable",
        )
        if staged[0] > at_event_sequence:
            continue
        require(
            item["anchor"]["schema_version"] == "deployment-request-anchor-v1",
            "unavailable",
        )
        entries.append(
            {
                "installation_ref": installed["ref"].as_dict(),
                "extension_id": installed["row"]["extension_id"],
                "request_ref": item["ref"].as_dict(),
                "head_revision": 1,
                "head_digest": installed["head"]["hash"],
                "slot_id": item["row"]["slot_id"],
                "service_identity": item["request"]["effect_payload"][
                    "new_service_effect"
                ]["service_identity"],
                "accepted_event_id": item["history"][2]["event_id"],
                "staged_event_id": installed["row"]["event_id"],
            }
        )
    topology = parse_canonical(source_bundle_files[2][1])
    value = {
        "schema_version": "deployment-provider-preserved-inventory-v1",
        "vault_id": roots.genesis.id,
        "instance_id": profile.instance_id,
        "origin_profile_digest": profile.digest,
        "topology_id": topology["topology_id"],
        "topology_sha256": sha256(source_bundle_files[2][1]).hexdigest(),
        "at_event_sequence": at_event_sequence,
        "installations": sorted(
            entries, key=lambda e: (e["extension_id"], e["installation_ref"]["id"])
        ),
    }
    raw = canonical_json(value)
    parse_provider_inventory(raw)
    return raw


def verify_inventories(domain, db, roots, profile, journal):
    for item in journal["requests"].values():
        if "provider_row" not in item:
            continue
        sequence = item["provider_row"]["at_event_sequence"]
        prepared = db.execute(
            "SELECT sequence FROM api_event_envelopes WHERE event_id=?",
            (item["history"][0]["event_id"],),
        ).fetchone()
        require(prepared is not None and sequence < prepared[0], "unavailable")
        require(
            inventory(
                domain,
                db,
                roots,
                profile,
                journal,
                source_bundle_files=item["context"]["files"],
                at_event_sequence=sequence,
            )
            == item["inventory_raw"],
            "unavailable",
        )
