"""Requester ownership, using isolated synthetic roots and real local resources.

The imported channel seams simulate platform observations, not native isolation.
Broker-specific tests below execute the actual broker rather than those seams.
"""

import fcntl
import json
import os
import socket
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.tests.test_extension_listener import (
    accept_in_thread,
    channel,
    connect,
    deadline,
    seams,
)
from app.workers import broker, ipc_root, listener
from app.workers.listener import _anchored_socket_path as real_anchored_socket_path


class ControlStop(BaseException):
    pass


CONTROLS = [KeyboardInterrupt, SystemExit, ControlStop]


def fail(error):
    raise error


def assert_closed(fd):
    with pytest.raises(OSError):
        os.fstat(fd)


def assert_unlocked(root):
    fd = os.open(root.generation_lock_path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def owning_pair(channel, monkeypatch):
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="worker-lifetime")
    box = {}
    thread = accept_in_thread(worker, box, side)
    client = None
    try:
        client = connect(root, spec)
        thread.join(5)
        assert not thread.is_alive()
        assert "error" not in box, box.get("error")
        yield client, box["connection"], worker, side
    finally:
        if client is not None:
            client.close()
        if "connection" in box:
            box["connection"].close()
        worker.close()
        thread.join(5)


def test_generation_returned_ownership_and_repeat_close(channel):
    root, _spec = channel
    lease = ipc_root.acquire_generation(root)
    held = (lease.endpoint_fd, lease.lock_fd, lease.pair_fd)
    assert lease.pair_identity.inode == root.pair_root.stat().st_ino
    assert lease.endpoint_identity.inode == root.endpoint_path.stat().st_ino
    probe = os.open(root.generation_lock_path, os.O_RDONLY)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(probe)
    lease.close()
    lease.close()
    assert lease.closed
    for descriptor in held:
        assert_closed(descriptor)
    assert_unlocked(root)


def test_returned_connection_frames_currentness_and_refusal(channel, monkeypatch):
    wrappers = []
    original_verify = listener.verify_listener
    def verify(*a, **k):
        value = original_verify(*a, **k)
        wrappers.append(value)
        return value
    monkeypatch.setattr(listener, "verify_listener", verify)
    with owning_pair(channel, monkeypatch) as (client, server, worker, _side):
        assert type(client) is listener.ExtensionConnection
        assert client.record == server.record == worker.record
        assert client.session.connection_id == server.session.connection_id
        assert client._fence._generation is client._generation
        assert wrappers[0].generation is client._generation
        wrappers[0].close()
        assert not client._generation.closed
        client.recheck()
        client.write(message_id=str(uuid4()), correlation_id=None,
                     message_type="extension-request-v1", payload=b'{"n":42}',
                     deadline=deadline())
        received = server.read(deadline=deadline())
        assert received.payload == b'{"n":42}'
        assert received.envelope.message_type == "extension-request-v1"
        server.write(message_id=str(uuid4()), correlation_id=received.envelope.message_id,
                     message_type="extension-result-v1", payload=b'{"ok":true}', deadline=deadline())
        assert client.read(deadline=deadline()).payload == b'{"ok":true}'
        codec, generation = client._codec, client._generation  # detached by close
        owned = (client._socket.fileno(), client._fence._secret_fd,
                 client._generation.endpoint_fd, client._generation.lock_fd,
                 client._generation.pair_fd)
        with pytest.raises(broker.ProtocolViolation) as caught:
            client.write(message_id=str(uuid4()), correlation_id=None,
                         message_type="execute", payload=b"{}", deadline=deadline())
        assert caught.value.dispatch_effect == "definitely_not_sent"
        assert client.closed and codec.closed and generation.closed
        client.close()
        for fd in owned:
            assert_closed(fd)
    assert_unlocked(channel[0])


class FdLedger:
    """Track acquisition instances; a reused number gets a new entry."""

    def __init__(self):
        self.entries = []
        self.live = {}
        self.latest = {}
        self.close_fault = None
        self.real_open = os.open
        self.real_close = os.close

    def open(self, path, *args, **kwargs):
        fd = self.real_open(path, *args, **kwargs)
        entry = dict(fd=fd, path=path, attempts=0, live=True)
        self.entries.append(entry)
        self.live[fd] = entry
        self.latest[fd] = entry
        return fd

    def close(self, fd):
        entry = self.latest.get(fd)
        if entry is None:
            return self.real_close(fd)
        entry["attempts"] += 1
        if not entry["live"]:
            return self.real_close(fd)
        fault = self.close_fault(entry) if self.close_fault else None
        if fault is not None and fault[1] == "refuse":
            raise fault[0]
        self.real_close(fd)
        entry["live"] = False
        del self.live[fd]
        if fault is not None:
            raise fault[0]

    def released_once(self):
        assert self.entries
        assert not self.live, self.live
        assert all(e["attempts"] == 1 for e in self.entries), self.entries


