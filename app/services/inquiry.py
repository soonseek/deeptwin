"""Inquiry contracts for the growth journey (US5, T056, FR-019, G-03/04).

An inquiry investigates a confirmed expert-judgment hypothesis over a recorded
difference through registry-vouched SPLI lens decisions. Its questions and
opposing predictions freeze before any new evidence is observed: evidence
stamped at or before the freeze is rejected, the existing alternative can never
be renamed into new evidence, supported/refuted outcomes require actual fresh
evidence, and declining is a legitimate outcome without any. A concluded
inquiry is final.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef
from ..services.diagnosis import (
    is_issued_hypothesis_set,
    is_recorded_difference,
)
from ..services.lenses import LensDecision, LensRegistry

INQUIRY_SCHEMA_VERSION = "inquiry-v1"
OUTCOMES = frozenset({"supported", "refuted", "unresolved", "declined"})
_SPLI_PATH = "post_alternative_spli"
_EVIDENCE_KINDS = frozenset({"artifact", "comparison_result", "handoff", "source"})
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_ISSUE_TOKEN = object()


def _issue(kind, **fields):
    value = object.__new__(kind)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


class InquiryError(ValueError):
    """An inquiry opening, observation or conclusion is invalid."""


def _text(value, label, maximum):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise InquiryError(f"invalid {label}")
    return value


def _stamp(value, label):
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise InquiryError(f"invalid {label} stamp")
    from datetime import datetime

    try:
        # Naive-parse only: the exact string is stored verbatim; this call
        # validates calendar reality, never produces a datetime value.
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")  # noqa: DTZ007
    except ValueError as exc:
        raise InquiryError(f"{label} stamp is not a real datetime") from exc
    return value


@dataclass(frozen=True, slots=True, init=False)
class OpposingPrediction:
    """One frozen contrasting prediction pair for one question."""

    question_index: int
    if_supported: str
    if_refuted: str
    _issuer_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, init=False)
class Inquiry:
    """One frozen investigation; evolution only through the module functions."""

    difference_ref: EntityRef
    confirmed_h_exp: tuple[str, ...]
    lens_refs: tuple[str, ...]
    questions: tuple[str, ...]
    opposing_predictions: tuple[OpposingPrediction, ...]
    frozen_at: str
    excluded_refs: tuple[EntityRef, ...] = field(repr=False)
    new_evidence: tuple[tuple[str, EntityRef], ...]
    outcome: str | None
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": INQUIRY_SCHEMA_VERSION,
            "difference_ref": self.difference_ref.as_dict(),
            "confirmed_h_exp": list(self.confirmed_h_exp),
            "lens_refs": list(self.lens_refs),
            "questions": list(self.questions),
            "opposing_predictions": [
                {
                    "question_index": item.question_index,
                    "if_supported": item.if_supported,
                    "if_refuted": item.if_refuted,
                }
                for item in self.opposing_predictions
            ],
            "frozen_at": self.frozen_at,
            "new_evidence": [
                {"observed_at": observed_at, "ref": ref.as_dict()}
                for observed_at, ref in self.new_evidence
            ],
            "outcome": self.outcome,
        }


def open_inquiry(
    difference,
    hypothesis_set,
    *,
    registry,
    lens_decisions,
    questions,
    opposing_predictions,
    frozen_at,
) -> Inquiry:
    """Freeze one investigation over a difference's confirmed expert judgment."""

    if not is_recorded_difference(difference):
        raise InquiryError("a recorded difference is required")
    if (
        not is_issued_hypothesis_set(hypothesis_set)
        or hypothesis_set.difference_ref != difference.difference_ref
    ):
        raise InquiryError("the hypothesis set must belong to this difference")
    confirmed = tuple(
        item.hypothesis_id
        for item in hypothesis_set.hypotheses
        if item.family == "expert_judgment" and item.status == "confirmed"
    )
    if not confirmed:
        raise InquiryError(
            "an inquiry requires at least one confirmed expert judgment"
        )
    if type(registry) is not LensRegistry:
        raise InquiryError("the qualified lens registry is required")
    if type(lens_decisions) is not list or not 1 <= len(lens_decisions) <= 16:
        raise InquiryError("lens decisions are out of bounds")
    expected_scope = "partial" if difference.alignment else "whole"
    bound_hashes = {
        difference.original_artifact.sha256,
        difference.alternative_artifact.sha256,
        difference.difference_ref.sha256,
    }
    for decision in lens_decisions:
        if (
            type(decision) is not LensDecision
            or not registry.vouches_for(decision)
            or decision.path != _SPLI_PATH
            or decision.qualification_status != "qualified"
            or decision.state != "proposed"
        ):
            raise InquiryError(
                "every lens decision must be a registry-vouched qualified SPLI use"
            )
        if (
            decision.alternative_scope != expected_scope
            or not bound_hashes <= set(decision.evidence_hashes)
        ):
            # The decision's route evidence must cite this exact original,
            # alternative and observed difference, not unrelated records.
            raise InquiryError(
                "the lens route evidence does not bind this exact difference"
            )
    if type(questions) is not list or not 1 <= len(questions) <= 16:
        raise InquiryError("questions are out of bounds")
    frozen_questions = tuple(
        _text(item, "inquiry question", 2_048) for item in questions
    )
    if (
        type(opposing_predictions) is not list
        or not 1 <= len(opposing_predictions) <= 32
    ):
        raise InquiryError("opposing predictions are out of bounds")
    predictions = []
    for item in opposing_predictions:
        if type(item) is not dict or set(item) != {
            "question_index", "if_supported", "if_refuted",
        }:
            raise InquiryError("expected the exact opposing prediction object")
        index = item["question_index"]
        if type(index) is not int or not 0 <= index < len(frozen_questions):
            raise InquiryError("prediction question index is out of range")
        supported = _text(item["if_supported"], "supported prediction", 2_048)
        refuted = _text(item["if_refuted"], "refuted prediction", 2_048)
        if supported == refuted:
            raise InquiryError("predictions must actually oppose each other")
        predictions.append(_issue(
            OpposingPrediction,
            question_index=index,
            if_supported=supported,
            if_refuted=refuted,
            _issuer_token=_ISSUE_TOKEN,
        ))
    pre_freeze = list(difference.excluded_evidence)
    for item in hypothesis_set.hypotheses:
        pre_freeze.extend(item.support)
        pre_freeze.extend(item.counterevidence)
        pre_freeze.extend(item.confirmation_basis)
    return _issue(
        Inquiry,
        difference_ref=difference.difference_ref,
        confirmed_h_exp=confirmed,
        lens_refs=tuple(sorted(str(item.lens_ref) for item in lens_decisions)),
        questions=frozen_questions,
        opposing_predictions=tuple(predictions),
        frozen_at=_stamp(frozen_at, "freeze"),
        excluded_refs=tuple(pre_freeze),
        new_evidence=(),
        outcome=None,
        _issuer_token=_ISSUE_TOKEN,
    )


