"""Verify candidate records against their actual domain blobs, index and journal."""

import json
from datetime import datetime
from hashlib import sha256

from jsonschema import Draft202012Validator

from ..domain.public_events import (
    EventEnvelope,
    _decode_cursor,
    _encode_cursor,
    _event_cursor_in_transaction,
)
from ..domain.refs import EntityRef, canonical_json, parse_canonical
from ..domain.store import BlobRef
from .candidate_contracts import CandidateError, metadata_ref, parse_bundle
from .candidate_schema_exports import anchor_schema, registration_schema


def encoded(value):
    return canonical_json(value).decode()


def load_candidate(domain, db, row):
    roots = domain._read_roots(db)
    if row["vault_id"] != roots.genesis.id:
        raise CandidateError("unavailable")
    ref = EntityRef("extension_manifest", row["candidate_id"], 1, row["anchor_digest"])
    record = domain._load(db, ref, roots)[0]
    domain._check_graph(db, [ref], roots)
    body = record.body
    anchor = body["content"]
    if not Draft202012Validator(anchor_schema()).is_valid(anchor):
        raise CandidateError("unavailable")
    blobs = []

    def load(value):
        blob = BlobRef.from_dict(value)
        if blob.vault_id != roots.genesis.id or blob.purpose != "operational":
            raise CandidateError("unavailable")
        blobs.append(blob)
        return domain._blob_bytes(db, blob, roots, purpose="operational")

    manifest = parse_canonical(load(anchor["manifest_blob_ref"]))
    descriptor = parse_canonical(load(anchor["service_descriptor_blob_ref"]))
    registration_raw = load(anchor["registration_blob_ref"])
    registration = parse_canonical(registration_raw)
    if not Draft202012Validator(registration_schema()).is_valid(registration):
        raise CandidateError("unavailable")
    leaves = {}
    refs = []
    for support in anchor["support_documents"]:
        kind = support["document_kind"]
        raw = load(support["blob_ref"])
        meta = metadata_ref(kind, raw)
        refs.append(meta)
        leaves[encoded(meta)] = {
            "document_kind": kind,
            "content": raw.decode() if kind == "license" else parse_canonical(raw),
        }
    if refs != sorted(refs, key=lambda r: (r["document_kind"], r["sha256"])) or len(leaves) != len(refs):
        raise CandidateError("unavailable")
    command = db.execute(
        "SELECT * FROM extension_candidate_commands WHERE candidate_id=?", (row["candidate_id"],)
    ).fetchone()
    if command is None:
        raise CandidateError("unavailable")
    order = parse_canonical(command["document_order"].encode())
    documents = [leaves[encoded(meta)] for meta in order]
    bundle = parse_bundle(
        {
            "command_id": command["command_id"],
            "manifest": manifest,
            "service_descriptor": descriptor,
            "documents": documents,
        }
    )
    actor = EntityRef.from_dict(json.loads(row["actor_ref"]))
    actor_record = domain._load(db, actor, roots)[0]
    account = db.execute("SELECT actor_ref FROM owner_auth_accounts WHERE owner_id=?", (actor.id,)).fetchone()
    receipt = parse_canonical(command["receipt"].encode())
    current_cursor = _decode_cursor(
        _event_cursor_in_transaction(db, vault_id=roots.genesis.id, sequence=command["event_sequence"], event_types=())
    )
    saved_cursor = _decode_cursor(receipt["event_cursor"])
    if (
        saved_cursor["generation"] > current_cursor["generation"]
        or {**saved_cursor, "generation": current_cursor["generation"]} != current_cursor
    ):
        raise CandidateError("unavailable")
    saved_cursor.pop("schema_version")
    expected_receipt = {
        "command_id": command["command_id"],
        "state": "registered_unqualified",
        "event_cursor": _encode_cursor(**saved_cursor),
        "links": {"self": "/api/v1/extensions/candidates/" + row["candidate_id"], "events": "/api/v1/events"},
        "candidate_ref": {
            "candidate_id": row["candidate_id"],
            "manifest_digest": bundle.manifest.digest,
            "service_descriptor_digest": bundle.descriptor.digest,
        },
        "registration_digest": sha256(registration_raw).hexdigest(),
    }
    if (
        anchor["candidate_id"] != ref.id
        or registration["candidate_id"] != ref.id
        or registration["extension_id"] != manifest["extension_id"]
        or registration["support_refs"] != refs
        or registration["manifest_digest"] != row["manifest_digest"]
        or row["manifest_digest"] != bundle.manifest.digest
        or registration["service_descriptor_digest"] != row["descriptor_digest"]
        or row["descriptor_digest"] != bundle.descriptor.digest
        or row["registration_digest"] != sha256(registration_raw).hexdigest()
        or registration["registered_by"] != actor.as_dict()
        or body["actor_ref"] != actor.as_dict()
        or actor_record.body["content"] != {"id": actor.id, "kind": "human", "origin": "local_session"}
        or account is None
        or account["actor_ref"] != row["actor_ref"]
        or command["actor_ref"] != row["actor_ref"]
        or registration["command_id"] != command["command_id"]
        or command["command_id"] != row["command_id"]
        or bundle.digest != command["request_digest"]
        or receipt != expected_receipt
        or body["created_at_utc"] != registration["registered_at"][:-1] + "000Z"
        or body["access_policy_ref"] != roots.access_policy.as_dict()
        or body["retention_policy_ref"] != roots.retention_policy.as_dict()
        or body["purpose"] != "operational"
        or body["parent_refs"] != []
    ):
        raise CandidateError("unavailable")
    datetime.fromisoformat(registration["registered_at"])
    event = db.execute(
        "SELECT event_id,event_type,envelope FROM api_event_envelopes WHERE vault_id=? AND sequence=?",
        (roots.genesis.id, command["event_sequence"]),
    ).fetchone()
    if event is None:
        raise CandidateError("unavailable")
    event_body = EventEnvelope.from_bytes(event["envelope"]).as_dict()
    expected_event = EventEnvelope.create(
        event_id=event["event_id"],
        vault_id=roots.genesis.id,
        sequence=command["event_sequence"],
        recorded_at_utc=body["created_at_utc"],
        observed_at_utc=body["created_at_utc"],
        actor_kind="human",
        actor_ref=actor,
        event_type="extension.candidate_registered",
        object_refs=(),
        correlation_id=command["command_id"],
        causation_id=None,
        status="succeeded",
        error_code=None,
        public_metadata={
            "extension_kind": manifest["extension_kind"],
            "port_contract_version": manifest["port_contract_version"],
            "candidate_count": 1,
            "byte_count": sum(b.size for b in blobs),
        },
        private_evidence_refs=(),
        retention_class="core",
        policy_ref=roots.access_policy,
    ).as_dict()
    if event_body != expected_event or event["event_type"] != "extension.candidate_registered":
        raise CandidateError("unavailable")
    return {
        **receipt,
        "registration": registration,
        "manifest": manifest,
        "service_descriptor": descriptor,
        "documents": documents,
    }, blobs
