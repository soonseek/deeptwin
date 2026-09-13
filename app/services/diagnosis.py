"""Difference and hypothesis contracts for the growth journey (US5, FR-018).

A :class:`Difference` carries format-aware *observations* bound to the exact
original/alternative artifacts and the alternative's stated scopes — never a
causal interpretation; interpretation lives only in :class:`Hypothesis` objects
of the five contract families, which must compete. Confirming one hypothesis
while its competitors are still unexamined is the forbidden single-cause
shortcut, and a confirmation basis must be real comparison/behavior evidence
references — the difference record itself (a string diff) can never confirm a
judgment difference, and non-referential grounds (model confidence, philosopher
authority, human silence) cannot enter a basis at all because a basis is made of
exact entity references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from hashlib import sha256

from ..domain.refs import DomainContractError, EntityRef, canonical_json
from .alternatives import OwnAlternative

DIFFERENCE_SCHEMA_VERSION = "difference-v1"
OBSERVATION_KINDS = frozenset({
    "text_change", "table_change", "page_region_change",
    "image_region_change", "time_range_change", "structure_change",
})
HYPOTHESIS_FAMILIES = frozenset({
    "system", "expert_judgment", "exception", "alternative_error",
    "no_generalization",
})
RESOLVED_STATUSES = frozenset({"supported", "confirmed", "refuted", "unresolved"})
_EVIDENCE_KINDS = frozenset({"comparison_result", "artifact", "handoff"})
_OBSERVATION_ID = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*\Z")


class DiagnosisError(ValueError):
    """A difference, hypothesis or transition is invalid."""


def _strict(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise DiagnosisError(f"expected the exact {label} object")
    return value


def _text(value, label, maximum):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise DiagnosisError(f"invalid {label}")
    return value


def _text_list(value, label, *, maximum, minimum=0):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise DiagnosisError(f"expected a bounded {label} list")
    return tuple(_text(item, label, 1_024) for item in value)


def _evidence_refs(value, label, *, minimum):
    if type(value) is not list or not minimum <= len(value) <= 64:
        raise DiagnosisError(f"expected a bounded {label} list")
    refs = []
    for item in value:
        try:
            ref = EntityRef.from_dict(item)
        except (DomainContractError, TypeError) as exc:
            raise DiagnosisError(f"invalid {label} reference") from exc
        if ref.kind not in _EVIDENCE_KINDS:
            # A string diff (the difference record) or any other non-evidence
            # kind can never ground a judgment about causes.
            raise DiagnosisError(
                f"a {label} reference must be comparison or behavior evidence"
            )
        refs.append(ref)
    return tuple(refs)


@dataclass(frozen=True, slots=True)
class Observation:
    """One observable, format-aware difference; never an interpretation."""

    observation_id: str
    kind: str
    locator: tuple[tuple[str, object], ...] = field(repr=False)
    description: str

    @classmethod
    def from_untrusted(cls, value) -> Observation:
        _strict(
            value, {"observation_id", "kind", "locator", "description"},
            "observation",
        )
        identifier = _text(value["observation_id"], "observation id", 128)
        if _OBSERVATION_ID.fullmatch(identifier) is None:
            raise DiagnosisError("invalid observation id")
        kind = value["kind"]
        if kind not in OBSERVATION_KINDS:
            raise DiagnosisError("unknown observation kind")
        locator = value["locator"]
        if (
            type(locator) is not dict
            or not 1 <= len(locator) <= 16
            or any(type(name) is not str for name in locator)
            or len(canonical_json(locator)) > 4_096
        ):
            raise DiagnosisError("observation locator is out of bounds")
        return cls(
            identifier,
            kind,
            tuple(sorted(locator.items())),
            _text(value["description"], "observation description", 4_096),
        )

    def as_dict(self) -> dict:
        return {
            "observation_id": self.observation_id,
            "kind": self.kind,
            "locator": dict(self.locator),
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class Difference:
    """Observed differences plus stated scopes; interpretation lives elsewhere."""

    original_artifact: EntityRef
    alternative_artifact: EntityRef
    alignment: tuple[dict, ...] = field(repr=False)
    observations: tuple[Observation, ...]
    evidence_scope: tuple[str, ...]
    unreviewed_scope: str
    uncertainties: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "schema_version": DIFFERENCE_SCHEMA_VERSION,
            "original_artifact_ref": self.original_artifact.as_dict(),
            "alternative_artifact_ref": self.alternative_artifact.as_dict(),
            "alignment": list(self.alignment),
            "observations": [item.as_dict() for item in self.observations],
            "evidence_scope": list(self.evidence_scope),
            "unreviewed_scope": self.unreviewed_scope,
            "uncertainties": list(self.uncertainties),
        }

    @property
    def difference_ref(self) -> EntityRef:
        return EntityRef(
            "difference",
            self.original_artifact.id,
            1,
            sha256(canonical_json(self.as_dict())).hexdigest(),
        )


def record_difference(alternative, observations, *, uncertainties) -> Difference:
    """Record observable differences for one accepted alternative."""

    if type(alternative) is not OwnAlternative:
        raise DiagnosisError("an accepted own alternative is required")
    if type(observations) is not list or not 1 <= len(observations) <= 256:
        raise DiagnosisError("observations are out of bounds")
    return Difference(
        original_artifact=alternative.original_artifact,
        alternative_artifact=alternative.alternative_artifact,
        alignment=tuple(item.as_dict() for item in alternative.selectors),
        observations=tuple(
            Observation.from_untrusted(item) for item in observations
        ),
        evidence_scope=alternative.evidence_scope,
        unreviewed_scope=alternative.unreviewed_scope,
        uncertainties=_text_list(uncertainties, "uncertainty", maximum=64),
    )


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """One competing interpretation; transitions happen only through the set."""

    hypothesis_id: str
    family: str
    claim: str
    conditions: tuple[str, ...]
    predictions: tuple[str, ...]
    status: str
    support: tuple[EntityRef, ...]
    counterevidence: tuple[EntityRef, ...]
    confirmation_basis: tuple[EntityRef, ...]


@dataclass(frozen=True, slots=True)
class HypothesisSet:
    """The competing hypotheses of one difference; immutable evolution only."""

    difference_ref: EntityRef
    hypotheses: tuple[Hypothesis, ...]

    def resolve(self, hypothesis_id, status, *, basis_refs) -> HypothesisSet:
        if status not in RESOLVED_STATUSES:
            raise DiagnosisError("unknown hypothesis resolution status")
        target = None
        for item in self.hypotheses:
            if item.hypothesis_id == hypothesis_id:
                target = item
        if target is None:
            raise DiagnosisError("unknown hypothesis id")
        if target.status != "proposed":
            raise DiagnosisError(
                "a resolved hypothesis cannot transition again"
            )
        if status == "confirmed":
            if any(
                item.status == "proposed"
                and item.hypothesis_id != hypothesis_id
                for item in self.hypotheses
            ):
                # The forbidden single-cause shortcut: competitors must be
                # examined before any confirmation.
                raise DiagnosisError(
                    "competing hypotheses must be examined before confirmation"
                )
            basis = _evidence_refs(basis_refs, "confirmation basis", minimum=1)
            updated = replace(
                target, status=status, confirmation_basis=basis, support=basis,
            )
        elif status == "refuted":
            basis = _evidence_refs(basis_refs, "counterevidence", minimum=1)
            updated = replace(target, status=status, counterevidence=basis)
        elif status == "supported":
            basis = _evidence_refs(basis_refs, "support", minimum=1)
            updated = replace(target, status=status, support=basis)
        else:
            _evidence_refs(basis_refs, "evidence", minimum=0)
            updated = replace(target, status=status)
        return HypothesisSet(
            difference_ref=self.difference_ref,
            hypotheses=tuple(
                updated if item.hypothesis_id == hypothesis_id else item
                for item in self.hypotheses
            ),
        )


def propose_hypotheses(difference, values) -> HypothesisSet:
    """Open one competing hypothesis set over a recorded difference."""

    if type(difference) is not Difference:
        raise DiagnosisError("a recorded difference is required")
    if type(values) is not list or not 1 <= len(values) <= 16:
        raise DiagnosisError("hypothesis proposals are out of bounds")
    hypotheses = []
    for index, value in enumerate(values):
        _strict(value, {"family", "claim", "conditions", "predictions"}, "hypothesis")
        family = value["family"]
        if family not in HYPOTHESIS_FAMILIES:
            raise DiagnosisError("unknown hypothesis family")
        hypotheses.append(Hypothesis(
            hypothesis_id=f"{family}-{index}",
            family=family,
            claim=_text(value["claim"], "hypothesis claim", 4_096),
            conditions=_text_list(
                value["conditions"], "hypothesis condition", maximum=32,
            ),
            predictions=_text_list(
                value["predictions"], "hypothesis prediction", maximum=32,
            ),
            status="proposed",
            support=(),
            counterevidence=(),
            confirmation_basis=(),
        ))
    families = {item.family for item in hypotheses}
    if families != {"no_generalization"} and len(families) < 2:
        # A lone causal family is a single-cause claim before any evidence.
        raise DiagnosisError(
            "hypotheses must compete across families or state no generalization"
        )
    return HypothesisSet(
        difference_ref=difference.difference_ref,
        hypotheses=tuple(hypotheses),
    )


__all__ = [
    "DIFFERENCE_SCHEMA_VERSION",
    "HYPOTHESIS_FAMILIES",
    "OBSERVATION_KINDS",
    "RESOLVED_STATUSES",
    "DiagnosisError",
    "Difference",
    "Hypothesis",
    "HypothesisSet",
    "Observation",
    "propose_hypotheses",
    "record_difference",
]
