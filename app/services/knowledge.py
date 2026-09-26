"""Active conditional knowledge registry (US5, T058, FR-021/032).

Active knowledge is canonical structured condition/action/exception text with
behavior provenance — never an ever-growing prompt. Registration requires the
promoted candidate lineage (`change_candidate` + `action_approval` +
`validation_report` refs); the draft stores (alternatives, differences,
hypotheses, inquiries, selectors) are never operating memory in any field.
Retrieval filters scope, authority lifecycle, effective time and purpose, and
reports exactly which entries were supplied and which were excluded and why.
Conflicting authority within one scope is never averaged away: a second
active entry in a scope must explicitly supersede an existing one or it is
refused, and the superseded entry is preserved, never erased. A declared
condition change (policy, provider model, data conditions) moves the affected
scope's entries to ``revalidation_required``, excluding them from retrieval
until revalidated with fresh evidence — past qualification is never a
permanent guarantee. Values are issued, never constructed; the registry is an
immutable value, so single-writer transactions belong to the storage layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from ..domain.refs import DomainContractError, EntityRef

PURPOSES = frozenset({"operation", "tuning", "audit"})
LIFECYCLES = frozenset({
    "active", "superseded", "retired", "revalidation_required",
})
_DRAFT_KINDS = frozenset({
    "own_alternative", "difference", "hypothesis", "inquiry", "selector",
    # the owner's process feedback (mark and memo): an observation, not operating memory
    "process_feedback",
})
_PROVENANCE_KINDS = frozenset({
    "comparison_result", "validation_report", "decision_record",
})
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_ISSUE_TOKEN = object()


class KnowledgeError(ValueError):
    """A knowledge entry, registry operation or query is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kinds, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise KnowledgeError(f"invalid {label} reference") from exc
    if result.kind in _DRAFT_KINDS:
        # Draft diagnosis/alternative/inquiry stores are not operating memory.
        raise KnowledgeError(
            f"a draft-store reference can never enter {label}"
        )
    if result.kind not in kinds:
        raise KnowledgeError(f"invalid {label} reference kind")
    return result


def _text(value, label, maximum):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise KnowledgeError(f"invalid {label}")
    return value


def _stamp(value, label):
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise KnowledgeError(f"{label} must be a canonical UTC timestamp")
    try:
        # Naive-parse only: the exact string is stored verbatim; this call
        # validates calendar reality, never produces a datetime value.
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")  # noqa: DTZ007
    except ValueError as exc:
        raise KnowledgeError(f"{label} must be a canonical UTC timestamp") from exc
    return value


@dataclass(frozen=True, slots=True, init=False)
class ActiveKnowledge:
    """One canonical condition/action/exception with promoted provenance."""

    knowledge_id: str
    condition: str
    action: str
    exception: str
    scope: str
    purposes: tuple[str, ...]
    candidate: EntityRef
    approval: EntityRef
    compatibility: EntityRef
    provenance: tuple[EntityRef, ...]
    effective_from: str
    lifecycle: str
    lifecycle_reason: str | None
    supersedes: str | None
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "active-knowledge-v1",
            "knowledge_id": self.knowledge_id,
            "condition": self.condition,
            "action": self.action,
            "exception": self.exception,
            "scope": self.scope,
            "purposes": list(self.purposes),
            "candidate_ref": self.candidate.as_dict(),
            "approval_ref": self.approval.as_dict(),
            "compatibility_ref": self.compatibility.as_dict(),
            "provenance_refs": [item.as_dict() for item in self.provenance],
            "effective_from": self.effective_from,
            "lifecycle": self.lifecycle,
            "lifecycle_reason": self.lifecycle_reason,
            "supersedes": self.supersedes,
        }


@dataclass(frozen=True, slots=True, init=False)
class KnowledgeRegistry:
    """One registry value; evolution only through the module functions."""

    entries: tuple[ActiveKnowledge, ...]
    revision: int
    _issuer_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, init=False)
class RetrievalResult:
    """What one query actually supplied, and what it excluded and why."""

    query_scope: str
    query_purpose: str
    query_at: str
    entries: tuple[ActiveKnowledge, ...]
    # (knowledge_id, reason) for every scope-matching entry NOT supplied
    gaps: tuple[tuple[str, str], ...]


