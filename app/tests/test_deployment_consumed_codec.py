"""Pure consumed marker parsing is separate from publication and authority."""

import builtins
import hashlib
from base64 import urlsafe_b64encode

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import module


def b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def marker(*, consumed_at="0001-01-01T00:00:00.000Z", outcome="failed"):
    return {
        "schema": "deployment-consumption-v1",
        "domain": "deeptwin-deployment-consumption-v1",
        "consumption_id": "11111111-1111-4111-8111-111111111111",
        "request_id": "22222222-2222-4222-8222-222222222222",
        "request_digest": b64(b"r" * 32),
        "receipt_digest": b64(b"e" * 32),
        "winning_lifecycle_revision": 2,
        "consumed_at": consumed_at,
        "outcome": outcome,
    }


def validate(value, *, selector=None, raw=None):
    return module("receipt_publication").validate_consumed_marker(
        receipt_digest=selector or value.get("receipt_digest", b64(b"e" * 32)),
        payload=raw if raw is not None else canonical_json(value),
    )


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
@pytest.mark.parametrize(
    "timestamp", ["0001-01-01T00:00:00.000Z", "9999-12-31T23:59:59.999Z"]
)
def test_exact_marker_roundtrip_with_calendar_extrema_and_inert_fresh_dict(
    outcome, timestamp
):
    value = marker(consumed_at=timestamp, outcome=outcome)
    raw = canonical_json(value)
    parsed = validate(value, raw=raw)
    assert parsed == value
    assert canonical_json(parsed) == raw
    parsed["outcome"] = "mutated"
    assert validate(value, raw=raw) == value


def test_selector_is_complete_decoded_receipt_digest_not_whole_payload_hash():
    value = marker()
    raw = canonical_json(value)
    assert b64(hashlib.sha256(raw).digest()) != value["receipt_digest"]
    assert validate(value, raw=raw) == value
    with pytest.raises(module("contracts").DeploymentSourceError):
        validate(value, selector=b64(b"f" * 32), raw=raw)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("schema", "deployment-consumption-v2"),
        ("domain", "deeptwin-deployment-consumption-v2"),
        ("consumption_id", "00000000-0000-0000-0000-000000000000"),
        ("request_id", True),
        ("request_digest", "A" * 42 + "B"),
        ("receipt_digest", "A" * 44),
        ("winning_lifecycle_revision", True),
        ("winning_lifecycle_revision", 1),
        ("consumed_at", "2024-02-30T00:00:00.000Z"),
        ("consumed_at", "2024-01-01T00:00:00Z"),
        ("outcome", "succeeded"),
        ("outcome", None),
    ],
)
def test_every_fixed_marker_field_rejects_wrong_value_or_type(field, bad):
    value = marker()
    value[field] = bad
    with pytest.raises(module("contracts").DeploymentSourceError):
        validate(value)


@pytest.mark.parametrize("field", ["nonce", "key_id", "instance_id", "unknown"])
def test_marker_rejects_forbidden_and_unknown_fields_without_reflection(field):
    value = marker()
    value[field] = "attacker-value"
    with pytest.raises(
        module("contracts").DeploymentSourceError,
        match="^deployment_source_invalid$",
    ) as error:
        validate(value)
    assert "attacker-value" not in str(error.value)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b'{"schema":"x","schema":"x"}',
        b"\xef\xbb\xbf{}",
        b"{}\n",
        b"[1]",
        b" " * 4097,
        b'{"winning_lifecycle_revision":2.0}',
    ],
)
def test_marker_rejects_malformed_duplicate_noncanonical_and_bounded_payload(raw):
    value = marker()
    with pytest.raises(module("contracts").DeploymentSourceError):
        validate(value, raw=raw)


def test_marker_rejects_noncanonical_base64_pad_bits_and_selector_type():
    value = marker()
    value["receipt_digest"] = value["receipt_digest"][:-1] + "Z"
    with pytest.raises(module("contracts").DeploymentSourceError):
        validate(value, selector=value["receipt_digest"])
    with pytest.raises(module("contracts").DeploymentSourceError):
        module("receipt_publication").validate_consumed_marker(
            receipt_digest=b"not-text", payload=canonical_json(marker())
        )


def test_marker_codec_performs_no_filesystem_observation(monkeypatch):
    value = marker()
    real_open = builtins.open

    def guarded_open(path, *args, **kwargs):
        if str(path).startswith(("/run/", "/var/lib/")):
            raise AssertionError("filesystem observation")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    assert validate(value) == value
