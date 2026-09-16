"""Strict, framework-neutral HTTP wire decoding before domain authority.

The helpers in this module deliberately consume raw bytes and raw ASGI header pairs.  A web
framework's convenient mappings have already discarded duplicate-member/header evidence, so they
cannot be the canonical security boundary.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote_to_bytes

_PERCENT = re.compile(br"%[0-9A-Fa-f]{2}")
_HEADER_NAME = re.compile(rb"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


class WireInputError(ValueError):
    """A bounded, non-reflective wire-format rejection."""


@dataclass(frozen=True, slots=True)
class WireLimits:
    max_bytes: int = 8_192
    max_depth: int = 16
    max_items: int = 1_024
    max_members: int = 256
    max_string_bytes: int = 65_536
    max_integer: int = _MAX_SAFE_INTEGER

    def __post_init__(self) -> None:
        for value in (
            self.max_bytes,
            self.max_depth,
            self.max_items,
            self.max_members,
            self.max_string_bytes,
            self.max_integer,
        ):
            if type(value) is not int or value < 1:
                raise ValueError("wire limits must be strict positive integers")


_DEFAULT_WIRE_LIMITS = WireLimits()


def _closed_names(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} must be a collection")
    result = tuple(values)
    if any(type(value) is not str or not value for value in result):
        raise ValueError(f"{label} contains an invalid name")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} contains a duplicate")
    return result


def _fail(_detail: object | None = None) -> WireInputError:
    # Do not reflect attacker-controlled bytes, names or values in public exception text.
    return WireInputError("invalid request wire format")


def _strict_integer(token: str, maximum: int) -> int:
    negative = token.startswith("-")
    digits = token[1:] if negative else token
    if not digits or len(digits) > 16:
        raise _fail()
    value = int(token, 10)
    if abs(value) > maximum:
        raise _fail()
    return value


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8", "strict"))
    except UnicodeError:
        raise _fail() from None


def _walk_limits(root: object, limits: WireLimits) -> None:
    stack: list[tuple[object, int]] = [(root, 1)]
    item_count = 0
    while stack:
        value, depth = stack.pop()
        if depth > limits.max_depth:
            raise _fail()
        if type(value) is dict:
            if len(value) > limits.max_members:
                raise _fail()
            item_count += len(value)
            for key, child in value.items():
                if _utf8_size(key) > limits.max_string_bytes:
                    raise _fail()
                stack.append((child, depth + 1))
        elif type(value) is list:
            item_count += len(value)
            stack.extend((child, depth + 1) for child in value)
        elif type(value) is str:
            if _utf8_size(value) > limits.max_string_bytes:
                raise _fail()
        elif value is not None and type(value) not in (bool, int):
            raise _fail()
        if item_count > limits.max_items:
            raise _fail()


def parse_json_object(
    raw: bytes,
    *,
    required: Iterable[str] = (),
    optional: Iterable[str] = (),
    field_types: Mapping[str, type | tuple[type, ...]] | None = None,
    limits: WireLimits = _DEFAULT_WIRE_LIMITS,
) -> dict[str, Any]:
    """Decode one exact UTF-8 JSON object with closed top-level fields."""

    if type(raw) is not bytes:
        raise TypeError("raw JSON must be bytes")
    if type(limits) is not WireLimits:
        raise TypeError("limits must be WireLimits")
    if not raw or len(raw) > limits.max_bytes or raw.startswith(b"\xef\xbb\xbf"):
        raise _fail()
    required_names = _closed_names(required, label="required")
    optional_names = _closed_names(optional, label="optional")
    if set(required_names) & set(optional_names):
        raise ValueError("required and optional names overlap")
    allowed = set(required_names) | set(optional_names)

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _fail()
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_int=lambda token: _strict_integer(token, limits.max_integer),
            parse_float=lambda _token: (_ for _ in ()).throw(_fail()),
            parse_constant=lambda _token: (_ for _ in ()).throw(_fail()),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, WireInputError, ValueError, MemoryError):
        raise _fail() from None
    if type(value) is not dict:
        raise _fail()
    if set(value) - allowed or not set(required_names).issubset(value):
        raise _fail()
    _walk_limits(value, limits)

    if field_types is not None:
        # Mapping proxies and other trusted mappings are accepted, but string-like input is not.
        if type(field_types) is not dict and not isinstance(field_types, Mapping):
            raise TypeError("field_types must be a mapping")
        if set(field_types) - allowed:
            raise ValueError("field type declared for an unknown field")
        for name, expected in field_types.items():
            expected_types = expected if type(expected) is tuple else (expected,)
            if not expected_types or any(type(item) is not type for item in expected_types):
                raise TypeError("field type declarations must contain types")
            if name in value and type(value[name]) not in expected_types:
                raise _fail()
    return value


def parse_json_then[T](
    raw: bytes,
    callback: Callable[[dict[str, Any]], T],
    **parse_options: object,
) -> T:
    """Invoke domain work only after the complete strict wire parse succeeds."""

    if not callable(callback):
        raise TypeError("callback must be callable")
    value = parse_json_object(raw, **parse_options)
    return callback(value)


def _valid_percent_encoding(raw: bytes) -> bool:
    index = 0
    while index < len(raw):
        if raw[index] == 0x25:  # '%'
            match = _PERCENT.match(raw, index)
            if match is None:
                return False
            index += 3
        else:
            index += 1
    return True


def _query_text(raw: bytes) -> str:
    if not _valid_percent_encoding(raw):
        raise _fail()
    try:
        value = unquote_to_bytes(raw).decode("utf-8", "strict")
    except (UnicodeError, ValueError):
        raise _fail() from None
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise _fail()
    return value


def parse_query(
    raw: bytes,
    *,
    allowed: Iterable[str],
    required: Iterable[str] = (),
    max_bytes: int = 8_192,
) -> dict[str, str]:
    """Parse a closed, duplicate-free raw query string without lossy framework mappings."""

    if type(raw) is not bytes:
        raise TypeError("raw query must be bytes")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    allowed_names = _closed_names(allowed, label="allowed")
    required_names = _closed_names(required, label="required")
    if not set(required_names).issubset(allowed_names):
        raise ValueError("required query name is not allowed")
    if len(raw) > max_bytes or b"+" in raw or b";" in raw or b"#" in raw:
        raise _fail()
    if not raw:
        if required_names:
            raise _fail()
        return {}
    result: dict[str, str] = {}
    for field in raw.split(b"&"):
        if field.count(b"=") != 1:
            raise _fail()
        raw_name, raw_value = field.split(b"=", 1)
        name, value = _query_text(raw_name), _query_text(raw_value)
        if not name or not value or name not in allowed_names or name in result:
            raise _fail()
        result[name] = value
    if not set(required_names).issubset(result):
        raise _fail()
    return result


def parse_singleton_headers(
    raw_headers: Sequence[tuple[bytes, bytes]],
    *,
    names: Iterable[str],
    required: Iterable[str] = (),
    max_value_bytes: int = 8_192,
) -> dict[str, str]:
    """Read exact singleton headers while duplicate evidence is still available."""

    if isinstance(raw_headers, (str, bytes)) or not isinstance(raw_headers, Sequence):
        raise TypeError("raw_headers must be a sequence")
    configured = _closed_names(names, label="names")
    lowered = tuple(name.lower() for name in configured)
    if len(set(lowered)) != len(lowered):
        raise ValueError("header names collide case-insensitively")
    required_names = tuple(name.lower() for name in _closed_names(required, label="required"))
    if not set(required_names).issubset(lowered):
        raise ValueError("required header is not configured")
    if type(max_value_bytes) is not int or max_value_bytes < 1:
        raise ValueError("max_value_bytes must be positive")

    result: dict[str, str] = {}
    for item in raw_headers:
        if type(item) is not tuple or len(item) != 2 or any(type(value) is not bytes for value in item):
            raise TypeError("raw header entries must be byte pairs")
        raw_name, raw_value = item
        if not _HEADER_NAME.fullmatch(raw_name):
            raise _fail()
        name = raw_name.decode("ascii").lower()
        if name not in lowered:
            continue
        if name in result or not raw_value or len(raw_value) > max_value_bytes:
            raise _fail()
        if b"," in raw_value or raw_value != raw_value.strip() or any(
            byte < 0x20 or byte == 0x7F for byte in raw_value
        ):
            raise _fail()
        try:
            result[name] = raw_value.decode("ascii", "strict")
        except UnicodeError:
            raise _fail() from None
    if not set(required_names).issubset(result):
        raise _fail()
    return result


__all__ = [
    "WireInputError",
    "WireLimits",
    "parse_json_object",
    "parse_json_then",
    "parse_query",
    "parse_singleton_headers",
]
