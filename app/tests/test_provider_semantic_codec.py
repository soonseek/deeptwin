import json

import pytest

from app.extensions.provider_semantic_contracts import ProviderSemanticError
from app.workers.provider_semantic_codec import (
    CatalogTraversal,
    advance_catalog,
    encode_text_body,
    normalize_text,
    parse_model_page,
)


def support(value=False):
    return {"supported": value}


def capabilities():
    return {
        "batch": support(), "citations": support(), "code_execution": support(),
        "context_management": {"supported": False},
        "effort": {"supported": True, "high": support(True), "low": support(True),
                   "max": support(), "medium": support(True)},
        "image_input": support(), "pdf_input": support(), "structured_outputs": support(),
        "thinking": {"supported": False, "types": {"adaptive": support(), "enabled": support()}},
    }


def page(ids, *, more=False):
    rows = [{"type": "model", "id": identity, "display_name": identity,
             "created_at": f"2026-09-{20-index:02d}T00:00:00Z",
             "capabilities": capabilities(), "max_input_tokens": 10000, "max_tokens": 8192}
            for index, identity in enumerate(ids)]
    return json.dumps({"data": rows, "first_id": ids[0] if ids else None,
                       "last_id": ids[-1] if ids else None, "has_more": more},
                      separators=(",", ":")).encode()


def dense_page(ids, *, more=False, created_at="2026-09-20T00:00:00Z"):
    rows = [{"type": "model", "id": identity, "display_name": identity,
             "created_at": created_at, "capabilities": capabilities(),
             "max_input_tokens": 10000, "max_tokens": 8192} for identity in ids]
    return json.dumps({"data": rows, "first_id": ids[0] if ids else None,
                       "last_id": ids[-1] if ids else None, "has_more": more},
                      separators=(",", ":")).encode()


def sse(events):
    return b"".join(("event: " + event + "\ndata: " + json.dumps(body, separators=(",", ":")) + "\n\n").encode()
                    for event, body in events)


def valid_stream(text="hello"):
    return sse([
        ("message_start", {"type": "message_start", "message": {"id": "msg", "type": "message",
          "role": "assistant", "model": "model-1", "content": [], "stop_reason": None,
          "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
          "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
          "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn",
          "stop_sequence": None}, "usage": {"output_tokens": 2}}),
        ("message_stop", {"type": "message_stop"}),
    ])


def test_models_page_preserves_optional_states_and_bounds_traversal():
    parsed = parse_model_page(page(["m1", "m2"], more=True))
    assert [model.id for model in parsed.models] == ["m1", "m2"]
    assert parsed.models[0].capabilities.state == "value"
    assert parsed.models[0].capabilities.value["effort"]["xhigh"] == {"state": "absent", "value": None}
    state = advance_catalog(CatalogTraversal(), parsed)
    final_raw = page(["m3"]).replace(b"2026-09-20T00:00:00Z", b"2026-09-18T00:00:00Z")
    state = advance_catalog(state, parse_model_page(final_raw))
    assert state.complete and state.model_ids == ("m1", "m2", "m3")
    with pytest.raises(ProviderSemanticError):
        advance_catalog(state, parse_model_page(page(["m3"])))


def test_sse_cumulative_usage_and_text_are_normalized_without_currency_fiction():
    observation = normalize_text(valid_stream("안녕"), "model-1")
    assert observation.reason == "complete"
    assert observation.text_blocks == ("안녕".encode(),)
    assert observation.usage["input_tokens"] == {"state": "value", "value": 3}
    assert observation.usage["output_tokens"] == {"state": "value", "value": 2}
    assert observation.usage["currency_cost_known"] is False


def test_sse_refuses_decreasing_usage_partial_and_model_mismatch():
    raw = valid_stream()
    with pytest.raises(ProviderSemanticError):
        normalize_text(raw, "different")
    with pytest.raises(ProviderSemanticError):
        normalize_text(raw.rsplit(b"event: message_stop", 1)[0], "model-1")
    decreasing = raw.replace(b'"input_tokens":3,"output_tokens":0',
                             b'"input_tokens":3,"output_tokens":3')
    with pytest.raises(ProviderSemanticError):
        normalize_text(decreasing, "model-1")


def test_text_body_is_exact_closed_profile():
    frozen = {"turn": {"model_id": "model-1"}, "max_output_tokens": 8,
              "messages": [{"role": "system", "input_ordinals": [0]},
                           {"role": "user", "input_ordinals": [1]}]}
    assert json.loads(encode_text_body(frozen, (b"rules", b"question"))) == {
        "model": "model-1", "max_tokens": 8, "system": "rules",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "question"}]}],
        "stream": True,
    }


