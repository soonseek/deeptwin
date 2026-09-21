"""Owner work revisions, source retention and exact text-command receipts.

The shared journal binds new text and original-upload commands across works.
Historical v1 commands remain readable/replayable without rewriting their records.
Every new mutation emits its public event in the same relation transaction.
Original publication lives in owner_material_intake; no extraction occurs.
"""

from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import _append_event_in_transaction
from ..domain.refs import EntityRef, ObjectRef, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from . import owner_material_journal as journal
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority
from .run_approvals import _authenticate_owner, _owner_actor_ref

__all__ = ["PersistentWorks", "WorkServiceError", "work_identity"]

REVISION_SCHEMA = "work-revision-v1"
CREATE_SCHEMA = "work-create-command-v1"
REVISE_SCHEMA = "work-revise-command-v1"
CREATE_V2 = "work-create-command-v2"
REVISE_V2 = "work-revise-command-v2"
MAX_TEXT_CHARS = 20_000  # the intake store's own bound (app/storage.py `_text`)
MAX_TEXT_BYTES = 65_536  # the domain record's canonical string bound (app/domain/refs.py), raw UTF-8
CODES = frozenset({
    "invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
    "too_large", "unavailable", "capacity",
})


class WorkServiceError(ValueError):
    """Closed codes; storage detail never leaks."""

    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (WorkServiceError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise WorkServiceError("unavailable") from None

    return invoke


def work_identity(command_id: str) -> str:
    """One work per creating command: findable from the command, never multiplied."""

    uuid_string(command_id)
    return str(uuid5(NAMESPACE_URL, f"deeptwin:work:{command_id}"))


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _text(value, *, empty=False) -> str:
    if (type(value) is not str or not (0 if empty else 1) <= len(value) <= MAX_TEXT_CHARS
            or len(value.encode("utf-8")) > MAX_TEXT_BYTES):
        raise WorkServiceError("invalid_input")
    return value


def _command(payload, schema, fields) -> dict:
    if (type(payload) is not dict or set(payload) != {"schema_version", "command_id", *fields}
            or payload["schema_version"] != schema):
        raise WorkServiceError("invalid_input")
    try:
        command_id = uuid_string(payload["command_id"])
    except (TypeError, ValueError):
        raise WorkServiceError("invalid_input") from None
    return {"command_id": command_id, **{name: payload[name] for name in fields}}


class PersistentWorks:
    """Owner-authenticated work revisions over the actual domain store."""

    def __init__(self, domain_store, owner_authority):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(owner_authority) is not PersistentOwnerAuthority:
            raise TypeError("Exact PersistentOwnerAuthority required")
        if owner_authority._domain is not domain_store:
            raise TypeError("Owner authority must share the actual domain store")
        self._domain = domain_store
        self._owner = owner_authority
        with _writer(), self._domain._connection(write=True) as db:
            db.execute(journal.DDL)

    # --- reads -------------------------------------------------------------

    def _version(self, db, roots, work_id: str, version: int):
        row = db.execute(
            "SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='work_revision' "
            "AND id=? AND version=?",
            (roots.genesis.id, work_id, version),
        ).fetchone()
        if row is None:
            return None
        ref = EntityRef("work_revision", work_id, version, row["sha256"])
        return self._domain._load(db, ref, roots)[0]

    def _by_command(self, db, roots, command_id: str):
        """The one revision a command sealed, across every work (a scan of the
        canonical bodies: the key is exact in them, no index)."""
        # the canonical body escapes every quote inside a string, so the needle can only
        # be the key itself; every match is still read back and checked
        needle = f'"command_id":"{command_id}"'.encode()
        rows = db.execute(
            "SELECT id, version FROM domain_records WHERE vault_id=? AND kind='work_revision' "
            "AND instr(body, ?) > 0 ORDER BY id, version LIMIT 2",
            (roots.genesis.id, needle),
        ).fetchall()
        for row in rows:
            record = self._version(db, roots, row["id"], row["version"])
            if record.body["content"].get("command_id") == command_id:
                return record
        return None

    def _latest(self, db, roots, work_id: str):
        row = db.execute(
            "SELECT version FROM domain_records WHERE vault_id=? AND kind='work_revision' "
            "AND id=? ORDER BY version DESC LIMIT 1",
            (roots.genesis.id, work_id),
        ).fetchone()
        if row is None:
            return None
        return self._version(db, roots, work_id, row["version"])

    @staticmethod
    def _projection(record) -> dict:
        content = record.body["content"]
        if content.get("schema_version") not in {REVISION_SCHEMA, "work-revision-v2"}:
            raise WorkServiceError("unavailable")
        value = {
            "work_id": record.ref.id, "revision": record.ref.version, "text": content["text"],
            "ref": record.ref.as_dict(), "created_at_utc": record.body["created_at_utc"],
        }
        if content["schema_version"] == "work-revision-v2":
            value.update(source_refs=content["source_refs"], input_origin=content["input_origin"])
        return value

    @_closed
    def read(self, work_id, request=None, revision=None) -> dict:
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise WorkServiceError("invalid_input") from None
        with self._domain._connection() as db:
            if request is not None:
                self._owner.authenticate_bound(request.session)
            roots = self._domain._read_roots(db)
            latest = self._latest(db, roots, work_id) if revision is None else self._version(db, roots, work_id, revision)
        if latest is None:
            raise WorkServiceError("not_found")
        return self._projection(latest)

    # --- commands ----------------------------------------------------------

    def _seal(self, db, roots, actor_ref, *, work_id, version, command_id, text, parent,
              sources=(), origin="owner_text", v2=False):
        record = ImmutableRecord.create(
            kind="work_revision", id=work_id, version=version, created_at_utc=_stamp(),
            actor_ref=actor_ref, parent_refs=() if parent is None else (parent.ref,),
            purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content={
                "schema_version": "work-revision-v2" if v2 or sources else REVISION_SCHEMA,
                "work_id": work_id, "revision": version,
                "command_id": command_id, "text": text, "source_refs": list(sources),
                "input_origin": origin,
            },
        )
        self._domain._put_in_transaction(db, record)
        return self._domain._load(db, record.ref, roots)[0]

    def _event(self, db, roots, actor_ref, kind, refs, command_id, metadata):
        stamp = _stamp()
        return _append_event_in_transaction(db, vault_id=roots.genesis.id, recorded_at_utc=stamp,
            observed_at_utc=stamp, actor_kind="human", actor_ref=actor_ref, event_type=kind,
            object_refs=tuple(ObjectRef(ref.kind, ref.id, ref.version, ref.sha256) for ref in refs),
            correlation_id=command_id, causation_id=None, status="succeeded",
            error_code=None, public_metadata=metadata, private_evidence_refs=(),
            retention_class="core", policy_ref=roots.access_policy)

    def _replay(self, db, roots, command_id, digest, *, legacy=None):
        row = journal.lookup(db, roots.genesis.id, command_id)
        if row is not None:
            if row["fingerprint"] != digest:
                raise WorkServiceError("conflict")
            return journal.receipt(row)
        old = self._by_command(db, roots, command_id)
        if old is not None:
            # Only pre-journal v1 text commands can use historical inference.
            if legacy is None or not legacy(old):
                raise WorkServiceError("conflict")
            return self._projection(old)
        return None

    @_closed
    def receipt(self, request, command_id):
        uuid_string(command_id)
        with self._domain._connection() as db:
            self._owner.authenticate_bound(request.session)
            roots = self._domain._read_roots(db)
            row = journal.lookup(db, roots.genesis.id, command_id)
            if row is not None:
                return journal.receipt(row)
            old = self._by_command(db, roots, command_id)
            if old is not None:
                return self._projection(old)
        raise WorkServiceError("not_found")

    @_closed
    def create(self, request, payload) -> dict:
        _authenticate_owner(self._owner, request)
        v2 = type(payload) is dict and payload.get("schema_version") == CREATE_V2
        command = _command(payload, CREATE_V2 if v2 else CREATE_SCHEMA, ("text", "input_origin") if v2 else ("text",))
        origin = command.get("input_origin", "owner_text")
        if type(origin) is not str or origin not in {"owner_text", "owner_material"}:
            raise WorkServiceError("invalid_input")
        text = _text(command["text"], empty=v2 and origin == "owner_material")
        work_id = work_identity(command["command_id"])
        digest = journal.fingerprint("create", work_id, payload)
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            replay = self._replay(db, roots, command["command_id"], digest,
                legacy=None if v2 else lambda old: (old.ref.id, old.ref.version, old.body["content"].get("text"),
                    old.body["content"].get("schema_version")) == (work_id, 1, text, REVISION_SCHEMA))
            if replay is not None:
                return replay
            sealed = self._seal(db, roots, actor_ref, work_id=work_id, version=1,
                                command_id=command["command_id"], text=text, parent=None, origin=origin, v2=v2)
            self._event(db, roots, actor_ref, "work.created", (sealed.ref,), command["command_id"],
                        {"revision": 1, "source_count": 0})
            journal.save(db, roots.genesis.id, command["command_id"], digest, self._projection(sealed))
        return self._projection(sealed)

    @_closed
    def revise(self, request, work_id, payload) -> dict:
        _authenticate_owner(self._owner, request)
        v2 = type(payload) is dict and payload.get("schema_version") == REVISE_V2
        command = _command(payload, REVISE_V2 if v2 else REVISE_SCHEMA, ("expected_revision", "text"))
        text = _text(command["text"], empty=v2)
        expected = command["expected_revision"]
        if type(expected) is not int or expected < 1:
            raise WorkServiceError("invalid_input")
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise WorkServiceError("invalid_input") from None
        target = expected + 1
        digest = journal.fingerprint("revise", work_id, payload)
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            replay = self._replay(db, roots, command["command_id"], digest,
                legacy=None if v2 else lambda old: (old.ref.id, old.ref.version, old.body["content"].get("text"),
                    old.body["content"].get("schema_version")) == (work_id, target, text, REVISION_SCHEMA))
            if replay is not None:
                return replay
            latest = self._latest(db, roots, work_id)
            if latest is None:
                raise WorkServiceError("not_found")
            if latest.ref.version != expected:
                # another screen revised first (a stale expectation), or the expectation
                # runs ahead of the work
                raise WorkServiceError("conflict")
            sources = latest.body["content"].get("source_refs", [])
            if not text and not sources:
                raise WorkServiceError("invalid_input")
            sealed = self._seal(db, roots, actor_ref, work_id=work_id, version=target,
                                command_id=command["command_id"], text=text, parent=latest, sources=sources, v2=v2)
            self._event(db, roots, actor_ref, "work.revised", (sealed.ref,), command["command_id"],
                        {"revision": target, "source_count": len(sources)})
            journal.save(db, roots.genesis.id, command["command_id"], digest, self._projection(sealed))
        return self._projection(sealed)
