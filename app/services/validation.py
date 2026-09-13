"""Sealed validation for frozen candidates (US6, T064, FR-025).

A :func:`freeze_candidate` fixes the full compatibility bundle — environment
graph, model bindings, prompts, knowledge rules, archetype I/O, tool
permissions, lens versions, scope, evaluation/approval policy, dependencies
and rollback — under one content hash; changing anything is a new candidate.
The dataset ledger separates tuning, sealed-validation and prospective data:
a sealed dataset exposed to tuning or candidate authoring is reclassified to
development permanently, a dataset consumed by a validation run is seen
forever, and no operation relabels seen data unseen. A validation run keeps
the §8 report categories distinct, requires reasons on every failed gate,
treats judge failure as invalid without erasing real failures, and confines
shadow observation and user-approved limited application to their own modes —
neither ever claims sealed-offline coverage. Values are issued, never
constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256

from ..domain.refs import DomainContractError, EntityRef, canonical_json

VALIDATION_REPORT_SCHEMA_VERSION = "validation-report-v1"
GATES = (
    "reconstruction", "heldout_transfer", "boundary_exclusion",
    "regression", "leakage", "side_effects",
)
MODES = frozenset({"sealed_offline", "shadow", "limited_application"})
CLASSIFICATIONS = frozenset({"tuning", "sealed_validation", "prospective"})
EXPOSURE_PURPOSES = frozenset({
    "tuning", "candidate_authoring", "report_review", "validation",
})
_BUNDLE_BINDINGS = (
    ("candidate", "change_candidate"),
    ("environment_graph", "environment"),
    ("model_bindings", "model_choice"),
    ("prompts", "artifact"),
    ("knowledge_rules", "decision_record"),
    ("archetype_io", "observation_contract"),
    ("tool_permissions", "grant"),
    ("lens_versions", "lens_composition"),
    ("scope", "decision_record"),
    ("evaluation_policy", "evaluation_profile"),
    ("approval_policy", "decision_record"),
    ("dependencies", "run_manifest"),
    ("rollback_bundle", "backup_manifest"),
)
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_ISSUE_TOKEN = object()


class GrowthValidationError(ValueError):
    """A candidate bundle, dataset ledger or validation run is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise GrowthValidationError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise GrowthValidationError(f"invalid {label} reference kind")
    return result


@dataclass(frozen=True, slots=True, init=False)
class FrozenCandidate:
    """One candidate's full compatibility bundle under one content hash."""

    candidate: EntityRef
    environment_graph: EntityRef
    model_bindings: EntityRef
    prompts: EntityRef
    knowledge_rules: EntityRef
    archetype_io: EntityRef
    tool_permissions: EntityRef
    lens_versions: EntityRef
    scope: EntityRef
    evaluation_policy: EntityRef
    approval_policy: EntityRef
    dependencies: EntityRef
    rollback_bundle: EntityRef
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "frozen-candidate-v1",
            **{
                f"{name}_ref": getattr(self, name).as_dict()
                for name, _kind in _BUNDLE_BINDINGS
            },
        }

    @property
    def bundle_ref(self) -> EntityRef:
        return EntityRef(
            "environment",
            self.candidate.id,
            self.candidate.version,
            sha256(canonical_json(self.as_dict())).hexdigest(),
        )


def freeze_candidate(value) -> FrozenCandidate:
    """Freeze one candidate's bundle; any modification is a new candidate."""

    if type(value) is not dict or set(value) != {
        name for name, _kind in _BUNDLE_BINDINGS
    }:
        raise GrowthValidationError("expected the exact candidate bundle object")
    return _issue(
        FrozenCandidate,
        _issuer_token=_ISSUE_TOKEN,
        **{
            name: _ref(value[name], kind, name.replace("_", " "))
            for name, kind in _BUNDLE_BINDINGS
        },
    )


@dataclass(frozen=True, slots=True, init=False)
class DatasetLedger:
    """One lineage's dataset classifications and exposure history."""

    lineage_id: str
    # entries: (dataset_id, classification, manifest, seen)
    entries: tuple[tuple[str, str, EntityRef, bool], ...]
    _issuer_token: object = field(repr=False, compare=False)


