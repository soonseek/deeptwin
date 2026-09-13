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
from dataclasses import dataclass, field, replace

from ..domain.refs import DomainContractError, EntityRef
from ..services.diagnosis import Difference, HypothesisSet
from ..services.lenses import LensDecision, LensRegistry

INQUIRY_SCHEMA_VERSION = "inquiry-v1"
OUTCOMES = frozenset({"supported", "refuted", "unresolved", "declined"})
_SPLI_PATH = "post_alternative_spli"
_EVIDENCE_KINDS = frozenset({"artifact", "comparison_result", "handoff", "source"})
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)


class InquiryError(ValueError):
    """An inquiry opening, observation or conclusion is invalid."""


def _text(value, label, maximum):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise InquiryError(f"invalid {label}")
    return value


def _stamp(value, label):
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise InquiryError(f"invalid {label} stamp")
    return value


@dataclass(frozen=True, slots=True)
class OpposingPrediction:
    """One frozen contrasting prediction pair for one question."""

    question_index: int
    if_supported: str
    if_refuted: str


@dataclass(frozen=True, slots=True)
class Inquiry:
    """One frozen investigation; evolution only through the module functions."""

    difference_ref: EntityRef
    confirmed_h_exp: tuple[str, ...]
    lens_refs: tuple[str, ...]
    questions: tuple[str, ...]
    opposing_predictions: tuple[OpposingPrediction, ...]
    frozen_at: str
    excluded_refs: tuple[EntityRef, ...] = field(repr=False)
    new_evidence: tuple[tuple[str, EntityRef], ...] = ()
    outcome: str | None = None

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

    if type(difference) is not Difference:
        raise InquiryError("a recorded difference is required")
    if (
        type(hypothesis_set) is not HypothesisSet
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
    for decision in lens_decisions:
        if (
            type(decision) is not LensDecision
            or not registry.vouches_for(decision)
            or decision.path != _SPLI_PATH
            or decision.qualification_status != "qualified"
        ):
            raise InquiryError(
                "every lens decision must be a registry-vouched qualified SPLI use"
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
        predictions.append(OpposingPrediction(index, supported, refuted))
    return Inquiry(
        difference_ref=difference.difference_ref,
        confirmed_h_exp=confirmed,
        lens_refs=tuple(sorted(str(item.lens_ref) for item in lens_decisions)),
        questions=frozen_questions,
        opposing_predictions=tuple(predictions),
        frozen_at=_stamp(frozen_at, "freeze"),
        excluded_refs=(
            difference.original_artifact, difference.alternative_artifact,
        ),
    )


def observe_evidence(inquiry, evidence_refs, *, observed_at) -> Inquiry:
    """Append fresh evidence observed strictly after the freeze."""

    if type(inquiry) is not Inquiry:
        raise InquiryError("an opened inquiry is required")
    if inquiry.outcome is not None:
        raise InquiryError("a concluded inquiry is final")
    stamp = _stamp(observed_at, "observation")
    if stamp <= inquiry.frozen_at:
        raise InquiryError(
            "evidence must be observed strictly after the prediction freeze"
        )
    if type(evidence_refs) is not list or not 1 <= len(evidence_refs) <= 64:
        raise InquiryError("evidence references are out of bounds")
    observed = []
    for item in evidence_refs:
        try:
            ref = EntityRef.from_dict(item)
        except (DomainContractError, TypeError) as exc:
            raise InquiryError("invalid evidence reference") from exc
        if ref.kind not in _EVIDENCE_KINDS:
            raise InquiryError("evidence must be an observable record kind")
        if ref in inquiry.excluded_refs:
            raise InquiryError(
                "the existing alternative or original is not new evidence"
            )
        observed.append((stamp, ref))
    return replace(
        inquiry, new_evidence=inquiry.new_evidence + tuple(observed),
    )


def conclude_inquiry(inquiry, outcome) -> Inquiry:
    """Settle one outcome; supported/refuted require actual fresh evidence."""

    if type(inquiry) is not Inquiry:
        raise InquiryError("an opened inquiry is required")
    if inquiry.outcome is not None:
        raise InquiryError("a concluded inquiry is final")
    if outcome not in OUTCOMES:
        raise InquiryError("unknown inquiry outcome")
    if outcome in ("supported", "refuted") and not inquiry.new_evidence:
        raise InquiryError(
            "supported or refuted outcomes require fresh observed evidence"
        )
    return replace(inquiry, outcome=outcome)


__all__ = [
    "INQUIRY_SCHEMA_VERSION",
    "OUTCOMES",
    "Inquiry",
    "InquiryError",
    "OpposingPrediction",
    "conclude_inquiry",
    "observe_evidence",
    "open_inquiry",
]
