"""Owner-authorized run approvals: the real producer of `action_approval`
records that human gates consume (runtime.md §2 approval edges, §4
`awaiting_human`; FR-026 authenticated human approval).

The persistent owner session (Task 7) is the only authority: a POST with a
verified CSRF token and exact origin is re-authenticated with
`authenticate_bound` inside the final writer, and the approval is written
as one immutable `action_approval` record — content bound to the run,
gate node, scope, decision and command — with the owner's human actor as
its author, plus its `approval.decided` public event, in one transaction.
One decision exists per (run, node, scope): an exact replay of the same
command returns the same receipt, any other command or decision for the
same key conflicts, and nothing is ever overwritten. Readers resolve the
record through the store's exact reference; no caller-supplied boolean or
reference can stand in for it.

An owner recovery expires every still-pending gate request inside its one
reconciliation transaction (`expire_pending_in_transaction`): the same
record, decision `expired`, with `approval.decided(expired)`; the scheduler
reads any decision but `approved` as a refusal, and a later owner command
for that gate conflicts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import (
    _append_event_in_transaction,
    _assert_event_schema,
    _event_cursor_in_transaction,
    _event_stream,
)
from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.request_identity import AuthenticatedRequest
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from ..runtime.gates import (
    GATE_REQUEST_COMMAND,
    LOCAL,
    gate_request_identity,
    gate_request_recorded,
)
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority

__all__ = [
    "DECISIONS",
    "PersistentRunApprovals",
    "RunApproval",
    "RunApprovalError",
    "approval_identity",
    "expire_pending_in_transaction",
    "gate_request_identity",
]

DECISIONS = ("approved", "rejected")
_SCHEMA = "run-approval-command-v1"
_RECORD_SCHEMA = "run-approval-v1"
# one grammar for gate node ids and scopes, shared with the ledger's requests
_LOCAL = LOCAL


class RunApprovalError(ValueError):
    """invalid | conflict | unavailable — never a private storage detail."""


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (RunApprovalError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage errors must not disclose private detail
            raise RunApprovalError("unavailable") from None

    return invoke


def approval_identity(run_id: str, node_id: str, approval_scope: str) -> str:
    """The single record identity for one (run, gate node, scope) decision."""

    # canonical JSON keeps the components delimiter-proof ("a:b","c" ≠ "a","b:c")
    return str(
        uuid5(
            NAMESPACE_URL,
            canonical_json(
                {
                    "domain": "deeptwin-run-approval-v1",
                    "run_id": run_id,
                    "node_id": node_id,
                    "approval_scope": approval_scope,
                }
            ).decode(),
        )
    )


@dataclass(frozen=True, slots=True)
class RunApproval:
    run_id: str
    node_id: str
    approval_scope: str
    decision: str
    command_id: str
    approval_ref: EntityRef
    actor_ref: EntityRef


def _local(value, label) -> str:
    if type(value) is not str or _LOCAL.fullmatch(value) is None:
        raise RunApprovalError(f"invalid {label}")
    return value


def _uuid(value, label) -> str:
    try:
        uuid_string(value)
    except (DomainContractError, TypeError, ValueError):
        raise RunApprovalError(f"invalid {label}") from None
    return value


def _validate_command(payload) -> dict:
    if type(payload) is not dict or set(payload) != {
        "schema_version",
        "command_id",
        "run_id",
        "node_id",
        "approval_scope",
        "decision",
    }:
        raise RunApprovalError("invalid command")
    if payload["schema_version"] != _SCHEMA:
        raise RunApprovalError("invalid schema version")
    if payload["decision"] not in DECISIONS or type(payload["decision"]) is not str:
        raise RunApprovalError("invalid decision")
    return {
        "command_id": _uuid(payload["command_id"], "command id"),
        "run_id": _uuid(payload["run_id"], "run id"),
        "node_id": _local(payload["node_id"], "node id"),
        "approval_scope": _local(payload["approval_scope"], "approval scope"),
        "decision": payload["decision"],
    }


def _bound_pair(domain_store, owner_authority, error):
    if (
        type(domain_store) is not DomainStore
        or type(owner_authority) is not PersistentOwnerAuthority
        or owner_authority._domain is not domain_store
    ):
        raise error("unavailable")
    return domain_store, owner_authority


def _authenticate_owner(owner, request, db=None):
    """The owner's human actor for a CSRF-verified same-origin POST, re-checked
    against the live session (inside the writer when `db` is given)."""

    profile = owner.profile
    if (
        type(request) is not AuthenticatedRequest
        or request.method != "POST"
        or request.csrf_verified is not True
        or type(request.host) is not str
        or request.host != profile.http_origin.split("://", 1)[1]
        or request.origin != profile.http_origin
    ):
        raise OwnerAuthError("access_denied")
    actor = owner.authenticate_bound(request.session, db=db)
    if (
        actor is not request.session.actor
        or actor.kind != "human"
        or actor.origin != "local_session"
    ):
        raise OwnerAuthError("unauthenticated")
    return actor


def _owner_actor_ref(db, actor) -> EntityRef:
    account = db.execute(
        "SELECT actor_ref FROM owner_auth_accounts WHERE owner_id=?",
        (actor.id,),
    ).fetchone()
    if account is None:
        raise OwnerAuthError("unauthenticated")
    return EntityRef.from_dict(json.loads(account["actor_ref"]))


def _stored_owner_actor_ref(db) -> dict | None:
    account = db.execute("SELECT actor_ref FROM owner_auth_accounts").fetchone()
    return None if account is None else json.loads(account["actor_ref"])


def _write_decision(domain, db, roots, *, approval_id, run_id, node_id, approval_scope,
                    decision, command_id, actor_ref, stamp):
    """Seal one decision record and its `approval.decided` event in the caller's writer."""

    event_sequence = _event_stream(db, roots.genesis.id)["next_sequence"]
    content = {
        "schema_version": _RECORD_SCHEMA,
        "run_id": run_id,
        "node_id": node_id,
        "approval_scope": approval_scope,
        "decision": decision,
        "command_id": command_id,
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
    domain._put_in_transaction(db, record)
    event = _append_event_in_transaction(
        db,
        vault_id=roots.genesis.id,
        recorded_at_utc=stamp,
        observed_at_utc=stamp,
        actor_kind="human",
        actor_ref=actor_ref,
        event_type="approval.decided",
        object_refs=(),
        correlation_id=command_id,
        causation_id=None,
        status="succeeded",
        error_code=None,
        public_metadata={"decision": decision},
        private_evidence_refs=(),
        retention_class="core",
        policy_ref=roots.access_policy,
    )
    if event.sequence != event_sequence:
        raise RunApprovalError("unavailable")
    return record, event_sequence


def expire_pending_in_transaction(domain, db, roots, *, recovery_id: str, stamp: str) -> int:
    """Expire every gate request no decision answers yet, for one owner recovery.

    Runs inside the recovery reconciliation writer. Each request row is re-derived from
    its own payload; any row that does not reproduce its identity fails the whole
    reconciliation rather than being skipped.
    """

    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_commands'"
    ).fetchone()
    if table is None:
        return 0
    rows = list(db.execute(
        "SELECT command_id, payload FROM runtime_commands WHERE vault_id=? AND kind=? "
        "ORDER BY command_id",
        (roots.genesis.id, GATE_REQUEST_COMMAND),
    ))
    if not rows:
        return 0
    owner = _stored_owner_actor_ref(db)
    if owner is None:
        raise RunApprovalError("unavailable")  # a gate request implies an owner's consent
    actor_ref = EntityRef.from_dict(owner)
    expired = 0
    for row in rows:
        payload = json.loads(bytes(row["payload"]))
        if (
            type(payload) is not dict
            or set(payload) != {"run_id", "node_id", "approval_scope"}
            or gate_request_identity(
                payload["run_id"], payload["node_id"], payload["approval_scope"]
            ) != row["command_id"]
        ):
            raise RunApprovalError("unavailable")
        approval_id = approval_identity(
            payload["run_id"], payload["node_id"], payload["approval_scope"]
        )
        decided = db.execute(
            "SELECT 1 FROM domain_records WHERE vault_id=? AND kind='action_approval' AND id=?",
            (roots.genesis.id, approval_id),
        ).fetchone()
        if decided is not None:
            continue
        command_id = str(uuid5(NAMESPACE_URL, canonical_json({
            "domain": "deeptwin-recovery-approval-expiry-v1",
            "recovery_id": recovery_id,
            "approval_id": approval_id,
        }).decode()))
        _write_decision(
            domain, db, roots, approval_id=approval_id, run_id=payload["run_id"],
            node_id=payload["node_id"], approval_scope=payload["approval_scope"],
            decision="expired", command_id=command_id, actor_ref=actor_ref, stamp=stamp,
        )
        expired += 1
    return expired


