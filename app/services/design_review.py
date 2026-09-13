"""Selection pool and derived design versions (US2, T036 first slice).

The pool presents at most three structurally different passed candidates
(experience.md: 통과한 구조적으로 다른 기본 3안). A rejected verdict — a
mandatory defect — never enters the pool regardless of any other property;
insufficient evidence is not a pass; a structural duplicate of an already
pooled candidate is excluded by its projected shape, never by its name; and
when fewer than three candidates qualify the pool states the real count and
every exclusion's reason instead of padding. Selecting, editing or merging
creates a NEW immutable design version bound to its exact parents with
mandatory re-review — the original candidates' scores, verdicts and
approvals never inherit (FR-008). Values are issued, never constructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from ..domain.refs import EntityRef, canonical_json
from ..runtime.graph import structural_diversity_projection
from .design import DesignCandidate, is_accepted_candidate
from .design_criticism import CandidateVerdict

SELECTION_POOL_SIZE = 3
VERDICT_STATUSES = frozenset({"passed", "rejected", "insufficient_evidence"})
DERIVATION_ACTIONS = frozenset({"select", "edit", "merge"})
_ISSUE_TOKEN = object()


class DesignReviewError(ValueError):
    """A selection pool input or design derivation is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


@dataclass(frozen=True, slots=True, init=False)
class SelectionPool:
    """What is actually presented, and why everything else is not."""

    presented: tuple[DesignCandidate, ...]
    # (candidate_id, reason) for every entry NOT presented
    excluded: tuple[tuple[str, str], ...]
    passed_count: int
    supplementation_available: bool


def _signature(candidate: DesignCandidate) -> str:
    return sha256(
        canonical_json(structural_diversity_projection(candidate.graph))
    ).hexdigest()


def assemble_selection_pool(entries) -> SelectionPool:
    """Assemble one honest pool from (candidate, verdict) pairs."""

    if type(entries) is not list or not 1 <= len(entries) <= 64:
        raise DesignReviewError("expected a bounded candidate/verdict list")
    seen_candidates: set[tuple[str, int]] = set()
    presented: list[DesignCandidate] = []
    excluded: list[tuple[str, str]] = []
    pooled_signatures: set[str] = set()
    passed_count = 0
    for item in entries:
        if type(item) is not tuple or len(item) != 2:
            raise DesignReviewError("expected (candidate, verdict) pairs")
        candidate, verdict = item
        if not is_accepted_candidate(candidate):
            raise DesignReviewError(
                "only an accepted design candidate can be pooled"
            )
        if type(verdict) is not CandidateVerdict:
            raise DesignReviewError("a criticism verdict is required")
        if (
            verdict.candidate_id != candidate.candidate_id
            or verdict.candidate_version != str(candidate.version)
        ):
            raise DesignReviewError(
                "the verdict does not bind this exact candidate"
            )
        if verdict.status not in VERDICT_STATUSES:
            raise DesignReviewError("unknown verdict status")
        key = (candidate.candidate_id, candidate.version)
        if key in seen_candidates:
            raise DesignReviewError(
                "a candidate can never appear twice in one pool"
            )
        seen_candidates.add(key)
        if verdict.status != "passed":
            # A mandatory defect or missing evidence is stated, never
            # hidden behind aggregation or padding.
            reasons = ",".join(verdict.reasons) or "no stated reasons"
            excluded.append(
                (candidate.candidate_id, f"{verdict.status}:{reasons}"),
            )
            continue
        passed_count += 1
        signature = _signature(candidate)
        if signature in pooled_signatures:
            excluded.append((candidate.candidate_id, "structural_duplicate"))
            continue
        if len(presented) >= SELECTION_POOL_SIZE:
            excluded.append((candidate.candidate_id, "pool_full"))
            continue
        pooled_signatures.add(signature)
        presented.append(candidate)
    return _issue(
        SelectionPool,
        presented=tuple(presented),
        excluded=tuple(excluded),
        passed_count=passed_count,
        supplementation_available=len(presented) < SELECTION_POOL_SIZE,
    )


@dataclass(frozen=True, slots=True, init=False)
class DerivedDesignVersion:
    """One select/edit/merge act: a new version, never an inheritance."""

    action: str
    parent_refs: tuple[EntityRef, ...]
    instruction: str | None
    re_review_required: bool
    inherited_verdict: None
    _issuer_token: object = field(repr=False, compare=False)


def derive_design_version(action, parents, *, instruction=None):
    """Create one derived design version; re-review is always mandatory."""

    if action not in DERIVATION_ACTIONS:
        raise DesignReviewError("unknown design derivation action")
    if type(parents) is not list or not 1 <= len(parents) <= 8:
        raise DesignReviewError("expected a bounded parent candidate list")
    for parent in parents:
        if not is_accepted_candidate(parent):
            raise DesignReviewError(
                "only accepted candidates can parent a derived version"
            )
    if action == "merge" and len(parents) < 2:
        raise DesignReviewError("a merge requires at least two parents")
    if action in {"select", "edit"} and len(parents) != 1:
        raise DesignReviewError(f"a {action} takes exactly one parent")
    if action == "edit":
        if (
            type(instruction) is not str
            or not 1 <= len(instruction.encode("utf-8")) <= 4_096
        ):
            raise DesignReviewError("an edit states its instruction")
    elif instruction is not None:
        raise DesignReviewError("only an edit carries an instruction")
    return _issue(
        DerivedDesignVersion,
        action=action,
        parent_refs=tuple(parent.graph_ref for parent in parents),
        instruction=instruction,
        # The original candidates' scores and approvals never inherit; a
        # derived graph is unreviewed until its own mandatory re-review.
        re_review_required=True,
        inherited_verdict=None,
        _issuer_token=_ISSUE_TOKEN,
    )


__all__ = [
    "DERIVATION_ACTIONS",
    "SELECTION_POOL_SIZE",
    "VERDICT_STATUSES",
    "DerivedDesignVersion",
    "DesignReviewError",
    "SelectionPool",
    "assemble_selection_pool",
    "derive_design_version",
]
