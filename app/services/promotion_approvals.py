"""Owner-authorized promotion approvals: the authoritative evidence behind
`record_promotion_decision` (growth.md `PromotionDecision` — a human's
authenticated explicit act; FR-026; G-13 exact-hash approval).

The persistent owner session is the only authority: a CSRF-verified
same-origin POST is re-authenticated with `authenticate_bound` inside the
final writer, and the decision is written as one immutable
`action_approval` record whose content binds the exact candidate bundle
identity, the validation report the human decided over, the expected
current environment, the decision and the command, authored by the owner's
human actor. An approve or reject also appends its `approval.decided` public
event in the same transaction (the closed catalog carries no promotion kind
or deferred value, so a defer leaves the approval undecided, appends no
decided event and is visible only through the record). One record exists
per command: exact replay returns the same
issued value, a different command body under the same id conflicts, and a
new command for the same bundle (for example after the current environment
moved) is a fresh decision, never a rewrite. Only values issued here — or
resolved here from an exact reference — are accepted by the promotion
constructor; no caller-declared boolean stands in for them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import (
    _append_event_in_transaction,
    _assert_event_schema,
    _event_stream,
)
from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import _writer
from .owner_auth import OwnerAuthError
from .run_approvals import (
    _authenticate_owner,
    _bound_pair,
    _owner_actor_ref,
    _stored_owner_actor_ref,
)

DECISIONS = ("approve", "reject", "defer")
_EVENT_DECISION = {"approve": "approved", "reject": "rejected"}
_SCHEMA = "promotion-approval-command-v1"
_RECORD_SCHEMA = "promotion-approval-v1"
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_ISSUE_TOKEN = object()


class PromotionApprovalError(ValueError):
    """invalid | conflict | unavailable — never a private storage detail."""


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (PromotionApprovalError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose private detail
            raise PromotionApprovalError("unavailable") from None

    return invoke


@dataclass(frozen=True, slots=True, init=False)
class PromotionApproval:
    """One owner-recorded promotion decision, issued by this module only."""

    candidate_bundle: EntityRef
    validation_report: EntityRef
    expected_current_environment: EntityRef
    decision: str
    command_id: str
    approval_ref: EntityRef
    actor_ref: EntityRef
    decided_at_utc: str
    _issuer_token: object = field(repr=False, compare=False)


def is_issued_promotion_approval(value) -> bool:
    return (
        type(value) is PromotionApproval
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def _issue(**fields) -> PromotionApproval:
    value = object.__new__(PromotionApproval)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    object.__setattr__(value, "_issuer_token", _ISSUE_TOKEN)
    return value


def approval_identity(command_id: str) -> str:
    """One record per command: replay is exact, every other body conflicts."""

    return str(
        uuid5(
            NAMESPACE_URL,
            canonical_json(
                {"domain": "deeptwin-promotion-approval-v1", "command_id": command_id}
            ).decode(),
        )
    )


def _ref(value, kind, label) -> EntityRef:
    try:
        ref = EntityRef.from_dict(value)
    except DomainContractError:
        raise PromotionApprovalError(f"invalid {label}") from None
    if ref.kind != kind:
        raise PromotionApprovalError(f"invalid {label}")
    return ref


# the exact identities one approval binds (G-13): field name → entity kind
_BINDINGS = {
    "candidate_bundle": "environment",
    "validation_report": "validation_report",
    "expected_current_environment": "environment",
}
_CONTENT_KEYS = frozenset(
    {"schema_version", "decision", "command_id", "decided_at_utc", "event_sequence"}
    | set(_BINDINGS)
)


def _binding(ref: EntityRef) -> dict:
    """An exact identity stored as fields, not as a stored-record reference:
    bundle and report identities are content-derived and may precede their
    stored records, and the store verifies every exact reference it finds
    in record content against the vault."""

    return {"id": ref.id, "version": ref.version, "sha256": ref.sha256}


def _bound(kind: str, value) -> EntityRef:
    if type(value) is not dict or set(value) != {"id", "version", "sha256"}:
        raise PromotionApprovalError("unavailable")
    try:
        return EntityRef(kind=kind, **value)
    except DomainContractError:
        raise PromotionApprovalError("unavailable") from None


def _uuid(value, label) -> str:
    try:
        uuid_string(value)
    except (DomainContractError, TypeError, ValueError):
        raise PromotionApprovalError(f"invalid {label}") from None
    return value


def _validate_command(payload) -> dict:
    if type(payload) is not dict or set(payload) != {
        "schema_version",
        "command_id",
        "decision",
        *_BINDINGS,
    }:
        raise PromotionApprovalError("invalid command")
    if payload["schema_version"] != _SCHEMA:
        raise PromotionApprovalError("invalid schema version")
    if type(payload["decision"]) is not str or payload["decision"] not in DECISIONS:
        raise PromotionApprovalError("invalid decision")
    command = {
        "command_id": _uuid(payload["command_id"], "command id"),
        "decision": payload["decision"],
    }
    for name, kind in _BINDINGS.items():
        command[name] = _ref(payload[name], kind, name.replace("_", " "))
    return command


def _parse_content(content) -> dict:
    """Re-validate stored content with the writer's grammar: the record's
    schema label alone never makes it evidence."""

    if (
        type(content) is not dict
        or set(content) != _CONTENT_KEYS
        or content["schema_version"] != _RECORD_SCHEMA
        or type(content["decision"]) is not str
        or content["decision"] not in DECISIONS
        or type(content["decided_at_utc"]) is not str
        or _STAMP.fullmatch(content["decided_at_utc"]) is None
        or (
            content["event_sequence"] is not None
            and (
                type(content["event_sequence"]) is not int
                or content["event_sequence"] < 1
            )
        )
        or (content["event_sequence"] is None) != (content["decision"] == "defer")
    ):
        raise PromotionApprovalError("unavailable")
    try:
        command_id = _uuid(content["command_id"], "command id")
    except PromotionApprovalError:
        raise PromotionApprovalError("unavailable") from None
    parsed = {
        "decision": content["decision"],
        "command_id": command_id,
        "decided_at_utc": content["decided_at_utc"],
        "event_sequence": content["event_sequence"],
    }
    for name, kind in _BINDINGS.items():
        parsed[name] = _bound(kind, content[name])
    return parsed


class PersistentPromotionApprovals:
    """Writes and resolves owner promotion approvals over the exact bound store."""

    def __init__(self, domain_store, owner_authority):
        self._domain, self._owner = _bound_pair(
            domain_store, owner_authority, PromotionApprovalError
        )

    def _load(self, db, ref: EntityRef, roots) -> PromotionApproval:
        if ref.kind != "action_approval" or ref.version != 1:
            raise PromotionApprovalError("unavailable")
        body = self._domain._load(db, ref, roots)[0].body
        if _stored_owner_actor_ref(db) != body["actor_ref"]:
            # only records authored by the persistent owner's human actor
            # are promotion evidence
            raise PromotionApprovalError("unavailable")
        content = _parse_content(body["content"])
        if approval_identity(content["command_id"]) != ref.id:
            # the record identity is derived from the command it records
            raise PromotionApprovalError("unavailable")
        event_sequence = content.pop("event_sequence")
        if event_sequence is not None:
            event = db.execute(
                "SELECT event_type FROM api_event_envelopes WHERE vault_id=? AND sequence=?",
                (roots.genesis.id, event_sequence),
            ).fetchone()
            if event is None or event["event_type"] != "approval.decided":
                # an approve/reject names the decided event written with it
                raise PromotionApprovalError("unavailable")
        return _issue(
            **content,
            approval_ref=ref,
            actor_ref=EntityRef.from_dict(body["actor_ref"]),
        )

    def _existing(self, db, approval_id: str, roots) -> PromotionApproval | None:
        row = db.execute(
            "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
            "ORDER BY version DESC LIMIT 1",
            (roots.genesis.id, "action_approval", approval_id),
        ).fetchone()
        if row is None:
            return None
        if row["version"] != 1:
            raise PromotionApprovalError("unavailable")
        return self._load(
            db,
            EntityRef(
                kind="action_approval", id=approval_id, version=1, sha256=row["sha256"]
            ),
            roots,
        )

    @_closed
    def record(self, request, payload) -> PromotionApproval:
        # authentication first: an unauthenticated caller learns nothing
        # about the command grammar
        _authenticate_owner(self._owner, request)
        command = _validate_command(payload)
        approval_id = approval_identity(command["command_id"])
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            _assert_event_schema(db, roots.genesis.id)
            existing = self._existing(db, approval_id, roots)
            if existing is not None:
                if existing.decision != command["decision"] or any(
                    getattr(existing, name) != command[name] for name in _BINDINGS
                ):
                    raise PromotionApprovalError("conflict")
                return existing
            actor_ref = _owner_actor_ref(db, actor)
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
            event_decision = _EVENT_DECISION.get(command["decision"])
            event_sequence = (
                None
                if event_decision is None
                else _event_stream(db, roots.genesis.id)["next_sequence"]
            )
            content = {
                "schema_version": _RECORD_SCHEMA,
                **{name: _binding(command[name]) for name in _BINDINGS},
                "decision": command["decision"],
                "command_id": command["command_id"],
                "decided_at_utc": stamp,
                "event_sequence": event_sequence,
            }
            record = ImmutableRecord.create(
                kind="action_approval",
                id=approval_id,
                version=1,
                created_at_utc=stamp,
                actor_ref=actor_ref,
                parent_refs=(),
                purpose="operational",
                access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content=content,
            )
            self._domain._put_in_transaction(db, record)
            if event_decision is not None:
                event = _append_event_in_transaction(
                    db,
                    vault_id=roots.genesis.id,
                    recorded_at_utc=stamp,
                    observed_at_utc=stamp,
                    actor_kind="human",
                    actor_ref=actor_ref,
                    event_type="approval.decided",
                    object_refs=(),
                    correlation_id=command["command_id"],
                    causation_id=None,
                    status="succeeded",
                    error_code=None,
                    public_metadata={"decision": event_decision},
                    private_evidence_refs=(),
                    retention_class="core",
                    policy_ref=roots.access_policy,
                )
                if event.sequence != event_sequence:
                    raise PromotionApprovalError("unavailable")
            return _issue(
                **command,
                approval_ref=record.ref,
                actor_ref=actor_ref,
                decided_at_utc=stamp,
            )

    @_closed
    def resolve(self, ref) -> PromotionApproval:
        """The issued approval behind one exact `action_approval` reference."""

        if type(ref) is not EntityRef:
            raise PromotionApprovalError("unavailable")
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            return self._load(db, ref, roots)
