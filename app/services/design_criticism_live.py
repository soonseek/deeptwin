"""Live-driven candidate criticism over the untrusted model boundary.

Mirror of :mod:`design_live` for the criticism side: the four stages
(review, counterexample proposal, validity, candidate response) run through
one ``model_turn(system, user)`` callable. Each stage's system prompt is the
code-owned instruction profile for that purpose plus the stage's exact
output schema; the user payload is the prepared contract input, byte for
byte. Raw responses are admitted only through ``parse_response`` — a
malformed, oversized or wrongly-bound response is a typed refusal, never a
verdict. A completed answer the contract refuses raises
:class:`CriticismStageRefused`, which carries that answer (bounded to
``MAX_REFUSED_RESPONSE_BYTES``) and the exact rule it broke
(:func:`diagnose_contract_violation`) so the caller can persist them. The driver mints one framework-owned :class:`CriticismCallRecord`
per actual model call (purpose, profile digest, prompt/response hashes,
request binding), spends no call a stage outcome makes unnecessary (a
rejected validity skips the response stage; an abstaining proposal ends the
chain), and folds the outcome through ``fold_candidate_criticism``. No
provider is bound here: the callable is the boundary, and live transport
authorization stays a separate user-gated concern.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import uuid4

from .. import critic_contract as _contract
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
_ISSUE_TOKEN = object()


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


@dataclass(frozen=True, slots=True, init=False)
class CriticismCallRecord:
    """The framework-minted durable fact of one exact criticism model call.

    The driver is the only issuer. ``prompt_sha256`` is provable (the prompt
    re-renders deterministically); ``response_sha256`` is the boundary's
    recorded attestation — the raw response is not retained beyond it.
    """

    call_id: str
    version: int
    request_ref: EntityRef
    purpose: str
    profile_digest: str
    model_id: str
    prompt_sha256: str
    response_sha256: str
    _issuer_token: object = field(repr=False, compare=False)

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


@dataclass(frozen=True, slots=True, init=False)
class CriticismRunResult:
    """One candidate's driven criticism: verdict, evidence, call records."""

    verdict: CandidateVerdict
    review: dict = field(repr=False)
    chains: tuple[dict, ...] = field(repr=False)
    call_records: tuple[CriticismCallRecord, ...] = field(repr=False)
    # The contract-validated proposal outcome: whether the proposal abstained,
    # and per lens rule whether it contributed (with the exact counterexample
    # ids), was excluded or abstained, and why.
    proposal_status: str
    lens_use: tuple[dict, ...]
    _issuer_token: object = field(repr=False, compare=False)


