"""Closed private control/plan/result values, separate from artifact grammar.

No value here supplies provider, model, credential, admission or send authority.
"""

from __future__ import annotations
import json
import math
import re
from ..adapters.claude_protocol import decode_json, ProtocolError, safe_id, integer

PROFILE = "claude-text-transform-v1"
MAX_BLOB = 1048576
MAX_PLAN = 262144
MAX_DIALOGUE = 12 * 1048576
USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
STOPS = (
    "end_turn",
    "max_tokens",
    "stop_sequence",
    "tool_use",
    "pause_turn",
    "refusal",
    "model_context_window_exceeded",
)
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_SERVICE = re.compile(r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*\Z")


class ProviderMessageError(ValueError):
    def __init__(self):
        super().__init__("invalid provider message")


def require(ok):
    if not ok:
        raise ProviderMessageError()


def closed(value, fields):
    require(type(value) is dict and set(value) == set(fields))
    return value


def uuid(value):
    require(type(value) is str and _UUID.fullmatch(value) is not None)
    return value


def digest(value):
    require(type(value) is str and _HEX.fullmatch(value) is not None)
    return value


def number(value, minimum=0, maximum=2**63 - 1):
    try:
        return integer(value, minimum, maximum)
    except ProtocolError:
        raise ProviderMessageError() from None


def identifier(value):
    try:
        return safe_id(value)
    except ProtocolError:
        raise ProviderMessageError() from None


def bounded_json(
    value,
    *,
    depth=16,
    items=16384,
    members=256,
    string=1048576,
    keys=128,
    floats=False,
    nonnegative=False,
):
    """Bound complete values before selecting fields, including ignored evidence."""
    stack = [(value, 1)]
    count = 0
    try:
        while stack:
            item, level = stack.pop()
            count += 1
            require(level <= depth and count <= items)
            if type(item) is dict:
                require(len(item) <= members)
                for key, child in item.items():
                    require(type(key) is str and len(key.encode("utf-8")) <= keys)
                    stack.append((child, level + 1))
            elif type(item) is list:
                require(len(item) <= items)
                stack.extend((child, level + 1) for child in item)
            elif type(item) is str:
                require(len(item.encode("utf-8")) <= string)
            elif type(item) is int:
                require((0 if nonnegative else -(2**63 - 1)) <= item <= 2**63 - 1)
            elif type(item) is float:
                require(floats and math.isfinite(item))
            else:
                require(item is None or type(item) is bool)
    except (UnicodeError, RecursionError, MemoryError):
        raise ProviderMessageError() from None


def _encode(value, *, cap, **limits):
    bounded_json(value, **limits)
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError, MemoryError):
        raise ProviderMessageError() from None
    require(len(raw) <= cap)
    return raw


def _decode(raw, *, cap, canonical=True, **limits):
    require(
        type(raw) is bytes
        and 0 < len(raw) <= cap
        and not raw.startswith(b"\xef\xbb\xbf")
    )
    try:
        value = decode_json(raw)
    except (ProtocolError, ValueError, MemoryError):
        raise ProviderMessageError() from None
    bounded_json(value, **limits)
    if canonical:
        require(_encode(value, cap=cap, **limits) == raw)
    return value


def encode_body(value):
    return _encode(value, cap=MAX_BLOB)


def decode_body(raw):
    return _decode(raw, cap=MAX_BLOB)


def descriptor(value, media=None):
    closed(value, ("batch_id", "size", "sha256", "media_type"))
    uuid(value["batch_id"])
    number(value["size"], 0, MAX_BLOB)
    digest(value["sha256"])
    require(
        value["media_type"] in ("application/json", "text/plain", "text/event-stream")
    )
    if media is not None:
        require(value["media_type"] == media)
    return value


_CONTROL_FIELDS = {
    "provider-worker-identify-v1": ("challenge",),
    "provider-worker-identity-v1": (
        "challenge",
        "service_identity",
        "build_identity_digest",
        "port_schema_set_digest",
        "platform",
        "uid",
        "gid",
        "worker_profile",
        "implemented_transforms",
    ),
    "provider-transform-start-v1": ("dialogue_id", "operation", "remaining_ms", "plan"),
    "provider-transform-ready-v1": ("dialogue_id", "phase"),
    "provider-transform-inputs-v1": ("dialogue_id", "batch_id"),
    "provider-transform-projection-v1": (
        "dialogue_id",
        "step",
        "endpoint",
        "after_id",
        "body",
    ),
    "provider-transform-response-v1": ("dialogue_id", "step", "status", "body"),
    "provider-transform-final-v1": ("dialogue_id", "result"),
}


