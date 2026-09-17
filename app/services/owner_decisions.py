"""Owner decisions over an exact subject digest — the shared producer of
`action_approval` evidence for value-level human approvals that are neither
run gates (`run_approvals`) nor promotions (`promotion_approvals`).

A consumer (first: design approval, environments.py / FR-008) derives the
exact subject the human sees as a JSON object that contains no stored-record
reference, and the persistent owner session records one immutable
`action_approval` per command holding the closed subject kind, that subject
verbatim, its canonical SHA-256, the decision and the command — authored by
the owner's human actor, with its `approval.decided` public event in the
same transaction. Exact replay returns the same issued value, any other
body under the same command conflicts, nothing is overwritten. The consumer
accepts only an issued value whose kind and subject equal what it computes
itself; no caller-declared boolean stands in for it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from types import MappingProxyType
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import (
    _append_event_in_transaction,
    _assert_event_schema,
    _event_stream,
)
from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import _BLOB_KEYS, _writer
from .owner_auth import OwnerAuthError
from .run_approvals import (
    _authenticate_owner,
    _bound_pair,
    _owner_actor_ref,
    _stored_owner_actor_ref,
)

SUBJECT_KINDS = ("design_approval", "deletion")
DECISIONS = ("approve", "reject")
_EVENT_DECISION = {"approve": "approved", "reject": "rejected"}
_SCHEMA = "owner-decision-command-v1"
_RECORD_SCHEMA = "owner-decision-v1"
_CONTENT_KEYS = frozenset(
    {
        "schema_version",
        "subject_kind",
        "subject",
        "subject_sha256",
        "decision",
        "command_id",
        "decided_at_utc",
        "event_sequence",
    }
)
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_REF_KEYS = frozenset({"kind", "id", "version", "sha256"})
_SUBJECT_MAX_BYTES = 65_536
_SUBJECT_MAX_DEPTH = 8
_ISSUE_TOKEN = object()


class OwnerDecisionError(ValueError):
    """invalid | conflict | unavailable — never a private storage detail."""


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (OwnerDecisionError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose private detail
            raise OwnerDecisionError("unavailable") from None

    return invoke


@dataclass(frozen=True, slots=True, init=False)
class OwnerDecision:
    """One owner-recorded decision over one exact subject, issued here only."""

    subject_kind: str
    subject: Mapping  # read-only view; equal to the plain dict it copies
    subject_sha256: str
    decision: str
    command_id: str
    approval_ref: EntityRef
    actor_ref: EntityRef
    decided_at_utc: str
    _issuer_token: object = field(repr=False, compare=False)


def is_issued_owner_decision(value) -> bool:
    return (
        type(value) is OwnerDecision
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def _issue(**fields) -> OwnerDecision:
    value = object.__new__(OwnerDecision)
    for name, item in fields.items():
        if name == "subject":
            item = MappingProxyType(deepcopy(item))
        object.__setattr__(value, name, item)
    object.__setattr__(value, "_issuer_token", _ISSUE_TOKEN)
    return value


def decision_identity(command_id: str) -> str:
    """One record per command: replay is exact, every other body conflicts."""

    return str(
        uuid5(
            NAMESPACE_URL,
            canonical_json(
                {"domain": "deeptwin-owner-decision-v1", "command_id": command_id}
            ).decode(),
        )
    )


def subject_digest(subject: dict) -> str:
    return sha256(canonical_json(subject)).hexdigest()


def _check_subject(value, depth=0) -> None:
    """A subject is plain JSON data: the store must never read a stored-record
    or blob reference (`_references` shapes) or a reserved `*_ref(s)` field
    out of it, and it stays bounded. This is the sole gate — the store's own
    reference scan must never be what refuses a subject."""

    if depth > _SUBJECT_MAX_DEPTH:
        raise OwnerDecisionError("invalid subject")
    if type(value) is dict:
        if _REF_KEYS <= set(value) or _BLOB_KEYS <= set(value):
            raise OwnerDecisionError("invalid subject")
        for name, child in value.items():
            if type(name) is not str or name.endswith(("_ref", "_refs")):
                raise OwnerDecisionError("invalid subject")
            _check_subject(child, depth + 1)
    elif type(value) is list:
        for child in value:
            _check_subject(child, depth + 1)
    elif type(value) not in (str, int, bool) and value is not None:
        # canonical JSON carries no floats (decimals travel as strings)
        raise OwnerDecisionError("invalid subject")


def _validate_subject(value) -> dict:
    if type(value) is not dict or not value:
        raise OwnerDecisionError("invalid subject")
    _check_subject(value)
    try:
        if len(canonical_json(value)) > _SUBJECT_MAX_BYTES:
            raise OwnerDecisionError("invalid subject")
    except (DomainContractError, TypeError, ValueError):
        raise OwnerDecisionError("invalid subject") from None
    return deepcopy(value)


def _uuid(value, label) -> str:
    try:
        uuid_string(value)
    except (DomainContractError, TypeError, ValueError):
        raise OwnerDecisionError(f"invalid {label}") from None
    return value


def _validate_command(payload) -> dict:
    if type(payload) is not dict or set(payload) != {
        "schema_version",
        "command_id",
        "subject_kind",
        "subject",
        "decision",
    }:
        raise OwnerDecisionError("invalid command")
    if payload["schema_version"] != _SCHEMA:
        raise OwnerDecisionError("invalid schema version")
    if (
        type(payload["subject_kind"]) is not str
        or payload["subject_kind"] not in SUBJECT_KINDS
    ):
        raise OwnerDecisionError("invalid subject kind")
    if type(payload["decision"]) is not str or payload["decision"] not in DECISIONS:
        raise OwnerDecisionError("invalid decision")
    subject = _validate_subject(payload["subject"])
    return {
        "command_id": _uuid(payload["command_id"], "command id"),
        "subject_kind": payload["subject_kind"],
        "subject": subject,
        "subject_sha256": subject_digest(subject),
        "decision": payload["decision"],
    }


def _parse_content(content) -> dict:
    """Re-validate stored content with the writer's grammar."""

    try:
        if (
            type(content) is not dict
            or set(content) != _CONTENT_KEYS
            or content["schema_version"] != _RECORD_SCHEMA
            or content["subject_kind"] not in SUBJECT_KINDS
            or content["decision"] not in DECISIONS
            or type(content["decided_at_utc"]) is not str
            or _STAMP.fullmatch(content["decided_at_utc"]) is None
            or type(content["event_sequence"]) is not int
            or content["event_sequence"] < 1
        ):
            raise OwnerDecisionError("unavailable")
        subject = _validate_subject(content["subject"])
        if content["subject_sha256"] != subject_digest(subject):
            raise OwnerDecisionError("unavailable")
        command_id = _uuid(content["command_id"], "command id")
    except OwnerDecisionError:
        raise OwnerDecisionError("unavailable") from None
    return {
        "subject_kind": content["subject_kind"],
        "subject": subject,
        "subject_sha256": content["subject_sha256"],
        "decision": content["decision"],
        "command_id": command_id,
        "decided_at_utc": content["decided_at_utc"],
        "event_sequence": content["event_sequence"],
    }