@contextmanager
def tracked_fds(monkeypatch):
    ledger = FdLedger()
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", ledger.open)
        patch.setattr(os, "close", ledger.close)
        try:
            yield ledger
        finally:
            # Release only known test acquisitions left by a failing implementation
            # or an intentional close refusal. Never inspect the process FD table.
            for fd in list(ledger.live):
                ledger.real_close(fd)


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("checkpoint", ["layout", "flock", "secret", "endpoint", "boot", "lease"])
def test_acquire_generation_preserves_primary_and_releases_all(channel, monkeypatch, control, checkpoint):
    root, _spec = channel
    primary, secondary = control("acquire"), ControlStop("cleanup")
    with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
        # Only closes during unwind fail, not transient layout traversal closes.
        def trigger(*args, **kwargs):
            ledger.close_fault = lambda entry: (secondary, "release")
            fail(primary)
        if checkpoint in {"layout", "secret", "boot", "lease", "flock"}:
            target, name = {
                "layout": (ipc_root, "_validate_layout"),
                "secret": (ipc_root, "_read_exact_secret"),
                "boot": (broker, "BootSecret"),
                "lease": (ipc_root, "GenerationLease"),
                "flock": (fcntl, "flock"),
            }[checkpoint]
            patch.setattr(target, name, trigger)
        else:
            original = ipc_root._validate_directory
            def validate(fd, **kwargs):
                if ledger.live[fd]["path"] == ipc_root.ENDPOINT_NAME:
                    return trigger()
                return original(fd, **kwargs)
            patch.setattr(ipc_root, "_validate_directory", validate)
        with pytest.raises(BaseException) as caught:
            ipc_root.acquire_generation(root)
        assert caught.value is primary
        ledger.released_once()
    assert_unlocked(root)


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("position", ["unlock", "endpoint", "lock", "pair"])
@pytest.mark.parametrize("behavior", ["release", "refuse"])
def test_generation_close_attempts_every_position_once(channel, monkeypatch, control, position, behavior):
    root, _spec = channel
    primary = control("close")
    with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
        lease = ipc_root.acquire_generation(root)
        owned = dict(endpoint=lease.endpoint_fd, lock=lease.lock_fd, pair=lease.pair_fd)
        original_flock = fcntl.flock
        unlocks = []
        def unlock(fd, flags):
            unlocks.append((fd, flags))
            if position == "unlock":
                if behavior == "release":
                    original_flock(fd, flags)
                fail(primary)
            return original_flock(fd, flags)
        patch.setattr(fcntl, "flock", unlock)
        if position != "unlock":
            ledger.close_fault = lambda e: (primary, behavior) if e["fd"] == owned[position] else None
        with pytest.raises(BaseException) as caught:
            lease.close()
        assert caught.value is primary
        lease.close()
        assert lease.closed
        assert unlocks == [(owned["lock"], fcntl.LOCK_UN)]
        assert all(e["attempts"] == 1 for e in ledger.entries)
        for name, fd in owned.items():
            if name == position and behavior == "refuse":
                os.fstat(fd)
            else:
                assert_closed(fd)
    assert_unlocked(root)


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("stage", ["before_transfer", "initial_recheck", "current_recheck"])
def test_populated_fence_primary_and_borrowed_ownership(channel, monkeypatch, control, stage):
    root, _spec = channel
    generation = ipc_root.acquire_generation(root)
    borrowed = (generation.pair_fd, generation.lock_fd, generation.endpoint_fd)
    primary, secondary = control("fence"), ControlStop("close")
    fence = None
    try:
        with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
            if stage == "current_recheck":
                fence = ipc_root._retain_populated_generation(root, generation)
                retained = fence._secret_fd
                def read(fd):
                    ledger.close_fault = lambda e: (secondary, "release")
                    fail(primary)
                patch.setattr(ipc_root, "_read_exact_secret", read)
                operation = fence.recheck_current
            elif stage == "initial_recheck":
                def initial(self):
                    ledger.close_fault = lambda e: (secondary, "release")
                    fail(primary)
                patch.setattr(ipc_root.PopulatedGenerationFence, "recheck_current", initial)
                operation = lambda: ipc_root._retain_populated_generation(root, generation)
            else:
                original_stat = os.fstat
                def stat(fd):
                    if fd == generation.lock_fd:
                        ledger.close_fault = lambda e: (secondary, "release")
                        fail(primary)
                    return original_stat(fd)
                patch.setattr(os, "fstat", stat)
                operation = lambda: ipc_root._retain_populated_generation(root, generation)
            with pytest.raises(BaseException) as caught:
                operation()
            assert caught.value is primary
            if stage == "current_recheck":
                assert list(ledger.live) == [retained]
                ledger.close_fault = None
                fence.close()
            ledger.released_once()
        assert not generation.closed
        for fd in borrowed:
            os.fstat(fd)
    finally:
        if fence is not None:
            fence.close()
        generation.close()
    assert_unlocked(root)


@pytest.mark.parametrize("control", CONTROLS)
def test_readiness_read_keeps_primary_when_close_fails(channel, monkeypatch, control):
    root, spec = channel
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="readiness-lifetime")
    primary = control("readiness")
    try:
        with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
            def read(*args):
                ledger.close_fault = lambda e: (ControlStop("close"), "release")
                fail(primary)
            patch.setattr(os, "read", read)
            with pytest.raises(BaseException) as caught:
                listener._read_file_at(worker._generation.endpoint_fd,
                                       ipc_root.LISTENER_NAME, worker._readiness_identity)
            assert caught.value is primary
            ledger.released_once()
        os.fstat(worker._generation.endpoint_fd)
    finally:
        worker.close()


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("stage", ["record", "wrapper"])
def test_verify_listener_keeps_generation_through_wrapper(channel, monkeypatch, control, stage):
    root, spec = channel
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="verify-lifetime")
    primary = control("verify")
    try:
        with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
            def trigger(*a, **k):
                ledger.close_fault = lambda e: (ControlStop("close"), "release")
                fail(primary)
            patch.setattr(listener, "_verify_record" if stage == "record" else "VerifiedListener", trigger)
            with pytest.raises(BaseException) as caught:
                listener.verify_listener(root, spec)
            assert caught.value is primary
            ledger.released_once()
        assert not worker._generation.closed
    finally:
        worker.close()
    assert_unlocked(root)