def _control(value):
    require(type(value) is dict and type(value.get("schema")) is str)
    schema = value["schema"]
    require(schema in _CONTROL_FIELDS)
    closed(value, ("schema", *_CONTROL_FIELDS[schema]))
    if "dialogue_id" in value:
        uuid(value["dialogue_id"])
    if "step" in value:
        number(value["step"], 1, 20)
    if "challenge" in value:
        digest(value["challenge"])
    if schema == "provider-worker-identity-v1":
        require(
            type(value["service_identity"]) is str
            and 1 <= len(value["service_identity"]) <= 64
            and _SERVICE.fullmatch(value["service_identity"]) is not None
        )
        digest(value["build_identity_digest"])
        digest(value["port_schema_set_digest"])
        require(value["platform"] in ("linux/amd64", "linux/arm64"))
        number(value["uid"], 1, 2**32 - 1)
        number(value["gid"], 1, 2**32 - 1)
        require(
            value["worker_profile"] == PROFILE
            and value["implemented_transforms"] == ["catalog", "text"]
        )
    elif schema == "provider-transform-start-v1":
        require(value["operation"] in ("text", "catalog"))
        number(value["remaining_ms"], 1, 30000)
        descriptor(value["plan"], "application/json")
        require(value["plan"]["size"] <= MAX_PLAN)
    elif schema == "provider-transform-ready-v1":
        require(value["phase"] in ("plan", "inputs"))
    elif schema == "provider-transform-inputs-v1":
        if value["batch_id"] is not None:
            uuid(value["batch_id"])
    elif schema == "provider-transform-projection-v1":
        require(value["endpoint"] in ("messages", "models"))
        if value["after_id"] is not None:
            identifier(value["after_id"])
        if value["endpoint"] == "messages":
            require(value["step"] == 1 and value["after_id"] is None)
            descriptor(value["body"], "application/json")
        else:
            require(value["body"] is None)
            require((value["step"] == 1) == (value["after_id"] is None))
    elif schema == "provider-transform-response-v1":
        require(value["status"] in ("supplied", "unavailable", "truncated"))
        require((value["status"] == "supplied") == (value["body"] is not None))
        if value["body"] is not None:
            descriptor(value["body"])
            require(
                value["body"]["media_type"] in ("application/json", "text/event-stream")
            )
    elif schema == "provider-transform-final-v1":
        descriptor(value["result"], "application/json")
    return value


_CONTROL_LIMITS = dict(cap=16384, depth=8, items=2048, members=32, string=512)


def parse_control(raw):
    return _control(_decode(raw, **_CONTROL_LIMITS))


def encode_control(value):
    return _encode(_control(value), **_CONTROL_LIMITS)


def validate_plan(value, operation):
    require(operation in ("text", "catalog"))
    if operation == "catalog":
        closed(value, ("profile", "limit"))
        require(
            value["profile"] == PROFILE
            and type(value["limit"]) is int
            and value["limit"] == 1000
        )
        return value
    closed(value, ("profile", "model_id", "max_output_tokens", "messages", "inputs"))
    require(value["profile"] == PROFILE)
    identifier(value["model_id"])
    number(value["max_output_tokens"], 1, 8192)
    require(type(value["messages"]) is list and 1 <= len(value["messages"]) <= 32)
    require(type(value["inputs"]) is list and 1 <= len(value["inputs"]) <= 32)
    total = 0
    for entry in value["inputs"]:
        closed(entry, ("size", "sha256"))
        total += number(entry["size"], 0, MAX_BLOB)
        digest(entry["sha256"])
    require(total <= MAX_BLOB)
    ordinals = []
    user = False
    for index, message in enumerate(value["messages"]):
        closed(message, ("role", "input_ordinals"))
        require(message["role"] in ("system", "user", "assistant"))
        require(message["role"] != "system" or index == 0)
        user |= message["role"] == "user"
        require(
            type(message["input_ordinals"]) is list
            and 1 <= len(message["input_ordinals"]) <= 32
        )
        ordinals.extend(number(item, 0, 31) for item in message["input_ordinals"])
    require(user and ordinals == list(range(len(value["inputs"]))))
    return value