class PersistentOwnerDecisions:
    """Writes and resolves owner decisions over the exact bound store."""

    def __init__(self, domain_store, owner_authority):
        self._domain, self._owner = _bound_pair(
            domain_store, owner_authority, OwnerDecisionError
        )

    def _load(self, db, ref: EntityRef, roots) -> OwnerDecision:
        if ref.kind != "action_approval" or ref.version != 1:
            raise OwnerDecisionError("unavailable")
        body = self._domain._load(db, ref, roots)[0].body
        if _stored_owner_actor_ref(db) != body["actor_ref"]:
            # only records authored by the persistent owner's human actor
            # are decision evidence
            raise OwnerDecisionError("unavailable")
        content = _parse_content(body["content"])
        if decision_identity(content["command_id"]) != ref.id:
            raise OwnerDecisionError("unavailable")
        event_sequence = content.pop("event_sequence")
        event = db.execute(
            "SELECT event_type, envelope FROM api_event_envelopes "
            "WHERE vault_id=? AND sequence=?",
            (roots.genesis.id, event_sequence),
        ).fetchone()
        if (
            event is None
            or event["event_type"] != "approval.decided"
            or json.loads(event["envelope"]).get("correlation_id")
            != content["command_id"]
        ):
            # the named event is the decided event of this very command
            raise OwnerDecisionError("unavailable")
        return _issue(
            **content,
            approval_ref=ref,
            actor_ref=EntityRef.from_dict(body["actor_ref"]),
        )

    def _existing(self, db, decision_id: str, roots) -> OwnerDecision | None:
        row = db.execute(
            "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
            "ORDER BY version DESC LIMIT 1",
            (roots.genesis.id, "action_approval", decision_id),
        ).fetchone()
        if row is None:
            return None
        if row["version"] != 1:
            raise OwnerDecisionError("unavailable")
        return self._load(
            db,
            EntityRef(
                kind="action_approval", id=decision_id, version=1, sha256=row["sha256"]
            ),
            roots,
        )

    @_closed
    def record(self, request, payload) -> OwnerDecision:
        # authentication first: an unauthenticated caller learns nothing
        # about the command grammar
        _authenticate_owner(self._owner, request)
        command = _validate_command(payload)
        decision_id = decision_identity(command["command_id"])
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            _assert_event_schema(db, roots.genesis.id)
            existing = self._existing(db, decision_id, roots)
            if existing is not None:
                if (
                    existing.decision != command["decision"]
                    or existing.subject_kind != command["subject_kind"]
                    or existing.subject_sha256 != command["subject_sha256"]
                ):
                    raise OwnerDecisionError("conflict")
                return existing
            actor_ref = _owner_actor_ref(db, actor)
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
            event_sequence = _event_stream(db, roots.genesis.id)["next_sequence"]
            content = {
                "schema_version": _RECORD_SCHEMA,
                **command,
                "decided_at_utc": stamp,
                "event_sequence": event_sequence,
            }
            record = ImmutableRecord.create(
                kind="action_approval",
                id=decision_id,
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
                public_metadata={"decision": _EVENT_DECISION[command["decision"]]},
                private_evidence_refs=(),
                retention_class="core",
                policy_ref=roots.access_policy,
            )
            if event.sequence != event_sequence:
                raise OwnerDecisionError("unavailable")
            return _issue(
                **command,
                approval_ref=record.ref,
                actor_ref=actor_ref,
                decided_at_utc=stamp,
            )

    @_closed
    def resolve(self, ref) -> OwnerDecision:
        """The issued decision behind one exact `action_approval` reference."""

        if type(ref) is not EntityRef:
            raise OwnerDecisionError("unavailable")
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            return self._load(db, ref, roots)