class ClosingSocket:
    """A close-fault seam around one already acquired real socket."""

    def __init__(self, sock, close):
        self.sock, self.close = sock, close

    def __getattr__(self, name):
        return getattr(self.sock, name)


@contextmanager
def connection_close_faults(client, monkeypatch, *, position, error, behavior="release", all_fail=False):
    resources = dict(fence=client._fence, codec=client._codec,
                     socket=client._socket, generation=client._generation)
    calls = []
    with monkeypatch.context() as patch:
        def close(name, original):
            def invoke():
                calls.append(name)
                fault = name == position or all_fail
                if fault and behavior == "refuse":
                    fail(error if name == position else ControlStop(name))
                original()
                if fault:
                    fail(error if name == position else ControlStop(name))
            return invoke
        for name in ("fence", "codec", "generation"):
            instance = resources[name]
            original = type(instance).close
            invoke = close(name, lambda obj=instance, fn=original: fn(obj))
            def patched(self, *, obj=instance, fn=original, invoke=invoke):
                return invoke() if self is obj else fn(self)
            patch.setattr(type(instance), "close", patched)
        client._socket = ClosingSocket(resources["socket"], close("socket", resources["socket"].close))
        try:
            yield calls, resources
        finally:
            client._socket = resources["socket"]
            patch.undo()
            # Refused release leaves real resources to the test owner.
            for resource in resources.values():
                resource.close()


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("position", ["fence", "codec", "socket", "generation"])
@pytest.mark.parametrize("behavior", ["release", "refuse"])
def test_connection_close_all_positions_once(channel, monkeypatch, control, position, behavior):
    with owning_pair(channel, monkeypatch) as (client, _server, _worker, _side):
        primary = control("close")
        with connection_close_faults(client, monkeypatch, position=position,
                                     error=primary, behavior=behavior) as (calls, resources):
            socket_fd = resources["socket"].fileno()
            with pytest.raises(BaseException) as caught:
                client.close()
            assert caught.value is primary
            client.close()
            assert calls == ["fence", "codec", "socket", "generation"]
            assert client.closed
            if position == "socket" and behavior == "refuse":
                os.fstat(socket_fd)
            else:
                assert_closed(socket_fd)
            for name in ("fence", "codec", "generation"):
                assert resources[name].closed is not (position == name and behavior == "refuse")


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("operation", ["recheck", "read", "write"])
def test_connection_operation_primary_survives_all_cleanup(channel, monkeypatch, control, operation):
    with owning_pair(channel, monkeypatch) as (client, _server, _worker, _side):
        primary = control("operation")
        with monkeypatch.context() as patch:
            if operation == "recheck":
                patch.setattr(ipc_root.PopulatedGenerationFence, "recheck_current", lambda self: fail(primary))
                invoke = client.recheck
            elif operation == "read":
                patch.setattr(broker.FrameCodec, "read", lambda *a, **k: fail(primary))
                invoke = lambda: client.read(deadline=deadline())
            else:
                patch.setattr(broker.FrameCodec, "write", lambda *a, **k: fail(primary))
                invoke = lambda: client.write(message_id=str(uuid4()), correlation_id=None,
                    message_type="extension-request-v1", payload=b"{}", deadline=deadline())
            with connection_close_faults(client, monkeypatch, position="fence",
                                         error=ControlStop("secondary"), all_fail=True) as (calls, resources):
                socket_fd = resources["socket"].fileno()
                with pytest.raises(BaseException) as caught:
                    invoke()
                assert caught.value is primary
                assert calls == ["fence", "codec", "socket", "generation"]
                client.close()
                assert len(calls) == 4
                assert_closed(socket_fd)
                assert all(resources[n].closed for n in ("fence", "codec", "generation"))


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("stage", ["handshake", "codec", "connection"])
def test_connector_owns_every_resource_until_return(channel, monkeypatch, control, stage):
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="connector-lifetime")
    primary = control("connector")
    captured, calls, box = {}, [], {}
    originals = dict(verify=listener.verify_listener, fence=ipc_root._retain_populated_generation,
                     connect=broker.connect_verified, handshake=broker._extension_client_handshake,
                     codec=broker.FrameCodec, connection=listener._extension_connection)
    def verify(*a, **k):
        value = originals["verify"](*a, **k)
        captured["verified"] = value
        captured["generation"] = value.generation
        return value
    def fence(*a, **k):
        value = originals["fence"](*a, **k)
        if a[1] is captured.get("generation"):
            captured["fence"] = value
        return value
    def connect_socket(*a, **k):
        value = originals["connect"](*a, **k)
        captured["socket"] = value[0]
        return value
    def handshake(*a, **k):
        if stage == "handshake":
            fail(primary)
        return originals["handshake"](*a, **k)
    def codec(*a, **k):
        if k["local_service"] == spec.requester_service:
            if stage == "codec":
                fail(primary)
            value = originals["codec"](*a, **k)
            captured["codec"] = value
            return value
        return originals["codec"](*a, **k)
    def connection(**k):
        if k["read_only"]:
            fail(primary)
        return originals["connection"](**k)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(listener, "verify_listener", verify)
            patch.setattr(ipc_root, "_retain_populated_generation", fence)
            patch.setattr(broker, "connect_verified", connect_socket)
            patch.setattr(broker, "_extension_client_handshake", handshake)
            patch.setattr(broker, "FrameCodec", codec)
            patch.setattr(listener, "_extension_connection", connection)
            for name, cls in (("fence", ipc_root.PopulatedGenerationFence),
                              ("codec", originals["codec"]), ("generation", ipc_root.GenerationLease)):
                original_close = cls.close
                def close(self, *, name=name, original=original_close):
                    if self is captured.get(name):
                        calls.append(name)
                        original(self)
                        fail(ControlStop("secondary-" + name))
                    return original(self)
                patch.setattr(cls, "close", close)
            thread = accept_in_thread(worker, box, side)
            with pytest.raises(BaseException) as caught:
                connect(root, spec)
            thread.join(5)
            assert not thread.is_alive()
            assert caught.value is primary
            assert captured["socket"].fileno() == -1
            expected = ["fence", "generation"] if stage != "connection" else ["fence", "codec", "generation"]
            assert sorted(calls) == sorted(expected)
            assert captured["generation"].closed and captured["fence"].closed
            if stage == "connection":
                assert captured["codec"].closed
            captured["verified"].close()
            assert len(calls) == len(expected)
    finally:
        # Finite captured ownership only, also cleans up the intentionally red path.
        for name in ("socket", "fence", "codec", "generation"):
            if name in captured:
                captured[name].close()
        if "connection" in box:
            box["connection"].close()
        worker.close()
    assert_unlocked(root)


