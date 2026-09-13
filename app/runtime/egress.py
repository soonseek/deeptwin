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
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

_METHODS = frozenset({"GET", "HEAD"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_FORBIDDEN_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "cookie2",
})
_MAX_URL_BYTES = 2048
_ISSUE_TOKEN = object()


class EgressBrokerError(ValueError):
    """A fetch request, resolution, redirect or response violates policy."""


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
        raise EgressBrokerError("url is out of bounds")
    if "\x00" in url:
        raise EgressBrokerError("url carries a NUL byte")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise EgressBrokerError(
            f"unsupported route: scheme {parts.scheme or '(none)'!r} "
            "is not brokered"
        )
    if parts.username is not None or parts.password is not None:
        raise EgressBrokerError("url userinfo credentials are forbidden")
    try:
        port = parts.port
    except ValueError as exc:
        raise EgressBrokerError("invalid url port") from exc
    if port not in (None, 443):
        raise EgressBrokerError("only port 443 is brokered")
    host = _hostname(parts.hostname, "destination")
    if host in policy.product_origins:
        raise EgressBrokerError("the product origin is never reachable")
    if host not in policy.granted_hosts:
        raise EgressBrokerError(f"host {host!r} is outside the grant")
    return host


def _resolve_public(resolver, host: str) -> tuple[str, ...]:
    addresses = tuple(resolver(host))
    if not addresses:
        raise EgressBrokerError(f"host {host!r} did not resolve")
    for item in addresses:
        try:
            parsed = ipaddress.ip_address(item)
        except ValueError as exc:
            raise EgressBrokerError(
                f"host {host!r} resolved to a non-address"
            ) from exc
        # is_global is the single authoritative test: it excludes private,
        # loopback, link-local (cloud metadata), multicast, reserved,
        # unspecified, CGNAT and documentation ranges alike.
        if not parsed.is_global:
            raise EgressBrokerError(
                f"host {host!r} resolved into a forbidden network"
            )
    return addresses


def _admit_headers(headers) -> dict[str, str]:
    admitted = {}
    for name, value in dict(headers or {}).items():
        if type(name) is not str or type(value) is not str:
            raise EgressBrokerError("headers must be string pairs")
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
        host = _admit_url(policy, current)
        addresses = _resolve_public(resolver, host)
        status, response_headers, body = transport(
            method, current, addresses, admitted_headers,
        )
        if status in _REDIRECT_STATUSES:
            location = dict(response_headers).get("Location")
            if location is None:
                raise EgressBrokerError("redirect without a destination")
            if len(chain) >= policy.max_redirects:
                raise EgressBrokerError("redirect limit exceeded")
            chain.append(current)
            current = urljoin(current, location)
            continue
        if type(body) is not bytes or len(body) > policy.max_response_bytes:
            raise EgressBrokerError("response body exceeds the byte limit")
        return _issue(
            FetchResult,
            final_url=current,
            status=status,
            body=body,
            redirect_chain=tuple(chain),
            _issuer_token=_ISSUE_TOKEN,
        )
