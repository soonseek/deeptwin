"""T090 create/rotate ingress wire checks.

The explicit create/rotate ingress may pass a raw secret once through bounded
no-store control-plane request memory — but only after exactly one decimal
Content-Length of at most 96 KiB, no Transfer-/Content-Encoding, and a strict
1..65,536-byte UTF-8 secret. Every violation fails before any intent or vault
effect, and errors never carry secret bytes.
"""

import json

import pytest

from app.api.credential_ingress import (
    MAX_INGRESS_BODY_BYTES,
    CredentialIngressError,
    parse_credential_ingress,
)

INTENT = "00000000-0000-4000-8000-00000000cc01"
SECRET = "sk-ingress-secret-000"


def body_bytes(**overrides):
    payload = {"intent_id": INTENT, "provider": "claude", "secret": SECRET}
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def headers_for(body, *, extra=(), content_length=None):
    length = str(len(body)) if content_length is None else content_length
    return [
        (b"content-type", b"application/json"),
        (b"content-length", length.encode("ascii")),
        *extra,
    ]


def test_create_and_rotate_parse_exactly_once():
    body = body_bytes()
    ingress = parse_credential_ingress(headers_for(body), body)
    assert ingress.intent_id == INTENT
    assert ingress.provider == "claude"
    assert ingress.secret == SECRET.encode("utf-8")
    assert ingress.rotate_from is None

    rotated = body_bytes(rotate_from="0" * 32)
    ingress = parse_credential_ingress(headers_for(rotated), rotated)
    assert ingress.rotate_from == "0" * 32


def test_content_length_must_be_exactly_one_exact_decimal():
    body = body_bytes()
    for headers in (
        [(b"content-type", b"application/json")],  # missing
        headers_for(body, extra=[(b"content-length", str(len(body)).encode())]),
        headers_for(body, content_length="+" + str(len(body))),
        headers_for(body, content_length="0x40"),
        headers_for(body, content_length=" " + str(len(body))),
        headers_for(body, content_length="0" + str(len(body))),  # leading zero
        headers_for(body, content_length=str(len(body) - 1)),  # body mismatch
        headers_for(body, content_length=str(MAX_INGRESS_BODY_BYTES + 1)),
    ):
        with pytest.raises(CredentialIngressError):
            parse_credential_ingress(headers, body)


def test_encoding_headers_fail_before_any_effect():
    body = body_bytes()
    for name, value in (
        (b"transfer-encoding", b"chunked"),
        (b"transfer-encoding", b"identity"),
        (b"content-encoding", b"gzip"),
        (b"content-encoding", b"identity"),
    ):
        with pytest.raises(CredentialIngressError):
            parse_credential_ingress(
                headers_for(body, extra=[(name, value)]), body,
            )


def test_body_shape_is_strict():
    for raw in (
        b"not json",
        json.dumps(["not", "object"]).encode(),
        json.dumps({"intent_id": INTENT, "provider": "claude"}).encode(),
        body_bytes(extra_key=True),
        body_bytes(secret=123),
        body_bytes(secret=""),
        body_bytes(secret="x" * 65_537),
        body_bytes(provider="Bad Provider"),
        json.dumps({
            "intent_id": "nope", "provider": "claude", "secret": SECRET,
        }).encode(),
        body_bytes(rotate_from="not-a-handle"),
    ):
        with pytest.raises(CredentialIngressError):
            parse_credential_ingress(headers_for(raw), raw)


def test_oversized_declared_body_never_reaches_parsing():
    huge = body_bytes(secret="x" * 90_000)  # within secret rejection range but
    assert len(huge) <= MAX_INGRESS_BODY_BYTES  # framed acceptably
    with pytest.raises(CredentialIngressError):
        parse_credential_ingress(headers_for(huge), huge)


def test_errors_never_carry_secret_bytes():
    body = body_bytes(secret="sk-super-sensitive-value")
    broken = body[:-2]  # framing mismatch
    try:
        parse_credential_ingress(headers_for(body), broken)
    except CredentialIngressError as exc:
        assert "sk-super-sensitive-value" not in str(exc)
    bad_provider = body_bytes(provider="NOPE", secret="sk-super-sensitive-value")
    try:
        parse_credential_ingress(headers_for(bad_provider), bad_provider)
    except CredentialIngressError as exc:
        assert "sk-super-sensitive-value" not in str(exc)


def test_content_type_must_be_json():
    body = body_bytes()
    headers = [
        (b"content-type", b"text/plain"),
        (b"content-length", str(len(body)).encode()),
    ]
    with pytest.raises(CredentialIngressError):
        parse_credential_ingress(headers, body)


def test_control_characters_and_surrogates_in_secrets_fail_sanitized():
    for secret in ("sk\nmultiline", "sk\rtoken", "sk\x00token"):
        raw = body_bytes(secret=secret)
        with pytest.raises(CredentialIngressError) as failure:
            parse_credential_ingress(headers_for(raw), raw)
        assert "multiline" not in str(failure.value)
    lone = body_bytes(secret="\ud800")
    with pytest.raises(CredentialIngressError) as failure:
        parse_credential_ingress(headers_for(lone), lone)
    assert "\\ud800" not in str(failure.value)
    assert "\ud800" not in str(failure.value)
