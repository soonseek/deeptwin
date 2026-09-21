"""Independent pure text and complete-catalog vectors; no network or credentials."""

import json
import pytest
from app.tests._provider_worker_fixture import (
    MODEL,
    encoded,
    event,
    text_events,
    text_plan,
    model_record,
    page,
)


def test_request_body_preserves_only_explicit_text():
    from app.workers.provider_transform import prepare_text

    raw = "내 업무 자료".encode()
    assert json.loads(prepare_text(text_plan(raw), (raw,))) == {
        "model": MODEL,
        "max_tokens": 32,
        "stream": True,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "내 업무 자료"}]}
        ],
    }


def test_long_text_and_escaped_request_overflow():
    from app.workers.provider_transform import prepare_text, UnsupportedProfile

    raw = ("한" * 30000).encode()
    assert (
        json.loads(prepare_text(text_plan(raw), (raw,)))["messages"][0]["content"][0][
            "text"
        ]
        == raw.decode()
    )
    raw = b"\x00" * 180000
    with pytest.raises(UnsupportedProfile):
        prepare_text(text_plan(raw), (raw,))


def test_plural_deltas_nullable_atomic_cumulative_usage():
    from app.workers.provider_transform import parse_text_response

    chunks = text_events()
    chunks.insert(
        -1,
        event(
            "message_delta",
            delta={"stop_reason": "end_turn"},
            usage={
                "input_tokens": None,
                "output_tokens": 7,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 2,
            },
        ),
    )
    observed = parse_text_response(MODEL, chunks)
    assert (observed.state, observed.reason) == ("parsed_complete", "complete")
    assert observed.as_dict()["text_blocks"] == ["answer"]
    assert observed.as_dict()["usage_complete"] == {
        "input_tokens": 3,
        "output_tokens": 7,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 2,
    }
    broken = chunks[:-1] + [
        event("message_delta", delta={}, usage={"input_tokens": 9, "output_tokens": 1}),
        chunks[-1],
    ]
    result = parse_text_response(MODEL, broken)
    assert result.reason == "protocol_error"
    assert result.as_dict()["usage_observed"]["input_tokens"] == 3
    assert result.as_dict()["usage_observed"]["output_tokens"] == 7
    assert result.as_dict()["usage_complete"] is None


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("tool_use", "unsupported"),
        ("server_tool_use", "unsupported"),
        ("thinking", "unsupported"),
        ("redacted_thinking", "unsupported"),
        ("refusal", "refusal"),
        ("fallback", "model_mismatch"),
    ],
)
def test_rejected_blocks_drain_and_retain_usage(kind, reason):
    from app.workers.provider_transform import parse_text_response

    chunks = text_events(
        kind=kind,
        usage={"cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    )
    if kind in ("tool_use", "server_tool_use"):
        chunks[2:2] = [
            event(
                "content_block_delta",
                index=0,
                delta={"type": "input_json_delta", "partial_json": s},
            )
            for s in ("{evil", ":false}")
        ]
    if kind == "thinking":
        chunks[2:2] = [
            event(
                "content_block_delta",
                index=0,
                delta={"type": "thinking_delta", "thinking": "secret"},
            ),
            event(
                "content_block_delta",
                index=0,
                delta={"type": "signature_delta", "signature": "opaque"},
            ),
        ]
    result = parse_text_response(MODEL, chunks)
    assert result.reason == reason and result.as_dict()["text_blocks"] == []
    assert result.as_dict()["usage_complete"]["output_tokens"] == 4


@pytest.mark.parametrize("location", ["start", "delta"])
def test_refusal_details_with_end_turn(location):
    from app.workers.provider_transform import parse_text_response

    chunks = text_events()
    index = 0 if location == "start" else -2
    data = json.loads(chunks[index].split(b"data: ")[1])
    data["message" if location == "start" else "delta"]["stop_details"] = {
        "type": "refusal",
        "category": "cyber",
        "explanation": "fixture",
    }
    chunks[index] = (
        b"event: " + data["type"].encode() + b"\ndata: " + encoded(data) + b"\n\n"
    )
    result = parse_text_response(MODEL, chunks)
    assert result.reason == "refusal"
    assert "stop_details" not in result.as_dict() and "explanation" not in str(
        result.as_dict()
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("model", "model_mismatch"),
        ("unknown", "protocol_error"),
        ("late", "protocol_error"),
        ("index", "protocol_error"),
        ("wrong_delta", "protocol_error"),
        ("negative_usage", "protocol_error"),
        ("missing_stop", "protocol_error"),
        ("provider", "provider_error"),
    ],
)
def test_text_failure_precedence_and_no_success_prefix(mutation, reason):
    from app.workers.provider_transform import parse_text_response

    chunks = text_events(model="other" if mutation == "model" else MODEL)
    if mutation == "unknown":
        chunks.insert(1, event("mystery"))
    if mutation == "late":
        chunks.append(event("content_block_stop", index=0))
    if mutation == "index":
        chunks[2] = event(
            "content_block_delta", index=1, delta={"type": "text_delta", "text": "x"}
        )
    if mutation == "wrong_delta":
        chunks[2] = event(
            "content_block_delta",
            index=0,
            delta={"type": "input_json_delta", "partial_json": "x"},
        )
    if mutation == "negative_usage":
        chunks[-2] = event(
            "message_delta",
            delta={"stop_reason": "end_turn"},
            usage={"output_tokens": -1},
        )
    if mutation == "missing_stop":
        chunks.pop()
    if mutation == "provider":
        chunks = chunks[:1] + [
            event("error", error={"type": "api_error", "message": "private"})
        ]
    result = parse_text_response(MODEL, chunks)
    assert result.reason == reason and result.as_dict()["text_blocks"] == []
    assert result.as_dict()["usage_complete"] is None


def test_ping_comments_split_unicode_no_synthesized_cache_and_no_prose_refusal():
    from app.workers.provider_transform import parse_text_response

    raw = (
        b": comment\n\nevent: ping\n\n"
        + b"".join(text_events("한 refusal"))
        + event("ping")
    )
    result = parse_text_response(MODEL, (bytes([x]) for x in raw))
    assert result.state == "parsed_complete"
    assert result.as_dict()["text_blocks"] == ["한 refusal"]
    assert result.as_dict()["usage_observed"]["cache_read_input_tokens"] is None
    assert result.as_dict()["usage_complete"] is None


def test_complete_two_page_catalog_preserves_unknown_capability_evidence():
    from app.workers.provider_transform import CatalogAccumulator

    acc = CatalogAccumulator()
    capabilities = {
        "effort": {"supported": True, "levels": ["low", "high"]},
        "unknown": {"x": None},
    }
    assert (
        acc.accept_page(
            page([model_record("one", capabilities=capabilities, max_tokens=0)], True)
        )
        == "one"
    )
    assert acc.finish().as_dict()["models"] == []
    assert acc.accept_page(page([model_record("two")])) is None
    result = acc.finish()
    assert result.state == "parsed_complete" and result.as_dict()["complete"] is True
    assert result.as_dict()["models"][0]["capabilities"] == capabilities
    assert result.as_dict()["models"][0]["max_tokens"] == 0
    assert result.as_dict()["models"][1]["max_input_tokens"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "float",
        "negative",
        "bool_limit",
        "duplicate",
        "cursor",
        "timezone",
        "id",
        "nonterminal_empty",
    ],
)
def test_bad_catalog_never_selects_prefix(mutation):
    from app.workers.provider_transform import CatalogAccumulator

    acc = CatalogAccumulator()
    acc.accept_page(page([model_record("one")], True))
    entry = model_record("two")
    if mutation == "float":
        entry["capabilities"] = {"x": 1.5}
    if mutation == "negative":
        entry["capabilities"] = {"x": -1}
    if mutation == "bool_limit":
        entry["max_tokens"] = True
    if mutation in ("duplicate", "cursor"):
        entry["id"] = "one"
    if mutation == "timezone":
        entry["created_at"] = "2026-01-01T00:00:00"
    if mutation == "id":
        entry["id"] = "bad/id"
    acc.accept_page(
        page(
            [] if mutation == "nonterminal_empty" else [entry],
            mutation in ("cursor", "nonterminal_empty"),
        )
    )
    result = acc.finish()
    assert result.reason == "catalog_incomplete"
    assert result.as_dict()["models"] == [] and result.as_dict()["complete"] is False


