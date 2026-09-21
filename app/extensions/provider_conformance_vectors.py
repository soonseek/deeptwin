"""Code-owned public provider conformance vectors and literal expected results.

This module intentionally does not import the provider transformation implementation.  The
expected values are an independent application-level oracle over four fixed public inputs.
"""

from dataclasses import dataclass
from hashlib import sha256

from ..domain.refs import canonical_json


SUITE_VERSION = "private-provider-conformance-v1"
REQUESTER_VERSION = "private-provider-requester-v1"
COMPARATOR_VERSION = "private-provider-literal-oracle-v1"
MODEL = "claude-conformance-fixture"


@dataclass(frozen=True, slots=True)
class FixedVector:
    vector_id: str
    operation: str
    plan_bytes: bytes
    input_bytes: tuple[bytes, ...]
    supplied_bodies: tuple[bytes, ...]
    expected_projections: tuple[bytes, ...]
    expected_result_bytes: bytes


def _event(name, fields):
    return (b"event: " + name.encode("ascii") + b"\ndata: "
            + canonical_json({"type": name, **fields}) + b"\n\n")


def _text_body(stop):
    return b"".join((
        _event("message_start", {"message": {"type": "message", "role": "assistant",
            "model": MODEL, "content": [], "usage": {"input_tokens": 3, "output_tokens": 0}}}),
        _event("content_block_start", {"index": 0,
            "content_block": {"type": "text", "text": ""}}),
        _event("content_block_delta", {"index": 0,
            "delta": {"type": "text_delta", "text": "answer"}}),
        _event("content_block_stop", {"index": 0}),
        _event("message_delta", {"delta": {"stop_reason": stop},
            "usage": {"output_tokens": 4}}),
        _event("message_stop", {}),
    ))


def _text_vector(vector_id, stop, state, reason, blocks):
    input_bytes = b"hello conformance\n"
    plan = canonical_json({"profile": "claude-text-transform-v1", "model_id": MODEL,
        "max_output_tokens": 32, "messages": [{"role": "user", "input_ordinals": [0]}],
        "inputs": [{"size": 18, "sha256": sha256(input_bytes).hexdigest()}]})
    request_body = canonical_json({"model": MODEL, "max_tokens": 32, "stream": True,
        "messages": [{"role": "user", "content": [{"type": "text",
            "text": "hello conformance\n"}]}]})
    projection = canonical_json({"step": 1, "endpoint": "messages", "after_id": None,
        "body_sha256": sha256(request_body).hexdigest()})
    result = canonical_json({"schema": "provider-transform-result-v1", "operation": "text",
        "state": state, "reason": reason, "input_digest": sha256(plan).hexdigest(),
        "observation": {"requested_model": MODEL, "observed_model": MODEL,
            "text_blocks": blocks, "stop_reason": stop,
            "usage_observed": {"input_tokens": 3, "output_tokens": 4,
                "cache_read_input_tokens": None, "cache_creation_input_tokens": None},
            "usage_complete": None}})
    return FixedVector(vector_id, "text", plan, (input_bytes,), (_text_body(stop),),
                       (projection,), result)


def _page(model_id, has_more, extra):
    return canonical_json({"data": [{"type": "model", "id": model_id,
        "display_name": "Fixture", "created_at": "2026-01-01T00:00:00Z", **extra}],
        "has_more": has_more, "first_id": model_id, "last_id": model_id})


def _catalog_vector(vector_id, pages, after_ids, *, complete):
    plan = canonical_json({"profile": "claude-text-transform-v1", "limit": 1000})
    projections = tuple(canonical_json({"step": index, "endpoint": "models",
        "after_id": after_id, "body_sha256": None})
        for index, after_id in enumerate(after_ids, 1))
    models = ([{"id": model_id, "display_name": "Fixture",
        "created_at": "2026-01-01T00:00:00Z", "max_input_tokens": None,
        "max_tokens": None, "capabilities": None} for model_id in ("one", "two")]
        if complete else [])
    result = canonical_json({"schema": "provider-transform-result-v1", "operation": "catalog",
        "state": "parsed_complete" if complete else "invalid_response",
        "reason": "complete" if complete else "catalog_incomplete",
        "input_digest": sha256(plan).hexdigest(),
        "observation": {"page_digests": [sha256(page).hexdigest() for page in pages],
            "complete": complete, "models": models}})
    return FixedVector(vector_id, "catalog", plan, (), tuple(pages), projections, result)


_PAGE_ONE = _page("one", True, {})
_PAGE_TWO = _page("two", False, {})
_NEGATIVE = _page("one", False, {"capabilities": {"unexpected": -1}})
_VECTORS = (
    _text_vector("text-basic-v1", "end_turn", "parsed_complete", "complete", ["answer"]),
    _text_vector("text-refusal-v1", "refusal", "non_success", "refusal", []),
    _catalog_vector("catalog-two-pages-v1", (_PAGE_ONE, _PAGE_TWO), (None, "one"), complete=True),
    _catalog_vector("catalog-negative-capability-v1", (_NEGATIVE,), (None,), complete=False),
)


def fixed_vectors():
    return tuple(list(_VECTORS))


def vector_manifest():
    return canonical_json({"schema_version": "provider-conformance-vectors-v1", "vectors": [
        {"vector_id": vector.vector_id, "operation": vector.operation,
         "plan_sha256": sha256(vector.plan_bytes).hexdigest(),
         "input_sha256s": [sha256(value).hexdigest() for value in vector.input_bytes],
         "supplied_body_sha256s": [sha256(value).hexdigest() for value in vector.supplied_bodies],
         "projection_sha256s": [sha256(value).hexdigest() for value in vector.expected_projections],
         "expected_result_sha256": sha256(vector.expected_result_bytes).hexdigest()}
        for vector in _VECTORS]})


SUITE_SHA256 = sha256(vector_manifest()).hexdigest()
