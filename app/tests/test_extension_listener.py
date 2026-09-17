"""Task 25 slice 2c: private extension listener accept/connect and fences
(contracts/extension-worker-probe.md §3/§6; proposal §3).

`_accept_extension_authenticated(listener, *, deadline)` and
`_connect_extension_authenticated(root, spec, *, requester_boot_id, deadline)`
return a private owning `ExtensionConnection`: the accepted/connected
socket, the authenticated session and codec, the borrowed-then-owned
generation, the populated-generation fence, the listener record fence
(readiness bytes/HMAC/socket inode via `_verify_record`) and the mount
fence (slot mount read-only for control, read-write for the worker, no
nested or alias mounts). `recheck()` re-runs every fence; any failure
closes the connection. No serialized observation can recreate it.

macOS honesty: peer credentials, /proc-anchored socket paths and
/proc/self/mountinfo do not exist here. The seamless wrappers are asserted
to fail closed; the flows are exercised through the existing implementation
seams (`verify_peer=False`, a symlinked socket alias, `connect_verified`
returning the connected socket, synthetic mountinfo bytes) — handshake and
fence logic, never positive Linux authentication.
"""

import copy
import dataclasses
import os
import pickle
import socket
import sys
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from app.deployment import mounts as m
from app.workers import broker, ipc_root, listener
from app.workers.extension_channel import extension_channel
from deploy.tests.test_ipc_root_initializer import _pair_gid

INSTANCE = "0123456789abcdef0123456789abcdef"


def open_fds():
    return {int(name) for name in os.listdir("/dev/fd")}


def mountinfo(pair_root: Path, *, read_only: bool, extra=()):
    info = pair_root.stat()
    device = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
    flag = "ro" if read_only else "rw"
    lines = [
        f"1 1 {device} / {pair_root} {flag},relatime shared:1 - tmpfs tmpfs rw",
        *extra,
    ]
    return m.parse_mountinfo(("\n".join(lines) + "\n").encode())


@pytest.fixture
def channel(tmp_path, monkeypatch):
    metadata_uid = os.geteuid()
    responder_uid = metadata_uid if metadata_uid != 0 else 21_162
    responder_gid = os.getegid() if os.getegid() != 0 else 21_163
    pair_gid = _pair_gid()
    monkeypatch.setattr(ipc_root, "METADATA_UID", metadata_uid)
    root = ipc_root.PairRootSpec(
        pair_root=tmp_path.resolve(),
        responder_uid=responder_uid,
        responder_gid=responder_gid,
        pair_gid=pair_gid,
    )
    ipc_root.initialize_pair_root(root, entropy=lambda size: b"a" * size)
    # the extension profile with this test's root, owner and pair group
    _slot_root, profile = extension_channel(instance_id=INSTANCE, slot_number=4)
    spec = dataclasses.replace(
        profile,
        pair_root=root.endpoint_path,
        responder_uid=responder_uid,
        responder_gid=responder_gid,
        pair_gid=pair_gid,
        root_uid=responder_uid,
        root_gid=pair_gid,
        socket_uid=responder_uid,
        socket_gid=pair_gid,
    )
    monkeypatch.setattr(
        listener,
        "_process_identity",
        lambda: (responder_uid, responder_gid, frozenset({pair_gid})),
    )
    alias_root = None
    if sys.platform != "linux":
        alias_root = Path(tempfile.mkdtemp(prefix="dt-ext-", dir="/private/tmp"))
        (alias_root / "endpoint").symlink_to(
            root.endpoint_path, target_is_directory=True
        )
        monkeypatch.setattr(
            listener,
            "_anchored_socket_path",
            lambda _fd, _pair, name: str(alias_root / "endpoint" / name),
        )
    try:
        yield root, spec
    finally:
        if alias_root is not None:
            (alias_root / "endpoint").unlink(missing_ok=True)
            alias_root.rmdir()


def seams(monkeypatch, root, spec):
    """The macOS seams: no peer credentials, no /proc, no mountinfo."""

    def server(sock, channel_spec, secret, *, responder_boot_id, deadline):
        return broker._extension_server_handshake_impl(
            sock,
            channel_spec,
            secret,
            responder_boot_id=responder_boot_id,
            deadline=deadline,
            verify_peer=False,
        )

    def client(
        sock, channel_spec, secret, *, requester_boot_id, responder_boot_id, deadline
    ):
        return broker._extension_client_handshake_impl(
            sock,
            channel_spec,
            secret,
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            deadline=deadline,
            verify_peer=False,
        )

    def connect_verified(channel_spec, *, local_service, deadline):
        path = listener._anchored_socket_path(-1, root, channel_spec.socket_name)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(path)
        return sock, broker._endpoint_identity(os.stat(path)), None

    # the worker thread sees its slot read-write, every other thread (the
    # control side) sees it read-only; a test may claim the worker view for
    # the current thread by setting side["worker_ident"]
    side = {"worker_ident": None}

    def read_mountinfo():
        worker_view = threading.get_ident() == side["worker_ident"]
        return mountinfo(root.pair_root, read_only=not worker_view)

    monkeypatch.setattr(listener.broker, "_extension_server_handshake", server)
    monkeypatch.setattr(listener.broker, "_extension_client_handshake", client)
    monkeypatch.setattr(listener.broker, "connect_verified", connect_verified)
    monkeypatch.setattr(listener, "_read_mountinfo", read_mountinfo)
    return side


