"""Live design-candidate generation over one untrusted model boundary.

The framework keeps every authority here: it renders the exact bounded prompt from a
framework-issued :class:`DesignGenerationRequest`, sends it through one caller-supplied
``model_turn`` callable, mints the generation-call record itself, and admits the returned
graphs only through :func:`accept_design_candidates`.  The model contributes nothing but
functional graphs — never identities, refs, or acceptance.  A malformed model turn is
terminal; this driver performs no retry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import uuid4

from ..domain.refs import EntityRef, canonical_json
from ..generation_profiles import DesignGenerationPurpose, design_profile_for
from .design import (
    DESIGN_CANDIDATE_SCHEMA_VERSION,
    DesignCandidate,
    DesignGenerationRequest,
    accept_design_candidates,
)

MAX_MODEL_RESPONSE_CHARS = 1_048_576
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)

_OUTPUT_SCHEMA = (
    'Return exactly one JSON object of the form {"candidates": [{"graph": '
    "<functional-graph-object>}, ...]} with between one and the requested number of "
    "candidates. Provide nothing except each candidate's graph: no identifiers, no "
    "references, no commentary, no markdown."
)


class DesignGenerationError(ValueError):
    """Terminal live-generation failure; the model turn cannot be retried here."""


@dataclass(frozen=True, slots=True)
class GenerationCallRecord:
    """The framework-minted durable fact of one exact model generation call."""

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
            or self.purpose != DesignGenerationPurpose.DESIGN_CANDIDATE.value
            or type(self.profile_digest) is not str
            or _SHA256.fullmatch(self.profile_digest) is None
            or type(self.model_id) is not str
            or _MODEL_ID.fullmatch(self.model_id) is None
            or type(self.prompt_sha256) is not str
            or _SHA256.fullmatch(self.prompt_sha256) is None
            or type(self.response_sha256) is not str
            or _SHA256.fullmatch(self.response_sha256) is None
        ):
            raise DesignGenerationError("generation call record is invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "design-generation-call-v1",
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
class DesignGenerationResult:
    candidates: tuple[DesignCandidate, ...]
    call_record: GenerationCallRecord = field(repr=False)


def render_candidate_prompt(request: DesignGenerationRequest) -> tuple[str, str]:
    """Render the deterministic (system, user) prompt pair for one request."""

    if type(request) is not DesignGenerationRequest:
        raise DesignGenerationError("a framework-issued generation request is required")
    profile = design_profile_for(DesignGenerationPurpose.DESIGN_CANDIDATE)
    system = (
        f"{profile.base_instructions}\n{profile.developer_instructions}\n{_OUTPUT_SCHEMA}"
    )
    payload = {
        "generation_request": request.as_dict(),
        "work_model": request.work_target.work_model.as_dict(),
        "design_decisions": [item.as_dict() for item in request.decisions],
        "design_disposition": request.design_disposition,
        "requested_candidate_count": request.requested_candidate_count,
    }
    return system, canonical_json(payload).decode("utf-8")


def _parse_model_graphs(raw: object, maximum: int) -> list[object]:
    if type(raw) is not str or not 1 <= len(raw) <= MAX_MODEL_RESPONSE_CHARS:
        raise DesignGenerationError("model response is not bounded text")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise DesignGenerationError("model response is not valid JSON") from exc
    if type(value) is not dict or set(value) != {"candidates"}:
        raise DesignGenerationError("model response is not the exact candidates object")
    candidates = value["candidates"]
    if type(candidates) is not list or not 1 <= len(candidates) <= maximum:
        raise DesignGenerationError("model candidate list is out of bounds")
    graphs = []
    for item in candidates:
        if type(item) is not dict or set(item) != {"graph"}:
            raise DesignGenerationError(
                "a model candidate may contain exactly one graph and nothing else"
            )
        graphs.append(item["graph"])
    return graphs


def run_candidate_generation(
    request: DesignGenerationRequest,
    *,
    model_turn,
    model_id: str,
    call_id: str | None = None,
) -> DesignGenerationResult:
    """Run one bounded generation call and admit its graphs through the authority."""

    if type(request) is not DesignGenerationRequest:
        raise DesignGenerationError("a framework-issued generation request is required")
    if type(model_id) is not str or _MODEL_ID.fullmatch(model_id) is None:
        raise DesignGenerationError("an exact bounded model identity is required")
    if not callable(model_turn):
        raise DesignGenerationError("a callable model boundary is required")
    system, user = render_candidate_prompt(request)
    try:
        raw = model_turn(system, user)
    except Exception as exc:
        raise DesignGenerationError("the model boundary failed") from exc
    graphs = _parse_model_graphs(raw, request.requested_candidate_count)
    record = GenerationCallRecord(
        call_id=call_id if call_id is not None else str(uuid4()),
        version=1,
        request_ref=request.request_ref,
        purpose=DesignGenerationPurpose.DESIGN_CANDIDATE.value,
        profile_digest=design_profile_for(
            DesignGenerationPurpose.DESIGN_CANDIDATE
        ).digest,
        model_id=model_id,
        prompt_sha256=sha256(
            canonical_json({"system": system, "user": user})
        ).hexdigest(),
        response_sha256=sha256(raw.encode("utf-8")).hexdigest(),
    )
    values = [
        {
            "schema_version": DESIGN_CANDIDATE_SCHEMA_VERSION,
            "candidate_id": str(uuid4()),
            "version": 1,
            "generation_request_ref": request.request_ref.as_dict(),
            "parent_candidate_refs": [],
            "generation_call_refs": [record.call_ref.as_dict()],
            "graph": graph,
        }
        for graph in graphs
    ]
    accepted = accept_design_candidates(request, values)
    return DesignGenerationResult(candidates=tuple(accepted), call_record=record)


__all__ = [
    "MAX_MODEL_RESPONSE_CHARS",
    "DesignGenerationError",
    "DesignGenerationResult",
    "GenerationCallRecord",
    "render_candidate_prompt",
    "run_candidate_generation",
]
