"""The bounded, deterministic secret scan over raw export content (T074 gap)."""

from app.services import export_secret_scan as scan
from app.services.export_secret_scan import FINDING_KINDS, findings_digest, scan_text

WORK = "11111111-1111-4111-8111-111111111111"


def kinds(text, **kwargs):
    findings, truncated, _ = scan_text(text, **kwargs)
    assert not truncated
    return [(f.kind, f.line, f.column) for f in findings]


def test_common_credential_shapes_are_found_with_kind_and_location_only():
    lines = [
        "plain words, nothing here",
        "anthropic sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
        "other sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX",
        "id AKIAIOSFODNN7EXAMPLE and",
        'AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"',
        "-----BEGIN RSA PRIVATE KEY-----",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
    ]
    text = "\n".join(lines)
    assert kinds(text) == [
        ("anthropic_api_key", 2, 11), ("provider_api_key", 3, 7), ("aws_access_key_id", 4, 4),
        ("aws_secret_access_key", 5, 1), ("private_key_block", 6, 1), ("bearer_token", 7, 16)]
    findings, _, values = scan_text(text)
    for finding in findings:
        assert set(finding.as_dict()) == {"kind", "line", "column"}  # never the matched value
        assert finding.kind in FINDING_KINDS
    assert "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789" in values


def test_near_misses_are_not_findings():
    assert kinds("a task-ant-like word, sk-short, AKIA123, bearer of news, aws_secret_access_key") == []
    assert kinds("BEGIN PUBLIC KEY and ask-ant-api03-abcdefghijklmnopqrstuvwxyz") == []


def test_the_scan_is_deterministic_and_the_digest_binds_the_exact_set():
    text = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123 AKIAIOSFODNN7EXAMPLE"
    first, second = scan_text(text), scan_text(text)
    assert first == second
    one = [{"relative_path": "originals/revision-1.txt", **f.as_dict()} for f in first[0]]
    assert findings_digest(WORK, one) == findings_digest(WORK, list(one))
    assert findings_digest(WORK, one) != findings_digest(WORK, one[:1])
    assert findings_digest(WORK, one) != findings_digest("22222222-2222-4222-8222-222222222222", one)


def test_instance_secrets_are_checked_through_the_callback_only_for_43_character_candidates():
    token = "Q" * 43
    seen = []

    def known(candidate):
        seen.append(candidate)
        return "instance_session_token" if candidate == token else None

    assert kinds(f"x {token} y {'R' * 43} z {'S' * 44}", known=known) == [("instance_session_token", 1, 3)]
    assert seen == [token, "R" * 43]
    assert kinds(f"x {token}") == []  # no callback: no instance check


def test_the_scan_is_bounded(monkeypatch):
    monkeypatch.setattr(scan, "MAX_CANDIDATES", 2)
    text = " ".join(chr(ord("A") + index) * 43 for index in range(4))
    assert kinds(text, known=lambda candidate: None) == [("unscanned_candidates", 1, 89)]
    monkeypatch.setattr(scan, "MAX_TEXT", 10)
    assert kinds("0123456789 sk-ant-api03-abcdefghijklmnopqrstuvwxyz") == [("unscanned_text", 1, 11)]
    monkeypatch.setattr(scan, "MAX_TEXT", 200_000)
    monkeypatch.setattr(scan, "MAX_FINDINGS", 3)
    findings, truncated, values = scan_text("\n".join(["AKIAIOSFODNN7EXAMPLE"] * 5))
    assert len(findings) == 3 and truncated is True and len(values) == 5
