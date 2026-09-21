from hashlib import sha256

from app.domain.refs import canonical_json as J, parse_canonical
from app.extensions.provider_conformance_vectors import SUITE_SHA256, fixed_vectors, vector_manifest


MODEL = "claude-conformance-fixture"


def _event(name, fields):
    return b"event: " + name.encode("ascii") + b"\ndata: " + J({"type": name, **fields}) + b"\n\n"


def _text_body(stop):
    return b"".join((
        _event("message_start", {"message": {"type": "message", "role": "assistant",
            "model": MODEL, "content": [], "usage": {"input_tokens": 3, "output_tokens": 0}}}),
        _event("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        _event("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "answer"}}),
        _event("content_block_stop", {"index": 0}),
        _event("message_delta", {"delta": {"stop_reason": stop}, "usage": {"output_tokens": 4}}),
        _event("message_stop", {}),
    ))


def test_text_oracle_is_exact_public_literal():
    vector = fixed_vectors()[0]
    raw = b"hello conformance\n"
    plan = J({"profile": "claude-text-transform-v1", "model_id": MODEL,
        "max_output_tokens": 32, "messages": [{"role": "user", "input_ordinals": [0]}],
        "inputs": [{"size": 18, "sha256": sha256(raw).hexdigest()}]})
    projection = J({"model": MODEL, "max_tokens": 32, "stream": True,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hello conformance\n"}]}]})
    observation = {"requested_model": MODEL, "observed_model": MODEL,
        "text_blocks": ["answer"], "stop_reason": "end_turn",
        "usage_observed": {"input_tokens": 3, "output_tokens": 4,
            "cache_read_input_tokens": None, "cache_creation_input_tokens": None},
        "usage_complete": None}
    result = J({"schema": "provider-transform-result-v1", "operation": "text",
        "state": "parsed_complete", "reason": "complete", "input_digest": sha256(plan).hexdigest(),
        "observation": observation})
    assert vector.vector_id == "text-basic-v1"
    assert vector.operation == "text"
    assert vector.plan_bytes == plan
    assert vector.input_bytes == (raw,)
    assert vector.supplied_bodies == (_text_body("end_turn"),)
    assert vector.expected_projections == (J({"step": 1, "endpoint": "messages",
        "after_id": None, "body_sha256": sha256(projection).hexdigest()}),)
    assert vector.expected_result_bytes == result


def test_refusal_catalog_and_negative_capability_literals_are_independent():
    vectors = fixed_vectors()
    assert tuple(v.vector_id for v in vectors) == (
        "text-basic-v1", "text-refusal-v1", "catalog-two-pages-v1",
        "catalog-negative-capability-v1")
    refusal = parse_canonical(vectors[1].expected_result_bytes)
    assert vectors[1].supplied_bodies == (_text_body("refusal"),)
    assert refusal["state"] == "non_success" and refusal["reason"] == "refusal"
    assert refusal["observation"]["text_blocks"] == []

    page1 = J({"data": [{"type": "model", "id": "one", "display_name": "Fixture",
        "created_at": "2026-01-01T00:00:00Z"}], "has_more": True,
        "first_id": "one", "last_id": "one"})
    page2 = J({"data": [{"type": "model", "id": "two", "display_name": "Fixture",
        "created_at": "2026-01-01T00:00:00Z"}], "has_more": False,
        "first_id": "two", "last_id": "two"})
    assert vectors[2].supplied_bodies == (page1, page2)
    catalog = parse_canonical(vectors[2].expected_result_bytes)
    assert catalog["observation"]["page_digests"] == [sha256(page1).hexdigest(), sha256(page2).hexdigest()]
    assert [item["id"] for item in catalog["observation"]["models"]] == ["one", "two"]

    negative = J({"data": [{"type": "model", "id": "one", "display_name": "Fixture",
        "created_at": "2026-01-01T00:00:00Z", "capabilities": {"unexpected": -1}}],
        "has_more": False, "first_id": "one", "last_id": "one"})
    assert vectors[3].supplied_bodies == (negative,)
    invalid = parse_canonical(vectors[3].expected_result_bytes)
    assert invalid["state"] == "invalid_response" and invalid["reason"] == "catalog_incomplete"
    assert invalid["observation"] == {"page_digests": [sha256(negative).hexdigest()],
        "complete": False, "models": []}


def test_manifest_binds_every_ordered_literal_byte():
    vectors = fixed_vectors()
    manifest = parse_canonical(vector_manifest())
    assert manifest["schema_version"] == "provider-conformance-vectors-v1"
    assert len(manifest["vectors"]) == 4
    for entry, vector in zip(manifest["vectors"], vectors, strict=True):
        assert entry == {"vector_id": vector.vector_id, "operation": vector.operation,
            "plan_sha256": sha256(vector.plan_bytes).hexdigest(),
            "input_sha256s": [sha256(value).hexdigest() for value in vector.input_bytes],
            "supplied_body_sha256s": [sha256(value).hexdigest() for value in vector.supplied_bodies],
            "projection_sha256s": [sha256(value).hexdigest() for value in vector.expected_projections],
            "expected_result_sha256": sha256(vector.expected_result_bytes).hexdigest()}


def test_every_literal_digest_and_suite_digest_are_independently_pinned():
    pinned = (
        ("text-basic-v1", "text", "3ec6587d8514875c5bec02267bc6f4e06cdf34f16a31c821686147ae7cebfcfb",
         ("2befdb6288fdc0fab3b26805948f7ded5a7b079d8699a8937070069c9dc3a95f",),
         ("841a21ab0f016344f9f5e2e84716bbfcf07e2f9b80dedcc0c73ff0e14c5db95c",),
         ("f327f70577d3c9725460d82d75b0d1e263b0a6cd5330b5cac4dd650d69afec45",),
         "cb7be1c0f099655a4cb1f9bdf2f66e908cbca2f181500f0cf9f8a028cd89db02"),
        ("text-refusal-v1", "text", "3ec6587d8514875c5bec02267bc6f4e06cdf34f16a31c821686147ae7cebfcfb",
         ("2befdb6288fdc0fab3b26805948f7ded5a7b079d8699a8937070069c9dc3a95f",),
         ("41557fd7ad77d976b0bfa436263fb054d9ff0e089c72d6929d38e110e4cb89c1",),
         ("f327f70577d3c9725460d82d75b0d1e263b0a6cd5330b5cac4dd650d69afec45",),
         "828d507ad9b586b45d28833a5347fe4565f4313115827cf1ff1bd556890cccff"),
        ("catalog-two-pages-v1", "catalog", "6d93d625fb2dd945987f2034a4a0ce215376c725dc856e4c6a0edd985842452f",
         (), ("e1a9ef552cefe7b12acc3608e22644be1628ca0a1f710164fb51d92adcb42921",
              "492f2a145e467b0d22c3e10a7b3897e153cd7cdfcef8a53b33f0bd085a72f2cb"),
         ("eb815544229f20d127ebf0920faf6b0ba42c6e35fd274cf825970022b49b94dd",
          "b8b19cb96c058272645869844fd39d415d3564a69ba6aacd5c1b5c6eac9715e5"),
         "0eb5faac599f44b06e7181d1668d815422460bcc597da0d45feaa2ecc2e3604e"),
        ("catalog-negative-capability-v1", "catalog",
         "6d93d625fb2dd945987f2034a4a0ce215376c725dc856e4c6a0edd985842452f",
         (), ("9c218c5a6185abfd2a3b690693aafc57314827c40809616b3976cb923680c8f4",),
         ("eb815544229f20d127ebf0920faf6b0ba42c6e35fd274cf825970022b49b94dd",),
         "fe177628d087f9a1fe8da505def20ca11d10e182d9f71bf86e7929336ea262ee"),
    )
    actual = tuple((vector.vector_id, vector.operation, sha256(vector.plan_bytes).hexdigest(),
        tuple(sha256(value).hexdigest() for value in vector.input_bytes),
        tuple(sha256(value).hexdigest() for value in vector.supplied_bodies),
        tuple(sha256(value).hexdigest() for value in vector.expected_projections),
        sha256(vector.expected_result_bytes).hexdigest()) for vector in fixed_vectors())
    assert actual == pinned
    assert SUITE_SHA256 == "04059afe33f51eadd840db9b984b6ee99e79de3164a096d6144b1be31ca9368c"


def test_vector_views_are_immutable_and_detached():
    first = fixed_vectors()
    second = fixed_vectors()
    assert first == second and first is not second
    assert type(first) is tuple and type(first[0].input_bytes) is tuple
    changed = bytearray(first[0].plan_bytes)
    changed[-1] ^= 1
    assert bytes(changed) != fixed_vectors()[0].plan_bytes
