"""The pinned HTTPS transport behind the controlled egress broker (US3, T043
transport half; runtime.md §5-6, R09, FR-014).

`broker_fetch` resolves and judges every hostname itself and hands the transport
the exact public addresses it admitted. This transport connects only to those
addresses — it never resolves a name, never reads proxy environment variables and
never follows a redirect (each hop goes back through the broker's full policy).
TLS is verified against the original hostname: SNI and certificate hostname
checking both use the URL's host, never the pinned address, so a pinned address
serving another name's certificate refuses. The body is read in bounded chunks
and the transfer is abandoned as soon as it would exceed the limit — a declared
Content-Length above the limit refuses before any body is read — so an oversized
response never materializes. Response headers are bounded in count and size.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

from .egress import EgressBrokerError

__all__ = ["make_pinned_transport"]

_CHUNK = 64 * 1024
_MAX_HEADERS = 100
_MAX_HEADER_BYTES = 16 * 1024


class _PinnedConnection(http.client.HTTPSConnection):
    """An HTTPS connection whose socket goes to one pinned address while TLS
    (SNI and certificate hostname) is bound to the URL's hostname."""

    def __init__(self, host, address, port, *, context, timeout):
        super().__init__(host, port, context=context, timeout=timeout)
        self._pinned_address = address

    def connect(self):
        # a literal address only: no name reaches getaddrinfo from here
        family = socket.AF_INET6 if ipaddress.ip_address(self._pinned_address).version == 6 else socket.AF_INET
        raw = socket.socket(family, socket.SOCK_STREAM)
        try:
            raw.settimeout(self.timeout)
            raw.connect((self._pinned_address, self.port))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def make_pinned_transport(*, max_response_bytes, ssl_context=None, timeout=15.0, port=443):
    """A broker transport `(method, url, addresses, headers) -> (status, headers, body)`.

    `ssl_context` defaults to the system trust store with hostname checking on; a
    context that disables verification is refused. `port` exists so tests can
    serve on an unprivileged port; the broker's policy still only admits 443 URLs.
    """

    if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 64 * 1024 * 1024:
        raise EgressBrokerError("max_response_bytes is out of bounds", "invalid_request")
    context = ssl.create_default_context() if ssl_context is None else ssl_context
    if (type(context) is not ssl.SSLContext or context.verify_mode != ssl.CERT_REQUIRED
            or not context.check_hostname):
        raise EgressBrokerError("the transport requires a verifying TLS context")
    if type(timeout) not in (int, float) or not 0 < timeout <= 120:
        raise EgressBrokerError("timeout is out of bounds")
    if type(port) is not int or not 1 <= port <= 65535:
        raise EgressBrokerError("port is out of bounds")

    def transport(method, url, addresses, headers):
        parts = urlsplit(url)
        host = parts.hostname
        if parts.scheme != "https" or not host or not addresses:
            raise EgressBrokerError("the transport needs an https url and pinned addresses", "invalid_request")
        try:
            pinned = tuple(str(ipaddress.ip_address(item)) for item in addresses)
        except (TypeError, ValueError) as exc:
            raise EgressBrokerError("the transport accepts literal pinned addresses only", "dns_denied") from exc
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        last_error = None
        for address in pinned:
            connection = _PinnedConnection(host, address, port, context=context, timeout=timeout)
            try:
                connection.putrequest(method, target, skip_accept_encoding=True)
                for name, value in headers.items():
                    connection.putheader(name, value)
                connection.putheader("Accept-Encoding", "identity")
                connection.endheaders()
                response = connection.getresponse()
                return _read(response, method, max_response_bytes)
            except ssl.SSLCertVerificationError as exc:
                # a pinned address that cannot prove the hostname is never tried around
                raise EgressBrokerError("the destination's certificate does not match its hostname",
                                        "fetch_failed") from exc
            except EgressBrokerError:
                raise  # a bounded read refused: never retried against another address
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc  # unreachable pinned address: try the next pinned one
            finally:
                connection.close()
        raise EgressBrokerError("no pinned address could be reached",
                                "timeout" if isinstance(last_error, TimeoutError) else "fetch_failed") from last_error

    return transport


def _read(response, method, limit):
    header_items = response.getheaders()
    if len(header_items) > _MAX_HEADERS or sum(len(k) + len(v) for k, v in header_items) > _MAX_HEADER_BYTES:
        raise EgressBrokerError("response headers exceed their bounds", "too_large")
    headers = {}
    for name, value in header_items:
        key = name.lower()
        headers[key] = f"{headers[key]}, {value}" if key in headers else value
    declared = headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            raise EgressBrokerError("the response declares an invalid length", "fetch_failed")
        if int(declared) > limit:
            raise EgressBrokerError("response body exceeds the byte limit", "too_large")
    if method == "HEAD":
        return response.status, headers, b""
    body = bytearray()
    while True:
        chunk = response.read(min(_CHUNK, limit + 1 - len(body)))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > limit:
            raise EgressBrokerError("response body exceeds the byte limit", "too_large")
    return response.status, headers, bytes(body)
