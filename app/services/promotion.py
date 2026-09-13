"""Human promotion of validated candidates (US6, T065, FR-026).

A :class:`PromotionDecision` records a human's authenticated explicit act —
approve, reject or defer. Silence, a UI refresh or a developer default never
create an approve, and an approve requires a passed sealed-offline validation
report bound to the exact candidate bundle (observation-only or limited
reports back nothing, G-11). Activation is compare-and-swap on the current
operating environment: the approved bundle hash must equal the applied
bundle hash and the expected current environment must still be current — a
tampered bundle or a moved environment fails the conditional apply and
demands re-approval (G-13). The three FR-026 axes stay separate: validation
lives in the report, deployment in the current environment pointer, and
lifecycle in the version history — rollback restores the previous compatible
bundle while every version stays in history, and it never claims external
real-world effects were undone. Values are issued, never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef, canonical_json
from .validation import FrozenCandidate, is_frozen_candidate, is_validation_report

PROMOTION_DECISION_SCHEMA_VERSION = "promotion-decision-v1"
DECISIONS = frozenset({"approve", "reject", "defer"})
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_ISSUE_TOKEN = object()


class PromotionError(ValueError):
    """A promotion decision, activation or rollback is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise PromotionError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise PromotionError(f"invalid {label} reference kind")
    return result


def _stamp(value, label):
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise PromotionError(f"{label} must be a canonical UTC timestamp")
    try:
        # Naive-parse only: the exact string is stored verbatim; this call
        # validates calendar reality, never produces a datetime value.
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")  # noqa: DTZ007
    except ValueError as exc:
        raise PromotionError(f"{label} must be a canonical UTC timestamp") from exc
    return value


@dataclass(frozen=True, slots=True, init=False)
class PromotionDecision:
    """One human's authenticated explicit decision on one exact bundle."""

    candidate_environment: EntityRef
    validation_report: EntityRef
    scope: EntityRef
    approver_id: str
    approver_evidence: EntityRef
    decision: str
    decision_at: str
    expected_current_environment: EntityRef
    rollback_bundle: EntityRef
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": PROMOTION_DECISION_SCHEMA_VERSION,
            "candidate_environment_ref": self.candidate_environment.as_dict(),
            "validation_report_ref": self.validation_report.as_dict(),
            "scope_ref": self.scope.as_dict(),
            "approver_id": self.approver_id,
            "approver_evidence_ref": self.approver_evidence.as_dict(),
            "decision": self.decision,
            "decision_at": self.decision_at,
            "expected_current_environment_ref": (
                self.expected_current_environment.as_dict()
            ),
            "rollback_bundle_ref": self.rollback_bundle.as_dict(),
        }


def record_promotion_decision(value) -> PromotionDecision:
    """Record one explicit human decision; silence never becomes an approve."""

    if type(value) is not dict or set(value) != {
        "candidate", "validation_report", "scope", "approver", "decision",
        "decision_at", "expected_current_environment", "rollback_bundle",
    }:
        raise PromotionError("expected the exact promotion decision object")
    candidate = value["candidate"]
    if not is_frozen_candidate(candidate):
        raise PromotionError("a frozen candidate bundle is required")
    report = value["validation_report"]
    if not is_validation_report(report):
        raise PromotionError("a framework-issued validation report is required")
    bundle_ref = candidate.bundle_ref
    if report.candidate_bundle != bundle_ref:
        raise PromotionError(
            "the validation report is not bound to this exact bundle"
        )
    decision = value["decision"]
    if decision not in DECISIONS:
        raise PromotionError(
            "a decision must be an explicit approve, reject or defer"
        )
    if decision == "approve" and (
        report.mode != "sealed_offline" or report.status != "passed"
    ):
        # Observation-only, limited, failed or invalid evidence never backs
        # an operational promotion (G-11); rejecting or deferring a failed
        # candidate is a first-class recorded human outcome (§7).
        raise PromotionError(
            "an approve requires a passed sealed-offline validation report"
        )
    approver = value["approver"]
    if type(approver) is not dict or set(approver) != {
        "actor_id", "authenticated", "evidence",
    }:
        raise PromotionError("expected the exact approver object")
    actor_id = approver["actor_id"]
    if type(actor_id) is not str or _UUID.fullmatch(actor_id) is None:
        raise PromotionError("approver id is not a canonical UUID")
    if approver["authenticated"] is not True:
        raise PromotionError("promotion requires an authenticated approver")
    report_sha = sha256(canonical_json(report.as_dict())).hexdigest()
    return _issue(
        PromotionDecision,
        candidate_environment=bundle_ref,
        # A content-derived id: two different reports can never share
        # (kind, id, version).
        validation_report=EntityRef(
            "validation_report",
            str(uuid5(NAMESPACE_URL, f"deeptwin:validation-report:{report_sha}")),
            1,
            report_sha,
        ),
        scope=_ref(value["scope"], "decision_record", "scope"),
        approver_id=actor_id,
        approver_evidence=_ref(
            approver["evidence"], "action_approval", "approver evidence",
        ),
        decision=decision,
        decision_at=_stamp(value["decision_at"], "decision time"),
        expected_current_environment=_ref(
            value["expected_current_environment"], "environment",
            "expected current environment",
        ),
        rollback_bundle=_ref(
            value["rollback_bundle"], "backup_manifest", "rollback bundle",
        ),
        _issuer_token=_ISSUE_TOKEN,
    )