@pytest.mark.parametrize("counts", [(100, 1), (100, 100, 56)])
def test_catalog_accepts_required_multi_page_boundaries(counts):
    state, offset = CatalogTraversal(), 0
    for page_index, count in enumerate(counts):
        ids = [f"model-{offset + index:03d}" for index in range(count)]
        offset += count
        state = advance_catalog(state, parse_model_page(dense_page(
            ids, more=page_index < len(counts) - 1)))
    assert state.complete and len(state.model_ids) == sum(counts)


def test_catalog_refuses_257th_twentieth_more_repeats_empty_more_and_time_reversal():
    first = [f"model-{index:03d}" for index in range(100)]
    second = [f"model-{100 + index:03d}" for index in range(100)]
    state = advance_catalog(CatalogTraversal(), parse_model_page(dense_page(first, more=True)))
    state = advance_catalog(state, parse_model_page(dense_page(second, more=True)))
    with pytest.raises(ProviderSemanticError):
        advance_catalog(state, parse_model_page(dense_page(
            [f"model-{200 + index:03d}" for index in range(57)])))
    with pytest.raises(ProviderSemanticError):
        advance_catalog(state, parse_model_page(dense_page(["model-000"])))
    with pytest.raises(ProviderSemanticError):
        parse_model_page(dense_page([], more=True))
    reversed_state = advance_catalog(CatalogTraversal(), parse_model_page(
        dense_page(["old"], more=True, created_at="2026-09-19T00:00:00Z")))
    with pytest.raises(ProviderSemanticError):
        advance_catalog(reversed_state, parse_model_page(
            dense_page(["new"], created_at="2026-09-20T00:00:00Z")))
    pages = CatalogTraversal()
    for index in range(19):
        pages = advance_catalog(pages, parse_model_page(
            dense_page([f"cursor-{index:02d}"], more=True)))
    with pytest.raises(ProviderSemanticError):
        advance_catalog(pages, parse_model_page(dense_page(["cursor-19"], more=True)))


def test_page_cursor_and_nested_capability_shapes_are_closed_and_optional_states_survive():
    value = json.loads(dense_page(["model-a"]))
    for name, expected in (("capabilities", "absent"), ("max_tokens", "null")):
        candidate = json.loads(dense_page(["model-a"]))
        if expected == "absent":
            del candidate["data"][0][name]
        else:
            candidate["data"][0][name] = None
        projected = parse_model_page(json.dumps(candidate, separators=(",", ":")).encode()).models[0]
        assert getattr(projected, name).state == expected
    value["data"][0]["capabilities"]["effort"]["xhigh"] = {"supported": False}
    projected = parse_model_page(json.dumps(value, separators=(",", ":")).encode()).models[0]
    assert projected.capabilities.value["effort"]["xhigh"] == {
        "state": "value", "value": {"supported": False}}
    for mutation in (
        lambda body: body.update(first_id="different"),
        lambda body: body.update(last_id="different"),
        lambda body: body["data"][0]["capabilities"]["effort"].update(future=True),
    ):
        malformed = json.loads(dense_page(["model-a"]))
        mutation(malformed)
        with pytest.raises(ProviderSemanticError):
            parse_model_page(json.dumps(malformed, separators=(",", ":")).encode())
    ordinary = json.loads(dense_page(["model-a"]))
    ordinary["future_root"] = {"number": 1}
    ordinary["data"][0]["future_model"] = ["retained"]
    retained = parse_model_page(json.dumps(ordinary, separators=(",", ":")).encode())
    assert retained.models[0].id == "model-a"


def test_json_cumulative_item_and_numeric_token_bounds():
    boundary_number = b'{"data":[],"first_id":null,"last_id":null,"has_more":false,"n":' + b"1" * 128 + b"}"
    assert parse_model_page(boundary_number).models == ()
    oversized_number = b'{"data":[],"first_id":null,"last_id":null,"has_more":false,"n":' + b"1" * 129 + b"}"
    with pytest.raises(ProviderSemanticError):
        parse_model_page(oversized_number)
    exact = {"data": [], "first_id": None, "last_id": None, "has_more": False,
             "ordinary": [None] * 65_531}
    assert parse_model_page(json.dumps(exact, separators=(",", ":")).encode()).models == ()
    many = {"data": [], "first_id": None, "last_id": None, "has_more": False,
            "ordinary": [None] * 65_532}
    with pytest.raises(ProviderSemanticError):
        parse_model_page(json.dumps(many, separators=(",", ":")).encode())


