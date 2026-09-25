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

Two record versions exist. `run-approval-v1` binds (run, gate node, scope)
and is what a human gate's passage consults; it stays readable, but it names
no execution, so it can never authorize a tool call's dispatch. A
`run-approval-v2` decision additionally binds the exact execution it
authorizes as the ledger names it — the execution (the node visit) id, the
executing node and the attempt number — under its own identity, so one
decision authorizes one attempt of one visit and nothing else: never another
visit (a later loop round, another node's execution) and never a retry
attempt. Both are recordable only against a gate request the ledger holds.

An owner recovery ends every earlier authority inside its one reconciliation
transaction. `expire_pending_in_transaction` expires every gate request no
v1 decision answers yet: the v1 record, decision `expired`, with
`approval.decided(expired)`; the scheduler reads any decision but `approved`
as a refusal, and a later v1 owner command for that gate conflicts. A v1
decision already recorded before the recovery stays historical gate evidence
(the scheduler replays it; it authorizes no dispatch). A v2 decision is a
forward-looking authorization of one dispatch, so it cannot outlive the
authority that made it: a v2 record whose `approval.decided` event precedes
the latest `auth.recovery_completed` event is superseded — `lookup_execution`
and `resolve` refuse it with `RunApprovalError("superseded")` and every
dispatcher fails closed. The record itself is never rewritten.
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
from ..runtime.ledger import MAX_ATTEMPTS_PER_EXECUTION
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority

__all__ = [
    "DECISIONS",
    "PersistentRunApprovals",
    "RunApproval",
    "RunApprovalError",
    "approval_identity",
    "execution_approval_identity",
    "expire_pending_in_transaction",
    "gate_request_identity",
]

DECISIONS = ("approved", "rejected")
_SCHEMA = "run-approval-command-v1"
_RECORD_SCHEMA = "run-approval-v1"
# the execution-bound version: the command and the record name the execution
_SCHEMA_V2 = "run-approval-command-v2"
_RECORD_SCHEMA_V2 = "run-approval-v2"
_EXECUTION_FIELDS = ("execution_id", "execution_node_id", "attempt_no")
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


def execution_approval_identity(
    run_id: str, node_id: str, approval_scope: str, execution_id: str,
    execution_node_id: str, attempt_no: int,
) -> str:
    """The single record identity for one execution-bound decision: the gate's
    (run, node, scope) plus the execution, its node and the attempt number.
    A namespace of its own, so it never collides with a v1 identity."""

    return str(
        uuid5(
            NAMESPACE_URL,
            canonical_json(
                {
                    "domain": "deeptwin-run-approval-v2",
                    "run_id": run_id,
                    "node_id": node_id,
                    "approval_scope": approval_scope,
                    "execution_id": execution_id,
                    "execution_node_id": execution_node_id,
                    "attempt_no": attempt_no,
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
    # the record version, and for v2 the execution the decision authorizes
    schema_version: str = _RECORD_SCHEMA
    execution_id: str | None = None
    execution_node_id: str | None = None
    attempt_no: int | None = None

    @property
    def execution_bound(self) -> bool:
        return self.schema_version == _RECORD_SCHEMA_V2


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


def _attempt_no(value) -> int:
    if type(value) is not int or not 1 <= value <= MAX_ATTEMPTS_PER_EXECUTION:
        raise RunApprovalError("invalid attempt number")
    return value


_V1_FIELDS = frozenset({"schema_version", "command_id", "run_id", "node_id", "approval_scope", "decision"})


def _validate_command(payload) -> dict:
    if type(payload) is not dict or "schema_version" not in payload:
        raise RunApprovalError("invalid command")
    version = payload["schema_version"]
    if type(version) is not str or version not in (_SCHEMA, _SCHEMA_V2):
        if set(payload) not in (_V1_FIELDS, _V1_FIELDS | set(_EXECUTION_FIELDS)):
            raise RunApprovalError("invalid command")
        raise RunApprovalError("invalid schema version")
    expected = _V1_FIELDS if version == _SCHEMA else _V1_FIELDS | set(_EXECUTION_FIELDS)
    if set(payload) != expected:
        raise RunApprovalError("invalid command")
    if payload["decision"] not in DECISIONS or type(payload["decision"]) is not str:
        raise RunApprovalError("invalid decision")
    command = {
        "command_id": _uuid(payload["command_id"], "command id"),
        "run_id": _uuid(payload["run_id"], "run id"),
        "node_id": _local(payload["node_id"], "node id"),
        "approval_scope": _local(payload["approval_scope"], "approval scope"),
        "decision": payload["decision"],
    }
    if version == _SCHEMA_V2:
        command.update({
            "execution_id": _uuid(payload["execution_id"], "execution id"),
            "execution_node_id": _local(payload["execution_node_id"], "execution node id"),
            "attempt_no": _attempt_no(payload["attempt_no"]),
        })
    return command


def _command_identity(command: dict) -> str:
    if "execution_id" in command:
        return execution_approval_identity(
            command["run_id"], command["node_id"], command["approval_scope"],
            command["execution_id"], command["execution_node_id"], command["attempt_no"],
        )
    return approval_identity(command["run_id"], command["node_id"], command["approval_scope"])


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
                    decision, command_id, actor_ref, stamp, execution=None):
    """Seal one decision record and its `approval.decided` event in the caller's writer.
    `execution` (the three execution fields) makes it a v2 record; None a v1 record."""

    event_sequence = _event_stream(db, roots.genesis.id)["next_sequence"]
    content = {
        "schema_version": _RECORD_SCHEMA if execution is None else _RECORD_SCHEMA_V2,
        "run_id": run_id,
        "node_id": node_id,
        "approval_scope": approval_scope,
        "decision": decision,
        "command_id": command_id,
        "decided_at_utc": stamp,
        "event_sequence": event_sequence,
    }
    if execution is not None:
        content.update({name: execution[name] for name in _EXECUTION_FIELDS})
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


def _recovery_barrier(db, vault_id) -> int | None:
    """The event sequence before which every v2 decision is superseded by an owner
    recovery, or None when this vault never recovered. Fails closed: when the latest
    `auth.recovery_completed` envelope is no longer held, the first sequence the stream
    still holds is the barrier (everything older is treated as pre-recovery)."""

    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='owner_auth_control'"
    ).fetchone()
    if table is None:
        return None
    recovered = db.execute(
        "SELECT 1 FROM owner_auth_control WHERE recovery_request_id IS NOT NULL LIMIT 1"
    ).fetchone()
    if recovered is None:
        return None
    row = db.execute(
        "SELECT MAX(sequence) AS sequence FROM api_event_envelopes WHERE vault_id=? AND event_type=?",
        (vault_id, "auth.recovery_completed"),
    ).fetchone()
    if row is not None and type(row["sequence"]) is int:
        return row["sequence"]
    return _event_stream(db, vault_id)["first_available_sequence"]


def _require_current(domain, db, roots, found: RunApproval) -> RunApproval:
    """A v2 decision recorded before the latest owner recovery authorizes nothing."""

    if not found.execution_bound:
        return found
    barrier = _recovery_barrier(db, roots.genesis.id)
    if barrier is None:
        return found
    sequence = domain._load(db, found.approval_ref, roots)[0].body["content"].get("event_sequence")
    if type(sequence) is not int or sequence < barrier:
        raise RunApprovalError("superseded")
    return found


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
        version = content.get("schema_version")
        if version not in (_RECORD_SCHEMA, _RECORD_SCHEMA_V2):
            raise RunApprovalError("unavailable")
        if _stored_owner_actor_ref(db) != body["actor_ref"]:
            # only the persistent owner's human actor authors approvals
            raise RunApprovalError("unavailable")
        bound = dict.fromkeys(_EXECUTION_FIELDS)
        if version == _RECORD_SCHEMA_V2:
            bound = {name: content.get(name) for name in _EXECUTION_FIELDS}
            try:
                _uuid(bound["execution_id"], "execution id")
                _local(bound["execution_node_id"], "execution node id")
                _attempt_no(bound["attempt_no"])
            except RunApprovalError:
                raise RunApprovalError("unavailable") from None
        elif any(name in content for name in _EXECUTION_FIELDS):
            raise RunApprovalError("unavailable")  # a v1 record never carries a binding
        return RunApproval(
            run_id=content["run_id"],
            node_id=content["node_id"],
            approval_scope=content["approval_scope"],
            decision=content["decision"],
            command_id=content["command_id"],
            approval_ref=ref,
            actor_ref=EntityRef.from_dict(body["actor_ref"]),
            schema_version=version,
            **bound,
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
        approval_id = _command_identity(command)
        record_schema = _RECORD_SCHEMA_V2 if "execution_id" in command else _RECORD_SCHEMA
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
                    or existing.schema_version != record_schema
                    or any(getattr(existing, name) != command.get(name)
                           for name in _EXECUTION_FIELDS)
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
                execution=command if record_schema == _RECORD_SCHEMA_V2 else None,
            )
            approval = RunApproval(
                run_id=command["run_id"],
                node_id=command["node_id"],
                approval_scope=command["approval_scope"],
                decision=command["decision"],
                command_id=command["command_id"],
                approval_ref=record.ref,
                actor_ref=actor_ref,
                schema_version=record_schema,
                **{name: command.get(name) for name in _EXECUTION_FIELDS},
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
            or found.execution_bound
        ):
            raise RunApprovalError("unavailable")
        return found

    @_closed
    def lookup_execution(
        self, run_id: str, node_id: str, approval_scope: str, *, execution_id: str,
        execution_node_id: str, attempt_no: int,
    ) -> RunApproval | None:
        """The recorded execution-bound (v2) decision for one gate scope and one
        attempt of one execution, or None; a v1 decision is never returned here."""

        approval_id = execution_approval_identity(
            _uuid(run_id, "run id"),
            _local(node_id, "node id"),
            _local(approval_scope, "approval scope"),
            _uuid(execution_id, "execution id"),
            _local(execution_node_id, "execution node id"),
            _attempt_no(attempt_no),
        )
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            found = self._load(db, approval_id, roots)
            if found is not None:
                _require_current(self._domain, db, roots, found)
        if found is not None and (
            not found.execution_bound
            or (found.run_id, found.node_id, found.approval_scope) != (run_id, node_id, approval_scope)
            or (found.execution_id, found.execution_node_id, found.attempt_no)
            != (execution_id, execution_node_id, attempt_no)
        ):
            raise RunApprovalError("unavailable")
        return found

    @_closed
    def resolve(self, approval_ref) -> RunApproval | None:
        """The decision an exact `action_approval` reference names (either
        version), or None when no record of this service is exactly that ref."""

        if type(approval_ref) is not EntityRef or approval_ref.kind != "action_approval":
            raise RunApprovalError("invalid approval reference")
        _uuid(approval_ref.id, "approval id")
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            found = self._load(db, approval_ref.id, roots)
            if found is None or found.approval_ref != approval_ref:
                return None
            _require_current(self._domain, db, roots, found)
        bound = ({name: getattr(found, name) for name in _EXECUTION_FIELDS}
                 if found.execution_bound else {})
        if found.approval_ref.id != _command_identity({
            "run_id": found.run_id, "node_id": found.node_id,
            "approval_scope": found.approval_scope, **bound,
        }):
            raise RunApprovalError("unavailable")  # a record under another decision's identity
        return found
