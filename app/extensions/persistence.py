"""Actual owner/session to durable, unqualified metadata registration."""

import json
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from uuid import uuid4

from ..domain.public_events import (
    _append_event_in_transaction,
    _assert_event_schema,
    _event_cursor_in_transaction,
)
from ..domain.refs import EntityRef, canonical_json, parse_canonical, uuid_string
from ..domain.request_identity import AuthenticatedRequest
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from ..services.owner_auth import OwnerAuthError, PersistentOwnerAuthority
from . import candidate_storage as storage
from .candidate_contracts import CandidateError, metadata_ref, parse_bundle
from .candidate_records import load_candidate

MAX_CANDIDATES = 1024
MAX_CONTENT_BYTES = 67108864


def closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (CandidateError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose private paths or metadata
            raise CandidateError("unavailable") from None

    return invoke


def encoded(value):
    return canonical_json(value).decode()


class PersistentCandidateRegistry:
    @closed
    def __init__(self, domain_store, owner_authority):
        if (
            type(domain_store) is not DomainStore
            or type(owner_authority) is not PersistentOwnerAuthority
            or owner_authority._domain is not domain_store
        ):
            raise CandidateError("unavailable")
        self._domain, self._owner = domain_store, owner_authority
        self._binding = {"vault_id": domain_store.vault_id, "instance_id": owner_authority.profile.instance_id}
        with _writer(), domain_store._connection(write=True) as db:
            owner_authority._check(db)
            existing = db.execute("SELECT 1 FROM sqlite_master WHERE name='extension_candidate_migrations'").fetchone()
            storage.install(db)
            if not existing:
                storage.insert(
                    db, "control", dict(singleton=1, **self._binding, candidate_count=0, content_bytes=0, revision=1)
                )
            self._verify(db)

    def _authenticate(self, request, db=None, *, read=False):
        profile = self._owner.profile
        if (
            type(request) is not AuthenticatedRequest
            or type(request.method) is not str
            or request.method not in ({"GET", "HEAD"} if read else {"POST"})
            or type(request.csrf_verified) is not bool
            or (not read and not request.csrf_verified)
            or type(request.host) is not str
            or request.host != profile.http_origin.split("://", 1)[1]
            or request.origin not in (None, profile.http_origin)
            or (not read and request.origin != profile.http_origin)
        ):
            raise OwnerAuthError("access_denied")
        actor = self._owner.authenticate_bound(request.session, db=db)
        if actor is not request.session.actor or actor.kind != "human" or actor.origin != "local_session":
            raise OwnerAuthError("unauthenticated")
        return actor

    def _verify(self, db):
        storage.verify(db)
        _assert_event_schema(db, self._binding["vault_id"])
        control = db.execute("SELECT * FROM extension_candidate_control").fetchone()
        if control is None or any(control[k] != v for k, v in self._binding.items()):
            raise CandidateError("unavailable")
        indices = list(db.execute("SELECT * FROM extension_candidate_index"))
        commands = list(db.execute("SELECT * FROM extension_candidate_commands"))
        expected = {}
        for row in indices:
            try:
                _, blobs = load_candidate(self._domain, db, row)
            except CandidateError:
                raise CandidateError("unavailable") from None
            expected.update({blob.sha256: blob.size for blob in blobs})
        contents = list(db.execute("SELECT * FROM extension_candidate_contents"))
        actual = {r["sha256"]: r["size"] for r in contents}
        if (
            len(indices) != len(commands)
            or len(indices) != control["candidate_count"]
            or actual != expected
            or sum(actual.values()) != control["content_bytes"]
            or any(r["vault_id"] != self._binding["vault_id"] or r["purpose"] != "operational" for r in contents)
        ):
            raise CandidateError("unavailable")
        return control

    def _replay(self, db, bundle, actor):
        row = db.execute(
            "SELECT * FROM extension_candidate_commands WHERE command_id=?", (bundle.as_dict()["command_id"],)
        ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != bundle.digest or EntityRef.from_dict(json.loads(row["actor_ref"])).id != actor.id:
            raise CandidateError("conflict")
        return parse_canonical(row["receipt"].encode())

    @staticmethod
    def _capacity(db, control, raws):
        unique = {sha256(raw).hexdigest(): len(raw) for raw in raws}
        stored = {r[0]: r[1] for r in db.execute("SELECT sha256,size FROM extension_candidate_contents")}
        extra = sum(size for digest, size in unique.items() if digest not in stored)
        if control["candidate_count"] >= MAX_CANDIDATES or control["content_bytes"] + extra > MAX_CONTENT_BYTES:
            raise CandidateError("capacity")
        return extra

    @closed
    def register(self, request, payload):
        bundle = parse_bundle(payload)
        actor = self._authenticate(request)
        with _writer(), self._domain._connection(write=True) as db:
            actor = self._authenticate(request, db)
            control = self._verify(db)
            replay = self._replay(db, bundle, actor)
            if replay is not None:
                return replay
            roots = self._domain._read_roots(db)
            account = db.execute("SELECT actor_ref FROM owner_auth_accounts WHERE owner_id=?", (actor.id,)).fetchone()
            actor_ref = EntityRef.from_dict(json.loads(account["actor_ref"]))
            stamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            candidate_id = str(uuid4())
            support_refs = [metadata_ref(kind, raw) for kind, raw in bundle.documents]
            registration = {
                "schema_version": "extension-candidate-registration-v1",
                "candidate_id": candidate_id,
                "extension_id": bundle.manifest.as_dict()["extension_id"],
                "manifest_digest": bundle.manifest.digest,
                "service_descriptor_digest": bundle.descriptor.digest,
                "support_refs": support_refs,
                "registered_by": actor_ref.as_dict(),
                "registered_at": stamp,
                "source_class": "owner_proposal",
                "command_id": bundle.as_dict()["command_id"],
            }
            raws = [
                bundle.manifest.content_bytes,
                bundle.descriptor.content_bytes,
                canonical_json(registration),
                *[raw for _, raw in bundle.documents],
            ]
            self._capacity(db, control, raws)
        # put_blob owns a writer. These rows/files may remain unattached after failure.
        blobs = [self._domain.put_blob(raw, purpose="operational") for raw in raws]
        with _writer(), self._domain._connection(write=True) as db:
            actor = self._authenticate(request, db)
            control = self._verify(db)
            replay = self._replay(db, bundle, actor)
            if replay is not None:
                return replay
            extra = self._capacity(db, control, raws)
            anchor = {
                "schema_version": "extension-candidate-anchor-v1",
                "candidate_id": candidate_id,
                "manifest_blob_ref": blobs[0].as_dict(),
                "service_descriptor_blob_ref": blobs[1].as_dict(),
                "registration_blob_ref": blobs[2].as_dict(),
                "support_documents": [
                    {"document_kind": kind, "blob_ref": blob.as_dict()}
                    for (kind, _), blob in zip(bundle.documents, blobs[3:], strict=True)
                ],
            }
            record = ImmutableRecord.create(
                kind="extension_manifest",
                id=candidate_id,
                version=1,
                created_at_utc=stamp[:-1] + "000Z",
                actor_ref=actor_ref,
                parent_refs=(),
                purpose="operational",
                access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content=anchor,
            )
            self._domain._put_in_transaction(db, record)
            storage.insert(
                db,
                "index",
                {
                    "candidate_id": candidate_id,
                    "vault_id": roots.genesis.id,
                    "kind": "extension_manifest",
                    "version": 1,
                    "anchor_digest": record.ref.sha256,
                    "manifest_digest": bundle.manifest.digest,
                    "descriptor_digest": bundle.descriptor.digest,
                    "registration_digest": blobs[2].sha256,
                    "actor_ref": encoded(actor_ref.as_dict()),
                    "command_id": registration["command_id"],
                },
            )
            for blob in blobs:
                if (
                    db.execute("SELECT 1 FROM extension_candidate_contents WHERE sha256=?", (blob.sha256,)).fetchone()
                    is None
                ):
                    storage.insert(db, "contents", blob.as_dict())
            storage.advance(
                db,
                control,
                candidate_count=control["candidate_count"] + 1,
                content_bytes=control["content_bytes"] + extra,
            )
            manifest = bundle.manifest.as_dict()
            event = _append_event_in_transaction(
                db,
                vault_id=roots.genesis.id,
                recorded_at_utc=stamp[:-1] + "000Z",
                observed_at_utc=stamp[:-1] + "000Z",
                actor_kind="human",
                actor_ref=actor_ref,
                event_type="extension.candidate_registered",
                object_refs=(),
                correlation_id=registration["command_id"],
                causation_id=None,
                status="succeeded",
                error_code=None,
                public_metadata={
                    "extension_kind": manifest["extension_kind"],
                    "port_contract_version": manifest["port_contract_version"],
                    "candidate_count": 1,
                    "byte_count": sum(len(raw) for raw in raws),
                },
                private_evidence_refs=(),
                retention_class="core",
                policy_ref=roots.access_policy,
            )
            receipt = {
                "command_id": registration["command_id"],
                "state": "registered_unqualified",
                "event_cursor": _event_cursor_in_transaction(
                    db, vault_id=roots.genesis.id, sequence=event.sequence, event_types=()
                ),
                "links": {"self": "/api/v1/extensions/candidates/" + candidate_id, "events": "/api/v1/events"},
                "candidate_ref": {
                    "candidate_id": candidate_id,
                    "manifest_digest": bundle.manifest.digest,
                    "service_descriptor_digest": bundle.descriptor.digest,
                },
                "registration_digest": blobs[2].sha256,
            }
            document_order = [
                metadata_ref(
                    e["document_kind"],
                    e["content"].encode() if e["document_kind"] == "license" else canonical_json(e["content"]),
                )
                for e in bundle.as_dict()["documents"]
            ]
            storage.insert(
                db,
                "commands",
                {
                    "command_id": registration["command_id"],
                    "candidate_id": candidate_id,
                    "namespace": "extension-candidate-register-v1",
                    "actor_ref": encoded(actor_ref.as_dict()),
                    "request_digest": bundle.digest,
                    "document_order": encoded(document_order),
                    "receipt": encoded(receipt),
                    "event_sequence": event.sequence,
                },
            )
            self._verify(db)
            return receipt

    @closed
    def read(self, request, candidate_id):
        try:
            uuid_string(candidate_id)
        except ValueError:
            raise CandidateError() from None
        with _writer(), self._domain._connection(write=True) as db:
            self._authenticate(request, db, read=True)
            self._verify(db)
            row = db.execute("SELECT * FROM extension_candidate_index WHERE candidate_id=?", (candidate_id,)).fetchone()
            if row is None:
                raise CandidateError("not_found")
            return load_candidate(self._domain, db, row)[0]
