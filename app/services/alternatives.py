"""Own-alternative contracts for the growth journey (US4, FR-016/017/022).

The growth loop starts from a preserved original execution boundary and a
user-made alternative bound to one exact original artifact version. This module
enforces the entry guards: initial work descriptions, revision instructions,
review approvals, comments and empty drafts are never promoted into alternatives
(G-01) — they keep their own submission kind; derived or mock material is a
separate ``SyntheticAlternative`` type that can never count as real user
learning evidence. Partial selectors bind the exact original version's digest
and keep formal selection separate from semantic impact (G-02): the evidence
scope is exactly the selectors, the unreviewed area is stated rather than
claimed, and the impact scope always stays ``pending_investigation`` — partial
evidence never narrows it, and nothing here asserts user intent over unreviewed
area.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256

from ..domain.refs import DomainContractError, EntityRef, canonical_json

OWN_ALTERNATIVE_SCHEMA_VERSION = "own-alternative-v1"
SELECTOR_KINDS = frozenset({
    "whole", "text_span", "table_range", "page_region",
    "image_region", "time_range", "structured_path",
})
ALIGNMENTS = frozenset({"confirmed", "proposed", "unresolved"})
SUBMISSION_KINDS = frozenset({
    "user_artifact", "work_description", "revision_instruction",
    "review_approval", "comment",
})
_NON_ALTERNATIVE_KINDS = SUBMISSION_KINDS - {"user_artifact"}
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*\Z")


class AlternativeContractError(ValueError):
    """An original execution or alternative submission is invalid."""


class NonAlternativeSubmission(AlternativeContractError):
    """G-01: this submission keeps its own kind and never becomes an alternative."""

    def __init__(self, submission_kind: str) -> None:
        super().__init__(
            "this submission kind is preserved, not promoted to an alternative"
        )
        self.submission_kind = submission_kind


def _strict(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise AlternativeContractError(f"expected the exact {label} object")
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise AlternativeContractError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise AlternativeContractError(f"invalid {label} reference kind")
    return result


def _ref_list(value, kind, label, *, maximum, minimum=0):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise AlternativeContractError(f"expected a bounded {label} list")
    refs = [_ref(item, kind, label) for item in value]
    if len({(item.id, item.version, item.sha256) for item in refs}) != len(refs):
        raise AlternativeContractError(f"duplicate {label} reference")
    return tuple(refs)


def _text(value, label, maximum):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise AlternativeContractError(f"invalid {label}")
    return value


@dataclass(frozen=True, slots=True)
class Selector:
    """One formal selection bound to the exact original artifact version."""

    kind: str
    locator: tuple[tuple[str, object], ...] = field(repr=False)
    source_hash: str
    alignment: str

    @classmethod
    def from_untrusted(cls, value) -> Selector:
        _strict(value, {"kind", "locator", "source_hash", "alignment"}, "selector")
        kind = value["kind"]
        if kind not in SELECTOR_KINDS:
            raise AlternativeContractError("unknown selector kind")
        locator = value["locator"]
        if (
            type(locator) is not dict
            or not 1 <= len(locator) <= 16
            or any(type(name) is not str for name in locator)
            or len(canonical_json(locator)) > 4_096
        ):
            raise AlternativeContractError("selector locator is out of bounds")
        source_hash = value["source_hash"]
        if type(source_hash) is not str or _SHA256.fullmatch(source_hash) is None:
            raise AlternativeContractError("selector source hash is invalid")
        alignment = value["alignment"]
        if alignment not in ALIGNMENTS:
            raise AlternativeContractError("selector alignment is invalid")
        return cls(
            kind,
            tuple(sorted(locator.items())),
            source_hash,
            alignment,
        )

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "locator": dict(self.locator),
            "source_hash": self.source_hash,
            "alignment": self.alignment,
        }


@dataclass(frozen=True, slots=True)
class OriginalExecution:
    """A preserved node/task execution boundary; never a post-hoc reconstruction."""

    boundary_id: str
    work_revision_ref: EntityRef
    environment_ref: EntityRef
    input_refs: tuple[EntityRef, ...]
    output_refs: tuple[EntityRef, ...]
    handoff_refs: tuple[EntityRef, ...]
    tool_refs: tuple[EntityRef, ...]
    model_binding_refs: tuple[EntityRef, ...]
    observation_gaps: tuple[str, ...]

    @classmethod
    def from_untrusted(cls, value) -> OriginalExecution:
        _strict(value, {
            "boundary_id", "work_revision_ref", "environment_ref", "input_refs",
            "output_refs", "handoff_refs", "tool_refs", "model_binding_refs",
            "observation_gaps",
        }, "original execution")
        boundary = _text(value["boundary_id"], "boundary id", 128)
        if _IDENTIFIER.fullmatch(boundary) is None:
            raise AlternativeContractError("invalid boundary id")
        gaps = value["observation_gaps"]
        if type(gaps) is not list or len(gaps) > 64:
            raise AlternativeContractError("observation gaps are out of bounds")
        return cls(
            boundary,
            _ref(value["work_revision_ref"], "work_revision", "work revision"),
            _ref(value["environment_ref"], "environment", "environment"),
            _ref_list(value["input_refs"], "artifact", "input", maximum=128),
            _ref_list(
                value["output_refs"], "artifact", "output", maximum=128, minimum=1,
            ),
            _ref_list(value["handoff_refs"], "handoff", "handoff", maximum=128),
            _ref_list(value["tool_refs"], "tool_definition", "tool", maximum=128),
            _ref_list(
                value["model_binding_refs"], "model_choice", "model binding",
                maximum=128,
            ),
            tuple(_text(item, "observation gap", 1_024) for item in gaps),
        )


@dataclass(frozen=True, slots=True)
class OwnAlternative:
    """A frozen user-made alternative bound to one exact original artifact."""

    author_id: str
    created_at: str
    original: OriginalExecution = field(repr=False)
    original_artifact: EntityRef
    alternative_artifact: EntityRef
    coverage: str
    selectors: tuple[Selector, ...]
    optional_explanation: EntityRef | None

    @property
    def evidence_scope(self) -> tuple[str, ...]:
        if self.coverage == "whole":
            return ("whole",)
        return tuple(
            f"selector:{selector.kind}:{index}"
            for index, selector in enumerate(self.selectors)
        )

    @property
    def unreviewed_scope(self) -> str:
        if self.coverage == "whole":
            return "none"
        return f"outside_selectors:{self.original_artifact.sha256}"

    @property
    def impact_scope(self) -> str:
        # G-02: partial evidence never narrows the semantic impact scope, and
        # nothing asserts user intent over unreviewed area. Impact is always a
        # separate investigation outcome, never derived from selection.
        return "pending_investigation"

    @property
    def fully_aligned(self) -> bool:
        return all(item.alignment == "confirmed" for item in self.selectors)

    def as_dict(self) -> dict:
        return {
            "schema_version": OWN_ALTERNATIVE_SCHEMA_VERSION,
            "author_id": self.author_id,
            "created_at": self.created_at,
            "original_boundary_id": self.original.boundary_id,
            "original_artifact_ref": self.original_artifact.as_dict(),
            "alternative_artifact_ref": self.alternative_artifact.as_dict(),
            "coverage": self.coverage,
            "selectors": [item.as_dict() for item in self.selectors],
            "optional_explanation_ref": (
                None if self.optional_explanation is None
                else self.optional_explanation.as_dict()
            ),
            "evidence_scope": list(self.evidence_scope),
            "unreviewed_scope": self.unreviewed_scope,
            "impact_scope": self.impact_scope,
        }

    @property
    def alternative_ref(self) -> EntityRef:
        payload = self.as_dict()
        return EntityRef(
            "own_alternative",
            self.author_id,
            1,
            sha256(canonical_json(payload)).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class SyntheticAlternative:
    """Derived or mock material: a separate type, never user learning evidence."""

    inner: OwnAlternative = field(repr=False)
    is_user_learning_evidence: bool = False

    def as_dict(self) -> dict:
        payload = self.inner.as_dict()
        payload["synthetic"] = True
        return payload


def accept_own_alternative(original, value):
    """Accept one alternative submission against its preserved original."""

    if type(original) is not OriginalExecution:
        raise AlternativeContractError("a preserved original execution is required")
    _strict(value, {
        "author_id", "created_at", "submission_kind", "original_artifact",
        "alternative_artifact", "coverage", "selectors", "optional_explanation",
        "synthetic",
    }, "alternative submission")
    submission_kind = value["submission_kind"]
    if submission_kind in _NON_ALTERNATIVE_KINDS:
        raise NonAlternativeSubmission(submission_kind)
    if submission_kind != "user_artifact":
        raise AlternativeContractError("unknown submission kind")
    if value["alternative_artifact"] is None:
        raise NonAlternativeSubmission("empty_draft")

    author_id = value["author_id"]
    if type(author_id) is not str or _UUID.fullmatch(author_id) is None:
        raise AlternativeContractError("author id is not a canonical UUID")
    created_at = value["created_at"]
    if type(created_at) is not str or _STAMP.fullmatch(created_at) is None:
        raise AlternativeContractError("creation stamp is invalid")

    original_artifact = _ref(value["original_artifact"], "artifact", "original artifact")
    if original_artifact not in original.output_refs:
        raise AlternativeContractError(
            "the original artifact is not an output of this execution boundary"
        )
    alternative_artifact = _ref(
        value["alternative_artifact"], "artifact", "alternative artifact",
    )
    if alternative_artifact == original_artifact:
        raise AlternativeContractError(
            "an alternative must be a distinct user-made artifact"
        )

    coverage = value["coverage"]
    if coverage not in ("whole", "partial"):
        raise AlternativeContractError("coverage must be whole or partial")
    raw_selectors = value["selectors"]
    if type(raw_selectors) is not list or len(raw_selectors) > 64:
        raise AlternativeContractError("selectors are out of bounds")
    selectors = tuple(Selector.from_untrusted(item) for item in raw_selectors)
    if coverage == "whole" and selectors:
        raise AlternativeContractError("whole coverage carries no selectors")
    if coverage == "partial":
        if not selectors:
            raise AlternativeContractError("partial coverage requires selectors")
        for selector in selectors:
            if selector.kind == "whole":
                raise AlternativeContractError(
                    "a whole selector cannot express partial coverage"
                )
            if selector.source_hash != original_artifact.sha256:
                raise AlternativeContractError(
                    "a selector must bind the exact original artifact version"
                )

    explanation = value["optional_explanation"]
    if explanation is not None:
        explanation = _ref(explanation, "source", "optional explanation")

    synthetic = value["synthetic"]
    if type(synthetic) is not bool:
        raise AlternativeContractError("the synthetic flag must be explicit")

    accepted = OwnAlternative(
        author_id=author_id,
        created_at=created_at,
        original=original,
        original_artifact=original_artifact,
        alternative_artifact=alternative_artifact,
        coverage=coverage,
        selectors=selectors,
        optional_explanation=explanation,
    )
    if synthetic:
        return SyntheticAlternative(inner=accepted)
    return accepted


__all__ = [
    "ALIGNMENTS",
    "OWN_ALTERNATIVE_SCHEMA_VERSION",
    "SELECTOR_KINDS",
    "SUBMISSION_KINDS",
    "AlternativeContractError",
    "NonAlternativeSubmission",
    "OriginalExecution",
    "OwnAlternative",
    "Selector",
    "SyntheticAlternative",
    "accept_own_alternative",
]
