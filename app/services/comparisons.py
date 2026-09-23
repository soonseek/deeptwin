"""Comparison contracts for the growth loop (US6, T061, FR-022/023/025).

A :class:`ComparisonPlan` freezes every condition — baseline environment, prior
queue, quality profile, evaluator bundle, reset manifest, allowed changes, tool
effect policy and budget — before any observation; changing a condition is a new
lineage, never a mutation. A :class:`ComparisonResult` binds the exact frozen
plan, pairs baseline and candidate runs, and keeps validity, work failure and
semantic irresolution distinct: an invalid round states its reasons, a missing
measurement is never converted into a zero or a no-improvement score, and
utility is an exact decimal that may exist only on a valid round. Values are
issued (init-disabled, tokened), never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef, canonical_json

COMPARISON_PLAN_SCHEMA_VERSION = "comparison-plan-v1"
COMPARISON_RESULT_SCHEMA_VERSION = "comparison-result-v1"
PLAN_MODES = frozenset({"automatic", "human_assisted"})
VALIDITIES = frozenset({"valid", "invalid", "pending"})
_PLAN_BINDINGS = (
    ("baseline_environment", "environment"),
    ("queue", "run_manifest"),
    ("quality_profile", "evaluation_profile"),
    ("evaluator_bundle", "rubric"),
    ("reset_manifest", "run_manifest"),
    ("allowed_changes", "decision_record"),
    ("tool_effect_policy", "observation_contract"),
    ("budget", "budget_policy"),
)
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_DECIMAL = re.compile(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?\Z")
_ISSUE_TOKEN = object()


class ComparisonError(ValueError):
    """A comparison plan or round is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise ComparisonError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise ComparisonError(f"invalid {label} reference kind")
    return result


def _run_refs(value, label):
    if type(value) is not list or not 1 <= len(value) <= 64:
        raise ComparisonError(f"expected a bounded {label} list")
    refs = [_ref(item, "run_manifest", label) for item in value]
    if len({(item.id, item.version, item.sha256) for item in refs}) != len(refs):
        raise ComparisonError(f"duplicate {label} reference")
    return tuple(refs)


def _exact_decimal(value, label):
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise ComparisonError(f"{label} must be an exact decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex guards first
        raise ComparisonError(f"{label} must be an exact decimal string") from exc


@dataclass(frozen=True, slots=True, init=False)
class ComparisonPlan:
    """Every comparison condition, frozen before observation."""

    lineage_id: str
    baseline_environment: EntityRef
    queue: EntityRef
    quality_profile: EntityRef
    evaluator_bundle: EntityRef
    reset_manifest: EntityRef
    allowed_changes: EntityRef
    tool_effect_policy: EntityRef
    budget: EntityRef
    mode: str
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": COMPARISON_PLAN_SCHEMA_VERSION,
            "lineage_id": self.lineage_id,
            "baseline_environment_ref": self.baseline_environment.as_dict(),
            "queue_ref": self.queue.as_dict(),
            "quality_profile_ref": self.quality_profile.as_dict(),
            "evaluator_bundle_ref": self.evaluator_bundle.as_dict(),
            "reset_manifest_ref": self.reset_manifest.as_dict(),
            "allowed_changes_ref": self.allowed_changes.as_dict(),
            "tool_effect_policy_ref": self.tool_effect_policy.as_dict(),
            "budget_ref": self.budget.as_dict(),
            "mode": self.mode,
        }

    @property
    def plan_ref(self) -> EntityRef:
        # A content-derived id: two plans with different conditions can
        # never share (kind, id, version) — changed conditions are a new
        # lineage, never a same-name variant.
        digest = sha256(canonical_json(self.as_dict())).hexdigest()
        return EntityRef(
            "comparison_plan",
            str(uuid5(NAMESPACE_URL, f"deeptwin:comparison-plan:{digest}")),
            1,
            digest,
        )


def freeze_comparison_plan(value) -> ComparisonPlan:
    """Freeze one comparison lineage's conditions before any observation."""

    if type(value) is not dict or set(value) != {
        "lineage_id", "mode", *(name for name, _kind in _PLAN_BINDINGS),
    }:
        raise ComparisonError("expected the exact comparison plan object")
    lineage = value["lineage_id"]
    if type(lineage) is not str or _UUID.fullmatch(lineage) is None:
        raise ComparisonError("lineage id is not a canonical UUID")
    mode = value["mode"]
    if mode not in PLAN_MODES:
        raise ComparisonError("plan mode must be automatic or human_assisted")
    bindings = {
        name: _ref(value[name], kind, name.replace("_", " "))
        for name, kind in _PLAN_BINDINGS
    }
    return _issue(
        ComparisonPlan,
        lineage_id=lineage,
        mode=mode,
        _issuer_token=_ISSUE_TOKEN,
        **bindings,
    )


@dataclass(frozen=True, slots=True, init=False)
class ComparisonResult:
    """One paired round bound to its exact frozen plan."""

    plan_ref: EntityRef
    round_id: str
    round_index: int
    candidate: EntityRef
    baseline_runs: tuple[EntityRef, ...]
    candidate_runs: tuple[EntityRef, ...]
    validity: str
    validity_reasons: tuple[str, ...]
    mandatory_checks: EntityRef
    metric_vector: tuple[tuple[str, Decimal], ...] | None
    utility: Decimal | None
    evidence: tuple[EntityRef, ...]
    usage: EntityRef
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": COMPARISON_RESULT_SCHEMA_VERSION,
            "plan_ref": self.plan_ref.as_dict(),
            "round_id": self.round_id,
            "round_index": self.round_index,
            "candidate_ref": self.candidate.as_dict(),
            "baseline_run_refs": [item.as_dict() for item in self.baseline_runs],
            "candidate_run_refs": [item.as_dict() for item in self.candidate_runs],
            "validity": self.validity,
            "validity_reasons": list(self.validity_reasons),
            "mandatory_checks_ref": self.mandatory_checks.as_dict(),
            "metric_vector": (
                None if self.metric_vector is None
                else {name: str(metric) for name, metric in self.metric_vector}
            ),
            "utility": None if self.utility is None else str(self.utility),
            "evidence_refs": [item.as_dict() for item in self.evidence],
            "usage_ref": self.usage.as_dict(),
        }