def deadline():
    return broker.Deadline.after_ms(3_000)


def accept_in_thread(worker, box, side=None, *, as_worker=True):
    def body():
        if side is not None and as_worker:
            side["worker_ident"] = threading.get_ident()
        try:
            box["connection"] = listener._accept_extension_authenticated(
                worker, deadline=deadline()
            )
        except BaseException as error:  # noqa: BLE001 - surfaced to the test thread
            box["error"] = error

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread


def connect(root, spec, *, requester="control-boot-" + "c" * 20):
    return listener._connect_extension_authenticated(
        root, spec, requester_boot_id=requester, deadline=deadline()
    )


def test_accept_and_connect_yield_owning_connections_with_every_fence(
    channel, monkeypatch
):
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    baseline = open_fds()  # before the listener: everything below is released
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="ext-boot-" + "w" * 24
    )
    box = {}
    thread = accept_in_thread(worker, box, side)
    client = connect(root, spec)
    thread.join(5)
    assert not thread.is_alive()
    assert "error" not in box, box.get("error")
    server = box["connection"]
    try:
        assert type(server) is type(client) is listener.ExtensionConnection
        assert server.session.connection_id == client.session.connection_id
        assert server.session.requester_boot_id == client.session.requester_boot_id
        assert server.record == client.record == worker.record
        assert client.peer is None  # the seam supplies none; a real connect retains it
        # every fence rechecks on demand, on both sides
        side["worker_ident"] = threading.get_ident()
        server.recheck()
        side["worker_ident"] = None
        client.recheck()
        # frames flow under the extension profile types only
        client.write(
            message_id=str(uuid4()),
            correlation_id=None,
            message_type="extension-request-v1",
            payload=b"{}",
            deadline=deadline(),
        )
        frame = server.read(deadline=deadline())
        assert (
            frame.payload == b"{}"
            and frame.envelope.message_type == "extension-request-v1"
        )
        with pytest.raises(broker.BrokerError):
            client.write(
                message_id=str(uuid4()),
                correlation_id=None,
                message_type="execute",
                payload=b"{}",
                deadline=deadline(),
            )
        assert client.closed  # a write failure closes the connection
        for clone in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                clone(server)
        with pytest.raises(TypeError):
            listener.ExtensionConnection()
    finally:
        server.close()
        client.close()
        worker.close()
    assert server.closed and client.closed
    with pytest.raises(broker.TransportClosed):
        server.read(deadline=deadline())
    assert open_fds() == baseline
    # nothing retained: the generation is free for rotation again
    ipc_root.initialize_pair_root(root, entropy=lambda size: b"b" * size)


@pytest.mark.parametrize("who", ["control", "worker"])
def test_the_mount_fence_requires_the_side_specific_mapping(channel, monkeypatch, who):
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="ext-boot-" + "w" * 24
    )
    try:
        if who == "worker":
            # the worker must see its slot read-write: accept without the worker view
            box = {}
            thread = accept_in_thread(worker, box, side, as_worker=False)
            raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                raw.connect(listener._anchored_socket_path(-1, root, spec.socket_name))
                thread.join(5)
            finally:
                raw.close()
            assert type(box.get("error")) is listener.ListenerIntegrityError
        else:
            # control must see its slot read-only: claim the worker view here
            side["worker_ident"] = threading.get_ident()
            with pytest.raises(listener.ListenerIntegrityError):
                listener._connect_extension_authenticated(
                    root,
                    spec,
                    requester_boot_id="control-boot-" + "c" * 20,
                    deadline=deadline(),
                )
    finally:
        worker.close()


