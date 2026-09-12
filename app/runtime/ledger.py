"""Durable runtime control ledger for an initialized local domain vault.

This module owns persistence and integrity only.  It deliberately does not turn a
stored consent, actor, lease, or immutable reference into authorization.  Callers
must pass the permission gate before reserving; only the budget-coupled commit can
produce the one-shot permit accepted by the production dispatch boundary.

The ledger never calls a provider, kills a process, replays a checkpoint, releases
a budget reservation, or redispatches work.  A committed send intent means only
that transfer may have started; restart handling is conservative by construction.
"""

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from hashlib import sha256
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
import time
from uuid import uuid4

from ..domain.events import event_metadata
from ..domain.permissions import Grant, Principal
from ..domain.refs import (
    DomainContractError,
    EntityRef,
    MAX_INTEGER,
    ObjectRef,
    canonical_json,
    parse_canonical,
    positive_integer,
    uuid_string,
)
from ..domain.store import DomainStore, StorageError, _writer
from .budgets import BudgetBook, BudgetDispatchRequest


MAX_LEASE_MS = 86_400_000
MAX_ACTIVE_ATTEMPTS = 1_000
MAX_ATTEMPTS_PER_EXECUTION = 1_000
MAX_CHECKPOINT_BYTES = 1_048_576
MAX_CHECKPOINT_NAMESPACES = 128
MAX_RESULT_OBSERVATIONS = 1_000
MAX_PAGE = 1_000
MAX_NODE_ID_BYTES = 256
MAX_IDEMPOTENCY_KEY_BYTES = 512

RUN_MODES = frozenset({"live", "replay", "snapshot", "isolated-comparison"})
PHASES = frozenset({
    "reserved", "preflighting", "awaiting_human", "send_intent",
    "running", "validating", "terminal",
})
ACTIVE_PHASES = PHASES - {"terminal"}
TERMINAL_OUTCOMES = frozenset({
    "succeeded", "failed", "denied", "timed_out", "cancelled", "outcome_unknown",
})
SEND_FINALITIES = frozenset({
    "not_started", "may_have_started", "transport_accepted",
    "definitely_not_sent", "remote_terminal",
})
REMOTE_TERMINALS = TERMINAL_OUTCOMES | frozenset({"not_observed"})
USAGE_FINALITIES = frozenset({"final", "provisional", "unknown"})
RESULT_REASONS = frozenset({
    "provider_terminal", "validation_failed", "permission_denied", "deadline",
    "transport_failure", "transport_unknown", "cancel_requested",
    "restart_reconciliation",
})
JOURNAL_TRANSITIONS = frozenset({
    "reserved", "preflighting", "awaiting_human", "send_intent", "running",
    "validating", "lease_renewed", "cancel_requested", "cancel_terminal",
    "result_accepted", "result_duplicate", "result_late", "recovery_pending",
    "recovery_terminal", "transport_observed",
})

TRANSPORT_EFFECTS = frozenset({
    "definitely_not_sent", "may_have_started", "outcome_unknown",
    "transport_accepted",
})
_TRANSPORT_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_TRANSPORT_MESSAGE_TYPE = re.compile(
    r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class LedgerError(ValueError):
    pass


class CorruptLedger(LedgerError):
    """Persisted runtime state failed validation and cannot authorize dispatch."""


class CommandConflict(LedgerError):
    pass


class IdempotencyConflict(LedgerError):
    pass


class ResultConflict(LedgerError):
    pass


class RevisionConflict(LedgerError):
    pass


class InvalidTransition(LedgerError):
    pass


class LeaseOwnershipError(LedgerError):
    pass


class LeaseExpired(LedgerError):
    pass


class DispatchBlocked(LedgerError):
    pass


class StartupReconciliationRequired(DispatchBlocked):
    pass


class ClockError(LedgerError):
    pass


def _ref(value, kind):
    if type(value) is not EntityRef or value.kind != kind:
        raise DomainContractError(f"Expected exact {kind} EntityRef")
    return value


def _nonnegative(name, value):
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise ValueError(f"{name} must be a bounded nonnegative integer")
    return value


def _bounded_positive(name, value, maximum=MAX_INTEGER):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be a bounded positive integer")
    return value


def _bounded_text(name, value, maximum, *, pattern=None):
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be nonempty text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} contains invalid Unicode") from exc
    if size > maximum or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{name} is invalid or exceeds its byte limit")
    if pattern is not None and re.fullmatch(pattern, value) is None:
        raise ValueError(f"{name} has an invalid format")
    return value