@dataclass(frozen=True, slots=True, init=False)
class PromotionState:
    """The current operating environment and its full version history."""

    current_environment: EntityRef
    # history entries: (environment_ref, lifecycle) — versions are never erased
    history: tuple[tuple[EntityRef, str], ...]
    # content hashes of every decision this state lineage has applied; a
    # consumed approval is never valid again, rollback included (G-13).
    consumed_decisions: tuple[str, ...]
    external_effects_reverted: bool
    _issuer_token: object = field(repr=False, compare=False)


def _require_state(value) -> None:
    if (
        type(value) is not PromotionState
        or getattr(value, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise PromotionError("a framework-issued promotion state is required")


def open_promotion_state(current_environment) -> PromotionState:
    return _issue(
        PromotionState,
        current_environment=_ref(
            current_environment, "environment", "current environment",
        ),
        history=(),
        consumed_decisions=(),
        external_effects_reverted=False,
        _issuer_token=_ISSUE_TOKEN,
    )


def activate_candidate(state, decision, candidate) -> PromotionState:
    """Conditionally apply the exact approved bundle, or fail honestly."""

    _require_state(state)
    if (
        type(decision) is not PromotionDecision
        or getattr(decision, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise PromotionError("a recorded promotion decision is required")
    if not is_frozen_candidate(candidate):
        raise PromotionError("a frozen candidate bundle is required")
    if decision.decision != "approve":
        raise PromotionError("only an explicit approve can activate")
    if candidate.bundle_ref != decision.candidate_environment:
        # The approved hash and the applied hash must be identical; a bundle
        # changed after approval is a different version (G-13).
        raise PromotionError(
            "the applied bundle is not the approved bundle"
        )
    if state.current_environment != decision.expected_current_environment:
        # The current environment moved since approval: compare again and
        # re-approve; the stale approval is never reused.
        raise PromotionError(
            "the current environment changed since approval"
        )
    decision_sha = sha256(canonical_json(decision.as_dict())).hexdigest()
    if decision_sha in state.consumed_decisions:
        # A rollback restores the environment the approval expected, but the
        # human rolled back for a reason: re-promotion needs a fresh decision.
        raise PromotionError("this approval was already applied once")
    if len(state.history) >= 10_000:
        raise PromotionError("promotion history is full")
    return _issue(
        PromotionState,
        current_environment=candidate.bundle_ref,
        history=(*state.history, (state.current_environment, "retired")),
        consumed_decisions=(*state.consumed_decisions, decision_sha),
        external_effects_reverted=False,
        _issuer_token=_ISSUE_TOKEN,
    )


def rollback_environment(state, reason) -> PromotionState:
    """Restore the previous compatible bundle; nothing external is undone."""

    _require_state(state)
    if type(reason) is not str or not 1 <= len(reason.encode("utf-8")) <= 1_024:
        raise PromotionError("a rollback must state its reason")
    # Only a previously retired (once-active) version is restorable; a
    # rolled-back bundle can never come back without a fresh human approval.
    restorable = None
    for index in range(len(state.history) - 1, -1, -1):
        if state.history[index][1] == "retired":
            restorable = index
            break
    if restorable is None:
        raise PromotionError("there is no previous version to restore")
    previous = state.history[restorable][0]
    remaining = (
        *state.history[:restorable], *state.history[restorable + 1:],
    )
    return _issue(
        PromotionState,
        current_environment=previous,
        history=(*remaining, (state.current_environment, "rolled_back")),
        consumed_decisions=state.consumed_decisions,
        # Real-world sends and publications already happened; a rollback
        # restores the bundle, never the world.
        external_effects_reverted=False,
        _issuer_token=_ISSUE_TOKEN,
    )


__all__ = [
    "DECISIONS",
    "PROMOTION_DECISION_SCHEMA_VERSION",
    "FrozenCandidate",
    "PromotionDecision",
    "PromotionError",
    "PromotionState",
    "activate_candidate",
    "open_promotion_state",
    "record_promotion_decision",
    "rollback_environment",
]
