"""Strict framing for the bounded browser feasibility helper.

This is deliberately not a generic RPC layer.  A frame can request one synthetic
capture and carries response bytes, never a URL to fetch, a host path, a command,
credentials, or an inherited descriptor.
"""

from __future__ import annotations

import base64
import binascii
import json
import struct
from typing import Any
from urllib.parse import urlsplit


MAX_FRAME_BYTES = 65_536
SCHEMA = "deeptwin-browser-ipc-v1"
_CAPTURE_FIELDS = frozenset(
    {
        "schema",
        "request_id",
        "generation",
        "action",
        "url",
        "status",
        "headers",
        "body_base64",
    }
)
_ALLOWED_RESPONSE_HEADERS = frozenset({"content-type", "cache-control"})


class ProtocolViolation(ValueError):
    """The peer supplied a message outside the closed IPC schema."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolViolation(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def strict_json_loads(payload: str) -> Any:
    """Parse JSON while rejecting duplicate object keys at every nesting level."""
    try:
        return json.loads(payload, object_pairs_hook=_reject_duplicate_pairs)
    except ProtocolViolation:
        raise
    except json.JSONDecodeError as error:
        raise ProtocolViolation("frame is not JSON") from error


def _hex_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 32 and all(char in "0123456789abcdef" for char in value)


def _validate_capture(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict) or frozenset(message) != _CAPTURE_FIELDS:
        raise ProtocolViolation("capture frame has unknown or missing fields")
    if message["schema"] != SCHEMA or message["action"] != "capture":
        raise ProtocolViolation("unknown schema or action")
    if not _hex_id(message["request_id"]) or not _hex_id(message["generation"]):
        raise ProtocolViolation("request and generation IDs must be lowercase 128-bit hex")
    if not isinstance(message["url"], str) or len(message["url"]) > 256:
        raise ProtocolViolation("capture URL is missing or too large")
    try:
        parsed = urlsplit(message["url"])
        port = parsed.port
    except ValueError as error:
        raise ProtocolViolation("capture URL is malformed") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "fixture.deeptwin.invalid"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/t018/")
        or parsed.query
        or parsed.fragment
    ):
        raise ProtocolViolation("capture URL is outside the closed synthetic fixture origin")
    if type(message["status"]) is not int or message["status"] != 200:
        raise ProtocolViolation("the feasibility broker accepts only a successful fixture response")
    headers = message["headers"]
    if not isinstance(headers, list) or not 1 <= len(headers) <= 4:
        raise ProtocolViolation("invalid response headers")
    seen: set[str] = set()
    for item in headers:
        if not isinstance(item, list) or len(item) != 2 or not all(isinstance(value, str) for value in item):
            raise ProtocolViolation("headers must be string pairs")
        name, value = item
        lowered = name.lower()
        if name != lowered or lowered not in _ALLOWED_RESPONSE_HEADERS or lowered in seen:
            raise ProtocolViolation("response header is duplicated or unsupported")
        if len(value) > 256 or "\r" in value or "\n" in value:
            raise ProtocolViolation("invalid response header value")
        seen.add(lowered)
    if "content-type" not in seen:
        raise ProtocolViolation("content-type is required")
    if dict(headers)["content-type"] != "text/html; charset=utf-8":
        raise ProtocolViolation("the feasibility response must be UTF-8 HTML")
    body = message["body_base64"]
    if not isinstance(body, str) or len(body) > 43_692:
        raise ProtocolViolation("body must be base64 text")
    try:
        decoded = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ProtocolViolation("body is not canonical base64") from error
    if not decoded or len(decoded) > 32_768 or base64.b64encode(decoded).decode("ascii") != body:
        raise ProtocolViolation("fixture body is empty, too large, or non-canonical base64")
    return message


def encode_browser_request(message: dict[str, Any]) -> bytes:
    """Validate and length-prefix one capture message."""
    _validate_capture(message)
    payload = json.dumps(message, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolViolation("frame exceeds the 64 KiB IPC limit")
    return struct.pack(">I", len(payload)) + payload


def decode_browser_request(frame: bytes) -> dict[str, Any]:
    """Decode exactly one complete capture frame with no trailing bytes."""
    if not isinstance(frame, bytes) or len(frame) < 4 or len(frame) > MAX_FRAME_BYTES + 4:
        raise ProtocolViolation("invalid frame size")
    (length,) = struct.unpack(">I", frame[:4])
    if length > MAX_FRAME_BYTES or length != len(frame) - 4:
        raise ProtocolViolation("invalid frame length")
    try:
        message = strict_json_loads(frame[4:].decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ProtocolViolation("frame is not UTF-8 JSON") from error
    return _validate_capture(message)