def record_comparison_round(plan, value) -> ComparisonResult:
    """Record one paired round against a frozen plan, honestly."""

    if (
        type(plan) is not ComparisonPlan
        or getattr(plan, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise ComparisonError("a frozen comparison plan is required")
    if type(value) is not dict or set(value) != {
        "round_id", "round_index", "candidate", "baseline_runs",
        "candidate_runs", "validity", "validity_reasons", "mandatory_checks",
        "metric_vector", "utility", "evidence", "usage",
    }:
        raise ComparisonError("expected the exact comparison round object")
    round_id = value["round_id"]
    if (
        type(round_id) is not str
        or not 1 <= len(round_id.encode("utf-8")) <= 128
    ):
        raise ComparisonError("round id is out of bounds")
    round_index = value["round_index"]
    if type(round_index) is not int or not 0 <= round_index <= 100_000:
        raise ComparisonError("round index is out of bounds")
    baseline_runs = _run_refs(value["baseline_runs"], "baseline run")
    candidate_runs = _run_refs(value["candidate_runs"], "candidate run")
    if len(baseline_runs) != len(candidate_runs):
        raise ComparisonError(
            "paired execution requires equal baseline and candidate runs"
        )
    if set(baseline_runs) & set(candidate_runs):
        # A run compared against itself is not a paired execution of the
        # baseline and candidate environments.
        raise ComparisonError(
            "a run can never appear on both sides of one pairing"
        )
    validity = value["validity"]
    if validity not in VALIDITIES:
        raise ComparisonError("validity must be valid, invalid or pending")
    reasons = value["validity_reasons"]
    if (
        type(reasons) is not list or len(reasons) > 32
        or any(
            type(item) is not str
            or not 1 <= len(item.encode("utf-8")) <= 1_024
            for item in reasons
        )
    ):
        raise ComparisonError("validity reasons are out of bounds")
    if validity == "invalid" and not reasons:
        raise ComparisonError("an invalid round must state its reasons")

    metric_vector = value["metric_vector"]
    utility = value["utility"]
    if validity != "valid":
        # A missing or failed measurement never becomes a score of any kind.
        if metric_vector is not None or utility is not None:
            raise ComparisonError(
                "only a valid round may carry measurements or a utility"
            )
        metrics = None
        parsed_utility = None
    else:
        if metric_vector is None:
            metrics = None
        else:
            if (
                type(metric_vector) is not dict
                or not 1 <= len(metric_vector) <= 64
            ):
                raise ComparisonError("metric vector is out of bounds")
            metrics = tuple(sorted(
                (
                    name if type(name) is str
                    and 1 <= len(name.encode("utf-8")) <= 128
                    else _fail_metric_name(),
                    _exact_decimal(metric, f"metric {name!r}"),
                )
                for name, metric in metric_vector.items()
            ))
        parsed_utility = (
            None if utility is None else _exact_decimal(utility, "utility")
        )

    evidence = value["evidence"]
    if type(evidence) is not list or len(evidence) > 64:
        raise ComparisonError("evidence references are out of bounds")
    evidence_refs = tuple(
        _ref(item, "comparison_result", "evidence") for item in evidence
    )
    return _issue(
        ComparisonResult,
        plan_ref=plan.plan_ref,
        round_id=round_id,
        round_index=round_index,
        candidate=_ref(value["candidate"], "change_candidate", "candidate"),
        baseline_runs=baseline_runs,
        candidate_runs=candidate_runs,
        validity=validity,
        validity_reasons=tuple(reasons),
        mandatory_checks=_ref(
            value["mandatory_checks"], "validation_report", "mandatory checks",
        ),
        metric_vector=metrics,
        utility=parsed_utility,
        evidence=evidence_refs,
        usage=_ref(value["usage"], "decision_record", "usage"),
        _issuer_token=_ISSUE_TOKEN,
    )


def _fail_metric_name():
    raise ComparisonError("a metric name is out of bounds")


def is_recorded_round(value: object) -> bool:
    """True only for a round recorded by record_comparison_round."""

    return (
        type(value) is ComparisonResult
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def comparison_result_ref(result) -> EntityRef:
    """The content-derived reference of one recorded round."""

    if not is_recorded_round(result):
        raise ComparisonError("a recorded comparison round is required")
    digest = sha256(canonical_json(result.as_dict())).hexdigest()
    return EntityRef("comparison_result",
                     str(uuid5(NAMESPACE_URL, f"deeptwin:comparison-result:{digest}")), 1, digest)


def is_frozen_plan(value: object) -> bool:
    """True only for a plan issued by freeze_comparison_plan."""

    return (
        type(value) is ComparisonPlan
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


__all__ = [
    "COMPARISON_PLAN_SCHEMA_VERSION",
    "COMPARISON_RESULT_SCHEMA_VERSION",
    "PLAN_MODES",
    "VALIDITIES",
    "ComparisonError",
    "ComparisonPlan",
    "ComparisonResult",
    "comparison_result_ref",
    "freeze_comparison_plan",
    "is_frozen_plan",
    "is_recorded_round",
    "record_comparison_round",
]