def _require_issued(inquiry) -> None:
    if not is_issued_inquiry(inquiry):
        raise InquiryError("an opened inquiry is required")


def is_issued_inquiry(value: object) -> bool:
    """True only for an inquiry issued through this module's functions."""

    return (
        type(value) is Inquiry
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def _reissue(inquiry: Inquiry, **changes) -> Inquiry:
    fields = {
        "difference_ref": inquiry.difference_ref,
        "confirmed_h_exp": inquiry.confirmed_h_exp,
        "lens_refs": inquiry.lens_refs,
        "questions": inquiry.questions,
        "opposing_predictions": inquiry.opposing_predictions,
        "frozen_at": inquiry.frozen_at,
        "excluded_refs": inquiry.excluded_refs,
        "new_evidence": inquiry.new_evidence,
        "outcome": inquiry.outcome,
        "_issuer_token": _ISSUE_TOKEN,
    }
    fields.update(changes)
    return _issue(Inquiry, **fields)


def observe_evidence(inquiry, evidence_refs, *, observed_at) -> Inquiry:
    """Append fresh evidence observed strictly after the freeze."""

    _require_issued(inquiry)
    if inquiry.outcome is not None:
        raise InquiryError("a concluded inquiry is final")
    stamp = _stamp(observed_at, "observation")
    if stamp <= inquiry.frozen_at:
        raise InquiryError(
            "evidence must be observed strictly after the prediction freeze"
        )
    if type(evidence_refs) is not list or not 1 <= len(evidence_refs) <= 64:
        raise InquiryError("evidence references are out of bounds")
    excluded_hashes = {item.sha256 for item in inquiry.excluded_refs}
    excluded_ids = {(item.kind, item.id) for item in inquiry.excluded_refs}
    observed = []
    for item in evidence_refs:
        try:
            ref = EntityRef.from_dict(item)
        except (DomainContractError, TypeError) as exc:
            raise InquiryError("invalid evidence reference") from exc
        if ref.kind not in _EVIDENCE_KINDS:
            raise InquiryError("evidence must be an observable record kind")
        if ref.sha256 in excluded_hashes or (ref.kind, ref.id) in excluded_ids:
            # Neither the compared material nor any pre-freeze record — nor a
            # version-bumped rename of the same content — is fresh evidence.
            raise InquiryError(
                "pre-freeze material cannot be renamed into new evidence"
            )
        observed.append((stamp, ref))
    return _reissue(inquiry, new_evidence=inquiry.new_evidence + tuple(observed))


def conclude_inquiry(inquiry, outcome) -> Inquiry:
    """Settle one outcome; supported/refuted require actual fresh evidence."""

    _require_issued(inquiry)
    if inquiry.outcome is not None:
        raise InquiryError("a concluded inquiry is final")
    if outcome not in OUTCOMES:
        raise InquiryError("unknown inquiry outcome")
    if outcome in ("supported", "refuted") and not inquiry.new_evidence:
        raise InquiryError(
            "supported or refuted outcomes require fresh observed evidence"
        )
    return _reissue(inquiry, outcome=outcome)


def spli_questions(registry, lens_decisions) -> tuple[list[str], list[dict]]:
    """The questions and opposing predictions the qualified lens cards state.

    SPLI routing reads each registry-vouched, qualified `post_alternative_spli`
    decision's own card: its distinguishing question is the frozen question,
    its expected contrast what the question predicts if the expert judgment
    holds, and its disconfirmation cue what it predicts if it does not. Nothing
    is paraphrased or generated, so no question outruns the qualified lens that
    grounds it; a decision the registry does not vouch for, or one for another
    path, stops the routing rather than being skipped silently.
    """

    if type(registry) is not LensRegistry:
        raise InquiryError("the qualified lens registry is required")
    if type(lens_decisions) is not list or not 1 <= len(lens_decisions) <= 16:
        raise InquiryError("lens decisions are out of bounds")
    questions: list[str] = []
    predictions: list[dict] = []
    for decision in lens_decisions:
        if (
            type(decision) is not LensDecision
            or not registry.vouches_for(decision)
            or decision.path != _SPLI_PATH
            or decision.qualification_status != "qualified"
            or decision.state != "proposed"
        ):
            raise InquiryError(
                "every lens decision must be a registry-vouched qualified SPLI use"
            )
        definition = registry.get(decision.lens_ref.lens_id)
        if definition.ref != decision.lens_ref:
            raise InquiryError("the decision's lens card is not the registry's current card")
        question = definition.distinguishing_question
        if question in questions:
            continue  # two decisions over one card ask one question
        questions.append(question)
        predictions.append({
            "question_index": len(questions) - 1,
            "if_supported": definition.expected_contrast,
            "if_refuted": definition.disconfirmation,
        })
    return questions, predictions


def open_routed_inquiry(difference, hypothesis_set, *, registry, lens_decisions, frozen_at) -> Inquiry:
    """Open an inquiry whose questions come only from the qualified lens cards."""

    questions, predictions = spli_questions(registry, lens_decisions)
    return open_inquiry(
        difference, hypothesis_set, registry=registry, lens_decisions=lens_decisions,
        questions=questions, opposing_predictions=predictions, frozen_at=frozen_at,
    )


H_EXP_OUTCOMES = {
    "supported": "supported_by_fresh_evidence",
    "refuted": "refuted_by_fresh_evidence",
    "unresolved": "unchanged",
    "declined": "unchanged",
}


@dataclass(frozen=True, slots=True, init=False)
class ExpertJudgmentRevision:
    """What a concluded inquiry did to the confirmed expert judgment (H_exp).

    The hypothesis set stays as it was confirmed; this is the next, separate
    fact: fresh evidence observed after the freeze supported or refuted the
    judgment, or the inquiry abstained and the judgment is unchanged. Only a
    `supported_by_fresh_evidence` revision can ground learn/protect changes
    (the compiler already requires a supported inquiry); a refuted judgment is
    withdrawn from change grounds, never quietly kept.
    """

    difference_ref: EntityRef
    h_exp_ids: tuple[str, ...]
    status: str
    evidence: tuple[tuple[str, EntityRef], ...]
    lens_refs: tuple[str, ...]
    frozen_at: str
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "h-exp-revision-v1",
            "difference_ref": self.difference_ref.as_dict(),
            "h_exp_ids": list(self.h_exp_ids),
            "status": self.status,
            "evidence": [{"observed_at": at, "ref": ref.as_dict()} for at, ref in self.evidence],
            "lens_refs": list(self.lens_refs),
            "frozen_at": self.frozen_at,
        }