class PersistentRunApprovals:
    """Writes and reads owner approvals over the exact bound store."""

    def __init__(self, domain_store, owner_authority):
        self._domain, self._owner = _bound_pair(
            domain_store, owner_authority, RunApprovalError
        )

    def _authenticate(self, request, db=None):
        return _authenticate_owner(self._owner, request, db)

    def _load(self, db, approval_id: str, roots) -> RunApproval | None:
        row = db.execute(
            "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
            "ORDER BY version DESC LIMIT 1",
            (roots.genesis.id, "action_approval", approval_id),
        ).fetchone()
        if row is None:
            return None
        if row["version"] != 1:
            # a decision is immutable: any later version is not this service's
            # record and is never trusted, whatever its content says
            raise RunApprovalError("unavailable")
        ref = EntityRef(
            kind="action_approval",
            id=approval_id,
            version=1,
            sha256=row["sha256"],
        )
        body = self._domain._load(db, ref, roots)[0].body
        content = body["content"]
        if content.get("schema_version") != _RECORD_SCHEMA:
            raise RunApprovalError("unavailable")
        if _stored_owner_actor_ref(db) != body["actor_ref"]:
            # only the persistent owner's human actor authors approvals
            raise RunApprovalError("unavailable")
        return RunApproval(
            run_id=content["run_id"],
            node_id=content["node_id"],
            approval_scope=content["approval_scope"],
            decision=content["decision"],
            command_id=content["command_id"],
            approval_ref=ref,
            actor_ref=EntityRef.from_dict(body["actor_ref"]),
        )

    def _receipt(self, db, roots, approval: RunApproval, event_sequence: int) -> dict:
        return {
            "command_id": approval.command_id,
            "state": "recorded",
            "decision": approval.decision,
            "approval_ref": approval.approval_ref.as_dict(),
            "event_cursor": _event_cursor_in_transaction(
                db, vault_id=roots.genesis.id, sequence=event_sequence, event_types=()
            ),
        }

    @_closed
    def record(self, request, payload) -> dict:
        # authentication first: an unauthenticated caller learns nothing
        # about the command grammar
        self._authenticate(request)
        command = _validate_command(payload)
        approval_id = approval_identity(
            command["run_id"], command["node_id"], command["approval_scope"]
        )
        with _writer(), self._domain._connection(write=True) as db:
            actor = self._authenticate(request, db)
            roots = self._domain._read_roots(db)
            _assert_event_schema(db, roots.genesis.id)
            existing = self._load(db, approval_id, roots)
            if existing is not None:
                if (
                    existing.command_id != command["command_id"]
                    or existing.decision != command["decision"]
                    or existing.run_id != command["run_id"]
                    or existing.node_id != command["node_id"]
                ):
                    raise RunApprovalError("conflict")
                stored = self._domain._load(db, existing.approval_ref, roots)[0].body
                return self._receipt(
                    db, roots, existing, stored["content"]["event_sequence"]
                )
            # an approval answers a gate some run's scheduler durably asked
            # for; nothing is recordable ahead of, or beside, that ask. The
            # ledger's command table lives in this same vault database (its
            # vault id is the genesis id); a vault without a ledger has no
            # table and fails closed as "unavailable".
            if not gate_request_recorded(
                db,
                roots.genesis.id,
                command["run_id"],
                command["node_id"],
                command["approval_scope"],
            ):
                raise RunApprovalError("invalid gate: no pending approval request")
            actor_ref = _owner_actor_ref(db, actor)
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
            record, event_sequence = _write_decision(
                self._domain, db, roots, approval_id=approval_id,
                run_id=command["run_id"], node_id=command["node_id"],
                approval_scope=command["approval_scope"], decision=command["decision"],
                command_id=command["command_id"], actor_ref=actor_ref, stamp=stamp,
            )
            approval = RunApproval(
                run_id=command["run_id"],
                node_id=command["node_id"],
                approval_scope=command["approval_scope"],
                decision=command["decision"],
                command_id=command["command_id"],
                approval_ref=record.ref,
                actor_ref=actor_ref,
            )
            return self._receipt(db, roots, approval, event_sequence)

    @_closed
    def lookup(
        self, run_id: str, node_id: str, approval_scope: str
    ) -> RunApproval | None:
        """The recorded decision for one gate scope, or None; never a default."""

        approval_id = approval_identity(
            _uuid(run_id, "run id"),
            _local(node_id, "node id"),
            _local(approval_scope, "approval scope"),
        )
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            found = self._load(db, approval_id, roots)
        if found is not None and (
            found.run_id != run_id
            or found.node_id != node_id
            or found.approval_scope != approval_scope
        ):
            raise RunApprovalError("unavailable")
        return found
