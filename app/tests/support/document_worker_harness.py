"""Test-only harness for the document codec channel (T045).

Two shapes, both running the unmodified `DocumentCodecService` over the real frame
codec and the real authenticated handshake of the fixed `cp-document` spec:

- `in_thread_client(...)`: a socketpair per call, the service in a thread (unit tests);
- `python -m app.tests.support.document_worker_harness <socket path>`: the service as a
  SEPARATE PROCESS on a plain AF_UNIX listener, one request per accepted connection; the
  32-byte test boot secret arrives hex-encoded on stdin, `ready` is printed on stdout.
  `process_client(path, secret)` is the matching control-side transport.

The only relaxations against production are the ones the credential gateway's harness
makes: `verify_peer=False` (no SO_PEERCRED, because the test runs everything under one
identity) and a plain socket path instead of the root-initialized pair root with its
readiness record. The root-only qualification in `test_document_worker_main.py` runs the
production entrypoint under the real identities instead.
"""

from __future__ import annotations

import os
import socket
import sys
import threading

from app.workers import broker
from app.workers.document_channel import DocumentCodecClient, document_channel
from app.workers.document_service import DocumentCodecService

REQUESTER_BOOT = "control-boot-document-harness"
RESPONDER_BOOT = "document-boot-document-harness"


def _serve_socket(sock, spec, secret, service, outcomes):
    try:
        session = broker._server_handshake_impl(
            sock, spec, secret, requester_boot_id=REQUESTER_BOOT, responder_boot_id=RESPONDER_BOOT,
            deadline=broker.Deadline.after_ms(10_000), verify_peer=False)
        codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
        from app.workers.gateway_connection import _RawConnection

        connection = _RawConnection(sock, codec)
        try:
            outcomes.append(service.serve_connection(connection,
                                                     deadline=broker.Deadline.after_ms(spec.max_operation_ms)))
        finally:
            connection.close()
    except BaseException as error:  # noqa: BLE001 - recorded by class for the test
        outcomes.append("failed:" + type(error).__name__)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _client_codec(sock, spec, secret):
    session = broker._client_handshake_impl(
        sock, spec, secret, requester_boot_id=REQUESTER_BOOT, responder_boot_id=RESPONDER_BOOT,
        deadline=broker.Deadline.after_ms(10_000), verify_peer=False)
    return broker.FrameCodec(spec, session, local_service=spec.requester_service)


def in_thread_client(*, service=None, deadline_ms=20_000, outcomes=None):
    _root, spec = document_channel()
    secret = broker.BootSecret(b"d" * broker.AUTH_SECRET_BYTES)
    service = DocumentCodecService(spec) if service is None else service
    outcomes = [] if outcomes is None else outcomes
    threads = []

    def factory():
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        thread = threading.Thread(target=_serve_socket, args=(right, spec, secret, service, outcomes),
                                  daemon=True)
        thread.start()
        threads.append(thread)
        return left, _client_codec(left, spec, secret)

    return DocumentCodecClient(factory, deadline_ms=deadline_ms), threads, outcomes


def process_client(path, secret: bytes, *, deadline_ms=20_000):
    _root, spec = document_channel()
    boot = broker.BootSecret(secret)

    def factory():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(5)
            sock.connect(str(path))
            sock.settimeout(None)
            return sock, _client_codec(sock, spec, boot)
        except BaseException:
            sock.close()
            raise

    return DocumentCodecClient(factory, deadline_ms=deadline_ms)


def main() -> int:
    path = sys.argv[1]
    secret = broker.BootSecret(bytes.fromhex(sys.stdin.readline().strip()))
    _root, spec = document_channel()
    service = DocumentCodecService(spec)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    os.chmod(path, 0o600)
    listener.listen(8)
    sys.stdout.write("ready\n")
    sys.stdout.flush()
    outcomes: list = []
    parent = os.getppid()
    listener.settimeout(0.5)
    while True:
        if os.getppid() != parent:
            return 0  # the owning test process is gone: never outlive it
        try:
            connection, _address = listener.accept()
        except TimeoutError:
            continue
        connection.settimeout(None)
        _serve_socket(connection, spec, secret, service, outcomes)
        sys.stderr.write(f"outcome {outcomes[-1]}\n")
        sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