def _require_ledger(value) -> None:
    if (
        type(value) is not DatasetLedger
        or getattr(value, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise GrowthValidationError("a framework-issued dataset ledger is required")


def open_dataset_ledger(lineage_id) -> DatasetLedger:
    if type(lineage_id) is not str or _UUID.fullmatch(lineage_id) is None:
        raise GrowthValidationError("lineage id is not a canonical UUID")
    return _issue(
        DatasetLedger, lineage_id=lineage_id, entries=(),
        _issuer_token=_ISSUE_TOKEN,
    )


def register_dataset(ledger, value) -> DatasetLedger:
    """Register one dataset exactly once; an id can never be re-registered."""

    _require_ledger(ledger)
    if type(value) is not dict or set(value) != {
        "dataset_id", "classification", "manifest",
    }:
        raise GrowthValidationError("expected the exact dataset object")
    dataset_id = value["dataset_id"]
    if (
        type(dataset_id) is not str
        or not 1 <= len(dataset_id.encode("utf-8")) <= 128
    ):
        raise GrowthValidationError("dataset id is out of bounds")
    if any(dataset_id == entry[0] for entry in ledger.entries):
        # Re-registration is the relabeling attack: seen data would come
        # back unseen under the same name. There is no such path.
        raise GrowthValidationError("a dataset id can never be re-registered")
    classification = value["classification"]
    if classification not in CLASSIFICATIONS:
        raise GrowthValidationError("unknown dataset classification")
    manifest = _ref(value["manifest"], "run_manifest", "dataset manifest")
    if len(ledger.entries) >= 1_024:
        raise GrowthValidationError("dataset ledger is full")
    return _issue(
        DatasetLedger,
        lineage_id=ledger.lineage_id,
        entries=(*ledger.entries, (dataset_id, classification, manifest, False)),
        _issuer_token=_ISSUE_TOKEN,
    )


def expose_dataset(ledger, dataset_id, purpose) -> DatasetLedger:
    """Record one exposure; sealed data touched by development is burned."""

    _require_ledger(ledger)
    if purpose not in EXPOSURE_PURPOSES:
        raise GrowthValidationError("unknown exposure purpose")
    entries = []
    found = False
    for entry_id, classification, manifest, seen in ledger.entries:
        if entry_id == dataset_id:
            found = True
            if classification in {"sealed_validation", "prospective"} and (
                purpose in {"tuning", "candidate_authoring", "report_review"}
            ):
                # Development exposure burns sealed data permanently.
                classification = "tuning"
            seen = True
        entries.append((entry_id, classification, manifest, seen))
    if not found:
        raise GrowthValidationError("unknown dataset id")
    return _issue(
        DatasetLedger,
        lineage_id=ledger.lineage_id,
        entries=tuple(entries),
        _issuer_token=_ISSUE_TOKEN,
    )


def unseen_dataset_ids(ledger) -> tuple[str, ...]:
    """Sealed or prospective datasets that were never exposed to anything."""

    _require_ledger(ledger)
    return tuple(
        entry_id
        for entry_id, classification, _manifest, seen in ledger.entries
        if classification in {"sealed_validation", "prospective"} and not seen
    )


@dataclass(frozen=True, slots=True, init=False)
class GateOutcome:
    """One §8 report category's outcome with its evidence and reasons."""

    status: str
    evidence: tuple[EntityRef, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True, init=False)
class ValidationReport:
    """One validation run bound to the exact frozen candidate bundle."""

    candidate_bundle: EntityRef
    mode: str
    status: str
    datasets: tuple[str, ...]
    gates: tuple[tuple[str, GateOutcome], ...]
    approved_scope: EntityRef | None
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": VALIDATION_REPORT_SCHEMA_VERSION,
            "candidate_bundle_ref": self.candidate_bundle.as_dict(),
            "mode": self.mode,
            "status": self.status,
            "dataset_ids": list(self.datasets),
            "gates": {
                name: {
                    "status": outcome.status,
                    "evidence_refs": [
                        item.as_dict() for item in outcome.evidence
                    ],
                    "reasons": list(outcome.reasons),
                }
                for name, outcome in self.gates
            },
            "approved_scope_ref": (
                None if self.approved_scope is None
                else self.approved_scope.as_dict()
            ),
        }


def _parse_gate(name, value) -> GateOutcome:
    if type(value) is not dict or set(value) != {
        "status", "evidence", "reasons",
    }:
        raise GrowthValidationError(f"expected the exact {name} gate object")
    status = value["status"]
    if status not in {"pass", "fail", "invalid"}:
        raise GrowthValidationError(f"{name} gate status is unknown")
    evidence = value["evidence"]
    if type(evidence) is not list or len(evidence) > 64:
        raise GrowthValidationError(f"{name} gate evidence is out of bounds")
    reasons = value["reasons"]
    if (
        type(reasons) is not list or len(reasons) > 32
        or any(
            type(item) is not str
            or not 1 <= len(item.encode("utf-8")) <= 1_024
            for item in reasons
        )
    ):
        raise GrowthValidationError(f"{name} gate reasons are out of bounds")
    if status == "fail" and not reasons:
        # validation_failed always leaves its causes (§7).
        raise GrowthValidationError(f"a failed {name} gate must state reasons")
    return _issue(
        GateOutcome,
        status=status,
        evidence=tuple(
            _ref(item, "comparison_result", f"{name} evidence")
            for item in evidence
        ),
        reasons=tuple(reasons),
    )


def run_validation(candidate, ledger, value):
    """Run one validation; sealed data is consumed exactly once, honestly."""

    if (
        type(candidate) is not FrozenCandidate
        or getattr(candidate, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise GrowthValidationError("a frozen candidate bundle is required")
    _require_ledger(ledger)
    if type(value) is not dict or set(value) != {
        "mode", "datasets", "gates", "approved_scope",
    }:
        raise GrowthValidationError("expected the exact validation run object")
    mode = value["mode"]
    if mode not in MODES:
        raise GrowthValidationError("unknown validation mode")
    datasets = value["datasets"]
    if type(datasets) is not list or len(datasets) > 64:
        raise GrowthValidationError("dataset ids are out of bounds")
    if len(set(datasets)) != len(datasets):
        raise GrowthValidationError("duplicate dataset id in one run")
    approved_scope = value["approved_scope"]
    if mode == "limited_application":
        if approved_scope is None:
            raise GrowthValidationError(
                "limited application requires the exact user-approved scope"
            )
        approved_scope = _ref(
            approved_scope, "decision_record", "approved scope",
        )
    elif approved_scope is not None:
        raise GrowthValidationError(
            "only limited application carries an approved scope"
        )
    if mode != "sealed_offline":
        if datasets:
            # Shadow observation and limited application never consume
            # sealed data as an unseen pass.
            raise GrowthValidationError(
                f"{mode} validation never consumes sealed datasets"
            )
    elif not datasets:
        raise GrowthValidationError(
            "sealed offline validation requires sealed datasets"
        )
    unseen = set(unseen_dataset_ids(ledger))
    for dataset_id in datasets:
        if dataset_id not in unseen:
            # Seen data is never relabeled unseen; a second unseen claim
            # requires genuinely new sealed data (FR-025, G-12).
            raise GrowthValidationError(
                "an unseen pass requires unexposed sealed data"
            )
    gates_value = value["gates"]
    if type(gates_value) is not dict or set(gates_value) != set(GATES):
        raise GrowthValidationError("expected the exact §8 gate set")
    gates = tuple(
        (name, _parse_gate(name, gates_value[name])) for name in GATES
    )
    statuses = {outcome.status for _name, outcome in gates}
    if "fail" in statuses:
        status = "failed"  # invalid never erases a real failure
    elif "invalid" in statuses:
        status = "invalid"
    else:
        status = "passed"
    seen_ledger = ledger
    for dataset_id in datasets:
        seen_ledger = expose_dataset(seen_ledger, dataset_id, "validation")
    report = _issue(
        ValidationReport,
        candidate_bundle=candidate.bundle_ref,
        mode=mode,
        status=status,
        datasets=tuple(datasets),
        gates=gates,
        approved_scope=approved_scope,
        _issuer_token=_ISSUE_TOKEN,
    )
    return report, seen_ledger


def is_validation_report(value: object) -> bool:
    """True only for a report issued by run_validation."""

    return (
        type(value) is ValidationReport
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def is_frozen_candidate(value: object) -> bool:
    """True only for a bundle issued by freeze_candidate."""

    return (
        type(value) is FrozenCandidate
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


__all__ = [
    "CLASSIFICATIONS",
    "EXPOSURE_PURPOSES",
    "GATES",
    "MODES",
    "VALIDATION_REPORT_SCHEMA_VERSION",
    "DatasetLedger",
    "FrozenCandidate",
    "GateOutcome",
    "GrowthValidationError",
    "ValidationReport",
    "expose_dataset",
    "freeze_candidate",
    "is_frozen_candidate",
    "is_validation_report",
    "open_dataset_ledger",
    "register_dataset",
    "run_validation",
    "unseen_dataset_ids",
]