def is_issued_call_record(value: object) -> bool:
    """True only for a record minted by the criticism driver."""

    return (
        type(value) is CriticismCallRecord
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def is_issued_criticism_run(value: object) -> bool:
    """True only for a run produced by run_candidate_criticism."""

    return (
        type(value) is CriticismRunResult
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


# The contract admits a citation only when it names a location the input actually shows,
# and a response only in the transitions its validity allows; a model cannot guess these
# rules, so the prompt states them (both were the causes of the first live calibration's
# contract failures).
_CITATION_RULE = (
    "Cite evidence only as {document_id, version, location} of an original document, the "
    "criteria document or the candidate document; never cite a counterexample or validity "
    "document, which are claims under test, not evidence. For an original, location is exactly "
    "one of its sections' location values. For the criteria or the candidate, location is a JSON "
    "Pointer (RFC 6901) to an existing value inside that document as given, for example "
    "/roles/0/responsibility or /items/2; never a prose description or a path of another form. "
    "An original whose availability is not text has no sections and is never cited; cite the "
    "text document that states the fact instead. In a candidate response, when the given "
    "validity status is not valid, your status must be unresolved."
    # T038 live diagnosis (2026-09-26): the critic's review cited the criteria document
    # under the design decision's id (the prefix of the criterion ids) and wrapped its JSON
    # in a markdown fence; both are refused by the contract, so the prompt states them.
    " A citation's document_id and version are exactly the id and version fields of the cited "
    "document as given in the input: the criteria document's id is its own id field (for "
    "example review:…), never a criterion id or any part of one, and the candidate's is the "
    "candidate document's id field."
)
_OUTPUT_RULE = (
    "Answer with the JSON object alone: the first character of the answer is { and the last is "
    "}. No markdown code fence (no ```json), no heading and no text before or after it."
)


# A refused stage keeps the model's own answer (bounded) and the exact rule it broke, so
# a contract failure can be diagnosed afterwards (the first live design-arc review was
# refused and, with only digests kept, its cause could not be established).
MAX_REFUSED_RESPONSE_BYTES = 64_000
_MAX_VIOLATION_CHARS = 2_000


class CriticismStageRefused(DesignCriticismError):
    """A completed model call whose answer the critic contract refused.

    The message stays the closed one (``the <purpose> response violates the
    contract``); the exact violation and the bounded raw answer ride along for the
    caller to persist. Nothing here is, or becomes, a verdict."""

    def __init__(self, message, *, purpose, violation, raw_text, raw_bytes, truncated,
                 response_sha256, prompt_sha256, profile_digest, model_id, completed_calls):
        super().__init__(message)
        self.purpose = purpose
        self.violation = violation
        self.raw_text = raw_text
        self.raw_bytes = raw_bytes
        self.truncated = truncated
        self.response_sha256 = response_sha256
        self.prompt_sha256 = prompt_sha256
        self.profile_digest = profile_digest
        self.model_id = model_id
        self.completed_calls = completed_calls

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "design-criticism-refusal-v1",
            "purpose": self.purpose,
            "violation": self.violation,
            "model_id": self.model_id,
            "profile_digest": self.profile_digest,
            "prompt_sha256": self.prompt_sha256,
            "response_sha256": self.response_sha256,
            "response_bytes": self.raw_bytes,
            "response_truncated": self.truncated,
            "response_text": self.raw_text,
            "completed_calls_before": self.completed_calls,
        }


def _bounded_text(raw: str) -> tuple[str, int, bool]:
    data = raw.encode("utf-8", "replace")
    if len(data) <= MAX_REFUSED_RESPONSE_BYTES:
        return data.decode("utf-8"), len(data), False
    return data[:MAX_REFUSED_RESPONSE_BYTES].decode("utf-8", "ignore"), len(data), True


def _pydantic_reason(error) -> str:
    items = []
    for item in error.errors()[:8]:
        location = "/".join(str(part) for part in item.get("loc", ())) or "(root)"
        items.append(f"{location}: {item.get('msg', 'invalid')}")
    more = error.error_count() - len(items)
    return "schema: " + "; ".join(items) + (f"; and {more} more" if more > 0 else "")


def _uncited(items, references, path) -> str | None:
    for index, item in enumerate(items):
        if (item["document_id"], item["version"], item["location"]) not in references:
            return (f"citation is not visible: {path}/{index} names document "
                    f"{item['document_id']!r} version {item['version']!r} location "
                    f"{item['location']!r}")
    return None


def _diagnose(prepared, visible, raw) -> str | None:
    from pydantic import ValidationError

    purpose = prepared.purpose
    try:
        value = _contract._load(raw, _contract.RESPONSE_MAX_BYTES)
    except json.JSONDecodeError as error:
        return f"json: {error.msg} at line {error.lineno} column {error.colno}"
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        return f"json: {error}"
    try:
        result = _contract.OUTPUT_MODELS[purpose].model_validate(value).model_dump(mode="json")
    except ValidationError as error:
        return _pydantic_reason(error)
    try:
        _contract._candidate_binding(result, visible)
        references = _contract._registry(visible)
        if purpose is GenerationPurpose.REVIEW:
            ids = [finding["criterion_id"] for finding in result["findings"]]
            _contract._unique(ids, "finding criterion")
            expected = {item["id"] for item in visible["criteria"]["items"]}
            if set(ids) != expected:
                return (f"rule: finding coverage mismatch: missing {sorted(expected - set(ids))}, "
                        f"unknown {sorted(set(ids) - expected)}")
            for index, finding in enumerate(result["findings"]):
                reason = _uncited(finding["evidence"], references, f"/findings/{index}/evidence")
                if reason:
                    return reason
                if finding["status"] == "unresolved" and not finding["uncertainties"]:
                    return f"rule: unresolved result needs uncertainty (/findings/{index})"
        elif purpose is GenerationPurpose.COUNTEREXAMPLE_PROPOSAL:
            for index, example in enumerate(result["counterexamples"]):
                reason = _uncited(example["citations"], references, f"/counterexamples/{index}/citations")
                if reason:
                    return reason
            for index, use in enumerate(result["lens_use"]):
                reason = _uncited(use["evidence"], references, f"/lens_use/{index}/evidence")
                if reason:
                    return reason
            _contract._proposal(result, visible, references)
        else:
            _contract._counterexample_binding(result, visible)
            reason = _uncited(result["evidence"], references, "/evidence")
            if reason:
                return reason
            _contract._unresolved(result)
            if purpose is GenerationPurpose.CANDIDATE_RESPONSE:
                status = visible["validity"]["status"]
                _contract._require(result["validity_status"] == status, "validity status mismatch")
                _contract._require(status == "valid" or result["status"] == "unresolved",
                                   "invalid candidate-response transition")
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        return f"rule: {error}"
    return None


def diagnose_contract_violation(prepared: PreparedInput, raw: object) -> str | None:
    """The exact rule a refused answer broke, or None when the contract admits it.

    Diagnostic only: it replays the contract's own checks in the contract's order
    (the contract closes every reason to one message on purpose) and never admits
    anything — admission stays ``parse_response``. If the two ever disagree the
    disagreement itself is reported, never resolved in the answer's favour."""

    if type(prepared) is not PreparedInput:
        raise DesignCriticismError("a prepared criticism input is required")
    try:
        visible = _contract._prepared_visible(prepared)
    except InputContractError:
        return "prepared input: the prepared input failed its own integrity check"
    reason = _diagnose(prepared, visible, raw)
    try:
        parse_response(prepared, raw)
        admitted = True
    except ResponseContractError:
        admitted = False
    if reason is None and not admitted:
        return "unclassified: the contract refused an answer this diagnosis did not"
    if reason is not None and admitted:
        return f"inconsistent: the contract admits this answer; the diagnosis said {reason}"[
            :_MAX_VIOLATION_CHARS]
    return None if reason is None else reason[:_MAX_VIOLATION_CHARS]


def render_criticism_prompt(prepared: PreparedInput) -> tuple[str, str]:
    """Render the deterministic (system, user) prompt pair for one stage."""

    if type(prepared) is not PreparedInput:
        raise DesignCriticismError("a prepared criticism input is required")
    profile = profile_for(prepared.purpose)
    system = (
        f"{profile.base_instructions}\n{profile.developer_instructions}\n"
        f"{_CITATION_RULE}\n{_OUTPUT_RULE}\n{prepared.schema_json}"
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
        profile = profile_for(prepared.purpose)
        try:
            result = parse_response(prepared, raw)
        except (ResponseContractError, InputContractError) as exc:
            message = f"the {prepared.purpose.value} response violates the contract"
            if type(raw) is not str:
                raise DesignCriticismError(message) from exc
            # the answer and the exact rule it broke are kept first, before anything
            # else can fail; only model output is kept (never the prompt or a key)
            text, size, truncated = _bounded_text(raw)
            raise CriticismStageRefused(
                message,
                purpose=prepared.purpose.value,
                violation=diagnose_contract_violation(prepared, raw)
                or "unclassified: the contract refused the answer",
                raw_text=text, raw_bytes=size, truncated=truncated,
                response_sha256=sha256(raw.encode("utf-8", "surrogatepass")).hexdigest(),
                prompt_sha256=sha256(canonical_json({"system": system, "user": user})).hexdigest(),
                profile_digest=profile.digest, model_id=model_id, completed_calls=len(records),
            ) from exc
        record = _issue(
            CriticismCallRecord,
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
            _issuer_token=_ISSUE_TOKEN,
        )
        if (
            _UUID.fullmatch(record.call_id) is None
            or record.purpose not in CRITICISM_PURPOSES
            or _SHA256.fullmatch(record.profile_digest) is None
        ):  # pragma: no cover - driver-internal consistency
            raise DesignCriticismError("criticism call record is invalid")
        records.append(record)
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
    return _issue(
        CriticismRunResult,
        verdict=verdict,
        review=review,
        chains=tuple(chains),
        call_records=tuple(records),
        proposal_status=proposal["status"],
        lens_use=tuple(
            {
                "rule_id": use["rule_id"],
                "rule_version": use["rule_version"],
                "status": use["status"],
                "reason": use["reason"],
                "counterexample_ids": tuple(use["counterexample_ids"]),
            }
            for use in proposal["lens_use"]
        ),
        _issuer_token=_ISSUE_TOKEN,
    )


__all__ = [
    "CRITICISM_PURPOSES",
    "MAX_REFUSED_RESPONSE_BYTES",
    "CriticismStageRefused",
    "diagnose_contract_violation",
    "CriticismCallRecord",
    "CriticismRunResult",
    "is_issued_call_record",
    "is_issued_criticism_run",
    "render_criticism_prompt",
    "run_candidate_criticism",
]