class ModuleView:
    def __init__(self, module, **overrides):
        self.module, self.overrides = module, overrides

    def __getattr__(self, name):
        return self.overrides[name] if name in self.overrides else getattr(self.module, name)


@contextmanager
def direct_broker(channel, monkeypatch):
    """Only /proc addressing and native peer observations are simulated.

    Production connect_verified, _open_root, endpoint checks, socket validation,
    deadlines, actual Unix connect and timeout reset all execute.
    """
    root, spec = channel
    native_socket, native_stat, native_fstat = socket.socket, os.stat, os.fstat
    state, sockets = {}, []
    primary = None
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="broker-lifetime")
    try:
        actual_path = listener._anchored_socket_path(worker._endpoint_fd, root, spec.socket_name)
        class LocalSocket(native_socket):
            def __new__(cls, *a, **k):
                if state.get("checkpoint") == "socket_create":
                    fail(state["primary"])
                return super().__new__(cls, *a, **k)

            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.close_attempts = 0
                sockets.append(self)

            def set_inheritable(self, value):
                if state.get("checkpoint") == "socket_validate":
                    fail(state["primary"])
                return super().set_inheritable(value)

            def settimeout(self, value):
                checkpoint = "reset" if value is None else "timeout"
                if state.get("checkpoint") == checkpoint:
                    fail(state["primary"])
                return super().settimeout(value)

            def connect(self, path):
                assert path.startswith("/proc/self/fd/") and path.endswith("/" + spec.socket_name)
                if state.get("checkpoint") == "connect":
                    fail(state["primary"])
                return super().connect(actual_path)

            def close(self):
                self.close_attempts += 1
                fault = state.get("socket_close")
                if fault and state.get("refuse_socket"):
                    fail(fault)
                super().close()
                if fault:
                    fail(fault)

        def proc_stat(path, *a, **k):
            if str(path).startswith("/proc/self/fd/"):
                if state.get("checkpoint") == "proc":
                    fail(state["primary"])
                return native_fstat(int(str(path).rsplit("/", 1)[1]))
            return native_stat(path, *a, **k)

        def peer(sock):
            assert sock in sockets
            if state.get("checkpoint") == "peer":
                fail(state["primary"])
            return broker.PeerCredentials(pid=123, uid=spec.responder_uid, gid=spec.responder_gid)

        with monkeypatch.context() as patch:
            patch.setattr(broker, "sys", SimpleNamespace(platform="linux"))
            patch.setattr(broker, "socket", ModuleView(socket, socket=LocalSocket, SO_PEERCRED=17))
            patch.setattr(broker, "os", ModuleView(os, stat=proc_stat))
            patch.setattr(broker, "peer_credentials", peer)
            yield spec, worker, state, sockets
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_error = None
        for sock in sockets:
            try:
                native_socket.close(sock)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        try:
            worker.close()
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
        if primary is None and cleanup_error is not None:
            raise cleanup_error


def test_actual_broker_returns_only_socket_and_preserves_endpoint(channel, monkeypatch):
    with direct_broker(channel, monkeypatch) as (spec, worker, _state, sockets):
        with tracked_fds(monkeypatch) as ledger:
            sock, endpoint, peer = broker.connect_verified(
                spec, local_service=spec.requester_service, deadline=deadline())
            ledger.released_once()
            assert sock is sockets[0]
            assert sock.gettimeout() is None
            assert (endpoint.device, endpoint.inode) == (worker.record.socket.device, worker.record.socket.inode)
            assert (peer.pid, peer.uid, peer.gid) == (123, spec.responder_uid, spec.responder_gid)
            # Transport bytes actually cross the locally connected Unix sockets.
            accepted, _ = worker._socket.accept()
            try:
                sock.sendall(b"owned")
                assert accepted.recv(5) == b"owned"
            finally:
                accepted.close()
            sock.close()
            assert sock.close_attempts == 1


