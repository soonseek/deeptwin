"""Explicit deletion of a work's stored originals (US7, T073; operations.md §5.1,
OPS-D04/AC06).

Nothing is deleted automatically. The owner first reads a preview of exactly what a
deletion would remove and what it touches:
- each original (name, media type, size, digest)
- every stored record that names it: the original's artifact, its source record,
  every revision of every work listing that source, and other works' sources that
  hold the same bytes (content-addressed storage keeps one copy)
- what the deletion cannot reach: backups made before it, and copies already
  exported or sent elsewhere

`preview_sha256` digests that whole preview together with the request id and the
reason. The deletion itself needs the explicit `confirmed: true` and that exact
digest. It recomputes the preview inside the writer, so anything that changed in
between is a conflict.

It seals one immutable tombstone per original (`blob-erasure-v1`, carrying the
contract's minimal tombstone fields and nothing of the deleted content, file name
included) and the `retention.deleted` event. Only after the commit does it remove
the bytes and confirm their absence. From the commit on, every reader answers
`deleted`; the records that named the original stay and read back, and the
tombstone stands where the bytes were.

A deletion is never undone, and the same bytes cannot be stored again under this
vault's content address.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.owner_material import ARTIFACT_SCHEMA, SOURCE_SCHEMA
from ..domain.refs import EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import ERASURE_KIND, ERASURE_SCHEMA, BlobRef, _writer, erasure_identity
from .run_approvals import _authenticate_owner, _owner_actor_ref
from .works import WorkServiceError, _closed

PREVIEW_SCHEMA = "source-deletion-preview-command-v1"
CONFIRM_SCHEMA = "source-deletion-command-v1"
REASONS = frozenset({"user_requested", "rights_request"})
MAX_SOURCES = 20
NOT_REACHED = ("backups_made_before_this_deletion", "copies_already_exported_or_sent",
               "copies_outside_this_instance")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def deletion_request_identity(request_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:source-deletion:{uuid_string(request_id)}"))


class SourceDeletions:
    def __init__(self, works):
        self.works = works
        self.domain, self.owner = works._domain, works._owner

    # --- the exact scope --------------------------------------------------------------

    def _scope(self, db, roots, work_id, source_ids):
        latest = self.works._latest(db, roots, work_id)
        if latest is None:
            raise WorkServiceError("not_found")
        listed = {ref["id"]: EntityRef.from_dict(ref) for ref in latest.body["content"].get("source_refs", [])}
        items, affected = [], {}

        def touch(ref):
            affected[(ref.kind, ref.id, ref.version)] = ref

        for source_id in source_ids:
            ref = listed.get(source_id)
            if ref is None:
                raise WorkServiceError("not_found")
            source = self.domain._load(db, ref, roots)[0]
            detail = source.body["content"]
            if detail.get("schema_version") != SOURCE_SCHEMA or detail["work_id"] != work_id:
                raise WorkServiceError("unavailable")
            artifact = self.domain._load(db, EntityRef.from_dict(detail["artifact_ref"]), roots)[0]
            original = artifact.body["content"]
            if original.get("schema_version") != ARTIFACT_SCHEMA:
                raise WorkServiceError("unavailable")
            blob = BlobRef.from_dict(original["blob_ref"])
            erased = self.domain._erasure(db, blob, roots) is not None
            # every record whose body names these exact bytes, and every record naming those
            holders = [EntityRef(row[0], row[1], row[2], row[3]) for row in db.execute(
                "SELECT r.kind, r.id, r.version, r.sha256 FROM domain_record_blobs b JOIN domain_records r "
                "ON r.vault_id=b.vault_id AND r.kind=b.source_kind AND r.id=b.source_id AND r.version=b.source_version "
                "WHERE b.vault_id=? AND b.purpose=? AND b.sha256=? ORDER BY r.kind, r.id, r.version",
                (roots.genesis.id, blob.purpose, blob.sha256))]
            others = []
            for holder in holders:
                touch(holder)
                for row in db.execute(
                        "SELECT r.kind, r.id, r.version, r.sha256 FROM domain_edges e JOIN domain_records r "
                        "ON r.vault_id=e.vault_id AND r.kind=e.source_kind AND r.id=e.source_id "
                        "AND r.version=e.source_version WHERE e.vault_id=? AND e.target_kind=? AND e.target_id=? "
                        "AND e.target_version=? ORDER BY r.kind, r.id, r.version",
                        (roots.genesis.id, holder.kind, holder.id, holder.version)):
                    dependent = EntityRef(row[0], row[1], row[2], row[3])
                    touch(dependent)
                    if dependent.kind == "source" and dependent.id != ref.id:
                        others.append(dependent.id)
            touch(ref)
            revisions = [EntityRef(row[0], row[1], row[2], row[3]) for row in db.execute(
                "SELECT kind, id, version, sha256 FROM domain_records WHERE vault_id=? AND kind='work_revision' "
                "AND instr(body, ?) > 0 ORDER BY id, version", (roots.genesis.id, ref.id.encode()))]
            for revision in revisions:
                touch(revision)
            items.append({
                "source_id": ref.id, "name": detail["name"], "media_type": original["declared_media_type"],
                "size": blob.size, "sha256": blob.sha256, "state": "deleted" if erased else "stored",
                "blob": blob, "artifact": artifact.ref, "revisions_naming_it": len(revisions),
                "shared_with_other_sources": sorted(set(others)),
            })
        return latest, items, sorted(affected.values(), key=lambda item: (item.kind, item.id, item.version))

    @staticmethod
    def _view(request_id, reason, items, affected) -> dict:
        body = {
            "request_id": request_id, "reason_code": reason,
            "items": [{key: value for key, value in item.items() if key not in {"blob", "artifact"}}
                      for item in items],
            "affected_refs": [ref.as_dict() for ref in affected],
            "affected_record_count": len(affected),
            "not_reached": list(NOT_REACHED),
            "records_kept": "records that named a deleted original stay and read back; the original reads as deleted",
        }
        return {**body, "preview_sha256": sha256(canonical_json(body)).hexdigest()}

    @staticmethod
    def _command(payload, schema, keys):
        if type(payload) is not dict or set(payload) != keys or payload.get("schema_version") != schema:
            raise WorkServiceError("invalid_input")
        ids = payload["source_ids"]
        if (type(ids) is not list or not 1 <= len(ids) <= MAX_SOURCES or len(set(ids)) != len(ids)
                or payload["reason_code"] not in REASONS):
            raise WorkServiceError("invalid_input")
        try:
            uuid_string(payload["request_id"])
            for item in ids:
                uuid_string(item)
        except (TypeError, ValueError):
            raise WorkServiceError("invalid_input") from None
        return payload

    # --- preview ----------------------------------------------------------------------

    @_closed
    def preview(self, request, work_id, payload) -> dict:
        uuid_string(work_id)
        command = self._command(payload, PREVIEW_SCHEMA,
                                {"schema_version", "request_id", "source_ids", "reason_code"})
        with self.domain._connection() as db:
            _authenticate_owner(self.owner, request)
            roots = self.domain._read_roots(db)
            _latest, items, affected = self._scope(db, roots, work_id, command["source_ids"])
        if any(item["state"] == "deleted" for item in items):
            raise WorkServiceError("conflict")  # already deleted: nothing left to preview
        return self._view(command["request_id"], command["reason_code"], items, affected)

    # --- the deletion -----------------------------------------------------------------

    @_closed
    def delete(self, request, work_id, payload) -> dict:
        uuid_string(work_id)
        command = self._command(payload, CONFIRM_SCHEMA, {"schema_version", "request_id", "source_ids",
                                                          "reason_code", "preview_sha256", "confirmed"})
        if command["confirmed"] is not True or type(command["preview_sha256"]) is not str:
            raise WorkServiceError("invalid_input")  # consent is explicit, never implied
        deletion_id = deletion_request_identity(command["request_id"])
        with _writer(), self.domain._connection(write=True) as db:
            actor = _authenticate_owner(self.owner, request, db)
            roots = self.domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            _latest, items, affected = self._scope(db, roots, work_id, command["source_ids"])
            replay = [item for item in items if item["state"] == "deleted"]
            if replay:
                if len(replay) == len(items) and all(
                        self._tombstone_request(db, roots, item["blob"]) == deletion_id for item in items):
                    return self._result(command["request_id"], items, removed=None)
                raise WorkServiceError("conflict")
            view = self._view(command["request_id"], command["reason_code"], items, affected)
            if view["preview_sha256"] != command["preview_sha256"]:
                raise WorkServiceError("conflict")  # the scope changed since the owner saw it
            stamp = _stamp()
            tombstones, sealed = [], set()
            for item in items:
                blob = item["blob"]
                if blob.sha256 in sealed:
                    continue  # two selected sources with the same bytes share one tombstone
                sealed.add(blob.sha256)
                record = ImmutableRecord.create(
                    kind=ERASURE_KIND, id=erasure_identity(roots.genesis.id, blob.purpose, blob.sha256), version=1,
                    created_at_utc=stamp, actor_ref=actor_ref, parent_refs=(), purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                    content={"schema_version": ERASURE_SCHEMA, "blob_purpose": blob.purpose,
                             "blob_sha256": blob.sha256, "blob_size": blob.size,
                             "object_id": item["artifact"].id, "former_kind": "original",
                             "deleted_at": stamp, "deletion_request_id": deletion_id,
                             "affected_refs": [ref.as_dict() for ref in affected],
                             "reason_code": command["reason_code"],
                             "preview_sha256": command["preview_sha256"]})
                tombstones.append(self.domain._erase_in_transaction(db, blob, record))
            self.works._event(db, roots, actor_ref, "retention.deleted",
                              tuple(tombstones), command["request_id"],
                              {"object_count": len(tombstones),
                               "byte_count": sum({item["sha256"]: item["size"] for item in items}.values())})
        # the bytes go only after the tombstones are durable
        removed = {}
        for item in items:
            try:
                removed[item["source_id"]] = self.domain.remove_erased_bytes(item["blob"])
            except Exception:  # noqa: BLE001 - reported as pending, never as done
                removed[item["source_id"]] = False
        return self._result(command["request_id"], items, removed=removed)

    def _tombstone_request(self, db, roots, blob):
        record = self.domain._erasure(db, blob, roots)
        return None if record is None else record.body["content"]["deletion_request_id"]

    @staticmethod
    def _result(request_id, items, *, removed):
        return {
            "request_id": request_id,
            "deleted": [{"source_id": item["source_id"], "size": item["size"], "sha256": item["sha256"],
                         "bytes_removed": (None if removed is None else removed[item["source_id"]])}
                        for item in items],
            "not_reached": list(NOT_REACHED),
        }
