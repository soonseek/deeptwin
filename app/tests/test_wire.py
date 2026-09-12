"""Strict pre-domain wire parsing for the web release boundary."""

import json

import pytest

from app.api.wire import (
    WireInputError,
    WireLimits,
    parse_json_object,
    parse_json_then,
    parse_query,
    parse_singleton_headers,
)


def test_json_accepts_only_exact_utf8_top_level_object():
    assert parse_json_object(
        '{"name":"한국어","revision":1}'.encode(),
        required=("name", "revision"),
        field_types={"name": str, "revision": int},
    ) == {"name": "한국어", "revision": 1}
    for raw in (b"[]", b'"value"', b"null", b"\xef\xbb\xbf{}", b'\xff'):
        with pytest.raises(WireInputError):
            parse_json_object(raw)


@pytest.mark.parametrize(
    "raw",
    (
        b'{"x":1,"x":2}',
        b'{"nested":{"x":1,"x":2}}',
        b'{"x":1,"unknown":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1} trailing',
        b'{"x":1.25}',
    ),
)
def test_json_rejects_duplicate_unknown_nonfinite_float_and_trailing(raw):
    with pytest.raises(WireInputError):
        parse_json_object(raw, optional=("x", "nested"))


def test_json_rejects_missing_and_bool_for_integer():
    with pytest.raises(WireInputError):
        parse_json_object(b"{}", required=("revision",), field_types={"revision": int})
    with pytest.raises(WireInputError):
        parse_json_object(
            b'{"revision":true}',
            required=("revision",),
            field_types={"revision": int},
        )


@pytest.mark.parametrize("raw", (b'{"name":"\\ud800"}', b'{"\\udfff":"value"}'))
def test_json_rejects_escaped_unpaired_surrogates_as_wire_errors(raw):
    with pytest.raises(WireInputError):
        parse_json_object(raw, optional=("name", "\udfff"))


def test_json_enforces_endpoint_size_depth_item_member_and_string_limits():
    limits = WireLimits(
        max_bytes=64,
        max_depth=3,
        max_items=4,
        max_members=3,
        max_string_bytes=4,
        max_integer=99,
    )
    accepted = parse_json_object(b'{"x":[1,2]}', optional=("x",), limits=limits)
    assert accepted == {"x": [1, 2]}
    rejected = (
        b'{"padding":"' + b"x" * 60 + b'"}',
        b'{"x":[[[[]]]]}',
        b'{"x":[1,2,3,4,5]}',
        b'{"a":1,"b":2,"c":3,"d":4}',
        json.dumps({"x": "가나"}, ensure_ascii=False).encode(),
        b'{"x":100}',
    )
    for raw in rejected:
        with pytest.raises(WireInputError):
            parse_json_object(raw, optional=("x", "a", "b", "c", "d", "padding"), limits=limits)


def test_wire_rejection_occurs_before_supplied_domain_callback():
    calls = []
    with pytest.raises(WireInputError):
        parse_json_then(
            b'{"x":1,"x":2}',
            lambda value: calls.append(value),
            required=("x",),
            field_types={"x": int},
        )
    assert calls == []
    assert parse_json_then(
        b'{"x":1}', lambda value: value["x"] + 1,
        required=("x",), field_types={"x": int},
    ) == 2


def test_query_rejects_unknown_duplicate_and_malformed_percent_encoding():
    assert parse_query(
        b"name=%ED%95%9C%EA%B5%AD&revision=1",
        allowed=("name", "revision"),
        required=("name",),
    ) == {"name": "한국", "revision": "1"}
    for raw in (
        b"name=one&name=two",
        b"other=one",
        b"name=%",
        b"name=%0",
        b"name=%GG",
        b"name=one+two",
        b"name=one=two",
        b"=value",
        b"name=%FF",
        b"name=one;other=two",
    ):
        with pytest.raises(WireInputError):
            parse_query(raw, allowed=("name", "revision"), required=("name",))


def test_query_enforces_required_blank_and_size_rules():
    assert parse_query(b"", allowed=()) == {}
    for raw in (b"", b"name=", b"name=" + b"x" * 20):
        with pytest.raises(WireInputError):
            parse_query(raw, allowed=("name",), required=("name",), max_bytes=16)


def test_singleton_header_rejects_case_variant_duplicates_and_comma_folding():
    names = ("x-deeptwin-csrf", "host")
    assert parse_singleton_headers(
        ((b"Host", b"deeptwin.example"), (b"X-DeepTwin-CSRF", b"token")),
        names=names,
        required=names,
    ) == {"host": "deeptwin.example", "x-deeptwin-csrf": "token"}
    rejected = (
        ((b"X-DeepTwin-CSRF", b"one"), (b"x-deeptwin-csrf", b"two")),
        ((b"X-DeepTwin-CSRF", b"one,two"),),
        ((b"X-DeepTwin-CSRF", b" one"),),
        ((b"X-DeepTwin-CSRF", b"one\r\ntwo"),),
    )
    for raw in rejected:
        with pytest.raises(WireInputError):
            parse_singleton_headers(raw, names=names, required=("x-deeptwin-csrf",))


def test_wire_apis_reject_implicit_text_and_ambiguous_sets():
    with pytest.raises(TypeError):
        parse_json_object("{}")
    with pytest.raises(TypeError):
        parse_query("x=1", allowed=("x",))
    with pytest.raises(ValueError):
        parse_json_object(b"{}", required=("x", "x"))
    with pytest.raises(ValueError):
        parse_singleton_headers((), names=("host", "Host"))
