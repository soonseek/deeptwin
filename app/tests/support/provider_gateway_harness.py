"""Test-only harness for the owned shared gateway (Task51; test machinery, never policy).

A real temporary pair root, generation and readiness record, a bound worker
listener, the two generic factories over the explicit platform seams (no
peer credentials, no /proc), accepted/connected owners joined on bounded
threads. The harness fabricates no owner: every connection comes from the
real listener/handshake APIs.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest

from app.workers import broker, ipc_root, listener

ACCEPT_MS = 3_000
CONTROL_BOOT = "control-boot-a"
PROVIDER_BOOT = "provider-boot-a"


def _pair_gid() -> int:
    for value in os.getgroups():
        if value not in {0, os.getegid()}:
            return value
    if os.geteuid() == 0:
        return 21_161
    pytest.skip("a distinct supplemental test group is unavailable")


def gateway_seams(monkeypatch, root, spec):
    """The macOS seams: handshakes without peer credentials, a short socket alias."""

    def server(sock, channel_spec, secret, *, requester_boot_id, responder_boot_id, deadline):
        return broker._server_handshake_impl(
            sock, channel_spec, secret, requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id, deadline=deadline, verify_peer=False)

    def client(sock, channel_spec, secret, *, requester_boot_id, responder_boot_id, deadline):
        return broker._client_handshake_impl(
            sock, channel_spec, secret, requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id, deadline=deadline, verify_peer=False)

    def connect_verified(channel_spec, *, local_service, deadline):
        path = listener._anchored_socket_path(-1, root, channel_spec.socket_name)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(deadline.require())
        sock.connect(path)
        sock.settimeout(None)
        return sock, broker._endpoint_identity(os.stat(path)), None

    monkeypatch.setattr(listener.broker, "server_handshake", server)
    monkeypatch.setattr(listener.broker, "client_handshake", client)
    monkeypatch.setattr(listener.broker, "connect_verified", connect_verified)


@contextmanager
def gateway_pair(tmp_path, monkeypatch):
    """A real pair root with the worker's identities bound to this process."""

    metadata_uid = os.geteuid()
    responder_uid = metadata_uid if metadata_uid != 0 else 21_162
    responder_gid = os.getegid() if os.getegid() != 0 else 21_163
    pair_gid = _pair_gid()
    monkeypatch.setattr(ipc_root, "METADATA_UID", metadata_uid)
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    root = ipc_root.PairRootSpec(pair_root=tmp_path.resolve(), responder_uid=responder_uid,
                                 responder_gid=responder_gid, pair_gid=pair_gid)
    ipc_root.initialize_pair_root(root, entropy=lambda size: b"a" * size)
    spec = broker.ChannelSpec(
        channel_id="cp-provider", requester_service="control", responder_service="provider",
        request_direction="control-to-provider", protocol_id="credential-gateway-v1",
        requester_uid=20_102, requester_gid=20_102, responder_uid=responder_uid,
        responder_gid=responder_gid, pair_gid=pair_gid, pair_root=root.endpoint_path,
        socket_name="worker.sock", root_uid=responder_uid, root_gid=pair_gid,
        socket_uid=responder_uid, socket_gid=pair_gid,
        requester_message_types=("credential_op",), responder_message_types=("credential_result",),
        max_frame_bytes=65_536, max_in_flight=1, max_queue_depth=16, max_operation_ms=30_000,
    )
    monkeypatch.setattr(listener, "_process_identity",
                        lambda: (responder_uid, responder_gid, frozenset({pair_gid})))
    alias_root = None
    if sys.platform != "linux":
        alias_root = Path(tempfile.mkdtemp(prefix="dt-gateway-", dir="/private/tmp"))
        alias = alias_root / "endpoint"
        alias.symlink_to(root.endpoint_path, target_is_directory=True)
        monkeypatch.setattr(listener, "_anchored_socket_path",
                            lambda _fd, _pair, name: str(alias / name))
    else:
        # the test-only fd-less form (-1) addresses the socket by path; real
        # descriptors keep the product's /proc/self/fd anchoring
        anchored = listener._anchored_socket_path
        monkeypatch.setattr(listener, "_anchored_socket_path",
                            lambda fd, pair, name: str(root.endpoint_path / name) if fd == -1
                            else anchored(fd, pair, name))
    gateway_seams(monkeypatch, root, spec)
    try:
        yield root, spec
    finally:
        if alias_root is not None:
            (alias_root / "endpoint").unlink(missing_ok=True)
            alias_root.rmdir()


