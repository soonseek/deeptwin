"""Typed change-candidate compilation (US5, T057, FR-020/021).

A change candidate has exactly two admissions (growth.md §4). A concluded
*supported* inquiry grounds any kind; and — because SPLI is not forced on
every deficit — a `system` hypothesis *confirmed* over its competitors grounds
a `restore` candidate directly (the system-repair path: restoration first),
never `learn` or `protect`, whose grounds are an expert judgment difference.
Each candidate records which admission grounded it.
The compiler binds every patch field (condition/action/exception) to its own
provenance, and each provenance reference must be evidence the inquiry actually
observed after its freeze — real change grounds connected to the exact
modification. Two absorption shortcuts are blocked structurally: patch text may
not contain verbatim spans of forbidden material (the alternative's own wording
or philosophy sources; whitespace-normalized matching), and no reference into
the unpromoted alternative/interpretation store may appear anywhere in a
compiled candidate. The leak check is not optional: the caller must hand the
compiler the forbidden source material (at least the alternative's own
wording) on every compilation, so a call that forgot it fails instead of
passing unchecked. Candidates are issued (init-disabled, tokened), never
constructed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef
from ..services.diagnosis import is_issued_hypothesis_set
from ..services.inquiry import is_issued_inquiry

CHANGE_KINDS = frozenset({"restore", "learn", "protect"})
GROUNDS = frozenset({"supported_inquiry", "confirmed_system_hypothesis"})
_FORBIDDEN_REF_KINDS = frozenset({
    "own_alternative", "difference", "hypothesis", "selector",
})
_PATCH_FIELDS = ("condition", "action", "exception")
_ISSUE_TOKEN = object()
_WHITESPACE = re.compile(r"\s+")


class ChangeCompilerError(ValueError):
    """A change candidate cannot be compiled as presented."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _text(value, label, maximum):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise ChangeCompilerError(f"invalid {label}")
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise ChangeCompilerError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise ChangeCompilerError(f"invalid {label} reference kind")
    return result


def _normalized(value: str) -> str:
    # NFKC folds compatibility variants (e.g. fullwidth letters) and the
    # format-character strip removes zero-width evasion before comparison.
    folded = unicodedata.normalize("NFKC", value)
    visible = "".join(
        ch for ch in folded if unicodedata.category(ch) != "Cf"
    )
    return _WHITESPACE.sub(" ", visible).strip()


@dataclass(frozen=True, slots=True, init=False)
class PatchField:
    """One patch clause with its own behavior provenance."""

    text: str
    evidence_refs: tuple[EntityRef, ...]


@dataclass(frozen=True, slots=True, init=False)
class ChangeCandidate:
    """A typed, provenance-bound change; issued only by the compiler."""

    kind: str
    condition: PatchField
    action: PatchField
    exception: PatchField
    change_scope: str
    predicted_impact_scope: str
    parent_environment: EntityRef
    compatibility: EntityRef
    rollback_bundle: EntityRef
    inquiry_ref: EntityRef
    grounds: str
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        def clause(item: PatchField) -> dict:
            return {
                "text": item.text,
                "evidence_refs": [ref.as_dict() for ref in item.evidence_refs],
            }

        return {
            "schema_version": "change-candidate-v1",
            "kind": self.kind,
            "condition": clause(self.condition),
            "action": clause(self.action),
            "exception": clause(self.exception),
            "change_scope": self.change_scope,
            "predicted_impact_scope": self.predicted_impact_scope,
            "parent_environment_ref": self.parent_environment.as_dict(),
            "compatibility_ref": self.compatibility.as_dict(),
            "rollback_bundle_ref": self.rollback_bundle.as_dict(),
            "inquiry_difference_ref": self.inquiry_ref.as_dict(),
            "grounds": self.grounds,
        }


def _patch_field(
    value,
    label,
    observed: dict,
    forbidden: tuple[str, ...],
) -> PatchField:
    if type(value) is not dict or set(value) != {"text", "evidence_refs"}:
        raise ChangeCompilerError(f"expected the exact {label} clause")
    text = _text(value["text"], f"{label} text", 4_096)
    flattened = _normalized(text)
    for span in forbidden:
        if span and span in flattened:
            # Copying the alternative's wording (or philosophy material) into
            # an operational patch is the forbidden absorption shortcut.
            raise ChangeCompilerError(
                f"the {label} text copies forbidden source material"
            )
    refs = value["evidence_refs"]
    if type(refs) is not list or not 1 <= len(refs) <= 32:
        raise ChangeCompilerError(
            f"the {label} clause requires bounded behavior provenance"
        )
    resolved = []
    for item in refs:
        try:
            ref = EntityRef.from_dict(item)
        except (DomainContractError, TypeError) as exc:
            raise ChangeCompilerError(
                f"invalid {label} provenance reference"
            ) from exc
        if ref.kind in _FORBIDDEN_REF_KINDS:
            raise ChangeCompilerError(
                "the unpromoted alternative store never enters a candidate"
            )
        if (ref.kind, ref.id, ref.version, ref.sha256) not in observed:
            raise ChangeCompilerError(
                f"the {label} provenance must be the inquiry's fresh evidence"
            )
        resolved.append(ref)
    return _issue(PatchField, text=text, evidence_refs=tuple(resolved))


