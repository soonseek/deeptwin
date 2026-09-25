"""Exact design approval and environment-version preparation (US2, T036 B).

`이 설계로 준비` is a human's authenticated explicit act on one EXACT design
version (experience.md §6.3): the approval binds the accepted candidate's
graph hash, the passed criticism verdict for that exact candidate, and the
concrete configuration refs (model bindings, tool grants, observation
contract). It never includes work start, un-granted account or data access,
external sends, or operational promotion of later changes — a design changed
after approval is a different hash, and a stale approval prepares nothing.
Preparation is compare-and-swap on the environment head: the expected head
must still be current, each approval prepares at most once, and the prepared
version's status is "prepared" — this module exposes no activation path, so
preparation can never masquerade as operational promotion (promotion is the
growth contract's separate human act). The approval additionally binds ONE
environment: it never prepares any other environment. EnvironmentState is an
immutable value, so single-use enforcement across restarts belongs to the
storage layer (CAS on the head, exactly as growth_store does for the growth
chain); this module refuses every replay it can see in-value. Values are
issued, never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256

from ..domain.refs import DomainContractError, EntityRef, canonical_json
from .critic_qualification import is_issued_critic_qualification
from .design import is_accepted_candidate
from .design_criticism import verdict_binds_candidate
from .owner_decisions import is_issued_owner_decision, subject_digest

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_ISSUE_TOKEN = object()


class EnvironmentContractError(ValueError):
    """A design approval or environment preparation is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise EnvironmentContractError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise EnvironmentContractError(f"invalid {label} reference kind")
    return result


def _stamp(value, label):
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise EnvironmentContractError(f"{label} must be a canonical UTC timestamp")
    try:
        # Naive-parse only: the exact string is stored verbatim; this call
        # validates calendar reality, never produces a datetime value.
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")  # noqa: DTZ007
    except ValueError as exc:
        raise EnvironmentContractError(
            f"{label} must be a canonical UTC timestamp"
        ) from exc
    return value


@dataclass(frozen=True, slots=True, init=False)
class DesignApproval:
    """One human's authenticated approval of one exact design version."""

    environment_id: str
    design_ref: EntityRef
    verdict_sha: str
    candidate_id: str
    candidate_version: int
    approver_id: str
    approver_evidence: EntityRef
    approved_at: str
    model_bindings: EntityRef
    tool_permissions: EntityRef
    observation_contract: EntityRef
    critic_qualification: dict
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "design-approval-v2",
            "environment_id": self.environment_id,
            "design_ref": self.design_ref.as_dict(),
            "verdict_sha": self.verdict_sha,
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "approver_id": self.approver_id,
            "approver_evidence_ref": self.approver_evidence.as_dict(),
            "approved_at": self.approved_at,
            "model_bindings_ref": self.model_bindings.as_dict(),
            "tool_permissions_ref": self.tool_permissions.as_dict(),
            "observation_contract_ref": self.observation_contract.as_dict(),
            "critic_qualification": dict(self.critic_qualification),
        }

    @property
    def approval_sha(self) -> str:
        return sha256(canonical_json(self.as_dict())).hexdigest()


DESIGN_APPROVAL_SUBJECT_SCHEMA_VERSION = "design-approval-subject-v2"
_SUBJECT_KEYS = frozenset({
    "environment", "candidate", "verdict", "model_bindings", "tool_permissions",
    "observation_contract", "critic_qualification",
})


def _identity(ref: EntityRef) -> dict:
    # an exact identity including its kind, never the four-key reference
    # shape the store would try to resolve (design and binding records may
    # not exist yet)
    return {
        "entity_kind": ref.kind,
        "id": ref.id,
        "version": ref.version,
        "sha256": ref.sha256,
    }