@pytest.mark.parametrize("counter", [True, -1, 2**63, 1.5])
def test_invalid_usage_update_is_atomic(counter):
    from app.workers.provider_transform import parse_text_response

    chunks = text_events()
    chunks.insert(
        -1,
        event(
            "message_delta",
            delta={"stop_reason": "end_turn"},
            usage={"input_tokens": 19, "output_tokens": counter},
        ),
    )
    result = parse_text_response(MODEL, chunks)
    assert result.reason == "protocol_error"
    assert result.as_dict()["usage_observed"]["input_tokens"] == 3
    assert result.as_dict()["usage_observed"]["output_tokens"] == 4


@pytest.mark.parametrize(
    ("kind", "delta"),
    [
        ("refusal", {"type": "text_delta", "text": "x"}),
        ("fallback", {"type": "text_delta", "text": "x"}),
        ("redacted_thinking", {"type": "thinking_delta", "thinking": "x"}),
        ("tool_use", {"type": "text_delta", "text": "x"}),
        ("thinking", {"type": "signature_delta"}),
    ],
)
def test_rejected_block_incompatible_delta_is_protocol_error(kind, delta):
    from app.workers.provider_transform import parse_text_response

    chunks = text_events(kind=kind)
    chunks.insert(2, event("content_block_delta", index=0, delta=delta))
    assert parse_text_response(MODEL, chunks).reason == "protocol_error"