@pytest.mark.parametrize("shape", ["nested", "alias", "unmounted"])
def test_nested_alias_or_missing_slot_mounts_are_refused(channel, monkeypatch, shape):
    root, spec = channel
    seams(monkeypatch, root, spec)
    info = root.pair_root.stat()
    device = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
    if shape == "nested":
        extra = (
            f"2 1 {device} /x {root.pair_root / 'endpoint'} ro,relatime - tmpfs tmpfs rw",
        )
        data = mountinfo(root.pair_root, read_only=True, extra=extra)
    elif shape == "alias":
        extra = (
            f"2 1 {device} / {root.pair_root.parent / 'alias'} ro,relatime - tmpfs tmpfs rw",
        )
        data = mountinfo(root.pair_root, read_only=True, extra=extra)
    else:
        data = m.parse_mountinfo(
            f"1 1 {device} / /elsewhere ro,relatime - tmpfs tmpfs rw\n".encode()
        )
    monkeypatch.setattr(listener, "_read_mountinfo", lambda: data)
    with pytest.raises(listener.ListenerIntegrityError):
        listener._extension_mount_fence(root, read_only=True)
    # a good mapping passes and an unreadable mountinfo fails closed
    monkeypatch.setattr(
        listener, "_read_mountinfo", lambda: mountinfo(root.pair_root, read_only=True)
    )
    listener._extension_mount_fence(root, read_only=True)
    with pytest.raises(listener.ListenerIntegrityError):
        listener._extension_mount_fence(root, read_only=False)
    # the compose deployment shape: an overlay root, the kernel pseudo
    # filesystems, docker-managed /etc files and every slot volume on the host
    # state device — the same-device alias clause must not refuse it
    compose = "\n".join(
        [
            "1 1 0:60 / / rw,relatime - overlay overlay rw,lowerdir=/x,upperdir=/y",
            "2 1 0:61 / /proc rw,nosuid - proc proc rw",
            "3 1 0:62 / /dev rw,nosuid - tmpfs tmpfs rw",
            "4 1 0:63 / /sys ro,nosuid - sysfs sysfs ro",
            "5 1 0:64 / /tmp rw,nosuid - tmpfs tmpfs rw",
            "6 1 254:1 /var/lib/docker/containers/c/resolv.conf /etc/resolv.conf rw,relatime - ext4 /dev/vda1 rw",
            "7 1 254:1 /var/lib/docker/volumes/dt-state/_data /var/lib/deeptwin rw,relatime - ext4 /dev/vda1 rw",
            *(
                f"{10 + n} 1 254:1 /var/lib/docker/volumes/dt-i-ipc-xs{n:02}/_data "
                f"/run/deeptwin/ipc/xs{n:02} {'rw' if n == 4 else 'ro'},relatime - ext4 /dev/vda1 rw"
                for n in range(1, 17)
            ),
        ]
    )
    table = m.parse_mountinfo((compose + "\n").encode())
    slot = ipc_root.PairRootSpec(
        pair_root=Path("/run/deeptwin/ipc/xs04"),
        responder_uid=root.responder_uid,
        responder_gid=root.responder_gid,
        pair_gid=root.pair_gid,
    )
    other_slot = dataclasses.replace(slot, pair_root=Path("/run/deeptwin/ipc/xs05"))
    monkeypatch.setattr(listener, "_read_mountinfo", lambda: table)
    listener._extension_mount_fence(slot, read_only=False)  # the worker's own slot
    listener._extension_mount_fence(
        other_slot, read_only=True
    )  # control's view of another
    with pytest.raises(listener.ListenerIntegrityError):
        listener._extension_mount_fence(slot, read_only=True)  # wrong side mapping

    def unavailable():
        raise m.DeploymentSourceUnavailable()

    monkeypatch.setattr(listener, "_read_mountinfo", unavailable)
    with pytest.raises(listener.ListenerIntegrityError):
        listener._extension_mount_fence(root, read_only=True)


def test_rechecks_detect_a_swapped_socket_and_close_the_connection(
    channel, monkeypatch
):
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="ext-boot-" + "w" * 24
    )
    box = {}
    thread = accept_in_thread(worker, box, side)
    client = connect(root, spec)
    thread.join(5)
    server = box["connection"]
    try:
        client.recheck()
        # the socket inode is replaced under the readiness record
        socket_path = root.endpoint_path / spec.socket_name
        socket_path.unlink()
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement.bind(listener._anchored_socket_path(-1, root, spec.socket_name))
        try:
            with pytest.raises(listener.ListenerIntegrityError):
                client.recheck()
            assert client.closed  # a failed fence closes the connection
            side["worker_ident"] = threading.get_ident()  # the worker view, so
            with pytest.raises(listener.ListenerIntegrityError):  # only the swap
                server.recheck()  # can be what the worker side refuses
            assert server.closed
        finally:
            replacement.close()
    finally:
        server.close()
        client.close()
        with pytest.raises(listener.ListenerIntegrityError):
            worker.close()  # the listener refuses to unlink the replacement