def revise_expert_judgment(hypothesis_set, inquiry) -> ExpertJudgmentRevision:
    """The H_exp update a concluded inquiry grounds, bound to its evidence."""

    _require_issued(inquiry)
    if inquiry.outcome is None:
        raise InquiryError("only a concluded inquiry revises the expert judgment")
    if (
        not is_issued_hypothesis_set(hypothesis_set)
        or hypothesis_set.difference_ref != inquiry.difference_ref
    ):
        raise InquiryError("the hypothesis set must belong to the inquiry's difference")
    confirmed = {
        item.hypothesis_id for item in hypothesis_set.hypotheses
        if item.family == "expert_judgment" and item.status == "confirmed"
    }
    if not set(inquiry.confirmed_h_exp) <= confirmed:
        raise InquiryError("the inquiry's expert judgment is not confirmed in this set")
    status = H_EXP_OUTCOMES[inquiry.outcome]
    return _issue(
        ExpertJudgmentRevision,
        difference_ref=inquiry.difference_ref,
        h_exp_ids=inquiry.confirmed_h_exp,
        status=status,
        # abstaining keeps no evidence as if it had decided anything
        evidence=inquiry.new_evidence if status != "unchanged" else (),
        lens_refs=inquiry.lens_refs,
        frozen_at=inquiry.frozen_at,
        _issuer_token=_ISSUE_TOKEN,
    )


def is_issued_revision(value: object) -> bool:
    return (type(value) is ExpertJudgmentRevision
            and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN)


__all__ = [
    "H_EXP_OUTCOMES",
    "INQUIRY_SCHEMA_VERSION",
    "OUTCOMES",
    "ExpertJudgmentRevision",
    "Inquiry",
    "InquiryError",
    "OpposingPrediction",
    "conclude_inquiry",
    "is_issued_inquiry",
    "is_issued_revision",
    "observe_evidence",
    "open_inquiry",
    "open_routed_inquiry",
    "revise_expert_judgment",
    "spli_questions",
]