def accept_in_thread(worker, box, *, deadline_ms=ACCEPT_MS):
    """The worker side accepts one authenticated owner on a bounded thread."""

    def body():
        try:
            box["owner"] = worker.accept_authenticated(
                requester_boot_id=CONTROL_BOOT, deadline=broker.Deadline.after_ms(deadline_ms))
        except BaseException as error:  # noqa: BLE001 - surfaced to the test thread
            box["error"] = error

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread


def connect_owner(root, spec, *, deadline_ms=ACCEPT_MS):
    return listener.connect_authenticated(
        root, spec, requester_boot_id=CONTROL_BOOT, deadline=broker.Deadline.after_ms(deadline_ms))


@contextmanager
def owned_pair(root, spec, *, deadline_ms=ACCEPT_MS):
    """A connected owner on the control side and its accepted owner on the worker
    side, over a real listener; every resource joined and closed on exit."""

    worker = listener.bind_worker_listener(root, spec, responder_boot_id=PROVIDER_BOOT)
    box = {}
    thread = accept_in_thread(worker, box, deadline_ms=deadline_ms)
    client = None
    try:
        client = connect_owner(root, spec, deadline_ms=deadline_ms)
        thread.join(deadline_ms / 1000 + 1)
        assert not thread.is_alive(), "the accept thread did not finish"
        if "error" in box:
            raise box["error"]
        yield client, box["owner"], worker
    finally:
        for resource in (client, box.get("owner"), worker):
            if resource is not None:
                with suppress(Exception):  # teardown must reach every resource
                    resource.close()
        thread.join(1)
        assert not thread.is_alive()


# --- the shared ingress over the real listener (G5–G10) ------------------------------

def fixed_profile_into(monkeypatch, root, spec):
    """Tests may substitute only the module-local profile resolution into an owned temp
    root: the fixed factories themselves expose no override."""
    from app.workers import gateway_channel as profile_module

    monkeypatch.setattr(profile_module, "gateway_channel", lambda: (root, spec))


class ServedIngress:
    """The gateway side: one accepted owner served by the real ingress on a bounded
    thread per call; every thread joined and every owner closed on exit."""

    def __init__(self, ingress, worker, *, deadline_ms=ACCEPT_MS):
        self.ingress, self.worker, self.deadline_ms = ingress, worker, deadline_ms
        self.threads, self.errors = [], []

    def serve(self, count=1):
        """One thread serves `count` owners one after another — the ingress is serial by
        design; a failed dialogue is recorded and the next owner is still served."""
        errors = []

        def body():
            for _ in range(count):
                try:
                    self.ingress.serve_one(self.worker, requester_boot_id=CONTROL_BOOT,
                                           deadline=broker.Deadline.after_ms(self.deadline_ms))
                except BaseException as error:  # noqa: BLE001 - surfaced to the test thread
                    errors.append(error)

        thread = threading.Thread(target=body, daemon=True)
        thread.start()
        self.threads.append((thread, errors))
        return self

    def join(self):
        collected = []
        for thread, errors in self.threads:
            thread.join(self.deadline_ms / 1000 * 3 + 2)
            assert not thread.is_alive(), "an ingress thread did not finish"
            collected.extend(errors)
        self.threads = []
        return collected


@contextmanager
def served_gateway(root, spec, ingress, *, deadline_ms=ACCEPT_MS):
    worker = listener.bind_worker_listener(root, spec, responder_boot_id=PROVIDER_BOOT)
    served = ServedIngress(ingress, worker, deadline_ms=deadline_ms)
    try:
        yield served
    finally:
        leftovers = served.join()
        worker.close()
        for error in leftovers:
            if not isinstance(error, Exception):
                raise error
