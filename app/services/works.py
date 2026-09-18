"""The intake's server surface: an owner's work and its revisions as immutable
`work_revision` domain records (data-model.md `WorkRevision`; api.md Intake
`/works`). Every revision is sealed by an owner command — the first one
identifies the work, a later one names the revision it expects — so the run
creation route can name a revision as the run's own input. A replayed command
returns the revision it sealed; a reused command with different content, or a
stale expected revision (another screen revised first), is a conflict. A
command names exactly one revision across every work (found by a scan of the
revisions' canonical bodies — no index; linear in the vault's revisions). The
text is the owner's own sentence, stored exactly (experience.md §5.2: never
overwritten by a system summary), inline in the record under the record's own
64 KiB string bound — data-model.md's `WorkRevision` names an `input_text_ref`
and `interpretation_edits`, and a mutable `Work` head; none exists yet (the
latest revision is read by version). No source, file or event yet.
"""

from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority
from .run_approvals import _authenticate_owner, _owner_actor_ref

__all__ = ["PersistentWorks", "WorkServiceError", "work_identity"]

REVISION_SCHEMA = "work-revision-v1"
CREATE_SCHEMA = "work-create-command-v1"
REVISE_SCHEMA = "work-revise-command-v1"
MAX_TEXT_CHARS = 20_000  # the intake store's own bound (app/storage.py `_text`)
MAX_TEXT_BYTES = 65_536  # the domain record's canonical string bound (app/domain/refs.py), raw UTF-8
CODES = frozenset({
    "invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
    "too_large", "unavailable",
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


def _text(value) -> str:
    if (type(value) is not str or not 1 <= len(value) <= MAX_TEXT_CHARS
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
            "AND instr(body, ?) > 0 ORDER BY id, version",
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
        if content.get("schema_version") != REVISION_SCHEMA:
            raise WorkServiceError("unavailable")
        return {
            "work_id": record.ref.id, "revision": record.ref.version, "text": content["text"],
            "ref": record.ref.as_dict(), "created_at_utc": record.body["created_at_utc"],
        }

    @_closed
    def read(self, work_id) -> dict:
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise WorkServiceError("invalid_input") from None
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            latest = self._latest(db, roots, work_id)
        if latest is None:
            raise WorkServiceError("not_found")
        return self._projection(latest)

    # --- commands ----------------------------------------------------------

    def _seal(self, db, roots, actor_ref, *, work_id, version, command_id, text, parent):
        record = ImmutableRecord.create(
            kind="work_revision", id=work_id, version=version, created_at_utc=_stamp(),
            actor_ref=actor_ref, parent_refs=() if parent is None else (parent.ref,),
            purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content={
                "schema_version": REVISION_SCHEMA, "work_id": work_id, "revision": version,
                "command_id": command_id, "text": text, "source_refs": [],
                "input_origin": "owner_text",
            },
        )
        self._domain._put_in_transaction(db, record)
        return self._domain._load(db, record.ref, roots)[0]

    @_closed
    def create(self, request, payload) -> dict:
        _authenticate_owner(self._owner, request)
        command = _command(payload, CREATE_SCHEMA, ("text",))
        text = _text(command["text"])
        work_id = work_identity(command["command_id"])
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            sealed_before = self._by_command(db, roots, command["command_id"])
            if sealed_before is not None:
                # a replay returns the revision the command sealed; the same command with
                # different content, or naming another work or revision, is a conflict
                if ((sealed_before.ref.id, sealed_before.ref.version) != (work_id, 1)
                        or sealed_before.body["content"].get("text") != text):
                    raise WorkServiceError("conflict")
                return self._projection(sealed_before)
            sealed = self._seal(db, roots, actor_ref, work_id=work_id, version=1,
                                command_id=command["command_id"], text=text, parent=None)
        return self._projection(sealed)

    @_closed
    def revise(self, request, work_id, payload) -> dict:
        _authenticate_owner(self._owner, request)
        command = _command(payload, REVISE_SCHEMA, ("expected_revision", "text"))
        text = _text(command["text"])
        expected = command["expected_revision"]
        if type(expected) is not int or expected < 1:
            raise WorkServiceError("invalid_input")
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise WorkServiceError("invalid_input") from None
        target = expected + 1
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            sealed_before = self._by_command(db, roots, command["command_id"])
            if sealed_before is not None:
                # this command's own replay; the same command with different content, or
                # naming another work or revision, is a conflict
                if ((sealed_before.ref.id, sealed_before.ref.version) != (work_id, target)
                        or sealed_before.body["content"].get("text") != text):
                    raise WorkServiceError("conflict")
                return self._projection(sealed_before)
            latest = self._latest(db, roots, work_id)
            if latest is None:
                raise WorkServiceError("not_found")
            if latest.ref.version != expected:
                # another screen revised first (a stale expectation), or the expectation
                # runs ahead of the work
                raise WorkServiceError("conflict")
            sealed = self._seal(db, roots, actor_ref, work_id=work_id, version=target,
                                command_id=command["command_id"], text=text, parent=latest)
        return self._projection(sealed)