def design_approval_subject(value) -> dict:
    """The exact subject a human approves: one passed design version for one
    environment with its bindings. Both the approval screen and
    `record_design_approval` derive it from the same inputs, so the owner's
    recorded decision can bind it by canonical digest."""

    if type(value) is not dict or set(value) - {"approval"} != _SUBJECT_KEYS:
        raise EnvironmentContractError("expected the exact design approval object")
    environment_id = value["environment"]
    if type(environment_id) is not str or _UUID.fullmatch(environment_id) is None:
        raise EnvironmentContractError("environment id is not a canonical UUID")
    candidate = value["candidate"]
    if not is_accepted_candidate(candidate):
        raise EnvironmentContractError("an accepted design candidate is required")
    verdict = value["verdict"]
    if not verdict_binds_candidate(verdict, candidate):
        # Only the fold issues verdicts, and a verdict binds its candidate
        # by content hash — a constructed look-alike or a verdict earned by
        # a different design approves nothing (FR-006).
        raise EnvironmentContractError(
            "a fold-issued verdict bound to this exact design is required"
        )
    if verdict.status != "passed":
        # A mandatory defect or missing evidence is never approvable; a
        # derived (select/edit/merge) design must complete its own
        # re-review into a passed candidate first.
        raise EnvironmentContractError("only a passed design version is approvable")
    critic = value["critic_qualification"]
    if not is_issued_critic_qualification(critic):
        raise EnvironmentContractError("the critic configuration's qualification state is required")
    if critic.status != "qualified":
        # A verdict is only as trustworthy as the critic configuration that
        # produced it: an unknown, calibration-only or failed critic
        # qualification never lets a passed verdict be approved (FR-006).
        raise EnvironmentContractError(
            f"the critic configuration is not qualified ({critic.status}: {critic.reason})"
        )
    return {
        "schema_version": DESIGN_APPROVAL_SUBJECT_SCHEMA_VERSION,
        "environment_id": environment_id,
        "design": _identity(candidate.graph_ref),
        "verdict_sha256": sha256(canonical_json(verdict.as_dict())).hexdigest(),
        "candidate_id": candidate.candidate_id,
        "candidate_version": candidate.version,
        "model_bindings": _identity(
            _ref(value["model_bindings"], "model_choice", "model bindings")
        ),
        "tool_permissions": _identity(
            _ref(value["tool_permissions"], "grant", "tool permissions")
        ),
        "observation_contract": _identity(
            _ref(value["observation_contract"], "observation_contract",
                 "observation contract")
        ),
        "critic_qualification": critic.as_dict(),
    }


def design_approval_evidence_subject(approval) -> dict:
    """The subject the owner decision behind an issued DesignApproval must
    carry — rebuilt from the approval alone, so a store can check that the
    evidence it resolves is over exactly this design."""

    if not is_issued_design_approval(approval):
        raise EnvironmentContractError("a recorded design approval is required")
    return {
        "schema_version": DESIGN_APPROVAL_SUBJECT_SCHEMA_VERSION,
        "environment_id": approval.environment_id,
        "design": _identity(approval.design_ref),
        "verdict_sha256": approval.verdict_sha,
        "candidate_id": approval.candidate_id,
        "candidate_version": approval.candidate_version,
        "model_bindings": _identity(approval.model_bindings),
        "tool_permissions": _identity(approval.tool_permissions),
        "observation_contract": _identity(approval.observation_contract),
        "critic_qualification": dict(approval.critic_qualification),
    }


def record_design_approval(value) -> DesignApproval:
    """Record one explicit approval; absence or silence records nothing.

    The approver, evidence and time come only from an owner-recorded
    decision (`owner_decisions`) over exactly this design subject — the
    caller declares nothing about authentication.
    """

    if type(value) is not dict or set(value) != _SUBJECT_KEYS | {"approval"}:
        raise EnvironmentContractError("expected the exact design approval object")
    subject = design_approval_subject(value)
    approval = value["approval"]
    if not is_issued_owner_decision(approval):
        raise EnvironmentContractError("approval requires an owner-recorded decision")
    if (
        approval.subject_kind != "design_approval"
        or approval.subject != subject
        or approval.subject_sha256 != subject_digest(subject)
    ):
        # The human decided over one exact subject; a decision over any
        # other design, environment, verdict or binding approves nothing.
        raise EnvironmentContractError("the decision is not over this exact design")
    if approval.decision != "approve":
        raise EnvironmentContractError("a recorded reject approves nothing")
    actor_id = approval.actor_ref.id
    if type(actor_id) is not str or _UUID.fullmatch(actor_id) is None:
        raise EnvironmentContractError("approver id is not a canonical UUID")
    candidate = value["candidate"]
    return _issue(
        DesignApproval,
        environment_id=subject["environment_id"],
        design_ref=candidate.graph_ref,
        verdict_sha=subject["verdict_sha256"],
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.version,
        approver_id=actor_id,
        approver_evidence=approval.approval_ref,
        approved_at=_stamp(approval.decided_at_utc, "approval time"),
        model_bindings=_ref(
            value["model_bindings"], "model_choice", "model bindings",
        ),
        tool_permissions=_ref(
            value["tool_permissions"], "grant", "tool permissions",
        ),
        observation_contract=_ref(
            value["observation_contract"], "observation_contract",
            "observation contract",
        ),
        critic_qualification=subject["critic_qualification"],
        _issuer_token=_ISSUE_TOKEN,
    )


@dataclass(frozen=True, slots=True, init=False)
class EnvironmentVersion:
    """One prepared environment version; prepared is never active."""

    environment_id: str
    version: int
    design_ref: EntityRef
    approval_sha: str
    status: str
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "environment-version-v1",
            "environment_id": self.environment_id,
            "version": self.version,
            "design_ref": self.design_ref.as_dict(),
            "approval_sha": self.approval_sha,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True, init=False)
