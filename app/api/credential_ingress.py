"""Wire checks for the explicit credential create/rotate ingress (T090).

The raw secret may cross the control plane exactly once, in bounded no-store
request memory, on its way to the authenticated gateway UDS. Before anything
else — before any intent record and before any vault call — the wire itself must
be exact: exactly one decimal ``Content-Length`` of at most 96 KiB, no
``Transfer-Encoding`` and no ``Content-Encoding`` in any spelling, a strict JSON
object, and a 1..65,536-byte UTF-8 secret. A violation fails closed with a
sanitized error that never carries secret bytes. This module keeps no copy of
the secret beyond the returned value; callers must hand it to the gateway and
drop it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

MAX_INGRESS_BODY_BYTES = 96 * 1024
MAX_SECRET_BYTES = 65_536
_DECIMAL = re.compile(rb"(0|[1-9][0-9]{0,9})\Z")
_PROVIDER = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_HANDLE = re.compile(r"[0-9a-f]{32}\Z")
_FIELDS = frozenset({"intent_id", "provider", "secret"})
_OPTIONAL = frozenset({"rotate_from"})


class CredentialIngressError(ValueError):
    """Sanitized ingress rejection; the message never contains secret bytes."""


@dataclass(frozen=True, slots=True)
class CredentialIngress:
    """One validated create/rotate intent; the secret crosses exactly once."""

    intent_id: str
    provider: str
    secret: bytes = field(repr=False)
    rotate_from: str | None


def parse_credential_ingress(
    raw_headers: list[tuple[bytes, bytes]],
    body: bytes,
) -> CredentialIngress:
    """Validate the exact wire framing and strict body of one ingress request."""

    if type(raw_headers) is not list or any(
        type(item) is not tuple or len(item) != 2
        or type(item[0]) is not bytes or type(item[1]) is not bytes
        for item in raw_headers
    ):
        raise CredentialIngressError("ingress headers are not raw byte pairs")
    if type(body) is not bytes:
        raise CredentialIngressError("ingress body is not bytes")

    lengths = []
    content_types = []
    for name, value in raw_headers:
        lowered = name.lower()
        if lowered in (b"transfer-encoding", b"content-encoding"):
            raise CredentialIngressError(
                "ingress requests may not carry a transfer or content encoding"
            )
        if lowered == b"content-length":
            lengths.append(value)
        if lowered == b"content-type":
            content_types.append(value)
    if len(lengths) != 1:
        raise CredentialIngressError(
            "ingress requests require exactly one content length"
        )
    if _DECIMAL.fullmatch(lengths[0]) is None:
        raise CredentialIngressError("ingress content length is not exact decimal")
    declared = int(lengths[0])
    if declared > MAX_INGRESS_BODY_BYTES:
        raise CredentialIngressError("ingress body exceeds the framing bound")
    if len(body) != declared:
        raise CredentialIngressError("ingress body does not match its framing")
    if (
        len(content_types) != 1
        or content_types[0].split(b";", 1)[0].strip().lower() != b"application/json"
    ):
        raise CredentialIngressError("ingress requests must declare JSON content")

    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CredentialIngressError("ingress body is not strict JSON") from exc
    if type(value) is not dict or not (
        _FIELDS <= set(value) and set(value) <= _FIELDS | _OPTIONAL
    ):
        raise CredentialIngressError("ingress body is not the exact intent object")

    intent_id = value["intent_id"]
    provider = value["provider"]
    secret = value["secret"]
    rotate_from = value.get("rotate_from")
    if type(intent_id) is not str or _UUID.fullmatch(intent_id) is None:
        raise CredentialIngressError("ingress intent id is not a canonical UUID")
    if type(provider) is not str or _PROVIDER.fullmatch(provider) is None:
        raise CredentialIngressError("ingress provider identifier is invalid")
    if type(secret) is not str:
        raise CredentialIngressError("ingress secret is not text")
    try:
        secret_bytes = secret.encode("utf-8")
    except UnicodeEncodeError:
        raise CredentialIngressError("ingress secret is not encodable text") from None
    if not 1 <= len(secret_bytes) <= MAX_SECRET_BYTES:
        raise CredentialIngressError("ingress secret is out of bounds")
    if any(ord(character) < 32 or ord(character) == 127 for character in secret):
        raise CredentialIngressError("ingress secret contains control characters")
    if rotate_from is not None and (
        type(rotate_from) is not str or _HANDLE.fullmatch(rotate_from) is None
    ):
        raise CredentialIngressError("ingress rotation handle is invalid")
    return CredentialIngress(
        intent_id=intent_id,
        provider=provider,
        secret=secret_bytes,
        rotate_from=rotate_from,
    )


__all__ = [
    "MAX_INGRESS_BODY_BYTES",
    "MAX_SECRET_BYTES",
    "CredentialIngress",
    "CredentialIngressError",
    "parse_credential_ingress",
]
