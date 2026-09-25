"""A bounded, deterministic secret scan over the raw content an export would carry
(US7, T074 gap: raw originals were exported without any secret check).

`scan_text` looks for common credential shapes — provider API keys (`sk-ant-…`,
`sk-…`), AWS access key ids and `aws_secret_access_key=` assignments, PEM private
key blocks and bearer tokens — and, through an optional `known` callback, for the
instance's own secrets that the server can check WITHOUT holding them: a 43-character
base64url candidate is hashed and compared with what the server already stores
(session token digests, the bootstrap capability verifier). No new secret is read.

A finding carries only its closed `kind` and its location (1-based line and column
in characters); the matched text never leaves this module except as the `values`
list the caller may use as manifest canaries. Input and output are bounded: at most
`MAX_TEXT` characters are scanned (a longer text is itself a finding), at most
`MAX_CANDIDATES` instance-secret candidates are checked (the rest is a finding) and
at most `MAX_FINDINGS` findings are reported (the rest is stated as truncated).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from hashlib import sha256

from ..domain.refs import canonical_json

__all__ = ["FINDING_KINDS", "Finding", "findings_digest", "scan_text", "scan_text_spans"]

MAX_TEXT = 200_000
MAX_CANDIDATES = 64
MAX_FINDINGS = 32

FINDING_KINDS = (
    "anthropic_api_key", "provider_api_key", "aws_access_key_id", "aws_secret_access_key",
    "private_key_block", "bearer_token", "instance_session_token", "instance_bootstrap_capability",
    "unscanned_candidates", "unscanned_text",
)

# ordered: an earlier pattern owns its span, so `sk-ant-…` is never also `sk-…`
_PATTERNS = (
    ("private_key_block", re.compile(r"-----BEGIN (?:[A-Z0-9]{1,16} ){0,3}PRIVATE KEY-----")),
    ("anthropic_api_key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{16,256}")),
    ("provider_api_key", re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,256}")),
    ("aws_access_key_id", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("aws_secret_access_key", re.compile(
        r"aws_secret_access_key[\"']?[ \t]{0,8}[:=][ \t]{0,8}[\"']?[^\s\"',;]{8,256}", re.IGNORECASE)),
    ("bearer_token", re.compile(r"\bbearer[ \t]{1,8}[A-Za-z0-9._~+/=-]{16,2048}", re.IGNORECASE)),
)
_CANDIDATE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])")


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str
    line: int
    column: int

    def as_dict(self) -> dict:
        return {"kind": self.kind, "line": self.line, "column": self.column}


def _locator(text):
    starts = [0] + [index + 1 for index, char in enumerate(text) if char == "\n"]

    def locate(offset):
        line = bisect_right(starts, offset)
        return line, offset - starts[line - 1] + 1

    return locate


def scan_text(text: str, *, known=None):
    """(findings, truncated, matched values) for one raw text, deterministically ordered.

    `known(candidate) -> kind | None` checks one 43-character base64url candidate
    against the instance's stored digests; it must not raise for a non-secret."""

    findings, truncated, values, _spans = scan_text_spans(text, known=known)
    return findings, truncated, values


def scan_text_spans(text: str, *, known=None):
    """As `scan_text`, plus each matched value's (start, end) character span in `text`
    (T074: what a redaction must cover). A bound finding (`unscanned_*`) has no span:
    nothing it names was matched, so nothing can be painted over for it."""

    if type(text) is not str:
        raise TypeError("text required")
    locate = _locator(text)
    hits, taken, values = [], [], []
    scanned = text[:MAX_TEXT]
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(scanned):
            start, end = match.span()
            if any(start < other_end and other_start < end for other_start, other_end in taken):
                continue
            taken.append((start, end))
            hits.append((start, kind))
            values.append(match.group(0))
    if known is not None:
        checked = 0
        for match in _CANDIDATE.finditer(scanned):
            start, end = match.span()
            if any(start < other_end and other_start < end for other_start, other_end in taken):
                continue
            if checked == MAX_CANDIDATES:
                hits.append((start, "unscanned_candidates"))
                break
            checked += 1
            kind = known(match.group(0))
            if kind is not None:
                taken.append((start, end))
                hits.append((start, kind))
                values.append(match.group(0))
    if len(text) > MAX_TEXT:
        hits.append((MAX_TEXT, "unscanned_text"))
    hits.sort()
    findings = [Finding(kind, *locate(offset)) for offset, kind in hits]
    return findings[:MAX_FINDINGS], len(findings) > MAX_FINDINGS, values, sorted(taken)


def findings_digest(work_id: str, findings) -> str:
    """The digest the owner's explicit confirmation of an exact finding set binds.
    Revisions are immutable, so each finding's path names exact bytes."""

    return sha256(canonical_json({"work_id": work_id, "findings": list(findings)})).hexdigest()
