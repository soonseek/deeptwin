"""Controlled egress broker: typed fetch under a frozen destination policy
(US3, T043 broker half; runtime.md §5-6, R09, FR-014).

Supported HTTP(S) requests become typed broker fetches — never an
unrestricted direct worker fetch. The policy is a frozen issued value:
HTTPS on port 443 only, GET/HEAD only, hostnames from the explicit grant
set with the product's own origin never reachable, no inherited
credentials (URL userinfo and auth/cookie headers refuse), and a bounded
response size. Every hostname is resolved through the injected resolver
and every resolved address must be public — private, loopback, link-local
(cloud metadata included), multicast, reserved and unspecified networks
refuse, and one bad address poisons the whole set. The transport connects
only to the exact addresses the policy check resolved (DNS-rebinding
defense), and every redirect revalidates the full policy with a fresh
pinned resolution under a bounded hop count. Unsupported routes
(http/ws/wss/file/data/…) fail visibly. The resolver and transport are
injected: this module performs no live network activity of its own.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

_METHODS = frozenset({"GET", "HEAD"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_FORBIDDEN_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "cookie2",
})
_MAX_URL_BYTES = 2048
_ISSUE_TOKEN = object()


# the closed refusal codes a broker (or its transport) reports; the browser and fetch
# workers answer exactly these, never a free-form message
EGRESS_CODES = frozenset({
    "grant_denied", "dns_denied", "redirect_denied", "too_large", "timeout",
    "fetch_failed", "invalid_request",
})


class EgressBrokerError(ValueError):
    """A fetch request, resolution, redirect or response violates policy.

    `code` is one of `EGRESS_CODES`: the destination is outside the grant
    (`grant_denied`), a name resolved into a forbidden network or not at all
    (`dns_denied`), a redirect left the grant or the hop budget
    (`redirect_denied`), a body exceeded its limit (`too_large`), the transfer
    timed out (`timeout`), the destination could not be reached or answered
    outside HTTP (`fetch_failed`), or the request itself is malformed
    (`invalid_request`)."""

    def __init__(self, message="egress refused", code="invalid_request"):
        if code not in EGRESS_CODES:
            code = "invalid_request"
        super().__init__(message)
        self.code = code


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


@dataclass(frozen=True, slots=True, init=False)
class EgressPolicy:
    """The frozen destination policy one broker fetch is judged against."""

    granted_hosts: tuple[str, ...]
    product_origins: tuple[str, ...]
    max_redirects: int
    max_response_bytes: int
    _issuer_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, init=False)
class FetchResult:
    """The broker-issued fact of one policy-clean fulfilled fetch."""

    final_url: str
    status: int
    body: bytes
    redirect_chain: tuple[str, ...]
    _issuer_token: object = field(repr=False, compare=False)
    # the final response's declared Content-Type, verbatim (None when absent)
    content_type: str | None = None


def is_issued_fetch_result(value) -> bool:
    return (
        type(value) is FetchResult
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


def _hostname(value, label):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 253
        or value != value.lower()
        or value.strip(".") != value
    ):
        raise EgressBrokerError(f"invalid {label} hostname")
    for part in value.split("."):
        if not part or len(part) > 63:
            raise EgressBrokerError(f"invalid {label} hostname")
        if not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in part):
            raise EgressBrokerError(f"invalid {label} hostname")
    return value


def freeze_egress_policy(
    *, granted_hosts, product_origins, max_redirects, max_response_bytes,
) -> EgressPolicy:
    hosts = tuple(_hostname(host, "granted") for host in granted_hosts)
    origins = tuple(_hostname(origin, "product") for origin in product_origins)
    if not hosts or len(set(hosts)) != len(hosts):
        raise EgressBrokerError("granted hosts must be non-empty and unique")
    if type(max_redirects) is not int or not 1 <= max_redirects <= 10:
        raise EgressBrokerError("max_redirects is out of bounds")
    if (
        type(max_response_bytes) is not int
        or not 1 <= max_response_bytes <= 64 * 1024 * 1024
    ):
        raise EgressBrokerError("max_response_bytes is out of bounds")
    return _issue(
        EgressPolicy,
        granted_hosts=hosts,
        product_origins=origins,
        max_redirects=max_redirects,
        max_response_bytes=max_response_bytes,
        _issuer_token=_ISSUE_TOKEN,
    )


def _admit_url(policy: EgressPolicy, url: str) -> str:
    if type(url) is not str or not 1 <= len(url.encode("utf-8")) <= _MAX_URL_BYTES:
        raise EgressBrokerError("url is out of bounds", "invalid_request")
    # urlsplit strips \t\r\n and tolerates surrounding whitespace, so a
    # policy-clean parse could otherwise hand the transport a raw URL
    # carrying request-line/Host injection. Refuse every control character
    # and space outright — a legal URL percent-encodes them.
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in url):
        raise EgressBrokerError("url carries control characters", "invalid_request")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise EgressBrokerError(
            f"unsupported route: scheme {parts.scheme or '(none)'!r} "
            "is not brokered", "grant_denied",
        )
    if parts.username is not None or parts.password is not None:
        raise EgressBrokerError("url userinfo credentials are forbidden", "grant_denied")
    try:
        port = parts.port
    except ValueError as exc:
        raise EgressBrokerError("invalid url port", "invalid_request") from exc
    if port not in (None, 443):
        raise EgressBrokerError("only port 443 is brokered", "grant_denied")
    host = _hostname(parts.hostname, "destination")
    if host in policy.product_origins:
        raise EgressBrokerError("the product origin is never reachable", "grant_denied")
    if host not in policy.granted_hosts:
        raise EgressBrokerError(f"host {host!r} is outside the grant", "grant_denied")
    return host


def _resolve_public(resolver, host: str) -> tuple[str, ...]:
    addresses = tuple(resolver(host))
    if not addresses:
        raise EgressBrokerError(f"host {host!r} did not resolve", "dns_denied")
    for item in addresses:
        try:
            parsed = ipaddress.ip_address(item)
        except ValueError as exc:
            raise EgressBrokerError(
                f"host {host!r} resolved to a non-address", "dns_denied"
            ) from exc
        # is_global is the single authoritative test: it excludes private,
        # loopback, link-local (cloud metadata), multicast, reserved,
        # unspecified, CGNAT and documentation ranges alike.
        if not parsed.is_global:
            raise EgressBrokerError(
                f"host {host!r} resolved into a forbidden network", "dns_denied"
            )
    return addresses


_HEADER_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")


def _admit_headers(headers) -> dict[str, str]:
    admitted = {}
    for name, value in dict(headers or {}).items():
        if type(name) is not str or type(value) is not str:
            raise EgressBrokerError("headers must be string pairs")
        # A padded or non-token name ("Authorization ") smuggles past the
        # blocklist; a control character in a value injects headers.
        if _HEADER_TOKEN.fullmatch(name) is None:
            raise EgressBrokerError(f"header name {name!r} is not a token")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
            raise EgressBrokerError(
                f"header {name!r} value carries control characters"
            )
        if name.lower() in _FORBIDDEN_HEADERS:
            raise EgressBrokerError(
                f"header {name!r} would inherit credentials"
            )
        admitted[name] = value
    return admitted


def broker_fetch(
    policy: EgressPolicy, method: str, url: str, *,
    resolver, transport, headers=None,
) -> FetchResult:
    if (
        type(policy) is not EgressPolicy
        or getattr(policy, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise EgressBrokerError("a frozen egress policy is required")
    if method not in _METHODS:
        raise EgressBrokerError(f"method {method!r} is not brokered")
    admitted_headers = _admit_headers(headers)
    chain: list[str] = []
    current = url
    while True:
        try:
            host = _admit_url(policy, current)
        except EgressBrokerError as error:
            if not chain:
                raise
            # a hop that leaves the grant is the redirect's refusal, whatever the reason
            raise EgressBrokerError(str(error), "redirect_denied") from None
        addresses = _resolve_public(resolver, host)
        status, response_headers, body = transport(
            method, current, addresses, admitted_headers,
        )
        if type(status) is not int or not 100 <= status <= 599:
            raise EgressBrokerError("transport status is not a valid code", "fetch_failed")
        # EVERY hop's body is bounded, redirect bodies included. The check
        # is necessarily post-materialization at this layer; streaming
        # enforcement mid-transfer belongs to the transport itself.
        if type(body) is not bytes or len(body) > policy.max_response_bytes:
            raise EgressBrokerError("response body exceeds the byte limit", "too_large")
        if status in _REDIRECT_STATUSES:
            location = next(
                (item for name, item in dict(response_headers).items()
                 if type(name) is str and name.lower() == "location"),
                None,
            )
            if location is None:
                raise EgressBrokerError("redirect without a destination", "fetch_failed")
            if len(chain) >= policy.max_redirects:
                raise EgressBrokerError("redirect limit exceeded", "redirect_denied")
            chain.append(current)
            current = urljoin(current, location)
            continue
        return _issue(
            FetchResult,
            final_url=current,
            status=status,
            body=body,
            redirect_chain=tuple(chain),
            _issuer_token=_ISSUE_TOKEN,
            content_type=next(
                (item for name, item in dict(response_headers).items()
                 if type(name) is str and name.lower() == "content-type"
                 and type(item) is str),
                None,
            ),
        )
