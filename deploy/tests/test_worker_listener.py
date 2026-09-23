from __future__ import annotations

import inspect
import json
import os
import socket
import stat
import sys
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from app.workers import broker, ipc_root, listener


def _pair_gid() -> int:
    for value in os.getgroups():
        if value not in {0, os.getegid()}:
            return value
    if os.geteuid() == 0:
        return 21_161
    pytest.skip("a distinct supplemental test group is unavailable")


@pytest.fixture
def channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[ipc_root.PairRootSpec, broker.ChannelSpec]]:
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
    spec = broker.ChannelSpec(
        channel_id="control-browser",
        requester_service="control",
        responder_service="browser",
        request_direction="control-to-browser",
        protocol_id="browser-command-v1",
        requester_uid=21_164,
        requester_gid=21_165,
        responder_uid=responder_uid,
        responder_gid=responder_gid,
        pair_gid=pair_gid,
        pair_root=root.endpoint_path,
        socket_name="worker.sock",
        root_uid=responder_uid,
        root_gid=pair_gid,
        socket_uid=responder_uid,
        socket_gid=pair_gid,
        requester_message_types=("cancel", "execute"),
        responder_message_types=("failed", "result"),
        max_queue_depth=2,
    )
    monkeypatch.setattr(
        listener,
        "_process_identity",
        lambda: (responder_uid, responder_gid, frozenset({pair_gid})),
    )
    socket_alias_root: Path | None = None
    if sys.platform != "linux":
        # Darwin's AF_UNIX path limit is shorter than pytest's temporary path.
        # The production Linux implementation remains /proc/self/fd anchored.
        socket_alias_root = Path(
            tempfile.mkdtemp(prefix="dt-listener-", dir="/private/tmp")
        )
        socket_alias = socket_alias_root / "endpoint"
        socket_alias.symlink_to(root.endpoint_path, target_is_directory=True)
        monkeypatch.setattr(
            listener,
            "_anchored_socket_path",
            lambda _fd, _pair, name: str(socket_alias / name),
        )
    try:
        yield root, spec
    finally:
        if socket_alias_root is not None:
            (socket_alias_root / "endpoint").unlink(missing_ok=True)
            socket_alias_root.rmdir()


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    info = path.lstat()
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        stat.S_IMODE(info.st_mode),
    )