def test_sse_zero_and_four_blocks_unicode_unknown_usage_and_noncomplete_vectors():
    zero = sse([
        ("message_start", {"type": "message_start", "message": {"id": "msg", "type": "message",
          "role": "assistant", "model": "model-1", "content": [], "stop_reason": None,
          "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0,
                                             "future_usage": 7}}}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn",
          "stop_sequence": None}, "usage": {"output_tokens": 0}}),
        ("message_stop", {"type": "message_stop"})])
    observed = normalize_text(zero, "model-1")
    assert observed.text_blocks == ()
    assert observed.usage["unknown_categories"] == ["/message_start/message/usage/future_usage"]
    events = [("message_start", {"type": "message_start", "message": {"id": "msg", "type": "message",
        "role": "assistant", "model": "model-1", "content": [], "stop_reason": None,
        "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0}}})]
    for index, text in enumerate(("한", "둘", "셋", "넷")):
        events.extend([("content_block_start", {"type": "content_block_start", "index": index,
            "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": index,
             "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": index})])
    events.extend([("message_delta", {"type": "message_delta", "delta": {
        "stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 4}}),
        ("message_stop", {"type": "message_stop"})])
    assert normalize_text(sse(events), "model-1").text_blocks == tuple(
        value.encode() for value in ("한", "둘", "셋", "넷"))
    for malformed in (valid_stream().rstrip(),
                      valid_stream().replace(b'"stop_reason":"end_turn"', b'"stop_reason":"max_tokens"'),
                      valid_stream() + sse([("error", {"type": "error"})])):
        with pytest.raises(ProviderSemanticError):
            normalize_text(malformed, "model-1")


def test_usage_nullable_cache_and_thinking_contradictions_hold_cost_unknown():
    def stream(start_usage, delta_usage):
        return sse([
            ("message_start", {"type": "message_start", "message": {"id": "msg",
             "type": "message", "role": "assistant", "model": "model-1", "content": [],
             "stop_reason": None, "stop_sequence": None, "usage": start_usage}}),
            ("message_delta", {"type": "message_delta", "delta": {
             "stop_reason": "end_turn", "stop_sequence": None}, "usage": delta_usage}),
            ("message_stop", {"type": "message_stop"})])
    nullable = normalize_text(stream({"input_tokens": 1, "output_tokens": 0,
        "cache_creation_input_tokens": None, "cache_read_input_tokens": None,
        "cache_creation": None, "service_tier": None}, {"output_tokens": 0}), "model-1")
    assert nullable.usage["cache_creation"]["state"] == "null"
    assert nullable.usage["service_tier"]["state"] == "null"
    assert nullable.usage["currency_cost_known"] is False
    contradictions = [
        ({"input_tokens": 1, "output_tokens": 0, "cache_creation_input_tokens": 1,
          "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 1}},
         {"output_tokens": 0}),
        ({"input_tokens": 1, "output_tokens": 0, "cache_creation_input_tokens": 0,
          "cache_creation": {"ephemeral_1h_input_tokens": 1, "ephemeral_5m_input_tokens": 0}},
         {"output_tokens": 0}),
        ({"input_tokens": 1, "output_tokens": 0},
         {"output_tokens": 1, "output_tokens_details": {"thinking_tokens": 2}}),
    ]
    for start_usage, delta_usage in contradictions:
        with pytest.raises(ProviderSemanticError):
            normalize_text(stream(start_usage, delta_usage), "model-1")


@pytest.mark.parametrize(("aggregate", "cache_creation"), [
    ("absent", {"ephemeral_1h_input_tokens": 1, "ephemeral_5m_input_tokens": 0}),
    ("null", {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 1}),
])
def test_positive_cache_ttl_constituent_refuses_no_cache_profile(aggregate, cache_creation):
    """Removing the constituent-positive check must admit forbidden cache use."""
    start_usage = {"input_tokens": 1, "output_tokens": 0,
                   "cache_creation": cache_creation}
    if aggregate == "null":
        start_usage["cache_creation_input_tokens"] = None
    raw = sse([
        ("message_start", {"type": "message_start", "message": {"id": "msg",
         "type": "message", "role": "assistant", "model": "model-1", "content": [],
         "stop_reason": None, "stop_sequence": None, "usage": start_usage}}),
        ("message_delta", {"type": "message_delta", "delta": {
         "stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 0}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    with pytest.raises(ProviderSemanticError):
        normalize_text(raw, "model-1")

    zero = dict(start_usage)
    zero["cache_creation"] = {
        "ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0}
    observed = normalize_text(raw.replace(
        json.dumps(cache_creation, separators=(",", ":")).encode(),
        json.dumps(zero["cache_creation"], separators=(",", ":")).encode()), "model-1")
    assert observed.usage["cache_creation_input_tokens"]["state"] == aggregate


def test_delta_geo_and_service_tier_remain_raw_unknown_not_canonical_usage():
    raw = sse([
        ("message_start", {"type": "message_start", "message": {"id": "msg",
         "type": "message", "role": "assistant", "model": "model-1", "content": [],
         "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1,
         "output_tokens": 0}}}),
        ("message_delta", {"type": "message_delta", "delta": {
         "stop_reason": "end_turn", "stop_sequence": None}, "usage": {
         "output_tokens": 0, "inference_geo": "kr", "service_tier": "priority"}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    observed = normalize_text(raw, "model-1")
    assert observed.usage["inference_geo"] == {"state": "absent", "value": None}
    assert observed.usage["service_tier"] == {"state": "absent", "value": None}
    assert observed.usage["unknown_categories"] == [
        "/message_delta/usage/inference_geo", "/message_delta/usage/service_tier"]


def test_unknown_nested_decision_field_is_not_silently_accepted():
    malformed = valid_stream().replace(
        b'"content_block":{"type":"text","text":""}',
        b'"content_block":{"type":"text","text":"","future":true}')
    with pytest.raises(ProviderSemanticError):
        normalize_text(malformed, "model-1")


def test_sse_retains_ordinary_fields_and_validates_nested_usage_without_guessing():
    events = [
        ("message_start", {"type": "message_start", "ordinary_wrapper": {"retained": True},
         "message": {"id": "msg", "type": "message", "role": "assistant",
         "model": "model-1", "content": [], "stop_reason": None,
         "stop_sequence": None, "ordinary_message": "retained", "usage": {
             "input_tokens": 3, "output_tokens": 0,
             "cache_creation": {"ephemeral_1h_input_tokens": 0,
                                "ephemeral_5m_input_tokens": 0,
                                "future_counter": 0},
             "output_tokens_details": {"thinking_tokens": 0, "future_detail": 0},
             "server_tool_use": {"web_fetch_requests": 0, "web_search_requests": 0,
                                 "future_tool": 0},
             "inference_geo": "kr", "service_tier": "standard"}}}),
        ("message_delta", {"type": "message_delta", "ordinary_wrapper": 1,
         "delta": {"stop_reason": "end_turn", "stop_sequence": None,
                   "ordinary_delta": "retained"},
         "usage": {"output_tokens": 1,
                   "output_tokens_details": {"thinking_tokens": 1,
                                             "future_detail": 1},
                   "server_tool_use": {"web_fetch_requests": 0,
                                       "web_search_requests": 0,
                                       "future_tool": 0}}}),
        ("message_stop", {"type": "message_stop", "ordinary_wrapper": True}),
    ]
    observed = normalize_text(sse(events), "model-1")
    assert observed.usage["unknown_categories"] == [
        "/message_delta/usage/output_tokens_details/future_detail",
        "/message_delta/usage/server_tool_use/future_tool",
        "/message_start/message/usage/cache_creation/future_counter",
        "/message_start/message/usage/output_tokens_details/future_detail",
        "/message_start/message/usage/server_tool_use/future_tool",
    ]
    assert observed.usage["inference_geo"] == {"state": "value", "value": "kr"}
    assert observed.usage["service_tier"] == {"state": "value", "value": "standard"}


def test_sse_refuses_bool_indices_late_blocks_positive_tools_and_nested_decrease():
    malformed = []
    malformed.append(valid_stream().replace(b'"index":0', b'"index":false', 1))
    late = valid_stream().replace(b'event: message_stop',
        b'event: content_block_start\ndata: {"type":"content_block_start","index":1,'
        b'"content_block":{"type":"text","text":"late"}}\n\n'
        b'event: message_stop')
    malformed.append(late)
    malformed.append(valid_stream().replace(
        b'"input_tokens":3,"output_tokens":0',
        b'"input_tokens":3,"output_tokens":0,"server_tool_use":'
        b'{"web_fetch_requests":1,"web_search_requests":0}'))
    nested = sse([
        ("message_start", {"type": "message_start", "message": {"id": "msg",
         "type": "message", "role": "assistant", "model": "model-1", "content": [],
         "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1,
         "output_tokens": 0, "output_tokens_details": {"thinking_tokens": 2}}}}),
        ("message_delta", {"type": "message_delta", "delta": {
         "stop_reason": "end_turn", "stop_sequence": None}, "usage": {
         "output_tokens": 2, "output_tokens_details": {"thinking_tokens": 1}}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    malformed.append(nested)
    for raw in malformed:
        with pytest.raises(ProviderSemanticError):
            normalize_text(raw, "model-1")

    # A native cache breakdown may be observed while its aggregate counterpart is
    # absent; that counterpart remains unknown rather than being invented.
    cache_only = valid_stream().replace(
        b'"input_tokens":3,"output_tokens":0',
        b'"input_tokens":3,"output_tokens":0,"cache_creation":'
        b'{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}')
    observed = normalize_text(cache_only, "model-1")
    assert observed.usage["cache_creation_input_tokens"] == {
        "state": "absent", "value": None}