@pytest.mark.parametrize("refusal", ["mode", "peer", "deadline", "symlink"])
def test_actual_broker_normal_refusal(channel, monkeypatch, refusal):
    root, _ = channel
    with direct_broker(channel, monkeypatch) as (spec, _worker, state, sockets):
        if refusal == "mode":
            os.chmod(root.socket_path(spec.socket_name), 0o600)
            expected = broker.EndpointViolation
        elif refusal == "symlink":
            # A no-follow root alias must be refused even when it targets the same root.
            import dataclasses
            alias = root.pair_root / "endpoint-alias"
            alias.symlink_to(root.endpoint_path, target_is_directory=True)
            spec = dataclasses.replace(spec, pair_root=alias)
            expected = broker.EndpointViolation
        elif refusal == "peer":
            state.update(checkpoint="peer", primary=broker.PeerCredentialError())
            expected = broker.PeerCredentialError
        else:
            expected = broker.DeadlineExceeded
        with tracked_fds(monkeypatch) as ledger:
            with pytest.raises(expected):
                broker.connect_verified(spec, local_service=spec.requester_service,
                    deadline=broker.Deadline(0.5) if refusal == "deadline" else deadline())
            if ledger.entries:
                ledger.released_once()
            assert all(sock.fileno() == -1 for sock in sockets)
        if refusal == "mode":
            os.chmod(root.socket_path(spec.socket_name), spec.socket_mode)
        if refusal == "symlink":
            alias.unlink()


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("stage", ["child_open", "parent_close", "final_stat"])
@pytest.mark.parametrize("behavior", ["release", "refuse"])
def test_broker_root_tracks_child_before_parent_release(channel, monkeypatch, control, stage, behavior):
    root, spec = channel
    primary, secondary = control("root"), ControlStop("cleanup")
    borrowed = os.open(root.pair_root, os.O_RDONLY)
    try:
        with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
            def fault(entry):
                if stage == "parent_close" and entry["path"] == os.sep:
                    return primary, behavior
                if stage != "parent_close" or entry["path"] != os.sep:
                    return secondary, "release"
            if stage == "child_open":
                def open_child(path, *a, **k):
                    if "dir_fd" in k:
                        ledger.close_fault = fault
                        fail(primary)
                    return ledger.open(path, *a, **k)
                patch.setattr(os, "open", open_child)
            elif stage == "parent_close":
                ledger.close_fault = fault
            else:
                original_stat = os.fstat
                def final_stat(fd):
                    if ledger.live.get(fd, {}).get("path") == spec.pair_root.name:
                        ledger.close_fault = fault
                        fail(primary)
                    return original_stat(fd)
                patch.setattr(os, "fstat", final_stat)
            with pytest.raises(BaseException) as caught:
                broker._open_root(spec)
            assert caught.value is primary
            assert all(e["attempts"] == 1 for e in ledger.entries), ledger.entries
            refused = [e for e in ledger.entries if e["live"]]
            if stage == "parent_close" and behavior == "refuse":
                assert len(refused) == 1 and refused[0]["path"] == os.sep
                os.fstat(refused[0]["fd"])
            else:
                assert not refused
            os.fstat(borrowed)
    finally:
        os.close(borrowed)


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("stage", ["endpoint_before", "proc", "socket_create", "socket_validate",
                                   "timeout", "connect", "endpoint_after", "peer", "reset"])
