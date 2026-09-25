"""Test-only in-thread harness for the browser and fetch channels (T043).

`pair_factory(spec, serve)` returns a transport factory for the frame-only clients: each
call opens a socketpair, runs the real authenticated handshake of the given fixed spec on
both ends (with `verify_peer=False`, because everything runs under one identity — the
same relaxation the document and credential harnesses make) and serves the far end with
`serve(connection, deadline=...)` in a thread. The root-only qualification in
`test_browser_worker.py` runs the production entrypoints under the real identities and
pair roots instead.
"""

from __future__ import annotations

import socket
import threading

from app.workers import broker

REQUESTER_BOOT = "requester-boot-browser-harness"
RESPONDER_BOOT = "responder-boot-browser-harness"


def pair_factory(spec, serve, *, outcomes=None, threads=None, deadline_ms=30_000):
    secret = broker.BootSecret(b"b" * broker.AUTH_SECRET_BYTES)
    outcomes = [] if outcomes is None else outcomes
    threads = [] if threads is None else threads

    def serve_socket(sock):
        from app.workers.gateway_connection import _RawConnection

        try:
            session = broker._server_handshake_impl(
                sock, spec, secret, requester_boot_id=REQUESTER_BOOT, responder_boot_id=RESPONDER_BOOT,
                deadline=broker.Deadline.after_ms(10_000), verify_peer=False)
            connection = _RawConnection(sock, broker.FrameCodec(spec, session, local_service=spec.responder_service))
            try:
                outcomes.append(serve(connection, deadline=broker.Deadline.after_ms(deadline_ms)))
            finally:
                connection.close()
        except BaseException as error:  # noqa: BLE001 - recorded by class for the test
            outcomes.append("failed:" + type(error).__name__)
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def factory():
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        thread = threading.Thread(target=serve_socket, args=(right,), daemon=True)
        thread.start()
        threads.append(thread)
        session = broker._client_handshake_impl(
            left, spec, secret, requester_boot_id=REQUESTER_BOOT, responder_boot_id=RESPONDER_BOOT,
            deadline=broker.Deadline.after_ms(10_000), verify_peer=False)
        return left, broker.FrameCodec(spec, session, local_service=spec.requester_service)

    return factory