def test_late_corruption_clears_previously_complete_usage():
    from app.workers.provider_transform import parse_text_response

    chunks = text_events(
        kind="refusal",
        usage={"cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    )
    good = parse_text_response(MODEL, chunks)
    assert good.as_dict()["usage_complete"] is not None
    bad = parse_text_response(MODEL, chunks + [b"event: malformed\ndata: {\n\n"])
    assert bad.reason == "protocol_error" and bad.as_dict()["usage_complete"] is None
    assert bad.as_dict()["usage_observed"]["output_tokens"] == 4


@pytest.mark.parametrize(
    ("stop", "reason"),
    [
        ("refusal", "refusal"),
        ("max_tokens", "truncated"),
        ("model_context_window_exceeded", "truncated"),
        ("stop_sequence", "unsupported"),
        ("tool_use", "unsupported"),
        ("pause_turn", "unsupported"),
        ("unknown", "protocol_error"),
    ],
)
def test_exact_stop_mapping(stop, reason):
    from app.workers.provider_transform import parse_text_response

    assert parse_text_response(MODEL, text_events(stop=stop)).reason == reason


def test_unknown_details_and_semantic_precedence():
    from app.workers.provider_transform import parse_text_response

    chunks = text_events(kind="tool_use", model="other", stop="max_tokens")
    assert parse_text_response(MODEL, chunks).reason == "model_mismatch"
    chunks[-2] = event(
        "message_delta",
        delta={
            "stop_reason": "end_turn",
            "stop_details": {"type": "refusal", "explanation": "fixture"},
        },
        usage={"output_tokens": 4},
    )
    assert parse_text_response(MODEL, chunks).reason == "refusal"
    chunks = text_events()
    chunks[-2] = event(
        "message_delta",
        delta={"stop_reason": "end_turn", "stop_details": {"type": "new"}},
        usage={"output_tokens": 4},
    )
    assert parse_text_response(MODEL, chunks).reason == "unsupported"


def test_escaped_final_text_result_is_refused_without_partial_success():
    from app.workers.provider_transform import TextResponseAccumulator, result_bytes

    accumulator = TextResponseAccumulator(MODEL)
    # Direct decoded-event input exercises the final encoded-size guard independently
    # of the tighter SSE transport limit. All decoded text remains below 512KiB.
    for raw in text_events("\x00" * 180000):
        value = json.loads(raw.split(b"data: ")[1])
        accumulator.accept((value["type"], value))
    result = json.loads(result_bytes("text", "a" * 64, accumulator.finish()))
    assert (
        result["state"] == "unsupported_profile" and result["reason"] == "unsupported"
    )
    assert result["observation"]["text_blocks"] == []
    assert result["observation"]["usage_observed"]["output_tokens"] == 4


def test_system_concatenation_preserves_ordinals_and_invalid_utf8():
    from hashlib import sha256
    from app.workers.provider_transform import prepare_text
    from app.workers.provider_messages import ProviderMessageError

    raws = ("a".encode(), "한".encode(), b"user")
    plan = text_plan()
    plan["inputs"] = [{"size": len(x), "sha256": sha256(x).hexdigest()} for x in raws]
    plan["messages"] = [
        {"role": "system", "input_ordinals": [0, 1]},
        {"role": "user", "input_ordinals": [2]},
    ]
    assert json.loads(prepare_text(plan, raws))["system"] == "a한"
    raw = b"\xff"
    with pytest.raises(ProviderMessageError):
        prepare_text(text_plan(raw), (raw,))


def test_catalog_empty_terminal_and_twenty_page_cap():
    from app.workers.provider_transform import CatalogAccumulator

    empty = CatalogAccumulator()
    empty.accept_page(page([]))
    assert (
        empty.finish().state == "parsed_complete"
        and empty.finish().as_dict()["models"] == []
    )
    acc = CatalogAccumulator()
    for index in range(20):
        acc.accept_page(page([model_record(str(index))], True))
    assert (
        acc.finish().reason == "catalog_incomplete"
        and acc.finish().as_dict()["models"] == []
    )


@pytest.mark.parametrize(
    "case",
    [
        "per_page",
        "duplicate_json",
        "model_count",
        "depth",
        "members",
        "capability_bytes",
        "result_bytes",
    ],
)
def test_catalog_caps_fail_closed(case):
    from app.workers.provider_transform import CatalogAccumulator

    acc = CatalogAccumulator()
    if case == "per_page":
        raw = b" " * 1048577
    elif case == "duplicate_json":
        raw = b'{"data":[],"data":[],"has_more":false,"first_id":null,"last_id":null}'
    elif case == "model_count":
        raw = page([model_record(str(n)) for n in range(1001)])
    elif case == "depth":
        cap = {}
        for _ in range(9):
            cap = {"nested": cap}
        raw = page([model_record(capabilities=cap)])
    elif case == "members":
        raw = page([model_record(capabilities={str(n): True for n in range(129)})])
    elif case == "capability_bytes":
        raw = page([model_record(capabilities={str(n): "x" * 8192 for n in range(9)})])
    else:
        for n in range(19):
            raw = page(
                [
                    model_record(
                        str(n), capabilities={str(k): "x" * 8000 for k in range(7)}
                    )
                ],
                n < 18,
            )
            acc.accept_page(raw)
        assert acc.finish().reason == "catalog_incomplete"
        return
    acc.accept_page(raw)
    assert (
        acc.finish().reason == "catalog_incomplete"
        and acc.finish().as_dict()["models"] == []
    )


def test_catalog_aggregate_raw_page_cap_includes_ignored_fields():
    from app.workers.provider_transform import CatalogAccumulator

    acc = CatalogAccumulator()
    for index in range(5):
        value = json.loads(page([model_record(str(index))], True))
        value["ignored"] = ["x" * 60000 for _ in range(15)]
        cursor = acc.accept_page(encoded(value))
        if index < 4:
            assert cursor == str(index)
    assert acc.finish().reason == "catalog_incomplete"
    assert acc.finish().as_dict()["models"] == []


@pytest.mark.parametrize(
    "case",
    [
        "float_index",
        "overlap",
        "late_content",
        "repeated_start",
        "inconsistent_stop",
        "blocks",
    ],
)
def test_text_exact_index_order_and_block_caps(case):
    from app.workers.provider_transform import parse_text_response

    chunks = text_events()
    if case == "float_index":
        chunks[2] = event(
            "content_block_delta", index=0.0, delta={"type": "text_delta", "text": "x"}
        )
    elif case == "overlap":
        chunks.insert(
            2,
            event(
                "content_block_start",
                index=1,
                content_block={"type": "text", "text": ""},
            ),
        )
    elif case == "late_content":
        chunks.insert(
            -1,
            event(
                "content_block_start",
                index=1,
                content_block={"type": "text", "text": ""},
            ),
        )
    elif case == "repeated_start":
        chunks.insert(1, chunks[0])
    elif case == "inconsistent_stop":
        chunks.insert(
            -1,
            event(
                "message_delta",
                delta={"stop_reason": "max_tokens"},
                usage={"output_tokens": 5},
            ),
        )
    else:
        chunks = (
            [chunks[0]]
            + [
                part
                for index in range(33)
                for part in (
                    event(
                        "content_block_start",
                        index=index,
                        content_block={"type": "text", "text": ""},
                    ),
                    event("content_block_stop", index=index),
                )
            ]
            + chunks[-2:]
        )
    assert parse_text_response(MODEL, chunks).reason == "protocol_error"
