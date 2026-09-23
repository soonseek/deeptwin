# T043 slice — pinned HTTPS transport behind the egress broker (2026-09-23)

Status: **transport landed; T043 stays open**. The sandboxed Chromium
navigation/read/screenshot worker and the typed IPC are not built yet, and neither
is the wiring of the broker into runtime tool dispatch.

## What landed

`app/runtime/egress_transport.py` provides `make_pinned_transport(max_response_bytes,
ssl_context=None, timeout, port=443)`. It returns the `(method, url, addresses, headers)`
transport that `broker_fetch` injects.

- **Pinned connection.**
  - It connects only to the literal addresses the broker admitted, through a raw socket
    of the matching family, so no name reaches `getaddrinfo`.
  - A non-literal address refuses.
  - Proxy environment variables are never consulted.
- **TLS bound to the hostname.**
  - SNI and certificate hostname checking use the URL's host, never the pinned address.
  - A context that disables verification is refused at construction.
  - A certificate mismatch refuses outright; it never falls through to another address.
- **No redirect following.** A 3xx is returned to the broker, which re-runs the full
  policy and a fresh pinned resolution for every hop.
- **Byte limit.**
  - A declared Content-Length above the limit refuses before any body is read.
  - Chunked or undeclared bodies are read in bounded chunks and abandoned as soon as they
    would exceed the limit.
  - `Accept-Encoding: identity` is sent, so the limit applies to the actual bytes.
- **Headers.** Response headers are bounded (100 headers, 16 KiB); HEAD reads no body.
- **Fall-through.** An unreachable pinned address falls through only to the other pinned
  addresses.

## Observed

`app/tests/test_egress_transport.py`: **9 passed**, three consecutive runs. It runs against
a local TLS server whose test CA and leaf certificate are made with the `openssl` CLI (the
test skips if openssl is absent). The cases:

- SNI equals the hostname while the socket goes to the pinned 127.0.0.1; `getaddrinfo` is
  patched to fail and `HTTPS_PROXY` is set to a dead proxy.
- A certificate for another name refuses; a non-verifying context and an untrusted CA
  refuse.
- A 302 is returned, not followed.
- A declared oversized body refuses.
- A streamed oversized body is abandoned before the server finished sending.
- HEAD returns no body.
- Pinned fall-through works, and every pinned address unreachable refuses.
- Composed with `broker_fetch`, the transport receives exactly the admitted addresses on
  every redirect hop.

`test_egress_broker.py` still passes: 26.

No live network activity: every connection goes to a loopback test server.