def is_issued_knowledge(value: object) -> bool:
    """True only for an entry issued through this module's functions."""

    return (
        type(value) is ActiveKnowledge
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def _require_registry(value) -> None:
    if (
        type(value) is not KnowledgeRegistry
        or getattr(value, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise KnowledgeError("a framework-issued knowledge registry is required")


def open_knowledge_registry() -> KnowledgeRegistry:
    return _issue(
        KnowledgeRegistry, entries=(), revision=1, _issuer_token=_ISSUE_TOKEN,
    )


def _reissue(registry, entries) -> KnowledgeRegistry:
    return _issue(
        KnowledgeRegistry,
        entries=tuple(entries),
        revision=registry.revision + 1,
        _issuer_token=_ISSUE_TOKEN,
    )


def _reissue_entry(entry: ActiveKnowledge, **changes) -> ActiveKnowledge:
    fields = {
        name: getattr(entry, name)
        for name in ActiveKnowledge.__slots__
        if name != "_issuer_token"
    }
    fields.update(changes)
    return _issue(ActiveKnowledge, _issuer_token=_ISSUE_TOKEN, **fields)


def register_knowledge(registry, value) -> KnowledgeRegistry:
    """Register one promoted entry; conflicts must supersede explicitly."""

    _require_registry(registry)
    if type(value) is not dict or set(value) != {
        "knowledge_id", "condition", "action", "exception", "scope",
        "purposes", "candidate", "approval", "compatibility", "provenance",
        "effective_from", "supersedes",
    }:
        raise KnowledgeError("expected the exact knowledge entry object")
    knowledge_id = _text(value["knowledge_id"], "knowledge id", 128)
    if any(entry.knowledge_id == knowledge_id for entry in registry.entries):
        raise KnowledgeError("a knowledge id can never be re-registered")
    purposes = value["purposes"]
    if (
        type(purposes) is not list or not 1 <= len(purposes) <= 3
        or any(item not in PURPOSES for item in purposes)
        or len(set(purposes)) != len(purposes)
    ):
        raise KnowledgeError("purposes are out of bounds")
    provenance_value = value["provenance"]
    if (
        type(provenance_value) is not list
        or not 1 <= len(provenance_value) <= 32
    ):
        # Knowledge without behavior provenance is prompt growth, not memory.
        raise KnowledgeError(
            "an entry requires bounded behavior provenance"
        )
    scope = _text(value["scope"], "scope", 128)
    supersedes = value["supersedes"]
    if supersedes is not None:
        supersedes = _text(supersedes, "supersedes id", 128)
    entries = list(registry.entries)
    conflicting = [
        index for index, entry in enumerate(entries)
        if entry.scope == scope and entry.lifecycle == "active"
    ]
    if conflicting:
        targets = {entries[index].knowledge_id for index in conflicting}
        if supersedes is None or supersedes not in targets:
            # Conflicting authority is never averaged away: coexisting
            # active entries in one scope require explicit supersession.
            raise KnowledgeError(
                "an active entry in this scope must be superseded explicitly"
            )
    if supersedes is not None:
        matched = False
        for index, entry in enumerate(entries):
            if entry.knowledge_id == supersedes:
                if entry.lifecycle != "active":
                    raise KnowledgeError(
                        "only an active entry can be superseded"
                    )
                entries[index] = _reissue_entry(
                    entry, lifecycle="superseded",
                    lifecycle_reason=f"superseded by {knowledge_id}",
                )
                matched = True
        if not matched:
            raise KnowledgeError("the superseded entry does not exist")
    if len(entries) >= 4_096:
        raise KnowledgeError("the knowledge registry is full")
    entries.append(_issue(
        ActiveKnowledge,
        knowledge_id=knowledge_id,
        condition=_text(value["condition"], "condition", 4_096),
        action=_text(value["action"], "action", 4_096),
        exception=_text(value["exception"], "exception", 4_096),
        scope=scope,
        purposes=tuple(purposes),
        candidate=_ref(value["candidate"], {"change_candidate"}, "candidate"),
        approval=_ref(value["approval"], {"action_approval"}, "approval"),
        compatibility=_ref(
            value["compatibility"], {"validation_report"}, "compatibility",
        ),
        provenance=tuple(
            _ref(item, _PROVENANCE_KINDS, "provenance")
            for item in provenance_value
        ),
        effective_from=_stamp(value["effective_from"], "effective from"),
        lifecycle="active",
        lifecycle_reason=None,
        supersedes=supersedes,
        _issuer_token=_ISSUE_TOKEN,
    ))
    return _reissue(registry, entries)


def retrieve_active(registry, value) -> RetrievalResult:
    """Filter scope/purpose/time/lifecycle; report what was excluded."""

    _require_registry(registry)
    if type(value) is not dict or set(value) != {"scope", "purpose", "at"}:
        raise KnowledgeError("expected the exact retrieval query object")
    scope = _text(value["scope"], "query scope", 128)
    purpose = value["purpose"]
    if purpose not in PURPOSES:
        raise KnowledgeError("unknown retrieval purpose")
    at = _stamp(value["at"], "query time")
    supplied = []
    gaps = []
    for entry in registry.entries:
        if entry.scope != scope:
            continue
        if entry.lifecycle != "active":
            gaps.append((entry.knowledge_id, entry.lifecycle))
            continue
        if purpose not in entry.purposes:
            gaps.append((entry.knowledge_id, "purpose_mismatch"))
            continue
        if at < entry.effective_from:
            # Canonical stamps compare correctly as strings.
            gaps.append((entry.knowledge_id, "not_yet_effective"))
            continue
        supplied.append(entry)
    return _issue(
        RetrievalResult,
        query_scope=scope,
        query_purpose=purpose,
        query_at=at,
        entries=tuple(supplied),
        gaps=tuple(gaps),
    )


def declare_condition_change(registry, scope, reason) -> KnowledgeRegistry:
    """Suspend one scope's active entries until revalidated."""

    _require_registry(registry)
    scope = _text(scope, "scope", 128)
    reason = _text(reason, "condition change reason", 1_024)
    entries = []
    touched = False
    for entry in registry.entries:
        if entry.scope == scope and entry.lifecycle == "active":
            entry = _reissue_entry(
                entry, lifecycle="revalidation_required",
                lifecycle_reason=reason,
            )
            touched = True
        entries.append(entry)
    if not touched:
        raise KnowledgeError("no active entries exist in this scope")
    return _reissue(registry, entries)


def revalidate_knowledge(registry, knowledge_id, evidence) -> KnowledgeRegistry:
    """Reactivate one suspended entry with fresh validation evidence."""

    _require_registry(registry)
    if type(evidence) is not list or not 1 <= len(evidence) <= 32:
        # Past qualification is never a permanent guarantee; reactivation
        # requires fresh evidence.
        raise KnowledgeError("revalidation requires fresh evidence")
    refs = tuple(
        _ref(item, {"validation_report", "comparison_result"}, "revalidation")
        for item in evidence
    )
    entries = []
    touched = False
    for entry in registry.entries:
        if entry.knowledge_id == knowledge_id:
            if entry.lifecycle != "revalidation_required":
                raise KnowledgeError(
                    "only a suspended entry can be revalidated"
                )
            entry = _reissue_entry(
                entry,
                lifecycle="active",
                lifecycle_reason=None,
                provenance=entry.provenance + refs,
            )
            touched = True
        entries.append(entry)
    if not touched:
        raise KnowledgeError("unknown knowledge id")
    return _reissue(registry, entries)


def retire_knowledge(registry, knowledge_id, reason) -> KnowledgeRegistry:
    """Retire one entry explicitly; retirement is preserved, never erased."""

    _require_registry(registry)
    reason = _text(reason, "retirement reason", 1_024)
    entries = []
    touched = False
    for entry in registry.entries:
        if entry.knowledge_id == knowledge_id:
            if entry.lifecycle == "retired":
                raise KnowledgeError("this entry is already retired")
            entry = _reissue_entry(
                entry, lifecycle="retired", lifecycle_reason=reason,
            )
            touched = True
        entries.append(entry)
    if not touched:
        raise KnowledgeError("unknown knowledge id")
    return _reissue(registry, entries)


__all__ = [
    "LIFECYCLES",
    "PURPOSES",
    "ActiveKnowledge",
    "KnowledgeError",
    "KnowledgeRegistry",
    "RetrievalResult",
    "declare_condition_change",
    "is_issued_knowledge",
    "open_knowledge_registry",
    "register_knowledge",
    "retire_knowledge",
    "retrieve_active",
    "revalidate_knowledge",
]