def parse_plan(raw, operation):
    return validate_plan(
        _decode(raw, cap=MAX_PLAN, depth=8, items=2048, members=32, string=512),
        operation,
    )


def validate_result(value):
    closed(
        value, ("schema", "operation", "state", "reason", "input_digest", "observation")
    )
    require(value["schema"] == "provider-transform-result-v1")
    require(value["operation"] in ("text", "catalog"))
    mapping = {
        "parsed_complete": ("complete",),
        "non_success": (
            "upstream_unavailable",
            "truncated",
            "refusal",
            "model_mismatch",
            "provider_error",
        ),
        "invalid_response": ("protocol_error", "catalog_incomplete"),
        "unsupported_profile": ("unsupported",),
    }
    require(
        type(value["state"]) is str
        and value["state"] in mapping
        and value["reason"] in mapping[value["state"]]
    )
    digest(value["input_digest"])
    observation = value["observation"]
    success = value["state"] == "parsed_complete"
    if value["operation"] == "text":
        require(value["reason"] != "catalog_incomplete")
        closed(
            observation,
            (
                "requested_model",
                "observed_model",
                "text_blocks",
                "stop_reason",
                "usage_observed",
                "usage_complete",
            ),
        )
        identifier(observation["requested_model"])
        if observation["observed_model"] is not None:
            identifier(observation["observed_model"])
        require(
            observation["stop_reason"] is None or observation["stop_reason"] in STOPS
        )
        require(
            type(observation["text_blocks"]) is list
            and len(observation["text_blocks"]) <= 32
        )
        require(all(type(x) is str for x in observation["text_blocks"]))
        require(
            sum(len(x.encode("utf-8")) for x in observation["text_blocks"]) <= 524288
        )
        require(success or observation["text_blocks"] == [])
        if success:
            require(
                observation["observed_model"] == observation["requested_model"]
                and observation["stop_reason"] == "end_turn"
            )
        closed(observation["usage_observed"], USAGE_KEYS)
        for n in observation["usage_observed"].values():
            if n is not None:
                number(n)
        if observation["usage_complete"] is not None:
            require(
                value["reason"]
                not in ("protocol_error", "provider_error", "upstream_unavailable")
            )
            closed(observation["usage_complete"], USAGE_KEYS)
            for n in observation["usage_complete"].values():
                number(n)
            require(observation["usage_complete"] == observation["usage_observed"])
    else:
        require(
            value["reason"]
            in ("complete", "catalog_incomplete", "upstream_unavailable", "truncated")
        )
        closed(observation, ("page_digests", "complete", "models"))
        require(
            type(observation["page_digests"]) is list
            and len(observation["page_digests"]) <= 20
        )
        for item in observation["page_digests"]:
            digest(item)
        require(
            type(observation["complete"]) is bool and observation["complete"] == success
        )
        require(
            type(observation["models"]) is list and len(observation["models"]) <= 1000
        )
        require(success or observation["models"] == [])
        ids = set()
        for model in observation["models"]:
            closed(
                model,
                (
                    "id",
                    "display_name",
                    "created_at",
                    "max_input_tokens",
                    "max_tokens",
                    "capabilities",
                ),
            )
            identifier(model["id"])
            require(model["id"] not in ids)
            ids.add(model["id"])
            validate_model_fields(model)
    return value


def validate_model_fields(model):
    from datetime import datetime

    require(
        type(model["display_name"]) is str
        and 1 <= len(model["display_name"].encode("utf-8")) <= 512
    )
    require(
        type(model["created_at"]) is str
        and len(model["created_at"].encode("utf-8")) <= 64
    )
    try:
        require(datetime.fromisoformat(model["created_at"]).utcoffset() is not None)
    except ValueError:
        raise ProviderMessageError() from None
    for field in ("max_input_tokens", "max_tokens"):
        if model.get(field) is not None:
            number(model[field])
    capabilities = model.get("capabilities")
    if capabilities is not None:
        require(type(capabilities) is dict)
        _encode(
            capabilities,
            cap=65536,
            depth=8,
            items=2048,
            members=128,
            string=8192,
            nonnegative=True,
        )


def encode_result(value):
    return encode_body(validate_result(value))


def parse_result(raw):
    return validate_result(decode_body(raw))
