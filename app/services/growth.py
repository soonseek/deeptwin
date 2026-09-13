"""Growth-loop state and exact plateau arithmetic (US6, T062/T063, FR-024).

Early stopping here is a PRODUCT policy over the product's own tuning loop —
it never describes or stops development work. The loop separates
``best_observed`` (the genuinely best eligible candidate, preserved even for
small gains) from ``progress_reference`` (the last *meaningful* improvement):
the first valid candidate at the quality floor sets the reference without
counting as a non-improvement; afterwards a candidate improves meaningfully
only when ``current - reference >= min_delta`` in exact ``Decimal`` arithmetic.
Invalid, unresolved or interrupted rounds never touch the counters while their
consumed budget still accrues; a confirmed-defect round counts as a valid
non-improvement but can never replace the best. Three consecutive valid
non-improving rounds after the floor end the loop as ``plateau_reached`` — a
stop of exploration, never a claim of operational fitness. A loop that never
reached the floor can only end ``below_floor_exhausted``. Application of one
round is a single, non-replayable transition within one state value; because
states are immutable values, replaying an old state object or re-opening a
lineage with :func:`start_growth_loop` is not preventable here — the storage
layer must CAS on ``revision`` per §7 and refuse a second loop for a live
lineage. Counters and budget are never resettable through this module's own
transitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

STOP_REASONS = frozenset({
    "plateau_reached", "budget_exhausted", "below_floor_exhausted",
    "evidence_blocked", "safety_stop", "human_stop", "lineage_changed",
})
_EXTERNAL_STOPS = STOP_REASONS - {"plateau_reached"}
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_DECIMAL = re.compile(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?\Z")
_ISSUE_TOKEN = object()


class GrowthLoopError(ValueError):
    """A profile, loop state or round application is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _exact_decimal(value, label):
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise GrowthLoopError(f"{label} must be an exact decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex guards first
        raise GrowthLoopError(f"{label} must be an exact decimal string") from exc


@dataclass(frozen=True, slots=True, init=False)
class QualityProfile:
    """The frozen quality contract of one lineage; patience never changes."""

    profile_id: str
    version: int
    quality_floor: Decimal
    min_delta: Decimal
    patience: int
    _issuer_token: object = field(repr=False, compare=False)


def freeze_quality_profile(value) -> QualityProfile:
    if type(value) is not dict or set(value) != {
        "profile_id", "version", "quality_floor", "min_delta", "patience",
    }:
        raise GrowthLoopError("expected the exact quality profile object")
    profile_id = value["profile_id"]
    if (
        type(profile_id) is not str
        or not 1 <= len(profile_id.encode("utf-8")) <= 128
    ):
        raise GrowthLoopError("profile id is out of bounds")
    version = value["version"]
    if type(version) is not int or not 1 <= version <= 1_000_000:
        raise GrowthLoopError("profile version is out of bounds")
    patience = value["patience"]
    if type(patience) is not int or not 1 <= patience <= 100:
        raise GrowthLoopError("patience is out of bounds")
    quality_floor = _exact_decimal(value["quality_floor"], "quality floor")
    if quality_floor < 0:
        raise GrowthLoopError("the quality floor must be non-negative")
    min_delta = _exact_decimal(value["min_delta"], "min delta")
    if min_delta <= 0:
        # A zero or negative delta destroys plateau semantics: every tie or
        # worsening round would count as a meaningful improvement.
        raise GrowthLoopError("min delta must be strictly positive")
    return _issue(
        QualityProfile,
        profile_id=profile_id,
        version=version,
        quality_floor=quality_floor,
        min_delta=min_delta,
        patience=patience,
        _issuer_token=_ISSUE_TOKEN,
    )


@dataclass(frozen=True, slots=True, init=False)
class GrowthLoop:
    """One lineage's loop state; evolution only through the module functions."""

    lineage_id: str
    profile: QualityProfile
    revision: int
    status: str
    floor_reached: bool
    best_observed: tuple[str, Decimal] | None
    progress_reference: tuple[str, Decimal] | None
    non_improving_valid_count: int
    completed_round_ids: tuple[str, ...]
    consumed_budget: tuple[tuple[str, int], ...]
    stop_reason: str | None
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "growth-loop-v1",
            "lineage_id": self.lineage_id,
            "profile_id": self.profile.profile_id,
            "profile_version": self.profile.version,
            "revision": self.revision,
            "status": self.status,
            "floor_reached": self.floor_reached,
            "best_observed": (
                None if self.best_observed is None
                else {
                    "round_id": self.best_observed[0],
                    "utility": str(self.best_observed[1]),
                }
            ),
            "progress_reference": (
                None if self.progress_reference is None
                else {
                    "round_id": self.progress_reference[0],
                    "utility": str(self.progress_reference[1]),
                }
            ),
            "non_improving_valid_count": self.non_improving_valid_count,
            "completed_round_ids": list(self.completed_round_ids),
            "consumed_budget": dict(self.consumed_budget),
            "stop_reason": self.stop_reason,
        }


