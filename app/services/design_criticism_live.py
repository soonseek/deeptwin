"""Live-driven candidate criticism over the untrusted model boundary.

Mirror of :mod:`design_live` for the criticism side: the four stages
(review, counterexample proposal, validity, candidate response) run through
one ``model_turn(system, user)`` callable. Each stage's system prompt is the
code-owned instruction profile for that purpose plus the stage's exact
output schema; the user payload is the prepared contract input, byte for
byte. Raw responses are admitted only through ``parse_response`` — a
malformed, oversized or wrongly-bound response is a typed refusal, never a
verdict. The driver mints one framework-owned :class:`CriticismCallRecord`
per actual model call (purpose, profile digest, prompt/response hashes,
request binding), spends no call a stage outcome makes unnecessary (a
rejected validity skips the response stage; an abstaining proposal ends the
chain), and folds the outcome through ``fold_candidate_criticism``. No
provider is bound here: the callable is the boundary, and live transport
authorization stays a separate user-gated concern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import uuid4

from ..critic_contract import (
    InputContractError,
    PreparedInput,
    ResponseContractError,
    parse_response,
)
from ..domain.refs import EntityRef, canonical_json
from ..generation_profiles import GenerationPurpose, profile_for
from .design import DesignCandidate, DesignGenerationRequest
from .design_criticism import (
    CandidateVerdict,
    DesignCriticismError,
    fold_candidate_criticism,
    prepare_candidate_proposal,
    prepare_candidate_response,
    prepare_candidate_review,
    prepare_candidate_validity,
)

CRITICISM_PURPOSES = frozenset({
    GenerationPurpose.REVIEW.value,
    GenerationPurpose.COUNTEREXAMPLE_PROPOSAL.value,
    GenerationPurpose.COUNTEREXAMPLE_VALIDITY.value,
    GenerationPurpose.CANDIDATE_RESPONSE.value,
})
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class CriticismCallRecord:
    """The framework-minted durable fact of one exact criticism model call."""

    call_id: str
    version: int
    request_ref: EntityRef
    purpose: str
    profile_digest: str
    model_id: str
    prompt_sha256: str
    response_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.call_id) is not str
            or _UUID.fullmatch(self.call_id) is None
            or self.version != 1
            or type(self.request_ref) is not EntityRef
            or self.purpose not in CRITICISM_PURPOSES
            or type(self.profile_digest) is not str
            or _SHA256.fullmatch(self.profile_digest) is None
            or type(self.model_id) is not str
            or _MODEL_ID.fullmatch(self.model_id) is None
            or type(self.prompt_sha256) is not str
            or _SHA256.fullmatch(self.prompt_sha256) is None
            or type(self.response_sha256) is not str
            or _SHA256.fullmatch(self.response_sha256) is None
        ):
            raise DesignCriticismError("criticism call record is invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "design-criticism-call-v1",
            "call_id": self.call_id,
            "version": self.version,
            "request_ref": self.request_ref.as_dict(),
            "purpose": self.purpose,
            "profile_digest": self.profile_digest,
            "model_id": self.model_id,
            "prompt_sha256": self.prompt_sha256,
            "response_sha256": self.response_sha256,
        }

    @property
    def call_ref(self) -> EntityRef:
        return EntityRef(
            "decision_record",
            self.call_id,
            self.version,
            sha256(canonical_json(self.as_dict())).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class CriticismRunResult:
    """One candidate's driven criticism: verdict, evidence, call records."""

    verdict: CandidateVerdict
    review: dict = field(repr=False)
    chains: tuple[dict, ...] = field(repr=False)
    call_records: tuple[CriticismCallRecord, ...] = field(repr=False)


def render_criticism_prompt(prepared: PreparedInput) -> tuple[str, str]:
    """Render the deterministic (system, user) prompt pair for one stage."""

    if type(prepared) is not PreparedInput:
        raise DesignCriticismError("a prepared criticism input is required")
    profile = profile_for(prepared.purpose)
    system = (
        f"{profile.base_instructions}\n{profile.developer_instructions}\n"
        f"{prepared.schema_json}"
    )
    return system, prepared.prompt


def _response_bytes(raw: object) -> bytes:
    if type(raw) is not str:
        raise DesignCriticismError("the model boundary must return text")
    return raw.encode("utf-8")


def run_candidate_criticism(
    candidate: DesignCandidate,
    request: DesignGenerationRequest,
    registry,
    *,
    model_turn,
    model_id: str,
) -> CriticismRunResult:
    """Drive the four criticism stages and fold one selectability verdict."""

    if type(request) is not DesignGenerationRequest:
        raise DesignCriticismError(
            "a framework-issued generation request is required"
        )
    if type(model_id) is not str or _MODEL_ID.fullmatch(model_id) is None:
        raise DesignCriticismError("an exact bounded model identity is required")
    if not callable(model_turn):
        raise DesignCriticismError("a callable model boundary is required")
    records: list[CriticismCallRecord] = []

    def stage(prepared: PreparedInput) -> dict:
        system, user = render_criticism_prompt(prepared)
        try:
            raw = model_turn(system, user)
        except Exception as exc:
            raise DesignCriticismError(
                f"the model boundary failed during {prepared.purpose.value}"
            ) from exc
        try:
            result = parse_response(prepared, raw)
        except (ResponseContractError, InputContractError) as exc:
            raise DesignCriticismError(
                f"the {prepared.purpose.value} response violates the contract"
            ) from exc
        profile = profile_for(prepared.purpose)
        records.append(CriticismCallRecord(
            call_id=str(uuid4()),
            version=1,
            request_ref=request.request_ref,
            purpose=prepared.purpose.value,
            profile_digest=profile.digest,
            model_id=model_id,
            prompt_sha256=sha256(
                canonical_json({"system": system, "user": user})
            ).hexdigest(),
            response_sha256=sha256(_response_bytes(raw)).hexdigest(),
        ))
        return result

    review = stage(prepare_candidate_review(candidate, request))
    proposal = stage(prepare_candidate_proposal(candidate, request, registry))
    chains: list[dict] = []
    for counterexample in proposal["counterexamples"]:
        validity = stage(
            prepare_candidate_validity(candidate, request, counterexample),
        )
        response = None
        if validity["status"] == "valid":
            response = stage(prepare_candidate_response(
                candidate, request, counterexample, validity,
            ))
        # rejected and unresolved validities spend no response call; the
        # fold accounts for them (skip and insufficiency respectively).
        chains.append({
            "counterexample": counterexample,
            "validity": validity,
            "response": response,
        })
    verdict = fold_candidate_criticism(candidate, request, review, chains)
    return CriticismRunResult(
        verdict=verdict,
        review=review,
        chains=tuple(chains),
        call_records=tuple(records),
    )


__all__ = [
    "CRITICISM_PURPOSES",
    "CriticismCallRecord",
    "CriticismRunResult",
    "render_criticism_prompt",
    "run_candidate_criticism",
]
