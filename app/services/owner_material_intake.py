"""Canonical original publication, immutable lineage, and membership-scoped readback."""
from hashlib import sha256
from uuid import uuid4

from ..domain.owner_material import (
    ARTIFACT_SCHEMA,
    MAX_SOURCES,
    MAX_WORK_BYTES,
    SOURCE_SCHEMA,
    indicate,
    validate_upload,
)
from ..domain.public_events import _event_stream
from ..domain.refs import EntityRef, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef, _writer
from . import owner_material_journal as journal
from .run_approvals import _authenticate_owner, _owner_actor_ref
from .works import WorkServiceError, _closed, _stamp


class OwnerMaterialIntake:
    def __init__(self, works):
        self.works = works
        self.domain, self.owner = works._domain, works._owner

    def _capacity(self, db, roots, latest, size):
        refs = latest.body["content"].get("source_refs", [])
        total = 0
        for ref in refs:
            source = self.domain._load(db, EntityRef.from_dict(ref), roots)[0]
            artifact = self.domain._load(db, EntityRef.from_dict(source.body["content"]["artifact_ref"]), roots)[0]
            total += artifact.body["content"]["size"]
        if len(refs) >= MAX_SOURCES or total + size > MAX_WORK_BYTES:
            raise WorkServiceError("too_large")

    def _admit(self, db, roots, work_id, meta):
        digest = journal.fingerprint("upload", work_id, meta)
        replay = self.works._replay(db, roots, meta["command_id"], digest)
        if replay is not None:
            return replay, None, digest
        latest = self.works._latest(db, roots, work_id)
        if latest is None:
            raise WorkServiceError("not_found")
        if latest.ref.version != meta["expected_revision"]:
            raise WorkServiceError("conflict")
        self._capacity(db, roots, latest, meta["size"])
        return None, latest, digest

    @_closed
    def admit(self, request, work_id, meta):
        uuid_string(work_id)
        validate_upload(meta)
        with self.domain._connection() as db:
            _authenticate_owner(self.owner, request)
            self._admit(db, self.domain._read_roots(db), work_id, meta)

    @_closed
    def publish(self, request, work_id, meta, data):
        self.admit(request, work_id, meta)
        if type(data) is not bytes or len(data) != meta["size"] or sha256(data).hexdigest() != meta["sha256"]:
            raise WorkServiceError("invalid_input")
        # Replays check actual resent bytes but never republish or reapply capacity.
        with self.domain._connection() as db:
            roots = self.domain._read_roots(db)
            replay, _, _ = self._admit(db, roots, work_id, meta)
            if replay is not None:
                _authenticate_owner(self.owner, request)
                return replay
        _authenticate_owner(self.owner, request)  # before CAS, then again inside relation writer
        blob = self.domain.put_blob(data, purpose="operational")
        with _writer(), self.domain._connection(write=True) as db:
            actor = _authenticate_owner(self.owner, request, db)
            roots = self.domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            replay, latest, digest = self._admit(db, roots, work_id, meta)
            if replay is not None:
                return replay
            self.domain._blob_bytes(db, blob, roots, purpose="operational")
            stamp = _stamp()

            def record(kind, content, parents=()):
                value = ImmutableRecord.create(kind=kind, id=str(uuid4()), version=1, created_at_utc=stamp,
                    actor_ref=actor_ref, parent_refs=parents, purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy, content=content)
                self.domain._put_in_transaction(db, value)
                return value

            artifact = record("artifact", {"schema_version": ARTIFACT_SCHEMA, "blob_ref": blob.as_dict(),
                "size": blob.size, "sha256": blob.sha256, "name": meta["name"], "declared_media_type": meta["declared_media_type"],
                "media_indication": indicate(data), "format_validation": "not_performed", "origin": "owner_upload",
                "availability": "stored", "rights": None})
            sequence = _event_stream(db, roots.genesis.id)["next_sequence"]
            source = record("source", {"schema_version": SOURCE_SCHEMA, "artifact_ref": artifact.ref.as_dict(),
                "work_id": work_id, "upload_command_id": meta["command_id"], "supplied_by": actor_ref.as_dict(),
                "source_kind": "upload", "acquisition_event_sequence": sequence, "name": meta["name"], "rights": None},
                (artifact.ref,))
            sources = [*latest.body["content"].get("source_refs", []), source.ref.as_dict()]
            revised = self.works._seal(db, roots, actor_ref, work_id=work_id, version=latest.ref.version + 1,
                command_id=meta["command_id"], text=latest.body["content"]["text"], parent=latest,
                sources=sources, origin="owner_material", v2=True)
            event = self.works._event(db, roots, actor_ref, "source.stored", (source.ref,), meta["command_id"], {"byte_count": blob.size})
            if event.sequence != sequence:
                raise WorkServiceError("unavailable")
            self.works._event(db, roots, actor_ref, "work.revised", (revised.ref,), meta["command_id"],
                              {"revision": revised.ref.version, "source_count": len(sources)})
            value = self.works._projection(revised)
            journal.save(db, roots.genesis.id, meta["command_id"], digest, value)
            return value

    @_closed
    def read_source(self, request, work_id, source_id, *, content=False, head=False):
        uuid_string(work_id)
        uuid_string(source_id)
        with self.domain._connection() as db:
            self.owner.authenticate_bound(request.session)
            roots = self.domain._read_roots(db)
            latest = self.works._latest(db, roots, work_id)
            if latest is None:
                raise WorkServiceError("not_found")
            # Revisions retain every source; the latest immutable membership is the union.
            refs = latest.body["content"].get("source_refs", [])
            ref = next((EntityRef.from_dict(ref) for ref in refs if ref["id"] == source_id), None)
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
            deleted = self.domain._erasure(db, blob, roots) is not None
            if deleted and content:
                raise WorkServiceError("deleted")  # the owner deleted these bytes; the tombstone stands
            data = self.domain._blob_bytes(db, blob, roots, purpose="operational") if content and not head else None
            self.owner.authenticate_bound(request.session)
            return {"source_ref": source.ref.as_dict(), "source": detail, "artifact_ref": artifact.ref.as_dict(),
                    "artifact": original, "original_state": "deleted" if deleted else "stored"}, data
