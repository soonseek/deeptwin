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
growth contract's separate human act). Values are issued, never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256

from ..domain.refs import DomainContractError, EntityRef, canonical_json
from .design import is_accepted_candidate
from .design_criticism import CandidateVerdict

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_ISSUE_TOKEN = object()


class EnvironmentError(ValueError):
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
        raise EnvironmentError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise EnvironmentError(f"invalid {label} reference kind")
    return result


def _stamp(value, label):
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise EnvironmentError(f"{label} must be a canonical UTC timestamp")
    try:
        # Naive-parse only: the exact string is stored verbatim; this call
        # validates calendar reality, never produces a datetime value.
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")  # noqa: DTZ007
    except ValueError as exc:
        raise EnvironmentError(
            f"{label} must be a canonical UTC timestamp"
        ) from exc
    return value


@dataclass(frozen=True, slots=True, init=False)
class DesignApproval:
    """One human's authenticated approval of one exact design version."""

    design_ref: EntityRef
    candidate_id: str
    candidate_version: int
    approver_id: str
    approver_evidence: EntityRef
    approved_at: str
    model_bindings: EntityRef
    tool_permissions: EntityRef
    observation_contract: EntityRef
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "design-approval-v1",
            "design_ref": self.design_ref.as_dict(),
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "approver_id": self.approver_id,
            "approver_evidence_ref": self.approver_evidence.as_dict(),
            "approved_at": self.approved_at,
            "model_bindings_ref": self.model_bindings.as_dict(),
            "tool_permissions_ref": self.tool_permissions.as_dict(),
            "observation_contract_ref": self.observation_contract.as_dict(),
        }

    @property
    def approval_sha(self) -> str:
        return sha256(canonical_json(self.as_dict())).hexdigest()


def record_design_approval(value) -> DesignApproval:
    """Record one explicit approval; absence or silence records nothing."""

    if type(value) is not dict or set(value) != {
        "candidate", "verdict", "approver", "approved_at",
        "model_bindings", "tool_permissions", "observation_contract",
    }:
        raise EnvironmentError("expected the exact design approval object")
    candidate = value["candidate"]
    if not is_accepted_candidate(candidate):
        raise EnvironmentError("an accepted design candidate is required")
    verdict = value["verdict"]
    if type(verdict) is not CandidateVerdict:
        raise EnvironmentError("a criticism verdict is required")
    if (
        verdict.candidate_id != candidate.candidate_id
        or verdict.candidate_version != str(candidate.version)
    ):
        raise EnvironmentError(
            "the verdict does not bind this exact candidate"
        )
    if verdict.status != "passed":
        # A mandatory defect or missing evidence is never approvable; a
        # derived (select/edit/merge) design must complete its own
        # re-review into a passed candidate first.
        raise EnvironmentError("only a passed design version is approvable")
    approver = value["approver"]
    if type(approver) is not dict or set(approver) != {
        "actor_id", "authenticated", "evidence",
    }:
        raise EnvironmentError("expected the exact approver object")
    actor_id = approver["actor_id"]
    if type(actor_id) is not str or _UUID.fullmatch(actor_id) is None:
        raise EnvironmentError("approver id is not a canonical UUID")
    if approver["authenticated"] is not True:
        raise EnvironmentError("approval requires an authenticated approver")
    return _issue(
        DesignApproval,
        design_ref=candidate.graph_ref,
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.version,
        approver_id=actor_id,
        approver_evidence=_ref(
            approver["evidence"], "action_approval", "approver evidence",
        ),
        approved_at=_stamp(value["approved_at"], "approval time"),
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


def open_environment(environment_id) -> EnvironmentState:
    if type(environment_id) is not str or _UUID.fullmatch(environment_id) is None:
        raise EnvironmentError("environment id is not a canonical UUID")
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
        raise EnvironmentError("a framework-issued environment state is required")
    if (
        type(approval) is not DesignApproval
        or getattr(approval, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise EnvironmentError("a recorded design approval is required")
    if type(expected_head) is not int or expected_head != state.head:
        # The environment moved since the approval was formed: re-compare
        # and re-approve; the stale expectation prepares nothing.
        raise EnvironmentError("the environment head changed since approval")
    approval_sha = approval.approval_sha
    if approval_sha in state.consumed_approvals:
        raise EnvironmentError("this approval already prepared a version")
    if state.head >= 1_000_000:
        raise EnvironmentError("the environment version space is exhausted")
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
    "EnvironmentError",
    "EnvironmentState",
    "EnvironmentVersion",
    "open_environment",
    "prepare_environment_version",
    "record_design_approval",
]
