"""Real descriptor checkpoints; synthetic ownership is not native qualification."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import publication as p
from app.tests.support.inode_pins import pinned_fds
from app.tests.test_provider_publication import (
    digest_of,
    final_path,
    opened,
    publisher,
    wire_pair,
)
from app.tests.test_provider_publication import (
    pub_tree as pub_tree,  # noqa: PLC0414 - pytest fixture registration
)


class Stop(BaseException):
    pass


@pytest.fixture
def helper_directory(tmp_path, monkeypatch):
    tmp_path.chmod(0o750)
    raw_stat, raw_fstat = os.stat, os.fstat
    ownership = {}

    def observed(info):
        uid, gid = ownership.get((info.st_dev, info.st_ino), (20102, 21201))
        return SimpleNamespace(
            **{
                **{
                    key: getattr(info, key)
                    for key in dir(info)
                    if key.startswith("st_")
                },
                "st_uid": uid,
                "st_gid": gid,
            }
        )

    monkeypatch.setattr(f, "stat_fd", lambda fd: observed(raw_fstat(fd)))
    monkeypatch.setattr(
        f,
        "stat_at",
        lambda fd, name: observed(raw_stat(name, dir_fd=fd, follow_symlinks=False)),
    )

    def chown(fd, uid, gid):
        info = raw_fstat(fd)
        ownership[(info.st_dev, info.st_ino)] = (20102, gid)

    monkeypatch.setattr(os, "fchown", chown)
    directory = f.Directory.open(tmp_path, uid=20102, gid=21201, mode=0o750)
    yield directory
    directory.close()


def test_old_helpers_characterize_bytes_modes_fsync_and_stage_remnant(
    helper_directory, monkeypatch
):
    directory = helper_directory
    events = []
    write, chown, chmod, fsync = p._write_all, os.fchown, os.fchmod, os.fsync

    def writing(fd, raw):
        events.append(("write", os.fstat(fd).st_mode & 0o777))
        write(fd, raw)

    def owning(fd, uid, gid):
        events.append(("chown", uid, gid))
        chown(fd, uid, gid)

    def mode(fd, value):
        events.append(("chmod", value))
        chmod(fd, value)

    def synced(fd):
        events.append(("fsync", fd == directory.fd))
        fsync(fd)

    monkeypatch.setattr(p, "_write_all", writing)
    monkeypatch.setattr(os, "fchown", owning)
    monkeypatch.setattr(os, "fchmod", mode)
    monkeypatch.setattr(os, "fsync", synced)
    stage = p._stage_payload(directory, b"exact wire", policy=f._REQUEST_NAMESPACE)
    assert events == [
        ("write", 0o600),
        ("chown", -1, 21201),
        ("chmod", 0o440),
        ("fsync", False),
    ]
    assert stage.name.startswith(".stage-") and stage.name.endswith(".tmp")
    assert (directory.path / stage.name).read_bytes() == b"exact wire"
    assert stage.signature[0].gid == 21201 and stage.signature[0].mode == 0o440
    stage.close()
    assert (directory.path / stage.name).exists()
    events.clear()
    found = p._existing_for_policy(
        directory, stage.name, b"exact wire", policy=f._REQUEST_NAMESPACE
    )
    assert found == stage.signature[0]
    assert events == [("fsync", False), ("fsync", True)]
    with pytest.raises(c.DeploymentSourceError):
        p._existing_for_policy(
            directory, stage.name, b"different", policy=f._REQUEST_NAMESPACE
        )
    with pytest.raises(c.DeploymentSourceError):
        p._existing_for_policy(
            directory, "missing.json", b"x", policy=f._REQUEST_NAMESPACE
        )


def test_old_helpers_characterize_write_error_leaves_stage(
    helper_directory, monkeypatch
):
    error = OSError("synthetic failure")
    monkeypatch.setattr(p, "_write_all", lambda *_: (_ for _ in ()).throw(error))
    with pytest.raises(OSError) as caught:
        p._stage_payload(helper_directory, b"wire", policy=f._REQUEST_NAMESPACE)
    assert caught.value is error
    paths = tuple(helper_directory.path.iterdir())
    assert len(paths) == 1 and paths[0].read_bytes() == b""
    assert paths[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
@pytest.mark.parametrize(
    "checkpoint",
    [
        "read",
        "stat",
        "fsync",
        "mismatch",
        "post_read_stat",
        "post_sync_stat",
        "closing_fd",
        "return_identity",
        "directory_fsync",
    ],
)
def test_existing_primary_survives_real_fd_cleanup_failure(
    helper_directory, monkeypatch, kind, checkpoint
):
    path = helper_directory.path / ("a" * 64 + ".json")
    path.write_bytes(b"wire")
    path.chmod(0o440)
    primary = kind("primary")
    closed = []
    close, stat_fd = f.close_fd, f.stat_fd

    def cleanup(fd):
        if fd != helper_directory.fd and fd >= 0:
            closed.append(fd)
            close(fd)
            raise Stop("secondary")
        close(fd)

    def fail(*args, **kwargs):
        raise primary

    monkeypatch.setattr(f, "close_fd", cleanup)
    if checkpoint == "read":
        monkeypatch.setattr(f, "read_exact", fail)
    elif checkpoint in ("stat", "closing_fd", "return_identity"):
        calls = 0

        def stated(fd):
            nonlocal calls
            calls += 1
            if calls == {"stat": 2, "closing_fd": 3, "return_identity": 4}[checkpoint]:
                raise primary
            return stat_fd(fd)

        monkeypatch.setattr(f, "stat_fd", stated)
    elif checkpoint == "fsync":
        monkeypatch.setattr(os, "fsync", fail)
    elif checkpoint in ("post_read_stat", "post_sync_stat", "directory_fsync"):
        calls = 0
        target, name = (
            (os, "fsync") if checkpoint == "directory_fsync" else (f, "stat_at")
        )
        original = getattr(target, name)

        def checked(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (1 if checkpoint == "post_read_stat" else 2):
                raise primary
            return original(*args, **kwargs)

        monkeypatch.setattr(target, name, checked)
    else:
        # Raise at the mismatch/error constructor checkpoint after a real read.
        monkeypatch.setattr(c, "DeploymentSourceError", lambda: primary)
    with pytest.raises(kind) as caught:
        p._existing_for_policy(
            helper_directory,
            path.name,
            b"wrong" if checkpoint == "mismatch" else b"wire",
            policy=f._REQUEST_NAMESPACE,
        )
    assert caught.value is primary
    assert len(closed) == 1
    with pytest.raises(OSError):
        os.fstat(closed[0])


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
@pytest.mark.parametrize(
    "checkpoint",
    ["write", "chown", "chmod", "fsync", "stat", "validation", "signature", "owner"],
)
def test_stage_primary_survives_real_fd_cleanup_failure(
    helper_directory, monkeypatch, kind, checkpoint
):
    primary = kind("primary")
    closed = []
    close = f.close_fd

    def cleanup(fd):
        if fd >= 0 and fd != helper_directory.fd:
            closed.append(fd)
            close(fd)
            raise Stop("secondary")
        close(fd)

    def fail(*args, **kwargs):
        raise primary

    monkeypatch.setattr(f, "close_fd", cleanup)
    target, name = {
        "write": (p, "_write_all"),
        "chown": (os, "fchown"),
        "chmod": (os, "fchmod"),
        "fsync": (os, "fsync"),
        "stat": (f, "stat_fd"),
        "validation": (f, "validate_regular"),
        "signature": (f, "stat_at"),
        "owner": (p, "_StagedFile"),
    }[checkpoint]
    monkeypatch.setattr(target, name, fail)
    with pytest.raises(kind) as caught:
        p._stage_payload(helper_directory, b"wire", policy=f._REQUEST_NAMESPACE)
    assert caught.value is primary
    assert len(closed) == 1
    with pytest.raises(OSError):
        os.fstat(closed[0])


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
@pytest.mark.parametrize("number", [1, 2, 3])
def test_factory_acquisition_failure_closes_only_owned_directories(
    pub_tree, monkeypatch, kind, number
):
    module = publisher()
    context = pub_tree.open()
    baseline = set(pub_tree.live)
    primary = kind("acquisition")
    open_dir, close_dir = f.Directory.open.__func__, f.Directory.close
    acquired, closed, calls = [], [], []

    def opening(cls, path, **kwargs):
        calls.append(path)
        if len(calls) == number:
            raise primary
        result = open_dir(cls, path, **kwargs)
        acquired.append(result)
        return result

    def closing(directory):
        closed.append(directory)
        close_dir(directory)
        if directory in acquired:
            raise Stop("cleanup")

    monkeypatch.setattr(f.Directory, "open", classmethod(opening))
    monkeypatch.setattr(f.Directory, "close", closing)
    try:
        with pytest.raises(kind) as caught:
            module.open_provider_outbox_lease(
                context, profile=pub_tree.profile, expected_payloads=wire_pair()
            )
        assert caught.value is primary
        assert closed == list(reversed(acquired))
        assert pub_tree.live == baseline
        assert context.read_current() == pub_tree.bundle
    finally:
        context.close()


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
@pytest.mark.parametrize(
    "checkpoint", ["stage_write", "commit_syscall", "commit_read", "observe_read"]
)
def test_operation_process_control_closes_lease_preserves_primary_and_borrowed_context(
    pub_tree, monkeypatch, kind, checkpoint
):
    context, lease = opened(pub_tree)
    digest = digest_of(wire_pair())
    baseline = len(pub_tree.live) - 3
    primary = kind("operation")

    def fail(*args, **kwargs):
        raise primary

    if checkpoint == "stage_write":
        monkeypatch.setattr(p, "_write_all", fail)
        action = lambda: lease.stage(role="request", request_digest=digest)
    else:
        attempt = lease.stage(role="request", request_digest=digest)
        if checkpoint == "observe_read":
            lease.commit(attempt)
            action = lambda: lease.observe_existing(
                role="request", request_digest=digest
            )
        else:
            action = lambda: lease.commit(attempt)
        if checkpoint == "commit_syscall":
            monkeypatch.setattr(p, "_rename_noreplace", fail)
        else:
            read_exact = f.read_exact

            def reading(fd, cap):
                if (
                    pub_tree.paths[fd].suffix == ".json"
                    and "provider-deployment-outbox" in pub_tree.paths[fd].parts
                ):
                    raise primary
                return read_exact(fd, cap)

            monkeypatch.setattr(f, "read_exact", reading)
    close = f.Directory.close
    closed = []

    def closing(directory):
        close(directory)
        if directory in lease._directories:
            closed.append(directory)
            raise Stop("secondary directory cleanup")

    monkeypatch.setattr(f.Directory, "close", closing)
    try:
        with pytest.raises(kind) as caught:
            action()
        assert caught.value is primary
        assert closed == list(reversed(lease._directories))
        assert lease._active is None and lease._closed
        assert len(pub_tree.live) == baseline
        assert context.read_current() == pub_tree.bundle
    finally:
        lease.close()
        context.close()
    assert not pub_tree.live


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
def test_commit_success_cleanup_control_failure_closes_remaining_lease(
    pub_tree, monkeypatch, kind
):
    context, lease = opened(pub_tree)
    digest = digest_of(wire_pair())
    attempt = lease.stage(role="request", request_digest=digest)
    primary = kind("stage close")
    close = f.close_fd

    def closing(fd):
        close(fd)
        if fd == attempt._stage.fd and not lease._closed:
            raise primary

    monkeypatch.setattr(f, "close_fd", closing)
    try:
        with pytest.raises(kind) as caught:
            lease.commit(attempt)
        assert caught.value is primary
        assert lease._closed and lease._active is None
        assert final_path(pub_tree, "request", digest).read_bytes() == wire_pair()[0][1]
        assert context.read_current() == pub_tree.bundle
    finally:
        lease.close()
        context.close()


def test_aggregate_close_attempts_every_child_and_propagates_first(
    pub_tree, monkeypatch
):
    context, lease = opened(pub_tree)
    attempt = lease.stage(role="request", request_digest=digest_of(wire_pair()))
    owned = [
        attempt._stage.fd,
        *(directory.fd for directory in reversed(lease._directories)),
    ]
    close, calls = f.close_fd, []
    primary = Stop("first cleanup")

    def closing(fd):
        close(fd)
        if fd in owned and fd not in calls:
            calls.append(fd)
            raise primary if fd == owned[0] else Stop("later")

    monkeypatch.setattr(f, "close_fd", closing)
    with pytest.raises(Stop) as caught:
        lease.close()
    assert caught.value is primary and calls == owned
    lease.close()
    attempt.close()
    assert calls == owned
    assert context.read_current() == pub_tree.bundle
    context.close()
    assert not pub_tree.live


def test_physical_close_refusal_is_not_reported_as_descriptor_release(
    pub_tree, monkeypatch
):
    context, lease = opened(pub_tree)
    attempt = lease.stage(role="request", request_digest=digest_of(wire_pair()))
    refused = attempt._stage.fd
    close, calls = f.close_fd, []

    def closing(fd):
        calls.append(fd)
        if fd == refused:
            raise Stop("physical refusal")
        close(fd)

    monkeypatch.setattr(f, "close_fd", closing)
    with pytest.raises(Stop):
        lease.close()
    assert os.fstat(refused).st_size > 0
    assert all(directory._closed for directory in lease._directories)
    assert calls.count(refused) == 1
    # The test owns deliberate refusal recovery; production never retries close.
    close(refused)
    context.close()
    assert not pub_tree.live


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
def test_borrowed_context_self_cleanup_remains_authoritative_on_its_guard_interruption(
    pub_tree, monkeypatch, kind
):
    context, lease = opened(pub_tree)
    primary = kind("source guard")
    monkeypatch.setattr(
        publisher().m, "native_platform", lambda: (_ for _ in ()).throw(primary)
    )
    with pytest.raises(kind) as caught:
        lease.observe_existing(role="request", request_digest=digest_of(wire_pair()))
    assert caught.value is primary
    assert context._closed and lease._closed
    assert not pub_tree.live


@pytest.mark.parametrize("protected_count", [0, 64])
def test_measured_persistent_and_transient_fd_peaks(
    pub_tree, monkeypatch, protected_count
):
    caller_baseline = len(os.listdir("/dev/fd")) - 1 - len(pinned_fds())
    roots = tuple(Path(f"/protected/p{number}") for number in range(protected_count))
    for path in roots:
        pub_tree.directory(path, 20102, 20102)
        pub_tree.mount(path, False)
    context = pub_tree.open(protected_roots=roots)
    context_owned = len(pub_tree.live)
    context_peak = pub_tree.peak
    pub_tree.peak = context_owned
    lease = publisher().open_provider_outbox_lease(
        context, profile=pub_tree.profile, expected_payloads=wire_pair()
    )
    assert len(pub_tree.live) == context_owned + 3
    digest = digest_of(wire_pair())
    attempt = lease.stage(role="request", request_digest=digest)
    assert len(pub_tree.live) == context_owned + 4
    open_regular = f.open_regular
    read_additions = []

    def opening(fd, name, **kwargs):
        result = open_regular(fd, name, **kwargs)
        if "provider-deployment-outbox" in pub_tree.paths[fd].parts:
            read_additions.append(len(pub_tree.live) - context_owned)
        return result

    monkeypatch.setattr(f, "open_regular", opening)
    lease.commit(attempt)
    lease.observe_existing(role="request", request_digest=digest)
    assert read_additions == [5, 4]
    assert len(pub_tree.live) == context_owned + 3
    peak = pub_tree.peak
    assert peak + caller_baseline <= 256
    lease.close()
    assert len(pub_tree.live) == context_owned
    context.close()
    assert not pub_tree.live
    print(
        f"FD measurement: caller baseline={caller_baseline}, context={context_owned}, context acquisition peak={context_peak}, publisher persistent=3, stage=1, read=1, whole operation transient peak={peak}, total including caller={peak + caller_baseline}, final=0"
    )
