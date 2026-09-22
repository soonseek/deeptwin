"""The owner's run consent: one immutable `run_consent` record per command over
the exact stored records a run will name.

`RunConsent` authorizes a specific execution (data-model §3: a distinct grant,
never interchangeable with a design approval or an action approval). The
screen's `업무 시작` fixes the input/environment version and this run's allowed
usage and model path (experience §6.3); here that is the exact graph, work
revision, environment and budget policy records, each resolved in this vault
with its declared kind before anything is sealed. The record is authored by
the owner's human actor with its `approval.decided` public event in the same
transaction; exact replay returns the same consent, any other body under the
same command conflicts, nothing is overwritten. A stored row is consent
evidence only with the writer's whole discipline — the owner's actor, the
identity derived from its command, the exact content grammar and the decided
event it names — re-checked on every read. The consent implies no external
write, no billing change and no promotion; the run route still verifies every
input itself.

The run route starts a run only under a consent that names exactly its
inputs, and one consent starts one run (`runs.py`: `_consented`). Deliberately
deferred (recorded open): an expiry and a revocation path (the "current consent"
runtime.md verifies before dispatch — so `resume`/`recover` and the replay of
a sealed command do not re-verify), the run `mode` (the run route fixes
`live`), and the environment ⇄ graph coherence (no production environment
writer exists yet).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import (
    _append_event_in_transaction,
    _assert_event_schema,
    _event_stream,
)
from ..domain.refs import DomainContractError, EntityRef, ObjectRef, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import _writer
from .owner_auth import OwnerAuthError
from .run_approvals import (
    _authenticate_owner,
    _bound_pair,
    _owner_actor_ref,
    _stored_owner_actor_ref,
)
from .runs import PersistentRuns, RunServiceError

__all__ = ["COMMAND_SCHEMA", "RECORD_SCHEMA", "PersistentRunConsents", "RunConsentError", "consent_identity",
           "resolve_consent"]

COMMAND_SCHEMA = "run-consent-command-v1"
RECORD_SCHEMA = "run-consent-v1"
INPUTS = (("graph_ref", "graph"), ("work_revision_ref", "work_revision"),
          ("environment_ref", "environment"), ("budget_policy_ref", "budget_policy"))
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict", "unavailable"})
_CONTENT_KEYS = frozenset({"schema_version", "command_id", *(name for name, _ in INPUTS), "decided_at_utc",
                           "event_sequence"})
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")


class RunConsentError(ValueError):
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
        except (RunConsentError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise RunConsentError("unavailable") from None

    return invoke


def consent_identity(command_id: str) -> str:
    """One consent per command: findable from the command, never multiplied."""

    uuid_string(command_id)
    return str(uuid5(NAMESPACE_URL, f"deeptwin:run-consent:{command_id}"))


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _command(payload) -> dict:
    if (type(payload) is not dict
            or set(payload) != {"schema_version", "command_id", *(name for name, _ in INPUTS)}
            or payload["schema_version"] != COMMAND_SCHEMA):
        raise RunConsentError("invalid_input")
    try:
        command = {"command_id": uuid_string(payload["command_id"])}
        for name, kind in INPUTS:
            ref = EntityRef.from_dict(payload[name])
            if ref.kind != kind:
                raise RunConsentError("invalid_input")
            command[name] = ref
    except (DomainContractError, TypeError, ValueError):
        raise RunConsentError("invalid_input") from None
    return command


def _parse_content(content) -> dict:
    """Re-validate stored content with the writer's grammar."""

    try:
        if (type(content) is not dict or set(content) != _CONTENT_KEYS
                or content["schema_version"] != RECORD_SCHEMA
                or type(content["decided_at_utc"]) is not str
                or _STAMP.fullmatch(content["decided_at_utc"]) is None
                or type(content["event_sequence"]) is not int or content["event_sequence"] < 1):
            raise RunConsentError("unavailable")
        parsed = {"command_id": uuid_string(content["command_id"])}
        for name, kind in INPUTS:
            ref = EntityRef.from_dict(content[name])
            if ref.kind != kind:
                raise RunConsentError("unavailable")
            parsed[name] = ref.as_dict()
    except (RunConsentError, DomainContractError, TypeError, ValueError):
        raise RunConsentError("unavailable") from None
    return {**parsed, "decided_at_utc": content["decided_at_utc"], "event_sequence": content["event_sequence"]}