def _forbidden(forbidden_spans) -> tuple[str, ...]:
    if type(forbidden_spans) is not list or not 1 <= len(forbidden_spans) <= 256:
        # the leak check is mandatory: at least the alternative's own wording
        raise ChangeCompilerError(
            "forbidden source material is required for every compilation"
        )
    return tuple(
        _normalized(_text(item, "forbidden span", 4_096)) for item in forbidden_spans
    )


def _compile(value, *, observed, forbidden, grounds, difference_ref, kinds) -> ChangeCandidate:
    if type(value) is not dict or set(value) != {
        "kind", "condition", "action", "exception", "change_scope",
        "predicted_impact_scope", "parent_environment", "compatibility",
        "rollback_bundle",
    }:
        raise ChangeCompilerError("expected the exact change patch object")
    kind = value["kind"]
    if kind not in CHANGE_KINDS:
        raise ChangeCompilerError("change kind must be restore, learn or protect")
    if kind not in kinds:
        raise ChangeCompilerError(
            "a confirmed system hypothesis grounds a restore candidate only"
        )
    clauses = {
        label: _patch_field(value[label], label, observed, forbidden)
        for label in _PATCH_FIELDS
    }
    scopes = {}
    for label in ("change_scope", "predicted_impact_scope"):
        text = _text(value[label], label.replace("_", " "), 2_048)
        flattened = _normalized(text)
        for span in forbidden:
            if span and span in flattened:
                # Scope prose is downstream-visible text too; the forbidden
                # absorption shortcut is blocked in every free-text field.
                raise ChangeCompilerError(
                    f"the {label} text copies forbidden source material"
                )
        scopes[label] = text
    return _issue(
        ChangeCandidate,
        kind=kind,
        condition=clauses["condition"],
        action=clauses["action"],
        exception=clauses["exception"],
        change_scope=scopes["change_scope"],
        predicted_impact_scope=scopes["predicted_impact_scope"],
        parent_environment=_ref(
            value["parent_environment"], "environment", "parent environment",
        ),
        compatibility=_ref(
            value["compatibility"], "validation_report", "compatibility",
        ),
        rollback_bundle=_ref(
            value["rollback_bundle"], "backup_manifest", "rollback bundle",
        ),
        inquiry_ref=difference_ref,
        grounds=grounds,
        _issuer_token=_ISSUE_TOKEN,
    )


def compile_change_candidate(inquiry, value, *, forbidden_spans) -> ChangeCandidate:
    """Compile one typed change candidate from a supported inquiry."""

    if not is_issued_inquiry(inquiry):
        # A look-alike Inquiry that never went through open/observe/conclude
        # carries none of the freeze-ordering or evidence discipline.
        raise ChangeCompilerError("a concluded inquiry is required")
    if inquiry.outcome != "supported":
        raise ChangeCompilerError(
            "only a supported inquiry outcome can ground a change candidate"
        )
    forbidden = _forbidden(forbidden_spans)
    observed = {
        (ref.kind, ref.id, ref.version, ref.sha256)
        for _stamp, ref in inquiry.new_evidence
    }
    return _compile(value, observed=observed, forbidden=forbidden,
                    grounds="supported_inquiry", difference_ref=inquiry.difference_ref,
                    kinds=CHANGE_KINDS)


def compile_system_restore(hypotheses, hypothesis_id, value, *, forbidden_spans) -> ChangeCandidate:
    """Compile a restore candidate on growth §4's system-repair path.

    The named hypothesis must be a `system` hypothesis the framework-issued set
    records as *confirmed* — which the set itself allows only after every
    competitor was examined, over evidence outside the alternative and
    difference — and every clause's provenance must be part of that
    confirmation basis. No inquiry is required and none is implied.
    """

    if not is_issued_hypothesis_set(hypotheses):
        raise ChangeCompilerError("a framework-issued hypothesis set is required")
    target = next((item for item in hypotheses.hypotheses
                   if item.hypothesis_id == hypothesis_id), None)
    if target is None or target.family != "system" or target.status != "confirmed":
        raise ChangeCompilerError(
            "the system-repair path needs a confirmed system hypothesis"
        )
    forbidden = _forbidden(forbidden_spans)
    observed = {
        (ref.kind, ref.id, ref.version, ref.sha256) for ref in target.confirmation_basis
    }
    return _compile(value, observed=observed, forbidden=forbidden,
                    grounds="confirmed_system_hypothesis",
                    difference_ref=hypotheses.difference_ref, kinds={"restore"})


def is_compiled_candidate(value: object) -> bool:
    """True only for a ChangeCandidate issued by this compiler."""

    return (
        type(value) is ChangeCandidate
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


__all__ = [
    "CHANGE_KINDS",
    "GROUNDS",
    "ChangeCandidate",
    "ChangeCompilerError",
    "PatchField",
    "compile_change_candidate",
    "compile_system_restore",
    "is_compiled_candidate",
]