def test_actual_broker_failure_closes_socket_and_root_preserving_primary(channel, monkeypatch, control, stage):
    primary = control("connect")
    with direct_broker(channel, monkeypatch) as (spec, _worker, state, sockets):
        state.update(checkpoint=stage, primary=primary, socket_close=ControlStop("socket-close"))
        with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
            endpoint_calls = []
            original_endpoint = broker._validate_endpoint_at
            def endpoint(fd, channel_spec):
                endpoint_calls.append(fd)
                if (stage == "endpoint_before" and len(endpoint_calls) == 1
                        or stage == "endpoint_after" and len(endpoint_calls) == 2):
                    fail(primary)
                return original_endpoint(fd, channel_spec)
            patch.setattr(broker, "_validate_endpoint_at", endpoint)
            ledger.close_fault = lambda e: (ControlStop("root-close"), "release") if e["path"] == spec.pair_root.name else None
            with pytest.raises(BaseException) as caught:
                broker.connect_verified(spec, local_service=spec.requester_service, deadline=deadline())
            assert caught.value is primary
            ledger.released_once()
            expected_socket = stage not in {"endpoint_before", "proc", "socket_create"}
            assert len(sockets) == int(expected_socket)
            for sock in sockets:
                assert sock.close_attempts == 1
                assert sock.fileno() == -1


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("behavior", ["release", "refuse"])
def test_actual_broker_root_cleanup_cannot_lose_successful_socket(channel, monkeypatch, control, behavior):
    primary = control("root-close")
    with direct_broker(channel, monkeypatch) as (spec, _worker, state, sockets):
        state["socket_close"] = ControlStop("socket-close")
        with tracked_fds(monkeypatch) as ledger:
            ledger.close_fault = lambda e: (primary, behavior) if e["path"] == spec.pair_root.name else None
            with pytest.raises(BaseException) as caught:
                broker.connect_verified(spec, local_service=spec.requester_service, deadline=deadline())
            assert caught.value is primary
            assert len(sockets) == 1 and sockets[0].fileno() == -1
            assert sockets[0].close_attempts == 1
            assert all(e["attempts"] == 1 for e in ledger.entries)
            if behavior == "refuse":
                assert len(ledger.live) == 1
                os.fstat(next(iter(ledger.live)))
            else:
                ledger.released_once()


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("stage", ["locked_layout", "owned_endpoint", "secret_close"])
def test_late_generation_checkpoints_release_all(channel, monkeypatch, control, stage):
    root, _spec = channel
    primary = control("late-acquire")
    with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
        original_layout, original_read = ipc_root._validate_layout, ipc_root._read_exact_secret
        original_validate = ipc_root._validate_directory
        state = {"layout": 0, "read": False}
        def trigger():
            ledger.close_fault = lambda e: (ControlStop("cleanup"), "release")
            fail(primary)
        def layout(*a, **k):
            state["layout"] += 1
            if stage == "locked_layout" and state["layout"] == 2:
                trigger()
            return original_layout(*a, **k)
        def read(fd):
            value = original_read(fd)
            state["read"] = True
            if stage == "secret_close":
                ledger.close_fault = lambda e: (primary if e["fd"] == fd else ControlStop("cleanup"), "release")
            return value
        def validate(fd, **k):
            if stage == "owned_endpoint" and state["read"]:
                trigger()
            return original_validate(fd, **k)
        patch.setattr(ipc_root, "_validate_layout", layout)
        patch.setattr(ipc_root, "_read_exact_secret", read)
        patch.setattr(ipc_root, "_validate_directory", validate)
        with pytest.raises(BaseException) as caught:
            ipc_root.acquire_generation(root)
        assert caught.value is primary
        ledger.released_once()
    assert_unlocked(root)


@pytest.mark.parametrize("control", CONTROLS)
def test_aggregate_close_raises_first_of_multiple_failures(channel, monkeypatch, control):
    primary = control("first")
    root, _ = channel
    with tracked_fds(monkeypatch) as ledger:
        generation = ipc_root.acquire_generation(root)
        endpoint = generation.endpoint_fd
        ledger.close_fault = lambda e: (primary if e["fd"] == endpoint else ControlStop("later"), "release")
        with pytest.raises(BaseException) as caught:
            generation.close()
        assert caught.value is primary
        generation.close()
        ledger.released_once()
    with owning_pair(channel, monkeypatch) as (client, _server, _worker, _side):
        with connection_close_faults(client, monkeypatch, position="fence", error=primary,
                                     all_fail=True) as (calls, _resources):
            with pytest.raises(BaseException) as caught:
                client.close()
            assert caught.value is primary
            client.close()
            assert calls == ["fence", "codec", "socket", "generation"]


@pytest.mark.parametrize("stage", ["secret", "readiness", "fence"])
@pytest.mark.parametrize("kind", ["os", "domain"])
def test_file_and_fence_ordinary_errors_keep_mapping(channel, monkeypatch, stage, kind):
    root, spec = channel
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="mapping-lifetime")
    domain = listener.ListenerIntegrityError if stage == "readiness" else ipc_root.IpcRootIntegrityError
    primary = OSError("synthetic") if kind == "os" else domain()
    fence = None
    try:
        with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
            if stage == "fence":
                fence = ipc_root._retain_populated_generation(root, worker._generation)
                invoke = fence.recheck_current
            elif stage == "readiness":
                invoke = lambda: listener._read_file_at(worker._generation.endpoint_fd,
                    ipc_root.LISTENER_NAME, worker._readiness_identity)
            else:
                invoke = lambda: ipc_root.acquire_generation(root)
            def trigger(*a, **k):
                ledger.close_fault = lambda e: (ControlStop("cleanup"), "release")
                fail(primary)
            patch.setattr(os if stage == "readiness" else ipc_root,
                          "read" if stage == "readiness" else "_read_exact_secret", trigger)
            with pytest.raises(domain) as caught:
                invoke()
            if kind == "domain":
                assert caught.value is primary
            if fence is not None:
                ledger.close_fault = None
                fence.close()
            ledger.released_once()
    finally:
        if fence is not None:
            fence.close()
        worker.close()


@pytest.mark.parametrize("operation", ["recheck_os", "recheck_ipc", "recheck_listener", "read", "write"])
def test_connection_ordinary_error_mapping_and_dispatch_effect(channel, monkeypatch, operation):
    with owning_pair(channel, monkeypatch) as (client, _server, _worker, _side):
        primary = {
            "recheck_os": OSError("synthetic"),
            "recheck_ipc": ipc_root.IpcRootIntegrityError(),
            "recheck_listener": listener.ListenerIntegrityError(),
            "read": broker.TransportUncertain(dispatch_effect="outcome_unknown"),
            "write": broker.TransportUncertain(dispatch_effect="may_have_started"),
        }[operation]
        with monkeypatch.context() as patch:
            if operation.startswith("recheck"):
                patch.setattr(ipc_root.PopulatedGenerationFence, "recheck_current", lambda self: fail(primary))
                invoke, expected = client.recheck, listener.ListenerIntegrityError
            elif operation == "read":
                patch.setattr(broker.FrameCodec, "read", lambda *a, **k: fail(primary))
                invoke, expected = lambda: client.read(deadline=deadline()), broker.TransportUncertain
            else:
                patch.setattr(broker.FrameCodec, "write", lambda *a, **k: fail(primary))
                invoke = lambda: client.write(message_id=str(uuid4()), correlation_id=None,
                    message_type="extension-request-v1", payload=b"{}", deadline=deadline())
                expected = broker.TransportUncertain
            with connection_close_faults(client, monkeypatch, position="fence",
                                         error=ControlStop("cleanup"), all_fail=True) as (calls, _resources):
                with pytest.raises(expected) as caught:
                    invoke()
                if operation not in {"recheck_os", "recheck_ipc"}:
                    assert caught.value is primary
                assert calls == ["fence", "codec", "socket", "generation"]