def _strict_dict(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise CorruptLedger(f"Persisted {label} has unexpected fields")
    return value


def _blob(value, label):
    if type(value) not in (bytes, bytearray, memoryview):
        raise CorruptLedger(f"Persisted {label} is not bytes")
    return bytes(value)


def _digest(data):
    return sha256(data).hexdigest()


def _decode_canonical(data, digest, label):
    encoded = _blob(data, label)
    if type(digest) is not str or _digest(encoded) != digest:
        raise CorruptLedger(f"Persisted {label} digest mismatch")
    try:
        return parse_canonical(encoded)
    except DomainContractError as exc:
        raise CorruptLedger(f"Persisted {label} is not canonical") from exc


@dataclass(frozen=True, slots=True)
class RunSpec:
    run_id: str
    work_revision_ref: EntityRef
    environment_ref: EntityRef
    consent_ref: EntityRef
    mode: str
    budget_policy_ref: EntityRef
    budget_session_id: str
    manifest_ref: EntityRef

    def __post_init__(self):
        uuid_string(self.run_id)
        _ref(self.work_revision_ref, "work_revision")
        _ref(self.environment_ref, "environment")
        _ref(self.consent_ref, "run_consent")
        if type(self.mode) is not str or self.mode not in RUN_MODES:
            raise DomainContractError("Invalid run mode")
        _ref(self.budget_policy_ref, "budget_policy")
        uuid_string(self.budget_session_id)
        _ref(self.manifest_ref, "run_manifest")

    def as_dict(self):
        return {
            "run_id": self.run_id,
            "work_revision_ref": self.work_revision_ref.as_dict(),
            "environment_ref": self.environment_ref.as_dict(),
            "consent_ref": self.consent_ref.as_dict(),
            "mode": self.mode,
            "budget_policy_ref": self.budget_policy_ref.as_dict(),
            "budget_session_id": self.budget_session_id,
            "manifest_ref": self.manifest_ref.as_dict(),
        }

    @classmethod
    def from_dict(cls, value):
        fields = ("run_id", "work_revision_ref", "environment_ref", "consent_ref",
                  "mode", "budget_policy_ref", "budget_session_id", "manifest_ref")
        value = _strict_dict(value, fields, "run spec")
        try:
            return cls(value["run_id"], EntityRef.from_dict(value["work_revision_ref"]),
                       EntityRef.from_dict(value["environment_ref"]),
                       EntityRef.from_dict(value["consent_ref"]), value["mode"],
                       EntityRef.from_dict(value["budget_policy_ref"]),
                       value["budget_session_id"],
                       EntityRef.from_dict(value["manifest_ref"]))
        except (DomainContractError, TypeError, ValueError) as exc:
            raise CorruptLedger("Persisted run spec is invalid") from exc


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    execution_id: str
    run_id: str
    node_id: str
    visit_id: str
    loop_indices: tuple[int, ...]
    parent_execution_ids: tuple[str, ...]

    def __post_init__(self):
        uuid_string(self.execution_id)
        uuid_string(self.run_id)
        _bounded_text("node_id", self.node_id, MAX_NODE_ID_BYTES,
                      pattern=r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
        uuid_string(self.visit_id)
        if (type(self.loop_indices) is not tuple or len(self.loop_indices) > 32
                or any(type(value) is not int or not 0 <= value <= MAX_INTEGER
                       for value in self.loop_indices)):
            raise DomainContractError("Loop indices must be a bounded immutable sequence")
        if (type(self.parent_execution_ids) is not tuple
                or len(self.parent_execution_ids) > 256
                or len(set(self.parent_execution_ids)) != len(self.parent_execution_ids)):
            raise DomainContractError("Parent executions must be bounded and unique")
        for value in self.parent_execution_ids:
            uuid_string(value)

    def as_dict(self):
        return {
            "execution_id": self.execution_id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "visit_id": self.visit_id,
            "loop_indices": list(self.loop_indices),
            "parent_execution_ids": list(self.parent_execution_ids),
        }

    @classmethod
    def from_dict(cls, value):
        fields = ("execution_id", "run_id", "node_id", "visit_id", "loop_indices",
                  "parent_execution_ids")
        value = _strict_dict(value, fields, "execution spec")
        try:
            if type(value["loop_indices"]) is not list or type(value["parent_execution_ids"]) is not list:
                raise DomainContractError("Persisted execution sequences must be arrays")
            return cls(value["execution_id"], value["run_id"], value["node_id"],
                       value["visit_id"], tuple(value["loop_indices"]),
                       tuple(value["parent_execution_ids"]))
        except (DomainContractError, TypeError, ValueError) as exc:
            raise CorruptLedger("Persisted execution spec is invalid") from exc


@dataclass(frozen=True, slots=True)
class OwnerIdentity:
    owner_id: str
    pid: int
    process_started_at_ms: int
    nonce: str

    def __post_init__(self):
        uuid_string(self.owner_id)
        _bounded_positive("pid", self.pid)
        _nonnegative("process_started_at_ms", self.process_started_at_ms)
        uuid_string(self.nonce)

    def as_dict(self):
        return {
            "owner_id": self.owner_id,
            "pid": self.pid,
            "process_started_at_ms": self.process_started_at_ms,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, value):
        fields = ("owner_id", "pid", "process_started_at_ms", "nonce")
        value = _strict_dict(value, fields, "owner identity")
        try:
            return cls(**value)
        except (DomainContractError, TypeError, ValueError) as exc:
            raise CorruptLedger("Persisted owner identity is invalid") from exc


@dataclass(frozen=True, slots=True)
class AttemptSpec:
    attempt_id: str
    execution_id: str
    attempt_no: int
    envelope_ref: EntityRef
    profile_ref: EntityRef
    budget_policy_ref: EntityRef
    reservation_id: str
    idempotency_key: str
    owner: OwnerIdentity
    deadline_at_ms: int

    def __post_init__(self):
        uuid_string(self.attempt_id)
        uuid_string(self.execution_id)
        _bounded_positive("attempt_no", self.attempt_no, MAX_ATTEMPTS_PER_EXECUTION)
        _ref(self.envelope_ref, "execution_envelope")
        _ref(self.profile_ref, "runtime_profile")
        _ref(self.budget_policy_ref, "budget_policy")
        uuid_string(self.reservation_id)
        _bounded_text("idempotency_key", self.idempotency_key, MAX_IDEMPOTENCY_KEY_BYTES)
        if type(self.owner) is not OwnerIdentity:
            raise DomainContractError("Attempt owner must be an exact OwnerIdentity")
        _bounded_positive("deadline_at_ms", self.deadline_at_ms)

    def as_dict(self):
        return {
            "attempt_id": self.attempt_id,
            "execution_id": self.execution_id,
            "attempt_no": self.attempt_no,
            "envelope_ref": self.envelope_ref.as_dict(),
            "profile_ref": self.profile_ref.as_dict(),
            "budget_policy_ref": self.budget_policy_ref.as_dict(),
            "reservation_id": self.reservation_id,
            "idempotency_key": self.idempotency_key,
            "owner": self.owner.as_dict(),
            "deadline_at_ms": self.deadline_at_ms,
        }

    @classmethod
    def from_dict(cls, value):
        fields = ("attempt_id", "execution_id", "attempt_no", "envelope_ref", "profile_ref",
                  "budget_policy_ref", "reservation_id", "idempotency_key", "owner",
                  "deadline_at_ms")
        value = _strict_dict(value, fields, "attempt spec")
        try:
            return cls(value["attempt_id"], value["execution_id"], value["attempt_no"],
                       EntityRef.from_dict(value["envelope_ref"]),
                       EntityRef.from_dict(value["profile_ref"]),
                       EntityRef.from_dict(value["budget_policy_ref"]),
                       value["reservation_id"], value["idempotency_key"],
                       OwnerIdentity.from_dict(value["owner"]), value["deadline_at_ms"])
        except (DomainContractError, TypeError, ValueError) as exc:
            if isinstance(exc, CorruptLedger):
                raise
            raise CorruptLedger("Persisted attempt spec is invalid") from exc


@dataclass(frozen=True, slots=True)
class ResultObservation:
    observation_id: str
    attempt_id: str
    outcome: str
    result_ref: EntityRef | None
    usage_finality: str
    remote_terminal_observed: str
    reason_code: str

    def __post_init__(self):
        uuid_string(self.observation_id)
        uuid_string(self.attempt_id)
        if type(self.outcome) is not str or self.outcome not in TERMINAL_OUTCOMES:
            raise ValueError("Unsupported terminal outcome")
        if self.result_ref is not None and type(self.result_ref) is not EntityRef:
            raise DomainContractError("Result evidence must be an exact EntityRef")
        if self.outcome == "succeeded" and self.result_ref is None:
            raise DomainContractError("Success requires an exact sealed result reference")
        if type(self.usage_finality) is not str or self.usage_finality not in USAGE_FINALITIES:
            raise ValueError("Unsupported usage finality")
        if (type(self.remote_terminal_observed) is not str
                or self.remote_terminal_observed not in REMOTE_TERMINALS):
            raise ValueError("Unsupported remote terminal observation")
        if type(self.reason_code) is not str or self.reason_code not in RESULT_REASONS:
            raise ValueError("Unsupported typed result reason")
        if (self.outcome == "outcome_unknown"
                and self.remote_terminal_observed not in {"not_observed", "outcome_unknown"}):
            raise ValueError("Unknown outcome cannot claim a known remote terminal")

    def as_dict(self):
        return {
            "observation_id": self.observation_id,
            "attempt_id": self.attempt_id,
            "outcome": self.outcome,
            "result_ref": None if self.result_ref is None else self.result_ref.as_dict(),
            "usage_finality": self.usage_finality,
            "remote_terminal_observed": self.remote_terminal_observed,
            "reason_code": self.reason_code,
        }

    def semantic_dict(self):
        value = self.as_dict()
        del value["observation_id"]
        return value

    @classmethod
    def from_dict(cls, value):
        fields = ("observation_id", "attempt_id", "outcome", "result_ref",
                  "usage_finality", "remote_terminal_observed", "reason_code")
        value = _strict_dict(value, fields, "result observation")
        try:
            reference = None if value["result_ref"] is None else EntityRef.from_dict(value["result_ref"])
            return cls(value["observation_id"], value["attempt_id"], value["outcome"],
                       reference, value["usage_finality"], value["remote_terminal_observed"],
                       value["reason_code"])
        except (DomainContractError, TypeError, ValueError) as exc:
            raise CorruptLedger("Persisted result observation is invalid") from exc


@dataclass(frozen=True, slots=True)
class CancellationObservation:
    outcome: str
    local_transport_closed: bool
    owned_process_exit: int | None
    remote_terminal_observed: str
    usage_finality: str

    def __post_init__(self):
        if self.outcome not in {"cancelled", "outcome_unknown"}:
            raise ValueError("Cancellation ends as cancelled or outcome_unknown")
        if type(self.local_transport_closed) is not bool:
            raise ValueError("Local transport observation must be boolean")
        if (self.owned_process_exit is not None
                and (type(self.owned_process_exit) is not int
                     or not -255 <= self.owned_process_exit <= 255)):
            raise ValueError("Owned process exit must be a bounded status")
        if self.remote_terminal_observed not in REMOTE_TERMINALS:
            raise ValueError("Unsupported remote terminal observation")
        if self.usage_finality not in USAGE_FINALITIES:
            raise ValueError("Unsupported usage finality")
        if (self.outcome == "outcome_unknown"
                and self.remote_terminal_observed not in {"not_observed", "outcome_unknown"}):
            raise ValueError("Unknown cancellation outcome cannot claim a known remote terminal")

    def as_dict(self):
        return {
            "outcome": self.outcome,
            "local_transport_closed": self.local_transport_closed,
            "owned_process_exit": self.owned_process_exit,
            "remote_terminal_observed": self.remote_terminal_observed,
            "usage_finality": self.usage_finality,
        }


@dataclass(frozen=True, slots=True)
class TransportObservation:
    """Redacted authenticated-transport fact; never a semantic result."""

    permit_id: str
    command_id: str
    attempt_id: str
    effect: str
    connection_id: str | None
    worker_boot_id: str | None
    message_id: str | None
    message_type: str | None
    payload_bytes: int | None
    payload_sha256: str | None

    def __post_init__(self):
        uuid_string(self.permit_id)
        uuid_string(self.command_id)
        uuid_string(self.attempt_id)
        if self.effect not in TRANSPORT_EFFECTS:
            raise ValueError("Unsupported transport observation effect")
        response_fields = (
            self.connection_id,
            self.worker_boot_id,
            self.message_id,
            self.message_type,
            self.payload_bytes,
            self.payload_sha256,
        )
        if self.effect == "transport_accepted":
            if (
                type(self.connection_id) is not str
                or _SHA256.fullmatch(self.connection_id) is None
                or type(self.worker_boot_id) is not str
                or _TRANSPORT_BOOT_ID.fullmatch(self.worker_boot_id) is None
                or type(self.message_id) is not str
                or type(self.message_type) is not str
                or _TRANSPORT_MESSAGE_TYPE.fullmatch(self.message_type) is None
                or type(self.payload_bytes) is not int
                or not 0 <= self.payload_bytes <= 65_536
                or type(self.payload_sha256) is not str
                or _SHA256.fullmatch(self.payload_sha256) is None
            ):
                raise ValueError("Accepted transport observation is incomplete")
            uuid_string(self.message_id)
        elif any(value is not None for value in response_fields):
            raise ValueError("Failed transport observation cannot claim a response")

    def as_dict(self):
        return {
            "permit_id": self.permit_id,
            "command_id": self.command_id,
            "attempt_id": self.attempt_id,
            "effect": self.effect,
            "connection_id": self.connection_id,
            "worker_boot_id": self.worker_boot_id,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "payload_bytes": self.payload_bytes,
            "payload_sha256": self.payload_sha256,
        }

    @classmethod
    def from_dict(cls, value):
        fields = (
            "permit_id", "command_id", "attempt_id", "effect",
            "connection_id", "worker_boot_id", "message_id", "message_type",
            "payload_bytes", "payload_sha256",
        )
        value = _strict_dict(value, fields, "transport observation")
        try:
            return cls(**value)
        except (DomainContractError, TypeError, ValueError) as exc:
            raise CorruptLedger("Persisted transport observation is invalid") from exc


@dataclass(frozen=True, slots=True)
class LedgerOnlyPermit:
    """Test-only lifecycle token that the production dispatch boundary rejects."""

    permit_id: str
    command_id: str
    attempt_id: str
    execution_id: str
    idempotency_key: str
    envelope_ref: EntityRef
    profile_ref: EntityRef
    budget_policy_ref: EntityRef
    reservation_id: str
    owner: OwnerIdentity
    lease_fence: int
    lease_expires_at_ms: int
    deadline_at_ms: int
    issued_at_ms: int


@dataclass(frozen=True, slots=True)
class DispatchPermit:
    """Budget-bound process-local capability; replay never recreates it."""

    permit_id: str
    command_id: str
    attempt_id: str
    execution_id: str
    idempotency_key: str
    envelope_ref: EntityRef
    profile_ref: EntityRef
    budget_policy_ref: EntityRef
    reservation_id: str
    owner: OwnerIdentity
    lease_fence: int
    lease_expires_at_ms: int
    deadline_at_ms: int
    issued_at_ms: int
    budget_session_id: str
    budget_deadline_epoch_seconds: int
    principal: Principal | None = field(default=None, repr=False)
    grant: Grant | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.principal is None and self.grant is None:
            return
        if (
            type(self.principal) is not Principal
            or type(self.grant) is not Grant
            or self.principal.kind != "runtime"
            or self.grant.subject_id != self.principal.id
            or self.grant.ref != self.envelope_ref
            or self.grant.action != "read"
            or self.grant.purpose != self.principal.purpose
        ):
            raise TypeError("Dispatch permit authorization binding is invalid")

    def __copy__(self):
        raise TypeError("Dispatch permit is not copyable")

    def __deepcopy__(self, _memo):
        raise TypeError("Dispatch permit is not copyable")

    def __reduce__(self):
        raise TypeError("Dispatch permit is not serializable")

    @property
    def principal_id(self):
        return None if self.principal is None else self.principal.id

    @property
    def grant_id(self):
        return None if self.grant is None else self.grant.id


@dataclass(frozen=True, slots=True)
class ConsumedDispatchWindow:
    """Conservative wall-clock windows anchored before durable validation."""

    permit: DispatchPermit
    runtime_remaining_ms: int
    budget_remaining_ms: int
    anchor_monotonic: float

    def __post_init__(self):
        if type(self.permit) is not DispatchPermit:
            raise TypeError("Consumed dispatch requires an exact permit")
        for value in (self.runtime_remaining_ms, self.budget_remaining_ms):
            if type(value) is not int or not 0 <= value <= MAX_INTEGER:
                raise TypeError("Consumed dispatch windows must be bounded milliseconds")
        if type(self.anchor_monotonic) is not float or not (
            0.0 < self.anchor_monotonic < float("inf")
        ):
            raise TypeError("Consumed dispatch anchor must be finite monotonic time")

    @property
    def effective_remaining_ms(self):
        return min(self.runtime_remaining_ms, self.budget_remaining_ms)

    @property
    def deadline_end_monotonic(self):
        return self.anchor_monotonic + self.effective_remaining_ms / 1_000.0


_DDL = (
    "CREATE TABLE runtime_migrations (component TEXT NOT NULL, version INTEGER NOT NULL "
    "CHECK(typeof(version)='integer' AND version>0), sha256 TEXT NOT NULL, "
    "PRIMARY KEY(component,version))",
    "CREATE TABLE runtime_control (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id), "
    "last_clock_ms INTEGER NOT NULL CHECK(typeof(last_clock_ms)='integer' AND last_clock_ms>=0), "
    "active_session_id TEXT, reconciliation_generation INTEGER NOT NULL DEFAULT 0 "
    "CHECK(typeof(reconciliation_generation)='integer' AND reconciliation_generation>=0))",
    "CREATE TABLE runtime_commands (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), "
    "command_id TEXT NOT NULL, kind TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, "
    "result BLOB NOT NULL, result_digest TEXT NOT NULL, created_at_ms INTEGER NOT NULL, "
    "PRIMARY KEY(vault_id,command_id))",
    "CREATE TABLE runtime_runs (vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id), "
    "id TEXT NOT NULL, spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, "
    "revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), "
    "created_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id))",
    "CREATE TABLE runtime_run_refs (vault_id TEXT NOT NULL, run_id TEXT NOT NULL, role TEXT NOT NULL, "
    "kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, "
    "PRIMARY KEY(vault_id,run_id,role), FOREIGN KEY(vault_id,run_id) "
    "REFERENCES runtime_runs(vault_id,id), FOREIGN KEY(vault_id,kind,id,version,sha256) "
    "REFERENCES domain_records(vault_id,kind,id,version,sha256))",
    "CREATE TABLE runtime_node_executions (vault_id TEXT NOT NULL, id TEXT NOT NULL, "
    "run_id TEXT NOT NULL, node_id TEXT NOT NULL, visit_id TEXT NOT NULL, spec BLOB NOT NULL, "
    "spec_digest TEXT NOT NULL, phase TEXT NOT NULL, revision INTEGER NOT NULL "
    "CHECK(typeof(revision)='integer' AND revision>0), created_at_ms INTEGER NOT NULL, "
    "PRIMARY KEY(vault_id,id), UNIQUE(vault_id,run_id,node_id,visit_id), "
    "FOREIGN KEY(vault_id,run_id) REFERENCES runtime_runs(vault_id,id))",
    "CREATE TABLE runtime_execution_parents (vault_id TEXT NOT NULL, execution_id TEXT NOT NULL, "
    "position INTEGER NOT NULL, parent_execution_id TEXT NOT NULL, "
    "PRIMARY KEY(vault_id,execution_id,position), UNIQUE(vault_id,execution_id,parent_execution_id), "
    "FOREIGN KEY(vault_id,execution_id) REFERENCES runtime_node_executions(vault_id,id), "
    "FOREIGN KEY(vault_id,parent_execution_id) REFERENCES runtime_node_executions(vault_id,id))",
    "CREATE TABLE runtime_attempts (vault_id TEXT NOT NULL, id TEXT NOT NULL, execution_id TEXT NOT NULL, "
    "attempt_no INTEGER NOT NULL, idempotency_key TEXT NOT NULL, reservation_id TEXT NOT NULL, "
    "spec BLOB NOT NULL, spec_digest TEXT NOT NULL, phase TEXT NOT NULL, dispatch_gate TEXT NOT NULL, "
    "send_finality TEXT NOT NULL, cancel_state TEXT NOT NULL, recovery_state TEXT NOT NULL, "
    "terminal_outcome TEXT, revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0), "
    "lease_owner BLOB NOT NULL, lease_owner_digest TEXT NOT NULL, lease_fence INTEGER NOT NULL, "
    "lease_expires_at_ms INTEGER NOT NULL, dispatch_blocked_at_ms INTEGER, send_intent_at_ms INTEGER, "
    "local_transport_closed_at_ms INTEGER, owned_process_exit INTEGER, remote_terminal_observed TEXT NOT NULL, "
    "usage_finality TEXT NOT NULL, accepted_observation_id TEXT, created_at_ms INTEGER NOT NULL, "
    "updated_at_ms INTEGER NOT NULL, PRIMARY KEY(vault_id,id), "
    "UNIQUE(vault_id,execution_id,attempt_no), UNIQUE(vault_id,idempotency_key), "
    "FOREIGN KEY(vault_id,execution_id) REFERENCES runtime_node_executions(vault_id,id))",
    "CREATE TABLE runtime_attempt_refs (vault_id TEXT NOT NULL, attempt_id TEXT NOT NULL, role TEXT NOT NULL, "
    "kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, "
    "PRIMARY KEY(vault_id,attempt_id,role), FOREIGN KEY(vault_id,attempt_id) "
    "REFERENCES runtime_attempts(vault_id,id), FOREIGN KEY(vault_id,kind,id,version,sha256) "
    "REFERENCES domain_records(vault_id,kind,id,version,sha256))",
    "CREATE TABLE runtime_result_observations (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "vault_id TEXT NOT NULL, id TEXT NOT NULL, "
    "attempt_id TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, "
    "semantic_digest TEXT NOT NULL, classification TEXT NOT NULL, observed_at_ms INTEGER NOT NULL, "
    "UNIQUE(vault_id,id), FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id))",
    "CREATE TABLE runtime_result_refs (vault_id TEXT NOT NULL, observation_id TEXT NOT NULL, "
    "kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL, "
    "PRIMARY KEY(vault_id,observation_id), FOREIGN KEY(vault_id,observation_id) "
    "REFERENCES runtime_result_observations(vault_id,id), "
    "FOREIGN KEY(vault_id,kind,id,version,sha256) "
    "REFERENCES domain_records(vault_id,kind,id,version,sha256))",
    "CREATE TABLE runtime_checkpoints (vault_id TEXT NOT NULL, run_id TEXT NOT NULL, namespace TEXT NOT NULL, "
    "revision INTEGER NOT NULL, cursor BLOB NOT NULL, cursor_sha256 TEXT NOT NULL, "
    "bound_attempt_id TEXT, bound_attempt_revision INTEGER, bound_execution_id TEXT, "
    "bound_envelope_sha256 TEXT, created_at_ms INTEGER NOT NULL, command_id TEXT NOT NULL, "
    "PRIMARY KEY(vault_id,run_id,namespace,revision), UNIQUE(vault_id,command_id), "
    "FOREIGN KEY(vault_id,run_id) REFERENCES runtime_runs(vault_id,id))",
    "CREATE TABLE runtime_attempt_journal (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "vault_id TEXT NOT NULL, attempt_id TEXT NOT NULL, transition TEXT NOT NULL, "
    "payload BLOB NOT NULL, payload_digest TEXT NOT NULL, at_ms INTEGER NOT NULL, "
    "FOREIGN KEY(vault_id,attempt_id) REFERENCES runtime_attempts(vault_id,id))",
    "CREATE TABLE runtime_public_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "vault_id TEXT NOT NULL, event_type TEXT NOT NULL, object_kind TEXT NOT NULL, "
    "object_id TEXT NOT NULL, payload BLOB NOT NULL, payload_digest TEXT NOT NULL, at_ms INTEGER NOT NULL)",
    "CREATE INDEX runtime_attempts_execution ON runtime_attempts(vault_id,execution_id,attempt_no)",
    "CREATE INDEX runtime_results_attempt ON runtime_result_observations(vault_id,attempt_id,observed_at_ms,id)",
    "CREATE INDEX runtime_checkpoints_latest ON runtime_checkpoints(vault_id,run_id,namespace,revision)",
)
RUNTIME_MIGRATION_SHA256 = _digest("\n".join(_DDL).encode("utf-8"))
_OWNED_TABLES = frozenset({
    "runtime_migrations", "runtime_control", "runtime_commands", "runtime_runs",
    "runtime_run_refs", "runtime_node_executions", "runtime_execution_parents",
    "runtime_attempts", "runtime_attempt_refs", "runtime_result_observations",
    "runtime_result_refs", "runtime_checkpoints", "runtime_attempt_journal",
    "runtime_public_events",
})
_LEDGER_TABLES = _OWNED_TABLES - {"runtime_migrations"}
_LEDGER_INDEXES = frozenset({
    "runtime_attempts_execution", "runtime_results_attempt",
    "runtime_checkpoints_latest",
})


def _normalize_schema_sql(value):
    if type(value) is not str:
        return ""
    compact = " ".join(value.split()).casefold()
    return re.sub(r"\s*([(),=<>])\s*", r"\1", compact)


_EXPECTED_LEDGER_SCHEMA = {}
for _statement in _DDL:
    _schema_match = re.match(r"CREATE (TABLE|INDEX) ([a-z_]+)", _statement)
    if _schema_match is None:  # pragma: no cover - constant construction invariant
        raise RuntimeError("Invalid runtime ledger migration statement")
    _EXPECTED_LEDGER_SCHEMA[_schema_match.group(2)] = (
        _schema_match.group(1).casefold(), _normalize_schema_sql(_statement)
    )


class RuntimeLedger:
    """Additive ledger sharing the exact initialized ``intake.sqlite3`` vault."""

    def __init__(self, domain_store, *, clock_ms=None):
        if type(domain_store) is not DomainStore:
            raise TypeError("RuntimeLedger requires the exact initialized DomainStore")
        if clock_ms is None:
            clock_ms = lambda: time.time_ns() // 1_000_000
        if not callable(clock_ms):
            raise TypeError("clock_ms must be callable")
        self._domain = domain_store
        self._clock = clock_ms
        self.vault_id = domain_store.vault_id
        self._session_id = str(uuid4())
        self._startup_reconciled = False
        self._pending_permits = {}
        self._emergency_inhibited = set()
        self._global_emergency_inhibited = False
        self._clock_lock = RLock()
        self._last_now = None
        self._permit_lock = RLock()
        self._install_schema()

    @contextmanager
    def _transaction(self, *, write=False):
        if write:
            with _writer(), self._domain._connection(write=True) as db:
                yield db
        else:
            with self._domain._connection() as db:
                yield db

    def _install_schema(self):
        with self._transaction(write=True) as db:
            present = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (%s)"
                % ",".join("?" for _ in _OWNED_TABLES), tuple(sorted(_OWNED_TABLES)))}
            migration_present = "runtime_migrations" in present
            ledger_present = present - {"runtime_migrations"}
            if ledger_present and ledger_present != _LEDGER_TABLES:
                raise CorruptLedger("Partial runtime ledger schema")
            if migration_present:
                columns = [(row[1], row[2], row[3], row[5]) for row in
                           db.execute("PRAGMA table_info(runtime_migrations)")]
                expected = [("component", "TEXT", 1, 1), ("version", "INTEGER", 1, 2),
                            ("sha256", "TEXT", 1, 0)]
                if columns != expected:
                    raise CorruptLedger("Incompatible shared runtime migration ledger")
                probe = f"__ledger_schema_probe_{self._session_id}"
                try:
                    db.execute("INSERT INTO runtime_migrations VALUES (?,?,?)",
                               (probe, 1, "0" * 64))
                except sqlite3.IntegrityError as exc:
                    raise CorruptLedger(
                        "Shared runtime migration ledger rejects a valid version") from exc
                else:
                    db.execute("DELETE FROM runtime_migrations WHERE component=?", (probe,))
                for suffix, invalid in (("zero", 0), ("real", 1.5)):
                    try:
                        db.execute("INSERT INTO runtime_migrations VALUES (?,?,?)",
                                   (f"{probe}_{suffix}", invalid, "0" * 64))
                    except sqlite3.IntegrityError:
                        continue
                    raise CorruptLedger(
                        "Shared runtime migration ledger lacks the exact version constraint")
            if not ledger_present:
                for index, statement in enumerate(_DDL):
                    if index == 0 and migration_present:
                        continue
                    db.execute(statement)
                existing = db.execute("SELECT 1 FROM runtime_migrations "
                                      "WHERE component='ledger'").fetchone()
                if existing is not None:
                    raise CorruptLedger("Ledger migration row exists without ledger tables")
                db.execute("INSERT INTO runtime_migrations VALUES ('ledger',1,?)",
                           (RUNTIME_MIGRATION_SHA256,))
                db.execute("INSERT INTO runtime_control(singleton,vault_id,last_clock_ms) VALUES (1,?,0)",
                           (self.vault_id,))
            else:
                if not migration_present:
                    raise CorruptLedger("Runtime ledger migration registry is missing")
                rows = [tuple(row) for row in db.execute(
                    "SELECT version,sha256 FROM runtime_migrations WHERE component='ledger' "
                    "ORDER BY version")]
                if rows != [(1, RUNTIME_MIGRATION_SHA256)]:
                    raise CorruptLedger("Unknown or corrupt runtime ledger migration")
                control = db.execute("SELECT * FROM runtime_control WHERE singleton=1").fetchone()
                if (control is None or control["vault_id"] != self.vault_id
                        or db.execute("SELECT count(*) FROM runtime_control").fetchone()[0] != 1):
                    raise CorruptLedger("Runtime ledger control/vault binding is invalid")
                self._validate_control(control)

    @staticmethod
    def _assert_dispatch_schema(db):
        """Verify exact ledger tables/indexes and reject attached trigger hooks."""
        names = tuple(sorted(_EXPECTED_LEDGER_SCHEMA))
        stored = {row["name"]: (row["type"], _normalize_schema_sql(row["sql"]))
                  for row in db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name IN (%s)"
            % ",".join("?" for _ in names), names)}
        if stored != _EXPECTED_LEDGER_SCHEMA:
            raise CorruptLedger("Runtime ledger dispatch schema is inconsistent")
        migrations = [tuple(row) for row in db.execute(
            "SELECT version,sha256 FROM runtime_migrations WHERE component='ledger' "
            "ORDER BY version")]
        if migrations != [(1, RUNTIME_MIGRATION_SHA256)]:
            raise CorruptLedger("Runtime ledger dispatch migration is inconsistent")
        if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' LIMIT 1"
        ).fetchone() is not None:
            raise CorruptLedger("Unexpected shared-database trigger")
        table_names = tuple(sorted(_OWNED_TABLES))
        for row in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE type='index' AND lower(tbl_name) IN (%s)"
                % ",".join("?" for _ in table_names), table_names):
            automatic = (row["type"] == "index" and row["sql"] is None
                         and row["name"].casefold().startswith("sqlite_autoindex_"))
            expected = row["name"].casefold() in _LEDGER_INDEXES
            if not automatic and not expected:
                raise CorruptLedger("Unexpected runtime ledger dispatch schema object")

    @staticmethod
    def _validate_control(row):
        try:
            _nonnegative("last_clock_ms", row["last_clock_ms"])
            _nonnegative("reconciliation_generation", row["reconciliation_generation"])
            if row["active_session_id"] is not None:
                uuid_string(row["active_session_id"])
        except (DomainContractError, TypeError, ValueError, KeyError) as exc:
            raise CorruptLedger("Runtime control row is invalid") from exc

    def _now(self, db):
        with self._clock_lock:
            try:
                now = self._clock()
            except Exception as exc:
                raise ClockError("Trusted clock failed") from exc
            if type(now) is not int or not 0 <= now <= MAX_INTEGER:
                raise ClockError("Trusted clock must return bounded integer milliseconds")
            if self._last_now is not None and now < self._last_now:
                raise ClockError("Trusted runtime clock moved backwards")
            self._last_now = now
        row = db.execute("SELECT * FROM runtime_control WHERE singleton=1").fetchone()
        if row is None:
            raise CorruptLedger("Runtime control row is missing")
        self._validate_control(row)
        if now < row["last_clock_ms"]:
            raise ClockError("Clock moved backward across persisted runtime state")
        if now != row["last_clock_ms"]:
            db.execute("UPDATE runtime_control SET last_clock_ms=? WHERE singleton=1", (now,))
        return now

    def _observed_clock_floor(self):
        with self._clock_lock:
            if type(self._last_now) is not int:
                raise ClockError("Trusted runtime clock has not been observed")
            return self._last_now

    def _persist_clock_watermark_in_transaction(self, db, observed):
        """Persist an already-observed runtime floor in a recovery transaction."""
        if (type(db) is not sqlite3.Connection or not db.in_transaction
                or db.row_factory is not sqlite3.Row
                or type(observed) is not int or not 0 <= observed <= MAX_INTEGER):
            raise CorruptLedger("Runtime clock recovery requires an exact transaction")
        self._assert_dispatch_schema(db)
        row = db.execute("SELECT * FROM runtime_control WHERE singleton=1").fetchone()
        if (row is None or row["vault_id"] != self.vault_id
                or db.execute("SELECT count(*) FROM runtime_control").fetchone()[0] != 1):
            raise CorruptLedger("Runtime clock control/vault binding is invalid")
        self._validate_control(row)
        previous = row["last_clock_ms"]
        if observed > previous:
            changed = db.execute(
                "UPDATE runtime_control SET last_clock_ms=? "
                "WHERE singleton=1 AND vault_id=? AND last_clock_ms=?",
                (observed, self.vault_id, previous),
            ).rowcount
            if changed != 1:
                raise CorruptLedger("Runtime clock floor changed concurrently")
        return None

    def _require_session(self, db):
        row = db.execute("SELECT active_session_id FROM runtime_control WHERE singleton=1").fetchone()
        if (not self._startup_reconciled or row is None
                or row["active_session_id"] != self._session_id):
            self._startup_reconciled = False
            raise StartupReconciliationRequired(
                "Explicit startup reconciliation is required before dispatch")

    def _verify_refs(self, refs):
        for reference in refs:
            self._domain.get(reference)

    @staticmethod
    def _command_payload(value):
        return canonical_json(value)

    def _command_replay(self, db, command_id, kind, payload):
        uuid_string(command_id)
        row = db.execute("SELECT * FROM runtime_commands WHERE vault_id=? AND command_id=?",
                         (self.vault_id, command_id)).fetchone()
        if row is None:
            return None
        stored_payload = _decode_canonical(row["payload"], row["payload_digest"], "command payload")
        stored_result = _decode_canonical(row["result"], row["result_digest"], "command result")
        requested = parse_canonical(payload)
        if row["kind"] != kind or stored_payload != requested or bytes(row["payload"]) != payload:
            raise CommandConflict("Command ID was reused with different input")
        if type(stored_result) is not dict:
            raise CorruptLedger("Persisted command result is not an object")
        return stored_result

    def _record_command(self, db, command_id, kind, payload, result, now):
        encoded = canonical_json(result)
        db.execute("INSERT INTO runtime_commands VALUES (?,?,?,?,?,?,?,?)",
                   (self.vault_id, command_id, kind, payload, _digest(payload),
                    encoded, _digest(encoded), now))

    def _journal(self, db, attempt_id, transition, payload, now):
        if transition not in JOURNAL_TRANSITIONS:
            raise ValueError("Unregistered runtime journal transition")
        encoded = canonical_json(payload)
        db.execute("INSERT INTO runtime_attempt_journal"
                   "(vault_id,attempt_id,transition,payload,payload_digest,at_ms) "
                   "VALUES (?,?,?,?,?,?)",
                   (self.vault_id, attempt_id, transition, encoded, _digest(encoded), now))

    def _event(self, db, event_type, object_kind, object_id, payload, now):
        payload = event_metadata(event_type, payload)
        encoded = canonical_json(payload)
        db.execute("INSERT INTO runtime_public_events"
                   "(vault_id,event_type,object_kind,object_id,payload,payload_digest,at_ms) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (self.vault_id, event_type, object_kind, object_id,
                    encoded, _digest(encoded), now))

    @staticmethod
    def _object_ref(kind, identity, revision, content):
        digest = _digest(canonical_json(content))
        return ObjectRef(kind, identity, revision, digest).as_dict()

    def _run_snapshot(self, row):
        spec_value = _decode_canonical(row["spec"], row["spec_digest"], "run spec")
        spec = RunSpec.from_dict(spec_value)
        if spec.run_id != row["id"] or row["phase"] != "created":
            raise CorruptLedger("Runtime run row does not match its frozen spec")
        revision = positive_integer(row["revision"])
        core = {"spec": spec.as_dict(), "phase": row["phase"], "revision": revision,
                "created_at_ms": _nonnegative("created_at_ms", row["created_at_ms"])}
        return {"object_ref": self._object_ref("run", spec.run_id, revision, core), **core}

    def _execution_snapshot(self, row):
        spec_value = _decode_canonical(row["spec"], row["spec_digest"], "execution spec")
        spec = ExecutionSpec.from_dict(spec_value)
        if (spec.execution_id != row["id"] or spec.run_id != row["run_id"]
                or spec.node_id != row["node_id"] or spec.visit_id != row["visit_id"]
                or row["phase"] != "pending"):
            raise CorruptLedger("Execution row does not match its frozen spec")
        revision = positive_integer(row["revision"])
        core = {"spec": spec.as_dict(), "phase": row["phase"], "revision": revision,
                "created_at_ms": _nonnegative("created_at_ms", row["created_at_ms"])}
        return {"object_ref": self._object_ref("node_execution", spec.execution_id, revision, core), **core}

    def _attempt_snapshot(self, row):
        spec_value = _decode_canonical(row["spec"], row["spec_digest"], "attempt spec")
        spec = AttemptSpec.from_dict(spec_value)
        owner_value = _decode_canonical(row["lease_owner"], row["lease_owner_digest"], "lease owner")
        owner = OwnerIdentity.from_dict(owner_value)
        try:
            revision = positive_integer(row["revision"])
            lease_fence = positive_integer(row["lease_fence"])
            lease_expires = _nonnegative("lease_expires_at_ms", row["lease_expires_at_ms"])
            created = _nonnegative("created_at_ms", row["created_at_ms"])
            updated = _nonnegative("updated_at_ms", row["updated_at_ms"])
        except (DomainContractError, ValueError) as exc:
            raise CorruptLedger("Attempt counters/timestamps are invalid") from exc
        if (spec.attempt_id != row["id"] or spec.execution_id != row["execution_id"]
                or spec.attempt_no != row["attempt_no"] or spec.idempotency_key != row["idempotency_key"]
                or spec.reservation_id != row["reservation_id"] or owner != spec.owner
                or row["phase"] not in PHASES or row["dispatch_gate"] not in {"open", "closed"}
                or row["send_finality"] not in SEND_FINALITIES
                or row["cancel_state"] not in {"none", "requested"}
                or row["recovery_state"] not in {"clean", "pending", "reconciled"}
                or row["remote_terminal_observed"] not in REMOTE_TERMINALS
                or row["usage_finality"] not in USAGE_FINALITIES):
            raise CorruptLedger("Attempt row does not match its frozen spec or enums")
        terminal = row["terminal_outcome"]
        if ((row["phase"] == "terminal") != (terminal is not None)
                or terminal is not None and terminal not in TERMINAL_OUTCOMES):
            raise CorruptLedger("Attempt terminal phase/outcome is inconsistent")
        if terminal is not None and row["dispatch_gate"] != "closed":
            raise CorruptLedger("Terminal attempt has an open dispatch gate")
        if row["cancel_state"] == "requested" and row["dispatch_gate"] != "closed":
            raise CorruptLedger("Cancellation request has an open dispatch gate")
        if row["accepted_observation_id"] is not None:
            try:
                uuid_string(row["accepted_observation_id"])
            except DomainContractError as exc:
                raise CorruptLedger("Accepted observation identity is invalid") from exc
            if terminal is None:
                raise CorruptLedger("Nonterminal attempt points at an accepted observation")
        if row["dispatch_gate"] == "closed" and row["dispatch_blocked_at_ms"] is None:
            raise CorruptLedger("Closed dispatch gate lacks its durable timestamp")
        sent = row["send_intent_at_ms"] is not None
        if sent != (row["send_finality"] in {
                "may_have_started", "transport_accepted", "remote_terminal"}):
            raise CorruptLedger("Attempt send finality disagrees with its committed intent")
        if ((row["phase"] in {"send_intent", "running", "validating"} and not sent)
                or (row["phase"] in {"reserved", "preflighting", "awaiting_human"}
                    and sent)):
            raise CorruptLedger("Attempt phase disagrees with its committed send intent")
        if row["recovery_state"] == "pending" and row["dispatch_gate"] != "closed":
            raise CorruptLedger("Recovery-pending attempt has an open dispatch gate")
        if row["recovery_state"] == "reconciled" and row["phase"] != "terminal":
            raise CorruptLedger("Reconciled attempt is not terminal")
        if row["phase"] == "terminal" and row["recovery_state"] != "reconciled":
            raise CorruptLedger("Terminal attempt is not reconciled")
        for name in ("dispatch_blocked_at_ms", "send_intent_at_ms",
                     "local_transport_closed_at_ms"):
            if row[name] is not None:
                _nonnegative(name, row[name])
                if row[name] < created:
                    raise CorruptLedger(f"{name} predates attempt creation")
        if updated < created or lease_expires > spec.deadline_at_ms or lease_fence > revision:
            raise CorruptLedger("Attempt timestamp, deadline, or fence ordering is invalid")
        if (row["owned_process_exit"] is not None
                and (type(row["owned_process_exit"]) is not int
                     or not -255 <= row["owned_process_exit"] <= 255)):
            raise CorruptLedger("Owned process exit is invalid")
        core = {
            "spec": spec.as_dict(), "phase": row["phase"],
            "dispatch_gate": row["dispatch_gate"], "send_finality": row["send_finality"],
            "cancel_state": row["cancel_state"], "recovery_state": row["recovery_state"],
            "terminal_outcome": terminal, "revision": revision,
            "lease_owner": owner.as_dict(), "lease_fence": lease_fence,
            "lease_expires_at_ms": lease_expires,
            "reservation_ref": ObjectRef("budget_reservation", spec.reservation_id).as_dict(),
            "dispatch_blocked_at_ms": row["dispatch_blocked_at_ms"],
            "send_intent_at_ms": row["send_intent_at_ms"],
            "local_transport_closed_at_ms": row["local_transport_closed_at_ms"],
            "owned_process_exit": row["owned_process_exit"],
            "remote_terminal_observed": row["remote_terminal_observed"],
            "usage_finality": row["usage_finality"],
            "accepted_observation_id": row["accepted_observation_id"],
            "created_at_ms": created, "updated_at_ms": updated,
        }
        return {"object_ref": self._object_ref("attempt", spec.attempt_id, revision, core), **core}

    def _load_attempt(self, db, attempt_id):
        uuid_string(attempt_id)
        row = db.execute("SELECT * FROM runtime_attempts WHERE vault_id=? AND id=?",
                         (self.vault_id, attempt_id)).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        snapshot = self._attempt_snapshot(row)
        spec = AttemptSpec.from_dict(snapshot["spec"])
        self._validate_ref_roles(db, "runtime_attempt_refs", "attempt_id", attempt_id, {
            "envelope": spec.envelope_ref, "profile": spec.profile_ref,
            "budget_policy": spec.budget_policy_ref,
        })
        execution = db.execute("SELECT * FROM runtime_node_executions WHERE vault_id=? AND id=?",
                               (self.vault_id, spec.execution_id)).fetchone()
        if execution is None:
            raise CorruptLedger("Attempt execution is missing")
        execution_spec = ExecutionSpec.from_dict(self._execution_snapshot(execution)["spec"])
        self._validate_execution_bindings(db, execution_spec)
        run = db.execute("SELECT * FROM runtime_runs WHERE vault_id=? AND id=?",
                         (self.vault_id, execution_spec.run_id)).fetchone()
        if run is None:
            raise CorruptLedger("Attempt run is missing")
        run_spec = RunSpec.from_dict(self._run_snapshot(run)["spec"])
        self._validate_run_bindings(db, run_spec)
        if run_spec.budget_policy_ref != spec.budget_policy_ref:
            raise CorruptLedger("Attempt budget policy no longer matches its run")
        if row["accepted_observation_id"] is not None:
            result = db.execute("SELECT * FROM runtime_result_observations "
                "WHERE vault_id=? AND id=?", (self.vault_id,
                                               row["accepted_observation_id"])).fetchone()
            if (result is None or result["attempt_id"] != attempt_id
                    or result["classification"] != "accepted"):
                raise CorruptLedger("Accepted result pointer is invalid")
            observation = ResultObservation.from_dict(_decode_canonical(
                result["payload"], result["payload_digest"], "accepted result observation"))
            if (observation.attempt_id != attempt_id or observation.outcome != row["terminal_outcome"]
                    or _digest(canonical_json(observation.semantic_dict()))
                    != result["semantic_digest"]):
                raise CorruptLedger("Accepted result does not match terminal attempt state")
            self._validate_result_binding(db, observation)
        return row

    def _check_owner(self, row, owner):
        if type(owner) is not OwnerIdentity:
            raise LeaseOwnershipError("Exact owner identity is required")
        stored = OwnerIdentity.from_dict(_decode_canonical(
            row["lease_owner"], row["lease_owner_digest"], "lease owner"))
        if stored != owner:
            raise LeaseOwnershipError("Owner nonce/start identity does not match the lease")

    @staticmethod
    def _check_revision(row, expected_revision):
        positive_integer(expected_revision)
        if row["revision"] != expected_revision:
            raise RevisionConflict("Runtime object revision changed")

    def _insert_ref_roles(self, db, table, parent_column, parent_id, values):
        for role, reference in values.items():
            db.execute(f"INSERT INTO {table}"
                       f"(vault_id,{parent_column},role,kind,id,version,sha256) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (self.vault_id, parent_id, role, reference.kind, reference.id,
                        reference.version, reference.sha256))

    def _validate_domain_ref_row(self, db, reference):
        found = db.execute("SELECT 1 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
            "AND version=? AND sha256=?", (self.vault_id, reference.kind, reference.id,
                                            reference.version, reference.sha256)).fetchone()
        if found is None:
            raise CorruptLedger("Runtime reference target is missing or changed")

    def _validate_ref_roles(self, db, table, parent_column, parent_id, expected):
        rows = db.execute(f"SELECT role,kind,id,version,sha256 FROM {table} "
            f"WHERE vault_id=? AND {parent_column}=? ORDER BY role",
            (self.vault_id, parent_id)).fetchall()
        actual = {row["role"]: (row["kind"], row["id"], row["version"], row["sha256"])
                  for row in rows}
        wanted = {role: (reference.kind, reference.id, reference.version, reference.sha256)
                  for role, reference in expected.items()}
        if len(actual) != len(rows) or actual != wanted:
            raise CorruptLedger("Runtime reference index disagrees with canonical state")
        for reference in expected.values():
            self._validate_domain_ref_row(db, reference)

    def _validate_run_bindings(self, db, spec):
        self._validate_ref_roles(db, "runtime_run_refs", "run_id", spec.run_id, {
            "work_revision": spec.work_revision_ref, "environment": spec.environment_ref,
            "consent": spec.consent_ref, "budget_policy": spec.budget_policy_ref,
            "manifest": spec.manifest_ref,
        })

    def _validate_execution_bindings(self, db, spec):
        rows = db.execute("SELECT position,parent_execution_id FROM runtime_execution_parents "
            "WHERE vault_id=? AND execution_id=? ORDER BY position",
            (self.vault_id, spec.execution_id)).fetchall()
        actual = [(row["position"], row["parent_execution_id"]) for row in rows]
        expected = list(enumerate(spec.parent_execution_ids))
        if actual != expected:
            raise CorruptLedger("Execution parent index disagrees with canonical state")
        for parent_id in spec.parent_execution_ids:
            parent = db.execute("SELECT run_id FROM runtime_node_executions "
                "WHERE vault_id=? AND id=?", (self.vault_id, parent_id)).fetchone()
            if parent is None or parent["run_id"] != spec.run_id:
                raise CorruptLedger("Execution parent target is missing or cross-run")

    def _validate_result_binding(self, db, observation):
        rows = db.execute("SELECT kind,id,version,sha256 FROM runtime_result_refs "
            "WHERE vault_id=? AND observation_id=?", (self.vault_id,
                                                       observation.observation_id)).fetchall()
        if observation.result_ref is None:
            if rows:
                raise CorruptLedger("Result without an exact ref has an indexed ref")
            return
        reference = observation.result_ref
        expected = (reference.kind, reference.id, reference.version, reference.sha256)
        actual = [tuple(row) for row in rows]
        if actual != [expected]:
            raise CorruptLedger("Result reference index disagrees with canonical observation")
        self._validate_domain_ref_row(db, reference)

    def create_run(self, command_id, spec):
        if type(spec) is not RunSpec:
            raise TypeError("create_run requires an exact RunSpec")
        self._verify_refs((spec.work_revision_ref, spec.environment_ref, spec.consent_ref,
                           spec.budget_policy_ref, spec.manifest_ref))
        payload = self._command_payload({"spec": spec.as_dict()})
        with self._transaction(write=True) as db:
            replay = self._command_replay(db, command_id, "create_run", payload)
            if replay is not None:
                return replay
            now = self._now(db)
            encoded = canonical_json(spec.as_dict())
            db.execute("INSERT INTO runtime_runs VALUES (?,?,?,?,?,?,?)",
                       (self.vault_id, spec.run_id, encoded, _digest(encoded), "created", 1, now))
            self._insert_ref_roles(db, "runtime_run_refs", "run_id", spec.run_id, {
                "work_revision": spec.work_revision_ref, "environment": spec.environment_ref,
                "consent": spec.consent_ref, "budget_policy": spec.budget_policy_ref,
                "manifest": spec.manifest_ref,
            })
            row = db.execute("SELECT * FROM runtime_runs WHERE vault_id=? AND id=?",
                             (self.vault_id, spec.run_id)).fetchone()
            self._validate_run_bindings(db, spec)
            result = self._run_snapshot(row)
            self._record_command(db, command_id, "create_run", payload, result, now)
            return result

    def create_execution(self, command_id, spec):
        if type(spec) is not ExecutionSpec:
            raise TypeError("create_execution requires an exact ExecutionSpec")
        payload = self._command_payload({"spec": spec.as_dict()})
        with self._transaction(write=True) as db:
            replay = self._command_replay(db, command_id, "create_execution", payload)
            if replay is not None:
                return replay
            now = self._now(db)
            run = db.execute("SELECT 1 FROM runtime_runs WHERE vault_id=? AND id=?",
                             (self.vault_id, spec.run_id)).fetchone()
            if run is None:
                raise KeyError(spec.run_id)
            for parent in spec.parent_execution_ids:
                found = db.execute("SELECT run_id FROM runtime_node_executions "
                    "WHERE vault_id=? AND id=?", (self.vault_id, parent)).fetchone()
                if found is None or found["run_id"] != spec.run_id:
                    raise LedgerError("Parent execution is missing or belongs to another run")
            encoded = canonical_json(spec.as_dict())
            db.execute("INSERT INTO runtime_node_executions VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (self.vault_id, spec.execution_id, spec.run_id, spec.node_id,
                        spec.visit_id, encoded, _digest(encoded), "pending", 1, now))
            for position, parent in enumerate(spec.parent_execution_ids):
                db.execute("INSERT INTO runtime_execution_parents VALUES (?,?,?,?)",
                           (self.vault_id, spec.execution_id, position, parent))
            row = db.execute("SELECT * FROM runtime_node_executions WHERE vault_id=? AND id=?",
                             (self.vault_id, spec.execution_id)).fetchone()
            self._validate_execution_bindings(db, spec)
            result = self._execution_snapshot(row)
            self._record_command(db, command_id, "create_execution", payload, result, now)
            return result

    def reserve_attempt(self, command_id, spec, *, lease_duration_ms):
        if type(spec) is not AttemptSpec:
            raise TypeError("reserve_attempt requires an exact AttemptSpec")
        duration = _bounded_positive("lease_duration_ms", lease_duration_ms, MAX_LEASE_MS)
        self._verify_refs((spec.envelope_ref, spec.profile_ref, spec.budget_policy_ref))
        payload = self._command_payload({"spec": spec.as_dict(), "lease_duration_ms": duration})
        with self._transaction(write=True) as db:
            self._require_session(db)
            replay = self._command_replay(db, command_id, "reserve_attempt", payload)
            if replay is not None:
                return replay
            now = self._now(db)
            conflict = db.execute("SELECT spec,spec_digest FROM runtime_attempts "
                "WHERE vault_id=? AND idempotency_key=?", (self.vault_id, spec.idempotency_key)).fetchone()
            if conflict is not None:
                old = AttemptSpec.from_dict(_decode_canonical(
                    conflict["spec"], conflict["spec_digest"], "attempt spec"))
                if old == spec:
                    existing = db.execute("SELECT * FROM runtime_attempts WHERE vault_id=? "
                        "AND id=?", (self.vault_id, old.attempt_id)).fetchone()
                    result = self._attempt_snapshot(existing)
                    self._record_command(db, command_id, "reserve_attempt", payload, result, now)
                    return result
                raise IdempotencyConflict("Idempotency key was reused with different attempt input")
            if spec.owner.process_started_at_ms > now:
                raise ValueError("Owner process start cannot be in the future")
            if spec.deadline_at_ms <= now:
                raise InvalidTransition("Attempt deadline already expired")
            if duration > MAX_INTEGER - now:
                raise ValueError("Lease expiry overflow")
            active = db.execute("SELECT count(*) FROM runtime_attempts WHERE vault_id=? "
                "AND phase<>'terminal'", (self.vault_id,)).fetchone()[0]
            if active >= MAX_ACTIVE_ATTEMPTS:
                raise LedgerError("Active attempt bound reached")
            execution = db.execute("SELECT run_id FROM runtime_node_executions WHERE vault_id=? AND id=?",
                                   (self.vault_id, spec.execution_id)).fetchone()
            if execution is None:
                raise KeyError(spec.execution_id)
            self._validated_run_checkpoints(db, execution["run_id"])
            run_row = db.execute("SELECT spec,spec_digest FROM runtime_runs WHERE vault_id=? AND id=?",
                                 (self.vault_id, execution["run_id"])).fetchone()
            run_spec = RunSpec.from_dict(_decode_canonical(
                run_row["spec"], run_row["spec_digest"], "run spec"))
            if run_spec.budget_policy_ref != spec.budget_policy_ref:
                raise LedgerError("Attempt budget policy differs from its frozen run")
            predecessors = db.execute("SELECT * FROM runtime_attempts WHERE vault_id=? "
                "AND execution_id=? ORDER BY attempt_no",
                (self.vault_id, spec.execution_id)).fetchall()
            numbers = [row["attempt_no"] for row in predecessors]
            if numbers != list(range(1, len(numbers) + 1)):
                raise CorruptLedger("Attempt retry sequence is not contiguous")
            if spec.attempt_no != len(predecessors) + 1:
                raise InvalidTransition("Attempt retry number is not the next logical retry")
            for predecessor in predecessors:
                predecessor = self._load_attempt(db, predecessor["id"])
                safely_unsent = (predecessor["dispatch_gate"] == "closed"
                                 and predecessor["send_finality"] == "definitely_not_sent"
                                 and predecessor["send_intent_at_ms"] is None)
                has_late_evidence = db.execute(
                    "SELECT 1 FROM runtime_result_observations WHERE vault_id=? "
                    "AND attempt_id=? AND classification='late' LIMIT 1",
                    (self.vault_id, predecessor["id"]),
                ).fetchone() is not None
                observed_terminal = (
                    predecessor["phase"] == "terminal"
                    and predecessor["terminal_outcome"] in {"failed", "timed_out", "cancelled"}
                    and predecessor["remote_terminal_observed"]
                    == predecessor["terminal_outcome"]
                    and predecessor["usage_finality"] == "final"
                    and not has_late_evidence
                )
                if not safely_unsent and not observed_terminal:
                    raise DispatchBlocked(
                        "A prior attempt is not proven retry-safe")
            lease_expires = min(now + duration, spec.deadline_at_ms)
            encoded = canonical_json(spec.as_dict())
            encoded_owner = canonical_json(spec.owner.as_dict())
            db.execute("INSERT INTO runtime_attempts (vault_id,id,execution_id,attempt_no,"
                       "idempotency_key,reservation_id,spec,spec_digest,phase,dispatch_gate,"
                       "send_finality,cancel_state,recovery_state,terminal_outcome,revision,"
                       "lease_owner,lease_owner_digest,lease_fence,lease_expires_at_ms,"
                       "dispatch_blocked_at_ms,send_intent_at_ms,local_transport_closed_at_ms,"
                       "owned_process_exit,remote_terminal_observed,usage_finality,"
                       "accepted_observation_id,created_at_ms,updated_at_ms) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (self.vault_id, spec.attempt_id, spec.execution_id, spec.attempt_no,
                        spec.idempotency_key, spec.reservation_id, encoded, _digest(encoded),
                        "reserved", "open", "not_started", "none", "clean", None, 1,
                        encoded_owner, _digest(encoded_owner), 1, lease_expires, None, None,
                        None, None, "not_observed", "provisional", None, now, now))
            self._insert_ref_roles(db, "runtime_attempt_refs", "attempt_id", spec.attempt_id, {
                "envelope": spec.envelope_ref, "profile": spec.profile_ref,
                "budget_policy": spec.budget_policy_ref,
            })
            self._journal(db, spec.attempt_id, "reserved",
                          {"attempt_no": spec.attempt_no, "lease_fence": 1}, now)
            self._event(db, "attempt.reserved", "attempt", spec.attempt_id,
                        {"attempt_no": spec.attempt_no}, now)
            row = self._load_attempt(db, spec.attempt_id)
            result = self._attempt_snapshot(row)
            self._record_command(db, command_id, "reserve_attempt", payload, result, now)
            return result

    def renew_lease(self, command_id, attempt_id, owner, *, expected_revision, lease_duration_ms):
        duration = _bounded_positive("lease_duration_ms", lease_duration_ms, MAX_LEASE_MS)
        if type(owner) is not OwnerIdentity:
            raise LeaseOwnershipError("Exact owner identity is required")
        payload = self._command_payload({"attempt_id": attempt_id, "owner": owner.as_dict(),
            "expected_revision": expected_revision, "lease_duration_ms": duration})
        with self._transaction(write=True) as db:
            self._require_session(db)
            replay = self._command_replay(db, command_id, "renew_lease", payload)
            if replay is not None:
                return replay
            now = self._now(db)
            row = self._load_attempt(db, attempt_id)
            self._check_owner(row, owner)
            self._check_revision(row, expected_revision)
            if row["phase"] == "terminal" or row["dispatch_gate"] == "closed":
                raise InvalidTransition("Closed or terminal attempt lease cannot renew")
            if now >= row["lease_expires_at_ms"]:
                raise LeaseExpired("Lease expired; expiry alone does not authorize takeover")
            spec = AttemptSpec.from_dict(_decode_canonical(row["spec"], row["spec_digest"], "attempt spec"))
            if now >= spec.deadline_at_ms:
                raise LeaseExpired("Attempt deadline expired")
            if duration > MAX_INTEGER - now:
                raise ValueError("Lease expiry overflow")
            expires = min(now + duration, spec.deadline_at_ms)
            changed = db.execute("UPDATE runtime_attempts SET revision=revision+1,lease_fence=lease_fence+1,"
                "lease_expires_at_ms=?,updated_at_ms=? WHERE vault_id=? AND id=? AND revision=? "
                "AND phase<>'terminal' AND dispatch_gate='open'",
                (expires, now, self.vault_id, attempt_id, expected_revision)).rowcount
            if changed != 1:
                raise RevisionConflict("Lease renewal lost its revision/state CAS")
            updated = self._load_attempt(db, attempt_id)
            self._journal(db, attempt_id, "lease_renewed",
                          {"lease_fence": updated["lease_fence"]}, now)
            result = self._attempt_snapshot(updated)
            self._record_command(db, command_id, "renew_lease", payload, result, now)
            return result

    def advance_attempt(self, command_id, attempt_id, owner, target_phase, *, expected_revision):
        if target_phase not in {"preflighting", "awaiting_human", "running", "validating"}:
            raise InvalidTransition("Unsupported nonterminal attempt phase")
        if type(owner) is not OwnerIdentity:
            raise LeaseOwnershipError("Exact owner identity is required")
        payload = self._command_payload({"attempt_id": attempt_id, "owner": owner.as_dict(),
            "target_phase": target_phase, "expected_revision": expected_revision})
        allowed = {
            "reserved": {"preflighting", "awaiting_human"},
            "preflighting": {"awaiting_human"},
            "awaiting_human": {"preflighting"},
            "send_intent": {"running"},
            "running": {"validating"},
        }
        with self._transaction(write=True) as db:
            self._require_session(db)
            replay = self._command_replay(db, command_id, "advance_attempt", payload)
            if replay is not None:
                return replay
            now = self._now(db)
            row = self._load_attempt(db, attempt_id)
            self._check_owner(row, owner)
            self._check_revision(row, expected_revision)
            if target_phase not in allowed.get(row["phase"], set()):
                raise InvalidTransition("Attempt phase transition is not allowed")
            if row["dispatch_gate"] != "open" or now >= row["lease_expires_at_ms"]:
                raise DispatchBlocked("Attempt gate or lease blocks phase transition")
            send_finality = "transport_accepted" if target_phase == "running" else row["send_finality"]
            changed = db.execute("UPDATE runtime_attempts SET phase=?,send_finality=?,revision=revision+1,"
                "updated_at_ms=? WHERE vault_id=? AND id=? AND revision=? AND phase=? AND dispatch_gate='open'",
                (target_phase, send_finality, now, self.vault_id, attempt_id,
                 expected_revision, row["phase"])).rowcount
            if changed != 1:
                raise RevisionConflict("Attempt phase transition lost its CAS")
            updated = self._load_attempt(db, attempt_id)
            self._journal(db, attempt_id, target_phase, {"revision": updated["revision"]}, now)
            result = self._attempt_snapshot(updated)
            self._record_command(db, command_id, "advance_attempt", payload, result, now)
            return result

    def _commit_unbudgeted_send_intent_for_test(
            self, command_id, attempt_id, owner, *, expected_revision):
        """Exercise the ledger lifecycle without creating a production permit."""
        return self._commit_send_intent(
            command_id,
            attempt_id,
            owner,
            expected_revision=expected_revision,
            command_kind="test_commit_unbudgeted_send_intent",
            budget_book=None,
            budget_request=None,
        )

    def commit_budgeted_send_intent(self, command_id, attempt_id, owner, *,
                                    expected_revision, budget_book, budget_request,
                                    principal=None, grant=None):
        """Atomically reserve budget and commit send intent before issuing a permit."""
        if type(budget_book) is not BudgetBook:
            raise TypeError("Exact BudgetBook required")
        if type(budget_request) is not BudgetDispatchRequest:
            raise TypeError("Exact BudgetDispatchRequest required")
        book_path = Path(os.path.abspath(budget_book.path))
        if book_path != self._domain.path:
            raise LedgerError("BudgetBook must share the same vault database")
        return self._commit_send_intent(
            command_id,
            attempt_id,
            owner,
            expected_revision=expected_revision,
            command_kind="commit_budgeted_send_intent",
            budget_book=budget_book,
            budget_request=budget_request,
            principal=principal,
            grant=grant,
        )

    def _stage_budgeted_send_intent_in_transaction(
            self, db, command_id, attempt_id, owner, *, expected_revision,
            budget_book, budget_request, principal=None, grant=None):
        """Stage one budgeted send intent in a caller-owned SQLite transaction.

        The returned capability is deliberately absent from ``_pending_permits``.
        Only the root coordinator may activate it after the outer commit succeeds.
        """
        if type(db) is not sqlite3.Connection or not db.in_transaction:
            raise LedgerError("Staged dispatch requires an active SQLite transaction")
        if type(budget_book) is not BudgetBook:
            raise TypeError("Exact BudgetBook required")
        if type(budget_request) is not BudgetDispatchRequest:
            raise TypeError("Exact BudgetDispatchRequest required")
        if (type(budget_book._domain) is not DomainStore
                or Path(os.path.abspath(budget_book.path)) != self._domain.path
                or budget_book._domain.path != self._domain.path
                or budget_book._domain.data_dir != self._domain.data_dir):
            raise LedgerError("BudgetBook must share the same exact vault")
        databases = list(db.execute("PRAGMA database_list"))
        settings = {
            name: db.execute(f"PRAGMA {name}").fetchone()[0]
            for name in ("journal_mode", "synchronous", "fullfsync",
                         "foreign_keys", "trusted_schema")
        }
        if (db.row_factory is not sqlite3.Row
                or len(databases) != 1 or databases[0][1] != "main"
                or Path(os.path.abspath(databases[0][2])) != self._domain.path):
            raise LedgerError("Staged dispatch connection is not the canonical vault")
        if (type(settings["journal_mode"]) is not str
                or settings["journal_mode"].casefold() != "wal"
                or settings["synchronous"] != 2
                or settings["fullfsync"] != 1
                or settings["foreign_keys"] != 1
                or settings["trusted_schema"] != 0):
            raise LedgerError("Staged dispatch connection is not hardened")
        return self._commit_send_intent(
            command_id,
            attempt_id,
            owner,
            expected_revision=expected_revision,
            command_kind="commit_budgeted_send_intent",
            budget_book=budget_book,
            budget_request=budget_request,
            principal=principal,
            grant=grant,
            _db=db,
            _activate=False,
        )

    def _commit_send_intent(self, command_id, attempt_id, owner, *, expected_revision,
                            command_kind, budget_book, budget_request, _db=None,
                            principal=None, grant=None, _activate=True):
        """Commit the may-have-sent barrier, then return at most one ephemeral permit.

        Exact command replay returns ``None``.  This deliberate exception prevents an
        idempotent API replay from becoming a second local provider dispatch.
        """
        if type(owner) is not OwnerIdentity:
            raise LeaseOwnershipError("Exact owner identity is required")
        if (principal is None) != (grant is None):
            raise TypeError("Dispatch authorization binding must be complete")
        if principal is not None and (
                type(principal) is not Principal
                or type(grant) is not Grant
                or principal.kind != "runtime"
                or grant.subject_id != principal.id
                or grant.action != "read"
                or grant.purpose != principal.purpose):
            raise TypeError("Dispatch authorization binding is invalid")
        if _db is None:
            self.get_attempt(attempt_id)
        elif type(_db) is not sqlite3.Connection or not _db.in_transaction:
            raise LedgerError("Caller-owned dispatch requires an active transaction")
        payload_value = {"attempt_id": attempt_id, "owner": owner.as_dict(),
                         "expected_revision": expected_revision}
        if budget_request is not None:
            payload_value["budget_request"] = budget_request.as_dict()
        if principal is not None:
            payload_value["principal_id"] = principal.id
            payload_value["grant_id"] = grant.id
        payload = self._command_payload(payload_value)
        permit = None
        transaction = self._transaction(write=True) if _db is None else nullcontext(_db)
        with transaction as db:
            if budget_request is not None:
                self._assert_dispatch_schema(db)
                BudgetBook._assert_transaction_schema(db)
            self._require_session(db)
            replay = self._command_replay(db, command_id, command_kind, payload)
            if replay is not None:
                return None
            now = self._now(db)
            row = self._load_attempt(db, attempt_id)
            self._check_owner(row, owner)
            self._check_revision(row, expected_revision)
            with self._permit_lock:
                if (self._global_emergency_inhibited
                        or attempt_id in self._emergency_inhibited):
                    raise DispatchBlocked("Process-local emergency inhibition is active")
            spec = AttemptSpec.from_dict(_decode_canonical(row["spec"], row["spec_digest"], "attempt spec"))
            if grant is not None and grant.ref != spec.envelope_ref:
                raise LedgerError("Dispatch grant must bind the attempt envelope")
            if budget_request is not None:
                if budget_request.request_id != spec.reservation_id:
                    raise LedgerError(
                        "Budget request must bind the attempt reservation ID"
                    )
                if budget_request.policy_ref != spec.budget_policy_ref:
                    raise LedgerError(
                        "Budget request must bind the attempt budget policy"
                    )
            if row["dispatch_gate"] != "open" or row["cancel_state"] != "none":
                raise DispatchBlocked("Dispatch gate is closed")
            if row["phase"] not in {"reserved", "preflighting"}:
                result = {"intent_committed": False, "reason": "already_committed",
                          "attempt_id": attempt_id}
                self._record_command(db, command_id, command_kind, payload, result, now)
                return None
            execution = db.execute("SELECT run_id FROM runtime_node_executions "
                "WHERE vault_id=? AND id=?", (self.vault_id, spec.execution_id)).fetchone()
            if execution is None:
                raise CorruptLedger("Attempt execution is missing")
            run = db.execute("SELECT spec,spec_digest FROM runtime_runs WHERE vault_id=? AND id=?",
                             (self.vault_id, execution["run_id"])).fetchone()
            if run is None:
                raise CorruptLedger("Attempt run is missing")
            run_spec = RunSpec.from_dict(_decode_canonical(
                run["spec"], run["spec_digest"], "run spec"))
            if run_spec.mode in {"replay", "snapshot"}:
                raise DispatchBlocked(f"{run_spec.mode} runs cannot dispatch external work")
            if (budget_request is not None
                    and budget_request.session_id != run_spec.budget_session_id):
                raise LedgerError(
                    "Budget request must bind the frozen run budget session"
                )
            if now >= spec.deadline_at_ms:
                changed = db.execute("UPDATE runtime_attempts SET phase='terminal',dispatch_gate='closed',"
                    "send_finality='definitely_not_sent',terminal_outcome='timed_out',"
                    "recovery_state='reconciled',dispatch_blocked_at_ms=?,usage_finality='final',"
                    "revision=revision+1,updated_at_ms=? "
                    "WHERE vault_id=? AND id=? AND revision=? AND phase IN ('reserved','preflighting') "
                    "AND dispatch_gate='open'", (now, now, self.vault_id, attempt_id,
                                                  expected_revision)).rowcount
                if changed != 1:
                    raise RevisionConflict("Deadline transition lost its CAS")
                self._journal(db, attempt_id, "recovery_terminal", {"outcome": "timed_out"}, now)
                self._event(db, "attempt.terminal", "attempt", attempt_id,
                            {"outcome": "timed_out"}, now)
                result = {"intent_committed": False, "reason": "deadline", "attempt_id": attempt_id}
                self._record_command(db, command_id, command_kind, payload, result, now)
                return None
            if now >= row["lease_expires_at_ms"]:
                changed = db.execute("UPDATE runtime_attempts SET dispatch_gate='closed',"
                    "send_finality='definitely_not_sent',recovery_state='pending',"
                    "dispatch_blocked_at_ms=?,revision=revision+1,updated_at_ms=? "
                    "WHERE vault_id=? AND id=? AND revision=? AND dispatch_gate='open'",
                    (now, now, self.vault_id, attempt_id, expected_revision)).rowcount
                if changed != 1:
                    raise RevisionConflict("Expired lease transition lost its CAS")
                self._journal(db, attempt_id, "recovery_pending", {"reason": "lease_expired"}, now)
                result = {"intent_committed": False, "reason": "lease_expired", "attempt_id": attempt_id}
                self._record_command(db, command_id, command_kind, payload, result, now)
                return None
            budget_deadline_epoch_seconds = None
            if budget_request is not None:
                _, policy, budget_deadline_epoch_seconds = \
                    budget_book._reserve_and_mark_dispatched_in_transaction(
                    db, budget_request
                )
                self._assert_budget_policy_binding(db, spec.budget_policy_ref, policy)
            permit_id = str(uuid4())
            changed = db.execute("UPDATE runtime_attempts SET phase='send_intent',send_finality='may_have_started',"
                "send_intent_at_ms=?,revision=revision+1,updated_at_ms=? WHERE vault_id=? AND id=? "
                "AND revision=? AND phase IN ('reserved','preflighting') AND dispatch_gate='open' "
                "AND cancel_state='none' AND recovery_state='clean' "
                "AND send_finality='not_started' AND terminal_outcome IS NULL "
                "AND accepted_observation_id IS NULL AND send_intent_at_ms IS NULL",
                (now, now, self.vault_id, attempt_id, expected_revision)).rowcount
            if changed != 1:
                raise RevisionConflict("Send-intent barrier lost its state/revision CAS")
            updated = self._load_attempt(db, attempt_id)
            self._journal(db, attempt_id, "send_intent",
                          {"lease_fence": updated["lease_fence"], "revision": updated["revision"]}, now)
            self._event(db, "attempt.dispatched", "attempt", attempt_id,
                        {"attempt_no": spec.attempt_no}, now)
            result = {"intent_committed": True, "attempt_id": attempt_id,
                      "permit_id": permit_id, "revision": updated["revision"]}
            self._record_command(db, command_id, command_kind, payload, result, now)
            verified_budget_deadline = self._assert_committed_send(
                db, command_id=command_id, command_kind=command_kind,
                command_payload=payload, command_result=result, spec=spec,
                owner=owner, updated=updated, committed_at_ms=now,
                budget_book=budget_book, budget_request=budget_request,
            )
            permit_values = (
                permit_id, command_id, attempt_id, spec.execution_id,
                spec.idempotency_key, spec.envelope_ref, spec.profile_ref,
                spec.budget_policy_ref, spec.reservation_id, owner,
                updated["lease_fence"], updated["lease_expires_at_ms"],
                spec.deadline_at_ms, now,
            )
            if budget_request is None:
                permit = LedgerOnlyPermit(*permit_values)
            else:
                if (type(budget_deadline_epoch_seconds) is not int
                        or verified_budget_deadline != budget_deadline_epoch_seconds):
                    raise CorruptLedger(
                        "Committed budget deadline changed before permit activation"
                    )
                permit = DispatchPermit(
                    *permit_values,
                    budget_request.session_id,
                    budget_deadline_epoch_seconds,
                    principal,
                    grant,
                )
        if _activate:
            self._activate_dispatch_permit(permit, budget_book=budget_book)
        return permit

    def _activate_dispatch_permit(self, permit, *, budget_book):
        """Expose a staged capability only after its owning transaction committed."""
        expected_type = LedgerOnlyPermit if budget_book is None else DispatchPermit
        if type(permit) is not expected_type:
            raise DispatchBlocked("Exact staged dispatch permit required")
        if budget_book is not None:
            if (type(budget_book) is not BudgetBook
                    or type(budget_book._domain) is not DomainStore
                    or Path(os.path.abspath(budget_book.path)) != self._domain.path
                    or budget_book._domain.path != self._domain.path
                    or budget_book._domain.data_dir != self._domain.data_dir):
                raise DispatchBlocked("Staged permit budget owner changed")
        with self._permit_lock:
            if (permit.permit_id in self._pending_permits
                    or self._global_emergency_inhibited
                    or permit.attempt_id in self._emergency_inhibited):
                raise DispatchBlocked("Staged dispatch permit is duplicate or inhibited")
            self._pending_permits[permit.permit_id] = (
                permit,
                budget_book,
                getattr(permit, "principal", None),
                getattr(permit, "grant", None),
                getattr(getattr(permit, "principal", None), "id", None),
                getattr(getattr(permit, "grant", None), "id", None),
            )
        return permit

    def _inhibit_all_dispatch(self):
        """Revoke every process-local permit after root recovery becomes unsafe."""
        # This safety latch must never wait behind the SQLite writer.  It is the
        # last process-local barrier after a durable observation becomes unknown:
        # publish it and revoke every pending capability in one lock acquisition.
        with self._permit_lock:
            self._global_emergency_inhibited = True
            self._pending_permits.clear()
        return None

    def emergency_inhibit_attempt(self, attempt_id):
        """Fail closed in memory when a post-commit observation cannot persist."""
        uuid_string(attempt_id)
        with self._permit_lock:
            self._emergency_inhibited.add(attempt_id)
            for permit_id, stored in tuple(self._pending_permits.items()):
                if stored[0].attempt_id == attempt_id:
                    self._pending_permits.pop(permit_id, None)
        return None

    def emergency_inhibit_all_dispatch(self):
        """Public fail-closed latch for an unrecordable post-commit effect."""
        return self._inhibit_all_dispatch()

    def assert_dispatch_session_ready(self):
        """Prove startup reconciliation completed before a dispatcher starts."""
        with self._permit_lock:
            if self._global_emergency_inhibited:
                raise DispatchBlocked("Process-local emergency inhibition is active")
        with self._transaction() as db:
            self._require_session(db)
        # Do not publish readiness if another transport thread inhibited dispatch
        # while the durable session check was in progress.
        with self._permit_lock:
            if self._global_emergency_inhibited:
                raise DispatchBlocked("Process-local emergency inhibition is active")
        return None

    def discard_dispatch_permit(self, permit):
        """Remove an exact unconsumed permit without authorizing an external send."""
        if type(permit) is not DispatchPermit:
            raise DispatchBlocked("Exact budget-bound dispatch permit required")
        with self._permit_lock:
            stored = self._pending_permits.get(permit.permit_id)
            if stored is None:
                return False
            if (
                type(stored) is not tuple
                or len(stored) != 6
                or stored[0] is not permit
                or stored[2] is not permit.principal
                or stored[3] is not permit.grant
            ):
                raise DispatchBlocked("Dispatch permit identity changed")
            self._pending_permits.pop(permit.permit_id)
            return True

    def _transport_command_binding(self, db, permit):
        if type(permit) is not DispatchPermit:
            raise DispatchBlocked("Exact dispatch permit required")
        command = db.execute(
            "SELECT * FROM runtime_commands WHERE vault_id=? AND command_id=?",
            (self.vault_id, permit.command_id),
        ).fetchone()
        if command is None or command["kind"] != "commit_budgeted_send_intent":
            raise CorruptLedger("Transport observation command is absent")
        payload = _decode_canonical(
            command["payload"], command["payload_digest"], "dispatch command payload"
        )
        result = _decode_canonical(
            command["result"], command["result_digest"], "dispatch command result"
        )
        expected_fields = {
            "attempt_id", "owner", "expected_revision", "budget_request",
            "principal_id", "grant_id",
        }
        budget_request = payload.get("budget_request") if type(payload) is dict else None
        if (
            type(payload) is not dict
            or set(payload) != expected_fields
            or type(budget_request) is not dict
            or payload["attempt_id"] != permit.attempt_id
            or payload["owner"] != permit.owner.as_dict()
            or payload["principal_id"] != permit.principal_id
            or payload["grant_id"] != permit.grant_id
            or budget_request.get("session_id") != permit.budget_session_id
            or budget_request.get("request_id") != permit.reservation_id
            or budget_request.get("policy_ref") != permit.budget_policy_ref.as_dict()
            or type(result) is not dict
            or result.get("intent_committed") is not True
            or result.get("attempt_id") != permit.attempt_id
            or result.get("permit_id") != permit.permit_id
        ):
            raise CorruptLedger("Transport observation dispatch binding changed")
        return result

    def record_transport_observation(self, permit, observation):
        """Persist one redacted transport fact without settling or accepting work."""
        if type(permit) is not DispatchPermit or type(observation) is not TransportObservation:
            raise TypeError("Exact permit and transport observation required")
        if (
            observation.permit_id != permit.permit_id
            or observation.command_id != permit.command_id
            or observation.attempt_id != permit.attempt_id
        ):
            raise DispatchBlocked("Transport observation identity changed")
        encoded = canonical_json(observation.as_dict())
        with self._transaction(write=True) as db:
            self._require_session(db)
            self._transport_command_binding(db, permit)
            row = self._load_attempt(db, permit.attempt_id)
            spec = AttemptSpec.from_dict(_decode_canonical(
                row["spec"], row["spec_digest"], "attempt spec"
            ))
            if (
                spec.execution_id != permit.execution_id
                or spec.envelope_ref != permit.envelope_ref
                or spec.profile_ref != permit.profile_ref
                or spec.owner != permit.owner
            ):
                raise CorruptLedger("Transport observation attempt binding changed")
            observed = list(db.execute(
                "SELECT payload,payload_digest FROM runtime_attempt_journal "
                "WHERE vault_id=? AND attempt_id=? AND transition='transport_observed'",
                (self.vault_id, permit.attempt_id),
            ))
            if observed:
                if len(observed) != 1:
                    raise CorruptLedger("Transport observation is duplicated")
                prior = _decode_canonical(
                    observed[0]["payload"], observed[0]["payload_digest"],
                    "transport observation",
                )
                if prior != observation.as_dict() or bytes(observed[0]["payload"]) != encoded:
                    raise CommandConflict("Transport observation changed after commit")
                return {
                    "observation": prior,
                    "attempt": self._attempt_snapshot(row),
                }
            if (
                row["phase"] != "send_intent"
                or row["send_finality"] != "may_have_started"
                or row["cancel_state"] != "none"
                or row["recovery_state"] != "clean"
            ):
                raise InvalidTransition("Attempt cannot accept a transport observation")
            now = self._now(db)
            if observation.effect == "transport_accepted":
                if row["dispatch_gate"] != "open":
                    raise InvalidTransition("Closed dispatch cannot become transport accepted")
                changed = db.execute(
                    "UPDATE runtime_attempts SET phase='running',"
                    "send_finality='transport_accepted',revision=revision+1,updated_at_ms=? "
                    "WHERE vault_id=? AND id=? AND revision=? AND phase='send_intent' "
                    "AND dispatch_gate='open' AND recovery_state='clean'",
                    (now, self.vault_id, permit.attempt_id, row["revision"]),
                ).rowcount
            else:
                changed = db.execute(
                    "UPDATE runtime_attempts SET dispatch_gate='closed',"
                    "recovery_state='pending',dispatch_blocked_at_ms=?,"
                    "revision=revision+1,updated_at_ms=? WHERE vault_id=? AND id=? "
                    "AND revision=? AND phase='send_intent' AND dispatch_gate='open' "
                    "AND recovery_state='clean'",
                    (now, now, self.vault_id, permit.attempt_id, row["revision"]),
                ).rowcount
            if changed != 1:
                raise RevisionConflict("Transport observation lost its state CAS")
            self._journal(
                db,
                permit.attempt_id,
                "transport_observed",
                observation.as_dict(),
                now,
            )
            updated = self._load_attempt(db, permit.attempt_id)
            return {
                "observation": observation.as_dict(),
                "attempt": self._attempt_snapshot(updated),
            }

    def dispatch_status(self, command_id):
        """Read the redacted current transport projection for one dispatch command."""
        uuid_string(command_id)
        with self._transaction() as db:
            command = db.execute(
                "SELECT * FROM runtime_commands WHERE vault_id=? AND command_id=?",
                (self.vault_id, command_id),
            ).fetchone()
            if command is None or command["kind"] != "commit_budgeted_send_intent":
                raise KeyError(command_id)
            payload = _decode_canonical(
                command["payload"], command["payload_digest"], "dispatch command payload"
            )
            result = _decode_canonical(
                command["result"], command["result_digest"], "dispatch command result"
            )
            if (
                type(payload) is not dict
                or type(result) is not dict
                or result.get("intent_committed") is not True
                or result.get("attempt_id") != payload.get("attempt_id")
            ):
                raise CorruptLedger("Dispatch status command is invalid")
            attempt_id = result["attempt_id"]
            row = self._load_attempt(db, attempt_id)
            observed = list(db.execute(
                "SELECT payload,payload_digest FROM runtime_attempt_journal "
                "WHERE vault_id=? AND attempt_id=? AND transition='transport_observed'",
                (self.vault_id, attempt_id),
            ))
            observation = None
            if observed:
                if len(observed) != 1:
                    raise CorruptLedger("Transport observation is duplicated")
                observation = TransportObservation.from_dict(_decode_canonical(
                    observed[0]["payload"], observed[0]["payload_digest"],
                    "transport observation",
                ))
                if (
                    observation.command_id != command_id
                    or observation.permit_id != result.get("permit_id")
                ):
                    raise CorruptLedger("Transport status binding changed")
            snapshot = self._attempt_snapshot(row)
            with self._permit_lock:
                globally_inhibited = self._global_emergency_inhibited
            if globally_inhibited:
                state = "outcome_unknown"
                dispatch = {"state": "recovery_pending", "effect": "outcome_unknown"}
            elif observation is None:
                if (
                    snapshot["recovery_state"] == "pending"
                    or snapshot["phase"] == "terminal"
                ):
                    state = "outcome_unknown"
                    dispatch = {"state": "recovery_pending", "effect": "outcome_unknown"}
                else:
                    state = "pending"
                    dispatch = {"state": "intent_committed", "effect": "not_observed"}
            elif observation.effect == "transport_accepted":
                state = "running"
                dispatch = {"state": "transport_accepted", "effect": "transport_accepted"}
            elif observation.effect == "definitely_not_sent":
                state = "blocked"
                dispatch = {"state": "recovery_pending", "effect": observation.effect}
            else:
                state = "outcome_unknown"
                dispatch = {"state": "recovery_pending", "effect": observation.effect}
            return {"state": state, "dispatch": dispatch, "attempt": snapshot}

    @property
    def is_dispatch_emergency_inhibited(self):
        with self._permit_lock:
            return self._global_emergency_inhibited

    @property
    def pending_permit_count(self):
        with self._permit_lock:
            return len(self._pending_permits)

    def _assert_budget_policy_binding(self, db, policy_ref, policy):
        roots = self._domain._read_roots(db)
        self._domain._check_graph(db, (policy_ref,), roots)
        record, _, _ = self._domain._load(db, policy_ref, roots)
        if record.body["content"] != policy.domain_content():
            raise CorruptLedger(
                "Exact budget policy record does not bind the active budget session"
            )

    def _run_spec_for_attempt(self, db, spec):
        execution = db.execute(
            "SELECT run_id FROM runtime_node_executions WHERE vault_id=? AND id=?",
            (self.vault_id, spec.execution_id),
        ).fetchone()
        if execution is None:
            raise CorruptLedger("Attempt execution is missing")
        run = db.execute(
            "SELECT * FROM runtime_runs WHERE vault_id=? AND id=?",
            (self.vault_id, execution["run_id"]),
        ).fetchone()
        if run is None:
            raise CorruptLedger("Attempt run is missing")
        run_spec = RunSpec.from_dict(self._run_snapshot(run)["spec"])
        self._validate_run_bindings(db, run_spec)
        if run_spec.budget_policy_ref != spec.budget_policy_ref:
            raise CorruptLedger("Attempt budget policy no longer matches its run")
        return run_spec

    def _assert_committed_send(self, db, *, command_id, command_kind,
                               command_payload, command_result, spec, owner,
                               updated, committed_at_ms, budget_book,
                               budget_request):
        """Re-read every dispatch invariant after the final transactional write."""
        row = self._load_attempt(db, spec.attempt_id)
        current = self._attempt_snapshot(row)
        if (current != self._attempt_snapshot(updated)
                or current["phase"] != "send_intent"
                or current["dispatch_gate"] != "open"
                or current["send_finality"] != "may_have_started"
                or current["cancel_state"] != "none"
                or current["recovery_state"] != "clean"
                or current["revision"] != command_result["revision"]
                or current["send_intent_at_ms"] != committed_at_ms
                or OwnerIdentity.from_dict(current["lease_owner"]) != owner):
            raise CorruptLedger("Committed send-intent state failed final verification")

        journal_rows = list(db.execute(
            "SELECT payload,payload_digest,at_ms FROM runtime_attempt_journal "
            "WHERE vault_id=? AND attempt_id=? AND transition='send_intent'",
            (self.vault_id, spec.attempt_id),
        ))
        expected_journal = {
            "lease_fence": current["lease_fence"],
            "revision": current["revision"],
        }
        if (len(journal_rows) != 1
                or _decode_canonical(journal_rows[0]["payload"],
                                     journal_rows[0]["payload_digest"],
                                     "send-intent journal") != expected_journal
                or journal_rows[0]["at_ms"] != committed_at_ms):
            raise CorruptLedger("Committed send-intent journal failed final verification")

        event_rows = list(db.execute(
            "SELECT payload,payload_digest,at_ms FROM runtime_public_events "
            "WHERE vault_id=? AND event_type='attempt.dispatched' "
            "AND object_kind='attempt' AND object_id=?",
            (self.vault_id, spec.attempt_id),
        ))
        expected_event = event_metadata(
            "attempt.dispatched", {"attempt_no": spec.attempt_no}
        )
        if (len(event_rows) != 1
                or _decode_canonical(event_rows[0]["payload"],
                                     event_rows[0]["payload_digest"],
                                     "dispatch event") != expected_event
                or event_rows[0]["at_ms"] != committed_at_ms):
            raise CorruptLedger("Committed dispatch event failed final verification")

        if self._command_replay(
                db, command_id, command_kind, command_payload) != command_result:
            raise CorruptLedger("Committed dispatch command failed final verification")
        if budget_request is not None:
            run_spec = self._run_spec_for_attempt(db, spec)
            if run_spec.budget_session_id != budget_request.session_id:
                raise CorruptLedger("Committed run budget session binding changed")
            reservation, policy, budget_deadline, _ = \
                budget_book._assert_dispatched_in_transaction(
                db, budget_request.request_id, budget_request.session_id
            )
            if reservation.request_id != spec.reservation_id:
                raise CorruptLedger("Committed budget reservation binding changed")
            self._assert_budget_policy_binding(db, spec.budget_policy_ref, policy)
            return budget_deadline
        return None

    def _consume_pending_permit(self, permit, permit_type, budget_book):
        if type(permit) is not permit_type:
            raise DispatchBlocked("Exact process-local dispatch permit required")
        with self._permit_lock:
            if self._global_emergency_inhibited:
                raise DispatchBlocked("Process-local emergency inhibition is active")
            stored = self._pending_permits.get(permit.permit_id)
            if (type(stored) is not tuple or len(stored) != 6
                    or stored[0] is not permit or stored[1] is not budget_book):
                raise DispatchBlocked("Dispatch permit budget owner is absent or changed")
            if (stored[2] is not getattr(permit, "principal", None)
                    or stored[3] is not getattr(permit, "grant", None)
                    or stored[4] != getattr(getattr(permit, "principal", None), "id", None)
                    or stored[5] != getattr(getattr(permit, "grant", None), "id", None)):
                raise DispatchBlocked("Dispatch permit authorization binding changed")
            self._pending_permits.pop(permit.permit_id, None)
            if permit.attempt_id in self._emergency_inhibited:
                raise DispatchBlocked("Dispatch permit is absent, consumed, or inhibited")

    def _assert_permit_attempt_state(self, db, permit):
        now = self._now(db)
        row = self._load_attempt(db, permit.attempt_id)
        spec = AttemptSpec.from_dict(_decode_canonical(
            row["spec"], row["spec_digest"], "attempt spec"))
        if (row["phase"] != "send_intent" or row["dispatch_gate"] != "open"
                or row["cancel_state"] != "none" or row["lease_fence"] != permit.lease_fence
                or now >= row["lease_expires_at_ms"] or now >= spec.deadline_at_ms
                or spec.execution_id != permit.execution_id
                or spec.idempotency_key != permit.idempotency_key
                or spec.envelope_ref != permit.envelope_ref
                or spec.profile_ref != permit.profile_ref
                or spec.budget_policy_ref != permit.budget_policy_ref
                or spec.reservation_id != permit.reservation_id
                or spec.owner != permit.owner
                or row["lease_expires_at_ms"] != permit.lease_expires_at_ms
                or spec.deadline_at_ms != permit.deadline_at_ms
                or row["send_intent_at_ms"] != permit.issued_at_ms):
            raise DispatchBlocked("Durable attempt state revoked the dispatch permit")
        return spec, now

    def _consume_unbudgeted_permit_for_test(self, permit):
        with _writer():
            self._consume_pending_permit(permit, LedgerOnlyPermit, None)
            with self._transaction(write=True) as db:
                self._require_session(db)
                self._assert_permit_attempt_state(db, permit)
        return permit

    def _consume_dispatch_permit_window(self, permit, *, budget_book):
        # Anchor before every lock, graph check and SQLite/fsync operation. Wall-clock
        # samples occur later, so converting their remaining durations from this earlier
        # point can only shorten the transport window; validation latency is never added
        # back after permit consumption.
        anchor_monotonic = time.monotonic()
        if type(permit) is not DispatchPermit:
            raise DispatchBlocked("Exact budget-bound dispatch permit required")
        if type(budget_book) is not BudgetBook:
            raise DispatchBlocked("Exact BudgetBook is required for dispatch")
        if Path(os.path.abspath(budget_book.path)) != self._domain.path:
            raise DispatchBlocked("Dispatch budget must belong to the same vault")
        with _writer():
            self._consume_pending_permit(permit, DispatchPermit, budget_book)
            with self._transaction(write=True) as db:
                self._assert_dispatch_schema(db)
                BudgetBook._assert_transaction_schema(db)
                self._require_session(db)
                spec, runtime_now = self._assert_permit_attempt_state(db, permit)
                run_spec = self._run_spec_for_attempt(db, spec)
                if run_spec.budget_session_id != permit.budget_session_id:
                    raise DispatchBlocked("Dispatch run budget session binding changed")
                reservation, policy, budget_deadline, budget_now = \
                    budget_book._assert_dispatched_in_transaction(
                    db, permit.reservation_id, permit.budget_session_id
                )
                if (reservation.request_id != spec.reservation_id
                        or reservation.session_id != permit.budget_session_id
                        or budget_deadline
                        != permit.budget_deadline_epoch_seconds):
                    raise DispatchBlocked("Dispatch budget binding changed")
                self._assert_budget_policy_binding(db, spec.budget_policy_ref, policy)
        # Both trusted clocks are integer/floor clocks.  Remove one source-clock
        # tick so a transport deadline cannot extend into an unobserved partial tick.
        runtime_remaining = max(
            0,
            min(permit.deadline_at_ms, permit.lease_expires_at_ms)
            - runtime_now
            - 1,
        )
        budget_remaining = min(
            MAX_INTEGER,
            max(
                0,
                (permit.budget_deadline_epoch_seconds - budget_now - 1) * 1_000,
            ),
        )
        return ConsumedDispatchWindow(
            permit=permit,
            runtime_remaining_ms=runtime_remaining,
            budget_remaining_ms=budget_remaining,
            anchor_monotonic=anchor_monotonic,
        )

    def consume_dispatch_permit_window(self, permit, *, budget_book=None):
        """Consume once and return conservative remaining windows for transport."""

        return self._consume_dispatch_permit_window(
            permit, budget_book=budget_book
        )

    def consume_dispatch_permit(self, permit, *, budget_book=None):
        """Compatibility boundary returning the exact consumed permit."""

        return self._consume_dispatch_permit_window(
            permit, budget_book=budget_book
        ).permit

    def _revoke_permits(self, attempt_id):
        with self._permit_lock:
            for permit_id, stored in tuple(self._pending_permits.items()):
                permit = stored[0]
                if permit.attempt_id == attempt_id:
                    self._pending_permits.pop(permit_id, None)

    def request_cancel(self, command_id, attempt_id, *, expected_revision):
        payload = self._command_payload({"attempt_id": attempt_id,
                                         "expected_revision": expected_revision})
        try:
            with self._transaction(write=True) as db:
                replay = self._command_replay(db, command_id, "request_cancel", payload)
                if replay is not None:
                    self._revoke_permits(attempt_id)
                    return replay
                now = self._now(db)
                row = self._load_attempt(db, attempt_id)
                self._check_revision(row, expected_revision)
                if row["phase"] == "terminal":
                    result = {"applied": False, "attempt": self._attempt_snapshot(row)}
                    self._record_command(db, command_id, "request_cancel", payload, result, now)
                    self._revoke_permits(attempt_id)
                    return result
                if row["cancel_state"] == "requested":
                    result = {"applied": False, "attempt": self._attempt_snapshot(row)}
                    self._record_command(db, command_id, "request_cancel", payload, result, now)
                    self._revoke_permits(attempt_id)
                    return result
                changed = db.execute("UPDATE runtime_attempts SET dispatch_gate='closed',"
                    "cancel_state='requested',dispatch_blocked_at_ms=COALESCE(dispatch_blocked_at_ms,?),"
                    "revision=revision+1,updated_at_ms=? WHERE vault_id=? AND id=? AND revision=? "
                    "AND phase<>'terminal' AND cancel_state='none'",
                    (now, now, self.vault_id, attempt_id, expected_revision)).rowcount
                if changed != 1:
                    raise RevisionConflict("Cancellation gate close lost its CAS")
                updated = self._load_attempt(db, attempt_id)
                self._journal(db, attempt_id, "cancel_requested",
                              {"revision": updated["revision"]}, now)
                result = {"applied": True, "attempt": self._attempt_snapshot(updated)}
                self._record_command(db, command_id, "request_cancel", payload, result, now)
        except (sqlite3.Error, StorageError):
            with self._permit_lock:
                self._emergency_inhibited.add(attempt_id)
                self._revoke_permits(attempt_id)
            raise
        self._revoke_permits(attempt_id)
        return result

    def is_emergency_inhibited(self, attempt_id):
        uuid_string(attempt_id)
        with self._permit_lock:
            return attempt_id in self._emergency_inhibited

    def finish_cancellation(self, command_id, attempt_id, owner, observation, *, expected_revision):
        if type(owner) is not OwnerIdentity:
            raise LeaseOwnershipError("Exact owner identity is required")
        if type(observation) is not CancellationObservation:
            raise TypeError("Exact CancellationObservation required")
        payload = self._command_payload({"attempt_id": attempt_id, "owner": owner.as_dict(),
            "observation": observation.as_dict(), "expected_revision": expected_revision})
        with self._transaction(write=True) as db:
            replay = self._command_replay(db, command_id, "finish_cancellation", payload)
            if replay is not None:
                self._revoke_permits(attempt_id)
                return replay
            now = self._now(db)
            row = self._load_attempt(db, attempt_id)
            self._check_owner(row, owner)
            self._check_revision(row, expected_revision)
            if (row["phase"] == "terminal" or row["cancel_state"] != "requested"
                    or row["dispatch_gate"] != "closed"):
                raise InvalidTransition("Attempt has no durable pending cancellation")
            sent = row["send_intent_at_ms"] is not None
            if (not sent and (observation.outcome != "cancelled"
                              or observation.remote_terminal_observed != "not_observed")):
                raise InvalidTransition(
                    "A definitely-unsent cancellation cannot claim a remote or unknown outcome")
            if (sent and observation.outcome == "cancelled"
                    and observation.remote_terminal_observed != "cancelled"):
                raise InvalidTransition("Local closure cannot prove remote cancellation")
            send_finality = "remote_terminal" if observation.remote_terminal_observed != "not_observed" \
                else ("may_have_started" if sent else "definitely_not_sent")
            local_closed = now if observation.local_transport_closed else None
            changed = db.execute("UPDATE runtime_attempts SET phase='terminal',terminal_outcome=?,"
                "send_finality=?,recovery_state='reconciled',local_transport_closed_at_ms=?,"
                "owned_process_exit=?,remote_terminal_observed=?,usage_finality=?,"
                "revision=revision+1,updated_at_ms=? WHERE vault_id=? AND id=? AND revision=? "
                "AND phase<>'terminal' AND dispatch_gate='closed' AND cancel_state='requested'",
                (observation.outcome, send_finality, local_closed, observation.owned_process_exit,
                 observation.remote_terminal_observed, observation.usage_finality, now,
                 self.vault_id, attempt_id, expected_revision)).rowcount
            if changed != 1:
                raise RevisionConflict("Cancellation terminal transition lost its CAS")
            updated = self._load_attempt(db, attempt_id)
            self._journal(db, attempt_id, "cancel_terminal",
                          {"outcome": observation.outcome, "revision": updated["revision"]}, now)
            self._event(db, "attempt.terminal", "attempt", attempt_id,
                        {"outcome": observation.outcome}, now)
            result_value = self._attempt_snapshot(updated)
            self._record_command(db, command_id, "finish_cancellation", payload, result_value, now)
        self._revoke_permits(attempt_id)
        return result_value

    def accept_result(self, command_id, observation):
        if type(observation) is not ResultObservation:
            raise TypeError("accept_result requires an exact ResultObservation")
        if observation.result_ref is not None:
            self._verify_refs((observation.result_ref,))
        payload = self._command_payload({"observation": observation.as_dict()})
        encoded = canonical_json(observation.as_dict())
        semantic = _digest(canonical_json(observation.semantic_dict()))
        with self._transaction(write=True) as db:
            replay = self._command_replay(db, command_id, "accept_result", payload)
            if replay is not None:
                if replay.get("classification") == "accepted":
                    self._revoke_permits(observation.attempt_id)
                return replay
            now = self._now(db)
            row = self._load_attempt(db, observation.attempt_id)
            existing = db.execute("SELECT payload,payload_digest,classification FROM "
                "runtime_result_observations WHERE vault_id=? AND id=?",
                (self.vault_id, observation.observation_id)).fetchone()
            if existing is not None:
                prior = _decode_canonical(existing["payload"], existing["payload_digest"],
                                          "result observation")
                if prior != observation.as_dict() or bytes(existing["payload"]) != encoded:
                    raise ResultConflict("Observation ID was reused with different result")
                result_value = {"classification": existing["classification"],
                                "observation_id": observation.observation_id,
                                "attempt": self._attempt_snapshot(row)}
                self._record_command(db, command_id, "accept_result", payload, result_value, now)
                if existing["classification"] == "accepted":
                    self._revoke_permits(observation.attempt_id)
                return result_value
            observation_count = db.execute(
                "SELECT count(*) FROM runtime_result_observations "
                "WHERE vault_id=? AND attempt_id=?",
                (self.vault_id, observation.attempt_id),
            ).fetchone()[0]
            if observation_count >= MAX_RESULT_OBSERVATIONS:
                raise LedgerError("Result observation bound reached")
            spec = AttemptSpec.from_dict(_decode_canonical(
                row["spec"], row["spec_digest"], "attempt spec"))
            if (now >= spec.deadline_at_ms and row["phase"] != "terminal"
                    and row["cancel_state"] == "none"):
                sent = row["send_intent_at_ms"] is not None
                changed = db.execute("UPDATE runtime_attempts SET phase='terminal',"
                    "dispatch_gate='closed',send_finality=?,recovery_state='reconciled',"
                    "terminal_outcome='timed_out',dispatch_blocked_at_ms=COALESCE(dispatch_blocked_at_ms,?),"
                    "remote_terminal_observed='not_observed',usage_finality=?,revision=revision+1,"
                    "updated_at_ms=? WHERE vault_id=? AND id=? AND revision=? AND phase<>'terminal' "
                    "AND cancel_state='none'",
                    (row["send_finality"] if sent else "definitely_not_sent", now,
                     "unknown" if sent else "final", now, self.vault_id,
                     observation.attempt_id, row["revision"])).rowcount
                if changed != 1:
                    raise RevisionConflict("Deadline result quarantine lost its CAS")
                self._journal(db, observation.attempt_id, "recovery_terminal",
                              {"outcome": "timed_out", "reason": "deadline"}, now)
                self._event(db, "attempt.terminal", "attempt", observation.attempt_id,
                            {"outcome": "timed_out"}, now)
                row = self._load_attempt(db, observation.attempt_id)
            accepted = None
            if row["accepted_observation_id"] is not None:
                accepted = db.execute("SELECT semantic_digest FROM runtime_result_observations "
                    "WHERE vault_id=? AND id=?", (self.vault_id,
                    row["accepted_observation_id"])).fetchone()
                if accepted is None:
                    raise CorruptLedger("Accepted observation pointer is missing")
            recoverable = (row["recovery_state"] == "pending"
                           and row["cancel_state"] == "none"
                           and row["send_intent_at_ms"] is not None)
            eligible = (row["phase"] in {"send_intent", "running", "validating"}
                        and row["send_intent_at_ms"] is not None
                        and row["cancel_state"] == "none"
                        and (row["dispatch_gate"] == "open" or recoverable)
                        and row["terminal_outcome"] is None
                        and row["accepted_observation_id"] is None)
            if eligible:
                classification = "accepted"
            elif accepted is not None and accepted["semantic_digest"] == semantic:
                classification = "duplicate"
            else:
                classification = "late"
            db.execute("INSERT INTO runtime_result_observations"
                       "(vault_id,id,attempt_id,payload,payload_digest,semantic_digest,"
                       "classification,observed_at_ms) VALUES (?,?,?,?,?,?,?,?)",
                       (self.vault_id, observation.observation_id, observation.attempt_id,
                        encoded, _digest(encoded), semantic, classification, now))
            if observation.result_ref is not None:
                reference = observation.result_ref
                db.execute("INSERT INTO runtime_result_refs VALUES (?,?,?,?,?,?)",
                           (self.vault_id, observation.observation_id, reference.kind,
                            reference.id, reference.version, reference.sha256))
            if classification == "accepted":
                changed = db.execute("UPDATE runtime_attempts SET phase='terminal',dispatch_gate='closed',"
                    "send_finality=?,recovery_state='reconciled',terminal_outcome=?,"
                    "dispatch_blocked_at_ms=COALESCE(dispatch_blocked_at_ms,?),"
                    "remote_terminal_observed=?,usage_finality=?,accepted_observation_id=?,"
                    "revision=revision+1,updated_at_ms=? WHERE vault_id=? AND id=? AND revision=? "
                    "AND phase IN ('send_intent','running','validating') AND terminal_outcome IS NULL "
                    "AND accepted_observation_id IS NULL AND cancel_state='none'",
                    ("remote_terminal" if observation.remote_terminal_observed != "not_observed"
                     else row["send_finality"], observation.outcome, now,
                     observation.remote_terminal_observed, observation.usage_finality,
                     observation.observation_id, now, self.vault_id,
                     observation.attempt_id, row["revision"])).rowcount
                if changed != 1:
                    raise RevisionConflict("Terminal result acceptance lost its CAS")
                updated = self._load_attempt(db, observation.attempt_id)
                self._journal(db, observation.attempt_id, "result_accepted",
                              {"outcome": observation.outcome,
                               "revision": updated["revision"]}, now)
                self._event(db, "attempt.terminal", "attempt", observation.attempt_id,
                            {"outcome": observation.outcome}, now)
            else:
                transition = "result_duplicate" if classification == "duplicate" else "result_late"
                self._journal(db, observation.attempt_id, transition,
                              {"outcome": observation.outcome}, now)
                updated = row
            result_value = {"classification": classification,
                            "observation_id": observation.observation_id,
                            "attempt": self._attempt_snapshot(updated)}
            self._record_command(db, command_id, "accept_result", payload, result_value, now)
        if classification == "accepted":
            self._revoke_permits(observation.attempt_id)
        return result_value

    def write_checkpoint(self, command_id, run_id, namespace, cursor, *, expected_revision,
                         attempt_id=None):
        uuid_string(run_id)
        _bounded_text("checkpoint namespace", namespace, 128,
                      pattern=r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
        if type(cursor) is not bytes or len(cursor) > MAX_CHECKPOINT_BYTES:
            raise ValueError("Checkpoint cursor must be bounded opaque bytes")
        _nonnegative("expected_revision", expected_revision)
        if attempt_id is not None:
            uuid_string(attempt_id)
        header = {"run_id": run_id, "namespace": namespace,
                  "cursor_sha256": _digest(cursor), "cursor_size": len(cursor),
                  "expected_revision": expected_revision, "attempt_id": attempt_id}
        payload = self._command_payload(header)
        with self._transaction(write=True) as db:
            self._require_session(db)
            replay = self._command_replay(db, command_id, "write_checkpoint", payload)
            if replay is not None:
                current = self._checkpoint(db, run_id, namespace,
                                           revision=replay["revision"])
                if current["cursor"] != cursor:
                    raise CommandConflict("Checkpoint command digest collision/mismatch")
                return current
            now = self._now(db)
            run = db.execute("SELECT 1 FROM runtime_runs WHERE vault_id=? AND id=?",
                             (self.vault_id, run_id)).fetchone()
            if run is None:
                raise KeyError(run_id)
            latest = db.execute("SELECT max(revision) FROM runtime_checkpoints "
                "WHERE vault_id=? AND run_id=? AND namespace=?",
                (self.vault_id, run_id, namespace)).fetchone()[0]
            current_revision = 0 if latest is None else latest
            if current_revision != expected_revision:
                raise RevisionConflict("Checkpoint revision changed")
            if current_revision == 0:
                count = db.execute("SELECT count(DISTINCT namespace) FROM runtime_checkpoints "
                    "WHERE vault_id=? AND run_id=?", (self.vault_id, run_id)).fetchone()[0]
                if count >= MAX_CHECKPOINT_NAMESPACES:
                    raise LedgerError("Checkpoint namespace bound reached")
            bound_revision = bound_execution = bound_envelope = None
            if attempt_id is not None:
                attempt = self._load_attempt(db, attempt_id)
                execution = db.execute("SELECT run_id FROM runtime_node_executions "
                    "WHERE vault_id=? AND id=?", (self.vault_id, attempt["execution_id"])).fetchone()
                if execution is None or execution["run_id"] != run_id:
                    raise LedgerError("Checkpoint attempt belongs to another run")
                spec = AttemptSpec.from_dict(_decode_canonical(
                    attempt["spec"], attempt["spec_digest"], "attempt spec"))
                bound_revision = attempt["revision"]
                bound_execution = spec.execution_id
                bound_envelope = spec.envelope_ref.sha256
            revision = current_revision + 1
            db.execute("INSERT INTO runtime_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (self.vault_id, run_id, namespace, revision, cursor, _digest(cursor),
                        attempt_id, bound_revision, bound_execution, bound_envelope, now, command_id))
            result_value = self._checkpoint(db, run_id, namespace, revision=revision)
            command_result = {key: value for key, value in result_value.items() if key != "cursor"}
            self._record_command(db, command_id, "write_checkpoint", payload, command_result, now)
            return result_value

    def _checkpoint(self, db, run_id, namespace, *, revision=None):
        sql = ("SELECT * FROM runtime_checkpoints WHERE vault_id=? AND run_id=? AND namespace=? "
               + ("ORDER BY revision DESC LIMIT 1" if revision is None else "AND revision=?"))
        parameters = (self.vault_id, run_id, namespace) if revision is None else (
            self.vault_id, run_id, namespace, revision)
        row = db.execute(sql, parameters).fetchone()
        if row is None:
            raise KeyError((run_id, namespace) if revision is None else (run_id, namespace, revision))
        cursor = _blob(row["cursor"], "checkpoint cursor")
        if _digest(cursor) != row["cursor_sha256"] or len(cursor) > MAX_CHECKPOINT_BYTES:
            raise CorruptLedger("Checkpoint cursor digest or bound is invalid")
        try:
            uuid_string(row["run_id"])
            _bounded_text("checkpoint namespace", row["namespace"], 128,
                          pattern=r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
            positive_integer(row["revision"])
            _nonnegative("created_at_ms", row["created_at_ms"])
            uuid_string(row["command_id"])
        except (DomainContractError, ValueError) as exc:
            raise CorruptLedger("Checkpoint metadata is invalid") from exc
        binding = (row["bound_attempt_id"], row["bound_attempt_revision"],
                   row["bound_execution_id"], row["bound_envelope_sha256"])
        if any(value is None for value in binding) != all(value is None for value in binding):
            raise CorruptLedger("Checkpoint binding is partial")
        if row["bound_attempt_id"] is not None:
            try:
                uuid_string(row["bound_attempt_id"])
                positive_integer(row["bound_attempt_revision"])
                uuid_string(row["bound_execution_id"])
                if (type(row["bound_envelope_sha256"]) is not str
                        or re.fullmatch(r"[0-9a-f]{64}", row["bound_envelope_sha256"]) is None):
                    raise DomainContractError("Invalid bound envelope digest")
            except (DomainContractError, TypeError, ValueError) as exc:
                raise CorruptLedger("Checkpoint binding metadata is invalid") from exc
            attempt = self._load_attempt(db, row["bound_attempt_id"])
            spec = AttemptSpec.from_dict(_decode_canonical(
                attempt["spec"], attempt["spec_digest"], "attempt spec"))
            execution = db.execute("SELECT run_id FROM runtime_node_executions "
                "WHERE vault_id=? AND id=?", (self.vault_id,
                                               row["bound_execution_id"])).fetchone()
            if (spec.execution_id != row["bound_execution_id"]
                    or spec.envelope_ref.sha256 != row["bound_envelope_sha256"]
                    or row["bound_attempt_revision"] > attempt["revision"]
                    or execution is None or execution["run_id"] != run_id):
                raise CorruptLedger("Checkpoint binding no longer matches exact ledger state")
        return {"run_id": run_id, "namespace": namespace, "revision": row["revision"],
                "cursor": cursor, "cursor_sha256": row["cursor_sha256"],
                "bound_attempt_id": row["bound_attempt_id"],
                "bound_attempt_revision": row["bound_attempt_revision"],
                "bound_execution_id": row["bound_execution_id"],
                "bound_envelope_sha256": row["bound_envelope_sha256"],
                "created_at_ms": row["created_at_ms"]}

    def read_checkpoint(self, run_id, namespace, *, revision=None):
        uuid_string(run_id)
        _bounded_text("checkpoint namespace", namespace, 128,
                      pattern=r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
        if revision is not None:
            positive_integer(revision)
        with self._transaction() as db:
            return self._checkpoint(db, run_id, namespace, revision=revision)

    def _validated_run_checkpoints(self, db, run_id):
        rows = db.execute("SELECT run_id,namespace,max(revision) AS revision "
            "FROM runtime_checkpoints WHERE vault_id=? AND run_id=? GROUP BY run_id,namespace "
            "ORDER BY namespace", (self.vault_id, run_id)).fetchall()
        if len(rows) > MAX_CHECKPOINT_NAMESPACES:
            raise CorruptLedger("Run checkpoint namespace bound exceeded")
        for checkpoint in rows:
            self._checkpoint(db, checkpoint["run_id"], checkpoint["namespace"],
                             revision=checkpoint["revision"])
        return rows

    def _validated_active_checkpoints(self, db):
        rows = db.execute(
            "WITH active_runs AS ("
            "SELECT DISTINCT execution.run_id FROM runtime_node_executions AS execution "
            "JOIN runtime_attempts AS attempt ON attempt.vault_id=execution.vault_id "
            "AND attempt.execution_id=execution.id "
            "WHERE execution.vault_id=? AND attempt.phase<>'terminal') "
            "SELECT checkpoint.run_id,checkpoint.namespace,max(checkpoint.revision) AS revision "
            "FROM runtime_checkpoints AS checkpoint JOIN active_runs "
            "ON active_runs.run_id=checkpoint.run_id WHERE checkpoint.vault_id=? "
            "GROUP BY checkpoint.run_id,checkpoint.namespace ORDER BY checkpoint.run_id,checkpoint.namespace",
            (self.vault_id, self.vault_id),
        ).fetchall()
        maximum = MAX_ACTIVE_ATTEMPTS * MAX_CHECKPOINT_NAMESPACES
        if len(rows) > maximum:
            raise CorruptLedger("Active checkpoint recovery bound exceeded")
        for checkpoint in rows:
            self._checkpoint(db, checkpoint["run_id"], checkpoint["namespace"],
                             revision=checkpoint["revision"])
        return rows

    def checkpoint_for_replay(self, run_id, namespace, *, revision=None):
        uuid_string(run_id)
        _bounded_text("checkpoint namespace", namespace, 128,
                      pattern=r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
        if revision is not None:
            positive_integer(revision)
        with self._transaction() as db:
            self._require_session(db)
            return self._checkpoint(db, run_id, namespace, revision=revision)

    def recovery_snapshot(self):
        with self._transaction() as db:
            rows = db.execute("SELECT * FROM runtime_attempts WHERE vault_id=? AND phase<>'terminal' "
                              "ORDER BY created_at_ms,id", (self.vault_id,)).fetchall()
            if len(rows) > MAX_ACTIVE_ATTEMPTS:
                raise CorruptLedger("Active attempt bound exceeded")
            checkpoints = self._validated_active_checkpoints(db)
            validated = [self._load_attempt(db, row["id"]) for row in rows]
            return {"attempts": [self._attempt_snapshot(row) for row in validated],
                    "checkpoints": [dict(row) for row in checkpoints],
                    "dispatch_enabled": False}

    def reconcile_startup(self, command_id, *, observed_owners):
        if type(observed_owners) is not dict or len(observed_owners) > MAX_ACTIVE_ATTEMPTS:
            raise ValueError("Observed owners must be a bounded exact mapping")
        normalized = {}
        for attempt_id, value in observed_owners.items():
            uuid_string(attempt_id)
            if type(value) is not OwnerIdentity:
                raise ValueError("Observed owner must include exact nonce and process start identity")
            normalized[attempt_id] = value.as_dict()
        payload = self._command_payload({"observed_owners": normalized})
        with self._transaction(write=True) as db:
            replay = self._command_replay(db, command_id, "reconcile_startup", payload)
            if replay is not None:
                current = db.execute("SELECT active_session_id FROM runtime_control "
                                     "WHERE singleton=1").fetchone()
                self._startup_reconciled = bool(
                    self._startup_reconciled and current is not None
                    and current["active_session_id"] == self._session_id)
                with self._permit_lock:
                    self._pending_permits.clear()
                return replay
            now = self._now(db)
            rows = db.execute("SELECT * FROM runtime_attempts WHERE vault_id=? AND phase<>'terminal' "
                              "ORDER BY created_at_ms,id", (self.vault_id,)).fetchall()
            if len(rows) > MAX_ACTIVE_ATTEMPTS:
                raise CorruptLedger("Active attempt recovery bound exceeded")
            ids = {row["id"] for row in rows}
            if set(observed_owners) - ids:
                raise LedgerError("Observed owner names an unknown or terminal attempt")
            checkpoints = self._validated_active_checkpoints(db)
            recovery_pending = unknown = definitely_unsent = 0
            for row in rows:
                row = self._load_attempt(db, row["id"])
                stored_owner = OwnerIdentity.from_dict(_decode_canonical(
                    row["lease_owner"], row["lease_owner_digest"], "lease owner"))
                observed = observed_owners.get(row["id"])
                sent = row["send_intent_at_ms"] is not None
                gate_time = (row["dispatch_blocked_at_ms"]
                             if row["dispatch_blocked_at_ms"] is not None else now)
                if not sent:
                    terminal = row["cancel_state"] == "requested"
                    phase = "terminal" if terminal else row["phase"]
                    outcome = "cancelled" if terminal else None
                    recovery = "reconciled" if terminal else "pending"
                    transition = "recovery_terminal" if terminal else "recovery_pending"
                    definitely_unsent += 1
                    if not terminal:
                        recovery_pending += 1
                    changed = db.execute("UPDATE runtime_attempts SET phase=?,dispatch_gate='closed',"
                        "send_finality='definitely_not_sent',recovery_state=?,terminal_outcome=?,"
                        "dispatch_blocked_at_ms=?,usage_finality=?,revision=revision+1,updated_at_ms=? "
                        "WHERE vault_id=? AND id=? AND revision=? AND phase<>'terminal'",
                        (phase, recovery, outcome, gate_time, "final" if terminal else row["usage_finality"],
                         now, self.vault_id, row["id"], row["revision"])).rowcount
                    if changed != 1:
                        raise RevisionConflict("Unsent recovery lost its CAS")
                    self._journal(db, row["id"], transition,
                                  {"reason": "restart", "sent": False}, now)
                    if terminal:
                        self._event(db, "attempt.terminal", "attempt", row["id"],
                                    {"outcome": "cancelled"}, now)
                elif (observed == stored_owner and now < row["lease_expires_at_ms"]
                      and row["cancel_state"] == "none"):
                    recovery_pending += 1
                    changed = db.execute("UPDATE runtime_attempts SET dispatch_gate='closed',"
                        "recovery_state='pending',dispatch_blocked_at_ms=?,revision=revision+1,updated_at_ms=? "
                        "WHERE vault_id=? AND id=? AND revision=? AND phase<>'terminal'",
                        (gate_time, now, self.vault_id, row["id"], row["revision"])).rowcount
                    if changed != 1:
                        raise RevisionConflict("Owned recovery transition lost its CAS")
                    self._journal(db, row["id"], "recovery_pending",
                                  {"reason": "restart", "sent": True}, now)
                else:
                    unknown += 1
                    changed = db.execute("UPDATE runtime_attempts SET phase='terminal',"
                        "dispatch_gate='closed',recovery_state='reconciled',terminal_outcome='outcome_unknown',"
                        "dispatch_blocked_at_ms=?,remote_terminal_observed='not_observed',"
                        "usage_finality='unknown',revision=revision+1,updated_at_ms=? "
                        "WHERE vault_id=? AND id=? AND revision=? AND phase<>'terminal'",
                        (gate_time, now, self.vault_id, row["id"], row["revision"])).rowcount
                    if changed != 1:
                        raise RevisionConflict("Unknown recovery transition lost its CAS")
                    self._journal(db, row["id"], "recovery_terminal",
                                  {"outcome": "outcome_unknown", "reason": "restart"}, now)
                    self._event(db, "attempt.terminal", "attempt", row["id"],
                                {"outcome": "outcome_unknown"}, now)
            result = {"recovery_pending_count": recovery_pending, "unknown_count": unknown,
                      "definitely_unsent_count": definitely_unsent,
                      "checkpoint_count": len(checkpoints), "redispatched_count": 0}
            self._event(db, "recovery.reconciled", "vault_genesis", self.vault_id,
                        {"recovered_count": recovery_pending,
                         "unknown_count": unknown}, now)
            self._record_command(db, command_id, "reconcile_startup", payload, result, now)
            db.execute("UPDATE runtime_control SET active_session_id=?,"
                       "reconciliation_generation=reconciliation_generation+1 WHERE singleton=1",
                       (self._session_id,))
        with self._permit_lock:
            self._pending_permits.clear()
        self._startup_reconciled = True
        return result

    def get_run(self, run_id):
        uuid_string(run_id)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM runtime_runs WHERE vault_id=? AND id=?",
                             (self.vault_id, run_id)).fetchone()
            if row is None:
                raise KeyError(run_id)
            result = self._run_snapshot(row)
            spec = RunSpec.from_dict(result["spec"])
            self._validate_run_bindings(db, spec)
        self._verify_refs((spec.work_revision_ref, spec.environment_ref, spec.consent_ref,
                           spec.budget_policy_ref, spec.manifest_ref))
        return result

    def get_execution(self, execution_id):
        uuid_string(execution_id)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM runtime_node_executions WHERE vault_id=? AND id=?",
                             (self.vault_id, execution_id)).fetchone()
            if row is None:
                raise KeyError(execution_id)
            result = self._execution_snapshot(row)
            spec = ExecutionSpec.from_dict(result["spec"])
            self._validate_execution_bindings(db, spec)
            return result

    def get_attempt(self, attempt_id):
        with self._transaction() as db:
            row = self._load_attempt(db, attempt_id)
            result = self._attempt_snapshot(row)
        spec = AttemptSpec.from_dict(result["spec"])
        self._verify_refs((spec.envelope_ref, spec.profile_ref, spec.budget_policy_ref))
        return result

    def result_observations(self, attempt_id):
        uuid_string(attempt_id)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM runtime_attempts WHERE vault_id=? AND id=?",
                          (self.vault_id, attempt_id)).fetchone() is None:
                raise KeyError(attempt_id)
            rows = db.execute("SELECT * FROM runtime_result_observations WHERE vault_id=? "
                "AND attempt_id=? ORDER BY sequence", (self.vault_id, attempt_id)).fetchall()
            if len(rows) > MAX_RESULT_OBSERVATIONS:
                raise CorruptLedger("Result observation read bound exceeded")
            result = []
            for row in rows:
                value = _decode_canonical(row["payload"], row["payload_digest"],
                                          "result observation")
                observation = ResultObservation.from_dict(value)
                if (observation.attempt_id != attempt_id
                        or _digest(canonical_json(observation.semantic_dict())) != row["semantic_digest"]
                        or row["classification"] not in {"accepted", "duplicate", "late"}):
                    raise CorruptLedger("Result observation index/payload mismatch")
                self._validate_result_binding(db, observation)
                try:
                    positive_integer(row["sequence"])
                    _nonnegative("observed_at_ms", row["observed_at_ms"])
                except (DomainContractError, ValueError) as exc:
                    raise CorruptLedger("Result observation ordering metadata is invalid") from exc
                result.append({**observation.as_dict(), "classification": row["classification"],
                               "observed_at_ms": row["observed_at_ms"]})
            return result

    def lookup_committed_result(self, attempt_id, execution_id, envelope_ref):
        uuid_string(attempt_id)
        uuid_string(execution_id)
        if type(envelope_ref) is not EntityRef or envelope_ref.kind != "execution_envelope":
            raise DomainContractError("Exact execution envelope reference required")
        with self._transaction() as db:
            row = self._load_attempt(db, attempt_id)
            spec = AttemptSpec.from_dict(_decode_canonical(row["spec"], row["spec_digest"], "attempt spec"))
            if spec.execution_id != execution_id or spec.envelope_ref != envelope_ref:
                return None
            observation_id = row["accepted_observation_id"]
            if observation_id is None:
                return None
            result = db.execute("SELECT * FROM runtime_result_observations WHERE vault_id=? AND id=?",
                                (self.vault_id, observation_id)).fetchone()
            if result is None or result["classification"] != "accepted":
                raise CorruptLedger("Committed result pointer is invalid")
            observation = ResultObservation.from_dict(_decode_canonical(
                result["payload"], result["payload_digest"], "result observation"))
            self._validate_result_binding(db, observation)
            value = observation.as_dict()
        if observation.result_ref is not None:
            self._verify_refs((observation.result_ref,))
        return value

    def events(self, *, after_sequence, limit):
        _nonnegative("after_sequence", after_sequence)
        _bounded_positive("limit", limit, MAX_PAGE)
        with self._transaction() as db:
            rows = db.execute("SELECT * FROM runtime_public_events WHERE vault_id=? AND sequence>? "
                "ORDER BY sequence LIMIT ?", (self.vault_id, after_sequence, limit)).fetchall()
            result = []
            for row in rows:
                payload = _decode_canonical(row["payload"], row["payload_digest"], "public event")
                try:
                    validated = event_metadata(row["event_type"], payload)
                    uuid_string(row["object_id"])
                    positive_integer(row["sequence"])
                    _nonnegative("event at_ms", row["at_ms"])
                    if row["object_kind"] not in {"vault_genesis", "run", "attempt"}:
                        raise DomainContractError("Invalid runtime event object kind")
                except (DomainContractError, TypeError, ValueError) as exc:
                    raise CorruptLedger("Persisted public runtime event is invalid") from exc
                result.append({"sequence": row["sequence"], "event_type": row["event_type"],
                               "object_kind": row["object_kind"], "object_id": row["object_id"],
                               "payload": validated, "at_ms": row["at_ms"]})
            return result

    def attempt_journal(self, attempt_id, *, after_sequence=0, limit=MAX_PAGE):
        uuid_string(attempt_id)
        _nonnegative("after_sequence", after_sequence)
        _bounded_positive("limit", limit, MAX_PAGE)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM runtime_attempts WHERE vault_id=? AND id=?",
                          (self.vault_id, attempt_id)).fetchone() is None:
                raise KeyError(attempt_id)
            rows = db.execute("SELECT * FROM runtime_attempt_journal WHERE vault_id=? "
                "AND attempt_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (self.vault_id, attempt_id, after_sequence, limit)).fetchall()
            result = []
            for row in rows:
                payload = _decode_canonical(row["payload"], row["payload_digest"], "attempt journal")
                if (row["transition"] not in JOURNAL_TRANSITIONS or type(payload) is not dict
                        or type(row["sequence"]) is not int or row["sequence"] <= 0
                        or type(row["at_ms"]) is not int or row["at_ms"] < 0):
                    raise CorruptLedger("Attempt journal entry is invalid")
                result.append({"sequence": row["sequence"], "transition": row["transition"],
                               "payload": payload, "at_ms": row["at_ms"]})
            return result