class EnvironmentState:
    """One environment's preparation head and consumed approvals."""

    environment_id: str
    head: int
    consumed_approvals: tuple[str, ...]
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "environment-state-v1",
            "environment_id": self.environment_id,
            "head": self.head,
            "consumed_approvals": list(self.consumed_approvals),
        }


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def is_issued_design_approval(value: object) -> bool:
    """True only for an approval recorded through this module."""

    return (
        type(value) is DesignApproval
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def is_issued_environment_version(value: object) -> bool:
    """True only for a version prepared through this module."""

    return (
        type(value) is EnvironmentVersion
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def is_issued_environment_state(value: object) -> bool:
    """True only for a state issued through this module."""

    return (
        type(value) is EnvironmentState
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def restore_environment_state(value) -> EnvironmentState:
    """Rebuild one persisted state; trust is the store's hash chain, so the
    payload itself is revalidated strictly and inconsistencies are refused."""

    if type(value) is not dict or set(value) != {
        "schema_version", "environment_id", "head", "consumed_approvals",
    }:
        raise EnvironmentContractError(
            "expected the exact persisted environment state"
        )
    if value["schema_version"] != "environment-state-v1":
        raise EnvironmentContractError("unknown environment state schema")
    environment_id = value["environment_id"]
    if type(environment_id) is not str or _UUID.fullmatch(environment_id) is None:
        raise EnvironmentContractError("environment id is not a canonical UUID")
    head = value["head"]
    if type(head) is not int or not 0 <= head <= 1_000_000:
        raise EnvironmentContractError("the environment head is out of bounds")
    consumed = value["consumed_approvals"]
    if (
        type(consumed) is not list or len(consumed) > head
        or any(
            type(item) is not str or _SHA256.fullmatch(item) is None
            for item in consumed
        )
        or len(set(consumed)) != len(consumed)
    ):
        raise EnvironmentContractError("consumed approvals are inconsistent")
    return _issue(
        EnvironmentState,
        environment_id=environment_id,
        head=head,
        consumed_approvals=tuple(consumed),
        _issuer_token=_ISSUE_TOKEN,
    )


def open_environment(environment_id) -> EnvironmentState:
    if type(environment_id) is not str or _UUID.fullmatch(environment_id) is None:
        raise EnvironmentContractError("environment id is not a canonical UUID")
    return _issue(
        EnvironmentState,
        environment_id=environment_id,
        head=0,
        consumed_approvals=(),
        _issuer_token=_ISSUE_TOKEN,
    )


def prepare_environment_version(state, approval, *, expected_head):
    """Conditionally prepare the exact approved design, or refuse honestly."""

    if (
        type(state) is not EnvironmentState
        or getattr(state, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise EnvironmentContractError("a framework-issued environment state is required")
    if (
        type(approval) is not DesignApproval
        or getattr(approval, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise EnvironmentContractError("a recorded design approval is required")
    if state.environment_id != approval.environment_id:
        # The human approved this design FOR one environment; the act never
        # extends to any other environment (FR-008).
        raise EnvironmentContractError(
            "the approval does not belong to this environment"
        )
    if type(expected_head) is not int or expected_head != state.head:
        # The environment moved since the approval was formed: re-compare
        # and re-approve; the stale expectation prepares nothing.
        raise EnvironmentContractError("the environment head changed since approval")
    approval_sha = approval.approval_sha
    if approval_sha in state.consumed_approvals:
        raise EnvironmentContractError("this approval already prepared a version")
    if state.head >= 1_000_000:
        raise EnvironmentContractError("the environment version space is exhausted")
    version = _issue(
        EnvironmentVersion,
        environment_id=state.environment_id,
        version=state.head + 1,
        design_ref=approval.design_ref,
        approval_sha=approval_sha,
        # Preparation approves configuration; it never starts work and it
        # never operationally promotes anything.
        status="prepared",
        _issuer_token=_ISSUE_TOKEN,
    )
    new_state = _issue(
        EnvironmentState,
        environment_id=state.environment_id,
        head=state.head + 1,
        consumed_approvals=(*state.consumed_approvals, approval_sha),
        _issuer_token=_ISSUE_TOKEN,
    )
    return version, new_state


__all__ = [
    "DesignApproval",
    "EnvironmentContractError",
    "EnvironmentState",
    "EnvironmentVersion",
    "is_issued_design_approval",
    "is_issued_environment_state",
    "is_issued_environment_version",
    "open_environment",
    "prepare_environment_version",
    "record_design_approval",
    "restore_environment_state",
]
