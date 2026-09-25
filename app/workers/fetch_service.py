"""The fetch service's engine (responder of `cp-fetch` and `browser-fetch`, T043).

It runs only inside the fetch service process (`app.workers.fetch_worker_main`, identity
20104, the `fetch-egress` network). It holds the grants control registered — in memory
only, bounded in number, each with a monotonic expiry — and performs each browser fetch
through the egress broker (`app.runtime.egress.broker_fetch`) with the pinned HTTPS
transport (`app.runtime.egress_transport.make_pinned_transport`):

- the URL must be under the grant: for a `navigation`, under one of its source prefixes
  (and so must the final URL after redirects: otherwise `redirect_denied`); for every
  request, its host — and every redirect hop's host — must be a recipient;
- every name is resolved here and every resolved address must be public (one private
  address refuses the whole answer, so a rebinding answer is `dns_denied`); the transport
  connects only to the addresses that check admitted;
- each response is bounded by the grant's per-response limit and by what remains of its
  total byte budget, and the grant's request count is finite; an expired or unknown grant
  refuses (`grant_denied`).

The answer carries only the status, a sanitized content type, the final URL, the redirect
count and the body with its digest — never response headers such as `Set-Cookie`. The
browser's request headers are never forwarded: the broker sends its own fixed `Accept`.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import uuid4

from . import broker
from .fetch_channel import (
    FETCH_BODY_TYPE,
    FETCH_REQUEST_SCHEMA,
    FETCH_REQUEST_TYPE,
    FETCH_RESULT_SCHEMA,
    FETCH_RESULT_TYPE,
    GRANT_REQUEST_SCHEMA,
    GRANT_REQUEST_TYPE,
    GRANT_RESULT_SCHEMA,
    GRANT_RESULT_TYPE,
    KINDS,
    MAX_CONTENT_TYPE,
    MAX_GRANTS,
    BrowserGrant,
    canonical,
    check_grant_id,
    check_hostname,
    check_url,
    chunk_count,
    source_admits,
    strict_object,
    write_chunks,
)

FETCH_TIMEOUT_S = 15.0
_ACCEPT = {"Accept": "text/html,application/xhtml+xml,image/*,text/css,*/*;q=0.5"}


def system_resolver(host: str) -> tuple[str, ...]:
    """Every address the system resolver answers for `host` on 443 (deduplicated)."""

    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return ()
    seen = []
    for _family, _type, _proto, _name, address in answers:
        if address[0] not in seen:
            seen.append(address[0])
    return tuple(seen)


def pinned_transport_factory(max_response_bytes: int):
    from ..runtime.egress_transport import make_pinned_transport

    return make_pinned_transport(max_response_bytes=max_response_bytes, timeout=FETCH_TIMEOUT_S)


class _Refusal(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class _Grant:
    grant: BrowserGrant
    excluded: tuple[str, ...]
    expires: float
    requests: int = 0
    denied: int = 0
    body_bytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


def _content_type(declared) -> str:
    value = declared.strip() if type(declared) is str else ""
    if not value or len(value) > MAX_CONTENT_TYPE or any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in value):
        return "application/octet-stream"
    return value


class FetchService:
    """Serves one request per authenticated connection on either pair."""

    def __init__(self, control_spec: broker.ChannelSpec, browser_spec: broker.ChannelSpec, *,
                 resolver=None, transport_factory=None, clock=time.monotonic) -> None:
        if type(control_spec) is not broker.ChannelSpec or type(browser_spec) is not broker.ChannelSpec:
            raise TypeError("exact channel specs are required")
        self.control_spec, self.browser_spec = control_spec, browser_spec
        # the module's own resolver and pinned transport unless a caller names others
        self._resolver = system_resolver if resolver is None else resolver
        self._transport_factory = pinned_transport_factory if transport_factory is None else transport_factory
        self._clock = clock
        self._grants: dict[str, _Grant] = {}
        self._lock = threading.Lock()

    # --- grants (cp-fetch) ------------------------------------------------------------

    def _purge(self) -> None:
        now = self._clock()
        for key in [key for key, item in self._grants.items() if item.expires <= now]:
            del self._grants[key]

    def register(self, identifier, grant: BrowserGrant, excluded=()) -> str:
        with self._lock:
            self._purge()
            if identifier in self._grants:
                raise _Refusal("invalid_request")
            if len(self._grants) >= MAX_GRANTS:
                raise _Refusal("too_many_grants")
            if any(host in excluded for host in grant.recipients):
                raise _Refusal("grant_denied")
            self._grants[identifier] = _Grant(grant, tuple(excluded), self._clock() + grant.ttl_ms / 1000.0)
        return grant.digest

    def revoke(self, identifier) -> dict:
        with self._lock:
            item = self._grants.pop(identifier, None)
        if item is None:
            raise _Refusal("grant_denied")
        with item.lock:
            return {"requests": item.requests, "denied": item.denied, "body_bytes": item.body_bytes}

    def serve_control(self, connection, *, deadline: broker.Deadline) -> str:
        from .gateway_connection import _require_connection

        _require_connection(connection)
        first = connection.read(deadline=deadline)
        if first.envelope.message_type != GRANT_REQUEST_TYPE or first.envelope.correlation_id is not None:
            raise broker.ProtocolViolation()
        try:
            try:
                value = strict_object(first.payload)
            except (ValueError, UnicodeDecodeError):
                raise _Refusal("invalid_request") from None
            if value.get("schema") != GRANT_REQUEST_SCHEMA:
                raise _Refusal("invalid_request")
            try:
                identifier = check_grant_id(value.get("grant_id"))
            except ValueError:
                raise _Refusal("invalid_request") from None
            if value.get("op") == "register":
                if set(value) - {"excluded_hosts"} != {"schema", "op", "grant_id", "grant"}:
                    raise _Refusal("invalid_request")
                try:
                    grant = BrowserGrant.from_mapping(value["grant"])
                    excluded = value.get("excluded_hosts", [])
                    if type(excluded) is not list or len(excluded) > 8:
                        raise ValueError("excluded hosts")
                    excluded = tuple(check_hostname(item) for item in excluded)
                except (ValueError, TypeError):
                    raise _Refusal("invalid_request") from None
                answer = {"grant_id": identifier, "grant_sha256": self.register(identifier, grant, excluded)}
                outcome = "registered"
            elif value.get("op") == "revoke":
                if set(value) != {"schema", "op", "grant_id"}:
                    raise _Refusal("invalid_request")
                answer = {"grant_id": identifier, "usage": self.revoke(identifier)}
                outcome = "revoked"
            else:
                raise _Refusal("invalid_request")
        except _Refusal as refusal:
            connection.write(message_id=str(uuid4()), correlation_id=first.envelope.message_id,
                             message_type=GRANT_RESULT_TYPE, deadline=deadline,
                             payload=canonical({"schema": GRANT_RESULT_SCHEMA, "ok": False, "code": refusal.code}))
            return refusal.code
        connection.write(message_id=str(uuid4()), correlation_id=first.envelope.message_id,
                         message_type=GRANT_RESULT_TYPE, deadline=deadline,
                         payload=canonical({"schema": GRANT_RESULT_SCHEMA, "ok": True, **answer}))
        return outcome

    # --- fetches (browser-fetch) ------------------------------------------------------

    def fetch(self, identifier, url, kind):
        """One brokered GET under a grant: `(status, final_url, declared content type,
        redirects, body)`, or `_Refusal(code)`."""

        from ..runtime.egress import (
            EgressBrokerError,
            broker_fetch,
            freeze_egress_policy,
        )

        with self._lock:
            self._purge()
            item = self._grants.get(identifier)
        if item is None:
            raise _Refusal("grant_denied")
        grant = item.grant
        with item.lock:
            item.requests += 1
            if item.requests > grant.max_requests:
                item.denied += 1
                raise _Refusal("grant_denied")
            remaining = grant.max_total_bytes - item.body_bytes
        try:
            if kind == "navigation" and not source_admits(grant.sources, url):
                raise _Refusal("grant_denied")
            if remaining <= 0:
                raise _Refusal("too_large")
            limit = min(grant.max_response_bytes, remaining)
            try:
                policy = freeze_egress_policy(granted_hosts=grant.recipients, product_origins=item.excluded,
                                              max_redirects=grant.max_redirects, max_response_bytes=limit)
                result = broker_fetch(policy, "GET", url, resolver=self._resolver,
                                      transport=self._transport_factory(limit), headers=_ACCEPT)
            except EgressBrokerError as error:
                raise _Refusal(error.code) from None
            except Exception:  # noqa: BLE001 - a transport fault is a closed code, never its message
                raise _Refusal("fetch_failed") from None
            if kind == "navigation" and not source_admits(grant.sources, result.final_url):
                raise _Refusal("redirect_denied")
            try:
                final_url = check_url(result.final_url)
            except ValueError:
                raise _Refusal("redirect_denied") from None
        except _Refusal:
            with item.lock:
                item.denied += 1
            raise
        with item.lock:
            item.body_bytes += len(result.body)
            if item.body_bytes > grant.max_total_bytes:  # pragma: no cover - bounded by `limit`
                raise _Refusal("too_large")
        return result.status, final_url, result.content_type, len(result.redirect_chain), result.body

    def serve_browser(self, connection, *, deadline: broker.Deadline) -> str:
        from .gateway_connection import _require_connection

        _require_connection(connection)
        first = connection.read(deadline=deadline)
        if first.envelope.message_type != FETCH_REQUEST_TYPE or first.envelope.correlation_id is not None:
            raise broker.ProtocolViolation()
        correlation = first.envelope.message_id
        try:
            try:
                value = strict_object(first.payload)
                if (set(value) != {"schema", "grant_id", "url", "kind"} or value["schema"] != FETCH_REQUEST_SCHEMA
                        or value["kind"] not in KINDS):
                    raise ValueError("request shape")
                identifier = check_grant_id(value["grant_id"])
                url = value["url"]
                if type(url) is not str:
                    raise ValueError("url")
            except (ValueError, UnicodeDecodeError):
                raise _Refusal("invalid_request") from None
            status, final_url, declared, redirects, body = self.fetch(identifier, url, value["kind"])
            content_type = _content_type(declared)
        except _Refusal as refusal:
            connection.write(message_id=str(uuid4()), correlation_id=correlation, message_type=FETCH_RESULT_TYPE,
                             deadline=deadline,
                             payload=canonical({"schema": FETCH_RESULT_SCHEMA, "ok": False, "code": refusal.code}))
            return refusal.code
        header = {"schema": FETCH_RESULT_SCHEMA, "ok": True, "status": status, "final_url": final_url,
                  "content_type": content_type, "redirects": redirects, "body_bytes": len(body),
                  "body_sha256": sha256(body).hexdigest(), "chunk_count": chunk_count(len(body))}
        connection.write(message_id=str(uuid4()), correlation_id=correlation, message_type=FETCH_RESULT_TYPE,
                         payload=canonical(header), deadline=deadline)
        write_chunks(connection, body, message_type=FETCH_BODY_TYPE, correlation_id=correlation, deadline=deadline)
        return "ok"


__all__ = ["FETCH_TIMEOUT_S", "FetchService", "pinned_transport_factory", "system_resolver"]