def resolve_consent(domain, db, roots, ref: EntityRef) -> dict:
    """The projection behind one exact `run_consent` reference — only a record with the
    writer's whole discipline: the owner's human actor, the identity derived from its
    command, the exact content grammar and the `approval.decided` event it names. Any
    other row is `unavailable` as consent evidence (the run route reads that as no consent)."""
    if type(ref) is not EntityRef or ref.kind != "run_consent" or ref.version != 1:
        raise RunConsentError("unavailable")
    try:
        body = domain._load(db, ref, roots)[0].body
    except Exception:  # noqa: BLE001 - an unresolvable consent is no consent evidence
        raise RunConsentError("unavailable") from None
    if _stored_owner_actor_ref(db) != body["actor_ref"]:
        raise RunConsentError("unavailable")
    content = _parse_content(body["content"])
    if consent_identity(content["command_id"]) != ref.id:
        raise RunConsentError("unavailable")
    event_sequence = content.pop("event_sequence")
    event = db.execute(
        "SELECT event_type, envelope FROM api_event_envelopes WHERE vault_id=? AND sequence=?",
        (roots.genesis.id, event_sequence),
    ).fetchone()
    if (event is None or event["event_type"] != "approval.decided"
            or json.loads(event["envelope"]).get("correlation_id") != content["command_id"]):
        # the named event is the decided event of this very command
        raise RunConsentError("unavailable")
    return {"consent_id": ref.id, "ref": ref.as_dict(), **content}


class PersistentRunConsents:
    """Writes and reads run consents over the exact bound store."""

    def __init__(self, domain_store, owner_authority):
        self._domain, self._owner = _bound_pair(domain_store, owner_authority, RunConsentError)

    # --- reads -------------------------------------------------------------

    def _load(self, db, roots, ref: EntityRef) -> dict:
        return resolve_consent(self._domain, db, roots, ref)

    def _existing(self, db, roots, consent_id: str) -> dict | None:
        row = db.execute(
            "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind='run_consent' AND id=? "
            "ORDER BY version DESC LIMIT 1",
            (roots.genesis.id, consent_id),
        ).fetchone()
        if row is None:
            return None
        if row["version"] != 1:
            raise RunConsentError("unavailable")
        return self._load(db, roots, EntityRef("run_consent", consent_id, 1, row["sha256"]))

    @_closed
    def read(self, request, consent_id) -> dict:
        try:
            consent_id = uuid_string(consent_id)
        except (TypeError, ValueError):
            raise RunConsentError("invalid_input") from None
        with self._domain._connection() as db:
            self._owner.authenticate_bound(request.session)
            roots = self._domain._read_roots(db)
            projection = self._existing(db, roots, consent_id)
        if projection is None:
            raise RunConsentError("not_found")
        return projection

    # --- the command -------------------------------------------------------

    def _input(self, db, roots, ref: EntityRef):
        """The exact stored record, or not found: a consent is only ever over records
        that exist in this vault with the declared kind."""
        try:
            return self._domain._load(db, ref, roots)[0]
        except Exception:  # noqa: BLE001 - an unresolvable input is not found
            raise RunConsentError("not_found") from None

    @staticmethod
    def _readable(inputs) -> None:
        """A consent fixes only what the run can read: the graph the executor parses and
        the budget policy binding it verifies — the run route's own readers."""
        try:
            PersistentRuns._graph(inputs["graph_ref"])
            PersistentRuns._policy(inputs["budget_policy_ref"])
        except RunServiceError:
            raise RunConsentError("invalid_input") from None

    @_closed
    def record(self, request, payload) -> dict:
        # authentication before the command: the service itself tells an unauthenticated
        # caller nothing about the grammar (the boundary's wire preflight runs first)
        _authenticate_owner(self._owner, request)
        command = _command(payload)
        consent_id = consent_identity(command["command_id"])
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            _assert_event_schema(db, roots.genesis.id)
            existing = self._existing(db, roots, consent_id)
            if existing is not None:
                if (existing["command_id"] != command["command_id"]
                        or any(existing[name] != command[name].as_dict() for name, _ in INPUTS)):
                    raise RunConsentError("conflict")
                return existing
            inputs = {name: self._input(db, roots, command[name]) for name, _ in INPUTS}
            self._readable(inputs)
            actor_ref = _owner_actor_ref(db, actor)
            stamp = _stamp()
            event_sequence = _event_stream(db, roots.genesis.id)["next_sequence"]
            record = ImmutableRecord.create(
                kind="run_consent", id=consent_id, version=1, created_at_utc=stamp,
                actor_ref=actor_ref, parent_refs=(), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content={
                    "schema_version": RECORD_SCHEMA, "command_id": command["command_id"],
                    **{name: command[name].as_dict() for name, _ in INPUTS},
                    "decided_at_utc": stamp, "event_sequence": event_sequence,
                },
            )
            self._domain._put_in_transaction(db, record)
            event = _append_event_in_transaction(
                db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
                actor_kind="human", actor_ref=actor_ref, event_type="approval.decided",
                object_refs=(ObjectRef(record.ref.kind, record.ref.id, record.ref.version, record.ref.sha256),
                             *(ObjectRef(ref.kind, ref.id, ref.version, ref.sha256)
                               for ref in (command[name] for name, _ in INPUTS))),
                correlation_id=command["command_id"], causation_id=None, status="succeeded",
                error_code=None, public_metadata={"decision": "approved"}, private_evidence_refs=(),
                retention_class="core", policy_ref=roots.access_policy,
            )
            if event.sequence != event_sequence:
                raise RunConsentError("unavailable")
            return self._load(db, roots, record.ref)