@pytest.mark.parametrize("inside", [False, True])
def test_connector_preserves_verification_ipc_boundary(channel, monkeypatch, inside):
    root, spec = channel
    primary = ipc_root.IpcRootIntegrityError()
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="boundary-lifetime")
    try:
        with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
            def trigger(*a, **k):
                ledger.close_fault = lambda e: (ControlStop("cleanup"), "release")
                fail(primary)
            patch.setattr(ipc_root if inside else listener,
                          "_retain_populated_generation" if inside else "verify_listener", trigger)
            with pytest.raises(listener.ListenerIntegrityError if inside else ipc_root.IpcRootIntegrityError) as caught:
                connect(root, spec)
            if not inside:
                assert caught.value is primary
                assert not ledger.entries
            else:
                ledger.released_once()
    finally:
        worker.close()


@pytest.mark.parametrize("kind", ["os", "timeout", "broker"])
def test_actual_broker_ordinary_errors_keep_mapping_and_cleanup(channel, monkeypatch, kind):
    primary = {"os": OSError("synthetic"), "timeout": TimeoutError("synthetic"),
               "broker": broker.TransportUncertain(dispatch_effect="may_have_started")}[kind]
    with direct_broker(channel, monkeypatch) as (spec, _worker, state, sockets):
        state.update(checkpoint="connect", primary=primary, socket_close=ControlStop("socket-close"))
        with tracked_fds(monkeypatch) as ledger:
            ledger.close_fault = lambda e: (ControlStop("root-close"), "release") if e["path"] == spec.pair_root.name else None
            with pytest.raises(broker.TransportUncertain if kind == "broker" else broker.TransportClosed) as caught:
                broker.connect_verified(spec, local_service=spec.requester_service, deadline=deadline())
            if kind == "broker":
                assert caught.value is primary
            else:
                assert caught.value.dispatch_effect == "definitely_not_sent"
                assert caught.value.__cause__ is None
                assert caught.value.__context__ is None
            ledger.released_once()
            assert len(sockets) == 1 and sockets[0].fileno() == -1
            assert sockets[0].close_attempts == 1


def test_generation_oserror_close_policy_stays_suppressed(channel, monkeypatch):
    root, _ = channel
    with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
        generation = ipc_root.acquire_generation(root)
        original = fcntl.flock
        def unlock(fd, flags):
            original(fd, flags)
            raise OSError("synthetic unlock")
        patch.setattr(fcntl, "flock", unlock)
        ledger.close_fault = lambda e: (OSError("synthetic close"), "release")
        generation.close()
        generation.close()
        ledger.released_once()
    assert_unlocked(root)


def test_broker_socket_oserror_close_policy_stays_suppressed(channel, monkeypatch):
    primary = broker.PeerCredentialError()
    with direct_broker(channel, monkeypatch) as (spec, _worker, state, sockets):
        state.update(checkpoint="peer", primary=primary, socket_close=OSError("synthetic close"))
        with tracked_fds(monkeypatch) as ledger:
            ledger.close_fault = lambda e: (OSError("synthetic close"), "release")
            with pytest.raises(broker.PeerCredentialError) as caught:
                broker.connect_verified(spec, local_service=spec.requester_service, deadline=deadline())
            assert caught.value is primary
            ledger.released_once()
            assert len(sockets) == 1 and sockets[0].fileno() == -1
            assert sockets[0].close_attempts == 1


@pytest.mark.parametrize("kind", ["os", "metadata"])
def test_broker_root_validation_error_survives_cleanup(channel, monkeypatch, kind):
    root, spec = channel
    with tracked_fds(monkeypatch) as ledger, monkeypatch.context() as patch:
        original = os.fstat
        def stat(fd):
            info = original(fd)
            if ledger.live.get(fd, {}).get("path") == spec.pair_root.name:
                ledger.close_fault = lambda e: (ControlStop("cleanup"), "release")
                if kind == "os":
                    raise OSError("synthetic stat")
                info = SimpleNamespace(st_mode=0, st_uid=info.st_uid, st_gid=info.st_gid)
            return info
        patch.setattr(os, "fstat", stat)
        with pytest.raises(broker.EndpointViolation) as caught:
            broker._open_root(spec)
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        ledger.released_once()
    assert_unlocked(root)