def test_accept_refuses_a_recreated_readiness_record_with_identical_bytes(
    channel, monkeypatch
):
    # anyone holding the shared boot secret (control) could rewrite
    # listener.json byte for byte; the accept side compares the readiness
    # file identity it published, not only the record content
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="ext-boot-" + "w" * 24
    )
    try:
        readiness = root.endpoint_path / ipc_root.LISTENER_NAME
        raw = readiness.read_bytes()
        mode = os.stat(readiness).st_mode & 0o7777
        readiness.unlink()
        readiness.write_bytes(raw)
        os.chmod(readiness, mode)
        os.chown(readiness, root.responder_uid, root.pair_gid)
        box = {}
        thread = accept_in_thread(worker, box, side)
        raw_client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            raw_client.connect(
                listener._anchored_socket_path(-1, root, spec.socket_name)
            )
            thread.join(5)
        finally:
            raw_client.close()
        assert type(box.get("error")) is listener.ListenerIntegrityError
    finally:
        with pytest.raises(listener.ListenerIntegrityError):
            worker.close()  # its own readiness inode is gone


def test_the_secret_fence_runs_on_recheck(channel, monkeypatch):
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="ext-boot-" + "w" * 24
    )
    box = {}
    thread = accept_in_thread(worker, box, side)
    client = connect(root, spec)
    thread.join(5)
    server = box["connection"]
    try:
        calls = []
        original = ipc_root.PopulatedGenerationFence.recheck_current

        def spy(self):
            calls.append(self)
            return original(self)

        monkeypatch.setattr(ipc_root.PopulatedGenerationFence, "recheck_current", spy)
        client.recheck()
        side["worker_ident"] = threading.get_ident()
        server.recheck()
        assert len(calls) == 2  # one populated fence per side, rechecked each time

        def failing(self):
            raise ipc_root.IpcRootIntegrityError()

        monkeypatch.setattr(
            ipc_root.PopulatedGenerationFence, "recheck_current", failing
        )
        with pytest.raises(listener.ListenerIntegrityError):
            server.recheck()
        assert server.closed
    finally:
        server.close()
        client.close()
        worker.close()


def test_a_failed_handshake_unwinds_socket_fence_and_generation(channel, monkeypatch):
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    baseline = open_fds()  # before the listener: everything below is released
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="ext-boot-" + "w" * 24
    )
    box = {}
    thread = accept_in_thread(worker, box, side)
    raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        raw.connect(listener._anchored_socket_path(-1, root, spec.socket_name))
        broker.write_packet(raw, {"garbage": True}, deadline())
        thread.join(5)
    finally:
        raw.close()
        worker.close()
    assert not thread.is_alive()
    assert isinstance(box.get("error"), broker.BrokerError)
    assert open_fds() == baseline
    ipc_root.initialize_pair_root(root, entropy=lambda size: b"b" * size)


def test_only_the_extension_profile_is_accepted_before_any_socket(channel, monkeypatch):
    root, spec = channel
    seams(monkeypatch, root, spec)
    other = dataclasses.replace(spec, protocol_id="browser-command-v1")
    with pytest.raises(broker.ChannelConfigurationError):
        listener._connect_extension_authenticated(
            root,
            other,
            requester_boot_id="control-boot-" + "c" * 20,
            deadline=deadline(),
        )
    worker = listener.bind_worker_listener(
        root, other, responder_boot_id="ext-boot-" + "w" * 24
    )
    try:
        with pytest.raises(broker.ChannelConfigurationError):
            listener._accept_extension_authenticated(worker, deadline=deadline())
    finally:
        worker.close()


@pytest.mark.skipif(
    sys.platform == "linux", reason="Linux peer credentials are a separate gate"
)
def test_the_seamless_paths_fail_closed_without_peer_credentials(channel, monkeypatch):
    root, spec = channel
    real_server_wrapper = broker._extension_server_handshake  # before any seam
    real_connect_verified = broker.connect_verified
    side = seams(monkeypatch, root, spec)
    # leave the other seams in place but restore the real server wrapper:
    # its peer verification must refuse before any packet is read
    monkeypatch.setattr(
        listener.broker, "_extension_server_handshake", real_server_wrapper
    )
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="ext-boot-" + "w" * 24
    )
    box = {}
    thread = accept_in_thread(worker, box, side)
    raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        raw.connect(listener._anchored_socket_path(-1, root, spec.socket_name))
        thread.join(5)
        # the requester path with the real connect_verified refuses before any
        # socket, while the listener is still live
        monkeypatch.setattr(listener.broker, "connect_verified", real_connect_verified)
        with pytest.raises(broker.PeerCredentialError):
            listener._connect_extension_authenticated(
                root,
                spec,
                requester_boot_id="control-boot-" + "c" * 20,
                deadline=deadline(),
            )
    finally:
        raw.close()
        worker.close()
    assert type(box.get("error")) is broker.PeerCredentialError


def test_the_private_entry_points_expose_no_seams():
    import inspect

    for name in ("_accept_extension_authenticated", "_connect_extension_authenticated"):
        parameters = inspect.signature(getattr(listener, name)).parameters
        assert "verify_peer" not in parameters and "challenge_factory" not in parameters