def _require_loop(state) -> None:
    if (
        type(state) is not GrowthLoop
        or getattr(state, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise GrowthLoopError("a framework-issued growth loop state is required")


def start_growth_loop(lineage_id, profile) -> GrowthLoop:
    """Open one lineage's loop; counters and budget start empty exactly once."""

    if type(lineage_id) is not str or _UUID.fullmatch(lineage_id) is None:
        raise GrowthLoopError("lineage id is not a canonical UUID")
    if (
        type(profile) is not QualityProfile
        or getattr(profile, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise GrowthLoopError("a frozen quality profile is required")
    return _issue(
        GrowthLoop,
        lineage_id=lineage_id,
        profile=profile,
        revision=1,
        status="running",
        floor_reached=False,
        best_observed=None,
        progress_reference=None,
        non_improving_valid_count=0,
        completed_round_ids=(),
        consumed_budget=(),
        stop_reason=None,
        _issuer_token=_ISSUE_TOKEN,
    )


def _reissue(state: GrowthLoop, **changes) -> GrowthLoop:
    fields = {
        "lineage_id": state.lineage_id,
        "profile": state.profile,
        "revision": state.revision + 1,
        "status": state.status,
        "floor_reached": state.floor_reached,
        "best_observed": state.best_observed,
        "progress_reference": state.progress_reference,
        "non_improving_valid_count": state.non_improving_valid_count,
        "completed_round_ids": state.completed_round_ids,
        "consumed_budget": state.consumed_budget,
        "stop_reason": state.stop_reason,
        "_issuer_token": _ISSUE_TOKEN,
    }
    fields.update(changes)
    return _issue(GrowthLoop, **fields)


def _accrue(budget, consumed) -> tuple[tuple[str, int], ...]:
    if type(consumed) is not dict or len(consumed) > 16:
        raise GrowthLoopError("consumed budget is out of bounds")
    totals = dict(budget)
    for name, amount in consumed.items():
        if (
            type(name) is not str or not 1 <= len(name) <= 64
            or type(amount) is not int or not 0 <= amount <= 1_000_000_000
        ):
            raise GrowthLoopError("consumed budget is out of bounds")
        totals[name] = totals.get(name, 0) + amount
    return tuple(sorted(totals.items()))


def apply_round(state, value) -> GrowthLoop:
    """Apply exactly one round outcome; a round id can never apply twice."""

    _require_loop(state)
    if state.status != "running":
        raise GrowthLoopError("a terminal loop accepts no further rounds")
    required = {
        "round_id", "validity", "utility", "mandatory_passed",
        "regression_ok", "consumed",
    }
    if (
        type(value) is not dict
        or not required <= set(value)
        or set(value) - required - {"invalid_reason"}
    ):
        raise GrowthLoopError("expected the exact round outcome object")
    if value["validity"] not in {"valid", "invalid", "pending"}:
        raise GrowthLoopError("round validity must be valid, invalid or pending")
    round_id = value["round_id"]
    if (
        type(round_id) is not str
        or not 1 <= len(round_id.encode("utf-8")) <= 128
    ):
        raise GrowthLoopError("round id is out of bounds")
    if round_id in state.completed_round_ids:
        raise GrowthLoopError("a round result can never apply twice")
    budget = _accrue(state.consumed_budget, value["consumed"])
    completed = state.completed_round_ids + (round_id,)

    if value["validity"] != "valid":
        # Missing material, tool/evaluator failure, unresolved judgment or an
        # interrupted run is not a completed valid comparison: score stays
        # null and counters stay untouched, while real consumption accrues.
        if value["utility"] is not None:
            # A missing or failed measurement never smuggles in a score.
            raise GrowthLoopError(
                "only a valid round may carry a utility"
            )
        return _reissue(
            state, completed_round_ids=completed, consumed_budget=budget,
        )
    if value["utility"] is None:
        # A valid round without a completed evaluation score: the evaluator
        # never finished, so counters stay untouched (§6.2 — a fully observed
        # capability failure is expressed as a valid round WITH the
        # evaluator's score, never as an absent one).
        return _reissue(
            state, completed_round_ids=completed, consumed_budget=budget,
        )

    utility = _exact_decimal(value["utility"], "round utility")
    mandatory = value["mandatory_passed"]
    regression = value["regression_ok"]
    if type(mandatory) is not bool or type(regression) is not bool:
        raise GrowthLoopError("mandatory and regression outcomes must be explicit")
    eligible = mandatory and regression
    profile = state.profile

    floor_reached = state.floor_reached
    best = state.best_observed
    reference = state.progress_reference
    counter = state.non_improving_valid_count
    status = state.status
    stop_reason = state.stop_reason

    if eligible and (best is None or utility > best[1]):
        # Ties keep the earlier candidate; a confirmed defect never replaces
        # the best even with a higher raw number.
        best = (round_id, utility)

    if not floor_reached:
        if eligible and utility >= profile.quality_floor:
            # The first floor round sets the reference and never counts as a
            # non-improvement.
            floor_reached = True
            reference = (round_id, utility)
            counter = 0
    else:
        improved = (
            eligible and utility - reference[1] >= profile.min_delta
        )
        if improved:
            reference = (round_id, utility)
            counter = 0
        else:
            counter += 1
            if counter >= profile.patience:
                status = "plateau_reached"
                stop_reason = "plateau_reached"

    return _reissue(
        state,
        floor_reached=floor_reached,
        best_observed=best,
        progress_reference=reference,
        non_improving_valid_count=counter,
        completed_round_ids=completed,
        consumed_budget=budget,
        status=status,
        stop_reason=stop_reason,
    )


def stop_growth_loop(state, reason) -> GrowthLoop:
    """End one loop for an external reason; plateau is never claimable by fiat."""

    _require_loop(state)
    if state.status != "running":
        raise GrowthLoopError("a terminal loop cannot stop again")
    if reason not in _EXTERNAL_STOPS:
        raise GrowthLoopError("unknown or non-declarable stop reason")
    if reason == "budget_exhausted" and not state.floor_reached:
        raise GrowthLoopError(
            "budget exhaustion below the floor is below_floor_exhausted"
        )
    if reason == "below_floor_exhausted" and state.floor_reached:
        raise GrowthLoopError(
            "a loop that reached the floor cannot claim below-floor exhaustion"
        )
    return _reissue(state, status=reason, stop_reason=reason)


__all__ = [
    "STOP_REASONS",
    "GrowthLoop",
    "GrowthLoopError",
    "QualityProfile",
    "apply_round",
    "freeze_quality_profile",
    "start_growth_loop",
    "stop_growth_loop",
]
