import copy
import fcntl
import os
import pickle

import pytest

from app.workers import ipc_root
from deploy.tests.test_ipc_root_initializer import layout as layout  # noqa: PLC0414


def acquire(spec):
    assert hasattr(ipc_root, "acquire_generation_metadata"), (
        "Metadata-only lease missing"
    )
    return ipc_root.acquire_generation_metadata(spec)


def test_metadata_lease_holds_real_lock_without_secret_read(layout, monkeypatch):
    ipc_root.initialize_pair_root(layout, entropy=lambda size: b"a" * size)

    def forbidden(*args, **kwargs):
        raise AssertionError("secret bytes read")

    monkeypatch.setattr(ipc_root, "_read_exact_secret", forbidden)
    with acquire(layout) as lease:
        lease.recheck_current()
        assert not hasattr(lease, "secret")
        assert not hasattr(lease, "generation_id")
        with pytest.raises(ipc_root.IpcRootBusy):
            ipc_root.initialize_pair_root(layout)
        for clone in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                clone(lease)
    lease.close()
    with pytest.raises(ipc_root.IpcRootError):
        lease.recheck_current()


@pytest.mark.parametrize("name", ["worker.sock", "listener.json"])
def test_known_endpoint_presence_denies_without_listing(layout, monkeypatch, name):
    ipc_root.initialize_pair_root(layout)
    (layout.endpoint_path / name).touch()
    with pytest.raises(ipc_root.IpcRootError):
        acquire(layout)


@pytest.mark.parametrize(
    "target", ["generation.lock", "boot-secret", "endpoint", "root"]
)
def test_retained_lease_detects_name_replacement(layout, target):
    ipc_root.initialize_pair_root(layout)
    with acquire(layout) as lease:
        path = layout.pair_root if target == "root" else layout.pair_root / target
        path.rename(path.with_name(path.name + ".old"))
        if target in {"endpoint", "root"}:
            path.mkdir()
        else:
            path.write_bytes(b"a" * (32 if target == "boot-secret" else 0))
        with pytest.raises(ipc_root.IpcRootError):
            lease.recheck_current()


@pytest.mark.parametrize(
    "change", ["missing", "mode", "size", "hardlink", "symlink", "exclusive"]
)
def test_invalid_metadata_denied_and_fds_released(layout, change):
    ipc_root.initialize_pair_root(layout)
    path = layout.generation_lock_path
    held = None
    if change == "missing":
        path.unlink()
    elif change == "mode":
        path.chmod(0o600)
    elif change == "size":
        path.write_bytes(b"x")
    elif change == "hardlink":
        os.link(path, path.with_name("extra"))
    elif change == "symlink":
        path.rename(path.with_name("original"))
        path.symlink_to("original")
    else:
        held = os.open(path, os.O_RDONLY)
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(ipc_root.IpcRootError):
            acquire(layout)
    finally:
        if held is not None:
            os.close(held)


def test_permission_denial_is_not_endpoint_absence(layout, monkeypatch):
    ipc_root.initialize_pair_root(layout)
    original = os.stat

    def denied(name, *args, **kwargs):
        if name == "worker.sock":
            raise PermissionError()
        return original(name, *args, **kwargs)

    monkeypatch.setattr(os, "stat", denied)
    with pytest.raises(ipc_root.IpcRootError):
        acquire(layout)


def test_search_only_metadata_never_lists_pair_or_endpoint(layout, monkeypatch):
    ipc_root.initialize_pair_root(layout)

    def forbidden(*args, **kwargs):
        raise AssertionError("search-only directory was listed")

    monkeypatch.setattr(os, "listdir", forbidden)
    with acquire(layout) as lease:
        lease.recheck_current()


def test_failed_context_entry_closes_held_metadata_fds(layout):
    ipc_root.initialize_pair_root(layout)
    lease = acquire(layout)
    (layout.endpoint_path / "listener.json").touch()
    with pytest.raises(ipc_root.IpcRootError):
        lease.__enter__()
    assert lease.closed


def test_metadata_constructor_cannot_create_a_caller_proof():
    with pytest.raises(TypeError):
        ipc_root.MetadataGenerationLease()


def test_failure_during_final_metadata_snapshot_is_sanitized_and_closes_fds(
    layout, monkeypatch
):
    ipc_root.initialize_pair_root(layout)
    original_open, original_close, original_fstat = os.open, os.close, os.fstat
    opened = set()
    endpoints = 0

    def track_open(name, *args, **kwargs):
        nonlocal endpoints
        fd = original_open(name, *args, **kwargs)
        opened.add(fd)
        if name == "endpoint":
            endpoints += 1
        return fd

    def track_close(fd):
        original_close(fd)
        opened.discard(fd)

    def failed_snapshot(fd):
        if endpoints == 2:
            raise OSError("private snapshot detail")
        return original_fstat(fd)

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "close", track_close)
    monkeypatch.setattr(os, "fstat", failed_snapshot)
    with pytest.raises(ipc_root.IpcRootIntegrityError):
        acquire(layout)
    assert opened == set()