@pytest.mark.parametrize("control", CONTROLS)
def test_actual_broker_refused_socket_close_still_attempts_root(channel, monkeypatch, control):
    primary = control("peer")
    with direct_broker(channel, monkeypatch) as (spec, _worker, state, sockets):
        state.update(checkpoint="peer", primary=primary, socket_close=ControlStop("refused"), refuse_socket=True)
        with tracked_fds(monkeypatch) as ledger:
            ledger.close_fault = lambda e: (ControlStop("root-close"), "release") if e["path"] == spec.pair_root.name else None
            with pytest.raises(BaseException) as caught:
                broker.connect_verified(spec, local_service=spec.requester_service, deadline=deadline())
            assert caught.value is primary
            ledger.released_once()
            assert len(sockets) == 1 and sockets[0].close_attempts == 1
            # A refused close proves the attempt, not kernel release.
            os.fstat(sockets[0].fileno())


def test_readiness_content_continuity_is_not_inode_continuity(channel, monkeypatch):
    root, _ = channel
    with owning_pair(channel, monkeypatch) as (client, _server, _worker, _side):
        readiness = root.listener_path
        original = root.endpoint_path / "saved-readiness"
        raw, info = readiness.read_bytes(), readiness.stat()
        readiness.rename(original)
        try:
            readiness.write_bytes(raw)
            os.chmod(readiness, info.st_mode & 0o7777)
            os.chown(readiness, info.st_uid, info.st_gid)
            assert readiness.stat().st_ino != info.st_ino
            client.recheck()
            assert not client.closed
            record = json.loads(raw)
            record["hmac_sha256"] = "0" * 64 if record["hmac_sha256"] != "0" * 64 else "1" * 64
            readiness.write_bytes(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
            owned_socket = client._socket  # detached by the close the recheck performs
            with pytest.raises(listener.ListenerIntegrityError):
                client.recheck()
            assert client.closed and owned_socket.fileno() == -1
        finally:
            readiness.unlink()
            original.rename(readiness)


def test_direct_broker_setup_uses_owned_endpoint_for_actual_anchor(channel, monkeypatch):
    root, spec = channel
    original_bind = listener.bind_worker_listener
    captured, observed = {}, []

    def anchored(fd, pair_root, name):
        observed.append(fd)
        # Execute the actual platform-gated helper using only synthetic proc
        # observation. Its fstat still validates a real currently owned FD.
        def proc_stat(path, *, follow_symlinks):
            assert path == f"/proc/self/fd/{fd}" and follow_symlinks
            return os.fstat(fd)
        with monkeypatch.context() as patch:
            patch.setattr(listener, "sys", SimpleNamespace(platform="linux"))
            patch.setattr(listener, "os", ModuleView(os, O_PATH=0, stat=proc_stat))
            return real_anchored_socket_path(fd, pair_root, name)

    def bind(*args, **kwargs):
        worker = original_bind(*args, **kwargs)
        captured["worker"] = worker
        captured["fds"] = (worker._socket.fileno(), worker._endpoint_fd,
            worker._listener_lock_fd, worker._generation.endpoint_fd,
            worker._generation.lock_fd, worker._generation.pair_fd)
        monkeypatch.setattr(listener, "_anchored_socket_path", anchored)
        return worker

    monkeypatch.setattr(listener, "bind_worker_listener", bind)
    failure = None
    try:
        try:
            with direct_broker(channel, monkeypatch) as (returned_spec, worker, _state, _sockets):
                assert returned_spec is spec and worker is captured["worker"]
                assert observed == [worker._endpoint_fd]
                assert os.fstat(observed[0]).st_ino == root.endpoint_path.stat().st_ino
        except BaseException as error:
            failure = error
        assert failure is None, failure
        assert captured["worker"].closed
        for fd in captured["fds"]:
            assert_closed(fd)
        assert_unlocked(root)
    finally:
        if "worker" in captured:
            captured["worker"].close()


@pytest.mark.parametrize("control", CONTROLS)
@pytest.mark.parametrize("close_failure", [False, True])
def test_direct_broker_setup_failure_preserves_primary_and_closes_worker(channel, monkeypatch, control, close_failure):
    root, _spec = channel
    primary = control("post-bind setup")
    original_bind, original_close = listener.bind_worker_listener, listener.WorkerListener.close
    captured, calls = {}, []

    def bind(*args, **kwargs):
        worker = original_bind(*args, **kwargs)
        captured["worker"] = worker
        captured["fds"] = (worker._socket.fileno(), worker._endpoint_fd,
            worker._listener_lock_fd, worker._generation.endpoint_fd,
            worker._generation.lock_fd, worker._generation.pair_fd)
        monkeypatch.setattr(listener, "_anchored_socket_path", lambda *a: fail(primary))
        return worker

    def close(worker):
        if worker is captured.get("worker"):
            calls.append(worker)
        original_close(worker)
        if close_failure and worker is captured.get("worker"):
            fail(ControlStop("secondary cleanup"))

    monkeypatch.setattr(listener, "bind_worker_listener", bind)
    monkeypatch.setattr(listener.WorkerListener, "close", close)
    try:
        with pytest.raises(BaseException) as caught:
            with direct_broker(channel, monkeypatch):
                pytest.fail("setup failure must prevent fixture return")
        assert caught.value is primary
        assert calls == [captured["worker"]]
        assert captured["worker"].closed and captured["worker"]._generation.closed
        for fd in captured["fds"]:
            assert_closed(fd)
        assert not root.listener_path.exists()
        assert not root.socket_path(channel[1].socket_name).exists()
        assert_unlocked(root)
    finally:
        if "worker" in captured:
            original_close(captured["worker"])
