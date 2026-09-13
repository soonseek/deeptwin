"""Bounded supplementation orchestration of the design arc (US2, T036).

`propose_environment` ties generation, criticism and the honest selection
pool together offline: it generates up to the requested candidates through
the untrusted generation boundary, criticizes every accepted candidate
through the live criticism driver, assembles the pool, and — when fewer
than three structurally different passed candidates exist and rounds
remain — runs one bounded supplementation round. Regeneration preserves
every prior candidate, verdict, exclusion and call record; rounds are hard
bounded (1..3); a shortfall ends as the real count with per-candidate
reasons, never as padding; and a criticism-contract violation is a typed
refusal of the whole proposal, never a silently skipped candidate. Two
separate callables keep the generation and criticism boundaries distinct.
The proposal is an issued value, never constructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .design import DesignCandidate, DesignGenerationRequest
from .design_criticism import CandidateVerdict, DesignCriticismError
from .design_criticism_live import CriticismRunResult, run_candidate_criticism
from .design_live import GenerationCallRecord, run_candidate_generation
from .design_review import (
    SELECTION_POOL_SIZE,
    SelectionPool,
    assemble_selection_pool,
)

MAX_SUPPLEMENTATION_ROUNDS = 3
_ISSUE_TOKEN = object()


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


@dataclass(frozen=True, slots=True, init=False)
class EnvironmentProposal:
    """One bounded proposal run: the pool plus everything it came from."""

    pool: SelectionPool
    rounds: int
    candidates: tuple[DesignCandidate, ...]
    verdicts: tuple[CandidateVerdict, ...]
    generation_records: tuple[GenerationCallRecord, ...] = field(repr=False)
    criticism_runs: tuple[CriticismRunResult, ...] = field(repr=False)
    _issuer_token: object = field(repr=False, compare=False)


def propose_environment(
    request: DesignGenerationRequest,
    registry,
    *,
    generation_turn,
    criticism_turn,
    model_id: str,
    max_rounds: int = MAX_SUPPLEMENTATION_ROUNDS,
) -> EnvironmentProposal:
    """Generate, criticize and pool candidates with bounded supplementation."""

    if (
        type(max_rounds) is not int
        or not 1 <= max_rounds <= MAX_SUPPLEMENTATION_ROUNDS
    ):
        raise DesignCriticismError(
            "supplementation rounds are bounded between one and three"
        )
    candidates: list[DesignCandidate] = []
    verdicts: list[CandidateVerdict] = []
    generation_records: list[GenerationCallRecord] = []
    criticism_runs: list[CriticismRunResult] = []
    pool = None
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        generation = run_candidate_generation(
            request, model_turn=generation_turn, model_id=model_id,
        )
        generation_records.append(generation.call_record)
        for candidate in generation.candidates:
            run = run_candidate_criticism(
                candidate, request, registry,
                model_turn=criticism_turn, model_id=model_id,
            )
            criticism_runs.append(run)
            candidates.append(candidate)
            verdicts.append(run.verdict)
        # The pool is re-assembled over the CUMULATIVE entries: regeneration
        # preserves every prior candidate, verdict and exclusion.
        pool = assemble_selection_pool(
            request, list(zip(candidates, verdicts)),
        )
        if len(pool.presented) >= SELECTION_POOL_SIZE:
            break
    return _issue(
        EnvironmentProposal,
        pool=pool,
        rounds=rounds,
        candidates=tuple(candidates),
        verdicts=tuple(verdicts),
        generation_records=tuple(generation_records),
        criticism_runs=tuple(criticism_runs),
        _issuer_token=_ISSUE_TOKEN,
    )


__all__ = [
    "MAX_SUPPLEMENTATION_ROUNDS",
    "EnvironmentProposal",
    "propose_environment",
]
