"""Bounded Claude Models and text SSE codec for the semantic profile."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import math
import re
from typing import Any

from ..domain.refs import canonical_json
from ..extensions.provider_semantic_contracts import (
    MAX_INPUTS, MAX_OUTPUT_BLOCKS, MAX_OUTPUT_TOKENS, ProviderSemanticError, identifier,
)

MAX_RAW = 1_048_576
MAX_CATALOG_RAW = 4_194_304
MAX_EVENTS = 8_192
MAX_EVENT_BYTES = 65_536


def _require(ok: bool, message: str = "invalid provider response") -> None:
    if not ok:
        raise ProviderSemanticError(message)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def _json(raw: bytes) -> Any:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_RAW and not raw.startswith(b"\xef\xbb\xbf"))
    try:
        def number(token, convert):
            _require(len(token.encode("ascii")) <= 128, "numeric token exceeds bound")
            value = convert(token)
            _require(type(value) is not float or math.isfinite(value))
            return value
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_int=lambda token: number(token, int),
                           parse_float=lambda token: number(token, float),
                           parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError):
        raise ProviderSemanticError("invalid upstream JSON") from None
    member_count = 0
    def walk(item, depth=0):
        nonlocal member_count
        _require(depth <= 32)
        if type(item) is dict:
            member_count += len(item)
            _require(member_count <= 65_536, "JSON recursive member bound exceeded")
            for key, child in item.items():
                _require(len(key.encode()) <= 65_536)
                walk(child, depth + 1)
        elif type(item) is list:
            member_count += len(item)
            _require(member_count <= 65_536, "JSON recursive member bound exceeded")
            for child in item:
                walk(child, depth + 1)
        elif type(item) is str:
            _require(len(item.encode()) <= 65_536)
        elif type(item) is float:
            _require(math.isfinite(item))
    walk(value)
    return value


@dataclass(frozen=True, slots=True)
class OptionalField:
    state: str
    value: Any

    def __post_init__(self):
        _require(self.state in {"absent", "null", "value"})
        _require((self.state == "value") == (self.value is not None))

    def as_dict(self):
        return {"state": self.state, "value": self.value}


def _optional(mapping, name, validator=lambda value: value):
    if name not in mapping:
        return OptionalField("absent", None)
    if mapping[name] is None:
        return OptionalField("null", None)
    return OptionalField("value", validator(mapping[name]))


def _support(value):
    _require(type(value) is dict and set(value) == {"supported"} and type(value["supported"]) is bool)
    return {"supported": value["supported"]}


def _capabilities(value):
    required = {"batch", "citations", "code_execution", "context_management", "effort",
                "image_input", "pdf_input", "structured_outputs", "thinking"}
    _require(type(value) is dict and set(value) == required)
    result = {name: _support(value[name]) for name in
              ("batch", "citations", "code_execution", "image_input", "pdf_input", "structured_outputs")}
    context = value["context_management"]
    _require(type(context) is dict and set(context) <= {"supported", "clear_thinking_20251015",
             "clear_tool_uses_20250919", "compact_20260112"} and "supported" in context
             and type(context["supported"]) is bool)
    result["context_management"] = {"supported": context["supported"]}
    for name in ("clear_thinking_20251015", "clear_tool_uses_20250919", "compact_20260112"):
        result["context_management"][name] = _optional(context, name, _support).as_dict()
    effort = value["effort"]
    _require(type(effort) is dict and set(effort) <= {"supported", "high", "low", "max", "medium", "xhigh"}
             and {"supported", "high", "low", "max", "medium"} <= set(effort)
             and type(effort["supported"]) is bool)
    result["effort"] = {"supported": effort["supported"]}
    for name in ("high", "low", "max", "medium"):
        result["effort"][name] = _support(effort[name])
    result["effort"]["xhigh"] = _optional(effort, "xhigh", _support).as_dict()
    levels = [result["effort"][name]["supported"] for name in ("high", "low", "max", "medium")]
    if result["effort"]["xhigh"]["state"] == "value":
        levels.append(result["effort"]["xhigh"]["value"]["supported"])
    _require(effort["supported"] or not any(levels), "contradictory effort capabilities")
    thinking = value["thinking"]
    _require(type(thinking) is dict and set(thinking) == {"supported", "types"}
             and type(thinking["supported"]) is bool and type(thinking["types"]) is dict
             and set(thinking["types"]) == {"adaptive", "enabled"})
    result["thinking"] = {"supported": thinking["supported"], "types": {
        "adaptive": _support(thinking["types"]["adaptive"]),
        "enabled": _support(thinking["types"]["enabled"]),}}
    return result


def _positive(value):
    _require(type(value) is int and 1 <= value <= 9_007_199_254_740_991)
    return value


@dataclass(frozen=True, slots=True)
class ModelProjection:
    id: str
    display_name: str
    created_at: str
    capabilities: OptionalField
    max_input_tokens: OptionalField
    max_tokens: OptionalField


@dataclass(frozen=True, slots=True)
class ModelPage:
    models: tuple[ModelProjection, ...]
    first_id: str | None
    last_id: str | None
    has_more: bool
    raw_sha256: str
    raw_size: int


_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})\Z")


def _model(value):
    required = {"type", "id", "display_name", "created_at"}
    _require(type(value) is dict and required <= set(value))
    _require(value["type"] == "model")
    identity = identifier(value["id"])
    display = value["display_name"]
    created = value["created_at"]
    _require(type(display) is str and 1 <= len(display.encode()) <= 512)
    _require(type(created) is str and len(created) <= 64 and _RFC3339.fullmatch(created) is not None)
    try:
        datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        raise ProviderSemanticError("invalid model timestamp") from None
    return ModelProjection(identity, display, created,
                           _optional(value, "capabilities", _capabilities),
                           _optional(value, "max_input_tokens", _positive),
                           _optional(value, "max_tokens", _positive))


def validate_model_projection(value):
    """Validate the closed durable decision projection (not ordinary raw fields)."""
    _require(type(value) is dict and set(value) == {"id", "display_name", "created_at",
        "capabilities", "max_input_tokens", "max_tokens"})
    native = {"type": "model", "id": value["id"], "display_name": value["display_name"],
              "created_at": value["created_at"]}
    for name, validator in (("capabilities", _capabilities_projection),
                            ("max_input_tokens", _positive), ("max_tokens", _positive)):
        field = value[name]
        _require(type(field) is dict and set(field) == {"state", "value"}
                 and field["state"] in {"absent", "null", "value"})
        if field["state"] == "value":
            validator(field["value"])
        else:
            _require(field["value"] is None)
    _model(native)
    return value


def _optional_projection(value, validator):
    _require(type(value) is dict and set(value) == {"state", "value"}
             and value["state"] in {"absent", "null", "value"})
    if value["state"] == "value":
        validator(value["value"])
    else:
        _require(value["value"] is None)


def _capabilities_projection(value):
    required = {"batch", "citations", "code_execution", "context_management", "effort",
                "image_input", "pdf_input", "structured_outputs", "thinking"}
    _require(type(value) is dict and set(value) == required)
    for name in ("batch", "citations", "code_execution", "image_input", "pdf_input",
                 "structured_outputs"):
        _support(value[name])
    context = value["context_management"]
    _require(type(context) is dict and set(context) == {"supported", "clear_thinking_20251015",
        "clear_tool_uses_20250919", "compact_20260112"}
        and type(context["supported"]) is bool)
    for name in ("clear_thinking_20251015", "clear_tool_uses_20250919", "compact_20260112"):
        _optional_projection(context[name], _support)
    effort = value["effort"]
    _require(type(effort) is dict and set(effort) == {"supported", "high", "low", "max",
        "medium", "xhigh"} and type(effort["supported"]) is bool)
    for name in ("high", "low", "max", "medium"):
        _support(effort[name])
    _optional_projection(effort["xhigh"], _support)
    levels = [effort[name]["supported"] for name in ("high", "low", "max", "medium")]
    if effort["xhigh"]["state"] == "value":
        levels.append(effort["xhigh"]["value"]["supported"])
    _require(effort["supported"] or not any(levels), "contradictory effort capabilities")
    thinking = value["thinking"]
    _require(type(thinking) is dict and set(thinking) == {"supported", "types"}
             and type(thinking["supported"]) is bool and type(thinking["types"]) is dict
             and set(thinking["types"]) == {"adaptive", "enabled"})
    _support(thinking["types"]["adaptive"]); _support(thinking["types"]["enabled"])
    return value


def parse_model_page(raw: bytes) -> ModelPage:
    value = _json(raw)
    required = {"data", "first_id", "last_id", "has_more"}
    _require(type(value) is dict and required <= set(value))
    _require(type(value["data"]) is list and len(value["data"]) <= 100 and type(value["has_more"]) is bool)
    models = tuple(_model(item) for item in value["data"])
    ids = [item.id for item in models]
    _require(len(ids) == len(set(ids)))
    for cursor in (value["first_id"], value["last_id"]):
        _require(cursor is None or type(cursor) is str)
        if cursor is not None:
            identifier(cursor)
    _require((not models and value["first_id"] is None and value["last_id"] is None and not value["has_more"])
             or (bool(models) and value["first_id"] == ids[0] and value["last_id"] == ids[-1]))
    return ModelPage(models, value["first_id"], value["last_id"], value["has_more"],
                     sha256(raw).hexdigest(), len(raw))


@dataclass(frozen=True, slots=True)
class CatalogTraversal:
    pages: tuple[ModelPage, ...] = ()
    requested_cursors: tuple[str, ...] = ()
    model_ids: tuple[str, ...] = ()
    raw_bytes: int = 0
    complete: bool = False


def advance_catalog(state: CatalogTraversal, page: ModelPage) -> CatalogTraversal:
    _require(type(state) is CatalogTraversal and type(page) is ModelPage and not state.complete)
    _require(len(state.pages) < 20 and state.raw_bytes + page.raw_size <= MAX_CATALOG_RAW)
    expected_cursor = state.pages[-1].last_id if state.pages else None
    cursors = state.requested_cursors + ((expected_cursor,) if expected_cursor is not None else ())
    _require(len(cursors) == len(set(cursors)))
    if expected_cursor is not None:
        _require(page.last_id != expected_cursor)
    new_ids = tuple(model.id for model in page.models)
    _require(not set(state.model_ids).intersection(new_ids) and len(state.model_ids) + len(new_ids) <= 256)
    _require(not page.has_more or bool(page.models))
    if page.has_more:
        _require(len(state.pages) + 1 < 20)
    instants = []
    for model in (*[m for p in state.pages for m in p.models], *page.models):
        instant = datetime.fromisoformat(model.created_at.replace("Z", "+00:00"))
        if instant.timestamp() != 0:
            instants.append(instant)
    _require(all(left >= right for left, right in zip(instants, instants[1:])), "model order changed")
    return CatalogTraversal(state.pages + (page,), cursors, state.model_ids + new_ids,
                            state.raw_bytes + page.raw_size, not page.has_more)


def encode_text_body(frozen_content: dict, input_bytes: tuple[bytes, ...]) -> bytes:
    _require(type(frozen_content) is dict and type(input_bytes) is tuple
             and 1 <= len(input_bytes) <= MAX_INPUTS)
    messages = frozen_content.get("messages")
    _require(type(messages) is list and frozen_content.get("turn", {}).get("model_id") is not None)
    texts = []
    try:
        texts = [item.decode("utf-8") for item in input_bytes]
    except (AttributeError, UnicodeDecodeError):
        raise ProviderSemanticError("input is not UTF-8 text") from None
    body = {"model": identifier(frozen_content["turn"]["model_id"]),
            "max_tokens": _positive(frozen_content["max_output_tokens"]), "messages": [], "stream": True}
    _require(body["max_tokens"] <= MAX_OUTPUT_TOKENS)
    for index, message in enumerate(messages):
        ordinals = message.get("input_ordinals") if type(message) is dict else None
        _require(type(ordinals) is list and ordinals and all(type(n) is int and 0 <= n < len(texts) for n in ordinals))
        if message.get("role") == "system":
            _require(index == 0 and len(ordinals) == 1 and "system" not in body)
            body["system"] = texts[ordinals[0]]
        else:
            _require(message.get("role") in {"user", "assistant"})
            body["messages"].append({"role": message["role"], "content": [
                {"type": "text", "text": texts[n]} for n in ordinals]})
    _require(any(message["role"] == "user" for message in body["messages"]))
    raw = canonical_json(body)
    _require(len(raw) <= MAX_RAW)
    return raw


def _f(mapping, name, validator=lambda value: value):
    return _optional(mapping, name, validator).as_dict()


def _nonnegative(value):
    _require(type(value) is int and 0 <= value <= 9_007_199_254_740_991)
    return value


def _pointer(prefix, name):
    path = prefix + "/" + name.replace("~", "~0").replace("/", "~1")
    _require(len(path.encode("utf-8")) <= 512, "unknown usage path exceeds bound")
    return path


def _usage_object(value, *, event, unknown):
    """Validate one native usage object and return only reviewed known fields."""
    _require(type(value) is dict)
    required = {"input_tokens", "output_tokens"} if event == "message_start" else {"output_tokens"}
    _require(required <= set(value))
    allowed = ({"input_tokens", "output_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens", "cache_creation", "output_tokens_details",
                "server_tool_use", "inference_geo", "service_tier"}
               if event == "message_start" else
               {"input_tokens", "output_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens", "output_tokens_details", "server_tool_use"})
    prefix = "/message_start/message/usage" if event == "message_start" else "/message_delta/usage"
    result = {}
    for name, item in value.items():
        if name not in allowed:
            unknown.add(_pointer(prefix, name))
            continue
        if item is None:
            _require(name not in required)
            result[name] = None
            continue
        if name in {"input_tokens", "output_tokens", "cache_creation_input_tokens",
                    "cache_read_input_tokens"}:
            result[name] = _nonnegative(item)
            continue
        if name == "inference_geo":
            _require(type(item) is str and 1 <= len(item.encode("utf-8")) <= 128
                     and "\x00" not in item)
            result[name] = item
            continue
        if name == "service_tier":
            _require(item in {"standard", "priority", "batch"})
            result[name] = item
            continue
        expected = ({"ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"}
                    if name == "cache_creation" else {"thinking_tokens"}
                    if name == "output_tokens_details" else
                    {"web_fetch_requests", "web_search_requests"})
        _require(type(item) is dict and expected <= set(item))
        nested = {}
        for nested_name, nested_value in item.items():
            if nested_name not in expected:
                unknown.add(_pointer(prefix + "/" + name, nested_name))
            else:
                nested[nested_name] = _nonnegative(nested_value)
        result[name] = nested
    _require(len(unknown) <= 64, "too many unknown usage categories")
    return result


def _merge_usage(target, current):
    for name, item in current.items():
        previous = target.get(name)
        if item is None:
            if name not in target:
                target[name] = None
            continue
        if type(item) is int and previous is not None:
            _require(type(previous) is int and item >= previous, "decreasing cumulative usage")
        elif type(item) is dict and type(previous) is dict:
            for nested_name, nested_value in item.items():
                if nested_name in previous:
                    _require(nested_value >= previous[nested_name], "decreasing cumulative usage")
        target[name] = item


@dataclass(frozen=True, slots=True)
class TextObservation:
    reason: str
    observed_model: str | None
    stop_reason: str | None
    text_blocks: tuple[bytes, ...]
    usage: dict


def _events(raw: bytes):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_RAW
             and (raw.endswith(b"\n\n") or raw.endswith(b"\r\n\r\n")))
    events = []
    for block in raw.replace(b"\r\n", b"\n").split(b"\n\n"):
        if not block:
            continue
        _require(len(block) <= MAX_EVENT_BYTES)
        event = None
        data = []
        for line in block.split(b"\n"):
            if line.startswith(b"event: "):
                event = line[7:].decode("utf-8")
            elif line.startswith(b"data: "):
                data.append(line[6:])
            elif line and not line.startswith(b":"):
                raise ProviderSemanticError("invalid SSE field")
        _require(event is not None and data)
        events.append((event, _json(b"\n".join(data))))
        _require(len(events) <= MAX_EVENTS)
    return events


def normalize_text(raw: bytes, requested_model: str) -> TextObservation:
    requested_model = identifier(requested_model)
    started = stopped = False
    active = None
    blocks: list[bytearray] = []
    stop_reason = observed_model = None
    usage_source = {}
    unknown = set()
    for event, value in _events(raw):
        _require(type(value) is dict)
        if event == "ping":
            _require(value == {"type": "ping"})
            continue
        if event not in {"message_start", "content_block_start", "content_block_delta",
                                             "content_block_stop", "message_delta", "message_stop", "error"}:
            continue
        _require(value.get("type") == event)
        if event == "error":
            raise ProviderSemanticError("provider stream error")
        if event == "message_start":
            _require(not started and "message" in value)
            message = value.get("message")
            required_message = {"id", "type", "role", "model", "content", "stop_reason",
                                "stop_sequence", "usage"}
            _require(type(message) is dict and required_message <= set(message)
                     and type(message.get("id")) is str
                     and 1 <= len(message["id"].encode("utf-8")) <= 200
                     and message.get("type") == "message" and message.get("role") == "assistant"
                     and message.get("content") == [] and message.get("stop_reason") is None
                     and message.get("stop_sequence") is None)
            observed_model = identifier(message.get("model"))
            _require(observed_model == requested_model)
            _merge_usage(usage_source, _usage_object(message.get("usage"),
                                                      event=event, unknown=unknown))
            started = True
        elif event == "content_block_start":
            _require(set(value) == {"type", "index", "content_block"}
                     and started and not stopped and stop_reason is None and active is None
                     and type(value.get("index")) is int and value.get("index") == len(blocks)
                     and len(blocks) < MAX_OUTPUT_BLOCKS)
            content = value.get("content_block")
            _require(type(content) is dict and set(content) == {"type", "text"}
                     and content.get("type") == "text" and type(content.get("text")) is str)
            blocks.append(bytearray(content["text"].encode()))
            active = value["index"]
        elif event == "content_block_delta":
            delta = value.get("delta")
            _require(set(value) == {"type", "index", "delta"}
                     and active is not None and type(value.get("index")) is int
                     and value.get("index") == active and type(delta) is dict
                     and set(delta) == {"type", "text"}
                     and delta.get("type") == "text_delta" and type(delta.get("text")) is str)
            blocks[active].extend(delta["text"].encode())
        elif event == "content_block_stop":
            _require(set(value) == {"type", "index"}
                     and active is not None and type(value.get("index")) is int
                     and value.get("index") == active)
            active = None
        elif event == "message_delta":
            _require({"type", "delta", "usage"} <= set(value)
                     and started and active is None and not stopped and stop_reason is None)
            delta, current = value.get("delta"), value.get("usage")
            _require(type(delta) is dict and {"stop_reason", "stop_sequence"} <= set(delta))
            reason = delta.get("stop_reason")
            _require(type(reason) is str and reason == "end_turn" and delta.get("stop_sequence") is None)
            stop_reason = reason
            _merge_usage(usage_source, _usage_object(current, event=event, unknown=unknown))
        elif event == "message_stop":
            _require(started and active is None
                     and stop_reason == "end_turn" and not stopped)
            stopped = True
    _require(started and stopped)
    for name in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        if name in usage_source and usage_source[name] is not None:
            _nonnegative(usage_source[name])
    cache = usage_source.get("cache_creation")
    if cache is not None:
        _require(type(cache) is dict and set(cache) == {"ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"})
        total = _nonnegative(cache["ephemeral_1h_input_tokens"]) + _nonnegative(cache["ephemeral_5m_input_tokens"])
        _require(total == 0, "cache creation usage contradicts selected profile")
        if usage_source.get("cache_creation_input_tokens") is not None:
            _require(usage_source["cache_creation_input_tokens"] == total)
    details = usage_source.get("output_tokens_details")
    if details is not None:
        _require(type(details) is dict and set(details) == {"thinking_tokens"}
                 and _nonnegative(details["thinking_tokens"]) <= usage_source["output_tokens"])
    tools = usage_source.get("server_tool_use")
    if tools is not None:
        _require(type(tools) is dict and set(tools) == {"web_fetch_requests", "web_search_requests"})
        _require(not any(tools.values()), "server tool usage contradicts selected profile")
    _require(not any((usage_source.get(name) or 0) > 0 for name in
                     ("cache_creation_input_tokens", "cache_read_input_tokens")))
    usage = {name: _f(usage_source, name) for name in
             ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
              "cache_creation", "output_tokens_details", "server_tool_use", "inference_geo", "service_tier")}
    usage.update(unknown_categories=sorted(unknown), cache_zero_basis="request_omits_cache_and_tools",
                 currency_cost_known=False)
    _require(sum(len(block) for block in blocks) <= 524_288, "provider text exceeds output bound")
    return TextObservation("complete", observed_model, stop_reason, tuple(bytes(block) for block in blocks), usage)


__all__ = ["CatalogTraversal", "ModelPage", "ModelProjection", "OptionalField", "TextObservation",
           "advance_catalog", "encode_text_body", "normalize_text", "parse_model_page",
           "validate_model_projection"]