def test_listener_binds_socket_and_publishes_exact_authenticated_readiness(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    worker = listener.bind_worker_listener(
        root,
        spec,
        responder_boot_id="browser-boot-a",
    )
    try:
        assert worker._socket.fileno() >= 0
        assert worker._socket.type & socket.SOCK_STREAM
        socket_info = root.socket_path(spec.socket_name).lstat()
        assert stat.S_ISSOCK(socket_info.st_mode)
        assert (
            socket_info.st_uid,
            socket_info.st_gid,
            stat.S_IMODE(socket_info.st_mode),
        ) == (
            spec.responder_uid,
            spec.pair_gid,
            0o660,
        )
        readiness = root.listener_path.read_bytes()
        assert readiness == json.dumps(
            json.loads(readiness),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert set(json.loads(readiness)) == {
            "schema_version",
            "protocol_version",
            "channel_spec_sha256",
            "generation_id",
            "responder_boot_id",
            "endpoint",
            "socket",
            "hmac_sha256",
        }
        assert _file_identity(root.listener_path)[2:] == (
            spec.responder_uid,
            spec.pair_gid,
            0o640,
        )
        with listener.verify_listener(root, spec) as verified:
            assert verified.record == worker.record
            assert verified.record.socket.inode == socket_info.st_ino
            assert verified.record.responder_boot_id == "browser-boot-a"
    finally:
        worker.close()
    assert not root.socket_path(spec.socket_name).exists()
    assert not root.listener_path.exists()


def test_active_listener_holds_shared_generation_and_exclusive_listener_locks(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-a"
    )
    try:
        with pytest.raises(ipc_root.IpcRootBusy):
            ipc_root.initialize_pair_root(root, entropy=lambda size: b"b" * size)
        with pytest.raises(listener.ListenerBusy):
            listener.bind_worker_listener(
                root, spec, responder_boot_id="browser-boot-b"
            )
    finally:
        worker.close()


def test_restart_rotates_generation_and_listener_reclaims_only_stale_pair(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    first = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-a"
    )
    first_generation = first.record.generation_id

    # Model an abrupt responder exit: kernel descriptors/locks close, while the
    # pathname socket and authenticated readiness record remain on the volume.
    first._socket.close()
    os.close(first._listener_lock_fd)
    os.close(first._endpoint_fd)
    first._generation.close()
    for pin in first._pins:  # the crash releases the inode pins with every descriptor
        os.close(pin)
    first._closed = True

    rotated = ipc_root.initialize_pair_root(root, entropy=lambda size: b"b" * size)
    assert rotated.generation_id != first_generation
    second = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-b"
    )
    try:
        assert second.record.generation_id == rotated.generation_id
        # Not `inode != first_socket_inode`: once the crash released it, ext4 may
        # hand the freed inode number to the new bind. The new generation's
        # authenticated record is the reclaim proof.
        assert second.record.generation_id != first_generation
        with listener.verify_listener(root, spec) as verified:
            assert verified.record == second.record
    finally:
        second.close()


def test_restart_reconciles_exact_socket_only_crash_residue_under_listener_lock(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    with ipc_root.acquire_generation(root) as generation:
        endpoint_fd = listener._open_endpoint_for_owner(generation, root)
        orphan = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            orphan.bind(
                listener._anchored_socket_path(endpoint_fd, root, spec.socket_name)
            )
            os.chmod(
                spec.socket_name,
                spec.socket_mode,
                dir_fd=endpoint_fd,
                follow_symlinks=False,
            )
            if os.geteuid() == 0:
                os.chown(
                    spec.socket_name,
                    spec.responder_uid,
                    spec.pair_gid,
                    dir_fd=endpoint_fd,
                    follow_symlinks=False,
                )
            assert _file_identity(root.socket_path(spec.socket_name))
        finally:
            orphan.close()
            os.close(endpoint_fd)

    worker = listener.bind_worker_listener(
        root,
        spec,
        responder_boot_id="browser-boot-restarted",
    )
    try:
        # The orphan was removed and a new socket bound; its inode number may be
        # the orphan's reused one (ext4), so the verified record is the proof.
        assert worker.record.responder_boot_id == "browser-boot-restarted"
        with listener.verify_listener(root, spec) as verified:
            assert verified.record == worker.record
    finally:
        worker.close()


@pytest.mark.parametrize("tamper", ["foreign", "symlink", "hardlink", "fifo", "mode"])
def test_socket_only_reconciliation_rejects_non_exact_residue_without_unlink(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
    tamper: str,
) -> None:
    root, spec = channel
    socket_path = root.socket_path(spec.socket_name)
    cleanup: list[Path] = []
    held_socket: socket.socket | None = None
    with ipc_root.acquire_generation(root) as generation:
        endpoint_fd = listener._open_endpoint_for_owner(generation, root)
        try:
            if tamper == "symlink":
                target = root.endpoint_path / "foreign-target.sock"
                held_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                held_socket.bind(
                    listener._anchored_socket_path(
                        endpoint_fd,
                        root,
                        target.name,
                    )
                )
                socket_path.symlink_to(target.name)
                cleanup.append(target)
            elif tamper == "fifo":
                os.mkfifo(socket_path, 0o660)
            else:
                held_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                held_socket.bind(
                    listener._anchored_socket_path(
                        endpoint_fd,
                        root,
                        spec.socket_name,
                    )
                )
                os.chmod(socket_path, 0o600 if tamper == "mode" else 0o660)
                if tamper == "foreign":
                    os.chown(socket_path, -1, spec.responder_gid)
                elif tamper == "hardlink":
                    alias = root.endpoint_path / "socket-hardlink"
                    os.link(socket_path, alias)
                    cleanup.append(alias)
        finally:
            os.close(endpoint_fd)
    before = socket_path.lstat()
    try:
        with pytest.raises(listener.ListenerIntegrityError):
            listener.bind_worker_listener(
                root,
                spec,
                responder_boot_id="browser-boot-restarted",
            )
        after = socket_path.lstat()
        assert (after.st_dev, after.st_ino, after.st_mode, after.st_nlink) == (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
        )
    finally:
        if held_socket is not None:
            held_socket.close()
        socket_path.unlink(missing_ok=True)
        for path in cleanup:
            path.unlink(missing_ok=True)


def test_readiness_only_crash_residue_remains_fail_closed_and_preserved(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    first = listener.bind_worker_listener(
        root,
        spec,
        responder_boot_id="browser-boot-a",
    )
    root.socket_path(spec.socket_name).unlink()
    first._socket.close()
    os.close(first._listener_lock_fd)
    os.close(first._endpoint_fd)
    first._generation.close()
    for pin in first._pins:  # the crash releases the inode pins with every descriptor
        os.close(pin)
    first._closed = True
    readiness_identity = _file_identity(root.listener_path)

    with pytest.raises(listener.ListenerIntegrityError):
        listener.bind_worker_listener(
            root,
            spec,
            responder_boot_id="browser-boot-b",
        )
    assert _file_identity(root.listener_path) == readiness_identity
    root.listener_path.unlink()


@pytest.mark.parametrize("fault", ["post_link", "directory_fsync", "readback"])
def test_publish_failure_rolls_back_only_its_exact_readiness_inode(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    root, spec = channel
    if fault == "post_link":
        real_link = listener.os.link

        def link_then_fail(*args: object, **kwargs: object) -> None:
            real_link(*args, **kwargs)
            raise OSError("synthetic post-link failure")

        monkeypatch.setattr(listener.os, "link", link_then_fail)
    elif fault == "directory_fsync":
        real_fsync = listener.os.fsync

        def fail_publish_fsync(descriptor: int) -> None:
            info = os.fstat(descriptor)
            if stat.S_ISDIR(info.st_mode) and root.listener_path.exists():
                raise OSError("synthetic readiness directory fsync failure")
            real_fsync(descriptor)

        monkeypatch.setattr(listener.os, "fsync", fail_publish_fsync)
    else:
        real_read = listener._read_file_at

        def fail_readback(
            directory_fd: int,
            name: str,
            expected: listener.FileIdentity,
        ) -> bytes:
            if name == ipc_root.LISTENER_NAME:
                raise listener.ListenerIntegrityError()
            return real_read(directory_fd, name, expected)

        monkeypatch.setattr(listener, "_read_file_at", fail_readback)

    with pytest.raises(listener.ListenerIntegrityError):
        listener.bind_worker_listener(root, spec, responder_boot_id="browser-boot-a")

    assert not root.listener_path.exists()
    assert not root.socket_path(spec.socket_name).exists()
    assert not list(root.endpoint_path.glob(".listener.*.tmp"))


def test_accepted_connection_owns_generation_after_listener_close(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, spec = channel
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-a"
    )

    def test_server_handshake(
        sock: socket.socket,
        channel_spec: broker.ChannelSpec,
        secret: broker.BootSecret,
        *,
        requester_boot_id: str,
        responder_boot_id: str,
        deadline: broker.Deadline,
    ) -> broker.AuthenticatedSession:
        return broker._server_handshake_impl(
            sock,
            channel_spec,
            secret,
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            deadline=deadline,
            verify_peer=False,
        )

    monkeypatch.setattr(listener.broker, "server_handshake", test_server_handshake)
    accepted: list[listener.AuthenticatedConnection] = []
    server_errors: list[BaseException] = []

    def accept() -> None:
        try:
            accepted.append(
                worker.accept_authenticated(
                    requester_boot_id="control-boot-a",
                    deadline=broker.Deadline.after_ms(2_000),
                )
            )
        except Exception as error:  # noqa: BLE001 - surface background assertion.
            server_errors.append(error)

    thread = threading.Thread(target=accept)
    thread.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(
        listener._anchored_socket_path(
            worker._endpoint_fd,
            root,
            spec.socket_name,
        )
    )
    with ipc_root.acquire_generation(root) as client_generation:
        client_session = broker._client_handshake_impl(
            client,
            spec,
            client_generation.secret,
            requester_boot_id="control-boot-a",
            responder_boot_id="browser-boot-a",
            deadline=broker.Deadline.after_ms(2_000),
            verify_peer=False,
        )
        client_codec = broker.FrameCodec(
            spec,
            client_session,
            local_service=spec.requester_service,
        )
        client_codec.write(
            client,
            message_id=str(uuid4()),
            correlation_id=None,
            message_type="execute",
            payload=b"buffered-old-generation-frame",
            deadline=broker.Deadline.after_ms(2_000),
        )
    client.close()
    thread.join(2)
    assert not thread.is_alive()
    assert not server_errors
    assert len(accepted) == 1

    connection = accepted[0]
    worker.close()
    try:
        with pytest.raises(ipc_root.IpcRootBusy):
            ipc_root.initialize_pair_root(root, entropy=lambda size: b"b" * size)
        frame = connection.read(deadline=broker.Deadline.after_ms(2_000))
        assert frame.payload == b"buffered-old-generation-frame"
        with pytest.raises(broker.TransportClosed):
            connection.read(deadline=broker.Deadline.after_ms(2_000))
    finally:
        connection.close()
    assert connection.closed
    assert connection.codec_closed
    ipc_root.initialize_pair_root(root, entropy=lambda size: b"b" * size)


@pytest.mark.parametrize("field", ["hmac_sha256", "generation_id", "responder_boot_id"])
def test_readiness_hmac_generation_and_boot_tamper_fail_closed(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
    field: str,
) -> None:
    root, spec = channel
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-a"
    )
    try:
        value = json.loads(root.listener_path.read_bytes())
        value[field] = "0" * 64 if field != "responder_boot_id" else "other-boot"
        root.listener_path.write_bytes(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        os.chmod(root.listener_path, 0o640)
        if os.geteuid() == 0:
            os.chown(root.listener_path, spec.responder_uid, spec.pair_gid)
        with pytest.raises(listener.ListenerIntegrityError):
            listener.verify_listener(root, spec)
    finally:
        worker.close()


def test_wrong_spec_and_noncanonical_or_unknown_readiness_fail_closed(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-a"
    )
    try:
        with pytest.raises(listener.ListenerIntegrityError):
            listener.verify_listener(root, replace(spec, max_queue_depth=3))
        original = root.listener_path.read_bytes()
        root.listener_path.write_bytes(original + b"\n")
        with pytest.raises(listener.ListenerIntegrityError):
            listener.verify_listener(root, spec)
    finally:
        worker.close()


def test_socket_inode_swap_is_rejected_and_close_never_unlinks_replacement(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-a"
    )
    socket_path = root.socket_path(spec.socket_name)
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    socket_path.unlink()
    replacement.bind(
        listener._anchored_socket_path(
            worker._endpoint_fd,
            root,
            spec.socket_name,
        )
    )
    os.chmod(socket_path, 0o660)
    if os.geteuid() == 0:
        os.chown(socket_path, spec.responder_uid, spec.pair_gid)
    replacement_identity = _file_identity(socket_path)
    try:
        with pytest.raises(listener.ListenerIntegrityError):
            listener.verify_listener(root, spec)
        with pytest.raises(listener.ListenerIntegrityError):
            worker.close()
        assert _file_identity(socket_path) == replacement_identity
    finally:
        replacement.close()
        socket_path.unlink(missing_ok=True)


def test_readiness_inode_swap_is_preserved_by_close(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-a"
    )
    root.listener_path.unlink()
    root.listener_path.write_bytes(b"replacement")
    os.chmod(root.listener_path, 0o640)
    if os.geteuid() == 0:
        os.chown(root.listener_path, spec.responder_uid, spec.pair_gid)
    replacement_identity = _file_identity(root.listener_path)
    with pytest.raises(listener.ListenerIntegrityError):
        worker.close()
    assert _file_identity(root.listener_path) == replacement_identity
    root.listener_path.unlink()


def test_wrong_local_primary_identity_fails_before_endpoint_mutation(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, spec = channel
    monkeypatch.setattr(
        listener,
        "_process_identity",
        lambda: (spec.responder_uid + 1, spec.pair_gid, frozenset({spec.pair_gid})),
    )
    with pytest.raises(listener.ListenerIdentityError):
        listener.bind_worker_listener(root, spec, responder_boot_id="browser-boot-a")
    assert not root.socket_path(spec.socket_name).exists()
    assert not root.listener_path.exists()


def test_accept_deadline_is_bounded_and_does_not_mutate_readiness(
    channel: tuple[ipc_root.PairRootSpec, broker.ChannelSpec],
) -> None:
    root, spec = channel
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="browser-boot-a"
    )
    before = root.listener_path.read_bytes()
    try:
        with pytest.raises(broker.DeadlineExceeded):
            worker.accept_authenticated(
                requester_boot_id="control-boot-a",
                deadline=broker.Deadline.after_ms(5),
            )
        assert root.listener_path.read_bytes() == before
    finally:
        worker.close()


def test_listener_public_entrypoints_have_no_peer_or_integrity_bypass() -> None:
    for function in (
        listener.bind_worker_listener,
        listener.verify_listener,
        listener.connect_authenticated,
    ):
        parameters = inspect.signature(function).parameters
        assert "verify_peer" not in parameters
        assert "verify_hmac" not in parameters
        assert "metadata_uid" not in parameters
        assert "challenge_factory" not in parameters
    assert not hasattr(listener.WorkerListener, "accept")
    assert not hasattr(listener.WorkerListener, "socket")
    assert not hasattr(listener.AuthenticatedConnection, "codec")
    assert not hasattr(listener.AuthenticatedConnection, "generation")
    assert not hasattr(listener.AuthenticatedConnection, "socket")
